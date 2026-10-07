# M2b.5: in-place statements in selected regions

Version **0.6.0a0** accepts the statements that change something in place,
which are the most common lines in data-cleaning scripts. Every plan still
needs review and has `can_apply=false` and `behavior_verified=false`.

## Newly supported statement forms

| Form | Example | Inputs | Returned names |
| --- | --- | --- | --- |
| Augmented assignment to a name | `total += amount` | `total`, `amount` | `total` |
| Augmented assignment to an item or attribute | `counts["a"] += 1` | `counts` | none |
| Item or attribute assignment | `df["ratio"] = df["a"] / df["b"]`, `table.note = "ok"` | the object and the value's names | none |
| Expression statement | `rows.append(row)`, `df.dropna(inplace=True)`, `print(x)` | names read | none |
| Unpacking | `first, *rest = rows` | names read | every bound name |
| Chained assignment | `a = b = []` | names read | every bound name |

Calls and other code-running syntax in any of these forms are subject to
PLAN008 exactly as in [M2B_CALLS.md](M2B_CALLS.md).

## Why these are equivalent after extraction

- An object passed into the draft is the **same object** the original line
  would use, and it is changed at the same moment. So item and attribute
  updates, `append`, `sort`, in-place pandas methods and a custom
  `__iadd__` all act on the same object, and every other name referring to
  it (aliases) sees the change, just as before.
- `x += y` starts from the same object as the original. If the type updates
  in place (lists), the shared object changes; if not (numbers, tuples), a
  new value is produced. Either way the new binding is returned and the
  caller assigns it.
- Output is produced in the same order because the statements run in the
  same order at the same point in the script.

A region that binds no names produces `return None` and a caller that just
calls the function, for example `clean_rows(rows)`.

## Still refused (PLAN002)

- `del`, and annotated assignment (`x: int = 1`) because moving the
  annotation into a function changes its evaluation;
- nested unpacking targets (`(a, b), c = ...`) and item or attribute targets
  inside unpacking (`obj.x, y = ...`);
- control flow (`if`, `for`, `while`, `with`, `try`, `match`) and nested
  definitions inside the selection;
- the expression limits in M2B_CALLS.md (lambdas, comprehensions, `:=`,
  f-strings, frame-dependent names).

The example `examples/plan_refused.py` now shows a value set on only one
branch with no earlier value (PLAN003, `possibly_unbound`), because its
old `+=` case and, since M2b.7, its `ambiguous` case are supported.

## M2b.8: if, for and while

Selected regions may contain `if`/`elif`/`else`, `for` and `while`
blocks (with `else`, `break` and `continue`) whose bodies hold the
supported statements. `try`, `with`, `match`, `del` and definitions stay
refused (PLAN002).

Definite assignment decides which names a read can rely on: inside a
branch, names assigned earlier in it; after `if`/`else`, names assigned
in both branches; after a loop, nothing assigned in its body (it may run
zero times). Any other read must be a valid input (PLAN003 otherwise).
Every name the region assigns is then settled:

- set on every path: returned as usual;
- set on only some paths but bound before the region (or read by the
  region first): passed in, so it keeps its earlier value when the region
  does not assign it; the plan says so;
- set on only some paths with no earlier value, and nothing else in the
  file reads it (no read outside the region, no `global` use, no string
  of its name, no namespace call): not returned; the plan says another
  module importing it would no longer see it. A loop variable that is
  only used inside its loop is the usual case;
- otherwise the region is refused with PLAN009.

Calls inside blocks are covered by PLAN008. Ten regressions
(tests/test_plan_control_flow.py) compare the original and the draft on
trusted, test-authored scripts (accumulating loops, both outcomes of a
branch, a `while` loop with `break` and `continue`, nested loops with a
comprehension and `for`/`else`) and check the refusals.

## M2b.9: try, with, match, raise and assert

- `try`/`except`/`else`/`finally`: a handler starts from the names
  definite before the `try` (the body may stop anywhere). After the
  statement, a name is definite when the normal path (body and `else`)
  and every handler set it, or when `finally` sets it. Python deletes an
  `except ... as name` target when the clause ends, so it is never
  returned; if that name already has a value, the region is refused
  (PLAN009) because the clause could delete it from the module.
  `except*` stays refused.
- `with`: the `as` targets are definite afterwards, and so are names the
  body sets on every path. The plan states the one assumption this needs:
  a context manager that suppresses an exception part-way through would
  make the draft raise `UnboundLocalError` for names not yet set, where
  the original leaves them unset.
- `match`: captures are set inside their case; after the statement a name
  is definite when every case sets it and the last case always matches
  (`case _` or a bare capture). Pattern values, classes and keys are
  reads.
- `raise` and `assert` only read.

Iteration, truth tests, in-place operators, unpacking, context managers
and pattern matching can call user methods, so PLAN008 now treats them
like calls. Eight regressions (tests/test_plan_blocks.py) compare the
original and the draft on both paths of each construct.

## M2b.10: definitions, lambdas and generator expressions

`def`, `async def`, `class`, lambdas and generator expressions may appear
in a region. Their decorators, defaults, annotations and bases are read
when the region runs; their bodies run later. Inside the draft, a body
that reads a name local to the draft (an input or anything the region
assigns) keeps that variable as a closure, while the original reads the
module name when it runs. Python's own scope tables (`symtable`) give the
names each body reads; the two versions agree unless code outside the
region rebinds such a name (an assignment, import, definition or `del`
after the region, a `global` declaration in any function, a wildcard
import after the region, or a namespace call), which is refused with
PLAN010. `global`/`nonlocal` and type parameters inside a moved
definition stay refused (PLAN002). The plan notes that moved functions
and classes get nested qualified names (`draft.<locals>.helper`), which
shows in reprs and stops pickling them by reference. Seven regressions
(tests/test_plan_definitions.py) cover helpers called after the region,
recursion, lambdas with generators, a class with a method, and the
refusals.

## Snippets

The snippet workflow handles the same forms. Mutated or unpacked values
get no numeric type proposal; `x += 1` on a numeric input keeps its
proposal. Renaming no longer touches attribute names (`Box.size`) or
keyword-argument names (`round(x, ndigits=2)`), so a variable named like
an attribute or keyword can still be renamed. Long statements of every
supported form are wrapped: the right-hand side, or a whole expression
statement, goes inside parentheses.

## Limits

- As before, a statement that raises leaves earlier returned names
  unpublished in the draft (the `binding_visibility` limitation).
- Objects are not analyzed. Mutating an object shared with module code is
  safe only because it happens at the same moment; code that stores and
  later compares object identities across the call boundary is not
  modeled.

## Validation

Six tests in `tests/test_plan_statements.py`: a table-cleaning region with
methods, attribute and item updates, `+=` and starred unpacking executed
both ways (including an alias); a region with no returned names; a module
method reading an earlier write (PLAN008); remaining refusals; and two
snippet cases (wrapped long call with `+=`, renaming that skips attributes
and keyword arguments). Ten existing tests that asserted the old refusals
were updated. A separate 12-pattern probe (list and tuple `+=` with
aliases, swap, starred, chained, `append` through an alias, dict, item,
attribute and slice updates, custom `__iadd__`, output order) gave the same
state for every pattern.
