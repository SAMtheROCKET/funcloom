# M2b.4: calls in selected regions

Version **0.5.0a0** lets the selected assignments use calls and other
expressions that run code. It adds one new refusal, **PLAN008**, for the one
way such code can see a difference after extraction. As before, every plan
needs review and has `can_apply=false` and `behavior_verified=false`.

## What the selected lines may now contain

Each selected statement is still one assignment to one plain name. Its
value may now use:

- calls, including keyword arguments and `*`/`**` unpacking;
- attribute access (`math.pi`, `data.mean()`) and item access/slices
  (`values[0]`, `rows[1:3]`);
- comparisons, `and`/`or`, and conditional expressions (`a if c else b`);
- tuple, list, dict and set displays.

Still refused with PLAN002: lambdas, comprehensions and generator
expressions, `:=`, f-strings, `await`/`yield`, multiline strings, and the
frame-dependent names `locals`, `vars`, `eval`, `exec`, `globals`,
`setattr` and `delattr`. Inside a function these change meaning (for
example `locals()` returns the function's locals).

Statements other than single-name assignments are unchanged: `x += 1`,
`df["a"] = ...`, `obj.attr = ...`, bare expression statements such as
`print(x)`, `if`, loops and `with` are still refused.

## Builtins stay free names

A read of a builtin such as `round`, `len` or `print` with **no module
binding anywhere in the syntax** (status `builtin_lexical`) is no longer
refused and does not become a parameter. It stays a free name in the draft,
and the plan records an assumption. Lookup inside the function uses the
same module globals and builtins, so it finds the same object the original
line would. `__name__` and similar runner-set names are treated the same
way. A name that might be either a module binding or a builtin
(`builtin_fallback`, for example `len` assigned inside an `if`) is still
refused with PLAN003.

## Why PLAN008 exists

In the draft, the region's assignments are local to the function. The module
globals are only updated when the caller receives the returned values. Code
that runs during the region and reads those globals would therefore see the
old values. For example:

```python
rate = 0.1


def total(amount):
    return amount * (1 + rate)


rate = 0.2           # selected
result = total(100)  # selected: 120.0 originally, 110.0 in a naive draft
```

A regression builds this naive draft with the check disabled and executes
the test-authored fixture both ways to show the difference is real.

Code from other modules cannot read this module's globals except through
reflection (see limits). So the check looks, lexically, at every function,
lambda, method and generator expression defined before the region, including
nested ones, lambdas inside comprehensions, decorators' wrappers and class
methods. Parameters, local variables and closure variables are not globals.

The region gets a located PLAN008 when it contains code-running syntax
(calls, attribute or item access, operators, comparisons, `and`/`or`,
conditional expressions) and one of these holds:

1. Module code reads a global that the region assigns in an **earlier**
   statement than a later code-running statement. A call in the same
   statement as the write runs before the write, so it is safe.
2. Module code declares `global name` for a name the region reads or
   returns; a call could rebind it.
3. Module code uses a dynamic namespace spelling (`globals()`, `exec`, ...),
   so it could read or rebind anything.

Operators count because `__add__` and similar methods can be module code.
A region that only uses operators and no module code is defined keeps its
M2a behavior.

## Snippets

The snippet workflow now keeps leading imports and function/class
definitions outside the function, along with literal setup under the
default `parameters` policy. A notebook cell that starts with imports and
helper definitions can therefore produce a draft. `SNIPCALL` questions now
ask what a callable does rather than saying calls are unsupported. Wrapped
drafts write calls conventionally: `math.hypot(a, b)`, `round(x, ndigits=2)`.

## Limits

- Detection is lexical. Reflection (`sys._getframe`, `inspect`,
  `import __main__`, another module writing this module's attributes) and
  code created at runtime are not detected.
- Closure variables are approximated; unknown cases count as globals
  (possible over-refusal, never under-refusal among the cases handled).
- A call may raise, leaving earlier assignments unpublished; this is the
  existing `binding_visibility` limitation.
- Calls are not resolved: their types, effects and exceptions are unknown.
  Snippet type proposals are therefore unknown for call results.

## Validation

Eleven added tests in `tests/test_plan_calls.py`: a realistic region with
calls, attributes, slices and comparisons executed both ways; the delayed
read refusal and its demonstrated difference; same-statement writes;
helper locals and closures not being treated as globals; `global`
declarations; dynamic namespace use; lazy generators and methods; and two
snippet cases (leading setup, wrapped call spacing). Five existing tests
that asserted the old call refusal were updated. An additional probe of 16
patterns (properties, `__add__`, decorators, generator functions, lambdas
in comprehensions, parameter shadowing) refused all 11 unsafe patterns and
accepted all 5 safe ones with identical results.
