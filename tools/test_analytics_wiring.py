"""Telemetry wiring: session, page errors and ad results reach ANALYTICS.

Boot calls ANALYTICS.init({build}) + sessionStart() once after PLATFORM.init;
window 'error' / 'unhandledrejection' -> ANALYTICS.error('error',
'<message> @ <file>:<line>'), deduplicated, at most 10 per session;
PLATFORM.showInterstitial/showRewarded results -> ANALYTICS.ad (none for
'skipped'/'unavailable'); pagehide -> one sessionEnd per page.

ANALYTICS_WIRING_EVIDENCE_DIR, when set, receives debuglog.json: compact
[[fn, args], ...] of ANALYTICS.debugLog at the end of the test.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
READY = ('PLATFORM.environment !== "pending" && bootComplete && runInProgress'
         ' && document.getElementById("loading").hidden')
LOG = '() => ANALYTICS.debugLog.map(e => [e.fn, e.args.map(a => a === undefined ? null : a)])'

# 12 page errors, 2 of them repeat an earlier message -> 10 unique
ERRORS = ['probe %d' % i for i in range(9)] + ['probe 0', 'probe 1']
REJECTION = 'rejected probe'
# After the cap: new unique messages that must be dropped
OVER_CAP = ['late probe %d' % i for i in range(3)]

THROW = r'''async (messages) => {
    for (const m of messages)
        setTimeout(() => { throw new Error(m) })
    await new Promise(r => setTimeout(r, 50))
}'''
REJECT = r'''async (message) => {
    Promise.reject(new Error(message))
    await new Promise(r => setTimeout(r, 50))
}'''

# (method, stubbed inner result, expected ANALYTICS inner call args or None)
ADS = [
    ('showInterstitial', 'closed', ['show', 'interstitial', 'grapnelninja', 'game_over']),
    ('showInterstitial', 'failed', ['failed_show', 'interstitial', 'grapnelninja', 'game_over']),
    ('showInterstitial', 'skipped', None),
    ('showRewarded', 'rewarded', ['reward_received', 'rewarded', 'grapnelninja', 'continue']),
    ('showRewarded', 'closed', ['show', 'rewarded', 'grapnelninja', 'continue']),
    ('showRewarded', 'failed', ['failed_show', 'rewarded', 'grapnelninja', 'continue']),
    ('showRewarded', 'skipped', None),
    ('showRewarded', 'unavailable', None),
]
AD = r'''async ([method, value]) => {
    const saved = PLATFORM_BACKEND[method]
    PLATFORM_BACKEND[method] = () => Promise.resolve(value)
    const before = ANALYTICS.debugLog.length
    let result
    try {
        result = await PLATFORM[method](method === 'showRewarded' ? 'continue' : 'game_over')
    } finally {
        PLATFORM_BACKEND[method] = saved
    }
    return {result, added: ANALYTICS.debugLog.slice(before).map(e => [e.fn, e.args])}
}'''


class AnalyticsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('ANALYTICS_WIRING_EVIDENCE_DIR')
        context, cls.page, cls.errors = open_game(cls.browser, 'about:blank', VIEWPORT)
        cls.addClassCleanup(context.close)
        cls.page.goto(cls.url + 'index.html')
        cls.page.wait_for_function(READY)
        cls.page.evaluate('() => { runFixedPhysics = function () {} }')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            log = cls.page.evaluate(LOG)
            (out / 'debuglog.json').write_text(json.dumps(log, separators=(',', ':')) + '\n')

    def log(self):
        return self.page.evaluate(LOG)

    def test_01_boot_init_then_session_start_once(self):
        log = self.log()
        build = self.page.evaluate('PLATFORM.buildVersion')
        self.assertEqual(log[:2], [['initialize', [{'build': build}]], ['startSession', []]])
        self.assertEqual([e[0] for e in log].count('initialize'), 1)
        self.assertEqual([e[0] for e in log].count('startSession'), 1)
        self.assertEqual(self.errors['page'], [])
        print('  boot: initialize(%s), startSession once' % build, file=sys.stderr)

    def test_02_page_errors_deduplicated_and_capped(self):
        self.page.evaluate(THROW, ERRORS[:-1])
        self.page.evaluate(REJECT, REJECTION)
        self.page.evaluate(THROW, ERRORS[-1:])
        self.assertEqual(len(self.errors['page']), 12)
        errors = [e[1] for e in self.log() if e[0] == 'addErrorEvent']
        self.assertEqual(len(errors), 10)
        self.assertEqual(len({m for _, m in errors}), 10)
        self.assertTrue(all(s == 'error' for s, _ in errors))
        texts = [m for _, m in errors]
        for i in range(9):
            self.assertEqual(sum(('Error: probe %d @ ' % i) in t for t in texts), 1, i)
        self.assertIn(REJECTION + ' @ promise:0', texts)
        # Cap reached: more unique messages send nothing
        self.page.evaluate(THROW, OVER_CAP)
        self.assertEqual(len([e for e in self.log() if e[0] == 'addErrorEvent']), 10)
        print('  errors: 12 injected (2 duplicates) -> %d unique; +3 after cap -> still 10'
              % len(errors), file=sys.stderr)
        print('  sample: %s' % texts[0], file=sys.stderr)

    def test_03_ad_results(self):
        for method, value, expected in ADS:
            with self.subTest(method=method, value=value):
                got = self.page.evaluate(AD, [method, value])
                want = [['addAdEvent', expected]] if expected else []
                self.assertEqual(got['added'], want)
                print('  %s %s -> %s' % (method, value, expected[0] if expected else 'no event'),
                      file=sys.stderr)

    def test_04_pagehide_session_end_once(self):
        self.page.evaluate('''() => {
            window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))
            window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))
        }''')
        ends = [e for e in self.log() if e[0] == 'endSession']
        self.assertEqual(ends, [['endSession', []]])
        print('  pagehide x2 -> endSession x%d' % len(ends), file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
