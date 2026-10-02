"""Split long functions and methods into short, documented helpers."""

import ast
from dataclasses import dataclass, field

from funcloom.modular_models import StepPlan, TopStatement
from funcloom.modular_scan import collect_statement_names_info
from funcloom.modular_steps import (
    block_bind_set, collect_may_deletes_set, merge_steps_none,
    collect_must_binds_set,
    step_facts_tuple,
)
from funcloom.plan_bindings import DYNAMIC_NAMESPACE_NAMES_TUPLE

PIECE_TARGET_LINES_INT = 25
FUNCTIONS_TUPLE = (ast.FunctionDef, ast.AsyncFunctionDef)
NESTED_SCOPES_TUPLE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                       ast.Lambda)


REGION_LABELS_DICT = {"loop": "loop body", "if": "if body",
                      "else": "else body", "with": "with body"}


@dataclass
class SplitPlan:
    """One function body, or one block inside it, to split into helpers.

    `owner_index` is -1 for the whole body; otherwise it is the index of
    the loop, if or with statement in the function body whose
    `block_field` block is split. Name sets describe the region: names
    maybe bound before it, certainly bound before it, read after it,
    local to the function, and with types not stable across the region.
    """

    node: ast.FunctionDef
    class_node: ast.ClassDef | None
    parameters: set[str]
    pieces: list[StepPlan] = field(default_factory=list)
    helper_names: list[str] = field(default_factory=list)
    exit_names: tuple[str, str] = ("exit_bool", "exit_value")
    piece_types: list[dict] = field(default_factory=list)
    before: set[str] = field(default_factory=set)
    certain: set[str] = field(default_factory=set)
    after_reads: set[str] = field(default_factory=set)
    locals: set[str] = field(default_factory=set)
    unstable: set[str] = field(default_factory=set)
    loop_bool: bool = False
    header_int: int = 0
    end_int: int = 0
    indent_int: int = 4
    owner_index: int = -1
    block_field: str = "body"
    infix: str = ""

    @property
    def terminal_bool(self) -> bool:
        """Tell whether the region is the whole function body.

        Args:
            None: Reads the plan's owner index.
        Returns:
            bool: True when the last piece's result is the function's.
        Warnings:
            A block's pieces return values instead of the result.
        """
        return self.owner_index < 0


def plan_label_str(plan_info: SplitPlan) -> str:
    """Name a planned split for notes and reports.

    Args:
        plan_info (SplitPlan): Planned split.
    Returns:
        str: Such as "load", "Report.build" or "load (loop body)".
    Warnings:
        Used for display only.
    """
    label_str = plan_info.node.name if plan_info.class_node is None else (
        f"{plan_info.class_node.name}.{plan_info.node.name}")
    if plan_info.infix:
        label_str += f" ({REGION_LABELS_DICT[plan_info.infix]})"
    return label_str


def collect_parameter_names_set(node: ast.FunctionDef) -> set[str]:
    """Return a function's parameter names.

    Args:
        node (ast.FunctionDef): Function.
    Returns:
        set[str]: Positional, keyword and star parameter names.
    Warnings:
        Annotations and defaults are not included.
    """
    arguments_node = node.args
    return {parameter_node.arg for parameter_node in [
        *arguments_node.posonlyargs, *arguments_node.args,
        *arguments_node.kwonlyargs, arguments_node.vararg,
        arguments_node.kwarg] if parameter_node is not None}


def classify_piece_kind_str(piece_info: StepPlan) -> str:
    """Tell whether a piece suspends with yield or await.

    Args:
        piece_info (StepPlan): Piece of a function body.
    Returns:
        str: "yield", "await" or "" for ordinary code.
    Warnings:
        A yielding piece becomes a generator called with yield from; an
        awaiting piece becomes a coroutine called with await.
    """
    nodes_list = [
        statement_part_node for top_info in piece_info.statements
        for statement_part_node in list_statement_nodes_list(top_info.node)]
    if any(isinstance(statement_part_node, (ast.Yield, ast.YieldFrom))
           for statement_part_node in nodes_list):
        return "yield"
    if any(
            isinstance(
                statement_part_node, (ast.Await, ast.AsyncFor, ast.AsyncWith))
            for statement_part_node in nodes_list):
        return "await"
    return ""


