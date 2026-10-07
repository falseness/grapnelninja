"""Mobile performance harness: one seeded, CPU-throttled phone run of the game.

Emulates a phone (844x390 landscape, DPR 3, is_mobile, has_touch), applies the
CDP CPU throttle, seeds Math.random, starts startGame(mode) and replays a
seeded touch script as real TouchEvents (the touchstart/touchend events
events.js listens to), scheduled in the page against performance.now() so the
input timing does not depend on how fast the revision renders. The window is
exactly --seconds from startGame(); frames, touches and timings are recorded
only inside it. physics(), draw() and gameLoop() are wrapped in the page for
measurement only; game files are served unchanged.

Unless --no-trace is given, the window is also covered by a CDP trace (GC
events) and the V8 sampling heap profiler (allocations, including objects
already collected), reported as gc_minor_count, gc_major_count, gc_total_ms
and allocated_bytes_per_frame. With --no-trace those keys are null.
allocated_bytes_per_frame_after_warmup counts only what was allocated after
--warmup seconds (default 3), divided by the frames after that point; the
profile is read without stopping at t0 + warmup. --heapprofile FILE saves the
sampling heap profile of the whole window (.heapprofile, DevTools format).

--layers also times every draw layer function in render/draw.js (layers_ms)
and counts per frame: gradients created, fill/stroke calls made while
shadowBlur > 0 (any canvas) and floor element draw() calls whose element's
points lie fully outside the visible view. <key>_per_frame_after_warmup holds
the same counters for the frames that start --warmup seconds after t0. --cpuprofile FILE saves a CDP
Profiler (.cpuprofile) of the window.

Usage: python3 tools/perf_mobile.py --rev worktree|<git rev> --mode bad|classic
       [--seconds 20] [--seed 1] [--warmup 3] [--no-trace] [--layers] [--cpuprofile F]
       [--heapprofile F] --out perf.json
"""
import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import random
import subprocess
import tarfile
import tempfile
import time

from browser_test_support import start_browser_test, wait_for_boot

ROOT = Path(__file__).resolve().parents[1]
VIEWPORT = {'width': 844, 'height': 390}
DEVICE_SCALE_FACTOR = 3
CPU_THROTTLE_RATE = 4
CLK = os.sysconf('SC_CLK_TCK')
TRACE_CATEGORIES = ['v8', 'disabled-by-default-v8.gc', 'devtools.timeline', 'blink.user_timing']
GC_EVENTS = {'MinorGC': 'minor', 'MajorGC': 'major'}
T0_MARK = 'perf-mobile-t0'
LAYERS = ['drawBackgroundLayer', 'drawLightsLayer', 'drawBehindForegroundParticlesLayer',
          'drawPlayerTrailLayer', 'drawWorldLayer', 'drawParticlesAndTrailsLayer',
          'drawBloomLayer', 'drawPlayerLayer', 'drawColorGradeLayer', 'drawUILayer', 'drawFpsCounterLayer']
COUNTERS = ['gradients', 'shadow_draws', 'offscreen_element_draws', 'element_draws']

# Mulberry32 replaces Math.random before any game script runs.
SEED_SCRIPT = '''(() => {
    let a = %d >>> 0
    Math.random = function() {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
})()'''

# Measurement wrappers around the global game functions. Nothing is recorded
# until START_SCRIPT sets perf.t0, and nothing after perf.t0 + perf.windowMs.
INSTRUMENT_SCRIPT = '''() => {
    const perf = window.__perf = {t0: null, windowMs: 0, frames: [], physicsMs: [], drawMs: [], steps: [],
                                  current: 0, touches: 0, throws: 0, dispatched: []}
    const recording = () => perf.t0 !== null && performance.now() - perf.t0 < perf.windowMs
    // Capture on window: counted before the game's handlers run, so a slow
    // handler on a loaded host cannot push the count past the window.
    window.addEventListener('touchstart', () => recording() && perf.touches++, true)
    document.addEventListener('touchstart', () => recording() && grapnel.throwed && perf.throws++)
    const physics0 = window.physics, draw0 = window.draw, loop0 = window.gameLoop
    window.physics = function() {
        const t = performance.now()
        physics0()
        if (recording()) perf.physicsMs.push(performance.now() - t)
        perf.current++
    }
    window.draw = function() {
        const t = performance.now()
        draw0()
        if (recording()) perf.drawMs.push(performance.now() - t)
    }
    window.gameLoop = function(frameTime) {
        if (perf.fireDue) perf.fireDue()
        const on = recording()
        if (on) perf.frames.push(frameTime)
        perf.current = 0
        loop0(frameTime)
        if (on) perf.steps.push(perf.current)
    }
}'''

