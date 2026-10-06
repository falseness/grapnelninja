"""Pixel-identity harness: deterministic canvas captures of one revision.

The page clock is frozen before any game script runs: performance.now(),
Date.now() / new Date(), requestAnimationFrame and setTimeout/setInterval all
run on a manual clock that advances exactly 1000/60 ms per step, and
Math.random is seeded. The game is never driven by rAF: after startGame(mode)
each step advances the clock, fires due timers and the seeded scripted input
of that tick (the same script for every revision), then calls physics() and
draw() by hand. Captures are the canvas composited over opaque black (the
body color), so alpha differences that are invisible on screen do not count.

Captures (18): the main menu, and bad and classic at ticks 60, 300, 600 and
1200, at 844x390@DPR3 (mobile, touch) and 1920x1080@DPR1 (mouse).

Usage: python3 tools/render_snapshot.py --capture --rev worktree|<git rev> --out DIR
       python3 tools/render_snapshot.py --compare REV_A REV_B --out DIR
           [--init-script-b FILE]   (extra init script for REV_B, e.g. a test change)
--capture writes DIR/<name>.png and DIR/manifest.json (sha256 per capture).
--compare captures both into DIR/a and DIR/b and writes DIR/compare.json with
differing_pixels / max_channel_diff per capture, plus DIR/diff/<name>.png for
every capture that differs; exit 1 if any capture differs.
"""
import argparse
import base64
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import random
import sys

import numpy as np
from PIL import Image

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev

VIEWPORTS = [
    {'name': 'mobile', 'width': 844, 'height': 390, 'dpr': 3, 'touch': True},
    {'name': 'desktop', 'width': 1920, 'height': 1080, 'dpr': 1, 'touch': False},
]
MODES = ['bad', 'classic']
TICKS = [60, 300, 600, 1200]
SEED = 1

# Manual clock. Runs before every game script, so all game timing reads it.
CLOCK_SCRIPT = '''(() => {
    const STEP = 1000 / 60, EPOCH = 1767225600000
    const snap = window.__snap = {now: 0, tick: 0, timers: [], nextId: 1, rafs: 0}
    performance.now = () => snap.now
    const RealDate = Date
    class FrozenDate extends RealDate {
        constructor(...args) { super(...(args.length ? args : [EPOCH + snap.now])) }
        static now() { return EPOCH + snap.now }
    }
    window.Date = FrozenDate
    // rAF callbacks are recorded and never run: the harness steps by hand.
    // Until boot() hides #loading they are queued for pumpBoot instead.
    snap.bootRafs = []
    snap.booted = false
    window.requestAnimationFrame = cb => {
        if (!snap.booted)
            snap.bootRafs.push(cb)
        return ++snap.rafs
    }
    window.cancelAnimationFrame = () => {}
    const addTimer = (fn, ms, repeat, args) => {
        const id = snap.nextId++
        snap.timers.push({id, fn, due: snap.now + Math.max(0, +ms || 0), ms: +ms || 0, repeat, args})
        return id
    }
    window.setTimeout = (fn, ms, ...args) => addTimer(fn, ms, false, args)
    window.setInterval = (fn, ms, ...args) => addTimer(fn, ms, true, args)
    window.clearTimeout = window.clearInterval = id => {
        snap.timers = snap.timers.filter(t => t.id !== id)
    }
    snap.runTimers = () => {
        for (;;) {
            const due = snap.timers.filter(t => t.due <= snap.now)
            if (!due.length)
                return
            due.sort((a, b) => a.due - b.due || a.id - b.id)
            const t = due[0]
            if (t.repeat)
                t.due += Math.max(t.ms, STEP)
            else
                snap.timers = snap.timers.filter(x => x !== t)
            if (typeof t.fn == 'function')
                t.fn(...t.args)
        }
    }
    // One boot round: due timers and the queued rAFs; true once booted
    // (trees without #loading boot synchronously on load).
    snap.pumpBoot = () => {
        snap.runTimers()
        for (const cb of snap.bootRafs.splice(0))
            cb(snap.now)
        const loading = document.getElementById('loading')
        snap.booted = !loading || loading.hidden
        return snap.booted
    }
    snap.step = () => {
        snap.tick++
        snap.now = snap.tick * STEP
        snap.runTimers()
        snap.fireInput(snap.tick)
        physics()
        draw()
    }
})()'''

