"""Momentum Cave Crystal performance gate: HEAD vs BASE (TASK-126).

Scenes: FxHarness mid-shaft and run-right at 1280x720 (FX on) and a dense
placement at 1280x720 and 390x844: M134 on the down->right corner of the
scripted R U R D R course, M04 and M66 right after it in the exit corridor,
the camera centred on all their pieces, the ninja parked far away.

Every run is a fresh page of index.html?perf=1 (render/perfprofile.js)
booted under the frozen clock of momentum_fx_support; once the scene is
built, performance.now is the real clock again (both trees alike), the perf
panel is off. A run draws WARMUP frames, then TIMED draw() calls in chunks
of CHUNK, a PERF_PROFILE.snapshot() after each chunk; the world value of the
run is the median of the snapshots' world meanMs whose 120-frame window lies
inside the timed draws (draws 1-120, 61-180, 121-240, 181-300). Per draw the
tool also times, with the real clock:
  frame        draw() plus a 1 px getImageData (the canvas raster lands in
               the readback, not in the JS spans)
  worldFlushed drawWorldLayer bracketed by 1 px readbacks (the world layer's
               JS plus its raster; the readback before it is not counted)
and takes their medians over the TIMED draws. The control region is the same
on the same page with the pattern and obstacle floors emptied (no crystal
pieces: HEAD and BASE draw the same thing, so its ratio is the VM noise).

HEAD and BASE alternate, RUNS each per scene (H B B H H B ...), a fresh page
each. Ratios are median(HEAD runs) / median(BASE runs). pass = every scene's
worldRatio <= MAX_RATIO and frameRatio <= MAX_RATIO.

    python3 momentum_crystal_perf.py --base BASE --out <perf.json> [--head HEAD]

--base BASE is the parent of the TASK-122 game commit 4c9ba46; --head
defaults to HEAD (a git archive export, so uncommitted edits are not
measured; 'worktree' measures the checkout). Compact JSON; exit status 1
when the gate fails. Requires Playwright Chromium.
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import momentum_fx_support as fxs  # noqa: E402
from perf_mobile import SEED_SCRIPT  # noqa: E402
import render_snapshot  # noqa: E402
from test_momentum_borders import SEED_COURSE  # noqa: E402
from test_momentum_patterns_turn import SCRIPT  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REVS = {'BASE': '4c9ba46~1'}
RUNS = 5
WARMUP = 60
TIMED = 300
CHUNK = 60
WINDOW = 120
MAX_RATIO = 1.05
SCENES = [('mid-shaft', (1280, 720)), ('run-right', (1280, 720)),
          ('dense', (1280, 720)), ('dense', (390, 844))]

# M134 on the down->right corner, M04 and M66 after it in the exit corridor;
# camera on the union of the pieces. Returns the piece count
DENSE = r'''() => {
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor) {
            f.elements = []
            if (f.groups) f.groups = []
        }
    const course = momentumCourse
    let segment = -1
    for (let i = 0; i < 5; ++i)
        if (course.segment(i).dir + '->' + course.segment(i + 1).dir == 'down->right') { segment = i; break }
    const corner = momentumPlaceCorner('M134', segment)
    if (!corner) throw new Error('corner M134')
    const s = course.segment(segment + 1)
    let x = s.x0 + corner.reach.out
    for (const id of ['M04', 'M66']) {
        const r = momentumPlacePattern(id, x, s.y0, 'right')
        if (!r) throw new Error('pattern ' + id)
        x += r.length
    }
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const e of floor.elements) {
        const b = getElementBounds(e)
        x0 = Math.min(x0, b.left); y0 = Math.min(y0, b.top); x1 = Math.max(x1, b.right); y1 = Math.max(y1, b.bottom)
    }
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
    const vw = width / scale[version], vh = height / scale[version]
    screen.x = -(cx - vw / 2); screen.y = -(cy - vh / 2)
    screen.segmentIndex = segment + 1
    screen.leftWall.update(screen)
    for (const f of floors)
        if (f instanceof MomentumBorderFloor)
            f.replenishElements()
    grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
    ninja.x = cx; ninja.y = cy - 1e5; ninja.speedX = ninja.speedY = 0
    ninja.track.pos = []
    if (typeof MOMENTUM_FX != 'undefined')
        MOMENTUM_FX.enabled = true
    return floor.elements.length
}'''

# Real clock from here on, perf panel off, per-draw readback probes
SETUP = r'''() => {
    const real = () => Performance.prototype.now.call(performance)
    performance.now = real
    PERF_OVERLAY.enabled = false
    const probe = canvas.getContext('2d')
    const inner = window.drawWorldLayer
    window.__perf = {world: []}
    window.drawWorldLayer = function() {
        probe.getImageData(0, 0, 1, 1)
        const t0 = real()
        try {
            return inner.apply(this, arguments)
        } finally {
            probe.getImageData(0, 0, 1, 1)
            __perf.world.push(real() - t0)
        }
    }
    window.__perfDraws = n => {
        const frame = []
        __perf.world = []
        for (let i = 0; i < n; ++i) {
            const t0 = real()
            draw()
            probe.getImageData(0, 0, 1, 1)
            frame.push(real() - t0)
        }
        const world = PERF_PROFILE.snapshot().entries.find(e => e.name == 'world')
        return {frame: frame, worldFlushed: __perf.world, worldMean: world.meanMs, worldSamples: world.samples}
    }
}'''

EMPTY = r'''() => {
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor) {
            f.elements = []
            if (f.groups) f.groups = []
        }
}'''

COUNT = '''() => floors.filter(f => f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor)
    .reduce((n, f) => n + f.elements.length, 0)'''


def median(values):
    return statistics.median(values)


def open_perf(fx, viewport):
    """fx.open at index.html?perf=1"""
    w, h = viewport
    touch = h > w
    context = fx.browser.new_context(viewport={'width': w, 'height': h}, is_mobile=touch, has_touch=touch)
    context.add_init_script(SEED_SCRIPT % fxs.SEED)
    context.add_init_script(render_snapshot.CLOCK_SCRIPT)
    fx.patch_context(context)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
    page.goto(fx.url + 'index.html?perf=1', wait_until='load')
    render_snapshot.boot_frozen(page)
    page.evaluate(render_snapshot.SETUP_SCRIPT, [[], touch])
    page.evaluate(SEED_COURSE, SCRIPT)
    page.evaluate("() => startGame('momentum')")
    page.errors = errors
    return context, page


def region(page):
    """WARMUP draws, then TIMED draws in CHUNKs: medians of one region"""
    page.evaluate('n => __perfDraws(n)', WARMUP)
    frame, flushed, world = [], [], []
    for k in range(TIMED // CHUNK):
        r = page.evaluate('n => __perfDraws(n)', CHUNK)
        frame += r['frame']
        flushed += r['worldFlushed']
        done = (k + 1) * CHUNK
        if done >= WINDOW:
            if r['worldSamples'] != WINDOW:
                raise RuntimeError(f'world samples {r["worldSamples"]} != {WINDOW}')
            world.append(r['worldMean'])
    if len(frame) != TIMED or len(flushed) != TIMED:
        raise RuntimeError(f'timed draws {len(frame)} / {len(flushed)} != {TIMED}')
    return {'world': median(world), 'frame': median(frame), 'worldFlushed': median(flushed)}


def run(fx, scene, viewport):
    context, page = open_perf(fx, viewport)
    try:
        if scene == 'dense':
            pieces = page.evaluate(DENSE)
        else:
            page.evaluate(fxs.BUILD, [fxs.SCENE_SPECS[scene], True])
            pieces = page.evaluate(COUNT)
        page.evaluate(SETUP)
        main = region(page)
        page.evaluate(EMPTY)
        if page.evaluate(COUNT) != 0:
            raise RuntimeError('control floors not empty')
        control = region(page)
        if page.errors:
            raise RuntimeError(f'page errors {fx.rev} {scene} {viewport}: {page.errors}')
    finally:
        context.close()
    return pieces, main, control


def r4(v):
    return round(v, 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    base_rev = REVS.get(args.base, args.base)
    head_rev = args.head
    started = time.time()
    tool_rev = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    sides = {'head': fxs.harness(head_rev), 'base': fxs.harness(base_rev)}
    rows = []
    try:
        for scene, viewport in SCENES:
            raw = {side: {'world': [], 'frame': [], 'worldFlushed': [],
                          'controlWorld': [], 'controlFrame': [], 'controlWorldFlushed': []} for side in sides}
            pieces = {}
            for i in range(RUNS):
                # H B, B H, H B, ...: neither side always goes first
                order = ['head', 'base'] if i % 2 == 0 else ['base', 'head']
                for side in order:
                    n, m, c = run(sides[side], scene, viewport)
                    pieces[side] = n
                    for key in ('world', 'frame', 'worldFlushed'):
                        raw[side][key].append(r4(m[key]))
                        raw[side]['control' + key[0].upper() + key[1:]].append(r4(c[key]))
                    print(f'{scene} {viewport[0]}x{viewport[1]} run {i + 1} {side}: world {m["world"]:.3f} '
                          f'frame {m["frame"]:.3f} worldFlushed {m["worldFlushed"]:.3f} | control world '
                          f'{c["world"]:.3f} frame {c["frame"]:.3f} worldFlushed {c["worldFlushed"]:.3f}', flush=True)
            med = {side: {key: r4(median(v)) for key, v in raw[side].items()} for side in sides}
            ratio = {key: r4(med['head'][key] / med['base'][key]) for key in med['head']}
            row = {'scene': scene, 'viewport': f'{viewport[0]}x{viewport[1]}', 'pieces': pieces,
                   'head': raw['head'], 'base': raw['base'], 'medians': med,
                   'worldRatio': ratio['world'], 'frameRatio': ratio['frame'],
                   'worldFlushedRatio': ratio['worldFlushed'], 'controlWorldRatio': ratio['controlWorld'],
                   'controlFrameRatio': ratio['controlFrame'],
                   'controlWorldFlushedRatio': ratio['controlWorldFlushed']}
            row['pass'] = row['worldRatio'] <= MAX_RATIO and row['frameRatio'] <= MAX_RATIO
            rows.append(row)
            print(f'{scene} {row["viewport"]} pieces {pieces["head"]}/{pieces["base"]}: worldRatio {row["worldRatio"]} '
                  f'frameRatio {row["frameRatio"]} worldFlushedRatio {row["worldFlushedRatio"]} | control '
                  f'world {row["controlWorldRatio"]} frame {row["controlFrameRatio"]} worldFlushed '
                  f'{row["controlWorldFlushedRatio"]} -> {"PASS" if row["pass"] else "FAIL"}', flush=True)
    finally:
        head_sha, base_sha = sides['head'].rev, sides['base'].rev
        fxs.close()
    ok = all(r['pass'] for r in rows) and len(rows) == len(SCENES)
    result = {'head': head_sha, 'base': base_sha, 'baseArg': args.base, 'toolRev': tool_rev,
              'runs': RUNS, 'warmup': WARMUP, 'timed': TIMED, 'chunk': CHUNK, 'maxRatio': MAX_RATIO,
              'units': 'ms', 'world': 'PERF_PROFILE world meanMs, median of the in-region 120-frame snapshots',
              'frame': 'draw() + 1 px getImageData, median of the timed draws',
              'worldFlushed': 'drawWorldLayer between 1 px readbacks, median of the timed draws',
              'control': 'same page, pattern/obstacle floors emptied',
              'seconds': round(time.time() - started, 1), 'rows': rows, 'pass': ok}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, separators=(',', ':')))
    print(out, 'head', head_sha, 'base', base_sha, 'pass', ok)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
