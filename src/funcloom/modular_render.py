"""Render configuration, definition and step modules as source text."""

import ast

from funcloom.modular_models import PackageDraft, StepPlan, TopStatement
from funcloom.modular_text import (
    indent_lines_list, render_statement_text_tuple
)
from funcloom.modular_text import wrap_long_statements_tuple
from funcloom.snippet_render import escape_doc_lines_list
from funcloom.type_hints import write_return_annotation_str

FILE_ALIAS_STR = "_funcloom_path"


def collect_reads_set(statements_list: list[TopStatement]) -> set[str]:
    """Collect every name a group of statements may read.

    Args:
        statements_list (list[TopStatement]): Statements in one module.
    Returns:
        set[str]: Direct and deferred reads.
    Warnings:
        Names are original spellings, before constant renames.
    """
    return set().union(*(
        top_info.names.direct_reads | top_info.names.nested_reads
        for top_info in statements_list))


def plan_modules_none(draft_info: PackageDraft) -> None:
    """Split moved definitions into functions and models modules.

    Args:
        draft_info (PackageDraft): Draft receiving the module layout.
    Returns:
        None: Sets draft_info.modules.
    Warnings:
        Mutual references would import in a cycle, so both kinds then go
        to one components module.
    """
    definitions_list = [top_info for top_info in draft_info.statements
                        if top_info.kind == "definition"]
    classes_list = [definition_info for definition_info in definitions_list
                    if isinstance(definition_info.node, ast.ClassDef)]
    functions_list = [definition_info for definition_info in definitions_list
                      if definition_info not in classes_list]
    class_names_set = {class_info.node.name for class_info in classes_list}
    function_names_set = {
        function_info.node.name for function_info in functions_list}
    if collect_reads_set(functions_list) & class_names_set and (
        collect_reads_set(classes_list) & function_names_set
    ):
        draft_info.modules = {"components": definitions_list}
        return
    draft_info.modules = {stem_str: items_list for stem_str, items_list in
                          (("functions", functions_list),
                           ("models", classes_list)) if items_list}


def render_from_import_list(
    module_str: str, names_list: list[str], width_int: int,
) -> list[str]:
    """Write a relative import, wrapping it when it is too long.

    Args:
        module_str (str): Sibling module name.
        names_list (list[str]): Names to import.
        width_int (int): Maximum line length.
    Returns:
        list[str]: One line, or a parenthesized block.
    Warnings:
        Names are imported exactly as spelled.
    """
    line_str = f"from .{module_str} import {', '.join(names_list)}"
    if len(line_str) <= width_int:
        return [line_str]
    return ([f"from .{module_str} import ("]
            + [f"    {name_str}," for name_str in names_list] + [")"])


def import_lines_list(
    draft_info: PackageDraft, needed_set: set[str], own_str: str,
) -> list[str]:
    """Build the imports a generated module needs.

    Args:
        draft_info (PackageDraft): Classified program.
        needed_set (set[str]): Names the module's code reads.
        own_str (str): This module's name, to avoid self-imports.
    Returns:
        list[str]: Future imports, saved bindings, then package imports.
    Warnings:
        Original imports run once in _imports.py, including unused imports.
    """
    lines_list: list[str] = []
    for top_info in draft_info.statements:
        if top_info.kind == "future":
            text_str, _ = render_statement_text_tuple(
                top_info, draft_info.lines, {}, False)
            lines_list.extend(text_str.splitlines())
    imported_set = set().union(*(top_info.names.writes
                                for top_info in draft_info.statements
                                if top_info.kind == "import")) & needed_set
    if imported_set:
        lines_list += render_from_import_list("_imports", sorted(imported_set),
                                              draft_info.width)
    constants_list = [draft_info.constants[name_str] for name_str in
                      draft_info.constants if name_str in needed_set]
    if constants_list and own_str != "config":
        lines_list += render_from_import_list("config", constants_list,
                                              draft_info.width)
    for stem_str, items_list in draft_info.modules.items():
        names_list = [
            definition_info.node.name for definition_info in items_list
            if definition_info.node.name in needed_set]
        if names_list and stem_str != own_str:
            lines_list += render_from_import_list(stem_str, names_list,
                                                  draft_info.width)
    return lines_list + render_notebook_display_list(draft_info, needed_set)


