"""Decide where each top-level statement goes in the generated package."""

import ast

from funcloom.definition_effects import (
    is_definition_effect_free_bool, is_pure_expression_bool,
)
from funcloom.modular_models import ModularReport, TopStatement
from funcloom.modular_models import add_diagnostic_none
from funcloom.modular_scan import DEFINITIONS_TUPLE
from funcloom.modular_scan import count_binding_occurrences_counter

IMMUTABLE_TYPES_TUPLE = (int, float, complex, str, bytes, bool, type(None))
REFUSED_SPECIALS_TUPLE = ("__spec__", "__loader__", "__cached__")


def is_immutable_literal_bool(node: ast.expr) -> bool:
    """Recognize literal values that cannot change after assignment.

    Args:
        node (ast.expr): Assigned value.
    Returns:
        bool: True for numbers, strings, bytes, booleans, None, signed
            numbers and tuples of these.
    Warnings:
        Lists, dicts and sets are mutable and are never constants.
    """
    if isinstance(node, ast.Constant):
        return type(node.value) in IMMUTABLE_TYPES_TUPLE
    if isinstance(node, ast.UnaryOp) and isinstance(
        node.op, (ast.USub, ast.UAdd),
    ):
        return isinstance(node.operand, ast.Constant) and type(
            node.operand.value,
        ) in (int, float, complex)
    return isinstance(node, ast.Tuple) and all(
        is_immutable_literal_bool(element_node) for element_node in node.elts
    )


def find_constant_name_str(node: ast.stmt) -> str | None:
    """Return the name a literal-constant statement binds, if it is one.

    Args:
        node (ast.stmt): Top-level statement.
    Returns:
        str | None: Bound name for `NAME = literal`, otherwise None.
    Warnings:
        Chained, unpacking and augmented assignments are not constants.
    """
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target_node, value_node = node.targets[0], node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target_node, value_node = node.target, node.value
    else:
        return None
    if isinstance(node, ast.AnnAssign) and not is_pure_expression_bool(
        node.annotation,
    ):
        return None
    if isinstance(target_node, ast.Name) and is_immutable_literal_bool(
        value_node,
    ):
        return target_node.id
    return None


def count_binding_keys_dict(statements_list: list[TopStatement]) -> dict:
    """Find how many distinct module-level bindings each name has.

    Args:
        statements_list (list[TopStatement]): Program statements.
    Returns:
        dict: Name to a set of binding keys; identical imports share one.
    Warnings:
        Global declarations in nested code count as extra bindings.
    """
    keys_dict: dict[str, set] = {}
    for index_int, top_info in enumerate(statements_list):
        node = top_info.node
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias_node in node.names:
                name_str = alias_node.asname or alias_node.name.split(".")[0]
                keys_dict.setdefault(name_str, set()).add((
                    "import", getattr(node, "module", None),
                    getattr(node, "level", 0), alias_node.name,
                    alias_node.asname,
                ))
            continue
        for name_str in top_info.names.writes | top_info.names.global_writes:
            keys_dict.setdefault(name_str, set()).add(("stmt", index_int))
    return keys_dict


def classify_leading_kind_str(
    index_int: int, top_info: TopStatement, single_set: set[str],
) -> str:
    """Place a statement that comes before any executable code.

    Args:
        index_int (int): Position in the program.
        top_info (TopStatement): Statement to place.
        single_set (set[str]): Names bound exactly once.
    Returns:
        str: docstring, future, import, constant, definition or executable.
    Warnings:
        A name bound more than once always stays executable, and so does a
        definition whose decorators, defaults, annotations or class body
        could have effects when it is defined.
    """
    node = top_info.node
    if index_int == 0 and isinstance(node, ast.Expr) and isinstance(
        node.value, ast.Constant,
    ) and isinstance(node.value.value, str):
        return "docstring"
    if isinstance(node, ast.ImportFrom) and node.module == "__future__":
        return "future"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import" if top_info.names.writes <= single_set | {
            "*"} else "executable"
    if find_constant_name_str(node) in single_set:
        return "constant"
    return "definition" if isinstance(node, DEFINITIONS_TUPLE) and (
        is_definition_effect_free_bool(node)
    ) else "executable"


