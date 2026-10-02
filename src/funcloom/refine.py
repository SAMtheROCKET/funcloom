"""Refine module text: split long functions, document, wrap long lines."""

import ast
from dataclasses import dataclass, field
from pathlib import Path
import tokenize

from funcloom._version import __version__
from funcloom.config import RuleProfile, validate_profile_none
from funcloom.function_docs import insert_docstrings_tuple
from funcloom.function_split_text import split_functions_text_tuple
from funcloom.modular_steps import enable_with_block_trust
from funcloom.modular_text import wrap_long_statements_tuple
from funcloom.models import Diagnostic
from funcloom.modular_verify import (
    detect_newline_style_str, normalize_newlines_str
)
from funcloom.syntax import read_source_tuple


@dataclass(frozen=True)
class RefineOptions:
    """Which refinements to apply."""

    split_functions: bool = True
    document: bool = False
    trust_with_blocks: bool = False
    wrap_lines: bool = True


@dataclass
class RefineReport:
    """Result of refining one file."""

    source: str
    schema_version: str = "refine-1"
    tool_version: str = __version__
    status: str = "refused"
    output: str | None = None
    split_functions: list[str] = field(default_factory=list)
    documented_functions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    original_source_changed: bool = False
    behavior_verified: bool = False


def apply_refinements_str(
    source_str: str, label_str: str, profile_info: RuleProfile,
    options_info: RefineOptions, report_info: RefineReport,
) -> str:
    """Apply the enabled refinements, each verified on its own.

    Args:
        source_str (str): Module text.
        label_str (str): File label for notes.
        profile_info (RuleProfile): Width and function size limits.
        options_info (RefineOptions): Enabled refinements.
        report_info (RefineReport): Names and notes destination.
    Returns:
        str: Refined text; unchanged where a step did not verify.
    Warnings:
        Documentation comes first so that its lines count towards the
        length that triggers splitting.
    """
    validate_profile_none(profile_info)
    if not check_compiles_bool(source_str, label_str, report_info):
        return source_str
    text_str = source_str
    if options_info.document:
        text_str, names_list = insert_docstrings_tuple(
            text_str, profile_info.line_length)
        report_info.documented_functions += [
            f"{label_str}: {function_name_str}"
            for function_name_str in names_list]
    if options_info.split_functions:
        with enable_with_block_trust(options_info.trust_with_blocks):
            text_str, notes_list, names_list = split_functions_text_tuple(
                text_str, profile_info.line_length,
                profile_info.function_target_lines)
        report_info.notes += [
            f"{label_str}: {note_str}" for note_str in notes_list]
        report_info.split_functions += [f"{label_str}: {function_name_str}"
                                        for function_name_str in names_list]
    if options_info.wrap_lines:
        wrapped_str, notes_list = wrap_long_statements_tuple(
            text_str, 0, profile_info.line_length, label_str)
        if has_same_tree_bool(text_str, wrapped_str):
            text_str = wrapped_str
            report_info.notes += notes_list
    return (text_str if check_compiles_bool(text_str, label_str, report_info)
            else source_str)


@dataclass
class RefinedSource:
    """Result of refine_source_text, FuncLoom's public refinement API.

    Args:
        text: Refined text; the input text when nothing could be applied.
        changed: Whether the text differs from the input.
        split_functions: Names of functions or blocks that were split.
        documented_functions: Names that received docstring skeletons.
        notes: Explanations, including refinements that were refused.
        diagnostics: Located errors (for example the input not compiling).
    Returns:
        RefinedSource: Plain data, stable across FuncLoom 0.x releases.
    Warnings:
        Every applied step was verified; a step that did not verify was
        skipped and explained in notes.
    """

    text: str
    changed: bool
    split_functions: list[str]
    documented_functions: list[str]
    notes: list[str]
    diagnostics: list[Diagnostic]


def refine_source_text(
    source_str: str, label_str: str = "<source>", *,
    line_length_int: int = 79, function_target_lines_int: int = 40,
    split_functions_bool: bool = True, document_bool: bool = True,
    wrap_lines_bool: bool = True, trust_with_blocks_bool: bool = False,
) -> RefinedSource:
    """Refine Python text in memory: docstrings, splitting and wrapping.

    Args:
        source_str (str): Python module text.
        label_str (str): Name used in notes and diagnostics.
        line_length_int (int): Maximum line length (40-200).
        function_target_lines_int (int): Functions longer than this are
            split.
        split_functions_bool (bool): Split long functions and blocks.
        document_bool (bool): Add docstring skeletons where missing.
        wrap_lines_bool (bool): Wrap long simple statements.
        trust_with_blocks_bool (bool): Trust with-block bindings when
            splitting (see REFINE.md).
    Returns:
        RefinedSource: Refined text and what was done.
    Warnings:
        This is the public API other tools (such as RefacTrail) use; it
        never reads or writes files and never executes the code.
    """
    profile_info = RuleProfile(line_length=line_length_int,
                               function_target_lines=function_target_lines_int)
    report_info = RefineReport(label_str)
    options_info = RefineOptions(split_functions_bool, document_bool,
                                 trust_with_blocks_bool, wrap_lines_bool)
    text_str = apply_refinements_str(source_str, label_str, profile_info,
                                     options_info, report_info)
    return RefinedSource(text_str, text_str != source_str,
                         report_info.split_functions,
                         report_info.documented_functions,
                         report_info.notes, report_info.diagnostics)


