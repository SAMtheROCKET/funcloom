"""Modularize every entry script of a folder and copy the rest unchanged."""

import ast
import os
from pathlib import Path
import re

from funcloom.config import RuleProfile, validate_profile_none
from funcloom.modular_models import ModularReport, ProjectReport
from funcloom.modular_scan import is_plain_main_guard_bool
from funcloom.modular_source import load_program_source
from funcloom.modular_verify import (
    detect_newline_style_str, write_project_none,
)
from funcloom.modularize import choose_package_name_str, plan_program_tuple
from funcloom.refine import (
    RefineOptions, RefineReport, apply_refinements_str, read_utf8_text_str,
)
from funcloom.models import Diagnostic

TOOLING_NAMES_TUPLE = ("setup.py", "conftest.py", "noxfile.py",
                       "fabfile.py", "manage.py", "__init__.py",
                       "__main__.py")
TEST_FOLDERS_TUPLE = ("test", "tests", "testing", "docs", "doc")
SCRIPT_STATEMENTS_TUPLE = (ast.Expr, ast.For, ast.AsyncFor, ast.While,
                           ast.With, ast.AsyncWith)
DATA_LIMIT_BYTES_INT = 200_000_000
ORCHESTRATOR_TEMPLATE_STR = '''"""Run a pipeline that FuncLoom generated.

Usage: python main.py [NAME] [ARGUMENTS...]
"""

from pathlib import Path
import runpy
import sys

ENTRY_SCRIPTS_DICT = {
__MAPPING__
}


def main() -> None:
    """Run the chosen entry script as if it were started directly.

    Args:
        None: Reads the pipeline name from the command line.
    Returns:
        None: The entry script runs in this process.
    Warnings:
        With several pipelines, the first argument must name one.
    """
    arguments_list = sys.argv[1:]
    if arguments_list and arguments_list[0] in ENTRY_SCRIPTS_DICT:
        name_str = arguments_list.pop(0)
    elif len(ENTRY_SCRIPTS_DICT) == 1:
        name_str = next(iter(ENTRY_SCRIPTS_DICT))
    else:
        raise SystemExit("Choose a pipeline: "
                         + ", ".join(ENTRY_SCRIPTS_DICT))
    script_path = Path(__file__).resolve().parent / (
        ENTRY_SCRIPTS_DICT[name_str])
    sys.argv = [str(script_path), *arguments_list]
    sys.path.insert(0, str(script_path.parent))
    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
'''


def project_files_tuple(
    root_path: Path, profile_info: RuleProfile,
) -> tuple[list[Path], list[Path]]:
    """List Python files and other files, skipping environments and links.

    Args:
        root_path (Path): Project folder.
        profile_info (RuleProfile): Excluded folder names.
    Returns:
        tuple: Python files and other files, sorted.
    Warnings:
        Symbolic links are never followed or copied. Folders holding a
        pyvenv.cfg are virtual environments and are skipped by any name.
    """
    python_list, other_list = [], []
    excluded_set = set(profile_info.excluded_dirs)
    for folder_str, folders_list, names_list in os.walk(root_path):
        folders_list[:] = sorted(
            name_str for name_str in folders_list
            if name_str not in excluded_set
            and not name_str.endswith(".egg-info")
            and not (Path(folder_str) / name_str).is_symlink()
            and not (Path(folder_str) / name_str / "pyvenv.cfg").is_file())
        for name_str in sorted(names_list):
            file_path = Path(folder_str) / name_str
            if file_path.is_symlink() or name_str.endswith((".pyc", ".pyo")):
                continue
            (python_list if name_str.endswith(".py") else other_list).append(
                file_path)
    return python_list, other_list


def compute_dotted_name_str(root_path: Path, file_path: Path) -> str:
    """Return the module name a file has relative to the project root.

    Args:
        root_path (Path): Project folder.
        file_path (Path): Python file inside it.
    Returns:
        str: Dotted name; a package's __init__.py maps to the package.
    Warnings:
        Folders without __init__.py are treated as namespace packages.
    """
    parts_list = list(file_path.relative_to(root_path).with_suffix("").parts)
    if parts_list[-1] == "__init__":
        parts_list.pop()
    return ".".join(parts_list)


