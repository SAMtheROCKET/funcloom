"""Walk a selected region with blocks and definitions (M2b.8-M2b.10).

Definite assignment decides which names a read can rely on: inside a
branch, names assigned earlier in that branch; after an if/else, names
assigned in both branches; after a loop, nothing assigned in its body,
because it may run zero times. Every other read must be a valid input.
At the end every assigned name must be set on all paths, be passed in
because it had a value before the region, or be left out of the return
when nothing else in the file can read it; otherwise PLAN009 refuses.
"""

import ast
from dataclasses import dataclass, field
import symtable

from funcloom.plan_analysis import (
    accepts_input_bool, find_expression_issue_str, make_binding_fact,
    read_names_list, record_inputs_none, split_statement_parts_tuple,
    split_target_parts_tuple,
)
from funcloom.plan_bindings import (
    DYNAMIC_NAMESPACE_NAMES_TUPLE, choose_reaching_sites_list,
    resolve_status_tuple,
)
from funcloom.plan_models import (
    ExtractionPlan, ModuleBindings, NameResolution, append_issue_none,
)

JUMPS_TUPLE = (ast.Pass, ast.Break, ast.Continue)


@dataclass
class RegionFlow:
    """What the walk over one selected region has learned so far."""

    bindings: ModuleBindings
    report: ExtractionPlan
    inputs: set[str] = field(default_factory=set)
    outputs: list[str] = field(default_factory=list)


def analyze_region_none(
    module_node: ast.Module, statements_list: list[ast.stmt],
    bindings_info: ModuleBindings, plan_report: ExtractionPlan,
    source_str: str,
) -> None:
    """Derive inputs and outputs of a region with blocks and definitions.

    Args:
        module_node (ast.Module): Whole parsed source.
        statements_list (list[ast.stmt]): Whole selected statements.
        bindings_info (ModuleBindings): Accepted prefix bindings.
        plan_report (ExtractionPlan): Contract and diagnostic accumulator.
        source_str (str): Decoded source, for Python's own scope tables.
    Returns:
        None: Records inputs, outputs, assumptions and refusals.
    Warnings:
        Constant conditions are not folded; a loop may always run zero
        times as far as this analysis knows.
    """
    flow_info = RegionFlow(bindings_info, plan_report)
    definite_set = walk_block_set(statements_list, set(), flow_info)
    if not plan_report.diagnostics:
        settle_outputs_none(module_node, definite_set, flow_info)
    if not plan_report.diagnostics:
        check_deferred_reads_none(module_node, statements_list, flow_info,
                                  source_str)


def walk_block_set(statements_list: list[ast.stmt], definite_set: set[str],
                   flow_info: RegionFlow) -> set[str]:
    """Walk statements in order.

    Args:
        statements_list (list[ast.stmt]): One block.
        definite_set (set[str]): Names set on every path so far.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: Names set on every path after the block.
    Warnings:
        Statements after break or continue are walked as if reachable.
    """
    for statement_node in statements_list:
        definite_set = walk_statement_set(statement_node, definite_set,
                                          flow_info)
    return definite_set


def walk_statement_set(statement_node: ast.stmt, definite_set: set[str],
                       flow_info: RegionFlow) -> set[str]:
    """Walk one statement of a supported form.

    Args:
        statement_node (ast.stmt): The statement.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: Names set on every path after it.
    Warnings:
        del, global, try/except* and async forms stay refused (PLAN002).
    """
    if isinstance(statement_node, JUMPS_TUPLE):
        return definite_set
    walker = BLOCK_WALKERS_DICT.get(type(statement_node))
    if walker is not None:
        return walker(statement_node, definite_set, flow_info)
    return walk_simple_set(statement_node, definite_set, flow_info)


