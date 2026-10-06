"""Group executable statements into step functions that keep behavior."""

import ast
from contextlib import contextmanager
from contextvars import ContextVar
import keyword
import re
from typing import Iterator
import weakref

from funcloom.modular_models import (
    ProgramSource, StepPlan, StepRecord, TopStatement,
)

STEP_BODY_TARGET_INT = 28
# Names each analysed statement may unbind. Statement nodes are never
# changed in place (rewrites work on copies), so the result per node
# stays valid; entries go when their node does.
MAY_DELETES_CACHE: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
TRUST_WITH_VAR: ContextVar[bool] = ContextVar("funcloom_trust_with",
                                              default=False)
SUPPRESSING_NAMES_TUPLE = (
    "suppress", "raises", "assertRaises", "assertRaisesRegex",
    "assertWarns", "assertWarnsRegex", "ExitStack", "AsyncExitStack",
)
STOPWORDS_TUPLE = ("the", "a", "an", "of", "and", "to", "for", "in", "on",
                   "with", "step", "cell")


@contextmanager
def enable_with_block_trust(enabled_bool: bool) -> Iterator[None]:
    """Treat with-body bindings as certain while the block runs.

    Args:
        enabled_bool (bool): The user's --trust-with-blocks choice.
    Returns:
        Iterator[None]: Context in which the choice applies.
    Warnings:
        Opt-in: a context manager that suppresses an exception halfway
        would leave later names unbound in the original program.
    """
    token_info = TRUST_WITH_VAR.set(enabled_bool)
    try:
        yield
    finally:
        TRUST_WITH_VAR.reset(token_info)


def is_with_body_trusted_bool(node: ast.With | ast.AsyncWith) -> bool:
    """Tell whether a with body's bindings may be treated as certain.

    Args:
        node (ast.With | ast.AsyncWith): With statement.
    Returns:
        bool: True when the option is on and no context manager is a
            known exception suppressor (suppress, raises, ExitStack...).
    Warnings:
        Custom context managers are trusted only under the option.
    """
    if not TRUST_WITH_VAR.get():
        return False
    for with_item_node in node.items:
        expression = with_item_node.context_expr
        target = (expression.func if isinstance(expression, ast.Call)
                  else expression)
        name_str = getattr(target, "attr", None) or getattr(target, "id", "")
        if name_str in SUPPRESSING_NAMES_TUPLE:
            return False
    return True


def collect_walrus_binds_set(expression_node: ast.AST | None) -> set[str]:
    """Return names bound by := where the expression is always evaluated.

    Args:
        expression_node (ast.AST | None): Expression evaluated in full.
    Returns:
        set[str]: Walrus targets outside short-circuit operands,
            conditional branches, lambdas and comprehensions.
    Warnings:
        Assumes the expression finishes without raising.
    """
    names_set: set[str] = set()
    pending_list = [expression_node] if expression_node is not None else []
    while pending_list:
        node = pending_list.pop()
        if isinstance(node, ast.NamedExpr):
            names_set.add(node.target.id)
        if isinstance(node, ast.BoolOp):
            pending_list.append(node.values[0])
        elif isinstance(node, ast.IfExp):
            pending_list.append(node.test)
        elif not isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp,
                                   ast.DictComp, ast.GeneratorExp)):
            pending_list.extend(ast.iter_child_nodes(node))
    return names_set


def is_always_terminating_bool(statements_list: list[ast.stmt]) -> bool:
    """Tell whether a block always ends by returning or raising.

    Args:
        statements_list (list[ast.stmt]): Block of statements.
    Returns:
        bool: True when its last statement is return or raise.
    Warnings:
        Other ways of never finishing (loops, sys.exit) are not assumed.
    """
    return bool(statements_list) and isinstance(
        statements_list[-1], (ast.Return, ast.Raise))