# --layers: wraps each draw layer and the canvas drawing calls. Counters are
# per gameLoop frame (all canvases, including the offscreen light canvas).
LAYERS_SCRIPT = '''([layers]) => {
    const perf = window.__perf
    const recording = () => perf.t0 !== null && performance.now() - perf.t0 < perf.windowMs
    perf.layersMs = {}
    perf.counters = {gradients: [], shadow_draws: [], offscreen_element_draws: [], element_draws: []}
    perf.counterFrames = []
    let frame = null
    for (const name of layers) {
        const f = window[name]
        perf.layersMs[name] = []
        window[name] = function(...args) {
            const t = performance.now()
            const r = f.apply(this, args)
            if (recording()) perf.layersMs[name].push(performance.now() - t)
            return r
        }
    }
    const proto = CanvasRenderingContext2D.prototype
    for (const name of ['createLinearGradient', 'createRadialGradient']) {
        const f = proto[name]
        proto[name] = function(...args) {
            if (frame) frame.gradients++
            return f.apply(this, args)
        }
    }
    for (const name of ['fill', 'stroke', 'fillRect', 'strokeRect', 'fillText', 'strokeText']) {
        const f = proto[name]
        proto[name] = function(...args) {
            if (frame && this.shadowBlur > 0) frame.shadow_draws++
            return f.apply(this, args)
        }
    }
    const offscreen = element => {
        const points = element.getPoints && element.getPoints()
        if (!points || !points.length) return false
        const w = canvas.width / scale[version], h = canvas.height / scale[version]
        const xs = points.map(p => p.x + screen.x), ys = points.map(p => p.y + screen.y)
        return Math.max(...xs) < 0 || Math.min(...xs) > w || Math.max(...ys) < 0 || Math.min(...ys) > h
    }
    const wrapElement = element => {
        if (Object.prototype.hasOwnProperty.call(element, 'draw')) return
        element.draw = function() {
            if (frame) {
                frame.element_draws++
                if (offscreen(element)) frame.offscreen_element_draws++
            }
            return Object.getPrototypeOf(element).draw.call(element)
        }
    }
    const world = window.drawWorldLayer
    window.drawWorldLayer = function() {
        for (const floor of floors)
            for (const element of floor.elements) wrapElement(element)
        return world()
    }
    const loop = window.gameLoop
    window.gameLoop = function(frameTime) {
        const on = recording()
        frame = on ? {gradients: 0, shadow_draws: 0, offscreen_element_draws: 0, element_draws: 0} : null
        loop(frameTime)
        if (on) {
            for (const k in frame) perf.counters[k].push(frame[k])
            perf.counterFrames.push(frameTime)
        }
        frame = null
    }
}'''

# Starts the game, opens the measurement window and schedules every touch at
# t0 + t_ms on the page clock. Each dispatch records its actual offset.
START_SCRIPT = '''([mode, script, windowMs]) => {
    const perf = window.__perf
    startGame(mode)
    perf.windowMs = windowMs
    perf.t0 = performance.now()
    performance.mark('perf-mobile-t0')
    let touch = null
    const fire = event => {
        const offset = performance.now() - perf.t0
        if (offset >= windowMs)
            return
        const target = document.elementFromPoint(event.x, event.y) || document.body
        if (event.type == 'start')
            touch = new Touch({identifier: 0, target, clientX: event.x, clientY: event.y})
        const init = {bubbles: true, cancelable: true, changedTouches: [touch],
                      touches: event.type == 'start' ? [touch] : []}
        target.dispatchEvent(new TouchEvent(event.type == 'start' ? 'touchstart' : 'touchend', init))
        perf.dispatched.push({t_ms: event.t_ms, type: event.type, offset_ms: Math.round(offset * 10) / 10})
    }
    const queue = script.slice()
    perf.fireDue = () => {
        while (queue.length && performance.now() - perf.t0 >= queue[0].t_ms)
            fire(queue.shift())
    }
    for (const event of script)
        setTimeout(perf.fireDue, Math.max(0, event.t_ms - (performance.now() - perf.t0)))
}'''


