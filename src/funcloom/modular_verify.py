"""Check generated modules against the original program, then write them."""

import ast
import builtins
import os
import re
from pathlib import Path
import shutil
import uuid

from funcloom.modular_models import PackageDraft
from funcloom.modular_pipeline import (
    choose_attribute_names_dict, call_lines_list,
)
from funcloom.modular_render import return_str
from funcloom.modular_scan import collect_statement_names_info
from funcloom.modular_text import rename_constants_node

CODING_PATTERN = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")


def dump_trees_list(nodes_list: list[ast.AST]) -> list[str]:
    """Dump syntax trees for structural comparison.

    Args:
        nodes_list (list[ast.AST]): Nodes to compare.
    Returns:
        list[str]: Dumps without line or column information.
    Warnings:
        Equal dumps mean equal structure, not proven equal behavior.
    """
    return [ast.dump(node) for node in nodes_list]


def check_pipeline_layout_bool(
    draft_info: PackageDraft, trees_dict: dict[str, ast.Module],
) -> bool:
    """Check that wrapping did not change the pipeline's step calls.

    Args:
        draft_info (PackageDraft): Program, steps and line width.
        trees_dict (dict[str, ast.Module]): Parsed generated files.
    Returns:
        bool: True when the step calls in run() and its stages, in order,
            equal their unwrapped form, or when there is no pipeline.
    Warnings:
        Guards against layout mistakes such as unpacking one result;
        how calls are grouped into stages is not compared.
    """
    tree_node = trees_dict.get(f"{draft_info.package_name}/pipeline.py")
    if tree_node is None:
        return True
    methods_dict = {node.name: node for class_node in tree_node.body
                    if isinstance(class_node, ast.ClassDef)
                    for node in class_node.body
                    if isinstance(node, ast.FunctionDef)}
    stages_list = sorted((name_str for name_str in methods_dict
                          if name_str.startswith("run_stage_")),
                         key=lambda name_str: int(name_str.rsplit("_", 1)[1]))
    actual_list = [node for name_str in stages_list or ["run"]
                   for node in methods_dict.get(name_str, ast.Pass()).body
                   if not (isinstance(node, ast.Expr) and isinstance(
                       node.value, ast.Constant))]
    attributes_dict = choose_attribute_names_dict(draft_info)
    expected_list = [ast.parse(line_str.strip()).body[0]
                     for step_info in draft_info.steps
                     for line_str in call_lines_list(
                         step_info, attributes_dict, 10 ** 6)]
    return dump_trees_list(actual_list) == dump_trees_list(expected_list)


def step_problems_list(
    draft_info: PackageDraft, functions_list: list[ast.FunctionDef],
) -> list[str]:
    """Compare each step function with its original statements.

    Args:
        draft_info (PackageDraft): Program, steps and constant renames.
        functions_list (list[ast.FunctionDef]): Step functions in order.
    Returns:
        list[str]: Problems; empty when every body and return matches.
    Warnings:
        The return must equal its unwrapped form, so one output is never
        returned as a one-item tuple.
    """
    problems_list = []
    for step_info, function_node in zip(draft_info.steps, functions_list):
        expected_list = [
            rename_constants_node(top_info.node, draft_info.constants)
            for top_info in step_info.statements]
        if dump_trees_list(
                function_node.body[1:-1]) != dump_trees_list(expected_list):
            problems_list.append(f"Step {step_info.name} changed structure.")
        expected_return = ast.parse(
            return_str(step_info, 10 ** 6).strip()).body[0]
        if dump_trees_list(function_node.body[-1:]) != dump_trees_list(
            [expected_return],
        ):
            problems_list.append(f"Step {step_info.name} returns changed.")
    return problems_list


