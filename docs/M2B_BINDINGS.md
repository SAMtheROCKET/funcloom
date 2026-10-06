# M2b.2: lexical binding resolution evidence

Version 0.2.2a0 adds module-scope binding resolution to the `plan` API and
CLI. It is the second bounded M2b increment. Like M2b.1 it adds evidence
only: M2a's candidate/refusal subset, `can_apply=false` and every
source-writing restriction are unchanged. M2b is not complete.

## Report contract

The planning schema is now `plan-3`. All `plan-2` fields keep their meaning.
Four fields are added:

| Field | Meaning |
| --- | --- |
| `binding_analysis` | `not_run` when reading/compilation/selection failed; otherwise `partial` |
| `binding_sites` | Every module-scope binding, deletion or namespace risk in the prefix and selection |
| `name_resolutions` | For the first selected read of each name: status, explanation and reaching sites |
| `binding_limitations` | Explicit boundaries of this analysis |

A site has `name`, `kind`, `certainty`, `region`, a located position
(`line`, `column_utf8`) and a visibility point (`visible_line`,
`visible_column_utf8`) after which the binding can be observed. Columns are
zero-based UTF-8 byte offsets, as in `plan-2` effect facts.

Site kinds: `assignment`, `augmented_assignment`, `named_expression`,
`loop_target`, `context_target`, `exception_target`, `match_capture`,
`import`, `function_definition`, `class_definition`, `type_alias`,
`delete`, `wildcard_import`, `global_declaration`, `dynamic_namespace`.

Certainty: `unconditional` (not inside any guarded path), `conditional`
(inside `if`/loop/`try`/`with` bodies/`match` cases, a conditional
expression, a later short-circuit operand or a comprehension),
`call_dependent` (a `global` declaration or namespace call inside a
function, lambda or class body; it may run after any later binding) and
`unknown` (a wildcard import or top-level namespace call).

## Resolution statuses

| Status | Meaning |
| --- | --- |
| `direct` | One unconditional prefix binding reaches the read, with no later uncertain site |
| `selection_local` | An earlier unconditional binding in the selection reaches it |
| `ambiguous` | Bound on every syntactic path, but its value may come from several sites |
| `possibly_unbound` | Some syntactic path reaches the read without a binding |
| `builtin_fallback` | Either a module binding or the builtin of that name |
| `unbound` | Every reaching path deletes the binding |
| `builtin_lexical` | No module binding in syntax; resolves to builtins unless replaced |
| `module_implicit` | `__name__`, `__file__` and similar names set by the runner |
| `unresolved` | No module-scope binding was found before the read |

Deletions unbind. Exception targets are unbound when their handler ends.
Wildcard imports and top-level namespace calls may bind any name at their
position; a later unconditional binding resolves that. Call-dependent sites
make every name they precede at best `ambiguous`. A loop target always
binds reads inside its own loop body. A binding later in the same loop as
a read reaches it through the back edge (`loop_carried`).

Every candidate has only `direct` inputs. Until 0.4.0a0 this followed
from the restricted prefix; since M2b.3 it is the acceptance rule
(see below). A regression asserts this consistency.

## Coverage boundaries

- Only the prefix and selection are analyzed; the suffix is not.
- Syntax positions approximate order. Constant conditions such as
  `if True:` are not folded, and reachability is not proven.
- Function, lambda, class and PEP 695 type-parameter bodies stay opaque.
  Their free reads are not resolved. Decorators, defaults, bases and eager
  annotations are evaluated in module scope and are analyzed.
- Only the first read of each name is resolved. Since M2b.6 the free
  reads of selected comprehensions (element, conditions and later
  iterables, nested comprehensions included) are collected; iteration
  variables are local and never collected.
- Namespace writes are detected only by the spellings `globals`, `locals`,
  `vars`, `exec`, `eval`, `setattr` and `delattr`. Spelling can over-report
  shadowed names and miss aliases. `sys.modules`, builtins replacement,
  import side effects and tracing are not detected.
- A status is lexical evidence, not runtime identity, value or type.

## Validation

Fifteen added tests cover each status, conditional and constant-condition
paths, deletion and exception targets, wildcard imports, `global`
declarations and namespace calls (including a function defined after the
read), loop targets and back edges, opaque definitions/comprehensions with
walrus leakage, context managers, match captures, implicit names, UTF-8
columns, invalid selections, repeatability and text/JSON rendering. One
trusted, test-authored fixture is executed to confirm that an exception
target read raises `NameError`; no arbitrary target code is run.

## M2b.3: resolution-gated prefix (0.4.0a0)

The evidence above now decides eligibility for the statements before the
region. Any compilable prefix is accepted when every selected read resolves
`direct`; other statuses are refused with PLAN003 naming the status.
PLAN005 is retired. Namespace-wide risks already prevent a `direct`
status, so no separate rule is needed. The snippet workflow proposes
numeric input types only for `direct` inputs. Six regressions include a
trusted comparison on a script with imports, a helper function, a loop,
a call and an unrelated conditional before the selection. See
[EXTRACTION_PLANNING.md](EXTRACTION_PLANNING.md) for the updated subset.

## M2b.6: comprehensions

List, set and dict comprehensions are accepted in selected statements.
They run immediately: at module level their free names read module
globals at that moment, and inside the draft they read the function's
parameters (or selection-local names), which hold the same values. The
draft is therefore only accepted when every free read resolves as
before: `direct`, `selection_local` or a free builtin/runner name.

- Iteration targets are comprehension-local; they are never inputs or
  outputs, even when a module variable has the same name
  (`[x for x in values]` does not read module `x`).
- The first iterable is evaluated in the enclosing scope, so
  `[item for item in item]` reads the outer `item`.
- Calls inside a comprehension are covered by the PLAN008 check for
  module code that could observe delayed writes.
- Still refused (PLAN002): generator expressions (they run lazily,
  possibly after the function returns), lambdas (they run later and would
  read the function's values instead of the module's), async
  comprehensions and `:=`.

Seven regressions (tests/test_plan_comprehensions.py) cover nested,
filtered, multi-generator, tuple-target, set and dict comprehensions with
trusted, test-authored comparisons of the original and the draft, plus
the refusals above. The effect inventory still treats comprehension bodies
as opaque scope boundaries. Snippet drafts rename a comprehension variable
together with a module variable of the same name; behavior is unchanged,
but the proposed name (for example a `_float` suffix) can then describe
the module value rather than the loop item.

## Next boundary

Remaining M2b work: consider accepting `ambiguous` reads; widen the
selected statements themselves (control flow); resolve free reads inside
function and lambda bodies; path-sensitive
exception and alias contracts; definition-time effects; a concrete-syntax
edit representation; and more counterexamples before any M3 apply path.
