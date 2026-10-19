"""Momentum corner frames M18 Kicker (right->up), M60 Lip Kicker
(right->down) (TASK-108), M39 Ramp Exit, M117 Slope Window and M134 Double
Window (down->right, TASK-109), M40 Corner Deflector, M98 Deflect Window and
M136 Deflect Two Windows (up->right, TASK-110) at the course vertex.

elements/momentumpatterns.js MOMENTUM_FRAMES_TURN holds the user's picked
corner frames copied from the TASK-102 catalog (MOMENTUM_FRAMES_CATALOG,
default artifacts/TASK-102/catalog-m.json); MomentumCornerFrameFactory places
a piece at vertex + catalog * (shaft W across x, corridor W across y), the
M60 bar an axis-x sweeper between the shaft wall faces, the M39 and M40
elevators axis-y movers between the exit corridor's faces. momentumPlaceTurn(id,
segmentIndex) hands a corner id to momentumPlaceCorner. Placeable only: no
id is in momentumTurnsByJoin or momentumPatternsByDir.

At 1280x720 and 390x844 (touch, as test_momentum_frames_v) momentum starts on
a course right, up, right, down, right (SCRIPT, as test_momentum_patterns_turn:
right->up after segment 0, up->right after segment 1, right->down after
segment 2, down->right after segment 3), rAF loop stopped,
obstacle floor emptied. Asserts:
- test_1_geometry: per id at its join: piece count = catalog, class per kind,
  nothing lethal, vertex = the segment end, shaftW = 2 x the shaft half
  width, corridorW = 2 x momentumBorders.halfWidth, every box and polygon
  point = vertex + catalog * per-axis W within GEOM_TOL, every box (for the
  movers their whole sweep range) inside the L-shaped interior of the two
  corridors (never in a wall or the inner wall mass) and crossed by no
  border line, the sweeper's bounds = the shaft wall faces and speedX =
  speed x shaft W x momentumMotionScale(1), the elevator's bounds = the
  corridor wall faces and |speedY| = speed x corridor W x
  momentumMotionScale(1), getReach = reach.in x W of the incoming travel
  axis, reach.out x W of the outgoing one; the windows between two blue
  pieces at the same x (measured between the placed blue edges, in corridor
  W): M117 one >= 0.375, M134 two >= 0.5 (the TASK-109 bigger gaps), M98
  one >= 0.5, M136 two >= 0.5 (TASK-110);
- test_2_refused: each id returns null on the three other joins, in classic
  and bad; momentumTurnsByJoin and momentumPatternsByDir hold no corner id
  and momentumPatternsByDir equals the port lists;
- test_4_elevator: the M39 and M40 movers moved 400 cycles: x constant,
  top/bottom never outside the exit corridor faces, reverses at both faces,
  travel >= 0.5 W;
- test_3_shots: per id per viewport a montage: left = the concept PNG, right
  = the game view of the same frame rectangle (only walls and pieces), scaled
  to the same height.

MOMENTUM_FRAMES_TURN_EVIDENCE_DIR (default /tmp/momentum-frames-turn)
receives placed.json (compact {id: {viewport: {vertex, shaftW, corridorW,
reach, pieces}}}), windows.json (compact {id: {viewport: {corridorW,
windows: [{top, bottom, size, sizeInW}]}}}), elevator.json ({id: {viewport:
...}}) and
shots/<id>-<viewport>.png.
Requires Playwright Chromium and Pillow.
"""
import base64
import io
import json
import os
from pathlib import Path
import unittest

