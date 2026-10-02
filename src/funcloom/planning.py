"""Read-only plans for explicitly selected module-scope assignment regions."""

import ast
from pathlib import Path

from funcloom.config import RuleProfile, validate_profile_none
from funcloom.plan_analysis import (
    analyze_selection_none, resolve_prefix_bindings_info
)
from funcloom.plan_bindings import resolve_bindings_none
from funcloom.plan_dispatch import check_dispatch_none
from funcloom.plan_effects import record_effect_inventory_none
from funcloom.plan_models import ExtractionPlan, append_issue_none
from funcloom.plan_preview import build_preview_none
from funcloom.plan_selection import (
    check_name_none, record_fragment_none, select_statements_list,
    validate_request_none,
)
from funcloom.syntax import read_source_tuple

ASSUMPTIONS_TUPLE = (
    "Only complete module-scope single-name assignments are proposed.",
    "Runtime values and types are unknown; annotations are declarations.",
    "Operators can invoke user code; arithmetic syntax does not prove purity.",
    "Imports and annotation evaluation can have unmodeled runtime effects.",
    "Bindings are returned on normal completion only, not partial failure.",
    "Adding a function changes namespace, stack, and object lifetime details.",
)
VALIDATION_REQUIRED_TUPLE = (
    "Validate runtime value types, effects, aliasing, and evaluation order.",
    "Check exception paths and assignments visible before a failure.",
    "Review globals/reflection, tracing, and cross-module callers.",
    "Resolve input/output annotations and useful domain documentation.",
    "Recheck the complete source hash immediately before any future apply.",
    "Run behavioral regressions for the intended source and supported cases.",
)


def plan_extraction_report(
    source_path: str | Path, start_line_int: int, end_line_int: int,
    function_name_str: str, profile_info: RuleProfile | None = None,
) -> ExtractionPlan:
    """Plan a user-selected extraction without changing or running source.

    Args:
        source_path (str | Path): One Python file, not a directory or link.
        start_line_int (int): First selected physical line, inclusive.
        end_line_int (int): Last selected physical line, inclusive.
        function_name_str (str): Explicit operation name supplied by caller.
        profile_info (RuleProfile | None): Limits, or default settings.
    Returns:
        ExtractionPlan: A review candidate or source-located refusals.
    Warnings:
        A candidate is not safe-to-apply approval or a behavior proof.
    """
    validate_request_none(start_line_int, end_line_int, function_name_str)
    profile_info = profile_info or RuleProfile()
    validate_profile_none(profile_info)
    source_path = Path(source_path).absolute()
    if source_path.is_symlink() or source_path.is_dir() or (
        source_path.suffix != ".py"
    ):
        raise ValueError("Plan requires one .py file, not a directory or link")
    plan_report = ExtractionPlan(
        str(source_path.resolve()), start_line_int, end_line_int,
        function_name_str,
    )
    plan_report.assumptions = list(ASSUMPTIONS_TUPLE)
    plan_report.validation_required = list(VALIDATION_REQUIRED_TUPLE)
    source_tuple = read_plan_source_tuple(
        source_path, profile_info, plan_report,
    )
    if source_tuple is not None:
        source_str, module_node = source_tuple
        prepare_candidate_none(source_str, module_node, profile_info,
                               plan_report)
    plan_report.diagnostics.sort(
        key=lambda diagnostic_info: (
            diagnostic_info.line, diagnostic_info.code))
    return plan_report


def read_plan_source_tuple(
    source_path: Path, profile_info: RuleProfile, plan_report: ExtractionPlan,
) -> tuple[str, ast.Module] | None:
    """Read and compile source while retaining failures in the plan report.

    Args:
        source_path (Path): Python source file to inspect.
        profile_info (RuleProfile): Bounded file read settings.
        plan_report (ExtractionPlan): Hash and diagnostic destination.
    Returns:
        tuple | None: Decoded source and AST, or a refused read/parse result.
    Warnings:
        Compiling validates syntax; no resulting bytecode is executed.
    """
    try:
        source_str, plan_report.source_sha256 = read_source_tuple(
            source_path, profile_info.max_file_bytes,
        )
        module_node = ast.parse(source_str, filename=source_path.name)
        compile(module_node, source_path.name, "exec", dont_inherit=True)
        return source_str, module_node
    except SyntaxError as error:
        append_issue_none(plan_report, "PARSE001", error.lineno or 1,
                          str(error.msg))
    except (OSError, UnicodeError, LookupError, ValueError,
            RecursionError) as error:
        append_issue_none(plan_report, "READ001", 1, str(error))
    return None


def prepare_candidate_none(
    source_str: str, module_node: ast.Module, profile_info: RuleProfile,
    plan_report: ExtractionPlan,
) -> None:
    """Validate selection, bindings, expressions, and review preview syntax.

    Args:
        source_str (str): Original decoded source.
        module_node (ast.Module): Parsed and compiled file.
        profile_info (RuleProfile): Output size constraints.
        plan_report (ExtractionPlan): Result accumulator.
    Returns:
        None: Populates a candidate only when all subset checks pass.
    Warnings:
        Refused reports may contain partial facts; they contain no preview.
    """
    try:
        record_fragment_none(source_str, plan_report)
        if plan_report.diagnostics:
            return
        statements_list = select_statements_list(module_node, plan_report)
        if not plan_report.diagnostics:
            record_effect_inventory_none(
                module_node, statements_list, plan_report)
            resolve_bindings_none(module_node, statements_list, plan_report)
        check_name_none(module_node, plan_report)
        if plan_report.diagnostics:
            return
        bindings_info = resolve_prefix_bindings_info(module_node, plan_report)
        analyze_selection_none(statements_list, bindings_info, plan_report)
        if not plan_report.diagnostics:
            check_dispatch_none(module_node, statements_list, plan_report)
        if not plan_report.diagnostics:
            build_preview_none(plan_report, profile_info, statements_list)
    except (SyntaxError, ValueError, RecursionError) as error:
        append_issue_none(plan_report, "PLAN007", plan_report.start_line,
                          f"Preview analysis failed: {error}")
