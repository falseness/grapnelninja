"""Exercise platform.js (the Playgama wrapper) against the fake Bridge in Chromium."""
import json
import os
from pathlib import Path
import sys
import unittest

# Also importable as tools/test_playgama_platform.py without PYTHONPATH=tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from playgama_harness import (bridge_calls, bridge_errors, open_game,
                              start_playgama_test)

ROOT = Path(__file__).resolve().parent.parent
HOST = 'tools/fixtures/fake-playgama-platform-host.html'
VIEWPORT = {'width': 1280, 'height': 720}

INIT = '''async () => {
    const t0 = performance.now()
    const environment = await PLATFORM.init()
    return {environment, ms: performance.now() - t0,
            platformId: PLATFORM.platformId, language: PLATFORM.language}
}'''

# Run requestRewarded and keep listening for settleMs after it resolves so
# late ad states show up in the fake's calls.
REWARD = '''async ({settleMs, overrides}) => {
    Object.assign(PLATFORM, overrides || {})
    const t0 = performance.now()
    const result = await PLATFORM.requestRewarded()
    const ms = performance.now() - t0
    await new Promise((r) => setTimeout(r, settleMs))
    return Object.assign({ms}, result)
}'''

INTERSTITIAL = '''async (overrides) => {
    Object.assign(PLATFORM, overrides || {})
    const t0 = performance.now()
    const result = await PLATFORM.showInterstitial()
    return {result, ms: performance.now() - t0}
}'''


