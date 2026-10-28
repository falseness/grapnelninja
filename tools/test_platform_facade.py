"""PLATFORM facade (platform.js) over the swappable PLATFORM_BACKEND.

platform/backends/local.js defines PLATFORM_BACKEND, the inner methods;
platform.js keeps the public PLATFORM API and routes every method through
one delegate helper that returns a documented default when the inner method
throws, rejects or is missing.

PLATFORM_FACADE_EVIDENCE_DIR, when set, receives api.json (public members
of the pre-facade platform.js at eb3ab8a vs the working tree),
facade-results.json and returns.json (every TASK-746 method called once on
the local backend: {method: returnedValue}).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
READY = ('PLATFORM.environment !== "pending" && bootComplete && runInProgress'
         ' && document.getElementById("loading").hidden')
PROBE_KEY = 'grapnelninja.facadeProbe'
# Last commit before the facade split (TASK-745): the API baseline
PRE_FACADE = 'eb3ab8a'

# Every public method (getters included) -> (JS that calls it through the
# facade, the documented default when the inner method fails). init is
# checked at boot (its promise is cached), see test_04.
CALLS = {
    'now': ('PLATFORM.now()', None),
    'isInterstitialSupported': ('PLATFORM.isInterstitialSupported()', False),
    'isInterstitialDue': ('PLATFORM.isInterstitialDue()', False),
    'showInterstitial': ('PLATFORM.showInterstitial("game_over")', 'skipped'),
    'sendMessage': ('PLATFORM.sendMessage("facade_probe")', None),
    'sendLifecycle': ('PLATFORM.sendLifecycle("facade_probe", {a: 1})', None),
    'track': ('PLATFORM.track("facade_probe", {a: 1})', None),
    'startup': ('PLATFORM.startup("facade_probe", "classic")', None),
    'gameReady': ('PLATFORM.gameReady()', None),
    'readiness': ('PLATFORM.readiness', {'state': 'local'}),
    'isAudioEnabled': ('PLATFORM.isAudioEnabled()', True),
    'onPause': ('PLATFORM.onPause(() => {})', None),
    'onAudio': ('PLATFORM.onAudio(() => {})', None),
    'onAdState': ('PLATFORM.onAdState(() => {})', None),
    'storage.remoteKnown': ('PLATFORM.storage.remoteKnown', True),
    'storage.onRecovery': ('PLATFORM.storage.onRecovery(() => {})', None),
    'storage.getMany': ('PLATFORM.storage.getMany(["%s"])' % PROBE_KEY, {PROBE_KEY: None}),
    'storage.setMany': ('PLATFORM.storage.setMany({})', False),
    # TASK-746 cross-portal methods
    'loadingProgress': ('PLATFORM.loadingProgress(42)', None),
    'gameplayStart': ('PLATFORM.gameplayStart("classic")', None),
    'gameplayStop': ('PLATFORM.gameplayStop("death", "classic")', None),
    'happyMoment': ('PLATFORM.happyMoment()', None),
    'isRewardedSupported': ('PLATFORM.isRewardedSupported()', False),
    'showRewarded': ('PLATFORM.showRewarded("continue")', 'unavailable'),
    'showBanner': ('PLATFORM.showBanner("bottom")', None),
    'hideBanner': ('PLATFORM.hideBanner()', None),
    'submitScore': ('PLATFORM.submitScore("height", 1234)', False),
    'unlockAchievement': ('PLATFORM.unlockAchievement("summit")', False),
    'getLanguage': ('PLATFORM.getLanguage()', 'en'),
    'getPlatformId': ('PLATFORM.getPlatformId()', 'local'),
}
# Members added after the pre-facade baseline (TASK-746)
NEW_METHODS = ['getLanguage', 'getPlatformId', 'gameplayStart', 'gameplayStop', 'happyMoment',
               'hideBanner', 'isRewardedSupported', 'loadingProgress', 'showBanner', 'showRewarded',
               'submitScore', 'unlockAchievement']
# Local backend return values (same as the defaults; getLanguage is the
# detected en-US -> 'en')
LOCAL_RETURNS = {m: CALLS[m][1] for m in NEW_METHODS}
METHODS = sorted(CALLS) + ['init']

# Sorted public members: 'name:typeof' with getters read, storage.* nested,
# plus the non-function values and the shapes the methods return.
API = r'''async () => {
    const members = []
    const values = {}
    function walk(obj, prefix) {
        for (const name of Object.getOwnPropertyNames(obj)) {
            const path = prefix + name
            const desc = Object.getOwnPropertyDescriptor(obj, name)
            const value = obj[name]
            members.push(path + ':' + typeof value + (desc.get ? ':getter' : ''))
            if (path === 'storage') walk(value, 'storage.')
            else if (typeof value !== 'function') values[path] = value
        }
    }
    walk(PLATFORM, '')
    const returns = {
        isInterstitialSupported: PLATFORM.isInterstitialSupported(),
        isInterstitialDue: PLATFORM.isInterstitialDue(),
        showInterstitial: await PLATFORM.showInterstitial('game_over'),
        sendMessage: String(await PLATFORM.sendMessage('facade_probe')),
        sendLifecycle: String(await PLATFORM.sendLifecycle('facade_probe')),
        track: String(PLATFORM.track('facade_probe')),
        startup: String(PLATFORM.startup('facade_probe')),
        gameReady: String(await PLATFORM.gameReady()),
        init: await PLATFORM.init(),
        isAudioEnabled: PLATFORM.isAudioEnabled(),
        nowType: typeof PLATFORM.now(),
        getMany: await PLATFORM.storage.getMany(['%s']),
        setMany: await PLATFORM.storage.setMany({}),
    }
    return {members: members.sort(), values, returns}
}''' % PROBE_KEY

# Appended to local.js: wraps every inner method so each call is recorded
SPY = r'''
;(() => {
    window.__backendHits = {}
    function wrap(obj, prefix) {
        for (const name of Object.keys(obj)) {
            const path = prefix + name
            if (name === 'storage') { wrap(obj[name], 'storage.'); continue }
            const original = obj[name]
            if (typeof original !== 'function') continue
            obj[name] = function (...args) {
                (window.__backendHits[path] = window.__backendHits[path] || []).push(
                    args.map(a => typeof a === 'function' ? 'function' : a))
                return original.apply(this, args)
            }
        }
    }
    wrap(PLATFORM_BACKEND, '')
})()
'''

# Replaces (or deletes) one inner method, then calls the facade
BREAK = r'''async ([path, call, mode]) => {
    const parts = path.split('.')
    const owner = parts.length > 1 ? PLATFORM_BACKEND[parts[0]] : PLATFORM_BACKEND
    const name = parts[parts.length - 1]
    const original = owner[name]
    if (mode === 'throw') owner[name] = () => { throw new Error('facade probe ' + path) }
    else if (mode === 'reject') owner[name] = () => Promise.reject(new Error('facade probe ' + path))
    else delete owner[name]
    try {
        const result = await eval(call)
        return {result: result === undefined ? null : result, type: typeof result}
    } finally {
        owner[name] = original
    }
}'''

ASYNC = {'showInterstitial', 'sendMessage', 'sendLifecycle', 'gameReady',
         'storage.getMany', 'storage.setMany',
         'showRewarded', 'showBanner', 'hideBanner', 'submitScore', 'unlockAchievement'}


class PlatformFacadeTests(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('PLATFORM_FACADE_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'facade-results.json').write_text(
                json.dumps(cls.results, separators=(',', ':'), sort_keys=True) + '\n')

    def boot(self, routes=(), locale='en-US'):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT, locale=locale)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        for pattern, handler in routes:
            context.route(pattern, handler)
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        page.evaluate('() => { runFixedPhysics = function () {} }')
        return page

    @staticmethod
    def append(code):
        def handler(route):
            response = route.fetch()
            route.fulfill(response=response, body=response.text() + code)
        return handler

    def test_01_api_unchanged_from_pre_facade(self):
        # The pre-facade members, values and return shapes are unchanged; the
        # only additions are the TASK-746 methods
        head = subprocess.run(['git', 'show', PRE_FACADE + ':platform.js'], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout
        self.assertNotIn('PLATFORM_BACKEND', head, 'the baseline must be the pre-facade platform.js')
        # The game calls the TASK-746 methods since TASK-748: the baseline boots
        # with no-op stand-ins, removed again before its API is read
        shim = ';window.__shim = %s.filter(m => !(m in PLATFORM));' \
               '__shim.forEach(m => { PLATFORM[m] = function () {} })' % json.dumps(NEW_METHODS)
        serve_head = lambda route: route.fulfill(body=head + shim, content_type='application/javascript')
        baseline = self.boot([('**/platform.js', serve_head)])
        self.assertEqual(baseline.evaluate('__shim.splice(0).filter(m => delete PLATFORM[m])'),
                         NEW_METHODS)
        before = baseline.evaluate(API)
        after = self.boot().evaluate(API)
        self.assertGreater(len(after['members']), 20)
        added = sorted(set(after['members']) - set(before['members']))
        self.assertEqual(added, sorted(m + ':function' for m in NEW_METHODS))
        self.assertEqual(sorted(set(before['members']) - set(after['members'])), [])
        self.assertEqual(before['values'], after['values'])
        self.assertEqual(before['returns'], after['returns'])
        equal = not set(before['members']) - set(after['members']) and \
            before['values'] == after['values'] and before['returns'] == after['returns']
        self.results['api'] = {'members': len(after['members']), 'equal': equal, 'added': added}
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'api.json').write_text(json.dumps(
                {'before': before['members'], 'after': after['members'], 'equal': equal, 'added': added,
                 'valuesEqual': before['values'] == after['values'],
                 'returnsEqual': before['returns'] == after['returns'],
                 'values': after['values'], 'returns': after['returns']},
                separators=(',', ':')) + '\n')

    def test_02_every_method_delegates(self):
        page = self.boot([('**/platform/backends/local.js', self.append(SPY))])
        members = page.evaluate(API)['members']
        methods = sorted(m.split(':')[0] for m in members
                         if m.split(':')[1] == 'function' or m.endswith(':getter'))
        self.assertEqual(methods, sorted(METHODS), 'every public method is covered')
        # init ran at boot; the rest are called once each now
        page.evaluate('() => { window.__backendHits = {init: window.__backendHits.init} }')
        for path, (call, _) in CALLS.items():
            page.evaluate('async () => { await %s }' % call)
        hits = page.evaluate('window.__backendHits')
        missing = [m for m in METHODS if not hits.get(m)]
        self.assertEqual(missing, [])
        self.assertEqual(hits['sendLifecycle'][-1], ['facade_probe', {'a': 1}])
        self.assertEqual(hits['storage.getMany'][-1], [[PROBE_KEY]])
        self.assertEqual(hits['onPause'][-1], ['function'])
        self.assertEqual(hits['gameplayStop'][-1], ['death', 'classic'])
        self.assertEqual(hits['submitScore'][-1], ['height', 1234])
        self.assertEqual(hits['showRewarded'][-1], ['continue'])
        self.results['delegation'] = {m: len(hits[m]) for m in METHODS}

    def check_defaults(self, mode):
        page = self.boot()
        got = {}
        for path, (call, default) in CALLS.items():
            if mode == 'reject' and path not in ASYNC:
                continue
            outcome = page.evaluate(BREAK, [path, call, mode])
            got[path] = outcome['result']
            with self.subTest(path=path, mode=mode):
                if path == 'now':
                    self.assertEqual(outcome['type'], 'number')
                else:
                    self.assertEqual(outcome['result'], default)
        # The game keeps running on the healthy backend afterwards
        self.assertEqual(page.evaluate('PLATFORM.showInterstitial("x")'), 'skipped')
        self.results[mode] = got

    def test_03a_throwing_inner_methods_return_defaults(self):
        self.check_defaults('throw')

    def test_03b_rejecting_inner_methods_return_defaults(self):
        self.check_defaults('reject')

    def test_03c_missing_inner_methods_return_defaults(self):
        self.check_defaults('delete')

    def test_04_init_failure_boots_with_defaults(self):
        # de-DE: the healthy backend detects 'de', the default is 'en'
        healthy = self.boot(locale='de-DE')
        self.assertEqual(healthy.evaluate('[PLATFORM.environment, PLATFORM.language]'),
                         ['local', 'de'])
        got = {}
        for mode, code in [('throw', 'PLATFORM_BACKEND.init = () => { throw new Error("probe") }'),
                           ('reject', 'PLATFORM_BACKEND.init = () => Promise.reject(new Error("probe"))'),
                           ('delete', 'delete PLATFORM_BACKEND.init')]:
            page = self.boot([('**/platform/backends/local.js', self.append(';' + code))],
                             locale='de-DE')
            got[mode] = page.evaluate('[PLATFORM.environment, PLATFORM.language, PLATFORM.platformId]')
            self.assertEqual(got[mode], ['local', 'en', 'local'], mode)
        self.results['init'] = got

    def test_05_platform_id_from_backend(self):
        page = self.boot([('**/platform/backends/local.js',
                           self.append(';PLATFORM_BACKEND.platformId = "facade-probe"'))])
        self.assertEqual(page.evaluate('PLATFORM.platformId'), 'facade-probe')
        self.assertEqual(page.evaluate('PLATFORM_BACKEND.platformId'), 'facade-probe')
        self.assertEqual(page.evaluate('PLATFORM.getPlatformId()'), 'facade-probe')

    def test_06_loading_progress_clamps(self):
        # The inner method receives the clamped, never-decreasing integer. The
        # boot reports its own milestones (TASK-748), so each sequence runs as
        # platform.js loads, on a fresh clamp.
        got = {}
        for sequence in ([-5, 42.7, 150], [60, 30]):
            probe = ';window.__clamp = %s.map(v => {' \
                    ' window.__backendHits.loadingProgress = [];' \
                    ' const result = PLATFORM.loadingProgress(v);' \
                    ' return [window.__backendHits.loadingProgress[0][0], result === undefined] })' \
                    % json.dumps(sequence)
            page = self.boot([('**/platform/backends/local.js', self.append(SPY)),
                              ('**/platform.js', self.append(probe))])
            seen = page.evaluate('__clamp')
            got[str(sequence)] = [s[0] for s in seen]
            self.assertTrue(all(s[1] for s in seen))
        self.assertEqual(got, {'[-5, 42.7, 150]': [0, 42, 100], '[60, 30]': [60, 60]})
        self.results['loadingProgress'] = got

    def test_07_local_returns(self):
        page = self.boot()
        returns = {}
        for method in NEW_METHODS:
            result = page.evaluate('async () => { const r = await %s; return r === undefined ? null : r }'
                                   % CALLS[method][0])
            returns[method] = result
        self.assertEqual(returns, LOCAL_RETURNS)
        self.assertEqual(page.evaluate('[PLATFORM.getLanguage(), PLATFORM.language]'), ['en', 'en'])
        de = self.boot(locale='de-DE')
        self.assertEqual(de.evaluate('[PLATFORM.getLanguage(), PLATFORM.language]'), ['de', 'de'])
        self.assertEqual(page.evaluate('PLATFORM.getPlatformId() === PLATFORM.platformId'), True)
        self.results['returns'] = returns
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'returns.json').write_text(json.dumps(returns, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    unittest.main()
