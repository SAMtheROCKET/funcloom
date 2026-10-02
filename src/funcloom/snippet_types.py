"""Conservative numeric type proposals, never runtime type verification."""

import ast

from funcloom.plan_analysis import (
    split_assignment_parts_tuple, split_statement_parts_tuple,
)
from funcloom.snippet_naming import (
    propose_mathematical_names_dict, record_name_questions_none,
)
from funcloom.snippet_models import (
    SnippetContext, SnippetQuestion, SnippetReport, SnippetValue,
)

NUMERIC_OPERATORS_TUPLE = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
)


def infer_numeric_type_str(
    expression_node: ast.expr, types_dict: dict[str, str | None],
) -> str | None:
    """Infer a narrow built-in numeric result under explicit assumptions.

    Args:
        expression_node (ast.expr): Unevaluated source expression.
        types_dict (dict): Proposed types for currently bound names.
    Returns:
        str | None: int, float, or unknown.
    Warnings:
        Overloads, power and non-numeric operations remain unresolved.
    """
    if isinstance(expression_node, ast.Constant):
        value_type = type(expression_node.value)
        return value_type.__name__ if value_type in (int, float) else None
    if isinstance(expression_node, ast.Name):
        return types_dict.get(expression_node.id)
    if isinstance(expression_node, ast.UnaryOp) and isinstance(
        expression_node.op, (ast.UAdd, ast.USub),
    ):
        return infer_numeric_type_str(expression_node.operand, types_dict)
    if isinstance(expression_node, ast.BinOp) and isinstance(
        expression_node.op, NUMERIC_OPERATORS_TUPLE,
    ):
        left_str = infer_numeric_type_str(expression_node.left, types_dict)
        right_str = infer_numeric_type_str(expression_node.right, types_dict)
        if left_str is not None and right_str is not None:
            if isinstance(expression_node.op, ast.Div) or (
                "float" in (left_str, right_str)
            ):
                return "float"
            return "int"
    return None


def reject_context_names_none(report_info: SnippetReport) -> None:
    """Reject context keys that do not identify the proposed contract.

    Args:
        report_info (SnippetReport): Base candidate and user context.
    Returns:
        None: Raises ValueError on misspellings and unsupported overrides.
    Warnings:
        Context cannot invent bindings or change which outputs are returned.
    """
    inputs_set = {input_info.name for input_info in report_info.plan.inputs}
    contract_set = inputs_set | {
        output_info.name for output_info in report_info.plan.outputs
    }
    context_info = report_info.context
    if set(context_info.input_types) - inputs_set:
        raise ValueError("input_types keys must name actual extracted inputs")
    if (set(context_info.names) | set(context_info.descriptions)
        ) - contract_set:
        raise ValueError("Context names must identify contract values")


def collect_types_tuple(
    module_node: ast.Module, report_info: SnippetReport,
) -> tuple[dict, dict, dict]:
    """Follow assignment order while retaining type changes across a region.

    Args:
        module_node (ast.Module): Original syntax, already subset checked.
        report_info (SnippetReport): Base plan and explicit input declarations.
    Returns:
        tuple: Input types, final types and observed per-name type sets.
    Warnings:
        Literal and arithmetic inference assumes exact built-in numeric types.
    """
    types_dict, input_types_dict, history_dict = {}, {}, {}
    for node in module_node.body:
        if node.lineno >= report_info.plan.start_line:
            break
        parts_tuple = split_assignment_parts_tuple(node, True)
        if parts_tuple is not None and parts_tuple[1] is not None:
            types_dict[parts_tuple[0].id] = infer_numeric_type_str(
                parts_tuple[1], types_dict,
            )
    direct_set = {
        name_resolution_info.name
        for name_resolution_info in report_info.plan.name_resolutions
        if name_resolution_info.status == "direct"}
    for input_info in report_info.plan.inputs:
        inferred_str = (
            types_dict.get(input_info.name) if input_info.name in direct_set
            else None)
        type_str = report_info.context.input_types.get(
            input_info.name, inferred_str,
        )
        types_dict[input_info.name] = input_types_dict[
            input_info.name] = type_str
        history_dict[input_info.name] = {type_str}
    for node in module_node.body:
        if node.lineno < report_info.plan.start_line:
            continue
        for name_str, type_str in propose_statement_types_list(
                node, types_dict):
            types_dict[name_str] = type_str
            history_dict.setdefault(name_str, set()).add(type_str)
    return input_types_dict, types_dict, history_dict


def propose_statement_types_list(
    statement_node: ast.stmt, types_dict: dict[str, str | None],
) -> list[tuple[str, str | None]]:
    """Propose a numeric type for each name a selected statement binds.

    Args:
        statement_node (ast.stmt): Supported selected statement.
        types_dict (dict): Proposed types for currently bound names.
    Returns:
        list[tuple]: Bound name and proposed type, or None when unknown.
    Warnings:
        Unpacked and mutated values are unknown; no call is resolved.
    """
    parts_tuple = split_statement_parts_tuple(statement_node)
    names_list = parts_tuple[1] if parts_tuple else []
    if isinstance(statement_node, ast.Assign) and all(
        isinstance(target_node, ast.Name)
        for target_node in statement_node.targets
    ):
        type_str = infer_numeric_type_str(statement_node.value, types_dict)
        return [(name_node.id, type_str) for name_node in names_list]
    if isinstance(statement_node, ast.AugAssign) and names_list:
        expression_node = ast.BinOp(
            ast.Name(names_list[0].id, ast.Load()), statement_node.op,
            statement_node.value,
        )
        return [(names_list[0].id,
                 infer_numeric_type_str(expression_node, types_dict))]
    return [(name_node.id, None) for name_node in names_list]


