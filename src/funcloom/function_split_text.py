"""Rewrite a module so long functions call short helpers, then verify it."""

import ast
from copy import deepcopy

from funcloom.function_blocks import plan_block_tuple
from funcloom.function_split import (
    SplitPlan, read_body_statements_tuple, compute_piece_contract_tuple,
    plan_label_str,
    plan_split_info, return_nodes_list, find_split_targets_list,
)
from funcloom.function_split import (
    classify_piece_kind_str, list_statement_nodes_list
)
from funcloom.modular_scan import split_program_lines_list
from funcloom.modular_text import dedent_lines_list, has_multiline_string_bool
from funcloom.modular_verify import find_undefined_names_set
from funcloom.snippet_render import escape_doc_lines_list
from funcloom.type_hints import (
    write_return_annotation_str, update_statement_types_none,
    list_trusted_names_set,
)

SPLIT_ROUNDS_INT = 4
SMALLEST_GAIN_LINES_INT = 10


def check_early_exit_bool(plan_info: SplitPlan, index_int: int) -> bool:
    """Tell whether a piece may return early for the whole function.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
    Returns:
        bool: True for a piece containing a return statement, unless it
            is the last piece of a whole function body.
    Warnings:
        The last piece's returns then pass straight through.
    """
    return (index_int < len(plan_info.pieces) - 1
            or not plan_info.terminal_bool) and bool(
        return_nodes_list(plan_info.pieces[index_int]))


def return_edits_list(node: ast.Return) -> list[tuple]:
    """Describe the text edits that turn one return into an early exit.

    Args:
        node (ast.Return): Return statement.
    Returns:
        list[tuple]: (line, start column, end column, new text) edits.
    Warnings:
        Columns are UTF-8 byte offsets, as in the syntax tree.
    """
    if node.value is None:
        return [(node.lineno, node.col_offset, node.end_col_offset,
                 "return True, None, None")]
    return [(node.value.end_lineno, node.value.end_col_offset,
             node.value.end_col_offset, "), None"),
            (node.value.lineno, node.value.col_offset,
             node.value.col_offset, "True, (")]


def exit_returns_lines_list(
    plan_info: SplitPlan, index_int: int, lines_list: list[str],
    outputs_list: list[str],
) -> list[str]:
    """Rewrite a piece's return statements to report an early exit.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        lines_list (list[str]): Module lines.
        outputs_list (list[str]): Names the piece normally returns.
    Returns:
        list[str]: The piece's lines with each `return X` written as
            `return True, (X), None...`.
    Warnings:
        Parentheses keep tuple returns such as `return a, b` intact.
    """
    piece_info = plan_info.pieces[index_int]
    first_int = piece_info.statements[0].first_line
    edited_list = list(lines_list[first_int - 1:
                                  piece_info.statements[-1].last_line])
    edits_list = [edit for node in return_nodes_list(piece_info)
                  for edit in return_edits_list(node)]
    for line_int, start_int, end_int, new_str in sorted(edits_list,
                                                        reverse=True):
        line_str = edited_list[line_int - first_int]
        raw_bytes = line_str.encode("utf-8")
        start_int = len(raw_bytes[:start_int].decode("utf-8"))
        end_int = len(raw_bytes[:end_int].decode("utf-8"))
        edited_list[line_int - first_int] = (line_str[:start_int] + new_str
                                             + line_str[end_int:])
    return edited_list


def collect_module_trusted_set(module_node: ast.Module) -> set[str]:
    """List builtins and classes that are safe for type inference.

    Args:
        module_node (ast.Module): Parsed module.
    Returns:
        set[str]: Names whose calls give a known type.
    Warnings:
        Any module-level rebinding of a builtin name removes it.
    """
    bound_set = {getattr(node, "id", None) or getattr(node, "name", None)
                 for statement_node in module_node.body
                 for node in ast.walk(statement_node)
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef,
                                      ast.alias))
                 or isinstance(node, ast.Name)
                 and not isinstance(node.ctx, ast.Load)} - {None}
    return list_trusted_names_set(bound_set, [
        node for node in module_node.body if isinstance(node, ast.ClassDef)])


def infer_piece_types_list(
        plan_info: SplitPlan, trusted_set: set) -> list[dict]:
    """Infer certain types for each piece's inputs and outputs.

    Args:
        plan_info (SplitPlan): Planned split.
        trusted_set (set): Builtins and classes safe for inference.
    Returns:
        list[dict]: Name-to-type mapping per piece.
    Warnings:
        Parameter annotations are reused as written unless the function
        rebinds them before or around a split block.
    """
    arguments_node = plan_info.node.args
    known_dict = {
        parameter_node.arg: ast.unparse(parameter_node.annotation)
        for parameter_node
        in [
            *arguments_node.posonlyargs, *arguments_node.args,
            *arguments_node.kwonlyargs]
        if parameter_node.annotation is not None
        and parameter_node.arg not in plan_info.unstable}
    types_list = []
    for piece_info in plan_info.pieces:
        start_dict, local_dict = dict(known_dict), dict(known_dict)
        for top_info in piece_info.statements:
            update_statement_types_none(top_info.node, local_dict, trusted_set,
                                        top_info.names.writes)
        types_list.append({"in": start_dict, "out": local_dict})
        known_dict = local_dict
    return types_list


