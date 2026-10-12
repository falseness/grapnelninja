"""Read-only audit of TASK-328's rejected combined candidate and retained runtime.

Run with python3 -B tools/playgama_selection_audit.py artifacts/TASK-328.
Earlier raw-bound audits are rerun sequentially; no browser or build is launched.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_playgama import ROOT, runtime, sha


def read(path):
    return json.loads(path.read_text())


def audit(ticket):
    manifest = read(ticket / 'manifest.json')
    decision = read(ticket / 'decision.json')
    source = read(ticket / 'source.json')
    required = {str((ticket / p).relative_to(ROOT)) for p in
                ('decision.json', 'source.json', 'audit.py', 'integration.log', 'tests.log')}
    required.add('tools/playgama_selection_audit.py')
    for n in (324, 325, 326, 327):
        required.update(f'artifacts/TASK-{n}/{p}' for p in
                        ('manifest.json', 'audit.log', 'commit-receipt.json'))
    assert required <= manifest['sha256'].keys(), 'missing seals'
    for path, digest in manifest['sha256'].items():
        assert sha((ROOT / path).read_bytes()) == digest, path
    print('PASS input receipts, source/tool identities and original logs SHA256', flush=True)
    for n in (325, 326, 327):
        command = ['python3', '-B', f'artifacts/TASK-{n}/audit.py']
        if n == 325:
            command.append(f'artifacts/TASK-{n}')
        subprocess.run(command, cwd=ROOT, check=True)
        print(f'PASS TASK-{n} raw-bound audit rerun', flush=True)
    visual = read(ROOT / 'artifacts/TASK-325/decision.json')
    perf = [read(ROOT / f'artifacts/TASK-{n}/decision.json') for n in (326, 327)]
    gates = {'TASK-325': visual['eligible'] and visual['disposition'] == 'ELIGIBLE',
             **{f'TASK-{n}': d['verdict'] == 'PASS' for n, d in zip((326, 327), perf)}}
    assert decision['gates_pass'] == gates and not any(gates.values())
    assert decision['verdict'] == 'REJECT' and decision['selected'] == 'control'
    assert decision['runtime_adoption'] is False and decision['fps_claim'] is None
    assert decision['input_receipts'] == {
        f'TASK-{n}': [f'artifacts/TASK-{n}/{p}' for p in
                     ('manifest.json', 'audit.log', 'commit-receipt.json')]
        for n in (324, 325, 326, 327)}
    frozen = read(ROOT / 'artifacts/TASK-324/control/source.json')
    revision, files = runtime(source['revision'], frozen['revision'])
    assert source['members'] == frozen['members'] == {p: sha(b) for p, b in sorted(files.items())}
    assert source['arm'] == 'control' and source['source'] == 'git blobs only'
    selected = ticket / 'selected-runtime'
    assert {str(p.relative_to(selected)) for p in selected.rglob('*') if p.is_file()} == set(files)
    for path, data in files.items():
        assert (ROOT / path).read_bytes() == data, f'production drift: {path}'
        assert (selected / path).read_bytes() == data, path
        assert (ROOT / 'artifacts/TASK-324/control' / path).read_bytes() == data, path
        assert subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=ROOT) == data, path
    print(f'PASS selected-runtime/ source.json committed revision={revision} members={len(files)}')
    print('PASS production control unchanged; frozen, tested, selected and committed runtime bytes identical')
    for entry in manifest['commands']:
        assert entry['exit_code'] == 0 and entry['cwd'] == str(ROOT)
        assert entry['started_utc'] <= entry['ended_utc'] and entry['duration_seconds'] >= 0
        assert entry['log'] in manifest['sha256']
        assert 'EXIT_CODE=0' in (ROOT / entry['log']).read_text()
    assert manifest['browser_identity'] == read(ROOT / 'artifacts/TASK-325/manifest.json')['browser_identity']
    assert 'NOT_APPLICABLE: REJECT' in (ticket / 'tests.log').read_text()
    assert 'PASS production control unchanged' in (ticket / 'integration.log').read_text()
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    print('PASS git diff --check; adoption regression tests NOT_APPLICABLE: REJECT')
    size = sum(p.stat().st_size for p in (ROOT / 'artifacts').rglob('*') if p.is_file() and not p.is_symlink())
    assert size < 20 * 1024**3
    print(f'PASS artifacts_bytes={size} < 20.0 GiB')
    print('PASS verdict=REJECT; no optimization adopted; no FPS claim')


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ticket', type=Path)
    audit(parser.parse_args().ticket.resolve())