def classify_later_kind_str(
    top_info: TopStatement,
) -> str:
    """Place a statement that comes after executable code started.

    Args:
        top_info (TopStatement): Statement to place.
    Returns:
        str: definition or executable.
    Warnings:
        Later imports always stay at their original execution point.
    """
    node = top_info.node
    if isinstance(node, DEFINITIONS_TUPLE) and (
        is_definition_effect_free_bool(node)
    ):
        return "definition"
    return "executable"


def classify_statements_none(
    statements_list: list[TopStatement], report_info: ModularReport,
) -> None:
    """Assign every statement a destination and settle definitions.

    Args:
        statements_list (list[TopStatement]): Program statements.
        report_info (ModularReport): Notes and diagnostics destination.
    Returns:
        None: Sets each statement's kind.
    Warnings:
        Constants are taken only from before the first executable code.
    """
    keys_dict = count_binding_keys_dict(statements_list)
    single_set = {name_str for name_str, key_set in keys_dict.items()
                  if len(key_set) == 1}
    started_bool, imports_open_bool = False, True
    for index_int, top_info in enumerate(statements_list):
        if started_bool:
            top_info.kind = classify_later_kind_str(top_info)
            continue
        top_info.kind = classify_leading_kind_str(
            index_int, top_info, single_set)
        if top_info.kind == "import" and not imports_open_bool:
            top_info.kind = "executable"
        imports_open_bool &= top_info.kind in ("docstring", "future",
                                               "import")
        started_bool = top_info.kind == "executable"
    for top_info in statements_list:
        if isinstance(top_info.node, DEFINITIONS_TUPLE) and (
            not is_definition_effect_free_bool(top_info.node)
        ):
            report_info.notes.append(
                f"'{top_info.node.name}' (line {top_info.node.lineno}) stays "
                "in its original place: defining it runs code (a decorator, "
                "default, annotation or class body statement).")
    settle_definitions_none(statements_list, set(keys_dict), single_set,
                            report_info)


def settle_definitions_none(
    statements_list: list[TopStatement], bound_set: set[str],
    single_set: set[str], report_info: ModularReport,
) -> None:
    """Keep only definitions that do not depend on script state.

    Args:
        statements_list (list[TopStatement]): Classified statements.
        bound_set (set[str]): Every name bound at module level.
        single_set (set[str]): Names bound exactly once.
        report_info (ModularReport): Notes destination.
    Returns:
        None: Turns dependent definitions back into executable code.
    Warnings:
        Repeats until stable, since definitions can depend on each other.
    """
    allowed_set = set().union(*(
        top_info.names.writes for top_info in statements_list
        if top_info.kind in ("import", "future", "constant", "definition")
    ))
    changed_bool = True
    while changed_bool:
        changed_bool = False
        for top_info in statements_list:
            if top_info.kind != "definition":
                continue
            name_str, names_info = top_info.node.name, top_info.names
            bad_set = ((names_info.direct_reads | names_info.nested_reads)
                       & bound_set) - allowed_set - {name_str}
            if bad_set or name_str not in single_set or (
                names_info.global_writes or names_info.dynamic_line
            ):
                top_info.kind, changed_bool = "executable", True
                allowed_set.discard(name_str)
                report_info.notes.append(
                    f"'{name_str}' (line {top_info.node.lineno}) stays in the "
                    "steps because it uses script state: "
                    f"{', '.join(sorted(bad_set)) or 'rebinding or globals'}.")


def choose_constant_names_dict(
    statements_list: list[TopStatement], module_node: ast.Module,
) -> dict[str, str]:
    """Choose UPPER_CASE names for constants where renaming is safe.

    Args:
        statements_list (list[TopStatement]): Classified statements.
        module_node (ast.Module): Parsed program.
    Returns:
        dict[str, str]: Original constant name to generated name.
    Warnings:
        A name bound anywhere else, even as a parameter, keeps its name.
    """
    counter_info = count_binding_occurrences_counter(module_node)
    identifiers_set = set(counter_info) | {
        node.id for node in ast.walk(module_node) if isinstance(node, ast.Name)
    }
    names_dict: dict[str, str] = {}
    for top_info in statements_list:
        if top_info.kind != "constant":
            continue
        name_str = find_constant_name_str(top_info.node)
        upper_str = name_str.upper()
        safe_bool = counter_info[name_str] == 1 and (
            upper_str not in identifiers_set
            and upper_str not in names_dict.values()
        )
        names_dict[name_str] = upper_str if safe_bool else name_str
    return names_dict


