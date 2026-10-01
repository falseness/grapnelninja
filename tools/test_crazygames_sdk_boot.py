"""Boot index.html against the fake/blocked/hanging CrazyGames SDK."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crazygames_harness import open_game, sdk_calls, start_crazygames_test

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


class CrazyGamesSdkBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_crazygames_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('CG_BOOT_EVIDENCE_DIR')
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

    def boot(self, **kwargs):
        context, page, errors = open_game(
            self.browser, 'about:blank', VIEWPORT, **kwargs)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.add_init_script(MENU_HOOK)
        page.goto(self.url + 'index.html')
        page.wait_for_function('window.__menuDrawnAt !== undefined', timeout=5000)
        return page, errors

    def save(self, page, name):
        if not self.evidence:
            return
        out = Path(self.evidence)
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f'menu-{name}.png'))
        (out / f'calls-{name}.json').write_text(
            json.dumps(sdk_calls(page), indent=2) + '\n')

    def test_fake_sdk_init_before_menu(self):
        """(a) fake SDK: [init, loadingStart, loadingStop]; init resolves before menu draws."""
        page, _ = self.boot()
        page.wait_for_function('CG.environment !== "pending"')
        calls = sdk_calls(page)
        names = [c['name'] for c in calls]
        self.assertEqual(names, ['init', 'game.loadingStart', 'game.loadingStop'])
        resolved = page.evaluate('window.__cgFake.initResolvedAt')
        drawn = page.evaluate('window.__menuDrawnAt')
        print(f'\n  calls={names} initResolvedAt={resolved:.1f} '
              f'menuDrawnAt={drawn:.1f}', file=sys.stderr)
        self.assertLess(resolved, drawn)
        self.assertLess(calls[1]['t'], calls[2]['t'])
        self.assertEqual(page.evaluate('CG.environment'), 'crazygames')
        self.assertTrue(page.evaluate('menu.visible'))
        self.save(page, 'fake')

    def test_blocked_sdk_disabled(self):
        """(b) blocked SDK: menu renders, CG.environment == 'disabled', no page errors."""
        page, errors = self.boot(block_sdk=True)
        self.assertEqual(page.evaluate('CG.environment'), 'disabled')
        self.assertTrue(page.evaluate('menu.visible'))
        print(f'\n  environment=disabled pageErrors={len(errors["page"])}',
              file=sys.stderr)
        self.assertEqual(sdk_calls(page), [])
        self.assertEqual(errors['page'], [])
        # Wrapper calls are safe no-ops / localStorage fallbacks.
        self.assertEqual(page.evaluate('''async () => {
            CG.gameplayStart(); CG.gameplayStop()
            CG.loadingStart(); CG.loadingStop()
            CG.data.setItem('k', 'v')
            let adError = false
            CG.requestAd('midgame', {adError: () => { adError = true }})
            return [CG.data.getItem('k'), adError, await CG.hasAdblock()]
        }'''), ['v', True, False])
        self.save(page, 'blocked')

    def test_hanging_init_times_out(self):
        """(c) init never resolves: timeout disables SDK, menu renders within 5 s."""
        page, _ = self.boot(fake_options={'initHang': True})
        self.assertEqual(page.evaluate('CG.environment'), 'disabled')
        self.assertTrue(page.evaluate('menu.visible'))
        drawn = page.evaluate('window.__menuDrawnAt')
        print(f'\n  menuDrawnAt={drawn:.1f}ms', file=sys.stderr)
        self.assertLess(drawn, 5000)
        self.assertEqual([c['name'] for c in sdk_calls(page)], ['init'])


if __name__ == '__main__':
    unittest.main()
