"""Momentum green/blue pieces of any shape (sprites/momentumonetime.js).

Each case puts one piece from a MomentumOneTime.shapeObject spec on the
emptied momentum obstacle floor (window.momentumPlacePiece) next to the ninja
of a momentum run whose rAF loop is cancelled, and moves the ninja into it
through ninja.move() alone (a moving piece steps first, floor.moveElements()).
Shapes: a triangle pointing up (hit on its slope), a tall rect (hit on its
side), a wide rect rotated 0.3 rad (hit on its tilted top) and a moving cube
(bad-style speedY bouncing in [yMin, yMax], hit on its side). Per shape and
colour it asserts:
- contact on the real polygon: the ninja is past the bounding box edge
  (by more than one radius on the slope / tilt) at the contact move,
- one contact: use() succeeds once, a second approach changes nothing,
- response: green bounces (reversed or deflected by the edge) and adds 1 to
  the streak; blue keeps the direction, scales the speed by
  GAMEPLAY.momentumBlueSlow and costs 1 hp,
- fade: getAlpha falls from 1 to 0 over GAMEPLAY.momentumFadeMs and the
  floor drops the piece,
- motion: 400 cycles of a moving cube without (Triangle-like) and with
  gravity (JumpingCube-like): y changes by speedY every cycle, speedY flips
  at the limits, the cube stays inside them.

MOMENTUM_SHAPES_EVIDENCE_DIR (default artifacts/TASK-035) receives
shapes.json (compact per-case assertion values), motion.json and
shots/: compare-momentum.png (bad Trampoline / JumpingCube / Triangle row
over the green and blue rows of the same shapes, one momentum frame),
compare-bad.png (the same bad row drawn in an actual bad-mode run),
compare-zoom.png (2x crop of compare-momentum.png) and fade.png (the six
momentum pieces mid-fade). Requires Playwright Chromium.
"""
import json
import math
import os
from pathlib import Path
import unittest

from PIL import Image

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_SHAPES_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-035'))
# World units per physics cycle, under GAMEPLAY.momentumMaxSpeed (2.78 at
# h 1080 since TASK-047; 5 was clamped to it); move budget doubled with it
SPEED = 2.5
MAX_MOVES = 240
SHAPES = ['triangle', 'tall', 'wide', 'moving']

SETUP = '''() => {
    startGame('momentum')
    cancelAnimationFrame(game)
    window.__deaths = 0
    const lethal = window.onLethalDeath
    window.onLethalDeath = function() { ++window.__deaths; return lethal.apply(this, arguments) }
    ninja.__tag = 'shapes-test'
    window.__start = {x: ninja.x, y: ninja.y}
    return {x: ninja.x, y: ninja.y, radius: ninja.radius}
}'''

# One case: place, approach until the piece is used, approach again
CASE = '''([kind, shape, speed, maxMoves]) => {
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    floor.elements = []
    floor.groups = []
    momentumState.reset()
    const r = ninja.radius, x0 = window.__start.x, y0 = window.__start.y
    const specs = {
        triangle: {shape: 'triangle', x: x0 - 2 * r, y: y0 + 10 * r, radius: 6 * r, angle: Math.PI},
        tall: {shape: 'rect', x: x0 + 8 * r, y: y0, w: 4 * r, h: 20 * r},
        wide: {shape: 'rect', x: x0, y: y0 + 8 * r, w: 30 * r, h: 4 * r, angle: 0.3},
        moving: {shape: 'rect', x: x0 + 8 * r, y: y0, w: 10 * r, h: 10 * r,
                 motion: {speedY: 0.5, yMin: y0 - 8 * r, yMax: y0 + 8 * r}}
    }
    const fall = shape == 'triangle' || shape == 'wide'
    const placed = momentumPlacePiece(kind, specs[shape])
    const piece = placed.element
    let uses = 0
    const use = piece.use.bind(piece)
    piece.use = () => { const ok = use(); if (ok) ++uses; return ok }
    const box = getElementBounds(piece)
    const approach = () => {
        ninja.x = x0
        ninja.y = y0
        ninja.speedX = fall ? 0 : speed
        ninja.speedY = fall ? speed : 0
        const used = piece.passThrough
        const rows = []
        for (let moves = 1; moves <= maxMoves; ++moves) {
            const before = {x: ninja.x, y: ninja.y}
            if (piece.motion) floor.moveElements()
            ninja.move()
            if (!used && piece.passThrough)
                return {moves, before, speedX: ninja.speedX, speedY: ninja.speedY}
        }
        return {moves: maxMoves, before: null, speedX: ninja.speedX, speedY: ninja.speedY}
    }
    const first = approach()
    const state1 = {hp: momentumState.hp, streak: momentumState.greenStreak}
    const second = approach()
    window.__piece = {floor, piece}
    return {kind, shape, radius: r, box: [box.left, box.top, box.right, box.bottom],
        points: piece.points.length, className: piece.constructor.name,
        first, state1, second, uses, hp: momentumState.hp, streak: momentumState.greenStreak,
        passThrough: piece.passThrough, slow: GAMEPLAY.momentumBlueSlow, startHp: GAMEPLAY.momentumHp.startHp,
        deaths: window.__deaths, sameNinja: ninja.__tag === 'shapes-test', version, runInProgress}
}'''

