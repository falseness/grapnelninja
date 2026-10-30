"""Live canvas memory on the freeze-walk, read from the ?visualsPerf=1 recorder.

Headless Chromium at the user's recording size (1706x932, DPR 1.5) in Grapple
Over, the same walk as tools/canvas_audit.py (tools/fixtures/freeze-walk.json:
2 passes over the points, then the sweep). After the hold at each point the
page is garbage collected (--expose-gc) and the recorder is stopped, so its
canvasSnapshot (liveCanvasMB and liveCanvasByCreator, TASK-786) is read, then
started again. A canvas the game no longer references is collected first, so
the numbers are the canvases the game keeps: a deterministic sum of canvas
sizes (width * height * 4), not a timing. Output: peak (the largest snapshot,
with its creators), final snapshot, and per point {phase, point, mb, count}.

    python3 tools/canvas_memory_walk.py [--root TREE] [--quick] [--out canvas-memory.json]

--root serves another tree (e.g. a git archive of an older commit) with this
script's walk; --quick does one pass and every other sweep point.
"""
import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402

WALK = ROOT / 'tools/fixtures/freeze-walk.json'
VIEWPORT = {'width': 1706, 'height': 932}
DPR = 1.5
HOLD_STEPS = 6       # x 250 ms at each walk point
SWEEP_STEPS = 4      # x 250 ms at each sweep point

HOLD = '([x, y]) => { ninja.x = x; ninja.y = y; ninja.speedX = 0; ninja.speedY = 0 }'
SNAPSHOT = '''() => {
    gc(); gc()
    const report = visualsPerf.stop()
    visualsPerf.start({walk: true})
    return report.canvasSnapshot
}'''


def hold(page, point, steps):
    for _ in range(steps):
        page.evaluate(HOLD, point)
        page.wait_for_timeout(250)


def walk_memory(root, quick=False):
    walk = json.loads(WALK.read_text())
    errors, rows, peak = [], [], None
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback, chromium_args=('--js-flags=--expose-gc',))
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=DPR)
        stack.callback(context.close)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)[:300]))
        page.goto(url + 'index.html?visualsPerf=1', wait_until='load')
        wait_for_boot_run(page)
        if page.evaluate('version') != 'grapple_over':
            errors.append('not booted into grapple_over: ' + page.evaluate('version'))
        page.evaluate('() => visualsPerf.start({walk: true})')
        page.wait_for_timeout(3000)

        def snapshot(phase, point):
            nonlocal peak
            snap = page.evaluate(SNAPSHOT)
            rows.append({'phase': phase, 'point': point, 'mb': snap['liveCanvasMB'], 'count': snap['liveCanvases']})
            if peak is None or snap['liveCanvasMB'] > peak['liveCanvasMB']:
                peak = dict(snap, phase=phase, point=point)
            return snap

        snapshot('boot', None)
        for n in ((1,) if quick else (1, 2)):
            for point in walk['points']:
                hold(page, point, HOLD_STEPS)
                snapshot('pass%d' % n, point)
        for point in walk['sweep'][::2] if quick else walk['sweep']:
            hold(page, point, SWEEP_STEPS)
            snapshot('sweep', point)
        final = page.evaluate('() => visualsPerf.export().canvasSnapshot')
        build = page.evaluate('() => visualsPerf.export().buildId')
    def by_mb(snap):
        return dict(sorted(snap['liveCanvasByCreator'].items(), key=lambda kv: -kv[1]['mb']))
    peak['liveCanvasByCreator'] = by_mb(peak)
    final['liveCanvasByCreator'] = by_mb(final)
    return {'viewport': [VIEWPORT['width'], VIEWPORT['height'], DPR], 'root': str(root), 'quick': quick,
            'buildId': build, 'peakLiveCanvasMB': peak['liveCanvasMB'], 'peak': peak, 'final': final,
            'points': rows, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', default=str(ROOT), help='tree to serve (default: this checkout)')
    parser.add_argument('--quick', action='store_true', help='one pass, every other sweep point')
    parser.add_argument('--out', default='canvas-memory.json')
    args = parser.parse_args()
    result = walk_memory(Path(args.root).resolve(), args.quick)
    Path(args.out).write_text(json.dumps(result, indent=1) + '\n')
    peak = result['peak']
    print('peak liveCanvasMB %.1f (%d canvases) at %s %s; final %.1f; errors %d -> %s' % (
        peak['liveCanvasMB'], peak['liveCanvases'], peak['phase'], peak['point'],
        result['final']['liveCanvasMB'], len(result['errors']), args.out))
    for creator, row in list(peak['liveCanvasByCreator'].items())[:10]:
        print('  %8.2f MB x%-3d %s' % (row['mb'], row['count'], creator))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
