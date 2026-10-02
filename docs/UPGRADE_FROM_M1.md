# Keep M1 and install M2a alongside it

Your M1 run passed on Windows/Python 3.12.13: 29 passes, one symlink privilege
skip, and every verification step completed. No administrator launch or
system-wide setting change is needed for ordinary development.

1. Extract `funcloom-m2a-v0.2.0a0.zip` into your existing `Big-Project`
   folder. The ZIP contains a top-level **funcloom-m2a** folder. Confirm:
   `<your Big-Project folder>\funcloom-m2a\pyproject.toml`.
   Keep your existing `funcloom` M1 folder as it is.
2. From the same PowerShell prompt in the existing M1 `funcloom` folder,
   create the new environment using your already working Python:

```powershell
.\.venv\Scripts\python.exe -m venv ..\funcloom-m2a\.venv
Set-Location ..\funcloom-m2a
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m funcloom doctor
.\.venv\Scripts\python.exe scripts\verify.py
```

Run each command after the preceding command succeeds. Doctor should show
version **0.2.0a0**, milestone **M2a**, and a package path under
`funcloom-m2a\src\funcloom`. Verification should finish with:

```text
PASS: all local verification steps completed.
```

The suite contains 67 tests. Your current Windows privileges may again skip
the symlink test; that would mean 66 passes and one skip if all other tests
pass. The untidy example's warnings, the core's four preferred-size warnings,
and the augmented-assignment plan's refusal are expected. Skipped source
directories shown by scan/check are separate from skipped tests.

3. Open the **funcloom-m2a** folder in VS Code. Select its own
   `.venv\Scripts\python.exe` interpreter. The included tasks now offer
   **FuncLoom: Plan invoice example** as well as the existing commands.
4. Run the supported planning example from
   [EXTRACTION_PLANNING.md](EXTRACTION_PLANNING.md). Inspect its two inputs,
   two outputs, function draft, and caller draft.
5. Keep changes in the new project folder as you continue development.
   Each environment has its own editable installation, so using the old
   folder's interpreter will still run M1. Doctor makes this visible.

This package contains the cloud-prepared changes; it does not synchronize or
modify your Windows folder automatically. If you already edited M1 locally,
review and carry those edits forward separately rather than replacing them.
The next implementation stage is M2b, described in the updated roadmap.
