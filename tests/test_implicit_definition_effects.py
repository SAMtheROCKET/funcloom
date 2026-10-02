"""Implicit Python hooks must retain their place in the generated program."""

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from funcloom.modularize import modularize_report


class ImplicitDefinitionEffectsTests(unittest.TestCase):
    def test_definition_hooks_keep_behavior(self):
        sources = {
            "subclass": (
                "class Base:\n"
                "    def __init_subclass__(cls):\n"
                "        print('registered')\n"
                "class Child(Base):\n    pass\nprint('done')\n"),
            "shadowed_decorator": (
                "def cache(function):\n"
                "    print('decorated')\n    return function\n"
                "@cache\ndef handler():\n    return 1\nprint('done')\n"),
            "subscription": (
                "class Types:\n"
                "    def __class_getitem__(cls, key):\n"
                "        print('subscribed')\n        return int\n"
                "def handler(value: Types[int]):\n    return value\n"
                "print('done')\n"),
            "shadowed_property": (
                "def property(function):\n"
                "    print('property effect')\n    return function\n"
                "class Box:\n    @property\n    def value(self):\n"
                "        return 1\nprint('done')\n"),
            "class_namespace_decorator": (
                "class Box:\n"
                "    def property(function):\n"
                "        print('class decorator')\n"
                "        return function\n"
                "    @property\n    def value(self):\n"
                "        return 1\nprint('done')\n"),
        }
        for label, source in sources.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                original = root / "input.py"
                original.write_text(source, encoding="utf-8")
                report = modularize_report(original, output_dir=root / "out")
                self.assertEqual(report.status, "written", report.diagnostics)
                outputs = []
                for path in (original, root / "out/main.py"):
                    result = subprocess.run(
                        [sys.executable, str(path)], cwd=path.parent,
                        capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    outputs.append(result.stdout)
                self.assertEqual(*outputs)

    def test_implicit_annotation_hooks_are_refused(self):
        for annotation in ("Types[int]", "settings.kind", "Left | Right"):
            with self.subTest(annotation=annotation):
                report = modularize_report(source_text=(
                    f"amount: {annotation} = 1\nprint(amount)\n"))
                self.assertEqual(report.status, "refused")
                self.assertTrue(any(item.code == "MOD010"
                                    and item.line == 1
                                    for item in report.diagnostics))


class TypeEvidenceTests(unittest.TestCase):
    def test_fractional_power_does_not_claim_float_result(self):
        from funcloom.type_hints import infer_expression_type_str
        expression = ast.parse("(-1.0) ** 0.5", mode="eval").body
        self.assertIsNone(infer_expression_type_str(expression, {}, set()))
        self.assertIsInstance((-1.0) ** 0.5, complex)

    def test_inherited_constructor_is_not_assumed_to_return_its_class(self):
        from funcloom.type_hints import list_trusted_names_set
        tree = ast.parse("class Child(Base):\n    pass\n")
        self.assertNotIn("Child", list_trusted_names_set({"Child"}, tree.body))
