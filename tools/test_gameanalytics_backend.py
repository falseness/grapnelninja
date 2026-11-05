"""TASK-860: analytics/backends/gameanalytics.js in the built itch zip.

Builds the itch zip (tools/build_release.py, GA_GAME_KEY / GA_SECRET_KEY from
the environment or /root/credentials/grapnelninja/credentials.env; values
are never printed) from GA_BACKEND_REV (default HEAD) into a temp dir,
serves it over http with every external request aborted and replaces the
vendored SDK (analytics/vendor/GameAnalytics.min.js) with a recording mock
`gameanalytics` (the real EGA* enum values, GameAnalytics.* methods that
record their arguments):
- boot: configureBuild('itch-' + the release build id, BUILD_CONFIG.platform/build) then initialize(game key, secret key) once
  with the injected keys, then startSession; the game runs.
- every ANALYTICS facade call maps to its GameAnalytics call with the
  sanitized arguments and the EGA* enum values; unknown ad actions/types
  are dropped; a second ANALYTICS.init does not initialize again.
- a GameAnalytics whose every method throws, or no SDK at all (404), never
  reaches the game: no page error, the run goes on, facade calls return.
- the repo's gameanalytics.js (empty GA_KEYS) never calls GameAnalytics.
- an SDK that answers its init late (the real one does, one round trip after
  initialize): boot events (env:*, the run's progression Start) wait and go out
  in order after the answer; startSession is not replayed.
- TASK-899 pagehide flush ('threaded' mock: the real SDK's GA-thread task
  queue, store, processEvents and GAHTTPApi.sendRequest internals): the SDK's
  own beforeunload session end is held; at pagehide the queued add* tasks run
  at once, then session_end, and the batch goes out in ONE fetch(keepalive)
  /events POST (Authorization = the SDK's HMAC, no XHR) carrying every event
  the game handed the SDK, session_end last; the sent rows leave the saved
  store; nothing reaches the SDK after endSession; a second pagehide sends
  nothing.
- TASK-907 back/forward cache: pageshow(persisted) after that pagehide calls
  startSession once; the run's progression Start and later events wait
  until the SDK's new session started, then go out; the next pagehide hands
  the quit-time events and endSession again and sends one more keepalive
  batch; a non-persisted pageshow or a second persisted one does nothing.
- TASK-908 hidden tab: visibilitychange to hidden runs the queued GA-thread
  tasks and sends hide:*, hide_long_fall:*, longest_fall:hide in one
  fetch(keepalive) /events POST with NO endSession / session_end; the sent
  rows leave the store; once per hidden period, at most 5 per page; after
  visible again later events still reach the SDK, and pagehide still ends
  the session with quit:* and session_end.
- static: the itch zip loads the SDK + gameanalytics.js instead of none.js
  and ships the SDK unmodified with its licence; the y8 zip ships the same
  SDK and keys; the dev index.html and the gamepix / playgama zips stay on
  none.js without the SDK.

GA_BACKEND_EVIDENCE_DIR=DIR writes ga-backend.json (calls with the key
values replaced by '<GA_GAME_KEY>' / '<GA_SECRET_KEY>').

    python3 tools/test_gameanalytics_backend.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release  # noqa: E402
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402
from game_harness import collect_errors  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS = Path('/root/credentials/grapnelninja/credentials.env')
KEY_NAMES = ('GA_GAME_KEY', 'GA_SECRET_KEY', 'Y8_APP_ID', 'Y8_GAME_ID')
SDK_PATH = build_release.GA_SDK
VIEWPORT = {'width': 1280, 'height': 720}

# Recording stand-in for the vendored SDK (same globals and enum values as
# GameAnalytics.min.js 5.0.0). window.__GA_MOCK_MODE = 'throw' makes every method throw;
# 'deferred' adds the SDK's readiness API (isRemoteConfigsReady / addRemoteConfigsListener,
# not recorded): not ready until window.__gaAnswer() plays the init answer.
MOCK_SDK = r'''
(function(scope) {
    const GameAnalyticsNs = {}
    const calls = []
    const mode = scope.__GA_MOCK_MODE || 'record'
    const names = ['configureBuild', 'initialize', 'startSession', 'endSession', 'addProgressionEvent',
        'addDesignEvent', 'addErrorEvent', 'addAdEvent', 'setEnabledInfoLog', 'setEnabledVerboseLog',
        'setEnabledManualSessionHandling', 'onStop', 'onResume']
    const GameAnalytics = {}
    for (const name of names)
        GameAnalytics[name] = function(...args) {
            calls.push([name, args.map(a => a === undefined ? '<undefined>' : a)])
            if (mode === 'throw')
                throw new Error('GA mock ' + name + ' throws')
        }
    if (mode === 'deferred') {
        let answered = false
        const listeners = []
        GameAnalytics.isRemoteConfigsReady = () => answered
        GameAnalytics.addRemoteConfigsListener = l => listeners.push(l)
        scope.__gaAnswer = () => { answered = true; for (const l of listeners) l.onRemoteConfigsUpdated() }
    }
    if (mode === 'threaded') {
        // The SDK's internals the backend's pagehide flush uses (shapes as in 5.0.0):
        // add*/endSession only queue a GA-thread task; nothing runs them by itself here
        const queue = [], rows = [], xhr = [], ran = []
        let session = true, batch = 0
        const ns = {}
        const toRow = (name, args) => name === 'addDesignEvent' ? 'design:' + args[0]
            : name === 'addProgressionEvent' ? 'progression:' + args.slice(0, 3).join(':') : name
        for (const name of ['addDesignEvent', 'addProgressionEvent', 'addErrorEvent', 'addAdEvent']) {
            const record = GameAnalytics[name]
            GameAnalytics[name] = function(...args) {
                record(...args)
                queue.push(() => { ran.push(toRow(name, args)); rows.push({status: 'new', event: toRow(name, args)}) })
            }
        }
        const recordEnd = GameAnalytics.endSession
        GameAnalytics.endSession = function(...args) {
            recordEnd(...args)
            queue.push(() => ns.threading.GAThreading.endSessionAndStopQueue())
        }
        // As in 5.0.0: a GA-thread task that starts a new session (the init
        // answer is folded into it); until it ran sessionIsStarted() is false
        const recordStart = GameAnalytics.startSession
        GameAnalytics.startSession = function(...args) {
            recordStart(...args)
            queue.push(() => { if (!session) { session = true; ran.push('session_start') } })
        }
        ns.threading = {GAThreading: {
            taskQueue: queue,
            run() { while (queue.length) queue.shift()() },
            endSessionAndStopQueue() {
                if (!session) return
                session = false
                ran.push('session_end')
                rows.push({status: 'new', event: 'session_end'})
                ns.events.GAEvents.processEvents('', false)
            },
        }}
        ns.events = {GAEvents: {processEvents() {
            const fresh = rows.filter(r => r.status === 'new')
            if (!fresh.length) return
            const id = 'batch' + (++batch)
            for (const r of fresh) r.status = id
            const json = JSON.stringify(fresh.map(r => r.event))
            ns.http.GAHTTPApi.sendRequest('https://api.gameanalytics.com/v2/key/events', json,
                [json, id, String(fresh.length)], false, (x, url, done, extra) => {
                    ran.push('answer:' + x.status + ':' + extra[2])
                    for (let i = rows.length - 1; i >= 0; i--) if (rows[i].status === extra[2]) rows.splice(i, 1)
                }, null)
        }}}
        ns.http = {GAHTTPApi: {sendRequest(url) { xhr.push(url) }}}
        ns.state = {GAState: {instance: {isUnloading: false}, getGameSecret: () => 'secret', getGameKey: () => 'key',
            sessionIsStarted: () => session}}
        ns.utilities = {GAUtilities: {getHmac: (key, body) => 'hmac:' + key + ':' + body.length}}
        ns.store = {GAStore: {
            delete(kind, where) { for (let i = rows.length - 1; i >= 0; i--)
                if (where.every(([k, op, v]) => op === 0 && rows[i][k] === v)) rows.splice(i, 1) },
            save(key) { scope.__gaSaved = {key, rows: JSON.parse(JSON.stringify(rows))} },
        }, EGAStore: {Events: 0, Sessions: 1, Progression: 2}, EGAStoreArgsOperator: {Equal: 0, LessOrEqual: 1, NotEqual: 2}}
        scope.__gaThreaded = {queue, rows, xhr, ran}
        scope.__gaFetch = []
        scope.fetch = (url, init) => {
            scope.__gaFetch.push({url, keepalive: init.keepalive, method: init.method,
                auth: init.headers.Authorization, body: init.body})
            return Promise.resolve({status: 200, statusText: 'OK', text: () => Promise.resolve('{}')})
        }
        Object.assign(GameAnalyticsNs, ns)
    }
    scope.gameanalytics = {
        GameAnalytics,
        EGAErrorSeverity: {Undefined: 0, Debug: 1, Info: 2, Warning: 3, Error: 4, Critical: 5},
        EGAProgressionStatus: {Undefined: 0, Start: 1, Complete: 2, Fail: 3},
        EGAAdAction: {Undefined: 0, Clicked: 1, Show: 2, FailedShow: 3, RewardReceived: 4},
        EGAAdType: {Undefined: 0, Video: 1, RewardedVideo: 2, Playable: 3, Interstitial: 4,
                    OfferWall: 5, Banner: 6},
        ...GameAnalyticsNs,
    }
    scope.__gaCalls = calls
})(this)
'''

# (facade call as JS, expected GameAnalytics calls)
MAPPING = [
    ("ANALYTICS.progression('Start', 'grapple_over', 'SEC 1!')",
     [['addProgressionEvent', [1, 'grapple_over', 'SEC_1_', '']]]),
    ("ANALYTICS.progression('Complete', 'grapple_over', undefined, 'S:3', 120)",
     [['addProgressionEvent', [2, 'grapple_over', 'S_3', '', 120]]]),
    ("ANALYTICS.progression('Fail', 'a', 'b', 'c')",
     [['addProgressionEvent', [3, 'a', 'b', 'c']]]),
    ("ANALYTICS.progression('Unknown', 'a')", []),
    ("ANALYTICS.design('fall:S03 room!', 2.5)", [['addDesignEvent', ['fall:S03_room_', 2.5]]]),
    ("ANALYTICS.design('goback:SEC-chain1')", [['addDesignEvent', ['goback:SEC-chain1']]]),
    ("ANALYTICS.design('best_height:grapple_over', NaN)", [['addDesignEvent', ['best_height:grapple_over']]]),
    ("ANALYTICS.design('')", []),
    ("ANALYTICS.error('critical', 'boom @ index.html:12')", [['addErrorEvent', [5, 'boom @ index.html:12']]]),
    ("ANALYTICS.error('debug', 'x'.repeat(9000))", [['addErrorEvent', [1, 'x' * 8000]]]),
    ("ANALYTICS.error('fatal', 'x')", []),
    ("ANALYTICS.ad('show', 'interstitial', 'go back')", [['addAdEvent', [2, 4, 'grapnelninja', 'go_back']]]),
    ("ANALYTICS.ad('failed_show', 'rewarded', '')", [['addAdEvent', [3, 2, 'grapnelninja', 'none']]]),
    ("ANALYTICS.ad('reward_received', 'rewarded', 'continue')",
     [['addAdEvent', [4, 2, 'grapnelninja', 'continue']]]),
    ("ANALYTICS.ad(undefined, 'interstitial', 'x')", []),
    ("ANALYTICS.ad('show', 'popup', 'x')", []),
    ("ANALYTICS.ad('constructor', 'interstitial', 'x')", []),
    ("ANALYTICS.init({build: 'again'})", []),
    ("ANALYTICS.sessionStart()", [['startSession', []]]),
    ("ANALYTICS.sessionEnd()", [['endSession', []]]),
]


def credentials():
    """{name: value} from the environment, else the credentials file."""
    env = {k: os.environ.get(k, '') for k in KEY_NAMES}
    if not all(env.values()) and CREDENTIALS.exists():
        for line in CREDENTIALS.read_text().splitlines():
            m = re.match(r'^\s*(?:export\s+)?([A-Z0-9_]+)=(.*)$', line)
            if m and m.group(1) in env and not env[m.group(1)]:
                env[m.group(1)] = m.group(2).strip().strip('"\'')
    return env


class GameAnalyticsBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = credentials()
        if not all(cls.env.values()):
            raise unittest.SkipTest('GA_GAME_KEY / GA_SECRET_KEY / Y8 ids unavailable')
        cls.stack = ExitStack()
        cls.out = Path(tempfile.mkdtemp(prefix='ga-backend-'))
        cls.stack.callback(shutil.rmtree, cls.out, True)
        cls.tree = build_release.CommittedTree(os.environ.get('GA_BACKEND_REV', 'HEAD'))
        cls.zips = {}
        for portal in build_release.PORTALS:
            build_release.build(portal, cls.out, env=cls.env, tree=cls.tree)
            with zipfile.ZipFile(cls.out / portal / f'grapple-over-{portal}.zip') as z:
                cls.zips[portal] = {n: z.read(n) for n in z.namelist()}
        cls.site = cls.out / 'site'
        with zipfile.ZipFile(cls.out / 'itch' / 'grapple-over-itch.zip') as z:
            z.extractall(cls.site)
        cls.url, cls.browser = start_browser_test(cls.site, cls.stack.callback)
        cls.evidence = {'revision': cls.tree.revision, 'build_id': cls.tree.build_id(), 'cases': {}}

    @classmethod
    def tearDownClass(cls):
        folder = os.environ.get('GA_BACKEND_EVIDENCE_DIR')
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            Path(folder, 'ga-backend.json').write_text(cls.redact(json.dumps(cls.evidence, indent=1)) + '\n')
        cls.stack.close()

    @classmethod
    def redact(cls, text):
        for name in ('GA_GAME_KEY', 'GA_SECRET_KEY'):
            text = text.replace(cls.env[name], f'<{name}>')
        return text

    def boot(self, sdk='mock', backend=None, mode='record'):
        """Booted itch page; sdk 'mock' | 'missing'; backend overrides gameanalytics.js."""
        context = self.browser.new_context(viewport=VIEWPORT)
        self.addCleanup(context.close)
        if mode != 'record':
            context.add_init_script(f'window.__GA_MOCK_MODE = {json.dumps(mode)}')

        def vendor(route):
            if sdk == 'missing':
                return route.fulfill(status=404, body='')
            return route.fulfill(content_type='application/javascript', body=MOCK_SDK)
        context.route(self.url + SDK_PATH, vendor)
        if backend is not None:
            # TASK-893: gameanalytics.js is a bundle part; serve the bundle with that part replaced
            itch = self.zips['itch']
            bundle = build_release.replace_part(itch, build_release.GA_BACKEND, backend)
            context.route(self.url + build_release.bundle_path(itch),
                          lambda r: r.fulfill(content_type='application/javascript', body=bundle))
        page = context.new_page()
        errors = collect_errors(page)
        page.goto(self.url + 'index.html')
        wait_for_boot_run(page)
        page.wait_for_timeout(300)
        return page, errors

    def calls(self, page):
        return page.evaluate('() => window.__gaCalls ? JSON.parse(JSON.stringify(window.__gaCalls)) : null')

    def assert_running(self, page, errors):
        page.wait_for_timeout(500)
        state = page.evaluate('() => ({version, runInProgress, paused: menu.gamePaused, '
                              'backend: ANALYTICS_BACKEND.backendId})')
        self.assertEqual(errors['page'], [])
        self.assertEqual(state['version'], 'grapple_over')
        self.assertTrue(state['runInProgress'])
        self.assertFalse(state['paused'])
        return state

    def test_01_static_itch_zip_and_others(self):
        itch = self.zips['itch']
        html = itch['index.html'].decode('utf-8')
        tags = re.findall(r'<script src\s*=\s*"([^"]+)"', html)
        # TASK-893: the vendored SDK tag sits right before the one game bundle, whose parts
        # have gameanalytics.js right before analytics.js
        self.assertEqual(tags[tags.index(SDK_PATH) + 1], build_release.bundle_path(itch))
        srcs = list(build_release.bundle_parts(itch))
        i = srcs.index(build_release.GA_BACKEND)
        self.assertEqual(srcs[i:i + 2], [build_release.GA_BACKEND, 'analytics.js'])
        self.assertNotIn('analytics/backends/none.js', srcs)
        self.assertEqual(itch[SDK_PATH], self.tree.read(SDK_PATH))
        self.assertEqual(itch[SDK_PATH], (ROOT / SDK_PATH).read_bytes())
        self.assertIn(b'MIT License', itch[build_release.GA_LICENSE])
        backend = build_release.bundle_part(itch, build_release.GA_BACKEND).decode('utf-8') + '\n'
        repo_backend = self.tree.read(build_release.GA_BACKEND).decode('utf-8')
        self.assertIn("var GA_KEYS = {gameKey: '', secretKey: ''}", repo_backend)
        expected = repo_backend.replace(
            "var GA_KEYS = {gameKey: '', secretKey: ''}",
            "var GA_KEYS = {gameKey: '%s', secretKey: '%s'}" % (self.env['GA_GAME_KEY'], self.env['GA_SECRET_KEY']))
        self.assertTrue(backend == expected, 'itch gameanalytics.js is not the repo file with the keys filled in')
        dev = (ROOT / 'index.html').read_text()
        self.assertIn('<script src = "analytics/backends/none.js"></script>', dev)
        self.assertNotIn('gameanalytics', dev.lower())
        y8 = self.zips['y8']
        y8_tags = re.findall(r'<script src\s*=\s*"([^"]+)"', y8['index.html'].decode('utf-8'))
        self.assertEqual(y8_tags[y8_tags.index(SDK_PATH) + 1], build_release.bundle_path(y8))
        y8_srcs = list(build_release.bundle_parts(y8))
        j = y8_srcs.index(build_release.GA_BACKEND)
        self.assertEqual(y8_srcs[j:j + 2], [build_release.GA_BACKEND, 'analytics.js'])
        self.assertEqual(y8[SDK_PATH], itch[SDK_PATH])
        self.assertTrue(build_release.bundle_part(y8, build_release.GA_BACKEND)
                        == build_release.bundle_part(itch, build_release.GA_BACKEND),
                        'y8 gameanalytics.js differs from the itch one')
        for portal in ('gamepix', 'playgama'):
            with self.subTest(portal=portal):
                files = self.zips[portal]
                self.assertIn('analytics/backends/none.js', build_release.bundle_parts(files))
                self.assertFalse([n for n in list(files) + list(build_release.bundle_parts(files))
                                  if 'gameanalytics' in n.lower()])
                self.assertNotIn(b'GameAnalytics', files['index.html'])
        self.evidence['cases']['static'] = {'itch_tags': tags, 'itch_bundle_parts': srcs[i - 1:i + 2], 'pass': True}

    def test_02_boot_initializes_once_with_injected_keys(self):
        page, errors = self.boot()
        calls = self.calls(page)
        names = [c[0] for c in calls]
        self.assertEqual(names[:3], ['configureBuild', 'initialize', 'startSession'])
        self.assertEqual(names.count('initialize'), 1)
        self.assertEqual(names.count('configureBuild'), 1)
        self.assertEqual(calls[0][1], ['itch-' + self.tree.build_id()])
        self.assertTrue(calls[1][1] == [self.env['GA_GAME_KEY'], self.env['GA_SECRET_KEY']],
                        'initialize was not called with GA_GAME_KEY / GA_SECRET_KEY')
        # the spawn section's progression Start follows the session
        self.assertIn('addProgressionEvent', names)
        state = self.assert_running(page, errors)
        self.assertEqual(state['backend'], 'gameanalytics')
        self.evidence['cases']['boot'] = {'calls': calls, 'state': state, 'pass': True}

    def test_03_facade_maps_to_ga_calls(self):
        page, errors = self.boot()
        rows = []
        for js, expected in MAPPING:
            before = len(self.calls(page))
            page.evaluate(f'() => {{ {js} }}')
            got = self.calls(page)[before:]
            got = [c for c in got if c[0] != 'addProgressionEvent' or js.startswith('ANALYTICS.progression')]
            rows.append({'call': js, 'ga': got if len(json.dumps(got)) < 300 else '<long>'})
            with self.subTest(call=js):
                self.assertEqual(got, expected)
        self.assertEqual([c[0] for c in self.calls(page)].count('initialize'), 1)
        self.assert_running(page, errors)
        self.evidence['cases']['mapping'] = {'rows': rows, 'pass': True}

    def test_04_throwing_ga_never_reaches_the_game(self):
        page, errors = self.boot(mode='throw')
        results = []
        for js, _ in MAPPING:
            results.append(page.evaluate(f'() => {{ try {{ {js}; return "ok" }} catch (e) {{ return String(e) }} }}'))
        self.assertEqual(set(results), {'ok'})
        names = [c[0] for c in self.calls(page)]
        self.assertIn('initialize', names)
        box = page.locator('#canvas').bounding_box()
        page.mouse.click(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.3)
        self.assert_running(page, errors)
        self.evidence['cases']['throwing'] = {'facade_results': sorted(set(results)),
                                              'ga_calls_attempted': len(names), 'pass': True}

    def test_05_missing_sdk(self):
        page, errors = self.boot(sdk='missing')
        self.assertIsNone(self.calls(page))
        for js, _ in MAPPING:
            page.evaluate(f'() => {{ {js} }}')
        self.assert_running(page, errors)
        self.evidence['cases']['missing_sdk'] = {'pass': True}

    def test_06_repo_backend_without_keys_is_a_noop(self):
        page, errors = self.boot(backend=self.tree.read(build_release.GA_BACKEND).decode('utf-8'))
        for js, _ in MAPPING:
            page.evaluate(f'() => {{ {js} }}')
        self.assertEqual(self.calls(page), [])
        self.assert_running(page, errors)
        self.evidence['cases']['repo_backend_empty_keys'] = {'ga_calls': 0, 'pass': True}

    def test_07_boot_events_wait_for_the_init_answer(self):
        page, errors = self.boot(mode='deferred')
        before = self.calls(page)
        self.assertEqual([c[0] for c in before], ['configureBuild', 'initialize'],
                         'events reached GameAnalytics before its init answered')
        sent = page.evaluate('() => ANALYTICS.debugLog.filter(e => e.fn === "addDesignEvent" && '
                             'String(e.args[0]).startsWith("env:")).map(e => e.args[0])')
        self.assertTrue(sent, 'the game sent no env:* events at boot')
        page.evaluate('() => window.__gaAnswer()')
        page.wait_for_timeout(300)
        after = self.calls(page)[len(before):]
        names = [c[0] for c in after]
        env = [c[1][0] for c in after if c[0] == 'addDesignEvent' and str(c[1][0]).startswith('env:')]
        self.assertEqual(env, sent, 'queued env:* events were not delivered in order')
        self.assertIn('addProgressionEvent', names)
        self.assertNotIn('startSession', names)
        # later events go straight through
        n = len(self.calls(page))
        page.evaluate("() => ANALYTICS.design('goback:SEC-chain1')")
        self.assertEqual(self.calls(page)[n:], [['addDesignEvent', ['goback:SEC-chain1']]])
        self.assert_running(page, errors)
        self.evidence['cases']['deferred_init'] = {'before_answer': before, 'delivered_after': names,
                                                   'env_events': env, 'pass': True}

    def test_08_pagehide_flush_sends_quit_events_by_keepalive(self):
        page, errors = self.boot(mode='threaded')
        mark = len(self.calls(page))
        # The SDK's beforeunload handler (isUnloading) must not end the session first
        held = page.evaluate('''() => { const g = gameanalytics, st = g.state.GAState.instance
            st.isUnloading = true; g.threading.GAThreading.endSessionAndStopQueue(); st.isUnloading = false
            return __gaThreaded.ran.includes('session_end') }''')
        self.assertFalse(held, 'the SDK beforeunload session end was not held')
        self.assertEqual(page.evaluate('() => __gaFetch.length'), 0)
        page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))")
        page.wait_for_timeout(200)
        calls = self.calls(page)[mark:]
        names = [c[0] for c in calls]
        self.assertIn('endSession', names)
        end = names.index('endSession')
        handed = [('design:' + c[1][0]) if c[0] == 'addDesignEvent' else 'progression:' + ':'.join(map(str, c[1][:3]))
                  for c in calls[:end] if c[0] in ('addDesignEvent', 'addProgressionEvent')]
        self.assertTrue(any(h.startswith('design:quit:') for h in handed), handed)
        self.assertTrue(any(h.startswith('progression:3:') for h in handed), handed)
        self.assertEqual(calls[end + 1:], [], 'calls reached GameAnalytics after endSession')
        state = page.evaluate('() => ({fetch: __gaFetch, xhr: __gaThreaded.xhr, queue: __gaThreaded.queue.length, '
                              'ran: __gaThreaded.ran, rows: __gaThreaded.rows, saved: window.__gaSaved})')
        self.assertEqual(state['queue'], 0, 'GA-thread tasks were left queued')
        self.assertEqual(state['xhr'], [], 'the unload batch went out by XHR')
        self.assertEqual(len(state['fetch']), 1)
        sent = state['fetch'][0]
        body = json.loads(sent['body'])
        self.assertTrue(sent['keepalive'])
        self.assertEqual(sent['method'], 'POST')
        self.assertTrue(sent['url'].endswith('/events'))
        self.assertEqual(sent['auth'], 'hmac:secret:%d' % len(sent['body']))
        self.assertEqual(body[-1], 'session_end')
        for h in handed:
            self.assertIn(h, body)
        self.assertEqual(state['rows'], [], 'sent rows stayed in the store')
        self.assertEqual(state['saved'], {'key': 'key', 'rows': []})
        self.assertIn('answer:200:batch1', state['ran'])
        # Later facade calls (the visibility auto-pause, ...) and a second pagehide send nothing
        page.evaluate("() => { ANALYTICS.design('ui:pause:open:auto'); ANALYTICS.progression('Fail', 'x'); "
                      "window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false})) }")
        page.wait_for_timeout(200)
        self.assertEqual(self.calls(page)[mark + end + 1:], [])
        self.assertEqual(page.evaluate('() => __gaFetch.length'), 1)
        self.assertEqual(errors['page'], [])
        self.evidence['cases']['pagehide_flush'] = {'handed_at_pagehide': handed, 'keepalive_body': body,
                                                    'xhr': state['xhr'], 'pass': True}

    def test_09_bfcache_pageshow_reopens_the_session(self):
        page, errors = self.boot(mode='threaded')
        hide = "() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))"
        show = "persisted => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted}))"
        page.evaluate(hide)
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate('() => __gaFetch.length'), 1)
        mark = len(self.calls(page))
        # A pageshow that is not a bfcache restore changes nothing
        page.evaluate(show, False)
        page.evaluate("() => ANALYTICS.design('ui:pause:open:user')")
        self.assertEqual(self.calls(page)[mark:], [], 'calls reached GameAnalytics before the restore')
        page.evaluate(show, True)
        page.evaluate("() => ANALYTICS.design('ui:pause:open:user')")
        page.wait_for_timeout(600)
        waiting = self.calls(page)[mark:]
        self.assertEqual(waiting, [['startSession', []]], 'events went out before the new session started')
        # The GA thread runs the startSession task: the new session starts, the queue goes out
        page.evaluate('() => gameanalytics.threading.GAThreading.run()')
        page.wait_for_timeout(600)
        after = self.calls(page)[mark:]
        self.assertIn('session_start', page.evaluate('() => __gaThreaded.ran'))
        self.assertEqual(after[1], ['addProgressionEvent', [1, 'grapple_over', '', '']],
                         'the run in progress did not start again')
        self.assertIn(['addDesignEvent', ['ui:pause:open:user']], after)
        self.assertEqual([c[0] for c in after].count('startSession'), 1)
        # A second persisted pageshow (no pagehide between) starts nothing
        n = len(self.calls(page))
        page.evaluate(show, True)
        page.wait_for_timeout(400)
        self.assertEqual(self.calls(page)[n:], [])
        # The next pagehide hands the quit-time events and ends the session again
        page.evaluate("() => gameanalytics.threading.GAThreading.run()")
        page.evaluate(hide)
        page.wait_for_timeout(300)
        second = self.calls(page)[n:]
        names = [c[0] for c in second]
        self.assertIn('endSession', names)
        handed = [('design:' + c[1][0]) if c[0] == 'addDesignEvent' else 'progression:' + ':'.join(map(str, c[1][:3]))
                  for c in second[:names.index('endSession')] if c[0] in ('addDesignEvent', 'addProgressionEvent')]
        self.assertTrue(any(h.startswith('design:quit:') for h in handed), handed)
        self.assertIn('progression:3:grapple_over:', handed)
        state = page.evaluate('() => ({fetch: __gaFetch, xhr: __gaThreaded.xhr, ran: __gaThreaded.ran})')
        self.assertEqual(len(state['fetch']), 2, 'the second pagehide sent no keepalive batch')
        body = json.loads(state['fetch'][1]['body'])
        self.assertEqual(body[-1], 'session_end')
        for h in handed:
            self.assertIn(h, body)
        self.assertEqual(state['ran'].count('session_end'), 2)
        self.assertEqual(errors['page'], [])
        self.evidence['cases']['bfcache_pageshow'] = {'after_restore': after, 'handed_at_second_pagehide': handed,
                                                      'second_keepalive_body': body, 'pass': True}

    def test_10_hidden_tab_flushes_without_ending_the_session(self):
        page, errors = self.boot(mode='threaded')
        visibility = '''state => { Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => state})
            Object.defineProperty(document, 'hidden', {configurable: true, get: () => state === 'hidden'})
            document.dispatchEvent(new Event('visibilitychange')) }'''
        section = page.evaluate("() => { const s = CLIMB_UI.currentSection().id; TELEMETRY.mark('grapple', s); "
                                "TELEMETRY.falling(4500); return s }")
        mark = len(self.calls(page))
        page.evaluate(visibility, 'hidden')
        page.evaluate(visibility, 'hidden')
        page.wait_for_timeout(200)
        calls = self.calls(page)[mark:]
        names = [c[0] for c in calls]
        self.assertNotIn('endSession', names)
        designs = [c[1][0] for c in calls if c[0] == 'addDesignEvent']
        self.assertEqual(designs[:3], ['hide:grapple:' + section, 'hide_long_fall:' + section, 'longest_fall:hide'],
                         designs)
        state = page.evaluate('() => ({fetch: __gaFetch, xhr: __gaThreaded.xhr, queue: __gaThreaded.queue.length, '
                              'ran: __gaThreaded.ran, rows: __gaThreaded.rows, saved: window.__gaSaved})')
        self.assertEqual(len(state['fetch']), 1, 'a second hidden event in the same period sent again')
        sent = state['fetch'][0]
        body = json.loads(sent['body'])
        self.assertTrue(sent['keepalive'])
        self.assertTrue(sent['url'].endswith('/events'))
        self.assertEqual(sent['auth'], 'hmac:secret:%d' % len(sent['body']))
        for d in designs[:3]:
            self.assertIn('design:' + d, body)
        self.assertNotIn('session_end', body)
        self.assertNotIn('session_end', state['ran'])
        self.assertEqual(state['xhr'], [])
        self.assertIn('answer:200:batch1', state['ran'])
        # Only the auto pause's event, queued after the flush, stays in the store
        self.assertEqual([r['event'] for r in state['rows']], [], state['rows'])
        self.assertEqual(state['queue'], 1, 'the auto pause event should be the only queued task')
        # Visible again: later events still reach the SDK, the next hidden period sends again
        page.evaluate(visibility, 'visible')
        n = len(self.calls(page))
        page.evaluate("() => ANALYTICS.design('ui:pause:close')")
        self.assertEqual(self.calls(page)[n:], [['addDesignEvent', ['ui:pause:close']]])
        for _ in range(6):
            page.evaluate(visibility, 'hidden')
            page.evaluate(visibility, 'visible')
        page.wait_for_timeout(300)
        state = page.evaluate('() => ({fetch: __gaFetch.length, ran: __gaThreaded.ran})')
        self.assertEqual(state['fetch'], 5, 'hidden periods are capped at 5 per page')
        self.assertNotIn('session_end', state['ran'])
        self.assertNotIn('endSession', [c[0] for c in self.calls(page)])
        # pagehide still ends the session with the quit-time events
        n = len(self.calls(page))
        page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))")
        page.wait_for_timeout(300)
        tail = self.calls(page)[n:]
        self.assertEqual(tail[-1], ['endSession', []])
        self.assertTrue(any(c[0] == 'addDesignEvent' and c[1][0].startswith('quit:') for c in tail), tail)
        last = page.evaluate('() => JSON.parse(__gaFetch[__gaFetch.length - 1].body)')
        self.assertEqual(last[-1], 'session_end')
        self.assertEqual(page.evaluate('() => __gaFetch.length'), 6)
        self.assertEqual(errors['page'], [])
        self.evidence['cases']['hidden_flush'] = {'hidden_designs': designs, 'keepalive_body': body,
                                                  'keepalive_requests_after_7_periods': state['fetch'],
                                                  'pagehide_body': last, 'pass': True}


if __name__ == '__main__':
    unittest.main()