def collect_branch_binds_set(node: ast.If) -> set[str]:
    """Return names certainly bound after an if statement continues.

    Args:
        node (ast.If): Conditional statement.
    Returns:
        set[str]: Names bound in the test, plus those bound on every
            branch that can continue after the statement.
    Warnings:
        A branch that always returns or raises cannot continue.
    """
    test_set = collect_walrus_binds_set(node.test)
    body_set, else_set = block_bind_set(node.body), block_bind_set(
        node.orelse)
    if is_always_terminating_bool(node.body):
        return test_set | else_set
    if is_always_terminating_bool(node.orelse):
        return test_set | body_set
    return test_set | (body_set & else_set if node.orelse else set())


def collect_assignment_binds_set(
    node: ast.Assign | ast.AugAssign | ast.AnnAssign,
) -> set[str]:
    """Return names an assignment statement binds.

    Args:
        node (ast.Assign | ast.AugAssign | ast.AnnAssign): Assignment.
    Returns:
        set[str]: Plain-name targets and always-evaluated := targets.
    Warnings:
        An annotation without a value binds nothing.
    """
    if isinstance(node, ast.AnnAssign) and node.value is None:
        return set()
    targets_list = (node.targets if isinstance(node, ast.Assign)
                    else [node.target])
    return collect_walrus_binds_set(node.value) | {
        inner_node.id for target_node in targets_list
        for inner_node in ast.walk(target_node)
        if isinstance(inner_node, ast.Name)
        and isinstance(inner_node.ctx, ast.Store)}


def collect_must_binds_set(node: ast.stmt) -> set[str]:
    """Return names a statement binds on every path that completes.

    Args:
        node (ast.stmt): Top-level statement.
    Returns:
        set[str]: Names certainly bound when the statement finishes.
    Warnings:
        Loops and with bodies may be skipped or interrupted, so their
        bindings are not certain (with bodies count under the opt-in
        --trust-with-blocks); a try body counts only when every handler
        returns or raises.
    """
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        return collect_assignment_binds_set(node)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {alias_node.asname or alias_node.name.split(".")[0]
                for alias_node in node.names if alias_node.name != "*"}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return {inner_node.id for with_node in node.items
                if with_node.optional_vars is not None
                for inner_node in ast.walk(with_node.optional_vars)
                if isinstance(inner_node, ast.Name)} | (
            block_bind_set(node.body) if is_with_body_trusted_bool(node)
            else set())
    if isinstance(node, ast.If):
        return collect_branch_binds_set(node)
    if isinstance(node, (ast.Try, ast.TryStar)):
        handled_bool = bool(node.handlers) and all(
            is_always_terminating_bool(handler.body)
            for handler in node.handlers)
        return block_bind_set(node.finalbody) | (block_bind_set(
            node.body + node.orelse) if handled_bool else set())
    if isinstance(node, (ast.Expr, ast.While)):
        return collect_walrus_binds_set(getattr(node, "value", None)
                                        or getattr(node, "test", None))
    return set()


def collect_may_deletes_set(node: ast.stmt) -> set[str]:
    """Return names a statement may unbind.

    Args:
        node (ast.stmt): Top-level statement.
    Returns:
        set[str]: Deleted names and exception-handler names.
    Warnings:
        Over-approximates by including deletions inside nested code.
        Results are cached per node (see MAY_DELETES_CACHE).
    """
    cached_frozenset = MAY_DELETES_CACHE.get(node)
    if cached_frozenset is not None:
        return set(cached_frozenset)
    names_set: set[str] = set()
    for inner_node in ast.walk(node):
        if isinstance(
                inner_node, ast.Name) and isinstance(inner_node.ctx, ast.Del):
            names_set.add(inner_node.id)
        elif isinstance(inner_node, ast.ExceptHandler) and inner_node.name:
            names_set.add(inner_node.name)
    MAY_DELETES_CACHE[node] = frozenset(names_set)
    return names_set


