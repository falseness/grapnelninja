"""Tests for the background gradient cache (BackgroundRenderer, render/effects.js).

The game runs on render_snapshot's frozen clock (844x390@3, touch). An init
script counts every createLinearGradient / createRadialGradient call made from
the background's gradient cache (buildGradients), per frame. The cache must
create 3 gradients (base, haze, vignette) on the first background frame (the menu drawn at load), none
on the next 100 menu frames and 101 game frames, and rebuild them once (3)
after the canvas size changes. Gradients from any caller (lights,
grade, sprites) are counted too: after WARMUP_FRAMES game frames (the first
frames build the light and ninja sprite gradients), no game frame may create
one, except CubeTrackLine.draw: its moving endpoints require a fresh trail
gradient (TASK-184). The load-time creations are checked by caller: the 7
legacy ones, plus 3 momentum lighting caches that only exist with the
lighting switch on; with lighting stored off the load is the legacy 7 again.
Both loads also build the 8 crystal sprite gradients (CRYSTAL_CALLERS), all in
the load frame and all cached: 5 for the momentum obstacles of the first world
frame (MomentumObstacleFloor.draw) and 3 for the tutorial legend's real green
and blue pieces (tutorialhint.js, other sizes, so other sprites). No later
menu, startGame or game frame creates one.
Candidate: GRADIENT_REV (default worktree). GRADIENT_EVIDENCE_DIR (optional)
receives legend-stack.txt, the stacks of the load-time crystal creations.
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
# gradient cache (buildGradients, directly or via a helper), from page load on.
# The baked far tile's own gradients are built once per tile size and fall
# under the any-caller count.
COUNT_SCRIPT = '''(() => {
    Error.stackTraceLimit = 50
    const counter = window.__bgGradients = {frame: 0, all: 0, callers: {}, crystal: 0, crystalStacks: []}
    for (const name of ['createLinearGradient', 'createRadialGradient']) {
        const original = CanvasRenderingContext2D.prototype[name]
        CanvasRenderingContext2D.prototype[name] = function (...args) {
            // Hazard trails deliberately build a gradient from moving endpoints.
            const stack = new Error().stack
            if (!/CubeTrackLine\\.draw /.test(stack)) {
                counter.all++
                // First frame outside this wrapper: function name and file
                const m = /at (?:new )?([^ ]+) \\(.*\\/([^\\/]+\\.js):/.exec(stack.split('\\n')[2] || '')
                const caller = m ? m[1] + ' ' + m[2] : '?'
                counter.callers[caller] = (counter.callers[caller] || 0) + 1
                if (/crystalpieces\\.js:/.test(stack.split('\\n')[2] || '')) {
                    counter.crystal++
                    counter.crystalStacks.push(stack.split('\\n').slice(2).join('\\n'))
                }
            }
            if (/\\.buildGradients /.test(new Error().stack)) counter.frame++
            return original.apply(this, args)
        }
    }
})()'''

TAKE_ALL_SCRIPT = '''() => { const n = __bgGradients.all; __bgGradients.all = 0; return n }'''
TAKE_CRYSTAL_SCRIPT = '''() => {
    const r = {count: __bgGradients.crystal, stacks: __bgGradients.crystalStacks}
    __bgGradients.crystal = 0
    __bgGradients.crystalStacks = []
    return r
}'''
TAKE_CALLERS_SCRIPT = '''() => { const c = __bgGradients.callers; __bgGradients.callers = {}; return c }'''
# The momentum lighting switch stored off (PROGRESS reads it at boot)
LIGHTING_OFF_SCRIPT = '''localStorage.setItem('grapnelninja.lighting', 'false')'''

# Load-time creations by caller with lighting off (and on every tree before
# the momentum lighting): the background cache's base, haze and vignette
# (buildGradients, base and haze via createVerticalGradients), the baked far
# tile's base and haze (createVerticalGradients), the ninja's glow sprite and
# the tutorial hint sprite. No legacy washes.
LEGACY_CALLERS = {
    'BackgroundRenderer.createVerticalGradients effects.js': 4,
    'BackgroundRenderer.buildGradients effects.js': 1,
    'Ninja.getGlowSprite ninja.js': 1,
    'Object.build tutorialhint.js': 1,
}
# Momentum lighting caches built at load (MOMENTUM_FX on), each reused by later
# frames: the ninja light (LightmapRenderer.momentumGradient, via
# getMomentumGradient), the wall veins' light colour (LightmapRenderer.gradients,
# keyed by colour, via getLightGradient), both from createLightGradient; the
# deep shadow mask (LightmapRenderer.shadowGradient).
LIGHTING_CALLERS = {
    'LightmapRenderer.createLightGradient effects.js': 2,
    'LightmapRenderer.getShadowGradient effects.js': 1,
}
# Crystal piece sprites built at load (lighting on and off): green and blue
# sprite gradients and the glint star sprite, cached per piece / backing scale.
# CRYSTAL_SOURCES splits them by the frame on the stack: the first world
# frame's obstacles and the tutorial legend's real MomentumGreen / MomentumBlue.
CRYSTAL_CALLERS = {
    'Object.paintGreen crystalpieces.js': 3,
    'Object.paintBlue crystalpieces.js': 4,
    'Object.glintSprite crystalpieces.js': 1,
}
CRYSTAL_COUNT = sum(CRYSTAL_CALLERS.values())
CRYSTAL_SOURCES = {'world': 5, 'legend': 3}


def crystal_sources(stacks):
    """Load-time crystal creations by source: 'legend' (tutorialhint.js on the
    stack), 'world' (MomentumObstacleFloor.draw without the legend), else '?'."""
    counts = {}
    for s in stacks:
        source = ('legend' if 'tutorialhint.js' in s
                  else 'world' if 'MomentumObstacleFloor.draw ' in s else '?')
        counts[source] = counts.get(source, 0) + 1
    return counts
TAKE_SCRIPT = '''() => { const n = __bgGradients.frame; __bgGradients.frame = 0; return n }'''

MENU_SCRIPT = '''frames => {
    const counts = []
    for (let i = 0; i < frames; i++) {
        const b = visualEffects.background
        // Trees before TASK-407 still have the title menu's paintMenu
        const paint = () => b.paintMenu ? b.paintMenu() : b.paint()
        paint()
        b.drawWindowBars('menu', paint)
        counts.push(__bgGradients.frame)
        __bgGradients.frame = 0
    }
    return counts
}'''


def background_gradient_counts(rev, mode='bad', frames=FRAMES, lighting=True):
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
        if not lighting:
            context.add_init_script(LIGHTING_OFF_SCRIPT)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        context.add_init_script(COUNT_SCRIPT)
        page.goto(url + 'index.html', wait_until='load')
        render_snapshot.boot_frozen(page)
        load = page.evaluate(TAKE_SCRIPT)
        load_all = page.evaluate(TAKE_ALL_SCRIPT)
        load_callers = page.evaluate(TAKE_CALLERS_SCRIPT)
        load_crystal = page.evaluate(TAKE_CRYSTAL_SCRIPT)
        page.evaluate(render_snapshot.SETUP_SCRIPT, [script, True])
        menu = page.evaluate(MENU_SCRIPT, frames)
        page.evaluate('mode => startGame(mode)', mode)
        game = [page.evaluate(TAKE_SCRIPT)]
        game_all = [page.evaluate(TAKE_ALL_SCRIPT)]
        menu_crystal = page.evaluate(TAKE_CRYSTAL_SCRIPT)['count']
        for tick in range(1, frames + 1):
            page.evaluate(render_snapshot.ADVANCE_SCRIPT, tick)
            game.append(page.evaluate(TAKE_SCRIPT))
            game_all.append(page.evaluate(TAKE_ALL_SCRIPT))
        game_crystal = page.evaluate(TAKE_CRYSTAL_SCRIPT)['count']
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
        return {'rev': rev_id, 'mode': mode, 'frames': frames, 'load': load, 'load_all': load_all,
                'load_callers': load_callers, 'load_crystal': load_crystal,
                'menu_crystal': menu_crystal, 'game_crystal': game_crystal, 'menu': menu, 'game': game,
                'game_all': game_all,
                'resized_canvas': size, 'resized': resized, 'page_errors': errors}


class BackgroundGradientCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = background_gradient_counts(os.environ.get('GRADIENT_REV', 'worktree'))
        print('rev', cls.r['rev'], 'load', cls.r['load'], 'load_callers', cls.r['load_callers'], 'game[:3]', cls.r['game'][:3], 'resized', cls.r['resized'],
              'menu[:3]', cls.r['menu'][:3], 'game_all', cls.r['game_all'],
              'crystal load/menu+startGame/game', cls.r['load_crystal']['count'], cls.r['menu_crystal'], cls.r['game_crystal'])
        out = os.environ.get('GRADIENT_EVIDENCE_DIR')
        if out:
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, 'legend-stack.txt'), 'w') as f:
                stacks = cls.r['load_crystal']['stacks']
                f.write('# rev %s: %d crystal creations at load, by source %s; menu+startGame %d, game %d\n'
                        % (cls.r['rev'], len(stacks), crystal_sources(stacks),
                           cls.r['menu_crystal'], cls.r['game_crystal']))
                for i, s in enumerate(stacks):
                    f.write('# crystal creation %d at load: %s\n%s\n' % (i + 1, crystal_sources([s]), s))

    def test_no_page_errors(self):
        self.assertEqual(self.r['page_errors'], [])

    def test_first_frame_builds_all(self):
        self.assertEqual(self.r['load'], 3)
        # The 7 legacy creations, the 3 momentum lighting caches and the 8
        # crystal sprite gradients (5 first-frame world obstacles, 3 tutorial legend)
        self.assertEqual(self.r['load_callers'], {**LEGACY_CALLERS, **LIGHTING_CALLERS, **CRYSTAL_CALLERS})
        self.assertEqual(self.r['load_all'], 10 + CRYSTAL_COUNT)

    def test_crystal_gradients_built_at_load_only(self):
        stacks = self.r['load_crystal']['stacks']
        self.assertEqual(self.r['load_crystal']['count'], CRYSTAL_COUNT)
        self.assertEqual(crystal_sources(stacks), CRYSTAL_SOURCES)
        # The cached sprites are reused: no menu, startGame or game frame builds one
        self.assertEqual(self.r['menu_crystal'], 0)
        self.assertEqual(self.r['game_crystal'], 0)

    def test_lighting_off_load_builds_legacy_only(self):
        off = background_gradient_counts(os.environ.get('GRADIENT_REV', 'worktree'), frames=10, lighting=False)
        print('lighting off: load', off['load'], 'load_all', off['load_all'], 'load_callers', off['load_callers'])
        self.assertEqual(off['page_errors'], [])
        self.assertEqual(off['load'], 3)
        self.assertEqual(off['load_callers'], {**LEGACY_CALLERS, **CRYSTAL_CALLERS})
        self.assertEqual(off['load_all'], 7 + CRYSTAL_COUNT)
        self.assertEqual(off['load_crystal']['count'], CRYSTAL_COUNT)
        self.assertEqual(crystal_sources(off['load_crystal']['stacks']), CRYSTAL_SOURCES)
        self.assertEqual(off['game_crystal'], 0)

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
