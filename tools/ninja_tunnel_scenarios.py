"""Reproduce the ninja (ball) passing through bouncy surfaces.

Runs scenarios A-H in 'classic' and 'bad' with hand-built or factory
elements and steps physics with the per-cycle code of calcPhysics()
(gravity, floors[i].moveElements(), ninja.move()). Screen, grapnel and
element replenish/delete are not run, so the scene stays fixed.

Tunnel (checked every cycle): the ball centre is strictly inside a bouncy
polygon, or the centre path of this cycle (previous -> current centre,
no reflection can happen in between) properly crosses a bouncy edge, so
the centre ends on the other side of that line within the segment's span.

Usage: python3 tools/ninja_tunnel_scenarios.py [--out FILE] [--fuzz-runs N]
"""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test


ROOT = Path(__file__).resolve().parents[1]
MODES = ['classic', 'bad']
SCENARIOS = {
    'A': 'fall at maxSpeed onto a flat Trampoline, 16 phases',
    'B': 'speedX = 5x maxSpeed into a vertical Trampoline edge, 16 phases',
    'C': 'two Trampolines sharing an edge, landing on the seam',
    'D': 'ball resting on a flat Trampoline under gravity, 2000 cycles',
    'E': 'bad only: fast upward hit on the ceiling Side boundary, 16 phases',
    'F': 'fast hit on a sloped Trampoline edge, 16 phases',
    'G': 'hit exactly on a Trampoline vertex',
    'H': 'seeded fuzz at Trampolines of real factory frames',
}
FRAMES = {
    'classic': ['trampoline', 'twoTrampolines'],
    'bad': ['frame1Elements', 'frame4Elements', 'frame7Elements', 'frame8Elements',
            'frame10Elements', 'frame11Elements', 'frame12Elements', 'frame13Elements'],
}

