"""Assemble the TASK-270 inspection kit; audit integrity separately from readiness.

Offline only. Preserve previous releases and select fresh immutable output paths.
`--audit` validates sealed bytes; `--require-ready` additionally enforces local gates.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

import y8_readiness as readiness_eval

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/TASK-270'
RELEASE = ROOT / 'artifacts/y8-release'
KIT = ROOT / 'artifacts/y8-submission-kit.zip'
OWNER = readiness_eval.OWNER
FPS = readiness_eval.QUALIFICATION
INPUTS = None
HISTORY = OUT / "historical-relocations.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def write(p, v):
    Path(p).write_text(json.dumps(v, indent=2) + '\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def rel(p):
    return str(Path(p).relative_to(ROOT))


def files(root):
    return {rel(p): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def zip_inventory(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        require(len(names) == len(set(names)), 'Duplicate ZIP members')
        require(all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names), 'Unsafe ZIP path')
        require(z.testzip() is None, 'CRC failure')
        inventory = {n: hashlib.sha256(z.read(n)).hexdigest() for n in names}
    print('PASS CRC', rel(path), 'members=' + str(len(names)), 'sha256=' + sha(path))
    for n, h in inventory.items():
        print('MEMBER', rel(path), n, h)
    return inventory


def check_package(historical=False):
    m = read(RELEASE / 'manifest.json')
    candidate_path = OUT / 'candidate-input.json'
    relocations = read(HISTORY) if HISTORY.exists() else {}
    if candidate_path.exists():
        candidate = read(candidate_path)
    else:
        path = 'artifacts/TASK-267/candidate.json'
        candidate = json.loads(readiness_eval.historical_bytes(ROOT, path, m['external_evidence_sha256'][path], m['assembly_source_revision'], relocations))
    expected = {r['path']: r['sha256'] for r in candidate['packed_file_inventory']}
    game = zip_inventory(RELEASE / 'grapnelninja-y8.zip')
    require(game == expected, 'Wrong game inventory')
    require(sha(RELEASE / 'grapnelninja-y8.zip') == m['zip']['sha256'] == candidate['sha256'], 'Candidate identity differs')
    if not historical:
        require(sha(ROOT / candidate['archive']) == candidate['sha256'], 'Selected current archive differs')
    for n, h in game.items():
        if not historical:
            require(sha(ROOT / n) == h, 'Current/tested runtime differs: ' + n)
        revision = candidate['source_revision'] if historical else 'HEAD'
        blob = subprocess.check_output(['git', 'show', revision + ':' + n], cwd=ROOT)
        require(hashlib.sha256(blob).hexdigest() == h, 'Committed runtime differs: ' + n)
    kit = zip_inventory(KIT)
    expected_kit = {str(p.relative_to(RELEASE)): sha(p) for p in RELEASE.rglob('*') if p.is_file()}
    require(kit == expected_kit, 'Submission inventory differs')
    require(kit['grapnelninja-y8.zip'] == m['zip']['sha256'], 'Inner ZIP differs')
    print('PASS inner game ZIP hash equals tested candidate', m['zip']['sha256'])
    allowed = {'grapnelninja-y8.zip', 'manifest.json', 'media-manifest.json', 'requirements.json',
               'LISTING.txt', 'OWNER-CHECKLIST.txt', 'REVIEWER-RESPONSE.txt', 'TEST-RESULTS.txt', 'UPLOAD.txt'}
    media = read(RELEASE / 'media-manifest.json')
    allowed.update(a['path'] for a in media['assets'])
    require(set(kit) == allowed, 'Unexpected QA/secret/output file')
    require(len(media['assets']) == 9, 'Wrong media count')
    for a in media['assets']:
        require(kit[a['path']] == a['sha256'], 'Media digest differs')
    owner = (RELEASE / 'OWNER-CHECKLIST.txt').read_text()
    require('contains an older archive' not in owner and 'LISTING.txt' in owner, 'Stale owner copy')
    require('grapnelninja-y8.zip (beside this checklist' in owner, 'Owner ZIP reference missing')
    require(len(read(RELEASE / 'requirements.json')['tickets']) == 18, 'Requirements scope differs')
    for p, h in m['files'].items():
        require(sha(RELEASE / p) == h, 'Release member differs: ' + p)
    for p, h in m['external_evidence_sha256'].items():
        if historical:
            readiness_eval.historical_bytes(ROOT, p, h, m['assembly_source_revision'], relocations)
        else:
            require(sha(ROOT / p) == h, 'External handoff reference differs: ' + p)
        print('REFERENCE', p, h)
    text = (RELEASE / 'TEST-RESULTS.txt').read_text()
    require(m['zip']['sha256'] in text and m['source_revision'] in text and m['build_tag'] in text, 'Test identity mismatch')
    r = read(OUT / 'readiness.json')
    require(m['package_ready'] == r['all_required_local_pass'] == read(RELEASE / 'requirements.json')['all_required_local_pass'], 'Readiness propagation differs')
    require(m['local_blockers'] == r['local_blockers'] == read(RELEASE / 'requirements.json')['local_blockers'], 'Blocker propagation differs')
    require(all(m[k] is False for k in ('submission_ready', 'moderation_approved', 'uploaded')), 'Unsupported owner claim')
    require('NOT PERFORMED' in text and FPS in text, 'Missing qualifications')
    print('PASS handoff references, 9 media provenance hashes, instructions and strict allowlist; no raw QA, secrets or output/')
    require('package_ready=' + str(m['package_ready']).lower() in text, 'Text readiness differs')
    print('PASS source/build/hash/test agreement; package_ready=' + str(m['package_ready']).lower() + ' submission_ready=false moderation_approved=false')


def audit(require_current=False):
    m = read(OUT / 'manifest.json')
    require((OUT / 'manifest.sha256').read_text().split()[0] == sha(OUT / 'manifest.json'), 'Manifest seal differs')
    relocations = read(OUT / 'historical-relocations.json')
    if HISTORY.exists():
        relocations.update(read(HISTORY))
    for p, h in m['evidence_sha256'].items():
        readiness_eval.historical_bytes(ROOT, p, h, m['source_revision'], relocations)
    for p, h in m['dirty_file_sha256'].items():
        snapshot = OUT / 'source-snapshot' / p
        if snapshot.exists():
            require(sha(snapshot) == h, 'Captured source differs: ' + p)
        else:
            readiness_eval.historical_bytes(ROOT, p, h, m['source_revision'], relocations)
    r = read(OUT / 'readiness.json')
    saved = read(OUT / 'tasks-input.json')
    require([t['id'] for t in saved] == readiness_eval.SCOPE, 'Wrong readiness scope')
    if require_current:
        current = read(ROOT / 'artifacts/tasks.json')
        current = current if isinstance(current, list) else current['tasks']
        require(saved == [t for t in current if t['id'] in readiness_eval.SCOPE], 'Task state changed; create a fresh readiness evaluation')
    require([t['id'] for t in r['tickets']] == readiness_eval.SCOPE, 'Wrong ticket scope')
    if r.get('schema') == 1:
        require(sha(r['input']['path']) == r['input']['sha256'], 'Readiness input changed; use fresh evaluation')
        require(readiness_eval.evaluate_file(r['input']['path']) == r, 'Readiness differs from validated inputs')
    else:
        # Legacy snapshots retain their historical verdict. Never reinterpret a
        # sealed old snapshot as a new ready result or compare it to live tasks.
        require(not r['all_required_local_pass'] and r['local_blockers'], 'Invalid legacy readiness')
    require(all(v == 'NOT PERFORMED' for v in r['owner_checks'].values()), 'Owner pass invented')
    h = read(OUT / 'handoff.json')
    require(h.get('package_ready', r['all_required_local_pass']) == r['all_required_local_pass'] and h['local_blockers'] == r['local_blockers'], 'Handoff readiness differs')
    for item in h['files']:
        require(Path(item['path']).is_absolute() and sha(item['path']) == item['sha256'], 'Handoff identity differs')
    check_package(historical=not require_current)
    print(f"PASS manifest.json: {len(m['evidence_sha256'])} sealed evidence hashes; commands/exit codes/UTC/source/tool versions")
    print('PASS readiness.json: exactly TASK-252–269; snapshot state checked; owner checks NOT PERFORMED')
    print('PASS handoff.json: absolute paths and hashes; honest FPS qualification; local inspection only')
    print(('PASS' if r['all_required_local_pass'] else 'FAIL') + ' required-local-readiness: ' + '; '.join(r['local_blockers']))


def check_prior():
    total = 0
    for n in (266, 267, 268, 269):
        base = ROOT / f'artifacts/TASK-{n}'
        m = read(base / 'manifest.json')
        require((base / 'manifest.sha256').read_text().split()[0] == sha(base / 'manifest.json'), 'Prior manifest seal differs')
        for p, expected in m['evidence_sha256'].items():
            source_path = rel(base / p) if n == 268 and not p.startswith('artifacts/') else p
            relocations = read(HISTORY) if HISTORY.exists() else {}
            readiness_eval.historical_bytes(ROOT, source_path, expected, m['source_revision'], relocations)
            total += 1
    print('PASS historical evidence:', total, 'hashes; recorded source/relocations; current task state evaluated separately')


def assemble():
    global INPUTS
    require(INPUTS is not None, 'Select immutable --inputs and fresh --out/--release/--kit locations')
    readiness = readiness_eval.evaluate_file(INPUTS)
    require(not readiness['synthetic'], 'Synthetic fixtures cannot create release evidence')
    require(readiness['all_required_local_pass'], 'Required local evidence remains failing: ' + '; '.join(readiness['local_blockers']))
    selection = read(INPUTS)
    selected = readiness_eval.load(selection['tasks'], INPUTS.parent)
    current = read(ROOT / 'artifacts/tasks.json')
    current = current if isinstance(current, list) else current['tasks']
    require(selected == [t for t in current if t['id'] in readiness_eval.SCOPE], 'Task inputs stale; evaluate fresh state')
    candidate_path = INPUTS.parent / selection['candidate']['path']
    candidate = readiness_eval.load(selection['candidate'], INPUTS.parent)
    require(candidate == read(ROOT / 'artifacts/TASK-267/candidate.json'), 'Candidate differs from upstream verified selection')
    require(RELEASE != ROOT / 'artifacts/y8-release' and KIT != ROOT / 'artifacts/y8-submission-kit.zip', 'Use fresh release/kit paths; preserve historical aliases')
    require(not RELEASE.exists() and not KIT.exists(), 'Output already exists')
    require(not OUT.exists(), 'Use an absent output directory; preserve all previous attempts')
    OUT.mkdir(parents=True)
    INPUTS = readiness_eval.snapshot_inputs(INPUTS, OUT / 'inputs')
    readiness = readiness_eval.evaluate_file(INPUTS)
    require(readiness['all_required_local_pass'], 'Input snapshot validation failed')
    candidate_path = INPUTS.parent / selection['candidate']['path']
    commands = []
    evidence = {}

    def run(argv, name):
        start = now()
        result = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        record = dict(argv=argv, start_utc=start, end_utc=now(), exit_code=result.returncode, log=rel(OUT / name))
        commands.append(record)
        (OUT / name).write_text('COMMAND ' + json.dumps(argv) + '\nSTART_UTC ' + start + '\n' + result.stdout + '\nEND_UTC ' + record['end_utc'] + '\nexit_code=' + str(result.returncode) + '\n')
        write(OUT / 'commands.json', commands)
        require(result.returncode == 0, 'Command failed: ' + name)
        return result.stdout.strip()

    revision = run(['git', 'rev-parse', 'HEAD'], 'source.log')
    require(run(['git', 'branch', '--show-current'], 'branch.log') == 'y8', 'Wrong branch')
    run(['git', 'status', '--short'], 'git-status-before.log')
    run(['git', 'diff', '--check'], 'diff-check.log')
    run([sys.executable, 'tools/assemble_y8_submission.py', '--prior-check', '--history', str(HISTORY)], 'prior-audit.log')
    run([sys.executable, 'tools/audit_y8_candidate.py', '--out', 'artifacts/TASK-268'], 'candidate-audit.log')
    run([sys.executable, 'artifacts/TASK-269/audit.py'], 'media-audit.log')
    # Preserve historical aliases; new release outputs use fresh paths. Historical
    # manifests remain untouched; relocation records bind the exact old bytes.
    previous = OUT / 'previous-release'
    require(not previous.exists(), 'Previous release already saved')
    shutil.copytree(ROOT / 'artifacts/y8-release', previous)
    if (ROOT / 'artifacts/y8-submission-kit.zip').exists():
        shutil.copyfile(ROOT / 'artifacts/y8-submission-kit.zip', OUT / 'previous-submission-kit.zip')
    relocations = {}
    for n in (266, 267, 268, 269):
        base = ROOT / f'artifacts/TASK-{n}'
        mp = base / 'manifest.json'
        evidence[rel(mp)] = sha(mp)
        for p, expected in read(mp)['evidence_sha256'].items():
            source = ROOT / p if p.startswith('artifacts/') or n != 268 else base / p
            blob = readiness_eval.historical_bytes(ROOT, rel(source), expected, read(mp)['source_revision'], read(HISTORY) if HISTORY.exists() else {})
            if not source.is_file() or sha(source) != expected or source.is_relative_to(ROOT / 'artifacts/y8-release'):
                snapshot = OUT / 'historical-source' / f'TASK-{n}' / rel(source)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(blob)
                relocations[rel(source)] = dict(path=rel(snapshot), sha256=expected, source_revision=read(mp)['source_revision'])
                source = snapshot
            evidence[rel(source)] = expected
    write(OUT / 'historical-relocations.json', relocations)
    print('PASS historical evidence preserved; mutable release references relocated:', len(relocations))
    write(OUT / 'tasks-input.json', selected)
    write(OUT / 'candidate-input.json', candidate)
    tickets = readiness['tickets']
    blockers = readiness['local_blockers']
    gate_path = INPUTS.parent / selection['performance']['path']
    write(OUT / 'readiness.json', readiness)
    media = read(ROOT / 'artifacts/TASK-269/media-review.json')
    handoff = read(ROOT / 'artifacts/TASK-269/handoff-review.json')
    require(media['candidate'] == handoff['candidate_sha256'] == candidate['sha256'], 'Review candidate differs')
    # Create the explicitly selected fresh release; preserve old aliases.
    RELEASE.mkdir(parents=True)
    shutil.copyfile(ROOT / candidate['archive'], RELEASE / 'grapnelninja-y8.zip')
    for a in media['assets']:
        src = ROOT / a['path']
        dest = Path(src.parent.name) / src.name
        (RELEASE / dest.parent).mkdir(exist_ok=True)
        shutil.copyfile(src, RELEASE / dest)
        a['original_path'] = a['path']
        a['path'] = str(dest)
    write(RELEASE / 'media-manifest.json', media)
    sentences = [c['sentence'] for c in handoff['checks']]
    (RELEASE / 'LISTING.txt').write_text('\n'.join(sentences[:10]) + '\n')
    (RELEASE / 'REVIEWER-RESPONSE.txt').write_text('DRAFT — owner must validate before sending\n' + '\n'.join(sentences[10:]) + '\n')
    owner = (ROOT / 'Y8-OWNER-CHECKLIST.md').read_text()
    owner = owner.replace('artifacts/TASK-267/grapnelninja-y8.zip', 'grapnelninja-y8.zip (beside this checklist; workspace: ' + rel(RELEASE / 'grapnelninja-y8.zip') + ')')
    owner = owner.replace('Y8-MEDIA-HANDOFF.md', 'LISTING.txt, REVIEWER-RESPONSE.txt and media-manifest.json')
    owner = owner.replace('- artifacts/y8-release/ contains an older archive and historical instructions.\n  Do not select that archive or its stale recapture claim for this handoff.',
        '- This TASK-270 kit supersedes the older release. Historical QA references below\n  are workspace-only evidence, not files required inside the submission kit.')
    (RELEASE / 'OWNER-CHECKLIST.txt').write_text(owner)
    identity = f"Source: {candidate['source_revision']}\nBuild: {candidate['build_tag']}\nZIP SHA256: {candidate['sha256']}\n"
    (RELEASE / 'TEST-RESULTS.txt').write_text(identity +
        'PASS archived exact-candidate checks: 18 browser cases, 6 startup/storage cases, 4 mobile embed runs, 160 lifecycle cases, 24 offline ad flows.\n'
        'PASS media review: six covers and three screenshots; original TASK-263 capture provenance retained.\n'
        'Historical captures are not new final-build screenshots.\n' + FPS + '\n' +
        ('PASS' if readiness['all_required_local_pass'] else 'FAIL') + ' required local readiness: ' + '; '.join(blockers) + '\n' +
        'Owner checks NOT PERFORMED: ' + '; '.join(OWNER) + '\n'
        'package_ready=' + str(readiness['all_required_local_pass']).lower() + '; submission_ready=false; moderation_approved=false; uploaded=false\n'
        'Evidence references and hashes: manifest.json external_evidence_sha256 (local workspace, not included in kit).\n')
    (RELEASE / 'UPLOAD.txt').write_text(identity +
        'LOCAL PREPARATION ONLY — owner checks remain before submission.\n'
        'Owner later uploads only grapnelninja-y8.zip, with root index.html. This kit is not the game upload.\n'
        'Use LISTING.txt, media/, screenshots/ and media-manifest.json; verify actual console slots.\n'
        'Complete OWNER-CHECKLIST.txt, inspect TEST-RESULTS.txt and requirements.json, then review REVIEWER-RESPONSE.txt.\n'
        'No upload, live ads, physical checks or moderation performed. No approval guaranteed.\n')
    write(RELEASE / 'requirements.json', dict(
        scope=readiness['scope'],
        tickets=[dict(id=t['id'], status=t['status'], result=t['result']) for t in tickets],
        all_required_local_pass=readiness['all_required_local_pass'], local_blockers=blockers,
        owner_checks=readiness['owner_checks'], performance_qualification=FPS,
        evidence='External workspace: ' + rel(OUT / 'readiness.json')))
    # The kit carries reference metadata, never the underlying QA payload.
    external = ['artifacts/TASK-267/candidate.json', 'artifacts/TASK-268/release-checks.json',
                'artifacts/TASK-269/media-review.json', 'artifacts/TASK-269/handoff-review.json',
                'artifacts/TASK-266/performance-claims.json', rel(gate_path),
                rel(OUT / 'readiness.json'), rel(OUT / 'historical-relocations.json'), rel(candidate_path), rel(INPUTS),
                'artifacts/TASK-268/manifest.json']
    manifest = dict(created_utc=now(), source_revision=candidate['source_revision'],
        assembly_source_revision=revision, build_tag=candidate['build_tag'],
        zip=dict(file='grapnelninja-y8.zip', sha256=candidate['sha256'], bytes=candidate['byte_count']),
        package_ready=readiness['all_required_local_pass'], local_package_prepared=True, submission_ready=False,
        moderation_approved=False, uploaded=False, local_blockers=blockers,
        external_evidence_scope='Workspace-only references; raw QA deliberately excluded from kit',
        external_evidence_sha256={p: sha(ROOT / p) for p in external},
        files={str(p.relative_to(RELEASE)): sha(p) for p in RELEASE.rglob('*') if p.is_file()})
    write(RELEASE / 'manifest.json', manifest)
    with zipfile.ZipFile(KIT, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(RELEASE.rglob('*')):
            if p.is_file():
                info = zipfile.ZipInfo(str(p.relative_to(RELEASE)), (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                z.writestr(info, p.read_bytes())
    write(OUT / 'handoff.json', dict(scope='Local inspection kit prepared; not submission-ready',
        files=[dict(path=str(p.resolve()), sha256=sha(p)) for p in
               [KIT, RELEASE / 'grapnelninja-y8.zip', RELEASE / 'manifest.json', RELEASE / 'OWNER-CHECKLIST.txt']],
        source_revision=candidate['source_revision'], build_tag=candidate['build_tag'],
        package_ready=readiness['all_required_local_pass'], local_blockers=blockers, outstanding_owner_checks={k:'NOT PERFORMED' for k in OWNER},
        fps_qualification=FPS, uploaded=False, submission_ready=False, moderation_approved=False))
    run([sys.executable, 'tools/assemble_y8_submission.py', '--package-check', '--out', str(OUT), '--release', str(RELEASE), '--kit', str(KIT)], 'package-check.log')
    history = run(['git', 'log', '--format=%H %s', '--name-only', 'b72ff271..HEAD'], 'committed-paths.log')
    require(not any(line.startswith(('artifacts/', 'screenshots/')) for line in history.splitlines()), 'Forbidden committed paths')
    staged = run(['git', 'diff', '--cached', '--name-only'], 'staged-paths.log')
    require(not any(line.startswith(('artifacts/', 'screenshots/')) for line in staged.splitlines()), 'Forbidden staged paths')
    run(['git', 'status', '--short'], 'git-status-after.log')
    environment = dict(os=platform.platform(), python=sys.version,
        git=run(['git', '--version'], 'git-version.log'), node=run(['node', '--version'], 'node-version.log'),
        pillow=importlib.metadata.version('Pillow'), playwright=importlib.metadata.version('playwright'),
        browser_execution='NOT RUN; saved offline evidence audited',
        archived_browsers=read(ROOT / 'artifacts/TASK-269/manifest.json')['environment']['archived_browsers'])
    evidence.update(files(previous))
    evidence.update(files(RELEASE))
    evidence[rel(KIT)] = sha(KIT)
    for p in external:
        evidence[p] = sha(ROOT / p)
    evidence.update(files(OUT))
    dirty = {p:sha(ROOT / p) for p in ['tools/assemble_y8_submission.py', 'tools/y8_readiness.py', 'Y8-SUBMISSION-KIT.md']}
    for p in dirty:
        snapshot = OUT / 'source-snapshot' / p
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / p, snapshot)
    evidence.update(files(OUT / 'source-snapshot'))
    m = dict(created_utc=now(), source_revision=revision, dirty_file_sha256=dirty,
        environment=environment, commands=commands, archive=manifest['zip'], evidence_sha256=evidence,
        invocation=sys.argv, integrity='PASS: sealed bytes; readiness evaluated separately',
        historical_relocations=rel(OUT / 'historical-relocations.json'))
    write(OUT / 'manifest.json', m)
    (OUT / 'manifest.sha256').write_text(sha(OUT / 'manifest.json') + '  ' + rel(OUT / 'manifest.json') + '\n')
    print('PASS local preparation assembled; owner checks NOT PERFORMED; no submission/moderation claim')


def main():
    global OUT, RELEASE, KIT, INPUTS, HISTORY
    ap = argparse.ArgumentParser(description=__doc__)
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument('--prior-check', action='store_true')
    modes.add_argument('--audit', action='store_true')
    modes.add_argument('--package-check', action='store_true')
    modes.add_argument('--require-ready', action='store_true')
    ap.add_argument('--inputs', type=Path, help='Immutable readiness selection JSON; required for fresh assembly')
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--release', type=Path, default=RELEASE)
    ap.add_argument('--kit', type=Path, default=KIT)
    ap.add_argument('--history', type=Path, default=HISTORY)
    args = ap.parse_args()
    OUT, RELEASE, KIT = args.out.resolve(), args.release.resolve(), args.kit.resolve()
    INPUTS = args.inputs.resolve() if args.inputs else None
    HISTORY = args.history.resolve()
    require(all(p.is_relative_to(ROOT / 'artifacts') for p in (OUT, RELEASE, KIT)), 'Outputs must stay in artifacts/')
    if args.prior_check:
        check_prior()
    elif args.package_check:
        check_package()
    elif args.audit or args.require_ready:
        audit(require_current=args.require_ready)
        if args.require_ready:
            require(read(OUT / 'readiness.json')['all_required_local_pass'], 'Required local performance gate remains FAIL')
    else:
        assemble()


if __name__ == '__main__':
    main()
