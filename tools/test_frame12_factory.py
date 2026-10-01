"""Browser tests for the Frame 12 template: geometry, opposed 45-degree launches, trapped cubes."""
from pathlib import Path
import json
import os
import sys
import unittest

# Allow `python3 -m unittest tools/test_frame12_factory.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('FRAME12_EVIDENCE_DIR', ROOT / 'artifacts' / 'frame12'))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

VIEWPORTS = [(772, 630), (1280, 720), (1920, 1080)]
REFERENCE = (1120, 630)
# Bad-mode ground top in reference pixels (2 * height of a 2.2 * height world).
GROUND_TOP = REFERENCE[1] * 2 / 2.2
PILLAR_BOTTOM = GROUND_TOP - 60
# Like Frame 1, the right pillar moves from 638.5 to 858.5 and interior
# centres spread proportionally across the wider gap.
INNER_LEFT = 167.5 + 52


def spread(x):
    return INNER_LEFT + (x - INNER_LEFT) * (858.5 - INNER_LEFT) / (638.5 - INNER_LEFT)


# Rects: x, y, width, height. Derived from screenshots/Frame 12.svg.
SVG = {
    'leftPillar': (167.5, 137.5, 52, PILLAR_BOTTOM - 137.5),
    'rightPillar': (858.5, 137.5, 52, PILLAR_BOTTOM - 137.5),
    'middleBlock': (spread(397 + 53 / 2) - 53 / 2, 308, 53, 113),
    'leftCube': (spread(260 + 48) - 48, 210, 96, 98),
    'rightCube': (spread(525 + 48) - 48, 280, 96, 98),
}
TYPES = ['Trampoline'] * 3 + ['JumpingCube'] * 2
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
    const elements = elementsFactory.create({min: 0, max: 0}, {min: 0, max: 0}, 'frame12Elements');
    return {width, height, scaleBad: scale.bad,
        types: elements.map(e => e.constructor.name), bounds: elements.map(box),
        speeds: elements.slice(3).map(c => ({speedX: c.speedX, speedY: c.speedY}))};
}'''

SIMULATE = '''({ticks}) => {
    ''' + BOX + '''
    const gap = (a, b) => Math.max(b.left - a.right, a.left - b.right,
                                   b.top - a.bottom, a.top - b.bottom);
    const elements = elementsFactory.create({min: 0, max: 0}, {min: 0, max: 0}, 'frame12Elements');
    const [leftPillar, rightPillar] = elements;
    const cubes = elements.slice(3);
    // Keep the real bad-mode ground/ceiling floors; only the middle floor changes.
    floors[1].elements = elements;
    const ceilingBottom = Math.max(...floors[2].elements.map(e => box(e).bottom));
    const initial = cubes.map(c => ({speedX: c.speedX, speedY: c.speedY}));
    const stats = cubes.map(() => ({minTop: Infinity, minLeft: Infinity, maxRight: -Infinity,
        minGap: Infinity, wallReversals: 0, ceilingBounces: 0}));
    const cycles = ticks * cyclesPerTick;
    for (let i = 0; i < cycles; ++i) {
        cubes.forEach((cube, k) => {
            const before = {speedX: cube.speedX, speedY: cube.speedY};
            cube.move();
            const b = box(cube), s = stats[k];
            s.minTop = Math.min(s.minTop, b.top);
            s.minLeft = Math.min(s.minLeft, b.left);
            s.maxRight = Math.max(s.maxRight, b.right);
            for (const o of floors.flatMap(f => f.elements))
                if (o !== cube)
                    s.minGap = Math.min(s.minGap, gap(b, box(o)));
            if (Math.sign(cube.speedX) != Math.sign(before.speedX))
                s.wallReversals++;
            if (before.speedY < 0 && cube.speedY > 0 && b.top <= ceilingBottom + 1)
                s.ceilingBounces++;
        });
    }
    return {width, height, cycles, cyclesPerTick, epsilon: GAMEPLAY.cubeContactEpsilon, initial,
        innerLeftFace: box(leftPillar).right, innerRightFace: box(rightPillar).left,
        ceilingBottom, stats};
}'''


def expected_bounds(width, height, scale_bad, rect):
    x, y, w, h = rect
    sx = width / REFERENCE[0] / scale_bad
    sy = height / REFERENCE[1] / scale_bad
    return {'left': x * sx, 'right': (x + w) * sx, 'top': y * sy, 'bottom': (y + h) * sy}


class Frame12FactoryTests(unittest.TestCase):
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
            row = {'viewport': [width, height], 'types': run['types'],
                   'speeds': run['speeds'], 'elements': {}}
            for (name, rect), actual in zip(SVG.items(), run['bounds']):
                expected = expected_bounds(width, height, run['scaleBad'], rect)
                error = max(abs(expected[k] - actual[k]) for k in expected)
                row['elements'][name] = {'svg': rect, 'expected': expected, 'actual': actual,
                                         'maxError': error}
            rows.append(row)
            print(f"GEOMETRY {width}x{height} " + ' '.join(
                f"{n}.maxError={e['maxError']:.3e}" for n, e in row['elements'].items()),
                flush=True)
        (EVIDENCE / 'geometry.json').write_text(json.dumps(
            {'tolerance': TOLERANCE, 'reference': REFERENCE, 'viewports': rows}, indent=1))
        for row in rows:
            self.assertEqual(row['types'], TYPES)
            for name, element in row['elements'].items():
                self.assertLessEqual(element['maxError'], TOLERANCE, (row['viewport'], name))
            left, right = row['speeds']
            self.assertGreater(left['speedX'], 0)
            self.assertEqual(left['speedX'], -left['speedY'])
            self.assertLess(right['speedX'], 0)
            self.assertEqual(right['speedX'], right['speedY'])

    def test_cubes_bounce_and_stay_trapped(self):
        rows = []
        for width, height in VIEWPORTS:
            run = self.open_bad_game(width, height).evaluate(
                SIMULATE, {'ticks': SECONDS * TICKS_PER_SECOND})
            rows.append(run)
            print(f"MOTION {width}x{height} " + json.dumps(run['stats']), flush=True)
        (EVIDENCE / 'motion.json').write_text(json.dumps(rows, indent=1))
        for run in rows:
            eps = run['epsilon']
            self.assertGreaterEqual(run['cycles'] / run['cyclesPerTick'] / TICKS_PER_SECOND, SECONDS)
            for name, s in zip(['left', 'right'], run['stats']):
                with self.subTest(viewport=(run['width'], run['height']), cube=name):
                    self.assertLessEqual(s['minTop'], run['ceilingBottom'] + eps)
                    self.assertGreaterEqual(s['ceilingBounces'], 2)
                    self.assertGreaterEqual(s['minLeft'], run['innerLeftFace'] - eps)
                    self.assertLessEqual(s['maxRight'], run['innerRightFace'] + eps)
                    self.assertGreaterEqual(s['wallReversals'], 4)
                    self.assertGreaterEqual(s['minGap'], -eps)


if __name__ == '__main__':
    unittest.main()
