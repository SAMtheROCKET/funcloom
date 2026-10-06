"""Turn a script, snippet or notebook into a modular Python package."""

import ast
from hashlib import sha256
import keyword
from pathlib import Path
import re
import sys

from funcloom.config import RuleProfile, validate_profile_none
from funcloom.modular_classify import (
    classify_statements_none, choose_constant_names_dict,
    refuse_unsupported_none,
)
from funcloom.modular_models import (
    GeneratedFile, ModularReport, PackageDraft, ProgramSource,
    add_diagnostic_none,
)
from funcloom.modular_pipeline import (
    init_text_str, render_main_text_str, render_package_main_text_str,
    render_pipeline_text_str,
)
from funcloom.modular_render import (
    render_config_text_str, render_definitions_text_str,
    render_imports_text_str,
    detect_notebook_display_bool, plan_modules_none, render_steps_text_str,
)
from funcloom.modular_scan import (
    split_program_lines_list, list_top_statements_list
)
from funcloom.modular_source import load_program_source
from funcloom.modular_steps import (
    build_initial_steps_list, settle_steps_list, step_name_str, step_record,
    enable_with_block_trust,
)
from funcloom.modular_verify import (
    detect_newline_style_str, verify_files_list, write_files_none,
)
from funcloom.refine import RefineOptions, RefineReport, apply_refinements_str
from funcloom.type_hints import (
    update_statement_types_none, list_trusted_names_set
)

REFINED_STEMS_TUPLE = ("functions.py", "models.py", "components.py",
                       "steps.py")

LIMITATIONS_TUPLE = (
    "Run main.py from the output folder; relative file paths still resolve "
    "against the working directory.",
    "Values flow between steps as parameters and return values; a step "
    "that raises leaves later values unset, as the original stops too.",
    "Definitions that depend on script state stay inside steps as nested "
    "definitions; they cannot be pickled by reference.",
    "Structure and name checks passed; runtime behavior is not verified.",
)


def choose_package_name_str(stem_str: str, requested_str: str | None) -> str:
    """Choose a valid package name that does not shadow the standard library.

    Args:
        stem_str (str): Input file stem.
        requested_str (str | None): Name supplied by the user.
    Returns:
        str: Lower-case identifier.
    Warnings:
        A requested name is validated, not silently changed.
    """
    if requested_str is not None:
        if not requested_str.isidentifier() or keyword.iskeyword(
            requested_str,
        ) or requested_str in sys.stdlib_module_names:
            raise ValueError(f"Invalid package name: {requested_str!r}")
        return requested_str
    name_str = re.sub(r"[^0-9a-zA-Z]+", "_", stem_str).strip("_").lower()
    if not name_str or name_str[0].isdigit():
        name_str = f"app_{name_str}".rstrip("_")
    if keyword.iskeyword(name_str) or name_str in sys.stdlib_module_names:
        name_str += "_app"
    return name_str


def modularize_report(
    source_path: str | Path | None = None, source_text: str | None = None,
    output_dir: str | Path | None = None, cells_list: list[int] | None = None,
    package_name: str | None = None, profile_info: RuleProfile | None = None,
    options_info: RefineOptions | None = None,
) -> ModularReport:
    """Plan, verify and optionally write a modular package for a program.

    Args:
        source_path (str | Path | None): .py file or .ipynb notebook.
        source_text (str | None): Python text instead of a file.
        output_dir (str | Path | None): New folder to write; None plans only.
        cells_list (list[int] | None): Notebook cells to include.
        package_name (str | None): Package name; derived when omitted.
        profile_info (RuleProfile | None): Line length and size limits.
        options_info (RefineOptions | None): Function splitting and
            documentation; splitting is on by default.
    Returns:
        ModularReport: Files, steps, notes and any refusals.
    Warnings:
        The original file is never changed and no program code is run.
    """
    profile_info = profile_info or RuleProfile()
    validate_profile_none(profile_info)
    if source_path is not None and Path(source_path).is_dir():
        raise ValueError("Use modularize_project_report for folders")
    source_info = load_program_source_info(
        source_path, source_text, cells_list, profile_info.max_file_bytes)
    report_info, files_dict = plan_program_tuple(
        source_info, choose_package_name_str(source_info.stem, package_name),
        profile_info, options_info or RefineOptions())
    if source_path is not None and Path(source_path).suffix == ".py":
        warn_sibling_imports_none(Path(source_path), report_info)
    if files_dict is not None and output_dir is not None:
        write_report_none(files_dict, Path(output_dir), report_info,
                          detect_newline_style_str(source_info.text))
    return report_info