def check_compiles_bool(
    source_str: str, label_str: str, report_info: RefineReport,
) -> bool:
    """Compile without execution and record a located refusal on failure.

    Args:
        source_str (str): Original or generated Python text.
        label_str (str): File path for diagnostics.
        report_info (RefineReport): Diagnostic destination.
    Returns:
        bool: True only when contextual compilation succeeds.
    Warnings:
        A parsable AST alone does not establish valid Python code.
    """
    try:
        compile(source_str, label_str, "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as error:
        report_info.diagnostics.append(Diagnostic(
            "MOD001", "error", label_str,
            getattr(error, "lineno", None) or 1,
            getattr(error, "offset", None) or 1,
            f"Python compilation failed: {error}."))
        return False
    return True


def has_same_tree_bool(old_str: str, new_str: str) -> bool:
    """Check that two texts have the same syntax tree.

    Args:
        old_str (str): Original text.
        new_str (str): Reformatted text.
    Returns:
        bool: True when both parse to equal trees.
    Warnings:
        Positions and comments are not compared.
    """
    try:
        return ast.dump(ast.parse(old_str)) == ast.dump(ast.parse(new_str))
    except SyntaxError:
        return False


def read_utf8_text_str(file_path: Path, max_bytes_int: int) -> str | None:
    """Read a file for refinement when it can be written back as UTF-8.

    Args:
        file_path (Path): Python file.
        max_bytes_int (int): Size limit.
    Returns:
        str | None: Text, or None for other encodings or unreadable files.
    Warnings:
        Files that declare another encoding (a coding cookie such as
        latin-1) are never rewritten: writing them as UTF-8 under the old
        declaration would change their text. They are copied unchanged in
        folder mode and refused by the single-file command.
    """
    try:
        text_str, _ = read_source_tuple(file_path, max_bytes_int)
        with file_path.open("rb") as source_file:
            encoding_str, _ = tokenize.detect_encoding(source_file.readline)
    except (OSError, UnicodeError, ValueError, SyntaxError):
        return None
    if encoding_str not in ("utf-8", "utf-8-sig"):
        return None
    return text_str


def refine_file_report(
    source_path: str | Path, output_path: str | Path,
    profile_info: RuleProfile | None = None,
    options_info: RefineOptions | None = None,
) -> RefineReport:
    """Refine one Python file into a new file.

    Args:
        source_path (str | Path): Existing .py file.
        output_path (str | Path): New .py file to create.
        profile_info (RuleProfile | None): Limits.
        options_info (RefineOptions | None): Enabled refinements.
    Returns:
        RefineReport: What changed, with notes.
    Warnings:
        The source is never changed and the output must not exist.
    """
    profile_info = profile_info or RuleProfile()
    validate_profile_none(profile_info)
    options_info = options_info or RefineOptions()
    source_path, output_path = Path(source_path), Path(output_path)
    report_info = RefineReport(str(source_path.absolute()))
    text_str = read_utf8_text_str(source_path, profile_info.max_file_bytes)
    if text_str is None:
        report_info.diagnostics.append(Diagnostic(
            "MOD001", "error", report_info.source, 1, 1,
            "Not UTF-8 Python source: the file cannot be decoded or "
            "declares another encoding; only UTF-8 files are refined."))
        return report_info
    refined_str = apply_refinements_str(text_str, source_path.name,
                                        profile_info, options_info,
                                        report_info)
    if report_info.diagnostics:
        return report_info
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open(
                "x", encoding="utf-8",
                newline=detect_newline_style_str(text_str)) as file:
            file.write(normalize_newlines_str(refined_str))
    except OSError as error:
        report_info.diagnostics.append(Diagnostic(
            "MOD006", "error", report_info.source, 1, 1, str(error)))
        return report_info
    report_info.status, report_info.output = "written", str(
        output_path.absolute())
    return report_info
