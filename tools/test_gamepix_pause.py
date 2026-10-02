"""The run pauses on page visibility and GamePix on.pause, never on blur."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamepix_harness import fire, open_game, sdk_errors, start_gamepix_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
READY = ('typeof menu !== "undefined" && menu.visible'
         ' && !document.getElementById("loading")'
         ' && PLATFORM.environment === "gamepix"')
# Fake the Page Visibility API state and fire visibilitychange
SET_VISIBILITY = '''(state) => {
    Object.defineProperty(document, 'visibilityState',
        {configurable: true, get: () => state})
    Object.defineProperty(document, 'hidden',
        {configurable: true, get: () => state === 'hidden'})
    document.dispatchEvent(new Event('visibilitychange'))
}'''
STATE = '''({paused: menu.gamePaused, menu: menu.visible,
    offer: continueOffer.visible})'''


def log(message):
    print('  ' + message, file=sys.stderr)


class PauseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_gamepix_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('GAMEPIX_PAUSE_EVIDENCE_DIR')

    def boot(self):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(sdk_errors(page), []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        return page

    def play(self, page):
        page.evaluate('startGame("classic")')
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate(STATE),
                         {'paused': False, 'menu': False, 'offer': False})

    def hide(self, page):
        page.evaluate(SET_VISIBILITY, 'hidden')

    def screenshot(self, page, name):
        if not self.evidence:
            return
        out = Path(self.evidence) / 'screens'
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / name))

    def assert_frozen(self, page):
        before = page.evaluate('({x: ninja.x, y: ninja.y, sx: screen.x, sy: screen.y})')
        page.wait_for_timeout(1000)
        after = page.evaluate('({x: ninja.x, y: ninja.y, sx: screen.x, sy: screen.y})')
        log(f'paused ninja before={before} after 1 s={after}')
        self.assertEqual(before, after)

    def test_blur_does_not_pause(self):
        """A click outside the iframe (window blur) keeps the run going."""
        page = self.boot()
        self.play(page)
        page.evaluate('window.dispatchEvent(new Event("blur"))')
        state = page.evaluate(STATE)
        log(f'after window blur: {state}')
        self.assertFalse(state['paused'], 'window blur paused the run')

    def test_visibility_hidden_pauses(self):
        page = self.boot()
        self.play(page)
        self.hide(page)
        state = page.evaluate(STATE)
        log(f'after visibility hidden: {state}')
        self.assertTrue(state['paused'])
        page.evaluate(SET_VISIBILITY, 'visible')
        self.assertTrue(page.evaluate('menu.gamePaused'),
                        'visible again must not auto-resume')
        self.assert_frozen(page)
        self.screenshot(page, 'paused-by-visibility.png')

    def test_visibility_hidden_on_menu_is_harmless(self):
        page = self.boot()
        self.hide(page)
        state = page.evaluate(STATE)
        log(f'menu + hidden: {state}')
        self.assertEqual(state, {'paused': False, 'menu': True, 'offer': False})

    def test_visibility_hidden_during_continue_offer_is_harmless(self):
        page = self.boot()
        self.play(page)
        page.evaluate('continueOffer.show()')
        self.hide(page)
        state = page.evaluate(STATE)
        log(f'continue offer + hidden: {state}')
        self.assertEqual(state, {'paused': False, 'menu': False, 'offer': True})

    def test_sdk_pause_pauses(self):
        page = self.boot()
        self.play(page)
        fire(page, 'pause')
        state = page.evaluate(STATE)
        log(f'after GamePix on.pause: {state}')
        self.assertTrue(state['paused'])
        self.assert_frozen(page)
        self.screenshot(page, 'paused-by-sdk.png')

    def test_sdk_resume_keeps_pause_overlay(self):
        page = self.boot()
        self.play(page)
        fire(page, 'pause')
        fire(page, 'resume')
        state = page.evaluate(STATE)
        log(f'after GamePix on.pause + on.resume: {state}')
        self.assertTrue(state['paused'], 'on.resume must not auto-resume')
        self.assert_frozen(page)

    def test_sdk_pause_on_menu_is_harmless(self):
        page = self.boot()
        fire(page, 'pause')
        fire(page, 'resume')
        state = page.evaluate(STATE)
        log(f'menu + on.pause/on.resume: {state}')
        self.assertEqual(state, {'paused': False, 'menu': True, 'offer': False})


if __name__ == '__main__':
    unittest.main()
