"""Regressions for definitions, lambdas and generators in regions (M2b.10)."""

from pathlib import Path
import tempfile
import unittest

from funcloom import plan_extraction_report


class DefinitionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "script.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(self.source_path, start, end,
                                        "build_tuple")
        self.assertEqual(self.source_path.read_bytes(),
                         source.encode("utf-8"))
        self.assertFalse(report.can_apply)
        return report

    def codes(self, report) -> list[str]:
        return [item.code for item in report.diagnostics]

    def run_both(self, source: str, report) -> tuple[dict, dict]:
        # Execute only these test-authored fixtures, never target code.
        self.assertEqual(report.status, "candidate_for_review",
                         [item.message for item in report.diagnostics])
        lines = source.splitlines(True)
        original, extracted = {}, {}
        exec(source, original)
        exec("".join(lines[:report.start_line - 1]), extracted)
        exec(report.function_preview, extracted)
        exec(report.caller_preview, extracted)
        exec("".join(lines[report.end_line:]), extracted)
        return original, extracted

    def test_helper_function_and_its_later_calls(self):
        source = ("rate = 0.2\nprices = [10, 20]\n"
                  "def taxed(price, extra=1):\n"
                  "    return price * (1 + rate) + extra\n"
                  "totals = [taxed(price) for price in prices]\n"
                  "later = taxed(100)\n")
        report = self.plan(source, 3, 5)
        self.assertIn("taxed", [item.name for item in report.outputs])
        self.assertTrue(any("qualified names change" in item
                            for item in report.assumptions))
        original, extracted = self.run_both(source, report)
        self.assertEqual(original["totals"], extracted["totals"])
        self.assertEqual(original["later"], extracted["later"])

    def test_recursive_function(self):
        source = ("def fact(n):\n    return 1 if n < 2 else n * fact(n - 1)\n"
                  "value = fact(5)\nagain = fact(4)\n")
        report = self.plan(source, 1, 3)
        original, extracted = self.run_both(source, report)
        self.assertEqual(original["value"], extracted["value"])
        self.assertEqual(original["again"], extracted["again"])

    def test_lambda_and_generator_reading_region_names(self):
        source = ("scale = 3\nvalues = [1, 2, 3]\n"
                  "triple = lambda v: v * scale\n"
                  "lazy = (triple(v) for v in values)\n"
                  "result = list(lazy)\n")
        report = self.plan(source, 3, 5)
        original, extracted = self.run_both(source, report)
        self.assertEqual(original["result"], extracted["result"])

    def test_class_with_method_and_base(self):
        source = ("base_rate = 2\nclass Meter:\n    unit = 'kWh'\n"
                  "    def cost(self, used):\n"
                  "        return used * base_rate\n"
                  "bill = Meter().cost(5)\n")
        report = self.plan(source, 2, 6)
        original, extracted = self.run_both(source, report)
        self.assertEqual(original["bill"], extracted["bill"])

    def test_read_name_rebound_after_the_region_is_refused(self):
        source = ("rate = 0.2\ndef taxed(price):\n"
                  "    return price * (1 + rate)\n"
                  "rate = 0.5\nfinal = taxed(10)\n")
        report = self.plan(source, 1, 3)
        self.assertEqual(self.codes(report), ["PLAN010"])

    def test_global_inside_a_definition_is_refused(self):
        source = ("count = 0\ndef bump():\n    global count\n"
                  "    count += 1\n")
        report = self.plan(source, 2, 4)
        self.assertEqual(self.codes(report), ["PLAN002"])

    def test_pure_global_reads_need_no_check(self):
        source = ("def area(r):\n    return 3.14 * r * r\n"
                  "size = area(2)\nr = 9\n")
        report = self.plan(source, 1, 3)
        self.assertEqual(report.status, "candidate_for_review",
                         self.codes(report))


if __name__ == "__main__":
    unittest.main()
