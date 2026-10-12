"""Rebuild and audit the current local Y8 package (TASK-285).

Subcommands, each offline and receipt-friendly (run them through a receipt
wrapper so UTC/exit codes land in commands.jsonl):

  build            reproducible ZIP from committed HEAD; CRC/inventory/root/SDK
                   identity; extraction; member hashes against HEAD blobs, the
                   working tree and the extracted root -> candidate.json
  functional       the five offline browser suites against the exact ZIP via
                   tools/verify_y8_candidate.py, then release-checks.json and the
                   existing tools/audit_y8_candidate.py audit
  media            recapture the nine assets from the exact ZIP with
                   tools/prepare_y8_media.py and compare them pixel-wise with the
                   historical TASK-263 captures -> media-review.json
  readiness        audit TASK-271..284 and the applicable functional evidence;
                   separate fields for package preparation, software regression,
                   native 60-FPS acceptance, submission and moderation
  assemble         fresh artifacts/y8-release + artifacts/y8-submission-kit.zip,
                   preserving the previous ones under the task directory
  package-check    CRC/inventory/hash checks of both ZIPs against the tested root
                   and HEAD (test step 1)
  manifest         commands/UTC/exit codes/environment/hashes/evidence seal

Nothing here claims 60 FPS or release readiness: a passing package audit is a
statement about bytes and offline functional behaviour, never a performance verdict.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

_spec = importlib.util.spec_from_file_location('build_y8_zip', TOOLS / 'build-y8-zip.py')
build_zip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_zip)
from browser_test_support import node_label  # noqa: E402

SUITES = ['release', 'embed', 'mobile-embed', 'lifecycle', 'ads']
REQUIRED_ENGINES = ('chromium', 'firefox', 'webkit')  # every engine must be run or explained (TASK-294)
SUITE_RESULT = {'release': 'results.json', 'embed': 'results.json', 'mobile-embed': 'mobile-embed.json',
                'lifecycle': 'mobile-lifecycle.json', 'ads': 'ad-outcomes.json'}
TESTED_TOOLS = ['tools/verify_y8_candidate.py', 'tools/verify_y8_release.py', 'tools/verify_y8_embed.py',
                'tools/verify_y8_mobile_embed.py', 'tools/verify_y8_mobile_lifecycle.py', 'tools/verify_y8_ads.py',
                'tools/browser_test_support.py', 'tools/game_harness.py', 'tools/fixtures/fake-y8-sdk.js',
                'tools/audit_y8_candidate.py', 'tools/y8_package.py']
MEDIA_TOOLS = ['tools/prepare_y8_media.py', 'tools/make_covers.py', 'tools/autopilot.js', 'tools/browser_test_support.py']
SEEDS = 'artifacts/TASK-084/seed-search.json'
HISTORICAL_MEDIA = ROOT / 'artifacts/TASK-263'
SCOPE = [f'TASK-{n}' for n in range(271, 285)]
OWNER_CHECKS = ['Physical Android Chrome and iPhone Safari', 'Y8 preview/fullscreen',
                'Native interrupted touch and suspension', 'Natural death/restart on phones',
                'Hosted live ad outcomes', 'Hardware FPS and interactive DevTools/throttle reproduction',
                'Native 60-FPS benchmark rows (TASK-283 runner results/*.json)',
                'Console media slots and video requirements', 'Console upload', 'Moderation submission/approval']
LISTING = [
    'Title: Grapnel Ninja.',
    'Description: Swing through a neon obstacle course with a grappling hook, avoid hazards and chase your record.',
    'Modes: Choose Main for the harder course or Chill for a relaxed run.',
    'Controls: Click or tap and hold to throw the grappling hook; release to let go.',
    'Pause: Use the on-screen menu; desktop P or Escape toggles pause during an active run.',
    'Continue: With the rewarded SDK available, a death at score 5 or above can offer one optional rewarded Continue per run; '
    'Restart remains available on the offer except while an ad request is pending.',
    'Ads: Only a completed viewed reward grants Continue; dismissal, no-fill, blocking, errors or timeout do not reward, '
    'and this Y8 adapter does not support interstitials.',
    'Audio: Gameplay is silent; the SDK initializes with sound off, and there is no gameplay audio to restore after an ad.',
    'Orientation: On touch-first portrait viewports the landscape stage rotates clockwise; desktop portrait viewports do not use that rotation.',
    'Quality: Adaptive render density may reduce resolution and soften the image under sustained load; '
    'FPS gains from lower resolution are not equal-quality optimization gains.',
]
QUALIFICATION = ('Reduced-resolution FPS gains are not equal-quality optimization gains. '
                 'Software (SwiftShader) browser results do not certify native-phone or hardware FPS.')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=False) + '\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def require(ok, message):
    if not ok:
        raise SystemExit('FAIL ' + message)


def rel(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def git_blob(revision, path):
    return subprocess.check_output(['git', 'show', f'{revision}:{path}'], cwd=ROOT)


def receipt_runner(out):
    """Return run(argv, log_name) writing COMMAND/START_UTC/END_UTC/exit_code logs and commands.json."""
    out.mkdir(parents=True, exist_ok=True)
    commands = read(out / 'commands.json') if (out / 'commands.json').exists() else []

    def run(argv, name, env=None):
        start = now()
        with (out / name).open('w') as f:
            f.write('COMMAND ' + json.dumps(argv) + '\nSTART_UTC ' + start + '\n')
            f.flush()
            result = subprocess.run(argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=env)
            end = now()
            f.write('\nEND_UTC ' + end + '\nexit_code=' + str(result.returncode) + '\n')
        row = dict(argv=argv, start_utc=start, end_utc=end, exit_code=result.returncode, log=name)
        commands.append(row)
        write(out / 'commands.json', commands)
        print(f'[{name}] exit={result.returncode} {start} -> {end}', flush=True)
        return result.returncode
    return run, commands


# ---------------------------------------------------------------- build ----

def zip_inventory(path, label):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        require(len(names) == len(set(names)), f'{label}: duplicate ZIP members')
        require(all(not n.endswith('/') for n in names), f'{label}: directory entries present')
        require(all(not Path(n).is_absolute() and '..' not in Path(n).parts and not n.startswith('/') for n in names),
                f'{label}: unsafe member path')
        require(z.testzip() is None, f'{label}: CRC failure')
        inventory = {n: sha_bytes(z.read(n)) for n in names}
        sizes = {i.filename: i.file_size for i in infos}
    print(f'PASS CRC {label}: {len(names)} members, all CRC32 verified, sha256={sha(path)} bytes={Path(path).stat().st_size}')
    for n in names:
        print(f'MEMBER {label} {n} bytes={sizes[n]} sha256={inventory[n]}')
    return inventory


def cmd_build(args):
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    require(not (out / 'candidate.json').exists(), 'build output already holds a candidate; use a fresh --out')
    require(git('status', '--porcelain', '--', *build_zip.RUNTIME_FILES) == '', 'uncommitted runtime changes')
    zip1, zip2 = out / 'grapnelninja-y8.zip', out / 'grapnelninja-y8-repeat.zip'
    rc = build_zip.main(['--out', str(zip1), '--listing', str(out / 'listing.txt'), '--stats', str(out / 'stats.json'),
                         '--refs', str(out / 'refs.txt'), '--inventory', str(out / 'inventory.json')])
    require(rc == 0, 'first build failed')
    rc = build_zip.main(['--out', str(zip2)])
    require(rc == 0, 'second build failed')
    require(sha(zip1) == sha(zip2) and zip1.read_bytes() == zip2.read_bytes(), 'build is not reproducible')
    print(f'PASS reproducible build: two independent builds are byte-identical, sha256={sha(zip1)}')
    inventory = read(out / 'inventory.json')
    revision = inventory['source_revision']
    require(revision == git('rev-parse', 'HEAD'), 'inventory revision differs from HEAD')
    members = zip_inventory(zip1, 'grapnelninja-y8.zip')
    require(set(members) == set(build_zip.RUNTIME_FILES) and len(members) == 34,
            'ZIP inventory differs from the 34-file runtime allowlist')
    print('PASS inventory: exactly the 34 allowlisted runtime files, no excluded names')
    require('index.html' in members, 'index.html missing from the ZIP root')
    print('PASS root: index.html is at the archive root')
    with zipfile.ZipFile(zip1) as z:
        html = z.read('index.html').decode('utf-8')
        platform_js = z.read('platform.js').decode('utf-8')
        config_js = z.read('y8config.js').decode('utf-8')
        blobs = {n: z.read(n) for n in members}
    lines, errors = build_zip.check_references(html, list(members))
    require(not errors, 'index.html references: ' + '; '.join(errors))
    externals = [l for l in lines if 'external' in l]
    require(len(externals) == 1 and build_zip.SDK_URL in externals[0], 'exactly one external reference (the Y8 SDK) expected')
    require(html.count('cdn.y8.com') == 1, 'unexpected additional cdn.y8.com reference')
    require(not build_zip.check_y8_config(config_js), 'y8config.js IDs invalid')
    tag = re.search(r"buildVersion:\s*'([^']+)'", platform_js)
    require(tag is not None, 'buildVersion missing from platform.js')
    build_tag = tag.group(1)
    print(f'PASS SDK identity: single external reference {build_zip.SDK_URL}; y8config appId/gameId well-formed; '
          f'platform.js buildVersion={build_tag}')
    extracted = out / 'extracted'
    require(not extracted.exists(), 'extraction root already exists')
    with zipfile.ZipFile(zip1) as z:
        z.extractall(extracted)
    expected = {f['path']: f['sha256'] for f in inventory['files']}
    for name in build_zip.RUNTIME_FILES:
        data = blobs[name]
        digest = sha_bytes(data)
        require(digest == expected[name], f'inventory hash differs: {name}')
        require(data == git_blob(revision, name), f'committed HEAD blob differs: {name}')
        require(data == (ROOT / name).read_bytes(), f'working tree differs: {name}')
        require(data == (extracted / name).read_bytes(), f'extracted file differs: {name}')
    actual = {str(p.relative_to(extracted)): sha(p) for p in extracted.rglob('*') if p.is_file()}
    require(actual == expected, 'extraction holds extra or missing files')
    print(f'PASS source/member hashes: 34 members == committed {revision} blobs == working tree == extraction {rel(extracted)}')
    candidate = dict(task='TASK-285', source_revision=revision, build_tag=build_tag, archive=rel(zip1),
                     zip=str(zip1.resolve()), repeat_archive=rel(zip2), extracted=rel(extracted),
                     byte_count=zip1.stat().st_size, sha256=sha(zip1), identical_sha256=True,
                     external_dependencies=[build_zip.SDK_URL], files=inventory['files'], built_utc=now(),
                     builder_sha256={'tools/build-y8-zip.py': sha(TOOLS / 'build-y8-zip.py'), 'tools/y8_package.py': sha(__file__)})
    write(out / 'candidate.json', candidate)
    print(f"PASS candidate: {candidate['archive']} sha256={candidate['sha256']} bytes={candidate['byte_count']} "
          f"build={build_tag} source={revision}")
    return 0


# ----------------------------------------------------------- functional ----

def parse_engine_notes(engine_notes, webkit_note=None):
    """--engine-note ENGINE=reason (repeatable) plus the --webkit-note alias -> {engine: reason}; unknown engines fail."""
    notes = {}
    for note in list(engine_notes or []) + (['webkit=' + webkit_note] if webkit_note else []):
        engine, sep, reason = note.partition('=')
        engine, reason = engine.strip(), reason.strip()
        require(bool(sep) and engine in REQUIRED_ENGINES and bool(reason),
                f'engine note must be ENGINE=reason with ENGINE in {", ".join(REQUIRED_ENGINES)}: {note!r}')
        notes[engine] = reason
    return notes


def engine_coverage(engines_run, engines_not_run):
    """Pure rule: every REQUIRED engine is either run or explained; returns the sorted list of engines that are neither.

    An engine that was run must not also carry a not-run note (a stale note would otherwise hide a missing run)."""
    run, explained = set(engines_run), set(engines_not_run)
    overlap = sorted(run & explained)
    require(not overlap, 'engines both run and noted as not run: ' + ', '.join(overlap))
    unknown = sorted((run | explained) - set(REQUIRED_ENGINES))
    require(not unknown, 'unknown engines: ' + ', '.join(unknown))
    return sorted(set(REQUIRED_ENGINES) - run - explained)


def require_engine_coverage(engines_run, engines_not_run, where):
    missing = engine_coverage(engines_run, engines_not_run)
    require(not missing, f'{where}: engines neither run nor explained: {", ".join(missing)} '
                         f'(run: {", ".join(sorted(engines_run)) or "none"}; required: {", ".join(REQUIRED_ENGINES)}; '
                         f'pass --engine-note ENGINE=reason for every engine that cannot run)')
    return missing


def cmd_functional(args):
    candidate = read(args.candidate)
    archive, root = ROOT / candidate['archive'], ROOT / candidate['extracted']
    require(sha(archive) == candidate['sha256'], 'candidate archive changed')
    out = args.out
    run, commands = receipt_runner(out)
    failures = read(out / 'failures.json') if (out / 'failures.json').exists() else []
    env = dict(os.environ)
    requested = [e.strip() for e in args.engines.split(',') if e.strip()] if args.engines else list(REQUIRED_ENGINES)
    engines_not_run = parse_engine_notes(getattr(args, 'engine_note', None), getattr(args, 'webkit_note', None))
    # fail before any browser work: every engine left out of --engines needs an --engine-note ENGINE=reason
    require_engine_coverage(requested, engines_not_run, 'functional --engines')
    if args.engines:
        env['Y8_ENGINES'] = args.engines
    for suite in SUITES:
        marker = out / suite / 'instrumentation.json'
        if marker.exists() and read(marker)['verdict'] == 'PASS' and read(marker)['candidate']['sha256'] == candidate['sha256']:
            print(f'SKIP {suite}: already PASS for this exact ZIP')
            continue
        attempt = 1 + sum(1 for c in commands if c['argv'][3:4] == [suite])
        if (out / suite).exists():
            shutil.move(str(out / suite), str(out / f'{suite}-attempt{attempt - 1}'))
        log = f'{suite}.log' if attempt == 1 else f'{suite}-attempt{attempt}.log'
        rc = run([sys.executable, 'tools/verify_y8_candidate.py', '--suite', suite, '--root', rel(root),
                  '--archive', rel(archive), '--out', rel(out / suite)], log, env=env)
        if rc:
            text = (out / log).read_text()
            tail = [l for l in text.splitlines() if l.strip()][-3:]
            failures.append(dict(log=log, suite=suite, attempt=attempt, cause='UNRESOLVED: ' + ' | '.join(tail)[:400],
                                 resolution='pending rerun', initial_runner='tools/verify_y8_candidate.py'))
            write(out / 'failures.json', failures)
            print(f'FAIL {suite}: exit {rc}; failed attempt preserved as {log}; rerun this command after inspection')
            return rc
    if args.failure_note:
        for note in args.failure_note:
            log, _, text = note.partition('=')
            for f in failures:
                if f['log'] == log:
                    f['cause'] = text
                    f['resolution'] = 'successful rerun recorded in commands.json'
        write(out / 'failures.json', failures)
    identity = {k: candidate[k] for k in ('source_revision', 'sha256', 'build_tag')}
    identity['archive'] = candidate['archive']
    identity['extracted'] = candidate['extracted']
    suites = []
    for name in SUITES:
        instrument = read(out / name / 'instrumentation.json')
        require(instrument['verdict'] == 'PASS' and instrument['candidate']['sha256'] == identity['sha256'],
                f'{name}: instrumentation verdict or candidate mismatch')
        data = read(out / name / SUITE_RESULT[name])
        cases = data if isinstance(data, list) else data.get('runs', data.get('flows', []))
        require(len(cases) == len(instrument['contexts']), f'{name}: case/context count mismatch')
        for row, context in zip(cases, instrument['contexts']):
            row.setdefault('engine', context['engine'])
            if name == 'embed':
                row['mode'] = 'bad'
            row['mode_label'] = {'bad': 'Main', 'classic': 'Chill'}[row['mode']]
            row['tested_profile'] = context['profile']
            row['network_failures'] = context['failures']
            row['observed_page_errors'] = context['errors']
            row['trusted_input'] = {'mechanism': 'Playwright mouse/touchscreen/keyboard or CDP Input.dispatchTouchEvent; '
                                                 'state assertions in archived suite source',
                                    'observed_events': context['inputs'],
                                    'document_buffer_reset_by_reload': name in ('release', 'lifecycle')}
        suites.append(dict(suite=name, runner_sha256=sha(TOOLS / 'verify_y8_candidate.py'),
                           evidence=f'{name}/{SUITE_RESULT[name]}', instrumentation=f'{name}/instrumentation.json', results=data,
                           profiles=[dict(engine=c['engine'], version=c['version'], profile=c['profile'], errors=c['errors'],
                                          network_failures=c['failures']) for c in instrument['contexts']],
                           trusted_input='Playwright mouse/touchscreen/keyboard and Chromium Input.dispatchTouchEvent; asserted gameplay '
                                         'effects. Document-local input trace resets on reload in release/lifecycle suites; '
                                         'other suites retain isTrusted traces.',
                           boundaries=instrument['boundaries']))
    engines_run = sorted({p['engine'] for s in suites if s['suite'] == 'release' for p in s['profiles']})
    require_engine_coverage(engines_run, engines_not_run, 'release suite')
    write(out / 'release-checks.json', dict(
        candidate=identity, verdict='PASS', package_ready=False, suites=suites,
        unavailable=['Native Android/iOS physical rotation, OS backgrounding/memory kills: owner only; NOT RUN.',
                     'Real Y8 host, actual SDK/advertising transport, console/moderation: owner only; NOT RUN.'],
        inherited_limitations=['Measured software-renderer regression against the original ZIP remains open (TASK-282); '
                               'no performance claim is derived from these functional suites.'],
        runtime_changes=False, reused_historical_expensive_evidence=False,
        engines_run=engines_run,
        engines_not_run=engines_not_run,
        resolved_harness_failures=[dict(log=f['log'], cause=f['cause'], resolution=f['resolution'],
                                        initial_runner=f['initial_runner']) for f in failures]))
    for name in TESTED_TOOLS:
        target = out / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    write(out / 'tested-tool-hashes.json', {n: sha(ROOT / n) for n in TESTED_TOOLS})
    browsers = {}
    for s in suites:
        for c in s['profiles']:
            browsers[c['engine']] = c['version']
    manifest = dict(created_utc=now(), source_revision=git('rev-parse', 'HEAD'),
                    candidate_source_revision=identity['source_revision'], archive=identity, commands=commands,
                    environment=dict(os=platform.platform(), python=sys.version, playwright=_playwright_version(),
                                     browsers=browsers),
                    dirty_file_sha256={n: sha(ROOT / n) for n in TESTED_TOOLS},
                    evidence_sha256={str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
                                     if p.is_file() and p.name not in ('manifest.json', 'manifest.sha256', 'audit.log')})
    write(out / 'manifest.json', manifest)
    (out / 'manifest.sha256').write_text(sha(out / 'manifest.json') + '  ' + rel(out / 'manifest.json') + '\n')
    os.chdir(ROOT)
    audit_functional(out)
    counts = {s['suite']: len(s['results']) if isinstance(s['results'], list) else
              len(s['results'].get('runs', s['results'].get('flows', []))) for s in suites}
    lifecycle_cases = sum(len(r['cases']) for r in read(out / 'lifecycle/mobile-lifecycle.json')['runs'])
    print(f"PASS functional: exact ZIP {identity['sha256']} build {identity['build_tag']}; release {counts['release']} cases "
          f"({', '.join(sorted(browsers))}), embed {counts['embed']} cases, mobile-embed {counts['mobile-embed']} runs, "
          f"lifecycle {counts['lifecycle']} runs / {lifecycle_cases} cases, ads {counts['ads']} flows; "
          f"harness failures preserved: {len(failures)}")
    return 0


def audit_functional(out):
    """Port of tools/audit_y8_candidate.audit: same checks, engines taken from the actual release results."""
    import struct
    load = lambda name: read(out / name)
    report = load('release-checks.json')
    require(report['verdict'] == 'PASS' and report['package_ready'] is False, 'release-checks verdict/package_ready')
    digest = report['candidate']['sha256']
    require(len(digest) == 64 and report['candidate']['source_revision'] and sha(ROOT / report['candidate']['archive']) == digest,
            'release-checks candidate identity')
    commands = load('commands.json')
    require(bool(commands) and all(c['start_utc'] and c['end_utc'] for c in commands), 'commands.json receipts')
    require({c['log'] for c in commands if c['exit_code']} == {f['log'] for f in report['resolved_harness_failures']},
            'nonzero exits must match documented harness failures')
    for c in commands:
        log = (out / c['log']).read_text()
        require('exit_code=' + str(c['exit_code']) in log and 'COMMAND ' in log, 'receipt log ' + c['log'])
    print('PASS commands.json: actual commands and UTC intervals; nonzero exits matched to documented harness failures')
    release = load('release/results.json')
    engines = sorted({r['engine'] for r in release})
    engines_run, engines_not_run = report.get('engines_run', engines), report.get('engines_not_run', {})
    require(all(isinstance(v, str) and v.strip() for v in engines_not_run.values()), 'engines_not_run notes must be non-empty reasons')
    require_engine_coverage(engines, engines_not_run, 'release/results.json')
    require(sorted(engines_run) == engines, f"release-checks engines_run {sorted(engines_run)} != release results {engines}")
    require(len(release) == 6 * len(engines), 'release case count')
    require({(r['engine'], r['mode']) for r in release} == {(e, m) for e in engines for m in ('bad', 'classic')}, 'release engine/mode matrix')
    require(all(r['verdict'] == 'PASS' and r['resume'].startswith('PASS') and not r['errors'] for r in release), 'release verdicts')
    require(all(r.get('cancel') == 'PASS' for r in release if r['engine'] == 'chromium' and r['touch']), 'chromium touch cancel')
    print(f"PASS release/results.json: {len(release)} Main/Chill browser/profile cases on {', '.join(engines)}; trusted Resume and save/reload"
          + (f"; not run with recorded reasons: {', '.join(sorted(engines_not_run))}" if engines_not_run else ''))
    embed = load('embed/results.json')
    require({r['case'] for r in embed} == {'portrait-frame', 'storage-denied', 'sdk-missing', 'sdk-hang', 'sdk-reject', 'sdk-ready-never'}, 'embed cases')
    require(all(r['verdict'] == 'PASS' and not r['errors'] and r['menu_ms'] < 5000 for r in embed), 'embed verdicts')
    print('PASS embed/results.json: 6 startup/storage cases, missing/stalled/rejected SDK and interrupted touch')
    mobile = load('mobile-embed/mobile-embed.json')
    require(mobile['verdict'] == 'PASS' and len(mobile['runs']) == 4, 'mobile-embed runs')
    for r in mobile['runs']:
        require(r['verdict'] == 'PASS' and not r['errors'] and r['interrupted_hold'].startswith('PASS'), 'mobile-embed run')
        require(bool(r['touch_events']) and all(e['trusted'] for e in r['touch_events']), 'mobile-embed trusted touch')
        states = {s['name']: s for s in r['states']}
        for n in ('landscape-1', 'portrait-1', 'landscape-2', 'portrait-2', 'physical-landscape-fixed-portrait', 'bars-expanded', 'bars-collapsed'):
            a, b = states[n], states[n + '-resumed']
            require(a['paused'] and not b['paused'] and b['physics_steps'] > a['physics_steps'], 'mobile-embed resume ' + n)
        require(all(c['error'] < .001 for c in r['coordinate_checks']), 'mobile-embed coordinates')
        require(all((out / 'mobile-embed' / p).is_file() for p in r['captures']), 'mobile-embed captures')
    print('PASS mobile-embed/mobile-embed.json: 4 nested-frame runs; repeated settled rotations and trusted post-rotation touch')
    lifecycle = load('lifecycle/mobile-lifecycle.json')
    require(lifecycle['overall'] == 'PASS' and len(lifecycle['runs']) == 14, 'lifecycle runs')
    count = 0
    for r in lifecycle['runs']:
        require(r['verdict'] == 'PASS' and not r['page_errors'] and not r['console_errors'], 'lifecycle run')
        cases = {c['case']: c for c in r['cases']}
        require(all(c['verdict'] == 'PASS' for c in r['cases']), 'lifecycle cases')
        require(cases['background-flush']['storage_right_after_hidden']['grapnelninja.time'] == '999', 'background flush')
        require(cases['background-foreground']['resumed'] and cases['blur-focus']['resumed'], 'lifecycle resume')
        count += len(r['cases'])
    print(f'PASS lifecycle/mobile-lifecycle.json: 14 runs, {count} cases; background-save 999, denied storage, resume and recovery')
    ads = load('ads/ad-outcomes.json')
    callbacks = load('ads/callback-traces.json')
    require(ads['verdict'] == callbacks['verdict'] == 'PASS' and len(ads['flows']) == len(callbacks['traces']) == 24, 'ad flows')
    for r in ads['flows']:
        require(r['verdict'] == 'PASS' and not r['page_errors'] and r['recovery'].startswith('PASS'), 'ad flow')
        require(r['reward_count'] == (1 if r['flow'] == 'viewed' else 0), 'reward count')
        require(not r['terminal']['adOpen'] and not r['terminal']['pending'], 'ad terminal state')
        require(r['recovered']['physics'] > r['terminal']['physics'] and r['pause_menu']['paused'], 'ad recovery')
    print('PASS ads/ad-outcomes.json and ads/callback-traces.json: 24 offline flows; viewed/dismissed/no-fill/blocked recovery, exact reward counts')
    fixture = sha(out / 'sources/tools/fixtures/fake-y8-sdk.js')
    expected = load('release/instrumentation.json')['candidate']['runtime_sha256']
    for suite in SUITES:
        data = load(suite + '/instrumentation.json')
        require(data['verdict'] == 'PASS' and data['candidate']['sha256'] == digest, suite + ' instrumentation')
        require(data['candidate']['runtime_sha256'] == expected, suite + ' runtime hashes')
        for name, h in expected.items():
            require(sha(Path(data['candidate']['root']) / name) == h, suite + ' root ' + name)
        for c in data['contexts']:
            require(bool(c['transport']) and not c['errors'], suite + ' context')
            for t in c['transport']:
                if t['action'] == 'fulfill' and not t['url'].startswith('http://127.0.0.1:'):
                    require(t['url'] == build_zip.SDK_URL and t['body_sha256'] == fixture, suite + ' non-local fulfil')
            events = [e for f in c['inputs'] for e in f['events']]
            require(all(e['trusted'] for e in events), suite + ' trusted input')
            if suite in ('embed', 'mobile-embed', 'ads'):
                require(bool(events), suite + ' input events')
            require(all(t['action'] in ('fulfill', 'abort') or t['url'].startswith('http://127.0.0.1:') for t in c['transport']), suite + ' transport')
        print(f'PASS {suite}/instrumentation.json: candidate {digest}, trusted input, errors and offline routing recorded')
    pngs = list(out.rglob('*.png'))
    for p in pngs:
        data = p.read_bytes()
        require(data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) > 1000 and min(struct.unpack('>II', data[16:24])) >= 100, str(p))
    print(f'PASS PNG evidence: {len(pngs)} valid files (native browser captures); physical phones NOT RUN')
    manifest = load('manifest.json')
    require(bool(manifest['source_revision'] and manifest['environment'] and manifest['commands']), 'functional manifest')
    require(manifest['archive']['sha256'] == digest, 'manifest archive')
    for p, h in manifest['evidence_sha256'].items():
        require(sha(out / p) == h, 'evidence hash ' + p)
    require(all(sha(ROOT / p) == h for p, h in manifest['dirty_file_sha256'].items()), 'tested tool hashes match current files')
    print(f"PASS manifest.json: {len(manifest['evidence_sha256'])} evidence hashes verified; command/source/archive/tool identities recorded")
    print('PASS release-checks.json: exact candidate binding and per-case engine/profile/mode/results; fixture/native boundaries explicit')


def _playwright_version():
    try:
        import importlib.metadata
        return importlib.metadata.version('playwright')
    except Exception:
        return subprocess.check_output([sys.executable, '-c', 'import importlib.metadata as m;print(m.version("playwright"))'],
                                       text=True).strip()


# ---------------------------------------------------------------- media ----

def pixel_compare(new, old):
    from PIL import Image, ImageChops
    with Image.open(new) as a, Image.open(old) as b:
        a = a.convert('RGBA')
        b = b.convert('RGBA')
        if a.size != b.size:
            return dict(same_dimensions=False, pixel_identical=False, differing_pixels=None, max_channel_diff=None)
        diff = ImageChops.difference(a, b)
        # Per-pixel maximum over all four channels; a histogram counts differing pixels exactly.
        maximum = diff.split()[0]
        for band in diff.split()[1:]:
            maximum = ImageChops.lighter(maximum, band)
        histogram = maximum.histogram()
        differing = sum(histogram[1:])
        if differing == 0:
            return dict(same_dimensions=True, pixel_identical=True, differing_pixels=0, max_channel_diff=0)
        return dict(same_dimensions=True, pixel_identical=False, differing_pixels=differing,
                    max_channel_diff=max(i for i, count in enumerate(histogram) if count), bbox=list(maximum.getbbox()))


REVIEW_PENDING = 'PENDING: open contact-sheet.png and record a note with --review'


def capture_fingerprint(review):
    """sha256 of every shipped asset and source frame a media review describes: the bytes the visual review was given on."""
    return {**{a['path']: a['sha256'] for a in review.get('assets', [])},
            **{f['file']: f['sha256'] for f in review.get('source_frames', [])}}


def carry_over_review(review, previous):
    """Pure rule (TASK-295): keep the previous visual_review/verdict only when the captures are byte-identical.

    Returns (review, warning). `review` is updated in place: a carried-over note records review_carried_over=True
    and the utc it was first recorded at; differing captures reset the verdict to PENDING explicitly and the warning
    names the files that changed."""
    if not previous or previous.get('verdict') not in ('PASS', 'FAIL'):
        review['review_carried_over'] = False
        return review, None
    before, after = capture_fingerprint(previous), capture_fingerprint(review)
    if before and before == after:
        review.update(visual_review=previous['visual_review'], visual_review_utc=previous.get('visual_review_utc'),
                      verdict=previous['verdict'], review_carried_over=True,
                      review_carried_over_from_utc=previous.get('visual_review_utc'),
                      review_carry_over_basis=f'{len(after)} captures byte-identical to the reviewed ones')
        return review, None
    changed = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
    review.update(visual_review=REVIEW_PENDING, verdict='PENDING', review_carried_over=False,
                  review_reset_reason='captures differ from the ones the previous note reviewed: ' + ', '.join(changed),
                  previous_review=dict(verdict=previous['verdict'], visual_review=previous['visual_review'],
                                       visual_review_utc=previous.get('visual_review_utc')))
    review.pop('visual_review_utc', None)
    return review, (f"previous {previous['verdict']} visual review discarded: {len(changed)} capture(s) differ from the reviewed "
                    f"ones ({', '.join(changed)}); verdict reset to PENDING, review contact-sheet.png again and pass --review")


def apply_review_note(review, note):
    """Record a --review note on the review dict that is about to be written (same run as the captures)."""
    review.update(visual_review=note, visual_review_utc=now(), verdict='PASS' if note.upper().startswith('PASS') else 'FAIL',
                  review_carried_over=False)
    review.pop('review_carried_over_from_utc', None)
    review.pop('review_carry_over_basis', None)
    review.pop('review_reset_reason', None)
    return review


def run_media_review(out, review_note, capture, build_review):
    """Capture (only when media-manifest.json is missing), build the review, carry over or reset a previous note,
    apply --review in the same run, then write media-review.json once. Returns the written review."""
    review_path = out / 'media-review.json'
    previous = read(review_path) if review_path.exists() else None
    if not (out / 'media-manifest.json').exists():
        capture(out)
    review = build_review(out)
    review, warning = carry_over_review(review, previous)
    if warning:
        print('WARNING ' + warning, flush=True)
    if review_note:
        apply_review_note(review, review_note)
    write(review_path, review)
    return review


def cmd_media(args):
    candidate = read(args.candidate)
    out = args.out
    inventory = Path(candidate['archive']).resolve().parent / 'inventory.json'
    require(inventory.exists() and read(inventory)['sha256'] == candidate['sha256'], 'build inventory.json missing or stale')

    def capture(out):
        run, _ = receipt_runner(out)
        for stage in ('covers', 'screenshots', 'inventory'):
            rc = run([sys.executable, 'tools/prepare_y8_media.py', stage, '--candidate', rel(inventory),
                      '--seeds', SEEDS, '--out', rel(out)], f'{stage}.log')
            require(rc == 0, f'media stage {stage} failed (log preserved: {stage}.log)')

    review = run_media_review(out, args.review, capture, lambda out: build_media_review(out, candidate))
    print(f"PASS media: {review['regenerated_assets']} assets recaptured from exact ZIP {candidate['sha256']} at "
          f"{candidate['source_revision']}; pixel-identical to TASK-263 historical captures: "
          f"{review['pixel_identical_to_historical']}; verdict={review['verdict']}"
          + ('; review carried over from ' + str(review.get('review_carried_over_from_utc')) if review.get('review_carried_over')
             else '; visual review pending' if review['verdict'] == 'PENDING' else ''))
    return 0


def build_media_review(out, candidate):
    manifest = read(out / 'media-manifest.json')
    require(manifest['archive_sha256'] == candidate['sha256'], 'media captured from a different archive')
    frames = {}
    for folder in ('source-frames', 'screenshots'):
        meta = read(out / folder / 'source-frames.json')
        for frame in meta['frames'].values():
            frames[frame['file']] = dict(frame, captured_utc=meta['captured_utc'], archive_sha256=meta['archive_sha256'],
                                         source_revision=meta['source_revision'], folder=folder)
    historical_frames = {}
    for folder in ('source-frames', 'screenshots'):
        meta = read(HISTORICAL_MEDIA / folder / 'source-frames.json')
        for frame in meta['frames'].values():
            historical_frames[frame['file']] = dict(frame, captured_utc=meta['captured_utc'], folder=folder,
                                                    source_revision=meta['source_revision'], archive_sha256=meta['archive_sha256'])
    assets = []
    identical = 0
    for asset in manifest['assets']:
        path = Path(asset['path'])
        folder = path.parent.name
        historical = HISTORICAL_MEDIA / folder / path.name
        entry = dict(asset, path=f'{folder}/{path.name}', capture_revision=candidate['source_revision'],
                     capture_archive_sha256=candidate['sha256'], build_tag=candidate['build_tag'],
                     status='REFRESHED: recaptured from this exact ZIP (not a reused historical asset)')
        if folder == 'screenshots':
            frame = frames[path.name]
            entry.update(capture_utc=frame['captured_utc'], mode=frame['mode'], seed=frame['seed'], tick=frame['tick'],
                         canvas=frame['canvas'], dpr=frame['dpr'])
        else:
            frame = frames['crop-bad-seed4-t180.png'] if 'crop-bad-seed4-t180.png' in frames else next(
                f for f in frames.values() if f['folder'] == 'source-frames' and f['dpr'] == 1.5)
            entry.update(capture_utc=frame['captured_utc'], composed_from=frame['file'], mode=frame['mode'], seed=frame['seed'],
                         tick=frame['tick'], source_canvas=frame['canvas'], source_dpr=frame['dpr'])
        if historical.exists():
            comparison = pixel_compare(path, historical)
            entry['historical'] = dict(path=rel(historical), sha256=sha(historical),
                                       capture_revision=read(HISTORICAL_MEDIA / 'media-manifest.json')['source_revision'],
                                       archive_sha256=read(HISTORICAL_MEDIA / 'media-manifest.json')['archive_sha256'],
                                       **comparison)
            identical += comparison['pixel_identical']
        else:
            entry['historical'] = None
        assets.append(entry)
    frame_rows = []
    for name, frame in frames.items():
        old = historical_frames.get(name)
        row = dict(file=f"{frame['folder']}/{name}", sha256=sha(out / frame['folder'] / name), mode=frame['mode'], seed=frame['seed'],
                   tick=frame['tick'], dpr=frame['dpr'], canvas=frame['canvas'], ninja=frame['ninja'], score=frame['score'],
                   death_tick=frame['deathTick'], captured_utc=frame['captured_utc'])
        if old:
            row['historical'] = dict(sha256=old['sha256'], source_revision=old['source_revision'], ninja=old['ninja'],
                                     state_equal=(old['ninja'] == frame['ninja'] and old['score'] == frame['score']),
                                     **pixel_compare(out / frame['folder'] / name, HISTORICAL_MEDIA / old['folder'] / name))
        frame_rows.append(row)
    review = dict(
        task='TASK-285', candidate=candidate['sha256'], source_revision=candidate['source_revision'], build_tag=candidate['build_tag'],
        decision='REFRESHED', regenerated_assets=len(assets), reused_assets=0,
        reuse_or_refresh=f'All {len(assets)} shipped assets were recaptured from the exact TASK-285 ZIP; the TASK-263 captures '
                         f'(source 15aab22...) are kept only as the comparison baseline and are not shipped.',
        pixel_identical_to_historical=f'{identical}/{len(assets)}',
        comparison_meaning='pixel identity with the historical captures independently confirms that the TASK-280 render change '
                           'and the build-tag change left these deterministic frames unchanged; a difference would require a '
                           'fresh visual review, not rejection',
        assets=assets, source_frames=frame_rows,
        method='Main (internal bad) seed 4: deterministic physics/draw replay (tools/autopilot.js) at 1920x1080 DPR 1 and DPR 1.5; '
               'covers are aspect crops of the DPR 1.5 frame with the composed title; screenshots keep the release HUD',
        tools_sha256={n: sha(ROOT / n) for n in MEDIA_TOOLS},
        console_slots='OWNER-VERIFIED: console dimensions, format, byte/count limits and video requirement not accessible here',
        contact_sheet=rel(out / 'contact-sheet.png'),
        visual_review=REVIEW_PENDING, verdict='PENDING')
    return review


# ------------------------------------------------------------ readiness ----

def decide(functional_prepared, regression_outstanding, native_counts, owner_checks_performed):
    """Pure decision rule shared by readiness.json and the tests: fields stay separate."""
    all_native_pass = (native_counts.get('PASS', 0) == 10 and native_counts.get('FAIL', 0) == 0
                       and native_counts.get('UNVERIFIED', 0) == 0)
    fps = bool(all_native_pass and not regression_outstanding)
    blockers = []
    if not functional_prepared:
        blockers.append('functional package preparation incomplete')
    if regression_outstanding:
        blockers.append('measured software-renderer regression against the original ZIP outstanding (TASK-282)')
    if not all_native_pass:
        blockers.append('native 60-FPS acceptance rows not all PASS (TASK-284: %s)' % json.dumps(native_counts, sort_keys=True))
    if not owner_checks_performed:
        blockers.append('owner-only checks NOT PERFORMED')
    return {'60fps_achieved': fps, 'submission_ready': bool(fps and functional_prepared and owner_checks_performed and not blockers),
            'submission_blockers': blockers}


BUILD_VERSION_LINE = re.compile(r"^\s*buildVersion:\s*'[^']*',?\s*$")


def build_tag_only_difference(runner_text, candidate_text):
    """True when the two platform.js bodies differ in exactly one line and that line is the buildVersion string."""
    diff = [l for l in difflib.unified_diff(runner_text.splitlines(), candidate_text.splitlines(), lineterm='', n=0)
            if (l.startswith('+') or l.startswith('-')) and not l.startswith('+++') and not l.startswith('---')]
    removed = [l[1:] for l in diff if l.startswith('-')]
    added = [l[1:] for l in diff if l.startswith('+')]
    return (len(removed) == 1 and len(added) == 1
            and bool(BUILD_VERSION_LINE.match(removed[0])) and bool(BUILD_VERSION_LINE.match(added[0])))


def runner_runtime_binding(candidate_files, candidate_root, runner_game, decision_package):
    """Bind the runtime the owner measured (bench runner package, game/build.json) to the candidate ZIP members.

    Every runtime member of the candidate must hash-equal the served member of the runner package; index.html is
    compared with the committed (unpatched) index the runner recorded, because the served copy swaps the SDK tag
    for bench.js. A platform.js whose sole differing line is buildVersion is tolerated and listed under
    build_tag_only. Anything else lands in differing and the binding is not matched. The package on disk must be
    the one decision.json names (served_tree_sha256 / source_revision / build_version) and its served files must
    still hash to build.json, otherwise the binding is not matched either."""
    runner_game, candidate_root = Path(runner_game), Path(candidate_root)
    build_path = runner_game / 'build.json'
    binding = dict(runner_package=rel(runner_game.parent), build_json=rel(build_path), matched=False, differing=[],
                   build_tag_only=[], package_matches_decision=False, served_tree_intact=False, problems=[])
    if not build_path.is_file():
        binding['problems'].append(f'runner package build.json missing: {rel(build_path)}')
        binding['differing'] = ['<runner package build.json missing>']
        return binding
    build = read(build_path)
    served = build.get('served_files_sha256', {})
    binding.update(runner_source_revision=build.get('source_revision'), runner_build_version=build.get('build_version'),
                   runner_served_tree_sha256=build.get('served_tree_sha256'))
    identity_keys = (('served_tree_sha256', 'served_tree_sha256'), ('source_revision', 'source_revision'),
                     ('build_version', 'build_version'))
    mismatched = [k for k, d in identity_keys if decision_package.get(d) != build.get(k)]
    binding['package_matches_decision'] = not mismatched
    if mismatched:
        binding['problems'].append('runner package identity differs from decision.json package: ' + ', '.join(mismatched))
    actual = {str(p.relative_to(runner_game).as_posix()): sha(p) for p in runner_game.rglob('*')
              if p.is_file() and p.name not in ('build.json', 'PATCH.diff')}
    binding['served_tree_intact'] = actual == served
    if not binding['served_tree_intact']:
        binding['problems'].append('runner package game/ files no longer hash to their build.json')
    members = {}
    for f in candidate_files:
        path, digest = f['path'], f['sha256']
        expected = build.get('committed_index_html_sha256') if path == 'index.html' else served.get(path)
        if expected == digest:
            members[path] = 'matched'
        elif path == 'platform.js' and (runner_game / path).is_file() and (candidate_root / path).is_file() \
                and build_tag_only_difference((runner_game / path).read_text(), (candidate_root / path).read_text()):
            members[path] = 'build_tag_only'
            binding['build_tag_only'].append(path)
        else:
            members[path] = 'differing' if expected else 'missing_from_runner'
            binding['differing'].append(path)
    binding['differing'].sort()
    binding['build_tag_only'].sort()
    binding['members'] = members
    binding['matched'] = (not binding['differing'] and binding['package_matches_decision'] and binding['served_tree_intact'])
    return binding


def native_acceptance(decision, binding):
    """Counts/status/blocker actually used by the decision rule: the recorded counts only count when the owner
    measured the same runtime bytes as the candidate; otherwise every row is UNVERIFIED and a blocker names the files."""
    recorded = dict(decision['counts'])
    blockers = []
    if binding['matched']:
        counts = recorded
    else:
        counts = {'PASS': 0, 'FAIL': 0, 'UNVERIFIED': sum(recorded.values())}
        what = ', '.join(binding['differing']) if binding['differing'] else '; '.join(binding['problems'])
        blockers.append(f'runner package runtime differs from candidate: {what}')
    status = 'UNVERIFIED' if counts.get('UNVERIFIED') else ('FAIL' if counts.get('FAIL') else 'PASS')
    return dict(counts=counts, counts_as_recorded=recorded, status=status, blockers=blockers)


def ticket_audit(task):
    tid = task['id']
    directory = ROOT / 'artifacts' / tid
    row = dict(id=tid, status=task['status'], title=task['description'].split('. ')[0][:160],
               evidence_dir_present=directory.is_dir(), manifest_present=(directory / 'manifest.json').is_file(),
               evidence_audit_result=None, verifier_note_in_progress=False)
    audit = directory / 'evidence-audit.log'
    if audit.is_file():
        found = re.findall(r'^RESULT .*$', audit.read_text(errors='replace'), re.M)
        row['evidence_audit_result'] = found[-1] if found else None
    progress = (ROOT / 'artifacts/progress.md')
    if progress.is_file():
        row['verifier_note_in_progress'] = bool(re.search(r'^## %s verification' % re.escape(tid), progress.read_text(errors='replace'), re.M))
    m = re.search(r'Implemented: (.*)', task['description'])
    row['implemented_note'] = m.group(1)[:300] if m else None
    row['historical_result'] = {'done': 'VERIFIED_EVIDENCE', 'autoskip': 'HISTORICAL_UNRESOLVED', 'skip': 'SKIPPED',
                                'blocked': 'BLOCKED', 'pending': 'PENDING', 'to-verify': 'TO_VERIFY'}.get(task['status'], task['status'])
    return row


def scope_tickets(by_id):
    """Audit every SCOPE ticket; a scope id absent from the task list is a hard failure, never a silently shorter list."""
    missing = [i for i in SCOPE if i not in by_id]
    require(not missing, 'scope tickets missing from the task list: ' + ', '.join(missing))
    return [ticket_audit(by_id[i]) for i in SCOPE]


def cmd_readiness(args):
    candidate = read(args.candidate)
    checks = read(args.functional / 'release-checks.json')
    media = read(args.media / 'media-review.json')
    tasks = read(args.tasks)
    tasks = tasks if isinstance(tasks, list) else tasks['tasks']
    by_id = {t['id']: t for t in tasks}
    tickets = scope_tickets(by_id)
    engines_missing = engine_coverage(checks.get('engines_run', []), checks.get('engines_not_run', {}))
    functional_prepared = (checks['verdict'] == 'PASS' and checks['candidate']['sha256'] == candidate['sha256']
                           and media['verdict'] == 'PASS' and media['candidate'] == candidate['sha256'] and not engines_missing)
    comparison = read(ROOT / 'artifacts/TASK-282/comparison.json')
    ranking = read(ROOT / 'artifacts/TASK-282/cost-ranking.json')
    identity = read(ROOT / 'artifacts/TASK-282/identity.json')
    cells = {}
    regression_outstanding = False
    for name, cell in comparison['cells'].items():
        cells[name] = dict(viewport=cell['viewport'], dpr=cell['dpr'], backing=cell['backing'], verdict_vs_control=cell['verdict_vs_control'],
                           median_reduction_vs_control_fraction=cell['vs_control']['median_reduction_fraction'],
                           median_reduction_vs_control_ms=cell['vs_control']['median_reduction_ms'],
                           integrated_fps=cell['vs_control']['median_integrated_fps'], control_fps=cell['vs_control']['median_reference_fps'],
                           original_fps=cell['vs_original']['median_reference_fps'],
                           integrated_over_original_frame_time_ratio=cell['deficit_vs_original']['integrated_over_original_frame_time_ratio'],
                           integrated_slower_than_original=cell['deficit_vs_original']['integrated_slower_than_original'])
        regression_outstanding |= bool(cell['deficit_vs_original']['integrated_slower_than_original'])
    task282_runtime = identity['files_sha256']['integrated']
    runtime_match = {f['path']: (task282_runtime.get(f['path']) == f['sha256']) for f in candidate['files']}
    differing = sorted(p for p, ok in runtime_match.items() if not ok)
    decision = read(ROOT / 'artifacts/TASK-284/decision.json')
    binding = runner_runtime_binding(candidate['files'], ROOT / candidate['extracted'], args.runner / 'game', decision['package'])
    native = native_acceptance(decision, binding)
    native_counts = native['counts']
    historical = {}
    gate = ROOT / 'artifacts/TASK-265/live-geometry/final-byte/performance/performance-gate.json'
    if gate.is_file():
        runs = read(gate)['runs']
        historical['TASK-265'] = dict(status=by_id.get('TASK-265', {}).get('status'),
                                      failing_runs=sorted(r['id'] for r in runs if str(r.get('verdict', '')).startswith('FAIL')),
                                      note='historical six FAIL_MEASURED_REGRESSION verdicts preserved as evidence; the autoskip '
                                           'status is not a hardcoded blocker of this readiness evaluation')
    historical['TASK-270'] = dict(status=by_id.get('TASK-270', {}).get('status'),
                                  note='historical packaging ticket; its pending status is recorded, not required to change')
    verdict = decide(functional_prepared, regression_outstanding, native_counts, owner_checks_performed=False)
    for blocker in reversed(native['blockers']):
        verdict['submission_blockers'].insert(0, blocker)
    if engines_missing:
        verdict['submission_blockers'].insert(0, 'release suite engines neither run nor explained: ' + ', '.join(engines_missing))
    readiness = dict(
        task='TASK-285', generated_utc=now(), scope='TASK-271 through TASK-284 plus applicable functional evidence; later tasks excluded',
        candidate=dict(sha256=candidate['sha256'], source_revision=candidate['source_revision'], build_tag=candidate['build_tag'],
                       archive=candidate['archive']),
        tickets=tickets,
        ticket_status_counts={s: sum(1 for t in tickets if t['status'] == s) for s in sorted({t['status'] for t in tickets})},
        functional_package_preparation=dict(
            status='PREPARED' if functional_prepared else 'INCOMPLETE', functional_package_prepared=functional_prepared,
            engines=dict(required=list(REQUIRED_ENGINES), run=sorted(checks.get('engines_run', [])),
                         not_run=checks.get('engines_not_run', {}), neither_run_nor_explained=engines_missing),
            exact_zip_functional_checks=dict(path=rel(args.functional / 'release-checks.json'), verdict=checks['verdict'],
                                             candidate_sha256=checks['candidate']['sha256'],
                                             suites={s['suite']: (len(s['results']) if isinstance(s['results'], list) else
                                                                  len(s['results'].get('runs', s['results'].get('flows', []))))
                                                     for s in checks['suites']},
                                             harness_failures_preserved=len(checks['resolved_harness_failures'])),
            media=dict(path=rel(args.media / 'media-review.json'), verdict=media['verdict'], decision=media['decision'],
                       pixel_identical_to_historical=media['pixel_identical_to_historical']),
            superseded_functional_evidence=dict(path='artifacts/TASK-268/release-checks.json', candidate_sha256='c96a029eaff51071ea0bab0d260981dd14c0c91629097d49784e812eda01bc12',
                                                applicability='historical: same suites on candidate267; not reused because render/effects.js '
                                                              'and platform.js differ from this ZIP; all suites were re-run on the exact ZIP')),
        software_regression_status=dict(
            status='MEASURED_REGRESSION_VS_ORIGINAL_ZIP' if regression_outstanding else 'NO_MEASURED_REGRESSION',
            regression_outstanding=regression_outstanding, faster_than_frozen_control=all(c['verdict_vs_control'] == 'FASTER' for c in cells.values()),
            evidence='artifacts/TASK-282/comparison.json and cost-ranking.json (headless software Chromium, SwiftShader, 1280x720 dpr1 and 844x390 dpr2, pinned density)',
            runtime_binding=dict(task282_integrated_runtime_equals_this_zip=not differing, differing_files=differing,
                                 note='platform.js differs only by the buildVersion string (candidate267 -> candidate285); render/effects.js is the '
                                      'TASK-280 body measured by TASK-282' if differing == ['platform.js'] else 'see differing_files'),
            cells=cells, identity_exact_vs_control=ranking.get('integrated_identity_exact'),
            historical_failures_preserved=historical, qualification=QUALIFICATION),
        native_60fps_acceptance=dict(
            status=native['status'],
            evidence='artifacts/TASK-284/decision.json', evaluation_completed=decision['evaluation_completed'],
            counts=native_counts, counts_as_recorded=native['counts_as_recorded'], row_verdicts=decision['row_verdicts'],
            runner_runtime_binding={k: binding[k] for k in ('matched', 'differing', 'build_tag_only')},
            note=('owner-returned native results fill these rows; nothing local can; the runner package named by decision.json serves '
                  'the same runtime bytes as this ZIP' + (' except platform.js, which differs only by the buildVersion line'
                                                          if binding['build_tag_only'] else '')
                  if binding['matched'] else
                  'the runner package named by decision.json does not serve this ZIP\'s runtime bytes; recorded rows are not '
                  'evidence for this candidate and every row is treated as UNVERIFIED')),
        runner_runtime_binding=binding,
        **{'60fps_achieved': verdict['60fps_achieved']},
        submission_readiness=dict(submission_ready=verdict['submission_ready'], blockers=verdict['submission_blockers'],
                                  owner_checks={k: 'NOT PERFORMED' for k in OWNER_CHECKS}),
        moderation_status=dict(status='NOT_SUBMITTED', uploaded=False, moderation_approved=False,
                               note='owner controls console upload and moderation; no public gameplay, production ads or upload occurred'),
        decision_rule=dict(fps='60fps_achieved is true only when all 10 TASK-284 native rows PASS, the runner package the owner measured '
                               'serves the same runtime bytes as this ZIP (platform.js may differ only by buildVersion) and no measured '
                               'regression against the original ZIP is outstanding; it is independent of the package audit',
                           submission='submission_ready requires 60fps_achieved, a prepared functional package and performed owner checks',
                           historical='historical autoskip/pending statuses are recorded, never used as hardcoded blockers; '
                                      'current evidence is evaluated separately',
                           no_retry='unchanged package checks are not repeated to force a green field'))
    write(args.out, readiness)
    print(f"runner_runtime_binding: matched={binding['matched']} build_tag_only={binding['build_tag_only']} "
          f"differing={binding['differing']} package_matches_decision={binding['package_matches_decision']} "
          f"runner={binding['runner_package']} counts_as_recorded={json.dumps(native['counts_as_recorded'], sort_keys=True)}")
    for blocker in native['blockers']:
        print('BLOCKER ' + blocker)
    print(f"PASS readiness written: functional_package_prepared={functional_prepared} software_regression="
          f"{readiness['software_regression_status']['status']} native60={readiness['native_60fps_acceptance']['status']} "
          f"60fps_achieved={verdict['60fps_achieved']} submission_ready={verdict['submission_ready']} moderation=NOT_SUBMITTED")
    return 0


# ------------------------------------------------------------- assemble ----

def deterministic_zip(target, root):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob('*')):
            if p.is_file():
                info = zipfile.ZipInfo(str(p.relative_to(root)), (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                z.writestr(info, p.read_bytes())


def cmd_assemble(args):
    candidate = read(args.candidate)
    checks = read(args.functional / 'release-checks.json')
    media = read(args.media / 'media-review.json')
    readiness = read(args.readiness)
    require(checks['candidate']['sha256'] == media['candidate'] == readiness['candidate']['sha256'] == candidate['sha256'],
            'candidate identity differs between build, functional, media and readiness')
    require(media['verdict'] == 'PASS', 'media visual review not recorded as PASS')
    release, kit, out = args.release, args.kit, args.out
    previous = out / 'previous-release'
    require(not previous.exists() and not (out / 'previous-submission-kit.zip').exists(), 'previous release already preserved here')
    if release.exists():
        shutil.move(str(release), str(previous))
        print(f'PASS previous release preserved: {rel(previous)}')
    if kit.exists():
        shutil.move(str(kit), str(out / 'previous-submission-kit.zip'))
        print(f"PASS previous kit preserved: {rel(out / 'previous-submission-kit.zip')} sha256={sha(out / 'previous-submission-kit.zip')}")
    release.mkdir(parents=True)
    shutil.copyfile(ROOT / candidate['archive'], release / 'grapnelninja-y8.zip')
    require(sha(release / 'grapnelninja-y8.zip') == candidate['sha256'], 'copied ZIP differs')
    for asset in media['assets']:
        dest = release / asset['path']
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(args.media / asset['path'], dest)
        require(sha(dest) == asset['sha256'], 'media copy differs: ' + asset['path'])
    write(release / 'media-manifest.json', media)
    identity = (f"Source: {candidate['source_revision']}\nBuild: {candidate['build_tag']}\n"
                f"ZIP SHA256: {candidate['sha256']}\nZIP bytes: {candidate['byte_count']}\n")
    (release / 'LISTING.txt').write_text('\n'.join(LISTING) + '\n' + identity)
    suites = readiness['functional_package_preparation']['exact_zip_functional_checks']['suites']
    lifecycle_cases = sum(len(r['cases']) for r in read(args.functional / 'lifecycle/mobile-lifecycle.json')['runs'])
    engines = sorted({p['engine'] for s in checks['suites'] if s['suite'] == 'release' for p in s['profiles']})
    reg = readiness['software_regression_status']
    native = readiness['native_60fps_acceptance']
    (release / 'TEST-RESULTS.txt').write_text(identity +
        f"PASS exact-ZIP offline checks (TASK-285, this archive): release {suites['release']} browser cases ({', '.join(engines)}), "
        f"embed {suites['embed']} startup/storage cases, mobile-embed {suites['mobile-embed']} nested-frame runs, "
        f"lifecycle {suites['lifecycle']} runs / {lifecycle_cases} cases, ads {suites['ads']} offline rewarded flows.\n"
        f"PASS media: six covers and three screenshots recaptured from this exact ZIP at {candidate['source_revision']}; "
        f"pixel-identical to the TASK-263 historical captures: {media['pixel_identical_to_historical']}.\n"
        f"PERFORMANCE (software renderer, TASK-282): {reg['status']}; faster than the frozen TASK-271 control in every cell, "
        f"still about 2x the frame time of the original ZIP. {QUALIFICATION}\n"
        f"NATIVE 60 FPS (TASK-284): {native['status']}; rows {json.dumps(native['counts'], sort_keys=True)}; no owner results returned.\n"
        f"60fps_achieved={str(readiness['60fps_achieved']).lower()}; submission_ready={str(readiness['submission_readiness']['submission_ready']).lower()}; "
        f"moderation_status={readiness['moderation_status']['status']}; uploaded=false\n"
        'Owner checks NOT PERFORMED: ' + '; '.join(OWNER_CHECKS) + '\n'
        'Evidence references and hashes: manifest.json external_evidence_sha256 (local workspace, not included in kit).\n')
    (release / 'UPLOAD.txt').write_text(identity +
        'LOCAL INSPECTION ONLY - measured performance regression and native 60-FPS acceptance are outstanding.\n'
        'Owner later uploads only grapnelninja-y8.zip, with root index.html. This kit is not the game upload.\n'
        'Use LISTING.txt, media/, screenshots/ and media-manifest.json; verify actual console slots.\n'
        'Complete OWNER-CHECKLIST.txt, inspect TEST-RESULTS.txt and requirements.json, then review REVIEWER-RESPONSE.txt.\n'
        'No upload, live ads, physical checks or moderation performed. No approval guaranteed.\n')
    (release / 'REVIEWER-RESPONSE.txt').write_text(
        'DRAFT - owner must validate before sending\n'
        'The candidate retains touch cancellation, focus handling, portrait presentation and visibility-save fixes, and clips the '
        'glow composite to the dilated primitive rectangles (TASK-280) with pixel-identical output in the archived identity sessions.\n'
        'Offline checks against this exact archive passed across local desktop and emulated mobile browser profiles, including interrupted '
        'input and rewarded-ad fixtures; these are not native-phone or hosted-ad results.\n'
        f"The six covers and three gameplay screenshots were recaptured from this exact archive (source {candidate['source_revision']}).\n"
        'The measured software-renderer frame time remains about twice the original ZIP; native phones, Y8 preview/fullscreen, live ad '
        'outcomes, console slots and moderation remain owner checks, and no readiness, guaranteed FPS or resolved rejection is claimed.\n')
    owner_doc = (ROOT / 'Y8-OWNER-CHECKLIST.md').read_text()
    body = owner_doc.split('Record for EACH run:', 1)[1]
    (release / 'OWNER-CHECKLIST.txt').write_text(
        'Grapnel Ninja - owner preview and phone checklist (TASK-285 kit)\n\n'
        'Local preparation only. All owner checks below are NOT PERFORMED. Console access,\n'
        'phones and moderation do not gate completion of this preparation checklist.\n\n'
        'Package identity (paths relative to /opt/grapnelninja):\n'
        f"- Final candidate for these owner checks: grapnelninja-y8.zip (beside this checklist; workspace: {rel(release / 'grapnelninja-y8.zip')})\n"
        f"- SHA256: {candidate['sha256']}\n- Build: {candidate['build_tag']}; size: {candidate['byte_count']} bytes\n"
        f"- Source: {candidate['source_revision']}\n- Inventory: {candidate['archive'].replace('grapnelninja-y8.zip', 'candidate.json')}\n"
        f"- Exact-ZIP offline checks: {rel(args.functional / 'release-checks.json')}\n"
        '- Current copy/media instructions: LISTING.txt, REVIEWER-RESPONSE.txt and media-manifest.json\n'
        f"- Media review: {rel(args.media / 'media-review.json')}; all nine assets recaptured from this exact ZIP.\n"
        '- Native 60-FPS benchmark rows: artifacts/TASK-283/runner/OWNER-CHECKLIST.txt (return results/*.json; TASK-284 rows are UNVERIFIED).\n'
        '- Verify the selected ZIP with sha256sum before upload and record the hash below.\n'
        '  A displayed build label alone does not distinguish archives.\n'
        '- Local preparation only: the measured software-renderer regression against the original ZIP (TASK-282) is outstanding;\n'
        '  no upload, live ads or submission was performed.\n\n'
        'Record for EACH run:' + body)
    write(release / 'requirements.json', dict(
        scope=readiness['scope'], tickets=[dict(id=t['id'], status=t['status'], result=t['historical_result']) for t in readiness['tickets']],
        functional_package_prepared=readiness['functional_package_preparation']['functional_package_prepared'],
        software_regression_status=reg['status'], native_60fps_acceptance=native['status'],
        **{'60fps_achieved': readiness['60fps_achieved']}, submission_ready=readiness['submission_readiness']['submission_ready'],
        submission_blockers=readiness['submission_readiness']['blockers'], moderation_status=readiness['moderation_status']['status'],
        owner_checks=readiness['submission_readiness']['owner_checks'], performance_qualification=QUALIFICATION,
        evidence='External workspace: ' + rel(args.readiness)))
    external = [args.candidate, args.functional / 'release-checks.json', args.functional / 'manifest.json', args.media / 'media-review.json',
                args.readiness, ROOT / 'artifacts/TASK-282/comparison.json', ROOT / 'artifacts/TASK-282/cost-ranking.json',
                ROOT / 'artifacts/TASK-282/identity.json', ROOT / 'artifacts/TASK-284/decision.json', ROOT / 'artifacts/TASK-284/acceptance.json']
    manifest = dict(created_utc=now(), task='TASK-285', source_revision=candidate['source_revision'], assembly_source_revision=git('rev-parse', 'HEAD'),
                    build_tag=candidate['build_tag'], zip=dict(file='grapnelninja-y8.zip', sha256=candidate['sha256'], bytes=candidate['byte_count']),
                    functional_package_prepared=readiness['functional_package_preparation']['functional_package_prepared'],
                    software_regression_status=reg['status'], native_60fps_acceptance=native['status'],
                    **{'60fps_achieved': readiness['60fps_achieved']}, submission_ready=readiness['submission_readiness']['submission_ready'],
                    moderation_status=readiness['moderation_status']['status'], moderation_approved=False, uploaded=False,
                    submission_blockers=readiness['submission_readiness']['blockers'],
                    external_evidence_scope='Workspace-only references; raw QA deliberately excluded from kit',
                    external_evidence_sha256={rel(p): sha(p) for p in external},
                    files={str(p.relative_to(release)): sha(p) for p in sorted(release.rglob('*')) if p.is_file()})
    write(release / 'manifest.json', manifest)
    deterministic_zip(kit, release)
    print(f'PASS release assembled: {rel(release)} ({len(manifest["files"]) + 1} files) kit {rel(kit)} sha256={sha(kit)} bytes={kit.stat().st_size}')
    benefits = {name: dict(verdict_vs_control=c['verdict_vs_control'], median_reduction_vs_control_ms=round(c['median_reduction_vs_control_ms'], 2),
                           median_reduction_vs_control_fraction=round(c['median_reduction_vs_control_fraction'], 4),
                           integrated_fps=round(c['integrated_fps'], 2), control_fps=round(c['control_fps'], 2))
                for name, c in reg['cells'].items()}
    costs = {name: dict(original_zip_fps=round(c['original_fps'], 2), integrated_fps=round(c['integrated_fps'], 2),
                        integrated_over_original_frame_time_ratio=round(c['integrated_over_original_frame_time_ratio'], 3))
             for name, c in reg['cells'].items()}
    ranking = read(ROOT / 'artifacts/TASK-282/cost-ranking.json')
    committed = git('log', '--format=%H %s', '--name-only', 'b72ff271..HEAD')
    forbidden = [l for l in committed.splitlines() if l.startswith(('artifacts/', 'screenshots/', 'output/'))]
    handoff = dict(
        task='TASK-285', generated_utc=now(), scope='Local inspection kit rebuilt from the current runtime; not submission-ready',
        zip=dict(path=str((release / 'grapnelninja-y8.zip').resolve()), bytes=candidate['byte_count'], sha256=candidate['sha256'],
                 build=candidate['build_tag'], source_revision=candidate['source_revision'], members=len(candidate['files'])),
        kit=dict(path=str(kit.resolve()), bytes=kit.stat().st_size, sha256=sha(kit), members=len(manifest['files']) + 1),
        release_dir=str(release.resolve()), previous_release_preserved=rel(previous) if previous.exists() else None,
        measured_benefits=dict(source='artifacts/TASK-282/comparison.json (integrated runtime vs frozen TASK-271 control, equal backing, pinned density)',
                               cells=benefits, identity_exact_vs_control=ranking.get('integrated_identity_exact')),
        residual_costs=dict(source='artifacts/TASK-282/cost-ranking.json', cells=costs,
                            ranked_remaining_ms_bad=[dict(rank=r['rank'], subsystem=r['subsystem'], remaining_ms_estimate=r['remaining_ms_estimate'])
                                                     for r in ranking['modes']['bad']['ranking']],
                            statement='integrated frame time is about 2x the original ZIP on the headless software renderer; '
                                      'the almost-empty scene reaches 60 FPS on the same host'),
        native_60fps=dict(status=native['status'], counts=native['counts'], source='artifacts/TASK-284/decision.json'),
        **{'60fps_achieved': readiness['60fps_achieved']}, submission_ready=readiness['submission_readiness']['submission_ready'],
        owner_only_checks={k: 'NOT PERFORMED' for k in OWNER_CHECKS},
        no_upload=dict(uploaded=False, public_gameplay=False, production_ads=False, moderation_submitted=False,
                       statement='owner controls console upload and moderation; this ticket performed none of them'),
        commits=dict(forbidden_paths_committed_since_b72ff271=forbidden, statement='no artifacts/, screenshots/ or output/ files are committed'),
        qualification=QUALIFICATION)
    write(out / 'handoff.json', handoff)
    require(not forbidden, 'forbidden committed paths: ' + ', '.join(forbidden))
    print(f"PASS handoff written: {rel(out / 'handoff.json')}; 60fps_achieved={handoff['60fps_achieved']} submission_ready={handoff['submission_ready']}")
    return 0


# -------------------------------------------------------- package-check ----

def cmd_package_check(args):
    candidate = read(args.candidate)
    release, kit = args.release, args.kit
    manifest = read(release / 'manifest.json')
    game = zip_inventory(release / 'grapnelninja-y8.zip', 'y8-release/grapnelninja-y8.zip')
    expected = {f['path']: f['sha256'] for f in candidate['files']}
    require(game == expected, 'game ZIP members differ from the built candidate inventory')
    require(sha(release / 'grapnelninja-y8.zip') == candidate['sha256'] == manifest['zip']['sha256'], 'game ZIP identity differs')
    print(f"PASS inner game ZIP hash equals built and tested candidate {candidate['sha256']}")
    tested = read(args.functional / 'release/instrumentation.json')['candidate']
    require(tested['sha256'] == candidate['sha256'] and tested['runtime_sha256'] == expected, 'tested root hashes differ from ZIP members')
    for name, digest in expected.items():
        require(sha_bytes(git_blob('HEAD', name)) == digest, 'committed HEAD differs: ' + name)
        require(sha(Path(tested['root']) / name) == digest, 'served/tested root differs: ' + name)
        require(sha(ROOT / name) == digest, 'working tree differs: ' + name)
    print(f"PASS source/member hashes: 34 members == tested root {rel(tested['root'])} == HEAD {git('rev-parse', 'HEAD')} == working tree")
    members = zip_inventory(kit, 'y8-submission-kit.zip')
    files = {str(p.relative_to(release)): sha(p) for p in release.rglob('*') if p.is_file()}
    require(members == files, 'kit members differ from the release directory')
    require(members['grapnelninja-y8.zip'] == candidate['sha256'], 'kit inner ZIP differs')
    for p, h in manifest['files'].items():
        require(files[p] == h, 'release manifest hash differs: ' + p)
    require(set(files) == set(manifest['files']) | {'manifest.json'}, 'release directory holds unlisted files')
    allowed = {'grapnelninja-y8.zip', 'manifest.json', 'media-manifest.json', 'requirements.json', 'LISTING.txt',
               'OWNER-CHECKLIST.txt', 'REVIEWER-RESPONSE.txt', 'TEST-RESULTS.txt', 'UPLOAD.txt'}
    media = read(release / 'media-manifest.json')
    allowed.update(a['path'] for a in media['assets'])
    require(set(members) == allowed, 'unexpected kit member (QA payload, secret or output file)')
    require(len(media['assets']) == 9 and all(members[a['path']] == a['sha256'] for a in media['assets']), 'media digests differ')
    for p, h in manifest['external_evidence_sha256'].items():
        require(sha(ROOT / p) == h, 'external evidence changed: ' + p)
        print(f'REFERENCE {p} {h}')
    text = (release / 'TEST-RESULTS.txt').read_text()
    require(candidate['sha256'] in text and candidate['source_revision'] in text and candidate['build_tag'] in text, 'TEST-RESULTS identity')
    readiness_paths = [p for p in manifest['external_evidence_sha256'] if p.endswith('/readiness.json')]
    require(len(readiness_paths) == 1, 'manifest must reference exactly one hash-bound readiness.json')
    flags = check_manifest_flags(manifest, read(ROOT / readiness_paths[0]))
    print(f"PASS kit {rel(kit)}: {len(members)} members == release directory; media 9/9; external evidence {len(manifest['external_evidence_sha256'])} refs; "
          f"60fps_achieved={str(flags['60fps_achieved']).lower()} submission_ready={str(flags['submission_ready']).lower()} "
          f"uploaded={str(flags['uploaded']).lower()} (manifest == {readiness_paths[0]})")
    return 0


def check_manifest_flags(manifest, readiness):
    """Manifest readiness flags must equal the hash-bound readiness evaluation, never a hard-coded expectation; uploaded stays false."""
    expected = {'60fps_achieved': readiness['60fps_achieved'],
                'submission_ready': readiness['submission_readiness']['submission_ready']}
    actual = {k: manifest.get(k) for k in expected}
    require(actual == expected, 'manifest readiness flags differ from readiness.json: manifest=%s readiness=%s'
            % (json.dumps(actual, sort_keys=True), json.dumps(expected, sort_keys=True)))
    require(manifest.get('uploaded') is False, 'manifest uploaded flag must be false: %r' % (manifest.get('uploaded'),))
    return dict(expected, uploaded=False)


# ------------------------------------------------------------- manifest ----

def gpu_probe():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            try:
                cdp = b.new_browser_cdp_session()
                info = cdp.send('SystemInfo.getInfo')['gpu']
                aux = info.get('auxAttributes', {})
                return dict(browser=b.version, gl_renderer=aux.get('glRenderer'), gl_vendor=aux.get('glVendor'),
                            display_type=aux.get('displayType'), software_rendering=aux.get('softwareRendering'),
                            devices=[{k: d.get(k) for k in ('vendorId', 'deviceId', 'vendorString', 'deviceString')} for d in info.get('devices', [])])
            finally:
                b.close()
    except Exception as exc:  # the probe is informational; never fabricate it
        return dict(error=str(exc)[:300])


def cmd_manifest(args):
    out = args.out
    candidate = read(out / 'build/candidate.json')
    lines = [l for l in (out / 'commands.jsonl').read_text().splitlines() if l.strip()] if (out / 'commands.jsonl').exists() else []
    receipts = [json.loads(l) for l in lines]
    sub = {}
    for name in ('functional', 'media'):
        p = out / name / 'commands.json'
        if p.exists():
            sub[name] = read(p)
    all_cmds = receipts + [dict(c, group=g, utc_start=c['start_utc'], utc_end=c['end_utc']) for g, cs in sub.items() for c in cs]
    checks = read(out / 'functional/release-checks.json')
    instrumentation = {s: read(out / f'functional/{s}/instrumentation.json') for s in SUITES}
    browsers, profiles, transport = {}, [], dict(sdk_fixture_fulfilled=0, external_aborted=0, local_continued=0, non_local_continued=0, other=0)
    fixture = sha(ROOT / 'tools/fixtures/fake-y8-sdk.js')
    for s, inst in instrumentation.items():
        for c in inst['contexts']:
            browsers[c['engine']] = c['version']
            prof = c['profile']
            profiles.append(dict(suite=s, engine=c['engine'], viewport=prof.get('viewport'), dpr=prof.get('device_scale_factor'),
                                 has_touch=prof.get('has_touch'), is_mobile=prof.get('is_mobile')))
            for t in c['transport']:
                if t['action'] == 'fulfill' and t['url'] == build_zip.SDK_URL:
                    transport['sdk_fixture_fulfilled'] += 1
                    require(t.get('body_sha256') == fixture, 'SDK fixture body differs from tools/fixtures/fake-y8-sdk.js')
                elif t['action'] == 'abort':
                    transport['external_aborted'] += 1
                elif t['action'] == 'continue_' and t['url'].startswith('http://127.0.0.1:'):
                    transport['local_continued'] += 1
                elif t['action'] == 'continue_':
                    transport['non_local_continued'] += 1
                else:
                    transport['other'] += 1
    require(transport['non_local_continued'] == 0, 'non-local request continued')
    media = read(out / 'media/media-review.json')
    skip = {'manifest.json', 'manifest.log', 'evidence-audit.log', 'commands.jsonl'}
    evidence = {}
    for p in sorted(out.rglob('*')):
        if p.is_file() and p.name not in skip and '__pycache__' not in p.parts and 'previous-release' not in p.parts \
                and p.name != 'previous-submission-kit.zip':
            evidence[rel(p)] = dict(sha256=sha(p), bytes=p.stat().st_size)
    for name in ('previous-submission-kit.zip',):
        if (out / name).exists():
            evidence[rel(out / name)] = dict(sha256=sha(out / name), bytes=(out / name).stat().st_size)
    if (out / 'previous-release').exists():
        evidence[rel(out / 'previous-release')] = dict(directory=True, files={str(p.relative_to(out / 'previous-release')): sha(p)
                                                                             for p in sorted((out / 'previous-release').rglob('*')) if p.is_file()})
    if lines:
        evidence[rel(out / 'commands.jsonl')] = {'sha256_first_%d_lines' % len(lines): sha_bytes(('\n'.join(lines) + '\n').encode()),
                                                 'receipts_sealed': len(lines), 'note': 'later receipts (manifest, audit) append after this seal'}
    release = ROOT / 'artifacts/y8-release'
    kit = ROOT / 'artifacts/y8-submission-kit.zip'
    attempts = sorted(str(p.relative_to(ROOT)) for p in out.rglob('*attempt*') if p.is_file() or p.is_dir())
    readiness = read(out / 'readiness.json')
    manifest = dict(
        task='TASK-285', generated_utc=now(),
        purpose='rebuild and audit the current local Y8 package after the TASK-271..284 experiment series; package audit only, no performance verdict',
        utc_start=min(c['utc_start'] for c in all_cmds), utc_end=max(c['utc_end'] for c in all_cmds),
        commands=receipts, suite_commands=sub, exit_codes=sorted({c['exit_code'] for c in all_cmds}),
        failed_attempts_preserved=[c for c in all_cmds if c['exit_code'] != 0], attempt_paths_preserved=attempts,
        harness_failures_recorded=checks['resolved_harness_failures'],
        source_revision=git('rev-parse', 'HEAD'), source_status_porcelain=git('status', '--porcelain', '--untracked-files=no'),
        candidate=dict(sha256=candidate['sha256'], bytes=candidate['byte_count'], build_tag=candidate['build_tag'],
                       source_revision=candidate['source_revision'], archive=candidate['archive'], members={f['path']: f['sha256'] for f in candidate['files']}),
        release=dict(zip_sha256=sha(release / 'grapnelninja-y8.zip'), kit_sha256=sha(kit), kit_bytes=kit.stat().st_size,
                     files=read(release / 'manifest.json')['files']),
        executed_harness_hashes={**{n: sha(ROOT / n) for n in TESTED_TOOLS}, **{n: sha(ROOT / n) for n in MEDIA_TOOLS},
                                 'tools/build-y8-zip.py': sha(TOOLS / 'build-y8-zip.py'), 'tools/y8_package.py': sha(__file__),
                                 'artifacts/TASK-285/rec.py': sha(out / 'rec.py') if (out / 'rec.py').exists() else None,
                                 'tools/fixtures/fake-y8-sdk.js': fixture},
        environment=dict(os=platform.platform(), python=platform.python_version(), cpu_count=os.cpu_count(), git=git('--version'),
                         node=node_label(),
                         playwright=_playwright_version(), browsers=browsers, gpu=gpu_probe(),
                         renderer_note='headless software rendering on the build host; the functional suites certify offline behaviour of the exact ZIP, '
                                       'not any device or FPS'),
        fixed_profiles=dict(functional_contexts=profiles,
                            media_captures=[dict(file=f['file'], viewport=[1920, 1080], dpr=f['dpr'], canvas=f['canvas'], mode=f['mode'],
                                                 seed=f['seed'], tick=f['tick']) for f in media['source_frames']],
                            backing_note='the functional suites record viewport/DPR per context (adaptive density unpinned, shipped behaviour); '
                                         'the media captures record the exact canvas backing per frame'),
        seed_input_state=dict(functional='trusted Playwright mouse/touchscreen/keyboard and CDP touch; fixture SDK callbacks; synthetic visibility/blur; '
                                         'state assertions in the archived suite sources (functional/sources/)',
                              media='seed 4 (artifacts/TASK-084/seed-search.json best Main seed/actions), ticks 180/240/300, deaths none',
                              state_rule='every suite case asserts menu/pause/offer/physics state from page globals, see release-checks.json'),
        sdk_isolation=dict(**transport, statement='cdn.y8.com SDK requests are fulfilled with tools/fixtures/fake-y8-sdk.js (body hash asserted); every other '
                                                   'non-local request is aborted; no request left 127.0.0.1 (verify_y8_candidate asserts continue_ is local)'),
        media=dict(decision=media['decision'], pixel_identical_to_historical=media['pixel_identical_to_historical'], verdict=media['verdict'],
                   capture_revision=media['source_revision']),
        readiness_fields=dict(functional_package_prepared=readiness['functional_package_preparation']['functional_package_prepared'],
                              software_regression_status=readiness['software_regression_status']['status'],
                              native_60fps_acceptance=readiness['native_60fps_acceptance']['status'],
                              **{'60fps_achieved': readiness['60fps_achieved']}, submission_ready=readiness['submission_readiness']['submission_ready'],
                              moderation_status=readiness['moderation_status']['status']),
        evidence_paths_sha256=evidence,
        verdict_separation='A passing evidence audit means the build, functional suites, media captures and hashes are consistent and sealed. '
                           'It is NOT a performance verdict: the software-renderer regression against the original ZIP is outstanding, every '
                           'native 60-FPS row is UNVERIFIED, 60fps_achieved and submission_ready are false, and nothing was uploaded.')
    write(out / 'manifest.json', manifest)
    print(f"manifest: {len(receipts)} receipts sealed + {sum(len(v) for v in sub.values())} suite commands; exit_codes {manifest['exit_codes']}; "
          f"{len(evidence)} evidence entries; failed attempts {len(manifest['failed_attempts_preserved'])}; "
          f"browsers {browsers}; gpu {manifest['environment']['gpu'].get('gl_renderer') or manifest['environment']['gpu']}")
    return 0


# ----------------------------------------------------------------- main ----

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='command', required=True)
    task = ROOT / 'artifacts/TASK-307'
    p = sp.add_parser('build')
    p.add_argument('--out', type=Path, default=task / 'build')
    p.set_defaults(func=cmd_build)
    p = sp.add_parser('functional')
    p.add_argument('--candidate', type=Path, default=task / 'build/candidate.json')
    p.add_argument('--out', type=Path, default=task / 'functional')
    p.add_argument('--failure-note', action='append', help='LOG=cause, documents a preserved failed attempt')
    p.add_argument('--engines', help='comma list for the release suite (Y8_ENGINES), e.g. chromium,firefox when webkit is absent; '
                                     'every engine of %s left out needs an --engine-note' % ','.join(REQUIRED_ENGINES))
    p.add_argument('--engine-note', action='append', metavar='ENGINE=reason',
                   help='why ENGINE was not run; recorded verbatim in release-checks.json engines_not_run (repeatable)')
    p.add_argument('--webkit-note', help='alias for --engine-note webkit=REASON')
    p.set_defaults(func=cmd_functional)
    p = sp.add_parser('media')
    p.add_argument('--candidate', type=Path, default=task / 'build/candidate.json')
    p.add_argument('--out', type=Path, default=task / 'media')
    p.add_argument('--review', help='visual review note (PASS ... / FAIL ...) recorded after viewing contact-sheet.png')
    p.set_defaults(func=cmd_media)
    p = sp.add_parser('readiness')
    p.add_argument('--candidate', type=Path, default=task / 'build/candidate.json')
    p.add_argument('--functional', type=Path, default=task / 'functional')
    p.add_argument('--media', type=Path, default=task / 'media')
    p.add_argument('--out', type=Path, default=task / 'readiness.json')
    p.add_argument('--tasks', type=Path, default=ROOT / 'artifacts/tasks.json', help='task list audited for the SCOPE tickets')
    p.add_argument('--runner', type=Path, default=ROOT / 'artifacts/TASK-283/runner',
                   help='bench runner package (game/build.json) the owner measured; must be the one decision.json names')
    p.set_defaults(func=cmd_readiness)
    p = sp.add_parser('assemble')
    p.add_argument('--candidate', type=Path, default=task / 'build/candidate.json')
    p.add_argument('--functional', type=Path, default=task / 'functional')
    p.add_argument('--media', type=Path, default=task / 'media')
    p.add_argument('--readiness', type=Path, default=task / 'readiness.json')
    p.add_argument('--out', type=Path, default=task)
    p.add_argument('--release', type=Path, default=ROOT / 'artifacts/y8-release')
    p.add_argument('--kit', type=Path, default=ROOT / 'artifacts/y8-submission-kit.zip')
    p.set_defaults(func=cmd_assemble)
    p = sp.add_parser('package-check')
    p.add_argument('--candidate', type=Path, default=task / 'build/candidate.json')
    p.add_argument('--functional', type=Path, default=task / 'functional')
    p.add_argument('--release', type=Path, default=ROOT / 'artifacts/y8-release')
    p.add_argument('--kit', type=Path, default=ROOT / 'artifacts/y8-submission-kit.zip')
    p.set_defaults(func=cmd_package_check)
    p = sp.add_parser('manifest')
    p.add_argument('--out', type=Path, default=task)
    p.set_defaults(func=cmd_manifest)
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
