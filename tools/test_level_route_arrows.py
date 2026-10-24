"""Tests for the distance-based transfer direction arrows in tools/convert_extended_mountain_svg.py.

    python3 -m unittest discover -s tools -p test_level_route_arrows.py -v

Each arrow's shaft is the transfer guide from t=0 to the parameter where its arc
length reaches min(0.5 * G, L): G is the minimum edge-to-edge gap between the
transfer's complete fragment polygons, L the guide's arc length (world units).
Uses the shipped measurements (artifacts/levels) and the FIXTURES below (short,
long, curved, capped and degenerate guides). Arc lengths are re-measured here
from the written SVG paths with Gauss-Legendre quadrature, independently of the
converter's chord table. Set ROUTE_ARROWS_EVIDENCE_DIR to also write arrows.json,
geometry-compare.json, the "svg" part of arrow-lengths.json and the "import"
part of physics-unchanged.json there.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import check_level_geometry as checker  # noqa: E402
import convert_extended_mountain_svg as conv  # noqa: E402
from import_level_svg import dumps, import_svg  # noqa: E402

LEVELS = ROOT / 'artifacts' / 'levels'
MEASUREMENTS = LEVELS / 'extended-mountain-measurements.json'
SHIPPED_SVG = LEVELS / 'extended-mountain.svg'
EVIDENCE = os.environ.get('ROUTE_ARROWS_EVIDENCE_DIR')
SVG = '{http://www.w3.org/2000/svg}'
NUM = r'-?\d+(?:\.\d+)?(?:e-?\d+)?'
EPS = 1e-2          # canvas pixels; paths are written with 3 decimals
# SVG and runtime must agree on shaft length and endpoint within this many world units (<= 1).
WORLD_TOL = 0.1


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


# Focused fixtures in world units: from/to fragment polygons and a guide cubic.
FIXTURES = {
    # G = 100: a 50-unit shaft on a 300-unit guide.
    'short': {'from': [rect(0, 0, 200, 40)], 'to': [rect(300, 0, 200, 40)],
              'guide': [(150, -11), (230, -60), (330, -60), (400, -11)]},
    # G = 1600: an 800-unit shaft on a ~2000-unit guide.
    'long': {'from': [rect(0, 0, 400, 40)], 'to': [rect(2000, 0, 400, 40)],
             'guide': [(300, -11), (900, -700), (1700, -700), (2200, -11)]},
    # G = 600 on a tightly bent guide: the arc-length parameter differs from a chord or fixed-t guess.
    'curved': {'from': [rect(0, 0, 200, 40)], 'to': [rect(800, 0, 200, 40)],
               'guide': [(100, -11), (1400, -1200), (-500, -1200), (900, -11)]},
    # G = 1000 but the guide is only ~300 long: the shaft is capped at L (t = 1).
    'capped': {'from': [rect(0, 0, 200, 40)], 'to': [rect(1200, 0, 200, 40)],
               'guide': [(150, -11), (250, -100), (350, -100), (420, -11)]},
    # Touching fragments: G = 0, zero-length shaft at the guide start.
    'touching': {'from': [rect(0, 0, 200, 40)], 'to': [rect(200, 0, 200, 40)],
                 'guide': [(150, -11), (200, -80), (260, -80), (300, -11)]},
    # All four control points equal: L = 0, no derivative, no chord; the head points +x.
    'zeroCurve': {'from': [rect(0, 0, 200, 40)], 'to': [rect(500, 0, 200, 40)],
                  'guide': [(100, -11), (100, -11), (100, -11), (100, -11)]},
    # p0 = p1 and G = 0: the derivative vanishes at t = 0, so the head follows the chord.
    'cuspStart': {'from': [rect(0, 0, 200, 40)], 'to': [rect(100, 20, 300, 40)],
                  'guide': [(100, -11), (100, -11), (300, -200), (500, -11)]},
    # A compound (two-polygon) source: G is measured to the nearer body.
    'compound': {'from': [rect(0, 0, 200, 40), rect(150, -300, 200, 40)], 'to': [rect(700, -300, 200, 40)],
                 'guide': [(250, -351), (400, -500), (600, -500), (800, -351)]},
}


def sha(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def nums(s):
    return [float(v) for v in re.findall(NUM, s)]


def close(a, b, eps=EPS):
    return all(abs(x - y) <= eps for x, y in zip(a, b)) and len(a) == len(b)


GL_X = (-0.9061798459386640, -0.5384693101056831, 0.0, 0.5384693101056831, 0.9061798459386640)
GL_W = (0.2369268850561891, 0.4786286704993665, 0.5688888888888889, 0.4786286704993665, 0.2369268850561891)


def arc_length(p, pieces=64):
    """Independent arc length of the cubic p: 5-point Gauss-Legendre on `pieces` intervals of |B'(t)|."""
    total = 0.0
    for k in range(pieces):
        a, b = k / pieces, (k + 1) / pieces
        for x, w in zip(GL_X, GL_W):
            t = (a + b) / 2 + (b - a) / 2 * x
            total += w * (b - a) / 2 * math.hypot(*conv.bezier_tangent(p, t))
    return total