def plan_program_tuple(
    source_info: ProgramSource, package_str: str, profile_info: RuleProfile,
    options_info: RefineOptions, script_str: str = "main.py",
) -> tuple[ModularReport, dict[str, str] | None]:
    """Plan and verify a package, refusing programs nested too deeply.

    Args:
        source_info (ProgramSource): Loaded program.
        package_str (str): Package name for the generated code.
        profile_info (RuleProfile): Line length and limits.
        options_info (RefineOptions): Splitting and documentation.
        script_str (str): File name of the script that runs the package.
    Returns:
        tuple: Report, and generated files when planning succeeded.
    Warnings:
        A program whose syntax tree exceeds Python's recursion limit
        during analysis is refused with READ001 instead of failing.
    """
    try:
        return plan_checked_program_tuple(source_info, package_str,
                                          profile_info, options_info,
                                          script_str)
    except RecursionError:
        report_info = ModularReport(source_info.name, package_str)
        add_diagnostic_none(report_info, "READ001", 1, (
            "The program is nested too deeply to analyse within Python's "
            "recursion limit; nothing was generated."))
        return report_info, None


def plan_checked_program_tuple(
    source_info: ProgramSource, package_str: str, profile_info: RuleProfile,
    options_info: RefineOptions, script_str: str = "main.py",
) -> tuple[ModularReport, dict[str, str] | None]:
    """Plan and verify the package for one program without writing it.

    Args:
        source_info (ProgramSource): Loaded program.
        package_str (str): Package name for the generated code.
        profile_info (RuleProfile): Line length and limits.
        options_info (RefineOptions): Splitting and documentation.
        script_str (str): File name of the script that runs the package.
    Returns:
        tuple: Report, and generated files when planning succeeded.
    Warnings:
        Files are verified but not written.
    """
    report_info = ModularReport(source_info.name, package_str)
    report_info.source_sha256 = source_info.document_sha256 or sha256(
        source_info.text.encode("utf-8")).hexdigest()
    report_info.notes = list(source_info.notes)
    with enable_with_block_trust(options_info.trust_with_blocks):
        draft_info = draft_package_info(source_info, report_info,
                                        profile_info.line_length)
    if draft_info is not None:
        draft_info.script_name = script_str
        note_file_use_none(draft_info, report_info)
        note_with_trust_none(draft_info, report_info, options_info)
        if detect_notebook_display_bool(draft_info):
            add_diagnostic_none(report_info, "MODW08", 1, (
                "The notebook uses Jupyter's display(); generated modules "
                "import it from IPython and fall back to print when "
                "IPython is not installed."), "warning")
    if draft_info is None or any(
            diagnostic_info.severity == "error"
            for diagnostic_info in report_info.diagnostics):
        return report_info, None
    files_dict = render_files_dict(draft_info, report_info)
    if files_dict is not None:
        refine_files_none(files_dict, report_info, profile_info,
                          options_info)
        report_info.status = "planned"
    return report_info, files_dict


def note_file_use_none(
    draft_info: PackageDraft, report_info: ModularReport,
) -> None:
    """Warn that __file__ now names the script next to the package.

    Args:
        draft_info (PackageDraft): Program and shim name.
        report_info (ModularReport): MODW06 destination.
    Returns:
        None: Adds a warning when the program reads __file__.
    Warnings:
        Files read relative to __file__ must sit next to that script;
        folder mode copies them there.
    """
    lines_list = [top_info.names.special_lines["__file__"]
                  for top_info in draft_info.statements
                  if "__file__" in top_info.names.special_lines]
    if lines_list:
        add_diagnostic_none(report_info, "MODW06", min(lines_list), (
            f"__file__ now names {draft_info.script_name} next to the "
            "generated package; keep files it reads beside that script "
            "(folder mode copies them)."), "warning")