def block_bind_set(statements_list: list[ast.stmt]) -> set[str]:
    """Return names certainly bound after a sequence of statements.

    Args:
        statements_list (list[ast.stmt]): Statements in order.
    Returns:
        set[str]: Certain bindings, minus later deletions.
    Warnings:
        Assumes each statement completes normally.
    """
    bound_set: set[str] = set()
    for node in statements_list:
        bound_set = (
            bound_set | collect_must_binds_set(node)
        ) - collect_may_deletes_set(node)
    return bound_set


def build_initial_steps_list(
    executable_list: list[TopStatement], source_info: ProgramSource,
) -> list[StepPlan]:
    """Start with one step per notebook cell or commented script section.

    Args:
        executable_list (list[TopStatement]): Statements for steps.
        source_info (ProgramSource): Cell segments, if any.
    Returns:
        list[StepPlan]: Steps before size splitting and merging.
    Warnings:
        Titles come from Markdown headings or comments above code.
    """
    steps_list: list[StepPlan] = []
    previous_origin_str = None
    for top_info in executable_list:
        segment_info = next(
            (
                segment_info for segment_info in source_info.segments
                if segment_info.first_line <= top_info.first_line
                <= segment_info.last_line), None)
        origin_str = segment_info.origin if segment_info else ""
        if segment_info is not None:
            new_bool = origin_str != previous_origin_str
        else:
            new_bool = not steps_list or top_info.starts_section
        if new_bool:
            title_str = top_info.title or (
                segment_info.title if segment_info else "")
            steps_list.append(StepPlan("", title_str, origin_str))
        previous_origin_str = origin_str
        steps_list[-1].statements.append(top_info)
    return [piece for step_info in steps_list
            for piece in split_step_list(step_info)]


def split_step_list(step_info: StepPlan) -> list[StepPlan]:
    """Split a long step at statement boundaries.

    Args:
        step_info (StepPlan): Step that may exceed the size target.
    Returns:
        list[StepPlan]: One or more steps with the same title and origin.
    Warnings:
        A single long statement cannot be split and stays whole.
    """
    pieces_list = [StepPlan("", step_info.title, step_info.origin)]
    size_int = 0
    for top_info in step_info.statements:
        lines_int = top_info.last_line - top_info.first_line + 1
        if pieces_list[-1].statements and (
            size_int + lines_int > STEP_BODY_TARGET_INT
        ):
            pieces_list.append(StepPlan("", step_info.title,
                                        step_info.origin))
            size_int = 0
        pieces_list[-1].statements.append(top_info)
        size_int += lines_int
    return pieces_list


def collect_header_bound_set(node: ast.stmt) -> set[str]:
    """Return target names bound before a loop or with body reads them.

    Args:
        node (ast.stmt): Top-level statement.
    Returns:
        set[str]: for and with target names that the header expressions
            and the loop else block never read.
    Warnings:
        Reads after the statement still see the target as possibly
        unbound, because a loop may run zero times.
    """
    if isinstance(node, (ast.For, ast.AsyncFor)):
        targets_list, headers_list = [node.target], [node.iter, *node.orelse]
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        targets_list = [with_node.optional_vars for with_node in node.items
                        if with_node.optional_vars is not None]
        headers_list = [
            with_item_node.context_expr for with_item_node in node.items]
    else:
        return set()
    names_set = {
        inner_node.id for target in targets_list
        for inner_node in ast.walk(target) if isinstance(inner_node, ast.Name)}
    read_set = {
        inner_node.id for header in headers_list
        for inner_node in ast.walk(header) if isinstance(inner_node, ast.Name)}
    return names_set - read_set


def step_facts_tuple(step_info: StepPlan) -> tuple[set, set, set]:
    """Summarize a step's exposed reads, deferred reads and bindings.

    Args:
        step_info (StepPlan): Step to analyze.
    Returns:
        tuple: Reads before a certain local binding, reads by code
            defined in the step, and every name it binds.
    Warnings:
        Deferred reads happen when the defined code is called later.
    """
    exposed_set, nested_set, writes_set, bound_set = set(), set(), set(), set()
    for top_info in step_info.statements:
        exposed_set |= (top_info.names.direct_reads - bound_set
                        - collect_header_bound_set(top_info.node))
        nested_set |= top_info.names.nested_reads
        writes_set |= top_info.names.writes
        bound_set = ((bound_set | collect_must_binds_set(top_info.node))
                     - collect_may_deletes_set(top_info.node))
    return exposed_set, nested_set, writes_set


