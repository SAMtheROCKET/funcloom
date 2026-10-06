# FuncLoom

[![CI](https://github.com/SAMtheROCKET/funcloom/actions/workflows/ci.yml/badge.svg)](https://github.com/SAMtheROCKET/funcloom/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/funcloom?include_prereleases)](https://pypi.org/project/funcloom/)
[![Python](https://img.shields.io/pypi/pyversions/funcloom)](https://pypi.org/project/funcloom/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Website](https://img.shields.io/badge/website-funcloom-informational)](https://samtherocket.github.io/funcloom/)
[![VS Code](https://img.shields.io/visual-studio-marketplace/v/samtherocket.funcloom?label=VS%20Code)](https://marketplace.visualstudio.com/items?itemName=samtherocket.funcloom)

**The Python functionizer.** Turn Python snippets, scripts and Jupyter
notebooks into reviewable functions and modular packages; every
transformation is verified or refused with a reason and source location.

Website: [samtherocket.github.io/funcloom](https://samtherocket.github.io/funcloom/)

Part of a family of standalone Python tools: [FuncLoom](https://github.com/SAMtheROCKET/funcloom) (functionizer), [RefacTrail](https://github.com/SAMtheROCKET/refactrail) (refactorizer) and [FlowBlueprint](https://github.com/SAMtheROCKET/flowblueprint) (architect: script or notebook to architecture diagram). Each installs and works on its own.

**Use FuncLoom to:**

- generate functions automatically from long scripts, pasted snippets and
  notebook cells (an *auto function generator* that shows its evidence);
- turn a Jupyter notebook into a clean Python package with a pipeline
  class and `main.py` (*notebook to module*, *notebook to script*);
- auto-structure and modularize messy prototype, data-science or
  coursework code so it can be reused, tested and presented;
- split functions that are too long and add certain type hints and
  docstrings, with every change verified or refused with a reason.

Built for developers, data scientists, data analysts and students; pair it
with RefacTrail to check and refactor the result and FlowBlueprint to draw
its architecture for managers and product owners.

**Status: alpha.** The latest release on PyPI is 0.10.4a0 (experimental
alpha; see [what's new](#whats-new-in-0104a0)). It has no runtime
dependencies and does not need an LLM, account or network connection.
Python 3.12 or newer is required. CI tests CPython 3.12-3.14 on Windows,
Linux and macOS, and verifies the built packages on all three.

## Quick start

```bash
pip install funcloom
```

That is all: FuncLoom has no dependencies. Python 3.12 or newer is
required.

Then, in any project:

```bash
funcloom                                     # the most useful commands
funcloom check script.py                     # long functions, structure
funcloom snippet code.py                     # draft a reusable function
funcloom modularize notebook.ipynb --output my_package
funcloom refine script.py --output script_refined.py
```

![FuncLoom turns sales_report.py into a package with modularize; the package's main.py prints the same result as the script](https://raw.githubusercontent.com/SAMtheROCKET/funcloom/main/docs/media/funcloom-modularize.gif)

Your original files are never changed: results go to a new file or an
empty folder, and anything that cannot be proven safe is refused with a
reason and line number. If your system blocks the `funcloom` command, use
`python -m funcloom` instead.

**In VS Code**, install the [FuncLoom extension](https://marketplace.visualstudio.com/items?itemName=samtherocket.funcloom) from the
Marketplace (search *FuncLoom* in the Extensions view) and run
*FuncLoom: ...* from the Command Palette. It uses the Python interpreter selected in VS Code and
offers to install FuncLoom there with one click.

**On every commit**, add the hook to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/SAMtheROCKET/funcloom
    rev: v0.10.4a0
    hooks:
      - id: funcloom-check
```

## What's new in 0.10.4a0

- **Faster `refine` on very large files:** a repeated scan was removed;
  the output is identical on all 7,572 files checked.
- **Clearer refusals:** a program nested too deeply for Python is refused
  with READ001, and `from x import *` inside a `try`/`if` block with
  MOD004 at its line, instead of a crash or a generic MOD007.
- **Robustness:** `refine` ran on a 6,988-file corpus of real packages
  without a crash; `modularize` planned 5,669 of those files and refused
  the rest with located reasons.
- **Stable interfaces:** [docs/INTERFACES.md](docs/INTERFACES.md) lists
  the commands, exit codes, codes and API kept stable through the beta.

## Office machines and older Python

FuncLoom needs Python 3.12 or newer, but your project does not: the tool
only reads your code, so it can run on its own Python next to a project
that stays on 3.9, 3.10 or 3.11. Neither of these needs administrator
rights; [uv](https://docs.astral.sh/uv/) downloads its own Python 3.12
into your user folder:

```bash
uvx --python 3.12 funcloom check script.py                  # one-off run
uv tool install --python 3.12 funcloom                      # or install once
funcloom modularize notebook.ipynb --output my_package
```

`pipx install --python <path to a Python 3.12> funcloom` works the same
way. If `pip` says `from versions: none`, your Python is older than 3.12
or pip is pointed at a company mirror that does not carry the package
(check with `python -m pip config list`, and ask IT to allow it).

Step by step, with the VS Code settings and the limits: [using the tools on older-Python projects](https://github.com/SAMtheROCKET/funcloom/blob/main/docs/OLDER_PYTHON.md).

### From source (development)

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .      # Windows: .venv\Scripts\python.exe
.venv/bin/python -m funcloom doctor
```

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

![FuncLoom refine splits long functions into helpers; the refined copy prints exactly the same output](https://raw.githubusercontent.com/SAMtheROCKET/funcloom/main/docs/media/funcloom-refine.gif)

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
  work. The VS Code extension supplies explicit check, snippet, modularize and
  refine commands; see [editor setup](editor/funcloom/README.md).

See [snippet context](docs/SNIPPET_WORKFLOW.md),
[generic variable names](docs/GENERIC_VARIABLES.md),
[extraction planning](docs/EXTRACTION_PLANNING.md),
[modularization](docs/MODULARIZE.md), [refinement](docs/REFINE.md),
[rule coverage](docs/RULES.md),
[local/editor setup](docs/LOCAL_SETUP.md), and the
[stable interfaces](docs/INTERFACES.md) kept through the beta.

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
RefacTrail and FlowBlueprint remain separately releasable projects.

## License

[MIT](LICENSE), copyright 2026 Sambit Supriya Dash.
