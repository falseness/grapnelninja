"""Complete sealed SYNTHETIC 50-FPS fixtures are validator-only, never release proof."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import build_playgama as build
import playgama_release_fps as gate
from test_playgama_fps_gate import trace as legacy_trace


def trace(intervals):
    raw = legacy_trace(intervals)
    for frame in raw['frames']:
        for side in ('before', 'after'):
            frame[side] = dict.fromkeys(gate.ACTIVITY_FLAGS, False)
    return raw


def dispatch(raw):
    """Replay the PROBE input loop over raw frames, as the browser would."""
    raw['inputs'], active, previous, pending = [], 0, None, copy.deepcopy(gate.INPUT)
    for frame in raw['frames']:
        live = not any(frame['before'].values())
        if previous and live and not any(previous['after'].values()):
            active += frame['t'] - previous['t']
        while live and pending and pending[0]['at_active_ms'] <= active:
            raw['inputs'].append(dict(pending.pop(0), actual_active_ms=active, t=frame['t']))
        frame['activeMs'] = active; previous = frame
    assert not pending, 'synthetic trace too short for INPUT'
    return raw


def pause(raw, first, last):
    for frame in raw['frames'][first:last+1]:
        frame['before']['pause'] = frame['after']['pause'] = True
    return raw


def make_release(out):
    revision, files = build.runtime('HEAD', gate.git('rev-parse', 'HEAD').decode().strip())
    packed = build.bundle(files)
    archive = out/'release.zip'
    archive.write_bytes(build.archive(packed))
    gate.write(out/'source.json', dict(revision=revision, base_revision=revision,
        source='git blobs only', build_version=re.search(r"buildVersion:\s*'([^']+)'", files['platform.js'].decode()).group(1)))
    runtime = out/'runtime'; runtime.mkdir()
    for name, data in packed.items(): (runtime/name).write_bytes(data)
    return runtime, archive


def fixture(out, engine, identity, intervals=None, prepare=lambda raw: raw):
    out.mkdir()
    executable = Path('/opt/google/chrome/chrome') if engine == 'chrome' else next(Path('/root/.cache/ms-playwright').glob('firefox-*/firefox/firefox'))
    executable = executable.resolve()
    options = {'headless': True}
    if engine == 'chrome': options['channel'] = 'chrome'
    browser = dict(engine=engine, pid=1, version='SYNTHETIC validator-only',
        executable_path=str(executable), executable_sha256=gate.sha(executable.read_bytes()),
        launch_arguments=[str(executable), '-juggler-pipe' if engine == 'firefox' else '--remote-debugging-pipe'],
        launch_options=options, channel=options.get('channel'))
    (out/'command.log').write_text('SYNTHETIC validator-only 50-FPS fixture; not browser performance\nLAUNCH '+json.dumps(browser)+'\n')
    gate.write(out/'protocol.json', gate.protocol(engine, identity))
    data = dict(smoke=False, fixture_sha256=gate.sha(gate.FIXTURE.encode()), errors=[],
        origin='http://127.0.0.1:12345', environment={'browsers': {engine: browser}}, runs=[])
    for mode, number in gate.protocol(engine, identity)['order']:
        raw = dispatch(prepare(trace(intervals or [5000]+[20]*1500)))
        raw.update(done=True, mode=mode, run=number, transitions=[{'synthetic': True}],
            state={'mode': mode}, seed=gate.SEED, input_policy=gate.INPUT, source_sha256=identity['members'],
            layout=dict(viewport=[844, 390], dpr=2, backing=[1688, 780], css=[844, 390], logical=[2337, 1080]))
        name = f'{engine}-{mode}-{number}-raw.json'
        gate.write(out/name, raw)
        data['runs'].append(dict(engine=engine, mode=mode, run=number, raw=name, metrics=gate.active_metrics(raw)))
    gate.write(out/'results.json', data)
    gate.write(out/'network.json', [{'url': gate.SDK, 'action': 'SDK_STUB'}])
    reseal(out)


def reseal(out):
    gate.seal(out, dict(command=['SYNTHETIC validator-only'], cwd=str(gate.ROOT),
        started_utc=gate.utc(), ended_utc=gate.utc(), duration_seconds=0, exit_code=0,
        source_revision=gate.git('rev-parse', 'HEAD').decode().strip(), tool_sha256=gate.tool_identity()))


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(os.environ.get('RELEASE_FPS_EVIDENCE_DIR', cls.temp.name))
        cls.root.mkdir(parents=True, exist_ok=True)
        cls.runtime, cls.archive = make_release(cls.root)
        cls.identity = gate.release_identity(cls.runtime, cls.archive)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_complete_sealed_boundaries_and_combine(self):
        for label, intervals, expected in (
            ('above-30', [5000]+[20]*1500, 'PASS'),
            ('exactly-30', [5000]+[25, 25, 50]*300, 'FAIL'),
            ('below-30', [5000]+[40]*750, 'FAIL')):
            paths = []
            for engine in ('firefox', 'chrome'):
                out = self.root/f'{label}-{engine}'; paths.append(out)
                fixture(out, engine, self.identity, intervals)
                before = {p.name: gate.sha(p.read_bytes()) for p in out.iterdir()}
                result = gate.evaluate(out, self.runtime, self.archive)
                self.assertEqual(result['gate'], expected)
                self.assertEqual(before, {p.name: gate.sha(p.read_bytes()) for p in out.iterdir()})
                print(f'PASS sealed {engine} {label}: {expected}; SYNTHETIC validator-only')
            result = gate.combine(*paths, self.runtime, self.archive)
            self.assertEqual(len(result['runs']), 12)
            self.assertEqual(result['gate'], expected)
            gate.write(self.root/f'combine-{label}.json', result)
            print(f'PASS combine twelve per-run metrics exact ZIP sha256={result["release"]["zip"]["sha256"]}; SYNTHETIC validator-only')

    def test_invalid_complete_sealed_cases(self):
        cases = ('missing-run', 'duplicate-run', 'wrong-mode', 'chromium-as-chrome',
            'short-duration', 'wrong-layout', 'identity-mismatch', 'omitted-seal', 'tampering',
            'shortened-smoke', 'wrong-protocol', 'unsealed-raw', 'bad-metric', 'missing-log')
        for label in cases:
            out = self.root/label
            fixture(out, 'chrome', self.identity)
            data = gate.read(out/'results.json')
            rawpath = out/data['runs'][0]['raw']; raw = gate.read(rawpath)
            if label == 'missing-run': data['runs'].pop()
            elif label == 'duplicate-run': data['runs'][-1] = data['runs'][0]
            elif label == 'wrong-mode': raw['state']['mode'] = 'classic-wrong'
            elif label == 'chromium-as-chrome': data['environment']['browsers']['chrome']['executable_path'] = '/usr/bin/chromium'
            elif label == 'short-duration': raw['frames'] = trace([5000, 100])['frames']
            elif label == 'wrong-layout': raw['layout']['logical'] = [1688, 780]
            elif label == 'identity-mismatch': raw['source_sha256'] = {}
            elif label == 'shortened-smoke': data['smoke'] = True
            elif label == 'wrong-protocol':
                p = gate.read(out/'protocol.json'); p['seed'] = 293; gate.write(out/'protocol.json', p)
            elif label == 'unsealed-raw': data['runs'][0]['raw'] = '../outside.json'
            elif label == 'bad-metric': data['runs'][0]['metrics']['average_fps'] = 99
            elif label == 'missing-log': (out/'command.log').unlink()
            gate.write(rawpath, raw); gate.write(out/'results.json', data); reseal(out)
            if label == 'omitted-seal': (out/'seal.json').unlink()
            if label == 'tampering': rawpath.write_text('{}')
            with self.assertRaises((AssertionError, ValueError, KeyError, OSError)):
                gate.evaluate(out, self.runtime, self.archive)
            print(f'PASS {label}: INVALID; sealed SYNTHETIC validator-only negative fixture')

    def test_complete_sealed_malformed_activity_states(self):
        # Every case has all six sealed runs. Mutate the last run's final
        # snapshot too: arithmetic does not consult that final `after` map.
        cases = [('empty-all', None, None)]
        for side in ('before', 'after'):
            cases.extend((f'{side}-{label}', side, value) for label, value in (
                ('missing-snapshot', 'missing'), ('null-snapshot', None),
                ('list-snapshot', []), ('unknown-flag', {'unknown': False})))
            for flag in sorted(gate.ACTIVITY_FLAGS):
                cases.append((f'{side}-missing-{flag}', side, (flag, 'missing')))
                for label, value in (('integer-zero', 0), ('integer-one', 1),
                                     ('string', 'false'), ('null', None),
                                     ('list', []), ('map', {})):
                    cases.append((f'{side}-{flag}-{label}', side, (flag, value)))
        for label, side, value in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory(dir=self.root) as d:
                out = Path(d)/'capture'
                fixture(out, 'chrome', self.identity)
                data = gate.read(out/'results.json')
                self.assertEqual(len(data['runs']), 6)
                targets = data['runs'] if side is None else data['runs'][-1:]
                for run in targets:
                    path = out/run['raw']; raw = gate.read(path)
                    if side is None:
                        for frame in raw['frames']:
                            frame['before'] = {}; frame['after'] = {}
                    else:
                        frame = raw['frames'][-1]
                        if isinstance(value, tuple):
                            flag, replacement = value
                            if replacement == 'missing': del frame[side][flag]
                            else: frame[side][flag] = replacement
                        elif value == 'missing': del frame[side]
                        elif isinstance(value, dict): frame[side].update(value)
                        else: frame[side] = value
                    gate.write(path, raw)
                reseal(out)
                output = io.StringIO()
                argv = ['playgama_release_fps.py', 'evaluate', '--capture', str(out),
                        '--runtime', str(self.runtime), '--zip', str(self.archive)]
                with patch('sys.argv', argv), contextlib.redirect_stderr(output), \
                        patch.object(gate, 'active_metrics', wraps=gate.active_metrics) as metrics:
                    self.assertEqual(gate.main(), 2)
                self.assertIn('INVALID evidence: invalid activity state:', output.getvalue())
                self.assertEqual(metrics.call_count, 0 if side is None else 5)
                print(f'PASS sealed six-run {label}: {output.getvalue().strip()}; '
                      'exit=2; rejected before affected-run metrics; SYNTHETIC validator-only')

    def evaluate_main(self, out):
        output = io.StringIO()
        argv = ['playgama_release_fps.py', 'evaluate', '--capture', str(out),
                '--runtime', str(self.runtime), '--zip', str(self.archive)]
        with patch('sys.argv', argv), contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()), \
                patch.object(gate, 'active_metrics', wraps=gate.active_metrics) as metrics:
            code = gate.main()
        return code, output.getvalue().strip(), metrics.call_count

    def test_complete_sealed_valid_input_timing(self):
        gap = dict(intervals=[5000]+[20]*200+[9999]+[20]*1500, prepare=lambda raw: pause(raw, 201, 203))
        for label, options in (('default', {}), ('delayed-by-slow-frame', dict(intervals=[5000]+[20]*500+[3000]+[20]*1500)),
                               ('inactive-gap', gap)):
            with tempfile.TemporaryDirectory(dir=self.root) as d:
                out = Path(d)/'capture'
                fixture(out, 'chrome', self.identity, **options)
                data = gate.read(out/'results.json')
                self.assertEqual(len(data['runs']), 6)
                raw = gate.read(out/data['runs'][-1]['raw'])
                frames = {f['t']: f for f in raw['frames']}
                self.assertEqual(len(raw['inputs']), len(gate.INPUT))
                if label == 'delayed-by-slow-frame':
                    slow = raw['frames'][502]['t']
                    self.assertEqual([e['at_active_ms'] for e in raw['inputs'] if e['t'] == slow], list(range(15500, 18001, 500)))
                    self.assertEqual(raw['frames'][502]['t'] - raw['frames'][501]['t'], 3000)
                if label == 'inactive-gap':
                    self.assertFalse(any(any(frames[e['t']]['before'].values()) for e in raw['inputs']))
                    self.assertEqual(next(e for e in raw['inputs'] if e['at_active_ms'] == 9000)['t'], raw['frames'][205]['t'])
                    self.assertEqual(raw['frames'][204]['activeMs'], 8980)
                code, output, calls = self.evaluate_main(out)
                self.assertEqual((code, output, calls), (0, '', 6))
                print(f'PASS sealed six-run valid {label}: accepted exit=0; inputs bound to first eligible active frames; SYNTHETIC validator-only')

    def test_complete_sealed_invalid_input_timing(self):
        def event(raw, index=30): return raw['inputs'][index]
        def frame_of(raw, e): return next(i for i, f in enumerate(raw['frames']) if f['t'] == e['t'])
        def rebind(raw, offset):
            e = event(raw); f = raw['frames'][frame_of(raw, e)+offset]
            e.update(t=f['t'], actual_active_ms=f['activeMs'])
        def swap(raw):
            a, b = event(raw, 30), event(raw, 31)
            (a['t'], a['actual_active_ms']), (b['t'], b['actual_active_ms']) = (b['t'], b['actual_active_ms']), (a['t'], a['actual_active_ms'])
        def inactive(raw):
            f = raw['frames'][202]; self.assertTrue(f['before']['pause'])
            event(raw, 18).update(t=f['t'], actual_active_ms=f['activeMs'])
        def all_events(update):
            def apply(raw):
                for e in raw['inputs']: update(e)
            return apply
        gap = dict(intervals=[5000]+[20]*200+[9999]+[20]*1500, prepare=lambda raw: pause(raw, 201, 203))
        cases = [
            ('missing-all-runs', True, {}, all_events(lambda e: (e.pop('actual_active_ms'), e.pop('t')))),
            ('false-all-runs-minus-one', True, {}, all_events(lambda e: e.update(actual_active_ms=-1, t=-1))),
            ('missing-actual', False, {}, lambda raw: event(raw).pop('actual_active_ms')),
            ('missing-t', False, {}, lambda raw: event(raw).pop('t')),
            ('null-actual', False, {}, lambda raw: event(raw).update(actual_active_ms=None)),
            ('nan-actual', False, {}, lambda raw: event(raw).update(actual_active_ms=float('nan'))),
            ('infinite-actual', False, {}, lambda raw: event(raw).update(actual_active_ms=float('-inf'))),
            ('nan-t', False, {}, lambda raw: event(raw).update(t=float('nan'))),
            ('infinite-t', False, {}, lambda raw: event(raw).update(t=float('inf'))),
            ('boolean-actual', False, {}, lambda raw: event(raw).update(actual_active_ms=True)),
            ('string-t', False, {}, lambda raw: event(raw).update(t=str(event(raw)['t']))),
            ('negative-actual', False, {}, lambda raw: event(raw).update(actual_active_ms=-1)),
            ('negative-t', False, {}, lambda raw: event(raw).update(t=-1)),
            ('out-of-trace-between-frames', False, {}, lambda raw: event(raw).update(t=event(raw)['t']+0.5)),
            ('out-of-trace-after-last-frame', False, {}, lambda raw: event(raw).update(t=raw['frames'][-1]['t']+20)),
            ('mismatched-actual', False, {}, lambda raw: event(raw).update(actual_active_ms=event(raw)['actual_active_ms']+1)),
            ('early-previous-frame', False, {}, lambda raw: rebind(raw, -1)),
            ('late-next-frame', False, {}, lambda raw: rebind(raw, 1)),
            ('reordered-swapped-timings', False, {}, swap),
            ('inactive-frame', False, gap, inactive)]
        for label, every, options, mutate in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory(dir=self.root) as d:
                out = Path(d)/'capture'
                fixture(out, 'chrome', self.identity, **options)
                data = gate.read(out/'results.json')
                self.assertEqual(len(data['runs']), 6)
                for run in data['runs'] if every else data['runs'][-1:]:
                    path = out/run['raw']; raw = gate.read(path); mutate(raw); gate.write(path, raw)
                reseal(out)
                code, output, calls = self.evaluate_main(out)
                self.assertEqual(code, 2)
                self.assertRegex(output, r'^INVALID evidence: (invalid input timing|input timing outside trace|'
                                 r'input timing not bound to active frame|input not dispatched on first eligible active frame)')
                self.assertEqual(calls, 0 if every else 5)
                print(f'PASS sealed six-run {label}: {output}; exit=2; rejected before affected-run metrics; SYNTHETIC validator-only')

    def test_zip_extraction_and_committed_build(self):
        extra = self.runtime/'extra.txt'; extra.write_text('extra')
        try:
            with self.assertRaisesRegex(AssertionError, 'exact ZIP extraction'): gate.release_identity(self.runtime, self.archive)
        finally: extra.unlink()
        original = self.archive.read_bytes()
        try:
            self.archive.write_bytes(original+b'changed')
            with self.assertRaisesRegex(AssertionError, 'committed build'): gate.release_identity(self.runtime, self.archive)
        finally: self.archive.write_bytes(original)
        print('PASS exact extraction and archive byte identity; packaged bundle differs from raw committed checkout')

    def test_inactive_gap_and_death_ending(self):
        raw = trace([5000, 2000, 99999]+[20]*1400)
        raw['frames'][2]['after']['death'] = True
        gate.validate_activity_states(raw)
        metrics = gate.active_metrics(raw)
        self.assertEqual(metrics['measured_ms'], 30000)
        self.assertEqual(metrics['excluded_gap_ms'], 99999)
        self.assertEqual(metrics['interval_count'], 1401)
        gate.write(self.root/'death-gap.json', raw)
        print('PASS inactive-gap exclusion 99999 ms; death-ending slow frame 2000 ms retained; SYNTHETIC validator-only')


if __name__ == '__main__': unittest.main()
