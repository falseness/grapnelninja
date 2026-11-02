"""Tests for tools/scan_credential_values.py on a synthetic tree (no real credentials)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_credential_values as scv  # noqa: E402

SECRET = 'abcDEF1234567890secretvalue'
TARGET = 'someone/some-game'


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.creds = base / 'credentials.env'
        self.creds.write_text(f'# comment\nexport API_KEY="{SECRET}"\nTARGET={TARGET}\nSHORT=12\nEMPTY=\n')
        self.root = base / 'tree'
        (self.root / 'sub').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_01_parse(self):
        self.assertEqual(scv.read_credentials(self.creds), {'API_KEY': SECRET, 'TARGET': TARGET, 'SHORT': '12'})

    def test_02_clean_tree(self):
        (self.root / 'a.txt').write_text('nothing here, $TARGET and API_KEY by name only')
        out = self.root / 'key-scan.json'
        result = scv.scan(self.root, self.creds, out)
        self.assertTrue(result['clean'])
        self.assertEqual(result['variables_checked'], ['API_KEY', 'TARGET'])
        self.assertEqual(result['variables_skipped_short'], ['SHORT'])
        self.assertEqual(json.loads(out.read_text())['totals'], {'API_KEY': 0, 'TARGET': 0})

    def test_03_hits_in_files_and_zip_entries(self):
        (self.root / 'sub' / 'log.txt').write_text(f'push {TARGET}:html5 and {TARGET}')
        with zipfile.ZipFile(self.root / 'build.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('js/keys.js', f'var k = "{SECRET}"')
        out = self.root / 'key-scan.json'
        result = scv.scan(self.root, self.creds, out)
        self.assertFalse(result['clean'])
        self.assertEqual(result['totals'], {'API_KEY': 1, 'TARGET': 2})
        files = {hit['file'] for hit in result['hits']}
        self.assertEqual(files, {'sub/log.txt', 'build.zip!js/keys.js'})
        text = out.read_text()
        self.assertNotIn(SECRET, text)
        self.assertNotIn(TARGET, text)

    def test_04_exit_code(self):
        (self.root / 'a.txt').write_text('clean')
        self.assertEqual(scv.main([str(self.root), '--credentials', str(self.creds)]), 0)
        (self.root / 'b.txt').write_text(SECRET)
        self.assertEqual(scv.main([str(self.root), '--credentials', str(self.creds)]), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
