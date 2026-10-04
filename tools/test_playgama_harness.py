"""Exercise the fake Playgama Bridge through playgama_harness in Chromium."""
import json
import os
from pathlib import Path
import sys
import unittest

# Also importable as tools/test_playgama_harness.py without PYTHONPATH=tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from playgama_harness import (bridge_calls, bridge_errors, open_game,
                              start_playgama_test)

ROOT = Path(__file__).resolve().parent.parent
HOST = 'tools/fixtures/fake-playgama-host.html'
VIEWPORT = {'width': 1280, 'height': 720}

# Initialize, then run one ad show and collect its states until a terminal
# state (or timeoutMs). Returns {states, rewarded}.
SHOW_AD = '''async ([kind, timeoutMs]) => {
    await bridge.initialize()
    const ad = bridge.advertisement
    const event = kind === 'rewarded'
        ? bridge.EVENT_NAME.REWARDED_STATE_CHANGED
        : bridge.EVENT_NAME.INTERSTITIAL_STATE_CHANGED
    const states = []
    let rewarded = false
    await new Promise((resolve) => {
        const onState = (state) => {
            states.push(state)
            if (state === 'rewarded') rewarded = true
            if (state === 'closed' || state === 'failed') {
                ad.off(event, onState)
                resolve()
            }
        }
        ad.on(event, onState)
        if (kind === 'rewarded') ad.showRewarded('continue')
        else ad.showInterstitial('game_over')
        setTimeout(resolve, timeoutMs)
    })
    return {states, rewarded}
}'''

INIT_RACE = '''() => Promise.race([
    bridge.initialize().then(() => 'resolved', (e) => 'rejected: ' + e.message),
    new Promise((r) => setTimeout(() => r('pending'), 300))])'''


