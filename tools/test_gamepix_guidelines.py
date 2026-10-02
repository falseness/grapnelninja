"""GamePix score events and the remaining guideline checks (fake SDK)."""
import os
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamepix_harness import (canvas_to_viewport, collect_errors, open_game,
                             route_fake_sdk, sdk_calls, sdk_errors,
                             set_fake_config, start_gamepix_test)

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
READY = ('typeof menu !== "undefined" && menu.visible'
         ' && !document.getElementById("loading")'
         ' && PLATFORM.environment === "gamepix"')
# Records every string drawn on a canvas, so menu texts can be checked
RECORD_TEXT = '''
window.__drawnText = []
const fillText = CanvasRenderingContext2D.prototype.fillText
CanvasRenderingContext2D.prototype.fillText = function(text) {
    window.__drawnText.push(String(text))
    return fillText.apply(this, arguments)
}
'''
HOST_PAGE = '__iframe_host.html'
HOST_HTML = '''<!DOCTYPE html>
<html><body style="margin:0;background:#333">
<iframe id="game" src="index.html" width="{w}" height="{h}"
    style="position:absolute;left:40px;top:30px;border:0"></iframe>
</body></html>'''
FRAME_STATE = '''() => {
    const r = canvas.getBoundingClientRect()
    const de = document.documentElement
    return {
        inner: [window.innerWidth, window.innerHeight],
        rect: [r.left, r.top, r.width, r.height],
        scroll: [de.scrollWidth, de.scrollHeight, de.clientWidth, de.clientHeight,
                 document.body.scrollWidth, document.body.scrollHeight],
        scrollXY: [window.scrollX, window.scrollY]
    }
}'''
MENU_BUTTONS = ['classicVersionButton', 'badVersionButton', 'mainFpsCounterCheckbox']
BUTTON_CENTER = '''(name) => {
    const b = menu[name]
    if (b.background)
        return {x: b.background.x + b.background.width / 2,
                y: b.background.y + b.background.height / 2}
    return {x: b.x + b.size / 2, y: b.y}  // Checkbox: box left edge, middle y
}'''
FORBIDDEN_TEXT = re.compile(r'rotate|quit|exit|close|^\s*[x×✕✖]\s*$', re.I)


def log(message):
    print('  ' + message, file=sys.stderr)


def names(page):
    return [c['name'] for c in sdk_calls(page)]


class GuidelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_gamepix_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('GAMEPIX_GUIDELINES_EVIDENCE_DIR')

    def check_clean(self, page, errors):
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(sdk_errors(page), []))

    def boot(self):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT)
        self.addCleanup(context.close)
        self.check_clean(page, errors)
        context.add_init_script(RECORD_TEXT)
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        return page

    def score(self, page, points):
        for _ in range(points):
            page.evaluate('changeScoreText()')

    # Score events

    def test_update_score_carries_current_score(self):
        page = self.boot()
        page.evaluate('startGame("classic")')
        self.score(page, 3)
        page.evaluate('reStart()')
        self.score(page, 2)
        scores = [c['args'] for c in sdk_calls(page) if c['name'] == 'updateScore']
        log(f'updateScore args: {scores}')
        self.assertEqual(scores, [[1], [2], [3], [1], [2]])
        self.assertEqual(page.evaluate('scoreText.count[version]'), 2)
        self.assertNotIn('updateLevel', names(page))

    def test_happy_moment_once_per_record_run(self):
        page = self.boot()
        page.evaluate('scoreText.record.classic = 2')
        page.evaluate('startGame("classic")')
        self.score(page, 2)
        self.assertEqual(names(page).count('happyMoment'), 0,
                         'tying the record is not a happy moment')
        self.score(page, 4)
        self.assertEqual(names(page).count('happyMoment'), 1)
        # A second record run gets its own happy moment
        page.evaluate('reStart()')
        self.score(page, 7)
        calls = names(page)
        log(f'happyMoment calls after 2 record runs: {calls.count("happyMoment")}')
        self.assertEqual(calls.count('happyMoment'), 2)

    def test_no_happy_moment_on_non_record_run(self):
        page = self.boot()
        page.evaluate('scoreText.record.classic = 10')
        page.evaluate('startGame("classic")')
        self.score(page, 10)
        page.evaluate('reStart()')
        self.score(page, 5)
        calls = names(page)
        log(f'non-record runs: updateScore x{calls.count("updateScore")}, '
            f'happyMoment x{calls.count("happyMoment")}')
        self.assertEqual(calls.count('updateScore'), 15)
        self.assertEqual(calls.count('happyMoment'), 0)

    def test_no_sdk_call_before_loaded(self):
        page = self.boot()
        page.evaluate('startGame("classic")')
        self.score(page, 2)
        page.evaluate('reStart()')
        calls = names(page)
        log(f'SDK call order: {calls}')
        self.assertEqual(calls.count('loaded'), 1)
        first = calls.index('loaded')
        self.assertEqual(set(calls[:first]), {'loading'})
        self.assertIn('updateScore', calls[first:])
        self.assertIn('localStorage.getItem', calls[first:])

    # Iframe fit and input

    def open_iframe(self, w, h):
        context = self.browser.new_context(
            viewport={'width': w + 80, 'height': h + 60}, has_touch=True)
        self.addCleanup(context.close)
        route_fake_sdk(context)
        set_fake_config(context)
        context.route('**/' + HOST_PAGE, lambda route: route.fulfill(
            body=HOST_HTML.format(w=w, h=h), content_type='text/html'))
        page = context.new_page()
        page_errors = collect_errors(page)
        page.goto(self.url + HOST_PAGE)
        frame = page.wait_for_selector('#game').content_frame()
        frame.wait_for_function(READY)
        frame.evaluate('document.fonts.ready')
        self.check_clean(frame, page_errors)
        return page, frame

    def check_iframe(self, w, h):
        page, frame = self.open_iframe(w, h)
        state = frame.evaluate(FRAME_STATE)
        log(f'{w}x{h} iframe: {state}')
        self.assertEqual(state['inner'], [w, h])
        sw, sh, cw, ch, bw, bh = state['scroll']
        self.assertLessEqual(max(bw, sw), cw)
        self.assertLessEqual(max(bh, sh), ch)
        self.assertEqual(state['scrollXY'], [0, 0])
        left, top, rw, rh = state['rect']
        self.assertTrue(rw <= w + 0.5 and rh <= h + 0.5, 'canvas overflows the iframe')
        self.assertAlmostEqual(left, (w - rw) / 2, delta=1, msg='canvas not centered')
        self.assertAlmostEqual(top, (h - rh) / 2, delta=1, msg='canvas not centered')

        box = page.locator('#game').bounding_box()
        for name in MENU_BUTTONS:
            center = frame.evaluate(BUTTON_CENTER, name)
            point = canvas_to_viewport(frame, center['x'], center['y'])
            hit = frame.evaluate('''([x, y]) => {
                const el = document.elementFromPoint(x, y)
                return el && el.id
            }''', [point['x'], point['y']])
            log(f'{w}x{h} {name} at iframe px {point}: hit #{hit}')
            self.assertTrue(0 <= point['x'] < w and 0 <= point['y'] < h,
                            f'{name} outside the iframe')
            self.assertEqual(hit, 'canvas', f'{name} not hit-testable')

        if self.evidence:
            out = Path(self.evidence) / 'iframe'
            out.mkdir(parents=True, exist_ok=True)
            page.locator('#game').screenshot(path=str(out / f'{w}x{h}.png'))

        center = frame.evaluate(BUTTON_CENTER, 'classicVersionButton')
        point = canvas_to_viewport(frame, center['x'], center['y'])
        page.touchscreen.tap(box['x'] + point['x'], box['y'] + point['y'])
        frame.wait_for_function('!menu.visible && version === "classic"', timeout=3000)
        log(f'{w}x{h}: first tap started a {frame.evaluate("version")} run')

    def test_iframe_640x480(self):
        self.check_iframe(640, 480)

    def test_iframe_480x640(self):
        self.check_iframe(480, 640)

    def test_scroll_keys_and_wheel_prevented(self):
        page = self.boot()
        script = '''() => {
            const out = {}
            for (const key of [' ', 'ArrowUp', 'ArrowDown']) {
                const e = new KeyboardEvent('keydown',
                    {key: key, bubbles: true, cancelable: true})
                document.body.dispatchEvent(e)
                out[key] = e.defaultPrevented
            }
            const w = new WheelEvent('wheel', {deltaY: 100, bubbles: true, cancelable: true})
            canvas.dispatchEvent(w)
            out.wheel = w.defaultPrevented
            return out
        }'''
        expected = {' ': True, 'ArrowUp': True, 'ArrowDown': True, 'wheel': True}
        on_menu = page.evaluate(script)
        page.evaluate('startGame("classic")')
        in_run = page.evaluate(script)
        log(f'defaultPrevented on menu {on_menu}, in run {in_run}')
        self.assertEqual(on_menu, expected)
        self.assertEqual(in_run, expected)

    def test_viewport_meta_and_touch_action(self):
        page = self.boot()
        meta = page.evaluate(
            'document.querySelector(\'meta[name="viewport"]\').content')
        touch = page.evaluate('getComputedStyle(document.body).touchAction')
        log(f'viewport meta: {meta!r}; body touch-action: {touch!r}')
        self.assertIn('user-scalable=no', meta.replace(' ', ''))
        self.assertEqual(touch, 'none')

    def test_no_rotate_prompt_or_quit_button(self):
        page = self.boot()
        page.evaluate('menu.draw()')
        drawn = page.evaluate('window.__drawnText')
        dom = page.evaluate('document.body.innerText')
        buttons = page.evaluate('''() => Object.keys(menu).filter(k =>
            menu[k] && typeof menu[k].click === 'function')''')
        log(f'menu texts: {sorted(set(drawn))}; DOM text: {dom!r}; '
            f'menu buttons: {buttons}')
        self.assertTrue(drawn, 'no menu text recorded')
        self.assertEqual([t for t in drawn + [dom] if FORBIDDEN_TEXT.search(t)], [])
        self.assertEqual([b for b in buttons if re.search(r'quit|exit|close', b, re.I)], [])


if __name__ == '__main__':
    unittest.main()
