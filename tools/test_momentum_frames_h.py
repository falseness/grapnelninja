"""Momentum concept frames M04, M23, M24, M46, M47, M66 in the right corridor
(TASK-104, TASK-105).

elements/momentumpatterns.js MOMENTUM_FRAMES_H holds the user's picked
right-corridor concept frames copied from the TASK-102 catalog
(MOMENTUM_FRAMES_CATALOG, default tools/data/momentum-catalog-m.json), every
size in W = the corridor's interior width; MomentumFrameFactory places them
scaled by the live W. They are placeable (momentumPlacePattern) and, since
TASK-111, the only right-corridor frames spawned: momentumPatternsByDir.right
= these ids (the ported bad frames stay placeable, not spawned).

At 1280x720 and at 390x844 (touch) momentum starts on a course whose first
right segment is long (SCRIPT, as test_momentum_patterns_h), the rAF loop
stopped and the obstacle floor emptied; each frame is placed alone. Asserts:
- test_1_geometry: placed piece count = catalog count, class per kind, every
  rect box and polygon vertex = catalog * live W within GEOM_TOL world units,
  motion bounds (y + min/max * W) and speedY (-speed * W *
  momentumMotionScale(1)) match, every piece (and motion range) inside the
  corridor band, nothing lethal;
- test_2_refused: momentumPlacePattern returns null for these ids in an up
  and a down segment and in classic/bad; momentumPatternsByDir.right is
  exactly these ids (TASK-111), up/down hold none of them and no
  MOMENTUM_PATTERNS_PORT_H id is in any direction list;
- test_3_shots: per id per viewport a montage: left = the concept PNG
  (artifacts/momentum-frames/png), right = the frame placed in the game, the
  view cropped to the concept's frame rectangle and scaled to its height
  (only the game's walls and pieces: ninja parked away, no overlay);
- test_4_cap: M46 and M66 (a thin green cap lying on a blue block): the cap's
  bottom edge touches the blue's top (gap and overlap <= CAP_TOL); a ninja
  dropped straight down (vx 0, vy > 0) onto the cap centre from 0.2 W above
  its top bounces (vy < 0 after), the cap is used, the blue is not, hp is
  unchanged and momentumState.greenStreak + 1;
- test_5_fit (TASK-129, corridor 1.0 height since TASK-128): per frame per
  viewport, rasterized at FIT_STEP world units with every moving piece at
  its top and at its bottom bound: the widest path from the entry column
  (FIT_MARGIN_W before the footprint) to the exit column (as far past it)
  is >= FIT_MIN_RATIO x the ninja diameter (bottleneck of the distance
  transform, the corridor faces count as obstacles); every piece is a
  grapnel target hit first by a straight throw from some free entry-column
  point; every piece and motion range stays inside the corridor faces.

MOMENTUM_FRAMES_H_EVIDENCE_DIR (default /tmp/momentum-frames-h) receives
placed.json (compact {id: {viewport: {W, pieces: [{kind, box|points,
motion}]}}}), cap-test.json (compact {id: {viewport: {vyBefore, vyAfter,
greenUsed, blueUsed, hpBefore, hpAfter, streakBefore, streakAfter, moves}}})
shots/<id>-<viewport>.png and frames-fit.json (compact [{id, status, fix,
reason, viewport: {minGapOverDiameter, reachable, targets}}], TASK-129).
Requires Playwright Chromium and Pillow.
"""
import base64
import io
import json
import os
from pathlib import Path
import unittest