def detect_notebook_display_bool(draft_info: PackageDraft) -> bool:
    """Tell whether a notebook relies on Jupyter's built-in display().

    Args:
        draft_info (PackageDraft): Classified program.
    Returns:
        bool: True for notebook input that reads display without ever
            binding or importing it.
    Warnings:
        Outside Jupyter the name does not exist.
    """
    return draft_info.source.name.lower().endswith(".ipynb") and any(
        "display" in top_info.names.direct_reads | top_info.names.nested_reads
        for top_info in draft_info.statements) and not any(
        "display" in top_info.names.writes
        for top_info in draft_info.statements)


def render_notebook_display_list(
    draft_info: PackageDraft, needed_set: set[str],
) -> list[str]:
    """Define display() for a module whose notebook code uses it.

    Args:
        draft_info (PackageDraft): Classified program.
        needed_set (set[str]): Names the module reads.
    Returns:
        list[str]: Import of IPython's display, falling back to print.
    Warnings:
        Without IPython, values are printed as text instead of rendered.
    """
    if "display" not in needed_set or not detect_notebook_display_bool(
        draft_info,
    ):
        return []
    return ["try:", "    from IPython.display import display",
            "except ImportError:  # Outside Jupyter: show values as text.",
            "    display = print"]


def render_imports_text_str(draft_info: PackageDraft) -> str:
    """Keep the initial imports together in their original order.

    Args:
        draft_info (PackageDraft): Classified original program.
    Returns:
        str: Module containing every leading import, including duplicates.
    Warnings:
        Import execution is retained even when no bound name is read.
        Later imports remain inside their original step.
    """
    return "".join(
        render_statement_text_tuple(top_info, draft_info.lines, {}, False)[0]
        for top_info in draft_info.statements
        if top_info.kind in ("future", "import"))


def render_file_override_list(
        draft_info: PackageDraft, needed_set: set) -> list:
    """Point __file__ at the script shim for code that reads it.

    Args:
        draft_info (PackageDraft): Draft with the shim's file name.
        needed_set (set): Names the module reads.
    Returns:
        list: Lines to place after the imports, or nothing.
    Warnings:
        The shim sits where the original script was, so paths built from
        __file__ resolve as before.
    """
    if "__file__" not in needed_set:
        return []
    return [f"import os.path as {FILE_ALIAS_STR}", "",
            "# FuncLoom: code below expects __file__ to be the script's own "
            "path.",
            f"__file__ = {FILE_ALIAS_STR}.join({FILE_ALIAS_STR}.dirname(",
            f"    {FILE_ALIAS_STR}.dirname({FILE_ALIAS_STR}.abspath("
            f'__file__))), "{draft_info.script_name}")']


def assemble_module_text_str(
    docstring_str: str, imports_list: list[str], blocks_list: list[str],
) -> str:
    """Assemble a module: docstring, imports, then top-level blocks.

    Args:
        docstring_str (str): One-line module docstring text.
        imports_list (list[str]): Import lines.
        blocks_list (list[str]): Definitions or statements, each complete.
    Returns:
        str: Module text ending in a newline.
    Warnings:
        Blocks are separated by two blank lines.
    """
    parts_list = [f'"""{docstring_str}"""\n']
    if imports_list:
        parts_list.append("\n" + "\n".join(imports_list) + "\n")
    if blocks_list:
        parts_list.append("\n\n" + "\n\n".join(
            block_str.rstrip("\n") + "\n" for block_str in blocks_list))
    return "".join(parts_list)


def render_config_text_str(draft_info: PackageDraft) -> str:
    """Render config.py with the moved constants.

    Args:
        draft_info (PackageDraft): Classified program.
    Returns:
        str: Module text.
    Warnings:
        Values are copied unchanged; only names may become upper case.
        Names read by annotations, such as Literal, are imported.
    """
    items_list = [top_info for top_info in draft_info.statements
                  if top_info.kind == "constant"]
    blocks_list = [render_statement_text_tuple(constant_info, draft_info.lines,
                                               draft_info.constants, False)[0]
                   for constant_info in items_list]
    imports_list = import_lines_list(draft_info, collect_reads_set(items_list),
                                     "config")
    imports_str = "\n".join(imports_list) + "\n\n" if imports_list else ""
    return (
        f'"""Constants from {shorten_source_label_str(draft_info)}; '
        'values are unchanged."""\n\n' + imports_str + "".join(blocks_list))


