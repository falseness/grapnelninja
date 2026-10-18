"""Deterministic test-only replay. Never loaded by the game.

A manifest contains metadata, ticks, inputs (tick/event/world), expected_exit
(player field bounds), required_events, and a recorded trace. Isolated encounters
may supply initial_setup (recorder spawn arguments) or initial_snapshot (a climb
save); base-start runs may supply neither. Audit always replays, not just hashes.
"""
import argparse
from contextlib import ExitStack
import copy
import gzip
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from grapple_over_support import install_recorder, export_recording, state_hash
from perf_mobile import SEED_SCRIPT


# Grapple Over camera scale (gameoptions.js), which sets the world size of one CSS pixel.
CAMERA_SCALE = float(re.search(r"grapple_over: Object\.freeze\(\{cameraScale: ([0-9.]+)",
                               (ROOT / 'gameoptions.js').read_text()).group(1))


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
        # blind_targets='skip' (tolerance suites): a press whose target is off-screen is a blind
        # target a player cannot aim at, so it and its release are not dispatched; the run then
        # fails check_trace (input count mismatch) and replays identically.
        blind = None
        layout = {}
        for tick, next_tick in zip(boundaries, boundaries[1:]):
            for event in (e for e in manifest['inputs'] if e['tick'] == tick):
                if blind and event['event'].endswith(('up', 'end')):
                    blind = None
                    continue
                point = page.evaluate('p=>GRAPPLE_OVER_TEST.client(p)', event['world'])
                if manifest['metadata'].get('compact_contacts') and event['event'].endswith(('down', 'start')):
                    inside = 0 < point['x'] < viewport['width'] and 0 < point['y'] < viewport['height']
                    if not inside and manifest['metadata'].get('blind_targets') == 'skip':
                        blind = event
                        continue
                    require(inside, 'mandatory target outside viewport')
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
                if manifest['metadata'].get('layout_probe'):
                    # HUD obstruction proof: the drawn UI text/button boxes (CSS px) of this frame and the
                    # camera it was drawn with; display only, the trace is unchanged.
                    layout[tick] = page.evaluate('''() => {LAYOUT_PROBE.boxes=[]; draw();
                        const b=LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes=null; return {camera:{x:screen.x,y:screen.y},boxes:b}}''')
                else:
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
        if layout:
            evidence.write(prefix + '/layout-probe.json', dict(frames={str(t): v for t, v in layout.items()},
                note='frame-NNNN is drawn after the inputs of tick NNNN and one physics step'))
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
        # Chromium mouse coordinates are integer CSS pixels: 1080/height logical
        # pixels, i.e. 1080/height/cameraScale world units (4 at 720 and 0.375).
        if expected['event'] != 'touchend':
            tolerance = 1.000001 * 1080 / manifest['metadata']['viewport']['height'] / CAMERA_SCALE
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


def load_evidence(evidence, name):
    """Suite inputs may be gzip-compressed (*.gz) to keep full recorded traces small."""
    path = evidence.path(name)
    return json.loads(gzip.decompress(path.read_bytes()) if name.endswith('.gz') else path.read_text())


def compress_replay(evidence, prefix):
    """Keep the full replayed trace, gzip-compressed, once it has been compared."""
    path = evidence.path(prefix + '/trace.json')
    evidence.path(prefix + '/trace.json.gz').write_bytes(gzip.compress(path.read_bytes(), 6, mtime=0))
    path.unlink()


def check_s01_mechanics(encounter, trace, required=True):
    """Layout-v2 Foundations: blue hoist, lift + green deflector, in-flight jib, boom."""
    events=trace['events'];rows=trace['snapshots']
    grabs=[e for e in events if e['type']=='acquisition']
    ids=[e['after']['rope'][0]['id'] for e in grabs]
    bounces=[]
    for e in events:
        if e['type']=='bounce' and (not bounces or bounces[-1]['element']!=e['contact']['elementId']):
            bounces.append(dict(element=e['contact']['elementId'],tick=e['tick']))
    # Moving vertically on the tick before the catch, i.e. not launched from a rest.
    airborne=[g['after']['rope'][0]['id'] for g in grabs
              if abs(rows[g['tick']-1]['state']['simulation']['player']['speedY'])>.01]
    observations=dict(acquisitions=ids,acquisition_ticks=[e['tick'] for e in grabs],
        release_ticks=[e['tick'] for e in events if e['type']=='release'],bounces=bounces,
        airborne_acquisitions=airborne)
    if required:
        need={'S01-01':['S01-hoist'],'S01-02':['S01-lift'],'S01-03':['S01-crane-hook','S01-jib-hook'],
              'S01-04':['S01-boom-hook']}[encounter]
        require(ids[:len(need)]==need,'S01 acquisition sequence mismatch')
        if encounter=='S01-02':
            require('S01-deflector' in [b['element'] for b in bounces],'S01 deflector bounce missing')
        if encounter=='S01-03':
            require('S01-jib-hook' in airborne,'S01 in-flight jib acquisition missing')
    return observations


