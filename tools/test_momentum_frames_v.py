"""Momentum concept frames M93, M110, the sweepers M11, M30 and their up
mirrors in the shafts (TASK-106, TASK-107).

elements/momentumpatterns.js MOMENTUM_FRAMES_V holds the user's picked shaft
concept frames copied from the TASK-102 catalog (MOMENTUM_FRAMES_CATALOG,
default artifacts/TASK-102/catalog-m.json), every size in W = the shaft's
interior width; MomentumFrameVerticalFactory places them scaled by the live
shaft W (2 x momentumSegmentHalfWidth); the M11/M30 blue bar is an axis-x
sweeper (MomentumOneTime {axis: 'x', speedX = speed x W, xMin/xMax = shaft
centre + motion.min/max x W, the wall faces}). They are placeable
(momentumPlacePattern) but not spawned: no id is in momentumPatternsByDir.

At 1280x720 and at 390x844 (touch: the stage is drawn landscape behind the
rotate prompt, so the phone shaft is wider) momentum starts on a course whose segment 1 goes
up and segment 3 down (SCRIPT, as test_momentum_patterns_v), the rAF loop
stopped and the obstacle floor emptied; each frame is placed alone, its
footprint centred along its shaft. Asserts:
- test_1_geometry: placed piece count = catalog count, class per kind,
  nothing lethal, every box = catalog * live shaft W within GEOM_TOL world
  units (x across from the shaft centre line, y along from the footprint's
  top end), every piece between the shaft's wall faces (never crossing
  them), a ledge whose catalog edge is on a wall (|x +- w/2| = 0.5 W) ends
  within GEOM_TOL of that wall face, every static blue reaches from a wall;
  a catalog motion piece is an axis-x sweeper with the bounds and speed
  above, the others static; each -up placement equals its down frame's
  placement mirrored along the shaft (in W, within GEOM_TOL);
- test_2_refused: momentumPlacePattern returns null for every id in a right
  segment, for the down ids going up and the -up ids going down, and in
  classic/bad; no id is in any momentumPatternsByDir list;
- test_3_shots: at 1280x720 one montage per id: left = the concept PNG
  (artifacts/momentum-frames/png; for -up the down PNG flipped vertically,
  labelled 'mirrored'), right = the frame placed in the game, the view
  cropped to the concept's frame rectangle and scaled to its height (only
  the game's walls and pieces: ninja parked away, no overlay); at 390x844
  the same for M93 and M110 (the wider phone shaft);
- test_4_sweep: every sweeper id at both viewports, its pattern floor
  stepped SWEEP_CYCLES times: exactly the catalog's pieces (M11 3, M30 2: no
  arrow piece), only the bar moves, its y and size stay constant, it never
  crosses a wall face, travels >= 0.5 W, reverses >= 2 times, each reversal
  within 1 world unit of a wall face, |dx| = speedX x momentumMotionScale(1);
- test_5_sweep_shots: at 1280x720 for M11 and M30 three montages (as in
  test_3): the bar at the left wall, in the middle, at the right wall.

MOMENTUM_FRAMES_V_EVIDENCE_DIR (default /tmp/momentum-frames-v) receives
placed.json (compact {id: {viewport: {shaftW, pieces: [{kind, box}]}}}, box
[left, top, right, bottom] relative to (shaft centre x, footprint top)),
sweep.json (compact {id: {viewport: {shaftW, xMin, xMax, minLeft, maxRight,
reversals, pieceCount, ...}}}), shots/<id>-<viewport>.png and
shots/<id>-sweep-<left|middle|right>-1280x720.png.
Requires Playwright Chromium and Pillow.
"""
import base64
import io
import json
import os
from pathlib import Path
import unittest

from PIL import Image, ImageDraw, ImageFont

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_FRAMES_V_EVIDENCE_DIR', '/tmp/momentum-frames-v'))
CATALOG = Path(os.environ.get('MOMENTUM_FRAMES_CATALOG', ROOT / 'artifacts/TASK-102/catalog-m.json'))
CONCEPTS = ROOT / 'artifacts/momentum-frames'
IDS = ['M93', 'M110', 'M11', 'M30', 'M93-up', 'M110-up', 'M11-up', 'M30-up']
SWEEPERS = ['M11', 'M30', 'M11-up', 'M30-up']
SWEEP_SHOTS = ['M11', 'M30']
SWEEP_CYCLES = 400
# Phone shots: the down frames only
PHONE_SHOTS = ['M93', 'M110']
VIEWPORTS = [{'width': 1280, 'height': 720, 'touch': False}, {'width': 390, 'height': 844, 'touch': True}]
# Segments: right (short), up (~5 heights), right (long), down (~5 heights)
SCRIPT = [0.1, 0.99, 0.1, 0.99, 0.9, 0.99, 0.9, 0.99]
SEGMENT = {'up': 1, 'down': 3}
GEOM_TOL = 1.0
EPS = 1e-6
# Concept frame: 1 W = 480 frame px, shaft centre line at frame x 315,
# along anchor = smallest piece y - 48
FRAME_PX = 480
CENTRE_PX = 315
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}

