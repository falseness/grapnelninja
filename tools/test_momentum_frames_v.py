"""Momentum concept frames M93, M110 and their up mirrors in the shafts
(TASK-106).

elements/momentumpatterns.js MOMENTUM_FRAMES_V holds the user's picked shaft
concept frames copied from the TASK-102 catalog (MOMENTUM_FRAMES_CATALOG,
default artifacts/TASK-102/catalog-m.json), every size in W = the shaft's
interior width; MomentumFrameVerticalFactory places them scaled by the live
shaft W (2 x momentumSegmentHalfWidth). They are placeable
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
  within GEOM_TOL of that wall face; each -up placement equals its down
  frame's placement mirrored along the shaft (in W, within GEOM_TOL);
- test_2_refused: momentumPlacePattern returns null for every id in a right
  segment, for the down ids going up and the -up ids going down, and in
  classic/bad; no id is in any momentumPatternsByDir list;
- test_3_shots: at 1280x720 one montage per id: left = the concept PNG
  (artifacts/momentum-frames/png; for -up the down PNG flipped vertically,
  labelled 'mirrored'), right = the frame placed in the game, the view
  cropped to the concept's frame rectangle and scaled to its height (only
  the game's walls and pieces: ninja parked away, no overlay); at 390x844
  the same for M93 and M110 (the wider phone shaft).

MOMENTUM_FRAMES_V_EVIDENCE_DIR (default /tmp/momentum-frames-v) receives
placed.json (compact {id: {viewport: {shaftW, pieces: [{kind, box}]}}}, box
[left, top, right, bottom] relative to (shaft centre x, footprint top)) and
shots/<id>-<viewport>.png.
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
IDS = ['M93', 'M110', 'M93-up', 'M110-up']
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
                    self.assertIsNone(e['motion'], msg)
                    box = [e['left'] - x0, e['top'] - top, e['right'] - x0, e['bottom'] - top]
                    for a, b in zip(box, want):
                        self.assertAlmostEqual(a, b, delta=GEOM_TOL, msg=msg)
                    # Never across a wall face; a wall ledge ends on the face
                    self.assertGreaterEqual(e['left'], walls[0] - EPS, msg)
                    self.assertLessEqual(e['right'], walls[1] + EPS, msg)
                    if abs(p['x'] - p['w'] / 2 + 0.5) < 1e-3:
                        self.assertLessEqual(abs(e['left'] - walls[0]), GEOM_TOL, msg)
                        on_wall += 1
                    if abs(p['x'] + p['w'] / 2 - 0.5) < 1e-3:
                        self.assertLessEqual(abs(e['right'] - walls[1]), GEOM_TOL, msg)
                        on_wall += 1
                    rows.append({'kind': p['kind'], 'box': [round(v, 2) for v in box]})
                # Every blue ledge reaches from a wall
                self.assertEqual(on_wall, sum(p['kind'] == 'blue' for p in entry['pieces']) * 2, (name, id))
                rel[id] = {'W': W, 'length': length, 'boxes': [row['box'] for row in rows]}
                placed.setdefault(id, {})[name] = {'shaftW': round(W, 3), 'pieces': rows}
                print(f"{name} {id} ({d}, segment {shaft['index']}): shaft W {W:.2f} length {length:.2f} pieces "
                      f"{len(rows)} {[e['className'][8:] for e in r['elements']]} wall ends {on_wall} OK")
            # -up = its down frame mirrored along the shaft (compared in W)
            for id in ('M93', 'M110'):
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

    def test_3_shots(self):
        n = 0
        for vi, (name, page, shafts) in enumerate(self.pages):
            for id in (IDS if vi == 0 else PHONE_SHOTS):
                d = frame_dir(id)
                shaft, entry = shafts[d], self.catalog[id]
                half = shaft['half']
                W = 2 * half
                length = entry['span'] * W
                x0, start, top = self.footprint(shaft, length, d)
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
                self.assertIsNotNone(page.evaluate(PLACE, [id, x0, start, d, half]))
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
                path = EVIDENCE_DIR / 'shots' / f'{id}-{name}.png'
                montage.save(path)
                n += 1
                print(f'{path.name}: shaft W {W:.2f} crop {box} of {shot.size}, zoom {zoom:.3f}')
            page.evaluate(CLEAR)
        self.assertEqual(n, len(IDS) + len(PHONE_SHOTS))


if __name__ == '__main__':
    unittest.main()
