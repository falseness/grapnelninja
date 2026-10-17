"""Momentum vertical obstacle patterns (elements/momentumpatterns.js).

Reads the TASK-013 catalog (MOMENTUM_CATALOG_V, default
artifacts/TASK-013/catalog-v.json) and checks every kind 'vertical' type of
it. Starts momentum on a scripted course (MomentumCourse.generate, as in
test_momentum_borders) whose segment 1 goes up and segment 3 goes down, both
long, stops the rAF loop, empties the bad obstacle floor and places each type
alone with window.momentumPlacePattern in each of its directions. Asserts:
all vertical catalog ids are registered (momentumPatternFactories) and
momentumPatternsByDir up/down list exactly the types whose catalog dirs name
that direction; per type and direction the element count, green count and
blue count equal the catalog piece list, piece by piece (class and box at the
catalog fractions of the shaft and footprint); no element is lethal (only
MomentumGreen/MomentumBlue); every element lies between the two dark-green
walls of its segment (momentumBorders(), at the segment's own half width
since TASK-030) and inside the footprint, which
stays clear of both turns. A direction the type is not built for (and
'right') places nothing (null).

MomentumVStreakRouteTests drives the ninja along the route of every vertical
streak builder, in each of its directions (down = the route reversed), like
test_momentum_streak_routes: per leg the velocity is aimed at the next route
point and ninja.move() runs real collisions until a plain point is reached or
the contact green is used. Asserts the greens are used in contact order, 0
blues, no death, and the fifth green makes hp 5 -> 6.

Writes to MOMENTUM_PATTERNS_V_EVIDENCE_DIR (default artifacts/TASK-016):
patterns-v.json (compact {id: {dirs, refused, greens, blues, classes, lethal,
bboxShaft}}; bboxShaft in shaft/footprint fractions), vstreak-route.json and
compare-<id>.png (game canvas left, catalog SVG right).

Requires Playwright Chromium and Pillow. No remote requests.
"""
import io
import json
import os
from pathlib import Path
import unittest

from PIL import Image

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(os.environ.get('MOMENTUM_CATALOG_V', ROOT / 'artifacts/TASK-013/catalog-v.json'))
SVG_DIR = CATALOG.parent / 'diagrams'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PATTERNS_V_EVIDENCE_DIR', ROOT / 'artifacts/TASK-016'))
# Segments: right (short), up (~5 heights), right (short), down (~5 heights)
# Segment 2 long (0.9) so the down shaft stays clear of the up one
# (MomentumCourse oppositeShaftGap, TASK-030)
SCRIPT = [0.1, 0.99, 0.1, 0.99, 0.9, 0.99, 0.9, 0.99]
SEGMENT = {'up': 1, 'down': 3}
EPS = 1e-6
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}
# World units per physics cycle, under GAMEPLAY.momentumMaxSpeed (5.56 at h 1080
# since TASK-029 halved it; was 10 with 1000 moves under the old 11.12 cap)
DRIVE_SPEED = 5
MAX_MOVES = 2000

START = '''() => { startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = [] }'''
# Footprint start: on the centre line, 1.2 half widths into the shaft
FOOTPRINT = '''(dir) => {
    const s = momentumCourse.segment(dir == 'up' ? 1 : 3)
    const half = GAMEPLAY.momentumBorders.halfWidth
    return {x: s.x0, y: s.y0 + (dir == 'up' ? -1.2 : 1.2) * half, segment: s, half: half,
            walls: momentumBorders().filter(b => b.segment == (dir == 'up' ? 1 : 3))}
}'''
PLACE = '''([id, x, y, dir]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    return momentumPlacePattern(id, x, y, dir)
}'''
SHOOT = '''([cx, cy]) => {
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
    screen.leftWall.update(screen)
    ninja.x = cx - 0.45 * w; ninja.y = cy; ninja.speedX = ninja.speedY = 0
    draw()
}'''
DRIVE = '''([id, dir, points, speed, maxMoves, x0, y0]) => {
    momentumState.reset()
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    const half = GAMEPLAY.momentumBorders.halfWidth
    const placed = momentumPlacePattern(id, x0, y0, dir)
    const elements = floor.elements.slice()
    const left = x0 - half, top = dir == 'up' ? y0 - placed.length : y0
    const at = (u, v) => ({x: left + u * 2 * half, y: top + v * placed.length})
    // Keep the pattern in view: no out-of-view death while driving
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(x0 - w / 2); screen.y = -(top + placed.length / 2 - h / 2)
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
        streakAfter: momentumState.greenStreak, sameNinja: ninja === n0, version, runInProgress}
}'''