# Page-side harness: installs window.tunnel with setup/step/check helpers.
HARNESS = r'''() => {
    const T = window.tunnel = {};
    T.deaths = 0;
    T.borderDeaths = 0;
    // Deadly hits and the deletion border must not rebuild the scene.
    reStart = () => {
        T.deaths++;
        if (ninja.x + screen.x < screen.getDeletionBorder()) T.borderDeaths++;
    };
    T.maxSpeed = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent);
    T.r = ninja.radius;
    T.clear = () => {
        trackEnabled = false;
        firstCycleInThisTick = false;
        for (const floor of floors) floor.elements = [];
    };
    T.tramp = (x, y, pts) => new Trampoline({x, y, points: pts.map(([px, py]) => ({x: px, y: py}))});
    // Axis-aligned Trampoline with top-left (x, y), like the factory point order.
    T.box = (x, y, w, h) => T.tramp(x, y + h, [[0, 0], [0, -h], [w, -h], [w, 0]]);
    T.bouncy = () => {
        const res = [];
        for (const floor of floors) for (const e of floor.elements) {
            if (e instanceof Trampoline) res.push(e);
            else if (e instanceof Side && version == 'bad' && e.y < height / 2) res.push(e);
        }
        return res;
    };
    T.place = (x, y, vx, vy) => {
        ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy;
        T.deaths = 0;
        T.borderDeaths = 0;
    };
    const cross = (ax, ay, bx, by, cx, cy) => (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    const eps = 1e-9;
    T.inside = (px, py, pts) => {
        let inside = false;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            const a = pts[j], b = pts[i];
            const len = Math.hypot(b.x - a.x, b.y - a.y);
            const t = ((px - a.x) * (b.x - a.x) + (py - a.y) * (b.y - a.y)) / (len * len);
            const d = Math.abs(cross(a.x, a.y, b.x, b.y, px, py)) / len;
            if (t >= 0 && t <= 1 && d <= eps) return false;   // on the boundary
            if ((a.y > py) != (b.y > py) && px < (b.x - a.x) * (py - a.y) / (b.y - a.y) + a.x)
                inside = !inside;
        }
        return inside;
    };
    // Proper crossing of path p->q with edge a->b (strict on both sides).
    T.crosses = (p, q, a, b) => {
        const d1 = cross(a.x, a.y, b.x, b.y, p.x, p.y), d2 = cross(a.x, a.y, b.x, b.y, q.x, q.y);
        const d3 = cross(p.x, p.y, q.x, q.y, a.x, a.y), d4 = cross(p.x, p.y, q.x, q.y, b.x, b.y);
        return d1 * d2 < 0 && d3 * d4 < 0;
    };
    T.check = (prev, bouncy) => {
        const cur = {x: ninja.x, y: ninja.y};
        for (const e of bouncy) {
            const pts = e.getPoints();
            if (T.inside(cur.x, cur.y, pts))
                return {kind: 'inside', element: e.constructor.name};
            for (let i = 0; i < pts.length; ++i) {
                const a = pts[i], b = pts[(i + 1) % pts.length];
                if (T.crosses(prev, cur, a, b))
                    return {kind: 'crossed', element: e.constructor.name,
                            edge: [a.x, a.y, b.x, b.y]};
            }
        }
        return null;
    };
    // One physics cycle, the same order as calcPhysics(); records lines hit.
    T.cycle = () => {
        const hits = [];
        const all = [];
        for (const floor of floors) for (const e of floor.elements) all.push(e);
        for (const e of all) {
            const orig = e.collision;
            e.collision = function(who, line) {
                hits.push({element: e.constructor.name, type: line.type,
                           x1: line.x1, y1: line.y1, x2: line.x2, y2: line.y2});
                return orig.call(this, who, line);
            };
        }
        ninja.speedY += GRAVITY;
        for (let i = 0; i < floors.length; ++i) floors[i].moveElements();
        ninja.move();
        for (const e of all) delete e.collision;
        return hits;
    };
    // Run one launch; returns {tunnel, trace, died}.
    T.run = (cycles, keep) => {
        const bouncy = T.bouncy();
        const trace = [];
        let prev = {x: ninja.x, y: ninja.y};
        const start = T.check({x: ninja.x, y: ninja.y}, bouncy);
        if (start) return {invalidStart: start};
        for (let c = 0; c < cycles; ++c) {
            const hits = T.cycle();
            trace.push({cycle: c, x: ninja.x, y: ninja.y, speedX: ninja.speedX,
                        speedY: ninja.speedY, lines: hits});
            if (trace.length > keep) trace.shift();
            if (T.deaths) return {tunnel: null, died: true, border: T.borderDeaths > 0, trace};
            const t = T.check(prev, bouncy);
            if (t) return {tunnel: Object.assign({cycle: c, from: prev}, t), trace};
            prev = {x: ninja.x, y: ninja.y};
        }
        return {tunnel: null, trace};
    };
    T.summary = (name, results) => {
        const valid = results.filter(r => !r.invalidStart);
        const first = valid.find(r => r.tunnel);
        return {scenario: name, runs: valid.length,
                tunnels: valid.filter(r => r.tunnel).length,
                deaths: valid.filter(r => r.died).length,
                borderDeaths: valid.filter(r => r.border).length,
                invalidStarts: results.length - valid.length,
                firstTunnel: first ? {run: results.indexOf(first), tunnel: first.tunnel,
                                      trace: first.trace} : null};
    };
}'''

