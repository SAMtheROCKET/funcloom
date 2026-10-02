"""Token-preserving local name proposals with independent syntax checks."""

import ast
from copy import deepcopy
from dataclasses import replace
from io import StringIO
import tokenize

from funcloom.config import RuleProfile
from funcloom.plan_preview import (
    render_caller_preview_str, return_statement_str, validate_preview_none,
)
from funcloom.snippet_models import SnippetReport
from funcloom.snippet_wrapping import wrap_assignments_str
from funcloom.snippet_render import (
    render_proposed_docstring_str, render_proposed_signature_str,
)


def rename_source_tokens_str(
        source_str: str, names_dict: dict[str, str]) -> str:
    """Replace identifier tokens while preserving comments and string text.

    Args:
        source_str (str): Exact selected source fragment.
        names_dict (dict): Validated one-to-one local name proposals.
    Returns:
        str: New preview text; original input is unchanged.
    Warnings:
        Only the already accepted single-name expression subset is supported.
    """
    lines_list = StringIO(source_str, newline="").readlines()
    offsets_list = [0]
    for line_str in lines_list:
        offsets_list.append(offsets_list[-1] + len(line_str))
    edits_list = []
    for token_info in list_renamable_tokens_list(source_str):
        if token_info.string in names_dict:
            start_int = (
                offsets_list[token_info.start[0] - 1] + token_info.start[1]
            )
            end_int = (
                offsets_list[token_info.end[0] - 1] + token_info.end[1]
            )
            edits_list.append((start_int, end_int,
                               names_dict[token_info.string]))
    for start_int, end_int, replacement_str in reversed(edits_list):
        source_str = (
            source_str[:start_int] + replacement_str + source_str[end_int:]
        )
    return source_str


def list_renamable_tokens_list(source_str: str) -> list[tokenize.TokenInfo]:
    """List name tokens that refer to variables, not attributes or keywords.

    Args:
        source_str (str): Selected source fragment.
    Returns:
        list[tokenize.TokenInfo]: Variable name tokens in source order.
    Warnings:
        Attribute names after '.' and keyword-argument names before '='
        inside brackets are never renamed.
    """
    ignored_set = {tokenize.NL, tokenize.COMMENT}
    tokens_list = [token_info for token_info in tokenize.generate_tokens(
        StringIO(source_str, newline="").readline,
    ) if token_info.type not in ignored_set]
    names_list, depth_int = [], 0
    for index_int, scanned_token in enumerate(tokens_list):
        depth_int += (scanned_token.string in ("(", "[", "{")) - (
            scanned_token.string in (")", "]", "}")
        )
        previous_str = tokens_list[index_int - 1].string if index_int else ""
        next_str = (tokens_list[index_int + 1].string
                    if index_int + 1 < len(tokens_list) else "")
        if (scanned_token.type == tokenize.NAME and previous_str != "."
                and not (depth_int > 0 and next_str == "=")):
            names_list.append(scanned_token)
    return names_list


def prepare_renamed_statements_list(
    module_node: ast.Module, start_int: int, names_dict: dict[str, str],
) -> list[ast.stmt]:
    """Prepare expected ASTs for checking local identifier substitution.

    Args:
        module_node (ast.Module): Original validated snippet.
        start_int (int): First selected physical line.
        names_dict (dict): Validated rename mapping.
    Returns:
        list[ast.stmt]: Copied statements with only Name identifiers changed.
    Warnings:
        Structural matching is evidence, not proof of relocation equivalence.
    """
    statements_list = deepcopy([
        node for node in module_node.body if node.lineno >= start_int
    ])
    for statement_node in statements_list:
        for node in ast.walk(statement_node):
            if isinstance(node, ast.Name):
                node.id = names_dict.get(node.id, node.id)
    return statements_list


def build_snippet_preview_none(
    module_node: ast.Module, report_info: SnippetReport,
    profile_info: RuleProfile,
) -> None:
    """Build typed local drafts and validate syntax, structure and size.

    Args:
        module_node (ast.Module): Accepted original syntax.
        report_info (SnippetReport): Context and value proposals.
        profile_info (RuleProfile): Hard width and function size limits.
    Returns:
        None: Stores previews only after every draft validation succeeds.
    Warnings:
        Caller bindings retain their original names; apply remains disabled.
    """
    plan_info = report_info.plan
    names_dict = {value_info.original_name: value_info.proposed_name
                  for value_info in report_info.values}
    fragment_str = wrap_assignments_str(
        rename_source_tokens_str(plan_info.source_fragment, names_dict),
        profile_info.line_length,
    )
    body_str = "".join("    " + line_str for line_str in
                       StringIO(fragment_str, newline=""))
    if not body_str.endswith(("\n", "\r")):
        body_str += "\n"
    renamed_plan = replace(
        plan_info,
        outputs=[
            replace(output_info, name=names_dict[output_info.name])
            for output_info in plan_info.outputs])
    function_str = (
        render_proposed_signature_str(report_info)
        + render_proposed_docstring_str(report_info, profile_info.line_length)
        + body_str + return_statement_str(renamed_plan)
    )
    caller_str = render_caller_preview_str(plan_info)
    validate_snippet_preview_none(
        function_str, caller_str, prepare_renamed_statements_list(
            module_node, plan_info.start_line, names_dict,
        ), profile_info,
    )
    report_info.function_preview = function_str
    report_info.caller_preview = caller_str
    report_info.preview_compiles = True
    report_info.status = "candidate_for_review"


def validate_snippet_preview_none(
    function_str: str, caller_str: str, statements_list: list[ast.stmt],
    profile_info: RuleProfile,
) -> None:
    """Require syntax, renamed-statement structure and configured hard caps.

    Args:
        function_str (str): Contextual function proposal.
        caller_str (str): Caller retaining original external names.
        statements_list (list): Independently renamed expected statements.
        profile_info (RuleProfile): Width and physical function size caps.
    Returns:
        None: Raises ValueError or SyntaxError for failed validation.
    Warnings:
        Passing these checks is not a behavioral equivalence proof.
    """
    validate_preview_none(function_str, caller_str, statements_list)
    length_int = len(function_str.splitlines())
    if length_int > profile_info.function_max_lines:
        raise ValueError(
            f"Contextual draft has {length_int} function lines; the cap is "
            f"{profile_info.function_max_lines}"
        )
    for line_str in (function_str + caller_str).splitlines():
        if len(line_str) > profile_info.line_length:
            raise ValueError(
                f"Draft line has {len(line_str)} characters; the cap is "
                f"{profile_info.line_length}: {line_str.strip()[:40]}"
            )
