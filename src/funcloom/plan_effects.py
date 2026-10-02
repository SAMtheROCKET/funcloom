"""Partial syntax-based effect inventory without executing target code."""

import ast
from collections.abc import Iterator

from funcloom.plan_models import EffectFact, ExtractionPlan

SCOPE_BOUNDARIES_TUPLE = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)
CONTROL_BOUNDARIES_TUPLE = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
    ast.Try, ast.TryStar, ast.Match, ast.IfExp, ast.BoolOp,
)
NODE_EFFECTS_DICT = {
    ast.Call: ("call", "Call target, side effects and exceptions unresolved."),
    ast.BinOp: ("operator", "Operator may dispatch user code or raise."),
    ast.UnaryOp: ("operator", "Operator may dispatch user code or raise."),
    ast.Compare: ("operator", "Comparison may dispatch user code or raise."),
    ast.AugAssign: (
        "augmented_assignment", "Reads then writes; in-place mutation and "
        "alias effects depend on runtime values.",
    ),
    ast.Import: ("import", "Import loading and module effects unresolved."),
    ast.ImportFrom: (
        "import", "Import loading and module effects unresolved.",
    ),
    ast.AnnAssign: (
        "annotation", "Annotation evaluation depends on scope, interpreter "
        "and future flags; runtime type is unverified.",
    ),
    ast.Raise: ("raise", "Explicit exception path; outcome unresolved."),
    ast.Assert: ("assert", "Assertion evaluation depends on optimization."),
    ast.Delete: ("delete", "Deletes a binding or an object member."),
    ast.NamedExpr: ("named_expression", "Expression also writes a binding."),
}
EFFECT_LIMITATIONS_TUPLE = (
    "Partial syntax inventory of prefix and selection; suffix not analyzed.",
    "Scope boundaries are opaque, including decorators, defaults, class "
    "execution and comprehension iteration; their effects are unresolved.",
    "No reachability, call resolution, alias graph or exception-flow proof.",
    "Fact order is source order, not execution order. Missing facts do not "
    "establish purity; reflection, lifetimes and implicit effects remain.",
)


def visit_effect_nodes_iterable(root_node: ast.AST) -> Iterator[ast.AST]:
    """Visit syntax while keeping nested execution scopes opaque.

    Args:
        root_node (ast.AST): One complete module-level statement.
    Returns:
        Iterator[ast.AST]: Nodes including, but not inside, scope boundaries.
    Warnings:
        Does not model execution order or evaluate definition-time effects.
    """
    pending_list = [root_node]
    while pending_list:
        current_node = pending_list.pop()
        yield current_node
        if not isinstance(current_node, SCOPE_BOUNDARIES_TUPLE):
            pending_list.extend(reversed(list(
                ast.iter_child_nodes(current_node),
            )))


def classify_node_effect_tuple(node: ast.AST) -> tuple[str, str] | None:
    """Classify possible effects without inferring runtime types or targets.

    Args:
        node (ast.AST): Syntax occurrence in the bounded inventory.
    Returns:
        tuple | None: Effect kind and explanation, when recognized.
    Warnings:
        Unclassified syntax is not proven effect-free.
    """
    if isinstance(node, SCOPE_BOUNDARIES_TUPLE):
        return "scope_boundary", (
            f"{type(node).__name__} scope and definition/iteration effects "
            "are unresolved; descendants are not inventoried."
        )
    if isinstance(node, CONTROL_BOUNDARIES_TUPLE):
        return "control_flow", (
            "Branch, iteration, truth testing or context/exception handling "
            "needs path-sensitive analysis."
        )
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        operation_str = type(node.ctx).__name__
        return "object_access", (
            f"{operation_str} on {type(node).__name__} may invoke user "
            "code or raise; mutation and aliases are unresolved."
        )
    return NODE_EFFECTS_DICT.get(type(node))


def append_effect_none(
    node: ast.AST, region_str: str, effect_tuple: tuple[str, str],
    plan_report: ExtractionPlan,
) -> None:
    """Attach an original source span to a syntactic effect observation.

    Args:
        node (ast.AST): Located statement or expression.
        region_str (str): Prefix or selection.
        effect_tuple (tuple): Effect category and explanation.
        plan_report (ExtractionPlan): Evidence destination.
    Returns:
        None: Appends a fact without changing candidate eligibility.
    Warnings:
        Columns are zero-based UTF-8 byte offsets, with exclusive ends.
    """
    plan_report.effects.append(EffectFact(
        effect_tuple[0], node.lineno, node.col_offset,
        node.end_lineno, node.end_col_offset, region_str, effect_tuple[1],
    ))


def record_assignment_effects_none(
    node: ast.AST, region_str: str, plan_report: ExtractionPlan,
) -> None:
    """Record direct alias syntax and delayed publication of selected names.

    Args:
        node (ast.AST): Syntax occurrence, possibly an assignment.
        region_str (str): Prefix or selection.
        plan_report (ExtractionPlan): Partial evidence destination.
    Returns:
        None: Records risks for ordinary single-name assignments.
    Warnings:
        An alias fact is not a resolved alias graph or mutability claim.
    """
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return
    target_node = node.targets[0]
    if not isinstance(target_node, ast.Name):
        return
    if isinstance(node.value, ast.Name):
        append_effect_none(node, region_str, ("alias", (
            f"{target_node.id} = {node.value.id} shares a value if reached; "
            "mutability and later alias relationships are unresolved."
        )), plan_report)
    if region_str == "selection":
        append_effect_none(node, region_str, ("binding_visibility", (
            f"{target_node.id} would become function-local; caller writes "
            "occur only after return, changing partial-failure visibility."
        )), plan_report)


def record_effect_inventory_none(
    module_node: ast.Module, statements_list: list[ast.stmt],
    plan_report: ExtractionPlan,
) -> None:
    """Inventory prefix and selection syntax before subset refusal checks.

    Args:
        module_node (ast.Module): Contextually compiled source tree.
        statements_list (list): Complete selected module statements.
        plan_report (ExtractionPlan): Report receiving located evidence.
    Returns:
        None: Adds partial facts; never approves additional transformations.
    Warnings:
        Definitions and comprehensions remain opaque, not effects-free.
    """
    plan_report.effect_analysis = "partial"
    plan_report.effect_limitations = list(EFFECT_LIMITATIONS_TUPLE)
    selected_ids_set = {id(node) for node in statements_list}
    for statement_node in module_node.body:
        if statement_node.lineno > plan_report.end_line:
            break
        region_str = (
            "selection" if id(statement_node) in selected_ids_set else "prefix"
        )
        for node in visit_effect_nodes_iterable(statement_node):
            effect_tuple = classify_node_effect_tuple(node)
            if effect_tuple is not None:
                append_effect_none(node, region_str, effect_tuple, plan_report)
            record_assignment_effects_none(node, region_str, plan_report)
    plan_report.effects.sort(key=lambda effect_info: (
        effect_info.line, effect_info.column_utf8, effect_info.kind,
    ))