def return_nodes_list(piece_info: StepPlan) -> list[ast.Return]:
    """List return statements a piece runs itself.

    Args:
        piece_info (StepPlan): Piece of a function body.
    Returns:
        list[ast.Return]: Returns outside nested functions and lambdas.
    Warnings:
        Returns of nested functions belong to those functions.
    """
    return [statement_part_node for top_info in piece_info.statements
            for statement_part_node in list_statement_nodes_list(top_info.node)
            if isinstance(statement_part_node, ast.Return)]


def list_statement_nodes_list(node: ast.stmt) -> list[ast.AST]:
    """List nodes a statement runs in the enclosing function's scope.

    Args:
        node (ast.stmt): Statement of a function body or piece.
    Returns:
        list[ast.AST]: The statement and its own nodes; for a nested
            def or class only its decorators, defaults and bases.
    Warnings:
        A nested function's return and yield belong to that function,
        so they must never be rewritten or counted for the piece.
    """
    if not isinstance(node, NESTED_SCOPES_TUPLE):
        return [node, *own_nodes_list(node)]
    roots_list = list(getattr(node, "decorator_list", []))
    if isinstance(node, ast.ClassDef):
        roots_list += [*node.bases, *node.keywords]
    else:
        roots_list += [*node.args.defaults, *filter(
            None, node.args.kw_defaults)]
    return [scope_node for root_node in roots_list
            for scope_node in [root_node, *own_nodes_list(root_node)]]


def own_nodes_list(node: ast.AST) -> list[ast.AST]:
    """List nodes of a function body outside nested scopes.

    Args:
        node (ast.AST): Statement or function.
    Returns:
        list[ast.AST]: Nodes that execute in the function's own scope.
    Warnings:
        Nested functions, lambdas and classes are not entered.
    """
    result_list, pending_list = [], list(ast.iter_child_nodes(node))
    while pending_list:
        current_node = pending_list.pop()
        result_list.append(current_node)
        if not isinstance(current_node, NESTED_SCOPES_TUPLE):
            pending_list.extend(ast.iter_child_nodes(current_node))
    return result_list


def skip_reason_str(
    node: ast.FunctionDef, class_node: ast.ClassDef | None,
) -> str | None:
    """Explain why a function must not be split, or return None.

    Args:
        node (ast.FunctionDef): Candidate function.
        class_node (ast.ClassDef | None): Owning class for methods.
    Returns:
        str | None: Reason to leave it unchanged.
    Warnings:
        Generators and coroutines are split with yield from and await;
        async generators, frame and class tricks keep the function whole.
    """
    for inner_node in own_nodes_list(node):
        if isinstance(inner_node, (ast.Yield, ast.YieldFrom)) and isinstance(
            node, ast.AsyncFunctionDef,
        ):
            return "it is an async generator"
        if isinstance(inner_node, (ast.Global, ast.Nonlocal)):
            return "it declares global or nonlocal names"
    for inner_node in ast.walk(node):
        name_str = getattr(inner_node, "id", None) or getattr(
            inner_node, "attr", "")
        if isinstance(inner_node, ast.Name) and name_str in (
            *DYNAMIC_NAMESPACE_NAMES_TUPLE, "super", "__class__",
        ):
            return f"it uses {name_str}"
        if isinstance(inner_node, ast.Nonlocal):
            return "a nested function uses nonlocal"
        if class_node is not None and name_str.startswith("__") and (
            not name_str.endswith("__")
        ):
            return f"it uses the private name {name_str}"
    if any(
            current_node.lineno == previous.end_lineno
            for previous, current_node in zip(node.body, node.body[1:])):
        return "statements share a line"
    return None


