"""Boot index.html against the fake/blocked GamePix SDK."""
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamepix_harness import (GAMEPIX_SDK_URL, click_canvas, open_game, sdk_calls,
                             sdk_errors, start_gamepix_test)

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
MENU_READY = 'typeof menu !== "undefined" && menu.visible && !document.getElementById("loading")'


class HeadScripts(HTMLParser):
    """Collect the <script> tags that appear inside <head>."""
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        elif tag == 'script' and self.in_head:
            self.scripts.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


class StaticIndexTests(unittest.TestCase):
    def test_gamepix_tag_first_script(self):
        """The GamePix SDK is the first <script> in <head>, synchronous."""
        parser = HeadScripts()
        parser.feed((ROOT / 'index.html').read_text(encoding='utf-8'))
        self.assertTrue(parser.scripts)
        first = parser.scripts[0]
        self.assertEqual(first.get('src'), GAMEPIX_SDK_URL)
        self.assertNotIn('async', first)
        self.assertNotIn('defer', first)


class GamePixSdkBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_gamepix_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('GAMEPIX_BOOT_EVIDENCE_DIR')
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
        page.goto(self.url + 'index.html')
        page.wait_for_function(MENU_READY, timeout=5000)
        return page, errors

    def save(self, page, name):
        if not self.evidence:
            return
        out = Path(self.evidence)
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f'boot-{name}.png'))
        (out / f'calls-{name}.json').write_text(
            json.dumps(sdk_calls(page), indent=2) + '\n')

    def test_fake_sdk_boot(self):
        """Fake SDK: environment 'gamepix', menu visible, ads available."""
        page, _ = self.boot()
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'gamepix')
        self.assertTrue(page.evaluate('menu.visible'))
        self.assertEqual(page.evaluate('continueOffer.adsAvailable'), True)
        self.assertEqual(sdk_errors(page), [])
        self.save(page, 'fake')

    def test_call_order(self):
        """loading(...)* -> loaded once, nothing before loaded, last loading 100."""
        page, _ = self.boot()
        calls = sdk_calls(page)
        names = [c['name'] for c in calls]
        print(f'\n  calls={names}', file=sys.stderr)
        self.assertEqual(names.count('loaded'), 1)
        first_loaded = names.index('loaded')
        before = calls[:first_loaded]
        self.assertTrue(before)
        self.assertEqual({c['name'] for c in before}, {'loading'})
        self.assertEqual(before[-1]['args'], [100])
        values = [c['args'][0] for c in before]
        self.assertEqual(values, sorted(values))
        self.assertEqual(sdk_errors(page), [])

    def test_blocked_sdk_disabled(self):
        """Blocked SDK: 'disabled' within 1 s, menu usable, 'Ads unavailable'."""
        page, errors = self.boot(block_sdk=True)
        page.wait_for_function('PLATFORM.environment === "disabled"', timeout=1000)
        # Upper bound since navigation start: disabled and menu ready by now
        elapsed = page.evaluate('performance.now()')
        print(f'\n  environment=disabled, menu ready by {elapsed:.0f} ms '
              f'blockedSdk={len(errors["blocked_sdk"])}', file=sys.stderr)
        self.assertLess(elapsed, 1000)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'disabled')
        self.assertIsNone(page.query_selector('#loading'))
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
        self.save(page, 'blocked')

    def test_disabled_rewarded_reports_error(self):
        """Disabled platform: requestRewarded calls adError('disabled') once."""
        page, _ = self.boot(block_sdk=True)
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
