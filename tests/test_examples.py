"""Every shipped example notebook and data script converts without errors.

FuncLoom never runs these examples here (they need numpy, pandas and
matplotlib); behavior comparisons with those packages are recorded in
docs/BUILD_VERIFICATION.md.
"""

from pathlib import Path
import tempfile
import unittest

from funcloom.modularize import modularize_report
from funcloom.refine import RefineOptions

EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "examples"
CONVERTED_LIST = [
    *sorted((EXAMPLES_PATH / "notebooks").glob("*.ipynb")),
    EXAMPLES_PATH / "greenhouse_sensors.py",
]


class ExampleConversionTests(unittest.TestCase):
    def test_examples_convert_with_and_without_trusted_with_blocks(self):
        self.assertGreaterEqual(len(CONVERTED_LIST), 7)
        for source_path in CONVERTED_LIST:
            for trust_bool in (False, True):
                with self.subTest(example=source_path.name, trust=trust_bool):
                    with tempfile.TemporaryDirectory() as folder:
                        report = modularize_report(
                            source_path, output_dir=Path(folder) / "out",
                            options_info=RefineOptions(
                                trust_with_blocks=trust_bool))
                        errors = [item for item in report.diagnostics
                                  if item.severity == "error"]
                        self.assertEqual(report.status, "written", errors)
                        self.assertTrue(report.steps)
                        main_text = (Path(folder) / "out" / "main.py"
                                     ).read_text(encoding="utf-8")
                        self.assertIn('if __name__ == "__main__":',
                                      main_text)

    def test_notebooks_using_display_are_flagged(self):
        for source_path in CONVERTED_LIST:
            text = source_path.read_text(encoding="utf-8")
            if source_path.suffix != ".ipynb" or "display(" not in text:
                continue
            with self.subTest(example=source_path.name):
                report = modularize_report(source_path)
                self.assertIn("MODW08",
                              [item.code for item in report.diagnostics])


if __name__ == "__main__":
    unittest.main()
