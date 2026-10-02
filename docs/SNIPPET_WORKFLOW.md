# Snippet and notebook workflow

FuncLoom **0.6.0a0** provides review drafts from pasted Python, a small Python
file, or one Python notebook cell. Optional project context controls names,
descriptions and proposed numeric types. No LLM, kernel or runtime dependency
is required. The existing explicit `plan` command is unchanged.

## Try the supplied example

`examples/snippet_tax.py` contains exactly this calculation:

```python
base_amount=120
tax_rate= 0.1

tax_amount = base_amount * tax_rate
total_amount = base_amount + tax_amount
```

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_tax.py --interactive
```

The terminal offers:

```text
Context: [1] No additional context [2] Small project context [3] Mathematical naming (1):
```

The wizard then asks for the maximum line length (Enter keeps 79).
Press Enter or enter `1` for a source-derived proposal. Enter `2` to provide
brief project context, an optional operation summary and function name,
and optional `int`/`float` declarations for discovered inputs. Project mode
also asks for a local name and meaning/units for each discovered input/output.
Enter `3` for neutral mathematical names without supplying a domain.
Empty answers keep defaults or leave meaning unresolved. Invalid declarations
produce an explicit error. See [GENERIC_VARIABLES.md](GENERIC_VARIABLES.md).

Without project context, the draft uses `calculate_total_amount_tuple`,
`base_amount_int` and `tax_rate_float`. It proposes `int` for the literal
`120`; it does not assume that all amounts should be floats.

For repeatable, noninteractive operation:

```powershell
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_tax.py --no-context
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_tax.py --context profiles\snippet_tax.toml
```

Commands without `--interactive` never prompt. The default is no project
context. `--no-context`, `--context` and `--interactive` are mutually exclusive.

## What the contextual example produces

The supplied TOML declares numeric input proposals, descriptions, and a
function name. Its actual function preview is:

```python
def calculate_invoice_totals_tuple(
    base_amount_float: 'float',
    tax_rate_float: 'float',
) -> 'tuple[float, float]':
    """Calculate tax and the total amount including tax.

    Use the selected source expressions.
    User context: Invoice calculation; preserve the supplied arithmetic.
    Args:
        base_amount_float (float): Amount before tax.
        tax_rate_float (float): Fractional tax rate; 0.1 means ten percent.
    Returns:
        tax_amount_float (float): Tax amount calculated from the base
            amount and rate.
        total_amount_float (float): Base amount plus calculated tax.
    Warnings:
        Review required; proposed types are not runtime validation.
        No extra rounding, conversions or input checks are added.
    """

    tax_amount_float = base_amount_float * tax_rate_float
    total_amount_float = base_amount_float + tax_amount_float
    return (
        tax_amount_float,
        total_amount_float,
    )
```

The draft caller retains the original external names. The leading setup
assignments remain outside the function:

```python
base_amount=120
tax_rate= 0.1

(
    tax_amount,
    total_amount,
) = calculate_invoice_totals_tuple(
    base_amount,
    tax_rate,
)
```

The caller preview contains the call, not the original setup. Keep that
setup when manually evaluating a reviewed draft. Engine tests execute only
test-authored fixtures; FuncLoom never executes customer snippets.

Quoted annotations avoid evaluating type names while defining the draft
function. They do not convert values or enforce runtime types. This example
still passes the original integer `120`; declaring `float` does not insert
`float(...)`, rounding or input validation.

## Optional context file

`profiles/snippet_tax.toml` demonstrates the complete input format:

```toml
[snippet]
project_context = "Invoice calculation; preserve the supplied arithmetic."
summary = "Calculate tax and the total amount including tax."
function_name = "calculate_invoice_totals_tuple"
literal_policy = "parameters"

[input_types]
base_amount = "float"
tax_rate = "float"

