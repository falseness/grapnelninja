"""Mobile performance harness: one seeded, CPU-throttled phone run of the game.

Emulates a phone (844x390 landscape, DPR 3, is_mobile, has_touch), applies the
CDP CPU throttle, seeds Math.random, starts startGame(mode) and replays a
seeded touch script through CDP Input.dispatchTouchEvent (the real
touchstart/touchend events events.js listens to). physics(), draw() and
gameLoop() are wrapped in the page for measurement only; game files are
served unchanged.

Usage: python3 tools/perf_mobile.py --rev worktree|<git rev> --mode bad|classic
       [--seconds 20] [--seed 1] --out perf.json
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

from browser_test_support import start_browser_test

ROOT = Path(__file__).resolve().parents[1]
VIEWPORT = {'width': 844, 'height': 390}
DEVICE_SCALE_FACTOR = 3
CPU_THROTTLE_RATE = 4
CLK = os.sysconf('SC_CLK_TCK')

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

# Measurement wrappers around the global game functions.
INSTRUMENT_SCRIPT = '''() => {
    const perf = window.__perf = {frames: [], physicsMs: [], drawMs: [], steps: [], current: 0, touches: 0, throws: 0}
    document.addEventListener('touchstart', () => perf.touches++)
    document.addEventListener('touchstart', () => grapnel.throwed && perf.throws++)
    const physics0 = window.physics, draw0 = window.draw, loop0 = window.gameLoop
    window.physics = function() {
        const t = performance.now()
        physics0()
        perf.physicsMs.push(performance.now() - t)
        perf.current++
    }
    window.draw = function() {
        const t = performance.now()
        draw0()
        perf.drawMs.push(performance.now() - t)
    }
    window.gameLoop = function(frameTime) {
        perf.frames.push(frameTime)
        perf.current = 0
        loop0(frameTime)
        perf.steps.push(perf.current)
    }
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


def run(rev, mode, seconds, seed, log=print):
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
            f'input_events={len(script)}')
        page.goto(url + 'index.html')
        page.wait_for_function('() => typeof menu != "undefined" && menu.visible')
        page.evaluate(INSTRUMENT_SCRIPT)
        page.evaluate('mode => startGame(mode)', mode)
        cpu0, t0 = chrome_cpu_seconds(), time.monotonic()
        for event in script:
            delay = t0 + event['t_ms'] / 1000 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            point = {'x': event['x'], 'y': event['y'], 'id': 0}
            if event['type'] == 'start':
                cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [point]})
            else:
                cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        delay = t0 + seconds - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        perf = page.evaluate('() => window.__perf')
        cpu_s, wall_s = chrome_cpu_seconds() - cpu0, time.monotonic() - t0
    frames = perf['frames']
    intervals = [b - a for a, b in zip(frames, frames[1:])]
    histogram = {}
    for n in perf['steps']:
        histogram[str(n)] = histogram.get(str(n), 0) + 1
    result = {
        'rev': rev_id, 'mode': mode, 'seed': seed, 'seconds': seconds,
        'emulation': {'viewport': VIEWPORT, 'device_scale_factor': DEVICE_SCALE_FACTOR,
                      'is_mobile': True, 'has_touch': True, 'cpu_throttle_rate': CPU_THROTTLE_RATE},
        'input_events': len(script),
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
        'page_errors': errors,
    }
    log(f'frames={result["frames"]} frame_interval_ms={result["frame_interval_ms"]} '
        f'physics_ms={result["physics_ms"]} draw_ms={result["draw_ms"]} '
        f'steps={result["physics_steps_per_frame"]} over16.7={result["frames_over_16_7ms"]} '
        f'over33.4={result["frames_over_33_4ms"]} cpu_fps={result["cpu_fps"]} '
        f'wall_fps={result["wall_fps"]} touchstarts={perf["touches"]} throws={perf["throws"]} '
        f'page_errors={len(errors)}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--rev', default='worktree')
    parser.add_argument('--mode', choices=['bad', 'classic'], default='bad')
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = run(args.rev, args.mode, args.seconds, args.seed, log=lambda s: print(s, flush=True))
    Path(args.out).write_text(json.dumps(result, indent=1) + '\n')
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
