"""Read-only desktop Firefox >30 active-FPS gate over a rendering capture.

Exits 1 for a valid capture below the threshold and 2 for invalid evidence.
This does not make production or native Android performance claims.
"""
import argparse
import contextlib
import json
import math
from pathlib import Path
import subprocess
import sys

from playgama_render_compare import audit, hashes, validate_protocol, validate_capture_layout


def active_metrics(raw):
    active = warm = 0
    samples, excluded = [], []
    for previous, current in zip(raw['frames'], raw['frames'][1:]):
        dt = current['t'] - previous['t']
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError('invalid RAF interval')
        # A death-ending interval is retained: current.after is deliberately
        # not consulted. The next inactive interval is excluded instead.
        if any(previous['after'].values()) or any(current['before'].values()):
            excluded.append(dt)
            continue
        if active < 5000:
            warm += dt
        else:
            samples.append(dt)
        active += dt
    if warm < 5000 or sum(samples) < 30000:
        raise ValueError('incomplete active warmup or measurement')
    fps = len(samples) * 1000 / sum(samples)
    return dict(warmup_ms=warm, measured_ms=sum(samples), interval_count=len(samples),
                average_fps=fps, p95_ms=sorted(samples)[math.ceil(.95*len(samples))-1],
                excluded_gap_count=len(excluded), excluded_gap_ms=sum(excluded),
                gate='PASS' if fps > 30 else 'FAIL')


def evaluate(capture, runtime, arm):
    # Original logs, SHA256 receipts, protocol ordering and full raw arithmetic.
    with contextlib.redirect_stdout(sys.stderr):
        audit(capture)
    data = json.loads((capture/'results.json').read_text())
    protocol = json.loads((capture/'protocol.json').read_text())
    assert data['kind'] == 'capture' and not data['smoke']
    with contextlib.redirect_stdout(sys.stderr):
        validate_protocol(protocol)
    source = hashes(runtime)
    assert source == data['sources'][arm], 'tested runtime differs'
    # Also bind to committed bytes, not just the working tree.
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    for name in source:
        committed = subprocess.check_output(['git', 'show', f'{revision}:{name}'])
        assert committed == (runtime/name).read_bytes(), f'uncommitted runtime: {name}'
    runs = [r for r in data['runs'] if r['engine'] == 'firefox' and r['arm'] == arm]
    assert [(r['mode'], r['pair']) for r in runs] == [(m, p) for m in ('classic', 'bad') for p in range(3)]
    rows = []
    for run in runs:
        raw = json.loads((capture/run['raw']).read_text())
        assert raw['done'] and raw['inputs'] and raw['transitions']
        assert raw['seed'] == protocol['seed'] and raw['input_policy'] == protocol['input']
        assert raw['source_sha256'] == source
        validate_capture_layout(raw['layout'])
        metrics = active_metrics(raw)
        for key in ('warmup_ms', 'measured_ms', 'p95_ms'):
            assert metrics[key] == run['metrics'][key]
        rows.append(dict(mode=run['mode'], run=run['pair']+1, raw=run['raw'],
                         layout=raw['layout'], **metrics))
    return dict(gate='PASS' if all(r['gate'] == 'PASS' for r in rows) else 'FAIL',
                tested_committed_revision=revision, source_sha256=source, runs=rows,
                production_fps='NOT_MEASURED', native_android_firefox='UNVERIFIED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, default=Path('.'))
    parser.add_argument('--arm', choices=['candidate', 'control'], default='candidate')
    args = parser.parse_args()
    try:
        result = evaluate(args.capture, args.runtime, args.arm)
    except (AssertionError, ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f'INVALID evidence: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    for row in result['runs']:
        print(f"{row['gate']} firefox/{row['mode']} run={row['run']} average_fps={row['average_fps']:.9f} p95_ms={row['p95_ms']:.9f}", file=sys.stderr)
    return 0 if result['gate'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
