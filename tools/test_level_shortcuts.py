"""Finite production-input regression probes; these do not prove a full climb."""
from contextlib import ExitStack
import json
from pathlib import Path
import unittest
from browser_test_support import start_browser_test, wait_for_boot_run
from import_level_svg import import_svg
import convert_extended_mountain_svg as svg
from retune_extended_level import tune, LAYOUT
ROOT=Path(__file__).resolve().parent.parent

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

    def run_probe(self,**options):
        return self.page.evaluate('o=>ROUTE_PROBE.run(o)',options)

    def test_fourth_obstacle_reproduced_and_fixed(self):
        options=dict(source='P3',target='P6',fraction=.5,pumps=3,budget=1800)
        before=self.run_probe(**options,level=self.control)
        after=self.run_probe(**options)
        self.assertIsNotNone(before['arrival'])
        self.assertEqual(before['hit']['id'],'P6-body0')
        self.assertIsNotNone(after['arrival'])
        self.assertIsNone(after['hit'])

    def test_first_platform_upward_launch_is_damped(self):
        options=dict(source='P0',target='P3',fraction=.5,pumps=5,budget=1800)
        before=self.run_probe(**options,guard=False)
        after=self.run_probe(**options)
        self.assertGreater(after['dragTicks'],0)
        self.assertGreater(after['minY'],before['minY']+300)
        self.assertTrue(after['hit'] is None or after['hit']['id']=='P1-body0')

    def test_high_arc_cannot_skip_fifth_platform(self):
        options=dict(source='P3',target='P4',fraction=.5,pumps=1,drop=300,aimOffset=-.8,budget=1800)
        before=self.run_probe(**options,guard=False)
        after=self.run_probe(**options)
        self.assertEqual(before['hit']['id'],'P5-body0')
        self.assertTrue(after['hit'] is None or after['hit']['id']=='P4-body0')
        self.assertGreater(after['dragTicks'],0)

    def test_high_energy_arrival_cannot_skip_fifth_platform(self):
        for fraction in (.2,.5,.8):
            r=self.run_probe(source='P3',target='P4',fraction=fraction,pumps=3,
                             drop=1000,aimOffset=-.3,budget=1800)
            self.assertTrue(r['hit'] is None or r['hit']['id']=='P4-body0',r)

    def test_opening_route_remains_accessible(self):
        r=self.run_probe(source='P0',target='P1',fraction=.8,pumps=1,budget=1800)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],'P1-body0')

    def test_fourth_platform_leftward_transfer(self):
        # A zero-speed drop creates the incoming velocity via gravity, rather
        # than injecting a launch velocity. This is a local entry-state test.
        r=self.run_probe(source='P3',target='P4',fraction=.8,pumps=1,drop=300,aimOffset=-.8,budget=1800)
        self.assertIsNotNone(r['arrival'])
        self.assertEqual(r['hit']['id'],'P4-body0')

if __name__=='__main__':unittest.main()
