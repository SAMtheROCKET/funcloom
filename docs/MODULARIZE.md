# Definition effects in 0.10.2a0

Decorated definitions and classes with bases/keywords stay at their original
execution position. Decorator names such as `property` or `cache` do not
prove purity because those bindings can be replaced. Class assignments that
may bind descriptors remain in place. Attribute access, subscription, union
operators and other effectful expressions in definitions are not treated as
pure. Effectful module annotations cause a located MOD010 refusal.
These conservative restrictions supersede earlier purity-whitelist claims.

# Modularize: from a script or notebook to a package

Current version: **0.10.1a0**. Version 0.7.0a0 added `modularize`;
0.8.0a0 added folder mode and wrapping inside blocks. It turns a program into a
package of modules, step functions, a `Pipeline` class and a `main.py`
entry script with `if __name__ == "__main__":`. The original file is never
changed and no program code is run while planning.

This is the first increment that **writes files**. The user decided on
30 September 2026 to proceed before M2b was complete; see Limits.

## Inputs

| Input | How |
| --- | --- |
| A `.py` script or a file of functions/classes | `funcloom modularize script.py` |
| A whole notebook | `funcloom modularize analysis.ipynb` |
| Selected notebook cells | `funcloom modularize analysis.ipynb --cells 2,4-6` (one-based, Markdown cells count) |
| Pasted code | `Get-Content -Raw snippet.py \| funcloom modularize -` |
| Python API | `modularize_report(path_or_None, source_text, output_dir, cells_list, package_name, profile_info)` |

Without `--output` the command only plans and prints the files and steps.
Add `--show-files` to print every generated file, `--output FOLDER` to write
(the folder must be new or empty), `--package-name` to choose the package
name, `--line-length` for the width and `--format json` for a JSON report.

Notebook cells are combined in document order. Line magics and shell escapes
(`%matplotlib inline`, `!pip install`) become comments; `%%time` and
`%%capture` keep their code; other cell magics (`%%bash`, `%%writefile`, â€¦)
skip the cell. Every removal is listed in the report notes.

## Folder mode (0.8.0a0)

Pass a folder to convert a whole project:

```powershell
funcloom modularize my_project --output my_project_modular
```

The output is a copy of the project in which every **entry script** is
replaced by a package and a small script with the same name:

```
my_project_modular/
  main.py              runs any converted script: python main.py train [args]
  train.py             shim: retains the python train.py [args] entry command
  train_app/           config, functions, models, steps, pipeline
  tools/cleanup.py     shim next to its package, so sibling imports work
  tools/cleanup_app/
  utils.py, lib/...    library modules, copied byte-for-byte
  data/values.csv      data files, copied (use --skip-data to leave them out)
  tests/, setup.py     copied unchanged
```

An entry script runs code when started (a `__main__` block, top-level calls,
loops or `with` blocks), is not imported by another project file, is not a
test, tooling (`setup.py`, `conftest.py`, `manage.py` â€¦) or package file,
and uses no relative imports. Choose entries yourself with
`--entries train.py,tools/cleanup.py`. Imports are resolved against both the
project root and each file's own folder, the way Python runs a script.

An entry that cannot be converted safely, for example because it uses
`exec` or `__spec__`, is **copied unchanged** and listed with its reason; it
does not stop the rest of the project. Library modules keep their paths, so
their imports and `__file__`-relative data keep working. Since 0.10.0a0
entries that read `__file__` are converted: each generated module that
reads it first sets `__file__` to the path of the shim (in a single-file
conversion, `main.py`) next to the package, so paths built from it point
at the same folder as before, and warning MODW06 says so. More than 200 MB of other
files is refused (MOD009) unless `--skip-data` is given. The output folder
must be outside the input folder (MOD006).

The root `main.py` (or `run_pipelines.py` if the project already has a
`main.py`) runs the chosen shim as if it were started directly: its folder
first on `sys.path` and the remaining arguments in `sys.argv`.

## Long lines inside blocks (0.8.0a0)

