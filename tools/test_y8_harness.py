"""Exercise the fake Y8 SDK through y8_harness in Chromium."""
import json
import os
from pathlib import Path
import sys
import unittest

# Also importable as tools/test_y8_harness.py without PYTHONPATH=tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from y8_harness import open_game, sdk_calls, start_y8_test

ROOT = Path(__file__).resolve().parent.parent
HOST = 'tools/fixtures/fake-y8-host.html'
VIEWPORT = {'width': 1280, 'height': 720}
AD_CALLBACKS = ['beforeAd', 'adViewed', 'adDismissed', 'afterAd']

# Callback sequence the page sees for each rewardOutcome.
EXPECTED = {
    'viewed': ['beforeReward', 'beforeAd', 'adViewed', 'afterAd',
               'adBreakDone:viewed', 'promise:resolved'],
    'dismissed': ['beforeReward', 'beforeAd', 'adDismissed', 'afterAd',
                  'adBreakDone:dismissed', 'promise:resolved'],
    'noAdPreloaded': ['adBreakDone:noAdPreloaded', 'promise:resolved'],
    'frequencyCapped': ['adBreakDone:frequencyCapped', 'promise:resolved'],
    'notReady': ['adBreakDone:notReady', 'promise:resolved'],
    'reject': ['promise:rejected'],
    'silent': ['promise:resolved'],
}

# Run showAd with every callback logging into a list; beforeReward calls
# showAdFn unless told not to. Waits for adBreakDone (or 500 ms).
SHOW_AD = '''async (callShowAdFn) => {
    const seq = []
    let promise = 'pending'
    const log = (name) => (info) => seq.push(
        info && info.breakStatus ? name + ':' + info.breakStatus : name)
    const done = new Promise((resolve) => {
        y8.sdk().showAd({
            type: 'reward', name: 'continue',
            beforeReward: (showAdFn) => {
                seq.push('beforeReward')
                if (callShowAdFn) showAdFn()
            },
            beforeAd: log('beforeAd'), afterAd: log('afterAd'),
            adViewed: log('adViewed'), adDismissed: log('adDismissed'),
            adBreakDone: (info) => { log('adBreakDone')(info); resolve() },
        }).then(() => { promise = 'resolved' }, () => { promise = 'rejected' })
        setTimeout(resolve, 500)
    })
    await done
    await new Promise((r) => setTimeout(r, 50))
    seq.push('promise:' + promise)
    return seq
}'''


