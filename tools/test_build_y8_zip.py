"""tools/build-y8-zip.py: allowlist, exclusions and reference checks."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'build_y8_zip', Path(__file__).with_name('build-y8-zip.py'))
bz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bz)

# index.html moved to GamePix and y8config.js is gone (TASK-102)
UNTIL_TASK_109 = unittest.skip('builder still targets Y8 until TASK-109')


class BuildY8ZipTest(unittest.TestCase):
    @UNTIL_TASK_109
    def test_zip_holds_only_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game.zip'
            bz.build(out)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            _, stats = bz.zip_report(out)
        self.assertIn('index.html', names)
        self.assertIn('y8config.js', names)
        self.assertIn('platform.js', names)
        self.assertNotIn('crazygames.js', names)
        self.assertTrue(all(stats['checks'].values()), stats['checks'])
        for name in names:
            self.assertTrue(name.endswith('.js') or name == 'index.html', name)
            top = name.split('/')[0]
            self.assertTrue('/' not in name or top in bz.FOLDERS, name)
            self.assertNotIn(top, bz.EXCLUDED)

    @UNTIL_TASK_109
    def test_every_index_reference_is_present(self):
        html = (bz.ROOT / 'index.html').read_text(encoding='utf-8')
        lines, errors = bz.check_references(html, bz.allowlisted_files())
        self.assertEqual(errors, [])
        external = [l for l in lines if 'external' in l]
        self.assertEqual(len(external), 1)
        self.assertIn(bz.SDK_URL, external[0])

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

    @UNTIL_TASK_109
    def test_valid_ids_pass(self):
        js = "const Y8_CONFIG = {appId: '6abfc17d100b7c96fc2d684e', gameId: '285775'}"
        self.assertEqual(bz.check_y8_config(js), [])
        self.assertEqual(bz.check_y8_config(
            (bz.ROOT / 'y8config.js').read_text(encoding='utf-8')), [])

    def test_missing_ids_fail(self):
        cases = {
            "const Y8_CONFIG = {}": ['appId: missing', 'gameId: missing'],
            "const Y8_CONFIG = {appId: '6abfc17d100b7c96fc2d684e'}": ['gameId: missing'],
        }
        for js, expected in cases.items():
            self.assertEqual(bz.check_y8_config(js), expected, js)

    def test_empty_and_placeholder_ids_fail(self):
        cases = [
            "{appId: '', gameId: '285775'}",
            "{appId: 'YOUR_APP_ID', gameId: '285775'}",
            "{appId: '6abfc17d100b7c96fc2d684e', gameId: 'YOUR_GAME_ID'}",
            "{appId: '6ABFC17D100B7C96FC2D684E', gameId: '285775'}",
        ]
        for js in cases:
            errors = bz.check_y8_config(js)
            self.assertEqual(len(errors), 1, js)
            self.assertIn('does not match', errors[0])

    def test_build_fails_on_placeholder_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'index.html').write_text(
                f'<script src="{bz.SDK_URL}"></script><script src="y8config.js"></script>')
            (root / 'y8config.js').write_text(
                "const Y8_CONFIG = {appId: 'YOUR_APP_ID', gameId: 'YOUR_GAME_ID'}")
            with self.assertRaises(SystemExit) as cm:
                bz.build(root / 'out.zip', root)
            self.assertIn('bad y8config.js', str(cm.exception))
            self.assertFalse((root / 'out.zip').exists())

    def test_excluded_names_are_detected(self):
        self.assertEqual(bz.excluded_hits(['tools/x.js', 'sprites/__pycache__/a.js',
                                           'README.md', 'sprites/ninja.js']),
                         ['tools/x.js', 'sprites/__pycache__/a.js', 'README.md'])


if __name__ == '__main__':
    unittest.main()
