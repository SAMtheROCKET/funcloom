"""Regressions for try, with, match, raise and assert in regions (M2b.9)."""

from pathlib import Path
import tempfile
import unittest

from funcloom import plan_extraction_report


class BlockPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "script.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(self.source_path, start, end,
                                        "handle_tuple")
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

    def test_try_except_sets_the_name_on_both_paths(self):
        for text in ("'42'", "'x'"):
            with self.subTest(text=text):
                source = (f"text = {text}\ntry:\n    number = int(text)\n"
                          "except ValueError:\n    number = -1\n")
                report = self.plan(source, 2, 5)
                self.assertEqual([item.name for item in report.outputs],
                                 ["number"])
                self.assert_same(source, report, ["number"])

    def test_else_finally_and_exception_name(self):
        for text in ("'7'", "'seven'"):
            with self.subTest(text=text):
                source = (f"text = {text}\ntry:\n    value = int(text)\n"
                          "except ValueError as error:\n"
                          "    message = str(error)\n    value = 0\n"
                          "else:\n    message = 'ok'\nfinally:\n"
                          "    done = True\n")
                report = self.plan(source, 2, 10)
                names = [item.name for item in report.outputs]
                self.assertNotIn("error", names)
                self.assertEqual(sorted(names), ["done", "message", "value"])
                self.assert_same(source, report,
                                 ["value", "message", "done", "error"])

    def test_exception_name_with_a_value_is_refused(self):
        source = ("error = 'kept'\ntry:\n    int('x')\n"
                  "except ValueError as error:\n    pass\n")
        report = self.plan(source, 2, 5)
        self.assertEqual(self.codes(report), ["PLAN009"])

    def test_with_target_and_body(self):
        source = ("import io\nwith io.StringIO('a\\nb') as handle:\n"
                  "    lines = handle.read().splitlines()\n"
                  "count = len(lines)\n")
        report = self.plan(source, 2, 4)
        self.assertTrue(any("not to suppress exceptions" in item
                            for item in report.assumptions))
        self.assert_same(source, report, ["lines", "count"])

    def test_match_with_wildcard_sets_the_name(self):
        for command in ("'start'", "'stop'", "'other'", "[1, 2, 3]"):
            with self.subTest(command=command):
                source = (f"command = {command}\nmatch command:\n"
                          "    case 'start':\n        state = 1\n"
                          "    case 'stop':\n        state = 0\n"
                          "    case [first, *rest]:\n"
                          "        state = first + len(rest)\n"
                          "    case _:\n        state = -1\n")
                report = self.plan(source, 2, 10)
                self.assertEqual([item.name for item in report.outputs],
                                 ["state"])
                self.assert_same(source, report, ["state"])

    def test_match_without_wildcard_needs_an_earlier_value(self):
        source = ("command = 'stop'\nmatch command:\n"
                  "    case 'start':\n        state = 1\nprint(state)\n")
        report = self.plan(source, 2, 4)
        self.assertEqual(self.codes(report), ["PLAN009"])

    def test_raise_and_assert_only_read(self):
        source = ("limit = 5\namount = 3\nassert amount >= 0, 'negative'\n"
                  "if amount > limit:\n    raise ValueError(amount)\n"
                  "rest = limit - amount\n")
        report = self.plan(source, 3, 6)
        self.assertEqual([item.name for item in report.inputs],
                         ["amount", "limit"])
        self.assert_same(source, report, ["rest"])

    def test_iteration_can_run_module_code(self):
        source = ("limit = 1\nclass Box:\n    def __iter__(self):\n"
                  "        return iter([limit])\nbox = Box()\n"
                  "limit = 2\nfor value in box:\n    pass\n")
        report = self.plan(source, 6, 8)
        self.assertIn("PLAN008", self.codes(report))


if __name__ == "__main__":
    unittest.main()
