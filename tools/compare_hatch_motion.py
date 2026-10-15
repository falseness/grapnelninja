"""Audit TASK-439 matched motion captures and alternating warmed timing runs.

Run after danger_hatch_probe.py captures and perf_mobile.py runs. Visual review
is deliberately separate: numerical improvement does not establish visual quality.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import statistics
import subprocess

from perf_mobile import percentiles

REPRODUCED = {
    'desktop-bad-thin-horizontal': ['danger_rect'],
    'phone-bad-cross-diagonal': ['triangle'],
    'desktop-classic-chevron-horizontal': ['ceiling_join', 'floor_join'],
}


def read(path):
    return json.loads(path.read_text())


def compare(out, reference):
    baseline, final = [read(out / label / 'manifest.json') for label in ('baseline', 'final')]
    bm, fm = [read(out / label / 'motion.json') for label in ('baseline', 'final')]
    original = read(reference / 'manifest.json')
    assert baseline['BASE_REV'] == original['BASE_REV']
    assert baseline['cases'].keys() == final['cases'].keys() == original['cases'].keys()
    for key in ('browser', 'seed', 'trajectory', 'fps'):
        assert baseline[key] == final[key] == original[key], key
    assert baseline['harness_sha256'] == final['harness_sha256']
    # TASK-440 added runtime hashes and allowed dirty worktrees. The frozen
    # capture/registration scripts stayed identical; audit those independently.
    original_source = subprocess.check_output(
        ['git', 'show', 'ce67f9e:tools/danger_hatch_probe.py'])
    assert hashlib.sha256(original_source).hexdigest() == original['harness_sha256']
    def fixture_scripts(source):
        return {node.targets[0].id: ast.literal_eval(node.value)
                for node in ast.parse(source).body if isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ('MOTION_SETUP', 'MOTION_FRAME')}
    assert fixture_scripts(original_source) == fixture_scripts(
        Path(__file__).with_name('danger_hatch_probe.py').read_bytes())
    for path, digest in baseline['runtime_sha256'].items():
        content = subprocess.check_output(['git', 'show', baseline['BASE_REV'] + ':' + path])
        assert hashlib.sha256(content).hexdigest() == digest, path
    assert bm['registration'] == fm['registration'] == read(reference / 'motion.json')['registration']
    assert bm == read(reference / 'motion.json'), 'baseline measurement reproduction'
    cases = {}
    frame_count = static_count = 0
    for case, meta in baseline['cases'].items():
        for key in ('backing', 'logical', 'effective_backing_scale', 'regions', 'joins',
                    'classes', 'viewport', 'DPR', 'mode', 'variant', 'trajectory', 'frames'):
            assert meta[key] == final['cases'][case][key] == original['cases'][case][key], (case, key)
        assert meta['frame_sha256'] == original['cases'][case]['frame_sha256'], case
        for label, manifest in [('baseline', baseline), ('final', final)]:
            for i, expected in enumerate(manifest['cases'][case]['frame_sha256']):
                path = out / label / 'frames' / case / f'{i:03d}.png'
                assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path
                frame_count += 1
        assert bm['cases'][case].keys() == fm['cases'][case].keys()
        regions = {}
        for region, values in bm['cases'][case].items():
            b = values['mean_absolute_temporal_error']
            f = fm['cases'][case][region]['mean_absolute_temporal_error']
            assert len(values['per_frame_errors']) == len(fm['cases'][case][region]['per_frame_errors']) == 60
            if meta['trajectory'] == 'static':
                assert b == f == 0
                static_count += 1
            regions[region] = dict(baseline=b, final=f, delta=f-b, improved=f < b)
        b = statistics.mean(v['baseline'] for v in regions.values())
        f = statistics.mean(v['final'] for v in regions.values())
        required = case in REPRODUCED
        passed = not required or (f < b and all(regions[r]['improved'] for r in REPRODUCED[case]))
        cases[case] = dict(regions=regions, baseline_mean=b, final_mean=f,
                           visibly_shimmering_baseline=required, metric_gate=passed)
        print(f"{'PASS' if passed else 'FAIL'} {case}: mean {b:.9f} -> {f:.9f}")
    result = dict(baseline_revision=baseline['BASE_REV'], final_revision=final['BASE_REV'],
                  baseline_manifest='baseline/manifest.json', final_manifest='final/manifest.json',
                  frozen_reference=str(reference), matched_cases=len(cases),
                  registration=bm['registration'], cases=cases,
                  metric_gate=all(c['metric_gate'] for c in cases.values()),
                  visual_gate='Requires explicit human/agent review in review.md')
    (out / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS matched coverage: {len(cases)} cases; {frame_count} native frame hashes; {static_count} zero static region controls')
    summary = {}
    configuration = None
    for mode in ('bad', 'classic'):
        timings = {}
        for label in ('baseline', 'final'):
            runs = [read(out / 'perf' / f'{label}-{mode}-{i}.json') for i in range(1, 4)]
            for run in runs:
                assert run['rev'] == result[label + '_revision']
                assert (run['mode'], run['seconds'], run['warmup_seconds'], run['seed']) == (mode, 20, 3, 1)
                assert run['provenance']['danger_hatch'] == 'bold'
                assert run['provenance']['trace'] is False
                assert not run['page_errors']
                assert run['frame_intervals_after_warmup'] > 0
                intervals = run['frame_intervals_ms_after_warmup']
                assert len(intervals) == run['frame_intervals_after_warmup']
                assert percentiles(intervals) == run['frame_interval_ms_after_warmup']
                matched = {k: run['provenance'][k] for k in
                           ('browser_version', 'harness_files_sha256', 'runtime_scripts_sha256')}
                matched['emulation'] = run['emulation']
                if configuration is None:
                    configuration = matched
                assert matched == configuration
            timings[label] = [r['frame_interval_ms_after_warmup']['p95'] for r in runs]
        b, f = [statistics.median(timings[label]) for label in ('baseline', 'final')]
        summary[mode] = dict(raw_p95=timings, baseline_median_p95=b, final_median_p95=f,
                             ratio=f/b, browser_errors=0, passed=f <= 1.10*b)
        print(f"{'PASS' if summary[mode]['passed'] else 'FAIL'} perf {mode}: median p95 {b} -> {f}; ratio={f/b:.6f}; browser_errors=0")
    (out / 'perf' / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return result['metric_gate'] and all(s['passed'] for s in summary.values())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', type=Path, default=Path('artifacts/TASK-439'))
    args = parser.parse_args()
    raise SystemExit(0 if compare(args.out, args.reference) else 1)
