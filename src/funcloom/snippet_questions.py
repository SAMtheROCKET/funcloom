"""Review questions about source ambiguities without repairing user intent."""

import ast

from funcloom.plan_analysis import split_assignment_parts_tuple
from funcloom.snippet_models import SnippetQuestion, SnippetReport


def record_source_questions_none(
    module_node: ast.Module, report_info: SnippetReport,
) -> None:
    """Flag direct overwritten bindings and calls in top-level assignments.

    Args:
        module_node (ast.Module): Validated source syntax.
        report_info (SnippetReport): Source-located question destination.
    Returns:
        None: Records questions without changing extraction eligibility.
    Warnings:
        Direct reads are a syntax inventory, not an alias or liveness proof.
    """
    unread_dict = {}
    for statement_node in module_node.body:
        parts_tuple = split_assignment_parts_tuple(statement_node, True)
        if parts_tuple is None or parts_tuple[1] is None:
            unread_dict.clear()
            continue
        target_node, value_node = parts_tuple
        for node in ast.walk(value_node):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                unread_dict.pop(node.id, None)
            if isinstance(node, ast.Call):
                record_call_question_none(node, report_info)
        if target_node.id in unread_dict:
            earlier_int = unread_dict[target_node.id]
            report_info.questions.append(SnippetQuestion(
                "SNIPWRITE", statement_node.lineno,
                f"'{target_node.id}' was assigned at line {earlier_int} "
                "without an intervening direct read in these assignments. "
                "Is this overwrite intentional? No assignment is removed; "
                "effects and indirect reads remain unresolved.",
            ))
        unread_dict[target_node.id] = statement_node.lineno


def record_call_question_none(
    call_node: ast.Call, report_info: SnippetReport,
) -> None:
    """Ask about a callable's meaning, types and effects without resolving it.

    Args:
        call_node (ast.Call): Unevaluated source call.
        report_info (SnippetReport): Question destination.
    Returns:
        None: Adds implementation, input conversion or logarithm questions.
    Warnings:
        A familiar callable spelling does not resolve its implementation.
    """
    name_str = getattr(call_node.func, "id",
                       getattr(call_node.func, "attr", "<dynamic callable>"))
    prompt_str = (
        f"What does '{name_str}' do, and what types does it take and "
        "return? The draft keeps the call as written; FuncLoom does not "
        "resolve its implementation, types or effects."
    )
    if name_str == "input":
        prompt_str += (
            " If this is Python's built-in input, it returns text. Should "
            "numeric conversion and terminal input be separate from the "
            "calculation, or is this a different callable?"
        )
    elif name_str == "log":
        prompt_str += (
            " If this is a logarithm, specify its base and valid input "
            "domain; the name alone does not establish those choices."
        )
    report_info.questions.append(SnippetQuestion(
        "SNIPCALL", call_node.lineno, prompt_str,
    ))
