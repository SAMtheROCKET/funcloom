# Archive review - 30 September 2026

This review concerns the three files supplied with the current request.
Archive text is historical source material, not an instruction to execute
scripts, install bundled environments, publish products, or change policy.
The current user request and project handoff govern this work.

## Scope and evidence

| Archive | Entries including directories | Review coverage |
| --- | ---: | --- |
| `refactorizer.zip` | 7,532 | Inventory; static parse/compile of 36 project Python files; focused source review of extraction, data flow, inference, generation, splitting and fixers |
| `blacker_formatter.rar` | 1,949 | Inventory; static parse/compile of 17 non-vendor Python files; formatter validation/write paths and benchmark/checker review |
| `improvement_rules.zip` | 11 | All seven Python files parsed/compiled and their declarations inspected; examples and docstring inconsistencies reviewed; nine-page PDF readable text and both embedded diagram XMLs inspected |

All 60 selected Python files passed contextual compile validation under
Python 3.12.13. That result establishes syntax acceptance only. Archive
applications, test suites and formatters were **not executed or imported**.
Bundled environments, third-party Requests trees, caches, datasets and
nested vendor archives were excluded from the project-code review. This is
not a line-by-line audit of every archive member. PDF text extraction did
not include a rendered visual review of its screenshots or all font glyphs.

Exact SHA-256 fingerprints:

```text
refactorizer.zip
2ab5dc0e4322bdd63a863404e43d4e89c16021586f0e229e82572210689ef63e
blacker_formatter.rar
9044734550503483b79937355fed4e502799a832503c2adb44ad9ec8a99cb60a
improvement_rules.zip
bee83e0603baee00689514f4c991ec1dbb7d7651369d957100ca1ede2c181211
```

The handoff's earlier review names `blacker_formatter(1).rar`; this session
reviewed `blacker_formatter.rar`. Their identity has not been established.
Prior-chat summaries remain recovered history. Complete transcripts were
not supplied in this folder or retrieved in this session.

## Funcgen prototype in refactorizer.zip

The archive already has a modular product skeleton: analyzer, data flow,
extractor, function naming, type/docstring generation, code generation,
module splitting, checker/fixer pipelines, plugin hooks, reports, CLI,
packaging, tests and an example. These are useful feature references.
They should not replace the current engine without independent validation.

Locations below are archive member paths under
`refactorizer/funcgen/funcgen/`; line numbers refer to decoded source.
The failures described are conclusions from source inspection, not claims
that the archived application was run in this session.

| Evidence | Problem | Consequence for the new engine |
| --- | --- | --- |
| `data_flow.py:26-33, 132-139` | Removes builtin names and familiar aliases such as `pd` from inputs/outputs | A rebound `len` or `pd` remains a real dependency; never use a name blacklist as scope resolution |
| `data_flow.py:40-78` | Flat AST walks mix nested scopes, conditional writes and reads; augmented targets are stores in the AST | Track read-before-write and possible bindings separately; refuse unresolved paths |
| `data_flow.py:81-85` | Converts parse failure into an empty parsed block | Invalid input must retain an error and source location |
| `data_flow.py:121-125` | Repeatedly unions all later blocks | Potential quadratic work in number of blocks; measure before optimizing or claiming speed |
| `type_inferrer.py:22-112, 137-150` | Uses final call/method spelling and capitalization as type evidence | A method named `read_csv` need not be pandas; keep unresolved targets/types explicit |
| `type_inferrer.py:152-163` | Same-type binary operands preserve their type; subscription inherits container type | `1 / 2` is not an integer result; a list element is not necessarily a list |
| `extractor.py:97-113`, `codegen.py:125-157` | Emits a sequence of generated functions and a main caller | Sequential calls alone do not preserve module initialization, scope, partial failures or API visibility |
| `fixer/func_splitter.py:94-107` | Strips every nonblank line when forming segments | Nested indentation is lost; blank lines are not safe extraction boundaries |
| `fixer/func_splitter.py:250-286` | Rebuilds helpers/caller around segments without a general control-flow model | Returns, decorators, multiline signatures and exception paths need dedicated treatment |
| `fixer/const_extract.py:205-268` | Hoists large mutable list literals out of functions | Fresh-per-call objects can become shared state; uppercase spelling does not make an object immutable |
| `fixer/const_extract.py:273-281` | Replaces text on the starting line | Multiline literals and exact occurrence ownership need concrete syntax spans |
| `splitter.py:250-288` | Places constants in the utility module but imports only utility function names into main | Main functions that use those constants can lose access; imports and initialization need analysis |
| `splitter.py:323-325` | Directly writes generated filenames | Future output must handle collisions and transactional failure without overwriting unrelated work |
| `fixer/core.py:125-131` | Removes function-body comments | This conflicts with preserving source evidence and useful explanations |
| `fixer/core.py:149-179` | Runs textual fixers/plugins and returns output without final contextual compilation here | Each proposed artifact needs independent validation; a successful fixer return is insufficient |

