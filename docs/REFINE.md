# Refine: short functions, docstrings and 79-column lines

Current version: **0.10.1a0**. Input and final output must compile before
writing. Helpers precede their owning function/class, including decorators,
so a decorator or class initializer can call them immediately. Helper
annotations are quoted to avoid evaluating expressions again or before a
type exists. They remain static proposals, not verified runtime types.
Original function signatures are retained.

Version **0.9.0a0** added function splitting, optional documentation and the
`funcloom refine` command. Version **0.10.0a0** splits generators and
coroutines, splits long loop/if/with bodies in place, adds certain type
hints to helpers and keeps each file's line endings. Refinement also runs
inside `modularize`, on the generated modules and, in folder mode, on every
copied Python file.

```powershell
funcloom refine module.py --output module_refined.py            # one file
funcloom refine my_repo --output my_repo_refined --document      # whole repo
```

The input is never changed and the output must be new. Options:
`--keep-long-functions` (no splitting), `--document` (add missing
docstrings), `--trust-with-blocks` (see below), `--line-length N`, `--skip-data` for folders, `--format json`.
The same options work on `modularize`.

Each refinement verifies itself and is skipped for a file whose result does
not verify, so a failed refinement never produces changed code.

## Splitting long functions

Functions and methods longer than the preferred **40 lines** (including
decorators, docstring and comments) are split into module-level helpers:

```python
def summarize(values, scale=1):
    """Summarize a list of numbers."""
    exit_bool, exit_value, exit_value_parts = _summarize_part_1(scale, values)
    if exit_bool:
        return exit_value
    cleaned, count, total = exit_value_parts
    (
        deviation, extra, mean, notes, parts, ratio,
    ) = _summarize_part_2(
        cleaned, count, total,
    )
    return _summarize_part_3(deviation, extra, mean, notes, parts, ratio)
```

- The function keeps its name, signature, decorators and docstring.
  Callers and tests still need validation. Helpers are private
  (`_summarize_part_1`, `_Report_build_part_1` for methods), have
  Args/Returns/Warnings docstrings and contain the original statements.
- Cut points are chosen to minimize how many values cross between pieces,
  with each helper aimed at 40 lines including its docstring.
- A helper receives only the local values it reads and returns only those
  later pieces read. Globals and builtins are read directly, exactly as
  before. The last helper's result is returned, so the function's result
  is unchanged. A value that a piece changes only on some paths is passed
  in as well, so the helper can hand it back unchanged on the others.
- **Early returns** (guard clauses, returns inside loops or `try`) use an
  explicit protocol: the helper returns `(True, value, None)` when the
  original would return, and `(False, None, values)` when it finishes; the
  function checks the flag and returns the value.
- **Generators** are split into generator helpers called with
  `yield from`, which forwards `next`, `send`, `throw` and `close`, and
  passes return values through. **Coroutines** are split into `async`
  helpers called with `await`. Async generators are left whole, because
  Python has no `yield from` for them.
- **Type hints** are added to helper parameters and results only when the
  type is certain: an annotated parameter the function does not rebind, or
  a value built by a literal, display or trusted builtin/class call on every
  path. Anything else stays unannotated. Classes are written in quotes.

## Splitting long blocks

When a function is long because of one big `for`, `while`, `if`/`else` or
`with` statement, cutting between its top-level statements cannot help.
FuncLoom then splits the **body of that block** in place:

```python
def total_sales(rows):
    totals = {}
    notes = []
    for row in rows:
        (
            exit_bool, exit_value, exit_value_parts,
        ) = _total_sales_loop_part_1(
            notes, row,
        )
        if exit_bool:
            return exit_value
        region = exit_value_parts
        _total_sales_loop_part_2(notes, region, row, totals)
    return totals, len(notes)
```

(Real output for an authored 50-line function whose loop body has a
`return` in the middle; `notes` and `totals` are mutated in place, so
they need not be returned.)

- The loop, test or context manager stays where it was; only the body's
  statements move into helpers (`_name_loop_part_N`, `_name_if_part_N`,
  `_name_else_part_N`, `_name_with_part_N`).
- In a loop, values also flow from one round to the next, so a value read
  by an earlier piece in the next round, by the `while` test, the loop's
  `else` block or code after the loop is returned and rebound each round.
- A `return` inside the block uses the early-exit protocol from every
  piece, including the last one.
- Splitting runs in up to four verified rounds, so a helper that is itself
  one long loop, or a block nested inside a split block, is split in a
  later round. A block is chosen when the function's own statements cannot
  be cut or a cut would leave a piece still over the limit.

A block is left whole, with the reason in the notes, when:

- a loop body uses `break` or `continue` for that loop (these cannot leave a
  helper);
- code defined in the block (a lambda, nested function or comprehension)
  reads a value changed later, including by the next round of a loop;
- code defined before the block reads a value the block changes (it would
  not see the change until the helper returns);
