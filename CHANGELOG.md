# Unreleased

- `refine` (and RefacTrail's `fix`) is faster on very large files: the
  names a statement may unbind are computed once per statement instead
  of once per candidate split (2.6 times fewer seconds on the slowest
  corpus file under the profiler). Output is unchanged on
  all 584 standard-library and 6,988 corpus files; the slowest corpus
  file now takes 13 s instead of over 20 s.
- Robustness sweeps on the 6,988-file corpus: `refine` with splitting,
  docstrings and wrapping ran without a crash and every changed file
  compiles; `modularize` planned 5,669 files and refused 1,318 with
  located reasons. A program nested too deeply for Python's recursion
  limit is now refused with READ001 instead of failing, and a wildcard
  import inside a block (`try: from fast import *`) is refused with
  MOD004 at its line instead of the generic MOD007.
- docs/INTERFACES.md lists the commands, options, exit codes, codes,
  output formats, Python API and safety guarantees kept stable through
  the beta.
- `funcloom` without arguments shows a short quick start.
- VS Code: the extension uses the interpreter selected in the Python
  extension when `funcloom.pythonPath` is empty (the new default), and
  offers one-click Install/Update when FuncLoom is missing or outdated.
- pre-commit hook `funcloom-check`; README quick start.
- Package metadata and README describe FuncLoom as the Python
  functionizer, with keywords and family links to RefacTrail.

# 0.10.3a0 - strict-profile migration, local candidate, 2026-10-02

- FuncLoom's own source now passes RefacTrail's strict profile: 222
  module functions renamed to verb-first names with dtype suffixes, about
  220 generic loop/comprehension names (`item`, `value`, `info`) replaced
  by type-derived names, constants moved after the imports, 79-column
  lines and every function within the 50-line limit. 0 errors remain;
  32 functions of 41-50 lines carry advisory preferred-size warnings.
  Renames were scope-resolved and verified by syntax-tree comparison.
- Public API (`funcloom.__all__`), CLI and JSON schemas are unchanged.
  Internal module function names changed; code importing private
  modules must use the new names.
- Removed four unused imports found by RefacTrail's corrected RC202.
- Pre- and post-migration builds give byte-identical output on 102
  differential runs: every example script and notebook (modularize,
  check, refine) and three real repositories (439 generated files).
- New `tests/test_behavior_matrix.py`: decorators, inheritance and ABCs,
  exceptions and context managers, mutation and aliasing, early, late and
  fallback imports, async and generators, closures and walrus keep their
  output after modularize (script and notebook form) and after refine
  splits long loops, generators, coroutines and methods; wildcard
  imports, effectful annotations and global rebinding are refused with a
  code and line. 276 tests.
- Editor: a refused modularize or refine now shows an error naming the
  diagnostics instead of only opening the JSON report. New automated
  extension-host workflow test (`editor/funcloom/test/host_workflows.js`).

# 0.10.2a0 - local release preparation

- Keep decorated definitions, classes with bases and descriptors, and
  effectful definition expressions in their original execution position.
- Refuse effectful module annotations during modularization. Unknown power
  result types and inherited constructor results remain unknown.
- Add regressions for shadowed decorators, subclass hooks, annotations and
  conservative type evidence.
- Prepare a thin VS Code extension, local VSIX builder and multi-platform
  CI definition. Nothing is published by this increment.

# Changelog

## 0.10.1a0 - local release preparation, 2026-10-01

- Preserve unused and repeated initial imports in an ordered `_imports.py`
  module; keep later imports at their original execution point. Refuse
  wildcard imports instead of guessing exported names (MOD004).
- Define split helpers before their owning definition and decorators.
  Quote helper annotations to avoid repeating annotation side effects.
- Compile `refine` inputs and final outputs before writing; fail with a
  located diagnostic for parseable but invalid Python. Validate API profiles.
- Refuse comment wrapping that would create a new tool directive (SNIP004).
- Add 14 regression tests, including behavioral import/decorator comparisons,
  compile-failure paths and directive source locations.
- Select MIT, update package metadata and scope documentation, and add local
  wheel/sdist build, metadata, installation, regression and uninstall checks.
  Local reports and development history are excluded from distributions.
- Review fixes: helper annotations are quoted exactly once (quoted forward
  references such as 'Box' were quoted twice), and helpers are inserted
  above the comments directly preceding a split definition, never above a
  shebang or encoding line. Two regressions added. The artifacts in
  dist/0.10.1a0 predate these fixes and must be rebuilt.
- Fixes found by converting three real repositories (19 entry scripts;
  before them 16 were refused with MOD007 and many splits failed to
  verify; now all 19 convert and every split verifies):
  - lines inside multi-line strings (docstrings) are never re-indented,
    so functions kept in steps keep their docstrings and comments;
  - line wrapping keeps Python 3.12 f-strings whole instead of spacing
    their parts apart;
  - a single wrapped result is written `x = helper(...)`, never
    `(x,) = helper(...)`, and a single wrapped value is not a tuple;
  - config.py imports names its constants' annotations read (`Literal`);
  - folders holding `pyvenv.cfg` are skipped whatever their name;
  - a copied file that does not compile is copied unchanged with warning
    MODW07 in folder mode (single-file `refine` still refuses it);
  - Windows paths over 259 characters are refused before writing, with
    the path, when long paths are disabled;
  - a script imported anywhere by its bare name (for example by a test
    after a `sys.path` change) is not converted;
  - a script-like module inside a package (a folder with `__init__.py`)
    is only converted when chosen with `--entries`, because it may be
    imported by its dotted name at run time.
  Eight regressions added. Behavior was compared per test on two of the
  repositories: identical outcomes (see docs/BUILD_VERIFICATION.md).
- Opt-in `--trust-with-blocks`: values bound in with bodies count as bound
  unless a context manager is a known suppressor; modularize suggests it
  when with blocks forced step merges.
- Converted notebooks define Jupyter's `display()` (IPython, else print)
  and report MODW08.
- Fixes found with the owner's private example notebooks and script:
  - returns inside a nested function of a split piece were rewritten as
    early exits of the outer function (a nested `return df` became a
    tuple); an independent check now requires nested functions, classes
    and lambdas to move unchanged;
  - a single pipeline result on a wrapped line, and a single step output
    on a long return line, were written as one-item tuples; step returns
    and pipeline calls are now verified against their unwrapped form.
  - `scripts/verify.py` counts example files instead of assuming ten.
  Seven regressions added.
- Production-review fixes (seven behavior probes):
  - definitions move out of the step flow only when defining them cannot
    have effects (pure decorators, defaults, annotations, bases and class
    bodies); otherwise they keep their place and order, with a note;
  - module-level annotations that could have effects are refused (MOD010);
  - magic-looking notebook lines inside multi-line strings are kept;
  - only sources declaring UTF-8 are rewritten; others are refused by
    `refine` or copied unchanged in folder mode, and written files never
    carry a foreign coding declaration.
  Nine behavioral regressions added.
- The owner's private examples were replaced by original examples on
  unrelated topics (`examples/notebooks/*.ipynb`,
  `examples/greenhouse_sensors.py`) with the same code patterns; all seven
  convert to packages with identical output on Windows and Linux, and
  `tests/test_examples.py` converts them on every run.
- This candidate is unpublished. GitHub creation, TestPyPI, PyPI, editor and
  Product Hunt publication await the owner's later instruction.

## 0.10.0a0 - block splitting, generators, type hints, 2026-10-01

- Split the body of a long `for`, `while`, `if`/`else` or `with` block in
  place when the function's own statements cannot be cut usefully. Loop
  pieces carry values between rounds; returns inside the block use the
  exit protocol. Blocks with loop-level `break`/`continue`, late-bound
  closures, closures defined before the block, `with` values used after
  it, or values that may be unbound stay whole with a reason. Splitting
  runs in up to four verified rounds, so nested long blocks are reached.
- Split generators with `yield from` helpers and coroutines with `await`
  helpers; async generators stay whole.
- Add certain type hints to step and helper parameters and results.
- Keep each file's line endings (LF, CRLF, CR) in generated and refined
  files.
- Convert scripts that read `__file__`: generated modules point it at the
  script shim or `main.py` next to the package (warning MODW06).
- Fix: a step or helper that rebinds an earlier value only on some paths
  now receives it as a parameter; before, returning it raised
  `UnboundLocalError` when the rebinding was skipped (found by a probe).
- `for`/`with` targets count as bound inside their own body, so nested
  loops no longer look like reads before binding.
- A function that is long only because of one statement that cannot be
  split is left whole instead of being wrapped in a helper.
- Linux wheel install test: built, installed into a clean venv, tests,
  verification and CLI smoke checks against the installed package.

## 0.9.0a0 - refine: split long functions, document, 2026-09-30

- Split functions and methods over 40 lines into private, documented
  helpers, keeping the name, signature, docstring and result. Cut points
  minimize the values passed; early returns use an explicit exit flag.
  Pieces merge where a split would change behavior; generators, `global`,
  `locals()`, `super()`, mangled names and unbound-local reads keep the
  function whole.
- Verify each split: helper statements equal the original body, generated
  calls and returns match a canonical form, and no new undefined names.
- `--document` adds Args/Returns/Warnings docstrings stating only the
  signature; removing them must restore the original syntax tree.
- `funcloom refine FILE|FOLDER --output OUT`; refinement also runs in
  `modularize` (single file and folder mode). `--keep-long-functions`
  turns splitting off.
- Certain-binding analysis now accepts guard clauses, `try` bodies whose
  handlers return or raise, and `:=` in tests.
- Add `examples/long_functions.py`, a verify step, `docs/REFINE.md` and ten
  regressions. Two bugs found by running refined code were fixed and the
  verifier now also checks generated calls and returns.

## 0.8.0a0 - folder mode and wrapping inside blocks, 2026-09-30

- `funcloom modularize FOLDER`: every entry script becomes a package plus a
  same-named shim, so existing commands keep working; library modules and
  data are copied unchanged; a root `main.py` runs any pipeline. Scripts
  that cannot be converted are copied unchanged with a reason.
- Entry detection skips tests, tooling, package files, imported modules
  and relative imports; `--entries` chooses explicitly; `--skip-data`
  leaves data out; MOD009 refuses more than 200 MB of other files.
- Wrap long simple statements at any depth, including loop bodies.
- Warn (MODW04) when a single script imports a module next to it.
- Six folder-mode regressions compare every command's output between the
  original and the converted project.

## 0.7.0a0 - modularize: programs to packages, 2026-09-30

- Add `funcloom modularize` and `modularize_report`: a script, snippet,
  whole notebook or selected cells become a package with `config.py`,
  `functions.py`/`models.py`, `steps.py`, a `Pipeline` class in
  `pipeline.py`, `__main__.py` and a `main.py` with a `__main__` guard.
- Steps follow notebook cells and commented script sections; parameters
  and returns carry only values later code reads. Steps are merged when a
  split would change behavior (unbound values, late-bound closures).
- Refuse `globals()`/`exec`, `global`, late `import *`, `__file__` and
  executable `__name__` (MOD001-MOD007); never write into a non-empty
  folder; verify compile, syntax-tree equality and name resolution first.
- Add `examples/modular_sales_report.py`, an end-to-end verify step,
  `docs/MODULARIZE.md` and 13 behavior-comparison tests. A probe found and
  fixed `+=`/`del` reads across steps and the `__name__` behavior change.
- The owner chose to write output before M2b was complete.

## 0.6.0a0 - M2b.5 in-place statements, 2026-09-30

- Accept `+=` and other augmented assignments, item and attribute
  assignment, expression statements such as `rows.append(x)` or
  `df.dropna(inplace=True)`, starred unpacking and chained assignment in
  selected regions. `del`, annotated assignment, nested unpacking and
  control flow stay refused.
- Regions that bind no names produce `return None` and a plain call.
- Snippets: type proposals and mathematical names for the new forms;
  renaming skips attribute and keyword-argument names; every supported
  statement form can be wrapped, with `x = (` heads correctly spaced.
- `examples/plan_refused.py` now shows an `ambiguous` read (PLAN003).
- Add [M2B_STATEMENTS.md](docs/M2B_STATEMENTS.md) and six regressions;
  update ten tests that asserted the old refusals.

## 0.5.0a0 - M2b.4 calls in selected regions, 2026-09-30

- Allow calls, attribute and item access, slices, comparisons, `and`/`or`,
  conditional expressions and container displays in selected assignments.
- Add PLAN008: refuse when a function, method, lambda or generator defined
  before the region could read a global the region assigns earlier, or
  declares `global` for a contract name, or uses a dynamic namespace. A
  regression shows the naive draft really changes a result (120 vs 110).
- Keep builtins and runner-set names with no module binding as free names
  instead of refusing them; frame-dependent names (`locals()`, `eval`...)
  are refused in the region.
- Snippets keep leading imports and definitions as setup; SNIPCALL wording
  updated; wrapped drafts write `f(x)`, `a.b` and `key=value` without
  extra spaces.
- Add `examples/plan_calls.py`, a verify step, 11 regressions and
  [M2B_CALLS.md](docs/M2B_CALLS.md); update five tests that asserted the
  old call refusal.

## 0.4.0a0 - M2b.3 resolution-gated prefix, 2026-09-30

- Accept any compilable Python before the selected region (imports,
  definitions, calls, loops, conditionals, `with`) when every name the
  region reads resolves `direct`. The prefix is never moved.
- Refuse other statuses with PLAN003 naming the status and reason, for
  example `ambiguous` after a conditional or `global` rebinding. PLAN005
  is retired. The selected-statement subset is unchanged.
- Take annotation evidence only from top-level declarations; propose
  snippet input types only for `direct` inputs.
- Add `examples/plan_prefix.py`, a verify step and six regressions,
  including a trusted result comparison on a realistic script.
- Record the first Linux run (Ubuntu 24.04 on WSL2, Python 3.12.3):
  0.3.3a0 passed 163 of 163 tests with no skips.

## 0.3.3a0 - review fixes, 2026-09-30

- Never split or move tool-directive comments (`# type: ignore[...]`,
  `# noqa`, `# pragma`, `# fmt:`, `# pylint:`, `# nosec`, and mypy,
  pyright, ruff, isort and flake8 forms). Short lines keep them verbatim;
  a line that would need wrapping is refused with located `SNIP004`.
- Apply the 40-200 line-length range to rule profiles as well, through
  one shared validator. Profile values such as 10 or 201 now fail at load
  time with the same message as the CLI, instead of "invalid width -2" or
  an accepted 201.
- Add four regressions reproducing the review findings.

## 0.3.2a0 - line wrapping and user line length, 2026-09-30

- Wrap long source lines in snippet drafts, not only lines lengthened by
  renaming. Long standalone and trailing comments are split into several
  comment lines with every word kept. Docstring warnings wrap too.
- Let the user choose the maximum line length (40-200, default 79) with
  `--line-length` on snippet/check/plan, `line_length` in context TOML,
  or the new wizard question. Width refusals name the line length and cap.
- Fix drafts from sources using bare carriage-return line endings, which
  were refused with a misleading structure message.
- Give a specific error for a keyword or invalid name in `[names]`,
  `[descriptions]` or `[input_types]` instead of a function-name message.
- Add 11 regressions, including trusted result comparisons at widths
  60-120; update four wizard tests for the new question.

## 0.3.1a0 - generic-variable context, 2026-09-30

- Add source/domain/mathematical naming preferences through CLI, TOML and API.
  The wizard's project mode now captures names and meanings/units for each
  discovered contract value; option 3 offers neutral mathematical naming.
- Propose operand and expression-role stems without inventing domain meaning.
  Retain source mappings and name evidence in additive snippet-1 fields.
- Expose optional meaning, direct-overwrite, unresolved-call and invalid-
  syntax questions without widening extraction eligibility or enabling apply.
- Wrap long renamed assignment drafts inside parentheses; preserve token
  content and validate renamed ASTs, syntax and hard source-size limits.
- Add 18 regressions, mathematical/domain examples, VS Code tasks and guides.
  The exact input/decimal/log pseudocode example remains unsupported.


## 0.3.0a0 - local contextual snippet increment, 2026-09-30

- Add `snippet` for Python text, .py files and one selected .ipynb code cell.
- Offer no-context or small-context terminal choices, structured TOML,
  stdin input and public snippet APIs. Batch commands never prompt.
- Propose computation boundaries, operation names, narrow numeric types,
  local dtype names, documented functions and callers. Keep inferred types
  unverified and ask focused questions for unresolved choices.
- Preserve source, retain plan-3 evidence inside snippet-1 reports, reject
  unsupported cases, and keep all apply/behavior-verification flags false.
- Add 35 regressions, runnable Python/notebook/context examples, VS Code
  tasks, verification steps and a complete workflow guide.

## 0.2.2a0 - local M2b.2 increment, 2026-09-30

- Add lexical module-scope binding resolution to candidate and refused
  plans: located binding sites with certainty, plus a status and the
  reaching sites for the first selected read of each name.
- Model conditional paths, deletions, exception targets, loop targets and
  back edges, walrus leakage from comprehensions, match captures, wildcard
  imports, `global` declarations and namespace-call spellings.
- Use `plan-3` for the extended schema; preserve M2a eligibility and every
  refusal/apply restriction. M2b is not complete.
- Add 15 binding regressions, including a trusted `NameError` fixture.

## 0.2.1a0 - local M2b.1 increment, 2026-09-30

- Add partial, source-located effect inventory to candidate and refused plans.
- Record possible calls, operators, direct aliases, object access, imports,
  annotations, control flow, opaque scopes, and delayed binding visibility.
- Use `plan-2` for the extended report schema; preserve M2a eligibility and
  every refusal/apply restriction. M2b is not complete.
- Add 13 effect regressions, including an exception counterexample.
- Review the three supplied archives and document the product/release path.


## 0.2.0a0 â€” local M2a delivery, 2026-09-29

- Added explicit module-scope extraction review plans, user-selected line
  ranges and function names, CLI/API, JSON/text, and refusal diagnostics.
- Retained source text/hashes; reported inputs, all assigned outputs,
  unverified annotations, compiled previews, and unresolved validation work.
- Added 37 planning and CLI tests, including synthetic normal-completion
  comparisons and the earlier prototypes' failure classes.
- Recorded the user's successful Windows M1 run: 29 passes and one expected
  symlink privilege skip on Python 3.12.13.
- Added side-by-side Windows setup and the exact supported planning subset.
  Applying edits and broader nested/call/effect analysis remain future work.

## 0.1.0a0 â€” local M1 delivery, 2026-09-28 UTC

- Added read-only Python file/repository inventory and objective rule checks.
- Added versioned JSON/text reporting with explicit incomplete-analysis and
  coverage flags, source hashes, lexical scopes, and declared annotations.
- Added CLI/API entry points, strict profile loading, and report creation
  that refuses to overwrite an existing path.
- Added regression tests, synthetic examples, VS Code tasks/debug settings,
  packaging metadata, Windows setup, and project continuation documents.
- Kept transformation, full semantic rules, draw.io generation, AI adapters,
  custom editor extensions, and public distribution as later milestones.

This entry records a development artifact, not a PyPI or GitHub release.
