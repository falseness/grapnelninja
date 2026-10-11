"""Cheap tests for tools/y8_package.py: decision separation, pixel comparison, ZIP inventory checks."""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_package as pkg  # noqa: E402


class Decision(unittest.TestCase):
    ALL_PASS = {'PASS': 10, 'FAIL': 0, 'UNVERIFIED': 0}

    def test_unverified_native_rows_keep_fps_false_even_with_prepared_package(self):
        v = pkg.decide(True, False, {'PASS': 0, 'FAIL': 0, 'UNVERIFIED': 10}, owner_checks_performed=True)
        self.assertFalse(v['60fps_achieved'])
        self.assertFalse(v['submission_ready'])
        self.assertTrue(any('native 60-FPS' in b for b in v['submission_blockers']))

    def test_outstanding_regression_keeps_fps_false_even_when_native_rows_pass(self):
        v = pkg.decide(True, True, self.ALL_PASS, owner_checks_performed=True)
        self.assertFalse(v['60fps_achieved'])
        self.assertTrue(any('regression' in b for b in v['submission_blockers']))

    def test_prepared_package_alone_never_means_performance_succeeded(self):
        v = pkg.decide(True, True, {'PASS': 0, 'FAIL': 0, 'UNVERIFIED': 10}, owner_checks_performed=False)
        self.assertFalse(v['60fps_achieved'])
        self.assertFalse(v['submission_ready'])
        self.assertEqual(len(v['submission_blockers']), 3)

    def test_fps_true_only_with_all_native_pass_and_no_regression(self):
        v = pkg.decide(True, False, self.ALL_PASS, owner_checks_performed=False)
        self.assertTrue(v['60fps_achieved'])
        self.assertFalse(v['submission_ready'])  # owner checks still outstanding
        v = pkg.decide(True, False, self.ALL_PASS, owner_checks_performed=True)
        self.assertTrue(v['submission_ready'])
        self.assertEqual(v['submission_blockers'], [])

    def test_failed_native_row_is_a_failure_not_unknown(self):
        v = pkg.decide(True, False, {'PASS': 9, 'FAIL': 1, 'UNVERIFIED': 0}, owner_checks_performed=True)
        self.assertFalse(v['60fps_achieved'])

    def test_unprepared_package_blocks_submission_without_touching_fps(self):
        v = pkg.decide(False, False, self.ALL_PASS, owner_checks_performed=True)
        self.assertTrue(v['60fps_achieved'])
        self.assertFalse(v['submission_ready'])
        self.assertEqual(v['submission_blockers'], ['functional package preparation incomplete'])


class Pixels(unittest.TestCase):
    def test_identical_and_differing_images(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            a, b, c = (Path(d) / n for n in ('a.png', 'b.png', 'c.png'))
            Image.new('RGB', (4, 4), (10, 20, 30)).save(a)
            Image.new('RGB', (4, 4), (10, 20, 30)).save(b)
            img = Image.new('RGB', (4, 4), (10, 20, 30))
            img.putpixel((1, 2), (10, 20, 33))
            img.save(c)
            same = pkg.pixel_compare(a, b)
            self.assertTrue(same['pixel_identical'])
            self.assertEqual(same['differing_pixels'], 0)
            diff = pkg.pixel_compare(a, c)
            self.assertFalse(diff['pixel_identical'])
            self.assertEqual(diff['differing_pixels'], 1)
            self.assertEqual(diff['max_channel_diff'], 3)
            Image.new('RGB', (5, 4)).save(b)
            self.assertFalse(pkg.pixel_compare(a, b)['same_dimensions'])


class Inventory(unittest.TestCase):
    def test_zip_inventory_rejects_unsafe_or_corrupt_members(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / 'good.zip'
            with zipfile.ZipFile(good, 'w') as z:
                z.writestr('index.html', '<meta charset="utf-8">')
                z.writestr('a/b.js', 'x')
            inv = pkg.zip_inventory(good, 'good')
            self.assertEqual(set(inv), {'index.html', 'a/b.js'})
            bad = Path(d) / 'bad.zip'
            with zipfile.ZipFile(bad, 'w') as z:
                z.writestr('../escape.js', 'x')
            with self.assertRaises(SystemExit):
                pkg.zip_inventory(bad, 'bad')
            corrupt = Path(d) / 'corrupt.zip'
            data = bytearray(good.read_bytes())
            data[len(data) // 4] ^= 0xFF  # flip a byte inside the stored member data
            corrupt.write_bytes(bytes(data))
            with self.assertRaises((SystemExit, zipfile.BadZipFile)):
                pkg.zip_inventory(corrupt, 'corrupt')

    def test_ticket_audit_reads_status_and_implemented_note(self):
        row = pkg.ticket_audit({'id': 'TASK-000', 'status': 'done', 'description': 'Do a thing. More text. Implemented: did it.'})
        self.assertEqual(row['historical_result'], 'VERIFIED_EVIDENCE')
        self.assertEqual(row['implemented_note'], 'did it.')
        self.assertFalse(row['evidence_dir_present'])
        row = pkg.ticket_audit({'id': 'TASK-000', 'status': 'autoskip', 'description': 'x'})
        self.assertEqual(row['historical_result'], 'HISTORICAL_UNRESOLVED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
