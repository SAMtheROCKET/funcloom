"""Module-scope lexical binding resolution for reads in a selected region."""

import ast
import builtins

from funcloom.plan_models import BindingSite, ExtractionPlan, NameResolution

TraversalItem = tuple[ast.AST, bool, tuple[int, ...]]
LocatedSite = tuple[BindingSite, tuple[int, ...]]

DEFINITIONS_TUPLE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
COMPREHENSIONS_TUPLE = (
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)
CONDITIONAL_FIELDS_DICT = {
    ast.If: ("body", "orelse"), ast.IfExp: ("body", "orelse"),
    ast.For: ("target", "body", "orelse"),
    ast.AsyncFor: ("target", "body", "orelse"),
    ast.While: ("body", "orelse"), ast.With: ("body",),
    ast.AsyncWith: ("body",), ast.Match: ("cases",),
    ast.Try: ("body", "handlers", "orelse", "finalbody"),
    ast.TryStar: ("body", "handlers", "orelse", "finalbody"),
}
LOOP_FIELDS_DICT = {
    ast.For: ("target", "body"), ast.AsyncFor: ("target", "body"),
    ast.While: ("test", "body"),
}
TARGET_KINDS_DICT = {
    ast.Assign: "assignment", ast.AnnAssign: "assignment",
    ast.AugAssign: "augmented_assignment", ast.For: "loop_target",
    ast.AsyncFor: "loop_target", ast.NamedExpr: "named_expression",
    ast.Delete: "delete", ast.TypeAlias: "type_alias",
}
DYNAMIC_NAMESPACE_NAMES_TUPLE = (
    "globals", "locals", "vars", "exec", "eval", "setattr", "delattr",
)
NAMESPACE_RISK_KINDS_TUPLE = ("wildcard_import", "dynamic_namespace")
IMPLICIT_MODULE_NAMES_TUPLE = (
    "__name__", "__doc__", "__file__", "__spec__", "__loader__",
    "__package__", "__builtins__",
)
TRANSITIONS_DICT = {
    "bind": dict.fromkeys(("unbound", "direct", "ambiguous", "maybe"),
                          "direct"),
    "maybe_bind": {"unbound": "maybe", "direct": "ambiguous",
                   "ambiguous": "ambiguous", "maybe": "maybe"},
    "unbind": dict.fromkeys(("unbound", "direct", "ambiguous", "maybe"),
                            "unbound"),
    "maybe_unbind": {"unbound": "unbound", "direct": "maybe",
                     "ambiguous": "maybe", "maybe": "maybe"},
}
STATUS_DETAILS_DICT = {
    "direct": "One unconditional prefix binding reaches this read without "
    "later uncertain sites.",
    "selection_local": "An earlier unconditional selection binding "
    "reaches this read.",
    "ambiguous": "Bound on every syntactic path, but conditional, "
    "loop-carried, call-dependent or namespace-wide sites may change it.",
    "possibly_unbound": "Some syntactic paths reach this read without a "
    "binding; NameError is possible if reached.",
    "builtin_fallback": "May be a module binding or fall back to the "
    "builtin of that name.",
    "unbound": "Every reaching path deletes the binding; NameError is "
    "expected if reached.",
    "builtin_lexical": "No module binding found in syntax; resolves to "
    "builtins unless replaced at runtime.",
    "module_implicit": "Set by the import system or runner; its value "
    "depends on how the module is executed.",
    "unresolved": "No module-scope binding was found before this read.",
}
BINDING_LIMITATIONS_TUPLE = (
    "Module-scope lexical resolution of prefix and selection only; the "
    "suffix is not analyzed.",
    "Syntax positions approximate order; constant conditions are not "
    "folded and reachability is not proven.",
    "Function, lambda, class and type-parameter bodies stay opaque; their "
    "free reads are not resolved. Global declarations and namespace calls "
    "inside them are treated as call-dependent rebinding.",
    "Only the first read of each name is resolved. Comprehension reads "
    "after the first iterable are not collected.",
    "Dynamic namespace writes are detected only by the spellings globals, "
    "locals, vars, exec, eval, setattr and delattr. sys.modules, builtins "
    "replacement, import side effects and tracing are not detected.",
    "Resolution statuses are lexical evidence, not runtime identity, value "
    "or type.",
)


