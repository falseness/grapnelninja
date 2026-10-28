"""Mode time and the quit event (TASK-753).

- TELEMETRY.frame accumulates active play time (only frames where the run is
  playing) per floors[0].grapnelMode; TELEMETRY.flushModeTime() sends
  ANALYTICS.design('mode_time:<mode>', wholeSeconds) for each mode with a
  whole second, when setGrapnelMode changes the mode and on pagehide.
- TELEMETRY.mark(type, sectionId) keeps the last run event (fall, grapple,
  pause, restart, death, section, complete).
- pagehide, once per page: mode_time flush, design('quit:<type>:<section>'),
  progression('Fail', mode, section) when a section is in progress, then
  sessionEnd last.

The run plays in real time (~3 s single, ~2 s double, ~2 s paused), then
the frame loop is frozen and a fall is driven through production physics()
(test_climb_fall_recovery PLACE) before pagehide is dispatched.

ANALYTICS_QUIT_EVIDENCE_DIR, when set, receives quit.json: compact
[{fn, args}, ...] of the debugLog from the first mode switch to sessionEnd.

    python3 tools/test_analytics_quit.py -v
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
import test_climb_fall_recovery as recovery  # noqa: E402

EVIDENCE = os.environ.get('ANALYTICS_QUIT_EVIDENCE_DIR')
OUT = []

LOG = 'from => ANALYTICS.debugLog.slice(from).map(e => ({fn: e.fn, args: e.args.slice(0, e.fn === "addProgressionEvent" ? 3 : 2)}))'
PAGEHIDE = "() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))"
FREEZE = '() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }'
FALL = '''() => {
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,
        aim: null, clip: null, traveled: 0, speedX: 0, speedY: 0})
    const n = floors[0].climbStats.falls
    for (let i = 0; i < 400 && floors[0].climbStats.falls === n; i++) physics()
    return floors[0].climbStats.falls - n
}'''


def design(entries, prefix):
    return [e for e in entries if e['fn'] == 'addDesignEvent' and e['args'][0].startswith(prefix)]


class QuitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.errors = []

    def test_01_mode_time_and_quit(self):
        page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('floors[0].grapnelMode'), 'single')
        # No double offer pause on a fall during the timed play
        page.evaluate('floors[0].doubleOfferShown = true')
        # Nothing played before the boot run counts: start from a clean slate
        page.evaluate('TELEMETRY.flushModeTime()')

        page.wait_for_timeout(3000)
        switch = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate('CLIMB_UI.toggleGrapnel()')
        self.assertEqual(page.evaluate('floors[0].grapnelMode'), 'double')
        single = design(page.evaluate(LOG, switch), 'mode_time:')
        self.assertEqual([e['args'][0] for e in single], ['mode_time:single'])
        self.assertTrue(2 <= single[0]['args'][1] <= 4, single)

        page.wait_for_timeout(2000)
        page.evaluate('menu.startPause()')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        self.assertEqual(page.evaluate('TELEMETRY.lastEvent().type'), 'pause')
        page.wait_for_timeout(2000)
        # Unpause with the frame loop frozen: no frame counts after the pause
        page.evaluate(FREEZE)
        page.evaluate('menu.unPause()')
        page.evaluate(recovery.PLACE, [recovery.DEPTH - 200, 0])
        self.assertEqual(page.evaluate(FALL), 1)
        fall = design(page.evaluate(LOG, switch), 'fall:')[-1]['args'][0]
        section = fall.split(':', 1)[1]
        self.assertEqual(page.evaluate('TELEMETRY.lastEvent()'), {'type': 'fall', 'sectionId': section})
        progress = page.evaluate('({id: CLIMB_UI.progression.id, open: CLIMB_UI.progression.open})')
        self.assertTrue(progress['open'], progress)

        hide = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate(PAGEHIDE)
        tail = page.evaluate(LOG, hide)
        fns = [e['fn'] for e in tail]
        self.assertEqual(fns, ['addDesignEvent', 'addDesignEvent', 'addProgressionEvent', 'endSession'], tail)
        self.assertEqual(tail[0]['args'][0], 'mode_time:double')
        self.assertTrue(1 <= tail[0]['args'][1] <= 3, tail[0])
        self.assertEqual(tail[1]['args'][0], 'quit:fall:' + section)
        self.assertEqual(tail[2]['args'], ['Fail', 'grapple_over', progress['id']])
        self.assertFalse(page.evaluate('CLIMB_UI.progression.open'))
        # The paused 2 s were not counted: single + double stay under the
        # 3 s + 2 s played (plus one frame of slack each)
        self.assertLessEqual(single[0]['args'][1] + tail[0]['args'][1], 6)

        # A second pagehide sends nothing new
        end = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate(PAGEHIDE)
        self.assertEqual(page.evaluate(LOG, end), [])
        OUT.extend(page.evaluate(LOG, switch))
        page.close()

    def test_02_no_page_errors(self):
        self.assertEqual(self.errors, [])


def tearDownModule():
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'quit.json').write_text(json.dumps(OUT, separators=(',', ':')))


if __name__ == '__main__':
    unittest.main()
