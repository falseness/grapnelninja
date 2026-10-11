"""Cheap checks for tools/y8_chill_ablation.py (TASK-273): no browser.

Window density/camera arithmetic (death resets excluded, sample/frame coverage
enforced), per-population tiers that never share a noise threshold, stage names
for all eight TASK-272 features, Chill/Main mode names, and no hook or sampler
marker in the shipped runtime.
"""
import subprocess
import unittest

import y8_chill_ablation as ch
import y8_feature_ablation as ab
import y8_feature_cost as fc


def fake_raw(sx, deaths, particles, warmup_ms=0, window_ms=90):
    frames = [{'t': 1000 + 30 * i, 'dt': None if i == 0 else 30.0, 'canvas': [1280, 720],
               'state': {'menu': False, 'paused': False, 'offer': False, 'hidden': False, 'ad': False}} for i in range(len(sx))]
    samples = [{'t': f['t'], 'sx': x, 'sy': 0, 'nx': 1, 'ny': 1, 'particles': p, 'pool': 0, 'motes': 40, 'track': 2,
                'obstacleTrack': 0, 'elements': 5, 'lights': 1, 'score': 0, 'deaths': d}
               for f, x, d, p in zip(frames, sx, deaths, particles)]
    return {'case': 'fake', 'settings': {'warmup_ms': warmup_ms, 'window_ms': window_ms, 'windows': 1},
            'frames': frames, 'samples': samples, 'deaths': [None] * max(deaths)}


class DensityTests(unittest.TestCase):
    def test_camera_travel_excludes_death_reset(self):
        # camera moves -10 per frame, dies after frame 2 (jump back to 0), then moves again
        raw = fake_raw(sx=[0, -10, -20, 0, -5, -15], deaths=[0, 0, 0, 1, 1, 1], particles=[10, 20, 30, 0, 10, 20], window_ms=150)
        d = ch.window_density(raw)
        self.assertEqual(d['window_frames'], 6)
        self.assertEqual(d['samples'], 6)
        self.assertEqual(d['deaths_in_window'], 1)
        self.assertEqual(d['camera']['travel_px'], 10 + 10 + 5 + 10)
        self.assertEqual(d['camera']['resets_excluded'], 1)
        self.assertAlmostEqual(d['camera']['moving_fraction'], 4 / 5)
        self.assertEqual(d['camera']['x_range'], [-20, 0])
        self.assertAlmostEqual(d['counts']['particles']['mean'], 15.0)
        self.assertEqual(d['counts']['motes']['max'], 40)

    def test_missing_sample_is_evidence_error(self):
        raw = fake_raw(sx=[0, -1, -2, -3], deaths=[0, 0, 0, 0], particles=[1, 1, 1, 1])
        raw['samples'].pop()
        with self.assertRaises(fc.EvidenceError):
            ch.window_density(raw)


class ModeSeparationTests(unittest.TestCase):
    def test_stage_names_cover_eight_features(self):
        self.assertEqual(list(ch.STAGES), list(ab.FEATURES))
        self.assertEqual(len(ch.STAGES), 8)
        self.assertEqual(ch.CHILL, 'classic')
        self.assertEqual(ch.MAIN, 'bad')
        self.assertIn('chill', ch.MODE_NAMES[ch.CHILL])
        self.assertIn('main', ch.MODE_NAMES[ch.MAIN])
        self.assertEqual(ch.case_name('hud', 'control', 'classic', 11, 1), 'hud-control-classic-desktop-s11-w1')

    def test_tiers_use_own_population_spread(self):
        def quad(feature, deltas, cc):
            return {'feature': feature, 'stage': ch.STAGES[feature], 'result': 'PAIRED', 'cases': ['c1', 'k2', 'k3', 'c4'],
                    'pairs': [{'delta_mean_ms': d, 'delta_average_fps': -d / 10, 'delta_p50_ms': d, 'control_fps': 10.0, 'candidate_fps': 11.0} for d in deltas],
                    'control_control': {'delta_mean_ms': cc}, 'feature_active': {'c1': True, 'k2': True, 'k3': True, 'c4': True},
                    'mean_ms': {'c1': 100.0, 'k2': 90.0, 'k3': 90.0, 'c4': 100.0}, 'skipped_draw_calls': {'c1': 0, 'k2': 5, 'k3': 5, 'c4': 0},
                    'matched': {'deaths': {'c1': 0, 'k2': 0, 'k3': 0, 'c4': 0}}}
        chill = ch.tiers([quad('hud', [-6.0, -7.0], 1.0), quad('particles', [-1.0, 1.0], 3.0)], [1.0, 3.0])
        main = ch.tiers([quad('hud', [-6.0, -7.0], 9.0), quad('particles', [-20.0, -25.0], 9.0)], [9.0, 9.0])
        self.assertEqual(chill['noise_threshold_mean_ms'], 3.0)
        self.assertEqual(main['noise_threshold_mean_ms'], 9.0)
        self.assertEqual(chill['rows']['hud']['tier'], 'REPEATED_SAVING')
        self.assertEqual(main['rows']['hud']['tier'], 'NO_BENEFIT')  # same deltas, Main noise larger: never pooled
        self.assertEqual(ch.dominant(chill['rows'])['dominant'], 'hud')
        self.assertEqual(ch.dominant(main['rows'])['dominant'], 'particles')
        self.assertTrue(ch.dominant(ch.tiers([quad('hud', [-1.0, -1.0], 5.0)], [5.0])['rows'])['negative_finding'])

    def test_replay_styles_deterministic_bounded_and_distinct(self):
        self.assertEqual(ch.replay_script(4, 'desktop', 16000, 'screening'), fc.replay_script(4, 'desktop', 16000))
        for style, box in ch.REPLAY_STYLES.items():
            if box is None:
                continue
            a, b = ch.replay_script(1, 'desktop', 16000, style), ch.replay_script(1, 'desktop', 16000, style)
            self.assertEqual(a, b, style)
            self.assertNotEqual(a, ch.replay_script(2, 'desktop', 16000, style), style)
            self.assertNotEqual(fc.replay_sha256(a), fc.replay_sha256(fc.replay_script(1, 'desktop', 16000)))
            for ev in a:
                self.assertIn(ev['type'], ('start', 'end'))
                self.assertTrue(box['x'][0] * 1280 <= ev['x'] <= box['x'][1] * 1280, (style, ev))
                self.assertTrue(box['y'][0] * 720 <= ev['y'] <= box['y'][1] * 720, (style, ev))
                self.assertLessEqual(ev['t_ms'], 16000)
            self.assertEqual([e['type'] for e in a[:4]], ['start', 'end', 'start', 'end'])

    def test_no_diagnostic_hooks_or_sampler_in_shipped_runtime(self):
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=fc.ROOT, text=True).splitlines()
        runtime = [n for n in tracked if n.endswith(fc.RUNTIME_SUFFIXES) and not n.startswith('tools/')]
        self.assertGreater(len(runtime), 20)
        for name in runtime:
            text = (fc.ROOT / name).read_text(errors='replace')
            self.assertNotIn(fc.MARKER, text, name)
            self.assertNotIn('skip("', text, name)
            self.assertNotIn('FC.samples', text, name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