SCENARIO_JS = {
    # Fall at maxSpeed onto a flat top; phases spread over one cycle's displacement.
    'A': r'''() => {
        const T = tunnel, v = T.maxSpeed, r = T.r, res = [];
        const top = 0.6 * height, x0 = 0.5 * width;
        for (let k = 0; k < 16; ++k) {
            T.clear();
            floors[1].elements = [T.box(0.4 * width, top, 0.2 * width, 0.15 * height)];
            T.place(x0, top - r - 6 * v - k * v / 16, 0, v - GRAVITY);
            res.push(T.run(60, 80));
        }
        return T.summary('A', res);
    }''',
    'B': r'''() => {
        const T = tunnel, v = 5 * T.maxSpeed, r = T.r, res = [];
        const left = 0.5 * width, w = 0.05 * height;
        for (let k = 0; k < 16; ++k) {
            T.clear();
            floors[1].elements = [T.box(left, 0.3 * height, w, 0.4 * height)];
            T.place(left - r - 3 * v - k * v / 16, 0.5 * height, v, 0);
            res.push(T.run(12, 40));
        }
        return T.summary('B', res);
    }''',
    'C': r'''() => {
        const T = tunnel, v = T.maxSpeed, r = T.r, res = [];
        const top = 0.6 * height, seam = 0.5 * width;
        const offsets = [0, 0.25, 0.5, -0.25, -0.5, 1e-6, -1e-6, 0.1];
        for (const dx of offsets) for (const k of [0, 5, 11]) {
            T.clear();
            floors[1].elements = [T.box(seam - 0.1 * width, top, 0.1 * width, 0.15 * height),
                                  T.box(seam, top, 0.1 * width, 0.15 * height)];
            T.place(seam + dx * r, top - r - 6 * v - k * v / 16, 0, v - GRAVITY);
            res.push(T.run(60, 80));
        }
        return T.summary('C', res);
    }''',
    'D': r'''() => {
        const T = tunnel, r = T.r, res = [];
        const top = 0.6 * height;
        for (const gap of [0, 1e-6, 0.5]) {
            T.clear();
            floors[1].elements = [T.box(0.4 * width, top, 0.2 * width, 0.15 * height)];
            T.place(0.5 * width, top - r - gap, 0, 0);
            res.push(T.run(2000, 40));
        }
        return T.summary('D', res);
    }''',
    'E': r'''() => {
        const T = tunnel, v = T.maxSpeed, r = T.r, res = [];
        const side = new Side({x: 0, y: 0, width: 4 * width, height: 0.2 * height,
            fill: STYLE.colors.ground.fill, stroke: STYLE.colors.ground.stroke});
        const ceil = side.y + side.height;
        for (let k = 0; k < 16; ++k) {
            T.clear();
            floors[2].elements = [side];
            T.place(0.5 * width, ceil + r + 6 * v + k * v / 16, 0.3 * v, -v);
            res.push(T.run(60, 80));
        }
        return T.summary('E', res);
    }''',
    'F': r'''() => {
        const T = tunnel, v = T.maxSpeed, r = T.r, res = [];
        // Parallelogram, top edge rising to the right with slope -0.5 (screen y down).
        const w = 0.2 * width, s = 0.5 * w, t = 0.15 * height, x = 0.4 * width, y = 0.7 * height;
        for (let k = 0; k < 16; ++k) {
            T.clear();
            const tr = T.tramp(x, y, [[0, 0], [0, -t], [w, -t - s], [w, -s]]);
            floors[1].elements = [tr];
            const cx = x + 0.5 * w, top = y - t - 0.5 * s;
            T.place(cx - 3 * v - k * v / 16, top - r - 6 * v - k * v / 16, v, v - GRAVITY);
            res.push(T.run(60, 80));
        }
        return T.summary('F', res);
    }''',
    'G': r'''() => {
        const T = tunnel, v = T.maxSpeed, r = T.r, res = [];
        const top = 0.6 * height, x = 0.4 * width;
        const dirs = [[0, 1], [1, 1], [-1, 1], [1, 0.5], [0.5, 1], [1, 0], [-1, 0.5], [1, -1]];
        for (const [dx, dy] of dirs) for (const k of [0, 5, 11]) {
            T.clear();
            floors[1].elements = [T.box(x, top, 0.2 * width, 0.15 * height)];
            const n = Math.hypot(dx, dy), vx = v * dx / n, vy = v * dy / n;
            // Aim the centre straight at the top-left vertex (x, top).
            const steps = 6 + k / 16;
            T.place(x - vx * steps, top - vy * steps, vx, vy - GRAVITY);
            res.push(T.run(60, 80));
        }
        return T.summary('G', res);
    }''',
    'H': r'''([frames, runs, seed]) => {
        const T = tunnel, res = [];
        let s = seed >>> 0;
        const rnd = () => {   // mulberry32
            s = (s + 0x6D2B79F5) >>> 0;
            let t = s;
            t = Math.imul(t ^ (t >>> 15), t | 1);
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
        const saved = random;
        random = (min, max) => (min === undefined ? rnd() : min + rnd() * (max - min));
        try {
            // Launches that start inside a bouncy polygon are resampled.
            for (let i = 0, valid = 0; valid < runs && i < 4 * runs; ++i) {
                const frame = frames[valid % frames.length];
                T.clear();
                floors[1].creations = [{type: frame, chance: 100}];
                floors[1].generatePrimaryElements();
                const tramps = floors[1].elements.filter(e => e instanceof Trampoline);
                const tr = tramps[Math.floor(rnd() * tramps.length)];
                const pts = tr.getPoints();
                const e = Math.floor(rnd() * pts.length);
                const a = pts[e], b = pts[(e + 1) % pts.length], u = 0.05 + 0.9 * rnd();
                const hx = a.x + u * (b.x - a.x), hy = a.y + u * (b.y - a.y);
                const vx = (2 * rnd() - 1) * 5 * T.maxSpeed, vy = (2 * rnd() - 1) * T.maxSpeed;
                const steps = 3 + 4 * rnd();
                T.place(hx - vx * steps, hy - vy * steps, vx, vy - GRAVITY);
                const r = T.run(20, 30);
                r.frame = frame;
                res.push(r);
                if (!r.invalidStart) ++valid;
            }
        } finally {
            random = saved;
        }
        const out = T.summary('H', res);
        out.frames = frames;
        out.seed = seed;
        return out;
    }''',
}


