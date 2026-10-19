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

class Task489Tests(Task529Tests):
    """Lower join, re-specced by TASK-533 from layout v1 to layout v3 (same cases as Task529Tests).

    v1 test_01_continuous_lower (base -> S01..S04 exit, v1 hand-offs) -> test_01 v3 continuous base-start run;
    v1 test_02_cross_section_recovery (S04 fall into the S03 band, re-climb) -> test_02 v3 S04 -> S03 fall and
    input-only rejoin; plus the v3 transition frames; source hashes kept.
    """
    task_id = 'TASK-489'


class Task490Tests(Task530Tests):
    """Upper join, re-specced by TASK-533 from layout v1 to layout v3 (same cases as Task530Tests).

    v1 test_01_continuous_upper (v1 S04-exit fixture -> S05..S08 finish) -> test_01 v3 run from the labeled v3
    S04-exit fixture with the in-run range upgrade; plus the v3 transition frames; source hashes kept.
    """
    task_id = 'TASK-490'


# TASK-531: in-page sampler for the bypass search and the labeled start-state chain. It only reads production state
# and calls production physics(); input is trusted Playwright mouse events.
LITE_JS = '''() => {
    const box = e => {
        const xs = e.points.map(p => p.x), ys = e.points.map(p => p.y)
        return {left: e.x + Math.min(...xs), right: e.x + Math.max(...xs), top: e.y + Math.min(...ys), bottom: e.y + Math.max(...ys)}
    }
    const bounce = Ninja.prototype.applyBounce
    Ninja.prototype.applyBounce = function(contact) {
        const r = T531.rec
        if (r && contact.approaching) r.bounces.push([r.tick, contact.element.id])
        return bounce.call(this, contact)
    }
    window.T531 = {
        exits: [], rec: null,
        targets(radius) {
            const p = ninja
            return floors[0].elements.filter(e => e.grapplable !== false && e.id).map(e => {
                const b = box(e), nx = Math.min(Math.max(p.x, b.left), b.right), ny = Math.min(Math.max(p.y, b.top), b.bottom)
                return {id: e.id, center: {x: (b.left + b.right) / 2, y: (b.top + b.bottom) / 2}, nearest: {x: nx, y: ny},
                        distance: Math.hypot(nx - p.x, ny - p.y)}
            }).filter(t => t.distance <= radius)
        },
        state() {
            return {x: ninja.x, y: ninja.y, speedX: ninja.speedX, speedY: ninja.speedY, range: floors[0].rangeUpgraded,
                    radius: grappleOverAcquisitionRadius(), throwed: grapnel.throwed, pressHeld}
        },
        // n production ticks (physics() is one fixed step), sampling the player after each.
        run(n, rec) {
            this.rec = rec
            for (let i = 0; i < n; i++) {
                physics(); TUTORIAL_HINT.advance(physicsStepMs); rec.tick++
                const x = ninja.x, y = ninja.y
                if (y < rec.minY) {rec.minY = y; rec.minYTick = rec.tick}
                for (const e of this.exits)
                    if (!(e.id in rec.exits) && x >= e.left && x <= e.right && y >= e.top && y <= e.bottom) rec.exits[e.id] = rec.tick
                const g = grapnel.isGrappled()
                if (g && !rec.grappled) {
                    const a = grapnel.pos[0] && grapnel.pos[0][2]
                    rec.acquisitions.push([rec.tick, a && a.id || null, Math.round(grapnel.traveled*10)/10])
                }
                rec.grappled = g
                if (floors[0].climbStats.completed) rec.completed = true
            }
            this.rec = null
            return rec
        },
        // Keep stepping until the player has stayed within a 3-unit box for 60 ticks (settled) or `limit` ticks pass.
        settle(limit, rec) {
            const xs = [], ys = []
            rec.settled = false
            for (let i = 0; i < limit; i++) {
                this.run(1, rec); xs.push(ninja.x); ys.push(ninja.y)
                if (xs.length > 60) {xs.shift(); ys.shift()}
                if (xs.length === 60 && Math.max(...xs) - Math.min(...xs) < 3 && Math.max(...ys) - Math.min(...ys) < 3) {
                    rec.settled = true; break
                }
            }
            return rec
        },
    }
}'''


class LitePage:
    """One production page driven tick by tick with trusted mouse input and no per-tick recorder (TASK-531).

    Verified bit-identical to grapple_over_verify.execute: the TASK-529 base run reproduces its recorded S04-exit pose.
    """
    def __init__(self, browser, url, exits):
        from grapple_over_support import install_recorder
        from perf_mobile import SEED_SCRIPT
        self.context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.add_init_script(SEED_SCRIPT % 1)
        self.page.goto(url); wait_for_boot(self.page)
        self.page.evaluate("cancelAnimationFrame(game); window.requestAnimationFrame=()=>0; startGame('grapple_over'); CLIMB_UI.restart()")
        self.page.wait_for_function('!unTouch')
        self.page.mouse.up()
        install_recorder(self.page)
        self.page.evaluate(LITE_JS)
        self.page.evaluate('e=>{T531.exits=e}', exits)
        self.hud = None

    def restore(self, state):
        self.page.evaluate('s=>restoreClimbState(s)', state)

    def reset(self):
        """A fresh Grapple Over game, as at boot (after a completed run the completion screen has left the climb)."""
        self.page.evaluate("startGame('grapple_over'); CLIMB_UI.restart()")
        self.page.wait_for_function('!unTouch')
        self.page.mouse.up()

    @staticmethod
    def new_rec():
        return dict(tick=0, minY=1e18, minYTick=0, exits={}, acquisitions=[], bounces=[], grappled=False, completed=False)

    def play(self, plan, ticks, capture=(), rec=None):
        """Run `ticks` ticks with trusted mouse events at the plan ticks; capture full climb states at `capture` ticks."""
        rec = rec or self.new_rec()
        marks = sorted({0, ticks, *[p[0] for p in plan], *capture})
        states, clients, dropping = {}, [], False
        for a, b in zip(marks, marks[1:]):
            if a in capture: states[a] = self.page.evaluate('captureClimbState()')
            for t, e, x, y in (p for p in plan if p[0] == a):
                c = self.page.evaluate('p=>GRAPPLE_OVER_TEST.client(p)', dict(x=x, y=y))
                on = 0 < c['x'] < VIEWPORT['width'] and 0 < c['y'] < VIEWPORT['height']
                clients.append(dict(tick=t, event=e, world=dict(x=x, y=y), client=c, onscreen=on))
                # With `hud` set (controlled replays), a press whose client point is on a HUD button is not dispatched
                # (it would pause the game), nor is its release.
                if e == 'mousedown' and self.hud and any(h['x']-4 <= c['x'] <= h['x']+h['width']+4 and
                                                         h['y']-4 <= c['y'] <= h['y']+h['height']+4 for h in self.hud):
                    dropping = clients[-1]['dropped_on_hud'] = True; continue
                if e == 'mouseup' and dropping:
                    dropping, clients[-1]['dropped_on_hud'] = False, True; continue
                self.page.mouse.move(c['x'], c['y'])
                (self.page.mouse.down if e == 'mousedown' else self.page.mouse.up)()
            rec = self.page.evaluate('([n,r])=>T531.run(n,r)', [b - a, rec])
        if ticks in capture: states[ticks] = self.page.evaluate('captureClimbState()')
        return rec, states, clients


