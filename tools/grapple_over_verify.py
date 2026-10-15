"""Deterministic test-only replay. Never loaded by the game.

A manifest contains metadata, ticks, inputs (tick/event/world), expected_exit
(player field bounds), required_events, and a recorded trace. Isolated encounters
may supply initial_setup (recorder spawn arguments) or initial_snapshot (a climb
save); base-start runs may supply neither. Audit always replays, not just hashes.
"""
import argparse
from contextlib import ExitStack
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from grapple_over_support import install_recorder, export_recording, state_hash
from perf_mobile import SEED_SCRIPT


def hashes():
    result = source_hashes()
    for name in ('grapple_over_verify.py', 'grapple_over_support.py',
                 'grapple_over_injector.js', 'test_grapple_over_tools.py'):
        path = 'tools/' + name
        result[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    return result


def metadata(kind='base-start'):
    return dict(schema=1, kind=kind, hz=60, seed=1, viewport=VIEWPORT,
                source_hashes=hashes(), level_sha256=hashes()['fixedlevel.js'])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(manifest):
    m = manifest['metadata']
    require(m['schema'] == 1 and m['hz'] == 60 and m['seed'] == 1
            and m['viewport'] == VIEWPORT, 'metadata mismatch')
    require(m['source_hashes'] == hashes(), 'runtime hash mismatch')
    require(m['level_sha256'] == hashes()['fixedlevel.js'], 'level hash mismatch')
    require(m['kind'] in ('base-start', 'isolated'), 'unknown proof kind')
    require(not (manifest.get('initial_setup') and manifest.get('initial_snapshot')),
            'choose one initial state')
    require(m['kind'] == 'isolated' or not any(k in manifest for k in
            ('initial_setup', 'initial_snapshot')), 'base-start state injection')
    require(not set(manifest) - {'metadata', 'ticks', 'inputs', 'expected_exit',
            'required_events', 'trace', 'initial_setup', 'initial_snapshot'}, 'unknown/debug mutation field')
    ticks = manifest['ticks']
    require(type(ticks) is int and 0 < ticks <= 36000, 'invalid tick count')
    previous = -1
    for event in manifest['inputs']:
        require(set(event) == {'tick', 'event', 'world'}, 'input state injection')
        require(type(event['tick']) is int and previous <= event['tick'] < ticks,
                'input tick continuity')
        previous = event['tick']
        require(event['event'] in ('mousedown', 'mouseup', 'touchstart', 'touchend'), 'unknown input')
        require(set(event['world']) == {'x', 'y'} and all(type(v) in (int, float)
                and math.isfinite(v) for v in event['world'].values()), 'invalid aim')
    require(bool(manifest['expected_exit']), 'expected exit required')
    require(isinstance(manifest['required_events'], list), 'required events missing')


def variations(inputs, tick_offset=0, aim_offset=(0, 0), max_ticks=3, max_aim=12):
    """Explicit bounded offsets, with no random sampling or silent tick clamping."""
    require(type(tick_offset) is int and abs(tick_offset) <= max_ticks
            and all(math.isfinite(v) and abs(v) <= max_aim for v in aim_offset),
            'variation exceeds bounds')
    result = copy.deepcopy(inputs)
    for event in result:
        event['tick'] += tick_offset
        require(event['tick'] >= 0, 'variation precedes start')
        event['world']['x'] += aim_offset[0]
        event['world']['y'] += aim_offset[1]
    return result


def output_writer(out):
    evidence = EvidenceWriter('TASK-462')
    path = Path(out)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    require(path.is_relative_to(evidence.root), 'output must honor GRAPPLE_OVER_EVIDENCE_DIR')
    return evidence, path.relative_to(evidence.root).as_posix()


def execute(manifest, browser, url, out, clip=False):
    validate(manifest)
    evidence, prefix = output_writer(out)
    options = dict(viewport=VIEWPORT, device_scale_factor=1, has_touch=True)
    if clip:
        options['record_video_dir'] = str(evidence.path(prefix + '/video/.keep').parent)
        options['record_video_size'] = VIEWPORT
    context = browser.new_context(**options)
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(url)
        wait_for_boot(page)
        page.evaluate("cancelAnimationFrame(game); window.requestAnimationFrame=()=>0; startGame('grapple_over'); CLIMB_UI.restart()")
        page.wait_for_function('!unTouch')
        page.mouse.up()
        install_recorder(page)
        page.evaluate("GRAPPLE_OVER_TEST.begin('replay')")
        if 'initial_setup' in manifest:
            page.evaluate('s=>GRAPPLE_OVER_TEST.spawn(s)', manifest['initial_setup'])
        if 'initial_snapshot' in manifest:
            page.evaluate('s=>restoreClimbState(s)', manifest['initial_snapshot'])
        page.evaluate('''() => { const a=GRAPPLE_OVER_TEST.attempts[0];
            a.snapshots=[{tick:0,state:GRAPPLE_OVER_TEST.snapshot()}]; }''')
        cdp = context.new_cdp_session(page)
        for tick in range(manifest['ticks']):
            for event in (e for e in manifest['inputs'] if e['tick'] == tick):
                point = page.evaluate('p=>GRAPPLE_OVER_TEST.client(p)', event['world'])
                if event['event'].startswith('mouse'):
                    page.mouse.move(point['x'], point['y'])
                    (page.mouse.down if event['event'] == 'mousedown' else page.mouse.up)()
                else:
                    cdp.send('Input.dispatchTouchEvent', dict(
                        type='touchStart' if event['event'] == 'touchstart' else 'touchEnd',
                        touchPoints=[dict(x=point['x'], y=point['y'], id=1)]
                        if event['event'] == 'touchstart' else []))
            page.evaluate('GRAPPLE_OVER_TEST.step(1)')
            if clip:
                page.evaluate('draw()')
                page.wait_for_timeout(1000 / 60)
        page.evaluate("GRAPPLE_OVER_TEST.finish('passed')")
        trace = export_recording(page)[0]
        require(not errors, 'browser errors: ' + repr(errors))
        evidence.write(prefix + '/trace.json', trace)
        evidence.write(prefix + '/browser.json', dict(browser=browser.version, viewport=VIEWPORT,
            revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes()))
        video = page.video if clip else None
    finally:
        context.close()
    if video:
        video.save_as(str(evidence.path(prefix + '/clip.webm')))
        video.delete()
    return trace


def check_trace(manifest, trace):
    rows = trace['snapshots']
    require([r['tick'] for r in rows] == list(range(manifest['ticks'] + 1)), 'snapshot tick continuity')
    require(all(r['sha256'] == state_hash(r['state']) for r in rows), 'snapshot hash mismatch')
    events = trace['events']
    require([e['sequence'] for e in events] == list(range(len(events))), 'event sequence continuity')
    require([e['tick'] for e in events] == sorted(e['tick'] for e in events), 'event tick continuity')
    require(not trace['metadata']['setupOnlySpawns'] or manifest['metadata']['kind'] == 'isolated',
            'debug state mutation')
    inputs = [e for e in events if e['type'] == 'input']
    require(len(inputs) == len(manifest['inputs']), 'input count mismatch')
    for actual, expected in zip(inputs, manifest['inputs']):
        require(actual['tick'] == expected['tick'] and actual['event'] == expected['event']
                and actual['trusted'], 'input mismatch')
        # Chromium mouse coordinates are integer CSS pixels (2 world units here).
        require(all(abs(actual['world'][k] - expected['world'][k]) <= 2.000001 for k in ('x', 'y')),
                'aim mismatch')
    player = rows[-1]['state']['simulation']['player']
    for field, bounds in manifest['expected_exit'].items():
        require(field in player and len(bounds) == 2 and bounds[0] <= player[field] <= bounds[1],
                'expected exit mismatch: ' + field)
    require(set(manifest['required_events']) <= {e['type'] for e in events}, 'missing mechanic event')


def verify(manifest, browser, url, out, clip=False):
    validate(manifest)
    check_trace(manifest, manifest['trace'])
    replayed = execute(manifest, browser, url, out, clip)
    check_trace(manifest, replayed)
    require(manifest['trace'] == replayed, 'recorded/replayed trace mismatch (state mutation or inputs)')
    evidence, prefix = output_writer(out)
    result = dict(matching_traces=True, kind=manifest['metadata']['kind'],
                  ticks=manifest['ticks'], recorded_sha256=state_hash(manifest['trace']),
                  replayed_sha256=state_hash(replayed))
    evidence.write(prefix + '/audit.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command, flag in [('replay', '--input'), ('audit', '--manifest')]:
        p = sub.add_parser(command)
        p.add_argument(flag, required=True, dest='input')
        p.add_argument('--out', required=True)
        p.add_argument('--clip', action='store_true')
    args = parser.parse_args()
    try:
        manifest = json.loads(Path(args.input).read_text())
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            result = verify(manifest, browser, url, args.out, args.clip)
        print('PASS ' + args.command + ': ' + json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError) as error:
        print('FAIL ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
