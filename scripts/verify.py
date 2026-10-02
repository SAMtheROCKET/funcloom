"""Verify the installed local package using the current Python interpreter."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]


def run_step_int(
    title_str: str, arguments_list: list[str], expected_status_int: int = 0,
) -> int:
    """Run one trusted verification command and compare its exit status.

    Args:
        title_str (str): Human-readable purpose of this step.
        arguments_list (list[str]): Arguments to the current Python.
        expected_status_int (int): Expected process exit code.
    Returns:
        int: Zero on an expected outcome, otherwise one.
    Warnings:
        Runs only this project's own tests and analysis commands.
    """
    print(f"\n[{title_str}]", flush=True)
    process_result = subprocess.run(
        [sys.executable, *arguments_list], cwd=PROJECT_ROOT_PATH,
        check=False,
    )
    if process_result.returncode == expected_status_int:
        print(f"PASS: expected exit {expected_status_int}", flush=True)
        return 0
    print(
        f"FAIL: expected {expected_status_int}; "
        f"received {process_result.returncode}", flush=True,
    )
    return 1


def verify_json_report_int() -> int:
    """Check that the installed CLI returns usable inventory JSON.

    Args:
        None: Uses the included synthetic example directory.
    Returns:
        int: Zero for usable inventory, otherwise one.
    Warnings:
        This checks transport and coverage flags, not behavior preservation.
    """
    process_result = subprocess.run(
        [sys.executable, "-m", "funcloom", "scan", "examples",
         "--format", "json"],
        cwd=PROJECT_ROOT_PATH, capture_output=True, text=True, check=False,
    )
    try:
        report_dict = json.loads(process_result.stdout)
        summary_dict = report_dict["summary"]
        valid_bool = (
            process_result.returncode == 0
            and summary_dict["parsed_files"] == len(list(
                (PROJECT_ROOT_PATH / "examples").rglob("*.py")))
            and summary_dict["analysis_complete"] is True
            and summary_dict["behavior_verified"] is False
            and summary_dict["all_rules_implemented"] is False
        )
    except (ValueError, KeyError, TypeError):
        valid_bool = False
    print(f"{'PASS' if valid_bool else 'FAIL'}: inventory JSON contract")
    if not valid_bool:
        print(process_result.stderr or process_result.stdout)
    return int(not valid_bool)


def output_str(folder_path: Path, script_str: str) -> str:
    """Run one trusted script with the current Python and return stdout.

    Args:
        folder_path (Path): Working directory.
        script_str (str): Script file name in that folder.
    Returns:
        str: Captured standard output, or an error marker.
    Warnings:
        Runs only this project's example and the package generated from it.
    """
    process_result = subprocess.run(
        [sys.executable, script_str], cwd=folder_path, capture_output=True,
        text=True, check=False,
    )
    return (process_result.stdout if process_result.returncode == 0
            else f"error {process_result.returncode}")


def verify_modularize_int() -> int:
    """Build a package from the example script and compare its output.

    Args:
        None: Uses examples/modular_sales_report.py.
    Returns:
        int: Zero when the package writes the same output, otherwise one.
    Warnings:
        Output equality on one example is evidence, not a proof.
    """
    print("\n[Modularize example and compare output]", flush=True)
    example_path = PROJECT_ROOT_PATH / "examples" / "modular_sales_report.py"
    with tempfile.TemporaryDirectory() as directory_str:
        output_path = Path(directory_str) / "package"
        process_result = subprocess.run(
            [sys.executable, "-m", "funcloom", "modularize",
             str(example_path), "--output", str(output_path)],
            cwd=PROJECT_ROOT_PATH, capture_output=True, text=True,
            check=False,
        )
        expected_str = output_str(example_path.parent, example_path.name)
        actual_str = (output_str(output_path, "main.py")
                      if process_result.returncode == 0 else "not written")
    valid_bool = expected_str == actual_str and not expected_str.startswith(
        "error")
    print(f"{'PASS' if valid_bool else 'FAIL'}: generated package output "
          "matches the original script")
    return int(not valid_bool)


def verify_refine_int() -> int:
    """Refine the long-function example and compare its output.

    Args:
        None: Uses examples/long_functions.py.
    Returns:
        int: Zero when the refined copy prints the same output.
    Warnings:
        Output equality on one example is evidence, not a proof.
    """
    print("\n[Refine example and compare output]", flush=True)
    example_path = PROJECT_ROOT_PATH / "examples" / "long_functions.py"
    with tempfile.TemporaryDirectory() as directory_str:
        refined_path = Path(directory_str) / "long_functions.py"
        process_result = subprocess.run(
            [sys.executable, "-m", "funcloom", "refine", str(example_path),
             "--output", str(refined_path), "--document"],
            cwd=PROJECT_ROOT_PATH, capture_output=True, text=True,
            check=False,
        )
        expected_str = output_str(example_path.parent, example_path.name)
        actual_str = (output_str(refined_path.parent, refined_path.name)
                      if process_result.returncode == 0 else "not written")
        split_bool = "Split:" in process_result.stdout
    valid_bool = split_bool and expected_str == actual_str
    print(f"{'PASS' if valid_bool else 'FAIL'}: refined functions give the "
          "same output")
    return int(not valid_bool)


def main() -> int:
    """Run the local installation and regression verification sequence.

    Args:
        None: Uses the interpreter that launched this script.
    Returns:
        int: Zero when all checks have their expected outcomes.
    Warnings:
        The deliberately untidy example is expected to exit with one.
    """
    steps_tuple = (
        ("Installed runtime", ["-m", "funcloom", "doctor"], 0),
        ("Regression suite", ["-m", "unittest", "discover", "-s", "tests",
                              "-v"], 0),
        ("Clean example", ["-m", "funcloom", "check",
                           "examples/clean_module.py", "--fail-on",
                           "warning"], 0),
        ("Expected example findings", ["-m", "funcloom", "check",
                                       "examples/needs_structure.py",
                                       "--fail-on", "warning"], 1),
        ("Core source limits", ["-m", "funcloom", "check", "src"], 0),
        ("Extraction review candidate", ["-m", "funcloom", "plan",
                                         "examples/plan_supported.py",
                                         "--start-line", "7", "--end-line",
                                         "8", "--name",
                                         "calculate_invoice_totals_tuple"],
         0),
        ("Candidate after a realistic prefix", [
            "-m", "funcloom", "plan", "examples/plan_prefix.py",
            "--start-line", "16", "--end-line", "17",
            "--name", "calculate_invoice_totals_tuple",
        ], 0),
        ("Candidate with calls", [
            "-m", "funcloom", "plan", "examples/plan_calls.py",
            "--start-line", "13", "--end-line", "15",
            "--name", "summarize_readings_tuple",
        ], 0),
        ("Expected extraction refusal", ["-m", "funcloom", "plan",
                                          "examples/plan_refused.py",
                                          "--start-line", "8", "--end-line",
                                          "8", "--name",
                                          "calculate_net_amount_float"], 1),
        ("Snippet without project context", ["-m", "funcloom", "snippet",
                                            "examples/snippet_tax.py",
                                            "--no-context"], 0),
        ("Snippet with project context", ["-m", "funcloom", "snippet",
                                         "examples/snippet_tax.py",
                                         "--context",
                                         "profiles/snippet_tax.toml"], 0),
        ("Selected notebook cell", ["-m", "funcloom", "snippet",
                                    "examples/snippet_tax.ipynb",
                                    "--cell", "2", "--no-context"], 0),
        ("Mathematical naming", ["-m", "funcloom", "snippet",
                                  "examples/snippet_generic.py",
                                  "--naming", "mathematical"], 0),
        ("Explicit domain meanings", ["-m", "funcloom", "snippet",
                                       "examples/snippet_generic.py",
                                       "--context",
                                       "profiles/snippet_domain.toml"], 0),
    )
    failures_int = sum(
        run_step_int(title_str, arguments_list, expected_status_int)
        for title_str, arguments_list, expected_status_int in steps_tuple
    )
    failures_int += verify_json_report_int()
    failures_int += verify_modularize_int()
    failures_int += verify_refine_int()
    if failures_int:
        print(f"\nFAIL: {failures_int} verification steps failed.")
        return 1
    print("\nPASS: all local verification steps completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
