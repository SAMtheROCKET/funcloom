"""Load the deliberately small configuration supported in milestone one."""

from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
import tomllib

DEFAULT_EXCLUDED_DIRS_TUPLE = (
    ".git", ".hg", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".nox", "node_modules",
    "build", "dist",
)
LINE_LENGTH_LIMITS_TUPLE = (40, 200)


@dataclass(frozen=True)
class RuleProfile:
    """Supported rule settings; the larger design profile is future work."""

    name: str = "domain_explicit_m1"
    line_length: int = 79
    function_target_lines: int = 40
    function_max_lines: int = 50
    orchestrator_max_lines: int = 100
    main_guard_max_lines: int = 100
    max_file_bytes: int = 2_000_000
    main_function_names: tuple[str, ...] = ("main",)
    excluded_dirs: tuple[str, ...] = DEFAULT_EXCLUDED_DIRS_TUPLE
    doc_sections: tuple[str, ...] = ("Args", "Returns", "Warnings")


def validate_profile_none(profile: RuleProfile) -> None:
    """Validate configuration without silently coercing invalid values.

    Args:
        profile (RuleProfile): Settings to validate.
    Returns:
        None: The original instance is not changed.
    Raises:
        ValueError: A field or relationship is invalid.
    Warnings:
        This validates settings, not source-code behavior.
    """
    for field_info in fields(profile):
        field_value = getattr(profile, field_info.name)
        if field_info.name == "name":
            valid_bool = isinstance(field_value, str) and bool(field_value)
        elif field_info.name in {
            "main_function_names", "excluded_dirs", "doc_sections",
        }:
            valid_bool = isinstance(field_value, tuple) and all(
                isinstance(item_str, str) and bool(item_str)
                for item_str in field_value
            )
        else:
            valid_bool = type(field_value) is int and field_value > 0
        if not valid_bool:
            raise ValueError(f"Invalid profile value: {field_info.name}")
    validate_line_length_none(profile.line_length)
    if profile.function_target_lines > profile.function_max_lines:
        raise ValueError("function_target_lines exceeds function_max_lines")
    allowed_sections_set = {"Args", "Returns", "Warnings"}
    if not set(profile.doc_sections) <= allowed_sections_set:
        raise ValueError("doc_sections accepts Args, Returns, Warnings only")


def apply_line_length_profile(
    profile: RuleProfile, line_length_int: int,
) -> RuleProfile:
    """Apply a user-chosen maximum source line length to a rule profile.

    Args:
        profile (RuleProfile): Validated settings to copy.
        line_length_int (int): Requested maximum characters per line.
    Returns:
        RuleProfile: A copy using the requested line length.
    Raises:
        ValueError: The value is not a whole number within the limits.
    Warnings:
        Applies to reports and drafts only; source files are not rewritten.
    """
    validate_line_length_none(line_length_int)
    return replace(profile, line_length=line_length_int)


def validate_line_length_none(line_length_int: int) -> None:
    """Apply the one line-length rule shared by every entry point.

    Args:
        line_length_int (int): Maximum characters per line.
    Returns:
        None: Raises ValueError outside LINE_LENGTH_LIMITS_TUPLE.
    Warnings:
        Booleans and floats are rejected rather than coerced.
    """
    minimum_int, maximum_int = LINE_LENGTH_LIMITS_TUPLE
    if type(line_length_int) is not int or not (
        minimum_int <= line_length_int <= maximum_int
    ):
        raise ValueError(
            f"Line length must be a whole number from {minimum_int} "
            f"to {maximum_int}"
        )


def load_profile(config_path: Path | None = None) -> RuleProfile:
    """Load an explicit TOML profile or the built-in defaults.

    Args:
        config_path (Path | None): A file containing a [profile] table.
    Returns:
        RuleProfile: Validated settings.
    Raises:
        ValueError: Configuration keys or values are invalid.
    Warnings:
        No parent-directory or executable configuration is loaded.
    """
    profile_dict = asdict(RuleProfile())
    if config_path is not None:
        document_dict = tomllib.loads(config_path.read_text("utf-8"))
        if set(document_dict) != {"profile"}:
            raise ValueError("Configuration must contain only [profile]")
        supplied_dict = document_dict["profile"]
        if not isinstance(supplied_dict, dict):
            raise ValueError("profile must be a TOML table")
        unknown_set = set(supplied_dict) - set(profile_dict)
        if unknown_set:
            raise ValueError(f"Unknown profile keys: {sorted(unknown_set)}")
        for field_name, field_value in supplied_dict.items():
            if isinstance(profile_dict[field_name], tuple):
                if not isinstance(field_value, list):
                    raise ValueError(f"{field_name} must be an array")
                field_value = tuple(field_value)
            profile_dict[field_name] = field_value
    profile = RuleProfile(**profile_dict)
    validate_profile_none(profile)
    return profile
