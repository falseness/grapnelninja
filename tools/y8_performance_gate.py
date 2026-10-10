"""TASK-257 matched-density diagnostic. capture then audit; never certifies phones.

The audit exits zero for valid evidence, including an honest FAIL/UNVERIFIED gate.
Every candidate repetition is compared separately; no pooled medians.
"""
import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import y8_fps_baseline as baseline

OUT = baseline.ROOT / 'artifacts/TASK-257'


def metrics(frames):
    assert len(frames) > 1
    assert all(not any(f['state'].values()) for f in frames)
    # Reject interrupted samples rather than silently bridging inactive intervals.
    assert frames[0]['dt'] is None
    assert all(f['dt'] is not None and f['dt'] > 0 for f in frames[1:])
    times = [f['t'] for f in frames]
    assert all(abs(f['dt']-(f['t']-p['t'])) < 1e-6 for p, f in zip(frames, frames[1:]))
    duration = times[-1]-times[0]
    assert duration >= 30000
    # All full rolling windows anchored at frame boundaries, plus the last window.
    starts = [t for t in times if t+10000 <= times[-1]] + [times[-1]-10000]
    windows = [(bisect_right(times, t+10000)-bisect_right(times, t))/10 for t in starts]
    return {'active_ms': duration, 'average_fps': (len(times)-1)*1000/duration,
            'minimum_10s_fps': min(windows), 'windows_below_30': sum(v < 30 for v in windows)}


def build_gate():
    b = json.loads((OUT/'baseline.json').read_text())
    runs = []
    for row in json.loads((OUT/'baseline-runs.json').read_text()):
        raw = json.loads((OUT/row['trace']).read_text())
        runs.append({'id': row['id'], 'rep': row['rep'], 'settings': raw['case'],
                     'dimensions': raw['dimensions'], 'raw_samples': raw['frames'],
                     'metrics': metrics(raw['frames']), 'source_hash':
                     b['identity']['original_y8_commit' if raw['case']['tree']=='reported' else 'candidate_commit']})
    for run in runs:
        candidate = run['settings']['tree']=='candidate'
        control = next(r for r in runs if r['id']==run['id'].replace('candidate-', 'reported-'))
        matched = run['dimensions']==control['dimensions'] and all(
            run['settings'][k]==control['settings'][k] for k in
            ('viewport','device_emulation','DPR','cpu_throttle','seed','input','duration','warmup'))
        assert matched
        qualifies = control['metrics']['average_fps'] >= 55 and control['metrics']['minimum_10s_fps'] >= 55
        m = run['metrics']
        regression = candidate and m['average_fps'] < control['metrics']['average_fps']
        run['thresholds'] = {'baseline_approximately_60_definition': 'average and every full 10s window >=55 FPS',
            'absolute_gate_applicable': qualifies, 'candidate_average_minimum': 55,
            'ten_second_minimum': 30, 'baseline_average_fps': control['metrics']['average_fps'],
            'regression': regression, 'matched_settings': matched,
            'average_55_met': m['average_fps']>=55, 'ten_second_30_met': m['minimum_10s_fps']>=30}
        run['verdict'] = ('BASELINE_ONLY' if not candidate else
            'FAIL_MEASURED_REGRESSION' if regression else
            'FAIL_ABSOLUTE_THRESHOLD' if qualifies and (m['average_fps']<55 or m['minimum_10s_fps']<30) else
            'UNVERIFIED_PHYSICAL_HARDWARE')
    return {'identity': b['identity'], 'environment': b['environment'], 'runs': runs,
            'unsupported': b['unsupported'], 'density': 'matched pinned DPR2 / 1560x780; adaptive fallback disabled',
            'verdict': 'FAIL' if any(r['verdict'].startswith('FAIL') for r in runs) else 'UNVERIFIED',
            'scope': 'Software diagnostic only; user regression unresolved; no equal-quality claim from prior reduced-density runs.'}


