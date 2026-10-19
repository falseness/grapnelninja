"""Momentum audit 6/14: hue-rotation time per frame of the depth grade (TASK-093).

BackgroundRenderer.getDepthGrade hue-rotates the far and near tiles per pixel
whenever the depth step changes. The probe ramps scoreText.count.momentum
from 0 to the last depth stage (DRAWS_PER_POINT frames per point; a frame is
the background's paint(), the only caller of getDepthGrade, under a new
drawFrameId, with one full draw() per point; the frozen clock of render_snapshot; times come from the real performance.now
saved before the clock is frozen) and records:
- per hue rotation of a whole tile (hueRotateTile on trees before TASK-093)
  or per tile rotated in bands (HueRotateJob.advance calls, summed per job
  and tile: source reads, rotation and puts): {score (of the last band), hue, ms, w, h, bands,
  maxBandMs, frames};
- per frame the time spent in getDepthGrade (all hue rotation, whole tiles or
  bands, runs inside it) and the depthGrade.rebuilds count over the ramp.
The ramp runs RUNS times per viewport, each on a fresh page, run r after
r * PHASE_DRAWS extra draw() calls at score 0; a frame's time is its median
over the runs. A pause of the shared machine (another process) lands in one
run; a garbage collection is set off by the whole game's allocations, the
same in every run, and the extra draws move it to other frames of the ramp;
a spike of the code itself is in every run at the same frame.
maxFrameMs/framesOverBudget come from the medians, maxFrameMsPerRun/
framesOverBudgetPerRun from each run's own times; rotations are the first
run's.
Viewports 844x390@3 and 1280x720@1. DRAWS_PER_POINT 16 is about 3.75 points
per second at 60 fps, three times the fastest pace of the seeded run in
artifacts/TASK-041/run-trace.json (40 points in 60 s, at most 5 per 4 s).

Usage: python3 momentum_depth_grade_perf_probe.py REV OUT.json
(REV 'worktree' or a git revision)
"""
import json
import statistics
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
import render_snapshot

VIEWPORTS = [(844, 390, 3), (1280, 720, 1)]
DRAWS_PER_POINT = 16
BUDGET_MS = 4
RUNS = 3
PHASE_DRAWS = 3

REAL_CLOCK_SCRIPT = 'window.__realNow = performance.now.bind(performance)'

PROBE = r'''([drawsPerPoint, budget, phaseDraws]) => {
    const now = window.__realNow
    for (let i = 0; i < phaseDraws; ++i) {
        scoreText.count.momentum = 0
        draw()
    }
    const bg = visualEffects.background, grade = bg.depthGrade
    const stages = STYLE.momentumFx.depthStages, last = stages[stages.length - 1].score
    const rotations = []
    let score = 0
    if (typeof hueRotateTile == 'function') {
        const original = hueRotateTile
        window.hueRotateTile = (layer, deg) => {
            const t0 = now()
            const tile = original(layer, deg)
            rotations.push({score, hue: Math.round(deg * 1000) / 1000, ms: Math.round((now() - t0) * 100) / 100,
                            w: layer.canvas.width, h: layer.canvas.height})
            return tile
        }
    }
    if (typeof HueRotateJob == 'function') {
        const advance = HueRotateJob.prototype.advance, open = new Map()
        let frame = 0
        window.__bandFrame = () => ++frame
        HueRotateJob.prototype.advance = function(pixels) {
            if (this.done) return advance.call(this, pixels)
            const tile = this.tile, t0 = now()
            advance.call(this, pixels)
            const ms = now() - t0
            if (!open.has(this)) open.set(this, [])
            const records = open.get(this)
            if (!records[tile]) {
                const source = this.sources[tile].canvas
                records[tile] = {score, hue: this.hue, ms: 0, w: source.width, h: source.height,
                                 bands: 0, maxBandMs: 0, frames: new Set()}
                rotations.push(records[tile])
            }
            const r = records[tile]
            r.score = score; r.ms += ms; ++r.bands; r.maxBandMs = Math.max(r.maxBandMs, ms); r.frames.add(frame)
        }
    }
    const proto = Object.getPrototypeOf(bg), getDepthGrade = proto.getDepthGrade
    let frameMs = 0
    bg.getDepthGrade = function(...args) {
        const t0 = now()
        try { return getDepthGrade.apply(this, args) } finally { frameMs += now() - t0 }
    }
    const start = grade.rebuilds, hues = new Set()
    const times = []
    for (score = 0; score <= last; ++score)
        for (let k = 0; k < drawsPerPoint; ++k) {
            scoreText.count.momentum = score
            frameMs = 0
            if (window.__bandFrame) window.__bandFrame()
            if (k == 0) draw()
            else { ++drawFrameId; bg.paint() }
            const hue = bg.getDepthHue(score)
            if (hue) hues.add(hue)
            times.push(Math.round(frameMs * 100) / 100)
        }
    delete bg.getDepthGrade
    for (const r of rotations) {
        r.ms = Math.round(r.ms * 100) / 100
        if (r.frames) { r.maxBandMs = Math.round(r.maxBandMs * 100) / 100; r.frames = r.frames.size }
    }
    const far = bg.layerCache.farBaked, near = bg.layerCache.near
    return {logical: [LOGICAL_VIEWPORT.width, LOGICAL_VIEWPORT.height], canvas: [canvas.width, canvas.height],
            tiles: {far: [far.canvas.width, far.canvas.height], near: [near.canvas.width, near.canvas.height]},
            rampFrom: 0, rampTo: last, drawsPerPoint, frames: times.length, distinctSteps: hues.size,
            rebuilds: grade.rebuilds - start, rotations,
            rotationMsTotal: Math.round(rotations.reduce((s, r) => s + r.ms, 0) * 100) / 100, times}
}'''


