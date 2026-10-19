"""Momentum right-segment obstacle patterns (elements/momentumpatterns.js).

Since TASK-038 the right segments spawn the ported bad frames only: the
TASK-036 port catalog (MOMENTUM_PORT_CATALOG, default
artifacts/TASK-036/catalog-bad-port.json), its first MOMENTUM_PORT_COUNT
entries (default all 12). The TASK-012 horizontal types are retired.
Starts momentum on a course whose first right segment is long (scripted
MomentumCourse.generate, as in test_momentum_borders), stops the rAF loop,
empties the obstacle floor and places each frame alone with
window.momentumPlacePattern on that segment. Asserts: the 'right' registry
(momentumPatternsByDir.right, in momentumPatternFactories order) is exactly
the TASK-111 concept frames (FRAMES_H), no port id is in any spawn registry
(momentumPatternsByDir, momentumTurnsByJoin; they stay placeable) and no
retired TASK-012 id is registered
(MOMENTUM_CATALOG_H, default artifacts/TASK-012/catalog-h.json); the frames
are refused outside a right segment; every built piece matches the catalog
piece in order: class (colour), shape (polygon points), box within GEOM_TOL
world units, speedY and motion bounds; nothing lethal. A catalog rect that pokes past the
corridor band (BAND, by the catalog's 0.05 rounding: bad-frame6/10/14) is
expected flush with the band edge instead (TASK-043). Also: bad mode has no
pattern floor (momentumPlacePattern returns null).

Writes to MOMENTUM_PATTERNS_H_EVIDENCE_DIR (default artifacts/TASK-038):
registry-ids.txt (the 'right' ids, one per line), geometry-diff.json
(compact {portId: max box diff}) and shots/port-<portId>.png for the entries
from MOMENTUM_PORT_SHOTS_FROM (1-based, default 7) on (1280x720: momentum
left, the same frame in bad mode right, the same view placement relative to
the band).

Requires Playwright Chromium and Pillow. No remote requests.
"""
import io
import json
import math
import os
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from browser_test_support import start_browser_test, wait_for_boot, wait_for_boot_run
from test_momentum_borders import SEED_COURSE
from verification_scenarios import setup as BAD_FRAME_SETUP

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(os.environ.get('MOMENTUM_CATALOG_H', ROOT / 'artifacts/TASK-012/catalog-h.json'))
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PATTERNS_H_EVIDENCE_DIR', ROOT / 'artifacts/TASK-038'))
PORT_CATALOG = Path(os.environ.get('MOMENTUM_PORT_CATALOG', ROOT / 'artifacts/TASK-036/catalog-bad-port.json'))
PORT_COUNT = int(os.environ.get('MOMENTUM_PORT_COUNT', 12))
SHOTS_FROM = int(os.environ.get('MOMENTUM_PORT_SHOTS_FROM', 7))
GEOM_TOL = 1.0
# Bad corridor centre line (floor..ceiling band 0.2h..2h at h 1080)
BAD_CENTRE_Y = 1188
# The right corridor's spawn registry since TASK-111 (MOMENTUM_FRAMES_H)
FRAMES_H = ['M04', 'M23', 'M24', 'M46', 'M47', 'M66']
# First segment right with a length draw of 0.99 (~5 heights), then the LCG
SCRIPT = [0.99]
EPS = 1e-6
# Right corridor half width: wall-flush catalog rects are built ending here (TASK-043)
BAND = 972
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}

PLACE = '''([id, x, y, dir]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    return momentumPlacePattern(id, x, y, dir)
}'''
# Centres the view on the frame (bad: x only, its camera y kept), ninja
# parked out of view; returns the view centre in world units
SHOOT_PORT = '''([cx, cy]) => {
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(cx - w / 2)
    if (cy !== null)
        screen.y = -(cy - h / 2)
    if (screen.leftWall)
        screen.leftWall.update(screen)
    ninja.x = cx; ninja.y = -1e5; ninja.speedX = ninja.speedY = 0
    draw()
    return {x: -screen.x + w / 2, y: -screen.y + h / 2, scale: scale[version]}
}'''
BAD_FRAME_BOX = '''() => {
    const bs = floors[1].elements.map(box)
    return {left: Math.min(...bs.map(b => b.left)), right: Math.max(...bs.map(b => b.right))}
}'''


class MomentumPatternsHTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.retired = [t['id'] for t in json.loads(CATALOG.read_text())]
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
        cls.page.evaluate('''() => { startGame('momentum'); cancelAnimationFrame(game)
            floors.find(f => f instanceof MomentumObstacleFloor).elements = [] }''')
        cls.half = cls.page.evaluate('GAMEPLAY.momentumBorders.halfWidth')
        cls.segment = cls.page.evaluate('momentumCourse.segment(0)')
        cls.port = json.loads(PORT_CATALOG.read_text())[:PORT_COUNT]

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def place(self, t, dir='right'):
        s = self.segment
        x, y = s['x0'] + 0.2 * self.half, s['y0']
        return x, y, self.page.evaluate(PLACE, [t['id'], x, y, dir])

    def test_1_right_registry_is_the_port(self):
        # Since TASK-111 the right corridor spawns the concept frames only;
        # the ported bad frames stay placeable (test_2..test_4) but spawn nowhere
        ids = [t['id'] for t in self.port]
        r = self.page.evaluate('''([retired, ids]) => ({
            right: Object.keys(momentumPatternFactories).filter(id => momentumPatternsByDir.right.includes(id)),
            byDir: momentumPatternsByDir.right.slice(),
            spawned: ids.filter(id => Object.values(momentumPatternsByDir).some(l => l.includes(id)) ||
                                      Object.values(momentumTurnsByJoin).some(l => l.includes(id))),
            retired: retired.filter(id => id in momentumPatternFactories ||
                                    Object.values(momentumPatternsByDir).some(l => l.includes(id)))})''',
            [self.retired, ids])
        (EVIDENCE_DIR / 'registry-ids.txt').write_text('\n'.join(r['byDir']) + '\n')
        print('right registry:', len(r['byDir']), r['byDir'], '(want', FRAMES_H, ')')
        print('port catalog ids:', len(ids), ids)
        print('port ids in a spawn registry:', r['spawned'])
        print('retired TASK-012 ids still registered:', r['retired'], 'of', len(self.retired))
        self.assertEqual(len(ids), PORT_COUNT)
        self.assertEqual(r['byDir'], FRAMES_H)
        self.assertEqual(r['right'], FRAMES_H)
        self.assertEqual(r['spawned'], [])
        self.assertEqual(r['retired'], [])

    def test_2_port_refused_outside_right(self):
        ids = [t['id'] for t in self.port]
        r = self.page.evaluate('''(ids) => ({registered: ids.filter(id => id in momentumPatternFactories),
            vertical: ids.filter(id => momentumPatternsByDir.up.includes(id) || momentumPatternsByDir.down.includes(id)),
            up: ids.filter(id => momentumPlacePattern(id, 0, 0, 'up') !== null),
            down: ids.filter(id => momentumPlacePattern(id, 0, 0, 'down') !== null)})''', ids)
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")
        print('port ids:', ids, r)
        self.assertEqual(r['registered'], ids)
        self.assertEqual(r['vertical'], [])
        self.assertEqual(r['up'], [])
        self.assertEqual(r['down'], [])

    def test_3_port_pieces_match_catalog(self):
        s = self.segment
        # Catalog motion speeds are full speed; the pieces move at the TASK-073
        # slow motion (speedY x momentumMotionScale(1))
        motion_scale = self.page.evaluate("momentumMotionScale(1)")
        diffs = {}
        for t in self.port:
            with self.subTest(id=t['id']):
                x, y, r = self.place(t)
                self.assertIsNotNone(r)
                self.assertLessEqual(x + t['span'], s['x1'])
                self.assertAlmostEqual(r['length'], t['span'], delta=EPS)
                els = r['elements']
                self.assertEqual(len(els), len(t['pieces']))
                worst = 0
                for i, (p, e) in enumerate(zip(t['pieces'], els)):
                    self.assertEqual(e['className'], CLASSES[p['kind']])
                    self.assertFalse(e['lethal'])
                    b = p['box']
                    want = [x + b['left'], y + b['top'], x + b['right'], y + b['bottom']]
                    got = [e['left'], e['top'], e['right'], e['bottom']]
                    box_diff = max(abs(a - c) for a, c in zip(got, want))
                    if p['shape'] == 'rect':
                        local = [[-p['w'] / 2, -p['h'] / 2], [p['w'] / 2, -p['h'] / 2],
                                 [p['w'] / 2, p['h'] / 2], [-p['w'] / 2, p['h'] / 2]]
                    else:
                        local = p['points']
                    py = p['y']
                    if p['shape'] == 'rect' and abs(py) + p['h'] / 2 > BAND:
                        py = math.copysign(BAND - p['h'] / 2, py)
                    shape = [[x + p['x'] + a, y + py + c] for a, c in local]
                    self.assertEqual(len(e['points']), len(shape))
                    shape_diff = max(max(abs(a[0] - c[0]), abs(a[1] - c[1])) for a, c in zip(e['points'], shape))
                    m = p.get('motion')
                    speed = m['speedY'] * motion_scale if m else 0
                    print(f"{t['id']} piece {i}: {e['className']} {p['shape']} box diff {box_diff:.3f}"
                          f" shape diff {shape_diff:.2e} speedY {e['speedY']}/{speed}"
                          f" motion {e['motion']}")
                    self.assertLessEqual(box_diff, GEOM_TOL)
                    self.assertLess(shape_diff, 1e-6)
                    self.assertAlmostEqual(e['speedY'], speed, delta=EPS)
                    if m:
                        self.assertAlmostEqual(e['motion']['yMin'], y + m['yMin'], delta=EPS)
                        self.assertAlmostEqual(e['motion']['yMax'], y + m['yMax'], delta=EPS)
                        self.assertEqual(e['motion']['gravity'], m['gravity'])
                    else:
                        self.assertIsNone(e['motion'])
                    worst = max(worst, box_diff)
                diffs[t['id']] = round(worst, 3)
        (EVIDENCE_DIR / 'geometry-diff.json').write_text(json.dumps(diffs, separators=(',', ':')))
        print('geometry-diff.json:', diffs)
        self.assertEqual(len(diffs), PORT_COUNT)
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")

    def test_4_port_compare_screenshots(self):
        shots = EVIDENCE_DIR / 'shots'
        shots.mkdir(exist_ok=True)
        bad_page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        self.addCleanup(bad_page.close)
        bad_page.on('pageerror', lambda e: self.errors.append(str(e)))
        bad_page.goto(self.url)
        wait_for_boot(bad_page)
        for t in self.port[SHOTS_FROM - 1:]:
            with self.subTest(id=t['id']):
                bad_page.evaluate(BAD_FRAME_SETUP, t['source'])
                frame = bad_page.evaluate(BAD_FRAME_BOX)
                self.assertAlmostEqual(frame['left'], t['originX'], delta=GEOM_TOL)
                bad_view = bad_page.evaluate(SHOOT_PORT, [(frame['left'] + frame['right']) / 2, None])
                bad = Image.open(io.BytesIO(bad_page.screenshot())).convert('RGB')
                x, y, _ = self.place(t)
                view = self.page.evaluate(SHOOT_PORT, [x + (frame['right'] - frame['left']) / 2,
                                                       y + bad_view['y'] - BAD_CENTRE_Y])
                game = Image.open(io.BytesIO(self.page.screenshot())).convert('RGB')
                print(f"{t['id']}: bad view centre {bad_view} momentum view centre {view}"
                      f" (frame centre offset bad {bad_view['x'] - frame['left']:.1f}"
                      f" momentum {view['x'] - x:.1f}, band offset bad {bad_view['y'] - BAD_CENTRE_Y:.1f}"
                      f" momentum {view['y'] - y:.1f})")
                self.assertAlmostEqual(view['scale'], bad_view['scale'], delta=1e-9)
                self.assertAlmostEqual(view['x'] - x, bad_view['x'] - frame['left'], delta=GEOM_TOL)
                self.assertAlmostEqual(view['y'] - y, bad_view['y'] - BAD_CENTRE_Y, delta=GEOM_TOL)
                out = Image.new('RGB', (1280, 720), (255, 255, 255))
                out.paste(game.resize((636, 358)), (0, 181))
                out.paste(bad.resize((636, 358)), (644, 181))
                label = ImageDraw.Draw(out)
                label.text((8, 160), f"momentum {t['id']}", fill=(0, 0, 0))
                label.text((652, 160), f"bad {t['source']}", fill=(0, 0, 0))
                path = shots / f"port-{t['id']}.png"
                out.save(path)
                print('wrote', path.relative_to(EVIDENCE_DIR), out.size)
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")

    def test_5_bad_mode_has_no_pattern_floor(self):
        r = self.page.evaluate('''() => { startGame('bad'); cancelAnimationFrame(game)
            return {floor: floors.some(f => f instanceof MomentumPatternFloor),
                    placed: momentumPlacePattern('bad-frame1', 0, 0), floors: floors.length} }''')
        print('bad mode:', r)
        self.assertFalse(r['floor'])
        self.assertIsNone(r['placed'])


if __name__ == '__main__':
    unittest.main()