def collect_imported_names_set(
    root_path: Path, file_path: Path, tree_node: ast.Module,
) -> set[str]:
    """List every module name an import in the file may load.

    Args:
        root_path (Path): Project folder.
        file_path (Path): File containing the imports.
        tree_node (ast.Module): Parsed file.
    Returns:
        set[str]: Dotted names, relative to the root and to the file's
            folder, including every parent package.
    Warnings:
        Imports built at runtime (importlib, __import__) are not seen.
    """
    folder_list = list(file_path.parent.relative_to(root_path).parts)
    names_set: set[str] = set()
    for node in ast.walk(tree_node):
        modules_list: list[str] = []
        if isinstance(node, ast.Import):
            modules_list = [alias_node.name for alias_node in node.names]
        elif isinstance(node, ast.ImportFrom):
            base_list = (folder_list[:len(folder_list) - node.level + 1]
                         if node.level else [])
            module_str = ".".join(base_list + (
                [node.module] if node.module else []))
            modules_list = [module_str] + [
                f"{module_str}.{alias_node.name}".strip(".")
                for alias_node in node.names]
        for module_str in filter(None, modules_list):
            parts_list = module_str.split(".")
            for index_int in range(1, len(parts_list) + 1):
                prefix_str = ".".join(parts_list[:index_int])
                names_set.add(prefix_str)
                names_set.add(".".join(folder_list + [prefix_str]))
    return names_set


def is_script_like_bool(tree_node: ast.Module) -> bool:
    """Decide whether a file runs code when executed, like a script.

    Args:
        tree_node (ast.Module): Parsed file.
    Returns:
        bool: True with a main guard, top-level calls, loops or with blocks.
    Warnings:
        A leading string literal is a docstring, not a script statement.
    """
    for index_int, node in enumerate(tree_node.body):
        docstring_bool = index_int == 0 and isinstance(node, ast.Expr) and (
            isinstance(node.value, ast.Constant))
        if is_plain_main_guard_bool(node) or (
            isinstance(node, SCRIPT_STATEMENTS_TUPLE) and not docstring_bool
        ):
            return True
    return False


def explain_entry_reason_str(
    relative_path: Path, tree_node: ast.Module, imported_bool: bool,
) -> str | None:
    """Return why a file is not an entry script, or None when it is one.

    Args:
        relative_path (Path): File path inside the project.
        tree_node (ast.Module): Parsed file.
        imported_bool (bool): Whether another local file imports it.
    Returns:
        str | None: Reason to copy it unchanged, or None.
    Warnings:
        Tests, tooling and package files are never modularized.
    """
    if not is_script_like_bool(tree_node):
        return "library module"
    if relative_path.name in TOOLING_NAMES_TUPLE or re.match(
        r"(test_.*|.*_test)\.py$", relative_path.name,
    ) or set(relative_path.parts[:-1]) & set(TEST_FOLDERS_TUPLE):
        return "test, tooling or package file"
    if imported_bool:
        return "imported by another project file"
    if any(isinstance(node, ast.ImportFrom) and node.level
           for node in ast.walk(tree_node)):
        return "uses relative imports"
    return None


