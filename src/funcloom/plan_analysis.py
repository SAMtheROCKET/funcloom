"""Bounded module-scope binding analysis for extraction review candidates."""

import ast

from funcloom.plan_bindings import DYNAMIC_NAMESPACE_NAMES_TUPLE
from funcloom.plan_models import (
    BindingFact, ExtractionPlan, ModuleBindings, append_issue_none,
)

FREE_NAME_STATUSES_TUPLE = ("builtin_lexical", "module_implicit")
ALLOWED_EXPRESSIONS_TUPLE = (
    ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.Call, ast.Attribute,
    ast.Subscript, ast.Slice, ast.Starred, ast.Compare, ast.BoolOp,
    ast.IfExp, ast.Tuple, ast.List, ast.Dict, ast.Set,
)
BINDING_KINDS_TUPLE = (
    "assignment", "augmented_assignment", "named_expression",
    "loop_target", "context_target", "import", "function_definition",
    "class_definition", "type_alias",
)


def find_expression_issue_str(expression_node: ast.expr) -> str | None:
    """Identify expressions beyond the deliberately small planning subset.

    Args:
        expression_node (ast.expr): Assignment value to inspect.
    Returns:
        str | None: A refusal reason, or no syntactic subset violation.
    Warnings:
        Accepted calls and operators can run any code; module code that
        could observe delayed writes is checked separately (PLAN008).
    """
    for child_node in ast.walk(expression_node):
        if isinstance(child_node, ast.Name) and (
            child_node.id in DYNAMIC_NAMESPACE_NAMES_TUPLE
        ):
            return (f"'{child_node.id}' depends on the calling frame or "
                    "namespace, which changes inside a function")
        if isinstance(child_node, ast.expr) and not isinstance(
            child_node, ALLOWED_EXPRESSIONS_TUPLE,
        ):
            kind_str = type(child_node).__name__
            return f"{kind_str} expressions need more analysis"
        if (
            isinstance(child_node, ast.Constant)
            and isinstance(child_node.value, (str, bytes))
            and child_node.end_lineno != child_node.lineno
        ):
            return "multiline string literals need token-aware relocation"
    return None


def split_assignment_parts_tuple(
    statement_node: ast.stmt, allow_annotation_bool: bool = False,
) -> tuple[ast.Name, ast.expr | None] | None:
    """Recognize a single plain-name assignment without guessing targets.

    Args:
        statement_node (ast.stmt): Statement to classify.
        allow_annotation_bool (bool): Permit declarations in the prefix.
    Returns:
        tuple | None: Name and value, or unsupported assignment structure.
    Warnings:
        Unpacking, chained assignments, and augmented writes are excluded.
    """
    if isinstance(statement_node, ast.Assign):
        if len(statement_node.targets) == 1 and isinstance(
            statement_node.targets[0], ast.Name,
        ):
            return statement_node.targets[0], statement_node.value
    if allow_annotation_bool and isinstance(statement_node, ast.AnnAssign):
        if isinstance(statement_node.target, ast.Name):
            return statement_node.target, statement_node.value
    return None


def split_target_parts_tuple(
    target_node: ast.expr,
) -> tuple[list[ast.expr], list[ast.Name]] | None:
    """Split an assignment target into expressions read and names bound.

    Args:
        target_node (ast.expr): Name, tuple/list of names, attribute or item.
    Returns:
        tuple | None: Read expressions and bound names, or unsupported.
    Warnings:
        Attribute and item targets mutate an object; they bind no name.
    """
    if isinstance(target_node, ast.Name):
        return [], [target_node]
    if isinstance(target_node, ast.Attribute):
        return [target_node.value], []
    if isinstance(target_node, ast.Subscript):
        return [target_node.value, target_node.slice], []
    if not isinstance(target_node, (ast.Tuple, ast.List)):
        return None
    names_list = [
        element.value if isinstance(element, ast.Starred) else element
        for element in target_node.elts
    ]
    if not all(isinstance(name_node, ast.Name) for name_node in names_list):
        return None
    return [], names_list


