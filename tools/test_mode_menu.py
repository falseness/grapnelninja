"""Mode selector on the pause and death screens (TASK-002).

The two-way classic<->bad switch is now a row of three buttons: classic
('chill version'), bad ('main version') and momentum. Picking one starts a
run in that mode; the running mode is outlined in the primary colour.
game_harness.switch_mode reaches every mode from every other through real
mouse clicks on that row. Boot still runs 'bad'.

MODE_MENU_EVIDENCE_DIR (default: artifacts/TASK-002) receives
pause-menu.png and death-screen.png at 1280x720.

Requires Playwright Chromium. No remote requests.
"""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import READY, click_canvas, collect_errors, start_game_test, switch_mode

ROOT = Path(__file__).resolve().parent.parent
MODES = ('classic', 'bad', 'momentum')
LABELS = {'classic': 'chill version', 'bad': 'main version', 'momentum': 'momentum'}
TRANSITIONS = [(a, b) for a in MODES for b in MODES if a != b]
# Counts startGame calls and records the mode each was asked for
SPY = '''() => {
    window.__starts = []
    const start = window.startGame
    window.startGame = function(mode) { __starts.push(mode); return start.apply(this, arguments) }
}'''
SELECTOR = '''() => MODE_OPTIONS.map(o => {
    const b = menu.modeSelector.button(o.mode)
    return {mode: o.mode, label: b.text.text, stroke: b.background.stroke,
            clickable: b.clickable, x: b.background.x, y: b.background.y,
            width: b.background.width, height: b.background.height}
})'''


class ModeMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MODE_MENU_EVIDENCE_DIR', ROOT / 'artifacts/TASK-002'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = collect_errors(page)
        page.goto(self.url + 'index.html')
        self.addCleanup(lambda: self.assertEqual((errors['console'], errors['page']), ([], [])))
        page.wait_for_function(READY, timeout=15000)
        page.evaluate(SPY)
        return page

    def assert_row(self, buttons):
        self.assertEqual([b['label'] for b in buttons], [LABELS[m] for m in MODES])
        for a, b in zip(buttons, buttons[1:]):
            self.assertLess(a['x'] + a['width'], b['x'], (a, b))
            self.assertAlmostEqual(a['y'], b['y'])

    def test_boot_default_is_momentum(self):
        page = self.open()
        self.assertEqual(page.evaluate('version'), 'momentum')

    def test_transitions(self):
        for source, target in TRANSITIONS:
            with self.subTest(transition=f'{source}->{target}'):
                page = self.open()
                switch_mode(page, source)
                page.wait_for_timeout(300)
                page.evaluate('window.__starts = []')
                switch_mode(page, target)
                page.wait_for_timeout(300)
                state = page.evaluate('({version, runInProgress, paused: menu.gamePaused,'
                                      ' starts: __starts.slice()})')
                print(f'{source}->{target}:', state)
                self.assertEqual(state['version'], target)
                self.assertTrue(state['runInProgress'])
                self.assertFalse(state['paused'])
                # One pick, through the selector's startGame(<mode>)
                self.assertEqual(state['starts'], [target])

    def test_pause_menu_shows_three_modes(self):
        page = self.open()
        switch_mode(page, 'momentum')
        page.wait_for_timeout(300)
        page.evaluate('menu.startPause()')
        buttons = page.evaluate(SELECTOR)
        print('pause selector:', buttons)
        self.assert_row(buttons)
        self.assertTrue(all(b['clickable'] for b in buttons))
        primary = page.evaluate('STYLE.colors.ui.primary')
        self.assertEqual([b['stroke'] == primary for b in buttons], [False, False, True])
        # The old switch alias: from momentum it led to 'bad'
        self.assertEqual(page.evaluate('menu.backToMenu.text.text'), 'main version')
        page.screenshot(path=str(self.out / 'pause-menu.png'))

    def test_death_screen_picks_mode(self):
        page = self.open()
        # Boot runs momentum (TASK-019); this is bad's death screen
        switch_mode(page, 'bad')
        page.wait_for_function('!ninja.isInvulnerable()')
        page.evaluate('PLATFORM.isInterstitialDue = () => true; onLethalDeath()')
        page.wait_for_function('continueOffer.visible')
        page.evaluate('draw(); continueOffer.draw()')
        buttons = page.evaluate(SELECTOR.replace('menu.modeSelector', 'continueOffer.modeSelector'))
        print('death selector:', buttons)
        self.assert_row(buttons)
        self.assertTrue(all(b['clickable'] for b in buttons))
        self.assertEqual(page.evaluate('continueOffer.switchButton.text.text'), 'chill version')
        restart = page.evaluate('(b => ({y: b.y, height: b.height}))(continueOffer.restartButton.background)')
        self.assertGreater(buttons[0]['y'], restart['y'] + restart['height'])
        page.screenshot(path=str(self.out / 'death-screen.png'))

        momentum = buttons[2]
        page.evaluate('window.__starts = []')
        click_canvas(page, momentum['x'] + momentum['width'] / 2, momentum['y'] + momentum['height'] / 2)
        page.wait_for_function("version === 'momentum' && runInProgress && !continueOffer.visible")
        self.assertEqual(page.evaluate('__starts.slice()'), ['momentum'])


if __name__ == '__main__':
    unittest.main()
