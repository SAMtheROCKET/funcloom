"""Render original top-level statements as text for generated modules."""

import ast
from copy import deepcopy
from io import StringIO
import re
import tokenize

from funcloom.modular_models import TopStatement
from funcloom.snippet_wrapping import DIRECTIVE_PATTERN
from funcloom.snippet_wrapping import wrap_statement_str

WRAPPABLE_TUPLE = (ast.Assign, ast.AugAssign, ast.Expr)


def rename_constants_node(
        node: ast.stmt, renames_dict: dict[str, str]) -> ast.stmt:
    """Copy a statement with constant names replaced.

    Args:
        node (ast.stmt): Original statement.
        renames_dict (dict[str, str]): Old name to new name.
    Returns:
        ast.stmt: Renamed copy; the original tree is unchanged.
    Warnings:
        Only Name nodes change; attributes and keywords keep their text.
    """
    copy_node = deepcopy(node)
    for inner_node in ast.walk(copy_node):
        if isinstance(inner_node, ast.Name) and inner_node.id in renames_dict:
            inner_node.id = renames_dict[inner_node.id]
    return copy_node


def find_code_start_int(top_info: TopStatement) -> int:
    """Return the first line of code, after any attached comments.

    Args:
        top_info (TopStatement): Located statement.
    Returns:
        int: First decorator or statement line.
    Warnings:
        Lines before it in the range are comment lines.
    """
    return min(
        [top_info.node.lineno]
        + [
            decorator_node.lineno
            for decorator_node in getattr(top_info.node, "decorator_list", [])]
    )


def rename_lines_list(
    top_info: TopStatement, lines_list: list[str],
    renames_dict: dict[str, str],
) -> list[str]:
    """Return a statement's original lines with renames applied in place.

    Args:
        top_info (TopStatement): Located statement.
        lines_list (list[str]): Program lines without endings.
        renames_dict (dict[str, str]): Old name to new name.
    Returns:
        list[str]: Edited copies of the statement's lines.
    Warnings:
        AST columns are UTF-8 byte offsets and are converted per line.
    """
    selected_list = list(lines_list[top_info.first_line - 1:
                                    top_info.last_line])
    edits_list = sorted((
        (inner_node.lineno, inner_node.col_offset, inner_node.end_col_offset,
         renames_dict[inner_node.id])
        for inner_node in ast.walk(top_info.node)
        if isinstance(inner_node, ast.Name) and renames_dict.get(
            inner_node.id, inner_node.id) != inner_node.id
    ), reverse=True)
    for line_int, start_int, end_int, new_str in edits_list:
        index_int = line_int - top_info.first_line
        line_str = selected_list[index_int]
        raw_bytes = line_str.encode("utf-8")
        start_int = len(raw_bytes[:start_int].decode("utf-8"))
        end_int = len(raw_bytes[:end_int].decode("utf-8"))
        selected_list[index_int] = (line_str[:start_int] + new_str
                                    + line_str[end_int:])
    return selected_list


def dedent_lines_list(
    lines_list: list[str], indent_int: int,
    kept_set: set[int] | None = None,
) -> list[str] | None:
    """Remove a fixed indentation from every non-blank line.

    Args:
        lines_list (list[str]): Statement lines.
        indent_int (int): Spaces to remove.
        kept_set (set[int] | None): One-based lines inside multi-line
            strings; they are kept exactly as written.
    Returns:
        list[str] | None: Dedented lines, or None if a line has less.
    Warnings:
        Continuation lines with less indentation need regeneration.
    """
    prefix_str = " " * indent_int
    result_list = []
    for number_int, line_str in enumerate(lines_list, 1):
        if kept_set and number_int in kept_set:
            result_list.append(line_str)
        elif not line_str.strip():
            result_list.append("")
        elif line_str.startswith(prefix_str):
            result_list.append(line_str[indent_int:])
        else:
            return None
    return result_list