def parse_arrow(g):
    path, = g.findall(f'{SVG}path')
    poly, = g.findall(f'{SVG}polygon')
    d, head = nums(path.get('d')), nums(poly.get('points'))
    return path, poly, [tuple(d[i:i + 2]) for i in range(0, 8, 2)], [tuple(head[i:i + 2]) for i in range(0, 6, 2)]


def fixture_svg(name, fx):
    """The fixture drawn by the converter's own arrow_markup (identity map: canvas = world)."""
    markup = conv.arrow_markup(name, 'A', 'B', fx['guide'], fx['from'], fx['to'], lambda p: p)
    return ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{"".join(markup)}</svg>').find(f'{SVG}g')


def finite(v):
    return all(math.isfinite(x) for x in (v if isinstance(v, (list, tuple)) else [v]))


def head_report(shaft, head, tangent):
    tip, w1, w2 = head
    base = ((w1[0] + w2[0]) / 2, (w1[1] + w2[1]) / 2)
    ax, ay = tip[0] - base[0], tip[1] - base[1]
    n = math.hypot(ax, ay)
    return {'tipEqualsShaftEnd': close(tip, shaft[-1]), 'headLength': n, 'headWidth': math.dist(w1, w2),
            'alignmentCos': (ax * tangent[0] + ay * tangent[1]) / n if n else None}


class RouteArrowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meas = json.loads(MEASUREMENTS.read_text())
        cls.rows = cls.meas['encounters']
        cls.frags = cls.meas['fragments']
        cls.by_id = {m['id']: m for m in cls.frags}
        cls.plain = conv.build(cls.meas)
        cls.text = conv.build(cls.meas, guides=True, arrows=True)
        cls.root = ET.fromstring(cls.text)
        front = cls.root.find(f'{SVG}g[@id="annotations-front"]')
        a, b, c, d, e, f = nums(front.get('transform'))
        assert b == 0 and c == 0 and a == d
        # The group maps canvas px -> world: world = a*canvas + e, so canvas = (world - e) / a.
        cls.inv_scale, cls.front = a, front
        cls.T = staticmethod(lambda p: ((p[0] - e) / a, (p[1] - f) / a))
        cls.W = staticmethod(lambda p: (p[0] * a + e, p[1] * a + f))
        cls.arrows = front.findall(f'{SVG}g[@class="transfer-arrow"]')
        cls.geo = {'T%02d' % r['number']: conv.transfer_arrow(r, cls.frags) for r in cls.rows}
        cls.lengths = {'shipped': {}, 'fixtures': {}}

    def arrow(self, tid):
        return next(g for g in self.arrows if g.get('data-transfer') == tid)

    def tangent(self, r):
        return self.geo['T%02d' % r['number']]['tangent']

    def test_one_arrow_per_transfer_in_order(self):
        self.assertEqual(len(self.rows), len(self.frags) - 1)
        self.assertGreater(len(self.rows), 0)
        self.assertEqual(len(self.arrows), len(self.rows))
        got = [(g.get('data-transfer'), g.get('data-from'), g.get('data-to')) for g in self.arrows]
        want = [('T%02d' % r['number'], r['fromFragment'], r['toFragment']) for r in self.rows]
        self.assertEqual(got, want)
        # Every fragment but the summit starts exactly one arrow; nothing starts at the summit.
        self.assertEqual(self.frags[-1]['kind'], 'summit')
        self.assertEqual([g.get('data-from') for g in self.arrows], [f['id'] for f in self.frags[:-1]])
        self.assertEqual(self.text.count('class="transfer-arrow"'), len(self.rows))

    def test_metadata_guides_match_curve(self):
        level = import_svg(self.text.encode())
        transfers = level['svgFormat']['transfers']
        self.assertEqual(len(transfers), len(self.rows))
        for t, r in zip(transfers, self.rows):
            self.assertEqual((t['id'], t['from'], t['to']), ('T%02d' % r['number'], r['fromFragment'], r['toFragment']))
            self.assertEqual(t['guide'], [list(p) for p in conv.curve(r, self.frags)])

    def test_gap_matches_independent_checker(self):
        # G from the converter's polygon_gap equals check_level_geometry's union distance and the measured gap.
        for r in self.rows:
            tid = 'T%02d' % r['number']
            d = checker.union_distance(conv.bodies(self.by_id[r['fromFragment']]), conv.bodies(self.by_id[r['toFragment']]))[0]
            self.assertAlmostEqual(self.geo[tid]['G'], d, delta=1e-6, msg=tid)
            self.assertAlmostEqual(self.geo[tid]['G'], r['distance'], delta=1e-3, msg=tid)

    def test_shipped_shaft_arc_length_is_min_half_gap_and_curve(self):
        for g, r in zip(self.arrows, self.rows):
            tid = g.get('data-transfer')
            geo = self.geo[tid]
            _, _, d, head = parse_arrow(g)
            guide = conv.curve(r, self.frags)
            full = [self.T(p) for p in guide]
            L = arc_length(guide)
            measured = arc_length([self.W(p) for p in d])
            target = min(0.5 * geo['G'], L)
            self.assertAlmostEqual(geo['L'], L, delta=0.05, msg=tid)
            self.assertAlmostEqual(measured, target, delta=WORLD_TOL, msg=tid)
            self.assertTrue(close(sum(d, ()), sum(conv.head_of(full, geo['t']), ())), tid)
            # The sub-curve traces the guide itself: at u it is the guide at t* u.
            for u in (.2, .5, .8):
                self.assertTrue(close(conv.bezier(d, u), conv.bezier(full, u * geo['t'])), tid)
            self.assertTrue(close(d[0], full[0]))
            end = self.W(d[-1])
            self.assertLess(math.dist(end, geo['endpoint']), WORLD_TOL, tid)
            self.lengths['shipped'][tid] = {
                'from': r['fromFragment'], 'to': r['toFragment'], 'G': geo['G'], 'L': L, 'target': target,
                'converterTarget': geo['target'], 't': geo['t'], 'capped': geo['capped'],
                'measuredShaftLength': measured, 'lengthError': measured - target,
                'endpoint': list(geo['endpoint']), 'svgEndpoint': list(end), 'tangent': list(geo['tangent']),
                'head': head_report(d, head, geo['tangent'])}
        # Short and long transfers really get different shafts.
        shafts = [v['target'] for v in self.lengths['shipped'].values()]
        self.assertGreater(max(shafts), 2 * min(shafts))

    def test_fixture_arrows(self):
        for name, fx in FIXTURES.items():
            geo = conv.arrow_geometry(fx['guide'], fx['from'], fx['to'])
            g = fixture_svg(name, fx)
            _, _, d, head = parse_arrow(g)
            G = checker.union_distance([list(p) for p in fx['from']], [list(p) for p in fx['to']])[0]
            L = arc_length(fx['guide'])
            target = min(0.5 * G, L)
            measured = arc_length(d)
            values = [geo['G'], geo['L'], geo['target'], geo['t'], *geo['endpoint'], *geo['tangent'], measured, *sum(d, ()), *sum(head, ())]
            self.assertTrue(finite(values), name)
            self.assertAlmostEqual(geo['G'], G, delta=1e-9, msg=name)
            self.assertAlmostEqual(geo['L'], L, delta=0.05, msg=name)
            self.assertAlmostEqual(measured, target, delta=WORLD_TOL, msg=name)
            self.assertAlmostEqual(math.hypot(*geo['tangent']), 1, delta=1e-12, msg=name)
            rep = head_report(d, head, geo['tangent'])
            self.assertTrue(rep['tipEqualsShaftEnd'], name)
            self.assertAlmostEqual(rep['headLength'], conv.ARROW_HEAD, delta=2e-3, msg=name)
            self.assertAlmostEqual(rep['headWidth'], conv.ARROW_HEAD, delta=2e-3, msg=name)
            self.assertGreater(rep['alignmentCos'], 1 - 1e-6, name)
            self.lengths['fixtures'][name] = {
                'G': G, 'L': L, 'target': target, 'converterTarget': geo['target'], 't': geo['t'], 'capped': geo['capped'],
                'measuredShaftLength': measured, 'lengthError': measured - target, 'endpoint': list(geo['endpoint']),
                'svgEndpoint': list(d[-1]), 'tangent': list(geo['tangent']), 'head': rep, 'finite': True}
        fx = self.lengths['fixtures']
        self.assertEqual((fx['short']['G'], fx['long']['G'], fx['curved']['G'], fx['capped']['G']), (100, 1600, 600, 1000))
        self.assertAlmostEqual(fx['short']['target'], 50, delta=1e-9)
        self.assertAlmostEqual(fx['long']['target'], 800, delta=1e-9)
        self.assertTrue(fx['capped']['capped'])
        self.assertEqual(fx['capped']['t'], 1.0)
        self.assertAlmostEqual(fx['capped']['measuredShaftLength'], fx['capped']['L'], delta=WORLD_TOL)
        self.assertFalse(fx['curved']['capped'])
        # On the bent guide, a parameter proportional to the length fraction would be far off.
        self.assertGreater(abs(fx['curved']['t'] - fx['curved']['target'] / fx['curved']['L']), .05)
        for name in ('touching', 'zeroCurve', 'cuspStart'):
            self.assertEqual((fx[name]['target'], fx[name]['t'], fx[name]['measuredShaftLength']), (0, 0, 0), name)
        self.assertEqual(fx['zeroCurve']['L'], 0)
        self.assertEqual(fx['zeroCurve']['tangent'], [1.0, 0.0])
        self.assertGreater(fx['cuspStart']['tangent'][0], .9)          # the chord, rightward
        self.assertAlmostEqual(fx['compound']['G'], 350, delta=1e-9)  # nearer (upper) source body

    def test_arrowhead_follows_forward_derivative(self):
        for g, r in zip(self.arrows, self.rows):
            _, _, d, head = parse_arrow(g)
            geo = self.geo[g.get('data-transfer')]
            rep = head_report(d, head, conv.bezier_tangent([self.T(p) for p in conv.curve(r, self.frags)], geo['t']))
            self.assertTrue(rep['tipEqualsShaftEnd'])
            self.assertGreater(rep['alignmentCos'], 1 - 1e-6, g.get('data-transfer'))
            self.assertAlmostEqual(rep['headLength'], conv.ARROW_HEAD, delta=2e-3)
            self.assertAlmostEqual(rep['headWidth'], conv.ARROW_HEAD, delta=2e-3)

    def test_tangents_follow_transfer_direction(self):
        # Every arrow points the way its transfer goes horizontally; the route has both directions.
        signs = set()
        for r in self.rows:
            dx = r['flight'][1][0] - r['flight'][0][0]
            if abs(dx) > 200:
                self.assertEqual(math.copysign(1, self.tangent(r)[0]), math.copysign(1, dx), r['number'])
                signs.add(math.copysign(1, dx))
        self.assertEqual(signs, {-1.0, 1.0})
        self.assertGreater(self.tangent(self.rows[0])[0], 0)       # opening: rightward

    def test_style_and_displayed_pixel_size(self):
        w = float(self.root.get('width'))
        vb = nums(self.root.get('viewBox'))
        displayed = self.inv_scale * (w / vb[2])            # annotation units -> displayed pixels
        self.assertAlmostEqual(displayed, 1.0, places=9)
        for g in self.arrows:
            path, poly, _, _ = parse_arrow(g)
            self.assertEqual(g.get('opacity'), '0.4')
            self.assertEqual((path.get('stroke'), path.get('stroke-width'), path.get('fill')), ('#8bdde8', '1.5', 'none'))
            self.assertEqual(poly.get('fill'), '#8bdde8')
            self.assertIsNone(path.get('marker-end'))
            self.assertIsNone(path.get('stroke-dasharray'))

    def test_full_trajectories_and_labels_unchanged(self):
        stripped = re.sub(r'<g id="arrow-T\d+" class="transfer-arrow".*?\n</g>\n', '', self.text, flags=re.S)
        stripped = re.sub(r' guide="[^"]*"', '', stripped)
        self.assertEqual(stripped, self.plain)
        routes = [p for p in self.front.iter(f'{SVG}path') if p.get('stroke-dasharray') == '8 6']
        self.assertEqual(len(routes), len(self.rows))
        self.assertTrue(all(p.get('stroke') == '#eaf3ed' and p.get('marker-end') == 'url(#route)' for p in routes))
        self.assertEqual(self.text.count('clear gap</text>'), len(self.rows))

    def test_collision_geometry_identical_with_and_without_arrows(self):
        with_a = [dumps(import_svg(self.text.encode())) for _ in range(2)]
        without = [dumps(import_svg(self.plain.encode())) for _ in range(2)]
        self.assertEqual(with_a[0], with_a[1])
        self.assertEqual(without[0], without[1])
        a, b = json.loads(with_a[0]), json.loads(without[0])
        keys = ('layoutId', 'bounds', 'spawn', 'finish', 'elements', 'movers', 'sections', 'encounters')
        same = {k: a[k] == b[k] for k in keys}
        same['fragments'] = a['svgFormat']['fragments'] == b['svgFormat']['fragments']
        for t in a['svgFormat']['transfers']:
            t.pop('guide')
        same['transfersWithoutGuide'] = a['svgFormat']['transfers'] == b['svgFormat']['transfers']
        self.assertTrue(all(same.values()), same)
        geo = lambda s: re.search(r'<g id="geometry".*?\n</g>\n</g>', s, re.S).group(0)
        self.assertEqual(geo(self.text), geo(self.plain))
        if EVIDENCE:
            Path(EVIDENCE, 'geometry-compare.json').write_text(json.dumps({
                'importsWithArrows': [sha(x) for x in with_a], 'importsWithout': [sha(x) for x in without],
                'elementsSha256': {'withArrows': sha(json.dumps(a['elements'])), 'without': sha(json.dumps(b['elements']))},
                'elementCount': len(a['elements']), 'equal': same,
                'geometryLayerSha256': {'withArrows': sha(geo(self.text)), 'without': sha(geo(self.plain))}}, indent=1) + '\n')

    def test_shipped_regeneration_is_byte_identical(self):
        """Since TASK-677 the shipped SVG is the current generator's output: regeneration is byte-identical
        (distance-based arrows included), and the arrows/guides carry no collision/role/contact data."""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source',
                            str(ROOT / 'artifacts/level/extended-mountain-measurements.json'), '--output-dir', tmp,
                            '--guidelines', str(LEVELS / 'level-guidelines.md')], check=True, capture_output=True)
            new = Path(tmp, 'extended-mountain.svg').read_text()
            new_meas = Path(tmp, 'extended-mountain-measurements.json').read_bytes()
        old = SHIPPED_SVG.read_text()
        strip = lambda s: re.sub(r'<g id="arrow-T\d+" class="transfer-arrow".*?\n</g>\n', '', s, flags=re.S)
        self.assertEqual(new_meas, MEASUREMENTS.read_bytes())
        self.assertEqual(new, old)
        imports = {'regenerated': dumps(import_svg(new.encode())), 'shipped': dumps(import_svg(old.encode())),
                   'noArrowsNoGuides': dumps(import_svg(strip(re.sub(r' guide="[^"]*"', '', old)).encode()))}
        self.assertEqual(imports['regenerated'], imports['shipped'])
        self.assertEqual(imports['shipped'], (LEVELS / 'extended-mountain.level.json').read_text())
        a, c = json.loads(imports['shipped']), json.loads(imports['noArrowsNoGuides'])
        elements = lambda lv: [(e['id'], e['role'], e['grapplable'], e['x'], e['y'], e['points']) for e in lv['elements']]
        same = {'elementsCollisionRoleGrapplable': elements(a) == elements(c),
                **{k: a[k] == c[k] for k in ('layoutId', 'bounds', 'spawn', 'finish', 'movers', 'sections', 'encounters')},
                'fragments': a['svgFormat']['fragments'] == c['svgFormat']['fragments'],
                'transfersWithoutGuide': [{k: v for k, v in t.items() if k != 'guide'} for t in a['svgFormat']['transfers']]
                == c['svgFormat']['transfers']}
        self.assertTrue(all(same.values()), same)
        groups = re.findall(r'<g id="arrow-T\d+".*?\n</g>', old, re.S)
        self.assertEqual(len(groups), len(a['svgFormat']['transfers']))
        if EVIDENCE:
            path = Path(EVIDENCE, 'physics-unchanged.json')
            prior = json.loads(path.read_text()) if path.exists() else {}
            prior['import'] = {
                'command': 'tools/retune_extended_level.py --source artifacts/level/extended-mountain-measurements.json '
                           '--output-dir <tmp> --guidelines artifacts/levels/level-guidelines.md',
                'shippedSvgSha256': sha(old), 'regeneratedSvgSha256': sha(new), 'measurementsByteIdentical': True,
                'svgByteIdentical': True, 'arrowGroups': len(groups),
                'importSha256': {k: sha(v) for k, v in imports.items()},
                'elementCount': len(a['elements']), 'versusNoAnnotations': same}
            path.write_text(json.dumps(prior, indent=1, sort_keys=True) + '\n')

    def test_cli_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = []
            for i in range(2):
                dst = Path(tmp, f'run{i}.svg')
                subprocess.run([sys.executable, str(TOOLS / 'convert_extended_mountain_svg.py'), '--measurements', str(MEASUREMENTS),
                                '--output', str(dst), '--arrows'], check=True, capture_output=True)
                out.append(dst.read_text())
            self.assertEqual(out[0], out[1])
            self.assertEqual(out[0], self.text)
            self.assertEqual(conv.build(self.meas, guides=True, arrows=True), self.text)

    @classmethod
    def tearDownClass(cls):
        if not EVIDENCE:
            return
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        records = []
        level = json.loads(dumps(import_svg(cls.text.encode())))
        guides = {t['id']: t['guide'] for t in level['svgFormat']['transfers']}
        for g, r in zip(cls.arrows, cls.rows):
            _, _, d, head = parse_arrow(g)
            tid = g.get('data-transfer')
            records.append({'id': tid, 'from': g.get('data-from'), 'to': g.get('data-to'),
                            'targetKind': cls.frags[r['number']]['kind'], 'metadataGuide': guides[tid],
                            'arrowPathCanvas': [[round(v, 3) for v in p] for p in d], 't': cls.geo[tid]['t'],
                            'head': head_report(d, head, cls.geo[tid]['tangent'])})
        Path(EVIDENCE, 'arrows.json').write_text(json.dumps({
            'measurements': str(MEASUREMENTS.relative_to(ROOT)), 'fragments': len(cls.frags), 'transfers': len(cls.rows),
            'arrows': len(cls.arrows), 'style': {'color': conv.ARROW_COLOR, 'opacity': conv.ARROW_OPACITY,
                                                 'strokeDisplayedPx': conv.ARROW_STROKE, 'headDisplayedPx': conv.ARROW_HEAD},
            'svgSha256': sha(cls.text), 'records': records}, separators=(',', ':')) + '\n')
        path = Path(EVIDENCE, 'arrow-lengths.json')
        prior = json.loads(path.read_text()) if path.exists() else {}
        errs = [abs(v['lengthError']) for part in cls.lengths.values() for v in part.values()]
        prior['svg'] = {
            'rule': 'shaft arc length = min(0.5 * G, L) in world units; G = minimum edge-to-edge gap between the complete '
                    'from/to fragment polygons, L = guide arc length',
            'measurement': 'shaft arc length re-measured from the written SVG path (canvas -> world) with 5-point '
                           'Gauss-Legendre on 64 intervals; G re-measured with check_level_geometry.union_distance',
            'toleranceWorldUnits': WORLD_TOL, 'maxAbsLengthError': max(errs) if errs else None,
            'shippedCount': len(cls.lengths['shipped']), 'fixtureCount': len(cls.lengths['fixtures']),
            'measurementsSha256': sha(MEASUREMENTS.read_bytes()),
            'converterSha256': sha((TOOLS / 'convert_extended_mountain_svg.py').read_bytes()),
            'fixtures': {k: {'from': v['from'], 'to': v['to'], 'guide': v['guide']} for k, v in FIXTURES.items()},
            **cls.lengths}
        path.write_text(json.dumps(prior, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    unittest.main()