class PlaygamaPlatformTests(unittest.TestCase):
    outcomes = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('PLAYGAMA_PLATFORM_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'outcomes.json').write_text(
                json.dumps(cls.outcomes, indent=1, sort_keys=True) + '\n')

    def open(self, block_bridge=False, **kwargs):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, block_bridge=block_bridge,
                                          **kwargs)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        page.wait_for_function('() => typeof PLATFORM === "object"')
        if not block_bridge:
            page.wait_for_function('() => window.bridge && window.__fakeBridge')
        return page

    def init(self, page):
        return page.evaluate(INIT)

    def ready(self, **fake_options):
        page = self.open(fake_options=fake_options)
        self.assertEqual(self.init(page)['environment'], 'playgama')
        return page

    def calls(self, page, name):
        return [c for c in bridge_calls(page) if c['name'] == name]

    def reward(self, page, scenario, settle_ms=200, overrides=None):
        result = page.evaluate(REWARD, {'settleMs': settle_ms,
                                        'overrides': overrides})
        self.outcomes[scenario] = result
        return result

    def warnings(self, page):
        messages = []
        page.on('console', lambda m: m.type == 'warning' and messages.append(m.text))
        return messages

    # --- init -----------------------------------------------------------

    def test_disabled_without_bridge(self):
        page = self.open(block_bridge=True)
        result = self.init(page)
        self.assertEqual(result['environment'], 'disabled')
        self.assertLess(result['ms'], 200)
        self.assertEqual(result['language'], 'en')
        self.assertEqual(page.evaluate('PLATFORM.requestRewarded()'),
                         {'status': 'unavailable', 'reason': 'disabled'})
        self.assertEqual(page.evaluate('PLATFORM.showInterstitial()'), 'skipped')
        self.assertTrue(page.evaluate('PLATFORM.isAudioEnabled()'))

    def test_init_resolve_playgama_once(self):
        page = self.open(fake_options={'platformId': 'mock', 'language': 'ru-RU'})
        page.evaluate('() => Promise.all([PLATFORM.init(), PLATFORM.init()])')
        result = self.init(page)
        self.assertEqual(result['environment'], 'playgama')
        self.assertEqual(result['platformId'], 'mock')
        self.assertEqual(len(self.calls(page, 'initialize')), 1)

    def test_language_iso_639_1(self):
        for raw, expected in (('ru-RU', 'ru'), ('EN', 'en'), ('tr', 'tr'),
                              ('', 'en'), (None, 'en')):
            with self.subTest(raw=raw):
                page = self.open(fake_options={'language': raw})
                self.assertEqual(self.init(page)['language'], expected)

    def test_init_reject_disabled_warns_once(self):
        page = self.open(fake_options={'init': 'reject'})
        warnings = self.warnings(page)
        self.assertEqual(self.init(page)['environment'], 'disabled')
        self.assertEqual(page.evaluate('PLATFORM.init()'), 'disabled')
        self.assertEqual(len([w for w in warnings if 'Playgama' in w]), 1)

    def test_init_timeout_8s_disabled(self):
        page = self.open(fake_options={'init': 'never'})
        warnings = self.warnings(page)
        result = self.init(page)
        self.outcomes['initTimeout'] = result
        self.assertEqual(result['environment'], 'disabled')
        self.assertGreaterEqual(result['ms'], 7900)
        self.assertLess(result['ms'], 8600)
        self.assertEqual(len([w for w in warnings if 'Playgama' in w]), 1)
        # Never touches the Bridge after the timeout
        self.assertEqual(page.evaluate('PLATFORM.requestRewarded()')['reason'],
                         'disabled')

    # --- rewarded -------------------------------------------------------

    def test_rewarded_only_after_rewarded_state(self):
        page = self.ready()
        result = self.reward(page, 'rewarded')
        self.assertEqual(result['status'], 'rewarded')
        show = self.calls(page, 'advertisement.showRewarded')
        self.assertEqual([c['args'] for c in show], [['continue']])
        # Unsubscribed afterwards
        self.assertEqual(len(self.calls(page, 'advertisement.off')), 1)

    def test_rewarded_failed_unavailable(self):
        page = self.ready(rewardedSeq=['loading', 'failed'])
        result = self.reward(page, 'failed')
        self.assertEqual((result['status'], result['reason']),
                         ('unavailable', 'failed'))

    def test_rewarded_closed_without_reward_dismissed(self):
        page = self.ready(rewardedSeq=['loading', 'opened', 'closed'])
        self.assertEqual(self.reward(page, 'dismissed')['status'], 'dismissed')

    def test_rewarded_unsupported(self):
        page = self.ready(rewardedSupported=False)
        result = self.reward(page, 'unsupported')
        self.assertEqual((result['status'], result['reason']),
                         ('unavailable', 'unsupported'))
        self.assertEqual(self.calls(page, 'advertisement.showRewarded'), [])

    def test_rewarded_busy_one_ad_at_a_time(self):
        page = self.ready()
        results = page.evaluate('''() => Promise.all([
            PLATFORM.requestRewarded(), PLATFORM.requestRewarded()])''')
        self.outcomes['busy'] = results
        self.assertEqual([r['status'] for r in results], ['rewarded', 'unavailable'])
        self.assertEqual(results[1]['reason'], 'busy')
        shows = self.calls(page, 'advertisement.showRewarded')
        errors = bridge_errors(page)
        self.outcomes['busyBridge'] = {'showRewarded': len(shows), 'errors': errors}
        self.assertEqual(len(shows), 1)
        self.assertEqual(errors, [])

    def test_rewarded_watchdog_late_result_ignored(self):
        # Opened, then the playing watchdog (lowered) fires before 'rewarded'
        page = self.ready(rewardedSeq=['loading', 'opened',
                                       {'state': 'rewarded', 'delayMs': 400},
                                       'closed'])
        self.assertEqual(page.evaluate('PLATFORM.rewardTimeoutMs'), 15000)
        self.assertEqual(page.evaluate('PLATFORM.rewardPlayingTimeoutMs'), 120000)
        result = self.reward(page, 'watchdog', settle_ms=700, overrides={
            'rewardTimeoutMs': 150, 'rewardPlayingTimeoutMs': 150})
        self.assertEqual((result['status'], result['reason']),
                         ('unavailable', 'timeout'))
        states = [c['name'] for c in bridge_calls(page)]
        self.assertIn('rewarded:rewarded', states)
        self.assertIn('rewarded:closed', states)
        # The late 'rewarded' did not resolve anything twice; the next
        # request (default watchdogs) works once the late ad has closed.
        result = self.reward(page, 'afterWatchdog', overrides={
            'rewardTimeoutMs': 15000, 'rewardPlayingTimeoutMs': 120000})
        self.assertEqual(result['status'], 'rewarded')
        self.assertEqual(len(self.calls(page, 'advertisement.showRewarded')), 2)

    # --- interstitial ---------------------------------------------------

    def test_interstitial_closed(self):
        page = self.ready()
        out = page.evaluate(INTERSTITIAL)
        self.outcomes['interstitialClosed'] = out
        self.assertEqual(out['result'], 'closed')
        show = self.calls(page, 'advertisement.showInterstitial')
        self.assertEqual([c['args'] for c in show], [['game_over']])

    def test_interstitial_failed(self):
        page = self.ready(interstitialSeq=['loading', 'failed'])
        self.assertEqual(page.evaluate(INTERSTITIAL)['result'], 'failed')

    def test_interstitial_skipped(self):
        cases = (
            ('unsupported', {'interstitialSupported': False}, None),
            ('notOpened', {'interstitialSeq': ['loading']}, None),
            ('notOpened3s', {'interstitialSeq': ['loading']}, 'default'),
        )
        for name, options, timing in cases:
            with self.subTest(name=name):
                page = self.ready(**options)
                overrides = None if timing else {'interstitialOpenTimeoutMs': 200}
                out = page.evaluate(INTERSTITIAL, overrides)
                self.outcomes['interstitial_' + name] = out
                self.assertEqual(out['result'], 'skipped')
                if timing:
                    self.assertGreaterEqual(out['ms'], 2900)
                    self.assertLess(out['ms'], 3500)
        page = self.open(block_bridge=True)
        self.init(page)
        self.assertEqual(page.evaluate(INTERSTITIAL)['result'], 'skipped')

    # --- messages -------------------------------------------------------

    def test_game_ready_once(self):
        page = self.ready()
        page.evaluate('''async () => { await PLATFORM.gameReady();
                                       await PLATFORM.gameReady() }''')
        sent = [c['args'] for c in self.calls(page, 'platform.sendMessage')]
        self.assertEqual(sent, [['game_ready']])

    def test_send_message_safe(self):
        page = self.ready()
        page.evaluate('''async () => {
            bridge.platform.sendMessage = () => Promise.reject(new Error('x'))
            await PLATFORM.sendMessage('level_started', {world: 'classic'})
            bridge.platform.sendMessage = () => { throw new Error('y') }
            await PLATFORM.sendMessage('level_failed')
        }''')
        disabled = self.open(block_bridge=True)
        self.init(disabled)
        self.assertIsNone(disabled.evaluate('PLATFORM.sendMessage("game_ready")'))

    # --- storage --------------------------------------------------------

    def test_get_many_single_call(self):
        page = self.ready()
        page.evaluate('''() => bridge.storage.set(['a', 'b', 'c'],
                                                  ['12', '{"x":1}', 'en'])''')
        before = len(self.calls(page, 'storage.get'))
        got = page.evaluate('PLATFORM.storage.getMany(["a", "b", "c", "d"])')
        self.assertEqual(got, {'a': '12', 'b': '{"x":1}', 'c': 'en', 'd': None})
        gets = self.calls(page, 'storage.get')[before:]
        self.assertEqual([c['args'] for c in gets], [[['a', 'b', 'c', 'd']]])

    def test_set_many_single_call_strings(self):
        page = self.ready()
        page.evaluate('PLATFORM.storage.setMany({a: 5, b: "x", c: true})')
        sets = self.calls(page, 'storage.set')
        self.assertEqual([c['args'] for c in sets],
                         [[['a', 'b', 'c'], ['5', 'x', 'true']]])
        self.assertEqual(page.evaluate('localStorage.length'), 0)

    def test_storage_fallback_when_disabled(self):
        page = self.open(block_bridge=True)
        self.init(page)
        page.evaluate('PLATFORM.storage.setMany({a: 5, b: "x"})')
        self.assertEqual(page.evaluate('localStorage.getItem("a")'), '5')
        self.assertEqual(page.evaluate('PLATFORM.storage.getMany(["a", "b", "z"])'),
                         {'a': '5', 'b': 'x', 'z': None})

    # --- host events ----------------------------------------------------

    def test_on_pause(self):
        page = self.ready()
        page.evaluate('''() => { window.__pause = []
                                 PLATFORM.onPause((v) => __pause.push(v)) }''')
        page.evaluate('__fakeBridge.fire("PAUSE_STATE_CHANGED", true)')
        page.evaluate('__fakeBridge.fire("PAUSE_STATE_CHANGED", false)')
        self.assertEqual(page.evaluate('__pause'), [True, False])

    def test_on_audio_and_is_audio_enabled(self):
        page = self.ready(isAudioEnabled=False)
        self.assertFalse(page.evaluate('PLATFORM.isAudioEnabled()'))
        page.evaluate('''() => { window.__audio = []
                                 PLATFORM.onAudio((v) => __audio.push(v)) }''')
        page.evaluate('__fakeBridge.fire("AUDIO_STATE_CHANGED", true)')
        self.assertEqual(page.evaluate('__audio'), [True])
        self.assertTrue(page.evaluate('PLATFORM.isAudioEnabled()'))

    def test_on_ad_state_any_fullscreen_ad(self):
        page = self.ready()
        page.evaluate('''() => { window.__ad = []
                                 PLATFORM.onAdState((s) => __ad.push(s)) }''')
        self.assertEqual(page.evaluate(INTERSTITIAL)['result'], 'closed')
        self.assertEqual(page.evaluate('__ad'), ['opened', 'closed'])
        self.assertEqual(self.reward(page, 'adState')['status'], 'rewarded')
        self.assertEqual(page.evaluate('__ad'),
                         ['opened', 'closed', 'opened', 'closed'])
        # A failed load never opened: nothing reported
        page.evaluate('__fakeBridge.script("rewarded", ["loading", "failed"])')
        self.reward(page, 'adStateFailed')
        self.assertEqual(len(page.evaluate('__ad')), 4)


if __name__ == '__main__':
    unittest.main()
