"""Infer type hints only where a value's type is certain from syntax."""

import ast

BUILTIN_RESULTS_DICT = {
    "len": "int", "str": "str", "int": "int", "float": "float",
    "bool": "bool", "list": "list", "dict": "dict", "set": "set",
    "tuple": "tuple", "frozenset": "frozenset", "bytes": "bytes",
    "sorted": "list", "repr": "str", "range": "range", "ord": "int",
    "chr": "str", "hex": "str", "bin": "str", "oct": "str", "any": "bool",
    "all": "bool", "isinstance": "bool", "issubclass": "bool",
    "callable": "bool", "hasattr": "bool", "input": "str",
}
DISPLAYS_DICT = {
    ast.List: "list", ast.ListComp: "list", ast.Dict: "dict",
    ast.DictComp: "dict", ast.Set: "set", ast.SetComp: "set",
    ast.Tuple: "tuple", ast.JoinedStr: "str",
}
NUMBERS_TUPLE = ("bool", "int", "float")
SCALARS_TUPLE = ("bool", "int", "float", "str", "bytes", "None")
SEQUENCE_ADD_TUPLE = ("str", "bytes", "list", "tuple")


def name_constant_type_str(constant_value: object) -> str | None:
    """Name the type of a literal constant.

    Args:
        constant_value (object): Constant value from the syntax tree.
    Returns:
        str | None: Type name, or None for Ellipsis.
    Warnings:
        bool is checked before int because bool is a subclass of int.
    """
    for type_value in (bool, int, float, complex, str, bytes):
        if type(constant_value) is type_value:
            return type_value.__name__
    return "None" if constant_value is None else None


def infer_binary_type_str(
    operator_node: ast.operator, left_str: str | None, right_str: str | None,
) -> str | None:
    """Infer the result of a binary operation on known builtin types.

    Args:
        operator_node (ast.operator): Operator.
        left_str (str | None): Left operand type.
        right_str (str | None): Right operand type.
    Returns:
        str | None: Result type for numbers and sequences, else None.
    Warnings:
        Unknown or user-defined operand types give None.
    """
    if isinstance(operator_node, ast.Pow):
        return None
    if left_str in NUMBERS_TUPLE and right_str in NUMBERS_TUPLE:
        if isinstance(operator_node, ast.Div) or "float" in (left_str,
                                                             right_str):
            return "float"
        if isinstance(operator_node, (ast.Add, ast.Sub, ast.Mult,
                                      ast.FloorDiv, ast.Mod)):
            return "int"
        return None
    if isinstance(operator_node, ast.Add) and left_str == right_str and (
        left_str in SEQUENCE_ADD_TUPLE
    ):
        return left_str
    if isinstance(operator_node, ast.Mult) and (
        {left_str, right_str} in ({"str", "int"}, {"list", "int"},
                                  {"tuple", "int"})
    ):
        return next(
            operand_type_str for operand_type_str in (left_str, right_str)
            if operand_type_str != "int")
    return None


def infer_expression_type_str(
    node: ast.expr, known_dict: dict[str, str | None], trusted_set: set,
) -> str | None:
    """Infer an expression's type when it is certain from syntax.

    Args:
        node (ast.expr): Expression.
        known_dict (dict): Known types of names.
        trusted_set (set): Builtins and classes whose names are not rebound.
    Returns:
        str | None: Type annotation text, or None when unknown.
    Warnings:
        Operators and comparisons count only on builtin operand types.
    """
    if isinstance(node, ast.Constant):
        return name_constant_type_str(node.value)
    if type(node) in DISPLAYS_DICT:
        return DISPLAYS_DICT[type(node)]
    if isinstance(node, ast.Name):
        return known_dict.get(node.id)
    if isinstance(node, ast.UnaryOp):
        operand_str = infer_expression_type_str(node.operand, known_dict,
                                                trusted_set)
        if isinstance(node.op, ast.Not):
            return "bool"
        return ("int" if operand_str == "bool" else operand_str) if (
            operand_str in NUMBERS_TUPLE) else None
    if isinstance(node, ast.BinOp):
        return infer_binary_type_str(
            node.op,
            infer_expression_type_str(node.left, known_dict, trusted_set),
            infer_expression_type_str(node.right, known_dict, trusted_set))
    return infer_compound_type_str(node, known_dict, trusted_set)


