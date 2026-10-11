"""The Y8 PLATFORM adapter: offline boot, storage, no ads without an SDK,
rewarded support with the fake SDK, hidden-tab pause."""
import json
import os
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot
from game_harness import FAKE_SDK_URL, READY, install_kill, sdk_calls, serve_fake_sdk

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
RECORDS_KEY = 'grapnelninja.records'
# The only script index.html loads from outside the test server; the
# OfflineBrowser serves it with a rejecting stub (environment "disabled")
SDK_URL = FAKE_SDK_URL

# A cross-origin iframe with blocked storage: every localStorage access throws
BLOCK_STORAGE = '''Object.defineProperty(window, 'localStorage', {
    configurable: true,
    get() { throw new DOMException('The operation is insecure.', 'SecurityError') }
})'''

# Count physics ticks; window.__kill places the ninja on the top side floor
# before the next tick (a real lethal death through ninja.move(), see
# game_harness.PLACE_ON_TOP_SIDE). Otherwise the ninja is pinned so it never
# dies on its own.
INSTRUMENT_RUN = '''() => {
    window.__ticks = 0
    window.__reStarts = 0
    const original = window.reStart
    window.reStart = function() {
        window.__reStarts++
        window.__pin = null
        return original.apply(this, arguments)
    }
    const physicsStep = window.physics
    window.physics = function() {
        window.__ticks++
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        if (window.__kill) {
            window.__kill = false
            window.__killed = window.__placeOnTopSide()
            return physicsStep.apply(this, arguments)
        }
        const result = physicsStep.apply(this, arguments)
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        ninja.x = window.__pin.x
        ninja.y = window.__pin.y
        ninja.speedX = 0
        ninja.speedY = 0
        return result
    }
}'''

START_CLASSIC = '''() => {
    const b = menu.classicVersionButton.background
    menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
}'''

STATE = '''() => ({offer: continueOffer.visible, score: scoreText.count[version],
    record: scoreText.record[version], reStarts: window.__reStarts,
    menuVisible: menu.visible, gamePaused: menu.gamePaused,
    interstitialPending: interstitialPending, adOpen: adOpen})'''

PLATFORM_STATE = '''() => ({environment: PLATFORM.environment, platformId: PLATFORM.platformId,
    rewarded: PLATFORM.isRewardedSupported(), interstitial: PLATFORM.isInterstitialSupported(),
    sdkScript: typeof window.y8 === 'object' && typeof window.y8.sdk === 'function'})'''


