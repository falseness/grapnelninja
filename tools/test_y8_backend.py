"""TASK-858: the Y8 build (platform/backends/y8.js, Y8 minimal SDK 2.x).

Loads the built y8 zip (artifacts/release-grapple-over/y8/
grapple-over-y8.zip, or Y8_ZIP) from a blank local origin
(https://y8-local.test/grapple-over/, served by Playwright routes). The
zip's async SDK tag (https://cdn.y8.com/minimal-sdk/2-0/y8.min.js) is
answered with a fake SDK that records every call in order
(window.__fakeY8.calls), with no SDK, with throwing SDKs, or (test_09) with
the real SDK script. Every other request is blocked and recorded (test_09:
the real SDK's own requests to y8.com hosts are aborted and listed apart).
The vendored GameAnalytics SDK (analytics/vendor/GameAnalytics.min.js) is
served as an empty script, so the GameAnalytics backend stays a no-op and
nothing reaches api.gameanalytics.com (tools/smoke_gameanalytics.py --zip
covers the real GameAnalytics traffic of this zip).

Y8_APP_ID / Y8_GAME_ID come from the environment or the credentials file
(as tools/test_build_release.py); their values are compared, never printed
or written (assertion messages and evidence carry match flags only).

- 00: the zip is current (every shipped file except the rewritten
  index.html/buildconfig.js equals the working tree); the async SDK tag sits
  right before the y8.js tag; analytics is the GameAnalytics backend; y8.js is
  self-contained; buildconfig.js carries the env ids.
- 01: init: sdk.init called once, after the SDK script ran (also when the
  SDK script arrives late), with ({appId, autoLogin: false}, {gameId}) equal
  to the env ids; environment 'y8'; isBlacklisted asked once.
- 02: guest play: no login/getUser-driven call; the run plays; saves go to
  localStorage only (no saveData/loadData). Signed in (fake getUser): keys
  missing locally come from loadData; saveData mirrors writes, at most 1
  per key per remoteWriteGapMs with the latest value.
- 03: blacklisted (isBlacklisted() true): no interstitial, no rewarded
  (free go back), no showAd call. A rejecting or never-settling check
  allows ads.
- 04: interstitial: 'skipped' with no SDK call while a run is in play; at a
  natural break viewed/dismissed -> 'closed', no fill / throw / reject ->
  'failed'; never starts -> 'failed' after adOpenTimeoutMs and stays in
  flight; min gap; game over flow plays one showAd({type: 'next'}).
- 05: window blur pauses and mutes (the player cannot resume while it
  holds); focus unmutes and lifts the hold; the player's resume runs.
- 06: rewarded results as docs/platform-sdk.md: adViewed -> 'rewarded',
  adDismissed -> 'closed', no fill / throw / reject / never -> 'failed';
  the go-back dialog goes back on 'rewarded', keeps falling on 'closed'.
- 07: no SDK (empty script; a 404 SDK): boots to play, environment
  'disabled', no ads, free go back.
- 08: throwing SDKs (y8.sdk() throws; init throws; init rejects; init never
  settles; every property read throws): boot to play.
- 09: the real SDK script (fetched live; skipped when unreachable): boots to
  play with 0 uncaught errors; the SDK's 'App ID: .. Game ID: ..' log line
  matches the env ids. Writes real-sdk.json (ids_match, no id values).
Every test asserts 0 uncaught errors, 0 unhandled rejections, 0 console
errors, 0 blocked requests and no showAd({type: 'next'}) while a run plays.

Y8_BACKEND_EVIDENCE_DIR=DIR writes y8-backend.json, real-sdk.json,
real-sdk.log (ids redacted) and y8-boot.png.

    python3 tools/test_y8_backend.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from game_harness import READY
from test_build_release import y8_env
from test_go_back import SETUP, CANDIDATES, CATCH, AFTER
from test_go_back_dialog import START, FALL, HOOKS

ROOT = Path(__file__).resolve().parent.parent
ZIP = Path(os.environ.get('Y8_ZIP') or ROOT / 'artifacts' / 'release-grapple-over' / 'y8' / 'grapple-over-y8.zip')
SDK_URL = 'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js'
SDK_TAG = '<script src="%s" async></script>' % SDK_URL
BACKEND_TAG = '<script src = "platform/backends/y8.js"></script>'
GAME_BASE = 'https://y8-local.test/grapple-over/'
GAME_URL = GAME_BASE + 'index.html'
REWRITTEN = {'index.html', 'buildconfig.js', 'analytics/backends/gameanalytics.js'}
GA_SDK = 'analytics/vendor/GameAnalytics.min.js'
Y8_HOSTS = re.compile(r'^https://([a-z0-9-]+\.)*y8\.com/')
ID_LINE = re.compile(r'App ID: (\S+)\s+Game ID: (\S+)')

CONTENT_TYPES = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
                 '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
                 '.webp': 'image/webp', '.jpg': 'image/jpeg', '.woff2': 'font/woff2'}

INIT = r'''(() => {
    // A natural break for direct ad calls: the run really stops (pause menu)
    window.BREAK = () => { if (!menu.gamePaused) menu.startPause() }
    window.__errors = []
    addEventListener('error', e => __errors.push('error: ' + (e.message || e.type)))
    addEventListener('unhandledrejection', e => __errors.push('unhandledrejection: ' +
        (e.reason && e.reason.message || String(e.reason))))
})()'''

# Recording fake of the Y8 minimal SDK 2.x surface the backend uses
# (shape of the real y8.min.js: window.y8 = {sdk, emitReadyEvent}, the
# y8sdk.ready event fired in a setTimeout after the script ran). Options
# from window.__fakeY8Opts: init ('ok' | 'throw' | 'reject' | 'never'),
# blacklisted (false | true | 'reject' | 'never'), user (null or an object:
# signed in), data ({key: value} for loadData), next / reward ad modes
# ('viewed' | 'dismissed' | 'noAdPreloaded' | 'frequencyCapped' | 'throw' |
# 'reject' | 'never' (pending, no callbacks) | 'silent' (resolves, no
# callbacks)). Each showAd records whether a run was in play.
FAKE_SDK = r'''(() => {
    const F = window.__fakeY8 = Object.assign({calls: [], init: 'ok', blacklisted: false, user: null,
        data: {}, next: 'viewed', reward: 'viewed', adMs: 30, saved: []}, window.__fakeY8Opts || {})
    const rec = (name, arg) => F.calls.push(arg === undefined ? {name} : {name, arg})
    const call = (o, name, arg) => { rec('cb:' + name); if (typeof o[name] === 'function') o[name](arg) }
    const NO_AD = ['noAdPreloaded', 'frequencyCapped', 'notReady', 'timeout', 'error']
    function inPlay() {
        try { return !!(runInProgress && !menu.gamePaused && !continueOffer.visible) } catch (e) { return null }
    }
    function showAd(o) {
        o = o || {}
        const mode = o.type === 'reward' ? F.reward : F.next
        rec('showAd', {type: o.type, name: o.name, inPlay: inPlay()})
        if (mode === 'throw') throw new Error('fake showAd throw')
        if (mode === 'reject') return Promise.reject(new Error('fake showAd rejected'))
        if (mode === 'never') return new Promise(() => {})
        if (mode === 'silent') return Promise.resolve()
        setTimeout(() => {
            if (NO_AD.includes(mode)) return call(o, 'adBreakDone', {breakStatus: mode})
            const play = () => {
                call(o, 'beforeAd')
                setTimeout(() => {
                    if (o.type === 'reward') call(o, mode === 'viewed' ? 'adViewed' : 'adDismissed')
                    call(o, 'afterAd')
                    call(o, 'adBreakDone', {breakStatus: mode})
                }, F.adMs)
            }
            if (o.type === 'reward') call(o, 'beforeReward', play); else play()
        }, 0)
        return Promise.resolve()
    }
    const sdk = {
        init(app, ad) {
            rec('init', {app: Object.assign({}, app), ad: Object.assign({}, ad)})
            if (F.init === 'throw') throw new Error('fake init throw')
            if (F.init === 'reject') return Promise.reject(new Error('fake init rejected'))
            if (F.init === 'never') return new Promise(() => {})
            return Promise.resolve()
        },
        isBlacklisted() {
            rec('isBlacklisted')
            if (F.blacklisted === 'reject') return Promise.reject(new Error('fake isBlacklisted rejected'))
            if (F.blacklisted === 'never') return new Promise(() => {})
            return Promise.resolve(F.blacklisted === true)
        },
        getUser() { return F.user },
        showAd,
        saveData(o) { rec('saveData', o.key); F.saved.push(o); return Promise.resolve() },
        loadData(o) { rec('loadData', o.key); return Promise.resolve(F.data[o.key] === undefined ? null : F.data[o.key]) },
        login() { rec('login'); return Promise.resolve() },
        saveLeaderboardScore() { rec('saveLeaderboardScore'); return Promise.resolve() },
        awardAchievement() { rec('awardAchievement'); return Promise.resolve() }
    }
    function ready() { rec('y8sdk.ready'); dispatchEvent(new Event('y8sdk.ready')) }
    window.y8 = {sdk: () => sdk, emitReadyEvent: () => setTimeout(ready, 0)}
    setTimeout(ready, 0)
})()'''

# y8.sdk() itself throws
THROWING_SDK = r'''window.y8 = {sdk() { throw new Error('fake y8.sdk throws') }, emitReadyEvent() {}}
setTimeout(() => dispatchEvent(new Event('y8sdk.ready')), 0)'''

# Every property read of the SDK object throws
PROXY_SDK = r'''(() => { const sdk = new Proxy({}, {get(t, k) { throw new Error('fake Y8 getter ' + String(k)) }})
window.y8 = {sdk: () => sdk}; setTimeout(() => dispatchEvent(new Event('y8sdk.ready')), 0) })()'''

SDKS = {'fake': FAKE_SDK, 'none': '', 'throwing': THROWING_SDK, 'proxy': PROXY_SDK}

STATE = '''() => ({paused: menu.gamePaused, hostPaused, muted: GAME_AUDIO.muted,
    reasons: [...GAME_AUDIO.reasons].sort(), elapsed: floors[0].climbStats.elapsedActiveMs,
    adOpen, interstitialPending, offer: continueOffer.visible, runInProgress})'''

CALLS = '() => window.__fakeY8.calls.map(c => c.name)'


class Y8BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        if not ZIP.is_file():
            raise unittest.SkipTest('no y8 zip: run tools/build_release.py --portal y8')
        cls.env = y8_env()
        if not (cls.env['Y8_APP_ID'] and cls.env['Y8_GAME_ID']):
            raise unittest.SkipTest('Y8_APP_ID / Y8_GAME_ID unavailable')
        cls.tmp = cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='y8-zip-'))
        with zipfile.ZipFile(ZIP) as z:
            cls.names = sorted(z.namelist())
            z.extractall(cls.tmp)
        cls.files = {n: (Path(cls.tmp) / n).read_bytes() for n in cls.names if not n.endswith('/')}
        _, cls.browser = start_browser_test(Path(cls.tmp), cls.stack.callback)
        cls.evidence = {'zip': str(ZIP.relative_to(ROOT) if ZIP.is_relative_to(ROOT) else ZIP),
                        'files': len(cls.files), 'unhandled_rejections': 0, 'uncaught_errors': 0,
                        'next_ad_while_playing': []}
        cls.out = os.environ.get('Y8_BACKEND_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            text = json.dumps(cls.evidence, indent=1, sort_keys=True) + '\n'
            assert cls.env['Y8_APP_ID'] not in text and cls.env['Y8_GAME_ID'] not in text
            Path(cls.out, 'y8-backend.json').write_text(text)
        cls.stack.close()

    def redact(self, text):
        for key in ('Y8_APP_ID', 'Y8_GAME_ID'):
            text = text.replace(self.env[key], '<%s>' % key)
        return text

    # -- page --------------------------------------------------------------

    def serve(self, route):
        url = route.request.url
        if url == SDK_URL:
            self.sdk_requests += 1
            if self.sdk_delay_s:
                time.sleep(self.sdk_delay_s)
            if self.sdk == 'real':
                try:
                    response = route.fetch(timeout=30000)
                    body = response.body()
                except Exception as e:  # the host cannot reach Y8
                    self.real_fetch = {'error': str(e)}
                    return route.abort()
                self.real_fetch = {'status': response.status, 'bytes': len(body),
                                   'sha256': hashlib.sha256(body).hexdigest()}
                return route.fulfill(status=response.status, body=body,
                                     content_type='application/javascript')
            if self.sdk == '404':
                return route.fulfill(status=404, body='')
            return route.fulfill(body=SDKS[self.sdk], content_type='application/javascript')
        if url.startswith(GAME_BASE):
            name = url[len(GAME_BASE):].split('?')[0].split('#')[0] or 'index.html'
            if name == GA_SDK:
                return route.fulfill(content_type='application/javascript', body='// GameAnalytics stub\n')
            if name in self.files:
                return route.fulfill(body=self.files[name],
                                     content_type=CONTENT_TYPES.get(Path(name).suffix, 'application/octet-stream'))
            self.missing.append(name)
            return route.fulfill(status=404, body='')
        if self.sdk == 'real' and Y8_HOSTS.match(url):
            # The real SDK's own API/analytics/ad requests: not sent from a test page
            self.sdk_traffic.append(url.split('?')[0])
            return route.abort()
        self.blocked.append(url)
        return route.abort()

    def open(self, sdk='fake', opts=None, sdk_delay_s=0, setup=None):
        """New context with the game page and `sdk`; returns the page once a run is in play."""
        self.sdk = sdk
        self.sdk_delay_s = sdk_delay_s
        self.sdk_requests = 0
        self.real_fetch = None
        self.blocked, self.missing, self.sdk_traffic = [], [], []
        self.page_errors, self.console_errors, self.console = [], [], []
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        context.add_init_script(INIT)
        if opts:
            context.add_init_script('window.__fakeY8Opts = %s' % json.dumps(opts))
        if setup:
            context.add_init_script(setup)
        context.route('**/*', self.serve)
        page = context.new_page()
        page.on('pageerror', lambda e: self.page_errors.append(str(e)))

        def console(m):
            self.console.append('%s: %s' % (m.type, m.text))
            if m.type == 'error':
                self.console_errors.append(m.text)
        page.on('console', console)
        state = {'sdk': sdk, 'blocked': self.blocked, 'missing': self.missing,
                 'page_errors': self.page_errors, 'console_errors': self.console_errors}
        self.addCleanup(self.assert_clean, page, state)
        started = time.monotonic()
        page.goto(GAME_URL)
        page.wait_for_function(READY, timeout=30000)
        self.boot_s = round(time.monotonic() - started, 2)
        self.assertEqual(self.sdk_requests, 1)
        return page

    def assert_clean(self, page, state):
        frames = page.evaluate('() => window.__errors || []')
        console_errors = state['console_errors']
        if state['sdk'] == 'real':
            # Requests the test aborts log 'Failed to load resource' / fetch errors
            console_errors = [e for e in console_errors if not re.search(r'net::ERR_FAILED|Failed to fetch', e)]
        if state['sdk'] == '404':
            # The browser's own line for the SDK script answered 404
            console_errors = [e for e in console_errors if '404' not in e]
        errors = {'page': state['page_errors'], 'console': console_errors,
                  'frames': frames, 'blocked': state['blocked'], 'missing': state['missing']}
        pages = self.evidence.setdefault('pages', [])
        pages.append({'test': self._testMethodName, 'sdk': state['sdk'], **{k: len(v) for k, v in errors.items()}})
        type(self).evidence['unhandled_rejections'] += sum('unhandledrejection' in e for e in frames)
        type(self).evidence['uncaught_errors'] += len(state['page_errors']) + sum(e.startswith('error') for e in frames)
        if state['sdk'] == 'fake':
            ads = page.evaluate('() => window.__fakeY8.calls.filter(c => c.name === "showAd").map(c => c.arg)')
            bad = [a for a in ads if a['type'] == 'next' and a['inPlay'] is not False]
            if bad:
                self.evidence['next_ad_while_playing'].append(self._testMethodName)
            self.assertEqual(bad, [], "showAd({type: 'next'}) while a run was in play")
        self.assertEqual(errors, {'page': [], 'console': [], 'frames': [], 'blocked': [], 'missing': []})

    def fake(self, page, **modes):
        page.evaluate('m => Object.assign(window.__fakeY8, m)', modes)

    def calls(self, page):
        return page.evaluate(CALLS)

    def wait_unpaused_run(self, page):
        page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        page.wait_for_function('() => !menu.gamePaused && runInProgress', timeout=10000)

    def plays(self, page, ms=300):
        self.wait_unpaused_run(page)
        start = page.evaluate('floors[0].climbStats.elapsedActiveMs')
        page.wait_for_function('([el, ms]) => floors[0].climbStats.elapsedActiveMs > el + ms',
                               arg=[start, ms], timeout=10000)
        return True

    def init_ids_match(self, page):
        inits = page.evaluate('() => window.__fakeY8.calls.filter(c => c.name === "init").map(c => c.arg)')
        self.assertEqual(len(inits), 1, 'sdk.init calls: %d' % len(inits))
        app, ad = inits[0]['app'], inits[0]['ad']
        ok = (app == {'appId': self.env['Y8_APP_ID'], 'autoLogin': False} and
              ad == {'gameId': self.env['Y8_GAME_ID']})
        self.assertTrue(ok, 'init args differ from ({appId: Y8_APP_ID, autoLogin: false}, {gameId: Y8_GAME_ID}); '
                            'keys %s / %s' % (sorted(app), sorted(ad)))
        return {'init_calls': 1, 'app_keys': sorted(app), 'ad_keys': sorted(ad), 'autoLogin': app.get('autoLogin'),
                'ids_match': ok}

    # -- tests -------------------------------------------------------------

    def test_00_zip_is_current(self):
        stale = [n for n, b in self.files.items()
                 if n not in REWRITTEN and (not (ROOT / n).is_file() or (ROOT / n).read_bytes() != b)]
        self.assertEqual(stale, [], 'zip is stale: rebuild with tools/build_release.py --portal y8')
        html = self.files['index.html'].decode()
        self.assertEqual(html.count('platform/backends/'), 2)
        self.assertEqual(html.count(SDK_URL), 1)
        sdk_at, backend_at = html.index(SDK_TAG), html.index(BACKEND_TAG)
        self.assertLess(sdk_at, backend_at)
        self.assertEqual(html[sdk_at + len(SDK_TAG):backend_at].strip(), '')
        # Y8 ships the GameAnalytics backend (keys injected; the SDK is stubbed in these tests)
        self.assertIn('<script src = "analytics/vendor/GameAnalytics.min.js"></script>', html)
        self.assertIn('<script src = "analytics/backends/gameanalytics.js"></script>', html)
        self.assertNotIn('analytics/backends/none.js', html)
        config = self.files['buildconfig.js'].decode()
        self.assertIn("platform: 'y8'", config)
        self.assertIn("modes: ['grapple_over']", config)
        ids = re.search(r"y8: \{appId: '([^']*)', gameId: '([^']*)'\}", config)
        self.assertTrue(ids and ids.groups() == (self.env['Y8_APP_ID'], self.env['Y8_GAME_ID']),
                        'buildconfig.js y8 ids differ from Y8_APP_ID / Y8_GAME_ID')
        source = self.files['platform/backends/y8.js'].decode()
        code = '\n'.join(l for l in source.splitlines() if not l.strip().startswith('//'))
        self.assertNotIn('LOCAL_PLATFORM_BACKEND', code)
        self.assertNotIn('base.', code)
        self.assertNotIn('REPLACE', source)
        self.evidence['zip_current'] = {'stale': stale, 'y8_js_bytes': len(source), 'buildconfig_ids_match': True}

    def test_01_init(self):
        page = self.open()
        boot = page.evaluate('''() => ({calls: window.__fakeY8.calls.map(c => c.name), platformId: PLATFORM.getPlatformId(),
            environment: PLATFORM.environment, version, modes: BUILD_CONFIG.modes,
            readiness: PLATFORM_BACKEND.readiness(), interstitial: PLATFORM.isInterstitialSupported(),
            rewarded: PLATFORM.isRewardedSupported(), audio: PLATFORM.isAudioEnabled()})''')
        ids = self.init_ids_match(page)
        self.assertEqual([boot['platformId'], boot['environment']], ['y8', 'y8'])
        self.assertEqual(boot['version'], 'grapple_over')
        self.assertEqual(boot['modes'], ['grapple_over'])
        self.assertEqual(boot['readiness'], {'state': 'success'})
        self.assertTrue(boot['interstitial'] and boot['rewarded'] and boot['audio'], boot)
        self.assertEqual(boot['calls'].count('isBlacklisted'), 1)
        self.assertLess(boot['calls'].index('init'), boot['calls'].index('isBlacklisted'))
        self.assertNotIn('login', boot['calls'])
        self.assertTrue(self.plays(page))
        if self.out:
            Path(self.out).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(self.out) / 'y8-boot.png'))
        # The async SDK script arriving late: init still waits for it
        late = self.open(sdk_delay_s=1.5)
        late_row = late.evaluate('''() => ({environment: PLATFORM.environment,
            calls: window.__fakeY8.calls.map(c => c.name)})''')
        late_ids = self.init_ids_match(late)
        self.assertEqual(late_row['environment'], 'y8')
        self.assertTrue(self.plays(late))
        self.evidence['init'] = {'calls': boot['calls'], **ids, 'boot_s': self.boot_s,
                                 'late_sdk': {'delay_s': 1.5, **late_row, **late_ids},
                                 **{k: boot[k] for k in ('platformId', 'environment', 'readiness', 'modes')}}

    def test_02_guest_play_and_signed_in_saves(self):
        page = self.open()
        self.assertTrue(self.plays(page, 500))
        guest = page.evaluate('''async () => {
            const saved = await PLATFORM.storage.setMany({'grapnelninja.y8Probe': 'g1'})
            PROGRESS.save()
            await new Promise(r => setTimeout(r, 300))
            return {saved, local: localStorage.getItem('grapnelninja.y8Probe'),
                    read: await PLATFORM.storage.getMany(['grapnelninja.y8Probe', 'grapnelninja.y8Missing']),
                    calls: window.__fakeY8.calls.map(c => c.name)} }''')
        self.assertTrue(guest['saved'])
        self.assertEqual(guest['local'], 'g1')
        self.assertEqual(guest['read'], {'grapnelninja.y8Probe': 'g1', 'grapnelninja.y8Missing': None})
        for name in ('login', 'saveData', 'loadData', 'saveLeaderboardScore', 'awardAchievement'):
            self.assertNotIn(name, guest['calls'])
        # Signed in: remote fills missing keys; writes mirrored, 1 per key per gap
        signed = self.open(opts={'user': {'pid': 'fake'}, 'data': {'grapnelninja.y8Remote': 'r1'}})
        row = signed.evaluate('''async () => {
            PLATFORM_BACKEND.remoteWriteGapMs = 400
            const read = await PLATFORM.storage.getMany(['grapnelninja.y8Remote', 'grapnelninja.y8Nothing'])
            const F = window.__fakeY8, n = F.saved.length
            await PLATFORM.storage.setMany({'grapnelninja.y8Mirror': 'a'})
            await PLATFORM.storage.setMany({'grapnelninja.y8Mirror': 'b'})
            await PLATFORM.storage.setMany({'grapnelninja.y8Mirror': 'c'})
            const first = F.saved.slice(n).filter(s => s.key === 'grapnelninja.y8Mirror').map(s => s.value)
            await new Promise(r => setTimeout(r, 700))
            const later = F.saved.slice(n).filter(s => s.key === 'grapnelninja.y8Mirror').map(s => s.value)
            return {read, first, later, local: localStorage.getItem('grapnelninja.y8Mirror'),
                    remoteCopied: localStorage.getItem('grapnelninja.y8Remote')} }''')
        self.assertEqual(row['read'], {'grapnelninja.y8Remote': 'r1', 'grapnelninja.y8Nothing': None})
        self.assertEqual(row['first'], ['a'])
        self.assertEqual(row['later'], ['a', 'c'])
        self.assertEqual(row['local'], 'c')
        self.assertEqual(row['remoteCopied'], 'r1')
        self.assertTrue(self.plays(signed))
        self.assertNotIn('login', self.calls(signed))
        self.evidence['guest'] = {'guest': guest, 'signed_in': row}

    def ad_counts(self, page):
        return page.evaluate('''async () => ({interstitial: PLATFORM.isInterstitialSupported(),
            due: (PLATFORM.interstitialMinGapMs = 0, BREAK(), PLATFORM.isInterstitialDue()),
            rewarded: PLATFORM.isRewardedSupported(),
            show: await PLATFORM.showInterstitial('game_over'), reward: await PLATFORM.showRewarded('go_back'),
            showAds: window.__fakeY8.calls.filter(c => c.name === 'showAd').length})''')

    def test_03_blacklisted(self):
        page = self.open(opts={'blacklisted': True})
        self.assertTrue(self.plays(page))
        row = self.ad_counts(page)
        self.assertEqual(row, {'interstitial': False, 'due': False, 'rewarded': False,
                               'show': 'skipped', 'reward': 'unavailable', 'showAds': 0})
        free = self.go_back('viewed', opts={'blacklisted': True})
        self.assertEqual(free['marker'], 0, free)
        self.assertTrue(free['back'], free)
        self.assertNotIn('showAd', free['calls'])
        rows = {'blacklisted': row, 'go_back_free': free}
        for mode in ('reject', 'never'):
            p = self.open(opts={'blacklisted': mode})
            r = rows[mode] = self.ad_counts(p)
            self.assertTrue(r['interstitial'] and r['rewarded'], (mode, r))
            self.assertEqual([r['show'], r['reward'], r['showAds']], ['closed', 'rewarded', 2], (mode, r))
        self.evidence['blacklist'] = rows

    def interstitial(self, page, mode):
        """PLATFORM.showInterstitial at a natural break with the fake in mode."""
        self.fake(page, next=mode)
        return page.evaluate('''async () => {
            const before = window.__fakeY8.calls.length, states = []
            PLATFORM.onAdState(s => states.push(s))
            BREAK()
            const t0 = performance.now()
            const result = await PLATFORM.showInterstitial('game_over')
            const ms = Math.round(performance.now() - t0)
            return {result, ms, states, hostPaused, calls: window.__fakeY8.calls.slice(before).map(c => c.name)}
        }''')

    def test_04_interstitial(self):
        prepare = '''() => { PLATFORM.interstitialMinGapMs = 0; PLATFORM_BACKEND.adOpenTimeoutMs = 400 }'''
        page = self.open()
        self.wait_unpaused_run(page)
        page.evaluate(prepare)
        playing = page.evaluate('''async () => { PLATFORM.gameplayStart('grapple_over')
            const n = window.__fakeY8.calls.length
            const due = PLATFORM.isInterstitialDue()
            const result = await PLATFORM.showInterstitial('game_over')
            return {due, result, calls: window.__fakeY8.calls.slice(n).map(c => c.name)} }''')
        self.assertEqual(playing, {'due': False, 'result': 'skipped', 'calls': []})
        rows = {}
        expect = {'viewed': 'closed', 'dismissed': 'closed', 'noAdPreloaded': 'failed', 'frequencyCapped': 'failed',
                  'throw': 'failed', 'reject': 'failed', 'never': 'failed', 'silent': 'failed'}
        for mode, result in expect.items():
            if mode in ('never', 'silent'):
                # A break that never ends stays in flight: fresh page each
                page = self.open()
                page.evaluate(prepare)
            row = rows[mode] = self.interstitial(page, mode)
            self.assertEqual(row['result'], result, (mode, row))
            self.assertEqual(row['calls'].count('showAd'), 1, (mode, row))
            self.assertEqual(row['states'], ['opened', 'closed' if result == 'closed' else 'failed'], (mode, row))
            self.assertFalse(row['hostPaused'], (mode, row))
            if mode in ('never', 'silent'):
                self.assertGreaterEqual(row['ms'], 350)
                self.assertLess(row['ms'], 2000)
                stuck = page.evaluate('''async () => ({due: PLATFORM.isInterstitialDue(),
                    again: await PLATFORM.showInterstitial('game_over')})''')
                self.assertEqual(stuck, {'due': False, 'again': 'skipped'}, mode)
                row['after'] = stuck
        types = page.evaluate('() => window.__fakeY8.calls.filter(c => c.name === "showAd").map(c => c.arg.type)')
        self.assertEqual(set(types), {'next'})
        # Min gap
        gap = page.evaluate('''() => { PLATFORM.interstitialMinGapMs = 60000; return PLATFORM.isInterstitialDue() }''')
        self.assertFalse(gap)
        # Game over flow: death screen, Restart plays one interstitial, next run starts
        flow = self.open()
        self.wait_unpaused_run(flow)
        flow.evaluate('PLATFORM.interstitialMinGapMs = 0')
        n = len(self.calls(flow))
        flow.evaluate('''() => { ninja.isInvulnerable = () => false; onLethalDeath() }''')
        dead = flow.evaluate(STATE)
        self.assertTrue(dead['offer'], dead)
        self.assertEqual(self.calls(flow)[n:], [], 'no ad while the death screen opens')
        flow.evaluate('restartFromOffer()')
        flow.wait_for_function('() => !interstitialPending && runInProgress && !continueOffer.visible', timeout=10000)
        after = flow.evaluate('n => window.__fakeY8.calls.slice(n)', n)
        ads = [c['arg'] for c in after if c['name'] == 'showAd']
        self.assertEqual(ads, [{'type': 'next', 'name': 'game_over', 'inPlay': False}])
        self.wait_unpaused_run(flow)
        refused = flow.evaluate('PLATFORM.showInterstitial("game_over")')
        self.assertEqual(refused, 'skipped')
        self.evidence['interstitial'] = {'while_playing': playing,
                                         'modes': {k: {x: v.get(x) for x in ('result', 'states', 'calls', 'ms', 'after')}
                                                   for k, v in rows.items()},
                                         'min_gap_due': gap, 'game_over': {'dead': dead, 'ads': ads,
                                                                           'while_playing': refused}}

    def test_05_blur_pauses_and_mutes(self):
        page = self.open()
        self.wait_unpaused_run(page)
        running = page.evaluate(STATE)
        self.assertFalse(running['paused'] or running['hostPaused'] or running['muted'])
        page.evaluate('dispatchEvent(new Event("blur"))')
        blurred = page.evaluate(STATE)
        self.assertTrue(blurred['paused'] and blurred['hostPaused'] and blurred['muted'], blurred)
        self.assertEqual(blurred['reasons'], ['host'])
        self.assertFalse(page.evaluate('PLATFORM.isAudioEnabled()'))
        page.evaluate('menu.unPause()')
        page.wait_for_timeout(300)
        held = page.evaluate(STATE)
        self.assertTrue(held['paused'] and held['muted'], held)
        self.assertEqual(held['elapsed'], blurred['elapsed'])
        page.evaluate('dispatchEvent(new Event("focus"))')
        focused = page.evaluate(STATE)
        self.assertFalse(focused['hostPaused'] or focused['muted'], focused)
        self.assertEqual(focused['reasons'], [])
        self.assertTrue(page.evaluate('PLATFORM.isAudioEnabled()'))
        page.evaluate('menu.unPause()')
        page.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 200',
                               arg=focused['elapsed'], timeout=10000)
        running2 = page.evaluate(STATE)
        self.assertFalse(running2['paused'] or running2['hostPaused'] or running2['muted'])
        # A blur caused by our own ad (the ad iframe takes focus) does not pause
        ad_blur = page.evaluate('''async () => {
            const states = []
            PLATFORM.onPause(p => states.push(p))
            window.__fakeY8.adMs = 200
            const pending = PLATFORM.showRewarded('go_back')
            await new Promise(r => setTimeout(r, 60))
            dispatchEvent(new Event('blur'))
            const result = await pending
            return {result, states, hostPaused} }''')
        self.assertEqual(ad_blur, {'result': 'rewarded', 'states': [], 'hostPaused': False})
        self.evidence['blur'] = {'running': running, 'blurred': blurred, 'held': held,
                                 'focused': focused, 'running_again': running2, 'ad_blur': ad_blur}

    def rewarded(self, page, mode):
        self.fake(page, reward=mode)
        return page.evaluate('''async () => {
            const n = window.__fakeY8.calls.length, states = []
            PLATFORM.onAdState(s => states.push(s))
            const supported = PLATFORM.isRewardedSupported()
            const result = await PLATFORM.showRewarded('go_back')
            return {supported, result, states, hostPaused, calls: window.__fakeY8.calls.slice(n).map(c => c.name)} }''')

    def go_back(self, mode, opts=None):
        """The go-back dialog with the fake reward in mode; returns the outcome."""
        page = self.open(opts=opts)
        page.evaluate(SETUP)
        page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        page.evaluate(HOOKS)
        page.evaluate('PLATFORM_BACKEND.adOpenTimeoutMs = 400')
        page.evaluate('''() => { window.MUTED_SEEN = false; const mute = GAME_AUDIO.mute
            GAME_AUDIO.mute = function(r, on) { if (on && r === 'ad') MUTED_SEEN = true; return mute.call(this, r, on) } }''')
        self.fake(page, reward=mode)
        cp = None
        for target in page.evaluate(CANDIDATES)['static']:
            page.mouse.up()
            page.evaluate(CATCH, [target['x'], target['y']])
            p = page.evaluate('''([x, y]) => canvasCoordsToViewportCoords({
                x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})''', [target['x'], target['y']])
            page.mouse.move(p['x'], p['y'])
            page.mouse.down()
            row = page.evaluate(AFTER)
            if row['grappled'] and row['target'] == target['id']:
                page.evaluate('() => { ninja.speedX = ninja.speedY = 0; physics() }')
            page.mouse.up()
            if row['grappled'] and row['target'] == target['id'] and row['checkpoint']:
                cp = row['checkpoint']
                break
        self.assertIsNotNone(cp, 'no catchable checkpoint')
        page.evaluate(START, 9000)
        opened = page.evaluate(FALL, [2000, None])
        self.assertTrue(opened['paused'] and opened['dialog'] and opened['open'], opened)
        marker = page.evaluate('''() => { LAYOUT_PROBE.boxes = []; redrawOverlays()
            const boxes = LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes = null
            return boxes.filter(b => b.kind === 'adMarker').length }''')
        n = len(self.calls(page))
        page.evaluate('CLIMB_UI.goBack()')
        page.wait_for_function('() => !CLIMB_UI.goBackAdPending', polling=100, timeout=15000)
        rest = page.evaluate('() => { for (let i = 0; i < 300; i++) physics(); return STATE() }')
        audio = page.evaluate('() => ({mutedSeen: MUTED_SEEN, muted: GAME_AUDIO.muted, hostPaused})')
        back = rest['grapnel']['grappled'] and rest['grapnel']['anchor'] == [cp['anchorX'], cp['anchorY']] \
            and rest['goBacks'] == opened['goBacks'] + 1
        return {'mode': mode, 'marker': marker, 'back': bool(back), 'calls': self.calls(page)[n:],
                'goBacks': [opened['goBacks'], rest['goBacks']], **audio}

    def test_06_rewarded(self):
        page = self.open()
        page.evaluate('PLATFORM_BACKEND.adOpenTimeoutMs = 400')
        expect = {'viewed': 'rewarded', 'dismissed': 'closed', 'noAdPreloaded': 'failed',
                  'frequencyCapped': 'failed', 'throw': 'failed', 'reject': 'failed', 'never': 'failed',
                  'silent': 'failed'}
        rows = {}
        for mode, result in expect.items():
            row = rows[mode] = self.rewarded(page, mode)
            self.assertTrue(row['supported'])
            self.assertEqual(row['result'], result, (mode, row))
            self.assertEqual(row['calls'].count('showAd'), 1, (mode, row))
            self.assertEqual(row['states'], ['opened', 'failed' if result == 'failed' else 'closed'], (mode, row))
            self.assertFalse(row['hostPaused'], (mode, row))
        types = page.evaluate('() => window.__fakeY8.calls.filter(c => c.name === "showAd").map(c => [c.arg.type, c.arg.name])')
        self.assertEqual(set(map(tuple, types)), {('reward', 'go_back')})
        dialog = []
        for mode, back in (('viewed', True), ('dismissed', False), ('noAdPreloaded', True), ('throw', True)):
            row = self.go_back(mode)
            dialog.append(row)
            self.assertEqual(row['marker'], 1, row)
            self.assertEqual(row['back'], back, row)
            self.assertEqual(row['calls'].count('showAd'), 1, row)
            self.assertTrue(row['mutedSeen'], row)
            self.assertFalse(row['muted'] or row['hostPaused'], row)
        self.evidence['rewarded'] = {'results': rows, 'go_back': dialog}

    def boots_without_working_sdk(self, sdk, opts=None):
        page = self.open(sdk=sdk, opts=opts)
        self.assertTrue(self.plays(page))
        row = page.evaluate('''async () => ({platformId: PLATFORM.getPlatformId(), environment: PLATFORM.environment,
            readiness: PLATFORM_BACKEND.readiness(), language: PLATFORM.language,
            interstitial: PLATFORM.isInterstitialSupported(),
            due: (PLATFORM.interstitialMinGapMs = 0, BREAK(), PLATFORM.isInterstitialDue()),
            rewarded: PLATFORM.isRewardedSupported(),
            show: await PLATFORM.showInterstitial('game_over'),
            reward: await PLATFORM.showRewarded('go_back'), ready: await PLATFORM.gameReady(),
            saved: await PLATFORM.storage.setMany({'grapnelninja.y8Probe': 'v'}),
            read: await PLATFORM.storage.getMany(['grapnelninja.y8Probe'])})''')
        self.assertEqual(row['platformId'], 'y8')
        self.assertEqual(row['environment'], 'disabled')
        self.assertEqual(row['readiness'], {'state': 'disabled'})
        self.assertFalse(row['interstitial'] or row['due'] or row['rewarded'], row)
        self.assertEqual([row['show'], row['reward']], ['skipped', 'unavailable'])
        self.assertTrue(row['saved'])
        self.assertEqual(row['read'], {'grapnelninja.y8Probe': 'v'})
        row['boot_s'] = self.boot_s
        row['warnings'] = [c for c in self.console if c.startswith('warning')]
        return row

    def test_07_no_sdk_boots(self):
        rows = {'empty': self.boots_without_working_sdk('none'), '404': self.boots_without_working_sdk('404')}
        free = self.go_back_free('none')
        rows['go_back_free'] = free
        self.evidence['no_sdk'] = rows

    def go_back_free(self, sdk):
        page = self.open(sdk=sdk)
        page.evaluate(SETUP)
        marker = page.evaluate('''() => PLATFORM.isRewardedSupported()''')
        self.assertFalse(marker)
        return {'rewarded_supported': marker}

    def test_08_throwing_sdk_boots(self):
        rows = {}
        for name, sdk, opts in (('y8.sdk throws', 'throwing', None), ('getters throw', 'proxy', None),
                                ('init throws', 'fake', {'init': 'throw'}),
                                ('init rejects', 'fake', {'init': 'reject'}),
                                ('init never settles', 'fake', {'init': 'never'})):
            row = rows[name] = self.boots_without_working_sdk(sdk, opts)
            self.assertEqual(row['language'], 'en')
        self.assertGreaterEqual(rows['init never settles']['boot_s'], 2.5)
        self.evidence['throwing_sdk'] = rows

    def test_09_real_sdk_smoke(self):
        try:
            page = self.open(sdk='real')
        except Exception:
            if self.real_fetch and 'error' in self.real_fetch:
                self.write_real(None)
                self.skipTest('the real Y8 SDK could not be fetched: %s' % self.real_fetch['error'])
            raise
        self.assertTrue(self.plays(page, 500))
        row = page.evaluate('''() => ({platformId: PLATFORM.getPlatformId(), environment: PLATFORM.environment,
            readiness: PLATFORM_BACKEND.readiness(), version, sdkMethods: Object.keys(Object.getPrototypeOf(y8.sdk()))
                .filter(k => typeof y8.sdk()[k] === 'function').sort(),
            interstitial: PLATFORM.isInterstitialSupported(), rewarded: PLATFORM.isRewardedSupported(),
            running: !menu.gamePaused && runInProgress, hostPaused, errors: window.__errors})''')
        page.wait_for_timeout(500)
        lines = [ID_LINE.search(c) for c in self.console]
        found = [m.groups() for m in lines if m]
        ids_match = bool(found) and all(g == (self.env['Y8_APP_ID'], self.env['Y8_GAME_ID']) for g in found)
        row.update({'fetch': self.real_fetch, 'boot_s': self.boot_s, 'id_log_lines': len(found),
                    'ids_match': ids_match, 'uncaught_errors': len(self.page_errors) + len(row['errors']),
                    'sdk_traffic_aborted': sorted(set(self.redact(u) for u in self.sdk_traffic))})
        self.write_real(row)
        self.assertEqual(row['environment'], 'y8')
        self.assertTrue(row['running'], row)
        self.assertEqual(row['errors'], [])
        self.assertEqual(self.real_fetch['status'], 200)
        self.assertTrue(ids_match, 'the SDK logged App ID / Game ID differ from Y8_APP_ID / Y8_GAME_ID '
                                   '(%d id lines)' % len(found))
        self.evidence['real_sdk'] = row

    def write_real(self, row):
        if not self.out:
            return
        Path(self.out).mkdir(parents=True, exist_ok=True)
        lines = ['real Y8 SDK smoke (tools/test_y8_backend.py test_09)',
                 'sdk url: ' + SDK_URL, 'page: ' + GAME_URL + ' (blank local origin, y8 zip %s)' % self.evidence['zip'],
                 'ids: compared with Y8_APP_ID / Y8_GAME_ID, values redacted below',
                 'fetch: ' + json.dumps(self.real_fetch, sort_keys=True), '--- console ---'] + self.console
        lines += ['--- page errors ---'] + (self.page_errors or ['(none)'])
        result = {'test': 'tools/test_y8_backend.py test_09_real_sdk_smoke', 'sdk_url': SDK_URL,
                  'page': GAME_URL, 'zip': self.evidence['zip']}
        if row is None:
            lines.append('RESULT: SKIPPED (SDK not fetchable from this host)')
            result.update({'result': 'SKIPPED', 'fetch': self.real_fetch, 'ids_match': None})
        else:
            ok = (row['running'] and not row['uncaught_errors'] and row['ids_match'] and row['environment'] == 'y8')
            lines += ['--- state ---', json.dumps(row, sort_keys=True),
                      'uncaught errors: %d' % row['uncaught_errors'], 'ids_match: %s' % row['ids_match'],
                      'RESULT: %s' % ('PASS boots to play with the real SDK' if ok else 'FAIL')]
            result.update(row, result='PASS' if ok else 'FAIL')
        text = self.redact('\n'.join(lines) + '\n')
        data = self.redact(json.dumps(result, indent=1, sort_keys=True) + '\n')
        Path(self.out, 'real-sdk.log').write_text(text)
        Path(self.out, 'real-sdk.json').write_text(data)


if __name__ == '__main__':
    unittest.main()
