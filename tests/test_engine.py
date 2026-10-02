"""Regression tests for read-only behavior and accurate source facts."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from funcloom import RuleProfile, check_project_report, scan_project_report
from funcloom.reporting import report_dict


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_dir.cleanup)
        self.root_path = Path(self.temporary_dir.name)

    def write_source(self, name: str, source: str) -> Path:
        source_path = self.root_path / name
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(source, encoding="utf-8")
        return source_path

    def test_target_code_and_imports_are_not_executed(self) -> None:
        sentinel_path = self.root_path / "should_not_exist.txt"
        source_path = self.write_source(
            "effects.py", "import definitely_nonexistent_package\n"
            f"open({str(sentinel_path)!r}, 'w').write('executed')\n"
            "raise RuntimeError('Do not run me')\n",
        )
        before_bytes = source_path.read_bytes()
        report = check_project_report(source_path)
        self.assertEqual(len(report.modules), 1)
        self.assertFalse(sentinel_path.exists())
        self.assertEqual(before_bytes, source_path.read_bytes())

    def test_same_basenames_keep_their_relative_paths(self) -> None:
        self.write_source("first/data.py", "first_value_int = 1\n")
        self.write_source("second/data.py", "second_value_int = 2\n")
        report = scan_project_report(self.root_path)
        self.assertEqual(
            [module.path for module in report.modules],
            ["first/data.py", "second/data.py"],
        )

    def test_default_exclusions_prune_environments(self) -> None:
        self.write_source("source.py", "pass\n")
        for folder_str in (".venv", "node_modules", "dist", "demo.egg-info"):
            self.write_source(f"{folder_str}/bad.py", "this is invalid !\n")
        report = scan_project_report(self.root_path)
        self.assertEqual(len(report.modules), 1)
        self.assertEqual(len(report.skipped), 4)
        self.assertFalse(report.diagnostics)

    def test_file_and_directory_symlinks_are_skipped(self) -> None:
        source_path = self.write_source("source.py", "pass\n")
        try:
            (self.root_path / "alias.py").symlink_to(source_path)
            (self.root_path / "loop").symlink_to(
                self.root_path, target_is_directory=True,
            )
        except OSError as error:
            self.skipTest(f"Symbolic links not available: {error}")
        report = scan_project_report(self.root_path)
        self.assertEqual(len(report.modules), 1)
        self.assertEqual(len(report.skipped), 2)
        with self.assertRaises(ValueError):
            scan_project_report(self.root_path / "alias.py")

    def test_compile_failure_is_not_mistaken_for_valid_ast(self) -> None:
        self.write_source("invalid.py", "return 7\n")
        self.write_source("valid.py", "pass\n")
        report = scan_project_report(self.root_path)
        self.assertEqual(len(report.modules), 1)
        self.assertEqual(report.diagnostics[0].code, "PARSE001")
        self.assertFalse(report_dict(report)["summary"]["analysis_complete"])

    def test_invalid_syntax_keeps_source_untouched(self) -> None:
        source_path = self.write_source("invalid.py", "def unfinished(\n")
        before_bytes = source_path.read_bytes()
        report = check_project_report(source_path)
        self.assertEqual(report.diagnostics[0].severity, "error")
        self.assertEqual(source_path.read_bytes(), before_bytes)

    def test_encoding_cookie_is_respected(self) -> None:
        source_path = self.root_path / "encoded.py"
        source_path.write_bytes(
            b"# coding: latin-1\nlabel_str = 'caf\xe9'\n"
        )
        self.assertEqual(len(scan_project_report(source_path).modules), 1)

    def test_bad_encoding_is_reported(self) -> None:
        source_path = self.root_path / "encoded.py"
        source_path.write_bytes(b"label_str = '\xff'\n")
        report = scan_project_report(source_path)
        self.assertTrue(report.diagnostics)
        self.assertEqual(report.diagnostics[0].severity, "error")

    def test_resource_limit_is_an_explicit_error(self) -> None:
        source_path = self.write_source("large.py", "pass\n" * 10)
        report = scan_project_report(
            source_path, replace(RuleProfile(), max_file_bytes=8),
        )
        self.assertEqual(report.diagnostics[0].code, "READ001")

    def test_nested_scopes_and_method_arguments_stay_separate(self) -> None:
        source_path = self.write_source("nested.py", '''class Vehicle:
    async def compute(self, value_int: int) -> int:
        def inner(self):
            return self
        return value_int
''')
        report = check_project_report(source_path)
        functions_list = report.modules[0].functions
        self.assertEqual(
            [item.qualified_name for item in functions_list],
            ["Vehicle.compute", "Vehicle.compute.inner"],
        )
        self.assertTrue(functions_list[0].is_async)
        self.assertTrue(functions_list[0].is_method)
        self.assertFalse(functions_list[1].is_method)
        missing_list = [
            item for item in report.diagnostics if item.code == "TYPE001"
        ]
        self.assertEqual(len(missing_list), 1)
        self.assertIn("inner", missing_list[0].message)

    def test_all_argument_kinds_are_checked(self) -> None:
        source_path = self.write_source(
            "parameters.py",
            "def example(a, /, b: int, *args, flag, **kwargs) -> None:\n"
            "    pass\n",
        )
        report = check_project_report(source_path)
        missing_list = [
            item for item in report.diagnostics if item.code == "TYPE001"
        ]
        self.assertEqual(len(missing_list), 4)
        self.assertEqual(
            [item.kind for item in report.modules[0].functions[0].parameters],
            ["positional_only", "positional_or_keyword", "vararg",
             "keyword_only", "kwarg"],
        )

    def test_decorators_count_toward_physical_span(self) -> None:
        source_path = self.write_source(
            "decorated.py", "@unknown_decorator\ndef work() -> None:\n"
            "    pass\n",
        )
        report = scan_project_report(source_path)
        self.assertEqual(report.modules[0].functions[0].physical_lines, 3)

    def test_size_thresholds_are_precise(self) -> None:
        source_path = self.write_source(
            "length.py", "def work() -> None:\n" + "    pass\n" * 49,
        )
        report = check_project_report(source_path)
        codes_set = {item.code for item in report.diagnostics}
        self.assertIn("SIZE001", codes_set)
        self.assertNotIn("SIZE002", codes_set)
        source_path.write_text(source_path.read_text() + "    pass\n")
        report = check_project_report(source_path)
        self.assertIn("SIZE002", {item.code for item in report.diagnostics})

    def test_orchestrator_exception_does_not_cover_nested_main(self) -> None:
        source_path = self.write_source(
            "entry.py", "def main() -> None:\n" + "    pass\n" * 55
            + "class Runner:\n    def main(self) -> None:\n"
            + "        pass\n" * 55,
        )
        report = check_project_report(source_path)
        size_list = [
            item for item in report.diagnostics if item.code.startswith("SIZE")
        ]
        self.assertEqual(len(size_list), 1)
        self.assertIn("Runner.main", size_list[0].message)

    def test_main_guard_recognizes_reversed_equality(self) -> None:
        source_path = self.write_source(
            "guard.py", 'if "__main__" == __name__:\n    pass\n'
            'if "__name__" == "irrelevant":\n    pass\n',
        )
        report = scan_project_report(source_path)
        self.assertEqual(len(report.modules[0].main_guards), 1)

    def test_main_guard_limit_is_checked(self) -> None:
        source_path = self.write_source(
            "guard.py", 'if __name__ == "__main__":\n' + "    pass\n" * 100,
        )
        report = check_project_report(source_path)
        self.assertIn("SIZE004", {item.code for item in report.diagnostics})

    def test_line_length_and_analysis_completion_are_distinct(self) -> None:
        source_path = self.write_source("wide.py", "#" + "a" * 79 + "\n")
        report = check_project_report(source_path)
        self.assertEqual(report.diagnostics[0].code, "FMT001")
        self.assertTrue(report_dict(report)["summary"]["analysis_complete"])

    def test_docstring_sections_and_return_annotation_are_checked(self) -> None:
        source_path = self.write_source(
            "docs.py", 'def calculate_value(value_int: int):\n'
            '    """Calculate a value."""\n    return value_int\n',
        )
        report = check_project_report(source_path)
        self.assertEqual(
            sum(item.code == "DOC002" for item in report.diagnostics), 3,
        )
        self.assertIn("TYPE002", {item.code for item in report.diagnostics})

    def test_report_is_repeatable_and_does_not_claim_full_compliance(self) -> None:
        source_path = self.write_source("source.py", "pass\n")
        first_dict = report_dict(check_project_report(source_path))
        second_dict = report_dict(check_project_report(source_path))
        self.assertEqual(first_dict, second_dict)
        self.assertFalse(first_dict["summary"]["all_rules_implemented"])
        self.assertFalse(first_dict["summary"]["behavior_verified"])

    def test_missing_or_empty_targets_fail_explicitly(self) -> None:
        with self.assertRaises(ValueError):
            scan_project_report(self.root_path / "missing")
        with self.assertRaises(ValueError):
            scan_project_report(self.root_path)

    def test_parent_segments_are_normalized_for_single_files(self) -> None:
        self.write_source("nested/source.py", "pass\n")
        target_path = self.root_path / "nested" / ".." / "nested" / "source.py"
        report = scan_project_report(target_path)
        self.assertEqual(report.modules[0].path, "source.py")