SAMPLE_FADE = '''() => new Promise(resolve => {
    const {floor, piece} = window.__piece
    const start = piece.fadeStartMs
    const samples = [[0, piece.getAlpha(start)]]
    function tick() {
        const now = performance.now()
        const alpha = piece.getAlpha(now)
        floor.moveElements()
        samples.push([+(now - start).toFixed(1), +alpha.toFixed(4)])
        if (floor.elements.includes(piece)) setTimeout(tick, 40)
        else resolve({samples, removedMs: samples[samples.length - 1][0], fadeMs: GAMEPLAY.momentumFadeMs})
    }
    tick()
})'''

MOTION = '''([gravity]) => {
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    floor.elements = []
    floor.groups = []
    const r = ninja.radius, x0 = window.__start.x + 40 * r, y0 = window.__start.y
    const motion = gravity ? {speedY: -1, yMin: y0 - 10 * r, yMax: y0 + 10 * r, gravity: true}
                           : {speedY: 1.5, yMin: y0 - 6 * r, yMax: y0 + 6 * r}
    const piece = momentumPlacePiece('green', {shape: 'rect', x: x0, y: y0, w: 6 * r, h: 6 * r, motion}).element
    const rows = []
    let bad = 0, flips = 0, outside = 0, prevSpeed = piece.speedY
    for (let k = 0; k < 400; ++k) {
        const y = piece.y
        floor.moveElements()
        const b = getElementBounds(piece)
        if (Math.abs(piece.y - y - piece.speedY) > 1e-9 || piece.dy !== piece.speedY) ++bad
        if (Math.sign(piece.speedY) != Math.sign(prevSpeed)) ++flips
        if (b.top < motion.yMin - Math.abs(piece.speedY) - 1e-9 || b.bottom > motion.yMax + Math.abs(piece.speedY) + 1e-9) ++outside
        // gravity: the speed grows by GRAVITY per cycle between bounces
        if (gravity && Math.sign(piece.speedY) == Math.sign(prevSpeed) && Math.abs(piece.speedY - prevSpeed - GRAVITY) > 1e-9) ++bad
        prevSpeed = piece.speedY
        if (k % 20 == 0) rows.push([k, +piece.y.toFixed(3), +piece.speedY.toFixed(4)])
    }
    return {gravity, bad, flips, outside, rows, yMin: motion.yMin, yMax: motion.yMax}
}'''

# Shot layout: columns tall rect, wide rect, cube, triangle; rows bad,
# green, blue. Positions in view fractions, sizes in units of height
LAYOUT = '''([mode]) => {
    cancelAnimationFrame(game)
    const s = scale[version], vw = width / s, vh = height / s, H = height
    const wx = f => f * vw - screen.x, wy = f => f * vh - screen.y
    const cols = [0.16, 0.38, 0.62, 0.84], rows = mode == 'bad' ? [0.5] : [0.25, 0.5, 0.75]
    const size = {tall: [0.1 * H, 0.32 * H], wide: [0.42 * H, 0.09 * H], cube: [0.2 * H, 0.2 * H]}
    const triRadius = 0.18 * H
    const bad = []
    const cx = (c) => wx(cols[c]), cy = (r) => wy(rows[r])
    const rectPoints = (w, h) => [{x: -w / 2, y: -h / 2}, {x: w / 2, y: -h / 2}, {x: w / 2, y: h / 2}, {x: -w / 2, y: h / 2}]
    const badRow = 0
    for (const [c, key] of [[0, 'tall'], [1, 'wide']]) {
        const [w, h] = size[key]
        bad.push(new Trampoline({x: cx(c), y: cy(badRow), points: rectPoints(w, h),
            fill: STYLE.colors.cube.greenFill, stroke: STYLE.colors.cube.greenStroke}))
    }
    const [cw, ch] = size.cube
    const cube = new JumpingCube({x: cx(2) - cw / 2, y: cy(badRow) - ch / 2, width: cw, height: ch,
        fill: STYLE.colors.cube.blueFill, stroke: STYLE.colors.cube.blueStroke})
    cube.x = cx(2) - cw / 2; cube.y = cy(badRow) - ch / 2; cube.speedY = 0; cube.track.pos = []
    bad.push(cube)
    const tri = new Triangle({x: cx(3), y: cy(badRow), radius: triRadius, yMin: -1e9, yMax: 1e9,
        fill: STYLE.colors.hazard.fill, stroke: STYLE.colors.hazard.stroke})
    tri.speedY = 0; tri.track.pos = []; tri.track.addPos(tri.getPoints(), true)
    bad.push(tri)
    const pieces = []
    if (mode != 'bad') {
        ;['green', 'blue'].forEach((kind, k) => {
            const r = k + 1
            pieces.push(momentumPlacePiece(kind, {shape: 'rect', x: cx(0), y: cy(r), w: size.tall[0], h: size.tall[1]}).element)
            pieces.push(momentumPlacePiece(kind, {shape: 'rect', x: cx(1), y: cy(r), w: size.wide[0], h: size.wide[1]}).element)
            pieces.push(momentumPlacePiece(kind, {shape: 'rect', x: cx(2), y: cy(r), w: cw, h: ch}).element)
            pieces.push(momentumPlacePiece(kind, {shape: 'triangle', x: cx(3), y: cy(r), radius: triRadius}).element)
        })
    }
    const floor = floors.find(f => mode == 'bad' ? (f instanceof Floor && !(f instanceof SideFloor)) : f instanceof MomentumObstacleFloor)
    floor.elements.push(...bad)
    // the start hint would cover the middle column
    TUTORIAL_HINT.visible = false
    // ninja out of the way, left edge
    ninja.x = wx(0.03); ninja.y = wy(0.5); ninja.speedX = 0; ninja.speedY = 0
    window.__shotPieces = pieces
    // canvas px
    const box = e => { const b = getElementBounds(e)
        return [(b.left + screen.x) * s, (b.top + screen.y) * s, (b.right + screen.x) * s, (b.bottom + screen.y) * s].map(v => +v.toFixed(1)) }
    return {version, bad: bad.map(e => [e.constructor.name, box(e)]), pieces: pieces.map(e => [e.constructor.name, e.points.length, box(e)])}
}'''

