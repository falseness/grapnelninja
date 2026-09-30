"""Browser tests for the Frame 1 template: geometry, 45-degree launch, trapped cube."""
from pathlib import Path
import json
import os
import sys
import unittest

# Allow `python3 -m unittest tools/test_frame1_factory.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('FRAME1_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-064'))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

VIEWPORTS = [(772, 630), (1280, 720), (1920, 1080)]
REFERENCE = (1120, 630)
# Bad-mode ground top in reference pixels (2 * height of a 2.2 * height world).
GROUND_TOP = REFERENCE[1] * 2 / 2.2
# Rects: x, y, width, height. Derived from screenshots/Frame 1.svg, then changed:
# taller pillars reaching the ground, 1.5x pillar gap, 3x cube side.
SVG = {
    'leftPillar': (164.5, 137.5, 52, GROUND_TOP - 137.5),
    'rightPillar': (858.5, 137.5, 52, GROUND_TOP - 137.5),
    'cube': (330, 387, 153, 156),
}
TOLERANCE = 1e-6
# 30 simulated seconds at 60 ticks per second.
SECONDS = 30
TICKS_PER_SECOND = 60

BOX = '''const box = e => {
    const p = e.getPoints();
    return {left: Math.min(...p.map(p => p.x)), right: Math.max(...p.map(p => p.x)),
            top: Math.min(...p.map(p => p.y)), bottom: Math.max(...p.map(p => p.y))};
};'''

CREATE = '''() => {
    ''' + BOX + '''
    const elements = elementsFactory.create({min: 0, max: 0}, {min: 0, max: 0}, 'frame1Elements');
    return {width, height, scaleBad: scale.bad,
        types: elements.map(e => e.constructor.name), bounds: elements.map(box),
        speedX: elements[2].speedX, speedY: elements[2].speedY, gravity: GRAVITY};
}'''

SIMULATE = '''({ticks}) => {
    ''' + BOX + '''
    const gap = (a, b) => Math.max(b.left - a.right, a.left - b.right,
                                   b.top - a.bottom, a.top - b.bottom);
    const elements = elementsFactory.create({min: 0, max: 0}, {min: 0, max: 0}, 'frame1Elements');
    const [leftPillar, rightPillar, cube] = elements;
    // Keep the real bad-mode ground/ceiling floors; only the middle floor changes.
    floors[1].elements = elements;
    const obstacles = floors.flatMap(f => f.elements).filter(e => e !== cube);
    const groundTop = Math.min(...floors[0].elements.map(e => box(e).top));
    const ceilingBottom = Math.max(...floors[2].elements.map(e => box(e).bottom));
    const initial = {x: cube.x, y: cube.y, speedX: cube.speedX, speedY: cube.speedY};
    const cycles = ticks * cyclesPerTick;
    let minTop = Infinity, minLeft = Infinity, maxRight = -Infinity, minGap = Infinity;
    const wallReversals = [], groundBounces = [], ceilingBounces = [], samples = [];
    for (let i = 0; i < cycles; ++i) {
        const before = {speedX: cube.speedX, speedY: cube.speedY};
        cube.move();
        const b = box(cube);
        minTop = Math.min(minTop, b.top);
        minLeft = Math.min(minLeft, b.left);
        maxRight = Math.max(maxRight, b.right);
        const g = Math.min(...obstacles.map(e => gap(b, box(e))));
        minGap = Math.min(minGap, g);
        if (Math.sign(cube.speedX) != Math.sign(before.speedX))
            wallReversals.push({cycle: i, wall: before.speedX < 0 ? 'left' : 'right',
                left: b.left, right: b.right, speedXBefore: before.speedX, speedX: cube.speedX});
        if (before.speedY > 0 && cube.speedY < 0 && b.bottom > (box(leftPillar).top + groundTop) / 2)
            groundBounces.push({cycle: i, bottom: b.bottom, groundTop,
                speedYBefore: before.speedY, speedY: cube.speedY});
        if (before.speedY < 0 && cube.speedY > 0)
            ceilingBounces.push({cycle: i, top: b.top, ceilingBottom,
                speedYBefore: before.speedY, speedY: cube.speedY});
        if (i % cyclesPerTick == 0)
            samples.push({cycle: i, x: cube.x, y: cube.y, speedX: cube.speedX, speedY: cube.speedY});
    }
    return {width, height, cycles, cyclesPerTick, epsilon: GAMEPLAY.cubeContactEpsilon, initial,
        pillarTop: box(leftPillar).top, innerLeftFace: box(leftPillar).right,
        innerRightFace: box(rightPillar).left, groundTop, ceilingBottom,
        minTop, minLeft, maxRight, minGap, wallReversals, groundBounces, ceilingBounces, samples};
}'''