import numpy as np
from PIL import Image
from scipy import ndimage

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_FRAMES_H_EVIDENCE_DIR', '/tmp/momentum-frames-h'))
CATALOG = Path(os.environ.get('MOMENTUM_FRAMES_CATALOG', ROOT / 'tools/data/momentum-catalog-m.json'))
CONCEPTS = ROOT / 'artifacts/momentum-frames'
IDS = ['M04', 'M23', 'M24', 'M46', 'M47', 'M66']
# Frames with a green cap on a blue block: catalog piece index of the blue and the cap
CAPS = {'M46': (1, 2), 'M66': (1, 2)}
CAP_TOL = 1.0
# Drop: height above the cap top in W, start vy (world units per move), move budget
DROP_W = 0.2
DROP_VY = 1.25
DROP_MOVES = 3000
VIEWPORTS = [{'width': 1280, 'height': 720, 'touch': False}, {'width': 390, 'height': 844, 'touch': True}]
SCRIPT = [0.99]
GEOM_TOL = 1.0
# Footprint start: this many corridor half widths into segment 0
ORIGIN_HALF_WIDTHS = 1.5
EPS = 1e-6
# Concept frame: 1 W = 480 frame px, corridor centre line at frame y 315,
# along anchor = smallest piece x - 48
FRAME_PX = 480
CENTRE_PY = 315
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}
# test_5_fit: raster step (world units), entry/exit columns this many W
# outside the footprint, smallest path width over the ninja diameter
FIT_STEP = 2.0
FIT_MARGIN_W = 0.15
FIT_MIN_RATIO = 1.2

START = '''() => { startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    return {half: GAMEPLAY.momentumBorders.halfWidth, segment: momentumCourse.segment(0),
            motionScale: momentumMotionScale(1)} }'''
PLACE = '''([id, x, y, dir]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []; floor.groups = []
    return momentumPlacePattern(id, x, y, dir)
}'''
# View zoomed by zoom (< 1 zooms out) and centred on (cx, cy), ninja parked
# far away, drawn without the UI layer (score, hearts, menu button, fps);
# returns the canvas PNG (the stage is drawn landscape even where the window
# is portrait and the stage turned) and the world -> canvas px mapping
SHOOT = '''([cx, cy, zoom]) => {
    const s0 = scale[version], ui = drawUILayer, fps = drawFpsCounterLayer
    scale[version] = s0 * zoom
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
    } finally { scale[version] = s0; drawUILayer = ui; drawFpsCounterLayer = fps }
}'''

# Places id and drops the ninja straight down onto the cap centre from drop
# above its top, moving only the ninja (ninja.move(), gravity on), until the
# vertical speed turns up or a piece is used
DROP = '''([id, x, y, bi, ci, drop, vy, maxMoves]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []; floor.groups = []
    momentumPlacePattern(id, x, y, 'right')
    const blue = floor.elements[bi], cap = floor.elements[ci]
    const bb = getElementBounds(blue), cb = getElementBounds(cap)
    momentumState.reset()
    const hpBefore = momentumState.hp, streakBefore = momentumState.greenStreak
    ninja.x = (cb.left + cb.right) / 2
    ninja.y = cb.top - drop
    ninja.speedX = 0; ninja.speedY = vy
    const start = {startY: ninja.y, vxBefore: ninja.speedX, vyBefore: ninja.speedY}
    let moves = 0
    while (moves < maxMoves && ninja.speedY >= 0 && !cap.passThrough && !blue.passThrough) {
        ninja.move(); ++moves
    }
    // a few more moves: the bounce must not carry it into the blue
    for (let k = 0; k < 20 && ninja.speedY < 0; ++k) ninja.move()
    return {...start, moves, vyAfter: ninja.speedY, greenUsed: cap.passThrough, blueUsed: blue.passThrough,
            hpBefore, hpAfter: momentumState.hp, streakBefore, streakAfter: momentumState.greenStreak,
            capClass: cap.constructor.name, blueClass: blue.constructor.name,
            cap: [cb.left, cb.top, cb.right, cb.bottom].map(v => +v.toFixed(3)),
            blue: [bb.left, bb.top, bb.right, bb.bottom].map(v => +v.toFixed(3))}
}'''


