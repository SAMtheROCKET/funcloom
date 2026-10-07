"""List and inspect the top-level statements of a program."""

import ast
from collections import Counter
import re

from funcloom.modular_models import StatementNames, TopStatement
from funcloom.plan_bindings import DYNAMIC_NAMESPACE_NAMES_TUPLE
from funcloom.plan_dispatch import (
    ModuleCodeFacts, collect_scope_facts_none, list_enclosing_parts_list,
    collect_scope_names_info,
)

DEFINITIONS_TUPLE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
COMPREHENSIONS_TUPLE = (ast.ListComp, ast.SetComp, ast.DictComp)
SCOPES_TUPLE = (*DEFINITIONS_TUPLE, ast.Lambda, ast.GeneratorExp,
                *COMPREHENSIONS_TUPLE)
SPECIAL_NAMES_TUPLE = (
    "__file__", "__spec__", "__loader__", "__cached__", "__name__",
)
CAPTURES_TUPLE = (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)


def split_program_lines_list(source_str: str) -> list[str]:
    """Split program text into physical lines the way Python does.

    Args:
        source_str (str): Program text.
    Returns:
        list[str]: Lines without their endings.
    Warnings:
        Unlike str.splitlines, separators such as U+2028 inside strings do
        not end a line.
    """
    lines_list = re.split(r"\r\n|\r|\n", source_str)
    if lines_list and lines_list[-1] == "":
        lines_list.pop()
    return lines_list


def is_plain_main_guard_bool(node: ast.stmt) -> bool:
    """Recognize `if __name__ == "__main__":` without an else branch.

    Args:
        node (ast.stmt): Top-level statement.
    Returns:
        bool: True for the conventional script entry guard.
    Warnings:
        Equivalent but differently spelled conditions are not recognized.
    """
    if not isinstance(node, ast.If) or node.orelse:
        return False
    test_node = node.test
    if not isinstance(test_node, ast.Compare) or len(test_node.ops) != 1:
        return False
    sides_list = [test_node.left, test_node.comparators[0]]
    return isinstance(test_node.ops[0], ast.Eq) and any(
        isinstance(operand_node, ast.Name) and operand_node.id == "__name__"
        for operand_node in sides_list) and any(
        isinstance(operand_node, ast.Constant)
        and operand_node.value == "__main__" for operand_node in sides_list)


def make_top_statement(
    node: ast.stmt, previous_end_int: int, lines_list: list[str],
) -> TopStatement:
    """Locate a statement with its decorators and attached comments.

    Args:
        node (ast.stmt): Statement to place.
        previous_end_int (int): Last line of the previous statement.
        lines_list (list[str]): Program lines, one-based by index + 1.
    Returns:
        TopStatement: Text range, section start and title.
    Warnings:
        Only a comment block directly above the statement is attached.
    """
    first_int = min(
        [node.lineno]
        + [
            decorator_node.lineno
            for decorator_node in getattr(node, "decorator_list", [])])
    code_first_int = first_int
    while first_int - 1 > previous_end_int and lines_list[
        first_int - 2
    ].strip().startswith("#"):
        first_int -= 1
    gap_list = lines_list[previous_end_int:first_int - 1]
    blank_int = sum(1 for line_str in gap_list if not line_str.strip())
    title_str = ""
    if first_int < code_first_int:
        title_str = lines_list[first_int - 1].strip().lstrip("#").strip()
    return TopStatement(
        node, first_int, node.end_lineno, node.col_offset, title=title_str,
        starts_section=bool(title_str) or blank_int >= 2,
        blank_before=blank_int >= 1,
    )


def list_top_statements_list(
    module_node: ast.Module, source_str: str,
) -> list[TopStatement]:
    """List top-level statements, unwrapping a main guard's body.

    Args:
        module_node (ast.Module): Parsed program.
        source_str (str): Program text.
    Returns:
        list[TopStatement]: Statements in source order.
    Warnings:
        The main guard body runs unconditionally from the new main().
    """
    lines_list = split_program_lines_list(source_str)
    statements_list, previous_end_int = [], 0
    for node in module_node.body:
        if is_plain_main_guard_bool(node):
            previous_end_int = node.lineno
            for index_int, inner_node in enumerate(node.body):
                statements_list.append(make_top_statement(
                    inner_node, previous_end_int, lines_list,
                ))
                if index_int == 0:
                    statements_list[-1].starts_section = True
                    statements_list[-1].title = (statements_list[-1].title
                                                 or "Run the main block")
                previous_end_int = inner_node.end_lineno
            continue
        statements_list.append(make_top_statement(
            node, previous_end_int, lines_list,
        ))
        previous_end_int = node.end_lineno
    for top_info in statements_list:
        top_info.names = collect_statement_names_info(top_info.node)
    return statements_list