def walk_if_set(if_node: ast.If, definite_set: set[str],
                flow_info: RegionFlow) -> set[str]:
    """Walk an if statement; names set in both branches become definite.

    Args:
        if_node (ast.If): The statement.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: Names set on every path after it.
    Warnings:
        Constant tests are not folded.
    """
    if not check_expression_bool(if_node.test, flow_info):
        return definite_set
    read_expressions_none([if_node.test], definite_set, flow_info)
    body_set = walk_block_set(if_node.body, set(definite_set), flow_info)
    else_set = walk_block_set(if_node.orelse, set(definite_set), flow_info)
    return definite_set | (body_set & else_set)


def walk_loop_set(loop_node: ast.For | ast.While, definite_set: set[str],
                  flow_info: RegionFlow) -> set[str]:
    """Walk a loop; nothing assigned inside it becomes definite.

    Args:
        loop_node (ast.For | ast.While): The loop.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: The definite names, unchanged.
    Warnings:
        The loop may run zero times.
    """
    walk_loop_none(loop_node, definite_set, flow_info)
    return definite_set


def walk_try_set(try_node: ast.Try, definite_set: set[str],
                 flow_info: RegionFlow) -> set[str]:
    """Walk try/except/else/finally.

    Args:
        try_node (ast.Try): The statement.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: Names set after normal completion and after every
            handler, plus names set in finally.
    Warnings:
        The body may stop at any statement, so a handler starts from the
        names definite before the try. An exception that escapes ends
        the region in the original and the draft alike.
    """
    normal_set = walk_block_set(
        try_node.orelse,
        walk_block_set(try_node.body, set(definite_set), flow_info),
        flow_info)
    for handler_node in try_node.handlers:
        normal_set &= walk_handler_set(handler_node, definite_set, flow_info)
    final_set = walk_block_set(try_node.finalbody, set(definite_set),
                               flow_info)
    return definite_set | normal_set | final_set


def walk_handler_set(handler_node: ast.ExceptHandler, definite_set: set[str],
                     flow_info: RegionFlow) -> set[str]:
    """Walk one except clause.

    Args:
        handler_node (ast.ExceptHandler): The clause.
        definite_set (set[str]): Names definite before the try.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: Names set on every path through the clause.
    Warnings:
        Python deletes the `as` name when the clause ends, so it is never
        returned; a name that already has a value is refused (PLAN009)
        because the clause could delete it from the module.
    """
    inner_set = set(definite_set)
    if handler_node.type is not None:
        if not check_expression_bool(handler_node.type, flow_info):
            return set(definite_set)
        read_expressions_none([handler_node.type], definite_set, flow_info)
    name_str = handler_node.name
    if name_str and (name_str in definite_set
                     or name_str in flow_info.outputs
                     or is_bound_at_start_bool(name_str, flow_info.report)):
        append_issue_none(flow_info.report, "PLAN009", handler_node.lineno, (
            f"'except ... as {name_str}' deletes '{name_str}' when the "
            "clause ends; it already has a value, which the draft could "
            "not remove from the module."))
    if name_str:
        inner_set.add(name_str)
    after_set = walk_block_set(handler_node.body, inner_set, flow_info)
    after_set.discard(name_str)
    return after_set


def walk_with_set(with_node: ast.With, definite_set: set[str],
                  flow_info: RegionFlow) -> set[str]:
    """Walk a with statement.

    Args:
        with_node (ast.With): The statement.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: The definite names plus the `as` targets and the names
            the body sets on every path.
    Warnings:
        A context manager that suppresses an exception part-way through
        the body would leave later names unset; the plan states that the
        draft then raises UnboundLocalError where the original goes on.
    """
    after_set = set(definite_set)
    for item_node in with_node.items:
        if not check_expression_bool(item_node.context_expr, flow_info):
            return definite_set
        read_expressions_none([item_node.context_expr], after_set, flow_info)
        if item_node.optional_vars is None:
            continue
        parts_tuple = split_target_parts_tuple(item_node.optional_vars)
        if parts_tuple is None:
            append_issue_none(flow_info.report, "PLAN002", with_node.lineno,
                              "Nested unpacking in a with target is "
                              "outside the supported forms.")
            return definite_set
        read_expressions_none(parts_tuple[0], after_set, flow_info)
        note_outputs_none(parts_tuple[1], flow_info)
        after_set |= {name_node.id for name_node in parts_tuple[1]}
    body_set = walk_block_set(with_node.body, set(after_set), flow_info)
    if body_set - after_set:
        flow_info.report.assumptions.append(
            f"The with block at line {with_node.lineno} is assumed not to "
            "suppress exceptions: if its context manager did, the draft "
            "would raise UnboundLocalError for names the block had not "
            "set yet, where the original leaves them unset and goes on.")
    return body_set


