"""Boot index.html against the fake/blocked/never-ready Y8 SDK."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from y8_harness import click_canvas, open_game, sdk_calls, start_y8_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}

# Records when the menu first draws text on the game canvas.
MENU_HOOK = '''(() => {
    const fillText = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function () {
        if (window.__menuDrawnAt === undefined && this.canvas.id === 'canvas')
            window.__menuDrawnAt = performance.now()
        return fillText.apply(this, arguments)
    }
})()'''

# The fake records object arguments only as key lists; capture the real ones.
INIT_SPY = '''(() => {
    window.__initArgs = []
    const hook = () => {
        if (!window.y8 || window.y8.__spied)
            return
        window.y8.__spied = true
        const sdk = window.y8.sdk()
        const init = sdk.init
        sdk.init = function () {
            window.__initArgs.push(JSON.parse(JSON.stringify(Array.from(arguments))))
            return init.apply(this, arguments)
        }
    }
    window.addEventListener('y8sdk.ready', hook, {capture: true})
    document.addEventListener('DOMContentLoaded', hook)
})()'''


class Y8SdkBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_y8_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('Y8_BOOT_EVIDENCE_DIR')
        cls.errors = []

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            for kind in ('console', 'page', 'blocked_sdk'):
                lines = [f'{name}: {msg}' for name, errors in cls.errors
                         for msg in errors[kind]]
                (out / f'{kind}-errors.log').write_text(''.join(
                    line + '\n' for line in lines))

    def boot(self, **kwargs):
        context, page, errors = open_game(
            self.browser, 'about:blank', VIEWPORT, **kwargs)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.add_init_script(MENU_HOOK)
        page.add_init_script(INIT_SPY)
        page.goto(self.url + 'index.html')
        page.wait_for_function('window.__menuDrawnAt !== undefined', timeout=5000)
        return page, errors

    def save(self, page, name):
        if not self.evidence:
            return
        out = Path(self.evidence)
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f'boot-{name}.png'))
        (out / f'calls-{name}.json').write_text(
            json.dumps(sdk_calls(page), indent=2) + '\n')

    def assert_disabled_offer(self, page):
        """Menu is usable and the continue offer says 'Ads unavailable'."""
        self.assertTrue(page.evaluate('menu.visible'))
        b = page.evaluate('''() => {
            const bg = menu.classicVersionButton.background
            return {x: bg.x + bg.width / 2, y: bg.y + bg.height / 2}
        }''')
        click_canvas(page, b['x'], b['y'])
        page.wait_for_function('!menu.visible && ninja !== undefined')
        self.assertEqual(page.evaluate('''() => {
            scoreText.count[version] = CONTINUE_MIN_SCORE
            onLethalDeath()
            return [continueOffer.visible, continueOffer.notice()]
        }'''), [True, 'Ads unavailable'])

    def test_fake_sdk_boot(self):
        """Fake SDK: environment 'y8', menu visible, init called once with the IDs."""
        page, _ = self.boot()
        page.wait_for_function('PLATFORM.environment !== "pending"')
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'y8')
        self.assertTrue(page.evaluate('menu.visible'))
        inits = [c for c in sdk_calls(page) if c['name'] == 'init']
        self.assertEqual(len(inits), 1)
        args = page.evaluate('window.__initArgs')
        ids = page.evaluate('Y8_CONFIG')
        print(f'\n  initArgs={args} ids={ids}', file=sys.stderr)
        self.assertEqual(len(args), 1)
        self.assertEqual(args[0][0]['appId'], ids['appId'])
        self.assertEqual(args[0][1]['gameId'], ids['gameId'])
        self.assertEqual(page.evaluate('continueOffer.adsAvailable'), True)
        self.save(page, 'fake')

    def test_blocked_sdk_disabled(self):
        """Blocked SDK: 'disabled' within 3.5 s, menu usable, 'Ads unavailable'."""
        page, errors = self.boot(block_sdk=True)
        page.wait_for_function('PLATFORM.environment === "disabled"', timeout=3500)
        print(f'\n  environment=disabled blockedSdk={len(errors["blocked_sdk"])}',
              file=sys.stderr)
        self.assertEqual(sdk_calls(page), [])
        self.assert_disabled_offer(page)
        self.save(page, 'blocked')

    def test_ready_never_disabled(self):
        """SDK never fires ready: same as blocked."""
        page, _ = self.boot(fake_options={'readyNever': True})
        page.wait_for_function('PLATFORM.environment === "disabled"', timeout=3500)
        self.assertEqual([c for c in sdk_calls(page) if c['name'] == 'init'], [])
        self.assert_disabled_offer(page)
        self.save(page, 'ready-never')

    def test_disabled_rewarded_reports_error(self):
        """Disabled platform: requestRewarded calls adError('disabled') once."""
        page, _ = self.boot(block_sdk=True)
        page.wait_for_function('PLATFORM.environment === "disabled"', timeout=3500)
        self.assertEqual(page.evaluate('''() => {
            const seen = []
            PLATFORM.requestRewarded({
                adFinished: () => seen.push('finished'),
                adError: e => seen.push(e.code)
            })
            return seen
        }'''), ['disabled'])


if __name__ == '__main__':
    unittest.main()
