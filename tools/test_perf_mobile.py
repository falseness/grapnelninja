"""Smoke test for the mobile performance harness (tools/perf_mobile.py)."""
import unittest

import perf_mobile

KEYS = ['rev', 'mode', 'seed', 'frames', 'frame_interval_ms', 'physics_ms', 'draw_ms',
        'physics_steps_per_frame', 'frames_over_16_7ms', 'frames_over_33_4ms',
        'cpu_fps', 'wall_fps', 'page_errors']


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


if __name__ == '__main__':
    unittest.main()
