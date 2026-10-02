"""Behavioral regression matrix: authored programs per language feature.

Each program is run as written, after modularize (script and notebook
form) and after refine (with functions long enough to be split). A
written result must print exactly what the original prints; a refusal
must name a diagnostic code and a source line. Only these authored
fixtures are executed; FuncLoom itself never runs analysed code.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from funcloom.modularize import modularize_report
from funcloom.refine import RefineOptions, refine_file_report

PROGRAMS_DICT = {
    "decorators": '''
        import functools

        CALLS = []


        def traced(function):
            @functools.wraps(function)
            def wrapper(*arguments, **keywords):
                CALLS.append(function.__name__)
                return function(*arguments, **keywords)
            return wrapper


        REGISTRY = {}


        def register(cls):
            REGISTRY[cls.__name__] = cls
            return cls


        @register
        class Meter:
            def __init__(self, reading):
                self._reading = reading

            @property
            def doubled(self):
                return self._reading * 2

            @staticmethod
            def unit():
                return "kWh"

            @classmethod
            def zero(cls):
                return cls(0)


        @traced
        def scale(value, factor=3):
            return value * factor

        # Use the decorated objects
        first = scale(4)
        second = scale(5, factor=2)
        meter = Meter(21)
        print(first, second, meter.doubled, Meter.unit(), Meter.zero().doubled)

        # Report what the decorators recorded
        print(CALLS, sorted(REGISTRY), scale.__name__)
    ''',
    "inheritance": '''
        from abc import ABC, abstractmethod

        PLUGINS = []


        class Shape(ABC):
            def __init_subclass__(cls, **keywords):
                super().__init_subclass__(**keywords)
                PLUGINS.append(cls.__name__)

            @abstractmethod
            def area(self):
                raise NotImplementedError

            def describe(self):
                return f"{type(self).__name__}:{self.area():.2f}"


        class Rectangle(Shape):
            def __init__(self, width, height):
                self.width, self.height = width, height

            def area(self):
                return self.width * self.height


        class Square(Rectangle):
            def __init__(self, side):
                super().__init__(side, side)

        # Build shapes
        shapes = [Rectangle(2, 3.5), Square(4)]
        print([shape.describe() for shape in shapes])

        # Inspect the hierarchy
        print(PLUGINS, [cls.__name__ for cls in Square.__mro__])
        try:
            Shape()
        except TypeError:
            print("abstract base refused")
    ''',
    "exceptions": '''
        import contextlib


        class BudgetError(ValueError):
            pass


        def spend(balance, amount):
            if amount > balance:
                raise BudgetError(f"short by {amount - balance}")
            return balance - amount


        class Ledger:
            def __init__(self):
                self.entries = []

            def __enter__(self):
                self.entries.append("open")
                return self

            def __exit__(self, kind, error, trace):
                self.entries.append("closed" if kind is None else "rolled back")
                return False

        # Normal flow with else and finally
        log = []
        try:
            remaining = spend(10, 4)
        except BudgetError as error:
            log.append(str(error))
        else:
            log.append(f"left {remaining}")
        finally:
            log.append("checked")

        # Failure flow, chaining and suppression
        try:
            try:
                spend(3, 9)
            except BudgetError as error:
                raise RuntimeError("payment failed") from error
        except RuntimeError as error:
            log.append(f"{error} <- {error.__cause__}")
        with contextlib.suppress(KeyError):
            {}["missing"]
        with Ledger() as ledger:
            ledger.entries.append("posted")
        print(log, ledger.entries)
    ''',
    "mutation": '''
        counter = [0]
        totals = {"north": 0, "south": 0}
        history = []


        def bump(state, step):
            state[0] += step
            return state[0]

        # Mutate shared containers
        for region, amount in [("north", 5), ("south", 7), ("north", 1)]:
            totals[region] += amount
            history.append((region, bump(counter, amount)))
        alias = history
        alias.append(("audit", counter[0]))

        # Rebind, delete and augment
        snapshot = dict(totals)
        totals["south"] *= 2
        del snapshot["north"]
        values = [1, 2, 3]
        values[1:2] = [20, 21]
        values += [4]
        print(counter, totals, snapshot, history[-1], values)
    ''',
    "imports": '''
        import math
        import os.path as osp
        from collections import Counter, OrderedDict as Ordered

        try:
            import tomllib as toml_reader
        except ImportError:
            toml_reader = None

        # Use early imports
        words = "red green red blue green red".split()
        counts = Counter(words)
        print(round(math.tau, 3), osp.basename("a/b/c.txt"),
              counts.most_common(1))

        # Import later in the script
        import statistics
        from fractions import Fraction

        ordered = Ordered(sorted(counts.items()))
        print(statistics.mean([1, 2, 6]), Fraction(3, 9), list(ordered),
              toml_reader is not None)
    ''',
    "async_generators": '''
        import asyncio


        def countdown(start):
            while start > 0:
                yield start
                start -= 1


        def chained():
            yield from countdown(2)
            yield "lift-off"


        async def fetch(name, delay):
            await asyncio.sleep(delay)
            return name.upper()


        async def ticker(limit):
            for index in range(limit):
                await asyncio.sleep(0)
                yield index * index


        async def collect():
            results = await asyncio.gather(fetch("a", 0.01), fetch("b", 0))
            squares = [value async for value in ticker(4)]
            return results, squares

        # Generators
        print(list(chained()))

        # Coroutines
        print(asyncio.run(collect()))
    ''',
    "closures_scoping": '''
        def make_counter(start):
            count = start

            def step(amount=1):
                nonlocal count
                count += amount
                return count
            return step


        handlers = [lambda value, scale=scale: value * scale
                    for scale in range(3)]

        # Closures and default-argument binding
        tick = make_counter(10)
        tick()
        print(tick(5), [handler(2) for handler in handlers])

        # Walrus and comprehension scopes
        data = [3, 8, 1, 9]
        if (largest := max(data)) > 5:
            print("largest", largest)
        evens = {value: value % 2 == 0 for value in data}
        running = 0
        print(evens, [running := running + value for value in data][-1],
              running)
    ''',
}

REFUSED_PROGRAMS_DICT = {
    "wildcard_import": ("from math import *\n\nprint(floor(2.5))\n",
                        "MOD004"),
    "effectful_annotation": ('limit: print("annotating") = 3\n'
                             "print(limit)\n", "MOD010"),
    "global_rebinding": ("counter = 0\n\n\ndef bump(step):\n"
                         "    global counter\n    counter += step\n\n"
                         "bump(2)\nprint(counter)\n", "MOD003"),
}

LONG_FUNCTIONS_DICT = {
    "long_loop_with_mutation": '''
        def summarize(values):
            totals = {"even": 0, "odd": 0}
            trace = []
        {body}
            for value in values:
                key = "even" if value % 2 == 0 else "odd"
                totals[key] += value
                trace.append(key[0])
            return totals, "".join(trace), accumulated


        print(summarize(range(12)))
    ''',
    "long_generator": '''
        def produce(limit):
            accumulated = 0
        {body}
            for index in range(limit):
                yield index + accumulated


        print(list(produce(4)))
    ''',
    "long_coroutine": '''
        import asyncio


        async def gather_numbers():
            accumulated = 0
        {body}
            await asyncio.sleep(0)
            return accumulated


        print(asyncio.run(gather_numbers()))
    ''',
    "long_method_with_try": '''
        class Account:
            def __init__(self):
                self.balance = 0

            def settle(self, payments):
                accumulated = 0
        {body}
                for payment in payments:
                    try:
                        if payment < 0:
                            raise ValueError(payment)
                        self.balance += payment
                    except ValueError as error:
                        self.balance -= 1
                        last_error = str(error)
                return self.balance + accumulated, last_error


        print(Account().settle([5, -2, 7]))
    ''',
}


def build_long_body_str(indent_int: int, count_int: int = 60) -> str:
    """Return many simple statements that make a function long.

    Args:
        indent_int (int): Spaces before each statement.
        count_int (int): Number of statements.
    Returns:
        str: Statement lines updating a local accumulator.
    Warnings:
        The program must define `accumulated` before the body.
    """
    pad_str = " " * indent_int
    lines_list = [f"{pad_str}accumulated = accumulated + {index_int} % 7"
                  for index_int in range(count_int)]
    if indent_int == 4:
        lines_list.insert(0, f"{pad_str}accumulated = 0")
    return "\n".join(lines_list)


def run_output_str(folder_path: Path, *arguments: str) -> str:
    """Run an authored fixture and return its standard output.

    Args:
        folder_path (Path): Working folder.
        *arguments (str): Script path and arguments.
    Returns:
        str: Captured output.
    Warnings:
        Fails the test on a non-zero exit, showing standard error.
    """
    result = subprocess.run([sys.executable, *arguments], cwd=folder_path,
                            capture_output=True, text=True, timeout=60,
                            check=False)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


def make_notebook_str(source_str: str) -> str:
    """Turn a commented script into notebook cells, one per section.

    Args:
        source_str (str): Program text with "# " section comments.
    Returns:
        str: Notebook JSON.
    Warnings:
        Definitions stay in the first cell, as in a typical notebook.
    """
    cells_list, current_list = [], []
    for line_str in source_str.splitlines(keepends=True):
        if line_str.startswith("# ") and current_list:
            cells_list.append(current_list)
            current_list = []
        current_list.append(line_str)
    cells_list.append(current_list)
    return json.dumps({"nbformat": 4, "nbformat_minor": 5,
                       "metadata": {"kernelspec": {"language": "python"}},
                       "cells": [{"cell_type": "code", "metadata": {},
                                  "execution_count": None, "outputs": [],
                                  "source": cell_list}
                                 for cell_list in cells_list]})


class BehaviorMatrixTests(unittest.TestCase):
    """Every supported transformation keeps the authored output."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write_program(self, name: str, source: str) -> tuple[Path, str]:
        folder = self.root / name
        folder.mkdir()
        path = folder / "program.py"
        path.write_text(source, encoding="utf-8")
        return path, run_output_str(folder, "program.py")

    def assert_written_or_explained(self, report, output_path: Path,
                                    expected: str, entry: str) -> str:
        if report.status == "written":
            self.assertEqual(run_output_str(output_path, entry), expected)
            return "written"
        self.assertTrue(report.diagnostics, report)
        for diagnostic in report.diagnostics:
            self.assertTrue(diagnostic.code)
            self.assertGreaterEqual(diagnostic.line or 0, 1)
        return "refused"

    def test_modularize_scripts_keep_behavior(self):
        outcomes = {}
        for name, program in PROGRAMS_DICT.items():
            with self.subTest(program=name):
                source = textwrap.dedent(program).lstrip()
                path, expected = self.write_program(name, source)
                output_path = self.root / f"{name}_package"
                report = modularize_report(path, output_dir=output_path)
                outcomes[name] = self.assert_written_or_explained(
                    report, output_path, expected, "main.py")
                self.assertEqual(path.read_text(encoding="utf-8"), source)
        # Every feature program is supported today; a new refusal must
        # be a deliberate, reviewed change to this expectation.
        self.assertEqual(set(outcomes.values()), {"written"}, outcomes)

    def test_modularize_notebooks_keep_behavior(self):
        for name, program in PROGRAMS_DICT.items():
            with self.subTest(program=name):
                source = textwrap.dedent(program).lstrip()
                _, expected = self.write_program(name, source)
                notebook = self.root / f"{name}.ipynb"
                notebook.write_text(make_notebook_str(source),
                                    encoding="utf-8")
                output_path = self.root / f"{name}_notebook_package"
                report = modularize_report(notebook, output_dir=output_path)
                self.assertEqual(self.assert_written_or_explained(
                    report, output_path, expected, "main.py"), "written")

    def test_unsupported_programs_are_refused_with_location(self):
        for name, (source, code) in REFUSED_PROGRAMS_DICT.items():
            with self.subTest(program=name):
                path = self.root / f"{name}.py"
                path.write_text(source, encoding="utf-8")
                output_path = self.root / f"{name}_package"
                report = modularize_report(path, output_dir=output_path)
                self.assertNotEqual(report.status, "written")
                self.assertIn(code, [item.code for item in
                                     report.diagnostics])
                self.assertFalse(output_path.exists())

    def test_refine_splits_long_functions_and_keeps_behavior(self):
        for name, template in LONG_FUNCTIONS_DICT.items():
            with self.subTest(program=name):
                indent_int = 8 if "class " in template else 4
                source = textwrap.dedent(template).lstrip().replace(
                    "{body}", build_long_body_str(indent_int))
                path, expected = self.write_program(name, source)
                output_file = self.root / f"{name}_refined.py"
                report = refine_file_report(path, output_file,
                                            options_info=RefineOptions())
                self.assertTrue(output_file.exists(), report)
                self.assertTrue(report.split_functions, report)
                self.assertEqual(run_output_str(self.root, output_file.name),
                                 expected)


if __name__ == "__main__":
    unittest.main()