def input_script(seed, seconds):
    """Seeded grapnel throws: [{t_ms, type: start|end, x, y}] in viewport CSS px."""
    rng = random.Random(seed)
    events, t = [], 500
    limit = seconds * 1000 - 200
    while True:
        hold = rng.randint(250, 900)
        if t + hold > limit:
            break
        x = round(rng.uniform(0.45, 0.95) * VIEWPORT['width'], 1)
        y = round(rng.uniform(0.05, 0.6) * VIEWPORT['height'], 1)
        events.append({'t_ms': t, 'type': 'start', 'x': x, 'y': y})
        events.append({'t_ms': t + hold, 'type': 'end', 'x': x, 'y': y})
        t += hold + rng.randint(80, 450)
    return events


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def percentiles(values):
    return {'p50': pct(values, 50), 'p95': pct(values, 95), 'p99': pct(values, 99)}


def chrome_cpu_seconds():
    """utime+stime of every Chromium process below this Python process."""
    procs = {}
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            stat = Path(f'/proc/{pid}/stat').read_text()
        except OSError:
            continue
        end = stat.rindex(')')
        comm = stat[stat.index('(') + 1:end]
        fields = stat[end + 2:].split()
        procs[int(pid)] = (int(fields[1]), comm, int(fields[11]) + int(fields[12]))
    me, total = os.getpid(), 0
    for ppid, comm, ticks in procs.values():
        if not ('chrom' in comm.lower() or comm.startswith('headless')):
            continue
        p, depth = ppid, 0
        while p and p != me and p in procs and depth < 50:
            p, depth = procs[p][0], depth + 1
        if p == me:
            total += ticks
    return total / CLK


def read_trace(cdp, page):
    """Ends the trace started with ReturnAsStream and returns its events."""
    done = {}
    cdp.on('Tracing.tracingComplete', lambda params: done.update(params))
    cdp.send('Tracing.end')
    deadline = time.monotonic() + 120
    while 'stream' not in done:
        if time.monotonic() > deadline:
            raise TimeoutError('Tracing.tracingComplete not received')
        page.wait_for_timeout(50)
    chunks = []
    while True:
        chunk = cdp.send('IO.read', {'handle': done['stream'], 'size': 1 << 20})
        chunks.append(chunk['data'])
        if chunk.get('eof'):
            break
    cdp.send('IO.close', {'handle': done['stream']})
    data = json.loads(''.join(chunks))
    return data['traceEvents'] if isinstance(data, dict) else data


def gc_stats(events, seconds):
    """MinorGC/MajorGC events on the page's main thread inside [t0, t0+seconds].

    t0 is the performance.mark() START_SCRIPT sets next to __perf.t0, so the
    trace window matches the frame window."""
    mark = next(e for e in events if e.get('name') == T0_MARK)
    start, end = mark['ts'], mark['ts'] + seconds * 1e6
    thread = (mark['pid'], mark['tid'])
    counts, total_us, open_begin = {'minor': 0, 'major': 0}, 0.0, {}
    for e in sorted(events, key=lambda e: e.get('ts', 0)):
        kind = GC_EVENTS.get(e.get('name'))
        if not kind or (e.get('pid'), e.get('tid')) != thread or not start <= e.get('ts', 0) < end:
            continue
        if e['ph'] == 'X':
            counts[kind] += 1
            total_us += e.get('dur', 0)
        elif e['ph'] == 'B':
            open_begin[kind] = e['ts']
        elif e['ph'] == 'E' and kind in open_begin:
            counts[kind] += 1
            total_us += e['ts'] - open_begin.pop(kind)
    return {'gc_minor_count': counts['minor'], 'gc_major_count': counts['major'],
            'gc_total_ms': round(total_us / 1000, 3)}


def sampled_bytes(node):
    return node.get('selfSize', 0) + sum(sampled_bytes(c) for c in node.get('children', []))


