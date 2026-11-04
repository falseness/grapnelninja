"""TASK-859: the Playgama build (platform/backends/playgama.js, Playgama Bridge v2).

Loads the built playgama zip (artifacts/release-grapple-over/playgama/
grapple-over-playgama.zip, or PLAYGAMA_ZIP) from a blank local origin
(https://grapple-over-local.test/playgama/, served by Playwright routes).
The zip's SDK tag (https://bridge.playgama.com/v2/stable/playgama-bridge.js)
is NEVER fetched: Playwright answers it in-process with a FAKE bridge, built
on tools/game_harness.py LOCAL_BRIDGE (storage in the page's localStorage)
plus a recorder (window.__fakeBridge.calls, in order) and switchable modes.
Every other non-local request is aborted and recorded; every requested URL
is recorded (network-hosts.txt). No Playgama-hosted page is ever loaded.

- 00: the zip is current (every shipped file except the rewritten
  index.html/buildconfig.js equals the working tree), every mode, the SDK
  tag right before the playgama.js tag, analytics none.js, the bridge config
  file shipped, playgama.js self-contained.
- 01: boot order: initialize() is the first bridge call and nothing else
  touches the bridge before it resolves; game_ready exactly once, after the
  first playable frame (boot complete, loading hidden, a run in play);
  lifecycle messages (level_started, gameplay_started) only after
  game_ready, in order; startup_funnel via bridge.analytics.send only; more
  run starts never resend game_ready; the language comes from the bridge.
- 02: PAUSE_STATE_CHANGED pauses and mutes (the player cannot resume while
  it holds), false unmutes and lifts the hold; AUDIO_STATE_CHANGED false
  mutes without pausing, true restores; audio off survives a pause cycle.
- 03: interstitial: 'skipped' (no SDK call) while a run is in play; at a
  break 'closed' / 'failed' states, a throw and a rejection map to
  'closed' / 'failed' / 'failed' / 'failed'; an ad that never opens ->
  'failed' after adOpenTimeoutMs and stays in flight (the next one is
  'skipped'); min gap; adState opened/closed around the ad.
- 04: the game over flow: a death with an interstitial due shows the death
  screen without an ad; Restart plays one interstitial, then the next run.
- 05: rewarded results as docs/platform-sdk.md says: 'rewarded' then
  'closed' -> 'rewarded'; 'closed' alone -> 'closed'; 'failed', a throw, a
  rejection, never answering -> 'failed'; unsupported -> 'unavailable'.
- 06: save compatibility: a save in the release-20261014 format (keys in
  artifacts/TASK-859/save-format.md) is read by the new build, through the
  plain LOCAL_BRIDGE and through a bridge that JSON-parses values on get
  like the real SDK; the next write keeps the format; saves survive reload.
- 07: broken bridges still boot to play: none, initialize never settles,
  initialize rejects, every call throws, every property read throws,
  storage.get never settles (no write before the read; a late answer is
  reconciled), sendMessage never settles.
Every test asserts 0 uncaught errors, 0 unhandled rejections, 0 console
errors, 0 blocked and 0 missing requests.

PLAYGAMA_BACKEND_EVIDENCE_DIR=DIR writes playgama-backend.json,
network-hosts.txt and playgama-boot.png.

    python3 tools/test_playgama_backend.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from urllib.parse import urlparse
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from game_harness import READY, LOCAL_BRIDGE

from build_release import GENERATED_FILES, BUNDLE_NAME, bundle_parts, bundle_path, stale_parts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ZIP = Path(os.environ.get('PLAYGAMA_ZIP') or
           ROOT / 'artifacts' / 'release-grapple-over' / 'playgama' / 'grapple-over-playgama.zip')
BASELINE_ZIP = ROOT / 'artifacts' / 'release-20261014' / 'grapnelninja-playgama.zip'
SDK_URL = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'
SDK_TAG = '<script src="%s"></script>' % SDK_URL
BACKEND_TAG = '<script src = "platform/backends/playgama.js"></script>'
GAME_BASE = 'https://grapple-over-local.test/playgama/'
GAME_URL = GAME_BASE + 'index.html'
# Rewritten by the build, plus the files it generates (build-time bakes, no committed blob)
REWRITTEN = {'index.html', 'buildconfig.js'} | set(GENERATED_FILES)
ALL_MODES = ['grapple_over', 'bad', 'classic']

CONTENT_TYPES = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
                 '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
                 '.webp': 'image/webp', '.jpg': 'image/jpeg', '.woff2': 'font/woff2'}

INIT = r'''(() => {
    window.__errors = []
    addEventListener('error', e => __errors.push('error: ' + (e.message || e.type)))
    addEventListener('unhandledrejection', e => __errors.push('unhandledrejection: ' +
        (e.reason && e.reason.message || String(e.reason))))
})()'''

# LOCAL_BRIDGE (game_harness.py) wrapped in a recorder. window.__fakeBridge:
#   calls: [{name, arg?, t, state?}] in order ('initialize', 'initialize:resolved',
#     'platform.on', 'platform.sendMessage', 'advertisement.on/off/showInterstitial/
#     showRewarded', 'storage.get/set', 'analytics.send')
#   emit(event, value): fires bridge listeners (platform and advertisement)
#   modes: initialize ('ok' | 'never' | 'reject'), initDelayMs, interstitial /
#     rewarded ad scripts (lists of states, or 'throw' | 'reject' | 'never'),
#     storageGet ('ok' | 'parse' | 'never' | 'late'), lateMs, sendMessage ('ok' | 'never')
# Ad states are emitted asynchronously, 20 ms apart.
FAKE_BRIDGE = LOCAL_BRIDGE + r'''
;(() => {
    const local = window.bridge
    const S = window.__fakeSetup || {}
    const F = window.__fakeBridge = Object.assign({calls: [], handlers: {},
        initialize: 'ok', initDelayMs: 100, interstitial: ['loading', 'opened', 'closed'],
        rewarded: ['loading', 'opened', 'rewarded', 'closed'], storageGet: 'ok', lateMs: 2500,
        sendMessage: 'ok', interstitialSupported: true, rewardedSupported: true, audio: true, language: 'de'}, S)
    const rec = (name, arg, extra) => F.calls.push(Object.assign({name, t: Math.round(performance.now())},
        arg === undefined ? {} : {arg}, extra || {}))
    function on(name) {
        return (event, fn) => { rec(name, event); (F.handlers[event] = F.handlers[event] || []).push(fn) }
    }
    F.count = event => (F.handlers[event] || []).length
    F.emit = (event, value) => { rec('emit', [event, value]); (F.handlers[event] || []).slice().forEach(fn => fn(value)) }
    function adPlay(event, script) {
        if (script === 'throw') throw new Error('fake ad throws')
        if (script === 'reject') return Promise.reject(new Error('fake ad rejected'))
        if (script === 'never') return Promise.resolve()
        script.forEach((state, i) => setTimeout(() => {
            F.ads[event] = state
            F.emit(event, state)
        }, 20 * (i + 1)))
        return Promise.resolve()
    }
    F.ads = {}
    const parse = v => { if (v === null || v === undefined || v === '') return null
        try { return JSON.parse(v) } catch (_) { return v } }
    window.bridge = {
        EVENT_NAME: local.EVENT_NAME,
        initialize(options) {
            rec('initialize', options)
            if (F.initialize === 'never') return new Promise(() => {})
            if (F.initialize === 'reject') return Promise.reject(new Error('fake initialize rejected'))
            return new Promise(r => setTimeout(() => { rec('initialize:resolved'); r() }, F.initDelayMs))
        },
        platform: {
            id: 'playgama', get language() { return F.language }, get isAudioEnabled() { return F.audio },
            on: on('platform.on'),
            sendMessage(message, data) {
                rec('platform.sendMessage', data === undefined ? [message] : [message, data],
                    message === 'game_ready' ? {state: {bootComplete: typeof bootComplete !== 'undefined' && bootComplete,
                        loadingHidden: document.getElementById('loading').hidden,
                        runInProgress: typeof runInProgress !== 'undefined' && runInProgress,
                        frames: window.__frames || 0}} : undefined)
                return F.sendMessage === 'never' ? new Promise(() => {}) : Promise.resolve()
            }
        },
        advertisement: {
            get isInterstitialSupported() { return F.interstitialSupported },
            get isRewardedSupported() { return F.rewardedSupported },
            get interstitialState() { return F.ads[local.EVENT_NAME.INTERSTITIAL_STATE_CHANGED] || 'closed' },
            isBannerSupported: false,
            on: on('advertisement.on'),
            off(event, fn) { rec('advertisement.off', event); F.handlers[event] = (F.handlers[event] || []).filter(f => f !== fn) },
            showInterstitial(placement) { rec('advertisement.showInterstitial', placement)
                return adPlay(local.EVENT_NAME.INTERSTITIAL_STATE_CHANGED, F.interstitial) },
            showRewarded(placement) { rec('advertisement.showRewarded', placement)
                return adPlay(local.EVENT_NAME.REWARDED_STATE_CHANGED, F.rewarded) }
        },
        analytics: { send(name, data) { rec('analytics.send', [name, data]) } },
        leaderboards: {type: 'not_available'},
        storage: {
            get(keys) {
                rec('storage.get', keys.slice())
                if (F.storageGet === 'never') return new Promise(() => {})
                const answer = local.storage.get(keys).then(values => F.storageGet === 'parse' ? values.map(parse) : values)
                if (F.storageGet === 'late') return new Promise(r => setTimeout(() => r(answer), F.lateMs))
                return answer
            },
            set(keys, values) { rec('storage.set', [keys.slice(), values.slice()]); return local.storage.set(keys, values) }
        }
    }
})()'''

# Every bridge function throws (the object shape is right)
THROWING_BRIDGE = r'''(() => {
    const boom = name => () => { throw new Error('fake bridge ' + name + ' throws') }
    window.bridge = {
        EVENT_NAME: {PAUSE_STATE_CHANGED: 'pause', AUDIO_STATE_CHANGED: 'audio',
            INTERSTITIAL_STATE_CHANGED: 'interstitial', REWARDED_STATE_CHANGED: 'rewarded'},
        initialize: () => Promise.resolve(),
        platform: {id: 'x', language: 'en', on: boom('platform.on'), sendMessage: boom('sendMessage')},
        advertisement: {isInterstitialSupported: true, isRewardedSupported: true, on: boom('ad.on'),
            off: boom('ad.off'), showInterstitial: boom('showInterstitial'), showRewarded: boom('showRewarded')},
        analytics: {send: boom('analytics.send')},
        storage: {get: boom('storage.get'), set: boom('storage.set')}
    }
})()'''

# Every property read throws
PROXY_BRIDGE = r'''window.bridge = new Proxy({}, {get(t, k) { throw new Error('fake bridge getter ' + String(k)) }})'''

# Counts animation frames (the game's first frames)
FRAMES = r'''(() => { window.__frames = 0
    const raf = window.requestAnimationFrame.bind(window)
    window.requestAnimationFrame = fn => raf(t => { window.__frames++; fn(t) }) })()'''

SDKS = {'fake': FAKE_BRIDGE, 'none': '', 'throwing': THROWING_BRIDGE, 'proxy': PROXY_BRIDGE}

STATE = '''() => ({paused: menu.gamePaused, hostPaused, muted: GAME_AUDIO.muted,
    reasons: [...GAME_AUDIO.reasons].sort(), elapsed: floors[0].climbStats.elapsedActiveMs,
    adOpen, interstitialPending, offer: continueOffer.visible, runInProgress,
    audio: PLATFORM.isAudioEnabled()})'''

CALLS = '() => window.__fakeBridge.calls.map(c => c.name)'
MESSAGES = '''() => window.__fakeBridge.calls.filter(c => c.name === 'platform.sendMessage').map(c => c.arg[0])'''

# The release-20261014 save (keys and value format of its progress.js; see
# artifacts/TASK-859/save-format.md)
BASELINE_SAVE = {
    'grapnelninja.records': '{"classic":42,"bad":7}',
    'grapnelninja.time': '3600',
    'grapnelninja.lang': 'ru',
    'grapnelninja.tutorialDone': 'true',
    'grapnelninja.muted': 'true',
}


class PlaygamaBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        if not ZIP.is_file():
            raise unittest.SkipTest('no playgama zip: run tools/build_release.py --portal playgama')
        cls.tmp = cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='playgama-zip-'))
        with zipfile.ZipFile(ZIP) as z:
            cls.names = sorted(z.namelist())
            z.extractall(cls.tmp)
        cls.files = {n: (Path(cls.tmp) / n).read_bytes() for n in cls.names if not n.endswith('/')}
        _, cls.browser = start_browser_test(Path(cls.tmp), cls.stack.callback)
        cls.evidence = {'zip': str(ZIP.relative_to(ROOT) if ZIP.is_relative_to(ROOT) else ZIP),
                        'files': len(cls.files), 'unhandled_rejections': 0, 'uncaught_errors': 0,
                        'sdk_url_answered_by': 'fake bridge (in-process Playwright route, never fetched)'}
        cls.requests = {}
        cls.out = os.environ.get('PLAYGAMA_BACKEND_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.out:
            out = Path(cls.out)
            out.mkdir(parents=True, exist_ok=True)
            cls.evidence['requests_by_host'] = cls.requests
            (out / 'playgama-backend.json').write_text(json.dumps(cls.evidence, indent=1, sort_keys=True) + '\n')
            lines = ['# unique hosts of every request made by tools/test_playgama_backend.py pages',
                     '# host  requests  disposition']
            for host, row in sorted(cls.requests.items()):
                lines.append('%s  %d  %s' % (host, row['count'], row['disposition']))
            (out / 'network-hosts.txt').write_text('\n'.join(lines) + '\n')
        cls.stack.close()

    # -- page --------------------------------------------------------------

    def note(self, url, disposition):
        host = urlparse(url).netloc or url.split(':')[0]
        row = type(self).requests.setdefault(host, {'count': 0, 'disposition': disposition})
        row['count'] += 1

    def serve(self, route):
        url = route.request.url
        if url == SDK_URL:
            self.sdk_requests += 1
            self.note(url, 'SDK script URL answered in-process with the fake bridge (never reached the network)')
            return route.fulfill(body=SDKS[self.sdk], content_type='application/javascript')
        if url.startswith(GAME_BASE):
            self.note(url, 'local test origin (zip files served by Playwright)')
            name = url[len(GAME_BASE):].split('?')[0].split('#')[0] or 'index.html'
            if name in self.files:
                return route.fulfill(body=self.files[name],
                                     content_type=CONTENT_TYPES.get(Path(name).suffix, 'application/octet-stream'))
            self.missing.append(name)
            return route.fulfill(status=404, body='')
        self.note(url, 'ABORTED (blocked external request)')
        self.blocked.append(url)
        return route.abort()

    def open(self, sdk='fake', setup=None, store=None, ready=True):
        """New context with the game page and `sdk`; returns the page once a run is in play.

        setup: fake modes (window.__fakeSetup) before the bridge loads;
        store: localStorage seeded before the page's scripts run.
        """
        self.sdk = sdk
        self.sdk_requests = 0
        self.blocked, self.missing = [], []
        self.page_errors, self.console_errors, self.console = [], [], []
        # This page's own lists, checked by its cleanup
        mine = {'sdk': sdk, 'blocked': self.blocked, 'missing': self.missing,
                'page_errors': self.page_errors, 'console_errors': self.console_errors}
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        context.add_init_script(INIT)
        context.add_init_script(FRAMES)
        context.add_init_script('window.__fakeSetup = %s' % json.dumps(setup or {}))
        if store is not None:
            context.add_init_script('''(store => { if (sessionStorage.getItem('__seeded')) return
                sessionStorage.setItem('__seeded', '1'); localStorage.clear()
                for (const [k, v] of Object.entries(store)) localStorage.setItem(k, v) })(%s)''' % json.dumps(store))
        context.route('**/*', self.serve)
        page = context.new_page()
        page.on('pageerror', lambda e: self.page_errors.append(str(e)))

        def console(m):
            self.console.append('%s: %s' % (m.type, m.text))
            if m.type == 'error':
                self.console_errors.append(m.text)
        page.on('console', console)
        self.addCleanup(self.assert_clean, page, mine)
        started = time.monotonic()
        page.goto(GAME_URL)
        if ready:
            page.wait_for_function(READY, timeout=30000)
        self.boot_s = round(time.monotonic() - started, 2)
        self.assertEqual(self.sdk_requests, 1)
        return page

    def assert_clean(self, page, mine):
        frames = page.evaluate('() => window.__errors || []')
        errors = {'page': mine['page_errors'], 'console': mine['console_errors'],
                  'frames': frames, 'blocked': mine['blocked'], 'missing': mine['missing']}
        totals = self.evidence.setdefault('errors', {}).setdefault(self._testMethodName, {k: 0 for k in errors})
        for k, v in errors.items():
            totals[k] += len(v)
        type(self).evidence['unhandled_rejections'] += sum('unhandledrejection' in e for e in frames)
        type(self).evidence['uncaught_errors'] += len(mine['page_errors']) + sum(e.startswith('error') for e in frames)
        if mine['sdk'] == 'fake':
            calls = page.evaluate('() => window.__fakeBridge.calls')
            names = [c['name'] for c in calls]
            # initialize is the first bridge call; nothing else before it resolved
            self.assertEqual(names[0], 'initialize', names[:5])
            if 'initialize:resolved' in names:
                early = [n for n in names[1:names.index('initialize:resolved')] if n != 'emit']
                self.assertEqual(early, [], 'bridge calls before initialize() resolved')
            ready = [c for c in calls if c['name'] == 'platform.sendMessage' and c['arg'][0] == 'game_ready']
            self.assertLessEqual(len(ready), 1, 'game_ready sent more than once')
        self.assertEqual(errors, {'page': [], 'console': [], 'frames': [], 'blocked': [], 'missing': []})

    def fake(self, page, **modes):
        page.evaluate('m => Object.assign(window.__fakeBridge, m)', modes)

    def calls(self, page):
        return page.evaluate(CALLS)

    def emit(self, page, key, value):
        page.evaluate('([k, v]) => window.__fakeBridge.emit(bridge.EVENT_NAME[k], v)', [key, value])

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
        self.assertEqual(stale, [], 'zip is stale: rebuild with tools/build_release.py --portal playgama')
        html = self.files['index.html'].decode()
        self.assertEqual([n for n in parts if n.startswith('platform/backends/')],
                         ['platform/backends/local.js', 'platform/backends/playgama.js'])
        self.assertEqual(html.count('platform/backends/'), 0)
        self.assertEqual(html.count(SDK_URL), 1)
        # the SDK tag is the first script of <head> (Bridge required step 2,
        # Playgama 1.1.2); the backend follows local.js
        sdk_at = html.index(SDK_TAG)
        self.assertLess(sdk_at, html.index('</head>'))
        self.assertEqual(sdk_at, html.index('<script'))
        names = list(parts)
        self.assertEqual(names.index('platform/backends/playgama.js'), names.index('platform/backends/local.js') + 1)
        self.assertIn('analytics/backends/none.js', parts)
        self.assertNotIn('gameanalytics', html.lower())
        config = parts['buildconfig.js'].decode()
        self.assertIn("platform: 'playgama'", config)
        self.assertIn("modes: ['grapple_over', 'bad', 'classic']", config)
        self.assertIn('playgama-bridge-config.json', self.files)
        bridge_config = json.loads(self.files['playgama-bridge-config.json'])
        with zipfile.ZipFile(BASELINE_ZIP) as z:
            self.assertEqual(bridge_config, json.loads(z.read('playgama-bridge-config.json')))
        source = parts['platform/backends/playgama.js'].decode()
        code = '\n'.join(l for l in source.splitlines() if not l.strip().startswith('//'))
        self.assertNotIn('LOCAL_PLATFORM_BACKEND', code)
        self.assertNotIn('base.', code)
        self.assertNotIn('REPLACE', source)
        self.assertNotIn('gameanalytics', code.lower())
        self.evidence['zip_current'] = {'stale': stale, 'playgama_js_bytes': len(source),
                                        'bridge_config_equals_release_20261014': True, 'modes': ALL_MODES}

    def test_01_boot_order_and_game_ready(self):
        page = self.open()
        page.wait_for_function('() => window.__fakeBridge.calls.some(c => c.arg && c.arg[0] === "level_started")',
                               timeout=10000)
        boot = page.evaluate('''() => ({calls: window.__fakeBridge.calls, platformId: PLATFORM.getPlatformId(),
            environment: PLATFORM.environment, language: PLATFORM.language, version, modes: BUILD_CONFIG.modes,
            readiness: PLATFORM_BACKEND.readiness(), interstitial: PLATFORM.isInterstitialSupported(),
            rewarded: PLATFORM.isRewardedSupported(), audio: PLATFORM.isAudioEnabled()})''')
        calls = boot['calls']
        names = [c['name'] for c in calls]
        self.assertEqual(names[0], 'initialize')
        self.assertEqual(calls[0]['arg'], {'configFilePath': 'playgama-bridge-config.json', 'disableLoadingLogo': True})
        resolved = names.index('initialize:resolved')
        self.assertEqual([n for n in names[1:resolved] if n != 'emit'], [])
        self.assertEqual([boot['platformId'], boot['environment']], ['playgama', 'playgama'])
        self.assertEqual(boot['version'], 'grapple_over')
        self.assertEqual(boot['modes'], ALL_MODES)
        self.assertEqual(boot['readiness']['state'], 'success')
        self.assertEqual(boot['readiness']['gameReady'], 'success')
        self.assertTrue(boot['interstitial'] and boot['rewarded'] and boot['audio'])
        self.assertEqual(boot['language'], 'de')
        messages = [c for c in calls if c['name'] == 'platform.sendMessage']
        ready = [c for c in messages if c['arg'][0] == 'game_ready']
        self.assertEqual(len(ready), 1)
        state = ready[0]['state']
        self.assertTrue(state['bootComplete'] and state['loadingHidden'] and state['runInProgress'], state)
        self.assertGreaterEqual(state['frames'], 2, 'game_ready before the first playable frame')
        # Lifecycle after game_ready, in order
        order = [c['arg'][0] for c in messages]
        self.assertEqual(order[0], 'game_ready', order)
        self.assertEqual(order[1:3], ['level_started', 'gameplay_started'], order)
        # Telemetry only through bridge.analytics.send, after game_ready
        sends = [c for c in calls if c['name'] == 'analytics.send']
        self.assertTrue(sends and all(c['arg'][0] == 'startup_funnel' for c in sends), sends)
        self.assertGreater(min(calls.index(c) for c in sends), calls.index(ready[0]))
        stages = [c['arg'][1]['stage'] for c in sends]
        self.assertEqual(stages[:2], ['mode_selected', 'run_initialized'])
        self.assertTrue(all(c['arg'][1]['game_version'] for c in sends))
        # Pause/resume, a restart and another gameReady never resend game_ready
        self.wait_unpaused_run(page)
        page.evaluate('() => { menu.startPause(); menu.unPause(); PLATFORM.gameReady(); PLATFORM.gameReady() }')
        page.wait_for_timeout(200)
        after = page.evaluate(MESSAGES)
        self.assertEqual(after.count('game_ready'), 1)
        self.assertIn('level_paused', after)
        self.assertIn('gameplay_stopped', after)
        self.assertEqual(after[-2:], ['level_resumed', 'gameplay_started'], after)
        page.evaluate('() => PLATFORM.track("probe_event", {n: 1})')
        tracked = page.evaluate('() => window.__fakeBridge.calls.filter(c => c.name === "analytics.send").pop().arg')
        self.assertEqual(tracked[0], 'probe_event')
        self.assertEqual(tracked[1]['n'], 1)
        if self.out:
            Path(self.out).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(self.out) / 'playgama-boot.png'))
        self.evidence['boot'] = {'first_calls': names[:12], 'game_ready_state': state, 'messages': after,
                                 'startup_stages': stages, 'boot_s': self.boot_s, 'readiness': boot['readiness'],
                                 'language': boot['language'], 'environment': boot['environment']}

    def test_02_pause_and_audio(self):
        page = self.open()
        self.wait_unpaused_run(page)
        running = page.evaluate(STATE)
        self.assertFalse(running['paused'] or running['hostPaused'] or running['muted'])
        self.emit(page, 'PAUSE_STATE_CHANGED', True)
        paused = page.evaluate(STATE)
        self.assertTrue(paused['paused'] and paused['hostPaused'] and paused['muted'], paused)
        self.assertEqual(paused['reasons'], ['host'])
        # Repeated pause is folded; the player cannot resume while it holds
        self.emit(page, 'PAUSE_STATE_CHANGED', True)
        page.evaluate('menu.unPause()')
        page.wait_for_timeout(300)
        held = page.evaluate(STATE)
        self.assertTrue(held['paused'] and held['muted'])
        self.assertEqual(held['elapsed'], paused['elapsed'])
        self.emit(page, 'PAUSE_STATE_CHANGED', False)
        resumed = page.evaluate(STATE)
        self.assertFalse(resumed['hostPaused'] or resumed['muted'], resumed)
        page.evaluate('menu.unPause()')
        page.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 200',
                               arg=resumed['elapsed'], timeout=10000)
        # Audio off: muted, still playing; survives a pause cycle; on: restored
        self.emit(page, 'AUDIO_STATE_CHANGED', False)
        audio_off = page.evaluate(STATE)
        self.assertTrue(audio_off['muted'] and not audio_off['paused'] and not audio_off['audio'], audio_off)
        page.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 200',
                               arg=audio_off['elapsed'], timeout=10000)
        self.emit(page, 'PAUSE_STATE_CHANGED', True)
        self.emit(page, 'PAUSE_STATE_CHANGED', False)
        still_off = page.evaluate(STATE)
        self.assertTrue(still_off['muted'], still_off)
        self.emit(page, 'AUDIO_STATE_CHANGED', True)
        audio_on = page.evaluate(STATE)
        self.assertFalse(audio_on['muted'], audio_on)
        self.assertTrue(audio_on['audio'])
        page.evaluate('menu.unPause()')
        page.wait_for_function('() => !menu.gamePaused', timeout=5000)
        self.evidence['pause_audio'] = {'running': running, 'paused': paused, 'held': held, 'resumed': resumed,
                                        'audio_off': audio_off, 'audio_off_after_pause_cycle': still_off,
                                        'audio_on': audio_on}

    def interstitial(self, page, script):
        self.fake(page, interstitial=script)
        return page.evaluate('''async () => {
            const before = window.__fakeBridge.calls.length, states = []
            PLATFORM.onAdState(s => states.push(s))
            PLATFORM_BACKEND.gameplayStop('death')
            const t0 = performance.now()
            const result = await PLATFORM.showInterstitial('game_over')
            const ms = Math.round(performance.now() - t0)
            return {result, ms, states, calls: window.__fakeBridge.calls.slice(before).map(c => c.name)
                .filter(n => n.startsWith('advertisement.show'))}
        }''')

    def test_03_interstitial(self):
        prepare = '''() => { PLATFORM.interstitialMinGapMs = 0; PLATFORM_BACKEND.adOpenTimeoutMs = 400 }'''
        page = self.open()
        self.wait_unpaused_run(page)
        page.evaluate(prepare)
        playing = page.evaluate('''async () => { PLATFORM.gameplayStart('grapple_over')
            const n = window.__fakeBridge.calls.length
            const due = PLATFORM.isInterstitialDue()
            const result = await PLATFORM.showInterstitial('game_over')
            return {due, result, calls: window.__fakeBridge.calls.slice(n).map(c => c.name)
                .filter(n => n.startsWith('advertisement.show'))} }''')
        self.assertEqual(playing, {'due': False, 'result': 'skipped', 'calls': []})
        rows = {}
        cases = [('closed', ['loading', 'opened', 'closed'], 'closed'),
                 ('failed', ['loading', 'failed'], 'failed'),
                 ('throw', 'throw', 'failed'), ('reject', 'reject', 'failed')]
        for name, script, result in cases:
            row = rows[name] = self.interstitial(page, script)
            self.assertEqual(row['result'], result, (name, row))
            self.assertEqual(row['calls'], ['advertisement.showInterstitial'], (name, row))
            page.wait_for_timeout(100)
        self.assertEqual(rows['closed']['states'], ['opened', 'closed'])
        self.assertEqual(rows['failed']['states'], [])
        self.assertFalse(page.evaluate('adOpen'))
        # Never opens: 'failed' after adOpenTimeoutMs, stays in flight
        row = rows['never'] = self.interstitial(page, 'never')
        self.assertEqual(row['result'], 'failed')
        self.assertGreaterEqual(row['ms'], 350)
        self.assertLess(row['ms'], 1500)
        blocked = page.evaluate('''async () => ({due: PLATFORM.isInterstitialDue(),
            result: await PLATFORM.showInterstitial('game_over')})''')
        self.assertEqual(blocked, {'due': False, 'result': 'skipped'})
        # The SDK ends it late: in flight no more
        self.emit(page, 'INTERSTITIAL_STATE_CHANGED', 'closed')
        self.assertTrue(page.evaluate('PLATFORM.isInterstitialDue()'))
        # Min gap
        gap = page.evaluate('''async () => { PLATFORM.interstitialMinGapMs = 60000
            window.__fakeBridge.interstitial = ['opened', 'closed']
            return {due: PLATFORM.isInterstitialDue(), result: await PLATFORM.showInterstitial('game_over')} }''')
        self.assertEqual(gap, {'due': False, 'result': 'skipped'})
        # One in flight
        page.evaluate('PLATFORM.interstitialMinGapMs = 0')
        inflight = page.evaluate('''async () => { window.__fakeBridge.interstitial = ['loading', 'opened', 'closed']
            const n = window.__fakeBridge.calls.length
            const first = PLATFORM.showInterstitial('game_over')
            const second = await PLATFORM.showInterstitial('game_over')
            return {first: await first, second, calls: window.__fakeBridge.calls.slice(n).map(c => c.name)
                .filter(n => n.startsWith('advertisement.show'))} }''')
        self.assertEqual(inflight, {'first': 'closed', 'second': 'skipped', 'calls': ['advertisement.showInterstitial']})
        # Unsupported: skipped, never due
        self.fake(page, interstitialSupported=False)
        unsupported = page.evaluate('''async () => ({supported: PLATFORM.isInterstitialSupported(),
            due: PLATFORM.isInterstitialDue(), result: await PLATFORM.showInterstitial('game_over')})''')
        self.assertEqual(unsupported, {'supported': False, 'due': False, 'result': 'skipped'})
        self.evidence['interstitial'] = {'while_playing': playing, 'cases': rows, 'blocked_while_in_flight': blocked,
                                         'min_gap': gap, 'in_flight': inflight, 'unsupported': unsupported}

    def test_04_game_over_flow(self):
        page = self.open()
        self.wait_unpaused_run(page)
        page.evaluate('PLATFORM.interstitialMinGapMs = 0')
        n = len(self.calls(page))
        page.evaluate('''() => { ninja.isInvulnerable = () => false; onLethalDeath() }''')
        dead = page.evaluate(STATE)
        self.assertTrue(dead['offer'], dead)
        self.assertNotIn('advertisement.showInterstitial', self.calls(page)[n:], 'no ad while the death screen opens')
        page.evaluate('restartFromOffer()')
        pending = page.evaluate(STATE)
        self.assertTrue(pending['interstitialPending'], pending)
        page.wait_for_function('() => !interstitialPending && runInProgress && !continueOffer.visible', timeout=10000)
        after = self.calls(page)[n:]
        self.assertEqual(after.count('advertisement.showInterstitial'), 1, after)
        self.wait_unpaused_run(page)
        refused = page.evaluate('PLATFORM.showInterstitial("game_over")')
        self.assertEqual(refused, 'skipped')
        self.assertEqual(self.calls(page)[n:].count('advertisement.showInterstitial'), 1)
        messages = page.evaluate(MESSAGES)
        self.assertIn('level_failed', messages)
        self.evidence['game_over'] = {'dead': dead, 'pending': pending,
                                      'ad_calls': [c for c in after if c.startswith('advertisement.show')],
                                      'while_playing': refused}

    def rewarded(self, page, script):
        self.fake(page, rewarded=script)
        return page.evaluate('''async () => {
            const E = bridge.EVENT_NAME.REWARDED_STATE_CHANGED, F = window.__fakeBridge
            const before = F.count(E), states = []
            PLATFORM.onAdState(s => states.push(s))
            const supported = PLATFORM.isRewardedSupported()
            const result = await PLATFORM.showRewarded('go_back')
            await new Promise(r => setTimeout(r, 120))
            return {supported, result, states, listenersRestored: F.count(E) === before, adOpen}
        }''')

    def test_05_rewarded_results(self):
        page = self.open()
        page.evaluate('PLATFORM_BACKEND.adOpenTimeoutMs = 400')
        cases = [('rewarded_then_closed', ['loading', 'opened', 'rewarded', 'closed'], 'rewarded'),
                 ('closed_only', ['loading', 'opened', 'closed'], 'closed'),
                 ('failed', ['loading', 'failed'], 'failed'),
                 ('throw', 'throw', 'failed'), ('reject', 'reject', 'failed'), ('never', 'never', 'failed')]
        rows = {}
        for name, script, result in cases:
            row = rows[name] = self.rewarded(page, script)
            self.assertTrue(row['supported'])
            self.assertEqual(row['result'], result, (name, row))
            self.assertTrue(row['listenersRestored'], (name, row))
            self.assertFalse(row['adOpen'], (name, row))
            if name == 'never':
                # The SDK never answered: end it so the next ad may run
                self.emit(page, 'REWARDED_STATE_CHANGED', 'closed')
        self.assertEqual(rows['rewarded_then_closed']['states'], ['opened', 'closed'])
        self.fake(page, rewardedSupported=False)
        unavailable = page.evaluate('''async () => ({supported: PLATFORM.isRewardedSupported(),
            result: await PLATFORM.showRewarded('go_back')})''')
        self.assertEqual(unavailable, {'supported': False, 'result': 'unavailable'})
        rows['unsupported'] = unavailable
        self.evidence['rewarded'] = rows

    def baseline_save_case(self, storage_get):
        page = self.open(store=BASELINE_SAVE, setup={'storageGet': storage_get})
        got = page.evaluate('''() => ({records: {...scoreText.record}, time: PROGRESS.getTime(),
            lang: PROGRESS.getLang(), language: I18N.language, remoteKnown: PLATFORM.storage.remoteKnown,
            gets: window.__fakeBridge.calls.filter(c => c.name === 'storage.get').map(c => c.arg)})''')
        self.assertEqual({k: got['records'][k] for k in ('classic', 'bad')}, {'classic': 42, 'bad': 7}, got)
        self.assertGreaterEqual(got['time'], 3600)
        self.assertEqual([got['lang'], got['language']], ['ru', 'ru'])
        self.assertTrue(got['remoteKnown'])
        self.assertEqual(len(got['gets']), 1)
        for key in BASELINE_SAVE:
            if key != 'grapnelninja.muted':
                self.assertIn(key, got['gets'][0])
        # The next write keeps the format (tutorialDone carried over)
        page.evaluate('() => { PROGRESS.setTime(PROGRESS.getTime() + 5); PROGRESS.flush() }')
        page.wait_for_function('''() => window.__fakeBridge.calls.some(c => c.name === 'storage.set'
            && c.arg[0].includes('grapnelninja.records'))''', timeout=5000)
        written = page.evaluate('''() => Object.fromEntries(window.__fakeBridge.calls
            .filter(c => c.name === 'storage.set').flatMap(c => c.arg[0].map((k, i) => [k, c.arg[1][i]])))''')
        self.assertEqual(json.loads(written['grapnelninja.records']), {'classic': 42, 'bad': 7})
        self.assertEqual(written['grapnelninja.tutorialDone'], 'true')
        self.assertEqual(written['grapnelninja.lang'], 'ru')
        self.assertGreaterEqual(int(written['grapnelninja.time']), 3600)
        self.assertNotIn('grapnelninja.muted', written)
        # Reload: the saves are still read
        page.reload()
        page.wait_for_function(READY, timeout=30000)
        reloaded = page.evaluate('''() => ({records: {...scoreText.record}, time: PROGRESS.getTime(),
            lang: PROGRESS.getLang(), muted: localStorage.getItem('grapnelninja.muted')})''')
        self.assertEqual({k: reloaded['records'][k] for k in ('classic', 'bad')}, {'classic': 42, 'bad': 7})
        self.assertGreaterEqual(reloaded['time'], 3600)
        self.assertEqual(reloaded['lang'], 'ru')
        return {'storage_get': storage_get, 'read': got, 'written': written, 'after_reload': reloaded}

    def test_06_save_compatibility(self):
        rows = [self.baseline_save_case('ok'), self.baseline_save_case('parse')]
        self.evidence['save_compatibility'] = {'baseline_save': BASELINE_SAVE, 'cases': rows}

    def boots_with(self, sdk='fake', setup=None, note=None):
        page = self.open(sdk=sdk, setup=setup)
        self.wait_unpaused_run(page)
        start = page.evaluate('floors[0].climbStats.elapsedActiveMs')
        page.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 300', arg=start, timeout=10000)
        row = page.evaluate('''async () => ({platformId: PLATFORM.getPlatformId(), environment: PLATFORM.environment,
            readiness: PLATFORM_BACKEND.readiness().state, gameReady: PLATFORM_BACKEND.readiness().gameReady,
            language: PLATFORM.language, interstitial: PLATFORM.isInterstitialSupported(),
            rewarded: PLATFORM.isRewardedSupported(), remoteKnown: PLATFORM.storage.remoteKnown,
            show: (PLATFORM_BACKEND.gameplayStop('death'), await PLATFORM.showInterstitial('game_over')),
            reward: await PLATFORM.showRewarded('go_back'), ready: await PLATFORM.gameReady(),
            track: PLATFORM.track('probe', {}), lifecycle: await PLATFORM.sendLifecycle('level_paused')})''')
        self.assertEqual(row['platformId'], 'playgama')
        row['boot_s'] = self.boot_s
        row['warnings'] = [c for c in self.console if c.startswith('warning')][:6]
        if note:
            row['note'] = note
        return page, row

    def test_07_broken_bridges_boot(self):
        rows = {}
        page, rows['none'] = self.boots_with('none')
        self.assertEqual(rows['none']['environment'], 'disabled')
        self.assertEqual([rows['none']['show'], rows['none']['reward']], ['skipped', 'unavailable'])
        saved = page.evaluate('''async () => [await PLATFORM.storage.setMany({'grapnelninja.pgProbe': 'v'}),
            await PLATFORM.storage.getMany(['grapnelninja.pgProbe'])]''')
        self.assertEqual(saved, [True, {'grapnelninja.pgProbe': 'v'}])
        page, rows['initialize_never'] = self.boots_with(setup={'initialize': 'never'})
        self.assertEqual(rows['initialize_never']['environment'], 'disabled')
        self.assertLess(rows['initialize_never']['boot_s'], 15)
        self.assertEqual(page.evaluate(MESSAGES), [])
        page, rows['initialize_reject'] = self.boots_with(setup={'initialize': 'reject'})
        self.assertEqual(rows['initialize_reject']['environment'], 'disabled')
        self.assertEqual(page.evaluate(MESSAGES), [])
        for sdk in ('throwing', 'proxy'):
            page, rows[sdk] = self.boots_with(sdk)
            self.assertIn(rows[sdk]['reward'], ('failed', 'unavailable'))
            self.assertIn(rows[sdk]['show'], ('failed', 'skipped'))
        self.assertEqual(rows['throwing']['environment'], 'playgama')
        self.assertEqual(rows['proxy']['environment'], 'disabled')
        # storage.get never settles: boots with defaults, writes nothing
        page, rows['storage_never'] = self.boots_with(setup={'storageGet': 'never'})
        self.assertFalse(rows['storage_never']['remoteKnown'])
        page.evaluate('() => { PROGRESS.setTime(99); PROGRESS.flush(); PROGRESS.flushClimb() }')
        page.wait_for_timeout(500)
        self.assertNotIn('storage.set', self.calls(page))
        # A late storage.get answer is reconciled (onRecovery), then saved
        late_store = dict(BASELINE_SAVE)
        page = self.open(store=late_store, setup={'storageGet': 'late', 'lateMs': 2500})
        early = page.evaluate('() => ({remoteKnown: PLATFORM.storage.remoteKnown, classic: scoreText.record.classic})')
        page.wait_for_function('() => PLATFORM.storage.remoteKnown && scoreText.record.classic === 42', timeout=10000)
        page.evaluate('() => PROGRESS.flush()')
        page.wait_for_function('''() => window.__fakeBridge.calls.some(c => c.name === 'storage.set'
            && c.arg[0].includes('grapnelninja.records'))''', timeout=5000)
        rows['storage_late'] = {'early': early, 'recovered': page.evaluate('() => ({...scoreText.record})')}
        self.assertFalse(early['remoteKnown'])
        # sendMessage never settles: game_ready stays in flight, sent once
        page, rows['send_never'] = self.boots_with(setup={'sendMessage': 'never'})
        self.assertEqual(rows['send_never']['gameReady'], 'inflight')
        self.assertEqual(page.evaluate(MESSAGES), ['game_ready'])
        self.evidence['broken_bridges'] = rows


if __name__ == '__main__':
    unittest.main()
