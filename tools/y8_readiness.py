"""Offline readiness evaluation. Inputs are immutable, hash-bound snapshots.

Exit-zero integrity and task status are not local performance verdicts. No
browser, package generation, mutable release alias or task file is written here.
"""
import hashlib
import json
import math
from pathlib import Path

from y8_performance_gate import metrics

OWNER = ['Physical Android Chrome and iPhone Safari', 'Y8 preview/fullscreen',
         'Native interrupted touch and suspension', 'Natural death/restart on phones',
         'Hosted live ad outcomes', 'Hardware FPS and interactive DevTools/throttle reproduction',
         'Console media slots and video requirements', 'Console upload', 'Moderation submission/approval']

SCOPE = [f'TASK-{n}' for n in range(252, 270)]
QUALIFICATION = ('Reduced-resolution FPS gains are not equal-quality optimization gains. '
                 'Software browser results do not certify native-phone or hardware FPS.')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(ref, root):
    """Resolve only the explicitly selected bytes; never fall back to an alias."""
    path = (Path(root) / ref['path']).resolve()
    require(path.is_relative_to(Path(root).resolve()), 'Evidence escapes input root')
    require(path.is_file(), 'Missing evidence: ' + str(path))
    require(sha(path) == ref['sha256'], 'Stale evidence: ' + str(path))
    return json.loads(path.read_text())


def performance(gate, source):
    """Recompute all six local verdicts from active samples, not PASS labels."""
    require(gate['identity']['candidate_commit'] == source, 'Performance source mismatch')
    expected = {f'{tree}-emulation-{emulation}-{rep}'
                for tree in ('reported', 'candidate') for emulation in (False, True)
                for rep in (1, 2, 3)}
    runs = {r['id']: r for r in gate['runs']}
    require(len(gate['runs']) == 12 and set(runs) == expected, 'Missing/duplicate performance repetition')
    measured = {}
    for name, run in runs.items():
        settings = run['settings']
        tree = settings['tree']
        require(tree in ('candidate', 'reported'), 'Invalid tree')
        require(name == f"{tree}-emulation-{settings['device_emulation']}-{run['rep']}", 'Run identity mismatch')
        require(run['source_hash'] == gate['identity']['candidate_commit' if tree == 'candidate' else 'original_y8_commit'], 'Run source mismatch')
        require(settings['source'] == gate['identity'], 'Settings source mismatch')
        require(settings['DPR'] == 2 and settings['viewport'] == [780, 390] and settings['cpu_throttle'] == 1, 'Protocol mismatch')
        require(run['dimensions']['canvas'] == [1560, 780] and run['dimensions']['dpr'] == 2, 'Unequal-quality density')
        frames = run['raw_samples']
        require(all(all(math.isfinite(f[k]) for k in ('t',)) and
                    (f['dt'] is None or math.isfinite(f['dt'])) and
                    f['canvas'] == [1560, 780] and
                    set(f['state']) == {'menu', 'paused', 'offer', 'hidden'} for f in frames), 'Invalid sample')
        measured[name] = metrics(frames)
        require(measured[name] == run['metrics'], 'Stale metrics: ' + name)
    results = []
    for name in sorted(n for n in runs if n.startswith('candidate-')):
        run, control = runs[name], runs[name.replace('candidate-', 'reported-')]
        require(run['dimensions'] == control['dimensions'] and all(
            run['settings'][k] == control['settings'][k] for k in
            ('viewport', 'device_emulation', 'DPR', 'cpu_throttle', 'seed', 'input', 'duration', 'warmup', 'density', 'devtools')),
            'Unmatched settings: ' + name)
        m, b = measured[name], measured[control['id']]
        absolute = b['average_fps'] >= 55 and b['minimum_10s_fps'] >= 55
        verdict = ('FAIL_MEASURED_REGRESSION' if m['average_fps'] < b['average_fps'] else
                   'FAIL_ABSOLUTE_THRESHOLD' if absolute and (m['average_fps'] < 55 or m['minimum_10s_fps'] < 30) else 'PASS_LOCAL')
        results.append(dict(id=name, verdict=verdict, metrics=m, absolute_gate_applicable=absolute))
    return results


def obligations(tasks):
    """Bind coverage to exact requirement text, including its position and kind."""
    return {f"{t['id']}:{kind}:{i}": hashlib.sha256(text.encode()).hexdigest()
            for t in tasks for kind in ('acceptance_criteria', 'test_steps')
            for i, text in enumerate(t[kind])}