def boot_frozen(page, rounds=500):
    """Drive index.html's async boot() to the first menu frame under CLOCK_SCRIPT.

    boot() awaits rAF, which the frozen clock never fires on its own; the real
    event loop runs between rounds so the Bridge script load can settle.
    """
    for _ in range(rounds):
        if page.evaluate('() => __snap.pumpBoot()'):
            return
        page.wait_for_timeout(5)
    raise RuntimeError('boot() did not finish under the frozen clock')


# After load: input dispatch (touch or mouse) and the black composite capture.
SETUP_SCRIPT = '''([script, touch]) => {
    const snap = window.__snap
    window.onblur = null
    const byTick = {}
    for (const e of script)
        (byTick[e.tick] = byTick[e.tick] || []).push(e)
    let current = null
    snap.fireInput = tick => {
        for (const e of byTick[tick] || []) {
            const target = document.elementFromPoint(e.x, e.y) || document.body
            if (touch) {
                if (e.type == 'start')
                    current = new Touch({identifier: 0, target, clientX: e.x, clientY: e.y})
                target.dispatchEvent(new TouchEvent(e.type == 'start' ? 'touchstart' : 'touchend',
                    {bubbles: true, cancelable: true, changedTouches: [current],
                     touches: e.type == 'start' ? [current] : []}))
            } else {
                target.dispatchEvent(new MouseEvent(e.type == 'start' ? 'mousedown' : 'mouseup',
                    {bubbles: true, cancelable: true, clientX: e.x, clientY: e.y, button: 0}))
            }
        }
    }
    snap.capture = () => {
        const out = document.createElement('canvas')
        out.width = canvas.width
        out.height = canvas.height
        const c = out.getContext('2d')
        c.fillStyle = '#000'
        c.fillRect(0, 0, out.width, out.height)
        c.drawImage(canvas, 0, 0)
        return out.toDataURL('image/png')
    }
}'''

ADVANCE_SCRIPT = '''target => {
    while (__snap.tick < target)
        __snap.step()
    return __snap.tick
}'''


def input_script(seed=SEED, ticks=TICKS[-1], width=1, height=1):
    """Seeded grapnel throws [{tick, type, x, y}] scaled to a viewport; the
    tick schedule and relative positions are the same for every viewport."""
    rng = random.Random(seed)
    events, t = [], 20
    while True:
        hold = rng.randint(15, 55)
        if t + hold > ticks:
            break
        fx, fy = rng.uniform(0.45, 0.95), rng.uniform(0.05, 0.6)
        x, y = round(fx * width, 1), round(fy * height, 1)
        events.append({'tick': t, 'type': 'start', 'x': x, 'y': y})
        events.append({'tick': t + hold, 'type': 'end', 'x': x, 'y': y})
        t += hold + rng.randint(5, 27)
    return events


def capture_names():
    names = []
    for vp in VIEWPORTS:
        names.append(f'{vp["name"]}-menu')
        names += [f'{vp["name"]}-{mode}-tick{tick:04d}' for mode in MODES for tick in TICKS]
    return names


def png_bytes(data_url):
    return base64.b64decode(data_url.split(',', 1)[1])


