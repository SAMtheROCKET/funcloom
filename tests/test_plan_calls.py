"""Regressions for calls in selected regions and the PLAN008 check."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from funcloom import SnippetContext, plan_extraction_report
from funcloom import plan_snippet_report

CALL_SCRIPT = '''import math


def describe(value, digits=1):
    text = f"{value:.{digits}f}"
    return text


data = [5, 1, 4]
radius = 2.0
area = math.pi * radius ** 2
label = describe(area, digits=2)
values = sorted(data)[:2]
largest = max(values)
ok = largest > 1 and label != "" or None
'''

DELAYED_READ_SCRIPT = '''rate = 0.1


def total(amount):
    return amount * (1 + rate)


rate = 0.2
result = total(100)
'''


class CallPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "script.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(
            self.source_path, start, end, "calculate_values_tuple",
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

    def assert_same_results(self, source: str, report) -> None:
        original, extracted = self.run_both(source, report)
        for item in report.outputs:
            self.assertEqual(original[item.name], extracted[item.name])

    def codes(self, report) -> list[str]:
        return [item.code for item in report.diagnostics]

    def test_calls_attributes_subscripts_and_comparisons(self):
        report = self.plan(CALL_SCRIPT, 11, 15)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs],
                         ["math", "radius", "describe", "data"])
        self.assertTrue(any("'max' stays a free name" in item
                            for item in report.assumptions))
        self.assert_same_results(CALL_SCRIPT, report)

    def test_delayed_write_seen_by_module_function_is_refused(self):
        report = self.plan(DELAYED_READ_SCRIPT, 8, 9)
        self.assertEqual(self.codes(report), ["PLAN008"])
        self.assertEqual(report.diagnostics[0].line, 9)
        self.assertIn("'rate'", report.diagnostics[0].message)
        self.assertIsNone(report.function_preview)

    def test_refused_draft_would_really_change_the_result(self):
        with patch("funcloom.planning.check_dispatch_none"):
            unchecked = self.plan(DELAYED_READ_SCRIPT, 8, 9)
        self.assertEqual(unchecked.status, "candidate_for_review")
        original, extracted = self.run_both(DELAYED_READ_SCRIPT, unchecked)
        self.assertAlmostEqual(original["result"], 120.0)
        self.assertAlmostEqual(extracted["result"], 110.0)

    def test_write_in_same_statement_as_call_is_allowed(self):
        source = DELAYED_READ_SCRIPT.replace("rate = 0.2\nresult", "result")
        source = source.replace("result = total(100)", "rate = total(100)")
        report = self.plan(source, 8, 8)
        self.assertEqual(report.status, "candidate_for_review")
        self.assert_same_results(source, report)

    def test_helper_locals_and_closures_are_not_globals(self):
        source = ('def helper(x):\n    result = x * 2\n    return result\n'
                  'def outer():\n    total = 1\n    def inner():\n'
                  '        return total\n    return inner()\n'
                  'result = 1\ntotal = 5\ny = helper(3) + outer()\n')
        report = self.plan(source, 9, 11)
        self.assertEqual(report.status, "candidate_for_review")
        self.assert_same_results(source, report)

    def test_global_declaration_is_refused(self):
        # Reading count first is already refused as ambiguous (PLAN003);
        # writing it before the call reaches the PLAN008 check.
        source = ("count = 0\ndef bump():\n    global count\n"
                  "    count += 1\n    return count\n"
                  "count = 5\nnext_value = bump()\n")
        report = self.plan(source, 6, 7)
        self.assertEqual(set(self.codes(report)), {"PLAN008"})
        self.assertTrue(any("global count" in item.message
                            for item in report.diagnostics))

    def test_dynamic_namespace_in_module_code_blocks_calls_only(self):
        # Prefix reads become ambiguous (PLAN003), so these regions read
        # nothing from the prefix.
        source = ("def peek():\n    return globals()['x']\n"
                  "y = 1\nz = (y, 2)[0]\n")
        self.assertEqual(self.plan(source, 3, 3).status,
                         "candidate_for_review")
        report = self.plan(source, 3, 4)
        self.assertEqual(self.codes(report), ["PLAN008"])
        self.assertIn("dynamic namespace", report.diagnostics[0].message)

    def test_lazy_generator_and_method_reads_are_seen(self):
        for prefix in ("gen = (v * rate for v in [1, 2])\n",
                       "class Box:\n    def get(self):\n"
                       "        return rate\ngen = [Box().get()]\n"):
            with self.subTest(prefix=prefix):
                source = "rate = 1\n" + prefix + "rate = 2\ntotal = sum(gen)\n"
                start_int = source.count("\n") - 1
                report = self.plan(source, start_int, start_int + 1)
                self.assertIn("PLAN008", self.codes(report))

    def test_operators_without_module_code_stay_candidates(self):
        report = self.plan("base = 2\nfirst = base + 1\nlast = first * 2\n",
                           2, 3)
        self.assertEqual(report.status, "candidate_for_review")


class CallSnippetTests(unittest.TestCase):
    def test_leading_imports_and_definitions_are_setup(self):
        source = ("import math\n\ndef half(value):\n    return value / 2\n\n"
                  "radius=4.0\narea = math.pi * radius ** 2\n"
                  "half_area = half(area)\n")
        report = plan_snippet_report(source)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.plan.start_line, 7)
        self.assertIn("    half_area = half(area)\n", report.function_preview)
        self.assertEqual([item.name for item in report.plan.inputs],
                         ["math", "radius", "half"])

    def test_wrapped_calls_use_conventional_spacing(self):
        source = ("import math\nfirst_measurement=1.5\n"
                  "second_measurement=2.5\n"
                  "combined_measurement = math.hypot(first_measurement, "
                  "second_measurement) + round(first_measurement * "
                  "second_measurement, ndigits=2)\n")
        report = plan_snippet_report(source,
                                     SnippetContext(line_length=60))
        self.assertEqual(report.status, "candidate_for_review")
        preview = report.function_preview
        self.assertIn("math.hypot(", preview)
        self.assertIn("ndigits=2", preview)
        self.assertNotIn(" . ", preview)
        self.assertLessEqual(max(map(len, preview.splitlines())), 60)
        original, extracted = {}, {}
        exec(source, original)
        exec("".join(source.splitlines(True)[:3]), extracted)
        exec(preview, extracted)
        exec(report.caller_preview, extracted)
        self.assertEqual(original["combined_measurement"],
                         extracted["combined_measurement"])