def note_with_trust_none(
    draft_info: PackageDraft, report_info: ModularReport,
    options_info: RefineOptions,
) -> None:
    """Suggest --trust-with-blocks when with blocks forced step merges.

    Args:
        draft_info (PackageDraft): Program statements and settled steps.
        report_info (ModularReport): Notes destination.
        options_info (RefineOptions): Whether the option is already on.
    Returns:
        None: Adds one note when it may help.
    Warnings:
        A suggestion only; the option trusts that no context manager
        suppresses an exception halfway through its block.
    """
    with_bool = any(isinstance(top_info.node, (ast.With, ast.AsyncWith))
                    for top_info in draft_info.statements)
    merged_bool = any("may be unbound" in reason
                      for step_info in draft_info.steps
                      for reason in step_info.merge_reasons)
    if with_bool and merged_bool and not options_info.trust_with_blocks:
        report_info.notes.append(
            "Some steps were merged because values bound inside with "
            "blocks count as possibly unbound. --trust-with-blocks treats "
            "them as bound unless the context manager is a known "
            "suppressor such as contextlib.suppress.")


def refine_files_none(
    files_dict: dict[str, str], report_info: ModularReport,
    profile_info: RuleProfile, options_info: RefineOptions,
) -> None:
    """Split long functions and document generated modules in place.

    Args:
        files_dict (dict[str, str]): Verified generated files.
        report_info (ModularReport): Notes and file summaries.
        profile_info (RuleProfile): Limits.
        options_info (RefineOptions): Enabled refinements.
    Returns:
        None: Updates files and the report.
    Warnings:
        Each refinement verifies itself and is skipped if it fails.
    """
    refine_info = RefineReport(report_info.source_name)
    for path_str in list(files_dict):
        if path_str.startswith(f"{report_info.package_name}/") and (
            path_str.endswith(REFINED_STEMS_TUPLE)
        ):
            files_dict[path_str] = apply_refinements_str(
                files_dict[path_str], path_str, profile_info, options_info,
                refine_info)
    report_info.split_functions = refine_info.split_functions
    report_info.documented_functions = refine_info.documented_functions
    report_info.notes += refine_info.notes
    report_info.files = [GeneratedFile(
        path_str, sha256(text_str.encode("utf-8")).hexdigest(),
        len(text_str.splitlines()), text_str)
        for path_str, text_str in files_dict.items()]


def warn_sibling_imports_none(
    source_path: Path, report_info: ModularReport,
) -> None:
    """Warn when a script imports a module that sits next to it.

    Args:
        source_path (Path): Input script.
        report_info (ModularReport): Warning destination.
    Returns:
        None: Adds MODW04 warnings.
    Warnings:
        The generated package only finds those modules if they are copied
        next to main.py; folder mode does that automatically.
    """
    folder_path = source_path.absolute().parent
    try:
        module_node = ast.parse(source_path.read_bytes())
    except (SyntaxError, ValueError):
        return
    for node in ast.walk(module_node):
        names_list = ([alias_node.name for alias_node in node.names]
                      if isinstance(node, ast.Import) else [node.module]
                      if isinstance(node, ast.ImportFrom) and not node.level
                      and node.module else [])
        for name_str in names_list:
            first_str = name_str.split(".")[0]
            if (folder_path / f"{first_str}.py").is_file() or (
                folder_path / first_str / "__init__.py"
            ).is_file():
                add_diagnostic_none(report_info, "MODW04", node.lineno, (
                    f"'{first_str}' is a local module next to the script; "
                    "copy it next to main.py or modularize the whole folder."
                ), "warning")


