"""Deterministic file discovery without following symbolic links."""

from pathlib import Path
import os

from funcloom.config import RuleProfile


def discover_python_paths_tuple(
    source_path: Path, profile: RuleProfile,
) -> tuple[Path, list[Path], list[dict[str, str]]]:
    """Find source paths while retaining relative directory structure.

    Args:
        source_path (Path): A Python file or directory.
        profile (RuleProfile): Directory exclusions and resource limits.
    Returns:
        tuple: Root, sorted source paths, and excluded-path records.
    Raises:
        ValueError: The target is invalid or contains no selected sources.
    Warnings:
        Gitignore patterns are not interpreted in this milestone.
    """
    source_path = source_path.absolute()
    if source_path.is_symlink():
        raise ValueError("The scan target must not be a symbolic link")
    if source_path.is_file():
        if source_path.suffix != ".py":
            raise ValueError("A file target must have the .py extension")
        source_path = source_path.resolve()
        return source_path.parent, [source_path], []
    if not source_path.is_dir():
        raise ValueError(f"Source directory does not exist: {source_path}")
    root_path = source_path.resolve()
    paths_list, skipped_list = walk_python_paths_tuple(root_path, profile)
    if not paths_list:
        raise ValueError("No Python files selected; check target/exclusions")
    return root_path, sorted(paths_list), skipped_list


def walk_python_paths_tuple(
    root_path: Path, profile: RuleProfile,
) -> tuple[list[Path], list[dict[str, str]]]:
    """Traverse a directory with exclusions and explicit failure handling.

    Args:
        root_path (Path): Resolved directory to traverse.
        profile (RuleProfile): Settings with excluded directory basenames.
    Returns:
        tuple: Selected paths and skipped-path records.
    Warnings:
        Symbolic links and environment/build directories are skipped.
    """
    paths_list: list[Path] = []
    skipped_list: list[dict[str, str]] = []
    excluded_set = set(profile.excluded_dirs)
    for folder_str, folders_list, names_list in os.walk(
        root_path, followlinks=False, onerror=raise_walk_error_none,
    ):
        folder_path = Path(folder_str)
        for name_str in sorted(folders_list.copy()):
            child_path = folder_path / name_str
            excluded_bool = (
                name_str in excluded_set or name_str.endswith(".egg-info")
                or (child_path / "pyvenv.cfg").is_file()
            )
            if child_path.is_symlink() or excluded_bool:
                folders_list.remove(name_str)
                skipped_list.append({
                    "path": child_path.relative_to(root_path).as_posix(),
                    "reason": "symlink" if child_path.is_symlink()
                    else "excluded directory",
                })
        folders_list.sort()
        for name_str in sorted(names_list):
            child_path = folder_path / name_str
            if child_path.suffix != ".py":
                continue
            if child_path.is_symlink():
                skipped_list.append({
                    "path": child_path.relative_to(root_path).as_posix(),
                    "reason": "symlink",
                })
            else:
                paths_list.append(child_path)
    return paths_list, skipped_list


def raise_walk_error_none(error: OSError) -> None:
    """Propagate a traversal error to the calling command.

    Args:
        error (OSError): Failure reported by directory traversal.
    Returns:
        None: Always raises the supplied error.
    Warnings:
        The command fails because its file selection is incomplete.
    """
    raise error