S01_V3_ENCOUNTERS = {'S01-01':('S01-hoist','S01-yard-pad'), 'S01-02':('S01-lift','S01-deflector'),
                     'S01-03':('S01-gantry-hook',None), 'S01-04':('S01-crown-hook','S01-exit-pad')}


def check_s01_v3_mechanics(encounter, trace, required=True):
    """Layout-v3 Foundations (TASK-547/548): every attempt runs from the base spawn through the
    whole S01 route. The encounter's own mechanic must happen in order (anchor acquired, released,
    then its green bounce; S01-03 swings left-to-right on the gantry hook), every S01 anchor is
    acquired in route order, and the run never touches the S01-floor fall bouncers."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    events=trace['events']; rows=trace['snapshots']
    releases=[(e['tick'],e['before']['rope'][0]['id'],e['before']['simulation']['player']) for e in events
              if e['type']=='release' and e['before']['rope']]
    observations['releases']=[dict(tick=t,element=el) for t,el,_ in releases]
    observations['floor_bounce']='S01-floor' in [b['element'] for b in observations['bounces']]
    anchor, bouncer = S01_V3_ENCOUNTERS[encounter]
    grab=next((t for el,t in zip(observations['acquisitions'],observations['acquisition_ticks']) if el==anchor),None)
    release=next(((t,p) for t,el,p in releases if el==anchor and grab is not None and t>=grab),None)
    after=[b for b in observations['bounces'] if release and b['tick']>=release[0]]
    observations['encounter']=dict(anchor=anchor,acquisition_tick=grab,release_tick=release and release[0],
        bouncer=bouncer,bounce_tick=next((b['tick'] for b in after if b['element']==bouncer),None),
        release_speedX=release and release[1]['speedX'],
        press_speedX=rows[grab-1]['state']['simulation']['player']['speedX'] if grab else None)
    if required:
        route=[a for a,_ in S01_V3_ENCOUNTERS.values()]
        require(observations['acquisitions'][:4]==route,'S01 v3 acquisition sequence mismatch')
        require(release is not None,'S01 v3 '+anchor+' release missing')
        if bouncer:
            require(observations['encounter']['bounce_tick'] is not None,'S01 v3 '+bouncer+' bounce missing')
        else:
            enc=observations['encounter']
            require(enc['press_speedX']<0<enc['release_speedX'],'S01 v3 gantry swing reversal missing')
        if encounter in ('S01-03','S01-04'):
            require(anchor in observations['airborne_acquisitions'],'S01 v3 in-flight acquisition missing')
        require(not observations['floor_bounce'],'S01 v3 route fell onto S01-floor')
    return observations


S02_V3_ENCOUNTERS = {'S02-01':('S02-hoist','S02-canopy'), 'S02-02':('S02-lift','S02-bulkhead'),
                     'S02-03':('S02-gallery-hook','S02-east-wall'), 'S02-04':('S02-crown-hook','S02-exit-ledge')}


def check_s02_v3_mechanics(encounter, trace, required=True):
    """Layout-v3 Switchback (TASK-550/551/552): every attempt runs the S02 route from the real
    S01 v3 exit settled pose up to the encounter's exit. The encounter's anchor is acquired and
    released and its green surface is bounced after the acquisition (S02-01 canopy, S02-02 bulkhead
    rebound to the right, S02-03 east-wall reversal to the left while on the gallery hook, S02-04
    exit-ledge landing); the S02 anchors up to the encounter are acquired in route order, S02-02..04
    in flight, and after the hoist release the run never bounces on an S01 element (no fall back
    to the S01 drag zones)."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    events=trace['events']
    releases=[(e['tick'],e['before']['rope'][0]['id']) for e in events if e['type']=='release' and e['before']['rope']]
    observations['releases']=[dict(tick=t,element=el) for t,el in releases]
    anchor, bouncer = S02_V3_ENCOUNTERS[encounter]
    grab=next((t for el,t in zip(observations['acquisitions'],observations['acquisition_ticks']) if el==anchor),None)
    release=next((t for t,el in releases if el==anchor and grab is not None and t>=grab),None)
    bounce=next((e for e in events if e['type']=='bounce' and grab is not None and e['tick']>=grab
                 and e['contact']['elementId']==bouncer),None)
    hoist=next((t for t,el in releases if el=='S02-hoist'),None)
    s01=[b for b in observations['bounces'] if b['element'].startswith('S01-') and hoist is not None and b['tick']>hoist]
    observations['s01_bounces_after_hoist_release']=s01
    observations['encounter']=dict(anchor=anchor,acquisition_tick=grab,release_tick=release,bouncer=bouncer,
        bounce_tick=bounce and bounce['tick'],
        bounce_speedX=bounce and [bounce['before']['simulation']['player']['speedX'],bounce['after']['simulation']['player']['speedX']])
    if required:
        route=[a for a,_ in S02_V3_ENCOUNTERS.values()]
        route=route[:route.index(anchor)+1]
        require(observations['acquisitions'][:len(route)]==route,'S02 v3 acquisition sequence mismatch')
        require(release is not None,'S02 v3 '+anchor+' release missing')
        require(bounce is not None,'S02 v3 '+bouncer+' bounce missing')
        vx=observations['encounter']['bounce_speedX']
        if encounter=='S02-02': require(vx[0]<0<vx[1],'S02 v3 bulkhead rebound reversal missing')
        if encounter=='S02-03': require(vx[0]>0>vx[1],'S02 v3 east-wall lateral reversal missing')
        if encounter!='S02-01':
            require(anchor in observations['airborne_acquisitions'],'S02 v3 in-flight acquisition missing')
        require(not s01,'S02 v3 route fell back onto an S01 bouncer')
    return observations