def load_program_source_info(
    source_path: str | Path | None, source_text: str | None,
    cells_list: list[int] | None, max_bytes_int: int,
) -> ProgramSource:
    """Load the program from a file or from supplied text.

    Args:
        source_path (str | Path | None): .py or .ipynb file.
        source_text (str | None): Python text instead of a file.
        cells_list (list[int] | None): Notebook cells to include.
        max_bytes_int (int): Maximum input size.
    Returns:
        ProgramSource: Combined program text.
    Warnings:
        Exactly one of source_path and source_text must be given.
    """
    if (source_path is None) == (source_text is None):
        raise ValueError("Provide exactly one of source_path or source_text")
    if source_text is not None:
        if len(source_text.encode("utf-8")) > max_bytes_int:
            raise ValueError("Source exceeds the configured byte limit")
        return ProgramSource("<snippet>", source_text, "snippet")
    return load_program_source(source_path, cells_list, max_bytes_int)


def write_report_none(
    files_dict: dict[str, str], output_path: Path,
    report_info: ModularReport, newline_str: str = "\n",
) -> None:
    """Write the package and record the outcome in the report.

    Args:
        files_dict (dict[str, str]): Verified generated files.
        output_path (Path): New or empty folder.
        report_info (ModularReport): Status and diagnostics destination.
        newline_str (str): Line ending of the original source.
    Returns:
        None: Sets status to written, or refused with MOD006.
    Warnings:
        A folder with existing contents is never written into.
    """
    try:
        write_files_none(files_dict, output_path, newline_str)
    except (ValueError, OSError) as error:
        add_diagnostic_none(report_info, "MOD006", 1, str(error))
        report_info.status = "refused"
        return
    report_info.status = "written"
    report_info.output_dir = str(output_path.absolute())


def parse_program_node(
    source_info: ProgramSource, report_info: ModularReport,
) -> ast.Module | None:
    """Parse and compile the program without running it.

    Args:
        source_info (ProgramSource): Combined program text.
        report_info (ModularReport): MOD001 destination.
    Returns:
        ast.Module | None: Syntax tree, or None for invalid Python.
    Warnings:
        Notebook-only syntax such as top-level await is not Python here.
    """
    try:
        module_node = ast.parse(source_info.text)
        compile(module_node, report_info.source_name, "exec",
                dont_inherit=True)
    except SyntaxError as error:
        add_diagnostic_none(report_info, "MOD001", error.lineno or 1,
                            f"Not valid Python: {error.msg}.")
        return None
    return module_node


def draft_package_info(
    source_info: ProgramSource, report_info: ModularReport, width_int: int,
) -> PackageDraft | None:
    """Parse, classify and group the program into a package draft.

    Args:
        source_info (ProgramSource): Combined program text.
        report_info (ModularReport): Diagnostics and summary destination.
        width_int (int): Maximum line length.
    Returns:
        PackageDraft | None: Draft, or None when the text is not Python.
    Warnings:
        Refusals are recorded in the report; nothing is written.
    """
    module_node = parse_program_node(source_info, report_info)
    if module_node is None:
        return None
    statements_list = list_top_statements_list(module_node, source_info.text)
    classify_statements_none(statements_list, report_info)
    refuse_unsupported_none(statements_list, report_info)
    constants_dict = choose_constant_names_dict(statements_list, module_node)
    steps_list = settle_steps_list(
        build_initial_steps_list(
            [
                top_info for top_info in statements_list
                if top_info.kind == "executable"], source_info))
    name_steps_none(steps_list, module_node, statements_list, constants_dict)
    annotate_step_types_none(steps_list, statements_list)
    report_info.constants = constants_dict
    report_info.steps = [step_record(step_info) for step_info in steps_list]
    draft_info = PackageDraft(
        report_info.package_name, source_info,
        split_program_lines_list(source_info.text), statements_list,
        constants_dict, steps_list, width_int)
    plan_modules_none(draft_info)
    report_info.moved_definitions = {
        definition_info.node.name: f"{draft_info.package_name}/{stem_str}.py"
        for stem_str, items_list in draft_info.modules.items()
        for definition_info in items_list}
    return draft_info


