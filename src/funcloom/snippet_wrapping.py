"""Reflow long assignment drafts while retaining expression token content."""

import ast
from io import StringIO
import keyword
import re
import textwrap
import tokenize

OPENING_BRACKETS_TUPLE = ("(", "[", "{")
CLOSING_TOKENS_TUPLE = (")", "]", "}", ",")
DIRECTIVE_PATTERN = re.compile(
    r"#\s*(?:type\s*:|noqa\b|pragma\b|pylint\s*:|mypy\s*:|pyright\s*:|"
    r"pyre-|fmt\s*:|isort\s*:|ruff\s*:|nosec\b|flake8\s*[:-]|pytype\s*:|"
    r"pyrefly\s*:|ty\s*:)",
    re.IGNORECASE,
)


class WrappingRefusal(ValueError):
    """A located reason why a draft line cannot be wrapped safely."""

    def __init__(self, fragment_line_int: int, message_str: str) -> None:
        """Record the fragment line (one-based) and the reason.

        Args:
            fragment_line_int (int): Line within the selected fragment.
            message_str (str): Explanation shown to the user.
        Returns:
            None: Initializes the exception.
        Warnings:
            Callers convert the line to an original source line.
        """
        super().__init__(message_str)
        self.fragment_line_int = fragment_line_int


def wrap_assignments_str(source_str: str, width_int: int) -> str:
    """Wrap oversized statements and comments without editing the source.

    Args:
        source_str (str): Locally renamed, accepted assignment fragment.
        width_int (int): Final function line limit including indentation.
    Returns:
        str: Preview fragment with long assignments parenthesized.
    Warnings:
        Whitespace in wrapped statements changes; token content is retained.
    """
    lines_list = StringIO(source_str, newline="").readlines()
    statements_dict = {
        node.lineno - 1: node for node in ast.parse(source_str).body
    }
    output_list, index_int = [], 0
    while index_int < len(lines_list):
        node = statements_dict.get(index_int)
        end_int = node.end_lineno if node is not None else index_int + 1
        span_list = lines_list[index_int:end_int]
        if not check_fits_width_bool(span_list, width_int):
            refuse_directive_none(span_list, index_int + 1)
        try:
            output_list.append(wrap_span_str(span_list, node, width_int))
        except WrappingRefusal as error:
            raise WrappingRefusal(index_int + error.fragment_line_int,
                                   str(error)) from error
        index_int = end_int
    return "".join(output_list)


def wrap_span_str(
    span_list: list[str], node: ast.stmt | None, width_int: int,
) -> str:
    """Wrap one statement span or standalone comment line only if too long.

    Args:
        span_list (list[str]): Physical lines with their line endings.
        node (ast.stmt | None): Statement starting here, or None.
        width_int (int): Final function line limit including indentation.
    Returns:
        str: Unchanged lines, or a wrapped replacement.
    Warnings:
        Only assignments and comment lines can be wrapped.
    """
    if check_fits_width_bool(span_list, width_int):
        return "".join(span_list)
    if node is None:
        return wrap_comment_line_str(span_list[0], width_int)
    if not isinstance(node, (ast.Assign, ast.AugAssign, ast.Expr)):
        raise ValueError("Only simple statements can be line-wrapped")
    return wrap_statement_str("".join(span_list), width_int)


def check_fits_width_bool(span_list: list[str], width_int: int) -> bool:
    """Check whether lines fit once indented into the function body.

    Args:
        span_list (list[str]): Physical lines with endings.
        width_int (int): Final function line limit.
    Returns:
        bool: True when every line fits after four-space indentation.
    Warnings:
        Counts characters, not terminal display columns.
    """
    return all(len(line_str.rstrip("\r\n")) + 4 <= width_int
               for line_str in span_list)


def refuse_directive_none(span_list: list[str], first_line_int: int) -> None:
    """Refuse to wrap lines whose comments are tool directives.

    Args:
        span_list (list[str]): Too-long statement or comment lines.
        first_line_int (int): Fragment line number of span_list[0].
    Returns:
        None: Raises WrappingRefusal when a directive is present.
    Warnings:
        Directives such as type: ignore or noqa apply to their physical
        line, so moving or splitting them would change their meaning.
    """
    text_str = "".join(span_list)
    for token_info in tokenize.generate_tokens(
        StringIO(text_str, newline="").readline,
    ):
        match_info = (DIRECTIVE_PATTERN.search(token_info.string)
                      if token_info.type == tokenize.COMMENT else None)
        if match_info is not None:
            line_int = first_line_int + token_info.start[0] - 1
            raise WrappingRefusal(line_int, (
                f"Line carries tool directive {token_info.string[:40]!r}; "
                "wrapping would split or move it. Shorten the line or "
                "choose a larger line length."
            ))


