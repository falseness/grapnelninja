"""tools/build-playgama-zip.py: allowlist, exclusions and upload checks."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'build_playgama_zip', Path(__file__).with_name('build-playgama-zip.py'))
bz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bz)

SDK = f'<script src="{bz.SDK_URL}"></script>'
GOOD_HTML = f'<html><head>{SDK}<script src="a.js"></script></head><body></body></html>'


def good_texts():
    return {'index.html': GOOD_HTML, 'a.js': 'var a = 1;',
            bz.CONFIG_FILE: '{"advertisement": {}}'}


def failing(texts, sizes=None):
    sizes = sizes or {p: len(t) for p, t in texts.items()}
    return {name: errors for name, errors in bz.run_checks(texts, sizes) if errors}


class BuildPlaygamaZipTest(unittest.TestCase):
    def test_zip_holds_only_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game.zip'
            bz.build(out)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            _, stats = bz.zip_report(out)
        self.assertIn('index.html', names)
        self.assertIn(bz.CONFIG_FILE, names)
        self.assertIn('platform.js', names)
        self.assertNotIn('y8config.js', names)
        self.assertEqual(set(stats['checks'].values()), {'PASS'}, stats['errors'])
        for name in names:
            self.assertIn(Path(name).suffix, bz.ALLOWED_SUFFIXES, name)
            top = name.split('/')[0]
            self.assertTrue('/' not in name or top in bz.FOLDERS, name)
            self.assertNotIn(top, bz.EXCLUDED)

    def test_good_tree_passes_every_check(self):
        self.assertEqual(failing(good_texts()), {})

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
        for body, reason in cases.items():
            _, errors = bz.check_references(f'<head>{SDK}</head>{body}', paths)
            self.assertEqual(len(errors), 1, body)
            self.assertIn(reason, errors[0])

    def test_sdk_must_be_first_head_script(self):
        cases = {
            '<head><script src="a.js"></script></head>': 'found 0 times',
            f'<head><script src="a.js"></script>{SDK}</head>': 'not the first <head> script',
            f'<head><script>var x;</script>{SDK}</head>': 'not the first <head> script',
            f'<head></head><body>{SDK}</body>': 'not the first <head> script',
            f'<head>{SDK}{SDK}</head>': 'found 2 times',
        }
        for html, reason in cases.items():
            _, errors = bz.check_references(html, ['index.html', 'a.js'])
            self.assertEqual(len(errors), 1, html)
            self.assertIn(reason, errors[0])

    def test_missing_index_fails(self):
        texts = good_texts()
        del texts['index.html']
        self.assertIn('index.html at the zip root', failing(texts))

    def test_config_missing_or_invalid_fails(self):
        self.assertEqual(bz.check_bridge_config('{"a": 1}'), [])
        for text in ['{"a": 1,}', '', '[1, 2]']:
            self.assertEqual(len(bz.check_bridge_config(text)), 1, text)
        texts = good_texts()
        texts[bz.CONFIG_FILE] = '{bad'
        self.assertTrue(any('valid JSON' in n for n in failing(texts)))
        del texts[bz.CONFIG_FILE]
        self.assertTrue(any('valid JSON' in n for n in failing(texts)))

    def test_disallowed_suffixes_fail(self):
        self.assertEqual(bz.bad_suffixes(['a.js', 'b.json', 'index.html',
                                          'c.png', 'd.py', 'e.md', 'f']),
                         ['c.png', 'd.py', 'e.md', 'f'])
        texts = good_texts()
        texts['notes.txt'] = 'x'
        self.assertIn('only .html/.js/.json files', failing(texts))

    def test_excluded_names_are_detected(self):
        self.assertEqual(bz.excluded_hits(['tools/x.js', 'sprites/__pycache__/a.js',
                                           'README.md', 'sprites/ninja.js',
                                           'y8config.js', 'artifacts/a.json',
                                           'screenshots/s.js', '.git/HEAD',
                                           'build.py', 'sprites/notes.md']),
                         ['tools/x.js', 'sprites/__pycache__/a.js', 'README.md',
                          'y8config.js', 'artifacts/a.json', 'screenshots/s.js',
                          '.git/HEAD', 'build.py', 'sprites/notes.md'])

    def test_non_latin_names_fail(self):
        self.assertEqual(bz.non_latin_names(['sprites/ninja.js', 'a-b_c.js',
                                             'ниндзя.js', 'my file.js', 'é.js']),
                         ['ниндзя.js', 'my file.js', 'é.js'])
        texts = good_texts()
        texts['спрайт.js'] = 'x'
        self.assertIn('Latin file names [A-Za-z0-9._/-]', failing(texts))

    def test_analytics_hosts_fail(self):
        for snippet in ['https://www.googletagmanager.com/gtag/js',
                        'https://www.google-analytics.com/analytics.js',
                        "gtag('config', 'G-1')",
                        'https://mc.yandex.ru/metrika/tag.js',
                        'ym(1, "init"); // Metrika']:
            texts = good_texts()
            texts['a.js'] = snippet
            self.assertIn('no analytics hosts', failing(texts), snippet)

    def test_size_and_count_limits(self):
        texts = good_texts()
        sizes = {p: 1 for p in texts}
        sizes['a.js'] = bz.MAX_BYTES
        self.assertTrue(any(n.startswith('total size') for n in failing(texts, sizes)))
        for i in range(bz.MAX_FILES):
            texts[f'f{i}.js'] = ''
        self.assertTrue(any(n.startswith('file count') for n in failing(texts)))

    def test_build_fails_without_writing_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'index.html').write_text(
                '<head><script src="https://www.googletagmanager.com/gtag/js"></script></head>')
            (root / bz.CONFIG_FILE).write_text('{}')
            with self.assertRaises(SystemExit) as cm:
                bz.build(root / 'out.zip', root)
            self.assertIn('build checks failed', str(cm.exception))
            self.assertFalse((root / 'out.zip').exists())

    def test_default_out(self):
        self.assertEqual(bz.DEFAULT_OUT.relative_to(bz.ROOT).as_posix(),
                         'artifacts/TASK-128/grapnelninja-playgama.zip')

    def test_main_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rc = bz.main(['--out', str(tmp / 'g.zip'), '--stats', str(tmp / 's.json'),
                          '--refs', str(tmp / 'r.log'), '--listing', str(tmp / 'l.txt')])
            self.assertEqual(rc, 0)
            stats = json.loads((tmp / 's.json').read_text())
            refs = (tmp / 'r.log').read_text().splitlines()
        self.assertEqual(set(stats['checks'].values()), {'PASS'})
        self.assertEqual([l for l in refs if 'external' in l],
                         [f'script src={bz.SDK_URL}: external (Playgama Bridge CDN, allowed)'])


if __name__ == '__main__':
    unittest.main()
