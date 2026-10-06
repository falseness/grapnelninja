"""Tests for off-screen culling of floor elements and tracks (render/culling.js).

Helper cases run in the page against the bounds test: inside, partly inside,
just outside the padded edge (and exactly on it) and far outside, plus the
element and track boxes. The in-page run steps bad and classic on
render_snapshot's frozen clock (844x390@3, touch) for FRAMES ticks at the base
rev (before culling) and at CULL_REV (default worktree): element draw() calls
per frame must drop while the canvas captures stay byte-identical.
CULL_BASE defaults to the parent of the commit that added render/culling.js,
or HEAD while it is not committed yet.
"""
from contextlib import ExitStack
import base64
import hashlib
import os
import statistics
import subprocess
import unittest

from browser_test_support import start_browser_test
from perf_mobile import ROOT, SEED_SCRIPT, export_rev
import render_snapshot

FRAMES = 600
CAPTURE_TICKS = [60, 300, 600]
VIEWPORT = render_snapshot.VIEWPORTS[0]

# Init script: wraps every floor element's draw() (once per instance, like
# perf_mobile --layers) and counts element draws and shadowBlur draws per frame.
COUNT_SCRIPT = '''(() => {
    const counter = window.__cull = {frame: null, frames: []}
    const proto = CanvasRenderingContext2D.prototype
    for (const name of ['fill', 'stroke', 'fillRect', 'strokeRect', 'fillText', 'strokeText']) {
        const f = proto[name]
        proto[name] = function(...args) {
            if (counter.frame && this.shadowBlur > 0) counter.frame.shadow_draws++
            return f.apply(this, args)
        }
    }
    addEventListener('load', () => {
        const world = window.drawWorldLayer
        window.drawWorldLayer = function() {
            for (const floor of floors)
                for (const element of floor.elements) {
                    if (Object.prototype.hasOwnProperty.call(element, 'draw')) continue
                    element.draw = function() {
                        if (counter.frame) counter.frame.element_draws++
                        return Object.getPrototypeOf(element).draw.call(element)
                    }
                }
            return world()
        }
        const step = __snap.step
        __snap.step = () => {
            counter.frame = {element_draws: 0, shadow_draws: 0}
            step()
            counter.frames.push(counter.frame)
            counter.frame = null
        }
    })
})()'''

HELPER_SCRIPT = '''() => {
    const rect = {left: 0, top: 0, right: 100, bottom: 100}
    const box = (left, top, right, bottom) => ({left, top, right, bottom})
    const padded = getCullRect()
    const pad = getCullPadding()
    const o = STYLE.badVersionEffects.obstacles
    const trampoline = {getPoints: () => [{x: 0, y: 0}, {x: 10, y: 0, curvature: {x: 5, y: -40}}, {x: 10, y: 10}]}
    const cubeTrack = {pos: [{x: 0, y: 0}, {x: 20, y: 5}], lineWidth: 6, width: 6, height: 8}
    const triangleTrack = {pos: [[{x: 0, y: 0}, {x: 4, y: 0}, {x: 2, y: 3}], [{x: 0, y: 9}, {x: 4, y: 9}, {x: 2, y: 12}]], lineWidth: 4}
    return {
        inside: isBoxInCullRect(box(10, 10, 20, 20), rect),
        partly_inside: isBoxInCullRect(box(-5, 90, 5, 110), rect),
        just_outside_left: isBoxInCullRect(box(padded.left - 10, 0, padded.left - 0.001, 1), padded),
        just_outside_bottom: isBoxInCullRect(box(0, padded.bottom + 0.001, 1, padded.bottom + 10), padded),
        on_padded_edge: isBoxInCullRect(box(padded.right, 0, padded.right + 10, 1), padded),
        far_outside: isBoxInCullRect(box(padded.right + 1e5, 0, padded.right + 1e5 + 10, 1), padded),
        padded_rect: padded,
        view: {left: -screen.x, right: -screen.x + width / scale[version], top: -screen.y, bottom: -screen.y + height / scale[version]},
        pad,
        min_pad: 2 * Math.max(STYLE.strokes.neonGlowWidth, o.outerGlowWidth, STYLE.trails.hazard.glowBlur) / scale[version]
            + Math.max(STYLE.strokes.seamWidth, o.outerGlowWidth),
        empty_box: getElementCullBox(new Empty()),
        empty_visible: isCullBoxVisible(null, padded),
        trampoline_box: getElementCullBox(trampoline),
        cube_track_box: getTrackCullBox(cubeTrack),
        triangle_track_box: getTrackCullBox(triangleTrack),
        empty_track_box: getTrackCullBox(new Empty()),
    }
}'''


def default_base():
    added = subprocess.check_output(['git', 'log', '--diff-filter=A', '--format=%H', '--', 'render/culling.js'],
                                    cwd=ROOT, text=True).split()
    return added[-1] + '~1' if added else 'HEAD'


