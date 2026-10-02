"""Plan splitting the body of a long loop, if or with block in a function.

A function whose length comes from one big compound statement cannot be
cut between its top-level statements. Here the statements inside that
block are cut instead; the block stays in place and calls the helpers.
"""

import ast
from copy import copy

from funcloom.function_split import (
    NESTED_SCOPES_TUPLE, PIECE_TARGET_LINES_INT, SplitPlan,
    cut_balanced_pieces_list, collect_parameter_names_set,
    plan_label_str, settle_reason_str, skip_reason_str,
)
from funcloom.modular_models import StatementNames
from funcloom.modular_scan import collect_statement_names_info
from funcloom.modular_steps import (
    block_bind_set, collect_must_binds_set, collect_walrus_binds_set,
    is_with_body_trusted_bool,
)

BLOCK_TYPES_DICT = {ast.For: "loop", ast.While: "loop", ast.If: "if",
                    ast.With: "with"}


def loop_jump_bool(statements_list: list[ast.stmt]) -> bool:
    """Tell whether statements break or continue their enclosing loop.

    Args:
        statements_list (list[ast.stmt]): Loop body statements.
    Returns:
        bool: True when a break or continue belongs to that loop.
    Warnings:
        Jumps inside nested loops belong to those loops, except in their
        else blocks, which run in the enclosing loop.
    """
    pending_list: list[ast.AST] = list(statements_list)
    while pending_list:
        node = pending_list.pop()
        if isinstance(node, (ast.Break, ast.Continue)):
            return True
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            pending_list.extend(node.orelse)
        elif not isinstance(node, NESTED_SCOPES_TUPLE):
            pending_list.extend(ast.iter_child_nodes(node))
    return False


def block_candidates_list(node: ast.FunctionDef) -> list[tuple]:
    """List long blocks of a function's top-level statements.

    Args:
        node (ast.FunctionDef): Function.
    Returns:
        list[tuple]: (body index, block field, helper infix), longest
            block first.
    Warnings:
        Async loops and with statements are not candidates.
    """
    found_list = []
    for index_int, statement_node in enumerate(node.body):
        infix_str = BLOCK_TYPES_DICT.get(type(statement_node))
        if infix_str is None:
            continue
        fields_list = [("body", infix_str)]
        if isinstance(statement_node, ast.If) and statement_node.orelse:
            fields_list.append(("orelse", "else"))
        for field_str, name_str in fields_list:
            block_list = getattr(statement_node, field_str)
            span_int = block_list[-1].end_lineno - block_list[0].lineno + 1
            if len(block_list) > 1 and span_int > PIECE_TARGET_LINES_INT:
                found_list.append((-span_int, index_int, field_str,
                                   name_str))
    return [found_tuple[1:] for found_tuple in sorted(found_list)]


def describe_header_names_tuple(
    statement_node: ast.stmt, field_str: str,
) -> tuple[StatementNames, set[str]]:
    """Describe the statement header that runs before a block.

    Args:
        statement_node (ast.stmt): Loop, if or with statement.
        field_str (str): "body" or "orelse".
    Returns:
        tuple: Names of the header alone, and names it certainly binds
            before the block runs.
    Warnings:
        Walrus bindings count only where the test always evaluates them.
    """
    stub_node = copy(statement_node)
    stub_node.body = [ast.copy_location(ast.Pass(), statement_node)]
    if hasattr(stub_node, "orelse"):
        stub_node.orelse = []
    certain_set = set()
    if isinstance(statement_node, ast.For):
        certain_set = {
            inner_node.id for inner_node in ast.walk(statement_node.target)
            if isinstance(inner_node, ast.Name)} | collect_walrus_binds_set(
            statement_node.iter)
    elif isinstance(statement_node, ast.With):
        certain_set = collect_must_binds_set(stub_node)
    else:
        certain_set = collect_walrus_binds_set(statement_node.test)
    return collect_statement_names_info(stub_node), certain_set