def export_rev(rev, add_cleanup):
    """Serve directory for rev: the checkout itself or a `git archive` copy."""
    if rev == 'worktree':
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                        cwd=ROOT, text=True).strip()
        return ROOT, f'worktree@{head}' + ('+dirty' if dirty else '')
    sha = subprocess.check_output(['git', 'rev-parse', rev], cwd=ROOT, text=True).strip()
    scratch = tempfile.TemporaryDirectory(prefix='perf-mobile-')
    add_cleanup(scratch.cleanup)
    data = subprocess.check_output(['git', 'archive', sha], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(scratch.name)
    return Path(scratch.name), sha


def run(rev, mode, seconds, seed, log=print, trace=True, layers=False, cpuprofile=None,
        warmup=3, heapprofile=None):
    script = input_script(seed, seconds)
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE_FACTOR,
                                      is_mobile=True, has_touch=True)
        stack.callback(context.close)
        context.add_init_script(SEED_SCRIPT % seed)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        cdp = context.new_cdp_session(page)
        cdp.send('Emulation.setCPUThrottlingRate', {'rate': CPU_THROTTLE_RATE})
        log(f'rev={rev_id} mode={mode} seed={seed} seconds={seconds} '
            f'viewport={VIEWPORT["width"]}x{VIEWPORT["height"]} dpr={DEVICE_SCALE_FACTOR} '
            f'is_mobile=True has_touch=True cpu_throttle_rate={CPU_THROTTLE_RATE} '
            f'input_events={len(script)} trace={trace} layers={layers} cpuprofile={cpuprofile} '
            f'warmup={warmup} heapprofile={heapprofile}')
        page.goto(url + 'index.html')
        page.wait_for_function('() => typeof menu != "undefined" && menu.visible')
        wait_for_boot(page)
        page.evaluate(INSTRUMENT_SCRIPT)
        if layers:
            page.evaluate(LAYERS_SCRIPT, [LAYERS])
        if trace:
            cdp.send('HeapProfiler.enable')
            cdp.send('HeapProfiler.startSampling', {'includeObjectsCollectedByMajorGC': True,
                                                    'includeObjectsCollectedByMinorGC': True})
            cdp.send('Tracing.start', {'traceConfig': {'includedCategories': TRACE_CATEGORIES,
                                                       'recordMode': 'recordAsMuchAsPossible'},
                                       'transferMode': 'ReturnAsStream'})
        if cpuprofile:
            cdp.send('Profiler.enable')
            cdp.send('Profiler.start')
        page.evaluate(START_SCRIPT, [mode, script, seconds * 1000])
        cpu0, t0 = chrome_cpu_seconds(), time.monotonic()
        warm_frames = warm_bytes = None
        if trace and 0 < warmup < seconds:
            time.sleep(max(0, t0 + warmup - time.monotonic()))
            # Both read between two page tasks, so they agree on the frame boundary
            warm_frames = page.evaluate('() => __perf.frames.length')
            warm_bytes = sampled_bytes(cdp.send('HeapProfiler.getSamplingProfile')['profile']['head'])
        # Input runs in the page; Python only closes the CPU/wall window.
        time.sleep(max(0, t0 + seconds - time.monotonic()))
        cpu_s, wall_s = chrome_cpu_seconds() - cpu0, time.monotonic() - t0
        page.wait_for_function('() => performance.now() - __perf.t0 >= __perf.windowMs',
                               timeout=60000)
        perf = page.evaluate('() => window.__perf')
        if cpuprofile:
            profile = cdp.send('Profiler.stop')['profile']
            Path(cpuprofile).write_text(json.dumps(profile))
        gc = {'gc_minor_count': None, 'gc_major_count': None, 'gc_total_ms': None}
        allocated = None
        if trace:
            profile = cdp.send('HeapProfiler.stopSampling')['profile']
            allocated = sampled_bytes(profile['head'])
            if heapprofile:
                Path(heapprofile).write_text(json.dumps(profile))
            gc = gc_stats(read_trace(cdp, page), seconds)
    frames = perf['frames']
    intervals = [b - a for a, b in zip(frames, frames[1:])]
    histogram = {}
    for n in perf['steps']:
        histogram[str(n)] = histogram.get(str(n), 0) + 1
    lags = [d['offset_ms'] - d['t_ms'] for d in perf['dispatched']]
    # Longest main-thread gap inside the window (t0, every rAF, window end): an
    # in-page dispatch can be late by at most about one such gap.
    marks = [perf['t0']] + frames + [perf['t0'] + seconds * 1000]
    max_gap = max(b - a for a, b in zip(marks, marks[1:]))
    result = {
        'rev': rev_id, 'mode': mode, 'seed': seed, 'seconds': seconds,
        'emulation': {'viewport': VIEWPORT, 'device_scale_factor': DEVICE_SCALE_FACTOR,
                      'is_mobile': True, 'has_touch': True, 'cpu_throttle_rate': CPU_THROTTLE_RATE},
        'input_events': len(script), 'input_dispatched': len(perf['dispatched']),
        'input_lag_ms': {**percentiles(lags), 'max': round(max(lags), 1) if lags else None},
        'input_dispatch': perf['dispatched'], 'max_frame_gap_ms': round(max_gap, 1),
        'window_ms': seconds * 1000,
        'touchstarts_received': perf['touches'], 'grapnel_throws': perf['throws'],
        'frames': len(frames),
        'frame_interval_ms': percentiles(intervals),
        'physics_ms': percentiles(perf['physicsMs']),
        'draw_ms': percentiles(perf['drawMs']),
        'physics_steps_per_frame': dict(sorted(histogram.items(), key=lambda kv: int(kv[0]))),
        'frames_over_16_7ms': sum(1 for i in intervals if i > 16.7),
        'frames_over_33_4ms': sum(1 for i in intervals if i > 33.4),
        'cpu_seconds': round(cpu_s, 3), 'wall_seconds': round(wall_s, 3),
        'cpu_fps': round(len(frames) / cpu_s, 2) if cpu_s > 0 else None,
        'wall_fps': round(len(frames) / wall_s, 2),
        **gc,
        'allocated_bytes_per_frame': (round(allocated / len(frames), 1)
                                      if allocated is not None and frames else None),
        'warmup_seconds': warmup,
        'allocated_bytes_per_frame_after_warmup': (
            round((allocated - warm_bytes) / (len(frames) - warm_frames), 1)
            if warm_bytes is not None and len(frames) > warm_frames else None),
        'page_errors': errors,
    }
    if layers:
        result['layers_ms'] = {name: percentiles(perf['layersMs'][name]) for name in LAYERS}
        for key in COUNTERS:
            values = perf['counters'][key]
            result[f'{key}_per_frame'] = {**percentiles(values),
                                          'mean': round(sum(values) / len(values), 2) if values else None}
            warm = [v for t, v in zip(perf['counterFrames'], values) if t - perf['t0'] >= warmup * 1000]
            result[f'{key}_per_frame_after_warmup'] = {
                **percentiles(warm), 'max': max(warm) if warm else None,
                'mean': round(sum(warm) / len(warm), 2) if warm else None, 'frames': len(warm)}
        log('layers_ms=' + json.dumps(result['layers_ms']) + ' ' +
            ' '.join(f'{k}_per_frame={result[k + "_per_frame"]}' for k in COUNTERS) + ' ' +
            ' '.join(f'{k}_after_warmup={result[k + "_per_frame_after_warmup"]}' for k in COUNTERS))
    log(f'frames={result["frames"]} frame_interval_ms={result["frame_interval_ms"]} '
        f'physics_ms={result["physics_ms"]} draw_ms={result["draw_ms"]} '
        f'steps={result["physics_steps_per_frame"]} over16.7={result["frames_over_16_7ms"]} '
        f'over33.4={result["frames_over_33_4ms"]} cpu_fps={result["cpu_fps"]} '
        f'wall_fps={result["wall_fps"]} touchstarts={perf["touches"]} throws={perf["throws"]} '
        f'input_dispatched={len(perf["dispatched"])}/{len(script)} '
        f'input_lag_ms={result["input_lag_ms"]} wall_seconds={result["wall_seconds"]} '
        f'gc_minor={gc["gc_minor_count"]} gc_major={gc["gc_major_count"]} '
        f'gc_total_ms={gc["gc_total_ms"]} alloc_per_frame={result["allocated_bytes_per_frame"]} '
        f'alloc_per_frame_after_warmup={result["allocated_bytes_per_frame_after_warmup"]} '
        f'page_errors={len(errors)}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--rev', default='worktree')
    parser.add_argument('--mode', choices=['bad', 'classic'], default='bad')
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--no-trace', dest='trace', action='store_false',
                        help='skip the GC trace and heap sampling (plain timing run)')
    parser.add_argument('--layers', action='store_true',
                        help='time each draw layer and count gradients/shadow draws/offscreen elements')
    parser.add_argument('--cpuprofile', help='save a CDP CPU profile of the window to this file')
    parser.add_argument('--warmup', type=float, default=3,
                        help='seconds after startGame() excluded from the *_after_warmup values')
    parser.add_argument('--heapprofile', help='save the sampling heap profile of the window to this file')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = run(args.rev, args.mode, args.seconds, args.seed, log=lambda s: print(s, flush=True),
                 trace=args.trace, layers=args.layers, cpuprofile=args.cpuprofile,
                 warmup=args.warmup, heapprofile=args.heapprofile)
    Path(args.out).write_text(json.dumps(result, indent=1) + '\n')
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
