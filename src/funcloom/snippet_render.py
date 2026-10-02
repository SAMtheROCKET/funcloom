"""Format contextual documentation and quoted annotation proposals."""

import textwrap

from funcloom.snippet_models import SnippetReport, SnippetValue

WARNINGS_TUPLE = (
    "Review required; proposed types are not runtime validation.",
    "No extra rounding, conversions or input checks are added.",
)


def render_proposed_signature_str(report_info: SnippetReport) -> str:
    """Render proposed annotations without executing annotation expressions.

    Args:
        report_info (SnippetReport): Typed contract and function name.
    Returns:
        str: Function signature with optional quoted annotations.
    Warnings:
        Unknown types remain unannotated; annotations do not convert inputs.
    """
    inputs_list = [
        value_info for value_info in report_info.values
        if value_info.role == "input"]
    outputs_list = [
        value_info for value_info in report_info.values
        if value_info.role == "output"]
    arguments_str = "".join(
        f"    {input_info.proposed_name}"
        + (f": {input_info.annotation!r}" if input_info.annotation else "")
        + ",\n" for input_info in inputs_list)
    result_str = "" if outputs_list else " -> 'None'"
    if outputs_list and all(output_info.annotation is not None
                            for output_info in outputs_list):
        annotation_str = outputs_list[0].annotation
        if len(outputs_list) > 1:
            annotation_str = "tuple[" + ", ".join(
                output_info.annotation for output_info in outputs_list
            ) + "]"
        result_str = f" -> {annotation_str!r}"
    name_str = report_info.plan.function_name
    if not inputs_list:
        return f"def {name_str}(){result_str}:\n"
    return f"def {name_str}(\n{arguments_str}){result_str}:\n"


def escape_doc_lines_list(text_str: str, width_int: int) -> list[str]:
    """Wrap and escape user text before embedding a triple-quoted docstring.

    Args:
        text_str (str): User text or generated explanation.
        width_int (int): Available width excluding indentation.
    Returns:
        list[str]: Wrapped literal text that cannot close the docstring.
    Warnings:
        User prose stays documentation; it is never parsed as instructions.
    """
    escaped_str = " ".join(text_str.split())
    escaped_str = escaped_str.replace("\\", "\\\\").replace('"', '\\"')
    return textwrap.wrap(
        escaped_str, width=width_int, break_long_words=False,
        break_on_hyphens=False,
    ) or [""]


def describe_value_str(
    value_info: SnippetValue, report_info: SnippetReport,
) -> str:
    """Describe one source-linked value using explicit context if supplied.

    Args:
        value_info (SnippetValue): Input or output proposal.
        report_info (SnippetReport): User-authored descriptions.
    Returns:
        str: A source-derived or user-provided explanation.
    Warnings:
        No physical unit or domain meaning is inferred from a suffix.
    """
    description_str = report_info.context.descriptions.get(
        value_info.original_name,
        f"{'Input' if value_info.role == 'input' else 'Result'} corresponding "
        f"to source name {value_info.original_name}.",
    )
    type_str = value_info.annotation or "type unresolved"
    return f"{value_info.proposed_name} ({type_str}): {description_str}"


def render_value_sections_list(
    report_info: SnippetReport, width_int: int,
) -> list[str]:
    """Render contract documentation with indented continuation lines.

    Args:
        report_info (SnippetReport): Proposed values and descriptions.
        width_int (int): Configured total source width.
    Returns:
        list[str]: Argument and return documentation.
    Warnings:
        Descriptions are proposals; factual accuracy still requires review.
    """
    lines_list = []
    for heading_str, role_str in (("Args", "input"), ("Returns", "output")):
        lines_list.append(f"    {heading_str}:")
        values_list = [
            value_info for value_info in report_info.values
            if value_info.role == role_str]
        descriptions_list = [describe_value_str(value_info, report_info)
                             for value_info in values_list] or ["None."]
        for text_str in descriptions_list:
            wrapped_list = escape_doc_lines_list(text_str, width_int - 12)
            lines_list.append("        " + wrapped_list[0])
            lines_list.extend("            " + line_str
                              for line_str in wrapped_list[1:])
    return lines_list


def render_proposed_docstring_str(
    report_info: SnippetReport, width_int: int,
) -> str:
    """Render summary, explanation, arguments, returns and honest warnings.

    Args:
        report_info (SnippetReport): Context and source-derived value facts.
        width_int (int): Configured total source-line width.
    Returns:
        str: Indented documentation with safe literal quoting.
    Warnings:
        Project prose is explicitly labeled as user context.
    """
    outputs_list = [
        value_info for value_info in report_info.values
        if value_info.role == "output"]
    summary_str = report_info.context.summary or (
        "Evaluate the supplied mathematical expressions in source order."
        if report_info.context.naming_mode == "mathematical" else
        "Run the selected statements with the supplied inputs."
        if not outputs_list else
        "Calculate " + ", ".join(output_info.original_name.replace("_", " ")
                                for output_info in outputs_list)
        + " from the supplied inputs."
    )
    summary_list = escape_doc_lines_list(summary_str, width_int - 7)
    lines_list = ['    """' + summary_list[0]]
    lines_list.extend("    " + line_str for line_str in summary_list[1:])
    lines_list.extend(["", "    Use the selected source expressions."])
    if report_info.context.project_context:
        context_str = "User context: " + report_info.context.project_context
        lines_list.extend("    " + line_str for line_str in
                          escape_doc_lines_list(context_str, width_int - 4))
    lines_list.extend(render_value_sections_list(report_info, width_int))
    lines_list.append("    Warnings:")
    for warning_str in WARNINGS_TUPLE:
        lines_list.extend("        " + line_str for line_str in
                          escape_doc_lines_list(warning_str, width_int - 8))
    lines_list.append('    """')
    return "\n".join(lines_list) + "\n"
