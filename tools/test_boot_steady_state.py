"""Steady-state picture check (TASK-887): after a boot, once every lazy cache is warm, the canvas must
look the same - deferring or baking caches may change WHEN they are built, never what is drawn.

For every SCREEN MATRIX size (tools/boot_timing.py, 13 sizes; --sizes to narrow) the game is booted
from a source tree (default the repo root, --root) or a release zip (--zip) under a deterministic
page: performance.now / Date / rAF / timers on a manual clock (1000/60 ms per frame,
tools/render_snapshot.py's CLOCK_SCRIPT model), Math.random seeded, locale en-US, no input, no network.
Boot is driven to its run (render_snapshot.boot_frozen), then --frames (default 120) animation frames
run: each advances the clock one step, fires due timers and calls every queued rAF callback (so the
game's own gameLoop runs, paused or not, exactly as in a browser). The canvas is then captured over
opaque black (the body colour).

  --record DIR   write DIR/<size>.png (one per size) and DIR.json (sha256, size, source, frames)
  --ref DIR      capture again and compare with DIR/<size>.png: per size max channel diff and
                 differing-pixel count; --out FILE writes the report (JSON); exit 1 if any size
                 differs by more than --tolerance-pixels (default 0) or failed to capture.
  --diff-dir D   with --ref: write a red diff mask PNG per differing size into D

With no arguments (tools/run_regression.py runs every test_*.py that way) it is a unittest: one size,
recorded into a temp dir and compared with a second boot of the same tree (A/A must be identical).

Usage:
  python3 tools/test_boot_steady_state.py --record artifacts/TASK-887/steady-ref [--zip PATH]
  python3 tools/test_boot_steady_state.py --ref artifacts/TASK-887/steady-ref --out report.json
"""
import argparse
import base64
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import boot_timing as bt  # noqa: E402
from perf_mobile import SEED_SCRIPT  # noqa: E402
from render_snapshot import boot_frozen  # noqa: E402

SEED = 1
FRAMES = 120

# render_snapshot's manual clock, except that rAF callbacks are always queued: before boot pumpBoot
# runs them, afterwards each step() runs them - so the game's own loop draws every frame.
CLOCK_SCRIPT = r'''(() => {
    const STEP = 1000 / 60, EPOCH = 1767225600000
    const snap = window.__snap = {now: 0, tick: 0, timers: [], nextId: 1, rafs: 0, queue: [], booted: false}
    performance.now = () => snap.now
    const RealDate = Date
    class FrozenDate extends RealDate {
        constructor(...args) { super(...(args.length ? args : [EPOCH + snap.now])) }
        static now() { return EPOCH + snap.now }
    }
    window.Date = FrozenDate
    window.requestAnimationFrame = cb => { const id = ++snap.rafs; snap.queue.push({id, cb}); return id }
    window.cancelAnimationFrame = id => { snap.queue = snap.queue.filter(e => e.id !== id) }
    const addTimer = (fn, ms, repeat, args) => {
        const id = snap.nextId++
        snap.timers.push({id, fn, due: snap.now + Math.max(0, +ms || 0), ms: +ms || 0, repeat, args})
        return id
    }
    window.setTimeout = (fn, ms, ...args) => addTimer(fn, ms, false, args)
    window.setInterval = (fn, ms, ...args) => addTimer(fn, ms, true, args)
    window.clearTimeout = window.clearInterval = id => { snap.timers = snap.timers.filter(t => t.id !== id) }
    snap.runTimers = () => {
        for (;;) {
            const due = snap.timers.filter(t => t.due <= snap.now)
            if (!due.length) return
            due.sort((a, b) => a.due - b.due || a.id - b.id)
            const t = due[0]
            if (t.repeat) t.due += Math.max(t.ms, STEP)
            else snap.timers = snap.timers.filter(x => x !== t)
            if (typeof t.fn == 'function') t.fn(...t.args)
        }
    }
    snap.runFrame = () => { for (const e of snap.queue.splice(0)) e.cb(snap.now) }
    snap.pumpBoot = () => {
        snap.runTimers()
        snap.runFrame()
        const loading = document.getElementById('loading')
        snap.booted = !loading || loading.hidden
        return snap.booted
    }
    snap.advanceBoot = () => {
        if (!snap.timers.length) return false
        const t = snap.timers.reduce((a, b) => b.due < a.due || (b.due == a.due && b.id < a.id) ? b : a)
        t.due = snap.now
        return true
    }
    snap.step = () => {
        snap.tick++
        snap.now = snap.tick * STEP
        snap.runTimers()
        snap.runFrame()
    }
    snap.capture = () => {
        const src = document.getElementById('canvas') || document.querySelector('canvas')
        const out = document.createElement('canvas')
        out.width = src.width
        out.height = src.height
        const c = out.getContext('2d')
        c.fillStyle = '#000'
        c.fillRect(0, 0, out.width, out.height)
        c.drawImage(src, 0, 0)
        return out.toDataURL('image/png')
    }
})()'''