def read_line_ending_str(line_str: str) -> str:
    """Return a physical line's ending so wrapped lines keep its style.

    Args:
        line_str (str): Source text ending in CRLF, CR, LF or nothing.
    Returns:
        str: The same ending, or LF when the text has none.
    Warnings:
        Mixed endings inside one statement use the last line's ending.
    """
    for ending_str in ("\r\n", "\r", "\n"):
        if line_str.endswith(ending_str):
            return ending_str
    return "\n"


def wrap_comment_list(comment_str: str, width_int: int) -> list[str]:
    """Split one comment into several comments that fit the given width.

    Args:
        comment_str (str): Comment token text beginning with '#'.
        width_int (int): Available characters for each comment line.
    Returns:
        list[str]: Comment lines keeping every word in its original order.
    Warnings:
        Spacing inside the comment is normalized; a single word longer
        than the width stays whole and is refused later by width checks.
    """
    text_str = comment_str.lstrip("#").strip()
    pieces_list = textwrap.wrap(
        text_str, width=max(width_int - 2, 1), break_long_words=False,
        break_on_hyphens=False,
    )
    comments_list = ["# " + piece_str for piece_str in pieces_list] or ["#"]
    if any(
            DIRECTIVE_PATTERN.search(comment_str)
            for comment_str in comments_list):
        raise WrappingRefusal(1, "Wrapping this prose would create a tool "
                              "directive; shorten the comment or choose "
                              "a larger line length.")
    return comments_list


def wrap_comment_line_str(line_str: str, width_int: int) -> str:
    """Wrap a standalone comment line, keeping its indentation and ending.

    Args:
        line_str (str): Physical line containing only a comment.
        width_int (int): Final function line limit including indentation.
    Returns:
        str: One or more comment lines.
    Warnings:
        Raises ValueError for a long line that is not a comment.
    """
    body_str = line_str.rstrip("\r\n")
    text_str = body_str.lstrip()
    if not text_str.startswith("#"):
        raise ValueError("Cannot wrap this source line")
    indent_str = body_str[:len(body_str) - len(text_str)]
    ending_str = read_line_ending_str(line_str)
    return "".join(
        indent_str + comment_str + ending_str for comment_str in
        wrap_comment_list(text_str, width_int - 4 - len(indent_str))
    )


def wrap_statement_str(
    statement_str: str, width_int: int, indent_int: int = 4,
) -> str:
    """Render one name assignment with its original RHS tokens inside brackets.

    Args:
        statement_str (str): Whole supported assignment including comments.
        width_int (int): Final source width including outer indentation.
        indent_int (int): Indentation the statement will finally have.
    Returns:
        str: Parenthesized assignment with a newline after each comment.
    Warnings:
        Indivisible long tokens still cause a width refusal.
    """
    ignored_set = {tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER}
    tokens_list = merge_fstring_tokens_list([
        token_info for token_info in tokenize.generate_tokens(
            StringIO(statement_str, newline="").readline,
        ) if token_info.type not in ignored_set], statement_str)
    split_int = find_assignment_split_int(tokens_list)
    if split_int == 0 and tokens_list and tokens_list[0].string == "return":
        split_int = 1
    if split_int >= len(tokens_list):
        raise ValueError("Cannot wrap this statement token structure")
    head_list = pack_tokens_list(tokens_list[:split_int - 1], 1_000_000)
    if len(head_list) > 1:
        raise ValueError("Cannot wrap a statement with a comment before '='")
    head_str = (" ".join(filter(None, [
        "".join(head_list), tokens_list[split_int - 1].string]))
        if split_int else "")
    newline_str = read_line_ending_str(statement_str)
    lines_list = [f"{head_str} (" if head_str else "("]
    lines_list.extend("    " + line_str for line_str in pack_tokens_list(
        tokens_list[split_int:], width_int - indent_int - 4,
    ))
    lines_list.append(")")
    return newline_str.join(lines_list) + newline_str


def merge_fstring_tokens_list(
    tokens_list: list[tokenize.TokenInfo], statement_str: str,
) -> list[tokenize.TokenInfo]:
    """Turn each f-string's token pieces back into one string token.

    Args:
        tokens_list (list[tokenize.TokenInfo]): Tokens of one statement.
        statement_str (str): The statement's text.
    Returns:
        list[tokenize.TokenInfo]: Tokens where every f-string, including
            nested ones, is a single STRING token with its exact text.
    Warnings:
        Since Python 3.12 f-strings are split into several tokens;
        re-joining those pieces with spaces would change the string. A
        multi-line f-string raises ValueError and is not wrapped.
    """
    start_type = getattr(tokenize, "FSTRING_START", None)
    end_type = getattr(tokenize, "FSTRING_END", None)
    lines_list = statement_str.splitlines(keepends=True)
    merged_list, depth_int, first_info = [], 0, None
    for token_info in tokens_list:
        if start_type is not None and token_info.type == start_type:
            depth_int += 1
            first_info = first_info or token_info
        if depth_int == 0:
            merged_list.append(token_info)
        elif token_info.type == end_type:
            depth_int -= 1
            if depth_int == 0:
                if first_info.start[0] != token_info.end[0]:
                    raise ValueError("Cannot wrap a multi-line f-string")
                text_str = lines_list[first_info.start[0] - 1][
                    first_info.start[1]:token_info.end[1]]
                merged_list.append(tokenize.TokenInfo(
                    tokenize.STRING, text_str, first_info.start,
                    token_info.end, first_info.line))
                first_info = None
    return merged_list


