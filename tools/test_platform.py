"""PLATFORM local adapter: boot, localStorage, no ads, hidden-tab pause.

master loads no platform SDK (c232782): platform.js is the local adapter,
PLATFORM.environment is 'local' and progress persists in localStorage, with
an in-memory fallback when storage is blocked.
"""
import json
import os
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot
from game_harness import switch_mode

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
RECORDS_KEY = 'grapnelninja.records'
READY = ('PLATFORM.environment === "local" && bootComplete && runInProgress'
         ' && document.getElementById("loading").hidden')

# A cross-origin iframe with blocked storage: every localStorage access throws
BLOCK_STORAGE = '''Object.defineProperty(window, 'localStorage', {
    configurable: true,
    get() { throw new DOMException('The operation is insecure.', 'SecurityError') }
})'''

# Count physics ticks; window.__kill moves the ninja into the deadly bottom
# side band before the next tick (a real lethal hit through ninja.move()).
# The persistent left wall (TASK-225) keeps it off the deletion border.
# Otherwise the ninja is pinned so it never dies on its own.
INSTRUMENT_RUN = '''() => {
    window.__ticks = 0
    window.__reStarts = 0
    // Record every time the death offer is shown
    window.__offerShown = 0
    let offerVisible = continueOffer.visible
    Object.defineProperty(continueOffer, 'visible', {
        configurable: true,
        get: () => offerVisible,
        set: value => {
            if (value) window.__offerShown++
            offerVisible = value
        }
    })
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
            ninja.invulnerableMs = 0
            ninja.y = 0.95 * height - screen.y
            ninja.speedX = 0
            ninja.speedY = 0
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

STATE = '''() => ({offer: continueOffer.visible, score: scoreText.count[version],
    record: scoreText.record[version], reStarts: window.__reStarts,
    inRun: runInProgress, version, gamePaused: menu.gamePaused,
    interstitialPending: interstitialPending, adOpen: adOpen})'''


class ItchPlatformTests(unittest.TestCase):
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

    def open(self, init_script=None):
        context = self.browser.new_context(viewport=VIEWPORT)
        self.addCleanup(context.close)
        if init_script:
            context.add_init_script(init_script)
        page = context.new_page()
        errors = []
        requests = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: requests.append(r.url))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page, errors, requests

    def boot(self, page):
        page.goto(self.url + 'index.html')
        wait_for_boot(page)
        page.wait_for_function(READY)

    def start_run(self, page):
        page.evaluate(INSTRUMENT_RUN)
        switch_mode(page, 'classic')
        page.wait_for_function('window.__ticks > 10')

    def score_and_die(self, page, points):
        page.evaluate('n => { for (let i = 0; i < n; i++) changeScoreText() }', points)
        before = page.evaluate(STATE)
        self.assertEqual(before['score'], points)
        page.evaluate('window.__kill = true')
        # The local adapter never has an interstitial due, so every death is
        # a fast restart (TASK-370, e882a5e): no offer is shown.
        page.wait_for_function('!window.__kill && window.__reStarts > 0'
                               ' && !continueOffer.visible')
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate('window.__offerShown'), 0)
        return before, page.evaluate(STATE)

    def test_a_offline_boot(self):
        page, errors, requests = self.open()
        self.boot(page)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'local')
        self.assertEqual(page.evaluate('typeof window.bridge'), 'undefined')
        page.wait_for_timeout(500)
        foreign = [u for u in requests if not u.startswith(self.origin + '/')]
        if self.save_evidence:
            self.out('requests.json').write_text(json.dumps(
                {'origin': self.origin, 'count': len(requests), 'foreign': foreign,
                 'requests': requests}, indent=1) + '\n')
            page.screenshot(path=str(self.out('screens/menu.png')))
        self.assertTrue(requests)
        # No SDK script or any other off-origin request
        self.assertEqual(foreign, [])
        self.assertEqual(errors, [])

    def test_b_storage_round_trip(self):
        page, errors, _ = self.open()
        self.boot(page)
        self.start_run(page)
        self.score_and_die(page, 4)
        page.evaluate('PROGRESS.flush()')
        page.wait_for_function('localStorage.getItem("%s") !== null' % RECORDS_KEY)
        stored = json.loads(page.evaluate('localStorage.getItem("%s")' % RECORDS_KEY))
        self.assertEqual(stored['classic'], 4)
        page.reload()
        wait_for_boot(page)
        page.wait_for_function(READY)
        self.assertEqual(page.evaluate('scoreText.record.classic'), 4)
        self.assertEqual(errors, [])

    def test_c_blocked_storage(self):
        page, errors, _ = self.open(BLOCK_STORAGE)
        self.boot(page)
        with self.assertRaises(Exception):
            page.evaluate('window.localStorage')
        self.start_run(page)
        _, after = self.score_and_die(page, 3)
        self.assertEqual(after['record'], 3)
        page.evaluate('PROGRESS.flush()')
        # Blocked localStorage: the local adapter keeps progress in its
        # in-memory map, so reads return what was written this session.
        stored = page.evaluate('async () => PLATFORM.storage.getMany(["%s"])' % RECORDS_KEY)
        self.assertEqual(json.loads(stored[RECORDS_KEY])['classic'], 3)
        self.assertEqual(page.evaluate('scoreText.record.classic'), 3)
        self.assertEqual(errors, [])

    def test_d_no_ads_on_restart(self):
        page, _, _ = self.open()
        self.boot(page)
        # Rewarded continues no longer exist (TASK-242, 8519216)
        self.assertEqual(page.evaluate('typeof PLATFORM.isRewardedSupported'), 'undefined')
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialSupported()'))
        self.start_run(page)
        before, after = self.score_and_die(page, max(5, page.evaluate('CONTINUE_MIN_SCORE')))
        if self.save_evidence:
            page.screenshot(path=str(self.out('screens/after-death-score5.png')))
            self.out('death-state.json').write_text(json.dumps(
                {'before': before, 'after': after}, indent=1) + '\n')
        # The fast restart: a new run, no offer, no interstitial or ad
        self.assertEqual(after['reStarts'], 1)
        self.assertFalse(after['offer'])
        self.assertFalse(after['interstitialPending'])
        self.assertFalse(after['adOpen'])
        self.assertEqual([after['inRun'], after['version']], [True, 'classic'])
        self.assertEqual(after['score'], 0)
        self.assertEqual(after['record'], 5)
        page.wait_for_timeout(300)
        self.assertFalse(page.evaluate('continueOffer.visible'))

    def test_e_hidden_tab_pauses(self):
        page, _, _ = self.open()
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


if __name__ == '__main__':
    unittest.main()