def verify_structure_list(
    draft_info: PackageDraft, files_dict: dict[str, str],
) -> list[str]:
    """Compare generated code with the renamed original statements.

    Args:
        draft_info (PackageDraft): Program, steps and module layout.
        files_dict (dict[str, str]): Relative path to generated text.
    Returns:
        list[str]: Problems found; empty when everything matches.
    Warnings:
        Leading imports must be retained in order in _imports.py.
    """
    package_str, renames_dict = draft_info.package_name, draft_info.constants
    problems_list = []
    trees_dict = {path_str: ast.parse(text_str)
                  for path_str, text_str in files_dict.items()}
    imports_list = [top_info.node for top_info in draft_info.statements
                    if top_info.kind in ("future", "import")]
    imports_tree = trees_dict.get(f"{package_str}/_imports.py")
    if any(
            top_info.kind == "import" for top_info in draft_info.statements
    ) and (
            imports_tree is None
            or dump_trees_list(imports_tree.body)
            != (dump_trees_list(imports_list))):
        problems_list.append("Leading imports changed structure or order.")
    steps_tree = trees_dict.get(f"{package_str}/steps.py")
    functions_list = [node for node in getattr(steps_tree, "body", [])
                      if isinstance(node, ast.FunctionDef)]
    problems_list += step_problems_list(draft_info, functions_list)
    if len(functions_list) != len(draft_info.steps):
        problems_list.append("Generated step count does not match.")
    if not check_pipeline_layout_bool(draft_info, trees_dict):
        problems_list.append("Pipeline calls changed when wrapped.")
    for stem_str, items_list in draft_info.modules.items():
        tree_node = trees_dict[f"{package_str}/{stem_str}.py"]
        generated_list = [node for node in tree_node.body if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        expected_list = [
            rename_constants_node(definition_info.node, renames_dict)
            for definition_info in items_list]
        if dump_trees_list(generated_list) != dump_trees_list(expected_list):
            problems_list.append(f"Module {stem_str} changed structure.")
    return problems_list


def find_undefined_names_set(tree_node: ast.Module) -> set[str]:
    """Find names a module reads that it neither defines nor imports.

    Args:
        tree_node (ast.Module): Generated module.
    Returns:
        set[str]: Unresolved names, excluding builtins.
    Warnings:
        Wildcard imports make the result unreliable; callers skip them.
    """
    bound_set, read_set = set(dir(builtins)), set()
    for node in tree_node.body:
        names_info = collect_statement_names_info(node)
        bound_set |= names_info.writes
        read_set |= names_info.direct_reads | names_info.nested_reads
    return read_set - bound_set


def verify_names_list(
    draft_info: PackageDraft, files_dict: dict[str, str],
) -> list[str]:
    """Check that every generated module can resolve the names it reads.

    Args:
        draft_info (PackageDraft): Original program statements.
        files_dict (dict[str, str]): Relative path to generated text.
    Returns:
        list[str]: Problems; names already undefined originally are fine.
    Warnings:
        This catches missing generated imports, not runtime errors.
    """
    original_bound_set = set(dir(builtins)).union(*(
        top_info.names.writes for top_info in draft_info.statements))
    original_reads_set = set().union(*(
        top_info.names.direct_reads | top_info.names.nested_reads
        for top_info in draft_info.statements))
    allowed_set = (original_reads_set - original_bound_set) | set(
        draft_info.constants.values())
    problems_list = []
    for path_str, text_str in files_dict.items():
        tree_node = ast.parse(text_str)
        if "*" in {alias.name for node in ast.walk(tree_node)
                   if isinstance(node, ast.ImportFrom)
                   for alias in node.names}:
            continue
        missing_set = find_undefined_names_set(tree_node) - allowed_set
        if missing_set:
            problems_list.append(
                f"{path_str} cannot resolve {', '.join(sorted(missing_set))}.")
    return problems_list


def verify_files_list(
    draft_info: PackageDraft, files_dict: dict[str, str],
) -> list[str]:
    """Compile, compare structure and resolve names of generated files.

    Args:
        draft_info (PackageDraft): Program and plan.
        files_dict (dict[str, str]): Relative path to generated text.
    Returns:
        list[str]: Problems; empty means every check passed.
    Warnings:
        Passing is not a proof that the package behaves identically.
    """
    for path_str, text_str in files_dict.items():
        try:
            compile(text_str, path_str, "exec", dont_inherit=True)
        except SyntaxError as error:
            return [f"{path_str} does not compile: {error.msg} "
                    f"(line {error.lineno})."]
    return (verify_structure_list(draft_info, files_dict)
            + verify_names_list(draft_info, files_dict))


def detect_newline_style_str(text_str: str) -> str:
    """Return the line ending a text mostly uses.

    Args:
        text_str (str): File text.
    Returns:
        str: "\\r\\n" when most line breaks are CRLF, otherwise "\\n".
    Warnings:
        Old Mac-style CR-only files are written with LF.
    """
    crlf_int = text_str.count("\r\n")
    return "\r\n" if crlf_int and crlf_int * 2 >= text_str.count("\n") else (
        "\n")


def normalize_newlines_str(text_str: str) -> str:
    """Convert every line ending to LF before writing.

    Args:
        text_str (str): Text with any line endings.
    Returns:
        str: Text using LF only.
    Warnings:
        Python treats a bare CR as a line break, so none can be inside a
        string literal. Every written file is UTF-8, so a coding
        declaration in its first two lines is rewritten to utf-8; the
        line count does not change.
    """
    lines_list = text_str.replace("\r\n", "\n").replace(
        "\r", "\n").split("\n")
    for index_int in range(min(2, len(lines_list))):
        match_info = CODING_PATTERN.match(lines_list[index_int])
        if match_info:
            line_str = lines_list[index_int]
            lines_list[index_int] = (line_str[:match_info.start(1)] + "utf-8"
                                     + line_str[match_info.end(1):])
    return "\n".join(lines_list)


def write_files_none(
    files_dict: dict[str, str], output_path: Path, newline_str: str = "\n",
) -> None:
    """Write all files to a new folder in one final rename.

    Args:
        files_dict (dict[str, str]): Relative path to text.
        output_path (Path): Destination folder; must be new or empty.
        newline_str (str): Line ending to write, matching the source.
    Returns:
        None: Creates the folder and its files.
    Warnings:
        Nothing is written into a folder that already has contents.
    """
    if output_path.exists() and (
        not output_path.is_dir() or any(output_path.iterdir())
    ):
        raise ValueError(f"Output folder is not empty: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = output_path.parent / (
        f".{output_path.name}.funcloom-{uuid.uuid4().hex[:8]}")
    try:
        for relative_str, text_str in files_dict.items():
            file_path = staging_path / relative_str
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("x", encoding="utf-8",
                                newline=newline_str) as file:
                file.write(normalize_newlines_str(text_str))
        if output_path.exists():
            output_path.rmdir()
        staging_path.rename(output_path)
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path)


