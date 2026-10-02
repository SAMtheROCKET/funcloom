"""Render the Pipeline class, the entry points and the package marker."""

from funcloom.modular_models import PackageDraft, StepPlan
from funcloom.modular_render import (
    render_from_import_list, shorten_source_label_str
)
from funcloom.modular_text import render_statement_text_tuple
from funcloom.snippet_render import escape_doc_lines_list

STAGE_TARGET_LINES_INT = 30
RESERVED_ATTRIBUTES_TUPLE = ("run",)


def write_source_doc_lines_list(
    draft_info: PackageDraft, indent_str: str,
) -> list[str]:
    """Write a wrapped 'Source: <file>' docstring line.

    Args:
        draft_info (PackageDraft): Draft with the source name.
        indent_str (str): Docstring indentation.
    Returns:
        list[str]: One or more indented lines.
    Warnings:
        A single very long file name can still exceed the width.
    """
    return [indent_str + line_str for line_str in escape_doc_lines_list(
        f"Source: {shorten_source_label_str(draft_info)}.",
        draft_info.width - len(indent_str))]


def choose_attribute_names_dict(draft_info: PackageDraft) -> dict[str, str]:
    """Choose Pipeline attribute names for values passed between steps.

    Args:
        draft_info (PackageDraft): Program with settled steps.
    Returns:
        dict[str, str]: Variable name to attribute name.
    Warnings:
        Names that would hide a method get a _value suffix.
    """
    names_list = list(dict.fromkeys(
        name_str for step_info in draft_info.steps
        for name_str in step_info.outputs))
    attributes_dict: dict[str, str] = {}
    for name_str in names_list:
        attribute_str = name_str
        if name_str in RESERVED_ATTRIBUTES_TUPLE or name_str.startswith(
            ("__", "run_stage_"),
        ):
            attribute_str = f"{name_str.strip('_')}_value"
        while attribute_str in attributes_dict.values() or (
            attribute_str != name_str and attribute_str in names_list
        ):
            attribute_str += "_"
        attributes_dict[name_str] = attribute_str
    return attributes_dict


def call_lines_list(
    step_info: StepPlan, attributes_dict: dict[str, str], width_int: int,
) -> list[str]:
    """Write the statement that runs one step and stores its results.

    Args:
        step_info (StepPlan): Step to call.
        attributes_dict (dict[str, str]): Variable to attribute names.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Lines indented for a method body.
    Warnings:
        Arguments and results are positional, matching the signature. A
        single result is assigned directly, never unpacked.
    """
    arguments_list = [f"self.{attributes_dict[input_str]}"
                      for input_str in step_info.inputs]
    targets_list = [f"self.{attributes_dict[output_str]}"
                    for output_str in step_info.outputs]
    call_str = f"{step_info.name}({', '.join(arguments_list)})"
    line_str = (f"{', '.join(targets_list)} = {call_str}" if targets_list
                else call_str)
    if len(line_str) + 8 <= width_int:
        return ["        " + line_str]
    lines_list = []
    if len(targets_list) == 1:
        # "(x,) = step()" would unpack a one-item tuple instead.
        lines_list.append(f"        {targets_list[0]} = {step_info.name}(")
    elif targets_list:
        lines_list += ["        ("] + [f"            {target_str},"
                                       for target_str in targets_list]
        lines_list.append(f"        ) = {step_info.name}(")
    else:
        lines_list.append(f"        {step_info.name}(")
    lines_list += [
        f"            {argument_str}," for argument_str in arguments_list]
    return lines_list + ["        )"]


def write_method_str(
        name_str: str, summary_str: str, body_list: list[str]) -> str:
    """Write a documented method with no parameters besides self.

    Args:
        name_str (str): Method name.
        summary_str (str): One-line summary.
        body_list (list[str]): Indented body lines.
    Returns:
        str: Method text.
    Warnings:
        The docstring follows the project's Args/Returns/Warnings format.
    """
    return "\n".join([
        f"    def {name_str}(self) -> None:",
        f'        """{summary_str}',
        "",
        "        Args:",
        "            None: Values flow between steps through attributes.",
        "        Returns:",
        "            None: Results stay on this Pipeline instance.",
        "        Warnings:",
        "            Stops at the first exception, as the original did.",
        '        """',
        *body_list,
    ])


def stage_chunks_list(lines_groups_list: list[list[str]]) -> list[list[str]]:
    """Group step calls into stages of limited length.

    Args:
        lines_groups_list (list[list[str]]): Call lines per step.
    Returns:
        list[list[str]]: Body lines per stage.
    Warnings:
        A single very long call still forms its own stage.
    """
    chunks_list: list[list[str]] = [[]]
    for group_list in lines_groups_list:
        if chunks_list[-1] and (
            len(chunks_list[-1]) + len(group_list) > STAGE_TARGET_LINES_INT
        ):
            chunks_list.append([])
        chunks_list[-1].extend(group_list)
    return chunks_list


