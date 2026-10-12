"""Finite TASK-270 old/new experiment. ALL fixtures are synthetic logic tests.

Run with --old-source <preserved assembler> --saved-gate <saved failing gate>
--tasks <tasks.json> --report <new directory>. Does not run capture or assembly.

This is an argparse experiment script, not a unittest module (it was misnamed
tools/test_y8_readiness.py until TASK-301; a unittest runner collected zero tests
from it and reported OK). tools/test_y8_readiness.py now replays this experiment
on the recorded TASK-270 fixture inputs and asserts its report verdicts.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import zipfile

import assemble_y8_submission as assembly
import y8_readiness as evaluator


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return dict(path=path.name, sha256=evaluator.sha(path))


def frames(intervals):
    result = [dict(t=0, dt=None, canvas=[1560, 780], state=dict(menu=False, paused=False, offer=False, hidden=False))]
    for dt in intervals:
        result.append(dict(t=result[-1]['t'] + dt, dt=dt, canvas=[1560, 780], state=dict(menu=False, paused=False, offer=False, hidden=False)))
    return result


def old_evaluator(source):
    """Execute the original AST verbatim; redirect its fixed gate read only.

    This isolates the old readiness block from archive mutations/browser tools.
    Its ignored local receipts are still the exact same fixture inputs.
    """
    tree = ast.parse(source)
    body = next(n.body for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'assemble')
    start = next(i for i, n in enumerate(body) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'gate_path' for t in n.targets))
    end = next(i for i in range(start, len(body)) if isinstance(body[i], ast.Expr) and isinstance(body[i].value, ast.Call) and isinstance(body[i].value.func, ast.Name) and body[i].value.func.id == 'write')
    module = ast.Module(body=body[start:end+1], type_ignores=[])
    return compile(module, '<original-assemble-readiness>', 'exec'), ast.unparse(module)


def fixture(root, gate, tasks):
    # The archive is deliberately not a game; this cannot be release evidence.
    with zipfile.ZipFile(root / 'candidate.zip', 'w') as archive:
        archive.writestr('index.html', 'SYNTHETIC LOGIC FIXTURE; NOT A GAME\n')
    candidate = dict(synthetic=True, source_revision=gate['identity']['candidate_commit'],
                     archive='candidate.zip', sha256=evaluator.sha(root / 'candidate.zip'),
                     packed_file_inventory=[dict(path='index.html', sha256=hashlib.sha256(b'SYNTHETIC LOGIC FIXTURE; NOT A GAME\n').hexdigest())])
    identity = dict(source_revision=candidate['source_revision'], archive_sha256=candidate['sha256'])
    log = root / 'check.log'
    log.write_text('SYNTHETIC assertion: expected=1 actual=1\nexit_code=0\n')
    receipt = dict(identity=identity, argv=['synthetic-offline-fixture'], start_utc='2026-10-10T00:00:00Z',
                   end_utc='2026-10-10T00:00:01Z', exit_code=0,
                   log=dict(path=log.name, sha256=evaluator.sha(log)),
                   assertions=[dict(name='synthetic required check', actual=1, expected=1)])
    ref = save(root / 'receipt.json', receipt)
    checks = {k: dict(requirement_sha256=h, receipt=ref) for k, h in evaluator.obligations(tasks).items()}
    selection = dict(schema=1, synthetic=True, identity=identity,
                     candidate=save(root / 'candidate.json', candidate), tasks=save(root / 'tasks.json', tasks),
                     local_checks=save(root / 'checks.json', dict(identity=identity, checks=checks)),
                     performance=save(root / 'gate.json', gate),
                     owner_checks={k: 'NOT PERFORMED' for k in evaluator.OWNER})
    return selection


def propagation(root, result, task_input):
    """Exercise actual package/audit code on tiny synthetic archives only."""
    out, release, kit = root / 'snapshot', root / 'release', root / 'kit.zip'
    out.mkdir()
    release.mkdir()
    candidate = json.loads((root / 'candidate.json').read_text())
    shutil.copyfile(root / 'candidate.zip', release / 'grapnelninja-y8.zip')
    (root / 'index.html').write_text('SYNTHETIC LOGIC FIXTURE; NOT A GAME\n')
    assets = []
    for i in range(9):
        path = f'media/synthetic-{i}.png'
        target = release / path
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'SYNTHETIC MEDIA')
        assets.append(dict(path=path, sha256=evaluator.sha(target)))
    save(release / 'media-manifest.json', dict(assets=assets))
    save(release / 'requirements.json', dict(tickets=result['tickets'],
        all_required_local_pass=result['all_required_local_pass'], local_blockers=result['local_blockers']))
    for name in ('LISTING.txt', 'REVIEWER-RESPONSE.txt', 'UPLOAD.txt'):
        (release / name).write_text('SYNTHETIC ONLY')
    (release / 'OWNER-CHECKLIST.txt').write_text('LISTING.txt; grapnelninja-y8.zip (beside this checklist')
    (release / 'TEST-RESULTS.txt').write_text(candidate['sha256'] + candidate['source_revision'] + 'synthetic-build ' +
        assembly.FPS + ' NOT PERFORMED package_ready=' + str(result['all_required_local_pass']).lower())
    manifest = dict(source_revision=candidate['source_revision'], assembly_source_revision=candidate['source_revision'],
        build_tag='synthetic-build', zip=dict(sha256=candidate['sha256']),
        package_ready=result['all_required_local_pass'], submission_ready=False, moderation_approved=False, uploaded=False,
        local_blockers=result['local_blockers'], external_evidence_sha256={},
        files={str(p.relative_to(release)): evaluator.sha(p) for p in release.rglob('*') if p.is_file()})
    save(release / 'manifest.json', manifest)
    with zipfile.ZipFile(kit, 'w') as archive:
        for path in release.rglob('*'):
            if path.is_file(): archive.write(path, str(path.relative_to(release)))
    save(out / 'readiness.json', result)
    save(out / 'candidate-input.json', candidate)
    save(out / 'tasks-input.json', task_input)
    save(out / 'historical-relocations.json', {})
    save(out / 'handoff.json', dict(package_ready=result['package_ready'], local_blockers=result['local_blockers'],
        files=[dict(path=str(kit.resolve()), sha256=evaluator.sha(kit))]))
    manifest = dict(source_revision=candidate['source_revision'], dirty_file_sha256={},
        evidence_sha256={str(p.relative_to(root)): evaluator.sha(p) for p in out.rglob('*') if p.is_file()})
    save(out / 'manifest.json', manifest)
    (out / 'manifest.sha256').write_text(evaluator.sha(out / 'manifest.json'))
    # Deliberately different live state must not invalidate historical integrity.
    save(root / 'artifacts/tasks.json', [])
    with patch.multiple(assembly, ROOT=root, OUT=out, RELEASE=release, KIT=kit, HISTORY=out / 'historical-relocations.json'):
        with patch.object(assembly.subprocess, 'check_output', return_value=(root / 'index.html').read_bytes()):
            with redirect_stdout(io.StringIO()) as capture:
                assembly.check_package()
                assembly.audit()
                try:
                    assembly.audit(require_current=True)
                    raise AssertionError('Changed current tasks accepted as ready')
                except ValueError as exc:
                    assert 'Task state changed' in str(exc)
                print('PASS current readiness rejects changed tasks; historical integrity remains valid')
        (root / 'synthetic-propagation.log').write_text(capture.getvalue())
    assert ('package_ready=' + str(result['package_ready']).lower()) in capture.getvalue()
    print('PASS synthetic package/audit propagation: package_ready=' + str(result['package_ready']).lower() + '; live task changes do not rewrite history')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('old-source', 'saved-gate', 'tasks', 'report'):
        ap.add_argument('--' + key, type=Path, required=True)
    args = ap.parse_args()
    assert not args.report.exists(), 'Keep earlier failed/successful experiments'
    args.report.mkdir(parents=True)
    code, extracted = old_evaluator(args.old_source.read_text())
    (args.report / 'old-evaluator.py.txt').write_text(extracted + '\n')
    real = json.loads(args.saved_gate.read_text())
    tasks = json.loads(args.tasks.read_text())
    tasks = tasks if isinstance(tasks, list) else tasks['tasks']
    tasks = [t for t in tasks if t['id'] in evaluator.SCOPE]
    positive_tasks = deepcopy(tasks)
    for task in positive_tasks:
        task['status'] = 'done'  # explicit synthetic resolution, never persisted to real tasks
    positive = deepcopy(real)
    for run in positive['runs']:
        run['raw_samples'] = frames([20] * 1500)
        run['metrics'] = evaluator.metrics(run['raw_samples'])
        run['verdict'] = 'SYNTHETIC_IGNORE_LABEL_USE_SAMPLES'
    scenarios = [
        ('current_six_failures', False), ('synthetic_all_local_pass', True),
        ('one_failed_repetition', False), ('autoskip', False), ('pending', False),
        ('missing', False), ('stale', False), ('source_mismatch', False),
        ('owner_only_unknowns', True), ('missing_required_check', False),
        ('failed_local_assertion', False), ('archive_mismatch', False),
        ('duplicate_repetition', False), ('unequal_density', False),
        ('conditional_absolute_failure', False), ('conditional_absolute_pass', True),
        ('stale_requirement', False), ('owner_claim', False)]
    outcomes = []
    with tempfile.TemporaryDirectory(prefix='task270-synthetic-') as tmp:
        for name, expected in scenarios:
            root = Path(tmp) / name
            root.mkdir()
            gate = deepcopy(real if name == 'current_six_failures' else positive)
            task_input = deepcopy(tasks if name == 'current_six_failures' else positive_tasks)
            if name in ('autoskip', 'pending'):
                next(t for t in task_input if t['id'] == 'TASK-265')['status'] = name
            if name == 'one_failed_repetition':
                r = next(r for r in gate['runs'] if r['id'] == 'candidate-emulation-True-3')
                r['raw_samples'] = frames([40] * 750)
                r['metrics'] = evaluator.metrics(r['raw_samples'])
            if name.startswith('conditional_absolute_'):
                for run in gate['runs']:
                    intervals = [16] * 1875
                    if name.endswith('failure') and run['id'] == 'candidate-emulation-True-3':
                        intervals = [10] * 2000 + [50] * 200
                    run['raw_samples'] = frames(intervals)
                    run['metrics'] = evaluator.metrics(run['raw_samples'])
            if name == 'duplicate_repetition': gate['runs'][-1] = deepcopy(gate['runs'][-2])
            if name == 'unequal_density': gate['runs'][-1]['dimensions']['canvas'] = [780, 390]
            if name == 'source_mismatch': gate['runs'][-1]['source_hash'] = 'wrong-source'
            selection = fixture(root, gate, task_input)
            if name == 'missing': (root / 'receipt.json').unlink()
            if name == 'stale': (root / 'receipt.json').write_text('{}')
            if name == 'archive_mismatch': (root / 'candidate.zip').write_bytes(b'wrong candidate')
            if name in ('missing_required_check', 'stale_requirement', 'failed_local_assertion'):
                checks = json.loads((root / 'checks.json').read_text())
                if name == 'missing_required_check': checks['checks'].pop(next(iter(checks['checks'])))
                elif name == 'stale_requirement': next(iter(checks['checks'].values()))['requirement_sha256'] = 'stale'
                else:
                    receipt = json.loads((root / 'receipt.json').read_text())
                    receipt['assertions'][0]['actual'] = 0
                    ref = save(root / 'receipt.json', receipt)
                    for check in checks['checks'].values(): check['receipt'] = ref
                selection['local_checks'] = save(root / 'checks.json', checks)
            if name == 'owner_claim': selection['owner_checks'][evaluator.OWNER[0]] = 'PASS'
            save(root / 'selection.json', selection)
            old_globals = dict(ROOT=root, OUT=root, read=lambda _: gate, require=evaluator.require,
                               rel=lambda p: str(p.relative_to(root)), tickets=task_input,
                               FPS=assembly.FPS, OWNER=assembly.OWNER, write=lambda *a: None)
            try:
                exec(code, old_globals)
                old = dict(ready=old_globals['readiness']['all_required_local_pass'], error=None)
            except ValueError as exc:
                old = dict(ready=False, error=str(exc))
            result = evaluator.evaluate_file(root / 'selection.json')
            assert result['all_required_local_pass'] is expected, (name, result['local_blockers'])
            assert result['package_ready'] is expected
            assert not any(result[k] for k in ('submission_ready', 'moderation_approved', 'uploaded'))
            assert old['ready'] is False
            if name == 'current_six_failures':
                assert sum(r['verdict'] == 'FAIL_MEASURED_REGRESSION' for r in result['performance_results']) == 6
            if name == 'one_failed_repetition':
                assert sum(r['verdict'] == 'FAIL_MEASURED_REGRESSION' for r in result['performance_results']) == 1
            if name == 'conditional_absolute_failure':
                assert result['performance_results'][-1]['verdict'] == 'FAIL_ABSOLUTE_THRESHOLD'
            if expected:
                snap = evaluator.snapshot_inputs(root / 'selection.json', root / 'immutable')
                assert evaluator.evaluate_file(snap)['all_required_local_pass']
                (root / 'check.log').write_text('changed upstream alias')
                assert evaluator.evaluate_file(snap)['all_required_local_pass']
                assert not evaluator.evaluate_file(root / 'selection.json')['all_required_local_pass']
                (root / 'check.log').write_text('SYNTHETIC assertion: expected=1 actual=1\nexit_code=0\n')
                # An otherwise passing synthetic fixture cannot reach assembly.
                assembly.INPUTS = root / 'selection.json'
                try:
                    assembly.assemble()
                    raise AssertionError('Synthetic assembly allowed')
                except ValueError as exc:
                    assert 'Synthetic fixtures' in str(exc)
            if name in ('synthetic_all_local_pass', 'one_failed_repetition'):
                propagation(root, result, task_input)
            result.pop('input')  # temp path is not durable evidence
            outcome = dict(case=name, expected_ready=expected, old=old, generalized=result,
                           input_sha256=evaluator.sha(root / 'selection.json'))
            save(root / 'outcome.json', outcome)
            shutil.copytree(root, args.report / name)
            outcomes.append(outcome)
            print(f"PASS {name}: old_ready={old['ready']} generalized_ready={expected}; submission=false moderation=false")
    save(args.report / 'comparison.json', dict(synthetic=True, release_acceptance=False,
        old_source_sha256=evaluator.sha(args.old_source),
        new_source_sha256=evaluator.sha(Path(evaluator.__file__)),
        saved_gate_sha256=evaluator.sha(args.saved_gate), outcomes=outcomes,
        decision='PASS finite evaluator comparison; retired from mandatory repetition. Real gate remains failing; TASK-270 pending.'))
    print('PASS immutable snapshot survives changed upstream aliases; synthetic assembly rejected')
    print('PASS finite comparison: 18 cases; real release evidence unchanged; TASK-270 remains pending')


if __name__ == '__main__':
    main()
