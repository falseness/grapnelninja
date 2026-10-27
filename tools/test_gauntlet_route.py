"""Production-input crossings of the gauntlet zones of SEC-ext-summit (--ext-summit-gauntlet, TASK-733..).

One case per filled zone (ZONES; a zone with slabs but no case fails test_00). Each case is one continuous replay in
the real index.html (tools/opening_combination_replay.js: production importedMountainLevel(), physics() once per tick,
document mouse events at the recorded ticks of tools/fixtures/gauntlet-inputs-Zk.json; nothing written after the
zero-speed fixture on the zone's approach ledge). It must: run off the approach ledge into the zone through its entry
side, cross it touching only the zone's own slabs with no rope attached or thrown while the player overlaps the zone
(a press inside stays blocked), never rest inside (REST_TICKS ticks in a row slower than REST_SPEED), leave through the
far side above the fall-recovery depth and land on the exit ledge's top with no rope. Each case runs twice and both
logs must be identical.

test_climb_transfers replays the 27 safe-space climb transfers of tools/fixtures/gauntlet-climb-inputs.json (S0..S8: start
ledge -> Sk-G1 -> Sk-G2 -> Z(k+1)-APPROACH, S8 -> XS-SUMMIT; at most 2 grapple panels per safe space) per transfer, as
the retired v19 tools/test_ext_summit_route.py test_04 did (TASK-744): tools/probe_level_routes.js ROUTE_PROBE places the player at zero speed drop
300 above the source top, then only document mouse events and physics(); the first contact/attach on a later panel must
be the target. Each transfer runs twice and must be identical. test_zz_full_run is the chained proof: S0, Z1, S1, ..., Z8,
S8 in order, each leg ending on the panel the next one starts from, every leg passing, and the last transfer
(S8-G2 -> XS-SUMMIT) replayed on until climbStats.completed.

Level: GAUNTLET_CANDIDATE=DIR (extended-mountain.level.json and extended-mountain-measurements.json). Without it the
shipped artifacts/levels data is used when it has extSummit.gauntlet (shipped v20 since TASK-744); otherwise the candidate is regenerated into a
temporary directory (tools/retune_extended_level.py --ext-summit-gauntlet, then tools/import_level_svg.py).

GAUNTLET_EVIDENCE_DIR=DIR writes traversals.json (compact) and climbs.json. No default evidence directory.

    python3 tools/test_gauntlet_route.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

EVIDENCE = os.environ.get('GAUNTLET_EVIDENCE_DIR')
CANDIDATE = os.environ.get('GAUNTLET_CANDIDATE')
SHIPPED = ROOT / 'artifacts' / 'levels'
SOURCE = ROOT / 'artifacts' / 'level' / 'extended-mountain-measurements.json'
NAMES = ('extended-mountain.level.json', 'extended-mountain-measurements.json')
ZONES = ('Z1', 'Z2', 'Z3', 'Z4', 'Z5', 'Z6', 'Z7', 'Z8')
INPUTS = {z: TOOLS / 'fixtures' / ('gauntlet-inputs-%s.json' % z) for z in ZONES}
CLIMBS = TOOLS / 'fixtures' / 'gauntlet-climb-inputs.json'
POLICY_KEYS = ('pumps', 'fraction', 'lastAimOffset', 'targetWhenInRange', 'targetFraction', 'drop', 'budget')
RECOVERY_DEPTH = 1500  # physics.js CLIMB_FALL_RECOVERY_DEPTH
REST_SPEED, REST_TICKS = 0.05, 30
OUT = {}
CLIMB_OUT = {}
DONE = {}  # leg results of this run, reused by test_zz_full_run

# One climb transfer on ROUTE_PROBE; hooks = attaches counted by physics() (climbStats.grapples).
CLIMB = '''o => {
    const r = ROUTE_PROBE.run(o)
    return {hit: r.hit, setup: r.setup, ticks: r.ticks, bounces: r.bounces, minY: r.minY, hooks: floors[0].climbStats.grapples,
            finish: r.finish === undefined ? null : r.finish, completed: r.completed === undefined ? null : r.completed}
}'''

LEG = '''o => {
    const ids = o.ids
    const c = OPENING_REPLAY.start({level: o.level, fixture: {panel: ids[o.fixture.panel], fraction: o.fixture.fraction,
                                                              drop: o.fixture.drop}})
    const aim = a => { const p = OPENING_REPLAY.topAt(floors[0].byId.get(ids[a.panel] + '-body0'), a.fraction); return [p.x, p.y] }
    const queue = [...o.inputs].sort((a, b) => a.tick - b.tick)
    const boundary = [], presses = []
    let inside = floors[0].playerInNoGrapple === true
    const start = {inside, ...c.state()}
    let insideTicks = 0, insideAttached = 0, insideThrown = 0, slow = 0, maxSlow = 0, minSpeed = Infinity, maxY = -Infinity
    let landed = null, ropeAtLanding = null
    const path = [[c.tick, +ninja.x.toFixed(1), +ninja.y.toFixed(1)]]
    const exitBody = ids[o.exit] + '-body0'
    while (c.tick < o.budget) {
        while (queue.length && queue[0].tick === c.tick) {
            const ev = queue.shift()
            if (ev.type === 'down') {
                const where = floors[0].playerInNoGrapple === true
                c.press(aim(ev))
                presses.push({tick: c.tick, inside: where, stale: stalePress, thrown: grapnel.throwed})
            } else c.release()
        }
        const fresh = c.step()
        if (c.tick % 5 === 0) path.push([c.tick, +ninja.x.toFixed(1), +ninja.y.toFixed(1)])
        const now = floors[0].playerInNoGrapple === true
        if (now !== inside) { boundary.push({event: now ? 'enter' : 'exit', ...c.state()}); inside = now }
        if (now) {
            insideTicks++; if (grapnel.grappled) insideAttached++; if (grapnel.throwed) insideThrown++
            const s = Math.hypot(ninja.speedX, ninja.speedY)
            slow = s < o.restSpeed ? slow + 1 : 0; maxSlow = Math.max(maxSlow, slow)
            minSpeed = Math.min(minSpeed, s); maxY = Math.max(maxY, ninja.y)
        }
        const out = boundary.some(b => b.event === 'exit')
        const land = fresh.find(k => k.id === exitBody && k.ny < -0.99)
        if (land && out && !landed) {
            landed = land; ropeAtLanding = {grappled: grapnel.grappled === true, throwed: grapnel.throwed === true}
            break
        }
        if (c.log.recoveries.length) break
    }
    if (c.held) c.release()
    return {start, boundary, presses, insideTicks, insideAttached, insideThrown, maxSlow, minSpeed: +minSpeed.toFixed(4),
            maxY: +maxY.toFixed(3), landed, ropeAtLanding, ticks: c.tick, layoutId: c.log.layoutId,
            acquisitionRadius: c.log.acquisitionRadius, fixture: c.log.fixture, inputs: c.log.inputs,
            contacts: c.log.contacts, grapple: c.log.grapple, maxStep: c.log.maxStep, recoveries: c.log.recoveries,
            path, final: c.state()}
}'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def level_dir(stack):
    if CANDIDATE:
        return Path(CANDIDATE), 'GAUNTLET_CANDIDATE'
    if 'gauntlet' in json.loads((SHIPPED / NAMES[1]).read_text()).get('extSummit', {}):
        return SHIPPED, 'shipped'
    tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='gauntlet-')))
    subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source', str(SOURCE), '--output-dir', str(tmp),
                    '--ext-summit-gauntlet'], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(TOOLS / 'import_level_svg.py'), '--input', str(tmp / 'extended-mountain.svg'),
                    '--output', str(tmp / NAMES[0])], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return tmp, 'regenerated --ext-summit-gauntlet'


def tearDownModule():
    if EVIDENCE and OUT:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'traversals.json').write_text(json.dumps(OUT, separators=(',', ':')) + '\n')
    if EVIDENCE and CLIMB_OUT:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'climbs.json').write_text(json.dumps(CLIMB_OUT, indent=1) + '\n')


class GauntletRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from browser_test_support import start_browser_test, wait_for_boot_run
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.dir, source = level_dir(cls.stack)
        cls.m = json.loads((cls.dir / NAMES[1]).read_text())
        cls.level = json.loads((cls.dir / NAMES[0]).read_text())
        cls.gauntlet = {z['id']: z for z in cls.m['extSummit']['gauntlet']['zones']}
        cls.ids = {f['semanticId']: f['id'] for f in cls.m['fragments'] if f.get('semanticId')}
        cls.zones = {z['id']: z for z in cls.m['noGrappleZones']}
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.page = cls.browser.new_page(viewport={'width': 1280, 'height': 720})
        cls.page.errors = []
        cls.page.on('pageerror', lambda e: cls.page.errors.append(str(e)))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.add_script_tag(path=str(TOOLS / 'opening_combination_replay.js'))
        OUT.update(method='Real index.html; production importedMountainLevel() and physics() once per tick on '
                          'tools/opening_combination_replay.js; document mouse events at the recorded ticks of '
                          'tools/fixtures/gauntlet-inputs-Zk.json; nothing written after the zero-speed fixture. path: [tick, x, y] every 5 ticks.',
                   level=source, levelDir=str(cls.dir), layoutId=cls.level['layoutId'],
                   levelHashes={n: sha(cls.dir / n) for n in NAMES}, zones={})

    @classmethod
    def probe_page(cls):
        # Climb transfers run on their own page: ROUTE_PROBE patches applyBounce and rendering hooks.
        if not hasattr(cls, 'probe'):
            from browser_test_support import wait_for_boot_run
            cls.probe = cls.browser.new_page()
            cls.probe.errors = []
            cls.probe.on('pageerror', lambda e: cls.probe.errors.append(str(e)))
            cls.probe.goto(cls.url)
            wait_for_boot_run(cls.probe)
            cls.probe.add_script_tag(path=str(TOOLS / 'probe_level_routes.js'))
        return cls.probe

    def safe_spaces(self):
        fs = {f['id']: f for f in self.m['fragments']}
        out = []
        for s in self.m['extSummit']['gauntlet']['safeSpaces']:
            ids = [s['start']] + [p['id'] for p in s['grapplePanels']] + [s['end']]
            out.append(dict(id=s['id'], side=s['side'], panels=[fs[p['id']]['semanticId'] for p in s['grapplePanels']],
                            transfers=[[fs[a]['semanticId'], fs[b]['semanticId']] for a, b in zip(ids, ids[1:])]))
        return out

    def climb(self, t, finish=False):
        page = self.probe_page()
        pol = {k: t[k] for k in POLICY_KEYS if k in t}
        self.assertEqual(pol['drop'], 300)
        o = dict(pol, source=self.ids[t['source']], target=self.ids[t['target']], level=self.level, untilFinish=finish)
        runs = [page.evaluate(CLIMB, o) for _ in range(2)]
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(page.errors, [])
        r = runs[0]
        self.assertIsNotNone(r['hit'], t)
        self.assertEqual(r['hit']['id'], self.ids[t['target']] + '-body0', t)
        self.assertEqual((r['setup']['vx'], r['setup']['vy']), (0, 0))
        row = dict(source=t['source'], target=t['target'], policy=pol, pumps=pol['pumps'], hooks=r['hooks'],
                   hit=dict(kind=r['hit']['kind'], tick=r['hit']['tick'], id=r['hit']['id']), bounces=r['bounces'],
                   ticks=r['ticks'], identicalSecondRun=runs[0] == runs[1])
        if finish:
            self.assertTrue(r['completed'], r)
            f, q = self.level['finish'], r['finish']
            self.assertAlmostEqual(f['top'], self.m['extSummit']['gauntlet']['finish']['finishTop'], places=6)
            self.assertTrue(f['left'] <= q['x'] <= f['right'] and f['top'] <= q['y'] <= f['bottom'], (q, f))
            self.assertGreater(q['tick'], r['hit']['tick'])
            row['finish'] = dict(completed=r['completed'], tick=q['tick'], at=[q['x'], q['y']], finishRect=f, hooks=r['hooks'])
        return row

    def climb_transfers(self):
        rec = json.loads(CLIMBS.read_text())
        spaces = self.safe_spaces()
        want = [tr for s in spaces for tr in s['transfers']]
        self.assertEqual([[t['source'], t['target']] for t in rec['transfers']], want)
        self.assertEqual(len(want), 27)
        by = {(t['source'], t['target']): t for t in rec['transfers']}
        out = []
        for s in spaces:
            self.assertLessEqual(len(s['panels']), 2, s)
            rows = []
            for a, b in s['transfers']:
                with self.subTest(space=s['id'], source=a, target=b):
                    rows.append(self.climb(by[(a, b)], finish=b == 'XS-SUMMIT'))
            out.append(dict(space=s['id'], side=s['side'], grapplePanels=[self.ids[p] for p in s['panels']],
                            grapplePanelSemanticIds=s['panels'], panelCount=len(s['panels']), transfers=rows,
                            totalHooks=sum(r['hooks'] for r in rows), totalPumps=sum(r['pumps'] for r in rows)))
        self.assertEqual(sum(len(s['transfers']) for s in out), 27)
        return out

    def test_00_every_filled_zone_has_a_case(self):
        filled = sorted(z for z, g in self.gauntlet.items() if g['slabs'])
        self.assertEqual(filled, sorted(ZONES))

    def crossing(self, z):
        rec = json.loads(INPUTS[z].read_text())
        g, zone = self.gauntlet[z], self.zones[z]
        self.assertEqual((rec['zone'], rec['exit'], rec['fixture']['panel']), (z, z + '-EXIT', z + '-APPROACH'))
        slabs = [s['semanticId'] for s in g['slabs']]
        self.assertTrue(slabs)
        runs = [self.page.evaluate(LEG, dict(level=self.level, ids=self.ids, fixture=rec['fixture'], inputs=rec['inputs'],
                                             budget=rec['budget'], exit=rec['exit'], restSpeed=REST_SPEED))
                for _ in range(2)]
        log = runs[0]
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(self.page.errors, [])
        self.assertEqual((log['layoutId'], log['acquisitionRadius']), (self.level['layoutId'], 540))
        # Only the fixture places the player (zero speed on the approach ledge); then real mouse events only.
        self.assertEqual((log['fixture']['vx'], log['fixture']['vy'], log['fixture']['drop']), (0, 0, 0))
        self.assertEqual(log['fixture']['panel'], self.ids[z + '-APPROACH'])
        self.assertTrue(all(e['type'] in ('down', 'up') for e in log['inputs']))
        self.assertLess(log['maxStep'], 200)
        self.assertEqual(log['recoveries'], [])
        self.assertFalse(log['start']['inside'])
        self.assertEqual((zone['width'], zone['height']), (5760, 4320))
        self.assertEqual([b['event'] for b in log['boundary']], ['enter', 'exit'])
        enter, leave = log['boundary']
        right = g['direction'] == 'RIGHT'
        x0, x1 = zone['x'], zone['x'] + zone['width']
        # In through the entry side, out through the far side; well above the recovery depth.
        if right:
            self.assertLess(enter['x'], x0 + 20)
            self.assertGreater(leave['x'], x1)
        else:
            self.assertGreater(enter['x'], x1 - 20)
            self.assertLess(leave['x'], x0)
        depth = self.level['spawn']['y'] + RECOVERY_DEPTH
        self.assertLess(log['maxY'], depth)
        self.assertLess(leave['y'], depth)
        body = lambda c: c['id'].split('-')[0]
        internal = {self.ids[s] for s in slabs}
        before = [c for c in log['contacts'] if c['tick'] < enter['tick']]
        within = [c for c in log['contacts'] if enter['tick'] <= c['tick'] < leave['tick']]
        after = [c for c in log['contacts'] if c['tick'] >= leave['tick']]
        self.assertEqual({body(c) for c in before}, {self.ids[z + '-APPROACH']})
        self.assertTrue(within)
        self.assertTrue({body(c) for c in within} <= internal, within)
        seq = []
        for c in within:
            if not seq or seq[-1] != body(c):
                seq.append(body(c))
        # Rope-free inside: nothing attached or thrown while the circle overlaps the zone; a press there is blocked.
        self.assertEqual((log['insideAttached'], log['insideThrown']), (0, 0))
        attaches = [a for a in log['grapple'] if a['event'] == 'attach']
        self.assertFalse([a for a in attaches if a['tick'] >= enter['tick']])
        blocked = [p for p in log['presses'] if p['inside']]
        self.assertTrue(all(p['stale'] and not p['thrown'] for p in blocked))
        # No rest inside the zone.
        self.assertLess(log['maxSlow'], REST_TICKS)
        # Landing on the exit ledge's top with no rope.
        exit_id = self.ids[rec['exit']]
        self.assertIsNotNone(log['landed'])
        self.assertEqual(body(log['landed']), exit_id)
        self.assertLess(log['landed']['ny'], -.99)
        self.assertEqual(log['ropeAtLanding'], {'grappled': False, 'throwed': False})
        self.assertEqual({body(c) for c in after}, {exit_id})
        keep = lambda b: {k: b[k] for k in ('tick', 'x', 'y', 'vx', 'vy')}
        sem = {v: k for k, v in self.ids.items()}
        return dict(inputs=str(INPUTS[z].relative_to(ROOT)), inputsSha256=sha(INPUTS[z]),
                    zone=[zone['x'], zone['y'], zone['width'], zone['height']], direction=g['direction'],
                    slabs=slabs, fixture=log['fixture'], inputEvents=[dict(tick=i['tick'], type=i['type']) for i in log['inputs']],
                    enter=keep(enter), exit=keep(leave), insideTicks=log['insideTicks'],
                    insideAttachedTicks=log['insideAttached'], insideThrownTicks=log['insideThrown'], pressesInside=blocked,
                    internalSequence=[sem[b] for b in seq], maxSlowTicksInside=log['maxSlow'], minSpeedInside=log['minSpeed'],
                    lowestInsideY=log['maxY'], recoveryDepthY=depth,
                    landing=dict(tick=log['landed']['tick'], on=rec['exit'], id=exit_id, x=log['landed']['x'], y=log['landed']['y'],
                                 rope=log['ropeAtLanding']),
                    contacts=[dict(tick=c['tick'], on=sem[body(c)], x=c['x'], y=c['y']) for c in log['contacts']],
                    path=log['path']+[[log['final']['tick'], log['final']['x'], log['final']['y']]],
                    recoveries=len(log['recoveries']), maxStepPerTick=log['maxStep'], ticks=log['ticks'],
                    secondRun=dict(identical=runs[0] == runs[1], ticks=runs[1]['ticks'], final=runs[1]['final']))

    def test_climb_transfers(self):
        spaces = self.climb_transfers()
        DONE['climbs'] = spaces
        last = spaces[-1]['transfers'][-1]
        self.assertTrue(last['finish']['completed'])
        CLIMB_OUT.update(inputs=str(CLIMBS.relative_to(ROOT)), inputsSha256=sha(CLIMBS), layoutId=self.level['layoutId'],
                         levelHashes={n: sha(self.dir / n) for n in NAMES}, transfers=sum(len(s['transfers']) for s in spaces),
                         method='ROUTE_PROBE per transfer: zero-speed fixture drop 300 above the source top, then only '
                                'document mouse events and physics(); first later-panel contact/attach == target; run twice. '
                                'hooks = attaches counted by physics() (climbStats.grapples), reported, not capped; '
                                'S8-G2 -> XS-SUMMIT replayed on until climbStats.completed.',
                         maxPanelsPerSafeSpace=max(s['panelCount'] for s in spaces), safeSpaces=spaces,
                         finish=dict(completed=last['finish']['completed'], transfer=[last['source'], last['target']],
                                     tick=last['finish']['tick'], at=last['finish']['at']))

    def test_z1_crossing(self):
        OUT['zones']['Z1'] = DONE['Z1'] = self.crossing('Z1')

    def test_z2_crossing(self):
        OUT['zones']['Z2'] = DONE['Z2'] = self.crossing('Z2')

    def test_z3_crossing(self):
        OUT['zones']['Z3'] = DONE['Z3'] = self.crossing('Z3')

    def test_z4_crossing(self):
        OUT['zones']['Z4'] = DONE['Z4'] = self.crossing('Z4')

    def test_z5_crossing(self):
        OUT['zones']['Z5'] = DONE['Z5'] = self.crossing('Z5')

    def test_z6_crossing(self):
        OUT['zones']['Z6'] = DONE['Z6'] = self.crossing('Z6')

    def test_z7_crossing(self):
        OUT['zones']['Z7'] = DONE['Z7'] = self.crossing('Z7')

    def test_z8_crossing(self):
        OUT['zones']['Z8'] = DONE['Z8'] = self.crossing('Z8')

    def test_zz_full_run(self):
        # The chained proof: S0, Z1, S1, ..., Z8, S8, each leg passing (reused from this run's cases when they ran) and
        # each one ending on the panel the next starts from; the last transfer reaches the finish.
        spaces = DONE.get('climbs') or self.climb_transfers()
        legs, at = [], spaces[0]['transfers'][0]['source']
        for k, s in enumerate(spaces):
            for t in s['transfers']:
                self.assertEqual(t['source'], at)
                legs.append(dict(leg=s['space'], source=t['source'], target=t['target'], hooks=t['hooks'], hitTick=t['hit']['tick']))
                at = t['target']
            if k < len(ZONES):
                z = ZONES[k]
                self.assertEqual(at, z + '-APPROACH')
                r = DONE.get(z) or self.crossing(z)
                self.assertEqual(r['landing']['on'], z + '-EXIT')
                legs.append(dict(leg=z, source=at, target=r['landing']['on'], landingTick=r['landing']['tick'],
                                 rope=r['landing']['rope']))
                at = r['landing']['on']
        self.assertEqual(at, 'XS-SUMMIT')
        self.assertEqual(len(legs), 27 + len(ZONES))
        fin = spaces[-1]['transfers'][-1]['finish']
        self.assertTrue(fin['completed'])
        OUT['fullRun'] = CLIMB_OUT['fullRun'] = dict(legs=legs, count=len(legs), allPassed=True, completed=fin['completed'],
                                                     finishTick=fin['tick'], hooksTotal=sum(l.get('hooks', 0) for l in legs))


if __name__ == '__main__':
    unittest.main()
