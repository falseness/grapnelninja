"""Momentum concept frames M04, M23, M24 in the right corridor (TASK-104).

elements/momentumpatterns.js MOMENTUM_FRAMES_H holds the user's picked
right-corridor concept frames copied from the TASK-102 catalog
(MOMENTUM_FRAMES_CATALOG, default artifacts/TASK-102/catalog-m.json), every
size in W = the corridor's interior width; MomentumFrameFactory places them
scaled by the live W. They are placeable (momentumPlacePattern) but not
spawned: momentumPatternsByDir.right stays the ported bad frames.

At 1280x720 and at 390x844 (touch) momentum starts on a course whose first
right segment is long (SCRIPT, as test_momentum_patterns_h), the rAF loop
stopped and the obstacle floor emptied; each frame is placed alone. Asserts:
- test_1_geometry: placed piece count = catalog count, class per kind, every
  rect box and polygon vertex = catalog * live W within GEOM_TOL world units,
  motion bounds (y + min/max * W) and speedY (-speed * W *
  momentumMotionScale(1)) match, every piece (and motion range) inside the
  corridor band, nothing lethal;
- test_2_refused: momentumPlacePattern returns null for these ids in an up
  and a down segment and in classic/bad; momentumPatternsByDir.right is still
  MOMENTUM_PATTERNS_PORT_H and no frame id is in any direction list;
- test_3_shots: per id per viewport a montage: left = the concept PNG
  (artifacts/momentum-frames/png), right = the frame placed in the game, the
  view cropped to the concept's frame rectangle and scaled to its height
  (only the game's walls and pieces: ninja parked away, no overlay).

MOMENTUM_FRAMES_H_EVIDENCE_DIR (default /tmp/momentum-frames-h) receives
placed.json (compact {id: {viewport: {W, pieces: [{kind, box|points,
motion}]}}}) and shots/<id>-<viewport>.png.
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
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_FRAMES_H_EVIDENCE_DIR', '/tmp/momentum-frames-h'))
CATALOG = Path(os.environ.get('MOMENTUM_FRAMES_CATALOG', ROOT / 'artifacts/TASK-102/catalog-m.json'))
CONCEPTS = ROOT / 'artifacts/momentum-frames'
IDS = ['M04', 'M23', 'M24']
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
            self.assertEqual(r['byDir']['right'], r['port'])
            for d, ids in r['byDir'].items():
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


if __name__ == '__main__':
    unittest.main()
