"""Consolidate and independently assert spacing/advance/live capture evidence."""
import argparse
import hashlib
import json
from pathlib import Path

from verification_scenarios import frames

TEMPLATES = set(frames)
VIEWPORTS = {(772, 630), (1280, 720), (1920, 1080)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    out = parser.parse_args().directory
    spacing = json.loads((out / 'spacing.json').read_text())
    advance = json.loads((out / 'advance.json').read_text())
    assert {(r['width'], r['height']) for r in spacing} == VIEWPORTS
    assert {(r['width'], r['height']) for r in advance} == VIEWPORTS
    measurements = []
    for row in spacing:
        width, height = row['width'], row['height']
        assert {r['template'] for r in row['measurements']} == TEMPLATES
        for r in row['measurements']:
            assert r['passed']
            assert abs((r['newGroupLeft']-r['predecessorRight'])*r['scale']-.1*width) <= 1e-6
        traversal = next(r for r in advance if (r['width'], r['height']) == (width, height))
        gameplay = [r for r in traversal['creations'] if not r['initializing']]
        assert {r['template'] for r in gameplay} == TEMPLATES
        for r in traversal['creations']:
            assert r['passed'] and r['canvasWidth'] == width and r['canvasHeight'] == height
            assert abs(r['visibleRight'] - (-r['cameraX'] + width/r['scale'])) <= 1e-6
            if r['id'] > 0:
                assert abs((r['left']-r['predecessorRight'])*r['scale']-.1*width) <= 1e-6
            if not r['initializing']:
                assert r['left'] > r['visibleRight']
        measurements.append(dict(width=width, height=height, spacing=row['measurements'],
                                 advance=traversal['creations']))
        print(f'PASS {width}x{height}: all ten templates; {len(row["measurements"])} spacing measurements; '
              f'{len(gameplay)} offscreen gameplay spawns; pixel gaps within 1e-6')
    (out / 'measurements.json').write_text(json.dumps(measurements, indent=2) + '\n')
    live = json.loads((out / 'live/run.json').read_text())
    events = [e for e in live['spawns'] if not e['initializing']]
    assert live['passed'] and live['wallSeconds'] >= 30 and len(events) >= 3
    assert live['gameplayEventCount'] == len(events)
    assert live['restarts'] == len(live['runs'])-1
    for run in live['runs']:
        initial = [e for e in live['spawns'] if e['run'] == run['id'] and e['initializing']]
        assert initial and initial[0]['id'] == 0
    for e in live['spawns']:
        assert e['passed'] and e['gapPassed'] and e['offscreenPassed']
        assert abs(e['visibleRight'] - (-e['cameraX'] + e['canvasWidth']/e['scale'])) <= 1e-6
        if e['id'] > 0:
            gap = (e['left']-e['predecessorRight'])*e['scale']
            assert abs(gap-e['expectedPixelGap']) <= 1e-6
            assert abs(gap-.1*e['canvasWidth']) <= 1e-6
        if not e['initializing']:
            assert e['left'] > e['visibleRight']
    assert len(live['samples']) >= 11
    for sample in live['samples']:
        assert (out / 'live' / sample['screenshot']).stat().st_size > 0
    print(f'PASS live: {live["wallSeconds"]:.3f} seconds; {len(events)} gameplay events; '
          f'{live["restarts"]} classified restarts; {len(live["samples"])} time-labelled screenshots')
    for path in ['live/console-errors.log', 'live/page-errors.log', 'browser-errors.log']:
        assert (out / path).read_bytes() == b''
        print(f'PASS {path}: exists and empty (0 bytes)')
    assert (out / 'unit-tests.log').read_text().rstrip().endswith('OK')
    spawn = (out / 'spawn.log').read_text()
    for template in sorted(TEMPLATES) + ['classic']:
        assert 'PASS ' + template + ':' in spawn
    statuses = json.loads((out / 'exit-statuses.json').read_text())
    assert len(statuses) >= 5 and all(code == 0 for code in statuses.values())
    hashes = json.loads((out / 'source-hashes.json').read_text())
    for name, digest in hashes.items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
    for name, digest in live['sourceHashes'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
    print('PASS unit-tests.log ends with OK; spawn.log has ten frame and classic PASS assertions; command exits zero')
    print(f'PASS tested source hashes match checkout: {len(hashes)} sources/checkers; {len(live["sourceHashes"])} live sources')


if __name__ == '__main__':
    main()
