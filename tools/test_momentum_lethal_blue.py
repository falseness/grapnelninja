"""Momentum lethal blue touch ends the dead run's collision pass (TASK-090).

MomentumBlue.onNinjaPass -> momentumState.onBlueTouch -> onLethalDeath ->
reStart -> chooseVersion runs synchronously inside Ninja.collision, so before
the fix code after the restart ran against the NEW run: the blue's outline
pop and colour fringe (triggerBlueTouch) started for it, and the collision
pass kept going and applyBounce()d a green contact found earlier in the same
pass (greenStreak 1 on the fresh state).

Setup (rAF stopped, no interstitial due, tutorial hint hidden, obstacle
floors emptied): bad-frame11 is placed with window.momentumPlacePattern so
its blue (index BLUE) lies just right of the ninja start view centre; its
central green's bottom and that blue's top are ~3.8 units apart (ninja
radius 10.8). The ninja is put in that gap moving up (SPEED_Y), so one
physics sub-step finds the green contact first (pieces order) and then
touches the blue. physics() is stepped until the run restarts (lethal) or
STEPS steps (non-lethal).

- test_lethal_new_run_clean: hp 2, the other blue (OTHER) is touched once
  by script first (a world ring and a pop for the dead run), hp 1, step: on
  the new run hp is startHp, greenStreak 0, bluePops empty, blueTouchMs
  unset or older than the restart, no world ring, exactly 1 screen-anchored
  (death) ring, 1 restart and onGreenTouch never ran after it;
- test_nonlethal_unchanged: hp 3, same sub-step: same ninja, hp 2, streak 1
  (blue resets it, the green bounce at the end of the pass adds 1), 1 pop,
  1 world ring, blueTouchMs set.

MOMENTUM_LETHAL_BLUE_ROOT: the tree served (default this repo; a worktree of
the parent commit to see the old behaviour). MOMENTUM_LETHAL_BLUE_LABEL
(default 'after'): key the results are stored under in lethal.json and
nonlethal.json (compact, merged with the existing keys) in
MOMENTUM_LETHAL_BLUE_EVIDENCE_DIR (default /tmp/momentum-lethal-blue), with
shots/lethal-newrun-<label>.png (the first new-run frame, 1280x720).
Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(os.environ.get('MOMENTUM_LETHAL_BLUE_ROOT', Path(__file__).resolve().parents[1]))
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_LETHAL_BLUE_EVIDENCE_DIR', '/tmp/momentum-lethal-blue'))
LABEL = os.environ.get('MOMENTUM_LETHAL_BLUE_LABEL', 'after')
PATTERN = 'bad-frame11'
GREEN, BLUE, OTHER = 0, 1, 2
SPEED_Y = -3
STEPS = 3

SETUP = '''() => {
    PLATFORM.isInterstitialDue = () => false
    const t = window.__lb = {restarts: 0, restartAt: null, greensAfter: 0, deadNinja: null}
    const realReStart = reStart
    reStart = function() {
        ++t.restarts
        t.restartAt = performance.now()
        t.deadNinja = ninja
        return realReStart.apply(this, arguments)
    }
    const realGreen = momentumState.onGreenTouch
    momentumState.onGreenTouch = function() {
        if (t.restarts)
            ++t.greensAfter
        return realGreen.apply(this, arguments)
    }
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor) { f.elements = []; if (f.groups) f.groups = [] }
    ninja.invulnerableMs = 0
    // Blue right of the ninja start, the green/blue gap at the start height
    const placed = momentumPlacePattern(%(pattern)r, ninja.x + 250 - 748.6, ninja.y - 96.25)
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    t.els = floor.elements.slice(-placed.elements.length)
    const green = placed.elements[%(green)d], blue = placed.elements[%(blue)d]
    return {greenBottom: green.bottom, blueTop: blue.top, blueX: (blue.left + blue.right) / 2,
            classes: placed.elements.map(e => e.className), radius: ninja.radius}
}''' % {'pattern': PATTERN, 'green': GREEN, 'blue': BLUE}

STATE = '''() => {
    const t = window.__lb, fxs = visualEffects.screenEffects
    return {sameNinja: t.deadNinja === null, restarts: t.restarts, greensAfter: t.greensAfter,
        hp: momentumState.hp, streak: momentumState.greenStreak, version,
        bluePops: fxs.bluePops.length, blueTouchMs: fxs.blueTouchMs, restartAt: t.restartAt,
        worldRings: fxs.shockwaves.filter(w => w.world).length,
        screenRings: fxs.shockwaves.filter(w => !w.world).length,
        startHp: GAMEPLAY.momentumHp.startHp, offer: continueOffer.visible}
}'''


def merge(name, data):
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / name
    stored = json.loads(path.read_text()) if path.exists() else {}
    stored[LABEL] = data
    path.write_text(json.dumps(stored, separators=(',', ':')) + '\n')


class MomentumLethalBlueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        geo = page.evaluate(SETUP)
        self.assertEqual(geo['classes'][GREEN], 'MomentumGreen')
        self.assertEqual(geo['classes'][BLUE], 'MomentumBlue')
        gap = geo['blueTop'] - geo['greenBottom']
        self.assertLess(gap, 2 * geo['radius'], geo)
        return page, geo

    def step_touch(self, page, geo, hp):
        # Ninja in the gap moving up: one sub-step meets the green, then the blue
        page.evaluate('''([x, y, vy, hp]) => {
            momentumState.hp = hp
            ninja.x = x; ninja.y = y; ninja.speedX = 0; ninja.speedY = vy
            ninja.invulnerableMs = 0
        }''', [geo['blueX'], (geo['greenBottom'] + geo['blueTop']) / 2, SPEED_Y, hp])
        for _ in range(STEPS):
            page.evaluate('physics()')
            if page.evaluate('window.__lb.restarts'):
                break
        return page.evaluate(STATE)

    def test_lethal_new_run_clean(self):
        page, geo = self.open()
        # A non-lethal touch of the other blue first: the dead run's world
        # ring and pop
        page.evaluate('''([other]) => {
            momentumState.hp = 2
            const blue = window.__lb.els[other]
            blue.onNinjaPass(ninja)
        }''', [OTHER])
        before = page.evaluate(STATE)
        s = self.step_touch(page, geo, 1)
        page.evaluate('draw()')
        shots = EVIDENCE_DIR / 'shots'
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / f'lethal-newrun-{LABEL}.png'))
        stale_fringe = s['blueTouchMs'] is not None and s['blueTouchMs'] >= s['restartAt']
        merge('lethal.json', {'deadRunBefore': {k: before[k] for k in ('hp', 'bluePops', 'worldRings')},
                              'newRun': s, 'staleFringe': stale_fringe})
        print('lethal', LABEL, before, s)
        self.assertEqual((s['restarts'], s['version'], s['offer']), (1, 'momentum', False))
        self.assertEqual(s['hp'], s['startHp'])
        self.assertEqual(s['streak'], 0)
        self.assertEqual(s['greensAfter'], 0)
        self.assertEqual(s['bluePops'], 0)
        self.assertFalse(stale_fringe, s)
        self.assertEqual(s['worldRings'], 0)
        self.assertEqual(s['screenRings'], 1)

    def test_nonlethal_unchanged(self):
        page, geo = self.open()
        s = self.step_touch(page, geo, 3)
        merge('nonlethal.json', s)
        print('nonlethal', LABEL, s)
        self.assertTrue(s['sameNinja'])
        self.assertEqual(s['restarts'], 0)
        self.assertEqual((s['hp'], s['streak']), (2, 1))
        self.assertEqual(s['bluePops'], 1)
        self.assertEqual(s['worldRings'], 1)
        self.assertEqual(s['screenRings'], 0)
        self.assertIsNotNone(s['blueTouchMs'])


if __name__ == '__main__':
    unittest.main()
