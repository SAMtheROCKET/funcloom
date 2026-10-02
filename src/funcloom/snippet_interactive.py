"""Optional terminal context choices; batch commands never prompt."""

from dataclasses import replace
import sys

from funcloom.config import (
    LINE_LENGTH_LIMITS_TUPLE, RuleProfile, apply_line_length_profile,
)
from funcloom.snippet_models import SnippetContext, SnippetReport


def read_answer_str(question_str: str) -> str:
    """Read one explicit terminal answer while keeping JSON stdout clean.

    Args:
        question_str (str): Concise context or preference prompt.
    Returns:
        str: Stripped answer; an empty answer keeps the displayed default.
    Warnings:
        End-of-input cancels the wizard instead of implying consent.
    """
    print(question_str, file=sys.stderr, end=" ", flush=True)
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt) as error:
        raise ValueError("Context entry cancelled; source unchanged") from (
            error
        )


def ask_interactive_context_info(
    report_info: SnippetReport, default_line_length_int: int = 79,
) -> SnippetContext:
    """Offer source naming, domain meanings or neutral mathematical naming.

    Args:
        report_info (SnippetReport): Initial source-only analysis.
        default_line_length_int (int): Width shown if none is chosen.
    Returns:
        SnippetContext: Explicit user choices for a second analysis pass.
    Warnings:
        The wizard cannot approve an unsupported transformation.
    """
    if not sys.stdin.isatty():
        raise ValueError("--interactive requires a terminal; use --context")
    context_info = replace(report_info.context)
    choice_str = read_answer_str(
        "Context: [1] No additional context [2] Small project context "
        "[3] Mathematical naming (1):",
    ) or "1"
    if choice_str not in ("1", "2", "3"):
        raise ValueError("Choose context option 1, 2 or 3")
    context_info.line_length = prompt_line_length_int(
        context_info.line_length, default_line_length_int,
    )
    if any(
            question_info.code == "SNIP001"
            for question_info in report_info.questions):
        answer_str = read_answer_str(
            "Only setup found. Keep assignments in the function? [y/N]",
        )
        if answer_str.lower() == "y":
            context_info.literal_policy = "fixed"
    if choice_str != "1":
        context_info.naming_mode = (
            "domain" if choice_str == "2" else "mathematical"
        )
        prompt_purpose_none(context_info, report_info)
    return context_info


def prompt_line_length_int(
    chosen_int: int | None, default_int: int,
) -> int | None:
    """Ask for the maximum draft line length until the answer is valid.

    Args:
        chosen_int (int | None): Width already set by context or options.
        default_int (int): Profile width shown when none was chosen.
    Returns:
        int | None: New width, or the existing choice when blank.
    Warnings:
        End-of-input cancels the wizard; the source is never changed.
    """
    minimum_int, maximum_int = LINE_LENGTH_LIMITS_TUPLE
    while True:
        answer_str = read_answer_str(
            f"Maximum line length, {minimum_int}-{maximum_int} "
            f"({chosen_int or default_int}):",
        )
        if not answer_str:
            return chosen_int
        line_length_int = (
            int(answer_str) if answer_str.isdecimal() else 0
        )
        try:
            apply_line_length_profile(RuleProfile(), line_length_int)
        except ValueError as error:
            print(error, file=sys.stderr)
            continue
        return line_length_int


def prompt_purpose_none(
    context_info: SnippetContext, report_info: SnippetReport,
) -> None:
    """Capture operation intent separately from value types and meanings.

    Args:
        context_info (SnippetContext): Explicit user choices to update.
        report_info (SnippetReport): Discovered inputs and outputs.
    Returns:
        None: Adds optional text and per-value declarations.
    Warnings:
        Descriptions document intent; they do not implement business logic.
    """
    if context_info.naming_mode == "domain":
        context_info.project_context = read_answer_str(
            "Brief project context:",
        )
    context_info.summary = read_answer_str("Operation summary (optional):")
    context_info.function_name = (
        read_answer_str("Function name (keep current proposal):")
        or context_info.function_name
    )
    prompt_types_none(context_info, report_info)
    if context_info.naming_mode == "domain":
        prompt_meanings_none(context_info, report_info)


def prompt_types_none(
    context_info: SnippetContext, report_info: SnippetReport,
) -> None:
    """Collect optional numeric declarations for already discovered inputs.

    Args:
        context_info (SnippetContext): Explicit choices to update.
        report_info (SnippetReport): Source-only input proposals.
    Returns:
        None: Adds declarations only for nonempty answers.
    Warnings:
        These declarations neither cast nor validate runtime values.
    """
    context_info.input_types = dict(context_info.input_types)
    for value_info in report_info.values:
        if value_info.role == "input":
            type_str = read_answer_str(
                f"Type for {value_info.original_name}: int/float "
                f"(blank keeps {value_info.annotation or 'unknown'} "
                "proposal):",
            )
            if type_str:
                context_info.input_types[value_info.original_name] = type_str


def prompt_meanings_none(
    context_info: SnippetContext, report_info: SnippetReport,
) -> None:
    """Ask for local names and meanings once per discovered contract value.

    Args:
        context_info (SnippetContext): User mappings to update.
        report_info (SnippetReport): Source-linked contract values.
    Returns:
        None: Records explicit names and descriptions, including units.
    Warnings:
        Blank answers leave meaning unresolved; units are never inferred.
    """
    context_info.names = dict(context_info.names)
    context_info.descriptions = dict(context_info.descriptions)
    recorded_set = set()
    for value_info in report_info.values:
        name_str = value_info.original_name
        if name_str in recorded_set:
            continue
        recorded_set.add(name_str)
        stem_str = read_answer_str(
            f"Descriptive local name for '{name_str}' (blank keeps proposal):",
        )
        description_str = read_answer_str(
            f"Meaning/units of '{name_str}' (optional):",
        )
        if stem_str:
            context_info.names[name_str] = stem_str
        if description_str:
            context_info.descriptions[name_str] = description_str
