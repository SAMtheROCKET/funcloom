"""Integration checks for configuration, CLI status, and report writes."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from funcloom import RuleProfile, load_profile, scan_project_report
from funcloom.cli import main


class CliAndConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_dir.cleanup)
        self.root_path = Path(self.temporary_dir.name)
        self.source_path = self.root_path / "example.py"
        self.source_path.write_text("def calculate(x):\n    return x\n")

    def run_command(self, arguments: list[str]) -> tuple[int, str, str]:
        output_stream, error_stream = StringIO(), StringIO()
        with redirect_stdout(output_stream), redirect_stderr(error_stream):
            exit_int = main(arguments)
        return exit_int, output_stream.getvalue(), error_stream.getvalue()

    def test_no_arguments_show_the_quick_start(self) -> None:
        status, output, error = self.run_command([])
        self.assertEqual((status, error), (0, ""))
        for command_str in ("funcloom check", "funcloom snippet",
                            "funcloom plan", "funcloom modularize",
                            "funcloom refine"):
            self.assertIn(command_str, output)

    def test_doctor_reports_real_runtime(self) -> None:
        status, output, _ = self.run_command(["doctor", "--format", "json"])
        result_dict = json.loads(output)
        self.assertEqual(status, 0)
        self.assertTrue(Path(result_dict["python_executable"]).is_file())
        self.assertFalse(result_dict["source_execution"])

    def test_check_warning_threshold_is_explicit(self) -> None:
        arguments = ["check", str(self.source_path), "--format", "json"]
        status, output, _ = self.run_command(arguments)
        self.assertEqual(status, 0)
        self.assertGreater(json.loads(output)["summary"]["warnings"], 0)
        status, _, _ = self.run_command(arguments + ["--fail-on", "warning"])
        self.assertEqual(status, 1)

    def test_parse_error_has_nonzero_status_in_scan(self) -> None:
        self.source_path.write_text("def (\n")
        status, output, _ = self.run_command([
            "scan", str(self.source_path), "--format", "json",
        ])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output)["summary"]["errors"], 1)

    def test_output_file_is_created_and_never_overwritten(self) -> None:
        output_path = self.root_path / "reports" / "scan.json"
        arguments = [
            "scan", str(self.source_path), "--format", "json", "--output",
            str(output_path),
        ]
        status, _, _ = self.run_command(arguments)
        self.assertEqual(status, 0)
        original_bytes = output_path.read_bytes()
        status, _, error = self.run_command(arguments)
        self.assertEqual(status, 2)
        self.assertTrue(error)
        self.assertEqual(output_path.read_bytes(), original_bytes)

    def test_report_cannot_be_written_over_python_source(self) -> None:
        original_bytes = self.source_path.read_bytes()
        status, _, _ = self.run_command([
            "scan", str(self.source_path), "--output", str(self.source_path),
        ])
        self.assertEqual(status, 2)
        self.assertEqual(self.source_path.read_bytes(), original_bytes)

    def test_invalid_profile_keys_and_types_fail(self) -> None:
        for contents in (
            "[profile]\nline_lenght = 79\n",
            "[profile]\nline_length = true\n",
            '[profile]\nexcluded_dirs = "venv"\n',
            "[other]\nline_length = 79\n",
            "[profile]\nfunction_target_lines = 51\n",
        ):
            with self.subTest(contents=contents):
                config_path = self.root_path / "rules.toml"
                config_path.write_text(contents)
                status, _, error = self.run_command([
                    "check", str(self.source_path), "--config",
                    str(config_path),
                ])
                self.assertEqual(status, 2)
                self.assertTrue(error)

    def test_profile_override_does_not_drop_default_exclusions(self) -> None:
        config_path = self.root_path / "rules.toml"
        config_path.write_text("[profile]\nline_length = 80\n")
        profile = load_profile(config_path)
        self.assertEqual(profile.line_length, 80)
        self.assertIn(".venv", profile.excluded_dirs)

    def test_python_api_also_validates_profile(self) -> None:
        with self.assertRaises(ValueError):
            scan_project_report(
                self.source_path, replace(RuleProfile(), line_length=-1),
            )

    def test_missing_config_returns_usage_failure(self) -> None:
        status, _, error = self.run_command([
            "scan", str(self.source_path), "--config",
            str(self.root_path / "missing.toml"),
        ])
        self.assertEqual(status, 2)
        self.assertTrue(error)