def name_helpers_list(plan_info: SplitPlan, taken_set: set[str]) -> list[str]:
    """Name each piece's helper uniquely in the module.

    Args:
        plan_info (SplitPlan): Planned split.
        taken_set (set[str]): Identifiers already used in the module.
    Returns:
        list[str]: One name per piece, such as _load_part_1 or
            _load_loop_part_1 for a loop body.
    Warnings:
        Method helpers include the class name.
    """
    stem_str = plan_info.node.name.strip("_")
    if plan_info.class_node is not None:
        stem_str = f"{plan_info.class_node.name}_{stem_str}"
    if plan_info.infix:
        stem_str = f"{stem_str}_{plan_info.infix}"
    names_list = []
    for index_int in range(1, len(plan_info.pieces) + 1):
        base_str = candidate_str = f"_{stem_str}_part_{index_int}"
        counter_int = 2
        while candidate_str in taken_set:
            candidate_str = f"{base_str}_{counter_int}"
            counter_int += 1
        taken_set.add(candidate_str)
        names_list.append(candidate_str)
    return names_list


def call_line_list(
    targets_list: list[str], call_str: str, indent_int: int,
    width_int: int,
) -> list[str]:
    """Write one call statement, wrapped when it is too long.

    Args:
        targets_list (list[str]): Names receiving results, or ["return"].
        call_str (str): Call expression.
        indent_int (int): Statement indentation.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Indented lines.
    Warnings:
        Wrapping only adds parentheses and line breaks.
    """
    if targets_list == ["return"]:
        line_str = f"return {call_str}"
    elif targets_list:
        line_str = f"{', '.join(targets_list)} = {call_str}"
    else:
        line_str = call_str
    if indent_int + len(line_str) <= width_int:
        return [" " * indent_int + line_str]
    return wrap_call_lines_list(targets_list, call_str, indent_int,
                                width_int)


def wrap_call_lines_list(
    targets_list: list[str], call_str: str, indent_int: int,
    width_int: int,
) -> list[str]:
    """Lay out a too-long call statement with hanging indentation.

    Args:
        targets_list (list[str]): Names receiving results, or ["return"].
        call_str (str): Call expression, or a plain comma list of names.
        indent_int (int): Statement indentation.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Indented lines.
    Warnings:
        Several plain values are returned as a parenthesized tuple; a
        single target or value is never given a trailing comma.
    """
    pad_str = " " * indent_int
    if "(" not in call_str and targets_list == ["return"]:
        if ", " not in call_str:
            return [f"{pad_str}return {call_str}"]
        return ([f"{pad_str}return ("] + pack_names_list(
            call_str.split(", "), indent_int + 4, width_int)
            + [f"{pad_str})"])
    head_str, _, arguments_str = call_str.partition("(")
    arguments_list = [
        argument_str for argument_str in arguments_str.rstrip(")").split(", ")
        if argument_str]
    lines_list = []
    if targets_list == ["return"]:
        lines_list.append(f"{pad_str}return {head_str}(")
    elif len(targets_list) == 1:
        # One target: "(x,) = ..." would unpack a one-item tuple instead.
        if not arguments_str:
            return [f"{pad_str}{targets_list[0]} = {call_str}"]
        lines_list.append(f"{pad_str}{targets_list[0]} = {head_str}(")
    elif targets_list:
        lines_list += [f"{pad_str}("] + pack_names_list(
            targets_list, indent_int + 4, width_int)
        lines_list.append(f"{pad_str}) = {head_str}(" if arguments_str else
                          f"{pad_str}) = {call_str}")
        if not arguments_str:
            return lines_list
    else:
        lines_list.append(f"{pad_str}{head_str}(")
    return lines_list + pack_names_list(
        arguments_list, indent_int + 4, width_int) + [f"{pad_str})"]


def pack_names_list(
    names_list: list[str], indent_int: int, width_int: int,
) -> list[str]:
    """Pack comma-separated names onto as few lines as fit.

    Args:
        names_list (list[str]): Names in order.
        indent_int (int): Indentation of each line.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Lines, each ending with a comma.
    Warnings:
        Names are simple identifiers; nothing is re-tokenized.
    """
    lines_list, current_str = [], ""
    for name_str in names_list:
        candidate_str = f"{current_str} {name_str}," if current_str else (
            f"{name_str},")
        if current_str and indent_int + len(candidate_str) > width_int:
            lines_list.append(" " * indent_int + current_str)
            current_str = f"{name_str},"
        else:
            current_str = candidate_str
    return lines_list + ([" " * indent_int + current_str]
                         if current_str else [])


