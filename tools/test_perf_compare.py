"""Evidence integrity checks for paired diagnostics (no browser needed)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import perf_compare


class PerfCompareTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.probe = self.root / 'probe.js'
        self.probe.write_text('BloomRenderer.prototype.drawEmissiveShapes = function() {};')
        self.output = self.root / 'results'
        self.instrument = perf_compare.perf_mobile.INSTRUMENT_SCRIPT

    def run_compare(self, measure):
        with patch.object(perf_compare.subprocess, 'check_output', return_value='sha\n'), \
                patch.object(perf_compare.perf_mobile, 'run', side_effect=measure):
            perf_compare.compare('HEAD', self.probe, self.output)

    def test_alternating_runs_preserve_overrides_and_cannot_enter_acceptance(self):
        calls = []

        def measure(rev, mode, seconds, seed, **kwargs):
            calls.append((rev, mode, seconds, seed, kwargs['trace'], kwargs['layers'],
                          perf_compare.perf_mobile.INSTRUMENT_SCRIPT))
            return {'page_errors': [], 'frames': 30, 'input_dispatched': 4,
                    'draw_ms': {'p95': 10 if len(calls) % 2 else 20}}

        self.run_compare(measure)
        self.assertEqual(len(calls), 12)
        config = json.loads((self.output / 'config.json').read_text())
        self.assertEqual([row[2] for row in config['schedule']],
                         ['normal', 'probe', 'normal', 'probe', 'probe', 'normal',
                          'probe', 'normal', 'normal', 'probe', 'normal', 'probe'])
        for call, (rep, mode, variant) in zip(calls, config['schedule']):
            self.assertEqual(call[:6], ('sha', mode, 20, 1, False, True))
            stem = self.output / variant / f'{mode}-{rep}'
            run = json.loads(stem.with_suffix('.json').read_text())
            self.assertTrue(run['diagnostic'])
            override = self.probe.read_text() if variant == 'probe' else ''
            self.assertEqual(run['experiment']['diagnostic_override'], override)
            if variant == 'normal':
                self.assertEqual(call[6], self.instrument)
            else:
                self.assertIn(override, call[6])
            self.assertEqual(stem.with_suffix('.exit').read_text(), '0\n')
            self.assertIn('measurement.exit=0', stem.with_suffix('.log').read_text())
        self.assertEqual(perf_compare.perf_mobile.INSTRUMENT_SCRIPT, self.instrument)
        summary = (self.output / 'comparison.md').read_text()
        self.assertIn('Diagnostic only', summary)
        for mode in ('bad', 'classic'):
            self.assertIn(f'| {mode} | [10, 20, 10] | [20, 10, 20] | 10 | 20 | 1/3 |', summary)
        self.assertEqual((self.output / 'run.exit').read_text(), '0\n')
        with self.assertRaises(FileExistsError):
            self.run_compare(measure)
        self.assertEqual(len(calls), 12)

    def test_invalid_measurement_saved_and_stops_matrix(self):
        for changes in ({'page_errors': ['broken']}, {'frames': 0}, {'input_dispatched': 0}):
            with self.subTest(changes=changes):
                self.output = self.root / str(len(list(self.root.iterdir())))
                result = {'page_errors': [], 'frames': 30, 'input_dispatched': 4,
                          'draw_ms': {'p95': 1}, **changes}
                with self.assertRaisesRegex(ValueError, 'Invalid measurement'):
                    self.run_compare(lambda *args, **kwargs: result.copy())
                self.assertEqual(len(list(self.output.glob('*/*.json'))), 1)
                stem = self.output / 'normal' / 'bad-1'
                self.assertEqual(stem.with_suffix('.exit').read_text(), '1\n')
                self.assertIn('measurement.exit=1', stem.with_suffix('.log').read_text())
                self.assertEqual((self.output / 'run.exit').read_text(), '1\n')
                self.assertFalse((self.output / 'comparison.md').exists())
                self.assertEqual(perf_compare.perf_mobile.INSTRUMENT_SCRIPT, self.instrument)

    def test_browser_failure_restores_harness_and_records_failure(self):
        calls = 0

        def fail_on_probe(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {'page_errors': [], 'frames': 30, 'input_dispatched': 4,
                        'draw_ms': {'p95': 1}}
            self.assertIn(self.probe.read_text(), perf_compare.perf_mobile.INSTRUMENT_SCRIPT)
            raise RuntimeError('browser failed')

        with self.assertRaisesRegex(RuntimeError, 'browser failed'):
            self.run_compare(fail_on_probe)
        self.assertEqual(calls, 2)
        self.assertEqual(perf_compare.perf_mobile.INSTRUMENT_SCRIPT, self.instrument)
        self.assertTrue((self.output / 'normal' / 'bad-1.json').exists())
        stem = self.output / 'probe' / 'bad-1'
        self.assertFalse(stem.with_suffix('.json').exists())
        self.assertEqual(stem.with_suffix('.exit').read_text(), '1\n')
        self.assertIn('browser failed', stem.with_suffix('.log').read_text())
        self.assertEqual((self.output / 'run.exit').read_text(), '1\n')


if __name__ == '__main__':
    unittest.main()
