"""Thin command integration for snippets, context files and notebook cells."""

import argparse
from pathlib import Path
import sys

from funcloom.config import load_profile
from funcloom.snippet_context import load_snippet_context
from funcloom.snippet_interactive import ask_interactive_context_info
from funcloom.snippet_models import SnippetContext, SnippetSource
from funcloom.snippet_reporting import render_snippet_str
from funcloom.snippet_source import read_snippet_source
from funcloom.snippets import build_snippet_report


def add_snippet_parser_none(commands: argparse._SubParsersAction) -> None:
    """Register a separate snippet workflow without altering explicit plans.

    Args:
        commands (argparse._SubParsersAction): Existing CLI subcommands.
    Returns:
        None: Adds one read-only command and its options.
    Warnings:
        Interactive prompts are opt-in; there is no apply option.
    """
    parser = commands.add_parser("snippet", help="Draft a function from code")
    parser.add_argument("path", help="A .py/.ipynb file, or - for stdin")
    parser.add_argument("--cell", type=int, help="One-based cell index")
    parser.add_argument("--name", help="Optional operation name")
    parser.add_argument(
        "--naming", choices=("source", "domain", "mathematical"),
    )
    parser.add_argument("--literal-policy", choices=("parameters", "fixed"))
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--line-length", type=int,
        help="Maximum characters per draft line (default 79)",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--context", type=Path, help="Project context TOML")
    group.add_argument("--no-context", action="store_true")
    group.add_argument("--interactive", action="store_true")


def read_command_source_info(
    arguments: argparse.Namespace, max_bytes_int: int,
) -> SnippetSource:
    """Read bounded stdin or one document for a snippet command.

    Args:
        arguments (argparse.Namespace): Source and notebook selection.
        max_bytes_int (int): Configured input size cap.
    Returns:
        SnippetSource: Source text and available document provenance.
    Warnings:
        Stdin cannot simultaneously supply source and interactive answers.
    """
    if arguments.path != "-":
        return read_snippet_source(
            arguments.path, arguments.cell, max_bytes_int,
        )
    if arguments.interactive or arguments.cell is not None:
        raise ValueError("stdin source cannot use --interactive or --cell")
    source_str = sys.stdin.read(max_bytes_int + 1)
    if len(source_str.encode("utf-8")) > max_bytes_int:
        raise ValueError("stdin source exceeds the configured byte limit")
    return SnippetSource("<stdin>", source_str)


def load_command_context_info(arguments: argparse.Namespace) -> SnippetContext:
    """Load optional context TOML and apply explicit command-line choices.

    Args:
        arguments (argparse.Namespace): Parsed snippet command options.
    Returns:
        SnippetContext: Context where command-line options override TOML.
    Warnings:
        Values are validated later, when the report is built.
    """
    context_info = (
        load_snippet_context(arguments.context)
        if arguments.context else SnippetContext()
    )
    for option_str, field_str in (
        ("name", "function_name"), ("naming", "naming_mode"),
        ("literal_policy", "literal_policy"),
        ("line_length", "line_length"),
    ):
        if getattr(arguments, option_str) is not None:
            setattr(context_info, field_str, getattr(arguments, option_str))
    return context_info


def run_snippet_int(arguments: argparse.Namespace) -> int:
    """Run the same public snippet service for terminal and editor clients.

    Args:
        arguments (argparse.Namespace): Parsed snippet command options.
    Returns:
        int: Zero for a candidate; one for refusal or required clarification.
    Warnings:
        Exit zero does not permit apply or verify target runtime behavior.
    """
    from funcloom.cli import write_report_none

    profile_info = load_profile(arguments.config)
    context_info = load_command_context_info(arguments)
    source_info = read_command_source_info(
        arguments, profile_info.max_file_bytes)
    report_info = build_snippet_report(source_info, context_info, profile_info)
    if arguments.interactive:
        context_info = ask_interactive_context_info(
            report_info, profile_info.line_length,
        )
        report_info = build_snippet_report(
            source_info, context_info, profile_info,
        )
    rendered_str = render_snippet_str(report_info, arguments.format)
    if arguments.output is None:
        print(rendered_str, end="")
    else:
        write_report_none(arguments.output, rendered_str, arguments.format)
        print(f"Snippet report created: {arguments.output}")
    return int(report_info.status != "candidate_for_review")