def write_helper_docstring_list(
    plan_info: SplitPlan, index_int: int, inputs_list: list[str],
    outputs_list: list[str], width_int: int,
) -> list[str]:
    """Write a helper docstring with Args, Returns and Warnings.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        inputs_list (list[str]): Helper parameters.
        outputs_list (list[str]): Returned names.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Docstring lines indented for a module function body.
    Warnings:
        Describes structure only; the original code has the meaning.
    """
    label_str = plan_label_str(plan_info)
    last_bool = index_int == len(plan_info.pieces) - 1
    returns_str = (f"The result of {label_str}." if last_bool
                   and plan_info.terminal_bool else
                   f"{', '.join(outputs_list)}: Values the rest of "
                   f"{label_str} uses." if outputs_list else
                   "None: Nothing is passed on.")
    entries_list = [("Args", [f"{input_str}: Local value of {label_str}."
                              for input_str in inputs_list] or ["None."]),
                    ("Returns", [returns_str]),
                    ("Warnings", ["Split out by FuncLoom to keep functions "
                                  "short; the statements are unchanged."])]
    lines_list = [f'    """Run part {index_int + 1} of {label_str}.', ""]
    for heading_str, texts_list in entries_list:
        lines_list.append(f"    {heading_str}:")
        for text_str in texts_list:
            wrapped_list = escape_doc_lines_list(text_str, width_int - 12)
            lines_list += ["        " + wrapped_list[0]] + [
                "            " + wrapped_line_str
                for wrapped_line_str in wrapped_list[1:]]
    return lines_list + ['    """']


def indent_piece_body_list(
    plan_info: SplitPlan, index_int: int, lines_list: list[str],
    outputs_list: list[str],
) -> list[str] | None:
    """Return a piece's original lines, indented for a module function.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        lines_list (list[str]): Module lines.
        outputs_list (list[str]): Names the piece returns.
    Returns:
        list[str] | None: Lines, or None when they cannot be dedented.
    Warnings:
        Early returns are rewritten to the exit protocol first.
    """
    piece_info = plan_info.pieces[index_int]
    body_list = lines_list[piece_info.statements[0].first_line - 1:
                           piece_info.statements[-1].last_line]
    if check_early_exit_bool(plan_info, index_int):
        body_list = exit_returns_lines_list(plan_info, index_int, lines_list,
                                            outputs_list)
    indent_int = plan_info.indent_int
    if indent_int == 4:
        return body_list
    if has_multiline_string_bool("\n".join(body_list) + "\n"):
        return None
    return dedent_lines_list(body_list, indent_int - 4)


def write_helper_lines_list(
    plan_info: SplitPlan, index_int: int, lines_list: list[str],
    width_int: int,
) -> list[str] | None:
    """Write one helper function, or None when its text cannot move.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        lines_list (list[str]): Module lines.
        width_int (int): Maximum line length.
    Returns:
        list[str] | None: Helper lines, starting with two blank lines.
    Warnings:
        Method bodies are dedented; multi-line strings then prevent it.
    """
    inputs_list, outputs_list, _ = compute_piece_contract_tuple(plan_info,
                                                                index_int)
    body_list = indent_piece_body_list(plan_info, index_int, lines_list,
                                       outputs_list)
    if body_list is None:
        return None
    header_list = write_helper_header_list(
        plan_info, index_int, (inputs_list, outputs_list), width_int)
    docstring_list = write_helper_docstring_list(
        plan_info, index_int, inputs_list, outputs_list, width_int)
    return_list = write_final_return_list(plan_info, index_int, outputs_list,
                                          width_int)
    return ["", ""] + header_list + docstring_list + body_list + return_list


