"""Public snippet and notebook-cell review APIs with optional user context."""

import ast
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from funcloom.config import (
    RuleProfile, apply_line_length_profile, validate_profile_none,
)
from funcloom.plan_models import ExtractionPlan
from funcloom.planning import (
    ASSUMPTIONS_TUPLE, VALIDATION_REQUIRED_TUPLE, prepare_candidate_none,
)
from funcloom.snippet_analysis import (
    parse_snippet_module, attach_snippet_issue_none,
    suggest_snippet_region_tuple,
    suggest_operation_name_str,
)
from funcloom.snippet_context import validate_context_none
from funcloom.snippet_models import (
    SnippetContext, SnippetReport, SnippetSource,
)
from funcloom.snippet_preview import build_snippet_preview_none
from funcloom.snippet_questions import record_source_questions_none
from funcloom.snippet_source import read_snippet_source
from funcloom.snippet_types import propose_values_none
from funcloom.snippet_wrapping import WrappingRefusal

UNWRAPPED_WIDTH_INT = 1_000_000_000


def plan_snippet_report(
    source_str: str, context_info: SnippetContext | None = None,
    profile_info: RuleProfile | None = None,
) -> SnippetReport:
    """Propose a reusable function directly from pasted Python text.

    Args:
        source_str (str): Python text, for example a notebook cell string.
        context_info (SnippetContext | None): Optional structured user intent.
        profile_info (RuleProfile | None): Limits or project defaults.
    Returns:
        SnippetReport: A review candidate, refusal or focused question.
    Warnings:
        Source is never executed; inference is a numeric proposal only.
    """
    if not isinstance(source_str, str):
        raise ValueError("Snippet source must be text")
    return build_snippet_report(
        SnippetSource("<snippet>", source_str), context_info, profile_info,
    )


def plan_snippet_file_report(
    source_path: str | Path, context_info: SnippetContext | None = None,
    cell_index_int: int | None = None,
    profile_info: RuleProfile | None = None,
) -> SnippetReport:
    """Read one Python document or notebook cell into a source-linked plan.

    Args:
        source_path (str | Path): A .py or .ipynb file.
        context_info (SnippetContext | None): Optional non-executable context.
        cell_index_int (int | None): One-based index among all notebook cells.
        profile_info (RuleProfile | None): Limits or defaults.
    Returns:
        SnippetReport: Draft with document and selected-text fingerprints.
    Warnings:
        Other notebook cells, kernel state and outputs are not consulted.
    """
    profile_info = profile_info or RuleProfile()
    validate_profile_none(profile_info)
    source_info = read_snippet_source(
        source_path, cell_index_int, profile_info.max_file_bytes,
    )
    return build_snippet_report(source_info, context_info, profile_info)


def build_snippet_report(
    source_info: SnippetSource, context_info: SnippetContext | None,
    profile_info: RuleProfile | None,
) -> SnippetReport:
    """Compose the existing planner with bounded context and draft enrichment.

    Args:
        source_info (SnippetSource): Original source and optional notebook ID.
        context_info (SnippetContext | None): Explicit user intent.
        profile_info (RuleProfile | None): Review draft limits.
    Returns:
        SnippetReport: Evidence without source mutation or apply capability.
    Warnings:
        Context cannot override a base planner refusal.
    """
    context_info = (SnippetContext() if context_info is None
                    else deepcopy(context_info))
    validate_context_none(context_info)
    profile_info = profile_info or RuleProfile()
    validate_profile_none(profile_info)
    if context_info.line_length is not None:
        profile_info = apply_line_length_profile(
            profile_info, context_info.line_length,
        )
    report_info = create_snippet_report(source_info, context_info)
    module_node = parse_snippet_module(
        report_info, profile_info.max_file_bytes,
    )
    if module_node is None:
        return report_info
    report_info.source_sha256 = sha256(
        source_info.text.encode("utf-8"),
    ).hexdigest()
    record_source_questions_none(module_node, report_info)
    region_tuple = suggest_snippet_region_tuple(module_node, report_info)
    if region_tuple is not None:
        prepare_snippet_none(
            module_node, region_tuple, report_info, profile_info,
        )
    return report_info


