"""Production-input traversals of SEC-ext-summit, the three big zones above the old summit (TASK-709).

Per zone BZ1..BZ3 one continuous replay in the real index.html (tools/opening_combination_replay.js: production
importedMountainLevel(), physics() once per tick, document mouse events at the recorded ticks of
tools/fixtures/ext-summit-inputs-BZn.json; nothing written after the zero-speed fixture on the zone's approach
ledge) covers the transfer into the zone, the rope-free crossing (one entry, one exit through the zone's left side,
no rope attached or thrown inside, the press inside blocked, no fall recovery), the landing on the exit ledge and
the transfer out: a fresh press after the exit, then an attach on the next grapple panel (the first panel of the
next climb, XS-C2a-1 / XS-C3a-1). The BZ3 leg ends with the last transfer: a grapple onto the new summit
XS-SUMMIT that pulls the player into the new finish (climbStats.completed). Each leg is replayed twice and must
give identical logs.

test_04 (TASK-724) proves every other transfer of the extension, from the old summit through every climb to each
zone's approach ledge, one transfer at a time in the repo's per-transfer form (tools/fixtures/harder-transfer-inputs.json):
tools/probe_level_routes.js ROUTE_PROBE places the player at zero speed `drop` above the source panel's top, then only
document mouse events (pumps / fraction / lastAimOffset policy of tools/fixtures/ext-summit-climb-inputs.json) and
physics() run; the first contact or attach on a later panel must be the target. Each is run twice (identical). The
fixture belongs to one layout: a level whose extension transfers differ from it (e.g. the shipped v18) skips test_04.

Level: EXT_SUMMIT_CANDIDATE=DIR (extended-mountain.level.json and extended-mountain-measurements.json, e.g. the
retune --ext-summit output of artifacts/TASK-708/candidate), else the shipped artifacts/levels data. A level
without the extension (extSummit in its measurements) skips every test, which is not a pass.

EXT_SUMMIT_EVIDENCE_DIR=DIR writes traversals.json (compact). No default evidence directory.

    EXT_SUMMIT_CANDIDATE=artifacts/TASK-708/candidate EXT_SUMMIT_EVIDENCE_DIR=artifacts/TASK-709 \\
        python3 -m unittest tools/test_ext_summit_route.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

EVIDENCE = os.environ.get('EXT_SUMMIT_EVIDENCE_DIR')
LEVEL_DIR = Path(os.environ.get('EXT_SUMMIT_CANDIDATE') or ROOT / 'artifacts' / 'levels')
NAMES = ('extended-mountain.level.json', 'extended-mountain-measurements.json')
ZONES = ('BZ1', 'BZ2', 'BZ3')
INPUTS = {z: TOOLS / 'fixtures' / ('ext-summit-inputs-%s.json' % z) for z in ZONES}
CLIMBS = TOOLS / 'fixtures' / 'ext-summit-climb-inputs.json'
POLICY_KEYS = ('pumps', 'fraction', 'lastAimOffset', 'targetWhenInRange', 'drop', 'budget')
RECOVERY_DEPTH = 1500  # physics.js CLIMB_FALL_RECOVERY_DEPTH
OUT = {}

# One leg: fixture, then only mouse events; stops at the attach on the next panel or at the finish.
LEG = '''o => {
    const ids = o.ids, frag = s => floors[0].byId.get(ids[s] + '-body0')
    const c = OPENING_REPLAY.start({level: o.level, fixture: {panel: ids[o.fixture.panel], fraction: o.fixture.fraction,
                                                              drop: o.fixture.drop}})
    const bottomAt = (e, f) => {
        const p = OPENING_REPLAY.topAt(e, f), ys = []
        for (const l of e.getLines()) if (p.x >= Math.min(l.x1, l.x2) && p.x <= Math.max(l.x1, l.x2) && l.x1 !== l.x2)
            ys.push(l.y1 + (p.x - l.x1) * (l.y2 - l.y1) / (l.x2 - l.x1))
        return {x: p.x, y: Math.max(...ys)}
    }
    const aim = a => { const p = (a.side === 'bottom' ? bottomAt : OPENING_REPLAY.topAt)(frag(a.panel), a.fraction); return [p.x, p.y] }
    const queue = [...o.inputs].sort((a, b) => a.tick - b.tick)
    const boundary = [], presses = []
    let inside = floors[0].playerInNoGrapple === true
    const start = {inside, ...c.state()}
    let insideTicks = 0, insideAttached = 0, insideThrown = 0, landed = null, next = null
    const exitBody = ids[o.exit] + '-body0', nextBody = ids[o.next] + '-body0'
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
        const now = floors[0].playerInNoGrapple === true
        if (now !== inside) { boundary.push({event: now ? 'enter' : 'exit', ...c.state()}); inside = now }
        if (now) { insideTicks++; if (grapnel.grappled) insideAttached++; if (grapnel.throwed) insideThrown++ }
        const out = boundary.some(b => b.event === 'exit')
        const land = fresh.find(k => k.id === exitBody && k.ny < -0.99)
        if (land && out && !landed) landed = land
        if (out && !next && grapnel.grappled && grapnel.pos.at(-1)[2].id === nextBody)
            next = {...c.state(), point: grapnel.pos.at(-1).slice(0, 2).map(v => +v.toFixed(3))}
        if (floors[0].climbStats.completed || (next && !o.finish)) break
    }
    if (c.held) c.release()
    return {start, boundary, presses, insideTicks, insideAttached, insideThrown, landed, next, ticks: c.tick,
            completed: floors[0].climbStats.completed === true, layoutId: c.log.layoutId,
            acquisitionRadius: c.log.acquisitionRadius, fixture: c.log.fixture, inputs: c.log.inputs,
            contacts: c.log.contacts, grapple: c.log.grapple, maxStep: c.log.maxStep, recoveries: c.log.recoveries,
            final: c.state()}
}'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tearDownModule():
    if EVIDENCE and OUT:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'traversals.json').write_text(json.dumps(OUT, separators=(',', ':')) + '\n')


class ExtSummitTraversalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = json.loads((LEVEL_DIR / NAMES[1]).read_text())
        if 'extSummit' not in cls.m:
            raise unittest.SkipTest('%s has no SEC-ext-summit (set EXT_SUMMIT_CANDIDATE)' % LEVEL_DIR)
        from browser_test_support import start_browser_test, wait_for_boot_run
        cls.level = json.loads((LEVEL_DIR / NAMES[0]).read_text())
        cls.ids = {f['semanticId']: f['id'] for f in cls.m['fragments'] if f.get('semanticId')}
        cls.zones = {z['id']: z for z in cls.m['noGrappleZones']}
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.page = cls.browser.new_page(viewport={'width': 1280, 'height': 720})
        cls.page.errors = []
        cls.page.on('pageerror', lambda e: cls.page.errors.append(str(e)))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.add_script_tag(path=str(TOOLS / 'opening_combination_replay.js'))
        OUT.update(method='Real index.html; production importedMountainLevel() and physics() once per tick on '
                          'tools/opening_combination_replay.js; document mouse events at the recorded ticks of '
                          'tools/fixtures/ext-summit-inputs-BZn.json; nothing written after the zero-speed fixture.',
                   levelDir=str(LEVEL_DIR), layoutId=cls.level['layoutId'],
                   levelHashes={n: sha(LEVEL_DIR / n) for n in NAMES}, zones={})

    def leg(self, z):
        rec = json.loads(INPUTS[z].read_text())
        self.assertEqual((rec['zone'], rec['exit'], rec['finish']), (z, z + '-EXIT', z == 'BZ3'))
        runs = [self.page.evaluate(LEG, dict(level=self.level, ids=self.ids, fixture=rec['fixture'], inputs=rec['inputs'],
                                             budget=rec['budget'], exit=rec['exit'], next=rec['next'], finish=rec['finish']))
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
        zone = self.zones[z]
        self.assertEqual((zone['width'], zone['height']), (5760, 4320))
        self.assertEqual([b['event'] for b in log['boundary']], ['enter', 'exit'])
        enter, leave = log['boundary']
        # Leftward zones: in through the right side, out through the left side; well above the recovery depth.
        self.assertGreater(enter['x'], zone['x'] + zone['width'] - 20)
        self.assertLess(leave['x'], zone['x'])
        self.assertLess(leave['y'], self.level['spawn']['y'] + RECOVERY_DEPTH)
        body = lambda c: c['id'].split('-')[0]
        internal = {self.ids['%s%d' % (z, k)] for k in range(1, 6)}
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
        # Rope-free inside: nothing attached or thrown while the circle overlaps the zone; the press there is blocked.
        self.assertEqual((log['insideAttached'], log['insideThrown']), (0, 0))
        attaches = [g for g in log['grapple'] if g['event'] == 'attach']
        self.assertFalse([g for g in attaches if enter['tick'] <= g['tick'] < leave['tick']])
        blocked = [p for p in log['presses'] if p['inside']]
        self.assertTrue(blocked)
        self.assertTrue(all(p['stale'] and not p['thrown'] for p in blocked))
        # Landing on the exit ledge, then fresh presses after the exit: the exit ledge, then the next panel.
        exit_id = self.ids[rec['exit']]
        self.assertIsNotNone(log['landed'])
        self.assertEqual(body(log['landed']), exit_id)
        self.assertLess(log['landed']['ny'], -.99)
        fresh = [g for g in attaches if g['tick'] >= leave['tick']]
        self.assertTrue(fresh)
        self.assertGreater(fresh[0]['tick'], log['landed']['tick'])
        self.assertTrue(all(not p['stale'] and p['thrown'] for p in log['presses'] if p['tick'] > leave['tick']))
        next_id = self.ids[rec['next']]
        self.assertIsNotNone(log['next'])
        self.assertEqual([body(g) for g in fresh], [exit_id, next_id])
        self.assertTrue({body(c) for c in after} <= {exit_id, next_id}, after)
        keep = lambda b: {k: b[k] for k in ('tick', 'x', 'y', 'vx', 'vy')}
        out = dict(inputs=str(INPUTS[z].relative_to(ROOT)), inputsSha256=sha(INPUTS[z]), zone=[zone['x'], zone['y'], zone['width'], zone['height']],
                   fixture=log['fixture'], inputEvents=[dict(tick=i['tick'], type=i['type']) for i in log['inputs']],
                   enterTick=enter['tick'], enter=keep(enter), exitTick=leave['tick'], exit=keep(leave),
                   exitThroughLeftSide=leave['x'] < zone['x'], insideTicks=log['insideTicks'],
                   insideAttachedTicks=log['insideAttached'], insideThrownTicks=log['insideThrown'],
                   insideAttachEvents=0, pressesInside=blocked, internalSequence=seq,
                   landingTick=log['landed']['tick'], landedOn=exit_id,
                   freshAttachAfterExit=dict(tick=fresh[0]['tick'], id=fresh[0]['id'], point=fresh[0]['point']),
                   nextPanel=dict(semanticId=rec['next'], id=next_id, attachTick=log['next']['tick'], point=log['next']['point']),
                   recoveries=len(log['recoveries']), maxStepPerTick=log['maxStep'], ticks=log['ticks'], final=log['final'],
                   completed=log['completed'],
                   secondRun=dict(identical=runs[0] == runs[1], enterTick=runs[1]['boundary'][0]['tick'],
                                  exitTick=runs[1]['boundary'][1]['tick'], landingTick=runs[1]['landed']['tick'],
                                  nextAttachTick=runs[1]['next']['tick'], ticks=runs[1]['ticks'], final=runs[1]['final']))
        return log, out

    def test_01_bz1_crossing_to_climb_2(self):
        log, out = self.leg('BZ1')
        self.assertFalse(log['completed'])
        OUT['zones']['BZ1'] = out

    def test_02_bz2_crossing_to_climb_3(self):
        log, out = self.leg('BZ2')
        self.assertFalse(log['completed'])
        OUT['zones']['BZ2'] = out

    def test_03_bz3_crossing_and_finish(self):
        log, out = self.leg('BZ3')
        # The last transfer: grappled onto the new summit, the player reaches the new finish.
        self.assertTrue(log['completed'])
        self.assertEqual(self.ids['XS-SUMMIT'], self.m['extSummit']['summit'])
        f, q = self.level['finish'], log['final']
        self.assertAlmostEqual(f['top'], self.m['extSummit']['finishTop'], places=6)
        self.assertTrue(f['left'] <= q['x'] <= f['right'] and f['top'] <= q['y'] <= f['bottom'], (q, f))
        self.assertGreater(log['final']['tick'], log['next']['tick'])
        out['finish'] = dict(completed=True, climbStatsCompleted=log['completed'], tick=q['tick'], at=[q['x'], q['y']], finish=f,
                             summit=self.ids['XS-SUMMIT'], summitAttachTick=log['next']['tick'])
        OUT['zones']['BZ3'] = out


    def test_04_climb_transfers(self):
        rec = json.loads(CLIMBS.read_text())
        fs = {f['id']: f for f in self.m['fragments']}
        seq = [fs[self.m['extSummit']['oldSummit']]]+[fs[i] for i in self.m['extSummit']['fragments']]
        # Every transfer not replayed by a BZ leg: the leg covers approach -> zone -> exit -> next climb, BZ3 -> summit.
        want = [[a['semanticId'], b['semanticId']] for a, b in zip(seq, seq[1:])
                if not a['semanticId'].startswith('BZ') and b['semanticId'] != 'XS-SUMMIT'
                and (not b['semanticId'].startswith('BZ') or b['semanticId'].endswith('-APPROACH'))]
        have = [[t['source'], t['target']] for t in rec['transfers']]
        if have != want:
            self.skipTest('%s is for another layout than %s (extension transfers differ)' % (CLIMBS.name, LEVEL_DIR))
        page = self.browser.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append(str(e)))
        page.goto(self.url)
        from browser_test_support import wait_for_boot_run
        wait_for_boot_run(page)
        page.add_script_tag(path=str(TOOLS / 'probe_level_routes.js'))
        rows = []
        for t in rec['transfers']:
            with self.subTest(source=t['source'], target=t['target']):
                pol = {k: t[k] for k in POLICY_KEYS if k in t}
                self.assertEqual(pol['drop'], 300)
                o = dict(pol, source=self.ids[t['source']], target=self.ids[t['target']], level=self.level)
                runs = [page.evaluate('o => { const r = ROUTE_PROBE.run(o); return {hit: r.hit, setup: r.setup, ticks: r.ticks, '
                                      'bounces: r.bounces, minY: r.minY} }', o) for _ in range(2)]
                self.assertEqual(runs[0], runs[1])
                hit = runs[0]['hit']
                self.assertIsNotNone(hit, t)
                self.assertEqual(hit['id'], self.ids[t['target']] + '-body0', t)
                self.assertEqual((runs[0]['setup']['vx'], runs[0]['setup']['vy']), (0, 0))
                rows.append(dict(source=t['source'], target=t['target'], policy=pol, hit=dict(kind=hit['kind'], tick=hit['tick'], id=hit['id']),
                                 bounces=runs[0]['bounces'], identicalSecondRun=runs[0] == runs[1]))
        self.assertEqual(page.errors, [])
        self.assertEqual(len(rows), len(want))
        OUT['climbs'] = dict(inputs=str(CLIMBS.relative_to(ROOT)), inputsSha256=sha(CLIMBS), transfers=len(rows),
                             method='ROUTE_PROBE per transfer: zero-speed fixture drop 300 above the source top, then only '
                                    'document mouse events and physics(); first later-panel contact/attach == target; run twice',
                             rows=rows)


if __name__ == '__main__':
    unittest.main()