def block_layout_reason_str(
    statement_node: ast.stmt, block_list: list[ast.stmt],
    lines_list: list[str],
) -> str | None:
    """Explain why a block's text cannot be replaced, or return None.

    Args:
        statement_node (ast.stmt): Statement owning the block.
        block_list (list[ast.stmt]): Block to split.
        lines_list (list[str]): Module lines.
    Returns:
        str | None: Reason, or None when every statement has its own
            lines and the loop is not left early.
    Warnings:
        break and continue cannot leave a helper function.
    """
    first_node = block_list[0]
    prefix_bytes = lines_list[first_node.lineno - 1].encode("utf-8")[
        :first_node.col_offset]
    if prefix_bytes.strip() or any(
        current_node.lineno == previous.end_lineno
        for previous, current_node in zip(block_list, block_list[1:])
    ):
        return "its statements share lines"
    if isinstance(statement_node, (ast.For, ast.While)) and loop_jump_bool(
        block_list,
    ):
        return "it uses break or continue"
    return None


def unite_names_set(infos_list: list[StatementNames], *fields: str) -> set:
    """Unite name sets of several statements.

    Args:
        infos_list (list[StatementNames]): Statement names.
        *fields (str): Fields to unite, such as "writes".
    Returns:
        set: Every name in those fields.
    Warnings:
        Order is lost; callers sort where order matters.
    """
    return set().union(*(
        getattr(names_info, field_str) for names_info in infos_list
        for field_str in fields))


def describe_region_parts_tuple(
    node: ast.FunctionDef, index_int: int, field_str: str,
) -> tuple[dict[str, list[StatementNames]], set[str]]:
    """Describe the names used around and inside one block.

    Args:
        node (ast.FunctionDef): Function owning the block.
        index_int (int): Index of the block's statement in the body.
        field_str (str): "body" or "orelse".
    Returns:
        tuple: Names of the statements "before" and "after" it, its
            "header", loop "rest" (else block) and "inside"; and the
            names the header certainly binds.
    Warnings:
        Reads are lexical, as everywhere in FuncLoom.
    """
    statement_node = node.body[index_int]
    header_info, header_set = describe_header_names_tuple(
        statement_node, field_str)
    loop_bool = isinstance(statement_node, (ast.For, ast.While))
    return {
        "before": [
            collect_statement_names_info(statement_node)
            for statement_node in node.body[:index_int]],
        "after": [
            collect_statement_names_info(statement_node)
            for statement_node in node.body[index_int + 1:]],
        "header": [header_info],
        "inside": [
            collect_statement_names_info(block_statement_node)
            for block_statement_node in getattr(statement_node, field_str)],
        "rest": [
            collect_statement_names_info(orelse_statement_node)
            for orelse_statement_node
            in (statement_node.orelse if loop_bool else [])]}, header_set


def explain_region_reason_str(
    statement_node: ast.stmt, parts_dict: dict[str, list[StatementNames]],
    after_set: set[str],
) -> str | None:
    """Explain why moving a block's code would change behavior.

    Args:
        statement_node (ast.stmt): Statement owning the block.
        parts_dict (dict): Names of the statements "before" and "after"
            it, its "header", loop "rest" (else block) and "inside".
        after_set (set[str]): Names read after the block.
    Returns:
        str | None: Reason, or None when the block may be split.
    Warnings:
        Closures see a helper's own variables, not the function's, so
        closures that would observe a later change keep it whole.
    """
    loop_bool = isinstance(statement_node, (ast.For, ast.While))
    inside_writes_set = unite_names_set(parts_dict["inside"], "writes")
    late_set = unite_names_set(parts_dict["after"], "writes")
    if loop_bool:
        late_set |= inside_writes_set | unite_names_set(
            parts_dict["header"] + parts_dict["rest"], "writes")
    if unite_names_set(parts_dict["inside"], "nested_reads") & late_set:
        return "code defined in it reads a value that changes later"
    if unite_names_set(parts_dict["before"] + parts_dict["header"],
                       "nested_reads") & inside_writes_set:
        return "code defined before it reads a value it changes"
    if isinstance(statement_node, ast.With) and (
        inside_writes_set & after_set
    ) and not is_with_body_trusted_bool(statement_node):
        return "values it binds are used after it and a with block may stop"
    return None


