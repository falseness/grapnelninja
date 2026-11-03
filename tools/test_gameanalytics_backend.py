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
# GameAnalytics.min.js 5.0.0). window.__GA_MOCK = 'throw' makes every method throw.
MOCK_SDK = r'''
(function(scope) {
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
    scope.gameanalytics = {
        GameAnalytics,
        EGAErrorSeverity: {Undefined: 0, Debug: 1, Info: 2, Warning: 3, Error: 4, Critical: 5},
        EGAProgressionStatus: {Undefined: 0, Start: 1, Complete: 2, Fail: 3},
        EGAAdAction: {Undefined: 0, Clicked: 1, Show: 2, FailedShow: 3, RewardReceived: 4},
        EGAAdType: {Undefined: 0, Video: 1, RewardedVideo: 2, Playable: 3, Interstitial: 4,
                    OfferWall: 5, Banner: 6},
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
            context.route(self.url + build_release.GA_BACKEND,
                          lambda r: r.fulfill(content_type='application/javascript', body=backend))
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
        srcs = re.findall(r'<script src\s*=\s*"([^"]+)"', html)
        i = srcs.index(SDK_PATH)
        self.assertEqual(srcs[i:i + 3], [SDK_PATH, build_release.GA_BACKEND, 'analytics.js'])
        self.assertNotIn('analytics/backends/none.js', srcs)
        self.assertEqual(itch[SDK_PATH], self.tree.read(SDK_PATH))
        self.assertEqual(itch[SDK_PATH], (ROOT / SDK_PATH).read_bytes())
        self.assertIn(b'MIT License', itch[build_release.GA_LICENSE])
        backend = itch[build_release.GA_BACKEND].decode('utf-8')
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
        y8_srcs = re.findall(r'<script src\s*=\s*"([^"]+)"', y8['index.html'].decode('utf-8'))
        j = y8_srcs.index(SDK_PATH)
        self.assertEqual(y8_srcs[j:j + 3], [SDK_PATH, build_release.GA_BACKEND, 'analytics.js'])
        self.assertEqual(y8[SDK_PATH], itch[SDK_PATH])
        self.assertTrue(y8[build_release.GA_BACKEND] == itch[build_release.GA_BACKEND],
                        'y8 gameanalytics.js differs from the itch one')
        for portal in ('gamepix', 'playgama'):
            with self.subTest(portal=portal):
                files = self.zips[portal]
                self.assertIn('analytics/backends/none.js', files)
                self.assertFalse([n for n in files if 'gameanalytics' in n.lower()])
                self.assertNotIn(b'GameAnalytics', files['index.html'])
        self.evidence['cases']['static'] = {'itch_scripts': srcs[i - 1:i + 3], 'pass': True}

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


if __name__ == '__main__':
    unittest.main()