def choose_entry_paths_dict(
    root_path: Path, python_list: list[Path], chosen_list: list[str] | None,
    report_info: ProjectReport,
) -> dict[Path, str]:
    """Choose entry scripts; record why other scripts stay unchanged.

    Args:
        root_path (Path): Project folder.
        python_list (list[Path]): Python files.
        chosen_list (list[str] | None): Relative paths the user chose.
        report_info (ProjectReport): Notes destination.
    Returns:
        dict[Path, str]: Entry file to its dotted module name.
    Warnings:
        Files that cannot be parsed are copied unchanged. A script whose
        bare name is imported anywhere counts as imported, because a
        sys.path change (common in tests) can make its folder importable.
        A module inside a package may be imported by its dotted name at
        run time (importlib, streamlit, entry points), so it is only
        converted when chosen explicitly.
    """
    trees_dict: dict[Path, ast.Module] = {}
    for file_path in python_list:
        try:
            trees_dict[file_path] = ast.parse(file_path.read_bytes())
        except (SyntaxError, ValueError) as error:
            report_info.kept_scripts[file_path.relative_to(
                root_path).as_posix()] = f"not valid Python: {error}"
    imported_set = set().union(*(
        collect_imported_names_set(root_path, path, tree)
        for path, tree in trees_dict.items()))
    entries_dict: dict[Path, str] = {}
    for file_path, tree_node in trees_dict.items():
        relative_path = file_path.relative_to(root_path)
        dotted_str = compute_dotted_name_str(root_path, file_path)
        reason_str = explain_entry_reason_str(
            relative_path, tree_node, dotted_str in imported_set
            or file_path.stem in imported_set)
        if reason_str is None and (file_path.parent / "__init__.py").exists():
            reason_str = "module inside a package; choose it with --entries"
        if chosen_list is not None:
            reason_str = (None if relative_path.as_posix() in chosen_list
                          else "not selected with --entries")
        if reason_str is None:
            entries_dict[file_path] = dotted_str
        elif is_script_like_bool(tree_node) or chosen_list is not None:
            report_info.kept_scripts[relative_path.as_posix()] = reason_str
    return entries_dict


def name_entry_package_str(file_path: Path, taken_set: set[str]) -> str:
    """Name an entry script's generated package next to the script.

    Args:
        file_path (Path): Entry script.
        taken_set (set[str]): Names already used in that folder.
    Returns:
        str: Unique package folder name such as train_app.
    Warnings:
        The shim keeps the script's own file name.
    """
    base_str = choose_package_name_str(file_path.stem, None)
    base_str = base_str if base_str.endswith("_app") else f"{base_str}_app"
    candidate_str, counter_int = base_str, 2
    while candidate_str in taken_set:
        candidate_str = f"{base_str}{counter_int}"
        counter_int += 1
    taken_set.add(candidate_str)
    return candidate_str


def plan_entry_tuple(
    root_path: Path, file_path: Path, profile_info: RuleProfile,
    taken_set: set[str], options_info: RefineOptions,
) -> tuple[ModularReport, dict[str, str] | None]:
    """Plan one entry script, placing its files next to the script.

    Args:
        root_path (Path): Project folder.
        file_path (Path): Entry script.
        profile_info (RuleProfile): Limits.
        taken_set (set[str]): Names used in the script's folder.
        options_info (RefineOptions): Splitting and documentation.
    Returns:
        tuple: Report and project-relative files, or None when refused.
    Warnings:
        main.py of the single-file layout becomes the script's own name.
    """
    source_info = load_program_source(file_path, None,
                                      profile_info.max_file_bytes)
    package_str = name_entry_package_str(file_path, taken_set)
    report_info, files_dict = plan_program_tuple(
        source_info, package_str, profile_info, options_info, file_path.name)
    if files_dict is None:
        return report_info, None
    folder_str = file_path.parent.relative_to(root_path).as_posix()
    prefix_str = "" if folder_str == "." else f"{folder_str}/"
    placed_dict = {}
    for relative_str, text_str in files_dict.items():
        target_str = file_path.name if relative_str == "main.py" else (
            relative_str)
        placed_dict[prefix_str + target_str] = text_str
    for file_info in report_info.files:
        file_info.path = prefix_str + (file_path.name if file_info.path == (
            "main.py") else file_info.path)
    report_info.checks["newline"] = detect_newline_style_str(source_info.text)
    return report_info, placed_dict


def render_orchestrator_text_str(entries_dict: dict[str, str]) -> str:
    """Render the root script that runs any generated pipeline.

    Args:
        entries_dict (dict[str, str]): Pipeline name to entry shim path.
    Returns:
        str: Script text with main() and a __main__ guard.
    Warnings:
        The chosen shim runs as if started directly, with its folder first
        on sys.path and the remaining arguments in sys.argv.
    """
    mapping_str = "\n".join(f'    "{name_str}": "{path_str}",'
                            for name_str, path_str in entries_dict.items())
    return ORCHESTRATOR_TEMPLATE_STR.replace("__MAPPING__", mapping_str)