def walk_match_set(match_node: ast.Match, definite_set: set[str],
                   flow_info: RegionFlow) -> set[str]:
    """Walk a match statement.

    Args:
        match_node (ast.Match): The statement.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: Names set by every case when the last case always
            matches; otherwise the definite names unchanged.
    Warnings:
        Captures are set only inside their own case.
    """
    if not check_expression_bool(match_node.subject, flow_info):
        return definite_set
    read_expressions_none([match_node.subject], definite_set, flow_info)
    results_list = []
    for case_node in match_node.cases:
        case_set = walk_case_set(case_node, definite_set, flow_info)
        if case_set is None:
            return definite_set
        results_list.append(case_set)
    last_node = match_node.cases[-1]
    if last_node.guard is None and isinstance(last_node.pattern,
                                              ast.MatchAs) and (
            last_node.pattern.pattern is None):
        return definite_set | set.intersection(*results_list)
    return definite_set


def walk_case_set(case_node: ast.match_case, definite_set: set[str],
                  flow_info: RegionFlow) -> set[str] | None:
    """Walk one case of a match statement.

    Args:
        case_node (ast.match_case): The case.
        definite_set (set[str]): Names set on every path before the match.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str] | None: Names set on every path through the case, or
            None when a pattern value or guard is refused.
    Warnings:
        Captures are set only inside their own case.
    """
    captures_list, values_list = scan_pattern_tuple(case_node.pattern)
    guard_list = [case_node.guard] if case_node.guard else []
    if not all(check_expression_bool(node, flow_info)
               for node in [*values_list, *guard_list]):
        return None
    read_expressions_none(values_list, definite_set, flow_info)
    note_outputs_none([ast.Name(id=name_str, ctx=ast.Store(),
                                lineno=case_node.pattern.lineno,
                                col_offset=case_node.pattern.col_offset)
                       for name_str in captures_list], flow_info)
    inner_set = definite_set | set(captures_list)
    read_expressions_none(guard_list, inner_set, flow_info)
    return walk_block_set(case_node.body, inner_set, flow_info)


def scan_pattern_tuple(pattern_node: ast.pattern
                       ) -> tuple[list[str], list[ast.expr]]:
    """List a pattern's capture names and the expressions it reads.

    Args:
        pattern_node (ast.pattern): A case pattern.
    Returns:
        tuple: Capture names in order, and value, class and key
            expressions.
    Warnings:
        Alternatives of an or-pattern bind the same names.
    """
    captures_list: list[str] = []
    values_list: list[ast.expr] = []
    for node in ast.walk(pattern_node):
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            captures_list.append(node.name)
        elif isinstance(node, ast.MatchMapping):
            captures_list.extend([node.rest] if node.rest else [])
            values_list.extend(node.keys)
        elif isinstance(node, ast.MatchValue):
            values_list.append(node.value)
        elif isinstance(node, ast.MatchClass):
            values_list.append(node.cls)
    return list(dict.fromkeys(captures_list)), values_list


def walk_raise_set(statement_node: ast.Raise | ast.Assert,
                   definite_set: set[str], flow_info: RegionFlow) -> set[str]:
    """Walk raise and assert: they only read.

    Args:
        statement_node (ast.Raise | ast.Assert): The statement.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: The definite names, unchanged.
    Warnings:
        `python -O` removes assert statements in both versions.
    """
    fields_tuple = (("exc", "cause") if isinstance(statement_node, ast.Raise)
                    else ("test", "msg"))
    nodes_list = [getattr(statement_node, field_str)
                  for field_str in fields_tuple
                  if getattr(statement_node, field_str) is not None]
    if all(check_expression_bool(node, flow_info) for node in nodes_list):
        read_expressions_none(nodes_list, definite_set, flow_info)
    return definite_set