def split_statement_parts_tuple(
    statement_node: ast.stmt,
) -> tuple[list[ast.AST], list[ast.Name]] | None:
    """Return what a supported selected statement reads and binds.

    Args:
        statement_node (ast.stmt): Assignment, augmented assignment or
            expression statement.
    Returns:
        tuple | None: Read nodes and bound names, or an unsupported form.
    Warnings:
        A Name in the read list may be an augmented target (read first).
    """
    if isinstance(statement_node, ast.Expr):
        return [statement_node.value], []
    if isinstance(statement_node, ast.AugAssign):
        parts_tuple = split_target_parts_tuple(statement_node.target)
        if parts_tuple is None or isinstance(
            statement_node.target, (ast.Tuple, ast.List),
        ):
            return None
        reads_list, names_list = parts_tuple
        return [*names_list, *reads_list, statement_node.value], names_list
    if not isinstance(statement_node, ast.Assign):
        return None
    reads_list, names_list = [statement_node.value], []
    for target_node in statement_node.targets:
        parts_tuple = split_target_parts_tuple(target_node)
        if parts_tuple is None:
            return None
        reads_list.extend(parts_tuple[0])
        names_list.extend(parts_tuple[1])
    return reads_list, names_list


def read_names_list(read_nodes_list: list[ast.AST]) -> list[ast.Name]:
    """Flatten read expressions into names, keeping augmented targets.

    Args:
        read_nodes_list (list[ast.AST]): Nodes from statement_parts_tuple.
    Returns:
        list[ast.Name]: Name reads in the listed order.
    Warnings:
        Order within one statement does not affect input detection.
    """
    names_list: list[ast.Name] = []
    for node in read_nodes_list:
        names_list.extend([node] if isinstance(node, ast.Name)
                          else read_occurrences_list(node))
    return names_list


def read_occurrences_list(expression_node: ast.expr) -> list[ast.Name]:
    """List loaded names in source order for the supported expressions.

    Args:
        expression_node (ast.expr): A previously subset-checked expression.
    Returns:
        list[ast.Name]: Loaded names with original source locations.
    Warnings:
        This ordering is not a general execution model for arbitrary ASTs.
    """
    return sorted(
        (node for node in ast.walk(expression_node)
         if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)),
        key=lambda node: (node.lineno, node.col_offset),
    )


def make_binding_fact(
    name_str: str, line_int: int, bindings_info: ModuleBindings,
) -> BindingFact:
    """Attach only existing declared annotation evidence to a binding.

    Args:
        name_str (str): Python identifier.
        line_int (int): Source occurrence being reported.
        bindings_info (ModuleBindings): Existing declaration evidence.
    Returns:
        BindingFact: Unknown type or an explicitly unverified declaration.
    Warnings:
        A prior annotation may be stale after reassignment at runtime.
    """
    annotation_str = bindings_info.annotations.get(name_str)
    return BindingFact(
        name_str, line_int, annotation_str,
        "declared_unverified" if annotation_str is not None else "unknown",
    )


def record_prefix_annotations_dict(
    module_node: ast.Module, start_line_int: int,
) -> dict[str, str]:
    """Record top-level annotation declarations before the region.

    Args:
        module_node (ast.Module): Whole parsed source.
        start_line_int (int): First selected physical line.
    Returns:
        dict[str, str]: Name to annotation source text, unevaluated.
    Warnings:
        A declaration can be stale after reassignment; types are unverified.
    """
    annotations_dict: dict[str, str] = {}
    for statement_node in module_node.body:
        if statement_node.lineno >= start_line_int:
            break
        if isinstance(statement_node, ast.AnnAssign) and isinstance(
            statement_node.target, ast.Name,
        ):
            annotations_dict[statement_node.target.id] = ast.unparse(
                statement_node.annotation,
            )
    return annotations_dict


def resolve_prefix_bindings_info(
    module_node: ast.Module, plan_report: ExtractionPlan,
) -> ModuleBindings:
    """Accept selected reads whose lexical resolution is direct.

    Args:
        module_node (ast.Module): Whole parsed source.
        plan_report (ExtractionPlan): Region and binding resolutions.
    Returns:
        ModuleBindings: Direct names, statuses and declared annotations.
    Warnings:
        Any compilable prefix is allowed; it stays in place and is never
        moved. Only reads resolved as direct become function inputs.
    """
    bindings_info = ModuleBindings()
    bindings_info.annotations = record_prefix_annotations_dict(
        module_node, plan_report.start_line,
    )
    for resolution_info in plan_report.name_resolutions:
        bindings_info.statuses[resolution_info.name] = resolution_info
        if resolution_info.status != "direct":
            continue
        sites_list = [site for site in resolution_info.sites
                      if site.kind in BINDING_KINDS_TUPLE]
        bindings_info.bound[resolution_info.name] = make_binding_fact(
            resolution_info.name, sites_list[-1].line, bindings_info,
        )
    return bindings_info


