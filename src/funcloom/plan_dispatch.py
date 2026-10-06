"""Check whether module code run during a region can see delayed writes."""

import ast
from dataclasses import dataclass, field

from funcloom.plan_bindings import (
    DYNAMIC_NAMESPACE_NAMES_TUPLE, list_definition_time_nodes_list,
)
from funcloom.plan_control import list_written_names_list
from funcloom.plan_models import ExtractionPlan, append_issue_none

DEFERRED_SCOPES_TUPLE = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.GeneratorExp,
)
IMMEDIATE_SCOPES_TUPLE = (ast.ClassDef, ast.ListComp, ast.SetComp,
                          ast.DictComp)
DISPATCH_NODES_TUPLE = (
    ast.Call, ast.Attribute, ast.Subscript, ast.BinOp, ast.UnaryOp,
    ast.Compare, ast.BoolOp, ast.IfExp,
)
CAPTURE_NODES_TUPLE = (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)


@dataclass
class ScopeNames:
    """Names one scope reads, binds and declares, without nested bodies."""

    loads: set[str] = field(default_factory=set)
    stores: set[str] = field(default_factory=set)
    globals: set[str] = field(default_factory=set)
    nested: list[ast.AST] = field(default_factory=list)
    dynamic_line: int | None = None


@dataclass
class ModuleCodeFacts:
    """Globals that deferred module code may read or rebind when it runs."""

    reads: dict[str, int] = field(default_factory=dict)
    writes: dict[str, int] = field(default_factory=dict)
    dynamic_line: int | None = None


def list_scope_parameters_set(scope_node: ast.AST) -> set[str]:
    """List parameter names of a function or lambda scope.

    Args:
        scope_node (ast.AST): Any scope node.
    Returns:
        set[str]: Parameter names, empty for classes and comprehensions.
    Warnings:
        Default values are evaluated in the enclosing scope, not here.
    """
    arguments_node = getattr(scope_node, "args", None)
    if not isinstance(arguments_node, ast.arguments):
        return set()
    parameters_list = [
        *arguments_node.posonlyargs, *arguments_node.args,
        *arguments_node.kwonlyargs, arguments_node.vararg,
        arguments_node.kwarg,
    ]
    return {
        parameter_node.arg for parameter_node in parameters_list
        if parameter_node is not None}


def list_enclosing_parts_list(scope_node: ast.AST) -> list[ast.AST]:
    """Return a scope's parts evaluated by the enclosing scope.

    Args:
        scope_node (ast.AST): Function, lambda, class or comprehension.
    Returns:
        list[ast.AST]: Decorators, defaults, bases or the first iterable.
    Warnings:
        These run when the definition or comprehension is evaluated.
    """
    if hasattr(scope_node, "generators"):
        return [scope_node.generators[0].iter]
    return list_definition_time_nodes_list(scope_node)


def list_scope_body_list(scope_node: ast.AST) -> list[ast.AST]:
    """Return the syntax that executes inside a scope's own namespace.

    Args:
        scope_node (ast.AST): Function, lambda, class or comprehension.
    Returns:
        list[ast.AST]: Body statements or expressions.
    Warnings:
        Decorators, defaults and bases belong to the enclosing scope.
    """
    if isinstance(scope_node, ast.Lambda):
        return [scope_node.body]
    if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
        return list(scope_node.body)
    parts_list = [getattr(scope_node, name_str) for name_str in
                  ("elt", "key", "value") if hasattr(scope_node, name_str)]
    return parts_list + list(scope_node.generators)