def walk_loop_none(loop_node: ast.For | ast.While, definite_set: set[str],
                   flow_info: RegionFlow) -> None:
    """Walk a for or while loop and its else block.

    Args:
        loop_node (ast.For | ast.While): The loop.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        None: Nothing assigned inside becomes definite after the loop.
    Warnings:
        A for target binds before each pass through the body.
    """
    header_node = (loop_node.iter if isinstance(loop_node, ast.For)
                   else loop_node.test)
    if not check_expression_bool(header_node, flow_info):
        return
    read_expressions_none([header_node], definite_set, flow_info)
    inner_set = set(definite_set)
    if isinstance(loop_node, ast.For):
        parts_tuple = split_target_parts_tuple(loop_node.target)
        if parts_tuple is None:
            append_issue_none(flow_info.report, "PLAN002", loop_node.lineno,
                              "Nested unpacking in a loop target is "
                              "outside the supported forms.")
            return
        read_expressions_none(parts_tuple[0], definite_set, flow_info)
        note_outputs_none(parts_tuple[1], flow_info)
        inner_set |= {name_node.id for name_node in parts_tuple[1]}
    walk_block_set(loop_node.body, inner_set, flow_info)
    walk_block_set(loop_node.orelse, set(definite_set), flow_info)


def walk_simple_set(statement_node: ast.stmt, definite_set: set[str],
                    flow_info: RegionFlow) -> set[str]:
    """Walk an assignment, augmented assignment or expression statement.

    Args:
        statement_node (ast.stmt): The statement.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: The names it assigns added to the definite names.
    Warnings:
        Other statement forms are refused with PLAN002.
    """
    parts_tuple = split_statement_parts_tuple(statement_node)
    if parts_tuple is None:
        append_issue_none(flow_info.report, "PLAN002", statement_node.lineno,
                          f"{type(statement_node).__name__} is outside the "
                          "supported statement forms.")
        return definite_set
    reads_list, names_list = parts_tuple
    expressions_list = [node for node in reads_list
                        if isinstance(node, ast.expr)]
    if not all(check_expression_bool(node, flow_info)
               for node in expressions_list):
        return definite_set
    read_expressions_none(reads_list, definite_set, flow_info)
    note_outputs_none(names_list, flow_info)
    return definite_set | {name_node.id for name_node in names_list}


def check_expression_bool(expression_node: ast.AST,
                          flow_info: RegionFlow) -> bool:
    """Refuse an expression outside the planning subset.

    Args:
        expression_node (ast.AST): Value, test or iterable.
        flow_info (RegionFlow): Walk state (gets PLAN002).
    Returns:
        bool: True when the expression is supported.
    Warnings:
        Calls and operators are accepted; PLAN008 checks them later.
    """
    issue_str = find_expression_issue_str(expression_node)
    if issue_str is not None:
        append_issue_none(flow_info.report, "PLAN002", expression_node.lineno,
                          f"Unsupported value: {issue_str}.")
    return issue_str is None


def read_expressions_none(nodes_list: list[ast.AST], definite_set: set[str],
                          flow_info: RegionFlow) -> None:
    """Record reads that are not set on every path as inputs.

    Args:
        nodes_list (list[ast.AST]): Read expressions or names.
        definite_set (set[str]): Names set on every path at this point.
        flow_info (RegionFlow): Walk state.
    Returns:
        None: Adds inputs, assumptions and PLAN003 refusals.
    Warnings:
        A conditionally assigned name with a value before the region is
        read as an input, so its earlier value is passed in.
    """
    record_inputs_none(read_names_list(nodes_list), definite_set,
                       flow_info.inputs, flow_info.bindings, flow_info.report)