def list_definition_time_nodes_list(node: ast.AST) -> list[ast.AST]:
    """List definition parts evaluated in the enclosing module scope.

    Args:
        node (ast.AST): Function, async function, class, or lambda.
    Returns:
        list[ast.AST]: Decorators, defaults, bases and eager annotations.
    Warnings:
        Bodies and PEP 695 type-parameter scopes are intentionally omitted.
    """
    generic_bool = bool(getattr(node, "type_params", None))
    if isinstance(node, ast.ClassDef):
        if generic_bool:
            return list(node.decorator_list)
        return [*node.decorator_list, *node.bases,
                *(keyword_node.value for keyword_node in node.keywords)]
    arguments_node = node.args
    nodes_list = [
        *getattr(node, "decorator_list", []), *arguments_node.defaults,
        *(
            default_node for default_node in arguments_node.kw_defaults
            if default_node is not None),]
    if isinstance(node, ast.Lambda) or generic_bool:
        return nodes_list
    parameters_list = [
        *arguments_node.posonlyargs, *arguments_node.args,
        *arguments_node.kwonlyargs, arguments_node.vararg,
        arguments_node.kwarg,
    ]
    nodes_list.extend(
        parameter_node.annotation for parameter_node in parameters_list
        if parameter_node is not None and parameter_node.annotation
    )
    if node.returns is not None:
        nodes_list.append(node.returns)
    return nodes_list


def expose_comprehension_parts_list(
    item_tuple: TraversalItem, reads_bool: bool,
) -> list[TraversalItem]:
    """Expose comprehension parts that can touch the enclosing scope.

    Args:
        item_tuple (TraversalItem): Comprehension node and path context.
        reads_bool (bool): Collect module reads rather than bindings.
    Returns:
        list[TraversalItem]: Module-scope iterable, or walrus-capable parts.
    Warnings:
        Iteration targets are comprehension-local and never module sites.
    """
    node, conditional_bool, loops_tuple = item_tuple
    generators_list = node.generators
    first_item_tuple = (generators_list[0].iter, conditional_bool, loops_tuple)
    if reads_bool:
        return [first_item_tuple]
    inner_list = [getattr(node, field_str) for field_str in
                  ("elt", "key", "value") if hasattr(node, field_str)]
    for generator_node in generators_list:
        inner_list.extend(generator_node.ifs)
    inner_list.extend(
        generator_node.iter for generator_node in generators_list[1:])
    return [first_item_tuple, *((child_node, True, loops_tuple)
                          for child_node in inner_list)]


def propagate_field_context_list(
        item_tuple: TraversalItem) -> list[TraversalItem]:
    """Propagate conditional and loop context into ordinary child fields.

    Args:
        item_tuple (TraversalItem): Node, conditional flag and loop ids.
    Returns:
        list[TraversalItem]: Children in field order with their context.
    Warnings:
        Guarded fields are conditional even when a test looks constant.
    """
    node, conditional_bool, loops_tuple = item_tuple
    conditional_tuple = CONDITIONAL_FIELDS_DICT.get(type(node), ())
    loop_tuple = LOOP_FIELDS_DICT.get(type(node), ())
    items_list: list[TraversalItem] = []
    for field_str, field_value in ast.iter_fields(node):
        child_loops_tuple = (
            (*loops_tuple, id(node)) if field_str in loop_tuple
            else loops_tuple
        )
        child_conditional_bool = (
            conditional_bool or field_str in conditional_tuple
        )
        for child_node in field_value if isinstance(
                field_value, list) else [field_value]:
            if isinstance(child_node, ast.AST):
                items_list.append((child_node, child_conditional_bool,
                                   child_loops_tuple))
    return items_list