S03_V3_ENCOUNTERS = {'S03-01':('S03-hoist','S03-west-pier'), 'S03-02':('S03-lift','S03-east-pier'),
                     'S03-03':('S03-crest-hook',None), 'S03-04':('S03-exit-hook','S03-exit-ledge')}
# Compact contacts carry no element id: the blue shutter's right face over its travel, and the right map edge.
S03_V3_SHUTTER_FACE = dict(left=5745, right=5775, top=-6960, bottom=-6730)
S03_V3_MAP_EDGE_X = 6480
# Fall bouncers: reaching one after the hoist release means the S03 route was lost.
S03_V3_FALL_BOUNCERS = ('S03-lower-bridge',)


def check_s03_v3_mechanics(encounter, trace, required=True):
    """Layout-v3 Broken Viaduct (TASK-553/554/555): every attempt runs the S03 route from the real
    S02 v3 exit settled pose up to the encounter's exit. The encounter's anchor is acquired and
    released; S03-01 rebounds right off the green west pier and S03-02 left off the green east pier
    after the release, S03-02 catches the lift in flight, S03-03 is stopped by the blue shutter
    (contact on its right face) before the crest catch and its release flight stops on the right map
    edge, S03-04 lands on the green exit ledge after the release. The S03 anchors up to the encounter
    are acquired in route order, and after the hoist release the run never bounces on an S01/S02
    element or the S03 lower bridge (no fall)."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    events=trace['events']
    releases=[(e['tick'],e['before']['rope'][0]['id']) for e in events if e['type']=='release' and e['before']['rope']]
    observations['releases']=[dict(tick=t,element=el) for t,el in releases]
    anchor, bouncer = S03_V3_ENCOUNTERS[encounter]
    grab=next((t for el,t in zip(observations['acquisitions'],observations['acquisition_ticks']) if el==anchor),None)
    release=next((t for t,el in releases if el==anchor and grab is not None and t>=grab),None)
    bounce=next((e for e in events if e['type']=='bounce' and release is not None and e['tick']>=release
                 and e['contact']['elementId']==bouncer),None)
    contacts=[e for e in events if e['type']=='contact']
    face=S03_V3_SHUTTER_FACE
    shutter=next((e for e in contacts if e['contact']['nx']==1 and face['left']<=e['contact']['x']<=face['right']
                  and face['top']<=e['contact']['y']<=face['bottom'] and (grab is None or e['tick']<=grab)),None)
    edge=next((e['tick'] for e in contacts if release is not None and e['tick']>release
               and e['contact']['x']>=S03_V3_MAP_EDGE_X),None)
    hoist=next((t for t,el in releases if el=='S03-hoist'),None)
    fallen=[b for b in observations['bounces'] if hoist is not None and b['tick']>hoist
            and (b['element'].startswith(('S01-','S02-')) or b['element'] in S03_V3_FALL_BOUNCERS)]
    observations['fall_bounces_after_hoist_release']=fallen
    observations['encounter']=dict(anchor=anchor,acquisition_tick=grab,release_tick=release,bouncer=bouncer,
        bounce_tick=bounce and bounce['tick'],
        bounce_speedX=bounce and [bounce['before']['simulation']['player']['speedX'],bounce['after']['simulation']['player']['speedX']],
        shutter_contact=shutter and dict(tick=shutter['tick'],speedX=[shutter['before']['simulation']['player']['speedX'],
                                                                      shutter['after']['simulation']['player']['speedX']]),
        map_edge_contact_tick=edge)
    if required:
        route=[a for a,_ in S03_V3_ENCOUNTERS.values()]
        route=route[:route.index(anchor)+1]
        ids=[a for a in observations['acquisitions'] if a.startswith('S03-')]
        require(ids[:len(route)]==route,'S03 v3 acquisition sequence mismatch')
        require(release is not None,'S03 v3 '+anchor+' release missing')
        if bouncer:
            require(bounce is not None,'S03 v3 '+bouncer+' bounce missing')
            vx=observations['encounter']['bounce_speedX']
            if encounter=='S03-01': require(vx[0]<0<vx[1],'S03 v3 west-pier rebound reversal missing')
            if encounter=='S03-02': require(vx[0]>0>vx[1],'S03 v3 east-pier rebound reversal missing')
        if encounter=='S03-02':
            require(anchor in observations['airborne_acquisitions'],'S03 v3 in-flight lift acquisition missing')
        if encounter=='S03-03':
            stop=observations['encounter']['shutter_contact']
            require(stop is not None and stop['speedX'][0]<-1 and abs(stop['speedX'][1])<.05,'S03 v3 shutter stop missing')
            require(edge is not None,'S03 v3 map-edge stop missing')
        require(not fallen,'S03 v3 route fell onto a fall bouncer')
    return observations


S04_V3_ENCOUNTERS = {'S04-01':('S04-hoist','S04-reflector'), 'S04-02':('S04-lift','S04-deflector'),
                     'S04-03':('S04-crest-hook','S04-baffle'), 'S04-04':('S04-exit-hook','S04-exit-ledge')}
# Fall bouncers: reaching one after the hoist release means the S04 route was lost (the S04 catch
# basin, the legacy v1 S05 decks converted to green, and every S01-S03 element).
S04_V3_FALL_BOUNCERS = ('S04-catch-basin', 'S04-upper-step', 'S04-exit')


def check_s04_v3_mechanics(encounter, trace, required=True):
    """Layout-v3 Deflector Works (TASK-556/515/516): every attempt runs the S04 route from the real
    S03 v3 exit settled pose up to the encounter's exit. The encounter's anchor is acquired and
    released and its green surface is bounced after the release: S04-01 the flat reflector (vertical
    speed mirrored, sideways speed kept), S04-02 the angled deflector (leftward flight turned into a
    steeper climb) after an in-flight lift catch, S04-03 the vertical baffle (sideways speed reversed
    to the left) followed by a stop on the left map edge, S04-04 the exit ledge. The S04 anchors up to
    the encounter are acquired in route order, and after the hoist release the run never bounces on an
    S01-S03 element or an S04 fall bouncer (no fall)."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    events=trace['events']
    releases=[(e['tick'],e['before']['rope'][0]['id']) for e in events if e['type']=='release' and e['before']['rope']]
    observations['releases']=[dict(tick=t,element=el) for t,el in releases]
    anchor, bouncer = S04_V3_ENCOUNTERS[encounter]
    grab=next((t for el,t in zip(observations['acquisitions'],observations['acquisition_ticks']) if el==anchor),None)
    release=next((t for t,el in releases if el==anchor and grab is not None and t>=grab),None)
    bounce=next((e for e in events if e['type']=='bounce' and release is not None and e['tick']>=release
                 and e['contact']['elementId']==bouncer),None)
    # Compact contacts carry no element id: the left map edge is the contact at x 0.
    edge=next((e['tick'] for e in events if e['type']=='contact' and bounce is not None and e['tick']>bounce['tick']
               and e['contact']['x']==0),None)
    hoist=next((t for t,el in releases if el=='S04-hoist'),None)
    fallen=[b for b in observations['bounces'] if hoist is not None and b['tick']>hoist
            and (b['element'].startswith(('S01-','S02-','S03-')) or b['element'] in S04_V3_FALL_BOUNCERS)]
    observations['fall_bounces_after_hoist_release']=fallen
    speeds=lambda e: [{k:e[s]['simulation']['player'][k] for k in ('speedX','speedY')} for s in ('before','after')]
    observations['encounter']=dict(anchor=anchor,acquisition_tick=grab,release_tick=release,bouncer=bouncer,
        bounce_tick=bounce and bounce['tick'],bounce_speeds=bounce and speeds(bounce),map_edge_contact_tick=edge)
    if required:
        route=[a for a,_ in S04_V3_ENCOUNTERS.values()]
        route=route[:route.index(anchor)+1]
        ids=[a for a in observations['acquisitions'] if a.startswith('S04-')]
        require(ids[:len(route)]==route,'S04 v3 acquisition sequence mismatch')
        require(release is not None,'S04 v3 '+anchor+' release missing')
        require(bounce is not None,'S04 v3 '+bouncer+' bounce missing')
        b, a = observations['encounter']['bounce_speeds']
        if encounter=='S04-01':
            require(b['speedY']>0>a['speedY'] and abs(a['speedX']-b['speedX'])<1e-6,'S04 v3 flat reflector reflection missing')
        if encounter=='S04-02':
            require(anchor in observations['airborne_acquisitions'],'S04 v3 in-flight lift acquisition missing')
            require(b['speedX']<0 and a['speedX']<0 and abs(a['speedX'])<abs(b['speedX']) and a['speedY']<b['speedY'],
                    'S04 v3 deflector climb redirect missing')
        if encounter=='S04-03':
            require(b['speedX']>0>a['speedX'],'S04 v3 baffle reversal missing')
            require(edge is not None,'S04 v3 left map-edge stop missing')
        require(not fallen,'S04 v3 route fell onto a fall bouncer')
    return observations


