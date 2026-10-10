"""Audit saved TASK-265 geometry evidence without running a browser.

Exit zero means internally consistent evidence, including an honest rejection.
It never means the release performance gate passed.
"""
import argparse
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
        assert sha(ROOT / name) == digest, name
    assert sha(ROOT / 'tools/profile_y8_live_geometry.py') == manifest['tool_sha256']
    assert sha(ROOT / 'tools/y8_live_geometry.js') == manifest['geometry_sha256']
    for path in (out / 'control').rglob('*'):
        if path.is_file():
            name = str(path.relative_to(out / 'control'))
            expected = subprocess.check_output(['git', 'show', manifest['source_revision'] + ':' + name])
            assert path.read_bytes() == expected, name
    for path in out.glob('*-errors.json'):
        assert json.loads(path.read_text()) == [], path
    cases = ['menu'] + ['moving-' + str(t) for t in range(10, 181, 10)] + [
        'long-trail-edge-sparks-shake', 'resize', 'odd-backing', 'empty']
    validation = []
    for mode in ('bad', 'classic'):
        for seed in (1, 7, 49):
            a, b = [json.loads((out / f'{mode}-{seed}-{arm}-rows.json').read_text())
                    for arm in ('control', 'candidate')]
            assert [r['case'] for r in a] == cases == [r['case'] for r in b]
            assert all(x['canvas'] == y['canvas'] for x, y in zip(a, b))
            assert a[-3]['canvas'] == [1562, 782]
            assert a[-2]['canvas'] == [1559, 779]
            for rows in (a, b):
                state = json.loads(rows[-4]['state'])
                shake = state['effects']['screenEffects']['shakeOffset']
                assert shake['x'] != 0 or shake['y'] != 0
                cameras = [(json.loads(r['state'])['screen']['x'], json.loads(r['state'])['screen']['y'])
                           for r in rows[1:19]]
                assert len(set(cameras)) > 1
                assert len(state['ninja']['track']['pos']) == 80
            for x, y in zip(a, b):
                row = dict(mode=mode, seed=seed, case=x['case'], **{
                    k: x[k] == y[k] for k in ('state', 'sources', 'output')})
                validation.append(row)
    assert validation == manifest['validation']
    failures = [r for r in validation if not all(r[k] for k in ('state', 'sources', 'output'))]
    print('IDENTITY cases=' + str(len(validation)) + ' failures=' + str(len(failures)))
    for row in failures:
        print('MISMATCH', json.dumps(row, sort_keys=True))
    if failures:
        assert manifest['decision'] == 'REJECT_IDENTITY_MISMATCH'
        assert manifest['pairs'] == []
    else:
        assert len(manifest['pairs']) == 6
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
                fps = (len(frames) - 1) * 1000 / r['activeMs']
                assert fps == pair[arm]
                print('PASS untraced 30-second whole-frame run', name, 'readbacks=0', 'FPS=' + str(fps))
            assert pair['benefit'] == (pair['candidate'] > pair['control'])
            print('PAIR', json.dumps(pair, sort_keys=True))
        decision = 'PURSUE' if all(r['benefit'] for r in manifest['pairs']) else 'REJECT_INCONSISTENT_BENEFIT'
        assert manifest['decision'] == decision
    assert manifest['package_ready'] is False
    print('DECISION', manifest['decision'])
    print('PASS evidence integrity:', len(manifest['evidence_sha256']), 'hashes; source and dependency identity')
    print('RELEASE_PENDING package_ready=false; six inherited regressions are not resolved by this audit')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    audit(parser.parse_args().out.resolve())
