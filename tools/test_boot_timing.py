"""TASK-887: smoke test of the boot timing harness and the steady-state picture check.

- tools/boot_timing.py, 1 size x 1 run with --profile on the source tree: every timing field and every
  profiled cache builder is a positive number (at TASK-887's HEAD all of them run during boot), the
  medians equal the single run, and --compare of the result with itself gives 0 everywhere.
- tools/test_boot_steady_state.py: a boot recorded as a reference and compared against itself (the
  same PNG) reports 0 differing pixels; a second boot of the same tree compared with it runs and
  reports a well-formed entry (max channel diff, differing-pixel count).
- the SCREEN MATRIX has 13 sizes and the TIMING SET is a subset of it.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import boot_timing as bt  # noqa: E402
import test_boot_steady_state as ss  # noqa: E402

SIZE = 'desktop-1280x720@1'


class BootTimingTest(unittest.TestCase):
    def test_matrix(self):
        self.assertEqual(len(bt.SCREEN_MATRIX), 13)
        self.assertEqual(len(set(bt.SCREEN_MATRIX)), 13)
        self.assertTrue(set(bt.TIMING_SET) <= set(bt.SCREEN_MATRIX))
        self.assertEqual(bt.TIMING_SET, ['desktop-1920x1080@1', 'desktop-1366x768@1',
                                         'desktop-1280x720@2', 'pixel7-landscape'])

    def test_one_boot_fields_positive(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 't.json'
            subprocess.run([sys.executable, str(TOOLS / 'boot_timing.py'), '--sizes', SIZE, '--runs', '1',
                            '--profile', '--out', str(out)], check=True, cwd=str(TOOLS),
                           stdout=subprocess.DEVNULL)
            result = json.loads(out.read_text())
            entry = result['sizes'][SIZE]
            self.assertEqual(len(entry['runs']), 1)
            for k in bt.METRICS:
                v = entry['median'][k]
                self.assertIsInstance(v, (int, float), k)
                self.assertGreater(v, 0, k)
                self.assertEqual(v, entry['runs'][0][k], k)
            m = entry['median']
            self.assertLessEqual(m['dcl_ms'], m['load_ms'])
            self.assertLessEqual(m['first_frame_ms'], m['run_ready_ms'])
            self.assertLessEqual(m['first_paint_ms'], m['run_ready_ms'])
            for k in list(bt.PROFILED_FUNCTIONS) + ['profiled_total_ms', 'run_ready_ms']:
                v = entry['profile_median'][k]
                self.assertIsInstance(v, (int, float), k)
                self.assertGreater(v, 0, k)
            self.assertEqual(result['meta']['page_error_count'], 0, result['meta']['page_errors'])
            # A/A compare of a file with itself
            cmp_out = Path(d) / 'c.json'
            subprocess.run([sys.executable, str(TOOLS / 'boot_timing.py'), '--compare', str(out), str(out),
                            '--out', str(cmp_out)], check=True, cwd=str(TOOLS), stdout=subprocess.DEVNULL)
            spread = json.loads(cmp_out.read_text())
            self.assertTrue(spread['max_abs_rel_by_metric'])
            self.assertTrue(all(v == 0 for v in spread['max_abs_rel_by_metric'].values()), spread)

    def test_steady_state_self_compare(self):
        shots, errors = ss.capture_all(sizes=[SIZE], frames=30, log=lambda s: None)
        self.assertEqual(errors, [])
        with tempfile.TemporaryDirectory() as d:
            ref = Path(d) / 'ref'
            manifest = ss.record(ref, shots, ss.meta_for(None, None, 30, '', errors))
            self.assertTrue((ref / (SIZE + '.png')).exists())
            self.assertTrue((Path(d) / 'ref.json').exists())
            self.assertEqual(manifest['captures'][SIZE]['width'], 1280)
            same = ss.compare_to_ref(ref, shots, ss.meta_for(None, None, 30, '', errors))
            self.assertEqual(same['sizes'][SIZE]['differing_pixels'], 0)
            self.assertEqual(same['sizes'][SIZE]['max_channel_diff'], 0)
            again, errors2 = ss.capture_all(sizes=[SIZE], frames=30, log=lambda s: None)
            self.assertEqual(errors2, [])
            report = ss.compare_to_ref(ref, again, ss.meta_for(None, None, 30, '', errors2))
            e = report['sizes'][SIZE]
            self.assertIn('max_channel_diff', e)
            self.assertIn('differing_pixels', e)
            self.assertEqual(report['summary']['errors'], 0)


if __name__ == '__main__':
    unittest.main()
