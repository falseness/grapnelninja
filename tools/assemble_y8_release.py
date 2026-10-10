"""Assemble/audit the local Y8 handoff from final-byte and preceding evidence.

Run the builder, smoke matrix and mobile lifecycle suite first (see --help).
No browser, upload, live SDK, device certification or FPS inference occurs here.
A stale archive, incomplete run or changed evidence fails closed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone

from PIL import Image
from audit_y8_smoke import audit as audit_smoke
from y8_performance_gate import metrics


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prior(ticket, digest, hash_key):
    base = Path('artifacts') / ticket
    manifest = read(base / 'manifest.json')
    require(manifest['archive_sha256'] == digest, ticket + ': stale archive')
    entries = manifest[hash_key]
    if isinstance(entries, dict):
        entries = [dict(path=str(base / p), sha256=h) for p, h in entries.items()]
    for entry in entries:
        require(sha(entry['path']) == entry['sha256'], 'Changed evidence: ' + entry['path'])
    print(f'PASS {ticket}: archive identity and {len(entries)} evidence hashes')
    return [str(base / 'manifest.json')] + [e['path'] for e in entries]


def identity(evidence, release):
    candidate = read(evidence / 'candidate-release.json')
    archive = release / 'grapnelninja-y8.zip'
    require(sha(archive) == candidate['sha256'], 'Archive hash mismatch')
    expected = {r['path']: r['sha256'] for r in candidate['files']}
    with zipfile.ZipFile(archive) as z:
        require(z.testzip() is None, 'ZIP CRC failure')
        actual = {p: hashlib.sha256(z.read(p)).hexdigest() for p in z.namelist()}
    require(actual == expected and len(actual) == 34, 'ZIP inventory mismatch')
    root = evidence / 'final-run/extracted'
    require({str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()} == expected,
            'Tested extraction differs from ZIP')
    for path, digest in expected.items():
        committed = subprocess.check_output(['git', 'show', candidate['source_revision'] + ':' + path])
        require(hashlib.sha256(committed).hexdigest() == digest, 'Source differs: ' + path)
        head = subprocess.check_output(['git', 'show', 'HEAD:' + path])
        require(hashlib.sha256(head).hexdigest() == digest, 'Current committed runtime differs: ' + path)
        require(sha(path) == digest, 'Working runtime differs: ' + path)
    index = (root / 'index.html').read_text()
    visibility = index.split("document.addEventListener('visibilitychange'", 1)[1].split('});', 1)[0]
    require('PROGRESS.flush()' in visibility, 'Visibility persistence fix absent')
    print('PASS archive/source/extracted identity: 34 files; visibility PROGRESS.flush() present')
    return candidate


def assemble(evidence, release):
    # An interrupted/failed reassembly must not leave an old ready claim behind.
    if (release / 'manifest.json').exists():
        previous = read(release / 'manifest.json')
        previous.update(package_ready=False, submission_ready=False, moderation_approved=False)
        write(release / 'manifest.json', previous)
    candidate = identity(evidence, release)
    digest = candidate['sha256']
    commands = read(evidence / 'commands.json')
    require(len(commands) == 3 and all(r['exit_code'] == 0 for r in commands), 'Incomplete final-byte commands')
    run = evidence / 'final-run'
    smoke = read(run / 'release-smoke.json')
    require(smoke['archive_sha256'] == digest, 'Stale smoke')
    shutil.copyfile(evidence / 'release-smoke.log', run / 'release-smoke.log')
    smoke_manifest = read(run / 'run.json')
    smoke_manifest.update(archive=str((release / 'grapnelninja-y8.zip').resolve()), archive_sha256=digest,
                          evidence_sha256={str(p): sha(p) for p in run.rglob('*')
                                           if p.is_file() and p.name != 'manifest.json'})
    write(run / 'manifest.json', smoke_manifest)
    audit_smoke(run)
    shutil.copyfile(run / 'release-smoke.json', evidence / 'release-smoke.json')
    life = read(evidence / 'mobile-lifecycle.json')
    require(Path(life['root']).resolve() == (run / 'extracted').resolve(), 'Wrong lifecycle root')
    require(life['overall'] == 'PASS' and len(life['runs']) == 14, 'Incomplete lifecycle suite')
    cases = [c for r in life['runs'] for c in r['cases']]
    require(len(cases) == 160 and all(c['verdict'] == 'PASS' for c in cases), 'Lifecycle case failure')
    require(all(not r['page_errors'] and not r['console_errors'] for r in life['runs']), 'Lifecycle errors')
    require('OVERALL PASS runs 14 cases 160 failed cases 0' in (evidence / 'mobile-lifecycle.log').read_text(),
            'Lifecycle execution log incomplete')
    print('PASS final-byte lifecycle: 14 runs; 160 cases; synthetic visibility and emulated devices only')
    perf_root = Path('artifacts/TASK-257')
    perf_manifest = read(perf_root / 'manifest.json')
    gate = read(perf_root / 'performance-gate.json')
    for name in ('performance-gate.json', 'performance-summary.json'):
        require(sha(perf_root / name) == perf_manifest['sha256'][name], 'Changed performance proof')
    for item in candidate['files']:
        measured = subprocess.check_output(['git', 'show', gate['identity']['candidate_commit'] + ':' + item['path']])
        require(hashlib.sha256(measured).hexdigest() == item['sha256'], 'Performance proof predates runtime change')
    for row in gate['runs']:
        require(metrics(row['raw_samples']) == row['metrics'], 'Performance arithmetic mismatch')
    failures = [r['id'] for r in gate['runs'] if r['verdict'].startswith('FAIL')]
    require(gate['verdict'] == 'FAIL' and len(failures) == 6, 'Reassess changed performance gate before packaging')
    write(evidence / 'performance-audit.json', dict(status='FAIL', source_revision=gate['identity']['candidate_commit'],
          final_archive_sha256=digest, binding='All 34 measured runtime files match final ZIP',
          failed_runs=failures, cause='Matched-density software rendering regression; root cause unresolved',
          package_ready=False, proof=str(perf_root / 'performance-gate.json')))
    print('PASS performance evidence audit: 12 runs recomputed; 6 FAIL_MEASURED_REGRESSION; package_ready=false')
    bound = []
    for ticket, key in [('TASK-258', 'sha256'), ('TASK-260', 'evidence_sha256'), ('TASK-263', 'evidence')]:
        bound += prior(ticket, digest, key)
    require(read('artifacts/TASK-258/mobile-embed.json')['verdict'] == 'PASS', 'Embed failed')
    ads = read('artifacts/TASK-260/ad-outcomes.json')
    require(ads['verdict'] == 'PASS' and len(ads['flows']) == 24 and
            all(r['verdict'] == 'PASS' for r in ads['flows']), 'Ad fixture coverage incomplete')
    capture = read('artifacts/TASK-263/capture-source.json')
    require(capture['files'] == smoke['file_hashes'], 'Media captured different runtime')
    media = read('artifacts/TASK-263/media-manifest.json')
    review = read('artifacts/TASK-263/review.json')
    require(len(media['assets']) == 9 and len(review['assets']) == 9, 'Missing media')
    for folder in ('media', 'screenshots', 'source-frames'):
        # These are generated package directories, never unrelated output/.
        destination = release / folder
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(Path('artifacts/TASK-263') / folder, destination)
    reviews = {r['path']: r for r in review['assets']}
    require(set(reviews) == {a['path'] for a in media['assets']}, 'Reviewed asset inventory differs')
    for asset in media['assets']:
        inspected = reviews[asset['path']]
        require(asset['path'] == inspected['path'] and asset['sha256'] == inspected['sha256']
                and inspected['result'] == 'PASS', 'Media review mismatch')
        target = release / Path(asset['path']).relative_to('artifacts/TASK-263')
        require(sha(target) == asset['sha256'], 'Media hash mismatch')
        with Image.open(target) as image:
            require(list(image.size) == asset['dimensions'], 'Media dimensions mismatch')
            image.verify()
        asset['source_path'] = asset['path']
        asset['path'] = str(target.relative_to(release))
    media['final_source_revision'] = candidate['source_revision']
    media['binding'] = 'Identical ZIP and all 34 runtime hashes; original capture revision retained.'
    write(release / 'media-manifest.json', media)
    print('PASS media: 9 decoded originals match reviewed hashes and final runtime')
    require('Controls:' in (release / 'LISTING.txt').read_text(), 'Missing controls')
    shutil.copyfile('artifacts/TASK-264/owner-checklist.md', release / 'OWNER-CHECKLIST.txt')
    with (release / 'OWNER-CHECKLIST.txt').open('a') as f:
        f.write(f'\nFinal TASK-265 package: artifacts/y8-release/grapnelninja-y8.zip\n'
                f'SHA256: {digest}\nSource revision: {candidate["source_revision"]}\n'
                'Matches the accepted TASK-261 ZIP byte for byte. Upload only after checking this hash.\n'
                'LOCAL BLOCKER: six matched-density performance regressions remain unresolved.\n'
                'This package is for inspection; resolve/retest the local gate before resubmission.\n')
    (release / 'UPLOAD.txt').write_text(
        'Grapnel Ninja — local Y8 preparation only\nGame ID: 285775\nApp ID: 6abfc17d100b7c96fc2d684e\n'
        f'Source revision: {candidate["source_revision"]}\nZIP SHA256: {digest}\n\n'
        'Owner: sign in at https://developer.y8.com/ and open the existing game.\n'
        'Upload only grapnelninja-y8.zip, with index.html at its root, through Builds.\n'
        'Confirm the build becomes Ready and test its private preview. Use media/ and screenshots/\n'
        'as candidates; check actual console field sizes/counts and any video requirement.\n'
        'Use LISTING.txt for description and controls. Complete OWNER-CHECKLIST.txt on phones,\n'
        'including portrait/landscape, lifecycle, real ad outcomes and the reported FPS regression.\n'
        'Then review REVIEWER-RESPONSE.txt and submit manually. No upload or submission was performed.\n'
        'LOCAL BLOCKER: matched-density software performance regresses in six runs. Package is prepared\n'
        'for inspection but package_ready=false; resolve/retest this local gate before resubmission.\n'
        'Do not upload source-frames, proof files or this entire directory as the game.\n')
    (release / 'REVIEWER-RESPONSE.txt').write_text(
        'The updated build includes touch cancellation/focus handling, rotated portrait embed\n'
        'presentation, and saving pending progress when the page becomes hidden. Local tests of\n'
        'the supplied ZIP passed desktop/emulated touch gameplay, nested embed input, synthetic\n'
        'visibility and reload persistence checks. Ad recovery was checked with offline SDK fixtures.\n'
        'Rendering changes combine repeated glow blending; adaptive internal pixel density can\n'
        'produce softer output. Matched-density software tests measured a regression in all six\n'
        'candidate runs. This remains unresolved and blocks package readiness. Native-phone recovery\n'
        'is unverified; we do not claim a guaranteed frame rate or a proven cause of the rejection.\n\n'
        'Owner: complete private preview and actual-phone checks before sending this response.\n'
        'Add actual device/browser results only after performing those checks.\n')
    (release / 'TEST-RESULTS.txt').write_text(
        f'Final ZIP SHA256: {digest}\nSource: {candidate["source_revision"]}\n'
        'PASS: fresh 18-case Chromium/Firefox/WebKit smoke matrix; 14 lifecycle runs / 160 cases.\n'
        'PASS: preceding identical-ZIP nested embed and 24 offline ad outcome cases; nine reviewed media images.\n'
        'Lifecycle visibility/focus are synthetic; mobile profiles are Linux browser emulation.\n'
        'FAIL: six matched-density candidate runs regress (about 4.9–5.4 FPS versus 15.5–16.6 FPS baseline).\n'
        'This unresolved local gate blocks package_ready. Prior 1688x780 versus 633x293 gains are unequal quality.\n'
        'UNVERIFIED owner checks: native phones, hardware FPS, interactive DevTools regression,\n'
        'hosted preview/ads, console fields, upload and moderation. No acceptance guarantee.\n'
        'Tutorial/mute controls are absent, not passed features. Runtime gameplay is silent.\n')
    for name in ('page-errors.log', 'console-errors.log'):
        (release / name).write_text('')  # Derived from both validated suites above.
    checks = []
    def check(name, status, paths, scope='required_local', notes=''):
        checks.append(dict(requirement=name, status=status, evidence=paths, scope=scope, notes=notes))
    check('Deterministic self-contained ZIP and source identity', 'PASS',
          [str(evidence / 'candidate-release.json'), str(evidence / 'build.log')])
    check('Final-byte browser/input/recovery/persistence smoke', 'PASS', [str(evidence / 'release-smoke.json')])
    check('Final-byte emulated lifecycle and visibility persistence', 'PASS', [str(evidence / 'mobile-lifecycle.json')])
    check('Nested embed/orientation/touch and offline ad callbacks', 'PASS',
          ['artifacts/TASK-258/manifest.json', 'artifacts/TASK-260/manifest.json'], notes='Same archive SHA256; no real ads.')
    check('Current media, listing and controls', 'PASS', ['media-manifest.json', 'LISTING.txt', 'artifacts/TASK-263/review.json'])
    check('Current public SDK requirements and preceding-ticket audit', 'PASS',
          [str(evidence / 'official-audit.json'), str(evidence / 'official/sources.json')],
          notes='Offline contract checks only; source-specific UNVERIFIED items retained in audit.')
    check('Matched-density local software performance gate', 'FAIL',
          [str(evidence / 'performance-audit.json'), 'artifacts/TASK-257/performance-gate.json'],
          notes='All six candidate runs regress; measured source matches final bytes. Local blocker, not owner-only.')
    check('Native phones, hardware FPS, interactive DevTools, hosted preview/ads, console fields and moderation',
          'UNVERIFIED', ['OWNER-CHECKLIST.txt', 'UPLOAD.txt'], 'owner_only', 'NOT PERFORMED; owner performs and records results.')
    sources = read(evidence / 'official/sources.json')
    write(release / 'requirements.json', dict(sources=sources, checks=checks))
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(), source_revision=candidate['source_revision'],
                    zip=dict(file='grapnelninja-y8.zip', sha256=digest, bytes=(release / 'grapnelninja-y8.zip').stat().st_size),
                    package_ready=all(c['status'] == 'PASS' for c in checks if c['scope'] == 'required_local'),
                    local_package_prepared=True,
                    package_ready_scope='Prepared for inspection; unresolved matched-density local regression blocks readiness.',
                    local_blockers=['TASK-257: six FAIL_MEASURED_REGRESSION runs on identical runtime'],
                    next_action='Resolve/retest the local matched-density regression before owner resubmission.',
                    submission_ready=False, moderation_approved=False, uploaded=False,
                    runtime_inventory=candidate['files'], commands=commands,
                    environment=read(run / 'run.json')['environment'],
                    evidence_binding=dict(archive_sha256=digest, served_root=smoke['served_root'],
                                          preceding_checks='TASK-258/260/263 verified by identical archive SHA256',
                                          lifecycle_limitations=life['unverified']),
                    evidence=sorted(set(bound + [str(evidence / 'release-smoke.json'), str(evidence / 'mobile-lifecycle.json'),
                                                str(evidence / 'final-checks.log'), str(evidence / 'manifest.json')])),
                    checks='requirements.json', media_manifest='media-manifest.json')
    manifest['files'] = [dict(path=str(p.relative_to(release)), sha256=sha(p), bytes=p.stat().st_size)
                         for p in sorted(release.rglob('*')) if p.is_file() and p != release / 'manifest.json']
    write(release / 'manifest.json', manifest)
    print('PASS assembly: local_package_prepared=true; package_ready=false; submission_ready=false; owner checks UNVERIFIED')


def audit(evidence, release):
    candidate = identity(evidence, release)
    manifest = read(release / 'manifest.json')
    require(manifest['source_revision'] == candidate['source_revision'], 'Stale manifest source')
    require(manifest['zip']['sha256'] == candidate['sha256'], 'Stale manifest ZIP')
    expected = {r['path'] for r in manifest['files']}
    actual = {str(p.relative_to(release)) for p in release.rglob('*') if p.is_file() and p != release / 'manifest.json'}
    require(actual == expected, 'Unmanifested package files')
    for row in manifest['files']:
        p = release / row['path']
        require(sha(p) == row['sha256'] and p.stat().st_size == row['bytes'], 'Package hash mismatch: ' + str(p))
    require(all((release / name).stat().st_size == 0 for name in ('page-errors.log', 'console-errors.log')),
            'Nonempty error log')
    for row in read(release / 'media-manifest.json')['assets']:
        with Image.open(release / row['path']) as image: image.verify()
    for item in read(evidence / 'official-audit.json')['checks']:
        for path in item['proof']:
            require(Path(path).is_file(), 'Missing official audit proof: ' + path)
    print(f'PASS test_step 1: extracted ZIP/source identity; {len(expected)} package hashes; 9 media; listing/controls')
    checks = read(release / 'requirements.json')['checks']
    require(all(c['status'] in ('PASS', 'FAIL', 'UNVERIFIED') for c in checks), 'Invalid status')
    for c in checks:
        for p in c['evidence']:
            require(Path(p).is_file() or (release / p).is_file(), 'Missing proof: ' + p)
        if c['scope'] in ('owner_only', 'diagnostic_only'):
            require(c['status'] == 'UNVERIFIED', 'Unsupported performance/device claim')
    require(manifest['package_ready'] == all(c['status'] == 'PASS' for c in checks if c['scope'] == 'required_local'),
            'Readiness exceeds evidence')
    require(not any(manifest[k] for k in ('submission_ready', 'moderation_approved', 'uploaded')), 'Unsupported submission claim')
    ticket = read(evidence / 'manifest.json')
    for path, digest in ticket['evidence_sha256'].items():
        require(sha(path) == digest, 'Evidence hash mismatch: ' + path)
    require(ticket['archive_sha256'] == candidate['sha256'], 'Ticket ZIP mismatch')
    staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only']).decode().splitlines()
    require(not any(p.startswith(('artifacts/', 'screenshots/', 'output/')) for p in staged), 'Forbidden staged files')
    print('PASS test_step 2: readiness claims bound to preceding/final-byte proof; no native or equal-quality FPS PASS')
    print(f'PASS evidence hashes: {len(ticket["evidence_sha256"])}; forbidden staged paths: 0')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence', type=Path, default=Path('artifacts/TASK-265'))
    ap.add_argument('--release', type=Path, default=Path('artifacts/y8-release'))
    ap.add_argument('--audit', action='store_true', help='Audit sealed manifests without regenerating evidence')
    args = ap.parse_args()
    (audit if args.audit else assemble)(args.evidence, args.release)
