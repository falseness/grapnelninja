"""Momentum streak builder routes (elements/momentumpatterns.js).

For every streakBuilder type of the TASK-012 horizontal catalog
(MOMENTUM_CATALOG_H, default artifacts/TASK-012/catalog-h.json) the type is
placed alone on the first (long, right) segment of a scripted course, the rAF
loop is stopped and the ninja is driven along the catalog route: per leg the
test aims the velocity (DRIVE_SPEED, straight line, ninja.move() has no
gravity) from where the ninja is at the next route point and steps
ninja.move() (real collisions, bounces and one-time uses) until it reaches a
plain point or the route's contact green is used. Asserts per type: the greens
are used in the route's contact order and nothing else is touched (0 blues),
no death, and the fifth green in a row makes hp 5 -> 6 (streak back to 0).

Writes MOMENTUM_STREAK_EVIDENCE_DIR (default artifacts/TASK-015)/streak-routes.json
(compact {id: {route, contacts, used, greens, blues, hpBefore, hpAfter5, hpAfter,
streakAfter, deaths, moves}}).

Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE
from test_momentum_patterns_h import SCRIPT

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(os.environ.get('MOMENTUM_CATALOG_H', ROOT / 'artifacts/TASK-012/catalog-h.json'))
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_STREAK_EVIDENCE_DIR', ROOT / 'artifacts/TASK-015'))
# World units per physics cycle, under GAMEPLAY.momentumMaxSpeed (5.56 at h 1080
# since TASK-029 halved it; was 10 with 1000 moves under the old 11.12 cap)
DRIVE_SPEED = 5
MAX_MOVES = 2000

DRIVE = '''([id, points, speed, maxMoves]) => {
    momentumState.reset()
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    const s = momentumCourse.segment(0)
    const half = GAMEPLAY.momentumBorders.halfWidth
    const x0 = s.x0 + 0.2 * half, top = s.y0 - half
    const placed = momentumPlacePattern(id, x0, s.y0, 'right')
    const elements = floor.elements.slice()
    const at = (u, v) => ({x: x0 + u * placed.length, y: top + v * 2 * half})
    // Keep the pattern in view: no left-edge death while driving
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(x0 + placed.length / 2 - w / 2); screen.y = -(s.y0 - h / 2)
    screen.leftWall.update(screen)
    let deaths = 0
    const lethal = onLethalDeath
    onLethalDeath = function() { ++deaths; return lethal.apply(this, arguments) }
    const used = []
    const usedNow = () => elements.forEach((e, i) => {
        if (e.passThrough && !used.some(u => u.piece == i))
            used.push({piece: i, kind: e instanceof MomentumBlue ? 'blue' : 'green',
                streak: momentumState.greenStreak, hp: momentumState.hp})
    })
    const hpBefore = momentumState.hp
    const n0 = ninja
    grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
    const start = at(points[0][0], points[0][1])
    ninja.x = start.x; ninja.y = start.y
    let moves = 0
    const legs = []
    try {
        for (let k = 1; k < points.length; ++k)
        {
            const [u, v, contact] = points[k]
            const p = at(u, v)
            const usedBefore = used.length
            let reached = false
            while (moves < maxMoves && ninja === n0 && deaths == 0)
            {
                const dx = p.x - ninja.x, dy = p.y - ninja.y, d = Math.hypot(dx, dy)
                if (contact === null && d <= speed) { reached = true; break }
                if (contact !== null && elements[contact].passThrough) { reached = true; break }
                ninja.speedX = speed * dx / d; ninja.speedY = speed * dy / d
                ninja.move()
                ++moves
                usedNow()
            }
            legs.push({to: [u, v, contact], reached, newlyUsed: used.slice(usedBefore).map(x => x.piece)})
            if (!reached)
                break
        }
    } finally { onLethalDeath = lethal }
    return {legs, used, moves, deaths, hpBefore, hpAfter: momentumState.hp,
        streakAfter: momentumState.greenStreak, sameNinja: ninja === n0,
        version, runInProgress,
        pieces: elements.map(e => e instanceof MomentumBlue ? 'blue' : 'green')}
}'''


class MomentumStreakRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.types = [t for t in json.loads(CATALOG.read_text()) if t['streakBuilder']]
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
        cls.addClassCleanup(context.close)
        cls.page = context.new_page()
        cls.errors = []
        cls.page.on('pageerror', lambda e: cls.errors.append(str(e)))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.evaluate(SEED_COURSE, SCRIPT)
        cls.page.evaluate('''() => { startGame('momentum'); cancelAnimationFrame(game)
            floors.find(f => f instanceof MomentumObstacleFloor).elements = [] }''')

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_streak_routes(self):
        print('streak builders:', [t['id'] for t in self.types])
        self.assertGreater(len(self.types), 0)
        summary = {}
        for t in self.types:
            with self.subTest(id=t['id']):
                route = t['routes'][0]
                points = route['points']
                contacts = [p[2] for p in points if p[2] is not None]
                r = self.page.evaluate(DRIVE, [t['id'], points, DRIVE_SPEED, MAX_MOVES])
                used = r['used']
                greens = [u for u in used if u['kind'] == 'green']
                blues = [u for u in used if u['kind'] == 'blue']
                fifth = greens[4] if len(greens) >= 5 else None
                hp5 = fifth['hp'] if fifth else None
                print(f"{t['id']} route {route['name']}: contacts {contacts} used {[u['piece'] for u in used]}"
                      f" greens touched {len(greens)} blues touched {len(blues)}"
                      f" hp before {r['hpBefore']} after 5th green {hp5} after route {r['hpAfter']}"
                      f" streak after {r['streakAfter']} deaths {r['deaths']} moves {r['moves']}")
                for leg in r['legs']:
                    print('   leg ->', leg['to'], 'reached' if leg['reached'] else 'NOT REACHED',
                          'used', leg['newlyUsed'])
                summary[t['id']] = {
                    'route': route['name'], 'contacts': contacts, 'used': [u['piece'] for u in used],
                    'greens': len(greens), 'blues': len(blues), 'hpBefore': r['hpBefore'],
                    'hpAfter5': hp5, 'hpAfter': r['hpAfter'], 'streakAfter': r['streakAfter'],
                    'deaths': r['deaths'], 'moves': r['moves']}
                self.assertEqual(r['version'], 'momentum')
                self.assertTrue(r['runInProgress'])
                self.assertTrue(r['sameNinja'])
                self.assertEqual(r['deaths'], 0)
                self.assertTrue(all(leg['reached'] for leg in r['legs']))
                self.assertEqual(len(r['legs']), len(points) - 1)
                self.assertEqual([u['piece'] for u in used], contacts)
                self.assertEqual(blues, [])
                self.assertGreaterEqual(len(greens), 5)
                # Greens in a row: streak 1..4, then the 5th trades the streak for one hp
                self.assertEqual([g['streak'] for g in greens[:4]], [1, 2, 3, 4])
                self.assertEqual([g['hp'] for g in greens[:4]], [5] * 4)
                self.assertEqual(r['hpBefore'], 5)
                self.assertEqual((fifth['hp'], fifth['streak']), (6, 0))
                self.assertEqual(r['hpAfter'], 6)
                self.assertEqual(r['streakAfter'], len(greens) - 5)
        (EVIDENCE_DIR / 'streak-routes.json').write_text(json.dumps(summary, separators=(',', ':')))
        print('wrote streak-routes.json with', len(summary), 'types')


if __name__ == '__main__':
    unittest.main()
