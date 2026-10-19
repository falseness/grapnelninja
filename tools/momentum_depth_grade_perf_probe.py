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
  bands, runs inside it) less the layer tile repaints it set off (a new
  pixel scale; getLayerTile cache misses, reported apart as builds), and the
  depthGrade.rebuilds count over the ramp.
The ramp runs RUNS times per viewport, each on a fresh page, run r after
r * PHASE_DRAWS extra draw() calls at score 0. TOGGLE_RUNS more runs paint
every frame through BACKDROP.begin/end (as render/draw.js does) and switch
the fast backdrop (BACKDROP.scale, which rebuilds the far/near tiles at a new
pixel scale) at the TOGGLES scores; they record per switch the frames until
the graded tiles drawn are the new scale's (deferred) and the hue rotation
time of the switch frame and the frames after it. Every frame runs in its
own task (a MessageChannel message: the frozen clock holds timers), so a
worker's replies arrive between frames as between rAF frames.
maxFrameMs/framesOverBudget are the slowest frame and the count over
BUDGET_MS across every frame of every run (no aggregation over runs);
maxFrameMsPerRun/framesOverBudgetPerRun per run; overBudget lists the slow
frames with their run; rotations are the first run's. control*: the same
measure of the lookups getDepthGrade makes with nothing to do (cache hits,
getDepthHue) right after each frame, the machine's noise floor.
Viewports 844x390@3 and 1280x720@1. DRAWS_PER_POINT 16 is about 3.75 points
per second at 60 fps, three times the fastest pace of the seeded run in
artifacts/TASK-041/run-trace.json (40 points in 60 s, at most 5 per 4 s).

Each run is traced (TRACE_CATEGORIES) and every frame over BUDGET_MS is
classified by classify_slow (descheduled / gc / code); the trace itself is
not kept. PERF_NICE=<n> runs the browser at nice n.

Usage: [PERF_NICE=-15] python3 momentum_depth_grade_perf_probe.py REV OUT.json
(REV 'worktree' or a git revision)
"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
import render_snapshot

VIEWPORTS = [(844, 390, 3), (1280, 720, 1)]
DRAWS_PER_POINT = 16
BUDGET_MS = 4
RUNS = 3
PHASE_DRAWS = 3
# Chrome trace categories: tasks (wall and thread time), garbage collections
TRACE_CATEGORIES = ['toplevel', 'devtools.timeline', 'disabled-by-default-v8.gc', 'v8']
TOGGLE_RUNS = 2
# PERF_NICE=<n>: the browser's threads at nice n for the ramps (root; see renice_browser)
NICE = int(os.environ['PERF_NICE']) if os.environ.get('PERF_NICE') else None
# Score: BACKDROP.scale from then on
TOGGLES = [(120, 0.5), (200, 1), (360, 0.5)]

REAL_CLOCK_SCRIPT = 'window.__realNow = performance.now.bind(performance)'