CLEAR_MODE = '''([mode]) => {
    if (mode == 'bad') {
        startGame('bad')
        cancelAnimationFrame(game)
        for (const f of floors)
            if (f instanceof Floor && !(f instanceof SideFloor)) f.elements = []
    } else {
        startGame('momentum')
        cancelAnimationFrame(game)
        const floor = floors.find(f => f instanceof MomentumObstacleFloor)
        floor.elements = []
        floor.groups = []
    }
    return version
}'''

DRAW = '(() => { draw() })()'

FADE_HALF = '''() => {
    const now = performance.now()
    for (const p of window.__shotPieces) { p.passThrough = true; p.fadeStartMs = now - GAMEPLAY.momentumFadeMs / 2 }
    const real = performance.now
    performance.now = () => now
    draw()
    performance.now = real
    return window.__shotPieces.map(p => +p.getAlpha(now).toFixed(3))
}'''


class MomentumShapesTests(unittest.TestCase):
    cases = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        (EVIDENCE_DIR / 'shots').mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        (EVIDENCE_DIR / 'shapes.json').write_text(json.dumps(cls.cases, separators=(',', ':')) + '\n')

    def open(self, setup=True):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        if setup:
            print('setup', page.evaluate(SETUP))
        return page

    def run_case(self, page, kind, shape):
        res = page.evaluate(CASE, [kind, shape, SPEED, MAX_MOVES])
        fade = page.evaluate(SAMPLE_FADE)
        r = res['radius']
        left, top, right, bottom = res['box']
        first, second = res['first'], res['second']
        fall = shape in ('triangle', 'wide')
        self.assertEqual(res['version'], 'momentum')
        self.assertTrue(res['runInProgress'])
        self.assertTrue(res['sameNinja'])
        self.assertEqual(res['deaths'], 0)
        self.assertEqual(res['className'], 'MomentumGreen' if kind == 'green' else 'MomentumBlue')
        self.assertEqual(res['points'], 3 if shape == 'triangle' else 4)
        # Contact once
        self.assertIsNotNone(first['before'], 'no contact')
        self.assertTrue(res['passThrough'])
        self.assertEqual(res['uses'], 1)
        self.assertIsNone(second['before'])
        # Contact on the real polygon, not on the bounding box
        if fall:
            depth = first['before']['y'] + SPEED - (top - r)
            # slope / tilt: the edge under the ninja is far below the box top
            self.assertGreater(depth, r, 'contact at the bounding box top')
        else:
            depth = first['before']['x'] + SPEED - (left - r)
            self.assertGreaterEqual(depth, 0)
            self.assertLess(depth, SPEED + 1e-6)
        # Response
        if kind == 'green':
            self.assertEqual(res['state1'], {'hp': res['startHp'], 'streak': 1})
            if shape in ('tall', 'moving'):
                self.assertAlmostEqual(first['speedX'], -SPEED, places=6)
            else:
                self.assertGreater(first['speedX'], 0.5, 'not deflected by the slanted edge')
                self.assertLess(abs(math.hypot(first['speedX'], first['speedY']) - SPEED), 0.1 * SPEED)
        else:
            self.assertEqual(res['state1'], {'hp': res['startHp'] - 1, 'streak': 0})
            ex, ey = (0, SPEED * res['slow']) if fall else (SPEED * res['slow'], 0)
            self.assertAlmostEqual(first['speedX'], ex, places=6)
            self.assertAlmostEqual(first['speedY'], ey, places=6)
        # Second approach: passes with the start speed, state unchanged
        self.assertEqual((second['speedX'], second['speedY']), (0, SPEED) if fall else (SPEED, 0))
        self.assertEqual({'hp': res['hp'], 'streak': res['streak']}, res['state1'])
        # Fade
        alphas = [a for _, a in fade['samples']]
        self.assertAlmostEqual(alphas[0], 1, places=3)
        self.assertEqual(alphas, sorted(alphas, reverse=True))
        self.assertEqual(alphas[-1], 0)
        self.assertGreaterEqual(fade['removedMs'], fade['fadeMs'])
        mid = [a for t, a in fade['samples'] if 0.3 * fade['fadeMs'] < t < 0.7 * fade['fadeMs']]
        self.assertTrue(mid and all(0 < a < 1 for a in mid))
        self.cases[f'{kind}-{shape}'] = {
            'contactMove': first['moves'], 'depthPastBox': round(depth, 2), 'radius': round(r, 2),
            'firstSpeed': [round(first['speedX'], 4), round(first['speedY'], 4)],
            'secondSpeed': [second['speedX'], second['speedY']], 'uses': res['uses'],
            'afterFirst': res['state1'], 'final': {'hp': res['hp'], 'streak': res['streak']},
            'fade': {'first': alphas[0], 'last': alphas[-1], 'removedMs': fade['removedMs'],
                     'fadeMs': fade['fadeMs'], 'samples': len(alphas)}}
        print(kind, shape, 'OK', json.dumps(self.cases[f'{kind}-{shape}'], separators=(',', ':')))

    def test_green_shapes(self):
        page = self.open()
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.run_case(page, 'green', shape)

    def test_blue_shapes(self):
        page = self.open()
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.run_case(page, 'blue', shape)

    def test_motion_follows_speed(self):
        page = self.open()
        out = {}
        for gravity in (False, True):
            res = page.evaluate(MOTION, [gravity])
            key = 'gravity' if gravity else 'constant'
            out[key] = res
            print('motion', key, 'bad', res['bad'], 'flips', res['flips'], 'outside', res['outside'])
            self.assertEqual(res['bad'], 0)
            self.assertEqual(res['outside'], 0)
            self.assertGreaterEqual(res['flips'], 2)
        (EVIDENCE_DIR / 'motion.json').write_text(json.dumps(out, separators=(',', ':')) + '\n')

    def test_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        page = self.open(setup=False)
        # Actual bad mode first, then momentum
        self.assertEqual(page.evaluate(CLEAR_MODE, ['bad']), 'bad')
        bad = page.evaluate(LAYOUT, ['bad'])
        page.evaluate(DRAW)
        page.screenshot(path=str(shots / 'compare-bad.png'))
        self.assertEqual(page.evaluate(CLEAR_MODE, ['momentum']), 'momentum')
        mom = page.evaluate(LAYOUT, ['momentum'])
        page.evaluate(DRAW)
        page.screenshot(path=str(shots / 'compare-momentum.png'))
        # 2x of the top-left quarter (tall and wide rects, all three rows)
        Image.open(shots / 'compare-momentum.png').crop((60, 40, 700, 400)).resize(
            (1280, 720), Image.LANCZOS).save(shots / 'compare-zoom.png')
        alphas = page.evaluate(FADE_HALF)
        page.screenshot(path=str(shots / 'fade.png'))
        print('layout bad', json.dumps(bad), 'momentum', json.dumps(mom), 'fade alphas', alphas)
        # Same screen sizes for the bad row and every momentum row
        size = lambda b: (round(b[2] - b[0]), round(b[3] - b[1]))
        bad_sizes = [size(b) for _, b in bad['bad']]
        for k in range(2):
            row = [size(b) for _, _, b in mom['pieces'][4 * k:4 * k + 4]]
            for a, b in zip(row, bad_sizes):
                self.assertLessEqual(abs(a[0] - b[0]), 1)
                self.assertLessEqual(abs(a[1] - b[1]), 1)
        self.assertTrue(all(abs(a - 0.5) < 0.01 for a in alphas))
        (EVIDENCE_DIR / 'shots-layout.json').write_text(
            json.dumps({'bad': bad, 'momentum': mom, 'fadeAlphas': alphas}, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    unittest.main()
