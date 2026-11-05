"""Mode time and the quit event (TASK-753).

- TELEMETRY.frame accumulates active play time (only frames where the run is
  playing) per floors[0].grapnelMode; TELEMETRY.flushModeTime() sends
  ANALYTICS.design('mode_time:<mode>', wholeSeconds) for each mode with a
  whole second, when setGrapnelMode changes the mode and on pagehide.
- TELEMETRY.mark(type, sectionId) keeps the last run event (fall, grapple,
  pause, restart, death, section, complete).
- pagehide, once per page: mode_time flush, playtime:* (TASK-861),
  design('quit:<type>:<section>'),
  progression('Fail', mode, section) when a section is in progress, then
  sessionEnd last.
- TASK-907: pageshow(persisted) after that pagehide (a back/forward-cache
  restore) reopens it: sessionStart, then progression Start for the run and
  the section the pagehide failed; the next pagehide sends quit:*, the Fails
  and sessionEnd again. A non-persisted pageshow and a second persisted one
  send nothing.
- TASK-908: visibilitychange to hidden during the Grapple Over run sends,
  before the auto pause, design hide:<last event>, hide_long_fall:<section>
  (within 30 s of a long fall), longest_fall:hide, then ANALYTICS.flush();
  never sessionEnd. Once per hidden period (a second hidden event sends
  nothing until visible again), at most 5 hidden periods per page; pagehide
  afterwards still sends quit:* and sessionEnd.

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
        # Play time events (TASK-861, tools/test_telemetry_session.py) follow the mode_time flush
        playtime = [e['args'][0] for e in design(tail, 'playtime:')]
        self.assertEqual(playtime, ['playtime:session:single', 'playtime:total:single',
                                    'playtime:session:double', 'playtime:total:double'])
        self.assertEqual([e['args'][0] for e in tail[1:5]], playtime)
        tail = [e for e in tail if not (e['fn'] == 'addDesignEvent' and e['args'][0].startswith('playtime:'))]
        # Gameplay telemetry (TASK-862, tools/test_telemetry_gameplay.py) after quit:*: the
        # session's longest fall, the section height, then the run Fail after the section Fail
        gameplay = [e for e in tail if (e['fn'] == 'addDesignEvent' and e['args'][0].split(':')[0] in
                                        ('longest_fall', 'section_height', 'quit_long_fall')) or
                    (e['fn'] == 'addProgressionEvent' and e['args'][2] is None)]
        self.assertEqual([e['args'][0] for e in gameplay], ['longest_fall:session', 'section_height:' + progress['id'],
                                                           'Fail'], tail)
        self.assertEqual(tail[-2], gameplay[-1])
        tail = [e for e in tail if e not in gameplay]
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

    def test_01_b_bfcache_pageshow_reopens_telemetry(self):
        page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.wait_for_timeout(1000)
        progress = page.evaluate('({id: CLIMB_UI.progression.id, open: CLIMB_UI.progression.open, '
                                 'run: CLIMB_UI.progression.run})')
        self.assertTrue(progress['run'] and progress['open'], progress)
        show = "persisted => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted}))"
        page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        first = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate(show, False)
        self.assertEqual(page.evaluate(LOG, first), [], 'a non-bfcache pageshow sent events')
        page.evaluate(show, True)
        restored = page.evaluate(LOG, first)
        self.assertEqual(restored[0]['fn'], 'startSession', restored)
        self.assertEqual([e['args'] for e in restored if e['fn'] == 'addProgressionEvent'],
                         [['Start', 'grapple_over', None], ['Start', 'grapple_over', progress['id']]])
        self.assertTrue(page.evaluate('CLIMB_UI.progression.run && CLIMB_UI.progression.open'))
        again = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate(show, True)
        self.assertEqual(page.evaluate(LOG, again), [], 'a second persisted pageshow sent events')
        page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        tail = page.evaluate(LOG, again)
        self.assertEqual(tail[-1]['fn'], 'endSession', tail)
        self.assertEqual(len(design(tail, 'quit:')), 1, tail)
        self.assertEqual([e['args'] for e in tail if e['fn'] == 'addProgressionEvent'],
                         [['Fail', 'grapple_over', progress['id']], ['Fail', 'grapple_over', None]])
        OUT.append({'bfcache_restore': restored, 'second_pagehide': tail})
        page.close()

    def test_01_c_hidden_tab_sends_and_flushes_without_ending(self):
        page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.wait_for_timeout(500)
        visibility = '''state => { Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => state})
            Object.defineProperty(document, 'hidden', {configurable: true, get: () => state === 'hidden'})
            document.dispatchEvent(new Event('visibilitychange')) }'''
        section = page.evaluate('CLIMB_UI.currentSection().id')
        page.evaluate("s => { TELEMETRY.mark('grapple', s); TELEMETRY.falling(4500) }", section)
        fall_section = page.evaluate('TELEMETRY.fallState().longFall.section')
        periods = []
        for i in range(7):
            start = page.evaluate('ANALYTICS.debugLog.length')
            page.evaluate(visibility, 'hidden')
            # A second hidden event in the same period sends nothing more
            page.evaluate(visibility, 'hidden')
            periods.append(page.evaluate(LOG, start))
            page.evaluate(visibility, 'visible')
        first = periods[0]
        expected = [{'fn': 'addDesignEvent', 'args': ['hide:grapple:' + section, None]},
                    {'fn': 'addDesignEvent', 'args': ['hide_long_fall:' + fall_section, 4000]},
                    {'fn': 'addDesignEvent', 'args': ['longest_fall:hide', 4000]},
                    {'fn': 'flush', 'args': []}]
        self.assertEqual(first[:4], expected, first)
        # The auto pause comes after (its mark is the next period's last event)
        self.assertEqual(first[4:], [{'fn': 'addDesignEvent', 'args': ['ui:pause:open:auto', None]}], first)
        for n, period in enumerate(periods):
            hides = [e for e in period if e['fn'] == 'flush']
            self.assertEqual(len(hides), 1 if n < 5 else 0, (n, period))
            self.assertFalse(any(e['fn'] == 'endSession' for e in period), period)
            if 0 < n < 5:
                # Already paused: nothing follows the flush
                self.assertEqual(period[-1]['fn'], 'flush', period)
        self.assertEqual(periods[1][0]['args'][0], 'hide:pause:' + section, periods[1])
        self.assertEqual([e for p in periods[5:] for e in p], [], 'hidden periods past the cap sent events')
        end = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate(PAGEHIDE)
        tail = page.evaluate(LOG, end)
        self.assertEqual(len(design(tail, 'quit:')), 1, tail)
        self.assertEqual(design(tail, 'longest_fall:session')[0]['args'], ['longest_fall:session', 4000])
        self.assertEqual(tail[-1]['fn'], 'endSession', tail)
        # After pagehide a hidden tab sends nothing (the session is over)
        after = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate(visibility, 'hidden')
        self.assertEqual(page.evaluate(LOG, after), [])
        OUT.append({'hidden_periods': periods, 'pagehide_after_hidden': tail})
        page.close()

    def test_02_no_page_errors(self):
        self.assertEqual(self.errors, [])


def tearDownModule():
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'quit.json').write_text(json.dumps(OUT, separators=(',', ':')))


if __name__ == '__main__':
    unittest.main()
