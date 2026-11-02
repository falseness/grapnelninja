"""TASK-794: Playgama rewarded ads through bridge.advertisement.

Boots the real index.html with the Playgama backend (a route adds the
platform/backends/playgama.js tag after local.js, as test_platform_backends
does) and, unless a case asks for none, an init script that installs a fake
window.bridge (FAKE_BRIDGE). Its advertisement keeps a real listener list
(on/off), records showRewarded placements and lets the test emit
REWARDED_STATE_CHANGED states. Checks: 'rewarded' then 'closed' gives
'rewarded'; 'closed' alone gives 'closed'; 'failed' gives 'failed'; a throwing
showRewarded gives 'failed'; the listener count is back to its starting value
after each ad; isRewardedSupported false gives false and the go-back dialog has
no ad marker (true: a marker, and Go back goes through the fake SDK); without
window.bridge the backend keeps the stub results (false / 'unavailable').

PLAYGAMA_REWARDED_EVIDENCE_DIR=DIR writes cases.json (one row per case).

    python3 -m unittest discover -s tools -p test_playgama_rewarded.py -v
"""
import json
import os
from pathlib import Path
import unittest

import test_go_back_dialog as base

ROOT = Path(__file__).resolve().parent.parent
LOCAL_TAG = '<script src = "platform/backends/local.js"></script>'
PLAYGAMA_TAG = LOCAL_TAG + '\n        <script src = "platform/backends/playgama.js"></script>'

FAKE_BRIDGE = '''(() => {
    const listeners = {}
    const FAKE = window.__fakeBridge = {calls: [], throwOnShow: false,
        count(event) { return (listeners[event] || []).length },
        emit(event, state) { (listeners[event] || []).slice().forEach(fn => fn(state)) }}
    // TASK-859: the ported backend uses the bridge only after initialize()
    window.bridge = {
        initialize() { return Promise.resolve() },
        platform: {id: 'fake', language: 'en', isAudioEnabled: true, on() {}, sendMessage() { return Promise.resolve() }},
        EVENT_NAME: {PAUSE_STATE_CHANGED: 'pause_state_changed', AUDIO_STATE_CHANGED: 'audio_state_changed',
            INTERSTITIAL_STATE_CHANGED: 'interstitial_state_changed',
            REWARDED_STATE_CHANGED: 'rewarded_state_changed'},
        advertisement: {
            isRewardedSupported: true,
            on(event, fn) { (listeners[event] = listeners[event] || []).push(fn) },
            off(event, fn) { listeners[event] = (listeners[event] || []).filter(f => f !== fn) },
            showRewarded(placement) {
                FAKE.calls.push(placement)
                if (FAKE.throwOnShow) throw new Error('fake showRewarded error')
            }
        }
    }
})()'''

# Start PLATFORM.showRewarded, emit states, return the result and listener counts
SHOW = '''async ([states, placement]) => {
    const F = window.__fakeBridge, E = bridge.EVENT_NAME.REWARDED_STATE_CHANGED
    const before = F.count(E)
    let result = 'pending'
    const done = PLATFORM.showRewarded(placement).then(r => result = r)
    await Promise.resolve()
    const during = F.count(E)
    const seen = []
    for (const s of states) { F.emit(E, s); await Promise.resolve(); seen.push(result) }
    await done
    // A state after it settled changes nothing
    F.emit(E, 'rewarded'); F.emit(E, 'closed')
    return {result, seen, before, during, after: F.count(E), calls: F.calls.slice()}
}'''

MARKER = '''() => { LAYOUT_PROBE.boxes = []; redrawOverlays()
    const boxes = LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes = null
    return boxes.filter(b => b.kind === 'adMarker').map(b => b.name) }'''


class PlaygamaBrowser:
    """Browser whose contexts serve index.html with the Playgama backend and,
    with bridge=True, the fake window.bridge."""
    def __init__(self, browser):
        self._browser = browser
        self.bridge = True

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)

        def rewrite(route):
            response = route.fetch()
            body = response.text()
            assert body.count(LOCAL_TAG) == 1
            route.fulfill(response=response, body=body.replace(LOCAL_TAG, PLAYGAMA_TAG))
        context.route('**/', rewrite)
        context.route('**/index.html', rewrite)
        if self.bridge:
            context.add_init_script(FAKE_BRIDGE)
        return context


