"""An upright phone lays out in landscape: the stage turns 90 degrees clockwise.

Touch-first portrait windows rotate the stage (#stage: the game canvas and
the letterbox bars) so the logical viewport is laid out for the long side;
canvas <-> window coordinates map through the rotation. Since 8d9b25e
(TASK-244) the turned stage is hidden and inert behind #rotate-prompt: a
portrait tap does not start a run, and turning the phone mid-run pauses it.
Turning to landscape re-lays out with no errors and the same tap starts the
run. Desktop portrait windows and landscape phones are not rotated.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import READY, canvas_to_viewport, open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent
PHONE = dict(has_touch=True, is_mobile=True, device_scale_factor=3)
PORTRAIT = {'width': 390, 'height': 844}
LANDSCAPE = {'width': 844, 'height': 390}

STATE = '''() => {
    const stage = document.getElementById('stage').getBoundingClientRect()
    const box = canvas.getBoundingClientRect()
    return {rotated: isViewRotated(), width: width, height: height,
            transform: document.getElementById('stage').style.transform,
            stage: {left: stage.left, top: stage.top, width: stage.width, height: stage.height},
            canvas: {left: box.left, top: box.top, width: box.width, height: box.height},
            scroll: [document.documentElement.scrollWidth, document.documentElement.scrollHeight]}
}'''

CENTER = '''(path) => { const b = eval(path).background
    return {x: b.x + b.width / 2, y: b.y + b.height / 2} }'''


class RotateLandscapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)

    def boot(self, viewport, **options):
        context, page, errors = open_game(self.browser, self.url, viewport, **options)
        self.addCleanup(context.close)
        page.wait_for_function(READY, timeout=15000)
        return page, errors

    def tap_button(self, page, path):
        c = page.evaluate(CENTER, path)
        point = canvas_to_viewport(page, c['x'], c['y'])
        size = page.viewport_size
        self.assertTrue(0 <= point['x'] <= size['width'] and 0 <= point['y'] <= size['height'],
                        point)
        page.touchscreen.tap(point['x'], point['y'])
        return point

    def assert_rotate_prompt(self, page):
        """Portrait phone (TASK-244): the prompt covers the hidden, inert stage."""
        self.assertTrue(page.locator('#rotate-prompt').is_visible())
        self.assertTrue(page.evaluate("document.getElementById('stage').inert"))
        self.assertFalse(page.locator('#canvas').is_visible())

    def test_backing_resolution_and_css_probe(self):
        for touch, dpr in [(True, 3), (True, 1), (False, 1), (False, 3)]:
            with self.subTest(touch=touch, dpr=dpr):
                # Four live pages (the last 1920x1080@3) overload a busy
                # host: each subtest closes its context before the next boots
                page, errors = self.boot(LANDSCAPE if touch else
                                         {'width': 1920, 'height': 1080},
                                         has_touch=touch, is_mobile=touch,
                                         device_scale_factor=dpr)
                result = page.evaluate("""() => {
                    configureCanvasViewport(canvas, ctx)
                    const css = getCanvasCssRect()
                    LAYOUT_PROBE.boxes = []
                    LAYOUT_PROBE.rect('button', 'floor', 0, 0, minTouchSize(), minTouchSize())
                    const probe = LAYOUT_PROBE.boxes[0]
                    LAYOUT_PROBE.boxes = null
                    visualEffects.bloom.resize()
                    return {css, backing: [canvas.width, canvas.height], probe,
                            lightScale: visualEffects.lightmap.scale,
                            bloomWidth: visualEffects.bloom.levels[0].canvas.width}
                }""")
                ratio = min(dpr, 2) if touch else dpr
                self.assertEqual(result['backing'],
                                 [int(result['css'][axis] * ratio + .5)
                                  for axis in ('width', 'height')])
                for axis in ('width', 'height'):
                    self.assertAlmostEqual(result['probe'][axis], 44, places=4)
                self.assertEqual(result['lightScale'], .15 if touch else .2)
                self.assertEqual(result['bloomWidth'],
                                 int(result['backing'][0] * (.2 if touch else .25)))
                self.assertFalse(errors['page'])
                page.context.close()

    def test_pointer_query_remains_live_without_recreating_queries(self):
        page, errors = self.boot(PORTRAIT)
        cdp = page.context.new_cdp_session(page)
        self.addCleanup(cdp.detach)
        page.evaluate('''() => {
            window.pointerQueryCalls = 0
            const original = window.matchMedia.bind(window)
            window.matchMedia = query => {
                ++window.pointerQueryCalls
                return original(query)
            }
        }''')
        for enabled in (True, False, True):
            cdp.send('Emulation.setTouchEmulationEnabled', {'enabled': enabled})
            page.wait_for_function('(expected) => isTouchFirstDevice() === expected', arg=enabled)
            self.assertEqual(page.evaluate('isViewRotated()'), enabled)
        self.assertEqual(page.evaluate('pointerQueryCalls'), 0)
        self.assertFalse(errors['page'])

    def test_portrait_phone_is_rotated_to_landscape(self):
        page, errors = self.boot(PORTRAIT, **PHONE)
        s = page.evaluate(STATE)
        self.assertTrue(s['rotated'])
        self.assertEqual(s['transform'], 'rotate(90deg)')
        # The logical viewport follows the long side: landscape aspect
        self.assertGreater(s['width'], s['height'])
        # The turned stage covers the window exactly, nothing scrolls
        for key, value in {'left': 0, 'top': 0, 'width': 390, 'height': 844}.items():
            self.assertAlmostEqual(s['stage'][key], value, delta=0.5, msg=key)
        self.assertEqual(s['scroll'], [390, 844])
        # The landscape phone screen is all play rect: no letterbox bars
        self.assertEqual(page.evaluate(
            "Array.from(document.getElementsByClassName('window-bar')).map(c => c.hidden)"),
            [True, True])
        # The canvas on screen is taller than wide (its long side runs down)
        self.assertGreater(s['canvas']['height'], s['canvas']['width'])
        # The touch floor is measured along the canvas, not the screen
        self.assertGreaterEqual(page.evaluate('minTouchSize() * getCanvasCssRect().height / height'),
                                43.99)
        # Canvas <-> window mapping round-trips
        back = page.evaluate('''() => { const p = canvasCoordsToViewportCoords({x: 300, y: 200})
            return viewportCoordsToCanvasCoords(p) }''')
        self.assertAlmostEqual(back['x'], 300, delta=1e-6)
        self.assertAlmostEqual(back['y'], 200, delta=1e-6)
        # Logical top-left lands on the screen's top-right (clockwise turn)
        corner = page.evaluate('canvasCoordsToViewportCoords({x: 0, y: 0})')
        self.assertGreater(corner['x'], PORTRAIT['width'] / 2)
        self.assertLess(corner['y'], PORTRAIT['height'] / 2)

        # The boot run (momentum since TASK-019) starts paused behind the prompt.
        # Upright, a tap on the pause screen's classic button lands on the
        # rotate prompt: no switch
        self.assert_rotate_prompt(page)
        self.assertEqual(page.evaluate('[menu.gamePaused, version]'), [True, 'momentum'])
        self.tap_button(page, "menu.modeSelector.button('classic')")
        page.wait_for_timeout(500)
        self.assertEqual(page.evaluate('[menu.gamePaused, version]'), [True, 'momentum'])

        # Turned to landscape, the same switch starts a classic run
        page.set_viewport_size(LANDSCAPE)
        page.wait_for_function('!isViewRotated() && !document.getElementById("stage").inert',
                               timeout=5000)
        page.wait_for_timeout(300)
        self.tap_button(page, "menu.modeSelector.button('classic')")
        page.wait_for_function('!menu.gamePaused && version === "classic"', timeout=5000)
        self.assertEqual(errors, {'console': [], 'page': []})

    def test_turning_the_phone_mid_run(self):
        page, errors = self.boot(PORTRAIT, **PHONE)
        portrait = page.evaluate(STATE)
        self.assert_rotate_prompt(page)

        page.set_viewport_size(LANDSCAPE)
        page.wait_for_function('!isViewRotated() && document.getElementById("stage").style.transform === ""',
                               timeout=5000)
        page.wait_for_timeout(300)
        landscape = page.evaluate(STATE)
        self.assertEqual(landscape['scroll'], [844, 390])
        self.assertGreater(landscape['canvas']['width'], landscape['canvas']['height'])
        # Same screen in both orientations: the same logical viewport
        self.assertEqual(landscape['width'], portrait['width'])
        # The boot run waited paused behind the prompt: resume it
        self.assertEqual(page.evaluate('[menu.gamePaused, version]'), [True, 'momentum'])
        self.tap_button(page, 'menu.resume')
        page.wait_for_function('!menu.gamePaused && version === "momentum"', timeout=5000)

        # Turned upright mid-run: re-laid out, the run pauses behind the prompt
        page.set_viewport_size(PORTRAIT)
        page.wait_for_function('isViewRotated() && document.getElementById("stage").style.transform !== ""',
                               timeout=5000)
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate(STATE)['width'], portrait['width'])
        self.assert_rotate_prompt(page)
        self.assertEqual(page.evaluate('[menu.gamePaused, version]'), [True, 'momentum'])

        page.set_viewport_size(LANDSCAPE)
        page.wait_for_function('!isViewRotated() && !document.getElementById("stage").inert',
                               timeout=5000)
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate(STATE)['width'], portrait['width'])
        self.assertEqual(errors, {'console': [], 'page': []})

    def test_desktop_portrait_window_is_not_rotated(self):
        page, errors = self.boot(PORTRAIT)
        s = page.evaluate(STATE)
        self.assertFalse(s['rotated'])
        self.assertEqual(s['transform'], '')
        self.assertGreater(s['canvas']['width'], s['canvas']['height'])
        self.assertEqual(errors, {'console': [], 'page': []})

    def test_landscape_phone_is_not_rotated(self):
        page, errors = self.boot(LANDSCAPE, **PHONE)
        s = page.evaluate(STATE)
        self.assertFalse(s['rotated'])
        self.assertEqual(s['transform'], '')
        self.assertEqual(errors, {'console': [], 'page': []})


if __name__ == '__main__':
    unittest.main()
