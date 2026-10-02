# Rule contract and implementation coverage

The M1 `scan`/`check` contract below remains the base checker in 0.10.1a0. The
`plan` command has a separate, bounded contract in
[EXTRACTION_PLANNING.md](EXTRACTION_PLANNING.md). Its drafts are review aids,
not fully annotated or semantically verified generated application code.

## Requested full profile

The user wants understandable modular code, explicit functions and justified
classes, meaningful domain-oriented names, input/output annotations, and
useful documentation. Prefer variables shaped as `<meaning>_<dtype>`;
include a physical unit when established, for example
`duration_seconds_float`. Functions should name an operation and, where
helpful, its return type. Never invent a dtype or unit just to satisfy a
naming convention. Required framework/protocol names and public interfaces
need compatibility-aware exceptions.

Docstrings need a concise operation summary, short explanation when useful,
arguments, returns, and warnings. Add known exceptions or yield semantics
where relevant. A plausible template is not evidence of correct meaning.
Use uppercase immutable constants after imports only when relocation is
semantically safe. Mutable objects, import timing, and expressions with side
effects must not be blindly hoisted.

Aim for functions of at most **40 physical lines**, with **50** as the hard
cap. A top-level orchestration function and `if __name__ == "__main__"` block
have a **100-line** cap; new main guards should normally be just a few lines.
Lines have a **79-character** default cap. The user can choose 40-200
with `--line-length`, context TOML, the wizard or the rule profile;
every entry point applies the same range (0.3.3a0). Different
scripts should own coherent modules, with explicit imports and orchestration
that preserves actual branches, loops, exceptions, ordering, and state.

Classes are useful for state/invariants, not a mandatory wrapper around every
operation. Generated customer test files are secondary; engine regression
tests are required before claiming a transformation is dependable.

## Objective checks implemented in M1

| Code | Meaning | Severity |
| --- | --- | --- |
| READ001 | Source cannot be read/decoded or exceeds the file limit; some analysis resource failures also use this code | Error |
| PARSE001 | Parsing or contextual compile validation fails | Error |
| FMT001 | A decoded source line exceeds the configured character cap | Error |
| SIZE001 | Non-orchestrator function exceeds the 40-line target but stays within the hard cap | Warning |
| SIZE002 | Non-orchestrator function exceeds 50 lines | Error |
| SIZE003 | Configured top-level orchestration function exceeds 100 lines | Error |
| SIZE004 | Recognized top-level main guard exceeds 100 lines | Error |
| TYPE001 | Parameter annotation is absent | Warning |
| TYPE002 | Return annotation is absent | Warning |
| DOC001 | Function docstring is absent | Warning |
| DOC002 | A configured docstring section heading is absent | Warning |
| NAME001 | Parameter name contains only one character | Warning |

The `scan` command inventories declarations and reports read/parse/compile
failures. `check` additionally applies the ten objective style checks.
Missing types are reported, not fabricated. `self` and `cls` are exempted
from parameter checks for class-owned functions as a simple convention;
descriptor/decorator resolution and receiver semantics are future work.
Local variables and attributes are not checked by NAME001.

Function length runs from its earliest decorator (or `def`) through the
AST-reported end of its last statement. Intervening blank lines and comments
count. Trailing comments after the last syntax node are outside that extent.
Nested functions count within the outer extent and are also checked
independently. Only a configured name at module scope gets the orchestrator
exception; a method named `main` does not.

M1 recognizes a main guard only when the condition is a single equality
comparison between `__name__` and the string `"__main__"`, in either order.
Equivalent compound expressions are not inferred. Docstring checking looks
for exact standalone `Args:`, `Returns:`, and `Warnings:` headings; `Yields:`
can satisfy `Returns:`. It does not verify that the content matches the code
or accept every documentation convention. Character counts use Python
string length, not display columns or byte length; tabs count as one.

## Configuration

Load an explicit configuration file with
`--config profiles/domain_explicit.toml`. It contains one `[profile]` table.
Unknown keys and invalid values fail instead of being silently ignored.
No parent-directory or executable config is loaded automatically.

| Setting | Default |
| --- | --- |
| name | `domain_explicit_m1` |
| line_length | `79` (whole number, 40-200) |
| function_target_lines | `40` |
| function_max_lines | `50` |
| orchestrator_max_lines | `100` |
| main_guard_max_lines | `100` |
| max_file_bytes | `2000000` |
| main_function_names | `["main"]` |
| doc_sections | `["Args", "Returns", "Warnings"]` |
| excluded_dirs | Common environment, version-control, cache, build, and dependency directories listed in `config.py` |

Omitted settings retain defaults. Providing `excluded_dirs` replaces that
list; it does not append. Directory names ending in `.egg-info` are also
excluded. Symlink entries encountered during traversal are skipped, and a
symlink supplied directly as the target is rejected. This is ordinary
filesystem discovery, not a hostile-filesystem sandbox. No `.gitignore`
parser is included. The older broad design-profile document is a future
specification; only the settings above are implemented by this loader.

## Report interpretation

- `schema_version` and `tool_version` identify the report contract.
- `modules` retains relative paths, original-byte SHA-256, declarations,
  import syntax, and top-level source boundaries. Imports are not resolved
  into a dependency graph. Qualified names describe lexical ownership;
  repeated definitions may share a name and are distinguished by spans.
- `analysis_complete` means all selected files were read and compiled.
  Excluded entries remain excluded; this flag does not mean every repository
  file, language, or rule was analyzed. Style errors do not make parsing
  incomplete.
- `checks_run` and `limitations` state coverage. `all_rules_implemented` and
  `behavior_verified` remain false in M1, even for a clean report.
- Reports are deterministic for the same root path, interpreter, source
  bytes, selected files, and profile. Absolute root paths differ across
  machines. Running another Python version can change supported syntax.

## Deferred semantic work

The `snippet` workflow now proposes local dtype names, narrow built-in
numeric annotations and source-derived or user-described docstrings.
Version 0.3.1a0 adds explicit domain mappings and neutral mathematical roles,
with name evidence and optional meaning questions. Long renamed assignment
drafts can be parenthesized and wrapped before hard-cap validation.
These are explicitly unverified proposals. Unknown/mixed types do not
receive new inferred dtype suffixes; collisions are refused. Project prose
is labeled documentation, not executable intent. Generated previews enforce
the hard function/line limits before becoming candidates. See
[SNIPPET_WORKFLOW.md](SNIPPET_WORKFLOW.md).

The separate `modularize` and `refine` commands now write new output trees
with bounded module splitting, literal constant moves and function splitting.
Still deferred: general meaning-aware renaming/type inference, schema/units,
broader scope/effect resolution, applying saved extraction plans, arbitrary
prose-to-code and architecture generation. Neither a clean check nor a
compiled draft establishes complete rule compliance or runtime equivalence.

The future RefacTrail profile should make strong naming conventions opt-in
for adoption in existing projects. Existing public APIs, reflection, string
references, keyword callers, and external imports need explicit analysis
before renaming.
