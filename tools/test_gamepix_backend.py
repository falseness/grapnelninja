"""TASK-857: the GamePix build (platform/backends/gamepix.js, GamePix SDK v3).

Loads the built gamepix zip (artifacts/release-grapple-over/gamepix/
grapple-over-gamepix.zip, or GAMEPIX_ZIP) from a blank local origin
(https://gamepix-local.test/grapple-over/, served by Playwright routes).
The zip's SDK tag (https://integration.gamepix.com/sdk/v3/gamepix.sdk.js)
is answered with a fake SDK that records every call in order
(window.__fakeGamePix.calls), with no SDK, with a throwing SDK, or (test_09)
with the real SDK script. Every other request is blocked and recorded.

- 00: the zip is current (every shipped file except the rewritten
  index.html/buildconfig.js equals the working tree); the SDK tag sits
  right before the gamepix.js tag; analytics stays none.js; gamepix.js is
  self-contained.
- 01: lifecycle: loading(n) values non-decreasing, integers 0..100, ending
  at 100; lifecycle.loaded() once, after loading(100); gameStart() once,
  after loaded(), though every run start calls gameplayStart; lang() sets
  the language; loaded() before any ad call (checked over every test).
- 02: GamePix 'pause' pauses and mutes (the player cannot resume while it
  holds); 'resume' unmutes and lifts the hold; the player's resume runs.
- 03: interstitial: refused ('skipped', no SDK call) while a run is in
  play; at a natural break success -> 'closed', {success:false}, throw,
  rejection -> 'failed'; a promise that never settles -> 'failed' after
  adOpenTimeoutMs (no pause) or after the ad's pause and resume; a pause the
  ad caused is lifted before the result; min gap and one ad at a time.
- 04: the game over flow: a death with an interstitial due shows the death
  screen, Restart plays one interstitial (never while playing) and starts
  the next run.
- 05: rewarded results: {success:true} -> 'rewarded', {success:false} ->
  'closed', throw / rejection / never settles -> 'failed', no reward()
  -> 'unavailable' (free go back).
- 06: the go-back dialog: 'rewarded', 'failed' and a never-settling ad (the
  menu's 30 s timeout, shortened) go back; 'closed' keeps falling; muted
  while the ad is up.
- 07: no SDK (empty script): boots to play, environment 'disabled', no ads,
  free go back.
- 08: throwing SDK (every function throws; and a GamePix whose every
  property read throws): boots to play.
- 09: the real SDK script (fetched live through the route; skipped when the
  host cannot fetch it): boots to play with 0 uncaught errors. Writes
  real-sdk.log.
Every test asserts 0 uncaught errors, 0 unhandled rejections, 0 console
errors and 0 blocked requests.

GAMEPIX_BACKEND_EVIDENCE_DIR=DIR writes gamepix-backend.json, real-sdk.log
and gamepix-boot.png.

    python3 tools/test_gamepix_backend.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from game_harness import READY
from test_go_back import SETUP, CANDIDATES, CATCH, AFTER
from test_go_back_dialog import START, FALL, HOOKS

from build_release import GENERATED_FILES, BUNDLE_NAME, bundle_parts, bundle_path, stale_parts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ZIP = Path(os.environ.get('GAMEPIX_ZIP') or
           ROOT / 'artifacts' / 'release-grapple-over' / 'gamepix' / 'grapple-over-gamepix.zip')
SDK_URL = 'https://integration.gamepix.com/sdk/v3/gamepix.sdk.js'
SDK_TAG = '<script src="%s"></script>' % SDK_URL
BACKEND_TAG = '<script src = "platform/backends/gamepix.js"></script>'
GAME_BASE = 'https://gamepix-local.test/grapple-over/'
GAME_URL = GAME_BASE + 'index.html'
# Rewritten by the build, plus the files it generates (build-time bakes, no committed blob)
REWRITTEN = {'index.html', 'buildconfig.js'} | set(GENERATED_FILES)

CONTENT_TYPES = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
                 '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
                 '.webp': 'image/webp', '.jpg': 'image/jpeg', '.woff2': 'font/woff2'}

INIT = r'''(() => {
    window.__errors = []
    addEventListener('error', e => __errors.push('error: ' + (e.message || e.type)))
    addEventListener('unhandledrejection', e => __errors.push('unhandledrejection: ' +
        (e.reason && e.reason.message || String(e.reason))))
})()'''

# Recording fake of the GamePix SDK v3 surface the backend uses. Ad modes
# (F.interstitial / F.reward): success, fail ({success:false}), throw,
# reject, never, pauseNever (pause, never settles), pauseResumeNever (pause,
# resume, never settles), resolveFirst (resolves, then a late resume). With
# F.adPauses the SDK sends 'pause' before and 'resume' after a normal ad.
FAKE_SDK = r'''(() => {
    const F = window.__fakeGamePix = {calls: [], handlers: {}, interstitial: 'success', reward: 'success',
        adPauses: false, lang: window.__fakeLang || 'en'}
    const rec = (name, arg) => F.calls.push(arg === undefined ? {name} : {name, arg})
    function fire(name) {
        rec('event:' + name)
        for (const fn of (F.handlers[name] || []).slice()) fn(null)
    }
    F.fire = fire
    function answer(kind) {
        const mode = F[kind]
        if (mode === 'throw') throw new Error('fake ' + kind + ' throw')
        if (mode === 'reject') return Promise.reject(new Error('fake ' + kind + ' rejected'))
        if (mode === 'never') return new Promise(() => {})
        if (mode === 'pauseNever') { fire('pause'); return new Promise(() => {}) }
        if (mode === 'pauseResumeNever') {
            fire('pause'); setTimeout(() => fire('resume'), 50); return new Promise(() => {})
        }
        if (mode === 'resolveFirst') {
            fire('pause'); setTimeout(() => fire('resume'), 80)
            return new Promise(r => setTimeout(() => r({success: true}), 20))
        }
        if (F.adPauses) fire('pause')
        return new Promise(r => setTimeout(() => {
            if (F.adPauses) fire('resume')
            r(mode === 'success' ? {success: true} : {success: false})
        }, 30))
    }
    window.GamePix = {
        lang() { rec('lang'); return F.lang },
        lifecycle: {
            loading(n) { rec('loading', n) },
            loaded() { rec('loaded'); return Promise.resolve({}) },
            gameStart() { rec('gameStart'); return true }
        },
        ads: {
            interstitial() { rec('ads.interstitial'); return answer('interstitial') },
            reward() { rec('ads.reward'); return answer('reward') }
        },
        events: {
            on(name, fn) { rec('events.on', name); (F.handlers[name] = F.handlers[name] || []).push(fn); return () => {} },
            off() {}
        },
        happyMoment() { rec('happyMoment') }
    }
})()'''

# Every SDK function throws (the object shape is right)
THROWING_SDK = r'''(() => {
    const boom = name => () => { throw new Error('fake GamePix ' + name + ' throws') }
    window.GamePix = {
        lang: boom('lang'),
        lifecycle: {loading: boom('loading'), loaded: boom('loaded'), gameStart: boom('gameStart')},
        ads: {interstitial: boom('interstitial'), reward: boom('reward')},
        events: {on: boom('events.on')},
        happyMoment: boom('happyMoment')
    }
})()'''

# Every property read throws
PROXY_SDK = r'''window.GamePix = new Proxy({}, {get(t, k) { throw new Error('fake GamePix getter ' + String(k)) }})'''

SDKS = {'fake': FAKE_SDK, 'none': '', 'throwing': THROWING_SDK, 'proxy': PROXY_SDK}

STATE = '''() => ({paused: menu.gamePaused, hostPaused, muted: GAME_AUDIO.muted,
    reasons: [...GAME_AUDIO.reasons].sort(), elapsed: floors[0].climbStats.elapsedActiveMs,
    adOpen, interstitialPending, offer: continueOffer.visible, runInProgress})'''

CALLS = '() => window.__fakeGamePix.calls.map(c => c.name)'


class GamePixBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        if not ZIP.is_file():
            raise unittest.SkipTest('no gamepix zip: run tools/build_release.py --portal gamepix')
        cls.tmp = cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='gamepix-zip-'))
        with zipfile.ZipFile(ZIP) as z:
            cls.names = sorted(z.namelist())
            z.extractall(cls.tmp)
        cls.files = {n: (Path(cls.tmp) / n).read_bytes() for n in cls.names if not n.endswith('/')}
        _, cls.browser = start_browser_test(Path(cls.tmp), cls.stack.callback)
        cls.evidence = {'zip': str(ZIP.relative_to(ROOT) if ZIP.is_relative_to(ROOT) else ZIP),
                        'files': len(cls.files), 'unhandled_rejections': 0, 'uncaught_errors': 0,
                        'ad_before_loaded': []}
        cls.out = os.environ.get('GAMEPIX_BACKEND_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            Path(cls.out, 'gamepix-backend.json').write_text(
                json.dumps(cls.evidence, indent=1, sort_keys=True) + '\n')
        cls.stack.close()

    # -- page --------------------------------------------------------------

    def serve(self, route):
        url = route.request.url
        if url == SDK_URL:
            self.sdk_requests += 1
            if self.sdk == 'real':
                try:
                    response = route.fetch(timeout=30000)
                    body = response.body()
                except Exception as e:  # the host cannot reach GamePix
                    self.real_fetch = {'error': str(e)}
                    return route.abort()
                self.real_fetch = {'status': response.status, 'bytes': len(body),
                                   'sha256': hashlib.sha256(body).hexdigest()}
                return route.fulfill(status=response.status, body=body,
                                     content_type='application/javascript')
            return route.fulfill(body=SDKS[self.sdk], content_type='application/javascript')
        if url.startswith(GAME_BASE):
            name = url[len(GAME_BASE):].split('?')[0].split('#')[0] or 'index.html'
            if name in self.files:
                return route.fulfill(body=self.files[name],
                                     content_type=CONTENT_TYPES.get(Path(name).suffix, 'application/octet-stream'))
            self.missing.append(name)
            return route.fulfill(status=404, body='')
        self.blocked.append(url)
        return route.abort()

    def open(self, sdk='fake', lang='en', setup=None):
        """New context with the game page and `sdk`; returns the page once a run is in play."""
        self.sdk = sdk
        self.sdk_requests = 0
        self.real_fetch = None
        self.blocked, self.missing = [], []
        self.page_errors, self.console_errors, self.console = [], [], []
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        context.add_init_script(INIT)
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
        self.addCleanup(self.assert_clean, page)
        if sdk == 'fake':
            page.add_init_script('window.__fakeLang = %s' % json.dumps(lang))
        started = time.monotonic()
        page.goto(GAME_URL)
        page.wait_for_function(READY, timeout=30000)
        self.boot_s = round(time.monotonic() - started, 2)
        self.assertEqual(self.sdk_requests, 1)
        return page

    def assert_clean(self, page):
        frames = page.evaluate('() => window.__errors || []')
        errors = {'page': self.page_errors, 'console': self.console_errors,
                  'frames': frames, 'blocked': self.blocked, 'missing': self.missing}
        self.evidence.setdefault('errors', {})[self._testMethodName] = {k: len(v) for k, v in errors.items()}
        type(self).evidence['unhandled_rejections'] += sum('unhandledrejection' in e for e in frames)
        type(self).evidence['uncaught_errors'] += len(self.page_errors) + sum(e.startswith('error') for e in frames)
        if self.sdk == 'fake':
            calls = page.evaluate(CALLS)
            first_ad = next((i for i, c in enumerate(calls) if c.startswith('ads.')), None)
            if first_ad is not None and 'loaded' not in calls[:first_ad]:
                self.evidence['ad_before_loaded'].append(self._testMethodName)
            self.assertFalse(first_ad is not None and 'loaded' not in calls[:first_ad],
                             'an ad call before lifecycle.loaded(): %s' % calls)
        self.assertEqual(errors, {'page': [], 'console': [], 'frames': [], 'blocked': [], 'missing': []})

    def fake(self, page, **modes):
        page.evaluate('m => Object.assign(window.__fakeGamePix, m)', modes)

    def calls(self, page):
        return page.evaluate(CALLS)

    def wait_unpaused_run(self, page):
        page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        page.wait_for_function('() => !menu.gamePaused && runInProgress', timeout=10000)

    # -- tests -------------------------------------------------------------

    def test_00_zip_is_current(self):
        # TASK-893: the game scripts are one bundle; its parts are checked by their source sha
        stale = [n for n, b in self.files.items()
                 if n not in REWRITTEN and not BUNDLE_NAME.match(n)
                 and (not (ROOT / n).is_file() or (ROOT / n).read_bytes() != b)]
        stale += stale_parts(self.files, lambda p: (ROOT / p).read_bytes() if (ROOT / p).is_file() else None)
        parts = bundle_parts(self.files)
        bundle_tag = '<script src = "%s"></script>' % bundle_path(self.files)
        self.assertEqual(stale, [], 'zip is stale: rebuild with tools/build_release.py --portal gamepix')
        html = self.files['index.html'].decode()
        self.assertEqual([n for n in parts if n.startswith('platform/backends/')],
                         ['platform/backends/local.js', 'platform/backends/gamepix.js'])
        self.assertEqual(html.count('platform/backends/'), 0)
        self.assertEqual(html.count(SDK_URL), 1)
        # the SDK tag sits right before the bundle (it was right before the backend tag before TASK-893)
        sdk_at, bundle_at = html.index(SDK_TAG), html.index(bundle_tag)
        self.assertLess(sdk_at, bundle_at)
        self.assertEqual(html[sdk_at + len(SDK_TAG):bundle_at].strip(), '')
        self.assertIn('analytics/backends/none.js', parts)
        self.assertNotIn('gameanalytics', html.lower())
        config = parts['buildconfig.js'].decode()
        self.assertIn("platform: 'gamepix'", config)
        self.assertIn("modes: ['grapple_over']", config)
        source = parts['platform/backends/gamepix.js'].decode()
        code = '\n'.join(l for l in source.splitlines() if not l.strip().startswith('//'))
        self.assertNotIn('LOCAL_PLATFORM_BACKEND', code)
        self.assertNotIn('base.', code)
        self.assertNotIn('REPLACE', source)
        self.evidence['zip_current'] = {'stale': stale, 'gamepix_js_bytes': len(source)}

    def test_01_lifecycle(self):
        page = self.open(lang='de')
        boot = page.evaluate('''() => ({calls: window.__fakeGamePix.calls, platformId: PLATFORM.getPlatformId(),
            environment: PLATFORM.environment, language: PLATFORM.language, version, modes: BUILD_CONFIG.modes,
            readiness: PLATFORM_BACKEND.readiness(), interstitial: PLATFORM.isInterstitialSupported(),
            rewarded: PLATFORM.isRewardedSupported(), audio: PLATFORM.isAudioEnabled()})''')
        calls = [c['name'] for c in boot['calls']]
        loading = [c['arg'] for c in boot['calls'] if c['name'] == 'loading']
        self.assertEqual([boot['platformId'], boot['environment']], ['gamepix', 'gamepix'])
        self.assertEqual(boot['version'], 'grapple_over')
        self.assertEqual(boot['modes'], ['grapple_over'])
        self.assertEqual(boot['readiness'], {'state': 'success'})
        self.assertTrue(boot['interstitial'] and boot['rewarded'] and boot['audio'])
        self.assertTrue(loading and all(isinstance(n, int) and 0 <= n <= 100 for n in loading), loading)
        self.assertEqual(loading, sorted(loading))
        self.assertEqual(loading[-1], 100)
        self.assertEqual(loading[0], 0)
        self.assertEqual(calls.count('loaded'), 1, calls)
        self.assertEqual(calls.count('gameStart'), 1, calls)
        last_loading = max(i for i, c in enumerate(calls) if c == 'loading')
        self.assertLess(last_loading, calls.index('loaded'))
        self.assertLess(calls.index('loaded'), calls.index('gameStart'))
        self.assertIn('lang', calls)
        self.assertEqual(sorted(c['arg'] for c in boot['calls'] if c['name'] == 'events.on'), ['pause', 'resume'])
        # More run starts (resume from pause, restart) never send gameStart again
        self.wait_unpaused_run(page)
        page.evaluate('() => { menu.startPause(); menu.unPause() }')
        page.evaluate('() => { PLATFORM.gameplayStart("grapple_over"); PLATFORM.loadingProgress(40); PLATFORM.gameReady() }')
        after = self.calls(page)
        self.assertEqual(after.count('gameStart'), 1)
        self.assertEqual(after.count('loaded'), 1)
        self.assertEqual(after.count('loading'), calls.count('loading'))
        self.assertEqual(page.evaluate('[PLATFORM.language, PLATFORM.getLanguage()]'), ['de', 'de'])
        if self.out:
            Path(self.out).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(self.out) / 'gamepix-boot.png'))
        self.evidence['lifecycle'] = {'calls': calls, 'loading': loading, 'after_more_starts': after,
                                      'language_de': 'de', 'boot_s': self.boot_s,
                                      **{k: boot[k] for k in ('platformId', 'environment', 'readiness', 'modes')}}

    def test_02_pause_resume(self):
        page = self.open()
        self.wait_unpaused_run(page)
        running = page.evaluate(STATE)
        self.assertFalse(running['paused'] or running['hostPaused'] or running['muted'])
        page.evaluate('window.__fakeGamePix.fire("pause")')
        paused = page.evaluate(STATE)
        self.assertTrue(paused['paused'] and paused['hostPaused'] and paused['muted'], paused)
        self.assertEqual(paused['reasons'], ['host'])
        self.assertFalse(page.evaluate('PLATFORM.isAudioEnabled()'))
        # A repeated pause is folded; the player cannot resume while it holds
        page.evaluate('window.__fakeGamePix.fire("pause")')
        page.evaluate('menu.unPause()')
        page.wait_for_timeout(300)
        held = page.evaluate(STATE)
        self.assertTrue(held['paused'] and held['muted'])
        self.assertEqual(held['elapsed'], paused['elapsed'])
        page.evaluate('window.__fakeGamePix.fire("resume")')
        resumed = page.evaluate(STATE)
        self.assertFalse(resumed['hostPaused'] or resumed['muted'], resumed)
        self.assertEqual(resumed['reasons'], [])
        self.assertTrue(page.evaluate('PLATFORM.isAudioEnabled()'))
        page.evaluate('menu.unPause()')
        page.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 200',
                               arg=resumed['elapsed'], timeout=10000)
        running2 = page.evaluate(STATE)
        self.assertFalse(running2['paused'] or running2['hostPaused'] or running2['muted'])
        self.evidence['pause'] = {'running': running, 'paused': paused, 'held': held,
                                  'resumed': resumed, 'running_again': running2}

    def interstitial(self, page, mode, **extra):
        """PLATFORM.showInterstitial at a natural break with the fake in mode."""
        self.fake(page, interstitial=mode, **extra)
        return page.evaluate('''async () => {
            const before = window.__fakeGamePix.calls.length, states = []
            PLATFORM.onAdState(s => states.push(s))
            PLATFORM.onPause(p => states.push(p ? 'pause' : 'resume'))
            PLATFORM_BACKEND.gameplayStop('death')
            const t0 = performance.now()
            const result = await PLATFORM.showInterstitial('game_over')
            const ms = Math.round(performance.now() - t0)
            return {result, ms, states, hostPaused, calls: window.__fakeGamePix.calls.slice(before).map(c => c.name)}
        }''')

    def test_03_interstitial(self):
        page = self.open()
        self.wait_unpaused_run(page)
        # Shorter timeouts and no min gap, so each case runs at once
        page.evaluate('''() => { PLATFORM.interstitialMinGapMs = 0
            Object.assign(PLATFORM_BACKEND, {adOpenTimeoutMs: 400, adResumeGraceMs: 300}) }''')
        # A run in play: refused without an SDK call
        playing = page.evaluate('''async () => { PLATFORM.gameplayStart('grapple_over')
            const n = window.__fakeGamePix.calls.length
            const result = await PLATFORM.showInterstitial('game_over')
            return {result, calls: window.__fakeGamePix.calls.slice(n).map(c => c.name)} }''')
        self.assertEqual(playing, {'result': 'skipped', 'calls': []})
        rows = {}
        expect = {'success': 'closed', 'fail': 'failed', 'throw': 'failed', 'reject': 'failed',
                  'resolveFirst': 'closed', 'never': 'failed', 'pauseNever': None, 'pauseResumeNever': 'failed'}
        prepare = '''() => { PLATFORM.interstitialMinGapMs = 0
            Object.assign(PLATFORM_BACKEND, {adOpenTimeoutMs: 400, adResumeGraceMs: 300}) }'''
        for mode, result in expect.items():
            if mode == 'pauseNever':
                continue
            if 'ever' in mode:
                # A never-settling interstitial stays in flight for good
                # (no later interstitial), so each gets a fresh page
                page = self.open()
                page.evaluate(prepare)
            row = rows[mode] = self.interstitial(page, mode)
            self.assertEqual(row['result'], result, (mode, row))
            self.assertEqual(row['calls'].count('ads.interstitial'), 1, (mode, row))
            self.assertEqual(row['states'][0], 'opened', (mode, row))
            self.assertFalse(row['hostPaused'], (mode, row))
            page.wait_for_timeout(150)  # let a late resume land
        self.assertLess(rows['never']['ms'], 1500)
        self.assertGreaterEqual(rows['never']['ms'], 350)
        self.assertLess(rows['pauseResumeNever']['ms'], 1500)
        # The ad's pause is lifted before the result resolves
        for mode in ('pauseResumeNever', 'resolveFirst'):
            states = rows[mode]['states']
            self.assertIn('pause', states)
            self.assertEqual(states[-2:], ['resume', 'closed' if mode == 'resolveFirst' else 'failed'], states)
        page = self.open()
        page.evaluate(prepare)
        rows['ad_pauses'] = row = self.interstitial(page, 'success', adPauses=True)
        self.assertEqual(row['result'], 'closed')
        self.assertEqual(row['states'][:2], ['opened', 'pause'])
        self.assertEqual(row['states'][-1], 'closed')
        self.assertIn('resume', row['states'])
        # Min gap and one ad in flight: a pending interstitial blocks the next
        gap = page.evaluate('''async () => {
            PLATFORM.interstitialMinGapMs = 60000
            Object.assign(window.__fakeGamePix, {interstitial: 'success'})
            PLATFORM_BACKEND.gameplayStop('death')
            const due = PLATFORM.isInterstitialDue()
            return {due, afterRecent: PLATFORM.isInterstitialDue()} }''')
        self.assertFalse(gap['due'], 'the last interstitial was just now')
        inflight = page.evaluate('''async () => {
            PLATFORM.interstitialMinGapMs = 0
            window.__fakeGamePix.interstitial = 'never'
            const n = window.__fakeGamePix.calls.length
            const first = PLATFORM.showInterstitial('game_over')
            const second = await PLATFORM.showInterstitial('game_over')
            const firstResult = await first
            const due = PLATFORM.isInterstitialDue()
            return {firstResult, second, due, calls: window.__fakeGamePix.calls.slice(n).map(c => c.name)} }''')
        # The first never settles: it times out, and stays in flight
        self.assertEqual(inflight['firstResult'], 'failed')
        self.assertEqual(inflight['second'], 'skipped')
        self.assertFalse(inflight['due'])
        self.assertEqual(inflight['calls'], ['ads.interstitial'])
        self.evidence['interstitial'] = {'while_playing': playing, 'modes': {k: {x: v[x] for x in ('result', 'states', 'calls')}
                                                                           for k, v in rows.items()},
                                         'min_gap': gap, 'in_flight': inflight}

    def test_04_game_over_flow(self):
        page = self.open()
        self.wait_unpaused_run(page)
        page.evaluate('PLATFORM.interstitialMinGapMs = 0')
        n = len(self.calls(page))
        page.evaluate('''() => { ninja.isInvulnerable = () => false; onLethalDeath() }''')
        dead = page.evaluate(STATE)
        self.assertTrue(dead['offer'], dead)
        self.assertEqual(self.calls(page)[n:], [], 'no ad while the death screen opens')
        # Restart: the interstitial plays, then the next run starts
        page.evaluate('restartFromOffer()')
        pending = page.evaluate(STATE)
        self.assertTrue(pending['interstitialPending'], pending)
        page.wait_for_function('() => !interstitialPending && runInProgress && !continueOffer.visible', timeout=10000)
        after = self.calls(page)[n:]
        self.assertEqual(after.count('ads.interstitial'), 1, after)
        # Playing again: the next showInterstitial is refused
        self.wait_unpaused_run(page)
        refused = page.evaluate('PLATFORM.showInterstitial("game_over")')
        self.assertEqual(refused, 'skipped')
        self.assertEqual(self.calls(page)[n:].count('ads.interstitial'), 1)
        self.evidence['game_over'] = {'dead': dead, 'pending': pending, 'calls': after, 'while_playing': refused}

    def rewarded(self, page, mode, **extra):
        self.fake(page, reward=mode, **extra)
        return page.evaluate('''async () => {
            const n = window.__fakeGamePix.calls.length, states = []
            PLATFORM.onAdState(s => states.push(s))
            const supported = PLATFORM.isRewardedSupported()
            const result = await PLATFORM.showRewarded('go_back')
            return {supported, result, states, hostPaused,
                    calls: window.__fakeGamePix.calls.slice(n).map(c => c.name)} }''')

    def test_05_rewarded_results(self):
        page = self.open()
        page.evaluate('Object.assign(PLATFORM_BACKEND, {adOpenTimeoutMs: 400, adResumeGraceMs: 300})')
        expect = {'success': 'rewarded', 'fail': 'closed', 'throw': 'failed', 'reject': 'failed',
                  'never': 'failed', 'pauseResumeNever': 'failed'}
        rows = {}
        for mode, result in expect.items():
            row = rows[mode] = self.rewarded(page, mode)
            self.assertTrue(row['supported'])
            self.assertEqual(row['result'], result, (mode, row))
            self.assertEqual(row['calls'].count('ads.reward'), 1, (mode, row))
            self.assertFalse(row['hostPaused'], (mode, row))
            page.wait_for_timeout(150)
        rows['ad_pauses'] = row = self.rewarded(page, 'success', adPauses=True)
        self.assertEqual(row['result'], 'rewarded')
        self.assertFalse(row['hostPaused'])
        # No reward() in the SDK: unavailable, Go back is free
        unavailable = page.evaluate('''async () => { delete window.GamePix.ads.reward
            return {supported: PLATFORM.isRewardedSupported(), result: await PLATFORM.showRewarded('go_back')} }''')
        self.assertEqual(unavailable, {'supported': False, 'result': 'unavailable'})
        rows['unavailable'] = unavailable
        self.evidence['rewarded'] = rows

    def go_back(self, mode, ad_timeout_ms=None):
        """The go-back dialog with the fake reward in mode; returns the outcome."""
        page = self.open()
        page.evaluate(SETUP)
        page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        page.evaluate(HOOKS)
        page.evaluate('Object.assign(PLATFORM_BACKEND, {adOpenTimeoutMs: 400, adResumeGraceMs: 300})')
        if ad_timeout_ms:
            page.evaluate('ms => { CLIMB_UI.goBackAdTimeoutMs = ms; PLATFORM_BACKEND.adOpenTimeoutMs = 60000 }',
                          ad_timeout_ms)
        page.evaluate('''() => { window.MUTED_SEEN = false; const mute = GAME_AUDIO.mute
            GAME_AUDIO.mute = function(r, on) { if (on && r === 'ad') MUTED_SEEN = true; return mute.call(this, r, on) } }''')
        self.fake(page, reward=mode, adPauses=True)
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

    def test_06_go_back_dialog(self):
        rows = []
        for mode, back, timeout in (('success', True, None), ('fail', False, None),
                                    ('throw', True, None), ('never', True, 800)):
            row = self.go_back(mode, timeout)
            rows.append(row)
            self.assertEqual(row['marker'], 1, row)
            self.assertEqual(row['back'], back, row)
            self.assertEqual(row['calls'].count('ads.reward'), 1, row)
            self.assertTrue(row['mutedSeen'], row)
            self.assertFalse(row['muted'] or row['hostPaused'], row)
        self.evidence['go_back'] = rows

    def boots_without_working_sdk(self, sdk):
        page = self.open(sdk=sdk)
        self.wait_unpaused_run(page)
        start = page.evaluate('floors[0].climbStats.elapsedActiveMs')
        page.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 300', arg=start, timeout=10000)
        row = page.evaluate('''async () => ({platformId: PLATFORM.getPlatformId(), environment: PLATFORM.environment,
            readiness: PLATFORM_BACKEND.readiness(), language: PLATFORM.language,
            interstitial: PLATFORM.isInterstitialSupported(), due: PLATFORM.isInterstitialDue(),
            rewarded: PLATFORM.isRewardedSupported(),
            show: (PLATFORM_BACKEND.gameplayStop('death'), await PLATFORM.showInterstitial('game_over')),
            reward: await PLATFORM.showRewarded('go_back'), ready: await PLATFORM.gameReady(),
            happy: PLATFORM.happyMoment(), saved: await PLATFORM.storage.setMany({'grapnelninja.gpxProbe': 'v'}),
            read: await PLATFORM.storage.getMany(['grapnelninja.gpxProbe'])})''')
        self.assertEqual(row['platformId'], 'gamepix')
        self.assertTrue(row['saved'])
        self.assertEqual(row['read'], {'grapnelninja.gpxProbe': 'v'})
        row['boot_s'] = self.boot_s
        row['warnings'] = [c for c in self.console if c.startswith('warning')]
        return row

    def test_07_no_sdk_boots(self):
        row = self.boots_without_working_sdk('none')
        self.assertEqual(row['environment'], 'disabled')
        self.assertEqual(row['readiness'], {'state': 'disabled'})
        self.assertFalse(row['interstitial'] or row['due'] or row['rewarded'])
        self.assertEqual([row['show'], row['reward']], ['skipped', 'unavailable'])
        self.evidence['no_sdk'] = row

    def test_08_throwing_sdk_boots(self):
        rows = {}
        for sdk in ('throwing', 'proxy'):
            row = rows[sdk] = self.boots_without_working_sdk(sdk)
            self.assertEqual(row['language'], 'en')
            self.assertIn(row['reward'], ('failed', 'unavailable'))
            self.assertIn(row['show'], ('failed', 'skipped'))
        self.assertEqual(rows['throwing']['reward'], 'failed')
        self.evidence['throwing_sdk'] = rows

    def test_09_real_sdk_smoke(self):
        self.sdk = 'real'
        try:
            page = self.open(sdk='real')
        except Exception:
            if self.real_fetch and 'error' in self.real_fetch:
                self.write_real_log(None)
                self.skipTest('the real GamePix SDK could not be fetched: %s' % self.real_fetch['error'])
            raise
        self.wait_unpaused_run(page)
        start = page.evaluate('floors[0].climbStats.elapsedActiveMs')
        page.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 500', arg=start, timeout=10000)
        row = page.evaluate('''() => ({platformId: PLATFORM.getPlatformId(), environment: PLATFORM.environment,
            readiness: PLATFORM_BACKEND.readiness(), language: PLATFORM.language, version,
            sdk: {lifecycle: Object.keys(GamePix.lifecycle || {}), ads: Object.keys(GamePix.ads || {}),
                  events: Object.keys(GamePix.events || {})},
            interstitial: PLATFORM.isInterstitialSupported(), rewarded: PLATFORM.isRewardedSupported(),
            running: !menu.gamePaused && runInProgress, hostPaused, errors: window.__errors})''')
        self.assertEqual(row['environment'], 'gamepix')
        self.assertTrue(row['running'], row)
        self.assertEqual(row['errors'], [])
        self.assertEqual(self.real_fetch['status'], 200)
        row['fetch'] = self.real_fetch
        row['boot_s'] = self.boot_s
        self.evidence['real_sdk'] = row
        self.write_real_log(row)

    def write_real_log(self, row):
        if not self.out:
            return
        Path(self.out).mkdir(parents=True, exist_ok=True)
        lines = ['real GamePix SDK smoke (tools/test_gamepix_backend.py test_09)',
                 'sdk url: ' + SDK_URL, 'page: ' + GAME_URL + ' (blank local origin, gamepix zip %s)' % self.evidence['zip'],
                 'fetch: ' + json.dumps(self.real_fetch, sort_keys=True), '--- console ---'] + self.console
        lines += ['--- page errors ---'] + (self.page_errors or ['(none)'])
        if row is None:
            lines.append('RESULT: SKIPPED (SDK not fetchable from this host; the fake-SDK suite counts)')
        else:
            lines += ['--- state ---', json.dumps(row, sort_keys=True),
                      'uncaught errors: %d' % (len(self.page_errors) + len(row['errors'])),
                      'console errors: %d' % len(self.console_errors),
                      'blocked requests: %d' % len(self.blocked),
                      'RESULT: %s' % ('PASS boots to play with the real SDK' if row['running'] and not self.page_errors
                                      and not row['errors'] else 'FAIL')]
        Path(self.out, 'real-sdk.log').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    unittest.main()
