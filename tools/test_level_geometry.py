"""Tests for tools/check_level_geometry.py (independent level geometry checks).

    python3 -m unittest discover -s tools -p test_level_geometry.py -v
"""
import copy
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from check_level_geometry import axis_rect, check, inside, polygon_distance, union_distance  # noqa: E402
from import_level_svg import import_svg  # noqa: E402

CHECKER = TOOLS / 'check_level_geometry.py'
EXTENDED = ROOT / 'artifacts' / 'level' / 'extended-mountain.import.svg'
REFERENCE = ROOT / 'artifacts' / 'level' / 'extended-mountain-measurements.json'
SVG_TEXT = EXTENDED.read_text()
REFERENCE_DATA = json.loads(REFERENCE.read_text())


def square(x, y, size=10):
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


def translate_fragment(svg, fid, dx, dy):
    """Move every polygon of fragment fid in the SVG text."""
    def move(m):
        n = [float(v) for v in m.group(2).replace(',', ' ').split()]
        pts = ' '.join('%r,%r' % (x + dx, y + dy) for x, y in zip(n[0::2], n[1::2]))
        return m.group(1) + pts + '"'
    out, count = re.subn(r'(<polygon id="%s-body\d+" points=")([^"]*)"' % re.escape(fid), move, svg)
    assert count, fid
    return out


def translate_reference(reference, fid, dx, dy):
    ref = copy.deepcopy(reference)
    for f in ref['fragments']:
        if f['id'] == fid:
            f['x'] += dx
            f['y'] += dy
    return ref


def run_check(svg=SVG_TEXT, reference=REFERENCE_DATA, level=None):
    if level is None:
        level = import_svg(svg.encode())
    return check(level, svg.encode(), reference)


def messages(report, needle):
    return [m for m in report['failureMessages'] if needle in m]


def shortcuts(report, pair):
    return [m for m in messages(report, 'pair %s:' % pair) if 'grapple shortcut' in m]


class PolygonDistanceTests(unittest.TestCase):
    def test_separated_axis_gap(self):
        d, witness, relation = polygon_distance(square(0, 0), square(30, 0))
        self.assertEqual((d, relation), (20.0, 'separated'))
        self.assertEqual(witness[0][0], 10)
        self.assertEqual(witness[1][0], 30)

    def test_separated_diagonal_corner(self):
        d, _, relation = polygon_distance(square(0, 0), square(13, 14))
        self.assertAlmostEqual(d, math.hypot(3, 4), places=12)
        self.assertEqual(relation, 'separated')

    def test_touching_edge_and_corner(self):
        self.assertEqual(polygon_distance(square(0, 0), square(10, 0))[0], 0.0)
        self.assertEqual(polygon_distance(square(0, 0), square(10, 3))[0], 0.0)
        self.assertEqual(polygon_distance(square(0, 0), square(10, 10))[0], 0.0)

    def test_overlapping(self):
        d, _, relation = polygon_distance(square(0, 0), square(5, 5))
        self.assertEqual((d, relation), (0.0, 'intersect'))

    def test_contained_both_orders(self):
        big, small = square(0, 0, 100), square(40, 40, 5)
        self.assertEqual(polygon_distance(small, big)[:3:2], (0.0, 'contained'))
        self.assertEqual(polygon_distance(big, small)[:3:2], (0.0, 'contains'))
        # Edge-to-edge distance alone would report 40, not 0.
        self.assertEqual(polygon_distance(small, big)[0], 0.0)

    def test_concave_notch_is_not_treated_as_hull(self):
        u = [(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10), (10, 30), (0, 30)]
        box = [(13, 20), (17, 20), (17, 25), (13, 25)]  # inside the convex hull, outside the polygon
        self.assertFalse(inside((15, 22), u))
        self.assertTrue(inside((5, 5), u))
        d, _, relation = polygon_distance(box, u)
        self.assertAlmostEqual(d, 3.0, places=12)
        self.assertEqual(relation, 'separated')
        self.assertEqual(polygon_distance(square(5, 15, 2), u)[0], 0.0)  # inside the left arm

    def test_compound_fragment_is_union(self):
        a = [square(0, 0), square(0, -100)]
        b = [square(40, -100)]
        d, _, _, bodies = union_distance(a, b)
        self.assertEqual((d, bodies), (30.0, (1, 0)))
        d, _, relation, _ = union_distance(a + [square(35, -95)], b)
        self.assertEqual((d, relation), (0.0, 'intersect'))

    def test_axis_rect(self):
        self.assertEqual(axis_rect(square(1, 2, 5)), (1, 2, 5, 5))
        self.assertIsNone(axis_rect([(0, 0), (10, 1), (10, 11), (0, 10)]))
        self.assertIsNone(axis_rect([(0, 0), (10, 0), (10, 10)]))


class ExtendedLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_check()

    def test_historical_level_rejected_by_new_yellow_clearance(self):
        s = self.report['summary']
        self.assertTrue(self.report['failureMessages'])
        self.assertTrue(all('solid clearance' in m for m in self.report['failureMessages']))
        self.assertEqual((s['transfers'], s['transfersPass']), (24, 24))
        self.assertEqual((s['fragmentPairs'], s['pairsPass']), (300, 300))
        self.assertEqual(s['dragZones'], 6)
        self.assertLess(s['dragZonesPass'], 6)
        self.assertLessEqual(s['maxTransferPercentError'], 0.01)
        self.assertGreater(s['minPairClearanceMinusDiameter'], 540)
        self.assertGreaterEqual(s['minDragSolidClearance'], 540)
        self.assertLessEqual(s['maxFragmentCoordError'], 0.01)

    def test_reference_cannot_weaken_yellow_clearance(self):
        reference=copy.deepcopy(REFERENCE_DATA)
        for band in reference['yellowBands']:
            band['minimumSolidClearance']=80
        report=run_check(reference=reference)
        self.assertFalse(report['summary']['pass'])
        self.assertTrue(any('< 1080' in m for m in report['failureMessages']))

    def test_opening_transfer_recomputed_by_hand(self):
        # T01: P0 top-right corner (720, 0) to P1's slanted left edge.
        t = self.report['transfers'][0]
        p1 = REFERENCE_DATA['fragments'][1]
        a = (p1['x'] + 180.0, p1['y'] + 117.0)
        b = (p1['x'], p1['y'])
        ax, ay, bx, by = a[0] - 720, a[1], b[0] - 720, b[1]
        cross = abs(ax * by - ay * bx) / math.hypot(bx - ax, by - ay)
        self.assertAlmostEqual(t['computedDistance'], cross, places=6)
        self.assertAlmostEqual(t['computedPercent'], cross / 540 * 100, places=6)