def note_outputs_none(names_list: list[ast.Name],
                      flow_info: RegionFlow) -> None:
    """Remember assigned names in first-assignment order.

    Args:
        names_list (list[ast.Name]): Names one statement or loop assigns.
        flow_info (RegionFlow): Walk state (outputs extended).
    Returns:
        None.
    Warnings:
        Names set on only some paths are settled at the end of the walk.
    """
    for name_node in names_list:
        if name_node.id not in flow_info.outputs:
            flow_info.outputs.append(name_node.id)
            flow_info.report.outputs.append(make_binding_fact(
                name_node.id, name_node.lineno, flow_info.bindings))


def settle_outputs_none(module_node: ast.Module, definite_set: set[str],
                        flow_info: RegionFlow) -> None:
    """Make every returned name safe to return, or refuse.

    Args:
        module_node (ast.Module): Whole parsed source.
        definite_set (set[str]): Names set on every path at the end.
        flow_info (RegionFlow): Walk state.
    Returns:
        None: Adds inputs or assumptions, drops outputs or adds PLAN009.
    Warnings:
        A dropped name is no longer set in the module after the call;
        other modules that import it would not see it.
    """
    report = flow_info.report
    for name_str in list(flow_info.outputs):
        if name_str in definite_set or name_str in flow_info.inputs:
            continue
        if is_bound_at_start_bool(name_str, report):
            report.inputs.append(make_binding_fact(
                name_str, report.start_line, flow_info.bindings))
            report.assumptions.append(
                f"'{name_str}' is passed in so it keeps its earlier value "
                "on paths that do not assign it.")
        elif is_read_elsewhere_bool(module_node, name_str, report):
            append_issue_none(report, "PLAN009", report.start_line, (
                f"'{name_str}' is set only on some paths through the region "
                "and has no value before it, but other code in the file "
                "reads it, so the draft cannot return it reliably."))
        else:
            report.outputs = [item for item in report.outputs
                              if item.name != name_str]
            report.assumptions.append(
                f"'{name_str}' is set only on some paths and nothing else in "
                "this file reads it, so the draft does not return it; "
                "another module importing it would no longer see it.")


def is_bound_at_start_bool(name_str: str, plan_report: ExtractionPlan
                           ) -> bool:
    """Whether a name has an accepted value where the region starts.

    Args:
        name_str (str): Module name.
        plan_report (ExtractionPlan): Binding sites of the prefix.
    Returns:
        bool: True for a direct or module-level ambiguous binding.
    Warnings:
        Resolves a read placed at the first selected line.
    """
    read_node = ast.Name(id=name_str, ctx=ast.Load(),
                         lineno=plan_report.start_line, col_offset=0)
    located_list = [
        (site, (-1,) if site.kind == "loop_target" else ())
        for site in plan_report.binding_sites if site.region == "prefix"]
    reaching_list = choose_reaching_sites_list(read_node, (), located_list)
    status_str, detail_str = resolve_status_tuple(name_str, reaching_list)
    return accepts_input_bool(NameResolution(
        name_str, plan_report.start_line, 0, status_str, detail_str,
        [site for site, _ in reaching_list]))


def is_read_elsewhere_bool(module_node: ast.Module, name_str: str,
                           plan_report: ExtractionPlan) -> bool:
    """Whether code outside the region could read a module name.

    Args:
        module_node (ast.Module): Whole parsed source.
        name_str (str): Module name.
        plan_report (ExtractionPlan): Region lines.
    Returns:
        bool: True when module code outside the region reads it, a
            function, class or comprehension uses it as a global, the
            name appears as a string, or a namespace call is present.
    Warnings:
        Reads from other modules cannot be seen here. Python's own
        scoping (symtable) separates a function's parameters and locals
        from the module name.
    """
    if any(isinstance(node, ast.Name) and node.id in (
            DYNAMIC_NAMESPACE_NAMES_TUPLE) or isinstance(
            node, ast.Constant) and node.value == name_str
           for node in ast.walk(module_node)):
        return True
    rest_node = ast.Module(body=[
        node for node in module_node.body
        if not plan_report.start_line <= node.lineno <= plan_report.end_line
    ], type_ignores=[])
    try:
        table_info = symtable.symtable(ast.unparse(rest_node), "<rest>",
                                       "exec")
    except (SyntaxError, ValueError):
        return True
    return check_table_reads_bool(table_info, name_str, True)


