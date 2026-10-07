"""Regression cases for source selection, bindings, and proposal refusals."""

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from funcloom import RuleProfile, plan_extraction_report


class PlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_dir.cleanup)
        self.source_path = Path(self.temporary_dir.name) / "source.py"

    def plan(self, source: str, start: int, end: int, **options):
        self.source_path.write_bytes(source.encode())
        return plan_extraction_report(
            self.source_path, start, end,
            options.pop("name", "calculate_selected_values"), **options,
        )

    def assert_refused(self, report, code: str) -> None:
        self.assertEqual(report.status, "refused")
        self.assertIn(code, [item.code for item in report.diagnostics])
        self.assertIsNone(report.function_preview)
        self.assertIsNone(report.caller_preview)
        self.assertFalse(report.can_apply)

    def test_ordered_inputs_and_every_assigned_output(self) -> None:
        report = self.plan(
            "amount: float = 120.0\nrate: float = 0.1\n"
            "tax = amount * rate\ntotal = amount + tax\nprint(total)\n",
            3, 4,
        )
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs],
                         ["amount", "rate"])
        self.assertEqual([item.name for item in report.outputs],
                         ["tax", "total"])
        self.assertEqual(report.inputs[0].annotation, "float")
        self.assertEqual(report.inputs[0].type_evidence, "declared_unverified")
        self.assertIsNone(report.outputs[0].annotation)
        self.assertTrue(report.preview_compiles)

    def test_read_before_write_is_an_input_and_output(self) -> None:
        report = self.plan("amount = 3\namount = amount + 1\n", 2, 2)
        self.assertEqual([item.name for item in report.inputs], ["amount"])
        self.assertEqual([item.name for item in report.outputs], ["amount"])

    def test_internal_definitions_are_not_external_inputs(self) -> None:
        report = self.plan("first = 2\nsecond = first * 3\n", 1, 2)
        self.assertEqual(report.inputs, [])
        self.assertEqual([item.name for item in report.outputs],
                         ["first", "second"])

    def test_repeated_writes_keep_first_write_order(self) -> None:
        report = self.plan("alpha = 1\nbeta = alpha\nalpha = 3\n", 1, 3)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.outputs],
                         ["alpha", "beta"])

    def test_builtin_shadow_is_not_dropped(self) -> None:
        report = self.plan("len = 3\ncount = len + 2\n", 2, 2)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs], ["len"])
        report = self.plan("count = len\n", 1, 1)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.inputs, [])
        self.assertTrue(any("'len' stays a free name" in item
                            for item in report.assumptions))
        report = self.plan("if flag:\n    len = 3\ncount = len\n", 3, 3)
        self.assert_refused(report, "PLAN003")

    def test_unknown_and_later_bindings_are_refused(self) -> None:
        for source in ("result = missing + 1\n",
                       "result = later + 1\nlater = 4\n"):
            with self.subTest(source=source):
                self.assert_refused(self.plan(source, 1, 1), "PLAN003")

    def test_annotation_only_does_not_bind_value(self) -> None:
        report = self.plan("amount: float\nresult = amount + 1\n", 2, 2)
        self.assert_refused(report, "PLAN003")

    def test_unknown_types_are_not_guessed_from_literals_or_division(self):
        report = self.plan("numerator = 1\nratio = numerator / 2\n", 2, 2)
        self.assertIsNone(report.inputs[0].annotation)
        self.assertIsNone(report.outputs[0].annotation)
        self.assertNotIn(" -> ", report.function_preview)

    def test_stale_annotation_remains_declared_not_verified(self) -> None:
        report = self.plan("value: int = 1\nvalue = 'text'\ncopy = value\n",
                           3, 3)
        self.assertEqual(report.inputs[0].annotation, "int")
        self.assertEqual(report.inputs[0].type_evidence, "declared_unverified")

    def test_comments_and_crlf_source_bytes_are_retained(self) -> None:
        source = "base = 4\r\n# keep this comment\r\nresult = base + 2  # end\r\n"
        report = self.plan(source, 2, 3)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.source_fragment,
                         "# keep this comment\r\nresult = base + 2  # end\r\n")
        self.assertEqual(report.source_sha256, sha256(source.encode()).hexdigest())
        self.assertEqual(self.source_path.read_bytes(), source.encode())
        self.assertIn("# keep this comment", report.function_preview)

    def test_unicode_line_separators_inside_literals_keep_line_numbers(self):
        report = self.plan("message = 'one\u2028two'\ncopy = message\n", 2, 2)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.source_fragment, "copy = message\n")

    def test_non_utf8_source_hash_uses_original_bytes(self) -> None:
        original = b"# coding: latin-1\nlabel = 'caf\xe9'\ncopy = label\n"
        self.source_path.write_bytes(original)
        report = plan_extraction_report(self.source_path, 3, 3, "copy_label")
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(report.source_sha256, sha256(original).hexdigest())
        self.assertEqual(self.source_path.read_bytes(), original)

    def test_partial_multiline_statement_is_refused(self) -> None:
        self.assert_refused(self.plan("total = (\n    1 + 2\n)\n", 2, 2),
                            "PLAN001")
        report = self.plan("total = (\n    1 + 2\n)\n", 1, 3)
        self.assertEqual(report.status, "candidate_for_review")

    def test_nested_selection_and_decorators_are_refused(self) -> None:
        for source, start, end in (
            ("def outer():\n    result = 1\n", 2, 2),
            ("@decorator\ndef outer():\n    result = 1\n", 2, 3),
            ("class Outer:\n    result = 1\n", 2, 2),
        ):
            with self.subTest(source=source):
                self.assert_refused(self.plan(source, start, end), "PLAN001")

    def test_semicolon_groups_are_refused(self) -> None:
        self.assert_refused(self.plan("first = 1; second = 2\n", 1, 1),
                            "PLAN001")

    def test_augmented_and_object_assignments_are_candidates(self) -> None:
        for statement, inputs, outputs in (
            ("amount += 1", ["amount"], ["amount"]),
            ("amount[0] = 1", ["amount"], []),
            ("amount.value = 1", ["amount"], []),
        ):
            with self.subTest(statement=statement):
                report = self.plan("amount = 2\n" + statement + "\n", 2, 2)
                self.assertEqual(report.status, "candidate_for_review")
                self.assertEqual([item.name for item in report.inputs],
                                 inputs)
                self.assertEqual([item.name for item in report.outputs],
                                 outputs)

    def test_delete_and_control_flow_stay_refused(self) -> None:
        for statement in ("del amount", "import os"):
            with self.subTest(statement=statement):
                self.assert_refused(self.plan(
                    "amount = 2\n" + statement + "\n", 2,
                    1 + statement.count("\n") + 1,
                ), "PLAN002")

    def test_calls_containers_and_expressions_are_candidates(self):
        for expression in (
            "print(1)", "[].append(1)", "[1, 2]", "{'key': 1}",
            "(1, 2)", "1 if True else 2", "True and 2", "1 < 2",
            "str(1)[0:1]",
        ):
            with self.subTest(expression=expression):
                report = self.plan(f"result = {expression}\n", 1, 1)
                self.assertEqual(report.status, "candidate_for_review")

    def test_scopes_walrus_fstrings_and_frame_calls_are_refused(self):
        for expression in (
            "(value := 1)", "f'{1}'", "locals()", "eval('1')", "vars()",
        ):
            with self.subTest(expression=expression):
                report = self.plan(f"result = {expression}\n", 1, 1)
                self.assert_refused(report, "PLAN002")

    def test_annotated_region_assignment_is_refused(self):
        # Moving an annotation into a function changes its evaluation.
        self.assert_refused(self.plan("result: int = 1\n", 1, 1), "PLAN002")

    def test_chained_and_unpacking_assignments_return_every_name(self):
        for source, names in (("first = second = 1\n", ["first", "second"]),
                              ("first, *rest = (1, 2, 3)\n",
                               ["first", "rest"])):
            with self.subTest(source=source):
                report = self.plan(source, 1, 1)
                self.assertEqual(report.status, "candidate_for_review")
                self.assertEqual([item.name for item in report.outputs],
                                 names)

    def test_branches_loops_with_and_definitions_are_refused(self) -> None:
        for source in (
            "global result\nresult = 1\n",
            "def inner():\n    global result\n",
        ):
            with self.subTest(source=source):
                self.assert_refused(self.plan(source, 1, 2), "PLAN002")

    def test_uncertain_reads_are_refused_with_their_status(self) -> None:
        for source, line, status in (
            ("if True:\n    base = 2\nresult = base\n", 3,
             "possibly_unbound"),
            ("from unknown import *\nresult = base\n", 2,
             "possibly_unbound"),
            ("base = 1\ndel base\nresult = base\n", 3, "unbound"),
        ):
            with self.subTest(source=source):
                report = self.plan(source, line, line)
                self.assert_refused(report, "PLAN003")
                self.assertIn(status, report.diagnostics[-1].message)

    def test_module_level_ambiguous_reads_are_inputs(self) -> None:
        report = self.plan(
            "base = 1\nif flag:\n    base = 2\nresult = base\n", 4, 4)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual([item.name for item in report.inputs], ["base"])

    def test_any_prefix_is_allowed_when_reads_are_direct(self) -> None:
        for source, line in (
            ("base = load_value()\nresult = base\n", 2),
            ("from unknown import *\nresult = 1\n", 2),
            ("from unknown import *\nbase = 2\nresult = base\n", 3),
            ("def helper():\n    return 2\nresult = 1\n", 3),
            ("import math\nfor item in []:\n    pass\nif flag:\n"
             "    other = 1\nbase = 2\nresult = base * math\n", 7),
        ):
            with self.subTest(source=source):
                report = self.plan(source, line, line)
                self.assertEqual(report.status, "candidate_for_review")
                self.assertFalse(report.can_apply)

    def test_multiline_string_literals_are_refused(self) -> None:
        self.assert_refused(self.plan("text = '''first\nsecond'''\n", 1, 2),
                            "PLAN002")

    def test_no_source_or_import_execution(self) -> None:
        source = (
            "import no_such_module_for_funcloom_testing\n"
            "base = 3\nresult = base + 1\n"
            "raise RuntimeError('must never run')\n"
        )
        report = self.plan(source, 3, 3)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertEqual(self.source_path.read_bytes(), source.encode())

    def test_name_collisions_include_nested_names_and_builtins(self):
        for name in ("result", "print", "nested", "parameter"):
            with self.subTest(name=name):
                report = self.plan(
                    "result = 1\ndef nested(parameter):\n    return parameter\n",
                    1, 1, name=name,
                )
                self.assert_refused(report, "PLAN004")

    def test_invalid_requests_raise_before_reading(self) -> None:
        for start, end, name in ((0, 1, "compute"), (2, 1, "compute"),
                                  (True, 1, "compute"), (1, 1, "bad-name"),
                                  (1, 1, "class"), (1, 1, "\u212a")):
            with self.subTest(start=start, end=end, name=name):
                with self.assertRaises(ValueError):
                    plan_extraction_report(self.source_path, start, end, name)

    def test_empty_or_out_of_file_selections_are_refused(self) -> None:
        for source, start, end in (("# comment\n", 1, 1),
                                  ("value = 1\n", 1, 2)):
            with self.subTest(source=source):
                self.assert_refused(self.plan(source, start, end), "PLAN001")

    def test_parse_compile_and_read_failures_remain_failures(self) -> None:
        for source in ("def (\n", "return 1\n"):
            self.assert_refused(self.plan(source, 1, 1), "PARSE001")
        self.source_path.unlink()
        self.assert_refused(plan_extraction_report(self.source_path, 1, 1,
                                                   "compute"), "READ001")

    def test_resource_and_preview_caps_are_enforced(self) -> None:
        source = "first_value = 1\nsecond_value = first_value + 2\n"
        self.assert_refused(self.plan(source, 1, 2, profile_info=replace(
            RuleProfile(), max_file_bytes=4)), "READ001")
        self.assert_refused(self.plan(source, 1, 2, profile_info=replace(
            RuleProfile(), function_target_lines=5, function_max_lines=5)),
            "PLAN006")
        self.assert_refused(self.plan(source, 1, 2, profile_info=replace(
            RuleProfile(), line_length=40)), "PLAN006")

    def test_reports_are_repeatable_and_never_authorize_apply(self) -> None:
        report = self.plan("first = 1\nsecond = first + 2\n", 1, 2)
        repeated = plan_extraction_report(self.source_path, 1, 2,
                                          "calculate_selected_values")
        self.assertEqual(asdict(report), asdict(repeated))
        self.assertTrue(report.review_required)
        self.assertFalse(report.can_apply)
        self.assertFalse(report.source_rewriting)
        self.assertFalse(report.behavior_verified)

    def test_partial_exception_effects_are_explicitly_unproven(self):
        report = self.plan("first = 1\nsecond = 1 / 0\n", 1, 2)
        self.assertEqual(report.status, "candidate_for_review")
        self.assertFalse(report.behavior_verified)
        self.assertTrue(any("partial failure" in item for item in report.assumptions))

    def test_synthetic_numeric_previews_match_normal_completion(self):
        # Only these trusted synthetic fixtures are executed, never user code.
        for base in (-7, 0, 1, 13, 2.5):
            source = (
                f"base = {base!r}\n"
                "double = base * 2\nresult = (double + base) / 3\n"
            )
            with self.subTest(base=base):
                report = self.plan(source, 2, 3)
                self.assertEqual(report.status, "candidate_for_review")
                original, rewritten = {}, {}
                exec(source, original)
                exec(report.function_preview, rewritten)
                exec(f"base = {base!r}\n" + report.caller_preview, rewritten)
                self.assertEqual({name: original[name] for name in
                                  ("base", "double", "result")},
                                 {name: rewritten[name] for name in
                                  ("base", "double", "result")})