Useful counterexamples for future work include a shadowed builtin,
`total += increment`, a conditional definition, `with ... as handle`, a
mutable list created inside a repeatedly called function, a decorator with
side effects, a function with a multiline signature, and two input modules
with the same basename. Current engine tests already cover several refusal
classes; M2b.1 adds evidence for calls, aliases, scopes and partial writes.
The remaining cases stay in the roadmap instead of being advertised as fixed.

## Blacker prototype

The RAR contains successive formatter versions, seven focused cases,
AST/parity checkers, a timing harness and two Requests trees. The 1,614
`env` entries are an archived environment, not portable package contents.
The seven cases are useful starting points for operator chains, signatures,
trailing commas, dictionary comments, method chains, f-strings and semicolons.

The most consequential finding is in `blacker_v3.3_working.py:890-905`:
AST comparison is optional, and its `except SyntaxError: pass` allows the
formatted result to proceed. The write path at lines 981-993 can then write
that result. An invalid output must be refused even if AST comparison was
requested. The label "working" does not establish correctness.

`format_source` at lines 863-885 transforms physical lines and normalizes
line endings. That requires careful handling of multiline strings,
continuations, comments and encodings. A token-aware helper does not make
the complete line-based pipeline syntax-preserving.

The cache at lines 942-954 and 1000-1002 keys files by modification time and
size. Formatter version and formatting options are absent from that
signature, so an unchanged file can be skipped after options change.

`src_check/ast_safety_check.py` counts unparseable originals separately,
compares only those with recorded ASTs, prints findings, and does not make
its final result a failing process exit. `bench_formatter.py` continues
recording elapsed time for nonzero formatter exits. Its normal runs also
operate on the given tree unless the filtered-copy path is selected.
Those measurements cannot substantiate a successful-work speed advantage.

A future benchmark must use disposable equivalent inputs, fail on parse or
formatter errors, report the full denominator, and separate cold work,
warm work and cache hits. Compare formatting with formatting and extraction
with extraction. Preserve raw timing results and corpus/version details.

## Rules and architecture examples

The seven example scripts contain 70 function definitions in total.
Simple physical-span measurements found 20 functions above 50 lines;
this count includes test helpers and makes no orchestrator exception.
All seven files have lines longer than 79 characters. The examples express
intent but are not a perfectly conforming reference implementation.

One concrete documentation conflict is
`improvement_rules/2_utils.py:152`: `extract_dtc_valid_rows` declares a
DataFrame result, while its Returns section describes a dictionary.
A docstring generator must reconcile implementation evidence instead of
copying a plausible template. The data-processing examples also illustrate
mutation, external I/O and domain units that cannot be inferred from names
alone. Their specific function and variable names must not become rules.

Both `.drawio.png` images contain a `tEXt` chunk keyed `mxfile` with
URL-encoded, parseable native Draw.io XML:

| Reference | Diagram pages | Vertex cells | Edge cells |
| --- | ---: | ---: | ---: |
| `1_architecture.drawio.png` | 1 | 64 | 48 |
| `2_architecture.drawio.png` | 1 | 45 | 34 |

Vertex counts include labels/containers, not just executable operations.
The XML shows named functions, I/O labels, loop/decision structure and
module areas. It is stronger format evidence than the filename alone,
but does not prove the diagrams are current with every source file.

The PDF's readable text specifies:

- Top-to-bottom, left-to-right flow, a script title and start/end markers.
- Distinct process, decision, data, document, database and loop shapes.
- Function name, brief operation summary and input/output names per process.
- Database placement on the left; labeled decision branches.
- Module colors with a legend, consistent spacing and page connectors.
- At most ten step blocks per diagram part as a presentation preference.
- Diagram maintenance alongside source changes and editable PNG delivery.

Carry these into an optional FlowBlueprint rendering profile. Syntax analysis
must determine actual loops and branches; it must not draw an unconditional
path merely to avoid an open connector. Unknown dynamic relationships need
visible labels. Management views should summarize modules/data boundaries;
developer views should expose control flow and known contracts. Native
`.drawio` is the first output; embedded-PNG export follows.

## Decisions applied now

Keep the current analyzer and its explicit refusal contract. Add located
partial effect evidence without broadening extraction eligibility. Preserve
unknown types, source bytes and validation limits. Retain useful examples
as design evidence, but use synthetic fixtures in the public package rather
than copying the archive's business data or environment. The launch plan is
in [PRODUCT_PLAN.md](PRODUCT_PLAN.md), and the implemented increment is in
[M2B_EFFECTS.md](M2B_EFFECTS.md).