def write_pipeline_methods_list(draft_info: PackageDraft) -> list[str]:
    """Write run(), plus run_stage_N methods for long pipelines.

    Args:
        draft_info (PackageDraft): Program with settled, named steps.
    Returns:
        list[str]: Method texts in order.
    Warnings:
        Stages share values through attributes, so splitting is safe.
    """
    attributes_dict = choose_attribute_names_dict(draft_info)
    chunks_list = stage_chunks_list([
        call_lines_list(step_info, attributes_dict, draft_info.width)
        for step_info in draft_info.steps])
    if len(chunks_list) == 1:
        return [
            write_method_str(
                "run", "Run every step in the original order.", chunks_list[0])
        ]
    return [
        write_method_str(
            "run", "Run every stage in the original order.",
            [
                f"        self.run_stage_{index_int}()"
                for index_int in range(1, len(chunks_list) + 1)])] + [
        write_method_str(
            f"run_stage_{index_int}", f"Run stage {index_int} of the steps.",
            chunk_list) for index_int, chunk_list in enumerate(chunks_list, 1)]


def render_pipeline_text_str(draft_info: PackageDraft) -> str:
    """Render pipeline.py: a class that runs every step in order.

    Args:
        draft_info (PackageDraft): Program with settled, named steps.
    Returns:
        str: Module text.
    Warnings:
        Long pipelines are split into run_stage_N methods.
    """
    methods_list = write_pipeline_methods_list(draft_info)
    imports_list = render_from_import_list(
        "steps", [step_info.name for step_info in draft_info.steps],
        draft_info.width,
    ) if draft_info.steps else []
    class_str = "\n".join([
        "class Pipeline:",
        '    """Run the generated steps in their original order.',
        "",
        *write_source_doc_lines_list(draft_info, "    "),
        "    Values that later steps need are stored as attributes, so they",
        "    can be inspected after run() finishes.",
        '    """',
        "",
        "",
    ]) + "\n\n".join(methods_list) + "\n"
    header_str = '"""Run the generated steps in their original order."""\n'
    imports_str = ("\n" + "\n".join(imports_list) + "\n") if (
        imports_list) else ""
    return header_str + imports_str + "\n\n" + class_str


def render_main_text_str(draft_info: PackageDraft) -> str:
    """Render main.py, the script that runs the package.

    Args:
        draft_info (PackageDraft): Draft with the package name.
    Returns:
        str: Script text with a main() function and a __main__ guard.
    Warnings:
        Run it from the output folder so the package can be imported.
    """
    return "\n".join([
        '"""Run the pipeline that FuncLoom generated.',
        "",
        *write_source_doc_lines_list(draft_info, ""),
        '"""',
        "",
        f"from {draft_info.package_name}.pipeline import Pipeline",
        "", "",
        "def main() -> None:",
        '    """Run every generated step in the original order.',
        "",
        "    Args:",
        "        None: The pipeline takes no arguments.",
        "    Returns:",
        "        None: Results stay on the Pipeline instance.",
        "    Warnings:",
        "        Relative file paths resolve against the working directory.",
        '    """',
        "    Pipeline().run()",
        "", "",
        'if __name__ == "__main__":',
        "    main()",
        "",
    ])


def render_package_main_text_str() -> str:
    """Render __main__.py so `python -m <package>` runs the pipeline.

    Args:
        None: The text does not depend on the program.
    Returns:
        str: Module text.
    Warnings:
        Equivalent to running main.py.
    """
    return "\n".join([
        '"""Allow `python -m` on the package to run the pipeline."""',
        "",
        "from .pipeline import Pipeline",
        "",
        'if __name__ == "__main__":',
        "    Pipeline().run()",
        "",
    ])


def init_text_str(draft_info: PackageDraft) -> str:
    """Render __init__.py with the original module docstring if any.

    Args:
        draft_info (PackageDraft): Classified program.
    Returns:
        str: Package docstring and initialization of leading imports.
    Warnings:
        Importing the generated package runs the original leading imports.
        FuncLoom itself never imports or executes the target program.
    """
    text_str = (f'"""Package generated by FuncLoom from '
                f'{shorten_source_label_str(draft_info)}."""\n')
    for top_info in draft_info.statements:
        if top_info.kind == "docstring":
            text_str = render_statement_text_tuple(
                top_info, draft_info.lines, {}, False)[0]
            break
    if any(top_info.kind == "import" for top_info in draft_info.statements):
        text_str += "\nfrom . import _imports\n"
    return text_str