def name_steps_none(
    steps_list: list, module_node: ast.Module, statements_list: list,
    constants_dict: dict[str, str],
) -> None:
    """Give every step a unique name that clashes with nothing else.

    Args:
        steps_list (list): Settled steps.
        module_node (ast.Module): Parsed program.
        statements_list (list): Program statements.
        constants_dict (dict[str, str]): Constant renames.
    Returns:
        None: Sets each step's name.
    Warnings:
        Generated names avoid every identifier used in the program.
    """
    taken_set = {
        node.id for node in ast.walk(module_node) if isinstance(node, ast.Name)
    } | set().union(*(
        top_info.names.writes for top_info in statements_list)) | {
        "Pipeline", "main"} | set(constants_dict.values())
    for index_int, step_info in enumerate(steps_list, 1):
        step_info.name = step_name_str(step_info, index_int, taken_set)


def annotate_step_types_none(steps_list: list, statements_list: list) -> None:
    """Record certain types for each step's parameters and results.

    Args:
        steps_list (list): Named, settled steps.
        statements_list (list): Classified program statements.
    Returns:
        None: Fills each step's types.
    Warnings:
        Types flow from constants and earlier steps; uncertain values
        stay unannotated.
    """
    bound_set = set().union(*(
        top_info.names.writes for top_info in statements_list))
    trusted_set = list_trusted_names_set(
        bound_set,
        [
            top_info.node for top_info in statements_list
            if top_info.kind == "definition"
            and isinstance(top_info.node, ast.ClassDef)])
    known_dict: dict[str, str | None] = {}
    for statement_info in statements_list:
        if statement_info.kind == "constant":
            update_statement_types_none(
                statement_info.node, known_dict, trusted_set,
                statement_info.names.writes)
    for step_info in steps_list:
        local_dict = dict(known_dict)
        for top_info in step_info.statements:
            update_statement_types_none(top_info.node, local_dict, trusted_set,
                                        top_info.names.writes)
        step_info.types = {name_str: known_dict.get(name_str)
                           for name_str in step_info.inputs}
        step_info.types.update({name_str: local_dict.get(name_str)
                                for name_str in step_info.outputs})
        known_dict.update({name_str: local_dict.get(name_str)
                           for name_str in step_info.outputs})


def render_files_dict(
    draft_info: PackageDraft, report_info: ModularReport,
) -> dict[str, str] | None:
    """Render every file, verify it, and record file summaries.

    Args:
        draft_info (PackageDraft): Settled draft.
        report_info (ModularReport): Files, checks and notes destination.
    Returns:
        dict | None: Relative path to text, or None when checks failed.
    Warnings:
        A failed check is reported as MOD007 and nothing is written.
    """
    package_str = draft_info.package_name
    files_dict = {"main.py": render_main_text_str(draft_info),
                  f"{package_str}/__init__.py": init_text_str(draft_info),
                  f"{package_str}/__main__.py": render_package_main_text_str()}
    if any(top_info.kind == "import" for top_info in draft_info.statements):
        files_dict[f"{package_str}/_imports.py"] = render_imports_text_str(
            draft_info)
    if draft_info.constants:
        files_dict[f"{package_str}/config.py"] = render_config_text_str(
            draft_info)
    for stem_str in draft_info.modules:
        files_dict[
            f"{package_str}/{stem_str}.py"] = render_definitions_text_str(
            draft_info, stem_str)
    files_dict[f"{package_str}/steps.py"] = render_steps_text_str(draft_info)
    files_dict[f"{package_str}/pipeline.py"] = render_pipeline_text_str(
        draft_info)
    report_info.notes += list(dict.fromkeys(draft_info.notes))
    report_info.notes += list(LIMITATIONS_TUPLE)
    problems_list = verify_files_list(draft_info, files_dict)
    report_info.checks = {"compiled": not problems_list,
                          "structure_and_names_verified": not problems_list,
                          "problems": problems_list}
    for problem_str in problems_list:
        add_diagnostic_none(report_info, "MOD007", 1, problem_str)
    report_info.files = [GeneratedFile(
        path_str, sha256(text_str.encode("utf-8")).hexdigest(),
        len(text_str.splitlines()), text_str)
        for path_str, text_str in files_dict.items()]
    return None if problems_list else files_dict
