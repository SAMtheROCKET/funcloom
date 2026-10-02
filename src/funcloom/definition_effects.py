"""Decide whether defining a function or class can have side effects.

Defining a function evaluates its decorators, defaults and annotations; a
class statement also runs its whole body. Such definitions can only move
into separate modules, which are imported once and possibly never, when
nothing evaluated at definition time can print, register or change state.
"""

import ast

PURE_NODES_TUPLE = (ast.Constant, ast.Name, ast.Tuple, ast.List, ast.Load)


def is_pure_expression_bool(node: ast.AST | None) -> bool:
    """Tell whether evaluating an expression cannot have side effects.

    Args:
        node (ast.AST | None): Expression evaluated at definition time.
    Returns:
        bool: True for literal values, names and tuple/list construction.
    Warnings:
        Attributes, subscriptions, formatting, operators and container
        hashing may dispatch user code. Name lookup may still fail;
        binding analysis must separately establish availability.
    """
    if node is None:
        return True
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub)) and isinstance(
            node.operand, ast.Constant) and type(node.operand.value) in (
                int, float, complex)
    if not isinstance(node, PURE_NODES_TUPLE):
        return False
    return all(is_pure_expression_bool(child) for child in
               ast.iter_child_nodes(node))


def list_function_parts_list(node: ast.FunctionDef) -> list[ast.expr]:
    """List the expressions a def statement evaluates immediately.

    Args:
        node (ast.FunctionDef): Function or async function definition.
    Returns:
        list[ast.expr]: Defaults and annotations, not decorators.
    Warnings:
        The function body runs later, at call time, and is not included.
    """
    arguments_node = node.args
    parameters_list = [*arguments_node.posonlyargs, *arguments_node.args,
                       *arguments_node.kwonlyargs, arguments_node.vararg,
                       arguments_node.kwarg]
    return [
        *arguments_node.defaults, *filter(None, arguments_node.kw_defaults),
        *(
            parameter_node.annotation for parameter_node in parameters_list
            if parameter_node is not None
            and parameter_node.annotation is not None),
        *filter(None, [node.returns])]


def is_class_statement_pure_bool(node: ast.stmt) -> bool:
    """Tell whether one statement of a class body runs without effects.

    Args:
        node (ast.stmt): Statement directly inside a class body.
    Returns:
        bool: True for docstrings, pass, simple assignments of pure values
            and nested definitions that are themselves pure.
    Warnings:
        Loops, conditions, calls and anything else count as effects.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef)):
        return is_definition_effect_free_bool(node)
    if isinstance(node, ast.Pass) or isinstance(node, ast.Expr) and (
        isinstance(node.value, ast.Constant)
    ):
        return True
    if isinstance(node, ast.Assign):
        return all(
            isinstance(target_node, ast.Name) for target_node in node.targets
        ) and (
            is_pure_expression_bool(node.value)
            and not any(
                isinstance(part_node, ast.Name)
                for part_node in ast.walk(node.value)))
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and is_pure_expression_bool(
            node.annotation) and is_pure_expression_bool(node.value) and (
                node.value is None or not any(
                    isinstance(part_node, ast.Name)
                    for part_node in ast.walk(node.value)))
    return False


def is_definition_effect_free_bool(node: ast.stmt) -> bool:
    """Tell whether defining a function or class can have no side effects.

    Args:
        node (ast.stmt): Function, async function or class definition.
    Returns:
        bool: True when decorators, defaults, annotations, bases and the
            class body all evaluate without observable effects.
    Warnings:
        Only such definitions may move out of the original execution
        order; the others stay where they were written.
    """
    if node.decorator_list:
        return False
    if isinstance(node, ast.ClassDef):
        # Class construction can invoke metaclasses, __init_subclass__
        # and descriptor __set_name__. Spelling is not proof of purity.
        return not node.bases and not node.keywords and all(
            is_class_statement_pure_bool(statement_node)
            for statement_node in node.body)
    return all(is_pure_expression_bool(function_part_node)
               for function_part_node in list_function_parts_list(node))
