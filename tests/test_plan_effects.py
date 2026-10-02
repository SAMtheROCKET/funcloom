"""Regressions for partial, source-located effect evidence in plans."""

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from funcloom import plan_extraction_report
from funcloom.plan_reporting import render_plan_str


class PlanEffectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "effects.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(
            self.source_path, start, end, "calculate_result",
        )
        self.assertEqual(self.source_path.read_bytes(), source.encode("utf-8"))
        self.assertFalse(report.can_apply)
        self.assertFalse(report.behavior_verified)
        return report

    def test_candidate_records_operators_and_delayed_writes(self):
        report = self.plan(
            "base = 2\nfirst = base + 1\nlast = first / 0\n", 2, 3,
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.schema_version, "plan-3")
        self.assertEqual(report.effect_analysis, "partial")
        operators = [f for f in report.effects if f.kind == "operator"]
        self.assertEqual([f.line for f in operators], [2, 3])
        writes = [f for f in report.effects if f.kind == "binding_visibility"]
        self.assertEqual([f.line for f in writes], [2, 3])
        self.assertIn("partial-failure", writes[0].detail)
        self.assertTrue(report.effect_limitations)

    def test_alias_syntax_does_not_claim_mutability_or_infer_type(self):
        report = self.plan("base = 2\ncopy = base\nresult = copy\n", 3, 3)
        aliases = [f for f in report.effects if f.kind == "alias"]
        self.assertEqual([(f.line, f.region) for f in aliases],
                         [(2, "prefix"), (3, "selection")])
        self.assertIn("copy = base", aliases[0].detail)
        self.assertTrue(all(f.evidence == "syntactic" for f in aliases))
        self.assertIsNone(report.outputs[0].annotation)

    def test_call_candidates_keep_effect_locations_without_execution(self):
        # The named package does not exist; planning never imports it.
        report = self.plan(
            "import absent_package_for_effect_testing\n"
            "result = absent_package_for_effect_testing.fetch()\n", 2, 2,
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertFalse(report.behavior_verified)
        self.assertIn(("import", 1, "prefix"),
                      [(f.kind, f.line, f.region) for f in report.effects])
        calls = [f for f in report.effects if f.kind == "call"]
        self.assertEqual(
            [(f.line, f.region) for f in calls], [(2, "selection")],
        )

    def test_mutation_keeps_effect_evidence_and_del_stays_refused(self):
        for statement, kind, status in (
            ("value += 2", "augmented_assignment", "candidate_for_review"),
            ("value[0] = 2", "object_access", "candidate_for_review"),
            ("value.field = 2", "object_access", "candidate_for_review"),
            ("del value[0]", "delete", "refused"),
        ):
            with self.subTest(statement=statement):
                report = self.plan("value = 1\n" + statement + "\n", 2, 2)
                self.assertEqual(report.status, status)
                self.assertIn(kind, [f.kind for f in report.effects])

    def test_definition_defaults_and_decorators_remain_opaque(self):
        report = self.plan(
            "@decorate()\ndef helper(value=load()):\n"
            "    hidden = danger()\nresult = 1\n", 4, 4,
        )
        boundaries = [f for f in report.effects if f.kind == "scope_boundary"]
        self.assertEqual([(f.line, f.end_line) for f in boundaries], [(2, 3)])
        self.assertNotIn("call", [f.kind for f in report.effects])
        self.assertTrue(any(
            "decorators" in item for item in report.effect_limitations
        ))
        # The prefix stays in place, so an opaque definition no longer
        # blocks a selection whose reads are resolved.
        self.assertEqual(report.status, "candidate_for_review")

    def test_comprehension_and_lambda_do_not_leak_scope_facts(self):
        for expression in ("[danger(item) for item in values]",
                           "(lambda: danger())"):
            report = self.plan(f"result = {expression}\n", 1, 1)
            self.assertIn("scope_boundary", [f.kind for f in report.effects])
            self.assertNotIn("call", [f.kind for f in report.effects])
            self.assertEqual(report.status, "refused")

    def test_control_flow_is_syntax_evidence_not_reachability(self):
        report = self.plan("if False:\n    value = danger()\n", 1, 2)
        self.assertIn("control_flow", [f.kind for f in report.effects])
        self.assertIn("call", [f.kind for f in report.effects])
        self.assertEqual(report.status, "refused")

    def test_annotations_are_unverified_even_with_future_import(self):
        report = self.plan(
            "from __future__ import annotations\n"
            "base: unknown_type() = 2\nresult = base\n", 3, 3,
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertIn("annotation", [f.kind for f in report.effects])
        self.assertEqual(report.inputs[0].type_evidence, "declared_unverified")
        self.assertTrue(all(f.evidence == "syntactic" for f in report.effects))

    def test_partial_selection_and_bad_source_do_not_claim_inventory(self):
        for source, start, end in (("value = (\n    1 + 2\n)\n", 2, 2),
                                   ("return 2\n", 1, 1),
                                   ("value = 1\n", 1, 3)):
            report = self.plan(source, start, end)
            self.assertEqual(report.effect_analysis, "not_run")
            self.assertEqual(report.effects, [])
            self.assertEqual(report.status, "refused")

    def test_columns_are_original_utf8_offsets_with_exclusive_ends(self):
        report = self.plan("base = 2\n\u00e9 = base + 1\n", 2, 2)
        fact = next(f for f in report.effects if f.kind == "operator")
        self.assertEqual((fact.line, fact.column_utf8, fact.end_line,
                          fact.end_column_utf8), (2, 5, 2, 13))

    def test_suffix_is_excluded_and_reports_remain_repeatable(self):
        source = "base = 2\nresult = base + 1\nsuffix_call()\n"
        report = self.plan(source, 2, 2)
        repeated = self.plan(source, 2, 2)
        self.assertEqual(asdict(report), asdict(repeated))
        self.assertNotIn("call", [f.kind for f in report.effects])
        self.assertIn("suffix not analyzed", report.effect_limitations[0])

    def test_text_and_json_include_effects_for_refusals(self):
        report = self.plan("value = danger()\n", 1, 1)
        self.assertIn("selection:1 call", render_plan_str(report, "text"))
        self.assertIn('"effect_analysis": "partial"',
                      render_plan_str(report, "json"))

    def test_trusted_fixture_demonstrates_partial_write_difference(self):
        # Execute only this synthetic fixture, never arbitrary target code.
        source = "first = 1\nsecond = 1 / 0\n"
        report = self.plan(source, 1, 2)
        original, extracted = {}, {}
        with self.assertRaises(ZeroDivisionError):
            exec(source, original)
        exec(report.function_preview, extracted)
        with self.assertRaises(ZeroDivisionError):
            exec(report.caller_preview, extracted)
        self.assertEqual(original["first"], 1)
        self.assertNotIn("first", extracted)
        self.assertIn("binding_visibility", [f.kind for f in report.effects])