ADVANCE = '''n => {
    window.onblur = null
    for (let i = 0; i < n; i++) __snap.step()
    // async boot tail (await nextFrame) may still be pending: its microtasks ran between steps
    return {tick: __snap.tick, bootComplete: typeof bootComplete != 'undefined' && bootComplete,
            runInProgress: typeof runInProgress != 'undefined' && runInProgress}
}'''


def capture_size(browser, url, size, frames, query='', errors=None):
    """PNG bytes of one size's steady-state canvas."""
    ctx = browser.new_context(locale='en-US', **bt.context_options(size, bt.DEVICES))
    try:
        ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())
        ctx.add_init_script(SEED_SCRIPT % SEED)
        ctx.add_init_script(CLOCK_SCRIPT)
        page = ctx.new_page()
        if errors is not None:
            page.on('pageerror', lambda e: errors.append('%s: %s' % (size['name'], e)))
        page.goto(url + 'index.html' + query, wait_until='load')
        boot_frozen(page)
        # boot()'s tail awaits two more frames before game_ready: step them with the real event loop
        # running in between so its promise continuations settle
        for _ in range(4):
            page.evaluate(ADVANCE, 1)
            page.wait_for_timeout(5)
        state = page.evaluate(ADVANCE, max(0, frames - 4))
        if not (state['bootComplete'] and state['runInProgress']):
            raise RuntimeError('%s: run not started after boot: %s' % (size['name'], state))
        data = page.evaluate('() => __snap.capture()')
        return base64.b64decode(data.split(',', 1)[1])
    finally:
        ctx.close()


def capture_all(zip_path=None, root=None, sizes=None, frames=FRAMES, query='', log=print):
    sizes = sizes or bt.SCREEN_MATRIX
    shots, errors = {}, []
    with ExitStack() as stack:
        site = bt.serve_root(zip_path, root, stack.callback)
        browsers = bt.Browsers(site, stack)
        for name in sizes:
            size = dict(bt.SIZES[name], name=name)
            browser, url = browsers.get(size['browser'])
            t0 = time.time()
            shots[name] = capture_size(browser, url, size, frames, query, errors)
            log('%s captured (%.1f s)' % (name, time.time() - t0))
    return shots, errors


def pixels(data):
    return np.asarray(Image.open(io.BytesIO(data)).convert('RGB'), dtype=np.int16)


def diff_entry(ref_bytes, new_bytes):
    a, b = pixels(ref_bytes), pixels(new_bytes)
    if a.shape != b.shape:
        return {'size_mismatch': [list(a.shape), list(b.shape)], 'max_channel_diff': 255,
                'differing_pixels': max(a.shape[0] * a.shape[1], b.shape[0] * b.shape[1])}, None
    delta = np.abs(a - b)
    mask = delta.max(axis=2) > 0
    entry = {'width': int(a.shape[1]), 'height': int(a.shape[0]), 'max_channel_diff': int(delta.max()),
             'differing_pixels': int(mask.sum()),
             'differing_fraction': round(float(mask.mean()), 8)}
    return entry, mask


def record(out_dir, shots, meta):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(meta, captures={})
    for name, data in shots.items():
        (out_dir / (name + '.png')).write_bytes(data)
        w, h = Image.open(io.BytesIO(data)).size
        manifest['captures'][name] = {'sha256': hashlib.sha256(data).hexdigest(), 'width': w, 'height': h}
    # the manifest sits next to the directory so DIR holds only the PNGs
    Path(str(out_dir).rstrip('/') + '.json').write_text(json.dumps(manifest, indent=1) + '\n')
    return manifest


