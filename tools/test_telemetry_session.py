"""Session and environment telemetry (TASK-861), through ANALYTICS.

Documented in docs/platform-sdk.md ("Session telemetry"):
- once per page, right after the game language is applied at boot:
  env:browser:<family> (value: major version), env:os:<family>,
  env:device:<desktop|phone|tablet>, env:input:<touch|mouse>,
  env:screen:<W>x<H>:dpr<D>, env:viewport:<W>x<H>, env:lang:<game>:<browser>;
- every 60 s of active play: perf:fps_p50, perf:fps_p5, perf:frame_ms_p95,
  perf:freezes, then playtime:session:<mode> / playtime:total:<mode> (whole
  seconds) for each grapnel mode with a played second in total;
- pagehide: the playtime events again (after mode_time, before quit:*).
Total play time is kept in localStorage and survives a reload.

test_02 is a scripted ~3-minute headless run: ~96 s single, an 8 s pause,
~90 s double, pagehide; then a reload (the restored run keeps its mode and opens
paused: nothing counts), unpause, ~5 s of play, pagehide.

TELEMETRY_SESSION_EVIDENCE_DIR, when set, receives debuglog.json (the
ANALYTICS.debugLog of both pages plus the measured run segments).

    python3 tools/test_telemetry_session.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402

EVIDENCE = os.environ.get('TELEMETRY_SESSION_EVIDENCE_DIR')
OUT = {}

SINGLE_S = int(os.environ.get('TELEMETRY_SESSION_SINGLE_S', '96'))
PAUSE_S = 8
DOUBLE_S = int(os.environ.get('TELEMETRY_SESSION_DOUBLE_S', '90'))
RELOAD_S = 5

LOG = '() => ANALYTICS.debugLog.map(e => ({t: e.t, fn: e.fn, args: e.args.map(a => a === undefined ? null : a)}))'
PAGEHIDE = "() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))"
NOW = '() => performance.now()'
# The page's own environment, gathered exactly as TELEMETRY.sendEnvironment does
INFO = '''() => ({ua: navigator.userAgent, maxTouchPoints: navigator.maxTouchPoints || 0,
    coarse: matchMedia('(pointer: coarse)').matches,
    screenWidth: window.screen.width, screenHeight: window.screen.height,
    viewWidth: window.innerWidth, viewHeight: window.innerHeight,
    dpr: window.devicePixelRatio, browserLanguage: navigator.language, gameLanguage: I18N.language})'''
ENV_PREFIXES = ['env:browser:', 'env:os:', 'env:device:', 'env:input:', 'env:screen:',
                'env:viewport:', 'env:lang:']
PERF_IDS = ['perf:fps_p50', 'perf:fps_p5', 'perf:frame_ms_p95', 'perf:freezes']
PERF_RANGES = {'perf:fps_p50': (1, 240), 'perf:fps_p5': (1, 240),
               'perf:frame_ms_p95': (0, 250), 'perf:freezes': (0, 1000)}

UA = {
    'iphone_safari': ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
                      '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'),
    'ipad_desktop_mode': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
                          '(KHTML, like Gecko) Version/16.6 Safari/605.1.15'),
    'android_chrome': ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/131.0.0.0 Mobile Safari/537.36'),
    'android_tablet_samsung': ('Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 (KHTML, like Gecko) '
                               'SamsungBrowser/25.0 Chrome/121.0.0.0 Safari/537.36'),
    'windows_edge': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0'),
    'windows_firefox': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
    'mac_chrome': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/130.0.0.0 Safari/537.36'),
    'linux_opera': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/129.0.0.0 Safari/537.36 OPR/115.0.0.0'),
    'cros_chrome': ('Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/130.0.0.0 Safari/537.36'),
    'garbage': 'x' * 300 + ' <script>:"\'',
}
EXPECTED_ENV = {
    'iphone_safari': ['env:browser:safari', 17, 'ios', 'phone', 'touch', '360x800:dpr3', '768x360', 'en:de'],
    'ipad_desktop_mode': ['env:browser:safari', 16, 'ios', 'tablet', 'touch', '1024x1200:dpr2', '1024x1200', 'ru:ru'],
    'android_chrome': ['env:browser:chrome', 131, 'android', 'phone', 'touch', '400x900:dpr2.5', '768x360', 'en:zh'],
    'android_tablet_samsung': ['env:browser:samsung', 25, 'android', 'tablet', 'touch', '768x1200:dpr2', '1280x720', 'en:pt'],
    'windows_edge': ['env:browser:edge', 130, 'windows', 'desktop', 'mouse', '1920x1080:dpr1.25', '1440x720', 'en:en'],
    'windows_firefox': ['env:browser:firefox', 132, 'windows', 'desktop', 'mouse', '2560x1440:dpr1', '1920x900', 'ru:ru'],
    'mac_chrome': ['env:browser:chrome', 130, 'macos', 'desktop', 'mouse', '1440x900:dpr2', '1280x720', 'en:en'],
    'linux_opera': ['env:browser:opera', 115, 'linux', 'desktop', 'mouse', '1366x768:dpr1', '1366x600', 'en:fr'],
    'cros_chrome': ['env:browser:chrome', 130, 'chromeos', 'desktop', 'mouse', '1280x800:dpr1.5', '1280x720', 'en:en'],
    'garbage': ['env:browser:other', 0, 'other', 'desktop', 'mouse', '0x0:dpr1', '0x0', 'other:other'],
}
INFOS = {
    'iphone_safari': dict(maxTouchPoints=5, coarse=True, screenWidth=393, screenHeight=852, viewWidth=852,
                          viewHeight=393, dpr=3, browserLanguage='de-DE', gameLanguage='en'),
    'ipad_desktop_mode': dict(maxTouchPoints=5, coarse=True, screenWidth=1024, screenHeight=1366,
                              viewWidth=1024, viewHeight=1300, dpr=2, browserLanguage='ru', gameLanguage='ru'),
    'android_chrome': dict(maxTouchPoints=5, coarse=True, screenWidth=412, screenHeight=915, viewWidth=915,
                           viewHeight=412, dpr=2.625, browserLanguage='zh-Hans-CN-x-private', gameLanguage='en'),
    'android_tablet_samsung': dict(maxTouchPoints=5, coarse=True, screenWidth=800, screenHeight=1280,
                                   viewWidth=1280, viewHeight=740, dpr=2, browserLanguage='pt-BR',
                                   gameLanguage='en'),
    'windows_edge': dict(coarse=False, screenWidth=1920, screenHeight=1080, viewWidth=1500, viewHeight=760,
                         dpr=1.25, browserLanguage='en-US', gameLanguage='en'),
    'windows_firefox': dict(coarse=False, screenWidth=2560, screenHeight=1440, viewWidth=2000, viewHeight=1000,
                            dpr=1, browserLanguage='ru-RU', gameLanguage='ru'),
    'mac_chrome': dict(maxTouchPoints=0, coarse=False, screenWidth=1440, screenHeight=900, viewWidth=1300,
                       viewHeight=760, dpr=2, browserLanguage='en-GB', gameLanguage='en'),
    'linux_opera': dict(coarse=False, screenWidth=1366, screenHeight=768, viewWidth=1366, viewHeight=650,
                        dpr=1, browserLanguage='fr', gameLanguage='en'),
    'cros_chrome': dict(coarse=False, screenWidth=1280, screenHeight=800, viewWidth=1280, viewHeight=720,
                        dpr=1.5, browserLanguage='en', gameLanguage='en'),
    'garbage': dict(coarse=False, screenWidth=None, screenHeight=-5, viewWidth='x', viewHeight=None,
                    dpr=None, browserLanguage='<b>:x', gameLanguage='<script>'),
}


def designs(entries, prefix):
    return [e for e in entries if e['fn'] == 'addDesignEvent' and e['args'][0].startswith(prefix)]


def ids(entries, prefix=''):
    return [e['args'][0] for e in designs(entries, prefix)]


class SessionTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.errors = []

    def new_page(self):
        page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        return page

    def assert_clean_ids(self, page, raw_ids):
        sanitized = page.evaluate('ids => ids.map(ANALYTICS.sanitizeId)', raw_ids)
        self.assertEqual(sanitized, raw_ids)

    def test_01_classify(self):
        """Environment classes from user agents (pure; the UA itself is never sent)."""
        page = self.new_page()
        page.goto(self.url)
        wait_for_boot_run(page)
        got = {}
        for name, ua in UA.items():
            events = page.evaluate('info => TELEMETRY.classify(info)', dict(INFOS[name], ua=ua))
            got[name] = events
            self.assertEqual([e[0].split(':')[0] + ':' + e[0].split(':')[1] + ':' for e in events], ENV_PREFIXES)
            want = EXPECTED_ENV[name]
            self.assertEqual(events[0], [want[0], want[1]], name)
            self.assertEqual([e[0] for e in events[1:]],
                             ['env:os:' + want[2], 'env:device:' + want[3], 'env:input:' + want[4],
                              'env:screen:' + want[5], 'env:viewport:' + want[6], 'env:lang:' + want[7]], name)
            self.assert_clean_ids(page, [e[0] for e in events])
            for event in events:
                self.assertLessEqual(len(event[0].split(':')), 5)
                self.assertTrue(all(len(s) <= 32 for s in event[0].split(':')), event)
            # No UA fragment beyond the family name and major version
            self.assertNotIn('Mozilla', json.dumps(events))
        OUT['classify'] = got
        page.close()

    def test_02_scripted_session_and_reload(self):
        page = self.new_page()
        page.goto(self.url)
        wait_for_boot_run(page)
        info = page.evaluate(INFO)
        boot = page.evaluate(LOG)
        # Start events: exactly once each, after startSession, ids == classify(page env)
        fns = [e['fn'] for e in boot]
        self.assertEqual(fns[:2], ['initialize', 'startSession'], fns)
        env = designs(boot, 'env:')
        self.assertEqual(len(env), 7, env)
        raw = page.evaluate('info => TELEMETRY.classify(info)', info)
        self.assertEqual([[e['args'][0], e['args'][1]] for e in env],
                         [[r[0], r[1] if len(r) > 1 else None] for r in raw])
        self.assert_clean_ids(page, [r[0] for r in raw])
        self.assertEqual([e['args'][0] for e in env],
                         ['env:browser:chrome', 'env:os:linux', 'env:device:desktop', 'env:input:mouse',
                          'env:screen:1280x720:dpr1', 'env:viewport:1280x720', 'env:lang:en:en'])
        self.assertTrue(100 <= env[0]['args'][1] <= 999, env[0])
        self.assertTrue(all(fns.index('startSession') < boot.index(e) for e in env))

        # Scripted run: single, pause (not counted), double
        page.evaluate('floors[0].doubleOfferShown = true')
        self.assertEqual(page.evaluate('floors[0].grapnelMode'), 'single')
        self.assertEqual(page.evaluate('localStorage.getItem("grapnelninja_playtime_v1")'), None)
        t0, pt0 = page.evaluate('() => [performance.now(), TELEMETRY.playTime()]')
        page.wait_for_timeout(SINGLE_S * 1000)
        t_switch = page.evaluate('() => { const t = performance.now(); CLIMB_UI.toggleGrapnel(); return t }')
        self.assertEqual(page.evaluate('floors[0].grapnelMode'), 'double')
        page.wait_for_timeout(2000)
        t_pause = page.evaluate('() => { menu.startPause(); return performance.now() }')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        page.wait_for_timeout(PAUSE_S * 1000)
        t_unpause = page.evaluate('() => { menu.unPause(); return performance.now() }')
        page.wait_for_timeout((DOUBLE_S - 2) * 1000)
        state = page.evaluate('() => [menu.gamePaused, continueOffer.visible, runInProgress]')
        self.assertEqual(state, [False, False, True], 'the run must stay in play')
        t_end = page.evaluate(NOW)
        played = page.evaluate('TELEMETRY.playTime()')
        hide = len(page.evaluate(LOG))
        page.evaluate(PAGEHIDE)
        log = page.evaluate(LOG)
        stored = json.loads(page.evaluate('localStorage.getItem("grapnelninja_playtime_v1")'))

        expect = {'single': pt0['session']['single'] / 1000 + (t_switch - t0) / 1000,
                  'double': ((t_pause - t_switch) + (t_end - t_unpause)) / 1000}
        segments = {'t0': t0, 'switch': t_switch, 'pause': t_pause, 'unpause': t_unpause, 'end': t_end,
                    'boot_single_ms': pt0['session']['single'], 'expected_s': expect,
                    'counted_ms': played, 'stored_ms': stored}
        OUT['page1'] = {'info_ua_family': env[0]['args'][0], 'segments': segments, 'debugLog': log}

        # Active play (wall clock) is >= 3 minutes
        self.assertGreaterEqual(expect['single'] + expect['double'], 180)
        # Pagehide play time: once per mode, before quit:*, values match the run within 1 s
        tail = log[hide:]
        self.assertEqual(ids(tail, 'playtime:'), ['playtime:session:single', 'playtime:total:single',
                                                 'playtime:session:double', 'playtime:total:double'])
        tail_ids = ids(tail)
        quit = [i for i, x in enumerate(tail_ids) if x.startswith('quit:')]
        if quit:
            self.assertLess(tail_ids.index('playtime:total:double'), quit[0])
        final = {e['args'][0]: e['args'][1] for e in designs(tail, 'playtime:')}
        for mode in ('single', 'double'):
            self.assertLessEqual(abs(final['playtime:session:' + mode] - expect[mode]), 1.0,
                                 (mode, final, expect))
            # Fresh profile: total == session, and it is what localStorage holds
            self.assertEqual(final['playtime:total:' + mode], final['playtime:session:' + mode])
            self.assertEqual(final['playtime:total:' + mode], int(stored[mode] // 1000))
        self.assertEqual(tail[-1]['fn'], 'endSession')

        # One perf group per active minute, each followed by the play time events
        active_ms = played['session']['single'] + played['session']['double']
        minutes = int(active_ms // 60000)
        self.assertEqual(minutes, 3, active_ms)
        body = log[:hide]
        for pid in PERF_IDS:
            self.assertEqual(ids(body).count(pid), minutes, pid)
        perf = designs(body, 'perf:')
        self.assertEqual([e['args'][0] for e in perf], PERF_IDS * minutes)
        for e in perf:
            low, high = PERF_RANGES[e['args'][0]]
            self.assertTrue(isinstance(e['args'][1], (int, float)) and low <= e['args'][1] <= high, e)
        for k in range(minutes):
            group = perf[4 * k: 4 * k + 4]
            fps50, fps5, p95 = (g['args'][1] for g in group[:3])
            self.assertLessEqual(fps5, fps50, group)
            self.assertAlmostEqual(fps5, 1000 / max(p95, 0.05), delta=max(1.5, fps5 * 0.05))
            start = body.index(group[-1]) + 1
            after = [e for e in body[start:start + 4] if e['fn'] == 'addDesignEvent']
            minute = {e['args'][0]: e['args'][1] for e in after if e['args'][0].startswith('playtime:')}
            # Session seconds of both modes add up to the minute mark (floor per mode)
            session = minute.get('playtime:session:single', 0) + minute.get('playtime:session:double', 0)
            self.assertTrue(60 * (k + 1) - 2 <= session <= 60 * (k + 1), (k, minute))
            self.assertIn('playtime:session:single', minute)
        periodic_single = [e['args'][1] for e in designs(body, 'playtime:session:single')]
        self.assertEqual(len(periodic_single), minutes)
        self.assertEqual(periodic_single, sorted(periodic_single))
        # Each minute group's single seconds track the scripted single segment
        self.assertLessEqual(abs(periodic_single[-1] - expect['single']), 1.0)
        # Every logged id is already clean (the sanitizer leaves it unchanged)
        self.assert_clean_ids(page, ids(log))
        self.assertTrue(all(len(i.split(':')) <= 5 for i in ids(log)))

        # Reload: total play time survives; the start events are sent once again.
        # The restored run keeps its saved grapnel mode (double here).
        page.reload()
        wait_for_boot_run(page)
        page.evaluate('floors[0].doubleOfferShown = true')
        mode2 = page.evaluate('floors[0].grapnelMode')
        other = 'single' if mode2 == 'double' else 'double'
        boot2 = page.evaluate(LOG)
        self.assertEqual(len(designs(boot2, 'env:')), 7)
        restored = page.evaluate('TELEMETRY.playTime()')
        for mode in ('single', 'double'):
            self.assertAlmostEqual(restored['total'][mode] - restored['session'][mode], stored[mode], delta=1)
        # A restored run opens paused (resume screen): nothing counts until unpaused
        if page.evaluate('menu.gamePaused'):
            page.wait_for_timeout(1000)
            self.assertEqual(page.evaluate('TELEMETRY.playTime().session'), {'single': 0, 'double': 0})
            page.evaluate('menu.unPause()')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        page.wait_for_timeout(RELOAD_S * 1000)
        played2 = page.evaluate('TELEMETRY.playTime()')
        hide2 = len(page.evaluate(LOG))
        page.evaluate(PAGEHIDE)
        log2 = page.evaluate(LOG)
        final2 = {e['args'][0]: e['args'][1] for e in designs(log2[hide2:], 'playtime:')}
        self.assertTrue(RELOAD_S - 1 <= final2['playtime:session:' + mode2] <= RELOAD_S + 3, final2)
        self.assertEqual(final2['playtime:session:' + other], 0)
        self.assertEqual(final2['playtime:total:' + other], final['playtime:total:' + other])
        self.assertLessEqual(abs(final2['playtime:total:' + mode2]
                                 - (stored[mode2] + played2['session'][mode2]) / 1000), 1.0)
        self.assertGreaterEqual(final2['playtime:total:' + mode2],
                                final['playtime:total:' + mode2] + final2['playtime:session:' + mode2])
        self.assertEqual(json.loads(page.evaluate('localStorage.getItem("grapnelninja_playtime_v1")'))[other],
                         stored[other])
        self.assert_clean_ids(page, ids(log2))
        OUT['page2'] = {'mode': mode2, 'restored_ms': restored, 'counted_ms': played2, 'debugLog': log2}
        page.close()

    def test_03_stall_and_synthetic_minutes(self):
        """A huge frame gap sends at most one group and counts as <= 1 s of play;
        synthetic 20 ms frames send exactly one group per 60 s."""
        page = self.new_page()
        page.goto(self.url)
        wait_for_boot_run(page)
        got = page.evaluate('''() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
            const groups = () => ANALYTICS.debugLog.filter(e => e.args[0] === 'perf:fps_p50').length
            const mode = floors[0].grapnelMode
            const before = TELEMETRY.playTime().session[mode], g0 = groups()
            let t = performance.now() + 1e9
            TELEMETRY.frame(t, true, version, mode)
            for (let i = 0; i < 100; i++) TELEMETRY.frame(t += 20, true, version, mode)
            const stall = {groups: groups() - g0, playedMs: TELEMETRY.playTime().session[mode] - before}
            const g1 = groups()
            for (let i = 0; i < 3000 * 5; i++) TELEMETRY.frame(t += 20, true, version, mode)
            return {stall, minutes: groups() - g1} }''')
        self.assertLessEqual(got['stall']['groups'], 1, got)
        self.assertLessEqual(got['stall']['playedMs'], 1000 + 100 * 20 + 1, got)
        self.assertIn(got['minutes'], (4, 5), got)
        OUT['stall'] = got
        page.close()

    def test_04_no_page_errors(self):
        self.assertEqual(self.errors, [])


def tearDownModule():
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'debuglog.json').write_text(json.dumps(OUT, indent=1))


if __name__ == '__main__':
    unittest.main()
