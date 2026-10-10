"""tools/build-y8-zip.py: allowlist, exclusions and reference checks."""
import importlib.util
import subprocess
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'build_y8_zip', Path(__file__).with_name('build-y8-zip.py'))
bz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bz)


class BuildY8ZipTest(unittest.TestCase):
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

    def fixture(self, root):
        for name in bz.RUNTIME_FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bz.ROOT / name, path)
        self.git(root, 'init', '-q')
        self.commit(root)

    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root),
            '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
            '-c', 'user.name=Builder Test', '-c', 'user.email=test@example.invalid',
            *args], stderr=subprocess.STDOUT)

    def commit(self, root):
        self.git(root, 'add', '.')
        self.git(root, 'commit', '-qm', 'fixture')

    def test_build_fails_on_placeholder_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'y8config.js').write_text(
                "const Y8_CONFIG = {appId: 'YOUR_APP_ID', gameId: 'YOUR_GAME_ID'}")
            self.commit(root)
            with self.assertRaisesRegex(SystemExit, 'bad y8config.js'):
                bz.build(root / 'out.zip', root)
            self.assertFalse((root / 'out.zip').exists())

    def test_dirty_runtime_and_staged_changes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            path = root / 'platform.js'
            original = path.read_bytes()
            path.write_bytes(original + b'\n// dirty')
            with self.assertRaisesRegex(SystemExit, 'uncommitted runtime'):
                bz.build(root / 'out.zip', root)
            self.git(root, 'add', 'platform.js')
            path.write_bytes(original)
            with self.assertRaisesRegex(SystemExit, 'uncommitted runtime changes in index'):
                bz.build(root / 'out.zip', root)

    def test_unrelated_tracked_untracked_and_symlink_files_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            for name in ['test-probe.js', 'playgama.js', 'output/probe.js',
                         'artifacts/probe.js', 'screenshots/probe.js']:
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_text('unrelated')
            self.commit(root)
            (root / 'uncommitted-probe.js').write_text('uncommitted')
            (root / 'symlink-probe.js').symlink_to('/etc/hostname')
            bz.build(root / 'out.zip', root)
            with zipfile.ZipFile(root / 'out.zip') as archive:
                self.assertEqual(archive.namelist(), bz.RUNTIME_FILES)

    def test_runtime_symlink_and_parent_symlink_rejected(self):
        for committed in [False, True]:
            with self.subTest(committed=committed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.fixture(root)
                (root / 'platform.js').unlink()
                (root / 'platform.js').symlink_to('/etc/hostname')
                if committed:
                    self.commit(root)
                with self.assertRaisesRegex(SystemExit, 'unsafe'):
                    bz.build(root / 'out.zip', root)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            self.fixture(root)
            shutil.move(str(root / 'sprites'), outside + '/sprites')
            (root / 'sprites').symlink_to(outside + '/sprites')
            with self.assertRaisesRegex(SystemExit, 'unsafe symlink'):
                bz.build(root / 'out.zip', root)

    def test_missing_committed_file_and_non_git_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(SystemExit, 'committed Git source required'):
                bz.build(root / 'out.zip', root)
            self.fixture(root)
            self.git(root, 'rm', 'platform.js')
            self.commit(root)
            with self.assertRaisesRegex(SystemExit, 'missing committed runtime file'):
                bz.build(root / 'out.zip', root)

    def test_committed_missing_reference_and_charset_rejected(self):
        for change, error in [('<script src="missing.js"></script>', 'missing from the zip'),
                              ('no charset', 'UTF-8 declaration')]:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.fixture(root)
                path = root / 'index.html'
                path.write_text(path.read_text() + change if 'script' in change else change)
                self.commit(root)
                with self.assertRaisesRegex(SystemExit, error):
                    bz.build(root / 'out.zip', root)

    def test_excluded_names_are_detected(self):
        self.assertEqual(bz.excluded_hits(['tools/x.js', 'sprites/__pycache__/a.js',
                                           'README.md', 'sprites/ninja.js']),
                         ['tools/x.js', 'sprites/__pycache__/a.js', 'README.md'])


if __name__ == '__main__':
    unittest.main()
