"""Regressions for long-line wrapping and user-chosen line lengths."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import tokenize
import unittest
from unittest.mock import patch

from funcloom import SnippetContext, plan_snippet_report
from funcloom.cli import main
from funcloom.snippet_context import load_snippet_context

LONG_SOURCE = (
    "gross_revenue_amount=1200\nrefund_amount=150\ndiscount_rate=0.05\n"
    "# " + "a long explanatory comment about revenue " * 3 + "\n"
    "net_revenue_amount = gross_revenue_amount - refund_amount - "
    "gross_revenue_amount * discount_rate + refund_amount * discount_rate"
    "  # " + "trailing detail " * 5 + "\n"
)


def comment_words(text: str) -> list[str]:
    """Return comment words in order, ignoring how comments were wrapped."""
    return [word for token in tokenize.generate_tokens(
        StringIO(text).readline) if token.type == tokenize.COMMENT
        for word in token.string.lstrip("#").split()]


class SnippetWidthTests(unittest.TestCase):
    def draft(self, source: str, context=None):
        report = plan_snippet_report(source, context)
        self.assertFalse(report.can_apply)
        return report

    def assert_same_results(self, source: str, report) -> None:
        # Execute only test-authored fixtures, never customer snippets.
        original, extracted = {}, {}
        exec(source, original)
        lines = source.replace("\r\n", "\n").replace("\r", "\n")
        exec("".join(lines.splitlines(True)[:report.plan.start_line - 1]),
             extracted)
        exec(report.function_preview, extracted)
        exec(report.caller_preview, extracted)
        for item in report.plan.outputs:
            self.assertEqual(original[item.name], extracted[item.name])

    def widest(self, report) -> int:
        return max(map(len, (report.function_preview
                             + report.caller_preview).splitlines()))

    def test_long_source_line_is_wrapped_to_default_79(self):
        report = self.draft(LONG_SOURCE)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertLessEqual(self.widest(report), 79)
        self.assert_same_results(LONG_SOURCE, report)
        self.assertEqual(report.plan.status, "candidate_for_review")
        self.assertTrue(any("wrapped" in item for item in report.assumptions))

    def test_comments_are_wrapped_with_every_word_kept(self):
        report = self.draft(LONG_SOURCE)
        self.assertEqual(comment_words(report.function_preview),
                         comment_words(LONG_SOURCE))

    def test_user_widths_are_enforced(self):
        for width in (60, 79, 100, 120):
            with self.subTest(width=width):
                report = self.draft(LONG_SOURCE,
                                    SnippetContext(line_length=width))
                self.assertEqual(report.status, "candidate_for_review")
                self.assertLessEqual(self.widest(report), width)
                self.assert_same_results(LONG_SOURCE, report)

    def test_invalid_widths_are_rejected(self):
        for value in (39, 201, True, "80", 79.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.draft("x=1\ny=x\n", SnippetContext(line_length=value))

    def test_indivisible_token_refusal_names_width(self):
        report = self.draft("x=1\ny = x + " + "1" * 90 + "\n")
        self.assertEqual(report.status, "refused")
        self.assertIsNone(report.function_preview)
        self.assertIn("the cap is 79", report.diagnostics[-1].message)

    def test_lone_carriage_returns_rename_every_line(self):
        source = "b=3.0\rc=4.0\ra=b*c\rtotal=a+(a/c)\r"
        report = self.draft(source,
                            SnippetContext(naming_mode="mathematical"))
        self.assertEqual(report.status, "candidate_for_review")
        self.assertNotIn("total", report.function_preview.split("return")[1])
        self.assert_same_results(source, report)

    def test_keyword_name_mapping_gets_a_specific_error(self):
        with self.assertRaisesRegex(ValueError, "names value for 'a'.*class"):
            self.draft("a=1\nb=a+1\n", SnippetContext(names={"a": "class"}))
        with self.assertRaisesRegex(ValueError, "descriptions key 'def'"):
            self.draft("a=1\nb=a+1\n",
                       SnippetContext(descriptions={"def": "x"}))
        report = self.draft("a=1\nb=a+1\n",
                            SnippetContext(names={"a": "match"}))
        self.assertEqual(report.status, "candidate_for_review")


class LineLengthEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source_path = self.root / "source.py"
        self.source_path.write_text(LONG_SOURCE)

    def command(self, arguments, answers=None):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors), patch(
            "sys.stdin.isatty", return_value=True,
        ), patch("funcloom.snippet_interactive.read_answer_str",
                 side_effect=answers or AssertionError("Prompted")):
            status = main(arguments)
        return status, output.getvalue(), errors.getvalue()

    def test_toml_setting_and_cli_override(self):
        context_path = self.root / "context.toml"
        context_path.write_text("[snippet]\nline_length = 100\n")
        self.assertEqual(load_snippet_context(context_path).line_length, 100)
        base = ["snippet", str(self.source_path), "--format", "json",
                "--context", str(context_path)]
        for extra, expected in (([], 100), (["--line-length", "60"], 60)):
            status, output, errors = self.command(base + extra)
            self.assertEqual(status, 0, errors)
            report = json.loads(output)
            self.assertEqual(report["context"]["line_length"], expected)
            self.assertLessEqual(max(map(
                len, report["function_preview"].splitlines())), expected)

    def test_wizard_asks_and_repeats_invalid_line_length(self):
        status, output, errors = self.command(
            ["snippet", str(self.source_path), "--interactive", "--format",
             "json"], ["1", "abc", "30", "72"],
        )
        self.assertEqual(status, 0, errors)
        self.assertEqual(json.loads(output)["context"]["line_length"], 72)
        self.assertIn("from 40 to 200", errors)

    def test_blank_wizard_answer_keeps_default(self):
        status, output, errors = self.command(
            ["snippet", str(self.source_path), "--interactive", "--format",
             "json"], ["1", ""],
        )
        self.assertEqual(status, 0, errors)
        self.assertIsNone(json.loads(output)["context"]["line_length"])

    def test_check_and_plan_accept_line_length(self):
        long_path = self.root / "long.py"
        long_path.write_text("value = 1  # " + "x" * 80 + "\n")
        self.assertEqual(self.command(["check", str(long_path)])[0], 1)
        self.assertEqual(self.command(
            ["check", str(long_path), "--line-length", "100"])[0], 0)
        self.assertEqual(self.command(
            ["check", str(long_path), "--line-length", "30"])[0], 2)
        status, _, errors = self.command(
            ["plan", str(long_path), "--start-line", "1", "--end-line", "1",
             "--name", "make_value", "--line-length", "120"])
        self.assertEqual(status, 0, errors)


class ReviewFindingTests(unittest.TestCase):
    """Reproductions from the 0.3.2a0 review report."""

    DIRECTIVE_SOURCE = (
        "x=1\ny=x+1  # type: ignore[assignment, operator, attr-defined, "
        "return-value, arg-type, call-overload]\n"
    )

    def test_long_directive_comment_is_refused_not_split(self):
        report = plan_snippet_report(self.DIRECTIVE_SOURCE,
                                     SnippetContext(line_length=60))
        self.assertEqual(report.status, "refused")
        self.assertIsNone(report.function_preview)
        diagnostic = report.diagnostics[-1]
        self.assertEqual((diagnostic.code, diagnostic.line), ("SNIP004", 2))
        self.assertIn("type: ignore", diagnostic.message)

    def test_directive_that_fits_is_kept_verbatim_on_its_line(self):
        report = plan_snippet_report(self.DIRECTIVE_SOURCE,
                                     SnippetContext(line_length=120))
        self.assertEqual(report.status, "candidate_for_review")
        directive = self.DIRECTIVE_SOURCE.split("  ", 1)[1].strip()
        self.assertIn("y_int=x_int+1  " + directive,
                      report.function_preview)

    def test_standalone_directives_refused_but_prose_wraps(self):
        for directive in ("# noqa: E501", "# pragma: no cover",
                          "# fmt: off", "# pylint: disable=invalid-name"):
            with self.subTest(directive=directive):
                source = f"x=1\n{directive} " + "word " * 20 + "\ny=x\n"
                report = plan_snippet_report(source)
                self.assertEqual(report.diagnostics[-1].code, "SNIP004")
                self.assertEqual(report.diagnostics[-1].line, 2)
        source = "x=1\n# pragmatic " + "word " * 20 + "\ny=x\n"
        report = plan_snippet_report(source)
        self.assertEqual(report.status, "candidate_for_review")

    def test_profile_line_length_uses_the_shared_range(self):
        from dataclasses import replace
        from funcloom.config import RuleProfile, load_profile
        from funcloom.snippets import plan_snippet_file_report
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.py"
            source_path.write_text("x=1\ny=x+1\n")
            for width in (10, 39, 201):
                config_path = root / f"profile{width}.toml"
                config_path.write_text(f"[profile]\nline_length = {width}\n")
                with self.subTest(width=width), self.assertRaisesRegex(
                    ValueError, "from 40 to 200",
                ):
                    load_profile(config_path)
                with self.subTest(width=width), self.assertRaisesRegex(
                    ValueError, "from 40 to 200",
                ):
                    plan_snippet_file_report(source_path, profile_info=replace(
                        RuleProfile(), line_length=width))
