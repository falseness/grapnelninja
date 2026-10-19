"""Momentum turn obstacle patterns (elements/momentumpatterns.js).

Since TASK-040 the turn types are the turn candidates of the TASK-036 port
catalog (MOMENTUM_PORT_CATALOG, default
artifacts/TASK-036/catalog-bad-port.json; entries with turnJoins): each is
the ported bad frame (MOMENTUM_PATTERNS_PORT_H) placed whole in the right
corridor at the join, before the corner box on right->up/down and after it
on up/down->right, with turnClearanceHalfWidths base half widths between.
The TASK-013 turn types are retired.

Starts momentum on a scripted course (MomentumCourse.generate, as in
test_momentum_borders) of five long segments R U R D R, so its four joins are
right->up, up->right, right->down and down->right, stops the rAF loop,
empties the bad obstacle floor and places each type alone with
window.momentumPlaceTurn(id, segmentIndex) on every join it declares.
Asserts: the registered ids are bad-frameN-turn for the catalog's turn
frames, with the catalog's joins, together covering all four joins; none of
them is in a spawn registry (momentumTurnsByJoin = the TASK-111 corner
frames FRAMES_TURN, momentumPatternsByDir); an undeclared join, a retired TASK-013 id and a
non-turn id place nothing (null); per type and join the pieces are the
source frame's (class, box = footprint start + catalog offset), none is
lethal, none crosses a border line of the segments round the join, all lie
in the right corridor (both within TOL 0.1: catalog rounding of wall-flush
pieces) and none reaches into the corner box (the shaft's
x range at the vertex) or its clearance.

MomentumTurnRouteTests drives the ninja through every type at every declared
join: a lane across the frame clear of its pieces (pieces do not move: the
rAF loop is stopped), then the course vertex (the corner), then 2500 units
out of the corner along the outgoing segment (or in reverse order for
up/down->right). Per leg the velocity is aimed at the next point and
ninja.move() runs real collisions (borders included). The camera follows
the ninja. Asserts every leg reached, no death, the same ninja and run, no
blue used, hp unchanged. Then a 1280x720 screenshot per type and join shows
the pieces round the corner with the driven path drawn as a dashed overlay
(not part of the game).

Writes to MOMENTUM_PATTERNS_TURN_EVIDENCE_DIR (default artifacts/TASK-040):
joins.json (compact {id: [joins]}), turn-geometry.json, turn-routes.json and
shots/turn-<id>-<from>-<to>.png.

Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(os.environ.get('MOMENTUM_PORT_CATALOG', ROOT / 'artifacts/TASK-036/catalog-bad-port.json'))
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PATTERNS_TURN_EVIDENCE_DIR', ROOT / 'artifacts/TASK-040'))
# Segments: right, up, right, down, right, all ~5 heights long (>= 1.5 band)
SCRIPT = [0.99, 0.99, 0.1, 0.99, 0.99, 0.99, 0.9, 0.99, 0.99]
# Join -> the incoming segment index
JOINS = {'right->up': 0, 'up->right': 1, 'right->down': 2, 'down->right': 3}
DIRS = {'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}
RETIRED = ['corner-kicker', 'apex-net', 'blue-corner-cut', 'pinwheel']
# The corner spawn registry since TASK-111 (MOMENTUM_FRAMES_TURN per join);
# the ported turn frames stay placeable with momentumPlaceTurn but spawn nowhere
FRAMES_TURN = {'right->up': ['M18'], 'up->right': ['M40', 'M98', 'M136'],
               'right->down': ['M60'], 'down->right': ['M39', 'M117', 'M134']}
EPS = 1e-6
# Port catalog rounding: wall-flush bad pieces end up to ~0.05 past the band
TOL = 0.1
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}
# World units per physics cycle, under GAMEPLAY.momentumMaxSpeed (2.78 at h 1080
# since TASK-047; was 5 under the 5.56 cap); move budget doubled with it
DRIVE_SPEED = 2.5
MAX_MOVES = 12000
# Route: how far it starts before / ends past the frame, and runs along the shaft
LEAD = 600
SHAFT_RUN = 2500

START = '''() => { startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = [] }'''
# halves: per segment its own half width (vertical ones wider, TASK-030)
COURSE = '''() => ({segments: momentumCourse.take(5), half: GAMEPLAY.momentumBorders.halfWidth,
    borders: momentumBorders(), halves: momentumCourse.take(5).map(momentumSegmentHalfWidth),
    clearance: GAMEPLAY.momentumSpawn.turnClearanceHalfWidths * GAMEPLAY.momentumBorders.halfWidth,
    radius: ninja.radius, view: [width / scale[version], height / scale[version]]})'''
PLACE = '''([id, segment]) => {
    floors.find(f => f instanceof MomentumPatternFloor).elements = []
    return momentumPlaceTurn(id, segment)
}'''
# The camera is put in the join's incoming segment: the TASK-044 wall mask
# keeps only the corridor round screen.segmentIndex (restored after drawing)
SHOOT = '''([cx, cy, path, at, segment]) => {
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
    screen.leftWall.update(screen)
    ninja.x = at[0]; ninja.y = at[1]; ninja.speedX = ninja.speedY = 0
    const i0 = screen.segmentIndex
    screen.segmentIndex = segment
    try { draw() } finally { screen.segmentIndex = i0 }
    ctx.save()
    // The canvas is width x height game pixels drawn at its own size
    const k = ctx.canvas.width / width * scale[version]
    ctx.setTransform(k, 0, 0, k, 0, 0)
    ctx.translate(screen.x, screen.y)
    ctx.strokeStyle = '#ffe14d'; ctx.lineWidth = 14; ctx.setLineDash([60, 40])
    ctx.beginPath()
    path.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))
    ctx.stroke()
    ctx.restore()
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
    const hp0 = momentumState.hp
    ninja.x = points[0][0]; ninja.y = points[0][1]
    let moves = 0
    const legs = [], path = [[ninja.x, ninja.y]]
    try {
        for (let k = 1; k < points.length; ++k)
        {
            const [x, y] = points[k]
            let reached = false
            while (moves < maxMoves && ninja === n0 && deaths == 0)
            {
                const dx = x - ninja.x, dy = y - ninja.y, d = Math.hypot(dx, dy)
                if (d <= speed) { reached = true; break }
                ninja.speedX = speed * dx / d; ninja.speedY = speed * dy / d
                follow()
                ninja.move()
                ++moves
                usedNow()
                if (moves % 50 == 0)
                    path.push([ninja.x, ninja.y])
            }
            legs.push(reached)
            path.push([ninja.x, ninja.y])
            if (!reached)
                break
        }
    } finally { onLethalDeath = lethal }
    return {join: placed.join, legs, used, moves, deaths, hp0, hp: momentumState.hp,
        borderTouches: momentumState.borderTouches - touches0, end: [ninja.x, ninja.y], path,
        sameNinja: ninja === n0, version, runInProgress, footprint: placed.footprint, vertex: placed.vertex}
}'''


def turn_frames():
    """Port catalog entries that are turn candidates."""
    return [f for f in json.loads(CATALOG.read_text()) if f['turnJoins']]


def piece_box(p, x0, y0):
    """World bounding box of a port catalog piece of a frame whose footprint
    starts at x0 on the corridor centre line y0."""
    cx, cy = x0 + p['x'], y0 + p['y']
    if p.get('points'):
        xs = [cx + q[0] for q in p['points']]
        ys = [cy + q[1] for q in p['points']]
        return [min(xs), min(ys), max(xs), max(ys)]
    return [cx - p['w'] / 2, cy - p['h'] / 2, cx + p['w'] / 2, cy + p['h'] / 2]


def lane(frame, half, radius):
    """Offset across the corridor (from its centre line) of the middle of the
    widest band clear of every piece of the frame (ninja radius kept off)."""
    edges = sorted((piece_box(p, 0, 0)[1] - radius, piece_box(p, 0, 0)[3] + radius) for p in frame['pieces'])
    free, y = [], -half + radius
    for top, bottom in edges:
        if top > y:
            free.append((y, top))
        y = max(y, bottom)
    if half - radius > y:
        free.append((y, half - radius))
    lo, hi = max(free, key=lambda f: f[1] - f[0])
    return (lo + hi) / 2, hi - lo


def route(course, frame, join, footprint):
    """Route points: lane across the frame, the vertex, SHAFT_RUN along the shaft."""
    i = JOINS[join]
    segs = course['segments']
    vx, vy = segs[i]['x1'], segs[i]['y1']
    y, _ = lane(frame, course['half'], course['radius'])
    src, dst = join.split('->')
    if src == 'right':
        d = DIRS[dst]
        return [(footprint['x0'] - LEAD, vy + y), (footprint['x1'] + LEAD / 3, vy + y), (vx, vy),
                (vx + d[0] * SHAFT_RUN, vy + d[1] * SHAFT_RUN)]
    d = DIRS[src]
    return [(vx - d[0] * SHAFT_RUN, vy - d[1] * SHAFT_RUN), (vx, vy), (footprint['x0'] - LEAD / 3, vy + y),
            (footprint['x1'] + LEAD, vy + y)]


def corridor_rect(s, hx, hy):
    """Corridor of segment s run on hx / hy past both ends: [l, t, r, b]."""
    return [min(s['x0'], s['x1']) - hx, min(s['y0'], s['y1']) - hy,
            max(s['x0'], s['x1']) + hx, max(s['y0'], s['y1']) + hy]


def inside(rect, x, y, tol=EPS):
    return rect[0] - tol <= x <= rect[2] + tol and rect[1] - tol <= y <= rect[3] + tol


def crosses(line, box, tol=EPS):
    """Does the axis-aligned border line run through the open interior of box?"""
    l, t, r, b = box
    if abs(line['y0'] - line['y1']) < EPS:
        y, lo, hi = line['y0'], min(line['x0'], line['x1']), max(line['x0'], line['x1'])
        return t + tol < y < b - tol and lo < r - EPS and hi > l + EPS
    x, lo, hi = line['x0'], min(line['y0'], line['y1']), max(line['y0'], line['y1'])
    return l + tol < x < r - tol and lo < b - EPS and hi > t + EPS


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
        cls.frames = turn_frames()
        open_page(cls)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_1_course_and_registry(self):
        segs, half = self.course['segments'], self.course['half']
        print('course:', [(s['dir'], round(s['length'], 1)) for s in segs], 'half width', half,
              'shaft half widths', self.course['halves'], 'clearance', self.course['clearance'])
        for join, i in JOINS.items():
            self.assertEqual(f"{segs[i]['dir']}->{segs[i + 1]['dir']}", join)
            self.assertGreaterEqual(segs[i]['length'], 3 * half)
            self.assertGreaterEqual(segs[i + 1]['length'], 3 * half)
        ids = self.page.evaluate('Object.keys(momentumTurnFactories)')
        by_join = self.page.evaluate('momentumTurnsByJoin')
        by_dir = self.page.evaluate('momentumPatternsByDir')
        declared = self.page.evaluate('Object.fromEntries(MOMENTUM_PATTERNS_TURN.map(p => [p.id, p.joins]))')
        want = {f"{f['id']}-turn": f['turnJoins'] for f in self.frames}
        print('catalog turn frames:', want)
        print('registered:', ids)
        print('by join:', by_join)
        self.assertEqual(ids, list(want))
        self.assertEqual(declared, want)
        (EVIDENCE_DIR / 'joins.json').write_text(json.dumps(declared, separators=(',', ':')))
        covered = sorted({j for joins in declared.values() for j in joins})
        print('joins covered:', covered)
        self.assertEqual(covered, sorted(JOINS))
        spawned = sorted({t for t in want for l in list(by_join.values()) + list(by_dir.values()) if t in l})
        print('turn ids in a spawn registry:', spawned)
        self.assertEqual(spawned, [])
        for join in JOINS:
            self.assertEqual(by_join[join], FRAMES_TURN[join])
        for t, joins in want.items():
            for join, i in JOINS.items():
                if join not in joins:
                    r = self.page.evaluate(PLACE, [t, i])
                    print(f"{t} {join}: not declared -> {r}")
                    self.assertIsNone(r)
        for retired in RETIRED + ['no-such-turn', 'bad-frame6-v', 'bad-frame6']:
            r = self.page.evaluate(PLACE, [retired, 0])
            print(f'{retired}: -> {r}')
            self.assertIsNone(r)
        self.assertIsNone(self.page.evaluate("momentumPlacePattern('bad-frame6-turn', 0, 0, 'right')"))

    def test_2_pieces_round_the_corner(self):
        half, clearance = self.course['half'], self.course['clearance']
        segs = self.course['segments']
        summary = {}
        for f in self.frames:
            t = f"{f['id']}-turn"
            for join in f['turnJoins']:
                with self.subTest(id=t, join=join):
                    i = JOINS[join]
                    r = self.page.evaluate(PLACE, [t, i])
                    self.assertIsNotNone(r)
                    self.assertEqual(r['join'], join)
                    vx, vy = segs[i]['x1'], segs[i]['y1']
                    shaft = self.course['halves'][i + 1 if segs[i]['dir'] == 'right' else i]
                    self.assertAlmostEqual(r['shaftHalfWidth'], shaft, delta=EPS)
                    corridor = segs[i] if segs[i]['dir'] == 'right' else segs[i + 1]
                    fp = r['footprint']
                    if join.startswith('right->'):
                        self.assertAlmostEqual(fp['x1'], vx - shaft - clearance, delta=1e-3)
                    else:
                        self.assertAlmostEqual(fp['x0'], vx + shaft + clearance, delta=1e-3)
                    self.assertAlmostEqual(fp['x1'] - fp['x0'], f['span'], delta=1e-3)
                    els = r['elements']
                    self.assertEqual(len(els), len(f['pieces']))
                    lines = [b for b in self.course['borders'] if i - 1 <= b['segment'] <= i + 2]
                    rect = corridor_rect(corridor, 0, half)
                    box_diff = crossings = outside = in_corner = 0
                    gap = float('inf')
                    for p, e in zip(f['pieces'], els):
                        self.assertEqual(e['className'], CLASSES[p['kind']])
                        want = piece_box(p, fp['x0'], vy)
                        got = [e['left'], e['top'], e['right'], e['bottom']]
                        box_diff = max(box_diff, *[abs(g - w) for g, w in zip(got, want)])
                        crossings += sum(crosses(line, got, TOL) for line in lines)
                        outside += not (inside(rect, got[0], got[1], TOL) and inside(rect, got[2], got[3], TOL))
                        # Corner box: the shaft's x range at the vertex
                        in_corner += got[2] > vx - shaft + EPS and got[0] < vx + shaft - EPS
                        gap = min(gap, vx - shaft - got[2] if join.startswith('right->') else got[0] - (vx + shaft))
                    lethal = sum(e['lethal'] for e in els)
                    print(f"{t} {join} (segment {i} vertex {vx:.1f},{vy:.1f} shaft {shaft}): pieces {len(els)}"
                          f" footprint {fp['x0']:.1f}..{fp['x1']:.1f} box diff {box_diff:.3f} lethal {lethal}"
                          f" border lines {len(lines)} crossings {crossings} outside corridor {outside}"
                          f" in corner box {in_corner} gap to corner box {gap:.1f} (clearance {clearance})")
                    self.assertGreaterEqual(len(lines), 6)
                    self.assertLessEqual(box_diff, 1)
                    self.assertEqual(lethal, 0)
                    self.assertEqual(crossings, 0)
                    self.assertEqual(outside, 0)
                    self.assertEqual(in_corner, 0)
                    self.assertGreaterEqual(gap, clearance - 1)
                    summary[f'{t}/{join}'] = {'pieces': len(els), 'boxDiff': round(box_diff, 3), 'lethal': lethal,
                                              'crossings': crossings, 'outside': outside, 'inCorner': in_corner,
                                              'gap': round(gap, 1)}
        (EVIDENCE_DIR / 'turn-geometry.json').write_text(json.dumps(summary, separators=(',', ':')))
        print('wrote turn-geometry.json with', len(summary), 'placements')
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")


class MomentumTurnRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (EVIDENCE_DIR / 'shots').mkdir(parents=True, exist_ok=True)
        cls.frames = turn_frames()
        open_page(cls)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_routes_through_turns(self):
        half = self.course['half']
        segs = self.course['segments']
        view_w, view_h = self.course['view']
        summary = {}
        shots = 0
        for f in self.frames:
            t = f"{f['id']}-turn"
            for join in f['turnJoins']:
                with self.subTest(id=t, join=join):
                    i = JOINS[join]
                    vx, vy = segs[i]['x1'], segs[i]['y1']
                    placed = self.page.evaluate(PLACE, [t, i])
                    points = route(self.course, f, join, placed['footprint'])
                    y, width = lane(f, half, self.course['radius'])
                    r = self.page.evaluate(DRIVE, [t, i, [list(p) for p in points], DRIVE_SPEED, MAX_MOVES])
                    reached = sum(r['legs'])
                    blues = [u['piece'] for u in r['used'] if u['kind'] == 'blue']
                    greens = [u['piece'] for u in r['used'] if u['kind'] == 'green']
                    # The vertex leg went through the corner box
                    corner = min(abs(px - vx) + abs(py - vy) for px, py in r['path'])
                    out = segs[i + 1]
                    along = ((r['end'][0] - vx) * (out['x1'] - out['x0']) +
                             (r['end'][1] - vy) * (out['y1'] - out['y0'])) / out['length']
                    alive = r['sameNinja'] and r['runInProgress'] and r['deaths'] == 0
                    print(f"{t} {join}: lane {y:.1f} (clear {width:.1f}) legs reached {reached}/{len(points) - 1}"
                          f" greens {greens} blues {blues} hp {r['hp0']}->{r['hp']} border touches"
                          f" {r['borderTouches']} deaths {r['deaths']} alive {alive} closest to vertex"
                          f" {corner:.1f} end past vertex {along:.1f} moves {r['moves']}"
                          f" -> {'OK' if alive and reached == len(points) - 1 else 'FAIL'}")
                    summary[f'{t}/{join}'] = {'lane': round(y, 1), 'reached': reached, 'legs': len(points) - 1,
                                              'greens': greens, 'blues': blues, 'hp': [r['hp0'], r['hp']],
                                              'deaths': r['deaths'], 'alive': alive, 'corner': round(corner, 1),
                                              'past': round(along, 1), 'moves': r['moves']}
                    self.assertEqual(r['join'], join)
                    self.assertEqual(r['version'], 'momentum')
                    self.assertTrue(r['runInProgress'])
                    self.assertTrue(r['sameNinja'])
                    self.assertEqual(r['deaths'], 0)
                    self.assertEqual(reached, len(points) - 1)
                    self.assertEqual(blues, [])
                    self.assertEqual(r['hp'], r['hp0'])
                    self.assertLessEqual(corner, 2 * DRIVE_SPEED)
                    self.assertGreater(along, half)
                    # Screenshot: the frame and the corner in view, the shaft side shown
                    fp = placed['footprint']
                    cx = (min(fp['x0'], vx - 400) + max(fp['x1'], vx + 400)) / 2
                    shaft_dir = DIRS[join.split('->')[1] if join.startswith('right->') else join.split('->')[0]]
                    cy = vy + shaft_dir[1] * (view_h / 2 - half - 150)
                    # Ninja drawn at the frame's exit (or entry) on its lane
                    at = points[1] if join.startswith('right->') else points[2]
                    self.page.evaluate(PLACE, [t, i])
                    self.page.evaluate(SHOOT, [cx, cy, r['path'], list(at), i])
                    path = EVIDENCE_DIR / 'shots' / f"turn-{t}-{join.replace('->', '-')}.png"
                    self.page.screenshot(path=str(path))
                    shots += 1
                    print('wrote', path.name, f'view centre {cx:.1f},{cy:.1f} ({view_w}x{view_h} world units)')
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")
        (EVIDENCE_DIR / 'turn-routes.json').write_text(json.dumps(summary, separators=(',', ':')))
        print('wrote turn-routes.json with', len(summary), 'runs,', shots, 'shots')
        self.assertEqual(len(summary), sum(len(f['turnJoins']) for f in self.frames))


if __name__ == '__main__':
    unittest.main()
