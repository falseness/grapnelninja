"""Momentum vertical ports of the bad frames (elements/momentumpatterns.js).

Reads the TASK-036 port catalog (MOMENTUM_PORT_CATALOG, default
tools/data/momentum-catalog-bad-port.json) and checks every entry with a
`vertical` variant: MOMENTUM_PATTERNS_PORT_V, id <entry id>-v, the bad frame
rotated 90 deg and scaled uniformly by the shaft's half width over the base
one (TASK-030 wide shafts), so the pieces span the shaft wall to wall as the
frame spans floor..ceiling in bad.

At 1280x720 and 390x844 (fresh page each) momentum starts on a scripted
course (MomentumCourse.generate seeded as in test_momentum_borders) whose
segment 1 goes up and segment 3 goes down, the rAF loop stopped and the bad
obstacle floor emptied; each variant is placed alone with
window.momentumPlacePattern in each of its directions, its footprint centred
along the shaft. Asserts:
- momentumPatternsByDir up/down list exactly the TASK-111 concept frames
  (FRAMES_V), no variant is in any spawn registry (momentumPatternsByDir,
  momentumTurnsByJoin) while every variant is still registered and placed
  below, no retired TASK-013 vertical type is registered, a variant in
  'right' and a ported frame (bad-frameN) in a shaft place nothing;
- per variant and direction: class, colour and rect of every piece = the
  catalog piece scaled by the shaft half width / base half width (wall
  anchored pieces flush with their wall), footprint length = span x that
  scale, 0 lethal elements, the across fill (bbox width / shaft width) equals
  the bad frame's across fill (catalog box / band);
- 0 pieces outside the shaft (across between its two wall faces, along
  within the segment) and 0 pieces crossing any border face line.

Writes to MOMENTUM_PATTERNS_V_EVIDENCE_DIR (default artifacts/TASK-039):
registry-ids.txt, pieces-inside.json (compact {viewport: {halfWidth, scale,
variants: {id/dir: {pieces, outside, inWall, acrossFill, badFill, length,
spawnable}}}}; spawnable = the footprint clears both join margins of a
shaft this long) and shots/port-<id>-<dir>.png (1280x720: the game view,
zoomed out to the whole footprint when it is taller than the view, left;
the bad frame of the TASK-036 montage rotated the same way, right; the
montage is read from MOMENTUM_PORT_MONTAGE_DIR, default
artifacts/TASK-036/shots, and the shot is the game view alone when it is
missing, e.g. in a clean checkout).

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
CATALOG = Path(os.environ.get('MOMENTUM_PORT_CATALOG', ROOT / 'tools/data/momentum-catalog-bad-port.json'))
MONTAGE_DIR = Path(os.environ.get('MOMENTUM_PORT_MONTAGE_DIR', ROOT / 'artifacts/TASK-036/shots'))
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PATTERNS_V_EVIDENCE_DIR', ROOT / 'artifacts/TASK-039'))
# Segments: right (short), up (~5 heights), right (short), down (~5 heights)
# Segment 2 long (0.9) so the down shaft stays clear of the up one
# (MomentumCourse oppositeShaftGap, TASK-030)
SCRIPT = [0.1, 0.99, 0.1, 0.99, 0.9, 0.99, 0.9, 0.99]
SEGMENT = {'up': 1, 'down': 3}
VIEWPORTS = [(1280, 720), (390, 844)]
EPS = 1e-6
CLASSES = {'green': 'MomentumGreen', 'blue': 'MomentumBlue'}
RETIRED = ['wall-ladder', 'gate-bypass', 'trampoline-chimney', 'ricochet-well', 'staggered-column', 'needle-shaft']
# The bad frame's half of a TASK-036 montage (x 0..960, below the 30 px title)
MONTAGE_BAD = (0, 30, 960, 570)
# The shafts' spawn registries since TASK-111 (MOMENTUM_FRAMES_V); the
# variants stay placeable but spawn nowhere
FRAMES_V = {'up': ['M11-up', 'M30-up', 'M93-up', 'M110-up'], 'down': ['M11', 'M30', 'M93', 'M110']}
INSIDE = {}

START = '''() => { startGame('momentum'); cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = [] }'''
# base: the shaft half width the vertical ports are scaled from
# (MomentumPortVerticalPatternFactory.getScale; the right corridors' half width
# before TASK-128)
COURSE = '''() => ({base: GAMEPLAY.momentumBorders.shaftReferenceHalfWidth,
    margin: GAMEPLAY.momentumSpawn.joinMarginHalfWidths * GAMEPLAY.momentumBorders.halfWidth,
    shafts: Object.fromEntries(['up', 'down'].map(dir => {
        const i = dir == 'up' ? 1 : 3, s = momentumCourse.segment(i)
        return [dir, {segment: s, half: momentumSegmentHalfWidth(s),
                      walls: momentumBorders().filter(b => b.segment == i)}]
    })),
    borders: momentumBorders(),
    registry: Object.keys(momentumPatternFactories), byDir: momentumPatternsByDir})'''
PLACE = '''([id, x, y, dir, half]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    return momentumPlacePattern(id, x, y, dir, half)
}'''
# Centres the view on (cx, cy) at zoom (< 1 zooms out) with the camera in
# course segment `segment` (the TASK-044 wall mask keeps the corridor round
# screen.segmentIndex), draws, restores scale and segment
SHOOT = '''([cx, cy, zoom, segment]) => {
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const s0 = scale[version], i0 = screen.segmentIndex
    scale[version] = s0 * zoom
    screen.segmentIndex = segment
    try {
        const w = width / scale[version], h = height / scale[version]
        screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
        screen.leftWall.update(screen)
        for (const f of floors)
            if (f instanceof MomentumBorderFloor)
                f.replenishElements()
        ninja.x = cx - 0.3 * w; ninja.y = cy; ninja.speedX = ninja.speedY = 0
        draw()
    } finally { scale[version] = s0; screen.segmentIndex = i0 }
}'''


def variants():
    return [e for e in json.loads(CATALOG.read_text()) if e.get('vertical')]


def variant_dirs(entry):
    return [d for d in ('up', 'down') if entry['vertical'].get(d)]


def bad_fill(entry):
    """Across extent of the bad frame / the bad band (floor..ceiling)."""
    lo = min(p['y'] - p['h'] / 2 for p in entry['pieces'])
    hi = max(p['y'] + p['h'] / 2 for p in entry['pieces'])
    return (min(hi, 972) - max(lo, -972)) / 1944


def crosses(box, line):
    """Whether an axis-aligned border face line runs through the box interior."""
    left, top, right, bottom = box
    if abs(line['y0'] - line['y1']) < EPS:
        c, a, b = line['y0'], *sorted([line['x0'], line['x1']])
        return top + EPS < c < bottom - EPS and min(right, b) - max(left, a) > EPS
    c, a, b = line['x0'], *sorted([line['y0'], line['y1']])
    return left + EPS < c < right - EPS and min(bottom, b) - max(top, a) > EPS


class PortVBase:
    viewport = None

    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.entries = variants()
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        w, h = cls.viewport
        context = cls.browser.new_context(viewport={'width': w, 'height': h})
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

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def footprint(self, entry, d):
        """Footprint start (centred along the shaft), its top and length."""
        shaft = self.course['shafts'][d]
        s, half = shaft['segment'], shaft['half']
        k = half / self.course['base']
        length = entry['span'] * k
        mid = (s['y0'] + s['y1']) / 2
        start = mid + length / 2 if d == 'up' else mid - length / 2
        return s['x0'], start, (start - length if d == 'up' else start), length, k

    def test_1_registry(self):
        ids, by_dir = self.course['registry'], self.course['byDir']
        want = {d: [e['id'] + '-v' for e in self.entries if d in variant_dirs(e)] for d in ('up', 'down')}
        variants = want['up'] + [i for i in want['down'] if i not in want['up']]
        spawned = [i for i in variants if any(i in v for v in by_dir.values()) or
                   any(i in v for v in self.page.evaluate('Object.values(momentumTurnsByJoin)'))]
        lines = [f"viewport {self.viewport[0]}x{self.viewport[1]}",
                 f"catalog vertical variants: {[e['id'] for e in self.entries]}"]
        for d in ('up', 'down'):
            lines.append(f"{d}: {by_dir[d]} (want {FRAMES_V[d]}) {'MATCH' if by_dir[d] == FRAMES_V[d] else 'MISMATCH'}")
        lines.append(f"variants in a spawn registry: {spawned}")
        lines.append(f"right: {by_dir['right']}")
        retired = [i for i in RETIRED if i in ids or any(i in v for v in by_dir.values())]
        lines.append(f"retired TASK-013 vertical ids still registered: {retired}")
        refused = self.page.evaluate('''(ids) => ({right: ids.filter(id => momentumPlacePattern(id, 0, 0, 'right') !== null),
            portInShaft: ids.map(id => id.replace(/-v$/, '')).filter(id => momentumPlacePattern(id, 0, 0, 'up') !== null ||
                                                                         momentumPlacePattern(id, 0, 0, 'down') !== null)})''',
                                     variants)
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")
        lines.append(f"variants placed in 'right': {refused['right']}; ported frames placed in a shaft: "
                     f"{refused['portInShaft']}")
        print('\n'.join(lines))
        if self.viewport == VIEWPORTS[0]:
            (EVIDENCE_DIR / 'registry-ids.txt').write_text('\n'.join(lines) + '\n')
        self.assertEqual(len(self.entries), 6)
        for d in ('up', 'down'):
            self.assertEqual(by_dir[d], FRAMES_V[d])
            self.assertEqual([i for i in ids if i in want[d]], want[d])
        self.assertEqual(spawned, [])
        self.assertEqual(retired, [])
        self.assertEqual(refused, {'right': [], 'portInShaft': []})

    def test_2_pieces_inside(self):
        out = {'halfWidth': {d: self.course['shafts'][d]['half'] for d in ('up', 'down')}, 'variants': {}}
        for e in self.entries:
            for d in variant_dirs(e):
                with self.subTest(id=e['id'], dir=d):
                    out['variants'][f"{e['id']}-v/{d}"] = self.check(e, d)
        INSIDE[f"{self.viewport[0]}x{self.viewport[1]}"] = out
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")

    def check(self, e, d):
        shaft = self.course['shafts'][d]
        s, half = shaft['segment'], shaft['half']
        x0, start, top, length, k = self.footprint(e, d)
        r = self.page.evaluate(PLACE, [e['id'] + '-v', x0, start, d, half])
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['length'], length, delta=EPS)
        els, pieces = r['elements'], e['vertical'][d]
        self.assertEqual(len(els), len(pieces))
        walls = sorted(w['x0'] for w in shaft['walls'])
        self.assertEqual(len(walls), 2)
        self.assertAlmostEqual(walls[0], x0 - half, delta=EPS)
        self.assertAlmostEqual(walls[1], x0 + half, delta=EPS)
        along = sorted([s['y0'], s['y1']])
        outside, in_wall = [], []
        for i, (p, el) in enumerate(zip(pieces, els)):
            self.assertEqual(el['className'], CLASSES[p['kind']])
            self.assertFalse(el['lethal'])
            w, h = p['w'] * k, p['h'] * k
            cx, cy = x0 + p['x'] * k, start + p['y'] * k
            tol = EPS
            if p.get('wallAnchor'):
                # Flush with the wall on its side; the catalog edge was within rounding of the band edge
                side = 1 if p['x'] > 0 else -1
                self.assertAlmostEqual(el['left'] if side < 0 else el['right'], x0 + side * half, delta=EPS)
                tol = 0.1 * k + EPS
            box = [el['left'], el['top'], el['right'], el['bottom']]
            for a, b in zip(box, [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]):
                self.assertAlmostEqual(a, b, delta=tol)
            if (box[0] < walls[0] - EPS or box[2] > walls[1] + EPS or
                    box[1] < along[0] - EPS or box[3] > along[1] + EPS):
                outside.append(i)
            if any(crosses(box, line) for line in self.course['borders']):
                in_wall.append(i)
        bbox = [min(x['left'] for x in els), min(x['top'] for x in els),
                max(x['right'] for x in els), max(x['bottom'] for x in els)]
        fill = (bbox[2] - bbox[0]) / (2 * half)
        bad = bad_fill(e)
        margin = self.course['margin']
        spawnable = length <= s['length'] - 2 * margin
        print(f"{self.viewport} {e['id']}-v {d}: pieces {len(els)} classes "
              f"{[x['className'][8:] for x in els]} scale {k:.4f} length {length:.1f} (shaft {s['length']:.1f},"
              f" spawnable {spawnable}) bbox x {bbox[0]:.1f}..{bbox[2]:.1f} walls {walls[0]:.1f}..{walls[1]:.1f}"
              f" y {bbox[1]:.1f}..{bbox[3]:.1f} segment {along[0]:.1f}..{along[1]:.1f} across fill {fill:.4f}"
              f" bad {bad:.4f} outside {outside} inWall {in_wall}")
        self.assertEqual(outside, [])
        self.assertEqual(in_wall, [])
        self.assertAlmostEqual(fill, bad, delta=1e-3)
        return {'pieces': len(els), 'outside': len(outside), 'inWall': len(in_wall), 'scale': round(k, 4),
                'acrossFill': round(fill, 4), 'badFill': round(bad, 4), 'length': round(length, 1),
                'shaftLength': round(s['length'], 1), 'spawnable': spawnable}


class MomentumPatternsVLandscapeTests(PortVBase, unittest.TestCase):
    viewport = VIEWPORTS[0]

    def test_3_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        shots.mkdir(parents=True, exist_ok=True)
        view_h = self.page.evaluate('height / scale[version]')
        n = 0
        for e in self.entries:
            source = MONTAGE_DIR / f"{e['id']}.png"
            montage = Image.open(source).convert('RGB').crop(MONTAGE_BAD) if source.is_file() else None
            for d in variant_dirs(e):
                with self.subTest(id=e['id'], dir=d):
                    shaft = self.course['shafts'][d]
                    x0, start, top, length, k = self.footprint(e, d)
                    self.assertIsNotNone(self.page.evaluate(PLACE, [e['id'] + '-v', x0, start, d, shaft['half']]))
                    zoom = min(1, view_h / (length + 0.3 * shaft['half']))
                    self.page.evaluate(SHOOT, [x0, top + length / 2, zoom, 1 if d == 'up' else 3])
                    game = Image.open(io.BytesIO(self.page.screenshot())).convert('RGB')
                    out = game
                    if montage:
                        # Up: the bad frame's right (travel) points up; down: it points down
                        bad = montage.rotate(90 if d == 'up' else -90, expand=True)
                        bad = bad.resize((round(bad.width * game.height / bad.height), game.height))
                        out = Image.new('RGB', (game.width + bad.width + 8, game.height), (255, 255, 255))
                        out.paste(game, (0, 0))
                        out.paste(bad, (game.width + 8, 0))
                    path = shots / f"port-{e['id']}-v-{d}.png"
                    out.save(path)
                    n += 1
                    print('wrote', path.name, out.size, f'zoom {zoom:.3f}')
        self.page.evaluate("floors.find(f => f instanceof MomentumPatternFloor).elements = []")
        self.assertLessEqual(n, 12)


class MomentumPatternsVPortraitTests(PortVBase, unittest.TestCase):
    viewport = VIEWPORTS[1]


def tearDownModule():
    if INSIDE:
        path = EVIDENCE_DIR / 'pieces-inside.json'
        path.write_text(json.dumps(INSIDE, separators=(',', ':')))
        print('wrote pieces-inside.json:', {v: (sum(x['outside'] for x in o['variants'].values()),
                                                sum(x['inWall'] for x in o['variants'].values()))
                                            for v, o in INSIDE.items()}, '(outside, inWall)')


if __name__ == '__main__':
    unittest.main()
