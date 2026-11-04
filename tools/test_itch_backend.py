"""TASK-856: the itch.io build (platform/backends/itch.js) inside an itch.io-like embed.

Loads the built itch zip (artifacts/release-grapple-over/itch/
grapple-over-itch.zip, or ITCH_ZIP) the way itch.io serves an HTML5 game:
the zip's files are served from https://html-classic.itch.zone/html/856/
and shown in a sandboxed 960x540 iframe on a page at
https://falseness.itch.io/grapple-over (cross-origin, like itch.io's game
frame). Every other request is blocked and recorded. Checks:

- 00: the zip is current: every shipped file except the rewritten
  index.html/buildconfig.js equals the working tree, itch.js is the only
  portal backend tag, no SDK tag.
- 01: the game boots in the iframe: PLATFORM is itch (environment 'itch',
  language from navigator.language), the frame is 960x540, no ads
  (interstitials and rewarded unsupported).
- 02: saves survive a reload: a language choice, the climb save and a
  storage round-trip key are in localStorage before the reloaded page's
  first script runs, and the reloaded game uses the saved language.
- 03: window blur pauses and mutes (the player cannot resume while blurred);
  focus lifts the host pause and unmutes; the player's resume then runs
  the game again. A hidden document does the same.
- 04: Go back after a long fall works with no ad (no showRewarded call,
  never muted, back on the checkpoint rope).
- 05: a sandbox without allow-same-origin (localStorage throws) still boots
  and saves in memory.
Every test asserts 0 uncaught errors, 0 unhandled rejections and 0 console
errors in the page and the game frame, and 0 blocked requests.
The vendored GameAnalytics SDK (analytics/vendor/GameAnalytics.min.js) is
served as an empty script, so the GameAnalytics backend stays a no-op and
nothing reaches api.gameanalytics.com; tools/test_gameanalytics_backend.py
covers that backend.

ITCH_BACKEND_EVIDENCE_DIR=DIR writes itch-backend.json and itch-embed.png.

    python3 tools/test_itch_backend.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from game_harness import READY
from test_go_back import SETUP, CANDIDATES, CATCH, AFTER
from test_go_back_dialog import START, FALL, HOOKS

from build_release import GENERATED_FILES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ZIP = Path(os.environ.get('ITCH_ZIP') or
           ROOT / 'artifacts' / 'release-grapple-over' / 'itch' / 'grapple-over-itch.zip')
HOST_URL = 'https://falseness.itch.io/grapple-over'
GAME_BASE = 'https://html-classic.itch.zone/html/856/'
GAME_URL = GAME_BASE + 'index.html'
FRAME_W, FRAME_H = 960, 540
# The flags itch.io's game frame needs; 'same-origin' keeps localStorage
SANDBOX = ('allow-scripts allow-same-origin allow-pointer-lock allow-forms '
           'allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals')
# Rewritten by the build, plus the files it generates (build-time bakes, no committed blob)
REWRITTEN = {'index.html', 'buildconfig.js', 'analytics/backends/gameanalytics.js'} | set(GENERATED_FILES)
GA_SDK = 'analytics/vendor/GameAnalytics.min.js'
PROBE_KEY = 'grapnelninja.itchProbe'
CLIMB_KEY = 'grapnelninja.grappleOver'
LANG_KEY = 'grapnelninja.lang'

CONTENT_TYPES = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
                 '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
                 '.webp': 'image/webp', '.jpg': 'image/jpeg', '.woff2': 'font/woff2'}

# Every frame: record uncaught errors and unhandled rejections; the game
# frame also snapshots localStorage before any game script runs.
INIT = r'''(() => {
    window.__errors = []
    addEventListener('error', e => __errors.push('error: ' + (e.message || e.type)))
    addEventListener('unhandledrejection', e => __errors.push('unhandledrejection: ' +
        (e.reason && e.reason.message || String(e.reason))))
    if (location.host === 'html-classic.itch.zone') {
        try {
            window.__bootStore = Object.fromEntries(Object.keys(localStorage)
                .map(k => [k, localStorage.getItem(k)]))
        } catch (e) { window.__bootStore = 'blocked: ' + e.name }
    }
})()'''

AUDIO = '''() => ({paused: menu.gamePaused, hostPaused, muted: GAME_AUDIO.muted,
    reasons: [...GAME_AUDIO.reasons].sort(), elapsed: floors[0].climbStats.elapsedActiveMs,
    hasFocus: document.hasFocus()})'''


def host_html(sandbox):
    return ('<!DOCTYPE html><html><head><title>Grapple Over by falseness</title></head>'
            '<body style="margin:0;background:#2e2e2e">'
            '<div class="game_frame" style="padding:40px">'
            '<iframe id="game_drop" frameborder="0" allowfullscreen="true" scrolling="no" '
            'allow="autoplay; fullscreen *; geolocation; microphone; camera; midi; monetization; '
            'xr-spatial-tracking; gamepad; gyroscope; accelerometer; xr; cross-origin-isolated; web-share" '
            'sandbox="%s" width="%d" height="%d" src="%s"></iframe></div></body></html>'
            % (sandbox, FRAME_W, FRAME_H, GAME_URL))


class ItchBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        if not ZIP.is_file():
            raise unittest.SkipTest('no itch zip: run tools/build_release.py --portal itch')
        cls.tmp = cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='itch-zip-'))
        with zipfile.ZipFile(ZIP) as z:
            cls.names = sorted(z.namelist())
            z.extractall(cls.tmp)
        cls.files = {n: (Path(cls.tmp) / n).read_bytes() for n in cls.names if not n.endswith('/')}
        _, cls.browser = start_browser_test(Path(cls.tmp), cls.stack.callback)
        cls.evidence = {'zip': str(ZIP.relative_to(ROOT) if ZIP.is_relative_to(ROOT) else ZIP),
                        'files': len(cls.files)}
        cls.out = os.environ.get('ITCH_BACKEND_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            Path(cls.out, 'itch-backend.json').write_text(
                json.dumps(cls.evidence, indent=1, sort_keys=True) + '\n')
        cls.stack.close()

    # -- embed -------------------------------------------------------------

    def serve(self, route):
        url = route.request.url
        if url == HOST_URL:
            return route.fulfill(content_type='text/html', body=host_html(self.sandbox))
        if url.startswith(GAME_BASE):
            name = url[len(GAME_BASE):].split('?')[0].split('#')[0]
            if name == GA_SDK:
                return route.fulfill(content_type='application/javascript', body='// GameAnalytics stub\n')
            if name in self.files:
                suffix = Path(name).suffix
                return route.fulfill(body=self.files[name],
                                     content_type=CONTENT_TYPES.get(suffix, 'application/octet-stream'))
            self.missing.append(name)
            return route.fulfill(status=404, body='')
        self.blocked.append(url)
        return route.abort()

    def open(self, sandbox=SANDBOX, locale='en-US'):
        """New context with the itch.io page; returns (page, frame)."""
        self.sandbox = sandbox
        self.blocked, self.missing = [], []
        self.page_errors, self.console_errors = [], []
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale=locale)
        self.addCleanup(context.close)
        context.add_init_script(INIT)
        context.route('**/*', self.serve)
        page = context.new_page()
        page.on('pageerror', lambda e: self.page_errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and self.console_errors.append(m.text))
        self.addCleanup(self.assert_clean, page)
        frame = self.load(page)
        return page, frame

    def load(self, page):
        page.goto(HOST_URL)
        handle = page.wait_for_selector('#game_drop')
        frame = handle.content_frame()
        frame.wait_for_function(READY, timeout=30000)
        return frame

    def reload(self, page):
        page.reload()
        frame = page.wait_for_selector('#game_drop').content_frame()
        frame.wait_for_function(READY, timeout=30000)
        return frame

    def frame_errors(self, page):
        out = []
        for frame in page.frames:
            try:
                out += frame.evaluate('() => window.__errors || []')
            except Exception as e:  # a detached frame has nothing to report
                out.append('evaluate failed: %s' % e)
        return out

    def assert_clean(self, page):
        errors = {'page': self.page_errors, 'console': self.console_errors,
                  'frames': self.frame_errors(page), 'blocked': self.blocked, 'missing': self.missing}
        self.evidence.setdefault('errors', {})[self._testMethodName] = {k: len(v) for k, v in errors.items()}
        self.assertEqual(errors, {'page': [], 'console': [], 'frames': [], 'blocked': [], 'missing': []})

    def offset(self, page):
        box = page.locator('#game_drop').bounding_box()
        return box['x'], box['y']

    # -- tests -------------------------------------------------------------

    def test_00_zip_is_current(self):
        stale = [n for n, b in self.files.items()
                 if n not in REWRITTEN and (not (ROOT / n).is_file() or (ROOT / n).read_bytes() != b)]
        self.assertEqual(stale, [], 'zip is stale: rebuild with tools/build_release.py --portal itch')
        html = self.files['index.html'].decode()
        self.assertEqual(html.count('platform/backends/'), 2)
        self.assertIn('<script src = "platform/backends/itch.js"></script>', html)
        self.assertNotIn('<script src="http', html)
        config = self.files['buildconfig.js'].decode()
        self.assertIn("platform: 'itch'", config)
        self.assertIn("modes: ['grapple_over']", config)
        source = self.files['platform/backends/itch.js'].decode()
        code = '\n'.join(l for l in source.splitlines() if not l.strip().startswith('//'))
        self.assertNotIn('LOCAL_PLATFORM_BACKEND', code)
        self.assertNotIn('base.', code)
        self.evidence['zip_current'] = {'stale': stale, 'itch_js_bytes': len(source)}

    def test_01_boots_in_iframe(self):
        page, frame = self.open(locale='de-DE')
        row = frame.evaluate('''() => ({platformId: PLATFORM.getPlatformId(), backend: PLATFORM_BACKEND.platformId,
            environment: PLATFORM.environment, language: PLATFORM.language, getLanguage: PLATFORM.getLanguage(),
            version, modes: BUILD_CONFIG.modes, inner: [innerWidth, innerHeight],
            canvas: (r => [r.left, r.top, r.right, r.bottom])(canvas.getBoundingClientRect()),
            framed: window.top !== window, origin: location.origin,
            interstitial: PLATFORM.isInterstitialSupported(), due: PLATFORM.isInterstitialDue(),
            rewarded: PLATFORM.isRewardedSupported(), readiness: PLATFORM_BACKEND.readiness(),
            audio: PLATFORM.isAudioEnabled(), remoteKnown: PLATFORM_BACKEND.storage.remoteKnown()})''')
        ads = frame.evaluate('''async () => ({interstitial: await PLATFORM.showInterstitial('death'),
            rewarded: await PLATFORM.showRewarded('go_back'), score: await PLATFORM.submitScore('b', 1),
            achievement: await PLATFORM.unlockAchievement('a')})''')
        self.assertEqual([row['platformId'], row['backend'], row['environment']], ['itch'] * 3)
        self.assertEqual([row['language'], row['getLanguage']], ['de', 'de'])
        self.assertEqual(row['version'], 'grapple_over')
        self.assertEqual(row['modes'], ['grapple_over'])
        self.assertEqual(row['inner'], [FRAME_W, FRAME_H])
        self.assertTrue(row['framed'])
        self.assertEqual(row['origin'], 'https://html-classic.itch.zone')
        left, top, right, bottom = row['canvas']
        self.assertTrue(left >= 0 and top >= 0 and right <= FRAME_W + 0.5 and bottom <= FRAME_H + 0.5, row['canvas'])
        self.assertGreater(min(right - left, bottom - top), 500, row['canvas'])
        self.assertFalse(row['interstitial'] or row['due'] or row['rewarded'])
        self.assertEqual(row['readiness'], {'state': 'local'})
        self.assertTrue(row['audio'] and row['remoteKnown'])
        self.assertEqual(ads, {'interstitial': 'skipped', 'rewarded': 'unavailable',
                               'score': False, 'achievement': False})
        page.wait_for_timeout(300)
        if self.out:
            Path(self.out).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(self.out) / 'itch-embed.png'))
        self.evidence['boot'] = {**row, 'calls': ads}

    def test_02_saves_survive_reload(self):
        page, frame = self.open()
        self.assertEqual(frame.evaluate('I18N.language'), 'en')
        frame.evaluate('setLanguage("ru")')
        self.assertTrue(frame.evaluate('PLATFORM.storage.setMany({"%s": "itch-v"})' % PROBE_KEY))
        # The pause saves and flushes the climb; a paused run writes no more
        frame.evaluate('() => { if (!menu.gamePaused) menu.startPause() }')
        page.wait_for_timeout(1500)
        frame.wait_for_function('''() => localStorage.getItem("%s") === "ru" &&
            localStorage.getItem("%s") !== null''' % (LANG_KEY, CLIMB_KEY), timeout=10000)
        before = frame.evaluate('''() => Object.fromEntries(Object.keys(localStorage)
            .filter(k => k.startsWith("grapnelninja.")).map(k => [k, localStorage.getItem(k)]))''')
        frame = self.reload(page)
        boot = frame.evaluate('window.__bootStore')
        self.assertIsInstance(boot, dict)
        for key in (LANG_KEY, CLIMB_KEY, PROBE_KEY):
            self.assertEqual(boot.get(key), before[key], key)
        after = frame.evaluate('''async () => ({language: I18N.language,
            probe: await PLATFORM.storage.getMany(["%s"])})''' % PROBE_KEY)
        self.assertEqual(after, {'language': 'ru', 'probe': {PROBE_KEY: 'itch-v'}})
        self.evidence['reload'] = {'keys_before': sorted(before), 'boot_matches': True, **after}

    def test_03_blur_pauses_mutes_focus_resumes(self):
        page, frame = self.open()
        frame.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        running = frame.evaluate(AUDIO)
        self.assertFalse(running['paused'] or running['hostPaused'] or running['muted'])
        frame.evaluate("dispatchEvent(new Event('blur'))")
        blurred = frame.evaluate(AUDIO)
        self.assertTrue(blurred['paused'] and blurred['hostPaused'] and blurred['muted'], blurred)
        self.assertEqual(blurred['reasons'], ['host'])
        # The player cannot resume while the host pause holds
        frame.evaluate('menu.unPause()')
        page.wait_for_timeout(300)
        held = frame.evaluate(AUDIO)
        self.assertTrue(held['paused'] and held['muted'])
        self.assertEqual(held['elapsed'], blurred['elapsed'])
        frame.evaluate("dispatchEvent(new Event('focus'))")
        focused = frame.evaluate(AUDIO)
        self.assertFalse(focused['hostPaused'] or focused['muted'], focused)
        self.assertEqual(focused['reasons'], [])
        # The pause menu stays for the player; their resume runs the game
        frame.evaluate('menu.unPause()')
        frame.wait_for_function('el => floors[0].climbStats.elapsedActiveMs > el + 200',
                                arg=focused['elapsed'], timeout=10000)
        resumed = frame.evaluate(AUDIO)
        self.assertFalse(resumed['paused'] or resumed['hostPaused'] or resumed['muted'])
        # A hidden document pauses and mutes; visible again lifts both
        set_hidden = '''hidden => { Object.defineProperty(document, 'visibilityState',
            {configurable: true, get: () => hidden ? 'hidden' : 'visible'})
            document.dispatchEvent(new Event('visibilitychange')) }'''
        frame.evaluate(set_hidden, True)
        hidden = frame.evaluate(AUDIO)
        self.assertTrue(hidden['paused'] and hidden['hostPaused'] and hidden['muted'], hidden)
        frame.evaluate(set_hidden, False)
        shown = frame.evaluate(AUDIO)
        self.assertFalse(shown['hostPaused'] or shown['muted'], shown)
        frame.evaluate('menu.unPause()')
        self.assertFalse(frame.evaluate('menu.gamePaused'))
        self.evidence['pause'] = {'running': running, 'blurred': blurred, 'held': held, 'focused': focused,
                                  'resumed': resumed, 'hidden': hidden, 'shown': shown}

    def catch(self, page, frame, target):
        """Real mouse throw (through the iframe) at target, as test_go_back_dialog."""
        dx, dy = self.offset(page)
        page.mouse.up()
        frame.evaluate(CATCH, [target['x'], target['y']])
        p = frame.evaluate('''([x, y]) => canvasCoordsToViewportCoords({
            x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})''', [target['x'], target['y']])
        page.mouse.move(p['x'] + dx, p['y'] + dy)
        page.mouse.down()
        row = frame.evaluate(AFTER)
        if row['grappled'] and row['target'] == target['id']:
            frame.evaluate('() => { ninja.speedX = ninja.speedY = 0; physics() }')
        page.mouse.up()
        return row

    def test_04_go_back_without_ad(self):
        page, frame = self.open()
        frame.evaluate(SETUP)
        frame.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        frame.evaluate(HOOKS)
        frame.evaluate('''() => { window.AD_CALLS = []; window.MUTED_SEEN = false
            const show = PLATFORM_BACKEND.showRewarded
            PLATFORM_BACKEND.showRewarded = function(p) { AD_CALLS.push(p); return show.call(this, p) }
            const mute = GAME_AUDIO.mute
            GAME_AUDIO.mute = function(r, on) { if (on) MUTED_SEEN = true; return mute.call(this, r, on) } }''')
        cp = None
        for target in frame.evaluate(CANDIDATES)['static']:
            row = self.catch(page, frame, target)
            if row['grappled'] and row['target'] == target['id'] and row['checkpoint']:
                cp = row['checkpoint']
                break
        self.assertIsNotNone(cp, 'no catchable checkpoint')
        frame.evaluate(START, 9000)
        opened = frame.evaluate(FALL, [2000, None])
        self.assertTrue(opened['paused'] and opened['dialog'] and opened['open'], opened)
        self.assertEqual(opened['buttons'], ['Go back', 'Keep falling'])
        dx, dy = self.offset(page)
        p = frame.evaluate('''() => { const r = CLIMB_UI.buttons[0].background
            return canvasCoordsToViewportCoords({x: r.x + r.width / 2, y: r.y + r.height / 2}) }''')
        page.mouse.move(p['x'] + dx, p['y'] + dy)
        page.mouse.down()
        held = frame.evaluate('() => { for (let i = 0; i < 30; i++) physics(); return STATE() }')
        page.mouse.up()
        rest = frame.evaluate('() => { for (let i = 0; i < 300; i++) physics(); return STATE() }')
        ads = frame.evaluate('() => ({calls: AD_CALLS, mutedSeen: MUTED_SEEN, muted: GAME_AUDIO.muted})')
        self.assertFalse(held['paused'] or held['dialog'])
        for row in (held, rest):
            self.assertTrue(row['grapnel']['grappled'])
            self.assertEqual(row['grapnel']['anchor'], [cp['anchorX'], cp['anchorY']])
            self.assertEqual(row['goBacks'], opened['goBacks'] + 1)
            self.assertEqual(row['recoveries'], 0)
        self.assertEqual(ads, {'calls': [], 'mutedSeen': False, 'muted': False})
        self.evidence['go_back'] = {'checkpoint': cp, 'fall': opened['displacement'],
                                    'goBacks': [opened['goBacks'], rest['goBacks']],
                                    'anchor': rest['grapnel']['anchor'], 'ads': ads}

    def test_05_storage_blocked_sandbox_boots(self):
        page, frame = self.open(sandbox='allow-scripts allow-pointer-lock allow-forms')
        boot = frame.evaluate('window.__bootStore')
        self.assertTrue(str(boot).startswith('blocked'), boot)
        row = frame.evaluate('''async () => ({platformId: PLATFORM.getPlatformId(),
            written: await PLATFORM.storage.setMany({"%s": "m"}),
            read: await PLATFORM.storage.getMany(["%s"]), origin: self.origin})''' % (PROBE_KEY, PROBE_KEY))
        self.assertEqual(row, {'platformId': 'itch', 'written': True, 'read': {PROBE_KEY: 'm'}, 'origin': 'null'})
        self.evidence['opaque_origin'] = {'bootStore': boot, **row}


if __name__ == '__main__':
    unittest.main()