def evaluate(selection, root):
    blockers, tickets, results = [], [], []
    try:
        require(selection['schema'] == 1, 'Unsupported readiness schema')
        require(selection['owner_checks'] == {k: 'NOT PERFORMED' for k in OWNER}, 'Owner checks must remain NOT PERFORMED')
        candidate = load(selection['candidate'], root)
        tasks = load(selection['tasks'], root)
        require([t['id'] for t in tasks] == SCOPE, 'Wrong task scope/order')
        identity = dict(source_revision=candidate['source_revision'], archive_sha256=candidate['sha256'])
        require(selection['identity'] == identity, 'Selected candidate identity mismatch')
        archive = (Path(root) / candidate['archive']).resolve()
        require(archive.is_relative_to(Path(root).resolve()) and sha(archive) == candidate['sha256'], 'Candidate archive mismatch')
        require(candidate.get('synthetic', False) == selection.get('synthetic', False), 'Fixture/candidate scope mismatch')
        receipts = load(selection['local_checks'], root)
        require(receipts['identity'] == identity, 'Local evidence source/archive mismatch')
        required = obligations(tasks)
        require(set(receipts['checks']) == set(required), 'Missing/extra required local checks')
        for key, digest in required.items():
            check = receipts['checks'][key]
            require(check['requirement_sha256'] == digest, 'Stale task requirement: ' + key)
            # All obligations need a source-bound command receipt with structured
            # assertions. NOT PERFORMED owner checks are tracked separately.
            receipt = load(check['receipt'], root)
            require(receipt['identity'] == identity, 'Receipt provenance mismatch: ' + key)
            require(receipt['argv'] and receipt['start_utc'] and receipt['end_utc'], 'Missing command metadata: ' + key)
            log = (Path(root) / receipt['log']['path']).resolve()
            require(log.is_relative_to(Path(root).resolve()) and sha(log) == receipt['log']['sha256'], 'Command log mismatch: ' + key)
            assertions = receipt['assertions']
            require(assertions and all(a['name'] and 'actual' in a and 'expected' in a for a in assertions), 'Missing structured assertions: ' + key)
            if receipt['exit_code'] != 0 or any(a['actual'] != a['expected'] for a in assertions):
                blockers.append('Failed local check: ' + key)
        for task in tasks:
            unresolved = task['status'] != 'done'
            if unresolved:
                blockers.append(task['id'] + ' ' + task['status'] + ' is unresolved, not PASS')
            tickets.append(dict(task, result='UNRESOLVED' if unresolved else 'VERIFIED_EVIDENCE'))
        gate = load(selection['performance'], root)
        results = performance(gate, candidate['source_revision'])
        blockers.extend(r['id'] + ': ' + r['verdict'] for r in results if r['verdict'] != 'PASS_LOCAL')
    except (ValueError, KeyError, OSError, TypeError, AssertionError, IndexError) as exc:
        blockers.append('Invalid required evidence: ' + str(exc))
    ready = not blockers
    return dict(schema=1, scope='TASK-252 through TASK-269 only', synthetic=selection.get('synthetic', False),
                tickets=tickets, all_required_local_pass=ready, package_ready=ready,
                local_blockers=blockers, performance_results=results,
                performance_qualification=QUALIFICATION,
                owner_checks=selection.get('owner_checks', {}),
                submission_ready=False, moderation_approved=False, uploaded=False)


def evaluate_file(path):
    path = Path(path).resolve()
    selection = json.loads(path.read_text())
    result = evaluate(selection, path.parent)
    result['input'] = dict(path=str(path), sha256=sha(path))
    return result


def historical_bytes(root, path, expected, revision, relocations):
    """Resolve history by digest and recorded relocation/revision, never status."""
    import subprocess
    root = Path(root)
    candidates = [root / path]
    relocation = relocations.get(path)
    if relocation and relocation['sha256'] == expected:
        candidates.append(root / relocation['path'])
    for candidate in candidates:
        if candidate.is_file() and sha(candidate) == expected:
            return candidate.read_bytes()
    require(not path.startswith('artifacts/'), 'Missing historical artifact: ' + path)
    subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'HEAD'], cwd=root, check=True)
    blob = subprocess.check_output(['git', 'show', revision + ':' + path], cwd=root)
    require(hashlib.sha256(blob).hexdigest() == expected, 'Historical source mismatch: ' + path)
    return blob


def snapshot_inputs(path, destination):
    """Copy only cited inputs; snapshots survive mutable upstream aliases."""
    import shutil
    path, destination = Path(path).resolve(), Path(destination).resolve()
    require(not destination.exists(), 'Input snapshot already exists')
    root = path.parent
    selection = json.loads(path.read_text())
    refs = [selection[k] for k in ('candidate', 'tasks', 'local_checks', 'performance')]
    candidate = load(selection['candidate'], root)
    refs.append(dict(path=candidate['archive'], sha256=candidate['sha256']))
    checks = load(selection['local_checks'], root)['checks']
    for check in checks.values():
        refs.append(check['receipt'])
        refs.append(load(check['receipt'], root)['log'])
    # Keep relative references stable; refuse traversal or absolute paths.
    for ref in refs:
        source = root / ref['path']
        require(not Path(ref['path']).is_absolute() and source.resolve().is_relative_to(root), 'Invalid snapshot path')
        require(sha(source) == ref['sha256'], 'Snapshot input changed')
    destination.mkdir(parents=True)
    for ref in refs:
        target = destination / ref['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / ref['path'], target)
    target = destination / 'selection.json'
    require(not target.exists(), 'Reserved selection.json collides with input')
    shutil.copyfile(path, target)
    return target
