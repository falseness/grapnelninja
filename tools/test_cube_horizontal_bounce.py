"""Browser regression for JumpingCube horizontal speed and wall bounces."""
from pathlib import Path
import json
import os
import sys
import unittest

# Allow `python3 -m unittest tools/test_cube_horizontal_bounce.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('CUBE_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-062'))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

# Shared page helpers: bounding box and signed gap between two boxes.
HELPERS = '''() => {
    window.box = e => {
        const p = e.getPoints();
        return {left: Math.min(...p.map(p => p.x)), right: Math.max(...p.map(p => p.x)),
                top: Math.min(...p.map(p => p.y)), bottom: Math.max(...p.map(p => p.y))};
    };
    window.gap = (a, b) => Math.max(b.left - a.right, a.left - b.right,
                                    b.top - a.bottom, a.top - b.bottom);
}'''


class CubeHorizontalBounceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open_bad_game(self):
        page = self.browser.new_page(viewport={'width': 772, 'height': 630})
        self.addCleanup(page.close)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate("startGame('bad'); cancelAnimationFrame(game)")
        page.evaluate(HELPERS)
        return page

    def test_horizontal_speed_bounces_between_walls(self):
        page = self.open_bad_game()
        run = page.evaluate('''() => {
            trackEnabled = true;
            QUALITY.playerTrail = true;
            firstCycleInThisTick = true;
            for (const floor of floors) floor.elements = [];
            const w = 0.05 * height;
            const groundTop = 0.8 * height;
            const leftX = 0.3 * width;
            const gray = (x, y, width, height) => new Rect({x, y, width, height});
            const ground = gray(0, groundTop, width, 0.1 * height);
            const leftWall = gray(leftX - w, groundTop - 5 * w, w, 5 * w);
            const rightWall = gray(leftX + 3 * w, groundTop - 5 * w, w, 5 * w);
            const cube = new JumpingCube({x: leftX + w, y: groundTop - w - 1e-6, width: w, height: w,
                fill: STYLE.colors.cube.blueFill, stroke: STYLE.colors.cube.blueStroke});
            cube.x = leftX + w;
            cube.y = groundTop - w - 1e-6;
            cube.speedX = 0.005 * width;
            cube.speedY = 0;
            floors[1].elements = [ground, leftWall, rightWall, cube];
            const obstacles = {ground, leftWall, rightWall};
            const cycles = [];
            for (let i = 0; i < 700; ++i) {
                const before = {x: cube.x, speedX: cube.speedX};
                cube.move();
                const b = box(cube);
                const gaps = Object.fromEntries(Object.entries(obstacles)
                    .map(([name, e]) => [name, gap(b, box(e))]));
                const trail = cube.track.pos[cube.track.pos.length - 1];
                cycles.push({cycle: i, x: cube.x, y: cube.y, left: b.left, right: b.right,
                    speedX: cube.speedX, speedY: cube.speedY, speedXBefore: before.speedX,
                    dx: cube.x - before.x, gaps, minGap: Math.min(...Object.values(gaps)),
                    trailX: trail.x, trailExpectedX: cube.x + cube.circle.x});
            }
            return {width, height, cubeWidth: w, epsilon: GAMEPLAY.cubeContactEpsilon,
                initialSpeedX: 0.005 * width, walls: {left: box(leftWall).right,
                right: box(rightWall).left}, ground: box(ground).top, cycles};
        }''')
        eps, speed = run['epsilon'], run['initialSpeedX']
        reversals, lines = [], []
        for c in run['cycles']:
            if c['speedX'] == -c['speedXBefore']:
                wall = 'left' if c['speedXBefore'] < 0 else 'right'
                bound = run['walls'][wall]
                touched = c['left'] if wall == 'left' else c['right']
                reversals.append(wall)
                lines.append(f"REVERSAL cycle={c['cycle']} wall={wall} x={c['x']:.9f} "
                             f"left={c['left']:.9f} right={c['right']:.9f} "
                             f"wallBound={bound:.9f} touched={touched:.9f} "
                             f"gap={abs(bound - touched):.3e} speedX {c['speedXBefore']:.9f} "
                             f"-> {c['speedX']:.9f}")
        print('\n' + '\n'.join(lines), flush=True)

        # Invariants asserted by the test and recorded with actual numbers.
        min_gap = min(c['minGap'] for c in run['cycles'])
        speed_error = max(abs(abs(c['speedX']) - speed) for c in run['cycles'])
        free = [c for c in run['cycles'] if c['speedX'] == c['speedXBefore']]
        free_dx_error = max(abs(c['dx'] - c['speedXBefore']) for c in free)
        trail_error = max(abs(c['trailX'] - c['trailExpectedX']) for c in run['cycles'])
        run['assertions'] = {
            'cycles': len(run['cycles']),
            'minGapOverAllCycles': min_gap, 'minGapFloor': -eps,
            'minGapPass': min_gap >= -eps,
            'maxAbsSpeedXError': speed_error, 'speedXTolerance': 1e-9,
            'speedXConstantPass': speed_error <= 1e-9,
            'nonContactCycles': len(free),
            'nonContactMinAbsDx': min(abs(c['dx']) for c in free),
            'nonContactMaxDxError': free_dx_error,
            'nonContactXChangesPass': all(c['dx'] != 0 for c in free) and free_dx_error <= 1e-9,
            'trailMaxXError': trail_error, 'trailFollowsXPass': trail_error <= 1e-9,
            'reversals': len(reversals), 'leftReversals': reversals.count('left'),
            'rightReversals': reversals.count('right'),
        }
        (EVIDENCE / 'trace.json').write_text(json.dumps(run, indent=1))
        print('ASSERTIONS ' + json.dumps(run['assertions']), flush=True)

        self.assertGreaterEqual(len(run['cycles']), 600)
        self.assertGreaterEqual(min_gap, -eps)
        self.assertLessEqual(speed_error, 1e-9)
        self.assertTrue(run['assertions']['nonContactXChangesPass'])
        self.assertLessEqual(trail_error, 1e-9)
        self.assertGreaterEqual(len(reversals), 4)
        self.assertGreaterEqual(reversals.count('left'), 2)
        self.assertGreaterEqual(reversals.count('right'), 2)

    def test_frame_cubes_keep_zero_horizontal_speed(self):
        page = self.open_bad_game()
        result = {}
        for frame in ['frame7Elements', 'frame13Elements']:
            row = page.evaluate('''frame => {
                chooseVersion();
                for (const floor of floors) floor.elements = [];
                floors[1].creations = [{type: frame, chance: 100}];
                floors[1].generatePrimaryElements();
                const cubes = floors[1].elements.filter(e => e instanceof JumpingCube);
                const initial = cubes.map(c => ({x: c.x, speedX: c.speedX}));
                const cycles = [];
                for (let i = 0; i < 300; ++i) {
                    for (const c of cubes) c.move();
                    cycles.push({cycle: i, cubes: cubes.map(c => ({x: c.x, y: c.y,
                        speedX: c.speedX, speedY: c.speedY}))});
                }
                return {cubeCount: cubes.length, initial, cycles};
            }''', frame)
            row['allSpeedXZero'] = all(c['speedX'] == 0 for cy in row['cycles'] for c in cy['cubes'])
            row['xUnchanged'] = all(c['x'] == row['initial'][i]['x']
                                    for cy in row['cycles'] for i, c in enumerate(cy['cubes']))
            row['yRange'] = [max(cy['cubes'][i]['y'] for cy in row['cycles']) -
                             min(cy['cubes'][i]['y'] for cy in row['cycles'])
                             for i in range(row['cubeCount'])]
            result[frame] = row
            print(f"REGRESSION {frame}: cubes={row['cubeCount']} cycles={len(row['cycles'])} "
                  f"speedX===0 every cycle={row['allSpeedXZero']} x unchanged={row['xUnchanged']} "
                  f"yRange={row['yRange']}", flush=True)
        (EVIDENCE / 'regression.json').write_text(json.dumps(result, indent=1))
        for frame, row in result.items():
            self.assertGreaterEqual(row['cubeCount'], 1, frame)
            self.assertGreaterEqual(len(row['cycles']), 300, frame)
            self.assertTrue(row['allSpeedXZero'], frame)
            self.assertTrue(row['xUnchanged'], frame)
            self.assertTrue(all(r > 0 for r in row['yRange']), frame)


if __name__ == '__main__':
    unittest.main()
