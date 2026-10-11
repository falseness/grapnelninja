"""Tests for the 60-FPS readiness evaluator (TASK-284): synthetic exports that
pass benchtool's integrity validation and exercise every verdict path:
passing, slow-average, bad-10-second-window, bad-p95, invalid-gap (unexplained
null interval and interval != timestamp difference), insufficient-duration,
wrong-build; plus density-reduced quality, emulation, explained pause gap,
device classification and the decision rule (60fps_achieved only when every
required native row is PASS).

Environment: BENCH_PACKAGE = built package root (artifacts/TASK-283/runner);
without it a package is built from the enclosing checkout into a temp dir.
"""
import copy
import json
import os
import random
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import benchtool as bt  # noqa: E402
import evaluate as ev  # noqa: E402
from test_bench_runner import make_result, make_run, package_root, synthetic_frames, log  # noqa: E402

FPS60 = 1000 / 60


def frames_for(run_ms=60000, dt=FPS60, warmup_ms=5000, slack=5):
    return synthetic_frames(int((warmup_ms + run_ms) / dt) + slack, dt=dt)


def frames_from_dts(dts, t0=1000.0):
    frames, t = [[t0, None]], t0
    for d in dts:
        t += d
        frames.append([t, d])
    return frames


_CACHE = {}


def cached_result(pkg, modes, frames, emulation):
    """make_result is slow (benchtool.verdict_inputs per run); reuse a deep copy per distinct fixture."""
    key = (id(frames), tuple(modes), emulation)
    if key not in _CACHE:
        build = json.loads((pkg / 'game' / 'build.json').read_text())
        _CACHE[key] = make_result(build=build, emulation=emulation, frames=frames, modes=modes)
    return copy.deepcopy(_CACHE[key])


