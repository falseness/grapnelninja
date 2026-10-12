"""Read-only TASK-326 audit when the combined candidate fails the visual gate.

No browser is launched and no timing metric can be inferred from visual captures.
Run: python3 tools/playgama_browser_rejection_audit.py artifacts/TASK-326
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def audit(ticket):
    manifest = read(ticket / 'manifest.json')
    required = {'artifacts/TASK-325/manifest.json', 'artifacts/TASK-325/decision.json',
                'artifacts/TASK-325/audit.py', 'tools/playgama_browser_rejection_audit.py'}
    required.update(str((ticket / name).relative_to(ROOT)) for name in
                    ('decision.json', 'metrics.json', 'audit.py', 'capture/NOT_RUN_VISUAL_REJECT.json'))
    assert required <= manifest['sha256'].keys(), 'missing required seals'
    for path, digest in manifest['sha256'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    print('PASS complete inventory and SHA256 of sources, consumed evidence and original logs', flush=True)
    prior = ROOT / 'artifacts/TASK-325'
    spec = importlib.util.spec_from_file_location('visual_gate_audit', prior / 'audit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.audit(prior)
    visual = read(prior / 'decision.json')
    assert visual['eligible'] is False and visual['disposition'] == 'REJECT'
    # Recompute the exact blocker independently of both declared verdicts.
    from playgama_render_compare import pixel_diff
    failures = []
    for relative in visual['reproduced_in']:
        capture = prior / relative
        row = next(r for r in read(capture / 'results.json')['comparisons']
                   if r['checkpoint'] == visual['failed_checkpoint'])
        stats = pixel_diff(capture / row['control'], capture / row['candidate'])
        assert max(stats['max_per_channel']) > 3
        failures.append(stats)
    assert len(failures) >= 2 and all(x == failures[0] for x in failures)
    metrics = read(ticket / 'metrics.json')
    assert metrics == {'status': 'NOT_RUN_VISUAL_REJECT', 'timing_arms': 0,
                       'means': None, 'p95': None, 'fps': None, 'pair_changes': None,
                       'control_drift': None, 'per_mode_medians': None,
                       'visual_failure': failures[0]}
    decision = read(ticket / 'decision.json')
    assert decision['verdict'] == 'NOT_RUN_VISUAL_REJECT'
    assert decision['carry_forward'] == 'artifacts/TASK-324/control'
    assert decision['reason'] == visual['reason']
    assert decision['runtime_adoption'] is False and decision['fps_claim'] is None
    assert decision['engines'] == dict.fromkeys(('firefox', 'chrome'), 'NOT_RUN_VISUAL_REJECT')
    skipped = read(ticket / 'capture/NOT_RUN_VISUAL_REJECT.json')
    assert skipped['timing_arms'] == 0 and skipped['verdict'] == decision['verdict']
    assert skipped['visual_evidence'] == 'artifacts/TASK-325/decision.json'
    assert sorted(p.name for p in (ticket / 'capture').iterdir()) == ['NOT_RUN_VISUAL_REJECT.json']
    assert manifest['browser_identity'] == read(prior / 'manifest.json')['browser_identity']
    for entry in manifest['commands']:
        assert entry['cwd'] == str(ROOT) and entry['exit_code'] == 0
        assert entry['started_utc'] <= entry['ended_utc'] and entry['duration_seconds'] >= 0
        assert entry['log'] in manifest['sha256']
        log = (ROOT / entry['log']).read_text()
        assert 'EXIT_CODE=0' in log and 'PASS' in log
    assert len(manifest['commands']) == 2
    print('PASS recomputed visual blocker: ' + json.dumps(failures[0]), flush=True)
    print('PASS workload/backing/durations/raw timing metrics: NOT_APPLICABLE; visual rejection prevented all timing arms')
    print('PASS means/p95/FPS/pair changes/control drift/per-mode medians: null; no timing evidence or >30 FPS claim')
    size = sum(p.stat().st_size for p in (ROOT / 'artifacts').rglob('*') if p.is_file() and not p.is_symlink())
    assert size < 20 * 1024**3
    print(f'PASS artifacts_bytes={size} < 20.0 GiB')
    print('PASS verdict=NOT_RUN_VISUAL_REJECT; carry_forward=artifacts/TASK-324/control; runtime_adoption=False')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ticket', type=Path)
    audit(parser.parse_args().ticket.resolve())
