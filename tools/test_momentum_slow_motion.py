"""Momentum slow motion: same trajectory shape at half the speed (TASK-072).

A momentum run (seeded Math.random, rAF loop cancelled, obstacle floor
emptied and frozen, ninja invulnerable, deaths only counted) gets two
Trampoline boxes from the test: a small anchor up and right of the ninja and
a long ground below it. The test then drives calcPhysics() itself:

  throw  - the grapnel is thrown at the anchor (as events.js throwGrapnel)
           with the ninja moving right at VX0;
  swing  - the rope pulls the ninja up past the anchor;
  release - the grapnel is picked up at RELEASE (events.js pickUpGrapnel);
  fall   - gravity only, until one bounce on the ground.

Positions are recorded before the first and after every calcPhysics. The baseline sets
window.MOMENTUM_TIME_SCALE_OVERRIDE = 1, so it runs at full speed; the normal
run uses GAMEPLAY.momentumTimeScale (1 while it does not exist). The time
scale s also stretches the script: VX0 * s, release at RELEASE / s cycles,
2 * BASELINE_CYCLES cycles recorded.

  test_baseline_reproducible - two baseline runs give identical positions,
      the grapnel hooks the anchor, one ground bounce inside the segment;
  test_shape - normal position at cycle 2n within 2% of the baseline path
      length of the baseline position at cycle n, for every baseline n;
  test_half_speed - median |v| normal / baseline in [0.45, 0.55].

Writes MOMENTUM_SLOW_MOTION_EVIDENCE_DIR (default artifacts/TASK-072)/
baseline-trajectory.json: compact {cycle, x, y} every 4th cycle, relative to
the ninja's start.

Requires Playwright Chromium. No remote requests.
"""
import json
import math
import os
from pathlib import Path
import statistics
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_SLOW_MOTION_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-072'))
SEED = 7
# Script in ninja radii and baseline cycles
ANCHOR = (15, -25)
GROUND_Y = 6
VX0 = 1.2
RELEASE = 300
BASELINE_CYCLES = 2100
SHAPE_TOLERANCE = 0.02
SPEED_RATIO = (0.45, 0.55)

RUN = '''({seed, baseline, anchor, groundY, vx0, release, baselineCycles}) => {
    let a = seed >>> 0
    Math.random = () => {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    if (baseline)
        window.MOMENTUM_TIME_SCALE_OVERRIDE = 1
    else
        delete window.MOMENTUM_TIME_SCALE_OVERRIDE
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    let lethal = 0
    onLethalDeath = function() { ++lethal }
    const s = baseline ? 1 : (typeof GAMEPLAY.momentumTimeScale == 'number' ? GAMEPLAY.momentumTimeScale : 1)
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    floor.replenishElements = () => {}
    floor.deleteElements = () => {}
    const r = ninja.radius, x0 = ninja.x, y0 = ninja.y
    const ax = x0 + anchor[0] * r, ay = y0 + anchor[1] * r
    const anchorBox = new Trampoline(MomentumOneTime.boxObject(ax - 2 * r, ay - 2 * r, 4 * r, 4 * r))
    const ground = new Trampoline(MomentumOneTime.boxObject(x0 - 20 * r, y0 + groundY * r, 400 * r, 10 * r))
    floor.elements = [anchorBox, ground]
    ninja.invulnerableMs = 1e9
    ninja.speedX = vx0 * s
    ninja.speedY = 0
    // events.js throwGrapnel
    grapnel.pos = [[ninja.x, ninja.y, new Empty()]]
    const dir = grapnel.calcSpeed({x: ax, y: ay})
    grapnel.speedX = dir.cos * grapnelSpeed
    grapnel.speedY = dir.sin * grapnelSpeed
    grapnel.throwed = true
    grapnel.setGrappled(false)
    let cycle = 0
    const bounces = []
    const applyBounce = ninja.applyBounce
    ninja.applyBounce = function(contact) {
        if (contact.approaching)
            bounces.push([cycle, contact.element === ground ? 'ground' : contact.element === anchorBox ? 'anchor' : contact.element.constructor.name])
        return applyBounce.apply(this, arguments)
    }
    const releaseCycle = Math.round(release / s)
    const cycles = baseline ? baselineCycles : 2 * baselineCycles
    let hookCycle = null, hookedAnchor = false
    // xs[c], ys[c]: position after c cycles
    const xs = [0], ys = [0]
    for (cycle = 0; cycle < cycles; ++cycle) {
        // events.js pickUpGrapnel
        if (cycle == releaseCycle) {
            grapnel.setGrappled(false)
            grapnel.throwed = false
        }
        calcPhysics()
        if (hookCycle === null && grapnel.isGrappled()) {
            hookCycle = cycle
            hookedAnchor = grapnel.pos[0][2] === anchorBox
        }
        xs.push(ninja.x - x0)
        ys.push(ninja.y - y0)
    }
    return {s, xs, ys, hookCycle, hookedAnchor, releaseCycle, bounces, lethal, version}
}'''


class MomentumSlowMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.baseline = cls.run_script(True)
        cls.baseline2 = cls.run_script(True)
        cls.normal = cls.run_script(False)
        b = cls.baseline
        (EVIDENCE_DIR / 'baseline-trajectory.json').write_text(json.dumps(
            [{'cycle': i, 'x': round(b['xs'][i], 3), 'y': round(b['ys'][i], 3)}
             for i in range(0, len(b['xs']), 4)], separators=(',', ':')) + '\n')
        print('baseline: hook cycle', b['hookCycle'], 'release cycle', b['releaseCycle'],
              'bounces', b['bounces'], 'segment', len(b['xs']), 'cycles')
        print('normal: s', cls.normal['s'], 'hook cycle', cls.normal['hookCycle'],
              'release cycle', cls.normal['releaseCycle'], 'bounces', cls.normal['bounces'])

    @classmethod
    def run_script(cls, baseline):
        context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
        try:
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(cls.url)
            wait_for_boot_run(page)
            result = page.evaluate(RUN, {'seed': SEED, 'baseline': baseline, 'anchor': list(ANCHOR),
                                         'groundY': GROUND_Y, 'vx0': VX0, 'release': RELEASE,
                                         'baselineCycles': BASELINE_CYCLES})
            result['errors'] = errors
            return result
        finally:
            context.close()

    @staticmethod
    def speeds(run):
        xs, ys = run['xs'], run['ys']
        return [math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]) for i in range(1, len(xs))]

    def test_baseline_reproducible(self):
        b, b2 = self.baseline, self.baseline2
        for run in (b, b2, self.normal):
            self.assertEqual(run['errors'], [])
            self.assertEqual(run['version'], 'momentum')
            self.assertEqual(run['lethal'], 0)
        self.assertEqual(b['s'], 1)
        self.assertTrue(b['hookedAnchor'], 'the grapnel did not hook the anchor')
        self.assertLess(b['hookCycle'], b['releaseCycle'])
        self.assertEqual([k for _, k in b['bounces']], ['ground'], 'want one ground bounce in the segment')
        self.assertGreater(b['bounces'][0][0], b['releaseCycle'])
        print('baseline bounce cycle', b['bounces'][0][0])
        self.assertEqual(b['xs'], b2['xs'])
        self.assertEqual(b['ys'], b2['ys'])

    @unittest.expectedFailure  # fails until TASK-073 applies GAMEPLAY.momentumTimeScale
    def test_shape(self):
        b, n = self.baseline, self.normal
        path = sum(self.speeds(b))
        error = max(math.hypot(n['xs'][2 * i] - b['xs'][i], n['ys'][2 * i] - b['ys'][i])
                    for i in range(len(b['xs'])))
        print(f'max shape error {error / path:.4f} of the baseline path {path:.1f}')
        self.assertLessEqual(error / path, SHAPE_TOLERANCE)

    @unittest.expectedFailure  # fails until TASK-073 applies GAMEPLAY.momentumTimeScale
    def test_half_speed(self):
        ratio = statistics.median(self.speeds(self.normal)) / statistics.median(self.speeds(self.baseline))
        print(f'median speed ratio normal/baseline {ratio:.4f}')
        self.assertGreaterEqual(ratio, SPEED_RATIO[0])
        self.assertLessEqual(ratio, SPEED_RATIO[1])


if __name__ == '__main__':
    unittest.main()
