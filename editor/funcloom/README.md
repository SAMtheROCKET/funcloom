# FuncLoom for VS Code

FuncLoom, the Python functionizer: turn scripts, snippets and notebooks into
verified functions and packages, without leaving the editor.

## Getting started

1. Install this extension, open a project and trust the workspace.
2. Run any **FuncLoom:** command from the Command Palette (Ctrl+Shift+P).
3. The first time, if FuncLoom is not in your Python environment yet, click
   **Install**. The extension runs `pip install funcloom==0.10.5a0` in that
   interpreter, and only after your click.

The interpreter is the one selected in VS Code's Python extension (or
`python` on your PATH). To use another, click **Choose interpreter** or set
`funcloom.pythonPath`.

## Commands

- **Check active file**: findings appear in the Problems panel.
- **Draft function from selection or cell**: drafts a reusable function from
  the selected code or the active notebook cell, optionally with a context
  TOML file.
- **Modularize to new folder**: turns a script or notebook into a package.
- **Refine to new file**: splits long functions and wraps long lines in a copy.
- **Extract selected lines to a function (new file)**: select lines, type a
  function name and pick a new file; FuncLoom writes a copy where those
  lines are a function and its call, or tells you why it refused.

Your original files are never changed; results go to a new file or folder,
and anything that cannot be proven safe is refused with a reason. Save
files before running a command. Nothing is sent to any service, the
checked code is never run, and each command is limited to 60 seconds and
8 MB of output.
