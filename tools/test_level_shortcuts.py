"""Finite production-input regression probes; these do not prove a full climb.

ROUTE_REPLAY_EVIDENCE=FILE writes the compact probe results (setup, first
source bounce, first later-panel contact) of every probe to FILE."""
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
ROUTE_MAP=json.loads((ROOT/'artifacts/levels/extended-mountain-measurements.json').read_text())['routeMap']

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
        r=self.page.evaluate('o=>ROUTE_PROBE.run(o)',options)
        keep={k:r[k] for k in ('source','target','fraction','aimOffset','drop','pumps','budget','setup','arrival','hit','bounces','ticks','dragTicks')}
        self.replays.append(dict(test=self.id().rsplit('.',1)[-1],control='level' in options,**keep))
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
        r=self.run_probe(source='P0',target='P1',fraction=.8,pumps=1,budget=1800)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],'P1-body0')

    def test_second_easy_opening_transfer(self):
        # The second 80% transfer (P1 -> P2) keeps its panels and position.
        self.assertEqual((panel('P1'),panel('P2')),('P1','P2'))
        r=self.run_probe(source='P1',target='P2',fraction=.8,pumps=1,budget=1800)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],'P2-body0')

    def test_fourth_platform_leftward_transfer(self):
        # A zero-speed drop creates the incoming velocity via gravity, rather
        # than injecting a launch velocity. This is a local entry-state test.
        # The v5 P3->P4 leftward encounter (S07-02) is now P3' -> L1.
        source=panel('P3');target=successor(source)
        self.assertEqual(target,ROUTE_MAP['addedFragments']['L1'])
        r=self.run_probe(source=source,target=target,fraction=.8,pumps=1,drop=300,aimOffset=-.8,budget=1800)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],target+'-body0')

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
