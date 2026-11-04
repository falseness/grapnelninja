#!/usr/bin/env python3
"""Parallax band builds during a climb (TASK-889).

render/parallax.js builds, in a live frame, only the parallax tiles the frame draws (the bands at
the camera height); the other bands are queued and built one per later frame (BACKGROUND_BAKE_QUEUE,
nearest band first). This tool boots index.html on the manual clock of test_boot_steady_state.py
(seed 1, en-US, 1000/60 ms per step, the game's own loop draws every step) and then climbs the
background camera from the start band to the top of the last band, at --speed-factor times the
fastest climb the physics allows (the ninja's vertical speed cap, screenHeightPercent(
GAMEPLAY.ninjaMaxSpeedHeightPercent) per physics step, times the physics steps of one 60 Hz frame).
The camera of the background only is moved (drawBackgroundLayer is wrapped: screen.y is set for the
background and restored), so the world and the gameplay are untouched.

Per parallax tile it records the drawFrameId it was built in (and why: initial = drawn in the
frame of a scale change, i.e. the boot frame; ahead = from the queue; late = needed by a frame
before the queue reached it; sync = outside a live frame) and first drawn in
(GRAPPLE_OVER_PARALLAX_TILES.log). Pass: every band of every layer drawn, no tile built in the frame
it is first drawn other than the boot frame's (same_frame_after_boot == 0), stats.late == 0.

Usage:
  python3 tools/test_parallax_band_builds.py [--size desktop-1366x768@1] [--speed-factor 2]
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

SETUP_JS = r'''speedFactor => {
    const theme = GRAPPLE_OVER_THEME
    const perStep = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)
    const stepsPerFrame = (1000 / 60) / physicsStepMs
    const climb = window.__climb = {
        risePerFrame: perStep * stepsPerFrame * speedFactor, rise: null, top: theme.bandHeight * theme.palettes.length,
        frames: 0, bands: [], startRise: null
    }
    const original = drawBackgroundLayer
    window.drawBackgroundLayer = function()
    {
        if (climb.rise === null)
            return original()
        const saved = screen.y
        // grappleOverBackdropPalette(height / scale / 2 - screen.y): rise = -cameraY
        screen.y = height / scale[version] / 2 + climb.rise
        try { return original() }
        finally
        {
            const p = visualEffects.background.palette
            climb.bands.push([drawFrameId, Math.round(climb.rise), p && p.from, p && p.to, p && +p.t.toFixed(3)])
            screen.y = saved
        }
    }
    return {risePerFrame: climb.risePerFrame, perStep, stepsPerFrame, physicsStepMs, top: climb.top,
            startRise: height / scale[version] / 2 - screen.y}
}'''

CLIMB_JS = r'''() => {
    const climb = window.__climb
    climb.rise = height / scale[version] / 2 - screen.y
    climb.startRise = climb.rise
    let frames = 0
    while (climb.rise < climb.top)
    {
        __snap.step()
        climb.rise += climb.risePerFrame
        ++frames
    }
    // a few more at the top
    for (let i = 0; i < 5; ++i) __snap.step()
    const store = GRAPPLE_OVER_PARALLAX_TILES
    const tiles = {}
    for (const [key, built] of store.log.built)
        tiles[key] = {built_frame: built.frame, why: built.why, first_drawn_frame: store.log.drawn.get(key) ?? null}
    for (const [key, frame] of store.log.drawn)
        if (!tiles[key]) tiles[key] = {built_frame: null, why: null, first_drawn_frame: frame}
    return {frames, startRise: climb.startRise, endRise: climb.rise, stats: store.stats, tiles,
            pendingAfter: store.pending.length, bakeJobsAfter: BACKGROUND_BAKE_QUEUE.jobs.length,
            bakesBuilt: BACKGROUND_BAKE_QUEUE.built, gradientDither: GRADIENT_DITHER.enabled,
            scaleFrame: store.scaleFrame, scale: store.scale,
            layers: GRAPPLE_OVER_PARALLAX.layers.map(l => [l.name, l.motifs.length]),
            bandsSampled: climb.bands.filter((b, i) => i % 25 == 0), bandsSeen: [...new Set(climb.bands.flatMap(b => [b[2], b[3]]))].sort((a, b) => a - b)}
}'''


def run(size_name=DEFAULT_SIZE, speed_factor=2.0, zip_path=None, root=None):
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
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html', wait_until='load')
        boot_frozen(page)
        for _ in range(4):
            page.evaluate(steady.ADVANCE, 1)
            page.wait_for_timeout(5)
        state = page.evaluate(steady.ADVANCE, 0)
        if not (state['bootComplete'] and state['runInProgress']):
            raise RuntimeError('run not started after boot: %s' % state)
        setup = page.evaluate(SETUP_JS, speed_factor)
        result = page.evaluate(CLIMB_JS)
    tiles = result['tiles']
    expected = sum(n for _, n in result['layers'])
    boot_frame = result['scaleFrame']
    same_frame = sorted(k for k, t in tiles.items()
                        if t['built_frame'] is not None and t['built_frame'] == t['first_drawn_frame'])
    same_frame_after_boot = [k for k in same_frame if tiles[k]['built_frame'] != boot_frame]
    drawn = [k for k, t in tiles.items() if t['first_drawn_frame'] is not None]
    never_built = [k for k, t in tiles.items() if t['built_frame'] is None]
    checks = {
        'every_tile_drawn': len(drawn) == expected,
        'every_drawn_tile_built': not never_built,
        'same_frame_after_boot_zero': not same_frame_after_boot,
        'late_zero': result['stats']['late'] == 0,
        'every_band_seen': result['bandsSeen'] == list(range(expected // len(result['layers']))),
        'no_page_errors': not errors,
    }
    return {
        'tool': 'tools/test_parallax_band_builds.py', 'size': size_name, 'speed_factor': speed_factor,
        'source': bt.describe_source(zip_path, root), 'setup': setup,
        'climb_frames': result['frames'], 'start_rise': result['startRise'], 'end_rise': result['endRise'],
        'tiles_expected': expected, 'tiles_drawn': len(drawn), 'stats': result['stats'],
        'boot_frame': boot_frame, 'same_frame_built_and_drawn': same_frame,
        'same_frame_after_boot': same_frame_after_boot,
        'same_frame_after_boot_count': len(same_frame_after_boot),
        'pending_after': result['pendingAfter'], 'bake_jobs_after': result['bakeJobsAfter'],
        'background_bakes_built': result['bakesBuilt'], 'gradient_dither': result['gradientDither'],
        'tiles': dict(sorted(tiles.items(), key=lambda kv: (kv[1]['first_drawn_frame'] or 0, kv[0]))),
        'bands_seen': result['bandsSeen'], 'bands_sampled': result['bandsSampled'],
        'page_errors': errors, 'checks': checks, 'pass': all(checks.values()),
    }


class ParallaxBandBuildsTest(unittest.TestCase):
    def test_climb_builds_bands_ahead(self):
        report = run()
        self.assertTrue(report['pass'], json.dumps({k: report[k] for k in
                        ('checks', 'stats', 'same_frame_after_boot', 'page_errors')}))


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
    p.add_argument('--out')
    a = p.parse_args(argv)
    report = run(a.size, a.speed_factor, a.zip, a.root)
    text = json.dumps(report, indent=1)
    if a.out:
        Path(a.out).write_text(text + '\n')
    print(json.dumps({k: report[k] for k in ('size', 'climb_frames', 'stats', 'same_frame_after_boot_count',
                                             'checks', 'pass')}))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
