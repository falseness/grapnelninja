"""Ninja (ball) must not tunnel through bouncy surfaces (scenarios A-H).

Scenarios that still tunnel on HEAD are marked expectedFailure; tickets that
fix a scenario remove its marker.
"""
from pathlib import Path
import sys
import unittest

# Allow `python3 -m unittest tools/test_ninja_bounce.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from ninja_tunnel_scenarios import MODES, ROOT, run_scenario, format_trace


class NinjaBounceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def check(self, name):
        for mode in MODES:
            row = run_scenario(self.browser, self.url, name, mode)
            if row is None:
                continue
            print(f"\n{name}/{mode}: runs={row['runs']} tunnels={row['tunnels']}", flush=True)
            self.assertEqual(row['pageErrors'], [], f'{name}/{mode}')
            self.assertGreater(row['runs'], 0, f'{name}/{mode}')
            self.assertEqual(row['tunnels'], 0, f'{name}/{mode}\n' +
                             (format_trace(row) if row['firstTunnel'] else ''))

    @unittest.expectedFailure
    def test_a_fall_at_max_speed_onto_flat_trampoline(self):
        self.check('A')

    @unittest.expectedFailure
    def test_b_fast_horizontal_into_vertical_edge(self):
        self.check('B')

    @unittest.expectedFailure
    def test_c_landing_on_shared_seam(self):
        self.check('C')

    def test_d_resting_on_flat_trampoline(self):
        self.check('D')

    @unittest.expectedFailure
    def test_e_bad_ceiling_side_upward_hit(self):
        self.check('E')

    @unittest.expectedFailure
    def test_f_fast_hit_on_sloped_edge(self):
        self.check('F')

    @unittest.expectedFailure
    def test_g_hit_on_vertex(self):
        self.check('G')

    @unittest.expectedFailure
    def test_h_seeded_fuzz_at_factory_frames(self):
        self.check('H')


if __name__ == '__main__':
    unittest.main()