def select_module_children_list(
    item_tuple: TraversalItem, reads_bool: bool,
) -> list[TraversalItem]:
    """Select children evaluated in module scope, keeping bodies opaque.

    Args:
        item_tuple (TraversalItem): Node, conditional flag and loop ids.
        reads_bool (bool): Collect reads rather than binding sites.
    Returns:
        list[TraversalItem]: Children still in the module namespace.
    Warnings:
        Short-circuit operands after the first are marked conditional.
    """
    node, conditional_bool, loops_tuple = item_tuple
    if isinstance(node, (*DEFINITIONS_TUPLE, ast.Lambda)):
        return [(child_node, conditional_bool, loops_tuple)
                for child_node in list_definition_time_nodes_list(node)]
    if isinstance(node, COMPREHENSIONS_TUPLE):
        return expose_comprehension_parts_list(item_tuple, reads_bool)
    if isinstance(node, ast.BoolOp):
        return [(child_node, conditional_bool or index_int > 0, loops_tuple)
                for index_int, child_node in enumerate(node.values)]
    return propagate_field_context_list(item_tuple)


def make_site(
    name_str: str, kind_str: str, certainty_str: str, region_str: str,
    located_node: ast.AST, visible_node: ast.AST,
) -> BindingSite:
    """Create a binding site located at its syntax and visibility point.

    Args:
        name_str (str): Bound name, or a namespace-wide risk spelling.
        kind_str (str): Binding syntax category.
        certainty_str (str): Unconditional, conditional, or risk category.
        region_str (str): Prefix or selection.
        located_node (ast.AST): Syntax that names the binding.
        visible_node (ast.AST): Syntax after which the binding is visible.
    Returns:
        BindingSite: Located evidence using UTF-8 byte columns.
    Warnings:
        Visibility follows syntax positions, not a runtime event trace.
    """
    return BindingSite(
        name_str, kind_str, certainty_str, region_str,
        located_node.lineno, located_node.col_offset,
        visible_node.end_lineno, visible_node.end_col_offset,
    )


def find_target_names_list(target_node: ast.AST) -> list[ast.Name]:
    """Find plain names bound by an assignment or deletion target.

    Args:
        target_node (ast.AST): Name, tuple, list, starred, or object target.
    Returns:
        list[ast.Name]: Names only; attribute and item targets are omitted.
    Warnings:
        Object targets mutate values and are reported by effect analysis.
    """
    if isinstance(target_node, ast.Name):
        return [target_node]
    if isinstance(target_node, ast.Starred):
        return find_target_names_list(target_node.value)
    if isinstance(target_node, (ast.Tuple, ast.List)):
        return [name_node for element_node in target_node.elts
                for name_node in find_target_names_list(element_node)]
    return []


def list_target_nodes_list(node: ast.AST) -> list[ast.AST]:
    """Return the target expressions of one binding or deletion statement.

    Args:
        node (ast.AST): Syntax whose type appears in TARGET_KINDS_DICT.
    Returns:
        list[ast.AST]: Target expressions that may contain plain names.
    Warnings:
        Annotation-only declarations do not bind a value.
    """
    if isinstance(node, (ast.Assign, ast.Delete)):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign):
        return [node.target] if node.value is not None else []
    if isinstance(node, ast.TypeAlias):
        return [node.name]
    return [node.target]


def record_target_sites_list(
    node: ast.AST, conditional_bool: bool, region_str: str,
) -> list[BindingSite]:
    """Record names bound by assignments, loops, contexts and deletions.

    Args:
        node (ast.AST): Candidate binding syntax.
        conditional_bool (bool): Whether the node is on a guarded path.
        region_str (str): Prefix or selection.
    Returns:
        list[BindingSite]: Located sites, possibly empty.
    Warnings:
        Loop targets are conditional because a loop can run zero times.
    """
    certainty_str = "conditional" if conditional_bool else "unconditional"
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [
            make_site(
                name_node.id, "context_target", certainty_str, region_str,
                name_node, item_node.context_expr) for item_node in node.items
            if item_node.optional_vars
            for name_node in find_target_names_list(item_node.optional_vars)]
    kind_str = TARGET_KINDS_DICT.get(type(node))
    if kind_str is None:
        return []
    visible_node = node
    if kind_str == "loop_target":
        certainty_str, visible_node = "conditional", node.iter
    return [make_site(name_node.id, kind_str, certainty_str, region_str,
                      name_node, visible_node)
            for target_node in list_target_nodes_list(node)
            for name_node in find_target_names_list(target_node)]


