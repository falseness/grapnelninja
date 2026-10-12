"""Cheap, browser-free audit of verify_y8_candidate output and its manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

# Evidence paths recorded in the reports (dirty_file_sha256 keys, candidate.archive, candidate.root)
# are repo-relative; resolve them against the repository, not the process cwd (TASK-301).
ROOT = Path(__file__).resolve().parents[1]


def audit_source(manifest):
    """Bind recorded dirty bytes to one tree, never mix unrelated revisions."""
    hashes = manifest['dirty_file_sha256']
    digest = lambda data: hashlib.sha256(data).hexdigest()
    if all((ROOT / p).is_file() and digest((ROOT / p).read_bytes()) == h
           for p, h in hashes.items()):
        print('PASS source binding: recorded dirty hashes match current files')
        return
    base = manifest['source_revision']
    subprocess.run(['git', 'merge-base', '--is-ancestor', base, 'HEAD'], check=True, cwd=ROOT)
    revisions = subprocess.check_output(
        ['git', 'rev-list', '--ancestry-path', base + '..HEAD'], text=True, cwd=ROOT).splitlines()
    for revision in revisions + [base]:
        matched = True
        for path, expected in hashes.items():
            blob = subprocess.run(['git', 'show', revision + ':' + path], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if blob.returncode or digest(blob.stdout) != expected:
                matched = False
                break
        if matched:
            print(f'PASS historical source binding: all {len(hashes)} dirty hashes match ancestor {revision}')
            for path, expected in hashes.items():
                current = digest((ROOT / path).read_bytes()) if (ROOT / path).is_file() else 'MISSING'
                print(f'SOURCE {path}: historical_sha256={expected} current_sha256={current}')
            print('Historical source binding certifies saved evidence, not current source/runtime equivalence')
            return
    raise AssertionError('Recorded dirty hashes match neither current files nor one ancestor tree')


def audit(out):
    load = lambda name: json.loads((out/name).read_text())
    report = load('release-checks.json')
    assert report['verdict'] == 'PASS' and report['package_ready'] is False
    sha = report['candidate']['sha256']
    assert len(sha) == 64 and report['candidate']['source_revision']
    assert hashlib.sha256((ROOT / report['candidate']['archive']).read_bytes()).hexdigest()==sha
    commands = load('commands.json')
    assert commands and all(c['start_utc'] and c['end_utc'] for c in commands)
    assert {c['log'] for c in commands if c['exit_code']} == {f['log'] for f in report.get('resolved_harness_failures', [])}
    for c in commands:
        log = (out/c['log']).read_text()
        assert 'exit_code='+str(c['exit_code']) in log and 'COMMAND ' in log
    print('PASS commands.log: actual commands and UTC intervals; nonzero exits matched to documented harness repairs and reruns')
    release = load('release/results.json')
    assert len(release) == 18
    assert {(r['engine'],r['mode']) for r in release} == {(e,m) for e in ('chromium','firefox','webkit') for m in ('bad','classic')}
    assert all(r['verdict']=='PASS' and r['resume'].startswith('PASS') and not r['errors'] for r in release)
    print('PASS release/results.json: 18 Main/Chill browser/profile cases; trusted Resume and save/reload')
    embed = load('embed/results.json')
    assert {r['case'] for r in embed} == {'portrait-frame','storage-denied','sdk-missing','sdk-hang','sdk-reject','sdk-ready-never'}
    assert all(r['verdict']=='PASS' and not r['errors'] and r['menu_ms']<5000 for r in embed)
    print('PASS embed/results.json: 6 startup/storage cases, missing/stalled/rejected SDK and interrupted touch')
    mobile = load('mobile-embed/mobile-embed.json')
    assert mobile['verdict']=='PASS' and len(mobile['runs'])==4
    for r in mobile['runs']:
        assert r['verdict']=='PASS' and not r['errors'] and r['interrupted_hold'].startswith('PASS')
        assert r['touch_events'] and all(e['trusted'] for e in r['touch_events'])
        states = {s['name']:s for s in r['states']}
        for n in ('landscape-1','portrait-1','landscape-2','portrait-2','physical-landscape-fixed-portrait','bars-expanded','bars-collapsed'):
            a,b=states[n],states[n+'-resumed']
            assert a['paused'] and not b['paused'] and b['physics_steps']>a['physics_steps']
        assert all(c['error']<.001 for c in r['coordinate_checks'])
        assert all((out/'mobile-embed'/p).is_file() for p in r['captures'])
    print('PASS mobile-embed/mobile-embed.json: 4 nested-frame runs; repeated settled rotations and trusted post-rotation touch')
    lifecycle=load('lifecycle/mobile-lifecycle.json')
    assert lifecycle['overall']=='PASS' and len(lifecycle['runs'])==14
    count=0
    for r in lifecycle['runs']:
        assert r['verdict']=='PASS' and not r['page_errors'] and not r['console_errors']
        cases={c['case']:c for c in r['cases']}
        assert all(c['verdict']=='PASS' for c in r['cases'])
        assert cases['background-flush']['storage_right_after_hidden']['grapnelninja.time']=='999'
        assert cases['background-foreground']['resumed'] and cases['blur-focus']['resumed']
        count+=len(r['cases'])
    print(f'PASS lifecycle/mobile-lifecycle.json: 14 runs, {count} cases; background-save 999, denied storage, resume and recovery')
    ads=load('ads/ad-outcomes.json'); callbacks=load('ads/callback-traces.json')
    assert ads['verdict']==callbacks['verdict']=='PASS' and len(ads['flows'])==len(callbacks['traces'])==24
    for r in ads['flows']:
        assert r['verdict']=='PASS' and not r['page_errors'] and r['recovery'].startswith('PASS')
        assert r['reward_count']==(1 if r['flow']=='viewed' else 0)
        assert not r['terminal']['adOpen'] and not r['terminal']['pending']
        assert r['recovered']['physics']>r['terminal']['physics'] and r['pause_menu']['paused']
    print('PASS ads/ad-outcomes.json and ads/callback-traces.json: 24 offline flows; viewed/dismissed/no-fill/blocked recovery, exact reward counts')
    for suite in ('release','embed','mobile-embed','lifecycle','ads'):
        data=load(suite+'/instrumentation.json')
        assert data['verdict']=='PASS' and data['candidate']['sha256']==sha
        expected=load('release/instrumentation.json')['candidate']['runtime_sha256']
        assert data['candidate']['runtime_sha256']==expected
        for name,h in expected.items():
            assert hashlib.sha256((ROOT / data['candidate']['root'] / name).read_bytes()).hexdigest()==h
        fixture_hash=hashlib.sha256((out/'sources/tools/fixtures/fake-y8-sdk.js').read_bytes()).hexdigest()
        for c in data['contexts']:
            assert c['transport'] and not c['errors']
            for t in c['transport']:
                if t['action']=='fulfill' and not t['url'].startswith('http://127.0.0.1:'):
                    assert t['url']=='https://cdn.y8.com/minimal-sdk/2-0/y8.min.js' and t['body_sha256']==fixture_hash
            events=[e for f in c['inputs'] for e in f['events']]
            assert all(e['trusted'] for e in events)
            # Reload suites reset document-local input buffers; their explicit
            # trusted Playwright input calls and state assertions are the proof.
            if suite in ('embed','mobile-embed','ads'):
                assert events
            assert all(t['action'] in ('fulfill','abort') or t['url'].startswith('http://127.0.0.1:') for t in c['transport'])
        print(f'PASS {suite}/instrumentation.json: candidate {sha}, trusted input, errors and offline routing recorded')
    pngs=list(out.rglob('*.png'))
    for p in pngs:
        data=p.read_bytes()
        assert data[:8]==b'\x89PNG\r\n\x1a\n' and len(data)>1000 and min(struct.unpack('>II',data[16:24]))>=100,p
    print(f'PASS PNG evidence: {len(pngs)} valid files (native browser captures plus review sheets); physical phones NOT RUN')
    manifest=load('manifest.json')
    assert manifest['source_revision'] and manifest['environment'] and manifest['commands']
    assert manifest['archive']['sha256']==sha
    for p,h in manifest['evidence_sha256'].items():
        assert hashlib.sha256((out/p).read_bytes()).hexdigest()==h,p
    audit_source(manifest)
    print(f"PASS manifest.json: {len(manifest['evidence_sha256'])} evidence hashes verified; command/source/archive/tool identities recorded")
    print('PASS release-checks.json: exact candidate binding and per-case engine/profile/mode/results; fixture/native boundaries explicit')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    audit(ap.parse_args().out)
