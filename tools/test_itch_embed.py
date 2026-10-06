"""The game embedded like on itch.io: cross-origin 960x540 iframe, click to play, fullscreen."""
import json
import os
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import OfflineBrowser
from itch_harness import start_itch_embed
from playwright.sync_api import sync_playwright

VIEWPORT = {'width': 1920, 'height': 1080}
SCREEN = {'width': 1920, 'height': 1080}
FRAME = (960, 540)
HOST_SCROLL = 120
SCROLL_KEYS = ['Space', 'ArrowUp', 'ArrowDown', 'PageDown', 'PageUp', 'End', 'Home']
READY = ('typeof PLATFORM !== "undefined" && PLATFORM.environment === "itch" && menu.visible'
         ' && document.getElementById("loading").hidden')

# Runs in the host and in the game frame: uncaught errors of every frame
ERROR_SPY = '''(() => {
    window.__errors = []
    window.addEventListener('error', e => window.__errors.push(String(e.message)))
    window.addEventListener('unhandledrejection', e => window.__errors.push(String(e.reason)))
})()'''

# Count physics ticks; window.__kill moves the ninja behind the deletion
# border (a real lethal death through ninja.move()); otherwise it is pinned.
INSTRUMENT_RUN = '''() => {
    if (window.__instrumented) return
    window.__instrumented = true
    window.__ticks = 0
    window.__reStarts = 0
    const original = window.reStart
    window.reStart = function() {
        window.__reStarts++
        window.__pin = null
        return original.apply(this, arguments)
    }
    const physicsStep = window.physics
    window.physics = function() {
        window.__ticks++
        if (window.__kill) {
            window.__kill = false
            ninja.x = screen.getDeletionBorder() - screen.x - 10 * ninja.radius
            ninja.speedX = 0
            ninja.speedY = 0
            return physicsStep.apply(this, arguments)
        }
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        const result = physicsStep.apply(this, arguments)
        ninja.x = window.__pin.x
        ninja.y = window.__pin.y
        ninja.speedX = 0
        ninja.speedY = 0
        return result
    }
}'''

# Centre of a menu button in canvas logical units, mapped to frame CSS px
BUTTON_CENTER = '''name => {
    const b = menu[name].background
    const rect = canvas.getBoundingClientRect()
    return {x: rect.left + (b.x + b.width / 2) * rect.width / width,
            y: rect.top + (b.y + b.height / 2) * rect.height / height}
}'''

CANVAS = '''() => {
    const r = canvas.getBoundingClientRect()
    return {left: r.left, top: r.top, cssWidth: r.width, cssHeight: r.height,
            backingWidth: canvas.width, backingHeight: canvas.height,
            dpr: window.devicePixelRatio, innerWidth: innerWidth, innerHeight: innerHeight,
            logicalWidth: width, logicalHeight: height}
}'''


class ItchEmbedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host_url, cls.game_origin, cls.game_url, cls.game_log = \
            start_itch_embed(cls.addClassCleanup)
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        browser = playwright.chromium.launch(args=['--no-sandbox'])
        cls.addClassCleanup(browser.close)
        cls.browser = OfflineBrowser(browser)
        cls.save_evidence = bool(os.environ.get('ITCH_EMBED_EVIDENCE_DIR'))
        cls.evidence = Path(os.environ.get('ITCH_EMBED_EVIDENCE_DIR') or '.')
        cls.scroll = {}

    def out(self, name):
        path = self.evidence / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def shot(self, page, name):
        if self.save_evidence:
            page.screenshot(path=str(self.out('screens/' + name)))

    def save_scroll(self):
        if self.save_evidence:
            self.out('scroll.json').write_text(json.dumps(self.scroll, indent=1) + '\n')

    def open(self, **options):
        options.setdefault('viewport', VIEWPORT)
        context = self.browser.new_context(screen=SCREEN, **options)
        self.addCleanup(context.close)
        context.add_init_script(ERROR_SPY)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(self.host_url)
        return page, errors

    def play(self, page):
        """Click 'Click to play'; return the game frame once its menu is up."""
        page.click('#load_game')
        frame = page.wait_for_selector('#game_drop').content_frame()
        frame.wait_for_function(READY)
        frame.evaluate(INSTRUMENT_RUN)
        return frame

    def frame_errors(self, page, frame):
        return page.evaluate('window.__errors') + frame.evaluate('window.__errors')

    def click_game(self, page, frame, x, y):
        """Click at frame CSS px (x, y) with the real mouse."""
        box = page.locator('#game_drop').bounding_box()
        page.mouse.click(box['x'] + x, box['y'] + y)

    def click_button(self, page, frame, name):
        point = frame.evaluate(BUTTON_CENTER, name)
        self.click_game(page, frame, point['x'], point['y'])

    def start_version(self, page, frame, version):
        button = 'classicVersionButton' if version == 'classic' else 'badVersionButton'
        self.click_button(page, frame, button)
        frame.wait_for_function('v => version === v && !menu.visible', arg=version)
        ticks = frame.evaluate('window.__ticks')
        frame.wait_for_function('t => window.__ticks > t + 10', arg=ticks)

    def scroll_y(self, page):
        return page.evaluate('window.scrollY')

    def test_a_click_to_play(self):
        page, errors = self.open()
        requests = []
        page.on('requestfinished', lambda r: requests.append(r))
        failed = []
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.wait_for_selector('#load_game')
        self.assertEqual(page.locator('#game_drop').count(), 0)
        self.shot(page, 'host-before-click.png')
        frame = self.play(page)
        box = page.locator('#game_drop').bounding_box()
        self.assertEqual((box['width'], box['height']), FRAME)
        canvas = frame.evaluate(CANVAS)
        self.assertEqual((canvas['innerWidth'], canvas['innerHeight']), FRAME)
        page.wait_for_timeout(500)
        self.shot(page, 'embed-menu.png')
        game = [r for r in requests if r.frame != page.main_frame]
        records = [{'url': r.url, 'status': r.response().status, 'type': r.resource_type}
                   for r in game]
        host = [r.url for r in requests if r.frame == page.main_frame]
        if self.save_evidence:
            self.out('requests.json').write_text(json.dumps(
                {'game_origin': self.game_origin, 'host_url': self.host_url,
                 'count': len(records), 'failed': failed,
                 'not_game_origin': [x['url'] for x in records
                                     if not x['url'].startswith(self.game_origin + '/')],
                 'not_200': [x for x in records if x['status'] != 200],
                 'host_requests': host, 'game_requests': records}, indent=1) + '\n')
        self.assertTrue(any(x['url'] == self.game_url for x in records))
        self.assertGreater(len(records), 10)
        for x in records:
            self.assertTrue(x['url'].startswith(self.game_origin + '/'), x)
            self.assertEqual(x['status'], 200, x)
        self.assertEqual(failed, [])
        # The host page itself loads nothing more after the click
        self.assertEqual(host, [])
        self.assertEqual(self.frame_errors(page, frame), [])
        self.assertEqual(errors, [])

    def test_b_keys_do_not_scroll_host(self):
        page, errors = self.open()
        frame = self.play(page)
        page.evaluate('y => window.scrollTo(0, y)', HOST_SCROLL)
        self.assertEqual(self.scroll_y(page), HOST_SCROLL)
        self.start_version(page, frame, 'classic')
        self.assertTrue(frame.evaluate('document.hasFocus()'))
        # Keyboard controls: P and Escape toggle the pause
        for key in ('p', 'p', 'Escape', 'Escape'):
            paused = frame.evaluate('menu.gamePaused')
            page.keyboard.press(key)
            frame.wait_for_function('p => menu.gamePaused === p', arg=not paused)
        self.assertFalse(frame.evaluate('menu.gamePaused'))
        keys = []
        for key in SCROLL_KEYS:
            before = self.scroll_y(page)
            page.keyboard.press(key)
            page.wait_for_timeout(250)
            keys.append({'key': key, 'before': before, 'after': self.scroll_y(page)})
        self.scroll['keys_in_game'] = keys
        # Control: the same key with the focus on the host page does scroll it
        page.click('#description')
        before = self.scroll_y(page)
        page.keyboard.press('PageDown')
        page.wait_for_function('y => window.scrollY !== y', arg=before)
        self.scroll['control_host_focus_pagedown'] = {'before': before, 'after': self.scroll_y(page)}
        self.save_scroll()
        for k in keys:
            self.assertEqual(k['after'], k['before'], k)
            self.assertEqual(k['after'], HOST_SCROLL, k)
        self.assertEqual(self.frame_errors(page, frame), [])
        self.assertEqual(errors, [])

    def touch_drag(self, page, x, y, dy, steps=10):
        """A real finger drag up by dy px (touchstart, touchmoves, touchend)."""
        cdp = page.context.new_cdp_session(page)
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
        for i in range(1, steps + 1):
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove',
                                                  'touchPoints': [{'x': x, 'y': y - dy * i / steps}]})
            page.wait_for_timeout(16)
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        cdp.detach()

    def test_c_wheel_and_touch_do_not_scroll_host(self):
        results = {}
        page, errors = self.open()
        frame = self.play(page)
        page.evaluate('y => window.scrollTo(0, y)', HOST_SCROLL)
        box = page.locator('#game_drop').bounding_box()
        cx, cy = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        wheel = []
        for delta in (300, -300, 600):
            before = self.scroll_y(page)
            page.mouse.move(cx, cy)
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(400)
            wheel.append({'deltaY': delta, 'before': before, 'after': self.scroll_y(page)})
        results['wheel_over_game'] = wheel
        desc = page.locator('#description').bounding_box()
        page.mouse.move(cx, desc['y'] + 100)
        before = self.scroll_y(page)
        page.mouse.wheel(0, 300)
        page.wait_for_function('y => window.scrollY !== y', arg=before)
        results['control_wheel_over_host'] = {'before': before, 'after': self.scroll_y(page)}
        self.assertEqual(self.frame_errors(page, frame), [])
        self.assertEqual(errors, [])

        page, errors = self.open(has_touch=True)
        frame = self.play(page)
        page.evaluate('y => window.scrollTo(0, y)', HOST_SCROLL)
        box = page.locator('#game_drop').bounding_box()
        cx, cy = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        frame.evaluate('''() => { window.__touchmoves = 0
            document.addEventListener('touchmove', () => window.__touchmoves++, true) }''')
        touch = []
        for dy in (300, -200):
            before = self.scroll_y(page)
            self.touch_drag(page, cx, cy + 100, dy)
            page.wait_for_timeout(400)
            touch.append({'dragUp': dy, 'before': before, 'after': self.scroll_y(page)})
        results['touch_drag_over_game'] = touch
        results['touchmoves_in_game'] = frame.evaluate('window.__touchmoves')
        desc = page.locator('#description').bounding_box()
        before = self.scroll_y(page)
        self.touch_drag(page, cx, desc['y'] + 300, 300)
        page.wait_for_timeout(400)
        results['control_touch_drag_over_host'] = {'before': before, 'after': self.scroll_y(page)}
        self.scroll.update(results)
        self.save_scroll()
        for w in wheel + touch:
            self.assertEqual(w['after'], w['before'], w)
            self.assertEqual(w['after'], HOST_SCROLL, w)
        self.assertGreater(results['touchmoves_in_game'], 0)
        for control in ('control_wheel_over_host', 'control_touch_drag_over_host'):
            self.assertNotEqual(results[control]['after'], results[control]['before'], control)
        self.assertEqual(self.frame_errors(page, frame), [])
        self.assertEqual(errors, [])

    def black_edges(self, path):
        """Share of pure #000 pixels in 8 px strips along each screen edge."""
        img = Image.open(path).convert('RGB')
        w, h = img.size
        strips = {'top': (0, 0, w, 8), 'bottom': (0, h - 8, w, h),
                  'left': (0, 0, 8, h), 'right': (w - 8, 0, w, h)}
        share = {}
        for name, crop in strips.items():
            pixels = list(img.crop(crop).getdata())
            share[name] = sum(p == (0, 0, 0) for p in pixels) / len(pixels)
        return {'size': [w, h], 'black_share': share}

    def test_d_fullscreen(self):
        page, errors = self.open()
        frame = self.play(page)
        page.click('#fullscreen_btn')
        page.wait_for_function('document.fullscreenElement && document.fullscreenElement.id === "game_drop"')
        frame.wait_for_function('''() => { const r = canvas.getBoundingClientRect()
            return innerWidth === 1920 && r.width === 1920 && r.height === 1080 }''')
        page.wait_for_timeout(300)
        full = frame.evaluate(CANVAS)
        box = page.locator('#game_drop').bounding_box()
        self.shot(page, 'fullscreen.png')
        self.assertEqual((box['x'], box['y'], box['width'], box['height']), (0, 0, 1920, 1080))
        self.assertEqual((full['left'], full['top'], full['cssWidth'], full['cssHeight']),
                         (0, 0, 1920, 1080))
        self.assertEqual((full['backingWidth'], full['backingHeight']), (1920, 1080))
        # A run in fullscreen uses the whole play rect
        self.start_version(page, frame, 'classic')
        play = frame.evaluate(CANVAS)
        edges = None
        if self.save_evidence:
            edges = self.black_edges(self.out('screens/fullscreen.png'))
        page.evaluate('document.exitFullscreen()')
        page.wait_for_function('!document.fullscreenElement')
        frame.wait_for_function('''() => { const r = canvas.getBoundingClientRect()
            return innerWidth === 960 && r.width === 960 && r.height === 540 && canvas.width === 960 }''')
        page.wait_for_timeout(300)
        after = frame.evaluate(CANVAS)
        box_after = page.locator('#game_drop').bounding_box()
        self.shot(page, 'after-exit.png')
        if self.save_evidence:
            self.out('fullscreen.json').write_text(json.dumps(
                {'fullscreen_canvas': full, 'fullscreen_iframe_box': box,
                 'fullscreen_run_canvas': play, 'fullscreen_png_edges': edges,
                 'after_exit_canvas': after, 'after_exit_iframe_box': box_after}, indent=1) + '\n')
        self.assertEqual((play['cssWidth'], play['cssHeight']), (1920, 1080))
        if edges:
            for name, share in edges['black_share'].items():
                self.assertLess(share, 0.05, (name, edges))
        self.assertEqual((box_after['width'], box_after['height']), FRAME)
        self.assertEqual((after['cssWidth'], after['cssHeight']), FRAME)
        self.assertEqual((after['backingWidth'], after['backingHeight']), FRAME)
        self.assertEqual(self.frame_errors(page, frame), [])
        self.assertEqual(errors, [])

    def test_e_classic_and_bad_run_to_death_and_menu(self):
        page, errors = self.open()
        frame = self.play(page)
        states = []
        for version in ('classic', 'bad'):
            self.start_version(page, frame, version)
            if version == 'classic':
                self.shot(page, 'embed-play.png')
            restarts = frame.evaluate('window.__reStarts')
            frame.evaluate('window.__kill = true')
            frame.wait_for_function('r => !window.__kill && window.__reStarts > r', arg=restarts)
            page.wait_for_timeout(300)
            self.assertFalse(frame.evaluate('menu.visible || continueOffer.visible'))
            page.keyboard.press('Escape')
            frame.wait_for_function('menu.gamePaused')
            self.click_button(page, frame, 'backToMenu')
            frame.wait_for_function('menu.visible && !menu.gamePaused')
            states.append(frame.evaluate('''v => ({version: v, deaths: window.__reStarts,
                menuVisible: menu.visible, record: scoreText.record[v]})''', version))
        if self.save_evidence:
            self.out('runs.json').write_text(json.dumps(states, indent=1) + '\n')
        self.assertEqual([s['deaths'] for s in states], [1, 2])
        self.assertTrue(all(s['menuVisible'] for s in states))
        self.assertEqual(self.frame_errors(page, frame), [])
        self.assertEqual(errors, [])

    def test_f_canvas_dpr(self):
        results = []
        for dpr in (1, 2):
            page, errors = self.open(viewport={'width': 1280, 'height': 900}, device_scale_factor=dpr)
            frame = self.play(page)
            canvas = frame.evaluate(CANVAS)
            results.append(canvas)
            self.assertEqual(canvas['dpr'], dpr)
            self.assertEqual((canvas['cssWidth'], canvas['cssHeight']), FRAME)
            self.assertEqual((canvas['backingWidth'], canvas['backingHeight']),
                             (round(FRAME[0] * dpr), round(FRAME[1] * dpr)))
            self.assertEqual(self.frame_errors(page, frame), [])
            self.assertEqual(errors, [])
        if self.save_evidence:
            self.out('dpr.json').write_text(json.dumps(results, indent=1) + '\n')


if __name__ == '__main__':
    unittest.main()
