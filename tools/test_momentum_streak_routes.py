"""Momentum green-streak route through ported bad frames (elements/momentumpatterns.js).

Since TASK-038 the right segments spawn the ported bad frames only
(MOMENTUM_PATTERNS_PORT_H). No ported frame has five greens (at most three,
artifacts/TASK-038/streak.md), so the HP gain is driven across two
consecutive frames: the ROUTE frames (bad-frame5 then bad-frame14, three
greens each, no blue) are placed one after the other on the first (long,
right) segment of a scripted course, GAP world units apart, the rAF loop is
stopped and the ninja is driven along the route: per leg the test aims the
velocity (DRIVE_SPEED, straight line, ninja.move() has no gravity) from where
the ninja is at the leg's contact green (its centre) or plain point and
steps ninja.move() (real collisions, bounces and one-time uses) until the
point is reached or the contact green is used. The view follows the ninja.
Asserts: the greens are used in the route's contact order and nothing else
is touched (0 blues, no green out of order), no death, and the fifth green
in a row (the second of bad-frame14) makes hp 5 -> 6 (streak back to 0).

Writes MOMENTUM_STREAK_EVIDENCE_DIR (default artifacts/TASK-038)/streak-routes.json
(compact {frames, route, contacts, used, greens, blues, hpBefore, hpAfter5,
hpAfter, streakAfter, deaths, moves}).

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
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_STREAK_EVIDENCE_DIR', ROOT / 'artifacts/TASK-038'))
# World units per physics cycle, under GAMEPLAY.momentumMaxSpeed (5.56 at h 1080)
DRIVE_SPEED = 5
MAX_MOVES = 4000
ROUTE_FRAMES = ['bad-frame5', 'bad-frame14']
# World units between the two footprints (a spawn gap is >= 0.6 view widths)
GAP = 600
# Route points: ['at', x, y] = a plain point, x along from the first
# footprint start, y across from the corridor centre line; ['hit', frame,
# piece] = aim at that piece's centre, the leg ends when it is used. Piece
# order is the catalog's: bad-frame5 / bad-frame14 greens 0 = far wall,
# 1 = near wall, 2 = shelf. The first point is the start.
ROUTE = [['at', -150, 0], ['hit', 0, 1], ['hit', 0, 2], ['hit', 0, 0],
         ['hit', 1, 1], ['hit', 1, 2], ['hit', 1, 0]]

DRIVE = '''([ids, gap, route, speed, maxMoves]) => {
    momentumState.reset()
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    const s = momentumCourse.segment(0)
    const half = GAMEPLAY.momentumBorders.halfWidth
    const x0 = s.x0 + 0.2 * half
    const frames = []
    let x = x0
    for (const id of ids)
    {
        const first = floor.elements.length
        const placed = momentumPlacePattern(id, x, s.y0, 'right')
        frames.push({id, x, first, length: placed.length})
        x += placed.length + gap
    }
    const elements = floor.elements.slice()
    const w = width / scale[version], h = height / scale[version]
    const follow = () => {
        screen.x = -(ninja.x - 0.4 * w); screen.y = -(s.y0 - h / 2)
        screen.leftWall.update(screen)
    }
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
    ninja.x = x0 + route[0][1]; ninja.y = s.y0 + route[0][2]
    follow()
    let moves = 0
    const legs = [], contacts = []
    try {
        for (let k = 1; k < route.length; ++k)
        {
            const [kind, a, b] = route[k]
            const contact = kind == 'hit' ? frames[a].first + b : null
            let p
            if (contact !== null)
            {
                const pts = elements[contact].getPoints()
                p = {x: pts.reduce((t, q) => t + q.x, 0) / pts.length, y: pts.reduce((t, q) => t + q.y, 0) / pts.length}
                contacts.push(contact)
            }
            else
                p = {x: x0 + a, y: s.y0 + b}
            const usedBefore = used.length
            let reached = false
            while (moves < maxMoves && ninja === n0 && deaths == 0)
            {
                const dx = p.x - ninja.x, dy = p.y - ninja.y, d = Math.hypot(dx, dy)
                if (contact === null && d <= speed) { reached = true; break }
                if (contact !== null && elements[contact].passThrough) { reached = true; break }
                ninja.speedX = speed * dx / d; ninja.speedY = speed * dy / d
                ninja.move()
                follow()
                ++moves
                usedNow()
            }
            legs.push({to: route[k], contact, reached, newlyUsed: used.slice(usedBefore).map(x => x.piece)})
            if (!reached)
                break
        }
    } finally { onLethalDeath = lethal }
    return {frames, legs, contacts, used, moves, deaths, hpBefore, hpAfter: momentumState.hp,
        streakAfter: momentumState.greenStreak, sameNinja: ninja === n0,
        version, runInProgress,
        pieces: elements.map(e => e instanceof MomentumBlue ? 'blue' : 'green')}
}'''


class MomentumStreakRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
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

    def test_streak_across_two_ported_frames(self):
        r = self.page.evaluate(DRIVE, [ROUTE_FRAMES, GAP, ROUTE, DRIVE_SPEED, MAX_MOVES])
        used = r['used']
        greens = [u for u in used if u['kind'] == 'green']
        blues = [u for u in used if u['kind'] == 'blue']
        fifth = greens[4] if len(greens) >= 5 else None
        hp5 = fifth['hp'] if fifth else None
        print('frames:', [(f['id'], round(f['x'], 1), f['first'], round(f['length'], 1)) for f in r['frames']],
              'pieces:', r['pieces'])
        print(f"route {ROUTE}: contacts {r['contacts']} used {[u['piece'] for u in used]}"
              f" greens touched {len(greens)} blues touched {len(blues)}"
              f" hp before {r['hpBefore']} after 5th green {hp5} after route {r['hpAfter']}"
              f" streak after {r['streakAfter']} deaths {r['deaths']} moves {r['moves']}")
        print('greens (piece, streak, hp):', [(g['piece'], g['streak'], g['hp']) for g in greens])
        for leg in r['legs']:
            print('   leg ->', leg['to'], 'contact', leg['contact'], 'reached' if leg['reached'] else 'NOT REACHED',
                  'used', leg['newlyUsed'])
        (EVIDENCE_DIR / 'streak-routes.json').write_text(json.dumps({
            'frames': ROUTE_FRAMES, 'route': ROUTE, 'contacts': r['contacts'], 'used': [u['piece'] for u in used],
            'greens': len(greens), 'blues': len(blues), 'hpBefore': r['hpBefore'], 'hpAfter5': hp5,
            'hpAfter': r['hpAfter'], 'streakAfter': r['streakAfter'], 'deaths': r['deaths'],
            'moves': r['moves']}, separators=(',', ':')))
        self.assertEqual(r['version'], 'momentum')
        self.assertTrue(r['runInProgress'])
        self.assertTrue(r['sameNinja'])
        self.assertEqual([f['id'] for f in r['frames']], ROUTE_FRAMES)
        self.assertEqual(r['pieces'], ['green'] * 6)
        self.assertEqual(r['deaths'], 0)
        self.assertTrue(all(leg['reached'] for leg in r['legs']))
        self.assertEqual(len(r['legs']), len(ROUTE) - 1)
        self.assertEqual([u['piece'] for u in used], r['contacts'])
        self.assertEqual(blues, [])
        self.assertEqual(len(greens), 6)
        # Greens in a row: streak 1..4, then the 5th trades the streak for one hp
        self.assertEqual([g['streak'] for g in greens[:4]], [1, 2, 3, 4])
        self.assertEqual([g['hp'] for g in greens[:4]], [5] * 4)
        self.assertEqual(r['hpBefore'], 5)
        # The 5th green is the second piece used in bad-frame14
        self.assertGreaterEqual(fifth['piece'], r['frames'][1]['first'])
        self.assertEqual((fifth['hp'], fifth['streak']), (6, 0))
        self.assertEqual(r['hpAfter'], 6)
        self.assertEqual(r['streakAfter'], len(greens) - 5)


if __name__ == '__main__':
    unittest.main()