S05_V3_ENCOUNTERS = {'S05-01':('S05-hoist','S05-deflector'), 'S05-02':('S05-lift','S05-baffle'),
                     'S05-03':('S05-pull-hook',None), 'S05-04':('S05-exit-hook','S05-exit-ledge')}
# Fall bouncers: reaching one after the hoist release means the S05 route was lost (the S05 catch
# deck, the S04 exit ledge and catch basin, every S01-S04 element and the v1 S05 pieces converted to green).
S05_V3_FALL_BOUNCERS = ('S05-catch-deck', 'S05-projecting-girder', 'S05-transfer-canopy', 'S05-recessed-ceiling', 'S05-exit')


def check_s05_v3_mechanics(encounter, trace, required=True):
    """Layout-v3 Cable Galleries (TASK-517/518/519): every attempt runs the S05 route from the real
    S04 v3 exit settled pose up to the encounter's exit. The encounter's anchor is acquired and
    released: S05-01 the blue hoist, whose release rise is turned into a drop by the green canopy
    (vertical speed reversed) onto the angled green deflector; S05-02 the blue lift caught in flight,
    released into the green baffle (sideways speed reversed to the left); S05-03 the green pull hook
    caught in flight while flying west and released flying east (swing reversal); S05-04 the green
    exit hook, released into the green exit canopy and onto the green exit ledge. The S05 anchors up
    to the encounter are acquired in route order, and after the hoist release the run never bounces
    on an S01-S04 element or an S05 fall bouncer (no fall)."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    events=trace['events']; rows=trace['snapshots']
    releases=[(e['tick'],e['before']['rope'][0]['id'],e['before']['simulation']['player']) for e in events
              if e['type']=='release' and e['before']['rope']]
    observations['releases']=[dict(tick=t,element=el) for t,el,_ in releases]
    anchor, bouncer = S05_V3_ENCOUNTERS[encounter]
    grab=next((t for el,t in zip(observations['acquisitions'],observations['acquisition_ticks']) if el==anchor),None)
    release=next(((t,p) for t,el,p in releases if el==anchor and grab is not None and t>=grab),None)
    after=lambda element: next((e for e in events if e['type']=='bounce' and release is not None and e['tick']>=release[0]
                                and e['contact']['elementId']==element),None)
    bounce=after(bouncer) if bouncer else None
    # The surface bounced between the release and the encounter bouncer (S05-01 canopy, S05-04 exit canopy).
    canopy={'S05-01':'S05-canopy','S05-04':'S05-exit-canopy'}.get(encounter)
    first=after(canopy) if canopy else None
    hoist=next((t for t,el,_ in releases if el=='S05-hoist'),None)
    fallen=[b for b in observations['bounces'] if hoist is not None and b['tick']>hoist
            and (b['element'].startswith(('S01-','S02-','S03-','S04-')) or b['element'] in S05_V3_FALL_BOUNCERS)]
    observations['fall_bounces_after_hoist_release']=fallen
    speeds=lambda e: [{k:e[s]['simulation']['player'][k] for k in ('speedX','speedY')} for s in ('before','after')]
    observations['encounter']=dict(anchor=anchor,acquisition_tick=grab,release_tick=release and release[0],bouncer=bouncer,
        bounce_tick=bounce and bounce['tick'],bounce_speeds=bounce and speeds(bounce),
        canopy=canopy,canopy_tick=first and first['tick'],canopy_speeds=first and speeds(first),
        press_speedX=rows[grab-1]['state']['simulation']['player']['speedX'] if grab else None,
        release_speedX=release and release[1]['speedX'])
    if required:
        route=[a for a,_ in S05_V3_ENCOUNTERS.values()]
        route=route[:route.index(anchor)+1]
        ids=[a for a in observations['acquisitions'] if a.startswith('S05-')]
        require(ids[:len(route)]==route,'S05 v3 acquisition sequence mismatch')
        require(release is not None,'S05 v3 '+anchor+' release missing')
        enc=observations['encounter']
        if bouncer:
            require(bounce is not None,'S05 v3 '+bouncer+' bounce missing')
        if canopy:
            require(first is not None and first['tick']<bounce['tick'],'S05 v3 '+canopy+' bounce missing')
            b, a = enc['canopy_speeds']
            require(b['speedY']<0<a['speedY'],'S05 v3 '+canopy+' rise-to-drop reversal missing')
        if encounter=='S05-02':
            require(anchor in observations['airborne_acquisitions'],'S05 v3 in-flight lift acquisition missing')
            b, a = enc['bounce_speeds']
            require(b['speedX']>0>a['speedX'],'S05 v3 baffle reversal missing')
        if encounter=='S05-03':
            require(anchor in observations['airborne_acquisitions'],'S05 v3 in-flight pull-hook acquisition missing')
            require(enc['press_speedX']<0<enc['release_speedX'],'S05 v3 pull-hook swing reversal missing')
        require(not fallen,'S05 v3 route fell onto a fall bouncer')
    return observations


S06_V3_ENCOUNTERS = {'S06-01':('S06-carriage','S06-skid'), 'S06-02':('S06-lift','S06-canopy'),
                     'S06-03':('S06-climb-hook','S06-swing-skid'), 'S06-04':('S06-exit-hook','S06-exit-ledge')}
# Fall bouncers: reaching one after the carriage release means the S06 route was lost (the S06 catch
# and drop ledges, every S01-S05 element and the v1 S06 pieces converted to green).
S06_V3_FALL_BOUNCERS = ('S06-catch-ledge', 'S06-drop-ledge', 'S06-phase-rest', 'S06-exit')


def check_s06_v3_mechanics(encounter, trace, required=True):
    """Layout-v3 Liftworks (TASK-520/521/522): every attempt runs the S06 route from the real S05 v3
    exit settled pose up to the encounter's exit. The encounter's anchor is acquired and released:
    S06-01 the blue carriage, whose release dive is turned into a rise by the bounce-only green skid
    (vertical speed reversed); S06-02 the blue lift caught in flight, released into the green canopy
    (rise turned into a drop); S06-03 the green climb hook caught while sliding down the left map
    edge, its swing grazing the green swing skid (descent turned) before a rising release; S06-04
    the green exit hook, released onto the green exit ledge. The S06 anchors up to the encounter are
    acquired in route order, and after the carriage release the run never bounces on an S01-S05
    element or an S06 fall bouncer (no fall)."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    events=trace['events']; rows=trace['snapshots']
    releases=[(e['tick'],e['before']['rope'][0]['id'],e['before']['simulation']['player']) for e in events
              if e['type']=='release' and e['before']['rope']]
    observations['releases']=[dict(tick=t,element=el) for t,el,_ in releases]
    anchor, bouncer = S06_V3_ENCOUNTERS[encounter]
    grab=next((t for el,t in zip(observations['acquisitions'],observations['acquisition_ticks']) if el==anchor),None)
    release=next(((t,p) for t,el,p in releases if el==anchor and grab is not None and t>=grab),None)
    # S06-03: the swing skid is grazed while still attached; every other bouncer follows the release.
    since=grab if encounter=='S06-03' else release and release[0]
    bounce=next((e for e in events if e['type']=='bounce' and since is not None and e['tick']>=since
                 and e['contact']['elementId']==bouncer),None)
    carriage=next((t for t,el,_ in releases if el=='S06-carriage'),None)
    fallen=[b for b in observations['bounces'] if carriage is not None and b['tick']>carriage
            and (b['element'].startswith(('S01-','S02-','S03-','S04-','S05-')) or b['element'] in S06_V3_FALL_BOUNCERS)]
    observations['fall_bounces_after_carriage_release']=fallen
    speeds=lambda e: [{k:e[s]['simulation']['player'][k] for k in ('speedX','speedY')} for s in ('before','after')]
    observations['encounter']=dict(anchor=anchor,acquisition_tick=grab,release_tick=release and release[0],bouncer=bouncer,
        bounce_tick=bounce and bounce['tick'],bounce_speeds=bounce and speeds(bounce),
        press_speedY=rows[grab-1]['state']['simulation']['player']['speedY'] if grab else None,
        release_speedY=release and release[1]['speedY'])
    if required:
        route=[a for a,_ in S06_V3_ENCOUNTERS.values()]
        route=route[:route.index(anchor)+1]
        ids=[a for a in observations['acquisitions'] if a.startswith('S06-')]
        require(ids[:len(route)]==route,'S06 v3 acquisition sequence mismatch')
        require(release is not None,'S06 v3 '+anchor+' release missing')
        require(bounce is not None,'S06 v3 '+bouncer+' bounce missing')
        enc=observations['encounter']
        b, a = enc['bounce_speeds']
        if encounter=='S06-01':
            require(b['speedY']>0>a['speedY'],'S06 v3 skid dive-to-rise reversal missing')
        if encounter=='S06-02':
            require(anchor in observations['airborne_acquisitions'],'S06 v3 in-flight lift acquisition missing')
            require(b['speedY']<0<a['speedY'],'S06 v3 canopy rise-to-drop reversal missing')
        if encounter=='S06-03':
            require(anchor in observations['airborne_acquisitions'],'S06 v3 in-flight climb-hook acquisition missing')
            require(bounce['tick']<release[0] and b['speedY']>0>a['speedY'],'S06 v3 swing-skid graze missing')
            require(enc['release_speedY']<0,'S06 v3 rising climb-hook release missing')
        require(not fallen,'S06 v3 route fell onto a fall bouncer')
    return observations