class PlaygamaRewardedTests(unittest.TestCase):
    open_page = base.GoBackDialogTests.open
    catch = base.GoBackDialogTests.catch
    checkpoint = base.GoBackDialogTests.checkpoint
    long_fall = base.GoBackDialogTests.long_fall
    button = base.GoBackDialogTests.button

    @classmethod
    def setUpClass(cls):
        base.GoBackDialogTests.setUpClass.__func__(cls)
        cls.browser = PlaygamaBrowser(cls.browser)
        cls.out = os.environ.get('PLAYGAMA_REWARDED_EVIDENCE_DIR')
        cls.cases = []

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            Path(cls.out, 'cases.json').write_text(json.dumps(cls.cases, indent=1, sort_keys=True) + '\n')

    def open(self, bridge=True):
        self.browser.bridge = bridge
        page = self.open_page()
        self.assertEqual(page.evaluate('[PLATFORM_BACKEND.platformId, PLATFORM.getPlatformId()]'),
                         ['playgama', 'playgama'])
        self.assertEqual(page.evaluate('typeof window.bridge'), 'object' if bridge else 'undefined')
        return page

    def show(self, case, states, expected, throw=False):
        page = self.open()
        page.evaluate('t => window.__fakeBridge.throwOnShow = t', throw)
        row = page.evaluate(SHOW, [states, 'go_back'])
        self.assertEqual(row['result'], expected)
        self.assertEqual(row['calls'], ['go_back'])
        self.assertEqual(row['during'], row['before'] + 1 if not throw else row['before'])
        self.assertEqual(row['after'], row['before'])
        if not throw:
            # Settles only on the final state
            self.assertEqual(row['seen'][:-1], ['pending'] * (len(states) - 1))
        row.update(case=case, states=states, expected=expected, throwOnShow=throw,
                   listenersRestored=row['after'] == row['before'], pass_=True)
        self.cases.append(row)
        return row

    def test_01_rewarded_then_closed(self):
        self.show('rewarded_then_closed', ['loading', 'opened', 'rewarded', 'closed'], 'rewarded')

    def test_02_closed_only(self):
        self.show('closed_only', ['loading', 'opened', 'closed'], 'closed')

    def test_03_failed(self):
        self.show('failed', ['loading', 'failed'], 'failed')

    def test_04_show_throws(self):
        self.show('show_throws', [], 'failed', throw=True)

    def test_05_two_ads_in_a_row(self):
        page = self.open()
        first = page.evaluate(SHOW, [['opened', 'rewarded', 'closed'], 'go_back'])
        second = page.evaluate(SHOW, [['opened', 'closed'], 'go_back'])
        self.assertEqual([first['result'], second['result']], ['rewarded', 'closed'])
        self.assertEqual([first['before'], first['after'], second['before'], second['after']],
                         [first['before']] * 4)
        self.cases.append({'case': 'two_in_a_row', 'results': [first['result'], second['result']],
                           'listeners': [first['before'], first['after'], second['after']], 'pass_': True})

    def test_06_unsupported_no_marker(self):
        page = self.open()
        page.evaluate('bridge.advertisement.isRewardedSupported = false')
        self.assertIs(page.evaluate('PLATFORM.isRewardedSupported()'), False)
        self.checkpoint(page)
        self.long_fall(page)
        self.assertTrue(page.evaluate('CLIMB_UI.goingBack'))
        marker = page.evaluate(MARKER)
        self.assertEqual(marker, [])
        p = self.button(page, 0)
        page.mouse.click(p['x'], p['y'])
        self.assertEqual(page.evaluate('window.__fakeBridge.calls'), [])
        self.assertFalse(page.evaluate('CLIMB_UI.goingBack'))
        self.cases.append({'case': 'unsupported', 'isRewardedSupported': False, 'marker': marker,
                           'showRewarded_calls': [], 'pass_': True})

    def test_07_supported_marker_and_go_back(self):
        page = self.open()
        self.assertIs(page.evaluate('PLATFORM.isRewardedSupported()'), True)
        cp = self.checkpoint(page)
        self.long_fall(page)
        marker = page.evaluate(MARKER)
        self.assertEqual(len(marker), 1)
        p = self.button(page, 0)
        page.mouse.click(p['x'], p['y'])
        E = 'bridge.EVENT_NAME.REWARDED_STATE_CHANGED'
        waiting = page.evaluate('() => [CLIMB_UI.goBackAdPending, window.__fakeBridge.count(%s)]' % E)
        # TASK-859: +1 permanent listener (the backend's ad-state subscription)
        self.assertEqual(waiting, [True, 2])
        page.evaluate('''async () => { const F = window.__fakeBridge, E = %s
            F.emit(E, 'opened'); F.emit(E, 'rewarded'); F.emit(E, 'closed')
            for (let i = 0; i < 5; i++) await Promise.resolve()
            await new Promise(r => setTimeout(r, 0)) }''' % E)
        after = page.evaluate(base.STATE)
        after.update(page.evaluate('''() => ({pending: CLIMB_UI.goBackAdPending,
            listeners: window.__fakeBridge.count(%s), calls: window.__fakeBridge.calls.slice()})''' % E))
        self.assertEqual(after['calls'], ['go_back'])
        self.assertFalse(after['pending'] or after['dialog'] or after['paused'])
        self.assertEqual(after['listeners'], 1)
        self.assertEqual(after['goBacks'], 1)
        self.assertTrue(after['grapnel']['grappled'])
        self.assertEqual(after['grapnel']['anchor'], [cp['anchorX'], cp['anchorY']])
        self.cases.append({'case': 'supported_go_back', 'marker': marker, 'listenersWhileShowing': waiting[1],
                           'listenersAfter': after['listeners'], 'calls': after['calls'], 'goBacks': after['goBacks'],
                           'anchor': after['grapnel']['anchor'], 'checkpoint': [cp['anchorX'], cp['anchorY']],
                           'went_back': True, 'pass_': True})

    def test_08_no_bridge_stub(self):
        page = self.open(bridge=False)
        row = page.evaluate('''async () => ({supported: PLATFORM.isRewardedSupported(),
            result: await PLATFORM.showRewarded('go_back'),
            backendSupported: PLATFORM_BACKEND.isRewardedSupported(),
            backendResult: await PLATFORM_BACKEND.showRewarded('go_back')})''')
        self.assertEqual(row, {'supported': False, 'result': 'unavailable',
                               'backendSupported': False, 'backendResult': 'unavailable'})
        self.cases.append({'case': 'no_bridge', **row, 'pass_': True})


if __name__ == '__main__':
    unittest.main()
