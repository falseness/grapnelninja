"""Production-input crossings of the gauntlet zones of SEC-ext-summit (--ext-summit-gauntlet, TASK-733..).

One case per filled zone (ZONES; a zone with slabs but no case fails test_00). Each case is one continuous replay in
the real index.html (tools/opening_combination_replay.js: production importedMountainLevel(), physics() once per tick,
document mouse events at the recorded ticks of tools/fixtures/gauntlet-inputs-Zk.json; nothing written after the
zero-speed fixture on the zone's approach ledge). It must: run off the approach ledge into the zone through its entry
side, cross it touching only the zone's own slabs with no rope attached or thrown while the player overlaps the zone
(a press inside stays blocked), never rest inside (REST_TICKS ticks in a row slower than REST_SPEED), leave through the
far side above the fall-recovery depth and land on the exit ledge's top with no rope. Each case runs twice and both
logs must be identical.

Level: GAUNTLET_CANDIDATE=DIR (extended-mountain.level.json and extended-mountain-measurements.json). Without it the
shipped artifacts/levels data is used when it has extSummit.gauntlet; otherwise the candidate is regenerated into a
temporary directory (tools/retune_extended_level.py --ext-summit-gauntlet, then tools/import_level_svg.py).

GAUNTLET_EVIDENCE_DIR=DIR writes traversals.json (compact). No default evidence directory.

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
ZONES = ('Z1', 'Z2', 'Z3', 'Z4', 'Z5')
INPUTS = {z: TOOLS / 'fixtures' / ('gauntlet-inputs-%s.json' % z) for z in ZONES}
RECOVERY_DEPTH = 1500  # physics.js CLIMB_FALL_RECOVERY_DEPTH
REST_SPEED, REST_TICKS = 0.05, 30
OUT = {}

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

    def test_z1_crossing(self):
        OUT['zones']['Z1'] = self.crossing('Z1')

    def test_z2_crossing(self):
        OUT['zones']['Z2'] = self.crossing('Z2')

    def test_z3_crossing(self):
        OUT['zones']['Z3'] = self.crossing('Z3')

    def test_z4_crossing(self):
        OUT['zones']['Z4'] = self.crossing('Z4')

    def test_z5_crossing(self):
        OUT['zones']['Z5'] = self.crossing('Z5')


if __name__ == '__main__':
    unittest.main()
