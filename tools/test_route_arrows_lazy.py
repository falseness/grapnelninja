#!/usr/bin/env python3
"""Lazy route arrows during a climb (TASK-890).

render/routearrows.js computes, at run start (warmRouteArrows), only the arrows whose guide box lies
within one view of the camera; a live draw() then computes the rest nearest to the view first under
ROUTE_ARROWS.budgetMs (buildPendingRouteArrows), and drawRouteArrows computes a missing arrow whose
guide box reaches the view before drawing it (stats.sameFrame in a live frame). This tool boots
index.html on the manual clock of test_boot_steady_state.py (seed 1, en-US, the game's own loop draws
every step) and moves the world camera along the route: through the guide midpoints of every
transfer in order, at --speed-factor times the ninja's speed cap (screenHeightPercent(
GAMEPLAY.ninjaMaxSpeedHeightPercent) per physics step) of path length per 60 Hz frame. Only draw()
sees the moved camera (draw is wrapped: screen is set for the draw and restored), so gameplay is
untouched.

Per arrow it records the drawFrameId and phase it was computed in (warm = before the first frame,
queue = buildPendingRouteArrows, draw = inside drawRouteArrows, other = routeArrowsFor) and the
drawFrameId it was first drawn in. Pass: every arrow drawn, computed before (warm, or an earlier
frame) the frame that first draws it, stats.sameFrame == 0 and no phase 'draw' compute.

The manual clock freezes performance.now(), so a time budget never runs out there: --budget-ms
(default 0) sets ROUTE_ARROWS.budgetMs before boot, and 0 means exactly one arrow per frame (the
queue's minimum, slower than any real budget), the harshest case for staying ahead of the camera.

Usage:
  python3 tools/test_route_arrows_lazy.py [--size desktop-1366x768@1] [--speed-factor 2] [--budget-ms 0]
                                          [--out FILE] [--zip PATH | --root DIR]
With no arguments under unittest (run_regression) it runs the default climb and asserts the pass.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import boot_timing as bt  # noqa: E402
import test_boot_steady_state as steady  # noqa: E402
from perf_mobile import SEED_SCRIPT  # noqa: E402
from render_snapshot import boot_frozen  # noqa: E402

DEFAULT_SIZE = 'desktop-1366x768@1'

# Before boot: wraps the per-arrow compute to log the frame and phase of every arrow
HOOK_SCRIPT = r'''(() => {
    const log = window.__arrowLog = {computed: {}, firstDrawn: {}, phase: 'other', frames: []}
    const wrap = (name, phase) => {
        const original = window[name]
        window[name] = function(...args)
        {
            const saved = log.phase
            log.phase = phase
            try { return original.apply(this, args) }
            finally { log.phase = saved }
        }
    }
    addEventListener('DOMContentLoaded', () => {
        ROUTE_ARROWS.budgetMs = window.__arrowBudgetMs
        const compute = window.computeRouteArrow
        window.computeRouteArrow = function(state, i)
        {
            const arrow = compute(state, i)
            log.computed[arrow.id] = {frame: drawFrameId, phase: log.phase}
            return arrow
        }
        wrap('warmRouteArrows', 'warm')
        wrap('buildPendingRouteArrows', 'queue')
        wrap('drawRouteArrows', 'draw')
        const draw = window.drawRouteArrows
        window.drawRouteArrows = function(world)
        {
            const r = draw(world)
            for (const id of ROUTE_ARROWS.drawn)
                if (!(id in log.firstDrawn))
                    log.firstDrawn[id] = drawFrameId
            return r
        }
    })
})()'''

SETUP_JS = r'''speedFactor => {
    const perStep = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)
    const stepsPerFrame = (1000 / 60) / physicsStepMs
    const transfers = floors[0].level.svgFormat.transfers.filter(t => t.guide)
    const points = transfers.map(t => {
        const g = t.guide
        return [(g[0][0] + g[3][0]) / 2, (g[0][1] + g[3][1]) / 2]
    })
    const halfW = width / scale[version] / 2, halfH = height / scale[version] / 2
    const start = [halfW - screen.x, halfH - screen.y]
    const path = [start, ...points]
    const climb = window.__climb = {stepPerFrame: perStep * stepsPerFrame * speedFactor, path, seg: 0, f: 0,
                                    centre: start.slice(), active: false}
    const original = window.draw
    window.draw = function()
    {
        if (!climb.active)
            return original()
        const sx = screen.x, sy = screen.y
        screen.x = halfW - climb.centre[0]
        screen.y = halfH - climb.centre[1]
        try { return original() }
        finally { screen.x = sx; screen.y = sy }
    }
    return {stepPerFrame: climb.stepPerFrame, perStep, stepsPerFrame, transfers: transfers.length, start,
            statsAtSetup: JSON.parse(JSON.stringify(ROUTE_ARROWS.stats))}
}'''

CLIMB_JS = r'''() => {
    const climb = window.__climb, path = climb.path
    climb.active = true
    let frames = 0
    // Walks the polyline by stepPerFrame world units per frame
    while (climb.seg < path.length - 1)
    {
        let left = climb.stepPerFrame
        while (left > 0 && climb.seg < path.length - 1)
        {
            const a = climb.centre, b = path[climb.seg + 1]
            const d = Math.hypot(b[0] - a[0], b[1] - a[1])
            if (d <= left) { climb.centre = b.slice(); climb.seg++; left -= d }
            else { climb.centre = [a[0] + (b[0] - a[0]) * left / d, a[1] + (b[1] - a[1]) * left / d]; left = 0 }
        }
        __snap.step()
        ++frames
    }
    for (let i = 0; i < 5; ++i) __snap.step()
    const log = window.__arrowLog
    return {frames, end: climb.centre, stats: ROUTE_ARROWS.stats, computed: log.computed, firstDrawn: log.firstDrawn,
            pendingAfter: routeArrowsPending(), budgetMs: ROUTE_ARROWS.budgetMs, warmScreens: ROUTE_ARROWS.warmScreens,
            liveFlagAtEnd: GLYPH_GLOW_QUEUE.defer}
}'''


def run(size_name=DEFAULT_SIZE, speed_factor=2.0, zip_path=None, root=None, budget_ms=0.0):
    size = bt.SIZES[size_name]
    errors = []
    with ExitStack() as stack:
        site = bt.serve_root(zip_path, root, stack.callback)
        browsers = bt.Browsers(site, stack)
        browser, url = browsers.get(size['browser'])
        ctx = browser.new_context(locale='en-US', **bt.context_options(size, bt.DEVICES))
        stack.callback(ctx.close)
        ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())
        ctx.add_init_script(SEED_SCRIPT % steady.SEED)
        ctx.add_init_script(steady.CLOCK_SCRIPT)
        ctx.add_init_script('window.__arrowBudgetMs = %r' % float(budget_ms))
        ctx.add_init_script(HOOK_SCRIPT)
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html', wait_until='load')
        boot_frozen(page)
        state = page.evaluate(steady.ADVANCE, 0)
        if not (state['bootComplete'] and state['runInProgress']):
            raise RuntimeError('run not started after boot: %s' % state)
        setup = page.evaluate(SETUP_JS, speed_factor)
        result = page.evaluate(CLIMB_JS)
    computed, first = result['computed'], result['firstDrawn']
    ids = ['T%02d' % (i + 1) for i in range(setup['transfers'])]
    rows = {}
    late = []
    for tid in ids:
        c, d = computed.get(tid), first.get(tid)
        rows[tid] = [c and c['frame'], c and c['phase'], d]
        if d is not None and (c is None or c['phase'] == 'draw' or (c['phase'] != 'warm' and c['frame'] >= d)):
            late.append(tid)
    phases = {}
    for c in computed.values():
        phases[c['phase']] = phases.get(c['phase'], 0) + 1
    checks = {
        'every_arrow_computed': len(computed) == setup['transfers'],
        'every_arrow_drawn': len(first) == setup['transfers'],
        'computed_before_first_drawn': not late,
        'same_frame_counter_zero': result['stats']['sameFrame'] == 0,
        'no_draw_phase_compute': phases.get('draw', 0) == 0,
        'none_pending_after': not result['pendingAfter'],
        'budget_applied': result['budgetMs'] == budget_ms,
        'no_page_errors': not errors,
    }
    return {
        'tool': 'tools/test_route_arrows_lazy.py', 'size': size_name, 'speed_factor': speed_factor,
        'source': bt.describe_source(zip_path, root), 'setup': setup, 'climb_frames': result['frames'],
        'budget_ms': result['budgetMs'], 'budget_ms_requested': budget_ms,
        'queue_frames': sorted({c['frame'] for c in computed.values() if c['phase'] == 'queue'}).__len__(), 'warm_screens': result['warmScreens'],
        'stats': result['stats'], 'same_frame_counter': result['stats']['sameFrame'],
        'computed_by_phase': phases, 'late': late,
        'last_queue_frame': max((c['frame'] for c in computed.values() if c['phase'] == 'queue'), default=None),
        'arrows': {'columns': ['computed_frame', 'phase', 'first_drawn_frame'], 'rows': rows},
        'page_errors': errors, 'checks': checks, 'pass': all(checks.values()),
    }


class RouteArrowsLazyTest(unittest.TestCase):
    def test_climb_computes_arrows_ahead(self):
        report = run()
        self.assertTrue(report['pass'], json.dumps({k: report[k] for k in
                        ('checks', 'stats', 'late', 'computed_by_phase', 'page_errors')}))


def main(argv):
    if not argv:
        unittest.main(argv=[sys.argv[0]])
        return 0
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    src = p.add_mutually_exclusive_group()
    src.add_argument('--zip')
    src.add_argument('--root')
    p.add_argument('--size', default=DEFAULT_SIZE)
    p.add_argument('--speed-factor', type=float, default=2.0)
    p.add_argument('--budget-ms', type=float, default=0.0)
    p.add_argument('--out')
    a = p.parse_args(argv)
    report = run(a.size, a.speed_factor, a.zip, a.root, a.budget_ms)
    if a.out:
        Path(a.out).write_text(json.dumps(report, separators=(',', ':')) + '\n')
    print(json.dumps({k: report[k] for k in ('size', 'climb_frames', 'stats', 'computed_by_phase',
                                             'same_frame_counter', 'budget_ms', 'queue_frames', 'last_queue_frame', 'checks', 'pass')}))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