def plan_region_split_tuple(
    node: ast.FunctionDef, class_node: ast.ClassDef | None,
    candidate_tuple: tuple, lines_list: list[str],
) -> tuple[SplitPlan | None, str]:
    """Plan the split of one block, or explain why it cannot be split.

    Args:
        node (ast.FunctionDef): Function owning the block.
        class_node (ast.ClassDef | None): Owning class for methods.
        candidate_tuple (tuple): (body index, block field, helper infix).
        lines_list (list[str]): Module lines.
    Returns:
        tuple: Plan or None, and the reason when it is None.
    Warnings:
        In a loop, every round passes values in and out of the helpers.
    """
    index_int, field_str, infix_str = candidate_tuple
    statement_node = node.body[index_int]
    block_list = getattr(statement_node, field_str)
    reason_str = block_layout_reason_str(statement_node, block_list,
                                         lines_list)
    if reason_str is not None:
        return None, reason_str
    parts_dict, header_set = describe_region_parts_tuple(
        node, index_int, field_str)
    after_set = unite_names_set(parts_dict["after"] + parts_dict["rest"] + (
        parts_dict["header"] if isinstance(statement_node, ast.While)
        else []), "direct_reads", "nested_reads")
    reason_str = explain_region_reason_str(
        statement_node, parts_dict, after_set)
    if reason_str is not None:
        return None, reason_str
    plan_info = build_block_plan_info(node, class_node, candidate_tuple,
                                      parts_dict, (header_set, after_set))
    plan_info.pieces = cut_balanced_pieces_list(
        block_list, plan_info.header_int, plan_info.before, 40)
    reason_str = settle_reason_str(plan_info)
    return (None, reason_str) if reason_str else (plan_info, "")


def build_block_plan_info(
    node: ast.FunctionDef, class_node: ast.ClassDef | None,
    candidate_tuple: tuple, parts_dict: dict, names_tuple: tuple,
) -> SplitPlan:
    """Create the split plan of one block, before it is cut into pieces.

    Args:
        node (ast.FunctionDef): Function owning the block.
        class_node (ast.ClassDef | None): Owning class for methods.
        candidate_tuple (tuple): (body index, block field, helper infix).
        parts_dict (dict): Name facts around and inside the block.
        names_tuple (tuple): (names bound by the header, names read after).
    Returns:
        SplitPlan: Plan with its name sets and block position.
    Warnings:
        In a loop, values written inside are unstable between rounds.
    """
    index_int, field_str, infix_str = candidate_tuple
    header_set, after_set = names_tuple
    statement_node = node.body[index_int]
    block_list = getattr(statement_node, field_str)
    loop_bool = isinstance(statement_node, (ast.For, ast.While))
    parameters_set = collect_parameter_names_set(node)
    before_set = parameters_set | unite_names_set(
        parts_dict["before"] + parts_dict["header"], "writes")
    inside_set = (unite_names_set(parts_dict["inside"], "writes")
                  if loop_bool else set())
    locals_set = parameters_set.union(*(
        collect_statement_names_info(body_node).writes
        for body_node in node.body))
    certain_set = (parameters_set | header_set
                   | block_bind_set(node.body[:index_int]))
    return SplitPlan(
        node, class_node, parameters_set, before=before_set,
        certain=certain_set, after_reads=after_set, locals=locals_set,
        unstable=before_set - parameters_set | inside_set,
        loop_bool=loop_bool, header_int=block_list[0].lineno - 1,
        end_int=block_list[-1].end_lineno,
        indent_int=block_list[0].col_offset, owner_index=index_int,
        block_field=field_str, infix=infix_str)


def plan_block_tuple(
    node: ast.FunctionDef, class_node: ast.ClassDef | None,
    lines_list: list[str],
) -> tuple[SplitPlan | None, str]:
    """Plan the split of a function's longest block that can be split.

    Args:
        node (ast.FunctionDef): Long function.
        class_node (ast.ClassDef | None): Owning class for methods.
        lines_list (list[str]): Module lines.
    Returns:
        tuple: Plan or None, and why the longest block was refused (empty
            when the function has no long block).
    Warnings:
        Used when the function's own statements cannot be split.
    """
    if skip_reason_str(node, class_node) is not None:
        return None, ""
    first_reason_str = ""
    for candidate_tuple in block_candidates_list(node):
        plan_info, reason_str = plan_region_split_tuple(node, class_node,
                                                        candidate_tuple,
                                                        lines_list)
        if plan_info is not None:
            return plan_info, ""
        if not first_reason_str:
            label_str = plan_label_str(SplitPlan(
                node, None, set(), infix=candidate_tuple[2]))
            first_reason_str = (f"its {label_str.rsplit('(', 1)[1][:-1]} "
                                f"was not split either: {reason_str}")
    return None, first_reason_str
