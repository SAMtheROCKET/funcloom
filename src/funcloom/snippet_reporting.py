"""Text and JSON reports for contextual, read-only snippet proposals."""

from dataclasses import asdict
import json

from funcloom.plan_reporting import render_effects_list
from funcloom.snippet_models import SnippetReport


def render_snippet_header_list(report_info: SnippetReport) -> list[str]:
    """Render provenance, proposed names and explicit type evidence.

    Args:
        report_info (SnippetReport): Source-linked snippet artifact.
    Returns:
        list[str]: Header and value contract lines.
    Warnings:
        Proposed annotations remain unverified even in a successful draft.
    """
    lines_list = [
        f"FuncLoom {report_info.tool_version} | snippet | "
        f"{report_info.status}",
        f"Source: {report_info.source.name}",
        f"Cell: {report_info.source.cell_index or 'not a notebook'}",
        f"Context: {report_info.context_mode}",
        f"Naming: {report_info.context.naming_mode}",
        f"Source text SHA-256: {report_info.source_sha256}",
        "Review required; can_apply=false; behavior_verified=false.",
    ]
    for value_info in report_info.values:
        lines_list.append(
            f"{value_info.role}: {value_info.original_name} -> "
            f"{value_info.proposed_name} "
            f"({value_info.annotation or 'unknown'}; "
            f"{value_info.type_evidence})",
        )
    return lines_list


def render_snippet_str(report_info: SnippetReport, format_str: str) -> str:
    """Render drafts, focused questions, refusals and their proof limits.

    Args:
        report_info (SnippetReport): Contextual candidate or refusal.
        format_str (str): text or json.
    Returns:
        str: Human-readable or versioned machine-readable review artifact.
    Warnings:
        Includes source and user context; review before sharing the report.
    """
    if format_str == "json":
        return json.dumps(asdict(report_info), indent=2) + "\n"
    lines_list = render_snippet_header_list(report_info)
    lines_list.extend(f"Assumption: {assumption_str}"
                      for assumption_str in report_info.assumptions)
    lines_list.extend(
        f"{diagnostic_info.path}:{diagnostic_info.line}: "
        f"{diagnostic_info.code} {diagnostic_info.message}"
        for diagnostic_info in report_info.diagnostics
    )
    for question_info in report_info.questions:
        lines_list.append(
            f"Question at line {question_info.line}: {question_info.prompt}")
        lines_list.extend(
            f"  Option: {option}" for option in question_info.options)
    if report_info.function_preview is not None:
        lines_list.extend(["", "Draft function:", report_info.function_preview,
                           "Draft caller:", report_info.caller_preview])
    if report_info.plan is not None:
        lines_list.extend(render_effects_list(report_info.plan))
        lines_list.append("Validation still required:")
        lines_list.extend(f"- {validation_str}" for validation_str in
                          report_info.plan.validation_required)
    return "\n".join(lines_list) + "\n"