def record_node_none(node: ast.AST, names_info: StatementNames) -> None:
    """Record one module-scope syntax node's reads and bindings.

    Args:
        node (ast.AST): Node outside any nested scope body.
        names_info (StatementNames): Accumulator.
    Returns:
        None: Updates reads, writes, global declarations and dynamics.
    Warnings:
        Namespace calls are detected by spelling only.
    """
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        names_info.direct_reads.add(node.target.id)
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load):
            names_info.direct_reads.add(node.id)
            if node.id in DYNAMIC_NAMESPACE_NAMES_TUPLE:
                names_info.dynamic_line = (names_info.dynamic_line
                                           or node.lineno)
        else:
            names_info.writes.add(node.id)
            if isinstance(node.ctx, ast.Del):
                names_info.direct_reads.add(node.id)
    elif isinstance(node, ast.alias):
        names_info.writes.add(node.asname or node.name.split(".")[0])
    elif isinstance(node, CAPTURES_TUPLE) and node.name:
        names_info.writes.add(node.name)
    elif isinstance(node, ast.MatchMapping) and node.rest:
        names_info.writes.add(node.rest)
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        names_info.global_writes.update(node.names)


def record_deferred_none(node: ast.AST, names_info: StatementNames) -> None:
    """Record globals that code defined here may read or rebind later.

    Args:
        node (ast.AST): Function, lambda, generator or class method.
        names_info (StatementNames): Accumulator.
    Returns:
        None: Adds nested reads, global writes and dynamic evidence.
    Warnings:
        Closure variables of enclosing functions are excluded.
    """
    facts_info = ModuleCodeFacts()
    collect_scope_facts_none(node, set(), True, facts_info)
    names_info.nested_reads |= set(facts_info.reads)
    names_info.global_writes |= set(facts_info.writes)
    names_info.dynamic_line = (names_info.dynamic_line
                               or facts_info.dynamic_line)


def record_scope_none(node: ast.AST, names_info: StatementNames) -> None:
    """Record a nested scope: immediate bodies read now, others later.

    Args:
        node (ast.AST): Definition, lambda or comprehension.
        names_info (StatementNames): Accumulator.
    Returns:
        None: Updates reads and bindings for the enclosing statement.
    Warnings:
        Class bodies and list/set/dict comprehensions run immediately.
    """
    if hasattr(node, "name"):
        names_info.writes.add(node.name)
    if not isinstance(node, (ast.ClassDef, *COMPREHENSIONS_TUPLE)):
        record_deferred_none(node, names_info)
        return
    scope_info = collect_scope_names_info(node)
    names_info.direct_reads |= scope_info.loads - scope_info.stores
    names_info.dynamic_line = (names_info.dynamic_line
                               or scope_info.dynamic_line)
    names_info.global_writes |= scope_info.globals
    for nested_node in scope_info.nested:
        record_deferred_none(nested_node, names_info)


def collect_statement_names_info(statement_node: ast.stmt) -> StatementNames:
    """Collect what one top-level statement reads, binds and risks.

    Args:
        statement_node (ast.stmt): Top-level statement.
    Returns:
        StatementNames: Direct and deferred reads, writes and hazards.
    Warnings:
        Reads are lexical; attribute and item access are not tracked.
    """
    names_info = StatementNames()
    pending_list: list[ast.AST] = [statement_node]
    while pending_list:
        node = pending_list.pop()
        if isinstance(node, SCOPES_TUPLE):
            record_scope_none(node, names_info)
            parts_list = list_enclosing_parts_list(node)
            if isinstance(node, DEFINITIONS_TUPLE) and any(
                isinstance(inner_node, ast.Call)
                for part in parts_list for inner_node in ast.walk(part)
            ):
                names_info.has_calls_at_definition = True
            pending_list.extend(parts_list)
            continue
        record_node_none(node, names_info)
        pending_list.extend(ast.iter_child_nodes(node))
    for node in ast.walk(statement_node):
        if isinstance(node, ast.Name) and node.id in SPECIAL_NAMES_TUPLE:
            names_info.special_lines.setdefault(node.id, node.lineno)
    return names_info


def count_binding_occurrences_counter(module_node: ast.Module) -> Counter:
    """Count every binding of each name in every scope of the program.

    Args:
        module_node (ast.Module): Parsed program.
    Returns:
        Counter: Name to number of binding sites anywhere.
    Warnings:
        A name bound once in total can be renamed everywhere safely.
    """
    counter_info: Counter = Counter()
    for node in ast.walk(module_node):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            counter_info[node.id] += 1
        elif isinstance(node, ast.arg):
            counter_info[node.arg] += 1
        elif isinstance(node, ast.alias):
            counter_info[node.asname or node.name.split(".")[0]] += 1
        elif isinstance(node, (*DEFINITIONS_TUPLE, *CAPTURES_TUPLE)) and (
            getattr(node, "name", None)
        ):
            counter_info[node.name] += 1
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            counter_info.update(node.names)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            counter_info[node.rest] += 1
    return counter_info