def merge_steps_none(
    steps_list: list[StepPlan], first_int: int, last_int: int,
    reason_str: str,
) -> None:
    """Combine consecutive steps into the first of them.

    Args:
        steps_list (list[StepPlan]): Steps, modified in place.
        first_int (int): Index of the first step to keep.
        last_int (int): Index of the last step to absorb.
        reason_str (str): Why the split would change behavior.
    Returns:
        None: The absorbed steps are removed.
    Warnings:
        Merging can exceed the preferred function size.
    """
    kept_info = steps_list[first_int]
    for absorbed_info in steps_list[first_int + 1:last_int + 1]:
        kept_info.statements.extend(absorbed_info.statements)
        kept_info.merge_reasons.extend(absorbed_info.merge_reasons)
        kept_info.title = kept_info.title or absorbed_info.title
    kept_info.merge_reasons.append(reason_str)
    del steps_list[first_int + 1:last_int + 1]


def compute_certain_states_list(steps_list: list[StepPlan]) -> list[set[str]]:
    """Compute names certainly bound at each step start and at the end.

    Args:
        steps_list (list[StepPlan]): Steps in order.
    Returns:
        list[set[str]]: One state per step start, then the final state.
    Warnings:
        Imported definitions and constants are always available and are
        not part of these states.
    """
    bound_set: set[str] = set()
    states_list = [set()]
    for step_info in steps_list:
        for top_info in step_info.statements:
            bound_set = ((bound_set | collect_must_binds_set(top_info.node))
                         - collect_may_deletes_set(top_info.node))
        states_list.append(set(bound_set))
    return states_list


def list_contract_names_tuple(
    steps_list: list[StepPlan], index_int: int, facts_list: list[tuple],
) -> tuple[list[str], list[str]]:
    """List a step's parameters and the values later steps need from it.

    Args:
        steps_list (list[StepPlan]): Steps in order.
        index_int (int): Step to describe.
        facts_list (list[tuple]): step_facts_tuple for every step.
    Returns:
        tuple: Input names and output names, in source order.
    Warnings:
        Only names bound by earlier steps become parameters. A value the
        step may leave unchanged is passed in so it can be returned.
    """
    exposed_set, nested_set, writes_set = facts_list[index_int]
    earlier_set = set().union(*(
        fact_tuple[2] for fact_tuple in facts_list[:index_int]))
    later_set = set().union(*(fact_tuple[0] | fact_tuple[1]
                              for fact_tuple in facts_list[index_int + 1:]))
    order_list = order_names_list(steps_list[index_int])
    outputs_set = writes_set & later_set
    kept_set = (outputs_set & earlier_set) - block_bind_set(
        [top_info.node for top_info in steps_list[index_int].statements])
    inputs_list = [name_str for name_str in order_list if name_str in (
        (exposed_set | nested_set) & earlier_set | kept_set)]
    outputs_list = [name_str for name_str in order_list
                    if name_str in outputs_set]
    return inputs_list, outputs_list


def order_names_list(step_info: StepPlan) -> list[str]:
    """List every name used in a step by first source position.

    Args:
        step_info (StepPlan): Step to scan.
    Returns:
        list[str]: Unique names in order of first appearance.
    Warnings:
        Used only to order parameters and returned values readably.
    """
    occurrences_list = sorted(
        (node.lineno, node.col_offset, node.id)
        for top_info in step_info.statements
        for node in ast.walk(top_info.node) if isinstance(node, ast.Name)
    )
    ordered_list = list(
        dict.fromkeys(
            occurrence_tuple[2] for occurrence_tuple in occurrences_list))
    all_set = set().union(*(
        top_info.names.writes | top_info.names.direct_reads
        | top_info.names.nested_reads for top_info in step_info.statements))
    return ordered_list + sorted(all_set - set(ordered_list))