def write_helper_header_list(
    plan_info: SplitPlan, index_int: int, contract_tuple: tuple,
    width_int: int,
) -> list[str]:
    """Write a helper's def line, one parameter per line when too long.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        contract_tuple (tuple): (input names, output names) of the piece.
        width_int (int): Maximum line length.
    Returns:
        list[str]: The def line or lines, ending with a colon.
    Warnings:
        Annotations appear only when their types are certain; awaiting
        pieces become coroutines and yielding pieces get no annotation.
    """
    inputs_list, outputs_list = contract_tuple
    name_str = plan_info.helper_names[index_int]
    types_dict = plan_info.piece_types[index_int] if (
        plan_info.piece_types) else {"in": {}, "out": {}}
    parameters_list = [
        f"{input_str}: {quote_annotation_str(types_dict['in'][input_str])}"
        if types_dict["in"].get(input_str) else input_str
        for input_str in inputs_list]
    result_str = write_helper_result_str(plan_info, index_int, outputs_list,
                                         types_dict["out"])
    if result_str:
        result_str = (" -> "
                      + quote_annotation_str(result_str.removeprefix(" -> ")))
    kind_str = classify_piece_kind_str(plan_info.pieces[index_int])
    def_str = "async def" if kind_str == "await" else "def"
    if kind_str == "yield":
        result_str = ""
    header_list = [f"{def_str} {name_str}({', '.join(parameters_list)})"
                   f"{result_str}:"]
    if len(header_list[0]) > width_int:
        header_list = (
            [f"{def_str} {name_str}("]
            + [f"    {parameter_str}," for parameter_str in parameters_list]
            + [f"){result_str}:"])
    return header_list


def quote_annotation_str(annotation_text_str: str) -> str:
    """Write an annotation as one string literal, never quoted twice.

    Args:
        annotation_text_str (str): Annotation source, possibly containing
            quoted forward references such as 'Box'.
    Returns:
        str: A single string literal, such as "tuple[list, Box]".
    Warnings:
        Text that is not a valid expression is quoted as written.
    """
    try:
        tree_node = ast.parse(annotation_text_str, mode="eval")
    except SyntaxError:
        return repr(annotation_text_str)
    for node in ast.walk(tree_node):
        for field_str, field_value in ast.iter_fields(node):
            if isinstance(field_value, ast.Constant) and isinstance(
                field_value.value, str,
            ):
                setattr(
                    node, field_str, ast.Name(field_value.value, ast.Load()))
            elif isinstance(field_value, list):
                setattr(node, field_str, [
                    ast.Name(element_node.value, ast.Load()) if isinstance(
                        element_node,
                        ast.Constant) and isinstance(element_node.value, str)
                    else element_node for element_node in field_value])
    body_node = tree_node.body
    if isinstance(body_node, ast.Constant) and isinstance(
        body_node.value, str,
    ):
        return repr(body_node.value)
    return repr(ast.unparse(tree_node))


def write_helper_result_str(
    plan_info: SplitPlan, index_int: int, outputs_list: list[str],
    out_types_dict: dict,
) -> str:
    """Write a helper's return annotation when it is certain.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        outputs_list (list[str]): Returned names.
        out_types_dict (dict): Types after the piece.
    Returns:
        str: Annotation text, or empty.
    Warnings:
        The last helper reuses the function's own return annotation;
        early-exit helpers stay unannotated.
    """
    if index_int == len(plan_info.pieces) - 1 and plan_info.terminal_bool:
        returns_node = plan_info.node.returns
        return f" -> {ast.unparse(returns_node)}" if returns_node else ""
    if check_early_exit_bool(plan_info, index_int):
        return ""
    return write_return_annotation_str(outputs_list, out_types_dict)


def write_final_return_list(
    plan_info: SplitPlan, index_int: int, outputs_list: list[str],
    width_int: int,
) -> list[str]:
    """Write a helper's closing return statement, if it needs one.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        outputs_list (list[str]): Names later pieces need.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Return lines, or nothing for the last piece.
    Warnings:
        Early-exit pieces return (False, None, values) when they finish.
    """
    if check_early_exit_bool(plan_info, index_int):
        parts_str = ("None" if not outputs_list else outputs_list[0]
                     if len(outputs_list) == 1 else
                     f"({', '.join(outputs_list)})")
        return call_line_list(["return"], f"False, None, {parts_str}", 4,
                              width_int)
    if outputs_list and (index_int < len(plan_info.pieces) - 1
                         or not plan_info.terminal_bool):
        return call_line_list(["return"], ", ".join(outputs_list), 4,
                              width_int)
    return []


