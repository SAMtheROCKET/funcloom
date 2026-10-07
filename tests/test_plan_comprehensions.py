"""Regressions for comprehensions in selected regions (M2b.6)."""

from pathlib import Path
import tempfile
import unittest

from funcloom import plan_extraction_report

REPORT_SCRIPT = '''"""Synthetic sales summary built with comprehensions."""

x = 100
rate = 0.2
values = [3, 1, 4, 1, 5]
pairs = [("north", 2), ("south", 3), ("north", 4)]
grid = [[1, 2], [3, 4]]
squares = [x * x for x in values]
taxed = {value: value * (1 + rate) for value in values if value > x / 100}
regions = {region for region, _ in pairs}
flat = [cell + rate for row in grid for cell in row]
nested = [[cell * x for cell in row] for row in grid]
scale = 3
scaled = [value * scale for value in values]
first = [x for x in values][0]
'''


class ComprehensionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "script.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(self.source_path, start, end,
                                        "summarize_tuple")
        self.assertEqual(self.source_path.read_bytes(),
                         source.encode("utf-8"))
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

    def codes(self, report) -> list[str]:
        return [item.code for item in report.diagnostics]

    def test_comprehensions_match_the_original_results(self):
        report = self.plan(REPORT_SCRIPT, 8, 15)
        self.assertEqual(report.status, "candidate_for_review",
                         self.codes(report))
        self.assertEqual([item.name for item in report.inputs],
                         ["values", "rate", "x", "pairs", "grid"])
        self.assertEqual(
            [item.name for item in report.outputs],
            ["squares", "taxed", "regions", "flat", "nested", "scale",
             "scaled", "first"])
        original, extracted = self.run_both(REPORT_SCRIPT, report)
        for item in report.outputs:
            self.assertEqual(original[item.name], extracted[item.name],
                             item.name)
        self.assertEqual(original["x"], extracted["x"])

    def test_iteration_variables_are_never_inputs_or_outputs(self):
        report = self.plan("values = [1, 2]\n"
                           "doubled = [item * 2 for item in values]\n", 2, 2)
        self.assertEqual([item.name for item in report.inputs], ["values"])
        self.assertEqual([item.name for item in report.outputs], ["doubled"])
        resolved = {item.name: item.status
                    for item in report.name_resolutions}
        self.assertEqual(resolved, {"values": "direct"})

    def test_first_iterable_reads_the_enclosing_name(self):
        report = self.plan("item = [1, 2]\nsame = [item for item in item]\n",
                           2, 2)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs], ["item"])
        original, extracted = self.run_both(
            "item = [1, 2]\nsame = [item for item in item]\n", report)
        self.assertEqual(original["same"], extracted["same"])

    def test_selection_local_names_inside_comprehensions(self):
        source = ("values = [1, 2]\nfactor = 3\n"
                  "out = [v * factor for v in values]\n")
        report = self.plan(source, 2, 3)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs], ["values"])
        original, extracted = self.run_both(source, report)
        self.assertEqual(original["out"], extracted["out"])

    def test_unresolved_reads_inside_comprehensions_are_refused(self):
        source = ("import random\nvalues = [1, 2]\n"
                  "if random.random() > 2:\n    limit = 1\n"
                  "kept = [v for v in values if v > limit]\n")
        report = self.plan(source, 5, 5)
        self.assertEqual(report.status, "refused")
        self.assertIn("PLAN003", self.codes(report))
        resolved = {item.name: item.status
                    for item in report.name_resolutions}
        self.assertEqual(resolved["limit"], "possibly_unbound")

    def test_generators_and_lambdas_are_candidates_since_m2b10(self):
        for expression in ("(v for v in values)", "sum(v for v in values)",
                           "[lambda: v for v in values]"):
            with self.subTest(expression=expression):
                report = self.plan(f"values = [1]\nresult = {expression}\n",
                                   2, 2)
                self.assertEqual(report.status, "candidate_for_review",
                                 self.codes(report))

    def test_walrus_stays_refused(self):
        for expression, reason in (
            ("[(w := v) for v in values]", "NamedExpr"),
        ):
            with self.subTest(expression=expression):
                report = self.plan(f"values = [1]\nresult = {expression}\n",
                                   2, 2)
                self.assertEqual(report.status, "refused")
                self.assertIn("PLAN002", self.codes(report))
                self.assertTrue(any(reason in item.message
                                    for item in report.diagnostics))

    def test_module_function_reading_a_region_write_is_refused(self):
        source = ("limit = 1\ndef keep(value):\n    return value > limit\n"
                  "values = [1, 2, 3]\nlimit = 2\n"
                  "kept = [v for v in values if keep(v)]\n")
        report = self.plan(source, 5, 6)
        self.assertIn("PLAN008", self.codes(report))


if __name__ == "__main__":
    unittest.main()