def read_body_statements_tuple(
    node: ast.FunctionDef,
) -> tuple[list[ast.stmt], int]:
    """Return the body statements after any docstring, and the last line
    that stays in the function header.

    Args:
        node (ast.FunctionDef): Function.
    Returns:
        tuple: Statements, and the header's last line.
    Warnings:
        Comments between the header and the first statement stay above
        the generated calls.
    """
    body_list = list(node.body)
    header_int = body_list[0].lineno - 1
    if isinstance(body_list[0], ast.Expr) and isinstance(
        body_list[0].value, ast.Constant,
    ) and isinstance(body_list[0].value.value, str):
        header_int = body_list[0].end_lineno
        body_list = body_list[1:]
    return body_list, header_int


def cut_initial_pieces_list(
    statements_list: list[ast.stmt], header_int: int,
) -> list[StepPlan]:
    """Cut body statements into pieces of about the target length.

    Args:
        statements_list (list[ast.stmt]): Body after the docstring.
        header_int (int): Last header line; text starts after it.
    Returns:
        list[StepPlan]: Pieces with located statements.
    Warnings:
        Blank and comment lines go with the statement that follows them.
    """
    pieces_list, size_int, previous_int = [StepPlan("", "", "")], 0, header_int
    for node in statements_list:
        top_info = TopStatement(node, previous_int + 1, node.end_lineno,
                                names=collect_statement_names_info(node))
        lines_int = top_info.last_line - top_info.first_line + 1
        if pieces_list[-1].statements and (
            size_int + lines_int > PIECE_TARGET_LINES_INT
        ):
            pieces_list.append(StepPlan("", "", ""))
            size_int = 0
        pieces_list[-1].statements.append(top_info)
        size_int += lines_int
        previous_int = node.end_lineno
    return pieces_list


def cut_balanced_pieces_list(
    statements_list: list[ast.stmt], header_int: int,
    parameters_set: set[str], budget_int: int,
) -> list[StepPlan]:
    """Cut body statements where the fewest values cross between pieces.

    Args:
        statements_list (list[ast.stmt]): Body after the docstring.
        header_int (int): Last header line; text starts after it.
        parameters_set (set[str]): Function parameters.
        budget_int (int): Preferred total lines per helper.
    Returns:
        list[StepPlan]: Pieces whose estimated size fits the budget
            where possible.
    Warnings:
        A single long statement still forms its own piece.
    """
    tops_list, previous_int = [], header_int
    for node in statements_list:
        tops_list.append(
            TopStatement(
                node, previous_int + 1, node.end_lineno,
                names=collect_statement_names_info(node)))
        previous_int = node.end_lineno
    count_int = len(tops_list)
    best_list: list[tuple[int, int]] = [(0, 0)] + [(10 ** 9, 0)] * count_int
    for end_int in range(1, count_int + 1):
        for start_int in range(end_int - 1, -1, -1):
            cost_int, size_int = estimate_piece_cost_tuple(
                tops_list, start_int, end_int, parameters_set)
            if size_int > budget_int and end_int - start_int > 1:
                break
            total_int = best_list[start_int][0] + cost_int
            if total_int < best_list[end_int][0]:
                best_list[end_int] = (total_int, start_int)
    cuts_list, end_int = [], count_int
    while end_int > 0:
        start_int = best_list[end_int][1]
        cuts_list.insert(0, (start_int, end_int))
        end_int = start_int
    return [StepPlan("", "", "", statements=tops_list[start:end])
            for start, end in cuts_list]


def estimate_piece_cost_tuple(
    tops_list: list[TopStatement], start_int: int, end_int: int,
    parameters_set: set[str],
) -> tuple[int, int]:
    """Estimate how costly and how long one candidate piece would be.

    Args:
        tops_list (list[TopStatement]): All body statements.
        start_int (int): First statement index.
        end_int (int): One past the last statement index.
        parameters_set (set[str]): Function parameters.
    Returns:
        tuple[int, int]: Values crossing its edges plus a per-piece cost,
            and the estimated helper length in lines.
    Warnings:
        Estimates guide the choice; merges later keep behavior.
    """
    piece_list = tops_list[start_int:end_int]
    reads_set = gather_statement_names_set(piece_list, "direct_reads")
    reads_set |= gather_statement_names_set(piece_list, "nested_reads")
    before_set = parameters_set | gather_statement_names_set(
        tops_list[:start_int], "writes")
    later_list = tops_list[end_int:]
    later_set = gather_statement_names_set(later_list, "direct_reads")
    later_set |= gather_statement_names_set(later_list, "nested_reads")
    inputs_int = len(reads_set & before_set)
    outputs_int = len(
        gather_statement_names_set(piece_list, "writes") & later_set)
    body_int = piece_list[-1].last_line - piece_list[0].first_line + 1
    return inputs_int + outputs_int + 4, body_int + 12 + inputs_int