Long assignments, expression statements and `return` statements are now
wrapped at any depth, inside loops, `if`, `with` and function bodies, both
in steps and in moved definitions. Lines that share a statement with a
semicolon, use tab indentation, contain multi-line strings or carry tool
directives stay as written and are listed in the notes.

## Refinement (0.9.0a0)

Generated modules, and in folder mode every copied Python file, are refined:
functions over 40 lines are split into verified helpers, long lines are
wrapped, and missing docstrings are added (`--no-document` leaves them
out). Use
`--keep-long-functions` to turn splitting off, and `--trust-with-blocks`
to let values bound in `with` blocks cross step boundaries (see
[REFINE.md](REFINE.md)). Compilation and line
wrapping still run with splitting disabled; unchanged copies stay byte-for-byte. See [REFINE.md](REFINE.md).

Since 0.10.0a0, generators and coroutines are split too, long loop, `if`
and `with` bodies are split in place, and step functions and helpers get
type hints where the type is certain (an annotated or literal value never
rebound to something else). Generated and refined files keep the source's
line endings (LF, CRLF or CR).

A step that changes an earlier value only on some paths now receives that
value as a parameter and returns it, so the unchanged value is passed on;
0.9.0a0 and earlier raised `UnboundLocalError` for such scripts.

## Output

```
OUTPUT/
  main.py                 def main(): Pipeline().run(); if __name__ == "__main__": main()
  <package>/
    __init__.py           docstring and leading import initialization
    _imports.py           leading imports in their original order
    __main__.py           python -m <package>
    config.py             leading literal constants, renamed UPPER_CASE when safe
    functions.py          functions that do not depend on script state
    models.py             classes that do not depend on script state
    steps.py              one function per notebook cell or commented section
    pipeline.py           class Pipeline: run() calls every step in order
```

If functions and classes use each other, both go into `components.py` to
avoid a circular import. Run the result from the output folder with
`python main.py` or `python -m <package>`.

## How the program is split

- **Imports** in the initial contiguous import block run once in
  `_imports.py`, initialized by the package. Unused and repeated imports
  are retained. Other generated modules read bindings from that module.
  Imports after another kind of statement always stay at their original
  execution point. Wildcard imports receive MOD004; exports are not guessed.
- **Constants** are leading `NAME = literal` statements (numbers, strings,
  booleans, `None`, tuples of these) bound once. They are renamed
  UPPER_CASE only when the name is bound nowhere else, even as a
  parameter; otherwise they keep their name.
- **Definitions** move to `functions.py`/`models.py` only when they read
  nothing but imports, constants, other moved definitions and builtins, are
  bound once, use no `global`, `globals()`, `exec` or similar, and defining
  them cannot have effects: decorators must be known-pure (`property`,
  `staticmethod`, `classmethod`, `dataclass`, `lru_cache` ...), and
  defaults, annotations, base classes and class-body statements may only
  use literals, names, attribute and item access and type unions. A class
  body that prints, a default that calls a function or a decorator that
  registers keeps the definition in its original place and order. Anything
  else stays inside a step for review; the report names each one and why.
- **Annotated assignments** at module level whose annotation could have
  effects are refused (MOD010): inside a step function the annotation of
  a local variable is never evaluated.
- **Steps**: each notebook cell, or each script section that starts with a
  comment or after two blank lines, becomes a step; long sections are split
  at about 28 lines. The comment or Markdown heading becomes the function
  name and docstring (`# Load the records` â†’ `load_records`). The body of
  `if __name__ == "__main__":` becomes the `run_main_block` step.
  A script with no such headings at all is split at its blank-line
  paragraphs instead; a paragraph of fewer than four lines joins the next
  one. Steps without a heading are named after what they produce
  (`compute_totals`) or, when they produce nothing later code reads,
  after their first known operations (`save_csv_and_plot`,
  `print_results`).
- Each step's parameters are the values earlier steps produced that it
  reads; it returns only values that later steps read. The `Pipeline`
  stores them as attributes, so results can be inspected after `run()`.
  Long pipelines get `run_stage_N` methods to keep functions short.

### When steps are merged

Splitting must not change behavior. Adjacent steps are merged, with the
reason recorded, when:

