"""CrazyGames gameplayStart/gameplayStop events driven through real input."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crazygames_harness import click_canvas, open_game, sdk_calls, start_crazygames_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
GAMEPLAY = ('game.gameplayStart', 'game.gameplayStop')
START, STOP = GAMEPLAY


def gameplay_events(page):
    return [c['name'] for c in sdk_calls(page) if c['name'] in GAMEPLAY]


class CrazyGamesGameplayEventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_crazygames_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('CG_EVENTS_EVIDENCE_DIR')
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

    def boot(self):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.goto(self.url + 'index.html')
        page.wait_for_function('CG.environment === "crazygames" && menu.visible')
        return page

    def click_button(self, page, button, scaled=False):
        """Click the centre of a menu Button (background x/y is top-left)."""
        b = page.evaluate(f'''(() => {{
            const b = {button}.background
            const k = {'scale[version]' if scaled else '1'}
            return {{x: (b.x + b.width / 2) * k, y: (b.y + b.height / 2) * k}}
        }})()''')
        click_canvas(page, b['x'], b['y'])
        # events.js ignores input for STYLE.timing.inputUntouchMs after a button click
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def assert_no_repeats(self, events):
        for a, b in zip(events, events[1:]):
            self.assertNotEqual(a, b, f'repeated gameplay event in {events}')

    def save(self, page, name):
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / name))

    def test_scenario_sequence(self):
        """menu -> chill -> Esc -> Esc -> pause btn -> menu -> main -> blur -> resume."""
        page = self.boot()
        self.click_button(page, 'menu.classicVersionButton')
        self.assertFalse(page.evaluate('menu.visible'))
        page.wait_for_timeout(1000)
        page.keyboard.press('Escape')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        page.wait_for_timeout(100)
        self.save(page, 'paused.png')
        page.keyboard.press('Escape')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        page.wait_for_timeout(300)
        self.click_button(page, 'menu.button', scaled=True)
        self.assertTrue(page.evaluate('menu.gamePaused'))
        self.click_button(page, 'menu.backToMenu')
        self.assertTrue(page.evaluate('menu.visible'))
        self.click_button(page, 'menu.badVersionButton')
        self.assertEqual(page.evaluate('version'), 'bad')
        page.wait_for_timeout(1000)
        before_blur = gameplay_events(page)
        page.evaluate('window.dispatchEvent(new Event("blur"))')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        page.wait_for_timeout(100)
        self.save(page, 'blur-paused.png')
        self.assertEqual(gameplay_events(page), before_blur)
        self.click_button(page, 'menu.resume')
        self.assertFalse(page.evaluate('menu.gamePaused'))

        calls = sdk_calls(page)
        events = gameplay_events(page)
        if self.evidence:
            Path(self.evidence).mkdir(parents=True, exist_ok=True)
            (Path(self.evidence) / 'sdk-calls-scenario.json').write_text(
                json.dumps(calls, indent=2) + '\n')
        print(f'\n  gameplay events={events}', file=sys.stderr)
        self.assertEqual(events, [START, STOP, START, STOP, START])
        self.assertEqual(events, before_blur, 'blur pause/resume sent an event')
        self.assert_no_repeats(events)
        print('  ASSERT sequence == [start, stop, start, stop, start]: pass;'
              ' blur pause/resume events: none; consecutive repeats: none',
              file=sys.stderr)

    def test_forced_death_sends_nothing(self):
        """reStart() (instant death) keeps gameplay active and sends no event."""
        page = self.boot()
        self.click_button(page, 'menu.badVersionButton')
        page.wait_for_timeout(500)
        before = gameplay_events(page)
        self.assertEqual(before, [START])
        page.evaluate('reStart()')
        page.wait_for_timeout(500)
        page.evaluate('reStart()')
        page.wait_for_timeout(300)
        events = gameplay_events(page)
        print(f'\n  after 2x reStart events={events}', file=sys.stderr)
        self.assertEqual(events, before)
        # Gameplay is still active: a user pause sends exactly one stop.
        page.keyboard.press('Escape')
        events = gameplay_events(page)
        self.assertEqual(events, [START, STOP])
        self.assert_no_repeats(events)
        print('  ASSERT forced death (reStart) gameplay events: none;'
              ' consecutive repeats: none', file=sys.stderr)

    def test_wrapper_never_repeats(self):
        """Direct repeated CG calls collapse; blur pause then unpause sends nothing."""
        page = self.boot()
        page.evaluate('''() => {
            CG.gameplayStop(); CG.gameplayStart(); CG.gameplayStart()
            CG.gameplayStop(); CG.gameplayStop(); CG.gameplayStart()
        }''')
        self.assertEqual(gameplay_events(page), [START, STOP, START])
        page.evaluate('''() => {
            menu.setVisible(false)
            menu.startPause('blur'); menu.unPause()
            menu.startPause('blur'); menu.unPause()
        }''')
        events = gameplay_events(page)
        print(f'\n  wrapper events={events}', file=sys.stderr)
        self.assertEqual(events, [START, STOP, START])
        self.assert_no_repeats(events)
        print('  ASSERT wrapper collapses repeats; blur pause+unpause events:'
              ' none; consecutive repeats: none', file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
