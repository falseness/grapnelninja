"""Tests for the owner benchmark runner (TASK-283).

Cheap tests (no browser): replay determinism, frame arithmetic, pause-gap
exclusion, rolling windows, schema / missing-field / mismatched-build
rejection, index.html patch shape, static network inspection.

Browser smoke (Playwright, skipped with BENCH_SKIP_BROWSER=1): serves a copy of
the built package on 127.0.0.1, runs a short custom-protocol capture on the
desktop and touch engines (Chromium) and on Firefox desktop, exercises the
pause gap, export by POST /save and by download, imports both files with the
validator, and asserts network isolation and measurement invariance.

Environment: BENCH_PACKAGE (built package root; otherwise built into a temp
dir from the enclosing git checkout), BENCH_SMOKE_DIR (copies of the smoke
exports and logs are written there).
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import benchtool as bt  # noqa: E402

SMOKE_DIR = os.environ.get('BENCH_SMOKE_DIR')
_TMP = []


def log(*parts):
    print('[evidence]', *parts, flush=True)


def find_repo():
    for p in [HERE] + list(HERE.parents):
        if (p / 'tools' / 'build-y8-zip.py').exists() and (p / '.git').exists():
            return p
    return None


_PACKAGE = None


def package_root():
    """Built package: BENCH_PACKAGE, else a fresh build in a temp dir."""
    global _PACKAGE
    if _PACKAGE is None:
        if os.environ.get('BENCH_PACKAGE'):
            _PACKAGE = Path(os.environ['BENCH_PACKAGE']).resolve()
        else:
            repo = find_repo()
            if repo is None:
                raise unittest.SkipTest('no BENCH_PACKAGE and no enclosing git checkout to build from')
            tmp = Path(tempfile.mkdtemp(prefix='bench-pkg-'))
            _TMP.append(tmp)
            rc = bt.main(['build', '--repo', str(repo), '--output', str(tmp)])
            assert rc == 0
            _PACKAGE = tmp
    return _PACKAGE


def temp_copy(src):
    dst = Path(tempfile.mkdtemp(prefix='bench-copy-'))
    _TMP.append(dst)
    shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def synthetic_frames(count, dt=1000 / 60, t0=1000.0, gap_after=None, gap_ms=0.0):
    """[t, dt] frames at a fixed cadence; a gap (null interval) after frame gap_after."""
    frames, t = [], t0
    for i in range(count):
        if i == 0:
            frames.append([t, None])
        elif gap_after is not None and i == gap_after + 1:
            t += gap_ms
            frames.append([t, None])
        else:
            t += dt
            frames.append([t, dt])
    return frames


def dims(mode='bad', backing=(1280, 720)):
    return {'canvas_backing': list(backing), 'canvas_css': [1280, 720], 'dpr': 1, 'viewport': [1280, 720],
            'logical': [1920, 1080], 'rotated': False, 'render_density': 1, 'density_limit': 'Infinity',
            'platform': 'disabled', 'build_version': 'x', 'fps_counter_enabled': False, 'version': mode}


def make_run(index, mode, frames, settings, result='COMPLETE', replay_kind='auto'):
    seed = 0 if settings['seed'] == 'none' else int(settings['seed'])
    replay = bt.replay_fractions(seed, settings['warmup_ms'] + settings['run_ms'] + 1000) if replay_kind == 'auto' else []
    run = {'index': index, 'mode': mode, 'started_utc': 'u', 'ended_utc': 'u', 'seed_installed': 'mulberry32(4)',
           'replay_kind': replay_kind, 'input_kind': 'mouse', 'replay_fractions_sha256': bt.sha_canonical(replay),
           'replay_events': len(replay), 'dimensions_at_start': dims(mode), 'dimensions_at_end': dims(mode),
           'frames': frames, 'excluded': 0, 'excluded_samples': [], 'interruptions': [], 'deaths': [], 'dispatched': [],
           'backing': {'initial': [1280, 720], 'changes': []}, 'warmup_end_active_ms': None,
           'active_ms': sum(f[1] for f in frames if f[1] is not None), 'result': result, 'error': None,
           'frames_sha256': bt.sha_canonical(frames)}
    try:
        vi = bt.verdict_inputs(run, settings)
        vi.pop('rolling_10s_windows_detail')
    except bt.Rejected:
        vi = {'warmup_ms': settings['warmup_ms'], 'run_ms': settings['run_ms'], 'measured_start_frame': None,
              'measured': None, 'rolling_10s_windows': 0, 'rolling_10s_min_fps': None, 'backing_constant': True,
              'backing_sizes': [[1280, 720]], 'inactive_frames_excluded': 0, 'deaths': 0, 'dispatched_inputs': 0,
              'measured_active_ms_reached': False}
    run['verdict_inputs'] = vi
    return run


def make_result(build=None, warmup_ms=5000, run_ms=60000, reps=3, emulation='none', frames=None, modes=('bad',)):
    settings = {'seed': '4', 'replay_kind': 'auto', 'input_kind': 'auto', 'warmup_ms': warmup_ms, 'run_ms': run_ms,
                'repetitions_target': reps, 'protocol': 'standard' if (warmup_ms, run_ms, reps) == (5000, 60000, 3) else 'custom',
                'devtools': 'closed', 'cpu_throttle': 'none (1x)', 'emulation': emulation, 'notes': '', 'density': 'NOT pinned',
                'sdk_isolation': 'x', 'hooks': 'x', 'autosend': True, 'autostart': False, 'seed_installed_at_load': 'mulberry32(4)'}
    if build is None:
        build = {'source_revision': 'f' * 40, 'served_tree_sha256': 'a' * 64, 'served_files_sha256': {}, 'bench_js_sha256': 'b' * 64,
                 'build_version': 'x', 'committed_index_html_sha256': 'c' * 64, 'served_index_html_sha256': 'd' * 64}
    if frames is None:
        frames = synthetic_frames(int((warmup_ms + run_ms) / (1000 / 60)) + 5)
    return {'schema': bt.SCHEMA_ID, 'build': build,
            'device': {'model_supplied': 'Test Device', 'user_agent': 'ua', 'os_family_detected': None, 'browser_family_detected': None,
                       'detected_from': 'navigator.userAgent', 'max_touch_points': 0, 'ua_client_hints': None},
            'display': {'refresh_rate_hz_supplied': None, 'refresh_rate_marker': 'unknown', 'raf_estimate': None,
                        'screen': [1920, 1080], 'dpr': 1, 'orientation': None, 'viewport': [1280, 720]},
            'gpu': {'available': False, 'reason': 'test'}, 'settings': settings, 'platform_at_session_start': 'disabled',
            'build_version': 'x', 'page_url': '/game/index.html', 'started_utc': 'u', 'exported_utc': 'u',
            'runs': [make_run(i + 1, m, frames, settings) for i, m in enumerate(modes)]}


class Arithmetic(unittest.TestCase):
    def test_replay_deterministic_and_bounded(self):
        a, b = bt.replay_fractions(4, 66000), bt.replay_fractions(4, 66000)
        self.assertEqual(a, b)
        self.assertNotEqual(bt.sha_canonical(a), bt.sha_canonical(bt.replay_fractions(1, 66000)))
        for e in a:
            self.assertTrue(0.40 <= e['fx'] <= 0.85 and 0.15 <= e['fy'] <= 0.60)
            self.assertLessEqual(e['t_ms'], 66000)
        self.assertEqual([e['type'] for e in a[:4]], ['start', 'end', 'start', 'end'])
        self.assertTrue(all(a[i]['t_ms'] <= a[i + 1]['t_ms'] for i in range(len(a) - 1)))
        log('replay seed 4 total 66000:', len(a), 'events sha', bt.sha_canonical(a))

    def test_canonical_json_matches_js_stringify_shape(self):
        self.assertEqual(bt.canonical({'b': 1, 'a': [1.5, None, 'x', True]}), '{"a":[1.5,null,"x",true],"b":1}')

    def test_check_frames_rejects_bad_arithmetic(self):
        good = synthetic_frames(10)
        bt.check_frames(good)
        bad = copy.deepcopy(good); bad[3][1] += 0.5
        with self.assertRaisesRegex(bt.Rejected, 'interval does not equal timestamp difference'):
            bt.check_frames(bad)
        bad = copy.deepcopy(good); bad[4][0] = bad[3][0] - 1; bad[4][1] = None
        with self.assertRaisesRegex(bt.Rejected, 'non-increasing'):
            bt.check_frames(bad)
        bad = copy.deepcopy(good); bad[0][1] = 16.0
        with self.assertRaisesRegex(bt.Rejected, 'first frame carries an interval'):
            bt.check_frames(bad)
        with self.assertRaisesRegex(bt.Rejected, 'fewer than two'):
            bt.check_frames([[1.0, None]])
        log('frame arithmetic: interval mismatch, non-increasing, first-frame interval, too-short all rejected')

    def test_metrics_percentiles(self):
        frames = synthetic_frames(101, dt=10.0)
        frames[-1][0] += 40.0; frames[-1][1] += 40.0  # one 50 ms frame
        m = bt.metrics(frames)
        self.assertEqual(m['intervals'], 100)
        self.assertAlmostEqual(m['active_ms'], 1040.0)
        self.assertAlmostEqual(m['average_fps'], 100 * 1000 / 1040.0)
        self.assertEqual(m['frame_ms']['p50'], 10.0)
        self.assertEqual(m['frame_ms']['p95'], 10.0)
        self.assertEqual(m['frame_ms']['p99'], 10.0)
        self.assertEqual(m['frame_ms']['max'], 50.0)
        self.assertEqual(bt.percentile(sorted([10.0] * 95 + [50.0] * 5), 95), 10.0)
        self.assertEqual(bt.percentile(sorted([10.0] * 94 + [50.0] * 6), 95), 50.0)
        log('metrics: 100 intervals, avg %.3f fps, p50/p95/p99/max %s' % (m['average_fps'], m['frame_ms']))

    def test_pause_gap_excluded_from_metrics_and_windows(self):
        frames = synthetic_frames(22, dt=16.0, gap_after=10, gap_ms=3000.0)
        m = bt.metrics(frames)
        self.assertEqual(m['intervals'], 20)
        self.assertEqual(m['gaps'], 1)
        self.assertAlmostEqual(m['active_ms'], 320.0)
        self.assertAlmostEqual(m['average_fps'], 62.5)
        self.assertGreater(m['wall_ms'], 3000.0)
        windows = bt.rolling_windows(frames, 100.0)
        self.assertEqual(len(windows), 8)  # 4 per contiguous segment, none spanning the gap
        self.assertTrue(all(w['intervals'] == 7 for w in windows))
        self.assertTrue(all(not (w['start'] < 11 <= w['end']) for w in windows))
        log('pause gap: 3000 ms gap excluded; active 320 ms over 20 intervals; 8 rolling windows, none spanning the gap')

    def test_measured_region_and_short_run(self):
        settings = {'warmup_ms': 100.0, 'run_ms': 200.0}
        frames = synthetic_frames(40, dt=10.0)
        run = {'frames': frames, 'backing': {'initial': [1, 1], 'changes': []}, 'excluded': 0, 'deaths': [], 'dispatched': []}
        vi = bt.verdict_inputs(run, settings)
        self.assertEqual(vi['measured_start_frame'], 10)
        self.assertEqual(vi['measured']['intervals'], 29)
        self.assertTrue(vi['measured_active_ms_reached'])
        short = bt.verdict_inputs(dict(run, frames=synthetic_frames(25, dt=10.0)), settings)
        self.assertFalse(short['measured_active_ms_reached'])
        with self.assertRaisesRegex(bt.Rejected, 'warmup never completed'):
            bt.verdict_inputs(dict(run, frames=synthetic_frames(5, dt=10.0)), settings)
        log('measured region starts at frame 10 (warmup 100 ms); 290 ms measured reached; 140 ms short run flagged')

    def test_rolling_minimum_detects_slow_stretch(self):
        frames = synthetic_frames(400, dt=10.0)
        for i in range(200, 230):  # 30 slow frames of 40 ms
            frames[i][1] = 40.0
        t = frames[0][0]
        for f in frames[1:]:
            t += f[1]; f[0] = t
        windows = bt.rolling_windows(frames, 100.0)
        self.assertLess(min(w['fps'] for w in windows), 30.0)
        self.assertAlmostEqual(max(w['fps'] for w in windows), 100.0)
        log('rolling 100 ms windows: min %.2f fps inside the slow stretch, max %.2f fps elsewhere' % (
            min(w['fps'] for w in windows), max(w['fps'] for w in windows)))


class Schema(unittest.TestCase):
    def test_fixture_accepted_and_eligible(self):
        rep = bt.validate_result(make_result(), None)
        self.assertEqual(rep['status'], 'ACCEPTED', rep['reasons'])
        self.assertTrue(rep['acceptance_eligible'])
        self.assertEqual(rep['runs'][0]['verdict_inputs']['measured']['intervals'] > 3500, True)
        log('standard fixture ACCEPTED, acceptance_eligible True; rolling windows', rep['runs'][0]['verdict_inputs']['rolling_10s_windows'])

    def test_missing_fields_rejected(self):
        for path in (('device', 'model_supplied'), ('display', 'refresh_rate_marker'), ('settings', 'devtools'), ('build', 'served_tree_sha256')):
            r = make_result()
            del r[path[0]][path[1]]
            rep = bt.validate_result(r, None)
            self.assertEqual(rep['status'], 'REJECTED')
            self.assertTrue(any(f'{path[1]}: missing required field' in x for x in rep['reasons']), rep['reasons'])
            log('missing', '.'.join(path), '->', rep['reasons'][0])
        r = make_result(); del r['runs'][0]['frames']
        rep = bt.validate_result(r, None)
        self.assertTrue(any('frames: missing required field' in x for x in rep['reasons']))
        log('missing runs[0].frames ->', rep['reasons'][0])

    def test_unknown_fields_are_not_inferred(self):
        r = make_result(); r['device']['model_supplied'] = '   '
        self.assertIn('device.model_supplied must name the actual device', bt.validate_result(r, None)['reasons'])
        r = make_result(); r['display']['refresh_rate_marker'] = 'manual'  # value still null
        self.assertTrue(any('manual requires' in x for x in bt.validate_result(r, None)['reasons']))
        r = make_result(); r['display']['refresh_rate_hz_supplied'] = 60  # marker still unknown
        self.assertTrue(any('unknown must not carry' in x for x in bt.validate_result(r, None)['reasons']))
        r = make_result(); r['display']['refresh_rate_marker'] = 'guessed'
        self.assertTrue(any('not in' in x for x in bt.validate_result(r, None)['reasons']))
        log('blank model, manual marker without value, unknown marker with value, invented marker all rejected')

    def test_custom_protocol_and_emulation_not_eligible(self):
        r = make_result(warmup_ms=800, run_ms=2500, reps=1)
        self.assertEqual(bt.validate_result(r, None)['status'], 'REJECTED')
        rep = bt.validate_result(r, None, allow_custom=True)
        self.assertEqual(rep['status'], 'ACCEPTED')
        self.assertFalse(rep['acceptance_eligible'])
        r = make_result(emulation='emulated')
        rep = bt.validate_result(r, None)
        self.assertEqual(rep['status'], 'ACCEPTED')
        self.assertFalse(rep['acceptance_eligible'])
        self.assertTrue(any('not a native-device result' in w for w in rep['warnings']))
        log('custom protocol rejected unless allowed, never eligible; emulated accepted for integrity, never eligible')

    def test_run_level_rejections(self):
        r = make_result(); r['runs'][0]['frames'][5][1] += 1.0
        self.assertTrue(any('interval does not equal' in x for x in bt.validate_result(r, None)['reasons']))
        r = make_result(); r['runs'][0]['frames'][5][0] += 1.0; r['runs'][0]['frames'][5][1] += 1.0; r['runs'][0]['frames'][6][1] -= 1.0
        self.assertTrue(any('frames_sha256 does not seal' in x for x in bt.validate_result(r, None)['reasons']))
        r = make_result(); r['runs'][0]['replay_fractions_sha256'] = 'e' * 64
        self.assertTrue(any('replay_fractions_sha256 differs' in x for x in bt.validate_result(r, None)['reasons']))
        r = make_result(); r['runs'][0]['dimensions_at_start']['version'] = 'classic'
        self.assertTrue(any('not started' in x for x in bt.validate_result(r, None)['reasons']))
        r = make_result(); r['platform_at_session_start'] = 'y8'
        self.assertTrue(any('SDK isolation' in x for x in bt.validate_result(r, None)['reasons']))
        r = make_result(); r['runs'][0]['verdict_inputs']['measured']['average_fps'] += 1
        self.assertTrue(any('differs from recomputed' in x for x in bt.validate_result(r, None)['reasons']))
        short = make_result(frames=synthetic_frames(1200))
        rep = bt.validate_result(short, None)
        self.assertTrue(any('measured active time' in x for x in rep['reasons']), rep['reasons'])
        aborted = make_result(); aborted['runs'][0]['result'] = 'ABORTED by owner'
        rep = bt.validate_result(aborted, None)
        self.assertEqual(rep['status'], 'ACCEPTED')
        self.assertEqual(rep['complete_runs']['bad'], 0)
        log('tampered interval, broken seal, foreign replay, wrong mode, SDK present, page-side drift, short run rejected; aborted run preserved uncounted')

    def test_gap_in_measured_region_is_warned_not_hidden(self):
        frames = synthetic_frames(4000, gap_after=1500, gap_ms=5000.0)
        rep = bt.validate_result(make_result(frames=frames), None)
        self.assertEqual(rep['status'], 'ACCEPTED', rep['reasons'])
        self.assertTrue(any('gap(s) excluded' in w for w in rep['warnings']))
        self.assertEqual(rep['runs'][0]['verdict_inputs']['measured']['gaps'], 1)
        log('5 s pause gap inside the measured region: accepted with warning,', rep['warnings'])


class BuildMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pkg = package_root()
        cls.build = json.loads((cls.pkg / 'game' / 'build.json').read_text())

    def test_matching_build_accepted(self):
        rep = bt.validate_result(make_result(build=self.build), self.pkg)
        self.assertEqual(rep['status'], 'ACCEPTED', rep['reasons'])
        log('matching build accepted:', self.build['source_revision'][:12], self.build['served_tree_sha256'][:12])

    def test_mismatched_build_rejected(self):
        b = dict(self.build, served_tree_sha256='0' * 64)
        rep = bt.validate_result(make_result(build=b), self.pkg)
        self.assertTrue(any(x.startswith('build mismatch: result served_tree_sha256') for x in rep['reasons']), rep['reasons'])
        b = dict(self.build, source_revision='1' * 40)
        rep = bt.validate_result(make_result(build=b), self.pkg)
        self.assertTrue(any('source_revision' in x for x in rep['reasons']), rep['reasons'])
        log('mismatched tree hash and revision rejected:', rep['reasons'])

    def test_tampered_package_rejected(self):
        tampered = temp_copy(self.pkg)
        with open(tampered / 'game' / 'style.js', 'a') as f:
            f.write('\n// tampered\n')
        rep = bt.validate_result(make_result(build=self.build), tampered)
        self.assertTrue(any('no longer match their build.json' in x for x in rep['reasons']), rep['reasons'])
        log('tampered package rejected:', [x for x in rep['reasons'] if 'build.json' in x])

    def test_index_patch_is_the_single_sdk_line(self):
        diff = (self.pkg / 'game' / 'PATCH.diff').read_text().splitlines()
        minus = [l for l in diff if l.startswith('-') and not l.startswith('---')]
        plus = [l for l in diff if l.startswith('+') and not l.startswith('+++')]
        self.assertEqual(len(minus), 1); self.assertEqual(len(plus), 1)
        self.assertIn('cdn.y8.com', minus[0]); self.assertIn(bt.BENCH_TAG, plus[0])
        self.assertNotIn('cdn.y8.com', (self.pkg / 'game' / 'index.html').read_text())
        self.assertEqual(len(self.build['served_files_sha256']), len(self.build['runtime_files']) + 1)
        log('PATCH.diff:', minus[0].strip(), '->', plus[0].strip())

    def test_static_inspection_passes(self):
        report = Path(tempfile.mkdtemp(prefix='bench-inspect-')) / 'inspect.log'
        _TMP.append(report.parent)
        repo = find_repo()
        argv = ['inspect', '--root', str(self.pkg), '--report', str(report)] + (['--repo', str(repo)] if repo else [])
        rc = bt.main(argv)
        self.assertEqual(rc, 0)
        self.assertIn('RESULT PASS', report.read_text())
        log('inspect:', [l for l in report.read_text().splitlines() if l.startswith(('OK', 'FAIL'))])


@unittest.skipIf(os.environ.get('BENCH_SKIP_BROWSER') == '1', 'BENCH_SKIP_BROWSER=1')
class BrowserSmoke(unittest.TestCase):
    PROFILES = {
        'desktop': dict(viewport={'width': 1280, 'height': 720}, device_scale_factor=1, is_mobile=False, has_touch=False),
        'touch': dict(viewport={'width': 844, 'height': 390}, device_scale_factor=2, is_mobile=True, has_touch=True),
    }
    WARMUP, RUN = 800, 2500

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('playwright not installed')
        cls.pkg = temp_copy(package_root())
        cls.build = json.loads((cls.pkg / 'game' / 'build.json').read_text())
        cls.server = bt.make_server(cls.pkg, '127.0.0.1', 0)
        cls.origin = 'http://127.0.0.1:%d' % cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.pw = sync_playwright().start()
        cls.smoke = Path(SMOKE_DIR) if SMOKE_DIR else Path(tempfile.mkdtemp(prefix='bench-smoke-'))
        cls.smoke.mkdir(parents=True, exist_ok=True)
        log('smoke server', cls.origin, 'package copy', cls.pkg, 'exports ->', cls.smoke)

    @classmethod
    def tearDownClass(cls):
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        shutil.copy2(cls.pkg / 'server.log', cls.smoke / 'server.log')

    def capture(self, engine, profile, pause=False):
        label = f'{engine}-{profile}'
        browser = getattr(self.pw, engine).launch(args=['--no-sandbox'] if engine == 'chromium' else [])
        self.addCleanup(browser.close)
        network, errors = [], []
        ctx = browser.new_context(accept_downloads=True, service_workers='block', **self.PROFILES[profile])

        def route(r):
            u = r.request.url
            if u.startswith(self.origin + '/'):
                network.append('LOCAL ' + u); r.continue_()
            else:
                network.append('BLOCKED ' + u); r.abort()
        ctx.route('**/*', route)
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console.error: ' + m.text) if m.type == 'error' else None)
        before = set(p.name for p in (self.pkg / 'results').glob('*.json'))
        url = (f'{self.origin}/game/index.html?model=Playwright+{label}&refresh=unknown&devtools=closed&throttle=none+(1x)'
               f'&emulation=emulated&warmup_ms={self.WARMUP}&run_ms={self.RUN}&reps=1&autosend=1&seed=4&mode=bad')
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_function('() => window.__bench && window.__bench.ready', timeout=60000)
        originals = page.evaluate('''() => ({observe: RENDER_BUDGET.observe.toString(), draw: draw.toString(), physics: physics.toString(),
            configure: configureCanvasViewport.toString(), loop: gameLoop.toString(), limit: String(RENDER_BUDGET.densityLimit),
            panelVisible: getComputedStyle(document.getElementById('bench-panel')).display !== 'none',
            platform: PLATFORM.environment, backing: [canvas.width, canvas.height], css: (r => [r.width, r.height])(canvas.getBoundingClientRect()),
            dpr: devicePixelRatio, density: getRenderDensity(), random: Math.random.toString().includes('0x6D2B79F5')})''')
        self.assertTrue(originals['panelVisible'])
        self.assertEqual(originals['platform'], 'disabled')
        self.assertTrue(originals['random'])
        self.assertEqual(originals['limit'], 'Infinity', 'adaptive density must start untouched (nothing pins it)')
        expected_backing = [round(originals['css'][0] * originals['dpr']), round(originals['css'][1] * originals['dpr'])]
        self.assertEqual(originals['backing'], [round(originals['css'][0] * originals['density']), round(originals['css'][1] * originals['density'])])
        page.click('#bench-start')
        page.wait_for_function('() => window.__bench.run !== null && window.__bench.run.frames.length > 5', timeout=30000)
        during = page.evaluate('''() => ({observe: RENDER_BUDGET.observe.toString(), draw: draw.toString(), physics: physics.toString(),
            configure: configureCanvasViewport.toString(), loop: gameLoop.toString(), limit: String(RENDER_BUDGET.densityLimit),
            panelVisible: getComputedStyle(document.getElementById('bench-panel')).display !== 'none',
            version: version, backing: [canvas.width, canvas.height]})''')
        for key in ('observe', 'draw', 'physics', 'configure'):
            self.assertEqual(originals[key], during[key], key + ' changed by the benchmark')
        self.assertNotEqual(originals['loop'], during['loop'], 'gameLoop must be wrapped while recording')
        self.assertFalse(during['panelVisible'], 'panel must be hidden while recording')
        self.assertEqual(during['version'], 'bad')
        if pause:
            page.wait_for_function('() => window.__bench.run.active_ms > %d' % (self.WARMUP + 500), timeout=30000)  # gap inside the measured region
            page.keyboard.press('Escape')
            page.wait_for_function("() => menu.gamePaused && getComputedStyle(document.getElementById('bench-panel')).display !== 'none'", timeout=10000)
            page.wait_for_timeout(500)
            paused = page.evaluate('() => ({excluded: __bench.run.excluded, active: __bench.run.active_ms})')
            self.assertGreater(paused['excluded'], 0)
            page.keyboard.press('Escape')
            page.wait_for_function("() => !menu.gamePaused && getComputedStyle(document.getElementById('bench-panel')).display === 'none'", timeout=10000)
            log(label, 'pause gap: paused for 500 ms after %.0f active ms, %d inactive frames excluded' % (paused['active'], paused['excluded']))
        page.wait_for_function('() => window.__bench.session && window.__bench.session.runs.length === 1', timeout=90000)
        after = page.evaluate('''() => ({loop: gameLoop.toString(), run: (r => ({result: r.result, frames: r.frames.length, excluded: r.excluded,
            gaps: r.frames.slice(1).filter(f => f[1] === null).length, input: r.input_kind, dispatched: r.dispatched.length, deaths: r.deaths.length,
            replay_sha: r.replay_fractions_sha256, frames_sha: r.frames_sha256, backing: r.backing, vi: r.verdict_inputs,
            dims_start: r.dimensions_at_start, dims_end: r.dimensions_at_end}))(__bench.session.runs[0]),
            panelVisible: getComputedStyle(document.getElementById('bench-panel')).display !== 'none'})''')
        self.assertEqual(after['loop'], originals['loop'], 'gameLoop must be restored after the run')
        self.assertTrue(after['panelVisible'])
        self.assertEqual(after['run']['result'], 'COMPLETE')
        self.assertEqual(after['run']['input'], 'touch' if profile == 'touch' else 'mouse')
        self.assertGreater(after['run']['dispatched'], 0)
        # Adaptive density is the game's own (unpinned) behaviour: whatever it did is recorded, never hidden.
        backing, ds, de = after['run']['backing'], after['run']['dims_start'], after['run']['dims_end']
        self.assertEqual(backing['initial'], ds['canvas_backing'])
        self.assertEqual(backing['initial'], [round(ds['canvas_css'][0] * ds['render_density']), round(ds['canvas_css'][1] * ds['render_density'])])
        final_backing = backing['changes'][-1]['backing'] if backing['changes'] else backing['initial']
        self.assertEqual(final_backing, de['canvas_backing'])
        self.assertEqual(after['run']['vi']['backing_constant'], not backing['changes'])
        density_path = 'density limit %s -> %s, backing %s -> %s (%d change(s) recorded%s)' % (
            ds['density_limit'], de['density_limit'], backing['initial'], final_backing, len(backing['changes']),
            '; native would be %s' % expected_backing if final_backing != expected_backing else '')
        if pause:
            self.assertGreater(after['run']['excluded'], 0)
            self.assertGreaterEqual(after['run']['gaps'], 1)
            self.assertGreaterEqual(after['run']['vi']['measured']['gaps'], 1, 'the pause gap must be excluded inside the measured region')
        expected_replay = bt.sha_canonical(bt.replay_fractions(4, self.WARMUP + self.RUN + 1000))
        self.assertEqual(after['run']['replay_sha'], expected_replay, 'JS and Python replay generators disagree')
        # export 1: POST /save (auto-send after the run)
        deadline = time.time() + 15
        saved = []
        while time.time() < deadline and not saved:
            saved = sorted(set(p.name for p in (self.pkg / 'results').glob('*.json')) - before)
            time.sleep(0.2)
        self.assertEqual(len(saved), 1, 'auto-send did not store exactly one result')
        saved_path = self.pkg / 'results' / saved[0]
        # export 2: download
        with page.expect_download(timeout=30000) as dl:
            page.click('#bench-download')
        download_path = self.smoke / f'download-{label}.json'
        dl.value.save_as(download_path)
        self.assertEqual(saved_path.read_bytes() != b'', True)
        exported = json.loads(download_path.read_text())
        self.assertEqual(json.loads(saved_path.read_text())['runs'][0]['frames_sha256'], exported['runs'][0]['frames_sha256'])
        self.assertEqual(bt.sha_canonical(exported['runs'][0]['frames']), exported['runs'][0]['frames_sha256'], 'Python canonical seal differs from the page seal')
        # import both
        for path in (saved_path, download_path):
            rep = bt.validate_result(json.loads(path.read_text()), self.pkg, allow_custom=True)
            self.assertEqual(rep['status'], 'ACCEPTED', rep['reasons'])
            self.assertFalse(rep['acceptance_eligible'])
            self.assertEqual(rep['package']['served_tree_sha256'], self.build['served_tree_sha256'])
            self.assertEqual(bool(backing['changes']), any('backing size changed' in w for w in rep['warnings']))
            (self.smoke / f'validate-{label}-{path.name}.json').write_text(json.dumps(rep, indent=1, sort_keys=True) + '\n')
        strict = bt.validate_result(exported, self.pkg)
        self.assertEqual(strict['status'], 'REJECTED')
        self.assertTrue(any('non-standard protocol' in x for x in strict['reasons']))
        shutil.copy2(saved_path, self.smoke / f'saved-{label}.json')
        blocked = [n for n in network if not n.startswith('LOCAL ')]
        self.assertEqual(blocked, [], 'non-local requests: ' + ', '.join(blocked))
        self.assertEqual(errors, [])
        (self.smoke / f'network-{label}.log').write_text('\n'.join(network) + '\n')
        vi = after['run']['vi']
        log(label, 'COMPLETE: %d frames, %d measured intervals, avg %.2f fps, p95 %.2f ms, min10s %s, gaps %d, excluded %d, deaths %d, dispatched %d, %s, %d local requests, 0 blocked; '
            'saved %s; download %s; validate ACCEPTED x2 (custom protocol -> not eligible), strict REJECTED' % (
                after['run']['frames'], vi['measured']['intervals'], vi['measured']['average_fps'], vi['measured']['frame_ms']['p95'],
                vi['rolling_10s_min_fps'], vi['measured']['gaps'], after['run']['excluded'], after['run']['deaths'], after['run']['dispatched'],
                density_path, len(network), saved[0], download_path.name))
        ctx.close()
        return exported

    def test_chromium_desktop_capture_export_import_with_pause_gap(self):
        self.capture('chromium', 'desktop', pause=True)

    def test_chromium_touch_capture_export_import(self):
        self.capture('chromium', 'touch')

    def test_firefox_desktop_capture_export_import(self):
        self.capture('firefox', 'desktop')

    def test_server_rejects_foreign_documents_and_listings(self):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(self.origin + '/save', data=b'{"schema": "other"}', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.origin + '/results/')
        self.assertEqual(cm.exception.code, 403)
        with urllib.request.urlopen(self.origin + '/game/build.json') as r:
            self.assertEqual(r.headers['Cache-Control'], 'no-store')
            self.assertEqual(json.loads(r.read())['served_tree_sha256'], self.build['served_tree_sha256'])
        log('server: foreign POST 400, directory listing 403, build.json served with no-store')


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        for p in _TMP:
            shutil.rmtree(p, ignore_errors=True)
