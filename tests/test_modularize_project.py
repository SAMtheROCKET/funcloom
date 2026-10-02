"""Folder-mode regressions: run each command on the original project and on
the converted copy, and compare the output. All fixtures are authored here.
"""

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from funcloom import modularize as modularize_module
from funcloom.modular_project import modularize_project_report

PROJECT_FILES = {
    "utils.py": '"""Shared helpers."""\n\nSCALE = 2\n\n\ndef scaled(value):\n'
                "    return value * SCALE\n",
    "lib/__init__.py": "from .stats import mean_of\n",
    "lib/helpers.py": "def total(values):\n    return sum(values)\n",
    "lib/stats.py": "from .helpers import total\n\n\ndef mean_of(values):\n"
                    "    return total(values) / len(values)\n",
    "data/values.csv": "value\n3\n5\n10\n",
    "train.py": (
        '"""Train from the CSV file."""\n\nimport csv\nimport sys\n\n'
        "from lib import mean_of\nfrom utils import scaled\n\nthreshold = 4"
        "\n\n\n# Load the data\nwith open('data/values.csv') as handle:\n"
        "    rows = [int(row['value']) for row in csv.DictReader(handle)]\n\n"
        "# Fit\nbig = [value for value in rows if value > threshold]\n"
        "model = {'mean': mean_of(rows), 'big': [scaled(v) for v in big]}\n\n"
        "if __name__ == '__main__':\n"
        "    label = sys.argv[1] if len(sys.argv) > 1 else 'default'\n"
        "    print(label, model)\n"),
    "report.py": "from lib.helpers import total\n\nnumbers = list(range(5))\n"
                 "print('report', total(numbers))\n",
    "tools/common.py": "PREFIX = '>>'\n",
    "tools/cleanup.py": "from common import PREFIX\n\nitems = ['a', 'b']\n"
                        "for item in items:\n    print(PREFIX, item)\n",
    "tools/report.py": "print('tools report')\n",
    "locate.py": "from pathlib import Path\nprint(Path(__file__).name)\n",
    "tests/test_utils.py": "import utils\nprint(utils.scaled(3))\n",
    "setup.py": "print('setup')\n",
}


def run_str(folder_path: Path, *arguments: str) -> str:
    """Run Python in a folder; return output, or the error's last line."""
    result = subprocess.run([sys.executable, *arguments], cwd=folder_path,
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        return "error: " + result.stderr.strip().splitlines()[-1]
    return result.stdout


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "project"
        for relative_str, text_str in PROJECT_FILES.items():
            path = self.root / relative_str
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text_str, encoding="utf-8")
        self.output = Path(self.directory.name) / "converted"

    def snapshot(self) -> dict[str, bytes]:
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_commands_behave_the_same_after_conversion(self):
        before = self.snapshot()
        report = modularize_project_report(self.root, self.output)
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(self.snapshot(), before)
        for command in (["train.py"], ["train.py", "custom"], ["report.py"],
                        ["tools/cleanup.py"], ["tools/report.py"],
                        ["locate.py"], ["setup.py"]):
            with self.subTest(command=command):
                self.assertEqual(run_str(self.output, *command),
                                 run_str(self.root, *command))
        self.assertEqual(run_str(self.output, "main.py", "train", "x"),
                         run_str(self.root, "train.py", "x"))
        self.assertEqual(run_str(self.output, "-m", "train_app"),
                         run_str(self.root, "train.py"))

    def test_layout_entries_and_kept_files(self):
        report = modularize_project_report(self.root, self.output)
        converted = {Path(entry.source_name).name for entry in report.entries
                     if entry.status == "written"}
        self.assertEqual(converted, {"train.py", "report.py", "cleanup.py",
                                     "locate.py"})
        self.assertIn("tooling", report.kept_scripts["setup.py"])
        self.assertIn("tooling", report.kept_scripts["tests/test_utils.py"])
        for relative_str in ("train_app/steps.py", "train_app/config.py",
                             "tools/cleanup_app/pipeline.py", "utils.py",
                             "lib/stats.py", "data/values.csv"):
            self.assertTrue((self.output / relative_str).is_file(),
                            relative_str)
        self.assertEqual((self.output / "utils.py").read_bytes(),
                         (self.root / "utils.py").read_bytes())
        self.assertEqual(report.orchestrator, "main.py")
        names = ast.literal_eval(
            (self.output / "main.py").read_text().split(
                "ENTRY_SCRIPTS_DICT = ")[1].split("\n}\n")[0] + "\n}")
        self.assertEqual(set(names), {"train", "report", "cleanup",
                                      "tools_report", "locate"})

    def test_entries_option_and_skip_data(self):
        report = modularize_project_report(
            self.root, self.output, entries_list=["report.py"],
            skip_data_bool=True)
        self.assertEqual([Path(item.source_name).name
                          for item in report.entries], ["report.py"])
        self.assertIn("--entries", report.kept_scripts["train.py"])
        self.assertFalse((self.output / "data" / "values.csv").exists())
        self.assertTrue(any("not copied" in note for note in report.notes))

    def test_output_inside_input_and_existing_output_are_refused(self):
        report = modularize_project_report(self.root, self.root / "out")
        self.assertEqual(report.status, "refused")
        self.assertIn("MOD006", [item.code for item in report.diagnostics])
        self.output.mkdir()
        (self.output / "mine.txt").write_text("keep")
        report = modularize_project_report(self.root, self.output)
        self.assertEqual(report.status, "refused")
        self.assertEqual(sorted(path.name for path in self.output.iterdir()),
                         ["mine.txt"])

    def test_plan_only_writes_nothing(self):
        report = modularize_project_report(self.root)
        self.assertEqual(report.status, "planned")
        self.assertFalse(self.output.exists())


class SingleFileAdditionsTests(unittest.TestCase):
    def test_sibling_import_warning_and_nested_wrapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "helpers.py").write_text("def twice(x):\n    return 2*x\n")
            source = ("import helpers\n\n\n# Loop\nfor index in range(2):\n"
                      "    very_long_result_name = helpers.twice(index) + "
                      "helpers.twice(index + 1) + helpers.twice(index + 2)\n"
                      "    print(very_long_result_name)\n")
            (root / "script.py").write_text(source)
            report = modularize_module.modularize_report(
                root / "script.py", output_dir=root / "out")
            self.assertIn("MODW04",
                          [item.code for item in report.diagnostics])
            steps = (root / "out" / "script" / "steps.py").read_text()
            self.assertIn("very_long_result_name = (", steps)
            self.assertTrue(all(len(line) <= 79
                                for line in steps.splitlines()))
            (root / "out" / "helpers.py").write_text(
                (root / "helpers.py").read_text())
            self.assertEqual(run_str(root / "out", "main.py"),
                             run_str(root, "script.py"))
