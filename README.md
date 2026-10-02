# FuncLoom

**The Python functionizer.** Turn Python snippets, scripts and Jupyter
notebooks into reviewable functions and modular packages; every
transformation is verified or refused with a reason and source location.

Part of a family of standalone Python tools: [FuncLoom](https://github.com/SAMtheROCKET/funcloom) (functionizer), [RefacTrail](https://github.com/SAMtheROCKET/refactrail) (refactorizer) and RepoContour (architect, planned). Each installs and works on its own.

**0.10.3a0 is an unpublished experimental alpha.** It has no runtime
dependencies and does not need an LLM, account or network connection.
Python 3.12 or newer is required. CI tests CPython 3.12-3.14 on Windows,
Linux and macOS, and verifies the built packages on all three.

## Capabilities

| Command | Input | Output |
| --- | --- | --- |
| `snippet` | Python text or one notebook cell | Function/caller drafts with optional context, naming proposals, type evidence and questions |
| `plan` | An explicit module-level line selection | Extraction contract, draft function/caller, source hashes, effects and refusal reasons |
| `modularize` | Script, stdin, notebook or project folder | New modules, step functions, a `Pipeline` class and entry scripts |
| `refine` | Python file or project folder | New copies with supported long functions/blocks split, lines wrapped and optional docstring skeletons |
| `scan` / `check` | Python file or project folder | Inventory and configured line, size, annotation, documentation and naming findings |
| `doctor` | Installed environment | Runtime version, interpreter, package location and capabilities |

The tools parse and compile source without importing or executing target
projects. Generated files require review and the target project's tests.
Structural checks and regression results do **not** prove that arbitrary
programs retain their behavior. Unknown types and meanings remain explicit;
domain context is supplied by the user, not guessed from names.

## Install locally

From the source folder in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m funcloom doctor
```

On Linux/macOS use `python3 -m venv .venv` and `.venv/bin/python` instead.
After local release preparation, a fresh environment can install the wheel
offline:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --no-deps dist\0.10.2a0\funcloom-0.10.2a0-py3-none-any.whl
```

Nothing has been uploaded to PyPI or TestPyPI. Repository links in package
metadata target the intended `SAMtheROCKET/funcloom` repository. Public
repository creation and publication remain deferred by the owner.

## Try the workflows

Use your environment's Python in place of `python` below.

```powershell
python -m funcloom snippet examples/snippet_tax.py --no-context
python -m funcloom snippet examples/snippet_tax.py --context profiles/snippet_tax.toml
python -m funcloom snippet examples/snippet_generic.py --interactive
python -m funcloom snippet examples/snippet_generic.py --naming mathematical
python -m funcloom snippet examples/snippet_tax.ipynb --cell 2 --no-context
python -m funcloom modularize examples/modular_sales_report.py --output demo_sales
python demo_sales/main.py
python -m funcloom refine examples/long_functions.py --output demo_refined.py --document
python demo_refined.py
python -m funcloom check examples/clean_module.py --fail-on warning
```

`snippet --interactive` offers no context or a small project description,
then optional naming/type/meaning information. It does not translate
pseudocode or natural-language instructions into executable Python.
Noninteractive commands work without domain context.

For whole repositories:

```powershell
python -m funcloom modularize path/to/project --output path/to/project_modular
python -m funcloom refine path/to/project --output path/to/project_refined
```

Outputs must be new; modularization also accepts an empty destination
folder. Folder outputs must be outside the input tree. Input files are
preserved. Run a generated package from its output folder. `modularize`
without `--output` only plans; `--show-files` includes the generated text.
`--format json` exposes the corresponding report contract.

## Generated package and limits

A typical package has `config.py`, `functions.py`/`models.py`, `steps.py`,
`pipeline.py` and `main.py`. Its initial imports are retained once, in source
order, in `_imports.py`; later imports stay where they occurred. Folder
mode retains library paths and data and adds entry-script shims.

- `plan` and `snippet` produce review drafts with no apply operation.
- `modularize` and `refine` write new copies. Known unsupported cases are
  refused or left unchanged with a reason; not every behavior difference
  can be detected statically.
- Wildcard imports are refused for modularization; use explicit imports.
  Dynamic namespaces, serialization, module identity, reflection and file
  paths need particular review.
- Notebook cells run in document order without kernel state. Magics and
  shell escapes may be omitted, with notes; outputs do not establish types
  or hidden dependencies.
- Unsupported functions/blocks stay whole, even over the size target. Type
  hints are narrow static proposals and documentation is a skeleton.
- Line length defaults to 79, configurable from 40 to 200. Existing tool
  directives are retained or refused. Wrapping that would create a new
  directive is refused too.
- No performance comparison with Ruff or Black has been established.
  Natural-language code generation and architecture diagrams remain future
  work. A local VSIX now supplies explicit check, snippet, modularize and
  refine commands; see [editor setup](editor/funcloom/README.md).

See [snippet context](docs/SNIPPET_WORKFLOW.md),
[generic variable names](docs/GENERIC_VARIABLES.md),
[extraction planning](docs/EXTRACTION_PLANNING.md),
[modularization](docs/MODULARIZE.md), [refinement](docs/REFINE.md),
[rule coverage](docs/RULES.md), and
[local/editor setup](docs/LOCAL_SETUP.md).

## Development and release checks

```powershell
.\.venv\Scripts\python.exe scripts/verify.py
.\.venv\Scripts\python.exe -m pip install -e ".[release]"
.\.venv\Scripts\python.exe scripts/release_check.py --output dist/0.10.2a0-final
```

The release check requires a new output directory. It builds a wheel and
source archive, checks metadata and contents, installs into fresh
environments, runs full verification against installed packages, and checks
uninstallation. It writes logs, checksums and `verification.json`, with no
upload step. See [release preparation](docs/RELEASE_PREPARATION.md).

Python APIs and report schemas may change during the alpha. FuncLoom,
RefacTrail and RepoContour remain separately releasable projects.

## License

[MIT](LICENSE), copyright 2026 Sambit Supriya Dash.