def check_table_reads_bool(table_info: symtable.SymbolTable, name_str: str,
                           module_bool: bool) -> bool:
    """Whether a scope, or any scope inside it, reads a module name.

    Args:
        table_info (symtable.SymbolTable): Module or nested scope.
        name_str (str): Module name.
        module_bool (bool): True for the module scope itself.
    Returns:
        bool: True when the module scope references the name, or a nested
            scope declares it global or reads it as a global.
    Warnings:
        A nested scope's own parameters and locals are not the module
        name.
    """
    if name_str in table_info.get_identifiers():
        symbol_info = table_info.lookup(name_str)
        if module_bool and symbol_info.is_referenced():
            return True
        if not module_bool and (symbol_info.is_declared_global() or (
                symbol_info.is_global() and symbol_info.is_referenced())):
            return True
    return any(check_table_reads_bool(child_info, name_str, False)
               for child_info in table_info.get_children())


def list_written_names_list(statement_node: ast.stmt) -> list[ast.Name]:
    """Names a supported statement assigns anywhere inside it.

    Args:
        statement_node (ast.stmt): Simple statement or block.
    Returns:
        list[ast.Name]: Assigned names (pattern captures and except names
            as synthetic Name nodes) in source order.
    Warnings:
        Comprehension and lambda variables are local and not listed.
    """
    names_list: list[ast.Name] = []
    pending_list: list[ast.AST] = [statement_node]
    while pending_list:
        node = pending_list.pop()
        if isinstance(node, LOCAL_SCOPES_TUPLE):
            continue
        if isinstance(node, DEFINITIONS_TUPLE):
            names_list.append(ast.Name(id=node.name, ctx=ast.Store(),
                                       lineno=node.lineno,
                                       col_offset=node.col_offset))
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names_list.append(node)
        name_str = (getattr(node, "rest", None) if isinstance(
            node, ast.MatchMapping) else getattr(node, "name", None))
        if isinstance(node, CAPTURES_TUPLE) and name_str:
            names_list.append(ast.Name(id=name_str, ctx=ast.Store(),
                                       lineno=node.lineno,
                                       col_offset=node.col_offset))
        pending_list.extend(ast.iter_child_nodes(node))
    return sorted(names_list, key=lambda node: (node.lineno, node.col_offset))


def walk_definition_set(definition_node: ast.stmt, definite_set: set[str],
                        flow_info: RegionFlow) -> set[str]:
    """Walk a def, async def or class statement (M2b.10).

    Args:
        definition_node (ast.stmt): The definition.
        definite_set (set[str]): Names set on every path before it.
        flow_info (RegionFlow): Walk state.
    Returns:
        set[str]: The definite names plus the defined name.
    Warnings:
        Decorators, defaults, bases and annotations are read now; the body
        runs later and is checked by check_deferred_reads_none.
    """
    if getattr(definition_node, "type_params", None) or any(
            isinstance(node, (ast.Global, ast.Nonlocal))
            for node in ast.walk(definition_node)):
        append_issue_none(flow_info.report, "PLAN002",
                          definition_node.lineno, (
                              "Type parameters, global and nonlocal inside "
                              "a definition need broader scope analysis."))
        return definite_set
    nodes_list = list_definition_reads_list(definition_node)
    if not all(check_expression_bool(node, flow_info) for node in nodes_list):
        return definite_set
    read_expressions_none(nodes_list, definite_set, flow_info)
    note_outputs_none([ast.Name(id=definition_node.name, ctx=ast.Store(),
                                lineno=definition_node.lineno,
                                col_offset=definition_node.col_offset)],
                      flow_info)
    return definite_set | {definition_node.name}


