"""Exercise platform.js (the GamePix wrapper) against the fake GamePix SDK in Chromium."""
import json
import os
from pathlib import Path
import sys
import unittest

# Also importable as tools/test_gamepix_platform.py without PYTHONPATH=tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamepix_harness import (fire, open_game, sdk_calls, sdk_errors,
                             start_gamepix_test)

ROOT = Path(__file__).resolve().parent.parent
HOST = 'tools/fixtures/fake-gamepix-platform-host.html'
VIEWPORT = {'width': 1280, 'height': 720}

# Start requestRewarded and return a handle; window.__rewards[i] collects
# its callbacks with timestamps.
START_REWARD = '''() => {
    window.__rewards = window.__rewards || []
    const events = []
    const t0 = performance.now()
    const log = (name) => (arg) =>
        events.push({name, arg: arg || null, ms: performance.now() - t0})
    window.__rewards.push(events)
    PLATFORM.requestRewarded({adStarted: log('adStarted'),
                              adFinished: log('adFinished'),
                              adError: log('adError')})
    return window.__rewards.length - 1
}'''

TERMINAL = ('adFinished', 'adError')


class GamePixPlatformTests(unittest.TestCase):
    outcomes = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_gamepix_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('GAMEPIX_PLATFORM_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'outcomes.json').write_text(
                json.dumps(cls.outcomes, indent=1, sort_keys=True) + '\n')

    def open(self, block_sdk=False, loaded=True, **kwargs):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, block_sdk=block_sdk,
                                          **kwargs)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('() => typeof PLATFORM === "object"')
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'pending')
        page.evaluate('PLATFORM.init()')
        if loaded:
            page.evaluate('PLATFORM.loaded()')
        return page

    def names(self, page):
        return [c['name'] for c in sdk_calls(page)]

    def events(self, page, index):
        return page.evaluate('(i) => window.__rewards[i]', index)

    def reward(self, page, scenario, expected, code=None, settleMs=300):
        """Run one request, wait for its terminal callback, then settleMs."""
        index = page.evaluate(START_REWARD)
        page.wait_for_function(
            '(i) => window.__rewards[i].some((e) => e.name !== "adStarted")',
            arg=index, timeout=5000)
        page.wait_for_timeout(settleMs)
        events = self.events(page, index)
        terminals = [e for e in events if e['name'] in TERMINAL]
        self.outcomes[scenario] = {
            'terminal': terminals[0]['name'],
            'count': len(terminals),
            'ms': round(terminals[0]['ms']),
            'code': (terminals[0]['arg'] or {}).get('code'),
            'message': (terminals[0]['arg'] or {}).get('message'),
        }
        self.assertEqual([e['name'] for e in terminals], [expected], events)
        if code is not None:
            self.assertEqual(terminals[0]['arg']['code'], code)
            self.assertTrue(terminals[0]['arg']['message'])
        return events

    # --- init / loading / loaded -----------------------------------------

    def test_init_gamepix_memoised(self):
        page = self.open(loaded=False)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'gamepix')
        self.assertTrue(page.evaluate('PLATFORM.init() === PLATFORM.init()'))
        self.assertEqual(page.evaluate('PLATFORM.init()'), 'gamepix')

    def test_loaded_once(self):
        page = self.open(loaded=False)
        self.assertTrue(page.evaluate(
            '() => PLATFORM.loaded() === PLATFORM.loaded()'))
        page.evaluate('() => Promise.all([PLATFORM.loaded(), PLATFORM.loaded()])')
        self.assertEqual(self.names(page).count('loaded'), 1)
        self.assertEqual(sdk_errors(page), [])

    def test_loaded_resolves_when_sdk_throws_or_rejects(self):
        for body in ('throw new Error("boom")',
                     'return Promise.reject(new Error("boom"))'):
            with self.subTest(body=body):
                page = self.open(loaded=False)
                page.evaluate(f'() => {{ GamePix.loaded = () => {{ {body} }} }}')
                self.assertEqual(page.evaluate(
                    '() => PLATFORM.loaded().then(() => "resolved")'), 'resolved')

    def test_loading_clamp(self):
        page = self.open(loaded=False)
        for pct in (-5, 0, 42.4, 42.6, 100, 250, 'abc', None):
            page.evaluate('(p) => PLATFORM.loading(p)', pct)
        args = [c['args'][0] for c in sdk_calls(page) if c['name'] == 'loading']
        self.assertEqual(args, [0, 0, 42, 43, 100, 100, 0, 0])

    # --- rewarded -------------------------------------------------------

    def test_reward_not_loaded(self):
        page = self.open(loaded=False)
        events = self.reward(page, 'not-loaded', 'adError', code='not-loaded')
        self.assertNotIn('adStarted', [e['name'] for e in events])
        self.assertNotIn('rewardAd', self.names(page))
        self.assertEqual(sdk_errors(page), [])

    def test_reward_success(self):
        page = self.open(fake_options={'reward': 'success'})
        events = self.reward(page, 'success', 'adFinished')
        self.assertEqual(events[0]['name'], 'adStarted')
        names = self.names(page)
        self.assertLess(names.index('loaded'), names.index('rewardAd'))
        self.assertEqual(names.count('rewardAd'), 1)

    def test_reward_unavailable(self):
        page = self.open()  # fake default 'fail' == localhost {success:false}
        self.reward(page, 'unavailable', 'adError', code='unavailable')

    def test_reward_unavailable_keeps_sdk_message(self):
        page = self.open(fake_options={'reward': 'never'})
        page.evaluate('''() => { GamePix.rewardAd = () =>
            Promise.resolve({success: false, message: "no fill"}) }''')
        self.reward(page, 'unavailableMessage', 'adError', code='unavailable')
        self.assertEqual(self.outcomes['unavailableMessage']['message'], 'no fill')

    def test_reward_truthy_non_true_is_not_success(self):
        page = self.open()
        page.evaluate('''() => { GamePix.rewardAd = () =>
            Promise.resolve({success: 1}) }''')
        self.reward(page, 'truthyNotTrue', 'adError', code='unavailable')

    def test_reward_rejected(self):
        page = self.open()
        page.evaluate('''() => { GamePix.rewardAd = () =>
            Promise.reject(new Error("nope")) }''')
        self.reward(page, 'rejected', 'adError', code='rejected')

    def test_reward_exception(self):
        page = self.open(fake_options={'reward': 'throw'})
        self.reward(page, 'exception', 'adError', code='exception')
        # A sync throw does not leave the platform stuck in 'busy'
        page.evaluate('() => { __fakeGamePix.reward = "success" }')
        self.reward(page, 'afterException', 'adFinished')

    def test_reward_busy_no_double_call(self):
        page = self.open(fake_options={'reward': 'success',
                                       'rewardDelayMs': 400})
        first = page.evaluate(START_REWARD)
        self.reward(page, 'busy', 'adError', code='busy', settleMs=0)
        page.wait_for_function(
            '(i) => window.__rewards[i].some((e) => e.name === "adFinished")',
            arg=first, timeout=5000)
        page.wait_for_timeout(200)
        first_events = [e['name'] for e in self.events(page, first)]
        self.assertEqual(first_events, ['adStarted', 'adFinished'])
        calls = sdk_calls(page)
        errors = sdk_errors(page)
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'no-double-reward.txt').write_text(
                f'rewardAd calls: {[c["name"] for c in calls].count("rewardAd")}\n'
                f'__fakeGamePix.calls: {json.dumps([c["name"] for c in calls])}\n'
                f'__fakeGamePix.errors: {json.dumps(errors)}\n'
                f'first request events: {json.dumps(first_events)}\n')
        self.assertEqual([c['name'] for c in calls].count('rewardAd'), 1)
        self.assertEqual(errors, [])
        # Once settled, a new request goes through
        self.reward(page, 'afterBusy', 'adFinished')

    def test_reward_watchdog(self):
        page = self.open(fake_options={'reward': 'never'})
        self.assertEqual(page.evaluate('PLATFORM.rewardPlayingTimeoutMs'), 120000)
        self.assertIsNone(page.evaluate('PLATFORM.rewardTimeoutMs'))
        page.evaluate('PLATFORM.rewardPlayingTimeoutMs = 200')
        events = self.reward(page, 'watchdog', 'adError', code='timeout')
        ms = [e['ms'] for e in events if e['name'] == 'adError'][0]
        self.assertGreaterEqual(ms, 190)

    def test_reward_late_result_ignored(self):
        page = self.open(fake_options={'reward': 'success',
                                       'rewardDelayMs': 500})
        page.evaluate('PLATFORM.rewardPlayingTimeoutMs = 100')
        self.reward(page, 'lateAfterWatchdog', 'adError', code='timeout',
                    settleMs=800)
        # The SDK did resolve {success:true} later, and it was ignored
        self.assertEqual(self.names(page).count('rewardAd'), 1)

    def test_reward_disabled(self):
        page = self.open(block_sdk=True)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'disabled')
        self.reward(page, 'disabled', 'adError', code='disabled')

    # --- storage / score / events -----------------------------------------

    def test_storage_gamepix_string_coercion(self):
        page = self.open()
        result = page.evaluate('''() => {
            PLATFORM.storage.setItem("best", 5)
            PLATFORM.storage.setItem(7, true)
            const r = [PLATFORM.storage.getItem("best"), PLATFORM.storage.getItem(7)]
            PLATFORM.storage.removeItem("best")
            r.push(PLATFORM.storage.getItem("best"))
            return r
        }''')
        self.assertEqual(result, ['5', 'true', None])
        names = self.names(page)
        self.assertIn('localStorage.setItem', names)
        self.assertIn('localStorage.removeItem', names)
        self.assertEqual(sdk_errors(page), [])

    def test_storage_fallback_when_disabled(self):
        page = self.open(block_sdk=True)
        result = page.evaluate('''() => {
            PLATFORM.storage.setItem("best", 9)
            const r = [PLATFORM.storage.getItem("best"), localStorage.getItem("best")]
            PLATFORM.storage.removeItem("best")
            r.push(localStorage.getItem("best"))
            return r
        }''')
        self.assertEqual(result, ['9', '9', None])

    def test_storage_never_throws(self):
        page = self.open()
        result = page.evaluate('''() => {
            const boom = () => { throw new Error("quota") }
            GamePix.localStorage.getItem = GamePix.localStorage.setItem =
                GamePix.localStorage.removeItem = boom
            PLATFORM.storage.setItem("a", "b")
            PLATFORM.storage.removeItem("a")
            return PLATFORM.storage.getItem("a")
        }''')
        self.assertIsNone(result)

    def test_update_score_filtering(self):
        page = self.open()
        for value in (3, 0, -1, 2.5, 'x', None, float('inf'), 12):
            page.evaluate('(v) => PLATFORM.updateScore(v)', value)
        page.evaluate('PLATFORM.updateScore(NaN); PLATFORM.updateScore(Infinity)')
        args = [c['args'][0] for c in sdk_calls(page) if c['name'] == 'updateScore']
        self.assertEqual(args, [3, 0, 12])
        self.assertEqual(sdk_errors(page), [])

    def test_happy_moment(self):
        page = self.open()
        page.evaluate('PLATFORM.happyMoment()')
        self.assertEqual(self.names(page).count('happyMoment'), 1)

    def test_on_pause_resume(self):
        page = self.open()
        page.evaluate('''() => {
            window.__seen = []
            PLATFORM.onPause(() => __seen.push("pause"))
            PLATFORM.onResume(() => { __seen.push("resume"); throw new Error("x") })
            PLATFORM.onPause("not a function")
        }''')
        self.assertEqual(page.evaluate('typeof GamePix.on.pause'), 'function')
        fire(page, 'pause')
        fire(page, 'resume')
        self.assertEqual(page.evaluate('__seen'), ['pause', 'resume'])

    def test_disabled_no_ops(self):
        page = self.open(block_sdk=True)
        result = page.evaluate('''() => {
            PLATFORM.loading(50)
            PLATFORM.updateScore(3)
            PLATFORM.happyMoment()
            PLATFORM.onPause(() => {})
            PLATFORM.onResume(() => {})
            return PLATFORM.loaded().then(() => [PLATFORM.environment,
                                                 PLATFORM.init() === PLATFORM.init()])
        }''')
        self.assertEqual(result, ['disabled', True])
        self.assertFalse(page.evaluate('"GamePix" in window'))


if __name__ == '__main__':
    unittest.main()
