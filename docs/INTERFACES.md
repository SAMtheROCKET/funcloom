# Stable interfaces (beta contract)

This page lists what FuncLoom keeps stable from the first beta onward,
so that scripts, CI jobs, RefacTrail, FlowBlueprint and editor
extensions can rely on it. Anything not listed may still change between
releases; such changes are named in the release notes.

During the beta, a stable interface changes only when a release note
says so and only after a deprecation period of at least one minor
release. Refusing more code (a new, located refusal for a pattern that
was handled unsafely) is a safety fix, not an interface change.

## Commands

| Command | Stable | Purpose |
| --- | --- | --- |
| `funcloom scan PATH` | yes | Inventory of files, functions and sizes |
| `funcloom check PATH` | yes | Findings against the rule profile (`--fail-on warning` for a stricter gate) |
| `funcloom modularize PATH --output DIR` | yes | Script, notebook, selected cells or a whole folder to a package with a `Pipeline` class and `main.py` |
| `funcloom refine PATH --output DIR` | yes | Split long functions, wrap long lines and optionally add docstrings, in a copy |
| `funcloom snippet` | yes | Draft one function from a code snippet, with questions for unclear names |
| `funcloom plan PATH --start-line --end-line --name` | yes | Plan extracting a selected region; never changes the source |
| `funcloom plan ... --apply-to NEW.py` | experimental | Write the rewritten module (region replaced by the function and its call) to a new file; the source is never changed |
| `funcloom doctor` | yes | Show the local runtime |

Stable options keep their names and meaning, including `--output`,
`--format`, `--config`, `--line-length`, `--cells`, `--entries`,
`--skip-data`, `--package-name`, `--document` (now the default;
`--no-document` turns it off), `--keep-long-functions`,
`--trust-with-blocks`, `--show-files` and `--fail-on`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Completed (for `check`: no finding at the failure threshold) |
| 1 | Findings at the threshold, or the operation was refused with located reasons |
| 2 | Usage, configuration or file-system failure |

## Codes

Rule codes (`READ001`, `PARSE001`, `FMT001`, `SIZE001`-`SIZE004`,
`TYPE001`, `TYPE002`, `DOC001`, `DOC002`, `NAME001`, see
[RULES.md](RULES.md)) and refusal codes (`PLAN001`-`PLAN010` in
[EXTRACTION_PLANNING.md](EXTRACTION_PLANNING.md), `SNIP` codes in
[SNIPPET_WORKFLOW.md](SNIPPET_WORKFLOW.md), `MOD001`-`MOD010` in
[MODULARIZE.md](MODULARIZE.md)) keep their meaning once released and
are not reused. Retired codes (such as `PLAN005`) stay documented.

## Output formats

- `text` is meant for people; its wording may change.
- `json` reports keep their field names and types; new fields may be
  added. Every finding or refusal carries a code, a severity, a message
  and a source location.

## Python API

These names exported by `funcloom` are stable: `scan_project_report`,
`check_project_report`, `plan_extraction_report`, `plan_snippet_report`,
`plan_snippet_file_report`, `refine_source_text`, `load_profile`,
`RuleProfile`, `RefinedSource` and `SnippetContext`.
`apply_extraction_result` and `ApplyResult` are experimental. Other modules are
internal and may move. RefacTrail and FlowBlueprint use only this API.

## Safety guarantees

- FuncLoom never imports or runs the code it reads.
- The original files are never changed; output goes to a new folder.
- A non-empty output folder is refused (MOD006); nothing is overwritten.
- Generated code is written only after it compiles, its statements match
  the original's, and its names resolve; otherwise the operation is
  refused with a located reason (MOD007, PLAN007).
- Unknown types stay unknown; FuncLoom does not guess annotations.

## Not yet stable

- Applying a planned extraction back to the source (`plan` only plans).
- The layout of generated packages beyond `main.py`, the `Pipeline`
  class and one module per step group.
- Message wording (codes and locations are stable).
