"""Produce compiled review text from retained source, with no target writes."""

import ast
from io import StringIO

from funcloom.config import RuleProfile
from funcloom.plan_models import ExtractionPlan, append_issue_none


def render_draft_signature_str(plan_report: ExtractionPlan) -> str:
    """Render an explicit user-named signature without invented annotations.

    Args:
        plan_report (ExtractionPlan): Proposed name and inferred dependencies.
    Returns:
        str: Function signature with one input per line when needed.
    Warnings:
        Declared types stay in metadata until annotation moves are validated.
    """
    if not plan_report.inputs:
        return f"def {plan_report.function_name}():\n"
    parameters_str = "".join(
        f"    {binding_info.name},\n" for binding_info in plan_report.inputs
    )
    return f"def {plan_report.function_name}(\n{parameters_str}):\n"


def draft_docstring_str(plan_report: ExtractionPlan) -> str:
    """Describe the proposal's source provenance and review limitations.

    Args:
        plan_report (ExtractionPlan): Source region and explicit inputs.
    Returns:
        str: Indented draft documentation grounded in the selected region.
    Warnings:
        This is draft contract documentation, not a semantic explanation.
    """
    lines_list = [
        '    """Draft extraction of the selected source expressions.',
        "", "    Args:",
    ]
    if not plan_report.inputs:
        lines_list.append("        None: No external names read.")
    for binding_info in plan_report.inputs:
        lines_list.append(f"        {binding_info.name}: Type not verified.")
    lines_list.extend([
        "    Returns:",
        "        Assigned values in the order listed by the extraction plan.",
        "    Warnings:",
        "        Review required; runtime behavior is not verified.",
        '    """',
    ])
    return "\n".join(lines_list) + "\n"


def return_statement_str(plan_report: ExtractionPlan) -> str:
    """Return every assigned name so the draft caller restores bindings.

    Args:
        plan_report (ExtractionPlan): First-write-ordered output names.
    Returns:
        str: Single-value or tuple return statement.
    Warnings:
        Preserving assigned names does not preserve exceptional execution.
    """
    if not plan_report.outputs:
        return "    return None\n"
    if len(plan_report.outputs) == 1:
        return f"    return {plan_report.outputs[0].name}\n"
    names_str = "".join(
        f"        {binding_info.name},\n"
        for binding_info in plan_report.outputs
    )
    return f"    return (\n{names_str}    )\n"


def render_caller_preview_str(plan_report: ExtractionPlan) -> str:
    """Render a draft caller restoring every region-assigned module name.

    Args:
        plan_report (ExtractionPlan): Ordered contract facts.
    Returns:
        str: Multiline assignment and call, suitable for review only.
    Warnings:
        Function placement, exceptions, reflection, and lifetime need review.
    """
    names_list = [binding_info.name for binding_info in plan_report.outputs]
    target_str = "" if not names_list else names_list[0] if len(
        names_list,
    ) == 1 else (
        "(\n" + "".join(
            f"    {name_str},\n" for name_str in names_list
        ) + ")"
    )
    inputs_str = "".join(
        f"    {binding_info.name},\n" for binding_info in plan_report.inputs
    )
    call_str = (
        f"{plan_report.function_name}(\n{inputs_str})" if inputs_str
        else f"{plan_report.function_name}()"
    )
    if not target_str:
        return f"{call_str}\n"
    return f"{target_str} = {call_str}\n"


def build_preview_none(
    plan_report: ExtractionPlan, profile_info: RuleProfile,
    statements_list: list[ast.stmt],
) -> None:
    """Compile candidate review text and enforce preview hard size limits.

    Args:
        plan_report (ExtractionPlan): Previously checked supported region.
        profile_info (RuleProfile): Maximum function and source-line lengths.
        statements_list (list[ast.stmt]): Original statements for comparison.
    Returns:
        None: Adds previews only after compilation and size checks pass.
    Warnings:
        Compilation is not execution or proof of behavioral equivalence.
    """
    body_str = "".join("    " + line_str for line_str in
                       StringIO(plan_report.source_fragment, newline=""))
    if not body_str.endswith(("\n", "\r")):
        body_str += "\n"
    function_str = (
        render_draft_signature_str(plan_report)
        + draft_docstring_str(plan_report) + body_str
        + return_statement_str(plan_report))
    caller_str = render_caller_preview_str(plan_report)
    validate_preview_none(function_str, caller_str, statements_list)
    length_int = len(function_str.splitlines())
    widest_int = max(map(len, (function_str + caller_str).splitlines()))
    if length_int > profile_info.function_max_lines or (
        widest_int > profile_info.line_length
    ):
        append_issue_none(plan_report, "PLAN006", plan_report.start_line,
                          f"Draft has {length_int} function lines and a "
                          f"maximum width of {widest_int}; configured caps "
                          "would be exceeded.")
        return
    plan_report.function_preview = function_str
    plan_report.caller_preview = caller_str
    plan_report.preview_compiles = True
    plan_report.status = "candidate_for_review"


def validate_preview_none(
    function_str: str, caller_str: str, statements_list: list[ast.stmt],
) -> None:
    """Compile draft code and compare its moved statements structurally.

    Args:
        function_str (str): Draft function with documentation and return.
        caller_str (str): Draft call and binding restoration.
        statements_list (list[ast.stmt]): Original selected statements.
    Returns:
        None: Raises if draft syntax or statement structure changes.
    Warnings:
        Matching statement ASTs do not prove that relocation is equivalent.
    """
    preview_node = ast.parse(function_str)
    compile(preview_node, "<funcloom-preview>", "exec", dont_inherit=True)
    compile(caller_str, "<funcloom-caller>", "exec", dont_inherit=True)
    if len(preview_node.body) != 1 or not isinstance(
        preview_node.body[0], ast.FunctionDef,
    ):
        raise ValueError("Preview must contain exactly one function")
    relocated_list = preview_node.body[0].body[1:-1]
    original_list = [ast.dump(node) for node in statements_list]
    if [ast.dump(node) for node in relocated_list] != original_list:
        raise ValueError("Relocated statements changed structure")
