"""Apply a reviewed extraction plan to a new file (M3, first increment).

The original file is never changed. The new file is the original text
before the region, the drafted function, its call and the original text
after the region. Before writing, the source hash is checked again, the
new text must compile, every statement outside the region must keep its
syntax tree, and the inserted function and call must equal the reviewed
previews. The output must not exist yet.
"""

import ast
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from funcloom.config import RuleProfile
from funcloom.modular_verify import (
    detect_newline_style_str, normalize_newlines_str,
)
from funcloom.plan_models import ExtractionPlan
from funcloom.planning import plan_extraction_report
from funcloom.syntax import read_source_tuple


@dataclass
class ApplyResult:
    """The plan and what applying it did.

    Args:
        plan: The extraction plan the output was built from.
        status: "written", "refused" (the plan was refused) or "failed".
        output: The written file, when status is "written".
        messages: Why nothing was written.
    """

    plan: ExtractionPlan
    status: str = "refused"
    output: str | None = None
    messages: list[str] = field(default_factory=list)


def apply_extraction_result(
    source_path: str | Path, start_line_int: int, end_line_int: int,
    function_name_str: str, output_path: str | Path,
    profile_info: RuleProfile | None = None,
) -> ApplyResult:
    """Plan an extraction and write the rewritten module to a new file.

    Args:
        source_path (str | Path): The Python file; it is never changed.
        start_line_int (int): First selected physical line.
        end_line_int (int): Last selected physical line.
        function_name_str (str): Name of the extracted function.
        output_path (str | Path): New file to create; it must not exist.
        profile_info (RuleProfile | None): Limits, or default settings.
    Returns:
        ApplyResult: The plan, and the written path or the reasons.
    Warnings:
        Behaviour is not proven: the plan's assumptions still apply, and
        the new file should be reviewed and tested before it is used.
    """
    profile_info = profile_info or RuleProfile()
    plan_report = plan_extraction_report(source_path, start_line_int,
                                         end_line_int, function_name_str,
                                         profile_info)
    result = ApplyResult(plan_report)
    if plan_report.status != "candidate_for_review":
        return result
    result.status = "failed"
    source_path, output_path = Path(source_path), Path(output_path)
    source_str, issue_str = read_unchanged_source_tuple(
        source_path, output_path, plan_report, profile_info)
    if issue_str:
        result.messages.append(issue_str)
        return result
    new_str = compose_module_str(source_str, plan_report)
    issue_str = find_rewrite_issue_str(source_str, new_str, plan_report)
    if issue_str:
        result.messages.append(issue_str)
        return result
    return write_new_file_result(result, output_path, source_str, new_str)


def read_unchanged_source_tuple(
    source_path: Path, output_path: Path, plan_report: ExtractionPlan,
    profile_info: RuleProfile,
) -> tuple[str, str | None]:
    """Read the source again and check the output target.

    Args:
        source_path (Path): The planned source file.
        output_path (Path): The new file to create.
        plan_report (ExtractionPlan): The plan with the source hash.
        profile_info (RuleProfile): Read limits.
    Returns:
        tuple: The source text, and why applying is refused (or None).
    Warnings:
        The hash is checked immediately before composing the new file.
    """
    if output_path.exists() or output_path.absolute() == (
            source_path.absolute()):
        return "", f"{output_path} exists; choose a new file."
    source_str, digest_str = read_source_tuple(source_path,
                                               profile_info.max_file_bytes)
    if digest_str != plan_report.source_sha256:
        return source_str, "The source changed after it was planned."
    return source_str, None


def compose_module_str(source_str: str, plan_report: ExtractionPlan) -> str:
    """The original text with the region replaced by function and call.

    Args:
        source_str (str): Decoded original source.
        plan_report (ExtractionPlan): A candidate plan.
    Returns:
        str: The rewritten module (LF line endings).
    Warnings:
        Two blank lines surround the new function, as PEP 8 suggests.
    """
    lines_list = normalize_newlines_str(source_str).splitlines(True)
    before_str = "".join(lines_list[:plan_report.start_line - 1])
    after_str = "".join(lines_list[plan_report.end_line:])
    if before_str and not before_str.endswith("\n"):
        before_str += "\n"
    gap_str = "\n\n" if before_str.strip() else ""
    return (before_str + gap_str + plan_report.function_preview + "\n\n"
            + plan_report.caller_preview + after_str)


def find_rewrite_issue_str(source_str: str, new_str: str,
                           plan_report: ExtractionPlan) -> str | None:
    """Check the rewritten module against the original and the previews.

    Args:
        source_str (str): Decoded original source.
        new_str (str): The rewritten module.
        plan_report (ExtractionPlan): The candidate plan.
    Returns:
        str | None: Why the rewrite is refused, or None when it passes.
    Warnings:
        Structural equality is not a proof of identical behaviour.
    """
    try:
        new_node = ast.parse(new_str)
        compile(new_node, "<funcloom-apply>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as error:
        return f"The rewritten file does not compile: {error}"
    old_body = ast.parse(source_str).body
    before_list = [node for node in old_body
                   if node.end_lineno < plan_report.start_line]
    after_list = [node for node in old_body
                  if node.lineno > plan_report.end_line]
    inserted_list = [*ast.parse(plan_report.function_preview).body,
                     *ast.parse(plan_report.caller_preview).body]
    expected_list = [*before_list, *inserted_list, *after_list]
    if [ast.dump(node) for node in new_node.body] != [
            ast.dump(node) for node in expected_list]:
        return ("The rewritten file differs from the original outside the "
                "region, or from the reviewed function and call.")
    return None


def write_new_file_result(result: ApplyResult, output_path: Path,
                          source_str: str, new_str: str) -> ApplyResult:
    """Create the output file with the source's line endings.

    Args:
        result (ApplyResult): The result to complete.
        output_path (Path): New file; creation fails if it exists.
        source_str (str): Original text, for its line-ending style.
        new_str (str): The rewritten module.
    Returns:
        ApplyResult: Marked written, or failed with the OS error.
    Warnings:
        The file is created exclusively; nothing is overwritten.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8",
                              newline=detect_newline_style_str(
                                  source_str)) as output_file:
            output_file.write(new_str)
    except OSError as error:
        result.messages.append(str(error))
        return result
    result.status, result.output = "written", str(output_path.absolute())
    result.messages.append("sha256 of the new file: " + sha256(
        output_path.read_bytes()).hexdigest())
    return result
