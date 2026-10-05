"""Ninja (ball) must not tunnel through bouncy surfaces (scenarios A-H).

Every scenario A-H must pass (the sub-stepping of TASK-157 cleared the last
known-failure markers, B and H).
"""
from pathlib import Path
import math
import sys
import unittest

# Allow `python3 -m unittest tools/test_ninja_bounce.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from ninja_tunnel_scenarios import MODES, ROOT, open_page, run_scenario, format_trace


# The trampoline bounce before TASK-156 (Trampoline.collision), applied to
# {speedX, speedY}; bounceSpeed() must reproduce it.
OLD_FORMULA = r'''(v, line) => {
    if (line.type == 'vertical')
        return {speedX: -v.speedX, speedY: v.speedY};
    let lineAngle = Math.atan(line.k);
    let xn = -v.speedX, yn = -v.speedY;
    let x = xn * Math.cos(lineAngle) + yn * Math.sin(lineAngle);
    let y = yn * Math.cos(lineAngle) - xn * Math.sin(lineAngle);
    x = -x;
    xn = x * Math.cos(lineAngle) - y * Math.sin(lineAngle);
    yn = y * Math.cos(lineAngle) + x * Math.sin(lineAngle);
    return {speedX: xn + GRAVITY * Math.cos(lineAngle) * Math.sin(lineAngle),
            speedY: yn - GRAVITY * Math.pow(Math.cos(lineAngle), 2)};
}'''

# 20 seeded incoming velocities per edge kind: old formula vs bounceSpeed().
REFLECTION_CHECK = r'''(seed) => {
    const old = OLD_FORMULA;
    let s = seed;
    const rnd = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
    const edges = {flat: lineFormula(0, 100, 200, 100),
                   vertical: lineFormula(50, 0, 50, 200),
                   sloped: lineFormula(0, 200, 200, 80)};
    const out = {seed, edges: {}, maxAbsDiff: 0};
    for (const [kind, line] of Object.entries(edges)) {
        const rows = [];
        for (let i = 0; i < 20; ++i) {
            const v = {speedX: (rnd() - 0.5) * 60, speedY: (rnd() - 0.5) * 60};
            const a = old(v, line);
            const b = {speedX: v.speedX, speedY: v.speedY};
            bounceSpeed(b, line);
            const diff = Math.max(Math.abs(a.speedX - b.speedX), Math.abs(a.speedY - b.speedY));
            out.maxAbsDiff = Math.max(out.maxAbsDiff, diff);
            rows.push({incoming: v, old: a, helper: {speedX: b.speedX, speedY: b.speedY},
                       absDiff: diff});
        }
        out.edges[kind] = rows;
    }
    return out;
}'''.replace('OLD_FORMULA', OLD_FORMULA)

# One Ninja.collision() against a flat Trampoline top, the centre `depth`
# closer than r to it.
FLAT_BOUNCE = r'''([depth, vy]) => {
    const old = OLD_FORMULA;
    const T = tunnel, r = T.r, top = 0.6 * height;
    T.clear();
    floors[1].elements = [T.box(0.4 * width, top, 0.2 * width, 0.15 * height)];
    T.place(0.5 * width, top - r + depth, 1.5, vy);
    const line = floors[1].elements[0].getLines()[1];
    const expected = old({speedX: ninja.speedX, speedY: ninja.speedY}, line);
    ninja.collision();
    return {speedX: ninja.speedX, speedY: ninja.speedY, expected, r,
            distance: Math.sqrt(segmentDistanceSquared(line, ninja.x, ninja.y)),
            deaths: T.deaths};
}'''.replace('OLD_FORMULA', OLD_FORMULA)


# Collision calls made by one Ninja.move() with velocity (vx, vy), no elements.
MOVE_STEPS = r'''([vx, vy]) => {
    tunnel.clear();
    tunnel.place(0.5 * width, 0.5 * height, vx, vy);
    let calls = 0;
    const orig = ninja.collision;
    ninja.collision = function() { calls++; return orig.call(this); };
    ninja.move();
    delete ninja.collision;
    return {calls, r: ninja.radius, x: ninja.x, y: ninja.y, x0: 0.5 * width, y0: 0.5 * height};
}'''


