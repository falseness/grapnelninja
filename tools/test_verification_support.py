"""Exercise the actual caller wrappers without launching their browser scripts."""

import ast
import contextlib
import importlib.util
import io
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from verification_support import assert_near, load_baseline_sources, baseline_route


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
        imports = [alias.name for n in tree.body if isinstance(n, ast.Import)
                   for alias in n.names]
        imports += [n.module for n in tree.body if isinstance(n, ast.ImportFrom)]
        self.assertTrue(all(name.split('.')[0] in sys.stdlib_module_names for name in imports))
        spec = importlib.util.spec_from_file_location('support_import_test', path)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        self.assertEqual(output.getvalue(), '')


class BaselineRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        previous = Path.cwd()
        os.chdir(temporary.name)
        self.addCleanup(os.chdir, previous)
        self.git('init', '-q')
        self.original = {'index.html': b'<html>baseline\r\n</html>',
                         'game.js': b'const baseline = "\xc3\xa9";\n'}
        for name, data in self.original.items():
            Path(name).write_bytes(data)
        Path('style.css').write_text('baseline CSS')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                 'commit', '-qm', 'baseline')
        self.revision = self.git('rev-parse', 'HEAD').decode().strip()
        Path('game.js').write_text('changed working tree')
        Path('index.html').unlink()
        self.files = self.git('ls-files').decode().splitlines()
        self.sources = load_baseline_sources(self.revision, self.files)

    def git(self, *args):
        return subprocess.check_output(['git', *args], stderr=subprocess.PIPE)

    def route(self, path):
        route = Mock()
        route.request.url = 'http://127.0.0.1:8035' + path
        baseline_route(self.sources)(route)
        return route

    def test_actual_baseline_bytes_and_explicit_file_selection(self):
        self.assertEqual(self.sources, self.original)
        self.assertEqual(load_baseline_sources(self.revision, ['game.js']),
                         {'game.js': self.original['game.js']})

    def test_root_html_and_html_mime(self):
        for path in ['/', '/index.html']:
            with self.subTest(path=path):
                route = self.route(path)
                route.fulfill.assert_called_once_with(
                    body=self.original['index.html'], content_type='text/html')
                route.fallback.assert_not_called()

    def test_javascript_and_javascript_mime(self):
        route = self.route('/game.js')
        route.fulfill.assert_called_once_with(
            body=self.original['game.js'], content_type='text/javascript')
        route.fallback.assert_not_called()

    def test_query_strings_preserve_root_html_and_javascript(self):
        for path, name, mime in [('/?v=1', 'index.html', 'text/html'),
                                 ('/index.html?v=2', 'index.html', 'text/html'),
                                 ('/game.js?v=3', 'game.js', 'text/javascript')]:
            with self.subTest(path=path):
                route = self.route(path)
                route.fulfill.assert_called_once_with(body=self.original[name], content_type=mime)
                route.fallback.assert_not_called()

    def test_unknown_asset_fallback(self):
        for path in ['/style.css', '/image.png?v=1', '/unknown.js', '/unknown.html']:
            with self.subTest(path=path):
                route = self.route(path)
                route.fallback.assert_called_once_with()
                route.fulfill.assert_not_called()

    def test_missing_baseline_source_failure(self):
        for name in ['missing.js', 'missing.html']:
            with self.subTest(name=name):
                with self.assertRaises(subprocess.CalledProcessError) as caught:
                    load_baseline_sources(self.revision, self.files + [name])
                self.assertNotEqual(caught.exception.returncode, 0)
                self.assertEqual(caught.exception.cmd, ['git', 'show', self.revision + ':' + name])
