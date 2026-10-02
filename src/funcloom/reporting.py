"""Stable JSON and concise plain-text output for local tools and editors."""

from dataclasses import asdict
import json

from funcloom.models import ProjectReport


def report_dict(report: ProjectReport) -> dict:
    """Serialize the report and include transparent completion counts.

    Args:
        report (ProjectReport): Analysis result.
    Returns:
        dict: JSON-compatible values with coverage and failure status.
    Warnings:
        Clean checks do not imply full style or behavioral compliance.
    """
    report_data_dict = asdict(report)
    errors_int = sum(
        finding.severity == "error" for finding in report.diagnostics
    )
    warnings_int = sum(
        finding.severity == "warning" for finding in report.diagnostics
    )
    report_data_dict["summary"] = {
        "parsed_files": len(report.modules),
        "functions": sum(len(module.functions) for module in report.modules),
        "errors": errors_int,
        "warnings": warnings_int,
        "skipped_entries": len(report.skipped),
        "analysis_complete": not any(
            finding.code in {"READ001", "PARSE001"}
            for finding in report.diagnostics
        ),
        "all_rules_implemented": False,
        "behavior_verified": False,
    }
    return report_data_dict


def render_report_str(report: ProjectReport, format_str: str) -> str:
    """Render facts without changing or hiding diagnostic severity.

    Args:
        report (ProjectReport): Analysis result.
        format_str (str): json or text.
    Returns:
        str: Human-readable or machine-readable report.
    Warnings:
        JSON contains the analyzed root path and declared docstrings.
    """
    report_data_dict = report_dict(report)
    if format_str == "json":
        return json.dumps(report_data_dict, indent=2, ensure_ascii=True) + "\n"
    summary_dict = report_data_dict["summary"]
    lines_list = [
        f"FuncLoom {report.tool_version} | {report.mode} | read-only",
        f"Root: {report.root}",
        f"Files: {summary_dict['parsed_files']} | "
        f"Functions: {summary_dict['functions']} | "
        f"Errors: {summary_dict['errors']} | "
        f"Warnings: {summary_dict['warnings']}",
    ]
    for module_info in report.modules:
        lines_list.append(
            f"  {module_info.path}: {module_info.physical_lines} lines, "
            f"{len(module_info.functions)} functions"
        )
    for finding in report.diagnostics:
        lines_list.append(
            f"{finding.path}:{finding.line}:{finding.column}: "
            f"{finding.severity} {finding.code} {finding.message}"
        )
    lines_list.append(
        "Coverage: syntax, inventory, and listed checks only; "
        "behavior and full profile compliance are not verified."
    )
    lines_list.append(f"Skipped entries: {len(report.skipped)} (see JSON)")
    return "\n".join(lines_list) + "\n"