def read_windows_path_limit_int() -> int | None:
    """Return the Windows path length limit, or None when there is none.

    Args:
        None: Reads the platform and the long-path system setting.
    Returns:
        int | None: 259 when long paths are disabled on Windows.
    Warnings:
        An unreadable setting is treated as disabled, the Windows default.
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, (
            r"SYSTEM\CurrentControlSet\Control\FileSystem"),
        ) as key_handle:
            if winreg.QueryValueEx(key_handle, "LongPathsEnabled")[0]:
                return None
    except OSError:
        pass
    return 259


def check_path_lengths_none(staging_path: Path, relative_list: list) -> None:
    """Refuse before writing when a file path would be too long.

    Args:
        staging_path (Path): Temporary folder the files are written to.
        relative_list (list): Relative paths of every file to write.
    Returns:
        None: Raises ValueError naming the longest path.
    Warnings:
        The staging name is a few characters longer than the output name.
    """
    limit_int = read_windows_path_limit_int()
    if limit_int is None or not relative_list:
        return
    longest_str = max(
        (
            str(staging_path / relative_path_str)
            for relative_path_str in relative_list), key=len)
    if len(longest_str) > limit_int:
        raise ValueError(
            f"A file path would have {len(longest_str)} characters, over "
            f"the Windows limit of {limit_int}: {longest_str}. Choose a "
            "shorter output folder or enable Windows long paths.")


def write_project_none(
    texts_dict: dict[str, str], copies_dict: dict[str, Path],
    output_path: Path, newlines_dict: dict[str, str] | None = None,
) -> None:
    """Write generated texts and unchanged copies in one final rename.

    Args:
        texts_dict (dict[str, str]): Relative path to generated text.
        copies_dict (dict[str, Path]): Relative path to source file.
        output_path (Path): Destination folder; must be new or empty.
        newlines_dict (dict[str, str] | None): Line ending per text path.
    Returns:
        None: Creates the folder and its files.
    Warnings:
        Copies are byte-for-byte; nothing is written into a non-empty
        folder.
    """
    if output_path.exists() and (
        not output_path.is_dir() or any(output_path.iterdir())
    ):
        raise ValueError(f"Output folder is not empty: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = output_path.parent / (
        f".{output_path.name}.funcloom-{uuid.uuid4().hex[:8]}")
    check_path_lengths_none(staging_path, [*copies_dict, *texts_dict])
    try:
        for relative_str, source_path in copies_dict.items():
            target_path = staging_path / relative_str
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
        for relative_str, text_str in texts_dict.items():
            target_path = staging_path / relative_str
            target_path.parent.mkdir(parents=True, exist_ok=True)
            newline_str = (newlines_dict or {}).get(relative_str, "\n")
            with target_path.open("x", encoding="utf-8",
                                  newline=newline_str) as file:
                file.write(normalize_newlines_str(text_str))
        if output_path.exists():
            output_path.rmdir()
        staging_path.rename(output_path)
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path)
