"""Launch boots straight into a Grapple Over run, not the title menu.

TASK-445 made Grapple Over the startup mode (it was the main version, 'bad');
classic/bad stay reachable through the pause mode selector (test_mode_switch).

Spies on the local PLATFORM adapter's gameReady/sendLifecycle/startup calls.
Requires Playwright Chromium. No remote requests.

BOOT_EVIDENCE_DIR (default: artifacts/TASK-360) receives boot.png.
"""
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test

ROOT = Path(__file__).resolve().parents[1]
# Appended to platform.js: records the adapter calls the game makes as probe.calls
SPY = r"""
window.probe = {calls: []};
for (const name of ['gameReady', 'sendLifecycle', 'startup']) {
    const original = PLATFORM[name];
    PLATFORM[name] = function(...args) {
        if (name === 'gameReady') probe.calls.push({name: 'game_ready'});
        else if (name === 'sendLifecycle') probe.calls.push({name: args[0], data: args[1]});
        else probe.calls.push({name: 'startup_funnel', data: {stage: args[0], mode: args[1]}});
        return original.apply(this, args);
    };
}
"""
BOOT_DONE = "probe.calls.some(c => c.name === 'game_ready') && " \
    "probe.calls.some(c => c.name === 'level_started')"


def serve_spied_platform(route):
    response = route.fetch()
    route.fulfill(response=response, body=response.text() + SPY)


class BootMainModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('BOOT_EVIDENCE_DIR', ROOT / 'artifacts/TASK-360'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self, **context_options):
        options = {'viewport': {'width': 1280, 'height': 720}, **context_options}
        context = self.browser.new_context(locale='en-US', **options)
        self.addCleanup(context.close)
        context.route('**/platform.js', serve_spied_platform)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(BOOT_DONE)
        return page

    def calls(self, page):
        return page.evaluate('probe.calls.map(c => [c.name, c.data ?? null])')

    def test_boot_starts_grapple_over_run_after_game_ready(self):
        page = self.open()
        # game_ready is sent after the first gameplay frame was painted
        page.screenshot(path=str(self.out / 'boot.png'))
        state = page.evaluate('''({version, titleMenu: "visible" in menu || "classicVersionButton" in menu || "draw" in menu, paused: menu.gamePaused,
            tutorial: TUTORIAL_HINT.visible && TUTORIAL_HINT.alpha === 1,
            loading: !document.getElementById('loading').hidden, ninja: !!ninja})''')
        self.assertEqual(page.evaluate('[PLATFORM.environment, PLATFORM.isInterstitialDue()]'), ['local', False])
        self.assertEqual(state, {'version': 'grapple_over', 'titleMenu': False, 'paused': False,
                                 'tutorial': True, 'loading': False, 'ninja': True})
        # The adapter has no queue: level_started precedes game_ready
        page.wait_for_function("probe.calls.some(c => c.name === 'startup_funnel' && c.data.stage === 'first_gameplay_frame')")
        calls = self.calls(page)
        messages = [c for c in calls if c[0] == 'game_ready' or c[0].startswith('level_')]
        self.assertEqual(messages[:2], [['level_started', {'world': 'grapple_over'}], ['game_ready', None]])
        self.assertEqual([c[0] for c in calls].count('level_started'), 1)
        self.assertEqual([c[0] for c in calls].count('game_ready'), 1)
        stages = [c[1]['stage'] for c in calls if c[0] == 'startup_funnel']
        self.assertNotIn('menu_interactive', stages)
        self.assertEqual(stages[:3], ['mode_selected', 'run_initialized', 'first_gameplay_frame'])
        self.assertTrue(all(c[1].get('mode') == 'grapple_over' for c in calls if c[0] == 'startup_funnel'))
        print('PASS boot: version=grapple_over no title menu, tutorial shown; order', [m[0] for m in messages],
              'stages', stages[:3], flush=True)

    def lifecycle_after_boot(self, page):
        # Two more frames: a late pause would have been sent by then
        page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        return [c[0] for c in self.calls(page) if c[0].startswith('level_')]

    def test_portrait_touch_boot_starts_then_pauses_once(self):
        page = self.open(viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
        page.wait_for_function("probe.calls.some(c => c.name === 'level_paused')")
        state = page.evaluate('({version, rotated: isViewRotated(), paused: menu.gamePaused, inert: document.getElementById("stage").inert})')
        self.assertEqual(state, {'version': 'grapple_over', 'rotated': True, 'paused': True, 'inert': True})
        levels = self.lifecycle_after_boot(page)
        self.assertEqual(levels, ['level_started', 'level_paused'])
        print('PASS portrait boot:', state, levels, flush=True)

    def test_landscape_touch_boot_only_starts(self):
        page = self.open(viewport={'width': 844, 'height': 390}, has_touch=True, is_mobile=True)
        state = page.evaluate('({version, rotated: isViewRotated(), paused: menu.gamePaused})')
        self.assertEqual(state, {'version': 'grapple_over', 'rotated': False, 'paused': False})
        levels = self.lifecycle_after_boot(page)
        self.assertEqual(levels, ['level_started'])
        print('PASS landscape boot:', state, levels, flush=True)


if __name__ == '__main__':
    unittest.main()
