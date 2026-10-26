"""Big no-grapple zone crossing on the TASK-706 template fixture (TASK-707).

The fixture is regenerated from the template (retune_extended_level.py --big-zone-fixture) into a temporary
directory, checked with the default geometry rules, and replayed in the real index.html with the
tools/test_purple_route.py TRAVERSE harness (tools/opening_combination_replay.js): the player starts at zero
speed on the approach ledge, then only the document mouse events of tools/fixtures/big-zone-inputs.json and
production physics() drive it. It must cross the zone rope-free (one entry, one exit through the right side,
no rope attached or thrown inside, presses inside blocked), never be reset by the fall recovery, grapple the
exit ledge with a fresh press after the exit and land on its top.

The traversal replays drop the level's finish rectangle: it lies just above the exit ledge and
CLIMB_UI.complete() freezes physics on entry, so the landing could not be observed. test_02 replays the same
inputs with the finish kept and checks that the run completes at the finish (which starts at the zone's
right edge) with no recovery and no rope inside the zone.

BIG_ZONE_EVIDENCE_DIR=DIR writes traversal.json (compact). No default evidence directory.

    BIG_ZONE_EVIDENCE_DIR=artifacts/TASK-707 python3 -m unittest tools/test_big_zone_route.py -v
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

import check_level_geometry as geometry  # noqa: E402
from test_purple_route import TRAVERSE  # noqa: E402

EVIDENCE = os.environ.get('BIG_ZONE_EVIDENCE_DIR')
INPUTS = TOOLS / 'fixtures' / 'big-zone-inputs.json'
NAMES = ('big-zone.svg', 'big-zone-measurements.json', 'big-zone.level.json')
LAYOUT_ID = 'big-zone-fixture-v2'
RECOVERY_DEPTH = 1500  # physics.js CLIMB_FALL_RECOVERY_DEPTH
OUT = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tearDownModule():
    if EVIDENCE and OUT:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'traversal.json').write_text(json.dumps(OUT, separators=(',', ':')) + '\n')


class BigZoneTraversalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from browser_test_support import start_browser_test, wait_for_boot_run
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        tmp = Path(cls.stack.enter_context(tempfile.TemporaryDirectory()))
        subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--big-zone-fixture', '--output-dir', str(tmp)],
                       check=True, capture_output=True, cwd=TOOLS)
        cls.hashes = {n: sha(tmp / n) for n in NAMES}
        cls.svg = (tmp / NAMES[0]).read_bytes()
        cls.m = json.loads((tmp / NAMES[1]).read_text())
        cls.level = json.loads((tmp / NAMES[2]).read_text())
        cls.ids = {f['semanticId']: f['id'] for f in cls.m['fragments']}
        cls.big = cls.m['bigZone']
        cls.zone = next(z for z in cls.m['noGrappleZones'] if z['id'] == cls.big['zone'])
        cls.rec = json.loads(INPUTS.read_text())
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.page = cls.browser.new_page(viewport={'width': 1280, 'height': 720})
        cls.page.errors = []
        cls.page.on('pageerror', lambda e: cls.page.errors.append(str(e)))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.add_script_tag(path=str(TOOLS / 'opening_combination_replay.js'))

    def replay(self, finish=False):
        level = self.level if finish else dict(self.level, finish=None)
        return self.page.evaluate(TRAVERSE, dict(level=level, ids=self.ids, fixture=self.rec['fixture'], inputs=self.rec['inputs'],
                                                 budget=self.rec['budget'], exit='NGB-EXIT', trace=False))

    def test_01_rope_free_crossing_to_the_exit_ledge(self):
        rep = geometry.check(self.level, self.svg, self.m, geometry.MIN_SIDE_LENGTH, True)
        self.assertTrue(rep['summary']['pass'] and not rep['failureMessages'], rep['failureMessages'][:3])
        runs = [self.replay() for _ in range(2)]
        log = runs[0]
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(self.page.errors, [])
        self.assertEqual((log['layoutId'], log['acquisitionRadius']), (LAYOUT_ID, 540))
        # Only the fixture places the player (zero speed on the approach ledge); then real mouse events only.
        self.assertEqual((log['fixture']['vx'], log['fixture']['vy'], log['fixture']['drop']), (0, 0, 0))
        self.assertEqual(log['fixture']['panel'], self.big['approach'])
        self.assertTrue(all(e['type'] in ('down', 'up', 'move') for e in log['inputs']))
        self.assertLess(log['maxStep'], 200)
        self.assertEqual(log['recoveries'], [])
        self.assertFalse(log['start']['inside'])
        self.assertEqual([b['event'] for b in log['boundary']], ['enter', 'exit'])
        enter, leave = log['boundary']
        right = self.zone['x'] + self.zone['width']
        spawn_y = self.level['spawn']['y']
        # Out through the right side, above the recovery depth.
        self.assertGreater(leave['x'], right)
        self.assertLess(leave['y'], spawn_y + RECOVERY_DEPTH)
        body = lambda c: c['id'].split('-')[0]
        before = [c for c in log['contacts'] if c['tick'] < enter['tick']]
        within = [c for c in log['contacts'] if enter['tick'] <= c['tick'] < leave['tick']]
        after = [c for c in log['contacts'] if c['tick'] >= leave['tick']]
        self.assertEqual({body(c) for c in before}, {self.big['approach']})
        self.assertTrue(within)
        self.assertTrue({body(c) for c in within} <= set(self.big['internal']), within)
        seq = []
        for c in within:
            if not seq or seq[-1] != body(c):
                seq.append(body(c))
        # Rope-free inside: nothing attached or thrown while the circle overlaps the zone; presses there are blocked.
        self.assertEqual((log['insideAttached'], log['insideThrown']), (0, 0))
        self.assertFalse([g for g in log['grapple'] if g['event'] == 'attach' and enter['tick'] <= g['tick'] < leave['tick']])
        blocked = [p for p in log['presses'] if p['inside']]
        self.assertTrue(blocked)
        self.assertTrue(all(p['stale'] and not p['thrown'] for p in blocked))
        # A fresh press after the exit grapples the exit ledge, then the player lands on its top.
        fresh = [g for g in log['grapple'] if g['event'] == 'attach' and g['tick'] >= leave['tick']]
        self.assertTrue(fresh)
        self.assertEqual(body(fresh[0]), self.big['exit'])
        self.assertIsNotNone(log['landed'])
        self.assertEqual(body(log['landed']), self.big['exit'])
        self.assertLess(log['landed']['ny'], -.99)
        self.assertTrue({body(c) for c in after} <= {self.big['exit']}, after)
        keep = lambda b: {k: b[k] for k in ('tick', 'x', 'y', 'vx', 'vy')}
        OUT.update(
            method='Real index.html; tools/test_purple_route.py TRAVERSE on tools/opening_combination_replay.js (production '
                   'importedMountainLevel(), physics() once per tick, document mouse events at the recorded ticks of %s; '
                   'nothing written after the zero-speed fixture). Level finish removed for the replay (see test docstring).'
                   % INPUTS.relative_to(ROOT),
            layoutId=log['layoutId'], fixtureHashes=self.hashes, inputsSha256=sha(INPUTS), zone=self.zone['id'],
            zoneRight=right, recoveryLineY=spawn_y + RECOVERY_DEPTH, fixture=log['fixture'],
            inputs=[dict(tick=i['tick'], type=i['type']) for i in log['inputs']],
            enterTick=enter['tick'], enter=keep(enter), exitTick=leave['tick'], exit=keep(leave),
            exitThroughRightSide=leave['x'] > right, insideTicks=log['insideTicks'],
            insideAttachedTicks=log['insideAttached'], insideThrownTicks=log['insideThrown'],
            insideAttachEvents=0, pressesInside=blocked, internalSequence=seq,
            freshAttachOnExit=dict(tick=fresh[0]['tick'], id=fresh[0]['id'], point=fresh[0]['point']),
            landingTick=log['landed']['tick'], landed=log['landed'], recoveries=len(log['recoveries']),
            maxStepPerTick=log['maxStep'], ticks=log['ticks'], final=log['final'],
            secondRun=dict(identical=runs[0] == runs[1], enterTick=runs[1]['boundary'][0]['tick'],
                           exitTick=runs[1]['boundary'][1]['tick'], landingTick=runs[1]['landed']['tick'],
                           ticks=runs[1]['ticks'], final=runs[1]['final']))

    def test_02_finish_kept_completes_at_the_finish(self):
        log = self.replay(finish=True)
        state = self.page.evaluate('() => ({completed: floors[0].climbStats.completed === true, x: ninja.x, y: ninja.y})')
        self.assertTrue(state['completed'])
        self.assertEqual(log['recoveries'], [])
        # The finish starts at the zone's right edge, so completion can freeze the run before the circle has left it.
        self.assertIn([b['event'] for b in log['boundary']], (['enter'], ['enter', 'exit']))
        f = self.level['finish']
        self.assertTrue(f['left'] <= state['x'] <= f['right'] and f['top'] <= state['y'] <= f['bottom'], state)
        self.assertEqual((log['insideAttached'], log['insideThrown']), (0, 0))
        OUT['finishKept'] = dict(completed=True, at=[round(state['x'], 3), round(state['y'], 3)], finish=f,
                                 boundary=[dict(event=b['event'], tick=b['tick']) for b in log['boundary']])


if __name__ == '__main__':
    unittest.main()