def analyze_selection_none(
    statements_list: list[ast.stmt], bindings_info: ModuleBindings,
    plan_report: ExtractionPlan,
) -> None:
    """Derive region inputs and all assigned outputs in statement order.

    Args:
        statements_list (list[ast.stmt]): Whole selected module statements.
        bindings_info (ModuleBindings): Bindings from the supported prefix.
        plan_report (ExtractionPlan): Contract and diagnostic accumulator.
    Returns:
        None: Records each external read and each unique assigned name.
    Warnings:
        Returning all writes preserves names only; behavior needs review.
    """
    assigned_set: set[str] = set()
    inputs_set: set[str] = set()
    for statement_node in statements_list:
        parts_tuple = split_statement_parts_tuple(statement_node)
        if parts_tuple is None:
            append_issue_none(plan_report, "PLAN002", statement_node.lineno,
                              f"{type(statement_node).__name__} is outside "
                              "the supported statement forms.")
            continue
        reads_list, names_list = parts_tuple
        issue_str = next(filter(None, map(find_expression_issue_str, (
            node for node in reads_list if isinstance(node, ast.expr)
        ))), None)
        if issue_str is not None:
            append_issue_none(plan_report, "PLAN002", statement_node.lineno,
                              f"Unsupported value: {issue_str}.")
            continue
        record_inputs_none(read_names_list(reads_list), assigned_set,
                           inputs_set, bindings_info, plan_report)
        for name_node in names_list:
            if name_node.id not in assigned_set:
                plan_report.outputs.append(make_binding_fact(
                    name_node.id, name_node.lineno, bindings_info,
                ))
            assigned_set.add(name_node.id)


def record_inputs_none(
    names_list: list[ast.Name], assigned_set: set[str], inputs_set: set[str],
    bindings_info: ModuleBindings, plan_report: ExtractionPlan,
) -> None:
    """Track reads before region-local definitions, including builtin names.

    Args:
        names_list (list[ast.Name]): Names read by one statement.
        assigned_set (set[str]): Names already written in this region.
        inputs_set (set[str]): Names already recorded as inputs.
        bindings_info (ModuleBindings): Direct prefix bindings.
        plan_report (ExtractionPlan): Facts and refusal diagnostics.
    Returns:
        None: Appends inputs and reports unresolved reads.
    Warnings:
        A familiar spelling such as len is not proof of a builtin binding;
        only names with no module binding in syntax stay free names.
    """
    for name_node in names_list:
        if name_node.id in assigned_set or name_node.id in inputs_set:
            continue
        inputs_set.add(name_node.id)
        if is_free_name_bool(name_node.id, bindings_info):
            plan_report.assumptions.append(
                f"'{name_node.id}' stays a free name in the draft; like the "
                "original, it resolves to the builtin or module value then."
            )
            continue
        plan_report.inputs.append(make_binding_fact(
            name_node.id, name_node.lineno, bindings_info,
        ))
        if name_node.id not in bindings_info.bound:
            append_issue_none(plan_report, "PLAN003", name_node.lineno,
                              explain_unresolved_read_str(name_node.id,
                                                          bindings_info))


def is_free_name_bool(name_str: str, bindings_info: ModuleBindings) -> bool:
    """Decide whether a read can stay unparameterized inside the draft.

    Args:
        name_str (str): Name read by the region.
        bindings_info (ModuleBindings): Resolution evidence by name.
    Returns:
        bool: True for builtins and runner-set names with no module
            binding in syntax.
    Warnings:
        Lookup inside the function uses the same module globals and
        builtins, so the value is the one the original line would see.
    """
    resolution_info = bindings_info.statuses.get(name_str)
    return resolution_info is not None and resolution_info.status in (
        FREE_NAME_STATUSES_TUPLE
    )


def explain_unresolved_read_str(
        name_str: str, bindings_info: ModuleBindings) -> str:
    """Explain why a selected read cannot become a function input.

    Args:
        name_str (str): Name read by the selection.
        bindings_info (ModuleBindings): Resolution evidence by name.
    Returns:
        str: Refusal message including the lexical status when known.
    Warnings:
        Only a direct status is accepted for extraction inputs.
    """
    resolution_info = bindings_info.statuses.get(name_str)
    if resolution_info is None:
        return (f"Read of '{name_str}' has no resolved direct binding "
                "before the region.")
    return (f"Read of '{name_str}' is {resolution_info.status}, not "
            f"direct: {resolution_info.detail}")
