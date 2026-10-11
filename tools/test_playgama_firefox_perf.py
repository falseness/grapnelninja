"""Measurement integrity: slow frames and inactive boundaries are not interchangeable."""
import unittest
from playgama_firefox_perf import metrics


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


if __name__ == '__main__':
    unittest.main()
