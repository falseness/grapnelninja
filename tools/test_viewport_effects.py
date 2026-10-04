"""Compare the viewport checker's real effects scenario in Chromium."""
import importlib.util
from io import BytesIO
from pathlib import Path
import subprocess
import unittest

from PIL import Image, ImageChops

from browser_test_support import start_browser_test
from playgama_harness import BRIDGE_URL
from verification_support import baseline_route, load_baseline_sources


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'viewport_checker', ROOT / 'tools/verify-viewport-percentages.py')
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class ViewportEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        # Files of the baseline tree: later additions (platform.js) do not exist there
        files = subprocess.check_output(
            ['git', 'ls-tree', '-r', '--name-only', 'a6b41aa'],
            cwd=ROOT, text=True).splitlines()
        cls.baseline = load_baseline_sources('a6b41aa', files)
        # TASK-112 capitalised the menu title on purpose; apply it to the baseline too
        cls.baseline['menu.js'] = cls.baseline['menu.js'].replace(b"'Grapnel ninja'", b"'Grapnel Ninja'")
        # TASK-120 added the speaker mute button to the menu, pause screen and
        # HUD: draw the current mutebutton.js at the same points in the baseline.
        # TASK-126 added the language toggle to the menu: draw the current
        # languagebutton.js (with i18n.js) there too
        # TASK-127: the buttons report to LAYOUT_PROBE (menu.js) and size from
        # getCanvasCssRect (gameoptions.js), both newer than the baseline
        cls.baseline['mutebutton.js'] = (
            b"const LAYOUT_PROBE = {rect() {}, text() {}}\n"
            b"function getCanvasCssRect() { return canvas.getBoundingClientRect() }\n"
            + (ROOT / 'mutebutton.js').read_bytes())
        # TASK-127 capped button labels at 0.8 of the button height
        for old in [b"this.getFittedTextSize(text.text, this.background.height)",
                    b"button.getFittedTextSize(button.text.text, height)"]:
            assert cls.baseline['menu.js'].count(old) == 1, old
            cls.baseline['menu.js'] = cls.baseline['menu.js'].replace(old, old[:-1] + b" * 0.8)")
        for name, old, new in [
                ('index.html', b"<script src = 'menu.js'></script>",
                 b"<script src = 'menu.js'></script><script src = 'mutebutton.js'></script>"
                 b"<script src = 'i18n.js'></script><script src = 'languagebutton.js'></script>"),
                ('menu.js', b"this.backToMenu.draw()\n",
                 b"this.backToMenu.draw()\nMUTE_BUTTON.draw('pause')\n"),
                ('menu.js', b"this.timeInGame.draw()\n",
                 b"this.timeInGame.draw()\nMUTE_BUTTON.draw('menu')\nLANGUAGE_BUTTON.draw()\n"),
                ('render/draw.js', b"ctx.scale(1 / scale[version], 1 / scale[version])\n}",
                 b"ctx.scale(1 / scale[version], 1 / scale[version])\nMUTE_BUTTON.draw('hud')\n}")]:
            assert cls.baseline[name].count(old) == 1, (name, old)
            cls.baseline[name] = cls.baseline[name].replace(old, new)

    def sample(self, mode, baseline):
        page = self.browser.new_page(viewport={'width': 1920, 'height': 1080})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        try:
            page.add_init_script(CHECKER.init)
            # Keep the real Bridge (and its splash screen) out, so PLATFORM
            # boots disabled
            page.route(BRIDGE_URL, lambda route: route.fulfill(
                content_type='application/javascript', body=''))
            if baseline:
                page.route('**/*', baseline_route(self.baseline))
            page.goto(self.url)
            if not baseline:
                # Since TASK-117 boot() waits for animation frames before start(),
                # and the checker's init script stubs requestAnimationFrame: run
                # the rest of boot by hand (draw the menu, hide #loading)
                page.wait_for_function("document.getElementById('loading-progress')"
                                       ".textContent == 'Starting...'")
                page.evaluate("() => { start(); document.getElementById('loading').hidden = true }")
            effects = page.evaluate(CHECKER.scenario, mode)
            for part in ['particles', 'trails', 'hud', 'screenEffects']:
                self.assertGreater(len(effects['parts'][part]), 5, part)
            images = {}
            for stage, function in [('game', 'drawTestGame'),
                                    ('menu', 'drawTestMenu'),
                                    ('pause', 'drawTestPause')]:
                page.evaluate(function + '()')
                with Image.open(BytesIO(page.screenshot())) as image:
                    images[stage] = image.copy()
            return effects, images
        finally:
            page.close()
            self.assertEqual(errors, [], f'{mode} baseline={baseline}: browser errors')

    def test_deterministic_effects_baseline_current(self):
        passed = []
        for mode in ['classic', 'bad']:
            with self.subTest(mode=mode):
                old, old_images = self.sample(mode, baseline=True)
                new, new_images = self.sample(mode, baseline=False)
                for stage in ['game', 'menu', 'pause']:
                    self.assertEqual(old_images[stage].size, new_images[stage].size)
                    self.assertIsNone(ImageChops.difference(
                        old_images[stage], new_images[stage]).getbbox(), (mode, stage))
                for field in ['parts', 'particles', 'shake', 'quality', 'panel']:
                    CHECKER.near(old[field], new[field], mode + '.' + field)
                CHECKER.near(CHECKER.normalized_style(old['style']),
                             CHECKER.normalized_style(new['style']))
                print(f'PASS {mode} baseline a6b41aa/current 1920x1080: '
                      'game/menu/pause pixel equality; normalized effects equality; '
                      'browser console/page errors=0', flush=True)
                passed.append(mode)
        self.assertEqual(passed, ['classic', 'bad'])
        print('PASS deterministic effects baseline/current: classic,bad', flush=True)


if __name__ == '__main__':
    unittest.main()
