"""Thin local CLI for source inventory, checks, and extraction proposals."""

import argparse
import json
from pathlib import Path
import platform
import sys

from funcloom import __version__
from funcloom.api import check_project_report, scan_project_report
from funcloom.config import (
    RuleProfile, apply_line_length_profile, load_profile
)
from funcloom.planning import plan_extraction_report
from funcloom.plan_reporting import render_plan_str
from funcloom.reporting import render_report_str
from funcloom.modular_cli import (
    add_modularize_parser_none, add_refine_parser_none, run_modularize_int,
    run_refine_int,
)
from funcloom.snippet_cli import add_snippet_parser_none, run_snippet_int


QUICK_START_STR = """\
FuncLoom - the Python functionizer. Original files are never changed.

  funcloom check script.py
      report long functions and structure problems
  funcloom snippet code.py
      draft a reusable function from a snippet or notebook cell
  funcloom plan script.py --start-line 10 --end-line 30 --name load_data
      test whether lines 10-30 can safely become a function
  funcloom modularize script.py --output my_package
      turn a script, notebook or folder into a package
  funcloom refine script.py --output script_refined.py
      split long functions and wrap long lines in a new copy

Run "funcloom COMMAND --help" for options or "funcloom --help" for all
commands.
"""


def build_parser() -> argparse.ArgumentParser:
    """Build CLI options shared by the local commands.

    Args:
        None: Command definitions are fixed by this version.
    Returns:
        argparse.ArgumentParser: Parser with supported subcommands.
    Warnings:
        Plans require review; source editing is not implemented.
    """
    parser = argparse.ArgumentParser(prog="funcloom")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor", help="Show local runtime")
    doctor_parser.add_argument("--format", choices=["text", "json"],
                               default="text")
    for command_str in ("scan", "check", "plan"):
        add_source_parser_none(commands, command_str)
    add_snippet_parser_none(commands)
    add_modularize_parser_none(commands)
    add_refine_parser_none(commands)
    return parser


def add_source_parser_none(
    commands: argparse._SubParsersAction, command_str: str,
) -> None:
    """Register one of the scan, check or plan subcommands.

    Args:
        commands (argparse._SubParsersAction): Subcommand registry.
        command_str (str): scan, check or plan.
    Returns:
        None: Adds the subcommand and its options.
    Warnings:
        --line-length applies to check and plan; scan has no width rule.
    """
    command_parser = commands.add_parser(command_str)
    command_parser.add_argument("path", type=Path)
    command_parser.add_argument("--config", type=Path)
    command_parser.add_argument("--format", choices=["text", "json"],
                                default="text")
    command_parser.add_argument("--output", type=Path)
    if command_str != "scan":
        command_parser.add_argument(
            "--line-length", type=int,
            help="Maximum characters per line (default 79)",
        )
    if command_str == "plan":
        command_parser.add_argument("--start-line", type=int, required=True)
        command_parser.add_argument("--end-line", type=int, required=True)
        command_parser.add_argument("--name", required=True)
    else:
        command_parser.add_argument(
            "--fail-on", choices=["error", "warning"], default="error",
            help="Exit 1 on errors, or on warnings as well",
        )


def describe_runtime_dict() -> dict:
    """Describe the Python runtime running this installation.

    Args:
        None: Reads information from this process.
    Returns:
        dict: Interpreter, package, and supported-capability details.
    Warnings:
        Paths identify this installation, not another computer.
    """
    return {
        "tool": "funcloom",
        "version": __version__,
        "milestone": "Modularize, refine and block splitting",
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.system(),
        "package_path": str(Path(__file__).parent),
        "runtime_dependencies": [],
        "source_execution": False,
        "source_rewriting": False,
        "extraction_planning": True,
        "snippet_planning": True,
        "modularize": True,
        "notebook_cell_input": True,
        "interactive_context": True,
        "mathematical_naming": True,
        "llm_required": False,
    }


