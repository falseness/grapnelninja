"""Momentum is the boot default: a fresh page starts a live momentum run.

Classic and bad stay reachable through the pause mode selector.
Requires Playwright Chromium. No remote requests.
"""
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from game_harness import switch_mode

ROOT = Path(__file__).resolve().parents[1]
STATE = '''() => ({version, runInProgress, paused: menu.gamePaused,
    hp: momentumState.hp, streak: momentumState.greenStreak,
    momentumScreen: screen instanceof MomentumScreen})'''


class MomentumBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self, **context_options):
        options = {'viewport': {'width': 1280, 'height': 720}, **context_options}
        context = self.browser.new_context(locale='en-US', **options)
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        wait_for_boot_run(page)
        return page

    def test_fresh_page_boots_momentum(self):
        page = self.open()
        state = page.evaluate(STATE)
        self.assertEqual(state, {'version': 'momentum', 'runInProgress': True, 'paused': False,
                                 'hp': 5, 'streak': 0, 'momentumScreen': True})
        # The run is live: the ninja moves on later frames
        page.wait_for_function('ninja.x !== %r || ninja.y !== %r' % tuple(
            page.evaluate('[ninja.x, ninja.y]')))
        print('PASS desktop boot:', state, flush=True)

    def test_landscape_touch_boot_momentum(self):
        page = self.open(viewport={'width': 844, 'height': 390}, has_touch=True, is_mobile=True)
        state = page.evaluate(STATE)
        self.assertEqual(state, {'version': 'momentum', 'runInProgress': True, 'paused': False,
                                 'hp': 5, 'streak': 0, 'momentumScreen': True})
        print('PASS landscape touch boot:', state, flush=True)

    def test_classic_and_bad_reachable_from_menu(self):
        page = self.open()
        for mode in ('bad', 'classic', 'momentum'):
            switch_mode(page, mode)
            state = page.evaluate(STATE)
            self.assertEqual((state['version'], state['runInProgress'], state['paused']),
                             (mode, True, False))
            self.assertEqual(state['momentumScreen'], mode == 'momentum')
            print('PASS switch to', mode, state, flush=True)


if __name__ == '__main__':
    unittest.main()
