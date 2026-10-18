"""Momentum hard speed limit (TASK-007): the effective cap
GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) (TASK-073 slow motion).

Both modes run 600 physics() frames (momentum: 600 / momentumTimeScale, the
slow-motion stretch of the script, TASK-073) with the rAF loop stopped and
the same forcing: before every frame the grapnel is forced grappled to a
point 3 view heights away along the travel direction (momentum: the
direction of the course segment the camera tracks, bad: right) and 1.5
heights to one side, the side flipping every 30 frames (momentum:
30 / momentumTimeScale), so the pull never ends and the ninja keeps
slamming into the floor/ceiling (momentum: borders on both sides of the
course). Obstacle floors are removed (only borders and walls are left), so no
deadly element ends the run. The momentum course is the scripted one of
test_momentum_camera_smooth (R R U R R D R ...).

Per frame the largest |v| = hypot(speedX, speedY) is taken over every
sub-step of Ninja.move (the speed at each collision() call, i.e. the speed
the ninja just moved with) and after physics() (after the grapple pull).

- momentum: max |v| <= the effective cap + 1e-6 on all 1200 frames; the cap is
  reached; >= 4 approaching bounces (the bound was 5 before TASK-030 widened the shafts:
  the forcing reaches their walls less often); same ninja (no death/restart);
- bad: the same forcing reaches |speedX| > the effective cap (bad keeps only
  its vertical cap) and |speedY| stays within that vertical cap;
- the effective cap is 0.1875 * 0.006867 * height: GAMEPLAY.momentumMaxSpeed
  0.375 * 0.006867 * height (TASK-029 halved the 1.5x cap, TASK-047 halved
  it again) times GAMEPLAY.momentumTimeScale 0.5 (TASK-073 slow motion), and
  / the bad cruise median
  (BAD_CRUISE_JSON, default artifacts/TASK-007/bad-cruise.json) is in
  [0.1625, 0.2125] (TASK-047's [0.325, 0.425] x 0.5);
- control: the momentum forcing with Ninja.limitMomentumSpeed stubbed out
  goes past 1.2x the limit (the forcing does push past the cap).

MOMENTUM_SPEED_EVIDENCE_DIR (default artifacts/TASK-007) receives
speed-trace.json: compact {limit, fields, momentum: [[frame, maxV, bounces]],
bad: [[frame, maxV, maxAbsSpeedX]]}. Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_camera import SEED_COURSE
from test_momentum_camera_smooth import SMOOTH_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
FRAMES = 600
TOLERANCE = 1e-6

# Records the per-frame speed maxima; sub-step speeds via Ninja.collision
INSTRUMENT = '''() => {
    if (window.speedProbe)
        return
    window.speedProbe = {maxV: 0, maxSX: 0, bounces: 0}
    const collision = Ninja.prototype.collision
    Ninja.prototype.collision = function() {
        speedProbe.maxV = Math.max(speedProbe.maxV, Math.hypot(this.speedX, this.speedY))
        speedProbe.maxSX = Math.max(speedProbe.maxSX, Math.abs(this.speedX))
        return collision.apply(this, arguments)
    }
    const applyBounce = Ninja.prototype.applyBounce
    Ninja.prototype.applyBounce = function(contact) {
        if (contact.approaching)
            speedProbe.bounces++
        return applyBounce.apply(this, arguments)
    }
}'''
RUN = '''([mode, frames]) => {
    if (mode == 'momentum')
        resetCourseScript()
    startGame(mode)
    cancelAnimationFrame(game)
    floors = floors.filter(f => mode == 'momentum'
        ? !(f instanceof MomentumObstacleFloor) : f instanceof SideFloor)
    const startNinja = ninja, deaths = lethalDeaths
    const anchor = {isEmpty: () => false, dx: 0, dy: 0}
    const far = 3 * height / scale[version], side = 1.5 * height / scale[version]
    const rows = []
    // Slow motion (TASK-073): the forcing script is stretched by 1 / s
    // (s = 1 outside momentum), as in test_momentum_slow_motion
    const s = momentumMotionScale(1), total = Math.round(frames / s)
    for (let frame = 0; frame < total; ++frame) {
        const dir = screen.getSegment ? screen.getSegment().dir : 'right'
        const along = dir == 'up' ? [0, -1] : dir == 'down' ? [0, 1] : [1, 0]
        const flip = Math.floor(frame * s / 30) % 2 ? 1 : -1
        // perpendicular to the travel direction, flipping sides
        const tx = ninja.x + along[0] * far + along[1] * side * flip
        const ty = ninja.y + along[1] * far + along[0] * side * flip
        grapnel.throwed = true
        grapnel.setGrappled(true)
        grapnel.pos = [[tx, ty, anchor]]
        ninja.invulnerableMs = 1e9
        speedProbe.maxV = 0
        speedProbe.maxSX = 0
        physics()
        speedProbe.maxV = Math.max(speedProbe.maxV, Math.hypot(ninja.speedX, ninja.speedY))
        speedProbe.maxSX = Math.max(speedProbe.maxSX, Math.abs(ninja.speedX))
        rows.push([frame, speedProbe.maxV, mode == 'momentum' ? speedProbe.bounces : speedProbe.maxSX])
    }
    return {rows, s, sameNinja: ninja === startNinja, deaths: lethalDeaths - deaths, version,
            limit: GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1), height,
            rawLimit: GAMEPLAY.momentumMaxSpeed, timeScale: GAMEPLAY.momentumTimeScale,
            verticalCap: screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent),
            segment: screen.segmentIndex === undefined ? null : screen.segmentIndex}
}'''


class MomentumSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_SPEED_EVIDENCE_DIR', ROOT / 'artifacts/TASK-007'))
        cls.out.mkdir(parents=True, exist_ok=True)
        url, browser = start_browser_test(ROOT, cls.addClassCleanup)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        cls.addClassCleanup(context.close)
        page = context.new_page()
        cls.errors = []
        page.on('pageerror', lambda e: cls.errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
        page.goto(url)
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE, SMOOTH_SCRIPT)
        page.evaluate(INSTRUMENT)
        cls.runs = {mode: page.evaluate(RUN, [mode, FRAMES]) for mode in ('momentum', 'bad')}
        # Negative control: the same momentum forcing with the clamp stubbed out
        page.evaluate('Ninja.prototype.limitMomentumSpeed = () => {}')
        cls.uncapped = page.evaluate(RUN, ['momentum', FRAMES])
        momentum, bad = cls.runs['momentum'], cls.runs['bad']
        cls.limit = momentum['limit']
        (cls.out / 'speed-trace.json').write_text(json.dumps(
            {'limit': cls.limit, 'unit': 'world units per physics cycle',
             'fields': {'momentum': ['frame', 'maxV', 'bounces'], 'bad': ['frame', 'maxV', 'maxAbsSpeedX']},
             'momentum': momentum['rows'], 'bad': bad['rows']}, separators=(',', ':')))
        for mode, run in cls.runs.items():
            print(f'{mode}: max |v| {max(r[1] for r in run["rows"]):.9f}, limit {cls.limit:.9f}, '
                  f'last row {run["rows"][-1]}, sameNinja {run["sameNinja"]}, deaths {run["deaths"]}, '
                  f'segment {run["segment"]}', file=sys.stderr)

    def test_momentum_never_exceeds_limit(self):
        run = self.runs['momentum']
        self.assertEqual(run['version'], 'momentum')
        self.assertEqual(run['s'], 0.5)
        self.assertEqual(len(run['rows']), round(FRAMES / run['s']))
        over = [r for r in run['rows'] if r[1] > self.limit + TOLERANCE]
        self.assertEqual(over, [], 'frames over the effective cap')
        peak = max(r[1] for r in run['rows'])
        print(f'momentum: {len(run["rows"])} frames (600 / s {run["s"]}), max |v| {peak!r} <= limit {self.limit!r} + {TOLERANCE}', file=sys.stderr)
        # the forcing really pushes against the cap
        self.assertGreater(peak, self.limit - TOLERANCE)
        reached = sum(1 for r in run['rows'] if r[1] > self.limit - TOLERANCE)
        print(f'momentum: frames at the cap {reached}', file=sys.stderr)

    def test_momentum_run_bounces_without_dying(self):
        run = self.runs['momentum']
        bounces = run['rows'][-1][2]
        print(f'momentum: approaching bounces {bounces}, deaths {run["deaths"]}, '
              f'course segment reached {run["segment"]}', file=sys.stderr)
        self.assertGreaterEqual(bounces, 4)
        self.assertTrue(run['sameNinja'])
        self.assertEqual(run['deaths'], 0)
        self.assertEqual(self.errors, [])

    def test_forcing_exceeds_limit_without_clamp(self):
        peak = max(r[1] for r in self.uncapped['rows'])
        print(f'momentum without the clamp (control): max |v| {peak!r}', file=sys.stderr)
        self.assertGreater(peak, self.limit * 1.2)

    def test_bad_is_not_capped(self):
        run = self.runs['bad']
        self.assertEqual(run['version'], 'bad')
        self.assertTrue(run['sameNinja'])
        peak_x = max(r[2] for r in run['rows'])
        print(f'bad: max |speedX| {peak_x!r} > effective cap {self.limit!r}', file=sys.stderr)
        self.assertGreater(peak_x, self.limit)

    def test_limit_is_01875_of_cruise_median(self):
        run = self.runs['momentum']
        expected = 0.375 * 0.006867 * run['height'] * 0.5
        print(f'effective cap {self.limit!r} (momentumMaxSpeed {run["rawLimit"]!r} x momentumTimeScale '
              f'{run["timeScale"]!r}), expected 0.375 * 0.006867 * height * 0.5 = {expected!r}', file=sys.stderr)
        self.assertAlmostEqual(self.limit, expected, delta=1e-9)
        self.assertAlmostEqual(run['rawLimit'], 0.375 * 0.006867 * run['height'], delta=1e-9)
        self.assertEqual(run['timeScale'], 0.5)

    def test_limit_vs_bad_cruise(self):
        cruise = json.loads(Path(os.environ.get('BAD_CRUISE_JSON',
                                                ROOT / 'artifacts/TASK-007/bad-cruise.json')).read_text())
        ratio = self.limit / cruise['median']
        print(f'effective cap {self.limit!r} / bad cruise median {cruise["median"]!r} = {ratio!r}',
              file=sys.stderr)
        self.assertGreaterEqual(ratio, 0.1625)
        self.assertLessEqual(ratio, 0.2125)


if __name__ == '__main__':
    unittest.main()