class PlaygamaHarnessTests(unittest.TestCase):
    sequences = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('PLAYGAMA_HARNESS_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'sequences.json').write_text(
                json.dumps(cls.sequences, indent=1, sort_keys=True) + '\n')

    def open(self, expect_errors=False, **kwargs):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, **kwargs)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('() => window.bridge && window.__fakeBridge')
        if not expect_errors:
            self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        return page

    def show(self, page, kind, timeout_ms=1000):
        return page.evaluate(SHOW_AD, [kind, timeout_ms])

    def test_init_resolve(self):
        page = self.open()
        self.assertFalse(page.evaluate('bridge.isInitialized'))
        self.assertEqual(page.evaluate(INIT_RACE), 'resolved')
        self.assertEqual(page.evaluate('''() => ({
            id: bridge.platform.id, language: bridge.platform.language,
            audio: bridge.platform.isAudioEnabled,
            init: bridge.isInitialized})'''),
            {'id': 'mock', 'language': 'en', 'audio': True, 'init': True})
        self.assertTrue(page.evaluate(
            'bridge.platform.sendMessage("game_ready") instanceof Promise'))
        names = [c['name'] for c in bridge_calls(page)]
        self.assertEqual(names, ['initialize', 'platform.sendMessage'])
        self.assertEqual(bridge_calls(page)[1]['args'], ['game_ready'])

    def test_init_options_language_audio(self):
        page = self.open(fake_options={'language': 'ru', 'isAudioEnabled': False})
        page.evaluate('bridge.initialize()')
        self.assertEqual(page.evaluate(
            '[bridge.platform.language, bridge.platform.isAudioEnabled]'),
            ['ru', False])

    def test_init_reject(self):
        page = self.open(fake_options={'init': 'reject'})
        self.assertEqual(page.evaluate(INIT_RACE),
                         'rejected: fake initialize rejected')
        self.assertFalse(page.evaluate('bridge.isInitialized'))

    def test_init_never(self):
        page = self.open(fake_options={'init': 'never'})
        self.assertEqual(page.evaluate(INIT_RACE), 'pending')
        self.assertFalse(page.evaluate('bridge.isInitialized'))

    def test_call_before_init_is_error(self):
        page = self.open(expect_errors=True)
        page.evaluate('''() => {
            bridge.platform.language
            bridge.storage.get(['best']).catch(() => {})
            bridge.advertisement.showInterstitial('game_over')
        }''')
        names = [e['name'] for e in bridge_errors(page)]
        self.assertEqual(names, ['platform.language', 'storage.get',
                                 'advertisement.showInterstitial'])
        for e in bridge_errors(page):
            self.assertIn('before bridge.initialize() resolved', e['message'])

    def test_rewarded_success(self):
        page = self.open()
        result = self.show(page, 'rewarded')
        self.sequences['rewarded:success'] = result
        self.assertEqual(result, {'states': ['loading', 'opened', 'rewarded',
                                             'closed'], 'rewarded': True})
        self.assertEqual(page.evaluate('bridge.advertisement.rewardedState'),
                         'closed')

    def test_rewarded_failed(self):
        page = self.open(fake_options={'rewardedSeq': ['loading', 'failed']})
        result = self.show(page, 'rewarded')
        self.sequences['rewarded:failed'] = result
        self.assertEqual(result, {'states': ['loading', 'failed'],
                                  'rewarded': False})

    def test_rewarded_closed_without_reward(self):
        page = self.open()
        page.evaluate('''__fakeBridge.script('rewarded',
            ['loading', 'opened', 'closed'])''')
        result = self.show(page, 'rewarded')
        self.sequences['rewarded:closed'] = result
        self.assertEqual(result, {'states': ['loading', 'opened', 'closed'],
                                  'rewarded': False})

    def test_rewarded_never_ends(self):
        page = self.open(fake_options={'rewardedSeq': ['loading', 'opened']})
        result = self.show(page, 'rewarded', 400)
        self.sequences['rewarded:never'] = result
        self.assertEqual(result, {'states': ['loading', 'opened'],
                                  'rewarded': False})
        self.assertEqual(page.evaluate('bridge.advertisement.rewardedState'),
                         'opened')

    def test_per_state_delays(self):
        page = self.open(fake_options={'rewardedSeq': [
            {'state': 'loading', 'delayMs': 0},
            {'state': 'opened', 'delayMs': 10},
            {'state': 'rewarded', 'delayMs': 300},
            {'state': 'closed', 'delayMs': 10}]})
        self.show(page, 'rewarded')
        t = {c['name']: c['t'] for c in bridge_calls(page)}
        # The states are timed from showRewarded (cumulative delays); a timer
        # only fires late, so measure from the call, not from the 'opened' timer
        self.assertGreaterEqual(t['rewarded:rewarded'] - t['advertisement.showRewarded'], 309)
        self.assertGreaterEqual(t['rewarded:closed'] - t['rewarded:rewarded'], 0)

    def test_double_show_rewarded_is_error(self):
        page = self.open(expect_errors=True)
        page.evaluate('''async () => {
            await bridge.initialize()
            bridge.advertisement.showRewarded('continue')
            bridge.advertisement.showRewarded('continue')
        }''')
        errors = bridge_errors(page)
        self.assertEqual([e['name'] for e in errors], ['advertisement.showRewarded'])
        self.assertIn('in progress', errors[0]['message'])

    def test_interstitial_states_and_minimum_delay(self):
        page = self.open()
        self.assertEqual(page.evaluate(
            'bridge.initialize().then(() => '
            'bridge.advertisement.minimumDelayBetweenInterstitial)'), 60)
        first = self.show(page, 'interstitial')
        second = self.show(page, 'interstitial')
        self.sequences['interstitial:first'] = first
        self.sequences['interstitial:within-delay'] = second
        self.assertEqual(first['states'], ['loading', 'opened', 'closed'])
        self.assertEqual(second['states'], ['failed'])
        page.evaluate('bridge.advertisement.setMinimumDelayBetweenInterstitial(0)')
        third = self.show(page, 'interstitial')
        self.assertEqual(third['states'], ['loading', 'opened', 'closed'])
        page.evaluate('''__fakeBridge.script('interstitial', ['loading', 'failed'])''')
        self.assertEqual(self.show(page, 'interstitial')['states'],
                         ['loading', 'failed'])

    def test_storage_round_trip_across_reload(self):
        page = self.open()
        page.evaluate('''async () => {
            await bridge.initialize()
            await bridge.storage.set(['best', 'lang', 'obj'],
                                     ['1234', 'ru', {a: 1}])
        }''')
        page.reload()
        page.wait_for_function('() => window.bridge')
        self.assertEqual(page.evaluate('''async () => {
            await bridge.initialize()
            return bridge.storage.get(['best', 'lang', 'obj', 'missing'])
        }'''), [1234, 'ru', {'a': 1}, None])
        self.assertEqual(page.evaluate('''async () => {
            await bridge.storage.delete(['lang'])
            return bridge.storage.get(['lang'])
        }'''), [None])
        self.assertEqual(page.evaluate('localStorage.length'), 0)

    def test_bad_storage_args_are_errors(self):
        page = self.open(expect_errors=True)
        results = page.evaluate('''async () => {
            await bridge.initialize()
            const s = bridge.storage
            const settle = (p) => p.then(() => 'resolved', () => 'rejected')
            return [await settle(s.get('best')),
                    await settle(s.set('best', 1)),
                    await settle(s.set(['a', 'b'], [1])),
                    await settle(s.set(['a'], [1]))]
        }''')
        self.assertEqual(results, ['rejected', 'rejected', 'rejected', 'resolved'])
        self.assertEqual([e['name'] for e in bridge_errors(page)],
                         ['storage.get', 'storage.set', 'storage.set'])

    def test_fire_pause_and_audio(self):
        page = self.open()
        seen = page.evaluate('''async () => {
            await bridge.initialize()
            const seen = []
            const E = bridge.EVENT_NAME
            bridge.platform.on(E.PAUSE_STATE_CHANGED, (v) => seen.push(['pause', v]))
            bridge.platform.on(E.AUDIO_STATE_CHANGED, (v) => seen.push(['audio', v]))
            __fakeBridge.fire(E.PAUSE_STATE_CHANGED, true)
            __fakeBridge.fire('AUDIO_STATE_CHANGED', false)
            seen.push(['isAudioEnabled', bridge.platform.isAudioEnabled])
            __fakeBridge.fire(E.AUDIO_STATE_CHANGED, true)
            __fakeBridge.fire(E.PAUSE_STATE_CHANGED, false)
            return seen
        }''')
        self.assertEqual(seen, [['pause', True], ['audio', False],
                                ['isAudioEnabled', False], ['audio', True],
                                ['pause', False]])

    def test_stub_config_served_when_missing(self):
        page = self.open()
        config = page.evaluate(
            'fetch("./playgama-bridge-config.json").then((r) => r.json())')
        self.assertIn('advertisement', config)

    def test_blocked_bridge(self):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, block_bridge=True)
        self.addCleanup(context.close)
        page.wait_for_load_state('load')
        self.assertFalse(page.evaluate('"bridge" in window'))
        self.assertEqual(bridge_calls(page), [])
        self.assertTrue(errors['blocked_bridge'])
        self.assertEqual((errors['console'], errors['page']), ([], []))


if __name__ == '__main__':
    unittest.main()
