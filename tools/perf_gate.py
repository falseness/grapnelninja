"""Check the TASK-174 mobile budget against a complete sequential perf attempt.

Run perf_mobile --layers --seconds 20 three times with --no-trace and once
with tracing per mode. Name files <mode>-notrace-{1,2,3}.json and
<mode>-traced-1.json. Preserve failed attempts in separate directories.
Usage: python3 tools/perf_gate.py --baseline DIR --current DIR --rev SHA
The Markdown report goes to stdout; invalid evidence or a failed gate exits 1.
"""
import argparse
import json
import math
from pathlib import Path
from statistics import median


def load_runs(directory, mode, revision=None):
    paths = [directory / f'{mode}-notrace-{i}.json' for i in (1, 2, 3)]
    paths.append(directory / f'{mode}-traced-1.json')
    runs = []
    for i, path in enumerate(paths):
        run = json.loads(path.read_text())
        if (run['mode'] != mode or run['seconds'] != 20 or run['seed'] != 1
                or run['frames'] <= 0 or run['page_errors'] or not run['layers_ms']
                or (revision is not None and run['rev'] != revision)
                or (run['allocated_bytes_per_frame'] is None) != (i < 3)):
            raise ValueError(f'{path}: invalid run configuration, revision or page errors')
        runs.append(run)
    if len({r['rev'] for r in runs}) != 1:
        raise ValueError(f'{directory}: mixed revisions')
    return paths, runs


def report(baseline, current, revision):
    lines = ['# Mobile performance gate', '', f'Current revision: `{revision}`.', '',
             'Draw p95 and counter means use the median of three untraced reps; '
             'allocation uses the single traced rep. No FPS gate.', '']
    passed = True
    for mode in ('bad', 'classic'):
        bp, base = load_runs(baseline, mode)
        cp, now = load_runs(current, mode, revision)
        if any(r['emulation'] != base[0]['emulation'] for r in base + now):
            raise ValueError(f'{mode}: emulation differs from baseline')
        lines += [f'## {mode}', '', f'Baseline revision: `{base[0]["rev"]}`.', '',
                  '| Metric | Baseline | Current | Ratio | Limit | Result | Sources (baseline; current) |',
                  '|---|---:|---:|---:|---:|---|---|']
        metrics = [('draw_ms.p95', 'draw_ms', 'p95', 1.25),
                   ('shadow_draws/frame', 'shadow_draws_per_frame', 'mean', 1),
                   ('gradients/frame', 'gradients_per_frame', 'mean', 1),
                   ('allocated bytes/frame', 'allocated_bytes_per_frame', None, 1)]
        for label, key, stat, multiplier in metrics:
            bv = [r[key][stat] for r in base[:3]] if stat else [base[3][key]]
            nv = [r[key][stat] for r in now[:3]] if stat else [now[3][key]]
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                   for v in bv + nv):
                raise ValueError(f'{mode}: invalid {label}')
            b, n = median(bv), median(nv)
            ok = n <= b * multiplier
            passed &= ok
            ratio = f'{n / b:.6f}' if b else ('0' if n == 0 else 'inf')
            sources = '; '.join(', '.join(f'`{p}` = {v}' for p, v in zip(
                paths[:3] if stat else paths[3:], values))
                for paths, values in ((bp, bv), (cp, nv)))
            lines.append(f'| {label} | {b:g} | {n:g} | {ratio} | {b * multiplier:g} | '
                         f'{"PASS" if ok else "FAIL"} | {sources} |')
        lines.append('')
    lines.append('PASS all gates' if passed else 'FAIL performance gate')
    return '\n'.join(lines) + '\n', passed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--rev', required=True)
    args = parser.parse_args()
    output, passed = report(args.baseline, args.current, args.rev)
    print(output, end='')
    raise SystemExit(0 if passed else 1)