def expected_pieces(entry, x0, y0, W):
    """Catalog pieces in world units: kind, box, points, motion bounds"""
    out = []
    for p in entry['pieces']:
        e = {'kind': p['kind']}
        if p['shape'] == 'rect':
            e['box'] = [x0 + (p['x'] - p['w'] / 2) * W, y0 + (p['y'] - p['h'] / 2) * W,
                        x0 + (p['x'] + p['w'] / 2) * W, y0 + (p['y'] + p['h'] / 2) * W]
        else:
            e['points'] = [[x0 + (p['x'] + px) * W, y0 + (p['y'] + py) * W] for px, py in p['points']]
            xs, ys = [q[0] for q in e['points']], [q[1] for q in e['points']]
            e['box'] = [min(xs), min(ys), max(xs), max(ys)]
        if 'motion' in p:
            m = p['motion']
            e['motion'] = {'axis': m['axis'], 'min': y0 + m['min'] * W, 'max': y0 + m['max'] * W, 'speed': m['speed'] * W}
        out.append(e)
    return out


def anchor_x(frame):
    """Concept frame px of the footprint start (smallest piece x - 48)"""
    xs = [p['x'] if p['shape'] == 'rect' else min(q[0] for q in p['points']) for p in frame['pieces']]
    return min(xs) - 48


def rasterize(polys, xs, ys):
    """Piece index + 1 per cell (0 = free) of polygons [[x, y], ...] on the grid xs x ys"""
    X, Y = np.meshgrid(xs, ys)
    owner = np.zeros(X.shape, dtype=np.int16)
    for k, pts in enumerate(polys):
        inside = np.zeros(X.shape, dtype=bool)
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            if ay == by:
                continue
            crosses = (ay > Y) != (by > Y)
            xc = ax + (Y - ay) * (bx - ax) / (by - ay)
            inside ^= crosses & (X < xc)
        owner[inside & (owner == 0)] = k + 1
    return owner


