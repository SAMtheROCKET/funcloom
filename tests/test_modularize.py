"""Behavior regressions for turning programs into modular packages.

Each fixture is authored here. It is run as the original script and as
the generated package, and the printed output must match.
"""

import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from funcloom.modularize import modularize_report

SALES_SOURCE = '''"""Summarize a small list of sales records."""

import statistics
from collections import Counter

tax_rate = 0.1
currency = "EUR"


def with_tax(amount):
    """Return an amount including tax."""
    return round(amount * (1 + tax_rate), 2)


class Sale:
    """One sale record."""

    def __init__(self, region, amount):
        self.region = region
        self.amount = amount


# Load the records
rows = [("north", 120.0), ("south", 80.5), ("north", 42.0)]
sales = [Sale(region, amount) for region, amount in rows]

# Clean the data
sales = [sale for sale in sales if sale.amount > 50]
regions = Counter(sale.region for sale in sales)

# Compute totals
totals = {}
for sale in sales:
    totals[sale.region] = totals.get(sale.region, 0) + with_tax(sale.amount)
if len(totals) > 1:
    busiest = max(totals, key=totals.get)
else:
    busiest = None

if __name__ == "__main__":
    print(currency, totals, busiest, dict(regions))
'''


def run_output_str(folder_path: Path, *arguments: str) -> str:
    """Run Python in a folder and return its output, failing on errors."""
    process_result = subprocess.run(
        [sys.executable, *arguments], cwd=folder_path, capture_output=True,
        text=True, check=False, timeout=60,
    )
    if process_result.returncode != 0:
        raise AssertionError(process_result.stderr)
    return process_result.stdout


class ModularizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def build(self, source: str, name: str = "program.py", **options):
        source_path = self.root / name
        source_path.write_text(source, encoding="utf-8")
        output_path = self.root / "out"
        report = modularize_report(source_path, output_dir=output_path,
                                   **options)
        self.assertEqual(source_path.read_text(encoding="utf-8"), source)
        return report, output_path

    def assert_same_behavior(self, source: str, **options):
        report, output_path = self.build(source, **options)
        self.assertEqual(report.status, "written", report.diagnostics)
        original_path = self.root / "original"
        original_path.mkdir()
        (original_path / "program.py").write_text(source, encoding="utf-8")
        expected = run_output_str(original_path, "program.py")
        self.assertEqual(run_output_str(output_path, "main.py"), expected)
        return report, output_path

    def test_script_becomes_package_with_same_output(self):
        report, output_path = self.assert_same_behavior(SALES_SOURCE)
        package = output_path / "program"
        self.assertEqual(sorted(path.name for path in package.iterdir()
                                if path.name != "__pycache__"), [
            "__init__.py", "__main__.py", "_imports.py", "config.py",
            "functions.py",
            "models.py", "pipeline.py", "steps.py"])
        self.assertEqual(report.constants,
                         {"tax_rate": "TAX_RATE", "currency": "CURRENCY"})
        self.assertEqual([step.name for step in report.steps], [
            "load_records", "clean_data", "compute_totals",
            "run_main_block"])
        self.assertIn("class Pipeline:",
                      (package / "pipeline.py").read_text())
        main_text = (output_path / "main.py").read_text()
        self.assertIn('if __name__ == "__main__":\n    main()', main_text)
        self.assertEqual(run_output_str(output_path, "-m", "program"),
                         run_output_str(output_path, "main.py"))

    def test_conditional_binding_merges_steps(self):
        source = ("import random\nrandom.seed(4)\n\n\n# Pick\n"
                  "if random.random() > 2:\n    label = 'never'\n\n\n"
                  "# Use\nprint(label if random.random() > 2 else 'ok')\n")
        report, _ = self.assert_same_behavior(source)
        self.assertTrue(any("may be unbound" in reason
                            for step in report.steps
                            for reason in step.merge_reasons))

    def test_value_kept_when_a_step_may_not_change_it(self):
        # The middle step rebinds x only sometimes; it must receive the
        # old value so it can hand it on unchanged.
        source = ("import sys\n\n# Setup\nx = 1\n\n\n# Maybe change\n"
                  "if len(sys.argv) > 5:\n    x = 2\n\n\n# Show\nprint(x)\n")
        report, _ = self.assert_same_behavior(source)
        middle = next(step for step in report.steps if "x" in step.outputs
                      and step.inputs)
        self.assertEqual(middle.inputs, ["x"])

    def test_late_bound_lambda_merges_until_rebinding(self):
        source = ("scale = [2]\n# Make\nf = lambda x: x * scale[0]\n\n\n"
                  "# Change\nscale = [3]\n\n\n# Use\nprint(f(1))\n")
        report, _ = self.assert_same_behavior(source)
        self.assertTrue(any("later step rebinds" in reason
                            for step in report.steps
                            for reason in step.merge_reasons))

    def test_function_using_script_state_stays_in_steps(self):
        source = ("data = [1, 2]\n\n\ndef total():\n    return sum(data)\n\n\n"
                  "# Grow\ndata.append(3)\n\n\n# Show\nprint(total())\n")
        report, output_path = self.assert_same_behavior(source)
        self.assertEqual(report.moved_definitions, {})
        self.assertTrue(any("'total'" in note for note in report.notes))

    def test_unsupported_programs_are_refused_without_writing(self):
        for source, code in (
            ("x = 1\nprint(globals()['x'])\n", "MOD002"),
            ("print(__spec__)\n", "MOD005"),
            ("print(1)\nfrom os.path import *\n", "MOD004"),
            ("global x\nx = 1\n", "MOD003"),
            ("x = = 1\n", "MOD001"),
        ):
            with self.subTest(code=code):
                report, output_path = self.build(source)
                self.assertEqual(report.status, "refused")
                self.assertIn(code, [item.code for item in report.diagnostics])
                self.assertFalse(output_path.exists())

    def test_library_only_input_and_multiline_strings(self):
        source = ('"""Tools."""\n\n\ndef double(x):\n    """Twice."""\n'
                  '    return 2 * x\n\n\nprint("start")\n'
                  'text = """first\nsecond"""\n'
                  'print(double(len(text)))\n')
        report, output_path = self.assert_same_behavior(source)
        # Multi-line strings are kept as written, never re-indented.
        self.assertFalse(any("regenerated" in note for note in report.notes))
        self.assertIn('text = """first' + chr(10) + 'second"""',
                      (output_path / "program" / "steps.py").read_text())
        library_path = self.root / "lib.py"
        library_path.write_text("def f(x):\n    return x\n")
        library = modularize_report(library_path,
                                    output_dir=self.root / "lib_out")
        self.assertEqual(library.status, "written", library.diagnostics)
        self.assertEqual(library.steps, [])
        self.assertEqual(run_output_str(self.root / "lib_out", "main.py"), "")

    def test_existing_folder_is_refused_and_nothing_is_left_behind(self):
        (self.root / "out").mkdir()
        (self.root / "out" / "keep.txt").write_text("mine")
        report, output_path = self.build("print(1)\n")
        self.assertEqual(report.status, "refused")
        self.assertIn("MOD006", [item.code for item in report.diagnostics])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()),
                         ["out", "program.py"])

    def test_many_sections_use_stage_methods_and_names_do_not_clash(self):
        body = "".join(f"# Part {index}\nrun = {index}\nprint(run)\n\n\n"
                       for index in range(40))
        source = "main = 'm'\nPipeline = 'p'\n\n\n" + body + "print(main)\n"
        report, output_path = self.assert_same_behavior(source)
        pipeline_text = (output_path / "program" / "pipeline.py").read_text()
        self.assertIn("def run_stage_2(self)", pipeline_text)
        tree = ast.parse(pipeline_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                self.assertLessEqual(node.end_lineno - node.lineno + 1, 50)

    def test_import_after_path_change_stays_in_place(self):
        source = ("import sys\nsys.path.insert(0, 'nowhere')\n"
                  "import json\nprint(json.dumps({'a': 1}))\n")
        report, output_path = self.assert_same_behavior(source)
        steps_text = (output_path / "program" / "steps.py").read_text()
        self.assertIn("    import json", steps_text)

    def test_notebook_cells_headings_and_magics(self):
        notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {},
                    "cells": [
            {"cell_type": "code", "source": "import math\n%matplotlib inline"},
            {"cell_type": "markdown", "source": "## Compute area"},
            {"cell_type": "code", "source": "radius = 2.0\n"
             "area = math.pi * radius ** 2\n!pip list"},
            {"cell_type": "code", "source": "print('skipped cell')"},
            {"cell_type": "markdown", "source": "# Report"},
            {"cell_type": "code", "source": "print(round(area, 3))"},
        ]}
        path = self.root / "analysis.ipynb"
        path.write_text(json.dumps(notebook), encoding="utf-8")
        report = modularize_report(path, output_dir=self.root / "out",
                                   cells_list=[1, 3, 6])
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual([step.name for step in report.steps],
                         ["compute_area", "report"])
        self.assertTrue(any("magic removed" in note for note in report.notes))
        self.assertEqual(run_output_str(self.root / "out", "main.py"),
                         "12.566\n")

    def test_augmented_and_deleted_names_are_passed_between_steps(self):
        # Found by the differential probe: `+=` and `del` read the name.
        source = ("count: int = 0\n\n\n# Up\ncount += 1\ncount += 1\n\n\n"
                  "# Drop\ntemp = count\n\n\n# Clear\ndel temp\n"
                  "print(count, 'temp' in dir())\n")
        report, _ = self.assert_same_behavior(source)
        self.assertIn("count", report.steps[1].inputs)

    def test_name_checks_in_executable_code_are_refused(self):
        for source in ("print(__name__)\n",
                       "if __name__ == '__main__':\n    x = 1\nelse:\n"
                       "    x = 2\n"):
            with self.subTest(source=source):
                report, output_path = self.build(source)
                self.assertIn("MOD005",
                              [item.code for item in report.diagnostics])
                self.assertFalse(output_path.exists())

    def test_file_paths_resolve_next_to_the_script(self):
        source = ("from pathlib import Path\n\n\n# Read\n"
                  "here = Path(__file__).resolve().parent\n"
                  "print((here / 'data.txt').read_text(), "
                  "Path(__file__).name)\n")
        (self.root / "data.txt").write_text("hello")
        report, output_path = self.build(source)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertIn("MODW06", [item.code for item in report.diagnostics])
        (output_path / "data.txt").write_text("hello")
        self.assertEqual(run_output_str(output_path, "main.py"),
                         "hello main.py\n")

    def test_cli_plans_from_stdin_without_writing(self):
        process_result = subprocess.run(
            [sys.executable, "-m", "funcloom", "modularize", "-",
             "--format", "json"], input="x = 2\nprint(x * 3)\n",
            capture_output=True, text=True, check=False, cwd=self.root)
        self.assertEqual(process_result.returncode, 0, process_result.stderr)
        report = json.loads(process_result.stdout)
        self.assertEqual(report["status"], "planned")
        self.assertNotIn("text", report["files"][0])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_too_deeply_nested_program_is_refused_not_crashed(self):
        nested_str = "x = " + "[" * 190 + "]" * 190 + "\nprint(x)\n"
        report = modularize_report(source_text=nested_str)
        self.assertEqual(report.status, "refused")
        self.assertEqual([diagnostic_info.code
                          for diagnostic_info in report.diagnostics],
                         ["READ001"])