def render_definitions_text_str(
        draft_info: PackageDraft, stem_str: str) -> str:
    """Render a functions, models or components module.

    Args:
        draft_info (PackageDraft): Classified program and module layout.
        stem_str (str): Module to render.
    Returns:
        str: Module text.
    Warnings:
        Definitions keep their original order and text.
    """
    items_list = draft_info.modules[stem_str]
    blocks_list = []
    for definition_info in items_list:
        text_str = render_statement_text_tuple(
            definition_info, draft_info.lines, draft_info.constants, False)[0]
        text_str, notes_list = wrap_long_statements_tuple(
            text_str, 0, draft_info.width,
            f"{stem_str}.py, '{definition_info.node.name}'")
        draft_info.notes += notes_list
        blocks_list.append(text_str)
    kind_str = {"functions": "Functions", "models": "Classes"}.get(
        stem_str, "Functions and classes")
    needed_set = collect_reads_set(items_list)
    return assemble_module_text_str(
        f"{kind_str} moved from {shorten_source_label_str(draft_info)}.",
        import_lines_list(draft_info, needed_set, stem_str)
        + render_file_override_list(draft_info, needed_set), blocks_list,
    )


def shorten_source_label_str(draft_info: PackageDraft) -> str:
    """Return a short name for the original program.

    Args:
        draft_info (PackageDraft): Draft with source information.
    Returns:
        str: File name, or <snippet>.
    Warnings:
        Paths are shortened to the file name for readable docstrings.
    """
    return draft_info.source.name.replace("\\", "/").rsplit("/", 1)[-1]


def render_steps_text_str(draft_info: PackageDraft) -> str:
    """Render steps.py with one function per step.

    Args:
        draft_info (PackageDraft): Program with settled, named steps.
    Returns:
        str: Module text.
    Warnings:
        Step bodies are the original statements, re-indented.
    """
    executable_list = [top_info for step_info in draft_info.steps
                       for top_info in step_info.statements]
    blocks_list = [step_function_str(draft_info, step_info)
                   for step_info in draft_info.steps]
    needed_set = collect_reads_set(executable_list)
    return assemble_module_text_str(
        f"Steps from {shorten_source_label_str(draft_info)}, in their "
        "original order.",
        import_lines_list(draft_info, needed_set, "steps")
        + render_file_override_list(draft_info, needed_set), blocks_list,
    )


def render_step_signature_str(step_info: StepPlan, width_int: int) -> str:
    """Write a step's def line, one parameter per line when long.

    Args:
        step_info (StepPlan): Step with inputs.
        width_int (int): Maximum line length.
    Returns:
        str: Signature lines ending in a newline.
    Warnings:
        Only types certain from the source are annotated.
    """
    result_str = write_return_annotation_str(
        step_info.outputs, step_info.types)
    parameters_list = [
        f"{input_str}: {step_info.types[input_str]}"
        if step_info.types.get(input_str) else input_str
        for input_str in step_info.inputs]
    line_str = (f"def {step_info.name}({', '.join(parameters_list)})"
                f"{result_str}:")
    if len(line_str) <= width_int:
        return line_str + "\n"
    return (
        f"def {step_info.name}(\n"
        + "".join(
            f"    {parameter_str},\n" for parameter_str in parameters_list)
        + f"){result_str}:\n")


def return_str(step_info: StepPlan, width_int: int) -> str:
    """Write the return statement for a step's outputs.

    Args:
        step_info (StepPlan): Step with outputs.
        width_int (int): Maximum line length.
    Returns:
        str: Indented return line(s).
    Warnings:
        Returns None when later steps need nothing. A single output is
        returned as itself; "(x,)" would make it a one-item tuple.
    """
    if not step_info.outputs:
        return "    return None\n"
    line_str = f"    return {', '.join(step_info.outputs)}"
    if len(line_str) <= width_int or len(step_info.outputs) == 1:
        return line_str + "\n"
    return (
        "    return (\n"
        + "".join(
            f"        {output_str},\n" for output_str in step_info.outputs)
        + "    )\n")