def infer_compound_type_str(
    node: ast.expr, known_dict: dict[str, str | None], trusted_set: set,
) -> str | None:
    """Infer types of calls, comparisons and conditional expressions.

    Args:
        node (ast.expr): Expression.
        known_dict (dict): Known types of names.
        trusted_set (set): Builtins and classes that are not rebound.
    Returns:
        str | None: Type annotation text, or None when unknown.
    Warnings:
        Class constructors are quoted so the annotation is never evaluated.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and (
        node.func.id in trusted_set
    ):
        name_str = node.func.id
        return BUILTIN_RESULTS_DICT.get(name_str, f"'{name_str}'")
    if isinstance(node, ast.Compare):
        types_list = [
            infer_expression_type_str(operand_node, known_dict, trusted_set)
            for operand_node in [node.left, *node.comparators]]
        return ("bool" if all(type_str in SCALARS_TUPLE
                              for type_str in types_list) else None)
    if isinstance(node, ast.IfExp):
        body_str = infer_expression_type_str(
            node.body, known_dict, trusted_set)
        return body_str if body_str == infer_expression_type_str(
            node.orelse, known_dict, trusted_set) else None
    return None


def update_statement_types_none(
    node: ast.stmt, known_dict: dict[str, str | None], trusted_set: set,
    writes_set: set[str],
) -> None:
    """Update known types after one statement runs.

    Args:
        node (ast.stmt): Statement.
        known_dict (dict): Types before the statement, updated in place.
        trusted_set (set): Builtins and classes that are not rebound.
        writes_set (set[str]): Every name the statement binds.
    Returns:
        None: Plain assignments set types; other bindings forget them.
    Warnings:
        Loops, unpacking, with targets and nested writes become unknown.
    """
    certain_dict: dict[str, str | None] = {}
    if isinstance(node, ast.Assign) and all(
        isinstance(target_node, ast.Name) for target_node in node.targets
    ):
        type_str = infer_expression_type_str(
            node.value, known_dict, trusted_set)
        certain_dict = {
            target_node.id: type_str for target_node in node.targets}
    elif isinstance(node, ast.AnnAssign) and node.value is not None and (
        isinstance(node.target, ast.Name)
    ):
        certain_dict = {node.target.id: infer_expression_type_str(
            node.value, known_dict, trusted_set)}
    elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        certain_dict = {node.target.id: infer_binary_type_str(
            node.op, known_dict.get(node.target.id),
            infer_expression_type_str(node.value, known_dict, trusted_set))}
    for name_str in writes_set:
        known_dict[name_str] = certain_dict.get(name_str)


def list_trusted_names_set(
    bound_set: set[str], class_nodes_list: list[ast.ClassDef],
) -> set[str]:
    """List builtins and classes whose calls give a known type.

    Args:
        bound_set (set[str]): Names bound anywhere in the program.
        class_nodes_list (list[ast.ClassDef]): Classes defined once.
    Returns:
        set[str]: Callable names safe to use for inference.
    Warnings:
        Classes with bases, __new__, metaclasses or decorators are excluded.
    """
    classes_set = {
        node.name for node in class_nodes_list
        if not node.bases and not node.decorator_list and not node.keywords
        and not any(
            isinstance(statement_node, ast.FunctionDef)
            and statement_node.name == "__new__"
            for statement_node in node.body)}
    return (set(BUILTIN_RESULTS_DICT) - bound_set) | classes_set


def write_return_annotation_str(
        names_list: list[str], types_dict: dict) -> str:
    """Write a return annotation for returned names, when all are known.

    Args:
        names_list (list[str]): Returned names, in order.
        types_dict (dict): Known types by name.
    Returns:
        str: " -> T", " -> tuple[...]", " -> None" or empty.
    Warnings:
        One unknown type leaves the whole return unannotated.
    """
    types_list = [types_dict.get(name_str) for name_str in names_list]
    if not names_list:
        return " -> None"
    if not all(types_list):
        return ""
    if len(types_list) == 1:
        return f" -> {types_list[0]}"
    return f" -> tuple[{', '.join(types_list)}]"