def list_definition_reads_list(definition_node: ast.stmt) -> list[ast.expr]:
    """Expressions a definition evaluates when it runs.

    Args:
        definition_node (ast.stmt): def, async def or class statement.
    Returns:
        list[ast.expr]: Decorators, then defaults and annotations or
            bases and keyword values.
    Warnings:
        Annotations are treated as evaluated now (Python 3.12 and 3.13);
        Python 3.14 defers them, which the deferred check also covers.
    """
    nodes_list = list(definition_node.decorator_list)
    if isinstance(definition_node, ast.ClassDef):
        return [*nodes_list, *definition_node.bases,
                *(item.value for item in definition_node.keywords)]
    arguments_node = definition_node.args
    parameters_list = [*arguments_node.posonlyargs, *arguments_node.args,
                       *arguments_node.kwonlyargs, arguments_node.vararg,
                       arguments_node.kwarg]
    nodes_list.extend(arguments_node.defaults)
    nodes_list.extend(item for item in arguments_node.kw_defaults if item)
    nodes_list.extend(item.annotation for item in parameters_list
                      if item is not None and item.annotation is not None)
    if definition_node.returns is not None:
        nodes_list.append(definition_node.returns)
    return nodes_list


def check_deferred_reads_none(module_node: ast.Module,
                              statements_list: list[ast.stmt],
                              flow_info: RegionFlow, source_str: str) -> None:
    """Check the names deferred code in the region reads (M2b.10).

    Args:
        module_node (ast.Module): Whole parsed source.
        statements_list (list[ast.stmt]): Selected statements.
        flow_info (RegionFlow): Walk state with inputs and outputs.
        source_str (str): Decoded source for Python's scope tables.
    Returns:
        None: Adds PLAN010 refusals and an assumption about names.
    Warnings:
        Inside the draft, a function, lambda, generator expression or
        class body that reads a draft-local name keeps that variable
        (a closure); the original reads the module name when it runs.
        Both agree unless code outside the region rebinds the name.
    """
    deferred_list = list_deferred_nodes_list(statements_list)
    if not deferred_list:
        return
    local_set = flow_info.inputs | set(flow_info.outputs) | {
        name_node.id for statement_node in statements_list
        for name_node in list_written_names_list(statement_node)}
    tables_list = list_tables_list(symtable.symtable(source_str, "<plan>",
                                                     "exec"))
    report = flow_info.report
    for node in deferred_list:
        for name_str in sorted(read_globals_set(node, tables_list)
                               & local_set):
            if is_rebound_elsewhere_bool(module_node, name_str, report):
                append_issue_none(report, "PLAN010", node.lineno, (
                    f"Code at line {node.lineno} runs later and reads "
                    f"'{name_str}'; inside the draft that is a local "
                    "variable, and code outside the region rebinds the "
                    "module name, so the two could differ."))
    note_qualified_names_none(deferred_list, report)


def note_qualified_names_none(deferred_list: list[ast.AST],
                              report: ExtractionPlan) -> None:
    """State that definitions moved into the draft get nested names.

    Args:
        deferred_list (list[ast.AST]): Deferred scopes in the region.
        report (ExtractionPlan): Assumption destination.
    Returns:
        None: Adds one assumption when a def, class or lambda moves.
    Warnings:
        Nested functions cannot be pickled by reference.
    """
    if any(isinstance(node, (*DEFINITIONS_TUPLE, ast.Lambda))
           for node in deferred_list):
        report.assumptions.append(
            "Functions, lambdas and classes defined in the region live "
            "inside the draft, so their qualified names change (for "
            "example 'draft.<locals>.helper'), which shows in reprs and "
            "stops pickling them by reference.")


def list_deferred_nodes_list(statements_list: list[ast.stmt]
                             ) -> list[ast.AST]:
    """The outermost definitions, lambdas and generator expressions.

    Args:
        statements_list (list[ast.stmt]): Selected statements.
    Returns:
        list[ast.AST]: Deferred scopes not nested in another one.
    Warnings:
        Scopes nested inside these are covered through their tables.
    """
    found_list: list[ast.AST] = []
    pending_list: list[ast.AST] = list(reversed(statements_list))
    while pending_list:
        node = pending_list.pop()
        if isinstance(node, DEFERRED_SCOPES_TUPLE):
            found_list.append(node)
            continue
        pending_list.extend(reversed(list(ast.iter_child_nodes(node))))
    return found_list


