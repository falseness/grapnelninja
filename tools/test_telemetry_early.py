"""Early-game telemetry (EARLY_TELEMETRY in telemetry.js), through ANALYTICS.

Documented in docs/platform-sdk.md ("Early-game telemetry"). Boots the real
index.html with its real frame loop and drives a real mouse:

test_01: a quick click to the right (released before the shot catches:
recalled, dir e), an arrow key, a hold aimed straight up that catches the
green P0-roof (green, dir n). Nothing reaches ANALYTICS during the presses
(buffered); pagehide hands everything over in order, first_press first.
test_02: 10 s of active play send early:check (presses so far) and
early:fps through the idle flush, without a pagehide.
test_03: the 8 directions (and none), then cost: 2000 press/release pairs through EARLY_TELEMETRY.shot /
caught / released and 2000 frame() calls take a few microseconds each, and
the 30-press cap holds.

    python3 tools/test_telemetry_early.py -v
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

EVIDENCE = os.environ.get('TELEMETRY_EARLY_EVIDENCE_DIR')
OUT = {}
EARLY = '''(from) => ANALYTICS.debugLog.slice(from).filter(e => e.fn === 'addDesignEvent' &&
    e.args[0].startsWith('early:')).map(e => [e.args[0], e.args[1] === undefined ? null : e.args[1]])'''
NINJA_VIEW = '''() => { const r = canvas.getBoundingClientRect(), k = r.width / canvas.width
    return [r.left + (ninja.x + screen.x) * scale[version] * k, r.top + (ninja.y + screen.y) * scale[version] * k] }'''
PAGEHIDE = "() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))"


class EarlyTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            Path(EVIDENCE, 'early.json').write_text(json.dumps(OUT, indent=1))

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        return page

    def test_01_presses_buffered_then_flushed(self):
        page = self.open()
        start = page.evaluate('ANALYTICS.debugLog.length')
        x, y = page.evaluate(NINJA_VIEW)
        # A quick click to the right: released before anything is caught
        page.mouse.move(x + 300, y)
        page.mouse.down()
        page.mouse.up()
        page.keyboard.press('ArrowUp')
        # A hold straight up: the shot catches the green P0-roof
        page.mouse.move(x, 10)
        page.mouse.down()
        page.wait_for_function('grapnel.grappled', timeout=20000)
        role = page.evaluate('grapnel.pos[0]?.[2]?.surfaceRole')
        page.wait_for_timeout(300)
        page.mouse.up()
        state = page.evaluate('EARLY_TELEMETRY.state()')
        before = page.evaluate(EARLY, start)
        page.evaluate(PAGEHIDE)
        after = page.evaluate(EARLY, start)
        OUT['test_01'] = {'role': role, 'state': state, 'before_pagehide': before, 'after_pagehide': after}
        self.assertEqual(role, 'bounce')
        self.assertEqual(state['presses'], 2)
        # Until the 5 s idle flush or pagehide, nothing reaches ANALYTICS
        # (a slow headless frame loop may already have flushed: then it is a prefix)
        self.assertEqual(after[:len(before)], before)
        ids = [e[0] for e in after]
        self.assertEqual(ids[0], 'early:first_press')
        self.assertIn('early:key:arrow', ids)
        presses = [e for e in after if e[0].startswith('early:press:')]
        # The real frame loop moves the ninja between reading its position and
        # the press: the direction is the expected one or a neighbour
        self.assertIn(presses[0][0], ['early:press:recalled:' + d for d in ('ne', 'e', 'se')])
        self.assertIn(presses[1][0], ['early:press:green:' + d for d in ('nw', 'n', 'ne')])
        self.assertGreaterEqual(presses[1][1], 300)
        self.assertLess(presses[0][1], presses[1][1])
        self.assertEqual(page.evaluate('EARLY_TELEMETRY.state().buffered'), 0)
        self.assertEqual(page.errors, [])

    def test_02_check_after_ten_active_seconds(self):
        page = self.open()
        start = page.evaluate('ANALYTICS.debugLog.length')
        page.wait_for_function('EARLY_TELEMETRY.state().activeMs >= 10000', timeout=60000)
        page.wait_for_function('EARLY_TELEMETRY.state().buffered === 0', timeout=20000)
        events = page.evaluate(EARLY, start)
        OUT['test_02'] = events
        self.assertEqual([e[0] for e in events], ['early:check', 'early:fps'])
        self.assertEqual(events[0][1], 0)
        self.assertTrue(0 < events[1][1] <= 240, events)
        self.assertEqual(page.errors, [])

    def test_03_cost_and_cap(self):
        page = self.open()
        result = page.evaluate('''() => {
            const E = EARLY_TELEMETRY, green = {surfaceRole: 'bounce'}
            // World y grows downwards
            for (const [dx, dy] of [[1, 0], [1, -1], [0, -1], [-1, -1], [-1, 0], [-1, 1], [0, 1], [1, 1], [0, 0]])
            { E.shot(dx, dy); E.released(false) }
            let t = performance.now()
            for (let i = 0; i < 2000; i++) { E.shot(10, -20); E.caught(green); E.released(false) }
            const pressUs = (performance.now() - t) * 1000 / 2000
            t = performance.now()
            for (let i = 0; i < 2000; i++) E.frame(0.001)
            const frameUs = (performance.now() - t) * 1000 / 2000
            const s = E.state()
            E.flush()
            const ids = ANALYTICS.debugLog.filter(e => e.args[0]?.startsWith?.('early:press:')).map(e => e.args[0])
            return {pressUs, frameUs, presses: s.presses, sent: ids.length, dirs: ids.slice(0, 9)}
        }''')
        OUT['test_03'] = result
        self.assertEqual(result['presses'], 30)
        self.assertEqual(result['sent'], 30)
        self.assertEqual(result['dirs'], ['early:press:recalled:' + d for d in
                                          ('e', 'ne', 'n', 'nw', 'w', 'sw', 's', 'se', 'none')])
        # Generous: a press costs ~1 us; a 60 fps frame is 16 667 us
        self.assertLess(result['pressUs'], 50, result)
        self.assertLess(result['frameUs'], 20, result)
        self.assertEqual(page.errors, [])


if __name__ == '__main__':
    unittest.main()
