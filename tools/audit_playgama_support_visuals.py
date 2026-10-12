"""Read-only audit of TASK-325 source-bound visual evidence. No browser/timing runs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if ROOT.name == 'artifacts':
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / 'tools'))
from playgama_render_compare import audit as audit_capture, pixel_diff, hashes, PROTOCOL
from playgama_support_visuals import CHECKPOINTS
from PIL import Image, ImageChops


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def audit(ticket):
    manifest = json.loads((ticket/'manifest.json').read_text())
    for path, digest in manifest['sha256'].items():
        assert sha(ROOT/path) == digest, f'seal mismatch: {path}'
    print('PASS source/tool identities, consumed evidence and original logs SHA256')
    review = json.loads((ticket/'visuals/review.json').read_text())
    expected_review = []
    eligible = True
    for engine in ('firefox', 'chrome'):
        out = ticket / manifest['selected'][engine]
        audit_capture(out)
        assert sha(out/'tested-support-fixtures.py') == sha(ROOT/'tools/playgama_support_visuals.py')
        assert sha(out/'tested-harness.py') == sha(ROOT/'tools/playgama_render_compare.py')
        data = json.loads((out/'results.json').read_text())
        assert [r['checkpoint'] for r in data['comparisons']] == PROTOCOL['visual_checkpoints'] + CHECKPOINTS
        for arm in ('control', 'candidate'):
            assert data['sources'][arm] == hashes(ROOT/'artifacts/TASK-324'/arm)
        for r in data['comparisons']:
            key = engine+'/'+r['checkpoint']
            expected_review.append(key)
            entry = review[key]
            assert entry['inspected'] == [str((out/r[k]).relative_to(ticket)) for k in ('control','candidate')] + [str((out/(Path(r['control']).stem+'-diff.png')).relative_to(ticket))]
            assert entry['finding'] and entry['geometry'] and entry['effects']
            stats = pixel_diff(out/r['control'], out/r['candidate'])
            assert stats == r['pixels']
            diff = ImageChops.difference(Image.open(out/r['control']).convert('RGBA'),Image.open(out/r['candidate']).convert('RGBA'))
            assert diff.tobytes() == Image.open(out/(Path(r['control']).stem+'-diff.png')).convert('RGBA').tobytes()
            assert r['state_equal']
            if r['checkpoint'].startswith('support:'):
                st = json.loads((out/r['control_state']).read_text())
                fixture = st['support_fixture']
                if r['checkpoint'].endswith(':gameplay'):
                    assert not st['pause'] and not st['death']
                    startup = json.loads((out/r['control_state'].replace(':gameplay', ':startup')).read_text())
                    assert (st['x'],st['y']) != (startup['x'],startup['y'])
                if r['checkpoint'].endswith(':death'):
                    assert st['death'] and not st['pause']
                if r['checkpoint'].endswith(':restart-shake'):
                    assert st['shake'] and not st['death'] and not st['pause']
                if r['checkpoint'].endswith(':empty'):
                    assert fixture['motes'] == fixture['emitters'] == 0 and not fixture['has_lights']
                if r['checkpoint'].endswith(':edge-overlap'):
                    assert fixture['motes'] == 5 and fixture['emitters'] >= 3 and fixture['has_lights']
                if r['checkpoint'].endswith(':portrait-odd'):
                    assert st['portrait'] and fixture['viewport'] == [391,853] and st['backing'] == [1706,782]
                if r['checkpoint'].endswith(':landscape-odd'):
                    assert not st['portrait'] and st['backing'] == [1706,782]
            within = max(stats['max_per_channel']) <= 3
            eligible &= within and entry['visual_pass']
            print(f'PAIR {key} state_equal=True max_per_channel={stats["max_per_channel"]} changed_pixels={stats["changed_pixels"]} tolerance_pass={within} visual_pass={entry["visual_pass"]}')
    assert set(review) == set(expected_review), 'review inventory'
    decision = json.loads((ticket/'decision.json').read_text())
    assert decision['eligible'] == eligible
    assert decision['disposition'] == ('ELIGIBLE' if eligible else 'REJECT')
    if not eligible:
        reproduced = []
        for relative in decision['reproduced_in']:
            out = ticket/relative
            rows = json.loads((out/'results.json').read_text())['comparisons']
            r = next(r for r in rows if r['checkpoint'] == decision['failed_checkpoint'])
            reproduced.append(pixel_diff(out/r['control'], out/r['candidate']))
        assert len(reproduced) >= 2 and all(r == reproduced[0] for r in reproduced)
        assert max(reproduced[0]['max_per_channel']) > 3
        print('PASS reproducible REJECT: chrome support:classic:landscape-odd changed_pixels=11 max_per_channel=[7, 7, 0, 0]; original control/candidate/difference images retained')
    assert decision['adoption'] == ('BLOCKED_PENDING_LATER_GATES' if eligible else 'BLOCKED')
    size = sum(p.stat().st_size for p in (ROOT/'artifacts').rglob('*') if p.is_file() and not p.is_symlink())
    assert size < 20*1024**3
    print(f'PASS inventory={len(expected_review)} state equality, pixel statistics, difference images and image seals; artifacts_bytes={size}')
    print(f'PASS decision={decision["disposition"]} eligible={eligible}; visual captures are never timing evidence')


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('ticket',type=Path); args=p.parse_args()
    audit(args.ticket.resolve())