def write_calls_lines_list(plan_info: SplitPlan, width_int: int) -> list[str]:
    """Write the new body of the split function: one call per piece.

    Args:
        plan_info (SplitPlan): Planned split with helper names.
        width_int (int): Maximum line length.
    Returns:
        list[str]: Indented call statements.
    Warnings:
        For a whole body the last call is returned, so the function's
        result is unchanged; a block's last call assigns its outputs.
    """
    indent_int = plan_info.indent_int
    last_int = len(plan_info.helper_names) - 1 if (
        plan_info.terminal_bool) else -1
    lines_list: list[str] = []
    for index_int, name_str in enumerate(plan_info.helper_names):
        inputs_list, outputs_list, _ = compute_piece_contract_tuple(plan_info,
                                                                    index_int)
        kind_str = classify_piece_kind_str(plan_info.pieces[index_int])
        prefix_str = {"yield": "yield from ", "await": "await "}.get(
            kind_str, "")
        call_str = f"{prefix_str}{name_str}({', '.join(inputs_list)})"
        last_bool = index_int == last_int
        if last_bool and kind_str == "yield":
            value_str = plan_info.exit_names[1]
            lines_list += call_line_list([value_str], call_str, indent_int,
                                         width_int)
            lines_list.append(" " * indent_int + f"return {value_str}")
            continue
        if check_early_exit_bool(plan_info, index_int):
            flag_str, value_str = plan_info.exit_names
            parts_str = f"{value_str}_parts"
            lines_list += call_line_list(
                [flag_str, value_str, parts_str], call_str, indent_int,
                width_int)
            lines_list += [" " * indent_int + f"if {flag_str}:",
                           " " * (indent_int + 4) + f"return {value_str}"]
            if outputs_list:
                lines_list += call_line_list(outputs_list, parts_str,
                                             indent_int, width_int)
            continue
        lines_list += call_line_list(
            ["return"] if last_bool else outputs_list, call_str, indent_int,
            width_int)
    return lines_list


def split_functions_text_tuple(
    source_str: str, width_int: int, max_lines_int: int,
) -> tuple[str, list[str], list[str]]:
    """Split every long function of a module that can be split safely.

    Args:
        source_str (str): Module text.
        width_int (int): Maximum line length.
        max_lines_int (int): Functions longer than this are split.
    Returns:
        tuple: New text, notes, and names of split functions.
    Warnings:
        When verification fails, the original text is returned unchanged.
    """
    names_list: list[str] = []
    notes_list: list[str] = []
    for _ in range(SPLIT_ROUNDS_INT):
        new_str, notes_list, round_list = split_round_tuple(
            source_str, width_int, max_lines_int)
        if not round_list:
            break
        source_str = new_str
        names_list += round_list
    return source_str, notes_list, names_list


def round_plans_list(
    module_node: ast.Module, lines_list: list[str], max_lines_int: int,
    notes_list: list[str],
) -> list[SplitPlan]:
    """Plan one split for every long function that allows it.

    Args:
        module_node (ast.Module): Parsed module.
        lines_list (list[str]): Module lines.
        max_lines_int (int): Functions longer than this are split.
        notes_list (list[str]): Destination for skip reasons.
    Returns:
        list[SplitPlan]: Whole-body splits, or else long-block splits.
    Warnings:
        A function whose statements cannot be cut, or whose cut would
        leave a piece still too long, splits its longest block instead.
    """
    plans_list = []
    for node, class_node in find_split_targets_list(
            module_node, max_lines_int):
        own_notes_list: list[str] = []
        plan_info = plan_split_info(node, class_node, own_notes_list)
        sizes_list = [piece_info.statements[-1].last_line
                      - piece_info.statements[0].first_line + 1
                      for piece_info in (plan_info.pieces if plan_info
                                         else [])]
        if plan_info is None or max(sizes_list) > max_lines_int:
            block_info, reason_str = plan_block_tuple(node, class_node,
                                                      lines_list)
            if block_info is None and plan_info is not None and sum(
                sizes_list) - max(sizes_list) < SMALLEST_GAIN_LINES_INT:
                own_notes_list.append(
                    f"{plan_label_str(plan_info)} was not split: one "
                    "statement makes it long and cannot be split.")
                plan_info = None
            plan_info = block_info or plan_info
            if plan_info is None:
                notes_list += [
                    own_note_str[:-1] + f"; {reason_str}." if reason_str
                    else own_note_str for own_note_str in own_notes_list]
        if plan_info is not None:
            plans_list.append(plan_info)
    return plans_list


def split_round_tuple(
    source_str: str, width_int: int, max_lines_int: int,
) -> tuple[str, list[str], list[str]]:
    """Split each long function once, then verify the new module.

    Args:
        source_str (str): Module text.
        width_int (int): Maximum line length.
        max_lines_int (int): Functions longer than this are split.
    Returns:
        tuple: New text, notes, and labels of the split regions.
    Warnings:
        When verification fails, the text is returned unchanged.
    """
    try:
        module_node = ast.parse(source_str)
    except SyntaxError:
        return source_str, [], []
    notes_list: list[str] = []
    plans_list = round_plans_list(
        module_node, split_program_lines_list(source_str), max_lines_int,
        notes_list)
    if not plans_list:
        return source_str, notes_list, []
    taken_set = {getattr(node, "id", None) or getattr(node, "name", None)
                 for node in ast.walk(module_node)} - {None}
    trusted_set = collect_module_trusted_set(module_node)
    for plan_info in plans_list:
        plan_info.helper_names = name_helpers_list(plan_info, taken_set)
        plan_info.exit_names = choose_unique_pair_tuple(taken_set)
        plan_info.piece_types = infer_piece_types_list(
            plan_info, trusted_set - plan_info.locals)
    new_str = apply_plans_str(source_str, plans_list, width_int, notes_list)
    if new_str is None or not verify_helper_statements_bool(
            source_str, new_str, plans_list):
        notes_list.append("Splitting was not applied: the result did not "
                          "verify.")
        return source_str, notes_list, []
    return new_str, notes_list, [plan_label_str(plan)
                                 for plan in plans_list]


