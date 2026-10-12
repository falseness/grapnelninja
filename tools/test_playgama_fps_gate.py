"""Boundary and state-exclusion checks for the mandatory active-FPS gate."""
import unittest
import tempfile
import os
import shutil
from pathlib import Path
from test_playgama_render_compare import capture_fixture, LAYOUT_CASES
from playgama_render_compare import ROOT, aggregate, audit
from playgama_fps_gate import active_metrics, evaluate


def trace(intervals):
    frames = [dict(t=0, before={'paused': False}, after={'paused': False})]
    for dt in intervals:
        frames.append(dict(t=frames[-1]['t']+dt, before={'paused': False}, after={'paused': False}))
    return {'frames': frames}


class FPSLayoutTests(unittest.TestCase):
    def test_complete_evaluate_layout(self):
        for index, (label, field, value, error) in enumerate(LAYOUT_CASES):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as d:
                out = Path(d)
                runs = capture_fixture(out, field, value)
                if error:
                    with self.assertRaisesRegex(AssertionError, error): aggregate(runs)
                    with self.assertRaisesRegex(AssertionError, error): audit(out)
                    with self.assertRaisesRegex(AssertionError, error): evaluate(out, ROOT, 'candidate')
                else:
                    aggregate(runs)
                    audit(out)
                    result = evaluate(out, ROOT, 'candidate')
                    self.assertEqual(result['gate'], 'PASS')
                    self.assertEqual(len(result['runs']), 6)
                if evidence := os.environ.get('LAYOUT_EVIDENCE_DIR'):
                    shutil.copytree(out, Path(evidence)/f'synthetic-{index}')
                print(f'PASS {label} through aggregate audit evaluate; field={field}; value={value}; SYNTHETIC validator evidence only')


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
