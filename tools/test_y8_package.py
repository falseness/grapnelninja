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

    def test_manifest_flags_disagreeing_with_readiness_fail_package_check(self):
        readiness = {'60fps_achieved': True, 'submission_readiness': {'submission_ready': False}}
        manifest = {'60fps_achieved': False, 'submission_ready': False, 'uploaded': False}
        with self.assertRaises(SystemExit) as ctx:
            pkg.check_manifest_flags(manifest, readiness)
        self.assertIn('manifest readiness flags differ from readiness.json', str(ctx.exception))
        manifest['60fps_achieved'] = True
        self.assertEqual(pkg.check_manifest_flags(manifest, readiness),
                         {'60fps_achieved': True, 'submission_ready': False, 'uploaded': False})
        manifest['uploaded'] = True
        with self.assertRaises(SystemExit) as ctx:
            pkg.check_manifest_flags(manifest, readiness)
        self.assertIn('uploaded flag must be false', str(ctx.exception))

    def test_task_list_missing_a_scope_id_fails_readiness_naming_it(self):
        by_id = {i: {'id': i, 'status': 'done', 'description': 'x'} for i in pkg.SCOPE if i != 'TASK-283'}
        with self.assertRaises(SystemExit) as ctx:
            pkg.scope_tickets(by_id)
        self.assertIn('TASK-283', str(ctx.exception))
        self.assertIn('scope tickets missing', str(ctx.exception))
        by_id['TASK-283'] = {'id': 'TASK-283', 'status': 'done', 'description': 'x'}
        self.assertEqual([t['id'] for t in pkg.scope_tickets(by_id)], pkg.SCOPE)

    def test_ticket_audit_reads_status_and_implemented_note(self):
        row = pkg.ticket_audit({'id': 'TASK-000', 'status': 'done', 'description': 'Do a thing. More text. Implemented: did it.'})
        self.assertEqual(row['historical_result'], 'VERIFIED_EVIDENCE')
        self.assertEqual(row['implemented_note'], 'did it.')
        self.assertFalse(row['evidence_dir_present'])
        row = pkg.ticket_audit({'id': 'TASK-000', 'status': 'autoskip', 'description': 'x'})
        self.assertEqual(row['historical_result'], 'HISTORICAL_UNRESOLVED')


class EngineCoverage(unittest.TestCase):
    """TASK-294: the release suite must run on chromium, firefox and webkit, or record a reason for each engine it skipped."""

    def test_one_engine_without_note_fails_naming_the_missing_engines(self):
        with self.assertRaises(SystemExit) as ctx:
            pkg.require_engine_coverage(['chromium'], {}, 'release/results.json')
        message = str(ctx.exception)
        self.assertIn('neither run nor explained: firefox, webkit', message)
        self.assertIn('release/results.json', message)
        self.assertNotIn('chromium,', message.split('neither run nor explained:')[1].split('(')[0])
        self.assertEqual(pkg.engine_coverage(['chromium'], {}), ['firefox', 'webkit'])
        # two engines run, one silent -> only that one is named
        with self.assertRaises(SystemExit) as ctx:
            pkg.require_engine_coverage(['chromium', 'firefox'], {}, 'functional --engines')
        self.assertIn('neither run nor explained: webkit', str(ctx.exception))

    def test_one_engine_with_notes_passes_with_engines_not_run_populated(self):
        notes = pkg.parse_engine_notes(['firefox=no Gecko build on this host'], webkit_note='WPE bundle missing libavif')
        self.assertEqual(notes, {'firefox': 'no Gecko build on this host', 'webkit': 'WPE bundle missing libavif'})
        self.assertEqual(pkg.require_engine_coverage(['chromium'], notes, 'release/results.json'), [])
        self.assertEqual(pkg.engine_coverage(['chromium', 'firefox', 'webkit'], {}), [])
        # --engine-note alone (no --webkit-note alias) also explains webkit
        self.assertEqual(pkg.parse_engine_notes(['webkit=absent']), {'webkit': 'absent'})

    def test_bad_notes_and_contradictory_coverage_fail(self):
        for bad in (['webkit'], ['webkit='], ['opera=not a target'], ['=reason']):
            with self.assertRaises(SystemExit, msg=bad):
                pkg.parse_engine_notes(bad)
        with self.assertRaises(SystemExit) as ctx:  # run AND noted as not run
            pkg.engine_coverage(['chromium', 'webkit'], {'webkit': 'stale note'})
        self.assertIn('both run and noted as not run: webkit', str(ctx.exception))
        with self.assertRaises(SystemExit) as ctx:
            pkg.engine_coverage(['chromium', 'edge'], {})
        self.assertIn('unknown engines: edge', str(ctx.exception))