def draw_counts(rev, modes=('bad', 'classic'), frames=FRAMES, helpers=False):
    """Per mode: per-frame element draws and shadowBlur draws over frames ticks,
    and the sha256 of the black-composited capture at CAPTURE_TICKS."""
    result = {'modes': {}, 'page_errors': []}
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        result['rev'] = rev_id
        url, browser = start_browser_test(root, stack.callback)
        script = render_snapshot.input_script(render_snapshot.SEED, frames,
                                              VIEWPORT['width'], VIEWPORT['height'])
        for mode in modes:
            context = browser.new_context(viewport={'width': VIEWPORT['width'], 'height': VIEWPORT['height']},
                                          device_scale_factor=VIEWPORT['dpr'], is_mobile=True, has_touch=True)
            context.add_init_script(SEED_SCRIPT % render_snapshot.SEED)
            context.add_init_script(render_snapshot.CLOCK_SCRIPT)
            context.add_init_script(COUNT_SCRIPT)
            page = context.new_page()
            page.on('pageerror', lambda e, m=mode: result['page_errors'].append(f'{m}: {e}'))
            page.goto(url + 'index.html', wait_until='load')
            render_snapshot.boot_frozen(page)
            page.evaluate(render_snapshot.SETUP_SCRIPT, [script, True])
            page.evaluate('mode => startGame(mode)', mode)
            if helpers and mode == modes[0]:
                result['helpers'] = page.evaluate(HELPER_SCRIPT)
            captures = {}
            for tick in CAPTURE_TICKS:
                page.evaluate(render_snapshot.ADVANCE_SCRIPT, tick)
                data = base64.b64decode(page.evaluate('() => __snap.capture()').split(',', 1)[1])
                captures[tick] = hashlib.sha256(data).hexdigest()
            counts = page.evaluate('() => __cull.frames')[-frames:]
            context.close()
            element = [c['element_draws'] for c in counts]
            shadow = [c['shadow_draws'] for c in counts]
            result['modes'][mode] = {
                'frames': len(counts),
                'element_draws_median': statistics.median(element),
                'element_draws_mean': sum(element) / len(element),
                'shadow_draws_median': statistics.median(shadow),
                'shadow_draws_mean': sum(shadow) / len(shadow),
                'captures': captures,
            }
    return result


class OffscreenCullingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_rev = os.environ.get('CULL_BASE') or default_base()
        cls.after = draw_counts(os.environ.get('CULL_REV', 'worktree'), helpers=True)
        cls.before = draw_counts(cls.base_rev)
        cls.h = cls.after['helpers']
        for name, r in [('before', cls.before), ('after', cls.after)]:
            print(name, r['rev'], {m: (v['element_draws_median'], v['shadow_draws_median'])
                                   for m, v in r['modes'].items()})
        print('helpers', cls.h)

    def test_no_page_errors(self):
        self.assertEqual(self.before['page_errors'], [])
        self.assertEqual(self.after['page_errors'], [])

    def test_helper_inside_and_partly_inside(self):
        self.assertTrue(self.h['inside'])
        self.assertTrue(self.h['partly_inside'])
        self.assertTrue(self.h['on_padded_edge'])

    def test_helper_outside(self):
        self.assertFalse(self.h['just_outside_left'])
        self.assertFalse(self.h['just_outside_bottom'])
        self.assertFalse(self.h['far_outside'])

    def test_helper_rect_is_view_plus_padding(self):
        rect, view, pad = self.h['padded_rect'], self.h['view'], self.h['pad']
        self.assertGreaterEqual(pad, self.h['min_pad'])
        for side, sign in [('left', -1), ('top', -1), ('right', 1), ('bottom', 1)]:
            self.assertAlmostEqual(rect[side], view[side] + sign * pad, places=6)

    def test_helper_boxes(self):
        self.assertIsNone(self.h['empty_box'])
        self.assertTrue(self.h['empty_visible'])
        self.assertIsNone(self.h['empty_track_box'])
        self.assertEqual(self.h['trampoline_box'], {'left': 0, 'top': -40, 'right': 10, 'bottom': 10})
        self.assertEqual(self.h['cube_track_box'], {'left': -8, 'top': -8, 'right': 28, 'bottom': 13})
        self.assertEqual(self.h['triangle_track_box'], {'left': -4, 'top': -4, 'right': 8, 'bottom': 16})

    def test_element_draws_drop(self):
        for mode in ('bad', 'classic'):
            self.assertLess(self.after['modes'][mode]['element_draws_mean'],
                            self.before['modes'][mode]['element_draws_mean'], mode)

    def test_captures_unchanged(self):
        for mode in ('bad', 'classic'):
            self.assertEqual(self.after['modes'][mode]['captures'], self.before['modes'][mode]['captures'], mode)


if __name__ == '__main__':
    unittest.main()