def apply_plans_str(
    source_str: str, plans_list: list[SplitPlan], width_int: int,
    notes_list: list[str],
) -> str | None:
    """Replace function bodies with calls and insert the helpers.

    Args:
        source_str (str): Module text.
        plans_list (list[SplitPlan]): Planned splits with helper names.
        width_int (int): Maximum line length.
        notes_list (list[str]): Destination for problems.
    Returns:
        str | None: New text, or None when a helper cannot be written.
    Warnings:
        Edits are applied from the bottom so line numbers stay valid.
    """
    lines_list = split_program_lines_list(source_str)
    edits_list = []
    for plan_info in plans_list:
        plan_edits_list = plan_helper_edits_list(plan_info, lines_list,
                                                 width_int)
        if plan_edits_list is None:
            notes_list.append(f"{plan_label_str(plan_info)} was not "
                              "split: its text could not be re-indented.")
            return None
        edits_list += plan_edits_list
    for end_int, kind_int, start_int, new_list in sorted(
            edits_list, key=lambda edit_tuple: (edit_tuple[0], edit_tuple[1]),
            reverse=True):
        if kind_int == 1:
            lines_list[end_int:end_int] = new_list
        else:
            lines_list[start_int:end_int] = new_list
    return "\n".join(lines_list) + "\n"


def plan_helper_edits_list(
    plan_info: SplitPlan, lines_list: list[str], width_int: int,
) -> list[tuple] | None:
    """Prepare the helper insertion and body replacement of one split.

    Args:
        plan_info (SplitPlan): Planned split with helper names.
        lines_list (list[str]): Module lines.
        width_int (int): Maximum line length.
    Returns:
        list[tuple] | None: (end line, kind, start line, new lines) edits,
            kind 1 inserting helpers and 0 replacing the body; None when
            a helper cannot be written.
    Warnings:
        Helpers go above the owning definition and its decorators,
        before any comments attached to it.
    """
    helpers_list = [write_helper_lines_list(plan_info, index_int, lines_list,
                                            width_int)
                    for index_int in range(len(plan_info.pieces))]
    if any(helper_lines_list is None for helper_lines_list in helpers_list):
        return None
    anchor_node = plan_info.class_node or plan_info.node
    top_int = min([anchor_node.lineno] + [
        decorator_node.lineno
        for decorator_node in anchor_node.decorator_list])
    first_int = find_attached_comments_start_int(lines_list, top_int - 1,
                                                 anchor_node.col_offset)
    helper_text_list = [line_str for helper_lines_list in helpers_list
                        for line_str in helper_lines_list] + ["", ""]
    return [(first_int, 1, first_int, helper_text_list),
            (plan_info.end_int, 0, plan_info.header_int,
             write_calls_lines_list(plan_info, width_int))]


def find_attached_comments_start_int(
    lines_list: list[str], first_int: int, column_int: int,
) -> int:
    """Move an insertion point above comments that describe a definition.

    Args:
        lines_list (list[str]): Module lines.
        first_int (int): Zero-based index of the definition's first line.
        column_int (int): The definition's indentation.
    Returns:
        int: Index above the comment lines directly preceding it.
    Warnings:
        Shebang and encoding lines are never moved below inserted code.
    """
    while first_int > 0:
        line_str = lines_list[first_int - 1]
        stripped_str = line_str.lstrip()
        if not stripped_str.startswith("#") or (
            len(line_str) - len(stripped_str) != column_int
        ) or stripped_str.startswith("#!") or (
            first_int <= 2 and "coding" in stripped_str
        ):
            break
        first_int -= 1
    return first_int


def choose_unique_pair_tuple(taken_set: set[str]) -> tuple[str, str]:
    """Choose unused names for the early-exit flag and value.

    Args:
        taken_set (set[str]): Identifiers already used.
    Returns:
        tuple[str, str]: Flag and value names.
    Warnings:
        Adds the names to taken_set.
    """
    counter_int, suffix_str = 1, ""
    while f"exit_bool{suffix_str}" in taken_set or (
        f"exit_value{suffix_str}" in taken_set
    ):
        counter_int += 1
        suffix_str = f"_{counter_int}"
    pair_tuple = (f"exit_bool{suffix_str}", f"exit_value{suffix_str}")
    taken_set.update(pair_tuple)
    return pair_tuple


