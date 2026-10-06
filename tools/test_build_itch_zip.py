"""tools/build-itch-zip.py: the HEAD build passes and every itch rule catches its bad tree."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('build_itch_zip', ROOT / 'tools' / 'build-itch-zip.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def page(*srcs):
    tags = ''.join(f'<script src="{s}"></script>' for s in srcs)
    return f'<!DOCTYPE html><html><head>{tags}</head><body></body></html>'.encode()


def good_tree():
    return {
        'index.html': page('game.js', 'sprites/ninja.js'),
        'game.js': b'var x = 1;',
        'sprites/ninja.js': b'var y = 2;',
        'README.md': b'# not shipped',
        'tools/build.py': b'print(1)',
    }


class BuildItchZipTest(unittest.TestCase):
    def assertFailsWith(self, tree, rule):
        blob, report = builder.build(tree)
        self.assertIsNone(blob)
        self.assertFalse(report['ok'])
        self.assertEqual(report['checks'][rule]['status'], 'FAIL', report['checks'])
        return report

    def test_good_synthetic_tree(self):
        blob, report = builder.build(good_tree())
        self.assertTrue(report['ok'], report['checks'])
        names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
        self.assertEqual(names, ['game.js', 'index.html', 'sprites/ninja.js'])

    def test_deterministic(self):
        self.assertEqual(builder.build(good_tree())[0], builder.build(good_tree())[0])

    def test_head_build_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'x.zip'
            proc = subprocess.run([sys.executable, str(ROOT / 'tools' / 'build-itch-zip.py'),
                                   '--out', str(out)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertIsNone(zf.testzip())
                for name in names:
                    blob = subprocess.run(['git', 'show', f'HEAD:{name}'], cwd=ROOT,
                                          check=True, capture_output=True).stdout
                    self.assertEqual(zf.read(name), blob, name)
        self.assertIn('index.html', names)
        for name in names:
            self.assertFalse(builder.is_excluded(name), name)

    def test_r1_missing_index(self):
        tree = good_tree()
        tree['game/index.html'] = tree.pop('index.html')
        self.assertFailsWith(tree, 'R1')

    def test_r3_too_many_files(self):
        tree = {f'f{i}.js': b'' for i in range(1001)}
        tree['index.html'] = page(*sorted(tree))
        self.assertFailsWith(tree, 'R3')

    def test_r3_limit_is_inclusive(self):
        tree = {f'f{i}.js': b'' for i in range(999)}
        tree['index.html'] = page(*sorted(tree))
        self.assertTrue(builder.build(tree)[1]['ok'])

    def test_r4_long_path(self):
        long = 'a' * 238 + '.js'
        self.assertEqual(len(long), 241)
        tree = {'index.html': page(long), long: b''}
        self.assertFailsWith(tree, 'R4')

    def test_r7_case_mismatch(self):
        tree = good_tree()
        tree['index.html'] = page('Game.js', 'sprites/ninja.js')
        report = self.assertFailsWith(tree, 'R7')
        self.assertIn('case mismatch', report['checks']['R7']['errors'][0])

    def test_r7_missing_file(self):
        tree = good_tree()
        del tree['sprites/ninja.js']
        report = self.assertFailsWith(tree, 'R7')
        self.assertIn('unresolved', report['checks']['R7']['errors'][0])

    def test_r7_missing_asset_string_in_js(self):
        tree = good_tree()
        tree['game.js'] = b'var img = "img/hero.png";'
        self.assertFailsWith(tree, 'R7')

    def test_r8_absolute_src(self):
        tree = good_tree()
        tree['index.html'] = page('/game.js', 'sprites/ninja.js')
        self.assertFailsWith(tree, 'R8')

    def test_r9_folder_reference(self):
        tree = good_tree()
        tree['index.html'] = page('game.js', 'sprites/ninja.js') + b'<link href="sprites/">'
        self.assertFailsWith(tree, 'R9')

    def test_r10_http_url(self):
        tree = good_tree()
        tree['index.html'] = page('http://example.com/lib.js', 'game.js')
        self.assertFailsWith(tree, 'R10')

    def test_r10_https_string_in_js(self):
        tree = good_tree()
        tree['game.js'] = b'fetch("https://example.com/score")'
        self.assertFailsWith(tree, 'R10')

    def test_r10_protocol_relative_string(self):
        tree = good_tree()
        tree['game.js'] = b'var u = "//cdn.example.com/a.js"; // a comment'
        self.assertFailsWith(tree, 'R10')

    def test_line_comment_is_not_external(self):
        tree = good_tree()
        tree['game.js'] = b'//ctx.fill()\nvar x = 1; //ctx.stroke()'
        self.assertTrue(builder.build(tree)[1]['ok'])

    def test_x1_excluded_reference(self):
        tree = good_tree()
        tree['tools/helper.js'] = b''
        tree['index.html'] = page('game.js', 'tools/helper.js')
        self.assertFailsWith(tree, 'X1')


if __name__ == '__main__':
    unittest.main()
