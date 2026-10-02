"""FuncLoom's read-only inventory, rule, and extraction-planning APIs."""

from funcloom.api import check_project_report, scan_project_report
from funcloom.config import RuleProfile, load_profile
from funcloom.planning import plan_extraction_report
from funcloom.refine import RefinedSource, refine_source_text
from funcloom._version import __version__
from funcloom.snippet_models import SnippetContext
from funcloom.snippets import plan_snippet_file_report, plan_snippet_report

__all__ = [
    "RefinedSource",
    "RuleProfile",
    "SnippetContext",
    "plan_snippet_file_report",
    "plan_snippet_report",
    "refine_source_text",
    "check_project_report",
    "load_profile",
    "plan_extraction_report",
    "scan_project_report",
]