def frame_fit(elements, x0, y0, W, span, radius):
    """Path width / ninja diameter, reachable targets, inside the faces, per
    moving-piece position (all at the top bound, all at the bottom bound)"""
    top, bottom = y0 - W / 2, y0 + W / 2
    inside = all(top - GEOM_TOL <= p[1] <= bottom + GEOM_TOL for e in elements for p in e['points']) and \
        all(top - GEOM_TOL <= e['motion'][b] <= bottom + GEOM_TOL for e in elements if e['motion'] for b in ('yMin', 'yMax'))
    xs = np.arange(x0 - FIT_MARGIN_W * W, x0 + (span + FIT_MARGIN_W) * W + FIT_STEP / 2, FIT_STEP)
    ys = np.arange(top + FIT_STEP / 2, bottom, FIT_STEP)
    out = []
    for at in ('yMin', 'yMax'):
        polys = []
        for e in elements:
            pts = [list(p) for p in e['points']]
            if e['motion']:
                dy = e['motion'][at] - (e['top'] if at == 'yMin' else e['bottom'])
                pts = [[px, py + dy] for px, py in pts]
            polys.append(pts)
        owner = rasterize(polys, xs, ys)
        # Faces just outside the first and last rows
        free = np.pad(owner == 0, ((1, 1), (0, 0)), constant_values=False)
        clearance = ndimage.distance_transform_edt(free)[1:-1] * FIT_STEP
        lo, hi = 0.0, float(clearance.max())
        for _ in range(40):
            mid = (lo + hi) / 2
            labels, _n = ndimage.label(clearance >= mid)
            if set(labels[:, 0][labels[:, 0] > 0]) & set(labels[:, -1][labels[:, -1] > 0]):
                lo = mid
            else:
                hi = mid
        # Grapnel: the first piece a straight throw from a free entry point meets
        reached = set()
        for sy in np.flatnonzero(owner[:, 0] == 0)[::10]:
            sx = xs[0]
            for k, pts in enumerate(polys):
                if k + 1 in reached:
                    continue
                for tx, ty in pts + [[(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] for a, b in zip(pts, pts[1:] + pts[:1])]:
                    n = int(np.hypot(tx - sx, ty - ys[sy]) / FIT_STEP) + 2
                    ix = np.clip(np.round((np.linspace(sx, tx, n) - xs[0]) / FIT_STEP).astype(int), 0, len(xs) - 1)
                    iy = np.clip(np.round((np.linspace(ys[sy], ty, n) - ys[0]) / FIT_STEP).astype(int), 0, len(ys) - 1)
                    hit = owner[iy, ix]
                    hit = hit[hit > 0]
                    if len(hit) and hit[0] == k + 1:
                        reached.add(k + 1)
                        break
        out.append({'gap': 2 * lo, 'reached': sorted(reached)})
    best = max(out, key=lambda r: r['gap'])
    reached = sorted(set().union(*[r['reached'] for r in out]))
    return {'minGapOverDiameter': round(best['gap'] / (2 * radius), 3), 'gap': round(best['gap'], 1),
            'gapAtBounds': [round(r['gap'], 1) for r in out], 'reachable': len(reached),
            'targets': len(elements), 'insideFaces': inside}


class MomentumFramesHTests(unittest.TestCase):
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
            info = page.evaluate(START)
            assert info['segment']['dir'] == 'right', info
            cls.pages.append((f"{vp['width']}x{vp['height']}", page, info))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def origin(self, info):
        s = info['segment']
        return s['x0'] + ORIGIN_HALF_WIDTHS * info['half'], s['y0']

    def test_1_geometry(self):
        self.assertEqual(sorted(self.catalog), IDS)
        placed = {}
        for name, page, info in self.pages:
            W = 2 * info['half']
            x0, y0 = self.origin(info)
            for id in IDS:
                entry = self.catalog[id]
                r = page.evaluate(PLACE, [id, x0, y0, 'right'])
                self.assertIsNotNone(r, (name, id))
                self.assertAlmostEqual(r['length'], entry['span'] * W, delta=EPS)
                want = expected_pieces(entry, x0, y0, W)
                self.assertEqual(len(r['elements']), len(entry['pieces']), (name, id))
                rows = []
                for k, (e, w) in enumerate(zip(r['elements'], want)):
                    msg = (name, id, k)
                    self.assertEqual(e['className'], CLASSES[w['kind']], msg)
                    self.assertFalse(e['lethal'], msg)
                    box = [e['left'], e['top'], e['right'], e['bottom']]
                    for a, b in zip(box, w['box']):
                        self.assertAlmostEqual(a, b, delta=GEOM_TOL, msg=msg)
                    if 'points' in w:
                        self.assertEqual(len(e['points']), len(w['points']), msg)
                        for p, q in zip(e['points'], w['points']):
                            self.assertAlmostEqual(p[0], q[0], delta=GEOM_TOL, msg=msg)
                            self.assertAlmostEqual(p[1], q[1], delta=GEOM_TOL, msg=msg)
                    if 'motion' in w:
                        m = w['motion']
                        self.assertIsNotNone(e['motion'], msg)
                        self.assertAlmostEqual(e['motion']['yMin'], m['min'], delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(e['motion']['yMax'], m['max'], delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(abs(e['speedY']), m['speed'] * info['motionScale'], delta=1e-9, msg=msg)
                        lo, hi = m['min'], m['max']
                    else:
                        self.assertIsNone(e['motion'], msg)
                        self.assertEqual(e['speedY'], 0, msg)
                        lo, hi = box[1], box[3]
                    # Inside the corridor band (and the motion range too)
                    self.assertGreaterEqual(min(box[1], lo), y0 - W / 2 - GEOM_TOL, msg)
                    self.assertLessEqual(max(box[3], hi), y0 + W / 2 + GEOM_TOL, msg)
                    self.assertGreaterEqual(box[0], x0 - GEOM_TOL, msg)
                    self.assertLessEqual(box[2], x0 + entry['span'] * W + GEOM_TOL, msg)
                    row = {'kind': w['kind']}
                    if e['points'] and 'points' in w:
                        row['points'] = [[round(p[0] - x0, 2), round(p[1] - y0, 2)] for p in e['points']]
                    else:
                        row['box'] = [round(box[0] - x0, 2), round(box[1] - y0, 2), round(box[2] - x0, 2), round(box[3] - y0, 2)]
                    if e['motion']:
                        row['motion'] = {'yMin': round(e['motion']['yMin'] - y0, 2), 'yMax': round(e['motion']['yMax'] - y0, 2),
                                         'speedY': round(e['speedY'], 4)}
                    rows.append(row)
                placed.setdefault(id, {})[name] = {'W': W, 'pieces': rows}
                print(f"{name} {id}: W {W} span {r['length']:.2f} pieces {len(rows)} "
                      f"{[e['className'] for e in r['elements']]} OK")
            page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")
        (EVIDENCE_DIR / 'placed.json').write_text(json.dumps(placed, separators=(',', ':')))

    def test_2_refused(self):
        for name, page, info in self.pages:
            r = page.evaluate('''(ids) => {
                const out = {up: ids.filter(id => momentumPlacePattern(id, 0, 0, 'up') !== null),
                             down: ids.filter(id => momentumPlacePattern(id, 0, 0, 'down') !== null),
                             registered: ids.filter(id => id in momentumPatternFactories),
                             byDir: Object.fromEntries(Object.entries(momentumPatternsByDir).map(([d, l]) => [d, l.slice()])),
                             port: MOMENTUM_PATTERNS_PORT_H.map(p => p.id)}
                floors.find(f => f instanceof MomentumPatternFloor).elements = []
                return out }''', IDS)
            print(name, 'placed up', r['up'], 'down', r['down'], 'registered', r['registered'],
                  'byDir.right', r['byDir']['right'])
            self.assertEqual(r['up'], [])
            self.assertEqual(r['down'], [])
            self.assertEqual(r['registered'], IDS)
            self.assertEqual(r['byDir']['right'], IDS)
            for d, ids in r['byDir'].items():
                self.assertEqual([i for i in ids if i in r['port']], [], d)
                if d != 'right':
                    self.assertEqual([i for i in ids if i in IDS], [], d)
        # Classic and bad: no pattern floor
        name, page, info = self.pages[0]
        r = page.evaluate('''(ids) => {
            const out = {}
            for (const mode of ['classic', 'bad']) {
                startGame(mode); cancelAnimationFrame(game)
                out[mode] = ids.filter(id => momentumPlacePattern(id, 0, 0, 'right') !== null)
            }
            return out }''', IDS)
        print('classic/bad placed', r)
        self.assertEqual(r, {'classic': [], 'bad': []})
        page.evaluate(SEED_COURSE, SCRIPT)
        page.evaluate(START)

    def test_3_shots(self):
        for name, page, info in self.pages:
            W = 2 * info['half']
            x0, y0 = self.origin(info)
            for id in IDS:
                concept = Image.open(CONCEPTS / self.concept[id]['png']).convert('RGB')
                cw, ch = concept.size
                ax = anchor_x(self.concept[id])
                # World rectangle of the concept image (frame px 0..cw, 0..ch)
                wl, wr = x0 + (0 - ax) / FRAME_PX * W, x0 + (cw - ax) / FRAME_PX * W
                wt, wb = y0 + (0 - CENTRE_PY) / FRAME_PX * W, y0 + (ch - CENTRE_PY) / FRAME_PX * W
                self.assertIsNotNone(page.evaluate(PLACE, [id, x0, y0, 'right']))
                view = page.evaluate('[width / scale[version], height / scale[version]]')
                zoom = min(view[0] / (wr - wl), view[1] / (wb - wt)) * 0.98
                m = page.evaluate(SHOOT, [(wl + wr) / 2, (wt + wb) / 2, zoom])
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
                print(f'{path.name}: crop {box} of {shot.size}, zoom {zoom:.3f}')
            page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")

    def test_4_cap(self):
        out = {}
        for name, page, info in self.pages:
            W = 2 * info['half']
            x0, y0 = self.origin(info)
            for id, (bi, ci) in CAPS.items():
                r = page.evaluate(DROP, [id, x0, y0, bi, ci, DROP_W * W, DROP_VY, DROP_MOVES])
                msg = (name, id, r)
                print(f"{name} {id}: cap {r['cap']} blue {r['blue']} start y {r['startY']:.2f} vy {r['vyBefore']} -> "
                      f"{r['vyAfter']:.4f} after {r['moves']} moves; green used {r['greenUsed']} blue used {r['blueUsed']} "
                      f"hp {r['hpBefore']}->{r['hpAfter']} streak {r['streakBefore']}->{r['streakAfter']}")
                self.assertEqual(r['capClass'], 'MomentumGreen', msg)
                self.assertEqual(r['blueClass'], 'MomentumBlue', msg)
                # The cap lies on the blue: bottom edge on its top edge, same column
                self.assertLessEqual(abs(r['cap'][3] - r['blue'][1]), CAP_TOL, msg)
                self.assertGreater(r['cap'][2], r['blue'][0], msg)
                self.assertLess(r['cap'][0], r['blue'][2], msg)
                self.assertGreater(r['vyBefore'], 0, msg)
                self.assertEqual(r['vxBefore'], 0, msg)
                self.assertLess(r['vyAfter'], 0, msg)
                self.assertTrue(r['greenUsed'], msg)
                self.assertFalse(r['blueUsed'], msg)
                self.assertEqual(r['hpAfter'], r['hpBefore'], msg)
                self.assertEqual(r['streakAfter'], r['streakBefore'] + 1, msg)
                out.setdefault(id, {})[name] = {k: r[k] for k in ('vyBefore', 'vyAfter', 'greenUsed', 'blueUsed', 'hpBefore',
                                                                   'hpAfter', 'streakBefore', 'streakAfter', 'moves')}
            page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")
        (EVIDENCE_DIR / 'cap-test.json').write_text(json.dumps(out, separators=(',', ':')))

    def test_5_fit(self):
        fit = []
        for id in IDS:
            row = {'id': id}
            for name, page, info in self.pages:
                W = 2 * info['half']
                x0, y0 = self.origin(info)
                r = page.evaluate(PLACE, [id, x0, y0, 'right'])
                radius = page.evaluate('ninja.radius')
                f = frame_fit(r['elements'], x0, y0, W, self.catalog[id]['span'], radius)
                f['W'] = W
                f['ninjaDiameter'] = 2 * radius
                print(f"{name} {id}: W {W} path {f['gap']} (at bounds {f['gapAtBounds']}) = "
                      f"{f['minGapOverDiameter']} x ninja diameter {2 * radius}; grapnel targets reachable "
                      f"{f['reachable']}/{f['targets']}; inside faces {f['insideFaces']}")
                self.assertGreaterEqual(f['minGapOverDiameter'], FIT_MIN_RATIO, (name, id))
                self.assertEqual(f['reachable'], f['targets'], (name, id))
                self.assertTrue(f['insideFaces'], (name, id))
                row[name] = f
            ratio = min(row[name]['minGapOverDiameter'] for name, _page, _info in self.pages)
            row['status'] = 'ok'
            row['fix'] = None
            row['reason'] = (f'passable as scaled: path >= {ratio} x ninja diameter (min {FIT_MIN_RATIO}), '
                             f'every grapnel target reachable from the entry, inside the faces')
            fit.append(row)
            page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")
        (EVIDENCE_DIR / 'frames-fit.json').write_text(json.dumps(fit, separators=(',', ':')))


if __name__ == '__main__':
    unittest.main()
