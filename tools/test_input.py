"""Input hardening for the game iframe: touch, keys, scrolling, focus."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import canvas_to_viewport, open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent
TOUCH_VIEWPORT = {'width': 844, 'height': 390}
DESKTOP_VIEWPORT = {'width': 1280, 'height': 720}


def open_touch_game(browser, url):
    """Return (context, page, errors) for a mobile landscape touch context."""
    context, page, errors = open_game(browser, url + 'index.html', TOUCH_VIEWPORT,
                                      has_touch=True, is_mobile=True)
    page.wait_for_function('menu.visible && typeof Grapnel !== "undefined"')
    return context, page, errors


def start_classic(page):
    """Start the classic run directly and let the input guard expire."""
    page.evaluate('''() => {
        const b = menu.classicVersionButton.background
        menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
    }''')
    page.wait_for_function('!menu.visible && version === "classic"')
    page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 300)


def count_tap_throws(page):
    """Tap once in the sky during classic gameplay; return calcSpeed calls."""
    start_classic(page)
    page.evaluate('''() => {
        window.__throws = 0
        const orig = Grapnel.prototype.calcSpeed
        Grapnel.prototype.calcSpeed = function () {
            window.__throws++
            return orig.apply(this, arguments)
        }
    }''')
    width = page.evaluate('menu.width')
    point = canvas_to_viewport(page, width * 0.6, page.evaluate('menu.height') * 0.3)
    page.touchscreen.tap(point['x'], point['y'])
    page.wait_for_timeout(300)
    return page.evaluate('window.__throws')


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('INPUT_EVIDENCE_DIR')
        cls.errors = []

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            for kind in ('console', 'page'):
                lines = [f'{name}: {msg}' for name, errors in cls.errors
                         for msg in errors[kind]]
                (out / f'{kind}-errors.log').write_text(''.join(
                    line + '\n' for line in lines))

    def track(self, context, errors):
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))

    def boot_desktop(self):
        context, page, errors = open_game(self.browser, 'about:blank', DESKTOP_VIEWPORT)
        self.track(context, errors)
        page.goto(self.url + 'index.html')
        page.wait_for_function('PLATFORM.environment === "local" && menu.visible')
        return page

    def out(self):
        out = Path(self.evidence)
        out.mkdir(parents=True, exist_ok=True)
        return out

    def test_one_tap_one_throw(self):
        context, page, errors = open_touch_game(self.browser, self.url)
        self.track(context, errors)
        throws = count_tap_throws(page)
        print(f'\n  tap throws={throws}', file=sys.stderr)
        self.assertEqual(throws, 1)
        # Hold a touch so the thrown grapnel is visible in the screenshot
        # (physics keeps calling calcSpeed while it flies, so no count here).
        page.evaluate('''() => {
            const t = new Touch({identifier: 1, target: canvas,
                clientX: innerWidth * 0.75, clientY: innerHeight * 0.2})
            document.dispatchEvent(new TouchEvent('touchstart', {
                touches: [t], changedTouches: [t], cancelable: true, bubbles: true}))
        }''')
        page.wait_for_timeout(120)
        self.assertTrue(page.evaluate('grapnel.throwed'))
        if self.evidence:
            page.screenshot(path=str(self.out() / 'touch-gameplay.png'))
        print('  ASSERT one tap -> exactly 1 grapnel throw: pass', file=sys.stderr)

    def test_first_tap_on_menu_starts_game(self):
        # A fresh load has no grapnel yet; the tap must reach the menu button
        context, page, errors = open_touch_game(self.browser, self.url)
        self.track(context, errors)
        self.assertTrue(page.evaluate('typeof grapnel == "undefined"'))
        c = page.evaluate('''(() => { const b = menu.classicVersionButton.background
            return {x: b.x + b.width / 2, y: b.y + b.height / 2} })()''')
        point = canvas_to_viewport(page, c['x'], c['y'])
        page.touchscreen.tap(point['x'], point['y'])
        page.wait_for_function('!menu.visible && version === "classic"', timeout=5000)
        print('\n  ASSERT first menu tap starts classic, no page error: pass', file=sys.stderr)

    def test_default_prevented(self):
        page = self.boot_desktop()
        result = page.evaluate('''() => {
            const fire = (target, ev) => { target.dispatchEvent(ev); return ev.defaultPrevented }
            const key = k => new KeyboardEvent('keydown', {key: k, code: k === ' ' ? 'Space' : k,
                cancelable: true, bubbles: true})
            return {
                contextmenu: fire(canvas, new MouseEvent('contextmenu', {cancelable: true, bubbles: true})),
                wheel: fire(canvas, new WheelEvent('wheel', {deltaY: 100, cancelable: true, bubbles: true})),
                ArrowUp: fire(document, key('ArrowUp')),
                ArrowDown: fire(document, key('ArrowDown')),
                ArrowLeft: fire(document, key('ArrowLeft')),
                ArrowRight: fire(document, key('ArrowRight')),
                Space: fire(document, key(' ')),
            }
        }''')
        print(f'\n  defaultPrevented={result}', file=sys.stderr)
        self.assertEqual(result, {k: True for k in result})
        print('  ASSERT contextmenu/wheel/ArrowDown/Space defaultPrevented == true: pass',
              file=sys.stderr)

    def test_p_toggles_pause(self):
        page = self.boot_desktop()
        start_classic(page)
        states = []
        for key in ('p', 'P', 'Escape', 'Escape'):
            page.keyboard.press(key)
            states.append(page.evaluate('menu.gamePaused'))
        print(f'\n  gamePaused after p,P,Escape,Escape={states}', file=sys.stderr)
        self.assertEqual(states, [True, False, True, False])
        print('  ASSERT "p" toggles gamePaused true then false: pass', file=sys.stderr)

    def test_visibility_hidden_pauses(self):
        page = self.boot_desktop()
        start_classic(page)
        page.evaluate('''() => {
            Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true})
            Object.defineProperty(document, 'hidden', {value: true, configurable: true})
            document.dispatchEvent(new Event('visibilitychange'))
        }''')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        print('\n  ASSERT visibilitychange hidden -> gamePaused: pass',
              file=sys.stderr)

    def test_computed_style(self):
        page = self.boot_desktop()
        style = page.evaluate('''() => Object.fromEntries(['body', 'canvas'].map(sel => {
            const s = getComputedStyle(document.querySelector(sel))
            return [sel, {userSelect: s.userSelect, webkitUserSelect: s.webkitUserSelect,
                touchAction: s.touchAction, webkitTapHighlightColor: s.webkitTapHighlightColor}]
        }))''')
        if self.evidence:
            (self.out() / 'computed-style.json').write_text(json.dumps(style, indent=2) + '\n')
        for sel in ('body', 'canvas'):
            self.assertEqual(style[sel]['userSelect'], 'none')
            self.assertEqual(style[sel]['touchAction'], 'none')
        print('\n  ASSERT body/canvas userSelect == none, touchAction == none: pass',
              file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
