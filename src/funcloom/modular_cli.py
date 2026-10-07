"""Thin command-line wrapper and report rendering for modularize."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from funcloom.config import (
    RuleProfile, apply_line_length_profile, load_profile
)
from funcloom.modular_models import ModularReport, ProjectReport
from funcloom.modular_project import modularize_project_report
from funcloom.modular_source import parse_cells_list
from funcloom.modularize import modularize_report
from funcloom.refine import RefineOptions, RefineReport, refine_file_report


def add_modularize_parser_none(commands: argparse._SubParsersAction) -> None:
    """Register the modularize command.

    Args:
        commands (argparse._SubParsersAction): Existing subcommands.
    Returns:
        None: Adds the command and its options.
    Warnings:
        Without --output the command only plans; nothing is written.
    """
    parser = commands.add_parser(
        "modularize", help="Turn a script or notebook into a package")
    parser.add_argument(
        "path", help="A .py/.ipynb file, a project folder, or - for stdin")
    parser.add_argument("--entries",
                        help="Folder mode: entry scripts, e.g. a.py,b/c.py")
    parser.add_argument("--skip-data", action="store_true",
                        help="Folder mode: copy only Python files")
    parser.add_argument("--cells", help="Notebook cells, e.g. 2,4-6")
    parser.add_argument("--output", type=Path,
                        help="New folder to write the package into")
    parser.add_argument("--package-name")
    parser.add_argument("--line-length", type=int)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--show-files", action="store_true",
                        help="Print every generated file")
    add_refine_options_none(parser)


def add_refine_options_none(parser: argparse.ArgumentParser) -> None:
    """Add the function-splitting and documentation options.

    Args:
        parser (argparse.ArgumentParser): Command parser.
    Returns:
        None: Adds --keep-long-functions, --document/--no-document and
            --trust-with-blocks.
    Warnings:
        Splitting and documentation are on by default; trusting with
        blocks is opt-in.
    """
    parser.add_argument("--keep-long-functions", action="store_true",
                        help="Do not split functions over 40 lines")
    parser.add_argument("--document", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Add docstrings that describe what the code "
                             "shows to functions that have none (default; "
                             "--no-document leaves them out)")
    parser.add_argument(
        "--trust-with-blocks", action="store_true",
        help="Treat values bound in with blocks as bound, unless the "
             "context manager is a known suppressor such as suppress")


def read_refine_options_info(arguments: argparse.Namespace) -> RefineOptions:
    """Read refinement options from parsed arguments.

    Args:
        arguments (argparse.Namespace): Parsed options.
    Returns:
        RefineOptions: Enabled refinements.
    Warnings:
        Defaults match the Python API.
    """
    return RefineOptions(not arguments.keep_long_functions,
                         arguments.document, arguments.trust_with_blocks)


def add_refine_parser_none(commands: argparse._SubParsersAction) -> None:
    """Register the refine command for files and folders.

    Args:
        commands (argparse._SubParsersAction): Existing subcommands.
    Returns:
        None: Adds the command.
    Warnings:
        Output is always a new file or folder.
    """
    parser = commands.add_parser(
        "refine", help="Split long functions and wrap lines in a copy")
    parser.add_argument("path", help="A .py file or a project folder")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-data", action="store_true")
    parser.add_argument("--line-length", type=int)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    add_refine_options_none(parser)


def run_refine_int(arguments: argparse.Namespace) -> int:
    """Run refine and print its report.

    Args:
        arguments (argparse.Namespace): Parsed options.
    Returns:
        int: 0 when written, 1 when refused.
    Warnings:
        Folders are copied without converting entry scripts.
    """
    profile_info = load_profile(arguments.config)
    if arguments.line_length is not None:
        profile_info = apply_line_length_profile(profile_info,
                                                 arguments.line_length)
    if Path(arguments.path).is_dir():
        report_info = modularize_project_report(
            arguments.path, arguments.output, None, arguments.skip_data,
            profile_info, read_refine_options_info(arguments),
            convert_bool=False)
        print(render_project_str(report_info, arguments.format, False),
              end="")
        return int(report_info.status == "refused")
    report_info = refine_file_report(arguments.path, arguments.output,
                                     profile_info,
                                     read_refine_options_info(arguments))
    if arguments.format == "json":
        print(json.dumps(asdict(report_info), indent=2))
    else:
        print("\n".join(refine_lines_list(report_info)))
    return int(report_info.status == "refused")


def refine_lines_list(report_info: RefineReport) -> list[str]:
    """Summarize a single-file refine run.

    Args:
        report_info (RefineReport): Result.
    Returns:
        list[str]: Text lines.
    Warnings:
        Notes list functions that were left unchanged and why.
    """
    return (
        [
            f"FuncLoom {report_info.tool_version} | refine | "
            f"{report_info.status}", f"Source: {report_info.source}",
            f"Output: {report_info.output}"]
        + [
            f"Split: {split_function_str}"
            for split_function_str in report_info.split_functions]
        + [
            f"Documented: {documented_function_str}"
            for documented_function_str in report_info.documented_functions]
        + [
            f"ERROR {diagnostic_info.code}: {diagnostic_info.message}"
            for diagnostic_info in report_info.diagnostics]
        + [f"- {note_str}" for note_str in report_info.notes])


def run_modularize_int(arguments: argparse.Namespace) -> int:
    """Run modularize and print its report.

    Args:
        arguments (argparse.Namespace): Parsed command options.
    Returns:
        int: 0 when planned or written, 1 when refused.
    Warnings:
        The original file is never changed.
    """
    profile_info = load_profile(arguments.config)
    if arguments.line_length is not None:
        profile_info = apply_line_length_profile(profile_info,
                                                 arguments.line_length)
    if arguments.path != "-" and Path(arguments.path).is_dir():
        return run_project_int(arguments, profile_info)
    source_text = None
    if arguments.path == "-":
        if arguments.cells is not None:
            raise ValueError("stdin input cannot use --cells")
        source_text = sys.stdin.read(profile_info.max_file_bytes + 1)
    report_info = modularize_report(
        None if source_text is not None else arguments.path, source_text,
        arguments.output, parse_cells_list(arguments.cells),
        arguments.package_name, profile_info,
        read_refine_options_info(arguments))
    print(render_modular_str(report_info, arguments.format,
                             arguments.show_files), end="")
    return int(report_info.status == "refused")


def render_modular_str(
    report_info: ModularReport, format_str: str, show_files_bool: bool,
) -> str:
    """Render a modularize report as text or JSON.

    Args:
        report_info (ModularReport): Result to show.
        format_str (str): text or json.
        show_files_bool (bool): Include generated file contents.
    Returns:
        str: Report ending in a newline.
    Warnings:
        JSON omits file contents unless show_files_bool is set.
    """
    if format_str == "json":
        report_dict = asdict(report_info)
        if not show_files_bool:
            for file_dict in report_dict["files"]:
                file_dict.pop("text")
        return json.dumps(report_dict, indent=2) + "\n"
    lines_list = [
        f"FuncLoom {report_info.tool_version} | modularize | "
        f"{report_info.status}",
        f"Source: {report_info.source_name}",
        f"Package: {report_info.package_name}"
        + (f" -> {report_info.output_dir}" if report_info.output_dir
           else " (not written; add --output FOLDER)"),
    ]
    lines_list += summarize_report_lines_list(report_info)
    if show_files_bool:
        for file_info in report_info.files:
            lines_list += ["", f"===== {file_info.path} =====",
                           file_info.text.rstrip("\n")]
    return "\n".join(lines_list) + "\n"


def summarize_report_lines_list(report_info: ModularReport) -> list[str]:
    """List files, steps, moves, diagnostics and notes as text lines.

    Args:
        report_info (ModularReport): Result to summarize.
    Returns:
        list[str]: Report body lines.
    Warnings:
        Line numbers refer to the combined program text.
    """
    lines_list = ["", "Files:"] + [
        f"  {file_info.path} ({file_info.lines} lines)"
        for file_info in report_info.files]
    lines_list += ["", "Steps, in order:"]
    for index_int, step_info in enumerate(report_info.steps, 1):
        origin_str = f"{step_info.origin}, " if step_info.origin else ""
        lines_list.append(
            f"  {index_int}. {step_info.name} ({origin_str}lines "
            f"{step_info.first_line}-{step_info.last_line}) inputs: "
            f"{', '.join(step_info.inputs) or '-'}; outputs: "
            f"{', '.join(step_info.outputs) or '-'}")
        lines_list += [f"     merged: {merge_reason_str}"
                       for merge_reason_str in step_info.merge_reasons]
    lines_list += ["", "Moved definitions:"] + [
        f"  {name_str} -> {path_str}"
        for name_str, path_str in report_info.moved_definitions.items()
    ] or ["  none"]
    lines_list += ["", "Constants:"] + [
        f"  {old_str} -> {new_str}"
        for old_str, new_str in report_info.constants.items()]
    lines_list += [""] + [
        f"{diagnostic_info.severity.upper()} {diagnostic_info.code} "
        f"line {diagnostic_info.line}: {diagnostic_info.message}"
        for diagnostic_info in report_info.diagnostics]
    lines_list += [
        f"Split: {split_function_str}"
        for split_function_str in report_info.split_functions]
    lines_list += [
        f"Documented: {documented_function_str}"
        for documented_function_str in report_info.documented_functions]
    lines_list += ["Notes:"] + [
        f"- {note_str}" for note_str in report_info.notes]
    if report_info.status == "written":
        lines_list += ["", "Run it from the output folder:",
                       f"  python {report_info.files[0].path}"]
    return lines_list


def run_project_int(
    arguments: argparse.Namespace, profile_info: RuleProfile,
) -> int:
    """Run folder mode and print its report.

    Args:
        arguments (argparse.Namespace): Parsed command options.
        profile_info (RuleProfile): Limits and excluded folders.
    Returns:
        int: 0 when planned or written, 1 when refused.
    Warnings:
        --cells and --package-name apply only to single files.
    """
    if arguments.cells is not None or arguments.package_name is not None:
        raise ValueError("--cells and --package-name need a single file")
    entries_list = (
        [
            entry_path_str.strip()
            for entry_path_str in arguments.entries.split(",")]
        if arguments.entries else None)
    report_info = modularize_project_report(
        arguments.path, arguments.output, entries_list, arguments.skip_data,
        profile_info, read_refine_options_info(arguments))
    print(render_project_str(report_info, arguments.format,
                             arguments.show_files), end="")
    return int(report_info.status == "refused")


def project_header_lines_list(report_info: ProjectReport) -> list[str]:
    """Summarize a folder run: status, counts and scripts kept unchanged.

    Args:
        report_info (ProjectReport): Result to summarize.
    Returns:
        list[str]: Header lines.
    Warnings:
        Kept scripts are copied byte-for-byte.
    """
    converted_int = sum(1 for entry_info in report_info.entries
                        if entry_info.status != "refused")
    lines_list = [
        f"FuncLoom {report_info.tool_version} | modularize folder | "
        f"{report_info.status}",
        f"Project: {report_info.root}",
        f"Output: {report_info.output_dir or '(not written; add --output)'}",
        f"Entry scripts converted: {converted_int}",
        f"Files copied unchanged: {len(report_info.copied_files)} "
        f"({report_info.copied_bytes} bytes)",
    ]
    return lines_list + [
        f"  kept unchanged: {relative_str} ({reason_str})"
        for relative_str, reason_str in report_info.kept_scripts.items()]


def render_project_str(
    report_info: ProjectReport, format_str: str, show_files_bool: bool,
) -> str:
    """Render a folder-mode report as text or JSON.

    Args:
        report_info (ProjectReport): Result to show.
        format_str (str): text or json.
        show_files_bool (bool): Include generated file contents.
    Returns:
        str: Report ending in a newline.
    Warnings:
        Per-entry details use the single-file layout.
    """
    if format_str == "json":
        report_dict = asdict(report_info)
        for entry_dict in report_dict["entries"]:
            for file_dict in entry_dict["files"]:
                if not show_files_bool:
                    file_dict.pop("text")
        return json.dumps(report_dict, indent=2) + "\n"
    lines_list = project_header_lines_list(report_info)
    lines_list += [f"ERROR {diagnostic_info.code}: {diagnostic_info.message}"
                   for diagnostic_info in report_info.diagnostics]
    for entry_info in report_info.entries:
        lines_list += ["", "=" * 60,
                       render_modular_str(entry_info, "text",
                                          show_files_bool).rstrip("\n")]
    if report_info.orchestrator:
        lines_list += ["", "Run a pipeline from the output folder:",
                       f"  python {report_info.orchestrator} [NAME]",
                       "or run any converted script exactly as before."]
    lines_list += [
        f"Refined: {refined_file_str}"
        for refined_file_str in report_info.refined_files]
    lines_list += [
        f"Split: {split_function_str}"
        for split_function_str in report_info.split_functions]
    lines_list += [
        f"Documented: {documented_function_str}"
        for documented_function_str in report_info.documented_functions]
    lines_list += [f"- {note_str}" for note_str in report_info.notes]
    return "\n".join(lines_list) + "\n"
