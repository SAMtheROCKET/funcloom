"""Regressions for if/for/while in selected regions (M2b.8)."""

from pathlib import Path
import tempfile
import unittest

from funcloom import plan_extraction_report


class ControlFlowPlanTests(unittest.TestCase):
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

    def codes(self, report) -> list[str]:
        return [item.code for item in report.diagnostics]

    def assert_same(self, source: str, report, names) -> None:
        # Execute only these test-authored fixtures, never target code.
        self.assertEqual(report.status, "candidate_for_review",
                         [item.message for item in report.diagnostics])
        lines = source.splitlines(True)
        original, extracted = {}, {}
        exec("".join(lines[:report.end_line]), original)
        exec("".join(lines[:report.start_line - 1]), extracted)
        exec(report.function_preview, extracted)
        exec(report.caller_preview, extracted)
        for name in names:
            self.assertEqual(original.get(name, "<unset>"),
                             extracted.get(name, "<unset>"), name)

    def test_loop_accumulates_and_drops_its_unread_variable(self):
        source = ("values = [3, 1, 4]\ntotal = 0\nfor value in values:\n"
                  "    total += value\n")
        report = self.plan(source, 3, 4)
        self.assertEqual([item.name for item in report.inputs],
                         ["values", "total"])
        self.assertEqual([item.name for item in report.outputs], ["total"])
        self.assertTrue(any("'value' is set only on some paths" in item
                            for item in report.assumptions))
        self.assert_same(source, report, ["total"])

    def test_loop_variable_read_later_is_refused(self):
        source = ("values = [3, 1, 4]\nfor value in values:\n"
                  "    pass\nprint(value)\n")
        report = self.plan(source, 2, 3)
        self.assertEqual(self.codes(report), ["PLAN009"])

    def test_if_else_assigning_both_branches_returns_the_name(self):
        for flag in ("True", "False"):
            with self.subTest(flag=flag):
                source = (f"flag = {flag}\nif flag:\n    label = 'yes'\n"
                          "else:\n    label = 'no'\n")
                report = self.plan(source, 2, 5)
                self.assertEqual([item.name for item in report.outputs],
                                 ["label"])
                self.assert_same(source, report, ["label"])

    def test_one_branch_keeps_the_earlier_value(self):
        for flag in ("True", "False"):
            with self.subTest(flag=flag):
                source = (f"flag = {flag}\nlabel = 'before'\nif flag:\n"
                          "    label = 'after'\n")
                report = self.plan(source, 3, 4)
                self.assertIn("label",
                              [item.name for item in report.inputs])
                self.assertTrue(any("'label' is passed in" in item
                                    for item in report.assumptions))
                self.assert_same(source, report, ["label"])

    def test_while_with_branches_break_and_continue(self):
        source = ("n = 27\nsteps = 0\nwhile n > 1:\n    steps += 1\n"
                  "    if steps > 500:\n        break\n    if n % 2:\n"
                  "        n = 3 * n + 1\n        continue\n"
                  "    n = n // 2\n")
        report = self.plan(source, 3, 10)
        self.assertEqual(sorted(item.name for item in report.outputs),
                         ["n", "steps"])
        self.assert_same(source, report, ["n", "steps"])

    def test_nested_loops_with_comprehension_and_for_else(self):
        source = ("grid = [[1, 2], [3, 4]]\nfound = None\n"
                  "for row in grid:\n"
                  "    doubled = [cell * 2 for cell in row]\n"
                  "    for cell in doubled:\n        if cell > 5:\n"
                  "            found = cell\n            break\n"
                  "else:\n    found = 0\n")
        report = self.plan(source, 3, 10)
        self.assert_same(source, report, ["found"])

    def test_read_after_a_one_branch_assignment_is_refused(self):
        source = "flag = True\nif flag:\n    x = 1\ny = x\n"
        report = self.plan(source, 2, 4)
        self.assertIn("PLAN003", self.codes(report))

    def test_same_branch_reads_are_local(self):
        source = ("flag = True\nb = 0\nif flag:\n    a = 2\n"
                  "    b = a * 3\n")
        report = self.plan(source, 3, 5)
        self.assertNotIn("a", [item.name for item in report.inputs])
        self.assert_same(source, report, ["b"])

    def test_loop_calling_module_code_that_reads_a_region_write(self):
        source = ("limit = 1\ndef over(value):\n    return value > limit\n"
                  "limit = 2\nhits = 0\nfor value in [1, 2, 3]:\n"
                  "    if over(value):\n        hits += 1\n")
        report = self.plan(source, 4, 8)
        self.assertIn("PLAN008", self.codes(report))

    def test_try_with_match_and_del_stay_refused(self):
        for body in ("try:\n    x = 1\nexcept ValueError:\n    x = 2\n",
                     "match 1:\n    case _:\n        x = 1\n",
                     "if True:\n    del flag\n"):
            with self.subTest(body=body):
                source = "flag = True\n" + body
                report = self.plan(source, 2, 1 + body.count("\n"))
                self.assertIn("PLAN002", self.codes(report))


if __name__ == "__main__":
    unittest.main()
