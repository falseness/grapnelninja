"""Momentum green objects (sprites/momentumgreen.js).

One MomentumGreen box is put on the (emptied) momentum obstacle floor right
below the ninja of a momentum run whose rAF loop is cancelled. The ninja falls
onto it at speedY 8 through ninja.move() alone (no gravity, camera or
replenish in between): the first contact reflects speedY and makes the green
streak 1. A second fall from the same spot during the fade keeps speedY and
the streak. The fade is then sampled every 16 ms (getAlpha, the value draw()
uses, then floor.moveElements()) until the floor drops the element.

Writes to MOMENTUM_GREEN_EVIDENCE_DIR (default artifacts/TASK-009):
green-alpha.json ({fadeMs, removedMs, samples: [[ms, alpha]]}, compact),
green-fade.png (mid-fade, alpha ~0.5) and green-full.png (before contact).

Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_GREEN_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-009'))
FALL_SPEED = 8
MAX_MOVES = 60

SETUP = '''() => {
    startGame('momentum')
    cancelAnimationFrame(game)
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    floor.elements = []
    ninja.speedX = 0
    ninja.speedY = 0
    const green = MomentumGreen.box(ninja.x - 15 * ninja.radius, ninja.y + 3 * ninja.radius,
        30 * ninja.radius, 10 * ninja.radius)
    floor.elements.push(green)
    window.__green = {floor, green, x: ninja.x, y: ninja.y}
    return {x: ninja.x, y: ninja.y, radius: ninja.radius, top: green.y}
}'''

# Falls from the start spot; stops at the first speedY change or past the box
FALL = '''([speed, maxMoves]) => {
    const g = window.__green
    ninja.x = g.x
    ninja.y = g.y
    ninja.speedX = 0
    ninja.speedY = speed
    let moves = 0
    while (moves < maxMoves && ninja.speedY == speed && ninja.y < g.green.y + 12 * ninja.radius)
    {
        ninja.move()
        ++moves
    }
    return {moves, speedX: ninja.speedX, speedY: ninja.speedY, y: ninja.y,
        streak: momentumState.greenStreak, hp: momentumState.hp,
        passThrough: g.green.passThrough, alpha: g.green.getAlpha(),
        inFloor: g.floor.elements.includes(g.green),
        version, runInProgress}
}'''

SAMPLE_FADE = '''() => new Promise(resolve => {
    const g = window.__green
    const start = g.green.fadeStartMs
    const samples = [[0, g.green.getAlpha(start)]]
    function tick()
    {
        const now = performance.now()
        const alpha = g.green.getAlpha(now)
        g.floor.moveElements()
        samples.push([+(now - start).toFixed(1), +alpha.toFixed(4)])
        if (g.floor.elements.includes(g.green))
            setTimeout(tick, 16)
        else
            resolve({samples, removedMs: samples[samples.length - 1][0],
                elements: g.floor.elements.length, fadeMs: GAMEPLAY.momentumFadeMs})
    }
    tick()
})'''


class MomentumGreenTests(unittest.TestCase):
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
        setup = page.evaluate(SETUP)
        print('setup', setup)
        return page

    def first_contact(self, page):
        before = page.evaluate('[momentumState.greenStreak, momentumState.hp]')
        self.assertEqual(before, [0, 5])
        hit = page.evaluate(FALL, [FALL_SPEED, MAX_MOVES])
        print('first pass', hit)
        self.assertEqual(hit['version'], 'momentum')
        self.assertTrue(hit['runInProgress'])
        self.assertLess(hit['moves'], MAX_MOVES)
        # Reflected normal (vertical) component; bounceSpeed also subtracts one GRAVITY
        gravity = page.evaluate('GRAVITY')
        self.assertAlmostEqual(hit['speedY'], -FALL_SPEED - gravity, places=6)
        self.assertEqual(hit['speedX'], 0)
        self.assertEqual(hit['streak'], 1)
        self.assertTrue(hit['passThrough'])
        self.assertTrue(hit['inFloor'])
        return hit

    def test_one_bounce_then_pass_through_then_removed(self):
        page = self.open()
        first = self.first_contact(page)
        second = page.evaluate(FALL, [FALL_SPEED, MAX_MOVES])
        print('second pass', second)
        # Fell through the box: below its bottom, speed and streak unchanged
        top = page.evaluate('window.__green.green.y')
        self.assertGreater(second['y'], top + 10 * page.evaluate('ninja.radius'))
        self.assertGreater(second['moves'], first['moves'])
        self.assertEqual((second['speedX'], second['speedY']), (0, FALL_SPEED))
        self.assertEqual(second['streak'], 1)
        self.assertGreater(second['alpha'], 0)
        self.assertLess(second['alpha'], 1)
        self.assertTrue(second['inFloor'])

        fade = page.evaluate(SAMPLE_FADE)
        samples = fade['samples']
        print('fade', len(samples), 'samples, removed at', fade['removedMs'], 'ms, first', samples[:2],
              'last', samples[-2:], 'floor elements left', fade['elements'])
        (EVIDENCE_DIR / 'green-alpha.json').write_text(json.dumps(
            {'fadeMs': fade['fadeMs'], 'removedMs': fade['removedMs'], 'samples': samples},
            separators=(',', ':')) + '\n')
        alphas = [a for _, a in samples]
        times = [t for t, _ in samples]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(b <= a for a, b in zip(alphas, alphas[1:])), 'alpha must not increase')
        positive = [a for a in alphas if a > 0]
        self.assertTrue(all(b < a for a, b in zip(positive, positive[1:])), 'alpha strictly falls while visible')
        self.assertEqual(alphas[-1], 0)
        self.assertLessEqual(abs(fade['removedMs'] - fade['fadeMs']), 100)
        self.assertEqual(fade['elements'], 0)
        # Linear: alpha = 1 - t / fadeMs at every sample
        for t, a in samples:
            self.assertAlmostEqual(a, max(0, 1 - t / fade['fadeMs']), delta=0.002)
        self.assertEqual(page.evaluate('momentumState.greenStreak'), 1)

    def test_mid_fade_screenshot(self):
        page = self.open()
        # Same draw before the contact (alpha 1) for comparison
        page.evaluate('draw()')
        page.screenshot(path=str(EVIDENCE_DIR / 'green-full.png'))
        self.first_contact(page)
        alpha = page.evaluate('''() => {
            const g = window.__green.green
            g.fadeStartMs = performance.now() - GAMEPLAY.momentumFadeMs / 2
            // Ninja well above the box so it does not cover it
            ninja.x = window.__green.x
            ninja.y = window.__green.y - 15 * ninja.radius
            draw()
            return g.getAlpha()
        }''')
        page.screenshot(path=str(EVIDENCE_DIR / 'green-fade.png'))
        print('mid-fade alpha', round(alpha, 4))
        self.assertAlmostEqual(alpha, 0.5, delta=0.05)


if __name__ == '__main__':
    unittest.main()