def open_page(tree, w, h, dpr):
    touch = dpr > 1
    context = tree.browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=dpr,
                                       is_mobile=touch, has_touch=touch)
    context.add_init_script(REAL_CLOCK_SCRIPT)
    context.add_init_script(fx.SEED_SCRIPT % fx.SEED)
    context.add_init_script(render_snapshot.CLOCK_SCRIPT)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(tree.url + 'index.html', wait_until='load')
    render_snapshot.boot_frozen(page)
    page.evaluate(render_snapshot.SETUP_SCRIPT, [[], touch])
    page.evaluate(fx.SEED_COURSE, fx.SCRIPT)
    page.evaluate("() => { startGame('momentum'); cancelAnimationFrame(game) }")
    page.errors = errors
    return context, page


def main(rev, out):
    tree = fx.harness(rev)
    runs = []
    try:
        for w, h, dpr in VIEWPORTS:
            ramps = []
            for run in range(RUNS):
                context, page = open_page(tree, w, h, dpr)
                try:
                    ramps.append(page.evaluate(PROBE, [DRAWS_PER_POINT, BUDGET_MS, run * PHASE_DRAWS]))
                    if page.errors:
                        raise RuntimeError(f'page errors: {page.errors}')
                finally:
                    context.close()
            row = {'viewport': f'{w}x{h}@{dpr}', **{k: v for k, v in ramps[0].items() if k != 'times'}}
            frames = [(score, k) for score in range(row['rampFrom'], row['rampTo'] + 1)
                      for k in range(DRAWS_PER_POINT)]
            median = [round(statistics.median(ms), 2) for ms in zip(*(r['times'] for r in ramps))]
            worst = max(range(len(median)), key=median.__getitem__)
            over = [{'score': frames[i][0], 'draw': frames[i][1], 'ms': median[i],
                     'runs': [r['times'][i] for r in ramps]} for i in range(len(median)) if median[i] > BUDGET_MS]
            row.update(runs=RUNS, phaseDraws=[run * PHASE_DRAWS for run in range(RUNS)], budgetMs=BUDGET_MS, maxFrameMs=median[worst], maxFrameScore=frames[worst][0],
                       framesOverBudget=len(over), overBudget=over[:40],
                       maxFrameMsPerRun=[max(r['times']) for r in ramps],
                       framesOverBudgetPerRun=[sum(t > BUDGET_MS for t in r['times']) for r in ramps],
                       rebuildsPerRun=[r['rebuilds'] for r in ramps])
            print(rev, {k: v for k, v in row.items() if k not in ('rotations', 'overBudget')})
            runs.append(row)
    finally:
        fx.close()
    result = {'rev': tree.rev, 'runs': runs}
    Path(out).write_text(json.dumps(result, separators=(',', ':')))
    return result


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
