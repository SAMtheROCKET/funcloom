"""Regressions for lexical module-scope binding resolution in plans."""

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from funcloom import plan_extraction_report
from funcloom.plan_reporting import render_plan_str


class PlanBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "bindings.py"

    def plan(self, source: str, start: int, end: int):
        self.source_path.write_bytes(source.encode("utf-8"))
        report = plan_extraction_report(
            self.source_path, start, end, "calculate_result",
        )
        self.assertEqual(self.source_path.read_bytes(), source.encode("utf-8"))
        self.assertFalse(report.can_apply)
        return report

    def statuses(self, report) -> dict[str, str]:
        return {item.name: item.status for item in report.name_resolutions}

    def test_candidate_inputs_resolve_directly_and_locals_stay_local(self):
        report = self.plan("base = 2\nrate = 3\nfirst = base\n"
                           "second = first + rate\n", 3, 4)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.schema_version, "plan-3")
        self.assertEqual(report.binding_analysis, "partial")
        self.assertEqual(self.statuses(report), {
            "base": "direct", "first": "selection_local", "rate": "direct",
        })
        for item in report.inputs:
            self.assertEqual(self.statuses(report)[item.name], "direct")
        self.assertTrue(report.binding_limitations)

    def test_conditional_binding_is_possibly_unbound_or_ambiguous(self):
        report = self.plan("if flag:\n    value = 1\nresult = value\n", 3, 3)
        self.assertEqual(self.statuses(report)["value"], "possibly_unbound")
        report = self.plan("value = 0\nif flag:\n    value = 1\n"
                           "result = value\n", 4, 4)
        self.assertEqual(self.statuses(report)["value"], "ambiguous")
        self.assertEqual([site.line for site in report.name_resolutions[0]
                          .sites], [1, 3])

    def test_constant_conditions_are_not_folded(self):
        report = self.plan("if True:\n    value = 1\nresult = value\n", 3, 3)
        self.assertEqual(self.statuses(report)["value"], "possibly_unbound")

    def test_deletion_and_exception_targets_unbind(self):
        report = self.plan("value = 1\ndel value\nresult = value\n", 3, 3)
        self.assertEqual(self.statuses(report)["value"], "unbound")
        report = self.plan("value = 1\ntry:\n    pass\nexcept Exception "
                           "as value:\n    pass\nresult = value\n", 6, 6)
        self.assertEqual(self.statuses(report)["value"], "possibly_unbound")
        self.assertIn("exception_target",
                      [site.kind for site in report.binding_sites])

    def test_trusted_fixture_confirms_unbound_exception_name(self):
        # Execute only this synthetic fixture, never arbitrary target code.
        source = ("value = 1\ntry:\n    1 / 0\nexcept ZeroDivisionError "
                  "as value:\n    pass\nresult = value\n")
        report = self.plan(source, 6, 6)
        self.assertEqual(self.statuses(report)["value"], "possibly_unbound")
        with self.assertRaises(NameError):
            exec(source, {})

    def test_wildcard_import_is_namespace_wide_until_rebound(self):
        report = self.plan("from package import *\nresult = value\n", 2, 2)
        self.assertEqual(self.statuses(report)["value"], "possibly_unbound")
        report = self.plan("from package import *\nvalue = 1\n"
                           "result = value + len\n", 3, 3)
        self.assertEqual(self.statuses(report), {
            "value": "direct", "len": "builtin_fallback",
        })

    def test_function_globals_and_namespace_calls_are_call_dependent(self):
        report = self.plan("value = 1\ndef change():\n    global value\n"
                           "    value = 2\nresult = value\n", 5, 5)
        self.assertEqual(self.statuses(report)["value"], "ambiguous")
        report = self.plan("def change():\n    globals()['other'] = 1\n"
                           "value = 1\nresult = value\n", 4, 4)
        self.assertEqual(self.statuses(report)["value"], "ambiguous")
        kinds = {(site.kind, site.certainty) for site in report.binding_sites}
        self.assertIn(("dynamic_namespace", "call_dependent"), kinds)

    def test_function_defined_after_read_is_not_a_risk(self):
        report = self.plan("value = 1\nresult = value\ndef change():\n"
                           "    global value\n", 2, 2)
        self.assertEqual(self.statuses(report)["value"], "direct")
        self.assertNotIn("global_declaration",
                         [site.kind for site in report.binding_sites])

    def test_loop_target_and_back_edges(self):
        report = self.plan("total = 0\nfor item in items:\n"
                           "    previous = total\n    total = item\n", 2, 4)
        self.assertEqual(self.statuses(report), {
            "items": "unresolved", "total": "ambiguous",
            "item": "selection_local",
        })
        report = self.plan("for item in []:\n    pass\nresult = item\n", 3, 3)
        self.assertEqual(self.statuses(report)["item"], "possibly_unbound")

    def test_nested_scopes_stay_opaque_but_walrus_leaks(self):
        report = self.plan("result = [item for item in values]\n", 1, 1)
        self.assertEqual(self.statuses(report), {"values": "unresolved"})
        report = self.plan("def helper(item=default):\n    return hidden\n",
                           1, 2)
        self.assertEqual(self.statuses(report), {"default": "unresolved"})
        report = self.plan("[(last := item) for item in values]\n"
                           "result = last\n", 2, 2)
        self.assertEqual(self.statuses(report)["last"], "possibly_unbound")
        self.assertNotIn("item", [site.name for site in report.binding_sites])

    def test_context_match_and_implicit_names(self):
        report = self.plan("with manager() as handle:\n    data = handle\n",
                           1, 2)
        self.assertEqual(self.statuses(report)["handle"], "selection_local")
        report = self.plan("match value:\n    case [first, *rest]:\n"
                           "        pass\nresult = rest\n", 4, 4)
        self.assertEqual(self.statuses(report)["rest"], "possibly_unbound")
        report = self.plan("result = __name__\n", 1, 1)
        self.assertEqual(self.statuses(report)["__name__"],
                         "module_implicit")

    def test_augmented_and_deleted_selection_names_are_reads(self):
        report = self.plan("value = 1\nvalue += 1\n", 2, 2)
        self.assertEqual(self.statuses(report)["value"], "direct")
        report = self.plan("del missing\n", 1, 1)
        self.assertEqual(self.statuses(report)["missing"], "unresolved")

    def test_invalid_selection_does_not_claim_resolution(self):
        report = self.plan("value = (\n    1\n)\n", 2, 2)
        self.assertEqual(report.binding_analysis, "not_run")
        self.assertEqual(report.name_resolutions, [])

    def test_reports_are_repeatable_and_rendered(self):
        source = "value = 0\nif flag:\n    value = 1\nresult = value\n"
        report = self.plan(source, 4, 4)
        self.assertEqual(asdict(report), asdict(self.plan(source, 4, 4)))
        text_str = render_plan_str(report, "text")
        self.assertIn("Binding analysis: partial", text_str)
        self.assertIn("- value (line 4): ambiguous", text_str)
        self.assertIn('"name_resolutions"', render_plan_str(report, "json"))

    def test_columns_are_original_utf8_offsets(self):
        report = self.plan("é = 1\nresult = é\n", 2, 2)
        site = report.name_resolutions[0].sites[0]
        self.assertEqual((site.line, site.column_utf8, site.visible_line,
                          site.visible_column_utf8), (1, 0, 1, 6))
        self.assertEqual(report.name_resolutions[0].column_utf8, 9)
