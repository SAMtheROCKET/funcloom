"""Extract syntax facts; never import, evaluate, or execute target code."""

import ast
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tokenize

from funcloom.models import FunctionInfo, ModuleInfo, ParameterInfo


def read_source_tuple(
    source_path: Path, max_bytes_int: int,
) -> tuple[str, str]:
    """Read bounded source bytes and respect Python's encoding cookie.

    Args:
        source_path (Path): Source file to read.
        max_bytes_int (int): Maximum allowed source byte length.
    Returns:
        tuple[str, str]: Decoded source and original-byte SHA-256.
    Raises:
        ValueError: The source exceeds the limit.
    Warnings:
        This does not execute the file or resolve imported modules.
    """
    with source_path.open("rb") as source_file:
        source_bytes = source_file.read(max_bytes_int + 1)
    if len(source_bytes) > max_bytes_int:
        raise ValueError(f"File exceeds {max_bytes_int} byte limit")
    encoding_str, _ = tokenize.detect_encoding(
        BytesIO(source_bytes).readline,
    )
    return source_bytes.decode(encoding_str), sha256(source_bytes).hexdigest()


def render_annotation_str(annotation_node: ast.expr | None) -> str | None:
    """Render a declared annotation as source text.

    Args:
        annotation_node (ast.expr | None): Declared annotation or absence.
    Returns:
        str | None: Normalized syntax text or an unknown declaration.
    Warnings:
        Annotation expressions are never evaluated or type-checked.
    """
    if annotation_node is None:
        return None
    return ast.unparse(annotation_node)


def record_parameter_facts_tuple(
    arguments_node: ast.arguments,
) -> tuple[ParameterInfo, ...]:
    """Record positional, keyword-only, and variadic parameters.

    Args:
        arguments_node (ast.arguments): Parsed function arguments.
    Returns:
        tuple[ParameterInfo, ...]: Parameters in signature order.
    Warnings:
        An annotation is a declaration, not proof of runtime type.
    """
    groups_list = [
        (arguments_node.posonlyargs, "positional_only"),
        (arguments_node.args, "positional_or_keyword"),
        ([arguments_node.vararg] if arguments_node.vararg else [], "vararg"),
        (arguments_node.kwonlyargs, "keyword_only"),
        ([arguments_node.kwarg] if arguments_node.kwarg else [], "kwarg"),
    ]
    return tuple(
        ParameterInfo(
            argument_node.arg, render_annotation_str(argument_node.annotation),
            kind_str, argument_node.lineno,
        )
        for arguments_list, kind_str in groups_list
        for argument_node in arguments_list
    )


