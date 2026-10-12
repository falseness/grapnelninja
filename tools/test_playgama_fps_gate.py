"""Boundary and state-exclusion checks for the mandatory active-FPS gate."""
import unittest
from playgama_fps_gate import active_metrics


def trace(intervals):
    frames = [dict(t=0, before={'paused': False}, after={'paused': False})]
    for dt in intervals:
        frames.append(dict(t=frames[-1]['t']+dt, before={'paused': False}, after={'paused': False}))
    return {'frames': frames}


class FPSGateTests(unittest.TestCase):
    def test_exactly_30_fails(self):
        result = active_metrics(trace([5000]+[1000]*30+[0.001]*870))
        self.assertLess(result['average_fps'], 30)
        self.assertEqual(result['gate'], 'FAIL')
        self.assertEqual(active_metrics(trace([5000]+[25, 25, 50]*300))['average_fps'], 30)
        self.assertEqual(active_metrics(trace([5000]+[25, 25, 50]*300))['gate'], 'FAIL')

    def test_fps_uses_total_time(self):
        result = active_metrics(trace([5000]+[10, 90]*300))
        self.assertEqual(result['average_fps'], 20)
        self.assertEqual(result['p95_ms'], 90)
        self.assertEqual(result['gate'], 'FAIL')
        self.assertEqual(active_metrics(trace([5000]+[20]*1500))['gate'], 'PASS')

    def test_death_ending_retained_inactive_gap_excluded(self):
        raw = trace([5000, 2000, 99999]+[20]*1400)
        raw['frames'][2]['after']['paused'] = True
        result = active_metrics(raw)
        self.assertEqual(result['measured_ms'], 30000)
        self.assertEqual(result['interval_count'], 1401)
        self.assertEqual(result['excluded_gap_ms'], 99999)

    def test_short_or_invalid_capture_rejected(self):
        for intervals in ([5000, 29999], [5000, 30000, 0], [5000, float('nan')]):
            with self.assertRaises(ValueError):
                active_metrics(trace(intervals))


if __name__ == '__main__':
    unittest.main()
