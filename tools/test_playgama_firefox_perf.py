"""Measurement integrity: slow frames and inactive boundaries are not interchangeable."""
import unittest
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from playgama_firefox_perf import (INPUT, PROBE, ROOT, SEED, capture_command, metrics, profile_metrics,
                                   profile_conclusions, no_candidate_decision, runtime_files)
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT


class FrameMetricsTests(unittest.TestCase):
    def test_slow_active_frame_retained_and_death_gap_excluded(self):
        frames = [dict(t=t, before={'death':False}, after={'death':False})
                  for t in (0, 2500, 5000, 5010, 6010)]
        frames[-1]['after']['death'] = True
        frames.extend([dict(t=9010, before={'death':True}, after={'death':False}),
                       dict(t=9030, before={'death':False}, after={'death':False})])
        result = metrics({'frames':frames})
        self.assertEqual(result['frame_intervals_ms'], [10, 1000, 20])
        self.assertEqual(result['p95_frame_ms'], 1000)
        self.assertAlmostEqual(result['average_fps'], 3000/1030)
        self.assertEqual(result['excluded_gaps'][0]['ms'], 3000)
        self.assertEqual(result['slow_frames_dropped'], 0)

    def test_warmup_boundary_keeps_whole_interval(self):
        frames = [dict(t=t, before={}, after={}) for t in (0, 4990, 5020, 5060)]
        result = metrics({'frames':frames})
        self.assertEqual(result['warmup_ms'], 5020)
        self.assertEqual(result['frame_intervals_ms'], [40])

    def test_duplicate_timestamp_rejected(self):
        with self.assertRaises(AssertionError):
            metrics({'frames':[dict(t=1,before={},after={})]*2})


class ProfileTests(unittest.TestCase):
    def test_profile_keeps_slow_intervals_and_excludes_only_warmup(self):
        raw = {'warmup':1,'frames':2,'names':['drawWorldLayer'],
               'rows':[dict(t=t,draw_ms=d,costs={'drawWorldLayer':d},skipped=0)
                       for t,d in ((0,90),(100,3),(110,7))], 'end':1110}
        self.assertEqual(profile_metrics(raw), {'frame_ms':505,'draw_ms':5,
                         'layer_ms':{'drawWorldLayer':5},'skipped':0})

    def test_pair_rejects_state_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            a={'rows':[{'before':{'rng':1},'after':{'rng':2}}]}
            b={'rows':[{'before':{'rng':1},'after':{'rng':3}}]}
            (out/'a.json').write_text(json.dumps(a)); (out/'b.json').write_text(json.dumps(b))
            runs=[dict(engine='firefox',mode='classic',layer='layer',repetition=1,
                       arm=arm,raw=path) for arm,path in [('control','a.json'),('suppressed','b.json')]]
            with self.assertRaisesRegex(AssertionError,'unmatched states'):
                profile_conclusions(out,runs,['layer'])


class CompareTests(unittest.TestCase):
    def test_no_candidate_is_not_a_performance_or_visual_success(self):
        result = no_candidate_decision({'status':'no-supported-candidate', 'reason':'No mechanism'}, 'abc')
        self.assertEqual(result['decision'], 'NO_SUPPORTED_CANDIDATE')
        self.assertEqual(result['runtime_sha256'], 'abc')
        self.assertIsNone(result['candidate_sha256'])
        self.assertIsNone(result['hypothesis_tested'])
        self.assertFalse(result['performance_success'])
        self.assertEqual(result['native_android'], 'UNVERIFIED')

    def test_supported_candidate_cannot_silently_skip_experiment(self):
        with self.assertRaisesRegex(ValueError, 'refusing an untested decision'):
            no_candidate_decision({'status':'supported-candidate'}, 'abc')

    def test_snapshot_includes_referenced_runtime_and_ignores_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'index.html').write_text('<script src="game.js"></script><script src="https://bridge.playgama.com/v2/stable/playgama-bridge.js"></script>')
            (root/'game.js').write_text('const fixed = true;')
            (root/'playgama-bridge-config.json').write_text('{}')
            self.assertEqual(set(runtime_files(root)), {'index.html', 'game.js', 'playgama-bridge-config.json'})
            (root/'index.html').write_text('<script src="../secret.js"></script>')
            with self.assertRaisesRegex(ValueError, 'Unsafe runtime reference'):
                runtime_files(root)


class StartScriptTests(unittest.TestCase):
    def test_start_script_starts_both_modes_from_boot_run(self):
        # The current tree has no title menu (TASK-364): 'bad' is the boot run,
        # 'classic' comes from the HUD button and the pause mode switch.
        url, browser = start_browser_test(ROOT, self.addCleanup)
        for mode in ('bad', 'classic'):
            with self.subTest(mode=mode):
                context = browser.new_context(viewport={'width':844,'height':390}, device_scale_factor=2,
                                              has_touch=True, service_workers='block', locale='en-US')
                self.addCleanup(context.close)
                context.add_init_script(SEED_SCRIPT % SEED)
                page = context.new_page(); page.set_default_timeout(20000)
                errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url+'index.html')
                page.wait_for_function('bootComplete && document.getElementById("loading").hidden')
                page.evaluate(PROBE, {'mode':mode, 'inputs':INPUT, 'seed':SEED})
                frames = page.evaluate('perfReceipt.frames.length')
                page.wait_for_function('n => perfReceipt.frames.length > n + 5', arg=frames)
                state = page.evaluate('''({version, running:runInProgress, paused:menu.gamePaused,
                    accepted:perfReceipt.accepted_input_ms, first:perfReceipt.first_active_frame_ms})''')
                self.assertEqual(state['version'], mode)
                self.assertTrue(state['running'])
                self.assertFalse(state['paused'])
                self.assertIsInstance(state['accepted'], (int, float))
                self.assertIsInstance(state['first'], (int, float))
                self.assertLessEqual(state['accepted'], state['first'] + 50)
                self.assertEqual(errors, [])


class ConsoleCaptureTests(unittest.TestCase):
    def test_original_stdout_stderr_and_failure_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'baseline-command.log'
            with contextlib.redirect_stdout(io.StringIO()):
                code = capture_command([sys.executable, '-u', '-c',
                    "import sys; print('original stdout'); print('original stderr', file=sys.stderr); sys.exit(7)"],
                    path, {'execution_id':'test-run'})
            lines = path.read_text().splitlines()
            self.assertEqual(code, 7)
            self.assertEqual(lines[1:3], ['original stdout', 'original stderr'])
            self.assertEqual(json.loads(lines[0][10:])['execution_id'], 'test-run')
            self.assertEqual(json.loads(lines[-1][5:])['exit_code'], 7)
            with self.assertRaises(FileExistsError):
                capture_command([], path, {})


if __name__ == '__main__':
    unittest.main()
