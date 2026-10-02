# Build verification record

Verified 28 September 2026 UTC. This record describes observed results, not
cross-platform certification or semantic-refactoring guarantees.

## Environment and installation

- Runtime: CPython **3.12.14**, Linux.
- Build tools available in the build environment: `build 1.6.1`,
  `setuptools 84.0.0`, `wheel 0.48.0`.
- Editable install: a project virtual environment with access to the
  preinstalled build tools, using
  `python -m pip install --no-build-isolation --no-deps -e .`.
  Installation succeeded and `doctor` located the package under
  `src/funcloom` using that environment's interpreter.
- Distribution build: `python -m build --no-isolation` succeeded, producing
  `funcloom-0.1.0a0.tar.gz` and `funcloom-0.1.0a0-py3-none-any.whl`.
  The wheel was built from the source distribution.
- Clean wheel install: a separate virtual environment without system site
  packages installed that wheel using `--no-index --no-deps`. `doctor`
  located the installed code in that environment's `site-packages`.
- The console entry point, module invocation, `py.typed`, Python-version
  metadata, and source distribution's development-file inclusion were checked.

The normal README installation command allows pip to obtain its build
dependency. This build reused available tools instead of testing a fresh
download from a package server. Build outputs were used for validation; the
delivered ZIP is the editable source project and excludes environments,
generated metadata, caches, and `dist/`.

## Observed checks

| Check | Result |
| --- | --- |
| Regression suite from editable installation | **30 passed**, no skips |
| Same suite against clean installed wheel with Python isolated mode, outside source root | **30 passed**, no skips |
| `scripts/verify.py` using project environment | All steps passed |
| Clean example with `--fail-on warning` | Exit 0, zero findings |
| Deliberately untidy example with `--fail-on warning` | Expected exit 1, four warnings |
| Example directory inventory | Two modules, valid JSON, completed analysis, no behavior-proof claim |
| Core-source objective check | Zero errors; four preferred-size warnings |
| Core and verification script width/hard function caps | No violations |
| VS Code settings/tasks/launch/recommendations | Valid JSON; settings matched official documentation |
| Wheel entry point and clean example invocation | Passed |

The four core warnings are for functions longer than the preferred 40-line
target but no longer than the 50-line hard cap. They are intentionally
reported rather than hidden or waived. Functions have declared annotations
and configured docstring sections; this does not prove that all semantic
naming, documentation, or typing requirements are satisfied.

The regressions exercise non-execution of targets/imports, byte preservation,
relative-path collisions, environment exclusions, symlink handling,
parse/compile failures, encoding cookies, invalid encodings, per-file limits,
nested/async scopes, argument kinds, decorator spans, size thresholds,
orchestrator ownership, main-guard recognition, line width, docstring
presence, report determinism and coverage flags, invalid targets/config,
exit thresholds, and refusal to overwrite report/source paths.

## Remaining validation

Native Windows and macOS execution, the VS Code GUI/debugger/test-panel flow,
Python versions other than 3.12, and isolated package-server downloads were
not run here. The included instructions/configuration support local trials;
run `doctor` and `scripts/verify.py` on the intended Windows machine next.
Windows may skip the symlink regression if link creation is unavailable.

No extraction or source-changing engine is included, so this milestone does
not establish transformation equivalence, dependency-graph completeness,
meaning-aware naming, or full repository understanding. No performance
benchmark against Ruff/Black and no public publishing operation was run.

M1 does not execute arbitrary target code. Python parsing and compilation
still consume resources, and this tool is not a sandbox for hostile source
or concurrently changing filesystems. The configured per-file size limit
is a bounded-input measure, not a full resource isolation mechanism.
