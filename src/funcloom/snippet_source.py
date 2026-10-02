"""Bounded Python and notebook-cell reading with no kernel execution."""

from hashlib import sha256
import json
from pathlib import Path

from funcloom.snippet_models import SnippetSource
from funcloom.syntax import read_source_tuple


def read_snippet_source(
    source_path: str | Path, cell_index_int: int | None,
    max_bytes_int: int,
) -> SnippetSource:
    """Read one Python file or explicitly selected notebook code cell.

    Args:
        source_path (str | Path): Python or notebook document.
        cell_index_int (int | None): One-based index among all notebook cells.
        max_bytes_int (int): Maximum original document byte count.
    Returns:
        SnippetSource: Text and original document fingerprint.
    Warnings:
        Other cells, outputs and kernel state are never executed or imported.
    """
    source_path = Path(source_path).absolute()
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError("Snippet input must be a regular file, not a link")
    if source_path.suffix == ".py":
        if cell_index_int is not None:
            raise ValueError("--cell requires an .ipynb notebook")
        source_str, digest_str = read_source_tuple(source_path, max_bytes_int)
        return SnippetSource(str(source_path), source_str, digest_str)
    if source_path.suffix != ".ipynb":
        raise ValueError("Snippet input must be .py or .ipynb")
    with source_path.open("rb") as source_file:
        raw_bytes = source_file.read(max_bytes_int + 1)
    if len(raw_bytes) > max_bytes_int:
        raise ValueError("Notebook exceeds the configured file byte limit")
    document_dict = json.loads(raw_bytes.decode("utf-8-sig"))
    source_str, index_int = select_notebook_cell_tuple(
        document_dict, cell_index_int)
    return SnippetSource(
        str(source_path), source_str, sha256(raw_bytes).hexdigest(), index_int,
    )


def select_notebook_cell_tuple(
    document_dict: dict, cell_index_int: int | None,
) -> tuple[str, int]:
    """Select a Python code cell without combining notebook execution state.

    Args:
        document_dict (dict): Decoded notebook JSON.
        cell_index_int (int | None): Requested one-based document cell index.
    Returns:
        tuple[str, int]: Exact cell text and selected document index.
    Warnings:
        Multi-cell notebooks require an explicit selection.
    """
    if not isinstance(document_dict, dict) or (
        document_dict.get("nbformat") != 4
    ):
        raise ValueError("Expected a version 4 notebook object")
    cells_list = document_dict.get("cells")
    if not isinstance(cells_list, list) or not all(
        isinstance(cell_dict, dict) for cell_dict in cells_list
    ):
        raise ValueError("Notebook cells must be a list of objects")
    validate_language_none(document_dict.get("metadata", {}))
    indices_list = [index_int for index_int, cell_dict in
                    enumerate(cells_list, 1)
                    if cell_dict.get("cell_type") == "code"]
    if cell_index_int is None and len(indices_list) == 1:
        cell_index_int = indices_list[0]
    if type(cell_index_int) is not int or cell_index_int not in indices_list:
        raise ValueError("Choose --cell with a one-based code-cell index")
    source_value = cells_list[cell_index_int - 1].get("source")
    if isinstance(source_value, list) and all(
        isinstance(line_str, str) for line_str in source_value
    ):
        source_value = "".join(source_value)
    if not isinstance(source_value, str):
        raise ValueError("Notebook cell source must be text or a text list")
    return source_value, cell_index_int


def validate_language_none(metadata_dict: dict) -> None:
    """Reject declared non-Python kernels without loading a kernel.

    Args:
        metadata_dict (dict): Notebook metadata, if present.
    Returns:
        None: Raises ValueError for non-Python language declarations.
    Warnings:
        Missing language metadata does not prove Python semantics.
    """
    if not isinstance(metadata_dict, dict):
        raise ValueError("Notebook metadata must be an object")
    for key_str, field_str in (("language_info", "name"),
                               ("kernelspec", "language")):
        language_dict = metadata_dict.get(key_str, {})
        if not isinstance(language_dict, dict):
            raise ValueError("Notebook language metadata must be an object")
        language_str = language_dict.get(field_str, "python")
        if not isinstance(language_str, str) or (
            language_str.lower() not in ("python", "python3")
        ):
            raise ValueError("Only Python notebook cells are supported")
