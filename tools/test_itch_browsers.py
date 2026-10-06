"""Cross-browser smoke of the itch.io embed: Chromium, Firefox and WebKit (Safari engine).

Per browser, the TASK-166 desktop flow (click to play, menu, a classic run and a
bad run to a death and back to the menu, itch's fullscreen button and exit) and
the TASK-168 iPhone 13 portrait flow (tap to launch in fullscreen, the menu fits,
tap 'classic', a tap throws the grapnel, double-tap keeps scale 1, rotation
mid-run). Only portable Playwright input is used (no CDP): pinch zoom and touch
scrolling stay Chromium-only in test_itch_embed and test_itch_mobile.

Firefox has no is_mobile emulation, so its phone case is has_touch + the iPhone
UA and DPR in a 390x844 viewport.

ITCH_BROWSERS=chromium,firefox,webkit picks the browsers (default: all three).
ITCH_BROWSERS_EVIDENCE_DIR saves results.json and screens/<browser>-*.png.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import OfflineBrowser
from itch_harness import start_itch_embed
import test_itch_embed as embed
import test_itch_mobile as mobile
from playwright.sync_api import sync_playwright

BROWSERS = [b for b in os.environ.get('ITCH_BROWSERS', 'chromium,firefox,webkit').split(',') if b]
PHONE = 'iPhone 13'
PHONE_VIEWPORT = (390, 844)

# Runs after the game's own document touchstart handler: was the grapnel thrown by it?
WATCH_TOUCH = '''() => {
    window.__touchThrows = []
    document.addEventListener('touchstart',
        () => window.__touchThrows.push(!!(grapnel && grapnel.throwed)), {passive: true})
}'''


class ItchBrowserFlows:
    browser_name = None
    # Portable helpers of the Chromium-only modules (mouse and touchscreen, no CDP)
    play = embed.ItchEmbedTests.play
    click_game = embed.ItchEmbedTests.click_game
    click_button = embed.ItchEmbedTests.click_button
    start_version = embed.ItchEmbedTests.start_version
    menu_layout = mobile.ItchMobileTests.menu_layout
    tap_button = mobile.ItchMobileTests.tap_button

    @classmethod
    def setUpClass(cls):
        cls.host_url, cls.game_origin, cls.game_url, _ = start_itch_embed(cls.addClassCleanup)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        launcher = getattr(cls.playwright, cls.browser_name)
        args = ['--no-sandbox'] if cls.browser_name == 'chromium' else []
        browser = launcher.launch(args=args)
        cls.addClassCleanup(browser.close)
        cls.version = browser.version
        cls.browser = OfflineBrowser(browser)
        cls.save_evidence = bool(os.environ.get('ITCH_BROWSERS_EVIDENCE_DIR'))
        cls.evidence = Path(os.environ.get('ITCH_BROWSERS_EVIDENCE_DIR') or '.')

    def shot(self, page, name):
        if self.save_evidence:
            path = self.evidence / 'screens' / f'{self.browser_name}-{name}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path))

    def save(self, flow, result):
        if not self.save_evidence:
            return
        self.evidence.mkdir(parents=True, exist_ok=True)
        path = self.evidence / 'results.json'
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault(self.browser_name, {'version': self.version})[flow] = result
        path.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n')

    def new_page(self, **options):
        context = self.browser.new_context(**options)
        self.addCleanup(context.close)
        context.add_init_script(embed.ERROR_SPY)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        return page, errors

    def frame_errors(self, page, frame):
        return page.evaluate('window.__errors') + frame.evaluate('window.__errors')

    def canvas_fills(self, frame, w, h):
        """Wait until the frame is w x h and the canvas fills it (WebKit/Firefox lay out in subpixels)."""
        frame.wait_for_function('''s => { const r = canvas.getBoundingClientRect()
            return innerWidth === s[0] && innerHeight === s[1] &&
                Math.abs(r.width - s[0]) < s[2] && Math.abs(r.height - s[1]) < s[2] }''',
                                arg=[w, h, mobile.EPS])

    def assertBox(self, box, expected):
        for key, value in expected.items():
            self.assertAlmostEqual(box[key], value, delta=mobile.EPS, msg=(key, box))

    def test_desktop_embed(self):
        page, errors = self.new_page(viewport=embed.VIEWPORT, screen=embed.SCREEN)
        page.goto(self.host_url)
        frame = self.play(page)
        result = {'menu_canvas': frame.evaluate(embed.CANVAS),
                  'iframe_box': page.locator('#game_drop').bounding_box()}
        page.wait_for_timeout(300)
        self.shot(page, 'embed-menu')

        # A classic run and a bad run, each to a real death and back to the menu
        runs = []
        for version in ('classic', 'bad'):
            self.start_version(page, frame, version)
            if version == 'classic':
                self.shot(page, 'play')
            restarts = frame.evaluate('window.__reStarts')
            frame.evaluate('window.__kill = true')
            frame.wait_for_function('r => !window.__kill && window.__reStarts > r', arg=restarts)
            page.wait_for_timeout(300)
            in_run = frame.evaluate('!menu.visible && !continueOffer.visible')
            page.keyboard.press('Escape')
            frame.wait_for_function('menu.gamePaused')
            self.click_button(page, frame, 'backToMenu')
            frame.wait_for_function('menu.visible && !menu.gamePaused')
            runs.append(frame.evaluate('''v => ({version: v, deaths: window.__reStarts,
                menuVisible: menu.visible})''', version) | {'in_run_after_death': in_run})
        result['runs'] = runs

        # itch's fullscreen button, then exit
        page.click('#fullscreen_btn')
        page.wait_for_function('document.fullscreenElement && document.fullscreenElement.id === "game_drop"')
        # Headless Firefox goes fullscreen at its own 1366x768 screen, not the emulated one
        screen = page.evaluate('[innerWidth, innerHeight]')
        result['fullscreen_host_inner'] = screen
        self.canvas_fills(frame, *screen)
        page.wait_for_timeout(300)
        result['fullscreen_canvas'] = frame.evaluate(embed.CANVAS)
        result['fullscreen_iframe_box'] = page.locator('#game_drop').bounding_box()
        self.shot(page, 'fullscreen')
        page.evaluate('document.exitFullscreen()')
        page.wait_for_function('!document.fullscreenElement')
        self.canvas_fills(frame, *embed.FRAME)
        result['after_exit_canvas'] = frame.evaluate(embed.CANVAS)
        result['errors'] = errors + self.frame_errors(page, frame)
        self.save('desktop', result)

        self.assertBox(result['iframe_box'], {'width': embed.FRAME[0], 'height': embed.FRAME[1]})
        self.assertBox(result['menu_canvas'], {'cssWidth': embed.FRAME[0], 'cssHeight': embed.FRAME[1]})
        self.assertEqual([r['deaths'] for r in runs], [1, 2])
        self.assertTrue(all(r['menuVisible'] and r['in_run_after_death'] for r in runs))
        full = result['fullscreen_canvas']
        self.assertBox(result['fullscreen_iframe_box'], {'x': 0, 'y': 0, 'width': screen[0], 'height': screen[1]})
        self.assertBox(full, {'left': 0, 'top': 0, 'cssWidth': screen[0], 'cssHeight': screen[1]})
        self.assertEqual((full['backingWidth'], full['backingHeight']), tuple(screen))
        after = result['after_exit_canvas']
        self.assertBox(after, {'cssWidth': 960, 'cssHeight': 540})
        self.assertEqual((after['backingWidth'], after['backingHeight']), embed.FRAME)
        self.assertEqual(result['errors'], [])

    def test_iphone13_portrait(self):
        device = self.playwright.devices[PHONE]
        w, h = PHONE_VIEWPORT
        options = dict(viewport={'width': w, 'height': h}, screen={'width': w, 'height': h},
                       user_agent=device['user_agent'], device_scale_factor=device['device_scale_factor'],
                       has_touch=True)
        if self.browser_name != 'firefox':
            options['is_mobile'] = True
        page, errors = self.new_page(**options)
        page.goto(self.host_url + '?launch=fullscreen')
        result = {'emulation': {k: v for k, v in options.items() if k != 'user_agent'}}
        self.assertEqual(page.inner_text('#load_game'), 'Click to launch in fullscreen')
        page.tap('#load_game')
        frame = page.wait_for_selector('#game_drop').content_frame()
        frame.wait_for_function(embed.READY)
        frame.evaluate(mobile.COUNT_TICKS)
        frame.evaluate(WATCH_TOUCH)
        result['iframe_box'] = page.locator('#game_drop').bounding_box()
        result['frame_inner'] = frame.evaluate('[innerWidth, innerHeight]')
        page.wait_for_timeout(300)
        result['menu'] = self.menu_layout(frame, PHONE_VIEWPORT)
        buttons = result['menu']['buttons']
        result['min_touch'] = min(min(b['width'], b['height']) for b in buttons)
        result['buttons_outside'] = [b['name'] for b in buttons if not b['inside_viewport']]
        self.shot(page, 'mobile')

        # Tap 'classic', then a tap on the field throws the grapnel
        self.tap_button(page, frame, 'classicVersionButton')
        frame.wait_for_function('version === "classic" && !menu.visible')
        ticks = frame.evaluate('window.__ticks')
        frame.wait_for_function('t => window.__ticks > t + 10', arg=ticks)
        page.wait_for_timeout(400)  # past STYLE.timing.inputUntouchMs
        before = frame.evaluate(mobile.RUN_STATE)
        frame.evaluate('window.__touchThrows = []')
        page.touchscreen.tap(w * 0.75, h * 0.3)
        frame.wait_for_function('window.__touchThrows.length > 0')
        frame.wait_for_function('t => window.__ticks > t + 10', arg=before['ticks'])
        result['touch'] = {'before': before, 'throws': frame.evaluate('window.__touchThrows'),
                           'after': frame.evaluate(mobile.RUN_STATE)}
        self.shot(page, 'mobile-play')

        # Double-tap over the game: no zoom, no scroll
        for _ in range(2):
            page.touchscreen.tap(w / 2, h / 2)
            page.wait_for_timeout(80)
        page.wait_for_timeout(400)
        result['after_double_tap'] = {'host': page.evaluate(mobile.VIEWPORT_STATE),
                                      'frame': frame.evaluate(mobile.VIEWPORT_STATE)}

        # Rotate mid-run
        ticks = frame.evaluate('window.__ticks')
        page.set_viewport_size({'width': h, 'height': w})
        frame.wait_for_function('s => innerWidth === s[0] && innerHeight === s[1]', arg=[h, w])
        page.wait_for_timeout(500)
        frame.wait_for_function('t => window.__ticks > t + 20', arg=ticks)
        result['rotate'] = {'play_rect_after': frame.evaluate(embed.CANVAS),
                            'iframe_box_after': page.locator('#game_drop').bounding_box(),
                            'ticks_before': ticks, 'state_after': frame.evaluate(mobile.RUN_STATE)}
        self.shot(page, 'mobile-rotated')
        result['errors'] = errors + self.frame_errors(page, frame)
        self.save('iphone13-portrait', result)

        self.assertBox(result['iframe_box'], {'x': 0, 'y': 0, 'width': w, 'height': h})
        self.assertEqual(result['frame_inner'], [w, h])
        self.assertEqual(result['buttons_outside'], [])
        self.assertEqual(result['menu']['layout_matrix']['clipped'], [])
        self.assertGreaterEqual(len(buttons), 3)
        self.assertGreaterEqual(result['min_touch'], mobile.MIN_TOUCH)
        self.assertFalse(before['grapnelThrown'])
        self.assertEqual(result['touch']['throws'][:1], [True])
        self.assertGreater(result['touch']['after']['ticks'], before['ticks'])
        for where in ('host', 'frame'):
            state = result['after_double_tap'][where]
            self.assertEqual(state['scale'], 1, where)
            self.assertEqual((state['scrollX'], state['scrollY']), (0, 0), where)
        rotate = result['rotate']
        self.assertBox(rotate['iframe_box_after'], {'x': 0, 'y': 0, 'width': h, 'height': w})
        after = rotate['play_rect_after']
        self.assertEqual((after['innerWidth'], after['innerHeight']), (h, w))
        self.assertLessEqual(after['cssWidth'], h + mobile.EPS)
        self.assertLessEqual(after['cssHeight'], w + mobile.EPS)
        state = rotate['state_after']
        self.assertGreater(state['ticks'], rotate['ticks_before'] + 20)
        self.assertEqual(state['version'], 'classic')
        self.assertFalse(state['menuVisible'])
        self.assertEqual(result['errors'], [])


for _name in BROWSERS:
    _cls = type(f'ItchBrowser_{_name}', (ItchBrowserFlows, unittest.TestCase), {'browser_name': _name})
    globals()[_cls.__name__] = _cls
del _name, _cls


if __name__ == '__main__':
    unittest.main()
