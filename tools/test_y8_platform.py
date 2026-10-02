"""Exercise platform.js (the Y8 wrapper) against the fake Y8 SDK in Chromium."""
import json
import os
from pathlib import Path
import sys
import unittest

# Also importable as tools/test_y8_platform.py without PYTHONPATH=tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from y8_harness import open_game, sdk_calls, start_y8_test

ROOT = Path(__file__).resolve().parent.parent
HOST = 'tools/fixtures/fake-y8-platform-host.html'
VIEWPORT = {'width': 1280, 'height': 720}

# Record the exact init() arguments, then run PLATFORM.init() and time it.
INIT = '''async (wrap) => {
    window.__initArgs = null
    if (wrap) {
        const sdk = y8.sdk()
        const init = sdk.init
        sdk.init = function () {
            window.__initArgs = JSON.parse(JSON.stringify(Array.from(arguments)))
            return init.apply(this, arguments)
        }
    }
    const t0 = performance.now()
    const environment = await PLATFORM.init()
    return {environment, ms: performance.now() - t0, args: window.__initArgs}
}'''

# Run requestRewarded, wait for the first terminal callback (or 2 s), then
# keep listening for settleMs so that late extra callbacks are counted too.
REWARD = '''async ({rewardTimeoutMs, settleMs}) => {
    if (rewardTimeoutMs) PLATFORM.rewardTimeoutMs = rewardTimeoutMs
    const events = []
    const t0 = performance.now()
    let first
    const terminal = new Promise((resolve) => { first = resolve })
    const log = (name) => (arg) => {
        events.push({name, arg: arg || null, ms: performance.now() - t0})
        if (name !== 'adStarted') first()
    }
    PLATFORM.requestRewarded({adStarted: log('adStarted'),
                              adFinished: log('adFinished'),
                              adError: log('adError')})
    await Promise.race([terminal, new Promise((r) => setTimeout(r, 2000))])
    await new Promise((r) => setTimeout(r, settleMs))
    return events
}'''

TERMINAL = ('adFinished', 'adError')


