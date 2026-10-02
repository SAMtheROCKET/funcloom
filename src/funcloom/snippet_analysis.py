"""Locate a bounded snippet region and record unresolved user decisions."""

import ast
import builtins
from io import StringIO

from funcloom.models import Diagnostic
from funcloom.plan_analysis import (
    split_assignment_parts_tuple, split_statement_parts_tuple,
)
from funcloom.snippet_models import SnippetQuestion, SnippetReport

SETUP_STATEMENTS_TUPLE = (
    ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
    ast.ClassDef,
)


def attach_snippet_issue_none(
    report_info: SnippetReport, code_str: str, line_int: int, message_str: str,
) -> None:
    """Attach a source-located refusal without losing the original snippet.

    Args:
        report_info (SnippetReport): Review artifact being assembled.
        code_str (str): Stable diagnostic category.
        line_int (int): One-based source or cell line.
        message_str (str): Specific reason for refusal.
    Returns:
        None: Records a diagnostic.
    Warnings:
        A diagnostic does not authorize editing source.
    """
    report_info.diagnostics.append(Diagnostic(
        code_str, "error", report_info.source.name, line_int, 1, message_str,
    ))


def parse_snippet_module(
    report_info: SnippetReport, max_bytes_int: int,
) -> ast.Module | None:
    """Parse and contextually compile a bounded snippet without execution.

    Args:
        report_info (SnippetReport): Source and diagnostic destination.
        max_bytes_int (int): UTF-8 snippet size cap.
    Returns:
        ast.Module | None: Valid syntax or a located refusal.
    Warnings:
        Notebook magics and hidden kernel dependencies are unsupported.
    """
    try:
        source_str = report_info.source.text
        if len(source_str.encode("utf-8")) > max_bytes_int:
            raise ValueError("Snippet exceeds configured source byte limit")
        module_node = ast.parse(source_str)
        compile(module_node, report_info.source.name, "exec",
                dont_inherit=True)
        return module_node
    except SyntaxError as error:
        attach_snippet_issue_none(report_info, "PARSE001", error.lineno or 1,
                                  str(error.msg))
        report_info.questions.append(SnippetQuestion(
            "SNIPSYNTAX", error.lineno or 1,
            "Supply executable Python for this line. Specify ambiguous "
            "operations and execution order explicitly; prose placeholders "
            "and equations cannot be repaired by formatting alone.",
        ))
    except (ValueError, UnicodeError, RecursionError) as error:
        attach_snippet_issue_none(report_info, "SNIP001", 1, str(error))
    return None


def is_literal_setup_bool(statement_node: ast.stmt) -> bool:
    """Recognize literal setup assignments without evaluating expressions.

    Args:
        statement_node (ast.stmt): A possible single-name initialization.
    Returns:
        bool: True only for constants or signed numeric constants.
    Warnings:
        This is a parameterization suggestion, not knowledge of user intent.
    """
    parts_tuple = split_assignment_parts_tuple(statement_node, True)
    if parts_tuple is None:
        return False
    value_node = parts_tuple[1]
    if isinstance(value_node, ast.Constant):
        return True
    return (
        isinstance(value_node, ast.UnaryOp)
        and isinstance(value_node.op, (ast.UAdd, ast.USub))
        and isinstance(value_node.operand, ast.Constant)
        and type(value_node.operand.value) in (int, float)
    )


def suggest_snippet_region_tuple(
    module_node: ast.Module, report_info: SnippetReport,
) -> tuple[int, int] | None:
    """Suggest computation boundaries after an initial literal setup prefix.

    Args:
        module_node (ast.Module): Parsed snippet.
        report_info (SnippetReport): Policy and clarification destination.
    Returns:
        tuple | None: Inclusive physical lines, or a focused question.
    Warnings:
        Leading imports and definitions always stay outside the function;
        leading literal assignments do too under the parameters policy.
    """
    start_int = 1
    remaining_list = list(module_node.body)
    if remaining_list and isinstance(remaining_list[0], ast.Expr) and (
        isinstance(remaining_list[0].value, ast.Constant)
        and isinstance(remaining_list[0].value.value, str)
    ):
        start_int = remaining_list.pop(0).end_lineno + 1
    literal_bool = report_info.context.literal_policy == "parameters"
    while remaining_list and (
        isinstance(remaining_list[0], SETUP_STATEMENTS_TUPLE)
        or (literal_bool and is_literal_setup_bool(remaining_list[0]))
    ):
        start_int = remaining_list.pop(0).end_lineno + 1
    if not remaining_list:
        report_missing_calculation_none(module_node, report_info)
        return None
    end_int = len(StringIO(report_info.source.text, newline="").readlines())
    report_info.assumptions.append(
        "Leading literals stay in caller setup; selected reads become inputs."
        if report_info.context.literal_policy == "parameters" else
        "Literal assignments remain inside the proposed function."
    )
    return start_int, end_int


def suggest_operation_name_str(
    module_node: ast.Module, start_line_int: int, naming_mode_str: str,
) -> str:
    """Suggest an operation name from written identifiers without domain AI.

    Args:
        module_node (ast.Module): Whole snippet syntax.
        start_line_int (int): First selected physical line.
        naming_mode_str (str): Source, domain or neutral mathematical naming.
    Returns:
        str: A deterministic non-colliding function name.
    Warnings:
        Source-derived wording is a proposal, not inferred business meaning.
    """
    outputs_list = []
    for node in module_node.body:
        parts_tuple = split_statement_parts_tuple(node)
        if node.lineno >= start_line_int and parts_tuple is not None:
            outputs_list.extend(name_node.id for name_node in parts_tuple[1]
                                if name_node.id not in outputs_list)
    stem_str = outputs_list[-1] if outputs_list else "selected_values"
    stem_str = stem_str.removesuffix("_int").removesuffix("_float")
    suffix_str = "tuple" if len(outputs_list) > 1 else "value"
    base_str = (f"evaluate_expression_{suffix_str}"
                if naming_mode_str == "mathematical" else
                f"calculate_{stem_str}_{suffix_str}")
    names_set = {node.id for node in ast.walk(module_node)
                 if isinstance(node, ast.Name)} | set(vars(builtins))
    candidate_str, counter_int = base_str, 2
    while candidate_str in names_set:
        candidate_str = f"{base_str}_{counter_int}"
        counter_int += 1
    return candidate_str


def report_missing_calculation_none(
    module_node: ast.Module, report_info: SnippetReport,
) -> None:
    """Distinguish literal-only setup from a source without assignments.

    Args:
        module_node (ast.Module): Source without a selected computation.
        report_info (SnippetReport): Clarification destination.
    Returns:
        None: Records a relevant user decision or missing source request.
    Warnings:
        An empty snippet cannot be repaired by a literal policy choice.
    """
    report_info.status = "needs_context"
    if any(isinstance(node, (ast.Assign, ast.AnnAssign))
           for node in module_node.body):
        question_info = SnippetQuestion(
            "SNIP001", 1, "No calculation follows the literal setup. Keep "
            "these assignments inside the function, or supply a calculation?",
            ("Use literal_policy=fixed", "Include calculation statements"),
        )
    else:
        question_info = SnippetQuestion(
            "SNIPEMPTY", 1, "Provide assignment statements to extract.",
        )
    report_info.questions.append(question_info)
