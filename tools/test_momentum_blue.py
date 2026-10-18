"""Momentum blue objects (sprites/momentumblue.js).

One MomentumBlue box is put on the (emptied) momentum obstacle floor below
and right of the ninja of a momentum run whose rAF loop is cancelled, after
three green touches (MomentumGreen.onNinjaBounce, the call Ninja.applyBounce
makes). The ninja flies into it diagonally through ninja.move() alone (no
gravity, camera or replenish in between): on the contact it passes through,
its velocity keeps its direction and is scaled by GAMEPLAY.momentumBlueSlow,
hp goes 5 -> 4 and the green streak 3 -> 0. A second pass from the same spot
during the fade changes nothing. The floor then drops the faded element.

Writes to MOMENTUM_BLUE_EVIDENCE_DIR (default artifacts/TASK-010):
blue-trace.json (compact [frame, vx, vy, hp], AFTER moves before to AFTER after the
contact move, frame 0 = contact) and blue-fade.json ({fadeMs, removedMs}).

Requires Playwright Chromium. No remote requests.
"""
import json
import math
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-010'))
# Diagonal flight in world units per physics cycle, |v| 1.25 under the
# effective cap GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) (1.39 at
# h 1080 since the TASK-073 slow motion; (1.5, 2) = 2.5 under 2.78 and (3, 4)
# = 5 are above it and Ninja.move clamps them)
SPEED = (0.75, 1)
MAX_MOVES = 480
# moves recorded after the contact (5 at |v| 5, 10 at 2.5; doubled with each
# halved speed so the slowed ninja still gets past the box top)
AFTER = 20

SETUP = '''() => {
    startGame('momentum')
    cancelAnimationFrame(game)
    window.__deaths = 0
    const lethal = window.onLethalDeath
    window.onLethalDeath = function() { ++window.__deaths; return lethal.apply(this, arguments) }
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    floor.elements = []
    ninja.__tag = 'blue-test'
    const r = ninja.radius
    const blue = MomentumBlue.box(ninja.x - 10 * r, ninja.y + 6 * r, 40 * r, 20 * r)
    floor.elements.push(blue)
    window.__blue = {floor, blue, x: ninja.x, y: ninja.y}
    return {x: ninja.x, y: ninja.y, radius: r, top: blue.y}
}'''

GREENS = '''() => {
    for (let i = 0; i < 3; ++i)
        MomentumGreen.box(0, 0, 10, 10).onNinjaBounce()
    return [momentumState.hp, momentumState.greenStreak]
}'''

# Flies from the start spot; frame = one ninja.move(). Stops AFTER moves past
# the contact move, or at MAX_MOVES.
FLY = '''([vx, vy, maxMoves, after]) => {
    const b = window.__blue
    ninja.x = b.x
    ninja.y = b.y
    ninja.speedX = vx
    ninja.speedY = vy
    const rows = []
    let contact = null
    const used = b.blue.passThrough
    for (let moves = 1; moves <= maxMoves; ++moves)
    {
        ninja.move()
        if (contact === null && !used && b.blue.passThrough)
            contact = moves
        rows.push([moves, ninja.speedX, ninja.speedY, momentumState.hp])
        if (contact !== null && moves >= contact + after)
            break
    }
    return {rows, contact, x: ninja.x, y: ninja.y,
        hp: momentumState.hp, streak: momentumState.greenStreak,
        passThrough: b.blue.passThrough, alpha: b.blue.getAlpha(),
        inFloor: b.floor.elements.includes(b.blue), deaths: window.__deaths,
        sameNinja: ninja.__tag === 'blue-test', version, runInProgress}
}'''

WAIT_REMOVED = '''() => new Promise(resolve => {
    const b = window.__blue
    const start = b.blue.fadeStartMs
    function tick()
    {
        b.floor.moveElements()
        if (b.floor.elements.includes(b.blue))
            setTimeout(tick, 16)
        else
            resolve({fadeMs: GAMEPLAY.momentumFadeMs, removedMs: +(performance.now() - start).toFixed(1),
                alpha: b.blue.getAlpha(), elements: b.floor.elements.length})
    }
    tick()
})'''


class MomentumBlueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        print('setup', page.evaluate(SETUP))
        return page

    def assert_alive(self, result):
        self.assertEqual(result['version'], 'momentum')
        self.assertTrue(result['runInProgress'])
        self.assertTrue(result['sameNinja'])
        self.assertEqual(result['deaths'], 0)

    def test_pass_through_slow_hp_streak_fade(self):
        page = self.open()
        slow = page.evaluate('GAMEPLAY.momentumBlueSlow')
        print('momentumBlueSlow', slow)
        self.assertGreater(slow, 0)
        self.assertLess(slow, 1)
        greens = page.evaluate(GREENS)
        print('after 3 greens [hp, greenStreak]', greens)
        self.assertEqual(greens, [5, 3])

        first = page.evaluate(FLY, [SPEED[0], SPEED[1], MAX_MOVES, AFTER])
        contact = first['contact']
        print('first pass: contact at move', contact, 'hp', first['hp'], 'streak', first['streak'],
              'alpha', round(first['alpha'], 4))
        self.assertIsNotNone(contact)
        self.assertGreater(contact, AFTER, 'need AFTER moves before the contact')
        rows = first['rows']
        trace = [[r[0] - contact, r[1], r[2], r[3]] for r in rows if contact - AFTER <= r[0] <= contact + AFTER]
        self.assertEqual(len(trace), 2 * AFTER + 1)
        (EVIDENCE_DIR / 'blue-trace.json').write_text(json.dumps(trace, separators=(',', ':')) + '\n')
        for row in trace:
            print('trace', row)

        before = [r for r in trace if r[0] < 0]
        after = [r for r in trace if r[0] >= 0]
        for r in before:
            self.assertEqual((r[1], r[2], r[3]), (SPEED[0], SPEED[1], 5))
        for r in after:
            self.assertEqual(r[3], 4)
            self.assertEqual((r[1], r[2]), (after[0][1], after[0][2]))
        vx, vy = after[0][1], after[0][2]
        angle_diff = abs(math.atan2(vy, vx) - math.atan2(SPEED[1], SPEED[0]))
        ratio = math.hypot(vx, vy) / math.hypot(*SPEED)
        print('angle diff', angle_diff, 'magnitude ratio', ratio)
        self.assertLess(angle_diff, 1e-6)
        self.assertAlmostEqual(ratio, slow, delta=1e-6)
        # Passed into the box instead of bouncing off its top
        self.assertGreater(first['y'], page.evaluate('window.__blue.blue.y'))
        self.assertEqual((first['hp'], first['streak']), (4, 0))
        self.assertTrue(first['passThrough'])
        self.assertTrue(first['inFloor'])
        self.assert_alive(first)

        second = page.evaluate(FLY, [SPEED[0], SPEED[1], 2 * contact, AFTER])
        print('second pass: moves', len(second['rows']), 'hp', second['hp'], 'streak', second['streak'],
              'alpha', round(second['alpha'], 4), 'end', second['rows'][-1])
        self.assertIsNone(second['contact'])
        self.assertTrue(all((r[1], r[2], r[3]) == (SPEED[0], SPEED[1], 4) for r in second['rows']))
        self.assertGreater(second['y'], page.evaluate('window.__blue.blue.y'))
        self.assertEqual((second['hp'], second['streak']), (4, 0))
        self.assertGreater(second['alpha'], 0)
        self.assertLess(second['alpha'], 1)
        self.assertTrue(second['inFloor'])
        self.assert_alive(second)

        fade = page.evaluate(WAIT_REMOVED)
        print('fade', fade)
        (EVIDENCE_DIR / 'blue-fade.json').write_text(json.dumps(fade, separators=(',', ':')) + '\n')
        self.assertEqual(fade['alpha'], 0)
        self.assertEqual(fade['elements'], 0)
        self.assertLessEqual(abs(fade['removedMs'] - fade['fadeMs']), 100)
        alive = page.evaluate('({hp: momentumState.hp, deaths: window.__deaths, '
                              'sameNinja: ninja.__tag === "blue-test", version, runInProgress})')
        print('after fade', alive)
        self.assertEqual(alive['hp'], 4)
        self.assert_alive(alive)

    def test_bad_mode_untouched(self):
        page = self.open()
        result = page.evaluate('''() => {
            startGame('bad')
            cancelAnimationFrame(game)
            return {version, hp: momentumState.hp,
                blueOnlyHook: floors.every(f => f.elements.every(e => !e.onNinjaPass))}
        }''')
        print('bad', result)
        self.assertEqual(result['version'], 'bad')
        self.assertTrue(result['blueOnlyHook'])


if __name__ == '__main__':
    unittest.main()