class Y8PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.origin = '{0.scheme}://{0.netloc}'.format(urlsplit(cls.url))
        cls.evidence = Path(os.environ.get('PLATFORM_EVIDENCE_DIR') or '')
        cls.save_evidence = bool(os.environ.get('PLATFORM_EVIDENCE_DIR'))

    def out(self, name):
        path = self.evidence / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def open(self, init_script=None, fake_sdk=None):
        context = self.browser.new_context(viewport=VIEWPORT)
        self.addCleanup(context.close)
        if init_script:
            context.add_init_script(init_script)
        if fake_sdk is not None:
            serve_fake_sdk(context, fake_sdk)
        page = context.new_page()
        errors = []
        requests = []
        failed = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('request', lambda r: requests.append(r.url))
        page.on('requestfailed', lambda r: failed.append(r.url))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page, errors, requests, failed

    def boot(self, page):
        page.goto(self.url + 'index.html')
        wait_for_boot(page)
        page.wait_for_function(READY, timeout=15000)

    def start_run(self, page):
        install_kill(page)
        page.evaluate(INSTRUMENT_RUN)
        page.evaluate(START_CLASSIC)
        page.wait_for_function('window.__ticks > 10')

    def score_and_die(self, page, points):
        page.evaluate('n => { for (let i = 0; i < n; i++) changeScoreText() }', points)
        before = page.evaluate(STATE)
        self.assertEqual(before['score'], points)
        page.evaluate('window.__kill = true')
        page.wait_for_function('!window.__kill && window.__reStarts > 0', timeout=5000)
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate('window.__killed.element'), 'Side')
        return before, page.evaluate(STATE)

    def test_a_offline_boot(self):
        page, errors, requests, failed = self.open()
        self.boot(page)
        platform = page.evaluate(PLATFORM_STATE)
        # SDK stubbed (init rejects): "disabled" on the "y8" platform, no ads
        self.assertEqual(platform, {'environment': 'disabled', 'platformId': 'y8',
                                    'rewarded': False, 'interstitial': False,
                                    'sdkScript': True})
        self.assertEqual(page.evaluate('typeof window.bridge'), 'undefined')
        page.wait_for_timeout(500)
        foreign = [u for u in requests if not u.startswith(self.origin + '/')]
        if self.save_evidence:
            self.out('requests.json').write_text(json.dumps(
                {'origin': self.origin, 'count': len(requests), 'foreign': foreign,
                 'failed': failed, 'requests': requests}, indent=1) + '\n')
            page.screenshot(path=str(self.out('screens/menu.png')))
        self.assertTrue(requests)
        # The SDK script is the only request that leaves the test server, and
        # the stub route answers it: nothing reaches the network or fails
        self.assertEqual(foreign, [SDK_URL])
        self.assertEqual(failed, [])
        self.assertEqual(errors, [])

    def test_b_storage_round_trip(self):
        page, _, _, _ = self.open()
        self.boot(page)
        page.evaluate('''() => {
            scoreText.record.classic = 42
            scoreText.record.bad = 7
            setLanguage('ru')
            PROGRESS.flush()
        }''')
        stored = page.evaluate('() => localStorage.getItem("%s")' % RECORDS_KEY)
        self.assertEqual(json.loads(stored), {'classic': 42, 'bad': 7})
        page.reload()
        wait_for_boot(page)
        page.wait_for_function(READY, timeout=15000)
        after = page.evaluate('''() => ({classic: scoreText.record.classic,
            bad: scoreText.record.bad, lang: I18N.language})''')
        self.assertEqual(after, {'classic': 42, 'bad': 7, 'lang': 'ru'})

    def test_c_blocked_storage(self):
        page, errors, _, _ = self.open(BLOCK_STORAGE)
        self.boot(page)
        with self.assertRaises(Exception):
            page.evaluate('window.localStorage')
        self.start_run(page)
        _, after = self.score_and_die(page, 3)
        self.assertEqual(after['record'], 3)
        page.evaluate('PROGRESS.flush()')
        stored = page.evaluate('async () => PLATFORM.storage.getMany(["%s"])' % RECORDS_KEY)
        self.assertEqual(json.loads(stored[RECORDS_KEY])['classic'], 3)
        self.assertEqual(errors, [])

    def test_d_no_continue_offer(self):
        page, _, _, _ = self.open()
        self.boot(page)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'disabled')
        self.assertFalse(page.evaluate('PLATFORM.isRewardedSupported()'))
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialSupported()'))
        self.start_run(page)
        before, after = self.score_and_die(page, max(5, page.evaluate('CONTINUE_MIN_SCORE')))
        if self.save_evidence:
            page.screenshot(path=str(self.out('screens/after-death-score5.png')))
            self.out('death-state.json').write_text(json.dumps(
                {'before': before, 'after': after}, indent=1) + '\n')
        # Without an SDK: a new run at once, no offer, no interstitial
        self.assertEqual(after['reStarts'], 1)
        self.assertFalse(after['offer'])
        self.assertFalse(after['interstitialPending'])
        self.assertFalse(after['adOpen'])
        self.assertFalse(after['menuVisible'])
        self.assertEqual(after['score'], 0)
        self.assertEqual(after['record'], 5)
        page.wait_for_timeout(300)
        self.assertFalse(page.evaluate('continueOffer.visible'))

    def test_e_hidden_tab_pauses(self):
        page, _, _, _ = self.open()
        self.boot(page)
        self.start_run(page)
        page.evaluate('''() => {
            Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'})
            Object.defineProperty(document, 'hidden', {configurable: true, get: () => true})
            document.dispatchEvent(new Event('visibilitychange'))
        }''')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        page.wait_for_timeout(100)
        ticks = page.evaluate('window.__ticks')
        page.wait_for_timeout(700)
        self.assertEqual(page.evaluate('window.__ticks'), ticks)

    def test_f_fake_sdk_boots_y8(self):
        # The fake SDK initialises: environment "y8", rewarded ads offered
        page, errors, _, failed = self.open(fake_sdk={})
        self.boot(page)
        platform = page.evaluate(PLATFORM_STATE)
        self.assertEqual(platform, {'environment': 'y8', 'platformId': 'y8',
                                    'rewarded': True, 'interstitial': False,
                                    'sdkScript': True})
        calls = sdk_calls(page)
        init = [c for c in calls if c['name'] == 'init']
        self.assertEqual(len(init), 1)
        self.assertEqual(init[0]['args'], [['appId', 'autoLogin'],
                                           ['gameId', 'preloadAdBreaks', 'sound']])
        self.assertNotIn('showAd', [c['name'] for c in calls])
        self.start_run(page)
        # An eligible death now holds the run behind the offer instead of restarting
        page.evaluate('n => { for (let i = 0; i < n; i++) changeScoreText() }', 5)
        page.evaluate('window.__kill = true')
        page.wait_for_function('!window.__kill && continueOffer.visible', timeout=5000)
        page.wait_for_timeout(200)
        after = page.evaluate(STATE)
        self.assertEqual((after['offer'], after['reStarts'], after['score']), (True, 0, 5))
        self.assertEqual(failed, [])
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