def compare_to_ref(ref_dir, shots, meta, diff_dir=None):
    ref_dir = Path(ref_dir)
    report = dict(meta, ref=str(ref_dir.resolve()), sizes={})
    for name, data in shots.items():
        ref = ref_dir / (name + '.png')
        if not ref.exists():
            report['sizes'][name] = {'error': 'no reference ' + str(ref)}
            continue
        entry, mask = diff_entry(ref.read_bytes(), data)
        entry['sha256_ref'] = hashlib.sha256(ref.read_bytes()).hexdigest()
        entry['sha256_new'] = hashlib.sha256(data).hexdigest()
        if diff_dir and mask is not None and mask.any():
            Path(diff_dir).mkdir(parents=True, exist_ok=True)
            img = np.zeros(mask.shape + (3,), dtype=np.uint8)
            img[..., 0] = np.where(mask, 255, pixels(data).mean(axis=2) // 4).astype(np.uint8)
            Image.fromarray(img).save(Path(diff_dir) / (name + '.png'))
        report['sizes'][name] = entry
    vals = [e for e in report['sizes'].values() if 'error' not in e]
    report['summary'] = {
        'sizes': len(report['sizes']), 'errors': len(report['sizes']) - len(vals),
        'max_channel_diff': max((e['max_channel_diff'] for e in vals), default=None),
        'max_differing_pixels': max((e['differing_pixels'] for e in vals), default=None),
        'identical_sizes': sum(1 for e in vals if e['differing_pixels'] == 0)}
    return report


def meta_for(zip_path, root, frames, query, errors):
    return {'tool': 'tools/test_boot_steady_state.py', 'source': bt.describe_source(zip_path, root),
            'frames': frames, 'seed': SEED, 'query': query,
            'captured_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'page_errors': errors[:20], 'page_error_count': len(errors)}


class SteadyStateSelfTest(unittest.TestCase):
    """A/A on one size: two boots of the repo tree give the same steady-state picture."""
    def test_aa_one_size(self):
        size = 'desktop-1280x720@1'
        shots_a, err_a = capture_all(sizes=[size], frames=30, log=lambda s: None)
        shots_b, err_b = capture_all(sizes=[size], frames=30, log=lambda s: None)
        with tempfile.TemporaryDirectory() as d:
            record(Path(d) / 'ref', shots_a, meta_for(None, None, 30, '', err_a))
            report = compare_to_ref(Path(d) / 'ref', shots_b, meta_for(None, None, 30, '', err_b))
        e = report['sizes'][size]
        self.assertEqual(e['differing_pixels'], 0, e)
        self.assertEqual(err_a + err_b, [])


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group()
    src.add_argument('--zip')
    src.add_argument('--root')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--record', metavar='DIR')
    mode.add_argument('--ref', metavar='DIR')
    p.add_argument('--sizes', default='matrix', help='comma list or "matrix" (13 sizes)')
    p.add_argument('--frames', type=int, default=FRAMES)
    p.add_argument('--query', default='')
    p.add_argument('--out', help='report JSON (with --ref)')
    p.add_argument('--diff-dir')
    p.add_argument('--tolerance-pixels', type=int, default=0)
    args = p.parse_args(argv)
    sizes = bt.SCREEN_MATRIX if args.sizes == 'matrix' else [s for s in args.sizes.split(',') if s]
    unknown = [s for s in sizes if s not in bt.SIZES]
    if unknown:
        p.error('unknown sizes %s' % unknown)
    log = lambda s: print(s, flush=True)
    shots, errors = capture_all(args.zip, args.root, sizes, args.frames, args.query, log=log)
    meta = meta_for(args.zip, args.root, args.frames, args.query, errors)
    if args.record:
        manifest = record(args.record, shots, meta)
        for name, c in manifest['captures'].items():
            print('%s  %s.png %dx%d' % (c['sha256'], name, c['width'], c['height']))
        print('recorded %d sizes, page_errors=%d' % (len(shots), len(errors)))
        return 0 if not errors else 1
    report = compare_to_ref(args.ref, shots, meta, args.diff_dir)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1) + '\n')
    for name, e in report['sizes'].items():
        print(name, json.dumps({k: e.get(k) for k in ('max_channel_diff', 'differing_pixels', 'error')}))
    print('summary', json.dumps(report['summary']))
    bad = [n for n, e in report['sizes'].items()
           if 'error' in e or e['differing_pixels'] > args.tolerance_pixels]
    return 1 if bad or errors else 0


if __name__ == '__main__':
    if len(sys.argv) == 1 or sys.argv[1].startswith('-v') or sys.argv[1].startswith('Steady'):
        unittest.main()
    else:
        sys.exit(main(sys.argv[1:]))