START = '''() => { startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    return Object.fromEntries(['up', 'down'].map(dir => {
        const i = dir == 'up' ? 1 : 3, s = momentumCourse.segment(i)
        return [dir, {index: i, dir: s.dir, segment: s, half: momentumSegmentHalfWidth(s),
                      walls: momentumBorders().filter(b => b.segment == i).map(b => b.x0)}]
    })) }'''
PLACE = '''([id, x, y, dir, half]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []; floor.groups = []
    return momentumPlacePattern(id, x, y, dir, half)
}'''
# View zoomed by zoom (< 1 zooms out), centred on (cx, cy) with the camera in
# course segment `segment` (the wall mask keeps the corridor round
# screen.segmentIndex), ninja parked far away, drawn without the UI layer;
# returns the canvas PNG and the world -> canvas px mapping
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
# Steps the pattern floor `cycles` times; per cycle (row 0 = placed) each
# element's [left, top, right, bottom], plus the movers' dx and speedX
STEP = '''(cycles) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    const box = e => { const b = getElementBounds(e); return [b.left, b.top, b.right, b.bottom] }
    const rows = [floor.elements.map(box)], dx = []
    for (let k = 1; k <= cycles; ++k) {
        floor.moveElements()
        rows.push(floor.elements.map(box))
        dx.push(floor.elements.map(e => e.dx || 0))
    }
    return {rows: rows, dx: dx, speedX: floor.elements.map(e => e.speedX || 0), motionScale: momentumMotionScale(1)}
}'''
CLEAR = "floors.find(f => f instanceof MomentumPatternFloor).elements = []"


def frame_dir(id):
    return 'up' if id.endswith('-up') else 'down'


def expected_boxes(entry, W):
    """Catalog rects in W -> world boxes relative to (centre x, footprint top)"""
    return [[(p['x'] - p['w'] / 2) * W, (p['y'] - p['h'] / 2) * W, (p['x'] + p['w'] / 2) * W, (p['y'] + p['h'] / 2) * W]
            for p in entry['pieces']]


def anchor_y(frame):
    """Concept frame px of the footprint start (smallest piece y - 48)"""
    return min(p['y'] for p in frame['pieces']) - 48