PROBE = r'''async ([drawsPerPoint, budget, phaseDraws, toggles]) => {
    const now = window.__realNow
    // The game's jobs bound their frames by the real clock (the frozen one
    // stands still)
    if (typeof DEPTH_GRADE_CLOCK == 'object') DEPTH_GRADE_CLOCK.now = now
    for (let i = 0; i < phaseDraws; ++i) {
        scoreText.count.momentum = 0
        draw()
    }
    const bg = visualEffects.background, grade = bg.depthGrade
    const stages = STYLE.momentumFx.depthStages, last = stages[stages.length - 1].score
    const rotations = [], remote = [], adoptions = []
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
        // Worker answers (main thread, between frames)
        const received = HueRotateJob.prototype.received
        if (received) HueRotateJob.prototype.received = function(bitmaps) {
            const t0 = now()
            received.call(this, bitmaps)
            remote.push({score, hue: this.hue, ms: Math.round((now() - t0) * 100) / 100, done: this.done})
        }
        HueRotateJob.prototype.advance = function(pixels) {
            // Waiting for the worker: nothing done here
            if (this.done || this.remote && pixels !== Infinity) return advance.call(this, pixels)
            const tile = this.tile || 0, t0 = now()
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
    const proto = Object.getPrototypeOf(bg), getDepthGrade = proto.getDepthGrade, getLayerTile = proto.getLayerTile
    let frameMs = 0, buildMs = 0, depth = 0, drawn = null
    bg.getDepthGrade = function(...args) {
        const t0 = now(), b0 = buildMs
        ++depth
        try { return drawn = getDepthGrade.apply(this, args) } finally { --depth; frameMs += now() - t0 - (buildMs - b0) }
    }
    // Tile repaints inside getDepthGrade (a new pixel scale) are not hue rotation
    bg.getLayerTile = function(name, ...args) {
        const before = this.layerCache[name], t0 = now()
        try { return getLayerTile.call(this, name, ...args) }
        finally { if (depth && this.layerCache[name] !== before) buildMs += now() - t0 }
    }
    // Each frame its own task, as rAF frames are: worker replies (a tile's
    // colours) come in between (the frozen clock holds setTimeout)
    const channel = new MessageChannel()
    const nextTask = () => new Promise(resolve => { channel.port1.onmessage = resolve; channel.port2.postMessage(0) })
    const switches = []
    let sw = null
    // Slow frames by real time from the trace's sync TimeStamp (ms)
    const slow = []
    console.timeStamp('t93sync')
    const sync = now()
    const paint = () => {
        if (!toggles) { bg.paint(); return }
        const backdrop = BACKDROP.begin()
        bg.paint()
        if (backdrop) BACKDROP.end()
    }
    const start = grade.rebuilds, hues = new Set()
    const times = [], control = []
    // Control: work of the size getDepthGrade does when it has nothing to do
    // (the tile cache keys built and compared, the step's hue), without
    // side effects (no getLayerTile: outside BACKDROP.begin it would rebuild
    // the tiles at the other scale), timed the same way each frame: the
    // shared machine's noise floor for a region of that size
    const lookups = () => {
        const w = LOGICAL_VIEWPORT.width, h = LOGICAL_VIEWPORT.height
        const hit = ['farBaked', 'near'].every(name => bg.layerCache[name] &&
            bg.layerCache[name].key === [w, h, bg.layerCache[name].canvas.width / w].join('|'))
        return [hit, bg.getDepthHue(score)]
    }
    for (score = 0; score <= last; ++score)
        for (let k = 0; k < drawsPerPoint; ++k) {
            scoreText.count.momentum = score
            const toggle = toggles && k == 0 && toggles.find(t => t[0] == score)
            if (toggle) {
                BACKDROP.scale = toggle[1]
                sw = {score, scale: toggle[1], frame: times.length, deferredFrames: null, maxMs: 0, buildMs: 0}
                switches.push(sw)
            }
            await nextTask()
            frameMs = 0; buildMs = 0
            const frameStart = now()
            if (window.__bandFrame) window.__bandFrame()
            const rebuilt = grade.rebuilds, p0 = now()
            if (k == 0) draw()
            else { ++drawFrameId; paint() }
            // A new step drawn: the frame's whole paint (draw() for k 0)
            if (grade.rebuilds != rebuilt)
                adoptions.push({frame: times.length, k, paintMs: Math.round((now() - p0) * 100) / 100,
                                fromWorker: !!(grade.tiles && grade.tiles.far.bitmap)})
            const hue = bg.getDepthHue(score)
            if (hue) hues.add(hue)
            times.push(Math.round(frameMs * 100) / 100)
            const c0 = now()
            lookups()
            control.push(Math.round((now() - c0) * 100) / 100)
            if (frameMs > budget)
                slow.push({frame: times.length - 1, start: frameStart - sync, end: now() - sync})
            if (sw) {
                sw.maxMs = Math.max(sw.maxMs, times[times.length - 1])
                sw.buildMs = Math.max(sw.buildMs, Math.round(buildMs * 100) / 100)
                // Graded tiles drawn at the tile size of the current scale
                const far = bg.layerCache.farBaked
                if (sw.deferredFrames === null && (!drawn || drawn.far.canvas.width == far.canvas.width)) {
                    sw.deferredFrames = times.length - 1 - sw.frame
                    sw.tileWidth = far.canvas.width
                    sw.graded = !!drawn
                }
            }
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
            rebuilds: grade.rebuilds - start, control, rotations, remote, adoptions, switches, slow,
            worker: typeof LAYER_TILE_WORKER == 'object' ? !!LAYER_TILE_WORKER.worker : null,
            rotationMsTotal: Math.round(rotations.reduce((s, r) => s + r.ms, 0) * 100) / 100, times}
}'''