def check_s02_mechanics(encounter, trace, required=True):
    """Layout-v2 Switchback: blue shuttle, blue lift + green bulkhead, green crest hook, blue trolley."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    if required:
        need={'S02-01':'S02-shuttle','S02-02':'S02-lift','S02-03':'S02-crest-hook','S02-04':'S02-trolley'}[encounter]
        require(observations['acquisitions'][:1]==[need],'S02 acquisition sequence mismatch')
        if encounter=='S02-02':
            require('S02-bulkhead' in [b['element'] for b in observations['bounces']],'S02 bulkhead bounce missing')
        if encounter=='S02-03':
            require('S02-ledge' in observations['airborne_acquisitions'],'S02 in-flight ledge catch missing')
    return observations


def check_s03_mechanics(encounter, trace, required=True):
    """Layout-v2 Broken Viaduct: blue carriage, blue lift + green buffer, green crest hook + in-flight ledge, blue trolley."""
    observations=check_s01_mechanics('S01-01', trace, required=False)
    # The S03 ledge is caught at the apex (vy ~ 0), so airborne = moving at all on the tick before
    # the catch (a launch from a rest pad has vx = vy = 0).
    rows=trace['snapshots']
    observations['airborne_acquisitions']=[e['after']['rope'][0]['id'] for e in trace['events'] if e['type']=='acquisition'
        and abs(rows[e['tick']-1]['state']['simulation']['player']['speedX'])+abs(rows[e['tick']-1]['state']['simulation']['player']['speedY'])>.01]
    if required:
        need={'S03-01':'S03-carriage','S03-02':'S03-lift','S03-03':'S03-crest-hook','S03-04':'S03-trolley'}[encounter]
        require(observations['acquisitions'][:1]==[need],'S03 acquisition sequence mismatch')
        if encounter=='S03-02':
            require('S03-span-buffer' in [b['element'] for b in observations['bounces']],'S03 span buffer bounce missing')
        if encounter=='S03-03':
            require('S03-ledge' in observations['airborne_acquisitions'],'S03 in-flight ledge catch missing')
    return observations


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


def check_s07_mechanics(encounter, trace, required=True):
    events=trace['events'];rows=trace['snapshots']
    grabs=[e for e in events if e['type']=='acquisition']
    ids=[e['after']['rope'][0]['id'] for e in grabs]
    hits=[e for e in events if e['type']=='knockback']
    detached=bool(hits and not hits[0]['after']['rope'])
    caught=bool(hits and grabs and grabs[-1]['tick']>hits[0]['tick'] and
                ids[-1]=='S07-shortcut-jib' and
                all(r['state']['simulation']['grapple']['grappled'] for r in rows[195:]))
    landed=any(abs(r['state']['simulation']['player']['y']+10190.8)<.001 and
               abs(r['state']['simulation']['player']['speedY'])<.001 for r in rows)
    observations=dict(acquisitions=ids,knockback_ticks=[e['tick'] for e in hits],
        hazard_detach=detached,airborne_catch=caught,lower_balcony_landing=landed)
    if required:
        if encounter=='S07-01': require(not hits and 'S07-service-gantry' in ids,'S07 safe hazard passage missing')
        if encounter=='S07-02': require(detached and caught,'S07 knockback detach/catch missing')
        if encounter=='S07-03': require(ids==['S07-launch-head','S07-roof-boom','S07-upper-motor','S07-exit'],'S07 exposed crossing missing')
        if encounter=='S07-04': require(landed and 'S07-side-hoist' in ids and ids[-1]=='S07-exit','S07 recovery missing')
    return observations


def check_s08_mechanics(encounter, trace, required=True):
    """Braking, bounce transfer, moving overhang attachment and final landing."""
    events=trace['events'];rows=trace['snapshots']
    grabs=[e for e in events if e['type']=='acquisition']
    ids=[e['after']['rope'][0]['id'] for e in grabs]
    releases=[e['tick'] for e in events if e['type']=='release']
    bounces=[e for e in events if e['type']=='bounce']
    player=lambda t:rows[t]['state']['simulation']['player']
    brake=None
    if 'S08-brake-davit' in ids:
        a=grabs[ids.index('S08-brake-davit')]['tick']
        r=next((t for t in releases if t>a),None)
        if r is not None: brake=dict(acquisition_tick=a,release_tick=r,speedX_before=player(a)['speedX'],speedX_after=player(r)['speedX'])
    transfer=None
    if bounces and 'S08-mast-yard' in ids:
        a=grabs[ids.index('S08-mast-yard')]['tick'];b=bounces[0]['tick']
        transfer=dict(bounce_tick=b,bounce_element=bounces[0]['contact']['elementId'],acquisition_tick=a,
            airborne=b<a and all(not rows[t]['state']['simulation']['grapple']['grappled'] for t in range(b+1,a)))
    overhang=None
    if 'S08-overhang-carriage' in ids:
        a=grabs[ids.index('S08-overhang-carriage')]['tick'];r=next((t for t in releases if t>a),None)
        if r is not None:
            ys=[next(e['y'] for e in rows[t]['state']['simulation']['elements'] if e['id']=='S08-overhang-carriage') for t in range(a,r+1)]
            overhang=dict(acquisition_tick=a,release_tick=r,carriage_travel=max(ys)-min(ys),
                below_underside_at_grab=player(a)['y']>-12390,
                above_deck_past_lip_at_release=player(r)['y']<-12420 and player(r)['x']>3420)
    done=next((r['tick'] for r in rows if r['state']['simulation']['stats']['completed']),None)
    landing=None
    if done is not None:
        p=player(done);landing=dict(completion_tick=done,x=p['x'],y=p['y'],
            in_finish=3420<=p['x']<=3700 and -12772<=p['y']<=-12760)
    observations=dict(acquisitions=ids,release_ticks=releases,
        bounces=[e['contact']['elementId'] for e in bounces],braking=brake,bounce_transfer=transfer,
        moving_overhang=overhang,final_landing=landing)
    if required:
        require(bool(releases),'S08 release missing')
        if encounter=='S08-01':
            require(ids[:2]==['S08-launch-arm','S08-brake-davit'] and brake and
                    brake['speedX_before']<0 and abs(brake['speedX_after'])<.5*abs(brake['speedX_before']),'S08 braking missing')
        if encounter=='S08-02':
            require(transfer and transfer['bounce_element']=='S08-deflector-ramp' and transfer['airborne'],'S08 bounce transfer missing')
        if encounter=='S08-03':
            require(overhang and overhang['carriage_travel']>100 and overhang['below_underside_at_grab']
                    and overhang['above_deck_past_lip_at_release'],'S08 moving overhang missing')
        if encounter=='S08-04':
            require(landing and landing['in_finish'] and 'S08-summit-gantry' in ids,'S08 final landing missing')
    return observations


def audit_suite(manifest, browser, url, out):
    """Replay every reported attempt, including failures, without trusting summary flags."""
    evidence, _ = output_writer(out)
    require(manifest['source_hashes'] == hashes(), 'suite source hash mismatch')
    section = manifest.get('section', 'S01')
    require(section in ('S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08'), 'unsupported section')
    require(set(manifest['encounters']) == {f'{section}-{i:02d}' for i in range(1, 5)}, 'encounter coverage')
    v3 = section in ('S01', 'S02', 'S03', 'S04', 'S05', 'S06') and manifest.get('designVersion') == 3
    s01 = check_s01_v3_mechanics if v3 else check_s01_mechanics
    s02 = check_s02_v3_mechanics if v3 else check_s02_mechanics
    s03 = check_s03_v3_mechanics if v3 else check_s03_mechanics
    count = 0
    for encounter, attempts in manifest['encounters'].items():
        for device in ('desktop', 'touch'):
            group = [a for a in attempts if a['device'] == device]
            require({a['variant'] for a in group} == {'nominal','early','late','aim-left','aim-right'}, 'variant coverage')
            require(next(a for a in group if a['variant']=='nominal')['success'], 'nominal failed')
            require(sum(a['success'] for a in group if a['variant']!='nominal') >= 2, 'tolerance failed')
        for a in attempts:
            recorded = load_evidence(evidence, a['input'])
            replayed = execute(recorded, browser, url, str(Path(out)/a['name']))
            require(recorded['trace'] == replayed, 'suite replay mismatch: '+a['name'])
            if a['input'].endswith('.gz'):
                compress_replay(evidence, output_writer(str(Path(out)/a['name']))[1])
            try:
                check_trace(recorded, replayed)
                if section == 'S01' and 'mechanic_events' in a: s01(encounter, replayed)
                if section == 'S02' and 'mechanic_events' in a: s02(encounter, replayed)
                if section == 'S03' and 'mechanic_events' in a: s03(encounter, replayed)
                if section == 'S04' and v3: check_s04_v3_mechanics(encounter, replayed)
                if section == 'S05': (check_s05_v3_mechanics if v3 else check_s05_mechanics)(encounter, replayed)
                if section == 'S06': (check_s06_v3_mechanics if v3 else check_s06_mechanics)(encounter, replayed)
                if section == 'S07': check_s07_mechanics(encounter, replayed)
                if section == 'S08': check_s08_mechanics(encounter, replayed)
                success = True
            except ValueError:
                success = False
            require(success == a['success'], 'outcome mismatch')
            if section == 'S01' and 'mechanic_events' in a:
                require(s01(encounter, replayed, success) == a['mechanic_events'], 'S01 mechanics mismatch')
            if section == 'S02' and 'mechanic_events' in a:
                require(s02(encounter, replayed, success) == a['mechanic_events'], 'S02 mechanics mismatch')
            if section == 'S03' and 'mechanic_events' in a:
                require(s03(encounter, replayed, success) == a['mechanic_events'], 'S03 mechanics mismatch')
            if section == 'S04':
                s04 = check_s04_v3_mechanics if v3 else check_s04_mechanics
                require(s04(encounter, replayed, success) == a['mechanic_events'], 'S04 mechanics mismatch')
            if section == 'S05':
                s05 = check_s05_v3_mechanics if v3 else check_s05_mechanics
                require(s05(encounter, replayed, success) == a['mechanic_events'], 'S05 mechanics mismatch')
            if section == 'S06':
                s06 = check_s06_v3_mechanics if v3 else check_s06_mechanics
                require(s06(encounter, replayed, success) == a['mechanic_events'], 'S06 mechanics mismatch')
            if section == 'S07':
                require(check_s07_mechanics(encounter, replayed, success) == a['mechanic_events'], 'S07 mechanics mismatch')
            if section == 'S08':
                require(check_s08_mechanics(encounter, replayed, success) == a['mechanic_events'], 'S08 mechanics mismatch')
            count += 1
    negative = json.loads(evidence.path(manifest['negative_control']).read_text())
    recorded = load_evidence(evidence, negative['input'])
    replayed = execute(recorded, browser, url, str(Path(out)/'negative'))
    require(recorded['trace'] == replayed, 'negative replay mismatch')
    if negative['input'].endswith('.gz'):
        compress_replay(evidence, output_writer(str(Path(out)/'negative'))[1])
    try:
        check_trace(recorded, replayed)
    except ValueError as error:
        require('expected exit mismatch' in str(error), 'negative failed for wrong reason')
    else:
        raise ValueError('negative unexpectedly succeeded')
    result = dict(matching_traces=True, attempts=count, negative_control_failed_exit=True)
    if v3:
        result['mechanics_check'] = f'check_{section.lower()}_v3_mechanics'
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
