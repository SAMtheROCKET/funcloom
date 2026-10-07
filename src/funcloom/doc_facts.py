"""Facts a function body shows, for generated docstrings.

Everything here is read from the syntax only: which files, data formats,
databases and web services the body visibly uses, what it loops over,
how each parameter is used and what it returns. Nothing is run or
guessed; when the body shows nothing, the caller falls back to a plain
"not described" text.
"""

import ast

# Facts by the called name's last part; "{0}" is the first argument.
CALL_FACTS_DICT = {
    "open": "opens {0}", "DictReader": "reads CSV rows",
    "reader": "reads CSV rows", "writer": "writes CSV rows",
    "DictWriter": "writes CSV rows", "read_csv": "reads a CSV table",
    "read_excel": "reads an Excel sheet", "read_parquet": "reads a Parquet "
    "table", "read_json": "reads a JSON table", "to_csv": "saves a CSV file",
    "to_excel": "saves an Excel file", "to_parquet": "saves a Parquet file",
    "load": "loads saved data", "dump": "saves data", "loads": "parses text",
    "connect": "connects to a database", "execute": "runs SQL",
    "executemany": "runs SQL", "commit": "commits to the database",
    "savefig": "saves a figure", "makedirs": "creates folder {0}",
    "mkdir": "creates a folder", "listdir": "lists the files of {0}",
    "glob": "finds files", "raise_for_status": "checks the HTTP status",
}
WEB_MODULES_TUPLE = ("requests", "httpx", "urllib", "aiohttp")
LITERAL_TYPES_DICT = {ast.List: "list", ast.ListComp: "list",
                      ast.Dict: "dict", ast.DictComp: "dict",
                      ast.Set: "set", ast.SetComp: "set",
                      ast.Tuple: "tuple", ast.JoinedStr: "str"}
MAX_FACTS_INT = 3


def read_called_name_str(function_node: ast.expr) -> str:
    """The dotted name of a called expression.

    Args:
        function_node (ast.expr): The call's func.
    Returns:
        str: Such as "csv.DictReader", or "" for computed callables.
    Warnings:
        Calls on call results keep only the final attribute.
    """
    if isinstance(function_node, ast.Name):
        return function_node.id
    if isinstance(function_node, ast.Attribute):
        prefix_str = read_called_name_str(function_node.value)
        return (f"{prefix_str}.{function_node.attr}" if prefix_str
                else function_node.attr)
    return ""


def list_body_nodes_list(node: ast.AST) -> list[ast.AST]:
    """The function's own nodes in source order, nested scopes excluded.

    Args:
        node (ast.AST): A function definition.
    Returns:
        list[ast.AST]: Nodes with positions, sorted by line and column.
    Warnings:
        Nested functions, classes and lambdas are not descended into.
    """
    found_list = []
    pending_list = list(node.body)
    while pending_list:
        current_node = pending_list.pop()
        if hasattr(current_node, "lineno"):
            found_list.append(current_node)
        if isinstance(current_node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef, ast.Lambda)):
            continue
        pending_list.extend(ast.iter_child_nodes(current_node))
    return sorted(found_list, key=lambda found_node: (
        found_node.lineno, found_node.col_offset))


def describe_call_fact_str(call_node: ast.Call) -> str:
    """A fact about one call, or "".

    Args:
        call_node (ast.Call): The call.
    Returns:
        str: "calls the web API" for requests-style calls, a known
            operation's phrase, else "".
    Warnings:
        Only well-known names are recognised.
    """
    name_str = read_called_name_str(call_node.func)
    if name_str.split(".")[0] in WEB_MODULES_TUPLE:
        return "calls the web API"
    template_str = CALL_FACTS_DICT.get(name_str.split(".")[-1], "")
    first_str = (ast.unparse(call_node.args[0]) if call_node.args
                 else "a path")
    return template_str.format(first_str)


def list_body_facts_list(node: ast.AST) -> list[str]:
    """Up to three facts the body shows, in source order.

    Args:
        node (ast.AST): A function definition.
    Returns:
        list[str]: Phrases such as "opens path" or "loops over rows".
    Warnings:
        Facts are what the syntax shows, not a full description.
    """
    facts_list: list[str] = []
    for body_node in list_body_nodes_list(node):
        fact_str = ""
        if isinstance(body_node, (ast.For, ast.AsyncFor)):
            fact_str = f"loops over {ast.unparse(body_node.iter)}"
        elif isinstance(body_node, ast.While):
            fact_str = f"repeats while {ast.unparse(body_node.test)}"
        elif isinstance(body_node, ast.Call):
            fact_str = describe_call_fact_str(body_node)
        if fact_str and len(fact_str) <= 60 and fact_str not in facts_list:
            facts_list.append(fact_str)
    return facts_list[:MAX_FACTS_INT]


