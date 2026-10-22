"""Tests for the short transfer direction arrows in tools/convert_extended_mountain_svg.py.

    python3 -m unittest discover -s tools -p test_level_route_arrows.py -v

Uses the shipped v6 measurements (31 panels, 30 transfers). Set
ROUTE_ARROWS_EVIDENCE_DIR to also write arrows.json and geometry-compare.json there.
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

import convert_extended_mountain_svg as conv  # noqa: E402
from import_level_svg import dumps, import_svg  # noqa: E402

MEASUREMENTS = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'
EVIDENCE = os.environ.get('ROUTE_ARROWS_EVIDENCE_DIR')
SVG = '{http://www.w3.org/2000/svg}'
NUM = r'-?\d+(?:\.\d+)?(?:e-?\d+)?'
EPS = 1e-2          # canvas pixels; paths are written with 3 decimals


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def nums(s):
    return [float(v) for v in re.findall(NUM, s)]


def close(a, b, eps=EPS):
    return all(abs(x - y) <= eps for x, y in zip(a, b)) and len(a) == len(b)


class RouteArrowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meas = json.loads(MEASUREMENTS.read_text())
        cls.rows = cls.meas['encounters']
        cls.frags = cls.meas['fragments']
        cls.plain = conv.build(cls.meas)
        cls.text = conv.build(cls.meas, guides=True, arrows=True)
        cls.root = ET.fromstring(cls.text)
        front = cls.root.find(f'{SVG}g[@id="annotations-front"]')
        a, b, c, d, e, f = nums(front.get('transform'))
        assert b == 0 and c == 0 and a == d
        # The group maps canvas px -> world: world = a*canvas + e, so canvas = (world - e) / a.
        cls.inv_scale, cls.front = a, front
        cls.T = staticmethod(lambda p: ((p[0] - e) / a, (p[1] - f) / a))
        cls.arrows = front.findall(f'{SVG}g[@class="transfer-arrow"]')

    def arrow(self, tid):
        return next(g for g in self.arrows if g.get('data-transfer') == tid)

    def parts(self, g):
        path, = g.findall(f'{SVG}path')
        poly, = g.findall(f'{SVG}polygon')
        d = nums(path.get('d'))
        head = nums(poly.get('points'))
        return path, poly, [tuple(d[i:i + 2]) for i in range(0, 8, 2)], [tuple(head[i:i + 2]) for i in range(0, 6, 2)]

    def tangent(self, r):
        return conv.bezier_tangent([self.T(p) for p in conv.curve(r, self.frags)], conv.ARROW_T)

    def test_one_arrow_per_transfer_in_order(self):
        self.assertEqual((len(self.frags), len(self.rows)), (31, 30))
        self.assertEqual(len(self.arrows), 30)
        got = [(g.get('data-transfer'), g.get('data-from'), g.get('data-to')) for g in self.arrows]
        want = [('T%02d' % r['number'], r['fromFragment'], r['toFragment']) for r in self.rows]
        self.assertEqual(got, want)
        # Every fragment but the summit starts exactly one arrow; nothing starts at the summit.
        self.assertEqual(self.frags[-1]['kind'], 'summit')
        self.assertEqual([g.get('data-from') for g in self.arrows], [f['id'] for f in self.frags[:-1]])
        self.assertNotIn(self.frags[-1]['id'], [g.get('data-from') for g in self.arrows])
        self.assertEqual(self.text.count('class="transfer-arrow"'), 30)

    def test_metadata_guides_match_curve(self):
        level = import_svg(self.text.encode())
        transfers = level['svgFormat']['transfers']
        self.assertEqual(len(transfers), 30)
        for t, r in zip(transfers, self.rows):
            self.assertEqual((t['id'], t['from'], t['to']), ('T%02d' % r['number'], r['fromFragment'], r['toFragment']))
            self.assertEqual(t['guide'], [list(p) for p in conv.curve(r, self.frags)])

    def test_arrow_is_first_quarter_of_same_cubic(self):
        for g, r in zip(self.arrows, self.rows):
            _, _, d, _ = self.parts(g)
            full = [self.T(p) for p in conv.curve(r, self.frags)]
            self.assertTrue(close(sum(d, ()), sum(conv.head_of(full, .25), ())), g.get('data-transfer'))
            self.assertTrue(close(d[0], full[0]))
            self.assertTrue(close(d[-1], conv.bezier(full, .25)))
            # The sub-curve evaluated at u traces the full curve at t = u / 4.
            for u in (.2, .5, .8):
                self.assertTrue(close(conv.bezier(d, u), conv.bezier(full, u * .25)))

    def test_arrowhead_follows_forward_derivative(self):
        for g, r in zip(self.arrows, self.rows):
            _, _, d, head = self.parts(g)
            tip, w1, w2 = head
            self.assertTrue(close(tip, d[-1]))
            base = ((w1[0] + w2[0]) / 2, (w1[1] + w2[1]) / 2)
            ax, ay = tip[0] - base[0], tip[1] - base[1]
            tx, ty = self.tangent(r)
            cos = (ax * tx + ay * ty) / math.hypot(ax, ay) / math.hypot(tx, ty)
            self.assertGreater(cos, 1 - 1e-6, g.get('data-transfer'))
            self.assertAlmostEqual(math.hypot(ax, ay), conv.ARROW_HEAD, delta=2e-3)
            self.assertAlmostEqual(math.dist(w1, w2), conv.ARROW_HEAD, delta=2e-3)

    def test_rightward_leftward_upward_and_descending_tangents(self):
        by = {'T%02d' % r['number']: r for r in self.rows}
        right, left, desc = self.tangent(by['T01']), self.tangent(by['T08']), self.tangent(by['T18'])
        self.assertGreater(right[0], 0)                      # opening: rightward
        self.assertLess(right[1], 0)                         # and climbing (screen y up)
        self.assertLess(left[0], 0)                          # T08 runs leftward
        self.assertGreater(desc[0], 0)                       # T18 descends rightward onto a bounce
        self.assertGreater(desc[1], 0)
        self.assertEqual(self.frags[18]['kind'], 'bounce')
        # Every arrow points the way its transfer goes horizontally.
        for r in self.rows:
            dx = r['flight'][1][0] - r['flight'][0][0]
            if abs(dx) > 200:
                self.assertEqual(math.copysign(1, self.tangent(r)[0]), math.copysign(1, dx), r['number'])

    def test_style_and_displayed_pixel_size(self):
        w = float(self.root.get('width'))
        vb = nums(self.root.get('viewBox'))
        displayed = self.inv_scale * (w / vb[2])            # annotation units -> displayed pixels
        self.assertAlmostEqual(displayed, 1.0, places=9)
        for g in self.arrows:
            path, poly, _, _ = self.parts(g)
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
        self.assertEqual(len(routes), 30)
        self.assertTrue(all(p.get('stroke') == '#eaf3ed' and p.get('marker-end') == 'url(#route)' for p in routes))
        self.assertEqual(self.text.count('clear gap</text>'), 30)

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
        records = []
        level = json.loads(dumps(import_svg(cls.text.encode())))
        guides = {t['id']: t['guide'] for t in level['svgFormat']['transfers']}
        self = cls('test_one_arrow_per_transfer_in_order')
        for g, r in zip(cls.arrows, cls.rows):
            _, _, d, head = self.parts(g)
            tid = g.get('data-transfer')
            full = [cls.T(p) for p in conv.curve(r, cls.frags)]
            tx, ty = self.tangent(r)
            base = ((head[1][0] + head[2][0]) / 2, (head[1][1] + head[2][1]) / 2)
            ax, ay = head[0][0] - base[0], head[0][1] - base[1]
            records.append({
                'id': tid, 'from': g.get('data-from'), 'to': g.get('data-to'),
                'expectedFrom': r['fromFragment'], 'expectedTo': r['toFragment'], 'targetKind': cls.frags[r['number']]['kind'],
                'metadataGuide': guides[tid], 'metadataEqualsCurve': guides[tid] == [list(p) for p in conv.curve(r, cls.frags)],
                'arrowPathCanvas': [[round(v, 3) for v in p] for p in d],
                'arrowPathIsCurveT0to025': close(sum(d, ()), sum(conv.head_of(full, .25), ())),
                'tangentAt025Canvas': [round(tx, 3), round(ty, 3)],
                'headAxisCanvas': [round(ax, 4), round(ay, 4)],
                'headAlignmentCos': round((ax * tx + ay * ty) / math.hypot(ax, ay) / math.hypot(tx, ty), 9),
                'headLengthPx': round(math.hypot(ax, ay), 4)})
        Path(EVIDENCE, 'arrows.json').write_text(json.dumps({
            'measurements': str(MEASUREMENTS.relative_to(ROOT)), 'fragments': len(cls.frags), 'transfers': len(cls.rows),
            'arrows': len(cls.arrows), 'finalPanel': cls.frags[-1]['id'],
            'arrowsFromFinalPanel': sum(g.get('data-from') == cls.frags[-1]['id'] for g in cls.arrows),
            'style': {'color': conv.ARROW_COLOR, 'opacity': conv.ARROW_OPACITY, 'strokeDisplayedPx': conv.ARROW_STROKE,
                      'headDisplayedPx': conv.ARROW_HEAD, 'annotationToDisplayScale': cls.inv_scale * float(cls.root.get('width')) / nums(cls.root.get('viewBox'))[2]},
            'svgSha256': sha(cls.text), 'records': records}, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    unittest.main()
