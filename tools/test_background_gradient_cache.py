"""Tests for the background gradient cache (BackgroundRenderer, render/effects.js).

The game runs on render_snapshot's frozen clock (844x390@3, touch). An init
script counts every createLinearGradient / createRadialGradient call made from
the background's drawBaseGradient, drawHaze or drawVignette, per frame. The cache must
create 3 gradients (base, haze, vignette) on the first background frame (the menu drawn at load), none
on the next 100 menu frames and 101 game frames, and rebuild them once (3)
after the canvas size changes. Gradients from any caller (lights,
grade, sprites) are counted too: after WARMUP_FRAMES game frames (the first
frames build the light and ninja sprite gradients), no game frame may create
one, except CubeTrackLine.draw: its moving endpoints require a fresh trail
gradient (TASK-184). Candidate: GRADIENT_REV (default worktree).
"""
from contextlib import ExitStack
import os
import unittest

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot

FRAMES = 100
WARMUP_FRAMES = 2
VIEWPORT = render_snapshot.VIEWPORTS[0]

# Init script: counts gradient creations whose caller is the background's
# drawBaseGradient/drawHaze/drawVignette (directly or via a helper), from page load on.
COUNT_SCRIPT = '''(() => {
    const counter = window.__bgGradients = {frame: 0, all: 0}
    for (const name of ['createLinearGradient', 'createRadialGradient']) {
        const original = CanvasRenderingContext2D.prototype[name]
        CanvasRenderingContext2D.prototype[name] = function (...args) {
            // Hazard trails deliberately build a gradient from moving endpoints.
            if (!/CubeTrackLine\\.draw /.test(new Error().stack)) counter.all++
            if (/\\.(drawBaseGradient|drawHaze|drawVignette) /.test(new Error().stack)) counter.frame++
            return original.apply(this, args)
        }
    }
})()'''

TAKE_ALL_SCRIPT = '''() => { const n = __bgGradients.all; __bgGradients.all = 0; return n }'''
TAKE_SCRIPT = '''() => { const n = __bgGradients.frame; __bgGradients.frame = 0; return n }'''

MENU_SCRIPT = '''frames => {
    const counts = []
    for (let i = 0; i < frames; i++) {
        visualEffects.background.drawMenuBackground()
        counts.push(__bgGradients.frame)
        __bgGradients.frame = 0
    }
    return counts
}'''


def background_gradient_counts(rev, mode='bad', frames=FRAMES):
    """Per-frame background gradient creations: 'load' (the menu drawn at page load,
    the first background frame), 'menu' (frames more menu frames), 'game' (startGame
    then frames game frames), 'resized' (10 game frames after a canvas size change)."""
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        script = render_snapshot.input_script(render_snapshot.SEED, frames + 20,
                                              VIEWPORT['width'], VIEWPORT['height'])
        context = browser.new_context(viewport={'width': VIEWPORT['width'], 'height': VIEWPORT['height']},
                                      device_scale_factor=VIEWPORT['dpr'],
                                      is_mobile=True, has_touch=True)
        stack.callback(context.close)
        context.add_init_script(SEED_SCRIPT % render_snapshot.SEED)
        context.add_init_script(render_snapshot.CLOCK_SCRIPT)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        context.add_init_script(COUNT_SCRIPT)
        page.goto(url + 'index.html', wait_until='load')
        render_snapshot.boot_frozen(page)
        load = page.evaluate(TAKE_SCRIPT)
        load_all = page.evaluate(TAKE_ALL_SCRIPT)
        page.evaluate(render_snapshot.SETUP_SCRIPT, [script, True])
        menu = page.evaluate(MENU_SCRIPT, frames)
        page.evaluate('mode => startGame(mode)', mode)
        game = [page.evaluate(TAKE_SCRIPT)]
        game_all = [page.evaluate(TAKE_ALL_SCRIPT)]
        for tick in range(1, frames + 1):
            page.evaluate(render_snapshot.ADVANCE_SCRIPT, tick)
            game.append(page.evaluate(TAKE_SCRIPT))
            game_all.append(page.evaluate(TAKE_ALL_SCRIPT))
        # Trees with live re-layout: a real window resize changes the logical
        # size; older trees: bump the canvas backing store
        page.set_viewport_size({'width': VIEWPORT['width'] + 60, 'height': VIEWPORT['height']})
        size = page.evaluate('''() => {
            const c = visualEffects.background.canvas
            if (typeof onViewportResize == 'function')
                onViewportResize()
            else
            {
                c.width = c.width + 10
                c.height = c.height + 10
            }
            return [c.width, c.height]
        }''')
        resized = []
        for tick in range(frames + 1, frames + 11):
            page.evaluate(render_snapshot.ADVANCE_SCRIPT, tick)
            resized.append(page.evaluate(TAKE_SCRIPT))
        return {'rev': rev_id, 'mode': mode, 'frames': frames, 'load': load, 'load_all': load_all, 'menu': menu, 'game': game,
                'game_all': game_all,
                'resized_canvas': size, 'resized': resized, 'page_errors': errors}


class BackgroundGradientCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = background_gradient_counts(os.environ.get('GRADIENT_REV', 'worktree'))
        print('rev', cls.r['rev'], 'load', cls.r['load'], 'game[:3]', cls.r['game'][:3], 'resized', cls.r['resized'],
              'menu[:3]', cls.r['menu'][:3], 'game_all', cls.r['game_all'])

    def test_no_page_errors(self):
        self.assertEqual(self.r['page_errors'], [])

    def test_first_frame_builds_all(self):
        self.assertEqual(self.r['load'], 3)
        # Base, haze, vignette plus two warmed ninja sprites; no legacy washes.
        self.assertEqual(self.r['load_all'], 5)

    def test_next_frames_build_none(self):
        self.assertEqual(self.r['menu'], [0] * FRAMES)
        self.assertEqual(self.r['game'], [0] * (FRAMES + 1))

    def test_no_gradient_of_any_kind_after_warmup(self):
        self.assertEqual(self.r['game_all'][WARMUP_FRAMES:], [0] * (FRAMES + 1 - WARMUP_FRAMES))

    def test_canvas_size_change_rebuilds_once(self):
        self.assertEqual(self.r['resized'][0], 3)
        self.assertEqual(self.r['resized'][1:], [0] * (len(self.r['resized']) - 1))


if __name__ == '__main__':
    unittest.main()
