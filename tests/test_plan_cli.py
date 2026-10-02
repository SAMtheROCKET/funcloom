"""Plan command status, transport, and non-overwriting output regressions."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from funcloom.cli import main


class PlanCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory(prefix="plan space ")
        self.addCleanup(self.temporary_dir.cleanup)
        self.root_path = Path(self.temporary_dir.name)
        self.source_path = self.root_path / "source file.py"
        self.source_path.write_text("base = 2\nresult = base + 1\n")
        self.arguments = ["plan", str(self.source_path), "--start-line", "2",
                          "--end-line", "2", "--name", "compute_result",
                          "--format", "json"]

    def run_command(self, arguments: list[str]) -> tuple[int, str, str]:
        output_stream, error_stream = StringIO(), StringIO()
        with redirect_stdout(output_stream), redirect_stderr(error_stream):
            exit_int = main(arguments)
        return exit_int, output_stream.getvalue(), error_stream.getvalue()

    def test_candidate_json_has_explicit_review_limits(self) -> None:
        status, output, _ = self.run_command(self.arguments)
        report = json.loads(output)
        self.assertEqual(status, 0)
        self.assertEqual(report["status"], "candidate_for_review")
        self.assertTrue(report["preview_compiles"])
        self.assertFalse(report["can_apply"])
        self.assertFalse(report["behavior_verified"])
        self.assertIn("source file.py", report["source_path"])

    def test_refusal_returns_one_with_source_location(self) -> None:
        self.source_path.write_text("base = 2\ndel base\n")
        status, output, _ = self.run_command(self.arguments)
        self.assertEqual(status, 1)
        report = json.loads(output)
        self.assertEqual(report["status"], "refused")
        self.assertEqual(report["diagnostics"][0]["line"], 2)
        self.assertIsNone(report["function_preview"])

    def test_plan_output_creates_once_and_refuses_overwrite(self) -> None:
        output_path = self.root_path / "reports" / "proposal.json"
        arguments = self.arguments + ["--output", str(output_path)]
        status, _, _ = self.run_command(arguments)
        self.assertEqual(status, 0)
        original_bytes = output_path.read_bytes()
        status, _, error = self.run_command(arguments)
        self.assertEqual(status, 2)
        self.assertTrue(error)
        self.assertEqual(output_path.read_bytes(), original_bytes)

    def test_plan_cannot_write_over_python_source(self) -> None:
        original_bytes = self.source_path.read_bytes()
        status, _, _ = self.run_command(self.arguments + [
            "--output", str(self.source_path),
        ])
        self.assertEqual(status, 2)
        self.assertEqual(self.source_path.read_bytes(), original_bytes)

    def test_bad_selection_request_is_usage_failure(self) -> None:
        status, _, error = self.run_command(self.arguments + [
            "--start-line", "0",
        ])
        self.assertEqual(status, 2)
        self.assertIn("positive lines", error)

    def test_required_selection_is_not_silently_guessed(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            main(["plan", str(self.source_path)])
        self.assertEqual(error.exception.code, 2)

    def test_apply_flag_does_not_exist(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            main(self.arguments + ["--apply"])
        self.assertEqual(error.exception.code, 2)
