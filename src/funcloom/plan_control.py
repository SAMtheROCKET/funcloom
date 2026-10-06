"""Walk a selected region, including if/for/while blocks (M2b.8).

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
) -> None:
    """Derive inputs and outputs of a region with if/for/while blocks.

    Args:
        module_node (ast.Module): Whole parsed source.
        statements_list (list[ast.stmt]): Whole selected statements.
        bindings_info (ModuleBindings): Accepted prefix bindings.
        plan_report (ExtractionPlan): Contract and diagnostic accumulator.
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
        try, with, match, del and definitions stay refused (PLAN002).
    """
    if isinstance(statement_node, JUMPS_TUPLE):
        return definite_set
    if isinstance(statement_node, ast.If):
        if not check_expression_bool(statement_node.test, flow_info):
            return definite_set
        read_expressions_none([statement_node.test], definite_set, flow_info)
        body_set = walk_block_set(statement_node.body, set(definite_set),
                                  flow_info)
        else_set = walk_block_set(statement_node.orelse, set(definite_set),
                                  flow_info)
        return definite_set | (body_set & else_set)
    if isinstance(statement_node, (ast.For, ast.While)):
        walk_loop_none(statement_node, definite_set, flow_info)
        return definite_set
    return walk_simple_set(statement_node, definite_set, flow_info)


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
        statement_node (ast.stmt): Simple statement or if/for/while.
    Returns:
        list[ast.Name]: Assigned names in source order.
    Warnings:
        Comprehension variables are local and not listed.
    """
    if isinstance(statement_node, ast.If):
        blocks_list = [statement_node.body, statement_node.orelse]
        names_list = []
    elif isinstance(statement_node, (ast.For, ast.While)):
        blocks_list = [statement_node.body, statement_node.orelse]
        parts_tuple = (split_target_parts_tuple(statement_node.target)
                       if isinstance(statement_node, ast.For) else None)
        names_list = list(parts_tuple[1]) if parts_tuple else []
    else:
        parts_tuple = split_statement_parts_tuple(statement_node)
        return list(parts_tuple[1]) if parts_tuple else []
    for block_list in blocks_list:
        for inner_node in block_list:
            names_list.extend(list_written_names_list(inner_node))
    return names_list
