"""Momentum borders (TASK-004): elements/momentumborders.js.

Starts momentum on a fixed course: MomentumCourse.generate draws from a
scripted Math.random stub (then a seeded LCG), so the course is
R U R R D R D R U R ... and every join type appears. Asserts on the live
window.momentumBorders() list: one floor and one ceiling per right
segment, two walls per vertical segment, each face halfWidth from the
centre line, corners closed (end of a border == start of the next on the
same side, gap 0), and a ninja moving into a floor, a ceiling and both
walls bounces (normal speed flips sign) and stays alive. Walls are drawn
in STYLE.momentum.wallStroke, darker than the '#3dff4a' floor; the
screenshots teleport the camera through screen.x/y with the loop stopped.

MOMENTUM_BORDERS_EVIDENCE_DIR (default: artifacts/TASK-004) receives
borders.json, bounces.json, right-segment.png and up-segment.png.
Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
DIRS = ['right', 'up', 'right', 'right', 'down', 'right', 'down', 'right', 'up', 'right']
# Draws of MomentumCourse.generate for DIRS: after a right segment one draw
# >= 0.4 picks vertical and a second picks up (< 0.5) or down, then the
# length draw. Short rights keep the scripted part inside the 3-viewport window.
SCRIPT = [0.1,
          0.9, 0.1, 0.5,
          0.1,
          0.1, 0.1,
          0.9, 0.9, 0.5,
          0.1,
          0.9, 0.9, 0.5,
          0.1,
          0.9, 0.1, 0.5,
          0.1]
SEED_COURSE = '''(script) => {
    let k = 0, s = 12345
    const next = () => k < script.length ? script[k++]
        : ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648)
    const generate = MomentumCourse.prototype.generate
    MomentumCourse.prototype.generate = function() {
        const random = Math.random
        Math.random = next
        try { return generate.call(this) } finally { Math.random = random }
    }
}'''
# Puts the ninja next to a border, moving into it, and runs real physics
# steps until it bounces. Synchronous, so the rAF loop cannot interleave.
BOUNCE = '''([x, y, vx, vy, axis, hit]) => {
    const n0 = ninja
    grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
    ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy
    const before = axis == 'x' ? ninja.speedX : ninja.speedY
    let after = before, steps = 0
    while (steps < 40 && Math.sign(after) == Math.sign(before)) {
        calcPhysics(); steps++
        after = axis == 'x' ? ninja.speedX : ninja.speedY
    }
    return {before, after, steps, alive: ninja === n0 && version == 'momentum' &&
            runInProgress && !runOver && !continueOffer.visible,
            x: ninja.x, y: ninja.y, hitBorderLive: momentumBorders().some(b =>
                b.segment == hit.segment && b.side == hit.side && b.kind == hit.kind)}
}'''


class MomentumBordersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_BORDERS_EVIDENCE_DIR',
                                      ROOT / 'artifacts/TASK-004'))
        cls.out.mkdir(parents=True, exist_ok=True)
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
        cls.page.evaluate("startGame('momentum')")
        # Freeze the loop: the bounce cases step physics themselves
        cls.page.evaluate('cancelAnimationFrame(game)')
        cls.options = cls.page.evaluate('({...GAMEPLAY.momentumBorders})')
        cls.segments = cls.page.evaluate('momentumCourse.segments')
        cls.borders = cls.page.evaluate('momentumBorders()')
        (cls.out / 'borders.json').write_text(json.dumps(
            {'halfWidth': cls.options['halfWidth'],
             'course': [[s['dir'], s['x0'], s['y0'], s['x1'], s['y1']] for s in cls.segments],
             'borders': cls.borders}, separators=(',', ':')))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def by_segment(self):
        out = {}
        for b in self.borders:
            out.setdefault(b['segment'], []).append(b)
        return out

    def test_course_is_scripted(self):
        dirs = [s['dir'] for s in self.segments[:len(DIRS)]]
        print('course dirs:', dirs, 'segments generated:', len(self.segments))
        self.assertEqual(dirs, DIRS)
        joins = {(a['dir'], b['dir']) for a, b in zip(self.segments, self.segments[1:])}
        for join in [('right', 'up'), ('up', 'right'), ('right', 'down'),
                     ('down', 'right'), ('right', 'right')]:
            self.assertIn(join, joins)

    def test_border_kinds_per_segment(self):
        groups = self.by_segment()
        print('segments with borders:', sorted(groups), 'border lines:', len(self.borders))
        self.assertGreaterEqual(len(groups), len(DIRS))
        self.assertEqual(sorted(groups), list(range(len(groups))))
        counts = {'right': 0, 'vertical': 0}
        for index, lines in groups.items():
            dir = self.segments[index]['dir']
            kinds = sorted(b['kind'] for b in lines)
            if dir == 'right':
                self.assertEqual(kinds, ['ceiling', 'floor'], index)
                counts['right'] += 1
            else:
                self.assertEqual(kinds, ['wall', 'wall'], index)
                self.assertEqual(sorted(b['side'] for b in lines), [-1, 1], index)
                counts['vertical'] += 1
        print('right segments with floor+ceiling:', counts['right'],
              'vertical segments with 2 walls:', counts['vertical'])

    def test_faces_on_offset_lines(self):
        hw = self.options['halfWidth']
        for b in self.borders:
            s = self.segments[b['segment']]
            if s['dir'] == 'right':
                y = s['y0'] + (hw if b['kind'] == 'floor' else -hw)
                self.assertEqual((b['y0'], b['y1']), (y, y), b)
                self.assertLess(b['x0'], b['x1'])
            else:
                normal = b['side'] if s['dir'] == 'up' else -b['side']
                x = s['x0'] + normal * hw
                self.assertEqual((b['x0'], b['x1']), (x, x), b)

    def test_corners_closed(self):
        groups = self.by_segment()
        gaps = []
        for index in sorted(groups)[:-1]:
            for side in (1, -1):
                a = next(b for b in groups[index] if b['side'] == side)
                c = next(b for b in groups[index + 1] if b['side'] == side)
                gaps.append([index, side, ((a['x1'] - c['x0']) ** 2 + (a['y1'] - c['y0']) ** 2) ** 0.5])
        print('corner joins:', len(gaps), 'max gap:', max(g[2] for g in gaps))
        self.assertGreaterEqual(len(gaps), 2 * (len(DIRS) - 1))
        self.assertTrue(all(g[2] == 0 for g in gaps), gaps)

    def border(self, segment, kind, side=None):
        return next(b for b in self.borders if b['segment'] == segment and b['kind'] == kind
                    and (side is None or b['side'] == side))

    def test_bounces(self):
        speed = 30
        gap = 60
        floor = self.border(3, 'floor')
        ceiling = self.border(3, 'ceiling')
        x = (floor['x0'] + floor['x1']) / 2
        up_right = self.border(1, 'wall', 1)
        up_left = self.border(1, 'wall', -1)
        down_right = self.border(4, 'wall', -1)
        wall_y = lambda w: (w['y0'] + w['y1']) / 2
        # Ordered along x: the camera only moves forward, and borders it
        # leaves behind are deleted
        cases = {
            'wall-up-left': [up_left['x0'] + gap, wall_y(up_left), -speed, 0, 'x', up_left],
            'wall-up-right': [up_right['x0'] - gap, wall_y(up_right), speed, 0, 'x', up_right],
            'floor': [x, floor['y0'] - gap, 0, speed, 'y', floor],
            'ceiling': [x, ceiling['y0'] + gap, 0, -speed, 'y', ceiling],
            'wall-down-right': [down_right['x0'] - gap, wall_y(down_right), speed, 0, 'x', down_right],
        }
        results = {}
        for name, args in cases.items():
            with self.subTest(name):
                # Keep the ninja inside the camera so neither the left edge nor
                # the momentum camera's left-behind side (TASK-005) can kill it
                self.page.evaluate('''([x, y]) => { screen.x = -x + width
                    screen.y = -(y - height / scale[version] / 2) }''', args[:2])
                r = self.page.evaluate(BOUNCE, args)
                results[name] = r
                print(name, 'normal speed', r['before'], '->', round(r['after'], 3),
                      'steps', r['steps'], 'alive', r['alive'], 'border still live', r['hitBorderLive'])
                self.assertLess(r['before'] * r['after'], 0, r)
                self.assertTrue(r['alive'], r)
                # Never one-time: the border that was hit is still live
                self.assertTrue(r['hitBorderLive'], r)
        (self.out / 'bounces.json').write_text(json.dumps(
            {k: {'before': v['before'], 'after': v['after'], 'steps': v['steps'], 'alive': v['alive'],
                 'hitBorderLive': v['hitBorderLive']}
             for k, v in results.items()}, separators=(',', ':')))

    # Sorted first: test_bounces moves the camera and deletes the borders behind it
    def test_appearance_walls_darker(self):
        style = self.page.evaluate('''({wall: STYLE.momentum.wallStroke,
            ground: STYLE.badVersionEffects.obstacles.groundStroke})''')
        lum = lambda c: sum(int(c[i:i + 2], 16) * w for i, w in ((1, .2126), (3, .7152), (5, .0722)))
        print('wall stroke', style['wall'], 'floor stroke', style['ground'],
              'luma', round(lum(style['wall'])), round(lum(style['ground'])))
        self.assertLess(lum(style['wall']), 0.6 * lum(style['ground']))
        strokes = self.page.evaluate('''floors.flatMap(f => f.elements)
            .filter(e => e instanceof MomentumBorder).map(e => [e.kind, e.stroke])''')
        for kind, stroke in strokes:
            self.assertEqual(stroke, style['wall'] if kind == 'wall' else style['ground'])
        shots = {'right-segment.png': 3, 'up-segment.png': 1}
        for name, index in shots.items():
            s = self.segments[index]
            cx, cy = (s['x0'] + s['x1']) / 2, (s['y0'] + s['y1']) / 2
            self.page.evaluate('''([cx, cy]) => {
                const w = width / scale[version], h = height / scale[version]
                screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
                // The camera-owned left wall follows the teleport, as in play
                screen.leftWall.update(screen)
                ninja.x = cx; ninja.y = cy; ninja.speedX = ninja.speedY = 0
                draw()
            }''', [cx, cy])
            self.page.screenshot(path=str(self.out / name))
            print('screenshot', name, 'segment', index, s['dir'], 'centre', round(cx), round(cy))


if __name__ == '__main__':
    unittest.main()