class MediaReview(unittest.TestCase):
    """TASK-295: --review is applied in the same run it is given, and a recorded verdict survives a plain re-run only
    while the captures stay byte-identical. No browser: a fake capture writes the 'assets' and a fake build_review
    hashes them."""

    def fakes(self, out, payloads, calls):
        def capture(out_dir):
            calls.append('capture')
            out_dir.mkdir(parents=True, exist_ok=True)
            for name, data in payloads.items():
                (out_dir / name).parent.mkdir(parents=True, exist_ok=True)
                (out_dir / name).write_bytes(data)
            (out_dir / 'media-manifest.json').write_text('{}')

        def build_review(out_dir):
            names = sorted(payloads)
            return dict(task='T', regenerated_assets=len(names), pixel_identical_to_historical='0/0',
                        assets=[dict(path=n, sha256=pkg.sha(out_dir / n)) for n in names if n.startswith('media/')],
                        source_frames=[dict(file=n, sha256=pkg.sha(out_dir / n)) for n in names if not n.startswith('media/')],
                        visual_review=pkg.REVIEW_PENDING, verdict='PENDING')
        return capture, build_review

    def run_media(self, out, note, payloads, calls):
        import contextlib
        import io
        capture, build_review = self.fakes(out, payloads, calls)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            review = pkg.run_media_review(out, note, capture, build_review)
        self.assertEqual(review, json.loads((out / 'media-review.json').read_text()))
        return review, buf.getvalue()

    def test_a_first_run_with_review_records_pass_in_the_same_run(self):
        with tempfile.TemporaryDirectory() as d:
            out, calls = Path(d) / 'media', []
            review, printed = self.run_media(out, 'PASS: contact sheet reviewed', {'media/a.png': b'A', 'f.png': b'F'}, calls)
            self.assertEqual(calls, ['capture'])
            self.assertEqual(review['verdict'], 'PASS')
            self.assertEqual(review['visual_review'], 'PASS: contact sheet reviewed')
            self.assertTrue(review['visual_review_utc'])
            self.assertFalse(review['review_carried_over'])
            self.assertNotIn('WARNING', printed)
            # a FAIL note is recorded as FAIL, also on the first run
            review, _ = self.run_media(Path(d) / 'media2', 'FAIL: title clipped', {'media/a.png': b'A'}, [])
            self.assertEqual(review['verdict'], 'FAIL')

    def test_b_plain_rerun_after_pass_keeps_the_verdict_with_carry_over_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            out, calls, payloads = Path(d) / 'media', [], {'media/a.png': b'A', 'f.png': b'F'}
            first, _ = self.run_media(out, 'PASS: reviewed', payloads, calls)
            second, printed = self.run_media(out, None, payloads, calls)
            self.assertEqual(calls, ['capture'])  # manifest present: no recapture
            self.assertEqual(second['verdict'], 'PASS')
            self.assertEqual(second['visual_review'], 'PASS: reviewed')
            self.assertTrue(second['review_carried_over'])
            self.assertEqual(second['review_carried_over_from_utc'], first['visual_review_utc'])
            self.assertEqual(second['visual_review_utc'], first['visual_review_utc'])
            self.assertNotIn('WARNING', printed)
            # a third plain run carries the same note again; a new note replaces it in the same run
            third, _ = self.run_media(out, None, payloads, calls)
            self.assertEqual(third['review_carried_over_from_utc'], first['visual_review_utc'])
            fourth, _ = self.run_media(out, 'FAIL: looked again', payloads, calls)
            self.assertEqual((fourth['verdict'], fourth['review_carried_over']), ('FAIL', False))
            self.assertNotIn('review_carried_over_from_utc', fourth)

    def test_recapture_with_different_bytes_resets_to_pending_with_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            out, calls = Path(d) / 'media', []
            first, _ = self.run_media(out, 'PASS: reviewed', {'media/a.png': b'A', 'f.png': b'F'}, calls)
            (out / 'media-manifest.json').unlink()  # force a recapture over the existing review
            second, printed = self.run_media(out, None, {'media/a.png': b'A', 'f.png': b'G'}, calls)
            self.assertEqual(calls, ['capture', 'capture'])
            self.assertEqual(second['verdict'], 'PENDING')
            self.assertEqual(second['visual_review'], pkg.REVIEW_PENDING)
            self.assertFalse(second['review_carried_over'])
            self.assertIn('f.png', second['review_reset_reason'])
            self.assertNotIn('media/a.png', second['review_reset_reason'])
            self.assertEqual(second['previous_review']['verdict'], 'PASS')
            self.assertEqual(second['previous_review']['visual_review_utc'], first['visual_review_utc'])
            self.assertIn('WARNING previous PASS visual review discarded', printed)
            self.assertIn('f.png', printed)
            # the pure rule on its own: a PENDING previous review carries nothing over
            review, warning = pkg.carry_over_review(dict(assets=[], source_frames=[], verdict='PENDING'),
                                                    dict(assets=[], source_frames=[], verdict='PENDING'))
            self.assertEqual((review['verdict'], review['review_carried_over'], warning), ('PENDING', False, None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
