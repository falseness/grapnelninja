"""Adaptive quality for slow canvases (render/backdrop.js).

Under Playwright (navigator.webdriver) the switch stays off without
?adaptive=1, so headless test frame rates never change what tests render.
With ?adaptive=1, BACKDROP.observe() is fed synthetic frame times (the real
game loop keeps running, so the state is reset first): a 2 s window of 30 ms
frames after the 5 s warm-up switches to the half-resolution backdrop; the
next slow window, after the 1 s settle, lowers the canvas resolution to 0.75
through a resize (canvas.width follows); fast 16 ms windows change nothing;
gaps over 250 ms (pauses, hidden tabs) are not counted. ?backdrop=1 turns the
switch off. A frame drawn with the fast backdrop has no page errors and the
backdrop canvas is half the frame size.
"""
from contextlib import ExitStack
from pathlib import Path
import unittest

from browser_test_support import start_browser_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}

class AdaptiveQualityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def open(self, query):
        context = self.browser.new_context(viewport=VIEWPORT)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url + 'index.html' + query, wait_until='load')
        page.wait_for_function('typeof bootComplete !== "undefined" && bootComplete', timeout=120000)
        # Only the synthetic frames below may reach the governor
        page.evaluate('''() => { const observe = BACKDROP.observe.bind(BACKDROP);
            window.__feedObserve = observe; BACKDROP.observe = () => {};
            Object.assign(BACKDROP, {firstAt: null, lastAt: null, windowMs: 0, windowFrames: 0, settleUntil: 0}) }''')
        return page, errors

    def feed(self, page, start, step_ms, duration_ms):
        return page.evaluate('''([start, stepMs, durationMs]) => {
            for (let t = start; t <= start + durationMs; t += stepMs) __feedObserve(t)
            return {scale: BACKDROP.scale, resolution: BACKDROP.resolution, adaptive: BACKDROP.adaptive}
        }''', [start, step_ms, duration_ms])

    def test_webdriver_stays_full_quality(self):
        page, errors = self.open('')
        self.assertFalse(page.evaluate('BACKDROP.adaptive'))
        state = self.feed(page, 1e9, 30, 12000)
        print('ASSERT webdriver without adaptive=1:', state, flush=True)
        self.assertEqual(state, {'scale': 1, 'resolution': 1, 'adaptive': False})
        self.assertEqual(errors, [])

    def test_forced_backdrop_turns_switch_off(self):
        page, errors = self.open('?adaptive=1&backdrop=1')
        state = self.feed(page, 1e9, 30, 12000)
        print('ASSERT backdrop=1:', state, flush=True)
        self.assertEqual(state, {'scale': 1, 'resolution': 1, 'adaptive': False})
        self.assertEqual(errors, [])

    def test_fast_frames_change_nothing(self):
        page, errors = self.open('?adaptive=1')
        state = self.feed(page, 1e9, 16, 12000)
        print('ASSERT 16 ms frames:', state, flush=True)
        self.assertEqual(state, {'scale': 1, 'resolution': 1, 'adaptive': True})
        # Slow frames separated by > 250 ms gaps are pauses, not frame time
        state = self.feed(page, 2e9, 300, 12000)
        print('ASSERT 300 ms gaps:', state, flush=True)
        self.assertEqual(state['scale'], 1)
        self.assertEqual(errors, [])

    def test_slow_frames_step_down(self):
        page, errors = self.open('?adaptive=1')
        width = page.evaluate('canvas.width')
        # Warm-up (5 s) then one 2 s window of 30 ms frames
        state = self.feed(page, 1e9, 30, 7100)
        print('ASSERT first slow window:', state, flush=True)
        self.assertEqual((state['scale'], state['resolution']), (0.5, 1))
        page.wait_for_function('BACKDROP.canvas && BACKDROP.canvas.width > 0')
        sizes = page.evaluate('[BACKDROP.canvas.width, canvas.width]')
        print('ASSERT backdrop canvas / frame width:', sizes, flush=True)
        self.assertEqual(sizes[0], round(sizes[1] * 0.5))
        # Settle (1 s) then the next slow window lowers the resolution
        state = self.feed(page, 1e9 + 7130, 30, 3100)
        print('ASSERT second slow window:', state, flush=True)
        self.assertEqual(state['resolution'], 0.75)
        page.wait_for_function(f'canvas.width === Math.round({width} * 0.75)', timeout=10000)
        print(f'ASSERT canvas.width {width} -> {page.evaluate("canvas.width")}', flush=True)
        page.wait_for_function('BACKDROP.canvas.width === Math.round(canvas.width * 0.5)', timeout=10000)
        self.assertEqual(errors, [])
        print('PASS slow windows: fast backdrop, then resolution 0.75', flush=True)


if __name__ == '__main__':
    unittest.main()
