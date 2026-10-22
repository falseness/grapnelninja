"""Tests for the minimum interior-angle helper in tools/check_level_geometry.py.

    python3 -m unittest discover -s tools -p test_level_angles.py -v
    python3 tools/test_level_angles.py --write ANGLES.json   # fixture report

Expected angles come from the fixture construction (closed-form trigonometry),
never from the helper under test.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from check_level_geometry import (ANGLE_TOL_DEG, MIN_INTERIOR_ANGLE, AngleError, angle_report,  # noqa: E402
                                  interior_angles)

EXPECT_TOL = 1e-9


def isosceles(apex_deg, leg=1000.0, x=5000.0, y=-3000.0):
    """Apex at (x, y), legs symmetric about +x: angles [apex, base, base]."""
    h = math.radians(apex_deg / 2)
    poly = [(x, y), (x + leg * math.cos(h), y - leg * math.sin(h)), (x + leg * math.cos(h), y + leg * math.sin(h))]
    base = (180.0 - apex_deg) / 2
    return poly, [apex_deg, base, base]


def chevron():
    """Arrowhead (0,0) (100,50) (0,100) (30,50); the notch vertex 3 is reflex."""
    tip = 2 * math.degrees(math.atan(50 / 100))
    notch = 360 - 2 * math.degrees(math.atan(50 / 30))
    back = math.degrees(math.atan(50 / 30)) - math.degrees(math.atan(50 / 100))
    return [(0, 0), (100, 50), (0, 100), (30, 50)], [back, tip, back, notch]


def narrow_notch():
    """Square with a 10-degree V cut into its top: the notch bottom is 350 interior."""
    half = 5.0
    depth = 50 / math.tan(math.radians(half))
    poly = [(0, 0), (1000, 0), (1000, 1000), (550, 1000), (500, 1000 - depth), (450, 1000), (0, 1000)]
    rim = 90 + half
    return poly, [90, 90, 90, rim, 360 - 2 * half, rim, 90]


def l_shape():
    poly = [(0, 0), (200, 0), (200, 100), (100, 100), (100, 300), (0, 300)]
    return poly, [90, 90, 90, 270, 90, 90]


def rotate(poly, deg, cx=0.0, cy=0.0):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in poly]


def reverse(poly, expected):
    """Reverse winding; vertex i maps to n-1-i."""
    return list(reversed(poly)), list(reversed(expected))


def valid_fixtures():
    sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
    out = [('square', sq, [90] * 4)]
    out.append(('square_reversed',) + reverse(sq, [90] * 4))
    out.append(('l_shape_concave', *l_shape()))
    out.append(('l_shape_concave_reversed',) + reverse(*l_shape()))
    out.append(('chevron_concave', *chevron()))
    out.append(('chevron_concave_reversed',) + reverse(*chevron()))
    out.append(('narrow_notch_reflex_350', *narrow_notch()))
    out.append(('narrow_notch_reflex_350_reversed',) + reverse(*narrow_notch()))
    for apex, label in ((20.0, 'exact_20'), (19.9, '19_9'), (20.1, '20_1')):
        poly, exp = isosceles(apex)
        out.append(('apex_%s' % label, poly, exp))
        out.append(('apex_%s_reversed' % label,) + reverse(poly, exp))
    poly, exp = isosceles(20.0, leg=2537.25, x=0, y=0)
    out.append(('apex_exact_20_rotated_37', rotate(poly, 37.0, 813.5, -91.25), exp))
    out.append(('straight_vertex', [(0, 0), (50, 0), (100, 0), (100, 100), (0, 100)], [90, 180, 90, 90, 90]))
    return out


def degenerate_fixtures():
    return [
        ('repeated_adjacent_vertex', [(0, 0), (100, 0), (100, 0), (100, 100), (0, 100)], 1),
        ('closing_vertex_repeated', [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)], 4),
        ('fold_back_spike', [(0, 0), (100, 0), (100, 100), (50, 100), (50, 150), (50, 100), (0, 100)], 4),
        ('collinear_fold_zero_area', [(0, 0), (100, 0), (200, 0), (100, 0.0)], None),
        ('collinear_zero_area', [(0, 0), (50, 0), (100, 0)], None),
        ('two_vertices', [(0, 0), (100, 0)], None),
    ]


def build_report():
    cases = []
    for name, poly, expected in valid_fixtures():
        rep = angle_report(poly)
        verts = []
        for v, exp in zip(rep['vertices'], expected):
            verts.append({'vertex': v['vertex'], 'expected': round(exp, 12), 'measured': round(v['angle'], 12),
                          'error': abs(v['angle'] - exp), 'kind': v['kind'],
                          'result': 'accept' if v['ok'] else 'reject'})
        cases.append({'name': name, 'points': [list(p) for p in poly], 'windingYUp':
                      'ccw' if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])) > 0 else 'cw',
                      'result': 'accept' if rep['ok'] else 'reject', 'vertices': verts,
                      'expectedResult': 'accept' if min(expected) >= MIN_INTERIOR_ANGLE - ANGLE_TOL_DEG else 'reject'})
    for name, poly, vertex in degenerate_fixtures():
        rep = angle_report(poly)
        cases.append({'name': name, 'points': [list(p) for p in poly], 'result': 'accept' if rep['ok'] else 'reject',
                      'expectedResult': 'reject', 'error': rep['error'], 'expectedErrorVertex': vertex})
    return {'minimumDeg': MIN_INTERIOR_ANGLE, 'toleranceDeg': ANGLE_TOL_DEG,
            'tolerancePolicy': 'accept when measured >= 20 - toleranceDeg; toleranceDeg <= 1e-6',
            'interiorConvention': 'interior side from signed-area winding; concave vertices report reflex (>180)',
            'cases': cases}


class InteriorAngleTests(unittest.TestCase):
    def test_tolerance_is_documented_and_small(self):
        self.assertGreater(ANGLE_TOL_DEG, 0)
        self.assertLessEqual(ANGLE_TOL_DEG, 1e-6)
        self.assertEqual(MIN_INTERIOR_ANGLE, 20.0)

    def test_measured_matches_analytic_expectation(self):
        fixtures = valid_fixtures()
        self.assertGreaterEqual(len(fixtures), 15)
        for name, poly, expected in fixtures:
            with self.subTest(name=name):
                got = interior_angles(poly)
                self.assertEqual(len(got), len(expected))
                for g, e in zip(got, expected):
                    self.assertAlmostEqual(g, e, delta=EXPECT_TOL)
                self.assertAlmostEqual(sum(got), (len(poly) - 2) * 180, delta=1e-8)

    def test_winding_reversal_invariance(self):
        for name, poly, _ in valid_fixtures():
            with self.subTest(name=name):
                fwd, back = interior_angles(poly), interior_angles(list(reversed(poly)))
                for g, b in zip(fwd, reversed(back)):
                    self.assertAlmostEqual(g, b, delta=EXPECT_TOL)
                self.assertEqual(angle_report(poly)['ok'], angle_report(list(reversed(poly)))['ok'])

    def test_concave_vertices_use_reflex_angle(self):
        for build, idx, exp in ((l_shape, 3, 270), (chevron, 3, chevron()[1][3]), (narrow_notch, 4, 350)):
            poly, _ = build()
            for p in (poly, list(reversed(poly))):
                with self.subTest(fixture=build.__name__, winding='reversed' if p is not poly else 'forward'):
                    j = idx if p is poly else len(poly) - 1 - idx
                    rep = angle_report(p)
                    self.assertEqual(rep['vertices'][j]['kind'], 'reflex')
                    self.assertAlmostEqual(rep['vertices'][j]['angle'], exp, delta=EXPECT_TOL)
                    self.assertTrue(rep['vertices'][j]['ok'])
        # The 350-degree notch has a 10-degree exterior angle; it must still pass.
        self.assertTrue(angle_report(narrow_notch()[0])['ok'])

    def test_exact_20_accepted(self):
        for name in ('apex_exact_20', 'apex_exact_20_reversed', 'apex_exact_20_rotated_37'):
            poly = dict((n, p) for n, p, _ in valid_fixtures())[name]
            with self.subTest(name=name):
                self.assertTrue(angle_report(poly)['ok'])

    def test_19_9_rejected_at_apex_only(self):
        for poly, apex in ((isosceles(19.9)[0], 0), reverse(*isosceles(19.9))[:1] + (2,)):
            rep = angle_report(poly)
            self.assertFalse(rep['ok'])
            self.assertEqual([v['vertex'] for v in rep['vertices'] if not v['ok']], [apex])

    def test_20_1_accepted(self):
        self.assertTrue(angle_report(isosceles(20.1)[0])['ok'])
        self.assertTrue(angle_report(list(reversed(isosceles(20.1)[0])))['ok'])

    def test_just_below_tolerance_rejected(self):
        poly, _ = isosceles(20.0 - 1e-6)
        self.assertFalse(angle_report(poly)['ok'])

    def test_repeated_adjacent_vertices_rejected(self):
        for name, poly, vertex in degenerate_fixtures():
            with self.subTest(name=name):
                with self.assertRaises(AngleError) as ctx:
                    interior_angles(poly)
                self.assertEqual(ctx.exception.vertex, vertex)
                rep = angle_report(poly)
                self.assertFalse(rep['ok'])
                self.assertIsNotNone(rep['error'])

    def test_report_matches_expectations(self):
        report = build_report()
        self.assertEqual(len(report['cases']), len(valid_fixtures()) + len(degenerate_fixtures()))
        for case in report['cases']:
            with self.subTest(name=case['name']):
                self.assertEqual(case['result'], case['expectedResult'])
                for v in case.get('vertices', []):
                    self.assertLessEqual(v['error'], EXPECT_TOL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', required=True)
    args = parser.parse_args()
    Path(args.write).write_text(json.dumps(build_report(), indent=1) + '\n')


if __name__ == '__main__':
    main()
