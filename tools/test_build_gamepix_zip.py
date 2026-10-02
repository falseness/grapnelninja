"""tools/build-gamepix-zip.py: allowlist, exclusions and reference checks."""
import importlib.util
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'build_gamepix_zip', Path(__file__).with_name('build-gamepix-zip.py'))
bz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bz)

SDK_TAG = f'<script src="{bz.SDK_URL}"></script>'


def make_root(tmp, head, body=''):
    """Write a minimal game tree with index.html and a.js; return its root."""
    root = Path(tmp)
    (root / 'index.html').write_text(
        f'<!Doctype html><html><head>{head}</head><body>{body}</body></html>')
    (root / 'a.js').write_text('var a = 1;')
    for folder in bz.FOLDERS:
        (root / folder).mkdir()
    return root


class BuildGamePixZipTest(unittest.TestCase):
    def test_zip_holds_only_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game.zip'
            bz.build(out)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            _, stats = bz.zip_report(out)
        self.assertIn('index.html', names)
        self.assertIn('platform.js', names)
        self.assertNotIn('crazygames.js', names)
        self.assertEqual(set(stats['checks'].values()), {'PASS'}, stats['checks'])
        for name in names:
            self.assertTrue(name.endswith('.js') or name == 'index.html', name)
            self.assertFalse(name.endswith(('.py', '.md')), name)
            # no leftover platform config (TASK-102 removed the old one)
            self.assertFalse(name.endswith('config.js'), name)
            top = name.split('/')[0]
            self.assertTrue('/' not in name or top in bz.FOLDERS, name)
            for excluded in ('tools', 'artifacts', 'screenshots', '.git'):
                self.assertNotEqual(top, excluded, name)

    def test_every_index_reference_is_present(self):
        html = (bz.ROOT / 'index.html').read_text(encoding='utf-8')
        lines, errors = bz.check_references(html, bz.allowlisted_files())
        self.assertEqual(errors, [])
        external = [l for l in lines if 'external' in l]
        self.assertEqual(len(external), 1)
        self.assertIn(bz.SDK_URL, external[0])
        self.assertEqual(bz.check_sdk_tag(html), [])

    def test_bad_references_fail(self):
        paths = ['index.html', 'a.js']
        cases = {
            '<script src="b.js"></script>': 'missing from the zip',
            '<script src="/a.js"></script>': 'absolute path',
            '<script src="https://cdn.example.com/x.js"></script>': 'non-relative URL',
            '<link rel="stylesheet" href="//cdn.example.com/x.css">': 'non-relative URL',
        }
        for html, reason in cases.items():
            _, errors = bz.check_references(html, paths)
            self.assertEqual(len(errors), 1, html)
            self.assertIn(reason, errors[0])

    def test_build_fails_on_injected_external_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, SDK_TAG + '<script src="a.js"></script>'
                             '<script src="https://cdn.example.com/x.js"></script>')
            with self.assertRaises(SystemExit) as cm:
                bz.build(root / 'out.zip', root)
            self.assertIn('non-relative URL', str(cm.exception))
            self.assertFalse((root / 'out.zip').exists())

    def test_build_fails_on_missing_referenced_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, SDK_TAG + '<script src="a.js"></script>'
                             '<script src="sprites/gone.js"></script>')
            with self.assertRaises(SystemExit) as cm:
                bz.build(root / 'out.zip', root)
            self.assertIn('sprites/gone.js: missing from the zip', str(cm.exception))
            self.assertFalse((root / 'out.zip').exists())

    def test_build_fails_when_sdk_is_not_the_first_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, '<script src="a.js"></script>' + SDK_TAG)
            with self.assertRaises(SystemExit) as cm:
                bz.build(root / 'out.zip', root)
            self.assertIn('bad GamePix SDK tag', str(cm.exception))
            self.assertFalse((root / 'out.zip').exists())

    def test_sdk_tag_rules(self):
        ok = f'<head><title>x</title>{SDK_TAG}<script src="a.js"></script></head>'
        self.assertEqual(bz.check_sdk_tag(ok), [])
        cases = {
            '<head><script src="a.js"></script></head>': 'not ' + bz.SDK_URL,
            '<head><script>var x;</script>' + SDK_TAG + '</head>': 'not ' + bz.SDK_URL,
            f'<head><script async src="{bz.SDK_URL}"></script></head>': 'async',
            f'<head><script defer src="{bz.SDK_URL}"></script></head>': 'defer',
            '<head></head><body>' + SDK_TAG + '</body>': 'no <script> in <head>',
        }
        for html, reason in cases.items():
            errors = bz.check_sdk_tag(html)
            self.assertEqual(len(errors), 1, html)
            self.assertIn(reason, errors[0], html)

    def test_build_succeeds_on_a_minimal_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, SDK_TAG + '<script src="a.js"></script>')
            (root / 'notes.md').write_text('x')
            (root / 'tools').mkdir()
            (root / 'tools' / 'x.js').write_text('x')
            shutil.copy(__file__, root / 'sprites' / 'helper.py')
            zip_paths, ref_lines = bz.build(root / 'out.zip', root)
            self.assertEqual(zip_paths, ['a.js', 'index.html'])
            self.assertEqual(len(ref_lines), 2)

    def test_excluded_names_are_detected(self):
        self.assertEqual(bz.excluded_hits(['tools/x.js', 'sprites/__pycache__/a.js',
                                           'README.md', 'sprites/ninja.js']),
                         ['tools/x.js', 'sprites/__pycache__/a.js', 'README.md'])


if __name__ == '__main__':
    unittest.main()
