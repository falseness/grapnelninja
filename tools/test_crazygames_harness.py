"""Exercise the fake CrazyGames SDK through crazygames_harness in Chromium."""
import json
import os
from pathlib import Path
import sys
import unittest

# Also importable as tools/test_crazygames_harness.py without PYTHONPATH=tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from crazygames_harness import (click_canvas, canvas_to_viewport, open_game,
                                sdk_calls, start_crazygames_test)

ROOT = Path(__file__).resolve().parent.parent
HOST = 'tools/fixtures/fake-sdk-host.html'
VIEWPORT = {'width': 1280, 'height': 720}


class CrazyGamesHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_crazygames_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('CG_HARNESS_EVIDENCE_DIR')
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

    def open(self, path=HOST, viewport=VIEWPORT, **kwargs):
        context, page, errors = open_game(self.browser, self.url + path,
                                          viewport, **kwargs)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        return page, errors

    def names(self, page):
        return [call['name'] for call in sdk_calls(page)]

    def test_init_resolves(self):
        page, _ = self.open()
        self.assertEqual(page.evaluate(
            'async () => { await CrazyGames.SDK.init(); return "resolved" }'),
            'resolved')
        self.assertEqual(page.evaluate('CrazyGames.SDK.environment'), 'crazygames')
        self.assertEqual(page.evaluate('CrazyGames.SDK.game.settings'),
                         {'muteAudio': False, 'disableChat': False})

    def test_calls_recorded_in_order(self):
        page, _ = self.open()
        page.evaluate('''async () => {
            const sdk = CrazyGames.SDK
            await sdk.init()
            sdk.game.loadingStart()
            sdk.game.loadingStop()
            sdk.game.gameplayStart()
            sdk.game.happytime()
            sdk.game.gameplayStop()
            sdk.data.setItem('best', 7)
        }''')
        calls = sdk_calls(page)
        self.assertEqual([c['name'] for c in calls], [
            'init', 'game.loadingStart', 'game.loadingStop',
            'game.gameplayStart', 'game.happytime', 'game.gameplayStop',
            'data.setItem'])
        self.assertEqual(calls[-1]['args'], ['best', 7])
        times = [c['t'] for c in calls]
        self.assertEqual(times, sorted(times))
        if self.evidence:
            Path(self.evidence, 'sample-calls.json').write_text(
                json.dumps(calls, indent=2) + '\n')

    def request_ad(self, page):
        return page.evaluate('''() => new Promise(resolve => {
            const seen = []
            const done = () => setTimeout(() => resolve(seen), 200)
            CrazyGames.SDK.ad.requestAd('rewarded', {
                adStarted: () => seen.push('adStarted'),
                adFinished: () => { seen.push('adFinished'); done() },
                adError: error => { seen.push('adError:' + error.code); done() }
            })
        })''')

    def test_ad_finished_outcome(self):
        page, _ = self.open(fake_options={'adOutcome': 'finished',
                                          'adDurationMs': 30})
        self.assertEqual(self.request_ad(page), ['adStarted', 'adFinished'])
        calls = sdk_calls(page)
        self.assertEqual([c['name'] for c in calls],
                         ['ad.requestAd', 'ad.adStarted', 'ad.adFinished'])
        self.assertGreaterEqual(calls[2]['t'] - calls[1]['t'], 25)

    def test_ad_error_outcome(self):
        page, _ = self.open(fake_options={'adOutcome': 'error'})
        self.assertEqual(self.request_ad(page), ['adError:other'])
        self.assertEqual(self.names(page), ['ad.requestAd', 'ad.adError'])

    def test_has_adblock_follows_option(self):
        for adblock in (True, False):
            with self.subTest(adblock=adblock):
                page, _ = self.open(fake_options={'adblock': adblock})
                self.assertIs(page.evaluate(
                    'CrazyGames.SDK.ad.hasAdblock()'), adblock)
                self.assertEqual(self.names(page), ['ad.hasAdblock'])

    def test_data_persists_across_reload(self):
        page, _ = self.open()
        page.evaluate('''() => {
            CrazyGames.SDK.data.setItem('best', '42')
            CrazyGames.SDK.data.setItem('gone', 'x')
            CrazyGames.SDK.data.removeItem('gone')
        }''')
        self.assertEqual(page.evaluate("localStorage.getItem('__cgfake:best')"), '42')
        page.reload()
        self.assertEqual(sdk_calls(page), [])
        self.assertEqual(page.evaluate("CrazyGames.SDK.data.getItem('best')"), '42')
        self.assertIsNone(page.evaluate("CrazyGames.SDK.data.getItem('gone')"))
        page.evaluate("localStorage.setItem('other', 'keep'); CrazyGames.SDK.data.clear()")
        self.assertIsNone(page.evaluate("CrazyGames.SDK.data.getItem('best')"))
        self.assertEqual(page.evaluate("localStorage.getItem('other')"), 'keep')

    def test_block_sdk_leaves_crazygames_undefined(self):
        page, errors = self.open(block_sdk=True)
        self.assertEqual(page.evaluate('typeof window.CrazyGames'), 'undefined')
        self.assertEqual(sdk_calls(page), [])
        self.assertEqual(len(errors['blocked_sdk']), 1)

    def test_click_canvas_uses_page_inverse(self):
        for viewport in (VIEWPORT, {'width': 720, 'height': 1280}):
            with self.subTest(viewport=viewport):
                page, _ = self.open('index.html', viewport)
                target = {'x': 300.0, 'y': 200.0}
                point = canvas_to_viewport(page, target['x'], target['y'])
                mapped = page.evaluate('p => viewportCoordsToCanvasCoords(p)', point)
                self.assertAlmostEqual(mapped['x'], target['x'], places=6)
                self.assertAlmostEqual(mapped['y'], target['y'], places=6)
                page.evaluate('''() => addEventListener('mousedown', e => {
                    window.__lastClick = viewportCoordsToCanvasCoords(
                        {x: e.clientX, y: e.clientY})
                }, true)''')
                click_canvas(page, target['x'], target['y'])
                clicked = page.evaluate('window.__lastClick')
                self.assertAlmostEqual(clicked['x'], target['x'], delta=1)
                self.assertAlmostEqual(clicked['y'], target['y'], delta=1)


if __name__ == '__main__':
    unittest.main()