[descriptions]
base_amount = "Amount before tax."
tax_rate = "Fractional tax rate; 0.1 means ten percent."
tax_amount = "Tax amount calculated from the base amount and rate."
total_amount = "Base amount plus calculated tax."
```

The optional `[snippet]` setting `naming_mode` accepts `source` (default),
`domain` or `mathematical`. The CLI `--naming` option overrides that setting.

An optional `[names]` table maps original contract identifiers to meaningful
local stems. For example, `base_amount = "invoice_amount"` proposes
`invoice_amount_float` when the proposed type is consistently float.
Mappings affect function-local identifiers only; the caller keeps original
bindings. Collisions produce a located refusal. No project-wide renaming
occurs. The original and proposed names are both present in JSON.

Only `int` and `float` input declarations are supported. Arbitrary type
expressions are rejected, not evaluated. Mapping keys must identify actual
discovered inputs or outputs. Context cannot invent missing bindings or
override an unsupported transformation. Unknown settings fail explicitly.
Context files are capped at 64,000 bytes; individual strings at 2,000
characters. Long documentation can cause a preview size refusal.

Project prose is labeled as user context and preserved as documentation.
It does not automatically become business logic. Supply a concise summary
and value descriptions when you want more specific documentation.

## Selection and clarification

Leading imports and function/class definitions always stay outside the
function (since 0.5.0a0). By default, leading single-name literal
assignments also become caller setup.
The remaining module statements become the proposed selection; referenced
setup values become function inputs. Every selected assigned name remains
an output, following the existing planner contract.

This is a visible heuristic, not knowledge of whether a value is truly a
constant. Use `--literal-policy fixed` to keep literal assignments inside
the function instead. The same choice is available in TOML/API context.

A source containing only literal setup receives `needs_context` and a
question about keeping those assignments inside the function or supplying
a calculation. Interactive mode offers that choice. Empty/comment-only
source asks for assignments. Unresolved types generate questions and remain
unannotated; such questions can accompany a candidate. Missing external
bindings produce a refusal even if a type declaration is provided.

Automatic numeric proposals cover literals, aliases, unary plus/minus,
and built-in numeric `+`, `-`, `*`, `/`, `//`, `%`.
They assume built-in numeric operations and normal completion. Power,
non-numeric values, overloaded operations, runtime types and effects remain
unresolved. Mixed/unknown types receive no newly inferred dtype suffix.
A generated annotation is evidence-labeled as an unverified proposal.

## Notebook input and Python API

Use one selected code cell from a saved version 4 notebook:

```powershell
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_tax.ipynb --cell 2 --interactive
```

Cell numbers are **one-based document indices, including Markdown cells**.
A notebook with exactly one code cell selects that cell automatically.
Multiple code cells require `--cell`.

Only the chosen cell is analyzed. Other cells' code, stored outputs and
kernel state do not supply bindings or types. The cell must be self-contained
within the supported subset. Magics and declared non-Python notebooks are
unsupported. No notebook file or kernel is modified.

Inside a notebook using the environment where FuncLoom is installed:

```python
from funcloom import SnippetContext, plan_snippet_report

source_str = """
base_amount=120
tax_rate=0.1
tax_amount=base_amount * tax_rate
total_amount=base_amount + tax_amount
"""

proposal = plan_snippet_report(
    source_str,
    SnippetContext(
        project_context="Invoice calculation.",
        summary="Calculate tax and the total amount including tax.",
        function_name="calculate_invoice_totals_tuple",
        input_types={"base_amount": "float", "tax_rate": "float"},
    ),
)
print(proposal.status)
print(proposal.function_preview)
print(proposal.caller_preview)
```

Omit `SnippetContext(...)` for the no-context API. The API returns questions;
it never opens terminal prompts. `plan_snippet_file_report(path,
context_info=None, cell_index_int=None, profile_info=None)` reads documents.
`--config` and `profile_info` configure rule/size limits independently of
project context.

For piped source:

```powershell
Get-Content -Raw examples\snippet_tax.py | .\.venv\Scripts\python.exe -m funcloom snippet - --no-context
```

Stdin cannot also carry interactive answers or notebook cell selection.

## Reports, limits and next steps

Save a new report without overwriting source:

```powershell
.\.venv\Scripts\python.exe -m funcloom snippet examples\snippet_tax.py --context profiles\snippet_tax.toml --format json --output reports\invoice-snippet.json
```

Choose a new destination if that file already exists. Only `.json` or `.txt`
report outputs are accepted. The text report shows the contextual draft,
assumptions, questions, diagnostics, effect evidence and validation work.

The JSON `snippet-1` wrapper contains:
- Original source text, optional document SHA-256 and notebook cell index.
- `source_sha256`: the SHA-256 of the analyzed text encoded as UTF-8.
- Validated context including `naming_mode`, original/proposed values, type
  evidence, `name_evidence` and questions.
- Top-level contextual function/caller previews and `preview_compiles`.
- `plan`: the existing `plan-3` extraction evidence and its original,
  unrenamed base draft. Use the **top-level** previews for this workflow.