def record_declaration_sites_list(
    node: ast.AST, conditional_bool: bool, region_str: str,
) -> list[BindingSite]:
    """Record imports, definitions, exception names and match captures.

    Args:
        node (ast.AST): Candidate declaration syntax.
        conditional_bool (bool): Whether the node is on a guarded path.
        region_str (str): Prefix or selection.
    Returns:
        list[BindingSite]: Located sites, possibly empty.
    Warnings:
        Wildcard imports are namespace-wide risks, not named bindings.
    """
    certainty_str = "conditional" if conditional_bool else "unconditional"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [make_site("*", "wildcard_import", "unknown", region_str,
                          alias_node, node) if alias_node.name == "*"
                else make_site(alias_node.asname
                               or alias_node.name.split(".")[0], "import",
                               certainty_str, region_str, alias_node, node)
                for alias_node in node.names]
    if isinstance(node, DEFINITIONS_TUPLE):
        kind_str = ("class_definition" if isinstance(node, ast.ClassDef)
                    else "function_definition")
        return [make_site(node.name, kind_str, certainty_str, region_str,
                          node, node)]
    if isinstance(node, ast.ExceptHandler) and node.name:
        return [make_site(node.name, "exception_target", "conditional",
                          region_str, node, node.type or node)]
    capture_str = getattr(node, "rest", None) or getattr(node, "name", None)
    if isinstance(node, (ast.MatchAs, ast.MatchStar, ast.MatchMapping)) and (
        capture_str
    ):
        return [make_site(capture_str, "match_capture", "conditional",
                          region_str, node, node)]
    return []


def find_risk_sites_list(
    statement_node: ast.stmt, region_str: str,
) -> list[BindingSite]:
    """Find global declarations and namespace-changing call spellings.

    Args:
        statement_node (ast.stmt): Complete module statement to scan.
        region_str (str): Prefix or selection.
    Returns:
        list[BindingSite]: Call-dependent or namespace-wide risk sites.
    Warnings:
        Spelling detection can over-report shadowed names and miss aliases.
    """
    nested_ids_set = {
        id(inner_node) for node in ast.walk(statement_node)
        if isinstance(node, (*DEFINITIONS_TUPLE, ast.Lambda))
        for inner_node in ast.walk(node) if inner_node is not node
    }
    sites_list: list[BindingSite] = []
    for node in ast.walk(statement_node):
        if isinstance(node, ast.Global) and id(node) in nested_ids_set:
            sites_list.extend(make_site(
                name_str, "global_declaration", "call_dependent",
                region_str, node, node,
            ) for name_str in node.names)
        elif isinstance(node, ast.Name) and (
            node.id in DYNAMIC_NAMESPACE_NAMES_TUPLE
        ):
            certainty_str = ("call_dependent" if id(node) in nested_ids_set
                             else "unknown")
            sites_list.append(make_site(node.id, "dynamic_namespace",
                                        certainty_str, region_str, node,
                                        node))
    return sites_list


