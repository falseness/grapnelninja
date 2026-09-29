"""Browser regression for grapnel points tethered to moving blue cubes."""
from pathlib import Path
import json
import math
import os
import sys
import unittest

# Allow `python3 -m unittest tools/test_grapnel_moving_cube.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('GRAPNEL_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-063'))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

CYCLES = 700

# TASK-062 two-wall scenario. The rope is attached through the real
# Grapnel.collision()/grapple() path, then each cycle runs the element, grapnel
# and pull steps of calcPhysics() with the ninja held still.
SCENARIO = '''({wraps, cycles}) => {
    const box = e => {
        const p = e.getPoints();
        return {left: Math.min(...p.map(p => p.x)), right: Math.max(...p.map(p => p.x)),
                top: Math.min(...p.map(p => p.y)), bottom: Math.max(...p.map(p => p.y))};
    };
    // Distance from a point to the rectangle outline (inside or outside).
    const outlineDistance = (x, y, b) => {
        if (x >= b.left && x <= b.right && y >= b.top && y <= b.bottom)
            return Math.min(x - b.left, b.right - x, y - b.top, b.bottom - y);
        return Math.hypot(Math.max(b.left - x, 0, x - b.right), Math.max(b.top - y, 0, y - b.bottom));
    };
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

    // Hook tip just inside the cube's top-left corner; the rope from the
    // ninja above crosses the top edge and snaps to that corner.
    const rest = {x: leftX + 1.5 * w, y: groundTop - 8 * w};
    ninja.x = rest.x;
    ninja.y = rest.y;
    grapnel.pos = [[cube.x + 1, cube.y + 1, new Empty()]];
    grapnel.speedX = 0;
    grapnel.speedY = 0;
    grapnel.throwed = true;
    grapnel.setGrappled(false);
    grapnel.collision();
    const attach = {afterHook: grapnel.pos.map(p => [p[0], p[1], p[2].constructor.name])};
    if (wraps) {
        // Swing the ninja just below the top edge on the right: the rope
        // crosses the right edge next to the top-right corner and wraps it.
        ninja.x = cube.x + 1.8 * w;
        ninja.y = cube.y + 2;
        grapnel.collision();
        attach.afterWrap = grapnel.pos.map(p => [p[0], p[1], p[2].constructor.name]);
        ninja.x = rest.x;
        ninja.y = rest.y;
    }
    attach.corners = cube.getPoints();

    const trace = [];
    for (let i = 0; i < cycles; ++i) {
        firstCycleInThisTick = i % cyclesPerTick == cyclesPerTick - 1;
        const speedXBefore = cube.speedX;
        for (const floor of floors) floor.moveElements();
        grapnel.move();
        const last = grapnel.pos[grapnel.pos.length - 1];
        const ratio = grapnel.isGrappled() ? grapnel.calcSpeed({x: last[0], y: last[1]}) : null;
        grapnel.collision();
        const b = box(cube);
        trace.push({cycle: i, cube: b, x: cube.x, y: cube.y, speedX: cube.speedX,
            speedY: cube.speedY, speedXBefore, bounce: cube.speedX == -speedXBefore,
            ninja: {x: ninja.x, y: ninja.y}, pullTarget: {x: last[0], y: last[1]}, ratio,
            points: grapnel.pos.map(p => ({x: p[0], y: p[1], type: p[2].constructor.name,
                onCube: p[2] === cube,
                cubeDistance: p[2] === cube ? outlineDistance(p[0], p[1], b) : null}))});
    }
    return {width, height, cubeWidth: w, tolerance: screenHeightPercent(GAMEPLAY.cornerToleranceHeightPercent),
        walls: {left: box(leftWall).right, right: box(rightWall).left}, attach, trace};
}'''

# Pre-change Grapnel.move tether step (y += element.speedY after move) runs on
# a copy of the tethered points next to the real grapnel.move().
REGRESSION = '''({kind, cycles}) => {
    chooseVersion();
    for (const floor of floors) floor.elements = [];
    let element;
    if (kind == 'frame7Elements') {
        floors[1].creations = [{type: kind, chance: 100}];
        floors[1].generatePrimaryElements();
        element = floors[1].elements.find(e => e instanceof JumpingCube);
    } else {
        element = new Triangle({x: 0.5 * width, y: 0.5 * height, radius: 0.04 * height,
            yMin: 0.3 * height, yMax: 0.7 * height, fill: STYLE.colors.hazard.hazardFill,
            stroke: STYLE.colors.hazard.hazardStroke});
        floors[1].elements = [element];
    }
    const corners = element.getPoints();
    grapnel.pos = corners.map(p => [p.x, p.y, element]);
    grapnel.speedX = 0;
    grapnel.speedY = 0;
    grapnel.throwed = true;
    const old = grapnel.pos.map(p => [p[0], p[1]]);
    const offsets = corners.map(p => [p.x - element.x, p.y - element.y]);
    const trace = [];
    let firstBounce = null;
    for (let i = 0; i < cycles; ++i) {
        const before = {x: element.x, y: element.y, speedY: element.speedY};
        for (const floor of floors) floor.moveElements();
        grapnel.move();
        for (const p of old) p[1] += element.speedY;
        const actualDy = element.y - before.y;
        // JumpingCube reverses speedY on contact; the old path then used
        // the post-bounce speed instead of the actual displacement.
        const bounce = element instanceof JumpingCube && element.speedY != before.speedY + GRAVITY;
        if (bounce && firstBounce === null) firstBounce = i;
        trace.push({cycle: i, x: element.x, y: element.y, speedY: element.speedY, actualDy, bounce,
            points: grapnel.pos.map(p => [p[0], p[1]]), oldPoints: old.map(p => [p[0], p[1]]),
            anchorError: Math.max(...grapnel.pos.map((p, k) =>
                Math.hypot(p[0] - element.x - offsets[k][0], p[1] - element.y - offsets[k][1])))});
    }
    return {kind, type: element.constructor.name, firstBounce, trace};
}'''


class GrapnelMovingCubeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.traces = {}
        cls.regression = {}

    @classmethod
    def tearDownClass(cls):
        if cls.traces:
            (EVIDENCE / 'tether-trace.json').write_text(json.dumps(cls.traces, indent=1))
        if cls.regression:
            (EVIDENCE / 'regression.json').write_text(json.dumps(cls.regression, indent=1))

    def open_bad_game(self):
        page = self.browser.new_page(viewport={'width': 772, 'height': 630})
        self.addCleanup(page.close)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url)
        page.evaluate("startGame('bad'); cancelAnimationFrame(game)")
        return page

    def run_tether(self, name, wraps):
        run = self.open_bad_game().evaluate(SCENARIO, {'wraps': wraps, 'cycles': CYCLES})
        trace, tol = run['trace'], run['tolerance']
        bounces = [c['cycle'] for c in trace if c['bounce']]
        distances = [p['cubeDistance'] for c in trace for p in c['points'] if p['onCube']]
        cube_counts = [sum(p['onCube'] for p in c['points']) for c in trace]
        around = sorted({i for b in bounces for i in (b - 1, b, b + 1) if 0 <= i < len(trace)})
        pull_error = 0.0
        for c in trace:
            dx = c['pullTarget']['x'] - c['ninja']['x']
            dy = c['pullTarget']['y'] - c['ninja']['y']
            d = math.hypot(dx, dy)
            pull_error = max(pull_error, abs(c['ratio']['cos'] - dx / d),
                             abs(c['ratio']['sin'] - dy / d))
        run['assertions'] = {
            'cycles': len(trace),
            'bounceCycles': bounces,
            'bounceCount': len(bounces),
            'maxCubeDistance': max(distances),
            'maxCubeDistanceAroundBounces': max(p['cubeDistance'] for i in around
                                                for p in trace[i]['points'] if p['onCube']),
            'aroundBounceCycles': around,
            'tolerance': tol,
            'minCubeTetheredPoints': min(cube_counts),
            'maxCubeTetheredPoints': max(cube_counts),
            'pullDirectionMaxError': pull_error,
            'cubeXRange': [min(c['x'] for c in trace), max(c['x'] for c in trace)],
        }
        self.traces[name] = run
        print(f"{name.upper()} " + json.dumps(run['attach']), flush=True)
        print(f"{name.upper()} ASSERTIONS " + json.dumps(run['assertions']), flush=True)
        for b in bounces:
            window = {i: [round(p['cubeDistance'], 12) for p in trace[i]['points'] if p['onCube']]
                      for i in (b - 1, b, b + 1) if 0 <= i < len(trace)}
            print(f"{name.upper()} BOUNCE cycle={b} speedX {trace[b]['speedXBefore']:.6f} -> "
                  f"{trace[b]['speedX']:.6f} cubeDistances(before/at/after)={window}", flush=True)

        self.assertGreaterEqual(len(trace), 600)
        self.assertGreaterEqual(len(bounces), 2)
        self.assertLessEqual(max(distances), tol)
        self.assertLessEqual(pull_error, 1e-9)
        return run

    def test_single_point_tether_follows_horizontal_cube(self):
        run = self.run_tether('single', wraps=False)
        self.assertEqual(run['attach']['afterHook'][0][2], 'JumpingCube')
        self.assertEqual(run['assertions']['minCubeTetheredPoints'], 1)

    def test_multi_point_tether_follows_horizontal_cube(self):
        run = self.run_tether('multi', wraps=True)
        self.assertGreaterEqual(sum(p[2] == 'JumpingCube' for p in run['attach']['afterWrap']), 2)
        self.assertGreaterEqual(run['assertions']['minCubeTetheredPoints'], 2)

    def test_vertical_cube_and_triangle_unchanged(self):
        page = self.open_bad_game()
        for kind in ['frame7Elements', 'triangle']:
            row = page.evaluate(REGRESSION, {'kind': kind, 'cycles': 300})
            trace = row['trace']
            # Compare with the old path up to the first cube bounce; after it
            # the old path is the defect this task fixes.
            end = row['firstBounce'] if row['firstBounce'] is not None else len(trace)
            deviation = max((abs(a - b) for c in trace[:end]
                             for p, q in zip(c['points'], c['oldPoints']) for a, b in zip(p, q)),
                            default=0.0)
            row['summary'] = {
                'type': row['type'], 'cycles': len(trace), 'comparedCycles': end,
                'firstBounce': row['firstBounce'],
                'maxDeviationFromPreChange': deviation,
                'maxAnchorErrorAllCycles': max(c['anchorError'] for c in trace),
                'yRange': max(c['y'] for c in trace) - min(c['y'] for c in trace),
                'speedYSignChanges': sum((a['speedY'] > 0) != (b['speedY'] > 0)
                                         for a, b in zip(trace, trace[1:])),
            }
            self.regression[kind] = row
            print(f"REGRESSION {kind} " + json.dumps(row['summary']), flush=True)
            self.assertEqual(row['type'], 'JumpingCube' if kind == 'frame7Elements' else 'Triangle')
            self.assertGreaterEqual(end, 30, kind)
            self.assertGreater(row['summary']['yRange'], 0, kind)
            self.assertLessEqual(deviation, 1e-6, kind)
            self.assertLessEqual(row['summary']['maxAnchorErrorAllCycles'], 1e-6, kind)


if __name__ == '__main__':
    unittest.main()