def prepare_snippet_none(
    module_node: ast.Module, region_tuple: tuple[int, int],
    report_info: SnippetReport, profile_info: RuleProfile,
) -> None:
    """Require a valid base plan before adding local naming and type proposals.

    Args:
        module_node (ast.Module): Validated source syntax.
        region_tuple (tuple): Suggested inclusive selection lines.
        report_info (SnippetReport): Proposal accumulator.
        profile_info (RuleProfile): Applicable source and preview limits.
    Returns:
        None: Adds drafts or source-located refusals.
    Warnings:
        All underlying effect and binding limitations remain in force.
        The base plan skips its width cap so long source lines can be
        wrapped; the contextual draft enforces the configured width.
    """
    name_str = report_info.context.function_name or suggest_operation_name_str(
        module_node, region_tuple[0], report_info.context.naming_mode,
    )
    plan_info = build_initial_plan_info(report_info, region_tuple, name_str)
    report_info.plan = plan_info
    report_info.assumptions.append(
        "Long source lines may be wrapped; the contextual draft must "
        f"fit {profile_info.line_length} characters per line."
    )
    prepare_candidate_none(
        report_info.source.text, module_node,
        replace(profile_info, line_length=UNWRAPPED_WIDTH_INT), plan_info,
    )
    report_info.diagnostics.extend(plan_info.diagnostics)
    if plan_info.status == "candidate_for_review":
        build_contextual_draft_none(module_node, report_info, profile_info)


def build_contextual_draft_none(
    module_node: ast.Module, report_info: SnippetReport,
    profile_info: RuleProfile,
) -> None:
    """Add typed names and a wrapped draft, or a located refusal.

    Args:
        module_node (ast.Module): Validated source syntax.
        report_info (SnippetReport): Report holding a candidate base plan.
        profile_info (RuleProfile): Width and size limits for the draft.
    Returns:
        None: Stores previews or appends SNIP003/SNIP004 diagnostics.
    Warnings:
        SNIP004 marks a tool directive that wrapping would split or move.
    """
    start_line_int = report_info.plan.start_line
    try:
        propose_values_none(module_node, report_info)
        build_snippet_preview_none(module_node, report_info, profile_info)
    except WrappingRefusal as error:
        attach_snippet_issue_none(report_info, "SNIP004", start_line_int
                                  + error.fragment_line_int - 1, str(error))
    except (ValueError, SyntaxError, RecursionError) as error:
        attach_snippet_issue_none(
            report_info, "SNIP003", start_line_int, str(error))


def create_snippet_report(
    source_info: SnippetSource, context_info: SnippetContext,
) -> SnippetReport:
    """Record whether the user supplied project meaning or only preferences.

    Args:
        source_info (SnippetSource): Original text and document provenance.
        context_info (SnippetContext): Validated optional user context.
    Returns:
        SnippetReport: An empty report with its context mode established.
    Warnings:
        Context mode does not verify the supplied descriptions or types.
    """
    report_info = SnippetReport(source_info, context_info)
    report_info.context_mode = (
        "project" if any((
            context_info.project_context, context_info.summary,
            context_info.input_types, context_info.descriptions,
            context_info.names, context_info.naming_mode == "domain",
        )) else "none"
    )
    return report_info


def build_initial_plan_info(
    report_info: SnippetReport, region_tuple: tuple[int, int], name_str: str,
) -> ExtractionPlan:
    """Associate the base plan with source text or original document bytes.

    Args:
        report_info (SnippetReport): Source provenance and selected-text hash.
        region_tuple (tuple): Inclusive selection boundaries.
        name_str (str): Proposed function identifier.
    Returns:
        ExtractionPlan: Base plan with the existing review requirements.
    Warnings:
        Notebook cell hashes do not replace the whole document fingerprint.
    """
    source_name_str = report_info.source.name
    digest_str = report_info.source_sha256
    if report_info.source.cell_index is not None:
        source_name_str += f"#cell={report_info.source.cell_index}"
    else:
        digest_str = report_info.source.document_sha256 or digest_str
    plan_info = ExtractionPlan(source_name_str, *region_tuple, name_str)
    plan_info.source_sha256 = digest_str
    plan_info.assumptions = list(ASSUMPTIONS_TUPLE)
    plan_info.validation_required = list(VALIDATION_REQUIRED_TUPLE)
    return plan_info
