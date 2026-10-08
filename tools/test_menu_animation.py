"""Menu animation must not step gameplay or replace the paused game."""
from contextlib import ExitStack
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from render_snapshot import CLOCK_SCRIPT, boot_frozen


class MenuAnimationTest(unittest.TestCase):
    def test_menu_lifecycle_and_drift(self):
        with ExitStack() as stack:
            url, browser = start_browser_test(Path(__file__).resolve().parent.parent, stack.callback)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            stack.callback(context.close)
            context.add_init_script(CLOCK_SCRIPT)
            page = context.new_page()
            page.goto(url + 'index.html')
            boot_frozen(page)
            result = page.evaluate('''() => {
                const bg = visualEffects.background;
                const shifts = [];
                for (let time = 0; time <= 3000; time += 50) {
                    __snap.now = time;
                    shifts.push(bg.getMenuLayerShift(1.5));
                }
                let drift = 0;
                for (const a of shifts) for (const b of shifts)
                    drift = Math.max(drift, Math.hypot(a.x-b.x, a.y-b.y));
                let menus = 0, worlds = 0, steps = 0;
                const originalMenu = menu.draw, originalDraw = draw, originalPhysics = physics;
                menu.draw = () => menus++;
                draw = () => worlds++;
                physics = () => steps++;
                gameLoop(3000);
                gameLoop(3017);
                const idle = {menus, worlds, steps};
                menu.draw = originalMenu;
                draw = originalDraw;
                physics = originalPhysics;
                startGame('bad');
                menu.startPause();
                menu.draw = () => menus++;
                draw = () => worlds++;
                physics = () => steps++;
                gameLoop(3034);
                const paused = {menus, worlds, steps};
                menu.backToMenu.click();
                const before = menus;
                gameLoop(3051);
                return {idle, paused, returned: menus === before + 1, drift};
            }''')
            self.assertEqual(result['idle'], {'menus': 2, 'worlds': 0, 'steps': 0})
            self.assertEqual(result['paused'], result['idle'])
            self.assertTrue(result['returned'])
            self.assertGreater(result['drift'], 0)
            self.assertLessEqual(result['drift'], 10)


if __name__ == '__main__':
    unittest.main()
