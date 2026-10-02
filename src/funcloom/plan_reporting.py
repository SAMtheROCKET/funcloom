"""Human and machine-readable rendering for extraction review plans."""

from dataclasses import asdict
import json

from funcloom.plan_models import ExtractionPlan


def render_plan_str(plan_report: ExtractionPlan, format_str: str) -> str:
    """Render contract facts, preview text, and explicit approval limits.

    Args:
        plan_report (ExtractionPlan): Candidate or refused proposal.
        format_str (str): Either text or json.
    Returns:
        str: A complete read-only review artifact.
    Warnings:
        The report includes source fragments; review contents before sharing.
    """
    if format_str == "json":
        return json.dumps(asdict(plan_report), indent=2) + "\n"
    inputs_str = ", ".join(
        input_info.name for input_info in plan_report.inputs) or "none"
    outputs_str = (
        ", ".join(output_info.name for output_info in plan_report.outputs)
        or "none")
    lines_list = [
        f"FuncLoom {plan_report.tool_version} | plan | {plan_report.status}",
        f"Source: {plan_report.source_path}",
        f"Region: {plan_report.start_line}-{plan_report.end_line} (module)",
        f"Function: {plan_report.function_name}",
        f"Inputs: {inputs_str}", f"Outputs: {outputs_str}",
        f"Source SHA-256: {plan_report.source_sha256}",
        "Review required; can_apply=false; behavior_verified=false.",
    ]
    lines_list.extend(
        f"{diagnostic_info.path}:{diagnostic_info.line}: "
        f"{diagnostic_info.code} {diagnostic_info.message}"
        for diagnostic_info in plan_report.diagnostics
    )
    lines_list.extend(render_effects_list(plan_report))
    lines_list.extend(render_bindings_list(plan_report))
    if plan_report.function_preview is not None:
        lines_list.extend(["", "Draft function:", plan_report.function_preview,
                           "Draft caller:", plan_report.caller_preview])
    lines_list.extend(["", "Validation still required:"])
    lines_list.extend(f"- {item_str}" for item_str in
                      plan_report.validation_required)
    return "\n".join(lines_list) + "\n"


def render_effects_list(plan_report: ExtractionPlan) -> list[str]:
    """Expose partial effect evidence and its limits in the text report.

    Args:
        plan_report (ExtractionPlan): Candidate or refused proposal.
    Returns:
        list[str]: Located effect observations and coverage limitations.
    Warnings:
        An empty inventory does not establish absence of runtime effects.
    """
    lines_list = ["", f"Effect analysis: {plan_report.effect_analysis}"]
    lines_list.extend(
        f"- {effect_info.region}:{effect_info.line} "
        f"{effect_info.kind}: {effect_info.detail}"
        for effect_info in plan_report.effects
    )
    lines_list.extend(
        f"- Limit: {effect_limitation_str}"
        for effect_limitation_str in plan_report.effect_limitations)
    return lines_list


def render_bindings_list(plan_report: ExtractionPlan) -> list[str]:
    """Expose lexical resolutions of selected reads in the text report.

    Args:
        plan_report (ExtractionPlan): Candidate or refused proposal.
    Returns:
        list[str]: One line per resolved name, then coverage limitations.
    Warnings:
        A direct status is lexical evidence, not runtime identity or type.
    """
    lines_list = ["", f"Binding analysis: {plan_report.binding_analysis}"]
    for resolution_info in plan_report.name_resolutions:
        sites_str = ", ".join(
            f"{site.kind}@{site.line}" for site in resolution_info.sites
        ) or "no sites"
        lines_list.append(
            f"- {resolution_info.name} (line {resolution_info.line}): "
            f"{resolution_info.status}; {sites_str}"
        )
    lines_list.extend(
        f"- Limit: {binding_limitation_str}"
        for binding_limitation_str in plan_report.binding_limitations)
    return lines_list
