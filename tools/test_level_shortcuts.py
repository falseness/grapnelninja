"""Finite production-input regression probes; these do not prove a full climb.

ROUTE_REPLAY_EVIDENCE=FILE writes the compact probe results (setup, first
source bounce, first later-panel contact) of every probe to FILE.
LEVEL_SHORTCUTS_LEVEL_DIR=DIR (TASK-680) probes that directory's level and route
map instead of the shipped artifacts/levels (the control is unchanged)."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest
from browser_test_support import start_browser_test, wait_for_boot_run
from import_level_svg import import_svg
import convert_extended_mountain_svg as svg
from retune_extended_level import tune, LAYOUT
ROOT=Path(__file__).resolve().parent.parent
LEVELS=Path(os.environ.get('LEVEL_SHORTCUTS_LEVEL_DIR',ROOT/'artifacts/levels'))
ROUTE_MAP=json.loads((LEVELS/'extended-mountain-measurements.json').read_text())['routeMap']
LEVEL=json.loads((LEVELS/'extended-mountain.level.json').read_text()) if os.environ.get('LEVEL_SHORTCUTS_LEVEL_DIR') else None

def panel(original):
    """Shipped panel id for a pre-extension (v5) panel id."""
    return ROUTE_MAP['fragmentIds'][original]

def successor(panel_id):
    """The intended next panel in the shipped connected route."""
    return f'P{int(panel_id[1:])+1}'

class ShortcutReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack=ExitStack();cls.addClassCleanup(cls.stack.close)
        cls.url,cls.browser=start_browser_test(ROOT,cls.stack.callback)
        source=json.loads((ROOT/'artifacts/level/extended-mountain-measurements.json').read_text())
        old=svg.LAYOUT_ID
        try:
            svg.LAYOUT_ID=LAYOUT
            cls.control=import_svg(svg.build(tune(source,reposition=False,guards=False)).encode())
        finally:svg.LAYOUT_ID=old
        cls.page=cls.browser.new_page(viewport={'width':1280,'height':720})
        cls.page.goto(cls.url);wait_for_boot_run(cls.page)
        cls.page.add_script_tag(path=str(ROOT/'tools/probe_level_routes.js'))

    @classmethod
    def tearDownClass(cls):
        out=os.environ.get('ROUTE_REPLAY_EVIDENCE')
        if out:Path(out).write_text(json.dumps(cls.replays,separators=(',',':'))+'\n')

    replays=[]

    def run_probe(self,**options):
        control='level' in options
        if LEVEL and not control:options=dict(options,level=LEVEL)
        r=self.page.evaluate('o=>ROUTE_PROBE.run(o)',options)
        keep={k:r[k] for k in ('source','target','fraction','aimOffset','drop','pumps','budget','setup','arrival','hit','bounces','ticks','dragTicks')}
        keep['targetWhenInRange']=bool(options.get('targetWhenInRange'))
        self.replays.append(dict(test=self.id().rsplit('.',1)[-1],control=control,**keep))
        return r

    def test_fourth_obstacle_reproduced_and_fixed(self):
        options=dict(source='P3',target='P6',fraction=.5,pumps=3,budget=1800)
        before=self.run_probe(**options,level=self.control)
        after=self.run_probe(**dict(options,source=panel('P3'),target=panel('P6')))
        self.assertIsNotNone(before['arrival'])
        self.assertEqual(before['hit']['id'],'P6-body0')
        self.assertIsNotNone(after['arrival'])
        # v6 inserts L1 between P3' and P4', so the aimed release may now land on
        # the intended successor; reaching anything later is still a skip.
        self.assertTrue(after['hit'] is None or after['hit']['id']==successor(panel('P3'))+'-body0',after['hit'])

    def test_first_platform_cannot_skip_opening(self):
        for target in [panel(p) for p in ('P3','P4','P5','P6')]:
            after=self.run_probe(source='P0',target=target,fraction=.5,pumps=5,budget=1800)
            self.assertTrue(after['hit'] is None or after['hit']['id']=='P1-body0',after['hit'])

    def test_high_arc_cannot_skip_fifth_platform(self):
        source=panel('P3');target=successor(source)
        options=dict(source=source,target=target,fraction=.5,pumps=1,drop=300,aimOffset=-.8,budget=1800)
        after=self.run_probe(**options)
        self.assertTrue(after['hit'] is None or after['hit']['id']==target+'-body0')

    def test_high_energy_arrival_cannot_skip_fifth_platform(self):
        for fraction in (.2,.5,.8):
            source=panel('P3');target=successor(source)
            r=self.run_probe(source=source,target=target,fraction=fraction,pumps=3,
                             drop=1000,aimOffset=-.3,budget=1800)
            self.assertTrue(r['hit'] is None or r['hit']['id']==target+'-body0',r)

    def test_opening_route_remains_accessible(self):
        # Since 49cf58e the opening transfers are wider than the 540 grapple range, so they need a
        # release jump: the probe pumps, releases and only throws at the target once it is in range.
        r=self.run_probe(source='P0',target='P1',fraction=.5,pumps=2,aimOffset=.3,targetWhenInRange=True,budget=1800)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],'P1-body0')

    def test_second_easy_opening_transfer(self):
        # The second 80% transfer (P1 -> P2) keeps its panels and position.
        self.assertEqual((panel('P1'),panel('P2')),('P1','P2'))
        # TASK-680: two pumps from 0.2 of P1 reach P2 on both v15 and the minimum-side
        # candidate (its rebuilt P2 slab moves the nearest in-range point; four pumps from 0.5 miss it).
        r=self.run_probe(source='P1',target='P2',fraction=.2,pumps=2,aimOffset=0,targetWhenInRange=True,budget=1800)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],'P2-body0')

    def test_fourth_platform_leftward_transfer(self):
        # A zero-speed drop creates the incoming velocity via gravity, rather
        # than injecting a launch velocity. This is a local entry-state test.
        # The v5 P3->P4 leftward encounter (S07-02) is now P3' -> L1.
        source=panel('P3');target=successor(source)
        self.assertEqual(target,ROUTE_MAP['addedFragments']['L1'])
        r=self.run_probe(source=source,target=target,fraction=.2,pumps=1,drop=300,lastAimOffset=-.15,budget=2400)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],target+'-body0')

    def test_leftward_diagonal_return(self):
        # v15's two rising leftward jumps return diagonally down-left to the
        # unchanged P4 endpoint. Use gravity and real grapple input to launch.
        source = ROUTE_MAP['addedFragments']['L2']
        target = panel('P4')
        self.assertEqual(successor(source), target)
        # TASK-686: from L2's middle (the three-zone candidate narrows L2 from its left
        # end, so a release from .2 now falls short; .5 / aim -.6 lands on both layouts).
        r = self.run_probe(source=source, target=target, fraction=.5,
                           pumps=1, drop=300, aimOffset=-.6,
                           targetWhenInRange=True, budget=2400)
        self.assertIsNotNone(r['arrival'])
        self.assertIsNotNone(r['hit'])
        self.assertEqual(r['hit']['id'], target + '-body0')

    def test_added_opening_transfers(self):
        # One added rightward and one added leftward (L1->L2) transfer, each from a
        # zero-speed drop onto the source panel's top. Since TASK-669, R1 is a ceiling
        # (caught from below) and R2 a slope; the top-to-top rightward transfer is
        # R3->R4. The ceiling/slope transfers are replayed continuously in
        # test_opening_jump_variety.CombinationReplayTests. R3 is 1400 wide since v9,
        # so its pump aims 0.3 of its width ahead of the drop (0.8 would pin it to the far end).
        added=ROUTE_MAP['addedFragments']
        for name,aim in (('R3',.3),('L1',-.8)):
            source=added[name];target=successor(source)
            with self.subTest(source=source,target=target):
                r=self.run_probe(source=source,target=target,fraction=.5,pumps=1,drop=300,aimOffset=aim,budget=1800)
                self.assertIsNotNone(r['arrival'])
                self.assertEqual(r['hit']['id'],target+'-body0')

if __name__=='__main__':unittest.main()
