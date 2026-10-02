"""Exercise the fake GamePix SDK through gamepix_harness in Chromium."""
from pathlib import Path
import sys
import unittest

# Also importable as tools/test_gamepix_harness.py without PYTHONPATH=tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamepix_harness import (fire, open_game, sdk_calls, sdk_errors,
                             start_gamepix_test)

ROOT = Path(__file__).resolve().parent.parent
HOST = 'tools/fixtures/fake-gamepix-host.html'
PLATFORM_HOST = 'tools/fixtures/fake-gamepix-platform-host.html'
VIEWPORT = {'width': 1280, 'height': 720}

# Resolve rewardAd() to its result, 'threw', or 'pending' after 300 ms.
REWARD = '''async () => {
    let promise
    try { promise = GamePix.rewardAd() } catch (e) { return 'threw' }
    return Promise.race([promise,
        new Promise((r) => setTimeout(() => r('pending'), 300))])
}'''


class GamePixHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_gamepix_test(ROOT, cls.addClassCleanup)

    def open(self, host=HOST, **kwargs):
        context, page, errors = open_game(self.browser, self.url + host,
                                          VIEWPORT, **kwargs)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('() => window.GamePix && window.__fakeGamePix')
        return page

    def open_loaded(self, **kwargs):
        page = self.open(**kwargs)
        self.assertEqual(page.evaluate('GamePix.loaded()'), {})
        return page

    def names(self, page):
        return [call['name'] for call in sdk_calls(page)]

    def test_defined_synchronously_at_parse(self):
        page = self.open()
        self.assertEqual(page.evaluate('window.__gamePixAtParse'), 'object')
        self.assertEqual(page.evaluate('Object.keys(GamePix).sort()'), [
            'happyMoment', 'lang', 'loaded', 'loading', 'localStorage', 'on',
            'rewardAd', 'updateLevel', 'updateScore'])
        self.assertEqual(page.evaluate('GamePix.on'), {
            'pause': False, 'resume': False, 'soundOn': False,
            'soundOff': False})

    def test_loading_and_loaded(self):
        page = self.open()
        self.assertIsNone(page.evaluate('GamePix.loading(50)'))
        self.assertEqual(page.evaluate('GamePix.loaded()'), {})
        self.assertEqual(sdk_errors(page), [])
        calls = sdk_calls(page)
        self.assertEqual([(c['name'], c['args']) for c in calls],
                         [('loading', [50]), ('loaded', [])])

    def test_loaded_twice_logs_error(self):
        page = self.open_loaded()
        self.assertEqual(page.evaluate('GamePix.loaded()'), {})
        self.assertEqual(sdk_errors(page), ['LOADED_ALREADY_CALLED'])

    def test_reward_before_loaded(self):
        page = self.open(fake_options={'reward': 'success'})
        self.assertEqual(page.evaluate(REWARD), {'success': False})
        self.assertEqual(sdk_errors(page), ['GAMEPIX_LOADED_NOT_CALLED'])

    def test_reward_success(self):
        page = self.open_loaded(fake_options={'reward': 'success'})
        self.assertEqual(page.evaluate(REWARD), {'success': True})
        self.assertEqual(sdk_errors(page), [])

    def test_reward_fail(self):
        page = self.open_loaded(fake_options={'reward': 'fail'})
        self.assertEqual(page.evaluate(REWARD), {'success': False})
        self.assertEqual(sdk_errors(page), [])

    def test_reward_fail_is_default_like_localhost(self):
        page = self.open_loaded()
        self.assertEqual(page.evaluate(REWARD), {'success': False})

    def test_reward_never(self):
        page = self.open_loaded(fake_options={'reward': 'never'})
        self.assertEqual(page.evaluate(REWARD), 'pending')

    def test_reward_throw(self):
        page = self.open_loaded(fake_options={'reward': 'throw'})
        self.assertEqual(page.evaluate(REWARD), 'threw')
        self.assertIn('rewardAd', self.names(page))

    def test_reward_delay(self):
        page = self.open_loaded(fake_options={'reward': 'success',
                                              'rewardDelayMs': 300})
        elapsed = page.evaluate('''async () => {
            const t = performance.now()
            await GamePix.rewardAd()
            return performance.now() - t
        }''')
        self.assertGreaterEqual(elapsed, 290)

    def test_reward_superseded(self):
        page = self.open_loaded(fake_options={'reward': 'success',
                                              'rewardDelayMs': 100})
        results = page.evaluate(
            'Promise.all([GamePix.rewardAd(), GamePix.rewardAd()])')
        self.assertEqual(results, [
            {'success': False,
             'message': 'Reward ad superseded by a new request'},
            {'success': True}])
        self.assertEqual(sdk_errors(page), ['REWARD_AD_CALLED_TWICE'])

    def test_reward_after_settled_is_not_superseded(self):
        page = self.open_loaded(fake_options={'reward': 'success'})
        page.evaluate(REWARD)
        self.assertEqual(page.evaluate(REWARD), {'success': True})
        self.assertEqual(sdk_errors(page), [])

    def test_storage_round_trip(self):
        page = self.open_loaded()
        page.evaluate('GamePix.localStorage.setItem("record", "5")')
        self.assertEqual(page.evaluate('localStorage.getItem("record")'), '5')
        self.assertEqual(
            page.evaluate('GamePix.localStorage.getItem("record")'), '5')
        page.evaluate('GamePix.localStorage.removeItem("record")')
        self.assertIsNone(
            page.evaluate('GamePix.localStorage.getItem("record")'))
        self.assertEqual(sdk_errors(page), [])

    def test_storage_non_string_rejected(self):
        page = self.open_loaded()
        page.evaluate('GamePix.localStorage.setItem("record", 5)')
        self.assertIsNone(page.evaluate('localStorage.getItem("record")'))
        page.evaluate('GamePix.localStorage.setItem(7, "x")')
        self.assertIsNone(page.evaluate('GamePix.localStorage.getItem(7)'))
        page.evaluate('GamePix.localStorage.removeItem(null)')
        self.assertEqual(sdk_errors(page),
                         ['KEY_OR_VALUE_FOR_LOCALSTORAGE_NOT_A_STRING'] * 4)

    def test_score_level_numbers_only(self):
        page = self.open_loaded()
        page.evaluate('GamePix.updateScore(12); GamePix.updateLevel(3)')
        self.assertEqual(sdk_errors(page), [])
        page.evaluate('GamePix.updateScore("12"); GamePix.updateLevel(NaN)')
        self.assertEqual(sdk_errors(page),
                         ['SCORE_NOT_A_NUMBER', 'LEVEL_NOT_A_NUMBER'])

    def test_happy_moment_and_lang(self):
        page = self.open_loaded(fake_options={'lang': 'de'})
        self.assertEqual(page.evaluate('GamePix.lang()'), 'de')
        page.evaluate('GamePix.happyMoment()')
        self.assertEqual(self.names(page)[-2:], ['lang', 'happyMoment'])
        page = self.open()
        self.assertEqual(page.evaluate('GamePix.lang()'), 'en')

    def test_fire_pause_and_others(self):
        page = self.open_loaded()
        fire(page, 'pause')  # unset slot: no-op
        page.evaluate('''() => {
            window.__fired = []
            for (const name of ['pause', 'resume', 'soundOn', 'soundOff'])
                GamePix.on[name] = () => window.__fired.push(name)
        }''')
        for name in ('pause', 'resume', 'soundOn', 'soundOff'):
            fire(page, name)
        self.assertEqual(page.evaluate('window.__fired'),
                         ['pause', 'resume', 'soundOn', 'soundOff'])
        fires = [c['args'] for c in sdk_calls(page) if c['name'] == 'fire']
        self.assertEqual(fires, [['pause'], ['pause'], ['resume'],
                                 ['soundOn'], ['soundOff']])

    def test_calls_recorded_with_times(self):
        page = self.open()
        page.evaluate('''async () => {
            GamePix.loading(100)
            await GamePix.loaded()
            GamePix.updateScore(3)
            await GamePix.rewardAd()
        }''')
        calls = sdk_calls(page)
        self.assertEqual([c['name'] for c in calls],
                         ['loading', 'loaded', 'updateScore', 'rewardAd'])
        times = [c['t'] for c in calls]
        self.assertEqual(times, sorted(times))

    def test_blocked_sdk(self):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, block_sdk=True)
        self.addCleanup(context.close)
        page.wait_for_load_state('load')
        self.assertFalse(page.evaluate('"GamePix" in window'))
        self.assertEqual(sdk_calls(page), [])
        self.assertTrue(errors['blocked_sdk'])
        self.assertEqual((errors['console'], errors['page']), ([], []))

    def test_platform_host_loads_with_fake(self):
        page = self.open(host=PLATFORM_HOST)
        page.wait_for_load_state('load')
        self.assertEqual(page.evaluate('typeof PLATFORM'), 'object')


if __name__ == '__main__':
    unittest.main()
