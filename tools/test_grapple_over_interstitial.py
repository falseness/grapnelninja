"""TASK-875: Grapple Over shows interstitials at its natural pauses.

Grapple Over has no death, so the game over interstitial never plays there.
Playgama requirement 2.1.2 / Bridge required step 7: it now calls
PLATFORM.showInterstitial('pause') when the player pauses by input (P key or
the pause button; never on blur, a hidden tab, a host pause or rotation) and
PLATFORM.showInterstitial('summit') when the summit screen opens. The backend
decides whether one is due; while it plays the run stays paused and the pause
menu ignores input, usable again once the ad is closed, failed or skipped.

Boots the built playgama zip (INTERSTITIAL_ZIP_DIR/playgama/grapple-over-playgama.zip,
as tools/build_release.py writes it; else built from HEAD into a temp dir)
offline: its SDK URL serves game_harness.LOCAL_BRIDGE plus FAKE_ADS, an
advertisement whose showInterstitial records placements and lets the test
emit INTERSTITIAL_STATE_CHANGED. No Playgama URL is ever loaded.
Scenarios, one fresh page each: pause_p (closed), summit (closed),
pause_p_failed, pause_p_no_bridge, pause_blur. INTERSTITIAL_EVIDENCE=FILE
writes one compact JSON object (rows per scenario).

    INTERSTITIAL_ZIP_DIR=artifacts/TASK-875/build python3 tools/test_grapple_over_interstitial.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

VIEWPORT = {'width': 1280, 'height': 720}

FAKE_ADS = r'''(() => {
    const listeners = {}
    const FAKE = window.__fakeAds = {calls: [],
        emit(state) { (listeners.interstitial || []).slice().forEach(fn => fn(state)) }}
    window.bridge.advertisement = {
        isInterstitialSupported: true, isRewardedSupported: false, interstitialState: null,
        on(event, fn) { (listeners[event] = listeners[event] || []).push(fn) },
        off(event, fn) { listeners[event] = (listeners[event] || []).filter(f => f !== fn) },
        showInterstitial(placement) { FAKE.calls.push(placement) }
    }
})()
'''
NO_BRIDGE = '// no window.bridge\n'

STATE = '''() => ({paused: menu.gamePaused, pending: interstitialPending, adOpen,
    completed: floors[0].climbStats.completed,
    calls: window.__fakeAds ? window.__fakeAds.calls.slice() : []})'''
FRAMES = '() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))'


def log(msg):
    print(msg, file=sys.stderr, flush=True)


class GrappleOverInterstitialTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import build_release
        zip_dir = os.environ.get('INTERSTITIAL_ZIP_DIR')
        if zip_dir:
            out = Path(zip_dir)
        else:
            out = Path(tempfile.mkdtemp(prefix='interstitial-zip-'))
            cls.addClassCleanup(shutil.rmtree, out, True)
            build_release.build('playgama', out, tree=build_release.CommittedTree('HEAD'))
        cls.zip = out / 'playgama' / 'grapple-over-playgama.zip'
        cls.site = Path(tempfile.mkdtemp(prefix='interstitial-site-'))
        cls.addClassCleanup(shutil.rmtree, cls.site, True)
        with zipfile.ZipFile(cls.zip) as z:
            z.extractall(cls.site)
        cls.rows = []

    @classmethod
    def tearDownClass(cls):
        evidence = os.environ.get('INTERSTITIAL_EVIDENCE')
        if evidence:
            Path(evidence).parent.mkdir(parents=True, exist_ok=True)
            Path(evidence).write_text(json.dumps({
                'zip': str(cls.zip), 'zipSha256': hashlib.sha256(cls.zip.read_bytes()).hexdigest(),
                'scenarios': cls.rows}, separators=(',', ':')) + '\n')

    def open(self, stack, bridge=True):
        from browser_test_support import start_browser_test, wait_for_boot_run
        from game_harness import LOCAL_BRIDGE, SDK_URL, collect_errors
        url, browser = start_browser_test(self.site, stack.callback)
        context = browser.new_context(viewport=VIEWPORT, locale='en-US')
        stack.callback(context.close)
        body = LOCAL_BRIDGE + ';\n' + FAKE_ADS if bridge else NO_BRIDGE
        context.route(SDK_URL, lambda r: r.fulfill(content_type='application/javascript', body=body))
        page = context.new_page()
        errors = collect_errors(page)
        page.goto(url + 'index.html')
        wait_for_boot_run(page)
        page.wait_for_function('() => runInProgress && !menu.gamePaused && !isViewRotated()')
        self.assertEqual(page.evaluate('[BUILD_CONFIG.platform, version]'), ['playgama', 'grapple_over'])
        return page, errors

    def state(self, page):
        page.evaluate(FRAMES)
        return page.evaluate(STATE)

    def click_button0(self, page):
        """Click the climb menu's first button (Resume, or Replay at the summit)."""
        p = page.evaluate('''() => { const r = CLIMB_UI.buttons[0].background
            return canvasCoordsToViewportCoords({x: r.x + r.width / 2, y: r.y + r.height / 2}) }''')
        page.mouse.click(p['x'], p['y'])
        return self.state(page)

    def run_scenario(self, name, open_by, final=None, bridge=True):
        with ExitStack() as stack:
            page, errors = self.open(stack, bridge)
            row = {'scenario': name}
            if open_by == 'p':
                page.keyboard.press('p')
            elif open_by == 'blur':
                page.evaluate('() => window.dispatchEvent(new Event("blur"))')
            else:
                # The hook a physics step calls in the finish region; the same
                # frame's draw() then paints the summit screen
                page.evaluate('() => { CLIMB_UI.complete(); draw() }')
            row['opened'] = self.state(page)
            if final:
                # While the ad is up: paused, and the menu ignores a click and P
                page.evaluate('() => window.__fakeAds.emit("opened")')
                row['duringAd'] = self.state(page)
                row['clickDuringAd'] = self.click_button0(page)
                page.keyboard.press('p')
                row['pDuringAd'] = self.state(page)
                page.evaluate('s => window.__fakeAds.emit(s)', final)
                row['afterAd'] = self.state(page)
            row['calls'] = row['opened']['calls']
            # The menu answers again: Resume unpauses, Replay restarts the climb
            row['clickAfter'] = self.click_button0(page)
            row['pageErrors'] = errors['page']
            return row

    def check(self, row, calls, ad):
        r = row
        ok = [r['pageErrors'] == [], r['calls'] == calls, r['opened']['paused'] is True,
              r['opened']['pending'] is ad,
              r['clickAfter']['paused'] is False, r['clickAfter']['completed'] is False]
        if ad:
            for key in ('duringAd', 'clickDuringAd', 'pDuringAd'):
                ok += [r[key]['paused'] is True, r[key]['pending'] is True]
            ok += [r['afterAd']['paused'] is True, r['afterAd']['pending'] is False,
                   r['afterAd']['adOpen'] is False]
        r['pass'] = all(ok)
        self.rows.append(r)
        log(json.dumps(r, separators=(',', ':')))
        self.assertEqual(r['pageErrors'], [])
        self.assertEqual(r['calls'], calls)
        self.assertTrue(r['pass'], r)

    def test_01_pause_by_p_ad_closed(self):
        self.check(self.run_scenario('pause_p_closed', 'p', 'closed'), ['pause'], True)

    def test_02_summit_ad_closed(self):
        row = self.run_scenario('summit_closed', 'summit', 'closed')
        self.assertTrue(row['opened']['completed'])
        self.check(row, ['summit'], True)

    def test_03_pause_by_p_ad_failed(self):
        self.check(self.run_scenario('pause_p_failed', 'p', 'failed'), ['pause'], True)

    def test_04_bridge_missing(self):
        self.check(self.run_scenario('pause_p_no_bridge', 'p', bridge=False), [], False)

    def test_05_blur_pause_no_ad(self):
        self.check(self.run_scenario('pause_blur', 'blur'), [], False)


if __name__ == '__main__':
    unittest.main()