def build_expected_piece_list(
    plan_info: SplitPlan, index_int: int, outputs_list: list[str],
) -> list[ast.stmt]:
    """Return a piece's original statements as its helper should hold them.

    Args:
        plan_info (SplitPlan): Planned split.
        index_int (int): Zero-based piece index.
        outputs_list (list[str]): Names the piece returns.
    Returns:
        list[ast.stmt]: Copies with early returns rewritten to the
            exit protocol, when the piece exits early.
    Warnings:
        Used only for verification.
    """
    statements_list = [deepcopy(top_info.node)
                       for top_info in plan_info.pieces[index_int].statements]
    if not check_early_exit_bool(plan_info, index_int):
        return statements_list
    padding_list = [ast.Constant(None)]
    for statement_node in statements_list:
        for node in list_statement_nodes_list(statement_node):
            if isinstance(node, ast.Return):
                node.value = ast.Tuple([ast.Constant(True), node.value
                                        or ast.Constant(None),
                                        *padding_list], ast.Load())
    return statements_list


def build_canonical_nodes_tuple(
    plan_info: SplitPlan,
) -> tuple[list[ast.stmt], list[ast.stmt]]:
    """Build the intended calls and helper returns without any wrapping.

    Args:
        plan_info (SplitPlan): Applied split.
    Returns:
        tuple: Expected body of the split function, and the expected final
            return of each non-last helper (None when it has none).
    Warnings:
        Compared with the generated text to catch layout mistakes.
    """
    indent_int = plan_info.indent_int
    body_list = ast.parse("\n".join(
        line_str[indent_int:]
        for line_str in write_calls_lines_list(plan_info, 10 ** 9))).body
    returns_list = []
    for index_int in range(len(plan_info.pieces) - (
            1 if plan_info.terminal_bool else 0)):
        _, outputs_list, _ = compute_piece_contract_tuple(plan_info,
                                                            index_int)
        if check_early_exit_bool(plan_info, index_int):
            parts_str = ("None" if not outputs_list else outputs_list[0]
                         if len(outputs_list) == 1 else
                         f"({', '.join(outputs_list)})")
            value_str = f"False, None, {parts_str}"
        else:
            value_str = ", ".join(outputs_list)
        returns_list.append(ast.parse(f"return {value_str}").body[0]
                            if value_str else None)
    return body_list, returns_list


