"""Momentum horizontal (axis x) motion of one-time pieces (TASK-103).

MomentumOneTime takes motion {axis: 'x', speedX, xMin, xMax}: constant speed
times momentumMotionScale(1), reversing whenever the left edge would pass xMin
or the right edge xMax (absolute world x), dx set every move; y motion
(moveY) is unchanged. Grapnel.move already follows each hooked element's dx.

At 1280x720 momentum starts on the scripted course of test_momentum_patterns_v
(segment 3 goes down), the rAF loop stopped and the obstacle floors emptied.
A sweeper (SWEEPER_W x SWEEPER_H shaft widths W) is placed with
window.momentumPlacePiece in the middle of the down shaft, xMin/xMax = the
shaft's inner wall faces (its vertical border lines), speedX = one pass in
PASS_CYCLES cycles before the time scale, and its floor is stepped. Asserts:
- test_1_blue_sweeps: over CYCLES cycles left >= xMin - EPS and right <=
  xMax + EPS, it reverses at both bounds (each turn within one step of its
  bound), |dx| per cycle = speedX * GAMEPLAY.momentumTimeScale (0.75), y and
  dy never change;
- test_2_grapnel_follows: a grapnel hooked on the sweeper moves by its dx
  every cycle (Grapnel.move), y unchanged;
- test_3_green_sweeps: a green with the same motion moves exactly like the blue;
- test_4_shots: the blue at its left bound, in the middle and at its right bound.

MOMENTUM_MOTION_X_EVIDENCE_DIR (default /tmp/momentum-motion-x) receives
sweep-trace.json (compact [{cycle, left, right, dx}] every TRACE_EVERY cycles
of the blue) and shots/sweeper-{left,middle,right}.png.
Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_MOTION_X_EVIDENCE_DIR', '/tmp/momentum-motion-x'))
# Segments: right (short), up, right, down (test_momentum_patterns_v)
SCRIPT = [0.1, 0.99, 0.1, 0.99, 0.9, 0.99, 0.9, 0.99]
SEGMENT = 3
SWEEPER_W = 0.25
SWEEPER_H = 0.05
PASS_CYCLES = 120
CYCLES = 400
TRACE_EVERY = 10
TIME_SCALE = 0.75
EPS = 1e-6

SETUP = '''(segment) => {
    startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    ninja.invulnerableMs = 1e9
    const s = momentumCourse.segment(segment)
    const faces = momentumBorders().filter(b => b.segment == segment && b.x0 == b.x1).map(b => b.x0)
    return {segment: s, half: momentumSegmentHalfWidth(s), faces: faces,
            timeScale: GAMEPLAY.momentumTimeScale, motionScale: momentumMotionScale(1)}
}'''
# Places one `kind` piece with the motion spec centred on (x, y), parks the
# ninja far above, steps its floor `cycles` times (hooking a grapnel on it
# first when `hook`); rows [cycle, left, right, x, y, dx, dy, hookX, hookY]
# after every move (row 0 = placed)
DRIVE = '''([kind, x, y, w, h, motion, cycles, hook]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []; floor.groups = []
    ninja.x = x; ninja.y = y - 1e5; ninja.speedX = ninja.speedY = 0
    const e = momentumPlacePiece(kind, {shape: 'rect', x: x, y: y, w: w, h: h, motion: motion}).element
    if (hook) {
        grapnel.throwed = true; grapnel.grappled = true
        grapnel.pos = [[x + w / 4, y - h / 2, e]]
    }
    const rows = []
    const record = k => rows.push([k, e.x + e.leftPointX, e.x + e.rightPointX, e.x, e.y, e.dx, e.dy,
                                   hook ? grapnel.pos[0][0] : null, hook ? grapnel.pos[0][1] : null])
    record(0)
    for (let k = 1; k <= cycles; ++k) {
        floor.moveElements()
        if (hook) grapnel.move()
        record(k)
    }
    const speedX = e.speedX
    if (hook) { grapnel.throwed = false; grapnel.grappled = false; grapnel.pos = [] }
    return {rows: rows, className: e.constructor.name, speedX: speedX, axis: e.motion.axis}
}'''
# Camera on (cx, cy) in course segment `segment`, ninja above the piece, draw
SHOOT = '''([cx, cy, segment]) => {
    const i0 = screen.segmentIndex
    screen.segmentIndex = segment
    try {
        const w = width / scale[version], h = height / scale[version]
        screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
        screen.leftWall.update(screen)
        for (const f of floors)
            if (f instanceof MomentumBorderFloor)
                f.replenishElements()
        ninja.x = cx; ninja.y = cy - 0.3 * h; ninja.speedX = ninja.speedY = 0
        draw()
    } finally { screen.segmentIndex = i0 }
}'''


class MomentumMotionXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (EVIDENCE_DIR / 'shots').mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
        cls.addClassCleanup(context.close)
        cls.page = context.new_page()
        cls.errors = []
        cls.page.on('pageerror', lambda e: cls.errors.append(str(e)))
        cls.page.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.evaluate(SEED_COURSE, SCRIPT)
        info = cls.page.evaluate(SETUP, SEGMENT)
        segment = info['segment']
        assert segment['dir'] == 'down', segment
        cls.info = info
        W = 2 * info['half']
        cls.cx = segment['x0']
        cls.cy = (segment['y0'] + segment['y1']) / 2
        cls.w, cls.h = SWEEPER_W * W, SWEEPER_H * W
        cls.x_min, cls.x_max = min(info['faces']), max(info['faces'])
        cls.speed_x = (cls.x_max - cls.x_min - cls.w) / PASS_CYCLES
        cls.motion = {'axis': 'x', 'speedX': cls.speed_x, 'xMin': cls.x_min, 'xMax': cls.x_max}
        print(f"\nshaft W {W:.3f} faces {cls.x_min:.3f}..{cls.x_max:.3f} sweeper {cls.w:.3f}x{cls.h:.3f}"
              f" speedX {cls.speed_x:.4f} timeScale {info['timeScale']} motionScale {info['motionScale']}")

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def drive(self, kind='blue', cycles=CYCLES, hook=False):
        return self.page.evaluate(DRIVE, [kind, self.cx, self.cy, self.w, self.h, self.motion, cycles, hook])

    def turns(self, rows):
        """(cycle, side) where dx changes sign"""
        return [(r[0], 'right' if p[5] > 0 else 'left')
                for p, r in zip(rows[1:], rows[2:]) if p[5] * r[5] < 0]

    def check_sweep(self, run):
        rows = run['rows']
        self.assertEqual(run['axis'], 'x')
        self.assertEqual(self.info['timeScale'], TIME_SCALE)
        step = self.speed_x * TIME_SCALE
        self.assertAlmostEqual(abs(run['speedX']), step, delta=1e-12)
        y0 = rows[0][4]
        for r in rows:
            self.assertGreaterEqual(r[1], self.x_min - EPS, r)
            self.assertLessEqual(r[2], self.x_max + EPS, r)
            self.assertEqual(r[4], y0, r)
            self.assertEqual(r[6], 0, r)
        for p, r in zip(rows, rows[1:]):
            self.assertAlmostEqual(abs(r[5]), step, delta=1e-9, msg=r)
            self.assertAlmostEqual(r[3] - p[3], r[5], delta=1e-9, msg=r)
        turns = self.turns(rows)
        sides = [t[1] for t in turns]
        self.assertIn('right', sides)
        self.assertIn('left', sides)
        by_cycle = {r[0]: r for r in rows}
        for cycle, side in turns:
            r = by_cycle[cycle]
            if side == 'right':
                self.assertLess(self.x_max - r[2], step + EPS, r)
            else:
                self.assertLess(r[1] - self.x_min, step + EPS, r)
        return turns

    def test_1_blue_sweeps(self):
        run = self.drive('blue')
        self.assertEqual(run['className'], 'MomentumBlue')
        turns = self.check_sweep(run)
        rows = run['rows']
        print('blue turns', turns, 'min left - xMin', min(r[1] for r in rows) - self.x_min,
              'xMax - max right', self.x_max - max(r[2] for r in rows))
        trace = [{'cycle': r[0], 'left': r[1], 'right': r[2], 'dx': r[5]} for r in rows if r[0] % TRACE_EVERY == 0]
        (EVIDENCE_DIR / 'sweep-trace.json').write_text(json.dumps(
            {'xMin': self.x_min, 'xMax': self.x_max, 'step': self.speed_x * TIME_SCALE,
             'turns': [{'cycle': c, 'side': s} for c, s in turns], 'rows': trace}, separators=(',', ':')))

    def test_2_grapnel_follows(self):
        run = self.drive('blue', hook=True)
        rows = run['rows']
        self.check_sweep(run)
        for p, r in zip(rows, rows[1:]):
            self.assertAlmostEqual(r[7] - p[7], r[5], delta=1e-9, msg=r)
            self.assertEqual(r[8], p[8], r)
        print('grapnel moved', rows[-1][7] - rows[0][7], 'piece moved', rows[-1][3] - rows[0][3])

    def test_3_green_sweeps(self):
        green = self.drive('green')
        self.assertEqual(green['className'], 'MomentumGreen')
        self.check_sweep(green)
        blue = self.drive('blue')
        self.assertEqual([r[:7] for r in green['rows']], [r[:7] for r in blue['rows']])

    def test_4_shots(self):
        rows = self.drive('blue')['rows']
        turns = self.turns(rows)
        # The cycle before a turn: the edge on its bound
        right = next(c for c, s in turns if s == 'right') - 1
        left = next(c for c, s in turns if s == 'left') - 1
        for name, cycles in (('left', left), ('middle', 0), ('right', right)):
            r = self.drive('blue', cycles=cycles)['rows'][-1]
            self.page.evaluate(SHOOT, [self.cx, self.cy, SEGMENT])
            path = EVIDENCE_DIR / 'shots' / f'sweeper-{name}.png'
            self.page.screenshot(path=str(path))
            print(f'{path.name}: cycle {cycles} left {r[1]:.3f} right {r[2]:.3f} (faces {self.x_min:.3f}..{self.x_max:.3f})')
        floor = "floors.find(f => f instanceof MomentumPatternFloor)"
        self.page.evaluate(f"() => {{ {floor}.elements = []; {floor}.groups = [] }}")


if __name__ == '__main__':
    unittest.main()
