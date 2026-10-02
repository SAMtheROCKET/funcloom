"""Stable read-only entry points for later editor and pipeline clients."""

from dataclasses import asdict
from pathlib import Path

from funcloom.checks import CHECK_CODES_TUPLE, check_module_list
from funcloom.config import RuleProfile, validate_profile_none
from funcloom.discovery import discover_python_paths_tuple
from funcloom.models import Diagnostic, ProjectReport
from funcloom.syntax import parse_module_info, read_source_tuple

LIMITATIONS_LIST = [
    "No extraction, edits, import execution, or target-code execution.",
    "Annotations are declarations, not verified runtime types.",
    "No data-flow analysis, dependency resolution, or behavior proof.",
    "No semantic naming, dtype-suffix checking, or constant hoisting yet.",
    "Docstring sections are checked for presence, not factual accuracy.",
    "Python syntax support follows the interpreter running FuncLoom.",
    "Exclusions use directory basenames; .gitignore is not interpreted.",
    "Zero findings means only that the implemented checks found nothing.",
]


def scan_project_report(
    source_path: str | Path, profile: RuleProfile | None = None,
) -> ProjectReport:
    """Inventory Python source without importing or executing it.

    Args:
        source_path (str | Path): A source file or directory.
        profile (RuleProfile | None): Explicit settings or defaults.
    Returns:
        ProjectReport: Facts and any read/parse/compile failures.
    Warnings:
        This does not establish that a repository can be safely refactored.
    """
    return analyze_project_report(Path(source_path), profile, "scan")


def check_project_report(
    source_path: str | Path, profile: RuleProfile | None = None,
) -> ProjectReport:
    """Inventory source and apply the implemented objective checks.

    Args:
        source_path (str | Path): A source file or directory.
        profile (RuleProfile | None): Explicit settings or defaults.
    Returns:
        ProjectReport: Source facts, findings, and stated coverage limits.
    Warnings:
        No source is edited and no type or domain meaning is invented.
    """
    return analyze_project_report(Path(source_path), profile, "check")


def analyze_project_report(
    source_path: Path, profile: RuleProfile | None, mode_str: str,
) -> ProjectReport:
    """Run the shared discovery and analysis pipeline.

    Args:
        source_path (Path): Source selection.
        profile (RuleProfile | None): Optional configuration.
        mode_str (str): Either scan or check.
    Returns:
        ProjectReport: Deterministically ordered facts and findings.
    Warnings:
        Per-file failures are errors, never silent successes.
    """
    profile = profile or RuleProfile()
    validate_profile_none(profile)
    root_path, paths_list, skipped_list = discover_python_paths_tuple(
        source_path, profile,
    )
    report = ProjectReport(str(root_path), mode_str, asdict(profile))
    report.skipped = skipped_list
    report.limitations = LIMITATIONS_LIST.copy()
    report.checks_run = ["PARSE001", "READ001"]
    if mode_str == "check":
        report.checks_run.extend(CHECK_CODES_TUPLE)
    for file_path in paths_list:
        analyze_file_none(file_path, root_path, profile, report)
    report.diagnostics.sort(key=lambda finding: (
        finding.path, finding.line, finding.column, finding.code,
    ))
    return report


def analyze_file_none(
    file_path: Path, root_path: Path, profile: RuleProfile,
    report: ProjectReport,
) -> None:
    """Append one file's facts or explicit failure to the report.

    Args:
        file_path (Path): File to inspect.
        root_path (Path): Relative-path anchor.
        profile (RuleProfile): Resource and style settings.
        report (ProjectReport): Accumulator for this request.
    Returns:
        None: Appends results to the supplied report.
    Warnings:
        Compiling source validates syntax but never executes bytecode.
    """
    relative_path_str = file_path.relative_to(root_path).as_posix()
    try:
        source_str, source_hash_str = read_source_tuple(
            file_path, profile.max_file_bytes,
        )
        module_info = parse_module_info(
            source_str, relative_path_str, source_hash_str,
        )
    except SyntaxError as error:
        report.diagnostics.append(Diagnostic(
            "PARSE001", "error", relative_path_str,
            error.lineno or 1, error.offset or 1, str(error.msg),
        ))
        return
    except (
        OSError, UnicodeError, LookupError, ValueError, RecursionError,
    ) as error:
        report.diagnostics.append(Diagnostic(
            "READ001", "error", relative_path_str, 1, 1, str(error),
        ))
        return
    report.modules.append(module_info)
    if report.mode == "check":
        report.diagnostics.extend(check_module_list(
            source_str, module_info, profile,
        ))