def native_result(pkg, target='desktop', devtools='closed', modes=('bad', 'bad', 'bad', 'classic', 'classic', 'classic'),
                  frames=None, emulation='none', density_reduced=False, dpr=1):
    r = cached_result(pkg, modes, frames, emulation)
    ua = {'desktop': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
          'android-chrome': 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36',
          'iphone-safari': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'}[target]
    r['device'].update({'user_agent': ua, 'model_supplied': {'desktop': 'Test desktop i7 / RTX', 'android-chrome': 'Pixel 8',
                                                             'iphone-safari': 'iPhone 15'}[target],
                        'max_touch_points': 0 if target == 'desktop' else 5,
                        'os_family_detected': {'desktop': 'Windows', 'android-chrome': 'Android', 'iphone-safari': 'iOS'}[target],
                        'browser_family_detected': 'Safari' if target == 'iphone-safari' else 'Chrome'})
    r['settings']['devtools'] = devtools
    r['display']['dpr'] = dpr
    for run in r['runs']:
        run['dimensions_at_start']['dpr'] = dpr
        run['dimensions_at_end']['dpr'] = dpr
        if density_reduced:
            run['backing']['changes'] = [{'frame': 10, 'backing': [960, 540], 'density_limit': 0.75}]
            run['verdict_inputs']['backing_constant'] = False
    return r


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pkg = package_root()
        cls.tmp = Path(tempfile.mkdtemp(prefix='eval-'))

    def write(self, name, doc):
        p = self.tmp / name
        p.write_text(json.dumps(doc))
        return p

    def row(self, acc, key):
        return next(r for r in acc['rows'] if r['row'] == key)

    def test_passing_rows(self):
        p = self.write('passing.json', native_result(self.pkg))
        acc, dec = ev.evaluate([p], self.pkg)
        for mode in ('bad', 'classic'):
            row = self.row(acc, f'desktop/closed/{mode}')
            self.assertEqual(row['verdict'], 'PASS', row['reason'])
            self.assertEqual(row['valid_repetitions'], 3)
            m = row['repetitions'][0]['metrics']
            self.assertGreaterEqual(m['average_fps'], 58)
            self.assertGreaterEqual(m['rolling_10s_min_fps'], 55)
            self.assertLessEqual(m['frame_ms']['p95'], 33.3)
            self.assertGreaterEqual(m['active_ms'], 60000)
        self.assertFalse(dec['60fps_achieved'], 'other rows are UNVERIFIED so the decision must stay false')
        self.assertTrue(dec['evaluation_completed'])
        self.assertEqual(dec['counts'], {'PASS': 2, 'FAIL': 0, 'UNVERIFIED': 8})
        log('passing: desktop/closed bad+classic PASS 3/3 reps each; avg %.2f fps, min10s %.2f, p95 %.2f ms; 60fps_achieved=%s (8 rows UNVERIFIED)'
            % (m['average_fps'], m['rolling_10s_min_fps'], m['frame_ms']['p95'], dec['60fps_achieved']))

    def test_slow_average(self):
        frames = frames_for(dt=1000 / 57)  # 57 FPS steady: windows 57 >= 55 and p95 17.5 ms pass, only the average fails
        p = self.write('slow-average.json', native_result(self.pkg, modes=('bad', 'bad', 'bad'), frames=frames))
        acc, dec = ev.evaluate([p], self.pkg)
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['verdict'], 'FAIL', row['reason'])
        self.assertEqual(row['valid_repetitions'], 3)
        failed = row['repetitions'][0]['thresholds_failed']
        self.assertEqual(len(failed), 1, failed)
        self.assertIn('average_fps', failed[0])
        self.assertFalse(dec['60fps_achieved'])
        log('slow-average: FAIL', failed)

    def test_bad_10_second_window(self):
        # 10 s at 54 FPS inside 60 s at 60 FPS: average 58.9 >= 58 and p95 18.5 ms pass; one stretch of windows < 55
        dts = [FPS60] * int(5000 / FPS60 + 1) + [FPS60] * 1500 + [1000 / 54] * 540 + [FPS60] * 1800
        p = self.write('bad-window.json', native_result(self.pkg, modes=('bad', 'bad', 'bad'), frames=frames_from_dts(dts)))
        acc, dec = ev.evaluate([p], self.pkg)
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['verdict'], 'FAIL', row['reason'])
        rep = row['repetitions'][0]
        self.assertGreaterEqual(rep['metrics']['average_fps'], 58)
        self.assertLess(rep['metrics']['rolling_10s_min_fps'], 55)
        self.assertEqual(len(rep['thresholds_failed']), 1, rep['thresholds_failed'])
        self.assertIn('rolling 10 s window', rep['thresholds_failed'][0])
        log('bad-10-second-window: FAIL avg %.2f min10s %.2f windows<55: %d' % (
            rep['metrics']['average_fps'], rep['metrics']['rolling_10s_min_fps'], rep['metrics']['rolling_10s_windows_below_min']))

    def test_bad_p95(self):
        # 120 Hz-like cadence with 6 % of frames at 35 ms: average ~100 FPS and every window >= 55 pass; p95 = 35 ms fails
        base, n = 1000 / 120, int(65000 / (1000 / 120)) + 20
        dts = [35.0 if i % 50 < 3 else base for i in range(n)]
        p = self.write('bad-p95.json', native_result(self.pkg, modes=('bad', 'bad', 'bad'), frames=frames_from_dts(dts)))
        acc, dec = ev.evaluate([p], self.pkg)
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['verdict'], 'FAIL', row['reason'])
        rep = row['repetitions'][0]
        self.assertGreater(rep['metrics']['frame_ms']['p95'], 33.3)
        self.assertEqual(len(rep['thresholds_failed']), 1, rep['thresholds_failed'])
        self.assertIn('p95', rep['thresholds_failed'][0])
        log('bad-p95: FAIL avg %.2f fps, p95 %.2f ms' % (rep['metrics']['average_fps'], rep['metrics']['frame_ms']['p95']))

    def test_invalid_gap_unexplained_null_interval(self):
        # frames dropped: a null interval in the measured region with no inactive-state sample -> repetition rejected
        frames = synthetic_frames(int(66000 / FPS60), gap_after=2000, gap_ms=3000.0)
        p = self.write('invalid-gap.json', native_result(self.pkg, modes=('bad', 'bad', 'bad'), frames=frames))
        acc, dec = ev.evaluate([p], self.pkg)
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['verdict'], 'UNVERIFIED', row['reason'])
        self.assertEqual(row['valid_repetitions'], 0)
        self.assertEqual(len(row['rejected_attempts']), 3)
        self.assertIn('without a recorded inactive state', row['rejected_attempts'][0]['reasons'][0])
        log('invalid-gap (unexplained null interval): rejected ->', row['rejected_attempts'][0]['reasons'][0][:90])

    def test_invalid_gap_interval_not_equal_timestamp_difference(self):
        # a frame whose interval understates the timestamp difference (slow frame hidden) -> integrity rejection
        doc = native_result(self.pkg, modes=('bad', 'bad', 'bad'))
        run = doc['runs'][1]
        run['frames'][2500][1] = run['frames'][2500][1] - 5.0
        run['frames_sha256'] = bt.sha_canonical(run['frames'])
        p = self.write('invalid-gap-arith.json', doc)
        acc, dec = ev.evaluate([p], self.pkg)
        e = acc['result_files'][0]
        self.assertFalse(e['eligible'])
        self.assertTrue(any('interval does not equal timestamp difference' in r for r in e['ineligible_reasons']), e['ineligible_reasons'])
        self.assertEqual(self.row(acc, 'desktop/closed/bad')['verdict'], 'UNVERIFIED')
        log('invalid-gap (interval != timestamp difference): file rejected ->', [r for r in e['ineligible_reasons'] if 'interval' in r])

    def test_explained_pause_gap_is_accepted(self):
        frames = synthetic_frames(int(66000 / FPS60), gap_after=2000, gap_ms=3000.0)
        doc = native_result(self.pkg, modes=('bad', 'bad', 'bad'), frames=frames)
        t_gap = frames[2001][0]
        for run in doc['runs']:
            run['excluded'] = 5
            run['excluded_samples'] = [{'t': t_gap - 1500.0, 'state': {'menu': False, 'paused': True, 'offer': False, 'hidden': False, 'ad': False}}]
        p = self.write('explained-gap.json', doc)
        acc, dec = ev.evaluate([p], self.pkg)
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['verdict'], 'PASS', row['reason'])
        self.assertEqual(row['repetitions'][0]['metrics']['gaps'], 1)
        self.assertEqual(row['repetitions'][0]['metrics']['unexplained_gaps'], 0)
        log('explained pause gap: accepted, windows none spanning it, PASS; gaps=1 unexplained=0')

    def test_insufficient_duration(self):
        frames = frames_for(run_ms=50000)
        p = self.write('insufficient-duration.json', native_result(self.pkg, modes=('bad', 'bad', 'bad'), frames=frames))
        acc, dec = ev.evaluate([p], self.pkg)
        e = acc['result_files'][0]
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['verdict'], 'UNVERIFIED', row['reason'])
        self.assertEqual(row['valid_repetitions'], 0)
        # the validator already rejects a COMPLETE run short of run_ms; the evaluator's own check covers files it lets through
        self.assertTrue(any('< 60000 ms' in r for r in e['ineligible_reasons']) or
                        any('insufficient duration' in a['reasons'][0] for a in row['rejected_attempts']))
        log('insufficient-duration: UNVERIFIED ->', (e['ineligible_reasons'] or row['rejected_attempts'][0]['reasons'])[0][:100])

    def test_evaluator_duration_check_without_validator(self):
        settings = native_result(self.pkg)['settings']
        run = make_run(1, 'bad', frames_for(run_ms=50000), settings)
        out = ev.evaluate_run(run, settings, {'dpr': 1})
        self.assertFalse(out['valid'])
        self.assertIn('insufficient duration', out['reasons'][0])
        log('insufficient-duration (evaluate_run direct):', out['reasons'][0])

    def test_wrong_build(self):
        doc = native_result(self.pkg)
        doc['build']['served_tree_sha256'] = '0' * 64
        p = self.write('wrong-build.json', doc)
        acc, dec = ev.evaluate([p], self.pkg)
        e = acc['result_files'][0]
        self.assertFalse(e['eligible'])
        self.assertTrue(any('build mismatch' in r for r in e['ineligible_reasons']), e['ineligible_reasons'])
        self.assertTrue(all(v == 'UNVERIFIED' for v in dec['row_verdicts'].values()))
        self.assertFalse(dec['60fps_achieved'])
        log('wrong-build: rejected ->', [r for r in e['ineligible_reasons'] if 'build mismatch' in r][0][:100])

    def test_density_reduced_cannot_pass(self):
        p = self.write('density.json', native_result(self.pkg, modes=('bad', 'bad', 'bad'), density_reduced=True))
        acc, dec = ev.evaluate([p], self.pkg)
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['verdict'], 'FAIL', row['reason'])
        self.assertIn('rendering quality reduced', row['repetitions'][0]['thresholds_failed'][0])
        log('adaptive density reduced the backing: valid evidence but FAIL (quality not unchanged)')

    def test_emulation_and_headless_never_fill_native_rows(self):
        p = self.write('emulated.json', native_result(self.pkg, target='android-chrome', emulation='emulated'))
        acc, dec = ev.evaluate([p], self.pkg)
        self.assertFalse(acc['result_files'][0]['eligible'])
        self.assertEqual(self.row(acc, 'android-chrome/closed/bad')['verdict'], 'UNVERIFIED')
        log('emulated Android export: ineligible ->', acc['result_files'][0]['ineligible_reasons'])

    def test_all_rows_pass_sets_decision_true(self):
        paths = []
        for target in ev.TARGETS:
            for dt in ev.DEVTOOLS_STATES[target]:
                paths.append(self.write(f'{target}-{dt}.json', native_result(self.pkg, target=target, devtools=dt,
                                                                           dpr=1 if target == 'desktop' else 3)))
        acc, dec = ev.evaluate(paths, self.pkg)
        self.assertEqual(dec['counts'], {'PASS': 10, 'FAIL': 0, 'UNVERIFIED': 0})
        self.assertTrue(dec['60fps_achieved'])
        self.assertTrue(acc['docking_comparison']['desktop/docked-vs-closed/bad']['comparable'])
        log('synthetic full matrix (fixture only, NOT device evidence): 10/10 PASS -> 60fps_achieved true; docked-vs-closed comparable at matched viewport')

    def test_rolling_windows_equivalent_to_benchtool(self):
        for trial in range(4):
            random.seed(trial)
            frames, t = [[1000.0, None]], 1000.0
            for _ in range(random.randint(200, 3000)):
                if random.random() < 0.004:
                    t += random.uniform(100, 5000)
                    frames.append([t, None])
                else:
                    d = random.uniform(5, 80)
                    t += d
                    frames.append([t, d])
            a, b = bt.rolling_windows(frames), ev.rolling_windows(frames)
            self.assertEqual(len(a), len(b))
            for x, y in zip(a, b):
                self.assertEqual((x['start'], x['end'], x['intervals']), (y['start'], y['end'], y['intervals']))
                self.assertAlmostEqual(x['active_ms'], y['active_ms'], places=6)
                self.assertAlmostEqual(x['fps'], y['fps'], places=6)
        f = frames_for()
        a, b = bt.rolling_windows(f), ev.rolling_windows(f)
        self.assertEqual(len(a), len(b))
        self.assertAlmostEqual(min(w['fps'] for w in a), min(w['fps'] for w in b), places=6)
        log('evaluator rolling windows == benchtool.rolling_windows on 4 random gap-bearing traces and the 60 s fixture (%d windows)' % len(a))

    def test_classification(self):
        for target in ev.TARGETS:
            self.assertEqual(ev.classify_target(native_result(self.pkg, target=target)), target)
        doc = native_result(self.pkg, target='iphone-safari')
        doc['device']['user_agent'] = doc['device']['user_agent'].replace('Version/18.0', 'CriOS/148.0')
        self.assertIsNone(ev.classify_target(doc))
        log('classification: desktop / android-chrome / iphone-safari recognised; Chrome on iOS is not the Safari row')

    def test_aborted_attempt_keeps_the_complete_repetitions(self):
        """TASK-298: one 3-second aborted run (before the 5 s warmup) plus three COMPLETE runs:
        the file validates ACCEPTED and the row counts the three repetitions."""
        r = native_result(self.pkg, modes=('bad', 'bad', 'bad'))
        aborted = make_run(2, 'bad', synthetic_frames(int(3000 / FPS60)), r['settings'], result='ABORTED by owner')
        aborted['dimensions_at_start']['dpr'] = aborted['dimensions_at_end']['dpr'] = 1
        r['runs'] = [r['runs'][0], aborted] + [dict(x, index=i) for i, x in zip((3, 4), r['runs'][1:])]
        rep = bt.validate_result(r, self.pkg)
        self.assertEqual(rep['status'], 'ACCEPTED', rep['reasons'])
        self.assertIn('preserved as a non-complete attempt (not counted)', rep['runs'][1]['checks'])
        p = self.write('aborted-plus-three.json', r)
        acc, dec = ev.evaluate([p], self.pkg)
        entry = acc['result_files'][0]
        self.assertTrue(entry['eligible'], entry['ineligible_reasons'])
        self.assertEqual(entry['validation']['status'], 'ACCEPTED')
        row = self.row(acc, 'desktop/closed/bad')
        self.assertEqual(row['valid_repetitions'], 3, row['reason'])
        self.assertEqual(row['verdict'], 'PASS', row['reason'])
        self.assertEqual([x['run_index'] for x in row['repetitions']], [1, 3, 4])
        self.assertEqual(len(row['non_complete_attempts']), 1)
        self.assertEqual(row['non_complete_attempts'][0]['run_index'], 2)
        self.assertEqual(row['rejected_attempts'], [])
        self.assertIn('non-complete attempt preserved, not counted: ABORTED by owner', row['non_complete_attempts'][0]['reasons'])
        log('aborted 3 s run + 3 COMPLETE: file ACCEPTED/eligible, desktop/closed/bad PASS with 3 repetitions (runs 1,3,4), 1 non-complete attempt preserved')

    def test_real_smoke_exports_are_ineligible(self):
        smoke = Path(os.environ.get('BENCH_SMOKE_EXPORTS', self.pkg.parent / 'smoke'))
        files = sorted(smoke.glob('saved-*.json'))
        if not files:
            self.skipTest('no smoke exports')
        acc, dec = ev.evaluate(files, self.pkg)
        for e in acc['result_files']:
            self.assertFalse(e['eligible'], e['file'])
        self.assertTrue(all(v == 'UNVERIFIED' for v in dec['row_verdicts'].values()))
        self.assertFalse(dec['60fps_achieved'])
        log('TASK-283 headless smoke exports: %d files, all ineligible (custom protocol / emulated), all rows UNVERIFIED' % len(files))


if __name__ == '__main__':
    unittest.main(verbosity=2)
