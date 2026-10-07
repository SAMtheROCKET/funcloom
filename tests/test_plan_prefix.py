"""Regressions for the resolution-gated prefix introduced in 0.4.0a0."""

from pathlib import Path
import tempfile
import unittest

from funcloom import plan_extraction_report

SCRIPT_SOURCE = '''"""Synthetic script with helpers before the calculation."""

import math


def rounded_amount(amount):
    return round(amount, 2)


counts = []
for index in range(3):
    counts.append(index)
base_amount = rounded_amount(120.456) + len(counts)
tax_rate = 0.1
if math.isfinite(base_amount):
    status = "ok"
tax_amount = base_amount * tax_rate
total_amount = base_amount + tax_amount
'''


class PrefixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "script.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(
            self.source_path, start, end, "calculate_result_tuple",
        )
        self.assertEqual(self.source_path.read_bytes(), source.encode("utf-8"))
        self.assertFalse(report.can_apply)
        self.assertFalse(report.behavior_verified)
        return report

    def assert_same_results(self, source: str, report) -> None:
        # Execute only these test-authored fixtures, never target code.
        original, extracted = {}, {}
        exec(source, original)
        prefix = "".join(source.splitlines(True)[:report.start_line - 1])
        exec(prefix, extracted)
        exec(report.function_preview, extracted)
        exec(report.caller_preview, extracted)
        for item in report.outputs:
            self.assertEqual(original[item.name], extracted[item.name])

    def test_realistic_prefix_yields_equivalent_candidate(self):
        report = self.plan(SCRIPT_SOURCE, 17, 18)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs],
                         ["base_amount", "tax_rate"])
        self.assertEqual({item.name: item.status
                          for item in report.name_resolutions}, {
            "base_amount": "direct", "tax_rate": "direct",
            "tax_amount": "selection_local",
        })
        self.assert_same_results(SCRIPT_SOURCE, report)

    def test_prefix_effects_are_still_reported(self):
        report = self.plan(SCRIPT_SOURCE, 17, 18)
        kinds = {item.kind for item in report.effects
                 if item.region == "prefix"}
        self.assertTrue({"call", "control_flow", "scope_boundary",
                         "import"} <= kinds)

    def test_conditionally_rebound_input_is_passed_in(self):
        # M2b.7: bound on every path, so the caller passes its value.
        for condition in ("math.isfinite", "math.isnan"):
            with self.subTest(condition=condition):
                source = SCRIPT_SOURCE.replace(
                    '    status = "ok"', "    tax_rate = 0.2").replace(
                    "math.isfinite", condition)
                report = self.plan(source, 17, 18)
                self.assertEqual(report.status, "candidate_for_review")
                statuses = {item.name: item.status
                            for item in report.name_resolutions}
                self.assertEqual(statuses["tax_rate"], "ambiguous")
                self.assertTrue(any("'tax_rate' may be set by several"
                                    in item for item in report.assumptions))
                self.assert_same_results(source, report)

    def test_rebinding_loop_target_is_passed_in(self):
        source = "x = 0\nfor x in range(3):\n    pass\nresult = x * 2\n"
        report = self.plan(source, 4, 4)
        self.assertEqual(report.status, "candidate_for_review")
        self.assert_same_results(source, report)

    def test_conditional_deletion_stays_refused(self):
        source = "x = 1\nflag = False\nif flag:\n    del x\nresult = x\n"
        report = self.plan(source, 5, 5)
        self.assertEqual(report.diagnostics[-1].code, "PLAN003")
        self.assertIn("possibly_unbound", report.diagnostics[-1].message)

    def test_function_that_rebinds_input_makes_it_ambiguous(self):
        source = ("rate = 0.1\ndef change():\n    global rate\n"
                  "    rate = 0.2\nchange()\nresult = rate * 2\n")
        report = self.plan(source, 6, 6)
        self.assertEqual(report.diagnostics[-1].code, "PLAN003")
        self.assertIn("ambiguous", report.diagnostics[-1].message)

    def test_lambda_reading_a_name_rebound_later_is_refused(self):
        source = ("import math\nbase = 2\n"
                  "result = (lambda: base)() + base\nbase = 3\n")
        report = self.plan(source, 3, 3)
        self.assertIn("PLAN010", [item.code for item in report.diagnostics])

    def test_annotation_evidence_only_from_top_level_declarations(self):
        source = ("base: float = 2\nif flag:\n    other: int = 1\n"
                  "result = base + 1\n")
        report = self.plan(source, 4, 4)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual((report.inputs[0].annotation,
                          report.inputs[0].type_evidence),
                         ("float", "declared_unverified"))