def classify_slow(trace, slow, budget):
    """Per slow frame of a run its renderer task's wall/thread time and the
    garbage collections in it, from the Chrome trace: 'descheduled' when the
    GC time inside the frame covers its excess over budget, 'descheduled'
    when the task's wall time minus thread time (the thread not running)
    does, 'code' otherwise."""
    events = trace['traceEvents'] if isinstance(trace, dict) else trace
    sync = next(e for e in events if e.get('name') == 'TimeStamp'
                and (e.get('args', {}).get('data', {}).get('message') == 't93sync'))
    pid, tid, base = sync['pid'], sync['tid'], sync['ts']
    main = [e for e in events if e.get('pid') == pid and e.get('tid') == tid and e.get('ph') == 'X']
    tasks = [e for e in main if e.get('name') == 'ThreadControllerImpl::RunTask' or e.get('name') == 'RunTask']
    gcs = [e for e in main if 'GC' in e.get('name', '') or 'Scavenge' in e.get('name', '')
           or 'MarkCompact' in e.get('name', '')]
    out = []
    for f in slow:
        start, end = base + f['start'] * 1000, base + f['end'] * 1000
        task = next((t for t in tasks if t['ts'] <= start and t['ts'] + t['dur'] >= end), None)
        # Union of the (nested) GC events' overlaps with the frame
        gc, reach = 0, start
        for g in sorted((g for g in gcs if g['ts'] < end and g['ts'] + g['dur'] > start), key=lambda g: g['ts']):
            lo, hi = max(reach, g['ts']), min(end, g['ts'] + g['dur'])
            if hi > lo:
                gc += hi - lo
                reach = hi
        gc /= 1000
        row = {'frame': f['frame'], 'ms': f['ms'], 'gcMs': round(gc, 2)}
        if task and 'tdur' in task:
            row.update(taskMs=round(task['dur'] / 1000, 2), taskThreadMs=round(task['tdur'] / 1000, 2),
                       descheduledMs=round((task['dur'] - task['tdur']) / 1000, 2))
        excess = f['ms'] - budget
        row['cause'] = ('gc' if gc >= excess else 'descheduled' if row.get('descheduledMs', 0) >= excess
                        else 'code')
        out.append(row)
    return out


