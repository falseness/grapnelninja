"""Pause and the continue offer must freeze gameplay in gameLoop.

While menu.gamePaused the loop does nothing: no physics step and no world
redraw over the frozen pause frame (drawn once by menu.startPause). While continueOffer.visible the
world and offer are redrawn but physics does not step.
"""
from contextlib import ExitStack
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from render_snapshot import CLOCK_SCRIPT, boot_frozen


class PauseLoopTest(unittest.TestCase):
    def test_pause_and_continue_offer_freeze_physics(self):
        with ExitStack() as stack:
            url, browser = start_browser_test(Path(__file__).resolve().parent.parent, stack.callback)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            stack.callback(context.close)
            context.add_init_script(CLOCK_SCRIPT)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
            page.goto(url + 'index.html')
            boot_frozen(page)
            result = page.evaluate('''() => {
                const originals = {pauseScreen: menu.drawPauseScreen, draw, physics, offerDraw: continueOffer.draw};
                let counts;
                const reset = () => counts = {pauses: 0, worlds: 0, steps: 0, offers: 0};
                menu.drawPauseScreen = () => counts.pauses++;
                draw = () => counts.worlds++;
                physics = () => counts.steps++;
                continueOffer.draw = () => counts.offers++;
                let time = 3000;
                const frames = n => { for (let i = 0; i < n; i++) gameLoop(time += 17); return {...counts}; };
                try {
                    reset(); const running = frames(2);
                    menu.startPause();
                    reset(); const paused = frames(2);
                    menu.unPause();
                    reset(); const resumed = frames(2);
                    continueOffer.show();
                    reset(); const offer = frames(2);
                    continueOffer.hide();
                    return {running, paused, resumed, offer, gamePaused: menu.gamePaused};
                } finally {
                    menu.drawPauseScreen = originals.pauseScreen;
                    draw = originals.draw;
                    physics = originals.physics;
                    continueOffer.draw = originals.offerDraw;
                }
            }''')
            # Baseline: an unpaused run steps physics and redraws the world every frame.
            self.assertEqual(result['running']['worlds'], 2)
            self.assertGreater(result['running']['steps'], 0)
            self.assertEqual(result['running']['pauses'], 0)
            # Paused: physics, world and pause-screen redraw are all frozen.
            self.assertEqual(result['paused'], {'pauses': 0, 'worlds': 0, 'steps': 0, 'offers': 0})
            # Leaving pause returns to the stepping branch.
            self.assertFalse(result['gamePaused'])
            self.assertEqual(result['resumed']['pauses'], 0)
            self.assertEqual(result['resumed']['worlds'], 2)
            self.assertGreater(result['resumed']['steps'], 0)
            # Continue offer: world and offer redraw, physics does not step.
            self.assertEqual(result['offer'], {'pauses': 0, 'worlds': 2, 'steps': 0, 'offers': 2})
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
