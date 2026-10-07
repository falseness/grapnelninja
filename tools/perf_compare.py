"""Run alternating, paired mobile diagnostics; never acceptance measurements.

Example: python3 tools/perf_compare.py --rev HEAD --probe probe.js --out NEW_DIR
The probe is JavaScript applied after the game boots. All runs (including
controls) are marked diagnostic. Output directories must not already exist.
The original TASK-174 budgets and perf_mobile measurement window are unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import subprocess
import traceback

import perf_mobile


def schedule():
    for repetition in (1, 2, 3):
        for mode in ('bad', 'classic'):
            order = ('normal', 'probe') if repetition % 2 else ('probe', 'normal')
            for variant in order:
                yield repetition, mode, variant


def summarize(output):
    lines = ['# Paired rendering diagnostic', '',
             'Diagnostic only: changed pictures are not acceptance evidence.', '',
             '| Mode | Normal p95 values | Probe p95 values | Normal median | '
             'Probe median | Improved pairs |', '|---|---|---|---:|---:|---:|']
    for mode in ('bad', 'classic'):
        values = {}
        for variant in ('normal', 'probe'):
            paths = [output / variant / f'{mode}-{rep}.json' for rep in (1, 2, 3)]
            values[variant] = [json.loads(path.read_text())['draw_ms']['p95'] for path in paths]
        normal, probe = values['normal'], values['probe']
        improved = sum(p < n for n, p in zip(normal, probe))
        lines.append(f'| {mode} | {normal} | {probe} | {median(normal):g} | '
                     f'{median(probe):g} | {improved}/3 |')
    lines += ['', 'Sources: `{normal,probe}/{bad,classic}-{1,2,3}.json`.',
              'Inspect page errors, frames, inputs, host load and provenance before '
              'attributing a difference to the probe. Percentile costs are not additive.']
    return '\n'.join(lines) + '\n'


def compare(revision, probe, output):
    # Resolve before allocating the output directory; pin one full source SHA.
    revision = subprocess.check_output(
        ['git', 'rev-parse', '--verify', revision + '^{commit}'],
        cwd=perf_mobile.ROOT, text=True).strip()
    source = probe.read_text()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'probe.js').write_text(source)
    (output / 'config.json').write_text(json.dumps({
        'revision': revision,
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'probe_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'seconds': 20, 'seed': 1, 'trace': False, 'layers': True,
        'schedule': list(schedule()),
    }, indent=2) + '\n')
    instrument = perf_mobile.INSTRUMENT_SCRIPT
    try:
        for repetition, mode, variant in schedule():
            stem = output / variant / f'{mode}-{repetition}'
            stem.parent.mkdir(exist_ok=True)
            override = source if variant == 'probe' else ''
            # Use the exact unmodified instrument script for the control.
            perf_mobile.INSTRUMENT_SCRIPT = (
                '() => {(' + instrument + ')();\n' + override + '\n}'
                if override else instrument)
            stem.with_suffix('.host.txt').write_text(subprocess.check_output(
                ['ps', '-eo', 'pid,ppid,pcpu,comm,args', '--sort=-pcpu'], text=True))
            print(f'START {stem}', flush=True)
            with stem.with_suffix('.log').open('w') as log:
                try:
                    run = perf_mobile.run(revision, mode, 20, 1, trace=False,
                                          layers=True, log=lambda line: print(line, file=log, flush=True))
                    run['diagnostic'] = True
                    run['experiment'] = {'variant': variant, 'repetition': repetition,
                                         'diagnostic_override': override}
                    # Preserve even invalid results for diagnosis, then fail the stage.
                    stem.with_suffix('.json').write_text(json.dumps(run, indent=2) + '\n')
                    if run['page_errors'] or run['frames'] <= 0 or run['input_dispatched'] <= 0:
                        raise ValueError('Invalid measurement: page errors, no frames or no inputs')
                except BaseException:
                    traceback.print_exc(file=log)
                    log.write('measurement.exit=1\n')
                    stem.with_suffix('.exit').write_text('1\n')
                    raise
                log.write('measurement.exit=0\n')
                stem.with_suffix('.exit').write_text('0\n')
            print(f'RESULT {stem}: {run["draw_ms"]}', flush=True)
        (output / 'comparison.md').write_text(summarize(output))
        (output / 'run.exit').write_text('0\n')
    except BaseException:
        (output / 'run.exit').write_text('1\n')
        raise
    finally:
        perf_mobile.INSTRUMENT_SCRIPT = instrument


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rev', required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compare(args.rev, args.probe, args.out)