class Task531Tests(unittest.TestCase):
    """Layout-v3 fall chain and lower-section bypass audit under the upgraded range.

    test_01: for each section S02..S08, one recorded mistimed release from a labeled reachable start state (the real
    section start pose of the chain that proves that section, restored once) falls into the section below through the
    drag zone under it and rejoins by input only. test_02: with 1620 earned and the player back in S01..S04, a bounded,
    logged search of one- and two-press routes for any that skips more than one encounter (not a universal
    impossibility claim). test_03: a confirmed restart returns the range to 1080.
    """
    task_id = 'TASK-531'
    PERIOD = 240
    # Section start states, by the chains the section proofs use (no placement up to the S05 start; then one labeled
    # restore of the previous section's exit pose per section, as TASK-518/521/524/527): (base-run tick | restore chain).
    BASE_TICKS = dict(S02=1495, S03=3245, S04=4545, S05=6545)
    START_POSES = dict(S03=(5955.4, -4870.9), S04=(6127.0, -7781.1), S05=(1387.9, -11660.9), S06=(6120.4, -9432.4),
                       S07=(1543.2, -11261.3), S08=(2608.9, -11971.5))

    @classmethod
    def falls_spec(cls):
        """Per section: the recorded mistimed release of its section proof, the landing in the section below, the drag
        zones crossed, the input-only rejoin and the bounds it ends in (all taken from the section proof classes)."""
        S = cls.S
        SB, VC, DC, GC = S.SwitchbackV3CompleteChecks, S.ViaductV3CompleteChecks, S.DeflectorV3CompleteChecks, S.GalleriesV3CompleteChecks
        LC, CC, UC = S.LiftworksV3CompleteChecks, S.CrownV3CompleteChecks, S.SummitV3CompleteChecks
        return [
            dict(section='S02', source='TASK-551 SwitchbackV3CompleteChecks.FALL_S02', plan=SB.FALL_S02, ticks=SB.FALL_S02_TICKS,
                 release=(620, 'S02-crown-hook'), nominal_release=622, landing='S01-exit-pad', drags=['S02-exit-drag', 'S01-exit-drag'],
                 rejoin_tick=SB.REJOIN_S02_TICK, end=SB.S02_02_EXIT, rejoin_goal='S02-02 exit (bulkhead rebound)'),
            dict(section='S03', source='TASK-554 ViaductV3CompleteChecks.FALL_S03', plan=VC.FALL_S03, ticks=VC.FALL_S03_TICKS,
                 release=(VC.EARLY_RELEASE, 'S03-crest-hook'), nominal_release=VC.CREST_RELEASE, landing='S02-exit-ledge', drags=['S02-exit-drag'],
                 rejoin_tick=VC.REJOIN_S03_TICK, end=VC.S03_04_EXIT, rejoin_goal='S03-04 exit (S03 exit ledge, section exit)'),
            dict(section='S04', source='TASK-515 DeflectorV3CompleteChecks.FALL_S04', plan=DC.FALL_S04, ticks=DC.FALL_S04_TICKS,
                 release=(DC.LATE_RELEASE, 'S04-hoist'), nominal_release=370, landing='S03-exit-ledge', drags=['S03-exit-drag'],
                 rejoin_tick=DC.REJOIN_S04_TICK, end=DC.S04_04_EXIT, rejoin_goal='S04-04 exit (S04 exit ledge, section exit)'),
            dict(section='S05', source='TASK-518 GalleriesV3CompleteChecks.FALL_S05', plan=GC.FALL_S05, ticks=GC.FALL_S05_TICKS,
                 release=(GC.SHORT_RELEASE, 'S05-hoist'), nominal_release=150, landing='S04-exit-ledge', drags=['S04-exit-drag'],
                 rejoin_tick=GC.REJOIN_TICK, end=GC.S05_04_EXIT, rejoin_goal='S05-04 exit (S05 exit ledge, section exit)'),
            cls.s06_fall(),
            dict(section='S07', source='TASK-524 CrownV3CompleteChecks.FALL_S07', plan=CC.FALL_S07, ticks=CC.FALL_S07_TICKS,
                 release=(CC.SHORT_GABLE_RELEASE, 'S07-gable-hook'), nominal_release=CC.SHORT_GABLE_RELEASE+30, landing='S06-drop-ledge',
                 drags=['S07-short-drag', 'S06-drop-drag'], rejoin_tick=CC.REJOIN_TICK, end=CC.REJOIN_END,
                 rejoin_goal='S07-02 exit (the flight west along the crown top) after re-climbing S06-03/04 and S07-01'),
            dict(section='S08', source='TASK-527 SummitV3CompleteChecks.FALL_S08', plan=UC.FALL_S08, ticks=UC.FALL_S08_TICKS,
                 release=(UC.SHORT_WALL_RELEASE, 'S08-east-wall'), nominal_release=UC.WALL_RELEASE, landing='S07-crown-ledge',
                 drags=['S08-crest-drag', 'S07-crown-drag'], rejoin_tick=UC.REJOIN_TICK, end=UC.REJOIN_END,
                 rejoin_goal='S08-02 exit (the flight east under the roof) after the S07 exit ledge'),
        ]

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        import test_grapple_over_sections as sections
        cls.S = sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        page = cls.browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate('''() => {const box = e => ({id:e.id, role:e.role,
                left:e.x+Math.min(...e.points.map(p=>p.x)), right:e.x+Math.max(...e.points.map(p=>p.x)),
                top:e.y+Math.min(...e.points.map(p=>p.y)), bottom:e.y+Math.max(...e.points.map(p=>p.y))});
            return {sections:GRAPPLE_OVER_MOUNTAIN.sections.map(s=>({id:s.id, band:s.band, rangeUpgradeZone:s.rangeUpgradeZone||null})),
                encounters:GRAPPLE_OVER_MOUNTAIN.encounters.slice(0,32).map(e=>({id:e.id, section:e.section, start:e.start, exit:e.exit})),
                spawn:GRAPPLE_OVER_MOUNTAIN.spawn, finish:GRAPPLE_OVER_MOUNTAIN.finish,
                drags:GRAPPLE_OVER_MOUNTAIN.geometry.elements.filter(e=>e.role==='drag').map(box),
                radius:{base:MODE_DEFINITIONS.grapple_over.acquisitionRadius, upgraded:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius},
                physics:{gravityPerCycle:GRAVITY, cyclesPerTick, dragHorizontal:DRAG_ZONE_HORIZONTAL_DAMPING, dragVertical:DRAG_ZONE_VERTICAL_DAMPING}}}''')
        page.close()
        cls.drags = {d['id']: d for d in cls.mountain['drags']}
        cls.exits = [dict(id=e['id'], index=i, **exit_box(e['exit'])) for i, e in enumerate(cls.mountain['encounters'])]
        cls.hashes = hashes()
        cls.hashes['tools/test_grapple_over_integration.py'] = hashlib.sha256(
            (ROOT/'tools/test_grapple_over_integration.py').read_bytes()).hexdigest()
        cls.proof = dict(browser=cls.browser.version, viewport=VIEWPORT, device_scale_factor=1,
            hz=60, seed=1, revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'],cwd=ROOT,text=True).splitlines(),
            source_hashes=cls.hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))
        cls.lite = LitePage(cls.browser, cls.url, cls.exits)
        cls.addClassCleanup(cls.lite.context.close)
        cls.starts, cls.start_proof = cls.section_starts()

    # ---- labeled start states -------------------------------------------------------------------
    @classmethod
    def section_starts(cls):
        """Real section start poses by the section proofs' chains: one base-start trusted-input run of the v3 S01..S04 routes
        (S02..S05 starts at its section ticks), then the S05, S06 and S07 routes each from ONE labeled restore of the
        previous exit pose (the TASK-518/521/524 S0N-full chains)."""
        S = cls.S
        route = Task529Tests.nominal.__func__(type('Lower', (), dict(S=S, SECTION_STARTS=Task529Tests.SECTION_STARTS)))
        lite = cls.lite
        lite.page.evaluate('CLIMB_UI.restart()')
        base0 = lite.page.evaluate('captureClimbState()')
        assert (base0['player']['x'], base0['player']['y'], base0['simulationTick']) == (2160, 0, 0), base0['player']
        rec, states, clients = lite.play(route, cls.BASE_TICKS['S05'], capture=set(cls.BASE_TICKS.values()))
        base_exits = dict(rec['exits'])
        starts = {k: states[t] for k, t in cls.BASE_TICKS.items()}
        chain = [('S06', S.GalleriesV3CompleteChecks.S05_ROUTE_V3, S.GalleriesV3CompleteChecks.S05_FULL_TICKS, 'S05'),
                 ('S07', S.LiftworksV3CompleteChecks.S06_ROUTE_V3, S.LiftworksV3CompleteChecks.S06_FULL_TICKS, 'S06'),
                 ('S08', S.CrownV3CompleteChecks.S07_ROUTE_V3, S.CrownV3CompleteChecks.S07_FULL_TICKS, 'S07')]
        restores = []
        for section, plan, ticks, previous in chain:
            lite.restore(starts[previous])
            _, out, c = lite.play(plan, ticks, capture={ticks})
            starts[section] = out[ticks]
            restores.append(dict(start=section, restored=previous + ' start (previous section exit pose)', route_ticks=ticks,
                                 inputs=len(plan), all_presses_on_screen=all(x['onscreen'] for x in c if x['event'] == 'mousedown')))
        for k, pose in cls.START_POSES.items():
            p = starts[k]['player']
            assert (round(p['x'], 1), round(p['y'], 1)) == pose, (k, p)
        assert starts['S05']['upgrades']['range'] is True and starts['S04']['upgrades']['range'] is False
        proof = dict(label='labeled section start states: the real start pose of each section by the chain its section proof uses; '
                     'each fall run restores exactly one of them before tick 0', base_run=dict(kind='base-start', inputs=len(route),
                     ticks=cls.BASE_TICKS['S05'], trusted_mouse=True, all_presses_on_screen=all(x['onscreen'] for x in clients if x['event'] == 'mousedown'),
                     first_exit_ticks=base_exits, section_ticks=cls.BASE_TICKS), restore_chain=restores,
                     poses={k: dict(player={f: v['player'][f] for f in ('x','y','speedX','speedY')}, range=v['upgrades']['range'],
                                    simulationTick=v['simulationTick'], matches_section_proof_pose=cls.START_POSES.get(k))
                            for k, v in sorted(starts.items())}, page_errors=list(lite.errors))
        return starts, proof

    # ---- falls ----------------------------------------------------------------------------------
    def fall_run(self, spec):
        """Record one mistimed-release run from the labeled section start with the audited harness; return the analysis."""
        from grapple_over_verify import metadata, execute, check_trace, validate
        start = self.starts[spec['section']]
        m = dict(metadata=metadata('isolated'), initial_snapshot=start, ticks=spec['ticks'], expected_exit=spec['end'],
                 inputs=[dict(tick=t, event=e, world=dict(x=x, y=y)) for t, e, x, y in spec['plan']],
                 required_events=['acquisition', 'release', 'bounce'])
        m['metadata']['compact_contacts'] = True
        validate(m)
        out = 'falls/' + spec['section']
        trace = execute(m, self.browser, self.url, str(self.evidence.path(out)))
        check_trace(m, trace)
        shutil.rmtree(self.evidence.path(out))
        return m, trace

    def analyse_fall(self, spec, m, trace):
        players = Task529Tests.players(trace)
        mech = Task529Tests.mechanics(trace)
        sim0 = trace['snapshots'][0]['state']['simulation']
        self.assertEqual(sim0['player'], self.starts[spec['section']]['player'])
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        inputs = [e for e in trace['events'] if e['type'] == 'input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        presses = [e for e in inputs if e['event'] == 'mousedown']
        self.assertTrue(all(0 < e['client']['x'] < VIEWPORT['width'] and 0 < e['client']['y'] < VIEWPORT['height'] for e in presses))
        tick, element = spec['release']
        release = next(x for x in mech if x['type'] == 'release' and x['element'] == element and x['tick'] == tick)
        below = 'S%02d' % (int(spec['section'][1:]) - 1)
        self.assertTrue(spec['landing'].startswith(below + '-'), spec)
        rejoin = spec['rejoin_tick']
        land = next(x for x in mech if x['type'] == 'bounce' and x['element'] == spec['landing'] and tick < x['tick'] < rejoin)
        self.assertFalse([x for x in mech if x['type'] == 'acquisition' and tick < x['tick'] < rejoin])
        self.assertFalse(any(trace['snapshots'][t]['state']['simulation']['grapple'].get('grappled') for t in range(tick+1, rejoin)))
        apex = min(range(tick, land['tick']), key=lambda t: players[t]['y'])
        inside = lambda p, b: b['left'] <= p['x'] <= b['right'] and b['top'] <= p['y'] <= b['bottom']
        contact = next(e for e in trace['events'] if e['type'] == 'bounce' and e['tick'] == land['tick'])
        at_land = contact['before']['simulation']['player']
        zones = []
        for zid in spec['drags']:
            box = self.drags[zid]
            ticks = [t for t in range(tick, land['tick']+1) if inside(players[t], box)]
            self.assertTrue(ticks, zid)
            entry, leave = ticks[0], ticks[-1]
            before = players[entry-1] if entry > tick else players[tick]
            last = at_land if leave == land['tick'] else players[leave]
            # Undamped counterfactual: the entry vy plus gravity for every cycle up to the last tick inside (no contact before the
            # landing). The zone multiplies vx and vy by the drag factors once per tick while the player overlaps it.
            ph = self.mountain['physics']
            vy_free = before['speedY'] + ph['gravityPerCycle'] * ph['cyclesPerTick'] * (leave - entry)
            zones.append(dict(id=zid, box={k: box[k] for k in ('left','right','top','bottom')}, entry_tick=entry, last_tick_inside=leave,
                undamped_vy_at_last_tick=vy_free, damping_per_tick=dict(vx=ph['dragHorizontal'], vy=ph['dragVertical']),
                before=dict(tick=entry-1, **{k: before[k] for k in ('x','y','speedX','speedY')}),
                after=dict(tick=leave, at='landing contact' if leave == land['tick'] else 'last tick inside',
                           **{k: last[k] for k in ('x','y','speedX','speedY')}),
                vx_reduced=abs(last['speedX']) <= abs(before['speedX']) + 1e-9, vy_reduced_vs_undamped=last['speedY'] < vy_free,
                vy_reduced_vs_entry=last['speedY'] < before['speedY'],
                ticks_inside=len(ticks)))
        # The drag zone above the landing is the last one crossed: it reduces both speed components on the way down.
        final = zones[-1]
        self.assertEqual(final['last_tick_inside'], land['tick'])
        self.assertLessEqual(abs(final['after']['speedX']), abs(final['before']['speedX']) + 1e-9, final)
        self.assertLess(final['after']['speedY'], final['undamped_vy_at_last_tick'], final)
        bounces = [x for x in mech if x['type'] == 'bounce' and x['element'] == spec['landing'] and land['tick'] <= x['tick'] < rejoin]
        rest_y = max(players[t]['y'] for t in range(rejoin-40, rejoin))
        fall_height = rest_y - players[apex]['y']
        self.assertGreater(fall_height, 0)
        nxt = bounces[1]['tick'] if len(bounces) > 1 else rejoin
        peak = min(range(land['tick'], nxt), key=lambda t: players[t]['y'])
        fraction = (rest_y - players[peak]['y']) / fall_height
        self.assertLessEqual(fraction, .5)
        settled = players[rejoin-40:rejoin]
        self.assertTrue(all(abs(p['speedX']) < .01 for p in settled), settled[-1])
        landing_box = self.drags[spec['drags'][-1]]
        self.assertTrue(all(inside(p, landing_box) for p in settled))
        after = [x for x in mech if x['tick'] >= rejoin and x['type'] == 'acquisition']
        self.assertTrue(after)
        final_p = players[-1]
        self.assertTrue(all(spec['end'][k][0] <= final_p[k] <= spec['end'][k][1] for k in spec['end']), final_p)
        ranges = [r['state']['simulation']['upgrades']['range'] for r in trace['snapshots']]
        return dict(section=spec['section'], start_section=spec['section'], landing_section=below, source=spec['source'],
            start=dict(label='labeled section start state (restored once before tick 0)', pose=sim0['player'], range_upgraded=sim0['upgrades']['range']),
            release=dict(tick=tick, element=element, nominal_release_tick=spec['nominal_release'], player=release['player']),
            apex=dict(tick=apex, player={k: players[apex][k] for k in ('x','y','speedX','speedY')}),
            landing=dict(tick=land['tick'], element=spec['landing'], section=below, player={k: at_land[k] for k in ('x','y','speedX','speedY')}),
            acquisitions_between_release_and_rejoin=0, drag_zones=zones,
            drag_zone_above_landing=dict(id=final['id'], vx_before=final['before']['speedX'], vy_before=final['before']['speedY'],
                                         vx_after=final['after']['speedX'], vy_after=final['after']['speedY'],
                                         undamped_vy=final['undamped_vy_at_last_tick'], vy_after_over_undamped=final['after']['speedY']/final['undamped_vy_at_last_tick']),
            fall_height=fall_height, rest_y=rest_y, first_bounce=dict(tick=land['tick'], peak_tick=peak, peak_y=players[peak]['y'],
                peak_height=rest_y-players[peak]['y'], fraction_of_fall_height=fraction, at_most_half=fraction <= .5),
            settled_before_rejoin=dict(window=[rejoin-40, rejoin-1], inside=spec['drags'][-1], player={k: settled[-1][k] for k in ('x','y','speedX','speedY')}),
            rejoin=dict(result='rejoined', input_only=True, tick=rejoin, goal=spec['rejoin_goal'], inputs=[i for i in m['inputs'] if i['tick'] >= rejoin],
                        acquisitions=[{k: x[k] for k in ('tick','element')} for x in after], end_bounds=spec['end'],
                        final={k: final_p[k] for k in ('x','y','speedX','speedY')}, final_in_end_bounds=True),
            range_during_run=sorted(set(ranges)), ticks=m['ticks'], trusted_inputs=len(inputs), recorded_sha256=state_hash(trace))

    def s06_sweep(self):
        """Recorded, not asserted (audit finding): where other S06-01/S06-03 mistimings from the labeled S06 start come to rest."""
        L, LC = self.S.LiftworksV3Checks, self.S.LiftworksV3CompleteChecks
        rows = []
        for name, press, aim, base, holds in (('S06-01 carriage', 5, L.CARRIAGE_V3, [], range(20, 421, 20)),
                                              ('S06-03 climb hook', LC.CLIMB_PRESS, LC.CLIMB_V3, L.S06_01_V3+L.S06_02_V3, range(400, 481, 4))):
            for release in holds:
                self.lite.restore(self.starts['S06'])
                rec, st, _ = self.lite.play(base+[(press, 'mousedown', *aim), (release if press > 5 else press+release, 'mouseup', *aim)],
                                            self.SETTLE, capture={self.SETTLE})
                p = st[self.SETTLE]['player']
                last = rec['bounces'][-1][1] if rec['bounces'] else None
                rows.append(dict(encounter=name, press=press, release=release if press > 5 else press+release, rest=[round(p['x'], 1), round(p['y'], 1)],
                                 speed=round(math.hypot(p['speedX'], p['speedY']), 3), last_bouncer=last,
                                 rest_section=last.split('-')[0] if last else None))
        return dict(note='lite runs (production physics, trusted input) from the labeled S06 start; recorded, not asserted. Several '
                    'mistimed S06-01/S06-03 releases fall past S05 through the lower sections, some to the S01 floor (follow-up)',
                    rows=rows, rest_sections={k: sum(r['rest_section'] == k for r in rows) for k in sorted({r['rest_section'] for r in rows if r['rest_section']})})

    # ---- cases ----------------------------------------------------------------------------------
    def test_01_fall_chain(self):
        falls = []
        for spec in self.falls_spec():
            m, trace = self.fall_run(spec)
            result = self.analyse_fall(spec, m, trace)
            del trace
            falls.append(result)
            z = result['drag_zone_above_landing']
            print('PASS fall %s -> %s: %s released at %d (nominal %d); apex %.1f; %s vx/vy %.3f/%.3f -> %.3f/%.3f; lands on %s at %d; '
                  'first bounce peak %.3f of %.1f; input-only rejoin from %d -> %s' % (result['start_section'], result['landing_section'],
                  spec['release'][1], spec['release'][0], spec['nominal_release'], result['apex']['player']['y'], z['id'], z['vx_before'], z['vy_before'],
                  z['vx_after'], z['vy_after'], spec['landing'], result['landing']['tick'], result['first_bounce']['fraction_of_fall_height'],
                  result['fall_height'], spec['rejoin_tick'], spec['rejoin_goal']), flush=True)
        self.assertEqual([f['start_section'] for f in falls], ['S02','S03','S04','S05','S06','S07','S08'])
        self.evidence.write('falls.json', dict(falls=falls, starts=self.start_proof, proof=self.proof, s06_mistiming_sweep=self.s06_sweep(),
            definitions=dict(landing_section='section prefix of the first bouncer touched after the release (the section below)',
                fall_height='settled rest y on the landing bouncer minus the apex y after the release',
                first_bounce_peak='highest point between the first and second landing bounce, as a fraction of the fall height',
                drag_zone_speeds='before = the tick before entering the zone; after = the player just before the landing contact; undamped_vy = '
                    'before.speedY + gravity x cycles x ticks inside (no drag); reduction asserted for vx (|after| <= |before|) and vy (after < undamped)')))

    # S06: no S06 section-proof fall lands in S05 (S06-04-tapped lands on the S06 drop ledge), so this one is new: the S06-03
    # climb hook released 44 ticks early (450, nominal 494) sinks through S05-fall-drag onto the green S05 catch deck (an S05
    # route bouncer); from the settled deck a 250-tick pull on the S07 roof boom (its centre, the only press found by a
    # bounded lite search of every target in reach x 9 holds) swings the player east onto the S05 exit ledge, the S06
    # entrance, where it settles (S06 rejoined at its start; the S06-01 replay from that pose is not reproduced, see review.md).
    @classmethod
    def s06_fall(cls):
        L, LC, GC = cls.S.LiftworksV3Checks, cls.S.LiftworksV3CompleteChecks, cls.S.GalleriesV3CompleteChecks
        boom = (5235, -10377.5)
        plan = L.S06_01_V3 + L.S06_02_V3 + [(LC.CLIMB_PRESS, 'mousedown', *LC.CLIMB_V3), (450, 'mouseup', *LC.CLIMB_V3),
                                            (1305, 'mousedown', *boom), (1555, 'mouseup', *boom)]
        return dict(section='S06', source='new (TASK-531): S06-03 climb hook released early', plan=plan, ticks=2155,
                    release=(450, 'S06-climb-hook'), nominal_release=LC.CLIMB_RELEASE, landing='S05-catch-deck', drags=['S05-fall-drag'],
                    rejoin_tick=1305, end=GC.S05_04_EXIT, rejoin_goal='S06 entrance (settled on the S05 exit ledge, the S06-01 start)')

    # ---- bypass audit -----------------------------------------------------------------------------
    # Two parts. test_02a (controlled.json): every violating route logged by the earlier full search (findings/exploration.log,
    # findings/README.md items 2-3) is replayed from the same start with identical inputs at 1080 (range flag false) and at
    # 1620 (range flag true). test_02b (bypass-search.json): a reduced, bounded search at 1620 from the violating S01..S04
    # starts and the real fallen states; every route it finds skipping more than one encounter is replayed at 1080 too.
    # Search space per start (bounded, logged): one press at tick 5 on every grappleable element whose nearest point is within
    # 1620 (aimed at its centre and at its nearest point; off-screen and HUD aims are logged, not dispatched) x HOLDS_1, then
    # OBSERVE ticks; the TOP_N furthest single-press attempts get a second press at their post-release apex on every target
    # then in range x 2 aims x HOLDS_2; up to CANDIDATES attempts that fly through an exit box 2+ encounters ahead get a
    # continuation press when they enter it. At most PER_START attempts per start.
    # Progress is judged where the player comes to REST (within a 3-unit box for 60 ticks, at most SETTLE_LIMIT ticks after
    # OBSERVE): the furthest encounter whose exit box (15 padding) or next start point (within 40) holds the rest pose.
    HOLDS_1, HOLDS_2, OBSERVE, TOP_N, PER_START, SETTLE_LIMIT, CANDIDATES = (40, 80, 160, 320), (40, 240), 420, 2, 110, 1800, 2
    BUDGET = 1400
    # Synthetic-range starts of the reduced search: the encounters whose starts produced (or came closest to) violations.
    SEARCH_ENCOUNTERS = (1, 2, 9, 10, 12)
    # Violating routes logged by the earlier full search: (start encounter index, source, logged skip, logged rest exit,
    # presses [(tick, hold, target)], logged rest pose). The aim kind (centre / nearest point) was not logged; it is
    # reconstructed by replaying every combination at 1620 and taking the one closest to the logged rest pose.
    LOGGED = [
        (1, 'findings/s01-02-after-exit-pad-deletion.log (logged with the v2 S03-exit-pad deleted in a scratch tree)', 4, 'S02-04', [(5, 80, 'S01-lift'), (115, 40, 'S01-gantry-hook'), (1041, 40, 'S01-gantry-hook')], (5818.1, -4871.0)),
        (1, 'findings/s01-02-after-exit-pad-deletion.log (logged with the v2 S03-exit-pad deleted in a scratch tree)', 4, 'S02-04', [(5, 80, 'S01-lift'), (115, 40, 'S01-crown-hook'), (265, 240, 'S02-lift')], (5629.3, -4862.1)),
        (1, 'findings/s01-02-after-exit-pad-deletion.log (logged with the v2 S03-exit-pad deleted in a scratch tree)', 4, 'S02-04', [(5, 80, 'S01-lift'), (115, 40, 'S01-crown-hook'), (262, 40, 'S02-lift')], (5649.2, -4872.7)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 240, 'S02-crown-hook')], (6130.4, -4871.5)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 240, 'S02-crown-hook')], (5809.4, -4871.6)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S03-hoist')], (5664.6, -4871.3)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 240, 'S03-hoist')], (5678.5, -4871.1)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 240, 'S03-hoist')], (5661.9, -4871.7)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S03-lower-bridge')], (5701.6, -4872.4)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 240, 'S03-lower-bridge')], (5840.1, -4871.7)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S03-lower-bridge')], (5699.6, -4871.1)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 240, 'S03-lower-bridge')], (5891.1, -4871.7)),
        (2, 'findings/exploration.log', 4, 'S02-04', [(5, 80, 'S01-gantry-hook'), (315, 240, 'S03-west-pier')], (5632.3, -4868.2)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 120, 'S02-crown-hook')], (5821.6, -4871.5)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 120, 'S02-crown-hook')], (5959.3, -4871.7)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 120, 'S02-crown-hook')], (5862.3, -4871.7)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 240, 'S02-crown-hook')], (6034.9, -4871.4)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 120, 'S02-crown-hook')], (5965.5, -4871.7)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 240, 'S02-crown-hook')], (6063.0, -4871.7)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 40, 'S02-exit-ledge')], (5653.5, -4871.7)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 120, 'S02-exit-ledge')], (5641.1, -4870.9)),
        (2, 'findings/exploration.log', 3, 'S02-04', [(5, 80, 'S01-gantry-hook'), (377, 120, 'S02-hoist'), (498, 240, 'S02-exit-ledge')], (5640.0, -4871.0)),
        (10, 'findings/exploration.log', 7, 'S05-04', [(5, 40, 'S05-recessed-ceiling'), (138, 120, 'S04-hoist'), (432, 240, 'S05-exit-hook')], (6150.7, -9431.4)),
        (10, 'findings/exploration.log', 7, 'S05-04', [(5, 40, 'S05-recessed-ceiling'), (138, 120, 'S04-hoist'), (432, 240, 'S05-exit-hook')], (6161.5, -9431.6)),
        (12, 'findings/exploration.log', 5, 'S05-04', [(5, 80, 'S06-phase-rest'), (115, 120, 'S03-exit-hook'), (1944, 240, 'S05-exit-hook')], (6122.5, -9431.0)),
        (12, 'findings/exploration.log', 5, 'S05-04', [(5, 80, 'S06-phase-rest'), (115, 120, 'S03-exit-hook'), (1944, 240, 'S05-exit-hook')], (6126.5, -9432.0)),
        (12, 'findings/exploration.log', 5, 'S05-04', [(5, 80, 'S06-phase-rest'), (115, 120, 'S03-exit-hook'), (1944, 120, 'S06-carriage')], (6137.8, -9431.4)),
        (12, 'findings/exploration.log', 5, 'S05-04', [(5, 320, 'S03-exit-hook'), (355, 40, 'S03-west-pier'), (765, 120, 'S05-catch-deck')], (6164.6, -9431.9)),
        (12, 'findings/exploration.log', 5, 'S05-04', [(5, 320, 'S03-exit-hook'), (355, 40, 'S03-shutter'), (2369, 40, 'S05-exit-hook')], (6114.3, -9431.6)),
        (12, 'findings/exploration.log', 5, 'S05-04', [(5, 320, 'S03-exit-hook'), (355, 40, 'S03-shutter'), (2369, 120, 'S06-carriage')], (6145.9, -9431.3)),
        (12, 'findings/exploration.log', 9, 'S06-04', [(5, 320, 'S03-exit-hook'), (355, 120, 'S04-exit'), (506, 240, 'S05-transfer-canopy')], (1488.8, -11261.3)),
    ]
    DESIGN = 'needs-design-decision (range rule or 1620 relayout)'
    # Pre-fix controlled replay (findings/controlled-before-fix.json, HEAD 9bfc09a geometry): per LOGGED route, the aim kinds and
    # world-space inputs it replayed and its skipped counts at 1080 and 1620. The post-fix replay uses these identical inputs.
    BEFORE_FIX = [
        (['nearest', 'center', 'nearest'], [(4440, -1718), (5250, -2995), (5310, -3010)], 0, 0),
        (['nearest', 'center', 'nearest'], [(4440, -1718), (5950, -3135), (4966.668545583515, -4649.666666666667)], 0, 4),
        (['nearest', 'nearest', 'center'], [(4440, -1718), (5890, -3120), (4985, -4666.666666666667)], 0, 4),
        (['nearest', 'center'], [(5190, -2980), (6060, -5615)], 0, 4),
        (['nearest', 'nearest'], [(5190, -2980), (6000, -5600)], 0, 4),
        (['nearest', 'center'], [(5190, -2980), (5520, -5801.333333333333)], 4, 4),
        (['nearest', 'center'], [(5190, -2980), (5520, -5801.333333333333)], 4, 4),
        (['nearest', 'nearest'], [(5190, -2980), (5460, -5786.333333333333)], 4, 4),
        (['nearest', 'center'], [(5190, -2980), (6420, -5380)], 0, 4),
        (['nearest', 'center'], [(5190, -2980), (6420, -5380)], 0, 4),
        (['nearest', 'nearest'], [(5190, -2980), (6360, -5360)], 0, 4),
        (['nearest', 'nearest'], [(5190, -2980), (6360, -5360)], 0, 4),
        (['nearest', 'center'], [(5190, -2980), (5165, -6150)], 4, 4),
        (['nearest', 'center', 'center'], [(5190, -2980), (6100, -3684.3333333333335), (6060, -5615)], 0, 3),
        (['nearest', 'center', 'nearest'], [(5190, -2980), (6100, -3684.3333333333335), (6000, -5600)], 0, 3),
        (['nearest', 'nearest', 'center'], [(5190, -2980), (6040, -3699.3333333333335), (6060, -5615)], 0, 3),
        (['nearest', 'nearest', 'center'], [(5190, -2980), (6040, -3699.3333333333335), (6060, -5615)], 0, 3),
        (['nearest', 'nearest', 'nearest'], [(5190, -2980), (6040, -3699.3333333333335), (6000, -5600)], 0, 3),
        (['nearest', 'nearest', 'nearest'], [(5190, -2980), (6040, -3699.3333333333335), (6000, -5600)], 0, 3),
        (['nearest', 'nearest', 'nearest'], [(5190, -2980), (6040, -3699.3333333333335), (5640, -4820)], 0, 3),
        (['nearest', 'nearest', 'nearest'], [(5190, -2980), (6040, -3699.3333333333335), (5640, -4820)], 0, 3),
        (['nearest', 'nearest', 'nearest'], [(5190, -2980), (6040, -3699.3333333333335), (5640, -4820)], 0, 3),
        (['nearest', 'nearest', 'center'], [(6070, -7530), (5154, -7790), (4980, -9087.5)], 0, 7),
        (['nearest', 'nearest', 'nearest'], [(6070, -7530), (5154, -7790), (4950, -9075)], 0, 7),
        (['nearest', 'nearest', 'center'], [(6000, -8160), (5520, -7975), (4980, -9087.5)], 0, 5),
        (['nearest', 'nearest', 'nearest'], [(6000, -8160), (5520, -7975), (4950, -9075)], 0, 5),
        (['nearest', 'nearest', 'center'], [(6000, -8160), (5520, -7975), (4747.999999999999, -9105)], 0, 5),
        (['nearest', 'nearest', 'center'], [(5520, -7950), (5180, -6600), (4100, -9480)], 5, 5),
        (['nearest', 'center', 'nearest'], [(5520, -7950), (5730.75, -6845), (4950, -9075)], 0, 5),
        (['nearest', 'center', 'center'], [(5520, -7950), (5730.75, -6845), (4757, -9105)], 0, 5),
        (['center', 'nearest', 'nearest'], [(5460, -7962.5), (4660, -6660), (5420, -7425)], 0, 9),
    ]
    # The local geometry fixes for the routes that also skipped > 1 at 1080 (findings/1080-bugs.md).
    GEOMETRY_FIXES = [
        dict(family='A', routes=[5, 6, 7, 12], element='S01-overpull-drag', change='new drag zone (5380,-4650) 260x500 left of the S02 canopy, '
             'under the new declared S01 fall point S01-03-overpull (5500,-4250); >= 132 from every nominal S01..S04 position and above '
             'the declared S02-03-short east-wall bank (apex ~-4065, which a first draft reaching -4080 touched: Task552 test_02); it '
             'spans the whole overpull rise (a 180-tall draft let route 4 still pull onto the S02 exit ledge from the apex)',
             effect='an S01-03 overpull (gantry hook caught early at its near corner and held 80) loses its horizontal speed there and drops '
                    'to the S01 floor instead of flying up the S02 shaft onto the S02-04 launch or pulling onto the S02 exit ledge'),
        dict(family='B', routes=[27], element='S05-transfer-canopy', change='legacy v1 Cable Galleries canopy (5420,-7400) deleted; no v3 '
             'route, recovery or fall chain uses it', effect='the S04-01 route S03-exit-hook -> canopy -> S05-catch-deck no longer reaches the '
             'S05 exit; the route falls to the base')]

    # Real fallen states with the range earned (no placement after the labeled section start): S06-01 carriage holds that
    # sling the player down through the lower sections, the S06-02 miss (S06-01 only) into the S04 catch basin, and the
    # TASK-518 short S05-01 hoist hold back onto the S04 exit ledge. Rest poses are judged at SETTLE ticks (the long drag-zone sinks take ~2000).
    FALLEN = [('S06-01 carriage held 80 (nominal 125)', 'S06', 'carriage', 80), ('S06-01 carriage held 220', 'S06', 'carriage', 220),
              ('S06-01 carriage held 250', 'S06', 'carriage', 250), ('S06-01 carriage held 280', 'S06', 'carriage', 280),
              ('S06-02 missed (S06-01 only, no lift press)', 'S06', 'carriage', 125), ('S05-01 hoist held 120 (TASK-518 short)', 'S05', 'hoist', 120)]
    SETTLE = 2400

    def search_starts(self):
        """Labeled start states in S01..S04 with range 1620: the real fallen states, and the real base-run pose at the start
        of every S01..S04 encounter (first tick at or after the previous encounter's exit with no rope and no press held)
        with the range flag set to the earned value (labeled synthetic upgrade)."""
        S, lite = self.S, self.lite
        starts = []
        for label, section, anchor, hold in self.FALLEN:
            aim = S.LiftworksV3Checks.CARRIAGE_V3 if anchor == 'carriage' else S.GalleriesV3Checks.HOIST_V3
            lite.restore(self.starts[section])
            rec, states, _ = lite.play([(5, 'mousedown', *aim), (hold, 'mouseup', *aim)], self.SETTLE, capture={self.SETTLE})
            st = states[self.SETTLE]; p = st['player']
            self.assertIs(st['upgrades']['range'], True)
            self.assertLess(math.hypot(p['speedX'], p['speedY']), .5, (label, p))
            starts.append(dict(label='real fallen state: '+label+' from the labeled %s start, at rest at tick %d' % (section, self.SETTLE),
                               kind='real', state=st, last_bouncer=rec['bounces'][-1][1] if rec['bounces'] else None))
        route = Task529Tests.nominal.__func__(type('Lower', (), dict(S=S, SECTION_STARTS=Task529Tests.SECTION_STARTS)))
        exits = self.start_proof['base_run']['first_exit_ticks']
        lite.page.evaluate('CLIMB_UI.restart()')
        rec = lite.new_rec()
        want = [0] + [exits[e['id']] for e in self.mountain['encounters'][:15]]
        poses, tick = [], 0
        for k, at in enumerate(want):
            while True:
                if tick < at:
                    rec, _, _ = lite.play([(t-tick, e, x, y) for t, e, x, y in route if tick <= t < at], at-tick, rec=rec); tick = at
                s = lite.page.evaluate('T531.state()')
                if not s['throwed'] and not s['pressHeld']: break
                rec, _, _ = lite.play([(t-tick, e, x, y) for t, e, x, y in route if t == tick], 1, rec=rec); tick += 1
            st = lite.page.evaluate('captureClimbState()')
            self.assertIs(st['upgrades']['range'], False)
            st['upgrades']['range'] = True
            enc = self.mountain['encounters'][k]['id']
            poses.append(dict(label='real base-run pose at the %s start (tick %d; previous exit at %d) with the range flag set to 1620 '
                              '(labeled synthetic upgrade)' % (enc, tick, at), kind='synthetic-range', state=st, encounter=k, base_tick=tick))
        for s in starts:
            p = s['state']['player']
            s['encounter'] = min(range(16), key=lambda i: math.hypot(p['x']-self.mountain['encounters'][i]['start']['x'],
                                                                     p['y']-self.mountain['encounters'][i]['start']['y']))
        return poses + starts

    def attempt(self, start, presses):
        """presses: [(tick, hold, target_id, aim_kind, world)]; returns the logged outcome."""
        lite = self.lite
        lite.restore(start['state'])
        plan = [p for t, h, _, _, w in presses for p in ((t, 'mousedown', w['x'], w['y']), (t+h, 'mouseup', w['x'], w['y']))]
        end = presses[-1][0] + presses[-1][1] + self.OBSERVE if presses else self.OBSERVE
        rec, _, clients = lite.play(plan, end)
        rec = lite.page.evaluate('([n,r])=>T531.settle(n,r)', [self.SETTLE_LIMIT, rec])
        # Guard: no press may reach the HUD (a pause or a mode switch would stop the simulation).
        self.assertEqual(lite.page.evaluate('[version, menu.gamePaused]'), ['grapple_over', False],
                         (presses, lite.page.evaluate('({completed:floors[0].climbStats.completed, x:ninja.x, y:ninja.y})')))
        return rec, lite.page.evaluate('T531.state()'), clients

    def progress(self, rec):
        idx = {e['id']: e['index'] for e in self.exits}
        return max((idx[k] for k in rec['exits']), default=-1)

    def rest_progress(self, p, settled):
        if not settled: return -1
        encs = self.mountain['encounters']
        hits = [e['index'] for e in self.exits if e['left']-15 <= p['x'] <= e['right']+15 and e['top']-15 <= p['y'] <= e['bottom']+15]
        hits += [j-1 for j in range(1, len(encs)) if math.hypot(p['x']-encs[j]['start']['x'], p['y']-encs[j]['start']['y']) < 40]
        return max(hits, default=-1)

    def outcome(self, start, presses, rec, final, clients, baseline):
        transient, rest = self.progress(rec), self.rest_progress(final, rec['settled'])
        # Presses not dispatched (on a HUD button in a controlled replay) do not count as presses.
        n = len(presses) - sum(1 for c in clients if c['event'] == 'mousedown' and c.get('dropped_on_hud'))
        skipped = max(0, rest - baseline['rest'] - n)
        transient_skipped = max(0, transient - baseline['transient'] - n)
        name = lambda i: self.exits[i]['id'] if i >= 0 else None
        return dict(presses=[dict(tick=t, hold=h, target=i, aim=a, world=w) for t, h, i, a, w in presses],
                    clients=[c['client'] for c in clients if c['event'] == 'mousedown'],
                    acquisitions=rec['acquisitions'], exits={k: v for k, v in sorted(rec['exits'].items(), key=lambda kv: kv[1])},
                    rest=[round(final['x'], 1), round(final['y'], 1)], settled=rec['settled'], rest_exit_index=rest, rest_exit=name(rest),
                    skipped=skipped, violation=skipped > 1, transient_exit_index=transient, transient_exit=name(transient),
                    transient_skipped=transient_skipped, min_y=round(rec['minY'], 1), apex_tick=rec['minYTick'], completed=rec['completed'],
                    ticks=rec['tick'])

    def search(self, start):
        lite, log = self.lite, []
        rec, final, _ = self.attempt(start, [])
        k = start['encounter']
        no_press = dict(transient_exit_index=self.progress(rec), rest_exit_index=self.rest_progress(final, rec['settled']), exits=rec['exits'],
                        rest=[round(final['x'], 1), round(final['y'], 1)], settled=rec['settled'])
        baseline = dict(rest=max(k-1, no_press['rest_exit_index']), transient=max(k-1, no_press['transient_exit_index']))
        lite.restore(start['state']); lite.play([], 5)
        targets = lite.page.evaluate('r=>T531.targets(r)', self.mountain['radius']['upgraded'])
        offscreen, hud = [], []
        def candidates(tick, targets):
            out = []
            for t in targets:
                for kind in ('center', 'nearest'):
                    w = t[kind]
                    if kind == 'nearest' and w == t['center']: continue
                    c = lite.page.evaluate('p=>GRAPPLE_OVER_TEST.client(p)', w)
                    if not (0 < c['x'] < VIEWPORT['width'] and 0 < c['y'] < VIEWPORT['height']):
                        offscreen.append(dict(tick=tick, target=t['id'], aim=kind, world=w, client=c))
                    elif any(b['x']-4 <= c['x'] <= b['x']+b['width']+4 and b['y']-4 <= c['y'] <= b['y']+b['height']+4 for b in self.hud_buttons):
                        hud.append(dict(tick=tick, target=t['id'], aim=kind, world=w, client=c))
                    else: out.append((t['id'], kind, w))
            return out
        first = candidates(5, targets)
        for i, kind, w in first:
            for h in self.HOLDS_1:
                presses = [(5, h, i, kind, w)]
                if len(log) >= self.PER_START: break
                rec, final, clients = self.attempt(start, presses)
                log.append(self.outcome(start, presses, rec, final, clients, baseline))
        ranked = sorted((o for o in log if o['acquisitions']), key=lambda o: (max(o['rest_exit_index'], o['transient_exit_index']), -o['min_y']),
                        reverse=True)[:self.TOP_N]
        for o in ranked:
            p0 = o['presses'][0]
            first_press = (p0['tick'], p0['hold'], p0['target'], p0['aim'], p0['world'])
            second = max(o['apex_tick'], p0['tick']+p0['hold']+10)
            if second >= p0['tick']+p0['hold']+self.OBSERVE: second = p0['tick']+p0['hold']+30
            lite.restore(start['state'])
            plan = [(p0['tick'], 'mousedown', p0['world']['x'], p0['world']['y']), (p0['tick']+p0['hold'], 'mouseup', p0['world']['x'], p0['world']['y'])]
            lite.play(plan, second)
            targets2 = lite.page.evaluate('r=>T531.targets(r)', self.mountain['radius']['upgraded'])
            for i, kind, w in candidates(second, targets2):
                for h in self.HOLDS_2:
                    if len(log) >= self.PER_START: break
                    presses = [first_press, (second, h, i, kind, w)]
                    rec, final, clients = self.attempt(start, presses)
                    log.append(self.outcome(start, presses, rec, final, clients, baseline))
        # Continuation of transient skips: can the flight through a skipped-ahead exit box be carried on with a further press?
        candidates_ = [o for o in log if o['transient_skipped'] > 1][:self.CANDIDATES]
        continued = []
        for o in candidates_:
            prior = [(p['tick'], p['hold'], p['target'], p['aim'], p['world']) for p in o['presses']]
            at = max(o['exits'][o['transient_exit']], prior[-1][0] + prior[-1][1] + 1)
            lite.restore(start['state'])
            lite.play([q for t, h, _, _, w in prior for q in ((t, 'mousedown', w['x'], w['y']), (t+h, 'mouseup', w['x'], w['y']))], at)
            targets3 = lite.page.evaluate('r=>T531.targets(r)', self.mountain['radius']['upgraded'])
            for i, kind, w in candidates(at, targets3):
                for h in self.HOLDS_2:
                    if len(log) + len(continued) >= self.PER_START: break
                    presses = prior + [(at, h, i, kind, w)]
                    rec, final, clients = self.attempt(start, presses)
                    out = self.outcome(start, presses, rec, final, clients, baseline)
                    out['continues'] = len(log)
                    continued.append(out)
        log += continued
        return dict(label=start['label'], kind=start['kind'], encounter=self.mountain['encounters'][k]['id'], encounter_index=k,
                    pose={f: start['state']['player'][f] for f in ('x','y','speedX','speedY')}, range=start['state']['upgrades']['range'],
                    baseline=baseline, no_press=no_press, transient_candidates=len(candidates_),
                    targets_at_first_press=[dict(id=t['id'], distance=round(t['distance'], 1)) for t in targets],
                    offscreen_aims_not_dispatched=offscreen, hud_button_aims_not_dispatched=hud, attempts=log)

    def all_starts(self):
        cls = type(self)
        if not hasattr(cls, '_starts'): cls._starts = self.search_starts()
        if not hasattr(cls, 'hud_buttons'):
            # The drawn HUD buttons (CSS px): a press there opens the pause menu instead of throwing.
            cls.hud_buttons = self.lite.page.evaluate('''() => {LAYOUT_PROBE.boxes=[]; draw(); const b=LAYOUT_PROBE.boxes;
                LAYOUT_PROBE.boxes=null; return b.filter(x=>x.kind==='button')}''')
            self.assertEqual(len(cls.hud_buttons), 1)
        return cls._starts

    @staticmethod
    def at_range(start, upgraded):
        """The same start with the range flag set (True = 1620, False = 1080); nothing else differs."""
        state = json.loads(json.dumps(start['state']))
        state['upgrades']['range'] = upgraded
        return dict(start, state=state)

    def baseline(self, start):
        rec, final, _ = self.attempt(start, [])
        rest, transient = self.rest_progress(final, rec['settled']), self.progress(rec)
        k = start['encounter']
        return dict(rest=max(k-1, rest), transient=max(k-1, transient)), dict(rest_exit_index=rest, transient_exit_index=transient,
                    rest=[round(final['x'], 1), round(final['y'], 1)], settled=rec['settled'])

    def replay(self, start, presses, upgraded):
        """One route from `start` at the given range with identical world-space inputs; the outcome judged as in the search."""
        s = self.at_range(start, upgraded)
        self.lite.restore(s['state'])
        radius = self.lite.page.evaluate('grappleOverAcquisitionRadius()')
        self.assertEqual(radius, self.mountain['radius']['upgraded' if upgraded else 'base'])
        base, no_press = self.baseline(s)
        self.lite.hud = self.hud_buttons
        try: rec, final, clients = self.attempt(s, presses)
        finally: self.lite.hud = None
        out = self.outcome(s, presses, rec, final, clients, base)
        out['presses_dropped_on_hud'] = [c['tick'] for c in clients if c['event'] == 'mousedown' and c.get('dropped_on_hud')]
        out.update(range=upgraded, radius=radius, baseline=base, no_press=no_press, range_at_end=final['range'],
                   all_presses_on_screen=all(0 < c['x'] < VIEWPORT['width'] and 0 < c['y'] < VIEWPORT['height'] for c in out['clients']))
        return out

    def disposition(self, at_1080, at_1620):
        if at_1080['skipped'] > 1: return 'lower-geometry bug: skips more than one encounter at 1080 too (fix locally in mountain.js)'
        if at_1620['skipped'] > 1: return self.DESIGN
        return 'no skip > 1 on the current geometry at either range'

    def test_02a_controlled_replay(self):
        import time
        began = time.time()
        starts = self.all_starts()
        rows = []
        for n, (k, source, skip, rest_exit, route, rest) in enumerate(self.LOGGED):
            start = starts[k]
            self.assertEqual((start['kind'], start['encounter']), ('synthetic-range', k))
            kinds, worlds, before_1080, before_1620 = self.BEFORE_FIX[n]
            presses = [(t, h, tid, kind, dict(x=x, y=y)) for (t, h, tid), kind, (x, y) in zip(route, kinds, worlds)]
            at_1620 = self.replay(start, presses, True)
            d = math.hypot(at_1620['rest'][0]-rest[0], at_1620['rest'][1]-rest[1]) if at_1620['rest'] else float('inf')
            at_1080 = self.replay(start, presses, False)
            row = dict(route=n, source=source, start=start['label'], start_kind=start['kind'], encounter=self.mountain['encounters'][k]['id'],
                       logged=dict(skipped=skip, rest_exit=rest_exit, rest=list(rest), presses=[list(p) for p in route]),
                       aims=[p[3] for p in presses], reproduced_at_1620=d < 1, distance_to_logged_rest=round(d, 1) if d < 1e9 else None,
                       before_fix=dict(skipped_1080=before_1080, skipped_1620=before_1620),
                       fixed_by=[f['family'] for f in self.GEOMETRY_FIXES if n in f['routes']],
                       inputs=[dict(tick=t, hold=h, target=tid, world=w) for t, h, tid, _, w in presses])
            for name, o in (('at_1080', at_1080), ('at_1620', at_1620)):
                row[name] = {f: o[f] for f in ('radius', 'rest', 'settled', 'rest_exit', 'rest_exit_index', 'skipped', 'baseline', 'acquisitions',
                                               'transient_exit', 'completed', 'range_at_end', 'all_presses_on_screen', 'presses_dropped_on_hud', 'ticks')}
            row['disposition'] = self.disposition(at_1080, at_1620)
            rows.append(row)
            print('REPLAY %2d %s %s: 1620 rest %s skipped %d (logged %d, reproduced %s) | 1080 rest %s skipped %d -> %s' % (
                n, row['encounter'], [p[2] for p in route], at_1620['rest_exit'], at_1620['skipped'], skip, d < 1,
                at_1080['rest_exit'], at_1080['skipped'], row['disposition']), flush=True)
        self.assertEqual(self.lite.errors, [])
        bugs = [r for r in rows if r['at_1080']['skipped'] > 1]
        design = [r for r in rows if r['disposition'] == self.DESIGN]
        type(self).controlled = dict(routes=len(rows), design=[dict(route=r['route'], encounter=r['encounter'], inputs=r['inputs'],
            rest_exit_1620=r['at_1620']['rest_exit'], skipped_1620=r['at_1620']['skipped'], skipped_1080=r['at_1080']['skipped']) for r in design])
        self.evidence.write('controlled.json', dict(
            purpose='controlled comparison: every violating route logged by the earlier full TASK-531 search (findings/exploration.log, '
                    'findings/README.md items 2-3), replayed from the same start with identical world-space trusted mouse inputs at range '
                    '1080 (upgrades.range false) and 1620 (true); the start differs only in that flag',
            starts='real base-run poses at the encounter starts (search_starts); at 1080 this is the unmodified base-run state, at 1620 the '
                   'labeled synthetic upgrade the search used',
            skip_rule='skipped = rest progress - baseline (no-press rest progress at that range, at least the previous encounter) - presses',
            aim_reconstruction='the logs kept target ids, ticks and holds but not the aim kind; the pre-fix controlled replay '
                               '(findings/controlled-before-fix.json) replayed every centre/nearest combination at 1620 and kept the one closest '
                               'to the logged rest; its world-space inputs (BEFORE_FIX) are replayed here unchanged at both ranges',
            summary=dict(routes=len(rows), reproduced_at_1620=sum(r['reproduced_at_1620'] for r in rows),
                         skip_gt1_at_1620=sum(r['at_1620']['skipped'] > 1 for r in rows), skip_gt1_at_1080=len(bugs),
                         max_skipped_1080=max(r['at_1080']['skipped'] for r in rows), max_skipped_1620=max(r['at_1620']['skipped'] for r in rows),
                         dispositions={d: sum(r['disposition'] == d for r in rows) for d in sorted({r['disposition'] for r in rows})},
                         geometry_fixes=self.GEOMETRY_FIXES if not bugs else 'REQUIRED', seconds=round(time.time()-began, 1)),
            routes=rows, proof=self.proof))
        self.assertEqual(bugs, [], 'routes that skip more than one encounter at 1080 are lower-geometry bugs')
        # Every route that skipped > 1 at 1080 before the fixes is covered by a recorded local geometry fix.
        self.assertEqual(sorted(r['route'] for r in rows if r['before_fix']['skipped_1080'] > 1),
                         sorted(n for f in self.GEOMETRY_FIXES for n in f['routes']))
        print('PASS controlled replay: %d logged routes, %d skip > 1 at 1620, 0 at 1080 (max %d)' % (
            len(rows), sum(r['at_1620']['skipped'] > 1 for r in rows), max(r['at_1080']['skipped'] for r in rows)), flush=True)

    def finish_route(self):
        """README item 1 (outside the S01..S04 scope, handed to TASK-492): base run, then S05-hoist and S08-mast-trolley."""
        hoist, mast = (2560.000000000001, -12440), (2123.76037818735, -13300)
        presses = [(180, 160, hoist), (400, 240, mast)]
        route = Task529Tests.nominal.__func__(type('Lower', (), dict(S=self.S, SECTION_STARTS=Task529Tests.SECTION_STARTS)))
        out = {}
        self.lite.page.evaluate('CLIMB_UI.restart()')
        t0 = self.BASE_TICKS['S05']
        plan = route + [q for t, h, w in presses for q in ((t0+t, 'mousedown', *w), (t0+t+h, 'mouseup', *w))]
        rec, _, clients = self.lite.play(plan, t0+400+240+400)
        s = self.lite.page.evaluate('T531.state()')
        out['base_start_run_1620_earned'] = dict(completed=rec['completed'], rest=[round(s['x'], 1), round(s['y'], 1)], range=s['range'],
            acquisitions=rec['acquisitions'][-2:], presses_on_screen=all(c['onscreen'] for c in clients if c['event'] == 'mousedown'))
        for upgraded in (True, False):
            st = json.loads(json.dumps(self.starts['S05'])); st['upgrades']['range'] = upgraded
            self.lite.restore(st)
            rec, _, clients = self.lite.play([q for t, h, w in presses for q in ((t, 'mousedown', *w), (t+h, 'mouseup', *w))], 400+240+400)
            s = self.lite.page.evaluate('T531.state()')
            out['from_S05_start_%d' % (1620 if upgraded else 1080)] = dict(completed=rec['completed'], rest=[round(s['x'], 1), round(s['y'], 1)],
                acquisitions=rec['acquisitions'], presses_on_screen=all(c['onscreen'] for c in clients if c['event'] == 'mousedown'))
        return dict(route='base run (TASK-529 nominal S01..S04, 1620 earned on the S04 exit ledge), then S05-hoist pressed at S05-start+180 '
                    'held 160 at %s and S08-mast-trolley at +400 held 240 at %s' % (hoist, mast), source='findings/README.md item 1, finish_probe.log',
                    disposition='handed to TASK-492 (map-wide bypasses): starts at the S05 entrance, outside the TASK-531 S01..S04 scope',
                    **out)

    def test_02b_bypass_search(self):
        import time
        began = time.time()
        starts = self.all_starts()
        chosen = [s for s in starts if s['kind'] == 'real' or s['encounter'] in self.SEARCH_ENCOUNTERS and s['kind'] == 'synthetic-range']
        results, total = [], 0
        for start in chosen:
            r = self.search(start)
            total += len(r['attempts'])
            self.assertLessEqual(total, self.BUDGET)
            results.append(r)
            print('SEARCH %s: %d attempts, baseline %s, max skipped %d, violations %d (%.0f s)' % (r['label'][:80], len(r['attempts']), r['baseline'],
                  max((o['skipped'] for o in r['attempts']), default=0), sum(o['violation'] for o in r['attempts']), time.time()-began), flush=True)
        # Every route skipping more than one encounter at 1620 is replayed from the same start at 1080 with identical inputs.
        remaining, bugs = [], []
        for r, start in zip(results, chosen):
            for o in r['attempts']:
                if not o['violation']: continue
                presses = [(p['tick'], p['hold'], p['target'], p['aim'], p['world']) for p in o['presses']]
                at_1080 = self.replay(start, presses, False)
                o['at_1080'] = {f: at_1080[f] for f in ('radius', 'rest', 'settled', 'rest_exit', 'skipped', 'acquisitions')}
                o['disposition'] = self.disposition(at_1080, o)
                entry = dict(start=r['label'], start_kind=start['kind'], inputs=o['presses'], rest_1620=o['rest'], rest_exit_1620=o['rest_exit'],
                             skipped_1620=o['skipped'], rest_1080=at_1080['rest'], rest_exit_1080=at_1080['rest_exit'], skipped_1080=at_1080['skipped'],
                             disposition=o['disposition'])
                (bugs if at_1080['skipped'] > 1 else remaining).append(entry)
        finish = self.finish_route()
        self.assertEqual(self.lite.errors, [])
        controlled = getattr(type(self), 'controlled', None)
        self.evidence.write('bypass-search.json', dict(
            scope='S01..S04 with the 1620 range; a reduced, bounded search, not a universal impossibility claim',
            search_space=dict(starts=[dict(label=s['label'], kind=s['kind'], encounter=self.mountain['encounters'][s['encounter']]['id']) for s in chosen],
                start_kinds='synthetic-range = real base-run pose at an encounter start with the range flag set to 1620 (labeled synthetic upgrade, the '
                    'starts where the earlier full search found or came closest to violations); real = real fallen state with the range earned',
                presses='one press at tick 5 on every grappleable element within 1620 (nearest point), aimed at its centre and nearest point '
                    '(on-screen, off the HUD) x holds %s, observed %d ticks after the release; the %d furthest single-press attempts get a second '
                    'press at their post-release apex on every target then within 1620 x 2 aims x holds %s; up to %d transient skips get a '
                    'continuation press; at most %d attempts per start' % (list(self.HOLDS_1), self.OBSERVE, self.TOP_N, list(self.HOLDS_2),
                    self.CANDIDATES, self.PER_START),
                hud_buttons=self.hud_buttons, skip_rule='skipped = rest progress - baseline - presses (rest progress: furthest encounter whose exit '
                    'box (+15) or next start (within 40) holds the settled rest pose)',
                settle='within a 3-unit box for 60 ticks, stepped up to %d ticks after the observation window' % self.SETTLE_LIMIT),
            budget=dict(max_attempts=self.BUDGET, per_start=self.PER_START, attempts=total, seconds=round(time.time()-began, 1)),
            outcome=dict(attempts=total, violations_1620=len(remaining)+len(bugs), skip_gt1_also_at_1080=len(bugs),
                         remaining_1620_only=len(remaining), max_skipped=max((o['skipped'] for r in results for o in r['attempts']), default=0),
                         by_kind={k: dict(starts=sum(r['kind'] == k for r in results), attempts=sum(len(r['attempts']) for r in results if r['kind'] == k),
                                          max_skipped=max((o['skipped'] for r in results if r['kind'] == k for o in r['attempts']), default=0),
                                          violations=sum(o['violation'] for r in results if r['kind'] == k for o in r['attempts']))
                                  for k in ('synthetic-range', 'real')},
                         unsettled_attempts=sum(not o['settled'] for r in results for o in r['attempts'])),
            remaining_1620_only_skips=remaining, lower_geometry_bugs=bugs,
            controlled_replay=controlled and dict(file='controlled.json', routes=controlled['routes'], remaining_1620_only=controlled['design']),
            handed_to_TASK_492=[finish],
            runner='LitePage: production physics() per tick with trusted Playwright mouse input, verified bit-identical to the audited '
                   'harness on the TASK-529 base run', proof=self.proof, starts=results))
        self.assertEqual(bugs, [], 'routes that skip more than one encounter at 1080 are lower-geometry bugs')
        self.assertTrue(all(e['disposition'] == self.DESIGN for e in remaining))
        print('PASS bypass search: %d starts, %d attempts (budget %d); %d skip > 1 at 1620, all 1620-only (%s); 0 at 1080; S05-entrance finish '
              'completed=%s handed to TASK-492' % (len(chosen), total, self.BUDGET, len(remaining), self.DESIGN,
              finish['base_start_run_1620_earned']['completed']), flush=True)

    def test_03_restart_returns_range(self):
        """A confirmed restart from a real fallen 1620 state (cancel first, then yes) returns the range to 1080."""
        page = self.lite.page
        fallen = None
        lite = self.lite
        # test_02b ends with the S05-entrance finish route completing the climb; start from a fresh game.
        lite.reset()
        self.assertEqual(page.evaluate('[version, !!floors[0].climbStats, floors[0].climbStats.completed]'), ['grapple_over', True, False])
        lite.restore(self.starts['S06'])
        aim = self.S.LiftworksV3Checks.CARRIAGE_V3
        lite.play([(5, 'mousedown', *aim), (125, 'mouseup', *aim)], self.SETTLE, capture={self.SETTLE})
        probe = lambda: page.evaluate('''() => ({radius:grappleOverAcquisitionRadius(), range:floors[0].rangeUpgraded,
            player:{x:ninja.x, y:ninja.y}, confirming:CLIMB_UI.confirming, paused:menu.gamePaused,
            saved:JSON.parse(localStorage.getItem('grapnelninja.grappleOver')||'null')?.upgrades||null})''')
        steps = [dict(step='fallen into the S04 catch basin (S06-02 missed) with the range earned', **probe())]
        self.assertEqual(steps[0]['radius'], 1620)
        page.evaluate('menu.startPause()')
        def tap(key):
            page.wait_for_function('!unTouch')
            boxes = page.evaluate('''() => {LAYOUT_PROBE.boxes=[]; menu.drawPauseScreen();
                const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;return b}''')
            label = page.evaluate('k=>I18N.t(k)', key)
            box = next(b for b in boxes if b['kind'] == 'button' and b['name'] == label)
            rect = page.locator('#canvas').bounding_box()
            page.mouse.click(rect['x']+box['x']+box['width']/2, rect['y']+box['y']+box['height']/2)
            page.evaluate('cancelAnimationFrame(game); window.requestAnimationFrame=()=>0')
            steps.append(dict(step='tap '+key, **probe()))
        tap('climb.restart'); self.assertTrue(steps[-1]['confirming'])
        tap('climb.cancel'); self.assertEqual(steps[-1]['radius'], 1620); self.assertTrue(steps[-1]['range'])
        tap('climb.restart')
        tap('climb.yes')
        after = steps[-1]
        self.assertFalse(after['confirming'])
        self.assertEqual(after['radius'], self.mountain['radius']['base'])
        self.assertIs(after['range'], False)
        self.assertEqual(after['player'], dict(x=self.mountain['spawn']['x'], y=self.mountain['spawn']['y']))
        page.wait_for_function("JSON.parse(localStorage.getItem('grapnelninja.grappleOver')).simulationTick===0")
        steps.append(dict(step='save after the confirmed restart', **probe()))
        self.assertEqual(steps[-1]['saved'], dict(range=False))
        self.evidence.write('restart.json', dict(passed=True, radius_before=1620, radius_after_cancel=1620, radius_after_restart=after['radius'],
            range_after_restart=after['range'], saved_upgrades=steps[-1]['saved'], steps=steps, proof=self.proof,
            note='pause menu buttons clicked with trusted mouse events at their drawn positions (as the TASK-460 modes test taps them)'))
        print('PASS restart: 1620 in the S04 catch basin, still 1620 after cancel, %d after the confirmed restart at the spawn; save upgrades %s'
              % (after['radius'], steps[-1]['saved']), flush=True)

    def test_04_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: runtime, level and harness match the tested worktree', flush=True)


if __name__ == '__main__':
    unittest.main()
