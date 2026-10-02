"""tools/build-crazygames-zip.py: allowlist, exclusions and reference checks."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'build_crazygames_zip', Path(__file__).with_name('build-crazygames-zip.py'))
bz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bz)


class BuildCrazyGamesZipTest(unittest.TestCase):
    def test_zip_holds_only_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game.zip'
            bz.build(out)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            _, stats = bz.zip_report(out)
        self.assertIn('index.html', names)
        self.assertIn('crazygames.js', names)
        self.assertTrue(all(stats['checks'].values()), stats['checks'])
        for name in names:
            self.assertTrue(name.endswith('.js') or name == 'index.html', name)
            top = name.split('/')[0]
            self.assertTrue('/' not in name or top in bz.FOLDERS, name)
            self.assertNotIn(top, bz.EXCLUDED)

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

    def test_excluded_names_are_detected(self):
        self.assertEqual(bz.excluded_hits(['tools/x.js', 'sprites/__pycache__/a.js',
                                           'README.md', 'sprites/ninja.js']),
                         ['tools/x.js', 'sprites/__pycache__/a.js', 'README.md'])


if __name__ == '__main__':
    unittest.main()
