"""Behavior and refusal regressions for contextual snippet drafts."""

import ast
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from funcloom import RuleProfile, SnippetContext, plan_snippet_report
from funcloom.snippet_context import load_snippet_context
from funcloom.snippet_preview import rename_source_tokens_str

SOURCE = (
    "base_amount=120\ntax_rate= 0.1\n\n"
    "tax_amount = base_amount * tax_rate\n"
    "total_amount = base_amount + tax_amount\n"
)


class SnippetTests(unittest.TestCase):
    def test_no_context_proposes_inputs_names_and_numeric_evidence(self):
        report = plan_snippet_report(SOURCE)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.context_mode, "none")
        self.assertEqual(report.source.text, SOURCE)
        self.assertEqual(report.source_sha256, sha256(SOURCE.encode()).hexdigest())
        self.assertEqual([v.proposed_name for v in report.values], [
            "base_amount_int", "tax_rate_float", "tax_amount_float",
            "total_amount_float",
        ])
        self.assertTrue(all("unverified" in v.type_evidence
                            for v in report.values))
        self.assertIn("'tuple[float, float]'", report.function_preview)
        self.assertFalse(report.can_apply)
        self.assertFalse(report.source_rewriting)
        self.assertFalse(report.behavior_verified)

    def test_small_context_produces_requested_contract_without_casting(self):
        context = SnippetContext(
            project_context="Rates are fractions; preserve arithmetic.",
            function_name="calculate_tax_totals_tuple",
            summary="Calculate tax and the total amount including tax.",
            input_types={"base_amount": "float", "tax_rate": "float"},
            descriptions={"base_amount": "Amount before tax.",
                          "tax_rate": "Fractional rate; 0.1 means ten percent."},
        )
        report = plan_snippet_report(SOURCE, context)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.values[0].annotation, "float")
        self.assertEqual(report.values[0].type_evidence,
                         "context_declared_unverified")
        self.assertIn("Amount before tax.", report.function_preview)
        self.assertIn("base_amount_float: 'float'", report.function_preview)
        self.assertNotIn("float(base_amount)", report.function_preview)
        self.assertIn("base_amount,", report.caller_preview)
        self.assertIn("tax_amount,", report.caller_preview)
        self.assertIn("Use the selected source expressions.",
                      report.function_preview)

    def test_name_and_literal_preferences_are_not_project_context(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(function_name="calculate_totals"),
        )
        self.assertEqual(report.context_mode, "none")

    def test_all_literals_asks_focused_question_then_fixed_policy_works(self):
        report = plan_snippet_report("amount=120\nrate=0.1\n")
        self.assertEqual(report.status, "needs_context")
        self.assertEqual(report.questions[0].code, "SNIP001")
        self.assertIsNone(report.function_preview)
        fixed = plan_snippet_report(
            "amount=120\nrate=0.1\n", SnippetContext(literal_policy="fixed"),
        )
        self.assertEqual(fixed.status, "candidate_for_review")
        self.assertEqual(fixed.plan.inputs, [])
        self.assertIn("amount_int=120", fixed.function_preview)

    def test_fixed_policy_keeps_every_original_assignment(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(literal_policy="fixed"),
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.plan.inputs, [])
        self.assertEqual(len(report.plan.outputs), 4)

    def test_unknown_types_are_questions_not_fabricated_annotations(self):
        report = plan_snippet_report("label='hello'\nresult=label + '!'\n")
        self.assertEqual(report.status, "candidate_for_review")
        self.assertTrue(all(v.annotation is None for v in report.values))
        self.assertTrue(report.questions)
        self.assertNotIn(" -> ", report.function_preview)
        self.assertIn("result=label + '!'", report.function_preview)

    def test_division_and_power_have_distinct_type_evidence(self):
        division = plan_snippet_report("numerator=1\nratio=numerator / 2\n")
        self.assertEqual(division.values[-1].annotation, "float")
        power = plan_snippet_report("base=2\nresult=base ** -1\n")
        self.assertIsNone(power.values[-1].annotation)

    def test_reassignment_does_not_give_a_misleading_dtype_suffix(self):
        report = plan_snippet_report("amount=1\namount=amount / 2\n")
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([v.proposed_name for v in report.values],
                         ["amount", "amount"])
        self.assertEqual([v.annotation for v in report.values], ["int", "float"])

    def test_name_proposals_are_local_and_collisions_refused(self):
        report = plan_snippet_report(
            "amount=2\namount_int=3\nresult=amount+amount_int\n",
        )
        self.assertEqual(report.status, "refused")
        self.assertEqual(report.diagnostics[-1].code, "SNIP003")
        self.assertIsNone(report.function_preview)
        resolved = plan_snippet_report(
            "amount=2\namount_int=3\nresult=amount+amount_int\n",
            SnippetContext(names={"amount_int": "adjustment"}),
        )
        self.assertEqual(resolved.status, "candidate_for_review")
        self.assertIn("adjustment_int", resolved.function_preview)
        self.assertIn("amount_int,", resolved.caller_preview)

    def test_context_cannot_override_unsupported_mutation_or_calls(self):
        for source in ("amount=2\ndel amount\n",
                       "amount=2\nresult=[(w := amount)]\n"):
            report = plan_snippet_report(
                source, SnippetContext(project_context="This is safe."),
            )
            self.assertEqual(report.status, "refused")
            self.assertIsNone(report.function_preview)
            self.assertIn("PLAN002", [d.code for d in report.diagnostics])

    def test_unknown_inputs_are_not_created_from_context(self):
        report = plan_snippet_report(
            "result=external + 1\n",
            SnippetContext(input_types={"external": "float"}),
        )
        self.assertEqual(report.status, "refused")
        self.assertIn("PLAN003", [d.code for d in report.diagnostics])

    def test_context_type_expressions_are_never_evaluated(self):
        for context in ({}, False, ""):
            with self.assertRaises(ValueError):
                plan_snippet_report(SOURCE, context)
        with self.assertRaises(ValueError):
            plan_snippet_report(SOURCE, SnippetContext(
                input_types={"base_amount": "__import__('os').getcwd()"},
            ))

    def test_context_key_misspellings_are_explicit_failures(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(input_types={"base_amout": "float"}),
        )
        self.assertEqual(report.status, "refused")
        self.assertIn("actual extracted inputs", report.diagnostics[-1].message)

    def test_docstring_quotes_backslashes_and_prose_cannot_inject_code(self):
        summary = 'Calculate results. """\nraise RuntimeError("injected")\n#'
        report = plan_snippet_report(
            SOURCE, SnippetContext(summary=summary,
                                   project_context="Path C:\\new\\test."),
        )
        self.assertEqual(report.status, "candidate_for_review")
        tree = ast.parse(report.function_preview)
        self.assertEqual(len(tree.body), 1)
        self.assertIn("raise RuntimeError", ast.get_docstring(tree.body[0]))
        self.assertFalse(any(isinstance(n, ast.Raise) for n in ast.walk(tree)))

    def test_renaming_preserves_comments_strings_unicode_and_crlf(self):
        source = (
            "\u00e9=2\r\n# \u00e9 remains here\r\n"
            "result=\u00e9+1  # result is original text\r\n"
        )
        report = plan_snippet_report(source)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.source.text, source)
        self.assertIn("# \u00e9 remains here\r\n", report.function_preview)
        self.assertIn("result_int=\u00e9_int+1", report.function_preview)
        self.assertIn("# result is original text", report.function_preview)
        changed = rename_source_tokens_str("value='value' # value\n", {"value": "item"})
        self.assertEqual(changed, "item='value' # value\n")

    def test_parse_and_contextual_compile_failures_are_not_candidates(self):
        for source in ("return 2\n", "%time result = 1\n", "result = (\n"):
            report = plan_snippet_report(source)
            self.assertEqual(report.status, "refused")
            self.assertEqual(report.diagnostics[0].code, "PARSE001")
            self.assertIsNone(report.function_preview)

    def test_limits_and_repetition_remain_explicit(self):
        report = plan_snippet_report(SOURCE, profile_info=replace(
            RuleProfile(), max_file_bytes=8,
        ))
        self.assertEqual(report.status, "refused")
        long_context = SnippetContext(project_context="description " * 165)
        report = plan_snippet_report(SOURCE, long_context)
        self.assertEqual(report.status, "refused")
        self.assertIsNone(report.function_preview)
        self.assertEqual(asdict(plan_snippet_report(SOURCE)),
                         asdict(plan_snippet_report(SOURCE)))

    def test_function_name_collisions_are_refused(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(function_name="total_amount"),
        )
        self.assertEqual(report.status, "refused")
        self.assertIn("PLAN004", [d.code for d in report.diagnostics])

    def test_empty_or_comments_only_source_needs_a_calculation(self):
        for source in ("", "# example\n"):
            report = plan_snippet_report(source)
            self.assertEqual(report.status, "needs_context")
            self.assertIsNone(report.function_preview)
            self.assertEqual(report.questions[0].code, "SNIPEMPTY")

    def test_trusted_numeric_fixture_matches_original_and_preserves_names(self):
        # Only explicitly authored numeric fixtures are executed here.
        for amount in (-3, 0, 120, 2.5):
            source = SOURCE.replace("base_amount=120", f"base_amount={amount}")
            report = plan_snippet_report(source)
            original, generated = {}, {}
            exec(source, original)
            exec(report.function_preview, generated)
            prefix = "".join(source.splitlines(keepends=True)[
                :report.plan.start_line - 1
            ])
            exec(prefix + report.caller_preview, generated)
            for name in ("base_amount", "tax_rate", "tax_amount", "total_amount"):
                self.assertEqual(original[name], generated[name])
            self.assertFalse(report.behavior_verified)

    def test_context_toml_is_strict_and_uses_literal_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.toml"
            path.write_text(
                '[snippet]\nsummary="Calculate values."\n'
                '[input_types]\nbase_amount="float"\n',
            )
            context = load_snippet_context(path)
            self.assertEqual(context.input_types, {"base_amount": "float"})
            for text in ('[unknown]\nx=1\n', '[snippet]\ninput_types={}\n',
                         '[input_types]\nbase_amount="Decimal"\n'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_snippet_context(path)
