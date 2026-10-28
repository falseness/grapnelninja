"""Facade call sites (TASK-748): the game calls the cross-portal PLATFORM
methods at its natural points. The local backend makes them no-ops, so this
only spies the calls.

A spy appended to platform.js (as in test_boot_main_mode) records every call
to the spied facade methods from before boot. One page then drives: boot
(loading milestones, the Grapple Over run start, game ready), pause, resume,
a switch to the classic 'bad' mode, a lethal death (fast restart, no ad is
due locally), a switch back to Grapple Over, its completion
(CLIMB_UI.complete) and a restart from the win screen.

PLATFORM_CALLS_EVIDENCE_DIR (default: artifacts/TASK-748) receives
sequence.json: the recorded [{method, args}] in call order.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from game_harness import READY, switch_mode

ROOT = Path(__file__).resolve().parents[1]
SPIED = ['loadingProgress', 'gameplayStart', 'gameplayStop', 'happyMoment',
         'submitScore', 'gameReady', 'sendLifecycle']
# Appended to platform.js: records the facade calls the game makes
SPY = r"""
window.__calls = [];
for (const name of %s) {
    const original = PLATFORM[name];
    PLATFORM[name] = function(...args) {
        window.__calls.push({method: name, args: JSON.parse(JSON.stringify(args))});
        return original.apply(this, args);
    };
}
""" % json.dumps(SPIED)


def serve_spied_platform(route):
    response = route.fetch()
    route.fulfill(response=response, body=response.text() + SPY)


class PlatformCallsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLATFORM_CALLS_EVIDENCE_DIR', ROOT / 'artifacts/TASK-748'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
        self.addCleanup(context.close)
        context.route('**/platform.js', serve_spied_platform)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY + " && __calls.some(c => c.method === 'gameReady')")
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'local')
        return page

    def take(self, page):
        """Facade calls since the last take (sendLifecycle kept as context)."""
        return page.evaluate('__calls.splice(0)')

    @staticmethod
    def facade(calls):
        return [[c['method']] + c['args'] for c in calls if c['method'] != 'sendLifecycle']

    def test_call_sequence(self):
        page = self.open()
        sequence = []

        # Boot: monotonic loading milestones ending at 100, then the run, then game ready
        boot = self.take(page)
        sequence += boot
        loading = [c['args'][0] for c in boot if c['method'] == 'loadingProgress']
        self.assertEqual(loading, sorted(loading))
        self.assertGreaterEqual(len(loading), 3)
        self.assertEqual(loading[0], 0)
        self.assertEqual(loading[-1], 100)
        methods = [c['method'] for c in boot]
        self.assertLess(len(methods) - 1 - methods[::-1].index('loadingProgress'), methods.index('gameReady'))
        self.assertEqual([c for c in self.facade(boot) if c[0] != 'loadingProgress'],
                         [['gameplayStart', 'grapple_over'], ['gameReady']])
        # Each facade call follows its lifecycle message
        self.assertLess(methods.index('sendLifecycle'), methods.index('gameplayStart'))

        page.evaluate('menu.startPause()')
        calls = self.take(page)
        sequence += calls
        self.assertEqual(self.facade(calls), [['gameplayStop', 'pause', 'grapple_over']])

        page.evaluate('menu.unPause()')
        calls = self.take(page)
        sequence += calls
        self.assertEqual(self.facade(calls), [['gameplayStart', 'grapple_over']])

        switch_mode(page, 'bad')
        calls = self.take(page)
        sequence += calls
        self.assertEqual(self.facade(calls), [['gameplayStop', 'pause', 'grapple_over'],
                                              ['gameplayStart', 'bad']])

        # No ad is due locally: the death fast-restarts the same mode
        state = page.evaluate('''() => {
            onLethalDeath()
            return {offer: continueOffer.visible, running: runInProgress, version}
        }''')
        self.assertEqual(state, {'offer': False, 'running': True, 'version': 'bad'})
        calls = self.take(page)
        sequence += calls
        self.assertEqual(self.facade(calls), [['gameplayStop', 'death', 'bad'], ['gameplayStart', 'bad']])
        self.assertEqual([c['args'][0] for c in calls if c['method'] == 'sendLifecycle'],
                         ['level_failed', 'level_started'])

        # Back to Grapple Over: the saved climb is restored paused (progress.js
        # restoreClimb), then resumed
        page.evaluate("menu.startPause(); menu.selectMode('grapple_over')")
        page.wait_for_function("version === 'grapple_over' && runInProgress && menu.gamePaused")
        page.evaluate('menu.unPause()')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        calls = self.take(page)
        sequence += calls
        self.assertEqual(self.facade(calls), [['gameplayStop', 'pause', 'bad'],
                                              ['gameplayStart', 'grapple_over'],
                                              ['gameplayStop', 'pause', 'grapple_over'],
                                              ['gameplayStart', 'grapple_over']])

        # The score is the run's active time in whole ms, read once the clock stopped
        elapsed = page.evaluate('''() => {
            floors[0].climbStats.elapsedActiveMs = 123456.7
            CLIMB_UI.complete()
            return floors[0].climbStats.elapsedActiveMs
        }''')
        self.assertGreaterEqual(elapsed, 123456.7)
        calls = self.take(page)
        sequence += calls
        self.assertEqual(self.facade(calls), [['gameplayStop', 'complete', 'grapple_over'],
                                              ['happyMoment'],
                                              ['submitScore', 'grapple_over_time', round(elapsed)]])
        self.assertEqual(page.evaluate('menu.gamePaused && floors[0].climbStats.completed'), True)

        # Restart from the win screen: a new run (level_started), then the unpause
        page.evaluate('CLIMB_UI.restart()')
        calls = self.take(page)
        sequence += calls
        self.assertEqual(self.facade(calls), [['gameplayStart', 'grapple_over'],
                                              ['gameplayStart', 'grapple_over']])
        self.assertEqual([c['args'][0] for c in calls if c['method'] == 'sendLifecycle'],
                         ['level_started', 'level_resumed'])

        # Every facade method the ticket names was called, with only valid stop reasons
        names = {c['method'] for c in sequence}
        self.assertTrue({'loadingProgress', 'gameplayStart', 'gameplayStop', 'happyMoment',
                         'submitScore', 'gameReady'} <= names)
        reasons = [c['args'][0] for c in sequence if c['method'] == 'gameplayStop']
        self.assertEqual(sorted(set(reasons)), ['complete', 'death', 'pause'])

        out = [c for c in sequence if c['method'] != 'sendLifecycle']
        (self.out / 'sequence.json').write_text(json.dumps(out, separators=(',', ':')) + '\n')
        print('sequence:', json.dumps(self.facade(sequence), separators=(',', ':')), flush=True)


if __name__ == '__main__':
    unittest.main()
