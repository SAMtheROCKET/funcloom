"""Load scripts, snippets and notebooks as one combined program."""

from hashlib import sha256
import json
from pathlib import Path
import re

from funcloom.modular_models import ProgramSegment, ProgramSource
from funcloom.modular_text import find_string_interior_lines_set
from funcloom.snippet_source import validate_language_none
from funcloom.syntax import read_source_tuple

KEPT_CELL_MAGICS_TUPLE = ("time", "capture")
MAGIC_NOTE_STR = "# [funcloom] notebook magic removed:"


def parse_cells_list(cells_str: str | None) -> list[int] | None:
    """Read a cell selection such as "2,4-6" into one-based indices.

    Args:
        cells_str (str | None): Comma-separated numbers and ranges.
    Returns:
        list[int] | None: Sorted unique indices, or None for all cells.
    Warnings:
        Indices count every notebook cell, including Markdown cells.
    """
    if cells_str is None:
        return None
    indices_set: set[int] = set()
    for part_str in cells_str.split(","):
        match_info = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part_str)
        if match_info is None:
            raise ValueError(f"Invalid cell selection: {part_str!r}")
        first_int = int(match_info.group(1))
        last_int = int(match_info.group(2) or first_int)
        if first_int < 1 or last_int < first_int:
            raise ValueError(f"Invalid cell range: {part_str!r}")
        indices_set.update(range(first_int, last_int + 1))
    return sorted(indices_set)


def load_program_source(
    source_path: str | Path, cells_list: list[int] | None,
    max_bytes_int: int,
) -> ProgramSource:
    """Read a .py file or notebook cells as one Python program.

    Args:
        source_path (str | Path): Python or notebook document.
        cells_list (list[int] | None): Selected notebook cells, or all.
        max_bytes_int (int): Maximum original document size.
    Returns:
        ProgramSource: Combined text, provenance and notes.
    Warnings:
        Nothing is executed; notebook outputs and kernel state are ignored.
    """
    source_path = Path(source_path).absolute()
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError("Input must be a regular file, not a link")
    if source_path.suffix == ".py":
        if cells_list is not None:
            raise ValueError("--cells requires an .ipynb notebook")
        text_str, digest_str = read_source_tuple(source_path, max_bytes_int)
        return ProgramSource(str(source_path), text_str, source_path.stem,
                             document_sha256=digest_str)
    if source_path.suffix != ".ipynb":
        raise ValueError("Input must be a .py file or an .ipynb notebook")
    raw_bytes = source_path.read_bytes()
    if len(raw_bytes) > max_bytes_int:
        raise ValueError("Notebook exceeds the configured file byte limit")
    document_dict = json.loads(raw_bytes.decode("utf-8-sig"))
    program_info = combine_notebook_program_info(document_dict, cells_list)
    program_info.name, program_info.stem = str(source_path), source_path.stem
    program_info.document_sha256 = sha256(raw_bytes).hexdigest()
    return program_info


def read_cell_text_str(cell_dict: dict) -> str:
    """Return a notebook cell's source as one string.

    Args:
        cell_dict (dict): Notebook cell object.
    Returns:
        str: Cell text, ending with a newline when not empty.
    Warnings:
        Raises ValueError for malformed cell sources.
    """
    source_value = cell_dict.get("source", "")
    if isinstance(source_value, list) and all(
        isinstance(line_str, str) for line_str in source_value
    ):
        source_value = "".join(source_value)
    if not isinstance(source_value, str):
        raise ValueError("Notebook cell source must be text")
    if source_value and not source_value.endswith("\n"):
        source_value += "\n"
    return source_value


def pick_heading_title_str(markdown_str: str) -> str:
    """Pick a step title from Markdown text.

    Args:
        markdown_str (str): Markdown cell text.
    Returns:
        str: The last heading's text, or an empty string.
    Warnings:
        Only '#' headings are used; prose is not interpreted.
    """
    headings_list = [line_str.lstrip("#").strip() for line_str in
                     markdown_str.splitlines()
                     if line_str.lstrip().startswith("#")]
    return headings_list[-1] if headings_list else ""


