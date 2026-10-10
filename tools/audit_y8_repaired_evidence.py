#!/usr/bin/env python3
"""Read-only cross-ticket reconciliation; writes only a new TASK-266 audit directory.

This certifies the consistency report, never release readiness. No browser runs.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text())


def tasks():
    x = read(ROOT / 'artifacts/tasks.json')
    return x if isinstance(x, list) else x['tasks']


# Each group maps the rejected evidence to the actual repaired files. Full
# feedback is retained alongside these groups, including historical caveats.
PROOFS = {
252: [('checkout/merge/ancestry', 'branch-merge.log'), ('file-level inventory/source references', 'integration-inventory.json')],
253: [('restored interface diff', 'adapter-diff.txt'), ('requirements/retrieval/mapping', 'requirements.json'), ('callback traces and command completion', 'sdk-contract.log')],
254: [('matched-density identity/settings', 'baseline.json'), ('active raw samples and percentiles', 'baseline-runs.json'), ('network isolation', 'network.log'), ('unsupported cases and diagnosis', 'diagnosis.json')],
255: [('equal-density layer profiles and source identity', 'profile-before-after.json'), ('CPU traces and paired visual review', 'verifier-evidence-audit.log'), ('focused tests', 'focused-tests.log')],
256: [('debounced resize/DPR/offscreen/allocation samples', 'resize-profile.json'), ('resize completion', 'resize-tests.log'), ('paused DPR and captures', 'verifier-current-paused.log')],
257: [('raw samples, thresholds, per-run failures and matched density', 'performance-gate.json'), ('non-PASS verdict and attribution', 'performance-summary.json')],
258: [('repeated rotations/nested host/bars/fullscreen/captures', 'mobile-embed.json'), ('completed four-case run', 'mobile-embed.log')],
259: [('visibility persistence fix and pre-fix failure', 'mobile-lifecycle.json'), ('completed lifecycle run', 'mobile-lifecycle.log'), ('derived exit marker limitation', 'mobile-lifecycle.exit')],
260: [('24 fixture outcomes', 'ad-outcomes.json'), ('ordered callbacks', 'callback-traces.json'), ('commands/exits/fixture scope', 'ads-tests.log')],
261: [('ticket-local committed ZIP inventory', 'candidate-release.json'), ('source identity', 'source-inventory.json'), ('dirty source and symlink rejection', 'builder-tests.log')],
262: [('recovery/SDK cases and captures', 'release-smoke.json'), ('complete expensive-run log', 'release-smoke.log')],
263: [('available media specifications', 'media-requirements.json'), ('capture completion', 'capture.log'), ('screenshot completion', 'screenshots.log'), ('capture/archive/tool binding', 'capture-source.json')],
264: [('exact package location and identity', 'owner-checklist.md'), ('unperformed owner checks', 'y8-mobile-review.json')],
265: [('final-byte provenance and functional checks repaired; performance unresolved', 'live-geometry/final-byte/current-audit.log'), ('six unresolved final-byte regressions', 'live-geometry/final-byte/performance/performance-gate.json')],
}


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument('--out', type=Path, default=ROOT / 'artifacts/TASK-266')
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args()
    out = args.out.resolve()
    if args.verify:
        m = read(out / 'manifest.json')
        assert (out / 'manifest.sha256').read_text().split()[0] == digest(out / 'manifest.json')
        for p, h in m['evidence_sha256'].items():
            assert digest(ROOT / p) == h, p
        report = read(out / 'evidence-audit.json')
        current = {t['id']: t for t in tasks()}
        assert len(report['tickets']) == 14
        for entry in report['tickets']:
            t = current[entry['id']]
            assert entry['status'] == t['status']
            assert entry['feedback'] == {k: t[k] for k in ('artifacts_feedback', 'code_feedback')}
            if t['status'] != 'done' or entry['integrity_findings']:
                assert entry['validation_result'] != 'PASS'
            for resolution in entry['resolutions']:
                content = (ROOT / resolution['resolution_artifact']).read_text(errors='replace')
                assert content, resolution['resolution_artifact']
                for marker in resolution['content_markers']:
                    assert marker in content, (resolution['resolution_artifact'], marker)
        claims = read(out / 'performance-claims.json')
        assert claims['performance_verdict'] == 'FAIL' and claims['release_ready'] is False
        assert sum(r.get('verdict') == 'FAIL_MEASURED_REGRESSION' for r in claims['fixed_density']['current_runs']) == 6
        assert report['release_ready'] is False
        print(f"PASS both test steps: 14 statuses/feedback compared; {len(m['evidence_sha256'])} evidence hashes verified; unresolved entries not PASS")
        return
    out.mkdir(parents=True, exist_ok=True)
    assert not (out / 'manifest.json').exists(), 'Use a new output directory; preserve previous runs'
    commands, lines, cited = [], [], {}

    def cite(p):
        p = p.resolve()
        assert p.is_file(), str(p)
        rel = str(p.relative_to(ROOT))
        cited[rel] = digest(p)
        return rel

    def run(argv, expected=0):
        start = datetime.now(timezone.utc).isoformat()
        r = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        record = dict(argv=argv, start_utc=start, end_utc=datetime.now(timezone.utc).isoformat(), exit_code=r.returncode, output=r.stdout)
        commands.append(record)
        lines.append(f'COMMAND {json.dumps(argv)}\n{r.stdout}EXIT_CODE={r.returncode}')
        assert r.returncode == expected, record
        return r.stdout.strip()

    head = run(['git', 'rev-parse', 'HEAD'])
    assert run(['git', 'branch', '--show-current']) == 'y8'
    run(['git', 'status', '--short'])
    run(['git', 'merge-base', '--is-ancestor', '9a062f7', 'HEAD'])
    run(['git', 'merge-base', '--is-ancestor', 'b72ff27120656518282e7196de32aaa2a0e8f035', 'HEAD'])
    run(['git', 'show', '9a062f7', '--', 'index.html'])
    run(['git', 'diff', '--check'])
    run(['git', '--version']); run(['node', '--version']); run([sys.executable, '--version'])
    index = (ROOT / 'index.html').read_text()
    assert re.search(r"visibilitychange[\s\S]{0,500}PROGRESS\.flush\(\)", index)
    lines.append('PASS lifecycle flush commit 9a062f7 ancestry and current visibility handler')
    selected = [t for t in tasks() if t['id'] in {f'TASK-{n}' for n in PROOFS}]
    (out / 'tasks-input.json').write_text(json.dumps(selected, indent=2)+'\n')
    cite(out / 'tasks-input.json')
    entries = []
    for t in selected:
        n = int(t['id'][5:]); base = ROOT / 'artifacts' / t['id']
        mp = base / 'manifest.json'; m = read(mp); cite(mp)
        expected = {}
        for key in ('sha256', 'evidence_sha256'):
            if isinstance(m.get(key), dict): expected.update(m[key])
        ev = m.get('evidence')
        if isinstance(ev, list):
            expected.update({v['path']:v['sha256'] for v in ev if 'path' in v and 'sha256' in v})
        elif isinstance(ev, dict):
            expected.update({k:v['sha256'] for k,v in ev.items() if isinstance(v,dict) and 'sha256' in v})
        elif isinstance(ev, str) and isinstance(m.get('evidence_sha256'), str):
            expected[ev] = m['evidence_sha256']
        findings = []; checks = []
        for name, h in expected.items():
            p = Path(name)
            if not p.is_absolute(): p = ROOT / p if name.startswith('artifacts/') else base / p
            actual = digest(p) if p.is_file() else None
            result = 'MATCH' if actual == h else 'MISSING' if actual is None else 'CHANGED_SINCE_HISTORICAL_MANIFEST'
            row = dict(path=str(p.relative_to(ROOT)), expected=h, actual=actual, result=result)
            checks.append(row)
            if actual: cite(p)
            if result != 'MATCH': findings.append(row)
            lines.append(f'{t["id"]} FILE HASH {result} {row["path"]} {actual}')
        resolutions = []
        for objection, name in PROOFS[n] + [('commands/UTC/environment/source/evidence provenance', 'manifest.json')]:
            p = base / name; rel = cite(p)
            # Literal excerpts give reviewers actual content rather than a bare existence claim.
            text = p.read_text(errors='replace')
            markers = [line[:500] for line in text.splitlines() if re.search(r'PASS|FAIL|OVERALL|exit_code|EXIT_CODE|source_revision|sha256|NOT PERFORMED', line)][:8]
            resolutions.append(dict(objection=objection, resolution_artifact=rel, bytes=p.stat().st_size, content_markers=markers,
                                    validation_result='UNRESOLVED_PERFORMANCE' if n==265 and 'regressions' in objection else 'CURRENT_FILE_INSPECTED_SEE_HISTORICAL_VERIFIER'))
        for p in base.glob('*verif*.log'): cite(p)
        revisions = []
        for container in (m, m.get('identity',{}), m.get('source_identity',{})):
            for k in ('source_revision','source_commit','candidate_commit','head'):
                rev = container.get(k)
                if isinstance(rev,str) and re.fullmatch('[0-9a-f]{7,40}', rev):
                    run(['git','merge-base','--is-ancestor',rev,'HEAD']); revisions.append(rev)
        historical = re.findall(r'Verification failed[^\n]*', t['description'], re.I)
        reference_findings = []
        old_archive = m.get('archive')
        if isinstance(old_archive, dict) and old_archive.get('path') and old_archive.get('sha256'):
            apath = ROOT / old_archive['path']
            if apath.is_file() and digest(apath) != old_archive['sha256']:
                reference_findings.append(dict(kind='HISTORICAL_ARCHIVE_PATH_NOW_REPLACED', path=str(apath.relative_to(ROOT)), historical_sha256=old_archive['sha256'], current_sha256=digest(apath)))
        if n == 264:
            reference_findings.append(dict(kind='HISTORICAL_CHECKLIST_SUPERSEDED', detail='TASK-264 checklist names TASK-261 bytes and describes an older root ZIP; use current release manifest for current identity. Its historical acceptance does not certify current package.'))
        for rev in revisions:
            changed = run(['git','diff','--name-only',rev,'HEAD','--','index.html','render','platform.js','gameoptions.js'])
            if changed: reference_findings.append(dict(kind='SOURCE_CHANGED_SINCE_CAPTURE',source_revision=rev, changed_paths=changed.splitlines()))
        entries.append(dict(id=t['id'],status=t['status'], prior_verifier_objections=historical,
                            feedback={k:t[k] for k in ('artifacts_feedback','code_feedback')},
                            resolutions=resolutions, hash_checks=checks, integrity_findings=findings, reference_findings=reference_findings, source_ancestors=revisions,
                            validation_result='UNRESOLVED' if t['status']!='done' else 'HISTORICAL_REFERENCE_DRIFT' if findings else 'HISTORICAL_REPAIR_CONFIRMED',
                            scope='Current verification of retained historical evidence; not a fresh runtime pass. Original reviewer caveats above remain applicable.'))
        lines.append(f'{t["id"]} status={t["status"]} result={entries[-1]["validation_result"]} checked={len(checks)} findings={len(findings)}')
    release = read(ROOT/'artifacts/y8-release/manifest.json'); cite(ROOT/'artifacts/y8-release/manifest.json')
    assert release['package_ready'] is False
    archive = ROOT/'artifacts/y8-release'/release['zip']['file']; cite(archive)
    assert digest(archive)==release['zip']['sha256']
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            argv = ['git','show',head+':'+name]
            started = datetime.now(timezone.utc).isoformat()
            proc = subprocess.run(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            commands.append(dict(argv=argv,start_utc=started,end_utc=datetime.now(timezone.utc).isoformat(),exit_code=proc.returncode,stdout_sha256=hashlib.sha256(proc.stdout).hexdigest()))
            assert proc.returncode == 0, proc.stderr
            b = proc.stdout
            assert b == z.read(name) == (ROOT/name).read_bytes(), name
            lines.append(f'PASS current HEAD/ZIP/workspace source {name} {hashlib.sha256(b).hexdigest()}')
    lines.append('PASS archive identity and 34 current source members; package_ready=false')
    perfpath=ROOT/'artifacts/TASK-265/live-geometry/final-byte/performance/performance-gate.json'
    perf=read(perfpath);cite(perfpath)
    results=[{k:r[k] for k in ('id','metrics','thresholds','verdict') if k in r} for r in perf['runs']]
    assert sum(r.get('verdict')=='FAIL_MEASURED_REGRESSION' for r in results)==6
    legacy=ROOT/'artifacts/TASK-254/benchmark.json';cite(legacy)
    legacyrows=read(legacy)['rows']
    claims=dict(fixed_density=dict(sources=[cite(ROOT/'artifacts/TASK-254/baseline-runs.json'),cite(ROOT/'artifacts/TASK-255/profile-before-after.json'),cite(perfpath)], current_runs=results,
        interpretation='TASK-255 CPU submission cost is not presentation FPS. Current final-byte gate retains six failures. Geometry clipping is only partial recovery; no individual cumulative FPS attribution.'),
        adaptive_resolution=dict(source=str(legacy.relative_to(ROOT)), rows=[{k:v for k,v in r.items() if k not in ('frames','samples','timestamps','frameTimes')} for r in legacyrows],
        interpretation='Historical 12.9-to-42.1 FPS comparison changed density from 2 to 0.75 and cumulative source. Unequal quality, not an isolated glow compositing improvement; historical logs are not reconstructed as fresh measurements.'),
        untested=['Physical Android/iOS and hardware GPU','Interactive DevTools docked and undocked with equal viewport','Native OS suspension/thermal clocks','Hosted Y8 preview/SDK ads/console/moderation'],
        performance_verdict='FAIL', release_ready=False)
    report=dict(task='TASK-266',source_revision=head, tickets=entries,release_ready=False,
        historical_policy='Reconstructed/current verification only. Original failures and derived exit markers retained. Earlier acceptance applies to recorded bytes; changed manifests and current renderer do not inherit historical PASS.',
        later_task_dependencies=[], lifecycle_flush='9a062f7 preserved in ancestry and current source')
    for name,value in [('evidence-audit.json',report),('performance-claims.json',claims)]:
        (out/name).write_text(json.dumps(value,indent=2)+'\n');cite(out/name)
    lines.append('PASS consistency audit: 14 tickets; autoskip TASK-265 unresolved; six current performance failures; no later dependencies')
    (out/'audit.log').write_text('\n'.join(lines)+'\n');cite(out/'audit.log')
    cite(Path(__file__))
    dirty=run(['git','diff','--name-only']).splitlines()
    environment=dict(os=platform.platform(), python=sys.version, playwright=importlib.metadata.version('playwright'),
                     browser_execution='NOT RUN: saved evidence audit only', recorded_browser_environment=perf['environment'])
    manifest=dict(task='TASK-266',utc=datetime.now(timezone.utc).isoformat(),source_revision=head,environment=environment,
        invocation=[sys.executable,*sys.argv],commands=commands,archive=dict(path=str(archive.relative_to(ROOT)),sha256=digest(archive)),
        dirty_file_sha256={p:digest(ROOT/p) for p in dirty if (ROOT/p).is_file()},auditor_sha256=digest(Path(__file__)),
        evidence_sha256=cited,limitations='No rebuild or expensive capture required; historical reference drift and unresolved acceptance are findings, never PASS.')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'manifest.sha256').write_text(digest(out/'manifest.json')+'  manifest.json\n')
    print('PASS consistency audit: 14 tickets; autoskip TASK-265 unresolved; six current performance failures; no later dependencies')
    for e in entries: print(e['id'],e['validation_result'],len(e['integrity_findings']))


if __name__ == '__main__':
    main()
