"""Behavior regressions for release preparation; all fixtures are authored.

Only these synthetic programs are executed, never arbitrary target projects.
"""

import ast
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from funcloom import SnippetContext, plan_snippet_report
from funcloom.config import RuleProfile
from funcloom.modular_project import modularize_project_report
from funcloom.modularize import modularize_report
from funcloom.refine import RefineOptions, refine_file_report
from test_refine import filler_lines, load_module


def run_fixture(folder, name):
    """Execute an authored fixture, requiring success."""
    result = subprocess.run([sys.executable, name], cwd=folder,
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


class ReleaseFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def compare_project(self, source, dependency):
        original = self.root / "project"
        original.mkdir()
        (original / "entry.py").write_text(source, encoding="utf-8")
        (original / "dependency.py").write_text(dependency, encoding="utf-8")
        output = self.root / "generated"
        report = modularize_project_report(original, output)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(run_fixture(output, "entry.py"),
                         run_fixture(original, "entry.py"))
        return report, output

    def test_unused_late_import_still_runs(self):
        self.compare_project("print('before')\nimport dependency\n"
                             "print('after')\n", "print('imported')\n")

    def test_used_late_import_runs_after_preceding_statements(self):
        self.compare_project("print('before')\nimport dependency\n"
                             "print(dependency.value)\n",
                             "print('imported')\nvalue = 7\n")

    def test_unused_initial_import_runs_once(self):
        self.compare_project("import dependency\nprint('after')\n",
                             "print('imported')\n")

    def test_import_after_definition_keeps_definition_effects(self):
        self.compare_project("class Event:\n    print('class')\n"
                             "import dependency\nprint(Event.__name__)\n",
                             "print('imported')\n")

    def test_initial_from_imports_are_not_reexecuted_or_deduplicated(self):
        dependency = ("count = 0\ndef __getattr__(name):\n"
                      "    global count\n    if name == 'value':\n"
                      "        count += 1\n        print(count)\n"
                      "        return count\n    raise AttributeError(name)\n")
        source = ("from dependency import (\n    value,\n)\n"
                  "from dependency import (\n    value,\n)\n"
                  "def result():\n    return value\nprint(result(), value)\n")
        self.compare_project(source, dependency)

    def test_wildcard_import_is_located_refusal(self):
        report = modularize_report(source_text="from math import *\n"
                                   "print(pi)\n")
        self.assertEqual(report.status, "refused")
        self.assertIn(("MOD004", 1), [(item.code, item.line)
                                      for item in report.diagnostics])

    def test_eager_decorator_and_annotations_keep_their_effects(self):
        source = ("events = []\ndef annotation():\n"
                  "    events.append('annotation')\n    return int\n"
                  "def evaluate(function):\n"
                  "    events.append(function(0))\n    return function\n"
                  "@evaluate\ndef compute(value: annotation()):\n"
                  "    acc = []\n" + filler_lines(60)
                  + "    return value + len(acc)\n")
        original = self.root / "decorated.py"
        original.write_text(source)
        output = self.root / "refined.py"
        report = refine_file_report(original, output)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertTrue(report.split_functions)
        self.assertEqual(load_module(source).events,
                         load_module(output.read_text()).events)

    def test_method_can_run_while_class_is_being_defined(self):
        source = ("class Report:\n    def compute():\n        acc = []\n"
                  + filler_lines(60, "        ")
                  + "        return len(acc)\n    result = compute()\n")
        original = self.root / "method.py"
        original.write_text(source)
        output = self.root / "refined.py"
        report = refine_file_report(original, output)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertTrue(report.split_functions)
        self.assertEqual(load_module(source).Report.result,
                         load_module(output.read_text()).Report.result)

    def test_uncompilable_sources_refused_before_writing(self):
        for index, source in enumerate(("\nreturn 1\n", "\nbreak\n",
                                         "\nawait task()\n")):
            with self.subTest(source=source):
                original = self.root / f"invalid{index}.py"
                original.write_text(source)
                output = self.root / f"output{index}.py"
                report = refine_file_report(original, output)
                self.assertEqual(report.status, "refused")
                self.assertEqual(report.diagnostics[0].line, 2)
                self.assertFalse(output.exists())
                self.assertEqual(original.read_text(), source)

    def test_invalid_final_output_is_refused(self):
        original = self.root / "valid.py"
        original.write_text("value = 1\n")
        output = self.root / "out.py"
        with patch("funcloom.refine.insert_docstrings_tuple",
                   return_value=("return 1\n", [])):
            report = refine_file_report(original, output,
                                        options_info=RefineOptions(False, True))
        self.assertEqual(report.status, "refused")
        self.assertFalse(output.exists())

    def test_invalid_compile_fails_file_and_is_copied_in_folder(self):
        # A single invalid file is refused; in a folder it is copied
        # unchanged with a located warning so the rest can be converted.
        project = self.root / "project"
        project.mkdir()
        original = project / "invalid.py"
        original.write_text("return 1\n")
        (project / "good.py").write_text("print(1)\n")
        for index, (path, options) in enumerate((
            (original, []), (project, []),
            (original, ["--keep-long-functions"]),
            (project, ["--keep-long-functions"]),
        )):
            output = self.root / f"out{index}"
            result = subprocess.run(
                [sys.executable, "-m", "funcloom", "refine", str(path),
                 "--output", str(output), "--format", "json", *options],
                capture_output=True, text=True, timeout=15)
            if path == original:
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("MOD001", result.stdout)
                self.assertFalse(output.exists())
                continue
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("MODW07", result.stdout)
            self.assertEqual((output / "invalid.py").read_bytes(),
                             original.read_bytes())
            self.assertTrue((output / "good.py").exists())

    def test_refine_api_validates_profile(self):
        with self.assertRaisesRegex(ValueError, "40 to 200"):
            refine_file_report(self.root / "missing.py", self.root / "out.py",
                               replace(RuleProfile(), line_length=39))

    def test_wrapped_prose_cannot_create_a_directive(self):
        for directive in ("type: ignore[assignment]", "noqa: E501",
                          "fmt: off", "pyright: ignore"):
            source = "x=1\n# " + "note " * 11 + directive + "\ny=x+1\n"
            with self.subTest(directive=directive):
                self.assertFalse(ast.parse(source, type_comments=True)
                                 .type_ignores)
                report = plan_snippet_report(source,
                                             SnippetContext(line_length=60))
                self.assertEqual(report.status, "refused")
                self.assertIsNone(report.function_preview)
                self.assertEqual((report.diagnostics[-1].code,
                                  report.diagnostics[-1].line), ("SNIP004", 2))

    def test_inline_prose_refusal_keeps_original_location(self):
        source = "x=1\ny=x+1  # " + "note " * 10 + "type: ignore[assignment]\n"
        report = plan_snippet_report(source, SnippetContext(line_length=60))
        self.assertEqual(report.status, "refused")
        self.assertEqual((report.diagnostics[-1].code,
                          report.diagnostics[-1].line), ("SNIP004", 2))

    def test_helper_annotations_are_quoted_once(self):
        from funcloom.function_split_text import split_functions_text_tuple
        text = ("class Box:\n    pass\n\n\nclass Report:\n"
                "    def build(self, rows: list[int]) -> 'Report':\n"
                "        acc = []\n        box = Box()\n"
                + filler_lines(22, " " * 8) + "        self.box = box\n"
                + filler_lines(22, " " * 8)
                + "        return self if box and acc else self\n")
        new_text, _, names = split_functions_text_tuple(text, 79, 40)
        self.assertEqual(names, ["Report.build"])
        annotations = []
        for node in ast.walk(ast.parse(new_text)):
            if isinstance(node, ast.FunctionDef) and node.name.startswith(
                "_Report",
            ):
                annotations += [item.annotation for item in node.args.args
                                if item.annotation is not None]
                annotations += [node.returns] if node.returns else []
        self.assertTrue(annotations)
        for annotation in annotations:
            self.assertIsInstance(annotation, ast.Constant)
            self.assertNotIn("'", annotation.value)
        refined = load_module(new_text).Report()
        self.assertIs(refined.build([1]), refined)

    def test_comment_above_split_function_stays_attached(self):
        text = ("#!/usr/bin/env python\n# Summary of f.\n"
                "def f(n):\n    acc = []\n" + filler_lines(22)
                + "    n = n + 1\n" + filler_lines(22)
                + "    return n, len(acc)\n")
        from funcloom.function_split_text import split_functions_text_tuple
        new_text, _, names = split_functions_text_tuple(text, 79, 40)
        self.assertEqual(names, ["f"])
        lines = new_text.splitlines()
        self.assertEqual(lines[0], "#!/usr/bin/env python")
        index = lines.index("# Summary of f.")
        self.assertEqual(lines[index + 1], "def f(n):")
        self.assertEqual(load_module(new_text).f(1),
                         load_module(text).f(1))


    # Found by converting real repositories (1 October 2026).
    def test_docstring_function_kept_in_step_keeps_its_text(self):
        source = ('import sys\n\nlimit = len(sys.argv)\n\n\n'
                  'def show(value):\n    """Show a value.\n\n    Args:\n'
                  '        value: Anything.\n    """\n'
                  '    print(value, limit)  # uses script state\n\n\n'
                  'show(show.__doc__)\n')
        path = self.root / "doc_script.py"
        path.write_text(source)
        report = modularize_report(path, output_dir=self.root / "doc_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(run_fixture(self.root / "doc_out", "main.py"),
                         run_fixture(self.root, "doc_script.py"))
        self.assertIn("# uses script state", (
            self.root / "doc_out" / "doc_script" / "steps.py").read_text())

    def test_wrapping_keeps_fstrings_intact(self):
        from funcloom.snippet_wrapping import wrap_statement_str
        source = ('path = os.path.join(output_folder_name, '
                  'f"{country}_output_all.pkl", f"{a:{w}d} {f"x{b}"}", '
                  'another_argument)\n')
        wrapped = wrap_statement_str(source, 60, 0)
        self.assertEqual(ast.dump(ast.parse(wrapped)),
                         ast.dump(ast.parse(source)))
        self.assertIn('f"{country}_output_all.pkl"', wrapped)

    def test_single_wrapped_result_is_not_a_tuple(self):
        from funcloom.function_split_text import split_functions_text_tuple
        names = ", ".join(f"argument_number_{index}" for index in range(4))
        text = (f"def build({names}):\n    parts = []\n"
                + "".join(f"    parts.append(argument_number_{index % 4})\n"
                          for index in range(25))
                + "".join(f"    parts.append(len(parts) + {index})\n"
                          for index in range(20))
                + f"    return parts, {names}\n")
        new_text, _, split_names = split_functions_text_tuple(text, 79, 40)
        self.assertEqual(split_names[0], "build")
        self.assertIn("    parts = _build_part_1(\n", new_text)
        self.assertNotIn("parts,\n    ) =", new_text)
        self.assertEqual(load_module(new_text).build(1, 2, 3, 4),
                         load_module(text).build(1, 2, 3, 4))

    def test_annotated_constant_imports_its_annotation_names(self):
        source = ('from typing import Any\n\n'
                  'LAYOUT: Any = "a"\nprint(LAYOUT)\n')
        path = self.root / "typed.py"
        path.write_text(source)
        report = modularize_report(path, output_dir=self.root / "typed_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(run_fixture(self.root / "typed_out", "main.py"),
                         "a\n")

    def test_virtual_environments_of_any_name_are_skipped(self):
        project = self.root / "venv_project"
        (project / "env" / "Lib").mkdir(parents=True)
        (project / "env" / "pyvenv.cfg").write_text("home = x\n")
        (project / "env" / "Lib" / "site.py").write_text("x = 1\n")
        (project / "tool.py").write_text("print(1)\n")
        report = modularize_project_report(project, self.root / "venv_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertFalse((self.root / "venv_out" / "env").exists())

    def test_over_long_windows_paths_are_refused_up_front(self):
        from funcloom import modular_verify
        project = self.root / "long_project"
        project.mkdir()
        (project / "tool.py").write_text("print(1)\n")
        with patch.object(modular_verify, "read_windows_path_limit_int",
                          return_value=20):
            report = modularize_project_report(project,
                                               self.root / "long_out")
        self.assertEqual(report.status, "refused")
        self.assertIn("Windows limit", report.diagnostics[0].message)
        self.assertFalse((self.root / "long_out").exists())


    def test_script_imported_via_sys_path_is_not_converted(self):
        project = self.root / "path_project"
        (project / "tools").mkdir(parents=True)
        (project / "tests").mkdir()
        (project / "tools" / "render.py").write_text(
            "def figure():\n    return 42\n\n\nprint(figure())\n")
        (project / "tests" / "check_render.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).parent.parent / 'tools'))"
            "\nfrom render import figure\nprint(figure())\n")
        out = self.root / "path_out"
        report = modularize_project_report(project, out)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual((out / "tools" / "render.py").read_bytes(),
                         (project / "tools" / "render.py").read_bytes())
        self.assertEqual(run_fixture(out / "tests", "check_render.py"),
                         "42\n42\n")


    def test_script_like_module_inside_package_stays_a_module(self):
        project = self.root / "pkg_project"
        (project / "pkg").mkdir(parents=True)
        (project / "pkg" / "__init__.py").write_text("")
        (project / "pkg" / "page.py").write_text("TITLE = 'x'\nprint(TITLE)\n")
        (project / "run.py").write_text(
            "import importlib\n"
            "print(importlib.import_module('pkg.page').TITLE)\n")
        out = self.root / "pkg_out"
        report = modularize_project_report(project, out)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertIn("module inside a package",
                      report.kept_scripts["pkg/page.py"])
        self.assertEqual(run_fixture(out, "run.py"), "x\nx\n")


    def with_program(self, manager):
        return ("import contextlib\n\n# Read\n"
                f"with {manager}:\n    size = 3\n    label = 'ok'\n\n\n"
                "# Report\nprint(size, label)\n")

    def test_trust_with_blocks_separates_steps(self):
        source = self.with_program("contextlib.nullcontext()")
        path = self.root / "with_script.py"
        path.write_text(source)
        strict = modularize_report(path)
        self.assertEqual(len(strict.steps), 1)
        self.assertTrue(any("--trust-with-blocks" in note
                            for note in strict.notes))
        trusted = modularize_report(
            path, output_dir=self.root / "trusted_out",
            options_info=RefineOptions(trust_with_blocks=True))
        self.assertEqual(trusted.status, "written", trusted.diagnostics)
        self.assertEqual(len(trusted.steps), 2)
        self.assertEqual(run_fixture(self.root / "trusted_out", "main.py"),
                         run_fixture(self.root, "with_script.py"))

    def test_trust_with_blocks_never_trusts_suppress(self):
        path = self.root / "suppress_script.py"
        path.write_text(self.with_program("contextlib.suppress(KeyError)"))
        report = modularize_report(
            path, options_info=RefineOptions(trust_with_blocks=True))
        self.assertEqual(len(report.steps), 1)

    def test_trust_with_blocks_cli_flag(self):
        path = self.root / "flag_script.py"
        path.write_text(self.with_program("contextlib.nullcontext()"))
        result = subprocess.run(
            [sys.executable, "-m", "funcloom", "modularize", str(path),
             "--trust-with-blocks", "--format", "json"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        import json
        self.assertEqual(len(json.loads(result.stdout)["steps"]), 2)


    # Found by converting the example notebooks (1 October 2026).
    def test_nested_function_returns_are_not_rewritten(self):
        from funcloom.function_split_text import split_functions_text_tuple
        text = ("def outer(flag):\n    acc = []\n" + filler_lines(22)
                + "    def helper(value):\n        if value:\n"
                "            return value * 2\n        return -1\n"
                + filler_lines(22)
                + "    if flag:\n        return helper(len(acc))\n"
                "    return helper(0), len(acc)\n")
        new_text, _, names = split_functions_text_tuple(text, 79, 40)
        self.assertEqual(names[:1], ["outer"])
        self.assertIn("            return value * 2\n", new_text)
        for flag in (True, False):
            self.assertEqual(load_module(new_text).outer(flag),
                             load_module(text).outer(flag))

    def test_single_pipeline_result_on_a_wrapped_line(self):
        long_name = "value_with_a_rather_long_descriptive_name_" * 2
        source = (f"import sys\n\n# Make\n{long_name} = len(sys.argv)\n\n\n"
                  f"# Use\nprint({long_name})\n")
        path = self.root / "long_names.py"
        path.write_text(source)
        report = modularize_report(path, output_dir=self.root / "long_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(run_fixture(self.root / "long_out", "main.py"),
                         run_fixture(self.root, "long_names.py"))

    def test_broken_pipeline_layout_is_refused(self):
        from funcloom import modular_pipeline
        original = modular_pipeline.call_lines_list

        def unpacking_lines(step_info, attributes_dict, width_int):
            lines = original(step_info, attributes_dict, width_int)
            if step_info.outputs:
                name = attributes_dict[step_info.outputs[0]]
                return [line.replace(f"self.{name} =", f"(self.{name},) =")
                        for line in lines]
            return lines

        path = self.root / "layout.py"
        path.write_text("import sys\n\n# Make\nx = len(sys.argv)\n\n\n"
                        "# Use\nprint(x)\n")
        with patch.object(modular_pipeline, "call_lines_list",
                          unpacking_lines):
            report = modularize_report(path)
        self.assertEqual(report.status, "refused")
        self.assertIn("Pipeline calls changed",
                      report.diagnostics[-1].message)

    def test_notebook_display_is_defined(self):
        import json
        notebook = {"cells": [
            {"cell_type": "code", "metadata": {}, "outputs": [],
             "execution_count": None, "source": ["value = 41 + 1\n"]},
            {"cell_type": "code", "metadata": {}, "outputs": [],
             "execution_count": None, "source": ["display(value)\n"]}],
            "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        path = self.root / "shown.ipynb"
        path.write_text(json.dumps(notebook))
        report = modularize_report(path, output_dir=self.root / "shown_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertIn("MODW08", [item.code for item in report.diagnostics])
        output = run_fixture(self.root / "shown_out", "main.py")
        self.assertIn("42", output)