class Y8PlatformTests(unittest.TestCase):
    outcomes = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_y8_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('Y8_PLATFORM_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'outcomes.json').write_text(
                json.dumps(cls.outcomes, indent=1, sort_keys=True) + '\n')

    def open(self, wait_sdk=True, **kwargs):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, **kwargs)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('() => typeof PLATFORM === "object"')
        if wait_sdk:
            page.wait_for_function('() => window.y8 && window.__y8Fake')
        return page, errors

    def init(self, page, wrap=True):
        return page.evaluate(INIT, wrap)

    def reward(self, page, scenario, expected, code=None, rewardTimeoutMs=None,
               settleMs=300):
        events = page.evaluate(REWARD, {'rewardTimeoutMs': rewardTimeoutMs,
                                        'settleMs': settleMs})
        terminals = [e for e in events if e['name'] in TERMINAL]
        self.outcomes[scenario] = {
            'terminal': terminals[0]['name'] if terminals else None,
            'count': len(terminals),
            'ms': round(terminals[0]['ms']) if terminals else None,
            'code': (terminals[0]['arg'] or {}).get('code') if terminals else None,
        }
        self.assertEqual([e['name'] for e in terminals], [expected], events)
        if code is not None:
            self.assertEqual(terminals[0]['arg']['code'], code)
            self.assertTrue(terminals[0]['arg']['message'])
        return events

    def show_ad_calls(self, page):
        return [c for c in sdk_calls(page) if c['name'] == 'showAd']

    # --- init -----------------------------------------------------------

    def test_init_y8_with_exact_ids(self):
        page, _ = self.open()
        result = self.init(page)
        self.assertEqual(result['environment'], 'y8')
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'y8')
        self.assertEqual(result['args'], [
            {'appId': '6abfc17d100b7c96fc2d684e', 'autoLogin': False},
            {'gameId': '285775', 'preloadAdBreaks': 'auto', 'sound': 'off'}])
        names = [c['name'] for c in sdk_calls(page)]
        self.assertEqual(names.count('init'), 1)
        # Race fix: the listener is added after load, so emitReadyEvent is used
        self.assertIn('emitReadyEvent', names)

    def test_init_twice_calls_sdk_once(self):
        page, _ = self.open()
        page.evaluate('() => Promise.all([PLATFORM.init(), PLATFORM.init()])')
        self.assertEqual([c['name'] for c in sdk_calls(page)].count('init'), 1)

    def test_blocked_sdk_disabled_within_3_5_s(self):
        page, errors = self.open(wait_sdk=False, block_sdk=True)
        result = self.init(page, wrap=False)
        self.assertEqual(result['environment'], 'disabled')
        self.assertLess(result['ms'], 3500)
        self.assertFalse(page.evaluate('!!window.y8'))

    def test_ready_never_disabled(self):
        page, _ = self.open(fake_options={'readyNever': True})
        result = self.init(page)
        self.assertEqual(result['environment'], 'disabled')
        self.assertLess(result['ms'], 3500)
        self.assertIsNone(result['args'])

    def test_init_reject_disabled(self):
        page, _ = self.open(fake_options={'initReject': True})
        result = self.init(page)
        self.assertEqual(result['environment'], 'disabled')
        self.assertIsNotNone(result['args'])

    def test_init_hang_disabled(self):
        page, _ = self.open(fake_options={'initHang': True})
        result = self.init(page)
        self.assertEqual(result['environment'], 'disabled')
        self.assertGreaterEqual(result['ms'], 2900)
        self.assertLess(result['ms'], 3500)

    def test_init_throw_disabled(self):
        page, _ = self.open()
        page.evaluate('() => { y8.sdk().init = () => { throw new Error("boom") } }')
        self.assertEqual(self.init(page, wrap=False)['environment'], 'disabled')

    # --- rewarded -------------------------------------------------------

    def test_reward_viewed(self):
        page, _ = self.open()
        self.init(page)
        events = self.reward(page, 'viewed', 'adFinished')
        self.assertEqual(events[0]['name'], 'adStarted')
        call = self.show_ad_calls(page)[0]
        self.assertEqual(sorted(call['args'][0]), sorted(
            ['type', 'name', 'beforeReward', 'beforeAd', 'adViewed',
             'adDismissed', 'adBreakDone']))

    def test_reward_dismissed(self):
        page, _ = self.open(fake_options={'rewardOutcome': 'dismissed'})
        self.init(page)
        self.reward(page, 'dismissed', 'adError', code='dismissed')

    def test_reward_no_ad_statuses(self):
        for status in ('noAdPreloaded', 'frequencyCapped', 'notReady'):
            with self.subTest(status=status):
                page, _ = self.open(fake_options={'rewardOutcome': status})
                self.init(page)
                events = self.reward(page, status, 'adError', code=status)
                self.assertNotIn('adStarted', [e['name'] for e in events])

    def test_reward_reject(self):
        page, _ = self.open(fake_options={'rewardOutcome': 'reject'})
        self.init(page)
        self.reward(page, 'reject', 'adError', code='rejected')

    def test_reward_sync_throw(self):
        page, _ = self.open()
        self.init(page)
        page.evaluate('() => { y8.sdk().showAd = () => { throw new Error("boom") } }')
        self.reward(page, 'throw', 'adError', code='exception')

    def test_reward_silent_watchdog(self):
        page, _ = self.open(fake_options={'rewardOutcome': 'silent'})
        self.init(page)
        self.assertEqual(page.evaluate('PLATFORM.rewardTimeoutMs'), 15000)
        events = self.reward(page, 'silent', 'adError', code='timeout',
                             rewardTimeoutMs=200)
        ms = [e['ms'] for e in events if e['name'] == 'adError'][0]
        self.assertGreaterEqual(ms, 190)

    def test_reward_late_callbacks_ignored(self):
        # The watchdog fires mid-ad; the later adViewed/adBreakDone are ignored.
        page, _ = self.open(fake_options={'adDurationMs': 400})
        self.init(page)
        self.reward(page, 'lateAfterWatchdog', 'adError', code='timeout',
                    rewardTimeoutMs=100, settleMs=700)
        self.assertTrue(page.evaluate(
            '() => __y8Fake.calls.some((c) => c.name === "adViewed")'))

    def test_reward_disabled_skips_show_ad(self):
        page, _ = self.open(fake_options={'readyNever': True})
        self.assertEqual(self.init(page)['environment'], 'disabled')
        self.reward(page, 'disabled', 'adError', code='disabled')
        self.assertEqual(self.show_ad_calls(page), [])

    def test_reward_blocked_sdk_disabled(self):
        page, _ = self.open(wait_sdk=False, block_sdk=True)
        self.init(page, wrap=False)
        self.reward(page, 'blockedSdk', 'adError', code='disabled')


if __name__ == '__main__':
    unittest.main()