def expected_bounds(width, height, scale_bad, rect):
    x, y, w, h = rect
    sx = width / REFERENCE[0] / scale_bad
    sy = height / REFERENCE[1] / scale_bad
    return {'left': x * sx, 'right': (x + w) * sx, 'top': y * sy, 'bottom': (y + h) * sy}


class Frame1FactoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open_bad_game(self, width, height):
        page = self.browser.new_page(viewport={'width': width, 'height': height})
        self.addCleanup(page.close)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url)
        page.evaluate("startGame('bad'); cancelAnimationFrame(game)")
        return page

    def test_geometry_matches_svg(self):
        rows = []
        for width, height in VIEWPORTS:
            run = self.open_bad_game(width, height).evaluate(CREATE)
            self.assertAlmostEqual(run['scaleBad'], 1 / 2.2, places=12)
            row = {'viewport': [width, height], 'scaleBad': run['scaleBad'],
                   'types': run['types'], 'elements': {}}
            for (name, rect), actual in zip(SVG.items(), run['bounds']):
                expected = expected_bounds(width, height, run['scaleBad'], rect)
                error = max(abs(expected[k] - actual[k]) for k in expected)
                row['elements'][name] = {'svg': rect, 'expected': expected, 'actual': actual,
                                         'maxError': error, 'pass': error <= TOLERANCE}
            row['typeCounts'] = {t: run['types'].count(t) for t in set(run['types'])}
            rows.append(row)
            print(f"GEOMETRY {width}x{height} types={row['typeCounts']} " + ' '.join(
                f"{n}.maxError={e['maxError']:.3e}" for n, e in row['elements'].items()),
                flush=True)
        (EVIDENCE / 'geometry.json').write_text(json.dumps(
            {'tolerance': TOLERANCE, 'reference': REFERENCE, 'viewports': rows}, indent=1))
        for row in rows:
            self.assertEqual(row['types'], ['Trampoline', 'Trampoline', 'JumpingCube'])
            for name, element in row['elements'].items():
                self.assertLessEqual(element['maxError'], TOLERANCE, (row['viewport'], name))

    def test_cube_launches_up_right_and_stays_trapped(self):
        rows = []
        for width, height in VIEWPORTS:
            run = self.open_bad_game(width, height).evaluate(
                SIMULATE, {'ticks': SECONDS * TICKS_PER_SECOND})
            eps = run['epsilon']
            speed_x, speed_y = run['initial']['speedX'], run['initial']['speedY']
            run['seconds'] = run['cycles'] / run['cyclesPerTick'] / TICKS_PER_SECOND
            run['assertions'] = {
                'speedX': speed_x, 'speedY': speed_y,
                'launch45Pass': speed_x > 0 and speed_x == -speed_y,
                'simulatedSeconds': run['seconds'],
                'minTop': run['minTop'], 'ceilingBottom': run['ceilingBottom'],
                'touchesCeilingPass': run['minTop'] <= run['ceilingBottom'] + eps,
                'ceilingBounces': len(run['ceilingBounces']),
                'xRange': [run['minLeft'], run['maxRight']],
                'innerFaces': [run['innerLeftFace'], run['innerRightFace']],
                'insidePillarsPass': run['minLeft'] >= run['innerLeftFace'] - eps
                and run['maxRight'] <= run['innerRightFace'] + eps,
                'wallReversals': len(run['wallReversals']),
                'leftReversals': sum(r['wall'] == 'left' for r in run['wallReversals']),
                'rightReversals': sum(r['wall'] == 'right' for r in run['wallReversals']),
                'groundBounces': len(run['groundBounces']),
                'minObstacleGap': run['minGap'], 'minGapFloor': -eps,
                'minGapPass': run['minGap'] >= -eps,
            }
            rows.append(run)
            print(f"MOTION {width}x{height} " + json.dumps(run['assertions']), flush=True)
        (EVIDENCE / 'motion.json').write_text(json.dumps(rows, indent=1))
        for run in rows:
            a = run['assertions']
            with self.subTest(viewport=(run['width'], run['height'])):
                self.assertGreater(a['speedX'], 0)
                self.assertEqual(a['speedX'], -a['speedY'])
                self.assertGreaterEqual(a['simulatedSeconds'], SECONDS)
                self.assertTrue(a['touchesCeilingPass'])
                self.assertGreaterEqual(a['ceilingBounces'], 2)
                self.assertTrue(a['insidePillarsPass'])
                self.assertGreaterEqual(a['wallReversals'], 4)
                self.assertGreaterEqual(a['groundBounces'], 2)
                self.assertGreaterEqual(a['minObstacleGap'], -run['epsilon'])


if __name__ == '__main__':
    unittest.main()