def collect_statement_sites_list(
    statement_node: ast.stmt, region_str: str,
) -> list[LocatedSite]:
    """Collect module-scope sites in one statement with loop context.

    Args:
        statement_node (ast.stmt): Complete module statement.
        region_str (str): Prefix or selection.
    Returns:
        list[LocatedSite]: Sites paired with enclosing module loop ids.
    Warnings:
        Nested function, lambda and class bodies remain opaque. A loop
        target's ids include its own loop so enclosed reads can see it.
    """
    located_list = [(site, ()) for site in
                    find_risk_sites_list(statement_node, region_str)]
    pending_list: list[TraversalItem] = [(statement_node, False, ())]
    while pending_list:
        item_tuple = pending_list.pop()
        node, conditional_bool, loops_tuple = item_tuple
        for site in (
                *record_target_sites_list(node, conditional_bool, region_str),
                *record_declaration_sites_list(
                    node, conditional_bool, region_str)):
            site_loops_tuple = (
                (*loops_tuple, id(node)) if site.kind == "loop_target"
                else loops_tuple
            )
            located_list.append((site, site_loops_tuple))
        pending_list.extend(
            reversed(select_module_children_list(item_tuple, False)))
    return located_list


def list_selection_reads_list(
    statements_list: list[ast.stmt],
) -> list[tuple[ast.Name, tuple[int, ...]]]:
    """List the first module-scope read of each name in the selection.

    Args:
        statements_list (list[ast.stmt]): Complete selected statements.
    Returns:
        list: Name reads in source order with enclosing loop ids.
    Warnings:
        Deletions and augmented targets count as reads of an existing name.
    """
    reads_list: list[tuple[ast.Name, tuple[int, ...]]] = []
    for statement_node in statements_list:
        pending_list: list[TraversalItem] = [(statement_node, False, ())]
        while pending_list:
            item_tuple = pending_list.pop()
            node = item_tuple[0]
            if isinstance(node, ast.AugAssign) and isinstance(
                node.target, ast.Name,
            ):
                reads_list.append((node.target, item_tuple[2]))
            elif isinstance(node, ast.Name) and not isinstance(
                node.ctx, ast.Store,
            ):
                reads_list.append((node, item_tuple[2]))
            pending_list.extend(
                reversed(select_module_children_list(item_tuple, True)))
    reads_list.sort(key=lambda pair: (pair[0].lineno, pair[0].col_offset))
    first_reads_dict: dict[str, tuple[ast.Name, tuple[int, ...]]] = {}
    for pair_tuple in reads_list:
        first_reads_dict.setdefault(pair_tuple[0].id, pair_tuple)
    return list(first_reads_dict.values())


def choose_reaching_sites_list(
    read_node: ast.Name, read_loops_tuple: tuple[int, ...],
    located_list: list[LocatedSite],
) -> list[tuple[BindingSite, str]]:
    """Choose sites visible before a read or carried around a shared loop.

    Args:
        read_node (ast.Name): Read occurrence in the selection.
        read_loops_tuple (tuple): Module loops enclosing the read.
        located_list (list[LocatedSite]): All sorted module-scope sites.
    Returns:
        list: Sites with a mode: ordered, loop_enclosed or loop_carried.
    Warnings:
        Namespace-wide risks apply to every name they precede. Carried
        sites are ordered last because they reach only via a back edge.
    """
    read_position_tuple = (read_node.lineno, read_node.col_offset)
    reaching_list: list[tuple[BindingSite, str]] = []
    for site, site_loops_tuple in located_list:
        if site.name != read_node.id and (
            site.kind not in NAMESPACE_RISK_KINDS_TUPLE
        ):
            continue
        before_bool = (
            (site.visible_line, site.visible_column_utf8)
            <= read_position_tuple
        )
        if before_bool and site.kind == "loop_target" and (
            site_loops_tuple[-1] in read_loops_tuple
        ):
            reaching_list.append((site, "loop_enclosed"))
        elif before_bool:
            reaching_list.append((site, "ordered"))
        elif set(site_loops_tuple) & set(read_loops_tuple):
            reaching_list.append((site, "loop_carried"))
    return sorted(reaching_list,
                  key=lambda pair: pair[1] == "loop_carried")


