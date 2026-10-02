# M2b.1: partial effect evidence

Version 0.2.1a0 adds a syntax-based effect inventory to the existing `plan`
API and CLI. This is the first bounded M2b increment. M2b is not complete;
M2a's candidate/refusal subset and all source-writing restrictions remain.

## Report contract

The planning schema is now `plan-2`. All `plan-1` fields retain their meaning;
three new fields describe the inventory:

| Field | Meaning |
| --- | --- |
| `effect_analysis` | `not_run` if reading/compilation/selection prevented inventory; otherwise `partial` |
| `effects` | Deterministically ordered syntax observations with original locations |
| `effect_limitations` | Explicit boundaries of this inventory |

Each effect has `kind`, `region` (`prefix` or `selection`), `line`,
`column_utf8`, `end_line`, `end_column_utf8`, `detail`, and
`evidence="syntactic"`. Lines are one-based. Columns are zero-based UTF-8
byte offsets with exclusive ends, following Python AST positions. They
are not editor display columns; non-ASCII text requires conversion.

Recognized kinds include `call`, `operator`, `augmented_assignment`,
`object_access`, `import`, `annotation`, `raise`, `assert`, `delete`,
`named_expression`, `scope_boundary`, `control_flow`, `alias`, and
`binding_visibility`. An effect fact is not a refusal diagnostic and does
not change candidate eligibility. Refused complete regions can retain
useful facts, but still have no generated previews.

For example, the included invoice plan now records two operators and two
selected binding writes. A selected `value += 1` remains refused with
PLAN002 and also explains that in-place mutation/aliases are unresolved.
A direct `copy = value` records possible sharing without guessing a type
or claiming the value is mutable.

## Coverage boundaries

Inventory covers complete module statements before and inside a valid
selection. It excludes the suffix. Statements and expressions within control
flow are syntax occurrences, not proof of reachability or execution count.
Facts are sorted by source position and kind, not Python evaluation order.

Functions, classes, lambdas and comprehensions are opaque scope boundaries.
Their bodies and definition/iteration expressions are not traversed. This
avoids folding inner-scope effects into module facts, but leaves decorators,
defaults, class execution, closure bindings and comprehension behavior
unresolved. The scope-boundary fact explicitly records that limitation.

Annotations may be delayed or executable depending on interpreter, scope
and future flags. The inventory records syntax, never that evaluation
actually occurred. It does not resolve calls, build an alias graph, prove
purity, track exception paths or support new extraction contexts. Absence
of a listed effect is not evidence of effect-free execution.

Selected simple assignments record `binding_visibility`: after extraction,
module writes happen only when the generated caller receives returned values.
A later failure can prevent earlier results from being published. The new
synthetic regression demonstrates this with `first = 1; second = 1 / 0`
written as separate statements. It supports retaining `can_apply=false`,
not approving that transformation.

## Validation and next boundary

Thirteen added tests cover source preservation, locations including UTF-8
columns, candidates/refusals, aliases, augmented/object mutation, calls,
opaque definitions/comprehensions, control flow, future annotations,
invalid selections, suffix exclusion, repeatability, text/JSON output,
and the partial-write counterexample. Only the explicitly authored numeric
counterexample is executed; no arbitrary target code is run.

Lexical binding resolution followed in M2b.2 ([M2B_BINDINGS.md](M2B_BINDINGS.md)),
with schema `plan-3`. The remaining M2b work includes path-sensitive
reads/writes, exception and alias contracts, definition-time effects,
concrete-syntax edits and more counterexamples before any M3 apply path.
