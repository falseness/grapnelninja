"""Progression telemetry per climb section (TASK-751).

CLIMB_UI.trackSection() runs once a frame while playing and uses the HUD's
section lookup (CLIMB_UI.currentSection()). On a section change it sends
ANALYTICS.progression: 'Start' on entering a section not completed in this
run, 'Complete' (once per section per run) for the section left upward,
'Fail' for the section left downward; the summit sends 'Complete' for the
last section. CLIMB_UI.restart() resets the tracking.

test_01 boots the game (a new run: Start for the first section). test_02
replays the recorded NGU purple route (test_purple_route TRAVERSE with
tools/fixtures/purple-route-inputs-ngu-rest.json, production input and
physics), one trackSection() per tick as the frame check, and compares the
events with model() applied to the per-tick section trace (bounces in the
purple zone briefly drop into the section below), then forces a fall
below the recovery depth (test_climb_fall_recovery PLACE): the production
recovery returns the player to the spawn. test_03 reaches the summit and
restarts.

ANALYTICS_PROGRESSION_EVIDENCE_DIR, when set, receives progression.json:
compact [{test, status, mode, section}, ...] of the progression debugLog
entries, and route-sections.json: the sections the HUD lookup reported along
the route replay, in order of change (the input of the expected-sequence model).

    python3 tools/test_analytics_progression.py -v
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
import test_purple_route as purple  # noqa: E402
import test_climb_fall_recovery as recovery  # noqa: E402

EVIDENCE = os.environ.get('ANALYTICS_PROGRESSION_EVIDENCE_DIR')
NGU_INPUTS = purple.INPUTS['NGU']
OUT = []
OUT_TRACE = []

# Progression entries of ANALYTICS.debugLog from index `from`
PROGRESSION = '''from => ANALYTICS.debugLog.slice(from).filter(e => e.fn === 'addProgressionEvent')
    .map(e => ({status: e.args[0], mode: e.args[1], section: e.args[2]}))'''

# The frame check: one trackSection() per production physics() tick; FRAMES
# keeps the tick count and the sections the HUD lookup reported, on change
FRAMES = '''() => {
    const step = physics
    window.FRAMES = {ticks: 0, trace: []}
    physics = function() {
        const r = step.apply(this, arguments)
        CLIMB_UI.trackSection()
        const id = CLIMB_UI.currentSection().id
        FRAMES.ticks++
        if (id !== FRAMES.trace.at(-1)) FRAMES.trace.push(id)
        return r
    }
}'''

# Inside the finish box: the next physics() tick completes the climb
SUMMIT = '''() => {
    const f = floors[0].level.finish
    ninja.x = (f.left + f.right) / 2; ninja.y = (f.top + f.bottom) / 2; ninja.speedX = ninja.speedY = 0
    physics()
    for (let i = 0; i < 10; i++) CLIMB_UI.trackSection()
    return floors[0].climbStats.completed
}'''


def model(sections, trace, summit=False):
    """Independent model of the rules: the expected events for a run that
    visits the sections of `trace` in order (fresh tracking)."""
    out, completed, cur, opened = [], set(), None, False
    ev = lambda status, section: out.append(dict(status=status, mode='grapple_over', section=section))
    for sid in trace:
        if sid == cur:
            continue
        if cur is not None and opened:
            up = sections.index(sid) > sections.index(cur)
            if up:
                completed.add(cur)
            ev('Complete' if up else 'Fail', cur)
        cur, opened = sid, sid not in completed
        if opened:
            ev('Start', sid)
    if summit and opened:
        ev('Complete', cur)
    return out


class ProgressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = url, browser = start_browser_test(ROOT, cls.stack.callback)
        cls.page = browser.new_page(viewport={'width': 1280, 'height': 720})
        cls.errors = []
        cls.page.on('pageerror', lambda e: cls.errors.append(str(e)))
        cls.page.goto(url)
        wait_for_boot_run(cls.page)
        cls.boot = cls.page.evaluate(PROGRESSION, 0)
        cls.first = cls.page.evaluate('floors[0].level.sections[0].id')
        cls.page.add_script_tag(path=str(TOOLS / 'opening_combination_replay.js'))
        cls.page.evaluate(FRAMES)
        m, cls.level = purple.load()
        cls.ids = dict(m['routeMap']['fragmentIds'], **m['routeMap']['addedFragments'])
        cls.sections = cls.page.evaluate('floors[0].level.sections.map(s => s.id)')

    def record(self, test, events):
        OUT.extend(dict(test=test, **e) for e in events)

    def mark(self):
        return self.page.evaluate('ANALYTICS.debugLog.length')

    def test_01_boot_starts_first_section(self):
        self.record('boot', self.boot)
        self.assertEqual(self.boot, [dict(status='Start', mode='grapple_over', section=self.first)])

    def test_02_route_replay_and_forced_fall(self):
        rec = json.loads(NGU_INPUTS.read_text())
        self.page.evaluate('CLIMB_UI.resetProgression()')
        start = self.mark()
        log = self.page.evaluate(purple.TRAVERSE, dict(level=self.level, ids=self.ids, fixture=rec['fixture'],
                                                       inputs=rec['inputs'], budget=rec['budget'], exit='NGU-EXIT',
                                                       trace=False))
        self.assertIsNotNone(log['landed'], 'NGU route did not reach its exit ledge')
        self.assertEqual(log['recoveries'], [])
        route = self.page.evaluate(PROGRESSION, start)
        frames = self.page.evaluate('FRAMES')
        trace = frames['trace']
        # The route climbs at least two sections, ending above where it started
        self.assertGreaterEqual(len(set(trace)), 3, trace)
        self.assertGreater(self.sections.index(trace[-1]), self.sections.index(trace[0]) + 1, trace)
        self.assertEqual(route, model(self.sections, trace))
        statuses = [e['status'] for e in route]
        self.assertEqual(statuses[0], 'Start')
        self.assertGreaterEqual(statuses.count('Complete'), 2, route)
        # Complete once per section per run
        done = [e['section'] for e in route if e['status'] == 'Complete']
        self.assertEqual(len(done), len(set(done)))
        # Events only on change: never more than 2 per section change
        self.assertLessEqual(len(route), 2 * len(trace) - 1)
        self.assertGreater(frames['ticks'], 20 * len(route))
        self.record('route', route)
        OUT_TRACE.extend(trace)

        # Standing still for 120 frames sends nothing
        still = self.mark()
        self.page.evaluate('() => { for (let i = 0; i < 120; i++) CLIMB_UI.trackSection() }')
        self.assertEqual(self.page.evaluate(PROGRESSION, still), [])

        # Forced fall: below the recovery depth, then production physics recovers to the spawn
        fall = self.mark()
        self.page.evaluate('floors[0].doubleOfferShown = true')
        self.page.evaluate(recovery.PLACE, [recovery.DEPTH - 200, 0])
        recovered = self.page.evaluate('''() => {
            const n = floors[0].climbStats.falls
            for (let i = 0; i < 400 && floors[0].climbStats.falls === n; i++) physics()
            return floors[0].climbStats.falls > n
        }''')
        self.assertTrue(recovered)
        fell = self.page.evaluate(PROGRESSION, fall)
        landed = self.page.evaluate('CLIMB_UI.currentSection().id')
        self.assertEqual(landed, self.first)
        # Fail for the section fallen from, Start for the (not yet completed) spawn section
        self.assertEqual(fell, [dict(status='Fail', mode='grapple_over', section=trace[-1]),
                                dict(status='Start', mode='grapple_over', section=self.first)])
        self.record('fall', fell)

    def test_03_summit_complete_and_restart(self):
        # A fresh page: the route replay helper disables rendering, which restart() needs
        page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        start = page.evaluate('ANALYTICS.debugLog.length')
        self.assertTrue(page.evaluate(SUMMIT))
        summit = page.evaluate(PROGRESSION, start)
        last = self.sections[-1]
        self.assertEqual(summit, [dict(status='Complete', mode='grapple_over', section=self.first),
                                  dict(status='Start', mode='grapple_over', section=last),
                                  dict(status='Complete', mode='grapple_over', section=last)])
        self.assertEqual(summit, model(self.sections, [self.first, last], summit=True)[1:])
        self.record('summit', summit)
        # Restart resets the tracking: a new run starts the first section again
        restart = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate('CLIMB_UI.restart(); CLIMB_UI.trackSection(); CLIMB_UI.trackSection()')
        again = page.evaluate(PROGRESSION, restart)
        self.assertEqual(again, [dict(status='Start', mode='grapple_over', section=self.first)])
        self.record('restart', again)
        page.close()

    def test_04_no_page_errors(self):
        self.assertEqual(self.errors, [])


def tearDownModule():
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'progression.json').write_text(json.dumps(OUT, separators=(',', ':')))
        (Path(EVIDENCE) / 'route-sections.json').write_text(json.dumps(OUT_TRACE, separators=(',', ':')))


if __name__ == '__main__':
    unittest.main()
