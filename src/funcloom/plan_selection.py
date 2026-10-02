"""Validate exact physical-line selections without discarding source text."""

import ast
import builtins
from hashlib import sha256
from io import StringIO
import keyword
import unicodedata

from funcloom.plan_models import ExtractionPlan, append_issue_none


def validate_request_none(
    start_line_int: int, end_line_int: int, function_name_str: str,
) -> None:
    """Validate the caller's explicit region and proposed function name.

    Args:
        start_line_int (int): First included physical line, starting at one.
        end_line_int (int): Last included physical line.
        function_name_str (str): User-supplied operation name.
    Returns:
        None: Raises ValueError for invalid request values.
    Warnings:
        Name meaning and return-type suffixes are not invented or verified.
    """
    if (
        type(start_line_int) is not int or type(end_line_int) is not int
        or start_line_int < 1 or end_line_int < start_line_int
    ):
        raise ValueError("Select positive lines with start <= end")
    if (
        not isinstance(function_name_str, str)
        or not function_name_str.isidentifier()
        or keyword.iskeyword(function_name_str)
        or unicodedata.normalize("NFKC", function_name_str)
        != function_name_str
    ):
        raise ValueError("Use a valid, normalized Python function name")


def record_fragment_none(
    source_str: str, plan_report: ExtractionPlan,
) -> None:
    """Retain the selected decoded text and a separate fragment fingerprint.

    Args:
        source_str (str): Source decoded with its Python encoding cookie.
        plan_report (ExtractionPlan): Region and report destination.
    Returns:
        None: Records the exact decoded fragment, including line endings.
    Warnings:
        Fragment SHA-256 uses UTF-8 text; file SHA-256 uses original bytes.
    """
    lines_list = StringIO(source_str, newline="").readlines()
    if plan_report.end_line > len(lines_list):
        append_issue_none(plan_report, "PLAN001", plan_report.start_line,
                          "Selection extends beyond the source file.")
        return
    fragment_str = "".join(
        lines_list[plan_report.start_line - 1:plan_report.end_line]
    )
    plan_report.source_fragment = fragment_str
    plan_report.fragment_sha256 = sha256(fragment_str.encode()).hexdigest()


def select_statements_list(
    module_node: ast.Module, plan_report: ExtractionPlan,
) -> list[ast.stmt]:
    """Select complete module-scope statements within physical line bounds.

    Args:
        module_node (ast.Module): Parsed and contextually compiled source.
        plan_report (ExtractionPlan): Explicit selection and diagnostics.
    Returns:
        list[ast.stmt]: Selected statements, or an empty refused selection.
    Warnings:
        Nested suites, partial statements, and semicolon groups are refused.
    """
    selected_list = []
    for statement_node in module_node.body:
        first_int = min([statement_node.lineno] + [
            node.lineno for node in getattr(statement_node,
                                            "decorator_list", [])
        ])
        last_int = statement_node.end_lineno or statement_node.lineno
        if (
            last_int < plan_report.start_line
            or first_int > plan_report.end_line
        ):
            continue
        if (
            first_int < plan_report.start_line
            or last_int > plan_report.end_line
            or statement_node.col_offset != 0
        ):
            append_issue_none(plan_report, "PLAN001", statement_node.lineno,
                              "Select complete statements at module scope.")
            return []
        selected_list.append(statement_node)
    if not selected_list:
        append_issue_none(plan_report, "PLAN001", plan_report.start_line,
                          "Selection contains no module-scope statements.")
    return selected_list


def check_name_none(
    module_node: ast.Module, plan_report: ExtractionPlan,
) -> None:
    """Reject a proposed name already visible anywhere in the source AST.

    Args:
        module_node (ast.Module): Full source tree, including nested scopes.
        plan_report (ExtractionPlan): Proposed name and diagnostic output.
    Returns:
        None: Reports collisions with identifiers and builtin names.
    Warnings:
        String-based reflection and names in other modules remain unresolved.
    """
    names_set = set(vars(builtins))
    for node in ast.walk(module_node):
        if isinstance(node, ast.Name):
            names_set.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names_set.add(node.name)
        elif isinstance(node, ast.arg):
            names_set.add(node.arg)
        elif isinstance(node, ast.alias):
            names_set.add(node.asname or node.name.split(".")[0])
    if plan_report.function_name in names_set:
        append_issue_none(plan_report, "PLAN004", plan_report.start_line,
                          "Proposed function name collides with a source "
                          "identifier or builtin.")
