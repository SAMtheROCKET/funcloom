"""Structured facts and diagnostics shared by the CLI and Python API."""

from dataclasses import dataclass, field
from typing import Any

from funcloom._version import __version__


@dataclass(frozen=True)
class Diagnostic:
    """A reported observation; field names form the public JSON contract."""

    code: str
    severity: str
    path: str
    line: int
    column: int
    message: str


@dataclass(frozen=True)
class ParameterInfo:
    """A declared parameter, without evaluating its type annotation."""

    name: str
    annotation: str | None
    kind: str
    line: int


@dataclass(frozen=True)
class FunctionInfo:
    """A function's declared contract and physical source extent."""

    qualified_name: str
    name: str
    line: int
    end_line: int
    physical_lines: int
    is_async: bool
    is_method: bool
    parameters: tuple[ParameterInfo, ...]
    return_annotation: str | None
    docstring: str | None


@dataclass
class ModuleInfo:
    """Facts obtained by parsing and compiling a source file only."""

    path: str
    sha256: str
    physical_lines: int
    imports: list[str] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    statements: list[dict[str, Any]] = field(default_factory=list)
    main_guards: list[dict[str, int]] = field(default_factory=list)


@dataclass
class ProjectReport:
    """A versioned report; absence of findings is not full compliance."""

    root: str
    mode: str
    profile: dict[str, Any]
    schema_version: str = "1"
    tool_version: str = __version__
    modules: list[ModuleInfo] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