def renice_browser(nice):
    """Every thread of this process's descendants (the browser, its renderers
    and GPU process) at nice: other processes' load on the shared machine
    then no longer preempts the page."""
    parents = {}
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = stat.read_text().rsplit(')', 1)[1].split()
        except OSError:
            continue
        parents[int(stat.parent.name)] = int(fields[1])
    def ours(pid):
        while pid > 1:
            if pid == os.getpid():
                return True
            pid = parents.get(pid, 0)
        return False
    threads = 0
    for pid in parents:
        if pid != os.getpid() and ours(pid):
            for task in Path(f'/proc/{pid}/task').glob('*'):
                try:
                    os.setpriority(os.PRIO_PROCESS, int(task.name), nice)
                    threads += 1
                except OSError:
                    pass
    return threads


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
            for run in range(RUNS + TOGGLE_RUNS):
                toggling = run >= RUNS
                context, page = open_page(tree, w, h, dpr)
                trace_path = Path(tempfile.mkstemp(suffix='.json', prefix='t93-trace-')[1])
                try:
                    reniced = renice_browser(NICE) if NICE is not None else 0
                    tree.browser.start_tracing(page=page, path=str(trace_path), categories=TRACE_CATEGORIES)
                    try:
                        ramp = page.evaluate(PROBE, [DRAWS_PER_POINT, BUDGET_MS,
                                                     (run - RUNS if toggling else run) * PHASE_DRAWS,
                                                     TOGGLES if toggling else None])
                    finally:
                        tree.browser.stop_tracing()
                    if page.errors:
                        raise RuntimeError(f'page errors: {page.errors}')
                    for f in ramp['slow']:
                        f['ms'] = ramp['times'][f['frame']]
                    ramp['slow'] = classify_slow(json.loads(trace_path.read_text()), ramp['slow'], BUDGET_MS)
                    if os.environ.get('T93_KEEP_TRACE'):
                        trace_path.rename(os.environ['T93_KEEP_TRACE'])
                    ramp['renicedThreads'] = reniced
                    ramps.append(ramp)
                finally:
                    trace_path.unlink(missing_ok=True)
                    context.close()
            row = {'viewport': f'{w}x{h}@{dpr}', **{k: v for k, v in ramps[0].items() if k not in ('times', 'control', 'switches', 'slow', 'remote', 'adoptions')}}
            frames = [(score, k) for score in range(row['rampFrom'], row['rampTo'] + 1)
                      for k in range(DRAWS_PER_POINT)]
            over = [{'run': run, 'score': frames[f['frame']][0], 'draw': frames[f['frame']][1], **f}
                    for run, r in enumerate(ramps) for f in r['slow']]
            worst = max(((ms, run, i) for run, r in enumerate(ramps) for i, ms in enumerate(r['times'])))
            row.update(runs=RUNS, toggleRuns=TOGGLE_RUNS, toggles=TOGGLES,
                       phaseDraws=[run * PHASE_DRAWS for run in range(RUNS)] + [run * PHASE_DRAWS for run in range(TOGGLE_RUNS)],
                       budgetMs=BUDGET_MS, maxFrameMs=worst[0], maxFrameRun=worst[1], maxFrameScore=frames[worst[2]][0],
                       framesOverBudget=len(over), overBudget=over,
                       overBudgetCauses={c: sum(o['cause'] == c for o in over) for c in ('descheduled', 'gc', 'code')},
                       maxCodeFrameMs=max([o['ms'] for o in over if o['cause'] == 'code'] or [0]),
                       maxFrameMsPerRun=[max(r['times']) for r in ramps],
                       controlMaxMsPerRun=[max(r['control']) for r in ramps],
                       controlFramesOverBudgetPerRun=[sum(t > BUDGET_MS for t in r['control']) for r in ramps],
                       framesOverBudgetPerRun=[sum(t > BUDGET_MS for t in r['times']) for r in ramps],
                       rebuildsPerRun=[r['rebuilds'] for r in ramps],
                       workerPerRun=[r['worker'] for r in ramps],
                       workerStepsPerRun=[sum(a['fromWorker'] for a in r['adoptions']) for r in ramps],
                       maxReceivedMsPerRun=[max([x['ms'] for x in r['remote']] or [0]) for r in ramps],
                       maxAdoptionPaintMsPerRun=[max([a['paintMs'] for a in r['adoptions'] if a['k']] or [0])
                                                 for r in ramps],
                       renicedThreadsPerRun=[r['renicedThreads'] for r in ramps],
                       switches=[r['switches'] for r in ramps[RUNS:]])
            print(rev, {k: v for k, v in row.items() if k not in ('rotations', 'overBudget', 'switches')})
            print('switches', row['switches'])
            runs.append(row)
    finally:
        fx.close()
    result = {'rev': tree.rev, 'nice': NICE, 'runs': runs}
    Path(out).write_text(json.dumps(result, separators=(',', ':')))
    return result


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