def map_site_effect_str(site: BindingSite, mode_str: str) -> str:
    """Map one reaching site to its effect on possible binding states.

    Args:
        site (BindingSite): Located binding, deletion or risk.
        mode_str (str): Ordered, loop_enclosed or loop_carried reach.
    Returns:
        str: One key of TRANSITIONS_DICT.
    Warnings:
        Exception targets are unbound when their handler finishes. A loop
        target always binds reads inside that loop's own body.
    """
    if mode_str == "loop_enclosed":
        return "bind"
    certain_bool = (
        site.certainty == "unconditional" and mode_str == "ordered"
    )
    if site.kind == "delete":
        return "unbind" if certain_bool else "maybe_unbind"
    if site.kind == "exception_target":
        return "maybe_unbind"
    return "bind" if certain_bool else "maybe_bind"


def resolve_status_tuple(
    name_str: str, reaching_list: list[tuple[BindingSite, str]],
) -> tuple[str, str]:
    """Combine reaching sites into a conservative lexical resolution.

    Args:
        name_str (str): Name being read.
        reaching_list (list): Ordered sites and their reach modes.
    Returns:
        tuple[str, str]: Status and its explanation.
    Warnings:
        Call-dependent sites may run after any later binding.
    """
    state_str, region_str, persistent_bool = "unbound", "", False
    for site, mode_str in reaching_list:
        if site.certainty == "call_dependent":
            persistent_bool = True
            continue
        effect_str = map_site_effect_str(site, mode_str)
        state_str = TRANSITIONS_DICT[effect_str][state_str]
        if effect_str == "bind":
            region_str = site.region
    if persistent_bool:
        state_str = TRANSITIONS_DICT["maybe_bind"][state_str]
    builtin_bool = hasattr(builtins, name_str)
    if state_str == "direct" and region_str == "selection":
        status_str = "selection_local"
    elif state_str == "maybe" and builtin_bool:
        status_str = "builtin_fallback"
    elif state_str == "maybe":
        status_str = "possibly_unbound"
    elif state_str != "unbound":
        status_str = state_str
    elif name_str in IMPLICIT_MODULE_NAMES_TUPLE:
        status_str = "module_implicit"
    elif builtin_bool:
        status_str = "builtin_lexical"
    else:
        status_str = "unbound" if reaching_list else "unresolved"
    return status_str, STATUS_DETAILS_DICT[status_str]


def resolve_bindings_none(
    module_node: ast.Module, statements_list: list[ast.stmt],
    plan_report: ExtractionPlan,
) -> None:
    """Resolve selected reads against lexical module-scope binding sites.

    Args:
        module_node (ast.Module): Contextually compiled source tree.
        statements_list (list[ast.stmt]): Complete selected statements.
        plan_report (ExtractionPlan): Evidence destination.
    Returns:
        None: Adds sites and resolutions; never changes eligibility.
    Warnings:
        Partial lexical evidence; no runtime namespace is inspected.
    """
    plan_report.binding_analysis = "partial"
    plan_report.binding_limitations = list(BINDING_LIMITATIONS_TUPLE)
    selected_ids_set = {id(node) for node in statements_list}
    located_list: list[LocatedSite] = []
    for statement_node in module_node.body:
        if statement_node.lineno > plan_report.end_line:
            break
        region_str = ("selection" if id(statement_node) in selected_ids_set
                      else "prefix")
        located_list.extend(
            collect_statement_sites_list(statement_node, region_str))
    located_list.sort(key=lambda pair: (
        pair[0].line, pair[0].column_utf8, pair[0].kind, pair[0].name,
    ))
    plan_report.binding_sites = [site for site, _ in located_list]
    for read_node, loops_tuple in list_selection_reads_list(statements_list):
        reaching_list = choose_reaching_sites_list(read_node, loops_tuple,
                                                   located_list)
        status_str, detail_str = resolve_status_tuple(read_node.id,
                                                      reaching_list)
        plan_report.name_resolutions.append(NameResolution(
            read_node.id, read_node.lineno, read_node.col_offset,
            status_str, detail_str, [site for site, _ in reaching_list],
        ))