def find_first_violation_tuple(
    steps_list: list[StepPlan],
) -> tuple[int, int, str] | None:
    """Find the first split that would change the program's behavior.

    Args:
        steps_list (list[StepPlan]): Steps in order.
    Returns:
        tuple | None: Steps to merge (first, last) and the reason.
    Warnings:
        Checks unbound inputs, unbound outputs and late-bound closures.
    """
    facts_list = [step_facts_tuple(step_info) for step_info in steps_list]
    states_list = compute_certain_states_list(steps_list)
    for index_int in range(len(steps_list)):
        inputs_list, outputs_list = list_contract_names_tuple(
            steps_list, index_int, facts_list)
        for name_str in inputs_list:
            if name_str not in states_list[index_int]:
                return index_int - 1, index_int, (
                    f"'{name_str}' may be unbound where this step starts.")
        for name_str in outputs_list:
            if name_str not in states_list[index_int + 1]:
                return index_int, index_int + 1, (
                    f"'{name_str}' may be unbound where this step ends.")
        for later_int in range(len(steps_list) - 1, index_int, -1):
            shared_set = facts_list[index_int][1] & facts_list[later_int][2]
            if shared_set:
                return index_int, later_int, (
                    "Code defined here reads "
                    f"{', '.join(sorted(shared_set))}, which a later step "
                    "rebinds.")
    return None


def settle_steps_list(steps_list: list[StepPlan]) -> list[StepPlan]:
    """Merge steps until every split keeps the original behavior.

    Args:
        steps_list (list[StepPlan]): Initial steps.
    Returns:
        list[StepPlan]: Steps with inputs and outputs filled in.
    Warnings:
        In the worst case everything becomes one step, which is correct
        but long.
    """
    violation_tuple = find_first_violation_tuple(steps_list)
    while violation_tuple is not None:
        merge_steps_none(steps_list, *violation_tuple)
        violation_tuple = find_first_violation_tuple(steps_list)
    facts_list = [step_facts_tuple(step_info) for step_info in steps_list]
    for index_int, step_info in enumerate(steps_list):
        step_info.inputs, step_info.outputs = list_contract_names_tuple(
            steps_list, index_int, facts_list)
    return steps_list


def step_name_str(
    step_info: StepPlan, index_int: int, taken_set: set[str],
) -> str:
    """Name a step from its title, its results or its position.

    Args:
        step_info (StepPlan): Step to name.
        index_int (int): One-based step position.
        taken_set (set[str]): Names already used in the program.
    Returns:
        str: A unique, valid, lower-case function name.
    Warnings:
        Titles are user text; only letters and digits are kept.
    """
    words_list = [word for word in re.findall(
        r"[a-z0-9]+", step_info.title.lower()) if word not in STOPWORDS_TUPLE]
    base_str = "_".join(words_list[:5])
    if not base_str and step_info.outputs:
        base_str = "compute_" + step_info.outputs[-1].lower().strip("_")
    if not base_str or not base_str.isidentifier():
        base_str = ("step_" + base_str if base_str and base_str[0].isdigit()
                    else f"run_step_{index_int}")
    candidate_str, counter_int = base_str, 2
    while candidate_str in taken_set or keyword.iskeyword(candidate_str):
        candidate_str = f"{base_str}_{counter_int}"
        counter_int += 1
    taken_set.add(candidate_str)
    return candidate_str


def step_record(step_info: StepPlan) -> StepRecord:
    """Summarize a step for the report.

    Args:
        step_info (StepPlan): Named, settled step.
    Returns:
        StepRecord: Serializable description with source lines.
    Warnings:
        Line numbers refer to the combined program text.
    """
    return StepRecord(
        step_info.name, step_info.title, step_info.origin,
        step_info.statements[0].first_line,
        step_info.statements[-1].last_line, list(step_info.inputs),
        list(step_info.outputs), list(step_info.merge_reasons),
    )