def compute_piece_contract_tuple(
    plan_info: SplitPlan, index_int: int,
) -> tuple[list[str], list[str], set[str]]:
    """Return a piece's inputs, outputs and unbound local reads.

    Args:
        plan_info (SplitPlan): Planned split with its pieces.
        index_int (int): Piece to describe.
    Returns:
        tuple: Inputs and outputs in source order, and local names read
            before any binding.
    Warnings:
        Globals and builtins are read directly and are never passed. In
        a loop, values also flow from later pieces to the next round.
        A value the piece may leave unchanged is passed in and back.
    """
    pieces_list = plan_info.pieces
    facts_list = [step_facts_tuple(piece_info) for piece_info in pieces_list]
    exposed_set, nested_set, writes_set = facts_list[index_int]
    loop_bool = plan_info.loop_bool
    earlier_set = plan_info.before.union(*(
        fact_tuple[2] for fact_tuple in (facts_list if loop_bool
                                         else facts_list[:index_int])))
    later_set = plan_info.after_reads.union(*(
        fact_tuple[0] | fact_tuple[1]
        for fact_tuple
        in (facts_list if loop_bool else facts_list[index_int + 1:])))
    reads_set = exposed_set | nested_set
    outputs_set = writes_set & later_set
    kept_set = (outputs_set & earlier_set) - block_bind_set(
        [top_info.node for top_info in pieces_list[index_int].statements])
    order_list = sorted(reads_set | writes_set)
    inputs_list = [name for name in order_list if name in kept_set
                   or name in reads_set and name in earlier_set]
    outputs_list = [name for name in order_list if name in outputs_set]
    unbound_set = (reads_set & plan_info.locals) - earlier_set - writes_set
    return inputs_list, outputs_list, unbound_set


def find_piece_violation_tuple(
        plan_info: SplitPlan) -> tuple[int, int, str] | None:
    """Find the first piece boundary that would change behavior.

    Args:
        plan_info (SplitPlan): Planned split with its pieces.
    Returns:
        tuple | None: Pieces to merge (first, last) and the reason; a
            negative first index means no merge can help.
    Warnings:
        Early returns are allowed; the caller checks an exit flag.
    """
    pieces_list, last_int = plan_info.pieces, len(plan_info.pieces) - 1
    facts_list = [step_facts_tuple(piece_info) for piece_info in pieces_list]
    deleted_set = set().union(*(
        collect_may_deletes_set(top_info.node) for piece_info in pieces_list
        for top_info in piece_info.statements
    )) if plan_info.loop_bool else set()
    bound_set = plan_info.certain - deleted_set
    for index_int, piece_info in enumerate(pieces_list if last_int else []):
        inputs_list, outputs_list, _ = compute_piece_contract_tuple(plan_info,
                                                                    index_int)
        missing_set = set(inputs_list) - bound_set
        writers_list = [later_int for later_int in range(index_int + 1,
                                                         last_int + 1)
                        if facts_list[later_int][2] & missing_set]
        if missing_set:
            return (index_int, writers_list[-1], "value may be unbound") if (
                writers_list) else (index_int - 1, index_int, "unbound")
        for top_info in piece_info.statements:
            bound_set = (
                (bound_set | collect_must_binds_set(top_info.node))
                - collect_may_deletes_set(top_info.node) - deleted_set)
        if (index_int < last_int or not plan_info.terminal_bool) and set(
            outputs_list,
        ) - bound_set:
            first_int = min(index_int, last_int - 1)
            return first_int, first_int + 1, "value may be unbound"
        for later_int in range(last_int, index_int, -1):
            if facts_list[index_int][1] & facts_list[later_int][2]:
                return index_int, later_int, "closure"
    return None


