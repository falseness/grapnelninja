"""Momentum camera x keeps a vertical shaft in view (TASK-023; TASK-070 exit preview exemption; TASK-085 exit arc exemption).

Course scripts right(5368) -> up and right(5368) -> down. With the rAF loop
stopped and the obstacle floor emptied, the ninja is driven (one
calcPhysics() per point, 8 world units apart) along the right corridor to the
shaft's x, then along the shaft to one half width before its end, at
x = shaft centre and x = centre + 0.8 halfWidth, at 1280x720 and 1024x768
(halfWidth: the shaft's own, momentumSegmentHalfWidth; since TASK-043 it can
be under the right corridors' GAMEPLAY.momentumBorders.halfWidth).

Per shaft cycle (screen.getSegment().dir is the shaft direction):
- shaftLeftFace + screen.x >= 0 (left wall face on screen) and
  screen.leftWall.x <= shaftLeftFace (the camera LeftWall is not inside the
  shaft), both only before the exit arc: while the view centre's rail
  position (screen.railS) is short of the start of the rail's quarter arc
  from the shaft into the right corridor after it. User decision of
  TASK-068..071 ("I would prefer it to change direction earlier ... i have to
  go there blindly"): on that arc the camera turns toward the right corridor,
  so its left wall may leave the view. TASK-085: the rail camera (TASK-084)
  centres the view on the rail, i.e. on the shaft's centre line; the
  TASK-070 exemption window (d <= GAMEPLAY.momentumCamera.preview.start, the
  exit preview getExitPreviewX) was removed with the preview, the exit arc
  replaces it;
- shaftRightFace + screen.x <= view width (right wall face on screen);
- no lethal death.

MOMENTUM_SHAFT_VIEW_EVIDENCE_DIR (default /tmp/momentum-shaft-view: a bare
run must not rewrite the TASK-023 evidence) receives
shaft-view.json: {case: {minLeftFaceOnScreen, maxRightFaceOnScreen,
leftWallInsideCycles, arcCycles}} (world units; arcCycles: shaft cycles
on the exit arc, exempt from the left checks). Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_camera import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
# Draws: segment 0 length, not right after right, up / down, segment 1 length
SCRIPTS = {'up': [0.99, 0.9, 0.1, 0.99, 0.5], 'down': [0.99, 0.9, 0.9, 0.99, 0.5]}
VIEWPORTS = [(1280, 720), (1024, 768)]
FRACTIONS = [0.0, 0.8]
SHAFT_DRIVE = '''([dir, xFrac]) => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const s0 = momentumCourse.segment(0), s1 = momentumCourse.segment(1)
    const hw = momentumSegmentHalfWidth(s1), hwNext = momentumSegmentHalfWidth(momentumCourse.segment(2))
    // Rail position where the exit arc (the shaft into segment 2) starts
    const rail = screen.rail, exitArc = rail.pieces[rail.pieceAt(rail.joinAt(1))]
    const shaftX = s1.x0 + xFrac * hw
    const leftFace = s1.x0 - hw, rightFace = s1.x0 + hw
    const viewWidth = width / scale[version]
    const v = 8, sy = s1.dir == 'up' ? -1 : 1
    const path = []
    for (let x = Math.max(ninja.x, s0.x0); x < shaftX; x += v) path.push([x, s0.y0, v, 0])
    for (let y = s0.y0; (s1.y1 - sy * hw - y) * sy > 0; y += sy * v) path.push([shaftX, y, 0, sy * v])
    const n0 = ninja, deaths0 = lethalDeaths
    let minLeft = Infinity, maxRight = -Infinity, inside = 0, cycles = 0, arcCycles = 0
    for (const [x, y, vx, vy] of path) {
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy - GRAVITY
        calcPhysics()
        if (ninja !== n0)
            break
        if (screen.getSegment().dir == s1.dir) {
            cycles++
            maxRight = Math.max(maxRight, rightFace + screen.x)
            if (screen.railS >= exitArc.s0) {
                arcCycles++
                continue
            }
            minLeft = Math.min(minLeft, leftFace + screen.x)
            if (screen.leftWall.x > leftFace)
                inside++
        }
    }
    return {dir: s1.dir, cycles, minLeftFaceOnScreen: minLeft, maxRightFaceOnScreen: maxRight,
            leftWallInsideCycles: inside, arcCycles, exitArc: {type: exitArc.type, s0: exitArc.s0}, viewWidth,
            deaths: lethalDeaths - deaths0, sameRun: ninja === n0}
}'''


class ShaftViewTests(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_SHAFT_VIEW_EVIDENCE_DIR', '/tmp/momentum-shaft-view'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'shaft-view.json').write_text(json.dumps(
            {k: {f: r[f] for f in ('minLeftFaceOnScreen', 'maxRightFaceOnScreen', 'leftWallInsideCycles', 'arcCycles')}
             for k, r in cls.results.items()}, separators=(',', ':')))

    def check_shaft(self, dir):
        for w, h in VIEWPORTS:
            context = self.browser.new_context(viewport={'width': w, 'height': h})
            self.addCleanup(context.close)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(self.url)
            wait_for_boot_run(page)
            page.evaluate(SEED_COURSE, SCRIPTS[dir])
            for frac in FRACTIONS:
                with self.subTest(viewport=f'{w}x{h}', x=frac):
                    r = page.evaluate(SHAFT_DRIVE, [dir, frac])
                    key = f'{dir}_{w}x{h}_x{frac}'
                    ShaftViewTests.results[key] = r
                    print(key, json.dumps(r, separators=(',', ':')), file=sys.stderr)
                    self.assertEqual(r['dir'], dir)
                    self.assertGreater(r['cycles'], 300)
                    self.assertEqual(r['exitArc']['type'], 'arc')
                    self.assertGreater(r['cycles'] - r['arcCycles'], 0)
                    self.assertGreater(r['arcCycles'], 0)
                    self.assertTrue(r['sameRun'])
                    self.assertEqual(r['deaths'], 0)
                    self.assertGreaterEqual(r['minLeftFaceOnScreen'], 0)
                    self.assertEqual(r['leftWallInsideCycles'], 0)
                    self.assertLessEqual(r['maxRightFaceOnScreen'], r['viewWidth'])
            self.assertEqual(errors, [])

    def test_right_up_shaft(self):
        self.check_shaft('up')

    def test_right_down_shaft(self):
        self.check_shaft('down')


if __name__ == '__main__':
    unittest.main(verbosity=2)
