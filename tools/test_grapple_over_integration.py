"""Continuous mountain proofs from the base, driven only by trusted input events."""
import hashlib
import json
import math
import shutil
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter
from grapple_over_support import state_hash


def holds(plan, start=30):
    """(x, y, hold, free) presses -> [(tick, event, x, y)] and the plan length."""
    out, tick = [], start
    for x, y, hold, free in plan:
        out += [(tick, 'mousedown', x, y), (tick + hold, 'mouseup', x, y)]
        tick += hold + free
    return out, tick


class Task489Tests(unittest.TestCase):
    """Lower four sections joined: base -> Foundations -> Switchback -> Viaduct -> Works exit."""
    task_id = 'TASK-489'
    # Section plans start where the previous section actually leaves the player:
    # S01 exit east stop 4209.2, S02 exit lip 4429.2, S03 exit lip 5050.8.
    S01 = [(2390,-310,30,300),(2970,-425,30,0),(3180,-730,55,0),(2890,-1040,45,0),
           (3290,-1070,80,180),(3290,-1070,20,0),(3630,-1280,55,0),(3840,-1680,45,0),
           (3840,-1680,45,0),(3840,-1680,50,0),(4070,-1620,30,180)]
    S02 = [(3975,-1940,55,0),(4220,-2240,45,0),(4220,-2240,25,0),(3890,-2480,30,180),
           (3890,-2480,55,0),(4220,-2760,55,0),(4220,-2760,45,0),(3850,-3040,55,0),
           (4170,-3220,55,0),(4430,-3180,30,180)]
    S03 = [(4740,-3480,65,165),(5250,-3670,70,12),(4910,-3990,110,5),(5270,-4310,135,1),
           (5190,-4630,90,30),(5270,-4880,60,300)]
    S04 = [('S04-01/02',[(30,'mousedown',4700,-5200),(85,'mouseup',4700,-5200),
            (115,'mousedown',5100,-4980),(175,'mouseup',5100,-4980),
            (405,'mousedown',5150,-5430),(460,'mouseup',5150,-5430)],700),
           ('S04-03',[(30,'mousedown',4610,-5630),(75,'mouseup',4610,-5630),
            (130,'mousedown',4820,-5510),(190,'mouseup',4820,-5510)],375),
           # The slide after the double reflection stops at the landing lip (4991.27).
           ('S04-04',[(30,'mousedown',5170,-5910),(75,'mouseup',5170,-5910),
            (140,'mousedown',4810,-5710),(180,'mouseup',4810,-5710)],600),
           ('S04-exit',[(30,'mousedown',4890,-6090),(105,'mouseup',4890,-6090),
            (140,'mousedown',4650,-6520),(235,'mouseup',4650,-6520),
            (240,'mousedown',4560,-6460),(275,'mouseup',4560,-6460)],450)]
    EXIT = dict(x=[4510.8,4609.2],y=[-6491,-6490],speedX=[-.001,.001],speedY=[-.001,.001])
    HANDOFFS = {'S01':(4209.2,-1630.8),'S02':(4429.2,-3190.8),'S03':(5050.8,-4830.8)}

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        page = cls.browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate('''() => ({sections:GRAPPLE_OVER_MOUNTAIN.sections.slice(0,4),
            encounters:GRAPPLE_OVER_MOUNTAIN.encounters.slice(0,16),spawn:GRAPPLE_OVER_MOUNTAIN.spawn})''')
        page.close()
        cls.hashes = hashes()
        cls.hashes['tools/test_grapple_over_integration.py'] = hashlib.sha256(
            (ROOT/'tools/test_grapple_over_integration.py').read_bytes()).hexdigest()
        cls.proof = dict(browser=cls.browser.version, viewport=VIEWPORT, device_scale_factor=1,
            hz=60, seed=1, revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'],cwd=ROOT,text=True).splitlines(),
            source_hashes=cls.hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    @classmethod
    def segments(cls, recovery=False):
        segs = []
        for label, plan in (('S01',cls.S01),('S02',cls.S02),('S03',cls.S03)):
            inputs, length = holds(plan); segs.append((label, inputs, length+1))
        s04 = [list(s) for s in cls.S04]
        if recovery:
            # Mistimed long flat-press pull: no rest catch, fall from the S04 band to
            # the catch basin in the S03 band; pull back up to the Viaduct exit.
            segs += [('fall',[(30,'mousedown',4790,-5200),(85,'mouseup',4790,-5200)],400),
                     ('return',[(30,'mousedown',5150,-4980),(60,'mouseup',5150,-4980)],300)]
            # The retry's camera rests 13 units further right: re-aim the first S04-03 press.
            s04[1][1] = [(t,e,x+3 if i<2 else x,y) for i,(t,e,x,y) in enumerate(s04[1][1])]
        return segs + [tuple(s) for s in s04]

    def manifest(self, segs):
        from grapple_over_verify import metadata
        inputs, marks, tick = [], [], 0
        for label, plan, length in segs:
            inputs += [dict(tick=tick+t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan]
            marks.append(dict(label=label,start=tick,end=tick+length)); tick += length
        m = dict(metadata=metadata('base-start'),ticks=tick+1,inputs=inputs,
                 expected_exit=self.EXIT,required_events=['acquisition','release','bounce'])
        # Contacts are fully represented by every retained physics snapshot.
        m['metadata']['snapshot_contacts'] = True
        return m, marks

    def run_route(self, name, segs, clip):
        from grapple_over_verify import execute, check_trace, validate
        m, marks = self.manifest(segs)
        validate(m)
        self.assertNotIn('initial_setup', m); self.assertNotIn('initial_snapshot', m)
        self.evidence.write(name+'-inputs.json' if name != 'lower' else 'inputs.json',
            dict(m, segments=marks, scope='Base start; CLIMB_UI.restart(); trusted mouse events only'))
        trace = execute(m, self.browser, self.url, str(self.evidence.path('runs/'+name)), clip=clip)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path('runs/'+name+'-replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        shutil.rmtree(self.evidence.path('runs/'+name+'-replay'))
        return m, marks, trace, state_hash(replay)

    def continuity(self, m, trace):
        rows = trace['snapshots']; sim = [r['state']['simulation'] for r in rows]
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        self.assertEqual(trace['metadata']['testOnly'], True)
        p0 = sim[0]['player']; spawn = self.mountain['spawn']
        self.assertEqual((p0['x'],p0['y'],p0['speedX'],p0['speedY']), (spawn['x'],spawn['y'],0,0))
        self.assertEqual(sim[0]['stats']['maxHeight'], 0)
        ticks = [s['simulationTick'] for s in sim]
        steps = sorted({b-a for a,b in zip(ticks,ticks[1:])})
        # The fixed-step clock advances every frame and never rewinds.
        self.assertTrue(all(b > a for a,b in zip(ticks,ticks[1:])), steps)
        jumps = [max(abs(b['player']['x']-a['player']['x']),abs(b['player']['y']-a['player']['y']))
                 for a,b in zip(sim,sim[1:])]
        self.assertLess(max(jumps), 20)
        geometry = {e['id']:(e['x'],e['y']) for e in sim[0]['elements']}
        moved = sorted({e['id'] for s in sim for e in s['elements'] if (e['x'],e['y']) != geometry[e['id']]})
        mover_steps = max([abs(b['x']-a['x'])+abs(b['y']-a['y']) for s0,s1 in zip(sim,sim[1:])
                           for a,b in zip(s0['elements'],s1['elements'])], default=0)
        self.assertTrue(all([e['id'] for e in s['elements']] == list(geometry) for s in sim))
        self.assertTrue(all(not i.startswith(('S01','S02','S03','S04')) for i in moved), moved)
        self.assertLess(mover_steps, 10)
        self.assertFalse(any(s['stats']['completed'] for s in sim))
        heights = [s['stats']['maxHeight'] for s in sim]
        self.assertTrue(all(b >= a for a,b in zip(heights,heights[1:])))
        inputs = [e for e in trace['events'] if e['type'] == 'input']
        self.assertEqual(len(inputs), len(m['inputs']))
        self.assertTrue(all(e['trusted'] for e in inputs))
        presses = [e for e in inputs if e['event'] == 'mousedown']
        offscreen = [e['tick'] for e in presses if not (0 < e['client']['x'] < VIEWPORT['width']
                     and 0 < e['client']['y'] < VIEWPORT['height'])]
        self.assertEqual(offscreen, [])
        return dict(base_start=True, setup_only_spawns=0, debug_mutation=False,
            initial_player=p0, simulation_ticks=[ticks[0],ticks[-1]], tick_increments=steps,
            max_player_step=max(jumps), static_lower_geometry=True, moved_elements=moved,
            max_mover_step=mover_steps, completed=False, max_height_monotonic=True,
            trusted_inputs=len(inputs), offscreen_presses=offscreen,
            press_clients=[dict(tick=e['tick'],world=e['world'],client=e['client']) for e in presses])

    def accounting(self, trace):
        rows = trace['snapshots']; events = trace['events']; result = []
        for e in self.mountain['encounters']:
            box = e['exit']
            inside = [r['tick'] for r in rows if box['left'] <= r['state']['simulation']['player']['x'] <= box['right']
                      and box['top'] <= r['state']['simulation']['player']['y'] <= box['bottom']]
            touched = [dict(tick=ev['tick'],type=ev['type'],element=ev['after']['rope'][0]['id']
                            if ev['type'] == 'acquisition' else ev['contact']['elementId'])
                       for ev in events if (ev['type'] == 'acquisition' and ev['after']['rope'][0]['id'] in e['elements'])
                       or (ev['type'] == 'bounce' and ev['contact']['elementId'] in e['elements'])]
            result.append(dict(id=e['id'],section=e['section'],exit=box,first_exit_tick=inside[0] if inside else None,
                exit_ticks=len(inside),first_interaction=touched[0] if touched else None,interactions=len(touched)))
        for r in result:
            self.assertIsNotNone(r['first_exit_tick'], r['id'])
            self.assertIsNotNone(r['first_interaction'], r['id'])
        firsts = [r['first_exit_tick'] for r in result]
        self.assertEqual(firsts, sorted(firsts))
        return result

    def handoffs(self, trace, marks):
        rows = trace['snapshots']; out = []
        for mark in marks:
            p = rows[mark['end']]['state']['simulation']['player']
            out.append(dict(segment=mark['label'],tick=mark['end'],player=p,
                camera=rows[mark['end']]['state']['camera']))
        for section, (x, y) in self.HANDOFFS.items():
            h = next(h for h in out if h['segment'] == section)
            self.assertAlmostEqual(h['player']['x'], x, delta=1e-5)
            self.assertAlmostEqual(h['player']['y'], y, delta=1e-5)
            self.assertEqual((h['player']['speedX'], h['player']['speedY']), (0, 0))
        starts = {e['id']:e['start'] for e in self.mountain['encounters']}
        self.assertEqual((starts['S02-01']['x'],starts['S03-01']['x'],starts['S04-01']['x']),
                         tuple(self.HANDOFFS[s][0] for s in ('S01','S02','S03')))
        return out

    def test_01_continuous_lower(self):
        m, marks, trace, replay_sha = self.run_route('lower', self.segments(), clip=True)
        shutil.move(str(self.evidence.path('runs/lower/clip.webm')), str(self.evidence.path('lower.webm')))
        continuity = self.continuity(m, trace)
        accounting = self.accounting(trace)
        handoffs = self.handoffs(trace, marks)
        final = trace['snapshots'][-1]['state']['simulation']['player']
        bounces = [e['contact']['elementId'] for e in trace['events'] if e['type'] == 'bounce']
        for element in ('S04-flat-press','S04-angled-chute','S04-combination-press','S04-double-right','S04-double-left'):
            self.assertIn(element, bounces)
        result = dict(name='base to section-4 exit', passed=True, matching_replay=True,
            recorded_sha256=state_hash(trace), replayed_sha256=replay_sha, final=final,
            expected_exit=self.EXIT, continuity=continuity, encounters=accounting, handoffs=handoffs,
            bounces=bounces, proof=self.proof, video='lower.webm', inputs='inputs.json',
            trace=trace)
        self.evidence.write('trace.json', result)
        # trace.json now embeds the recorded trace; drop the duplicate raw copy.
        self.evidence.path('runs/lower/trace.json').unlink()
        print('PASS continuous lower: base start, %d trusted inputs, %d ticks, 16/16 encounter exits in order, '
              'hand-offs %s, final %.1f,%.1f at rest; replay identical' % (continuity['trusted_inputs'],
              m['ticks'], [round(h['player']['x'],1) for h in handoffs[:3]], final['x'], final['y']), flush=True)

    def test_02_cross_section_recovery(self):
        m, marks, trace, replay_sha = self.run_route('recovery', self.segments(recovery=True), clip=False)
        continuity = self.continuity(m, trace)
        accounting = self.accounting(trace)
        handoffs = self.handoffs(trace, marks)
        rows = trace['snapshots']; band = {s['id']:s['band'] for s in self.mountain['sections']}
        fall, ret = next(k for k in marks if k['label'] == 'fall'), next(k for k in marks if k['label'] == 'return')
        players = [r['state']['simulation']['player'] for r in rows]
        peak = min(range(fall['start'], fall['end']), key=lambda t: players[t]['y'])
        release = next(e for e in trace['events'] if e['type'] == 'release' and e['tick'] > fall['start'])
        landed = next(t for t in range(peak, fall['end']) if abs(players[t]['y']+4810.8) < 1e-5 and players[t]['speedY'] == 0)
        self.assertLess(players[peak]['y'], band['S04']['bottom'])
        self.assertGreater(players[landed]['y'], band['S03']['top'])
        # Snapshot N precedes inputs dispatched at tick N, so the free fall starts at N+1.
        self.assertFalse(any(rows[t]['state']['simulation']['grapple']['grappled'] for t in range(release['tick']+1, landed)))
        basin = players[fall['end']]
        self.assertEqual((round(basin['x'],4), round(basin['y'],4), basin['speedX']), (4909.2, -4810.8, 0))
        back = players[ret['end']]
        self.assertEqual((round(back['x'],4), round(back['y'],4), back['speedX']), (5169.2, -4830.8, 0))
        grabbed = [e['after']['rope'][0]['id'] for e in trace['events'] if e['type'] == 'acquisition' and ret['start'] <= e['tick'] < ret['end']]
        reentry = next(t for t in range(ret['end'], len(rows)) if players[t]['y'] < band['S04']['bottom'])
        final = players[-1]
        result = dict(name='S04 mistimed press -> S03-band catch basin -> Viaduct exit -> S04 exit', passed=True,
            matching_replay=True, recorded_sha256=state_hash(trace), replayed_sha256=replay_sha,
            natural_initiation=dict(input='mousedown (4790,-5200) held 55 ticks: flat-press pull without the rest catch',
                tick=fall['start']+30, release_tick=release['tick']),
            fall=dict(peak_tick=peak, peak=players[peak], landing_tick=landed, landing=players[landed],
                from_band='S04', to_band='S03', grappled_during_fall=False, drop=players[landed]['y']-players[peak]['y']),
            basin_rest=dict(tick=fall['end'], player=basin),
            return_pull=dict(acquisitions=grabbed, tick=ret['end'], player=back, rejoined='S03-exit'),
            reentered_S04_band_tick=reentry, final=final, expected_exit=self.EXIT,
            continuity={k:v for k,v in continuity.items() if k != 'press_clients'}, encounters=accounting,
            handoffs=handoffs, inputs='recovery-inputs.json', trace='runs/recovery/trace.json', proof=self.proof,
            scope='Same base-start run; no relocation, checkpoint or velocity/mover reset; physical fall only')
        self.evidence.write('recovery.json', result)
        print('PASS cross-section recovery: fall S04 band y %.1f -> S03-band basin y %.1f at tick %d, return to '
              'Viaduct exit %.1f, re-climb to S04 exit %.1f,%.1f; replay identical' % (players[peak]['y'],
              players[landed]['y'], landed, back['x'], final['x'], final['y']), flush=True)

    def test_03_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: runtime, level and harness match the tested worktree', flush=True)

class LifecycleBrowser:
    """Pass-through browser whose pages log PLATFORM lifecycle calls to the console.

    The wrapper only observes: it calls the original sendLifecycle unchanged.
    """
    SCRIPT = '''addEventListener('DOMContentLoaded', () => { const p = PLATFORM, send = p.sendLifecycle;
        p.sendLifecycle = function(name, data) {
            console.log('GRAPPLE_LIFECYCLE ' + JSON.stringify({name, data, x: ninja.x, y: ninja.y}));
            return send.apply(this, arguments) } })'''

    def __init__(self, browser):
        self._browser, self.calls = browser, []

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)
        context.add_init_script(self.SCRIPT)
        context.on('console', lambda m: m.text.startswith('GRAPPLE_LIFECYCLE ')
                   and self.calls.append(json.loads(m.text.split(' ', 1)[1])))
        return context


def exit_box(exit):
    # S05-01..03 author their exits as a rest point plus a width; the player stops at x.
    if 'left' in exit:
        return exit
    return dict(left=exit['x']-.01, right=exit['x']+exit['width'], top=exit['y']-1.2, bottom=exit['y']+10.8)


class Task490Tests(unittest.TestCase):
    """Upper four sections joined: section-4-exit fixture -> Cable Galleries -> Liftworks
    -> Exposed Crown -> Summit Array finish, in one recording with trusted mouse input."""
    task_id = 'TASK-490'
    # One labeled fixture placement: the actual TASK-489 continuous-run final rest on S04-exit
    # (artifacts/TASK-489/trace.json final 4510.8,-6490.8 at rest). Not a full-game completion.
    FIXTURE = dict(x=4510.8, y=-6490.8, speedX=0, speedY=0)
    # (label, [(tick, event, x, y)] relative to the segment start, length). Segment lengths
    # include waits at rest so the mover-timed encounters (S06 counterweight/upper weight,
    # S08 carriage; period 240 ticks) begin on the phase their isolated proofs used.
    SEGS = [
        ('S05-01',[(30,'mousedown',4655,-6780),(120,'mouseup',4655,-6780)],500),
        ('S05-02',[(30,'mousedown',5005,-7080),(120,'mouseup',5005,-7080)],500),
        ('S05-03',[(30,'mousedown',5425,-7380),(116,'mouseup',5425,-7380),
                   (117,'mousedown',5500,-7400),(145,'mouseup',5500,-7400)],500),
        # The exit slide ends against the S05-exit east stop (6389.2); wait for counterweight phase 0.
        ('S05-04',[(30,'mousedown',5805,-7700),(130,'mouseup',5805,-7700),
                   (680,'mousedown',6205,-8050),(775,'mouseup',6205,-8050)],1380),
        # Re-aimed from the real 6389.2 rest (isolated proof: 6300, press 6110 held 180).
        ('S06-01/02/03',[(30,'mousedown',6080,-8370),(240,'mouseup',6080,-8370)],480),
        ('S06-04',[(30,'mousedown',5715,-8590),(80,'mouseup',5715,-8590),(85,'mousedown',5825,-8900),
                   (220,'mouseup',5825,-8900),(250,'mousedown',6105,-9280),(350,'mouseup',6105,-9280),
                   (370,'mousedown',5775,-9660),(470,'mouseup',5775,-9660)],780),
        # Starts while still sliding on S06-exit (speedX ~0.07): velocity carried, not reset.
        ('S07-01',[(60,'mousedown',5430,-10000),(85,'mouseup',5430,-10000)],500),
        # Catch the shortcut jib from the rest ledge and drop back onto the ledge.
        ('S07-02',[(30,'mousedown',5160,-9970),(90,'mouseup',5160,-9970)],180),
        ('S07-03/04',[(30,'mousedown',4995,-10060),(80,'mouseup',4995,-10060),(85,'mousedown',5235,-10380),
                      (125,'mouseup',5235,-10380),(150,'mousedown',5500,-10780),(250,'mouseup',5500,-10780),
                      (255,'mousedown',5330,-11330),(430,'mouseup',5330,-11330)],650),
        # Connector: the crossing settles on the S07-exit west lip (5270.8); a short pull on the
        # exit's east wall steps to the S08 departure rest (5339.2).
        ('S07-exit step',[(20,'mousedown',5360,-11400),(40,'mouseup',5360,-11400)],120),
        ('S08-01',[(20,'mousedown',5000,-11740),(65,'mouseup',5000,-11740),
                   (125,'mousedown',4930,-11865),(150,'mouseup',4930,-11865)],650),
        # The bounce arc passes the carriage, so S08-02 also starts on carriage phase 0.
        ('S08-02',[(20,'mousedown',4070,-11945),(55,'mouseup',4070,-11945),
                   (215,'mousedown',3450,-12185),(241,'mouseup',3450,-12185)],720),
        ('S08-03',[(110,'mousedown',3490,-12338),(216,'mouseup',3490,-12338)],520),
        ('S08-04',[(20,'mousedown',3760,-12890),(70,'mouseup',3760,-12890)],300)]
    # Actual rest at the end of each segment (speed 0), except S06-04 which is still sliding.
    RESTS = {'S05-01':(4839.2,-6810.8),'S05-02':(5239.2,-7110.8),'S05-03':(5639.2,-7410.8),
             'S05-04':(6389.2,-8080.8),'S06-01/02/03':(5830.8,-8280.8),'S07-01':(5100.8,-9750.8),
             'S07-02':(5100.8,-9750.8),'S07-03/04':(5270.8,-11350.8),'S07-exit step':(5339.2,-11350.8),
             'S08-01':(4290.8,-11610.8),'S08-02':(3070.8,-12090.8),'S08-03':(4189.2,-12710.8)}
    PHASED = {'S06-01/02/03':['S06-counterweight-travel'],'S06-04':['S06-upper-weight-travel'],
              'S08-02':['S08-carriage-lift'],'S08-03':['S08-carriage-lift']}
    MOVING = ('S06-counterweight','S06-upper-weight','S07-sweeper','S08-overhang-carriage')

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.browser = LifecycleBrowser(browser)
        page = browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.level = page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)')
        cls.mountain = page.evaluate('''() => ({sections:GRAPPLE_OVER_MOUNTAIN.sections.slice(4,8),
            encounters:GRAPPLE_OVER_MOUNTAIN.encounters.slice(16,32),
            finish:GRAPPLE_OVER_MOUNTAIN.connectors.find(c => c.id === 'summit-approach').finishRegion})''')
        page.close()
        cls.hashes = hashes()
        cls.hashes['tools/test_grapple_over_integration.py'] = hashlib.sha256(
            (ROOT/'tools/test_grapple_over_integration.py').read_bytes()).hexdigest()
        cls.proof = dict(browser=browser.version, viewport=VIEWPORT, device_scale_factor=1,
            hz=60, seed=1, revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'],cwd=ROOT,text=True).splitlines(),
            source_hashes=cls.hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    def manifest(self):
        from grapple_over_verify import metadata
        inputs, marks, tick = [], [], 0
        for label, plan, length in self.SEGS:
            inputs += [dict(tick=tick+t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan]
            marks.append(dict(label=label,start=tick,end=tick+length)); tick += length
        m = dict(metadata=metadata('isolated'),initial_setup=dict(level=self.level,player=dict(self.FIXTURE)),
                 ticks=tick+1,inputs=inputs,expected_exit=dict(x=[3420,3700],y=[-12772,-12760]),
                 required_events=['acquisition','release','bounce'])
        m['metadata']['snapshot_contacts'] = True
        return m, marks

    def continuity(self, m, trace):
        rows = trace['snapshots']; sim = [r['state']['simulation'] for r in rows]
        spawns = trace['metadata']['setupOnlySpawns']
        # Exactly one placement, before tick 0, at the labeled S04-exit fixture; never mid-run.
        self.assertEqual(len(spawns), 1)
        self.assertEqual(spawns[0]['fixture']['player'], self.FIXTURE)
        self.assertIsNone(spawns[0]['fixture'].get('camera'))
        self.assertEqual(trace['metadata']['testOnly'], True)
        p0 = sim[0]['player']
        self.assertEqual((p0['x'],p0['y'],p0['speedX'],p0['speedY']), (4510.8,-6490.8,0,0))
        ticks = [s['simulationTick'] for s in sim]
        # The clock never rewinds; it advances every frame until the ending pauses physics.
        done = next(i for i, s in enumerate(sim) if s['stats']['completed'])
        self.assertTrue(all(b > a for a,b in zip(ticks[:done+1],ticks[1:done+1])))
        self.assertEqual(set(ticks[done:]), {ticks[done]})
        jumps = [max(abs(b['player']['x']-a['player']['x']),abs(b['player']['y']-a['player']['y']))
                 for a,b in zip(sim,sim[1:])]
        self.assertLess(max(jumps), 20)
        geometry = {e['id']:(e['x'],e['y']) for e in sim[0]['elements']}
        self.assertTrue(all([e['id'] for e in s['elements']] == list(geometry) for s in sim))
        moved = sorted({e['id'] for s in sim for e in s['elements'] if (e['x'],e['y']) != geometry[e['id']]})
        self.assertEqual(moved, sorted(self.MOVING))
        mover_steps = max(abs(b['x']-a['x'])+abs(b['y']-a['y']) for s0,s1 in zip(sim,sim[1:])
                          for a,b in zip(s0['elements'],s1['elements']))
        self.assertLess(mover_steps, 10)
        heights = [s['stats']['maxHeight'] for s in sim]
        self.assertTrue(all(b >= a for a,b in zip(heights,heights[1:])))
        inputs = [e for e in trace['events'] if e['type'] == 'input']
        self.assertEqual(len(inputs), len(m['inputs']))
        self.assertTrue(all(e['trusted'] for e in inputs))
        presses = [e for e in inputs if e['event'] == 'mousedown']
        offscreen = [e['tick'] for e in presses if not (0 < e['client']['x'] < VIEWPORT['width']
                     and 0 < e['client']['y'] < VIEWPORT['height'])]
        self.assertEqual(offscreen, [])
        return dict(single_fixture_placement=spawns[0]['fixture']['player'], mid_run_injection=False,
            setup_only_spawns=len(spawns), initial_player=p0, simulation_ticks=[ticks[0],ticks[-1]],
            clock_frozen_from_tick=done,
            max_player_step=max(jumps), moved_elements=moved, max_mover_step=mover_steps,
            max_height_monotonic=True, trusted_inputs=len(inputs), offscreen_presses=offscreen,
            press_clients=[dict(tick=e['tick'],world=e['world'],client=e['client']) for e in presses])

    def attached(self, trace):
        """Snapshot tick -> rope anchor id, from acquisition/release events."""
        out, anchor = {}, None
        events = [e for e in trace['events'] if e['type'] in ('acquisition','release')]
        for t in range(len(trace['snapshots'])):
            while events and events[0]['tick'] < t:
                e = events.pop(0)
                anchor = e['after']['rope'][0]['id'] if e['type'] == 'acquisition' else None
            out[t] = anchor
        return out

    def accounting(self, trace):
        rows = trace['snapshots']; events = trace['events']; anchors = self.attached(trace); result = []
        for e in self.mountain['encounters']:
            box = exit_box(e['exit'])
            inside = [r['tick'] for r in rows if box['left'] <= r['state']['simulation']['player']['x'] <= box['right']
                      and box['top'] <= r['state']['simulation']['player']['y'] <= box['bottom']
                      and ('attachedTo' not in box or anchors[r['tick']] == box['attachedTo'])]
            touched = [dict(tick=ev['tick'],type=ev['type'],element=ev['after']['rope'][0]['id']
                            if ev['type'] == 'acquisition' else ev['contact']['elementId'])
                       for ev in events if (ev['type'] == 'acquisition' and ev['after']['rope'][0]['id'] in e['elements'])
                       or (ev['type'] == 'bounce' and ev['contact']['elementId'] in e['elements'])]
            result.append(dict(id=e['id'],section=e['section'],exit=box,first_exit_tick=inside[0] if inside else None,
                exit_ticks=len(inside),first_interaction=touched[0] if touched else None,interactions=len(touched)))
        for r in result:
            self.assertIsNotNone(r['first_exit_tick'], r['id'])
            self.assertIsNotNone(r['first_interaction'], r['id'])
        firsts = [r['first_exit_tick'] for r in result]
        self.assertEqual(firsts, sorted(firsts))
        return result

    def handoffs(self, trace, marks):
        rows = trace['snapshots']; out = []
        for mark in marks:
            p = rows[mark['end']]['state']['simulation']['player']
            out.append(dict(segment=mark['label'],start_tick=mark['start'],tick=mark['end'],player=p,
                start_player=rows[mark['start']]['state']['simulation']['player'],
                camera=rows[mark['end']]['state']['camera']))
        for h in out:
            if h['segment'] in self.RESTS:
                x, y = self.RESTS[h['segment']]
                self.assertAlmostEqual(h['player']['x'], x, delta=1e-5, msg=h['segment'])
                self.assertAlmostEqual(h['player']['y'], y, delta=1e-5, msg=h['segment'])
                self.assertEqual((h['player']['speedX'], h['player']['speedY']), (0, 0), h['segment'])
        # The Liftworks transfer hands over a moving player: S07-01 begins with carried velocity.
        s07 = next(h for h in out if h['segment'] == 'S07-01')['start_player']
        self.assertGreater(abs(s07['speedX']), .01)
        return out

    def phases(self, trace, marks):
        rows = trace['snapshots']; movers = {m['id']:m for m in self.level['movers']}
        period = {k: round(m['periodMs']*60/1000) for k, m in movers.items()}
        starts = []
        for mark in marks:
            for mover in self.PHASED.get(mark['label'], []):
                # Mover time is the simulation clock since the fixture load (no reset at segment starts).
                starts.append(dict(segment=mark['label'],mover=mover,tick=mark['start'],
                    phase=(mark['start'] % period[mover])/period[mover]))
                self.assertEqual(mark['start'] % period[mover], 0, mark['label'])
        by_element = {m['element']:k for k, m in movers.items()}
        grabs = []
        for e in trace['events']:
            if e['type'] == 'acquisition' and e['after']['rope'][0]['id'] in by_element:
                el = next(x for x in rows[e['tick']]['state']['simulation']['elements'] if x['id'] == e['after']['rope'][0]['id'])
                mover = by_element[el['id']]
                grabs.append(dict(tick=e['tick'],element=el['id'],mover=mover,x=el['x'],y=el['y'],
                    phase=(e['tick'] % period[mover])/period[mover]))
        self.assertEqual(sorted({g['element'] for g in grabs}),
                         ['S06-counterweight','S06-upper-weight','S08-overhang-carriage'])
        travel = {}
        for el in self.MOVING:
            vals = [next(x for x in r['state']['simulation']['elements'] if x['id'] == el) for r in rows[::4]]
            key = 'x' if el == 'S07-sweeper' else 'y'
            travel[el] = [min(v[key] for v in vals), max(v[key] for v in vals)]
            self.assertGreater(travel[el][1]-travel[el][0], 100, el)
        return dict(periods_ticks=period, segment_start_phases=starts, moving_target_acquisitions=grabs,
                    mover_travel=travel)

    def finish(self, trace, marks):
        rows = trace['snapshots']; done = [r['state']['simulation']['stats']['completed'] for r in rows]
        self.assertFalse(done[0])
        flips = [t for t in range(1, len(done)) if done[t] and not done[t-1]]
        self.assertEqual(len(flips), 1)
        tick = flips[0]
        self.assertTrue(all(done[tick:]))
        s084 = next(k for k in marks if k['label'] == 'S08-04')
        self.assertGreaterEqual(tick, s084['start'])
        p = rows[tick]['state']['simulation']['player']; f = self.mountain['finish']
        self.assertTrue(f['left'] <= p['x'] <= f['right'] and f['top'] <= p['y'] <= f['bottom'], p)
        # The ending freezes play: the player never moves after the finish event.
        frozen = all(r['state']['simulation']['player'] == p for r in rows[tick:])
        self.assertTrue(frozen)
        return dict(completion_tick=tick, completed_transitions=len(flips), player=p, finish_region=f,
                    frozen_after=frozen, ticks_after=len(rows)-1-tick)

    def test_01_continuous_upper(self):
        from grapple_over_verify import execute, check_trace, validate
        m, marks = self.manifest()
        validate(m)
        self.assertNotIn('initial_snapshot', m)
        self.evidence.write('inputs.json', dict(m, segments=marks,
            scope='One labeled section-4-exit fixture placement (TASK-489 final rest), then trusted mouse '
                  'events only; not a full-game completion claim'))
        self.browser.calls.clear()
        trace = execute(m, self.browser, self.url, str(self.evidence.path('runs/upper')), clip=True)
        lifecycle = list(self.browser.calls)
        check_trace(m, trace)
        self.evidence.path('runs/upper/trace.json').unlink()
        shutil.move(str(self.evidence.path('runs/upper/clip.webm')), str(self.evidence.path('upper.webm')))
        self.browser.calls.clear()
        replay = execute(m, self.browser, self.url, str(self.evidence.path('runs/upper-replay')), filmstrip=True)
        replay_lifecycle = list(self.browser.calls)
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        frames = sorted(self.evidence.path('runs/upper-replay').glob('frame-*.png'))
        continuity = self.continuity(m, trace)
        accounting = self.accounting(trace)
        handoffs = self.handoffs(trace, marks)
        phases = self.phases(trace, marks)
        finish = self.finish(trace, marks)
        completed = [c for c in lifecycle if c['name'] == 'level_completed']
        self.assertEqual(len(completed), 1)
        self.assertEqual([c['name'] for c in replay_lifecycle if c['name'] == 'level_completed'], ['level_completed'])
        self.assertEqual((completed[0]['x'], completed[0]['y']), (finish['player']['x'], finish['player']['y']))
        # Review stills: the filmstrip frame nearest each upper landmark, plus the finish.
        rows = trace['snapshots']; ticks = [int(f.stem.split('-')[1]) for f in frames]; stills = []
        for section in self.mountain['sections']:
            lm = section['landmark']
            t = min(ticks, key=lambda t: (rows[t]['state']['simulation']['player']['x']-lm['x'])**2
                    + (rows[t]['state']['simulation']['player']['y']-lm['y'])**2)
            stills.append(dict(section=section['id'],landmark=lm,tick=t,file='review/%s-tick-%04d.png' % (section['id'], t)))
        t = min(t for t in ticks if t > finish['completion_tick'])
        stills.append(dict(section='S08',landmark='finish',tick=t,file='review/finish-tick-%04d.png' % t))
        for s in stills:
            shutil.copy(self.evidence.path('runs/upper-replay/frame-%04d.png' % s['tick']), self.evidence.path(s['file']))
        shutil.rmtree(self.evidence.path('runs'))
        bounces = [e['contact']['elementId'] for e in trace['events'] if e['type'] == 'bounce']
        self.assertIn('S08-deflector-ramp', bounces)
        hazards = [e['tick'] for e in trace['events'] if e['type'] == 'knockback']
        result = dict(name='section-4-exit fixture to summit finish', passed=True, matching_replay=True,
            full_game_completion=False, recorded_sha256=state_hash(trace), replayed_sha256=state_hash(replay),
            final=rows[-1]['state']['simulation']['player'], finish=finish,
            lifecycle=dict(recorded=lifecycle, replayed=replay_lifecycle, level_completed_calls=len(completed)),
            continuity=continuity, encounters=accounting, handoffs=handoffs, mover_phases=phases,
            bounces=bounces, knockback_ticks=hazards, stills=stills, proof=self.proof, video='upper.webm',
            inputs='inputs.json', trace=trace)
        # Compact JSON: the embedded trace is the only retained copy of the recording.
        self.evidence.path('trace.json').write_text(json.dumps(result, separators=(',', ':')) + '\n')
        print('PASS continuous upper: 1 labeled S04-exit fixture, %d trusted inputs, %d ticks, 16/16 upper encounter '
              'exits in order, %d moving-target acquisitions on phase, finish at tick %d (%.1f,%.1f) with exactly one '
              'level_completed; replay identical' % (continuity['trusted_inputs'], m['ticks'],
              len(phases['moving_target_acquisitions']), finish['completion_tick'], finish['player']['x'],
              finish['player']['y']), flush=True)

    def test_02_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: runtime, level and harness match the tested worktree', flush=True)


class Task529Tests(unittest.TestCase):
    """Layout-v3 lower four sections joined: base -> S01 -> S02 -> S03 -> S04 exit in one base-start
    recording with trusted mouse input, plus a naturally initiated S04 -> S03 fall and an input-only rejoin.

    The section routes are the v3 nominal routes of the section proofs (TASK-548/551/554/515), played
    back to back in one run from the production restart at the base spawn: no placement, snapshot,
    spawn or velocity/mover reset at a section boundary. Every section ends settled on its green exit
    pad/ledge (the next section's start), and the next section's first press comes on the mover phase
    its proof used (the movers are clocked by the simulation since the level load, period 240 ticks).
    """
    task_id = 'TASK-529'
    # Segment starts (ticks): S01 at 0, S02 at 1495, S03 at 3245, S04 at 4545; the run ends at 6545.
    SECTION_STARTS = dict(S01=0, S02=1495, S03=3245, S04=4545)
    TICKS = 6545
    PERIOD = 240
    # Mistimed S04-01 (the recovery run): the blue hoist held 475 ticks instead of 365 (released at
    # 5025, not 4915). The swing carries the player past the S03 exit ledge into the right map edge;
    # it drops along it through S03-fall-drag onto the green S03 lower bridge (S03 band) and settles.
    LATE_RELEASE = 5025
    # Input-only rejoin from the bridge (a pocket between S02-east-wall and the right map edge): pull the
    # top of the green S02 east wall (out of the pocket, over the wall), a 6-tick S03 hoist tap that drops
    # the player west into S02-exit-drag onto the green S02 exit ledge, then a 125-tick pull along the
    # ledge to the nominal S03-01 start. The S03 route then repeats on its phase (tick 6845 = 3245 + 15
    # periods), and S04 (tick 8145 = 4545 + 15 periods) with inputs re-tuned for the rejoin camera: the
    # camera rests 58 units lower after the re-climb, so the quantized hoist aim and the second apex
    # differ (hoist aimed one pixel lower and held 369, exit hook at its near corner pressed at 1000).
    WALL, HOIST_TAP, LEDGE = (6345, -5799), (5520, -5800), (5800, -4860)
    REJOIN = [(5765,'mousedown',*WALL),(5975,'mouseup',*WALL),(5980,'mousedown',*HOIST_TAP),(5986,'mouseup',*HOIST_TAP),
              (6610,'mousedown',*LEDGE),(6735,'mouseup',*LEDGE)]
    REJOIN_S03, REJOIN_S04, RECOVERY_TICKS = 6845, 8145, 10045
    S03_BAND_LANDING = 'S03-lower-bridge'
    S02_LEDGE_SETTLE = dict(x=[5640,6160], y=[-4890,-4860], speedX=[-.001,.001], speedY=[-.05,.05])

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        import test_grapple_over_sections as sections
        cls.S = sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        page = cls.browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate('''() => ({sections:GRAPPLE_OVER_MOUNTAIN.sections,
            encounters:GRAPPLE_OVER_MOUNTAIN.encounters.slice(0,17),spawn:GRAPPLE_OVER_MOUNTAIN.spawn,
            range:GRAPPLE_OVER_MOUNTAIN.range,movers:GRAPPLE_OVER_MOUNTAIN.geometry.movers,
            drags:GRAPPLE_OVER_MOUNTAIN.geometry.elements.filter(e=>e.role==='drag').map(e=>({id:e.id,
                left:e.x+Math.min(...e.points.map(p=>p.x)),right:e.x+Math.max(...e.points.map(p=>p.x)),
                top:e.y+Math.min(...e.points.map(p=>p.y)),bottom:e.y+Math.max(...e.points.map(p=>p.y))})),
            radius:{base:MODE_DEFINITIONS.grapple_over.acquisitionRadius,upgraded:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius}})''')
        page.close()
        cls.hashes = hashes()
        cls.hashes['tools/test_grapple_over_integration.py'] = hashlib.sha256(
            (ROOT/'tools/test_grapple_over_integration.py').read_bytes()).hexdigest()
        cls.proof = dict(browser=cls.browser.version, viewport=VIEWPORT, device_scale_factor=1,
            hz=60, seed=1, revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'],cwd=ROOT,text=True).splitlines(),
            source_hashes=cls.hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    # ---- routes ---------------------------------------------------------------------------------
    @classmethod
    def nominal(cls):
        D, C = cls.S.DeflectorV3Checks, cls.S.DeflectorV3CompleteChecks
        # D.S03_V3_ROUTE is the TASK-548 S01 route, the TASK-551 S02 route from 1495 and the
        # TASK-554/555 S03 route from 3245; the TASK-515/516 S04 route follows from 4545.
        return D.S03_V3_ROUTE + [(t+cls.SECTION_STARTS['S04'], e, x, y) for t, e, x, y in C.S04_ROUTE_V3]

    @classmethod
    def recovery(cls):
        D, C, V = cls.S.DeflectorV3Checks, cls.S.DeflectorV3CompleteChecks, cls.S.ViaductV3CompleteChecks
        H, s4 = D.HOIST_V3, cls.SECTION_STARTS['S04']
        late = [(s4+5,'mousedown',*H),(cls.LATE_RELEASE,'mouseup',*H)]
        s04 = [(5,'mousedown',H[0],H[1]+4),(374,'mouseup',H[0],H[1]+4)] + D.S04_02_V3 + C.S04_03_V3 + \
              [(1000,'mousedown',812,-11994),(1065,'mouseup',812,-11994)]
        return (D.S03_V3_ROUTE + late + cls.REJOIN + [(t+cls.REJOIN_S03, e, x, y) for t, e, x, y in V.S03_ROUTE_V3]
                + [(t+cls.REJOIN_S04, e, x, y) for t, e, x, y in s04])

    def manifest(self, plan, ticks):
        from grapple_over_verify import metadata, validate
        m = dict(metadata=metadata('base-start'), ticks=ticks, inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
                 expected_exit=self.S.DeflectorV3CompleteChecks.S04_04_EXIT, required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        validate(m)
        self.assertNotIn('initial_setup', m); self.assertNotIn('initial_snapshot', m)
        return m

    def run_route(self, name, m, clip):
        """Record, replay and compare; the raw recordings are deleted (the compact evidence is kept)."""
        from grapple_over_verify import execute, check_trace
        trace = execute(m, self.browser, self.url, str(self.evidence.path('runs/'+name)), clip=clip)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path('runs/'+name+'-replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        recorded, replayed = state_hash(trace), state_hash(replay)
        del replay
        self.evidence.path('runs/'+name+'/trace.json').unlink()
        shutil.rmtree(self.evidence.path('runs/'+name+'-replay'))
        return trace, recorded, replayed

    # ---- shared checks --------------------------------------------------------------------------
    @staticmethod
    def players(trace):
        return [r['state']['simulation']['player'] for r in trace['snapshots']]

    @staticmethod
    def inside(p, bounds):
        return all(lo <= p[k] <= hi for k, (lo, hi) in bounds.items())

    def first_exit_ticks(self, players, encounters=None, after=0):
        out = {}
        for e in encounters or self.mountain['encounters'][:16]:
            b = exit_box(e['exit'])
            out[e['id']] = next((t for t in range(after, len(players)) if b['left'] <= players[t]['x'] <= b['right']
                                 and b['top'] <= players[t]['y'] <= b['bottom']), None)
        return out

    def continuity(self, m, trace, s04_exit_tick):
        sim = [r['state']['simulation'] for r in trace['snapshots']]
        self.assertEqual(m['metadata']['kind'], 'base-start')
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        self.assertIs(trace['metadata']['testOnly'], True)
        p0 = sim[0]['player']; spawn = self.mountain['spawn']
        self.assertEqual((p0['x'],p0['y'],p0['speedX'],p0['speedY']), (spawn['x'],spawn['y'],0,0))
        self.assertEqual(sim[0]['stats']['maxHeight'], 0)
        self.assertIs(sim[0]['upgrades']['range'], False)
        ticks = [s['simulationTick'] for s in sim]
        steps = sorted({b-a for a, b in zip(ticks, ticks[1:])})
        # The fixed-step clock advances by the same amount every frame and never rewinds or restarts.
        self.assertEqual(len(steps), 1, steps)
        self.assertGreater(steps[0], 0)
        jumps = [max(abs(b['player']['x']-a['player']['x']), abs(b['player']['y']-a['player']['y'])) for a, b in zip(sim, sim[1:])]
        # No relocation: every per-tick displacement is covered by the recorded speeds (8 physics cycles per tick).
        excess = max(j - 8*max(abs(a['player'][k]) for a in (u, v) for k in ('speedX', 'speedY'))
                     for j, u, v in zip(jumps, sim, sim[1:]))
        self.assertLess(excess, 1, excess)
        self.assertLess(max(jumps), 40)
        ids = [e['id'] for e in sim[0]['elements']]
        self.assertTrue(all([e['id'] for e in s['elements']] == ids for s in sim))
        # Lower-section movers: small continuous steps and a strict 240-tick period from the level load
        # (a reset at a section boundary would break the period); every other element stays put.
        index = {k: i for i, k in enumerate(ids)}
        movers, period_error, mover_step = {}, 0, 0
        for v in self.mountain['movers']:
            if not v['element'].startswith(('S01','S02','S03','S04')): continue
            i, k = index[v['element']], v['axis']
            pos = [s['elements'][i][k] for s in sim]
            mover_step = max(mover_step, max(abs(b-a) for a, b in zip(pos, pos[1:])))
            period_error = max(period_error, max(abs(pos[t]-pos[t-self.PERIOD]) for t in range(self.PERIOD, len(pos))))
            self.assertAlmostEqual(min(pos), v['min'], delta=1); self.assertAlmostEqual(max(pos), v['max'], delta=1)
            movers[v['element']] = dict(axis=k, min=min(pos), max=max(pos), every_60_ticks=[round(x, 3) for x in pos[::60]])
        self.assertLess(mover_step, 2)
        self.assertLess(period_error, 1e-6)
        mover_ids = {v['element'] for v in self.mountain['movers']}
        origin = {e['id']: (e['x'], e['y']) for e in sim[0]['elements']}
        moved = sorted({e['id'] for s in sim for e in s['elements'] if e['id'] not in mover_ids and (e['x'], e['y']) != origin[e['id']]})
        self.assertEqual(moved, [])
        self.assertFalse(any(s['stats']['completed'] for s in sim))
        heights = [s['stats']['maxHeight'] for s in sim]
        self.assertTrue(all(b >= a for a, b in zip(heights, heights[1:])))
        # Active range: the base 1080 at every snapshot before the S04 exit; the upgrade is earned on the
        # tick the player enters the S04-04 exit (the S05-01 start, S05's rangeUpgradeZone) and kept.
        ranges = [s['upgrades']['range'] for s in sim]
        upgrade = next((t for t, r in enumerate(ranges) if r), None)
        self.assertEqual(upgrade, s04_exit_tick)
        self.assertFalse(any(ranges[:s04_exit_tick]))
        self.assertTrue(all(ranges[s04_exit_tick:]))
        inputs = [e for e in trace['events'] if e['type'] == 'input']
        self.assertEqual(len(inputs), len(m['inputs']))
        self.assertTrue(all(e['trusted'] for e in inputs))
        presses = [e for e in inputs if e['event'] == 'mousedown']
        offscreen = [e['tick'] for e in presses if not (0 < e['client']['x'] < VIEWPORT['width'] and 0 < e['client']['y'] < VIEWPORT['height'])]
        self.assertEqual(offscreen, [])
        self.assertFalse(any(ranges[e['tick']] for e in presses))
        return dict(base_start=True, kind=m['metadata']['kind'], initial_setup=None, initial_snapshot=None,
            setup_only_spawns=trace['metadata']['setupOnlySpawns'], debug_mutation=False, state_reset=False,
            initial_player=p0, simulation_ticks=[ticks[0], ticks[-1]], simulation_tick_increment=steps,
            max_player_step=max(jumps), max_step_beyond_8x_speed=excess, static_elements_moved=moved, lower_movers=movers, max_mover_step=mover_step,
            mover_period_ticks=self.PERIOD, max_mover_period_error=period_error, completed=False, max_height_monotonic=True,
            range=dict(base=self.mountain['radius']['base'], upgraded=self.mountain['radius']['upgraded'],
                       snapshots_at_base_range=s04_exit_tick, upgrade_tick=upgrade, s04_exit_tick=s04_exit_tick,
                       all_presses_at_base_range=True, s05_zone=self.mountain['sections'][4]['rangeUpgradeZone']),
            trusted_inputs=len(inputs), offscreen_presses=offscreen,
            press_clients=[dict(tick=e['tick'], world=e['world'], client=e['client'], range=self.mountain['radius']['base']) for e in presses])

    @staticmethod
    def mechanics(trace):
        out = []
        for e in trace['events']:
            if e['type'] in ('acquisition', 'release'):
                rope = e['after']['rope'] if e['type'] == 'acquisition' else e['before']['rope']
                element = rope[0]['id'] if rope else None
            elif e['type'] == 'bounce':
                element = e['contact']['elementId']
            else:
                continue
            p = (e['after'] if e['type'] != 'bounce' else e['before'])['simulation']['player']
            out.append(dict(tick=e['tick'], type=e['type'], element=element, player={k: p[k] for k in ('x', 'y', 'speedX', 'speedY')}))
        return out

    def compact(self, trace):
        """Per-tick player/range/height rows, per-tick snapshot hashes and the input/rope/bounce events; no element lists."""
        rows = []
        for r in trace['snapshots']:
            s = r['state']['simulation']; p = s['player']
            rows.append([r['tick'], s['simulationTick'], p['x'], p['y'], p['speedX'], p['speedY'], int(s['upgrades']['range']),
                         s['stats']['maxHeight'], int(bool(s['grapple'].get('grappled')))])
        inputs = [{k: e[k] for k in ('tick', 'event', 'world', 'client', 'trusted')} for e in trace['events'] if e['type'] == 'input']
        return dict(fields=['tick','simulationTick','x','y','speedX','speedY','rangeUpgraded','maxHeight','grappled'], rows=rows,
                    snapshot_sha256=[r['sha256'] for r in trace['snapshots']], inputs=inputs, mechanics=self.mechanics(trace),
                    metadata=trace['metadata'])

    def handoffs(self, players, starts):
        ids = {'S02':'S02-01', 'S03':'S03-01', 'S04':'S04-01', 'S05':'S05-01'}
        encounters = {e['id']: e for e in self.mountain['encounters']}
        out = []
        for section, tick in starts.items():
            p = players[tick]; declared = encounters[ids[section]]['start']
            out.append(dict(into=section, tick=tick, player={k: p[k] for k in ('x','y','speedX','speedY')},
                            carried_speed=math.hypot(p['speedX'], p['speedY']), declared_start=declared,
                            distance_to_declared_start=math.hypot(p['x']-declared['x'], p['y']-declared['y'])))
        return out

    # ---- cases ----------------------------------------------------------------------------------
    def test_01_continuous_lower(self):
        m = self.manifest(self.nominal(), self.TICKS)
        bounds = [*self.SECTION_STARTS.values(), self.TICKS]
        segments = [dict(section=k, start=bounds[i], end=bounds[i+1]) for i, k in enumerate(self.SECTION_STARTS)]
        self.evidence.write('inputs.json', dict(m, segments=segments,
            scope='Base start: production CLIMB_UI.restart() at the base spawn; trusted Playwright mouse events only; '
                  'no initial_setup/initial_snapshot, no spawn, no velocity or mover reset at any section boundary'))
        trace, recorded, replayed = self.run_route('lower', m, clip=True)
        shutil.move(str(self.evidence.path('runs/lower/clip.webm')), str(self.evidence.path('lower.webm')))
        players = self.players(trace)
        exits = self.first_exit_ticks(players)
        order = [exits[e['id']] for e in self.mountain['encounters'][:16]]
        self.assertTrue(all(t is not None for t in order), exits)
        self.assertEqual(order, sorted(order))
        continuity = self.continuity(m, trace, exits['S04-04'])
        mech = self.mechanics(trace)
        acquired = [x['element'] for x in mech if x['type'] == 'acquisition' and x['element'] not in ('S01-entry-pad', 'S02-exit-ledge')]
        self.assertEqual(acquired, self.S.DeflectorV3Checks.S03_V3_ACQUIRED + ['S04-hoist','S04-lift','S04-crest-hook','S04-exit-hook'])
        encounters = []
        for e in self.mountain['encounters'][:16]:
            touched = [x for x in mech if x['element'] in e['elements'] and x['type'] in ('acquisition','bounce')]
            self.assertTrue(touched, e['id'])
            encounters.append(dict(id=e['id'], section=e['section'], exit=exit_box(e['exit']), first_exit_tick=exits[e['id']],
                                   first_interaction=touched[0]))
        starts = {k: v for k, v in self.SECTION_STARTS.items() if k != 'S01'}; starts['S05'] = self.TICKS
        handoffs = self.handoffs(players, starts)
        for h in handoffs:
            # Each section ends settled on the next section's start (its green exit pad/ledge).
            self.assertLess(h['carried_speed'], .05, h)
            self.assertLess(h['distance_to_declared_start'], 2, h)
        final = players[-1]
        result = dict(name='base to S04 exit (layout v3 S01-S04)', passed=True, matching_replay=True, recorded_sha256=recorded,
            replayed_sha256=replayed, ticks=m['ticks'], final={k: final[k] for k in ('x','y','speedX','speedY')},
            expected_exit=m['expected_exit'], encounter_exits_in_order=True, encounter_exit_ticks=order, encounters=encounters,
            handoffs=handoffs, acquisitions=acquired, continuity=continuity, proof=self.proof, video='lower.webm', inputs='inputs.json',
            trace=self.compact(trace))
        self.evidence.write('trace.json', result)
        print('PASS continuous lower: base start, %d trusted inputs, %d ticks, 16/16 encounter exits in order %s, hand-offs %s, '
              'range 1080 at every snapshot before the S04 exit (upgrade on the S04-04 exit tick %d), final %.1f,%.1f at rest; replay identical'
              % (continuity['trusted_inputs'], m['ticks'], order, [(h['into'], round(h['player']['x'],1), round(h['player']['y'],1)) for h in handoffs],
                 exits['S04-04'], final['x'], final['y']), flush=True)

    def test_02_fall_and_rejoin(self):
        m = self.manifest(self.recovery(), self.RECOVERY_TICKS)
        self.evidence.write('recovery-inputs.json', dict(m, scope='Same base start as inputs.json; the S04-01 hoist is held 105 ticks '
            'too long; every later input is a trusted mouse press/release (no relocation, checkpoint or reset)'))
        trace, recorded, replayed = self.run_route('recovery', m, clip=False)
        players = self.players(trace); mech = self.mechanics(trace)
        bands = {s['id']: s['band'] for s in self.mountain['sections']}
        drag = next(d for d in self.mountain['drags'] if d['id'] == 'S03-fall-drag')
        release = next(x for x in mech if x['type'] == 'release' and x['element'] == 'S04-hoist')
        self.assertEqual(release['tick'], self.LATE_RELEASE)
        # Natural initiation from the S04 band (the hoist swing), above the S03 band.
        self.assertTrue(bands['S04']['top'] <= release['player']['y'] <= bands['S04']['bottom'])
        self.assertLess(release['player']['y'], bands['S03']['top'])
        landing = next(x for x in mech if x['type'] == 'bounce' and x['tick'] > release['tick'] and x['element'] == self.S03_BAND_LANDING)
        between = [x for x in mech if release['tick'] < x['tick'] < landing['tick'] and x['type'] == 'acquisition']
        self.assertEqual(between, [])
        self.assertFalse(any(trace['snapshots'][t]['state']['simulation']['grapple'].get('grappled') for t in range(release['tick']+1, landing['tick'])))
        apex_tick = min(range(release['tick'], landing['tick']), key=lambda t: players[t]['y'])
        overlap = lambda p, b: (max(b['left']-p['x'], 0, p['x']-b['right'])**2 + max(b['top']-p['y'], 0, p['y']-b['bottom'])**2) < p['radius']**2
        ticks = [t for t in range(apex_tick, landing['tick']+1) if overlap(players[t], drag)]
        entry = ticks[0]
        self.assertEqual(ticks, list(range(entry, landing['tick']+1)))
        before, at = players[entry-1], landing['player']
        land_y = players[landing['tick']]['y']
        self.assertTrue(bands['S03']['top'] <= land_y <= bands['S03']['bottom'], land_y)
        # The drag zone damps the vertical speed every tick on the way down to the bridge.
        self.assertLess(at['speedY'], before['speedY'])
        rejoin_tick = self.REJOIN[0][0]
        bounces = [x for x in mech if x['type'] == 'bounce' and x['element'] == self.S03_BAND_LANDING and x['tick'] < rejoin_tick]
        rest_y = max(players[t]['y'] for t in range(rejoin_tick-60, rejoin_tick))
        fall_height = rest_y - players[apex_tick]['y']
        peaks = []
        for a, b in zip(bounces, bounces[1:]+[None]):
            end = b['tick'] if b else rejoin_tick
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], peak_tick=top, peak_y=players[top]['y'], height=rest_y-players[top]['y'],
                              fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(p['peak_y'] > release['player']['y'] for p in peaks))
        settled = players[rejoin_tick-40:rejoin_tick]
        self.assertTrue(all(overlap(p, drag) and abs(p['speedX']) < 1e-3 for p in settled))
        # Rejoin: out of the pocket onto the S02 exit ledge, then the S03 and S04 routes to the S04 exit.
        after = [x for x in mech if x['tick'] >= rejoin_tick and x['type'] == 'acquisition']
        names = [x['element'] for x in after]
        self.assertEqual(names[:3], ['S02-east-wall', 'S03-hoist', 'S02-exit-ledge'])
        self.assertEqual(names[3:], ['S03-hoist','S03-lift','S03-crest-hook','S03-exit-hook','S04-hoist','S04-lift','S04-crest-hook','S04-exit-hook'])
        ledge = players[self.REJOIN_S03]
        self.assertTrue(self.inside(ledge, self.S02_LEDGE_SETTLE), ledge)
        reclimb = self.first_exit_ticks(players, self.mountain['encounters'][8:16], after=self.REJOIN_S03)
        s04_exit = reclimb['S04-04']
        self.assertIsNotNone(s04_exit)
        continuity = self.continuity(m, trace, s04_exit)
        final = players[-1]
        handoffs = self.handoffs(players, dict(S03=self.REJOIN_S03, S04=self.REJOIN_S04, S05=self.RECOVERY_TICKS))
        for h in handoffs:
            self.assertLess(h['carried_speed'], .05, h)
        nominal_release = self.SECTION_STARTS['S04']+370
        result = dict(name='S04 mistimed hoist release -> S03-fall-drag -> S03 lower bridge (S03 band) -> input-only rejoin -> S04 exit',
            passed=True, matching_replay=True, recorded_sha256=recorded, replayed_sha256=replayed, ticks=m['ticks'],
            natural_initiation=dict(input='S04-01 blue hoist pressed at %d and held %d ticks (nominal 365): released at tick %d instead of %d'
                                    % (self.SECTION_STARTS['S04']+5, self.LATE_RELEASE-self.SECTION_STARTS['S04']-5, self.LATE_RELEASE, nominal_release),
                                    release=release, from_band='S04', s04_band=bands['S04'], release_above_S03_band_top=True),
            apex=dict(tick=apex_tick, player={k: players[apex_tick][k] for k in ('x','y','speedX','speedY')}),
            drag_zone=dict(id='S03-fall-drag', box=drag, entry_tick=entry, last_tick_inside=ticks[-1],
                before=dict(tick=entry-1, x=before['x'], y=before['y'], speedX=before['speedX'], speedY=before['speedY']),
                after=dict(tick=landing['tick'], x=at['x'], y=at['y'], speedX=at['speedX'], speedY=at['speedY'],
                           meaning='at the first contact with the S03 lower bridge (the end of the drag-zone descent)'),
                vertical_speed_reduced=at['speedY'] < before['speedY'],
                horizontal_note='the swing release hits the right map edge (x 6469.2) above the drag zone, so speedX is already 0 on entry'),
            landing=dict(tick=landing['tick'], element=self.S03_BAND_LANDING, y=land_y, band='S03', s03_band=bands['S03'], in_s03_band=True),
            fall_height=fall_height, fall_height_definition='settled rest y on the bridge minus the apex y after the release',
            bounce_peaks=peaks[:8], first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            settled=dict(window=[rejoin_tick-40, rejoin_tick-1], inside='S03-fall-drag', on=self.S03_BAND_LANDING,
                         player={k: settled[-1][k] for k in ('x','y','speedX','speedY')}),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'],
                inputs=[i for i in m['inputs'] if i['tick'] >= rejoin_tick],
                acquisitions=[{k: x[k] for k in ('tick','element','player')} for x in after],
                s02_exit_ledge_pose=dict(tick=self.REJOIN_S03, player={k: ledge[k] for k in ('x','y','speedX','speedY')}, box=self.S02_LEDGE_SETTLE),
                reclimb_exit_ticks=reclimb, handoffs=handoffs,
                note='the S04-03 exit box (0..30, -11600..-11380) is %s in the re-climb: the second apex on the map edge is lower than '
                     'nominal and the exit hook is caught from it at its near corner' % ('entered' if reclimb['S04-03'] else 'not entered'),
                final={k: final[k] for k in ('x','y','speedX','speedY')}, s04_exit=m['expected_exit'], s04_exit_tick=s04_exit),
            continuity={k: v for k, v in continuity.items() if k not in ('press_clients','lower_movers')}, proof=self.proof,
            inputs='recovery-inputs.json', trace=self.compact(trace),
            scope='Same base-start run; no relocation, checkpoint, spawn or velocity/mover reset; physical fall only')
        self.evidence.write('recovery.json', result)
        print('PASS fall and rejoin: S04-01 hoist released at %d (y %.1f, S04 band) -> apex %.1f -> S03-fall-drag at %d vx/vy %.3f/%.3f -> '
              '%.3f/%.3f at the %s (y %.1f, S03 band) at %d; first bounce peak %.3f of %.1f; input-only rejoin %s; S04 exit at %d (%.1f,%.1f); '
              'range 1080 until then; replay identical' % (release['tick'], release['player']['y'], players[apex_tick]['y'], entry,
              before['speedX'], before['speedY'], at['speedX'], at['speedY'], self.S03_BAND_LANDING, land_y, landing['tick'],
              peaks[0]['fraction'], fall_height, names, s04_exit, final['x'], final['y']), flush=True)

    def test_03_transition_frames(self):
        """Stills at the section hand-offs, drawn by the production renderer at exact ticks: a filmstrip replay
        of the test_01 manifest (identical state hash) screenshots every 60 ticks; lower.webm is the full clip."""
        from PIL import Image
        from grapple_over_verify import execute, check_trace
        self.assertTrue(self.evidence.path('lower.webm').stat().st_size > 0)
        m = self.manifest(self.nominal(), self.TICKS)
        trace = execute(m, self.browser, self.url, str(self.evidence.path('runs/frames')), filmstrip=True)
        check_trace(m, trace)
        lower = json.loads(self.evidence.path('trace.json').read_text())
        self.assertEqual(state_hash(trace), lower['recorded_sha256'])
        players = self.players(trace)
        marks = [('S01-start', 0), ('S01-to-S02', 1500), ('S02-to-S03', 3240), ('S03-to-S04', 4560), ('S04-exit', self.TICKS-1)]
        frames = []
        for name, tick in marks:
            src = self.evidence.path('runs/frames/frame-%04d.png' % tick)
            self.assertTrue(src.exists(), src)
            shutil.copy(str(src), str(self.evidence.path('transitions/%s.png' % name)))
            p = players[tick]
            frames.append(dict(name=name, tick=tick, player=dict(x=p['x'], y=p['y']), file='transitions/%s.png' % name))
        shutil.rmtree(self.evidence.path('runs/frames'))
        w, h = VIEWPORT['width']//2, VIEWPORT['height']//2
        sheet = Image.new('RGB', (w*len(frames), h))
        for i, f in enumerate(frames):
            with Image.open(self.evidence.path(f['file'])) as img: sheet.paste(img.convert('RGB').resize((w, h)), (i*w, 0))
        sheet.save(self.evidence.path('transitions.jpg'), quality=80)
        self.evidence.write('transitions.json', dict(video='lower.webm', replay_sha256=state_hash(trace),
            matches_trace_json_recorded_sha256=True, frames=frames,
            note='frame-NNNN is drawn after the inputs of tick NNNN and one physics step; hand-off ticks rounded to the 60-tick filmstrip grid'))
        print('PASS transition frames: filmstrip replay identical to trace.json (%s), %d stills at the section hand-offs %s -> transitions.jpg'
              % (state_hash(trace)[:12], len(frames), [f['tick'] for f in frames]), flush=True)

    def test_04_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: runtime, level and harness match the tested worktree', flush=True)

class Task530Tests(unittest.TestCase):
    """Layout-v3 upper four sections joined: v3 S04-exit fixture -> S05 -> S06 -> S07 -> S08 summit finish, in one
    recording with trusted mouse input.

    The fixture is ONE labeled placement (initial_snapshot) of real state: the TASK-529 base-start S01..S04 run at
    tick 5787, dropping through S04-exit-drag 18 units above the S04 exit ledge, one tick before the player enters
    S05.rangeUpgradeZone (range still 1080). Not a full-game completion claim. From there the S05..S08 v3 routes run
    back to back with no placement, snapshot, spawn or velocity/mover reset: the range upgrade is earned in-run on the
    S04 exit ledge (the S05 entrance), every section settles on its green exit ledge (the next section's start), and
    every later section begins on the mover phase its section proof used (the movers are clocked by the simulation
    since the level load; the section starts sit at the isolated chain's 1400/1300/1400-tick spacing).
    The section proofs (TASK-517/518, 520/521, 523/524, 526/527) restore each start pose with a snapped camera; in this
    continuous run the eased camera rests elsewhere, and Chromium mouse input is integer CSS pixels (4 world units),
    so the isolated press points cannot be hit exactly. UPPER is the isolated routes with each press re-aimed to the
    nearest pixel (and a few press/release ticks shifted by 1-3) chosen so the run follows the isolated chain.
    """
    task_id = 'TASK-530'
    FIXTURE_TICK = 5787
    # Section starts (ticks from the fixture): S05 at the isolated S04 exit pose tick (6545-5787), then the isolated
    # chain spacing (S05 1400, S06 1300, S07 1400 ticks).
    SECTION_STARTS = dict(S05=758, S06=2158, S07=3458, S08=4858)
    PERIOD = 240
    # The v3 section routes (TASK-517/518 S05, TASK-520/521 S06, TASK-523/524 S07, TASK-526/527 S08), ticks relative to each
    # section start, re-aimed to the continuous camera: every press is the integer pixel nearest the isolated aim that keeps
    # the run on the isolated chain (aim moved 2.1..5.5 world units, at most 1.4 px). Retimed: S06-02 pressed 4 ticks early
    # and released 6 late (200/264, was 204/258), S06-03 pressed at 321 (319), S06-04 at 627/717 (628/718), S07-02..04 one
    # tick later (291/323, 631/701, 737/762). S08-04 is held until the finish, as in TASK-527.
    S05_UPPER = [(5,'mousedown',2544.0,-12453.554618784061),(150,'mouseup',2544.0,-12453.554618784061),
                 (304,'mousedown',3860.0,-10850.298590759949),(365,'mouseup',3860.0,-10850.298590759949),
                 (410,'mousedown',5263.585711890056,-9305.585082877235),(650,'mouseup',5263.585711890056,-9305.585082877235),
                 (655,'mousedown',4978.056484272573,-9093.539714470548),(775,'mouseup',4978.056484272573,-9093.539714470548)]
    S06_UPPER = [(5,'mousedown',4704.0,-9112.199723935715),(125,'mouseup',4704.0,-9112.199723935715),
                 (200,'mousedown',1988.0,-9660.294050566703),(264,'mouseup',1988.0,-9660.294050566703),
                 (321,'mousedown',1124.0,-10450.410099734427),(494,'mouseup',1124.0,-10450.410099734427),
                 (627,'mousedown',2644.0,-11503.996354718722),(717,'mouseup',2644.0,-11503.996354718722)]
    S07_UPPER = [(5,'mousedown',308.0,-11930.140890103135),(245,'mouseup',308.0,-11930.140890103135),
                 (291,'mousedown',1992.0,-12880.388956174498),(323,'mouseup',1992.0,-12880.388956174498),
                 (631,'mousedown',1432.0,-12944.0),(701,'mouseup',1432.0,-12944.0),
                 (737,'mousedown',2348.0,-11960.0),(762,'mouseup',2348.0,-11960.0)]
    S08_UPPER = [(185,'mousedown',2060.0,-13296.0),(303,'mouseup',2060.0,-13296.0),
                 (390,'mousedown',432.0,-13330.616848123203),(550,'mouseup',432.0,-13330.616848123203),
                 (627,'mousedown',4180.0,-13444.0),(672,'mouseup',4180.0,-13444.0),
                 (740,'mousedown',1398.3078238591097,-13469.42904665146)]
    UPPER = (lambda starts, plans: [(t+starts[k], e, x, y) for k, plan in plans for t, e, x, y in plan])(
        SECTION_STARTS, (('S05',S05_UPPER),('S06',S06_UPPER),('S07',S07_UPPER),('S08',S08_UPPER)))
    # The finish comes at 4858+809 (as in TASK-527's S08-full); the run continues 53 ticks into the frozen ending.
    TICKS = 5720

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        import test_grapple_over_sections as sections
        cls.S = sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.browser = LifecycleBrowser(browser)
        page = browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate('''() => ({sections:GRAPPLE_OVER_MOUNTAIN.sections,
            encounters:GRAPPLE_OVER_MOUNTAIN.encounters.slice(16,32),finish:GRAPPLE_OVER_MOUNTAIN.finish,
            connectors:GRAPPLE_OVER_MOUNTAIN.connectors.filter(c=>['S05','S06','S07','S08'].some(s=>c.id.startsWith(s))).map(c=>({id:c.id,from:c.from,to:c.to})),
            movers:GRAPPLE_OVER_MOUNTAIN.geometry.movers,upgradeSection:MODE_DEFINITIONS.grapple_over.rangeUpgradeSection,
            radius:{base:MODE_DEFINITIONS.grapple_over.acquisitionRadius,upgraded:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius},
            notice:I18N.t('climb.rangeUpgrade'),sectionRows:Object.fromEntries(GRAPPLE_OVER_MOUNTAIN.sections.map(s=>[s.id,
                I18N.t('climb.section',{value:I18N.t('climb.section.'+s.id)})]))})''')
        page.close()
        cls.hashes = hashes()
        cls.hashes['tools/test_grapple_over_integration.py'] = hashlib.sha256(
            (ROOT/'tools/test_grapple_over_integration.py').read_bytes()).hexdigest()
        cls.proof = dict(browser=browser.version, viewport=VIEWPORT, device_scale_factor=1,
            hz=60, seed=1, revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'],cwd=ROOT,text=True).splitlines(),
            source_hashes=cls.hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))
        cls.fixture, cls.fixture_proof = cls.make_fixture()

    # ---- fixture --------------------------------------------------------------------------------
    @classmethod
    def make_fixture(cls):
        """The real state of the TASK-529 base-start S01..S04 run (Task529Tests.nominal) at FIXTURE_TICK."""
        from grapple_over_verify import metadata, execute, check_trace, validate
        route = Task529Tests.nominal.__func__(type('Lower', (), dict(S=cls.S, SECTION_STARTS=Task529Tests.SECTION_STARTS)))
        m = dict(metadata=metadata('base-start'), ticks=cls.FIXTURE_TICK, expected_exit=dict(y=[-1e9, 1e9]),
                 inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in route if t < cls.FIXTURE_TICK],
                 required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        validate(m)
        trace = execute(m, cls.browser._browser, cls.url, str(cls.evidence.path('runs/fixture')))
        check_trace(m, trace)
        shutil.rmtree(cls.evidence.path('runs/fixture'))
        assert trace['metadata']['setupOnlySpawns'] == [] and m['metadata']['kind'] == 'base-start'
        sim = trace['snapshots'][-1]['state']['simulation']
        acquired = [e['after']['rope'][0]['id'] for e in trace['events'] if e['type'] == 'acquisition']
        proof = dict(label='v3 S04-exit fixture: real state of the TASK-529 base-start S01..S04 v3 run (Task529Tests.nominal inputs, '
                     'trusted mouse, no placement) at tick %d, falling through S04-exit-drag onto the S04 exit ledge one tick before '
                     'it enters S05.rangeUpgradeZone; range still 1080. One labeled placement; not a full-game completion claim' % cls.FIXTURE_TICK,
                     base_run_ticks=cls.FIXTURE_TICK, base_run_inputs=len(m['inputs']), base_run_acquisitions=acquired,
                     snapshot_sha256=trace['snapshots'][-1]['sha256'], base_run_sha256=state_hash(trace),
                     player=sim['player'], upgrades=sim['upgrades'], simulationTick=sim['simulationTick'], stats=sim['stats'])
        return sim, proof

    # ---- shared checks --------------------------------------------------------------------------
    mechanics = staticmethod(Task529Tests.mechanics)
    compact = Task529Tests.compact
    players = staticmethod(Task529Tests.players)

    def manifest(self):
        from grapple_over_verify import metadata, validate
        f = self.mountain['finish']
        m = dict(metadata=metadata('isolated'), initial_snapshot=self.fixture, ticks=self.TICKS,
                 inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.UPPER],
                 expected_exit=dict(x=[f['left'], f['right']], y=[f['top'], f['bottom']]),
                 required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        validate(m)
        self.assertNotIn('initial_setup', m)
        return m

    @staticmethod
    def in_box(p, b, pad=0):
        return b['left']-pad <= p['x'] <= b['right']+pad and b['top']-pad <= p['y'] <= b['bottom']+pad

    def finish(self, trace):
        rows = trace['snapshots']; done = [r['state']['simulation']['stats']['completed'] for r in rows]
        self.assertFalse(done[0])
        flips = [t for t in range(1, len(done)) if done[t] and not done[t-1]]
        self.assertEqual(len(flips), 1)
        tick = flips[0]
        self.assertTrue(all(done[tick:]))
        self.assertGreaterEqual(tick, self.SECTION_STARTS['S08'])
        p = rows[tick]['state']['simulation']['player']
        self.assertTrue(self.in_box(p, self.mountain['finish']), p)
        frozen = all(r['state']['simulation']['player'] == p for r in rows[tick:])
        self.assertTrue(frozen)
        return dict(completion_tick=tick, completed_transitions=len(flips), player={k: p[k] for k in ('x','y','speedX','speedY')},
                    finish_region=self.mountain['finish'], frozen_after=frozen, ticks_after=len(rows)-1-tick)

    def continuity(self, m, trace, done):
        sim = [r['state']['simulation'] for r in trace['snapshots']]
        self.assertEqual(m['metadata']['kind'], 'isolated')
        # The only placement is the labeled fixture (initial_snapshot before tick 0): no spawn, no mid-run injection.
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        self.assertIs(trace['metadata']['testOnly'], True)
        self.assertEqual(sim[0]['player'], self.fixture['player'])
        self.assertEqual(sim[0]['simulationTick'], self.fixture['simulationTick'])
        self.assertIs(sim[0]['upgrades']['range'], False)
        ticks = [s['simulationTick'] for s in sim]
        # The fixed-step clock advances 8 physics cycles every frame until the ending; the finish pauses play inside the
        # completing frame (a partial step), and the clock stays frozen from then on.
        steps = sorted({b-a for a, b in zip(ticks[:done], ticks[1:done])})
        self.assertEqual(len(steps), 1, steps); self.assertGreater(steps[0], 0)
        final_step = ticks[done]-ticks[done-1]
        self.assertTrue(0 < final_step <= steps[0], final_step)
        self.assertEqual(set(ticks[done:]), {ticks[done]})
        live = sim[:done+1]
        jumps = [max(abs(b['player']['x']-a['player']['x']), abs(b['player']['y']-a['player']['y'])) for a, b in zip(live, live[1:])]
        excess = max(j - 8*max(abs(a['player'][k]) for a in (u, v) for k in ('speedX', 'speedY')) for j, u, v in zip(jumps, live, live[1:]))
        self.assertLess(excess, 1, excess)
        self.assertLess(max(jumps), 40)
        ids = [e['id'] for e in sim[0]['elements']]
        self.assertTrue(all([e['id'] for e in s['elements']] == ids for s in sim))
        # Upper-section movers: small continuous steps and a strict 240-tick period across every section boundary
        # (a reset at a hand-off would break it), up to the completing frame; every non-mover element stays put.
        index = {k: i for i, k in enumerate(ids)}
        movers, period_error, mover_step = {}, 0, 0
        for v in self.mountain['movers']:
            if not v['element'].startswith(('S05','S06','S07','S08')): continue
            i, k = index[v['element']], v['axis']
            pos = [s['elements'][i][k] for s in sim[:done]]
            mover_step = max(mover_step, max(abs(b-a) for a, b in zip(pos, pos[1:])))
            period_error = max(period_error, max(abs(pos[t]-pos[t-self.PERIOD]) for t in range(self.PERIOD, len(pos))))
            self.assertAlmostEqual(min(pos), v['min'], delta=1); self.assertAlmostEqual(max(pos), v['max'], delta=1)
            movers[v['element']] = dict(axis=k, min=min(pos), max=max(pos),
                at_section_starts={s: round(pos[t], 3) for s, t in self.SECTION_STARTS.items()})
        self.assertEqual(len(movers), 8)
        self.assertLess(mover_step, 2)
        self.assertLess(period_error, 1e-6)
        mover_ids = {v['element'] for v in self.mountain['movers']}
        origin = {e['id']: (e['x'], e['y']) for e in sim[0]['elements']}
        moved = sorted({e['id'] for s in sim for e in s['elements'] if e['id'] not in mover_ids and (e['x'], e['y']) != origin[e['id']]})
        self.assertEqual(moved, [])
        heights = [s['stats']['maxHeight'] for s in sim]
        self.assertTrue(all(b >= a for a, b in zip(heights, heights[1:])))
        inputs = [e for e in trace['events'] if e['type'] == 'input']
        self.assertEqual(len(inputs), len(m['inputs']))
        self.assertTrue(all(e['trusted'] for e in inputs))
        presses = [e for e in inputs if e['event'] == 'mousedown']
        offscreen = [e['tick'] for e in presses if not (0 < e['client']['x'] < VIEWPORT['width'] and 0 < e['client']['y'] < VIEWPORT['height'])]
        self.assertEqual(offscreen, [])
        return dict(fixture=self.fixture_proof['label'], kind=m['metadata']['kind'], placements=1, initial_snapshot='fixture (before tick 0)',
            setup_only_spawns=trace['metadata']['setupOnlySpawns'], mid_run_injection=False, state_reset=False,
            initial_player=sim[0]['player'], simulation_ticks=[ticks[0], ticks[-1]], simulation_tick_increment=steps, completing_frame_step=final_step, clock_frozen_from_tick=done,
            max_player_step=max(jumps), max_step_beyond_8x_speed=excess, static_elements_moved=moved, upper_movers=movers,
            max_mover_step=mover_step, mover_period_ticks=self.PERIOD, max_mover_period_error=period_error, max_height_monotonic=True,
            trusted_inputs=len(inputs), offscreen_presses=offscreen,
            press_clients=[dict(tick=e['tick'], world=e['world'], client=e['client']) for e in presses])

    def upgrade(self, trace):
        """The upgrade tick, the S05 upgrade region it lies in, and the acquisition reaches before/after it."""
        sim = [r['state']['simulation'] for r in trace['snapshots']]
        s05 = next(s for s in self.mountain['sections'] if s['id'] == self.mountain['upgradeSection'])
        self.assertEqual(s05['id'], 'S05')
        # physics.js grants the upgrade in `rangeUpgradeZone ?? band` of the upgrade section (TASK-529: the zone).
        region = s05.get('rangeUpgradeZone') or s05['band']
        ranges = [s['upgrades']['range'] for s in sim]
        tick = next(t for t, r in enumerate(ranges) if r)
        self.assertGreater(tick, 0)
        self.assertFalse(any(ranges[:tick])); self.assertTrue(all(ranges[tick:]))
        p, before = sim[tick]['player'], sim[tick-1]['player']
        self.assertTrue(self.in_box(p, region), p)
        self.assertFalse(self.in_box(before, region), before)
        presses = [e['tick'] for e in trace['events'] if e['type'] == 'input' and e['event'] == 'mousedown']
        self.assertTrue(all(t > tick for t in presses))
        self.assertLess(tick, self.SECTION_STARTS['S05'])
        reaches = [dict(tick=e['tick'], element=e['after']['rope'][0]['id'], reach=e['after']['simulation']['grapple']['traveled'],
                        range_upgraded=ranges[e['tick']]) for e in trace['events'] if e['type'] == 'acquisition']
        self.assertTrue(all(r['range_upgraded'] for r in reaches))
        self.assertTrue(all(r['reach'] <= self.mountain['radius']['upgraded'] for r in reaches))
        beyond = [r for r in reaches if r['reach'] > self.mountain['radius']['base']]
        # Most upper gaps are only crossable at 1620 (the S05-01 hoist is 1429 away from the S04 exit ledge).
        self.assertGreaterEqual(len(beyond), 8)
        self.assertEqual(beyond[0]['element'], 'S05-hoist')
        return dict(upgrade_tick=tick, player={k: p[k] for k in ('x','y','speedX','speedY')},
            previous_tick_player={k: before[k] for k in ('x','y','speedX','speedY')}, s05_upgrade_region=region,
            s05_upgrade_region_source='S05.rangeUpgradeZone (physics.js: upgradeSection.rangeUpgradeZone ?? band)',
            s05_declared_band=s05['band'], inside_s05_upgrade_region=True,
            inside_s05_declared_band_rectangle=self.in_box(p, s05['band']),
            band_note='the v3 S05 route (S05-01 start y -11660.9 .. S05-04 exit y -9432) mostly lies above the abstract S05 band '
                      'rectangle (y -9720..-6480), which the v3 S03/S04 routes cross; TASK-529 made S05.rangeUpgradeZone the S05 upgrade '
                      'region, so the upgrade tick is the tick the player enters it on the S04 exit ledge (the S05 entrance)',
            range_false_ticks=[0, tick-1], range_true_ticks=[tick, len(ranges)-1], first_press_tick=presses[0],
            radius_before=self.mountain['radius']['base'], radius_after=self.mountain['radius']['upgraded'],
            acquisition_reaches=reaches, reaches_beyond_base_range=len(beyond), max_reach=max(r['reach'] for r in reaches))

    # ---- cases ----------------------------------------------------------------------------------
    def test_01_continuous_upper(self):
        from grapple_over_verify import execute, check_trace
        m = self.manifest()
        bounds = [*self.SECTION_STARTS.values(), self.TICKS]
        segments = [dict(section=k, start=bounds[i], end=bounds[i+1]) for i, k in enumerate(self.SECTION_STARTS)]
        self.evidence.write('inputs.json', dict(m, segments=segments, fixture=self.fixture_proof,
            scope='One labeled v3 S04-exit fixture placement (initial_snapshot = real base-start run state at tick %d), then trusted '
                  'Playwright mouse events only; no spawn, snapshot or velocity/mover reset at any section boundary; not a '
                  'full-game completion claim' % self.FIXTURE_TICK))
        self.browser.calls.clear()
        trace = execute(m, self.browser, self.url, str(self.evidence.path('runs/upper')), clip=True)
        lifecycle = list(self.browser.calls)
        check_trace(m, trace)
        self.evidence.path('runs/upper/trace.json').unlink()
        shutil.move(str(self.evidence.path('runs/upper/clip.webm')), str(self.evidence.path('upper.webm')))
        self.browser.calls.clear()
        replay = execute(m, self.browser, self.url, str(self.evidence.path('runs/upper-replay')))
        replay_lifecycle = list(self.browser.calls)
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        recorded, replayed = state_hash(trace), state_hash(replay)
        del replay
        shutil.rmtree(self.evidence.path('runs'))
        players = self.players(trace)
        finish = self.finish(trace)
        done = finish['completion_tick']
        continuity = self.continuity(m, trace, done)
        upgrade = self.upgrade(trace)
        exits = Task529Tests.first_exit_ticks(self, players, self.mountain['encounters'])
        order = [exits[e['id']] for e in self.mountain['encounters']]
        self.assertTrue(all(t is not None for t in order), exits)
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(order), 16)
        mech = self.mechanics(trace)
        acquired = [x['element'] for x in mech if x['type'] == 'acquisition']
        self.assertEqual(acquired, ['S05-hoist','S05-lift','S05-pull-hook','S05-exit-hook','S06-carriage','S06-lift','S06-climb-hook',
            'S06-exit-hook','S07-trolley','S07-carriage','S07-gable-hook','S07-exit-ledge','S08-mast-trolley','S08-beacon-trolley',
            'S08-east-wall','S08-roof'])
        encounters = []
        for e in self.mountain['encounters']:
            touched = [x for x in mech if x['element'] in e['elements'] and x['type'] in ('acquisition','bounce')]
            self.assertTrue(touched, e['id'])
            encounters.append(dict(id=e['id'], section=e['section'], exit=exit_box(e['exit']), first_exit_tick=exits[e['id']],
                                   first_interaction=touched[0], interactions=len(touched)))
        # Each section starts settled on its green entrance ledge (the previous section's exit), at its declared start.
        handoffs = []
        starts = {e['id']: e['start'] for e in self.mountain['encounters']}
        for section, encounter in (('S05','S05-01'),('S06','S06-01'),('S07','S07-01'),('S08','S08-01')):
            t = self.SECTION_STARTS[section]; p = players[t]; d = starts[encounter]
            h = dict(into=section, tick=t, connector=section+'-entrance', player={k: p[k] for k in ('x','y','speedX','speedY')},
                     carried_speed=math.hypot(p['speedX'], p['speedY']), declared_start=d,
                     distance_to_declared_start=math.hypot(p['x']-d['x'], p['y']-d['y']),
                     simulation_tick=trace['snapshots'][t]['state']['simulation']['simulationTick'],
                     mover_phase_ticks=(trace['snapshots'][t]['state']['simulation']['simulationTick']//continuity['simulation_tick_increment'][0]) % self.PERIOD)
            self.assertLess(h['carried_speed'], .1, h)
            self.assertLess(h['distance_to_declared_start'], 6, h)
            handoffs.append(h)
        self.assertEqual([c['id'] for c in self.mountain['connectors'] if c['id'].endswith('entrance')],
                         ['S05-entrance','S06-entrance','S07-entrance','S08-entrance'])
        completed = [c for c in lifecycle if c['name'] == 'level_completed']
        self.assertEqual(len(completed), 1)
        self.assertEqual([c['name'] for c in replay_lifecycle if c['name'] == 'level_completed'], ['level_completed'])
        self.assertEqual((completed[0]['x'], completed[0]['y']), (finish['player']['x'], finish['player']['y']))
        self.assertGreater(exits['S08-04'], exits['S08-03'])
        self.assertEqual(exits['S08-04'], done)
        result = dict(name='v3 S04-exit fixture to summit finish (layout v3 S05-S08)', passed=True, matching_replay=True,
            full_game_completion=False, recorded_sha256=recorded, replayed_sha256=replayed, ticks=m['ticks'],
            fixture=self.fixture_proof, finish=finish,
            ending=dict(completed_transitions=finish['completed_transitions'], level_completed_calls=len(completed),
                        recorded_lifecycle=lifecycle, replayed_lifecycle=replay_lifecycle),
            upgrade=upgrade, encounter_exits_in_order=True, encounter_exit_ticks=order, encounters=encounters,
            handoffs=handoffs, acquisitions=acquired, continuity=continuity, proof=self.proof, video='upper.webm', inputs='inputs.json',
            trace=self.compact(trace))
        self.evidence.write('trace.json', result)
        print('PASS continuous upper: 1 labeled v3 S04-exit fixture (base-run tick %d), %d trusted inputs, %d ticks, range upgrade at tick %d '
              '(%.1f,%.1f in S05.rangeUpgradeZone, 1080 before, 1620 after; %d reaches > 1080, max %.1f), 16/16 upper encounter exits in '
              'order %s, hand-offs %s, finish at tick %d (%.1f,%.1f) with exactly one level_completed; replay identical'
              % (self.FIXTURE_TICK, continuity['trusted_inputs'], m['ticks'], upgrade['upgrade_tick'], upgrade['player']['x'], upgrade['player']['y'],
                 upgrade['reaches_beyond_base_range'], upgrade['max_reach'], order,
                 [(h['into'], round(h['player']['x'],1), round(h['player']['y'],1)) for h in handoffs], done,
                 finish['player']['x'], finish['player']['y']), flush=True)

    def test_02_transition_frames(self):
        """Stills drawn by the production renderer at exact ticks (a filmstrip replay of the test_01 manifest with the HUD layout
        probe, identical state hash): the upgrade notice after the fixture, each section hand-off and the finish."""
        from PIL import Image
        from grapple_over_verify import execute, check_trace
        self.assertTrue(self.evidence.path('upper.webm').stat().st_size > 0)
        upper = json.loads(self.evidence.path('trace.json').read_text())
        m = self.manifest(); m['metadata']['layout_probe'] = True
        trace = execute(m, self.browser._browser, self.url, str(self.evidence.path('runs/frames')), filmstrip=True)
        check_trace(m, trace)
        self.assertEqual(state_hash(trace), upper['recorded_sha256'])
        probe = json.loads(self.evidence.path('runs/frames/layout-probe.json').read_text())['frames']
        texts = {int(t): [b['name'] for b in v['boxes'] if b['kind'] == 'text'] for t, v in probe.items()}
        up = upper['upgrade']['upgrade_tick']; done = upper['finish']['completion_tick']
        notice = sorted(t for t, names in texts.items() if self.mountain['notice'] in names)
        # The one-time HUD notice is drawn after the in-run upgrade for its 3 s and never again (frame N shows state N+1).
        self.assertTrue(notice and all(up <= t+1 <= up+180 for t in notice), notice)
        self.assertIn(60, notice)
        rows = self.mountain['sectionRows']
        order = []
        for t in sorted(texts):
            sec = next((s for s, row in rows.items() if row in texts[t]), None)
            if sec and (not order or order[-1][0] != sec): order.append((sec, t))
        # Recorded, not ordered: the HUD section row names the first section with an encounter element within 300 of the
        # player's height (menu.js drawHud), so it flickers where the v3 sections overlap in height.
        self.assertTrue(all(any(sec == k for sec, _ in order) for k in ('S05','S06','S07','S08')), order)
        players = self.players(trace)
        grid = lambda t: min((f for f in texts), key=lambda f: abs(f-t))
        marks = [('fixture-upgrade-notice', 60)] + [('%s-start' % s, grid(t)) for s, t in self.SECTION_STARTS.items()] + \
                [('finish', min(f for f in texts if f > done))]
        frames = []
        for name, tick in marks:
            src = self.evidence.path('runs/frames/frame-%04d.png' % tick)
            self.assertTrue(src.exists(), src)
            shutil.copy(str(src), str(self.evidence.path('transitions/%s.png' % name)))
            p = players[tick]
            frames.append(dict(name=name, tick=tick, player=dict(x=p['x'], y=p['y']), hud_text=texts[tick],
                               file='transitions/%s.png' % name))
        shutil.rmtree(self.evidence.path('runs/frames'))
        w, h = VIEWPORT['width']//2, VIEWPORT['height']//2
        sheet = Image.new('RGB', (w*3, h*2))
        for i, f in enumerate(frames):
            with Image.open(self.evidence.path(f['file'])) as img: sheet.paste(img.convert('RGB').resize((w, h)), ((i % 3)*w, (i//3)*h))
        sheet.save(self.evidence.path('transitions.jpg'), quality=80)
        self.evidence.write('transitions.json', dict(video='upper.webm', replay_sha256=state_hash(trace), matches_trace_json_recorded_sha256=True,
            upgrade_tick=up, notice_text=self.mountain['notice'], notice_frames=notice, hud_section_changes=order, frames=frames,
            note='frame-NNNN is drawn after the inputs of tick NNNN and one physics step; filmstrip frames every 60 ticks and at every input'))
        print('PASS transition frames: filmstrip replay identical to trace.json (%s); notice %r drawn at frames %s (upgrade tick %d); HUD section '
              'row changes %s; %d stills -> transitions.jpg' % (state_hash(trace)[:12], self.mountain['notice'], notice, up, order, len(frames)), flush=True)

    def test_03_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: runtime, level and harness match the tested worktree', flush=True)

if __name__ == '__main__':
    unittest.main()