1. a value passed into a step might not be bound there (for example it is
   set only inside an `if`);
2. a value returned by a step might not be bound at its end;
3. a function, lambda or generator defined in a step reads a variable that
   a later step rebinds, because the original code would see the new value.

In the worst case the whole program becomes one long step. This preserves
those statements together, but does not prove runtime equivalence.

## Refusals

| Code | Reason |
| --- | --- |
| MOD001 | Not valid Python (including notebook-only syntax) |
| MOD002 | `globals()`, `locals()`, `vars()`, `exec` or `eval` in code that moves into a function |
| MOD003 | A `global`/`nonlocal` statement in that code |
| MOD004 | Wildcard imports have unresolved exports; use explicit imports |
| MOD005 | `__spec__`, `__loader__` or `__cached__` anywhere, or `__name__` in executable code: the values would describe the generated module |
| MOD006 | The output folder already has contents, or cannot be written |
| MOD007 | Internal check failed: a generated file did not compile, match the original statements or resolve its names |
| MOD010 | A module-level annotation could have effects (for example a call); local annotations are never evaluated inside a step |

`MODW08` (a warning) marks a notebook that uses Jupyter's built-in
`display()`: generated modules that need it import it from
`IPython.display` and fall back to `print` when IPython is not installed,
so the package runs outside Jupyter.

`MODW07` (a warning, folder mode) marks a copied Python file that does not
compile, such as a deliberately broken test fixture or a Python 2 script:
it is copied byte-for-byte and the rest of the project is converted.
Folders containing `pyvenv.cfg` (virtual environments of any name) are
skipped. On Windows without long paths enabled, an output whose longest
file path would exceed 259 characters is refused before anything is
written (MOD006), naming that path.

`MODW05` (a warning) marks `__name__` inside a moved definition, such as
`logging.getLogger(__name__)`; the logger name will change. `MODW06` (a
warning) marks code reading `__file__`: it now names the script next to the
generated package, so files read relative to it must sit beside that
script (folder mode copies them there).

## Checks before writing

Every generated file is compiled. Leading imports must match in order.
Every step body, moved definition and
constant must have the same syntax tree as the original statement (after
constant renames). Every name a generated module reads must be defined or
imported there, unless it was already undefined in the original. Files are
written to a hidden staging folder and renamed into place in one step.

Statements whose indentation must change and that contain multi-line
strings, or whose continuation lines are indented irregularly, are
regenerated from their syntax tree; comments inside them are lost and the
report says so. Long simple statements in steps are wrapped; long compound
statements are kept and listed in the notes.

## Evidence

Thirteen tests in `tests/test_modularize.py` run test-authored programs both
as the original script and as the generated package and compare the output:
scripts with constants, functions, classes, sections and a main block;
`python -m`; conditional bindings and late-bound lambdas that force merges;
functions that depend on script state; refusals leaving no files; library
files; multi-line strings; a non-empty output folder; 40 sections with
stages and clashing names; import-order sensitivity; a notebook with
headings, magics and selected cells; stdin; and `+=`/`del` across steps.
`scripts/verify.py` builds `examples/modular_sales_report.py` and compares
its output. An 18-program differential probe (try/except, while loops,
files, generators, closures with `nonlocal`, decorators, star imports,
f-strings, shadowed constantsâ€¦) produced identical output for all 16
accepted programs after two fixes it found; the other two are refused.

## Limits

- Long functions and long loop/if/with bodies are split; async
  generators, blocks using `break`/`continue` and functions using frame or
  class tricks stay whole (REFINE.md).
- Statements are kept as written; the generated code is not yet
  refactored to the naming, type and docstring rules. Moved definitions
  keep their original docstrings and missing annotations; step parameters
  are annotated only when their type is certain.
- Relative file paths resolve against the working directory; `sys.path[0]`
  becomes the output folder, so sibling modules of the original script
  must be copied next to `main.py`.
- Nested definitions left in steps cannot be pickled by reference.
- `print` order, exceptions and results matched in every test and probe,
  but runtime behavior is not proven equal for arbitrary programs.
