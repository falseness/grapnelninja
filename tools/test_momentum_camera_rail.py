"""Momentum camera rail geometry (TASK-083, elements/momentumcamerarail.js).

The rail is the course centre line with every turn join replaced by a
quarter circle of radius GAMEPLAY.momentumCamera.railRadius view heights (at
most half of either adjacent segment). It is not used by the camera yet
(TASK-084). Course scripts right -> up -> right and right -> down -> right
(test_momentum_shaft_view) give the joins right->up, up->right, right->down
and down->right. Per join:
1. C1 continuity: at both straight/arc boundaries of its arc the position
   gap is < 1e-6 and the tangent angle jump < 1e-6 rad;
2. arc length: the arc is pi/2 * r long and the rail position of its end is
   the analytic one (the centre-line length up to the join plus r, minus
   (2 - pi/2) * r per earlier turn), both within 1e-6;
3. project() of points on the rail around the join returns their s within
   1e-6 (hint a view height back);
4. the ninja's centre-line drive through the join (one point per physics
   cycle at the effective speed cap) projects monotonically, each point with
   the previous result as hint;
5. the arc lies inside both corridors (momentumSegmentHalfWidth) and its
   middle sits on the corner diagonal.
Also C1 continuity and length over the first 12 joins of both courses
(straight joins included, they stay lines), and the rail is not used by the
camera (MomentumScreen has no rail). MOMENTUM_CAMERA_RAIL_EVIDENCE_DIR
(default artifacts/TASK-083) receives rail-check.json (compact, per join
{maxPosGap, maxTangentJump, arcLengthError, projectError, ...}).
Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_camera import SEED_COURSE
from test_momentum_shaft_view import SCRIPTS

ROOT = Path(__file__).resolve().parents[1]
# join: (course script, index of the segment before the join)
JOINS = {'right-up': ('up', 0), 'right-down': ('down', 0), 'up-right': ('up', 1), 'down-right': ('down', 1)}
EPS = 1e-6
ALL_JOINS = 12

CHECK = '''([index, joins]) => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    const course = momentumCourse
    const rail = new MomentumCameraRail(course)
    const view = height / scale[version]
    rail.extend(joins)
    const P = rail.pieces
    const end = p => MomentumCameraRail.sample(p, p.length)
    const start = p => MomentumCameraRail.sample(p, 0)
    const angle = (a, b) => Math.abs(Math.atan2(a.tx * b.ty - a.ty * b.tx, a.tx * b.tx + a.ty * b.ty))
    // Every boundary: [s, position gap, tangent jump, s gap]
    const bounds = []
    for (let i = 0; i + 1 < P.length; ++i) {
        const e = end(P[i]), b = start(P[i + 1])
        bounds.push([P[i + 1].s0, Math.hypot(e.x - b.x, e.y - b.y), angle(e, b),
                     Math.abs(P[i].s0 + P[i].length - P[i + 1].s0)])
    }
    // Analytic rail length up to the end of join k's arc (or the join)
    const segs = course.take(joins + 2)
    const radius = GAMEPLAY.momentumCamera.railRadius * view
    let centre = 0, cut = 0, analytic = []
    for (let k = 0; k <= joins; ++k) {
        centre += segs[k].length
        const turn = segs[k].dir != segs[k + 1].dir
        const r = turn ? Math.min(radius, segs[k].length / 2, segs[k + 1].length / 2) : 0
        cut += (2 - Math.PI / 2) * r
        analytic.push([turn, r, centre + r - cut])
    }
    const arcs = P.filter(p => p.type == 'arc')
    const turnsBefore = analytic.slice(0, index).filter(a => a[0]).length
    const arc = arcs[turnsBefore]
    const arcEnd = arc.s0 + arc.length
    const a = segs[index], b = segs[index + 1]
    const near = bounds.filter(x => Math.abs(x[0] - arc.s0) < 1e-6 || Math.abs(x[0] - arcEnd) < 1e-6)
    // project() of rail points from a view before to a view after the arc
    let projectError = 0, samples = 0
    for (let s = arc.s0 - view; s <= arcEnd + view; s += view / 97) {
        const p = rail.pointAt(s)
        projectError = Math.max(projectError, Math.abs(rail.project(p.x, p.y, s - view) - s))
        ++samples
    }
    // The ninja centre-line drive through the join
    const v = GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1)
    const pts = [[ninja.x, segs[0].y0]]
    for (let k = 0; k <= index; ++k)
        pts.push([segs[k].x1, segs[k].y1])
    pts.push([b.x1, b.y1])
    let hint = 0, prev = -Infinity, backwards = 0, drive = 0, maxOff = 0
    for (let k = 0; k + 1 < pts.length; ++k) {
        const [x0, y0] = pts[k], [x1, y1] = pts[k + 1]
        const len = Math.hypot(x1 - x0, y1 - y0)
        for (let d = 0; d < len; d += v) {
            const x = x0 + (x1 - x0) * d / len, y = y0 + (y1 - y0) * d / len
            const s = rail.project(x, y, hint)
            if (s < prev - 1e-9)
                ++backwards
            const q = rail.pointAt(s)
            maxOff = Math.max(maxOff, Math.hypot(q.x - x, q.y - y))
            prev = hint = s
            ++drive
        }
    }
    // The arc inside both corridors: margin to the nearer corridor's wall
    const box = (seg) => {
        const hw = momentumSegmentHalfWidth(seg)
        return seg.dir == 'right'
            ? [Math.min(seg.x0, seg.x1), seg.y0 - hw, Math.max(seg.x0, seg.x1), seg.y0 + hw]
            : [seg.x0 - hw, Math.min(seg.y0, seg.y1), seg.x0 + hw, Math.max(seg.y0, seg.y1)]
    }
    const inner = (r, p) => Math.min(p.x - r[0], r[2] - p.x, p.y - r[1], r[3] - p.y)
    let minMargin = Infinity
    for (let i = 0; i <= 90; ++i) {
        const p = MomentumCameraRail.sample(arc, arc.length * i / 90)
        minMargin = Math.min(minMargin, Math.max(inner(box(a), p), inner(box(b), p)))
    }
    const mid = MomentumCameraRail.sample(arc, arc.length / 2)
    const jx = a.x1, jy = a.y1
    return {
        dirs: [a.dir, b.dir], view, railRadius: radius, r: arc.r,
        maxPosGap: Math.max(...near.map(x => x[1])), maxTangentJump: Math.max(...near.map(x => x[2])),
        boundaries: near.length,
        arcLengthError: Math.max(Math.abs(arc.length - Math.PI / 2 * arc.r),
                                 Math.abs(arcEnd - analytic[index][2])),
        projectError, projectSamples: samples,
        driveSamples: drive, driveBackwards: backwards, driveMaxOffset: maxOff,
        arcMinCorridorMargin: minMargin,
        midOffset: [Math.abs(Math.abs(mid.x - jx) - Math.abs(mid.y - jy)), Math.hypot(mid.x - jx, mid.y - jy)],
        all: {joins: analytic.length, turns: analytic.filter(x => x[0]).length,
              maxPosGap: Math.max(...bounds.map(x => x[1])), maxTangentJump: Math.max(...bounds.map(x => x[2])),
              maxSGap: Math.max(...bounds.map(x => x[3])),
              lengthError: Math.abs(rail.length - analytic[joins][2])},
        cameraHasRail: Object.values(screen).some(x => x instanceof MomentumCameraRail)
    }
}'''


class MomentumCameraRailTests(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_CAMERA_RAIL_EVIDENCE_DIR', ROOT / 'artifacts/TASK-083'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'rail-check.json').write_text(json.dumps(cls.results, separators=(',', ':')) + '\n')

    def check(self, join):
        script, index = JOINS[join]
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE, SCRIPTS[script])
        r = page.evaluate(CHECK, [index, ALL_JOINS - 1])
        self.results[join] = r
        self.assertEqual(errors, [])
        self.assertEqual('-'.join(r['dirs']), join)
        self.assertAlmostEqual(r['railRadius'], 0.5 * r['view'], places=6)
        self.assertAlmostEqual(r['r'], r['railRadius'], places=6, msg='arc radius clamped by a short segment')
        self.assertEqual(r['boundaries'], 2)
        self.assertLess(r['maxPosGap'], EPS)
        self.assertLess(r['maxTangentJump'], EPS)
        self.assertLess(r['arcLengthError'], EPS)
        self.assertLess(r['projectError'], EPS)
        self.assertGreater(r['driveSamples'], 100)
        self.assertEqual(r['driveBackwards'], 0)
        # The centre line is at most (sqrt 2 - 1) r off the rail (the join)
        self.assertLess(r['driveMaxOffset'], (2 ** 0.5 - 1) * r['r'] + EPS)
        self.assertGreater(r['arcMinCorridorMargin'], 0)
        self.assertLess(r['midOffset'][0], EPS)
        self.assertAlmostEqual(r['midOffset'][1], (2 ** 0.5 - 1) * r['r'], places=6)
        self.assertEqual(r['all']['joins'], ALL_JOINS)
        self.assertLess(r['all']['maxPosGap'], EPS)
        self.assertLess(r['all']['maxTangentJump'], EPS)
        self.assertLess(r['all']['maxSGap'], EPS)
        self.assertLess(r['all']['lengthError'], EPS)
        self.assertFalse(r['cameraHasRail'])

    def test_a_right_up(self):
        self.check('right-up')

    def test_b_right_down(self):
        self.check('right-down')

    def test_c_up_right(self):
        self.check('up-right')

    def test_d_down_right(self):
        self.check('down-right')


if __name__ == '__main__':
    unittest.main(verbosity=2)