class Y8HarnessTests(unittest.TestCase):
    sequences = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_y8_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('Y8_HARNESS_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'sequences.json').write_text(
                json.dumps(cls.sequences, indent=1, sort_keys=True) + '\n')

    def open(self, **kwargs):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, **kwargs)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('() => window.y8 && window.__y8Fake')
        return page, errors

    def ready_count(self, page):
        return page.evaluate('window.__readyEvents.length')

    def names(self, page):
        return [call['name'] for call in sdk_calls(page)]

    def test_ready_fires(self):
        page, _ = self.open()
        page.wait_for_function('() => window.__readyEvents.length > 0')
        page.wait_for_timeout(100)
        self.assertEqual(self.ready_count(page), 1)
        self.assertEqual(page.evaluate('Object.keys(window.y8).sort()'),
                         ['emitReadyEvent', 'sdk'])
        self.assertTrue(page.evaluate('y8.sdk() === y8.sdk()'))

    def test_ready_never(self):
        page, _ = self.open(fake_options={'readyNever': True})
        page.wait_for_timeout(200)
        page.evaluate('y8.emitReadyEvent()')
        page.wait_for_timeout(50)
        self.assertEqual(self.ready_count(page), 0)
        self.assertNotIn('y8sdk.ready', self.names(page))

    def test_emit_ready_event_redispatches(self):
        page, _ = self.open()
        page.wait_for_function('() => window.__readyEvents.length > 0')
        late = page.evaluate('''() => new Promise((resolve) => {
            window.addEventListener('y8sdk.ready', () => resolve('late'), {once: true})
            y8.emitReadyEvent()
        })''')
        self.assertEqual(late, 'late')
        self.assertEqual(self.ready_count(page), 2)

    def test_init_resolves_and_calls_on_ready(self):
        page, _ = self.open()
        result = page.evaluate('''async () => {
            let ready = false
            const value = await y8.sdk().init({appId: 'x'}, {onReady: () => { ready = true }})
            await new Promise((r) => setTimeout(r, 50))
            return {value: value === undefined ? 'undefined' : value, ready}
        }''')
        self.assertEqual(result, {'value': 'undefined', 'ready': True})

    def test_init_reject_and_hang(self):
        page, _ = self.open(fake_options={'initReject': True})
        self.assertEqual(page.evaluate(
            'y8.sdk().init({}, {}).then(() => "resolved", () => "rejected")'),
            'rejected')
        page, _ = self.open(fake_options={'initHang': True})
        self.assertEqual(page.evaluate('''() => Promise.race([
            y8.sdk().init({}, {}).then(() => 'settled', () => 'settled'),
            new Promise((r) => setTimeout(() => r('pending'), 300))])'''),
            'pending')

    def test_reward_outcome_sequences(self):
        for outcome, expected in EXPECTED.items():
            with self.subTest(outcome=outcome):
                page, _ = self.open(fake_options={'rewardOutcome': outcome})
                seq = page.evaluate(SHOW_AD, True)
                self.sequences[outcome] = seq
                self.assertEqual(seq, expected)

    def test_viewed_waits_for_ad_duration(self):
        page, _ = self.open(fake_options={'adDurationMs': 300})
        page.evaluate(SHOW_AD, True)
        calls = {c['name']: c['t'] for c in sdk_calls(page)}
        self.assertGreaterEqual(calls['adViewed'] - calls['beforeAd'], 290)

    def test_show_ad_fn_not_called_means_no_ad_callbacks(self):
        for outcome in ('viewed', 'dismissed'):
            with self.subTest(outcome=outcome):
                page, _ = self.open(fake_options={'rewardOutcome': outcome})
                seq = page.evaluate(SHOW_AD, False)
                self.assertEqual(seq, ['beforeReward', 'promise:resolved'])
                names = self.names(page)
                for name in AD_CALLBACKS + ['adBreakDone', 'showAdFn']:
                    self.assertNotIn(name, names)

    def test_calls_recorded(self):
        page, _ = self.open()
        page.wait_for_function('() => window.__readyEvents.length > 0')
        page.evaluate('''async () => {
            const sdk = y8.sdk()
            await sdk.init({appId: 'a'}, {onReady: () => {}})
            sdk.onAuth(() => {})
            sdk.trackCustomEvent('x', 1)
        }''')
        page.evaluate(SHOW_AD, True)
        calls = sdk_calls(page)
        names = [c['name'] for c in calls]
        self.assertEqual(names, [
            'y8sdk.ready', 'init', 'onAuth', 'trackCustomEvent', 'onReady',
            'showAd', 'beforeReward', 'showAdFn', 'beforeAd', 'adViewed',
            'afterAd', 'adBreakDone'])
        self.assertEqual(calls[1]['args'], [['appId'], ['onReady']])
        self.assertEqual(calls[2]['args'], ['function'])
        self.assertEqual(calls[3]['args'], ['x', 1])
        self.assertEqual(calls[5]['args'][0][:2], ['type', 'name'])
        self.assertEqual(calls[-1]['args'], [['breakStatus']])
        times = [c['t'] for c in calls]
        self.assertEqual(times, sorted(times))

    def test_blocked_sdk(self):
        page, errors = self.open_blocked()
        self.assertFalse(page.evaluate('"y8" in window'))
        self.assertEqual(sdk_calls(page), [])
        self.assertTrue(errors['blocked_sdk'])

    def open_blocked(self):
        context, page, errors = open_game(self.browser, self.url + HOST,
                                          VIEWPORT, block_sdk=True)
        self.addCleanup(context.close)
        page.wait_for_load_state('load')
        page.wait_for_timeout(100)
        self.assertEqual((errors['console'], errors['page']), ([], []))
        return page, errors


if __name__ == '__main__':
    unittest.main()
