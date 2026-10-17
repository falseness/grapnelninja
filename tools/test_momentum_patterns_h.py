"""Momentum horizontal obstacle patterns (elements/momentumpatterns.js).

Reads the TASK-012 horizontal catalog (MOMENTUM_CATALOG_H, default
artifacts/TASK-012/catalog-h.json) and checks every type of it, or with
MOMENTUM_PATTERNS_H_BATCH=N only the N lowest-difficulty ones (ties in
catalog order; 5 = the TASK-014 batch 1). Starts momentum on a course whose first right
segment is long (scripted MomentumCourse.generate, as in
test_momentum_borders), stops the rAF loop, empties the bad obstacle floor
and places each type alone with window.momentumPlacePattern on that
segment. Asserts: all catalog ids are registered, in catalog order (a
batch: its ids are among them); per type the element
count, green count and blue count equal the catalog piece list, piece by
piece (class and box at the catalog fractions of the footprint and band);
no element is lethal (isLethalElement, and only MomentumGreen/MomentumBlue
classes); every element lies inside the floor/ceiling band and footprint.
Also: an 'up' placement stays inside the vertical corridor, and bad mode
has no pattern floor (momentumPlacePattern returns null).

Writes to MOMENTUM_PATTERNS_H_EVIDENCE_DIR (default artifacts/TASK-015):
patterns-h.json (compact {id: {greens, blues, classes, lethal, bbox, bboxBand}};
bbox in world units, bboxBand in footprint/band fractions) and
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
CATALOG = Path(os.environ.get('MOMENTUM_CATALOG_H', ROOT / 'artifacts/TASK-012/catalog-h.json'))
SVG_DIR = CATALOG.parent / 'diagrams'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PATTERNS_H_EVIDENCE_DIR', ROOT / 'artifacts/TASK-015'))
BATCH = int(os.environ.get('MOMENTUM_PATTERNS_H_BATCH', 0)) or None
# First segment right with a length draw of 0.99 (~5 heights), then the LCG
SCRIPT = [0.99]
EPS = 1e-6
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}

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


def batch_types(catalog):
    if BATCH is None:
        return catalog
    order = sorted(range(len(catalog)), key=lambda i: (catalog[i]['difficulty'], i))
    return [catalog[i] for i in order[:BATCH]]


class MomentumPatternsHTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.catalog = json.loads(CATALOG.read_text())
        cls.types = batch_types(cls.catalog)
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
        cls.placed = {}
        cls.summary = {}

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def place(self, t, dir='right'):
        s = self.segment
        x, y = s['x0'] + 0.2 * self.half, s['y0']
        return x, y, self.page.evaluate(PLACE, [t['id'], x, y, dir])

    def test_1_registered_ids(self):
        ids = self.page.evaluate("Object.keys(momentumPatternFactories).filter(id => momentumPatternsByDir.right.includes(id))")
        want = [t['id'] for t in self.types]
        print('registered:', len(ids), ids, 'checked:', len(want), want,
              'difficulties:', [t['difficulty'] for t in self.types], 'catalog length:', len(self.catalog))
        if BATCH is None:
            self.assertEqual(ids, [t['id'] for t in self.catalog])
            self.assertEqual(len(want), len(self.catalog))
        else:
            self.assertTrue(set(want) <= set(ids))

    def test_2_types_match_catalog(self):
        band = 2 * self.half
        s = self.segment
        print('segment 0:', s['dir'], 'x', round(s['x0']), '->', round(s['x1']), 'y', s['y0'],
              'band', band)
        self.assertEqual(s['dir'], 'right')
        for t in self.types:
            with self.subTest(id=t['id']):
                x, y, r = self.place(t)
                length = t['span'] * band
                self.assertLessEqual(x + length, s['x1'])
                self.assertAlmostEqual(r['length'], length, delta=EPS)
                els = r['elements']
                kinds = [p['kind'] for p in t['pieces']]
                greens = sum(e['className'] == 'MomentumGreen' for e in els)
                blues = sum(e['className'] == 'MomentumBlue' for e in els)
                lethal = sum(e['lethal'] for e in els)
                classes = {}
                for e in els:
                    classes[e['className']] = classes.get(e['className'], 0) + 1
                print(f"{t['id']}: elements {len(els)}/{len(kinds)} greens {greens}/{kinds.count('green')}"
                      f" blues {blues}/{kinds.count('blue')} lethal {lethal} classes {classes}")
                self.assertEqual(len(els), len(kinds))
                self.assertEqual(greens, kinds.count('green'))
                self.assertEqual(blues, kinds.count('blue'))
                self.assertEqual(lethal, 0)
                self.assertTrue(set(classes) <= set(CLASSES.values()))
                top, bottom = y - self.half, y + self.half
                for p, e in zip(t['pieces'], els):
                    self.assertEqual(e['className'], CLASSES[p['kind']])
                    want = [x + p['x'] * length, top + p['y'] * band,
                            x + (p['x'] + p['w']) * length, top + (p['y'] + p['h']) * band]
                    got = [e['left'], e['top'], e['right'], e['bottom']]
                    for a, b in zip(got, want):
                        self.assertAlmostEqual(a, b, delta=EPS)
                    self.assertGreaterEqual(e['top'], top - EPS)
                    self.assertLessEqual(e['bottom'], bottom + EPS)
                    self.assertGreaterEqual(e['left'], x - EPS)
                    self.assertLessEqual(e['right'], x + length + EPS)
                bbox = [min(e['left'] for e in els), min(e['top'] for e in els),
                        max(e['right'] for e in els), max(e['bottom'] for e in els)]
                print(f"  inside band y {top:.1f}..{bottom:.1f}: bbox y {bbox[1]:.1f}..{bbox[3]:.1f}"
                      f" x {bbox[0]:.1f}..{bbox[2]:.1f} footprint x {x:.1f}..{x + length:.1f}")
                self.summary[t['id']] = {
                    'greens': greens, 'blues': blues, 'classes': classes, 'lethal': lethal,
                    'bbox': [round(v, 2) for v in bbox],
                    'bboxBand': [round((bbox[0] - x) / length, 4), round((bbox[1] - top) / band, 4),
                                 round((bbox[2] - x) / length, 4), round((bbox[3] - top) / band, 4)]}
                self.placed[t['id']] = (x + length / 2, y)
        (EVIDENCE_DIR / 'patterns-h.json').write_text(json.dumps(self.summary, separators=(',', ':')))
        print('wrote patterns-h.json with', len(self.summary), 'types; catalog length', len(self.catalog),
              '; lethal elements in all types', sum(v['lethal'] for v in self.summary.values()))

    def test_3_up_placement_inside_corridor(self):
        t = self.types[0]
        x, y, r = self.place(t, 'up')
        length = t['span'] * 2 * self.half
        els = r['elements']
        lo = min(e['left'] for e in els)
        hi = max(e['right'] for e in els)
        print(f"up {t['id']}: x {lo:.1f}..{hi:.1f} corridor {x - self.half:.1f}..{x + self.half:.1f}"
              f" y {min(e['top'] for e in els):.1f}..{max(e['bottom'] for e in els):.1f}"
              f" footprint {y - length:.1f}..{y:.1f}")
        self.assertGreaterEqual(lo, x - self.half - EPS)
        self.assertLessEqual(hi, x + self.half + EPS)
        self.assertGreaterEqual(min(e['top'] for e in els), y - length - EPS)
        self.assertLessEqual(max(e['bottom'] for e in els), y + EPS)
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")

    def test_4_compare_screenshots(self):
        if not self.placed:
            self.test_2_types_match_catalog()
        svg_page = self.browser.new_page()
        self.addCleanup(svg_page.close)
        for t in self.types:
            with self.subTest(id=t['id']):
                self.place(t)
                cx, cy = self.placed[t['id']]
                self.page.evaluate(SHOOT, [cx, cy])
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
                print('wrote', path.name, out.size)
                self.assertTrue(path.exists())
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")

    def test_5_bad_mode_has_no_pattern_floor(self):
        r = self.page.evaluate('''() => { startGame('bad'); cancelAnimationFrame(game)
            return {floor: floors.some(f => f instanceof MomentumPatternFloor),
                    placed: momentumPlacePattern('green-ladder', 0, 0), floors: floors.length} }''')
        print('bad mode:', r)
        self.assertFalse(r['floor'])
        self.assertIsNone(r['placed'])


if __name__ == '__main__':
    unittest.main()
