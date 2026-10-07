"""Regression checks for evidence validation and the mobile acceptance budget."""
import json
from pathlib import Path
import tempfile
import unittest

from perf_gate import report


class PerfGateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name) / 'baseline'
        self.current = Path(directory.name) / 'current'
        for directory, revision in ((self.base, 'baseline'), (self.current, 'head')):
            directory.mkdir()
            for mode in ('bad', 'classic'):
                for suffix in ('notrace-1', 'notrace-2', 'notrace-3', 'traced-1'):
                    run = dict(rev=revision, mode=mode, seconds=20, seed=1,
                               frames=30, page_errors=[], layers_ms={'world': {}},
                               emulation={'cpu_throttle_rate': 4},
                               draw_ms={'p95': 10}, shadow_draws_per_frame={'mean': 2},
                               gradients_per_frame={'mean': 1},
                               allocated_bytes_per_frame=100 if suffix == 'traced-1' else None)
                    (directory / f'{mode}-{suffix}.json').write_text(json.dumps(run))

    def change(self, suffix, key, value):
        path = self.current / f'bad-{suffix}.json'
        run = json.loads(path.read_text())
        run[key] = value
        path.write_text(json.dumps(run))

    def test_median_and_inclusive_timing_limit(self):
        for i, value in enumerate((1, 12.5, 100), 1):
            self.change(f'notrace-{i}', 'draw_ms', {'p95': value})
        output, passed = report(self.base, self.current, 'head')
        self.assertTrue(passed)
        self.assertIn('| draw_ms.p95 | 10 | 12.5 | 1.250000 | 12.5 | PASS |', output)
        self.change('notrace-2', 'draw_ms', {'p95': 12.501})
        self.assertFalse(report(self.base, self.current, 'head')[1])

    def test_each_counter_gate_can_fail_independently(self):
        for key in ('shadow_draws_per_frame', 'gradients_per_frame'):
            with self.subTest(key=key):
                for i in (1, 2, 3):
                    self.change(f'notrace-{i}', key, {'mean': 3})
                self.assertFalse(report(self.base, self.current, 'head')[1])
                for i in (1, 2, 3):
                    self.change(f'notrace-{i}', key, {'mean': 0})
        self.change('traced-1', 'allocated_bytes_per_frame', 101)
        self.assertFalse(report(self.base, self.current, 'head')[1])

    def test_reject_invalid_evidence(self):
        path = self.current / 'bad-notrace-1.json'
        original = path.read_text()
        for key, value in (('rev', 'wrong'), ('seconds', 5), ('page_errors', ['error']),
                           ('allocated_bytes_per_frame', 100), ('draw_ms', {'p95': float('nan')}),
                           ('emulation', {'cpu_throttle_rate': 1})):
            with self.subTest(key=key):
                path.write_text(original)
                self.change('notrace-1', key, value)
                with self.assertRaises(ValueError):
                    report(self.base, self.current, 'head')
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            report(self.base, self.current, 'head')

    def test_reject_diagnostic_runs_even_when_under_budget(self):
        path = self.current / 'bad-notrace-1.json'
        original = path.read_text()
        for key, value in (
                ('diagnostic', True),
                ('diagnostic_override', 'disableBloom()'),
                ('context_options', 'willReadFrequently:true'),
                ('experiment', {'diagnostic_override': 'disableLightmap()'}),
                ('experiment', {'subphases': {'bloom.blur': {'p95': 1}}})):
            with self.subTest(key=key, value=value):
                path.write_text(original)
                self.change('notrace-1', key, value)
                with self.assertRaisesRegex(ValueError, 'diagnostic run'):
                    report(self.base, self.current, 'head')
        path.write_text(original)
        self.change('notrace-1', 'experiment', {'diagnostic_override': ''})
        self.assertTrue(report(self.base, self.current, 'head')[1])


if __name__ == '__main__':
    unittest.main()