def vertical_types():
    return [t for t in json.loads(CATALOG.read_text()) if t['kind'] == 'vertical']


def open_page(cls):
    cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
    context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
    cls.addClassCleanup(context.close)
    cls.page = context.new_page()
    cls.errors = []
    cls.page.on('pageerror', lambda e: cls.errors.append(str(e)))
    cls.page.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
    cls.page.goto(cls.url)
    wait_for_boot_run(cls.page)
    cls.page.evaluate(SEED_COURSE, SCRIPT)
    cls.page.evaluate(START)
    cls.footprint = {d: cls.page.evaluate(FOOTPRINT, d) for d in ('up', 'down')}


class MomentumPatternsVTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.types = vertical_types()
        open_page(cls)
        cls.summary = {}

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def place(self, t, dir):
        f = self.footprint[dir]
        return f, self.page.evaluate(PLACE, [t['id'], f['x'], f['y'], dir])

    def test_1_course_and_registry(self):
        for d, f in self.footprint.items():
            s = f['segment']
            walls = [round(w['x0'], 2) for w in f['walls']]
            print(f"segment {SEGMENT[d]}: {s['dir']} length {s['length']:.1f} x {s['x0']:.1f}"
                  f" y {s['y0']:.1f} -> {s['y1']:.1f} walls x {walls}")
            self.assertEqual(s['dir'], d)
            self.assertEqual([w['kind'] for w in f['walls']], ['wall', 'wall'])
        ids = self.page.evaluate('Object.keys(momentumPatternFactories)')
        by_dir = self.page.evaluate('momentumPatternsByDir')
        want = [t['id'] for t in self.types]
        print('vertical catalog:', len(want), want, 'difficulties:', [t['difficulty'] for t in self.types])
        print('registered:', len(ids), ids)
        print('by direction:', by_dir)
        self.assertEqual([i for i in ids if i in want], want)
        self.assertEqual(len(want), 6)
        for d in ('up', 'down'):
            self.assertEqual(by_dir[d], [t['id'] for t in self.types if d in t['dirs']])
        self.assertFalse(set(want) & set(by_dir['right']))

    def test_2_types_match_catalog(self):
        for t in self.types:
            entry = {'dirs': t['dirs'], 'refused': []}
            for d in ('up', 'down', 'right'):
                with self.subTest(id=t['id'], dir=d):
                    f = self.footprint['up' if d == 'right' else d]
                    r = self.page.evaluate(PLACE, [t['id'], f['x'], f['y'], d])
                    if d not in t['dirs']:
                        print(f"{t['id']} {d}: not built for it -> {r}")
                        self.assertIsNone(r)
                        entry['refused'].append(d)
                        continue
                    self.check_placement(t, d, f, r, entry)
            self.summary[t['id']] = entry
        (EVIDENCE_DIR / 'patterns-v.json').write_text(json.dumps(self.summary, separators=(',', ':')))
        print('wrote patterns-v.json with', len(self.summary), 'types; lethal elements in all types',
              sum(v['lethal'] for v in self.summary.values()))

    def check_placement(self, t, d, f, r, entry):
        half, s = f['half'], f['segment']
        band = 2 * half
        length = t['span'] * band
        x, y = f['x'], f['y']
        left, top = x - half, (y - length if d == 'up' else y)
        self.assertAlmostEqual(r['length'], length, delta=EPS)
        els = r['elements']
        kinds = [p['kind'] for p in t['pieces']]
        greens = sum(e['className'] == 'MomentumGreen' for e in els)
        blues = sum(e['className'] == 'MomentumBlue' for e in els)
        lethal = sum(e['lethal'] for e in els)
        classes = {}
        for e in els:
            classes[e['className']] = classes.get(e['className'], 0) + 1
        print(f"{t['id']} {d}: elements {len(els)}/{len(kinds)} greens {greens}/{kinds.count('green')}"
              f" blues {blues}/{kinds.count('blue')} lethal {lethal} classes {classes}")
        self.assertEqual(len(els), len(kinds))
        self.assertEqual(greens, kinds.count('green'))
        self.assertEqual(blues, kinds.count('blue'))
        self.assertEqual(lethal, 0)
        self.assertTrue(set(classes) <= set(CLASSES.values()))
        wall_lo = min(w['x0'] for w in f['walls'])
        wall_hi = max(w['x0'] for w in f['walls'])
        # Walls at the shaft's own (wider, TASK-030) half width; patterns
        # still span the base band around the centre line
        shaft_half = f['segment'].get('halfWidth', half)
        self.assertGreaterEqual(shaft_half, half)
        self.assertAlmostEqual(wall_lo, x - shaft_half, delta=EPS)
        self.assertAlmostEqual(wall_hi, x + shaft_half, delta=EPS)
        for p, e in zip(t['pieces'], els):
            self.assertEqual(e['className'], CLASSES[p['kind']])
            want = [left + p['x'] * band, top + p['y'] * length,
                    left + (p['x'] + p['w']) * band, top + (p['y'] + p['h']) * length]
            got = [e['left'], e['top'], e['right'], e['bottom']]
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, delta=EPS)
            self.assertGreaterEqual(e['left'], wall_lo - EPS)
            self.assertLessEqual(e['right'], wall_hi + EPS)
            self.assertGreaterEqual(e['top'], top - EPS)
            self.assertLessEqual(e['bottom'], top + length + EPS)
        # Clear of the turns at both ends of the shaft
        ends = sorted([s['y0'], s['y1']])
        self.assertGreaterEqual(top, ends[0] + half)
        self.assertLessEqual(top + length, ends[1] - half)
        bbox = [min(e['left'] for e in els), min(e['top'] for e in els),
                max(e['right'] for e in els), max(e['bottom'] for e in els)]
        print(f"  between walls x {wall_lo:.1f}..{wall_hi:.1f}: bbox x {bbox[0]:.1f}..{bbox[2]:.1f}"
              f" y {bbox[1]:.1f}..{bbox[3]:.1f} footprint y {top:.1f}..{top + length:.1f}"
              f" shaft y {ends[0]:.1f}..{ends[1]:.1f}")
        entry.update({'greens': greens, 'blues': blues, 'classes': classes, 'lethal': lethal})
        entry.setdefault('bboxShaft', {})[d] = [
            round((bbox[0] - left) / band, 4), round((bbox[1] - top) / length, 4),
            round((bbox[2] - left) / band, 4), round((bbox[3] - top) / length, 4)]

    def test_3_compare_screenshots(self):
        svg_page = self.browser.new_page()
        self.addCleanup(svg_page.close)
        for t in self.types:
            with self.subTest(id=t['id']):
                d = t['dirs'][0]
                f, r = self.place(t, d)
                top = f['y'] - r['length'] if d == 'up' else f['y']
                self.page.evaluate(SHOOT, [f['x'], top + r['length'] / 2])
                game = Image.open(io.BytesIO(self.page.screenshot())).convert('RGB')
                svg = (SVG_DIR / f"{t['id']}.svg").read_text()
                svg_page.set_content(f'<html><body style="margin:0">{svg}</body></html>')
                diagram = Image.open(io.BytesIO(svg_page.locator('svg').screenshot())).convert('RGB')
                diagram = diagram.resize((round(diagram.width * game.height / diagram.height), game.height))
                out = Image.new('RGB', (game.width + diagram.width + 8, game.height), (255, 255, 255))
                out.paste(game, (0, 0))
                out.paste(diagram, (game.width + 8, 0))
                path = EVIDENCE_DIR / f"compare-{t['id']}.png"
                out.save(path)
                print('wrote', path.name, out.size, 'dir', d)
                self.assertTrue(path.exists())
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")


class MomentumVStreakRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.types = [t for t in vertical_types() if t['streakBuilder']]
        open_page(cls)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_vertical_streak_routes(self):
        print('vertical streak builders:', [t['id'] for t in self.types])
        self.assertGreater(len(self.types), 0)
        summary = {}
        for t in self.types:
            route = t['routes'][0]
            for d in t['dirs']:
                with self.subTest(id=t['id'], dir=d):
                    # Routes are drawn in dirs[0] order; the other way runs them backwards
                    points = route['points'] if d == t['dirs'][0] else route['points'][::-1]
                    contacts = [p[2] for p in points if p[2] is not None]
                    f = self.footprint[d]
                    r = self.page.evaluate(DRIVE, [t['id'], d, points, DRIVE_SPEED, MAX_MOVES,
                                                   f['x'], f['y']])
                    used = r['used']
                    greens = [u for u in used if u['kind'] == 'green']
                    blues = [u for u in used if u['kind'] == 'blue']
                    fifth = greens[4] if len(greens) >= 5 else None
                    hp5 = fifth['hp'] if fifth else None
                    print(f"{t['id']} {d} route {route['name']}: contacts {contacts}"
                          f" used {[u['piece'] for u in used]} greens touched {len(greens)}"
                          f" blues touched {len(blues)} hp before {r['hpBefore']} after 5th green {hp5}"
                          f" after route {r['hpAfter']} streak after {r['streakAfter']}"
                          f" deaths {r['deaths']} moves {r['moves']}")
                    for leg in r['legs']:
                        print('   leg ->', leg['to'], 'reached' if leg['reached'] else 'NOT REACHED',
                              'used', leg['newlyUsed'])
                    summary[f"{t['id']}/{d}"] = {
                        'route': route['name'], 'contacts': contacts, 'used': [u['piece'] for u in used],
                        'greens': len(greens), 'blues': len(blues), 'hpBefore': r['hpBefore'],
                        'hpAfter5': hp5, 'hpAfter': r['hpAfter'], 'streakAfter': r['streakAfter'],
                        'deaths': r['deaths'], 'moves': r['moves']}
                    self.assertEqual(r['version'], 'momentum')
                    self.assertTrue(r['runInProgress'])
                    self.assertTrue(r['sameNinja'])
                    self.assertEqual(r['deaths'], 0)
                    self.assertEqual(len(r['legs']), len(points) - 1)
                    self.assertTrue(all(leg['reached'] for leg in r['legs']))
                    self.assertEqual([u['piece'] for u in used], contacts)
                    self.assertEqual(blues, [])
                    self.assertGreaterEqual(len(greens), 5)
                    self.assertEqual([g['streak'] for g in greens[:4]], [1, 2, 3, 4])
                    self.assertEqual([g['hp'] for g in greens[:4]], [5] * 4)
                    self.assertEqual(r['hpBefore'], 5)
                    self.assertEqual((fifth['hp'], fifth['streak']), (6, 0))
                    self.assertEqual(r['hpAfter'], 6)
                    self.assertEqual(r['streakAfter'], len(greens) - 5)
        (EVIDENCE_DIR / 'vstreak-route.json').write_text(json.dumps(summary, separators=(',', ':')))
        print('wrote vstreak-route.json with', len(summary), 'runs')


if __name__ == '__main__':
    unittest.main()