def has_multiline_string_bool(text_str: str) -> bool:
    """Detect string tokens that span lines and cannot be re-indented.

    Args:
        text_str (str): Statement text at column zero.
    Returns:
        bool: True when indenting would change a string's content, or when
            the text cannot be tokenized.
    Warnings:
        Such statements are regenerated from their syntax tree instead.
    """
    try:
        return any(
            token_info.start[0] != token_info.end[0]
            for token_info in tokenize.generate_tokens(
                StringIO(text_str).readline)
            if token_info.type in (tokenize.STRING, tokenize.FSTRING_MIDDLE)
        )
    except (tokenize.TokenError, SyntaxError):
        return True


def find_string_interior_lines_set(text_str: str) -> set[int] | None:
    """Find lines that lie inside multi-line string literals.

    Args:
        text_str (str): Python statement text.
    Returns:
        set[int] | None: One-based line numbers after the first line of
            each multi-line string, or None when the text cannot be
            tokenized.
    Warnings:
        Changing the indentation of these lines would change the string.
    """
    lines_set: set[int] = set()
    try:
        for token_info in tokenize.generate_tokens(
            StringIO(text_str).readline,
        ):
            if token_info.type in (tokenize.STRING,
                                   tokenize.FSTRING_MIDDLE):
                lines_set.update(range(token_info.start[0] + 1,
                                       token_info.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        return None
    return lines_set


def indent_lines_list(text_str: str, prefix_str: str) -> list[str]:
    """Indent statement text, leaving multi-line string contents alone.

    Args:
        text_str (str): Statement text at column zero.
        prefix_str (str): Indentation to add.
    Returns:
        list[str]: Lines; blank lines outside strings stay empty.
    Warnings:
        String contents keep their original columns, so the value of
        every string, including docstrings, is unchanged.
    """
    kept_set = find_string_interior_lines_set(text_str) or set()
    return [line_str if number_int in kept_set
            else (prefix_str + line_str if line_str else "")
            for number_int, line_str in enumerate(text_str.splitlines(), 1)]


def render_statement_text_tuple(
    top_info: TopStatement, lines_list: list[str],
    renames_dict: dict[str, str], reindent_bool: bool,
) -> tuple[str, bool]:
    """Render a statement at column zero, keeping comments where possible.

    Args:
        top_info (TopStatement): Located statement.
        lines_list (list[str]): Program lines without endings.
        renames_dict (dict[str, str]): Old name to new name.
        reindent_bool (bool): Whether the text will be indented again.
    Returns:
        tuple[str, bool]: Text ending in a newline, and whether it was
            regenerated from the syntax tree.
    Warnings:
        Regenerated statements lose comments inside the statement; text
        is regenerated only when it cannot be tokenized or dedented.
        Lines inside multi-line strings are never re-indented, here or
        by indent_lines_list, so reindent_bool no longer matters.
    """
    edited_list = rename_lines_list(top_info, lines_list, renames_dict)
    kept_set = find_string_interior_lines_set("\n".join(edited_list) + "\n")
    dedented_list = None if kept_set is None else dedent_lines_list(
        edited_list, top_info.indent, kept_set)
    if dedented_list is not None:
        return "\n".join(dedented_list) + "\n", False
    comment_count_int = find_code_start_int(top_info) - top_info.first_line
    comments_list = [line_str.strip()
                     for line_str in edited_list[:comment_count_int]]
    unparsed_str = ast.unparse(
        rename_constants_node(top_info.node, renames_dict))
    return "\n".join([*comments_list, unparsed_str]) + "\n", True


def convert_char_column_int(line_str: str, byte_column_int: int) -> int:
    """Convert an AST byte column into a character index for one line.

    Args:
        line_str (str): Source line.
        byte_column_int (int): Zero-based UTF-8 byte offset.
    Returns:
        int: Zero-based character offset.
    Warnings:
        Assumes the offset falls on a character boundary, as AST offsets do.
    """
    return len(line_str.encode("utf-8")[:byte_column_int].decode("utf-8"))


def is_alone_on_lines_bool(node: ast.stmt, lines_list: list[str]) -> bool:
    """Check that no other statement shares a statement's first or last line.

    Args:
        node (ast.stmt): Simple statement.
        lines_list (list[str]): Text lines.
    Returns:
        bool: True when only indentation precedes it and at most a comment
            follows it.
    Warnings:
        Semicolon-separated statements are never wrapped.
    """
    first_str = lines_list[node.lineno - 1]
    last_str = lines_list[node.end_lineno - 1]
    before_str = first_str[
        :convert_char_column_int(first_str, node.col_offset)]
    after_str = last_str[
        convert_char_column_int(last_str, node.end_col_offset):]
    return before_str.strip() == "" and "\t" not in before_str and (
        after_str.strip() == "" or after_str.strip().startswith("#"))


def wrap_node_lines_list(
    node: ast.stmt, lines_list: list[str], base_int: int, width_int: int,
) -> list[str] | None:
    """Wrap one too-long simple statement, or explain why not with None.

    Args:
        node (ast.stmt): Assignment, expression or return statement.
        lines_list (list[str]): Text lines.
        base_int (int): Indentation the whole text will receive.
        width_int (int): Maximum final line length.
    Returns:
        list[str] | None: Replacement lines, or None when not wrappable.
    Warnings:
        The caller must verify the result's syntax tree.
    """
    indent_int = node.col_offset
    span_list = lines_list[node.lineno - 1:node.end_lineno]
    prefix_str = " " * indent_int
    if not is_alone_on_lines_bool(node, lines_list) or not all(
        line_str.startswith(prefix_str) or not line_str.strip()
        for line_str in span_list
    ):
        return None
    statement_str = "\n".join(line_str[indent_int:]
                              for line_str in span_list) + "\n"
    if has_multiline_string_bool(statement_str) or DIRECTIVE_PATTERN.search(
        statement_str,
    ):
        return None
    try:
        wrapped_str = wrap_statement_str(statement_str, width_int,
                                         base_int + indent_int)
    except (ValueError, tokenize.TokenError, SyntaxError):
        return None
    return [prefix_str + line_str for line_str in wrapped_str.splitlines()]


def wrap_long_statements_tuple(
    text_str: str, base_int: int, width_int: int, label_str: str,
) -> tuple[str, list[str]]:
    """Wrap every too-long simple statement, at any nesting depth.

    Args:
        text_str (str): Column-zero statement text.
        base_int (int): Indentation the whole text will receive.
        width_int (int): Maximum final line length.
        label_str (str): Where the text comes from, for notes.
    Returns:
        tuple: Possibly wrapped text and notes about lines left long.
    Warnings:
        Compound headers, long tokens, directives and multi-line strings
        stay as written.
    """
    lines_list = split_program_text_list(text_str)
    if all(len(line_str) + base_int <= width_int for line_str in lines_list):
        return text_str, []
    try:
        tree_node = ast.parse(text_str)
    except SyntaxError:
        return text_str, [f"{label_str}: long lines were not wrapped."]
    nodes_list = sorted((node for node in ast.walk(tree_node) if isinstance(
        node, (*WRAPPABLE_TUPLE, ast.Return))), key=lambda node: -node.lineno)
    for node in nodes_list:
        span_list = lines_list[node.lineno - 1:node.end_lineno]
        if all(
                len(line_str) + base_int <= width_int for line_str in span_list
        ):
            continue
        replacement_list = wrap_node_lines_list(node, lines_list,
                                                base_int, width_int)
        if replacement_list is not None:
            lines_list[node.lineno - 1:node.end_lineno] = replacement_list
    long_int = sum(1 for line_str in lines_list
                   if len(line_str) + base_int > width_int)
    notes_list = [f"{label_str}: {long_int} line(s) stay longer than "
                  f"{width_int} characters."] if long_int else []
    return "\n".join(lines_list) + "\n", notes_list


def split_program_text_list(text_str: str) -> list[str]:
    """Split text into physical lines without splitting inside strings.

    Args:
        text_str (str): Program text.
    Returns:
        list[str]: Lines without endings.
    Warnings:
        Separators such as U+2028 stay inside their line.
    """
    lines_list = re.split(r"\r\n|\r|\n", text_str)
    if lines_list and lines_list[-1] == "":
        lines_list.pop()
    return lines_list