def find_assignment_split_int(tokens_list: list[tokenize.TokenInfo]) -> int:
    """Find where the wrapped right-hand side starts.

    Args:
        tokens_list (list): Significant tokens of one simple statement.
    Returns:
        int: Index after the last top-level assignment operator, or 0 for
            an expression statement.
    Warnings:
        Parenthesizing the remainder must leave the syntax tree unchanged;
        the caller's AST comparison verifies that.
    """
    depth_int, split_int = 0, 0
    for index_int, scanned_token in enumerate(tokens_list):
        if scanned_token.string in OPENING_BRACKETS_TUPLE:
            depth_int += 1
        elif scanned_token.string in CLOSING_TOKENS_TUPLE[:3]:
            depth_int -= 1
        elif depth_int == 0 and scanned_token.type == tokenize.OP and (
            scanned_token.string.endswith("=")
            and scanned_token.string not in ("==", "<=", ">=", "!=")
        ):
            split_int = index_int + 1
    return split_int


def is_attached_bool(
    previous_info: tokenize.TokenInfo, token_info: tokenize.TokenInfo,
    depth_int: int,
) -> bool:
    """Decide whether two adjacent tokens are written without a space.

    Args:
        previous_info (tokenize.TokenInfo): Token already on the line.
        token_info (tokenize.TokenInfo): Next token.
        depth_int (int): Bracket depth before token_info.
    Returns:
        bool: True for brackets, commas, attribute dots, call/subscript
            brackets and keyword-argument equals signs.
    Warnings:
        A dot after a number keeps its space: 1.real would re-tokenize.
    """
    previous_str, token_str = previous_info.string, token_info.string
    callable_bool = previous_str in (")", "]") or previous_info.type in (
        tokenize.STRING,
    ) or (previous_info.type == tokenize.NAME
          and not keyword.iskeyword(previous_str))
    return (
        previous_str in OPENING_BRACKETS_TUPLE
        or token_str in CLOSING_TOKENS_TUPLE
        or ("=" in (previous_str, token_str) and depth_int > 0)
        or previous_str == "."
        or (token_str == "." and previous_info.type != tokenize.NUMBER)
        or (token_str in ("(", "[") and callable_bool)
    )


def finish_comment_lines_list(
    current_str: str, comment_str: str, width_int: int,
) -> list[str]:
    """Finish a packed line with a comment, splitting a long comment.

    Args:
        current_str (str): Code already on the line, possibly empty.
        comment_str (str): Comment token text.
        width_int (int): Available characters per line.
    Returns:
        list[str]: One or more complete lines.
    Warnings:
        Directive comments never reach this point; they are refused first.
    """
    candidate_str = (f"{current_str}  {comment_str}" if current_str
                     else comment_str)
    if len(candidate_str) <= width_int:
        return [candidate_str]
    return [*filter(None, [current_str]),
            *wrap_comment_list(comment_str, width_int)]


def pack_tokens_list(
    tokens_list: list[tokenize.TokenInfo], width_int: int,
) -> list[str]:
    """Pack whole expression tokens without changing their order or content.

    Args:
        tokens_list (list): RHS tokens, including comments and delimiters.
        width_int (int): Available width after both indentation levels.
    Returns:
        list[str]: Expression lines; long comments are split into lines.
    Warnings:
        Later AST comparison and hard caps must validate the full draft.
    """
    lines_list, current_str, previous_info, depth_int = [], "", None, 0
    for token_info in tokens_list:
        if token_info.type == tokenize.COMMENT:
            try:
                lines_list.extend(finish_comment_lines_list(current_str,
                                                            token_info.string,
                                                            width_int))
            except WrappingRefusal as error:
                raise WrappingRefusal(
                    token_info.start[0], str(error)) from error
            current_str = ""
            continue
        separator_str = "" if not current_str or (
            previous_info is not None
            and is_attached_bool(previous_info, token_info, depth_int)
        ) else " "
        depth_int += (token_info.string in OPENING_BRACKETS_TUPLE) - (
            token_info.string in CLOSING_TOKENS_TUPLE[:3]
        )
        candidate_str = current_str + separator_str + token_info.string
        if current_str and len(candidate_str) > width_int:
            lines_list.append(current_str)
            current_str = token_info.string
        else:
            current_str = candidate_str
        previous_info = token_info
    if current_str:
        lines_list.append(current_str)
    return lines_list
