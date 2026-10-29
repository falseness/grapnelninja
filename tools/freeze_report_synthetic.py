#!/usr/bin/env python3
"""Headless ?visualsPerf=1 exports with injected stalls for tools/freeze_report.py (TASK-777).

    python3 tools/freeze_report_synthetic.py <out_dir>

Writes synthetic-busy.json, synthetic-idle.json and synthetic-canvas.json
(full exports, schemaVersion 3) and synthetic-check.json: for each, the
injected stall's freeze (the longest after the injection) and its label. The
busy and idle stalls reuse BUSY / IDLE from tools/test_visualsperf_attribution.py;
the canvas burst is a test page script that creates 8 canvases and holds the
main thread 150 ms right after one game frame. Headless has no GPU, so
only labels are checked, never timings. Headless game frames
allocate ~2 MB each and V8 scavenges every few frames, so an idle 300 ms
would usually contain a scavenge (heapDropMB >= 2, gc-suspect first): the
idle stall is injected right after a frame whose heap just dropped. Exit code 1 when a label is wrong.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot  # noqa: E402
from freeze_report import analyse  # noqa: E402
from test_visualsperf_attribution import BUSY, FRAMES, IDLE, ROOT, STALL_MS, VIEWPORT  # noqa: E402

# One-shot wrapper over the game loop: right after the game's next frame,
# create n canvases and hold the main thread 150 ms, so the burst and the
# stall land in the same recorder interval
CANVAS_BURST = '''n => {
    const loop = window.gameLoop
    window.gameLoop = function() {
        window.gameLoop = loop
        const result = loop.apply(this, arguments)
        window.__burst = Array.from({length: n}, () => document.createElement('canvas'))
        const end = performance.now() + 150
        while (performance.now() < end) {}
        return result
    }
}'''

# IDLE, armed on the first frame whose used heap fell (a scavenge just ran)
SETTLED_IDLE = '''ms => new Promise(resolve => {
    const idle = %s
    let last = performance.memory.usedJSHeapSize
    const check = () => {
        const now = performance.memory.usedJSHeapSize
        if (now < last) {
            idle(ms)
            // the game's next rAF takes the override, not a later caller's
            setTimeout(resolve, ms + 200)
        }
        else {
            last = now
            requestAnimationFrame(check)
        }
    }
    requestAnimationFrame(check)
})''' % IDLE

CASES = [
    ('busy', BUSY, STALL_MS, 'main-thread-script'),
    ('idle', SETTLED_IDLE, STALL_MS, 'render-or-present'),
    ('canvas', CANVAS_BURST, 8, 'canvas-churn'),
]


def record(browser, url, script, arg):
    context = browser.new_context(viewport=VIEWPORT)
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html?visualsPerf=1', wait_until='load')
        wait_for_boot(page)
        page.evaluate('visualsPerf.start()')
        page.evaluate(FRAMES, 30)
        injected_at = page.evaluate('performance.now()')
        page.evaluate(script, arg)
        page.evaluate(FRAMES, 20)
        page.wait_for_function('visualsPerf.export().sourceHashFailures !== null')
        report = page.evaluate('visualsPerf.stop()')
        if errors:
            raise RuntimeError(f'page errors: {errors}')
        return report, injected_at
    finally:
        context.close()


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not out:
        print(__doc__)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    checks, ok = {}, True
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback, chromium_args=['--enable-precise-memory-info'])
        for name, script, arg, expected in CASES:
            report, injected_at = record(browser, url, script, arg)
            (out / f'synthetic-{name}.json').write_text(json.dumps(report, indent=1) + '\n')
            _, rows = analyse(report)
            after = [r for r in rows if r['t'] is not None and r['t'] > injected_at]
            stall = max(after, key=lambda r: r['gapMs']) if after else None
            freeze = report['freezes'][stall['index']] if stall else None
            passed = bool(stall) and stall['label'] == expected
            ok = ok and passed
            checks[name] = {'expected': expected, 'pass': passed, 'injectedAt': injected_at,
                            'schemaVersion': report.get('schemaVersion'), 'buildId': report.get('buildId'),
                            'freezes': len(rows), 'stall': stall,
                            'heapDropMB': freeze and freeze.get('heapDropMB'),
                            'canvasesCreated': freeze and freeze['context'].get('canvasesCreated'),
                            'loafs': freeze and len(freeze['context'].get('loafs') or [])}
            print(f'{"PASS" if passed else "FAIL"} {name}: expected {expected}, got '
                  f'{stall and stall["label"]} (gapMs {stall and stall["gapMs"]}, '
                  f'mainThreadSilenceMs {stall and stall["mainThreadSilenceMs"]})', flush=True)
    (out / 'synthetic-check.json').write_text(json.dumps(checks, indent=1) + '\n')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
