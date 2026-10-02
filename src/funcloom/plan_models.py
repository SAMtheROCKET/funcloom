"""Source-linked extraction proposals, never executable approval records."""

from dataclasses import dataclass, field

from funcloom._version import __version__
from funcloom.models import Diagnostic


@dataclass(frozen=True)
class BindingFact:
    """A name occurrence and its declared, unverified annotation if known."""

    name: str
    line: int
    annotation: str | None = None
    type_evidence: str = "unknown"


@dataclass
class ModuleBindings:
    """Direct module bindings and separate unverified type declarations."""

    bound: dict[str, BindingFact] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    statuses: dict[str, "NameResolution"] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectFact:
    """Syntax evidence for a possible effect, never runtime confirmation."""

    kind: str
    line: int
    column_utf8: int
    end_line: int
    end_column_utf8: int
    region: str
    detail: str
    evidence: str = "syntactic"


@dataclass(frozen=True)
class BindingSite:
    """A syntactic module-scope binding, deletion, or namespace-wide risk."""

    name: str
    kind: str
    certainty: str
    region: str
    line: int
    column_utf8: int
    visible_line: int
    visible_column_utf8: int


@dataclass(frozen=True)
class NameResolution:
    """Lexical status of one selected read and the sites that may reach it."""

    name: str
    line: int
    column_utf8: int
    status: str
    detail: str
    sites: list[BindingSite] = field(default_factory=list)


@dataclass
class ExtractionPlan:
    """A versioned review artifact with explicit refusal and proof limits."""

    source_path: str
    start_line: int
    end_line: int
    function_name: str
    schema_version: str = "plan-3"
    tool_version: str = __version__
    scope: str = "module"
    status: str = "refused"
    source_sha256: str | None = None
    fragment_sha256: str | None = None
    source_fragment: str | None = None
    inputs: list[BindingFact] = field(default_factory=list)
    outputs: list[BindingFact] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    function_preview: str | None = None
    caller_preview: str | None = None
    preview_compiles: bool = False
    review_required: bool = True
    can_apply: bool = False
    source_rewriting: bool = False
    behavior_verified: bool = False
    assumptions: list[str] = field(default_factory=list)
    validation_required: list[str] = field(default_factory=list)
    effect_analysis: str = "not_run"
    effects: list[EffectFact] = field(default_factory=list)
    effect_limitations: list[str] = field(default_factory=list)
    binding_analysis: str = "not_run"
    binding_sites: list[BindingSite] = field(default_factory=list)
    name_resolutions: list[NameResolution] = field(default_factory=list)
    binding_limitations: list[str] = field(default_factory=list)


def append_issue_none(
    plan_report: ExtractionPlan, code_str: str, line_int: int,
    message_str: str,
) -> None:
    """Add a source-located refusal reason to a planning report.

    Args:
        plan_report (ExtractionPlan): Report being assembled.
        code_str (str): Stable diagnostic identifier.
        line_int (int): One-based source location.
        message_str (str): Reason the supported subset cannot cover this.
    Returns:
        None: Appends a diagnostic without editing source.
    Warnings:
        A diagnostic is a refusal, not a suggested automatic repair.
    """
    plan_report.diagnostics.append(Diagnostic(
        code_str, "error", plan_report.source_path, line_int, 1, message_str,
    ))