def capture():
    baseline.OUT = OUT
    baseline.capture()
    (OUT/'manifest.json').rename(OUT/'capture-manifest.json')
    gate = build_gate()
    baseline.save('performance-gate.json', gate)
    diagnosis = baseline.ROOT/'artifacts/TASK-255/diagnosis.json'
    baseline.save('prior-fix-diagnosis.json', json.loads(diagnosis.read_text()))
    baseline.save('performance-summary.json', {
        'verdict': gate['verdict'], 'user_regression_resolved': False,
        'reproduced_cause': 'TASK-255 isolated combined glow-buffer CPU cost and additive pixel changes; interactive user 60-to-10 FPS cause remains unknown.',
        'fix_effects': {
            'glow_combine_revert': 'Prior fixed-tick CPU submission experiment is copied in prior-fix-diagnosis.json; not an FPS measurement. Current matched-resolution runs measure cumulative current source only.',
            'adaptive_density': 'Disabled in these runs; prior 0.75 versus 2 density FPS gains do not establish equal-quality optimization.',
            'resize_deduplication_and_paused_dpr': 'Included in candidate source; steady-state runs do not isolate their effect. No individual FPS attribution.'},
        'remaining_unknowns': gate['unsupported'] + ['Shared-host load and frame-rate-dependent world state; no thermal or physical CPU clock telemetry available.', 'No isolated FPS effect for each source change; no physical-device certification.'],
        'hardware_dependent_checks': 'Owner: native phones and interactive docked/undocked DevTools; repeat 3 x 30 seconds on same-device ~60 FPS baseline; average >=55 and no unexplained 10s below30.',
        'per_run_results': [{k:r[k] for k in ('id','metrics','thresholds','verdict')} for r in gate['runs']]})
    manifest = json.loads((OUT/'capture-manifest.json').read_text())
    manifest['capture']['argv'] = ['python3','tools/y8_performance_gate.py','capture']
    manifest['utc'] = datetime.now(timezone.utc).isoformat()
    manifest['gate_runner_sha256'] = baseline.sha(Path(__file__))
    for name in ('capture-manifest.json','performance-gate.json','performance-summary.json','prior-fix-diagnosis.json'):
        manifest['sha256'][name] = baseline.sha(OUT/name)
    manifest['evidence_paths'] = sorted(manifest['sha256'])
    baseline.save('manifest.json', manifest)
    print('PASS capture complete; performance verdict='+gate['verdict'])


def audit():
    baseline.OUT = OUT
    baseline.audit()
    manifest = json.loads((OUT/'manifest.json').read_text())
    assert baseline.sha(Path(__file__)) == manifest['gate_runner_sha256']
    gate = json.loads((OUT/'performance-gate.json').read_text())
    assert gate == build_gate()
    for r in gate['runs']:
        print('PASS recomputed', r['id'], json.dumps(r['metrics']), r['verdict'])
    print('PASS performance-gate.json: 12 embedded active sample sets; matched density/source hashes; per-run thresholds/verdicts; rolling 10s minima recomputed; gate='+gate['verdict'])
    summary = json.loads((OUT/'performance-summary.json').read_text())
    assert summary['verdict']==gate['verdict'] and summary['user_regression_resolved'] is False
    assert all(summary[k] for k in ('reproduced_cause','fix_effects','remaining_unknowns','hardware_dependent_checks'))
    print('PASS performance-summary.json: cause/fix effects/unknowns/hardware checks; no resolved user regression claim')
    # Runtime bytes, not just HEAD: catch later commits AND uncommitted changes.
    names = subprocess.check_output(['git','ls-files'],cwd=baseline.ROOT,text=True).splitlines()
    runtime = [n for n in names if n.endswith(('.html','.js','.css')) and not n.startswith('tools/')]
    for name in runtime:
        assert (baseline.ROOT/name).read_bytes()==(OUT/'candidate'/name).read_bytes(), name
    print('PASS runtime coverage: all',len(runtime),'current runtime files byte-identical to measured candidate; later runtime fixes require rerun')
    print('PASS metadata: GPU='+gate['environment']['gpu']['auxAttributes']['glRenderer']+'; CPU throttle=1 per run; physical clocks/thermal state unavailable')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['capture','audit'])
    args=parser.parse_args()
    capture() if args.action=='capture' else audit()