def reflection_check(page, seed=156):
    return page.evaluate(REFLECTION_CHECK, seed)


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

    def flat_bounce(self, mode, depth, vy):
        page, errors = open_page(self.browser, self.url, mode)
        try:
            out = page.evaluate(FLAT_BOUNCE, [depth, vy])
        finally:
            page.close()
        self.assertEqual(errors, [], mode)
        self.assertEqual(out['deaths'], 0, mode)
        return out

    def test_reflection_helper_matches_old_formula(self):
        page, errors = open_page(self.browser, self.url, 'classic')
        try:
            out = reflection_check(page)
        finally:
            page.close()
        self.assertEqual(errors, [])
        self.assertEqual([len(rows) for rows in out['edges'].values()], [20, 20, 20])
        self.assertLessEqual(out['maxAbsDiff'], 1e-9)

    def test_flat_bounce_speed_matches_old_formula(self):
        for mode in MODES:
            out = self.flat_bounce(mode, 3.0, 9.0)
            self.assertLess(out['speedY'], 0, mode)
            self.assertAlmostEqual(out['speedX'], out['expected']['speedX'], delta=1e-9, msg=mode)
            self.assertAlmostEqual(out['speedY'], out['expected']['speedY'], delta=1e-9, msg=mode)

    def test_ball_pushed_out_to_radius_after_bounce(self):
        for mode in MODES:
            for depth in [0.5, 3.0, 6.0, 9.0]:
                out = self.flat_bounce(mode, depth, 9.0)
                self.assertLess(out['speedY'], 0, f'{mode} depth={depth}')
                self.assertGreaterEqual(out['distance'], out['r'], f'{mode} depth={depth}')

    def test_ball_moving_away_is_not_reflected(self):
        for mode in MODES:
            out = self.flat_bounce(mode, 2.0, -4.0)
            self.assertEqual((out['speedX'], out['speedY']), (1.5, -4.0), mode)
            self.assertGreaterEqual(out['distance'], out['r'], mode)

    def move_steps(self, mode, vx, vy):
        page, errors = open_page(self.browser, self.url, mode)
        try:
            out = page.evaluate(MOVE_STEPS, [vx, vy])
        finally:
            page.close()
        self.assertEqual(errors, [], mode)
        return out

    def test_slow_cycle_collides_once_fast_cycle_n_times(self):
        for mode in MODES:
            r = self.move_steps(mode, 0, 0)['r']
            for vx, vy in [(0, 0), (0.5 * r, 0.5 * r), (0, r), (0, 1.01 * r),
                           (3.4 * r, 0), (-2 * r, 1.5 * r), (12.2 * r, -0.9 * r)]:
                out = self.move_steps(mode, vx, vy)
                n = max(1, math.ceil(math.hypot(vx, vy) / r))
                self.assertEqual(out['calls'], n, f'{mode} v=({vx}, {vy})')
                self.assertAlmostEqual(out['x'] - out['x0'], vx, delta=1e-9, msg=mode)
                self.assertAlmostEqual(out['y'] - out['y0'], vy, delta=1e-9, msg=mode)

    def test_a_fall_at_max_speed_onto_flat_trampoline(self):
        self.check('A')

    def test_b_fast_horizontal_into_vertical_edge(self):
        self.check('B')

    def test_c_landing_on_shared_seam(self):
        self.check('C')

    def test_d_resting_on_flat_trampoline(self):
        self.check('D')

    def test_e_bad_ceiling_side_upward_hit(self):
        self.check('E')

    def test_f_fast_hit_on_sloped_edge(self):
        self.check('F')

    def test_g_hit_on_vertex(self):
        self.check('G')

    def test_h_seeded_fuzz_at_factory_frames(self):
        self.check('H')


if __name__ == '__main__':
    unittest.main()