def record_name_none(node: ast.AST, names_info: ScopeNames) -> None:
    """Classify one syntax node's effect on a scope's name sets.

    Args:
        node (ast.AST): Syntax inside a scope, outside nested bodies.
        names_info (ScopeNames): Accumulator for this scope.
    Returns:
        None: Updates loads, stores, globals and dynamic evidence.
    Warnings:
        Namespace calls are detected by spelling only.
    """
    if isinstance(node, ast.Name):
        target_set = (names_info.loads if isinstance(node.ctx, ast.Load)
                      else names_info.stores)
        target_set.add(node.id)
        if node.id in DYNAMIC_NAMESPACE_NAMES_TUPLE and (
            names_info.dynamic_line is None
        ):
            names_info.dynamic_line = node.lineno
    elif isinstance(node, ast.Global):
        names_info.globals.update(node.names)
    elif isinstance(node, ast.alias):
        names_info.stores.add(node.asname or node.name.split(".")[0])
    elif isinstance(node, CAPTURE_NODES_TUPLE) and node.name:
        names_info.stores.add(node.name)
    elif isinstance(node, ast.MatchMapping) and node.rest:
        names_info.stores.add(node.rest)


def collect_scope_names_info(scope_node: ast.AST) -> ScopeNames:
    """Collect one scope's names while treating nested scopes separately.

    Args:
        scope_node (ast.AST): Function, lambda, class or comprehension.
    Returns:
        ScopeNames: Own loads, stores, globals and nested scope nodes.
    Warnings:
        Nested definitions' decorators and defaults count as own reads.
    """
    names_info = ScopeNames(stores=list_scope_parameters_set(scope_node))
    pending_list = list_scope_body_list(scope_node)
    while pending_list:
        node = pending_list.pop()
        if isinstance(node, (*DEFERRED_SCOPES_TUPLE,
                             *IMMEDIATE_SCOPES_TUPLE)):
            names_info.nested.append(node)
            if hasattr(node, "name"):
                names_info.stores.add(node.name)
            pending_list.extend(list_enclosing_parts_list(node))
            continue
        record_name_none(node, names_info)
        pending_list.extend(ast.iter_child_nodes(node))
    return names_info


def collect_scope_facts_none(
    scope_node: ast.AST, visible_set: set[str], deferred_bool: bool,
    facts_info: ModuleCodeFacts,
) -> None:
    """Record globals a scope can touch, then descend into nested scopes.

    Args:
        scope_node (ast.AST): Scope to analyze.
        visible_set (set[str]): Enclosing function locals (closures).
        deferred_bool (bool): Whether this code can run after definition.
        facts_info (ModuleCodeFacts): Module-wide accumulator.
    Returns:
        None: Adds read, write and dynamic evidence with source lines.
    Warnings:
        Closure variables are approximated; unknown cases count as global.
    """
    deferred_bool = deferred_bool or isinstance(scope_node,
                                                DEFERRED_SCOPES_TUPLE)
    names_info = collect_scope_names_info(scope_node)
    locals_set = names_info.stores - names_info.globals
    if deferred_bool:
        for name_str in (names_info.loads - locals_set) - visible_set:
            facts_info.reads.setdefault(name_str, scope_node.lineno)
        for name_str in names_info.globals:
            facts_info.writes.setdefault(name_str, scope_node.lineno)
            facts_info.reads.setdefault(name_str, scope_node.lineno)
        if names_info.dynamic_line is not None and (
            facts_info.dynamic_line is None
        ):
            facts_info.dynamic_line = names_info.dynamic_line
    inner_visible_set = (visible_set if isinstance(scope_node, ast.ClassDef)
                         else visible_set | locals_set)
    for nested_node in names_info.nested:
        collect_scope_facts_none(nested_node, inner_visible_set,
                                 deferred_bool, facts_info)


def gather_module_code_facts_info(
    module_node: ast.Module, start_line_int: int,
) -> ModuleCodeFacts:
    """Gather globals used by deferred code defined before a region.

    Args:
        module_node (ast.Module): Whole parsed source.
        start_line_int (int): First selected physical line.
    Returns:
        ModuleCodeFacts: Reads, rebinding declarations and dynamic use.
    Warnings:
        Code defined in other modules is not analyzed; it can reach this
        module's globals only reflectively, which remains unresolved.
    """
    facts_info = ModuleCodeFacts()
    for statement_node in module_node.body:
        if statement_node.lineno >= start_line_int:
            break
        pending_list = [statement_node]
        while pending_list:
            node = pending_list.pop()
            if isinstance(node, (*DEFERRED_SCOPES_TUPLE,
                                 *IMMEDIATE_SCOPES_TUPLE)):
                collect_scope_facts_none(node, set(), False, facts_info)
                pending_list.extend(list_enclosing_parts_list(node))
                continue
            pending_list.extend(ast.iter_child_nodes(node))
    return facts_info


