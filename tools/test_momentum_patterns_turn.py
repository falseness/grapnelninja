"""Momentum turn obstacle patterns (elements/momentumpatterns.js).

Reads the TASK-013 catalog (MOMENTUM_CATALOG_V, default
artifacts/TASK-013/catalog-v.json) and checks every kind 'turn' type of it.
Starts momentum on a scripted course (MomentumCourse.generate, as in
test_momentum_borders) of five long segments R U R D R, so its four joins are
right->up, up->right, right->down and down->right, stops the rAF loop,
empties the bad obstacle floor and places each type alone with
window.momentumPlaceTurn(id, segmentIndex) on every join it declares.
Asserts: all turn ids are registered (momentumTurnFactories) and
momentumTurnsByJoin lists exactly the types declaring each join; a join a type
does not declare places nothing (null); per type and join the element count,
green count and blue count equal the catalog, piece by piece (class and box
at the catalog fractions of the 2 x 2 band square, moved by the join's
transform onto the course vertex; since TASK-031 its side across the shaft
is 4 of the shaft's own half widths); no element is lethal; no piece crosses a
border line (momentumBorders() of the segments around the join) and every
piece lies inside the corridor (incoming corridor or outgoing one).

MomentumTurnRouteTests drives the ninja along every catalog route of every
type and declared join (reversed for down->right and up->right, as the
catalog's transform table says): per leg the velocity is aimed at the next
route point and ninja.move() runs real collisions (borders included) until a
plain point is reached or the contact green is used. The camera is centred on
the ninja before every move. Asserts every leg is reached, no death, the run
stays the same; a safe route uses exactly its contact greens in order and no
blue (hp 5, +1 per 5 greens); a fast route uses no green and
loses one hp per blue.

Writes to MOMENTUM_PATTERNS_TURN_EVIDENCE_DIR (default artifacts/TASK-017):
patterns-turn.json (compact {id: {joins, greens, blues}}), turn-routes.json
(compact per run results) and turn-<id>-<from>-<to>.png (game canvas round
the corner, the routes drawn as dashed overlays are not part of the game).

Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(os.environ.get('MOMENTUM_CATALOG_V', ROOT / 'artifacts/TASK-013/catalog-v.json'))
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PATTERNS_TURN_EVIDENCE_DIR', ROOT / 'artifacts/TASK-017'))
# Segments: right, up, right, down, right, all ~5 heights long (>= 1.5 band)
SCRIPT = [0.99, 0.99, 0.1, 0.99, 0.99, 0.99, 0.9, 0.99, 0.99]
# Join -> the incoming segment index
JOINS = {'right->up': 0, 'up->right': 1, 'right->down': 2, 'down->right': 3}
TRANSFORMS = {
    'right->up': lambda x, y: (x, y),
    'right->down': lambda x, y: (x, 1 - y),
    'down->right': lambda x, y: (1 - x, y),
    'up->right': lambda x, y: (1 - x, 1 - y),
}
REVERSED = {'down->right', 'up->right'}
EPS = 1e-6
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}
# World units per physics cycle, under GAMEPLAY.momentumMaxSpeed (5.56 at h 1080
# since TASK-029 halved it; was 10 with 2000 moves under the old 11.12 cap)
DRIVE_SPEED = 5
MAX_MOVES = 4000

START = '''() => { startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = [] }'''
# halves: per segment its own half width (vertical ones wider, TASK-030)
COURSE = '''() => ({segments: momentumCourse.take(5), half: GAMEPLAY.momentumBorders.halfWidth,
    borders: momentumBorders(), halves: momentumCourse.take(5).map(momentumSegmentHalfWidth)})'''
PLACE = '''([id, segment]) => {
    floors.find(f => f instanceof MomentumPatternFloor).elements = []
    return momentumPlaceTurn(id, segment)
}'''
SHOOT = '''([cx, cy]) => {
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
    screen.leftWall.update(screen)
    ninja.x = cx - 0.45 * w; ninja.y = cy; ninja.speedX = ninja.speedY = 0
    draw()
}'''
DRIVE = '''([id, segment, points, speed, maxMoves]) => {
    momentumState.reset()
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    const placed = momentumPlaceTurn(id, segment)
    const elements = floor.elements.slice()
    const w = width / scale[version], h = height / scale[version]
    const follow = () => {
        screen.x = -(ninja.x - w / 2); screen.y = -(ninja.y - h / 2)
        screen.leftWall.update(screen)
    }
    let deaths = 0
    const lethal = onLethalDeath
    onLethalDeath = function() { ++deaths; return lethal.apply(this, arguments) }
    const used = []
    const usedNow = () => elements.forEach((e, i) => {
        if (e.passThrough && !used.some(u => u.piece == i))
            used.push({piece: i, kind: e instanceof MomentumBlue ? 'blue' : 'green'})
    })
    const n0 = ninja
    grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
    const touches0 = momentumState.borderTouches
    ninja.x = points[0][0]; ninja.y = points[0][1]
    let moves = 0
    const legs = []
    try {
        for (let k = 1; k < points.length; ++k)
        {
            const [x, y, contact] = points[k]
            const usedBefore = used.length
            let reached = false
            while (moves < maxMoves && ninja === n0 && deaths == 0)
            {
                const dx = x - ninja.x, dy = y - ninja.y, d = Math.hypot(dx, dy)
                if (contact === null && d <= speed) { reached = true; break }
                if (contact !== null && elements[contact].passThrough) { reached = true; break }
                ninja.speedX = speed * dx / d; ninja.speedY = speed * dy / d
                follow()
                ninja.move()
                ++moves
                usedNow()
            }
            legs.push({contact, reached, newlyUsed: used.slice(usedBefore).map(u => u.piece)})
            if (!reached)
                break
        }
    } finally { onLethalDeath = lethal }
    return {join: placed.join, legs, used, moves, deaths, hp: momentumState.hp,
        borderTouches: momentumState.borderTouches - touches0, end: [ninja.x, ninja.y],
        sameNinja: ninja === n0, version, runInProgress}
}'''


def turn_types():
    return [t for t in json.loads(CATALOG.read_text()) if t['kind'] == 'turn']


def to_world(join, vertex, size, x, y):
    """Catalog square point (right->up drawing) -> world point for join;
    size: (x, y) sides of the square (x across the shaft, TASK-031)."""
    tx, ty = TRANSFORMS[join](x, y)
    vx, vy = TRANSFORMS[join](0.75, 0.75)
    return vertex[0] + (tx - vx) * size[0], vertex[1] + (ty - vy) * size[1]


def turn_size(course, i):
    """Square sides at join i: 4 shaft half widths across the shaft (x), 4
    base half widths across the right corridor (y)."""
    segs, halves = course['segments'], course['halves']
    shaft = i + 1 if segs[i]['dir'] == 'right' else i
    return 4 * halves[shaft], 4 * course['half']


def corridor_rect(s, hx, hy):
    """Corridor of segment s run on hx / hy past both ends: [l, t, r, b]."""
    return [min(s['x0'], s['x1']) - hx, min(s['y0'], s['y1']) - hy,
            max(s['x0'], s['x1']) + hx, max(s['y0'], s['y1']) + hy]


def inside(rect, x, y):
    return rect[0] - EPS <= x <= rect[2] + EPS and rect[1] - EPS <= y <= rect[3] + EPS


def crosses(line, box):
    """Does the axis-aligned border line run through the open interior of box?"""
    l, t, r, b = box
    if abs(line['y0'] - line['y1']) < EPS:
        y, lo, hi = line['y0'], min(line['x0'], line['x1']), max(line['x0'], line['x1'])
        return t + EPS < y < b - EPS and lo < r - EPS and hi > l + EPS
    x, lo, hi = line['x0'], min(line['y0'], line['y1']), max(line['y0'], line['y1'])
    return l + EPS < x < r - EPS and lo < b - EPS and hi > t + EPS


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
    cls.course = cls.page.evaluate(COURSE)


class MomentumPatternsTurnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.types = turn_types()
        open_page(cls)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_1_course_and_registry(self):
        segs, half = self.course['segments'], self.course['half']
        print('course:', [(s['dir'], round(s['length'], 1)) for s in segs], 'half width', half,
              '1.5 band', 3 * half)
        for join, i in JOINS.items():
            self.assertEqual(f"{segs[i]['dir']}->{segs[i + 1]['dir']}", join)
            self.assertGreaterEqual(segs[i]['length'], 3 * half)
            self.assertGreaterEqual(segs[i + 1]['length'], 3 * half)
        ids = self.page.evaluate('Object.keys(momentumTurnFactories)')
        by_join = self.page.evaluate('momentumTurnsByJoin')
        want = [t['id'] for t in self.types]
        print('turn catalog:', len(want), want, 'joins:', {t['id']: t['joins'] for t in self.types})
        print('registered:', ids)
        print('by join:', by_join)
        self.assertEqual(len(want), 4)
        self.assertEqual(ids, want)
        for join in JOINS:
            self.assertEqual(by_join[join], [t['id'] for t in self.types if join in t['joins']])
        for t in self.types:
            for join, i in JOINS.items():
                if join not in t['joins']:
                    r = self.page.evaluate(PLACE, [t['id'], i])
                    print(f"{t['id']} {join}: not declared -> {r}")
                    self.assertIsNone(r)
        self.assertIsNone(self.page.evaluate(PLACE, ['no-such-turn', 0]))
        self.assertIsNone(self.page.evaluate(PLACE, ['bad-frame6-v', 0]))
        self.assertIsNone(self.page.evaluate("momentumPlacePattern('corner-kicker', 0, 0, 'right')"))

    def test_2_types_match_catalog(self):
        summary = {}
        half = self.course['half']
        segs = self.course['segments']
        for t in self.types:
            entry = {'joins': t['joins']}
            for join in t['joins']:
                with self.subTest(id=t['id'], join=join):
                    i = JOINS[join]
                    r = self.page.evaluate(PLACE, [t['id'], i])
                    self.assertIsNotNone(r)
                    self.assertEqual(r['join'], join)
                    size = turn_size(self.course, i)
                    self.assertAlmostEqual(r['size']['x'], size[0], delta=EPS)
                    self.assertAlmostEqual(r['size']['y'], size[1], delta=EPS)
                    vertex = (segs[i]['x1'], segs[i]['y1'])
                    self.assertAlmostEqual(r['vertex']['x'], vertex[0], delta=EPS)
                    self.assertAlmostEqual(r['vertex']['y'], vertex[1], delta=EPS)
                    els = r['elements']
                    kinds = [p['kind'] for p in t['pieces']]
                    greens = sum(e['className'] == 'MomentumGreen' for e in els)
                    blues = sum(e['className'] == 'MomentumBlue' for e in els)
                    lethal = sum(e['lethal'] for e in els)
                    lines = [b for b in self.course['borders'] if i - 1 <= b['segment'] <= i + 2]
                    rects = [corridor_rect(segs[k], size[0] / 4, half) for k in (i, i + 1)]
                    crossings = 0
                    outside = 0
                    for p, e in zip(t['pieces'], els):
                        self.assertEqual(e['className'], CLASSES[p['kind']])
                        a = to_world(join, vertex, size, p['x'], p['y'])
                        b = to_world(join, vertex, size, p['x'] + p['w'], p['y'] + p['h'])
                        want = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
                        got = [e['left'], e['top'], e['right'], e['bottom']]
                        for g, w in zip(got, want):
                            self.assertAlmostEqual(g, w, delta=EPS)
                        crossings += sum(crosses(line, got) for line in lines)
                        corners = [(got[0], got[1]), (got[2], got[1]), (got[0], got[3]), (got[2], got[3])]
                        outside += not all(any(inside(rc, x, y) for rc in rects) for x, y in corners)
                    print(f"{t['id']} {join} (segment {i} vertex {vertex[0]:.1f},{vertex[1]:.1f}):"
                          f" elements {len(els)}/{len(kinds)} greens {greens}/{kinds.count('green')}"
                          f" blues {blues}/{kinds.count('blue')} lethal {lethal}"
                          f" border lines checked {len(lines)} crossings {crossings} outside corridor {outside}")
                    self.assertGreaterEqual(len(lines), 6)
                    self.assertEqual(len(els), len(kinds))
                    self.assertEqual(greens, kinds.count('green'))
                    self.assertEqual(blues, kinds.count('blue'))
                    self.assertEqual(lethal, 0)
                    self.assertEqual(crossings, 0)
                    self.assertEqual(outside, 0)
                    entry.update({'greens': greens, 'blues': blues})
            summary[t['id']] = entry
        (EVIDENCE_DIR / 'patterns-turn.json').write_text(json.dumps(summary, separators=(',', ':')))
        print('wrote patterns-turn.json with', len(summary), 'types,',
              sum(len(v['joins']) for v in summary.values()), 'placements')

    def test_3_screenshots(self):
        half = self.course['half']
        segs = self.course['segments']
        for t in self.types:
            for join in t['joins']:
                with self.subTest(id=t['id'], join=join):
                    i = JOINS[join]
                    self.page.evaluate(PLACE, [t['id'], i])
                    # Centre of the 2 x 2 band square
                    cx, cy = to_world(join, (segs[i]['x1'], segs[i]['y1']), turn_size(self.course, i), 0.5, 0.5)
                    self.page.evaluate(SHOOT, [cx, cy])
                    path = EVIDENCE_DIR / f"turn-{t['id']}-{join.replace('->', '-')}.png"
                    self.page.screenshot(path=str(path))
                    print('wrote', path.name)
                    self.assertTrue(path.exists())
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")


class MomentumTurnRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.types = turn_types()
        open_page(cls)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_routes_through_turns(self):
        half = self.course['half']
        segs = self.course['segments']
        summary = {}
        for t in self.types:
            for join in t['joins']:
                i = JOINS[join]
                vertex = (segs[i]['x1'], segs[i]['y1'])
                for route in t['routes']:
                    with self.subTest(id=t['id'], join=join, route=route['name']):
                        points = route['points'][::-1] if join in REVERSED else route['points']
                        world = [[*to_world(join, vertex, turn_size(self.course, i), x, y), c]
                                 for x, y, c in points]
                        contacts = [p[2] for p in points if p[2] is not None]
                        r = self.page.evaluate(DRIVE, [t['id'], i, world, DRIVE_SPEED, MAX_MOVES])
                        used = r['used']
                        greens = [u['piece'] for u in used if u['kind'] == 'green']
                        blues = [u['piece'] for u in used if u['kind'] == 'blue']
                        reached = sum(leg['reached'] for leg in r['legs'])
                        # The route ends in the outgoing corridor, past the vertex
                        out = segs[i + 1]
                        dx, dy = r['end'][0] - vertex[0], r['end'][1] - vertex[1]
                        along = dx * (out['x1'] - out['x0']) / out['length'] + dy * (out['y1'] - out['y0']) / out['length']
                        print(f"{t['id']} {join} route {route['name']}{' (fast)' if route['fast'] else ''}:"
                              f" legs reached {reached}/{len(points) - 1} contacts {contacts} used greens {greens}"
                              f" blues {blues} hp {r['hp']} border touches {r['borderTouches']}"
                              f" deaths {r['deaths']} alive {r['sameNinja'] and r['runInProgress']}"
                              f" end past vertex {along:.1f} moves {r['moves']}")
                        summary[f"{t['id']}/{join}/{route['name']}"] = {
                            'fast': route['fast'], 'reached': reached, 'legs': len(points) - 1,
                            'greens': greens, 'blues': blues, 'hp': r['hp'], 'deaths': r['deaths'],
                            'past': round(along, 1), 'moves': r['moves']}
                        self.assertEqual(r['join'], join)
                        self.assertEqual(r['version'], 'momentum')
                        self.assertTrue(r['runInProgress'])
                        self.assertTrue(r['sameNinja'])
                        self.assertEqual(r['deaths'], 0)
                        self.assertEqual(reached, len(points) - 1)
                        self.assertGreater(along, half)
                        if route['fast']:
                            # The fast route costs a blue: hp 5 -> 4 per blue, no green
                            self.assertEqual(greens, [])
                            self.assertGreaterEqual(len(blues), 1)
                            self.assertEqual(r['hp'], 5 - len(blues))
                        else:
                            # Every fifth green in a streak gives an hp (pinwheel: 6 greens)
                            self.assertEqual(greens, contacts)
                            self.assertEqual(blues, [])
                            self.assertEqual(r['hp'], 5 + len(greens) // 5)
        (EVIDENCE_DIR / 'turn-routes.json').write_text(json.dumps(summary, separators=(',', ':')))
        print('wrote turn-routes.json with', len(summary), 'runs')


if __name__ == '__main__':
    unittest.main()
