"""Production-input crossings of the tall purple zones of SEC-sky-spire (--sky-spire candidate, TASK-763..).

One case per filled zone (ZONES; a zone with slabs but no case fails test_00). Each case is one continuous replay in
the real index.html (tools/opening_combination_replay.js: production importedMountainLevel(), physics() once per tick,
document mouse events at the recorded ticks of tools/fixtures/spire-inputs-Yk.json; nothing written after the
zero-speed fixture on the zone's approach ledge), as tools/test_gauntlet_route.py does for Z1..Z8. It must: run off the
approach ledge into the zone through its entry side, cross it touching only the zone's own slabs with no rope attached
or thrown while the player overlaps the zone (a press inside stays blocked), never rest inside (REST_TICKS ticks in a
row slower than REST_SPEED), ricochet DOWN at least DESCENT (4,320) under the approach top inside the zone (tall-zone
contract, level-guidelines.md Sky Spire addendum: the slabs span >= 4,320 vertically), leave through the far side above
the fall-recovery depth and land on the exit ledge's top with no rope. Each case runs twice and both logs must be
identical.

test_climb_transfers replays the 27 safe-space climb transfers of tools/fixtures/spire-climb-inputs.json (T0..T8: start
ledge -> SP-Tk-G1 -> SP-Tk-G2 -> SP-Y(k+1)-APPROACH; T0 starts on the gauntlet finish ledge XS-SUMMIT, T8 ends on
SP-SUMMIT; at most 2 grapple panels per safe space) per transfer, as tools/test_gauntlet_route.py does for S0..S8:
tools/probe_level_routes.js ROUTE_PROBE places the player at zero speed drop 300 above the source top, then only document
mouse events and physics(); the first contact/attach on a later panel must be the target. Each transfer runs twice and
must be identical. test_full_spire_run is the chained run from the gauntlet finish ledge to the new finish: T0, Y1, T1,
..., Y8, T8 in order (the zone legs are the spire-inputs-Yk.json crossings), each leg ending on the panel the next one
starts from, every leg passing, and the last transfer (SP-T8-G2 -> SP-SUMMIT) replayed on until climbStats.completed
inside the level's finish rectangle. Legs already run by test_climb_transfers / test_yk_crossing are reused.

Level: SPIRE_CANDIDATE=DIR (extended-mountain.level.json and extended-mountain-measurements.json). Without it the
shipped artifacts/levels data is used when it has skySpire (from TASK-774); otherwise the candidate is regenerated into a
temporary directory (tools/retune_extended_level.py --sky-spire, then tools/import_level_svg.py; ~5 min).

SPIRE_EVIDENCE_DIR=DIR writes traversals.json and climbs.json (compact). No default evidence directory.

    python3 tools/test_spire_route.py -v
    python3 tools/test_spire_route.py -k y1
    python3 tools/test_spire_route.py -k y2
    python3 tools/test_spire_route.py -k y3
    python3 tools/test_spire_route.py -k y4
    python3 tools/test_spire_route.py -k y5
    python3 tools/test_spire_route.py -k y6
    python3 tools/test_spire_route.py -k climb
    python3 tools/test_spire_route.py -k full_spire_run
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

from test_gauntlet_route import CLIMB, LEG, NAMES, POLICY_KEYS, RECOVERY_DEPTH, REST_SPEED, REST_TICKS, SHIPPED, SOURCE, sha

EVIDENCE = os.environ.get('SPIRE_EVIDENCE_DIR')
CANDIDATE = os.environ.get('SPIRE_CANDIDATE')
PREFIX = 'SP-'
ZONES = ('Y1', 'Y2', 'Y3', 'Y4', 'Y5', 'Y6', 'Y7', 'Y8')
INPUTS = {z: TOOLS / 'fixtures' / ('spire-inputs-%s.json' % z) for z in ZONES}
ZONE_SIZE = (6912, 8640)
CLIMBS = TOOLS / 'fixtures' / 'spire-climb-inputs.json'
START, FINISH = 'XS-SUMMIT', PREFIX + 'SUMMIT'  # the gauntlet finish ledge and the Sky Spire finish ledge
DESCENT = 4320  # tall-zone contract: slabs span >= 4,320 vertically, the crossing goes down at least that far
OUT = {}
CLIMB_OUT = {}
DONE = {}  # leg results of this run, shared by the per-leg tests and test_full_spire_run


def level_dir(stack):
    if CANDIDATE:
        return Path(CANDIDATE), 'SPIRE_CANDIDATE'
    if 'skySpire' in json.loads((SHIPPED / NAMES[1]).read_text()):
        return SHIPPED, 'shipped'
    tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='spire-')))
    subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source', str(SOURCE), '--output-dir', str(tmp),
                    '--sky-spire'], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(TOOLS / 'import_level_svg.py'), '--input', str(tmp / 'extended-mountain.svg'),
                    '--output', str(tmp / NAMES[0])], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return tmp, 'regenerated --sky-spire'


def tearDownModule():
    if EVIDENCE and OUT.get('zones'):
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'traversals.json').write_text(json.dumps(OUT, separators=(',', ':')) + '\n')
    if EVIDENCE and CLIMB_OUT:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'climbs.json').write_text(json.dumps(CLIMB_OUT, separators=(',', ':')) + '\n')


class SpireRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from browser_test_support import start_browser_test, wait_for_boot_run
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.dir, source = level_dir(cls.stack)
        cls.m = json.loads((cls.dir / NAMES[1]).read_text())
        cls.level = json.loads((cls.dir / NAMES[0]).read_text())
        cls.spire = {z['id']: z for z in cls.m['skySpire']['zones']}
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
                          'tools/fixtures/spire-inputs-Yk.json; nothing written after the zero-speed fixture. path: [tick, x, y] every 5 ticks.',
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
        for s in self.m['skySpire']['safeSpaces']:
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
        row = dict(source=t['source'], target=t['target'], policy=pol, hooks=r['hooks'],
                   hit=dict(kind=r['hit']['kind'], tick=r['hit']['tick']), ticks=r['ticks'])
        if finish:
            self.assertTrue(r['completed'], r)
            f, q = self.level['finish'], r['finish']
            self.assertAlmostEqual(f['top'], self.m['skySpire']['finish']['finishTop'], places=6)
            self.assertTrue(f['left'] <= q['x'] <= f['right'] and f['top'] <= q['y'] <= f['bottom'], (q, f))
            self.assertGreater(q['tick'], r['hit']['tick'])
            row['finish'] = dict(completed=r['completed'], tick=q['tick'], at=[round(q['x'], 3), round(q['y'], 3)])
        return row

    def climb_transfers(self):
        if 'climbs' in DONE:
            return DONE['climbs']
        rec = json.loads(CLIMBS.read_text())
        spaces = self.safe_spaces()
        self.assertEqual([s['id'] for s in spaces], ['T%d' % k for k in range(len(ZONES) + 1)])
        self.assertEqual(spaces[0]['transfers'][0][0], START)
        self.assertEqual(spaces[-1]['transfers'][-1][1], FINISH)
        want = [tr for s in spaces for tr in s['transfers']]
        self.assertEqual([[t['source'], t['target']] for t in rec['transfers']], want)
        self.assertEqual(len(want), 27)
        by = {(t['source'], t['target']): t for t in rec['transfers']}
        out = []
        for s in spaces:
            self.assertLessEqual(len(s['panels']), 2, s)
            rows = [self.climb(by[(a, b)], finish=b == FINISH) for a, b in s['transfers']]
            # Grapple panels the rope hooks in this safe space (pump sources and targets; ledges are not panels).
            used = sorted({p for r in rows for p in (r['source'], r['target'])} & set(s['panels']))
            self.assertLessEqual(len(used), 2, used)
            out.append(dict(space=s['id'], grapplePanels=s['panels'], panelCount=len(s['panels']), grapplePanelsUsed=used,
                            transfers=rows, hooks=sum(r['hooks'] for r in rows)))
        DONE['climbs'] = out
        return out

    def zone_leg(self, z):
        if z not in DONE:
            DONE[z] = self.crossing(z)
        OUT['zones'][z] = DONE[z]
        return DONE[z]

    def test_00_every_filled_zone_has_a_case(self):
        filled = sorted(z for z, g in self.spire.items() if g['slabs'])
        self.assertEqual(filled, sorted(ZONES))

    def crossing(self, z):
        rec = json.loads(INPUTS[z].read_text())
        g, zone = self.spire[z], self.zones[z]
        approach, exit_ = PREFIX + z + '-APPROACH', PREFIX + z + '-EXIT'
        self.assertEqual((rec['zone'], rec['exit'], rec['fixture']['panel']), (z, exit_, approach))
        slabs = [s['semanticId'] for s in g['slabs']]
        self.assertTrue(slabs)
        # Tall-zone contract: 6912 x 8640, approach 600 under the zone top, exit 342..4320 lower on the far side,
        # slabs spanning >= 4320 vertically.
        self.assertEqual((zone['width'], zone['height']), ZONE_SIZE)
        self.assertAlmostEqual(g['approach']['top'] - zone['y'], 600, places=6)
        self.assertTrue(342 <= g['exit']['top'] - g['approach']['top'] <= 4320, g['exit'])
        span = max(s['y1'] for s in g['slabs']) - min(s['y0'] for s in g['slabs'])
        self.assertGreaterEqual(span, DESCENT)
        runs = [self.page.evaluate(LEG, dict(level=self.level, ids=self.ids, fixture=rec['fixture'], inputs=rec['inputs'],
                                             budget=rec['budget'], exit=exit_, restSpeed=REST_SPEED))
                for _ in range(2)]
        log = runs[0]
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(self.page.errors, [])
        self.assertEqual((log['layoutId'], log['acquisitionRadius']), (self.level['layoutId'], 540))
        # Only the fixture places the player (zero speed on the approach ledge); then real mouse events only.
        self.assertEqual((log['fixture']['vx'], log['fixture']['vy'], log['fixture']['drop']), (0, 0, 0))
        self.assertEqual(log['fixture']['panel'], self.ids[approach])
        self.assertTrue(all(e['type'] in ('down', 'up') for e in log['inputs']))
        self.assertLess(log['maxStep'], 200)
        self.assertEqual(log['recoveries'], [])
        self.assertFalse(log['start']['inside'])
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
        # Down through the zone: the lowest point inside is >= DESCENT under the approach top.
        descent = log['maxY'] - g['approach']['top']
        self.assertGreaterEqual(descent, DESCENT)
        body = lambda c: c['id'].split('-')[0]
        internal = {self.ids[s] for s in slabs}
        before = [c for c in log['contacts'] if c['tick'] < enter['tick']]
        within = [c for c in log['contacts'] if enter['tick'] <= c['tick'] < leave['tick']]
        after = [c for c in log['contacts'] if c['tick'] >= leave['tick']]
        self.assertEqual({body(c) for c in before}, {self.ids[approach]})
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
        exit_id = self.ids[exit_]
        self.assertIsNotNone(log['landed'])
        self.assertEqual(body(log['landed']), exit_id)
        self.assertLess(log['landed']['ny'], -.99)
        self.assertEqual(log['ropeAtLanding'], {'grappled': False, 'throwed': False})
        self.assertEqual({body(c) for c in after}, {exit_id})
        keep = lambda b: {k: b[k] for k in ('tick', 'x', 'y', 'vx', 'vy')}
        sem = {v: k for k, v in self.ids.items()}
        return dict(inputs=str(INPUTS[z].relative_to(ROOT)), inputsSha256=sha(INPUTS[z]),
                    zone=[zone['x'], zone['y'], zone['width'], zone['height']], direction=g['direction'],
                    slabs=slabs, slabSpan=round(span, 3), fixture=log['fixture'],
                    inputEvents=[dict(tick=i['tick'], type=i['type']) for i in log['inputs']],
                    enter=keep(enter), exit=keep(leave), insideTicks=log['insideTicks'],
                    insideAttachedTicks=log['insideAttached'], insideThrownTicks=log['insideThrown'], pressesInside=blocked,
                    internalSequence=[sem[b] for b in seq], maxSlowTicksInside=log['maxSlow'], minSpeedInside=log['minSpeed'],
                    lowestInsideY=log['maxY'], descentUnderApproach=round(descent, 3), recoveryDepthY=depth,
                    landing=dict(tick=log['landed']['tick'], on=exit_, id=exit_id, x=log['landed']['x'], y=log['landed']['y'],
                                 rope=log['ropeAtLanding']),
                    contacts=[dict(tick=c['tick'], on=sem[body(c)], x=c['x'], y=c['y']) for c in log['contacts']],
                    path=log['path']+[[log['final']['tick'], log['final']['x'], log['final']['y']]],
                    recoveries=len(log['recoveries']), maxStepPerTick=log['maxStep'], ticks=log['ticks'],
                    secondRun=dict(identical=runs[0] == runs[1], ticks=runs[1]['ticks'], final=runs[1]['final']))

    def test_y1_crossing(self):
        self.zone_leg('Y1')

    def test_y2_crossing(self):
        self.zone_leg('Y2')

    def test_y3_crossing(self):
        self.zone_leg('Y3')

    def test_y4_crossing(self):
        self.zone_leg('Y4')

    def test_y5_crossing(self):
        self.zone_leg('Y5')

    def test_y6_crossing(self):
        self.zone_leg('Y6')

    def test_y7_crossing(self):
        self.zone_leg('Y7')

    def test_y8_crossing(self):
        self.zone_leg('Y8')

    def test_climb_transfers(self):
        spaces = self.climb_transfers()
        fin = spaces[-1]['transfers'][-1]['finish']
        self.assertTrue(fin['completed'])
        CLIMB_OUT.update(inputs=str(CLIMBS.relative_to(ROOT)), inputsSha256=sha(CLIMBS), layoutId=self.level['layoutId'],
                         levelHashes={n: sha(self.dir / n) for n in NAMES}, transfers=sum(len(s['transfers']) for s in spaces),
                         method='ROUTE_PROBE per transfer: zero-speed fixture drop 300 above the source top, then only '
                                'document mouse events and physics(); first later-panel contact/attach == target; run twice '
                                '(identical). grapplePanelsPerSafeSpace = grapple panels the climb hooks in each safe space (<= 2, asserted); hooks = attaches counted '
                                'by physics() (climbStats.grapples, pumps included), reported, not capped; '
                                'SP-T8-G2 -> SP-SUMMIT replayed on until climbStats.completed.',
                         grapplePanelsPerSafeSpace={s['space']: len(s['grapplePanelsUsed']) for s in spaces},
                         maxPanelsPerSafeSpace=max(s['panelCount'] for s in spaces), safeSpaces=spaces,
                         finish=dict(fin, transfer=spaces[-1]['transfers'][-1]['target']))

    def test_full_spire_run(self):
        # The chained run: T0 (from the gauntlet finish ledge), Y1, T1, ..., Y8, T8; each leg passing and ending on the
        # panel the next one starts from; the last transfer reaches the Sky Spire finish.
        spaces = self.climb_transfers()
        legs, at = [], START
        for k, s in enumerate(spaces):
            for t in s['transfers']:
                self.assertEqual(t['source'], at)
                legs.append(dict(leg=s['space'], source=t['source'], target=t['target'], hooks=t['hooks'], hitTick=t['hit']['tick']))
                at = t['target']
            if k < len(ZONES):
                z = ZONES[k]
                self.assertEqual(at, PREFIX + z + '-APPROACH')
                r = self.zone_leg(z)
                self.assertEqual(r['landing']['on'], PREFIX + z + '-EXIT')
                self.assertEqual(r['landing']['rope'], {'grappled': False, 'throwed': False})
                legs.append(dict(leg=z, source=at, target=r['landing']['on'], landingTick=r['landing']['tick'],
                                 descent=r['descentUnderApproach']))
                at = r['landing']['on']
        self.assertEqual(at, FINISH)
        self.assertEqual(len(legs), 27 + len(ZONES))
        fin = spaces[-1]['transfers'][-1]['finish']
        self.assertTrue(fin['completed'])
        OUT['fullRun'] = CLIMB_OUT['fullRun'] = dict(start=START, finish=FINISH, legs=legs, count=len(legs), allPassed=True,
                                                     completed=fin['completed'], finishTick=fin['tick'], finishAt=fin['at'],
                                                     hooksTotal=sum(l.get('hooks', 0) for l in legs))


if __name__ == '__main__':
    unittest.main()