def modularize_project_report(
    root_path: str | Path, output_dir: str | Path | None = None,
    entries_list: list[str] | None = None, skip_data_bool: bool = False,
    profile_info: RuleProfile | None = None,
    options_info: RefineOptions | None = None, convert_bool: bool = True,
) -> ProjectReport:
    """Turn every entry script of a folder into a package, copying the rest.

    Args:
        root_path (str | Path): Project folder.
        output_dir (str | Path | None): New folder; None plans only.
        entries_list (list[str] | None): Entry paths; None detects them.
        skip_data_bool (bool): Copy only Python files.
        profile_info (RuleProfile | None): Limits and excluded folders.
        options_info (RefineOptions | None): Splitting and documentation.
        convert_bool (bool): False only refines copies (refine command).
    Returns:
        ProjectReport: Per-entry reports, copies and diagnostics.
    Warnings:
        The input is never changed; non-empty outputs are refused.
    """
    profile_info = profile_info or RuleProfile()
    validate_profile_none(profile_info)
    root_path = Path(root_path).absolute()
    if not root_path.is_dir():
        raise ValueError("Project path must be a folder")
    report_info = ProjectReport(str(root_path))
    output_path = Path(output_dir).absolute() if output_dir else None
    if not output_outside_bool(root_path, output_path, report_info):
        return report_info
    texts_dict, copies_dict = plan_project_tuple(
        root_path, [] if not convert_bool else entries_list, skip_data_bool,
        profile_info, report_info, options_info or RefineOptions())
    if not any(
            diagnostic_info.severity == "error"
            for diagnostic_info in report_info.diagnostics):
        report_info.status = "planned"
        if output_path is not None:
            write_project_report_none(texts_dict, copies_dict, output_path,
                                      report_info)
    return report_info


def output_outside_bool(
    root_path: Path, output_path: Path | None, report_info: ProjectReport,
) -> bool:
    """Refuse an output folder inside the project being converted.

    Args:
        root_path (Path): Project folder.
        output_path (Path | None): Requested output folder.
        report_info (ProjectReport): MOD006 destination.
    Returns:
        bool: True when there is no output or it is outside the project.
    Warnings:
        Writing inside the input would copy the output into itself.
    """
    if output_path is not None and output_path.is_relative_to(root_path):
        add_project_issue_none(report_info, "MOD006",
                               "The output folder must be outside the input.")
        return False
    return True


def write_project_report_none(
    texts_dict: dict[str, str], copies_dict: dict[str, Path],
    output_path: Path, report_info: ProjectReport,
) -> None:
    """Write the project and record the outcome.

    Args:
        texts_dict (dict[str, str]): Generated files.
        copies_dict (dict[str, Path]): Files copied unchanged.
        output_path (Path): New or empty folder.
        report_info (ProjectReport): Status destination.
    Returns:
        None: Sets written or refused statuses.
    Warnings:
        A folder with contents is never written into (MOD006).
    """
    try:
        write_project_none(texts_dict, copies_dict, output_path,
                           report_info.newlines)
    except (ValueError, OSError) as error:
        add_project_issue_none(report_info, "MOD006", str(error))
        report_info.status = "refused"
        return
    report_info.status, report_info.output_dir = "written", str(output_path)
    for entry_info in report_info.entries:
        if entry_info.status == "planned":
            entry_info.status, entry_info.output_dir = "written", str(
                output_path)


def add_project_issue_none(
    report_info: ProjectReport, code_str: str, message_str: str,
) -> None:
    """Record a project-level refusal.

    Args:
        report_info (ProjectReport): Report being assembled.
        code_str (str): Diagnostic code.
        message_str (str): Reason.
    Returns:
        None: Appends an error diagnostic.
    Warnings:
        Any error stops writing.
    """
    report_info.diagnostics.append(Diagnostic(
        code_str, "error", report_info.root, 1, 1, message_str))


