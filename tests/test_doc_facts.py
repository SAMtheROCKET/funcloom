"""Regressions for docstrings written from what a function body shows."""

import ast
import textwrap
import unittest

from funcloom.doc_facts import (
    describe_body_sentence_str, describe_parameter_use_str,
    infer_returned_type_str)
from funcloom.function_docs import insert_docstrings_tuple

SOURCE = textwrap.dedent('''
    import csv

    def load_rows(path):
        rows = []
        with open(path) as handle:
            for row in csv.DictReader(handle):
                rows.append(row)
        return rows
''')


def first_function(source_str: str) -> ast.FunctionDef:
    return ast.parse(textwrap.dedent(source_str)).body[0]


class DocFactsTests(unittest.TestCase):
    def test_body_facts_are_in_source_order(self):
        node = ast.parse(SOURCE).body[1]
        self.assertEqual(describe_body_sentence_str(node),
                         "It opens path, loops over csv.DictReader(handle) "
                         "and reads CSV rows.")
        self.assertEqual(describe_parameter_use_str(node, "path"),
                         "Passed to open().")
        self.assertEqual(infer_returned_type_str(node), "list")

    def test_uncertain_return_types_stay_unknown(self):
        for source_str in ("def f():\n    x = []\n    for x in y: pass\n"
                           "    return x\n",
                           "def f(x):\n    x = []\n    return x\n",
                           "def f():\n    x, y = [], 1\n    return x\n"):
            with self.subTest(source=source_str):
                self.assertEqual(
                    infer_returned_type_str(first_function(source_str)), "")

    def test_docstring_describes_the_code(self):
        new_str, names_list = insert_docstrings_tuple(SOURCE, 79)
        self.assertEqual(names_list, ["load_rows"])
        self.assertIn('"""Load rows. It opens path, loops over', new_str)
        self.assertIn("path (type not annotated): Passed to open().",
                      new_str)
        self.assertIn("list: rows.", new_str)
        self.assertNotIn("Not described", new_str)


if __name__ == "__main__":
    unittest.main()
