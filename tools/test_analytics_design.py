"""Design-event counters (TASK-752).

Grapple Over:
- 'best_height:<grapnelMode>' with value bucket*500 when climbStats.maxHeight
  (physics.js calcPhysics) reaches a new 500-unit bucket for the first time
  in the run, once per bucket, never per frame;
- 'fall:<sectionId>' when a fall is counted (recoverClimbFall, falls++),
  against the section (CLIMB_UI.currentSection(), the HUD/progression lookup)
  of the last grapple catch, or the spawn section without a catch since the
  launch;
- 'restart:grapple_over' in CLIMB_UI.restart(); a restart is a new run, so
  its buckets are reported again; a reloaded (restored) run is not.
Classic/Bad: 'death:<mode>' when the death screen opens (a game over
interstitial is due), 'restart:<mode>' on its Restart button
(restartFromOffer).

The climb is driven by relocating the player (test_climb_fall_recovery
PLACE) with the frame loop frozen and production physics() ticks. The
counters keep their state outside climbStats: its keys and the saved climb
are unchanged.

ANALYTICS_DESIGN_EVIDENCE_DIR, when set, receives design.json: compact
[{test, id, value}, ...] of the design debugLog entries.

    python3 tools/test_analytics_design.py -v
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
from game_harness import switch_mode  # noqa: E402
import test_climb_fall_recovery as recovery  # noqa: E402

EVIDENCE = os.environ.get('ANALYTICS_DESIGN_EVIDENCE_DIR')
OUT = []
STATS_KEYS = ['elapsedActiveMs', 'currentHeight', 'maxHeight', 'completed', 'falls', 'grapples']

# Design entries of ANALYTICS.debugLog from index `from`
DESIGN = '''from => ANALYTICS.debugLog.slice(from).filter(e => e.fn === 'addDesignEvent')
    .map(e => ({id: e.args[0], value: e.args[1] ?? null}))'''

# Freeze the frame loop: only the test's physics() ticks move the world
FREEZE = '''() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }'''

# Free the player at `height` above the spawn and run `ticks` physics() ticks
CLIMB = '''([height, ticks]) => {
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,
        aim: null, clip: null, traveled: 0, speedX: 0, speedY: 0})
    const s = floors[0].level.spawn
    ninja.x = s.x; ninja.y = s.y - height; ninja.speedX = 0; ninja.speedY = 0
    for (let i = 0; i < ticks; i++) physics()
    return floors[0].climbStats.maxHeight
}'''

# Below the recovery depth; production physics recovers to the spawn
FALL = '''() => {
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,
        aim: null, clip: null, traveled: 0, speedX: 0, speedY: 0})
    floors[0].doubleOfferShown = true
    const n = floors[0].climbStats.falls
    for (let i = 0; i < 400 && floors[0].climbStats.falls === n; i++) physics()
    return floors[0].climbStats.falls - n
}'''


class DesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.errors = []

    def open(self):
        page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        return page

    def record(self, test, events):
        OUT.extend(dict(test=test, **e) for e in events)

    def test_01_grapple_over_heights_fall_restart(self):
        page = self.open()
        page.evaluate(FREEZE)
        mode = page.evaluate('floors[0].grapnelMode')
        self.assertEqual(mode, 'single')
        first = page.evaluate('floors[0].level.sections[0].id')
        # Booting reports nothing
        self.assertEqual(page.evaluate(DESIGN, 0), [])
        start = page.evaluate('ANALYTICS.debugLog.length')

        # Past two buckets at once, then higher in the same bucket, then the third
        self.assertGreaterEqual(page.evaluate(CLIMB, [1250, 1]), 1000)
        self.assertLess(page.evaluate(CLIMB, [1300, 30]), 1500)
        self.assertGreaterEqual(page.evaluate(CLIMB, [1650, 1]), 1500)
        # A grapple catch up there: the next fall counts against its section
        # (beside the second section's first terrain, without a physics tick,
        # so the best height is untouched)
        caught = page.evaluate('''() => {
            const w = floors[0], sec = w.level.sections[1], b = {}
            const id = w.level.encounters.find(e => sec.encounters.includes(e.id)).elements[0]
            elementBounds(w.byId.get(id), b)
            ninja.x = (b.left + b.right) / 2; ninja.y = b.top - 20
            const n = w.climbStats.grapples
            countClimbGrapple(false)
            return {section: CLIMB_UI.currentSection().id, grapples: floors[0].climbStats.grapples - n}
        }''')
        self.assertEqual(caught['grapples'], 1)
        self.assertEqual(caught['section'], page.evaluate('floors[0].level.sections[1].id'))
        page.evaluate(recovery.PLACE, [recovery.DEPTH - 200, 0])
        self.assertEqual(page.evaluate(FALL), 1)
        # Below the best height again: no repeated bucket. A second fall
        # without a catch counts against the spawn section.
        self.assertGreaterEqual(page.evaluate(CLIMB, [1200, 1]), 1500)
        page.evaluate(recovery.PLACE, [recovery.DEPTH - 200, 0])
        self.assertEqual(page.evaluate(FALL), 1)
        stats = page.evaluate('floors[0].climbStats')
        self.assertEqual(list(stats), STATS_KEYS)
        self.assertEqual(stats['falls'], 2)
        page.evaluate('PROGRESS.flushClimb()')
        saved = page.evaluate('''() => Object.keys(localStorage).filter(k => /climb/i.test(k))
            .map(k => localStorage.getItem(k)).join('')''')
        self.assertNotIn('bucket', saved)
        self.assertNotIn('climbDesign', saved)

        # Restart: a new run reports its buckets again
        page.evaluate('CLIMB_UI.restart()')
        page.evaluate(FREEZE)
        self.assertGreaterEqual(page.evaluate(CLIMB, [600, 1]), 500)
        events = page.evaluate(DESIGN, start)
        bh = 'best_height:' + mode
        self.assertEqual(events, [
            dict(id=bh, value=500), dict(id=bh, value=1000), dict(id=bh, value=1500),
            dict(id='fall:' + caught['section'], value=None),
            dict(id='fall:' + first, value=None),
            dict(id='restart:grapple_over', value=None),
            dict(id=bh, value=500)])
        # Each bucket once per run
        run1 = [e['value'] for e in events[:events.index(dict(id='restart:grapple_over', value=None))]
                if e['id'] == bh]
        self.assertEqual(len(run1), len(set(run1)))
        self.record('grapple_over', events)
        page.close()

    def test_02_bad_death_screen_and_restart(self):
        page = self.open()
        switch_mode(page, 'bad')
        start = page.evaluate('ANALYTICS.debugLog.length')
        # A death with a game over ad due opens the death screen
        shown = page.evaluate('''() => {
            PLATFORM.isInterstitialDue = () => true
            onLethalDeath()
            return continueOffer.visible
        }''')
        self.assertTrue(shown)
        page.evaluate('restartFromOffer()')
        page.wait_for_function("version === 'bad' && runInProgress && !continueOffer.visible")
        events = page.evaluate(DESIGN, start)
        self.assertEqual(events, [dict(id='death:bad', value=None), dict(id='restart:bad', value=None)])
        # A death without the screen (fast restart) reports nothing
        fast = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate('PLATFORM.isInterstitialDue = () => false; onLethalDeath()')
        self.assertEqual(page.evaluate(DESIGN, fast), [])
        self.record('bad', events)
        page.close()

    def test_03_restored_run_keeps_its_buckets(self):
        # A reload restores the saved climb: the same run, no bucket repeats
        page = self.open()
        page.evaluate(FREEZE)
        self.assertGreaterEqual(page.evaluate(CLIMB, [1100, 1]), 1000)
        page.evaluate('PROGRESS.flushClimb()')
        page.reload()
        page.wait_for_function("bootComplete && runInProgress && version === 'grapple_over'")
        page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        page.evaluate(FREEZE)
        self.assertGreaterEqual(page.evaluate('floors[0].climbStats.maxHeight'), 1000)
        start = page.evaluate('ANALYTICS.debugLog.length')
        page.evaluate(CLIMB, [1200, 1])
        self.assertGreaterEqual(page.evaluate(CLIMB, [1600, 1]), 1500)
        events = page.evaluate(DESIGN, start)
        self.assertEqual(events, [dict(id='best_height:single', value=1500)])
        self.record('restored', events)
        page.close()

    def test_04_no_page_errors(self):
        self.assertEqual(self.errors, [])


def tearDownModule():
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'design.json').write_text(json.dumps(OUT, separators=(',', ':')))


if __name__ == '__main__':
    unittest.main()
