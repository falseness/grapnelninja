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

Level: SPIRE_CANDIDATE=DIR (extended-mountain.level.json and extended-mountain-measurements.json). Without it the
shipped artifacts/levels data is used when it has skySpire (from TASK-774); otherwise the candidate is regenerated into a
temporary directory (tools/retune_extended_level.py --sky-spire, then tools/import_level_svg.py; ~5 min).

SPIRE_EVIDENCE_DIR=DIR writes traversals.json (compact). No default evidence directory.

    python3 tools/test_spire_route.py -v
    python3 tools/test_spire_route.py -k y1
    python3 tools/test_spire_route.py -k y2
    python3 tools/test_spire_route.py -k y3
    python3 tools/test_spire_route.py -k y4
    python3 tools/test_spire_route.py -k y5
    python3 tools/test_spire_route.py -k y6
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

from test_gauntlet_route import LEG, NAMES, RECOVERY_DEPTH, REST_SPEED, REST_TICKS, SHIPPED, SOURCE, sha

EVIDENCE = os.environ.get('SPIRE_EVIDENCE_DIR')
CANDIDATE = os.environ.get('SPIRE_CANDIDATE')
PREFIX = 'SP-'
ZONES = ('Y1', 'Y2', 'Y3', 'Y4', 'Y5', 'Y6', 'Y7', 'Y8')
INPUTS = {z: TOOLS / 'fixtures' / ('spire-inputs-%s.json' % z) for z in ZONES}
ZONE_SIZE = (6912, 8640)
DESCENT = 4320  # tall-zone contract: slabs span >= 4,320 vertically, the crossing goes down at least that far
OUT = {}


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
        OUT['zones']['Y1'] = self.crossing('Y1')

    def test_y2_crossing(self):
        OUT['zones']['Y2'] = self.crossing('Y2')

    def test_y3_crossing(self):
        OUT['zones']['Y3'] = self.crossing('Y3')

    def test_y4_crossing(self):
        OUT['zones']['Y4'] = self.crossing('Y4')

    def test_y5_crossing(self):
        OUT['zones']['Y5'] = self.crossing('Y5')

    def test_y6_crossing(self):
        OUT['zones']['Y6'] = self.crossing('Y6')

    def test_y7_crossing(self):
        OUT['zones']['Y7'] = self.crossing('Y7')

    def test_y8_crossing(self):
        OUT['zones']['Y8'] = self.crossing('Y8')


if __name__ == '__main__':
    unittest.main()