def check_generated_body_bool(
    plan_info: SplitPlan, new_tree: ast.Module,
    helpers_dict: dict[str, ast.FunctionDef],
) -> bool:
    """Check the rewritten function body and each helper's final return.

    Args:
        plan_info (SplitPlan): Applied split.
        new_tree (ast.Module): Split module.
        helpers_dict (dict): Helper functions by name.
    Returns:
        bool: True when generated lines match their canonical form.
    Warnings:
        Early-exit checks are compared as part of the body.
    """
    expected_body_list, returns_list = build_canonical_nodes_tuple(plan_info)
    owner_list = new_tree.body if plan_info.class_node is None else next(
        (node.body for node in new_tree.body if isinstance(node, ast.ClassDef)
         and node.name == plan_info.class_node.name), [])
    if not any(check_region_matches_bool(plan_info, node, expected_body_list)
               for node in owner_list if isinstance(
                   node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == plan_info.node.name):
        return False
    for name_str, expected_node in zip(plan_info.helper_names, returns_list):
        last_node = helpers_dict[name_str].body[-1]
        if expected_node is not None and ast.dump(last_node) != ast.dump(
            expected_node,
        ):
            return False
    return True


def dump_split_nodes_list(nodes_list: list[ast.AST]) -> list[str]:
    """Dump syntax nodes for a structural comparison.

    Args:
        nodes_list (list[ast.AST]): Nodes to compare.
    Returns:
        list[str]: One dump per node.
    Warnings:
        Line and column positions are left out of the dumps.
    """
    return [ast.dump(compared_node) for compared_node in nodes_list]


def check_region_matches_bool(
    plan_info: SplitPlan, function_node: ast.FunctionDef,
    expected_list: list[ast.stmt],
) -> bool:
    """Check one rewritten function against the intended calls.

    Args:
        plan_info (SplitPlan): Applied split.
        function_node (ast.FunctionDef): Candidate rewritten function.
        expected_list (list[ast.stmt]): Intended calls.
    Returns:
        bool: True when the split region holds exactly the calls and,
            for a block, the rest of the function is unchanged.
    Warnings:
        Line positions are ignored; structure is compared.
    """
    if plan_info.terminal_bool:
        return dump_split_nodes_list(
            read_body_statements_tuple(function_node)[0]) == (
            dump_split_nodes_list(expected_list))
    old_list, new_list = plan_info.node.body, function_node.body
    index_int, field_str = plan_info.owner_index, plan_info.block_field
    if len(new_list) != len(old_list) or type(new_list[index_int]) is not (
        type(old_list[index_int])
    ):
        return False
    old_copy, new_copy = deepcopy(old_list[index_int]), deepcopy(
        new_list[index_int])
    new_block_list = getattr(new_copy, field_str)
    setattr(old_copy, field_str, [])
    setattr(new_copy, field_str, [])
    return dump_split_nodes_list(new_block_list) == dump_split_nodes_list(
        expected_list) and (
        dump_split_nodes_list(old_list[:index_int] + old_list[index_int + 1:])
        + dump_split_nodes_list([old_copy])
        == dump_split_nodes_list(
            new_list[:index_int] + new_list[index_int + 1:])
        + dump_split_nodes_list([new_copy]))


def verify_helper_statements_bool(
    old_str: str, new_str: str, plans_list: list[SplitPlan],
) -> bool:
    """Check that helpers contain exactly the original statements.

    Args:
        old_str (str): Original module text.
        new_str (str): Split module text.
        plans_list (list[SplitPlan]): Applied splits.
    Returns:
        bool: True when the text compiles, every body is preserved in
            order and no new undefined names appear.
    Warnings:
        Structural equality is evidence, not a proof of equal behavior.
    """
    try:
        compile(new_str, "<split>", "exec", dont_inherit=True)
    except SyntaxError:
        return False
    old_tree, new_tree = ast.parse(old_str), ast.parse(new_str)
    helpers_dict = {node.name: node for node in new_tree.body
                    if isinstance(node, (ast.FunctionDef,
                                         ast.AsyncFunctionDef))}
    for plan_info in plans_list:
        if any(name_str not in helpers_dict
               for name_str in plan_info.helper_names):
            return False
        if not check_pieces_kept_bool(plan_info, helpers_dict) or not (
            check_generated_body_bool(plan_info, new_tree, helpers_dict)
        ) or not check_nested_scopes_kept_bool(plan_info, helpers_dict):
            return False
    return find_undefined_names_set(new_tree) <= find_undefined_names_set(
        old_tree)


def check_nested_scopes_kept_bool(
    plan_info: SplitPlan, helpers_dict: dict[str, ast.FunctionDef],
) -> bool:
    """Check that nested functions, classes and lambdas move unchanged.

    Args:
        plan_info (SplitPlan): Applied split.
        helpers_dict (dict): Helper functions by name.
    Returns:
        bool: True when every nested scope in the helpers equals the one
            in the original statements, in the same order.
    Warnings:
        Independent of the early-exit rewrite, so a rewrite that reaches
        into a nested function is caught here.
    """
    original_list = dump_nested_scopes_list([top_info.node
                                 for piece_info in plan_info.pieces
                                 for top_info in piece_info.statements])
    helper_list = dump_nested_scopes_list([statement_node
                               for name_str in plan_info.helper_names
                               for statement_node in
                               helpers_dict[name_str].body])
    return original_list == helper_list


def check_pieces_kept_bool(
    plan_info: SplitPlan, helpers_dict: dict[str, ast.FunctionDef],
) -> bool:
    """Check that the helpers hold exactly the original body statements.

    Args:
        plan_info (SplitPlan): Applied split.
        helpers_dict (dict): Helper functions by name.
    Returns:
        bool: True when statements match in order, allowing only the
            early-exit rewrite of returns.
    Warnings:
        The helpers' docstrings and final returns are excluded here.
    """
    gathered_list, expected_list = [], []
    for index_int, name_str in enumerate(plan_info.helper_names):
        helper_node = helpers_dict[name_str]
        _, outputs_list, _ = compute_piece_contract_tuple(plan_info,
                                                            index_int)
        last_bool = index_int == len(plan_info.helper_names) - 1 and (
            plan_info.terminal_bool)
        trim_int = 0 if last_bool or not (
            outputs_list or check_early_exit_bool(plan_info, index_int)) else 1
        gathered_list += helper_node.body[1:len(helper_node.body) - trim_int]
        expected_list += build_expected_piece_list(plan_info, index_int,
                                                   outputs_list)
    return [ast.dump(gathered_node) for gathered_node in gathered_list] == [
        ast.dump(expected_node) for expected_node in expected_list]


def dump_nested_scopes_list(roots_list: list[ast.AST]) -> list[str]:
    """Dump nested scopes under the supplied statement roots in order.

    Args:
        roots_list (list[ast.AST]): Statements whose descendants are read.
    Returns:
        list[str]: Structural dumps of functions, classes and lambdas.
    Warnings:
        AST equality alone does not prove runtime equivalence.
    """
    return [ast.dump(node) for root_node in roots_list
            for node in ast.walk(root_node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Lambda))]