def list_tables_list(table_info: symtable.SymbolTable
                     ) -> list[symtable.SymbolTable]:
    """Every scope table in a module, depth first.

    Args:
        table_info (symtable.SymbolTable): The module table.
    Returns:
        list[symtable.SymbolTable]: The module table and all nested ones.
    Warnings:
        None.
    """
    tables_list = [table_info]
    for child_info in table_info.get_children():
        tables_list.extend(list_tables_list(child_info))
    return tables_list


def read_globals_set(node: ast.AST, tables_list: list) -> set[str]:
    """Module names a deferred scope (and scopes inside it) read.

    Args:
        node (ast.AST): def, class, lambda or generator expression.
        tables_list (list): All scope tables of the module.
    Returns:
        set[str]: Names the scope reads as globals.
    Warnings:
        Several lambdas on one line share a table key; all are included.
    """
    name_str = {ast.Lambda: "lambda", ast.GeneratorExp: "genexpr"}.get(
        type(node), getattr(node, "name", ""))
    names_set: set[str] = set()
    for table_info in tables_list:
        if table_info.get_name() == name_str and (
                table_info.get_lineno() == node.lineno):
            for inner_info in list_tables_list(table_info):
                names_set.update(
                    symbol.get_name() for symbol in inner_info.get_symbols()
                    if symbol.is_global() and symbol.is_referenced())
    return names_set


def is_rebound_elsewhere_bool(module_node: ast.Module, name_str: str,
                              plan_report: ExtractionPlan) -> bool:
    """Whether code outside the region could rebind a module name later.

    Args:
        module_node (ast.Module): Whole parsed source.
        name_str (str): Module name.
        plan_report (ExtractionPlan): Region lines.
    Returns:
        bool: True for an assignment, import, definition or deletion
            after the region, a global declaration anywhere outside it,
            a wildcard import after it, or a namespace call anywhere.
    Warnings:
        Rebinding from other modules cannot be seen here.
    """
    for node in ast.walk(module_node):
        outside_bool = not (plan_report.start_line
                            <= getattr(node, "lineno", 0)
                            <= plan_report.end_line)
        if isinstance(node, ast.Name) and (
                node.id in DYNAMIC_NAMESPACE_NAMES_TUPLE) or (
                isinstance(node, (ast.Global, ast.Nonlocal)) and outside_bool
                and name_str in node.names):
            return True
    suffix_node = ast.Module(body=[
        node for node in module_node.body
        if node.lineno > plan_report.end_line], type_ignores=[])
    if any(isinstance(node, ast.ImportFrom) and any(
            alias.name == "*" for alias in node.names)
           for node in ast.walk(suffix_node)):
        return True
    table_info = symtable.symtable(ast.unparse(suffix_node), "<suffix>",
                                   "exec")
    if name_str not in table_info.get_identifiers():
        return False
    symbol_info = table_info.lookup(name_str)
    return symbol_info.is_assigned() or symbol_info.is_imported()


LOCAL_SCOPES_TUPLE = (ast.ListComp, ast.SetComp, ast.DictComp,
                      ast.GeneratorExp, ast.Lambda)
CAPTURES_TUPLE = (ast.MatchAs, ast.MatchStar, ast.MatchMapping,
                  ast.ExceptHandler)
DEFINITIONS_TUPLE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
DEFERRED_SCOPES_TUPLE = (*DEFINITIONS_TUPLE, ast.Lambda, ast.GeneratorExp)
BLOCK_WALKERS_DICT = {
    ast.FunctionDef: walk_definition_set,
    ast.AsyncFunctionDef: walk_definition_set,
    ast.ClassDef: walk_definition_set,
    ast.If: walk_if_set, ast.For: walk_loop_set, ast.While: walk_loop_set,
    ast.Try: walk_try_set, ast.With: walk_with_set,
    ast.Match: walk_match_set, ast.Raise: walk_raise_set,
    ast.Assert: walk_raise_set,
}