class MutationTests(unittest.TestCase):
    def test_wrong_svg_gap_percent_fails(self):
        svg = SVG_TEXT.replace('id="T05" from="P4" to="P5" encounter="S07-03" gap-percent="540"',
                               'id="T05" from="P4" to="P5" encounter="S07-03" gap-percent="540.02"')
        self.assertNotEqual(svg, SVG_TEXT)
        report = run_check(svg)
        self.assertFalse(report['summary']['pass'])
        self.assertTrue(messages(report, 'T05 P4->P5'))
        self.assertTrue(messages(report, 'svgGapPercent'))

    def test_gap_percent_within_tolerance_passes(self):
        svg = SVG_TEXT.replace('encounter="S07-03" gap-percent="540"', 'encounter="S07-03" gap-percent="540.005"')
        self.assertEqual(run_check(svg)['summary']['transfersPass'], 24)

    def test_wrong_level_gap_percent_fails(self):
        level = import_svg(SVG_TEXT.encode())
        level['svgFormat']['transfers'][23]['gapPercent'] = 450
        report = run_check(level=level)
        self.assertFalse(report['summary']['pass'])
        self.assertTrue(messages(report, 'T24') and messages(report, 'levelGapPercent'))

    def test_wrong_reference_percent_fails(self):
        ref = copy.deepcopy(REFERENCE_DATA)
        ref['encounters'][0]['percent'] = 121
        report = run_check(reference=ref)
        self.assertTrue(messages(report, 'T01') and messages(report, 'referencePercent'))

    def test_level_coordinate_drift_fails(self):
        level = import_svg(SVG_TEXT.encode())
        el = next(e for e in level['elements'] if e['id'] == 'P7-body0')
        el['points'][2]['x'] += 0.02
        report = run_check(level=level)
        self.assertTrue(messages(report, 'P7-body0: level vs SVG'))
        self.assertTrue(messages(report, 'P7: coordinate error vs reference'))

    def test_forbidden_grapple_shortcut_fails(self):
        # Move P2 next to P0 (not a transfer pair) and keep SVG, level and reference consistent.
        dx, dy = -1250.0, 760.0
        svg = translate_fragment(SVG_TEXT, 'P2', dx, dy)
        ref = translate_reference(REFERENCE_DATA, 'P2', dx, dy)
        report = run_check(svg, ref)
        self.assertFalse(report['summary']['pass'])
        self.assertTrue(shortcuts(report, 'P0/P2'), report['failureMessages'])
        pair = next(p for p in report['pairs'] if (p['a'], p['b']) == ('P0', 'P2'))
        self.assertFalse(pair['transfer'])
        self.assertLessEqual(pair['clearanceMinusDiameter'], 540)
        self.assertFalse(messages(report, 'coordinate error'))

    def test_shortcut_threshold_includes_player_diameter(self):
        # Move P1 along the normal of its slanted left edge, which is closest to P0's corner (720, 0),
        # so the opening clearance becomes just under / just over 540 + 21.6.
        p1 = REFERENCE_DATA['fragments'][1]
        ex, ey = 180.0, 117.0
        nx, ny = -ey / math.hypot(ex, ey), ex / math.hypot(ex, ey)
        if (p1['x'] - 720) * nx + p1['y'] * ny < 0:
            nx, ny = -nx, -ny
        base = run_check()['transfers'][0]['computedDistance']
        for gap, ok in ((561.599, False), (561.61, True)):
            with self.subTest(gap=gap):
                dx, dy = nx * (gap - base), ny * (gap - base)
                svg = translate_fragment(SVG_TEXT, 'P1', dx, dy)
                report = run_check(svg, translate_reference(REFERENCE_DATA, 'P1', dx, dy))
                pair = next(p for p in report['pairs'] if (p['a'], p['b']) == ('P0', 'P1'))
                self.assertAlmostEqual(pair['clearance'], gap, places=5)
                self.assertEqual(bool(shortcuts(report, 'P0/P1')), not ok, report['failureMessages'])
                self.assertEqual(pair['clearanceMinusDiameter'] > 540, ok)

    def test_drag_zone_rules(self):
        cases = {
            'grapplable': ('id="Y1-drag" x="-148.768419165046" y="-3202.3870944892597" width="2700" height="240" '
                           'data-role="drag" data-grapplable="false"',
                           'id="Y1-drag" x="-148.768419165046" y="-3202.3870944892597" width="2700" height="240" '
                           'data-role="drag" data-grapplable="true"'),
            'rect error': ('id="Y2-drag" x="4720.272221008629"', 'id="Y2-drag" x="4720.292221008629"'),
            'not horizontal': ('id="Y3-drag" x="2234.0134123324697" y="-12759.725003408601" width="2700" height="240"',
                               'id="Y3-drag" x="2234.0134123324697" y="-12759.725003408601" width="240" height="240"'),
        }
        for needle, (old, new) in cases.items():
            with self.subTest(needle):
                self.assertIn(old, SVG_TEXT)
                svg = SVG_TEXT.replace(old, new)
                level = import_svg(svg.encode()) if needle != 'grapplable' else None
                if level is None:  # the importer rejects grapplable drag; corrupt the level JSON instead
                    level = import_svg(SVG_TEXT.encode())
                    next(e for e in level['elements'] if e['id'] == 'Y1-drag')['grapplable'] = True
                    svg = SVG_TEXT
                report = run_check(svg, level=level)
                self.assertTrue(messages(report, needle), report['failureMessages'])

    def test_drag_zone_rotated_and_near_solid(self):
        level = import_svg(SVG_TEXT.encode())
        y4 = next(e for e in level['elements'] if e['id'] == 'Y4-drag')
        y4['points'][1]['y'] += 5
        report = run_check(level=level)
        self.assertTrue(messages(report, 'Y4-drag: not an axis-aligned rectangle'))
        level = import_svg(SVG_TEXT.encode())
        y1 = next(e for e in level['elements'] if e['id'] == 'Y1-drag')
        y1['y'] -= 300  # towards P3 above, clearance drops under 540
        report = run_check(level=level)
        self.assertTrue(messages(report, 'Y1-drag: solid clearance'), report['failureMessages'])
        self.assertTrue(any('< 1080' in m for m in messages(report, 'Y1-drag')))


class CliTests(unittest.TestCase):
    def run_cli(self, svg_text, level):
        with tempfile.TemporaryDirectory() as tmp:
            svg, lvl, rep = Path(tmp, 'l.svg'), Path(tmp, 'l.json'), Path(tmp, 'r.json')
            svg.write_text(svg_text)
            lvl.write_text(json.dumps(level))
            p = subprocess.run([sys.executable, str(CHECKER), '--svg', str(svg), '--level', str(lvl),
                                '--report', str(rep), '--reference', str(REFERENCE)],
                               capture_output=True, text=True, timeout=120)
            return p, json.loads(rep.read_text())

    def test_cli_rejects_historical_clearance_and_bad_transfer(self):
        p, report = self.run_cli(SVG_TEXT, import_svg(SVG_TEXT.encode()))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('GEOMETRY_RESULT FAIL transfers=24/24 pairs=300/300', p.stdout)
        self.assertIn('< 1080', p.stderr)
        svg = SVG_TEXT.replace('encounter="S06-03" gap-percent="120"', 'encounter="S06-03" gap-percent="125"')
        p, report = self.run_cli(svg, import_svg(svg.encode()))
        self.assertEqual(p.returncode, 1)
        self.assertIn('GEOMETRY_RESULT FAIL', p.stdout)
        self.assertIn('FAIL T01', p.stderr)

    def test_cli_usage_error(self):
        p = subprocess.run([sys.executable, str(CHECKER), '--svg', 'x'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


if __name__ == '__main__':
    unittest.main()
