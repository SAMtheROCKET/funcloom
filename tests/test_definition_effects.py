"""Behavioral regressions for definition-time effects, notebook strings
and source encodings (the 1 October 2026 production review).

Every fixture is authored here and runs only in a temporary folder.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from funcloom.modular_project import modularize_project_report
from funcloom.modularize import modularize_report
from funcloom.refine import refine_file_report


def run_str(folder: Path, script: str) -> str:
    """Run an authored script and return its output, failing on errors."""
    result = subprocess.run([sys.executable, script], cwd=folder,
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


class DefinitionEffectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def convert(self, source: str, name: str = "program.py"):
        folder = self.root / name.split(".")[0]
        folder.mkdir()
        path = folder / name
        path.write_text(source, encoding="utf-8")
        report = modularize_report(path, output_dir=folder / "out")
        return report, folder

    def assert_same(self, source: str, name: str = "program.py"):
        report, folder = self.convert(source, name)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(run_str(folder / "out", "main.py"),
                         run_str(folder, name))
        return report, folder

    def test_review_cases_keep_every_definition_effect(self):
        for source in (
            "class Registration:\n    print('registered')\nprint('done')\n",
            "def calculate(value=print('initialized')):\n"
            "    return value\nprint('done')\n",
            "class Registration:\n    print('class first')\n"
            "def calculate(value=print('default second')):\n"
            "    return value\nprint(bool(Registration), bool(calculate))\n",
            "print('before')\nclass Registration:\n"
            "    print('class after')\nprint(bool(Registration))\n",
        ):
            with self.subTest(source=source.splitlines()[0]):
                self.setUp()
                report, _ = self.assert_same(source)
                self.assertTrue(any("stays in its original place" in note
                                    for note in report.notes))

    def test_registering_decorator_still_registers(self):
        source = ("REGISTRY = []\n\n\ndef register(function):\n"
                  "    REGISTRY.append(function.__name__)\n"
                  "    return function\n\n\n@register\ndef handler():\n"
                  "    return 1\n\n\nprint(REGISTRY)\n")
        self.assert_same(source)

    def test_pure_definitions_still_move_to_modules(self):
        source = ("import functools\n\n\nclass Box:\n"
                  "    '''A box.'''\n    size: int = 3\n\n"
                  "    def double(self) -> int:\n"
                  "        return self.size * 2\n\n\n"
                  "def square(value: int = 2) -> int:\n"
                  "    return value * value\n\n\n"
                  "print(Box().double(), square())\n")
        report, _ = self.assert_same(source)
        self.assertEqual(sorted(report.moved_definitions),
                         ["Box", "square"])

    def test_effectful_module_annotation_is_refused(self):
        report, folder = self.convert(
            "amount: print('annotation evaluated') = 12\nprint(amount)\n")
        self.assertEqual(report.status, "refused")
        self.assertEqual([(item.code, item.line) for item in
                          report.diagnostics], [("MOD010", 1)])
        self.assertFalse((folder / "out").exists())
        typed_report, _ = self.convert(
            "from typing import Final\n\n"
            "limit: Final[int] = 3\nprint(limit)\n", "typed.py")
        self.assertEqual(typed_report.status, "refused")
        self.assertTrue(any(item.code == "MOD010"
                            for item in typed_report.diagnostics))


class NotebookAndEncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_magic_like_lines_inside_strings_are_kept(self):
        cell = ("%load_ext something\n"
                "message = '''Invoice details:\n% discount applied\n"
                "! urgent delivery\nstatus?\n'''\n"
                "!echo hidden\nprint(repr(message))\n")
        notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {},
                    "cells": [{"cell_type": "code", "metadata": {},
                               "source": cell, "outputs": [],
                               "execution_count": None}]}
        path = self.root / "invoice.ipynb"
        path.write_text(json.dumps(notebook), encoding="utf-8")
        report = modularize_report(path, output_dir=self.root / "out")
        self.assertEqual(report.status, "written", report.diagnostics)
        expected = repr("Invoice details:\n% discount applied\n"
                        "! urgent delivery\nstatus?\n") + "\n"
        self.assertEqual(run_str(self.root / "out", "main.py"), expected)
        removed_list = [note for note in report.notes
                        if "magic removed" in note]
        self.assertEqual(len(removed_list), 2, removed_list)

    def latin1_path(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "legacy.py"
        path.write_bytes(b"# coding: latin-1\n\n\ndef codes():\n"
                         b"    return [ord(char) for char in '\xc3\xa9']\n")
        return path

    def test_refine_refuses_sources_declaring_another_encoding(self):
        path = self.latin1_path(self.root / "single")
        path.write_bytes(path.read_bytes() + b"\n\nprint(codes())\n")
        report = refine_file_report(path, self.root / "single" / "out.py")
        self.assertEqual(report.status, "refused")
        self.assertIn("declares another encoding",
                      report.diagnostics[0].message)
        self.assertFalse((self.root / "single" / "out.py").exists())

    def test_folder_mode_copies_non_utf8_sources_unchanged(self):
        path = self.latin1_path(self.root / "project")
        (self.root / "project" / "tool.py").write_text(
            "from legacy import codes\nprint(codes())\n")
        report = modularize_project_report(self.root / "project",
                                           self.root / "project_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        copied = self.root / "project_out" / "legacy.py"
        self.assertEqual(copied.read_bytes(), path.read_bytes())
        self.assertEqual(run_str(self.root / "project_out", "tool.py"),
                         run_str(self.root / "project", "tool.py"))
        self.assertEqual(run_str(self.root / "project", "tool.py"),
                         "[195, 169]\n")

    def test_utf8_cookie_file_still_refines(self):
        path = self.root / "modern.py"
        path.write_text("# -*- coding: utf-8 -*-\nprint('café')\n",
                        encoding="utf-8")
        report = refine_file_report(path, self.root / "modern_out.py")
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(run_str(self.root, "modern_out.py"),
                         run_str(self.root, "modern.py"))

    def test_generated_files_never_carry_a_foreign_cookie(self):
        path = self.root / "coded.py"
        path.write_bytes(b"# -*- coding: latin-1 -*-\nimport os\n"
                         b"LABEL = '\xe9t\xe9'\n"
                         b"print(len(LABEL), ord(LABEL[0]), os.sep != '')\n")
        report = modularize_report(path, output_dir=self.root / "coded_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(run_str(self.root / "coded_out", "main.py"),
                         run_str(self.root, "coded.py"))
        for generated in (self.root / "coded_out").rglob("*.py"):
            self.assertNotIn("latin-1", generated.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
