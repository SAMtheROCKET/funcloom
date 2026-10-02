"""Review-only snippet proposals with explicit context and type evidence."""

from dataclasses import dataclass, field

from funcloom._version import __version__
from funcloom.models import Diagnostic
from funcloom.plan_models import ExtractionPlan


@dataclass
class SnippetContext:
    """User intent, never executable instructions or a semantic proof."""

    project_context: str = ""
    summary: str = ""
    function_name: str = ""
    literal_policy: str = "parameters"
    input_types: dict[str, str] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    naming_mode: str = "source"
    line_length: int | None = None


@dataclass(frozen=True)
class SnippetSource:
    """One Python source or notebook cell, with original document identity."""

    name: str
    text: str
    document_sha256: str | None = None
    cell_index: int | None = None


@dataclass(frozen=True)
class SnippetValue:
    """An input/output annotation proposal, distinct from a runtime type."""

    original_name: str
    proposed_name: str
    annotation: str | None
    type_evidence: str
    role: str
    line: int
    name_evidence: str = "source_identifier"


@dataclass(frozen=True)
class SnippetQuestion:
    """A focused question exposed in both interactive and batch workflows."""

    code: str
    line: int
    prompt: str
    options: tuple[str, ...] = ()


@dataclass
class SnippetReport:
    """A contextual draft with unchanged source and no apply authorization."""

    source: SnippetSource
    context: SnippetContext
    schema_version: str = "snippet-1"
    tool_version: str = __version__
    status: str = "refused"
    source_sha256: str | None = None
    context_mode: str = "none"
    plan: ExtractionPlan | None = None
    values: list[SnippetValue] = field(default_factory=list)
    questions: list[SnippetQuestion] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    function_preview: str | None = None
    caller_preview: str | None = None
    preview_compiles: bool = False
    review_required: bool = True
    can_apply: bool = False
    source_rewriting: bool = False
    behavior_verified: bool = False
