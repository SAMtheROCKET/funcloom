"""Regressions for splitting long functions, documenting and refine.

Every fixture is authored here; original and refined modules are run and
their results compared.
"""

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

from funcloom.function_docs import insert_docstrings_tuple
from funcloom.function_split_text import split_functions_text_tuple
from funcloom.modularize import modularize_report
from funcloom.refine import RefineOptions, refine_file_report


def filler_lines(count: int, indent: str = "    ") -> str:
    """Return distinct harmless statements that use and grow `acc`."""
    return "".join(f"{indent}acc = acc + [{index}]\n" for index in range(count))


LONG_FUNCTION = (
    "import math\n\n\ndef analyse(values, scale=2):\n"
    '    """Analyse values."""\n'
    "    cleaned = [v for v in values if v is not None]\n"
    "    if not cleaned:\n        return None\n"
    "    acc = []\n" + filler_lines(18) +
    "    mean = sum(cleaned) / len(cleaned)\n"
    "    shift = lambda x: x - mean\n"
    + filler_lines(18) +
    "    spread = [shift(v) * scale for v in cleaned]\n"
    "    if max(spread) > 100:\n        return 'huge', len(acc)\n"
    "    return mean, math.fsum(spread), len(acc)\n"
)

LONG_METHOD = (
    "class Report:\n    def build(self, rows):\n        acc = []\n"
    + filler_lines(20, "        ")
    + "        self.total = sum(rows) + len(acc)\n"
    + filler_lines(20, "        ")
    + "        return self.total, len(acc)\n"
)


def load_module(text: str) -> types.ModuleType:
    """Execute authored module text and return it as a module object."""
    module = types.ModuleType("fixture")
    exec(compile(text, "fixture", "exec"), module.__dict__)
    return module