def plan_project_tuple(
    root_path: Path, entries_list: list[str] | None, skip_data_bool: bool,
    profile_info: RuleProfile, report_info: ProjectReport,
    options_info: RefineOptions,
) -> tuple[dict[str, str], dict[str, Path]]:
    """Plan generated texts and unchanged copies for the whole project.

    Args:
        root_path (Path): Project folder.
        entries_list (list[str] | None): Chosen entry scripts.
        skip_data_bool (bool): Copy only Python files.
        profile_info (RuleProfile): Limits.
        report_info (ProjectReport): Entries, copies and notes destination.
        options_info (RefineOptions): Splitting and documentation.
    Returns:
        tuple: Generated texts and files to copy, by relative path.
    Warnings:
        An entry that is refused is copied unchanged instead.
    """
    python_list, other_list = project_files_tuple(root_path, profile_info)
    entries_dict = choose_entry_paths_dict(
        root_path, python_list, entries_list, report_info
    ) if entries_list != [] else {}
    texts_dict: dict[str, str] = {}
    shims_dict: dict[str, str] = {}
    newlines_dict: dict[str, str] = {}
    converted_set = {file_path for file_path in entries_dict
                     if convert_entry_bool(root_path, file_path, profile_info,
                                           texts_dict, shims_dict,
                                           report_info, options_info,
                                           newlines_dict)}
    copies_dict = copy_plan_dict(root_path, python_list, other_list,
                                 converted_set, skip_data_bool, report_info)
    refine_copies_none(copies_dict, texts_dict, profile_info, options_info,
                       report_info, newlines_dict)
    if shims_dict:
        name_str = "main.py" if "main.py" not in texts_dict and (
            "main.py" not in copies_dict) else "run_pipelines.py"
        texts_dict[name_str] = render_orchestrator_text_str(shims_dict)
        report_info.orchestrator = name_str
    report_info.newlines = newlines_dict
    return texts_dict, copies_dict


def list_folder_names_set(
    root_path: Path, folder_path: Path, texts_dict: dict[str, str],
) -> set[str]:
    """List names already used directly inside one output folder.

    Args:
        root_path (Path): Project folder.
        folder_path (Path): Folder of the entry script.
        texts_dict (dict[str, str]): Files generated so far.
    Returns:
        set[str]: Existing file and folder names plus generated ones.
    Warnings:
        Used to keep generated package names unique per folder.
    """
    prefix_list = list(folder_path.relative_to(root_path).parts)
    names_set = {child_path.name for child_path in folder_path.iterdir()}
    for key_str in texts_dict:
        parts_list = Path(key_str).parts
        if list(parts_list[:len(prefix_list)]) == prefix_list and len(
            parts_list,
        ) > len(prefix_list):
            names_set.add(parts_list[len(prefix_list)])
    return names_set


def convert_entry_bool(
    root_path: Path, file_path: Path, profile_info: RuleProfile,
    texts_dict: dict[str, str], shims_dict: dict[str, str],
    report_info: ProjectReport, options_info: RefineOptions,
    newlines_dict: dict[str, str],
) -> bool:
    """Plan one entry script and record its files or its refusal.

    Args:
        root_path (Path): Project folder.
        file_path (Path): Entry script.
        profile_info (RuleProfile): Limits.
        texts_dict (dict[str, str]): Generated files, extended in place.
        shims_dict (dict[str, str]): Pipeline name to shim path.
        report_info (ProjectReport): Entries and kept scripts.
        options_info (RefineOptions): Splitting and documentation.
        newlines_dict (dict[str, str]): Line ending per generated file.
    Returns:
        bool: True when the script was converted.
    Warnings:
        A refused script is copied unchanged by the caller.
    """
    entry_info, placed_dict = plan_entry_tuple(
        root_path, file_path, profile_info,
        list_folder_names_set(root_path, file_path.parent, texts_dict),
        options_info)
    report_info.entries.append(entry_info)
    relative_str = file_path.relative_to(root_path).as_posix()
    if placed_dict is None:
        report_info.kept_scripts[relative_str] = "refused: " + "; ".join(
            f"{diagnostic_info.code} line {diagnostic_info.line}"
            for diagnostic_info in entry_info.diagnostics
            if diagnostic_info.severity == "error")
        return False
    texts_dict.update(placed_dict)
    newlines_dict.update(dict.fromkeys(
        placed_dict, entry_info.checks.get("newline", "\n")))
    name_str = choose_package_name_str(file_path.stem, None)
    if name_str in shims_dict:
        name_str = choose_package_name_str(relative_str[:-3], None)
    shims_dict[name_str] = relative_str
    return True


