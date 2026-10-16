"""Continuous mountain proofs from the base, driven only by trusted input events."""
import hashlib
import json
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


if __name__ == '__main__':
    unittest.main()