class MomentumFramesVTests(unittest.TestCase):
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
            shafts = page.evaluate(START)
            for d in ('up', 'down'):
                assert shafts[d]['dir'] == d and len(shafts[d]['walls']) == 2, shafts[d]
            cls.pages.append((f"{vp['width']}x{vp['height']}", page, shafts))
        cls.motion_scale = cls.pages[0][1].evaluate('momentumMotionScale(1)')

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def footprint(self, shaft, length, d):
        """Shaft centre x, footprint start (centred along the shaft) and top"""
        s = shaft['segment']
        mid = (s['y0'] + s['y1']) / 2
        start = mid + length / 2 if d == 'up' else mid - length / 2
        return s['x0'], start, start - length if d == 'up' else start

    def test_1_geometry(self):
        self.assertEqual(sorted(self.catalog), sorted(IDS))
        placed = {}
        for name, page, shafts in self.pages:
            rel = {}
            for id in IDS:
                d = frame_dir(id)
                shaft, entry = shafts[d], self.catalog[id]
                half = shaft['half']
                W = 2 * half
                length = entry['span'] * W
                x0, start, top = self.footprint(shaft, length, d)
                r = page.evaluate(PLACE, [id, x0, start, d, half])
                self.assertIsNotNone(r, (name, id))
                self.assertAlmostEqual(r['length'], length, delta=EPS)
                self.assertEqual(len(r['elements']), len(entry['pieces']), (name, id))
                walls = sorted(shaft['walls'])
                self.assertAlmostEqual(walls[0], x0 - half, delta=EPS)
                self.assertAlmostEqual(walls[1], x0 + half, delta=EPS)
                rows, on_wall = [], 0
                for k, (e, p, want) in enumerate(zip(r['elements'], entry['pieces'], expected_boxes(entry, W))):
                    msg = (name, id, k)
                    self.assertEqual(e['className'], CLASSES[p['kind']], msg)
                    self.assertFalse(e['lethal'], msg)
                    if 'motion' in p:
                        mo = p['motion']
                        self.assertEqual(p['kind'], 'blue', msg)
                        self.assertEqual(mo['axis'], 'x', msg)
                        self.assertEqual(e['motion']['axis'], 'x', msg)
                        self.assertAlmostEqual(e['motion']['xMin'], x0 + mo['min'] * W, delta=EPS, msg=msg)
                        self.assertAlmostEqual(e['motion']['xMax'], x0 + mo['max'] * W, delta=EPS, msg=msg)
                        self.assertAlmostEqual(e['motion']['xMin'], walls[0], delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(e['motion']['xMax'], walls[1], delta=GEOM_TOL, msg=msg)
                        self.assertAlmostEqual(e['motion']['speedX'], mo['speed'] * W * self.motion_scale, delta=EPS, msg=msg)
                    else:
                        self.assertIsNone(e['motion'], msg)
                    box = [e['left'] - x0, e['top'] - top, e['right'] - x0, e['bottom'] - top]
                    for a, b in zip(box, want):
                        self.assertAlmostEqual(a, b, delta=GEOM_TOL, msg=msg)
                    # Never across a wall face; a wall ledge ends on the face
                    self.assertGreaterEqual(e['left'], walls[0] - EPS, msg)
                    self.assertLessEqual(e['right'], walls[1] + EPS, msg)
                    ends = 0
                    if abs(p['x'] - p['w'] / 2 + 0.5) < 1e-3:
                        self.assertLessEqual(abs(e['left'] - walls[0]), GEOM_TOL, msg)
                        ends += 1
                    if abs(p['x'] + p['w'] / 2 - 0.5) < 1e-3:
                        self.assertLessEqual(abs(e['right'] - walls[1]), GEOM_TOL, msg)
                        ends += 1
                    if p['kind'] == 'blue' and 'motion' not in p:
                        self.assertGreaterEqual(ends, 1, msg)
                    on_wall += ends
                    rows.append({'kind': p['kind'], 'box': [round(v, 2) for v in box]})
                rel[id] = {'W': W, 'length': length, 'boxes': [row['box'] for row in rows]}
                placed.setdefault(id, {})[name] = {'shaftW': round(W, 3), 'pieces': rows}
                print(f"{name} {id} ({d}, segment {shaft['index']}): shaft W {W:.2f} length {length:.2f} pieces "
                      f"{len(rows)} {[e['className'][8:] for e in r['elements']]} wall ends {on_wall} OK")
            # -up = its down frame mirrored along the shaft (compared in W)
            for id in [i for i in IDS if not i.endswith('-up')]:
                down, up = rel[id], rel[id + '-up']
                k = up['W'] / down['W']
                for i, (b, u) in enumerate(zip(down['boxes'], up['boxes'])):
                    mirrored = [b[0] * k, (down['length'] - b[3]) * k, b[2] * k, (down['length'] - b[1]) * k]
                    for a, m in zip(u, mirrored):
                        self.assertAlmostEqual(a, m, delta=GEOM_TOL, msg=(name, id, i))
                print(f"{name} {id}-up = {id} mirrored along the shaft ({len(up['boxes'])} boxes within {GEOM_TOL}) OK")
            page.evaluate(CLEAR)
        (EVIDENCE_DIR / 'placed.json').write_text(json.dumps(placed, separators=(',', ':')))

    def test_2_refused(self):
        for name, page, shafts in self.pages:
            r = page.evaluate('''(ids) => {
                const out = {right: ids.filter(id => momentumPlacePattern(id, 0, 0, 'right') !== null),
                             wrongDir: ids.filter(id => momentumPlacePattern(id, 0, 0,
                                 id.endsWith('-up') ? 'down' : 'up') !== null),
                             registered: ids.filter(id => id in momentumPatternFactories),
                             byDir: Object.fromEntries(Object.entries(momentumPatternsByDir).map(([d, l]) => [d, l.slice()]))}
                floors.find(f => f instanceof MomentumPatternFloor).elements = []
                return out }''', IDS)
            print(name, 'placed right', r['right'], 'wrong direction', r['wrongDir'], 'registered', r['registered'],
                  'in byDir', {d: [i for i in l if i in IDS] for d, l in r['byDir'].items()})
            self.assertEqual(r['right'], [])
            self.assertEqual(r['wrongDir'], [])
            self.assertEqual(r['registered'], IDS)
            for d, ids in r['byDir'].items():
                self.assertEqual([i for i in ids if i in IDS], [], d)
        # Classic and bad on a page of their own: switching modes on a shared
        # page leaves the later momentum shots black
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        r = page.evaluate('''(ids) => {
            const out = {}
            for (const mode of ['classic', 'bad']) {
                startGame(mode); cancelAnimationFrame(game)
                out[mode] = ids.filter(id => momentumPlacePattern(id, 0, 0, id.endsWith('-up') ? 'up' : 'down') !== null)
            }
            return out }''', IDS)
        print('classic/bad placed', r)
        self.assertEqual(r, {'classic': [], 'bad': []})

    def place(self, page, shafts, id):
        d = frame_dir(id)
        shaft, entry = shafts[d], self.catalog[id]
        half = shaft['half']
        W = 2 * half
        length = entry['span'] * W
        x0, start, top = self.footprint(shaft, length, d)
        r = page.evaluate(PLACE, [id, x0, start, d, half])
        self.assertIsNotNone(r, id)
        return shaft, W, x0, start, top

    def montage(self, page, shafts, id, name, path, cycles=0):
        """Concept PNG | the frame placed in the game (its floor first stepped
        `cycles` times), cropped to the concept's frame rectangle"""
        d = frame_dir(id)
        shaft, W, x0, start, top = self.place(page, shafts, id)
        if cycles:
            page.evaluate(STEP, cycles)
        source = self.concept[id.replace('-up', '')]
        concept = Image.open(CONCEPTS / source['png']).convert('RGB')
        cw, ch = concept.size
        ay = anchor_y(source)
        # World rectangle of the concept image (frame px 0..cw, 0..ch)
        wl, wr = x0 + (0 - CENTRE_PX) / FRAME_PX * W, x0 + (cw - CENTRE_PX) / FRAME_PX * W
        if d == 'down':
            wt, wb = top - ay / FRAME_PX * W, top + (ch - ay) / FRAME_PX * W
        else:
            # The flipped image: its row r is the down frame's row ch - r
            concept = concept.transpose(Image.FLIP_TOP_BOTTOM)
            wt, wb = start - (ch - ay) / FRAME_PX * W, start + ay / FRAME_PX * W
            draw = ImageDraw.Draw(concept)
            try:
                font = ImageFont.truetype('DejaVuSans-Bold.ttf', 32)
            except OSError:
                font = ImageFont.load_default()
            draw.rectangle([0, ch - 48, 180, ch], fill=(255, 255, 255), outline=(0, 0, 0))
            draw.text((10, ch - 44), 'mirrored', fill=(200, 0, 0), font=font)
        view = page.evaluate('[width / scale[version], height / scale[version]]')
        zoom = min(view[0] / (wr - wl), view[1] / (wb - wt)) * 0.98
        m = page.evaluate(SHOOT, [(wl + wr) / 2, (wt + wb) / 2, zoom, shaft['index']])
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
        montage.save(path)
        print(f'{path.name}: shaft W {W:.2f} crop {box} of {shot.size}, zoom {zoom:.3f}, cycles {cycles}')

    def test_3_shots(self):
        n = 0
        for vi, (name, page, shafts) in enumerate(self.pages):
            for id in (IDS if vi == 0 else PHONE_SHOTS):
                self.montage(page, shafts, id, name, EVIDENCE_DIR / 'shots' / f'{id}-{name}.png')
                n += 1
            page.evaluate(CLEAR)
        self.assertEqual(n, len(IDS) + len(PHONE_SHOTS))

    def sweep(self, page, shafts, id):
        """Places id, steps it SWEEP_CYCLES times: (W, x0, walls, bar index, STEP result)"""
        shaft, W, x0, start, top = self.place(page, shafts, id)
        r = page.evaluate(STEP, SWEEP_CYCLES)
        bar = [i for i, p in enumerate(self.catalog[id]['pieces']) if 'motion' in p]
        self.assertEqual(len(bar), 1, id)
        return W, x0, (x0 - shaft['half'], x0 + shaft['half']), bar[0], r

    @staticmethod
    def reversals(dx):
        """[(cycle, side)] where the bar's dx changes sign (cycle = the move that turned)"""
        return [(k, 'right' if dx[k - 1] > 0 else 'left') for k in range(1, len(dx)) if dx[k] * dx[k - 1] < 0]

    def test_4_sweep(self):
        out = {}
        for name, page, shafts in self.pages:
            for id in SWEEPERS:
                entry = self.catalog[id]
                W, x0, walls, bar, r = self.sweep(page, shafts, id)
                rows = r['rows']
                msg = (name, id)
                self.assertEqual(len(rows[0]), len(entry['pieces']), msg)
                self.assertEqual(len(rows[0]), {'M11': 3, 'M30': 2}[id.replace('-up', '')], msg)
                for k, row in enumerate(rows):
                    self.assertEqual(len(row), len(rows[0]), (msg, k))
                    for i, b in enumerate(row):
                        if i != bar:
                            self.assertEqual(b, rows[0][i], (msg, k, i))
                    b, b0 = row[bar], rows[0][bar]
                    self.assertAlmostEqual(b[1], b0[1], delta=EPS, msg=(msg, k))
                    self.assertAlmostEqual(b[3], b0[3], delta=EPS, msg=(msg, k))
                    self.assertAlmostEqual(b[2] - b[0], b0[2] - b0[0], delta=EPS, msg=(msg, k))
                    self.assertGreaterEqual(b[0], walls[0] - EPS, (msg, k))
                    self.assertLessEqual(b[2], walls[1] + EPS, (msg, k))
                step = abs(r['speedX'][bar])
                want = entry['pieces'][bar]['motion']['speed'] * W * r['motionScale']
                self.assertAlmostEqual(step, want, delta=EPS, msg=msg)
                dx = [d[bar] for d in r['dx']]
                for d in dx:
                    self.assertAlmostEqual(abs(d), step, delta=EPS, msg=msg)
                turns = self.reversals(dx)
                # The edge before each turn lies within 1 unit of its wall face
                gaps = []
                for k, side in turns:
                    b = rows[k][bar]
                    gap = walls[1] - b[2] if side == 'right' else b[0] - walls[0]
                    self.assertGreaterEqual(gap, -EPS, (msg, k, side))
                    self.assertLessEqual(gap, 1.0, (msg, k, side))
                    gaps.append(round(gap, 4))
                min_left = min(row[bar][0] for row in rows)
                max_right = max(row[bar][2] for row in rows)
                travel = max(row[bar][0] for row in rows) - min_left
                self.assertGreaterEqual(len(turns), 2, msg)
                self.assertGreaterEqual(travel, 0.5 * W, msg)
                out.setdefault(id, {})[name] = {
                    'shaftW': round(W, 3), 'xMin': round(walls[0], 3), 'xMax': round(walls[1], 3),
                    'minLeft': round(min_left, 3), 'maxRight': round(max_right, 3), 'reversals': len(turns),
                    'turns': [[k, s] for k, s in turns], 'wallGaps': gaps, 'travelW': round(travel / W, 4),
                    'step': round(step, 4), 'pieceCount': len(rows[0]), 'cycles': SWEEP_CYCLES}
                print(f'{name} {id}: W {W:.2f} faces {walls[0]:.2f}..{walls[1]:.2f} bar {min_left:.2f}..{max_right:.2f} '
                      f'travel {travel / W:.4f} W, {len(turns)} reversals {turns} gaps {gaps}, step {step:.4f}, '
                      f'pieces {len(rows[0])}, others static, y constant OK')
            page.evaluate(CLEAR)
        (EVIDENCE_DIR / 'sweep.json').write_text(json.dumps(out, separators=(',', ':')))

    def test_5_sweep_shots(self):
        name, page, shafts = self.pages[0]
        n = 0
        for id in SWEEP_SHOTS:
            W, x0, walls, bar, r = self.sweep(page, shafts, id)
            rows, dx = r['rows'], [d[bar] for d in r['dx']]
            turns = self.reversals(dx)
            at = {side: next(k for k, s in turns if s == side) for side in ('left', 'right')}
            at['middle'] = min(range(len(rows)), key=lambda k: abs((rows[k][bar][0] + rows[k][bar][2]) / 2 - x0))
            for pos in ('left', 'middle', 'right'):
                b = rows[at[pos]][bar]
                self.montage(page, shafts, id, name, EVIDENCE_DIR / 'shots' / f'{id}-sweep-{pos}-{name}.png', at[pos])
                print(f'  {id} {pos}: cycle {at[pos]} bar {b[0]:.2f}..{b[2]:.2f} (faces {walls[0]:.2f}..{walls[1]:.2f})')
                n += 1
        page.evaluate(CLEAR)
        self.assertEqual(n, 6)

if __name__ == '__main__':
    unittest.main()
