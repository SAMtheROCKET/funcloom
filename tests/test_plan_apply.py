"""Regressions for applying a plan to a new file (M3, first increment)."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from funcloom import apply_extraction_result
from funcloom.cli import main

SOURCE = ('"""Sales demo."""\nimport json\n\nvalues = [3, 1, 4]\n'
          "rate = 0.2\ntotal = 0\nfor value in values:\n"
          "    total += value * (1 + rate)\n"
          "report = {'total': round(total, 2)}\n"
          "summary = json.dumps(report)\n")


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.source = self.folder / "sales.py"

    def write_source(self, text: str, newline: str = "\n") -> bytes:
        data = text.replace("\n", newline).encode("utf-8")
        self.source.write_bytes(data)
        return data

    def run_module(self, path: Path) -> dict:
        # Execute only these test-authored fixtures, never target code.
        namespace: dict = {}
        exec(path.read_text(encoding="utf-8"), namespace)
        return namespace

    def test_candidate_is_written_to_a_new_file(self):
        original = self.write_source(SOURCE)
        output = self.folder / "sales_extracted.py"
        result = apply_extraction_result(self.source, 6, 9,
                                         "build_report_dict", output)
        self.assertEqual(result.status, "written", result.messages)
        self.assertEqual(self.source.read_bytes(), original)
        text = output.read_text(encoding="utf-8")
        self.assertIn("def build_report_dict(", text)
        self.assertTrue(text.startswith('"""Sales demo."""\nimport json\n'))
        before, after = self.run_module(self.source), self.run_module(output)
        for name in ("total", "report", "summary"):
            self.assertEqual(before[name], after[name], name)

    def test_crlf_files_stay_crlf(self):
        self.write_source(SOURCE, "\r\n")
        output = self.folder / "out.py"
        result = apply_extraction_result(self.source, 6, 9, "build_dict",
                                         output)
        self.assertEqual(result.status, "written", result.messages)
        data = output.read_bytes()
        self.assertIn(b"\r\n", data)
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))

    def test_refused_plans_write_nothing(self):
        self.write_source("total = undefined_name + 1\n")
        output = self.folder / "out.py"
        result = apply_extraction_result(self.source, 1, 1, "make_total",
                                         output)
        self.assertEqual(result.status, "refused")
        self.assertFalse(output.exists())

    def test_future_imports_stay_at_the_top(self):
        self.write_source('"""Doc."""\nfrom __future__ import annotations\n'
                          "import json\n")
        output = self.folder / "out.py"
        result = apply_extraction_result(self.source, 2, 2, "make_future",
                                         output)
        self.assertEqual(result.status, "refused")
        self.assertIn("__future__", result.plan.diagnostics[0].message)
        self.assertFalse(output.exists())
        result = apply_extraction_result(self.source, 1, 1, "make_doc",
                                         output)
        self.assertEqual(result.status, "refused")
        self.assertIn("docstring", result.plan.diagnostics[0].message)

    def test_existing_output_and_the_source_are_never_overwritten(self):
        self.write_source(SOURCE)
        existing = self.folder / "taken.py"
        existing.write_text("keep = 1\n", encoding="utf-8")
        for target in (existing, self.source):
            with self.subTest(target=target.name):
                result = apply_extraction_result(self.source, 6, 9,
                                                 "build_dict", target)
                self.assertEqual(result.status, "failed")
                self.assertIn("exists", result.messages[0])
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep = 1\n")

    def test_source_changed_after_planning_is_refused(self):
        self.write_source(SOURCE)
        output = self.folder / "out.py"
        with mock.patch("funcloom.plan_apply.read_source_tuple",
                        return_value=(SOURCE, "0" * 64)):
            result = apply_extraction_result(self.source, 6, 9,
                                             "build_dict", output)
        self.assertEqual(result.status, "failed")
        self.assertIn("changed", result.messages[0])
        self.assertFalse(output.exists())

    def test_command_line_exit_codes(self):
        self.write_source(SOURCE)
        output = self.folder / "cli_out.py"
        arguments = ["plan", str(self.source), "--start-line", "6",
                     "--end-line", "9", "--name", "build_dict",
                     "--apply-to", str(output)]
        with contextlib.redirect_stdout(io.StringIO()) as text:
            self.assertEqual(main(arguments), 0)
        self.assertIn("Applied: wrote", text.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as text:
            self.assertEqual(main(arguments), 1)
        self.assertIn("Not applied:", text.getvalue())
        self.write_source("total = undefined_name + 1\n")
        arguments[2:6] = ["--start-line", "1", "--end-line", "1"]
        arguments[-1] = str(self.folder / "refused.py")
        with contextlib.redirect_stdout(io.StringIO()) as text:
            self.assertEqual(main(arguments), 1)
        self.assertIn("refused (PLAN003", text.getvalue())


if __name__ == "__main__":
    unittest.main()
