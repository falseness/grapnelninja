"""Real-input opening route proof; all retained output stays task-local."""
import hashlib
import json
import math
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from grapple_over_support import install_recorder, state_hash


class V1Task465:
    """Shared section-suite harness (setUp, page, aim, source hashes).

    TASK-532: the v1 S01-S04 suites Task465Tests..Task476Tests now run their layout-v3
    counterparts (see LEGACY_V3_MAPPING at the end of this module); TASK-533 did the same for the v1
    S05-S08 suites Task477Tests..Task488Tests (LEGACY_V3_UPPER_MAPPING), so the other v1 helper holders
    (V1Task467..V1Task476) had no users left and were removed.
    """
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter(getattr(cls, 'task_id', 'TASK-465'))
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_sections.py', 'tools/grapple_over_support.py',
                     'tools/grapple_over_injector.js', 'tools/grapple_over_verify.py'):
            hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = dict(browser=cls.browser.version, viewport=VIEWPORT, device_scale_factor=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            source_hashes=hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    def open(self, touch=False):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url); wait_for_boot(page)
        page.evaluate("startGame('grapple_over');menu.unPause();cancelAnimationFrame(game)")
        page.wait_for_function('!unTouch')
        install_recorder(page)
        return page

    def aim(self, page, x, y, down):
        p = page.evaluate('GRAPPLE_OVER_TEST.client', dict(x=x,y=y))
        self.assertTrue(0 <= p['x'] <= VIEWPORT['width'] and 0 <= p['y'] <= VIEWPORT['height'], p)
        page.mouse.move(p['x'],p['y'])
        if down: page.mouse.down()
        else: page.mouse.up()

    def test_03_source_hashes(self):
        for path,digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        print('PASS source hashes: runtime and harness match tested worktree')


# Pre-TASK-547 revision whose S01 is the layout-v2 Foundations (TASK-505..507).
V2_S01_REVISION = '28b65fd'
# What happened to every static v2 S01 solid in the layout-v3 rebuild (TASK-547).
V2_S01_DISPOSITION = {
    'S01-entry-pad':('converted-to-bounce','S01-01 launch: same 200x40 box, now green; S02 v2 fall lines still land on it'),
    'S01-yard-pad':('converted-to-bounce','S01-01 landing / S01-02 launch: moved to (3900,-880), 300x40 green yard bouncer'),
    'S01-loading-pad':('deleted','v2 S01-02 rest after the deflector; the v3 S01-02 ends in flight off the green deflector'),
    'S01-gantry-pad':('deleted','v2 S01-03/04 rest; the v3 S01-03/04 (TASK-548) swing from green hooks onto the green exit pad'),
    'S01-exit':('converted-to-bounce','Kept at (4060,-1620) as the v2 Switchback S02-01 start reference, now green; no S01 v3 route uses it')}
# Elements TASK-548 added to complete the v3 S01 (no v2 counterpart).
V3_S01_TASK548_ADDED = ('S01-gantry-hook','S01-crown-hook','S01-exit-pad','S01-floor','S01-exit-drag')
# TASK-531: the S01-03 overpull drag zone (left of the S02 canopy) that stops the early-gantry fling up the S02 shaft.
V3_S01_TASK531_ADDED = ('S01-overpull-drag',)
# TASK-491: the green recovery hook over the base left of the entry pad (no anchor reached that strip).
V3_S01_TASK491_ADDED = ('S01-west-hook',)


class FoundationsV3Checks:
    """Layout-v3 Foundations opening (S01-01/02) from the base spawn with real input.

    Shared by Task547Tests and by the re-specced Task505Tests (same cases, task-local evidence).
    """
    S01_01_V3 = [(10,'mousedown',2700,-790),(70,'mouseup',2700,-790)]
    S01_02_V3 = [(255,'mousedown',4500,-1730),(334,'mouseup',4500,-1730)]
    V3_MOVERS = ('S01-hoist','S01-lift')
    V3_BAND = (918, 972)
    # Exit boxes (also the manifest encounter exits): just off the yard bounce, rising;
    # and rebounding up-left off the green deflector.
    S01_01_EXIT = dict(x=[3990,4060], y=[-910,-880], speedX=[.5,2], speedY=[-1,-.01])
    S01_02_EXIT = dict(x=[4600,4800], y=[-2200,-1950], speedX=[-2,-.1], speedY=[-3,-.1])
    S01_01_TICKS, S01_02_TICKS = 255, 370

    def report(self):
        page = self.open()
        return page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN, level=validateMountainManifest(m);
            floors=[loadFixedLevel(level)];
            return {manifest:m, runtime:floors[0].level, report:layoutV2Report(m),
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))};}''')

    def v2_s01(self):
        """The layout-v2 S01 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V2_S01_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[0], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, report:layoutV2Report(m).sections[0],
                elements:m.geometry.elements.filter(e=>e.id.startsWith('S01-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S01-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S01-'))}}''', source)

    def test_01_geometry_and_rules(self):
        r = self.report(); v2 = self.v2_s01()
        m = r['manifest']; elements = m['geometry']['elements']
        s01 = m['sections'][0]
        # TASK-548 completed S01-03/04 and the exit; TASK-550 built the S02 entrance connector
        # (the v3 S02-01 hoist pull starts on the S01 exit pad).
        self.assertEqual((s01['designVersion'], s01['status']), (3, 'built'))
        self.assertEqual([e['status'] for e in m['encounters'][:4]], ['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][:5]], ['built']*5)
        self.assertNotIn('solidExceptions', s01)
        self.assertEqual(r['runtime']['elements'], elements)
        for actual, expected in zip(r['colliders'], elements):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S01-')]
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S01-')}
        self.assertEqual(set(movers), set(self.V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        enc = {e['id']:e for e in m['encounters'][:2]}
        self.assertEqual(enc['S01-01']['start'], {'x':2160,'y':0}); self.assertEqual(m['spawn'], {'x':2160,'y':0})
        for e in enc.values():
            self.assertTrue(any(x in movers for x in e['elements']), e['id'])
            self.assertTrue(any(roles[x] == 'green bounce' for x in e['elements']), e['id'])
        self.assertEqual(enc['S01-01']['exit'], dict(left=3990,right=4060,top=-910,bottom=-880))
        self.assertEqual(enc['S01-02']['exit'], dict(left=4600,right=4800,top=-2200,bottom=-1950))
        sec = r['report']['sections'][0]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S01', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][0], 'S01')
        self.assertFalse(r['report']['failed'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.V3_BAND))
        self.assertEqual([g['id'] for g in gaps], ['S01-01-hoist','S01-02-lift','S01-03-gantry','S01-04-crown'])
        for g in gaps:
            self.assertTrue(self.V3_BAND[0] <= g['distance'] <= self.V3_BAND[1], g)
        gaps = gaps[:2]
        # Since TASK-548 the fall points land on the green S01 floor bouncers (checked there).
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints'][:3]
        self.assertEqual([f['id'] for f in falls], ['S01-01-short','S01-02-short','S01-02-overshoot'])
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), (['S01-yard-drag'], 'S01-floor'), f)
        self.assertEqual(sec['rules']['strayDrag']['measured']['dragZones'][0]['fallPoints'][:3],
            ['S01-01-short','S01-02-short','S01-02-overshoot'])
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S01-01','S01-02'])
        # v2/v3 ratio against the v2 S01-01/02 gaps recorded by TASK-505 (and the v2 source).
        v2_geometry = json.loads((ROOT/'artifacts/TASK-505/geometry.json').read_text())
        v2_gaps = {g['id']:g for g in v2_geometry['manifest_section']['gaps']}
        self.assertEqual([v2_gaps[k] for k in ('S01-01-hoist','S01-02-lift')], v2['section']['gaps'][:2])
        dist = lambda g: ((g['to']['x']-g['from']['x'])**2+(g['to']['y']-g['from']['y'])**2) ** .5
        v2_d = {k:dist(v2_gaps[k]) for k in ('S01-01-hoist','S01-02-lift')}
        v3_d = {g['id']:g['distance'] for g in gaps}
        v2_mean, v3_mean = sum(v2_d.values())/2, sum(v3_d.values())/2
        ratio = v3_mean/v2_mean
        self.assertGreaterEqual(ratio, 2.0)
        per_gap = {k:v3_d[k]/v2_d[k] for k in v3_d}
        self.assertTrue(all(x >= 2.0 for x in per_gap.values()), per_gap)
        # Every static v2 S01 solid is deleted or converted to a green bouncer.
        self.assertEqual(sorted(v2['staticSolids']), sorted(V2_S01_DISPOSITION))
        self.assertEqual(sorted(v2['movers']), sorted(self.V3_MOVERS))
        by_id = {e['id']:e for e in own}
        mapping = []
        for old in v2['staticSolids']:
            kind, why = V2_S01_DISPOSITION[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertIsNone(now, old)
            else: self.assertEqual(now['role'], 'bounce', old)
            mapping.append(dict(id=old, v2_role='solid', disposition=kind, v3_role=now['role'] if now else None, reason=why))
        v2_ids = {e['id'] for e in v2['elements']}
        deleted_other = sorted(v2_ids - set(by_id) - set(V2_S01_DISPOSITION))
        self.assertEqual(deleted_other, ['S01-boom-hook','S01-crane-hook','S01-jib-hook'])
        self.assertEqual(sorted(set(by_id) - v2_ids), sorted(V3_S01_TASK548_ADDED + V3_S01_TASK531_ADDED + V3_S01_TASK491_ADDED))
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S01-01','S01-02'],
            gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=v3_d, v2_gap_distances=v2_d, v2_gap_source='artifacts/TASK-505/geometry.json manifest_section.gaps',
            v2_mean_gap=v2_mean, v3_mean_gap=v3_mean, v3_over_v2_mean_ratio=ratio, v3_over_v2_per_gap=per_gap,
            ratio_at_least_2=True, direction_note='S01-04 is built since TASK-548; the direction rule reads its exit-pad box'))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s01, encounters=m['encounters'][:4],
            elements=own, movers=list(movers.values()), roles=roles, gray_solids=gray, gray_solid_count=len(gray),
            runtime_matches_manifest=True, v2_revision=V2_S01_REVISION, v2_static_solids=v2['staticSolids'],
            v2_solid_disposition=mapping, v2_bounce_hooks_deleted=deleted_other, planned=[],
            task548_added=sorted(V3_S01_TASK548_ADDED)))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="1600 -2380 4400 2475" style="background:#111827">']
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            op = ' fill-opacity="0.45"' if e['role'] == 'drag' else ''
            parts.append(f'<polygon points="{pts}" fill="{colors[roles[e["id"]]]}"{op} stroke="white" stroke-width="3"/>'
                         f'<text x="{e["x"]}" y="{e["y"]-30}" fill="white" font-size="34">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+60}" x2="{e["x"]+60+dx}" y2="{e["y"]+60+dy}" stroke="#2f86ff" stroke-width="6" stroke-dasharray="14,8"/>')
        for g in s01['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="10,8"/>')
        for f in s01['fallPoints']:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="40" stroke="#fb923c" stroke-width="3" stroke-dasharray="4,10"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="14" fill="#fb923c"/><text x="{f["x"]+20}" y="{f["y"]}" fill="#fb923c" font-size="28">{f["id"]}</text>')
        for e in m['encounters'][:2]:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="5"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+40}" fill="#f472b6" font-size="28">{e["id"]} exit</text>')
        parts.append('<circle cx="2160" cy="0" r="18" fill="#ff7a1a"/>')
        for i, t in enumerate(['S01 Foundations v3 (designVersion 3) — zero gray solids; S01-01: green entry pad -> blue hoist -> green yard bounce',
                'S01-02: blue lift off the yard rebound -> green deflector rebound. Yellow dashes = gaps %s of 1080 (v3/v2 mean %.3f)'
                % ('/'.join(str(round(d)) for d in v3_d.values()), ratio),
                'Orange = declared fall points over the yellow drag zone; pink = exit boxes; S01-03/04 in TASK-548']):
            parts.append(f'<text x="1640" y="{-2320+i*48}" fill="#67e8f9" font-size="38">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=VIEWPORT); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S01 designVersion 3; gray solids', len(gray), '; roles', sorted(set(roles.values())),
              '; all 7 v3 rules pass; gaps', [round(d,1) for d in v3_d.values()], '; v3/v2 mean ratio', round(ratio,4),
              '; v2 solids', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def replay_v3(self, name, plan, ticks, bounds, density_until=None):
        from grapple_over_verify import metadata, execute, check_trace
        m = dict(metadata=metadata('base-start'),
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=True)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        # The in-memory full traces are identical; keep compact per-tick hashes plus the asserted fields.
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, Task506Tests.compact(self, t))
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce') or (e['type']=='contact' and element in self.V3_MOVERS):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    mover=element in self.V3_MOVERS, player=e['after']['simulation']['player'], rope=e['after']['rope']))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        # Longest stretch without an acquisition, bounce or mover contact (LAYOUT_V3_DENSITY_CAP_TICKS).
        # The settle at the section exit is not a stretch of the route: density_until ends it.
        horizon = density_until or ticks
        marks = sorted({0, horizon, *[x['tick'] for x in mechanics if x['type'] != 'release' and x['tick'] <= horizon]})
        stretch = max(b-a for a, b in zip(marks, marks[1:]))
        self.assertLessEqual(stretch, 254)
        result = dict(passed=True, matching_traces=True, trusted_inputs=True,
            proof_kind='base-start: production restart at base spawn (2160,0); no setup placement; real mouse input',
            placement=None, not_continuous_completion_claim=True,
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[{k:x[k] for k in ('tick','type','element','mover','player')} for x in mechanics],
            longest_stretch_without_mechanic_ticks=stretch, density_cap_ticks=254,
            final=players[-1], expected_exit=bounds, final_in_exit_box=True,
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        return trace, players, mechanics, result

    def reach_v3(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.V3_BAND[0] <= distance <= self.V3_BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y']), anchor=a['rope'][0], band=list(self.V3_BAND))

    def test_02_s01_01_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-01', self.S01_01_V3, self.S01_01_TICKS, self.S01_01_EXIT)
        kinds = [(e['type'],e['element']) for e in mech if e['element'] != 'S01-entry-pad']
        self.assertEqual(kinds, [('acquisition','S01-hoist'),('release','S01-hoist'),('bounce','S01-yard-pad')])
        self.assertLessEqual(mech[0]['tick'], 120)
        rope = [s['state']['rope'] for s in trace['snapshots'][15:70]]
        xs = [r[0]['x'] for r in rope if r and r[0]['id']=='S01-hoist']
        self.assertGreater(xs[-1]-xs[0], 1)
        bounce = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']=='S01-yard-pad')
        before, after = bounce['before']['simulation']['player'], bounce['after']['simulation']['player']
        self.assertGreater(before['speedY'], 0); self.assertLess(after['speedY'], 0)
        reach = self.reach_v3(players, mech, 10, 'S01-hoist')
        result.update(first_interaction_tick=mech[0]['tick'], mover_anchor_travel_while_attached=xs[-1]-xs[0],
            acquisition_reach=reach, yard_bounce=dict(tick=bounce['tick'], before=before, after=after))
        self.evidence.write('encounters/S01-01/result.json', result)
        print('PASS S01-01: base spawn; blue hoist acquisition', round(reach['distance'],1), 'at tick', reach['acquisition_tick'],
              '; green yard bounce at tick', bounce['tick'], '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s01_02_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-02', self.S01_01_V3+self.S01_02_V3, self.S01_02_TICKS, self.S01_02_EXIT)
        kinds = [(e['type'],e['element']) for e in mech if e['element'] != 'S01-entry-pad']
        self.assertEqual(kinds, [('acquisition','S01-hoist'),('release','S01-hoist'),('bounce','S01-yard-pad'),
            ('acquisition','S01-lift'),('release','S01-lift'),('bounce','S01-deflector')])
        start = players[self.S01_01_TICKS]
        for k, (lo, hi) in self.S01_01_EXIT.items():
            self.assertTrue(lo <= start[k] <= hi, (k, start))
        bounce = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']=='S01-deflector')
        before, after = bounce['before']['simulation']['player'], bounce['after']['simulation']['player']
        self.assertGreater(before['speedX'], 0); self.assertLess(after['speedX'], 0)
        rope = [s['state']['rope'] for s in trace['snapshots'][261:334]]
        ys = [r[0]['y'] for r in rope if r and r[0]['id']=='S01-lift']
        self.assertGreater(abs(ys[-1]-ys[0]), 1)
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S01-lift')
        self.assertGreater(lift['tick'], self.S01_01_TICKS)
        reach = self.reach_v3(players, mech, 255, 'S01-lift')
        result.update(segmented_from='S01-01 exit at tick 255 of the same base-start run (no placement)',
            s01_01_exit_at_tick_255=start, deflector_bounce=dict(tick=bounce['tick'], before=before, after=after),
            mover_anchor_travel_while_attached=ys[-1]-ys[0], acquisition_reach=reach)
        self.evidence.write('encounters/S01-02/result.json', result)
        print('PASS S01-02: from the S01-01 exit at tick 255; blue lift acquisition', round(reach['distance'],1),
              'at tick', lift['tick'], '; green deflector rebound at tick', bounce['tick'], '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')


class Task505Tests(FoundationsV3Checks, unittest.TestCase):
    """Foundations opening (S01-01/02), re-specced by TASK-547 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, all shared with Task547Tests via FoundationsV3Checks):
    test_01_geometry_and_rules: v2 rules/rest pads/459-486 gaps -> v3 rules, zero gray solids, 918-972 gaps.
    test_02_s01_01_nominal: hoist onto the yard rest pad -> hoist release onto the green yard bounce.
    test_03_s01_02_nominal: lift + deflector onto the loading pad -> lift off the yard rebound into the
    green deflector rebound. test_04_source_hashes is unchanged.
    """
    task_id = 'TASK-505'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_04_source_hashes = V1Task465.test_03_source_hashes
    # Layout-v2 route inputs, kept only for the v2 S01 suites (Task506/507) that layout v3 supersedes.
    S01_01 = [(10,'mousedown',2500,-318),(50,'mouseup',2500,-318)]
    S01_02 = [(190,'mousedown',3400,-530),(242,'mouseup',3400,-530)]
    MOVERS = ('S01-hoist','S01-lift')


class FoundationsV3CompleteChecks:
    """Layout-v3 Foundations S01-03/04, section exit and drag-zone fall recovery (TASK-548).

    Real trusted mouse input from the base spawn, no placement. Shared by Task548Tests and by
    the re-specced Task506Tests (same cases, task-local evidence).
    """
    V3_MOVERS, V3_BAND = FoundationsV3Checks.V3_MOVERS, FoundationsV3Checks.V3_BAND
    S01_01_V3, S01_02_V3 = FoundationsV3Checks.S01_01_V3, FoundationsV3Checks.S01_02_V3
    S01_01_EXIT, S01_02_EXIT = FoundationsV3Checks.S01_01_EXIT, FoundationsV3Checks.S01_02_EXIT
    S01_03_V3 = [(400,'mousedown',5250,-2990),(465,'mouseup',5250,-2990)]
    S01_04_V3 = [(530,'mousedown',5950,-3130),(615,'mouseup',5950,-3130)]
    ROUTE_V3 = S01_01_V3+S01_02_V3+S01_03_V3+S01_04_V3
    # S01-03 ends in flight off the gantry swing; S01-04 lands on the exit pad inside the exit
    # drag zone (LAND) and the full traversal settles there (SETTLE = the manifest exit box).
    S01_03_EXIT = dict(x=[4900,5000], y=[-3540,-3480], speedX=[.5,2], speedY=[-1.5,-.1])
    LAND = dict(x=[6040,6440], y=[-2760,-2700], speedX=[-.001,.001], speedY=[-.5,.5])
    SETTLE = dict(x=[6040,6440], y=[-2730,-2700], speedX=[-.001,.001], speedY=[-.05,.05])
    S01_03_TICKS, S01_04_TICKS, FULL_TICKS = 520, 1100, 1800
    # Naturally mistimed S01-01: the hoist is released after 45 ticks instead of 60. After the
    # player settles on the floor bouncers, a green yard-pad pull and a blue lift pull rejoin.
    FALL_V3 = [(10,'mousedown',2700,-790),(55,'mouseup',2700,-790),(700,'mousedown',3905,-865),(840,'mouseup',3905,-865),
               (845,'mousedown',4500,-1730),(905,'mouseup',4500,-1730)]
    FALL_TICKS, REJOIN_TICK = 928, 700
    YARD_DRAG = dict(left=2520, right=6480, top=-300, bottom=120)
    EXIT_DRAG = dict(left=5960, right=6480, top=-3100, bottom=-2660)
    report = FoundationsV3Checks.report
    replay_v3 = FoundationsV3Checks.replay_v3
    reach_v3 = FoundationsV3Checks.reach_v3

    @staticmethod
    def in_box(p, b):
        """Player circle overlaps a drag zone box (the runtime overlap test for rectangles)."""
        dx = max(b['left']-p['x'], 0, p['x']-b['right']); dy = max(b['top']-p['y'], 0, p['y']-b['bottom'])
        return dx*dx + dy*dy < p['radius']**2

    @staticmethod
    def inside(p, bounds):
        return all(lo <= p[k] <= hi for k, (lo, hi) in bounds.items())

    def kinds(self, mech, after=0):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S01-entry-pad' and e['tick'] >= after]

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']; s01 = m['sections'][0]
        self.assertEqual((s01['designVersion'], s01['status']), (3, 'built'))
        self.assertNotIn('solidExceptions', s01)
        self.assertEqual([e['status'] for e in m['encounters'][:4]], ['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][:4]], ['built']*4)
        self.assertEqual(m['recoveries'][0]['status'], 'built')
        self.assertEqual(r['runtime']['elements'], elements)
        for actual, expected in zip(r['colliders'], elements):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S01-')]
        by_id = {e['id']:e for e in own}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S01-')}
        self.assertEqual(set(movers), set(self.V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        box = lambda e: dict(left=e['x']+min(p['x'] for p in e['points']), right=e['x']+max(p['x'] for p in e['points']),
                             top=e['y']+min(p['y'] for p in e['points']), bottom=e['y']+max(p['y'] for p in e['points']))
        self.assertEqual(box(by_id['S01-yard-drag']), self.YARD_DRAG)
        self.assertEqual(box(by_id['S01-exit-drag']), self.EXIT_DRAG)
        enc = m['encounters'][:4]
        for a, b in zip(enc, enc[1:]):
            self.assertEqual(b['start']['from'], a['id'])
        for e in enc:
            self.assertTrue(any(roles.get(x) == 'green bounce' for x in e['elements']), e['id'])
        self.assertEqual([e['id'] for e in enc if any(x in movers for x in e['elements'])], ['S01-01','S01-02'])
        self.assertEqual(enc[2]['exit'], dict(left=4900,right=5000,top=-3540,bottom=-3480))
        # The S01 exit is the green exit pad inside the exit drag zone; the exit box sits on its top.
        pad, zone, exit_box = box(by_id['S01-exit-pad']), self.EXIT_DRAG, enc[3]['exit']
        self.assertEqual(roles['S01-exit-pad'], 'green bounce')
        self.assertTrue(zone['left'] <= pad['left'] and pad['right'] <= zone['right'] and zone['top'] < pad['top'] < zone['bottom'])
        self.assertEqual(exit_box, dict(left=6040,right=6440,top=-2730,bottom=-2700))
        self.assertEqual((exit_box['left'], exit_box['right'], exit_box['bottom']), (pad['left'], pad['right'], pad['top']))
        self.assertEqual([self.SETTLE[k] for k in ('x','y')], [[exit_box['left'],exit_box['right']],[exit_box['top'],exit_box['bottom']]])
        # Base floor bouncers: green, resting on the base catch floor (y 120), under the yard drag zone.
        floor = box(by_id['S01-floor'])
        self.assertEqual((roles['S01-floor'], floor['bottom']), ('green bounce', 120))
        self.assertEqual((floor['left'], floor['right']), (self.YARD_DRAG['left'], self.YARD_DRAG['right']))
        sec = r['report']['sections'][0]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S01', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('right', 'right'))
        self.assertEqual(sec['rules']['graySolid']['measured']['staticSolids'], [])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.V3_BAND))
        self.assertEqual([g['id'] for g in gaps], ['S01-01-hoist','S01-02-lift','S01-03-gantry','S01-04-crown'])
        for g in gaps:
            self.assertTrue(self.V3_BAND[0] <= g['distance'] <= self.V3_BAND[1], g)
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        # TASK-531 adds S01-03-overpull (the early-gantry fling, over S01-overpull-drag).
        self.assertEqual([f['id'] for f in falls], ['S01-01-short','S01-02-short','S01-02-overshoot','S01-03-early','S01-04-short','S01-03-overpull'])
        self.assertEqual(sorted({f['encounter'] for f in falls}), ['S01-01','S01-02','S01-03','S01-04'])
        under = {}
        for f in falls:
            self.assertEqual(f['firstBouncer'], 'S01-floor', f)
            self.assertIn('S01-yard-drag', f['dragZones'], f)
            for d in f['dragZones']:
                b = box(by_id[d])
                # Directly below: the zone spans the fall column and lies between the point and the floor.
                self.assertTrue(b['left'] < f['x']-18 and f['x']+18 < b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, d))
            under[f['id']] = dict(x=f['x'], y=f['y'], dragZones=f['dragZones'], firstBouncer=f['firstBouncer'])
        # Since TASK-550 the v3 S02 fall points also drop into these zones; only the S01 ones are pinned here.
        self.assertEqual([dict(id=d['id'], fallPoints=[p for p in d['fallPoints'] if p.startswith('S01-')])
                          for d in sec['rules']['strayDrag']['measured']['dragZones']],
            [dict(id='S01-yard-drag', fallPoints=[f['id'] for f in falls]), dict(id='S01-exit-drag', fallPoints=['S01-04-short']),
             dict(id='S01-overpull-drag', fallPoints=['S01-03-overpull'])])
        self.assertEqual(r['report']['v3'][0], 'S01')
        self.assertFalse(r['report']['failed'])
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=[e['id'] for e in enc], direction=direction,
            gray_solid_count=0, gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps}, fall_points_over_drag_zones=under,
            every_fall_point_has_drag_zone_below=True, drag_zones_only_under_fall_points=True))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s01, encounters=enc,
            connectors=m['connectors'][:5], recovery=m['recoveries'][0], elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True,
            direction=direction, exit=dict(pad='S01-exit-pad', pad_box=pad, drag_zone='S01-exit-drag', drag_box=zone, exit_box=exit_box),
            base_floor_bouncers=dict(id='S01-floor', box=floor, drag_zone='S01-yard-drag', drag_box=self.YARD_DRAG),
            fall_points=under, task548_added=sorted(V3_S01_TASK548_ADDED)))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="-280 -3830 7040 3960" style="background:#111827">',
                 '<rect x="0" y="120" width="6480" height="60" fill="#4b5563"/>']
        for e in sorted(own, key=lambda e: e['role'] != 'drag'):
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            op = ' fill-opacity="0.35"' if e['role'] == 'drag' else ''
            b = box(e)
            parts.append(f'<polygon points="{pts}" fill="{colors[roles[e["id"]]]}"{op} stroke="white" stroke-width="4"/>'
                         f'<text x="{b["left"]}" y="{b["top"]-20 if e["role"] != "drag" else b["top"]+60}" fill="white" font-size="46">{e["id"]}</text>')
        for g in s01['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="7" stroke-dasharray="18,12"/>')
        for f in s01['fallPoints']:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="80" stroke="#fb923c" stroke-width="5" stroke-dasharray="6,16"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="24" fill="#fb923c"/><text x="{f["x"]+30}" y="{f["y"]}" fill="#fb923c" font-size="40">{f["id"]}</text>')
        for e in enc:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="8"/>')
        parts.append('<circle cx="2160" cy="0" r="30" fill="#ff7a1a"/>')
        for i, t in enumerate(['S01 Foundations layout v3 complete (direction right, zero gray solids): hoist -> yard pad -> lift -> deflector',
                '-> green gantry hook -> green crown hook -> green exit pad inside the exit drag zone. Gaps (yellow) %s of 1080'
                % '/'.join(str(round(g['distance'])) for g in gaps),
                'Orange = declared fall points, each over a yellow drag zone and the green floor bouncers; pink = encounter exits']):
            parts.append(f'<text x="-240" y="{-3760+i*64}" fill="#67e8f9" font-size="54">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=VIEWPORT); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S01 built 4/4 designVersion 3; gray solids 0; direction right; all 7 v3 rules pass; gaps',
              [round(g['distance'],1) for g in gaps], '; fall points', list(under), 'each over', sorted({d for f in falls for d in f['dragZones']}),
              'onto S01-floor; exit pad inside S01-exit-drag; overview.png')

    def test_02_s01_03_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-03', self.S01_01_V3+self.S01_02_V3+self.S01_03_V3,
                                                      self.S01_03_TICKS, self.S01_03_EXIT)
        self.assertEqual(self.kinds(mech), [('acquisition','S01-hoist'),('release','S01-hoist'),('bounce','S01-yard-pad'),
            ('acquisition','S01-lift'),('release','S01-lift'),('bounce','S01-deflector'),
            ('acquisition','S01-gantry-hook'),('release','S01-gantry-hook')])
        start = players[FoundationsV3Checks.S01_02_TICKS]
        self.assertTrue(self.inside(start, self.S01_02_EXIT), start)
        press = players[400]
        self.assertLess(press['speedX'], 0)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S01-gantry-hook')
        self.assertGreater(release['player']['speedX'], 0)
        reach = self.reach_v3(players, mech, 400, 'S01-gantry-hook')
        result.update(encounter='S01-03', segmented_from='S01-02 exit at tick 370 of the same base-start run (no placement)',
            s01_02_exit_at_tick_370=start, player_at_press=press, gantry_release=release['player'],
            swing_reverses_left_to_right=True, acquisition_reach=reach)
        self.evidence.write('encounters/S01-03/result.json', result)
        print('PASS S01-03: from the S01-02 exit at tick 370; green gantry hook', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; vx', round(press['speedX'],2), '->', round(release['player']['speedX'],2), '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def landing(self, trace, players, mech):
        land = next(e for e in mech if e['type']=='bounce' and e['element']=='S01-exit-pad')
        nxt = next((e['tick'] for e in mech if e['type']=='bounce' and e['element']=='S01-exit-pad' and e['tick'] > land['tick']), len(players)-1)
        peak = min(p['y'] for p in players[land['tick']:nxt])
        for t in range(land['tick'], len(players)):
            self.assertTrue(self.in_box(players[t], self.EXIT_DRAG), (t, players[t]))
            self.assertLess(abs(players[t]['speedX']), .01)
        self.assertGreater(peak - players[0]['radius'], self.EXIT_DRAG['top'])
        before = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land['tick'])['before']['simulation']['player']
        return dict(tick=land['tick'], before=before, after=land['player'], first_rebound_peak_y=peak,
            first_rebound_inside_exit_drag=True, exit_drag=self.EXIT_DRAG)

    def test_03_s01_04_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-04', self.ROUTE_V3, self.S01_04_TICKS, self.LAND, density_until=650)
        kinds = self.kinds(mech, 520)
        self.assertEqual(kinds[:3], [('acquisition','S01-crown-hook'),('release','S01-crown-hook'),('bounce','S01-exit-pad')])
        self.assertEqual(set(kinds[2:]), {('bounce','S01-exit-pad')})
        start = players[self.S01_03_TICKS]
        self.assertTrue(self.inside(start, self.S01_03_EXIT), start)
        reach = self.reach_v3(players, mech, 530, 'S01-crown-hook')
        land = self.landing(trace, players, mech)
        self.assertLessEqual(land['tick'], 650)
        result.update(encounter='S01-04', segmented_from='S01-03 exit at tick 520 of the same base-start run (no placement)',
            s01_03_exit_at_tick_520=start, acquisition_reach=reach, exit_pad_landing=land)
        self.evidence.write('encounters/S01-04/result.json', result)
        print('PASS S01-04: from the S01-03 exit at tick 520; green crown hook', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; lands on the green exit pad at tick', land['tick'], 'inside S01-exit-drag; final',
              {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')}, '; identical replay; trusted input')

    def test_04_full_traversal(self):
        trace, players, mech, result = self.replay_v3('S01-full', self.ROUTE_V3, self.FULL_TICKS, self.SETTLE, density_until=650)
        self.assertEqual([(e['element'], e['tick']) for e in mech if e['type']=='acquisition' and e['element'] != 'S01-entry-pad'],
            [('S01-hoist',15),('S01-lift',260),('S01-gantry-hook',405),('S01-crown-hook',535)])
        exits = {}
        for name, tick, bounds in (('S01-01',255,self.S01_01_EXIT),('S01-02',370,self.S01_02_EXIT),('S01-03',520,self.S01_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        self.assertNotIn('S01-floor', {e['element'] for e in mech})
        land = self.landing(trace, players, mech)
        # Settled: from this tick to the end the player stays in the exit box with |vy| <= 0.05, vx = 0.
        settle = next(t for t in range(land['tick'], self.FULL_TICKS+1)
                      if all(self.inside(players[u], self.SETTLE) for u in range(t, self.FULL_TICKS+1)))
        self.assertLessEqual(settle, 1500)
        tail = players[settle:]
        exits['S01-04'] = dict(tick=settle, player=players[settle], box=self.SETTLE)
        result.update(encounter='S01 full traversal', encounter_exits=exits, exit_pad_landing=land,
            section_exit=dict(element='S01-exit-pad', drag_zone='S01-exit-drag', settle_tick=settle,
                settled_ticks=len(tail), settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[-1], settle_box=self.SETTLE, inside_exit_drag=True),
            section_exit_reached=True, settled_at_section_exit=True, floor_contact=False,
            reaches=[self.reach_v3(players, mech, t, el) for t, el in ((10,'S01-hoist'),(255,'S01-lift'),(400,'S01-gantry-hook'),(530,'S01-crown-hook'))])
        self.evidence.write('encounters/S01-full/result.json', result)
        print('PASS full S01: base spawn; exits', {k:v['tick'] for k,v in exits.items()}, '; exit pad landing tick', land['tick'],
              '; settled from tick', settle, 'for', len(tail), 'ticks at', {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')},
              'inside S01-exit-drag; no floor contact; identical replay; trusted input')

    def test_05_fall_through_drag_and_rejoin(self):
        # Density is a nominal-route rule; the miss run is measured only up to the mistimed release.
        trace, players, mech, result = self.replay_v3('fall', self.FALL_V3, self.FALL_TICKS, self.S01_02_EXIT, density_until=60)
        release = next(e for e in mech if e['type']=='release')
        self.assertEqual((release['element'], release['tick']), ('S01-hoist', 55))
        floor = [e for e in mech if e['type']=='bounce' and e['element']=='S01-floor']
        self.assertTrue(floor)
        land = floor[0]['tick']
        apex_tick = min(range(55, land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        entry = next(t for t in range(56, land) if self.in_box(players[t], self.YARD_DRAG))
        self.assertTrue(all(self.in_box(players[t], self.YARD_DRAG) for t in range(entry, self.REJOIN_TICK)))
        before = players[entry-1]
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_floor = contact['before']['simulation']['player']
        self.assertGreater(abs(before['speedX']), .5)
        self.assertLess(abs(at_floor['speedX']), .01*abs(before['speedX']))
        self.assertLess(at_floor['speedY'], before['speedY'])
        # Per-tick damping while airborne in the zone: vx x0.8 exactly; vy below free fall.
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, entry+8) if abs(players[t]['speedX']) > 1e-9]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios)
        rest_y = floor[0]['player']['y']
        fall_height = rest_y - apex['y']
        bounces = [e for e in floor if e['tick'] < self.REJOIN_TICK]
        peaks = []
        for a, b in zip(bounces, bounces[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(a['height'] > b['height'] for a, b in zip(peaks[:4], peaks[1:4])), peaks[:4])
        window = players[600:self.REJOIN_TICK]
        self.assertTrue(all(abs(p['speedX']) < 1e-6 for p in window))
        self.assertLess(rest_y - min(p['y'] for p in window), 15)
        self.assertLess(max(abs(p['speedY']) for p in window), .2)
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_TICK]
        self.assertEqual(len(rejoin_inputs), 4)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after = self.kinds(mech, self.REJOIN_TICK)
        after = [k for k in after if k != ('bounce','S01-floor')]
        self.assertEqual(after, [('acquisition','S01-yard-pad'),('release','S01-yard-pad'),('acquisition','S01-lift'),
                                 ('release','S01-lift'),('bounce','S01-deflector')])
        yard = next(e for e in mech if e['type']=='acquisition' and e['element']=='S01-yard-pad')
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S01-lift')
        deflector = next(e for e in mech if e['type']=='bounce' and e['element']=='S01-deflector')
        fall = dict(scenario='naturally mistimed S01-01 release: hoist held 45 ticks instead of 60; physical fall; no relocation',
            release=dict(tick=55, element='S01-hoist', player=release['player'], release_height_y=release['player']['y']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='floor-bounce rest y minus apex y after the release',
            drag_zone=dict(id='S01-yard-drag', box=self.YARD_DRAG, entry_tick=entry,
                before=dict(tick=entry-1, speedX=before['speedX'], speedY=before['speedY'], player=before),
                after=dict(tick=land, speedX=at_floor['speedX'], speedY=at_floor['speedY'], player=at_floor),
                per_tick_vx_ratio_airborne=ratios, vertical_damping_per_tick=0.985),
            floor_bouncer=dict(element='S01-floor', first_bounce_tick=land, rest_y=rest_y),
            bounce_peaks=peaks, first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            settled=dict(window=[600, self.REJOIN_TICK-1], max_abs_speedX=max(abs(p['speedX']) for p in window),
                max_abs_speedY=max(abs(p['speedY']) for p in window), y_range=[min(p['y'] for p in window), max(p['y'] for p in window)],
                inside_drag_zone=True, on='S01-floor'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                yard_pad_acquisition=dict(tick=yard['tick'], anchor=yard['rope'][0], player=yard['player']),
                lift_acquisition=dict(tick=lift['tick'], anchor=lift['rope'][0], player=lift['player']),
                deflector_bounce=dict(tick=deflector['tick'], player=deflector['player']),
                final=players[-1], encounter_rejoined='S01-02 exit box (S01-03 start)', exit_box=self.S01_02_EXIT))
        result.update(fall)
        self.evidence.write('encounters/fall/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed hoist release tick 55 at y', round(release['player']['y'],1), '; apex', round(apex['y'],1),
              '; drag entry tick', entry, 'vx/vy', round(before['speedX'],3), round(before['speedY'],3), '->', round(at_floor['speedX'],5),
              round(at_floor['speedY'],3), '; floor bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of', round(fall_height,1),
              '; settled on S01-floor; input-only rejoin: yard pad tick', yard['tick'], ', lift tick', lift['tick'],
              ', deflector tick', deflector['tick'], ', S01-02 exit box at tick', self.FALL_TICKS)


class Task506Tests(FoundationsV3CompleteChecks, unittest.TestCase):
    """Foundations S01-03/04, exit and fall recovery, re-specced by TASK-548 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, shared with Task548Tests via FoundationsV3CompleteChecks):
    test_01_geometry_and_rules: v2 rules, rest pads, 459-486 gaps, fall lines onto mountain-catch -> v3 rules,
    zero gray solids, 918-972 gaps, fall points over drag zones onto the green S01-floor, exit pad in a drag zone.
    test_02_s01_03_nominal: crane + jib hooks onto the gantry pad -> green gantry hook caught on the deflector rebound.
    test_03_s01_04_nominal: boom hook onto the S01-exit rest pad -> green crown hook onto the green exit pad.
    test_04_full_traversal: base spawn to the S01-exit rest -> base spawn to a settle on the green exit pad.
    test_05_fall_through_drag_and_rejoin: mistimed hoist (14 ticks) onto the solid base -> mistimed hoist
    (45 ticks) through the yard drag zone onto the green floor bouncers, then a yard-pad + lift rejoin.
    test_06_source_hashes is unchanged. The v2 helpers and constants below stay for the later v2 suites.
    """
    task_id = 'TASK-506'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    report = Task505Tests.report
    test_06_source_hashes = V1Task465.test_03_source_hashes
    S01_01 = Task505Tests.S01_01
    S01_02 = Task505Tests.S01_02
    CRANE, JIB, BOOM = (3350.05,-802.46), (3607.4,-994.39), (3920,-1740)
    S01_03 = [(400,'mousedown',*CRANE),(432,'mouseup',*CRANE),(455,'mousedown',*JIB),(487,'mouseup',*JIB)]
    S01_04 = [(760,'mousedown',*BOOM),(802,'mouseup',*BOOM)]
    # Mistimed S01-01: the hoist is released after 14 ticks instead of 40.
    FALL = [(10,'mousedown',2500,-318),(24,'mouseup',2500,-318),(300,'mousedown',2600,-318),(362,'mouseup',2600,-318)]
    MOVERS = ('S01-hoist','S01-lift')
    HOOKS = ('S01-crane-hook','S01-jib-hook','S01-boom-hook')
    DRAG = 'S01-yard-drag'
    BAND = (459, 486)
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])

    def box(self, name):
        b = {'S01-01':(2940,3090,-131,-130),'S01-02':(3500,3650,-361,-360),'S01-03':(3700,3860,-1271,-1270),
             'S01-04':(4060,4220,-1631,-1630)}[name]
        return dict(x=list(b[:2]), y=list(b[2:]), **self.REST)

    def at_rest(self, player, name):
        b = self.box(name)
        return all(b[k][0] <= player[k] <= b[k][1] for k in ('x','y','speedX','speedY'))

    def compact(self, trace):
        """Keep per-tick hashes and the fields the assertions use, not full world state."""
        pick = lambda s: dict(player=s['simulation']['player'], grapple={k:s['simulation']['grapple'][k]
            for k in ('throwed','grappled')}, rope=s['rope'], camera=s['camera'])
        events = []
        for e in trace['events']:
            row = {k:e[k] for k in ('sequence','tick','type') if k in e}
            for k in ('trusted','event','world','client','contact'):
                if k in e: row[k] = e[k]
            for k in ('before','after'):
                if k in e: row[k] = pick(e[k])
            events.append(row)
        return dict(name=trace['name'], outcome=trace['outcome'], metadata=trace['metadata'],
            full_trace_sha256=state_hash(trace), compaction='snapshots keep tick, full-state sha256, player, grapple flags, rope and camera',
            snapshots=[dict(tick=r['tick'], sha256=r['sha256'], **pick(r['state'])) for r in trace['snapshots']], events=events)

    def replay(self, name, plan, ticks, bounds, kind='base-start', snapshot=None):
        from grapple_over_verify import metadata, execute, check_trace
        m = dict(metadata=metadata(kind), inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=['acquisition','release'])
        if snapshot: m['initial_snapshot'] = snapshot
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=True)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, self.compact(t))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce') or (e['type']=='contact' and element in self.MOVERS):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    player=e['after']['simulation']['player'], rope=e['after']['rope']))
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        result = dict(passed=True, matching_traces=True, trusted_inputs=True, kind=kind,
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[dict(tick=x['tick'],type=x['type'],element=x['element'],player=x['player']) for x in mechanics],
            final=players[-1], expected_exit=bounds,
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        return trace, mechanics, players, result

    def reach(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.BAND[0] <= distance <= self.BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y'],speedX=p['speedX'],speedY=p['speedY']), anchor=a['rope'][0],
            band=list(self.BAND), in_band=True)

    def record_reach(self, rows):
        if not self.evidence.path('rules.json').exists(): return
        rules = json.loads(self.evidence.path('rules.json').read_text())
        rules.setdefault('trace_measured_reach', {}).update({r['element']:r for r in rows})
        self.evidence.write('rules.json', rules)

    def base_contact(self, e):
        # Contacts carry no element id; mountain-catch is the only surface whose top is y=120.
        c = e.get('contact') or {}
        return e['type'] == 'contact' and c.get('y') == 120 and c.get('ny') == -1

    def acquisitions(self, mechanics):
        return [(e['element'], e['tick']) for e in mechanics if e['type']=='acquisition']


class FoundationsV3ToleranceChecks:
    """Layout-v3 Foundations (S01) tolerance on desktop 1280x720 and touch 844x390 (TASK-549).

    Every attempt is a base-start run (production restart at the base spawn, no placement or
    snapshot) with recorded trusted mouse/touch input: the encounter's inputs carry the variant,
    the other encounters keep their TASK-547/548 nominal inputs. The intended exit is the S01
    section exit (landed on the green exit pad inside S01-exit-drag at tick 1200), and
    check_s01_v3_mechanics requires the encounter's own mechanic, the four S01 anchors in route
    order and no S01-floor fall. Shared by Task549Tests and by the re-specced Task507Tests.
    """
    V3 = FoundationsV3CompleteChecks
    SEGMENTS = [V3.S01_01_V3, V3.S01_02_V3, V3.S01_03_V3, V3.S01_04_V3]
    V3_TICKS = 1200
    V3_EXIT = V3.LAND
    # (id, mechanic, start tick, manifest exit tick) in the nominal route; S01-04 ends at the
    # exit pad landing. Every anchor underside is horizontal, so aim variants move along x.
    V3_ENCOUNTERS = [('S01-01','blue hoist pull from the green entry pad, release onto the green yard bouncer',0,255),
                     ('S01-02','blue lift pull off the yard rebound, release into the green deflector rebound',255,370),
                     ('S01-03','green gantry hook caught in flight on the up-left rebound, swing reversed to the right',370,520),
                     ('S01-04','green crown hook caught in flight, release onto the green exit pad in S01-exit-drag',520,None)]
    V3_VARIANTS = [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]
    # Mistimed releases, one per encounter, that fall through a drag zone onto S01-floor:
    # (encounter, release tick replacing the nominal one, nominal release tick, ticks).
    MISTIMED = [('S01-01',55,70,700), ('S01-02',280,334,1100), ('S01-03',445,465,1300), ('S01-04',580,615,1250)]
    DENSITY_CAP = 254
    HUD = (0.3, 0.18)  # top-left HUD block (4 text rows) as fractions of the viewport
    V3_MOVERS = ('S01-hoist','S01-lift')

    def make_input(self, plan, ticks, bounds, device='desktop', snapshot=None):
        from grapple_over_verify import metadata
        m = dict(metadata=metadata('isolated' if snapshot else 'base-start'), ticks=ticks, expected_exit=bounds,
            required_events=['acquisition','release'],
            inputs=[dict(tick=t, event=e if device=='desktop' else {'mousedown':'touchstart','mouseup':'touchend'}[e],
                         world=dict(x=x, y=y)) for t,e,x,y in plan])
        m['metadata']['compact_contacts'] = True
        if device == 'touch': m['metadata']['viewport'] = dict(width=844, height=390)
        if snapshot: m['initial_snapshot'] = snapshot
        return m

    def run_attempt(self, m, prefix, filmstrip=False):
        """Record with real input, keep the full trace gzip-compressed inside input.json.gz
        (what the audit replays) and a compact per-tick trace.json for reading."""
        import gzip
        from grapple_over_verify import execute, check_trace
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=filmstrip)
        m['trace'] = trace
        self.evidence.path(prefix+'/input.json.gz').write_bytes(
            gzip.compress(json.dumps(m, separators=(',',':')).encode(), 6, mtime=0))
        self.evidence.write(prefix+'/trace.json', self.compact(trace))
        success, reason = True, 'expected exit and mechanic events satisfied'
        try: check_trace(m, trace)
        except ValueError as error: success, reason = False, str(error)
        if filmstrip: self.filmstrip(prefix, m['metadata']['viewport'])
        return trace, success, reason

    def filmstrip(self, prefix, viewport):
        """Combine the per-input/per-second frames into one JPEG sheet and drop the PNGs."""
        from PIL import Image
        frames = sorted(self.evidence.path(prefix+'/x').parent.glob('frame-*.png'))
        w, h = viewport['width']//2, viewport['height']//2
        cols = 4; rows = (len(frames)+cols-1)//cols
        sheet = Image.new('RGB', (cols*w, rows*h))
        for i, f in enumerate(frames):
            with Image.open(f) as img: sheet.paste(img.convert('RGB').resize((w, h)), ((i%cols)*w, (i//cols)*h))
            f.unlink()
        sheet.save(self.evidence.path(prefix+'/filmstrip.jpg'), quality=80)
        self.evidence.write(prefix+'/filmstrip.json', dict(frames=[f.name for f in frames], cols=cols, tile=[w, h]))

    def targets(self, trace, viewport):
        """Every press lands inside the viewport and outside the HUD block (no blind target)."""
        rows = []
        for e in trace['events']:
            if e['type'] == 'input' and e['event'] in ('mousedown','touchstart'):
                c = e['client']
                inside = 0 < c['x'] < viewport['width'] and 0 < c['y'] < viewport['height']
                hud = c['x'] < self.HUD[0]*viewport['width'] and c['y'] < self.HUD[1]*viewport['height']
                rows.append(dict(tick=e['tick'], world=e['world'], client=c, in_viewport=inside, under_hud=hud))
        return rows

    def variant_plan(self, index, delta=0, shift=0):
        """Nominal S01 route with the variant on encounter `index` (release timing, aim along x)."""
        plan = []
        for k, segment in enumerate(self.SEGMENTS):
            for i, (t, e, x, y) in enumerate(segment):
                if k == index:
                    t += delta if i == 1 else 0
                    x += shift
                plan.append((t, e, x, y))
        return plan

    def density_v3(self, trace, name, start, end):
        """Longest stretch inside [start, end] without an acquisition, bounce or mover contact."""
        marks = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] == 'acquisition': element = e['after']['rope'][0]['id']
            if e['type'] in ('acquisition','bounce') or (e['type']=='contact' and element in self.V3_MOVERS):
                if start <= e['tick'] <= end and (not marks or marks[-1]['tick'] != e['tick']):
                    marks.append(dict(tick=e['tick'], type=e['type'], element=element))
        points = [start]+[m['tick'] for m in marks]+[end]
        gaps = [b-a for a, b in zip(points, points[1:])]
        i = gaps.index(max(gaps))
        return dict(trace=name, window=[start, end], interactions=marks, max_gap=max(gaps),
                    longest_gap=[points[i], points[i+1]], cap=self.DENSITY_CAP)

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s01_v3_mechanics
        source = hashes()
        suite = dict(section='S01', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='base-start for every attempt: production restart at the base spawn (2160,0), no placement, no snapshot; '
                       'variant inputs on the named encounter, TASK-547/548 nominal inputs elsewhere',
            browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exit=dict(box=self.V3_EXIT, tick=self.V3_TICKS, meaning='landed on S01-exit-pad inside S01-exit-drag (S01 section exit)'),
            mechanics_check='tools/grapple_over_verify.py check_s01_v3_mechanics',
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal = [], {}
        for k, (name, mechanic, start, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), self.V3_TICKS, self.V3_EXIT, device)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s01_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s01_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), (label, targets))
                        land = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S01-exit-pad')
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', start, exit_tick or land)
                        if exit_tick:
                            box = {'S01-01':self.V3.S01_01_EXIT,'S01-02':self.V3.S01_02_EXIT,'S01-03':self.V3.S01_03_EXIT}[name]
                            self.assertTrue(self.V3.inside(players[exit_tick], box), (label, players[exit_tick]))
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        outcome='S01 exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(LAYOUT_V3_DENSITY_CAP_TICKS = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','contact with S01-hoist/S01-lift'], cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal route (0/255/370/520) to its manifest exit tick '
                   '(255/370/520) or, for S01-04, the exit-pad landing; the settle on the exit pad is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control()
        self.assertEqual(failures, [])
        print('PASS S01 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-crown negative control fails the exit')

    def negative_control(self):
        from grapple_over_verify import hashes, check_s01_v3_mechanics
        # Named omission: the S01-04 crown-hook press/release left out; same base start, physics
        # and S01-01..03 inputs as every nominal attempt.
        plan = self.variant_plan(-1)[:6]
        m = self.make_input(plan, self.V3_TICKS, self.V3_EXIT)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s01_v3_mechanics('S01-04', trace, required=False)
        floor = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S01-floor')
        self.evidence.write('negative-control.json', dict(name='omitted crown hook: S01-04 S01-crown-hook press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=self.V3_EXIT, unchanged_physics=True, source_hashes=hashes(),
            proof_kind='base-start, real mouse input, same S01-01..03 inputs as the nominal attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step, exit_pad_contact='S01-exit-pad' in [b['element'] for b in mechanics['bounces']],
            floor_bounce_tick=floor, final_player=players[-1],
            scope='Without the crown catch the gantry flight drops past the exit pad through S01-exit-drag and S01-yard-drag onto S01-floor.'))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S01-crown-hook', mechanics['acquisitions'])
        self.assertNotIn('S01-exit-pad', [b['element'] for b in mechanics['bounces']])
        self.assertLess(step, 60)

    def test_02_mistimed_release_no_bounce_back(self):
        from grapple_over_verify import check_s01_v3_mechanics
        V3 = self.V3
        zones = dict(yard=V3.YARD_DRAG, exit=V3.EXIT_DRAG)
        rows = {}
        for k, (name, release, nominal, ticks) in enumerate(self.MISTIMED):
            segment = self.SEGMENTS[k]
            self.assertEqual(segment[1][0], nominal)
            plan = [p for seg in self.SEGMENTS[:k] for p in seg]+[segment[0], (release,)+segment[1][1:]]
            for device in ('desktop','touch'):
                m = self.make_input(plan, ticks, dict(y=[-1e9, 1e9]), device)
                prefix = f'clips/fall-{name}-{device}'
                trace, success, reason = self.run_attempt(m, prefix, True)
                self.assertTrue(success, reason)
                self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                mech = check_s01_v3_mechanics(name, trace, required=False)
                anchor = mech['encounter']['anchor']
                rel = next(r for r in mech['releases'] if r['element']==anchor)
                self.assertEqual(rel['tick'], release)
                r_player = players[release]
                after = [b for b in mech['bounces'] if b['tick'] > release]
                floor = [e['tick'] for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']=='S01-floor']
                self.assertTrue(floor, name)
                # The first surface reached after the mistimed release is the floor bouncer.
                self.assertEqual(after[0]['element'], 'S01-floor', (name, after[:3]))
                land = floor[0]
                crossed = {z: [t for t in range(release, land+1) if V3.in_box(players[t], b)] for z, b in zones.items()}
                self.assertTrue(crossed['yard'], name)
                contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
                rest_y = contact['after']['simulation']['player']['y']
                apex_tick = min(range(release, land), key=lambda t: players[t]['y'])
                second = next((t for t in floor if t > land+1), ticks)
                peak_tick = min(range(land+1, second), key=lambda t: players[t]['y'])
                release_height = rest_y - r_player['y']
                peak_height = rest_y - players[peak_tick]['y']
                fall_height = rest_y - players[apex_tick]['y']
                self.assertLessEqual(peak_height, .5*release_height, name)
                self.assertLessEqual(peak_height, .5*fall_height, name)
                targets = self.targets(trace, m['metadata']['viewport'])
                self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), targets)
                step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
                self.assertLess(step, 60)
                row = dict(encounter=name, device=device, viewport=m['metadata']['viewport'], anchor=anchor,
                    mistiming=f'{anchor} released at tick {release} instead of {nominal}',
                    input=prefix+'/input.json.gz', trace=prefix+'/trace.json', filmstrip=prefix+'/filmstrip.jpg',
                    release=dict(tick=release, player=r_player), floor_rest_y=rest_y,
                    release_height=release_height, release_height_definition='S01-floor bounce y minus player y at the release tick',
                    apex=dict(tick=apex_tick, y=players[apex_tick]['y']), fall_height_from_apex=fall_height,
                    drag_zones_crossed=[dict(id={'yard':'S01-yard-drag','exit':'S01-exit-drag'}[z], box=zones[z],
                        ticks=[ts[0], ts[-1]], entry_player=players[ts[0]]) for z, ts in crossed.items() if ts],
                    first_bounce=dict(element='S01-floor', tick=land, before=contact['before']['simulation']['player'],
                        after=contact['after']['simulation']['player']),
                    first_bounce_peak=dict(tick=peak_tick, y=players[peak_tick]['y'], height=peak_height,
                        fraction_of_release_height=peak_height/release_height, fraction_of_apex_fall=peak_height/fall_height),
                    at_most_half_of_release_height=True, bounces_after_release=after[:6],
                    max_tick_displacement=step, press_targets=targets, relocation=False)
                rows.setdefault(name, {})[device] = row
                print('PASS fall', name, device, ': release tick', release, 'y', round(r_player['y'],1), '; drag zones',
                      [d['id'] for d in row['drag_zones_crossed']], '; floor bounce tick', land, '; first peak',
                      round(peak_height,1), '=', round(peak_height/release_height,3), 'of release height', round(release_height,1))
        self.evidence.write('no-bounce-back.json', dict(self.proof, rule='a mistimed release passes through the drag zone below '
            'it and its first bounce peaks at most 50% of the release height (i.e. at least 50% lower)',
            proof_kind='base-start, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation',
            encounters=rows, passed=True))


class Task507Tests(FoundationsV3ToleranceChecks, unittest.TestCase):
    """Foundations (S01) tolerance, re-specced by TASK-549 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, shared with Task549Tests via FoundationsV3ToleranceChecks):
    test_01_tolerance_matrix: v2 S01-01..04 from restored rest states, 180-tick density, omitted-jib
    negative control -> v3 S01-01..04 base-start variants judged at the S01 exit-pad landing, 254-tick
    density cap, omitted-crown negative control. test_02_full_route: the v3 full route is the nominal
    S01-04 attempt of test_01 (and Task548 test_04). test_03_drag_zone_fall_clips -> test_02_mistimed_release_no_bounce_back
    (one mistimed release per encounter through a drag zone onto S01-floor, desktop and touch).
    test_04_source_hashes is unchanged. The v2 constants and helpers stay for the later v2 suites
    (Task508/510/513 reuse make_input, run_attempt, filmstrip, targets, ROUTE and S01_04).
    """
    task_id = 'TASK-507'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_04_source_hashes = V1Task465.test_03_source_hashes
    CRANE, JIB, BOOM = Task506Tests.CRANE, Task506Tests.JIB, Task506Tests.BOOM
    # TASK-507 tuning: the gantry pad and boom hook sit 20 lower, so a low jib arc clears the
    # pad's left corner, and the jib is pressed 6 ticks later than TASK-506 so its arc lands
    # on the gantry pad within 180 ticks of the catch (density limit).
    S01_03 = [(400,'mousedown',*CRANE),(432,'mouseup',*CRANE),(461,'mousedown',*JIB),(493,'mouseup',*JIB)]
    # A 48-tick boom hold (TASK-506: 42) swings past the green hook, bouncing off it, onto the exit pad.
    S01_04 = [(760,'mousedown',*BOOM),(808,'mouseup',*BOOM)]
    ROUTE = Task505Tests.S01_01+Task505Tests.S01_02+S01_03
    FALL = Task506Tests.FALL
    FALL_ZONE = dict(id='S01-yard-drag', left=2280, right=4680, top=40, bottom=120)
    LANDED = dict(speedY=[-.001,.001])
    REST = Task506Tests.REST
    BOXES = {'S01-01':dict(x=[2940,3090],y=[-131,-130],**REST), 'S01-02':dict(x=[3500,3650],y=[-361,-360],**REST),
             'S01-03':dict(x=[3700,3900],y=[-1271,-1270],**LANDED), 'S01-04':dict(x=[4060,4220],y=[-1631,-1630],**LANDED)}
    HUD = (0.3, 0.18)  # top-left HUD block (4 text rows) as fractions of the viewport
    VARIANTS = [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]

    @classmethod
    def encounters(cls):
        # (id, start tick in the base-start nominal run or None for base start, global plan, ticks,
        #  critical timing index, aim index, mechanic). Every aimed surface is a horizontal underside.
        return [('S01-01',None,Task505Tests.S01_01,240,1,0,'blue hoist swing onto the yard pad'),
                ('S01-02',180,Task505Tests.S01_02,260,1,0,'blue lift swing, green deflector rebound onto the loading pad'),
                ('S01-03',390,cls.S01_03,320,3,2,'crane hook then jib hook caught in flight onto the gantry pad'),
                ('S01-04',750,cls.S01_04,280,1,0,'boom hook swing past the hook onto the S01 exit pad')]

    def density(self, trace, bounds, name):
        """Gaps between acquisitions, bounces and mover contacts, from tick 0 to the first exit tick."""
        movers = ('S01-hoist','S01-lift')
        ticks = []
        for e in trace['events']:
            if e['type'] in ('acquisition','bounce') or (e['type']=='contact' and (e.get('contact') or {}).get('elementId') in movers):
                if not ticks or ticks[-1][0] != e['tick']:
                    element = e['after']['rope'][0]['id'] if e['type']=='acquisition' else e['contact'].get('elementId')
                    ticks.append((e['tick'], e['type'], element))
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        exit_tick = next(t for t, p in enumerate(players) if all(b[0] <= p[k] <= b[1] for k, b in bounds.items()))
        points = [0]+[t for t, _, _ in ticks if t <= exit_tick]+[exit_tick]
        gaps = [b-a for a, b in zip(points, points[1:])]
        return dict(trace=name, exit_tick=exit_tick, interactions=[dict(tick=t, type=k, element=el) for t, k, el in ticks if t <= exit_tick],
                    max_gap=max(gaps), longest_gap=[points[gaps.index(max(gaps))], points[gaps.index(max(gaps))+1]], limit=180)



# Pre-TASK-550 revision whose S02 is the layout-v2 Switchback (TASK-508..510).
V2_S02_REVISION = 'b680caa'
# What happened to every static v2 S02 solid in the layout-v3 rebuild (TASK-550).
V2_S02_DISPOSITION = {
    'S02-rail-bracket':('deleted','v2 non-grappleable shuttle rail end that capped the v2 S01-04 boom arc; the v3 S01 never reaches it'),
    'S02-balcony':('deleted','v2 S02-01 landing / S02-02 launch rest; the v3 S02-01 ends in flight off the green canopy'),
    'S02-landing':('converted-to-bounce','Kept at (2987,-2100) as a green 200x40 bouncer only because the v2 Broken Viaduct '
                   'S03-02 fall line lands on it; no v3 S02 route uses it'),
    'S02-ledge':('deleted','v2 S02-03 landing / S02-04 launch rest; S02-03/04 are planned for layout v3'),
    'S02-exit-pad':('converted-to-bounce','Kept at (2000,-2680) as a green 200x40 bouncer only as the v2 Broken Viaduct S03-01 '
                    'start reference; no v3 S02 route uses it')}
# The other v2 S02 elements (movers, bouncers, drag brakes): deleted or id re-used by a new v3 element.
V2_S02_OTHER = {'S02-shuttle':'deleted', 'S02-trolley':'deleted', 'S02-crest-hook':'deleted',
    'S02-balcony-brake':'deleted', 'S02-ledge-brake':'deleted', 'S02-fall-drag':'deleted',
    'S02-lift':'id re-used: new blue y mover (4925,-4705) for the v3 S02-02',
    'S02-bulkhead':'id re-used: new green west wall (4840,-4300) 30x500 for the v3 S02-02'}
V3_S02_ADDED = ('S02-hoist','S02-canopy')
# Elements TASK-551 added to complete the v3 S02 (no v2 counterpart).
V3_S02_TASK551_ADDED = ('S02-gallery-hook','S02-east-wall','S02-crown-hook','S02-exit-ledge','S02-exit-drag')


class SwitchbackV3Checks:
    """Layout-v3 Switchback opening (S02-01/02) from the real S01 v3 exit settled pose (TASK-550).

    The start pose comes from a base-start real-input run of the v3 S01 route (TASK-548 nominal
    inputs) that settles on the green S01 exit pad; it is restored once as a labeled initial
    placement. Production input and physics run from there. Not a continuous-completion claim.
    Shared by Task550Tests and the re-specced Task508Tests (same cases, task-local evidence).
    """
    S01_V3_ROUTE = FoundationsV3CompleteChecks.ROUTE_V3
    # The S01 exit settle starts by tick 1320 (TASK-548); the placement is the tick-1495 state.
    S01_V3_TICKS = 1495
    S01_V3_SETTLE = FoundationsV3CompleteChecks.SETTLE
    HOIST, LIFT_V3 = (6100,-3670), (4985,-4665)
    S02_01_V3 = [(5,'mousedown',*HOIST),(110,'mouseup',*HOIST)]
    S02_02_V3 = [(230,'mousedown',*LIFT_V3),(290,'mouseup',*LIFT_V3)]
    S02_V3_MOVERS = ('S02-hoist','S02-lift')
    S02_V3_BAND = (918, 972)
    # Exit boxes (also the manifest encounter exits): dropping down-left off the green
    # canopy; and rebounding right off the green west bulkhead.
    S02_01_EXIT = dict(x=[5800,5950], y=[-4250,-4100], speedX=[-.6,-.3], speedY=[.5,1.2])
    S02_02_EXIT = dict(x=[4950,5150], y=[-3880,-3760], speedX=[1,2.5], speedY=[0,1])
    S02_01_TICKS, S02_02_TICKS = 225, 330
    S01_EXIT_DRAG = FoundationsV3CompleteChecks.EXIT_DRAG
    report = FoundationsV3Checks.report
    inside = staticmethod(FoundationsV3CompleteChecks.inside)

    @staticmethod
    def bounds_v3(e, travel=None):
        b = dict(left=e['x']+min(p['x'] for p in e['points']), right=e['x']+max(p['x'] for p in e['points']),
                 top=e['y']+min(p['y'] for p in e['points']), bottom=e['y']+max(p['y'] for p in e['points']))
        if travel:
            span = travel['max']-travel['min']
            if travel['axis'] == 'x': b['right'] += span
            else: b['bottom'] += span
        return b

    def v2_s02(self):
        """The layout-v2 S02 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V2_S02_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[1], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, elements:m.geometry.elements.filter(e=>e.id.startsWith('S02-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S02-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S02-'))}}''', source)

    def s01_v3_exit(self):
        """Real S01 v3 exit settled pose: a base-start real-input run of the v3 S01 route (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'v3_start'): return type(self).v3_start
        m = dict(metadata=metadata('base-start'), ticks=self.S01_V3_TICKS, expected_exit=self.S01_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.S01_V3_ROUTE],
            required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/S01-exit-start'
        self.evidence.write(prefix+'/input.json', m)
        setup = execute(m, self.browser, self.url, str(self.evidence.path(prefix)))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual([a for a in acquired if a != 'S01-entry-pad'], ['S01-hoist','S01-lift','S01-gantry-hook','S01-crown-hook'])
        touched = sorted({(e.get('contact') or {}).get('elementId') for e in setup['events']} - {None})
        self.assertFalse([t for t in touched if t.startswith('S02-')], touched)
        self.evidence.write(prefix+'/trace.json', Task506Tests.compact(self, setup))
        settle = next(t for t in range(1000, self.S01_V3_TICKS+1)
                      if all(self.inside(p, self.S01_V3_SETTLE) for p in players[t:]))
        self.assertLessEqual(settle, 1400)
        start = setup['snapshots'][-1]['state']['simulation']
        self.assertTrue(FoundationsV3CompleteChecks.in_box(start['player'], self.S01_EXIT_DRAG))
        # Clearance of the S01 v3 flight (whole base-start route) from the new S02 route elements.
        report = self.report(); m2 = report['manifest']
        travel = {v['element']:v for v in m2['geometry']['movers']}
        clearance = {}
        for e in m2['geometry']['elements']:
            # Every v3 S02 route collider (TASK-550/551); the kept v2 pads and drag zones are not route elements.
            if not e['id'].startswith('S02-') or e['role'] == 'drag' or e['id'] in ('S02-landing','S02-exit-pad'): continue
            b = self.bounds_v3(e, travel.get(e['id']))
            gap = min(math.hypot(max(b['left']-p['x'], 0, p['x']-b['right']), max(b['top']-p['y'], 0, p['y']-b['bottom']))
                      for p in players)
            clearance[e['id']] = gap - players[0]['radius']
            self.assertGreater(clearance[e['id']], 50, (e['id'], clearance))
        type(self).v3_start = start
        type(self).v3_start_proof = dict(kind='base-start S01 v3 route (TASK-548 nominal inputs), real mouse input, no placement',
            inputs=m['inputs'], acquisitions=acquired, settled_in_exit_box_from_tick=settle, settle_box=self.S01_V3_SETTLE,
            final_tick=self.S01_V3_TICKS, player=start['player'], inside_S01_exit_drag=True,
            snapshot_sha256=setup['snapshots'][-1]['sha256'], full_trace_sha256=state_hash(setup), trace=prefix+'/trace.json',
            s02_element_contacts=[], s01_flight_clearance_to_s02_route_elements=clearance)
        self.evidence.write(prefix+'/result.json', dict(passed=True, **type(self).v3_start_proof))
        return start

    def run_v3(self, name, plan, ticks, bounds, density_until=None):
        """Labeled placement of the real S01 exit pose, then trusted input; identical replay."""
        from grapple_over_verify import metadata, execute, check_trace
        start = self.s01_v3_exit()
        m = dict(metadata=metadata('isolated'), inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=['acquisition','release','bounce'], initial_snapshot=start)
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=True)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, Task506Tests.compact(self, t))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        self.assertTrue(self.inside(players[0], self.S01_V3_SETTLE), players[0])
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce') or (e['type']=='contact' and element in self.S02_V3_MOVERS):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    mover=element in self.S02_V3_MOVERS, player=e['after']['simulation']['player'], rope=e['after']['rope']))
        # Longest stretch without an acquisition, bounce or mover contact (LAYOUT_V3_DENSITY_CAP_TICKS).
        # Density is a nominal-route rule: miss runs and settles are measured only up to density_until.
        until = ticks if density_until is None else density_until
        marks = sorted({0, until, *[x['tick'] for x in mechanics if x['type'] != 'release' and x['tick'] <= until]})
        stretch = max(b-a for a, b in zip(marks, marks[1:]))
        self.assertLessEqual(stretch, 254)
        travel = {}
        for mover in self.S02_V3_MOVERS:
            anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']==mover]
            if anchors:
                travel[mover] = dict(dx=anchors[-1]['x']-anchors[0]['x'], dy=anchors[-1]['y']-anchors[0]['y'], ticks=len(anchors))
        result = dict(passed=True, matching_traces=True, trusted_inputs=True,
            proof_kind='isolated: one labeled initial placement = restoreClimbState of the real S01 v3 exit settled pose '
                       'from a base-start real-input S01 run; production input/physics thereafter',
            initial_placement=dict(labeled=True, source=type(self).v3_start_proof), not_continuous_completion_claim=True,
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[{k:x[k] for k in ('tick','type','element','mover','player')} for x in mechanics],
            mover_anchor_travel_while_attached=travel, longest_stretch_without_mechanic_ticks=stretch, density_cap_ticks=254,
            density_measured_until_tick=until,
            final=players[-1], expected_exit=bounds, final_in_exit_box=self.inside(players[-1], bounds),
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        self.assertTrue(result['final_in_exit_box'], players[-1])
        return trace, players, mechanics, result

    def reach_s02(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.S02_V3_BAND[0] <= distance <= self.S02_V3_BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y'],speedX=p['speedX'],speedY=p['speedY']), anchor=a['rope'][0],
            band=list(self.S02_V3_BAND), in_band=True)

    def s02_kinds(self, mech):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S01-exit-pad']

    def bounce_at(self, trace, element):
        b = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']==element)
        return b, b['before']['simulation']['player'], b['after']['simulation']['player']

    def test_01_geometry_and_rules(self):
        r = self.report(); v2 = self.v2_s02()
        m = r['manifest']; elements = m['geometry']['elements']
        s02 = m['sections'][1]
        # TASK-551 completed S02-03/04, the exit and the S02 fall recovery; TASK-553 built the
        # S03 entrance once the Viaduct was rebuilt from the v3 S02 exit.
        self.assertEqual((s02['designVersion'], s02['status']), (3, 'built'))
        self.assertEqual([e['status'] for e in m['encounters'][4:8]], ['built']*4)
        # Since TASK-553 the v3 Viaduct starts on the v3 S02 exit ledge, so the S03 entrance is built.
        self.assertEqual([c['status'] for c in m['connectors'][4:9]], ['built']*5)
        self.assertNotIn('solidExceptions', s02)
        self.assertEqual(s02['band']['top'], -4860); self.assertEqual(s02['band']['bottom'], -1620)
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S02-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S02-')}
        self.assertEqual(set(movers), set(self.S02_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        enc = {e['id']:e for e in m['encounters'][4:6]}
        self.assertEqual(enc['S02-01']['start'], {'x':6373.4,'y':-2711.1,'from':'S01-04'})
        self.assertEqual(enc['S02-02']['start'], {'from':'S02-01','x':5863.4,'y':-4163.6})
        for e in enc.values():
            self.assertTrue(any(x in movers for x in e['elements']), e['id'])
            self.assertTrue(any(by_id[x]['role'] == 'bounce' for x in e['elements']), e['id'])
        for name, box in (('S02-01', self.S02_01_EXIT), ('S02-02', self.S02_02_EXIT)):
            self.assertEqual(enc[name]['exit'], dict(left=box['x'][0], right=box['x'][1], top=box['y'][0], bottom=box['y'][1]))
        sec = r['report']['sections'][1]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S02', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][:2], ['S01','S02'])
        self.assertFalse(r['report']['failed'])
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('left', 'left'))
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S02-01','S02-02'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S02_V3_BAND))
        # Since TASK-551 the S02-03/04 gaps follow; only the S02-01/02 ones are pinned here.
        self.assertEqual([g['id'] for g in gaps][:2], ['S02-01-hoist','S02-02-lift'])
        gaps = gaps[:2]
        for g in gaps:
            self.assertTrue(self.S02_V3_BAND[0] <= g['distance'] <= self.S02_V3_BAND[1], g)
        # Every declared S02-01/02 miss falls through a drag zone (S01's) onto a green bouncer.
        falls = [f for f in sec['rules']['dragUnderFall']['measured']['fallPoints'] if f['encounter'] in ('S02-01','S02-02')]
        self.assertEqual([f['id'] for f in falls], ['S02-01-short','S02-02-missed','S02-02-rebound'])
        expected_falls = {'S02-01-short':(['S01-exit-drag'],'S01-exit-pad'), 'S02-02-missed':(['S01-yard-drag'],'S01-floor'),
                          'S02-02-rebound':(['S01-yard-drag','S01-exit-drag'],'S01-floor')}
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), expected_falls[f['id']], f)
            self.assertEqual(by_id[f['firstBouncer']]['role'], 'bounce')
        # The only S02 drag zone is the TASK-551 exit drag zone, under the S02-04 fall point only.
        # Since TASK-553 the S03-01-short fall point also drops into it; only the S02 ones are pinned here.
        self.assertEqual([dict(id=d['id'], fallPoints=[p for p in d['fallPoints'] if p.startswith('S02-')])
                          for d in sec['rules']['strayDrag']['measured']['dragZones']], [dict(id='S02-exit-drag', fallPoints=['S02-04-overshoot'])])
        # v2/v3 ratio against the v2 S02-01/02 gaps recorded by TASK-508 (and the v2 source).
        v2_geometry = json.loads((ROOT/'artifacts/TASK-508/geometry.json').read_text())
        v2_gaps = {g['id']:g for g in v2_geometry['manifest_section']['gaps']}
        self.assertEqual([v2_gaps[k] for k in ('S02-01-shuttle','S02-02-lift')], v2['section']['gaps'][:2])
        dist = lambda g: ((g['to']['x']-g['from']['x'])**2+(g['to']['y']-g['from']['y'])**2) ** .5
        v2_d = {k:dist(v2_gaps[k]) for k in ('S02-01-shuttle','S02-02-lift')}
        v3_d = {g['id']:g['distance'] for g in gaps}
        v2_mean, v3_mean = sum(v2_d.values())/2, sum(v3_d.values())/2
        ratio = v3_mean/v2_mean
        self.assertGreaterEqual(ratio, 2.0)
        per_gap = {k3:v3_d[k3]/v2_d[k2] for k3, k2 in (('S02-01-hoist','S02-01-shuttle'),('S02-02-lift','S02-02-lift'))}
        self.assertTrue(all(x >= 2.0 for x in per_gap.values()), per_gap)
        # Every static v2 S02 solid is deleted or converted to a green bouncer.
        self.assertEqual(sorted(v2['staticSolids']), sorted(V2_S02_DISPOSITION))
        own_ids = {e['id'] for e in own}
        mapping = []
        for old in v2['staticSolids']:
            kind, why = V2_S02_DISPOSITION[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertNotIn(old, own_ids, old)
            else: self.assertEqual(now['role'], 'bounce', old)
            mapping.append(dict(id=old, v2_role='solid', disposition=kind, v3_role=now['role'] if now else None, reason=why))
        v2_ids = {e['id'] for e in v2['elements']}
        self.assertEqual(sorted(v2_ids - set(V2_S02_DISPOSITION)), sorted(V2_S02_OTHER))
        for old, what in V2_S02_OTHER.items():
            self.assertEqual(old in own_ids, what.startswith('id re-used'), old)
        self.assertEqual(sorted(own_ids - v2_ids), sorted(V3_S02_ADDED+V3_S02_TASK551_ADDED))
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S02-01','S02-02'], completed_by_task551=['S02-03','S02-04'],
            gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=v3_d, v2_gap_distances=v2_d, v2_gap_source='artifacts/TASK-508/geometry.json manifest_section.gaps',
            v2_mean_gap=v2_mean, v3_mean_gap=v3_mean, v3_over_v2_mean_ratio=ratio, v3_over_v2_per_gap=per_gap,
            ratio_at_least_2=True, direction_note='since TASK-551 the direction rule reads the built S02-04 exit box',
            fall_points=falls, own_drag_zones=sec['rules']['strayDrag']['measured']['dragZones']))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s02, encounters=m['encounters'][4:8],
            connectors=m['connectors'][4:9], recovery=m['recoveries'][1], elements=own, movers=list(movers.values()), roles=roles,
            gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True, v2_revision=V2_S02_REVISION,
            v2_static_solids=v2['staticSolids'], v2_solid_disposition=mapping, v2_other_elements=V2_S02_OTHER,
            v3_added=list(V3_S02_ADDED), task551_added=list(V3_S02_TASK551_ADDED)))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="2400 -5050 4356 2450" style="background:#111827">']
        for e in elements:
            if not e['id'].startswith('S01-'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.25' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>'
                         f'<text x="{e["x"]+5}" y="{e["y"]+40}" fill="#9ca3af" font-size="40">{e["id"]}</text>')
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            parts.append(f'<polygon points="{pts}" fill="{colors[roles[e["id"]]]}" stroke="white" stroke-width="3"/>'
                         f'<text x="{e["x"]}" y="{e["y"]-14}" fill="white" font-size="46">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+15}" x2="{e["x"]+60+dx}" y2="{e["y"]+15+dy}" stroke="#93c5fd" stroke-width="6" stroke-dasharray="10,6"/>')
        for g in s02['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="10,8"/>')
        for f in falls:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="{min(f["firstBouncerTop"], -2600)}" stroke="#fb923c" stroke-width="3" stroke-dasharray="4,10"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="12" fill="#fb923c"/><text x="{f["x"]+16}" y="{f["y"]+8}" fill="#fb923c" font-size="40">{f["id"]}</text>')
        for e in m['encounters'][4:6]:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="5"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+32}" fill="#f472b6" font-size="44">{e["id"]} exit</text>')
        parts.append('<circle cx="6373.4" cy="-2711.1" r="26" fill="#ff7a1a"/>')
        for i, t in enumerate(['S02 Switchback v3 (designVersion 3, travelling left) — zero gray solids; orange = real S01 v3 exit settled pose',
                'S02-01: blue hoist up out of the S01 exit drag -> green canopy bounce; S02-02: blue lift caught on the drop -> green bulkhead rebound',
                'Yellow dashes = gaps %s of 1080 (v3/v2 mean %.3f); orange = fall points into S01 drag zones; pink = exit boxes; grey = S01'
                % ('/'.join(str(round(d,1)) for d in v3_d.values()), ratio)]):
            parts.append(f'<text x="2440" y="{-4985+i*62}" fill="#67e8f9" font-size="50">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=VIEWPORT); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S02 designVersion 3 partial (S02-01/02 built); gray solids', len(gray), '; roles', sorted(set(roles.values())),
              '; all 7 v3 rules pass; gaps', [round(d,1) for d in v3_d.values()], '; v3/v2 mean ratio', round(ratio,4),
              '; v2 solids', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def test_02_s02_01_nominal(self):
        trace, players, mech, result = self.run_v3('S02-01', self.S02_01_V3, self.S02_01_TICKS, self.S02_01_EXIT)
        self.assertEqual(self.s02_kinds(mech), [('acquisition','S02-hoist'),('release','S02-hoist'),('bounce','S02-canopy')])
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S02-hoist']['dy']), 1)
        bounce, before, after = self.bounce_at(trace, 'S02-canopy')
        self.assertLess(before['speedY'], 0); self.assertGreater(after['speedY'], 0); self.assertLess(after['speedX'], 0)
        # The pull lifts the player out of the S01 exit drag zone before it gains leftward speed.
        out = next(t for t, p in enumerate(players) if not FoundationsV3CompleteChecks.in_box(p, self.S01_EXIT_DRAG))
        self.assertLess(out, 110)
        reach = self.reach_s02(players, mech, 5, 'S02-hoist')
        result.update(encounter='S02-01', acquisition_reach=reach, left_s01_exit_drag_tick=out,
            canopy_bounce=dict(tick=bounce['tick'], before=before, after=after))
        self.evidence.write('encounters/S02-01/result.json', result)
        print('PASS S02-01: from the real S01 v3 exit pose; blue hoist acquisition', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; left S01-exit-drag at tick', out, '; green canopy bounce at tick', bounce['tick'],
              '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s02_02_nominal(self):
        trace, players, mech, result = self.run_v3('S02-02', self.S02_01_V3+self.S02_02_V3, self.S02_02_TICKS, self.S02_02_EXIT)
        self.assertEqual(self.s02_kinds(mech), [('acquisition','S02-hoist'),('release','S02-hoist'),('bounce','S02-canopy'),
            ('acquisition','S02-lift'),('release','S02-lift'),('bounce','S02-bulkhead')])
        start = players[self.S02_01_TICKS]
        self.assertTrue(self.inside(start, self.S02_01_EXIT), start)
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S02-lift')
        self.assertGreater(lift['tick'], self.S02_01_TICKS)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S02-lift']['dy']), 1)
        bounce, before, after = self.bounce_at(trace, 'S02-bulkhead')
        self.assertLess(before['speedX'], 0); self.assertGreater(after['speedX'], 0)
        hoist = self.reach_s02(players, mech, 5, 'S02-hoist')
        reach = self.reach_s02(players, mech, 230, 'S02-lift')
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {'S02-hoist':hoist, 'S02-lift':reach}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S02-02', segmented_from='S02-01 exit at tick 225 of the same run (no further placement)',
            s02_01_exit_at_tick_225=start, acquisition_reach=reach, bulkhead_bounce=dict(tick=bounce['tick'], before=before, after=after))
        self.evidence.write('encounters/S02-02/result.json', result)
        print('PASS S02-02: from the S02-01 exit at tick 225; blue lift acquisition', round(reach['distance'],1), 'at tick',
              lift['tick'], '; green bulkhead rebound at tick', bounce['tick'], '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')


class Task508Tests(SwitchbackV3Checks, unittest.TestCase):
    """Switchback opening (S02-01/02), re-specced by TASK-550 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, all shared with Task550Tests via SwitchbackV3Checks):
    test_01_geometry_and_rules: v2 rules, rest-pad exceptions, 459-486 gaps -> v3 rules, zero gray solids,
    918-972 gaps (v3/v2 mean ratio >= 2.0), every v2 S02 solid deleted or converted to a green bouncer.
    test_02_s02_01_nominal: blue shuttle from the v2 S01 exit rest onto the braked balcony pad -> blue hoist
    from the real v3 S01 exit settled pose up out of the S01 exit drag zone into the green canopy bounce.
    test_03_s02_02_nominal: blue lift into the green bulkhead onto the landing pad -> blue lift caught on the
    canopy drop, swung into the green west bulkhead rebound. test_04_source_hashes is unchanged.
    The v2 helpers and constants below (s01_exit, at_rest, reach, routes) stay for the later v2 suites.
    """
    task_id = 'TASK-508'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    replay = Task506Tests.replay
    filmstrip = Task507Tests.filmstrip
    test_04_source_hashes = V1Task465.test_03_source_hashes
    # The TASK-507 S01 nominal route (base spawn to the S01 exit pad) produces the start pose.
    S01_ROUTE = Task507Tests.ROUTE+Task507Tests.S01_04
    SHUTTLE, LIFT = (3880,-1985), (3247,-2240)
    S02_01 = [(5,'mousedown',*SHUTTLE),(47,'mouseup',*SHUTTLE)]
    S02_02 = [(160,'mousedown',*LIFT),(234,'mouseup',*LIFT)]
    MOVERS = ('S02-shuttle','S02-lift')
    BRAKE = dict(id='S02-balcony-brake', left=3420, right=3620, top=-1945, bottom=-1880)
    BAND = (459, 486)
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])
    BOXES = {'S01-04':dict(x=[4209.1,4209.3],y=[-1631,-1630],**REST),
             'S02-01':dict(x=[3460,3620],y=[-1891,-1890],**REST),
             'S02-02':dict(x=[2987,3147],y=[-2111,-2110],**REST)}

    def at_rest(self, player, name):
        return all(b[0] <= player[k] <= b[1] for k, b in self.BOXES[name].items())

    def s01_exit(self):
        """Real S01 exit rest pose: a base-start real-input run of the v2 S01 route (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'start'): return type(self).start
        m = dict(metadata=metadata('base-start'), ticks=1120, expected_exit=self.BOXES['S01-04'],
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.S01_ROUTE],
            required_events=['acquisition','release'])
        m['metadata']['compact_contacts'] = True
        setup = execute(m, self.browser, self.url, str(self.evidence.path('encounters/S01-exit-start')))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual(acquired, ['S01-hoist','S01-lift','S01-crane-hook','S01-jib-hook','S01-boom-hook'])
        self.evidence.write('encounters/S01-exit-start/trace.json', self.compact(setup))
        rest = next(t for t in range(808, 1121) if self.at_rest(players[t], 'S01-04'))
        self.assertTrue(all(self.at_rest(p, 'S01-04') for p in players[rest:]))
        start = setup['snapshots'][-1]['state']['simulation']
        type(self).start = start
        type(self).start_proof = dict(kind='base-start S01 route (TASK-507 nominal inputs), real mouse input, no placement',
            inputs=m['inputs'], acquisitions=acquired, exit_rest_from_tick=rest, final_tick=1120, player=start['player'],
            snapshot_sha256=setup['snapshots'][-1]['sha256'], trace='encounters/S01-exit-start/trace.json')
        self.evidence.write('encounters/S01-exit-start/result.json', dict(passed=True, **type(self).start_proof))
        return start

    def reach(self, players, mech, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mech if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.BAND[0] <= distance <= self.BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y']), anchor=a['rope'][0], band=list(self.BAND), in_band=True)


class SwitchbackV3CompleteChecks:
    """Layout-v3 Switchback S02-03/04, section exit and drag-zone fall recovery (TASK-551).

    Same proof kind as SwitchbackV3Checks: the real S01 v3 exit settled pose from a base-start
    real-input S01 run, restored once as a labeled initial placement, then production trusted
    input and physics (the S02-01/02 nominal inputs first). Shared by Task551Tests and by the
    re-specced Task509Tests (same cases, task-local evidence).
    """
    SB = SwitchbackV3Checks
    S02_01_V3, S02_02_V3, S02_V3_BAND = SB.S02_01_V3, SB.S02_02_V3, SB.S02_V3_BAND
    S02_01_EXIT, S02_02_EXIT, S02_02_TICKS = SB.S02_01_EXIT, SB.S02_02_EXIT, SB.S02_02_TICKS
    S01_V3_ROUTE, S01_V3_TICKS, S01_V3_SETTLE, S01_EXIT_DRAG = SB.S01_V3_ROUTE, SB.S01_V3_TICKS, SB.S01_V3_SETTLE, SB.S01_EXIT_DRAG
    S02_V3_MOVERS = SB.S02_V3_MOVERS
    GALLERY, CROWN = (5540,-4705), (6060,-5615)
    S02_03_V3 = [(345,'mousedown',*GALLERY),(455,'mouseup',*GALLERY)]
    S02_04_V3 = [(560,'mousedown',*CROWN),(622,'mouseup',*CROWN)]
    ROUTE_S02_V3 = S02_01_V3+S02_02_V3+S02_03_V3+S02_04_V3
    # S02-03 ends in flight left over the canopy after the east-wall reversal (the manifest
    # exit box); S02-04 lands on the exit ledge inside the exit drag zone (LAND) and the full
    # traversal settles there (SETTLE = the manifest exit box).
    S02_03_EXIT = dict(x=[5500,5700], y=[-4860,-4760], speedX=[-1,-.6], speedY=[-.4,.1])
    LAND_S02 = dict(x=[5640,6160], y=[-5000,-4860], speedX=[-.001,.001], speedY=[-1,1])
    SETTLE_S02 = dict(x=[5640,6160], y=[-4890,-4860], speedX=[-.001,.001], speedY=[-.05,.05])
    S02_03_TICKS, S02_04_TICKS, S02_FULL_TICKS = 555, 1050, 1750
    S02_EXIT_DRAG = dict(left=5620, right=6330, top=-5260, bottom=-4820)
    # Naturally mistimed S02-04: the crown hook is released after 60 ticks instead of 62. The
    # arc misses the crown-hook top, carries past the exit ledge, drops through the S02 and S01 exit
    # drag zones and settles on the S01 exit pad; a blue hoist pull (east-wall and canopy-underside
    # bounces) and a swing from the green canopy's west end rejoin the route at the bulkhead
    # rebound (S02-02 exit box). The hoist press is phase-matched to the nominal one (240-tick period).
    REJOIN_S02 = [(1685,'mousedown',6140,-3670),(1805,'mouseup',6140,-3670),(1886,'mousedown',5000,-4600),(1948,'mouseup',5000,-4600)]
    FALL_S02 = S02_01_V3+S02_02_V3+S02_03_V3+[(560,'mousedown',*CROWN),(620,'mouseup',*CROWN)]+REJOIN_S02
    FALL_S02_TICKS, REJOIN_S02_TICK = 2030, 1685
    report = FoundationsV3Checks.report
    s01_v3_exit = SB.s01_v3_exit
    run_v3 = SB.run_v3
    reach_s02 = SB.reach_s02
    s02_kinds = SB.s02_kinds
    bounce_at = SB.bounce_at
    bounds_v3 = staticmethod(SB.bounds_v3)
    inside = staticmethod(FoundationsV3CompleteChecks.inside)
    in_box = staticmethod(FoundationsV3CompleteChecks.in_box)
    NOMINAL_KINDS = [('acquisition','S02-hoist'),('release','S02-hoist'),('bounce','S02-canopy'),
        ('acquisition','S02-lift'),('release','S02-lift'),('bounce','S02-bulkhead'),
        ('acquisition','S02-gallery-hook'),('bounce','S02-east-wall'),('release','S02-gallery-hook')]

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']; s02 = m['sections'][1]
        self.assertEqual((s02['designVersion'], s02['status']), (3, 'built'))
        self.assertNotIn('solidExceptions', s02)
        enc = m['encounters'][4:8]
        self.assertEqual([e['status'] for e in enc], ['built']*4)
        # Since TASK-553 the v3 Viaduct starts on the v3 S02 exit ledge, so the S03 entrance is built.
        self.assertEqual([c['status'] for c in m['connectors'][4:9]], ['built']*5)
        rec = m['recoveries'][1]
        self.assertEqual((rec['id'], rec['from'], rec['status'], rec['rejoin']), ('S02-fall', 'S02-04', 'built', 'S02-02'))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S02-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S02-')}
        self.assertEqual(set(movers), set(self.S02_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        for x in V3_S02_TASK551_ADDED:
            self.assertEqual(roles[x], 'yellow drag' if x == 'S02-exit-drag' else 'green bounce', x)
        box = lambda e: self.bounds_v3(e)
        self.assertEqual(box(by_id['S02-exit-drag']), self.S02_EXIT_DRAG)
        for a, b in zip(enc, enc[1:]):
            self.assertEqual(b['start']['from'], a['id'])
        for e in enc:
            self.assertTrue(any(roles.get(x) == 'green bounce' for x in e['elements']), e['id'])
        self.assertEqual([e['id'] for e in enc if any(x in movers for x in e['elements'])], ['S02-01','S02-02'])
        self.assertEqual(enc[1]['exit'], dict(left=4950,right=5150,top=-3880,bottom=-3760))
        self.assertEqual(enc[2]['exit'], dict(left=5500,right=5700,top=-4860,bottom=-4760))
        # The S02 exit is the green exit ledge inside the exit drag zone; the exit box sits on its top.
        ledge, zone, exit_box = box(by_id['S02-exit-ledge']), self.S02_EXIT_DRAG, enc[3]['exit']
        self.assertTrue(zone['left'] <= ledge['left'] and ledge['right'] <= zone['right'] and zone['top'] < ledge['top'] < zone['bottom'])
        self.assertEqual(exit_box, dict(left=5640,right=6160,top=-4890,bottom=-4860))
        self.assertEqual((exit_box['left'], exit_box['right'], exit_box['bottom']), (ledge['left'], ledge['right'], ledge['top']))
        self.assertEqual([self.SETTLE_S02[k] for k in ('x','y')], [[exit_box['left'],exit_box['right']],[exit_box['top'],exit_box['bottom']]])
        sec = r['report']['sections'][1]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S02', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('left', 'left'))
        self.assertLess(direction['exitX'], direction['entryX'])
        self.assertEqual(sec['rules']['graySolid']['measured']['staticSolids'], [])
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S02-01','S02-02'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S02_V3_BAND))
        self.assertEqual([g['id'] for g in gaps], ['S02-01-hoist','S02-02-lift','S02-03-gallery','S02-04-crown'])
        for g in gaps:
            self.assertTrue(self.S02_V3_BAND[0] <= g['distance'] <= self.S02_V3_BAND[1], g)
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], ['S02-01-short','S02-02-missed','S02-02-rebound','S02-03-short','S02-04-overshoot'])
        self.assertEqual(sorted({f['encounter'] for f in falls}), ['S02-01','S02-02','S02-03','S02-04'])
        under = {}
        for f in falls:
            # Each miss lands on a green S01 route bouncer through at least one drag zone.
            self.assertTrue(f['firstBouncer'].startswith('S01-') and by_id[f['firstBouncer']]['role'] == 'bounce', f)
            self.assertTrue(f['dragZones'], f)
            for d in f['dragZones']:
                b = box(by_id[d])
                # Directly below: the zone spans the fall column and lies between the point and the bouncer.
                self.assertTrue(b['left'] < f['x']-18 and f['x']+18 < b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, d))
            under[f['id']] = dict(x=f['x'], y=f['y'], dragZones=f['dragZones'], firstBouncer=f['firstBouncer'], firstBouncerTop=f['firstBouncerTop'])
        self.assertEqual(sorted(under['S02-04-overshoot']['dragZones']), ['S01-exit-drag','S02-exit-drag'])
        self.assertEqual(under['S02-04-overshoot']['firstBouncer'], 'S01-exit-pad')
        # Since TASK-553 the S03-01-short fall point also drops into it; only the S02 ones are pinned here.
        self.assertEqual([dict(id=d['id'], fallPoints=[p for p in d['fallPoints'] if p.startswith('S02-')])
                          for d in sec['rules']['strayDrag']['measured']['dragZones']], [dict(id='S02-exit-drag', fallPoints=['S02-04-overshoot'])])
        self.assertEqual(r['report']['v3'][:2], ['S01','S02'])
        self.assertFalse(r['report']['failed'])
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=[e['id'] for e in enc], direction=direction,
            gray_solid_count=0, gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps}, fall_points_over_drag_zones=under,
            every_fall_point_has_drag_zone_below=True, drag_zones_only_under_fall_points=True,
            s02_drag_zones=sec['rules']['strayDrag']['measured']['dragZones']))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s02, encounters=enc,
            connectors=m['connectors'][4:9], recovery=rec, elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True,
            direction=direction, exit=dict(ledge='S02-exit-ledge', ledge_box=ledge, drag_zone='S02-exit-drag', drag_box=zone, exit_box=exit_box),
            fall_points=under, task551_added=list(V3_S02_TASK551_ADDED),
            kept_v2_references={'S02-landing':'green; v2 S03-02 fall-line landing', 'S02-exit-pad':'green; v2 S03-01 start reference'}))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1280" viewBox="3250 -5950 3400 3400" style="background:#111827">']
        for e in sorted(elements, key=lambda e: e['role'] != 'drag'):
            if not e['id'].startswith('S01-') or e['id'] in ('S01-floor',): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.2' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>'
                         f'<text x="{box(e)["left"]+5}" y="{box(e)["bottom"]+34}" fill="#9ca3af" font-size="30">{e["id"]}</text>')
        for e in sorted(own, key=lambda e: e['role'] != 'drag'):
            if e['id'] in ('S02-landing','S02-exit-pad'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            op = ' fill-opacity="0.3"' if e['role'] == 'drag' else ''
            b = box(e)
            parts.append(f'<polygon points="{pts}" fill="{colors[roles[e["id"]]]}"{op} stroke="white" stroke-width="3"/>'
                         f'<text x="{b["left"]}" y="{b["top"]-12 if e["role"] != "drag" else b["top"]+40}" fill="white" font-size="32">{e["id"]}</text>')
        for g in s02['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="5" stroke-dasharray="14,10"/>')
        for f in falls:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="{min(f["firstBouncerTop"], -2660)}" stroke="#fb923c" stroke-width="4" stroke-dasharray="5,12"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="16" fill="#fb923c"/><text x="{f["x"]-260}" y="{f["y"]-10}" fill="#fb923c" font-size="30">{f["id"]}</text>')
        for e in enc:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="6"/>')
        parts.append('<circle cx="6373.4" cy="-2711.1" r="22" fill="#ff7a1a"/>')
        for i, t in enumerate(['S02 Switchback layout v3 complete (direction left, zero gray solids): hoist -> canopy -> lift -> bulkhead',
                '-> green gallery hook + east wall reversal -> green crown hook -> green exit ledge inside the yellow exit drag zone',
                'Gaps (yellow) %s of 1080; orange = fall points over drag zones onto green S01 bouncers; pink = exit boxes'
                % '/'.join(str(round(g['distance'])) for g in gaps)]):
            parts.append(f'<text x="3330" y="{-5890+i*50}" fill="#67e8f9" font-size="40">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=dict(width=1280, height=1280)); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S02 built 4/4 designVersion 3; gray solids 0; direction left', direction['entryX'], '->', direction['exitX'],
              '; all 7 v3 rules pass; gaps', [round(g['distance'],1) for g in gaps], '; fall points', list(under),
              'each over', sorted({d for f in falls for d in f['dragZones']}), 'onto green S01 bouncers; exit ledge inside S02-exit-drag; overview.png')

    def test_02_s02_03_nominal(self):
        trace, players, mech, result = self.run_v3('S02-03', self.S02_01_V3+self.S02_02_V3+self.S02_03_V3,
                                                   self.S02_03_TICKS, self.S02_03_EXIT)
        self.assertEqual(self.s02_kinds(mech), self.NOMINAL_KINDS)
        start = players[self.S02_02_TICKS]
        self.assertTrue(self.inside(start, self.S02_02_EXIT), start)
        gallery = next(e for e in mech if e['type']=='acquisition' and e['element']=='S02-gallery-hook')
        self.assertGreater(gallery['tick'], self.S02_02_TICKS)
        bounce, before, after = self.bounce_at(trace, 'S02-east-wall')
        # Lateral reversal: rightward into the east wall, leftward and still climbing after it.
        self.assertGreater(before['speedX'], 0); self.assertLess(after['speedX'], 0); self.assertLess(after['speedY'], 0)
        reach = self.reach_s02(players, mech, 345, 'S02-gallery-hook')
        result.update(encounter='S02-03', segmented_from='S02-02 exit at tick 330 of the same run (no further placement)',
            s02_02_exit_at_tick_330=start, acquisition_reach=reach, east_wall_reversal=dict(tick=bounce['tick'], before=before, after=after))
        self.evidence.write('encounters/S02-03/result.json', result)
        print('PASS S02-03: from the S02-02 exit at tick 330; green gallery hook', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; east-wall reversal at tick', bounce['tick'], 'vx', round(before['speedX'],2), '->',
              round(after['speedX'],2), '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def landing_s02(self, trace, players, mech):
        land = next(e for e in mech if e['type']=='bounce' and e['element']=='S02-exit-ledge')
        nxt = next((e['tick'] for e in mech if e['type']=='bounce' and e['element']=='S02-exit-ledge' and e['tick'] > land['tick']), len(players)-1)
        peak = min(p['y'] for p in players[land['tick']:nxt])
        for t in range(land['tick'], len(players)):
            self.assertTrue(self.in_box(players[t], self.S02_EXIT_DRAG), (t, players[t]))
            self.assertLess(abs(players[t]['speedX']), .01)
        self.assertGreater(peak - players[0]['radius'], self.S02_EXIT_DRAG['top'])
        before = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land['tick'])['before']['simulation']['player']
        entry = next(t for t in range(len(players)) if t > 560 and self.in_box(players[t], self.S02_EXIT_DRAG))
        return dict(tick=land['tick'], before=before, after=land['player'], first_rebound_peak_y=peak,
            first_rebound_inside_exit_drag=True, exit_drag=self.S02_EXIT_DRAG, drag_entry_tick=entry,
            drag_entry_from_above=players[entry-1]['y'] < self.S02_EXIT_DRAG['top'])

    def test_03_s02_04_nominal(self):
        trace, players, mech, result = self.run_v3('S02-04', self.ROUTE_S02_V3, self.S02_04_TICKS, self.LAND_S02, density_until=1000)
        kinds = self.s02_kinds(mech)
        self.assertEqual(kinds[:len(self.NOMINAL_KINDS)], self.NOMINAL_KINDS)
        rest = kinds[len(self.NOMINAL_KINDS):]
        self.assertEqual(rest[:5], [('acquisition','S02-crown-hook'),('release','S02-crown-hook'),('bounce','S02-crown-hook'),
                                    ('bounce','S02-east-wall'),('bounce','S02-exit-ledge')])
        self.assertEqual(set(rest[4:]), {('bounce','S02-exit-ledge')})
        start = players[self.S02_03_TICKS]
        self.assertTrue(self.inside(start, self.S02_03_EXIT), start)
        reach = self.reach_s02(players, mech, 560, 'S02-crown-hook')
        land = self.landing_s02(trace, players, mech)
        self.assertTrue(land['drag_entry_from_above'])
        self.assertLessEqual(land['tick'], 1000)
        crown = next(e for e in mech if e['type']=='bounce' and e['element']=='S02-crown-hook')
        wall = next(e for e in mech if e['type']=='bounce' and e['element']=='S02-east-wall' and e['tick'] > crown['tick'])
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules.setdefault('trace_measured_reach', {})['S02-crown-hook'] = reach
            self.evidence.write('rules.json', rules)
        result.update(encounter='S02-04', segmented_from='S02-03 exit at tick 555 of the same run (no further placement)',
            s02_03_exit_at_tick_555=start, acquisition_reach=reach, crown_hook_top_bounce=dict(tick=crown['tick'], player=crown['player']),
            east_wall_bounce=dict(tick=wall['tick'], player=wall['player']),
            exit_ledge_landing=land)
        self.evidence.write('encounters/S02-04/result.json', result)
        print('PASS S02-04: from the S02-03 exit at tick 555; green crown hook', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; crown-hook top bounce tick', crown['tick'], '; east-wall bounce tick', wall['tick'], '; drops into S02-exit-drag from above at tick',
              land['drag_entry_tick'], 'and lands on the green exit ledge at tick', land['tick'], '; final',
              {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')}, '; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_04_full_traversal(self):
        trace, players, mech, result = self.run_v3('S02-full', self.ROUTE_S02_V3, self.S02_FULL_TICKS, self.SETTLE_S02, density_until=1000)
        self.assertEqual([e['element'] for e in mech if e['type']=='acquisition'],
                         ['S02-hoist','S02-lift','S02-gallery-hook','S02-crown-hook'])
        exits = {}
        for name, tick, bounds in (('S02-01',SwitchbackV3Checks.S02_01_TICKS,self.S02_01_EXIT),('S02-02',self.S02_02_TICKS,self.S02_02_EXIT),
                                   ('S02-03',self.S02_03_TICKS,self.S02_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        touched = {e['element'] for e in mech}
        self.assertFalse({x for x in touched if x and x.startswith('S01-')} - {'S01-exit-pad'}, touched)
        land = self.landing_s02(trace, players, mech)
        settle = next(t for t in range(land['tick'], self.S02_FULL_TICKS+1)
                      if all(self.inside(players[u], self.SETTLE_S02) for u in range(t, self.S02_FULL_TICKS+1)))
        self.assertLessEqual(settle, 1600)
        tail = players[settle:]
        exits['S02-04'] = dict(tick=settle, player=players[settle], box=self.SETTLE_S02)
        reaches = [self.reach_s02(players, mech, t, el) for t, el in ((5,'S02-hoist'),(230,'S02-lift'),(345,'S02-gallery-hook'),(560,'S02-crown-hook'))]
        result.update(encounter='S02 full traversal', encounter_exits=exits, exit_ledge_landing=land,
            section_exit=dict(element='S02-exit-ledge', drag_zone='S02-exit-drag', settle_tick=settle,
                settled_ticks=len(tail), settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[-1], settle_box=self.SETTLE_S02, inside_exit_drag=True),
            section_exit_reached=True, settled_at_section_exit=True, s01_contacts_after_start=False, reaches=reaches)
        self.evidence.write('encounters/S02-full/result.json', result)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules.setdefault('trace_measured_reach', {}).update({x['element']:x for x in reaches})
            self.evidence.write('rules.json', rules)
        print('PASS full S02: from the real S01 v3 exit pose; exits', {k:v['tick'] for k,v in exits.items()}, '; reaches',
              [round(x['distance'],1) for x in reaches], '; exit ledge landing tick', land['tick'], '; settled from tick', settle,
              'for', len(tail), 'ticks at', {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')},
              'inside S02-exit-drag; identical replay; trusted input')

    def test_05_fall_through_drag_and_rejoin(self):
        trace, players, mech, result = self.run_v3('fall', self.FALL_S02, self.FALL_S02_TICKS, self.S02_02_EXIT, density_until=620)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S02-crown-hook')
        self.assertEqual(release['tick'], 620)
        pad = [e for e in mech if e['type']=='bounce' and e['element']=='S01-exit-pad' and e['tick'] > release['tick']]
        self.assertTrue(pad)
        land = pad[0]['tick']
        self.assertNotIn('S02-exit-ledge', {e['element'] for e in mech if release['tick'] < e['tick'] < self.REJOIN_S02_TICK})
        apex_tick = min(range(release['tick'], land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        zones = {}
        for zid, z in (('S02-exit-drag', self.S02_EXIT_DRAG), ('S01-exit-drag', self.S01_EXIT_DRAG)):
            ticks = [t for t in range(release['tick'], land+1) if self.in_box(players[t], z)]
            self.assertTrue(ticks, zid)
            entry, leave = ticks[0], ticks[-1]
            before, after = players[entry-1], players[leave]
            ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, leave) if abs(players[t]['speedX']) > 1e-9][:8]
            self.assertTrue(all(abs(x-.8) < 1e-9 for x in ratios), (zid, ratios))
            zones[zid] = dict(box=z, entry_tick=entry, last_tick_inside=leave,
                before=dict(tick=entry-1, speedX=before['speedX'], speedY=before['speedY'], x=before['x'], y=before['y']),
                after=dict(tick=leave, speedX=after['speedX'], speedY=after['speedY'], x=after['x'], y=after['y']),
                per_tick_vx_ratio_airborne=ratios)
        s02z, s01z = zones['S02-exit-drag'], zones['S01-exit-drag']
        # The S02 exit drag zone kills the horizontal speed: the drop below it is a vertical column.
        self.assertGreater(abs(s02z['before']['speedX']), .3)
        self.assertLess(abs(s02z['after']['speedX']), 1e-3)
        column = [players[t]['x'] for t in range(s02z['last_tick_inside'], land+1)]
        self.assertLess(max(column)-min(column), 1)
        fall_x = column[-1]
        self.assertLess(abs(fall_x - 6230), 18)
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_pad = contact['before']['simulation']['player']
        self.assertLess(at_pad['speedY'], s01z['before']['speedY'])
        self.assertTrue(self.in_box(at_pad, self.S01_EXIT_DRAG))
        rest_y = pad[0]['player']['y']
        fall_height = rest_y - apex['y']
        bounces = [e for e in pad if e['tick'] < self.REJOIN_S02_TICK]
        peaks = []
        for a, b in zip(bounces, bounces[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_S02_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        # Settled on the green S01 exit pad inside the S01 exit drag zone before the rejoin press.
        window = players[self.REJOIN_S02_TICK-100:self.REJOIN_S02_TICK]
        self.assertTrue(all(abs(p['speedX']) < 1e-6 and self.in_box(p, self.S01_EXIT_DRAG) for p in window))
        self.assertLess(max(p['y'] for p in window) - min(p['y'] for p in window), 15)
        self.assertLess(max(abs(p['speedY']) for p in window), .2)
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_S02_TICK]
        self.assertEqual(len(rejoin_inputs), 4)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after = [k for k in self.s02_kinds([e for e in mech if e['tick'] >= self.REJOIN_S02_TICK])]
        self.assertEqual(after, [('acquisition','S02-hoist'),('release','S02-hoist'),('bounce','S02-east-wall'),('bounce','S02-canopy'),
                                 ('acquisition','S02-canopy'),('release','S02-canopy'),('bounce','S02-bulkhead')])
        hoist = next(e for e in mech if e['type']=='acquisition' and e['element']=='S02-hoist' and e['tick'] >= self.REJOIN_S02_TICK)
        swing = next(e for e in mech if e['type']=='acquisition' and e['element']=='S02-canopy' and e['tick'] >= self.REJOIN_S02_TICK)
        bulkhead = [e for e in mech if e['type']=='bounce' and e['element']=='S02-bulkhead'][-1]
        fall = dict(scenario='naturally mistimed S02-04 release: crown hook held 60 ticks instead of 62; physical fall; no relocation '
                             'after the labeled S01-exit start placement',
            release=dict(tick=release['tick'], element='S02-crown-hook', nominal_release_tick=622, player=release['player'],
                         release_height_y=release['player']['y']),
            fall_point=dict(id='S02-04-overshoot', declared_x=6230, measured_column_x=fall_x),
            bounces_before_drop=[dict(tick=e['tick'], element=e['element']) for e in mech
                                 if e['type']=='bounce' and release['tick'] < e['tick'] < s02z['entry_tick']],
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='S01 exit pad bounce rest y minus the apex y after the release',
            drag_zones=dict(zones, vertical_damping_per_tick=0.985),
            s01_bouncer=dict(element='S01-exit-pad', first_bounce_tick=land, before=at_pad, rest_y=rest_y, inside='S01-exit-drag'),
            bounce_peaks=peaks, first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            settled=dict(window=[self.REJOIN_S02_TICK-100, self.REJOIN_S02_TICK-1], max_abs_speedX=max(abs(p['speedX']) for p in window),
                max_abs_speedY=max(abs(p['speedY']) for p in window), y_range=[min(p['y'] for p in window), max(p['y'] for p in window)],
                inside_drag_zone='S01-exit-drag', on='S01-exit-pad'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                hoist_acquisition=dict(tick=hoist['tick'], anchor=hoist['rope'][0], player=hoist['player']),
                canopy_swing_acquisition=dict(tick=swing['tick'], anchor=swing['rope'][0], player=swing['player']),
                bulkhead_bounce=dict(tick=bulkhead['tick'], player=bulkhead['player']),
                final=players[-1], encounter_rejoined='S02-02 exit box (S02-03 start)', exit_box=self.S02_02_EXIT))
        result.update(fall)
        self.evidence.write('encounters/fall/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed crown release tick 620 at y', round(release['player']['y'],1), '; apex', round(apex['y'],1),
              '; S02-exit-drag vx/vy', round(s02z['before']['speedX'],3), round(s02z['before']['speedY'],3), '->',
              round(s02z['after']['speedX'],5), round(s02z['after']['speedY'],3), '; column x', round(fall_x,1),
              '; S01-exit-drag vy', round(s01z['before']['speedY'],3), '->', round(at_pad['speedY'],3), '; S01 exit pad bounce peaks',
              [round(p['fraction'],3) for p in peaks[:5]], 'of', round(fall_height,1), '; settled; input-only rejoin: hoist tick', hoist['tick'],
              ', canopy swing tick', swing['tick'], ', bulkhead tick', bulkhead['tick'], ', S02-02 exit box at tick', self.FALL_S02_TICKS)


class Task509Tests(SwitchbackV3CompleteChecks, unittest.TestCase):
    """Switchback S02-03/04, exit and fall recovery, re-specced by TASK-551 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, all shared with Task551Tests via SwitchbackV3CompleteChecks):
    test_01_geometry_and_rules: v2 rules, rest-pad exceptions, 459-486 gaps, fall lines through
    S02-fall-drag onto the S01 entry pad -> v3 rules, zero gray solids, 918-972 gaps, every fall
    point over a drag zone onto a green S01 bouncer, green exit ledge inside S02-exit-drag.
    test_02_s02_03_nominal: green crest hook over the bulkhead onto the braked ledge -> green
    gallery hook off the bulkhead rebound into the green east-wall lateral reversal.
    test_03_s02_04_nominal: blue trolley onto the S02-exit-pad rest -> green crown hook climb-out,
    crown-hook top bounce and drop into S02-exit-drag onto the green exit ledge.
    test_04_full_traversal: v2 S01-exit rest to the S02-exit-pad rest -> real S01 v3 exit pose to
    a settle on the green exit ledge. test_05_fall_through_drag_and_rejoin: mistimed lift onto
    the S01 entry pad + hoist rejoin -> mistimed crown release through S02-exit-drag and
    S01-exit-drag onto the green S01 exit pad + hoist/lift rejoin at the bulkhead rebound.
    test_06_source_hashes is unchanged. The v2 constants and helpers below (at_rest, bounds,
    brake_ticks, BOXES, routes) stay for the later v2 suites (Task510-514).
    """
    task_id = 'TASK-509'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    test_06_source_hashes = V1Task465.test_03_source_hashes
    S01_ROUTE = Task508Tests.S01_ROUTE
    CREST, TROLLEY = (2960,-2550), (2260,-2905)
    S02_01, S02_02 = Task508Tests.S02_01, Task508Tests.S02_02
    S02_03 = [(425,'mousedown',*CREST),(466,'mouseup',*CREST)]
    S02_04 = [(765,'mousedown',*TROLLEY),(811,'mouseup',*TROLLEY)]
    NOMINAL = S02_01+S02_02+S02_03+S02_04
    # Mistimed S02-02: the lift is released after 60 ticks instead of 74. The rejoin is a
    # later hoist press from the S01 entry pad rest, pulled through to the loading pad.
    REJOIN = [(780,'mousedown',2480,-316),(850,'mouseup',2480,-316)]
    FALL = S02_01+[(160,'mousedown',3247,-2240),(220,'mouseup',3247,-2240)]+REJOIN
    MOVERS = ('S02-shuttle','S02-lift','S02-trolley','S01-hoist')
    DRAG = dict(id='S02-fall-drag', left=1990, right=2140, top=-1500, bottom=18)
    BRAKE = dict(id='S02-ledge-brake', left=2310, right=2510, top=-2560, bottom=-2480)
    BAND = (459, 486)
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])
    BOXES = {'S01-04':dict(x=[4209.1,4209.3],y=[-1631,-1630],**REST),
             'S02-01':dict(x=[3460,3620],y=[-1891,-1890],**REST),
             'S02-02':dict(x=[2987,3147],y=[-2111,-2110],**REST),
             'S02-03':dict(x=[2350,2510],y=[-2491,-2490],**REST),
             'S02-04':dict(x=[2040,2200],y=[-2691,-2690],**REST),
             'S01-entry':dict(x=[2060,2149],y=[7.1,7.3],**REST),
             'S01-02':dict(x=[3500,3650],y=[-361,-360],**REST)}

    def at_rest(self, player, name):
        return all(b[0] <= player[k] <= b[1] for k, b in self.BOXES[name].items())

    def bounds(self, e):
        return (e['x']+min(p['x'] for p in e['points']), e['x']+max(p['x'] for p in e['points']),
                e['y']+min(p['y'] for p in e['points']), e['y']+max(p['y'] for p in e['points']))

    def brake_ticks(self, players, z):
        r = players[0]['radius']
        def inside(p):
            dx = max(z['left']-p['x'], 0, p['x']-z['right']); dy = max(z['top']-p['y'], 0, p['y']-z['bottom'])
            return dx*dx + dy*dy < r*r
        return [t for t, p in enumerate(players) if inside(p)]


class SwitchbackV3ToleranceChecks(FoundationsV3ToleranceChecks):
    """Layout-v3 Switchback (S02) tolerance on desktop 1280x720 and touch 844x390 (TASK-552).

    Proof kind (as TASK-550/551): the real S01 v3 exit settled pose of a base-start real-input S01
    run is restored once as a labeled initial placement (initial_snapshot); production trusted
    mouse/touch input and physics run from there. An attempt on encounter k replays the S02 route
    up to k: the encounter's inputs carry the variant, the earlier encounters keep their nominal
    inputs. S02 has no rest between encounters (every exit is in flight), so S02-01..03 are judged
    at their declared manifest exit boxes (position at the nominal exit tick 225/330/555) and S02-04
    at the S02 section exit (settled on the green exit ledge inside S02-exit-drag at tick 1650).
    check_s02_v3_mechanics requires the encounter's own mechanic, the S02 anchors in route order
    and no fall back onto an S01 bouncer. Shared by Task552Tests and the re-specced Task510Tests.
    """
    CB = SwitchbackV3CompleteChecks
    SB = SwitchbackV3Checks
    # TASK-552 tolerance nominal for S02-04: the crown hook is released at 626 (hold 66) instead
    # of the TASK-551 622 (hold 62). Touch aim is quantized to 7.4 world units per CSS pixel (desktop
    # 4), which leaves the touch gallery flight ~60 px further left at tick 555; the 622 release then
    # overshoots the exit ledge on touch (TASK-551 hold 58-60 hole). 626 lands on both viewports.
    S02_04_TOL = [(560,'mousedown',*CB.CROWN),(626,'mouseup',*CB.CROWN)]
    SEGMENTS = [CB.S02_01_V3, CB.S02_02_V3, CB.S02_03_V3, S02_04_TOL]
    V3_ENCOUNTERS = [('S02-01','blue hoist pull up out of S01-exit-drag, release into the green canopy bounce',0,SB.S02_01_TICKS),
                     ('S02-02','blue lift caught on the drop, release into the green bulkhead rebound to the right',SB.S02_01_TICKS,CB.S02_02_TICKS),
                     ('S02-03','green gallery hook caught in flight off the rebound, green east-wall lateral reversal to the left',CB.S02_02_TICKS,CB.S02_03_TICKS),
                     ('S02-04','green crown hook caught in flight, drop into S02-exit-drag onto the green exit ledge (S02 section exit)',CB.S02_03_TICKS,None)]
    # Judged exits: the mountain.js encounter exit boxes (position) at the nominal exit tick; S02-04
    # the TASK-551 settle box on the exit ledge. The stricter TASK-550/551 boxes (with speeds) are
    # asserted on the nominal attempts.
    S04_TICKS = 1650
    STRICT = {'S02-01':SB.S02_01_EXIT, 'S02-02':SB.S02_02_EXIT, 'S02-03':CB.S02_03_EXIT}
    # Mistimed releases, one per encounter, no further input afterwards (as TASK-549):
    # (encounter, release tick replacing the nominal one, nominal release tick, ticks, declared fall point).
    # S02-04 is an early crown release that overshoots the exit ledge; the touch gallery flight
    # differs (aim quantization), so its overshooting tick is 623 on touch (620 lands on the ledge).
    MISTIMED = [('S02-01',90,110,700,'S02-01-short'), ('S02-02',295,290,1000,'S02-02-rebound'),
                ('S02-03',400,455,1000,'S02-03-short'), ('S02-04',dict(desktop=620,touch=623),626,1300,'S02-04-overshoot')]
    V3_MOVERS = SB.S02_V3_MOVERS
    S01_V3_ROUTE, S01_V3_TICKS, S01_V3_SETTLE, S01_EXIT_DRAG = SB.S01_V3_ROUTE, SB.S01_V3_TICKS, SB.S01_V3_SETTLE, SB.S01_EXIT_DRAG
    open = V1Task465.open
    report = FoundationsV3Checks.report
    s01_v3_exit = SB.s01_v3_exit
    inside = staticmethod(FoundationsV3CompleteChecks.inside)
    in_box = staticmethod(FoundationsV3CompleteChecks.in_box)
    bounds_v3 = staticmethod(SB.bounds_v3)

    def exits(self):
        """Per encounter: (ticks, judged exit bounds, meaning), from the runtime manifest."""
        enc = {e['id']:e for e in self.report()['manifest']['encounters'][4:8]}
        out = {}
        for name, _, _, tick in self.V3_ENCOUNTERS:
            if tick:
                b = enc[name]['exit']
                out[name] = (tick, dict(x=[b['left'],b['right']], y=[b['top'],b['bottom']]),
                             f'inside the mountain.js {name} exit box at the nominal exit tick {tick}')
            else:
                out[name] = (self.S04_TICKS, self.CB.SETTLE_S02,
                             'settled on S02-exit-ledge inside S02-exit-drag (S02 section exit) at tick %d' % self.S04_TICKS)
        return out

    def variant_plan(self, index, delta=0, shift=0):
        """Nominal S02 route up to encounter `index`, with the variant on that encounter."""
        n = sum(len(s) for s in self.SEGMENTS[:index+1])
        return FoundationsV3ToleranceChecks.variant_plan(self, index, delta, shift)[:n]

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s02_v3_mechanics
        start = self.s01_v3_exit()
        self.assertTrue(self.inside(start['player'], self.S01_V3_SETTLE), start['player'])
        exits = self.exits()
        source = hashes()
        suite = dict(section='S02', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='isolated: one labeled initial placement (initial_snapshot) = the real S01 v3 exit settled pose of a base-start '
                       'real-input S01 run (encounters/S01-exit-start), then production trusted mouse/touch input and physics; an attempt '
                       'on encounter k carries the variant on k and TASK-550/551 nominal inputs on S02-01..k-1',
            initial_placement=type(self).v3_start_proof, browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exits={n: dict(ticks=t, box=b, meaning=w) for n, (t, b, w) in exits.items()},
            mechanics_check='tools/grapple_over_verify.py check_s02_v3_mechanics',
            nominal_note='S02-04 crown release 626 (TASK-551 test inputs: 622); see S02_04_TOL',
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal = [], {}
        for k, (name, mechanic, begin, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            ticks, bounds, meaning = exits[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), ticks, bounds, device, snapshot=start)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s02_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s02_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), (label, targets))
                        if exit_tick:
                            self.assertTrue(self.inside(players[exit_tick], self.STRICT[name]), (label, players[exit_tick]))
                            end = exit_tick
                        else:
                            end = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S02-exit-ledge')
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', begin, end)
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning),
                        outcome=f'{name} exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(LAYOUT_V3_DENSITY_CAP_TICKS = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','contact with S02-hoist/S02-lift'], cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal S02 run (0/225/330/555) to its manifest exit tick '
                   '(225/330/555) or, for S02-04, the exit-ledge landing; the settle on the exit ledge is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(start, exits['S02-04'])
        self.assertEqual(failures, [])
        print('PASS S02 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-crown negative control fails the exit')

    def negative_control(self, start, exit):
        from grapple_over_verify import hashes, check_s02_v3_mechanics
        # Named omission: the S02-04 crown-hook press/release left out; same placement, physics and
        # S02-01..03 inputs as every S02-04 attempt.
        ticks, bounds, meaning = exit
        plan = self.variant_plan(3)[:6]
        m = self.make_input(plan, ticks, bounds, snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s02_v3_mechanics('S02-04', trace, required=False)
        self.evidence.write('negative-control.json', dict(name='omitted crown hook: S02-04 S02-crown-hook press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning), unchanged_physics=True, source_hashes=hashes(),
            proof_kind='same labeled S01-exit placement, real mouse input, same S02-01..03 inputs as the S02-04 attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step,
            exit_ledge_contact='S02-exit-ledge' in [b['element'] for b in mechanics['bounces']], final_player=players[-1],
            scope='Without the crown catch the gallery flight never climbs to the exit ledge and the S02 section exit is missed.'))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S02-crown-hook', mechanics['acquisitions'])
        self.assertFalse(self.inside(players[-1], self.CB.SETTLE_S02))
        self.assertLess(step, 60)

    def test_02_mistimed_release_no_bounce_back(self):
        from grapple_over_verify import check_s02_v3_mechanics
        start = self.s01_v3_exit()
        elements = {e['id']:e for e in self.report()['manifest']['geometry']['elements']}
        zones = {k: self.bounds_v3(e) for k, e in elements.items() if e['role']=='drag' and k.startswith(('S01-','S02-'))}
        falls = {f['id']:f for f in self.report()['report']['sections'][1]['rules']['dragUnderFall']['measured']['fallPoints']}
        inzone = lambda p, b: b['left'] <= p['x'] <= b['right'] and b['top'] <= p['y'] <= b['bottom']
        rows = {}
        for k, (name, releases, nominal, ticks, fall_id) in enumerate(self.MISTIMED):
            segment = self.SEGMENTS[k]
            self.assertEqual(segment[1][0], nominal)
            for device in ('desktop','touch'):
                release = releases[device] if isinstance(releases, dict) else releases
                plan = [p for seg in self.SEGMENTS[:k] for p in seg]+[segment[0], (release,)+segment[1][1:]]
                m = self.make_input(plan, ticks, dict(y=[-1e9, 1e9]), device, snapshot=start)
                prefix = f'clips/fall-{name}-{device}'
                trace, success, reason = self.run_attempt(m, prefix, True)
                self.assertTrue(success, reason)
                self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                mech = check_s02_v3_mechanics(name, trace, required=False)
                anchor = mech['encounter']['anchor']
                rel = next(r for r in mech['releases'] if r['element']==anchor)
                self.assertEqual(rel['tick'], release)
                r_player = players[release]
                bounces = [e for e in trace['events'] if e['type']=='bounce' and e['tick'] > release]
                # The landing bouncer is the first S01 bouncer reached after the release (earlier
                # contacts are glances off S02 walls on the way down, listed in bounces_before_landing).
                s01 = [e for e in bounces if e['contact']['elementId'].startswith('S01-')]
                self.assertTrue(s01, name)
                landing = s01[0]; element = landing['contact']['elementId']; land = landing['tick']
                self.assertEqual(elements[element]['role'], 'bounce')
                crossed = {z: [t for t in range(release, land+1) if inzone(players[t], b)] for z, b in zones.items()}
                crossed = {z: ts for z, ts in crossed.items() if ts}
                self.assertTrue(crossed, name)
                # The landing is inside or directly below the last drag zone crossed.
                last = max(crossed, key=lambda z: crossed[z][-1])
                self.assertLessEqual(land - crossed[last][-1], 120, (name, last))
                rest_y = landing['after']['simulation']['player']['y']
                apex_tick = min(range(release, land), key=lambda t: players[t]['y'])
                second = next((e['tick'] for e in s01 if e['tick'] > land+1), ticks)
                peak_tick = min(range(land+1, second), key=lambda t: players[t]['y'])
                release_height = rest_y - r_player['y']
                peak_height = rest_y - players[peak_tick]['y']
                fall_height = rest_y - players[apex_tick]['y']
                self.assertGreater(release_height, 0, name)
                self.assertLessEqual(peak_height, .5*release_height, name)
                self.assertLessEqual(peak_height, .5*fall_height, name)
                targets = self.targets(trace, m['metadata']['viewport'])
                self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), targets)
                step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
                self.assertLess(step, 60)
                declared = falls[fall_id]
                glances = []
                for e in bounces:
                    if e['tick'] >= land: break
                    if not glances or glances[-1]['element'] != e['contact']['elementId']:
                        glances.append(dict(element=e['contact']['elementId'], tick=e['tick']))
                row = dict(encounter=name, device=device, viewport=m['metadata']['viewport'], anchor=anchor,
                    mistiming=f'{anchor} released at tick {release} instead of {nominal}; no further input',
                    input=prefix+'/input.json.gz', trace=prefix+'/trace.json', filmstrip=prefix+'/filmstrip.jpg',
                    release=dict(tick=release, player=r_player), landing_rest_y=rest_y,
                    release_height=release_height, release_height_definition='landing-bouncer bounce y minus player y at the release tick',
                    apex=dict(tick=apex_tick, y=players[apex_tick]['y']), fall_height_from_apex=fall_height,
                    bounces_before_landing=glances,
                    drag_zones_crossed=[dict(id=z, box=zones[z], ticks=[ts[0], ts[-1]], entry_player=players[ts[0]],
                        exit_player=players[ts[-1]]) for z, ts in sorted(crossed.items(), key=lambda x: x[1][0])],
                    declared_fall_point=dict(id=fall_id, x=declared['x'], dragZones=declared['dragZones'], firstBouncer=declared['firstBouncer']),
                    first_bounce=dict(element=element, tick=land, before=landing['before']['simulation']['player'],
                        after=landing['after']['simulation']['player']),
                    first_bounce_peak=dict(tick=peak_tick, y=players[peak_tick]['y'], height=peak_height,
                        fraction_of_release_height=peak_height/release_height, fraction_of_apex_fall=peak_height/fall_height),
                    at_most_half_of_release_height=True, max_tick_displacement=step, press_targets=targets, relocation=False)
                rows.setdefault(name, {})[device] = row
                print('PASS fall', name, device, ': release tick', release, 'y', round(r_player['y'],1), '; drag zones',
                      [d['id'] for d in row['drag_zones_crossed']], '; first S01 bounce', element, 'tick', land, '; first peak',
                      round(peak_height,1), '=', round(peak_height/release_height,3), 'of release height', round(release_height,1))
        self.evidence.write('no-bounce-back.json', dict(self.proof, rule='a mistimed release passes through the drag zone below '
            'it and its first bounce peaks at most 50% of the release height (i.e. at least 50% lower)',
            proof_kind='labeled S01-exit placement, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation',
            encounters=rows, passed=True))


class Task510Tests(SwitchbackV3ToleranceChecks, unittest.TestCase):
    """Switchback (S02) tolerance, re-specced by TASK-552 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, shared with Task552Tests via SwitchbackV3ToleranceChecks):
    test_01_tolerance_matrix: v2 S02-01..04 from restored v2 rest states (starts/trace.json), 180-tick
    density, mistimed-lift negative control -> v3 S02-01..04 from the labeled real S01 v3 exit pose,
    S02-01..03 judged at their mountain.js exit boxes and S02-04 at the exit-ledge settle, 254-tick
    density cap, omitted-crown negative control. test_02_full_traversal: the v3 full route is the
    nominal S02-04 attempt of test_01 (and Task551 test_04). test_03_drag_zone_fall_clips ->
    test_02_mistimed_release_no_bounce_back (one mistimed release per encounter through a drag zone
    onto a green S01 bouncer, desktop and touch). test_04_source_hashes is unchanged. The v2
    constants below stay for the later v2 suites (Task511 uses NOMINAL, Task512 uses S02_03).
    """
    task_id = 'TASK-510'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_04_source_hashes = V1Task465.test_03_source_hashes
    LEDGE = (2483,-2482)
    S02_03 = Task509Tests.S02_03+[(550,'mousedown',*LEDGE),(570,'mouseup',*LEDGE)]
    S02_04 = Task509Tests.S02_04
    NOMINAL = Task509Tests.S02_01+Task509Tests.S02_02+S02_03+S02_04


V2_S03_REVISION = '89f85be'
# What happened to every static v2 S03 solid in the layout-v3 rebuild (TASK-553).
V2_S03_DISPOSITION = {
    'S03-pier':('deleted','v2 S03-01 landing / S03-02 launch rest; the v3 S03-01 ends in flight off the green west pier'),
    'S03-far-deck':('deleted','v2 S03-02 landing / S03-03 launch rest; the v3 S03-02 ends in flight off the green east pier'),
    'S03-ledge':('deleted','v2 S03-03 landing / S03-04 launch rest; the v3 S03-03 starts from rest against the blue '
                 'shutter and the v3 S03-04 from the apex on the right map edge (TASK-554)'),
    'S03-exit-pad':('converted-to-bounce','Kept at (4600,-3830) as a green 150x55 bouncer only because the v2 Deflector Works '
                    'S04-01 encounter still starts on it; no v3 S03 route uses it')}
# The other v2 S03 elements (movers, bouncers, drag zones): deleted or id re-used by a new v3 element.
V2_S03_OTHER = {'S03-carriage':'deleted', 'S03-trolley':'deleted', 'S03-span-buffer':'deleted',
    'S03-crest-hook':'id re-used: new green hook (6330,-7500) 120x25 for the v3 S03-03 crest pull (TASK-554; moved by TASK-555 '
                     'from (6090,-7675), which was under the touch pause button)',
    'S03-ledge-brake':'deleted', 'S03-exit-brake':'deleted',
    'S03-lift':'id re-used: new blue x mover (6140,-6960) for the v3 S03-02 span lift',
    'S03-fall-drag':'id re-used: new drag zone (6360,-5800) 120x440 over the green lower bridge (S03-02-missed)'}
V3_S03_ADDED = ('S03-hoist','S03-west-pier','S03-east-pier','S03-lower-bridge',
    'S03-shutter','S03-exit-hook','S03-exit-ledge','S03-exit-drag')


class ViaductV3Checks:
    """Layout-v3 Broken Viaduct opening (S03-01/02) from the real S02 v3 exit settled pose (TASK-553).

    The start pose comes from one base-start real-input run of the v3 S01 route (TASK-548 inputs)
    followed by the v3 S02 route (TASK-551 inputs, shifted to tick 1495) that settles on the green
    S02 exit ledge; no placement is used for it. It is restored once as a labeled initial placement,
    then production trusted input and physics run. Not a continuous-completion claim.
    Shared by Task553Tests and the re-specced Task511Tests (same cases, task-local evidence).
    """
    S02_V3_ROUTE = FoundationsV3CompleteChecks.ROUTE_V3+[(t+1495, e, x, y) for t, e, x, y in SwitchbackV3CompleteChecks.ROUTE_S02_V3]
    S02_V3_TICKS = 1495+1750
    S02_V3_SETTLE = SwitchbackV3CompleteChecks.SETTLE_S02
    S02_EXIT_DRAG = SwitchbackV3CompleteChecks.S02_EXIT_DRAG
    S02_V3_ACQUIRED = ['S01-hoist','S01-lift','S01-gantry-hook','S01-crown-hook','S02-hoist','S02-lift','S02-gallery-hook','S02-crown-hook']
    HOIST_V3, LIFT_V3 = (5520,-5750), (6200,-6940)
    S03_01_V3 = [(5,'mousedown',*HOIST_V3),(120,'mouseup',*HOIST_V3)]
    S03_02_V3 = [(266,'mousedown',*LIFT_V3),(311,'mouseup',*LIFT_V3)]
    S03_V3_MOVERS = ('S03-hoist','S03-lift','S03-shutter')
    S03_V3_BAND = (918, 972)
    # Exit boxes (also the manifest encounter exits): rebounding right off the green west pier;
    # and rebounding left off the green east pier.
    S03_01_EXIT = dict(x=[5240,5360], y=[-6520,-6420], speedX=[.5,.9], speedY=[-.5,-.2])
    S03_02_EXIT = dict(x=[6150,6400], y=[-6820,-6720], speedX=[-2.1,-1.6], speedY=[-.4,0])
    S03_01_TICKS, S03_02_TICKS = 250, 360
    # TASK-554: S03-03 is judged at the apex on the right map edge (the S03-04 launch, tick 625);
    # S03-04 is the settled pose on the green exit ledge inside S03-exit-drag.
    S03_03_EXIT = dict(x=[6440,6480], y=[-7990,-7900], speedX=[-.01,.01], speedY=[-.3,.1])
    S03_04_EXIT = dict(x=[5960,6190], y=[-7800,-7770], speedX=[-.001,.001], speedY=[-.05,.05])
    # Every declared S03 fall point: (drag zones crossed by its column, first bouncer under it).
    S03_V3_FALLS = {'S03-01-short':(['S02-exit-drag'],'S02-exit-ledge'), 'S03-02-missed':(['S03-fall-drag'],'S03-lower-bridge'),
        'S03-03-early':(['S02-exit-drag'],'S02-exit-ledge'), 'S03-04-missed':(['S03-fall-drag'],'S03-lower-bridge'),
        'S03-04-overshoot':(['S03-exit-drag'],'S03-exit-ledge')}
    # Declared misses: a short hoist hold (70 ticks) drops back through S02-exit-drag onto the
    # green S02 exit ledge; no lift catch glances off the S02 east-wall top and drops along the
    # right map edge through S03-fall-drag onto the green lower bridge.
    S03_01_SHORT = [(5,'mousedown',*HOIST_V3),(75,'mouseup',*HOIST_V3)]
    S03_FALL_DRAG = dict(left=6360, right=6480, top=-5800, bottom=-5360)
    BRIDGE_SETTLE = dict(x=[6360,6480], y=[-5430,-5400], speedX=[-.001,.001], speedY=[-.05,.05])
    report = FoundationsV3Checks.report
    bounds_v3 = staticmethod(SwitchbackV3Checks.bounds_v3)
    inside = staticmethod(FoundationsV3CompleteChecks.inside)
    in_box = staticmethod(FoundationsV3CompleteChecks.in_box)

    def v2_s03(self):
        """The layout-v2 S03 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V2_S03_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[2], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, elements:m.geometry.elements.filter(e=>e.id.startsWith('S03-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S03-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S03-'))}}''', source)

    def s02_v3_exit(self):
        """Real S02 v3 exit settled pose: one base-start real-input run of the v3 S01 and S02 routes (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'v3_s02_start'): return type(self).v3_s02_start
        m = dict(metadata=metadata('base-start'), ticks=self.S02_V3_TICKS, expected_exit=self.S02_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.S02_V3_ROUTE],
            required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/S02-exit-start'
        self.evidence.write(prefix+'/input.json', m)
        setup = execute(m, self.browser, self.url, str(self.evidence.path(prefix)))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual([a for a in acquired if a != 'S01-entry-pad'], self.S02_V3_ACQUIRED)
        touched = sorted({(e.get('contact') or {}).get('elementId') for e in setup['events']} - {None})
        self.assertFalse([t for t in touched if t.startswith('S03-')], touched)
        self.evidence.write(prefix+'/trace.json', Task506Tests.compact(self, setup))
        settle = next(t for t in range(2500, self.S02_V3_TICKS+1)
                      if all(self.inside(p, self.S02_V3_SETTLE) for p in players[t:]))
        self.assertLessEqual(settle, 3150)
        start = setup['snapshots'][-1]['state']['simulation']
        self.assertTrue(self.in_box(start['player'], self.S02_EXIT_DRAG))
        self.assertEqual((round(start['player']['x'],1), round(start['player']['y'],1)), (5955.4, -4870.9))
        # Clearance of the whole S01+S02 v3 flight from the new S03 route colliders.
        m2 = self.report()['manifest']
        travel = {v['element']:v for v in m2['geometry']['movers']}
        clearance = {}
        for e in m2['geometry']['elements']:
            if not e['id'].startswith('S03-') or e['role'] == 'drag' or e['id'] == 'S03-exit-pad': continue
            b = self.bounds_v3(e, travel.get(e['id']))
            gap = min(math.hypot(max(b['left']-p['x'], 0, p['x']-b['right']), max(b['top']-p['y'], 0, p['y']-b['bottom']))
                      for p in players)
            clearance[e['id']] = gap - players[0]['radius']
            self.assertGreater(clearance[e['id']], 50, (e['id'], clearance))
        type(self).v3_s02_start = start
        type(self).v3_s02_start_proof = dict(kind='base-start v3 S01 route (TASK-548 inputs) then v3 S02 route (TASK-551 inputs '
            'from tick 1495), real mouse input, no placement', inputs=m['inputs'], acquisitions=acquired,
            settled_in_exit_box_from_tick=settle, settle_box=self.S02_V3_SETTLE, final_tick=self.S02_V3_TICKS,
            player=start['player'], inside_S02_exit_drag=True, snapshot_sha256=setup['snapshots'][-1]['sha256'],
            full_trace_sha256=state_hash(setup), trace=prefix+'/trace.json', s03_element_contacts=[],
            s01_s02_flight_clearance_to_s03_route_elements=clearance)
        self.evidence.write(prefix+'/result.json', dict(passed=True, **type(self).v3_s02_start_proof))
        return start

    def run_s03(self, name, plan, ticks, bounds, density_until=None, folder='encounters'):
        """Labeled placement of the real S02 v3 exit pose, then trusted input; identical replay."""
        from grapple_over_verify import metadata, execute, check_trace
        start = self.s02_v3_exit()
        m = dict(metadata=metadata('isolated'), inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=['acquisition','release','bounce'], initial_snapshot=start)
        m['metadata']['compact_contacts'] = True
        prefix = folder+'/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=True)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, Task506Tests.compact(self, t))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        self.assertTrue(self.inside(players[0], self.S02_V3_SETTLE), players[0])
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce') or (e['type']=='contact' and element in self.S03_V3_MOVERS):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    mover=element in self.S03_V3_MOVERS, player=e['after']['simulation']['player'], rope=e['after']['rope']))
        # Longest stretch without an acquisition, bounce or mover contact (LAYOUT_V3_DENSITY_CAP_TICKS).
        until = ticks if density_until is None else density_until
        marks = sorted({0, until, *[x['tick'] for x in mechanics if x['type'] != 'release' and x['tick'] <= until]})
        stretch = max(b-a for a, b in zip(marks, marks[1:]))
        self.assertLessEqual(stretch, 254)
        travel = {}
        for mover in self.S03_V3_MOVERS:
            anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']==mover]
            if anchors:
                travel[mover] = dict(dx=anchors[-1]['x']-anchors[0]['x'], dy=anchors[-1]['y']-anchors[0]['y'], ticks=len(anchors))
        result = dict(passed=True, matching_traces=True, trusted_inputs=True,
            proof_kind='isolated: one labeled initial placement = restoreClimbState of the real S02 v3 exit settled pose '
                       'from one base-start real-input S01+S02 v3 run; production input/physics thereafter',
            initial_placement=dict(labeled=True, source=type(self).v3_s02_start_proof), not_continuous_completion_claim=True,
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[{k:x[k] for k in ('tick','type','element','mover','player')} for x in mechanics],
            mover_anchor_travel_while_attached=travel, longest_stretch_without_mechanic_ticks=stretch, density_cap_ticks=254,
            density_measured_until_tick=until,
            final=players[-1], expected_exit=bounds, final_in_exit_box=self.inside(players[-1], bounds),
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        self.assertTrue(result['final_in_exit_box'], players[-1])
        return trace, players, mechanics, result

    def reach_s03(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.S03_V3_BAND[0] <= distance <= self.S03_V3_BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y'],speedX=p['speedX'],speedY=p['speedY']), anchor=a['rope'][0],
            band=list(self.S03_V3_BAND), in_band=True)

    def s03_kinds(self, mech):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S02-exit-ledge']

    def bounce_s03(self, trace, element):
        b = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']==element)
        return b, b['before']['simulation']['player'], b['after']['simulation']['player']

    def test_01_geometry_and_rules(self):
        r = self.report(); v2 = self.v2_s03()
        m = r['manifest']; elements = m['geometry']['elements']
        s03 = m['sections'][2]
        # Completed by TASK-554: all four encounters and their connectors are built.
        self.assertEqual((s03['designVersion'], s03['status']), (3, 'built'))
        self.assertEqual([e['status'] for e in m['encounters'][8:12]], ['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][8:12]], ['built']*4)
        self.assertEqual(m['recoveries'][2]['status'], 'built')
        self.assertEqual(m['connectors'][8]['from'], 'S02-04')
        self.assertNotIn('solidExceptions', s03)
        self.assertEqual((s03['band']['top'], s03['band']['bottom']), (-6480, -3240))
        sc = m['shortcuts'][0]
        self.assertEqual((sc['from'], sc['to'], sc['optional'], sc['status']), ('S03-01', 'S03-04', True, 'planned'))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S03-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S03-')}
        self.assertEqual(set(movers), set(self.S03_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        enc = {e['id']:e for e in m['encounters'][8:12]}
        self.assertEqual(enc['S03-01']['start'], {'x':5955.4,'y':-4870.9,'from':'S02-04'})
        self.assertEqual(enc['S03-02']['start'], {'from':'S03-01','x':5388.9,'y':-6501.3})
        self.assertEqual(enc['S03-03']['start'], {'from':'S03-02','x':5767.1,'y':-6771.4})
        self.assertEqual(enc['S03-04']['start'], {'from':'S03-03','x':6469.2,'y':-7939.9})
        for e in enc.values():
            self.assertTrue(all(x in by_id for x in e['elements']), e['id'])
            self.assertTrue(any(by_id[x]['role'] == 'bounce' for x in e['elements']), e['id'])
        for name in ('S03-01','S03-02','S03-03'):
            self.assertTrue(any(x in movers for x in enc[name]['elements']), name)
        for name, box in (('S03-01', self.S03_01_EXIT), ('S03-02', self.S03_02_EXIT),
                          ('S03-03', self.S03_03_EXIT), ('S03-04', self.S03_04_EXIT)):
            self.assertEqual(enc[name]['exit'], dict(left=box['x'][0], right=box['x'][1], top=box['y'][0], bottom=box['y'][1]))
        sec = r['report']['sections'][2]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S03', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][:3], ['S01','S02','S03'])
        self.assertFalse(r['report']['failed'])
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('right', 'right'))
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S03-01','S03-02','S03-03'])
        self.assertEqual((direction['entryX'], direction['exitX']), (5955.4, 6075))
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S03_V3_BAND))
        self.assertEqual([g['id'] for g in gaps], ['S03-01-hoist','S03-02-lift','S03-03-crest','S03-04-exit'])
        for g in gaps:
            self.assertTrue(self.S03_V3_BAND[0] <= g['distance'] <= self.S03_V3_BAND[1], g)
        # Every declared S03 miss falls through a drag zone onto a green bouncer.
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], list(self.S03_V3_FALLS))
        expected_falls = self.S03_V3_FALLS
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), expected_falls[f['id']], f)
            self.assertEqual(by_id[f['firstBouncer']]['role'], 'bounce')
            for d in f['dragZones']:
                b = self.bounds_v3(by_id[d])
                # The column is clipped at the right map edge (x 6480): the player centre cannot pass x 6469.2.
                self.assertTrue(b['left'] < f['x']-18 and min(f['x']+18, 6480) <= b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, d))
        # Since TASK-556 the S04-01-short fall point also uses S03-exit-drag; only the S03 ones are pinned here.
        self.assertEqual([dict(id=d['id'], fallPoints=[p for p in d['fallPoints'] if p.startswith('S03-')])
                          for d in sec['rules']['strayDrag']['measured']['dragZones']], [dict(id='S03-fall-drag', fallPoints=['S03-02-missed','S03-04-missed']),
            dict(id='S03-exit-drag', fallPoints=['S03-04-overshoot'])])
        # v2/v3 ratio against the v2 S03-01/02 gaps recorded by TASK-511 (and the v2 source).
        v2_geometry = json.loads((ROOT/'artifacts/TASK-511/geometry.json').read_text())
        v2_gaps = {g['id']:g for g in v2_geometry['manifest_section']['gaps']}
        self.assertEqual([v2_gaps[k] for k in ('S03-01-carriage','S03-02-lift')], v2['section']['gaps'][:2])
        dist = lambda g: ((g['to']['x']-g['from']['x'])**2+(g['to']['y']-g['from']['y'])**2) ** .5
        v2_d = {k:dist(v2_gaps[k]) for k in ('S03-01-carriage','S03-02-lift')}
        v3_d = {g['id']:g['distance'] for g in gaps[:2]}
        v2_mean, v3_mean = sum(v2_d.values())/2, sum(v3_d.values())/2
        ratio = v3_mean/v2_mean
        self.assertGreaterEqual(ratio, 2.0)
        per_gap = {k3:v3_d[k3]/v2_d[k2] for k3, k2 in (('S03-01-hoist','S03-01-carriage'),('S03-02-lift','S03-02-lift'))}
        self.assertTrue(all(x >= 2.0 for x in per_gap.values()), per_gap)
        # S03-03/04 (TASK-554) against the v2 S03-03/04 gaps recorded by TASK-512.
        v2_late = {g['id']:dist(g) for g in json.loads((ROOT/'artifacts/TASK-512/geometry.json').read_text())['manifest_section']['gaps'][2:]}
        self.assertEqual(sorted(v2_late), ['S03-03-crest','S03-04-trolley'])
        v3_late = {g['id']:g['distance'] for g in gaps[2:]}
        late_ratio = {'S03-03-crest':v3_late['S03-03-crest']/v2_late['S03-03-crest'],
                      'S03-04-exit':v3_late['S03-04-exit']/v2_late['S03-04-trolley']}
        self.assertTrue(all(x >= 2.0 for x in late_ratio.values()), late_ratio)
        all_mean_ratio = (sum(v3_d.values())+sum(v3_late.values()))/(sum(v2_d.values())+sum(v2_late.values()))
        self.assertGreaterEqual(all_mean_ratio, 2.0)
        # Every static v2 S03 solid is deleted or converted to a green bouncer.
        self.assertEqual(sorted(v2['staticSolids']), sorted(V2_S03_DISPOSITION))
        own_ids = {e['id'] for e in own}
        mapping = []
        for old in v2['staticSolids']:
            kind, why = V2_S03_DISPOSITION[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertNotIn(old, own_ids, old)
            else: self.assertEqual(now['role'], 'bounce', old)
            mapping.append(dict(id=old, v2_role='solid', disposition=kind, v3_role=now['role'] if now else None, reason=why))
        v2_ids = {e['id'] for e in v2['elements']}
        self.assertEqual(sorted(v2_ids - set(V2_S03_DISPOSITION)), sorted(V2_S03_OTHER))
        for old, what in V2_S03_OTHER.items():
            self.assertEqual(old in own_ids, what.startswith('id re-used'), old)
        self.assertEqual(sorted(own_ids - v2_ids), sorted(V3_S03_ADDED))
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S03-01','S03-02','S03-03','S03-04'], planned=[],
            gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=v3_d, v2_gap_distances=v2_d, v2_gap_source='artifacts/TASK-511/geometry.json manifest_section.gaps',
            v2_mean_gap=v2_mean, v3_mean_gap=v3_mean, v3_over_v2_mean_ratio=ratio, v3_over_v2_per_gap=per_gap,
            v3_s03_03_04_gap_distances=v3_late, v2_s03_03_04_gap_distances=v2_late,
            v2_s03_03_04_gap_source='artifacts/TASK-512/geometry.json manifest_section.gaps',
            v3_over_v2_s03_03_04_per_gap=late_ratio, v3_over_v2_all_four_mean_ratio=all_mean_ratio,
            ratio_at_least_2=True, direction=direction,
            direction_note='the direction rule reads the S03-04 exit box centre x (6075, the green exit ledge) against the S03-01 entry x (5955.4)',
            fall_points=falls, own_drag_zones=sec['rules']['strayDrag']['measured']['dragZones'],
            drag_below_every_fall_point=True, gray_solid_count=len(gray)))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s03, encounters=m['encounters'][8:12],
            connectors=m['connectors'][8:13], recovery=m['recoveries'][2], shortcut=sc, elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True, v2_revision=V2_S03_REVISION,
            v2_static_solids=v2['staticSolids'], v2_solid_disposition=mapping, v2_other_elements=V2_S03_OTHER,
            v3_added=list(V3_S03_ADDED)))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1840" viewBox="4100 -8340 2560 3680" style="background:#111827">']
        for e in elements:
            if not e['id'].startswith('S02-'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.18' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>'
                         f'<text x="{e["x"]+5}" y="{e["y"]+30}" fill="#9ca3af" font-size="40">{e["id"]}</text>')
        for e in own:
            if e['id'] == 'S03-exit-pad': continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors[roles[e['id']]] + ('" fill-opacity="0.35' if roles[e['id']] == 'yellow drag' else '')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="2"/>'
                         f'<text x="{e["x"]-(560 if e["x"] > 6000 else 40)}" y="{e["y"]-14}" fill="white" font-size="44">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+15}" x2="{e["x"]+60+dx}" y2="{e["y"]+15+dy}" stroke="#93c5fd" stroke-width="5" stroke-dasharray="10,6"/>')
        for g in s03['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="10,8"/>')
        for f in falls:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="{f["firstBouncerTop"]}" stroke="#fb923c" stroke-width="3" stroke-dasharray="4,10"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="10" fill="#fb923c"/><text x="{f["x"]-330}" y="{f["y"]+12}" fill="#fb923c" font-size="40">{f["id"]}</text>')
        for e in m['encounters'][8:12]:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="4"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+44}" fill="#f472b6" font-size="40">{e["id"]} exit</text>')
        parts.append('<circle cx="5955.4" cy="-4870.9" r="26" fill="#ff7a1a"/>')
        for i, t in enumerate(['S03 Broken Viaduct v3 (designVersion 3, travelling right) - zero gray solids; orange = real S02 v3 exit settled pose',
                'S03-01: blue hoist up-left out of S02-exit-drag -> green west-pier rebound right',
                'S03-02: blue span lift caught in flight -> green east-pier rebound left',
                'S03-03: blue shutter stops the flight -> green crest hook up-right -> right map edge, rise to apex',
                'S03-04: green exit hook west from the apex -> S03-exit-drag -> settle on the green exit ledge',
                'yellow dashes = gaps %s of 1080; orange = fall points over drag zones; pink = exit boxes; grey = S02'
                % '/'.join(str(round(g['distance'],1)) for g in gaps)]):
            parts.append(f'<text x="4120" y="{-8290+i*44}" fill="#67e8f9" font-size="32">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=dict(width=1280, height=1840)); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S03 designVersion 3 built (S03-01..04); gray solids', len(gray), '; roles',
              sorted(set(roles.values())), '; all 7 v3 rules pass; direction right', direction['exitX'], '>', direction['entryX'],
              '; gaps', [round(g['distance'],1) for g in gaps], '; v3/v2 ratios', round(ratio,4), {k:round(v,4) for k, v in late_ratio.items()},
              '; fall points over drag', {f['id']:f['dragZones'] for f in falls}, '; v2 solids', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def s03_01_checks(self, trace, players, mech, result):
        out = next(t for t, p in enumerate(players) if t > 5 and not self.in_box(p, self.S02_EXIT_DRAG))
        self.assertLess(out, 120)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S03-hoist']['dy']), 1)
        bounce, before, after = self.bounce_s03(trace, 'S03-west-pier')
        self.assertLess(before['speedX'], 0); self.assertGreater(after['speedX'], 0); self.assertLess(after['speedY'], 0)
        self.assertTrue(self.inside(players[self.S03_01_TICKS], self.S03_01_EXIT), players[self.S03_01_TICKS])
        return out, bounce, before, after

    def test_02_s03_01_nominal(self):
        trace, players, mech, result = self.run_s03('S03-01', self.S03_01_V3, self.S03_01_TICKS, self.S03_01_EXIT)
        self.assertEqual(self.s03_kinds(mech), [('acquisition','S03-hoist'),('release','S03-hoist'),('bounce','S03-west-pier')])
        out, bounce, before, after = self.s03_01_checks(trace, players, mech, result)
        reach = self.reach_s03(players, mech, 5, 'S03-hoist')
        result.update(encounter='S03-01', acquisition_reach=reach, left_s02_exit_drag_tick=out,
            west_pier_bounce=dict(tick=bounce['tick'], before=before, after=after))
        self.evidence.write('encounters/S03-01/result.json', result)
        print('PASS S03-01: from the real S02 v3 exit pose; blue hoist acquisition', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; left S02-exit-drag at tick', out, '; green west-pier rebound at tick', bounce['tick'],
              '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s03_02_nominal(self):
        trace, players, mech, result = self.run_s03('S03-02', self.S03_01_V3+self.S03_02_V3, self.S03_02_TICKS, self.S03_02_EXIT)
        self.assertEqual(self.s03_kinds(mech), [('acquisition','S03-hoist'),('release','S03-hoist'),('bounce','S03-west-pier'),
            ('acquisition','S03-lift'),('release','S03-lift'),('bounce','S03-east-pier')])
        self.s03_01_checks(trace, players, mech, result)
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S03-lift')
        self.assertGreater(lift['tick'], self.S03_01_TICKS)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S03-lift']['dx']), 1)
        bounce, before, after = self.bounce_s03(trace, 'S03-east-pier')
        self.assertGreater(before['speedX'], 0); self.assertLess(after['speedX'], 0)
        launch = players[266]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (5388.9, -6501.3))
        hoist = self.reach_s03(players, mech, 5, 'S03-hoist')
        reach = self.reach_s03(players, mech, 266, 'S03-lift')
        # The east pier lies beyond the 1080 grapnel range from the S03-02 launch point.
        far = math.hypot(before['x']-launch['x'], before['y']-launch['y'])
        self.assertGreater(far, 1000)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {'S03-hoist':hoist, 'S03-lift':reach}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S03-02', segmented_from='S03-01 exit at tick 250 of the same run (no further placement)',
            s03_01_exit_at_tick_250=players[self.S03_01_TICKS], acquisition_reach=reach,
            east_pier_bounce=dict(tick=bounce['tick'], before=before, after=after, distance_from_launch=far))
        self.evidence.write('encounters/S03-02/result.json', result)
        print('PASS S03-02: from the S03-01 exit at tick 250; blue lift acquisition', round(reach['distance'],1), 'at tick',
              lift['tick'], '; green east-pier rebound at tick', bounce['tick'], round(far,1), 'from the launch; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def fall_s03(self, trace, players, mech, release_tick, element, drag, settle_box):
        """First landing on the green bouncer after a drag-zone pass; first rebound peak vs the drop."""
        land = next(e for e in mech if e['type']=='bounce' and e['element']==element and e['tick'] > release_tick)
        apex = min(range(release_tick, land['tick']), key=lambda t: players[t]['y'])
        entry = next(t for t in range(apex, land['tick']) if self.in_box(players[t], drag))
        self.assertTrue(all(self.in_box(players[t], drag) for t in range(entry, land['tick']+1)))
        nxt = next((e['tick'] for e in mech if e['type']=='bounce' and e['element']==element and e['tick'] > land['tick']), len(players)-1)
        peak = min(p['y'] for p in players[land['tick']:nxt+1])
        drop = land['player']['y'] - players[apex]['y']
        ratio = (land['player']['y'] - peak) / drop
        self.assertLessEqual(ratio, .5)
        self.assertGreater(peak, players[apex]['y'])
        settle = next(t for t in range(land['tick'], len(players)) if all(self.inside(p, settle_box) for p in players[t:]))
        speed_in = (players[entry]['speedX'], players[entry]['speedY'])
        speed_land = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land['tick'])['before']['simulation']['player']
        return dict(release_tick=release_tick, apex=dict(tick=apex, player=players[apex]), drag_zone=drag, drag_entry_tick=entry,
            speed_at_drag_entry=speed_in, speed_before_landing=(speed_land['speedX'], speed_land['speedY']),
            landing=dict(tick=land['tick'], element=element, player=land['player']), drop_height=drop,
            first_rebound_peak_y=peak, first_rebound_over_drop=ratio, below_release_height=True,
            settled_from_tick=settle, settle_box=settle_box, rest=players[-1])

    def test_04_declared_falls_through_drag(self):
        out = {}
        trace, players, mech, result = self.run_s03('S03-01-short', self.S03_01_SHORT, 1000, self.S02_V3_SETTLE, density_until=75, folder='falls')
        self.assertEqual(self.s03_kinds(mech)[:2], [('acquisition','S03-hoist'),('release','S03-hoist')])
        self.assertFalse([e for e in mech if e['element'] and e['element'].startswith('S03-') and e['type']=='bounce'])
        out['S03-01-short'] = self.fall_s03(trace, players, mech, 75, 'S02-exit-ledge', self.S02_EXIT_DRAG, self.S02_V3_SETTLE)
        trace, players, mech, result = self.run_s03('S03-02-missed', self.S03_01_V3, 1400, self.BRIDGE_SETTLE, density_until=250, folder='falls')
        kinds = self.s03_kinds(mech)
        self.assertEqual(kinds[:4], [('acquisition','S03-hoist'),('release','S03-hoist'),('bounce','S03-west-pier'),('bounce','S02-east-wall')])
        self.assertNotIn(('acquisition','S03-lift'), kinds)
        wall = next(e['tick'] for e in mech if e['element']=='S02-east-wall')
        out['S03-02-missed'] = self.fall_s03(trace, players, mech, wall, 'S03-lower-bridge', self.S03_FALL_DRAG, self.BRIDGE_SETTLE)
        self.evidence.write('falls/result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S03 fall point is exercised from the labeled real S02 v3 exit pose; the player crosses the drag '
                 'zone, lands on the green bouncer, rebounds to at most half the drop (never back to the release height) and settles'))
        for k, v in out.items():
            print('PASS fall', k, ': drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on', v['landing']['element'],
                  'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3), '; settled from tick', v['settled_from_tick'])


class ViaductV3CompleteChecks(ViaductV3Checks):
    """Layout-v3 Broken Viaduct S03-03/04, section exit and fall recovery (TASK-554), with real input.

    Same labeled-placement proof as ViaductV3Checks: the start is the real S02 v3 exit settled pose of one
    base-start real-input S01+S02 v3 run. S03-03/04 continue the S03-01/02 inputs of the same run, so they are
    segmented from the S03-02 exit (tick 360) and the S03-03 apex (tick 625), not placed. Not a
    continuous-completion claim. Shared by Task554Tests and the re-specced Task512Tests.
    """
    # TASK-555 moved the crest hook from (6090,-7675) to (6330,-7500), out from under the touch pause
    # button, and lowered the east pier top to -7000 so the up-right pull clears it.
    CREST_V3, EXIT_HOOK_V3 = (6430,-7488), (5460,-7950)
    CREST_RELEASE = 485
    # S03-03: the leftward flight off the east pier hits the blue shutter (tick ~394, speed killed); the
    # crest hook is pressed from rest at 400 and held to CREST_RELEASE; the release flies over the east
    # pier top into the right map edge.
    # S03-04: pressed at the apex on the map edge (625), held 70; the pull carries the player into the
    # exit drag zone, where it is released and settles on the green exit ledge.
    S03_03_V3 = [(400,'mousedown',*CREST_V3),(CREST_RELEASE,'mouseup',*CREST_V3)]
    S03_04_V3 = [(625,'mousedown',*EXIT_HOOK_V3),(695,'mouseup',*EXIT_HOOK_V3)]
    S03_ROUTE_V3 = ViaductV3Checks.S03_01_V3+ViaductV3Checks.S03_02_V3+S03_03_V3+S03_04_V3
    S03_03_TICKS, S03_04_TICKS, S03_FULL_TICKS, S03_LAND_BY = 625, 1300, 1500, 800
    S03_EXIT_DRAG = dict(left=5790, right=6200, top=-8095, bottom=-7770)
    MAP_EDGE_X = 6469.2
    # Mistimed S03-03 (fall.json): the crest hook released 5 ticks after the catch (410 instead of CREST_RELEASE;
    # TASK-555: with the moved hook a 413 release carries enough rightward speed to land on the S02 crown hook).
    # The player drops off the shutter through S02-exit-drag onto the green S02 exit ledge and settles.
    # Rejoin after 6 mover periods (1440 ticks, so every mover is back in phase): the unchanged S03-01/02
    # inputs, then S03-03 released 3 ticks earlier (the rejoined east-pier rebound is ~18 higher) and S03-04 at the apex.
    REJOIN_S03_TICK, EARLY_RELEASE = 1440, 410
    S03_03_EARLY = ViaductV3Checks.S03_01_V3+ViaductV3Checks.S03_02_V3+[(400,'mousedown',*CREST_V3),(EARLY_RELEASE,'mouseup',*CREST_V3)]
    REJOIN_S03 = [(t+1440, e, x, y) for t, e, x, y in ViaductV3Checks.S03_01_V3+ViaductV3Checks.S03_02_V3+
                  [(400,'mousedown',*CREST_V3),(CREST_RELEASE-3,'mouseup',*CREST_V3),(622,'mousedown',*EXIT_HOOK_V3),(692,'mouseup',*EXIT_HOOK_V3)]]
    FALL_S03, FALL_S03_TICKS = S03_03_EARLY+REJOIN_S03, REJOIN_S03_TICK+1300
    # Declared S03-04 misses: no exit-hook press (falls down the right map edge through S03-fall-drag onto
    # the green lower bridge) and an exit hook held 300 ticks (drifts west inside the exit drag, settles on the
    # ledge). Holds beyond ~360 ticks pull the player out of the drag's west end (undeclared; S03 tolerance ticket).
    S03_04_MISSED = ViaductV3Checks.S03_01_V3+ViaductV3Checks.S03_02_V3+S03_03_V3
    S03_04_OVERSHOOT = S03_04_MISSED+[(625,'mousedown',*EXIT_HOOK_V3),(925,'mouseup',*EXIT_HOOK_V3)]
    OVERSHOOT_SETTLE = dict(x=[5800,6190], y=[-7800,-7770], speedX=[-.001,.001], speedY=[-.05,.05])

    def wall_and_apex(self, players, release_tick):
        """The S03-03 release flight reaches the right map edge (sideways speed stopped) and rises to an apex."""
        wall = next(t for t in range(release_tick, len(players)) if abs(players[t]['x']-self.MAP_EDGE_X) < .05)
        apex = min(range(wall, min(len(players), wall+150)), key=lambda t: players[t]['y'])
        return wall, apex

    # Contact events carry the contact point, not an element id: the shutter's right face over its travel.
    SHUTTER_FACE = dict(left=5745, right=5775, top=-6960, bottom=-6730)

    def contacts(self, trace):
        return [e for e in trace['events'] if e['type']=='contact']

    def no_legacy_contact(self, trace):
        """No contact point lies on a legacy S04-S06 element (gray v1/v2 geometry the v3 S03 route must avoid)."""
        m = self.report()['manifest']
        boxes = {e['id']:self.bounds_v3(e) for e in m['geometry']['elements'] if e['id'].split('-')[0] in ('S04','S05','S06')}
        hits = sorted({k for e in self.contacts(trace) for k, b in boxes.items()
                       if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1})
        self.assertEqual(hits, [])
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 6480]
        return dict(legacy_contact_points=hits, contact_events=len(self.contacts(trace)),
                    right_map_edge_contact_ticks=[edge[0], edge[-1]] if edge else [])

    def s03_03_checks(self, trace, players, mech):
        self.assertTrue(self.inside(players[self.S03_02_TICKS], self.S03_02_EXIT), players[self.S03_02_TICKS])
        shutter = next(e for e in self.contacts(trace) if e['tick'] > self.S03_02_TICKS and self.inside(
            dict(x=e['contact']['x'], y=e['contact']['y']), dict(x=[self.SHUTTER_FACE['left'], self.SHUTTER_FACE['right']],
            y=[self.SHUTTER_FACE['top'], self.SHUTTER_FACE['bottom']])))
        self.assertEqual((shutter['contact']['nx'], shutter['contact']['ny']), (1, 0))
        before, after = shutter['before']['simulation']['player'], shutter['after']['simulation']['player']
        self.assertLess(before['speedX'], -1.5); self.assertLess(abs(after['speedX']), .05)
        self.assertGreater(shutter['tick'], self.S03_02_TICKS); self.assertLess(shutter['tick'], 400)
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S03-crest-hook')
        self.assertGreater(acq['tick'], shutter['tick'])
        release = next(e for e in mech if e['type']=='release' and e['element']=='S03-crest-hook')
        self.assertEqual(release['tick'], self.CREST_RELEASE)
        wall, apex = self.wall_and_apex(players, release['tick'])
        self.assertGreater(players[wall-1]['speedX'], .5); self.assertEqual(players[wall]['speedX'], 0)
        self.assertTrue(-7400 < players[wall]['y'] < -7150, players[wall])
        self.assertTrue(-7990 < players[apex]['y'] < -7900, players[apex])
        reach = self.reach_s03(players, mech, 400, 'S03-crest-hook')
        return dict(shutter_contact=dict(tick=shutter['tick'], before=before, after=after),
            crest_acquisition_reach=reach, crest_release=dict(tick=release['tick'], player=release['player']),
            map_edge_stop=dict(tick=wall, before=players[wall-1], after=players[wall]),
            apex=dict(tick=apex, player=players[apex]))

    def test_05_s03_03_nominal(self):
        plan = self.S03_01_V3+self.S03_02_V3+self.S03_03_V3
        trace, players, mech, result = self.run_s03('S03-03', plan, self.S03_03_TICKS, self.S03_03_EXIT)
        self.assertEqual([k for k in self.s03_kinds(mech) if k[0] != 'contact'], [('acquisition','S03-hoist'),('release','S03-hoist'),
            ('bounce','S03-west-pier'),('acquisition','S03-lift'),('release','S03-lift'),('bounce','S03-east-pier'),
            ('acquisition','S03-crest-hook'),('release','S03-crest-hook')])
        out = self.s03_03_checks(trace, players, mech)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S03-03', segmented_from='S03-02 exit at tick 360 of the same run (no further placement)',
            s03_02_exit_at_tick_360=players[self.S03_02_TICKS], exit_judged_at_tick=self.S03_03_TICKS,
            contacts=touched, legacy_s04_s06_contacts=[], **out)
        self.evidence.write('encounters/S03-03/result.json', result)
        print('PASS S03-03: from the S03-02 exit at tick 360; blue shutter contact tick', out['shutter_contact']['tick'], 'vx',
              round(out['shutter_contact']['before']['speedX'],3), '->', round(out['shutter_contact']['after']['speedX'],3),
              '; green crest-hook acquisition', round(out['crest_acquisition_reach']['distance'],1), 'at tick',
              out['crest_acquisition_reach']['acquisition_tick'], '; release', self.CREST_RELEASE, '; map edge stop tick', out['map_edge_stop']['tick'],
              '; apex', round(out['apex']['player']['y'],1), 'at tick', out['apex']['tick'], '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def s03_04_checks(self, trace, players, mech, press=625, ticks=None):
        """Exit-hook pull from the apex into S03-exit-drag, release inside it, settle on the green exit ledge."""
        ticks = ticks or len(players)-1
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S03-exit-hook' and e['tick'] >= press)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S03-exit-hook' and e['tick'] > acq['tick'])
        entry = next(t for t in range(acq['tick'], release['tick']+1) if self.in_box(players[t], self.S03_EXIT_DRAG))
        self.assertTrue(all(self.in_box(players[t], self.S03_EXIT_DRAG) for t in range(entry, ticks+1)))
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S03-exit-ledge' and e['tick'] > release['tick']]
        self.assertTrue(ledge)
        land = ledge[0]
        self.assertLessEqual(land['tick'], press+self.S03_LAND_BY-625)
        settle = next(t for t in range(land['tick'], ticks+1) if all(self.inside(players[u], self.S03_04_EXIT) for u in range(t, ticks+1)))
        tail = players[settle:ticks+1]
        reach = self.reach_s03(players, mech, press, 'S03-exit-hook')
        return dict(exit_hook_acquisition_reach=reach, exit_drag_entry=dict(tick=entry, player=players[entry], before=players[entry-1]),
            exit_hook_release=dict(tick=release['tick'], player=release['player'], inside_exit_drag=True),
            exit_ledge_landing=dict(tick=land['tick'], player=land['player']), ledge_bounces=len(ledge),
            section_exit=dict(element='S03-exit-ledge', drag_zone='S03-exit-drag', settle_tick=settle, settled_ticks=len(tail),
                settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[ticks], settle_box=self.S03_04_EXIT, inside_exit_drag=True))

    def test_06_s03_04_nominal(self):
        trace, players, mech, result = self.run_s03('S03-04', self.S03_ROUTE_V3, self.S03_04_TICKS, self.S03_04_EXIT,
                                                    density_until=self.S03_LAND_BY)
        self.assertTrue(self.inside(players[self.S03_03_TICKS], self.S03_03_EXIT), players[self.S03_03_TICKS])
        out = self.s03_04_checks(trace, players, mech)
        self.assertLessEqual(out['section_exit']['settle_tick'], 1250)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S03-04', segmented_from='S03-03 exit (apex on the right map edge) at tick 625 of the same run (no further placement)',
            s03_03_exit_at_tick_625=players[self.S03_03_TICKS], contacts=touched, legacy_s04_s06_contacts=[], **out)
        self.evidence.write('encounters/S03-04/result.json', result)
        print('PASS S03-04: from the S03-03 apex at tick 625; green exit-hook acquisition',
              round(out['exit_hook_acquisition_reach']['distance'],1), 'at tick', out['exit_hook_acquisition_reach']['acquisition_tick'],
              '; enters S03-exit-drag at tick', out['exit_drag_entry']['tick'], '; release inside it at', out['exit_hook_release']['tick'],
              '; green exit-ledge landing tick', out['exit_ledge_landing']['tick'], '; settled from tick', out['section_exit']['settle_tick'],
              'at', {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')}, '; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], 'until tick', self.S03_LAND_BY, '; identical replay; trusted input')

    def test_07_full_traversal(self):
        trace, players, mech, result = self.run_s03('S03-full', self.S03_ROUTE_V3, self.S03_FULL_TICKS, self.S03_04_EXIT,
                                                    density_until=self.S03_LAND_BY)
        self.assertEqual([e['element'] for e in mech if e['type']=='acquisition' and e['element'] != 'S02-exit-ledge'],
                         ['S03-hoist','S03-lift','S03-crest-hook','S03-exit-hook'])
        exits = {}
        for name, tick, bounds in (('S03-01',self.S03_01_TICKS,self.S03_01_EXIT),('S03-02',self.S03_02_TICKS,self.S03_02_EXIT),
                                   ('S03-03',self.S03_03_TICKS,self.S03_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        s3 = self.s03_03_checks(trace, players, mech)
        s4 = self.s03_04_checks(trace, players, mech)
        exits['S03-04'] = dict(tick=s4['section_exit']['settle_tick'], player=players[s4['section_exit']['settle_tick']], box=self.S03_04_EXIT)
        touched = self.no_legacy_contact(trace)
        reaches = [self.reach_s03(players, mech, t, el) for t, el in ((5,'S03-hoist'),(266,'S03-lift'),(400,'S03-crest-hook'),(625,'S03-exit-hook'))]
        result.update(encounter='S03 full traversal', encounter_exits=exits, s03_03=s3, s03_04=s4, section_exit=s4['section_exit'],
            section_exit_reached=True, settled_at_section_exit=True, contacts=touched, legacy_s04_s06_contacts=[], reaches=reaches)
        self.evidence.write('encounters/S03-full/result.json', result)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules.setdefault('trace_measured_reach', {}).update({x['element']:x for x in reaches})
            self.evidence.write('rules.json', rules)
        print('PASS full S03: from the real S02 v3 exit pose; exits', {k:v['tick'] for k, v in exits.items()}, '; reaches',
              [round(x['distance'],1) for x in reaches], '; exit ledge landing tick', s4['exit_ledge_landing']['tick'], '; settled from tick',
              s4['section_exit']['settle_tick'], 'for', s4['section_exit']['settled_ticks'], 'ticks at',
              {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')}, 'inside S03-exit-drag; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_08_fall_through_drag_and_rejoin(self):
        trace, players, mech, result = self.run_s03('S03-03-early', self.FALL_S03, self.FALL_S03_TICKS, self.S03_04_EXIT,
                                                    density_until=self.EARLY_RELEASE, folder='falls')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S03-crest-hook')
        self.assertEqual(release['tick'], self.EARLY_RELEASE)
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S02-exit-ledge' and release['tick'] < e['tick'] < self.REJOIN_S03_TICK]
        self.assertTrue(ledge)
        land = ledge[0]['tick']
        self.assertFalse([e for e in mech if e['type']=='bounce' and release['tick'] < e['tick'] < land])
        apex_tick = min(range(release['tick'], land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        ticks = [t for t in range(release['tick'], land+1) if self.in_box(players[t], self.S02_EXIT_DRAG)]
        entry, leave = ticks[0], ticks[-1]
        self.assertEqual(ticks, list(range(entry, land+1)))
        before, after = players[entry-1], players[leave]
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, leave) if abs(players[t]['speedX']) > 1e-9][:8]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios)
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_ledge = contact['before']['simulation']['player']
        self.assertLess(abs(at_ledge['speedX']), abs(before['speedX'])*.01)
        self.assertLess(at_ledge['speedY'], before['speedY'])
        rest_y = ledge[0]['player']['y']
        fall_height = rest_y - apex['y']
        peaks = []
        for a, b in zip(ledge, ledge[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_S03_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(p['peak_y'] > release['player']['y'] for p in peaks))
        # Settled on the green S02 exit ledge inside S02-exit-drag before the rejoin press.
        window = players[self.REJOIN_S03_TICK-100:self.REJOIN_S03_TICK]
        self.assertTrue(all(self.inside(p, self.S02_V3_SETTLE) and self.in_box(p, self.S02_EXIT_DRAG) for p in window))
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_S03_TICK]
        self.assertEqual(len(rejoin_inputs), 8)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after_rejoin = [e for e in mech if e['tick'] >= self.REJOIN_S03_TICK]
        self.assertEqual([e['element'] for e in after_rejoin if e['type']=='acquisition'], ['S03-hoist','S03-lift','S03-crest-hook','S03-exit-hook'])
        for el in ('S03-west-pier','S03-east-pier'):
            self.assertIn(('bounce', el), [(e['type'], e['element']) for e in after_rejoin])
        s4 = self.s03_04_checks(trace, players, mech, press=self.REJOIN_S03_TICK+622)
        fall = dict(scenario='naturally mistimed S03-03 release: crest hook released 5 ticks after the catch (tick %d instead of %d); ' % (self.EARLY_RELEASE, self.CREST_RELEASE) +
                             'physical fall; no relocation after the labeled S02 v3 exit start placement',
            release=dict(tick=release['tick'], element='S03-crest-hook', nominal_release_tick=self.CREST_RELEASE, player=release['player'],
                         release_height_y=release['player']['y']),
            fall_point=dict(id='S03-03-early', declared_x=5780, declared_y=-6760, release_x=release['player']['x'], landing_x=at_ledge['x']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='S02 exit ledge bounce rest y minus the apex y after the release',
            drag_zone=dict(id='S02-exit-drag', box=self.S02_EXIT_DRAG, entry_tick=entry, last_tick_inside=leave,
                before=dict(tick=entry-1, x=before['x'], y=before['y'], speedX=before['speedX'], speedY=before['speedY']),
                at_ledge=dict(tick=land, x=at_ledge['x'], y=at_ledge['y'], speedX=at_ledge['speedX'], speedY=at_ledge['speedY']),
                per_tick_vx_ratio_airborne=ratios, vertical_damping_per_tick=0.985),
            s02_bouncer=dict(element='S02-exit-ledge', route='S02-04 exit ledge (S02 route bouncer)', first_bounce_tick=land,
                rest_y=rest_y, inside='S02-exit-drag'),
            bounce_peaks=peaks, first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True, never_back_to_release_height=True,
            settled=dict(window=[self.REJOIN_S03_TICK-100, self.REJOIN_S03_TICK-1], box=self.S02_V3_SETTLE,
                max_abs_speedX=max(abs(p['speedX']) for p in window), max_abs_speedY=max(abs(p['speedY']) for p in window),
                y_range=[min(p['y'] for p in window), max(p['y'] for p in window)], inside_drag_zone='S02-exit-drag', on='S02-exit-ledge'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                start_tick=self.REJOIN_S03_TICK, mover_periods_after_start=self.REJOIN_S03_TICK//240,
                mechanics=[{k:e[k] for k in ('tick','type','element','player')} for e in after_rejoin if e['type'] != 'contact'],
                s03_04=s4, final=players[-1], encounter_rejoined='S03-01 (the section start) through the S03 exit ledge', exit_box=self.S03_04_EXIT))
        result.update(fall)
        self.evidence.write('falls/S03-03-early/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed crest release tick', self.EARLY_RELEASE, 'at y', round(release['player']['y'],1), '; apex', round(apex['y'],1),
              '; S02-exit-drag vx/vy', round(before['speedX'],3), round(before['speedY'],3), '->', round(at_ledge['speedX'],5),
              round(at_ledge['speedY'],3), '; S02 exit ledge bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of',
              round(fall_height,1), '; settled; input-only rejoin from tick', self.REJOIN_S03_TICK, ': acquisitions',
              [e['element'] for e in after_rejoin if e['type']=='acquisition'], '; settled on the S03 exit ledge from tick',
              s4['section_exit']['settle_tick'])
        # The other declared S03-04 fall points, each from the same labeled start.
        out = {}
        trace, players, mech, result = self.run_s03('S03-04-missed', self.S03_04_MISSED, 1900, self.BRIDGE_SETTLE, density_until=self.CREST_RELEASE, folder='falls')
        self.assertNotIn('S03-exit-hook', [e['element'] for e in mech if e['type']=='acquisition'])
        out['S03-04-missed'] = self.fall_s03(trace, players, mech, self.CREST_RELEASE, 'S03-lower-bridge', self.S03_FALL_DRAG, self.BRIDGE_SETTLE)
        trace, players, mech, result = self.run_s03('S03-04-overshoot', self.S03_04_OVERSHOOT, 1500, self.OVERSHOOT_SETTLE,
                                                    density_until=self.S03_LAND_BY, folder='falls')
        out['S03-04-overshoot'] = self.fall_s03(trace, players, mech, 925, 'S03-exit-ledge', self.S03_EXIT_DRAG, self.OVERSHOOT_SETTLE)
        self.evidence.write('falls/s03_04_result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S03-04 fall point is exercised from the labeled real S02 v3 exit pose; the player crosses the drag zone, '
                 'lands on the green bouncer, rebounds to at most half the drop (never back to the release height) and settles inside the drag zone'))
        for k, v in out.items():
            print('PASS fall', k, ': drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on', v['landing']['element'],
                  'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3), '; settled from tick', v['settled_from_tick'])


class Task511Tests(ViaductV3Checks, unittest.TestCase):
    """Broken Viaduct opening (S03-01/02), re-specced by TASK-553 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, all shared with Task553Tests via ViaductV3Checks):
    test_01_geometry_and_rules: v2 rules, rest-pad exceptions, 459-486 gaps at 540 -> v3 rules, zero
    gray solids, 918-972 gaps at 1080 (v3/v2 mean ratio >= 2.0 against artifacts/TASK-511/geometry.json),
    every v2 S03 solid deleted or converted to a green bouncer.
    test_02_s03_01_nominal: blue carriage from the v2 S02 exit-pad rest onto the pier pad -> blue hoist
    from the real v3 S02 exit settled pose up out of S02-exit-drag into the green west-pier rebound.
    test_03_s03_02_nominal: blue span lift from the pier across the span into the green buffer onto the
    far deck -> blue span lift caught in flight, swung across the broken span into the green east-pier
    rebound. New test_04_declared_falls_through_drag covers the v3 fall points; test_04_source_hashes
    is renamed test_05_source_hashes. The v2 helpers and constants below (s02_exit, at_rest, events,
    BASE_ROUTE, S03_01/02, LIFT, REST, BOXES) stay for the later v2 suites (Task512-514).
    """
    task_id = 'TASK-511'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    replay = Task506Tests.replay
    filmstrip = Task507Tests.filmstrip
    bounds = Task509Tests.bounds
    brake_ticks = Task509Tests.brake_ticks
    test_05_source_hashes = V1Task465.test_03_source_hashes
    # One base-start run: the S01 route, then the TASK-510 S02 nominal inputs from tick 1120.
    BASE_ROUTE = Task508Tests.S01_ROUTE+[(t+1120, e, x, y) for t, e, x, y in Task510Tests.NOMINAL]
    CARRIAGE, LIFT = (2244,-3125), (2903,-3370)
    S03_01 = [(5,'mousedown',*CARRIAGE),(45,'mouseup',*CARRIAGE)]
    S03_02 = [(200,'mousedown',*LIFT),(265,'mouseup',*LIFT)]
    MOVERS = ('S03-carriage','S03-lift')
    BUFFER = 'S03-span-buffer'
    BAND, RANGE = (459, 486), 540
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])
    BOXES = {'S02-04':dict(x=[2050.7,2050.9],y=[-2691,-2690],**REST),
             'S03-01':dict(x=[2420,2580],y=[-3011,-3010],**REST),
             'S03-02':dict(x=[3370,3500],y=[-3261,-3260],**REST)}

    def at_rest(self, player, name):
        return all(b[0] <= player[k] <= b[1] for k, b in self.BOXES[name].items())

    def s02_exit(self):
        """Real S02 exit rest pose: one base-start real-input run of the v2 S01 and S02 routes (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'start'): return type(self).start
        m = dict(metadata=metadata('base-start'), ticks=2120, expected_exit=self.BOXES['S02-04'],
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.BASE_ROUTE],
            required_events=['acquisition','release'])
        m['metadata']['compact_contacts'] = True
        setup = execute(m, self.browser, self.url, str(self.evidence.path('encounters/S02-exit-start')))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual(acquired, ['S01-hoist','S01-lift','S01-crane-hook','S01-jib-hook','S01-boom-hook',
            'S02-shuttle','S02-lift','S02-crest-hook','S02-ledge','S02-trolley'])
        self.evidence.write('encounters/S02-exit-start/trace.json', self.compact(setup))
        rest = next(t for t in range(1931, 2121) if self.at_rest(players[t], 'S02-04'))
        self.assertTrue(all(self.at_rest(p, 'S02-04') for p in players[rest:]))
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (2050.8, -2690.8))
        start = setup['snapshots'][-1]['state']['simulation']
        type(self).start = start
        type(self).start_proof = dict(kind='base-start S01+S02 v2 routes (TASK-507 S01 then TASK-510 S02 nominal inputs '
            'from tick 1120), real mouse input, no placement', inputs=m['inputs'], acquisitions=acquired,
            s02_exit_rest_from_tick=rest, final_tick=2120, player=start['player'],
            snapshot_sha256=setup['snapshots'][-1]['sha256'], trace='encounters/S02-exit-start/trace.json')
        self.evidence.write('encounters/S02-exit-start/result.json', dict(passed=True, **type(self).start_proof))
        return start

    def events(self, mech):
        return [(e['type'], e['element']) for e in mech if e['type'] in ('acquisition','release')]


class Task512Tests(ViaductV3CompleteChecks, unittest.TestCase):
    """Broken Viaduct S03-03/04, section exit and fall recovery, re-specced by TASK-554 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, all shared with Task554Tests via ViaductV3CompleteChecks):
    test_01_geometry_and_rules: v2 rules, rest-pad/brake exceptions and 459-486 gaps at 540 -> v3 rules for all
    four S03 encounters, zero gray solids, direction right, 918-972 gaps at 1080 (v3/v2 >= 2.0 per gap against
    artifacts/TASK-511 and artifacts/TASK-512 geometry.json), a drag zone under every declared fall point.
    test_02_s03_03_nominal: crest-hook pull plus in-flight ledge catch into the ledge brake -> test_05_s03_03_nominal:
    blue shutter stop, green crest-hook pull up-right, release into the right map edge, rise to the apex.
    test_03_s03_04_nominal: trolley pull and re-catch into the exit brake on the gray exit pad -> test_06_s03_04_nominal:
    green exit-hook pull from the apex into S03-exit-drag, settle on the green exit ledge.
    test_04_full_traversal -> test_07_full_traversal (S03-01..04 in one run from the real S02 v3 exit pose).
    test_05_fall_through_drag_and_rejoin (mistimed span lift onto the S02 landing deck) ->
    test_08_fall_through_drag_and_rejoin (mistimed crest release through S02-exit-drag onto the green S02 exit
    ledge, input-only rejoin to the S03 exit; plus the declared S03-04 misses).
    test_06_source_hashes -> test_09_source_hashes. The inherited S03-01/02 cases (test_02-04) also run.
    The v2 constants below (S03_01/02/03/04, CREST, LEDGE, TROLLEY, PAD, NOMINAL, REJOIN, FALL, MOVERS,
    BUFFER, DRAG, BOXES, ...) stay only because the later v2 suite Task513Tests imports them.
    """
    task_id = 'TASK-512'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_09_source_hashes = V1Task465.test_03_source_hashes
    S03_01, S03_02 = Task511Tests.S03_01, Task511Tests.S03_02
    BASE_ROUTE = Task511Tests.BASE_ROUTE
    # S03-03: a steep crest-hook pull (held 45) clears the span buffer top; the ledge is then
    # acquired in flight past the apex (press 620, held 20) and pulls the arc into the brake.
    CREST, LEDGE, TROLLEY, PAD = (3520,-3715), (4107,-3632), (4353,-4055), (4680,-3832)
    S03_03 = [(455,'mousedown',*CREST),(500,'mouseup',*CREST),(620,'mousedown',*LEDGE),(640,'mouseup',*LEDGE)]
    # S03-04: the trolley pull (held 44), then a press toward the exit pad (890, held 15) whose ray
    # strikes the blue trolley's top face as the arc passes over it: the in-flight re-catch splits
    # the long trolley flight and tames the arc into the exit brake.
    S03_04 = [(755,'mousedown',*TROLLEY),(799,'mouseup',*TROLLEY),(890,'mousedown',*PAD),(905,'mouseup',*PAD)]
    NOMINAL = S03_01+S03_02+S03_03+S03_04
    # Mistimed S03-02: the span lift is released after 50 ticks instead of 65. The arc rebounds
    # off the buffer back over the span, drops through the S03 fall column onto the S02 landing
    # deck; the rejoin is the unchanged S02-03 crest-hook pull plus in-flight ledge catch.
    REJOIN = [(t+175, e, x, y) for t, e, x, y in Task510Tests.S02_03]
    FALL = S03_01+[(200,'mousedown',*Task511Tests.LIFT),(250,'mouseup',*Task511Tests.LIFT)]+REJOIN
    MOVERS = ('S03-carriage','S03-lift','S03-trolley')
    BUFFER = 'S03-span-buffer'
    DRAG = dict(id='S03-fall-drag', left=3030, right=3140, top=-3310, bottom=-2400)
    LEDGE_BRAKE = dict(id='S03-ledge-brake', left=4007, right=4207, top=-3710, bottom=-3630)
    EXIT_BRAKE = dict(id='S03-exit-brake', left=4600, right=4750, top=-3920, bottom=-3830)
    BAND, RANGE = (459, 486), 540
    REST = Task511Tests.REST
    BOXES = dict(Task511Tests.BOXES, **{
        'S03-03':dict(x=[4007,4167],y=[-3641,-3640],**REST),
        'S03-04':dict(x=[4600,4710],y=[-3841,-3840],**REST),
        'S02-landing':dict(x=[2987,3147],y=[-2111,-2110],**REST),
        'S02-ledge':dict(x=[2350,2510],y=[-2491,-2490],**REST)})


class ViaductV3ToleranceChecks(SwitchbackV3ToleranceChecks):
    """Layout-v3 Broken Viaduct (S03) tolerance on desktop 1280x720 and touch 844x390 (TASK-555).

    Proof kind (as TASK-553/554): the real S02 v3 exit settled pose of one base-start real-input
    S01+S02 v3 run is restored once as a labeled initial placement (initial_snapshot); production
    trusted mouse/touch input and physics run from there. An attempt on encounter k replays the S03
    route up to k: the encounter's inputs carry the variant, the earlier encounters keep their nominal
    inputs. S03-01..03 end in flight, so they are judged at their mountain.js exit boxes (position at
    the nominal exit tick 250/360/625); S03-04 at the S03 section exit (settled on the green exit
    ledge inside S03-exit-drag at tick 1300). check_s03_v3_mechanics requires the encounter's own
    mechanic, the S03 anchors in route order and no fall onto an S01/S02 bouncer or the lower bridge.
    Shared by Task555Tests and the re-specced Task513Tests.
    """
    VC = ViaductV3CompleteChecks
    SEGMENTS = [VC.S03_01_V3, VC.S03_02_V3, VC.S03_03_V3, VC.S03_04_V3]
    V3_ENCOUNTERS = [('S03-01','blue hoist pull up-left out of S02-exit-drag, release into the green west-pier rebound to the right',0,VC.S03_01_TICKS),
                     ('S03-02','blue span lift caught in flight off the west-pier rebound, release into the green east-pier rebound to the left',VC.S03_01_TICKS,VC.S03_02_TICKS),
                     ('S03-03','blue shutter stops the leftward flight, green crest-hook pull up-right, release into the right map edge and rise to the apex',VC.S03_02_TICKS,VC.S03_03_TICKS),
                     ('S03-04','green exit hook pulled from the apex into S03-exit-drag, settle on the green exit ledge (S03 section exit)',VC.S03_03_TICKS,None)]
    S04_TICKS = 1300
    STRICT = {'S03-01':VC.S03_01_EXIT, 'S03-02':VC.S03_02_EXIT, 'S03-03':VC.S03_03_EXIT}
    # Mistimed releases, one per encounter, no further input afterwards: (encounter, release tick
    # replacing the nominal one, nominal release tick, ticks, declared fall point or None, landing bouncer).
    # S03-04: the exit hook released 8 ticks after the catch (638) drops back down past the moved crest
    # hook through S02-exit-drag onto the green S02 exit ledge (no S03 fall point declares it). TASK-555:
    # a 633 release now lands on the crest hook (6330..6450, -7500), which has no drag zone above it.
    MISTIMED = [('S03-01',75,120,900,'S03-01-short','S02-exit-ledge'), ('S03-02',290,311,1300,'S03-02-missed','S03-lower-bridge'),
                ('S03-03',VC.EARLY_RELEASE,VC.CREST_RELEASE,1300,'S03-03-early','S02-exit-ledge'), ('S03-04',638,695,1700,None,'S02-exit-ledge')]
    V3_MOVERS = ViaductV3Checks.S03_V3_MOVERS
    # Client rectangles that open the pause menu (scanned with menu.clickToPause), per viewport width.
    PAUSE_BUTTON = {1280:dict(x=[1210,1261], y=[16,67]), 844:dict(x=[793,836], y=[5,48])}
    S02_V3_ROUTE, S02_V3_TICKS, S02_V3_SETTLE = ViaductV3Checks.S02_V3_ROUTE, ViaductV3Checks.S02_V3_TICKS, ViaductV3Checks.S02_V3_SETTLE
    S02_EXIT_DRAG, S02_V3_ACQUIRED = ViaductV3Checks.S02_EXIT_DRAG, ViaductV3Checks.S02_V3_ACQUIRED
    s02_v3_exit = ViaductV3Checks.s02_v3_exit

    def targets(self, trace, viewport):
        """Every press lands inside the viewport, outside the HUD block and outside the pause button."""
        rows = FoundationsV3ToleranceChecks.targets(self, trace, viewport)
        pause = self.PAUSE_BUTTON[viewport['width']]
        for r in rows:
            r['under_pause_button'] = self.inside(r['client'], pause)
        return rows

    def clear(self, targets):
        return all(t['in_viewport'] and not t['under_hud'] and not t['under_pause_button'] for t in targets)

    def density_v3(self, trace, name, start, end):
        """As FoundationsV3ToleranceChecks.density_v3; compact contacts carry no element id, so a mover
        contact is a contact point on the blue shutter's right face (the only S03 mover the player touches)."""
        face = self.VC.SHUTTER_FACE
        marks = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] == 'acquisition': element = e['after']['rope'][0]['id']
            if e['type'] == 'contact' and face['left'] <= e['contact']['x'] <= face['right'] and face['top'] <= e['contact']['y'] <= face['bottom']:
                element = 'S03-shutter'
            if e['type'] in ('acquisition','bounce') or (e['type']=='contact' and element in self.V3_MOVERS):
                if start <= e['tick'] <= end and (not marks or marks[-1]['tick'] != e['tick']):
                    marks.append(dict(tick=e['tick'], type=e['type'], element=element))
        points = [start]+[m['tick'] for m in marks]+[end]
        gaps = [b-a for a, b in zip(points, points[1:])]
        i = gaps.index(max(gaps))
        return dict(trace=name, window=[start, end], interactions=marks, max_gap=max(gaps),
                    longest_gap=[points[i], points[i+1]], cap=self.DENSITY_CAP)

    def exits(self):
        """Per encounter: (ticks, judged exit bounds, meaning), from the runtime manifest."""
        enc = {e['id']:e for e in self.report()['manifest']['encounters'][8:12]}
        out = {}
        for name, _, _, tick in self.V3_ENCOUNTERS:
            if tick:
                b = enc[name]['exit']
                out[name] = (tick, dict(x=[b['left'],b['right']], y=[b['top'],b['bottom']]),
                             f'inside the mountain.js {name} exit box at the nominal exit tick {tick}')
            else:
                out[name] = (self.S04_TICKS, self.VC.S03_04_EXIT,
                             'settled on S03-exit-ledge inside S03-exit-drag (S03 section exit) at tick %d' % self.S04_TICKS)
        return out

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s03_v3_mechanics
        start = self.s02_v3_exit()
        self.assertTrue(self.inside(start['player'], self.S02_V3_SETTLE), start['player'])
        exits = self.exits()
        source = hashes()
        suite = dict(section='S03', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='isolated: one labeled initial placement (initial_snapshot) = the real S02 v3 exit settled pose of a base-start '
                       'real-input S01+S02 v3 run (encounters/S02-exit-start), then production trusted mouse/touch input and physics; an '
                       'attempt on encounter k carries the variant on k and TASK-553/554 nominal inputs on S03-01..k-1',
            initial_placement=type(self).v3_s02_start_proof, browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exits={n: dict(ticks=t, box=b, meaning=w) for n, (t, b, w) in exits.items()},
            mechanics_check='tools/grapple_over_verify.py check_s03_v3_mechanics',
            nominal_note='every nominal press aims at its anchor; the S03-03 crest press aims at the hook itself, which is '
                         'clear of the touch pause button (hud-probe.json)',
            pause_button_client_rects={str(k): v for k, v in self.PAUSE_BUTTON.items()},
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal = [], {}
        for k, (name, mechanic, begin, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            ticks, bounds, meaning = exits[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), ticks, bounds, device, snapshot=start)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s03_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s03_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(self.clear(targets), (label, targets))
                        if exit_tick:
                            self.assertTrue(self.inside(players[exit_tick], self.STRICT[name]), (label, players[exit_tick]))
                            end = exit_tick
                        else:
                            end = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S03-exit-ledge')
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', begin, end)
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning),
                        outcome=f'{name} exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(LAYOUT_V3_DENSITY_CAP_TICKS = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','contact with the S03-shutter right face (S03-hoist/S03-lift are only rope anchors)'],
            cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal S03 run (0/250/360/625) to its manifest exit tick '
                   '(250/360/625) or, for S03-04, the exit-ledge landing; the settle on the exit ledge is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(start, exits['S03-04'])
        self.hud_probe(start)
        self.assertEqual(failures, [])
        print('PASS S03 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-exit-hook negative control fails the exit')

    def negative_control(self, start, exit):
        from grapple_over_verify import hashes, check_s03_v3_mechanics
        # Named omission: the S03-04 exit-hook press/release left out; same placement, physics and
        # S03-01..03 inputs as every S03-04 attempt.
        ticks, bounds, meaning = exit
        plan = self.variant_plan(3)[:6]
        m = self.make_input(plan, ticks, bounds, snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s03_v3_mechanics('S03-04', trace, required=False)
        self.evidence.write('negative-control.json', dict(name='omitted exit hook: S03-04 S03-exit-hook press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning), unchanged_physics=True, source_hashes=hashes(),
            proof_kind='same labeled S02-exit placement, real mouse input, same S03-01..03 inputs as the S03-04 attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step,
            exit_ledge_contact='S03-exit-ledge' in [b['element'] for b in mechanics['bounces']], final_player=players[-1],
            scope='Without the exit-hook pull the apex on the right map edge drops back down the edge (S03-04-missed), '
                  'through S03-fall-drag onto the green lower bridge, and the S03 section exit is missed.'))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S03-exit-hook', mechanics['acquisitions'])
        self.assertFalse(self.inside(players[-1], self.VC.S03_04_EXIT))
        self.assertLess(step, 60)

    def hud_probe(self, start):
        """The nominal S03-03 crest press aims at the hook itself: on each viewport its press point and the
        hook's drawn rectangle (mapped from world to client at the press) are clear of the pause button, and
        the tap acquires the hook. The TASK-555 rework moved the hook down-right out from under the touch
        pause button (it was at (6090,-7675), client ~791-807 x 34-39 on 844x390)."""
        from grapple_over_verify import check_s03_v3_mechanics
        plan = self.SEGMENTS[0]+self.SEGMENTS[1]+self.VC.S03_03_V3
        hook = self.bounds_v3(next(e for e in self.report()['manifest']['geometry']['elements'] if e['id']=='S03-crest-hook'))
        rows = {}
        for device in ('desktop','touch'):
            m = self.make_input(plan, 500, dict(y=[-1e9, 1e9]), device, snapshot=start)
            prefix = 'hud-probe/'+device
            trace, _, _ = self.run_attempt(m, prefix)
            viewport = m['metadata']['viewport']
            press = next(t for t in self.targets(trace, viewport) if t['tick']==400)
            # Client pixels per world unit: the 1080-unit logical height at the grapple_over camera scale.
            k = viewport['height']/1080*0.375
            to_client = lambda x, y: (press['client']['x']+(x-press['world']['x'])*k, press['client']['y']+(y-press['world']['y'])*k)
            (l, t), (r, b) = to_client(hook['left'], hook['top']), to_client(hook['right'], hook['bottom'])
            # Cross-check of the mapping: the camera is clamped to the right map edge (x 6480) at the press.
            edge = to_client(6480, 0)[0]
            self.assertLess(abs(edge-viewport['width']), 2, (device, edge))
            pause = self.PAUSE_BUTTON[viewport['width']]
            overlap = l <= pause['x'][1] and r >= pause['x'][0] and t <= pause['y'][1] and b >= pause['y'][0]
            margin = min(t-pause['y'][1] if l <= pause['x'][1] else 1e9, pause['x'][0]-r if t <= pause['y'][1] else 1e9)
            acquired = check_s03_v3_mechanics('S03-03', trace, required=False)['acquisitions']
            rows[device] = dict(input=prefix+'/input.json.gz', trace=prefix+'/trace.json', press=press,
                                hook_client_rect=dict(x=[l, r], y=[t, b]), right_map_edge_client_x=edge,
                                hook_overlaps_pause_button=overlap, clearance_px=margin,
                                crest_hook_acquired='S03-crest-hook' in acquired, acquisitions=acquired)
            self.assertFalse(press['under_pause_button'], rows[device])
            self.assertFalse(overlap, rows[device])
            self.assertGreaterEqual(margin, 8, rows[device])
            self.assertTrue(rows[device]['crest_hook_acquired'], rows[device])
            print('PASS hud probe', device, ': crest press client', (round(press['client']['x']), round(press['client']['y'])),
                  '; hook drawn at client x', [round(l), round(r)], 'y', [round(t), round(b)], '; pause button', pause,
                  '; clearance', round(margin, 1), 'px; hook acquired', flush=True)
        self.evidence.write('hud-probe.json', dict(finding_closed='The S03-crest-hook was moved from (6090,-7675) to '
            '(6330,-7500) (and the east pier top lowered from -7300 to -7000 so the pull clears it), so at the S03-03 press '
            'pose its drawn rectangle and the nominal aim point (the hook itself) are below the touch pause button; '
            'the tap acquires the hook on both viewports.',
            aim_point=self.VC.CREST_V3, hook_world_rect=hook, client_px_per_world={'1280':720/1080*0.375, '844':390/1080*0.375},
            pause_button_client_rects={str(k): v for k, v in self.PAUSE_BUTTON.items()}, runs=rows))

    def test_02_mistimed_release_no_bounce_back(self):
        from grapple_over_verify import check_s03_v3_mechanics
        start = self.s02_v3_exit()
        elements = {e['id']:e for e in self.report()['manifest']['geometry']['elements']}
        zones = {k: self.bounds_v3(e) for k, e in elements.items() if e['role']=='drag' and k.startswith(('S01-','S02-','S03-'))}
        falls = {f['id']:f for f in self.report()['report']['sections'][2]['rules']['dragUnderFall']['measured']['fallPoints']}
        inzone = lambda p, b: b['left'] <= p['x'] <= b['right'] and b['top'] <= p['y'] <= b['bottom']
        rows = {}
        for k, (name, release, nominal, ticks, fall_id, landing_id) in enumerate(self.MISTIMED):
            segment = self.SEGMENTS[k]
            self.assertEqual(segment[1][0], nominal)
            for device in ('desktop','touch'):
                plan = [p for seg in self.SEGMENTS[:k] for p in seg]+[segment[0], (release,)+segment[1][1:]]
                m = self.make_input(plan, ticks, dict(y=[-1e9, 1e9]), device, snapshot=start)
                prefix = f'clips/fall-{name}-{device}'
                trace, success, reason = self.run_attempt(m, prefix, True)
                self.assertTrue(success, reason)
                self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                mech = check_s03_v3_mechanics(name, trace, required=False)
                anchor = mech['encounter']['anchor']
                rel = next(r for r in mech['releases'] if r['element']==anchor)
                self.assertEqual(rel['tick'], release)
                r_player = players[release]
                bounces = [e for e in trace['events'] if e['type']=='bounce' and e['tick'] > release]
                landings = [e for e in bounces if e['contact']['elementId']==landing_id]
                self.assertTrue(landings, name)
                landing = landings[0]; land = landing['tick']
                self.assertEqual(elements[landing_id]['role'], 'bounce')
                # The landing bouncer is the first surface bounced after the release (no glances on the way down).
                self.assertEqual(bounces[0]['tick'], land, (name, bounces[0]['contact']))
                crossed = {z: [t for t in range(release, land+1) if inzone(players[t], b)] for z, b in zones.items()}
                crossed = {z: ts for z, ts in crossed.items() if ts}
                self.assertTrue(crossed, name)
                # The landing is inside or directly below the last drag zone crossed.
                last = max(crossed, key=lambda z: crossed[z][-1])
                self.assertLessEqual(land - crossed[last][-1], 120, (name, last))
                rest_y = landing['after']['simulation']['player']['y']
                apex_tick = min(range(release, land), key=lambda t: players[t]['y'])
                second = next((e['tick'] for e in landings if e['tick'] > land+1), ticks)
                peak_tick = min(range(land+1, second), key=lambda t: players[t]['y'])
                release_height = rest_y - r_player['y']
                peak_height = rest_y - players[peak_tick]['y']
                fall_height = rest_y - players[apex_tick]['y']
                self.assertGreater(release_height, 0, name)
                self.assertLessEqual(peak_height, .5*release_height, name)
                self.assertLessEqual(peak_height, .5*fall_height, name)
                targets = self.targets(trace, m['metadata']['viewport'])
                self.assertTrue(self.clear(targets), targets)
                step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
                self.assertLess(step, 60)
                declared = falls[fall_id] if fall_id else None
                if declared:
                    self.assertEqual(declared['firstBouncer'], landing_id)
                row = dict(encounter=name, device=device, viewport=m['metadata']['viewport'], anchor=anchor,
                    mistiming=f'{anchor} released at tick {release} instead of {nominal}; no further input',
                    input=prefix+'/input.json.gz', trace=prefix+'/trace.json', filmstrip=prefix+'/filmstrip.jpg',
                    release=dict(tick=release, player=r_player), landing_rest_y=rest_y,
                    release_height=release_height, release_height_definition='landing-bouncer bounce y minus player y at the release tick',
                    apex=dict(tick=apex_tick, y=players[apex_tick]['y']), fall_height_from_apex=fall_height,
                    bounces_before_landing=[],
                    drag_zones_crossed=[dict(id=z, box=zones[z], ticks=[ts[0], ts[-1]], entry_player=players[ts[0]],
                        exit_player=players[ts[-1]]) for z, ts in sorted(crossed.items(), key=lambda x: x[1][0])],
                    declared_fall_point=dict(id=fall_id, x=declared['x'], dragZones=declared['dragZones'], firstBouncer=declared['firstBouncer'])
                        if declared else dict(id=None, note='undeclared S03 line: drops from the map-edge apex past the crest hook '
                                                            'through S02-exit-drag onto the S02 exit ledge (S02 declared drag column)'),
                    first_bounce=dict(element=landing_id, tick=land, before=landing['before']['simulation']['player'],
                        after=landing['after']['simulation']['player']),
                    first_bounce_peak=dict(tick=peak_tick, y=players[peak_tick]['y'], height=peak_height,
                        fraction_of_release_height=peak_height/release_height, fraction_of_apex_fall=peak_height/fall_height),
                    at_most_half_of_release_height=True, max_tick_displacement=step, press_targets=targets, relocation=False)
                rows.setdefault(name, {})[device] = row
                print('PASS fall', name, device, ': release tick', release, 'y', round(r_player['y'],1), '; drag zones',
                      [d['id'] for d in row['drag_zones_crossed']], '; first bounce', landing_id, 'tick', land, '; first peak',
                      round(peak_height,1), '=', round(peak_height/release_height,3), 'of release height', round(release_height,1))
        self.evidence.write('no-bounce-back.json', dict(self.proof, rule='a mistimed release passes through the drag zone below '
            'it and its first bounce peaks at most 50% of the release height (i.e. at least 50% lower)',
            proof_kind='labeled S02-exit placement, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation',
            encounters=rows, passed=True))


class Task513Tests(ViaductV3ToleranceChecks, unittest.TestCase):
    """Broken Viaduct (S03) tolerance, re-specced by TASK-555 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, shared with Task555Tests via ViaductV3ToleranceChecks):
    test_01_tolerance_matrix: v2 S03-01 from the v2 S02 exit-pad rest and S03-02..04 from restored v2
    rest states (starts/trace.json), 180-tick density, mistimed-lift negative control -> v3 S03-01..04 from
    the labeled real S02 v3 exit pose, S03-01..03 judged at their mountain.js exit boxes and S03-04 at the
    exit-ledge settle, 254-tick density cap, omitted-exit-hook negative control, touch pause-button probe.
    test_02_full_traversal: the v3 full route is the nominal S03-04 attempt of test_01 (and Task554
    test_07). test_03_drag_zone_fall_clips -> test_02_mistimed_release_no_bounce_back (one mistimed
    release per encounter through a drag zone onto a green bouncer, desktop and touch).
    test_04_source_hashes is unchanged. The v2 constants below stay only because the later v2 suite
    Task514Tests builds its base route from NOMINAL.
    """
    task_id = 'TASK-513'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_04_source_hashes = V1Task465.test_03_source_hashes
    CREST, TROLLEY, TOP = (3508,-3715), Task512Tests.TROLLEY, (4380,-4086)
    S03_03 = [(455,'mousedown',*CREST),(500,'mouseup',*CREST)]+Task512Tests.S03_03[2:]
    S03_04 = [(755,'mousedown',*TROLLEY),(801,'mouseup',*TROLLEY),(885,'mousedown',*TOP),(900,'mouseup',*TOP)]
    NOMINAL = Task512Tests.S03_01+Task512Tests.S03_02+S03_03+S03_04


V2_S04_REVISION = '5be68ed'
# What happened to every static v2 S04 solid in the layout-v3 rebuild (TASK-556).
V2_S04_DISPOSITION = {
    'S04-pier':('deleted','v2 S04-01 landing / S04-02 launch rest pad; the v3 S04-01 ends in flight off the green reflector plate'),
    'S04-press-deck':('deleted','v2 S04-02 landing rest pad under the flat press; the v3 S04-02 ends in flight off the green angled deflector'),
    'S04-upper-step':('converted-to-bounce','Legacy v1 Cable Galleries recovery step (recoveries[4] opening element); kept in place '
                      'with its shape, now a green bouncer; no v3 S04 route uses it'),
    'S04-exit':('converted-to-bounce','Legacy v1 Cable Galleries entrance deck (the v1 S05-01 start and encounters[16] element); kept in '
                'place with its shape, now a green bouncer; no v3 S04 route uses it')}
# The other v2 S04 elements (movers, bouncers): deleted or id re-used by a new v3 element.
V2_S04_OTHER = {'S04-carriage':'deleted', 'S04-flat-press':'deleted',
    'S04-lift':'id re-used: new blue x mover (2240,-8030) 120x30 for the v3 S04-02 in-flight lift catch'}
V3_S04_ADDED = ('S04-hoist','S04-reflector','S04-deflector','S04-catch-basin','S04-fall-drag',
    # TASK-515: S04-03/04 and the S04 exit.
    'S04-crest-hook','S04-baffle','S04-exit-hook','S04-exit-ledge','S04-exit-drag',
    # TASK-491: the green recovery hook over the catch basin (the basin was a dead end).
    'S04-basin-hook')


class DeflectorV3Checks:
    """Layout-v3 Deflector Works opening (S04-01/02) from the real S03 v3 exit settled pose (TASK-556).

    The start pose comes from ONE base-start real-input run with no placement: the v3 S01 route
    (TASK-548 inputs), the v3 S02 route (TASK-551 inputs from tick 1495) and the v3 S03 route (TASK-554/555
    inputs from tick 3245), 4545 ticks, settling on the green S03 exit ledge inside S03-exit-drag. It is
    restored once as a labeled initial placement (initial_snapshot), then production trusted input and
    physics run. Not a continuous-completion claim. TASK-515 completed S04-03/04, so test_01 asserts the
    completed section (DeflectorV3CompleteChecks runs the S04-03/04 cases).
    Shared by Task556Tests and the re-specced Task514Tests (same cases, task-local evidence).
    """
    VC = ViaductV3CompleteChecks
    S03_V3_ROUTE = ViaductV3Checks.S02_V3_ROUTE+[(t+3245, e, x, y) for t, e, x, y in VC.S03_ROUTE_V3]
    S03_V3_TICKS = 3245+1300
    S03_V3_SETTLE = VC.S03_04_EXIT
    S03_EXIT_DRAG = VC.S03_EXIT_DRAG
    S03_V3_ACQUIRED = ViaductV3Checks.S02_V3_ACQUIRED+['S03-hoist','S03-lift','S03-crest-hook','S03-exit-hook']
    # TASK-516: the hoist and lift aims are the exact world points of the desktop press pixels (968,340)
    # and (254,295) (the TASK-556 aims (5234,-7860) and (2350,-8000) rounded to them), so the unquantized
    # touch press aims at the same point and the touch route matches the desktop route; the near-
    # horizontal hoist ray turned the 1-unit difference into a 12-unit catch shift and a climb apex 128 lower.
    HOIST_V3, LIFT_V3 = (5232,-7861.14027745556), (2346.1409516605668,-8003.252822407399)
    # S04-01: the hoist is pulled near-horizontally west along the S03 exit ledge (the legacy S06 loading
    # floor caps the exit drag zone); the player slides out of the drag's west end (tick ~295) and swings
    # under the hoist; the release at 370 flies west onto the flat green reflector plate.
    # S04-02: on the rebound the lift press at 486 catches the blue lift in flight; the release at 556
    # flies up-left into the angled green deflector, which turns the flight into a climb.
    S04_01_V3 = [(5,'mousedown',*HOIST_V3),(370,'mouseup',*HOIST_V3)]
    S04_02_V3 = [(486,'mousedown',*LIFT_V3),(556,'mouseup',*LIFT_V3)]
    S04_V3_MOVERS = ('S04-hoist','S04-lift')
    S04_V3_BAND = (918, 972)
    V2_GAPS = ('S04-01-carriage','S04-02-lift')
    # Exit boxes (also the manifest encounter exits), judged in flight: falling west after the
    # reflector rebound; climbing up-left after the deflector.
    S04_01_EXIT = dict(x=[3200,3400], y=[-7600,-7480], speedX=[-2.2,-1.9], speedY=[-.7,-.45])
    S04_02_EXIT = dict(x=[780,920], y=[-9100,-8950], speedX=[-.85,-.65], speedY=[-1.85,-1.55])
    S04_01_TICKS, S04_02_TICKS = 480, 640
    # TASK-515: S04-03 is judged at the apex on the left map edge (the S04-04 press, tick 1040 since
    # TASK-516); S04-04 is the settled pose on the green exit ledge inside S04-exit-drag.
    S04_03_EXIT = dict(x=[0,30], y=[-11600,-11380], speedX=[-.01,.01], speedY=[-.3,.1])
    S04_04_EXIT = dict(x=[1350,1740], y=[-11680,-11650], speedX=[-.001,.001], speedY=[-.05,.05])
    S04_V3_FALLS = {'S04-01-short':(['S03-exit-drag'],'S03-exit-ledge'), 'S04-02-missed':(['S04-fall-drag'],'S04-catch-basin'),
        'S04-01-late':(['S03-exit-drag'],'S03-exit-ledge'), 'S04-03-missed':(['S04-fall-drag'],'S04-catch-basin'),
        'S04-04-missed':(['S04-fall-drag'],'S04-catch-basin'), 'S04-04-overshoot':(['S04-exit-drag'],'S04-exit-ledge')}
    S04_V3_GAPS = ('S04-01-hoist','S04-02-lift','S04-03-crest','S04-04-exit')
    S04_V3_ROUTE_ELEMENTS = ('S04-hoist','S04-reflector','S04-lift','S04-deflector','S04-catch-basin',
                             'S04-crest-hook','S04-baffle','S04-exit-hook','S04-exit-ledge')
    # Declared misses: a short hoist hold (released at 150) never leaves S03-exit-drag and settles on the
    # green S03 exit ledge; no lift catch carries the reflector rebound into the left map edge, down
    # through S04-fall-drag onto the green catch basin.
    S04_01_SHORT = [(5,'mousedown',*HOIST_V3),(150,'mouseup',*HOIST_V3)]
    SHORT_SETTLE = VC.OVERSHOOT_SETTLE
    S04_FALL_DRAG = dict(left=0, right=300, top=-6440, bottom=-6000)
    BASIN_SETTLE = dict(x=[0,300], y=[-6030,-6000], speedX=[-.001,.001], speedY=[-.05,.05])
    report = FoundationsV3Checks.report
    bounds_v3 = staticmethod(SwitchbackV3Checks.bounds_v3)
    inside = staticmethod(FoundationsV3CompleteChecks.inside)
    in_box = staticmethod(FoundationsV3CompleteChecks.in_box)
    fall_s03 = ViaductV3Checks.fall_s03

    def v2_s04(self):
        """The layout-v2 S04 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V2_S04_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[3], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, elements:m.geometry.elements.filter(e=>e.id.startsWith('S04-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S04-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S04-'))}}''', source)

    def s03_v3_exit(self):
        """Real S03 v3 exit settled pose: one base-start real-input run of the v3 S01, S02 and S03 routes (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'v3_s03_start'): return type(self).v3_s03_start
        m = dict(metadata=metadata('base-start'), ticks=self.S03_V3_TICKS, expected_exit=self.S03_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.S03_V3_ROUTE],
            required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/S03-exit-start'
        self.evidence.write(prefix+'/input.json', m)
        setup = execute(m, self.browser, self.url, str(self.evidence.path(prefix)))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual([a for a in acquired if a not in ('S01-entry-pad','S02-exit-ledge')], self.S03_V3_ACQUIRED)
        touched = sorted({(e.get('contact') or {}).get('elementId') for e in setup['events']} - {None})
        self.assertFalse([t for t in touched if t.startswith('S04-')], touched)
        self.evidence.write(prefix+'/trace.json', Task506Tests.compact(self, setup))
        settle = next(t for t in range(3245+700, self.S03_V3_TICKS+1)
                      if all(self.inside(p, self.S03_V3_SETTLE) for p in players[t:]))
        self.assertLessEqual(settle, 3245+1250)
        start = setup['snapshots'][-1]['state']['simulation']
        self.assertTrue(self.in_box(start['player'], self.S03_EXIT_DRAG))
        self.assertEqual((round(start['player']['x'],1), round(start['player']['y'],1)), (6127.0, -7781.1))
        # Clearance of the whole S01+S02+S03 v3 flight from the new S04 route colliders.
        m2 = self.report()['manifest']
        travel = {v['element']:v for v in m2['geometry']['movers']}
        clearance = {}
        for e in m2['geometry']['elements']:
            if not e['id'].startswith('S04-') or e['role'] == 'drag': continue
            b = self.bounds_v3(e, travel.get(e['id']))
            gap = min(math.hypot(max(b['left']-p['x'], 0, p['x']-b['right']), max(b['top']-p['y'], 0, p['y']-b['bottom']))
                      for p in players)
            clearance[e['id']] = gap - players[0]['radius']
            self.assertGreater(clearance[e['id']], 50, (e['id'], clearance))
        type(self).v3_s03_start = start
        type(self).v3_s03_start_proof = dict(kind='base-start v3 S01 route (TASK-548 inputs), v3 S02 route (TASK-551 inputs '
            'from tick 1495) and v3 S03 route (TASK-554/555 inputs from tick 3245), real mouse input, no placement', inputs=m['inputs'],
            acquisitions=acquired, settled_in_exit_box_from_tick=settle, settle_box=self.S03_V3_SETTLE, final_tick=self.S03_V3_TICKS,
            player=start['player'], inside_S03_exit_drag=True, snapshot_sha256=setup['snapshots'][-1]['sha256'],
            full_trace_sha256=state_hash(setup), trace=prefix+'/trace.json', s04_element_contacts=[],
            s01_s03_flight_clearance_to_s04_elements=clearance, range_upgraded=start['upgrades']['range'])
        self.evidence.write(prefix+'/result.json', dict(passed=True, **type(self).v3_s03_start_proof))
        return start

    def run_s04(self, name, plan, ticks, bounds, density_until=None, folder='encounters'):
        """Labeled placement of the real S03 v3 exit pose, then trusted input; identical replay."""
        from grapple_over_verify import metadata, execute, check_trace
        start = self.s03_v3_exit()
        m = dict(metadata=metadata('isolated'), inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=['acquisition','release','bounce'], initial_snapshot=start)
        m['metadata']['compact_contacts'] = True
        prefix = folder+'/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=folder == 'encounters')
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, Task506Tests.compact(self, t))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        self.assertTrue(self.inside(players[0], self.S03_V3_SETTLE), players[0])
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce') or (e['type']=='contact' and element in self.S04_V3_MOVERS):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    mover=element in self.S04_V3_MOVERS, player=e['after']['simulation']['player'], rope=e['after']['rope']))
        # Longest stretch without an acquisition, bounce or mover contact (LAYOUT_V3_DENSITY_CAP_TICKS).
        until = ticks if density_until is None else density_until
        marks = sorted({0, until, *[x['tick'] for x in mechanics if x['type'] != 'release' and x['tick'] <= until]})
        stretch = max(b-a for a, b in zip(marks, marks[1:]))
        self.assertLessEqual(stretch, 254)
        travel = {}
        for mover in self.S04_V3_MOVERS:
            anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']==mover]
            if anchors:
                travel[mover] = dict(dx=anchors[-1]['x']-anchors[0]['x'], dy=anchors[-1]['y']-anchors[0]['y'], ticks=len(anchors))
        # Mechanic events keep S04 elements and the S03 exit ledge only as a count (it bounces every few ticks).
        ledge = [x['tick'] for x in mechanics if x['element'] == 'S03-exit-ledge']
        result = dict(passed=True, matching_traces=True, trusted_inputs=True,
            proof_kind='isolated: one labeled initial placement = restoreClimbState of the real S03 v3 exit settled pose '
                       'from one base-start real-input S01+S02+S03 v3 run; production input/physics thereafter',
            initial_placement=dict(labeled=True, source=type(self).v3_s03_start_proof), not_continuous_completion_claim=True,
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[{k:x[k] for k in ('tick','type','element','mover','player')} for x in mechanics if x['element'] != 'S03-exit-ledge'],
            s03_exit_ledge_bounces=dict(count=len(ledge), first=ledge[0] if ledge else None, last=ledge[-1] if ledge else None),
            mover_anchor_travel_while_attached=travel, longest_stretch_without_mechanic_ticks=stretch, density_cap_ticks=254,
            density_measured_until_tick=until,
            final=players[-1], expected_exit=bounds, final_in_exit_box=self.inside(players[-1], bounds),
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        self.assertTrue(result['final_in_exit_box'], players[-1])
        return trace, players, mechanics, result

    def reach_s04(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.S04_V3_BAND[0] <= distance <= self.S04_V3_BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y'],speedX=p['speedX'],speedY=p['speedY']), anchor=a['rope'][0],
            band=list(self.S04_V3_BAND), in_band=True)

    def s04_kinds(self, mech):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S03-exit-ledge' and e['type'] != 'contact']

    def bounce_s04(self, trace, element):
        b = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']==element)
        return b, b['before']['simulation']['player'], b['after']['simulation']['player']

    def test_01_geometry_and_rules(self):
        r = self.report(); v2 = self.v2_s04()
        m = r['manifest']; elements = m['geometry']['elements']
        s04 = m['sections'][3]
        # Completed by TASK-515: all four encounters, their connectors and the S04 recovery are built.
        self.assertEqual((s04['designVersion'], s04['status']), (3, 'built'))
        enc_all = m['encounters'][12:16]
        self.assertEqual([e['status'] for e in enc_all], ['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][12:16]], ['built']*4)
        self.assertEqual((m['connectors'][12]['from'], m['connectors'][12]['to']), ('S03-04','S04-01'))
        # TASK-517 rebuilt S05-01 from the S04 v3 exit ledge, so the S05 entrance is built.
        self.assertEqual((m['connectors'][16]['from'], m['connectors'][16]['status']), ('S04-04', 'built'))
        self.assertEqual((m['recoveries'][3]['status'], m['recoveries'][3]['rejoin']), ('built', 'S04-01'))
        self.assertNotIn('solidExceptions', s04)
        self.assertNotIn('fallLines', s04)
        self.assertEqual((s04['band']['top'], s04['band']['bottom']), (-8100, -4860))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S04-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S04-')}
        self.assertEqual(set(movers), set(self.S04_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        # The angled deflector face is a true 45-degree slope (not axis-aligned).
        d = by_id['S04-deflector']['points']
        self.assertEqual((d[1]['x']-d[0]['x'], d[1]['y']-d[0]['y']), (300, 300))
        enc = {e['id']:e for e in enc_all}
        self.assertEqual(enc['S04-01']['start'], {'x':6127,'y':-7781.1,'from':'S03-04'})
        self.assertEqual(enc['S04-02']['start'], {'from':'S04-01','x':3194.9,'y':-7569.5})
        self.assertEqual(enc['S04-03']['start'], {'from':'S04-02','x':10.8,'y':-10385.5})
        self.assertEqual(enc['S04-04']['start'], {'from':'S04-03','x':10.8,'y':-11507.2})
        for e in enc.values():
            self.assertTrue(all(x in by_id for x in e['elements']), e['id'])
            self.assertTrue(any(by_id[x]['role'] == 'bounce' for x in e['elements']), e['id'])
        # Blue movers carry S04-01/02 (the mover rule needs two of the four encounters).
        for e in enc_all[:2]:
            self.assertTrue(any(x in movers for x in e['elements']), e['id'])
        for name, box in (('S04-01', self.S04_01_EXIT), ('S04-02', self.S04_02_EXIT), ('S04-03', self.S04_03_EXIT), ('S04-04', self.S04_04_EXIT)):
            self.assertEqual(enc[name]['exit'], dict(left=box['x'][0], right=box['x'][1], top=box['y'][0], bottom=box['y'][1]))
        sec = r['report']['sections'][3]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S04', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][:4], ['S01','S02','S03','S04'])
        self.assertFalse(r['report']['failed'])
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('left', 'left'))
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S04-01','S04-02'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S04_V3_BAND))
        self.assertEqual([g['id'] for g in gaps], list(self.S04_V3_GAPS))
        for g in gaps:
            self.assertTrue(self.S04_V3_BAND[0] <= g['distance'] <= self.S04_V3_BAND[1], g)
        # Every declared S04 miss falls through a drag zone onto a green bouncer.
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], list(self.S04_V3_FALLS))
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), self.S04_V3_FALLS[f['id']], f)
            self.assertEqual(by_id[f['firstBouncer']]['role'], 'bounce')
            for dz in f['dragZones']:
                b = self.bounds_v3(by_id[dz])
                # The column is clipped at the left map edge (x 0): the player centre cannot pass x 10.8.
                self.assertTrue(b['left'] <= max(f['x']-18, 0) and f['x']+18 <= b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, dz))
        # Filtered to S04 fall points: the TASK-517 S05-01-short line also drops through S04-exit-drag.
        self.assertEqual([dict(d, fallPoints=[f for f in d['fallPoints'] if f.startswith('S04-')]) for d in sec['rules']['strayDrag']['measured']['dragZones']], [
            dict(id='S04-fall-drag', fallPoints=['S04-02-missed','S04-03-missed','S04-04-missed']),
            dict(id='S04-exit-drag', fallPoints=['S04-04-overshoot'])])
        # v2/v3 ratio against the v2 S04-01/02 gaps recorded by TASK-514 (and the v2 source).
        v2_geometry = json.loads((ROOT/'artifacts/TASK-514/geometry.json').read_text())
        v2_gaps = {g['id']:g for g in v2_geometry['manifest_section']['gaps']}
        self.assertEqual([v2_gaps[k] for k in self.V2_GAPS], v2['section']['gaps'][:2])
        dist = lambda g: ((g['to']['x']-g['from']['x'])**2+(g['to']['y']-g['from']['y'])**2) ** .5
        v2_d = {k:dist(v2_gaps[k]) for k in self.V2_GAPS}
        v3_all = {g['id']:g['distance'] for g in gaps}
        # The ratio compares the rebuilt S04-01/02 with their v2 versions (v2 S04-03/04 were never built).
        v3_d = {k:v3_all[k] for k in ('S04-01-hoist','S04-02-lift')}
        v2_mean, v3_mean = sum(v2_d.values())/2, sum(v3_d.values())/2
        ratio = v3_mean/v2_mean
        self.assertGreaterEqual(ratio, 2.0)
        per_gap = {k3:v3_d[k3]/v2_d[k2] for k3, k2 in zip(('S04-01-hoist','S04-02-lift'), self.V2_GAPS)}
        self.assertTrue(all(x >= 2.0 for x in per_gap.values()), per_gap)
        # Every static v2 S04 solid is deleted or converted to a green bouncer.
        self.assertEqual(sorted(v2['staticSolids']), sorted(V2_S04_DISPOSITION))
        own_ids = {e['id'] for e in own}
        v2_by_id = {e['id']:e for e in v2['elements']}
        mapping = []
        for old in v2['staticSolids']:
            kind, why = V2_S04_DISPOSITION[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertNotIn(old, own_ids, old)
            else:
                self.assertEqual(now['role'], 'bounce', old)
                self.assertEqual((now['x'], now['y'], now['points']), (v2_by_id[old]['x'], v2_by_id[old]['y'], v2_by_id[old]['points']), old)
            mapping.append(dict(id=old, v2_role='solid', disposition=kind, v3_role=now['role'] if now else None, reason=why))
        v2_ids = set(v2_by_id)
        self.assertEqual(sorted(v2_ids - set(V2_S04_DISPOSITION)), sorted(V2_S04_OTHER))
        for old, what in V2_S04_OTHER.items():
            self.assertEqual(old in own_ids, what.startswith('id re-used'), old)
        self.assertEqual(sorted(own_ids - v2_ids), sorted(V3_S04_ADDED))
        # No v3 S04 route element overlaps a legacy S05/S06 collider or the S03 v3 colliders.
        route = [by_id[x] for x in self.S04_V3_ROUTE_ELEMENTS]
        travel = {v['element']:v for v in m['geometry']['movers']}
        others = [e for e in elements if e['id'].split('-')[0] in ('S03','S05','S06','S07') and e['role'] != 'drag']
        for a in route:
            ba = self.bounds_v3(a, travel.get(a['id']))
            for o in others:
                bo = self.bounds_v3(o, travel.get(o['id']))
                self.assertFalse(ba['left'] < bo['right'] and bo['left'] < ba['right'] and ba['top'] < bo['bottom'] and bo['top'] < ba['bottom'], (a['id'], o['id']))
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S04-01','S04-02','S04-03','S04-04'], planned=[],
            gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=v3_all, v2_gap_distances=v2_d, v2_gap_source='artifacts/TASK-514/geometry.json manifest_section.gaps',
            v2_mean_gap=v2_mean, v3_mean_gap=v3_mean, v3_over_v2_mean_ratio=ratio, v3_over_v2_per_gap=per_gap,
            ratio_at_least_2=True, direction=direction,
            direction_note='the direction rule reads the S04-04 exit box centre (the S04 exit ledge, x 1545) against the S04-01 entry x '
                           '(6127); every encounter exit lies west of the entry (exit boxes centred at x 3300, 850, 15 and 1545)',
            fall_points=falls, own_drag_zones=sec['rules']['strayDrag']['measured']['dragZones'],
            drag_below_every_fall_point=True, gray_solid_count=len(gray)))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s04, encounters=enc_all, planned_encounters=[],
            connectors=m['connectors'][12:17], recovery=m['recoveries'][3], elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True, v2_revision=V2_S04_REVISION,
            v2_static_solids=v2['staticSolids'], v2_solid_disposition=mapping, v2_other_elements=V2_S04_OTHER,
            v3_added=list(V3_S04_ADDED), route_overlaps_with_s03_s07_colliders=[]))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1303" viewBox="-100 -12700 6680 6800" style="background:#111827">']
        for e in elements:
            if e['id'].split('-')[0] not in ('S03','S05','S06','S07','S08'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.18' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="4"/>')
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors[roles[e['id']]] + ('" fill-opacity="0.35' if roles[e['id']] == 'yellow drag' else '')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="4"/>'
                         f'<text x="{e["x"]+(20 if e["x"] < 600 else 0)+(80 if e["id"] == "S04-baffle" else 0)}" y="{e["y"]-24+(260 if e["id"] == "S04-baffle" else 0)}" fill="white" font-size="64">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+15}" x2="{e["x"]+60+dx}" y2="{e["y"]+15+dy}" stroke="#93c5fd" stroke-width="8" stroke-dasharray="16,10"/>')
        for g in s04['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="8" stroke-dasharray="16,12"/>')
        for f in falls:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="{f["firstBouncerTop"]}" stroke="#fb923c" stroke-width="6" stroke-dasharray="8,16"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="22" fill="#fb923c"/><text x="{f["x"]+(40 if f["x"] < 600 else -560)}" y="{f["y"]+20}" fill="#fb923c" font-size="60">{f["id"]}</text>')
        for e in enc_all:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="8"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+70}" fill="#f472b6" font-size="60">{e["id"]} exit</text>')
        parts.append('<circle cx="6127" cy="-7781.1" r="40" fill="#ff7a1a"/>')
        for i, t in enumerate(['S04 Deflector Works v3 (designVersion 3, travelling left), zero gray solids',
                'orange dot = real S03 v3 exit settled pose; grey = S03/S05-S08',
                'S04-01: blue hoist west out of S03-exit-drag -> flat green reflector',
                'S04-02: blue lift caught in flight -> angled green deflector -> climb',
                'S04-03: green crest hook at the climb apex -> green baffle -> left edge',
                'S04-04: green exit hook at the 2nd apex -> S04-exit-drag -> exit ledge',
                'yellow dashes = gaps %s of 1080' % '/'.join(str(round(g['distance'],1)) for g in gaps),
                'orange = fall points over drag zones; pink = exit boxes']):
            parts.append(f'<text x="1300" y="{-10560+i*80}" fill="#67e8f9" font-size="64">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=dict(width=1280, height=1303)); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S04 designVersion 3 built (S04-01..04); gray solids', len(gray), '; roles',
              sorted(set(roles.values())), '; all 7 v3 rules pass; direction left', direction['exitX'], '<', direction['entryX'],
              '; gaps', [round(g['distance'],1) for g in gaps], '; v3/v2 mean ratio', round(ratio,4), {k:round(v,4) for k, v in per_gap.items()},
              '; fall points over drag', {f['id']:f['dragZones'] for f in falls}, '; v2 solids', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def s04_01_checks(self, trace, players, mech, result):
        out = next(t for t, p in enumerate(players) if t > 5 and not self.in_box(p, self.S03_EXIT_DRAG))
        self.assertLess(out, 370)
        self.assertTrue(all(abs(players[t]['y']-players[0]['y']) < 15 for t in range(out)))
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S04-hoist']['dy']), 1)
        bounce, before, after = self.bounce_s04(trace, 'S04-reflector')
        # Flat reflection: horizontal speed kept, vertical speed mirrored.
        self.assertLess(before['speedX'], -1.5); self.assertGreater(before['speedY'], .3)
        self.assertAlmostEqual(after['speedX'], before['speedX'], places=6)
        self.assertAlmostEqual(after['speedY'], -before['speedY'], delta=.02)
        self.assertTrue(self.inside(players[self.S04_01_TICKS], self.S04_01_EXIT), players[self.S04_01_TICKS])
        return out, bounce, before, after

    def test_02_s04_01_nominal(self):
        trace, players, mech, result = self.run_s04('S04-01', self.S04_01_V3, self.S04_01_TICKS, self.S04_01_EXIT)
        self.assertEqual(self.s04_kinds(mech), [('acquisition','S04-hoist'),('release','S04-hoist'),('bounce','S04-reflector')])
        out, bounce, before, after = self.s04_01_checks(trace, players, mech, result)
        reach = self.reach_s04(players, mech, 5, 'S04-hoist')
        result.update(encounter='S04-01', acquisition_reach=reach, left_s03_exit_drag_tick=out,
            reflector_bounce=dict(tick=bounce['tick'], before=before, after=after))
        self.evidence.write('encounters/S04-01/result.json', result)
        print('PASS S04-01: from the real S03 v3 exit pose; blue hoist acquisition', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; left S03-exit-drag at tick', out, '; flat green reflector bounce at tick', bounce['tick'],
              'vy', round(before['speedY'],3), '->', round(after['speedY'],3), '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s04_02_nominal(self):
        trace, players, mech, result = self.run_s04('S04-02', self.S04_01_V3+self.S04_02_V3, self.S04_02_TICKS, self.S04_02_EXIT)
        self.assertEqual(self.s04_kinds(mech), [('acquisition','S04-hoist'),('release','S04-hoist'),('bounce','S04-reflector'),
            ('acquisition','S04-lift'),('release','S04-lift'),('bounce','S04-deflector')])
        reflector = self.s04_01_checks(trace, players, mech, result)[1]
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S04-lift')
        self.assertGreater(lift['tick'], reflector['tick'])
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S04-lift']['dx']), 1)
        bounce, before, after = self.bounce_s04(trace, 'S04-deflector')
        # Angled redirect: leftward flight turned into a steeper climb, speed kept.
        self.assertLess(before['speedX'], 0); self.assertLess(after['speedX'], 0)
        self.assertLess(abs(after['speedX']), abs(before['speedX'])); self.assertLess(after['speedY'], before['speedY'])
        turn = math.degrees(math.atan2(-after['speedY'], -after['speedX']) - math.atan2(-before['speedY'], -before['speedX']))
        self.assertGreater(turn, 30)
        self.assertAlmostEqual(math.hypot(after['speedX'], after['speedY']), math.hypot(before['speedX'], before['speedY']), delta=.02)
        launch = players[486]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (3194.9, -7569.5))
        hoist = self.reach_s04(players, mech, 5, 'S04-hoist')
        reach = self.reach_s04(players, mech, 486, 'S04-lift')
        # The deflector lies beyond the 1080 grapnel range from the S04-02 launch point.
        far = math.hypot(before['x']-launch['x'], before['y']-launch['y'])
        self.assertGreater(far, 1080)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {'S04-hoist':hoist, 'S04-lift':reach}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S04-02', segmented_from='S04-01 exit at tick 480 of the same run (no further placement)',
            s04_01_exit_at_tick_480=players[self.S04_01_TICKS], acquisition_reach=reach,
            deflector_bounce=dict(tick=bounce['tick'], before=before, after=after, turn_degrees=turn, distance_from_launch=far))
        self.evidence.write('encounters/S04-02/result.json', result)
        print('PASS S04-02: from the S04-01 exit at tick 480; blue lift acquisition', round(reach['distance'],1), 'at tick',
              lift['tick'], '; angled green deflector bounce at tick', bounce['tick'], 'turned', round(turn,1), 'deg,', round(far,1),
              'from the launch; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_04_declared_falls_through_drag(self):
        out = {}
        trace, players, mech, result = self.run_s04('S04-01-short', self.S04_01_SHORT, 800, self.SHORT_SETTLE, density_until=150, folder='falls')
        self.assertEqual(self.s04_kinds(mech), [('acquisition','S04-hoist'),('release','S04-hoist')])
        release = 150
        self.assertTrue(all(self.in_box(p, self.S03_EXIT_DRAG) for p in players))
        self.assertTrue(all(p['y'] >= players[release]['y']-5 for p in players[release:]))
        ledge = [e['tick'] for e in mech if e['element']=='S03-exit-ledge' and e['tick'] > release]
        self.assertTrue(ledge)
        settle = next(t for t in range(release, len(players)) if all(self.inside(p, self.SHORT_SETTLE) for p in players[t:]))
        out['S04-01-short'] = dict(release_tick=release, release_player=players[release], drag_zone=self.S03_EXIT_DRAG,
            inside_drag_every_tick=True, highest_y_after_release=min(p['y'] for p in players[release:]),
            ledge_bounces_after_release=len(ledge), landing=dict(tick=ledge[0], element='S03-exit-ledge'),
            below_release_height=True, settled_from_tick=settle, settle_box=self.SHORT_SETTLE, rest=players[-1])
        trace, players, mech, result = self.run_s04('S04-02-missed', self.S04_01_V3, 1400, self.BASIN_SETTLE, density_until=480, folder='falls')
        kinds = self.s04_kinds(mech)
        self.assertEqual(kinds[:3], [('acquisition','S04-hoist'),('release','S04-hoist'),('bounce','S04-reflector')])
        self.assertNotIn(('acquisition','S04-lift'), kinds)
        self.assertFalse([k for k in kinds[3:] if k[1] != 'S04-catch-basin'], kinds)
        reflector = next(e['tick'] for e in mech if e['element']=='S04-reflector')
        wall = next(t for t in range(reflector, len(players)) if players[t]['x'] < 11)
        out['S04-02-missed'] = self.fall_s03(trace, players, mech, reflector, 'S04-catch-basin', self.S04_FALL_DRAG, self.BASIN_SETTLE)
        out['S04-02-missed']['left_map_edge_tick'] = wall
        self.evidence.write('falls/result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S04 fall point is exercised from the labeled real S03 v3 exit pose. S04-01-short: the player never '
                 'leaves S03-exit-drag and settles on the green S03 exit ledge below the release height. S04-02-missed: the player '
                 'crosses S04-fall-drag, lands on the green catch basin, rebounds to at most half the drop (never back to the '
                 'release height) and settles'))
        print('PASS fall S04-01-short: stays in S03-exit-drag every tick; highest y after release', round(out['S04-01-short']['highest_y_after_release'],1),
              '; settled on S03-exit-ledge from tick', out['S04-01-short']['settled_from_tick'])
        v = out['S04-02-missed']
        print('PASS fall S04-02-missed: left map edge tick', wall, '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on',
              v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
              '; settled from tick', v['settled_from_tick'])


class Task514Tests(DeflectorV3Checks, unittest.TestCase):
    """Deflector Works opening (S04-01/02), re-specced by TASK-556 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, all shared with Task556Tests via DeflectorV3Checks):
    test_01_geometry_and_rules: v2 rules, rest-pad exceptions, 459-486 gaps at 540 -> v3 rules, zero
    gray solids, 918-972 gaps at 1080 (v3/v2 mean ratio >= 2.0 against artifacts/TASK-514/geometry.json),
    every v2 S04 solid deleted or converted to a green bouncer.
    test_02_s04_01_nominal: blue carriage ride from the v2 S03 exit-pad rest onto the pier pad -> blue
    hoist from the real v3 S03 exit settled pose west out of S03-exit-drag onto the flat green reflector.
    test_03_s04_02_nominal: blue lift from the pier across the works floor into the flat green press onto
    the press deck -> blue lift caught in flight on the reflector rebound, released into the angled green
    deflector. New test_04_declared_falls_through_drag covers the v3 fall points; test_04_source_hashes is
    renamed test_05_source_hashes. The v2 start (one base-start run of the v2 S01-S03 routes) is replaced
    by the real v3 S03 exit pose (one base-start run of the v3 S01-S03 routes).
    """
    task_id = 'TASK-514'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class DeflectorV3CompleteChecks(DeflectorV3Checks):
    """Layout-v3 Deflector Works S04-03/04, section exit and fall recovery (TASK-515), with real input.

    Same labeled-placement proof as DeflectorV3Checks: the start is the real S03 v3 exit settled pose of one
    base-start real-input S01+S02+S03 v3 run. S04-03/04 continue the S04-01/02 inputs of the same run, so they
    are segmented from the S04-02 exit (tick 640) and the S04-03 apex (tick 1040), not placed. Not a
    continuous-completion claim. Shared by Task515Tests (the inherited S04-01/02 cases also run).
    """
    CREST_V3, EXIT_HOOK_V3 = (820,-10902), (820,-12002)
    CREST_PRESS, CREST_RELEASE, EXIT_PRESS, EXIT_RELEASE = 815, 905, 1040, 1105
    # S04-03: the deflector climb runs up the left map edge to an apex (tick ~840); the crest hook is
    # pressed just before it (815) and held 90; the release flies up-right under the hook into the green
    # baffle, which reverses the sideways speed, and the player flies back left over the hook into the map
    # edge and rises to a second apex. S04-04: pressed at that apex on the map edge (1040), held 65; the
    # release flies up-right over the baffle top and drops into the exit drag zone, where it settles on the
    # green exit ledge. TASK-516 lowered both hooks (and moved them right of world x 800) out from under
    # the HUD text; the earlier TASK-515 route pressed at 830/1036 (holds 70/55).
    S04_03_V3 = [(CREST_PRESS,'mousedown',*CREST_V3),(CREST_RELEASE,'mouseup',*CREST_V3)]
    S04_04_V3 = [(EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),(EXIT_RELEASE,'mouseup',*EXIT_HOOK_V3)]
    S04_ROUTE_V3 = DeflectorV3Checks.S04_01_V3+DeflectorV3Checks.S04_02_V3+S04_03_V3+S04_04_V3
    S04_03_TICKS, S04_04_TICKS, S04_FULL_TICKS, S04_LAND_BY = 1040, 1800, 2000, 1320
    S04_EXIT_DRAG = dict(left=1340, right=1750, top=-11975, bottom=-11650)
    MAP_EDGE_X = 10.8
    # Mistimed S04-01 (fall.json): the hoist held 160 ticks too long (released at 530 instead of 370). The
    # swing carries the player back east into S03-exit-drag, where it drops onto the green S03 exit ledge
    # (the S03-04 route bouncer) and settles. Rejoin after 6 mover periods (1440 ticks; press at 1445 as
    # in the nominal S04-01): the hoist pull from the settled pose (x ~5823, west of the nominal 6127
    # start) leaves the drag sooner, so it is released on its first swing at 1555 (close to the nominal
    # release pose); the lift is held 79 instead of 70 (an earlier release flies faster and climbs ~570
    # higher), so the climb peaks near the nominal apex, and S04-03/04 follow at the rejoined apex ticks
    # (the crest hook held 89, so the second apex is at the nominal height).
    LATE_RELEASE, REJOIN_S04_TICK, REJOIN_EXIT_PRESS = 530, 1440, 2230
    S04_01_LATE = [(5,'mousedown',*DeflectorV3Checks.HOIST_V3),(LATE_RELEASE,'mouseup',*DeflectorV3Checks.HOIST_V3)]
    REJOIN_S04 = [(1445,'mousedown',*DeflectorV3Checks.HOIST_V3),(1555,'mouseup',*DeflectorV3Checks.HOIST_V3),
                  (1671,'mousedown',*DeflectorV3Checks.LIFT_V3),(1750,'mouseup',*DeflectorV3Checks.LIFT_V3),
                  (2003,'mousedown',*CREST_V3),(2092,'mouseup',*CREST_V3),
                  (REJOIN_EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),(REJOIN_EXIT_PRESS+65,'mouseup',*EXIT_HOOK_V3)]
    FALL_S04, FALL_S04_TICKS = S04_01_LATE+REJOIN_S04, 3150
    LATE_SETTLE = dict(x=[5790,6190], y=[-7800,-7770], speedX=[-.001,.001], speedY=[-.05,.05])
    # Declared S04-03/04 misses: no crest-hook press (from the climb apex down the left map edge through
    # S04-fall-drag onto the green catch basin); no exit-hook press (from the second apex, same column);
    # an exit hook held 5 ticks longer (still drops inside S04-exit-drag onto the exit ledge).
    S04_03_MISSED = DeflectorV3Checks.S04_01_V3+DeflectorV3Checks.S04_02_V3
    S04_04_MISSED = S04_03_MISSED+S04_03_V3
    S04_04_OVERSHOOT = S04_04_MISSED+[(EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),(EXIT_RELEASE+5,'mouseup',*EXIT_HOOK_V3)]

    def contacts(self, trace):
        return [e for e in trace['events'] if e['type']=='contact']

    def no_legacy_contact(self, trace):
        """No contact point lies on a legacy S05-S08 element (gray v1 geometry the v3 S04 route must avoid)."""
        m = self.report()['manifest']
        boxes = {e['id']:self.bounds_v3(e) for e in m['geometry']['elements'] if e['id'].split('-')[0] in ('S05','S06','S07','S08')}
        hits = sorted({k for e in self.contacts(trace) for k, b in boxes.items()
                       if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1})
        self.assertEqual(hits, [])
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 0]
        return dict(legacy_contact_points=hits, contact_events=len(self.contacts(trace)),
                    left_map_edge_contact_ticks=[edge[0], edge[-1]] if edge else [])

    def wall_and_apex(self, players, after, until):
        """The flight reaches the left map edge (sideways speed stopped) and rises to an apex along it before the next press."""
        wall = next(t for t in range(after, len(players)) if abs(players[t]['x']-self.MAP_EDGE_X) < .05)
        apex = min(range(wall, min(len(players), until+1)), key=lambda t: players[t]['y'])
        return wall, apex

    def s04_03_checks(self, trace, players, mech):
        self.assertTrue(self.inside(players[self.S04_02_TICKS], self.S04_02_EXIT), players[self.S04_02_TICKS])
        deflector = next(e for e in mech if e['type']=='bounce' and e['element']=='S04-deflector')
        # The deflector climb reaches the left map edge and rises along it to the S04-03 launch.
        climb_wall, climb_apex = self.wall_and_apex(players, deflector['tick'], self.CREST_PRESS)
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S04-crest-hook')
        self.assertGreater(acq['tick'], climb_wall)
        launch = players[self.CREST_PRESS]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (10.8, -10385.5))
        release = next(e for e in mech if e['type']=='release' and e['element']=='S04-crest-hook')
        self.assertEqual(release['tick'], self.CREST_RELEASE)
        baffle, before, after = self.bounce_s04(trace, 'S04-baffle')
        self.assertGreater(baffle['tick'], release['tick'])
        # Vertical green wall: the sideways speed is reversed, the vertical speed kept.
        self.assertGreater(before['speedX'], 1); self.assertAlmostEqual(after['speedX'], -before['speedX'], delta=.02)
        self.assertAlmostEqual(after['speedY'], before['speedY'], delta=.02); self.assertLess(after['speedY'], 0)
        wall, apex = self.wall_and_apex(players, baffle['tick'], self.EXIT_PRESS)
        self.assertLess(players[wall-1]['speedX'], -1); self.assertEqual(players[wall]['speedX'], 0)
        self.assertTrue(-11560 < players[apex]['y'] < -11460, players[apex])
        reach = self.reach_s04(players, mech, self.CREST_PRESS, 'S04-crest-hook')
        far = math.hypot(baffle['before']['simulation']['player']['x']-launch['x'], baffle['before']['simulation']['player']['y']-launch['y'])
        return dict(deflector_climb=dict(bounce_tick=deflector['tick'], map_edge_tick=climb_wall, apex=dict(tick=climb_apex, player=players[climb_apex])),
            crest_acquisition_reach=reach, crest_release=dict(tick=release['tick'], player=release['player']),
            baffle_bounce=dict(tick=baffle['tick'], before=before, after=after, distance_from_launch=far),
            map_edge_stop=dict(tick=wall, before=players[wall-1], after=players[wall]),
            apex=dict(tick=apex, player=players[apex], gain_over_climb_apex=players[climb_apex]['y']-players[apex]['y']))

    def test_05_s04_03_nominal(self):
        plan = self.S04_01_V3+self.S04_02_V3+self.S04_03_V3
        trace, players, mech, result = self.run_s04('S04-03', plan, self.S04_03_TICKS, self.S04_03_EXIT)
        self.assertEqual(self.s04_kinds(mech), [('acquisition','S04-hoist'),('release','S04-hoist'),('bounce','S04-reflector'),
            ('acquisition','S04-lift'),('release','S04-lift'),('bounce','S04-deflector'),
            ('acquisition','S04-crest-hook'),('release','S04-crest-hook'),('bounce','S04-baffle')])
        out = self.s04_03_checks(trace, players, mech)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S04-03', segmented_from='S04-02 exit at tick 640 of the same run (no further placement)',
            s04_02_exit_at_tick_640=players[self.S04_02_TICKS], exit_judged_at_tick=self.S04_03_TICKS,
            contacts=touched, legacy_s05_s08_contacts=[], **out)
        self.evidence.write('encounters/S04-03/result.json', result)
        print('PASS S04-03: from the S04-02 exit at tick 640; climb apex', round(out['deflector_climb']['apex']['player']['y'],1),
              'at tick', out['deflector_climb']['apex']['tick'], '; green crest-hook acquisition', round(out['crest_acquisition_reach']['distance'],1),
              'at tick', out['crest_acquisition_reach']['acquisition_tick'], '; release', self.CREST_RELEASE, '; green baffle bounce tick',
              out['baffle_bounce']['tick'], 'vx', round(out['baffle_bounce']['before']['speedX'],3), '->', round(out['baffle_bounce']['after']['speedX'],3),
              '; map edge stop tick', out['map_edge_stop']['tick'], '; apex', round(out['apex']['player']['y'],1), 'at tick', out['apex']['tick'],
              '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def s04_04_checks(self, trace, players, mech, press=None, ticks=None):
        """Exit-hook pull from the apex, release over the baffle, drop into S04-exit-drag and settle on the green exit ledge."""
        press = press or self.EXIT_PRESS
        ticks = ticks or len(players)-1
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S04-exit-hook' and e['tick'] >= press)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S04-exit-hook' and e['tick'] > acq['tick'])
        entry = next(t for t in range(release['tick'], ticks+1) if self.in_box(players[t], self.S04_EXIT_DRAG))
        self.assertTrue(all(self.in_box(players[t], self.S04_EXIT_DRAG) for t in range(entry, ticks+1)))
        # The flight passes over the baffle top (no second baffle contact).
        self.assertFalse([e for e in mech if e['type']=='bounce' and e['element']=='S04-baffle' and e['tick'] > release['tick']])
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S04-exit-ledge' and e['tick'] > release['tick']]
        self.assertTrue(ledge)
        land = ledge[0]
        self.assertLessEqual(land['tick'], press+self.S04_LAND_BY-self.EXIT_PRESS)
        settle = next(t for t in range(land['tick'], ticks+1) if all(self.inside(players[u], self.S04_04_EXIT) for u in range(t, ticks+1)))
        tail = players[settle:ticks+1]
        reach = self.reach_s04(players, mech, press, 'S04-exit-hook')
        return dict(exit_hook_acquisition_reach=reach, exit_hook_release=dict(tick=release['tick'], player=release['player']),
            exit_drag_entry=dict(tick=entry, player=players[entry], before=players[entry-1]),
            exit_ledge_landing=dict(tick=land['tick'], player=land['player']), ledge_bounces=len(ledge),
            section_exit=dict(element='S04-exit-ledge', drag_zone='S04-exit-drag', settle_tick=settle, settled_ticks=len(tail),
                settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[ticks], settle_box=self.S04_04_EXIT, inside_exit_drag=True))

    def test_06_s04_04_nominal(self):
        trace, players, mech, result = self.run_s04('S04-04', self.S04_ROUTE_V3, self.S04_04_TICKS, self.S04_04_EXIT,
                                                    density_until=self.S04_LAND_BY)
        self.assertTrue(self.inside(players[self.S04_03_TICKS], self.S04_03_EXIT), players[self.S04_03_TICKS])
        out = self.s04_04_checks(trace, players, mech)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S04-04', segmented_from='S04-03 exit (apex on the left map edge) at tick 1040 of the same run (no further placement)',
            s04_03_exit_at_tick_1040=players[self.S04_03_TICKS], contacts=touched, legacy_s05_s08_contacts=[], **out)
        self.evidence.write('encounters/S04-04/result.json', result)
        print('PASS S04-04: from the S04-03 apex at tick 1040; green exit-hook acquisition',
              round(out['exit_hook_acquisition_reach']['distance'],1), 'at tick', out['exit_hook_acquisition_reach']['acquisition_tick'],
              '; release', out['exit_hook_release']['tick'], '; enters S04-exit-drag at tick', out['exit_drag_entry']['tick'],
              '; green exit-ledge landing tick', out['exit_ledge_landing']['tick'], '; settled from tick', out['section_exit']['settle_tick'],
              'at', {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')}, '; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], 'until tick', self.S04_LAND_BY, '; identical replay; trusted input')

    def test_07_full_traversal(self):
        trace, players, mech, result = self.run_s04('S04-full', self.S04_ROUTE_V3, self.S04_FULL_TICKS, self.S04_04_EXIT,
                                                    density_until=self.S04_LAND_BY)
        self.assertEqual([e['element'] for e in mech if e['type']=='acquisition' and e['element'] != 'S03-exit-ledge'],
                         ['S04-hoist','S04-lift','S04-crest-hook','S04-exit-hook'])
        exits = {}
        for name, tick, bounds in (('S04-01',self.S04_01_TICKS,self.S04_01_EXIT),('S04-02',self.S04_02_TICKS,self.S04_02_EXIT),
                                   ('S04-03',self.S04_03_TICKS,self.S04_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        s3 = self.s04_03_checks(trace, players, mech)
        s4 = self.s04_04_checks(trace, players, mech)
        exits['S04-04'] = dict(tick=s4['section_exit']['settle_tick'], player=players[s4['section_exit']['settle_tick']], box=self.S04_04_EXIT)
        touched = self.no_legacy_contact(trace)
        reaches = [self.reach_s04(players, mech, t, el) for t, el in ((5,'S04-hoist'),(486,'S04-lift'),(self.CREST_PRESS,'S04-crest-hook'),(self.EXIT_PRESS,'S04-exit-hook'))]
        result.update(encounter='S04 full traversal', encounter_exits=exits, s04_03=s3, s04_04=s4, section_exit=s4['section_exit'],
            section_exit_reached=True, settled_at_section_exit=True, contacts=touched, legacy_s05_s08_contacts=[], reaches=reaches)
        self.evidence.write('encounters/S04-full/result.json', result)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules.setdefault('trace_measured_reach', {}).update({x['element']:x for x in reaches})
            self.evidence.write('rules.json', rules)
        print('PASS full S04: from the real S03 v3 exit pose; exits', {k:v['tick'] for k, v in exits.items()}, '; reaches',
              [round(x['distance'],1) for x in reaches], '; exit ledge landing tick', s4['exit_ledge_landing']['tick'], '; settled from tick',
              s4['section_exit']['settle_tick'], 'for', s4['section_exit']['settled_ticks'], 'ticks at',
              {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')}, 'inside S04-exit-drag; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_08_fall_through_drag_and_rejoin(self):
        trace, players, mech, result = self.run_s04('S04-01-late', self.FALL_S04, self.FALL_S04_TICKS, self.S04_04_EXIT,
                                                    density_until=self.LATE_RELEASE, folder='falls')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S04-hoist')
        self.assertEqual(release['tick'], self.LATE_RELEASE)
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S03-exit-ledge' and release['tick'] < e['tick'] < self.REJOIN_S04_TICK]
        self.assertTrue(ledge)
        land = ledge[0]['tick']
        self.assertFalse([e for e in mech if e['type']=='bounce' and release['tick'] < e['tick'] < land])
        apex_tick = min(range(release['tick'], land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        # The swing back east carries the player into S03-exit-drag across its west face; it stays inside to the ledge.
        ticks = [t for t in range(release['tick'], land+1) if self.in_box(players[t], self.S03_EXIT_DRAG)]
        entry, leave = ticks[0], ticks[-1]
        self.assertEqual(ticks, list(range(entry, land+1)))
        self.assertLessEqual(entry, apex_tick)
        before, after = players[entry-1], players[leave]
        self.assertFalse(self.in_box(before, self.S03_EXIT_DRAG)); self.assertGreater(before['speedX'], .3)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, leave) if abs(players[t]['speedX']) > 1e-9][:8]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios)
        vratios = [players[t+1]['speedY']-players[t]['speedY']*.985 for t in range(entry, leave)][:8]
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_ledge = contact['before']['simulation']['player']
        self.assertLess(abs(at_ledge['speedX']), abs(before['speedX'])*.01)
        rest_y = ledge[0]['player']['y']
        fall_height = rest_y - apex['y']
        self.assertGreater(fall_height, 50)
        peaks = []
        for a, b in zip(ledge, ledge[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_S04_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(p['peak_y'] > release['player']['y'] for p in peaks))
        # Settled on the green S03 exit ledge inside S03-exit-drag before the rejoin press.
        window = players[self.REJOIN_S04_TICK-100:self.REJOIN_S04_TICK]
        self.assertTrue(all(self.inside(p, self.LATE_SETTLE) and self.in_box(p, self.S03_EXIT_DRAG) for p in window))
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_S04_TICK]
        self.assertEqual(len(rejoin_inputs), len(self.REJOIN_S04))
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after_rejoin = [e for e in mech if e['tick'] >= self.REJOIN_S04_TICK]
        self.assertEqual([e['element'] for e in after_rejoin if e['type']=='acquisition' and e['element'] != 'S03-exit-ledge'],
                         ['S04-hoist','S04-lift','S04-crest-hook','S04-exit-hook'])
        for el in ('S04-reflector','S04-deflector','S04-baffle'):
            self.assertIn(('bounce', el), [(e['type'], e['element']) for e in after_rejoin])
        s4 = self.s04_04_checks(trace, players, mech, press=self.REJOIN_EXIT_PRESS)
        fall = dict(scenario='naturally mistimed S04-01 release: blue hoist held %d ticks too long (released at tick %d instead of %d); '
                             % (self.LATE_RELEASE-370, self.LATE_RELEASE, 370) +
                             'the swing returns east and the player falls physically; no relocation after the labeled S03 v3 exit start placement',
            release=dict(tick=release['tick'], element='S04-hoist', nominal_release_tick=370, player=release['player'],
                         release_height_y=release['player']['y']),
            fall_point=dict(id='S04-01-late', declared_x=5830, declared_y=-7880, release_x=release['player']['x'], apex_x=apex['x'], landing_x=at_ledge['x']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='S03 exit ledge bounce rest y minus the apex y after the release',
            drag_zone=dict(id='S03-exit-drag', box=self.S03_EXIT_DRAG, entry_tick=entry, last_tick_inside=leave,
                before=dict(tick=entry-1, x=before['x'], y=before['y'], speedX=before['speedX'], speedY=before['speedY']),
                at_ledge=dict(tick=land, x=at_ledge['x'], y=at_ledge['y'], speedX=at_ledge['speedX'], speedY=at_ledge['speedY']),
                per_tick_vx_ratio_airborne=ratios, vertical_damping_per_tick=0.985,
                vy_minus_damped_previous_vy_first_ticks=vratios),
            s03_bouncer=dict(element='S03-exit-ledge', route='S03-04 exit ledge (S03 route bouncer, the S03 section exit)', first_bounce_tick=land,
                rest_y=rest_y, inside='S03-exit-drag'),
            bounce_peaks=peaks[:8], bounce_count=len(peaks), first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            never_back_to_release_height=True,
            settled=dict(window=[self.REJOIN_S04_TICK-100, self.REJOIN_S04_TICK-1], box=self.LATE_SETTLE,
                max_abs_speedX=max(abs(p['speedX']) for p in window), max_abs_speedY=max(abs(p['speedY']) for p in window),
                y_range=[min(p['y'] for p in window), max(p['y'] for p in window)], inside_drag_zone='S03-exit-drag', on='S03-exit-ledge'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                start_tick=self.REJOIN_S04_TICK, mover_periods_after_start=self.REJOIN_S04_TICK//240,
                mechanics=[{k:e[k] for k in ('tick','type','element','player')} for e in after_rejoin
                           if e['type'] != 'contact' and e['element'] != 'S03-exit-ledge'],
                s04_04=s4, final=players[-1], encounter_rejoined='S04-01 (the section start) through the S04 exit ledge', exit_box=self.S04_04_EXIT))
        result.update(fall)
        self.evidence.write('falls/S04-01-late/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed hoist release tick', self.LATE_RELEASE, 'at y', round(release['player']['y'],1), '; apex', round(apex['y'],1),
              '; S03-exit-drag vx/vy', round(before['speedX'],3), round(before['speedY'],3), '->', round(at_ledge['speedX'],5),
              round(at_ledge['speedY'],3), '; S03 exit ledge bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of',
              round(fall_height,1), '; settled; input-only rejoin from tick', self.REJOIN_S04_TICK, ': acquisitions',
              [e['element'] for e in after_rejoin if e['type']=='acquisition' and e['element'] != 'S03-exit-ledge'],
              '; settled on the S04 exit ledge from tick', s4['section_exit']['settle_tick'])
        # The declared S04-03/04 fall points, each from the same labeled start.
        out = {}
        trace, players, mech, result = self.run_s04('S04-03-missed', self.S04_03_MISSED, 2400, self.BASIN_SETTLE, density_until=self.S04_02_TICKS, folder='falls')
        self.assertNotIn('S04-crest-hook', [e['element'] for e in mech if e['type']=='acquisition'])
        deflector = next(e['tick'] for e in mech if e['element']=='S04-deflector')
        out['S04-03-missed'] = self.fall_s03(trace, players, mech, deflector, 'S04-catch-basin', self.S04_FALL_DRAG, self.BASIN_SETTLE)
        trace, players, mech, result = self.run_s04('S04-04-missed', self.S04_04_MISSED, 2800, self.BASIN_SETTLE, density_until=self.S04_03_TICKS, folder='falls')
        self.assertNotIn('S04-exit-hook', [e['element'] for e in mech if e['type']=='acquisition'])
        out['S04-04-missed'] = self.fall_s03(trace, players, mech, self.CREST_RELEASE, 'S04-catch-basin', self.S04_FALL_DRAG, self.BASIN_SETTLE)
        trace, players, mech, result = self.run_s04('S04-04-overshoot', self.S04_04_OVERSHOOT, self.S04_04_TICKS, self.S04_04_EXIT,
                                                    density_until=self.EXIT_RELEASE+5, folder='falls')
        out['S04-04-overshoot'] = self.fall_s03(trace, players, mech, self.EXIT_RELEASE+5, 'S04-exit-ledge', self.S04_EXIT_DRAG, self.S04_04_EXIT)
        for k, v in out.items():
            # Every drop starts at its apex on (or above) the declared fall point.
            self.assertLessEqual(v['apex']['player']['y'], {'S04-03-missed':-10350,'S04-04-missed':-11300,'S04-04-overshoot':-11900}[k]+1)
        self.evidence.write('falls/s04_03_04_result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S04-03/04 fall point is exercised from the labeled real S03 v3 exit pose; the player crosses the drag zone, '
                 'lands on the green bouncer, rebounds to at most half the drop (never back to the release height) and settles inside the drag zone'))
        for k, v in out.items():
            print('PASS fall', k, ': drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on', v['landing']['element'],
                  'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3), '; settled from tick', v['settled_from_tick'])


class DeflectorV3ToleranceChecks(SwitchbackV3ToleranceChecks):
    """Layout-v3 Deflector Works (S04) tolerance on desktop 1280x720 and touch 844x390 (TASK-516).

    Proof kind (as TASK-556/515): the real S03 v3 exit settled pose of one base-start real-input
    S01+S02+S03 v3 run is restored once as a labeled initial placement (initial_snapshot); production
    trusted mouse/touch input and physics run from there. An attempt on encounter k replays the S04
    route up to k: the encounter's inputs carry the variant, the earlier encounters keep their nominal
    inputs. S04-01..03 end in flight, so they are judged at their mountain.js exit boxes (position at
    the nominal exit tick 480/640/1040); S04-04 at the S04 section exit (settled on the green exit
    ledge inside S04-exit-drag at tick 1900). check_s04_v3_mechanics requires the encounter's own
    mechanic, the S04 anchors in route order and no fall onto an S01-S03 element or an S04 fall
    bouncer. The HUD probe reads the UI boxes the game draws (LAYOUT_PROBE) at every nominal press.
    No earlier Task516Tests exists (the layout-v2 S04 tolerance was never built), so there is no v2
    suite to map.
    """
    DC = DeflectorV3CompleteChecks
    SEGMENTS = [DC.S04_01_V3, DC.S04_02_V3, DC.S04_03_V3, DC.S04_04_V3]
    V3_ENCOUNTERS = [('S04-01','blue hoist pulled west along the S03 exit ledge out of S03-exit-drag, release onto the flat green reflector',0,DC.S04_01_TICKS),
                     ('S04-02','blue lift caught in flight off the reflector rebound, release into the angled green deflector climb',DC.S04_01_TICKS,DC.S04_02_TICKS),
                     ('S04-03','green crest hook pulled from the climb apex on the left map edge, release into the green baffle, back to the map edge and up to the second apex',DC.S04_02_TICKS,DC.S04_03_TICKS),
                     ('S04-04','green exit hook pulled from the second apex, release over the baffle into S04-exit-drag, settle on the green exit ledge (S04 section exit)',DC.S04_03_TICKS,None)]
    S04_TICKS = 1900
    STRICT = {'S04-01':DC.S04_01_EXIT, 'S04-02':DC.S04_02_EXIT, 'S04-03':DC.S04_03_EXIT}
    # Mistimed releases, one per encounter, no further input afterwards: (encounter, release tick
    # replacing the nominal one, nominal release tick, ticks, declared fall point or None, landing bouncer).
    # S04-01: the hoist held 110 ticks too long swings back east past the S03 exit ledge and drops by the
    # right map edge through S03-fall-drag onto the green S03 lower bridge (the S03-02-missed column).
    # S04-02: the lift released 41 ticks early (S04-02-missed column). S04-03: the crest hook held 30
    # ticks too long (after the baffle bounce) drops back to the left map edge (S04-03-missed column).
    # S04-04: the exit hook released 35 ticks early falls against the baffle's west face (a side glance
    # that keeps the player falling) and down the left map edge (S04-04-missed column).
    MISTIMED = [('S04-01',480,370,1400,None,'S03-lower-bridge'), ('S04-02',515,556,1500,'S04-02-missed','S04-catch-basin'),
                ('S04-03',935,905,1900,'S04-03-missed','S04-catch-basin'), ('S04-04',1070,1105,2100,'S04-04-missed','S04-catch-basin')]
    V3_MOVERS = DC.S04_V3_MOVERS
    PAUSE_BUTTON = ViaductV3ToleranceChecks.PAUSE_BUTTON
    HUD_MARGIN = 8
    S03_V3_ROUTE, S03_V3_TICKS, S03_V3_SETTLE = DC.S03_V3_ROUTE, DC.S03_V3_TICKS, DC.S03_V3_SETTLE
    S03_EXIT_DRAG, S03_V3_ACQUIRED = DC.S03_EXIT_DRAG, DC.S03_V3_ACQUIRED
    s03_v3_exit = DeflectorV3Checks.s03_v3_exit
    targets = ViaductV3ToleranceChecks.targets
    clear = ViaductV3ToleranceChecks.clear

    ANCHOR_IDS = {'S04-01':'S04-hoist','S04-02':'S04-lift','S04-03':'S04-crest-hook','S04-04':'S04-exit-hook'}
    HUD_FINDING = ('The TASK-515 S04-crest-hook (620,-11110) and S04-exit-hook (600,-12070) were drawn under/against the HUD Time '
                   'row at their presses (client y ~113 on 1280x720). TASK-516 moved them to (800,-10915) and (800,-12015) (60x25), '
                   'at most ~530 above the press pose and right of world x 800, so they are drawn below the Section row and right of '
                   'the Time row on both viewports (the touch HUD uses the 12 px minimum font, top-left 170x79 px).')

    def make_input(self, plan, ticks, bounds, device='desktop', snapshot=None):
        m = FoundationsV3ToleranceChecks.make_input(self, plan, ticks, bounds, device, snapshot)
        m['metadata']['layout_probe'] = True
        return m

    def exits(self):
        """Per encounter: (ticks, judged exit bounds, meaning), from the runtime manifest."""
        enc = {e['id']:e for e in self.report()['manifest']['encounters'][12:16]}
        out = {}
        for name, _, _, tick in self.V3_ENCOUNTERS:
            if tick:
                b = enc[name]['exit']
                out[name] = (tick, dict(x=[b['left'],b['right']], y=[b['top'],b['bottom']]),
                             f'inside the mountain.js {name} exit box at the nominal exit tick {tick}')
            else:
                out[name] = (self.S04_TICKS, self.DC.S04_04_EXIT,
                             'settled on S04-exit-ledge inside S04-exit-drag (S04 section exit) at tick %d' % self.S04_TICKS)
        return out

    def filmstrip(self, prefix, viewport):
        """As FoundationsV3ToleranceChecks.filmstrip; the full-route nominal clips also keep each press frame."""
        if prefix.startswith('clips/'+self.V3_ENCOUNTERS[-1][0]+'-') and prefix.endswith('-nominal'):
            from PIL import Image
            presses = [t for seg in self.SEGMENTS for t, e, _, _ in seg if e == 'mousedown']
            for t in presses:
                with Image.open(self.evidence.path(prefix+f'/frame-{t:04d}.png')) as img:
                    img.convert('RGB').save(self.evidence.path(prefix+f'/press-{t:04d}.jpg'), quality=80)
        FoundationsV3ToleranceChecks.filmstrip(self, prefix, viewport)

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s04_v3_mechanics
        start = self.s03_v3_exit()
        self.assertTrue(self.inside(start['player'], self.S03_V3_SETTLE), start['player'])
        exits = self.exits()
        source = hashes()
        suite = dict(section='S04', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='isolated: one labeled initial placement (initial_snapshot) = the real S03 v3 exit settled pose of a base-start '
                       'real-input S01+S02+S03 v3 run (encounters/S03-exit-start), then production trusted mouse/touch input and physics; '
                       'an attempt on encounter k carries the variant on k and the TASK-556/515/516 nominal inputs on S04-01..k-1',
            initial_placement=type(self).v3_s03_start_proof, browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exits={n: dict(ticks=t, box=b, meaning=w) for n, (t, b, w) in exits.items()},
            mechanics_check='tools/grapple_over_verify.py check_s04_v3_mechanics',
            nominal_note='every nominal press aims at its anchor; the S04-01/02 aims are the exact world points of their desktop '
                         'press pixels so desktop and touch run the same route; every anchor is drawn clear of the HUD text and '
                         'the pause button at its press (hud-probe.json)',
            pause_button_client_rects={str(k): v for k, v in self.PAUSE_BUTTON.items()},
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            hud_probe='hud-probe.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal, clips = [], {}, {}
        for k, (name, mechanic, begin, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            ticks, bounds, meaning = exits[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), ticks, bounds, device, snapshot=start)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s04_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s04_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(self.clear(targets), (label, targets))
                        if exit_tick:
                            self.assertTrue(self.inside(players[exit_tick], self.STRICT[name]), (label, players[exit_tick]))
                            end = exit_tick
                        else:
                            end = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S04-exit-ledge')
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', begin, end)
                        clips[label] = (trace, m['metadata']['viewport'], prefix, mechanics)
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning),
                        outcome=f'{name} exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(artifacts/TASK-544/calibration.json density_cap.frozen_ticks = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','mover contact (S04-hoist/S04-lift are only rope anchors; no player contact with them occurs)'],
            cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal S04 run (0/480/640/1040) to its manifest exit tick '
                   '(480/640/1040) or, for S04-04, the exit-ledge landing; the settle on the exit ledge is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(start, exits['S04-04'])
        self.hud_probe(clips)
        self.assertEqual(failures, [])
        print('PASS S04 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-exit-hook negative control fails the exit')

    def negative_control(self, start, exit):
        from grapple_over_verify import hashes, check_s04_v3_mechanics
        # Named omission: the S04-04 exit-hook press/release left out; same placement, physics and
        # S04-01..03 inputs as every S04-04 attempt.
        ticks, bounds, meaning = exit
        plan = self.variant_plan(3)[:6]
        m = self.make_input(plan, ticks, bounds, snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s04_v3_mechanics('S04-04', trace, required=False)
        self.evidence.write('negative-control.json', dict(name='omitted exit hook: S04-04 S04-exit-hook press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning), unchanged_physics=True, source_hashes=hashes(),
            proof_kind='same labeled S03-exit placement, real mouse input, same S04-01..03 inputs as the S04-04 attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step,
            exit_ledge_contact='S04-exit-ledge' in [b['element'] for b in mechanics['bounces']], final_player=players[-1],
            scope='Without the exit-hook pull the second apex on the left map edge drops back down the edge (S04-04-missed), '
                  'through S04-fall-drag onto the green catch basin, and the S04 section exit is missed.'))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S04-exit-hook', mechanics['acquisitions'])
        self.assertIn('S04-catch-basin', [b['element'] for b in mechanics['bounces']])
        self.assertFalse(self.inside(players[-1], self.DC.S04_04_EXIT))
        self.assertLess(step, 60)

    @staticmethod
    def clearance(a, b):
        """Gap in px between two client rectangles {x:[l,r], y:[t,b]} (negative: overlap depth)."""
        dx = max(a['x'][0]-b['x'][1], b['x'][0]-a['x'][1])
        dy = max(a['y'][0]-b['y'][1], b['y'][0]-a['y'][1])
        return max(dx, dy)

    def hud_probe(self, clips):
        """At every nominal press, on each viewport, the anchor's drawn rectangle and the press point are at
        least HUD_MARGIN px clear of every HUD text box the game drew in that frame (LAYOUT_PROBE, CSS px) and
        of the pause button, inside the viewport, and the press acquires that anchor. World -> client uses the
        camera recorded in the trace at the press tick, cross-checked against the dispatched press's client
        point. TASK-516 lowered the S04-03/04 hooks: the TASK-515 hooks were drawn under the HUD Time row."""
        m = self.report()['manifest']
        by_id = {e['id']:e for e in m['geometry']['elements']}
        travel = {v['element']:v for v in m['geometry']['movers']}
        rows, worst = [], {}
        for k, (name, _, _, _) in enumerate(self.V3_ENCOUNTERS):
            for device in ('desktop','touch'):
                trace, viewport, prefix, mechanics = clips[f'{name}-{device}-nominal']
                layout = json.loads(self.evidence.path(prefix+'/layout-probe.json').read_text())['frames']
                scale = viewport['height']/1080*0.375
                press_tick = self.SEGMENTS[k][0][0]
                event = next(e for e in trace['events'] if e['type']=='input' and e['tick']==press_tick and e['event'] in ('mousedown','touchstart'))
                anchor = next(e for e in trace['events'] if e['type']=='acquisition' and e['tick'] >= press_tick)
                anchor_id = anchor['after']['rope'][0]['id']
                self.assertEqual(anchor_id, self.ANCHOR_IDS[name])
                camera = trace['snapshots'][press_tick]['state']['camera']
                to_client = lambda x, y: ((x+camera['x'])*scale, (y+camera['y'])*scale)
                expect = to_client(event['world']['x'], event['world']['y'])
                self.assertLess(abs(expect[0]-event['client']['x'])+abs(expect[1]-event['client']['y']), 1.5, (name, device, expect, event['client']))
                b = self.bounds_v3(by_id[anchor_id], travel.get(anchor_id))
                (l, t), (r, bt) = to_client(b['left'], b['top']), to_client(b['right'], b['bottom'])
                rect = dict(x=[l, r], y=[t, bt])
                frame = layout[str(press_tick)]
                hud = [dict(name=x['name'], kind=x['kind'], x=[x['x'], x['x']+x['width']], y=[x['y'], x['y']+x['height']]) for x in frame['boxes']]
                texts = [h for h in hud if h['kind']=='text']
                self.assertGreaterEqual(len(texts), 4, hud)
                pause = dict(name='pause button (menu.clickToPause scan)', kind='pause', **self.PAUSE_BUTTON[viewport['width']])
                point = dict(x=[event['client']['x']]*2, y=[event['client']['y']]*2)
                gaps = {h['name']: dict(anchor=self.clearance(rect, h), press=self.clearance(point, h)) for h in texts+[pause]}
                low = min(min(g.values()) for g in gaps.values())
                inside = 0 <= l and r <= viewport['width'] and 0 <= t and bt <= viewport['height']
                acquired = anchor_id in mechanics['acquisitions']
                row = dict(encounter=name, device=device, viewport=viewport, press_tick=press_tick, anchor=anchor_id,
                    press=dict(world=event['world'], client=event['client'], client_from_camera=expect), camera=camera,
                    anchor_world_rect=b, anchor_client_rect=rect, anchor_inside_viewport=inside, hud_boxes=hud, pause_button=pause,
                    clearance_px=gaps, min_clearance_px=low, anchor_acquired=acquired, acquisition_tick=anchor['tick'],
                    frame=f'{prefix}/filmstrip.jpg (frame {press_tick})')
                rows.append(row)
                worst[f'{name}-{device}'] = round(low, 1)
                self.assertTrue(inside, row); self.assertTrue(acquired, row)
                self.assertGreaterEqual(low, self.HUD_MARGIN, row)
                print('PASS hud probe', name, device, ': anchor', anchor_id, 'client x', [round(l), round(r)], 'y', [round(t), round(bt)],
                      '; press', (round(event['client']['x']), round(event['client']['y'])), '; min clearance to HUD text/pause',
                      round(low, 1), 'px; acquired at tick', anchor['tick'], flush=True)
        self.evidence.write('hud-probe.json', dict(rule='every mandatory press target (the anchor drawn at its press) and the press point '
            'are at least %d px clear of every HUD text box drawn in that frame and of the pause button, inside the viewport, and acquired' % self.HUD_MARGIN,
            finding_closed=self.HUD_FINDING,
            hud_source='LAYOUT_PROBE boxes (menu.js) recorded by grapple_over_verify.execute (metadata layout_probe) on the nominal clip frames',
            client_px_per_world={'1280':720/1080*0.375, '844':390/1080*0.375}, min_clearance_px=worst, runs=rows, passed=True))

    def test_02_mistimed_release_no_bounce_back(self):
        from grapple_over_verify import check_s04_v3_mechanics
        start = self.s03_v3_exit()
        elements = {e['id']:e for e in self.report()['manifest']['geometry']['elements']}
        zones = {k: self.bounds_v3(e) for k, e in elements.items() if e['role']=='drag' and k.startswith(('S01-','S02-','S03-','S04-'))}
        falls = {f['id']:f for f in self.report()['report']['sections'][3]['rules']['dragUnderFall']['measured']['fallPoints']}
        inzone = lambda p, b: b['left'] <= p['x'] <= b['right'] and b['top'] <= p['y'] <= b['bottom']
        rows = {}
        self.assertEqual([r[0] for r in self.MISTIMED], ['S04-01','S04-02','S04-03','S04-04'])
        for k, (name, release, nominal, ticks, fall_id, landing_id) in enumerate(self.MISTIMED):
            segment = self.SEGMENTS[k]
            self.assertEqual(segment[1][0], nominal)
            for device in ('desktop','touch'):
                plan = [p for seg in self.SEGMENTS[:k] for p in seg]+[segment[0], (release,)+segment[1][1:]]
                m = self.make_input(plan, ticks, dict(y=[-1e9, 1e9]), device, snapshot=start)
                prefix = f'clips/fall-{name}-{device}'
                trace, success, reason = self.run_attempt(m, prefix, True)
                self.assertTrue(success, reason)
                self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                mech = check_s04_v3_mechanics(name, trace, required=False)
                anchor = mech['encounter']['anchor']
                rel = next(r for r in mech['releases'] if r['element']==anchor)
                self.assertEqual(rel['tick'], release)
                r_player = players[release]
                bounces = [e for e in trace['events'] if e['type']=='bounce' and e['tick'] > release]
                landings = [e for e in bounces if e['contact']['elementId']==landing_id]
                self.assertTrue(landings, name)
                landing = landings[0]; land = landing['tick']
                self.assertEqual(elements[landing_id]['role'], 'bounce')
                # Before the landing bouncer only side glances are allowed: a vertical face that reverses the
                # sideways speed while the player keeps falling, and the fall never rises above the glance.
                glances = [e for e in bounces if e['tick'] < land]
                for e in glances:
                    before, after = e['before']['simulation']['player'], e['after']['simulation']['player']
                    self.assertTrue(after['speedY'] > 0 and before['speedX']*after['speedX'] < 0, (name, e['contact']))
                    self.assertTrue(all(players[t]['y'] >= after['y'] for t in range(e['tick'], land+1)), (name, e['tick']))
                crossed = {z: [t for t in range(release, land+1) if inzone(players[t], b)] for z, b in zones.items()}
                crossed = {z: ts for z, ts in crossed.items() if ts}
                self.assertTrue(crossed, name)
                # The landing is inside or directly below the last drag zone crossed.
                last = max(crossed, key=lambda z: crossed[z][-1])
                self.assertLessEqual(land - crossed[last][-1], 120, (name, last))
                rest_y = landing['after']['simulation']['player']['y']
                apex_tick = min(range(release, land), key=lambda t: players[t]['y'])
                second = next((e['tick'] for e in landings if e['tick'] > land+1), ticks)
                peak_tick = min(range(land+1, second), key=lambda t: players[t]['y'])
                release_height = rest_y - r_player['y']
                peak_height = rest_y - players[peak_tick]['y']
                fall_height = rest_y - players[apex_tick]['y']
                self.assertGreater(release_height, 0, name)
                self.assertLessEqual(peak_height, .5*release_height, name)
                self.assertLessEqual(peak_height, .5*fall_height, name)
                targets = self.targets(trace, m['metadata']['viewport'])
                self.assertTrue(self.clear(targets), targets)
                step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
                self.assertLess(step, 60)
                declared = falls[fall_id] if fall_id else None
                if declared:
                    self.assertEqual(declared['firstBouncer'], landing_id)
                row = dict(encounter=name, device=device, viewport=m['metadata']['viewport'], anchor=anchor,
                    mistiming=f'{anchor} released at tick {release} instead of {nominal}; no further input',
                    input=prefix+'/input.json.gz', trace=prefix+'/trace.json', filmstrip=prefix+'/filmstrip.jpg',
                    release=dict(tick=release, player=r_player), landing_rest_y=rest_y,
                    release_height=release_height, release_height_definition='landing-bouncer bounce y minus player y at the release tick',
                    apex=dict(tick=apex_tick, y=players[apex_tick]['y']), fall_height_from_apex=fall_height,
                    bounces_before_landing=[dict(tick=e['tick'], element=e['contact']['elementId'], kind='side glance (keeps falling)',
                        before=e['before']['simulation']['player'], after=e['after']['simulation']['player']) for e in glances],
                    drag_zones_crossed=[dict(id=z, box=zones[z], ticks=[ts[0], ts[-1]], entry_player=players[ts[0]],
                        exit_player=players[ts[-1]]) for z, ts in sorted(crossed.items(), key=lambda x: x[1][0])],
                    declared_fall_point=dict(id=fall_id, x=declared['x'], dragZones=declared['dragZones'], firstBouncer=declared['firstBouncer'])
                        if declared else dict(id=None, note='undeclared S04 line: the swing back east drops by the right map edge '
                                                            'through S03-fall-drag onto the green S03 lower bridge (S03-02-missed column)'),
                    first_bounce=dict(element=landing_id, tick=land, before=landing['before']['simulation']['player'],
                        after=landing['after']['simulation']['player']),
                    first_bounce_peak=dict(tick=peak_tick, y=players[peak_tick]['y'], height=peak_height,
                        fraction_of_release_height=peak_height/release_height, fraction_of_apex_fall=peak_height/fall_height),
                    at_most_half_of_release_height=True, max_tick_displacement=step, press_targets=targets, relocation=False)
                rows.setdefault(name, {})[device] = row
                print('PASS fall', name, device, ': release tick', release, 'y', round(r_player['y'],1), '; drag zones',
                      [d['id'] for d in row['drag_zones_crossed']], '; first bounce', landing_id, 'tick', land, '; first peak',
                      round(peak_height,1), '=', round(peak_height/release_height,3), 'of release height', round(release_height,1))
        self.evidence.write('no-bounce-back.json', dict(self.proof, rule='a mistimed release passes through the drag zone below '
            'it and its first bounce peaks at most 50% of the release height (i.e. at least 50% lower)',
            proof_kind='labeled S03-exit placement, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation',
            encounters=rows, passed=True))


TASK544_RANGES = {1080: False, 1620: True}


V1_S05_REVISION = '6c5519d'
# What happened to every static v1 S05 solid in the layout-v3 rebuild (TASK-517).
V1_S05_DISPOSITION = {
    'S05-projecting-girder':('converted-to-bounce','v1 S05-01 corner; still the v1 Crown recovery collider (recoveries[6] opening element); '
                             'same place and shape, now green; no v3 S05 route uses it'),
    'S05-rest':('deleted','v1 S05-01 landing rest pad; the v3 S05-01 ends in flight off the green deflector'),
    'S05-deep-overhang':('deleted','v1 S05-02 overhang; the v3 S05-02 swings under the blue lift into the green baffle'),
    'S05-lower-gallery':('deleted','v1 S05-02 rest pad; the v3 S05-02 ends in flight off the green baffle'),
    # TASK-531: deleted (it carried a 1080 S04-01 -> S05 exit bypass; recoveries[5] stopped naming it in the v3 S06 rebuild).
    'S05-transfer-canopy':('deleted','v1 S05-03 canopy; converted to green in TASK-517, deleted in TASK-531 (S04-01 -> S05 exit bypass at 1080)'),
    'S05-upper-rest':('deleted','v1 S05-03 landing rest pad; the v3 S05-03 swings from the green pull hook and ends in flight (TASK-518)'),
    'S05-recessed-ceiling':('converted-to-bounce','v1 S05-04 ceiling; still a v1 Liftworks recovery collider (recoveries[5]); same place and shape, now green'),
    'S05-exit':('converted-to-bounce','v1 S05 exit deck; still the v1 S06-01 start and encounters[20] element; same place and shape, now green'),
}
V3_S05_ADDED = ('S05-hoist','S05-canopy','S05-deflector','S05-lift','S05-baffle','S05-catch-deck','S05-fall-drag',
                # TASK-518: S05-03/04 and the section exit.
                'S05-pull-hook','S05-exit-hook','S05-exit-canopy','S05-exit-ledge','S05-exit-drag')


class GalleriesV3Checks:
    """Layout-v3 Cable Galleries opening (S05-01/02) from the real S04 v3 exit settled pose (TASK-517).

    The start pose comes from ONE base-start real-input run with no placement: the v3 S01, S02 and S03 routes
    (as DeflectorV3Checks, 4545 ticks to the S03 exit ledge) and the v3 S04 route (TASK-515/516 inputs from tick
    4545), 6545 ticks, settling on the green S04 exit ledge inside S04-exit-drag. It is restored once as a labeled
    initial placement (initial_snapshot), then production trusted input and physics run. Not a continuous-
    completion claim. Range is 1620 from the start pose on (the S03 route climbs through the S05 band, which is
    the TASK-502 upgrade trigger); every S05 gap is judged at 1620 and the 1080 negative control shows neither
    S05 anchor is acquirable at the base range. TASK-518 built S05-03/04: test_01 judges the completed section.
    """
    DC = DeflectorV3CompleteChecks
    S04_V3_ROUTE = DeflectorV3Checks.S03_V3_ROUTE+[(t+4545, e, x, y) for t, e, x, y in DC.S04_ROUTE_V3]
    S04_V3_TICKS = 4545+2000
    S04_V3_SETTLE = DC.S04_04_EXIT
    S04_EXIT_DRAG = DC.S04_EXIT_DRAG
    S04_V3_ACQUIRED = DeflectorV3Checks.S03_V3_ACQUIRED+['S04-hoist','S04-lift','S04-crest-hook','S04-exit-hook']
    # Exact world points of the desktop press pixels (637,161) and (965,449).
    HOIST_V3, LIFT_V3 = (2548,-12456.917383189533), (3860,-10855.16526289322)
    # S05-01: the hoist pulls the player up-right out of S04-exit-drag; the release at 150 rises into the green
    # canopy (its underside turns the rise into a drop) and the drop lands on the angled green deflector,
    # which throws the flight right under the legacy S08 spill deck.
    # S05-02: just after the deflector bounce the lift press at 304 catches the blue lift in flight; the swing
    # under it is released at 365 into the green baffle, which reverses the flight west.
    S05_01_V3 = [(5,'mousedown',*HOIST_V3),(150,'mouseup',*HOIST_V3)]
    S05_02_V3 = [(304,'mousedown',*LIFT_V3),(365,'mouseup',*LIFT_V3)]
    S05_V3_MOVERS = ('S05-hoist','S05-lift')
    S05_V3_BAND = (1378, 1458)
    # TASK-519 widened the position box (was x 2440..2580, y -10960..-10860) for the 3-tick-early hoist release.
    S05_01_EXIT = dict(x=[2420,2580], y=[-11040,-10860], speedX=[1.5,1.8], speedY=[.6,.9])
    S05_02_EXIT = dict(x=[4050,4300], y=[-10250,-10120], speedX=[-3.5,-3.1], speedY=[.85,1.25])
    S05_01_TICKS, S05_02_TICKS = 304, 405
    # TASK-518: the S05-03 exit is the swing-release flight at the S05-04 press (tick 655); the S05-04 exit is the
    # green exit ledge inside S05-exit-drag (the ledge keeps a small damped hop, hence the speedY band).
    S05_03_EXIT = dict(x=[3900,4030], y=[-8100,-7980], speedX=[1.8,2.1], speedY=[-1.0,-0.7])
    S05_04_EXIT = dict(x=[6100,6470], y=[-9460,-9420], speedX=[-.001,.001], speedY=[-.2,.2])
    S05_V3_FALLS = {'S05-01-short':(['S04-exit-drag'],'S04-exit-ledge'), 'S05-02-missed':(['S05-fall-drag'],'S05-catch-deck'),
                    'S05-03-missed':(['S04-fall-drag'],'S04-catch-basin'), 'S05-04-early':(['S05-exit-drag'],'S05-exit-ledge')}
    S05_V3_GAPS = ('S05-01-hoist','S05-02-lift','S05-03-pull','S05-04-exit')
    # The anchor element of each gap (the 1080 check uses its nearest point over the whole mover travel).
    S05_V3_ANCHORS = ('S05-hoist','S05-lift','S05-pull-hook','S05-exit-hook')
    S05_V3_ROUTE_ELEMENTS = ('S05-hoist','S05-canopy','S05-deflector','S05-lift','S05-baffle','S05-catch-deck',
                             'S05-pull-hook','S05-exit-hook','S05-exit-canopy','S05-exit-ledge')
    # Declared misses: a short hoist hold (released at 130) drops from its apex back into S04-exit-drag onto
    # the green S04 exit ledge; no lift press carries the deflector throw down through S05-fall-drag onto the
    # green catch deck.
    S05_01_SHORT = [(5,'mousedown',*HOIST_V3),(130,'mouseup',*HOIST_V3)]
    SHORT_SETTLE = dict(x=[1350,1740], y=[-11680,-11650], speedX=[-.001,.001], speedY=[-.05,.05])
    S05_FALL_DRAG = dict(left=3800, right=4400, top=-9900, bottom=-9500)
    DECK_SETTLE = dict(x=[3800,4400], y=[-9530,-9500], speedX=[-.001,.001], speedY=[-.05,.05])
    report = FoundationsV3Checks.report
    bounds_v3 = staticmethod(SwitchbackV3Checks.bounds_v3)
    inside = staticmethod(FoundationsV3CompleteChecks.inside)
    in_box = staticmethod(FoundationsV3CompleteChecks.in_box)
    fall_s03 = ViaductV3Checks.fall_s03

    def v1_s05(self):
        """The layout-v1 S05 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V1_S05_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[4], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, encounters:m.encounters.slice(16,20), elements:m.geometry.elements.filter(e=>e.id.startsWith('S05-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S05-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S05-'))}}''', source)

    def s04_v3_exit(self):
        """Real S04 v3 exit settled pose: one base-start real-input run of the v3 S01..S04 routes (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'v3_s04_start'): return type(self).v3_s04_start
        m = dict(metadata=metadata('base-start'), ticks=self.S04_V3_TICKS, expected_exit=self.S04_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.S04_V3_ROUTE],
            required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/S04-exit-start'
        self.evidence.write(prefix+'/input.json', m)
        setup = execute(m, self.browser, self.url, str(self.evidence.path(prefix)))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual([a for a in acquired if a not in ('S01-entry-pad','S02-exit-ledge')], self.S04_V3_ACQUIRED)
        touched = sorted({(e.get('contact') or {}).get('elementId') for e in setup['events']} - {None})
        self.assertFalse([t for t in touched if t.startswith('S05-')], touched)
        self.evidence.write(prefix+'/trace.json', Task506Tests.compact(self, setup))
        settle = next(t for t in range(4545+1300, self.S04_V3_TICKS+1)
                      if all(self.inside(p, self.S04_V3_SETTLE) for p in players[t:]))
        self.assertLessEqual(settle, 4545+1800)
        start = setup['snapshots'][-1]['state']['simulation']
        self.assertTrue(self.in_box(start['player'], self.S04_EXIT_DRAG))
        self.assertEqual((round(start['player']['x'],1), round(start['player']['y'],1)), (1387.9, -11660.9))
        self.assertIs(start['upgrades']['range'], True)
        upgrade = next(t for t in range(len(players)) if setup['snapshots'][t]['state']['simulation']['upgrades']['range']) \
            if 'upgrades' in setup['snapshots'][0]['state']['simulation'] else None
        # Clearance of the whole S01..S04 v3 flight from the new S05 route colliders.
        m2 = self.report()['manifest']
        travel = {v['element']:v for v in m2['geometry']['movers']}
        clearance = {}
        for e in m2['geometry']['elements']:
            if e['id'] not in self.S05_V3_ROUTE_ELEMENTS: continue
            b = self.bounds_v3(e, travel.get(e['id']))
            gap = min(math.hypot(max(b['left']-p['x'], 0, p['x']-b['right']), max(b['top']-p['y'], 0, p['y']-b['bottom']))
                      for p in players)
            clearance[e['id']] = gap - players[0]['radius']
            self.assertGreater(clearance[e['id']], 50, (e['id'], clearance))
        type(self).v3_s04_start = start
        type(self).v3_s04_start_proof = dict(kind='base-start v3 S01 route (TASK-548 inputs), v3 S02 route (TASK-551 inputs from tick 1495), '
            'v3 S03 route (TASK-554/555 inputs from tick 3245) and v3 S04 route (TASK-515/516 inputs from tick 4545), real mouse input, no placement',
            inputs=m['inputs'], acquisitions=acquired, settled_in_exit_box_from_tick=settle, settle_box=self.S04_V3_SETTLE,
            final_tick=self.S04_V3_TICKS, player=start['player'], inside_S04_exit_drag=True,
            snapshot_sha256=setup['snapshots'][-1]['sha256'], full_trace_sha256=state_hash(setup), trace=prefix+'/trace.json',
            s05_element_contacts=[], s01_s04_flight_clearance_to_s05_route_elements=clearance,
            range_upgraded=start['upgrades']['range'], range_upgraded_from_tick=upgrade)
        self.evidence.write(prefix+'/result.json', dict(passed=True, **type(self).v3_s04_start_proof))
        return start

    def mover_contacts(self, trace):
        """Contacts whose point lies on a S05 blue mover (the recorder reports mover contacts without an element id)."""
        m = self.report()['manifest'] if not hasattr(type(self), 'mover_boxes') else None
        if m:
            travel = {v['element']:v for v in m['geometry']['movers']}
            type(self).mover_boxes = {e['id']:self.bounds_v3(e, travel[e['id']]) for e in m['geometry']['elements'] if e['id'] in self.S05_V3_MOVERS}
        out = []
        for e in trace['events']:
            if e['type'] != 'contact': continue
            for k, b in type(self).mover_boxes.items():
                if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1:
                    out.append((e, k))
        return out

    def run_s05(self, name, plan, ticks, bounds, density_until=None, folder='encounters', start=None, start_label=None):
        """Labeled placement of the real S04 v3 exit pose, then trusted input; identical replay."""
        from grapple_over_verify import metadata, execute, check_trace
        start = start or self.s04_v3_exit()
        m = dict(metadata=metadata('isolated'), inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=[], initial_snapshot=start)
        m['metadata']['compact_contacts'] = True
        prefix = folder+'/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=folder == 'encounters')
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, Task506Tests.compact(self, t))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce'):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    mover=element in self.S05_V3_MOVERS, player=e['after']['simulation']['player'], rope=e['after']['rope']))
        contacts = self.mover_contacts(trace)
        mechanics += [dict(tick=e['tick'], type='mover-contact', element=k, mover=True, player=e['after']['simulation']['player'],
                           rope=e['after']['rope']) for e, k in contacts]
        mechanics.sort(key=lambda x: x['tick'])
        # Longest stretch without an acquisition, bounce or mover contact (LAYOUT_V3_DENSITY_CAP_TICKS).
        # density_until=0: negative controls, not judged for density.
        until = ticks if density_until is None else density_until
        marks = sorted({0, until, *[x['tick'] for x in mechanics if x['type'] != 'release' and x['tick'] <= until]})
        stretch = max(b-a for a, b in zip(marks, marks[1:])) if until else None
        if until: self.assertLessEqual(stretch, 254)
        travel = {}
        for mover in self.S05_V3_MOVERS:
            anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']==mover]
            if anchors:
                travel[mover] = dict(dx=anchors[-1]['x']-anchors[0]['x'], dy=anchors[-1]['y']-anchors[0]['y'], ticks=len(anchors))
        ledge = [x['tick'] for x in mechanics if x['element'] == 'S04-exit-ledge']
        result = dict(passed=True, matching_traces=True, trusted_inputs=True,
            proof_kind='isolated: one labeled initial placement = restoreClimbState of ' + (start_label or
                'the real S04 v3 exit settled pose from one base-start real-input S01..S04 v3 run') + '; production input/physics thereafter',
            initial_placement=dict(labeled=True, source=start_label or type(self).v3_s04_start_proof), not_continuous_completion_claim=True,
            range_upgraded_at_start=start['upgrades']['range'],
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[{k:x[k] for k in ('tick','type','element','mover','player')} for x in mechanics if x['element'] != 'S04-exit-ledge'],
            mover_contacts=[dict(tick=e['tick'], element=k, contact=e['contact']) for e, k in contacts],
            s04_exit_ledge_bounces=dict(count=len(ledge), first=ledge[0] if ledge else None, last=ledge[-1] if ledge else None),
            mover_anchor_travel_while_attached=travel, longest_stretch_without_mechanic_ticks=stretch, density_cap_ticks=254,
            density_measured_until_tick=until,
            final=players[-1], expected_exit=bounds, final_in_exit_box=self.inside(players[-1], bounds),
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        self.assertTrue(result['final_in_exit_box'], players[-1])
        return trace, players, mechanics, result

    def reach_s05(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = math.hypot(a['rope'][0]['x']-p['x'], a['rope'][0]['y']-p['y'])
        self.assertTrue(self.S05_V3_BAND[0] <= distance <= self.S05_V3_BAND[1], (element, distance))
        # Beyond the base 1080 range: not crossable before the TASK-502 upgrade.
        self.assertGreater(distance, 1080)
        return dict(element=element, distance=distance, fraction_of_1620=distance/1620, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y'],speedX=p['speedX'],speedY=p['speedY']), anchor=a['rope'][0],
            band=list(self.S05_V3_BAND), in_band=True, beyond_1080=True)

    def s05_kinds(self, mech):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S04-exit-ledge']

    def bounce_s05(self, trace, element):
        b = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']==element)
        return b, b['before']['simulation']['player'], b['after']['simulation']['player']

    def test_01_geometry_and_rules(self):
        r = self.report(); v1 = self.v1_s05()
        m = r['manifest']; elements = m['geometry']['elements']
        s05 = m['sections'][4]
        self.assertEqual((s05['designVersion'], s05['status']), (3, 'built'))
        enc_all = m['encounters'][16:20]
        self.assertEqual([e['status'] for e in enc_all], ['built']*4)
        # TASK-520 rebuilt S06-01 as layout v3 from the S05 exit ledge: the S06 entrance is built.
        self.assertEqual([c['status'] for c in m['connectors'][16:21]], ['built']*5)
        self.assertEqual((m['connectors'][16]['from'], m['connectors'][16]['to']), ('S04-04','S05-01'))
        self.assertEqual((m['connectors'][20]['id'], m['connectors'][20]['from']), ('S06-entrance', 'S05-04'))
        rec = m['recoveries'][4]
        self.assertEqual((rec['status'], rec['from'], rec['to'], rec['rejoin']), ('built', 'S05-04', 'S04-01', 'S05-01'))
        self.assertTrue(all(x in {e['id'] for e in elements} for x in rec['elements']), rec)
        self.assertNotIn('solidExceptions', s05)
        self.assertNotIn('fallLines', s05)
        self.assertEqual((s05['band']['top'], s05['band']['bottom']), (-9720, -6480))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S05-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S05-')}
        self.assertEqual(set(movers), set(self.S05_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        self.assertTrue(all(by_id[x]['role'] == 'solid' and by_id[x]['grapplable'] for x in movers))
        # The angled deflector face is a true 45-degree slope.
        d = by_id['S05-deflector']['points']
        self.assertEqual((d[1]['x']-d[0]['x'], d[1]['y']-d[0]['y']), (600, 600))
        enc = {e['id']:e for e in enc_all}
        self.assertEqual(enc['S05-01']['start'], {'x':1387.9,'y':-11660.9,'from':'S04-04'})
        self.assertEqual(enc['S05-02']['start'], {'from':'S05-01','x':2511.7,'y':-10905.2})
        for e in enc_all:
            self.assertTrue(all(x in by_id for x in e['elements']), e['id'])
            self.assertTrue(any(by_id[x]['role'] == 'bounce' for x in e['elements']), e['id'])
        for e in enc_all[:2]:
            self.assertTrue(any(x in movers for x in e['elements']), e['id'])
        self.assertEqual([e['start']['from'] for e in enc_all], ['S04-04','S05-01','S05-02','S05-03'])
        for name, box in (('S05-01', self.S05_01_EXIT), ('S05-02', self.S05_02_EXIT), ('S05-03', self.S05_03_EXIT), ('S05-04', self.S05_04_EXIT)):
            self.assertEqual(enc[name]['exit'], dict(left=box['x'][0], right=box['x'][1], top=box['y'][0], bottom=box['y'][1]))
        sec = r['report']['sections'][4]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S05', 3, True, [], 1620))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][:5], ['S01','S02','S03','S04','S05'])
        self.assertFalse(r['report']['failed'])
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('right', 'right'))
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S05-01','S05-02'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S05_V3_BAND))
        self.assertEqual([g['id'] for g in gaps], list(self.S05_V3_GAPS))
        for g in gaps:
            self.assertTrue(self.S05_V3_BAND[0] <= g['distance'] <= self.S05_V3_BAND[1], g)
        # Not crossable at 1080: from each press pose the nearest point of the mover (over its whole travel) is beyond 1080.
        travel = {v['element']:v for v in m['geometry']['movers']}
        base_range = {}
        self.assertEqual([g['id'] for g in s05['gaps']], list(self.S05_V3_GAPS))
        for g, mover in zip(s05['gaps'], self.S05_V3_ANCHORS):
            b = self.bounds_v3(by_id[mover], travel.get(mover)); p = g['from']
            near = math.hypot(max(b['left']-p['x'], 0, p['x']-b['right']), max(b['top']-p['y'], 0, p['y']-b['bottom']))
            self.assertGreater(near, 1080, (g['id'], near))
            base_range[g['id']] = dict(anchor=mover, blue_mover=mover in movers, anchor_box_over_travel=b, nearest_point_distance=near,
                                       base_range=1080, beyond_base_range=True)
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], list(self.S05_V3_FALLS))
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), self.S05_V3_FALLS[f['id']], f)
            self.assertEqual(by_id[f['firstBouncer']]['role'], 'bounce')
            for dz in f['dragZones']:
                b = self.bounds_v3(by_id[dz])
                self.assertTrue(b['left'] <= f['x']-18 and f['x']+18 <= b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, dz))
        self.assertEqual(sec['rules']['strayDrag']['measured']['dragZones'], [dict(id='S05-fall-drag', fallPoints=['S05-02-missed']),
                                                                              dict(id='S05-exit-drag', fallPoints=['S05-04-early'])])
        # Every static v1 S05 solid is deleted or converted to a green bouncer in place.
        self.assertEqual(sorted(v1['staticSolids']), sorted(V1_S05_DISPOSITION))
        self.assertEqual(v1['movers'], [])
        own_ids = {e['id'] for e in own}
        v1_by_id = {e['id']:e for e in v1['elements']}
        mapping = []
        for old in v1['staticSolids']:
            kind, why = V1_S05_DISPOSITION[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertNotIn(old, own_ids, old)
            else:
                self.assertEqual(now['role'], 'bounce', old)
                self.assertEqual((now['x'], now['y'], now['points']), (v1_by_id[old]['x'], v1_by_id[old]['y'], v1_by_id[old]['points']), old)
            mapping.append(dict(id=old, v1_role='solid', disposition=kind, v3_role=now['role'] if now else None, reason=why))
        self.assertEqual(sorted(set(v1_by_id) - set(V1_S05_DISPOSITION)), [])
        self.assertEqual(sorted(own_ids - set(v1_by_id)), sorted(V3_S05_ADDED))
        # No v3 S05 route element overlaps another section's collider (S04 v3 or the legacy S06-S08).
        route = [by_id[x] for x in self.S05_V3_ROUTE_ELEMENTS]
        others = [e for e in elements if e['id'].split('-')[0] in ('S04','S06','S07','S08') and e['role'] != 'drag']
        for a in route:
            ba = self.bounds_v3(a, travel.get(a['id']))
            for o in others:
                bo = self.bounds_v3(o, travel.get(o['id']))
                self.assertFalse(ba['left'] < bo['right'] and bo['left'] < ba['right'] and ba['top'] < bo['bottom'] and bo['top'] < ba['bottom'], (a['id'], o['id']))
        measured = {g['id']:g['distance'] for g in gaps}
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S05-01','S05-02','S05-03','S05-04'], planned=[],
            active_range=sec['range'], gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1620] = 1378-1458 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=measured, gaps_not_crossable_at_1080=base_range, direction=direction,
            direction_note='the direction rule reads the S05-04 exit box centre x (6285, the green exit ledge against the right map edge) '
                           'against the S05-01 entry x (1387.9); the encounter exits are centred at x 2510, 4175, 3965 and 6285',
            fall_points=falls, own_drag_zones=sec['rules']['strayDrag']['measured']['dragZones'],
            drag_below_every_fall_point=True, gray_solid_count=len(gray)))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s05, encounters=enc_all, planned_encounters=[],
            connectors=m['connectors'][16:21], recovery=m['recoveries'][4], elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True, v1_revision=V1_S05_REVISION,
            v1_static_solids=v1['staticSolids'], v1_solid_disposition=mapping, v3_added=list(V3_S05_ADDED),
            route_overlaps_with_s04_s08_colliders=[]))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="950" viewBox="-50 -12750 6600 4900" style="background:#111827">']
        for e in elements:
            if e['id'].split('-')[0] not in ('S04','S06','S07','S08') and e['id'] != 'mountain-right': continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.18' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="3"/>')
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors[roles[e['id']]] + ('" fill-opacity="0.35' if roles[e['id']] == 'yellow drag' else '')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="3"/>')
            if e['id'] in V3_S05_ADDED:
                dx, dy = {'S05-baffle':(-600,0),'S05-canopy':(-280,0),'S05-exit-canopy':(-1000,0),'S05-exit-ledge':(-1000,-40),
                          'S05-exit-drag':(-850,250),'S05-pull-hook':(-150,110),'S05-exit-hook':(-300,0)}.get(e['id'], (0,0))
                parts.append(f'<text x="{e["x"]+dx}" y="{e["y"]-16+dy}" fill="white" font-size="56">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+15}" x2="{e["x"]+60+v["max"]-v["min"]}" y2="{e["y"]+15}" stroke="#93c5fd" stroke-width="6" stroke-dasharray="12,8"/>')
        for g in s05['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="6" stroke-dasharray="14,10"/>')
        for f in falls:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="{max(f["firstBouncerTop"], -7850)}" stroke="#fb923c" stroke-width="5" stroke-dasharray="8,12"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="16" fill="#fb923c"/><text x="{f["x"]+30}" y="{f["y"]+12}" fill="#fb923c" font-size="52">{f["id"]}</text>')
        for e in enc_all:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="6"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+50}" fill="#f472b6" font-size="52">{e["id"]} exit</text>')
        parts.append('<circle cx="1387.9" cy="-11660.9" r="28" fill="#ff7a1a"/>')
        for i, t in enumerate(['S05 Cable Galleries v3 (designVersion 3, built, travelling right), zero gray solids',
                'orange dot = real S04 v3 exit settled pose; grey = S04, legacy S06-S08 and the right map edge',
                'S05-01: blue hoist out of S04-exit-drag -> green canopy -> angled green deflector',
                'S05-02: blue lift caught in flight -> swing under the spill deck -> green baffle',
                'S05-03: green pull hook caught flying west -> long swing under the catch deck, released east',
                'S05-04: green exit hook -> release into S05-exit-drag -> green exit canopy -> green exit ledge',
                'yellow dashes = gaps %s of 1620 (all > 1080)' % '/'.join(str(round(g['distance'],1)) for g in gaps),
                'orange = fall points over drag zones (S05-03-missed drops down the left edge to the catch basin at y -6000); pink = exit boxes']):
            parts.append(f'<text x="250" y="{-9750+i*66}" fill="#67e8f9" font-size="54">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=dict(width=1280, height=950)); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S05 designVersion 3 built (S05-01..04); gray solids', len(gray), '; roles',
              sorted(set(roles.values())), '; all 7 v3 rules pass at range', sec['range'], '; direction right', direction['entryX'], '<', direction['exitX'],
              '; gaps', [round(g['distance'],1) for g in gaps], 'in', list(self.S05_V3_BAND), '; nearest mover point from each press',
              {k:round(v['nearest_point_distance'],1) for k, v in base_range.items()}, '> 1080; fall points over drag',
              {f['id']:f['dragZones'] for f in falls}, '; v1 solids', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def s05_01_checks(self, trace, players, mech, result):
        out = next(t for t, p in enumerate(players) if t > 5 and not self.in_box(p, self.S04_EXIT_DRAG))
        self.assertLess(out, 150)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S05-hoist']['dx']), 1)
        canopy, cb, ca = self.bounce_s05(trace, 'S05-canopy')
        # Flat ceiling: the rise is turned into a drop, the sideways speed kept.
        self.assertLess(cb['speedY'], 0); self.assertGreater(ca['speedY'], 0)
        self.assertAlmostEqual(ca['speedX'], cb['speedX'], places=6); self.assertGreater(ca['speedX'], .5)
        deflector, before, after = self.bounce_s05(trace, 'S05-deflector')
        # 45-degree face (normal up-right): the drop is thrown right, the speed kept.
        self.assertGreater(before['speedY'], 1); self.assertGreater(after['speedX'], before['speedX']*1.5)
        self.assertLess(after['speedY'], before['speedY']*.6)
        self.assertAlmostEqual(math.hypot(after['speedX'], after['speedY']), math.hypot(before['speedX'], before['speedY']), delta=.02)
        self.assertTrue(self.inside(players[self.S05_01_TICKS], self.S05_01_EXIT), players[self.S05_01_TICKS])
        return out, (canopy, cb, ca), (deflector, before, after)

    def test_02_s05_01_nominal(self):
        trace, players, mech, result = self.run_s05('S05-01', self.S05_01_V3, self.S05_01_TICKS, self.S05_01_EXIT)
        self.assertEqual(self.s05_kinds(mech), [('acquisition','S05-hoist'),('release','S05-hoist'),('bounce','S05-canopy'),('bounce','S05-deflector')])
        out, (canopy, cb, ca), (deflector, before, after) = self.s05_01_checks(trace, players, mech, result)
        reach = self.reach_s05(players, mech, 5, 'S05-hoist')
        result.update(encounter='S05-01', acquisition_reach=reach, left_s04_exit_drag_tick=out,
            canopy_bounce=dict(tick=canopy['tick'], before=cb, after=ca), deflector_bounce=dict(tick=deflector['tick'], before=before, after=after))
        self.evidence.write('encounters/S05-01/result.json', result)
        print('PASS S05-01: from the real S04 v3 exit pose (range upgraded', result['range_upgraded_at_start'], '); blue hoist acquisition',
              round(reach['distance'],1), 'at tick', reach['acquisition_tick'], '; left S04-exit-drag at tick', out, '; green canopy bounce tick',
              canopy['tick'], 'vy', round(cb['speedY'],3), '->', round(ca['speedY'],3), '; angled green deflector bounce tick', deflector['tick'],
              'v', (round(before['speedX'],3), round(before['speedY'],3)), '->', (round(after['speedX'],3), round(after['speedY'],3)),
              '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s05_02_nominal(self):
        trace, players, mech, result = self.run_s05('S05-02', self.S05_01_V3+self.S05_02_V3, self.S05_02_TICKS, self.S05_02_EXIT)
        self.assertEqual(self.s05_kinds(mech), [('acquisition','S05-hoist'),('release','S05-hoist'),('bounce','S05-canopy'),
            ('bounce','S05-deflector'),('acquisition','S05-lift'),('release','S05-lift'),('bounce','S05-baffle')])
        deflector = self.s05_01_checks(trace, players, mech, result)[2][0]
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S05-lift')
        self.assertGreater(lift['tick'], deflector['tick'])
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S05-lift']['dx']), 1)
        bounce, before, after = self.bounce_s05(trace, 'S05-baffle')
        # Vertical green wall: the sideways speed is reversed, the vertical speed kept.
        self.assertGreater(before['speedX'], 3); self.assertAlmostEqual(after['speedX'], -before['speedX'], delta=.02)
        self.assertAlmostEqual(after['speedY'], before['speedY'], delta=.02)
        launch = players[304]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (2511.7, -10905.2))
        hoist = self.reach_s05(players, mech, 5, 'S05-hoist')
        reach = self.reach_s05(players, mech, 304, 'S05-lift')
        # The baffle lies beyond even the 1620 range from the S05-02 launch point.
        far = math.hypot(before['x']-launch['x'], before['y']-launch['y'])
        self.assertGreater(far, 1620)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {'S05-hoist':hoist, 'S05-lift':reach}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S05-02', segmented_from='S05-01 exit at tick 304 of the same run (no further placement)',
            s05_01_exit_at_tick_304=players[self.S05_01_TICKS], acquisition_reach=reach,
            baffle_bounce=dict(tick=bounce['tick'], before=before, after=after, distance_from_launch=far))
        self.evidence.write('encounters/S05-02/result.json', result)
        print('PASS S05-02: from the S05-01 exit at tick 304; blue lift acquisition', round(reach['distance'],1), 'at tick',
              lift['tick'], '; green baffle bounce at tick', bounce['tick'], 'vx', round(before['speedX'],3), '->', round(after['speedX'],3), ',',
              round(far,1), 'from the launch; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_04_declared_falls_through_drag(self):
        out = {}
        trace, players, mech, result = self.run_s05('S05-01-short', self.S05_01_SHORT, 900, self.SHORT_SETTLE, density_until=130, folder='falls')
        kinds = self.s05_kinds(mech)
        self.assertEqual(kinds[:2], [('acquisition','S05-hoist'),('release','S05-hoist')])
        self.assertFalse([k for k in kinds[2:] if k[1] != 'S04-exit-ledge'], kinds)
        out['S05-01-short'] = self.fall_s03(trace, players, mech, 130, 'S04-exit-ledge', self.S04_EXIT_DRAG, self.SHORT_SETTLE)
        out['S05-01-short']['release_height_y'] = players[130]['y']
        self.assertGreater(min(p['y'] for p in players[out['S05-01-short']['landing']['tick']:]), players[130]['y'])
        trace, players, mech, result = self.run_s05('S05-02-missed', self.S05_01_V3, 1300, self.DECK_SETTLE, density_until=self.S05_01_TICKS, folder='falls')
        kinds = self.s05_kinds(mech)
        self.assertEqual(kinds[:4], [('acquisition','S05-hoist'),('release','S05-hoist'),('bounce','S05-canopy'),('bounce','S05-deflector')])
        self.assertNotIn(('acquisition','S05-lift'), kinds)
        self.assertFalse([k for k in kinds[4:] if k[1] != 'S05-catch-deck'], kinds)
        deflector = next(e['tick'] for e in mech if e['element']=='S05-deflector')
        out['S05-02-missed'] = self.fall_s03(trace, players, mech, deflector, 'S05-catch-deck', self.S05_FALL_DRAG, self.DECK_SETTLE)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(out['S05-02-missed']['drag_entry_tick'], out['S05-02-missed']['landing']['tick'])
                  if abs(players[t]['speedX']) > 1e-9][:6]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios)
        out['S05-02-missed']['per_tick_vx_ratio_in_drag'] = ratios
        for k, v in out.items():
            declared = {'S05-01-short':(1560,-12070),'S05-02-missed':(3850,-10000)}[k]
            v['declared_fall_point'] = declared
        self.evidence.write('falls/result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S05 fall point is exercised from the labeled real S04 v3 exit pose. S05-01-short: the short hoist hold rises '
                 'out of S04-exit-drag, drops back through it onto the green S04 exit ledge, rebounds to at most half the drop (never back '
                 'to the release height) and settles. S05-02-missed: with no lift press the deflector throw crosses S05-fall-drag (horizontal '
                 'speed x0.8 per tick, vertical x0.985), lands on the green catch deck, rebounds to at most half the drop and settles'))
        for k, v in out.items():
            print('PASS fall', k, ': apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on',
                  v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
                  '; settled from tick', v['settled_from_tick'])

    def test_05_not_crossable_at_1080(self):
        """Negative control: the same presses with the base 1080 range (upgrades.range false) acquire neither S05 mover."""
        start = dict(self.s04_v3_exit()); start['upgrades'] = dict(start['upgrades'], range=False)
        label = 'NEGATIVE CONTROL: the real S04 v3 exit settled pose with upgrades.range set to false (base 1080 range)'
        trace, players, mech, result = self.run_s05('S05-01-range1080', self.S05_01_V3, 300, self.SHORT_SETTLE, folder='negative',
                                                    density_until=0, start=start, start_label=label)
        self.assertFalse([e for e in mech if e['type']=='acquisition'], mech)
        self.assertTrue(all(abs(p['x']-players[0]['x']) < .01 and abs(p['y']-players[0]['y']) < 1 for p in players))
        out = {'S05-01':dict(start=label, acquisitions=[], player_stayed_on_s04_exit_ledge=True, final=players[-1],
                             range_upgraded=trace['snapshots'][-1]['state']['simulation']['upgrades']['range'])}
        self.assertIs(out['S05-01']['range_upgraded'], False)
        # S05-02: the nominal S05-01 state at the lift press (tick 304), downgraded to 1080.
        nominal = self.run_s05('S05-01-to-304', self.S05_01_V3, 304, self.S05_01_EXIT, folder='negative')[0]
        mid = dict(nominal['snapshots'][304]['state']['simulation']); mid['upgrades'] = dict(mid['upgrades'], range=False)
        label2 = 'NEGATIVE CONTROL: the nominal S05-01 state at tick 304 (lift press) with upgrades.range set to false'
        lift = [(0,'mousedown',*self.LIFT_V3),(61,'mouseup',*self.LIFT_V3)]
        trace, players, mech, result = self.run_s05('S05-02-range1080', lift, 300, self.DECK_SETTLE | dict(y=[-10000,-9500], speedX=[-.01,.01], speedY=[-2,2]),
                                                    folder='negative', density_until=0, start=mid, start_label=label2)
        self.assertFalse([e for e in mech if e['type']=='acquisition'], mech)
        self.assertFalse([e for e in mech if e['element'] == 'S05-baffle'], mech)
        out['S05-02'] = dict(start=label2, acquisitions=[], baffle_reached=False, final=players[-1],
                             in_S05_fall_drag_at_end=self.in_box(players[-1], self.S05_FALL_DRAG))
        self.evidence.write('negative/result.json', dict(self.proof, passed=True, range_1080=out,
            note='with the base range the hoist and lift shots fall short (no acquisition): the S05 gaps are not crossable before the range upgrade'))
        print('PASS 1080 negative control: S05-01 hoist not acquired (player stays on the S04 exit ledge); S05-02 lift not acquired, no baffle; final',
              {k:round(players[-1][k],1) for k in ('x','y')})



class GalleriesV3CompleteChecks(GalleriesV3Checks):
    """Layout-v3 Cable Galleries S05-03/04, section exit and fall recovery (TASK-518), with real input.

    Same labeled-placement proof as GalleriesV3Checks: the start is the real S04 v3 exit settled pose of one
    base-start real-input S01..S04 v3 run. S05-03/04 continue the S05-01/02 inputs of the same run, so they are
    segmented from the S05-02 exit (tick 405) and the S05-03 exit (tick 655), not placed. Not a
    continuous-completion claim. Shared by Task518Tests (the inherited S05-01/02 cases also run).
    """
    DV = DeflectorV3Checks
    # Exact world points of the desktop press pixels (1037,644) and (1055,130).
    PULL_V3, EXIT_HOOK_V3 = (5264.844856808948,-9308.088482900792), (4978.889259856017,-9089.19141110997)
    PULL_PRESS, PULL_RELEASE, EXIT_PRESS, EXIT_RELEASE = 410, 650, 655, 775
    # S05-03: flying west off the baffle, the green pull hook (east, below the baffle foot) is pressed at 410;
    # the long swing runs west and down past the catch deck, turns, and comes back east under it; released
    # on the upswing at 650. S05-04: the green exit hook is pressed from that flight at 655 and held 120; the
    # swing carries the player up-right past the legacy S06 exit (staying left of the exit drag zone) and the
    # release rises into S05-exit-drag, where the green exit canopy turns the rise into a drop onto the green
    # exit ledge. Probed (not asserted): exit-hook releases 735-800 all settle on the exit ledge.
    S05_03_V3 = [(PULL_PRESS,'mousedown',*PULL_V3),(PULL_RELEASE,'mouseup',*PULL_V3)]
    S05_04_V3 = [(EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),(EXIT_RELEASE,'mouseup',*EXIT_HOOK_V3)]
    S05_ROUTE_V3 = GalleriesV3Checks.S05_01_V3+GalleriesV3Checks.S05_02_V3+S05_03_V3+S05_04_V3
    S05_03_TICKS, S05_04_TICKS, S05_FULL_TICKS, S05_LAND_BY = 655, 1300, 1400, 930
    S05_EXIT_DRAG = dict(left=6100, right=6480, top=-9990, bottom=-9420)
    S04_FALL_DRAG, BASIN_SETTLE = DV.S04_FALL_DRAG, DV.BASIN_SETTLE
    CATCH_DECK = dict(left=3800, right=4400, top=-9500, bottom=-9460)
    S05_02_AT_410 = dict(x=[3950,4200], y=[-10250,-10050], speedX=[-3.5,-3.1], speedY=[.8,1.3])
    # Mistimed S05-01 (fall.json): the blue hoist held 30 ticks short (released at 120 instead of 150). The
    # rise tops out above S04-exit-drag and drops back through it onto the green S04 exit ledge (the S04-04
    # route bouncer, the S04 section exit), where it settles at x ~1503. Input-only rejoin from tick 960 (4
    # mover periods): a 105-tick tug on the green S04 exit hook steps the player back west along the exit
    # ledge (it settles at x ~1391, 3 east of the nominal start); then the S05 route from tick 1445 (6 mover
    # periods), retimed for that pose: the hoist is acquired one tick later and the canopy bounce comes earlier,
    # so the lift is pressed 3 ticks after the deflector bounce (1752) and held 55, the pull hook is pressed
    # 15 ticks after the baffle (1850) and released at 2070, and the exit hook is held 120 from 2075.
    S04_EXIT_HOOK_PIXEL = (828,-12003.637493210137)
    SHORT_RELEASE, REJOIN_TICK = 120, 960
    S05_01_SHORTER = [(5,'mousedown',*GalleriesV3Checks.HOIST_V3),(SHORT_RELEASE,'mouseup',*GalleriesV3Checks.HOIST_V3)]
    REJOIN_S05 = [(960,'mousedown',*S04_EXIT_HOOK_PIXEL),(1065,'mouseup',*S04_EXIT_HOOK_PIXEL),
                  (1445,'mousedown',*GalleriesV3Checks.HOIST_V3),(1590,'mouseup',*GalleriesV3Checks.HOIST_V3),
                  (1752,'mousedown',*GalleriesV3Checks.LIFT_V3),(1807,'mouseup',*GalleriesV3Checks.LIFT_V3),
                  (1850,'mousedown',*PULL_V3),(2070,'mouseup',*PULL_V3),
                  (2075,'mousedown',*EXIT_HOOK_V3),(2195,'mouseup',*EXIT_HOOK_V3)]
    REJOIN_EXIT_PRESS = 2075
    FALL_S05, FALL_S05_TICKS = S05_01_SHORTER+REJOIN_S05, 3000
    SHORTER_SETTLE = dict(x=[1480,1530], y=[-11680,-11650], speedX=[-.001,.001], speedY=[-.05,.05])
    # Declared S05-03/04 misses: no pull-hook press (the baffle rebound flies into the left map edge and drops
    # along it through S04-fall-drag onto the green S04 catch basin); an exit hook released 40 ticks early
    # (still rises into S05-exit-drag and drops from the exit canopy onto the exit ledge).
    S05_03_MISSED = GalleriesV3Checks.S05_01_V3+GalleriesV3Checks.S05_02_V3
    S05_04_EARLY = S05_03_MISSED+S05_03_V3+[(EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),(EXIT_RELEASE-40,'mouseup',*EXIT_HOOK_V3)]

    def contacts(self, trace):
        return [e for e in trace['events'] if e['type']=='contact']

    def no_legacy_contact(self, trace):
        """No contact point lies on legacy gray geometry (S06-S08) or on a converted v1 S05 piece."""
        m = self.report()['manifest']
        legacy = {e['id']:self.bounds_v3(e) for e in m['geometry']['elements']
                  if e['id'].split('-')[0] in ('S06','S07','S08') or e['id'] in V1_S05_DISPOSITION}
        hits = sorted({k for e in self.contacts(trace) for k, b in legacy.items()
                       if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1})
        self.assertEqual(hits, [])
        return dict(legacy_contact_points=hits, contact_events=len(self.contacts(trace)))

    def s05_03_checks(self, trace, players, mech):
        self.assertTrue(self.inside(players[self.S05_02_TICKS], self.S05_02_EXIT), players[self.S05_02_TICKS])
        baffle = next(e for e in mech if e['type']=='bounce' and e['element']=='S05-baffle')
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S05-pull-hook')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S05-pull-hook')
        self.assertTrue(baffle['tick'] < self.PULL_PRESS < acq['tick'] < release['tick'] == self.PULL_RELEASE)
        launch = players[self.PULL_PRESS]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (4078.6, -10145.9))
        # Caught while still flying west off the baffle.
        self.assertLess(players[acq['tick']]['speedX'], -3)
        swing = range(acq['tick'], release['tick']+1)
        turn = min(swing, key=lambda t: players[t]['x'])
        low = max(swing, key=lambda t: players[t]['y'])
        self.assertTrue(players[turn]['x'] < self.CATCH_DECK['left'] and abs(players[turn]['speedX']) < .1, players[turn])
        # The return passes under the catch deck going east.
        under = [t for t in range(turn, release['tick']) if self.CATCH_DECK['left'] <= players[t]['x'] <= self.CATCH_DECK['right']]
        self.assertTrue(under and all(players[t]['y'] > self.CATCH_DECK['bottom'] + 1000 and players[t]['speedX'] > 1 for t in under))
        # No contact at all while the rope is on the pull hook.
        self.assertFalse([e for e in self.contacts(trace) if acq['tick'] <= e['tick'] <= release['tick']])
        rel = players[release['tick']]
        self.assertTrue(rel['speedX'] > 1.5 and rel['speedY'] < 0, rel)
        self.assertTrue(self.inside(players[self.S05_03_TICKS], self.S05_03_EXIT), players[self.S05_03_TICKS])
        reach = self.reach_s05(players, mech, self.PULL_PRESS, 'S05-pull-hook')
        return dict(pull_acquisition_reach=reach, caught_flying_west=dict(tick=acq['tick'], player=players[acq['tick']]),
            swing=dict(west_turn=dict(tick=turn, player=players[turn]), lowest=dict(tick=low, player=players[low]),
                       under_catch_deck_ticks=[under[0], under[-1]], catch_deck=self.CATCH_DECK, contacts_on_rope=[]),
            pull_release=dict(tick=release['tick'], player=rel))

    def s05_04_checks(self, trace, players, mech, press=None, ticks=None):
        """Exit-hook swing, release into S05-exit-drag, exit canopy, exit ledge landing and settle."""
        press = press or self.EXIT_PRESS
        ticks = ticks or len(players)-1
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S05-exit-hook' and e['tick'] >= press)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S05-exit-hook' and e['tick'] > acq['tick'])
        # The swing stays left of the exit pocket and touches nothing.
        self.assertLess(max(players[t]['x'] for t in range(acq['tick'], release['tick']+1)), self.S05_EXIT_DRAG['left']-10.8)
        self.assertFalse([e for e in self.contacts(trace) if acq['tick'] <= e['tick'] <= release['tick']])
        entry = next(t for t in range(release['tick'], ticks+1) if self.in_box(players[t], self.S05_EXIT_DRAG))
        self.assertTrue(all(self.in_box(players[t], self.S05_EXIT_DRAG) for t in range(entry, ticks+1)))
        before = players[entry-1]
        self.assertGreater(before['speedX'], 0); self.assertLess(before['speedY'], 0)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, entry+6) if abs(players[t]['speedX']) > 1e-9]
        canopy = [e for e in mech if e['type']=='bounce' and e['element']=='S05-exit-canopy' and e['tick'] > release['tick']]
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S05-exit-ledge' and e['tick'] > release['tick']]
        self.assertTrue(ledge)
        land = ledge[0]
        if canopy:
            c = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==canopy[0]['tick'])
            cb, ca = c['before']['simulation']['player'], c['after']['simulation']['player']
            self.assertLess(cb['speedY'], 0); self.assertGreater(ca['speedY'], 0)
            self.assertLess(canopy[0]['tick'], land['tick'])
            canopy_out = dict(tick=canopy[0]['tick'], before=cb, after=ca)
        else:
            canopy_out = None
        settle = next(t for t in range(land['tick'], ticks+1) if all(self.inside(players[u], self.S05_04_EXIT) for u in range(t, ticks+1)))
        tail = players[settle:ticks+1]
        reach = self.reach_s05(players, mech, press, 'S05-exit-hook') if press == self.EXIT_PRESS else None
        return dict(exit_hook_acquisition_reach=reach, exit_hook_acquisition_tick=acq['tick'],
            exit_hook_release=dict(tick=release['tick'], player=release['player']),
            swing_max_x=max(players[t]['x'] for t in range(acq['tick'], release['tick']+1)),
            exit_drag_entry=dict(tick=entry, before=before, at_entry=players[entry], per_tick_vx_ratio=ratios),
            exit_canopy_bounce=canopy_out, exit_ledge_landing=dict(tick=land['tick'], player=land['player']), ledge_bounces=len(ledge),
            section_exit=dict(element='S05-exit-ledge', drag_zone='S05-exit-drag', settle_tick=settle, settled_ticks=len(tail),
                settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[ticks], settle_box=self.S05_04_EXIT, inside_exit_drag=True))

    def test_06_s05_03_nominal(self):
        plan = self.S05_01_V3+self.S05_02_V3+self.S05_03_V3
        trace, players, mech, result = self.run_s05('S05-03', plan, self.S05_03_TICKS, self.S05_03_EXIT)
        self.assertEqual(self.s05_kinds(mech), [('acquisition','S05-hoist'),('release','S05-hoist'),('bounce','S05-canopy'),
            ('bounce','S05-deflector'),('acquisition','S05-lift'),('release','S05-lift'),('bounce','S05-baffle'),
            ('acquisition','S05-pull-hook'),('release','S05-pull-hook')])
        out = self.s05_03_checks(trace, players, mech)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S05-03', segmented_from='S05-02 exit at tick 405 of the same run (no further placement)',
            s05_02_exit_at_tick_405=players[self.S05_02_TICKS], exit_judged_at_tick=self.S05_03_TICKS, contacts=touched, **out)
        self.evidence.write('encounters/S05-03/result.json', result)
        r = out['pull_acquisition_reach']
        print('PASS S05-03: from the S05-02 exit at tick 405; green pull-hook acquisition', round(r['distance'],1), 'at tick',
              r['acquisition_tick'], 'flying west (vx', round(out['caught_flying_west']['player']['speedX'],2), '); west turn at x',
              round(out['swing']['west_turn']['player']['x'],1), 'tick', out['swing']['west_turn']['tick'], '; under the catch deck ticks',
              out['swing']['under_catch_deck_ticks'], '; release', self.PULL_RELEASE, 'v', (round(out['pull_release']['player']['speedX'],2),
              round(out['pull_release']['player']['speedY'],2)), '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_07_s05_04_nominal(self):
        trace, players, mech, result = self.run_s05('S05-04', self.S05_ROUTE_V3, self.S05_04_TICKS, self.S05_04_EXIT,
                                                    density_until=self.S05_LAND_BY)
        self.assertTrue(self.inside(players[self.S05_03_TICKS], self.S05_03_EXIT), players[self.S05_03_TICKS])
        self.assertEqual(self.s05_kinds(mech)[9:13], [('acquisition','S05-exit-hook'),('release','S05-exit-hook'),
            ('bounce','S05-exit-canopy'),('bounce','S05-exit-ledge')])
        out = self.s05_04_checks(trace, players, mech)
        self.assertIsNotNone(out['exit_canopy_bounce'])
        self.assertLessEqual(out['exit_ledge_landing']['tick'], self.S05_LAND_BY)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S05-04', segmented_from='S05-03 exit (swing-release flight) at tick 655 of the same run (no further placement)',
            s05_03_exit_at_tick_655=players[self.S05_03_TICKS], contacts=touched, **out)
        self.evidence.write('encounters/S05-04/result.json', result)
        r = out['exit_hook_acquisition_reach']
        print('PASS S05-04: from the S05-03 flight at tick 655; green exit-hook acquisition', round(r['distance'],1), 'at tick',
              r['acquisition_tick'], '; swing max x', round(out['swing_max_x'],1), '; release', out['exit_hook_release']['tick'],
              '; enters S05-exit-drag at tick', out['exit_drag_entry']['tick'], 'vx ratio', [round(x,3) for x in out['exit_drag_entry']['per_tick_vx_ratio'][:3]],
              '; green exit canopy bounce tick', out['exit_canopy_bounce']['tick'], '; green exit ledge landing tick', out['exit_ledge_landing']['tick'],
              '; settled from tick', out['section_exit']['settle_tick'], 'at', {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')},
              '; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], 'until tick', self.S05_LAND_BY, '; identical replay; trusted input')

    def test_08_full_traversal(self):
        trace, players, mech, result = self.run_s05('S05-full', self.S05_ROUTE_V3, self.S05_FULL_TICKS, self.S05_04_EXIT,
                                                    density_until=self.S05_LAND_BY)
        self.assertEqual([e['element'] for e in mech if e['type']=='acquisition' and e['element'] != 'S04-exit-ledge'],
                         ['S05-hoist','S05-lift','S05-pull-hook','S05-exit-hook'])
        self.assertEqual([e['element'] for e in mech if e['type']=='bounce' and e['element'] != 'S04-exit-ledge'][:5],
                         ['S05-canopy','S05-deflector','S05-baffle','S05-exit-canopy','S05-exit-ledge'])
        exits = {}
        for name, tick, bounds in (('S05-01',self.S05_01_TICKS,self.S05_01_EXIT),('S05-02',self.S05_02_TICKS,self.S05_02_EXIT),
                                   ('S05-03',self.S05_03_TICKS,self.S05_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        s3 = self.s05_03_checks(trace, players, mech)
        s4 = self.s05_04_checks(trace, players, mech)
        exits['S05-04'] = dict(tick=s4['section_exit']['settle_tick'], player=players[s4['section_exit']['settle_tick']], box=self.S05_04_EXIT)
        touched = self.no_legacy_contact(trace)
        reaches = [self.reach_s05(players, mech, t, el) for t, el in ((5,'S05-hoist'),(304,'S05-lift'),(self.PULL_PRESS,'S05-pull-hook'),(self.EXIT_PRESS,'S05-exit-hook'))]
        result.update(encounter='S05 full traversal', encounter_exits=exits, s05_03=s3, s05_04=s4, section_exit=s4['section_exit'],
            section_exit_reached=True, settled_at_section_exit=True, contacts=touched, reaches=reaches)
        self.evidence.write('encounters/S05-full/result.json', result)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules.setdefault('trace_measured_reach', {}).update({x['element']:x for x in reaches})
            self.evidence.write('rules.json', rules)
        print('PASS full S05: from the real S04 v3 exit pose; exits', {k:v['tick'] for k, v in exits.items()}, '; reaches',
              [round(x['distance'],1) for x in reaches], '; exit ledge landing tick', s4['exit_ledge_landing']['tick'], '; settled from tick',
              s4['section_exit']['settle_tick'], 'for', s4['section_exit']['settled_ticks'], 'ticks at',
              {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')}, 'inside S05-exit-drag; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_09_fall_through_drag_and_rejoin(self):
        trace, players, mech, result = self.run_s05('S05-01-shorter', self.FALL_S05, self.FALL_S05_TICKS, self.S05_04_EXIT,
                                                    density_until=self.SHORT_RELEASE, folder='falls')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S05-hoist')
        self.assertEqual(release['tick'], self.SHORT_RELEASE)
        rel = players[self.SHORT_RELEASE]
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S04-exit-ledge' and release['tick'] < e['tick'] < self.REJOIN_TICK]
        self.assertTrue(ledge)
        land = ledge[0]['tick']
        # Nothing but the S04 exit ledge is touched between the release and the rejoin.
        self.assertFalse([e for e in mech if release['tick'] < e['tick'] < self.REJOIN_TICK and e['element'] != 'S04-exit-ledge'])
        self.assertFalse([e for e in self.contacts(trace) if release['tick'] < e['tick'] < self.REJOIN_TICK
                          and not (1340 <= e['contact']['x'] <= 1750 and abs(e['contact']['y'] + 11650) < 2)])
        apex_tick = min(range(release['tick'], land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        drag = self.S04_EXIT_DRAG
        # The rise leaves S04-exit-drag above its top; the drop re-enters it and stays inside to the ledge.
        self.assertLess(apex['y'], drag['top'])
        ticks = [t for t in range(apex_tick, land+1) if self.in_box(players[t], drag)]
        entry, leave = ticks[0], ticks[-1]
        self.assertEqual(ticks, list(range(entry, land+1)))
        before, inside_last = players[entry-1], players[leave]
        self.assertFalse(self.in_box(before, drag)); self.assertGreater(before['speedY'], 0)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, leave) if abs(players[t]['speedX']) > 1e-9][:8]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios)
        vdamp = [players[t+1]['speedY']-players[t]['speedY']*.985 for t in range(entry, leave)][:8]
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_ledge = contact['before']['simulation']['player']
        self.assertLess(abs(at_ledge['speedX']), max(abs(before['speedX'])*.01, 1e-6))
        self.assertLess(at_ledge['speedY'], before['speedY'] + 1)
        rest_y = ledge[0]['player']['y']
        fall_height = rest_y - apex['y']
        self.assertGreater(fall_height, 50)
        peaks = []
        for a, b in zip(ledge, ledge[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(p['peak_y'] > rel['y'] for p in peaks))
        # Settled on the green S04 exit ledge inside S04-exit-drag before the rejoin press.
        window = players[self.REJOIN_TICK-100:self.REJOIN_TICK]
        self.assertTrue(all(self.inside(p, self.SHORTER_SETTLE) and self.in_box(p, drag) for p in window))
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_TICK]
        self.assertEqual(len(rejoin_inputs), len(self.REJOIN_S05))
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after_rejoin = [e for e in mech if e['tick'] >= self.REJOIN_TICK]
        self.assertEqual([e['element'] for e in after_rejoin if e['type']=='acquisition' and e['element'] != 'S04-exit-ledge'],
                         ['S04-exit-hook','S05-hoist','S05-lift','S05-pull-hook','S05-exit-hook'])
        for el in ('S05-canopy','S05-deflector','S05-baffle'):
            self.assertIn(('bounce', el), [(e['type'], e['element']) for e in after_rejoin])
        # The tug leaves the player settled back on the ledge near the nominal S05-01 start before the hoist press.
        stepped = players[1444]
        self.assertTrue(self.in_box(stepped, drag) and abs(stepped['x'] - 1387.9) < 5 and abs(stepped['speedX']) < .001, stepped)
        s4 = self.s05_04_checks(trace, players, mech, press=self.REJOIN_EXIT_PRESS)
        fall = dict(scenario='naturally mistimed S05-01 release: blue hoist held %d ticks short (released at tick %d instead of %d); '
                             % (150-self.SHORT_RELEASE, self.SHORT_RELEASE, 150) +
                             'the rise tops out above S04-exit-drag and the player falls physically; no relocation after the labeled S04 v3 exit start placement',
            release=dict(tick=release['tick'], element='S05-hoist', nominal_release_tick=150, player=rel, release_height_y=rel['y']),
            fall_point=dict(id='S05-01-short (declared column x 1560; this shorter hold drops at x %.1f, same drag zone and bouncer)' % apex['x'],
                            declared_x=1560, declared_y=-12070, apex_x=apex['x'], landing_x=at_ledge['x']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='S04 exit ledge bounce rest y minus the apex y after the release',
            drag_zone=dict(id='S04-exit-drag', box=drag, entry_tick=entry, last_tick_inside_before_landing=leave,
                before=dict(tick=entry-1, x=before['x'], y=before['y'], speedX=before['speedX'], speedY=before['speedY']),
                after=dict(tick=land, x=at_ledge['x'], y=at_ledge['y'], speedX=at_ledge['speedX'], speedY=at_ledge['speedY'],
                           note='player state just before the ledge bounce, after crossing the drag zone'),
                per_tick_vx_ratio_airborne=ratios, vertical_damping_per_tick=0.985,
                vy_minus_damped_previous_vy_first_ticks=vdamp),
            s04_bouncer=dict(element='S04-exit-ledge', route='S04-04 exit ledge (S04 route bouncer, the S04 section exit)', first_bounce_tick=land,
                rest_y=rest_y, inside='S04-exit-drag'),
            bounce_peaks=peaks[:8], bounce_count=len(peaks), first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            never_back_to_release_height=True,
            settled=dict(window=[self.REJOIN_TICK-100, self.REJOIN_TICK-1], box=self.SHORTER_SETTLE,
                max_abs_speedX=max(abs(p['speedX']) for p in window), max_abs_speedY=max(abs(p['speedY']) for p in window),
                y_range=[min(p['y'] for p in window), max(p['y'] for p in window)], inside_drag_zone='S04-exit-drag', on='S04-exit-ledge'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                start_tick=self.REJOIN_TICK, mover_periods_after_start=self.REJOIN_TICK//240,
                step_back=dict(element='S04-exit-hook', press=960, release=1065, settled_at_tick_1444=stepped, nominal_start_x=1387.9),
                mechanics=[{k:e[k] for k in ('tick','type','element','player')} for e in after_rejoin
                           if e['type'] != 'contact' and e['element'] != 'S04-exit-ledge'],
                s05_04=s4, final=players[-1], encounter_rejoined='S05-01 (the section start) through the S05 exit ledge', exit_box=self.S05_04_EXIT))
        result.update(fall)
        self.evidence.write('falls/S05-01-shorter/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed hoist release tick', self.SHORT_RELEASE, 'at y', round(rel['y'],1), '; apex', round(apex['y'],1),
              '; S04-exit-drag vx/vy', round(before['speedX'],4), round(before['speedY'],3), '->', round(at_ledge['speedX'],6),
              round(at_ledge['speedY'],3), '; S04 exit ledge bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of',
              round(fall_height,1), '; settled at x', round(window[-1]['x'],1), '; input-only rejoin from tick', self.REJOIN_TICK,
              ': stepped back to x', round(stepped['x'],1), '; acquisitions',
              [e['element'] for e in after_rejoin if e['type']=='acquisition' and e['element'] != 'S04-exit-ledge'],
              '; settled on the S05 exit ledge from tick', s4['section_exit']['settle_tick'])
        # The declared S05-03/04 fall points, each from the same labeled start.
        out = {}
        trace, players, mech, result = self.run_s05('S05-03-missed', self.S05_03_MISSED, 2400, self.BASIN_SETTLE,
                                                    density_until=self.S05_02_TICKS, folder='falls')
        self.assertNotIn('S05-pull-hook', [e['element'] for e in mech if e['type']=='acquisition'])
        baffle = next(e['tick'] for e in mech if e['element']=='S05-baffle')
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 0]
        self.assertTrue(edge)
        out['S05-03-missed'] = self.fall_s03(trace, players, mech, baffle, 'S04-catch-basin', self.S04_FALL_DRAG, self.BASIN_SETTLE)
        out['S05-03-missed']['left_map_edge_first_contact'] = dict(tick=edge[0], player=players[edge[0]])
        self.assertLessEqual(players[edge[0]]['y'], -8000+20)
        trace, players, mech, result = self.run_s05('S05-04-early', self.S05_04_EARLY, self.S05_04_TICKS, self.S05_04_EXIT,
                                                    density_until=self.S05_LAND_BY, folder='falls')
        out['S05-04-early'] = self.fall_s03(trace, players, mech, self.EXIT_RELEASE-40, 'S05-exit-ledge', self.S05_EXIT_DRAG, self.S05_04_EXIT)
        for k, v in out.items():
            # Every drop starts at its apex on (or above) the declared fall point.
            self.assertLessEqual(v['apex']['player']['y'], {'S05-03-missed':-8000,'S05-04-early':-9960}[k]+1)
            v['declared_fall_point'] = {'S05-03-missed':(30,-8000),'S05-04-early':(6200,-9960)}[k]
        self.evidence.write('falls/s05_03_04_result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S05-03/04 fall point is exercised from the labeled real S04 v3 exit pose; the player crosses the drag zone, '
                 'lands on the green bouncer, rebounds to at most half the drop (never back to the release height) and settles'))
        for k, v in out.items():
            print('PASS fall', k, ': apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'],
                  '; lands on', v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
                  '; settled from tick', v['settled_from_tick'])

    def test_10_s05_03_04_not_crossable_at_1080(self):
        """Negative control at the base 1080 range from the nominal S05-03/04 press states.

        S05-03 (press pose y -10146, above the S05 band): the pull hook is never acquired. S05-04 (press pose
        y -8040, inside the S05 band): before TASK-529 the band was the upgrade trigger and re-granted 1620
        before the throw landed; TASK-529 moved the trigger to S05's rangeUpgradeZone (landing on the S04 exit
        ledge), so the base range now holds through the S05-04 throw and the exit hook is never acquired.
        """
        out = {}
        band = self.report()['manifest']['sections'][4]['band']
        for name, anchor, plan, tick, box, press in (
                ('S05-03', 'S05-pull-hook', self.S05_01_V3+self.S05_02_V3, self.PULL_PRESS, self.S05_02_AT_410,
                 [(0,'mousedown',*self.PULL_V3),(200,'mouseup',*self.PULL_V3)]),
                ('S05-04', 'S05-exit-hook', self.S05_01_V3+self.S05_02_V3+self.S05_03_V3, self.EXIT_PRESS, self.S05_03_EXIT,
                 [(0,'mousedown',*self.EXIT_HOOK_V3),(120,'mouseup',*self.EXIT_HOOK_V3)])):
            nominal = self.run_s05(name+'-to-%d' % tick, plan, tick, box, folder='negative', density_until=0)[0]
            mid = dict(nominal['snapshots'][tick]['state']['simulation']); mid['upgrades'] = dict(mid['upgrades'], range=False)
            label = 'NEGATIVE CONTROL: the nominal %s press state at tick %d with upgrades.range set to false (base 1080 range)' % (name, tick)
            trace, players, mech, result = self.run_s05(name+'-range1080', press, 240, dict(x=[0,6480], y=[-13500,180], speedX=[-30,30], speedY=[-30,30]),
                                                        folder='negative', density_until=0, start=mid, start_label=label)
            acquired = [dict(tick=e['tick'], element=e['element'], anchor=e['rope'][0]) for e in mech if e['type']=='acquisition']
            ranges = [snap['state']['simulation']['upgrades']['range'] for snap in trace['snapshots']]
            upgraded = next((t for t, r in enumerate(ranges) if r), None)
            in_band = band['top'] <= mid['player']['y'] <= band['bottom']
            hit = [a for a in acquired if a['element'] == anchor]
            if name == 'S05-03':
                # Above the band: the press and the whole throw stay at the base range and the pull hook is out of reach.
                # (The throw instead catches the near corner of the green catch deck; that swing drops into the band,
                # so the upgrade is re-earned later in the run.)
                self.assertFalse(in_band)
                self.assertFalse(any(ranges[:21]), ranges[:21])
                self.assertEqual(hit, [], mech)
                self.assertFalse([e for e in mech if e['element'] in ('S05-exit-hook','S05-exit-canopy','S05-exit-ledge')], mech)
                self.assertFalse(any(self.in_box(p, self.S05_EXIT_DRAG) for p in players))
            else:
                # Inside the band, but the band no longer grants the range (TASK-529): the throw stays at the base
                # range and the exit hook (nearest point 1428.7 from the press pose) is never acquired.
                self.assertTrue(in_band)
                self.assertFalse(any(ranges[:21]), ranges[:21])
                self.assertEqual(hit, [], mech)
            out[name] = dict(start=label, press_pose=mid['player'], press_pose_inside_s05_upgrade_band=in_band, s05_band=band,
                             gap_anchor=anchor, gap_anchor_acquired=bool(hit), acquisitions=acquired, range_reearned_at_tick=upgraded,
                             range_false_through_throw=not any(ranges[:21]), final=players[-1],
                             exit_pocket_reached=any(self.in_box(p, self.S05_EXIT_DRAG) for p in players))
        out['S05-04']['note'] = ('the S05-04 press pose lies inside the S05 band, which since TASK-529 no longer grants the range (the trigger is '
                                 "S05's rangeUpgradeZone on the S04 exit ledge): the base range holds through the throw and the exit hook is not "
                                 'acquired (range re-earned at tick %s); the geometric nearest-point check is in rules.json (gaps_not_crossable_at_1080)'
                                 % out['S05-04']['range_reearned_at_tick'])
        self.evidence.write('negative/s05_03_04_result.json', dict(self.proof, passed=True, range_1080=out,
            note='S05-03: with the base range the pull-hook shot falls short (gap anchor never acquired, exit pocket never reached). '
                 'S05-04: see range_1080.S05-04.note'))
        print('PASS 1080 negative control: S05-03 pull hook not acquired at the base range (other acquisitions',
              [a['element'] for a in out['S05-03']['acquisitions']], ', range false through the throw, exit pocket not reached); '
              'S05-04 exit hook not acquired at the base range (acquisitions', [a['element'] for a in out['S05-04']['acquisitions']],
              ', range false through the throw; the S05 band no longer grants it)')


class GalleriesV3ToleranceChecks(DeflectorV3ToleranceChecks):
    """Layout-v3 Cable Galleries (S05) tolerance on desktop 1280x720 and touch 844x390 (TASK-519).

    Proof kind (as TASK-517/518): the real S04 v3 exit settled pose of one base-start real-input
    S01..S04 v3 run is restored once as a labeled initial placement (initial_snapshot); production
    trusted mouse/touch input and physics run from there. An attempt on encounter k replays the S05
    route up to k: the encounter's inputs carry the variant, the earlier encounters keep their nominal
    inputs. S05-01..03 end in flight, so they are judged at their mountain.js exit boxes (position at
    the nominal exit tick 304/405/655); S05-04 at the S05 section exit (settled on the green exit
    ledge inside S05-exit-drag at tick 1300). check_s05_v3_mechanics requires the encounter's own
    mechanic, the S05 anchors in route order and no fall onto an S01-S04 element or an S05 fall
    bouncer. The HUD probe reads the UI boxes the game draws (LAYOUT_PROBE) at every nominal press.
    No earlier Task519Tests exists (the layout-v2 S05 tolerance was never built), so there is no v2
    suite to map.
    """
    G, GC = GalleriesV3Checks, GalleriesV3CompleteChecks
    SEGMENTS = [G.S05_01_V3, G.S05_02_V3, GC.S05_03_V3, GC.S05_04_V3]
    V3_ENCOUNTERS = [('S05-01','blue hoist pulled up-right out of S04-exit-drag, release under the green canopy (rise turned into a drop) onto the angled green deflector',0,G.S05_01_TICKS),
                     ('S05-02','blue lift caught in flight off the deflector throw, release into the green baffle (flight reversed west)',G.S05_01_TICKS,G.S05_02_TICKS),
                     ('S05-03','green pull hook caught in flight while flying west off the baffle, long swing west and back east under the catch deck, release on the upswing',G.S05_02_TICKS,GC.S05_03_TICKS),
                     ('S05-04','green exit hook caught from the swing-release flight, release into S05-exit-drag under the green exit canopy, settle on the green exit ledge (S05 section exit)',GC.S05_03_TICKS,None)]
    S05_TICKS = GC.S05_04_TICKS
    STRICT = {'S05-01':G.S05_01_EXIT, 'S05-02':G.S05_02_EXIT, 'S05-03':G.S05_03_EXIT}
    # Mistimed releases, one per encounter, no further input afterwards: (encounter, release tick
    # replacing the nominal one, nominal release tick, ticks, declared fall point or None, landing bouncer).
    # S05-01: the hoist released 20 ticks early drops from its apex back through S04-exit-drag onto the green
    # S04 exit ledge (S05-01-short). S05-02: the lift released 20 ticks early still glances off the baffle and
    # drops through S05-fall-drag onto the green catch deck (the S05-02-missed column and bouncer). S05-03: the
    # pull hook held 50 ticks too long throws the player up into the exit hook's underside (a side glance that
    # reverses the flight west), up through S05-fall-drag and back down onto the catch deck. S05-04: the exit
    # hook released 40 ticks early (S05-04-early) rises into S05-exit-drag and drops from the exit canopy onto
    # the exit ledge. The S05-03/04 releases are below their landing surface (released on an upswing), so the
    # rebound is judged against the drop from the apex; the release-height rule applies where the release is above.
    MISTIMED = [('S05-01',130,150,1100,'S05-01-short','S04-exit-ledge'), ('S05-02',345,365,1300,'S05-02-missed','S05-catch-deck'),
                ('S05-03',700,650,1500,None,'S05-catch-deck'), ('S05-04',735,775,1500,'S05-04-early','S05-exit-ledge')]
    UNDECLARED = {'S05-03':'undeclared S05-03 line: the pull hook held too long throws the player into the exit hook underside, '
                           'then west up through S05-fall-drag and down onto the green catch deck (the S05-02-missed bouncer)'}
    V3_MOVERS = G.S05_V3_MOVERS
    ANCHOR_IDS = {'S05-01':'S05-hoist','S05-02':'S05-lift','S05-03':'S05-pull-hook','S05-04':'S05-exit-hook'}
    HUD_FINDING = ('No HUD obstruction found: every S05 anchor is drawn clear of the HUD text rows and the pause button at its '
                   'press on both viewports (no S05 geometry moved for the HUD).')
    S04_V3_ROUTE, S04_V3_TICKS, S04_V3_SETTLE = G.S04_V3_ROUTE, G.S04_V3_TICKS, G.S04_V3_SETTLE
    S04_EXIT_DRAG, S04_V3_ACQUIRED, S05_V3_ROUTE_ELEMENTS = G.S04_EXIT_DRAG, G.S04_V3_ACQUIRED, G.S05_V3_ROUTE_ELEMENTS
    s04_v3_exit = G.s04_v3_exit

    def exits(self):
        """Per encounter: (ticks, judged exit bounds, meaning), from the runtime manifest."""
        enc = {e['id']:e for e in self.report()['manifest']['encounters'][16:20]}
        out = {}
        for name, _, _, tick in self.V3_ENCOUNTERS:
            if tick:
                b = enc[name]['exit']
                out[name] = (tick, dict(x=[b['left'],b['right']], y=[b['top'],b['bottom']]),
                             f'inside the mountain.js {name} exit box at the nominal exit tick {tick}')
            else:
                out[name] = (self.S05_TICKS, self.GC.S05_04_EXIT,
                             'settled on S05-exit-ledge inside S05-exit-drag (S05 section exit) at tick %d' % self.S05_TICKS)
        return out

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s05_v3_mechanics
        start = self.s04_v3_exit()
        self.assertTrue(self.inside(start['player'], self.S04_V3_SETTLE), start['player'])
        exits = self.exits()
        source = hashes()
        suite = dict(section='S05', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='isolated: one labeled initial placement (initial_snapshot) = the real S04 v3 exit settled pose of a base-start '
                       'real-input S01..S04 v3 run (encounters/S04-exit-start), then production trusted mouse/touch input and physics; '
                       'an attempt on encounter k carries the variant on k and the TASK-517/518 nominal inputs on S05-01..k-1',
            initial_placement=type(self).v3_s04_start_proof, browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exits={n: dict(ticks=t, box=b, meaning=w) for n, (t, b, w) in exits.items()},
            mechanics_check='tools/grapple_over_verify.py check_s05_v3_mechanics',
            nominal_note='every nominal press aims at its anchor at the exact world point of its desktop press pixel (TASK-517/518), so '
                         'desktop and touch run the same route; every anchor is drawn clear of the HUD text and the pause button at '
                         'its press (hud-probe.json)',
            pause_button_client_rects={str(k): v for k, v in self.PAUSE_BUTTON.items()},
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            hud_probe='hud-probe.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal, clips = [], {}, {}
        for k, (name, mechanic, begin, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            ticks, bounds, meaning = exits[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), ticks, bounds, device, snapshot=start)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s05_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s05_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(self.clear(targets), (label, targets))
                        if exit_tick:
                            self.assertTrue(self.inside(players[exit_tick], self.STRICT[name]), (label, players[exit_tick]))
                            end = exit_tick
                        else:
                            end = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S05-exit-ledge')
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', begin, end)
                        clips[label] = (trace, m['metadata']['viewport'], prefix, mechanics)
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning),
                        outcome=f'{name} exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(artifacts/TASK-544/calibration.json density_cap.frozen_ticks = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','mover contact (S05-hoist/S05-lift are only rope anchors; no player contact with them occurs)'],
            cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal S05 run (0/304/405/655) to its manifest exit tick '
                   '(304/405/655) or, for S05-04, the exit-ledge landing; the settle on the exit ledge is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(start, exits['S05-04'])
        self.hud_probe(clips)
        self.assertEqual(failures, [])
        print('PASS S05 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-exit-hook negative control fails the exit')

    def negative_control(self, start, exit):
        from grapple_over_verify import hashes, check_s05_v3_mechanics
        # Named omission: the S05-04 exit-hook press/release left out; same placement, physics and
        # S05-01..03 inputs as every S05-04 attempt.
        ticks, bounds, meaning = exit
        plan = self.variant_plan(3)[:6]
        m = self.make_input(plan, ticks, bounds, snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s05_v3_mechanics('S05-04', trace, required=False)
        landed = [b for b in mechanics['bounces'] if b['tick'] > self.GC.PULL_RELEASE]
        self.evidence.write('negative-control.json', dict(name='omitted exit hook: S05-04 S05-exit-hook press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning), unchanged_physics=True, source_hashes=hashes(),
            proof_kind='same labeled S04-exit placement, real mouse input, same S05-01..03 inputs as the S05-04 attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step, bounces_after_pull_release=landed,
            exit_ledge_contact='S05-exit-ledge' in [b['element'] for b in mechanics['bounces']], final_player=players[-1],
            scope='Without the exit-hook pull the swing-release flight off the pull hook falls back down the galleries '
                  '(first bouncer %s) and the S05 section exit is missed.' % (landed[0]['element'] if landed else 'none')))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S05-exit-hook', mechanics['acquisitions'])
        self.assertNotIn('S05-exit-ledge', [b['element'] for b in mechanics['bounces']])
        self.assertFalse(self.inside(players[-1], self.GC.S05_04_EXIT))
        self.assertLess(step, 60)
        print('PASS negative control: omitted exit hook; reason', reason[:80], '; bounces after the pull release',
              [(b['element'], b['tick']) for b in landed][:4], '; final', (round(players[-1]['x'],1), round(players[-1]['y'],1)))

    # test_02 hooks (LiftworksV3ToleranceChecks runs the same fall rule from the S05 exit pose).
    FALL_SECTION_INDEX, FALL_ZONE_PREFIXES = 4, ('S01-','S02-','S03-','S04-','S05-')
    FALL_PROOF = 'labeled S04-exit placement, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation'

    def fall_start(self):
        return self.s04_v3_exit()

    def section_mechanics(self, name, trace, required=True):
        from grapple_over_verify import check_s05_v3_mechanics
        return check_s05_v3_mechanics(name, trace, required)

    LEANING_FACES = ()

    def fall_segment(self, k):
        """The encounter's press and nominal release; the mistimed release replaces the latter."""
        return self.SEGMENTS[k]

    def test_02_mistimed_release_no_bounce_back(self):
        start = self.fall_start()
        elements = {e['id']:e for e in self.report()['manifest']['geometry']['elements']}
        zones = {k: self.bounds_v3(e) for k, e in elements.items() if e['role']=='drag' and k.startswith(self.FALL_ZONE_PREFIXES)}
        falls = {f['id']:f for f in self.report()['report']['sections'][self.FALL_SECTION_INDEX]['rules']['dragUnderFall']['measured']['fallPoints']}
        inzone = lambda p, b: b['left'] <= p['x'] <= b['right'] and b['top'] <= p['y'] <= b['bottom']
        rows = {}
        self.assertEqual([r[0] for r in self.MISTIMED], [r[0] for r in self.V3_ENCOUNTERS])
        for k, (name, release, nominal, ticks, fall_id, landing_id) in enumerate(self.MISTIMED):
            segment = self.fall_segment(k)
            self.assertEqual(segment[1][0], nominal)
            for device in ('desktop','touch'):
                plan = [p for seg in self.SEGMENTS[:k] for p in seg]+[segment[0], (release,)+segment[1][1:]]
                m = self.make_input(plan, ticks, dict(y=[-1e9, 1e9]), device, snapshot=start)
                prefix = f'clips/fall-{name}-{device}'
                trace, success, reason = self.run_attempt(m, prefix, True)
                self.assertTrue(success, reason)
                self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                mech = self.section_mechanics(name, trace, required=False)
                anchor = mech['encounter']['anchor']
                rel = next(r for r in mech['releases'] if r['element']==anchor)
                self.assertEqual(rel['tick'], release)
                r_player = players[release]
                bounces = [e for e in trace['events'] if e['type']=='bounce' and e['tick'] > release]
                landings = [e for e in bounces if e['contact']['elementId']==landing_id]
                self.assertTrue(landings, name)
                landing = landings[0]; land = landing['tick']
                self.assertEqual(elements[landing_id]['role'], 'bounce')
                # Before the landing bouncer only side glances (sideways speed reversed, no gain in upward speed)
                # and canopy hits (a rise turned into a drop) are allowed.
                glances = [e for e in bounces if e['tick'] < land]
                for e in glances:
                    before, after = e['before']['simulation']['player'], e['after']['simulation']['player']
                    side = before['speedX']*after['speedX'] < 0 and after['speedY'] >= before['speedY']-1e-6
                    canopy = before['speedY'] < 0 < after['speedY']
                    # A declared leaning face (LEANING_FACES) may lift the reversed flight by at most its lean
                    # (|ny| of the face normal) times the speed: a near-level rebound, not a bounce back up.
                    leaning = (e['contact']['elementId'] in self.LEANING_FACES and before['speedX']*after['speedX'] < 0
                               and -after['speedY'] <= abs(e['contact']['ny'])*math.hypot(after['speedX'], after['speedY'])+1e-6)
                    self.assertTrue(side or canopy or leaning, (name, e['contact'], before, after))
                crossed = {z: [t for t in range(release, land+1) if inzone(players[t], b)] for z, b in zones.items()}
                crossed = {z: ts for z, ts in crossed.items() if ts}
                self.assertTrue(crossed, name)
                # The landing is inside or directly below the last drag zone crossed.
                last = max(crossed, key=lambda z: crossed[z][-1])
                self.assertLessEqual(land - crossed[last][-1], 120, (name, last))
                rest_y = landing['after']['simulation']['player']['y']
                apex_tick = min(range(release, land), key=lambda t: players[t]['y'])
                second = next((e['tick'] for e in landings if e['tick'] > land+1), ticks)
                peak_tick = min(range(land+1, second), key=lambda t: players[t]['y'])
                release_height = rest_y - r_player['y']
                peak_height = rest_y - players[peak_tick]['y']
                fall_height = rest_y - players[apex_tick]['y']
                if release_height > 0:
                    self.assertLessEqual(peak_height, .5*release_height, name)
                self.assertGreater(fall_height, 0, name)
                self.assertLessEqual(peak_height, .5*fall_height, name)
                targets = self.targets(trace, m['metadata']['viewport'])
                self.assertTrue(self.clear(targets), targets)
                step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
                self.assertLess(step, 60)
                declared = falls[fall_id] if fall_id else None
                if declared:
                    self.assertEqual(declared['firstBouncer'], landing_id)
                row = dict(encounter=name, device=device, viewport=m['metadata']['viewport'], anchor=anchor,
                    mistiming=f'{anchor} released at tick {release}'+(f' instead of {nominal}' if nominal is not None else ' (the nominal holds it to the finish)')+'; no further input',
                    input=prefix+'/input.json.gz', trace=prefix+'/trace.json', filmstrip=prefix+'/filmstrip.jpg',
                    release=dict(tick=release, player=r_player), landing_rest_y=rest_y,
                    release_height=release_height, release_height_definition='landing-bouncer bounce y minus player y at the release tick',
                    apex=dict(tick=apex_tick, y=players[apex_tick]['y']), fall_height_from_apex=fall_height,
                    release_above_landing=release_height > 0,
                    bounces_before_landing=[dict(tick=e['tick'], element=e['contact']['elementId'],
                        before=e['before']['simulation']['player'], after=e['after']['simulation']['player']) for e in glances],
                    drag_zones_crossed=[dict(id=z, box=zones[z], ticks=[ts[0], ts[-1]], entry_player=players[ts[0]],
                        exit_player=players[ts[-1]]) for z, ts in sorted(crossed.items(), key=lambda x: x[1][0])],
                    declared_fall_point=dict(id=fall_id, x=declared['x'], dragZones=declared['dragZones'], firstBouncer=declared['firstBouncer'])
                        if declared else dict(id=None, note=self.UNDECLARED[name]),
                    first_bounce=dict(element=landing_id, tick=land, before=landing['before']['simulation']['player'],
                        after=landing['after']['simulation']['player']),
                    first_bounce_peak=dict(tick=peak_tick, y=players[peak_tick]['y'], height=peak_height,
                        fraction_of_release_height=peak_height/release_height if release_height > 0 else None,
                        fraction_of_apex_fall=peak_height/fall_height),
                    at_most_half_of_release_height=True if release_height > 0 else 'n/a (released below the landing surface)',
                    at_most_half_of_apex_fall=True, max_tick_displacement=step, press_targets=targets, relocation=False)
                rows.setdefault(name, {})[device] = row
                print('PASS fall', name, device, ': release tick', release, 'y', round(r_player['y'],1), '; drag zones',
                      [d['id'] for d in row['drag_zones_crossed']], '; first bounce', landing_id, 'tick', land, '; first peak',
                      round(peak_height,1), '=', round(peak_height/fall_height,3), 'of the apex fall', round(fall_height,1),
                      '; release height', round(release_height,1))
        self.evidence.write('no-bounce-back.json', dict(self.proof, rule='a mistimed release passes through the drag zone below '
            'it and its first bounce peaks at most 50% of the drop from the apex, and at most 50% of the release height where the '
            'release is above the landing surface',
            proof_kind=self.FALL_PROOF,
            encounters=rows, passed=True))


V1_S06_REVISION = '131bc65'
# What happened to every static v1 S06 solid and v1 S06 mover in the layout-v3 rebuild (TASK-520).
V1_S06_DISPOSITION = {
    'S06-loading-floor':('deleted','v1 S06-01 loading floor under the counterweight; the v3 S06-01 pulls the blue carriage out of the S05 exit drag zone'),
    'S06-phase-rest':('converted-to-bounce','v1 S06-02/03 rest; still a v1 Crown recovery opening collider (recoveries[6]); same place and shape, '
                      'now green; no v3 S06 route uses it'),
    'S06-fixed-head':('deleted','v1 S06-04 fixed head; S06-03/04 are planned again (TASK-521)'),
    'S06-transfer-head':('deleted','v1 S06-04 transfer head under the S05 exit ledge; S06-03/04 are planned again (TASK-521)'),
    'S06-exit':('converted-to-bounce','v1 S06 exit deck; was the v1 S07-01 start ledge (the v3 S07-01 starts on the S06 exit ledge since '
                'TASK-523); same place and shape, now green; no v3 route uses it'),
}
V1_S06_MOVER_DISPOSITION = {
    'S06-counterweight':('deleted','v1 S06-01..03 blue counterweight; the v3 S06-01/02 movers are the blue carriage and the blue lift'),
    'S06-upper-weight':('deleted','v1 S06-04 blue upper weight; S06-03/04 are planned again (TASK-521)'),
}
V3_S06_ADDED = ('S06-carriage','S06-skid','S06-lift','S06-canopy','S06-catch-ledge','S06-fall-drag',
                'S06-climb-hook','S06-swing-skid','S06-exit-hook','S06-exit-ledge','S06-drop-ledge','S06-exit-drag','S06-drop-drag')


class LiftworksV3Checks:
    """Layout-v3 Liftworks opening (S06-01/02) from the real S05 v3 exit settled pose (TASK-520).

    The start pose is the real S05 exit settled pose produced by the v3 S05 build, by the chain that proves it
    (TASK-518 S05-full): one base-start real-input run of the v3 S01..S04 routes (6545 ticks, no placement) settles on
    the S04 exit ledge, and the v3 S05 route runs from that pose (1400 ticks) onto the green S05 exit ledge inside
    S05-exit-drag. That pose is restored once as a labeled initial placement (initial_snapshot), then production
    trusted input and physics run. Not a continuous-completion claim.
    Range is 1620 (held since the S03 route climbs through the S05 band, the TASK-502 trigger). Both S06 press poses
    lie inside the S05 band, where physics.js re-grants the upgrade at once, so a runtime 1080 control cannot occur
    there (as TASK-518 recorded for S05-04); test_01 proves each gap is not crossable at 1080 geometrically (nearest
    point of the mover box over its whole travel from the press pose). S06-03/04 are built since TASK-521, so test_01
    judges the completed section (the S06-03/04 routes are LiftworksV3CompleteChecks).
    """
    GV, GC = GalleriesV3Checks, GalleriesV3CompleteChecks
    S05_V3_SETTLE, S05_EXIT_DRAG = GC.S05_04_EXIT, GC.S05_EXIT_DRAG
    START_LABEL = ('the real S05 v3 exit settled pose (the v3 S05 route run from the labeled real S04 v3 exit pose of one base-start '
                   'real-input S01..S04 v3 run, as TASK-518 S05-full)')
    # Exact world points of the desktop press pixels (837,441) and (161,186).
    CARRIAGE_V3, LIFT_V3 = (4708,-9108.422730222008), (1986.1336302249783,-9657.646763051394)
    # S06-01: the carriage pulls the player left out of S05-exit-drag (the rope runs under the S05 pull hook and over
    # the S05 exit hook; a hold past 128 would wrap it on the exit hook); released at 125 the dive lands on the green
    # skid (bounce only), which turns it into a long rising flight west under the S05 catch deck. S06-02: the lift
    # press at 204 catches the blue lift in flight (west of the S05-03 swing loop); the swing pulls the player up-left
    # past it and is released at 258 (before the rope wraps the lift's own corner) into the green canopy, which turns
    # the rise into a drop toward the S04 climb along the left map edge.
    S06_01_V3 = [(5,'mousedown',*CARRIAGE_V3),(125,'mouseup',*CARRIAGE_V3)]
    S06_02_V3 = [(204,'mousedown',*LIFT_V3),(258,'mouseup',*LIFT_V3)]
    CARRIAGE_RELEASE, LIFT_PRESS, LIFT_RELEASE = 125, 204, 258
    S06_V3_MOVERS = ('S06-carriage','S06-lift')
    S06_V3_BAND = (1378, 1458)
    S06_01_EXIT = dict(x=[3200,3340], y=[-9120,-9000], speedX=[-2.95,-2.8], speedY=[-1,-.9])
    S06_02_EXIT = dict(x=[540,660], y=[-9800,-9720], speedX=[-3.8,-3.6], speedY=[1.2,1.45])
    S06_01_TICKS, S06_02_TICKS = 204, 298
    # Manifest exit boxes of S06-03 (the rise at the exit-hook press) and S06-04 (the green exit ledge, section exit).
    # TASK-522: widened from x 1180..1280 so the 3-tick early/late and aim-left climb releases (x 1349.6/1143.2/1289.2 at
    # tick 628, all of which still complete S06-04 with the nominal exit hook) are judged inside; no collider moved.
    S06_03_BOX = dict(x=[1130,1360], y=[-11330,-11230])
    S06_04_BOX = dict(x=[1450,1850], y=[-11300,-11250])
    S06_V3_FALLS = {'S06-01-short':(['S06-fall-drag'],'S06-catch-ledge'), 'S06-02-missed':(['S04-fall-drag'],'S04-catch-basin'),
                    'S06-03-missed':(['S04-fall-drag'],'S04-catch-basin'), 'S06-04-missed':(['S06-drop-drag'],'S06-drop-ledge'),
                    'S06-04-early':(['S06-exit-drag'],'S06-exit-ledge')}
    S06_V3_FALL_POINTS = {'S06-01-short':(6020,-8900), 'S06-02-missed':(30,-9450), 'S06-03-missed':(30,-9540),
                          'S06-04-missed':(1230,-11500), 'S06-04-early':(1500,-11520)}
    S06_V3_GAPS = ('S06-01-carriage','S06-02-lift','S06-03-climb','S06-04-exit')
    S06_V3_ANCHORS = ('S06-carriage','S06-lift','S06-climb-hook','S06-exit-hook')
    S06_V3_ROUTE_ELEMENTS = ('S06-carriage','S06-skid','S06-lift','S06-canopy','S06-catch-ledge','S06-fall-drag')
    # TASK-521 elements, judged with the same S01..S05 path/rope/throw-line clearance. The exit pocket lies under the
    # S04 exit ledge (the S05-01 start), so its player-path clearance bound is lower than the 200 of the other elements.
    S06_V3_ROUTE_ELEMENTS_34 = ('S06-climb-hook','S06-swing-skid','S06-exit-hook','S06-exit-ledge','S06-drop-ledge','S06-exit-drag','S06-drop-drag')
    S06_PLAYER_CLEARANCE = {'S06-exit-drag':60, 'S06-exit-ledge':60}
    LIFT_BOX = dict(left=1880, right=2120, top=-9665, bottom=-9635)
    CATCH_DECK = GalleriesV3CompleteChecks.CATCH_DECK
    S05_FALL_DRAG = GalleriesV3Checks.S05_FALL_DRAG
    # Declared misses: a short carriage hold (released at 40) drops from the exit-pocket mouth through S06-fall-drag
    # onto the green catch ledge; no lift press carries the rising flight under the canopy into the left map edge and
    # down it through S04-fall-drag onto the green S04 catch basin.
    S06_01_SHORT = [(5,'mousedown',*CARRIAGE_V3),(40,'mouseup',*CARRIAGE_V3)]
    S06_FALL_DRAG = dict(left=5700, right=6090, top=-8800, bottom=-8350)
    LEDGE_SETTLE = dict(x=[5700,6090], y=[-8370,-8350], speedX=[-.001,.001], speedY=[-.05,.05])
    S04_FALL_DRAG, BASIN_SETTLE = DeflectorV3Checks.S04_FALL_DRAG, DeflectorV3Checks.BASIN_SETTLE
    report = FoundationsV3Checks.report
    bounds_v3 = staticmethod(SwitchbackV3Checks.bounds_v3)
    inside = staticmethod(FoundationsV3CompleteChecks.inside)
    in_box = staticmethod(FoundationsV3CompleteChecks.in_box)
    fall_s03 = ViaductV3Checks.fall_s03
    # GalleriesV3Checks' labeled-placement runner and mover attribution, driven by the S06 movers and band.
    run_s05, mover_contacts, reach_s05, bounce_s05 = GV.run_s05, GV.mover_contacts, GV.reach_s05, GV.bounce_s05
    S05_V3_MOVERS, S05_V3_BAND = S06_V3_MOVERS, S06_V3_BAND

    def v1_s06(self):
        """The layout-v1 S06 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V1_S06_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[5], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, encounters:m.encounters.slice(20,24), elements:m.geometry.elements.filter(e=>e.id.startsWith('S06-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S06-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S06-'))}}''', source)

    @staticmethod
    def box_gap(b, x, y):
        return math.hypot(max(b['left']-x, 0, x-b['right']), max(b['top']-y, 0, y-b['bottom']))

    def s05_v3_exit(self):
        """Real S05 v3 exit settled pose, by the same chain that proves the S05 build (TASK-518 S05-full).

        One base-start real-input run of the v3 S01..S04 routes (no placement) settles on the S04 exit ledge; its final
        snapshot is restored once (labeled) and the v3 S05 route (TASK-517/518 inputs) runs to the S05 exit ledge.
        A single continuous S01..S05 run is not equivalent: the camera there differs from a restored pose, and the S05
        route's press pixels were calibrated from the restored S04 exit pose.
        """
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'v3_s05_start'): return type(self).v3_s05_start
        m = dict(metadata=metadata('base-start'), ticks=self.GV.S04_V3_TICKS, expected_exit=self.GV.S04_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.GV.S04_V3_ROUTE],
            required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/S04-exit-start'
        self.evidence.write(prefix+'/input.json', m)
        setup = execute(m, self.browser, self.url, str(self.evidence.path(prefix)))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players4 = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players4[0]['x'], players4[0]['y']), (2160, 0))
        acquired4 = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual([a for a in acquired4 if a not in ('S01-entry-pad','S02-exit-ledge')], self.GV.S04_V3_ACQUIRED)
        self.evidence.write(prefix+'/trace.json', Task506Tests.compact(self, setup))
        start4 = setup['snapshots'][-1]['state']['simulation']
        self.assertEqual((round(start4['player']['x'],1), round(start4['player']['y'],1)), (1387.9, -11660.9))
        self.assertIs(start4['upgrades']['range'], True)
        proof4 = dict(kind='base-start v3 S01 route (TASK-548 inputs), v3 S02 route (TASK-551 inputs from tick 1495), '
            'v3 S03 route (TASK-554/555 inputs from tick 3245) and v3 S04 route (TASK-515/516 inputs from tick 4545), real mouse input, no placement',
            inputs=m['inputs'], acquisitions=acquired4, final_tick=self.GV.S04_V3_TICKS, player=start4['player'],
            snapshot_sha256=setup['snapshots'][-1]['sha256'], full_trace_sha256=state_hash(setup), trace=prefix+'/trace.json')
        self.evidence.write(prefix+'/result.json', dict(passed=True, **proof4))
        m5 = dict(metadata=metadata('isolated'), ticks=self.GC.S05_FULL_TICKS, expected_exit=self.S05_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.GC.S05_ROUTE_V3],
            required_events=['acquisition','release','bounce'], initial_snapshot=start4)
        m5['metadata']['compact_contacts'] = True
        prefix5 = 'encounters/S05-exit-start'
        self.evidence.write(prefix5+'/input.json', m5)
        run5 = execute(m5, self.browser, self.url, str(self.evidence.path(prefix5)))
        check_trace(m5, run5)
        self.assertTrue(all(e['trusted'] for e in run5['events'] if e['type']=='input'))
        players5 = [s['state']['simulation']['player'] for s in run5['snapshots']]
        acquired5 = [e['after']['rope'][0]['id'] for e in run5['events'] if e['type']=='acquisition']
        self.assertEqual([a for a in acquired5 if a != 'S04-exit-ledge'], ['S05-hoist','S05-lift','S05-pull-hook','S05-exit-hook'])
        touched = sorted({(e.get('contact') or {}).get('elementId') for e in setup['events']+run5['events']} - {None})
        self.assertFalse([t for t in touched if t.startswith('S06-')], touched)
        self.evidence.write(prefix5+'/trace.json', Task506Tests.compact(self, run5))
        settle = next(t for t in range(self.GC.S05_LAND_BY-100, self.GC.S05_FULL_TICKS+1)
                      if all(self.inside(p, self.S05_V3_SETTLE) for p in players5[t:]))
        self.assertLessEqual(settle, self.GC.S05_FULL_TICKS-100)
        start = run5['snapshots'][-1]['state']['simulation']
        self.assertTrue(self.in_box(start['player'], self.S05_EXIT_DRAG))
        self.assertEqual((round(start['player']['x'],1), round(start['player']['y'],1)), (6120.4, -9432.4))
        self.assertIs(start['upgrades']['range'], True)
        # Clearance of the whole S01..S05 v3 flight, and of every rope segment while attached, from the new S06
        # route colliders and drag zone (movers over their whole travel).
        m2 = self.report()['manifest']
        travel = {v['element']:v for v in m2['geometry']['movers']}
        judged = self.S06_V3_ROUTE_ELEMENTS + self.S06_V3_ROUTE_ELEMENTS_34
        boxes = {e['id']:self.bounds_v3(e, travel.get(e['id'])) for e in m2['geometry']['elements'] if e['id'] in judged}
        self.assertEqual(sorted(boxes), sorted(judged))
        clearance, rope_clearance, throw_clearance = {}, {}, {}
        ropes, throws = [], []
        for trace in (setup, run5):
            for s in trace['snapshots'][::2]:
                st = s['state']
                if st['simulation']['grapple']['grappled'] and st['rope']:
                    pts = [(p['x'], p['y']) for p in st['rope']]+[(st['simulation']['player']['x'], st['simulation']['player']['y'])]
                    ropes += list(zip(pts, pts[1:]))
            # Throw lines: the grapnel tip flies from the player at the press to the acquisition point.
            acq = sorted((e['tick'], e['after']['rope'][0]) for e in trace['events'] if e['type']=='acquisition')
            for e in trace['events']:
                if e['type'] == 'input' and e['event'] == 'mousedown':
                    a = next((v for k, v in acq if k >= e['tick']), None)
                    p = trace['snapshots'][e['tick']]['state']['simulation']['player']
                    if a: throws.append(((p['x'], p['y']), (a['x'], a['y'])))
        seg = lambda b, segs, n: min(self.box_gap(b, a[0]+(c[0]-a[0])*i/n, a[1]+(c[1]-a[1])*i/n) for a, c in segs for i in range(n+1))
        for k, b in boxes.items():
            clearance[k] = min(self.box_gap(b, p['x'], p['y']) for p in players4+players5) - players4[0]['radius']
            rope_clearance[k] = seg(b, ropes, 40)
            throw_clearance[k] = seg(b, throws, 200)
            self.assertGreater(clearance[k], self.S06_PLAYER_CLEARANCE.get(k, 200), (k, clearance))
            self.assertGreater(rope_clearance[k], 20, (k, rope_clearance))
            self.assertGreater(throw_clearance[k], 20, (k, throw_clearance))
        type(self).v3_s05_start = start
        type(self).v3_s05_start_proof = dict(kind='the real S05 v3 exit settled pose: the v3 S05 route (TASK-517/518 inputs, 1400 ticks) run '
            'from ONE labeled placement of the real S04 v3 exit settled pose, which comes from one base-start real-input S01..S04 v3 run '
            '(the chain that proves the S05 build, TASK-518 S05-full)', s04_exit=proof4,
            s05_inputs=m5['inputs'], s05_acquisitions=acquired5, settled_in_exit_box_from_tick=settle, settle_box=self.S05_V3_SETTLE,
            final_tick=self.GC.S05_FULL_TICKS, player=start['player'], inside_S05_exit_drag=True,
            snapshot_sha256=run5['snapshots'][-1]['sha256'], full_trace_sha256=state_hash(run5), trace=prefix5+'/trace.json',
            s06_element_contacts=[], s01_s05_flight_clearance_to_s06_route_elements=clearance,
            player_clearance_bounds={k:self.S06_PLAYER_CLEARANCE.get(k, 200) for k in clearance},
            s01_s05_rope_clearance_to_s06_route_elements=rope_clearance, s01_s05_throw_line_clearance_to_s06_route_elements=throw_clearance,
            throw_lines=len(throws), range_upgraded=start['upgrades']['range'])
        self.evidence.write(prefix5+'/result.json', dict(passed=True, **type(self).v3_s05_start_proof))
        return start

    def run_s06(self, name, plan, ticks, bounds, density_until=None, folder='encounters'):
        """Labeled placement of the real S05 v3 exit pose, then trusted input; identical replay."""
        start = self.s05_v3_exit()
        trace, players, mech, result = self.run_s05(name, plan, ticks, bounds, density_until=density_until, folder=folder,
                                                    start=start, start_label=self.START_LABEL)
        result.pop('s04_exit_ledge_bounces')
        ledge = [x['tick'] for x in mech if x['element'] == 'S05-exit-ledge']
        result.update(initial_placement=dict(labeled=True, source=type(self).v3_s05_start_proof),
            s05_exit_ledge_bounces=dict(count=len(ledge), first=ledge[0] if ledge else None, last=ledge[-1] if ledge else None))
        return trace, players, mech, result

    def s06_kinds(self, mech):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S05-exit-ledge']

    def test_01_geometry_and_rules(self):
        r = self.report(); v1 = self.v1_s06()
        m = r['manifest']; elements = m['geometry']['elements']
        s06 = m['sections'][5]
        self.assertEqual((s06['designVersion'], s06['status']), (3, 'built'))
        enc_all = m['encounters'][20:24]
        self.assertEqual([e['status'] for e in enc_all], ['built']*4)
        # S06-03/04 are built (TASK-521): their links and the S06 fall recovery too; the S07 entrance is built since the
        # v3 S07-01 starts on the S06 exit ledge (TASK-523).
        self.assertEqual([c['status'] for c in m['connectors'][20:25]], ['built']*5)
        self.assertEqual([(c['id'], c['from'], c['to']) for c in m['connectors'][20:24]],
                         [('S06-entrance','S05-04','S06-01'), ('S06-route-1','S06-01','S06-02'), ('S06-route-2','S06-02','S06-03'),
                          ('S06-route-3','S06-03','S06-04')])
        self.assertEqual((m['connectors'][24]['id'], m['connectors'][24]['from']), ('S07-entrance', 'S06-04'))
        rec = m['recoveries'][5]
        self.assertEqual((rec['status'], rec['from'], rec['to'], rec['rejoin']), ('built', 'S06-04', 'S05-01', 'S06-03'))
        self.assertTrue(all(x in [e['id'] for e in elements] for x in rec['elements']))
        self.assertNotIn('solidExceptions', s06)
        self.assertNotIn('fallLines', s06)
        self.assertEqual((s06['band']['top'], s06['band']['bottom']), (-11340, -8100))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S06-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S06-')}
        self.assertEqual(set(movers), set(self.S06_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        self.assertTrue(all(by_id[x]['role'] == 'solid' and by_id[x]['grapplable'] for x in movers))
        enc = {e['id']:e for e in enc_all}
        self.assertEqual(enc['S06-01']['start'], {'x':6120.4,'y':-9432.4,'from':'S05-04'})
        self.assertEqual(enc['S06-02']['start'], {'from':'S06-01','x':3269.4,'y':-9059})
        self.assertEqual(enc['S06-03']['start'], {'from':'S06-02','x':597.5,'y':-9758.5})
        self.assertEqual(enc['S06-04']['start'], {'from':'S06-03','x':1239.8,'y':-11279.8})
        for e in enc_all:
            self.assertTrue(all(x in by_id for x in e['elements']), e['id'])
            self.assertTrue(any(by_id[x]['role'] == 'bounce' for x in e['elements']), e['id'])
        for e in enc_all[:2]:
            self.assertTrue(any(x in movers for x in e['elements']), e['id'])
        self.assertEqual([e['start']['from'] for e in enc_all], ['S05-04','S06-01','S06-02','S06-03'])
        for name, box in (('S06-01', self.S06_01_EXIT), ('S06-02', self.S06_02_EXIT), ('S06-03', self.S06_03_BOX), ('S06-04', self.S06_04_BOX)):
            self.assertEqual(enc[name]['exit'], dict(left=box['x'][0], right=box['x'][1], top=box['y'][0], bottom=box['y'][1]))
        sec = r['report']['sections'][5]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S06', 3, True, [], 1620))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][:6], ['S01','S02','S03','S04','S05','S06'])
        self.assertFalse(r['report']['failed'])
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('left', 'left'))
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S06-01','S06-02'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S06_V3_BAND))
        self.assertEqual([g['id'] for g in gaps], list(self.S06_V3_GAPS))
        for g in gaps:
            self.assertTrue(self.S06_V3_BAND[0] <= g['distance'] <= self.S06_V3_BAND[1], g)
        # Not crossable at 1080: from each press pose the nearest point of the mover (over its whole travel) is beyond 1080.
        travel = {v['element']:v for v in m['geometry']['movers']}
        base_range = {}
        self.assertEqual([g['id'] for g in s06['gaps']], list(self.S06_V3_GAPS))
        for g, mover in zip(s06['gaps'], self.S06_V3_ANCHORS):
            b = self.bounds_v3(by_id[mover], travel.get(mover)); p = g['from']
            near = self.box_gap(b, p['x'], p['y'])
            self.assertGreater(near, 1080, (g['id'], near))
            base_range[g['id']] = dict(anchor=mover, blue_mover=mover in movers, anchor_box_over_travel=b, nearest_point_distance=near,
                                       base_range=1080, beyond_base_range=True)
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], list(self.S06_V3_FALLS))
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), self.S06_V3_FALLS[f['id']], f)
            self.assertEqual((f['x'], f['y']), self.S06_V3_FALL_POINTS[f['id']])
            self.assertEqual(by_id[f['firstBouncer']]['role'], 'bounce')
            for dz in f['dragZones']:
                b = self.bounds_v3(by_id[dz])
                self.assertTrue(b['left'] <= f['x']-18 and f['x']+18 <= b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, dz))
        # Filtered to S06 fall points: the TASK-524 S07-03-short line also drops through S06-drop-drag onto the drop ledge.
        self.assertEqual([dict(d, fallPoints=[f for f in d['fallPoints'] if f.startswith('S06-')]) for d in sec['rules']['strayDrag']['measured']['dragZones']],
            [dict(id='S06-fall-drag', fallPoints=['S06-01-short']), dict(id='S06-exit-drag', fallPoints=['S06-04-early']),
             dict(id='S06-drop-drag', fallPoints=['S06-04-missed'])])
        # Every static v1 S06 solid is deleted or converted to a green bouncer in place; both v1 movers are deleted.
        self.assertEqual(sorted(v1['staticSolids']), sorted(V1_S06_DISPOSITION))
        self.assertEqual(sorted(v1['movers']), sorted(V1_S06_MOVER_DISPOSITION))
        own_ids = {e['id'] for e in own}
        v1_by_id = {e['id']:e for e in v1['elements']}
        mapping = []
        for old in v1['staticSolids']+v1['movers']:
            kind, why = (V1_S06_DISPOSITION | V1_S06_MOVER_DISPOSITION)[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertNotIn(old, own_ids, old)
            else:
                self.assertEqual(now['role'], 'bounce', old)
                self.assertEqual((now['x'], now['y'], now['points']), (v1_by_id[old]['x'], v1_by_id[old]['y'], v1_by_id[old]['points']), old)
            mapping.append(dict(id=old, v1_role='solid' if old in v1['staticSolids'] else 'blue mover', disposition=kind,
                                v3_role=now['role'] if now else None, reason=why))
        self.assertEqual(sorted(set(v1_by_id) - set(V1_S06_DISPOSITION) - set(V1_S06_MOVER_DISPOSITION)), [])
        self.assertEqual(sorted(own_ids - set(v1_by_id)), sorted(V3_S06_ADDED))
        # The v3 S07-01 (TASK-523) starts on the green S06 exit ledge; the legacy v1 S06 pieces kept green in place are no
        # longer named by the Crown.
        self.assertEqual(m['encounters'][24]['start']['from'], 'S06-04')
        self.assertIn('S06-exit-ledge', m['encounters'][24]['elements'])
        # No v3 S06 route element (or its drag zone) overlaps another section's element.
        others = [e for e in elements if e['id'].split('-')[0] in ('S01','S02','S03','S04','S05','S07','S08') or e['id'].startswith('mountain-')]
        for k in self.S06_V3_ROUTE_ELEMENTS + self.S06_V3_ROUTE_ELEMENTS_34:
            ba = self.bounds_v3(by_id[k], travel.get(k))
            for o in others:
                bo = self.bounds_v3(o, travel.get(o['id']))
                self.assertFalse(ba['left'] < bo['right'] and bo['left'] < ba['right'] and ba['top'] < bo['bottom'] and bo['top'] < ba['bottom'], (k, o['id']))
        measured = {g['id']:g['distance'] for g in gaps}
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S06-01','S06-02','S06-03','S06-04'], planned=[],
            active_range=sec['range'], gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1620] = 1378-1458 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=measured, gaps_not_crossable_at_1080=base_range, direction=direction,
            direction_note='the direction rule reads the S06-04 exit box centre x (1650, the green exit ledge under the S04 exit ledge) '
                           'against the S06-01 entry x (6120.4, the S05 exit ledge against the right map edge)',
            mover_coverage=sec['rules']['moverCoverage']['measured'],
            fall_points=falls, own_drag_zones=sec['rules']['strayDrag']['measured']['dragZones'],
            drag_below_every_fall_point=True, gray_solid_count=len(gray)))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s06, encounters=enc_all, planned_encounters=[],
            connectors=m['connectors'][20:25], recovery=m['recoveries'][5], elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True, v1_revision=V1_S06_REVISION,
            v1_static_solids=v1['staticSolids'], v1_movers=v1['movers'], v1_disposition=mapping, v3_added=list(V3_S06_ADDED),
            route_overlaps_with_other_sections=[]))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1097" viewBox="-50 -11800 6600 5656" style="background:#111827">']
        for e in elements:
            if e['id'].split('-')[0] not in ('S04','S05','S07','S08') and e['id'] not in ('mountain-left','mountain-right'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.15' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="3"/>')
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors[roles[e['id']]] + ('" fill-opacity="0.35' if roles[e['id']] == 'yellow drag' else '')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="3"/>')
            dx, dy = {'S06-canopy':(-150,-20),'S06-catch-ledge':(-300,60),'S06-fall-drag':(-300,-10),'S06-carriage':(-300,0),
                      'S06-skid':(-700,90),'S06-lift':(-150,0),'S06-exit':(-250,-40),'S06-phase-rest':(-450,90),
                      'S06-climb-hook':(80,40),'S06-swing-skid':(-200,110),'S06-exit-hook':(-200,-10),'S06-exit-ledge':(450,60),
                      'S06-drop-ledge':(200,40),'S06-exit-drag':(450,-20),'S06-drop-drag':(200,-20)}.get(e['id'], (0,0))
            parts.append(f'<text x="{e["x"]+dx}" y="{e["y"]-16+dy}" fill="white" font-size="56">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+15}" x2="{e["x"]+60+v["max"]-v["min"]}" y2="{e["y"]+15}" stroke="#93c5fd" stroke-width="6" stroke-dasharray="12,8"/>')
        for g in s06['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="6" stroke-dasharray="14,10"/>')
        for f in falls:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="{f["firstBouncerTop"]}" stroke="#fb923c" stroke-width="5" stroke-dasharray="8,12"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="16" fill="#fb923c"/><text x="{f["x"]+30-(700 if f["x"] > 5000 else 0)}" y="{f["y"]+12}" fill="#fb923c" font-size="52">{f["id"]}</text>')
        for e in enc_all:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="6"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+55}" fill="#f472b6" font-size="52">{e["id"]} exit</text>')
        parts.append('<circle cx="6120.4" cy="-9432.4" r="28" fill="#ff7a1a"/>')
        for i, t in enumerate(['S06 Liftworks v3 (designVersion 3, built: S06-01..04, travelling left), zero gray solids',
                'orange dot = real S05 v3 exit settled pose; grey = S04, S05, legacy S07/S08 and the map edges',
                'S06-01: blue carriage pulled left out of S05-exit-drag -> dive -> green skid -> rising flight west under the S05 catch deck',
                'S06-02: blue lift caught in flight -> swing up-left past it -> green canopy turns the rise into a drop',
                'S06-03: green climb hook caught sliding down the map edge -> swing over the green swing skid -> straight rise',
                'S06-04: green exit hook pulls the rise east into S06-exit-drag -> settles on the green exit ledge (section exit)',
                'yellow dashes = gaps %s of 1620 (all > 1080)' % '/'.join(str(round(g['distance'],1)) for g in gaps),
                'orange = fall points over drag zones (S06-02/03-missed drop down the left edge to the S04 catch basin); pink = exit boxes']):
            parts.append(f'<text x="250" y="{-7300+i*66}" fill="#67e8f9" font-size="54">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=dict(width=1280, height=1000)); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S06 designVersion 3 built (S06-01..04); gray solids', len(gray), '; roles',
              sorted(set(roles.values())), '; all 7 v3 rules pass at range', sec['range'], '; direction left', direction['entryX'], '>', direction['exitX'],
              '; gaps', [round(g['distance'],1) for g in gaps], 'in', list(self.S06_V3_BAND), '; nearest mover point from each press',
              {k:round(v['nearest_point_distance'],1) for k, v in base_range.items()}, '> 1080; fall points over drag',
              {f['id']:f['dragZones'] for f in falls}, '; v1', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def s06_01_checks(self, trace, players, mech, result):
        out = next(t for t in range(6, len(players)) if not self.in_box(players[t], self.S05_EXIT_DRAG))
        self.assertLess(out, self.CARRIAGE_RELEASE)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S06-carriage']['dx']), 1)
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S06-carriage')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S06-carriage')
        self.assertEqual(release['tick'], self.CARRIAGE_RELEASE)
        rel = players[self.CARRIAGE_RELEASE]
        self.assertTrue(rel['speedX'] < -2 and rel['speedY'] > 0, rel)
        skid, before, after = self.bounce_s05(trace, 'S06-skid')
        # Flat green floor: the dive is turned into a rise, the westward speed kept.
        self.assertGreater(before['speedY'], 1); self.assertAlmostEqual(after['speedY'], -before['speedY'], delta=.02)
        self.assertAlmostEqual(after['speedX'], before['speedX'], delta=1e-6); self.assertLess(after['speedX'], -2)
        # No other contact from the carriage acquisition to the lift press; the rising flight passes under the S05
        # catch deck (>= 50 clear of its underside) and never enters S05-fall-drag.
        # (Small hops on the green S05 exit ledge while the pull drags the player off it are the start ledge.)
        ledge = [e['tick'] for e in trace['events'] if e['type'] in ('contact','bounce') and (e.get('contact') or {}).get('elementId') == 'S05-exit-ledge']
        self.assertLessEqual(max(ledge), out)
        quiet = [e for e in trace['events'] if e['type'] in ('contact','bounce') and acq['tick'] <= e['tick'] <= self.S06_01_TICKS
                 and e['tick'] != skid['tick'] and (e.get('contact') or {}).get('elementId') != 'S05-exit-ledge']
        self.assertEqual(quiet, [])
        under = [t for t in range(self.CARRIAGE_RELEASE, self.S06_01_TICKS+1) if self.CATCH_DECK['left'] <= players[t]['x'] <= self.CATCH_DECK['right']]
        self.assertTrue(under)
        clear = min(players[t]['y'] - players[t]['radius'] - self.CATCH_DECK['bottom'] for t in under)
        self.assertGreater(clear, 50)
        self.assertFalse([t for t in range(len(players)) if self.in_box(players[t], self.S05_FALL_DRAG)])
        self.assertTrue(self.inside(players[self.S06_01_TICKS], self.S06_01_EXIT), players[self.S06_01_TICKS])
        return dict(left_s05_exit_drag_tick=out, carriage_release=dict(tick=self.CARRIAGE_RELEASE, player=rel),
                    skid_bounce=dict(tick=skid['tick'], before=before, after=after),
                    start_ledge_hops=dict(count=len(ledge), last_tick=max(ledge)),
                    rising_flight_under_s05_catch_deck=dict(ticks=[under[0], under[-1]], min_clearance_below_deck=clear, catch_deck=self.CATCH_DECK,
                                                            entered_S05_fall_drag=False), other_contacts_between_acquisition_and_lift_press=[])

    def test_02_s06_01_nominal(self):
        trace, players, mech, result = self.run_s06('S06-01', self.S06_01_V3, self.S06_01_TICKS, self.S06_01_EXIT)
        self.assertEqual(self.s06_kinds(mech), [('acquisition','S06-carriage'),('release','S06-carriage'),('bounce','S06-skid')])
        checks = self.s06_01_checks(trace, players, mech, result)
        reach = self.reach_s05(players, mech, 5, 'S06-carriage')
        result.update(encounter='S06-01', acquisition_reach=reach, **checks)
        self.evidence.write('encounters/S06-01/result.json', result)
        sb = checks['skid_bounce']
        print('PASS S06-01: from the real S05 v3 exit pose (range upgraded', result['range_upgraded_at_start'], '); blue carriage acquisition',
              round(reach['distance'],1), 'at tick', reach['acquisition_tick'], '; left S05-exit-drag at tick', checks['left_s05_exit_drag_tick'],
              '; released at', self.CARRIAGE_RELEASE, '; green skid bounce at tick', sb['tick'], 'v', (round(sb['before']['speedX'],3), round(sb['before']['speedY'],3)),
              '->', (round(sb['after']['speedX'],3), round(sb['after']['speedY'],3)), '; under the S05 catch deck, clearance',
              round(checks['rising_flight_under_s05_catch_deck']['min_clearance_below_deck'],1), '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s06_02_nominal(self):
        trace, players, mech, result = self.run_s06('S06-02', self.S06_01_V3+self.S06_02_V3, self.S06_02_TICKS, self.S06_02_EXIT)
        self.assertEqual(self.s06_kinds(mech), [('acquisition','S06-carriage'),('release','S06-carriage'),('bounce','S06-skid'),
            ('acquisition','S06-lift'),('release','S06-lift'),('bounce','S06-canopy')])
        self.s06_01_checks(trace, players, mech, result)
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S06-lift')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S06-lift')
        self.assertTrue(self.LIFT_PRESS < lift['tick'] < release['tick'] == self.LIFT_RELEASE)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S06-lift']['dx']), 1)
        launch = players[self.S06_01_TICKS]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (3269.4, -9059.0))
        # Caught in flight: still flying west, no contact between the skid bounce and the canopy.
        skid = next(e['tick'] for e in mech if e['element']=='S06-skid')
        canopy_tick = next(e['tick'] for e in mech if e['element']=='S06-canopy')
        self.assertLess(players[lift['tick']]['speedX'], -2)
        self.assertFalse([e for e in trace['events'] if e['type'] in ('contact','bounce') and skid < e['tick'] < canopy_tick])
        # The swing pulls the player up-left: it passes under the lift (clear below its bottom over the lift's whole
        # travel), its climb steepens, and the release flies up-left with only the lift anchor on the rope.
        under = [t for t in range(lift['tick'], release['tick']+1) if self.LIFT_BOX['left'] <= players[t]['x'] <= self.LIFT_BOX['right']]
        self.assertTrue(under)
        below = min(players[t]['y'] - players[t]['radius'] - self.LIFT_BOX['bottom'] for t in under)
        self.assertGreater(below, 50)
        rel = players[release['tick']]
        self.assertTrue(rel['speedX'] < -3 and rel['speedY'] < players[lift['tick']]['speedY'] - .3, rel)
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][lift['tick']:release['tick']+1]))
        bounce, before, after = self.bounce_s05(trace, 'S06-canopy')
        # Flat green ceiling: the rise is turned into a drop, the westward speed kept.
        self.assertLess(before['speedY'], -1); self.assertAlmostEqual(after['speedY'], -before['speedY'], delta=.1)
        self.assertAlmostEqual(after['speedX'], before['speedX'], delta=1e-6); self.assertLess(after['speedX'], -3)
        carriage = self.reach_s05(players, mech, 5, 'S06-carriage')
        reach = self.reach_s05(players, mech, self.LIFT_PRESS, 'S06-lift')
        far = math.hypot(before['x']-launch['x'], before['y']-launch['y'])
        self.assertGreater(far, 1620)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {'S06-carriage':carriage, 'S06-lift':reach}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S06-02', segmented_from='S06-01 exit at tick 204 of the same run (no further placement)',
            s06_01_exit_at_tick_204=launch, acquisition_reach=reach, caught_in_flight=dict(tick=lift['tick'], player=players[lift['tick']]),
            swing_under_lift=dict(ticks=[under[0], under[-1]], min_clearance_below_lift_bottom=below, lift_box_over_travel=self.LIFT_BOX,
            rope_points_max=2), lift_release=dict(tick=release['tick'], player=rel), canopy_bounce=dict(tick=bounce['tick'], before=before,
            after=after, distance_from_launch=far))
        self.evidence.write('encounters/S06-02/result.json', result)
        print('PASS S06-02: from the S06-01 exit at tick', self.S06_01_TICKS, '; blue lift acquisition', round(reach['distance'],1), 'at tick',
              lift['tick'], '(in flight, vx', round(players[lift['tick']]['speedX'],3), '); swing under the lift (clearance', round(below,1),
              '); released at', release['tick'], 'flying up-left; green canopy bounce at tick', bounce['tick'], 'vy', round(before['speedY'],3), '->',
              round(after['speedY'],3), ',', round(far,1), 'from the launch; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def contacts(self, trace):
        return [e for e in trace['events'] if e['type']=='contact']

    def test_04_declared_falls_through_drag(self):
        out = {}
        trace, players, mech, result = self.run_s06('S06-01-short', self.S06_01_SHORT, 900, self.LEDGE_SETTLE, density_until=40, folder='falls')
        kinds = self.s06_kinds(mech)
        self.assertEqual(kinds[:2], [('acquisition','S06-carriage'),('release','S06-carriage')])
        self.assertFalse([k for k in kinds[2:] if k[1] != 'S06-catch-ledge'], kinds)
        out['S06-01-short'] = self.fall_s03(trace, players, mech, 40, 'S06-catch-ledge', self.S06_FALL_DRAG, self.LEDGE_SETTLE)
        fx, fy = self.S06_V3_FALL_POINTS['S06-01-short']
        cross = next(t for t in range(40, len(players)) if players[t]['y'] >= fy)
        self.assertLessEqual(abs(players[cross]['x']-fx), 18)
        out['S06-01-short']['declared_point_crossing'] = dict(tick=cross, player=players[cross])
        trace, players, mech, result = self.run_s06('S06-02-missed', self.S06_01_V3, 2000, self.BASIN_SETTLE, density_until=self.LIFT_PRESS, folder='falls')
        kinds = self.s06_kinds(mech)
        self.assertEqual(kinds[:3], [('acquisition','S06-carriage'),('release','S06-carriage'),('bounce','S06-skid')])
        self.assertNotIn(('acquisition','S06-lift'), kinds)
        # The rising flight passes under the canopy (no contact) into the left map edge.
        self.assertFalse([k for k in kinds[3:] if k[1] != 'S04-catch-basin'], kinds)
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 0]
        self.assertTrue(edge)
        out['S06-02-missed'] = self.fall_s03(trace, players, mech, self.CARRIAGE_RELEASE, 'S04-catch-basin', self.S04_FALL_DRAG, self.BASIN_SETTLE)
        out['S06-02-missed']['left_map_edge_first_contact'] = dict(tick=edge[0], player=players[edge[0]])
        self.assertLessEqual(players[edge[0]]['y'], self.S06_V3_FALL_POINTS['S06-02-missed'][1]+20)
        for k, v in out.items():
            # Every drop starts at its apex above the declared fall point, far above the landing.
            self.assertLessEqual(v['apex']['player']['y'], self.S06_V3_FALL_POINTS[k][1]+1)
            v['declared_fall_point'] = self.S06_V3_FALL_POINTS[k]
        self.evidence.write('falls/result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S06 fall point is exercised from the labeled real S05 v3 exit pose. S06-01-short: the carriage released at 40 '
                 'drops from the exit-pocket mouth through S06-fall-drag onto the green catch ledge, rebounds to at most half the drop (never '
                 'back to the release height) and settles. S06-02-missed: with no lift press the rising flight off the skid passes under the '
                 'canopy into the left map edge, drops along '
                 'it through S04-fall-drag onto the green S04 catch basin, rebounds to at most half the drop and settles'))
        for k, v in out.items():
            print('PASS fall', k, ': apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on',
                  v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
                  '; settled from tick', v['settled_from_tick'])


class LiftworksV3CompleteChecks(LiftworksV3Checks):
    """Layout-v3 Liftworks S06-03/04, section exit and fall recovery (TASK-521), with real input.

    Same labeled-placement proof as LiftworksV3Checks: the start is the real S05 v3 exit settled pose (the v3 S05 route
    run from the labeled real S04 v3 exit pose of one base-start real-input S01..S04 v3 run). S06-03/04 continue the
    S06-01/02 inputs of the same run, so they are segmented from the S06-02 exit (tick 298) and the S06-03 exit (tick
    628), not placed. Not a continuous-completion claim. Shared by Task521Tests (the inherited S06-01/02 cases also run).
    """
    # Exact world points of the desktop press pixels (280,136) and (662,229).
    CLIMB_V3, EXIT_HOOK_V3 = (1120,-10451.36692242505), (2648,-11507.094769107767)
    CLIMB_PRESS, CLIMB_RELEASE, EXIT_PRESS, EXIT_RELEASE = 319, 494, 628, 718
    # S06-03: after the canopy drop the player hits the left map edge (tick 318) and slides down it; the green climb
    # hook (up-right, above the canopy) is pressed at 319. The swing runs down and east, grazes the bounce-only green
    # swing skid at its lowest point, climbs past the canopy's east end and is released at the top of the upswing
    # (494), which leaves a straight rise between the S04 baffle and the exit pocket. S06-04: the green exit hook, far
    # east above the S05 deflector apex, is pressed near the top of the rise (628) and held 90; the pull carries the
    # player east into S06-exit-drag (under the S04 exit ledge), where it is released, and it settles on the green
    # exit ledge (the section exit).
    S06_03_V3 = [(CLIMB_PRESS,'mousedown',*CLIMB_V3),(CLIMB_RELEASE,'mouseup',*CLIMB_V3)]
    S06_04_V3 = [(EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),(EXIT_RELEASE,'mouseup',*EXIT_HOOK_V3)]
    S06_ROUTE_V3 = LiftworksV3Checks.S06_01_V3+LiftworksV3Checks.S06_02_V3+S06_03_V3+S06_04_V3
    S06_03_TICKS, S06_04_TICKS, S06_FULL_TICKS, S06_LAND_BY = 628, 1150, 1300, 830
    S06_03_EXIT = dict(x=[1180,1280], y=[-11330,-11230], speedX=[-.1,.1], speedY=[-.9,-.5])
    S06_04_EXIT = dict(x=[1450,1850], y=[-11300,-11250], speedX=[-.001,.001], speedY=[-.2,.2])
    S06_EXIT_DRAG = dict(left=1450, right=1850, top=-11570, bottom=-11250)
    S06_DROP_DRAG = dict(left=1150, right=1310, top=-9400, bottom=-9080)
    DROP_SETTLE = dict(x=[1150,1310], y=[-9110,-9080], speedX=[-.001,.001], speedY=[-.2,.2])
    S04_BAFFLE = dict(left=1100, right=1130, top=-11150, bottom=-10750)
    S04_EXIT_LEDGE = dict(left=1350, right=1740, top=-11650, bottom=-11620)
    # Mistimed S06-04 (fall.json): the exit hook is tapped (pressed at 628, released at 633, before the throw catches
    # at 635), so the rise tops out and the player falls straight back down it through S06-drop-drag onto the green
    # drop ledge and settles (by ~1700). Input-only rejoin from 1800: the climb hook again (aimed at its east end,
    # past the canopy's east end) held 180 throws the player back up the rise, and the exit hook pressed near its top
    # (2022, held 90) carries it into the exit pocket.
    TAP_RELEASE, REJOIN_TICK = 633, 1800
    CLIMB_EAST = (1144,-10446.145938580066)
    REJOIN_S06 = [(1800,'mousedown',*CLIMB_EAST),(1980,'mouseup',*CLIMB_EAST),
                  (2022,'mousedown',*EXIT_HOOK_V3),(2112,'mouseup',*EXIT_HOOK_V3)]
    REJOIN_EXIT_PRESS = 2022
    S06_04_TAPPED = LiftworksV3Checks.S06_01_V3+LiftworksV3Checks.S06_02_V3+S06_03_V3+[(EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),
                     (TAP_RELEASE,'mouseup',*EXIT_HOOK_V3)]
    FALL_S06, FALL_S06_TICKS = S06_04_TAPPED+REJOIN_S06, 2700
    # Declared S06-03/04 misses: no climb-hook press (the map-edge slide continues through S04-fall-drag onto the
    # green S04 catch basin); no exit-hook press (the rise falls back through S06-drop-drag onto the green drop
    # ledge); an exit hook released 28 ticks early (still inside S06-exit-drag, onto the green exit ledge).
    S06_03_MISSED = LiftworksV3Checks.S06_01_V3+LiftworksV3Checks.S06_02_V3
    S06_04_MISSED = S06_03_MISSED+S06_03_V3
    S06_04_EARLY = S06_04_MISSED+[(EXIT_PRESS,'mousedown',*EXIT_HOOK_V3),(EXIT_RELEASE-28,'mouseup',*EXIT_HOOK_V3)]

    def no_legacy_contact(self, trace):
        """No contact point lies on legacy gray geometry (S07/S08) or on a v1 S06 piece kept green in place."""
        m = self.report()['manifest']
        legacy = {e['id']:self.bounds_v3(e) for e in m['geometry']['elements']
                  if e['id'].split('-')[0] in ('S07','S08') or e['id'] in V1_S06_DISPOSITION}
        hits = sorted({k for e in self.contacts(trace) for k, b in legacy.items()
                       if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1})
        self.assertEqual(hits, [])
        return dict(legacy_contact_points=hits, contact_events=len(self.contacts(trace)))

    def s06_03_checks(self, trace, players, mech):
        self.assertTrue(self.inside(players[self.S06_02_TICKS], self.S06_02_EXIT), players[self.S06_02_TICKS])
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 0 and e['tick'] > self.LIFT_RELEASE]
        self.assertTrue(edge and edge[0] < self.CLIMB_PRESS, edge)
        press = players[self.CLIMB_PRESS]
        # Pressed sliding down the left map edge.
        self.assertTrue(press['x'] < 11 and press['speedY'] > 1 and press['speedX'] == 0, press)
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S06-climb-hook')
        skid, before, after = self.bounce_s05(trace, 'S06-swing-skid')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S06-climb-hook')
        self.assertTrue(self.CLIMB_PRESS < acq['tick'] < skid['tick'] < release['tick'] == self.CLIMB_RELEASE)
        # The skid only grazes the lowest point of the swing: the eastward speed is kept, the small descent is turned.
        self.assertTrue(0 < before['speedY'] < .5 and after['speedY'] < 0 and before['speedX'] > 1, (before, after))
        self.assertAlmostEqual(after['speedX'], before['speedX'], delta=1e-6)
        rel = players[self.CLIMB_RELEASE]
        self.assertTrue(abs(rel['speedX']) < .05 and rel['speedY'] < -1.5, rel)
        # The straight rise: no contact from the release to the exit-hook press, clear of the S04 baffle and of the
        # exit pocket (and its drag zone).
        rise = range(self.CLIMB_RELEASE, self.S06_03_TICKS+1)
        self.assertFalse([e for e in self.contacts(trace) if self.CLIMB_RELEASE <= e['tick'] <= self.S06_03_TICKS])
        baffle = min(self.box_gap(self.S04_BAFFLE, players[t]['x'], players[t]['y']) for t in rise) - press['radius']
        pocket = min(self.box_gap(self.S06_EXIT_DRAG, players[t]['x'], players[t]['y']) for t in rise) - press['radius']
        self.assertGreater(baffle, 50); self.assertGreater(pocket, 100)
        self.assertTrue(self.inside(players[self.S06_03_TICKS], self.S06_03_EXIT), players[self.S06_03_TICKS])
        reach = self.reach_s05(players, mech, self.CLIMB_PRESS, 'S06-climb-hook')
        return dict(climb_acquisition_reach=reach, map_edge_contact_tick=edge[0], press_on_map_edge=press,
            swing_skid_bounce=dict(tick=skid['tick'], before=before, after=after),
            climb_release=dict(tick=self.CLIMB_RELEASE, player=rel),
            rise=dict(ticks=[self.CLIMB_RELEASE, self.S06_03_TICKS], contacts=[], min_clearance_to_s04_baffle=baffle,
                      min_clearance_to_s06_exit_drag=pocket))

    def s06_04_checks(self, trace, players, mech, press=None, ticks=None):
        """Exit-hook pull into S06-exit-drag, release there, exit ledge landing and settle (the section exit)."""
        press = press or self.EXIT_PRESS
        ticks = ticks or len(players)-1
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S06-exit-hook' and e['tick'] >= press)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S06-exit-hook' and e['tick'] > acq['tick'])
        # The rope runs straight to the exit hook (above the S05 deflector apex) and nothing is touched on it.
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][acq['tick']:release['tick']+1]))
        self.assertFalse([e for e in self.contacts(trace) if acq['tick'] <= e['tick'] <= release['tick']])
        entry = next(t for t in range(acq['tick'], ticks+1) if self.in_box(players[t], self.S06_EXIT_DRAG))
        self.assertLessEqual(entry, release['tick'])
        self.assertTrue(all(self.in_box(players[t], self.S06_EXIT_DRAG) for t in range(entry, ticks+1)))
        before = players[entry-1]
        self.assertGreater(before['speedX'], .5)
        # Entered from the west side, above the exit ledge and below the S04 exit ledge.
        self.assertLess(before['x'], self.S06_EXIT_DRAG['left'])
        top = min(players[t]['y'] - players[t]['radius'] for t in range(acq['tick'], ticks+1))
        self.assertGreater(top, self.S04_EXIT_LEDGE['bottom'] + 30)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(release['tick'], release['tick']+6) if abs(players[t]['speedX']) > 1e-9]
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S06-exit-ledge' and e['tick'] > release['tick']]
        self.assertTrue(ledge)
        land = ledge[0]
        settle = next(t for t in range(land['tick'], ticks+1) if all(self.inside(players[u], self.S06_04_EXIT) for u in range(t, ticks+1)))
        tail = players[settle:ticks+1]
        reach = self.reach_s05(players, mech, press, 'S06-exit-hook') if press == self.EXIT_PRESS else None
        return dict(exit_hook_acquisition_reach=reach, exit_hook_acquisition_tick=acq['tick'],
            exit_hook_release=dict(tick=release['tick'], player=release['player']),
            exit_drag_entry=dict(tick=entry, before=before, at_entry=players[entry]), per_tick_vx_ratio_after_release=ratios,
            min_player_top_y=top, s04_exit_ledge_underside=self.S04_EXIT_LEDGE['bottom'],
            exit_ledge_landing=dict(tick=land['tick'], player=land['player']), ledge_bounces=len(ledge),
            section_exit=dict(element='S06-exit-ledge', drag_zone='S06-exit-drag', settle_tick=settle, settled_ticks=len(tail),
                settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[ticks], settle_box=self.S06_04_EXIT, inside_exit_drag=True))

    def test_06_s06_03_nominal(self):
        plan = self.S06_01_V3+self.S06_02_V3+self.S06_03_V3
        trace, players, mech, result = self.run_s06('S06-03', plan, self.S06_03_TICKS, self.S06_03_EXIT)
        self.assertEqual(self.s06_kinds(mech)[6:], [('acquisition','S06-climb-hook'),('bounce','S06-swing-skid'),('release','S06-climb-hook')])
        out = self.s06_03_checks(trace, players, mech)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S06-03', segmented_from='S06-02 exit at tick 298 of the same run (no further placement)',
            s06_02_exit_at_tick_298=players[self.S06_02_TICKS], exit_judged_at_tick=self.S06_03_TICKS, contacts=touched, **out)
        self.evidence.write('encounters/S06-03/result.json', result)
        r, sk = out['climb_acquisition_reach'], out['swing_skid_bounce']
        print('PASS S06-03: from the S06-02 exit at tick 298; map edge at tick', out['map_edge_contact_tick'], '; green climb-hook acquisition',
              round(r['distance'],1), 'at tick', r['acquisition_tick'], 'sliding down the edge; green swing skid bounce tick', sk['tick'], 'vy',
              round(sk['before']['speedY'],3), '->', round(sk['after']['speedY'],3), '; release', self.CLIMB_RELEASE, 'v',
              (round(out['climb_release']['player']['speedX'],3), round(out['climb_release']['player']['speedY'],3)), '; rise clear of the S04 baffle',
              round(out['rise']['min_clearance_to_s04_baffle'],1), '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_07_s06_04_nominal(self):
        trace, players, mech, result = self.run_s06('S06-04', self.S06_ROUTE_V3, self.S06_04_TICKS, self.S06_04_EXIT,
                                                    density_until=self.S06_LAND_BY)
        self.assertTrue(self.inside(players[self.S06_03_TICKS], self.S06_03_EXIT), players[self.S06_03_TICKS])
        self.assertEqual(self.s06_kinds(mech)[9:12], [('acquisition','S06-exit-hook'),('release','S06-exit-hook'),('bounce','S06-exit-ledge')])
        out = self.s06_04_checks(trace, players, mech)
        self.assertLessEqual(out['exit_ledge_landing']['tick'], self.S06_LAND_BY)
        touched = self.no_legacy_contact(trace)
        result.update(encounter='S06-04', segmented_from='S06-03 exit (the rise) at tick 628 of the same run (no further placement)',
            s06_03_exit_at_tick_628=players[self.S06_03_TICKS], contacts=touched, **out)
        self.evidence.write('encounters/S06-04/result.json', result)
        r = out['exit_hook_acquisition_reach']
        print('PASS S06-04: from the rise at tick 628; green exit-hook acquisition', round(r['distance'],1), 'at tick', r['acquisition_tick'],
              '; enters S06-exit-drag at tick', out['exit_drag_entry']['tick'], '; release', out['exit_hook_release']['tick'], 'vx ratio',
              [round(x,3) for x in out['per_tick_vx_ratio_after_release'][:3]], '; highest player top', round(out['min_player_top_y'],1),
              '(S04 exit ledge underside -11620); green exit ledge landing tick', out['exit_ledge_landing']['tick'], '; settled from tick',
              out['section_exit']['settle_tick'], 'at', {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')},
              '; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], 'until tick', self.S06_LAND_BY, '; identical replay; trusted input')

    def test_08_full_traversal(self):
        trace, players, mech, result = self.run_s06('S06-full', self.S06_ROUTE_V3, self.S06_FULL_TICKS, self.S06_04_EXIT,
                                                    density_until=self.S06_LAND_BY)
        self.assertEqual([e['element'] for e in mech if e['type']=='acquisition'],
                         ['S06-carriage','S06-lift','S06-climb-hook','S06-exit-hook'])
        self.assertEqual([e['element'] for e in mech if e['type']=='bounce' and e['element'] != 'S05-exit-ledge'][:5],
                         ['S06-skid','S06-canopy','S06-swing-skid','S06-exit-ledge','S06-exit-ledge'])
        exits = {}
        for name, tick, bounds in (('S06-01',self.S06_01_TICKS,self.S06_01_EXIT),('S06-02',self.S06_02_TICKS,self.S06_02_EXIT),
                                   ('S06-03',self.S06_03_TICKS,self.S06_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        s3 = self.s06_03_checks(trace, players, mech)
        s4 = self.s06_04_checks(trace, players, mech)
        exits['S06-04'] = dict(tick=s4['section_exit']['settle_tick'], player=players[s4['section_exit']['settle_tick']], box=self.S06_04_EXIT)
        touched = self.no_legacy_contact(trace)
        reaches = [self.reach_s05(players, mech, t, el) for t, el in ((5,'S06-carriage'),(self.LIFT_PRESS,'S06-lift'),
                   (self.CLIMB_PRESS,'S06-climb-hook'),(self.EXIT_PRESS,'S06-exit-hook'))]
        result.update(encounter='S06 full traversal', encounter_exits=exits, s06_03=s3, s06_04=s4, section_exit=s4['section_exit'],
            section_exit_reached=True, settled_at_section_exit=True, contacts=touched, reaches=reaches)
        self.evidence.write('encounters/S06-full/result.json', result)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules.setdefault('trace_measured_reach', {}).update({x['element']:x for x in reaches})
            self.evidence.write('rules.json', rules)
        print('PASS full S06: from the real S05 v3 exit pose; exits', {k:v['tick'] for k, v in exits.items()}, '; reaches',
              [round(x['distance'],1) for x in reaches], '; exit ledge landing tick', s4['exit_ledge_landing']['tick'], '; settled from tick',
              s4['section_exit']['settle_tick'], 'for', s4['section_exit']['settled_ticks'], 'ticks at',
              {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')}, 'inside S06-exit-drag; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_09_fall_through_drag_and_rejoin(self):
        trace, players, mech, result = self.run_s06('S06-04-tapped', self.FALL_S06, self.FALL_S06_TICKS, self.S06_04_EXIT,
                                                    density_until=self.EXIT_PRESS, folder='falls')
        # The tap is released before the throw reaches the exit hook: no acquisition at all between the press and the rejoin.
        self.assertFalse([e for e in mech if e['type']=='acquisition' and self.EXIT_PRESS <= e['tick'] < self.REJOIN_TICK])
        tap = [e for e in trace['events'] if e['type']=='input' and e['tick'] in (self.EXIT_PRESS, self.TAP_RELEASE)]
        self.assertEqual([e['event'] for e in tap], ['mousedown','mouseup'])
        rel = players[self.TAP_RELEASE]
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S06-drop-ledge' and self.TAP_RELEASE < e['tick'] < self.REJOIN_TICK]
        self.assertTrue(ledge)
        land = ledge[0]['tick']
        # Nothing but the drop ledge is touched between the tap and the rejoin.
        self.assertFalse([e for e in mech if self.TAP_RELEASE < e['tick'] < self.REJOIN_TICK and e['element'] != 'S06-drop-ledge'])
        self.assertFalse([e for e in self.contacts(trace) if self.TAP_RELEASE < e['tick'] < self.REJOIN_TICK
                          and not (1150 <= e['contact']['x'] <= 1310 and abs(e['contact']['y'] + 9080) < 2)])
        apex_tick = min(range(self.TAP_RELEASE, land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        drag = self.S06_DROP_DRAG
        ticks = [t for t in range(apex_tick, land+1) if self.in_box(players[t], drag)]
        entry, leave = ticks[0], ticks[-1]
        self.assertEqual(ticks, list(range(entry, land+1)))
        before, inside_last = players[entry-1], players[leave]
        self.assertFalse(self.in_box(before, drag)); self.assertGreater(before['speedY'], 1)
        vdamp = [players[t+1]['speedY']-players[t]['speedY']*.985 for t in range(entry, leave)][:8]
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_ledge = contact['before']['simulation']['player']
        self.assertLess(at_ledge['speedY'], before['speedY'])
        self.assertLessEqual(abs(at_ledge['speedX']), abs(before['speedX']))
        rest_y = ledge[0]['player']['y']
        fall_height = rest_y - apex['y']
        self.assertGreater(fall_height, 2000)
        # The declared S06-04-missed column: the drop crosses its height within the column radius.
        fx, fy = self.S06_V3_FALL_POINTS['S06-04-missed']
        self.assertLessEqual(apex['y'], fy+1)
        cross = next(t for t in range(apex_tick, land) if players[t]['y'] >= fy)
        self.assertLessEqual(abs(players[cross]['x']-fx), 18)
        peaks = []
        for a, b in zip(ledge, ledge[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(p['peak_y'] > rel['y'] for p in peaks))
        # Settled on the green drop ledge inside S06-drop-drag before the rejoin press.
        window = players[self.REJOIN_TICK-100:self.REJOIN_TICK]
        self.assertTrue(all(self.inside(p, self.DROP_SETTLE) and self.in_box(p, drag) for p in window))
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_TICK]
        self.assertEqual(len(rejoin_inputs), len(self.REJOIN_S06))
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after_rejoin = [e for e in mech if e['tick'] >= self.REJOIN_TICK]
        self.assertEqual([e['element'] for e in after_rejoin if e['type']=='acquisition'], ['S06-climb-hook','S06-exit-hook'])
        s4 = self.s06_04_checks(trace, players, mech, press=self.REJOIN_EXIT_PRESS)
        fall = dict(scenario='naturally mistimed S06-04 release: the green exit hook is tapped (pressed at tick %d, released at tick %d, '
                             'before the throw reaches the hook) instead of held 90 ticks; the rise tops out and the player falls physically; '
                             'no relocation after the labeled S05 v3 exit start placement' % (self.EXIT_PRESS, self.TAP_RELEASE),
            release=dict(tick=self.TAP_RELEASE, element='S06-exit-hook (throw still in flight, never acquired)', press_tick=self.EXIT_PRESS,
                         nominal_release_tick=self.EXIT_RELEASE, player=rel, release_height_y=rel['y']),
            fall_point=dict(id='S06-04-missed', declared_x=fx, declared_y=fy, apex_x=apex['x'], crossing=dict(tick=cross, player=players[cross]),
                            landing_x=at_ledge['x']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='drop ledge bounce rest y minus the apex y after the release',
            drag_zone=dict(id='S06-drop-drag', box=drag, entry_tick=entry, last_tick_inside_before_landing=leave,
                before=dict(tick=entry-1, x=before['x'], y=before['y'], speedX=before['speedX'], speedY=before['speedY']),
                after=dict(tick=land, x=at_ledge['x'], y=at_ledge['y'], speedX=at_ledge['speedX'], speedY=at_ledge['speedY'],
                           note='player state just before the drop ledge bounce, after crossing the drag zone'),
                vertical_damping_per_tick=0.985, vy_minus_damped_previous_vy_first_ticks=vdamp,
                horizontal_note='the drop is straight (|vx| < 0.01 before the zone); the zone multiplies vx by 0.8 per tick'),
            bouncer=dict(element='S06-drop-ledge', route='S06 drop ledge under the S06-03 rise (the S06-04 miss catch; the S06-03 climb hook '
                         'is in reach from it)', first_bounce_tick=land, rest_y=rest_y, inside='S06-drop-drag'),
            s05_route_bouncer_deviation='the ticket asks for a landing on S05 route bouncers; S06-03/04 sit at the west map edge, more than '
                'a band below and 2000+ west of any S05 bouncer with a drag zone (the S05 exit ledge at x 6100, the catch deck at x 3800), '
                'so the S06-03/04 misses settle on S06 green catches; see review.md',
            bounce_peaks=peaks[:8], bounce_count=len(peaks), first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            never_back_to_release_height=True,
            settled=dict(window=[self.REJOIN_TICK-100, self.REJOIN_TICK-1], box=self.DROP_SETTLE,
                max_abs_speedX=max(abs(p['speedX']) for p in window), max_abs_speedY=max(abs(p['speedY']) for p in window),
                y_range=[min(p['y'] for p in window), max(p['y'] for p in window)], inside_drag_zone='S06-drop-drag', on='S06-drop-ledge'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                start_tick=self.REJOIN_TICK, mover_periods_after_start=self.REJOIN_TICK//240,
                mechanics=[{k:e[k] for k in ('tick','type','element','player')} for e in after_rejoin
                           if e['type'] != 'contact' and e['element'] != 'S06-drop-ledge'],
                s06_04=s4, final=players[-1], encounter_rejoined='S06-03 (climb hook from the drop ledge) through the S06 exit ledge',
                exit_box=self.S06_04_EXIT))
        result.update(fall)
        self.evidence.write('falls/S06-04-tapped/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: exit hook tapped', self.EXIT_PRESS, '->', self.TAP_RELEASE, 'at y', round(rel['y'],1), '; apex', round(apex['y'],1),
              '; S06-drop-drag vx/vy', round(before['speedX'],4), round(before['speedY'],3), '->', round(at_ledge['speedX'],6),
              round(at_ledge['speedY'],3), '; drop ledge bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of',
              round(fall_height,1), '; settled at x', round(window[-1]['x'],1), '; input-only rejoin from tick', self.REJOIN_TICK,
              ': acquisitions', [e['element'] for e in after_rejoin if e['type']=='acquisition'],
              '; settled on the S06 exit ledge from tick', s4['section_exit']['settle_tick'])
        # The declared S06-03/04 fall points, each from the same labeled start.
        out = {}
        trace, players, mech, result = self.run_s06('S06-03-missed', self.S06_03_MISSED, 2000, self.BASIN_SETTLE,
                                                    density_until=self.S06_02_TICKS, folder='falls')
        self.assertNotIn('S06-climb-hook', [e['element'] for e in mech if e['type']=='acquisition'])
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 0]
        self.assertTrue(edge)
        out['S06-03-missed'] = self.fall_s03(trace, players, mech, self.LIFT_RELEASE, 'S04-catch-basin', self.S04_FALL_DRAG, self.BASIN_SETTLE)
        out['S06-03-missed']['left_map_edge_first_contact'] = dict(tick=edge[0], player=players[edge[0]])
        self.assertLessEqual(players[edge[0]]['y'], self.S06_V3_FALL_POINTS['S06-03-missed'][1]+20)
        trace, players, mech, result = self.run_s06('S06-04-missed', self.S06_04_MISSED, 2000, self.DROP_SETTLE,
                                                    density_until=self.S06_03_TICKS-120, folder='falls')
        self.assertNotIn('S06-exit-hook', [e['element'] for e in mech if e['type']=='acquisition'])
        out['S06-04-missed'] = self.fall_s03(trace, players, mech, self.CLIMB_RELEASE, 'S06-drop-ledge', self.S06_DROP_DRAG, self.DROP_SETTLE)
        trace, players, mech, result = self.run_s06('S06-04-early', self.S06_04_EARLY, self.S06_04_TICKS, self.S06_04_EXIT,
                                                    density_until=self.S06_LAND_BY, folder='falls')
        out['S06-04-early'] = self.fall_s03(trace, players, mech, self.EXIT_RELEASE-28, 'S06-exit-ledge', self.S06_EXIT_DRAG, self.S06_04_EXIT)
        for k, v in out.items():
            # Every drop starts at its apex on (or above) the declared fall point.
            self.assertLessEqual(v['apex']['player']['y'], self.S06_V3_FALL_POINTS[k][1]+1)
            v['declared_fall_point'] = self.S06_V3_FALL_POINTS[k]
        self.evidence.write('falls/s06_03_04_result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S06-03/04 fall point is exercised from the labeled real S05 v3 exit pose; the player crosses the drag zone, '
                 'lands on the green bouncer, rebounds to at most half the drop (never back to the release height) and settles'))
        for k, v in out.items():
            print('PASS fall', k, ': apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'],
                  '; lands on', v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
                  '; settled from tick', v['settled_from_tick'])


class LiftworksV3ToleranceChecks(GalleriesV3ToleranceChecks):
    """Layout-v3 Liftworks (S06) tolerance on desktop 1280x720 and touch 844x390 (TASK-522).

    Proof kind (as TASK-520/521): the real S05 v3 exit settled pose (the v3 S05 route run from the labeled
    real S04 v3 exit pose of one base-start real-input S01..S04 v3 run, TASK-518 S05-full) is restored once
    as a labeled initial placement (initial_snapshot); production trusted mouse/touch input and physics run
    from there. An attempt on encounter k replays the S06 route up to k: the encounter's inputs carry the
    variant, the earlier encounters keep their TASK-520/521 nominal inputs. S06-01..03 end in flight, so
    they are judged at their mountain.js exit boxes (position at the nominal exit tick 204/298/628); S06-04
    at the S06 section exit (settled on the green exit ledge inside S06-exit-drag at tick 1150).
    check_s06_v3_mechanics requires the encounter's own mechanic, the S06 anchors in route order and no
    fall onto an S01-S05 element or an S06 fall bouncer. The HUD probe reads the UI boxes the game draws
    (LAYOUT_PROBE) at every nominal press. No earlier Task522Tests exists (the layout-v2 S06 tolerance was
    never built), so there is no v2 suite to map.
    """
    LC, LX = LiftworksV3Checks, LiftworksV3CompleteChecks
    GV, GC = GalleriesV3Checks, GalleriesV3CompleteChecks
    SEGMENTS = [LC.S06_01_V3, LC.S06_02_V3, LX.S06_03_V3, LX.S06_04_V3]
    V3_ENCOUNTERS = [('S06-01','blue carriage pulled left out of S05-exit-drag, release into a dive that the bounce-only green skid turns into a rising flight west',0,LC.S06_01_TICKS),
                     ('S06-02','blue lift caught in flight on the rising flight, release into the green canopy (rise turned into a drop)',LC.S06_01_TICKS,LC.S06_02_TICKS),
                     ('S06-03','green climb hook caught sliding down the left map edge, swing grazing the green swing skid, release at the top of the upswing into a straight rise',LC.S06_02_TICKS,LX.S06_03_TICKS),
                     ('S06-04','green exit hook caught near the top of the rise, release in S06-exit-drag, settle on the green exit ledge (S06 section exit)',LX.S06_03_TICKS,None)]
    S06_TICKS = LX.S06_04_TICKS
    STRICT = {'S06-01':LC.S06_01_EXIT, 'S06-02':LC.S06_02_EXIT, 'S06-03':LX.S06_03_EXIT}
    # Mistimed releases, one per encounter, no further input afterwards: (encounter, release tick replacing the
    # nominal one, nominal release tick, ticks, declared fall point or None, landing bouncer).
    MISTIMED = [('S06-01',40,125,1100,'S06-01-short','S06-catch-ledge'), ('S06-02',300,258,2000,None,'S04-catch-basin'),
                ('S06-03',520,494,2000,None,'S04-catch-basin'), ('S06-04',690,718,1150,'S06-04-early','S06-exit-ledge')]
    UNDECLARED = {'S06-02':'undeclared S06-02 line: the lift held 42 ticks too long keeps the canopy drop, slides down the left map '
                           'edge (the S06-02-missed column) through S04-fall-drag onto the green S04 catch basin',
                  'S06-03':'undeclared S06-03 line: the climb hook held 26 ticks too long, the release flight drops back to the left '
                           'map edge and down it (the S06-03-missed column) through S04-fall-drag onto the green S04 catch basin'}
    V3_MOVERS = LC.S06_V3_MOVERS
    ANCHOR_IDS = {'S06-01':'S06-carriage','S06-02':'S06-lift','S06-03':'S06-climb-hook','S06-04':'S06-exit-hook'}
    HUD_FINDING = ('No HUD obstruction found: every S06 anchor is drawn clear of the HUD text rows and the pause button at its '
                   'press on both viewports (no S06 geometry moved for the HUD).')
    S05_V3_SETTLE, S05_EXIT_DRAG = LC.S05_V3_SETTLE, LC.S05_EXIT_DRAG
    S06_V3_ROUTE_ELEMENTS, S06_V3_ROUTE_ELEMENTS_34 = LC.S06_V3_ROUTE_ELEMENTS, LC.S06_V3_ROUTE_ELEMENTS_34
    S06_PLAYER_CLEARANCE = LC.S06_PLAYER_CLEARANCE
    s05_v3_exit = LC.s05_v3_exit
    box_gap = staticmethod(LC.box_gap)

    def exits(self):
        """Per encounter: (ticks, judged exit bounds, meaning), from the runtime manifest."""
        enc = {e['id']:e for e in self.report()['manifest']['encounters'][20:24]}
        out = {}
        for name, _, _, tick in self.V3_ENCOUNTERS:
            if tick:
                b = enc[name]['exit']
                out[name] = (tick, dict(x=[b['left'],b['right']], y=[b['top'],b['bottom']]),
                             f'inside the mountain.js {name} exit box at the nominal exit tick {tick}')
            else:
                out[name] = (self.S06_TICKS, self.LX.S06_04_EXIT,
                             'settled on S06-exit-ledge inside S06-exit-drag (S06 section exit) at tick %d' % self.S06_TICKS)
        return out

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s06_v3_mechanics
        start = self.s05_v3_exit()
        self.assertTrue(self.inside(start['player'], self.S05_V3_SETTLE), start['player'])
        exits = self.exits()
        source = hashes()
        suite = dict(section='S06', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='isolated: one labeled initial placement (initial_snapshot) = the real S05 v3 exit settled pose (the v3 S05 route '
                       'run from the labeled real S04 v3 exit pose of a base-start real-input S01..S04 v3 run; encounters/S04-exit-start, '
                       'encounters/S05-exit-start), then production trusted mouse/touch input and physics; an attempt on encounter k '
                       'carries the variant on k and the TASK-520/521 nominal inputs on S06-01..k-1',
            initial_placement=type(self).v3_s05_start_proof, browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exits={n: dict(ticks=t, box=b, meaning=w) for n, (t, b, w) in exits.items()},
            mechanics_check='tools/grapple_over_verify.py check_s06_v3_mechanics',
            nominal_note='every nominal press aims at its anchor at the exact world point of its desktop press pixel (TASK-520/521), so '
                         'desktop and touch run the same route; every anchor is drawn clear of the HUD text and the pause button at '
                         'its press (hud-probe.json)',
            pause_button_client_rects={str(k): v for k, v in self.PAUSE_BUTTON.items()},
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            hud_probe='hud-probe.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal, clips = [], {}, {}
        for k, (name, mechanic, begin, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            ticks, bounds, meaning = exits[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), ticks, bounds, device, snapshot=start)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s06_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s06_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(self.clear(targets), (label, targets))
                        if exit_tick:
                            self.assertTrue(self.inside(players[exit_tick], self.STRICT[name]), (label, players[exit_tick]))
                            end = exit_tick
                        else:
                            end = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S06-exit-ledge')
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', begin, end)
                        clips[label] = (trace, m['metadata']['viewport'], prefix, mechanics)
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning),
                        outcome=f'{name} exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(artifacts/TASK-544/calibration.json density_cap.frozen_ticks = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','mover contact (S06-carriage/S06-lift are only rope anchors; no player contact with them occurs)'],
            cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal S06 run (0/204/298/628) to its manifest exit tick '
                   '(204/298/628) or, for S06-04, the exit-ledge landing; the settle on the exit ledge is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(start, exits['S06-04'])
        self.hud_probe(clips)
        self.assertEqual(failures, [])
        print('PASS S06 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-exit-hook negative control fails the exit')

    def negative_control(self, start, exit):
        from grapple_over_verify import hashes, check_s06_v3_mechanics
        # Named omission: the S06-04 exit-hook press/release left out; same placement, physics and
        # S06-01..03 inputs as every S06-04 attempt.
        ticks, bounds, meaning = exit
        plan = self.variant_plan(3)[:6]
        m = self.make_input(plan, ticks, bounds, snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s06_v3_mechanics('S06-04', trace, required=False)
        landed = [b for b in mechanics['bounces'] if b['tick'] > self.LX.CLIMB_RELEASE]
        self.evidence.write('negative-control.json', dict(name='omitted exit hook: S06-04 S06-exit-hook press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning), unchanged_physics=True, source_hashes=hashes(),
            proof_kind='same labeled S05-exit placement, real mouse input, same S06-01..03 inputs as the S06-04 attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step, bounces_after_climb_release=landed,
            exit_ledge_contact='S06-exit-ledge' in [b['element'] for b in mechanics['bounces']], final_player=players[-1],
            scope='Without the exit-hook pull the straight rise off the climb hook tops out and falls back down it '
                  '(first bouncer %s) and the S06 section exit is missed.' % (landed[0]['element'] if landed else 'none')))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S06-exit-hook', mechanics['acquisitions'])
        self.assertNotIn('S06-exit-ledge', [b['element'] for b in mechanics['bounces']])
        self.assertFalse(self.inside(players[-1], self.LX.S06_04_EXIT))
        self.assertLess(step, 60)
        print('PASS negative control: omitted exit hook; reason', reason[:80], '; bounces after the climb release',
              [(b['element'], b['tick']) for b in landed][:4], '; final', (round(players[-1]['x'],1), round(players[-1]['y'],1)))

    FALL_SECTION_INDEX, FALL_ZONE_PREFIXES = 5, ('S01-','S02-','S03-','S04-','S05-','S06-')
    FALL_PROOF = 'labeled S05-exit placement, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation'

    def fall_start(self):
        return self.s05_v3_exit()

    def section_mechanics(self, name, trace, required=True):
        from grapple_over_verify import check_s06_v3_mechanics
        return check_s06_v3_mechanics(name, trace, required)


V1_S07_REVISION = 'bd8ab07'
# What happened to every static v1 S07 solid and v1 S07 mover in the layout-v3 rebuild (TASK-523).
V1_S07_DISPOSITION = {
    'S07-service-gantry':('deleted','v1 S07-01 gray gantry beside the red rotor; the v3 S07-01 pulls the blue trolley out of the S06 exit pocket'),
    'S07-rest-ledge':('deleted','v1 S07-02 vent-plinth rest pad; layout v3 has no rest pads'),
    'S07-shortcut-jib':('deleted','v1 S07-02 shortcut jib; the S07-01 -> S07-04 shortcut is kept planned until S07-03/04 are rebuilt'),
    'S07-launch-head':('deleted','v1 S07-03 launch head; S07-03/04 are planned again (TASK-523)'),
    'S07-roof-boom':('converted-to-bounce','v1 S07-03 boom; was a v1 Summit Array recovery opening collider (that S08 is deleted by TASK-526); same '
                     'place and shape, now green; no v3 route uses it'),
    'S07-upper-motor':('deleted','v1 S07-03/04 upper motor; S07-03/04 are planned again (TASK-523)'),
    'S07-recovery-balcony':('converted-to-bounce','v1 S07-04 recovery balcony; was a v1 Summit Array recovery opening collider '
                            '(that S08 is deleted by TASK-526); same place and shape, now green; no v3 route uses it'),
    'S07-side-hoist':('deleted','v1 S07-04 side hoist; S07-03/04 are planned again (TASK-523)'),
    'S07-exit':('converted-to-bounce','v1 S07 exit ledge; was the v1 S08-01 start ledge (that S08 is deleted by TASK-526); same place and '
                'shape, now green; no v3 route uses it'),
}
V1_S07_MOVER_DISPOSITION = {
    'S07-sweeper':('deleted','v1 S07-01/02 red rotor (nonlethal knockback hazard mover); the v3 S07-01/02 movers are the blue trolley and '
                   'the blue carriage, and no v3 S07 hazard exists yet, so every hazard stays nonlethal'),
}
V3_S07_ADDED = ('S07-trolley','S07-west-wall','S07-carriage','S07-crown-wall','S07-crown-ledge','S07-crown-drag',
                'S07-gable-hook','S07-exit-ledge','S07-exit-drag','S07-short-drag')


class CrownV3Checks:
    """Layout-v3 Exposed Crown opening (S07-01/02) from the real S06 v3 exit settled pose (TASK-523).

    The start pose is the real S06 exit settled pose produced by the v3 S06 build, by the chain that proves it
    (TASK-521 S06-full): one base-start real-input run of the v3 S01..S04 routes settles on the S04 exit ledge; its
    final snapshot is restored once (labeled) and the v3 S05 route runs onto the S05 exit ledge (TASK-518 S05-full);
    that snapshot is restored once (labeled) and the v3 S06 route (TASK-520/521 inputs, 1300 ticks) runs onto the
    green S06 exit ledge inside S06-exit-drag. That S06 pose is restored once as a labeled initial placement
    (initial_snapshot), then production trusted input and physics run. Not a continuous-completion claim.
    Range is 1620 (held since the S03 route climbs through the S05 band). test_01 also proves each gap is not
    crossable at 1080 geometrically (nearest point of the mover box over its whole travel from the press pose).
    S07-03/04 stay planned.
    """
    LV, LC, GV = LiftworksV3Checks, LiftworksV3CompleteChecks, GalleriesV3Checks
    # LiftworksV3Checks' S05-exit chain (with its S06 clearance proof) and the shared labeled-placement runner.
    GC, S05_V3_SETTLE, S05_EXIT_DRAG = LV.GC, LV.S05_V3_SETTLE, LV.S05_EXIT_DRAG
    S06_V3_ROUTE_ELEMENTS, S06_V3_ROUTE_ELEMENTS_34, S06_PLAYER_CLEARANCE = LV.S06_V3_ROUTE_ELEMENTS, LV.S06_V3_ROUTE_ELEMENTS_34, LV.S06_PLAYER_CLEARANCE
    s05_v3_exit = LV.s05_v3_exit
    box_gap = staticmethod(LV.box_gap)
    START_LABEL = ('the real S06 v3 exit settled pose (the v3 S06 route run from the labeled real S05 v3 exit pose, itself the v3 S05 route '
                   'run from the labeled real S04 v3 exit pose of one base-start real-input S01..S04 v3 run, as TASK-521 S06-full)')
    # Exact world points of the desktop press pixels (77,192) and (497,104).
    TROLLEY_V3, CARRIAGE_V3 = (308,-11933.25445257873), (1988,-12882.459816134844)
    # S07-01: the trolley (up-left, over the S04 route) is pressed at 5 and acquired at 52; the drag zone lets the player
    # only crawl out of the pocket's open west side; the pull then swings it west under the trolley, and released at 245
    # it ricochets off the green west wall (257) into a long flight east between the S05 canopy and the S05 hoist.
    # S07-02: the carriage press at 290 catches it in that flight (297); the swing climbs up-right over the S05 hoist and,
    # released at 322, rebounds off the green crown wall (374) above S07-crown-drag into a flight west along the top.
    S07_01_V3 = [(5,'mousedown',*TROLLEY_V3),(245,'mouseup',*TROLLEY_V3)]
    S07_02_V3 = [(290,'mousedown',*CARRIAGE_V3),(322,'mouseup',*CARRIAGE_V3)]
    TROLLEY_RELEASE, CARRIAGE_PRESS, CARRIAGE_RELEASE = 245, 290, 322
    S07_V3_MOVERS = ('S07-trolley','S07-carriage')
    S07_V3_BAND = (1378, 1458)
    S07_01_EXIT = dict(x=[700,840], y=[-12200,-12110], speedX=[2.5,2.9], speedY=[-.8,-.5])
    S07_02_EXIT = dict(x=[1600,1800], y=[-12780,-12680], speedX=[-3.6,-3.1], speedY=[-.3,.1])
    S07_01_TICKS, S07_02_TICKS = 290, 420
    S06_V3_SETTLE = LC.S06_04_EXIT
    S06_EXIT_DRAG = LC.S06_EXIT_DRAG
    # TASK-524 completes the section: S07-03/04, their fall points and drag zones are judged here too.
    S07_V3_FALLS = {'S07-01-short':(['S04-fall-drag'],'S04-catch-basin'), 'S07-02-missed':(['S07-crown-drag'],'S07-crown-ledge'),
                    'S07-03-short':(['S06-drop-drag','S07-short-drag'],'S06-drop-ledge'),
                    'S07-04-missed':(['S07-crown-drag'],'S07-crown-ledge'), 'S07-04-late':(['S07-exit-drag'],'S07-exit-ledge')}
    S07_V3_FALL_POINTS = {'S07-01-short':(30,-11560), 'S07-02-missed':(2800,-12330), 'S07-03-short':(1180,-12400),
                          'S07-04-missed':(2794,-12150), 'S07-04-late':(2560,-12150)}
    S07_V3_GAPS = ('S07-01-trolley','S07-02-carriage','S07-03-gable','S07-04-exit')
    S07_V3_ANCHORS = ('S07-trolley','S07-carriage','S07-gable-hook','S07-exit-ledge')
    S07_V3_ROUTE_ELEMENTS = ('S07-trolley','S07-west-wall','S07-carriage','S07-crown-wall','S07-crown-ledge','S07-crown-drag',
                             'S07-gable-hook','S07-exit-ledge','S07-exit-drag','S07-short-drag')
    S07_03_EXIT = dict(x=[1050,1250], y=[-12800,-12700], speedX=[2.0,2.3], speedY=[.1,.5])
    S07_04_EXIT = dict(x=[2340,2700], y=[-12010,-11960], speedX=[-.001,.001], speedY=[-.25,.25])
    WEST_WALL = dict(left=0, right=30, top=-12260, bottom=-11860)
    CROWN_WALL = dict(left=2930, right=2960, top=-12950, bottom=-11990)
    CROWN_DRAG = dict(left=2740, right=2930, top=-12530, bottom=-12020)
    CROWN_SETTLE = dict(x=[2740,2930], y=[-12050,-12020], speedX=[-.001,.001], speedY=[-.05,.05])
    S05_CANOPY = dict(left=1590, right=1680, top=-12150, bottom=-12120)
    # The S05 hoist over its whole travel.
    S05_HOIST = dict(left=2490, right=2730, top=-12470, bottom=-12440)
    S04_FALL_DRAG, BASIN_SETTLE = DeflectorV3Checks.S04_FALL_DRAG, DeflectorV3Checks.BASIN_SETTLE
    # Declared misses: a short trolley hold (released at 190) flies west onto the left map edge and slides down it through
    # S04-fall-drag onto the green S04 catch basin; no carriage press carries the S07-01 flight under the S05 hoist into
    # S07-crown-drag, which drops it onto the green crown ledge.
    S07_01_SHORT = [(5,'mousedown',*TROLLEY_V3),(190,'mouseup',*TROLLEY_V3)]
    SHORT_RELEASE = 190
    report = FoundationsV3Checks.report
    bounds_v3 = staticmethod(SwitchbackV3Checks.bounds_v3)
    inside = staticmethod(FoundationsV3CompleteChecks.inside)
    in_box = staticmethod(FoundationsV3CompleteChecks.in_box)
    fall_s03 = ViaductV3Checks.fall_s03
    run_s05, mover_contacts, reach_s05, bounce_s05 = GV.run_s05, GV.mover_contacts, GV.reach_s05, GV.bounce_s05
    S05_V3_MOVERS, S05_V3_BAND = S07_V3_MOVERS, S07_V3_BAND
    contacts = LV.contacts

    def v1_s07(self):
        """The layout-v1 S07 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V1_S07_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[6], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, encounters:m.encounters.slice(24,28), elements:m.geometry.elements.filter(e=>e.id.startsWith('S07-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S07-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S07-'))}}''', source)

    def path_segments(self, traces):
        """Player positions, attached rope segments and throw lines (press pose -> acquisition point) of compact traces."""
        players, ropes, throws = [], [], []
        for t in traces:
            snaps = t['snapshots']
            players += [s['player'] for s in snaps]
            for s in snaps[::2]:
                if s['grapple']['grappled'] and s['rope']:
                    pts = [(p['x'], p['y']) for p in s['rope']]+[(s['player']['x'], s['player']['y'])]
                    ropes += list(zip(pts, pts[1:]))
            acq = sorted((e['tick'], e['after']['rope'][0]) for e in t['events'] if e['type']=='acquisition')
            for e in t['events']:
                if e['type'] == 'input' and e['event'] == 'mousedown':
                    a = next((v for k, v in acq if k >= e['tick']), None)
                    p = snaps[e['tick']]['player']
                    if a: throws.append(((p['x'], p['y']), (a['x'], a['y'])))
        return players, ropes, throws

    def s06_v3_exit(self):
        """Real S06 v3 exit settled pose, by the chain that proves the S06 build (TASK-521 S06-full)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'v3_s06_start'): return type(self).v3_s06_start
        start5 = self.s05_v3_exit()
        m = dict(metadata=metadata('isolated'), ticks=self.LC.S06_FULL_TICKS, expected_exit=self.S06_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.LC.S06_ROUTE_V3],
            required_events=['acquisition','release','bounce'], initial_snapshot=start5)
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/S06-exit-start'
        self.evidence.write(prefix+'/input.json', m)
        run6 = execute(m, self.browser, self.url, str(self.evidence.path(prefix)))
        check_trace(m, run6)
        self.assertTrue(all(e['trusted'] for e in run6['events'] if e['type']=='input'))
        self.assertEqual(run6['metadata']['setupOnlySpawns'], [])
        players6 = [s['state']['simulation']['player'] for s in run6['snapshots']]
        acquired6 = [e['after']['rope'][0]['id'] for e in run6['events'] if e['type']=='acquisition']
        self.assertEqual(acquired6, ['S06-carriage','S06-lift','S06-climb-hook','S06-exit-hook'])
        compact6 = Task506Tests.compact(self, run6)
        self.evidence.write(prefix+'/trace.json', compact6)
        settle = next(t for t in range(self.LC.S06_LAND_BY-100, self.LC.S06_FULL_TICKS+1)
                      if all(self.inside(p, self.S06_V3_SETTLE) for p in players6[t:]))
        self.assertLessEqual(settle, self.LC.S06_FULL_TICKS-100)
        start = run6['snapshots'][-1]['state']['simulation']
        self.assertTrue(self.in_box(start['player'], self.S06_EXIT_DRAG))
        self.assertEqual((round(start['player']['x'],1), round(start['player']['y'],1)), (1543.2, -11261.3))
        self.assertIs(start['upgrades']['range'], True)
        touched = sorted({(e.get('contact') or {}).get('elementId') for e in run6['events']} - {None})
        self.assertFalse([t for t in touched if t.startswith('S07-')], touched)
        # Clearance of the whole S01..S06 v3 flight, of every rope segment while attached and of every throw line from
        # the new S07 route colliders and drag zone (movers over their whole travel).
        earlier = [json.loads(self.evidence.path(p+'/trace.json').read_text()) for p in ('encounters/S04-exit-start','encounters/S05-exit-start')]
        players, ropes, throws = self.path_segments(earlier+[compact6])
        m2 = self.report()['manifest']
        travel = {v['element']:v for v in m2['geometry']['movers']}
        boxes = {e['id']:self.bounds_v3(e, travel.get(e['id'])) for e in m2['geometry']['elements'] if e['id'] in self.S07_V3_ROUTE_ELEMENTS}
        self.assertEqual(sorted(boxes), sorted(self.S07_V3_ROUTE_ELEMENTS))
        seg = lambda b, segs, n: min(self.box_gap(b, a[0]+(c[0]-a[0])*i/n, a[1]+(c[1]-a[1])*i/n) for a, c in segs for i in range(n+1))
        clearance, rope_clearance, throw_clearance = {}, {}, {}
        for k, b in boxes.items():
            clearance[k] = min(self.box_gap(b, p['x'], p['y']) for p in players) - players[0]['radius']
            rope_clearance[k] = seg(b, ropes, 40)
            throw_clearance[k] = seg(b, throws, 200)
            self.assertGreater(clearance[k], 200, (k, clearance))
            self.assertGreater(rope_clearance[k], 20, (k, rope_clearance))
            self.assertGreater(throw_clearance[k], 20, (k, throw_clearance))
        type(self).v3_s06_start = start
        type(self).v3_s06_start_proof = dict(kind='the real S06 v3 exit settled pose: the v3 S06 route (TASK-520/521 inputs, 1300 ticks) run '
            'from ONE labeled placement of the real S05 v3 exit settled pose, which is the v3 S05 route run from ONE labeled placement of the '
            'real S04 v3 exit settled pose of one base-start real-input S01..S04 v3 run (the chain that proves the S06 build, TASK-521 S06-full)',
            s05_exit=type(self).v3_s05_start_proof, s06_inputs=m['inputs'], s06_acquisitions=acquired6, settled_in_exit_box_from_tick=settle,
            settle_box=self.S06_V3_SETTLE, final_tick=self.LC.S06_FULL_TICKS, player=start['player'], inside_S06_exit_drag=True,
            snapshot_sha256=run6['snapshots'][-1]['sha256'], full_trace_sha256=state_hash(run6), trace=prefix+'/trace.json',
            s07_element_contacts=[], s01_s06_flight_clearance_to_s07_route_elements=clearance, player_clearance_bound=200,
            s01_s06_rope_clearance_to_s07_route_elements=rope_clearance, s01_s06_throw_line_clearance_to_s07_route_elements=throw_clearance,
            throw_lines=len(throws), rope_segments=len(ropes), player_samples=len(players), range_upgraded=start['upgrades']['range'])
        self.evidence.write(prefix+'/result.json', dict(passed=True, **type(self).v3_s06_start_proof))
        return start

    def run_s07(self, name, plan, ticks, bounds, density_until=None, folder='encounters'):
        """Labeled placement of the real S06 v3 exit pose, then trusted input; identical replay."""
        start = self.s06_v3_exit()
        trace, players, mech, result = self.run_s05(name, plan, ticks, bounds, density_until=density_until, folder=folder,
                                                    start=start, start_label=self.START_LABEL)
        result.pop('s04_exit_ledge_bounces')
        ledge = [x['tick'] for x in mech if x['element'] == 'S06-exit-ledge']
        result.update(initial_placement=dict(labeled=True, source=type(self).v3_s06_start_proof),
            s06_exit_ledge_bounces=dict(count=len(ledge), first=ledge[0] if ledge else None, last=ledge[-1] if ledge else None),
            mechanic_events=[x for x in result['mechanic_events'] if x['element'] != 'S06-exit-ledge'])
        return trace, players, mech, result

    def s07_kinds(self, mech):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S06-exit-ledge']

    def no_foreign_contact(self, trace, until):
        """No contact point lies on an element of another section (or the legacy S07 pieces) up to tick `until`."""
        m = self.report()['manifest']
        travel = {v['element']:v for v in m['geometry']['movers']}
        own = set(self.S07_V3_ROUTE_ELEMENTS)
        others = {e['id']:self.bounds_v3(e, travel.get(e['id'])) for e in m['geometry']['elements']
                  if e['role'] != 'drag' and e['id'] not in own and e['id'] != 'S06-exit-ledge' and not e['id'].startswith('mountain-')}
        hits = sorted({k for e in self.contacts(trace) if e['tick'] <= until for k, b in others.items()
                       if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1})
        self.assertEqual(hits, [])
        return dict(foreign_contact_points=hits, contact_events=len([e for e in self.contacts(trace) if e['tick'] <= until]))

    def test_01_geometry_and_rules(self):
        r = self.report(); v1 = self.v1_s07()
        m = r['manifest']; elements = m['geometry']['elements']
        s07 = m['sections'][6]
        # Completed by TASK-524: all four encounters, their links and the S07 fall recovery are built; the optional
        # S07-01 -> S07-04 shortcut stays planned. TASK-526 built the S08 entrance (the v3 S08-01 starts on the S07 exit ledge).
        self.assertEqual((s07['designVersion'], s07['status']), (3, 'built'))
        enc_all = m['encounters'][24:28]
        self.assertEqual([e['status'] for e in enc_all], ['built']*4)
        self.assertEqual([(c['id'], c['from'], c['to'], c['status']) for c in m['connectors'][24:29]],
                         [('S07-entrance','S06-04','S07-01','built'), ('S07-route-1','S07-01','S07-02','built'),
                          ('S07-route-2','S07-02','S07-03','built'), ('S07-route-3','S07-03','S07-04','built'),
                          ('S08-entrance','S07-04','S08-01','built')])
        rec = m['recoveries'][6]
        self.assertEqual((rec['status'], rec['from'], rec['to'], rec['rejoin']), ('built', 'S07-04', 'S05-01', 'S07-01'))
        self.assertTrue(all(x in {e['id'] for e in elements} for x in rec['elements']))
        sc = m['shortcuts'][1]
        self.assertEqual((sc['id'], sc['from'], sc['to'], sc['optional'], sc['status']), ('S07-shortcut', 'S07-01', 'S07-04', True, 'planned'))
        self.assertNotIn('solidExceptions', s07)
        self.assertEqual((s07['band']['top'], s07['band']['bottom']), (-12960, -9720))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S07-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S07-')}
        self.assertEqual(set(movers), set(self.S07_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        hazards = [e['id'] for e in elements if e['role'] == 'hazard']
        self.assertFalse([h for h in hazards if h.startswith('S07-')])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        self.assertTrue(all(by_id[x]['role'] == 'solid' and by_id[x]['grapplable'] for x in movers))
        enc = {e['id']:e for e in enc_all}
        self.assertEqual(enc['S07-01']['start'], {'x':1543.2,'y':-11261.3,'from':'S06-04'})
        self.assertEqual(enc['S07-02']['start'], {'from':'S07-01','x':770.1,'y':-12154.3})
        self.assertEqual(enc['S07-03']['start'], {'from':'S07-02','x':1687.3,'y':-12735.5})
        self.assertEqual(enc['S07-04']['start'], {'from':'S07-03','x':1164,'y':-12742.7})
        for e in enc_all:
            self.assertTrue(all(x in by_id for x in e['elements']), e['id'])
            self.assertTrue(any(by_id[x]['role'] == 'bounce' and x.startswith('S07-') for x in e['elements']), e['id'])
        # Blue movers carry S07-01/02; S07-03/04 are green hooks.
        self.assertEqual([e['id'] for e in enc_all if any(x in movers for x in e['elements'])], ['S07-01','S07-02'])
        for name, box in (('S07-01', self.S07_01_EXIT), ('S07-02', self.S07_02_EXIT), ('S07-03', self.S07_03_EXIT), ('S07-04', self.S07_04_EXIT)):
            self.assertEqual(enc[name]['exit'], dict(left=box['x'][0], right=box['x'][1], top=box['y'][0], bottom=box['y'][1]))
        sec = r['report']['sections'][6]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S07', 3, True, [], 1620))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][:7], ['S01','S02','S03','S04','S05','S06','S07'])
        self.assertFalse(r['report']['failed'])
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual'], direction['entryX'], direction['exitX']), ('right', 'right', 1543.2, 2520))
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S07-01','S07-02'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S07_V3_BAND))
        self.assertEqual([g['id'] for g in gaps], list(self.S07_V3_GAPS))
        for g in gaps:
            self.assertTrue(self.S07_V3_BAND[0] <= g['distance'] <= self.S07_V3_BAND[1], g)
        travel = {v['element']:v for v in m['geometry']['movers']}
        base_range = {}
        self.assertEqual([g['id'] for g in s07['gaps']], list(self.S07_V3_GAPS))
        for g, mover in zip(s07['gaps'], self.S07_V3_ANCHORS):
            b = self.bounds_v3(by_id[mover], travel.get(mover)); p = g['from']
            near = self.box_gap(b, p['x'], p['y'])
            self.assertGreater(near, 1080, (g['id'], near))
            base_range[g['id']] = dict(anchor=mover, blue_mover=mover in movers, anchor_box_over_travel=b, nearest_point_distance=near,
                                       base_range=1080, beyond_base_range=True)
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], list(self.S07_V3_FALLS))
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), self.S07_V3_FALLS[f['id']], f)
            self.assertEqual((f['x'], f['y']), self.S07_V3_FALL_POINTS[f['id']])
            self.assertEqual(by_id[f['firstBouncer']]['role'], 'bounce')
            for dz in f['dragZones']:
                b = self.bounds_v3(by_id[dz])
                self.assertTrue(b['left'] <= f['x']-18 and f['x']+18 <= b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, dz))
        # S07 fall points only (TASK-526: S08-01-short also drops through S07-exit-drag).
        self.assertEqual([dict(id=d['id'], fallPoints=[f for f in d['fallPoints'] if f.startswith('S07-')]) for d in sec['rules']['strayDrag']['measured']['dragZones']],
            [dict(id='S07-crown-drag', fallPoints=['S07-02-missed','S07-04-missed']),
            dict(id='S07-exit-drag', fallPoints=['S07-04-late']), dict(id='S07-short-drag', fallPoints=['S07-03-short'])])
        # Every static v1 S07 solid is deleted or converted to a green bouncer in place; the v1 red rotor mover is deleted.
        self.assertEqual(sorted(v1['staticSolids']), sorted(V1_S07_DISPOSITION))
        self.assertEqual(sorted(v1['movers']), sorted(V1_S07_MOVER_DISPOSITION))
        own_ids = {e['id'] for e in own}
        v1_by_id = {e['id']:e for e in v1['elements']}
        mapping = []
        for old in v1['staticSolids']+v1['movers']:
            kind, why = (V1_S07_DISPOSITION | V1_S07_MOVER_DISPOSITION)[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertNotIn(old, own_ids, old)
            else:
                self.assertEqual(now['role'], 'bounce', old)
                self.assertEqual((now['x'], now['y'], now['points']), (v1_by_id[old]['x'], v1_by_id[old]['y'], v1_by_id[old]['points']), old)
            mapping.append(dict(id=old, v1_role=v1_by_id[old]['role'] if old in v1['staticSolids'] else 'mover (%s)' % v1_by_id[old]['role'],
                                disposition=kind, v3_role=now['role'] if now else None, reason=why))
        self.assertEqual(sorted(set(v1_by_id) - set(V1_S07_DISPOSITION) - set(V1_S07_MOVER_DISPOSITION)), [])
        self.assertEqual(sorted(own_ids - set(v1_by_id)), sorted(V3_S07_ADDED))
        # The legacy pieces once named by the v1 Summit Array (deleted by TASK-526) stay green in place.
        self.assertTrue(all(by_id[x]['role'] == 'bounce' for x in ('S07-exit','S07-roof-boom','S07-recovery-balcony')))
        # No v3 S07 route element (or its drag zone) overlaps another section's element (movers over their travel).
        others = [e for e in elements if e['id'].split('-')[0] in ('S01','S02','S03','S04','S05','S06','S08') or e['id'].startswith('mountain-')]
        for k in self.S07_V3_ROUTE_ELEMENTS:
            ba = self.bounds_v3(by_id[k], travel.get(k))
            for o in others:
                bo = self.bounds_v3(o, travel.get(o['id']))
                self.assertFalse(ba['left'] < bo['right'] and bo['left'] < ba['right'] and ba['top'] < bo['bottom'] and bo['top'] < ba['bottom'], (k, o['id']))
        measured = {g['id']:g['distance'] for g in gaps}
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S07-01','S07-02','S07-03','S07-04'], planned=[],
            active_range=sec['range'], gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1620] = 1378-1458 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=measured, gaps_not_crossable_at_1080=base_range, direction=direction,
            direction_note='the direction rule reads the centre of the S07-04 exit box (x 2340..2700 -> 2520, the green exit ledge inside '
                           'S07-exit-drag) against the S07-01 entry x (1543.2, the S06 exit ledge): the section exits right of its entry',
            mover_coverage=sec['rules']['moverCoverage']['measured'],
            fall_points=falls, own_drag_zones=sec['rules']['strayDrag']['measured']['dragZones'],
            drag_below_every_fall_point=True, gray_solid_count=len(gray), s07_hazards=[]))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s07, encounters=enc_all, planned_encounters=[],
            connectors=m['connectors'][24:29], recovery=m['recoveries'][6], shortcut=sc, elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True, v1_revision=V1_S07_REVISION,
            v1_static_solids=v1['staticSolids'], v1_movers=v1['movers'], v1_disposition=mapping, v3_added=list(V3_S07_ADDED),
            route_overlaps_with_other_sections=[]))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="900" viewBox="-60 -13200 6600 4640" style="background:#111827">']
        for e in elements:
            if e['id'].split('-')[0] not in ('S04','S05','S06','S08') and e['id'] not in ('mountain-left','mountain-right'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.15' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="3"/>')
        route = set(self.S07_V3_ROUTE_ELEMENTS)
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors[roles[e['id']]] + ('" fill-opacity="0.35' if roles[e['id']] == 'yellow drag' else '' if e['id'] in route else '" fill-opacity="0.45')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="3"/>')
            dx, dy = {'S07-trolley':(-120,-10),'S07-west-wall':(50,80),'S07-carriage':(-200,-10),'S07-crown-wall':(-650,-10),
                      'S07-crown-ledge':(-700,90),'S07-gable-hook':(-180,-10),'S07-exit-ledge':(-520,95),'S07-exit-drag':(-600,-10),'S07-short-drag':(-560,40),'S07-crown-drag':(-760,60),'S07-roof-boom':(-200,-10),'S07-recovery-balcony':(-300,-10),
                      'S07-exit':(-100,-60)}.get(e['id'], (0,0))
            label = e['id'] + ('' if e['id'] in route else ' (legacy, green)')
            parts.append(f'<text x="{e["x"]+dx}" y="{e["y"]-16+dy}" fill="white" font-size="56">{label} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+15}" x2="{e["x"]+60+v["max"]-v["min"]}" y2="{e["y"]+15}" stroke="#93c5fd" stroke-width="6" stroke-dasharray="12,8"/>')
        for g in s07['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="6" stroke-dasharray="14,10"/>')
        for f in falls:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="{min(f["firstBouncerTop"], -8600)}" stroke="#fb923c" stroke-width="5" stroke-dasharray="8,12"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="16" fill="#fb923c"/><text x="{f["x"]+30}" y="{f["y"]+60}" fill="#fb923c" font-size="52">{f["id"]}</text>')
        for e in enc_all:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="6"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+55}" fill="#f472b6" font-size="52">{e["id"]} exit</text>')
        parts.append('<circle cx="1543.2" cy="-11261.3" r="28" fill="#ff7a1a"/>')
        for i, t in enumerate(['S07 Exposed Crown v3 (designVersion 3, built: S07-01..04, travelling right), zero gray solids',
                'orange dot = real S06 v3 exit settled pose; grey = S04, S05, S06, legacy S08 and the map edges',
                'S07-01: blue trolley pulled up-left -> crawl out of the S06 exit pocket -> swing west -> green west wall ricochet east',
                'S07-02: blue carriage caught in flight -> swing up-right over the S05 hoist -> green crown wall -> flight west along the top',
                'yellow dashes = gaps %s of 1620 (all > 1080); orange = fall points over drag zones (S07-01-short slides down the' % '/'.join(str(round(g['distance'],1)) for g in gaps),
                'left map edge to the S04 catch basin at y -6000); pink = exit boxes; faded green = legacy v1 Crown pieces kept for the v1 Summit Array',
                'S07-03: flight west -> left map edge -> green west wall bounce -> green gable hook pulled east -> flight east along the top',
                'S07-04: green exit ledge caught in flight -> dive into S07-exit-drag -> settle on the exit ledge (section exit, under the S05 hoist)',
                'S07-03-short: early gable release -> S07-short-drag kills the drift -> straight down onto the green S06 drop ledge in S06-drop-drag']):
            parts.append(f'<text x="2950" y="{-9640+i*60}" fill="#67e8f9" font-size="44">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=dict(width=1280, height=900)); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S07 designVersion 3 built (S07-01..04); gray solids', len(gray), '; roles',
              sorted(set(roles.values())), '; all 7 v3 rules pass at range', sec['range'], '; direction right', direction['entryX'], '<', direction['exitX'],
              '; gaps', [round(g['distance'],1) for g in gaps], 'in', list(self.S07_V3_BAND), '; nearest mover point from each press',
              {k:round(v['nearest_point_distance'],1) for k, v in base_range.items()}, '> 1080; fall points over drag',
              {f['id']:f['dragZones'] for f in falls}, '; v1', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def s07_01_checks(self, trace, players, mech, result):
        """Crawl out of the S06 exit pocket's west side, swing west under the trolley, west-wall ricochet into the flight east."""
        drag = self.S06_EXIT_DRAG
        out = next(t for t in range(1, len(players)) if not self.in_box(players[t], drag))
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S07-trolley')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S07-trolley')
        self.assertEqual(release['tick'], self.TROLLEY_RELEASE)
        self.assertTrue(acq['tick'] < out < release['tick'], (acq['tick'], out))
        # Left the pocket through its open west side (the S04 exit ledge closes it above).
        self.assertLess(players[out]['x'], drag['left'])
        crawl = [players[t]['speedX'] for t in range(acq['tick']+15, out-5)]
        self.assertTrue(crawl and max(abs(v) for v in crawl) < .2, crawl[:5])
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S07-trolley']['dx']), 1)
        rel = players[self.TROLLEY_RELEASE]
        self.assertTrue(rel['speedX'] < -2 and rel['speedY'] < 0, rel)
        wall, before, after = self.bounce_s05(trace, 'S07-west-wall')
        self.assertTrue(release['tick'] < wall['tick'] < self.S07_01_TICKS)
        # Flat green wall: the westward flight is turned east, the climb kept.
        self.assertLess(before['speedX'], -2); self.assertAlmostEqual(after['speedX'], -before['speedX'], delta=.02)
        self.assertAlmostEqual(after['speedY'], before['speedY'], delta=1e-6); self.assertLess(after['speedY'], 0)
        quiet = [e for e in trace['events'] if e['type'] in ('contact','bounce') and acq['tick'] <= e['tick'] <= self.S07_01_TICKS
                 and e['tick'] != wall['tick'] and (e.get('contact') or {}).get('elementId') != 'S06-exit-ledge']
        self.assertEqual(quiet, [])
        self.assertTrue(self.inside(players[self.S07_01_TICKS], self.S07_01_EXIT), players[self.S07_01_TICKS])
        return dict(trolley_acquisition_tick=acq['tick'], left_s06_exit_drag=dict(tick=out, player=players[out], side='west'),
            crawl_max_abs_speedX=max(abs(v) for v in crawl), trolley_release=dict(tick=self.TROLLEY_RELEASE, player=rel),
            west_wall_bounce=dict(tick=wall['tick'], before=before, after=after), other_contacts_between_acquisition_and_exit=[])

    def test_02_s07_01_nominal(self):
        trace, players, mech, result = self.run_s07('S07-01', self.S07_01_V3, self.S07_01_TICKS, self.S07_01_EXIT)
        self.assertEqual(self.s07_kinds(mech), [('acquisition','S07-trolley'),('release','S07-trolley'),('bounce','S07-west-wall')])
        checks = self.s07_01_checks(trace, players, mech, result)
        reach = self.reach_s05(players, mech, 5, 'S07-trolley')
        touched = self.no_foreign_contact(trace, self.S07_01_TICKS)
        result.update(encounter='S07-01', acquisition_reach=reach, contacts=touched, **checks)
        self.evidence.write('encounters/S07-01/result.json', result)
        wb = checks['west_wall_bounce']
        print('PASS S07-01: from the real S06 v3 exit pose (range upgraded', result['range_upgraded_at_start'], '); blue trolley acquisition',
              round(reach['distance'],1), 'at tick', reach['acquisition_tick'], '; left S06-exit-drag west at tick', checks['left_s06_exit_drag']['tick'],
              '; released at', self.TROLLEY_RELEASE, '; green west wall bounce at tick', wb['tick'], 'v', (round(wb['before']['speedX'],3), round(wb['before']['speedY'],3)),
              '->', (round(wb['after']['speedX'],3), round(wb['after']['speedY'],3)), '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s07_02_nominal(self):
        trace, players, mech, result = self.run_s07('S07-02', self.S07_01_V3+self.S07_02_V3, self.S07_02_TICKS, self.S07_02_EXIT)
        self.assertEqual(self.s07_kinds(mech), [('acquisition','S07-trolley'),('release','S07-trolley'),('bounce','S07-west-wall'),
            ('acquisition','S07-carriage'),('release','S07-carriage'),('bounce','S07-crown-wall')])
        self.s07_01_checks(trace, players, mech, result)
        carriage = next(e for e in mech if e['type']=='acquisition' and e['element']=='S07-carriage')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S07-carriage')
        self.assertTrue(self.CARRIAGE_PRESS < carriage['tick'] < release['tick'] == self.CARRIAGE_RELEASE)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S07-carriage']['dx']), 1)
        launch = players[self.S07_01_TICKS]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (770.1, -12154.3))
        # Caught in flight: still flying east, nothing touched between the west wall and the crown wall.
        wall_tick = next(e['tick'] for e in mech if e['element']=='S07-west-wall')
        crown_tick = next(e['tick'] for e in mech if e['element']=='S07-crown-wall')
        self.assertGreater(players[carriage['tick']]['speedX'], 2)
        self.assertFalse([e for e in trace['events'] if e['type'] in ('contact','bounce') and wall_tick < e['tick'] < crown_tick])
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][carriage['tick']:release['tick']+1]))
        rel = players[release['tick']]
        self.assertTrue(rel['speedX'] > players[carriage['tick']]['speedX'] + .3 and rel['speedY'] < players[carriage['tick']]['speedY'], rel)
        bounce, before, after = self.bounce_s05(trace, 'S07-crown-wall')
        # Flat green wall: the up-right flight is turned west, the climb kept; the rebound passes over S07-crown-drag.
        self.assertGreater(before['speedX'], 3); self.assertAlmostEqual(after['speedX'], -before['speedX'], delta=.02)
        self.assertAlmostEqual(after['speedY'], before['speedY'], delta=1e-6)
        over = min(self.CROWN_DRAG['top'] - (players[t]['y'] + players[t]['radius']) for t in range(release['tick'], self.S07_02_TICKS+1)
                   if players[t]['x'] + players[t]['radius'] >= self.CROWN_DRAG['left'])
        self.assertGreater(over, 50)
        self.assertFalse([t for t in range(len(players)) if self.in_box(players[t], self.CROWN_DRAG)])
        # From the west-wall ricochet to the S07-02 exit the flight stays clear of the S05 canopy and the S05 hoist (whole travel).
        span = range(wall_tick, self.S07_02_TICKS+1)
        canopy = min(self.box_gap(self.S05_CANOPY, players[t]['x'], players[t]['y']) for t in span) - launch['radius']
        hoist = min(self.box_gap(self.S05_HOIST, players[t]['x'], players[t]['y']) for t in span) - launch['radius']
        self.assertGreater(canopy, 80); self.assertGreater(hoist, 60)
        reach = self.reach_s05(players, mech, self.CARRIAGE_PRESS, 'S07-carriage')
        trolley = self.reach_s05(players, mech, 5, 'S07-trolley')
        touched = self.no_foreign_contact(trace, self.S07_02_TICKS)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {'S07-trolley':trolley, 'S07-carriage':reach}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S07-02', segmented_from='S07-01 exit at tick 290 of the same run (no further placement)',
            s07_01_exit_at_tick_290=launch, acquisition_reach=reach, caught_in_flight=dict(tick=carriage['tick'], player=players[carriage['tick']]),
            rope_points_max=2, carriage_release=dict(tick=release['tick'], player=rel),
            crown_wall_bounce=dict(tick=bounce['tick'], before=before, after=after), clearance_over_s07_crown_drag=over,
            min_clearance_to_s05_canopy=canopy, min_clearance_to_s05_hoist_travel=hoist, contacts=touched)
        self.evidence.write('encounters/S07-02/result.json', result)
        print('PASS S07-02: from the S07-01 exit at tick', self.S07_01_TICKS, '; blue carriage acquisition', round(reach['distance'],1), 'at tick',
              carriage['tick'], '(in flight, vx', round(players[carriage['tick']]['speedX'],3), '); released at', release['tick'], '; green crown wall bounce at tick',
              bounce['tick'], 'vx', round(before['speedX'],3), '->', round(after['speedX'],3), ', clear of the crown drag by', round(over,1),
              '; S05 canopy / hoist clearance', round(canopy,1), round(hoist,1), '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_04_declared_falls_through_drag(self):
        out = {}
        trace, players, mech, result = self.run_s07('S07-01-short', self.S07_01_SHORT, 2000, self.BASIN_SETTLE,
                                                    density_until=self.SHORT_RELEASE, folder='falls')
        kinds = self.s07_kinds(mech)
        self.assertEqual(kinds[:2], [('acquisition','S07-trolley'),('release','S07-trolley')])
        self.assertFalse([k for k in kinds[2:] if k[1] != 'S04-catch-basin'], kinds)
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 0]
        self.assertTrue(edge)
        out['S07-01-short'] = self.fall_s03(trace, players, mech, self.SHORT_RELEASE, 'S04-catch-basin', self.S04_FALL_DRAG, self.BASIN_SETTLE)
        out['S07-01-short']['left_map_edge_first_contact'] = dict(tick=edge[0], player=players[edge[0]])
        self.assertLessEqual(abs(players[edge[0]]['y'] - self.S07_V3_FALL_POINTS['S07-01-short'][1]), 20)
        out['S07-01-short']['players_at'] = players
        trace, players, mech, result = self.run_s07('S07-02-missed', self.S07_01_V3, 1200, self.CROWN_SETTLE,
                                                    density_until=self.S07_01_TICKS, folder='falls')
        kinds = self.s07_kinds(mech)
        self.assertEqual(kinds[:3], [('acquisition','S07-trolley'),('release','S07-trolley'),('bounce','S07-west-wall')])
        self.assertNotIn(('acquisition','S07-carriage'), kinds)
        self.assertFalse([k for k in kinds[3:] if k[1] != 'S07-crown-ledge'], kinds)
        out['S07-02-missed'] = self.fall_s03(trace, players, mech, self.TROLLEY_RELEASE, 'S07-crown-ledge', self.CROWN_DRAG, self.CROWN_SETTLE)
        out['S07-02-missed']['players_at'] = players
        out['S07-02-missed']['contacts'] = self.no_foreign_contact(trace, 1200)
        for k, v in out.items():
            fx, fy = self.S07_V3_FALL_POINTS[k]
            # Every drop starts at its apex above the declared fall point, and crosses the declared height inside its column.
            self.assertLessEqual(v['apex']['player']['y'], fy+1)
            ps = v.pop('players_at')
            cross = next(t for t in range(v['apex']['tick'], v['landing']['tick']) if ps[t]['y'] >= fy)
            self.assertLessEqual(abs(ps[cross]['x'] - fx), 20, (k, ps[cross]))
            v['declared_fall_point'] = (fx, fy)
            v['declared_point_crossing'] = dict(tick=cross, player=ps[cross])
        self.evidence.write('falls/result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S07 fall point is exercised from the labeled real S06 v3 exit pose. S07-01-short: the trolley released at 190 '
                 'flies west onto the left map edge, slides down it through S04-fall-drag onto the green S04 catch basin (an exposed miss that '
                 'loses several sections), rebounds to at most half the drop (never back to the release height) and settles. S07-02-missed: '
                 'with no carriage press the S07-01 flight passes under the S05 hoist into S07-crown-drag, drops onto the green crown ledge, '
                 'rebounds to at most half the drop and settles'))
        for k, v in out.items():
            print('PASS fall', k, ': apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on',
                  v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
                  '; settled from tick', v['settled_from_tick'])


class CrownV3CompleteChecks(CrownV3Checks):
    """Layout-v3 Exposed Crown S07-03/04, section exit and fall recovery (TASK-524), with real input.

    Same labeled-placement proof as CrownV3Checks: the start is the real S06 v3 exit settled pose. S07-03/04 continue the
    S07-01/02 inputs of the same run, so they are segmented from the S07-02 exit (tick 420) and the S07-03 exit (tick
    736), not placed. Not a continuous-completion claim. Shared by Task524Tests (the inherited S07-01/02 cases also run).
    """
    LV6 = LiftworksV3CompleteChecks
    GABLE_V3, EXIT_LEDGE_V3 = (1435,-12940), (2345,-11958)
    GABLE_PRESS, GABLE_RELEASE, EXIT_PRESS, EXIT_RELEASE = 630, 700, 736, 761
    # S07-03: the S07-02 flight west meets the left map edge (contact, no bounce) and drops onto the green west wall,
    # which keeps bouncing it straight up and down; the green gable hook (top of the band, far east) is pressed near the
    # top of a bounce (630) and held 70: the pull carries the player east along the top, under the S07-02 return
    # flight's height, into a flight east. S07-04: the green exit ledge is caught in that flight (736) and held 25; the
    # pull turns the flight into a dive east, released early, which enters S07-exit-drag from above-west, lands on the
    # green exit ledge and settles there (the section exit, under the S05 hoist).
    S07_03_V3 = [(GABLE_PRESS,'mousedown',*GABLE_V3),(GABLE_RELEASE,'mouseup',*GABLE_V3)]
    S07_04_V3 = [(EXIT_PRESS,'mousedown',*EXIT_LEDGE_V3),(EXIT_RELEASE,'mouseup',*EXIT_LEDGE_V3)]
    S07_ROUTE_V3 = CrownV3Checks.S07_01_V3+CrownV3Checks.S07_02_V3+S07_03_V3+S07_04_V3
    S07_03_TICKS, S07_04_TICKS, S07_FULL_TICKS, S07_LAND_BY = 736, 1300, 1400, 900
    S07_EXIT_DRAG = dict(left=2340, right=2700, top=-12260, bottom=-11960)
    S07_SHORT_DRAG = dict(left=1145, right=1265, top=-12520, bottom=-12360)
    GABLE_HOOK = dict(left=1405, right=1465, top=-12955, bottom=-12925)
    S06_DROP_DRAG, DROP_SETTLE = LV6.S06_DROP_DRAG, LV6.DROP_SETTLE
    S07_04_SETTLE = CrownV3Checks.S07_04_EXIT
    # Mistimed S07-03 (fall.json): the gable hook is released 30 ticks early (670), so the flight east is too slow and
    # sinks: it crosses S07-short-drag, which kills the drift, and drops straight down the clear column through
    # S06-drop-drag onto the green S06 drop ledge (an S06 route bouncer) and settles (by ~1800). Input-only rejoin from
    # 1920: the S06 climb hook (aimed at its east end, TASK-521) held 180 throws the player up the S06 rise, the S06 exit
    # hook pressed near its top (2142, held 90) carries it into the S06 exit pocket onto the S06 exit ledge, and the S07-01
    # trolley pressed from there (2645, the trolley's period-matched phase) swings it west to the green west wall again;
    # the S07-02 carriage (2930) catches the flight east and the crown wall turns it west along the top (S07-02 rejoined).
    SHORT_GABLE_RELEASE, REJOIN_TICK = 670, 1920
    CLIMB_EAST, S06_EXIT_HOOK = LV6.CLIMB_EAST, LV6.EXIT_HOOK_V3
    REJOIN_S07 = [(1920,'mousedown',*CLIMB_EAST),(2100,'mouseup',*CLIMB_EAST),
                  (2142,'mousedown',*S06_EXIT_HOOK),(2232,'mouseup',*S06_EXIT_HOOK),
                  (2645,'mousedown',*CrownV3Checks.TROLLEY_V3),(2885,'mouseup',*CrownV3Checks.TROLLEY_V3),
                  (2930,'mousedown',*CrownV3Checks.CARRIAGE_V3),(2962,'mouseup',*CrownV3Checks.CARRIAGE_V3)]
    REJOIN_EXIT_PRESS, REJOIN_TROLLEY_PRESS, REJOIN_CARRIAGE_PRESS = 2142, 2645, 2930
    # The rejoined S07-02 ends in the flight west along the top (as the nominal S07-02 exit).
    REJOIN_END = dict(x=[1650,1850], y=[-12800,-12760], speedX=[-3.4,-3.1], speedY=[-.25,0])
    S07_03_SHORT = CrownV3Checks.S07_01_V3+CrownV3Checks.S07_02_V3+[(GABLE_PRESS,'mousedown',*GABLE_V3),(SHORT_GABLE_RELEASE,'mouseup',*GABLE_V3)]
    FALL_S07, FALL_S07_TICKS = S07_03_SHORT+REJOIN_S07, 3060
    # Declared S07-04 misses: no exit-ledge press (the flight east lands in S07-crown-drag on the green crown ledge); the
    # exit ledge held LATE_HOLD ticks (dives through S07-exit-drag onto the exit ledge).
    LATE_RELEASE = 769
    S07_04_MISSED = CrownV3Checks.S07_01_V3+CrownV3Checks.S07_02_V3+S07_03_V3
    S07_04_LATE = S07_04_MISSED+[(EXIT_PRESS,'mousedown',*EXIT_LEDGE_V3),(LATE_RELEASE,'mouseup',*EXIT_LEDGE_V3)]

    def s07_03_checks(self, trace, players, mech):
        """Flight west -> left map edge -> green west wall bounce -> gable hook pull -> flight east along the top."""
        self.assertTrue(self.inside(players[self.S07_02_TICKS], self.S07_02_EXIT), players[self.S07_02_TICKS])
        edge = [e['tick'] for e in self.contacts(trace) if e['contact']['x'] == 0 and e['tick'] > self.S07_02_TICKS]
        walls = [e for e in mech if e['type']=='bounce' and e['element']=='S07-west-wall' and e['tick'] > self.S07_02_TICKS]
        self.assertTrue(edge and walls and edge[0] < walls[0]['tick'] < self.GABLE_PRESS, (edge[:1], walls[:1]))
        wall, before, after = next((e, e['before']['simulation']['player'], e['after']['simulation']['player']) for e in trace['events']
                                   if e['type']=='bounce' and e['contact']['elementId']=='S07-west-wall' and e['tick'] == walls[0]['tick'])
        # Lands on the wall top straight down the map edge, bounced straight back up.
        self.assertTrue(before['speedY'] > .5 and after['speedY'] < -.5 and abs(after['speedX']) < .05 and after['x'] < 12, (before, after))
        press = players[self.GABLE_PRESS]
        self.assertTrue(press['x'] < 11 and -.5 < press['speedY'] < 0, press)
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S07-gable-hook')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S07-gable-hook')
        self.assertTrue(self.GABLE_PRESS < acq['tick'] < release['tick'] == self.GABLE_RELEASE)
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][acq['tick']:release['tick']+1]))
        rel = players[self.GABLE_RELEASE]
        self.assertTrue(rel['speedX'] > 2 and abs(rel['speedY']) < .1, rel)
        # The pull off the map edge touches only the map edge; the flight east along the top touches nothing and stays clear
        # of the gable hook and of every drag zone.
        span = range(acq['tick'], self.S07_03_TICKS+1)
        self.assertFalse([e for e in self.contacts(trace) if acq['tick'] <= e['tick'] <= self.S07_03_TICKS
                          and not (e['contact']['x'] == 0 and e['tick'] < self.GABLE_RELEASE)])
        hook = min(self.box_gap(self.GABLE_HOOK, players[t]['x'], players[t]['y']) for t in span) - press['radius']
        self.assertGreater(hook, 100)
        self.assertFalse([t for t in span for d in (self.S07_SHORT_DRAG, self.S07_EXIT_DRAG, self.CROWN_DRAG) if self.in_box(players[t], d)])
        self.assertTrue(self.inside(players[self.S07_03_TICKS], self.S07_03_EXIT), players[self.S07_03_TICKS])
        reach = self.reach_s05(players, mech, self.GABLE_PRESS, 'S07-gable-hook')
        return dict(gable_acquisition_reach=reach, map_edge_contact_tick=edge[0],
            west_wall_bounce=dict(tick=wall['tick'], before=before, after=after), press_on_west_wall_bounce=press,
            gable_release=dict(tick=self.GABLE_RELEASE, player=rel),
            flight=dict(ticks=[acq['tick'], self.S07_03_TICKS], contacts=[], min_clearance_to_gable_hook=hook, drag_zones_entered=[]))

    def s07_04_checks(self, trace, players, mech, ticks=None):
        """Exit-ledge pull in flight, dive into S07-exit-drag, exit ledge landing and settle (the section exit)."""
        ticks = ticks or len(players)-1
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S07-exit-ledge' and e['tick'] >= self.EXIT_PRESS)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S07-exit-ledge' and e['tick'] > acq['tick'])
        self.assertEqual(release['tick'], self.EXIT_RELEASE)
        self.assertGreater(players[acq['tick']]['speedX'], 2)
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][acq['tick']:release['tick']+1]))
        drag = self.S07_EXIT_DRAG
        entry = next(t for t in range(release['tick'], ticks+1) if self.in_box(players[t], drag))
        land = next(e for e in mech if e['type']=='bounce' and e['element']=='S07-exit-ledge' and e['tick'] > release['tick'])
        # Nothing is touched from the acquisition to the exit ledge landing.
        self.assertFalse([e for e in self.contacts(trace) if acq['tick'] <= e['tick'] < land['tick']])
        self.assertTrue(all(self.in_box(players[t], drag) for t in range(entry, ticks+1)))
        before = players[entry-1]
        self.assertTrue(before['speedX'] > 1 and before['speedY'] > .5, before)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, entry+6) if abs(players[t]['speedX']) > 1e-9]
        at_ledge = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land['tick'])['before']['simulation']['player']
        self.assertLess(abs(at_ledge['speedX']), .05)
        # The dive passes under the S05 hoist (whole travel) and stays clear of the crown drag.
        dive = range(release['tick'], land['tick']+1)
        hoist = min(self.box_gap(self.S05_HOIST, players[t]['x'], players[t]['y']) for t in dive) - before['radius']
        self.assertGreater(hoist, 60)
        self.assertFalse([t for t in range(acq['tick'], ticks+1) if self.in_box(players[t], self.CROWN_DRAG)])
        nxt = next((e['tick'] for e in mech if e['type']=='bounce' and e['element']=='S07-exit-ledge' and e['tick'] > land['tick']), ticks)
        peak = min(players[t]['y'] for t in range(land['tick'], nxt+1))
        apex = min(players[t]['y'] for t in range(self.GABLE_RELEASE, land['tick']))
        drop = land['player']['y'] - apex
        self.assertGreater(peak, drag['top'])
        settle = next(t for t in range(land['tick'], ticks+1) if all(self.inside(players[u], self.S07_04_SETTLE) for u in range(t, ticks+1)))
        tail = players[settle:ticks+1]
        self.assertGreaterEqual(len(tail), 100)
        return dict(exit_ledge_acquisition_reach=self.reach_s05(players, mech, self.EXIT_PRESS, 'S07-exit-ledge'),
            exit_ledge_acquisition_tick=acq['tick'], exit_ledge_release=dict(tick=release['tick'], player=release['player']),
            exit_drag_entry=dict(tick=entry, before=before, at_entry=players[entry]), per_tick_vx_ratio_in_drag=ratios,
            speed_before_landing=dict(speedX=at_ledge['speedX'], speedY=at_ledge['speedY']), min_clearance_to_s05_hoist_travel=hoist,
            exit_ledge_landing=dict(tick=land['tick'], player=land['player']),
            first_rebound=dict(peak_y=peak, drop_from_flight_apex=drop, fraction=(land['player']['y']-peak)/drop, stays_inside_exit_drag=True),
            section_exit=dict(element='S07-exit-ledge', drag_zone='S07-exit-drag', settle_tick=settle, settled_ticks=len(tail),
                settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[ticks], settle_box=self.S07_04_SETTLE, inside_exit_drag=True))

    def test_06_s07_03_nominal(self):
        plan = self.S07_01_V3+self.S07_02_V3+self.S07_03_V3
        trace, players, mech, result = self.run_s07('S07-03', plan, self.S07_03_TICKS, self.S07_03_EXIT)
        self.assertEqual(self.s07_kinds(mech)[6:], [('bounce','S07-west-wall'),('acquisition','S07-gable-hook'),('release','S07-gable-hook')])
        out = self.s07_03_checks(trace, players, mech)
        touched = self.no_foreign_contact(trace, self.S07_03_TICKS)
        result.update(encounter='S07-03', segmented_from='S07-02 exit at tick 420 of the same run (no further placement)',
            s07_02_exit_at_tick_420=players[self.S07_02_TICKS], exit_judged_at_tick=self.S07_03_TICKS, contacts=touched, **out)
        self.evidence.write('encounters/S07-03/result.json', result)
        r, wb = out['gable_acquisition_reach'], out['west_wall_bounce']
        print('PASS S07-03: from the S07-02 exit at tick 420; map edge at tick', out['map_edge_contact_tick'], '; green west wall bounce tick',
              wb['tick'], 'vy', round(wb['before']['speedY'],3), '->', round(wb['after']['speedY'],3), '; green gable-hook acquisition',
              round(r['distance'],1), 'at tick', r['acquisition_tick'], '; release', self.GABLE_RELEASE, 'v',
              (round(out['gable_release']['player']['speedX'],3), round(out['gable_release']['player']['speedY'],3)), '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_07_s07_04_nominal(self):
        trace, players, mech, result = self.run_s07('S07-04', self.S07_ROUTE_V3, self.S07_04_TICKS, self.S07_04_EXIT,
                                                    density_until=self.S07_LAND_BY)
        self.assertTrue(self.inside(players[self.S07_03_TICKS], self.S07_03_EXIT), players[self.S07_03_TICKS])
        self.assertEqual(self.s07_kinds(mech)[9:12], [('acquisition','S07-exit-ledge'),('release','S07-exit-ledge'),('bounce','S07-exit-ledge')])
        out = self.s07_04_checks(trace, players, mech)
        self.assertLessEqual(out['exit_ledge_landing']['tick'], self.S07_LAND_BY)
        touched = self.no_foreign_contact(trace, self.S07_04_TICKS)
        result.update(encounter='S07-04', segmented_from='S07-03 exit (the flight east) at tick 736 of the same run (no further placement)',
            s07_03_exit_at_tick_736=players[self.S07_03_TICKS], contacts=touched, **out)
        self.evidence.write('encounters/S07-04/result.json', result)
        r = out['exit_ledge_acquisition_reach']
        print('PASS S07-04: from the flight at tick 736; green exit-ledge acquisition', round(r['distance'],1), 'at tick', r['acquisition_tick'],
              '; release', out['exit_ledge_release']['tick'], '; enters S07-exit-drag at tick', out['exit_drag_entry']['tick'], 'vx ratio',
              [round(x,3) for x in out['per_tick_vx_ratio_in_drag'][:3]], '; S05 hoist clearance', round(out['min_clearance_to_s05_hoist_travel'],1),
              '; exit ledge landing tick', out['exit_ledge_landing']['tick'], 'first rebound', round(out['first_rebound']['fraction'],3),
              '; settled from tick', out['section_exit']['settle_tick'], 'at', {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')},
              '; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], 'until tick', self.S07_LAND_BY, '; identical replay; trusted input')

    def test_08_full_traversal(self):
        trace, players, mech, result = self.run_s07('S07-full', self.S07_ROUTE_V3, self.S07_FULL_TICKS, self.S07_04_EXIT,
                                                    density_until=self.S07_LAND_BY)
        self.assertEqual([e['element'] for e in mech if e['type']=='acquisition'],
                         ['S07-trolley','S07-carriage','S07-gable-hook','S07-exit-ledge'])
        self.assertEqual([e['element'] for e in mech if e['type']=='bounce' and e['element'] != 'S06-exit-ledge'][:5],
                         ['S07-west-wall','S07-crown-wall','S07-west-wall','S07-exit-ledge','S07-exit-ledge'])
        exits = {}
        for name, tick, bounds in (('S07-01',self.S07_01_TICKS,self.S07_01_EXIT),('S07-02',self.S07_02_TICKS,self.S07_02_EXIT),
                                   ('S07-03',self.S07_03_TICKS,self.S07_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        s3 = self.s07_03_checks(trace, players, mech)
        s4 = self.s07_04_checks(trace, players, mech)
        exits['S07-04'] = dict(tick=s4['section_exit']['settle_tick'], player=players[s4['section_exit']['settle_tick']], box=self.S07_04_EXIT)
        touched = self.no_foreign_contact(trace, self.S07_FULL_TICKS)
        reaches = [self.reach_s05(players, mech, t, el) for t, el in ((5,'S07-trolley'),(self.CARRIAGE_PRESS,'S07-carriage'),
                   (self.GABLE_PRESS,'S07-gable-hook'),(self.EXIT_PRESS,'S07-exit-ledge'))]
        m = self.report()['manifest']
        gaps = {g['id']:g for g in m['sections'][6]['gaps']}
        # The manifest gaps are the trace-measured press poses and anchors (rounded to 0.1; the S07-01 gap starts from the
        # settled S06 exit pose, which the ledge bounce moves by under a pixel before the press).
        for gid, r in zip(self.S07_V3_GAPS, reaches):
            g = gaps[gid]
            self.assertAlmostEqual(g['from']['x'], r['player_at_press']['x'], delta=1); self.assertAlmostEqual(g['from']['y'], r['player_at_press']['y'], delta=1)
            self.assertAlmostEqual(g['to']['x'], r['anchor']['x'], delta=.5); self.assertAlmostEqual(g['to']['y'], r['anchor']['y'], delta=.5)
        result.update(encounter='S07 full traversal', encounter_exits=exits, s07_03=s3, s07_04=s4, section_exit=s4['section_exit'],
            section_exit_reached=True, settled_at_section_exit=True, contacts=touched, reaches=reaches)
        self.evidence.write('encounters/S07-full/result.json', result)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {x['element']:x for x in reaches}
            self.evidence.write('rules.json', rules)
        print('PASS full S07: from the real S06 v3 exit pose; exits', {k:v['tick'] for k, v in exits.items()}, '; reaches',
              [round(x['distance'],1) for x in reaches], '; exit ledge landing tick', s4['exit_ledge_landing']['tick'], '; settled from tick',
              s4['section_exit']['settle_tick'], 'for', s4['section_exit']['settled_ticks'], 'ticks at',
              {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')}, 'inside S07-exit-drag; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_09_fall_through_drag_and_rejoin(self):
        trace, players, mech, result = self.run_s07('S07-03-short', self.FALL_S07, self.FALL_S07_TICKS, self.REJOIN_END,
                                                    density_until=self.SHORT_GABLE_RELEASE, folder='falls')
        rel = players[self.SHORT_GABLE_RELEASE]
        release = next(e for e in mech if e['type']=='release' and e['element']=='S07-gable-hook')
        self.assertEqual(release['tick'], self.SHORT_GABLE_RELEASE)
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S06-drop-ledge' and self.SHORT_GABLE_RELEASE < e['tick'] < self.REJOIN_TICK]
        self.assertTrue(ledge)
        land = ledge[0]['tick']
        # Nothing but the drop ledge is touched between the release and the rejoin.
        self.assertFalse([e for e in mech if self.SHORT_GABLE_RELEASE < e['tick'] < self.REJOIN_TICK and e['element'] != 'S06-drop-ledge'])
        self.assertFalse([e for e in self.contacts(trace) if self.SHORT_GABLE_RELEASE < e['tick'] < self.REJOIN_TICK
                          and not (1150 <= e['contact']['x'] <= 1310 and abs(e['contact']['y'] + 9080) < 2)])
        apex_tick = min(range(self.SHORT_GABLE_RELEASE, land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        # The S07-short-drag pass: the eastward drift is killed (vx x0.8 per tick), the sink continues.
        short = [t for t in range(apex_tick, land) if self.in_box(players[t], self.S07_SHORT_DRAG)]
        s_in, s_out = short[0], short[-1]
        self.assertEqual(short, list(range(s_in, s_out+1)))
        s_before, s_after = players[s_in-1], players[s_out+1]
        self.assertGreater(s_before['speedX'], 1); self.assertLess(abs(s_after['speedX']), .05)
        hratio = [players[t+1]['speedX']/players[t]['speedX'] for t in range(s_in, s_in+6) if abs(players[t]['speedX']) > 1e-9]
        # The S06-drop-drag pass, down to the drop ledge.
        drag = self.S06_DROP_DRAG
        ticks = [t for t in range(s_out+1, land+1) if self.in_box(players[t], drag)]
        entry, leave = ticks[0], ticks[-1]
        self.assertEqual(ticks, list(range(entry, land+1)))
        before = players[entry-1]
        self.assertFalse(self.in_box(before, drag)); self.assertGreater(before['speedY'], 1)
        vdamp = [players[t+1]['speedY']-players[t]['speedY']*.985 for t in range(entry, leave)][:8]
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_ledge = contact['before']['simulation']['player']
        self.assertLess(at_ledge['speedY'], before['speedY'])
        self.assertLessEqual(abs(at_ledge['speedX']), abs(before['speedX']))
        rest_y = ledge[0]['player']['y']
        fall_height = rest_y - apex['y']
        self.assertGreater(fall_height, 3000)
        # The declared S07-03-short fall point: the drop crosses its height within the column radius, and the whole drop
        # from there stays in the clear column over the drop ledge.
        fx, fy = self.S07_V3_FALL_POINTS['S07-03-short']
        self.assertLessEqual(apex['y'], fy+1)
        cross = next(t for t in range(apex_tick, land) if players[t]['y'] >= fy)
        self.assertLessEqual(abs(players[cross]['x']-fx), 18)
        column = [players[t]['x'] for t in range(cross, land+1)]
        self.assertTrue(1150+10.8 < min(column) and max(column) < 1310-10.8, (min(column), max(column)))
        peaks = []
        for a, b in zip(ledge, ledge[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(p['peak_y'] > rel['y'] for p in peaks))
        # Settled on the green S06 drop ledge inside S06-drop-drag before the rejoin press.
        window = players[self.REJOIN_TICK-100:self.REJOIN_TICK]
        self.assertTrue(all(self.inside(p, self.DROP_SETTLE) and self.in_box(p, drag) for p in window))
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_TICK]
        self.assertEqual(len(rejoin_inputs), len(self.REJOIN_S07))
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after_rejoin = [e for e in mech if e['tick'] >= self.REJOIN_TICK]
        self.assertEqual([e['element'] for e in after_rejoin if e['type']=='acquisition'], ['S06-climb-hook','S06-exit-hook','S07-trolley','S07-carriage'])
        # Back in the S06 exit pocket (the S07 entrance): settled on the S06 exit ledge inside S06-exit-drag before the
        # trolley press, then the S07-01 trolley swing reaches the green west wall again.
        pocket = players[self.REJOIN_TROLLEY_PRESS-50:self.REJOIN_TROLLEY_PRESS+1]
        self.assertTrue(all(self.inside(p, self.S06_V3_SETTLE) and self.in_box(p, self.S06_EXIT_DRAG) for p in pocket))
        exit_ledge = next(e for e in mech if e['element']=='S06-exit-ledge' and e['type']=='bounce' and e['tick'] > self.REJOIN_EXIT_PRESS)
        trolley = next(e for e in mech if e['type']=='acquisition' and e['element']=='S07-trolley' and e['tick'] > self.REJOIN_TICK)
        wall = next(e for e in mech if e['type']=='bounce' and e['element']=='S07-west-wall' and e['tick'] > trolley['tick'])
        self.assertGreater(wall['player']['speedX'], 2)
        carriage = next(e for e in mech if e['type']=='acquisition' and e['element']=='S07-carriage' and e['tick'] > wall['tick'])
        crown = next(e for e in mech if e['type']=='bounce' and e['element']=='S07-crown-wall' and e['tick'] > carriage['tick'])
        self.assertLess(crown['player']['speedX'], -3)
        fall = dict(scenario='naturally mistimed S07-03 release: the green gable hook is released at tick %d instead of %d (30 ticks early); the '
                             'flight east is too slow, sinks into S07-short-drag and drops physically; no relocation after the labeled S06 v3 '
                             'exit start placement' % (self.SHORT_GABLE_RELEASE, self.GABLE_RELEASE),
            release=dict(tick=self.SHORT_GABLE_RELEASE, element='S07-gable-hook', press_tick=self.GABLE_PRESS,
                         nominal_release_tick=self.GABLE_RELEASE, player=rel, release_height_y=rel['y']),
            fall_point=dict(id='S07-03-short', declared_x=fx, declared_y=fy, crossing=dict(tick=cross, player=players[cross]),
                            column_x_range=[min(column), max(column)], landing_x=at_ledge['x']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='S06 drop ledge bounce rest y minus the apex y after the release',
            drag_zones=[dict(id='S07-short-drag', box=self.S07_SHORT_DRAG, entry_tick=s_in, exit_tick=s_out+1,
                    before=dict(tick=s_in-1, **{k:s_before[k] for k in ('x','y','speedX','speedY')}),
                    after=dict(tick=s_out+1, **{k:s_after[k] for k in ('x','y','speedX','speedY')}),
                    per_tick_vx_ratio=hratio, note='the eastward drift is damped (vx x0.8 per tick); below it the drop is straight'),
                dict(id='S06-drop-drag', box=drag, entry_tick=entry, last_tick_inside_before_landing=leave,
                    before=dict(tick=entry-1, **{k:before[k] for k in ('x','y','speedX','speedY')}),
                    after=dict(tick=land, **{k:at_ledge[k] for k in ('x','y','speedX','speedY')},
                               note='player state just before the drop ledge bounce, after crossing the drag zone'),
                    vertical_damping_per_tick=0.985, vy_minus_damped_previous_vy_first_ticks=vdamp)],
            bouncer=dict(element='S06-drop-ledge', section='S06', route='S06 route bouncer: the green drop ledge under the S06-03 rise (the '
                         'S06-04 miss catch, TASK-521), from which the S06 climb hook rejoins the S06 route', first_bounce_tick=land,
                         rest_y=rest_y, inside='S06-drop-drag'),
            bounce_peaks=peaks[:8], bounce_count=len(peaks), first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            never_back_to_release_height=True,
            settled=dict(window=[self.REJOIN_TICK-100, self.REJOIN_TICK-1], box=self.DROP_SETTLE,
                max_abs_speedX=max(abs(p['speedX']) for p in window), max_abs_speedY=max(abs(p['speedY']) for p in window),
                y_range=[min(p['y'] for p in window), max(p['y'] for p in window)], inside_drag_zone='S06-drop-drag', on='S06-drop-ledge'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                start_tick=self.REJOIN_TICK, mechanics=[{k:e[k] for k in ('tick','type','element','player')} for e in after_rejoin
                           if e['type'] != 'contact' and e['element'] not in ('S06-drop-ledge','S06-exit-ledge')],
                s06_exit_ledge_landing=dict(tick=exit_ledge['tick'], player=exit_ledge['player']),
                s06_exit_pocket_settled=dict(window=[self.REJOIN_TROLLEY_PRESS-50, self.REJOIN_TROLLEY_PRESS], box=self.S06_V3_SETTLE,
                    inside='S06-exit-drag', player_at_trolley_press=players[self.REJOIN_TROLLEY_PRESS]),
                trolley_acquisition=dict(tick=trolley['tick'], player=trolley['player']),
                west_wall_ricochet=dict(tick=wall['tick'], player=wall['player']),
                carriage_acquisition=dict(tick=carriage['tick'], player=carriage['player']),
                crown_wall_rebound=dict(tick=crown['tick'], player=crown['player']), final=players[-1], end_box=self.REJOIN_END,
                encounter_rejoined='S06-03/04 (climb and exit hooks from the drop ledge) back onto the S06 exit ledge, the S07 entrance, '
                                   'then S07-01 (trolley swing, green west wall ricochet) and S07-02 (carriage caught in flight, green '
                                   'crown wall rebound into the flight west along the top, where S07-03 starts)'))
        result.update(fall)
        self.evidence.write('falls/S07-03-short/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: gable hook released', self.SHORT_GABLE_RELEASE, '(nominal', self.GABLE_RELEASE, ') at y', round(rel['y'],1), '; apex',
              round(apex['y'],1), '; S07-short-drag vx', round(s_before['speedX'],3), '->', round(s_after['speedX'],4), '; S06-drop-drag vx/vy',
              round(before['speedX'],4), round(before['speedY'],3), '->', round(at_ledge['speedX'],6), round(at_ledge['speedY'],3),
              '; S06 drop ledge bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of', round(fall_height,1), '; settled at x',
              round(window[-1]['x'],1), '; input-only rejoin from tick', self.REJOIN_TICK, ': acquisitions',
              [e['element'] for e in after_rejoin if e['type']=='acquisition'], '; S06 exit ledge tick', exit_ledge['tick'],
              '; west wall ricochet tick', wall['tick'], '; carriage tick', carriage['tick'], '; crown wall tick', crown['tick'],
              '; final', {k:round(players[-1][k],2) for k in ('x','y','speedX','speedY')})
        # The declared S07-03/04 fall points, each from the same labeled start.
        out = {}
        trace, players, mech, result = self.run_s07('S07-04-missed', self.S07_04_MISSED, 1800, self.CROWN_SETTLE,
                                                    density_until=self.S07_03_TICKS, folder='falls')
        self.assertNotIn('S07-exit-ledge', [e['element'] for e in mech if e['type']=='acquisition'])
        out['S07-04-missed'] = self.fall_s03(trace, players, mech, self.GABLE_RELEASE, 'S07-crown-ledge', self.CROWN_DRAG, self.CROWN_SETTLE)
        out['S07-04-missed']['players_at'] = players
        out['S07-04-missed']['contacts'] = self.no_foreign_contact(trace, 1800)
        trace, players, mech, result = self.run_s07('S07-04-late', self.S07_04_LATE, self.S07_04_TICKS, self.S07_04_EXIT,
                                                    density_until=self.S07_LAND_BY, folder='falls')
        out['S07-04-late'] = self.fall_s03(trace, players, mech, self.LATE_RELEASE, 'S07-exit-ledge', self.S07_EXIT_DRAG, self.S07_04_EXIT)
        out['S07-04-late']['players_at'] = players
        for k, v in out.items():
            fx, fy = self.S07_V3_FALL_POINTS[k]
            # Every drop starts at its apex above the declared fall point and crosses the declared height inside its column.
            self.assertLessEqual(v['apex']['player']['y'], fy+1)
            ps = v.pop('players_at')
            cross = next(t for t in range(v['apex']['tick'], v['landing']['tick']) if ps[t]['y'] >= fy)
            self.assertLessEqual(abs(ps[cross]['x'] - fx), 18, (k, ps[cross]))
            v['declared_fall_point'] = (fx, fy)
            v['declared_point_crossing'] = dict(tick=cross, player=ps[cross])
        out['S07-03-short'] = dict(declared_fall_point=self.S07_V3_FALL_POINTS['S07-03-short'], see='fall.json',
            drag_zones=['S07-short-drag','S06-drop-drag'], landing=fall['bouncer'], first_rebound_over_drop=fall['first_peak_fraction'],
            settled=fall['settled'])
        self.evidence.write('falls/s07_03_04_result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S07-03/04 fall point is exercised from the labeled real S06 v3 exit pose; the player crosses the drag zone, '
                 'lands on the green bouncer, rebounds to at most half the drop (never back to the release height) and settles'))
        for k, v in out.items():
            if k == 'S07-03-short': continue
            print('PASS fall', k, ': apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'],
                  '; lands on', v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
                  '; settled from tick', v['settled_from_tick'])


class CrownV3ToleranceChecks(LiftworksV3ToleranceChecks):
    """Layout-v3 Exposed Crown (S07) tolerance on desktop 1280x720 and touch 844x390 (TASK-525).

    Proof kind (as TASK-523/524): the real S06 v3 exit settled pose (the v3 S06 route run from the labeled real S05 v3
    exit pose, itself the v3 S05 route run from the labeled real S04 v3 exit pose of one base-start real-input S01..S04
    v3 run, TASK-521 S06-full) is restored once as a labeled initial placement (initial_snapshot); production trusted
    mouse/touch input and physics run from there. An attempt on encounter k replays the S07 route up to k: the
    encounter's inputs carry the variant, the earlier encounters keep their TASK-523/524 nominal inputs. S07-01..03 end
    in flight, so they are judged at their mountain.js exit boxes (position at the nominal exit tick 290/420/736); S07-04
    at the S07 section exit (settled on the green exit ledge inside S07-exit-drag at tick 1300). check_s07_v3_mechanics
    requires the encounter's own mechanic, the S07 anchors in route order and no fall onto an S01-S06 element or an S07
    fall bouncer. The HUD probe reads the UI boxes the game draws (LAYOUT_PROBE) at every nominal press. No earlier
    Task525Tests exists (the v1 S07 suites Task483-485 judge the superseded v1 geometry), so there is no v2 suite to map.
    """
    CC, CX = CrownV3Checks, CrownV3CompleteChecks
    SEGMENTS = [CC.S07_01_V3, CC.S07_02_V3, CX.S07_03_V3, CX.S07_04_V3]
    V3_ENCOUNTERS = [('S07-01','blue trolley pulled up-left out of the S06 exit pocket, release into a ricochet off the green west wall (flight turned east)',0,CC.S07_01_TICKS),
                     ('S07-02','blue carriage caught in flight over the S05 hoist, release into the green crown wall (flight turned west along the top)',CC.S07_01_TICKS,CC.S07_02_TICKS),
                     ('S07-03','flight west onto the green west wall, green gable hook pulled from the top of a wall bounce, release into a flight east along the top',CC.S07_02_TICKS,CX.S07_03_TICKS),
                     ('S07-04','green exit ledge caught in flight, release into S07-exit-drag under the S05 hoist, settle on the exit ledge (S07 section exit)',CX.S07_03_TICKS,None)]
    S07_TICKS = CX.S07_04_TICKS
    STRICT = {'S07-01':CC.S07_01_EXIT, 'S07-02':CC.S07_02_EXIT, 'S07-03':CX.S07_03_EXIT}
    # Mistimed releases, one per encounter, no further input afterwards: (encounter, release tick replacing the nominal one,
    # nominal release tick, ticks, declared fall point or None, landing bouncer).
    MISTIMED = [('S07-01',190,245,2000,'S07-01-short','S04-catch-basin'), ('S07-02',300,322,1200,'S07-02-missed','S07-crown-ledge'),
                ('S07-03',670,700,1900,'S07-03-short','S06-drop-ledge'), ('S07-04',769,761,1300,'S07-04-late','S07-exit-ledge')]
    UNDECLARED = {}
    V3_MOVERS = CC.S07_V3_MOVERS
    ANCHOR_IDS = dict(zip(('S07-01','S07-02','S07-03','S07-04'), CC.S07_V3_ANCHORS))
    HUD_FINDING = ('No HUD obstruction found: every S07 anchor is drawn clear of the HUD text rows and the pause button at its '
                   'press on both viewports (no S07 geometry moved for the HUD).')
    # The S06-exit start chain (CrownV3Checks.s06_v3_exit) reads the completed S06 route from LC.
    LC = LiftworksV3CompleteChecks
    S06_V3_SETTLE, S06_EXIT_DRAG, S07_V3_ROUTE_ELEMENTS = CC.S06_V3_SETTLE, CC.S06_EXIT_DRAG, CC.S07_V3_ROUTE_ELEMENTS
    s06_v3_exit, path_segments = CC.s06_v3_exit, CC.path_segments

    def exits(self):
        """Per encounter: (ticks, judged exit bounds, meaning), from the runtime manifest."""
        enc = {e['id']:e for e in self.report()['manifest']['encounters'][24:28]}
        out = {}
        for name, _, _, tick in self.V3_ENCOUNTERS:
            if tick:
                b = enc[name]['exit']
                out[name] = (tick, dict(x=[b['left'],b['right']], y=[b['top'],b['bottom']]),
                             f'inside the mountain.js {name} exit box at the nominal exit tick {tick}')
            else:
                out[name] = (self.S07_TICKS, self.CX.S07_04_EXIT,
                             'settled on S07-exit-ledge inside S07-exit-drag (S07 section exit) at tick %d' % self.S07_TICKS)
        return out

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s07_v3_mechanics
        start = self.s06_v3_exit()
        self.assertTrue(self.inside(start['player'], self.S06_V3_SETTLE), start['player'])
        exits = self.exits()
        source = hashes()
        suite = dict(section='S07', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='isolated: one labeled initial placement (initial_snapshot) = the real S06 v3 exit settled pose (the v3 S06 route '
                       'run from the labeled real S05 v3 exit pose, itself the v3 S05 route run from the labeled real S04 v3 exit pose of a '
                       'base-start real-input S01..S04 v3 run; encounters/S04-exit-start, S05-exit-start, S06-exit-start), then production '
                       'trusted mouse/touch input and physics; an attempt on encounter k carries the variant on k and the TASK-523/524 '
                       'nominal inputs on S07-01..k-1',
            initial_placement=type(self).v3_s06_start_proof, browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exits={n: dict(ticks=t, box=b, meaning=w) for n, (t, b, w) in exits.items()},
            mechanics_check='tools/grapple_over_verify.py check_s07_v3_mechanics',
            nominal_note='every nominal press aims at its anchor at a fixed world point (TASK-523/524), so desktop and touch run the same '
                         'route; every anchor is drawn clear of the HUD text and the pause button at its press (hud-probe.json)',
            pause_button_client_rects={str(k): v for k, v in self.PAUSE_BUTTON.items()},
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            hud_probe='hud-probe.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal, clips = [], {}, {}
        for k, (name, mechanic, begin, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            ticks, bounds, meaning = exits[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), ticks, bounds, device, snapshot=start)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s07_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s07_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(self.clear(targets), (label, targets))
                        if exit_tick:
                            self.assertTrue(self.inside(players[exit_tick], self.STRICT[name]), (label, players[exit_tick]))
                            end = exit_tick
                        else:
                            end = mechanics['encounter']['bounce_tick']
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', begin, end)
                        clips[label] = (trace, m['metadata']['viewport'], prefix, mechanics)
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning),
                        outcome=f'{name} exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(artifacts/TASK-544/calibration.json density_cap.frozen_ticks = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','mover contact (S07-trolley/S07-carriage are only rope anchors; no player contact with them occurs)'],
            cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal S07 run (0/290/420/736) to its manifest exit tick '
                   '(290/420/736) or, for S07-04, the exit-ledge landing; the settle on the exit ledge is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(start, exits['S07-04'])
        self.hud_probe(clips)
        self.assertEqual(failures, [])
        print('PASS S07 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-exit-ledge negative control fails the exit')

    def negative_control(self, start, exit):
        from grapple_over_verify import hashes, check_s07_v3_mechanics
        # Named omission: the S07-04 exit-ledge press/release left out; same placement, physics and
        # S07-01..03 inputs as every S07-04 attempt.
        ticks, bounds, meaning = exit
        plan = self.variant_plan(3)[:6]
        m = self.make_input(plan, ticks, bounds, snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s07_v3_mechanics('S07-04', trace, required=False)
        landed = [b for b in mechanics['bounces'] if b['tick'] > self.CX.GABLE_RELEASE]
        self.evidence.write('negative-control.json', dict(name='omitted exit-ledge catch: S07-04 S07-exit-ledge press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning), unchanged_physics=True, source_hashes=hashes(),
            proof_kind='same labeled S06-exit placement, real mouse input, same S07-01..03 inputs as the S07-04 attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step, bounces_after_gable_release=landed,
            exit_ledge_contact='S07-exit-ledge' in [b['element'] for b in mechanics['bounces']], final_player=players[-1],
            scope='Without the exit-ledge pull the flight east along the top carries on under the S05 hoist into S07-crown-drag '
                  '(first bouncer %s) and the S07 section exit is missed.' % (landed[0]['element'] if landed else 'none')))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S07-exit-ledge', mechanics['acquisitions'])
        self.assertNotIn('S07-exit-ledge', [b['element'] for b in mechanics['bounces']])
        self.assertFalse(self.inside(players[-1], self.CX.S07_04_EXIT))
        self.assertLess(step, 60)
        print('PASS negative control: omitted exit-ledge catch; reason', reason[:80], '; bounces after the gable release',
              [(b['element'], b['tick']) for b in landed][:4], '; final', (round(players[-1]['x'],1), round(players[-1]['y'],1)))

    FALL_SECTION_INDEX, FALL_ZONE_PREFIXES = 6, ('S01-','S02-','S03-','S04-','S05-','S06-','S07-')
    FALL_PROOF = 'labeled S06-exit placement, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation'

    def fall_start(self):
        return self.s06_v3_exit()

    def section_mechanics(self, name, trace, required=True):
        from grapple_over_verify import check_s07_v3_mechanics
        return check_s07_v3_mechanics(name, trace, required)


V1_S08_REVISION = '17a3d89'
V3_S08_ADDED = ('S08-mast-trolley','S08-roof','S08-beacon-trolley','S08-west-wall','S08-glide-cap','S08-glide-drag')
# TASK-527: S08-03/04 and the summit finish.
V3_S08_ADDED_34 = ('S08-east-wall','S08-summit-floor','S08-crest-drag')


class SummitV3Checks(CrownV3CompleteChecks):
    """Layout-v3 Summit Array opening (S08-01/02) from the real S07 v3 exit settled pose (TASK-526).

    The start pose is the real S07 exit settled pose produced by the v3 S07 build, by the chain that proves it (TASK-524
    S07-full): the CrownV3Checks S06-exit chain (one base-start real-input S01..S04 v3 run, then the S05 and S06 routes
    from ONE labeled placement each) gives the real S06 v3 exit pose; that pose is restored once (labeled) and the v3 S07
    route (TASK-523/524 inputs, 1400 ticks) runs onto the green S07 exit ledge inside S07-exit-drag. That S07 pose is
    restored once as a labeled initial placement (initial_snapshot), then production trusted input and physics run.
    Not a continuous-completion claim. Range 1620. TASK-527 completed S08-03/04 and the summit finish: test_01 judges the
    completed section (shared by Task526/527Tests), the S08-03/04 runs live in SummitV3CompleteChecks.
    The inherited S07 cases are judged by Task523/524Tests, not here.
    """
    test_02_s07_01_nominal = test_03_s07_02_nominal = test_04_declared_falls_through_drag = None
    test_06_s07_03_nominal = test_07_s07_04_nominal = test_08_full_traversal = test_09_fall_through_drag_and_rejoin = None
    CC = CrownV3CompleteChecks
    START_LABEL = ('the real S07 v3 exit settled pose (the v3 S07 route run from the labeled real S06 v3 exit pose, itself the end of '
                   'the TASK-521 S06-full chain from one base-start real-input S01..S04 v3 run, as TASK-524 S07-full)')
    MAST_V3, BEACON_V3 = (2060,-13300), (430,-13330)
    # S08-01: the mast trolley is pressed at 185 (so the rise out of S07-exit-drag passes the S05 hoist at its east turn,
    # tick 275) and acquired at 192; the drag zone only lets the player rise straight up out of the pocket, then the pull
    # hurls it up-left past the hoist's west end; released at 303 it rebounds off the green roof (352) onto the top of
    # the moving mast trolley (361) and slides off west into a glide. S08-02: the beacon trolley press at 390 catches it
    # in the glide (397); the swing runs west under it into the green west wall (498, still attached), and the pull lifts
    # it up-right; released at 550 it flies east under the roof.
    MAST_PRESS, MAST_RELEASE, BEACON_PRESS, BEACON_RELEASE = 185, 303, 390, 550
    S08_01_V3 = [(MAST_PRESS,'mousedown',*MAST_V3),(MAST_RELEASE,'mouseup',*MAST_V3)]
    S08_02_V3 = [(BEACON_PRESS,'mousedown',*BEACON_V3),(BEACON_RELEASE,'mouseup',*BEACON_V3)]
    S08_01_TICKS, S08_02_TICKS = 390, 565
    S08_01_EXIT = dict(x=[1850,2000], y=[-13345,-13310], speedX=[-.8,-.7], speedY=[0,.3])
    S08_02_EXIT = dict(x=[1450,1700], y=[-13400,-13300], speedX=[2.3,2.6], speedY=[-.7,-.3])
    S08_V3_MOVERS = ('S08-mast-trolley','S08-beacon-trolley')
    S05_V3_MOVERS = S08_V3_MOVERS
    # TASK-527 completed the section: S08-03/04, their gaps, fall points and drag zone and the finish are judged here too.
    S08_V3_GAPS = ('S08-01-trolley','S08-02-beacon','S08-03-wall','S08-04-roof')
    S08_V3_ANCHORS = ('S08-mast-trolley','S08-beacon-trolley','S08-east-wall','S08-roof')
    S08_V3_ROUTE_ELEMENTS = V3_S08_ADDED+V3_S08_ADDED_34
    S08_V3_FALLS = {'S08-01-short':(['S07-exit-drag'],'S07-exit-ledge'), 'S08-02-missed':(['S08-glide-drag'],'S08-glide-cap'),
                    'S08-03-short':(['S07-crown-drag','S08-crest-drag'],'S07-crown-ledge'),
                    'S08-04-missed':(['S07-crown-drag','S08-crest-drag'],'S07-crown-ledge')}
    S08_V3_FALL_POINTS = {'S08-01-short':(2587,-12300), 'S08-02-missed':(1560,-13150), 'S08-03-short':(2830,-13050), 'S08-04-missed':(2803,-13150)}
    S08_03_EXIT = dict(x=[2780,2840], y=[-13290,-13230], speedX=[-.3,.05], speedY=[-.1,.25])
    FINISH = dict(left=2380, right=2735, top=-13300, bottom=-13121)
    # The crest drag sits by design right over S07-crown-drag (the S07 route stays under y -12645 there): its clearance bound
    # from the S01..S07 flight is 100 (drag zone, not a collider); every collider keeps the 200 bound.
    S08_PLAYER_CLEARANCE_BY = {'S08-crest-drag':100}
    S07_V3_SETTLE = CrownV3Checks.S07_04_EXIT
    GLIDE_DRAG = dict(left=1400, right=1560, top=-13140, bottom=-13030)
    GLIDE_SETTLE = dict(x=[1400,1560], y=[-13050,-13030], speedX=[-.001,.001], speedY=[-.05,.05])
    # Extended west to 1350 by TASK-527 (its far west end is the S08-04 anchor).
    ROOF = dict(left=1350, right=2600, top=-13495, bottom=-13470)
    # Declared misses: the mast trolley released at 240 (still inside S07-exit-drag) rises short of the hoist and drops
    # back onto the S07 exit ledge; with no beacon press the glide sinks into S08-glide-drag onto the green glide cap.
    SHORT_RELEASE = 240
    S08_01_SHORT = [(MAST_PRESS,'mousedown',*MAST_V3),(SHORT_RELEASE,'mouseup',*MAST_V3)]
    # Clearance bounds of the S08 route colliders from the S01..S07 v3 flight, ropes and throw lines.
    S08_PLAYER_CLEARANCE, S08_LINE_CLEARANCE = 200, 20

    def v1_s08(self):
        """The layout-v1 S08 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V1_S08_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            movers=m.geometry.movers.filter(v=>v.element.startsWith('S08-'));
            return {section:m.sections[7], encounters:m.encounters.slice(28,32), elements:m.geometry.elements.filter(e=>e.id.startsWith('S08-')),
                movers:movers.map(v=>v.id), moverElements:movers.map(v=>v.element), finish:m.finish}}''', source)

    def s07_v3_exit(self):
        """Real S07 v3 exit settled pose, by the chain that proves the S07 build (TASK-524 S07-full)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'v3_s07_start'): return type(self).v3_s07_start
        start6 = self.s06_v3_exit()
        CC = self.CC
        m = dict(metadata=metadata('isolated'), ticks=CC.S07_FULL_TICKS, expected_exit=self.S07_V3_SETTLE,
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in CC.S07_ROUTE_V3],
            required_events=['acquisition','release','bounce'], initial_snapshot=start6)
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/S07-exit-start'
        self.evidence.write(prefix+'/input.json', m)
        run7 = execute(m, self.browser, self.url, str(self.evidence.path(prefix)))
        check_trace(m, run7)
        self.assertTrue(all(e['trusted'] for e in run7['events'] if e['type']=='input'))
        self.assertEqual(run7['metadata']['setupOnlySpawns'], [])
        players7 = [s['state']['simulation']['player'] for s in run7['snapshots']]
        acquired7 = [e['after']['rope'][0]['id'] for e in run7['events'] if e['type']=='acquisition']
        self.assertEqual(acquired7, list(CC.S07_V3_ANCHORS))
        compact7 = Task506Tests.compact(self, run7)
        self.evidence.write(prefix+'/trace.json', compact7)
        settle = next(t for t in range(CC.S07_LAND_BY, CC.S07_FULL_TICKS+1) if all(self.inside(p, self.S07_V3_SETTLE) for p in players7[t:]))
        self.assertLessEqual(settle, CC.S07_FULL_TICKS-100)
        start = run7['snapshots'][-1]['state']['simulation']
        self.assertTrue(self.in_box(start['player'], CC.S07_EXIT_DRAG))
        self.assertEqual((round(start['player']['x'],1), round(start['player']['y'],1)), (2608.9, -11971.5))
        self.assertIs(start['upgrades']['range'], True)
        # No S07-route contact point lies on a new S08 element.
        m2 = self.report()['manifest']
        travel = {v['element']:v for v in m2['geometry']['movers']}
        boxes = {e['id']:self.bounds_v3(e, travel.get(e['id'])) for e in m2['geometry']['elements'] if e['id'] in self.S08_V3_ROUTE_ELEMENTS}
        self.assertEqual(sorted(boxes), sorted(self.S08_V3_ROUTE_ELEMENTS))
        hits = sorted({k for e in run7['events'] if e['type'] == 'contact' for k, b in boxes.items()
                       if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1})
        self.assertEqual(hits, [])
        # Clearance of the whole S01..S07 v3 flight, of every rope segment while attached and of every throw line from
        # the new S08 route colliders and drag zone (movers over their whole travel).
        earlier = [json.loads(self.evidence.path(p+'/trace.json').read_text())
                   for p in ('encounters/S04-exit-start','encounters/S05-exit-start','encounters/S06-exit-start')]
        players, ropes, throws = self.path_segments(earlier+[compact7])
        seg = lambda b, segs, n: min(self.box_gap(b, a[0]+(c[0]-a[0])*i/n, a[1]+(c[1]-a[1])*i/n) for a, c in segs for i in range(n+1))
        clearance, rope_clearance, throw_clearance = {}, {}, {}
        for k, b in boxes.items():
            clearance[k] = min(self.box_gap(b, p['x'], p['y']) for p in players) - players[0]['radius']
            rope_clearance[k] = seg(b, ropes, 40)
            throw_clearance[k] = seg(b, throws, 200)
            self.assertGreater(clearance[k], getattr(self, 'S08_PLAYER_CLEARANCE_BY', {}).get(k, self.S08_PLAYER_CLEARANCE), (k, clearance))
            self.assertGreater(rope_clearance[k], self.S08_LINE_CLEARANCE, (k, rope_clearance))
            self.assertGreater(throw_clearance[k], self.S08_LINE_CLEARANCE, (k, throw_clearance))
        type(self).v3_s07_start = start
        type(self).v3_s07_start_proof = dict(kind='the real S07 v3 exit settled pose: the v3 S07 route (TASK-523/524 inputs, 1400 ticks) run '
            'from ONE labeled placement of the real S06 v3 exit settled pose (the TASK-521 S06-full chain: the v3 S06 route from ONE labeled '
            'placement of the real S05 v3 exit pose, itself the v3 S05 route from ONE labeled placement of the real S04 v3 exit pose of one '
            'base-start real-input S01..S04 v3 run); the chain that proves the S07 build (TASK-524 S07-full)',
            s06_exit=type(self).v3_s06_start_proof, s07_inputs=m['inputs'], s07_acquisitions=acquired7, settled_in_exit_box_from_tick=settle,
            settle_box=self.S07_V3_SETTLE, final_tick=CC.S07_FULL_TICKS, player=start['player'], inside_S07_exit_drag=True,
            snapshot_sha256=run7['snapshots'][-1]['sha256'], full_trace_sha256=state_hash(run7), trace=prefix+'/trace.json',
            s08_element_contacts=[], s01_s07_flight_clearance_to_s08_route_elements=clearance, player_clearance_bound=self.S08_PLAYER_CLEARANCE,
            s01_s07_rope_clearance_to_s08_route_elements=rope_clearance, s01_s07_throw_line_clearance_to_s08_route_elements=throw_clearance,
            player_clearance_bound_by_element=getattr(self, 'S08_PLAYER_CLEARANCE_BY', {}),
            line_clearance_bound=self.S08_LINE_CLEARANCE, throw_lines=len(throws), rope_segments=len(ropes), player_samples=len(players),
            range_upgraded=start['upgrades']['range'])
        self.evidence.write(prefix+'/result.json', dict(passed=True, **type(self).v3_s07_start_proof))
        return start

    def run_s08(self, name, plan, ticks, bounds, density_until=None, folder='encounters'):
        """Labeled placement of the real S07 v3 exit pose, then trusted input; identical replay."""
        start = self.s07_v3_exit()
        trace, players, mech, result = self.run_s05(name, plan, ticks, bounds, density_until=density_until, folder=folder,
                                                    start=start, start_label=self.START_LABEL)
        result.pop('s04_exit_ledge_bounces')
        acq = self.mast_acquisition(mech)
        rest = [x['tick'] for x in mech if x['element'] == 'S07-exit-ledge' and x['tick'] < acq]
        result.update(initial_placement=dict(labeled=True, source=type(self).v3_s07_start_proof),
            s07_exit_ledge_settle_bounces_before_acquisition=dict(count=len(rest), first=rest[0] if rest else None, last=rest[-1] if rest else None),
            mechanic_events=[x for x in result['mechanic_events'] if not (x['element'] == 'S07-exit-ledge' and x['tick'] < acq)])
        return trace, players, mech, result

    def mast_acquisition(self, mech):
        return next(e['tick'] for e in mech if e['type']=='acquisition' and e['element']=='S08-mast-trolley')

    def s08_kinds(self, mech):
        """Mechanic kinds from the trolley acquisition (the settled player's micro-bounces on the S07 exit ledge before it are
        reported separately); repeated mover contacts of one slide collapse to one."""
        out = []
        for e in mech:
            if e['tick'] < self.mast_acquisition(mech): continue
            k = (e['type'], e['element'])
            if not (k[0] == 'mover-contact' and out and out[-1] == k): out.append(k)
        return out

    def foreign_contacts(self, trace, until, allowed=()):
        """Contact points on elements outside the S08 route (plus `allowed`) up to tick `until` (movers over their travel)."""
        m = self.report()['manifest']
        travel = {v['element']:v for v in m['geometry']['movers']}
        own = set(self.S08_V3_ROUTE_ELEMENTS) | set(allowed)
        others = {e['id']:self.bounds_v3(e, travel.get(e['id'])) for e in m['geometry']['elements']
                  if e['role'] != 'drag' and e['id'] not in own}
        hits = sorted({k for e in self.contacts(trace) if e['tick'] <= until for k, b in others.items()
                       if b['left']-1 <= e['contact']['x'] <= b['right']+1 and b['top']-1 <= e['contact']['y'] <= b['bottom']+1})
        self.assertEqual(hits, [])
        return dict(foreign_contact_points=hits, contact_events=len([e for e in self.contacts(trace) if e['tick'] <= until]))

    def test_01_geometry_and_rules(self):
        r = self.report(); v1 = self.v1_s08()
        m = r['manifest']; elements = m['geometry']['elements']
        s08 = m['sections'][7]
        # Completed by TASK-527: all four encounters, their links, the summit approach and the S08 fall recovery are built,
        # so the existing summit finish trigger is loaded (at the authored S08-04 finish region).
        self.assertEqual((s08['designVersion'], s08['status']), (3, 'built'))
        enc_all = m['encounters'][28:32]
        self.assertEqual([e['status'] for e in enc_all], ['built']*4)
        self.assertEqual([(c['id'], c['from'], c['to'], c['status']) for c in m['connectors'][28:33]],
                         [('S08-entrance','S07-04','S08-01','built'), ('S08-route-1','S08-01','S08-02','built'),
                          ('S08-route-2','S08-02','S08-03','built'), ('S08-route-3','S08-03','S08-04','built'),
                          ('summit-approach','S08-04','summit','built')])
        rec = m['recoveries'][7]
        self.assertEqual((rec['from'], rec['to'], rec['status'], rec['rejoin'], rec['transport']), ('S08-04', 'S07-01', 'built', 'S08-01', 'physical-fall'))
        self.assertTrue(all(x in {e['id'] for e in elements} for x in rec['elements']))
        self.assertNotIn('solidExceptions', s08)
        self.assertEqual((s08['band']['top'], s08['band']['bottom']), (-14580, -11340))
        self.assertEqual(m['finish'], self.FINISH)
        self.assertEqual(r['runtime']['finish'], self.FINISH)
        self.assertEqual(m['connectors'][32]['finishRegion'], self.FINISH)
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S08-')]
        by_id = {e['id']:e for e in elements}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S08-')}
        self.assertEqual(set(movers), set(self.S08_V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        self.assertFalse([e['id'] for e in elements if e['role'] == 'hazard' and e['id'].startswith('S08-')])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        self.assertTrue(all(by_id[x]['role'] == 'solid' and by_id[x]['grapplable'] for x in movers))
        enc = {e['id']:e for e in enc_all}
        self.assertEqual(enc['S08-01']['start'], {'x':2608.9,'y':-11971.5,'from':'S07-04'})
        self.assertEqual(enc['S08-02']['start'], {'from':'S08-01','x':1917.7,'y':-13330.5})
        self.assertEqual(enc['S08-03']['start'], {'from':'S08-02','x':1563,'y':-13346.8})
        self.assertEqual(enc['S08-04']['start'], {'from':'S08-03','x':2805.9,'y':-13257.1})
        for e in enc_all:
            self.assertTrue(all(x in by_id for x in e['elements']), e['id'])
            self.assertTrue(any(by_id[x]['role'] == 'bounce' and x.startswith('S08-') for x in e['elements']), e['id'])
            # Encounter nodes may not sit above the summit height; each start carries the real pose.
            self.assertGreaterEqual(e['y'], m['summit']['y'])
        # Blue movers carry S08-01/02; S08-03/04 are green anchors with the crest drag pocket.
        self.assertEqual([e['id'] for e in enc_all if any(x in movers for x in e['elements'])], ['S08-01','S08-02'])
        for name, box in (('S08-01', self.S08_01_EXIT), ('S08-02', self.S08_02_EXIT), ('S08-03', self.S08_03_EXIT)):
            self.assertEqual(enc[name]['exit'], dict(left=box['x'][0], right=box['x'][1], top=box['y'][0], bottom=box['y'][1]))
        self.assertEqual((enc['S08-04']['exit'], enc['S08-04']['finishRegion']), (self.FINISH, self.FINISH))
        sec = r['report']['sections'][7]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S08', 3, True, [], 1620))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'], ['S01','S02','S03','S04','S05','S06','S07','S08'])
        self.assertEqual(r['report']['legacy'], [])
        self.assertFalse(r['report']['failed'])
        direction = sec['rules']['direction']['measured']
        finish_x = (self.FINISH['left']+self.FINISH['right'])/2
        self.assertEqual((direction['required'], direction['actual'], direction['entryX'], direction['exitX']), ('left', 'left', 2608.9, finish_x))
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S08-01','S08-02'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.S07_V3_BAND))
        self.assertEqual([g['id'] for g in gaps], list(self.S08_V3_GAPS))
        for g in gaps:
            self.assertTrue(self.S07_V3_BAND[0] <= g['distance'] <= self.S07_V3_BAND[1], g)
        travel = {v['element']:v for v in m['geometry']['movers']}
        base_range = {}
        for g, anchor in zip(s08['gaps'], self.S08_V3_ANCHORS):
            b = self.bounds_v3(by_id[anchor], travel.get(anchor)); p = g['from']
            near = self.box_gap(b, p['x'], p['y']); used = math.hypot(g['to']['x']-p['x'], g['to']['y']-p['y'])
            self.assertGreater(used, 1080, g['id'])
            if anchor == 'S08-roof':
                # The roof spans the strip: its near east end is within 1080 of the crest pocket but pulls the player up
                # into the roof, not west out of the pocket; the S08-04 anchor is its far west end.
                base_range[g['id']] = dict(anchor=anchor, used_anchor_point=g['to'], used_anchor_distance=used, nearest_point_distance=near,
                                           base_range=1080, used_anchor_beyond_base_range=True)
                continue
            self.assertGreater(near, 1080, (g['id'], near))
            base_range[g['id']] = dict(anchor=anchor, blue_mover=anchor in movers, anchor_box_over_travel=b, nearest_point_distance=near,
                                       used_anchor_distance=used, base_range=1080, beyond_base_range=True)
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], list(self.S08_V3_FALLS))
        for f in falls:
            self.assertEqual((sorted(f['dragZones']), f['firstBouncer']), (sorted(self.S08_V3_FALLS[f['id']][0]), self.S08_V3_FALLS[f['id']][1]), f)
            self.assertEqual((f['x'], f['y']), self.S08_V3_FALL_POINTS[f['id']])
            self.assertEqual(by_id[f['firstBouncer']]['role'], 'bounce')
            for dz in f['dragZones']:
                b = self.bounds_v3(by_id[dz])
                self.assertTrue(b['left'] < f['x']+18 and f['x']-18 < b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, dz))
        # The S08-03/04 misses land on an S07 route bouncer (the green crown ledge) inside S07-crown-drag.
        self.assertTrue(all(f['firstBouncer'] == 'S07-crown-ledge' for f in falls if f['id'] in ('S08-03-short','S08-04-missed')))
        self.assertEqual(sec['rules']['strayDrag']['measured']['dragZones'], [dict(id='S08-glide-drag', fallPoints=['S08-02-missed']),
                                                                              dict(id='S08-crest-drag', fallPoints=['S08-03-short','S08-04-missed'])])
        # Every v1 S08 element and mover is deleted (layout v3 supersedes the v1 Summit Array; no v1 piece is reused).
        own_ids = {e['id'] for e in own}
        v1_ids = sorted(e['id'] for e in v1['elements'])
        self.assertEqual(sorted(own_ids & set(v1_ids)), [])
        self.assertEqual(sorted(own_ids), sorted(V3_S08_ADDED+V3_S08_ADDED_34))
        self.assertFalse(set(v1['movers']) & {v['id'] for v in m['geometry']['movers']})
        mapping = [dict(id=e['id'], v1_role='mover (%s)' % e['role'] if e['id'] in v1['moverElements'] else e['role'], disposition='deleted',
                        reason='v1 Summit Array piece; layout v3 rebuilds S08 in the open strip above the Crown (TASK-526 S08-01/02, '
                               'TASK-527 S08-03/04 and the summit finish over the green summit pad)') for e in v1['elements']]
        # No v3 S08 route element (or its drag zones) overlaps another section's element (movers over their travel).
        others = [e for e in elements if not e['id'].startswith('S08-')]
        for k in self.S08_V3_ROUTE_ELEMENTS:
            ba = self.bounds_v3(by_id[k], travel.get(k))
            for o in others:
                bo = self.bounds_v3(o, travel.get(o['id']))
                self.assertFalse(ba['left'] < bo['right'] and bo['left'] < ba['right'] and ba['top'] < bo['bottom'] and bo['top'] < ba['bottom'], (k, o['id']))
        # The finish region overlaps no collider; the green summit pad sits right under it.
        f = self.FINISH
        self.assertFalse([e['id'] for e in colliders if (lambda b: b['left'] < f['right'] and f['left'] < b['right'] and b['top'] < f['bottom']
                          and f['top'] < b['bottom'])(self.bounds_v3(e, travel.get(e['id'])))])
        pad = self.bounds_v3(by_id['S08-summit-floor'])
        self.assertTrue(pad['left'] <= f['left'] and f['right'] <= pad['right'] and 0 < pad['top'] - f['bottom'] <= 15, (pad, f))
        measured = {g['id']:g['distance'] for g in gaps}
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S08-01','S08-02','S08-03','S08-04'],
            active_range=sec['range'], gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1620] = 1378-1458 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=measured, gaps_beyond_1080=base_range, direction=direction,
            direction_note='S08-04 ends in the authored finish region; the direction rule reads its centre x (%.1f) against the S08-01 entry '
                           'x (2608.9, the S07 exit ledge): the section travels left' % finish_x,
            mover_coverage=sec['rules']['moverCoverage']['measured'],
            fall_points=falls, drag_under_every_fall_point=True, own_drag_zones=sec['rules']['strayDrag']['measured']['dragZones'],
            gray_solid_count=len(gray), s08_hazards=[], finish_loaded=True, finish=r['runtime']['finish']))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s08, encounters=enc_all,
            connectors=m['connectors'][28:33], recovery=rec, elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True, v1_revision=V1_S08_REVISION,
            v1_elements=v1_ids, v1_movers=v1['movers'], v1_disposition=mapping, v3_added=list(V3_S08_ADDED+V3_S08_ADDED_34),
            route_overlaps_with_other_sections=[], finish_loaded=True, finish=m['finish'], finish_overlaps_colliders=[],
            summit_pad_under_finish=pad))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="-60 -13560 4400 2475" style="background:#111827">']
        for e in elements:
            if e['id'].split('-')[0] not in ('S04','S05','S06','S07') and e['id'] != 'mountain-left': continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = '#facc15" fill-opacity="0.15' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>')
        parts.append(f'<rect x="{f["left"]}" y="{f["top"]}" width="{f["right"]-f["left"]}" height="{f["bottom"]-f["top"]}" fill="#e879f9" fill-opacity="0.3" stroke="#e879f9" stroke-width="4"/>'
                     f'<text x="{f["left"]}" y="{f["top"]-12}" fill="#e879f9" font-size="30">summit finish region (S08-04 exit)</text>')
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors[roles[e['id']]] + ('" fill-opacity="0.35' if roles[e['id']] == 'yellow drag' else '')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="2"/>')
            dx, dy = {'S08-mast-trolley':(140,40),'S08-roof':(0,-4),'S08-beacon-trolley':(-20,-10),'S08-west-wall':(45,190),
                      'S08-glide-cap':(-120,75),'S08-glide-drag':(-300,-10),'S08-east-wall':(-330,380),'S08-summit-floor':(-90,75),
                      'S08-crest-drag':(30,620)}.get(e['id'], (0,0))
            parts.append(f'<text x="{e["x"]+dx}" y="{e["y"]-8+dy}" fill="white" font-size="30">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+15}" x2="{e["x"]+60+v["max"]-v["min"]}" y2="{e["y"]+15}" stroke="#93c5fd" stroke-width="4" stroke-dasharray="10,6"/>')
        for g in s08['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="12,8"/>')
        for fp in falls:
            parts.append(f'<line x1="{fp["x"]}" y1="{fp["y"]}" x2="{fp["x"]}" y2="{fp["firstBouncerTop"]}" stroke="#fb923c" stroke-width="4" stroke-dasharray="6,8"/>'
                         f'<circle cx="{fp["x"]}" cy="{fp["y"]}" r="12" fill="#fb923c"/><text x="{fp["x"]+20}" y="{fp["y"]-14}" fill="#fb923c" font-size="26">{fp["id"]}</text>')
        for e in enc_all[:3]:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="4"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+32}" fill="#f472b6" font-size="26">{e["id"]} exit</text>')
        parts.append('<circle cx="2608.9" cy="-11971.5" r="18" fill="#ff7a1a"/>')
        for i, t in enumerate(['S08 Summit Array v3 (designVersion 3, built: S08-01..04 and the summit finish; travelling left %.1f -> %.1f), zero gray solids' % (2608.9, finish_x),
                'orange dot = real S07 v3 exit settled pose; grey = S04-S07 v3 geometry and the left map edge; magenta = summit finish region',
                'S08-01: blue mast trolley pulled up out of S07-exit-drag past the S05 hoist -> green roof -> trolley top -> glide west',
                'S08-02: blue beacon trolley caught in the glide -> swing west -> green west wall (attached) -> flight east under the roof',
                'S08-03: green east wall pulled from that flight -> leaning-face rebound west over the crown wall -> stopped in S08-crest-drag',
                'S08-04: far west end of the green roof pulled from the crest pocket -> crawl west out of the drag -> summit finish over the green pad',
                'yellow dashes = gaps %s of 1620; orange = fall points over drag zones onto green catches; pink = exit boxes' % '/'.join(str(round(g['distance'],1)) for g in gaps)]):
            parts.append(f'<text x="-40" y="{-11380+i*30}" fill="#67e8f9" font-size="25">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=dict(width=1600, height=900)); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S08 designVersion 3 built (S08-01..04, summit approach and recovery built, finish loaded at', r['runtime']['finish'],
              '); gray solids', len(gray), '; roles', sorted(set(roles.values())), '; all 7 v3 rules pass at range', sec['range'],
              '; direction left', direction['entryX'], '>', direction['exitX'], '; gaps', [round(g['distance'],1) for g in gaps], 'in', list(self.S07_V3_BAND),
              '; fall points over drag', {fp['id']:(fp['dragZones'], fp['firstBouncer']) for fp in falls}, '; v1 S08 deleted:', len(v1_ids),
              'elements,', v1['movers'], '; overview.png')

    def hoist_passage(self, trace, players, start, end):
        """Closest approach of the player to the S05 hoist's current box between `start` and `end`."""
        best = None
        for t in range(start, end+1):
            h = next(e for e in trace['snapshots'][t]['state']['simulation']['elements'] if e['id'] == 'S05-hoist')
            b = dict(left=h['x'], right=h['x']+120, top=-12470, bottom=-12440)
            d = self.box_gap(b, players[t]['x'], players[t]['y']) - players[t]['radius']
            if best is None or d < best['clearance']: best = dict(tick=t, clearance=d, hoist_x=h['x'], player=players[t])
        return best

    def s08_01_checks(self, trace, players, mech, result):
        """Rise straight out of S07-exit-drag's top past the S05 hoist, green roof rebound, slide over the trolley top, glide west."""
        drag = self.CC.S07_EXIT_DRAG
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S08-mast-trolley')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S08-mast-trolley')
        self.assertEqual(release['tick'], self.MAST_RELEASE)
        out = next(t for t in range(acq['tick'], len(players)) if not self.in_box(players[t], drag))
        self.assertTrue(acq['tick'] < out < release['tick'], (acq['tick'], out))
        # Left the pocket through its top (the drag zone keeps the crawl near-vertical).
        self.assertLess(players[out]['y'], drag['top']); self.assertTrue(drag['left'] < players[out]['x'] < drag['right'])
        crawl = [players[t]['speedX'] for t in range(acq['tick']+5, out)]
        self.assertTrue(crawl and max(abs(v) for v in crawl) < .1, crawl[:5])
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S08-mast-trolley']['dx']), 1)
        hoist = self.hoist_passage(trace, players, out, release['tick'])
        self.assertGreater(hoist['clearance'], 20, hoist)
        rel = players[self.MAST_RELEASE]
        self.assertTrue(rel['speedX'] < -.5 and rel['speedY'] < -1.5, rel)
        roof, before, after = self.bounce_s05(trace, 'S08-roof')
        self.assertTrue(release['tick'] < roof['tick'] < self.S08_01_TICKS)
        # Flat green ceiling: the climb is turned into a descent, the westward drift kept.
        self.assertLess(before['speedY'], -1); self.assertAlmostEqual(after['speedY'], -before['speedY'], delta=.02)
        self.assertAlmostEqual(after['speedX'], before['speedX'], delta=1e-6); self.assertLess(after['speedX'], 0)
        tops = [x for x in mech if x['type'] == 'mover-contact' and x['element'] == 'S08-mast-trolley']
        self.assertTrue(tops)
        first = tops[0]
        top_event = next(e for e in trace['events'] if e['type'] == 'contact' and e['tick'] == first['tick'])
        # Landed on the trolley's top face (contact normal up) and slid off west: no vertical rebound, drift kept.
        self.assertEqual((top_event['contact']['nx'], top_event['contact']['ny']), (0, -1))
        self.assertGreater(first['tick'], roof['tick'])
        self.assertAlmostEqual(players[first['tick']]['speedY'], 0, delta=.05)
        self.assertAlmostEqual(players[first['tick']]['speedX'], after['speedX'], delta=1e-6)
        quiet = [e for e in trace['events'] if e['type'] in ('contact','bounce') and acq['tick'] <= e['tick'] <= self.S08_01_TICKS
                 and e['tick'] != roof['tick'] and e['tick'] not in {x['tick'] for x in tops}]
        self.assertEqual(quiet, [])
        self.assertTrue(self.inside(players[self.S08_01_TICKS], self.S08_01_EXIT), players[self.S08_01_TICKS])
        return dict(mast_trolley_acquisition_tick=acq['tick'], left_s07_exit_drag=dict(tick=out, player=players[out], side='top'),
            crawl_max_abs_speedX=max(abs(v) for v in crawl), s05_hoist_passage=hoist, mast_trolley_release=dict(tick=self.MAST_RELEASE, player=rel),
            roof_bounce=dict(tick=roof['tick'], before=before, after=after),
            trolley_top_landing=dict(tick=first['tick'], contact=top_event['contact'], player=players[first['tick']],
                                     contact_ticks=[x['tick'] for x in tops]),
            other_contacts_between_acquisition_and_exit=[])

    def test_02_s08_01_nominal(self):
        trace, players, mech, result = self.run_s08('S08-01', self.S08_01_V3, self.S08_01_TICKS, self.S08_01_EXIT)
        self.assertEqual(self.s08_kinds(mech), [('acquisition','S08-mast-trolley'),('release','S08-mast-trolley'),('bounce','S08-roof'),
                                                ('mover-contact','S08-mast-trolley')])
        checks = self.s08_01_checks(trace, players, mech, result)
        reach = self.reach_s05(players, mech, self.MAST_PRESS, 'S08-mast-trolley')
        touched = self.foreign_contacts(trace, self.S08_01_TICKS, allowed=('S07-exit-ledge',))
        result.update(encounter='S08-01', acquisition_reach=reach, contacts=touched, **checks)
        self.evidence.write('encounters/S08-01/result.json', result)
        rb = checks['roof_bounce']
        print('PASS S08-01: from the real S07 v3 exit pose (range upgraded', result['range_upgraded_at_start'], '); blue mast trolley acquisition',
              round(reach['distance'],1), 'at tick', reach['acquisition_tick'], '; left S07-exit-drag through its top at tick', checks['left_s07_exit_drag']['tick'],
              '; S05 hoist passed with', round(checks['s05_hoist_passage']['clearance'],1), 'px clearance; released at', self.MAST_RELEASE,
              '; green roof bounce at tick', rb['tick'], 'vy', round(rb['before']['speedY'],3), '->', round(rb['after']['speedY'],3),
              '; landed on the trolley top at tick', checks['trolley_top_landing']['tick'], '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s08_02_nominal(self):
        trace, players, mech, result = self.run_s08('S08-02', self.S08_01_V3+self.S08_02_V3, self.S08_02_TICKS, self.S08_02_EXIT)
        self.assertEqual(self.s08_kinds(mech), [('acquisition','S08-mast-trolley'),('release','S08-mast-trolley'),('bounce','S08-roof'),
            ('mover-contact','S08-mast-trolley'),('acquisition','S08-beacon-trolley'),('bounce','S08-west-wall'),('release','S08-beacon-trolley')])
        self.s08_01_checks(trace, players, mech, result)
        beacon = next(e for e in mech if e['type']=='acquisition' and e['element']=='S08-beacon-trolley')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S08-beacon-trolley')
        self.assertTrue(self.BEACON_PRESS < beacon['tick'] < release['tick'] == self.BEACON_RELEASE)
        self.assertGreater(abs(result['mover_anchor_travel_while_attached']['S08-beacon-trolley']['dx']), 1)
        launch = players[self.S08_01_TICKS]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (1917.7, -13330.5))
        # Caught in the glide: still drifting west and off the trolley (no contact from the slide-off to the west wall).
        last_top = max(x['tick'] for x in mech if x['type'] == 'mover-contact')
        wall, before, after = self.bounce_s05(trace, 'S08-west-wall')
        self.assertLess(players[beacon['tick']]['speedX'], 0)
        self.assertFalse([e for e in trace['events'] if e['type'] in ('contact','bounce') and last_top < e['tick'] < wall['tick']])
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][beacon['tick']:release['tick']+1]))
        # Flat green wall while still attached: the westward swing is turned east.
        self.assertTrue(beacon['tick'] < wall['tick'] < release['tick'])
        self.assertTrue(trace['snapshots'][wall['tick']]['state']['rope'])
        self.assertLess(before['speedX'], -2); self.assertAlmostEqual(after['speedX'], -before['speedX'], delta=.02)
        self.assertAlmostEqual(after['speedY'], before['speedY'], delta=1e-6)
        rel = players[release['tick']]
        self.assertTrue(rel['speedX'] > 2 and rel['speedY'] < -.3, rel)
        self.assertFalse([e for e in trace['events'] if e['type'] in ('contact','bounce') and wall['tick'] < e['tick'] <= self.S08_02_TICKS])
        # From the glide to the S08-02 exit the swing stays above S08-glide-drag and clear of the roof.
        span = range(self.S08_01_TICKS, self.S08_02_TICKS+1)
        over = min(self.GLIDE_DRAG['top'] - (players[t]['y'] + players[t]['radius']) for t in span
                   if self.GLIDE_DRAG['left'] - 11 <= players[t]['x'] <= self.GLIDE_DRAG['right'] + 11)
        self.assertGreater(over, 30)
        self.assertFalse([t for t in span if self.in_box(players[t], self.GLIDE_DRAG)])
        roof = min(self.box_gap(self.ROOF, players[t]['x'], players[t]['y']) for t in span) - launch['radius']
        self.assertGreater(roof, 50)
        reach = self.reach_s05(players, mech, self.BEACON_PRESS, 'S08-beacon-trolley')
        mast = self.reach_s05(players, mech, self.MAST_PRESS, 'S08-mast-trolley')
        touched = self.foreign_contacts(trace, self.S08_02_TICKS, allowed=('S07-exit-ledge',))
        m = self.report()['manifest']
        gaps = {g['id']:g for g in m['sections'][7]['gaps']}
        # The manifest gaps are the trace-measured press poses and anchors (rounded to 0.1).
        for gid, rr in zip(self.S08_V3_GAPS, (mast, reach)):
            g = gaps[gid]
            self.assertAlmostEqual(g['from']['x'], rr['player_at_press']['x'], delta=.1); self.assertAlmostEqual(g['from']['y'], rr['player_at_press']['y'], delta=.1)
            self.assertAlmostEqual(g['to']['x'], rr['anchor']['x'], delta=.1); self.assertAlmostEqual(g['to']['y'], rr['anchor']['y'], delta=.1)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {'S08-mast-trolley':mast, 'S08-beacon-trolley':reach}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S08-02', segmented_from='S08-01 exit at tick 390 of the same run (no further placement)',
            s08_01_exit_at_tick_390=launch, acquisition_reach=reach, caught_in_glide=dict(tick=beacon['tick'], player=players[beacon['tick']]),
            rope_points_max=2, west_wall_bounce_attached=dict(tick=wall['tick'], before=before, after=after),
            beacon_release=dict(tick=release['tick'], player=rel), clearance_over_s08_glide_drag=over, min_clearance_to_roof=roof,
            manifest_gaps_match_trace=True, contacts=touched)
        self.evidence.write('encounters/S08-02/result.json', result)
        print('PASS S08-02: from the S08-01 exit at tick', self.S08_01_TICKS, '; blue beacon trolley acquisition', round(reach['distance'],1), 'at tick',
              beacon['tick'], '(in the glide, vx', round(players[beacon['tick']]['speedX'],3), '); green west wall bounce (attached) at tick', wall['tick'],
              'vx', round(before['speedX'],3), '->', round(after['speedX'],3), '; released at', release['tick'], '; clear of the glide drag by', round(over,1),
              'and of the roof by', round(roof,1), '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_04_declared_falls_through_drag(self):
        out = {}
        trace, players, mech, result = self.run_s08('S08-01-short', self.S08_01_SHORT, 900, self.S07_V3_SETTLE,
                                                    density_until=self.SHORT_RELEASE, folder='falls')
        kinds = self.s08_kinds(mech)
        self.assertEqual(kinds[:2], [('acquisition','S08-mast-trolley'),('release','S08-mast-trolley')])
        self.assertFalse([k for k in kinds[2:] if k[1] != 'S07-exit-ledge'], kinds)
        out['S08-01-short'] = self.fall_s03(trace, players, mech, self.SHORT_RELEASE, 'S07-exit-ledge', self.CC.S07_EXIT_DRAG, self.S07_V3_SETTLE)
        out['S08-01-short']['s05_hoist_passage'] = self.hoist_passage(trace, players, self.SHORT_RELEASE, out['S08-01-short']['landing']['tick'])
        self.assertGreater(out['S08-01-short']['s05_hoist_passage']['clearance'], 20)
        out['S08-01-short']['players_at'] = players
        out['S08-01-short']['contacts'] = self.foreign_contacts(trace, 900, allowed=('S07-exit-ledge',))
        trace, players, mech, result = self.run_s08('S08-02-missed', self.S08_01_V3, 1200, self.GLIDE_SETTLE,
                                                    density_until=self.S08_01_TICKS, folder='falls')
        kinds = self.s08_kinds(mech)
        self.assertEqual(kinds[:4], [('acquisition','S08-mast-trolley'),('release','S08-mast-trolley'),('bounce','S08-roof'),
                                     ('mover-contact','S08-mast-trolley')])
        self.assertNotIn(('acquisition','S08-beacon-trolley'), kinds)
        self.assertFalse([k for k in kinds[4:] if k[1] != 'S08-glide-cap'], kinds)
        glide = max(x['tick'] for x in mech if x['type'] == 'mover-contact')
        out['S08-02-missed'] = self.fall_s03(trace, players, mech, glide, 'S08-glide-cap', self.GLIDE_DRAG, self.GLIDE_SETTLE)
        out['S08-02-missed']['glide_start'] = dict(tick=glide, meaning='last contact on the mast trolley top (slide-off)', player=players[glide])
        out['S08-02-missed']['players_at'] = players
        out['S08-02-missed']['contacts'] = self.foreign_contacts(trace, 1200, allowed=('S07-exit-ledge',))
        for k, v in out.items():
            fx, fy = self.S08_V3_FALL_POINTS[k]
            # Every drop starts at its apex above the declared fall point, and crosses the declared height inside its column.
            self.assertLessEqual(v['apex']['player']['y'], fy+1)
            ps = v.pop('players_at')
            cross = next(t for t in range(v['apex']['tick'], v['landing']['tick']) if ps[t]['y'] >= fy)
            self.assertLessEqual(abs(ps[cross]['x'] - fx), 20, (k, ps[cross]))
            v['declared_fall_point'] = (fx, fy)
            v['declared_point_crossing'] = dict(tick=cross, player=ps[cross])
        self.evidence.write('falls/result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S08 fall point is exercised from the labeled real S07 v3 exit pose. S08-01-short: the mast trolley released '
                 'at 240 (still inside S07-exit-drag) rises short of the S05 hoist, drops back through S07-exit-drag onto the green S07 exit '
                 'ledge, rebounds to at most half the drop (never back to the release height) and settles. S08-02-missed: with no beacon '
                 'press the glide off the mast trolley sinks into S08-glide-drag, which kills the drift, drops onto the green glide cap, '
                 'rebounds to at most half the drop and settles'))
        for k, v in out.items():
            print('PASS fall', k, ': apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on',
                  v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3),
                  '; settled from tick', v['settled_from_tick'])


class SummitV3CompleteChecks(SummitV3Checks):
    """Layout-v3 Summit Array S08-03/04, the summit finish and the S08 fall recovery (TASK-527), with real input.

    Same labeled-placement proof as SummitV3Checks: the start is the real S07 v3 exit settled pose (one labeled placement,
    then production trusted input and physics). S08-03/04 continue the S08-01/02 inputs of the same run, so they are
    segmented from the S08-02 exit (tick 565) and the S08-03 exit (tick 740), not placed. Not a continuous-completion claim.
    Shared by Task527Tests (the inherited S08-01/02 cases also run).
    """
    WALL_V3, ROOF_WEST_V3 = (4180,-13440), (1400,-13471)
    WALL_PRESS, WALL_RELEASE, ROOF_PRESS = 627, 672, 740
    # S08-03: the S08-02 flight east (roof rebound at 606) is caught by the green east wall far east (press 627, acquired
    # 634, 1416.8 reach) and pulled toward it; released at 672 short of the wall, the player rebounds off its leaning face
    # (683) back west nearly level, crosses the crown wall top and enters S08-crest-drag from the east, which stops it in the
    # crest pocket over the Crown (S08-03 exit at 740). S08-04: from the crest pocket, the far west end of the green roof is
    # pulled (press 740, 1411.4 reach) and held: the drag only lets the player crawl west out of the pocket, and as it leaves
    # the drag's west side it enters the summit finish region over the green summit pad, which completes the climb (809).
    S08_03_V3 = [(WALL_PRESS,'mousedown',*WALL_V3),(WALL_RELEASE,'mouseup',*WALL_V3)]
    S08_04_V3 = [(ROOF_PRESS,'mousedown',*ROOF_WEST_V3)]
    S08_ROUTE_V3 = SummitV3Checks.S08_01_V3+SummitV3Checks.S08_02_V3+S08_03_V3+S08_04_V3
    S08_03_TICKS, S08_04_TICKS, S08_FULL_TICKS = 740, 840, 900
    FINISH_BOX = dict(x=[2380,2735], y=[-13300,-13121])
    CREST_DRAG = dict(left=2750, right=2930, top=-13350, bottom=-12800)
    EAST_WALL = dict(left=4150, right=4222, top=-13470, bottom=-13150)
    SUMMIT_PAD = dict(left=2370, right=2750, top=-13110, bottom=-13080)
    CROWN_WALL, CROWN_DRAG = CrownV3Checks.CROWN_WALL, CrownV3Checks.CROWN_DRAG
    # Settled on the crown ledge inside S07-crown-drag (micro-bounces under 0.1).
    CROWN_REST = dict(x=[2740,2930], y=[-12045,-12025], speedX=[-.001,.001], speedY=[-.1,.1])
    # Declared S08-03/04 misses: the east wall released 15 ticks early (657) rebounds lower and slower into the crest pocket
    # and, with no roof press, sinks through S08-crest-drag and S07-crown-drag onto the green S07 crown ledge (fall.json);
    # the nominal S08-03 with no roof press sinks the same way.
    SHORT_WALL_RELEASE, REJOIN_TICK = 657, 1415
    S08_03_SHORT = SummitV3Checks.S08_01_V3+SummitV3Checks.S08_02_V3+[(WALL_PRESS,'mousedown',*WALL_V3),(SHORT_WALL_RELEASE,'mouseup',*WALL_V3)]
    S08_04_MISSED = SummitV3Checks.S08_01_V3+SummitV3Checks.S08_02_V3+S08_03_V3
    # Input-only rejoin from the crown ledge: the S05 hoist (over the pocket's west side) is pressed at 1415, when its
    # underside is in the throw line, and released at 1564: the swing west under it drops the player through S07-exit-drag
    # onto the S07 exit ledge (the S08 entrance), where it settles; the S08-01 mast trolley (1865, the period-matched phase of
    # the nominal 185) and the S08-02 beacon trolley (2070; aimed along the same line at a nearer point, on screen) replay
    # S08-01/02 into the flight east under the roof (S08-02 rejoined).
    HOIST_V3, BEACON_NEAR_V3 = (2650,-12445), (1100,-13334)
    HOIST_RELEASE, REJOIN_MAST_PRESS, REJOIN_BEACON_PRESS = 1564, 1865, 2070
    REJOIN_S08 = [(REJOIN_TICK,'mousedown',*HOIST_V3),(HOIST_RELEASE,'mouseup',*HOIST_V3),
                  (REJOIN_MAST_PRESS,'mousedown',*SummitV3Checks.MAST_V3),(REJOIN_MAST_PRESS+118,'mouseup',*SummitV3Checks.MAST_V3),
                  (REJOIN_BEACON_PRESS,'mousedown',*BEACON_NEAR_V3),(REJOIN_BEACON_PRESS+160,'mouseup',*BEACON_NEAR_V3)]
    FALL_S08, FALL_S08_TICKS = S08_03_SHORT+REJOIN_S08, 2250
    REJOIN_END = dict(x=[1550,1750], y=[-13360,-13290], speedX=[2.5,2.8], speedY=[-.5,-.25])

    def completion(self, trace, players):
        """The climb completes at one tick inside the finish region and stays completed and frozen."""
        done = [s['state']['simulation']['stats']['completed'] for s in trace['snapshots']]
        c = done.index(True)
        self.assertTrue(all(done[c:]) and not any(done[:c]))
        p = players[c]
        self.assertTrue(self.inside(p, self.FINISH_BOX), p)
        self.assertFalse(self.inside(players[c-1], self.FINISH_BOX) and done[c-1])
        self.assertTrue(all(q == p for q in players[c:]))
        return dict(completion_tick=c, player_at_completion=p, player_before=players[c-1], completed_before=False,
                    completed_through_end=True, frozen_after_completion=True, frozen_ticks=len(players)-1-c,
                    grappled_at_completion=trace['snapshots'][c]['state']['simulation']['grapple']['grappled'], finish_region=self.FINISH)

    def finish_once(self, state, ticks=150):
        """Restore the state one tick before completion and count the ending: CLIMB_UI.complete and level_completed."""
        page = self.open()
        return page.evaluate('''([s, n]) => {const out={lifecycle:[], completeCalls:0};
            const send=PLATFORM.sendLifecycle; PLATFORM.sendLifecycle=(e,d)=>{out.lifecycle.push(e); return send.call(PLATFORM,e,d)};
            const complete=CLIMB_UI.complete; CLIMB_UI.complete=function(){out.completeCalls++; return complete.apply(this,arguments)};
            GRAPPLE_OVER_TEST.begin('finish-once'); restoreClimbState(s);
            const p0={x:ninja.x,y:ninja.y}; let first=null; const rows=[];
            for (let i=1;i<=n;i++) {GRAPPLE_OVER_TEST.step(1); const c=floors[0].climbStats.completed;
                if (c && first===null) first=i; rows.push([i,c,ninja.x,ninja.y]);}
            GRAPPLE_OVER_TEST.finish('passed');
            return {...out, start:p0, firstCompletedStep:first, completedAtEnd:floors[0].climbStats.completed,
                levelCompleted:out.lifecycle.filter(e=>e==='level_completed').length, paused:menu.gamePaused,
                frozen:rows.filter(r=>r[1]).every(r=>r[2]===rows[first-1][2] && r[3]===rows[first-1][3]), steps:n}}''', [state, ticks])

    def s08_03_checks(self, trace, players, mech):
        """Flight east -> green east wall pull -> early release -> leaning-face rebound west -> crest pocket."""
        self.assertTrue(self.inside(players[self.S08_02_TICKS], self.S08_02_EXIT), players[self.S08_02_TICKS])
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S08-east-wall')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S08-east-wall')
        self.assertTrue(self.WALL_PRESS < acq['tick'] < release['tick'] == self.WALL_RELEASE)
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][acq['tick']:release['tick']+1]))
        rel = players[self.WALL_RELEASE]
        self.assertTrue(rel['speedX'] > 3 and rel['x'] < self.EAST_WALL['left'] - 100, rel)
        wall, before, after = next((e, e['before']['simulation']['player'], e['after']['simulation']['player']) for e in trace['events']
                                   if e['type']=='bounce' and e['contact']['elementId']=='S08-east-wall' and e['tick'] > release['tick'])
        # Released, not attached, at the wall; the leaning face turns the climb-free flight east into a nearly level rebound west.
        self.assertFalse(trace['snapshots'][wall['tick']]['state']['simulation']['grapple']['throwed'])
        self.assertTrue(before['speedX'] > 3 and after['speedX'] < -3 and after['speedY'] < before['speedY'] and abs(after['speedY']) < .6, (before, after))
        # The pull's outbound flight passes over the crest drag top and touches nothing.
        out_span = range(self.S08_02_TICKS, wall['tick'])
        over = min(self.CREST_DRAG['top'] - (players[t]['y'] + players[t]['radius']) for t in out_span
                   if self.CREST_DRAG['left'] - 11 <= players[t]['x'] <= self.CREST_DRAG['right'] + 11)
        self.assertGreater(over, 20)
        drag = self.CREST_DRAG
        entry = next(t for t in range(wall['tick'], self.S08_03_TICKS+1) if self.in_box(players[t], drag))
        self.assertTrue(all(self.in_box(players[t], drag) for t in range(entry, self.S08_03_TICKS+1)))
        b_in = players[entry-1]
        # Enters from the east side (over the crown wall top), the westward speed damped x0.8 per tick.
        self.assertTrue(b_in['x'] > drag['right'] and b_in['speedX'] < -3, b_in)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, entry+6) if abs(players[t]['speedX']) > 1e-9]
        crown = min(self.box_gap(self.CROWN_WALL, players[t]['x'], players[t]['y']) for t in range(wall['tick'], entry+1)) - b_in['radius']
        self.assertGreater(crown, 150)
        self.assertFalse([e for e in trace['events'] if e['type'] in ('contact','bounce') and wall['tick'] < e['tick'] <= self.S08_03_TICKS])
        self.assertTrue(self.inside(players[self.S08_03_TICKS], self.S08_03_EXIT), players[self.S08_03_TICKS])
        # Never in the finish region (nor completed) before S08-04.
        self.assertFalse([t for t in range(self.S08_03_TICKS+1) if self.inside(players[t], self.FINISH_BOX)])
        self.assertFalse(any(s['state']['simulation']['stats']['completed'] for s in trace['snapshots'][:self.S08_03_TICKS+1]))
        reach = self.reach_s05(players, mech, self.WALL_PRESS, 'S08-east-wall')
        return dict(east_wall_acquisition_reach=reach, east_wall_release=dict(tick=self.WALL_RELEASE, player=rel),
            east_wall_rebound=dict(tick=wall['tick'], before=before, after=after, attached=False, contact=wall['contact']),
            outbound_clearance_over_crest_drag=over, min_clearance_to_crown_wall=crown,
            crest_drag_entry=dict(tick=entry, before=b_in, at_entry=players[entry], side='east'), per_tick_vx_ratio_in_crest_drag=ratios,
            crest_pocket=dict(tick=self.S08_03_TICKS, player=players[self.S08_03_TICKS], box=self.S08_03_EXIT, inside_crest_drag=True),
            contacts_after_rebound=[], finish_region_entered=False)

    def s08_04_checks(self, trace, players, mech):
        """Roof pull from the crest pocket, crawl west out of the drag into the summit finish region; the ending once."""
        acq = next(e for e in mech if e['type']=='acquisition' and e['element']=='S08-roof' and e['tick'] >= self.ROOF_PRESS)
        self.assertLess(acq['rope'][0]['x'], 1500)
        out = self.completion(trace, players)
        c = out['completion_tick']
        drag = self.CREST_DRAG
        leave = next(t for t in range(acq['tick'], c+1) if not self.in_box(players[t], drag))
        # The drag only lets the player crawl: slow, westward, and it leaves through the drag's west side.
        crawl = [players[t]['speedX'] for t in range(acq['tick']+5, leave)]
        self.assertTrue(crawl and max(abs(v) for v in crawl) < .2 and players[leave]['x'] < drag['left'], (crawl[:3], players[leave]))
        self.assertTrue(self.FINISH['top'] < players[leave]['y'] < self.FINISH['bottom'], players[leave])
        self.assertTrue(all(len(s['state']['rope']) <= 2 for s in trace['snapshots'][acq['tick']:c+1]))
        self.assertFalse([e for e in trace['events'] if e['type'] in ('contact','bounce') and self.ROOF_PRESS <= e['tick'] <= c])
        pad = min(self.box_gap(self.SUMMIT_PAD, players[t]['x'], players[t]['y']) for t in range(acq['tick'], c+1)) - players[c]['radius']
        self.assertGreater(pad, 20)
        once = self.finish_once(trace['snapshots'][c-1]['state']['simulation'])
        self.assertEqual((once['firstCompletedStep'], once['completedAtEnd'], once['levelCompleted'], once['completeCalls'], once['frozen']), (1, True, 1, 1, True), once)
        return dict(roof_acquisition_reach=self.reach_s05(players, mech, self.ROOF_PRESS, 'S08-roof'), roof_anchor=acq['rope'][0],
            crawl=dict(ticks=[acq['tick'], leave], max_abs_speedX=max(abs(v) for v in crawl), left_crest_drag=dict(tick=leave, player=players[leave], side='west')),
            min_clearance_to_summit_pad=pad, contacts_from_press_to_completion=[], ending=out,
            ending_once=dict(restored_tick=c-1, steps=once['steps'], level_completed_events=once['levelCompleted'],
                             climb_complete_calls=once['completeCalls'], first_completed_step=once['firstCompletedStep'],
                             lifecycle=once['lifecycle'], frozen=once['frozen'], paused=once['paused']))

    def test_06_s08_03_nominal(self):
        trace, players, mech, result = self.run_s08('S08-03', self.S08_01_V3+self.S08_02_V3+self.S08_03_V3, self.S08_03_TICKS, self.S08_03_EXIT)
        self.assertEqual(self.s08_kinds(mech)[7:], [('bounce','S08-roof'),('acquisition','S08-east-wall'),('release','S08-east-wall'),
                                                     ('bounce','S08-east-wall')])
        out = self.s08_03_checks(trace, players, mech)
        touched = self.foreign_contacts(trace, self.S08_03_TICKS, allowed=('S07-exit-ledge',))
        result.update(encounter='S08-03', segmented_from='S08-02 exit at tick 565 of the same run (no further placement)',
            s08_02_exit_at_tick_565=players[self.S08_02_TICKS], exit_judged_at_tick=self.S08_03_TICKS, contacts=touched, **out)
        self.evidence.write('encounters/S08-03/result.json', result)
        r, wb = out['east_wall_acquisition_reach'], out['east_wall_rebound']
        print('PASS S08-03: from the S08-02 exit at tick 565; green east wall acquisition', round(r['distance'],1), 'at tick', r['acquisition_tick'],
              '; released', self.WALL_RELEASE, '; leaning-face rebound tick', wb['tick'], 'v', (round(wb['before']['speedX'],3), round(wb['before']['speedY'],3)),
              '->', (round(wb['after']['speedX'],3), round(wb['after']['speedY'],3)), '; enters S08-crest-drag at tick', out['crest_drag_entry']['tick'],
              'vx ratio', [round(x,3) for x in out['per_tick_vx_ratio_in_crest_drag'][:3]], '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in the crest pocket; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_07_s08_04_nominal(self):
        trace, players, mech, result = self.run_s08('S08-04', self.S08_ROUTE_V3, self.S08_04_TICKS, self.FINISH_BOX,
                                                    density_until=self.ROOF_PRESS+70)
        self.assertTrue(self.inside(players[self.S08_03_TICKS], self.S08_03_EXIT), players[self.S08_03_TICKS])
        self.assertEqual(self.s08_kinds(mech)[11:], [('acquisition','S08-roof')])
        out = self.s08_04_checks(trace, players, mech)
        touched = self.foreign_contacts(trace, self.S08_04_TICKS, allowed=('S07-exit-ledge',))
        result.update(encounter='S08-04', segmented_from='S08-03 exit (the crest pocket) at tick 740 of the same run (no further placement)',
            s08_03_exit_at_tick_740=players[self.S08_03_TICKS], contacts=touched, **out)
        self.evidence.write('encounters/S08-04/result.json', result)
        r, e = out['roof_acquisition_reach'], out['ending']
        print('PASS S08-04: from the crest pocket at tick 740; green roof (far west end) acquisition', round(r['distance'],1), 'at tick', r['acquisition_tick'],
              '; crawl max |vx|', round(out['crawl']['max_abs_speedX'],3), '; left S08-crest-drag (west) at tick', out['crawl']['left_crest_drag']['tick'],
              '; summit finish region entered and climb completed at tick', e['completion_tick'], 'at', {k:round(e['player_at_completion'][k],2) for k in ('x','y')},
              '; frozen', e['frozen_ticks'], 'ticks; ending once: level_completed', out['ending_once']['level_completed_events'], 'complete calls',
              out['ending_once']['climb_complete_calls'], '; summit pad clearance', round(out['min_clearance_to_summit_pad'],1),
              '; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_08_full_traversal(self):
        trace, players, mech, result = self.run_s08('S08-full', self.S08_ROUTE_V3, self.S08_FULL_TICKS, self.FINISH_BOX,
                                                    density_until=self.ROOF_PRESS+70)
        self.assertEqual([e['element'] for e in mech if e['type']=='acquisition'],
                         ['S08-mast-trolley','S08-beacon-trolley','S08-east-wall','S08-roof'])
        self.assertEqual([e['element'] for e in mech if e['type']=='bounce' and e['element'] != 'S07-exit-ledge'],
                         ['S08-roof','S08-west-wall','S08-roof','S08-east-wall'])
        exits = {}
        for name, tick, bounds in (('S08-01',self.S08_01_TICKS,self.S08_01_EXIT),('S08-02',self.S08_02_TICKS,self.S08_02_EXIT),
                                   ('S08-03',self.S08_03_TICKS,self.S08_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        self.s08_01_checks(trace, players, mech, result)
        s3 = self.s08_03_checks(trace, players, mech)
        s4 = self.s08_04_checks(trace, players, mech)
        exits['S08-04'] = dict(tick=s4['ending']['completion_tick'], player=s4['ending']['player_at_completion'], box=self.FINISH, finish=True)
        touched = self.foreign_contacts(trace, self.S08_FULL_TICKS, allowed=('S07-exit-ledge',))
        reaches = [self.reach_s05(players, mech, t, el) for t, el in ((self.MAST_PRESS,'S08-mast-trolley'),(self.BEACON_PRESS,'S08-beacon-trolley'),
                   (self.WALL_PRESS,'S08-east-wall'),(self.ROOF_PRESS,'S08-roof'))]
        m = self.report()['manifest']
        gaps = {g['id']:g for g in m['sections'][7]['gaps']}
        # The manifest gaps are the trace-measured press poses and anchors (rounded to 0.1).
        for gid, rr in zip(self.S08_V3_GAPS, reaches):
            g = gaps[gid]
            self.assertAlmostEqual(g['from']['x'], rr['player_at_press']['x'], delta=.1); self.assertAlmostEqual(g['from']['y'], rr['player_at_press']['y'], delta=.1)
            self.assertAlmostEqual(g['to']['x'], rr['anchor']['x'], delta=.1); self.assertAlmostEqual(g['to']['y'], rr['anchor']['y'], delta=.1)
        result.update(encounter='S08 full traversal', encounter_exits=exits, s08_03=s3, s08_04=s4, section_exit=dict(kind='summit finish region',
            region=self.FINISH, **s4['ending']), section_exit_reached=True, climb_completed_once=True, contacts=touched, reaches=reaches,
            manifest_gaps_match_trace=True)
        self.evidence.write('encounters/S08-full/result.json', result)
        if self.evidence.path('rules.json').exists():
            rules = json.loads(self.evidence.path('rules.json').read_text())
            rules['trace_measured_reach'] = {x['element']:x for x in reaches}
            self.evidence.write('rules.json', rules)
        print('PASS full S08: from the real S07 v3 exit pose; exits', {k:v['tick'] for k, v in exits.items()}, '; reaches',
              [round(x['distance'],1) for x in reaches], '; climb completed once at tick', s4['ending']['completion_tick'], 'inside the summit finish region',
              {k:round(s4['ending']['player_at_completion'][k],2) for k in ('x','y')}, '; frozen to', self.S08_FULL_TICKS, '; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_09_fall_through_drag_and_rejoin(self):
        trace, players, mech, result = self.run_s08('S08-03-short', self.FALL_S08, self.FALL_S08_TICKS, self.REJOIN_END,
                                                    density_until=self.SHORT_WALL_RELEASE, folder='falls')
        rel = players[self.SHORT_WALL_RELEASE]
        release = next(e for e in mech if e['type']=='release' and e['element']=='S08-east-wall')
        self.assertEqual(release['tick'], self.SHORT_WALL_RELEASE)
        ledge = [e for e in mech if e['type']=='bounce' and e['element']=='S07-crown-ledge' and self.SHORT_WALL_RELEASE < e['tick'] < self.REJOIN_TICK]
        self.assertTrue(ledge)
        land = ledge[0]['tick']
        # Between the release and the rejoin only the east wall (rebound) and the crown ledge are touched.
        self.assertEqual(sorted({e['element'] for e in mech if self.SHORT_WALL_RELEASE < e['tick'] < self.REJOIN_TICK}), ['S07-crown-ledge','S08-east-wall'])
        self.assertFalse([e for e in self.contacts(trace) if self.SHORT_WALL_RELEASE < e['tick'] < self.REJOIN_TICK])
        wall = next(e for e in mech if e['type']=='bounce' and e['element']=='S08-east-wall' and e['tick'] > self.SHORT_WALL_RELEASE)
        apex_tick = min(range(self.SHORT_WALL_RELEASE, land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        # S08-crest-drag: the rebound enters from the east; the westward speed is killed (vx x0.8 per tick), the sink kept.
        crest = [t for t in range(wall['tick'], land) if self.in_box(players[t], self.CREST_DRAG)]
        c_in, c_out = crest[0], crest[-1]
        self.assertEqual(crest, list(range(c_in, c_out+1)))
        c_before, c_after = players[c_in-1], players[c_out+1]
        self.assertTrue(c_before['speedX'] < -2 and c_before['x'] > self.CREST_DRAG['right'], c_before)
        self.assertLess(abs(c_after['speedX']), .01)
        hratio = [players[t+1]['speedX']/players[t]['speedX'] for t in range(c_in, c_in+6) if abs(players[t]['speedX']) > 1e-9]
        # S07-crown-drag, down to the crown ledge.
        drag = self.CROWN_DRAG
        ticks = [t for t in range(c_out+1, land+1) if self.in_box(players[t], drag)]
        entry, leave = ticks[0], ticks[-1]
        self.assertEqual(ticks, list(range(entry, land+1)))
        before = players[entry-1]
        self.assertFalse(self.in_box(before, drag)); self.assertGreater(before['speedY'], .5)
        vdamp = [players[t+1]['speedY']-players[t]['speedY']*.985 for t in range(entry, leave)][:8]
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_ledge = contact['before']['simulation']['player']
        self.assertLess(at_ledge['speedY'], before['speedY'])
        self.assertLessEqual(abs(at_ledge['speedX']), abs(before['speedX'])+1e-9)
        rest_y = ledge[0]['player']['y']
        fall_height = rest_y - apex['y']
        self.assertGreater(fall_height, 1000)
        fx, fy = self.S08_V3_FALL_POINTS['S08-03-short']
        self.assertLessEqual(apex['y'], fy+1)
        cross = next(t for t in range(apex_tick, land) if players[t]['y'] >= fy)
        self.assertLessEqual(abs(players[cross]['x']-fx), 18)
        column = [players[t]['x'] for t in range(cross, land+1)]
        self.assertTrue(self.CREST_DRAG['left']+10.8 < min(column) and max(column) < self.CREST_DRAG['right']-10.8, (min(column), max(column)))
        peaks = []
        for a, b in zip(ledge, ledge[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(p['peak_y'] > rel['y'] for p in peaks))
        # Settled on the green crown ledge inside S07-crown-drag before the rejoin press.
        window = players[self.REJOIN_TICK-50:self.REJOIN_TICK]
        self.assertTrue(all(self.inside(p, self.CROWN_REST) and self.in_box(p, drag) for p in window), [p for p in window if not self.inside(p, self.CROWN_REST)][:2])
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_TICK]
        self.assertEqual(len(rejoin_inputs), len(self.REJOIN_S08))
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after_rejoin = [e for e in mech if e['tick'] >= self.REJOIN_TICK]
        self.assertEqual([e['element'] for e in after_rejoin if e['type']=='acquisition'], ['S05-hoist','S08-mast-trolley','S08-beacon-trolley'])
        # The hoist swing drops the player through S07-exit-drag onto the S07 exit ledge (the S08 entrance), where it settles
        # before the period-matched S08-01 press; then S08-01 (roof rebound, trolley top) and S08-02 (west wall) are replayed.
        exit_ledge = next(e for e in mech if e['element']=='S07-exit-ledge' and e['type']=='bounce' and e['tick'] > self.HOIST_RELEASE)
        pocket = players[self.REJOIN_MAST_PRESS-50:self.REJOIN_MAST_PRESS+1]
        self.assertTrue(all(self.inside(p, self.S07_V3_SETTLE) and self.in_box(p, self.CC.S07_EXIT_DRAG) for p in pocket))
        self.assertLess(abs(players[self.REJOIN_MAST_PRESS]['x'] - 2608.9), 5)
        hoist = self.hoist_passage(trace, players, self.REJOIN_MAST_PRESS, self.REJOIN_MAST_PRESS+118)
        self.assertGreater(hoist['clearance'], 20)
        roof = next(e for e in mech if e['type']=='bounce' and e['element']=='S08-roof' and e['tick'] > self.REJOIN_MAST_PRESS)
        top = next(e for e in mech if e['type']=='mover-contact' and e['element']=='S08-mast-trolley' and e['tick'] > roof['tick'])
        beacon = next(e for e in mech if e['type']=='acquisition' and e['element']=='S08-beacon-trolley' and e['tick'] > top['tick'])
        west = next(e for e in mech if e['type']=='bounce' and e['element']=='S08-west-wall' and e['tick'] > beacon['tick'])
        self.assertGreater(west['player']['speedX'], 2)
        self.assertFalse(any(s['state']['simulation']['stats']['completed'] for s in trace['snapshots']))
        touched = self.foreign_contacts(trace, self.FALL_S08_TICKS, allowed=('S07-exit-ledge','S05-hoist'))
        fall = dict(scenario='naturally mistimed S08-03 release: the green east wall is released at tick %d instead of %d (15 ticks early); the '
                             'rebound is lower and slower, enters S08-crest-drag and, with no roof pull, drops physically; no relocation after the '
                             'labeled S07 v3 exit start placement' % (self.SHORT_WALL_RELEASE, self.WALL_RELEASE),
            release=dict(tick=self.SHORT_WALL_RELEASE, element='S08-east-wall', press_tick=self.WALL_PRESS,
                         nominal_release_tick=self.WALL_RELEASE, player=rel, release_height_y=rel['y']),
            east_wall_rebound=dict(tick=wall['tick'], player=wall['player']),
            fall_point=dict(id='S08-03-short', declared_x=fx, declared_y=fy, crossing=dict(tick=cross, player=players[cross]),
                            column_x_range=[min(column), max(column)], landing_x=at_ledge['x']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='crown ledge bounce rest y minus the highest point after the release (the release height)',
            drag_zones=[dict(id='S08-crest-drag', box=self.CREST_DRAG, entry_tick=c_in, exit_tick=c_out+1,
                    before=dict(tick=c_in-1, **{k:c_before[k] for k in ('x','y','speedX','speedY')}),
                    after=dict(tick=c_out+1, **{k:c_after[k] for k in ('x','y','speedX','speedY')}),
                    per_tick_vx_ratio=hratio, note='entered from the east: the westward speed is damped (vx x0.8 per tick); the sink continues straight down'),
                dict(id='S07-crown-drag', box=drag, entry_tick=entry, last_tick_inside_before_landing=leave,
                    before=dict(tick=entry-1, **{k:before[k] for k in ('x','y','speedX','speedY')}),
                    after=dict(tick=land, **{k:at_ledge[k] for k in ('x','y','speedX','speedY')},
                               note='player state just before the crown ledge bounce, after crossing the drag zone'),
                    vertical_damping_per_tick=0.985, vy_minus_damped_previous_vy_first_ticks=vdamp)],
            bouncer=dict(element='S07-crown-ledge', section='S07', route='S07 route bouncer: the green crown ledge under S07-crown-drag (the S07-02/04 '
                         'miss catch, TASK-523/524)', first_bounce_tick=land, rest_y=rest_y, inside='S07-crown-drag'),
            bounce_peaks=peaks[:8], bounce_count=len(peaks), first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            never_back_to_release_height=True,
            settled=dict(window=[self.REJOIN_TICK-50, self.REJOIN_TICK-1], box=self.CROWN_REST,
                max_abs_speedX=max(abs(p['speedX']) for p in window), max_abs_speedY=max(abs(p['speedY']) for p in window),
                y_range=[min(p['y'] for p in window), max(p['y'] for p in window)], inside_drag_zone='S07-crown-drag', on='S07-crown-ledge'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                start_tick=self.REJOIN_TICK, mechanics=[{k:e[k] for k in ('tick','type','element','player')} for e in after_rejoin
                           if e['type'] != 'contact' and e['element'] not in ('S07-crown-ledge','S07-exit-ledge')],
                s07_exit_ledge_landing=dict(tick=exit_ledge['tick'], player=exit_ledge['player']),
                s08_entrance_settled=dict(window=[self.REJOIN_MAST_PRESS-50, self.REJOIN_MAST_PRESS], box=self.S07_V3_SETTLE,
                    inside='S07-exit-drag', player_at_mast_press=players[self.REJOIN_MAST_PRESS]),
                s05_hoist_passage=hoist, roof_rebound=dict(tick=roof['tick'], player=roof['player']),
                trolley_top=dict(tick=top['tick'], player=top['player']), beacon_acquisition=dict(tick=beacon['tick'], player=beacon['player']),
                west_wall_rebound=dict(tick=west['tick'], player=west['player']), final=players[-1], end_box=self.REJOIN_END,
                encounter_rejoined='S08-01 (mast trolley from the S08 entrance on the S07 exit ledge, roof rebound, trolley top) and S08-02 '
                                   '(beacon trolley caught in the glide, green west wall rebound into the flight east under the roof, where S08-03 starts)'),
            contacts=touched, climb_completed=False)
        result.update(fall)
        self.evidence.write('falls/S08-03-short/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: east wall released', self.SHORT_WALL_RELEASE, '(nominal', self.WALL_RELEASE, ') at y', round(rel['y'],1), '; S08-crest-drag vx',
              round(c_before['speedX'],3), '->', round(c_after['speedX'],5), '; S07-crown-drag vx/vy', round(before['speedX'],4), round(before['speedY'],3), '->',
              round(at_ledge['speedX'],6), round(at_ledge['speedY'],3), '; crown ledge bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of',
              round(fall_height,1), '; settled at x', round(window[-1]['x'],1), '; input-only rejoin from tick', self.REJOIN_TICK, ': acquisitions',
              [e['element'] for e in after_rejoin if e['type']=='acquisition'], '; S07 exit ledge tick', exit_ledge['tick'], '; roof tick', roof['tick'],
              '; west wall tick', west['tick'], '; final', {k:round(players[-1][k],2) for k in ('x','y','speedX','speedY')})
        # The declared S08-04 miss: the nominal S08-03 with no roof press.
        trace, players, mech, result = self.run_s08('S08-04-missed', self.S08_04_MISSED, 1700, self.CROWN_REST,
                                                    density_until=self.S08_03_TICKS, folder='falls')
        self.assertNotIn('S08-roof', [e['element'] for e in mech if e['type']=='acquisition' and e['tick'] > self.WALL_PRESS])
        v = self.fall_s03(trace, players, mech, self.S08_03_TICKS, 'S07-crown-ledge', self.CROWN_DRAG, self.CROWN_REST)
        fx, fy = self.S08_V3_FALL_POINTS['S08-04-missed']
        self.assertLessEqual(v['apex']['player']['y'], fy+1)
        cross = next(t for t in range(v['apex']['tick'], v['landing']['tick']) if players[t]['y'] >= fy)
        self.assertLessEqual(abs(players[cross]['x'] - fx), 18, players[cross])
        self.assertTrue(all(self.in_box(players[t], self.CREST_DRAG) for t in range(self.S08_03_TICKS, cross+1)))
        self.assertFalse(any(s['state']['simulation']['stats']['completed'] for s in trace['snapshots']))
        v.update(declared_fall_point=(fx, fy), declared_point_crossing=dict(tick=cross, player=players[cross]),
                 reference_tick_meaning='S08-03 exit (the roof press tick of the nominal S08-04); no roof press follows',
                 contacts=self.foreign_contacts(trace, 1700, allowed=('S07-exit-ledge',)))
        out = {'S08-04-missed': v, 'S08-03-short': dict(declared_fall_point=self.S08_V3_FALL_POINTS['S08-03-short'], see='fall.json',
               drag_zones=['S08-crest-drag','S07-crown-drag'], landing=fall['bouncer'], first_rebound_over_drop=fall['first_peak_fraction'],
               settled=fall['settled'])}
        self.evidence.write('falls/s08_03_04_result.json', dict(self.proof, passed=True, falls=out,
            note='each declared S08-03/04 fall point is exercised from the labeled real S07 v3 exit pose; the player crosses the drag zones, '
                 'lands on the green S07 crown ledge, rebounds to at most half the drop (never back to the release height) and settles'))
        print('PASS fall S08-04-missed : apex', round(v['apex']['player']['y'],1), '; drag', v['drag_zone'], 'entry tick', v['drag_entry_tick'], '; lands on',
              v['landing']['element'], 'at tick', v['landing']['tick'], '; first rebound / drop', round(v['first_rebound_over_drop'],3), '; settled from tick', v['settled_from_tick'])


class Task544Tests(unittest.TestCase):
    """Recalibrate the TASK-503 families at 1080/1620; freeze the v3 gaps, extent and density cap."""
    import test_grapple_over_physics as physics
    attempt = physics.Task503Tests.attempt
    drag_pairs = physics.Task503Tests.drag_pairs
    judge = physics.Task503Tests.judge
    envelope = physics.Task503Tests.envelope
    del physics
    results, reach, flight = {}, {}, {}

    @classmethod
    def setUpClass(cls):
        import test_grapple_over_tools as task463
        cls.task463 = task463
        cls.evidence = EvidenceWriter('TASK-544')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.hashes = cls.current_hashes()
        cls.proof = dict(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
            text=True).strip(), source_hashes=cls.hashes, browser=cls.browser.version,
            viewport=task463.VIEWPORT, device_scale_factor=1, has_touch=True, hz=60, substeps=8, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    @staticmethod
    def current_hashes():
        from grapple_over_verify import hashes
        result = hashes()
        for path in ('tools/grapple_over_calibration.js', 'tools/test_grapple_over_physics.py'):
            result[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        return result

    def open(self):
        page = self.task463.Task461Tests.open(self)
        self.task463.install_recorder(page)
        page.add_script_tag(path=str(ROOT / 'tools/grapple_over_calibration.js'))
        return page

    def test_01_families_at_both_ranges(self):
        import test_grapple_over_physics as physics
        page = self.open()
        constants = page.evaluate('''() => ({gravity:GRAVITY,pull:grappleSpeed,
            throwSpeed:grapnelSpeed,cyclesPerTick,physicsStepMs,radius:ninja.radius,
            range:MODE_DEFINITIONS.grapple_over.acquisitionRadius,
            upgradedRange:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius,
            dragDamping:DRAG_ZONE_HORIZONTAL_DAMPING,scale:scale.grapple_over})''')
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())['modes']['classic']
        for key in ('gravity', 'pull', 'throwSpeed', 'cyclesPerTick', 'physicsStepMs'):
            self.assertEqual(constants[key], baseline['constants'][key])
        self.assertEqual((constants['range'], constants['upgradedRange'], constants['scale']), (1080, 1620, 0.375))
        v2 = json.loads((ROOT / 'artifacts/TASK-503/calibration.json').read_text())['measured_envelopes']['540']
        out = {}
        for rng, upgraded in TASK544_RANGES.items():
            out[rng] = {}
            for family in physics.TASK503_FAMILIES:
                runs = [self.attempt(page, family, upgraded, dt, aim) for dt, aim in
                        ((0, 0), (-3, 0), (3, 0), (0, -10.8), (0, 10.8))]
                runs.append(self.attempt(page, family, upgraded, negative=True))
                for r in runs:
                    self.assertEqual(r['range'], rng)
                    if family == 'drag_zone':
                        r['drag_pairs'] = self.drag_pairs(r, constants['dragDamping'])
                    self.judge(family, r)
                    print('MEASURE', rng, family, r['dt'], r['aim'], r['negative'], 'success=%s' % r['success'],
                          {k: round(r['rows'][100][k], 3) for k in ('x', 'y', 'speedX', 'speedY')},
                          'landing_tick=%d' % r['landing_contact']['tick'])
                    self.assertEqual(r['success'], not r['negative'], (rng, family, r['dt'], r['aim']))
                successes = [r for r in runs if r['success']]
                self.assertEqual(len(successes), 5)
                envelope = self.envelope(family, successes)
                envelope['differs_from_v2_540_envelope'] = sorted(k for k in v2[family] if envelope[k] != v2[family][k])
                print('PASS', rng, family, ': nominal + 4 variants; negative rejected; landing ticks',
                      envelope['landing_ticks'], 'v2 540 landing ticks', v2[family]['landing_ticks'],
                      'keys differing from TASK-503 540 envelope', envelope['differs_from_v2_540_envelope'])
                out[rng][family] = dict(runs=runs, envelope=envelope)
        self.__class__.results = dict(constants=constants, families=out)

    def test_02_gap_metric_reach(self):
        """Bisect the longest acquiring rope-to-anchor distance with trusted mouse input at 1080/1620."""
        page = self.open()
        trial = '''([d, upgraded]) => {
            const rect=(id,x,y,w,h)=>({id,x,y,role:'solid',points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
            const level=structuredClone(GRAPPLE_OVER_LEVEL);
            level.movers=[];
            level.elements=[rect('floor',-2000,1000,8000,60),rect('post',700+d,700,40,300)];
            level.encounters[0].elements=level.elements.map(e=>e.id);
            GRAPPLE_OVER_TEST.spawn({level,player:{x:700,y:1000-ninja.radius,speedX:0,speedY:0},
                camera:{x:700+d/2-innerWidth/2/scale.grapple_over,y:1000-innerHeight/2/scale.grapple_over}});
            floors[0].rangeUpgraded=upgraded;
            return GRAPPLE_OVER_TEST.client({x:700+d+20,y:1000-ninja.radius});
        }'''

        def shoot(d, upgraded):
            page.mouse.up()
            page.evaluate('GRAPPLE_OVER_TEST.attempts.length=0')
            page.evaluate("GRAPPLE_OVER_TEST.begin('reach')")
            p = page.evaluate(trial, [d, upgraded])
            self.assertTrue(0 <= p['x'] <= 1280 and 0 <= p['y'] <= 720, (d, p))
            page.mouse.move(p['x'], p['y'])
            page.mouse.down()
            page.evaluate('() => {for(let i=0;i<90 && !grapnel.isGrappled();i++) GRAPPLE_OVER_TEST.step(1)}')
            r = page.evaluate('''() => ({grappled:grapnel.isGrappled(),range:grappleOverAcquisitionRadius(),
                target:grapnel.isGrappled()?grapnel.pos[0][2].id:null,
                rope:grapnel.isGrappled()?Math.hypot(grapnel.pos[0][0]-ninja.x,grapnel.pos[0][1]-ninja.y):null})''')
            page.mouse.up()
            page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
            return r
        frozen = page.evaluate('LAYOUT_V3_GAP_TARGETS')
        v2 = page.evaluate('LAYOUT_V2_GAP_TARGETS')
        reach = {}
        for rng, upgraded in TASK544_RANGES.items():
            lo, hi = rng - 300.0, rng + 200.0
            first = shoot(lo, upgraded)
            self.assertTrue(first['grappled'])
            self.assertFalse(shoot(hi, upgraded)['grappled'])
            best, steps = first, 0
            while hi - lo > 0.05:
                mid = (lo + hi) / 2
                r = shoot(mid, upgraded)
                self.assertEqual(r['range'], rng)
                steps += 1
                if r['grappled']:
                    self.assertEqual(r['target'], 'post')
                    lo, best = mid, r
                else:
                    hi = mid
            measured = best['rope']
            self.assertAlmostEqual(measured, rng, delta=0.5)
            # Frozen v3 band: twice the v2 band, which must sit inside 85-90% of the measured reach
            # (upper end judged against the bisection bracket: true reach lies within measured + 0.05).
            v2_band = v2[str(rng // 2)]
            gap = [2 * v2_band[0], 2 * v2_band[1]]
            self.assertEqual(frozen[str(rng)], gap)
            fraction = [gap[0] / measured, gap[1] / measured]
            self.assertTrue(0.85 * measured <= gap[0] < gap[1] <= 0.90 * (measured + 0.05), fraction)
            band = [shoot(d, upgraded) for d in gap]
            self.assertTrue(all(b['grappled'] and b['target'] == 'post' for b in band))
            self.assertFalse(shoot(hi + 1, upgraded)['grappled'])
            reach[rng] = dict(measured_reach=measured, last_acquiring_post_face_distance=lo,
                first_missing_post_face_distance=hi, bisection_steps=steps, gap_targets=gap,
                gap_targets_as_fraction=fraction, v2_gap_targets=v2_band,
                v3_over_v2_gap_ratio=[gap[0] / v2_band[0], gap[1] / v2_band[1]],
                target_band_acquires=[dict(distance=d, rope=b['rope']) for d, b in zip(gap, band)])
            print('PASS reach %d: measured reach %.3f; v3 gap targets %s acquire (%.2f%%-%.2f%% of reach); v3/v2 %s'
                  % (rng, measured, gap, 100 * fraction[0], 100 * fraction[1], reach[rng]['v3_over_v2_gap_ratio']))
        self.__class__.reach = reach

    def test_03_flight_time_and_density_cap(self):
        """Free fall from rest across a v2 vs a v3 band height, stepped by the production physics."""
        page = self.open()
        r = page.evaluate('''() => {
            const fall = h => {
                GRAPPLE_OVER_TEST.attempts.length=0;
                GRAPPLE_OVER_TEST.begin('flight');
                const rect=(id,x,y,w,h)=>({id,x,y,role:'solid',points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
                const level=structuredClone(GRAPPLE_OVER_LEVEL);
                level.movers=[];
                level.elements=[rect('floor',-2000,h,8000,60)];
                level.encounters[0].elements=['floor'];
                GRAPPLE_OVER_TEST.spawn({level,player:{x:700,y:-ninja.radius,speedX:0,speedY:0},camera:{x:0,y:-300}});
                let t=0;
                while(t<2000 && !(ninja.speedY===0 && Math.abs(ninja.y-(h-ninja.radius))<1e-5)) {GRAPPLE_OVER_TEST.step(1);t++}
                GRAPPLE_OVER_TEST.finish('measured');
                return {height:h,ticks:t,landed_y:ninja.y,speedY:ninja.speedY};
            };
            const out={v2:fall(3*540), v3:fall(LAYOUT_V3_EXTENT.bandHeight)};
            return Object.assign(out,{v2Cap:LAYOUT_V2_DENSITY_CAP_TICKS,v3Cap:LAYOUT_V3_DENSITY_CAP_TICKS,
                extent:LAYOUT_V3_EXTENT,v2Extent:{ascent:GRAPPLE_OVER_MOUNTAIN.ascent,
                horizontalEnvelope:GRAPPLE_OVER_MOUNTAIN.horizontalEnvelope,bandHeight:3*540,
                encountersPerSection:GRAPPLE_OVER_MOUNTAIN.encounters.length/GRAPPLE_OVER_MOUNTAIN.sections.length}});
        }''')
        self.assertTrue(r['v2']['ticks'] < r['v3']['ticks'] < 2000, r)
        ratio = r['v3']['ticks'] / r['v2']['ticks']
        self.assertAlmostEqual(ratio, 2 ** 0.5, delta=0.02)
        self.assertEqual(r['v2Cap'], 180)
        self.assertEqual(r['v3Cap'], round(180 * ratio))
        v2e, v3e = r['v2Extent'], r['extent']
        self.assertEqual(v2e, dict(ascent=12960, horizontalEnvelope=6480, bandHeight=1620, encountersPerSection=4))
        self.assertEqual(v3e, dict(ascent=25920, horizontalEnvelope=12960, bandHeight=3240, encountersPerSection=4))
        for k in ('ascent', 'horizontalEnvelope', 'bandHeight'):
            self.assertEqual(v3e[k], 2 * v2e[k])
        r['flight_time_ratio'] = ratio
        self.__class__.flight = r
        print('PASS flight: free fall %d ticks over %d vs %d ticks over %d, ratio %.4f; density cap 180 x ratio = %.2f -> %d'
              % (r['v2']['ticks'], r['v2']['height'], r['v3']['ticks'], r['v3']['height'], ratio, 180 * ratio, r['v3Cap']))
        print('PASS extent: v3 %s = 2 x v2 %s' % (json.dumps(v3e, sort_keys=True), json.dumps(v2e, sort_keys=True)))

    def test_04_write_and_audit_calibration(self):
        import test_grapple_over_physics as physics
        self.assertTrue(self.results and self.reach and self.flight)
        fams = self.results['families']
        envelopes = {str(rng): {f: v['envelope'] for f, v in fs.items()} for rng, fs in fams.items()}
        runs = {str(rng): {f: [dict(dt=r['dt'], aim=r['aim'], negative=r['negative'], success=r['success'],
                range=r['range'], exit={k: r['rows'][100][k] for k in ('tick', 'x', 'y', 'speedX', 'speedY')},
                landing_tick=r['landing_contact']['tick'], trusted_inputs=len(r['inputs']),
                event_types=sorted(set(e['type'] for e in r['events']))) for r in v['runs']]
                for f, v in fs.items()} for rng, fs in fams.items()}
        current = self.current_hashes()
        self.assertEqual(current, self.hashes)
        f = self.flight
        data = dict(self.proof, constants=self.results['constants'], ranges=[1080, 1620],
            families_list=list(physics.TASK503_FAMILIES), exit_tick=100, success_exit_regions=physics.TASK503_BOXES,
            proof_convention='nominal + dt -3/+3 + aim -10.8/+10.8 must succeed, negative control must fail',
            measured_envelopes=envelopes, families=runs,
            measured_reach={str(k): v['measured_reach'] for k, v in self.reach.items()},
            gap_metric=dict(name='v3 mandatory gap', version=3, frozen=True,
                targets={str(k): v['gap_targets'] for k, v in self.reach.items()},
                rule='twice the TASK-503 v2 band; each endpoint inside 85-90% of measured reach and acquiring',
                measured={str(k): v for k, v in self.reach.items()}),
            extent=dict(frozen=f['extent'], v2=f['v2Extent'], ratio=2),
            flight_time=dict(definition='ticks of free fall from rest across one band height to a floor contact',
                v2=f['v2'], v3=f['v3'], ratio=f['flight_time_ratio']),
            density_cap=dict(frozen_ticks=f['v3Cap'], v2_ticks=f['v2Cap'], ratio=f['flight_time_ratio'],
                rule='longest allowed nominal-trace stretch without an acquisition, bounce or mover contact'),
            v2_reference='artifacts/TASK-503/calibration.json', all_families_pass=True)
        self.evidence.write('calibration.json', data)
        disk = json.loads(self.evidence.path('calibration.json').read_text())
        self.assertEqual(disk['source_hashes'], self.current_hashes())
        for rng in ('1080', '1620'):
            self.assertEqual(sorted(disk['families'][rng]), sorted(physics.TASK503_FAMILIES))
            for name, rows in disk['families'][rng].items():
                self.assertEqual([r['success'] for r in rows], [True] * 5 + [False])
                self.assertTrue(all(r['range'] == int(rng) for r in rows))
        print('PASS audit: 7 families x 2 ranges, 70 successful traces, 14 negative controls; reach %s; '
              'gap targets %s; extent %s; density cap %d; source hashes match'
              % (disk['measured_reach'], disk['gap_metric']['targets'], disk['extent']['frozen'],
                 disk['density_cap']['frozen_ticks']))


# TASK-546 layout-v3 fixture. Every section is now a real v3 section (TASK-526 rebuilt the last v1 one, S08), so the
# fixture is the current manifest itself and the mutations below are applied to the real v3 S08 (range 1620):
# green bouncers and two blue movers, no solid exceptions, a 3240 band, gaps in the 1620 band and drag zones under its
# miss points.
V3_FIXTURE = '''d => d'''
# One mutation per v3 rule (plus the exception and below-bouncer variants) and its exact thrown error.
V3_NEGATIVE = {
    'staticGrayPad': ("d=>{d.geometry.elements.find(e=>e.id==='S08-roof').role='solid'}",
                      'LayoutV3GraySolid: S08.S08-roof', ['graySolid']),
    'solidException': ("d=>{d.sections[7].solidExceptions=[{element:'S08-glide-cap',kind:'rest-pad',reason:'gray pad'}]}",
                       'LayoutV3GraySolid: S08.solidExceptions', ['graySolid']),
    'gapOutOfBand': ("d=>{const g=d.sections[7].gaps[0]; g.to={x:g.from.x,y:g.from.y-0.95*1620}}",
                     'LayoutV3GapBand: S08.gaps.S08-01-trolley', ['gapBand']),
    'fallWithoutDrag': ("d=>{d.sections[7].fallPoints.push({id:'exit-miss',encounter:'S08-04',x:5300,y:-11600})}",
                        'LayoutV3DragUnderFall: S08.fallPoints.exit-miss', ['dragUnderFall']),
    'dragBelowBouncer': ("d=>{d.geometry.elements.find(e=>e.id==='S08-glide-drag').y=-12990}",
                         'LayoutV3DragUnderFall: S08.fallPoints.S08-02-missed', ['dragUnderFall', 'strayDrag']),
    'strayDrag': ("d=>{d.geometry.elements.push({id:'S08-stray-drag',x:300,y:-9000,role:'drag',grapplable:false,"
                  "points:[{x:0,y:0},{x:200,y:0},{x:200,y:80},{x:0,y:80}]})}",
                  'LayoutV3StrayDrag: S08.S08-stray-drag', ['strayDrag']),
    'wrongBandHeight': ("d=>{d.sections[7].band.top=d.sections[7].band.bottom-1620}",
                        'LayoutV3Extent: S08.band', ['extent']),
}
V3_RULE_CODES = {'graySolid': 'LayoutV3GraySolid', 'moverCoverage': 'LayoutV2MoverCoverage',
                 'direction': 'LayoutV2Direction', 'gapBand': 'LayoutV3GapBand',
                 'dragUnderFall': 'LayoutV3DragUnderFall', 'strayDrag': 'LayoutV3StrayDrag',
                 'extent': 'LayoutV3Extent'}


# Sections rebuilt as layout v3 (TASK-547: S01 .. TASK-523: S07, TASK-526: S08); the fixture is the real S08.
V3_REBUILT = ['S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08']
V3_FIXTURE_SECTION = 'S08'


class SummitV3ToleranceChecks(CrownV3ToleranceChecks):
    """Layout-v3 Summit Array (S08) tolerance on desktop 1280x720 and touch 844x390 (TASK-528).

    Proof kind (as TASK-526/527): the real S07 v3 exit settled pose (the v3 S07 route run from the labeled real S06 v3
    exit pose, itself the end of the TASK-521 S06-full chain from one base-start real-input S01..S04 v3 run, TASK-524
    S07-full) is restored once as a labeled initial placement (initial_snapshot); production trusted mouse/touch input and
    physics run from there. An attempt on encounter k replays the S08 route up to k: the encounter's inputs carry the
    variant, the earlier encounters keep their TASK-526/527 nominal inputs. S08-01..03 end in flight or in the crest pocket,
    so they are judged at their mountain.js exit boxes (position at the nominal exit tick 390/565/740); S08-04 at the
    summit finish region (the climb completes there and the player is frozen, judged at tick 840). S08-04 holds the roof to
    the finish (no release), so its timing variant shifts the roof press. check_s08_v3_mechanics requires the encounter's
    own mechanic, the S08 anchors in route order and no fall onto an S01-S07 element or an S08 fall bouncer. The HUD probe
    reads the UI boxes the game draws (LAYOUT_PROBE) at every nominal press. No earlier Task528Tests exists (the v1 S08
    suites Task486-490 judge the superseded v1 geometry), so there is no v2 suite to map.
    """
    SC, SX = SummitV3Checks, SummitV3CompleteChecks
    # The S07-exit start chain (SummitV3Checks.s07_v3_exit) reads the completed S07 route from CC.
    CC = CX = CrownV3CompleteChecks
    SEGMENTS = [SC.S08_01_V3, SC.S08_02_V3, SX.S08_03_V3, SX.S08_04_V3]
    # Index of the timed input in each encounter's segment: the release, except S08-04 (the held roof press).
    TIMING_INDEX = (1, 1, 1, 0)
    V3_ENCOUNTERS = [('S08-01','blue mast trolley pulled up out of the S07 exit pocket past the S05 hoist, release into the green roof (rise turned into a drop) onto the moving trolley top and a glide west',0,SC.S08_01_TICKS),
                     ('S08-02','blue beacon trolley caught in the glide, attached swing turned east by the green west wall, release into a flight east under the roof',SC.S08_01_TICKS,SC.S08_02_TICKS),
                     ('S08-03','green east wall caught in the flight east, released short of it, leaning-face rebound west into the S08-crest-drag pocket over the Crown',SC.S08_02_TICKS,SX.S08_03_TICKS),
                     ('S08-04','far west end of the green roof caught from the crest pocket and held: crawl west out of the drag into the summit finish region (climb completed)',SX.S08_03_TICKS,None)]
    S08_TICKS = SX.S08_04_TICKS
    STRICT = {'S08-01':SC.S08_01_EXIT, 'S08-02':SC.S08_02_EXIT, 'S08-03':SX.S08_03_EXIT}
    # Mistimed releases, one per encounter, no further input afterwards: (encounter, release tick replacing the nominal one,
    # nominal release tick (None: S08-04 holds the roof to the finish), ticks, declared fall point or None, landing bouncer).
    # S08-01: the mast trolley released at 240 inside S07-exit-drag (S08-01-short). S08-02: the beacon released 80 ticks early,
    # before the west wall: the flight west ricochets off it (a side glance) and drops east through S07-exit-drag onto the
    # S07 exit ledge. S08-03: the east wall released 15 ticks early (S08-03-short). S08-04: the roof released 20 ticks after
    # its catch, still in the crest pocket: the player sinks through S08-crest-drag and S07-crown-drag onto the S07 crown
    # ledge (the S08-04-missed column and bouncer).
    MISTIMED = [('S08-01',SC.SHORT_RELEASE,SC.MAST_RELEASE,1100,'S08-01-short','S07-exit-ledge'),
                ('S08-02',470,SC.BEACON_RELEASE,1200,None,'S07-exit-ledge'),
                ('S08-03',SX.SHORT_WALL_RELEASE,SX.WALL_RELEASE,1500,'S08-03-short','S07-crown-ledge'),
                ('S08-04',760,None,1300,'S08-04-missed','S07-crown-ledge')]
    UNDECLARED = {'S08-02':'undeclared S08-02 line: the beacon trolley released before the west wall, the flight west glances off '
                           'the wall and drops east through S07-exit-drag onto the green S07 exit ledge (the S08 entrance)'}
    V3_MOVERS = SC.S08_V3_MOVERS
    ANCHOR_IDS = dict(zip(('S08-01','S08-02','S08-03','S08-04'), SC.S08_V3_ANCHORS))
    HUD_FINDING = ('No HUD obstruction found: every S08 anchor is drawn clear of the HUD text rows and the pause button at its '
                   'press on both viewports (no S08 geometry moved for the HUD).')
    S07_V3_SETTLE, START_LABEL = SC.S07_V3_SETTLE, SC.START_LABEL
    S08_V3_ROUTE_ELEMENTS, S08_PLAYER_CLEARANCE, S08_LINE_CLEARANCE = SC.S08_V3_ROUTE_ELEMENTS, SC.S08_PLAYER_CLEARANCE, SC.S08_LINE_CLEARANCE
    S08_PLAYER_CLEARANCE_BY = SC.S08_PLAYER_CLEARANCE_BY
    s07_v3_exit = SC.s07_v3_exit

    def exits(self):
        """Per encounter: (ticks, judged exit bounds, meaning), from the runtime manifest."""
        enc = {e['id']:e for e in self.report()['manifest']['encounters'][28:32]}
        out = {}
        for name, _, _, tick in self.V3_ENCOUNTERS:
            if tick:
                b = enc[name]['exit']
                out[name] = (tick, dict(x=[b['left'],b['right']], y=[b['top'],b['bottom']]),
                             f'inside the mountain.js {name} exit box at the nominal exit tick {tick}')
            else:
                out[name] = (self.S08_TICKS, self.SX.FINISH_BOX,
                             'inside the summit finish region with the climb completed (S08 section exit) at tick %d' % self.S08_TICKS)
        return out

    def variant_plan(self, index, delta=0, shift=0):
        """Nominal S08 route up to encounter `index`, with the variant on that encounter (timed input TIMING_INDEX)."""
        plan = []
        for k, segment in enumerate(self.SEGMENTS[:index+1]):
            for i, (t, e, x, y) in enumerate(segment):
                if k == index:
                    t += delta if i == self.TIMING_INDEX[k] else 0
                    x += shift
                plan.append((t, e, x, y))
        return plan

    # The S08-03-short line rebounds off the east wall's leaning face (TASK-527) into the crest pocket.
    LEANING_FACES = ('S08-east-wall',)

    def fall_segment(self, k):
        """S08-04 has no nominal release: its mistimed release follows the roof press."""
        segment = self.SEGMENTS[k]
        return segment if len(segment) > 1 else segment+[(None, 'mouseup')+tuple(segment[0][2:])]

    def density_v3(self, trace, name, start, end):
        """As FoundationsV3ToleranceChecks.density_v3; the recorder reports mover contacts without an element id, so a
        contact point on an S08 mover's travel envelope (the landing on the mast trolley top) counts as a mover contact."""
        m = self.report()['manifest']
        travel = {v['element']:v for v in m['geometry']['movers']}
        boxes = {e['id']:self.bounds_v3(e, travel[e['id']]) for e in m['geometry']['elements'] if e['id'] in self.V3_MOVERS}
        marks = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] == 'acquisition': element = e['after']['rope'][0]['id']
            if e['type'] == 'contact' and element is None:
                element = next((k for k, b in boxes.items() if b['left']-1 <= e['contact']['x'] <= b['right']+1
                                and b['top']-1 <= e['contact']['y'] <= b['bottom']+1), None)
            if e['type'] in ('acquisition','bounce') or (e['type']=='contact' and element in self.V3_MOVERS):
                if start <= e['tick'] <= end and (not marks or marks[-1]['tick'] != e['tick']):
                    marks.append(dict(tick=e['tick'], type='mover contact' if e['type']=='contact' else e['type'], element=element))
        points = [start]+[x['tick'] for x in marks]+[end]
        gaps = [b-a for a, b in zip(points, points[1:])]
        i = gaps.index(max(gaps))
        return dict(trace=name, window=[start, end], interactions=marks, max_gap=max(gaps),
                    longest_gap=[points[i], points[i+1]], cap=self.DENSITY_CAP)

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s08_v3_mechanics
        start = self.s07_v3_exit()
        self.assertTrue(self.inside(start['player'], self.S07_V3_SETTLE), start['player'])
        exits = self.exits()
        source = hashes()
        suite = dict(section='S08', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='isolated: one labeled initial placement (initial_snapshot) = the real S07 v3 exit settled pose (the v3 S07 route '
                       'run from the labeled real S06 v3 exit pose, itself the end of the S04/S05/S06 chain from a base-start real-input '
                       'S01..S04 v3 run; encounters/S04-exit-start .. S07-exit-start), then production trusted mouse/touch input and '
                       'physics; an attempt on encounter k carries the variant on k and the TASK-526/527 nominal inputs on S08-01..k-1',
            initial_placement=type(self).v3_s07_start_proof, browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exits={n: dict(ticks=t, box=b, meaning=w) for n, (t, b, w) in exits.items()},
            mechanics_check='tools/grapple_over_verify.py check_s08_v3_mechanics',
            nominal_note='every nominal press aims at its anchor at a fixed world point (TASK-526/527), so desktop and touch run the same '
                         'route; every anchor is drawn clear of the HUD text and the pause button at its press (hud-probe.json)',
            pause_button_client_rects={str(k): v for k, v in self.PAUSE_BUTTON.items()},
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            hud_probe='hud-probe.json',
            critical_inputs={r[0]: dict(timing_index=self.TIMING_INDEX[k], aim_indices=list(range(len(self.SEGMENTS[k]))), tangent=(1,0),
                                        mechanic=r[1], inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal, clips = [], {}, {}
        for k, (name, mechanic, begin, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            ticks, bounds, meaning = exits[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), ticks, bounds, device, snapshot=start)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s08_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s08_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(self.clear(targets), (label, targets))
                        if exit_tick:
                            self.assertTrue(self.inside(players[exit_tick], self.STRICT[name]), (label, players[exit_tick]))
                            end = exit_tick
                        else:
                            end = mechanics['encounter']['completion_tick']
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', begin, end)
                        clips[label] = (trace, m['metadata']['viewport'], prefix, mechanics)
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=self.TIMING_INDEX[k],
                        aim_input_indices=list(range(len(self.SEGMENTS[k]))), timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        intended_exit=dict(ticks=ticks, box=bounds, meaning=meaning),
                        outcome=f'{name} exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), 'completed at', mechanics['encounter']['completion_tick'], flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(artifacts/TASK-544/calibration.json density_cap.frozen_ticks = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','mover contact (a contact point on an S08 mover travel envelope: the landing on the mast trolley top)'],
            cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal S08 run (0/390/565/740) to its manifest exit tick '
                   '(390/565/740) or, for S08-04, the climb completion in the summit finish region',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(start, exits['S08-04'])
        self.hud_probe(clips)
        self.assertEqual(failures, [])
        print('PASS S08 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-roof-press negative control fails the finish')

    NEGATIVE_TICKS = 1100

    def negative_control(self, start, exit):
        from grapple_over_verify import hashes, check_s08_v3_mechanics
        # Named omission: the S08-04 roof press left out; same placement, physics and S08-01..03 inputs as every S08-04 attempt.
        ticks, bounds, meaning = exit
        plan = self.variant_plan(3)[:6]
        m = self.make_input(plan, self.NEGATIVE_TICKS, bounds, snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s08_v3_mechanics('S08-04', trace, required=False)
        landed = [b for b in mechanics['bounces'] if b['tick'] > self.SX.S08_03_TICKS]
        finish = [t for t, p in enumerate(players) if self.inside(p, self.SX.FINISH_BOX)]
        self.evidence.write('negative-control.json', dict(name='omitted roof pull: S08-04 S08-roof press left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=dict(ticks=self.NEGATIVE_TICKS, box=bounds, meaning=meaning), unchanged_physics=True, source_hashes=hashes(),
            proof_kind='same labeled S07-exit placement, real mouse input, same S08-01..03 inputs as the S08-04 attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step, bounces_after_crest_pocket=landed,
            completed=mechanics['encounter']['completion_tick'] is not None, finish_region_ticks=finish, final_player=players[-1],
            scope='Without the roof pull the player in the crest pocket sinks through S08-crest-drag and S07-crown-drag '
                  '(first bouncer %s) and never reaches the summit finish region.' % (landed[0]['element'] if landed else 'none')))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S08-roof', mechanics['acquisitions'])
        self.assertIsNone(mechanics['encounter']['completion_tick'])
        self.assertEqual(finish, [])
        self.assertTrue(landed and landed[0]['element'] == 'S07-crown-ledge', landed)
        self.assertLess(step, 60)
        print('PASS negative control: omitted roof pull; reason', reason[:80], '; bounces after the crest pocket',
              [(b['element'], b['tick']) for b in landed][:4], '; final', (round(players[-1]['x'],1), round(players[-1]['y'],1)))

    FALL_SECTION_INDEX, FALL_ZONE_PREFIXES = 7, ('S01-','S02-','S03-','S04-','S05-','S06-','S07-','S08-')
    FALL_PROOF = 'labeled S07-exit placement, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation'

    def fall_start(self):
        return self.s07_v3_exit()

    def section_mechanics(self, name, trace, required=True):
        from grapple_over_verify import check_s08_v3_mechanics
        return check_s08_v3_mechanics(name, trace, required)


class Task546Tests(unittest.TestCase):
    """Layout-v3 design-rule validator: designVersion 3 opt-in with rule-specific failure codes."""
    task_id = 'TASK-546'
    open = V1Task465.open
    test_03_source_hashes = V1Task465.test_03_source_hashes

    @classmethod
    def setUpClass(cls):
        V1Task465.setUpClass.__func__(cls)
        for name in ('tools/test_grapple_over_physics.py', 'tools/test_grapple_over_level.py'):
            cls.proof['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.evidence.log('HASHES+ '+json.dumps(cls.proof['source_hashes'], sort_keys=True))

    def test_01_current_manifest_and_v3_fixture(self):
        page = self.open()
        r = page.evaluate('''fixture => {
            const current=layoutV2Report(GRAPPLE_OVER_MOUNTAIN); loadMountainLevel()
            const d=eval(fixture)(structuredClone(GRAPPLE_OVER_MOUNTAIN)), world=loadMountainLevel(d)
            return {current, fixture:layoutV2Report(d), codes:LAYOUT_V3_RULES, loaded:world.level.elements.length,
                targets:LAYOUT_V3_GAP_TARGETS, extent:LAYOUT_V3_EXTENT, columnRadius:LAYOUT_V3_FALL_COLUMN_RADIUS}
        }''', V3_FIXTURE)
        self.assertEqual(r['codes'], V3_RULE_CODES)
        cur = r['current']
        self.assertEqual([s['id'] for s in cur['sections']], [f'S{i:02}' for i in range(1, 9)])
        # Sections rebuilt for layout v3 (S01 from TASK-547 .. S08 from TASK-526) are judged by the v3 rules.
        rebuilt = list(V3_REBUILT)
        self.assertEqual(cur['v3'], rebuilt)
        self.assertFalse(cur['failed'])
        for s in cur['sections']:
            self.assertFalse(s['failed'], s)
            if s['id'] in rebuilt: continue
            self.assertIn(s['designVersion'], (1, 2), s)
            self.assertNotIn('graySolid', s.get('rules', {}), s)
        fx = r['fixture']
        self.assertEqual(fx['v3'], sorted(set(rebuilt) | {V3_FIXTURE_SECTION}))
        self.assertFalse(fx['failed'])
        s6 = next(s for s in fx['sections'] if s['id'] == V3_FIXTURE_SECTION)
        self.assertEqual(sorted(s6['rules']), sorted(V3_RULE_CODES))
        for name, rule in s6['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        rules = s6['rules']
        self.assertEqual(s6['range'], 1620)
        self.assertEqual(rules['gapBand']['measured']['target'], [1378, 1458])
        for g in rules['gapBand']['measured']['gaps']:
            self.assertTrue(1378 <= g['distance'] <= 1458, g)
        self.assertEqual(rules['graySolid']['measured']['staticSolids'], [])
        self.assertEqual(sorted(rules['graySolid']['measured']['movers']), ['S08-beacon-trolley', 'S08-mast-trolley'])
        fall = rules['dragUnderFall']['measured']['fallPoints'][1]
        self.assertEqual(fall['dragZones'], ['S08-glide-drag'])
        self.assertEqual(fall['firstBouncer'], 'S08-glide-cap')
        # TASK-527 completed S08: the crest drag zone sits under the S08-03/04 miss points.
        self.assertEqual(rules['strayDrag']['measured']['dragZones'], [dict(id='S08-glide-drag', fallPoints=['S08-02-missed']),
                                                                       dict(id='S08-crest-drag', fallPoints=['S08-03-short','S08-04-missed'])])
        self.assertEqual(rules['extent']['measured']['bandHeight'], 3240)
        self.assertEqual(rules['moverCoverage']['measured']['count'], 2)
        self.assertEqual(rules['direction']['measured']['actual'], 'left')
        # v1/v2 sections in the fixture are still reported, never judged by v3 rules.
        for s in fx['sections']:
            if s['id'] != V3_FIXTURE_SECTION and s['id'] not in rebuilt:
                self.assertIn(s['designVersion'], (1, 2))
                self.assertNotIn('graySolid', s.get('rules', {}))
        self.evidence.write('rules.json', dict(self.proof, rules=[dict(rule=k, code=v) for k, v in V3_RULE_CODES.items()],
            gap_targets=r['targets'], extent=r['extent'], fall_column_radius=r['columnRadius'],
            current_manifest=dict(v1=[s['id'] for s in cur['sections'] if s['designVersion'] == 1],
                v2=cur['v2'], v3=cur['v3'], failed=cur['failed'],
                sections=[dict(id=s['id'], designVersion=s['designVersion'], failed=s['failed'],
                               judged_by_v3=s['id'] in rebuilt) for s in cur['sections']]),
            v3_fixture_section=s6, v3_fixture_loaded_elements=r['loaded'],
            current_no_v3_failure=True, fixture_all_v3_rules_passed=True))
        print('PASS rules: current manifest v1 %s, v2 %s, v3 %s, no failure; v3 fixture %s passes %s'
              % ([s['id'] for s in cur['sections'] if s['designVersion'] == 1], cur['v2'], cur['v3'], V3_FIXTURE_SECTION, sorted(rules)))

    def test_02_each_rule_rejects_its_mutation(self):
        page = self.open()
        cases = {k: v[0] for k, v in V3_NEGATIVE.items()}
        r = page.evaluate('''([fixture,cases]) => Object.entries(cases).map(([name,mutate])=>{
            const d=eval(fixture)(structuredClone(GRAPPLE_OVER_MOUNTAIN)); eval(mutate)(d)
            const s=layoutV2Report(d).sections.find(s=>s.id==='S08')
            let error=null; try {validateMountainManifest(d)} catch(e){error=e.message}
            return {name,mutation:mutate,error,failedRules:Object.entries(s.rules).filter(([,v])=>!v.passed).map(([k])=>k),
                errors:s.errors}
        })''', [V3_FIXTURE, cases])
        self.assertEqual([c['name'] for c in r], list(V3_NEGATIVE))
        for c in r:
            _, error, failed = V3_NEGATIVE[c['name']]
            self.assertEqual(c['error'], error, c)
            self.assertEqual(c['failedRules'], failed, c)
        self.assertEqual({c['error'].split(':')[0] for c in r},
                         {'LayoutV3GraySolid', 'LayoutV3GapBand', 'LayoutV3DragUnderFall', 'LayoutV3StrayDrag', 'LayoutV3Extent'})
        self.evidence.write('negative.json', dict(self.proof, fixture=V3_FIXTURE, cases=r,
            all_rejected_with_rule_specific_code=True))
        for c in r:
            print(f"PASS negative {c['name']}: rejected {c['error']}")


class Task547Tests(FoundationsV3Checks, unittest.TestCase):
    """Layout-v3 Foundations opening (S01-01/02): green bouncers and blue movers at the 1080 range."""
    task_id = 'TASK-547'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_04_source_hashes = V1Task465.test_03_source_hashes


class Task548Tests(FoundationsV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Foundations S01-03/04, exit pad settle and drag-zone fall recovery at the 1080 range."""
    task_id = 'TASK-548'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_06_source_hashes = V1Task465.test_03_source_hashes


class Task549Tests(FoundationsV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Foundations (S01) mechanics and tolerance: 40 real-input attempts, drag-zone falls."""
    task_id = 'TASK-549'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task550Tests(SwitchbackV3Checks, unittest.TestCase):
    """Layout-v3 Switchback S02-01/02 from the real S01 v3 exit settled pose, with real input."""
    task_id = 'TASK-550'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_04_source_hashes = V1Task465.test_03_source_hashes


class Task551Tests(SwitchbackV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Switchback S02-03/04, exit-ledge settle and drag-zone fall recovery at the 1080 range."""
    task_id = 'TASK-551'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_06_source_hashes = V1Task465.test_03_source_hashes


class Task552Tests(SwitchbackV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Switchback (S02) mechanics and tolerance: 40 real-input attempts, drag-zone falls."""
    task_id = 'TASK-552'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task553Tests(ViaductV3Checks, unittest.TestCase):
    """Layout-v3 Broken Viaduct S03-01/02 from the real S02 v3 exit settled pose, with real input."""
    task_id = 'TASK-553'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task554Tests(ViaductV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Broken Viaduct complete (S03-01..04, exit and fall recovery) from the real S02 v3 exit settled pose, with real input."""
    task_id = 'TASK-554'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_09_source_hashes = V1Task465.test_03_source_hashes


class Task555Tests(ViaductV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Broken Viaduct (S03) mechanics and tolerance: 40 real-input attempts, drag-zone falls."""
    task_id = 'TASK-555'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task556Tests(DeflectorV3Checks, unittest.TestCase):
    """Layout-v3 Deflector Works S04-01/02 from the real S03 v3 exit settled pose, with real input."""
    task_id = 'TASK-556'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task515Tests(DeflectorV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Deflector Works complete (S04-01..04, exit and fall recovery) from the real S03 v3 exit settled pose, with real input.

    No earlier Task515Tests exists (layout-v2 S04-03/04 were never built), so there is no v2 suite to map.
    test_01-04 are the shared DeflectorV3Checks cases (geometry and rules now judge the completed section);
    test_05-08 are the S04-03, S04-04, full-traversal and fall/rejoin cases.
    """
    task_id = 'TASK-515'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_09_source_hashes = V1Task465.test_03_source_hashes


class Task516Tests(DeflectorV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Deflector Works (S04) mechanics and tolerance: 40 real-input attempts, HUD probe, drag-zone falls."""
    task_id = 'TASK-516'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task517Tests(GalleriesV3Checks, unittest.TestCase):
    """Layout-v3 Cable Galleries S05-01/02 from the real S04 v3 exit settled pose, with real input.

    The v1 S05 suites Task477-479 now run these v3 cases (TASK-533, LEGACY_V3_UPPER_MAPPING).
    """
    task_id = 'TASK-517'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_06_source_hashes = V1Task465.test_03_source_hashes


class Task518Tests(GalleriesV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Cable Galleries complete (S05-01..04, exit and fall recovery) from the real S04 v3 exit settled pose, with real input.

    test_01-05 are the shared GalleriesV3Checks cases (geometry and rules now judge the completed section);
    test_06-10 are the S05-03, S05-04, full-traversal, fall/rejoin and 1080 negative-control cases.
    """
    task_id = 'TASK-518'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_11_source_hashes = V1Task465.test_03_source_hashes


class Task519Tests(GalleriesV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Cable Galleries (S05) mechanics and tolerance: 40 real-input attempts, HUD probe, drag-zone falls."""
    task_id = 'TASK-519'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task520Tests(LiftworksV3Checks, unittest.TestCase):
    """Layout-v3 Liftworks S06-01/02 from the real S05 v3 exit settled pose, with real input.

    The v1 S06 suites Task480-482 now run these v3 cases (TASK-533, LEGACY_V3_UPPER_MAPPING).
    """
    task_id = 'TASK-520'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task521Tests(LiftworksV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Liftworks S06-03/04, section exit and fall recovery from the real S05 v3 exit settled pose, with real input."""
    task_id = 'TASK-521'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_10_source_hashes = V1Task465.test_03_source_hashes


class Task522Tests(LiftworksV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Liftworks (S06) mechanics and tolerance: 40 real-input attempts, HUD probe, drag-zone falls."""
    task_id = 'TASK-522'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task523Tests(CrownV3Checks, unittest.TestCase):
    """Layout-v3 Exposed Crown S07-01/02 from the real S06 v3 exit settled pose, with real input.

    The v1 S07 suites Task483-485 now run these v3 cases (TASK-533, LEGACY_V3_UPPER_MAPPING).
    """
    task_id = 'TASK-523'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task524Tests(CrownV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Exposed Crown S07-03/04, section exit and fall recovery from the real S06 v3 exit settled pose, with real input."""
    task_id = 'TASK-524'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_10_source_hashes = V1Task465.test_03_source_hashes


class Task525Tests(CrownV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Exposed Crown (S07) mechanics and tolerance: 40 real-input attempts, HUD probe, drag-zone falls."""
    task_id = 'TASK-525'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task526Tests(SummitV3Checks, unittest.TestCase):
    """Layout-v3 Summit Array S08-01/02 from the real S07 v3 exit settled pose, with real input.

    The v1 S08 suites Task486-488 now run these v3 cases, and the v1 joins Task489/490 run the v3 joins
    Task529/530 (TASK-533, LEGACY_V3_UPPER_MAPPING).
    """
    task_id = 'TASK-526'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task527Tests(SummitV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Summit Array S08-03/04, the summit finish and the S08 fall recovery from the real S07 v3 exit settled pose, with real input."""
    task_id = 'TASK-527'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task528Tests(SummitV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Summit Array (S08) mechanics and tolerance: 40 real-input attempts, HUD probe, drag-zone falls."""
    task_id = 'TASK-528'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


# TASK-532: the v1 S01-S04 suites re-specced for layout v3. Each legacy class keeps its intent
# (opening geometry/mechanics, complete section with fall recovery, tolerance) and runs the same
# cases as its layout-v3 counterpart, with task-local evidence under its own task id.
LEGACY_V3_MAPPING = {
    'Task465Tests': ('FoundationsV3Checks', 'Task547Tests', 'S01 opening: geometry and S01-01/02 real-input replays'),
    'Task466Tests': ('FoundationsV3CompleteChecks', 'Task548Tests', 'S01 complete: S01-03/04, exit and fall recovery'),
    'Task467Tests': ('FoundationsV3ToleranceChecks', 'Task549Tests', 'S01 tolerance matrix and negative control'),
    'Task468Tests': ('SwitchbackV3Checks', 'Task550Tests', 'S02 opening: geometry and S02-01/02 replays'),
    'Task469Tests': ('SwitchbackV3CompleteChecks', 'Task551Tests', 'S02 complete: S02-03/04, exit and fall recovery'),
    'Task470Tests': ('SwitchbackV3ToleranceChecks', 'Task552Tests', 'S02 tolerance matrix and recovery'),
    'Task471Tests': ('ViaductV3Checks', 'Task553Tests', 'S03 opening: geometry and S03-01/02 replays'),
    'Task472Tests': ('ViaductV3CompleteChecks', 'Task554Tests', 'S03 complete: S03-03/04, exit and fall recovery'),
    'Task473Tests': ('ViaductV3ToleranceChecks', 'Task555Tests', 'S03 tolerance matrix and recovery'),
    'Task474Tests': ('DeflectorV3Checks', 'Task556Tests', 'S04 opening: geometry and S04-01/02 bounce replays'),
    'Task475Tests': ('DeflectorV3CompleteChecks', 'Task515Tests', 'S04 complete: S04-03/04 bounces, exit and recovery'),
    'Task476Tests': ('DeflectorV3ToleranceChecks', 'Task516Tests', 'S04 tolerance matrix and recovery'),
}


class Task465Tests(FoundationsV3Checks, unittest.TestCase):
    """S01 opening, re-specced by TASK-532 from layout v1 to layout v3 (same cases as Task547Tests).

    v1 test_01_geometry (gray solid loading bay) -> test_01 v3 rules, zero gray solids, 918-972 gaps;
    v1 test_02_real_input_replays (crane beam onto the rest ledge) -> test_02/03 S01-01 hoist and S01-02
    lift + green deflector; v1 test_03_source_hashes -> test_04_source_hashes.
    """
    task_id = 'TASK-465'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_04_source_hashes = V1Task465.test_03_source_hashes


class Task466Tests(FoundationsV3CompleteChecks, unittest.TestCase):
    """S01 complete, re-specced by TASK-532 from layout v1 to layout v3 (same cases as Task548Tests).

    v1 geometry/mouse route/touch lower-anchor recovery -> v3 geometry, S01-03/04 nominal, full traversal
    and the drag-zone fall with its physical rejoin; source hashes kept.
    """
    task_id = 'TASK-466'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_06_source_hashes = V1Task465.test_03_source_hashes


class Task467Tests(FoundationsV3ToleranceChecks, unittest.TestCase):
    """S01 tolerance, re-specced by TASK-532: the v1 5-variant x 2-viewport matrix and outside-range
    negative control -> the v3 40-attempt matrix, negative control and drag-zone falls (Task549Tests)."""
    task_id = 'TASK-467'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task468Tests(SwitchbackV3Checks, unittest.TestCase):
    """S02 opening, re-specced by TASK-532: v1 geometry, nominal encounters and failure recovery ->
    v3 S02-01/02 from the real S01 v3 exit settled pose (same cases as Task550Tests)."""
    task_id = 'TASK-468'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_04_source_hashes = V1Task465.test_03_source_hashes


class Task469Tests(SwitchbackV3CompleteChecks, unittest.TestCase):
    """S02 complete, re-specced by TASK-532: v1 completed shaft (mouse/touch) and local miss recovery ->
    v3 S02-03/04, exit-ledge settle and drag-zone fall recovery (same cases as Task551Tests)."""
    task_id = 'TASK-469'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_06_source_hashes = V1Task465.test_03_source_hashes


class Task470Tests(SwitchbackV3ToleranceChecks, unittest.TestCase):
    """S02 tolerance, re-specced by TASK-532: v1 isolated-entrance matrix and recovery -> the v3
    40-attempt matrix and drag-zone falls (same cases as Task552Tests)."""
    task_id = 'TASK-470'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task471Tests(ViaductV3Checks, unittest.TestCase):
    """S03 opening, re-specced by TASK-532: v1 geometry, nominal + shortcut and failure recovery ->
    v3 S03-01/02 from the real S02 v3 exit settled pose (same cases as Task553Tests)."""
    task_id = 'TASK-471'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task472Tests(ViaductV3CompleteChecks, unittest.TestCase):
    """S03 complete, re-specced by TASK-532: v1 complete viaduct routes -> v3 S03-01..04, exit and
    fall recovery (same cases as Task554Tests)."""
    task_id = 'TASK-472'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_09_source_hashes = V1Task465.test_03_source_hashes


class Task473Tests(ViaductV3ToleranceChecks, unittest.TestCase):
    """S03 tolerance, re-specced by TASK-532: v1 matrix, recovery and shortcut -> the v3 40-attempt
    matrix and drag-zone falls (same cases as Task555Tests)."""
    task_id = 'TASK-473'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task474Tests(DeflectorV3Checks, unittest.TestCase):
    """S04 opening, re-specced by TASK-532: v1 connected ascent and physical misses -> v3 S04-01/02
    from the real S03 v3 exit settled pose (same cases as Task556Tests)."""
    task_id = 'TASK-474'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_05_source_hashes = V1Task465.test_03_source_hashes


class Task475Tests(DeflectorV3CompleteChecks, unittest.TestCase):
    """S04 complete, re-specced by TASK-532: v1 reflections, double-bounce exit and local miss recovery
    -> v3 S04-01..04, exit and fall/rejoin (same cases as Task515Tests)."""
    task_id = 'TASK-475'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    open = V1Task465.open
    test_09_source_hashes = V1Task465.test_03_source_hashes


class Task476Tests(DeflectorV3ToleranceChecks, unittest.TestCase):
    """S04 tolerance, re-specced by TASK-532: v1 isolated matrix, recovery and scoped geometry -> the
    v3 40-attempt matrix, HUD probe and drag-zone falls (same cases as Task516Tests)."""
    task_id = 'TASK-476'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = V1Task465.test_03_source_hashes


class Task532Tests(unittest.TestCase):
    """Legacy Task465-Task476 re-spec: mapping, and the separate per-class run logs under legacy/."""
    task_id = 'TASK-532'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)

    @staticmethod
    def case_names(cls):
        # A fresh loader: -k Task532Tests sets name patterns on the default loader.
        return sorted(unittest.TestLoader().getTestCaseNames(cls))

    def test_01_mapping(self):
        module = globals()
        rows = {}
        for legacy, (checks, counterpart, intent) in LEGACY_V3_MAPPING.items():
            cls, mixin, peer = module[legacy], module[checks], module[counterpart]
            self.assertTrue(issubclass(cls, mixin) and issubclass(cls, unittest.TestCase), legacy)
            self.assertTrue(issubclass(peer, mixin), counterpart)
            names = self.case_names(cls)
            self.assertEqual(names, self.case_names(peer), legacy)
            self.assertGreater(len(names), 1)
            # Every case comes from the v3 checks except the unchanged source-hash case.
            for name in names:
                self.assertTrue(hasattr(mixin, name) or name.endswith('_source_hashes'), (legacy, name))
            rows[legacy] = dict(task='TASK-'+legacy[4:7], v3_checks=checks, v3_counterpart=counterpart,
                v3_counterpart_task='TASK-'+counterpart[4:7], intent=intent, cases=names,
                section='S0%d' % ((int(legacy[4:7])-465)//3+1))
        self.evidence.write('mapping.json', dict(revision=self.proof['revision'], classes=rows,
            verify_checks={'check_s0%d_mechanics' % n: 'check_s0%d_v3_mechanics' % n for n in range(1, 5)}))
        print('PASS mapping: 12 legacy classes run their v3 checks; case lists equal the v3 counterparts')

    def test_02_legacy_logs(self):
        import re
        for legacy in LEGACY_V3_MAPPING:
            task = 'TASK-'+legacy[4:7]
            log = self.evidence.path(f'legacy/{task}.log')
            self.assertTrue(log.exists(), log)
            text = log.read_text()
            names = self.case_names(globals()[legacy])
            ran = re.findall(r'^Ran (\d+) tests? ', text, re.M)
            self.assertEqual(ran, [str(len(names))], task)
            self.assertRegex(text, r'\nOK\n', task)
            self.assertNotRegex(text, r'skipped|^(FAIL|ERROR):|expected failures', task)
            self.assertEqual(text.rstrip().splitlines()[-1], 'exit 0', task)
            for name in names:
                self.assertIn(f'{name} (test_grapple_over_sections.{legacy}', text)
            configs = [l for l in self.evidence.path(f'legacy/{task}/commands.log').read_text().splitlines()
                       if l.startswith('CONFIG ')]
            config = json.loads(configs[-1][7:])
            # Committing the ticket moves HEAD, so the run's revision only has to be HEAD or an
            # ancestor of it; the source hashes are the guard that the tested files are unchanged.
            ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', config['revision'], 'HEAD'],
                                      cwd=ROOT, capture_output=True)
            self.assertEqual(ancestor.returncode, 0, (task, config['revision'], 'not an ancestor of HEAD'))
            self.assertEqual(config['source_hashes'], self.proof['source_hashes'], task)
            print(f'PASS {legacy}: {len(names)} cases ok, exit 0, no skips, source hashes match')

    def test_03_source_hashes(self):
        V1Task465.test_03_source_hashes(self)


# TASK-533: the v1 S05-S08 suites (sections file) and the two v1 joins (integration file) re-specced
# for layout v3. Each legacy class subclasses its layout-v3 counterpart, so it runs exactly the
# counterpart's cases (same geometry, mechanics, tolerance, recovery and source-hash checks) with
# task-local evidence under its own task id. (file, v3 checks, v3 counterpart, kept intent)
LEGACY_V3_UPPER_MAPPING = {
    'Task477Tests': ('sections', 'GalleriesV3Checks', 'Task517Tests', 'S05 opening: geometry and S05-01/02 corner-wrap replays'),
    'Task478Tests': ('sections', 'GalleriesV3CompleteChecks', 'Task518Tests', 'S05 complete: S05-03/04 transfers, exit and fall recovery'),
    'Task479Tests': ('sections', 'GalleriesV3ToleranceChecks', 'Task519Tests', 'S05 tolerance matrix, HUD probe and drag-zone falls'),
    'Task480Tests': ('sections', 'LiftworksV3Checks', 'Task520Tests', 'S06 opening: moving-anchor acquisition and S06-01/02 replays'),
    'Task481Tests': ('sections', 'LiftworksV3CompleteChecks', 'Task521Tests', 'S06 complete: S06-03/04 transfers, exit and fall recovery'),
    'Task482Tests': ('sections', 'LiftworksV3ToleranceChecks', 'Task522Tests', 'S06 tolerance matrix, HUD probe and drag-zone falls'),
    'Task483Tests': ('sections', 'CrownV3Checks', 'Task523Tests', 'S07 opening: rotor hazard and S07-01/02 replays'),
    'Task484Tests': ('sections', 'CrownV3CompleteChecks', 'Task524Tests', 'S07 complete: S07-03/04, exit and fall recovery'),
    'Task485Tests': ('sections', 'CrownV3ToleranceChecks', 'Task525Tests', 'S07 tolerance matrix, HUD probe and drag-zone falls'),
    'Task486Tests': ('sections', 'SummitV3Checks', 'Task526Tests', 'S08 opening: brake and bounce-transfer S08-01/02 replays'),
    'Task487Tests': ('sections', 'SummitV3CompleteChecks', 'Task527Tests', 'S08 finish: S08-03/04, summit landing and S08 fall recovery'),
    'Task488Tests': ('sections', 'SummitV3ToleranceChecks', 'Task528Tests', 'S08 tolerance matrix, HUD probe and drag-zone falls'),
    'Task489Tests': ('integration', None, 'Task529Tests', 'lower join: base -> S01..S04 exit continuous, cross-section fall and rejoin'),
    'Task490Tests': ('integration', None, 'Task530Tests', 'upper join: S04-exit fixture -> S05..S08 summit finish continuous'),
}


class Task477Tests(Task517Tests):
    """S05 opening, re-specced by TASK-533: v1 corner wraps (projecting girder / deep overhang), connected
    ascent and falls -> v3 S05-01/02 from the real S04 v3 exit settled pose (same cases as Task517Tests)."""
    task_id = 'TASK-477'


class Task478Tests(Task518Tests):
    """S05 complete, re-specced by TASK-533: v1 transfers, recessed ceiling and departure -> v3 S05-03/04,
    full traversal, fall/rejoin and the 1080 negative control (same cases as Task518Tests)."""
    task_id = 'TASK-478'


class Task479Tests(Task519Tests):
    """S05 tolerance, re-specced by TASK-533: the v1 isolated-start matrix -> the v3 40-attempt matrix,
    HUD probe and drag-zone falls (same cases as Task519Tests)."""
    task_id = 'TASK-479'


class Task480Tests(Task520Tests):
    """S06 opening, re-specced by TASK-533: v1 moving attachment and physical recovery -> v3 S06-01/02
    from the real S05 v3 exit settled pose (same cases as Task520Tests)."""
    task_id = 'TASK-480'


class Task481Tests(Task521Tests):
    """S06 complete, re-specced by TASK-533: v1 phase release, alternating transfer and fall -> v3
    S06-03/04, exit and fall recovery (same cases as Task521Tests)."""
    task_id = 'TASK-481'


class Task482Tests(Task522Tests):
    """S06 tolerance, re-specced by TASK-533: the v1 isolated-start matrix -> the v3 40-attempt matrix,
    HUD probe and drag-zone falls (same cases as Task522Tests)."""
    task_id = 'TASK-482'


class Task483Tests(Task523Tests):
    """S07 opening, re-specced by TASK-533: v1 timed rotor, displacement catch and jib cut -> v3 S07-01/02
    from the real S06 v3 exit settled pose (same cases as Task523Tests)."""
    task_id = 'TASK-483'


class Task484Tests(Task524Tests):
    """S07 complete, re-specced by TASK-533: v1 exposed launch, lower recovery and deep fall -> v3
    S07-03/04, exit and fall recovery (same cases as Task524Tests)."""
    task_id = 'TASK-484'


class Task485Tests(Task525Tests):
    """S07 tolerance, re-specced by TASK-533: the v1 isolated-start matrix -> the v3 40-attempt matrix,
    HUD probe and drag-zone falls (same cases as Task525Tests)."""
    task_id = 'TASK-485'


class Task486Tests(Task526Tests):
    """S08 opening, re-specced by TASK-533: v1 opposing-anchor brake and angled-bounce transfer -> v3
    S08-01/02 from the real S07 v3 exit settled pose (same cases as Task526Tests)."""
    task_id = 'TASK-486'


class Task487Tests(Task527Tests):
    """S08 finish, re-specced by TASK-533: v1 moving overhang, final landing and summit exit -> v3 S08-03/04,
    summit finish and S08 fall recovery (same cases as Task527Tests)."""
    task_id = 'TASK-487'


class Task488Tests(Task528Tests):
    """S08 tolerance, re-specced by TASK-533: the v1 isolated-start matrix -> the v3 40-attempt matrix,
    HUD probe and drag-zone falls (same cases as Task528Tests)."""
    task_id = 'TASK-488'


class Task533Tests(unittest.TestCase):
    """Legacy Task477-Task490 re-spec: mapping, and the separate per-class run logs under legacy/."""
    task_id = 'TASK-533'
    setUpClass = classmethod(V1Task465.setUpClass.__func__)
    case_names = staticmethod(Task532Tests.case_names)

    @staticmethod
    def module(kind):
        import test_grapple_over_integration
        return globals() if kind == 'sections' else vars(test_grapple_over_integration)

    def test_01_mapping(self):
        rows = {}
        self.assertEqual(sorted(LEGACY_V3_UPPER_MAPPING), ['Task%dTests' % n for n in range(477, 491)])
        for legacy, (kind, checks, counterpart, intent) in LEGACY_V3_UPPER_MAPPING.items():
            module = self.module(kind)
            cls, peer = module[legacy], module[counterpart]
            # The legacy class is its v3 counterpart under its own task id, nothing added or dropped.
            self.assertEqual(cls.__bases__, (peer,), legacy)
            self.assertEqual(cls.task_id, 'TASK-'+legacy[4:7])
            self.assertNotEqual(cls.task_id, peer.task_id)
            self.assertEqual({k for k in vars(cls) if not k.startswith('_')}, {'task_id'}, legacy)
            if checks:
                self.assertTrue(issubclass(peer, globals()[checks]), counterpart)
            names = self.case_names(cls)
            self.assertEqual(names, self.case_names(peer), legacy)
            self.assertGreater(len(names), 1)
            rows[legacy] = dict(task=cls.task_id, file=f'tools/test_grapple_over_{kind}.py', v3_checks=checks,
                v3_counterpart=counterpart, v3_counterpart_task=peer.task_id, intent=intent, cases=names,
                section='S0%d' % ((int(legacy[4:7])-477)//3+5) if kind == 'sections' else
                ('S01-S04 join' if legacy == 'Task489Tests' else 'S05-S08 join'))
        import grapple_over_verify as V
        for n in range(5, 9):
            self.assertIn(f'check_s0{n}_v3_mechanics', getattr(V, f'check_s0{n}_mechanics').__code__.co_names)
        self.evidence.write('mapping.json', dict(revision=self.proof['revision'], classes=rows,
            verify_checks={'check_s0%d_mechanics' % n: 'check_s0%d_v3_mechanics' % n for n in range(1, 9)}))
        print('PASS mapping: 14 legacy classes are their v3 counterparts; case lists equal the v3 counterparts')

    def test_02_legacy_logs(self):
        import re
        for legacy, (kind, _, counterpart, _) in LEGACY_V3_UPPER_MAPPING.items():
            task = 'TASK-'+legacy[4:7]
            log = self.evidence.path(f'legacy/{task}.log')
            self.assertTrue(log.exists(), log)
            text = log.read_text()
            names = self.case_names(self.module(kind)[legacy])
            self.assertEqual(re.findall(r'^Ran (\d+) tests? ', text, re.M), [str(len(names))], task)
            self.assertRegex(text, r'\nOK\n', task)
            self.assertNotRegex(text, r'skipped|^(FAIL|ERROR):|expected failures', task)
            self.assertEqual(text.rstrip().splitlines()[-1], 'exit 0', task)
            for name in names:
                self.assertIn(f'{name} (test_grapple_over_{kind}.{legacy}', text)
            configs = [l for l in self.evidence.path(f'legacy/{task}/commands.log').read_text().splitlines()
                       if l.startswith('CONFIG ')]
            config = json.loads(configs[-1][7:])
            ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', config['revision'], 'HEAD'],
                                      cwd=ROOT, capture_output=True)
            self.assertEqual(ancestor.returncode, 0, (task, config['revision'], 'not an ancestor of HEAD'))
            # Every file the run hashed (runtime, level, harness, both test files) is unchanged.
            self.assertIn(f'tools/test_grapple_over_{kind}.py', config['source_hashes'], task)
            for path, digest in config['source_hashes'].items():
                self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, (task, path))
            print(f'PASS {legacy}: {len(names)} cases ok, exit 0, no skips, source hashes match')

    def test_03_source_hashes(self):
        V1Task465.test_03_source_hashes(self)
