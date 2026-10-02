# FuncLoom for VS Code

Experimental local extension 0.10.2; requires Python package
`funcloom==0.10.2a0` in your selected interpreter. It installs no
Python package automatically and sends no source to a service.

Install the local VSIX with VS Code's **Extensions: Install from VSIX**.
Set `funcloom.pythonPath` to your environment's Python executable, for
example `.venv/Scripts/python.exe`. Open a trusted local workspace and
use the `FuncLoom:` commands in the Command Palette. Checks appear in
Problems; drafts and diffs open for review. Save files before checking or
writing transformations. Function drafts can use selected Python text,
an active notebook code cell, and optional context TOML.

Generated output still requires project-specific tests. FuncLoom's refine/modularize commands require a new destination.
No automatic save-time edits, arbitrary shell commands or target imports
are used. Command output is limited to 8 MB and execution to 60 seconds.

Publisher ID `samtherocket` is the intended Marketplace identity and is
not claimed or registered by this build. Publication is the owner's step.
