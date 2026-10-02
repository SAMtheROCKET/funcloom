"""Regressions for in-place statements in selected regions (0.6.0a0)."""

from pathlib import Path
import tempfile
import unittest

from funcloom import SnippetContext, plan_extraction_report
from funcloom import plan_snippet_report

TABLE_SCRIPT = '''"""Synthetic table cleaning with plain lists and dicts."""


class Table:
    def __init__(self, rows):
        self.rows = rows
        self.note = ""

    def drop_negative(self):
        self.rows = [row for row in self.rows if row["amount"] >= 0]


table = Table([{"amount": 5}, {"amount": -1}, {"amount": 7}])
alias = table.rows
table.drop_negative()
table.note = "cleaned"
totals = {"count": 0}
totals["count"] += len(table.rows)
first, *rest = table.rows
running = 0
running += first["amount"]
print(running)
'''


class StatementPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "script.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(
            self.source_path, start, end, "clean_table_tuple",
        )
        self.assertEqual(self.source_path.read_bytes(), source.encode("utf-8"))
        self.assertFalse(report.can_apply)
        return report

    def run_both(self, source: str, report) -> tuple[dict, dict]:
        # Execute only these test-authored fixtures, never target code.
        original, extracted = {}, {}
        exec(source, original)
        exec("".join(source.splitlines(True)[:report.start_line - 1]),
             extracted)
        exec(report.function_preview, extracted)
        exec(report.caller_preview, extracted)
        return original, extracted

    def test_in_place_statements_match_original_state(self):
        report = self.plan(TABLE_SCRIPT, 15, 22)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs],
                         ["table"])
        self.assertEqual([item.name for item in report.outputs],
                         ["totals", "first", "rest", "running"])
        original, extracted = self.run_both(TABLE_SCRIPT, report)
        for name in ("totals", "first", "rest", "running"):
            self.assertEqual(original[name], extracted[name])
        for name in ("rows", "note"):
            self.assertEqual(getattr(original["table"], name),
                             getattr(extracted["table"], name))
        self.assertEqual(original["alias"], extracted["alias"])

    def test_statements_without_outputs_get_a_plain_call(self):
        source = "log = []\nlog.append(1)\nlog.append(2)\n"
        report = self.plan(source, 2, 3)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.outputs, [])
        self.assertIn("    return None\n", report.function_preview)
        self.assertEqual(report.caller_preview,
                         "clean_table_tuple(\n    log,\n)\n")
        original, extracted = self.run_both(source, report)
        self.assertEqual(original["log"], extracted["log"])

    def test_module_method_reading_an_earlier_write_is_refused(self):
        source = ("scale = 1\nclass Box:\n    def grow(self):\n"
                  "        return scale * 2\nbox = Box()\n"
                  "scale = 3\nbox.size = box.grow()\n")
        report = self.plan(source, 6, 7)
        self.assertEqual([item.code for item in report.diagnostics],
                         ["PLAN008"])

    def test_remaining_statement_refusals(self):
        for statement in ("del value", "value: int = 2",
                          "(first, second), third = (1, 2), 3",
                          "value.items[0], other = 1, 2"):
            with self.subTest(statement=statement):
                report = self.plan("value = 1\n" + statement + "\n", 2, 2)
                self.assertIn("PLAN002",
                              [item.code for item in report.diagnostics])


class StatementSnippetTests(unittest.TestCase):
    def test_snippet_with_updates_and_long_call(self):
        source = ("import statistics\nreadings=[4.0, 9.0, 16.0]\n"
                  "readings.append(25.0)\n"
                  "summary_statistics_value = statistics.mean(readings) + "
                  "statistics.median(readings) + statistics.pstdev(readings)"
                  "\nsummary_statistics_value += 1\n")
        report = plan_snippet_report(source, SnippetContext(line_length=72))
        self.assertEqual(report.status, "candidate_for_review")
        preview = report.function_preview
        self.assertIn("readings.append(25.0)", preview)
        self.assertIn("summary_statistics_value = (", preview)
        self.assertLessEqual(max(map(len, preview.splitlines())), 72)
        original, extracted = {}, {}
        exec(source, original)
        exec("".join(source.splitlines(True)[:2]), extracted)
        exec(preview, extracted)
        exec(report.caller_preview, extracted)
        self.assertEqual(original["summary_statistics_value"],
                         extracted["summary_statistics_value"])
        self.assertEqual(original["readings"], extracted["readings"])

    def test_renaming_skips_attributes_and_keyword_arguments(self):
        source = ("import math\nclass Box:\n    size = 2.0\nsize=3.0\n"
                  "result = round(math.sqrt(size) * Box.size, ndigits=2)\n"
                  "ndigits = result\n")
        report = plan_snippet_report(source)
        self.assertEqual(report.status, "candidate_for_review")
        preview = report.function_preview
        self.assertIn("Box.size", preview)
        self.assertIn("ndigits=2", preview)
        self.assertIn("math.sqrt(size_float)", preview)