class SymbolCollector(ast.NodeVisitor):
    """Track lexical ownership of classes, functions, and nested functions."""

    def __init__(self, module_info: ModuleInfo) -> None:
        """Initialize the module accumulator and lexical scope stack.

        Args:
            module_info (ModuleInfo): Destination for collected facts.
        Returns:
            None: Initializes this visitor instance.
        Warnings:
            Lexical ownership is not full symbol or import resolution.
        """
        self.module_info = module_info
        self.scope_list: list[tuple[str, str]] = []

    def visit_ClassDef(self, class_node: ast.ClassDef) -> None:
        """Record a class and visit its lexical contents.

        Args:
            class_node (ast.ClassDef): Class declaration to inspect.
        Returns:
            None: Appends a qualified class name and nested declarations.
        Warnings:
            Decorators and base classes are not executed.
        """
        name_str = ".".join(
            [item_tuple[0] for item_tuple in self.scope_list]
            + [class_node.name]
        )
        self.module_info.classes.append(name_str)
        self.scope_list.append((class_node.name, "class"))
        self.generic_visit(class_node)
        self.scope_list.pop()

    def visit_FunctionDef(self, function_node: ast.FunctionDef) -> None:
        """Record a synchronous function through the common collector.

        Args:
            function_node (ast.FunctionDef): Function declaration.
        Returns:
            None: Appends facts to the module accumulator.
        Warnings:
            The visitor method name is required by Python's AST API.
        """
        self.collect_function_none(function_node)

    def visit_AsyncFunctionDef(
        self, function_node: ast.AsyncFunctionDef,
    ) -> None:
        """Record an asynchronous function's declarations.

        Args:
            function_node (ast.AsyncFunctionDef): Async declaration.
        Returns:
            None: Appends facts to the module accumulator.
        Warnings:
            No coroutine is created, awaited, or executed.
        """
        self.collect_function_none(function_node)

    def collect_function_none(
        self, function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Record a function's declared contract and source extent.

        Args:
            function_node (ast.FunctionDef | ast.AsyncFunctionDef): Source.
        Returns:
            None: Appends facts and visits nested declarations.
        Warnings:
            The span includes decorators and intervening blank lines.
        """
        first_line_int = min(
            [function_node.lineno]
            + [node.lineno for node in function_node.decorator_list]
        )
        last_line_int = function_node.end_lineno or function_node.lineno
        qualified_name_str = ".".join(
            [item_tuple[0] for item_tuple in self.scope_list]
            + [function_node.name]
        )
        self.module_info.functions.append(FunctionInfo(
            qualified_name=qualified_name_str,
            name=function_node.name,
            line=first_line_int,
            end_line=last_line_int,
            physical_lines=last_line_int - first_line_int + 1,
            is_async=isinstance(function_node, ast.AsyncFunctionDef),
            is_method=bool(self.scope_list)
            and self.scope_list[-1][1] == "class",
            parameters=record_parameter_facts_tuple(function_node.args),
            return_annotation=render_annotation_str(function_node.returns),
            docstring=ast.get_docstring(function_node),
        ))
        self.scope_list.append((function_node.name, "function"))
        self.generic_visit(function_node)
        self.scope_list.pop()


def is_main_guard_bool(statement_node: ast.stmt) -> bool:
    """Recognize exact main-guard equality in either operand order.

    Args:
        statement_node (ast.stmt): Top-level statement to inspect.
    Returns:
        bool: Whether the condition compares __name__ with __main__.
    Warnings:
        Equivalent complex expressions and aliases are not inferred.
    """
    if not isinstance(statement_node, ast.If):
        return False
    test_node = statement_node.test
    if not isinstance(test_node, ast.Compare):
        return False
    if len(test_node.ops) != 1 or not isinstance(test_node.ops[0], ast.Eq):
        return False
    left_node, right_node = test_node.left, test_node.comparators[0]
    pairs_tuple = ((left_node, right_node), (right_node, left_node))
    for name_node, value_node in pairs_tuple:
        if (
            isinstance(name_node, ast.Name) and name_node.id == "__name__"
            and isinstance(value_node, ast.Constant)
            and value_node.value == "__main__"
        ):
            return True
    return False


def parse_module_info(
    source_str: str, relative_path_str: str, source_hash_str: str,
) -> ModuleInfo:
    """Parse and compile source to facts without running its bytecode.

    Args:
        source_str (str): Decoded Python source.
        relative_path_str (str): Path relative to the analysis root.
        source_hash_str (str): Original source-byte fingerprint.
    Returns:
        ModuleInfo: Declared symbols, imports, and top-level boundaries.
    Warnings:
        Imports are syntactic records; no dependency graph is inferred.
    """
    module_node = ast.parse(source_str, filename=relative_path_str)
    compile(module_node, relative_path_str, "exec", dont_inherit=True)
    module_info = ModuleInfo(
        relative_path_str, source_hash_str, len(source_str.splitlines()),
    )
    SymbolCollector(module_info).visit(module_node)
    module_info.imports = [
        ast.unparse(node) for node in ast.walk(module_node)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    for statement_node in module_node.body:
        module_info.statements.append({
            "kind": type(statement_node).__name__,
            "line": statement_node.lineno,
            "end_line": statement_node.end_lineno,
        })
        if is_main_guard_bool(statement_node):
            module_info.main_guards.append({
                "line": statement_node.lineno,
                "physical_lines": (statement_node.end_lineno or 0)
                - statement_node.lineno + 1,
            })
    return module_info
