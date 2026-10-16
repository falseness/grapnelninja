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
import os
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
                 'grapple_over_injector.js', 'test_grapple_over_tools.py',
                 'test_grapple_over_sections.py'):
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
            and m['viewport'] in (VIEWPORT, {'width':844, 'height':390}), 'metadata mismatch')
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


def execute(manifest, browser, url, out, clip=False, filmstrip=False):
    validate(manifest)
    evidence, prefix = output_writer(out)
    viewport = manifest['metadata']['viewport']
    options = dict(viewport=viewport, device_scale_factor=1, has_touch=any(e['event'].startswith('touch') for e in manifest['inputs']))
    if clip:
        options['record_video_dir'] = str(evidence.path(prefix + '/video/.keep').parent)
        options['record_video_size'] = viewport
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
        boundaries = {0, manifest['ticks']}
        boundaries.update(e['tick'] for e in manifest['inputs'])
        if clip:
            boundaries.update(range(manifest['ticks']))
        elif filmstrip:
            frames = set(range(0, manifest['ticks'], 60)) | {manifest['ticks']-1}
            frames.update(e['tick'] for e in manifest['inputs'])
            boundaries.update(frames)
            boundaries.update(t+1 for t in frames)
        boundaries = sorted(boundaries)
        for tick, next_tick in zip(boundaries, boundaries[1:]):
            for event in (e for e in manifest['inputs'] if e['tick'] == tick):
                point = page.evaluate('p=>GRAPPLE_OVER_TEST.client(p)', event['world'])
                if manifest['metadata'].get('compact_contacts') and event['event'].endswith(('down', 'start')):
                    require(0 < point['x'] < viewport['width'] and 0 < point['y'] < viewport['height'], 'mandatory target outside viewport')
                if event['event'].startswith('mouse'):
                    page.mouse.move(point['x'], point['y'])
                    (page.mouse.down if event['event'] == 'mousedown' else page.mouse.up)()
                else:
                    cdp.send('Input.dispatchTouchEvent', dict(
                        type='touchStart' if event['event'] == 'touchstart' else 'touchEnd',
                        touchPoints=[dict(x=point['x'], y=point['y'], id=1)]
                        if event['event'] == 'touchstart' else []))
            page.evaluate('n=>{GRAPPLE_OVER_TEST.step(n); TUTORIAL_HINT.advance(n*physicsStepMs)}', next_tick-tick)
            if filmstrip and (tick % 60 == 0 or tick == manifest['ticks']-1 or any(e['tick'] == tick for e in manifest['inputs'])):
                page.evaluate('draw()')
                page.screenshot(path=str(evidence.path(prefix + f'/frame-{tick:04d}.png')))
            if clip:
                page.evaluate('draw()')
                page.wait_for_timeout(1000 / 60)
        page.evaluate("GRAPPLE_OVER_TEST.finish('passed')")
        if manifest['metadata'].get('snapshot_contacts'):
            # S05 assertions use every physics snapshot plus rope events. Avoid
            # retaining thousands of duplicate contact before/after state pairs.
            page.evaluate('''() => {
                const a=GRAPPLE_OVER_TEST.attempts[0];
                a.events=a.events.filter(e=>e.type!=='contact');
                a.events.forEach((e,i)=>e.sequence=i);
                a.metadata.contactPolicy='contacts represented by every physics snapshot; rope/input events retained';
            }''')
        elif manifest['metadata'].get('compact_contacts'):
            page.evaluate('''() => {
                const a=GRAPPLE_OVER_TEST.attempts[0], seen=new Set();
                a.events=a.events.filter(e=>{
                    if(e.type!=='contact')return true;
                    const key=JSON.stringify(e.contact);
                    if(seen.has(key))return false;seen.add(key);return true;
                });
                a.events.forEach((e,i)=>e.sequence=i);
                a.metadata.contactPolicy='first occurrence per identical contact; all physics snapshots retained';
            }''')
        trace = export_recording(page)[0]
        require(not errors, 'browser errors: ' + repr(errors))
        evidence.write(prefix + '/trace.json', trace)
        evidence.write(prefix + '/browser.json', dict(browser=browser.version, viewport=viewport,
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
        if expected['event'] != 'touchend':
            tolerance = 2.000001 * 720 / manifest['metadata']['viewport']['height']
            require(all(abs(actual['world'][k] - expected['world'][k]) <= tolerance for k in ('x', 'y')),
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


def check_s04_mechanics(encounter, trace, required=True):
    """Measure reflection contacts and airborne reacquisition from recorded events."""
    bounces = [e for e in trace['events'] if e['type'] == 'bounce']
    contacts = [e['contact']['elementId'] for e in bounces]
    expected = {'S04-01':['S04-flat-press'], 'S04-02':['S04-angled-chute'],
                'S04-03':['S04-combination-press'],
                'S04-04':['S04-double-right','S04-double-left']}[encounter]
    result = dict(contacts=contacts, bounce_ticks=[e['tick'] for e in bounces])
    if required:
        require(contacts == expected, 'S04 reflection sequence mismatch')
        if encounter == 'S04-01':
            e=bounces[0];before=e['before']['simulation']['player'];after=e['after']['simulation']['player']
            require(before['speedX'] < 0 < after['speedX'], 'flat reflection missing')
        if encounter == 'S04-02':
            e=bounces[0];before=e['before']['simulation']['player'];after=e['after']['simulation']['player']
            require(before['speedY'] < 0 < after['speedY'] and before['speedX'] > 0 > after['speedX'], 'sloped reflection missing')
        if encounter == 'S04-03':
            grabs=[e for e in trace['events'] if e['type']=='acquisition'
                   and e['after']['rope'][0]['id']=='S04-combination-rest']
            require(bool(grabs) and grabs[0]['tick'] > bounces[0]['tick']
                    and grabs[0]['after']['simulation']['player']['y'] < -5540.8, 'airborne reacquisition missing')
            result['airborne_reacquisition_tick']=grabs[0]['tick']
        if encounter == 'S04-04':
            tail=[r['state']['simulation']['player'] for r in trace['snapshots'][-60:]]
            require(all(4880 <= p['x'] <= 5050 and -5821 <= p['y'] <= -5790
                        and abs(p['speedY']) < .001 for p in tail), 'landing not sustained')
            result['sustained_landing_ticks']=60
    return result


def check_s05_mechanics(encounter, trace, required=True):
    """Check inserted rope segments and motion around their active corner."""
    elements={'S05-01':'S05-projecting-girder','S05-02':'S05-deep-overhang',
              'S05-03':'S05-transfer-canopy','S05-04':'S05-recessed-ceiling'}
    events=trace['events'];observations=[]
    for wrap in events:
        if wrap['type']!='wrap' or wrap['after']['rope'][-1]['id']!=elements[encounter]:
            continue
        rope=wrap['after']['rope']
        release=next((e for e in events if e['type']=='release' and e['tick']>wrap['tick']),None)
        if release is None: continue
        before=wrap['after']['simulation']['player'];end=release['before']['simulation']['player']
        observations.append(dict(wrap_tick=wrap['tick'],release_tick=release['tick'],
            inserted_segment=len(rope)>=2 and rope[0]!=rope[-1],corner=rope[-1],
            corner_directed_pull=release['tick']>wrap['tick'] and end['x']>before['x'] and end['x']>rope[-1]['x']))
    acquisitions=[e for e in events if e['type']=='acquisition']
    new_acquisition=any(a['tick']<r['tick']<b['tick'] and a['after']['rope'][0]!=b['after']['rope'][0]
        for a,b in zip(acquisitions,acquisitions[1:]) for r in events if r['type']=='release')
    if required:
        require(any(o['inserted_segment'] and o['corner_directed_pull'] for o in observations), 'S05 corner pull missing')
        if encounter in ('S05-03','S05-04'):
            require(new_acquisition, 'S05 new acquisition missing')
    return dict(wraps=observations,new_acquisition=new_acquisition)


def check_s06_mechanics(encounter, trace, required=True):
    """Measure moving attachment, reversal, release phase and actual transfers."""
    events=trace['events']; rows=trace['snapshots']
    grabs=[e for e in events if e['type']=='acquisition']
    ids=[e['after']['rope'][0]['id'] for e in grabs]
    releases=[e for e in events if e['type']=='release']
    mover='S06-upper-weight' if encounter=='S06-04' else 'S06-counterweight'
    attached=[r for r in rows if r['state']['simulation']['grapple']['grappled'] and r['state']['rope'] and
              r['state']['rope'][0]['id']==mover]
    ys=[r['state']['rope'][0]['y'] for r in attached]
    travel=max(ys)-min(ys) if ys else 0
    differences=[b-a for a,b in zip(ys,ys[1:])]
    reversal=any(d>0 for d in differences) and any(d<0 for d in differences)
    rising_release=bool(differences and differences[-1]<0)
    transfer=ids==['S06-fixed-head','S06-upper-weight','S06-transfer-head','S06-exit']
    observations=dict(acquisitions=ids,moving_anchor_travel=travel,
        attached_through_reversal=reversal,rising_phase_release=rising_release,
        fixed_moving_fixed_transfer=transfer,release_ticks=[e['tick'] for e in releases])
    if required:
        require(mover in ids and travel>40, 'S06 moving anchor travel missing')
        if encounter in ('S06-02','S06-03'):
            require(reversal and travel>100, 'S06 attached reversal missing')
        if encounter=='S06-03': require(rising_release, 'S06 rising phase release missing')
        if encounter=='S06-04': require(transfer, 'S06 fixed moving fixed transfer missing')
    return observations


def audit_suite(manifest, browser, url, out):
    """Replay every reported attempt, including failures, without trusting summary flags."""
    evidence, _ = output_writer(out)
    require(manifest['source_hashes'] == hashes(), 'suite source hash mismatch')
    section = manifest.get('section', 'S01')
    require(section in ('S01', 'S02', 'S03', 'S04', 'S05', 'S06'), 'unsupported section')
    require(set(manifest['encounters']) == {f'{section}-{i:02d}' for i in range(1, 5)}, 'encounter coverage')
    count = 0
    for encounter, attempts in manifest['encounters'].items():
        for device in ('desktop', 'touch'):
            group = [a for a in attempts if a['device'] == device]
            require({a['variant'] for a in group} == {'nominal','early','late','aim-left','aim-right'}, 'variant coverage')
            require(next(a for a in group if a['variant']=='nominal')['success'], 'nominal failed')
            require(sum(a['success'] for a in group if a['variant']!='nominal') >= 2, 'tolerance failed')
        for a in attempts:
            recorded = json.loads(evidence.path(a['input']).read_text())
            replayed = execute(recorded, browser, url, str(Path(out)/a['name']))
            require(recorded['trace'] == replayed, 'suite replay mismatch: '+a['name'])
            try:
                check_trace(recorded, replayed)
                if section == 'S05': check_s05_mechanics(encounter, replayed)
                if section == 'S06': check_s06_mechanics(encounter, replayed)
                success = True
            except ValueError:
                success = False
            require(success == a['success'], 'outcome mismatch')
            if section == 'S04':
                require(check_s04_mechanics(encounter, replayed, success) == a['mechanic_events'], 'S04 mechanics mismatch')
            if section == 'S05':
                require(check_s05_mechanics(encounter, replayed, success) == a['mechanic_events'], 'S05 mechanics mismatch')
            if section == 'S06':
                require(check_s06_mechanics(encounter, replayed, success) == a['mechanic_events'], 'S06 mechanics mismatch')
            count += 1
    negative = json.loads(evidence.path(manifest['negative_control']).read_text())
    recorded = json.loads(evidence.path(negative['input']).read_text())
    replayed = execute(recorded, browser, url, str(Path(out)/'negative'))
    require(recorded['trace'] == replayed, 'negative replay mismatch')
    try:
        check_trace(recorded, replayed)
    except ValueError as error:
        require('expected exit mismatch' in str(error), 'negative failed for wrong reason')
    else:
        raise ValueError('negative unexpectedly succeeded')
    result = dict(matching_traces=True, attempts=count, negative_control_failed_exit=True)
    evidence.write(output_writer(out)[1]+'/audit.json', result)
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
        if 'encounters' in manifest:
            os.environ.setdefault('GRAPPLE_OVER_EVIDENCE_DIR', str(Path(args.input).resolve().parent))
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            result = audit_suite(manifest, browser, url, args.out) if 'encounters' in manifest else verify(manifest, browser, url, args.out, args.clip)
        print('PASS ' + args.command + ': ' + json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError) as error:
        print('FAIL ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