- a `with` body binds values used after the statement (a context manager
  can suppress an exception halfway, and values bound before it would be
  lost with the helper's locals);
- a value might be unbound where a piece needs it (for example a value set
  late in one round and read early in the next), or statements share lines.

Only blocks directly in a function body are candidates. A block nested
inside another is split only once the outer block has been split into
helpers; a nested block that is the only statement of its parent is not
split.

### `--trust-with-blocks` (opt-in)

By default a value bound inside a `with` body counts as possibly unbound,
because a context manager can suppress an exception halfway through its
block. Code built around `with st.sidebar:` or `with open(...) as f:`
therefore merges into long steps and resists splitting. With
`--trust-with-blocks`, such values count as bound, except when a context
manager is a known suppressor: `contextlib.suppress`, `pytest.raises`,
`assertRaises`/`assertRaisesRegex`, `assertWarns`/`assertWarnsRegex`,
`ExitStack` and `AsyncExitStack` stay strict. The trade-off: if a custom
context manager does suppress an exception, the converted code can raise
`UnboundLocalError` at a step boundary where the original continued.
`modularize` suggests the option when with blocks caused merges.

### When a boundary is moved or the function is left whole

Pieces are merged, exactly like modularize steps, when a value passed in or
out might be unbound at that point, or when a function or lambda defined in
a piece reads a variable a later piece rebinds. A name that is certainly
bound includes assignments on every branch that can continue, `try` bodies
whose handlers all return or raise, `:=` in an always-evaluated test, and a
`for`/`with` target inside its own body; `with` bodies are never certain
because a context manager can suppress exceptions.

A function is left whole, with the reason in the notes, when it is an
async generator; uses `global`, `nonlocal`, `locals()`, `vars()`, `eval`,
`exec`, `super()` or `__class__`; is a method using name-mangled
`__private` names; has statements sharing a line; could read a local before
it is bound (the helper might see a global of the same name instead of
raising `UnboundLocalError`); has no safe cut point and no long block that
can be split; is long only because of one statement that cannot be split;
or is a method whose body contains a multi-line string that cannot be
re-indented.

### Verification

For every split function or block, the helpers' statements, concatenated,
must equal the original statements (allowing only the early-return
rewrite). The rewritten body or block, and every helper's closing `return`,
must match a canonical, unwrapped form of the same code. For a block, the
rest of the function must be unchanged. The module must compile and no new
undefined names may appear. Each round is verified on its own; otherwise
that round is not applied.

## Documenting (`--document`)

Functions and methods without a docstring get one that states only what the
code shows:

```python
def area(radius: float, *, scale=1) -> float:
    """Area.

    Args:
        radius (float): Not described in the original code.
        scale (type not annotated): Not described in the original code.
    Returns:
        float: Not described in the original code.
    Warnings:
        Generated by FuncLoom from the signature; describe the behavior
            before relying on it.
    """
```

The summary is the name as a sentence (`__init__` becomes "Initialize a Box
instance."). `self`/`cls` are skipped; generators are described as
iterators; functions that never return a value say so. Existing docstrings
and one-line functions are left alone. Removing the added docstrings must
give back the original syntax tree exactly.

## Line length

Long assignments, expression statements and returns are wrapped at any
depth. Every wrapped file must have the original syntax tree.

## Line endings

Each file is written with the line endings it had: LF, CRLF or CR,
detected per file. Generated files in `modularize` follow the source
script's style.

## Evidence

`tests/test_refine.py` runs authored modules before and after refinement:

- long functions with early returns and closures, and a long method
  keeping instance state;
- a generator driven with `send` and `throw`, and a coroutine;
- guard clauses with `try` and `:=`, and a `with` block staying uncertain;
- a long loop body with an early return, a carried total and a
  conditionally changed value;
- nested loops inside an `else` body split over three rounds;
- unsafe functions and blocks (`break`, a late-bound lambda, a value read
  in the next round) left whole;
- documentation, the file and folder commands, and modularize splitting a
  long merged step.

Differential probes on authored fixtures gave identical results for every
split function and block:

- 12 function cases, 11 of them split;
- 14 block cases (`for`, `while`, `if`, `else`, `with`, a method, a
  generator, nested loops, pre/post code and a conditional rewrite);
  the four unsafe blocks stayed whole.

`scripts/verify.py` refines `examples/long_functions.py` and compares its
output.

## Limits

- Splitting changes tracebacks, profiling names and `inspect` results for
  the split function. Names/signatures are retained; arbitrary runtime
  equivalence is not proven.
- Type hints use narrow static evidence; most helper parameters stay
  unannotated.
- `try` blocks, `match` statements, async loops/with and blocks that are
  the only statement of an enclosing block are not split.
- One very long statement (a large data literal, a long `st.markdown`
  call) and long nested functions stay long; only module-level functions
  and methods are split.
- Files that are not UTF-8 are copied unchanged.
- Generated documentation is a skeleton, not a description of behavior.
