"""Records for turning one program into a modular package."""

import ast
from dataclasses import dataclass, field

from funcloom._version import __version__
from funcloom.models import Diagnostic


@dataclass
class ProgramSegment:
    """A notebook cell or script section that can start a new step."""

    title: str
    origin: str
    first_line: int
    last_line: int


@dataclass
class ProgramSource:
    """Combined Python text with provenance for its lines."""

    name: str
    text: str
    stem: str
    segments: list[ProgramSegment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    document_sha256: str | None = None


@dataclass
class StatementNames:
    """Names one top-level statement reads, binds and depends on."""

    direct_reads: set[str] = field(default_factory=set)
    nested_reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    global_writes: set[str] = field(default_factory=set)
    dynamic_line: int | None = None
    special_lines: dict[str, int] = field(default_factory=dict)
    has_calls_at_definition: bool = False


@dataclass
class TopStatement:
    """One top-level statement, its text range and its placement."""

    node: ast.stmt
    first_line: int
    last_line: int
    indent: int = 0
    kind: str = "executable"
    title: str = ""
    starts_section: bool = False
    names: StatementNames = field(default_factory=StatementNames)
    blank_before: bool = False


@dataclass
class StepPlan:
    """Consecutive executable statements that become one step function."""

    name: str
    title: str
    origin: str
    statements: list[TopStatement] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    merge_reasons: list[str] = field(default_factory=list)
    types: dict[str, str | None] = field(default_factory=dict)


@dataclass
class PackageDraft:
    """Everything needed to render the generated package."""

    package_name: str
    source: ProgramSource
    lines: list[str]
    statements: list[TopStatement]
    constants: dict[str, str]
    steps: list[StepPlan]
    width: int
    modules: dict[str, list[TopStatement]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    script_name: str = "main.py"


@dataclass
class StepRecord:
    """Serializable summary of a generated step."""

    name: str
    title: str
    origin: str
    first_line: int
    last_line: int
    inputs: list[str]
    outputs: list[str]
    merge_reasons: list[str]


@dataclass
class GeneratedFile:
    """One generated file; its text is kept out of JSON reports."""

    path: str
    sha256: str
    lines: int
    text: str = field(default="", repr=False)


@dataclass
class ModularReport:
    """Result of planning or writing a modular package."""

    source_name: str
    package_name: str
    schema_version: str = "modularize-1"
    tool_version: str = __version__
    status: str = "refused"
    output_dir: str | None = None
    source_sha256: str | None = None
    files: list[GeneratedFile] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
    moved_definitions: dict[str, str] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: dict[str, object] = field(default_factory=dict)
    split_functions: list[str] = field(default_factory=list)
    documented_functions: list[str] = field(default_factory=list)
    original_source_changed: bool = False
    review_required: bool = True
    behavior_verified: bool = False


@dataclass
class ProjectReport:
    """Result of modularizing every entry script in a folder."""

    root: str
    schema_version: str = "modularize-project-1"
    tool_version: str = __version__
    status: str = "refused"
    output_dir: str | None = None
    entries: list[ModularReport] = field(default_factory=list)
    kept_scripts: dict[str, str] = field(default_factory=dict)
    copied_files: list[str] = field(default_factory=list)
    copied_bytes: int = 0
    refined_files: list[str] = field(default_factory=list)
    split_functions: list[str] = field(default_factory=list)
    documented_functions: list[str] = field(default_factory=list)
    orchestrator: str | None = None
    newlines: dict[str, str] = field(default_factory=dict, repr=False)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    original_source_changed: bool = False
    review_required: bool = True
    behavior_verified: bool = False


def add_diagnostic_none(
    report_info: ModularReport, code_str: str, line_int: int,
    message_str: str, severity_str: str = "error",
) -> None:
    """Attach a located refusal or warning to a modularization report.

    Args:
        report_info (ModularReport): Report being assembled.
        code_str (str): Stable diagnostic identifier.
        line_int (int): One-based line in the combined program.
        message_str (str): Reason, written for the user.
        severity_str (str): error refuses writing; warning does not.
    Returns:
        None: Appends a diagnostic.
    Warnings:
        Notebook line numbers refer to the combined program text.
    """
    report_info.diagnostics.append(Diagnostic(
        code_str, severity_str, report_info.source_name, line_int, 1,
        message_str,
    ))
