"""Boundary and state-exclusion checks for the mandatory active-FPS gate."""
import copy
import contextlib
import io
import json
import unittest
import tempfile
import os
import shutil
from pathlib import Path
from test_playgama_render_compare import capture_fixture, LAYOUT_CASES
from playgama_render_compare import ROOT, aggregate, audit, PROTOCOL, LEGACY_MODE_LABELS, read, write, sha, summarize
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


class FPSProtocolTests(unittest.TestCase):
    """Complete sealed synthetic validator evidence; never browser FPS proof."""

    def reseal(self, out, protocol):
        write(out/'protocol.json', protocol)
        receipt = read(out/'manifest.json')
        receipt['evidence_sha256'] = {
            p.name: sha(p.read_bytes()) for p in out.iterdir()
            if p.name != 'manifest.json'}
        write(out/'manifest.json', receipt)

    def archive(self, out, name):
        if evidence := os.environ.get('FPS_PROTOCOL_EVIDENCE_DIR'):
            shutil.copytree(out, Path(evidence)/name)

    def test_complete_evaluate_current_and_legacy(self):
        for name, intervals, fps, verdict in (
                ('passing', [5000]+[20]*1500, 50, 'PASS'),
                ('exactly-30', [5000]+[25, 25, 50]*300, 30, 'FAIL'),
                ('below-30', [5000]+[40]*750, 25, 'FAIL')):
            with self.subTest(case=name), tempfile.TemporaryDirectory() as d:
                out = Path(d)
                capture_fixture(out)
                data = read(out/'results.json')
                for run in data['runs']:
                    sample = read(out/run['raw'])
                    sample['frames'] = trace(intervals)['frames']
                    run['metrics'] = summarize(sample)
                    write(out/run['raw'], sample)
                data['comparison'] = aggregate(data['runs'])
                write(out/'results.json', data)
                results = []
                for label, labels in (('current', PROTOCOL['mode_labels']),
                                      ('legacy', LEGACY_MODE_LABELS)):
                    self.reseal(out, dict(PROTOCOL, mode_labels=dict(labels)))
                    before = {p.name: p.read_bytes() for p in out.iterdir()}
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                        result = evaluate(out, ROOT, 'candidate')
                    self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)
                    self.assertEqual(result['gate'], verdict)
                    self.assertEqual([(r['mode'], r['run']) for r in result['runs']],
                                     [(m, p) for m in ('classic', 'bad') for p in (1, 2, 3)])
                    for row in result['runs']:
                        self.assertEqual(row['average_fps'], fps)
                        self.assertEqual(row['gate'], verdict)
                    if label == 'legacy':
                        self.assertIn('PASS known legacy labels explicitly normalized', output.getvalue())
                    print(output.getvalue(), end='')
                    print(f'PASS {label} labels evaluate; case={name}; gate={verdict}; '
                          f'protocol bytes/hash unchanged SHA256={sha(before["protocol.json"])}; '
                          'all sealed bytes unchanged; SYNTHETIC validator evidence only')
                    print(json.dumps(result, sort_keys=True))
                    results.append(result)
                    self.archive(out, f'{name}-{label}')
                self.assertEqual(results[0], results[1])
                print(f'PASS identical six per-mode FPS metrics and gate verdicts; case={name}; '
                      f'average_fps={fps}; gate={verdict}; raw mode IDs/measurements preserved')

    def test_complete_evaluate_rejects_protocol_changes(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            capture_fixture(out)
            cases = [('unknown labels', 'mode_labels', {'classic': 'Unknown', 'bad': 'Main'}),
                     ('non-label protocol changes', 'seed', PROTOCOL['seed']+1),
                     ('non-label protocol changes', 'warmup_ms', 1),
                     ('non-label protocol changes', 'orders', []),
                     ('non-label protocol changes', 'extra', True)]
            for index, (label, key, value) in enumerate(cases):
                for variant, labels in (('current', PROTOCOL['mode_labels']),
                                        ('legacy', LEGACY_MODE_LABELS)):
                    with self.subTest(key=key, labels=variant):
                        protocol = copy.deepcopy(PROTOCOL)
                        protocol['mode_labels'] = dict(labels)
                        protocol[key] = value
                        self.reseal(out, protocol)
                        before = {p.name: p.read_bytes() for p in out.iterdir()}
                        for check in (lambda: audit(out), lambda: evaluate(out, ROOT, 'candidate')):
                            with self.assertRaisesRegex(AssertionError, '^protocol differs$'):
                                check()
                        self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)
                        self.archive(out, f'rejected-{index}-{variant}')
                        print(f'PASS {label} rejected; field={key}; labels={variant}; '
                              'audit/evaluate reason=protocol differs; all sealed bytes unchanged; '
                              'SYNTHETIC validator evidence only')


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
