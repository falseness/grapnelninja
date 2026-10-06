"""itch.io 'Mobile Friendly' on phones: 'Click to launch in fullscreen'.

The TASK-166 harness in its fullscreen launch mode (?launch=fullscreen): the
game iframe is a fixed 100vw x 100vh overlay over the host page. Each case
emulates a phone (touch, mobile viewport, its DPR and user agent), taps to
launch, checks the menu layout, starts a classic run by touch, throws the
grapnel by touch, tries a double-tap and a pinch zoom, checks that nothing
scrolls, then rotates the phone mid-run.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import OfflineBrowser
from itch_harness import start_itch_embed
import layout_matrix
import test_itch_embed as embed
from playwright.sync_api import sync_playwright

# (case name, Playwright descriptor for UA and DPR, portrait viewport, landscape?)
CASES = [
    ('iphone13-portrait', 'iPhone 13', (390, 844), False),
    ('iphone13-landscape', 'iPhone 13', (390, 844), True),
    ('pixel7-portrait', 'Pixel 7', (412, 915), False),
    ('pixel7-landscape', 'Pixel 7', (412, 915), True),
    ('iphonese-portrait', 'iPhone SE', (375, 667), False),
    ('iphonese-landscape', 'iPhone SE', (375, 667), True),
    ('android360-portrait', 'Galaxy S5', (360, 640), False),
    ('android360-landscape', 'Galaxy S5', (360, 640), True),
]
MIN_TOUCH = 44
EPS = 0.5

# Physics ticks, counted without touching the run
COUNT_TICKS = '''() => {
    if (window.__countingTicks) return
    window.__countingTicks = true
    window.__ticks = 0
    const physicsStep = window.physics
    window.physics = function() {
        window.__ticks++
        return physicsStep.apply(this, arguments)
    }
}'''
RUN_STATE = '''() => ({ticks: window.__ticks, ninjaX: ninja.x, ninjaY: ninja.y,
    grapnelThrown: !!(grapnel && grapnel.throwed), version: version,
    menuVisible: menu.visible, paused: menu.gamePaused})'''
VIEWPORT_STATE = '''() => ({scale: visualViewport.scale, scrollX: scrollX, scrollY: scrollY,
    innerWidth: innerWidth, innerHeight: innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight})'''


class ItchMobileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host_url, cls.game_origin, cls.game_url, _ = start_itch_embed(cls.addClassCleanup)
        cls.host_url = host_url + '?launch=fullscreen'
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        browser = cls.playwright.chromium.launch(args=['--no-sandbox'])
        cls.addClassCleanup(browser.close)
        cls.browser = OfflineBrowser(browser)
        cls.save_evidence = bool(os.environ.get('ITCH_MOBILE_EVIDENCE_DIR'))
        cls.evidence = Path(os.environ.get('ITCH_MOBILE_EVIDENCE_DIR') or '.')
        cls.results = []

    @classmethod
    def save_results(cls):
        if cls.save_evidence:
            cls.evidence.mkdir(parents=True, exist_ok=True)
            (cls.evidence / 'devices.json').write_text(json.dumps(cls.results, indent=1) + '\n')

    def shot(self, page, name):
        if self.save_evidence:
            path = self.evidence / 'screens' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path))

    def open(self, descriptor, viewport):
        device = self.playwright.devices[descriptor]
        context = self.browser.new_context(
            viewport=viewport, screen=viewport, user_agent=device['user_agent'],
            device_scale_factor=device['device_scale_factor'], is_mobile=True, has_touch=True)
        self.addCleanup(context.close)
        context.add_init_script(embed.ERROR_SPY)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(self.host_url)
        return page, errors

    def touch(self, page, kind, points):
        """One touch event; a touch sequence must stay in one CDP session."""
        if not hasattr(page, '_touch_cdp'):
            page._touch_cdp = page.context.new_cdp_session(page)
        page._touch_cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': points})

    def double_tap(self, page, x, y):
        for _ in range(2):
            self.touch(page, 'touchStart', [{'x': x, 'y': y}])
            self.touch(page, 'touchEnd', [])
            page.wait_for_timeout(80)

    def pinch(self, page, x, y, spread=120, steps=10):
        """Two fingers 40 px apart moving away from each other by 2 * spread."""
        fingers = lambda d: [{'x': x - 20 - d, 'y': y, 'id': 1}, {'x': x + 20 + d, 'y': y, 'id': 2}]
        self.touch(page, 'touchStart', fingers(0))
        for i in range(1, steps + 1):
            self.touch(page, 'touchMove', fingers(spread * i / steps))
            page.wait_for_timeout(16)
        self.touch(page, 'touchEnd', [])

    def tap_button(self, page, frame, name):
        point = frame.evaluate(embed.BUTTON_CENTER, name)
        page.touchscreen.tap(point['x'], point['y'])

    def menu_layout(self, frame, viewport):
        """Menu boxes in frame CSS px (= host px, the overlay is at 0,0)."""
        probe = frame.evaluate(layout_matrix.PROBE, layout_matrix.DRAW['menu'])
        row, boxes = layout_matrix.evaluate(probe, True)
        c = probe['canvas']
        w, h = viewport
        buttons = []
        for b in boxes:
            if b['kind'] != 'button':
                continue
            box = {'name': b['name'], 'x': round(c['left'] + b['x'], 2), 'y': round(c['top'] + b['y'], 2),
                   'width': round(b['width'], 2), 'height': round(b['height'], 2)}
            box['inside_viewport'] = (box['x'] >= -EPS and box['y'] >= -EPS and
                                      box['x'] + box['width'] <= w + EPS and
                                      box['y'] + box['height'] <= h + EPS)
            buttons.append(box)
        return {'canvas': c, 'buttons': buttons, 'layout_matrix': {
            k: row[k] for k in ('clipped', 'overlaps', 'min_font_px', 'min_button_px', 'scrollbar', 'failures')}}

    def run_case(self, name, descriptor, portrait, landscape):
        viewport = (portrait[1], portrait[0]) if landscape else portrait
        rotated = viewport[::-1]
        w, h = viewport
        result = {'case': name, 'device': descriptor, 'viewport': {'width': w, 'height': h},
                  'dpr': self.playwright.devices[descriptor]['device_scale_factor']}
        self.results.append(result)
        page, errors = self.open(descriptor, {'width': w, 'height': h})
        try:
            # Tap to launch: the iframe covers the whole phone viewport
            self.assertEqual(page.inner_text('#load_game'), 'Click to launch in fullscreen')
            page.tap('#load_game')
            frame = page.wait_for_selector('#game_drop').content_frame()
            frame.wait_for_function(embed.READY)
            frame.evaluate(COUNT_TICKS)
            result['iframe_box'] = page.locator('#game_drop').bounding_box()
            self.assertEqual(result['iframe_box'], {'x': 0, 'y': 0, 'width': w, 'height': h})
            self.assertEqual(frame.evaluate('[innerWidth, innerHeight]'), [w, h])

            # The menu fits: every button inside the viewport and >= 44 CSS px
            page.wait_for_timeout(300)
            self.shot(page, f'{name}-menu.png')
            result['menu'] = self.menu_layout(frame, viewport)
            buttons = result['menu']['buttons']
            result['min_touch'] = min(min(b['width'], b['height']) for b in buttons)
            result['buttons_outside'] = [b['name'] for b in buttons if not b['inside_viewport']]

            # Tap 'classic', then hold a finger on the field: the grapnel flies
            self.tap_button(page, frame, 'classicVersionButton')
            frame.wait_for_function('version === "classic" && !menu.visible')
            ticks = frame.evaluate('window.__ticks')
            frame.wait_for_function('t => window.__ticks > t + 10', arg=ticks)
            page.wait_for_timeout(400)  # past STYLE.timing.inputUntouchMs
            before = frame.evaluate(RUN_STATE)
            self.touch(page, 'touchStart', [{'x': w * 0.75, 'y': h * 0.3}])
            frame.wait_for_function('grapnel && grapnel.throwed')
            frame.wait_for_function('t => window.__ticks > t + 10', arg=before['ticks'])
            during = frame.evaluate(RUN_STATE)
            self.touch(page, 'touchEnd', [])
            result['touch'] = {'before': before, 'during': during}
            self.shot(page, f'{name}-play.png')

            # Double-tap and pinch over the game do not zoom anything
            self.double_tap(page, w / 2, h / 2)
            page.wait_for_timeout(400)
            result['after_double_tap'] = {'host': page.evaluate(VIEWPORT_STATE),
                                          'frame': frame.evaluate(VIEWPORT_STATE)}
            self.pinch(page, w / 2, h / 2, spread=min(w, h) / 4)
            page.wait_for_timeout(400)
            result['after_pinch'] = {'host': page.evaluate(VIEWPORT_STATE),
                                     'frame': frame.evaluate(VIEWPORT_STATE)}
            # Control: the same pinch over the bare host page does zoom it
            control = page.context.new_page()
            control.goto(self.host_url)
            self.pinch(control, w / 2, h * 0.7, spread=min(w, h) / 4)
            control.wait_for_function('visualViewport.scale > 1')
            result['control_pinch_host_scale'] = control.evaluate('visualViewport.scale')
            control.close()
            result['scale_after_double_tap'] = result['after_double_tap']['host']['scale']
            result['scale_after_pinch'] = result['after_pinch']['host']['scale']

            # Rotate mid-run: the run goes on in the resized play rect
            rect_before = frame.evaluate(embed.CANVAS)
            ticks = frame.evaluate('window.__ticks')
            page.set_viewport_size({'width': rotated[0], 'height': rotated[1]})
            frame.wait_for_function('s => innerWidth === s[0] && innerHeight === s[1]', arg=list(rotated))
            page.wait_for_timeout(500)  # the game re-lays out 100 ms after resize
            frame.wait_for_function('t => window.__ticks > t + 20', arg=ticks)
            result['rotate'] = {'to': {'width': rotated[0], 'height': rotated[1]},
                                'play_rect_before': rect_before, 'play_rect_after': frame.evaluate(embed.CANVAS),
                                'iframe_box_after': page.locator('#game_drop').bounding_box(),
                                'ticks_before': ticks, 'state_after': frame.evaluate(RUN_STATE),
                                'host_after': page.evaluate(VIEWPORT_STATE)}
            self.shot(page, f'{name}-rotated.png')
            result['page_errors'] = len(errors) + len(embed.ItchEmbedTests.frame_errors(self, page, frame))
            result['errors'] = errors + embed.ItchEmbedTests.frame_errors(self, page, frame)
        finally:
            self.save_results()

        self.assertEqual(result['buttons_outside'], [])
        self.assertEqual(result['menu']['layout_matrix']['clipped'], [])
        self.assertGreaterEqual(len(buttons), 3)
        self.assertGreaterEqual(result['min_touch'], MIN_TOUCH)
        self.assertGreater(during['ticks'], before['ticks'])
        self.assertTrue(during['grapnelThrown'])
        self.assertFalse(before['grapnelThrown'])
        self.assertNotEqual((during['ninjaX'], during['ninjaY']), (before['ninjaX'], before['ninjaY']))
        for key in ('after_double_tap', 'after_pinch'):
            for where in ('host', 'frame'):
                state = result[key][where]
                self.assertEqual(state['scale'], 1, (key, where))
                self.assertEqual((state['scrollX'], state['scrollY']), (0, 0), (key, where))
            self.assertLessEqual(result[key]['frame']['scrollHeight'], result[key]['frame']['innerHeight'])
            self.assertLessEqual(result[key]['frame']['scrollWidth'], result[key]['frame']['innerWidth'])
        self.assertGreater(result['control_pinch_host_scale'], 1)
        rotate = result['rotate']
        after = rotate['play_rect_after']
        self.assertEqual(rotate['iframe_box_after'], {'x': 0, 'y': 0, 'width': rotated[0], 'height': rotated[1]})
        self.assertEqual((after['innerWidth'], after['innerHeight']), rotated)
        self.assertNotEqual((after['cssWidth'], after['cssHeight']),
                            (rotate['play_rect_before']['cssWidth'], rotate['play_rect_before']['cssHeight']))
        self.assertLessEqual(after['cssWidth'], rotated[0] + EPS)
        self.assertLessEqual(after['cssHeight'], rotated[1] + EPS)
        state = rotate['state_after']
        self.assertGreater(state['ticks'], rotate['ticks_before'] + 20)
        self.assertEqual(state['version'], 'classic')
        self.assertFalse(state['menuVisible'])
        self.assertEqual((rotate['host_after']['scrollX'], rotate['host_after']['scrollY']), (0, 0))
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['page_errors'], 0)


def _make_test(case):
    return lambda self: self.run_case(*case)


for _case in CASES:
    setattr(ItchMobileTests, 'test_' + _case[0].replace('-', '_'), _make_test(_case))


if __name__ == '__main__':
    unittest.main()
