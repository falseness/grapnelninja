"""Physics micro-benchmark: time physics() ticks of a git rev.

Serves the game of each --rev (`git archive` copy, or the checkout for
'worktree'), seeds Math.random (Mulberry32), starts bad or classic and
cancels the rAF loop, so only this tool calls physics(). A fixed scripted
grapnel sequence is replayed by dispatching mousedown/mouseup on document,
so the real events.js handlers throw and release the grapnel. Each of
--ticks physics() calls is timed with performance.now(); restarts after a
death (reStart -> chooseVersion) happen inside physics() and are part of the
run. The page is cross-origin isolated (COOP/COEP) for 5 us timer resolution.

Reps alternate the rev order (rep 0: A then B, rep 1: B then A, ...).
Besides the raw per-rep stats and their medians, the min-envelope (for each
tick index the min over that rev's reps) is reported per mode: the ticks are
deterministic, while scheduler/GC spikes do not line up across reps, so the
envelope filters host noise out of p95.

Usage: python3 tools/physics_bench.py --rev A [--rev B] [--reps 5]
           [--mode bad|classic|both] [--out FILE.json]
"""
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import argparse
import json
import statistics
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import QuietHandler, wait_for_boot
from perf_mobile import SEED_SCRIPT, export_rev, pct


VIEWPORT = {'width': 844, 'height': 390}
SEED = 12345
TICKS = 3000
WARMUP_TICKS = 300
# Grapnel script, in ticks: every PERIOD ticks press at the next target
# (fractions of the viewport) and release HOLD ticks later. The targets
# avoid the HUD menu button (top right).
PERIOD = 50
HOLD = 30
TARGETS = [(0.80, 0.30), (0.70, 0.55), (0.85, 0.45), (0.60, 0.25), (0.75, 0.70)]

BENCH_SCRIPT = '''([mode, ticks, warmup, period, hold, targets]) => {
    startGame(mode)
    cancelAnimationFrame(game)
    let deaths = 0
    const reStart0 = window.reStart
    window.reStart = function() { deaths++; return reStart0() }
    const mouse = (type, t) => document.dispatchEvent(new MouseEvent(type,
        {bubbles: true, cancelable: true, clientX: t[0] * innerWidth, clientY: t[1] * innerHeight}))
    const input = k => {
        const target = targets[Math.floor(k / period) % targets.length]
        if (k % period == 0) mouse('mousedown', target)
        else if (k % period == hold) mouse('mouseup', target)
    }
    for (let k = 0; k < warmup; ++k) { input(k); physics() }
    deaths = 0
    let throws = 0
    const ms = new Float64Array(ticks)
    for (let k = 0; k < ticks; ++k) {
        input(warmup + k)
        if ((warmup + k) % period == 0 && grapnel.throwed) throws++
        const t = performance.now()
        physics()
        ms[k] = performance.now() - t
    }
    return {ms: Array.from(ms), deaths, throws, isolated: crossOriginIsolated}
}'''


class IsolatedHandler(QuietHandler):
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()


def serve(root, add_cleanup):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(IsolatedHandler, directory=str(root)))
    add_cleanup(server.server_close)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    add_cleanup(thread.join)
    add_cleanup(server.shutdown)
    return f'http://127.0.0.1:{server.server_port}/'


