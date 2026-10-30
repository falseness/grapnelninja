"""TASK-795: GamePix and Y8 rewarded ads, itch.io free go-back.

Boots the real index.html with one platform backend (a route adds its
platform/backends/<id>.js tag after local.js, as test_playgama_rewarded does)
and, unless a case asks for none, an init script with a fake SDK:

- GamePix (FAKE_GAMEPIX): window.GamePix.ads.reward() answers by mode:
  {success: true} -> 'rewarded', {success: false} -> 'closed', a throw or a
  rejected promise -> 'failed'.
- Y8 (FAKE_Y8): window.y8.sdk().showAd(options) plays the documented reward
  break by mode: viewed (beforeReward, beforeAd, adViewed, afterAd,
  adBreakDone viewed) -> 'rewarded'; dismissed (adDismissed, breakStatus
  dismissed) -> 'closed'; noAdPreloaded (adBreakDone only), a throw or a
  rejected promise -> 'failed'.

Without the SDK both keep the stub results (false / 'unavailable'). With the
SDK the go-back dialog has the ad marker and Go back goes through it. The
itch.io backend (no ad SDK) shows the dialog without a marker and goes back
for free.

REWARDED_BACKENDS_EVIDENCE_DIR=DIR writes cases.json (one row per case).

    python3 -m unittest discover -s tools -p test_rewarded_backends.py -v
"""
import json
import os
from pathlib import Path
import unittest

import test_go_back_dialog as base

LOCAL_TAG = '<script src = "platform/backends/local.js"></script>'

FAKE_GAMEPIX = '''(() => {
    const FAKE = window.__fakeSdk = {calls: [], mode: 'success'}
    window.GamePix = {ads: {reward() {
        FAKE.calls.push({mode: FAKE.mode})
        if (FAKE.mode === 'throw') throw new Error('fake reward error')
        if (FAKE.mode === 'reject') return Promise.reject(new Error('fake reward rejected'))
        return new Promise(r => setTimeout(() => r(FAKE.mode === 'success' ? {success: true}
            : {success: false, message: 'fake ' + FAKE.mode}), 20))
    }}}
})()'''

FAKE_Y8 = '''(() => {
    const FAKE = window.__fakeSdk = {calls: [], mode: 'viewed'}
    const later = fn => new Promise(r => setTimeout(() => { fn(); r() }, 10))
    const SDK = {showAd(o) {
        const call = {mode: FAKE.mode, type: o.type, name: o.name, callbacks: []}
        FAKE.calls.push(call)
        const fire = (name, ...args) => { call.callbacks.push(name); if (o[name]) o[name](...args) }
        if (FAKE.mode === 'throw') throw new Error('fake showAd error')
        if (FAKE.mode === 'reject') return Promise.reject(new Error('fake showAd rejected'))
        if (FAKE.mode === 'noAdPreloaded')
            return later(() => fire('adBreakDone', {breakStatus: 'noAdPreloaded'}))
        return later(() => fire('beforeReward', () => {
            fire('beforeAd')
            if (FAKE.mode === 'viewed') fire('adViewed'); else fire('adDismissed')
            fire('afterAd')
            fire('adBreakDone', {breakStatus: FAKE.mode})
        }))
    }}
    window.y8 = {sdk: () => SDK}
})()'''

FAKES = {'gamepix': FAKE_GAMEPIX, 'y8': FAKE_Y8, 'itch': None}

# PLATFORM.showRewarded with the fake in `mode`; result + the fake's calls
SHOW = '''async (mode) => {
    window.__fakeSdk.mode = mode
    const supported = PLATFORM.isRewardedSupported()
    const result = await PLATFORM.showRewarded('go_back')
    return {supported, result, calls: window.__fakeSdk.calls.slice()}
}'''

MARKER = '''() => { LAYOUT_PROBE.boxes = []; redrawOverlays()
    const boxes = LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes = null
    return boxes.filter(b => b.kind === 'adMarker').map(b => b.name) }'''


class BackendBrowser:
    """Browser whose contexts serve index.html with backend `platform` and,
    with sdk=True, that platform's fake SDK."""
    def __init__(self, browser):
        self._browser = browser
        self.platform = 'local'
        self.sdk = True

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)
        tag = LOCAL_TAG + '\n        <script src = "platform/backends/%s.js"></script>' % self.platform

        def rewrite(route):
            response = route.fetch()
            body = response.text()
            assert body.count(LOCAL_TAG) == 1
            route.fulfill(response=response, body=body.replace(LOCAL_TAG, tag))
        context.route('**/', rewrite)
        context.route('**/index.html', rewrite)
        if self.sdk and FAKES[self.platform]:
            context.add_init_script(FAKES[self.platform])
        return context


