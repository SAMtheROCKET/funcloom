"""A script without headings is split at its blank-line paragraphs.

The fixture is authored here, run as the original script and as the
generated package, and the printed output must match.
"""

import tempfile
import unittest
from pathlib import Path

from funcloom.modularize import modularize_report
from tests.test_modularize import run_output_str

PLAIN_SOURCE = '''import json

values = [3, 1, 4, 1, 5]
limit = 2

kept = []
for value in values:
    if value > limit:
        kept.append(value)
print("kept", kept)

total = 0
for value in kept:
    total += value
average = total / len(kept)

report = {"total": total, "average": average}
text = json.dumps(report, sort_keys=True)
print(text)
'''


class ParagraphStepTests(unittest.TestCase):
    def test_paragraphs_become_named_steps_with_same_output(self):
        with tempfile.TemporaryDirectory() as directory_str:
            root = Path(directory_str)
            source_path = root / "program.py"
            source_path.write_text(PLAIN_SOURCE, encoding="utf-8")
            output_path = root / "out"
            report = modularize_report(source_path, output_dir=output_path)
            self.assertEqual(report.status, "written", report.diagnostics)
            # The last paragraph (three lines) joins the one before; that
            # final step only prints, so it is named after printing.
            self.assertEqual([step.name for step in report.steps],
                             ["compute_kept", "print_results"])
            expected_str = run_output_str(root, "program.py")
            self.assertEqual(run_output_str(output_path, "main.py"),
                             expected_str)


if __name__ == "__main__":
    unittest.main()