def refuse_unsupported_none(
    statements_list: list[TopStatement], report_info: ModularReport,
) -> None:
    """Refuse programs whose meaning depends on being a single script.

    Args:
        statements_list (list[TopStatement]): Classified statements.
        report_info (ModularReport): Diagnostic destination.
    Returns:
        None: Adds MOD002-MOD005 and MOD010 errors and MODW05
            warnings.
    Warnings:
        These refusals protect behavior; they do not judge code quality.
    """
    for top_info in statements_list:
        names_info, line_int = top_info.names, top_info.node.lineno
        executable_bool = top_info.kind == "executable"
        if executable_bool and names_info.dynamic_line is not None:
            add_diagnostic_none(report_info, "MOD002",
                                names_info.dynamic_line,
                                "globals(), locals(), vars(), exec or eval "
                                "would see a function namespace instead of "
                                "the script's.")
        if executable_bool and names_info.global_writes:
            add_diagnostic_none(report_info, "MOD003", line_int, (
                "'global'/'nonlocal' for "
                f"{', '.join(sorted(names_info.global_writes))} would "
                "rebind a different namespace inside a step."))
        wildcard_line_int = find_wildcard_line_int(top_info.node)
        if wildcard_line_int is not None:
            add_diagnostic_none(report_info, "MOD004", wildcard_line_int,
                                "Wildcard import bindings cannot be shared "
                                "without resolving their exports; use "
                                "explicit imports before modularizing.")
        refuse_specials_none(top_info, report_info)
        if executable_bool:
            refuse_module_annotations_none(top_info, report_info)


def find_wildcard_line_int(statement_node: ast.stmt) -> int | None:
    """Find a wildcard import in a top-level statement.

    Args:
        statement_node (ast.stmt): The statement, including nested
            blocks such as `try: from fast import *`.
    Returns:
        int | None: The line of the first `from x import *`, or None.
    Warnings:
        Code in such a block would move into a step function, where a
        wildcard import is not allowed.
    """
    for node in ast.walk(statement_node):
        if isinstance(node, ast.ImportFrom) and any(
                alias_node.name == "*" for alias_node in node.names):
            return node.lineno
    return None


def refuse_module_annotations_none(
    top_info: TopStatement, report_info: ModularReport,
) -> None:
    """Refuse module-level annotations that would stop being evaluated.

    Args:
        top_info (TopStatement): Executable statement moving into a step.
        report_info (ModularReport): Diagnostic destination.
    Returns:
        None: Adds a located MOD010 error for each such annotation.
    Warnings:
        Python evaluates annotations of module-level variables but not of
        local variables, so an annotation with effects (a call) would
        silently stop running inside a step function.
    """
    pending_list: list[ast.AST] = [top_info.node]
    while pending_list:
        node = pending_list.pop()
        if isinstance(node, ast.AnnAssign) and not is_pure_expression_bool(
            node.annotation,
        ):
            add_diagnostic_none(report_info, "MOD010", node.lineno, (
                "This module-level annotation could have effects when it is "
                "evaluated, but annotations of local variables are never "
                "evaluated inside a step function; use a plain assignment "
                "or a comment instead."))
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Lambda)):
            pending_list.extend(ast.iter_child_nodes(node))


def refuse_specials_none(
    top_info: TopStatement, report_info: ModularReport,
) -> None:
    """Refuse file-location names and warn about module-name changes.

    Args:
        top_info (TopStatement): Statement to inspect.
        report_info (ModularReport): Diagnostic destination.
    Returns:
        None: Adds MOD005 errors or MODW05 warnings.
    Warnings:
        In the package, __file__ and __name__ describe the new modules.
    """
    for name_str, line_int in top_info.names.special_lines.items():
        if name_str == "__name__" and top_info.kind == "executable":
            add_diagnostic_none(report_info, "MOD005", line_int, (
                "'__name__' would be the steps module's name instead of "
                "'__main__', changing this code's behavior."))
        elif name_str in REFUSED_SPECIALS_TUPLE:
            add_diagnostic_none(report_info, "MOD005", line_int, (
                f"'{name_str}' would point at a generated module instead of "
                "the original file."))
        elif name_str == "__name__":
            add_diagnostic_none(report_info, "MODW05", line_int, (
                "'__name__' will be the generated module's name, not "
                "'__main__'."), "warning")
