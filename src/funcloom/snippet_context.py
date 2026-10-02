"""Strict, non-executable context for snippet proposals."""

from dataclasses import fields
import keyword
from pathlib import Path
import tomllib
import unicodedata

from funcloom.config import RuleProfile, apply_line_length_profile
from funcloom.plan_selection import validate_request_none
from funcloom.snippet_models import SnippetContext

CONTEXT_MAX_BYTES_INT = 64_000
TEXT_MAX_CHARACTERS_INT = 2_000
INPUT_TYPES_TUPLE = ("int", "float")


def validate_context_none(context_info: SnippetContext) -> None:
    """Validate context without interpreting prose as code or type evidence.

    Args:
        context_info (SnippetContext): Explicit user preferences.
    Returns:
        None: Raises ValueError for unknown or unsafe settings.
    Warnings:
        Supported input type declarations are unverified int or float only.
    """
    if not isinstance(context_info, SnippetContext):
        raise ValueError("Context must be a SnippetContext")
    if context_info.naming_mode not in ("source", "domain", "mathematical"):
        raise ValueError("naming_mode must be source, domain or mathematical")
    for name_str in ("project_context", "summary", "function_name"):
        validate_text_none(getattr(context_info, name_str))
    if context_info.function_name:
        validate_request_none(1, 1, context_info.function_name)
    if context_info.literal_policy not in ("parameters", "fixed"):
        raise ValueError("literal_policy must be parameters or fixed")
    if context_info.line_length is not None:
        apply_line_length_profile(RuleProfile(), context_info.line_length)
    for name_str in ("input_types", "descriptions", "names"):
        mapping_dict = getattr(context_info, name_str)
        if not isinstance(mapping_dict, dict):
            raise ValueError(f"{name_str} must be a table")
        for key_str, value_str in mapping_dict.items():
            validate_identifier_none(key_str, f"{name_str} key")
            validate_text_none(value_str)
            if name_str == "input_types" and (
                value_str not in INPUT_TYPES_TUPLE
            ):
                raise ValueError("Input types must be int or float")
            if name_str == "names":
                validate_identifier_none(
                    value_str, f"names value for {key_str!r}",
                )


def validate_identifier_none(name_str: str, label_str: str) -> None:
    """Require a usable local variable identifier in a context mapping.

    Args:
        name_str (str): Proposed or referenced variable identifier.
        label_str (str): Where the identifier appeared, for the message.
    Returns:
        None: Raises ValueError naming the invalid entry.
    Warnings:
        Soft keywords such as match remain valid identifiers.
    """
    if (
        not isinstance(name_str, str) or not name_str.isidentifier()
        or keyword.iskeyword(name_str)
        or unicodedata.normalize("NFKC", name_str) != name_str
    ):
        raise ValueError(
            f"{label_str} {name_str!r} must be a valid, normalized "
            "Python variable name that is not a keyword"
        )


def validate_text_none(value_str: str) -> None:
    """Bound context strings and reject embedded control characters.

    Args:
        value_str (str): User-authored context or description.
    Returns:
        None: Raises ValueError for invalid content.
    Warnings:
        Quotes and backslashes are allowed and escaped when rendered.
    """
    if not isinstance(value_str, str) or (
        len(value_str) > TEXT_MAX_CHARACTERS_INT
    ):
        raise ValueError("Context text must be a string of at most 2000 chars")
    if any(ord(character_str) < 32 and character_str not in "\n\t"
           for character_str in value_str):
        raise ValueError("Context contains unsupported control characters")


def load_snippet_context(context_path: str | Path) -> SnippetContext:
    """Read a bounded TOML context file without executing configuration.

    Args:
        context_path (str | Path): Explicit context file path.
    Returns:
        SnippetContext: Validated project text and structured preferences.
    Warnings:
        Prose is retained as user intent, not used to infer business rules.
    """
    with Path(context_path).open("rb") as context_file:
        raw_bytes = context_file.read(CONTEXT_MAX_BYTES_INT + 1)
    if len(raw_bytes) > CONTEXT_MAX_BYTES_INT:
        raise ValueError("Context file exceeds 64000 bytes")
    data_dict = tomllib.loads(raw_bytes.decode("utf-8-sig"))
    allowed_set = {"snippet", "input_types", "descriptions", "names"}
    if set(data_dict) - allowed_set:
        raise ValueError("Unknown context table")
    settings_dict = data_dict.get("snippet", {})
    allowed_fields_set = {
        field_info.name for field_info in fields(SnippetContext)}
    if not isinstance(settings_dict, dict) or (
        set(settings_dict) - (allowed_fields_set - allowed_set)
    ):
        raise ValueError("Unknown snippet setting")
    context_info = SnippetContext(**settings_dict, **{
        key_str: data_dict[key_str]
        for key_str in allowed_set - {"snippet"} if key_str in data_dict
    })
    validate_context_none(context_info)
    return context_info
