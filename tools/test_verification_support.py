"""Exercise the actual caller wrappers without launching their browser scripts."""

import ast
import contextlib
import importlib.util
import io
import math
from pathlib import Path
import unittest

from verification_support import assert_near


class ComparisonTests:
    def compare(self, a, b):
        self.near(a, b, 'sample')

    def mismatch(self, a, b, path='sample'):
        with self.assertRaises(AssertionError) as caught:
            self.compare(a, b)
        self.assertEqual(caught.exception.args[0][0], path)

    def test_nested_structures_and_mismatch_path(self):
        self.compare({'items': [1, {'value': 2.0}, None, 'text']},
                     {'items': [1.0, {'value': 2}, None, 'text']})
        self.mismatch({'items': [1, {'value': 2}]},
                      {'items': [1, {'value': 3}]}, 'sample.items[1].value')

    def test_booleans_keep_scalar_equality(self):
        self.compare([True, False, True], [True, False, 1])
        self.mismatch(True, False)
        self.mismatch(True, 1 + self.rel_tol / 2)

    def test_inside_and_outside_absolute_tolerance(self):
        self.compare(0, self.abs_tol * .5)
        self.mismatch(0, self.abs_tol * 2)

    def test_inside_and_outside_relative_tolerance(self):
        self.compare(1e6, 1e6 * (1 + self.rel_tol * .5))
        self.mismatch(1e6, 1e6 * (1 + self.rel_tol * 2))

    def test_mismatched_keys_lengths_and_container_types(self):
        self.mismatch({'x': {}}, {'x': {'extra': 1}}, 'sample.x')
        self.mismatch({'x': []}, {'x': [1]}, 'sample.x')
        self.mismatch({'x': []}, {'x': {}}, 'sample.x')
        self.mismatch({'x': {}}, {'x': []}, 'sample.x')
        self.mismatch([1], ['1'], 'sample[0]')

    def test_nan(self):
        for a, b in [(math.nan, math.nan), (1, math.nan), (math.nan, 1)]:
            self.mismatch(a, b)

    def test_infinity_policy(self):
        for value in [math.inf, -math.inf]:
            if self.require_finite:
                self.mismatch(value, value)
            else:
                self.compare(value, value)
            self.mismatch(value, -value)
            self.mismatch(1, value)
            self.mismatch(value, 1)


# Extract only the wrapper AST: importing the CLI scripts would run browsers.
for name, rel_tol, abs_tol, finite in [
        ('gameplay', 1e-12, 1e-12, True),
        ('frame', 1e-9, 1e-8, True),
        ('viewport', 1e-12, 1e-10, False)]:
    source = Path(__file__).with_name(f'verify-{name}-percentages.py')
    tree = ast.parse(source.read_text())
    wrapper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'near')
    namespace = {'assert_near': assert_near}
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), str(source), 'exec'), namespace)
    globals()[name.title() + 'ComparisonTests'] = type(
        name.title() + 'ComparisonTests', (ComparisonTests, unittest.TestCase),
        dict(near=staticmethod(namespace['near']), rel_tol=rel_tol,
             abs_tol=abs_tol, require_finite=finite))


class ImportTests(unittest.TestCase):
    def test_import_safe_standard_library_only(self):
        path = Path(__file__).with_name('verification_support.py')
        tree = ast.parse(path.read_text())
        self.assertEqual([n.names[0].name for n in tree.body if isinstance(n, ast.Import)], ['math'])
        self.assertFalse(any(isinstance(n, ast.ImportFrom) for n in tree.body))
        spec = importlib.util.spec_from_file_location('support_import_test', path)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        self.assertEqual(output.getvalue(), '')