from PIL import Image

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_FRAMES_TURN_EVIDENCE_DIR', '/tmp/momentum-frames-turn'))
CATALOG = Path(os.environ.get('MOMENTUM_FRAMES_CATALOG', ROOT / 'artifacts/TASK-102/catalog-m.json'))
CONCEPTS = ROOT / 'artifacts/momentum-frames'
IDS = ['M18', 'M60', 'M39', 'M117', 'M134', 'M40', 'M98', 'M136']
VIEWPORTS = [{'width': 1280, 'height': 720, 'touch': False}, {'width': 390, 'height': 844, 'touch': True}]
# Segments: right, up, right, down, right, all ~5 heights long
SCRIPT = [0.99, 0.99, 0.1, 0.99, 0.99, 0.99, 0.9, 0.99, 0.99]
# Join -> the incoming segment index
JOINS = {'right->up': 0, 'up->right': 1, 'right->down': 2, 'down->right': 3}
GEOM_TOL = 1.0
EPS = 1e-6
FRAME_PX = 480
# Concept frame px of the vertex per join
VERTEX_PX = {'right-up': (457, 457), 'right-down': (457, 315), 'down-right': (315, 457), 'up-right': (315, 315)}
# Window count and smallest window (corridor W) between two blue pieces at the same x
WINDOWS = {'M117': (1, 0.375), 'M134': (2, 0.5), 'M98': (1, 0.5), 'M136': (2, 0.5)}
ELEVATOR_CYCLES = 400
# Elevator id -> its join
ELEVATORS = {'M39': 'down->right', 'M40': 'up->right'}
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}

START = '''() => { startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    return {segments: momentumCourse.take(5), halves: momentumCourse.take(5).map(momentumSegmentHalfWidth),
            half: GAMEPLAY.momentumBorders.halfWidth, borders: momentumBorders(), motionScale: momentumMotionScale(1)} }'''
PLACE = '''([id, segment]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []; floor.groups = []
    const r = momentumPlaceTurn(id, segment)
    if (r) delete r.group
    return r
}'''
# As test_momentum_frames_v: view centred on (cx, cy) zoomed by zoom, the
# camera's wall mask in segment `segment`, ninja parked away, no UI layer
SHOOT = '''([cx, cy, zoom, segment]) => {
    const s0 = scale[version], i0 = screen.segmentIndex, ui = drawUILayer, fps = drawFpsCounterLayer
    scale[version] = s0 * zoom
    screen.segmentIndex = segment
    drawUILayer = drawFpsCounterLayer = () => {}
    try {
        const w = width / scale[version], h = height / scale[version]
        screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
        screen.leftWall.update(screen)
        for (const f of floors)
            if (f instanceof MomentumBorderFloor)
                f.replenishElements()
        ninja.x = cx; ninja.y = cy - 1e5; ninja.speedX = ninja.speedY = 0
        draw()
        return {png: canvas.toDataURL('image/png'), sx: screen.x, sy: screen.y,
                k: scale[version] * canvas.width / width}
    } finally {
        scale[version] = s0; screen.segmentIndex = i0; drawUILayer = ui; drawFpsCounterLayer = fps
    }
}'''
CLEAR = "floors.find(f => f instanceof MomentumPatternFloor).elements = []"


def join_arrow(join):
    return join.replace('-', '->')


def expected(p, vx, vy, Wx, Wy):
    """Catalog piece -> world box [l, t, r, b] and polygon points (None for rects)"""
    cx, cy = vx + p['x'] * Wx, vy + p['y'] * Wy
    if p['shape'] == 'rect':
        return [cx - p['w'] / 2 * Wx, cy - p['h'] / 2 * Wy, cx + p['w'] / 2 * Wx, cy + p['h'] / 2 * Wy], None
    pts = [(cx + px * Wx, cy + py * Wy) for px, py in p['points']]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    return [min(xs), min(ys), max(xs), max(ys)], pts


def shaft_index(join, i):
    """Index of the join's vertical segment (i = the incoming one)"""
    return i + 1 if join.startswith('right') else i


def l_interior(join, vx, vy, sh, ch):
    """The two corridor rects meeting at the vertex: the right corridor (up
    to the outer shaft wall) and the shaft (up to the outer floor/ceiling)"""
    if join.startswith('right'):
        corridor = [-1e9, vy - ch, vx + sh, vy + ch]
    else:
        corridor = [vx - sh, vy - ch, 1e9, vy + ch]
    shaft = [vx - sh, -1e9, vx + sh, vy + ch] if join in ('right->up', 'down->right') else [vx - sh, vy - ch, vx + sh, 1e9]
    return corridor, shaft


def windows(elements, Wy):
    """Gaps between vertically consecutive still blue pieces sharing a left edge"""
    columns = {}
    for e in elements:
        if e['className'] == 'MomentumBlue' and not e.get('motion'):
            columns.setdefault(round(e['left'], 3), []).append(e)
    out = []
    for x in sorted(columns):
        column = sorted(columns[x], key=lambda e: e['top'])
        for a, b in zip(column, column[1:]):
            size = b['top'] - a['bottom']
            out.append({'x': round(x, 2), 'top': round(a['bottom'], 2), 'bottom': round(b['top'], 2),
                        'size': round(size, 2), 'sizeInW': round(size / Wy, 6)})
    return out