def step_docstring_str(
    draft_info: PackageDraft, step_info: StepPlan,
) -> str:
    """Write a step docstring with Args, Returns and Warnings sections.

    Args:
        draft_info (PackageDraft): Draft for source names and width.
        step_info (StepPlan): Named step.
    Returns:
        str: Indented docstring ending in a newline.
    Warnings:
        Titles come from comments or headings; they are not verified.
    """
    width_int = draft_info.width
    first_int = step_info.statements[0].first_line
    last_int = step_info.statements[-1].last_line
    summary_str = (step_info.title[:1].upper() + step_info.title[1:]
                   ).rstrip(".") + "." if step_info.title else (
        f"Run lines {first_int}-{last_int} of the original program.")
    place_str = f"{step_info.origin}, " if step_info.origin else ""
    lines_list = escape_doc_lines_list(summary_str, width_int - 7)
    lines_list = ['    """' + lines_list[0]] + [
        "    " + line_str for line_str in lines_list[1:]]
    lines_list.append("")
    lines_list += [
        "    " + doc_line_str
        for doc_line_str
        in escape_doc_lines_list(
            f"Source: {place_str}lines {first_int}-{last_int} of "
            f"{shorten_source_label_str(draft_info)}.", width_int - 4)]
    lines_list += write_section_lines_list("Args", [
        f"{input_str}: Value from an earlier step; type not verified."
        for input_str in step_info.inputs
    ] or ["None: This step reads no value from earlier steps."], width_int)
    lines_list += write_section_lines_list("Returns", [
        f"{', '.join(step_info.outputs)}: Values later steps use, in "
        "this order." if step_info.outputs else
        "None: Later steps use no value from this step."], width_int)
    lines_list += write_section_lines_list(
        "Warnings",
        ["Generated by FuncLoom from the original statements; review it."]
        + [
            f"Merged: {merge_reason_str}"
            for merge_reason_str in step_info.merge_reasons], width_int)
    return "\n".join(lines_list + ['    """']) + "\n"


def write_section_lines_list(
    heading_str: str, entries_list: list[str], width_int: int,
) -> list[str]:
    """Write one docstring section with wrapped, indented entries.

    Args:
        heading_str (str): Section name.
        entries_list (list[str]): Entry texts.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Docstring lines.
    Warnings:
        Continuation lines are indented under their entry.
    """
    lines_list = [f"    {heading_str}:"]
    for entry_str in entries_list:
        wrapped_list = escape_doc_lines_list(entry_str, width_int - 12)
        lines_list.append("        " + wrapped_list[0])
        lines_list += [
            "            " + wrapped_line_str
            for wrapped_line_str in wrapped_list[1:]]
    return lines_list


def step_function_str(draft_info: PackageDraft, step_info: StepPlan) -> str:
    """Render one step function from its original statements.

    Args:
        draft_info (PackageDraft): Program text, renames and width.
        step_info (StepPlan): Named, settled step.
    Returns:
        str: Function text.
    Warnings:
        Regenerated statements lose inner comments; a note records this.
    """
    body_list = []
    for top_info in step_info.statements:
        text_str, regenerated_bool = render_statement_text_tuple(
            top_info, draft_info.lines, draft_info.constants, True)
        if regenerated_bool:
            draft_info.notes.append(
                f"Line {top_info.node.lineno} was regenerated from its "
                "syntax tree; comments inside it were not kept.")
        text_str, notes_list = wrap_long_statements_tuple(
            text_str, 4, draft_info.width,
            f"Step {step_info.name}, line {top_info.node.lineno}")
        draft_info.notes += notes_list
        body_list += indent_lines_list(text_str, "    ")
    return (render_step_signature_str(step_info, draft_info.width)
            + step_docstring_str(draft_info, step_info)
            + "\n".join(body_list) + "\n"
            + return_str(step_info, draft_info.width))