def run_once(browser, url, mode, ticks, warmup):
    context = browser.new_context(viewport=VIEWPORT)
    try:
        context.add_init_script(SEED_SCRIPT % SEED)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html')
        page.wait_for_function('() => typeof menu != "undefined" && menu.visible')
        wait_for_boot(page)
        r = page.evaluate(BENCH_SCRIPT, [mode, ticks, warmup, PERIOD, HOLD, TARGETS])
    finally:
        context.close()
    ms = r['ms']
    return ms, {'p50': round(pct(ms, 50), 4), 'p95': round(pct(ms, 95), 4),
            'total': round(sum(ms), 2), 'max': round(max(ms), 3), 'ticks': len(ms),
            'deaths': r['deaths'], 'throws': r['throws'],
            'cross_origin_isolated': r['isolated'], 'page_errors': errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--rev', action='append', required=True,
                        help='git rev or worktree; give once (A) or twice (A, B)')
    parser.add_argument('--reps', type=int, default=5)
    parser.add_argument('--mode', choices=['bad', 'classic', 'both'], default='both')
    parser.add_argument('--ticks', type=int, default=TICKS)
    parser.add_argument('--warmup', type=int, default=WARMUP_TICKS)
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    if len(args.rev) > 2:
        parser.error('at most two --rev')
    modes = ['bad', 'classic'] if args.mode == 'both' else [args.mode]
    labels = ['A', 'B'][:len(args.rev)]

    runs = []
    ticks_ms = {(label, mode): [] for label in labels for mode in modes}
    with ExitStack() as stack:
        revs, urls = {}, {}
        for label, rev in zip(labels, args.rev):
            root, revs[label] = export_rev(rev, stack.callback)
            urls[label] = serve(root, stack.callback)
        playwright = sync_playwright().start()
        stack.callback(playwright.stop)
        browser = playwright.chromium.launch(args=['--no-sandbox'])
        stack.callback(browser.close)
        print(f'revs={revs} reps={args.reps} modes={modes} ticks={args.ticks} '
              f'warmup={args.warmup} seed={SEED} viewport={VIEWPORT["width"]}x{VIEWPORT["height"]}',
              flush=True)
        for rep in range(args.reps):
            order = labels if rep % 2 == 0 else labels[::-1]
            for label in order:
                for mode in modes:
                    ms, r = run_once(browser, urls[label], mode, args.ticks, args.warmup)
                    ticks_ms[label, mode].append(ms)
                    r = {'rep': rep, 'label': label, 'rev': revs[label], 'mode': mode, **r}
                    runs.append(r)
                    print(f'rep={rep} {label}={revs[label][:7]} mode={mode} p50={r["p50"]} '
                          f'p95={r["p95"]} total={r["total"]} max={r["max"]} '
                          f'deaths={r["deaths"]} throws={r["throws"]} '
                          f'isolated={r["cross_origin_isolated"]} page_errors={len(r["page_errors"])}',
                          flush=True)

    medians = {label: {mode: {key: statistics.median(r[key] for r in runs
                                                     if r['label'] == label and r['mode'] == mode)
                              for key in ('p50', 'p95', 'total')}
                       for mode in modes}
               for label in labels}
    envelope = {}
    for label in labels:
        envelope[label] = {}
        for mode in modes:
            ms = [min(tick) for tick in zip(*ticks_ms[label, mode])]
            envelope[label][mode] = {'p50': round(pct(ms, 50), 4), 'p95': round(pct(ms, 95), 4),
                                     'total': round(sum(ms), 2)}
    result = {'revs': revs, 'reps': args.reps, 'modes': modes, 'ticks': args.ticks,
              'warmup': args.warmup, 'seed': SEED, 'viewport': VIEWPORT,
              'runs': runs, 'medians': medians, 'envelope': envelope}
    for label in labels:
        for mode in modes:
            m, e = medians[label][mode], envelope[label][mode]
            print(f'median {label}={revs[label][:7]} mode={mode} p50={m["p50"]} '
                  f'p95={m["p95"]} total={m["total"]}')
            print(f'envelope {label}={revs[label][:7]} mode={mode} p50={e["p50"]} '
                  f'p95={e["p95"]} total={e["total"]}')
    if len(labels) == 2:
        result['p95_ratio_b_over_a'] = {
            mode: round(medians['B'][mode]['p95'] / medians['A'][mode]['p95'], 4) for mode in modes}
        result['total_ratio_b_over_a'] = {
            mode: round(medians['B'][mode]['total'] / medians['A'][mode]['total'], 4) for mode in modes}
        result['envelope_p95_ratio_b_over_a'] = {
            mode: round(envelope['B'][mode]['p95'] / envelope['A'][mode]['p95'], 4) for mode in modes}
        result['envelope_total_ratio_b_over_a'] = {
            mode: round(envelope['B'][mode]['total'] / envelope['A'][mode]['total'], 4) for mode in modes}
        print(f'p95_ratio_b_over_a={result["p95_ratio_b_over_a"]} '
              f'total_ratio_b_over_a={result["total_ratio_b_over_a"]}')
        print(f'envelope_p95_ratio_b_over_a={result["envelope_p95_ratio_b_over_a"]} '
              f'envelope_total_ratio_b_over_a={result["envelope_total_ratio_b_over_a"]}')
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1) + '\n')
    return result


if __name__ == '__main__':
    main()
