# M2a: explicit extraction review plans

Current contract: the `plan` command in **0.10.1a0**, including the extensions
below. Saved plans cannot be applied. Separate `modularize` and `refine`
commands write new copies; see MODULARIZE.md and REFINE.md.

Version 0.2.0a0 adds a `plan` command and the Python API
`plan_extraction_report`. It proposes a function and a caller for a precisely
selected module-scope region. It does not write, import, or execute target
code. A successful plan is a **candidate for review**, never an approval to
apply it. This is the first increment of M2; M2b remains ahead.

Version 0.2.1a0 retains this subset and adds partial effect evidence with
planning schema `plan-2`. See [M2B_EFFECTS.md](M2B_EFFECTS.md) for its exact
coverage. Version 0.2.2a0 adds lexical binding resolution with schema
`plan-3`; see [M2B_BINDINGS.md](M2B_BINDINGS.md). Source rewriting and
broader extraction remain unsupported.

## Try the included examples

From the installed M2a project in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m funcloom plan examples\plan_supported.py --start-line 7 --end-line 8 --name calculate_invoice_totals_tuple
```

Expected contract:

| Role | Names |
| --- | --- |
| Inputs | `base_amount_float`, `tax_rate_float` |
| Outputs | `tax_amount_float`, `total_amount_float` |
| Status | `candidate_for_review` |
| Runtime type evidence | Input annotations are declared and unverified; output types remain unknown |
| Application status | `can_apply=false`; no source edits |

The text output includes a draft function and caller. The operation name is
supplied explicitly by you, avoiding script-specific hardcoding or invented
domain meaning. Keep line numbers aligned with the current source file.

This second example must be refused:

```powershell
.\.venv\Scripts\python.exe -m funcloom plan examples\plan_refused.py --start-line 8 --end-line 8 --name calculate_net_amount_float
```

It returns exit **1** and `PLAN003`: `discount_rate_float` is set on only
one branch and has no earlier value, so at the selection it is
`possibly_unbound`. This is an expected verification case. (Before
0.6.0a0 this example used `+=`, and before M2b.7 it gave the name an
earlier value, which made it `ambiguous`; both are now supported.)

Save a new JSON report by appending:

```powershell
--format json --output reports\invoice-plan-001.json
```

Append those arguments to the full command; they are not a standalone
PowerShell command. Report destinations must be new `.json` or `.txt` paths.
Existing files are refused. JSON includes the selected source text, so review
its contents before sharing it.

## Exact supported subset

- One Python file and explicit inclusive one-based start/end lines.
- Whole statements directly in the module body. Leading/trailing comment or
  blank lines may be selected along with those statements.
- Each selected statement is one plain assignment to one name, such as
  `total = base + tax`. Since 0.5.0a0 the value may also use calls,
  attribute and item access, comparisons, `and`/`or`, conditional
  expressions and tuple/list/dict/set displays; see
  [M2B_CALLS.md](M2B_CALLS.md). Builtins with no module binding stay
  free names in the draft.
- Since 0.4.0a0 (M2b.3) the statements before the region may be any
  compilable Python: imports, function/class definitions, calls, loops,
  conditionals, `with` blocks and so on. They stay where they are and
  are never moved. Every name the region reads from before it must
  resolve as `direct` in the binding analysis
  ([M2B_BINDINGS.md](M2B_BINDINGS.md)): exactly one unconditional
  binding reaches it, with no later conditional, loop-carried,
  call-dependent or namespace-wide site. Import objects are not loaded.
- Every name written by the region is returned, including intermediates.
  Outputs follow first-write order; inputs follow their first read before
  any region-local write. Reassignment is analyzed in statement order.
- The proposed function name must be a valid normalized identifier and must
  not collide with an identifier found anywhere in the file or a builtin.
  This conservative collision rule is broader than module-scope bindings.
- The generated draft must compile, retain the original selected statement
  ASTs, and fit the configured function and line-width hard caps.

In particular, `amount = amount + 1` records `amount` as both an input and
output when it has a direct prefix binding. The spelling `len` is treated as
a real dependency if it was rebound; builtin names are never silently
discarded. An annotation-only statement does not establish a value binding.

Why this is sound for the supported region: the prefix runs unchanged and
at the same moment, and the draft caller passes each input's current value
at the selection's position. A `direct` status guarantees the name is
bound there by one known site. Since M2b.7 an `ambiguous` read is also an
input when every site reaching it is a module-level statement: an
unconditional binding precedes it and later sites can only rebind, so the
name is bound on every path and the caller passes whichever value it
holds. An ambiguous read reached by a function's `global` declaration or a
namespace call stays refused (that function could delete the name). Reads
that are `possibly_unbound`, `unbound`, `builtin_fallback` or `unresolved`
are refused with PLAN003 and the status in the message.

Since 0.5.0a0 `builtin_lexical` and `module_implicit` reads are not
refused: they stay free names in the draft (see M2B_CALLS.md).

Selected statements may call functions since 0.5.0a0, subject to PLAN008.
Since 0.6.0a0 `+=`, item and attribute assignment, expression
statements, unpacking and chained assignment are also accepted; see
[M2B_STATEMENTS.md](M2B_STATEMENTS.md). Since M2b.6 list, set and dict
comprehensions are accepted too; their free reads are resolved like any
other read (see [M2B_BINDINGS.md](M2B_BINDINGS.md#m2b6-comprehensions)).
Control flow, `del`, generator expressions and lambdas are still refused
(PLAN002). Whole-repo modularization is available through the
separate `modularize` command.

## Refusal diagnostics

| Code | Reason |
| --- | --- |
| PLAN001 | Empty/out-of-file selection, partial statement, nested scope, or semicolon group |
| PLAN002 | Unsupported selected statement or expression: control flow, `del`, annotated assignment, nested unpacking, lambdas, generator expressions, async comprehensions, `:=`, f-strings, frame-dependent names such as `locals()`, annotation moves, or multiline string literals |
| PLAN003 | A name read by the region does not resolve as `direct` before it; the message gives its status |
| PLAN004 | Proposed function name collides with a source identifier or builtin |
| PLAN005 | Retired in 0.4.0a0: an unsupported prefix no longer refuses a plan by itself |
| PLAN006 | Draft function/caller would exceed a configured hard size or line cap |
| PLAN008 | Module code defined before the region could observe a value the draft delays, or rebind one it passes or returns (M2B_CALLS.md) |
| PLAN007 | Draft compilation, structural validation, or bounded analysis failed |
| PARSE001 / READ001 | Full input source failed contextual syntax validation or reading |

Exit **0** means a review candidate was emitted, **1** means the plan was
refused, and **2** means invalid command/configuration/output usage. Invalid
request values, such as a negative line or invalid function identifier, are
usage errors. Refused plans may contain partial facts, but contain no
function or caller previews. `--apply` is not implemented.

## Source evidence and type honesty

`source_sha256` fingerprints the complete original bytes. `source_fragment`
retains the decoded selected lines and their line endings;
`fragment_sha256` fingerprints that text encoded as UTF-8. These hashes are
different concepts for non-UTF-8 input. M2a consumes neither archived plans
nor hashes to apply changes; a future apply operation must recheck the
complete current source and its own validity conditions.

The source file is parsed and compiled, never executed. The plan records
type annotations from the prefix as **declared_unverified**. It does not
infer runtime types from a literal, operator, function name, or variable
suffix. A declaration can be stale after reassignment. Draft signatures
leave annotations unresolved instead of moving potentially executable
annotation expressions. Draft docstrings describe source provenance and
contract structure; useful domain documentation is still a review task.

M2a retains source slices rather than regenerating statements from ASTs.
It indents those slices for a draft and compares the resulting statement
ASTs against the originals. A general concrete-syntax editing engine and
comment ownership model are still future work.

## Why every candidate still requires validation

Even simple operators can call user-defined methods. Added function scope
changes reflection, stack frames, object lifetimes, and namespace contents.
Returning outputs on normal completion also changes visibility of partial
assignments if a later statement raises. For example, `first = 1` followed
by `second = 1 / 0` binds `first` before failure in the original module;
an extracted call would not restore it before raising. M2a makes no
equivalence claim for such a candidate and provides no apply path.

The report therefore always records `review_required=true`,
`can_apply=false`, `source_rewriting=false`, and `behavior_verified=false`.
`preview_compiles=true` means only that the draft syntax and selected
statement structure passed the implemented checks.

## Python API

```python
from dataclasses import asdict
from pathlib import Path

from funcloom import plan_extraction_report

invoice_plan = plan_extraction_report(
    Path("examples/plan_supported.py"),
    start_line_int=7,
    end_line_int=8,
    function_name_str="calculate_invoice_totals_tuple",
)
print(asdict(invoice_plan))
```

Broader scope/effect analysis and explicit contracts remain necessary
before saved extraction plans gain an apply capability. This command
continues to preserve user scripts.