def box_in(rect, b, tol=EPS):
    return rect[0] - tol <= b[0] and rect[1] - tol <= b[1] and b[2] <= rect[2] + tol and b[3] <= rect[3] + tol


def crosses(line, box, tol=EPS):
    """Does the axis-aligned border line run through the open interior of box?"""
    l, t, r, b = box
    if abs(line['y0'] - line['y1']) < EPS:
        y, lo, hi = line['y0'], min(line['x0'], line['x1']), max(line['x0'], line['x1'])
        return t + tol < y < b - tol and lo < r - EPS and hi > l + EPS
    x, lo, hi = line['x0'], min(line['y0'], line['y1']), max(line['y0'], line['y1'])
    return l + tol < x < r - tol and lo < b - EPS and hi > t + EPS


class MomentumFramesTurnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (EVIDENCE_DIR / 'shots').mkdir(parents=True, exist_ok=True)
        cls.catalog = {e['id']: e for e in json.loads(CATALOG.read_text())['frames'] if e['id'] in IDS}
        concept = json.loads((CONCEPTS / 'catalog.json').read_text())
        cls.concept = {f['id']: f for f in concept['frames'] if f['id'] in IDS}
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.pages = []
        cls.errors = []
        for vp in VIEWPORTS:
            context = cls.browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                              is_mobile=vp['touch'], has_touch=vp['touch'])
            cls.addClassCleanup(context.close)
            page = context.new_page()
            page.on('pageerror', lambda e: cls.errors.append(str(e)))
            page.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
            page.goto(cls.url + ('?input=touch' if vp['touch'] else ''))
            wait_for_boot_run(page)
            page.evaluate(SEED_COURSE, SCRIPT)
            course = page.evaluate(START)
            segs = course['segments']
            for join, i in JOINS.items():
                assert f"{segs[i]['dir']}->{segs[i + 1]['dir']}" == join, (vp, join)
            cls.pages.append((f"{vp['width']}x{vp['height']}", page, course))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_1_geometry(self):
        self.assertEqual(sorted(self.catalog), sorted(IDS))
        placed, gaps = {}, {}
        for name, page, course in self.pages:
            segs, halves, half = course['segments'], course['halves'], course['half']
            for id in IDS:
                entry = self.catalog[id]
                join = join_arrow(entry['join'])
                i = JOINS[join]
                r = page.evaluate(PLACE, [id, i])
                self.assertIsNotNone(r, (name, id))
                self.assertEqual(r['join'], join)
                vx, vy = segs[i]['x1'], segs[i]['y1']
                sh = halves[shaft_index(join, i)]
                Wx, Wy = 2 * sh, 2 * half
                self.assertAlmostEqual(r['vertex']['x'], vx, delta=EPS)
                self.assertAlmostEqual(r['vertex']['y'], vy, delta=EPS)
                self.assertAlmostEqual(r['shaftW'], Wx, delta=EPS)
                self.assertAlmostEqual(r['corridorW'], Wy, delta=EPS)
                # Reach: right corridor runs along x (shaft W), the shaft along y (corridor W)
                incoming, outgoing = join.split('->')
                self.assertAlmostEqual(r['reach']['in'], entry['reach']['in'] * (Wx if incoming == 'right' else Wy),
                                       delta=EPS)
                self.assertAlmostEqual(r['reach']['out'], entry['reach']['out'] * (Wx if outgoing == 'right' else Wy),
                                       delta=EPS)
                self.assertEqual(len(r['elements']), len(entry['pieces']), (name, id))
                corridor, shaft = l_interior(join, vx, vy, sh, half)
                lines = [b for b in course['borders'] if i - 1 <= b['segment'] <= i + 2]
                rows, diff = [], 0.0
                for k, (e, p) in enumerate(zip(r['elements'], entry['pieces'])):
                    msg = (name, id, k)
                    self.assertEqual(e['className'], CLASSES[p['kind']], msg)
                    self.assertFalse(e['lethal'], msg)
                    want, pts = expected(p, vx, vy, Wx, Wy)
                    got = [e['left'], e['top'], e['right'], e['bottom']]
                    for a, b in zip(got, want):
                        self.assertAlmostEqual(a, b, delta=GEOM_TOL, msg=msg)
                        diff = max(diff, abs(a - b))
                    if pts:
                        self.assertEqual(len(e['points']), len(pts), msg)
                        for q in pts:
                            near = min(abs(q[0] - g[0]) + abs(q[1] - g[1]) for g in e['points'])
                            self.assertLessEqual(near, GEOM_TOL, msg)
                            diff = max(diff, near)
                    sweep = got
                    if 'motion' in p and p['motion']['axis'] == 'y':
                        mo = e['motion']
                        self.assertEqual(mo['axis'], 'y', msg)
                        self.assertAlmostEqual(mo['yMin'], vy + p['motion']['min'] * Wy, delta=EPS, msg=msg)
                        self.assertAlmostEqual(mo['yMax'], vy + p['motion']['max'] * Wy, delta=EPS, msg=msg)
                        self.assertAlmostEqual(mo['yMin'], vy - half, delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(mo['yMax'], vy + half, delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(abs(mo['speedY']), p['motion']['speed'] * Wy * course['motionScale'],
                                               delta=EPS, msg=msg)
                        sweep = [got[0], mo['yMin'], got[2], mo['yMax']]
                    elif 'motion' in p:
                        mo = e['motion']
                        self.assertEqual(mo['axis'], 'x', msg)
                        self.assertAlmostEqual(mo['xMin'], vx + p['motion']['min'] * Wx, delta=EPS, msg=msg)
                        self.assertAlmostEqual(mo['xMax'], vx + p['motion']['max'] * Wx, delta=EPS, msg=msg)
                        self.assertAlmostEqual(mo['xMin'], vx - sh, delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(mo['xMax'], vx + sh, delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(mo['speedX'], p['motion']['speed'] * Wx * course['motionScale'],
                                               delta=EPS, msg=msg)
                        sweep = [mo['xMin'], got[1], mo['xMax'], got[3]]
                    else:
                        self.assertIsNone(e.get('motion'), msg)
                    inside = box_in(corridor, sweep, GEOM_TOL) or box_in(shaft, sweep, GEOM_TOL)
                    self.assertTrue(inside, (msg, sweep, corridor, shaft))
                    crossing = [b for b in lines if crosses(b, sweep, GEOM_TOL)]
                    self.assertEqual(crossing, [], msg)
                    rel = [round(got[0] - vx, 2), round(got[1] - vy, 2), round(got[2] - vx, 2), round(got[3] - vy, 2)]
                    row = {'kind': p['kind'], 'box': rel}
                    if pts:
                        row['points'] = [[round(x - vx, 2), round(y - vy, 2)] for x, y in e['points']]
                    if 'motion' in p and p['motion']['axis'] == 'y':
                        row['motion'] = {'yMin': round(e['motion']['yMin'] - vy, 2),
                                         'yMax': round(e['motion']['yMax'] - vy, 2),
                                         'speedY': round(e['motion']['speedY'], 4)}
                    elif 'motion' in p:
                        row['motion'] = {'xMin': round(e['motion']['xMin'] - vx, 2),
                                         'xMax': round(e['motion']['xMax'] - vx, 2),
                                         'speedX': round(e['motion']['speedX'], 4)}
                    rows.append(row)
                if id in WINDOWS:
                    count, least = WINDOWS[id]
                    found = windows(r['elements'], Wy)
                    self.assertEqual(len(found), count, (name, id, found))
                    for w in found:
                        self.assertGreaterEqual(w['sizeInW'], least - EPS, (name, id, w))
                        self.assertGreaterEqual(w['top'], vy - half - GEOM_TOL, (name, id, w))
                        self.assertLessEqual(w['bottom'], vy + half + GEOM_TOL, (name, id, w))
                    gaps.setdefault(id, {})[name] = {'corridorW': round(Wy, 3), 'windows': [
                        {k: w[k] for k in ('top', 'bottom', 'size', 'sizeInW')} for w in found]}
                    print(f"{name} {id} windows (corridor W {Wy:.2f}): "
                          f"{[(w['size'], w['sizeInW']) for w in found]} >= {least} W OK")
                placed.setdefault(id, {})[name] = {
                    'join': join, 'vertex': [round(vx, 2), round(vy, 2)], 'shaftW': round(Wx, 3),
                    'corridorW': round(Wy, 3), 'reach': {k: round(v, 3) for k, v in r['reach'].items()},
                    'pieces': rows}
                print(f"{name} {id} {join} (segment {i}) vertex ({vx:.1f},{vy:.1f}) shaft W {Wx:.2f} corridor W "
                      f"{Wy:.2f} reach in {r['reach']['in']:.2f} out {r['reach']['out']:.2f} pieces "
                      f"{[e['className'][8:] for e in r['elements']]} max diff {diff:.4f}, inside L, no wall OK")
            page.evaluate(CLEAR)
        (EVIDENCE_DIR / 'placed.json').write_text(json.dumps(placed, separators=(',', ':')))
        self.assertEqual(sorted(gaps), sorted(WINDOWS))
        (EVIDENCE_DIR / 'windows.json').write_text(json.dumps(gaps, separators=(',', ':')))

    def test_2_refused(self):
        for name, page, course in self.pages:
            r = page.evaluate('''([ids, joins]) => {
                const out = {}
                for (const id of ids)
                    out[id] = Object.fromEntries(Object.entries(joins).map(([j, i]) => [j, momentumPlaceTurn(id, i) !== null]))
                floors.find(f => f instanceof MomentumPatternFloor).elements = []
                return {placed: out, byJoin: momentumTurnsByJoin, byDir: momentumPatternsByDir,
                        ports: {right: MOMENTUM_PATTERNS_PORT_H.map(p => p.id),
                                up: MOMENTUM_PATTERNS_PORT_V.filter(p => p.dirs.includes('up')).map(p => p.id),
                                down: MOMENTUM_PATTERNS_PORT_V.filter(p => p.dirs.includes('down')).map(p => p.id)},
                        corner: Object.keys(momentumCornerFrameFactories)} }''', [IDS, JOINS])
            print(name, 'placed per join', r['placed'], 'corner factories', r['corner'])
            for id in IDS:
                own = join_arrow(self.catalog[id]['join'])
                self.assertEqual(r['placed'][id], {j: j == own for j in JOINS}, (name, id))
            self.assertEqual(r['corner'], IDS)
            for j, ids in r['byJoin'].items():
                self.assertEqual([i for i in ids if i in IDS], [], j)
            self.assertEqual(r['byDir'], r['ports'])
            print(name, 'momentumPatternsByDir = port lists', {d: len(l) for d, l in r['byDir'].items()},
                  'momentumTurnsByJoin', r['byJoin'])
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE, SCRIPT)
        r = page.evaluate('''(ids) => {
            const out = {}
            for (const mode of ['classic', 'bad']) {
                startGame(mode); cancelAnimationFrame(game)
                out[mode] = ids.filter(id => momentumPlaceTurn(id, 0) !== null || momentumPlaceTurn(id, 2) !== null)
            }
            return out }''', IDS)
        print('classic/bad placed', r)
        self.assertEqual(r, {'classic': [], 'bad': []})

    def test_3_shots(self):
        n = 0
        for name, page, course in self.pages:
            for id in IDS:
                entry, source = self.catalog[id], self.concept[id]
                join = join_arrow(entry['join'])
                i = JOINS[join]
                self.assertIsNotNone(page.evaluate(PLACE, [id, i]))
                vx, vy = course['segments'][i]['x1'], course['segments'][i]['y1']
                Wx, Wy = 2 * course['halves'][shaft_index(join, i)], 2 * course['half']
                concept = Image.open(CONCEPTS / source['png']).convert('RGB')
                cw, ch = concept.size
                px, py = VERTEX_PX[entry['join']]
                wl, wr = vx - px / FRAME_PX * Wx, vx + (cw - px) / FRAME_PX * Wx
                wt, wb = vy - py / FRAME_PX * Wy, vy + (ch - py) / FRAME_PX * Wy
                view = page.evaluate('[width / scale[version], height / scale[version]]')
                zoom = min(view[0] / (wr - wl), view[1] / (wb - wt)) * 0.98
                m = page.evaluate(SHOOT, [(wl + wr) / 2, (wt + wb) / 2, zoom, i])
                shot = Image.open(io.BytesIO(base64.b64decode(m['png'].split(',', 1)[1]))).convert('RGB')
                box = [round((wl + m['sx']) * m['k']), round((wt + m['sy']) * m['k']),
                       round((wr + m['sx']) * m['k']), round((wb + m['sy']) * m['k'])]
                self.assertGreaterEqual(min(box), 0, box)
                self.assertLessEqual(box[2], shot.size[0], box)
                self.assertLessEqual(box[3], shot.size[1], box)
                game = shot.crop(box).resize((round((box[2] - box[0]) * ch / (box[3] - box[1])), ch), Image.LANCZOS)
                montage = Image.new('RGB', (cw + 8 + game.size[0], ch), (255, 255, 255))
                montage.paste(concept, (0, 0))
                montage.paste(game, (cw + 8, 0))
                path = EVIDENCE_DIR / 'shots' / f'{id}-{name}.png'
                montage.save(path)
                print(f'{path.name}: shaft W {Wx:.2f} corridor W {Wy:.2f} crop {box} of {shot.size}, zoom {zoom:.3f}')
                n += 1
            page.evaluate(CLEAR)
        self.assertEqual(n, len(IDS) * len(VIEWPORTS))

    def test_4_elevator(self):
        out = {}
        for (id, join), (name, page, course) in ((x, y) for x in ELEVATORS.items() for y in self.pages):
            i = JOINS[join]
            self.assertIsNotNone(page.evaluate(PLACE, [id, i]))
            r = page.evaluate('''(cycles) => {
                const floor = floors.find(f => f instanceof MomentumPatternFloor)
                const e = floor.elements.find(e => e.motion)
                const b0 = getElementBounds(e), step = Math.abs(e.speedY)
                let top = b0.top, bottom = b0.bottom, flips = 0, sign = Math.sign(e.speedY)
                const xs = new Set()
                for (let k = 0; k < cycles; k++) {
                    e.move()
                    const b = getElementBounds(e)
                    top = Math.min(top, b.top); bottom = Math.max(bottom, b.bottom)
                    xs.add(b.left.toFixed(6) + ',' + b.right.toFixed(6))
                    if (Math.sign(e.speedY) != sign) { flips++; sign = Math.sign(e.speedY) }
                }
                floor.elements = []
                return {top: top, bottom: bottom, x0: b0.left.toFixed(6) + ',' + b0.right.toFixed(6), xs: [...xs],
                        flips: flips, step: step, h: b0.bottom - b0.top} }''', ELEVATOR_CYCLES)
            vy, half = course['segments'][i]['y1'], course['half']
            msg = (id, name, r)
            self.assertEqual(r['xs'], [r['x0']], msg)
            self.assertGreaterEqual(r['top'], vy - half - GEOM_TOL, msg)
            self.assertLessEqual(r['bottom'], vy + half + GEOM_TOL, msg)
            self.assertGreaterEqual(r['flips'], 2, msg)
            # Reversals at both faces: the sweep comes within one step of each
            self.assertLessEqual(r['top'] - (vy - half), r['step'] + GEOM_TOL, msg)
            self.assertLessEqual((vy + half) - r['bottom'], r['step'] + GEOM_TOL, msg)
            travel = (r['bottom'] - r['top'] - r['h']) / (2 * half)
            self.assertGreaterEqual(travel, 0.5, msg)
            out.setdefault(id, {})[name] = {'cycles': ELEVATOR_CYCLES, 'corridor': [round(vy - half, 2), round(vy + half, 2)],
                         'sweep': [round(r['top'], 2), round(r['bottom'], 2)], 'flips': r['flips'],
                         'step': round(r['step'], 4), 'xConstant': True, 'travelInW': round(travel, 4)}
            print(f"{name} {id} elevator {ELEVATOR_CYCLES} cycles: sweep {r['top']:.1f}..{r['bottom']:.1f} inside "
                  f"corridor {vy - half:.1f}..{vy + half:.1f}, {r['flips']} reversals, x constant, travel "
                  f"{travel:.3f} W OK")
        (EVIDENCE_DIR / 'elevator.json').write_text(json.dumps(out, separators=(',', ':')))


if __name__ == '__main__':
    unittest.main()