class SplitTests(unittest.TestCase):
    def split(self, text: str) -> tuple[str, list, list]:
        new_text, notes, names = split_functions_text_tuple(text, 79, 40)
        compile(new_text, "split", "exec")
        return new_text, notes, names

    def test_long_function_with_early_returns_and_closure(self):
        new_text, _, names = self.split(LONG_FUNCTION)
        self.assertEqual(names, ["analyse"])
        original, refined = load_module(LONG_FUNCTION), load_module(new_text)
        for values in ([1, 2, None, 3], [], [None], [500, -1], [2.5]):
            with self.subTest(values=values):
                self.assertEqual(original.analyse(values),
                                 refined.analyse(values))
        tree = ast.parse(new_text)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self.assertLessEqual(node.end_lineno - node.lineno + 1, 50)
        self.assertIn('"""Analyse values."""', new_text)

    def test_long_method_keeps_instance_state(self):
        new_text, _, names = self.split(LONG_METHOD)
        self.assertEqual(names, ["Report.build"])
        original = load_module(LONG_METHOD).Report()
        refined = load_module(new_text).Report()
        self.assertEqual(original.build([1, 2]), refined.build([1, 2]))
        self.assertEqual(vars(original), vars(refined))
        self.assertIn("def _Report_build_part_1(", new_text)

    def test_unsafe_functions_are_left_whole(self):
        body = filler_lines(45)
        for header, marker in (
            ("async def agen():\n    acc = []\n", "    yield acc\n"),
            ("def use_locals():\n    acc = []\n", "    print(locals())\n"),
            ("class A:\n    def m(self):\n        acc = []\n",
             "        return super().m()\n"),
            ("def uses_global():\n    global acc\n    acc = []\n", ""),
        ):
            with self.subTest(header=header):
                indent = "        " if header.startswith("class") else "    "
                text = header + filler_lines(45, indent) + marker
                new_text, notes, names = self.split(text)
                self.assertEqual(names, [])
                self.assertEqual(new_text, text)
                self.assertTrue(notes)

    def test_generator_split_keeps_yields_send_and_return(self):
        text = ("def gen(limit):\n    acc = []\n    received = []\n"
                "    got = yield 'start'\n    received.append(got)\n"
                + filler_lines(25) + "    for index in range(limit):\n"
                "        got = yield index\n        received.append(got)\n"
                + filler_lines(25) + "    if not limit:\n"
                "        return 'empty'\n    yield len(acc)\n"
                "    return received\n")
        new_text, _, names = self.split(text)
        self.assertEqual(names, ["gen"])
        self.assertIn("yield from _gen_part_", new_text)

        def drive(module, limit):
            generator, events = module.gen(limit), []
            try:
                events.append(next(generator))
                while True:
                    events.append(generator.send(len(events)))
            except StopIteration as stop:
                events.append(("return", stop.value))
            return events

        for limit in (0, 3):
            self.assertEqual(drive(load_module(text), limit),
                             drive(load_module(new_text), limit))
        original = load_module(text).gen(2)
        refined = load_module(new_text).gen(2)
        for generator in (original, refined):
            next(generator)
        with self.assertRaises(ValueError):
            original.throw(ValueError("x"))
        with self.assertRaises(ValueError):
            refined.throw(ValueError("x"))

    def test_coroutine_split_awaits_helpers(self):
        text = ("import asyncio\n\n\nasync def work(n):\n    acc = []\n"
                "    await asyncio.sleep(0)\n" + filler_lines(30)
                + "    if n < 0:\n        return 'negative'\n"
                + filler_lines(20) + "    await asyncio.sleep(0)\n"
                "    return n * 2, len(acc)\n")
        new_text, _, names = self.split(text)
        self.assertEqual(names, ["work"])
        self.assertIn("await _work_part_", new_text)
        import asyncio
        for value in (4, -1):
            self.assertEqual(
                asyncio.run(load_module(text).work(value)),
                asyncio.run(load_module(new_text).work(value)))

    def test_reading_local_before_binding_is_not_split(self):
        text = ("value = 'global'\n\n\ndef f(flag):\n    acc = []\n"
                "    if flag:\n        value = 'local'\n"
                + filler_lines(40) + "    return value, len(acc)\n")
        new_text, notes, names = self.split(text)
        original, refined = load_module(text), load_module(new_text)
        self.assertEqual(original.f(True), refined.f(True))
        with self.assertRaises(UnboundLocalError):
            refined.f(False)

    def test_guard_try_and_walrus_bindings_allow_splitting(self):
        # A handler that returns, and := in an if test, make later values
        # certain, so these functions can be split safely.
        text = ("def f(x, values):\n    acc = []\n    try:\n"
                "        ratio = 10 / x\n    except ZeroDivisionError:\n"
                "        return 'div0'\n"
                "    if (count := len(values)) > 1:\n"
                "        label = 'many'\n    else:\n        label = 'few'\n"
                + filler_lines(40) + "    return ratio, count, label, "
                "len(acc)\n")
        new_text, _, names = self.split(text)
        self.assertEqual(names, ["f"])
        original, refined = load_module(text), load_module(new_text)
        for args in ((2, [1, 2]), (0, []), (5, [1])):
            self.assertEqual(original.f(*args), refined.f(*args))

    def test_with_block_bindings_stay_uncertain(self):
        text = ("import contextlib\n\n\ndef f():\n    acc = []\n"
                "    with contextlib.suppress(ValueError):\n"
                "        value = int('x')\n" + filler_lines(40)
                + "    return value, len(acc)\n")
        new_text, notes, names = self.split(text)
        self.assertEqual(names, [])
        self.assertEqual(new_text, text)

    def test_long_loop_body_is_split_in_place(self):
        # The early return, the loop-carried total and the conditionally
        # changed label must all survive the split.
        text = ("def f(items):\n    acc = []\n    total = 0\n"
                "    label = 'none'\n    for item in items:\n"
                "        total = total + item\n" + filler_lines(22, " " * 8)
                + "        if item > 90:\n            return 'big', item\n"
                + filler_lines(22, " " * 8) + "        if item > 2:\n"
                "            label = 'high'\n"
                "    return total, label, len(acc)\n")
        new_text, _, names = self.split(text)
        self.assertEqual(names, ["f (loop body)"])
        self.assertIn("for item in items:", new_text)
        original, refined = load_module(text), load_module(new_text)
        for items in ([], [1], [1, 5], [5, 95, 1]):
            self.assertEqual(original.f(items), refined.f(items))
        for node in ast.walk(ast.parse(new_text)):
            if isinstance(node, ast.FunctionDef):
                self.assertLessEqual(node.end_lineno - node.lineno + 1, 50)

    def test_nested_loop_and_else_blocks_split(self):
        text = ("def f(rows, flag):\n    acc = []\n    if flag:\n"
                "        acc.append(0)\n    else:\n        acc.append(1)\n"
                "        for row in rows:\n            seen = 0\n"
                "            for cell in row:\n"
                + filler_lines(22, " " * 16) + "                seen += cell\n"
                + filler_lines(22, " " * 16)
                + "            acc.append(seen)\n    return acc[-3:], len(acc)\n")
        new_text, _, names = self.split(text)
        self.assertTrue(names)
        original, refined = load_module(text), load_module(new_text)
        for args in (([], True), ([[1, 2], [3]], False), ([], False)):
            self.assertEqual(original.f(*args), refined.f(*args))

    def test_unsafe_blocks_are_left_whole(self):
        loop = "def f(items):\n    acc = []\n    for item in items:\n"
        for middle in ("        if item:\n            break\n",
                       "        acc.append(lambda: item)\n",
                       "        if item:\n            acc.append(prev)\n"
                       "        prev = item\n"):
            with self.subTest(middle=middle):
                text = (loop + filler_lines(22, " " * 8) + middle
                        + filler_lines(22, " " * 8) + "    return len(acc)\n")
                new_text, notes, names = self.split(text)
                self.assertEqual(names, [])
                self.assertEqual(new_text, text)
                self.assertIn("loop body was not split either", notes[0])

    def test_documentation_is_honest_and_only_adds_docstrings(self):
        text = ("def area(radius: float, *, scale=1) -> float:\n"
                "    return 3.0 * radius * scale\n\n\n"
                "def one(): return 1\n\n\n"
                "class Box:\n    def __init__(self, size):\n"
                "        self.size = size\n")
        new_text, names = insert_docstrings_tuple(text, 79)
        self.assertEqual(names, ["area", "Box.__init__"])
        self.assertIn("radius (float): Not described in the original code.",
                      new_text)
        self.assertIn("scale (type not annotated)", new_text)
        self.assertIn("Initialize a Box instance.", new_text)
        self.assertIn("def one(): return 1", new_text)
        self.assertEqual(load_module(new_text).area(2), 6.0)


class RefineCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_refine_file_writes_new_file_and_refuses_existing(self):
        source = self.root / "mod.py"
        source.write_text(LONG_FUNCTION + "\n\n" + LONG_METHOD)
        report = refine_file_report(source, self.root / "out.py",
                                    options_info=RefineOptions(True, True))
        self.assertEqual(report.status, "written", report.diagnostics)
        self.assertEqual(len(report.split_functions), 2)
        self.assertEqual(source.read_text(), LONG_FUNCTION + "\n\n"
                         + LONG_METHOD)
        refined = load_module((self.root / "out.py").read_text())
        original = load_module(source.read_text())
        self.assertEqual(original.analyse([4, 8]), refined.analyse([4, 8]))
        again = refine_file_report(source, self.root / "out.py")
        self.assertEqual(again.status, "refused")

    def test_refine_folder_changes_only_long_files(self):
        project = self.root / "project"
        (project / "pkg").mkdir(parents=True)
        (project / "pkg" / "long.py").write_text(LONG_FUNCTION)
        (project / "pkg" / "short.py").write_text("def f():\n    return 1\n")
        (project / "data.txt").write_text("keep")
        result = subprocess.run(
            [sys.executable, "-m", "funcloom", "refine", str(project),
             "--output", str(self.root / "out"), "--no-document"],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.root / "out"
        self.assertEqual((out / "pkg" / "short.py").read_bytes(),
                         (project / "pkg" / "short.py").read_bytes())
        self.assertEqual((out / "data.txt").read_text(), "keep")
        self.assertNotEqual((out / "pkg" / "long.py").read_text(),
                            LONG_FUNCTION)
        self.assertFalse((out / "main.py").exists())

    def test_modularize_splits_long_merged_steps(self):
        body = "".join(f"total = total + {index}\n" for index in range(45))
        source = ("import random\nrandom.seed(1)\ntotal = 0\n"
                  "if random.random() > 2:\n    extra = 1\n" + body
                  + "print(total, 'extra' in dir())\n")
        path = self.root / "script.py"
        path.write_text(source)
        report = modularize_report(path, output_dir=self.root / "pkg_out")
        self.assertEqual(report.status, "written", report.diagnostics)
        expected = subprocess.run([sys.executable, str(path)],
                                  capture_output=True, text=True).stdout
        actual = subprocess.run([sys.executable, "main.py"],
                                cwd=self.root / "pkg_out",
                                capture_output=True, text=True).stdout
        self.assertEqual(actual, expected)
        steps = ast.parse((self.root / "pkg_out" / "script" / "steps.py")
                          .read_text())
        for node in steps.body:
            if isinstance(node, ast.FunctionDef):
                self.assertLessEqual(node.end_lineno - node.lineno + 1, 50)