def write_report_none(
    output_path: Path, content_str: str, format_str: str,
) -> None:
    """Create a report without overwriting an existing file or source.

    Args:
        output_path (Path): New .json or .txt report destination.
        content_str (str): Already-rendered report.
        format_str (str): Output format determining the allowed extension.
    Returns:
        None: Writes the new report.
    Warnings:
        Existing files are refused; choose a new destination to repeat.
    """
    suffix_str = ".json" if format_str == "json" else ".txt"
    if output_path.suffix.lower() != suffix_str:
        raise ValueError(f"Report output must use {suffix_str}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as report_file:
        report_file.write(content_str)


def main(argv_list: list[str] | None = None) -> int:
    """Run one command and return its documented process exit status.

    Args:
        argv_list (list[str] | None): Explicit arguments or process arguments.
    Returns:
        int: 0 completed; 1 findings reached threshold; 2 usage/I/O failure.
    Warnings:
        Warnings do not fail by default; use --fail-on warning for a gate.
    """
    if not (sys.argv[1:] if argv_list is None else argv_list):
        sys.stdout.write(QUICK_START_STR)
        return 0
    arguments = build_parser().parse_args(argv_list)
    if arguments.command == "doctor":
        runtime_dict = describe_runtime_dict()
        if arguments.format == "json":
            print(json.dumps(runtime_dict, indent=2))
        else:
            for key_str, runtime_detail in runtime_dict.items():
                print(f"{key_str}: {runtime_detail}")
        return 0
    try:
        if arguments.command == "snippet":
            return run_snippet_int(arguments)
        if arguments.command == "modularize":
            return run_modularize_int(arguments)
        if arguments.command == "refine":
            return run_refine_int(arguments)
        if arguments.command == "plan":
            return run_plan_int(arguments)
        profile = load_command_profile(arguments)
        operation = (
            check_project_report if arguments.command == "check"
            else scan_project_report
        )
        report = operation(arguments.path, profile)
        rendered_str = render_report_str(report, arguments.format)
        if arguments.output is None:
            print(rendered_str, end="")
        else:
            write_report_none(arguments.output, rendered_str, arguments.format)
            print(f"Report created: {arguments.output}")
        failure_severities_set = {"error"}
        if arguments.fail_on == "warning":
            failure_severities_set.add("warning")
        return int(any(
            finding.severity in failure_severities_set
            for finding in report.diagnostics
        ))
    except (OSError, UnicodeError, ValueError) as error:
        print(f"funcloom: {error}", file=sys.stderr)
        return 2


def load_command_profile(arguments: argparse.Namespace) -> RuleProfile:
    """Load the explicit profile and apply an optional line-length choice.

    Args:
        arguments (argparse.Namespace): Parsed --config and --line-length.
    Returns:
        RuleProfile: Validated settings for this command.
    Warnings:
        --line-length overrides the profile file's line_length setting.
    """
    profile = load_profile(arguments.config)
    line_length_int = getattr(arguments, "line_length", None)
    if line_length_int is None:
        return profile
    return apply_line_length_profile(profile, line_length_int)


def run_plan_int(arguments: argparse.Namespace) -> int:
    """Run an explicit extraction plan through the same public Python API.

    Args:
        arguments (argparse.Namespace): Parsed plan command options.
    Returns:
        int: Zero for a review candidate; one for a refused plan.
    Warnings:
        Exit zero never authorizes applying a source transformation.
    """
    plan_report = plan_extraction_report(
        arguments.path, arguments.start_line, arguments.end_line,
        arguments.name, load_command_profile(arguments),
    )
    rendered_str = render_plan_str(plan_report, arguments.format)
    if arguments.output is None:
        print(rendered_str, end="")
    else:
        write_report_none(arguments.output, rendered_str, arguments.format)
        print(f"Plan created: {arguments.output}")
    return int(plan_report.status != "candidate_for_review")
