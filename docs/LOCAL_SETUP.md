# Local setup

Use CPython 3.12 or newer. This alpha has been tested with CPython 3.12 on
Windows and Linux. Open the folder containing `pyproject.toml` in VS Code;
its physical folder name does not determine the installed package name.

## Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m funcloom doctor
.\.venv\Scripts\python.exe scripts/verify.py
```

Use `&` before a quoted interpreter path containing spaces. Activation is
optional when using the interpreter path explicitly.

## Linux and macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m funcloom doctor
.venv/bin/python scripts/verify.py
```

The commands are provided for both platforms; macOS execution is not part
of the current verification record. Python's venv/pip components must be
available, or use your environment manager to create an equivalent venv.

## VS Code

Select **Python: Select Interpreter** and choose this folder's `.venv`.
The included `.vscode/tasks.json` provides **Tasks: Run Task** entries for
verification, scanning, planning and contextual/interactive snippet drafts.
They use the same Python package as the terminal. They are not a dedicated
FuncLoom extension; no extension Marketplace artifact is included.

## Verify the active installation

`doctor` should report version `0.10.1a0`. An editable installation should
resolve to this folder's `src/funcloom`; a wheel installation should resolve
to the selected environment's `site-packages/funcloom`. It reports no
runtime dependencies, no target execution and no LLM requirement.
`source_rewriting=false` describes the original input: `modularize` and
`refine` can write new output copies while retaining the input files.

If the wrong version appears, run pip and FuncLoom through the same Python:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m funcloom doctor
```

The Windows symlink test may skip when symlink creation is unavailable.
Other test failures require investigation. A passing suite does not prove
that arbitrary customer programs preserve behavior after transformation.

See the [README](../README.md) for workflows and
[release preparation](RELEASE_PREPARATION.md) for offline artifact checks.
