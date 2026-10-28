"""ANALYTICS facade (analytics.js) over the swappable ANALYTICS_BACKEND.

analytics/backends/none.js defines ANALYTICS_BACKEND with no-op inner
methods; analytics.js sanitizes every call (GameAnalytics id rules), records
it in ANALYTICS.debugLog and delegates, never throwing into the game.

ANALYTICS_FACADE_EVIDENCE_DIR, when set, receives cases.json: compact
[{name, input, sanitized}] for every sanitization case (sanitized is the
delegated inner-method args, or null when the call was dropped).
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

# Appended to none.js: records every inner call as [fn, args]
SPY = r'''
;(() => {
    window.__analyticsHits = []
    for (const name of Object.keys(ANALYTICS_BACKEND)) {
        const original = ANALYTICS_BACKEND[name]
        if (typeof original !== 'function') continue
        ANALYTICS_BACKEND[name] = function (...args) {
            window.__analyticsHits.push([name, args.map(a => a === undefined ? null : a)])
            return original.apply(this, args)
        }
    }
})()
'''

# Runs one facade call with an empty spy; returns the inner calls it caused
CALL = r'''([fn, args]) => {
    window.__analyticsHits = []
    const r = ANALYTICS[fn](...args)
    return {result: r === undefined ? null : r, hits: window.__analyticsHits}
}'''

LONG = 'a' * 40
# name -> (facade method, args, expected inner call [fn, args] or None = dropped)
CASES = {
    'design_spaces_and_bang': ('design', ['fall:S03 room!'],
                               ['addDesignEvent', ['fall:S03_room_', None]]),
    'design_value': ('design', ['grapple:attach', 3.5], ['addDesignEvent', ['grapple:attach', 3.5]]),
    'design_six_segments_to_five': ('design', ['a:b:c:d:e:f'], ['addDesignEvent', ['a:b:c:d:e', None]]),
    'design_40_char_segment_to_32': ('design', ['x:' + LONG], ['addDesignEvent', ['x:' + 'a' * 32, None]]),
    'design_empty_segments_dropped': ('design', ['::fall::S03:'], ['addDesignEvent', ['fall:S03', None]]),
    'design_unicode_replaced': ('design', ['vershina:Высота'], ['addDesignEvent', ['vershina:______', None]]),
    'design_allowed_chars_kept': ('design', ['A-z_0.9'], ['addDesignEvent', ['A-z_0.9', None]]),
    'design_empty_id_dropped': ('design', [''], None),
    'design_only_colons_dropped': ('design', [':::'], None),
    'design_non_number_value_dropped': ('design', ['fall', 'x'], ['addDesignEvent', ['fall', None]]),
    'progression_three_levels': ('progression', ['Complete', 'grapple over', 'S03', 'room 2', 1234],
                                 ['addProgressionEvent', ['Complete', 'grapple_over', 'S03', 'room_2', 1234]]),
    'progression_level1_only': ('progression', ['Start', 'climb'],
                                ['addProgressionEvent', ['Start', 'climb', None, None, None]]),
    'progression_level3_without_level2_normalized': (
        'progression', ['Fail', 'climb', None, 'S07'],
        ['addProgressionEvent', ['Fail', 'climb', 'S07', None, None]]),
    'progression_level3_empty_level2_normalized': (
        'progression', ['Fail', 'climb', '', 'S07', 5],
        ['addProgressionEvent', ['Fail', 'climb', 'S07', None, 5]]),
    'progression_level_colon_replaced': ('progression', ['Start', 'a:b'],
                                         ['addProgressionEvent', ['Start', 'a_b', None, None, None]]),
    'progression_40_char_level_to_32': ('progression', ['Start', LONG],
                                        ['addProgressionEvent', ['Start', 'a' * 32, None, None, None]]),
    'progression_bad_status_dropped': ('progression', ['Finish', 'climb'], None),
    'progression_lowercase_status_dropped': ('progression', ['start', 'climb'], None),
    'progression_no_level1_dropped': ('progression', ['Start', None, 'S03'], None),
    'error_severity_kept': ('error', ['warning', 'slow frame'], ['addErrorEvent', ['warning', 'slow frame']]),
    'error_bad_severity_dropped': ('error', ['fatal', 'x'], None),
    'error_message_trimmed_8000': ('error', ['error', 'm' * 9000], ['addErrorEvent', ['error', 'm' * 8000]]),
    'ad_placement_sanitized': ('ad', ['Show', 'Interstitial', 'game over'],
                               ['addAdEvent', ['Show', 'Interstitial', 'grapnelninja', 'game_over']]),
    'init_build': ('init', [{'build': 'v20'}], ['initialize', [{'build': 'v20'}]]),
}

# Every public method -> (args, the inner method it must reach)
DELEGATION = {
    'init': ([{'build': 'test'}], 'initialize'),
    'sessionStart': ([], 'startSession'),
    'sessionEnd': ([], 'endSession'),
    'progression': (['Start', 'climb'], 'addProgressionEvent'),
    'design': (['fall:S03'], 'addDesignEvent'),
    'error': (['info', 'hello'], 'addErrorEvent'),
    'ad': (['Clicked', 'RewardedVideo', 'continue'], 'addAdEvent'),
}


def short(value):
    """Long repeated strings in cases.json as '<c>*<n>' to keep it compact."""
    if isinstance(value, str) and len(value) > 64 and len(set(value)) == 1:
        return '%s*%d' % (value[0], len(value))
    if isinstance(value, list):
        return [short(v) for v in value]
    return value


class AnalyticsFacadeTests(unittest.TestCase):
    cases = []

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('ANALYTICS_FACADE_EVIDENCE_DIR')
        context, cls.page, cls.errors = open_game(cls.browser, 'about:blank', VIEWPORT)
        cls.addClassCleanup(context.close)
        context.route('**/analytics/backends/none.js', cls.append(SPY))
        cls.page.goto(cls.url + 'index.html')
        cls.page.wait_for_function(READY)
        cls.page.evaluate('() => { runFixedPhysics = function () {} }')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'cases.json').write_text(json.dumps(cls.cases, separators=(',', ':'),
                                                       ensure_ascii=False) + '\n')

    @staticmethod
    def append(code):
        def handler(route):
            response = route.fetch()
            route.fulfill(response=response, body=response.text() + code)
        return handler

    def call(self, fn, args):
        return self.page.evaluate(CALL, [fn, args])

    def tearDown(self):
        self.assertEqual((self.errors['console'], self.errors['page']), ([], []))

    def test_01_scripts_load_after_platform(self):
        order = self.page.evaluate('''() => [...document.scripts].map(s => s.getAttribute('src'))
            .filter(s => s && /platform|analytics/.test(s))''')
        self.assertEqual(order, ['platform/backends/local.js', 'platform.js',
                                 'analytics/backends/none.js', 'analytics.js'])
        self.assertEqual(self.page.evaluate('ANALYTICS_BACKEND.backendId'), 'none')
        # Boot (TASK-750) sends only init + sessionStart
        self.assertEqual(self.page.evaluate('ANALYTICS.debugLog.map(e => e.fn)'),
                         ['initialize', 'startSession'])

    def test_02_sanitization_cases(self):
        for name, (fn, args, expected) in CASES.items():
            with self.subTest(name):
                got = self.call(fn, args)
                self.assertIsNone(got['result'])
                self.assertEqual(got['hits'], [expected] if expected else [], name)
                type(self).cases.append({'name': name, 'input': short([fn] + args),
                                         'sanitized': short(expected)})
                print('  case %s: %s' % (name, 'dropped' if expected is None else 'ok'),
                      file=sys.stderr)

    def test_03_delegation_spy_per_method(self):
        for fn, (args, inner) in DELEGATION.items():
            with self.subTest(fn):
                hits = self.call(fn, args)['hits']
                self.assertEqual([h[0] for h in hits], [inner], fn)
                print('  delegate %s -> %s' % (fn, inner), file=sys.stderr)
        sdk = self.call('ad', ['Show', 'Banner', 'menu'])['hits'][0][1][2]
        self.assertEqual(sdk, 'grapnelninja')

    def test_04_throwing_backend_never_throws(self):
        result = self.page.evaluate(r'''(calls) => {
            const saved = Object.assign({}, ANALYTICS_BACKEND)
            const warns = []
            const warn = console.warn
            console.warn = (...a) => warns.push(a.join(' '))
            for (const name of Object.keys(saved))
                if (typeof saved[name] === 'function')
                    ANALYTICS_BACKEND[name] = () => { throw new Error('analytics probe ' + name) }
            const thrown = []
            try {
                for (const [fn, args] of Object.entries(calls))
                    for (let i = 0; i < 2; i++)
                        try { ANALYTICS[fn](...args) } catch (e) { thrown.push(fn) }
                // Bad arguments that would throw inside the facade itself
                const evil = {toString() { throw new Error('evil') }}
                for (const fn of Object.keys(calls))
                    try { ANALYTICS[fn](evil, evil, evil) } catch (e) { thrown.push(fn + ':evil') }
                // A missing backend
                const backend = ANALYTICS_BACKEND
                ANALYTICS_BACKEND = undefined
                try { ANALYTICS.design('x') } catch (e) { thrown.push('missing') }
                ANALYTICS_BACKEND = backend
            } finally {
                Object.assign(ANALYTICS_BACKEND, saved)
                console.warn = warn
            }
            return {thrown, warns}
        }''', {fn: args for fn, (args, _) in DELEGATION.items()})
        self.assertEqual(result['thrown'], [])
        inner = [w for w in result['warns'] if w.startswith('ANALYTICS_BACKEND.')]
        # One warning per failing method, even though each was called twice
        self.assertEqual(sorted(set(inner)), sorted(inner))
        for _, name in DELEGATION.values():
            self.assertTrue(any(w.startswith('ANALYTICS_BACKEND.%s failed' % name) for w in inner), name)
        print('  thrown=%d warns=%d' % (len(result['thrown']), len(result['warns'])), file=sys.stderr)

    def test_05_debug_log_bounded_and_sanitized(self):
        log = self.page.evaluate('''() => {
            for (let i = 0; i < 600; i++) ANALYTICS.design('loop:' + i + ' x')
            ANALYTICS.design('')
            return {len: ANALYTICS.debugLog.length, first: ANALYTICS.debugLog[0],
                    last: ANALYTICS.debugLog[ANALYTICS.debugLog.length - 1]}
        }''')
        self.assertEqual(log['len'], 500)
        self.assertEqual(log['first']['fn'], 'addDesignEvent')
        self.assertEqual(log['first']['args'][0], 'loop:100_x')
        self.assertEqual(log['last']['args'][0], 'loop:599_x')
        self.assertIsInstance(log['last']['t'], (int, float))


if __name__ == '__main__':
    unittest.main()