def combine_notebook_program_info(
    document_dict: dict, cells_list: list[int] | None,
) -> ProgramSource:
    """Combine selected code cells in document order.

    Args:
        document_dict (dict): Decoded version 4 notebook.
        cells_list (list[int] | None): One-based cell indices, or all.
    Returns:
        ProgramSource: Combined code with one segment per code cell.
    Warnings:
        Cells are combined in document order, not execution-count order.
    """
    if not isinstance(document_dict, dict) or (
        document_dict.get("nbformat") != 4
    ):
        raise ValueError("Expected a version 4 notebook object")
    validate_language_none(document_dict.get("metadata", {}))
    all_cells_list = document_dict.get("cells")
    if not isinstance(all_cells_list, list):
        raise ValueError("Notebook cells must be a list")
    code_indices_list = [index_int for index_int, cell_dict in
                         enumerate(all_cells_list, 1)
                         if isinstance(cell_dict, dict)
                         and cell_dict.get("cell_type") == "code"]
    selected_list = code_indices_list if cells_list is None else cells_list
    if not set(selected_list) <= set(code_indices_list) or not selected_list:
        raise ValueError("Selected cells must be existing code cells")
    program_info = ProgramSource("", "", "")
    title_str, lines_list = "", []
    for index_int, cell_dict in enumerate(all_cells_list, 1):
        if cell_dict.get("cell_type") == "markdown":
            heading_str = pick_heading_title_str(read_cell_text_str(cell_dict))
            title_str = heading_str or title_str
        elif index_int in selected_list:
            append_cell_none(
                read_cell_text_str(cell_dict), index_int, title_str,
                lines_list, program_info)
            title_str = ""
    program_info.text = "".join(lines_list)
    return program_info


def append_cell_none(
    cell_str: str, index_int: int, title_str: str, lines_list: list[str],
    program_info: ProgramSource,
) -> None:
    """Add one code cell to the combined program, neutralizing magics.

    Args:
        cell_str (str): Cell text.
        index_int (int): One-based document cell index.
        title_str (str): Nearest preceding Markdown heading.
        lines_list (list[str]): Combined program lines so far.
        program_info (ProgramSource): Segment and note destination.
    Returns:
        None: Appends lines, one segment and any notes.
    Warnings:
        Unsupported cell magics skip the whole cell, with a note.
    """
    cell_lines_list = cell_str.splitlines(keepends=True)
    if cell_lines_list and cell_lines_list[0].startswith("%%"):
        magic_str = cell_lines_list[0][2:].split()[0] if (
            cell_lines_list[0][2:].split()
        ) else ""
        if magic_str not in KEPT_CELL_MAGICS_TUPLE:
            program_info.notes.append(
                f"Cell {index_int} skipped: cell magic %%{magic_str} is not "
                "Python.")
            return
        program_info.notes.append(
            f"Cell {index_int}: %%{magic_str} removed; its code is kept.")
        cell_lines_list = cell_lines_list[1:]
    first_int = len(lines_list) + 1
    kept_set = find_string_lines_set(cell_lines_list)
    for number_int, line_str in enumerate(cell_lines_list, 1):
        lines_list.append(line_str if number_int in kept_set else
                          neutralize_magic_line_str(line_str, index_int,
                                                    program_info))
    if not cell_lines_list or not lines_list[-1].endswith("\n"):
        lines_list.append("\n")
    program_info.segments.append(ProgramSegment(
        title_str, f"cell {index_int}", first_int, len(lines_list),
    ))
    lines_list.append("\n")


def is_magic_like_bool(line_str: str) -> bool:
    """Tell whether a cell line looks like an IPython magic or escape.

    Args:
        line_str (str): One cell line.
    Returns:
        bool: True for %magic, !shell and name? help lines.
    Warnings:
        Looks at one line only; find_string_lines_set excludes string text.
    """
    stripped_str = line_str.strip()
    return stripped_str.startswith(("%", "!")) or bool(re.fullmatch(
        r"[\w.]+\?{1,2}", stripped_str))


def find_string_lines_set(cell_lines_list: list[str]) -> set[int]:
    """Find cell lines inside multi-line strings, which are never magics.

    Args:
        cell_lines_list (list[str]): Lines of one code cell.
    Returns:
        set[int]: One-based line numbers inside string literals; empty
            when the cell cannot be tokenized.
    Warnings:
        Magic-looking lines are replaced by pass for tokenizing, so real
        magics do not break the scan.
    """
    probe_list = [
        line_str[:len(line_str) - len(line_str.lstrip())] + "pass\n"
        if is_magic_like_bool(line_str) else line_str
        for line_str in cell_lines_list]
    return find_string_interior_lines_set("".join(probe_list)) or set()


def neutralize_magic_line_str(
    line_str: str, index_int: int, program_info: ProgramSource,
) -> str:
    """Replace an IPython line magic or shell escape with a comment.

    Args:
        line_str (str): One cell line.
        index_int (int): Cell index for the note.
        program_info (ProgramSource): Note destination.
    Returns:
        str: The line, or a comment (with pass when indented).
    Warnings:
        Assignments from magics such as x = !ls stay and fail to parse.
    """
    stripped_str = line_str.strip()
    if not is_magic_like_bool(line_str):
        return line_str
    indent_str = line_str[:len(line_str) - len(line_str.lstrip())]
    program_info.notes.append(
        f"Cell {index_int}: notebook magic removed: {stripped_str}")
    prefix_str = f"{indent_str}pass  " if indent_str else ""
    return f"{prefix_str}{MAGIC_NOTE_STR} {stripped_str}\n"