def refine_copies_none(
    copies_dict: dict[str, Path], texts_dict: dict[str, str],
    profile_info: RuleProfile, options_info: RefineOptions,
    report_info: ProjectReport, newlines_dict: dict[str, str],
) -> None:
    """Refine copied Python files; changed files move to generated texts.

    Args:
        copies_dict (dict[str, Path]): Files to copy, updated in place.
        texts_dict (dict[str, str]): Generated files, extended in place.
        profile_info (RuleProfile): Limits.
        options_info (RefineOptions): Enabled refinements.
        report_info (ProjectReport): Summary destination.
        newlines_dict (dict[str, str]): Line ending per generated file.
    Returns:
        None: Moves refined files from copies to texts.
    Warnings:
        Compilation and wrapping still run when splitting is disabled.
        Refined files keep their line-ending style and become UTF-8. A
        copied file that does not compile is copied unchanged (MODW07);
        the single-file refine command refuses it instead.
    """
    refine_info = RefineReport(report_info.root)
    for relative_str, source_path in list(copies_dict.items()):
        text_str = (
            read_utf8_text_str(source_path, profile_info.max_file_bytes)
            if relative_str.endswith(".py") else None)
        if text_str is None:
            if relative_str.endswith(".py"):
                report_info.notes.append(f"{relative_str}: copied without "
                                         "refinement; not readable UTF-8 "
                                         "within the source size limit.")
            continue
        refined_str = apply_refinements_str(text_str, relative_str,
                                            profile_info, options_info,
                                            refine_info)
        if refined_str != text_str:
            texts_dict[relative_str] = refined_str
            newlines_dict[relative_str] = detect_newline_style_str(text_str)
            del copies_dict[relative_str]
            report_info.refined_files.append(relative_str)
    report_info.split_functions += refine_info.split_functions
    report_info.documented_functions += refine_info.documented_functions
    report_info.notes += refine_info.notes
    report_info.diagnostics += [Diagnostic(
        "MODW07", "warning", diagnostic_info.path, diagnostic_info.line,
        diagnostic_info.column,
        f"Copied unchanged: {diagnostic_info.message}") for diagnostic_info in
        refine_info.diagnostics]


def copy_plan_dict(
    root_path: Path, python_list: list[Path], other_list: list[Path],
    converted_set: set[Path], skip_data_bool: bool,
    report_info: ProjectReport,
) -> dict[str, Path]:
    """Choose which files are copied unchanged, enforcing the data limit.

    Args:
        root_path (Path): Project folder.
        python_list (list[Path]): Python files.
        other_list (list[Path]): Data and other files.
        converted_set (set[Path]): Entry scripts replaced by packages.
        skip_data_bool (bool): Leave out non-Python files.
        report_info (ProjectReport): Copy summary and refusal destination.
    Returns:
        dict[str, Path]: Relative destination to source file.
    Warnings:
        More than 200 MB of other files is refused unless skipped.
    """
    chosen_list = [path for path in python_list if path not in converted_set]
    if not skip_data_bool:
        chosen_list += other_list
    total_int = sum(path.stat().st_size for path in chosen_list)
    if total_int > DATA_LIMIT_BYTES_INT:
        add_project_issue_none(report_info, "MOD009", (
            f"{total_int} bytes to copy exceeds the limit; use --skip-data "
            "and copy data files yourself."))
    report_info.copied_bytes = total_int
    copies_dict = {path.relative_to(root_path).as_posix(): path
                   for path in chosen_list}
    report_info.copied_files = sorted(copies_dict)
    if skip_data_bool and other_list:
        report_info.notes.append(
            f"{len(other_list)} non-Python files were not copied.")
    return copies_dict