class RewardedBackendsTests(unittest.TestCase):
    open_page = base.GoBackDialogTests.open
    catch = base.GoBackDialogTests.catch
    checkpoint = base.GoBackDialogTests.checkpoint
    long_fall = base.GoBackDialogTests.long_fall
    button = base.GoBackDialogTests.button

    @classmethod
    def setUpClass(cls):
        base.GoBackDialogTests.setUpClass.__func__(cls)
        cls.browser = BackendBrowser(cls.browser)
        cls.out = os.environ.get('REWARDED_BACKENDS_EVIDENCE_DIR')
        cls.cases = []

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            cases = sorted(cls.cases, key=lambda c: (c['platform'], c['case']))
            Path(cls.out, 'cases.json').write_text(json.dumps(cases, indent=1, sort_keys=True) + '\n')

    def open(self, platform, sdk=True):
        self.browser.platform, self.browser.sdk = platform, sdk
        page = self.open_page()
        self.assertEqual(page.evaluate('[PLATFORM_BACKEND.platformId, PLATFORM.getPlatformId()]'),
                         [platform, platform])
        return page

    def show(self, platform, mode, expected):
        page = self.open(platform)
        row = page.evaluate(SHOW, mode)
        self.assertIs(row['supported'], True)
        self.assertEqual(row['result'], expected)
        self.assertEqual(len(row['calls']), 1)
        if platform == 'y8':
            self.assertEqual([row['calls'][0]['type'], row['calls'][0]['name']], ['reward', 'go_back'])
        self.cases.append({'platform': platform, 'case': mode, 'expected': expected, **row, 'pass_': True})

    def no_sdk(self, platform):
        page = self.open(platform, sdk=False)
        row = page.evaluate('''async () => ({supported: PLATFORM.isRewardedSupported(),
            result: await PLATFORM.showRewarded('go_back'),
            backendSupported: PLATFORM_BACKEND.isRewardedSupported(),
            backendResult: await PLATFORM_BACKEND.showRewarded('go_back')})''')
        self.assertEqual(row, {'supported': False, 'result': 'unavailable',
                               'backendSupported': False, 'backendResult': 'unavailable'})
        self.cases.append({'platform': platform, 'case': 'sdk_missing', 'expected': 'unavailable', **row,
                           'pass_': True})

    def go_back(self, platform):
        """The dialog after a long fall; Go back through the platform."""
        page = self.open(platform)
        cp = self.checkpoint(page)
        self.long_fall(page)
        self.assertTrue(page.evaluate('CLIMB_UI.goingBack'))
        marker = page.evaluate(MARKER)
        p = self.button(page, 0)
        page.mouse.click(p['x'], p['y'])
        page.wait_for_function('() => !CLIMB_UI.goBackAdPending && !CLIMB_UI.goingBack', timeout=10000)
        after = page.evaluate(base.STATE)
        self.assertFalse(after['dialog'] or after['paused'])
        self.assertEqual(after['goBacks'], 1)
        self.assertTrue(after['grapnel']['grappled'])
        self.assertEqual(after['grapnel']['anchor'], [cp['anchorX'], cp['anchorY']])
        calls = page.evaluate('window.__fakeSdk ? window.__fakeSdk.calls.length : 0')
        row = {'platform': platform, 'case': 'dialog_go_back', 'marker': marker, 'sdkCalls': calls,
               'supported': page.evaluate('PLATFORM.isRewardedSupported()'), 'goBacks': after['goBacks'],
               'anchor': after['grapnel']['anchor'], 'checkpoint': [cp['anchorX'], cp['anchorY']],
               'went_back': True, 'pass_': True}
        self.cases.append(row)
        return row

    def test_01_gamepix_rewarded(self):
        self.show('gamepix', 'success', 'rewarded')

    def test_02_gamepix_closed(self):
        self.show('gamepix', 'cancel', 'closed')

    def test_03_gamepix_failed_throw(self):
        self.show('gamepix', 'throw', 'failed')

    def test_04_gamepix_failed_reject(self):
        self.show('gamepix', 'reject', 'failed')

    def test_05_gamepix_sdk_missing(self):
        self.no_sdk('gamepix')

    def test_06_y8_rewarded(self):
        self.show('y8', 'viewed', 'rewarded')

    def test_07_y8_closed(self):
        self.show('y8', 'dismissed', 'closed')

    def test_08_y8_failed_no_ad(self):
        self.show('y8', 'noAdPreloaded', 'failed')

    def test_09_y8_failed_throw(self):
        self.show('y8', 'throw', 'failed')

    def test_10_y8_failed_reject(self):
        self.show('y8', 'reject', 'failed')

    def test_11_y8_sdk_missing(self):
        self.no_sdk('y8')

    def test_12_gamepix_dialog_ad(self):
        row = self.go_back('gamepix')
        self.assertEqual(len(row['marker']), 1)
        self.assertEqual([row['supported'], row['sdkCalls']], [True, 1])

    def test_13_y8_dialog_ad(self):
        row = self.go_back('y8')
        self.assertEqual(len(row['marker']), 1)
        self.assertEqual([row['supported'], row['sdkCalls']], [True, 1])

    def test_14_itch_free(self):
        row = self.go_back('itch')
        self.assertEqual(row['marker'], [])
        self.assertEqual([row['supported'], row['sdkCalls']], [False, 0])


if __name__ == '__main__':
    unittest.main()
