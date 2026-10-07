"""Smoke test for the mobile performance harness (tools/perf_mobile.py)."""
import unittest

import perf_mobile

KEYS = ['rev', 'mode', 'seed', 'frames', 'frame_interval_ms', 'physics_ms', 'draw_ms',
        'physics_steps_per_frame', 'frames_over_16_7ms', 'frames_over_33_4ms',
        'cpu_fps', 'wall_fps', 'page_errors']
GC_KEYS = ['gc_minor_count', 'gc_major_count', 'gc_total_ms', 'allocated_bytes_per_frame']


class PerfMobileTest(unittest.TestCase):
    def test_same_seed_same_input_script(self):
        self.assertEqual(perf_mobile.input_script(1, 20), perf_mobile.input_script(1, 20))
        self.assertNotEqual(perf_mobile.input_script(1, 20), perf_mobile.input_script(2, 20))
        self.assertTrue(perf_mobile.input_script(1, 5))

    def test_five_second_run(self):
        result = perf_mobile.run('worktree', 'bad', 5, 1, log=print)
        for key in KEYS:
            self.assertIn(key, result)
        for key in ('frame_interval_ms', 'physics_ms', 'draw_ms'):
            self.assertEqual(set(result[key]), {'p50', 'p95', 'p99'})
        self.assertGreater(result['frames'], 0)
        self.assertEqual(result['page_errors'], [])
        self.assertEqual(result['emulation']['cpu_throttle_rate'], 4)
        self.assertGreater(result['touchstarts_received'], 0)
        # The window is --seconds, not "until the last touch returns".
        self.assertLess(abs(result['wall_seconds'] - 5), 1.0)
        # Touches fire on the page clock: never early, and late by at most
        # about one main-thread gap (no accumulated schedule slip).
        self.assertGreater(result['input_dispatched'], 0)
        for d in result['input_dispatch']:
            self.assertGreaterEqual(d['offset_ms'], d['t_ms'])
            self.assertLess(d['offset_ms'], result['window_ms'])
        self.assertLessEqual(result['input_lag_ms']['max'], result['max_frame_gap_ms'] + 250)
        # GC trace and heap sampling counters.
        for key in GC_KEYS:
            self.assertIn(key, result)
            self.assertIsNotNone(result[key], key)
            self.assertGreaterEqual(result[key], 0, key)
        for key in ('gc_minor_count', 'gc_major_count'):
            self.assertIsInstance(result[key], int, key)

    def test_layers_run(self):
        result = perf_mobile.run('worktree', 'bad', 5, 1, log=print, trace=False, layers=True)
        self.assertEqual(result['page_errors'], [])
        self.assertEqual(list(result['layers_ms']), perf_mobile.LAYERS)
        # The bloom pass runs between the world effects and the HUD.
        self.assertIn('drawBloomLayer', perf_mobile.LAYERS)
        self.assertLess(perf_mobile.LAYERS.index('drawParticlesAndTrailsLayer'),
                        perf_mobile.LAYERS.index('drawBloomLayer'))
        self.assertLess(perf_mobile.LAYERS.index('drawBloomLayer'), perf_mobile.LAYERS.index('drawUILayer'))
        # The colour grade covers the world and the bloom, not the HUD.
        self.assertLess(perf_mobile.LAYERS.index('drawBloomLayer'),
                        perf_mobile.LAYERS.index('drawColorGradeLayer'))
        self.assertLess(perf_mobile.LAYERS.index('drawColorGradeLayer'), perf_mobile.LAYERS.index('drawUILayer'))
        for name, ms in result['layers_ms'].items():
            self.assertIsNotNone(ms['p50'], name)
            self.assertIsNotNone(ms['p95'], name)
        for key in ('gradients_per_frame', 'shadow_draws_per_frame',
                    'offscreen_element_draws_per_frame', 'element_draws_per_frame'):
            self.assertGreaterEqual(result[key]['mean'], 0, key)
        self.assertGreater(result['element_draws_per_frame']['mean'], 0)
        self.assertLessEqual(result['offscreen_element_draws_per_frame']['mean'],
                             result['element_draws_per_frame']['mean'])

    def test_gc_stats_window_and_thread(self):
        mark = {'name': perf_mobile.T0_MARK, 'ph': 'R', 'pid': 1, 'tid': 2, 'ts': 1000}
        events = [mark,
                  {'name': 'MinorGC', 'ph': 'X', 'pid': 1, 'tid': 2, 'ts': 2000, 'dur': 500},
                  {'name': 'MajorGC', 'ph': 'B', 'pid': 1, 'tid': 2, 'ts': 3000},
                  {'name': 'MajorGC', 'ph': 'E', 'pid': 1, 'tid': 2, 'ts': 4500},
                  {'name': 'MinorGC', 'ph': 'X', 'pid': 1, 'tid': 9, 'ts': 2000, 'dur': 500},
                  {'name': 'MinorGC', 'ph': 'X', 'pid': 1, 'tid': 2, 'ts': 500, 'dur': 500},
                  {'name': 'MinorGC', 'ph': 'X', 'pid': 1, 'tid': 2, 'ts': 1001001, 'dur': 500}]
        self.assertEqual(perf_mobile.gc_stats(events, 1),
                         {'gc_minor_count': 1, 'gc_major_count': 1, 'gc_total_ms': 2.0})


if __name__ == '__main__':
    unittest.main()
