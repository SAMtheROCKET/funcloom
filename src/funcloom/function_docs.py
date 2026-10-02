"""Add honest docstrings to functions that have none."""

import ast
from copy import deepcopy

from funcloom.function_split import own_nodes_list
from funcloom.modular_scan import split_program_lines_list
from funcloom.snippet_render import escape_doc_lines_list

UNDESCRIBED_STR = "Not described in the original code."


def find_documentable_list(module_node: ast.Module) -> list[tuple]:
    """Find module functions and methods without a docstring.

    Args:
        module_node (ast.Module): Parsed file.
    Returns:
        list[tuple]: (function, owning class or None) pairs.
    Warnings:
        One-line functions and tab-indented bodies are skipped.
    """
    found_list = []
    for node in module_node.body:
        owners_list = [(node, None)] if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)) else (
            [
                (statement_node, node) for statement_node in node.body
                if isinstance(
                    statement_node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if isinstance(node, ast.ClassDef) else [])
        for function_node, class_node in owners_list:
            if ast.get_docstring(function_node, clean=False) is None:
                found_list.append((function_node, class_node))
    return found_list


def own_line_bool(first_node: ast.stmt, lines_list: list[str]) -> bool:
    """Check that a body starts on its own space-indented line.

    Args:
        first_node (ast.stmt): First body statement.
        lines_list (list[str]): Module lines.
    Returns:
        bool: True when only spaces precede it on its line.
    Warnings:
        One-line functions and tab indentation are left unchanged.
    """
    prefix_str = lines_list[first_node.lineno - 1].encode("utf-8")[
        :first_node.col_offset].decode("utf-8")
    return prefix_str == " " * len(prefix_str)


def summarize_function_name_str(
        node: ast.FunctionDef, class_node: ast.ClassDef | None) -> str:
    """Turn a function name into a one-line summary.

    Args:
        node (ast.FunctionDef): Function.
        class_node (ast.ClassDef | None): Owning class.
    Returns:
        str: Sentence such as "Calculate total."
    Warnings:
        Only the name is used; it is not a description of behavior.
    """
    if node.name == "__init__" and class_node is not None:
        return f"Initialize a {class_node.name} instance."
    words_str = node.name.strip("_").replace("_", " ") or node.name
    return words_str[:1].upper() + words_str[1:] + "."


def describe_argument_entries_list(
    node: ast.FunctionDef, class_node: ast.ClassDef | None,
) -> list[str]:
    """Describe each parameter from its name and annotation only.

    Args:
        node (ast.FunctionDef): Function.
        class_node (ast.ClassDef | None): Owning class; self/cls skipped.
    Returns:
        list[str]: One entry per documented parameter.
    Warnings:
        Missing annotations are reported, never guessed.
    """
    arguments_node = node.args
    parameters_list = [*arguments_node.posonlyargs, *arguments_node.args]
    if class_node is not None and parameters_list and (
        parameters_list[0].arg in ("self", "cls")
    ):
        parameters_list = parameters_list[1:]
    entries_list = []
    for prefix_str, argument_node in (
            [("", parameter_node) for parameter_node in parameters_list]
            + ([("*", arguments_node.vararg)] if arguments_node.vararg else [])
            + [
                ("", keyword_parameter_node)
                for keyword_parameter_node in arguments_node.kwonlyargs]
            + ([("**", arguments_node.kwarg)] if arguments_node.kwarg else [])
    ):
        type_str = (
            ast.unparse(argument_node.annotation) if argument_node.annotation
            else "type not annotated")
        entries_list.append(
            f"{prefix_str}{argument_node.arg} ({type_str}): {UNDESCRIBED_STR}")
    return entries_list or ["None: The function takes no arguments."]


def describe_returns_entry_str(node: ast.FunctionDef) -> str:
    """Describe the return value from the annotation and return syntax.

    Args:
        node (ast.FunctionDef): Function.
    Returns:
        str: Returns entry.
    Warnings:
        Generators are described as iterators; values are not guessed.
    """
    own_list = own_nodes_list(node)
    if any(
            isinstance(own_node, (ast.Yield, ast.YieldFrom))
            for own_node in own_list):
        return f"Iterator: Values produced with yield. {UNDESCRIBED_STR}"
    if node.returns is not None:
        return f"{ast.unparse(node.returns)}: {UNDESCRIBED_STR}"
    if not any(isinstance(own_node, ast.Return) and own_node.value is not None
               for own_node in own_list):
        return "None: The function returns no value."
    return f"Value: {UNDESCRIBED_STR}"


def write_docstring_lines_list(
    node: ast.FunctionDef, class_node: ast.ClassDef | None, indent_int: int,
    width_int: int,
) -> list[str]:
    """Write a docstring with Args, Returns and Warnings sections.

    Args:
        node (ast.FunctionDef): Function.
        class_node (ast.ClassDef | None): Owning class.
        indent_int (int): Body indentation.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Indented docstring lines.
    Warnings:
        States only what the signature shows.
    """
    pad_str = " " * indent_int
    lines_list = [
        f'{pad_str}"""{summarize_function_name_str(node, class_node)}', ""]
    for heading_str, entries_list in (
        ("Args", describe_argument_entries_list(node, class_node)),
        ("Returns", [describe_returns_entry_str(node)]),
        ("Warnings", ["Generated by FuncLoom from the signature; describe "
                      "the behavior before relying on it."]),
    ):
        lines_list.append(f"{pad_str}{heading_str}:")
        for entry_str in entries_list:
            wrapped_list = escape_doc_lines_list(
                entry_str, width_int - indent_int - 8)
            lines_list += [f"{pad_str}    {wrapped_list[0]}"] + [
                f"{pad_str}        {wrapped_line_str}"
                for wrapped_line_str in wrapped_list[1:]]
    return lines_list + [f'{pad_str}"""']


def insert_docstrings_tuple(
    source_str: str, width_int: int,
) -> tuple[str, list[str]]:
    """Insert docstrings into functions and methods that have none.

    Args:
        source_str (str): Module text.
        width_int (int): Maximum line length.
    Returns:
        tuple: New text and names of documented functions.
    Warnings:
        The result is verified: removing the new docstrings must give the
        original syntax tree, or the original text is returned.
    """
    try:
        module_node = ast.parse(source_str)
    except SyntaxError:
        return source_str, []
    lines_list = split_program_lines_list(source_str)
    targets_list = [
        target_tuple for target_tuple in find_documentable_list(module_node)
        if own_line_bool(target_tuple[0].body[0], lines_list)]
    for node, class_node in sorted(
            targets_list, key=lambda target_tuple: -target_tuple[0].lineno):
        first_node = node.body[0]
        lines_list[first_node.lineno - 1:first_node.lineno - 1] = (
            write_docstring_lines_list(node, class_node, first_node.col_offset,
                                       width_int))
    new_str = "\n".join(lines_list) + "\n"
    names_list = [
        f"{target_tuple[1].name}.{target_tuple[0].name}" if target_tuple[1]
        else target_tuple[0].name for target_tuple in targets_list]
    if not targets_list or not verify_docstrings_only_bool(
            module_node, new_str, len(targets_list)):
        return source_str, []
    return new_str, names_list


def list_documentable_functions_list(module_node: ast.Module) -> list[ast.AST]:
    """List module functions and methods in source order.

    Args:
        module_node (ast.Module): Parsed module.
    Returns:
        list[ast.AST]: Functions and methods, including documented ones.
    Warnings:
        Nested functions are not included.
    """
    kinds_tuple = (ast.FunctionDef, ast.AsyncFunctionDef)
    return [candidate_node for node in module_node.body
            for candidate_node in ([node] if isinstance(node, kinds_tuple) else
                                   [child for child in node.body
                                    if isinstance(child, kinds_tuple)]
                                   if isinstance(node, ast.ClassDef) else [])]


def verify_docstrings_only_bool(
    old_node: ast.Module, new_str: str, count_int: int,
) -> bool:
    """Check that only docstrings were added.

    Args:
        old_node (ast.Module): Original syntax tree.
        new_str (str): Documented text.
        count_int (int): Number of docstrings added.
    Returns:
        bool: True when removing the added docstrings restores the tree.
    Warnings:
        Functions are paired by position, so repeated names are safe.
    """
    try:
        new_node = ast.parse(new_str)
        compile(new_node, "<documented>", "exec", dont_inherit=True)
    except SyntaxError:
        return False
    stripped_node = deepcopy(new_node)
    old_list, new_list = list_documentable_functions_list(
        old_node), list_documentable_functions_list(stripped_node)
    if len(old_list) != len(new_list):
        return False
    removed_int = 0
    for old_item, new_item in zip(old_list, new_list):
        if ast.get_docstring(old_item, clean=False) is None and (
            ast.get_docstring(new_item, clean=False) is not None
        ):
            new_item.body = new_item.body[1:]
            removed_int += 1
    return removed_int == count_int and ast.dump(stripped_node) == ast.dump(
        old_node)