def dispatch_lines_list(statements_list: list[ast.stmt]) -> list[int]:
    """Find selected statements whose evaluation can run arbitrary code.

    Args:
        statements_list (list[ast.stmt]): Selected assignments.
    Returns:
        list[int]: Statement indexes containing calls or dispatch syntax.
    Warnings:
        Operators and attribute access can call user-defined methods.
    """
    return [index_int for index_int, statement_node in
            enumerate(statements_list)
            if any(isinstance(node, DISPATCH_NODES_TUPLE)
                   for node in ast.walk(statement_node))]


def check_dispatch_none(
    module_node: ast.Module, statements_list: list[ast.stmt],
    plan_report: ExtractionPlan,
) -> None:
    """Refuse regions where module code could observe delayed bindings.

    Args:
        module_node (ast.Module): Whole parsed source.
        statements_list (list[ast.stmt]): Selected assignments.
        plan_report (ExtractionPlan): Contract and diagnostic destination.
    Returns:
        None: Appends PLAN008 diagnostics for each detected hazard.
    Warnings:
        Inside the draft, selected writes reach module globals only after
        the function returns; reflection by other modules is unresolved.
    """
    dispatch_list = dispatch_lines_list(statements_list)
    if not dispatch_list:
        return
    facts_info = gather_module_code_facts_info(
        module_node, plan_report.start_line)
    first_line_int = statements_list[dispatch_list[0]].lineno
    if facts_info.dynamic_line is not None:
        append_issue_none(plan_report, "PLAN008", first_line_int, (
            f"Module code at line {facts_info.dynamic_line} uses a dynamic "
            "namespace call, so code run here could read or rebind any "
            "global the draft changes."
        ))
    contract_set = {input_info.name for input_info in plan_report.inputs} | {
        output_info.name for output_info in plan_report.outputs
    }
    for name_str in sorted(set(facts_info.writes) & contract_set):
        append_issue_none(plan_report, "PLAN008", first_line_int, (
            f"Module code at line {facts_info.writes[name_str]} declares "
            f"'global {name_str}', so a call here could rebind a value the "
            "draft passes in or returns."
        ))
    check_delayed_reads_none(statements_list, dispatch_list, facts_info,
                             plan_report)


def check_delayed_reads_none(
    statements_list: list[ast.stmt], dispatch_list: list[int],
    facts_info: ModuleCodeFacts, plan_report: ExtractionPlan,
) -> None:
    """Refuse module-code reads of names written earlier in the region.

    Args:
        statements_list (list[ast.stmt]): Selected assignments.
        dispatch_list (list[int]): Indexes of statements that run code.
        facts_info (ModuleCodeFacts): Globals read by deferred code.
        plan_report (ExtractionPlan): Diagnostic destination.
    Returns:
        None: Appends one PLAN008 diagnostic per affected name.
    Warnings:
        A read in the same statement as the write happens before it.
    """
    first_write_dict: dict[str, int] = {}
    for index_int, statement_node in enumerate(statements_list):
        for name_node in list_written_names_list(statement_node):
            first_write_dict.setdefault(name_node.id, index_int)
    for name_str, write_index_int in first_write_dict.items():
        later_list = [index_int for index_int in dispatch_list
                      if index_int > write_index_int]
        if name_str in facts_info.reads and later_list:
            append_issue_none(
                plan_report, "PLAN008",
                statements_list[later_list[0]].lineno, (
                    f"Module code at line {facts_info.reads[name_str]} "
                    f"reads global '{name_str}', which the region assigns "
                    "earlier; inside the draft that write is not visible "
                    "until return."
                ),
            )
