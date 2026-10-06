"""An upright phone plays in landscape: the stage turns 90 degrees clockwise.

Touch-first portrait windows rotate the stage (#stage: the game canvas and
the letterbox bars) so the logical viewport is laid out for the long side;
taps map through the rotation; turning the phone mid-run re-lays out with
no errors. Desktop portrait windows and landscape phones are not rotated.
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
        self.assertTrue(0 <= point['x'] <= PORTRAIT['width'] and 0 <= point['y'] <= PORTRAIT['height'],
                        point)
        page.touchscreen.tap(point['x'], point['y'])
        return point

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

        self.tap_button(page, 'menu.classicVersionButton')
        page.wait_for_function('!menu.visible && version === "classic"', timeout=5000)
        self.assertEqual(errors, {'console': [], 'page': []})

    def test_turning_the_phone_mid_run(self):
        page, errors = self.boot(PORTRAIT, **PHONE)
        self.tap_button(page, 'menu.badVersionButton')
        page.wait_for_function('!menu.visible && version === "bad"', timeout=5000)
        portrait = page.evaluate(STATE)

        page.set_viewport_size(LANDSCAPE)
        page.wait_for_function('!isViewRotated() && document.getElementById("stage").style.transform === ""',
                               timeout=5000)
        page.wait_for_timeout(300)
        landscape = page.evaluate(STATE)
        self.assertEqual(landscape['scroll'], [844, 390])
        self.assertGreater(landscape['canvas']['width'], landscape['canvas']['height'])
        # Same screen in both orientations: the same logical viewport
        self.assertEqual(landscape['width'], portrait['width'])

        page.set_viewport_size(PORTRAIT)
        page.wait_for_function('isViewRotated() && document.getElementById("stage").style.transform !== ""',
                               timeout=5000)
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate(STATE)['width'], portrait['width'])
        self.assertFalse(page.evaluate('menu.visible'))
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