def propose_names_dict(
    history_dict: dict[str, set], context_info: SnippetContext,
    function_name_str: str, proposals_dict: dict[str, str],
) -> dict[str, str]:
    """Propose local dtype names and reject collisions rather than overwrite.

    Args:
        history_dict (dict): All observed types for each local identifier.
        context_info (SnippetContext): Optional explicit meaningful stems.
        function_name_str (str): Reserved generated function identifier.
        proposals_dict (dict): Optional neutral mathematical stems.
    Returns:
        dict[str, str]: One-to-one names for local tokens only.
    Warnings:
        Mixed or unknown types keep original or explicitly supplied names.
    """
    names_dict = {}
    used_set = {function_name_str}
    for name_str, types_set in history_dict.items():
        proposed_str = context_info.names.get(
            name_str, proposals_dict.get(name_str, name_str),
        )
        if len(types_set) == 1 and None not in types_set:
            type_str = next(iter(types_set))
            proposed_str = proposed_str.removesuffix("_int")
            proposed_str = proposed_str.removesuffix("_float")
            proposed_str += f"_{type_str}"
        if proposed_str in used_set:
            raise ValueError(f"Proposed local name collision: {proposed_str}")
        names_dict[name_str] = proposed_str
        used_set.add(proposed_str)
    return names_dict


def propose_values_none(
    module_node: ast.Module, report_info: SnippetReport,
) -> None:
    """Populate typed inputs/outputs and questions without changing source.

    Args:
        module_node (ast.Module): Base candidate syntax.
        report_info (SnippetReport): Contract and context destination.
    Returns:
        None: Records proposals with explicit unverified evidence.
    Warnings:
        An annotation neither converts values nor enforces runtime types.
    """
    reject_context_names_none(report_info)
    inputs_dict, final_dict, history_dict = collect_types_tuple(
        module_node, report_info,
    )
    names_dict = propose_names_dict(
        history_dict, report_info.context, report_info.plan.function_name,
        propose_mathematical_names_dict(module_node, report_info),
    )
    for role_str, facts_list, types_dict in (
        ("input", report_info.plan.inputs, inputs_dict),
        ("output", report_info.plan.outputs, final_dict),
    ):
        for fact_info in facts_list:
            report_info.values.append(label_proposed_value_info(
                fact_info.name, fact_info.line, names_dict[fact_info.name],
                types_dict.get(fact_info.name), role_str, report_info.context,
            ))
    record_type_questions_none(report_info)
    record_name_questions_none(report_info)
    report_info.assumptions.append(
        "Numeric annotations assume built-in int/float operations and normal "
        "completion. They do not convert values or validate inputs."
    )


def record_type_questions_none(report_info: SnippetReport) -> None:
    """Expose unresolved types once per name without inventing annotations.

    Args:
        report_info (SnippetReport): Proposed values and question destination.
    Returns:
        None: Appends focused optional clarification requests.
    Warnings:
        Unknown types do not become known merely because context is supplied.
    """
    recorded_set = set()
    for value_info in report_info.values:
        if value_info.annotation is None and (
                value_info.original_name not in recorded_set):
            report_info.questions.append(
                SnippetQuestion(
                    "SNIPTYPE", value_info.line,
                    f"What type is {value_info.original_name}? "
                    "The draft leaves its annotation unresolved.",))
            recorded_set.add(value_info.original_name)


def label_proposed_value_info(
    name_str: str, line_int: int, proposed_str: str, type_str: str | None,
    role_str: str, context_info: SnippetContext,
) -> SnippetValue:
    """Label the evidence behind a single input or output type proposal.

    Args:
        name_str (str): Original source identifier.
        line_int (int): Located contract evidence.
        proposed_str (str): Suggested local name.
        type_str (str | None): Proposed annotation, or unknown.
        role_str (str): Input or output.
        context_info (SnippetContext): Explicit type declarations.
    Returns:
        SnippetValue: A source-linked, unverified contract value.
    Warnings:
        Output inference depends on all relevant input type assumptions.
    """
    evidence_str = "numeric_inferred_unverified" if type_str else "unknown"
    if role_str == "input" and name_str in context_info.input_types:
        evidence_str = "context_declared_unverified"
    name_evidence_str = (
        "user_supplied" if name_str in context_info.names else
        "mathematical_role_proposal"
        if context_info.naming_mode == "mathematical" else "source_identifier"
    )
    return SnippetValue(
        name_str, proposed_str, type_str, evidence_str, role_str, line_int,
        name_evidence_str,
    )
