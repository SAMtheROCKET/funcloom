"""Notebook, stdin, context wizard and non-overwriting CLI regressions."""

from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from funcloom import plan_snippet_file_report
from funcloom.cli import main

SOURCE = (
    "base_amount=120\ntax_rate=0.1\n"
    "tax_amount=base_amount * tax_rate\n"
    "total_amount=base_amount + tax_amount\n"
)


class SnippetCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="snippet space ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source_path = self.root / "source.py"
        self.source_path.write_bytes(SOURCE.encode())

    def command(self, arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = main(arguments)
        return status, output.getvalue(), error.getvalue()

    def notebook(self, cells, metadata=None):
        path = self.root / "example.ipynb"
        path.write_text(json.dumps({
            "nbformat": 4, "nbformat_minor": 5,
            "metadata": metadata or {}, "cells": cells,
        }), encoding="utf-8")
        return path

    def test_no_context_cli_preserves_source_and_returns_json(self):
        before = self.source_path.read_bytes()
        status, output, error = self.command([
            "snippet", str(self.source_path), "--no-context", "--format", "json",
        ])
        report = json.loads(output)
        self.assertEqual(status, 0, error)
        self.assertEqual(report["schema_version"], "snippet-1")
        self.assertFalse(report["can_apply"])
        self.assertEqual(self.source_path.read_bytes(), before)
        self.assertEqual(report["source"]["document_sha256"],
                         sha256(before).hexdigest())

    def test_context_file_and_text_reporting(self):
        context_path = self.root / "context.toml"
        context_path.write_text(
            '[snippet]\nsummary="Calculate tax totals."\n'
            '[input_types]\nbase_amount="float"\ntax_rate="float"\n',
        )
        status, output, error = self.command([
            "snippet", str(self.source_path), "--context", str(context_path),
        ])
        self.assertEqual(status, 0, error)
        self.assertIn("base_amount_float: 'float'", output)
        self.assertIn("Calculate tax totals.", output)

    def test_literal_only_cli_requests_a_choice(self):
        self.source_path.write_text("amount=120\n")
        arguments = ["snippet", str(self.source_path), "--format", "json"]
        status, output, _ = self.command(arguments)
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output)["status"], "needs_context")
        status, output, _ = self.command(arguments + ["--literal-policy", "fixed"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["plan"]["inputs"], [])

    def test_stdin_and_no_automatic_prompt(self):
        with patch("sys.stdin", StringIO(SOURCE)), patch(
            "builtins.input", side_effect=AssertionError("Unexpected prompt"),
        ):
            status, output, _ = self.command(["snippet", "-", "--format", "json"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["source"]["name"], "<stdin>")

    def test_wizard_small_context_and_no_context_modes(self):
        arguments = ["snippet", str(self.source_path), "--interactive",
                     "--format", "json"]
        for answers in (["1", ""], ["2", "", "Invoice calculation.", "Compute totals.",
                               "calculate_totals_tuple", "float", "float"]
                              + [""] * 8):
            with patch("sys.stdin.isatty", return_value=True), patch(
                "funcloom.snippet_interactive.read_answer_str",
                side_effect=answers,
            ):
                status, output, error = self.command(arguments)
            self.assertEqual(status, 0, error)
            report = json.loads(output)
            self.assertEqual(report["context_mode"],
                             "none" if answers[0] == "1" else "project")

    def test_wizard_handles_required_literal_choice(self):
        self.source_path.write_text("amount=120\n")
        with patch("sys.stdin.isatty", return_value=True), patch(
            "funcloom.snippet_interactive.read_answer_str",
            side_effect=["1", "", "y"],
        ):
            status, output, error = self.command([
                "snippet", str(self.source_path), "--interactive", "--format",
                "json",
            ])
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output)["context"]["literal_policy"], "fixed")

    def test_noninteractive_stream_and_eof_do_not_hang(self):
        with patch("sys.stdin.isatty", return_value=False):
            status, _, error = self.command([
                "snippet", str(self.source_path), "--interactive",
            ])
        self.assertEqual(status, 2)
        self.assertIn("terminal", error)
        with patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", side_effect=EOFError,
        ):
            status, _, error = self.command([
                "snippet", str(self.source_path), "--interactive",
            ])
        self.assertEqual(status, 2)
        self.assertIn("cancelled", error)

    def test_report_destination_is_new_and_never_source(self):
        output_path = self.root / "proposal.json"
        arguments = ["snippet", str(self.source_path), "--format", "json",
                     "--output", str(output_path)]
        self.assertEqual(self.command(arguments)[0], 0)
        before = output_path.read_bytes()
        self.assertEqual(self.command(arguments)[0], 2)
        self.assertEqual(output_path.read_bytes(), before)
        self.assertEqual(self.command([
            "snippet", str(self.source_path), "--output", str(self.source_path),
        ])[0], 2)
        self.assertEqual(self.source_path.read_bytes(), SOURCE.encode())

    def test_notebook_selection_ignores_other_cells_and_outputs(self):
        path = self.notebook([
            {"cell_type": "markdown", "source": "Explanation"},
            {"cell_type": "code", "source": ["raise RuntimeError('never')\n"]},
            {"cell_type": "code", "source": SOURCE.splitlines(keepends=True),
             "outputs": [{"text": "untrusted output"}], "execution_count": 7},
        ])
        before = path.read_bytes()
        report = plan_snippet_file_report(path, cell_index_int=3)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.source.cell_index, 3)
        self.assertTrue(report.plan.source_path.endswith("#cell=3"))
        self.assertEqual(report.plan.source_sha256, sha256(SOURCE.encode()).hexdigest())
        self.assertEqual(report.source.text, SOURCE)
        self.assertEqual(report.source.document_sha256, sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(report.plan.inputs[0].name, "base_amount")

    def test_single_code_cell_autoselects_and_cli_accepts_explicit_cell(self):
        path = self.notebook([
            {"cell_type": "markdown", "source": "Example"},
            {"cell_type": "code", "source": SOURCE},
        ])
        self.assertEqual(plan_snippet_file_report(path).source.cell_index, 2)
        status, output, error = self.command([
            "snippet", str(path), "--cell", "2", "--format", "json",
        ])
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output)["source"]["cell_index"], 2)

    def test_multicell_notebook_requires_selection_and_notebook_shape(self):
        path = self.notebook([
            {"cell_type": "code", "source": SOURCE},
            {"cell_type": "code", "source": SOURCE},
        ])
        with self.assertRaisesRegex(ValueError, "Choose --cell"):
            plan_snippet_file_report(path)
        for content in ("[]", '{"nbformat":4,"cells":[3]}',
                        '{"nbformat":4,"cells":[]}'):
            path.write_text(content)
            with self.assertRaises(ValueError):
                plan_snippet_file_report(path)

    def test_notebook_hidden_state_magic_and_nonpython_are_refused(self):
        path = self.notebook([{"cell_type": "code",
                               "source": "result = hidden_value + 1\n"}])
        report = plan_snippet_file_report(path)
        self.assertEqual(report.status, "refused")
        self.assertIn("PLAN003", [d.code for d in report.diagnostics])
        path = self.notebook([{"cell_type": "code", "source": "%time result=1"}])
        self.assertEqual(plan_snippet_file_report(path).diagnostics[0].code,
                         "PARSE001")
        path = self.notebook([{"cell_type": "code", "source": SOURCE}],
                             {"kernelspec": {"language": "julia"}})
        with self.assertRaisesRegex(ValueError, "Only Python"):
            plan_snippet_file_report(path)

    def test_non_utf8_python_and_cell_flags(self):
        raw = b"# coding: latin-1\n# caf\xe9\nbase=2\nresult=base+1\n"
        self.source_path.write_bytes(raw)
        report = plan_snippet_file_report(self.source_path)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.source.document_sha256, sha256(raw).hexdigest())
        self.assertEqual(report.plan.source_sha256, sha256(raw).hexdigest())
        self.assertEqual(self.source_path.read_bytes(), raw)
        with self.assertRaises(ValueError):
            plan_snippet_file_report(self.source_path, cell_index_int=1)

    def test_context_options_are_mutually_exclusive(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            main(["snippet", str(self.source_path), "--no-context",
                  "--interactive"])
