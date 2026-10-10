"""Audit the isolated pattern experiment; integrity PASS is not release PASS."""
import argparse
import difflib
import json
from pathlib import Path
import subprocess

from profile_y8_glow_bounds import sha

ROOT = Path(__file__).resolve().parents[1]


def audit(out):
    manifest = json.loads((out / 'manifest.json').read_text())
    for name, digest in manifest['evidence_sha256'].items():
        assert sha(out / name) == digest, name
    for name, digest in json.loads((out / 'dependencies.json').read_text()).items():
        path = out / 'tool.py' if name == 'tools/profile_y8_glow_pattern.py' else ROOT / name
        assert sha(path) == digest, name
    assert sha(out / 'tool.py') == manifest['tool_sha256']
    control = (out / 'control/render/effects.js').read_text()
    candidate = (out / 'candidate/render/effects.js').read_text()
    assert (out / 'candidate.patch').read_text() == ''.join(difflib.unified_diff(
        control.splitlines(True), candidate.splitlines(True)))
    for path in (out / 'control').rglob('*'):
        if path.is_file():
            name = str(path.relative_to(out / 'control'))
            assert path.read_bytes() == subprocess.check_output(
                ['git', 'show', manifest['source_revision'] + ':' + name]), name
            if name != 'render/effects.js':
                assert path.read_bytes() == (out / 'candidate' / name).read_bytes(), name
    for path in out.glob('*-errors.json'):
        assert json.loads(path.read_text()) == [], path
    cases = ['menu'] + ['moving-' + str(t) for t in range(10, 181, 10)] + [
        'long-trail-edge-sparks-shake', 'resize', 'odd-backing', 'empty']
    rows = []
    for mode in ('bad', 'classic'):
        for seed in (1, 7, 49):
            control = out / f'{mode}-{seed}-control-rows.json'
            if not control.exists():
                continue
            a, b = [json.loads((out / f'{mode}-{seed}-{arm}-rows.json').read_text())
                    for arm in ('control', 'candidate')]
            assert [r['case'] for r in a] == cases == [r['case'] for r in b]
            for x, y in zip(a, b):
                assert x['canvas'] == y['canvas']
                rows.append(dict(mode=mode, seed=seed, case=x['case'], **{
                    k: x[k] == y[k] for k in ('state', 'sources', 'output')}))
    assert rows == manifest['validation'] and rows
    failed = [r for r in rows if not all(r[k] for k in ('state', 'sources', 'output'))]
    print(f'IDENTITY cases={len(rows)} failures={len(failed)}')
    for row in failed:
        print('MISMATCH', json.dumps(row, sort_keys=True))
    if failed:
        assert manifest['decision'] == 'REJECT_IDENTITY_MISMATCH'
        assert manifest['pairs'] == []
        assert not list(out.glob('*-r*-rows.json'))
        print('PASS timing prohibited after identity rejection; no shipping acceptance claimed')
    else:
        assert len(rows) == 138 and len(manifest['pairs']) == 6
        for pair in manifest['pairs']:
            for arm in ('control', 'candidate'):
                name = f"{pair['mode']}-r{pair['repetition']}-{arm}"
                r = json.loads((out / (name + '-rows.json')).read_text())
                frames = r['frames']
                assert r['readbacks'] == 0 and frames[0]['dt'] is None
                assert all(f['canvas'] == [1560, 780] for f in frames)
                assert all(abs(y['t'] - x['t'] - y['dt']) < 1e-6 and y['dt'] > 0
                           for x, y in zip(frames, frames[1:]))
                duration = frames[-1]['t'] - frames[0]['t']
                assert duration >= 30000 and abs(duration - r['activeMs']) < 1e-6
                assert pair[arm] == (len(frames) - 1) * 1000 / duration
            assert pair['benefit'] == (pair['candidate'] > pair['control'])
            print('PAIR', json.dumps(pair, sort_keys=True))
        expected = 'PURSUE' if all(p['benefit'] for p in manifest['pairs']) else 'REJECT_INCONSISTENT_BENEFIT'
        assert manifest['decision'] == expected
    assert manifest['package_ready'] is False
    print('DECISION', manifest['decision'])
    print('PASS evidence integrity:', len(manifest['evidence_sha256']), 'hashes; source and dependency identity')
    print('RELEASE_PENDING package_ready=false; six inherited regressions remain binding')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    audit(parser.parse_args().out.resolve())