def describe_body_sentence_str(node: ast.AST) -> str:
    """One sentence of what the body visibly does, or "".

    Args:
        node (ast.AST): A function definition.
    Returns:
        str: Such as "It opens path, reads CSV rows and loops over
            reader."
    Warnings:
        Empty when the body shows no known operation or loop.
    """
    facts_list = list_body_facts_list(node)
    if not facts_list:
        return ""
    joined_str = (facts_list[0] if len(facts_list) == 1 else
                  ", ".join(facts_list[:-1]) + " and " + facts_list[-1])
    return f"It {joined_str}."


def describe_parameter_use_str(node: ast.AST, name_str: str) -> str:
    """How the body first uses a parameter, or "".

    Args:
        node (ast.AST): A function definition.
        name_str (str): The parameter name.
    Returns:
        str: "Looped over.", "Passed to open().", "Indexed by key." or
            "Its .x is used."; "" when the body does not show a use.
    Warnings:
        Only the first use is described.
    """
    for body_node in list_body_nodes_list(node):
        if isinstance(body_node, (ast.For, ast.AsyncFor)) and (
                isinstance(body_node.iter, ast.Name)
                and body_node.iter.id == name_str):
            return "Looped over."
        if isinstance(body_node, ast.Call) and any(
                isinstance(argument_node, ast.Name)
                and argument_node.id == name_str
                for argument_node in body_node.args):
            called_str = read_called_name_str(body_node.func)
            return f"Passed to {called_str}()." if called_str else ""
        if isinstance(body_node, ast.Subscript) and isinstance(
                body_node.value, ast.Name) and body_node.value.id == name_str:
            return "Indexed by key."
        if isinstance(body_node, ast.Attribute) and isinstance(
                body_node.value, ast.Name) and body_node.value.id == name_str:
            return f"Its .{body_node.attr} is used."
    return ""


def infer_returned_type_str(node: ast.AST) -> str:
    """The type of the value a function visibly returns, or "".

    Args:
        node (ast.AST): A function definition.
    Returns:
        str: The type of a returned literal, or of a returned name
            (not a parameter) whose every binding in the body is an
            assignment of a literal of one type or an in-place update
            (rows = [] ... rows += more ... return rows gives "list").
    Warnings:
        Only the final statement is considered; callers check that no
        other statement returns a value.
    """
    if not node.body or not isinstance(node.body[-1], ast.Return) or (
            node.body[-1].value is None):
        return ""
    value_node = node.body[-1].value
    if not isinstance(value_node, ast.Name):
        return LITERAL_TYPES_DICT.get(type(value_node), "")
    is_parameter_bool = value_node.id in {
        argument_node.arg for argument_node in ast.walk(node.args)
        if isinstance(argument_node, ast.arg)}
    types_set = list_binding_types_set(node, value_node.id)
    if is_parameter_bool or len(types_set) != 1:
        return ""
    return types_set.pop()


def list_binding_types_set(node: ast.AST, name_str: str) -> set[str]:
    """The literal types a name is bound to in a function body.

    Args:
        node (ast.AST): A function definition.
        name_str (str): The name.
    Returns:
        set[str]: One type per kind of binding; "" for a binding that is
            not a plain assignment of a literal (loops, unpacking, calls).
            In-place updates (+=) are not bindings here.
    Warnings:
        Nested scopes are not searched.
    """
    nodes_list = list_body_nodes_list(node)
    literal_targets_dict = {
        id(body_node.targets[0]): LITERAL_TYPES_DICT.get(
            type(body_node.value), "")
        for body_node in nodes_list
        if isinstance(body_node, ast.Assign) and len(body_node.targets) == 1}
    in_place_set = {id(body_node.target) for body_node in nodes_list
                    if isinstance(body_node, ast.AugAssign)}
    return {literal_targets_dict.get(id(body_node), "")
            for body_node in nodes_list
            if isinstance(body_node, ast.Name) and body_node.id == name_str
            and isinstance(body_node.ctx, (ast.Store, ast.Del))
            and id(body_node) not in in_place_set}
