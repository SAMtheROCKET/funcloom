"""Objective milestone-one checks; no inference or source rewriting."""

from collections.abc import Iterable

from funcloom.config import RuleProfile
from funcloom.models import Diagnostic, FunctionInfo, ModuleInfo

CHECK_CODES_TUPLE = (
    "FMT001", "SIZE001", "SIZE002", "SIZE003", "SIZE004",
    "TYPE001", "TYPE002", "DOC001", "DOC002", "NAME001",
)
ERROR_RULE_CODES_SET = {"FMT001", "SIZE002", "SIZE003", "SIZE004"}


def check_module_list(
    source_str: str, module_info: ModuleInfo, profile: RuleProfile,
) -> list[Diagnostic]:
    """Check physical limits and declared function documentation.

    Args:
        source_str (str): Original decoded source.
        module_info (ModuleInfo): Parsed declarations.
        profile (RuleProfile): Explicit thresholds.
    Returns:
        list[Diagnostic]: Observations; no edits are produced.
    Warnings:
        Type correctness and meaningfulness of names are not inferred.
    """
    diagnostics_list: list[Diagnostic] = []
    for line_int, line_str in enumerate(source_str.splitlines(), 1):
        if len(line_str) > profile.line_length:
            diagnostics_list.append(Diagnostic(
                "FMT001", "error", module_info.path, line_int,
                profile.line_length + 1,
                f"Line has {len(line_str)} characters; "
                f"limit is {profile.line_length}.",
            ))
    for function_info in module_info.functions:
        diagnostics_list.extend(check_function_list(
            function_info, module_info.path, profile,
        ))
    for guard_dict in module_info.main_guards:
        if guard_dict["physical_lines"] > profile.main_guard_max_lines:
            diagnostics_list.append(Diagnostic(
                "SIZE004", "error", module_info.path,
                guard_dict["line"], 1,
                f"Main guard spans {guard_dict['physical_lines']} lines; "
                f"limit is {profile.main_guard_max_lines}.",
            ))
    return diagnostics_list


def check_function_list(
    function_info: FunctionInfo, path_str: str, profile: RuleProfile,
) -> list[Diagnostic]:
    """Check a function using its own signature, scope, and docstring.

    Args:
        function_info (FunctionInfo): Function facts.
        path_str (str): Relative source path.
        profile (RuleProfile): Check settings.
    Returns:
        list[Diagnostic]: Findings for this function.
    Warnings:
        An orchestration exception applies only to a top-level name.
    """
    diagnostics_list: list[Diagnostic] = []
    for code_str, message_str in yield_function_messages_iterable(
        function_info, profile,
    ):
        diagnostics_list.append(Diagnostic(
            code_str, "error" if code_str in ERROR_RULE_CODES_SET
            else "warning", path_str, function_info.line, 1,
            f"{function_info.qualified_name}: {message_str}",
        ))
    for parameter_info in function_info.parameters:
        if function_info.is_method and parameter_info.name in {
            "self", "cls",
        }:
            continue
        if parameter_info.annotation is None:
            diagnostics_list.append(Diagnostic(
                "TYPE001", "warning", path_str, parameter_info.line, 1,
                f"{function_info.qualified_name}: parameter "
                f"'{parameter_info.name}' has no annotation.",
            ))
        if len(parameter_info.name) == 1:
            diagnostics_list.append(Diagnostic(
                "NAME001", "warning", path_str, parameter_info.line, 1,
                f"{function_info.qualified_name}: single-character "
                f"parameter '{parameter_info.name}' needs review.",
            ))
    return diagnostics_list


def yield_function_messages_iterable(
    function_info: FunctionInfo, profile: RuleProfile,
) -> Iterable[tuple[str, str]]:
    """Yield function-level findings without inspecting nested bodies.

    Args:
        function_info (FunctionInfo): Function declarations.
        profile (RuleProfile): Limits and expected docstring sections.
    Returns:
        Iterable: Rule identifier and explanatory message pairs.
    Warnings:
        Docstring checking covers presence, not factual accuracy.
    """
    is_main_bool = (
        function_info.qualified_name == function_info.name
        and function_info.name in profile.main_function_names
    )
    limit_int = profile.orchestrator_max_lines if is_main_bool else (
        profile.function_max_lines
    )
    if function_info.physical_lines > limit_int:
        yield (
            "SIZE003" if is_main_bool else "SIZE002",
            f"spans {function_info.physical_lines} physical lines; "
            f"limit is {limit_int}.",
        )
    elif not is_main_bool and (
        function_info.physical_lines > profile.function_target_lines
    ):
        yield "SIZE001", "exceeds the preferred function-size target."
    if function_info.return_annotation is None:
        yield "TYPE002", "return annotation is missing."
    if not function_info.docstring:
        yield "DOC001", "docstring is missing."
        return
    sections_set = {
        line_str.strip() for line_str in function_info.docstring.splitlines()
    }
    for section_str in profile.doc_sections:
        if section_str == "Returns" and "Yields:" in sections_set:
            continue
        if f"{section_str}:" not in sections_set:
            yield "DOC002", f"docstring section '{section_str}' is missing."