def open_page(browser, url, mode):
    page = browser.new_page(viewport={'width': 772, 'height': 630})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.goto(url)
    page.evaluate(f"startGame('{mode}'); cancelAnimationFrame(game)")
    page.evaluate(HARNESS)
    return page, errors


def run_scenario(browser, url, name, mode, fuzz_runs=1000, seed=153):
    """Return the summary dict for one scenario in one mode (None if n/a)."""
    if name == 'E' and mode != 'bad':
        return None
    page, errors = open_page(browser, url, mode)
    try:
        if name == 'H':
            out = page.evaluate(SCENARIO_JS[name], [FRAMES[mode], fuzz_runs, seed])
        else:
            out = page.evaluate(SCENARIO_JS[name])
    finally:
        page.close()
    out['mode'] = mode
    out['description'] = SCENARIOS[name]
    out['pageErrors'] = errors
    return out


def format_trace(row):
    ft = row['firstTunnel']
    lines = [f"  first tunnel: run={ft['run']} {json.dumps(ft['tunnel'])}"]
    for c in ft['trace'][-12:]:
        hit = ','.join(f"{h['element']}:{h['type']}({h['x1']:.2f},{h['y1']:.2f})-"
                       f"({h['x2']:.2f},{h['y2']:.2f})" for h in c['lines']) or '-'
        lines.append(f"    cycle={c['cycle']} x={c['x']:.4f} y={c['y']:.4f} "
                     f"speedX={c['speedX']:.4f} speedY={c['speedY']:.4f} lines={hit}")
    return '\n'.join(lines)


class _Cleanup:
    def __init__(self):
        self.stack = []

    def __call__(self, fn, *args):
        self.stack.append((fn, args))

    def run(self):
        while self.stack:
            fn, args = self.stack.pop()
            fn(*args)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default=None)
    parser.add_argument('--fuzz-runs', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=153)
    args = parser.parse_args()
    cleanup = _Cleanup()
    try:
        url, browser = start_browser_test(ROOT, cleanup)
        results = {}
        for name in SCENARIOS:
            for mode in MODES:
                row = run_scenario(browser, url, name, mode, args.fuzz_runs, args.seed)
                if row is None:
                    continue
                results[f'{name}/{mode}'] = row
                print(f"SCENARIO {name} mode={mode} runs={row['runs']} tunnels={row['tunnels']} "
                      f"deaths={row['deaths']} borderDeaths={row['borderDeaths']} invalidStarts={row['invalidStarts']} "
                      f"pageErrors={len(row['pageErrors'])} :: {row['description']}", flush=True)
                if row['firstTunnel']:
                    print(format_trace(row), flush=True)
    finally:
        cleanup.run()
    failing = sorted(k for k, r in results.items() if r['tunnels'] > 0)
    print('FAILING ' + json.dumps(failing), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps({'scenarios': results, 'failing': failing}, indent=1))


if __name__ == '__main__':
    main()