def settle_reason_str(plan_info: SplitPlan) -> str | None:
    """Merge pieces until every boundary keeps behavior.

    Args:
        plan_info (SplitPlan): Planned split; its pieces change in place.
    Returns:
        str | None: Why the region cannot be split, or None when at
            least two safe pieces remain.
    Warnings:
        Merging can make pieces longer than the preferred size.
    """
    violation_tuple = find_piece_violation_tuple(plan_info)
    while violation_tuple is not None:
        if violation_tuple[0] < 0:
            return "a value may be unbound where it is needed"
        merge_steps_none(plan_info.pieces, *violation_tuple)
        violation_tuple = find_piece_violation_tuple(plan_info)
    if any(compute_piece_contract_tuple(plan_info, index_int)[2]
           for index_int in range(len(plan_info.pieces))):
        return "a local name may be read before it is bound"
    if len(plan_info.pieces) < 2:
        return "no safe split point was found"
    return None


def plan_split_info(
    node: ast.FunctionDef, class_node: ast.ClassDef | None,
    notes_list: list[str],
) -> SplitPlan | None:
    """Plan pieces for one long function, or explain why not.

    Args:
        node (ast.FunctionDef): Long function.
        class_node (ast.ClassDef | None): Owning class for methods.
        notes_list (list[str]): Destination for skip reasons.
    Returns:
        SplitPlan | None: Plan with at least two pieces, or None.
    Warnings:
        Pieces are merged until every boundary keeps behavior.
    """
    parameters_set = collect_parameter_names_set(node)
    statements_list, header_int = read_body_statements_tuple(node)
    plan_info = SplitPlan(
        node, class_node, parameters_set, before=set(parameters_set),
        certain=set(parameters_set), header_int=header_int,
        end_int=node.end_lineno, indent_int=node.body[0].col_offset,
        locals=parameters_set.union(*(
            collect_statement_names_info(node).writes
            for node in statements_list)))
    reason_str = skip_reason_str(node, class_node)
    if reason_str is None:
        plan_info.pieces = cut_balanced_pieces_list(
            statements_list, header_int, parameters_set, 40)
        reason_str = settle_reason_str(plan_info)
    if reason_str is not None:
        notes_list.append(f"{plan_label_str(plan_info)} was not split: "
                          f"{reason_str}.")
        return None
    return plan_info


def find_split_targets_list(
        module_node: ast.Module, max_lines_int: int) -> list[tuple]:
    """Find module functions and methods longer than the hard cap.

    Args:
        module_node (ast.Module): Parsed file.
        max_lines_int (int): Maximum physical lines per function.
    Returns:
        list[tuple]: (function, owning class or None) pairs.
    Warnings:
        Nested functions and async functions are not split.
    """
    found_list = []
    for node in module_node.body:
        owners_list = [(node, None)] if isinstance(
            node, FUNCTIONS_TUPLE) else (
            [(statement_node, node) for statement_node in node.body
             if isinstance(statement_node, FUNCTIONS_TUPLE)]
            if isinstance(node, ast.ClassDef) else [])
        for function_node, class_node in owners_list:
            first_int = min(
                [function_node.lineno]
                + [
                    decorator_node.lineno
                    for decorator_node in function_node.decorator_list])
            if function_node.end_lineno - first_int + 1 > max_lines_int:
                found_list.append((function_node, class_node))
    return found_list


def gather_statement_names_set(
    items_list: list[TopStatement], field_str: str,
) -> set[str]:
    """Collect one name-fact field across a group of statements.

    Args:
        items_list (list[TopStatement]): Statements with recorded facts.
        field_str (str): Name-fact attribute to combine.
    Returns:
        set[str]: Union of the selected name facts.
    Warnings:
        Facts describe syntax, not runtime resolution.
    """
    return set().union(*(getattr(top_info.names, field_str)
                         for top_info in items_list))
