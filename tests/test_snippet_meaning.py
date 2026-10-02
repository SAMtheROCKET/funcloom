"""Regressions for generic variables, mathematical roles and user meanings."""

import ast
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from funcloom import SnippetContext, plan_snippet_report
from funcloom.cli import main
from funcloom.snippet_context import load_snippet_context

SOURCE = "b=3.0\nc=4.0\na=b*c\ntotal=a+(a/c)\n"


class MathematicalContextTests(unittest.TestCase):
    def test_mathematical_roles_are_neutral_and_source_linked(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(naming_mode="mathematical"),
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([value.proposed_name for value in report.values], [
            "operand_1_float", "operand_2_float",
            "product_value_float", "sum_value_float",
        ])
        self.assertTrue(all(value.name_evidence == "mathematical_role_proposal"
                            for value in report.values))
        self.assertIn("def evaluate_expression_tuple(", report.function_preview)
        self.assertIn("mathematical expressions in source order",
                      report.function_preview)
        self.assertFalse(any(question.code == "SNIPNAME"
                             for question in report.questions))
        self.assertEqual(report.source.text, SOURCE)
        self.assertIn("    b,", report.caller_preview)
        self.assertFalse(report.can_apply)

    def test_source_mode_asks_meaning_without_inventing_it(self):
        report = plan_snippet_report(SOURCE)
        prompts = [item.prompt for item in report.questions
                   if item.code == "SNIPNAME"]
        self.assertEqual(len(prompts), 3)
        self.assertIn("b_float", report.function_preview)
        self.assertNotIn("invoice", report.function_preview)
        self.assertEqual(report.values[0].name_evidence, "source_identifier")

    def test_domain_names_descriptions_and_summary_are_explicit(self):
        context = SnippetContext(
            naming_mode="domain",
            summary="Calculate adjusted shipment mass.",
            function_name="calculate_shipment_mass_tuple",
            names={"b": "unit_mass", "c": "item_count",
                   "a": "shipment_mass", "total": "adjusted_mass"},
            descriptions={"b": "User-declared mass per item in kilograms.",
                          "c": "User-declared item count.",
                          "a": "User-declared shipment mass.",
                          "total": "User-declared adjusted result."},
        )
        report = plan_snippet_report(SOURCE, context)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertIn("unit_mass_float", report.function_preview)
        self.assertIn("mass per item in kilograms", report.function_preview)
        self.assertFalse(any(item.code == "SNIPNAME" for item in report.questions))
        self.assertTrue(all(value.name_evidence == "user_supplied"
                            for value in report.values))
        self.assertEqual(context.names["b"], "unit_mass")

    def test_domain_prose_does_not_automatically_resolve_value_meanings(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(naming_mode="domain",
                                   project_context="An engineering project."),
        )
        self.assertEqual(len([q for q in report.questions
                              if q.code == "SNIPNAME"]), 4)
        self.assertIn("b_float", report.function_preview)

    def test_repeated_math_roles_receive_distinct_local_names(self):
        source = "b=2\nc=4\na=b*c\nd=b*c\ntotal=a+d\n"
        report = plan_snippet_report(
            source, SnippetContext(naming_mode="mathematical"),
        )
        self.assertEqual(report.status, "candidate_for_review")
        names = [item.proposed_name for item in report.values]
        self.assertIn("product_value_int", names)
        self.assertIn("product_value_2_int", names)
        self.assertEqual(len(names), len(set(names)))

    def test_multiple_roles_keep_one_binding_and_preserve_all_assignments(self):
        source = "b=3.0\nc=4.0\na=b*c\na=b/c\ntotal=a+1\n"
        report = plan_snippet_report(
            source, SnippetContext(naming_mode="mathematical"),
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.values[2].proposed_name, "intermediate_value_float")
        self.assertEqual(len([q for q in report.questions
                              if q.code == "SNIPWRITE"]), 1)
        body = ast.parse(report.function_preview).body[0].body
        self.assertEqual(len([n for n in body if isinstance(n, ast.Assign)]), 3)

    def test_input_output_reassignment_keeps_same_symbol(self):
        report = plan_snippet_report(
            "a=2\na=a+1\n", SnippetContext(naming_mode="mathematical"),
        )
        self.assertEqual([v.proposed_name for v in report.values],
                         ["operand_1_int", "operand_1_int"])
        self.assertFalse(any(q.code == "SNIPWRITE" for q in report.questions))

    def test_explicit_names_override_math_roles_and_collisions_still_refuse(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(naming_mode="mathematical",
                                   names={"a": "scaled_operand"}),
        )
        self.assertEqual(report.values[2].proposed_name, "scaled_operand_float")
        self.assertEqual(report.values[2].name_evidence, "user_supplied")
        refused = plan_snippet_report(
            SOURCE, SnippetContext(naming_mode="mathematical",
                                   names={"b": "shared", "c": "shared"}),
        )
        self.assertEqual(refused.status, "refused")
        self.assertIsNone(refused.function_preview)

    def test_non_numeric_types_are_not_invented_by_mathematical_mode(self):
        report = plan_snippet_report(
            "a='hello'\nb=a+'!'\n", SnippetContext(naming_mode="mathematical"),
        )
        self.assertTrue(all(value.annotation is None for value in report.values))
        self.assertTrue(any(q.code == "SNIPTYPE" for q in report.questions))

    def test_calls_request_semantics_without_execution_or_assumed_bindings(self):
        source = "c=3\nb=2\na=99+input(c)\na=b*c\ntotal=log(b)+a+(a/c)\n"
        with patch("builtins.input", side_effect=AssertionError("Executed")):
            report = plan_snippet_report(
                source, SnippetContext(naming_mode="mathematical"),
            )
        self.assertEqual(report.status, "refused")
        self.assertIsNone(report.function_preview)
        prompts = "\n".join(q.prompt for q in report.questions)
        self.assertIn("returns text", prompts)
        self.assertIn("base and valid input", prompts)
        self.assertTrue(any(q.code == "SNIPWRITE" and q.line == 4
                            for q in report.questions))
        self.assertFalse(report.behavior_verified)

    def test_pseudocode_is_a_located_clarification_not_a_repaired_program(self):
        report = plan_snippet_report("b=(extract 2nd decimal of 'a')\n")
        self.assertEqual(report.status, "refused")
        self.assertEqual(report.diagnostics[0].code, "PARSE001")
        self.assertEqual(report.questions[0].code, "SNIPSYNTAX")
        self.assertEqual(report.questions[0].line, 1)
        self.assertIsNone(report.function_preview)

    def test_semantics_questions_do_not_reorder_or_create_inputs(self):
        report = plan_snippet_report(
            "a=b*c\nb=a/100\ntotal=a+b\n",
            SnippetContext(naming_mode="mathematical",
                           input_types={"b": "float", "c": "float"}),
        )
        self.assertEqual(report.status, "refused")
        self.assertIn("PLAN003", [item.code for item in report.diagnostics])

    def test_supported_math_drafts_match_only_trusted_numeric_fixtures(self):
        for value in (2, 3.5, -7):
            source = SOURCE.replace("b=3.0", f"b={value}")
            report = plan_snippet_report(
                source, SnippetContext(naming_mode="mathematical"),
            )
            original, proposed = {}, {}
            exec(source, original)
            exec(report.function_preview, proposed)
            prefix = "".join(source.splitlines(keepends=True)[
                :report.plan.start_line - 1
            ])
            exec(prefix + report.caller_preview, proposed)
            self.assertEqual((proposed["a"], proposed["total"]),
                             (original["a"], original["total"]))
        self.assertEqual(asdict(plan_snippet_report(SOURCE)),
                         asdict(plan_snippet_report(SOURCE)))

    def test_context_toml_and_naming_modes_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.toml"
            path.write_text('[snippet]\nnaming_mode="mathematical"\n')
            self.assertEqual(load_snippet_context(path).naming_mode, "mathematical")
        for value in ("magical", False, []):
            with self.assertRaises(ValueError):
                plan_snippet_report(SOURCE, SnippetContext(naming_mode=value))

    def run_cli(self, arguments, answers=None):
        output, errors = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.py"
            path.write_text(SOURCE)
            with redirect_stdout(output), redirect_stderr(errors), patch(
                "sys.stdin.isatty", return_value=True,
            ), patch("funcloom.snippet_interactive.read_answer_str",
                     side_effect=answers or AssertionError("Prompted")):
                status = main(["snippet", str(path), "--format", "json",
                               *arguments])
        return status, json.loads(output.getvalue()), errors.getvalue()

    def test_cli_and_wizard_offer_pure_mathematical_naming(self):
        status, report, errors = self.run_cli(["--naming", "mathematical"])
        self.assertEqual(status, 0, errors)
        self.assertEqual(report["context"]["naming_mode"], "mathematical")
        status, report, errors = self.run_cli(
            ["--interactive"], ["3", "", "", "", "", ""],
        )
        self.assertEqual(status, 0, errors)
        self.assertIn("operand_1_float", report["function_preview"])

    def test_wizard_collects_per_variable_domain_meanings(self):
        answers = ["2", "", "Shipment calculation.", "Calculate shipment values.",
                   "calculate_shipment_values_tuple", "", "",
                   "unit_mass", "Mass per item.",
                   "item_count", "Number of items.",
                   "shipment_mass", "Product of supplied values.",
                   "adjusted_mass", "Combined result."]
        status, report, errors = self.run_cli(["--interactive"], answers)
        self.assertEqual(status, 0, errors)
        self.assertEqual(report["context"]["names"]["b"], "unit_mass")
        self.assertIn("Mass per item.", report["function_preview"])
        self.assertFalse(any(q["code"] == "SNIPNAME" for q in report["questions"]))

    def test_wrapping_retains_ast_comment_and_literal_token_content(self):
        from funcloom.snippet_wrapping import wrap_assignments_str
        import tokenize
        source = (
            "result = operand + operand + operand + operand + operand "
            "+ operand  # keep this comment\r\n"
            "label = 'original # literal' + 'another original literal'\r\n"
        )
        wrapped = wrap_assignments_str(source, 55)
        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(wrapped)))
        for token_type in (tokenize.COMMENT, tokenize.STRING):
            original = [t.string for t in tokenize.generate_tokens(
                StringIO(source).readline,
            ) if t.type == token_type]
            rewritten = [t.string for t in tokenize.generate_tokens(
                StringIO(wrapped).readline,
            ) if t.type == token_type]
            self.assertEqual(original, rewritten)
        self.assertIn("\r\n", wrapped)
        self.assertTrue(all(len(line) + 4 <= 55 for line in wrapped.splitlines()))

    def test_expanded_domain_names_wrap_with_existing_preview_validation(self):
        report = plan_snippet_report(
            SOURCE, SnippetContext(
                names={"b": "initial_operand", "c": "scaling_operand",
                       "a": "calculated_product", "total": "combined_result"},
            ),
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertIn("combined_result_float = (", report.function_preview)
        self.assertTrue(all(len(line) <= 79
                            for line in report.function_preview.splitlines()))
        self.assertTrue(report.preview_compiles)