- `review_required=true`, `can_apply=false`, `source_rewriting=false`,
  and `behavior_verified=false`.

For Python files the nested plan retains the original-byte file hash.
For notebooks its source path includes `#cell=N` and its hash covers the
cell text; the separate document hash covers the original notebook bytes.
A contextual refusal can retain a valid base plan as evidence but has no
top-level contextual draft. Check the wrapper status first.

| Exit | Meaning |
| --- | --- |
| 0 | Candidate for review, possibly with unresolved optional type questions |
| 1 | Refused draft or required selection clarification |
| 2 | Invalid arguments/context, document I/O/shape failure or cancelled wizard |

Previews are parsed/compiled without execution and checked against an
independently renamed statement AST. Drafts must fit the chosen line
length and 50 physical function lines; the preferred target remains 40.
Oversize drafts are refused rather than silently truncated. Syntax and
structure checks are not a behavior-equivalence proof.

## Line length and wrapping

Every draft line must fit the chosen line length: **79 characters by
default**. Choose another whole number from **40 to 200** in any of these
ways. Later entries override earlier ones:

1. `line_length` in the `--config` rule profile (`[profile]` table).
   Since 0.3.3a0 the profile uses the same 40-200 range, so an invalid
   value is reported immediately rather than as a later draft error.
2. `line_length = 88` in the `[snippet]` table of a context TOML file.
3. `--line-length 88` on the `snippet`, `check` or `plan` command.
4. The interactive wizard, which asks right after the context choice:
   `Maximum line length, 40-200 (79):`. Press Enter to keep the shown
   value. Invalid answers are explained and asked again.

Long lines are wrapped in the draft, whether they were already long in
your source or became long after renaming. The original file or cell is
never changed.

- A long assignment is put inside parentheses and its tokens are packed
  onto as many lines as needed. Token content and order are unchanged.
  No space is added after `(`, `[`, `{` or before `)`, `]`, `}`, `,`.
- A long comment, whether on its own line or trailing an assignment, is
  split into several `#` lines. Every word is kept, in order; only the
  spacing inside the comment changes.
- Docstring text, including the fixed warnings, wraps to the width.
- Windows (CRLF), Unix (LF) and old Mac (CR) line endings are preserved.

Every wrapped draft is still compiled and compared against an independently
renamed syntax tree, so a wrapping mistake is refused, never emitted.
A draft is refused when something cannot be split: a single token such as
a long number or string, a very long name in the signature or caller, or
more than 50 function lines after wrapping. The refusal names the line
length found and the cap, for example `Draft line has 94 characters; the
cap is 79`. The base `plan` evidence inside a snippet report skips its own
width check so that wrapping can happen; the top-level draft enforces it.
**Tool directives are never split or moved.** Comments such as
`# type: ignore[...]`, `# noqa`, `# pragma: no cover`, `# fmt: off`,
`# pylint: disable=...`, `# nosec` and mypy/pyright/ruff/isort/flake8
directives apply to the physical line they are on. A short line that
carries one is kept exactly as written. If such a line is too long,
the draft is refused with `SNIP004`, located at that source line:
shorten the line or choose a larger line length. Recognition is by
comment spelling, so an ordinary comment beginning with, for example,
`# type:` is also treated as a directive.

Since 0.10.1a0 a wrap that would turn ordinary prose into a new directive
also receives SNIP004 at its original source line. For example, splitting
`# note ... type: ignore[assignment]` must not create a continuation line
starting with `# type: ignore[assignment]`. The comment is not silently
rewritten into a directive or discarded.

This is bounded draft formatting, not a general formatter.

Calls inside the calculation are supported since 0.5.0a0 (see
[M2B_CALLS.md](M2B_CALLS.md)), and in-place statements since 0.6.0a0
([M2B_STATEMENTS.md](M2B_STATEMENTS.md)). Branches, loops,
nested extraction, arbitrary prose-to-code, multi-cell orchestration and
automatic apply remain outside this increment.
See [EXTRACTION_PLANNING.md](EXTRACTION_PLANNING.md) for base eligibility and
[RELEASE_PREPARATION.md](RELEASE_PREPARATION.md) for scope/release limits.

VS Code's **Tasks: Run Task** includes contextual, interactive and notebook
examples. These are tasks using the same CLI; a dedicated extension remains
a later release.
