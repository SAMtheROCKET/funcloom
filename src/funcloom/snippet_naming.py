"""Source-grounded mathematical names and explicit domain clarification."""

import ast

from funcloom.plan_analysis import split_statement_parts_tuple
from funcloom.snippet_models import SnippetQuestion, SnippetReport

OPERATOR_NAMES_DICT = {
    ast.Add: "sum_value", ast.Sub: "difference_value",
    ast.Mult: "product_value", ast.Div: "quotient_value",
    ast.FloorDiv: "floor_quotient", ast.Mod: "remainder_value",
    ast.Pow: "power_value",
}


def propose_mathematical_names_dict(
    module_node: ast.Module, report_info: SnippetReport,
) -> dict[str, str]:
    """Propose neutral mathematical roles without assigning physical meaning.

    Args:
        module_node (ast.Module): Accepted source syntax.
        report_info (SnippetReport): Selection and input/output contract.
    Returns:
        dict[str, str]: Original identifiers mapped to proposed local stems.
    Warnings:
        These are syntax-based naming proposals, not verified numeric roles.
    """
    if report_info.context.naming_mode != "mathematical":
        return {}
    names_dict = {
        input_info.name: f"operand_{index_int}"
        for index_int, input_info in enumerate(report_info.plan.inputs, 1)}
    roles_dict = {}
    for node in module_node.body:
        if node.lineno < report_info.plan.start_line:
            continue
        for name_str, role_str in describe_statement_roles_list(node):
            roles_dict.setdefault(name_str, set()).add(role_str)
    used_set = set(names_dict.values())
    for output_info in report_info.plan.outputs:
        if output_info.name in names_dict:
            continue
        roles_set = roles_dict[output_info.name]
        stem_str = (next(iter(roles_set)) if len(roles_set) == 1
                    else "intermediate_value")
        proposal_str, counter_int = stem_str, 2
        while proposal_str in used_set:
            proposal_str = f"{stem_str}_{counter_int}"
            counter_int += 1
        names_dict[output_info.name] = proposal_str
        used_set.add(proposal_str)
    return names_dict


def describe_statement_roles_list(
    statement_node: ast.stmt,
) -> list[tuple[str, str]]:
    """Describe the role of each name a selected statement binds.

    Args:
        statement_node (ast.stmt): Supported selected statement.
    Returns:
        list[tuple[str, str]]: Name and neutral mathematical role.
    Warnings:
        Roles come from syntax only and carry no domain meaning.
    """
    parts_tuple = split_statement_parts_tuple(statement_node)
    names_list = parts_tuple[1] if parts_tuple else []
    if isinstance(statement_node, ast.Assign) and all(
        isinstance(target_node, ast.Name)
        for target_node in statement_node.targets
    ):
        role_str = describe_expression_role_str(statement_node.value)
    elif isinstance(statement_node, ast.AugAssign):
        role_str = OPERATOR_NAMES_DICT.get(type(statement_node.op),
                                           "updated_value")
    else:
        role_str = "unpacked_value"
    return [(name_node.id, role_str) for name_node in names_list]


def describe_expression_role_str(value_node: ast.expr) -> str:
    """Describe the outer expression shape with neutral mathematical wording.

    Args:
        value_node (ast.expr): Unevaluated assigned expression.
    Returns:
        str: Proposed role with no business meaning or units.
    Warnings:
        Operators may overload; the role remains an unverified suggestion.
    """
    if isinstance(value_node, ast.BinOp):
        return OPERATOR_NAMES_DICT.get(type(value_node.op), "combined_value")
    if isinstance(value_node, ast.UnaryOp):
        return {ast.USub: "negated_value", ast.UAdd: "positive_value"}.get(
            type(value_node.op), "transformed_value",
        )
    return "assigned_value"


def record_name_questions_none(report_info: SnippetReport) -> None:
    """Ask for meaning when short names or domain documentation are unresolved.

    Args:
        report_info (SnippetReport): Proposed contract and explicit context.
    Returns:
        None: Adds optional review questions, once per original identifier.
    Warnings:
        Source spellings and dtype suffixes do not establish domain meaning.
    """
    context_info = report_info.context
    recorded_set = set()
    for value_info in report_info.values:
        name_str = value_info.original_name
        if name_str in recorded_set:
            continue
        recorded_set.add(name_str)
        missing_name_bool = len(name_str) == 1 and (
            name_str not in context_info.names
            or len(context_info.names[name_str]) == 1
        )
        missing_description_bool = context_info.naming_mode == "domain" and (
            not context_info.descriptions.get(name_str, "").strip()
        )
        if context_info.naming_mode != "mathematical" and (
            missing_name_bool or missing_description_bool
        ):
            report_info.questions.append(SnippetQuestion(
                "SNIPNAME", value_info.line,
                f"What does '{name_str}' represent? Supply a descriptive "
                "name and meaning, or choose mathematical naming.",
                ("Provide names/descriptions", "Use naming_mode=mathematical"),
            ))
