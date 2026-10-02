# Generic variables and mathematical operators

FuncLoom **0.6.0a0** supports three naming choices for its bounded snippet
drafts. Variable names such as `a`, `b`, `c` and `total` do not establish
physical meaning. The user can supply that meaning, or explicitly request
neutral mathematical names.

## Choose the interpretation

```powershell
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_generic.py --interactive
```

The wizard offers:

1. **No additional context**: keep source-derived names and expose optional
   meaning questions for single-character identifiers.
2. **Small project context**: collect a purpose, function name, optional
   numeric input declarations, and a local name plus description/units for
   each discovered input/output. Blank answers leave meaning unresolved.
3. **Mathematical naming**: propose neutral names from expression syntax.
   Ask for an optional operation summary, function name and input types.
   No physical meaning is invented.

Input/output values referring to the same source binding receive one name.
Meanings are collected once per identifier. Callers retain original names.

These choices apply to the existing notebook-cell workflow too. Batch/API
calls return questions in the report and never open terminal prompts.

## A working mathematical example

The included `examples/snippet_generic.py` is:

```python
b=3.0
c=4.0

a=b*c
total=a+(a/c)
```

Run:

```powershell
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_generic.py --naming mathematical
```

It proposes `evaluate_expression_tuple` and these local names:

| Original | Proposed | Evidence |
| --- | --- | --- |
| b | operand_1_float | First discovered input; proposed float type |
| c | operand_2_float | Second discovered input; proposed float type |
| a | product_value_float | Outermost expression is multiplication |
| total | sum_value_float | Outermost expression is addition |

The generated function includes annotations, a summary, Args, Returns,
Warnings, the original expressions with renamed locals, and a tuple return.
The unchanged caller setup supplies `b` and `c`; the call restores `a` and
`total`. As with other plans, all selected assigned names remain outputs.
Choosing the final result alone is not implemented by this increment.

Names based on mathematical roles are proposals. Operators can be overloaded,
and their spelling does not establish numeric types, units, purity or
business meaning. Unknown types stay unknown. Different values with the
same proposed role receive distinct stems. A name used for different
operations gets a neutral intermediate name; an input later reassigned
keeps one shared local identifier.

To give the operator your own name, add `--name evaluate_my_formula_tuple`
or use `function_name` in context. The engine does not solve simultaneous
equations or reorder assignments.

## Supply explicit domain meanings

Use the same source with the illustrative context file:

```powershell
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_generic.py --context profiles\snippet_domain.toml
```

That file explicitly supplies `b -> unit_mass`, `c -> item_count`,
`a -> shipment_mass`, `total -> adjusted_mass`, descriptions and a function
name. Those meanings are supplied by the example author, not inferred from
the arithmetic. No units or dimensional consistency are verified.

A minimal context can be:

```toml
[snippet]
naming_mode = "domain"
summary = "Evaluate the user-defined calculation."
function_name = "evaluate_custom_calculation_tuple"

[names]
b = "initial_operand"
c = "scale_factor"
a = "scaled_value"
total = "combined_value"

[descriptions]
b = "Starting numeric value."
c = "User-provided scaling factor."
a = "Product of the two inputs."
total = "Result of the supplied combination."
```

`naming_mode` accepts `source` (default), `domain` or `mathematical`.
`--naming` overrides the TOML preference. Explicit `[names]` overrides
automatic mathematical stems. Types still follow the narrow numeric
proposal rules and can be declared under `[input_types]`.
Prose alone does not generate per-variable mappings or executable logic.

The Python API accepts the same choices:

```python
from funcloom import SnippetContext, plan_snippet_report

proposal = plan_snippet_report(
    "b=3.0\nc=4.0\na=b*c\ntotal=a+(a/c)\n",
    SnippetContext(
        naming_mode="mathematical",
        function_name="evaluate_custom_expression_tuple",
    ),
)
print(proposal.function_preview)
```

The existing `snippet-1` JSON gains additive fields:
`context.naming_mode` and `values[].name_evidence`. Evidence is
`source_identifier`, `user_supplied` or `mathematical_role_proposal`.
`context_mode` continues to distinguish supplied project context from its
absence; a purely mathematical naming preference can have
`context_mode="none"`.

## Why the original rough example needs decisions

The requested rough example was:

```text
a = 99 + input(c)
a = b * c
b = (extract 2nd decimal of 'a')
total = log(b) + a + (a / c)
```

Several separate decisions are unresolved:

- **Execution order**: sequential Python overwrites `a` on the second line.
  The earlier input call can still have effects. If these are equations
  rather than ordered statements, a separate equation-solving feature is
  needed. FuncLoom does not delete or reorder these assignments.
- **External values**: `c` and the initial `b` need bindings before their
  reads in a self-contained script/cell. Context type declarations do not
  create those missing values.
- **Input**: if `input` is Python's built-in function, its result is text.
  Numeric conversion and whether input should happen outside the calculation
  must be explicit. A custom callable with that name could mean something
  different.
- **Decimal operation**: the hundredths digit and rounding to two decimal
  places are different operations. The quoted `'a'` is a string, not the
  variable `a`. Negative numbers and numeric representation may also need
  an explicit policy.
- **Logarithm**: identify the callable, logarithm base, valid input domain and
  intended treatment of invalid values.

The exact sample is not executable Python and is **not converted into a
function by this release**. Context naming does not override refusal.
A syntax failure now includes a located request for executable operations.
For syntactically valid assignment dumps, the report can ask about direct
overwrites and unresolved calls, including input/log spellings. Questions
do not execute or resolve the callable. The original source is retained.

| Question | Meaning |
| --- | --- |
| SNIPNAME | Variable meaning or a descriptive name remains unresolved |
| SNIPSYNTAX | Invalid Python needs executable operations and explicit order |
| SNIPWRITE | A direct assignment was overwritten without an intervening direct read in the inspected assignment sequence |
| SNIPCALL | What a called function does, and its types and effects, is unknown; the draft keeps the call as written |

Overwrite analysis is deliberately local syntax evidence. Aliases, indirect
reads, effects and scope boundaries prevent a general dead-code claim.
Other statement kinds end this local inspection sequence. Optional meaning
questions may accompany a candidate; syntax/call/missing-binding failures
remain refusals. No question response silently enables a transformation.

## Formatting and current limits

Renaming can make a valid statement longer, and source lines can already
be long. Since 0.3.2a0 both are wrapped to the chosen line length (79 by
default, 40-200 on request); long comments are split into several comment
lines. See the line-length section of
[SNIPPET_WORKFLOW.md](SNIPPET_WORKFLOW.md). Indivisible long tokens or
signatures, and drafts exceeding 50 physical function lines, still cause an
explicit refusal that names the line length and cap. Long lines carrying
tool directives such as `# type: ignore` are refused with `SNIP004`
instead of being split.

This is bounded draft formatting, not a general formatter. Source spacing
is retained where wrapping is unnecessary. Calls and in-place statements
are supported within M2B_CALLS.md and M2B_STATEMENTS.md. Decimal-operation
generation, equation solving and applying these drafts remain future work.
Separate `modularize`/`refine` commands write new trees. See
[SNIPPET_WORKFLOW.md](SNIPPET_WORKFLOW.md) for the full snippet contract.