def capture(rev, out, extra_init=None, log=print):
    """Writes the 18 PNGs and manifest.json into out; returns the manifest."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    shots, errors = {}, []
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for vp in VIEWPORTS:
            script = input_script(SEED, TICKS[-1], vp['width'], vp['height'])
            for mode in [None] + MODES:
                context = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                              device_scale_factor=vp['dpr'],
                                              is_mobile=vp['touch'], has_touch=vp['touch'])
                context.add_init_script(SEED_SCRIPT % SEED)
                context.add_init_script(CLOCK_SCRIPT)
                if extra_init:
                    context.add_init_script(extra_init)
                page = context.new_page()
                page.on('pageerror', lambda e, n=vp['name']: errors.append(f'{n}: {e}'))
                page.goto(url + 'index.html', wait_until='load')
                boot_frozen(page)
                if not page.evaluate('() => typeof menu != "undefined" && menu.visible'):
                    raise RuntimeError('menu not visible after load')
                page.evaluate(SETUP_SCRIPT, [script, vp['touch']])
                if mode is None:
                    shots[f'{vp["name"]}-menu'] = png_bytes(page.evaluate('() => __snap.capture()'))
                else:
                    page.evaluate('mode => startGame(mode)', mode)
                    for tick in TICKS:
                        page.evaluate(ADVANCE_SCRIPT, tick)
                        shots[f'{vp["name"]}-{mode}-tick{tick:04d}'] = png_bytes(
                            page.evaluate('() => __snap.capture()'))
                context.close()
                log(f'rev={rev_id} viewport={vp["name"]} {vp["width"]}x{vp["height"]}@{vp["dpr"]} '
                    f'mode={mode or "menu"} done')
    captures = {}
    for name in capture_names():
        data = shots[name]
        (out / f'{name}.png').write_bytes(data)
        size = Image.open(io.BytesIO(data)).size
        captures[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'width': size[0], 'height': size[1]}
    manifest = {'rev': rev_id, 'seed': SEED, 'ticks': TICKS, 'viewports': VIEWPORTS,
                'extra_init_script': bool(extra_init), 'page_errors': errors, 'captures': captures}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    return manifest


def pixels(path):
    return np.asarray(Image.open(path).convert('RGB'), dtype=np.int16)


def compare(rev_a, rev_b, out, init_b=None, log=print):
    """Captures both revisions and diffs them; returns the compare report."""
    out = Path(out)
    man_a = capture(rev_a, out / 'a', log=log)
    man_b = capture(rev_b, out / 'b', extra_init=init_b, log=log)
    report = {'rev_a': man_a['rev'], 'rev_b': man_b['rev'], 'captures': {}}
    for name in capture_names():
        a, b = pixels(out / 'a' / f'{name}.png'), pixels(out / 'b' / f'{name}.png')
        entry = {'sha256_a': man_a['captures'][name]['sha256'],
                 'sha256_b': man_b['captures'][name]['sha256']}
        if a.shape != b.shape:
            entry.update(differing_pixels=max(a.shape[0] * a.shape[1], b.shape[0] * b.shape[1]),
                         max_channel_diff=255, size_mismatch=[list(a.shape), list(b.shape)])
        else:
            delta = np.abs(a - b)
            mask = delta.max(axis=2) > 0
            entry.update(differing_pixels=int(mask.sum()), max_channel_diff=int(delta.max()))
            if mask.any():
                (out / 'diff').mkdir(exist_ok=True)
                diff = np.zeros(a.shape, dtype=np.uint8)
                diff[..., 0] = np.where(mask, 255, a.mean(axis=2) // 4).astype(np.uint8)
                Image.fromarray(diff).save(out / 'diff' / f'{name}.png')
                entry['diff_png'] = str(out / 'diff' / f'{name}.png')
        report['captures'][name] = entry
    report['differing_captures'] = sorted(n for n, e in report['captures'].items()
                                          if e['differing_pixels'])
    report['page_errors_a'], report['page_errors_b'] = man_a['page_errors'], man_b['page_errors']
    (out / 'compare.json').write_text(json.dumps(report, indent=1) + '\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--capture', action='store_true')
    group.add_argument('--compare', nargs=2, metavar=('REV_A', 'REV_B'))
    parser.add_argument('--rev', default='worktree')
    parser.add_argument('--init-script-b', help='extra init script (JS file) for REV_B')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    log = lambda s: print(s, flush=True)
    if args.capture:
        manifest = capture(args.rev, args.out, log=log)
        for name, c in manifest['captures'].items():
            print(f'{c["sha256"]}  {name}.png')
        print(f'rev={manifest["rev"]} captures={len(manifest["captures"])} '
              f'page_errors={len(manifest["page_errors"])}')
        return 0
    init_b = Path(args.init_script_b).read_text() if args.init_script_b else None
    report = compare(*args.compare, args.out, init_b=init_b, log=log)
    for name, e in report['captures'].items():
        print(f'{name}: differing_pixels={e["differing_pixels"]} max_channel_diff={e["max_channel_diff"]}')
    print(f'rev_a={report["rev_a"]} rev_b={report["rev_b"]} '
          f'differing_captures={len(report["differing_captures"])}/{len(report["captures"])}')
    return 1 if report['differing_captures'] else 0


if __name__ == '__main__':
    sys.exit(main())
