"""Tests for the minimum polygon side length rule in tools/check_level_geometry.py.

    python3 -m unittest discover -s tools -p test_level_minimum_sides.py -v
    python3 tools/test_level_minimum_sides.py --write DIR   # boundary cases + real level inventory

Expected lengths come from the fixture construction (closed-form), never from
the helper under test. The rule (0.5 R = 270) is enforced by the CLI by default since v16 (TASK-687);
--no-min-side-length only inventories. It is
separate from the 270 maximum internal no-grapple transfer gap.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import check_level_geometry as geometry  # noqa: E402
from check_level_geometry import (COORD_TOL, GAMEPLAY_ROLES, MIN_SIDE_LENGTH, NO_GRAPPLE_INTERNAL_GAP,  # noqa: E402
                                  check, check_sides)

CHECKER = TOOLS / 'check_level_geometry.py'
FIXTURES = TOOLS / 'fixtures' / 'min-sides'
LEVEL_SVG = ROOT / 'artifacts' / 'levels' / 'extended-mountain.svg'
LEVEL_JSON = ROOT / 'artifacts' / 'levels' / 'extended-mountain.level.json'
REFERENCE = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'


def rect(w, h, x=0.0, y=0.0):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def rotated(poly, deg, cx=0.0, cy=0.0):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [(cx + (px - cx) * c - (py - cy) * s, cy + (px - cx) * s + (py - cy) * c) for px, py in poly]


def bevelled(w, h, bevel):
    """w x h rectangle with its top-right corner cut by a 45-degree bevel of length bevel."""
    k = bevel / math.sqrt(2)
    return [(0, 0), (w - k, 0), (w, k), (w, h), (0, h)], [w - k, bevel, h - k, w, h]


def element(eid, poly, role='bounce', ox=1000.0, oy=-2000.0):
    """Level JSON element whose world polygon is poly (stored relative to (ox, oy))."""
    return {'id': eid, 'x': ox, 'y': oy, 'role': role, 'grapplable': role in ('bounce', 'solid'),
            'points': [{'x': px - ox, 'y': py - oy} for px, py in poly]}


def level(elements, fragments=None):
    return {'layoutId': 'min-sides-fixture', 'elements': elements,
            'svgFormat': {'version': 1, 'grappleRange': 540, 'fragments': fragments or []}}


def sides_of(report, eid):
    return [s for s in report['sides'] if s['element'] == eid]


class BoundaryTests(unittest.TestCase):
    def assert_lengths(self, report, eid, expected):
        got = [s['length'] for s in sides_of(report, eid)]
        self.assertEqual(len(got), len(expected))
        for g, e in zip(got, expected):
            self.assertAlmostEqual(g, e, places=6)

    def test_269_270_271(self):
        for short, ok in ((269.0, False), (270.0, True), (271.0, True)):
            with self.subTest(short=short):
                rep = check_sides(level([element('A', rect(600, short))]), MIN_SIDE_LENGTH)
                self.assert_lengths(rep, 'A', [600, short, 600, short])
                self.assertEqual(rep['summary']['pass'], ok)
                self.assertEqual(rep['summary']['sideViolations'], 0 if ok else 2)
                self.assertAlmostEqual(rep['summary']['minMeasuredSide'], min(600, short))

    def test_coordinate_tolerance(self):
        self.assertEqual(MIN_SIDE_LENGTH, 270.0)
        self.assertEqual(COORD_TOL, 0.01)
        for short, ok in ((270 - 0.009, True), (270 - 0.011, False)):
            with self.subTest(short=short):
                self.assertEqual(check_sides(level([element('A', rect(600, short))]))['summary']['pass'], ok)

    def test_rotated(self):
        for deg in (17.0, 37.0, 90.0, 233.0):
            for short, ok in ((269.0, False), (270.0, True), (271.0, True)):
                with self.subTest(deg=deg, short=short):
                    poly = rotated(rect(800, short, 3000, -500), deg, 3100, -400)
                    rep = check_sides(level([element('R', poly)]))
                    self.assert_lengths(rep, 'R', [800, short, 800, short])
                    self.assertEqual(rep['summary']['pass'], ok)

    def test_bevel(self):
        for bevel, ok in ((269.0, False), (270.0, True), (271.0, True)):
            with self.subTest(bevel=bevel):
                poly, expected = bevelled(1200, 900, bevel)
                rep = check_sides(level([element('B', poly)]))
                self.assert_lengths(rep, 'B', expected)
                self.assertEqual(rep['summary']['pass'], ok)
                bad = [s['edge'] for s in rep['sides'] if not s['pass']]
                self.assertEqual(bad, [] if ok else [1])

    def test_multi_body_fragment(self):
        body0 = element('P3-body0', rect(2700, 300))
        post = element('P3-body1', rect(269, 900, 2400, -900))
        rep = check_sides(level([body0, post], [{'id': 'P3', 'elements': ['P3-body0', 'P3-body1']}]),
                          names={'P3': 'R1'})
        self.assertFalse(rep['summary']['pass'])
        bad = [s for s in rep['sides'] if not s['pass']]
        self.assertEqual([(s['element'], s['fragment'], s['body'], s['semantic'], s['edge']) for s in bad],
                         [('P3-body1', 'P3', 1, 'R1', 0), ('P3-body1', 'P3', 1, 'R1', 2)])
        self.assertTrue(all(s['pass'] for s in sides_of(rep, 'P3-body0')))
        self.assertIn('P3-body1 edge 0 (bounce R1): side length 269.000000 < 270.0', rep['failureMessages'])

    def test_each_gameplay_role(self):
        self.assertEqual(set(GAMEPLAY_ROLES), {'solid', 'bounce', 'hazard', 'drag', 'no-grapple'})
        for role in GAMEPLAY_ROLES:
            for short, ok in ((269.0, False), (270.0, True), (271.0, True)):
                with self.subTest(role=role, short=short):
                    rep = check_sides(level([element('E', rect(1600, short), role)]))
                    self.assertEqual(rep['summary']['pass'], ok)
                    self.assertEqual(rep['summary']['sideEdges'], 4)

    def test_decorative_exempt(self):
        for role in ('decorative', None):
            with self.subTest(role=role):
                rep = check_sides(level([element('D', rect(10, 5), role), element('E', rect(400, 300))]))
                self.assertTrue(rep['summary']['pass'], rep['failureMessages'])
                self.assertTrue(all(s['exempt'] for s in sides_of(rep, 'D')))
                self.assertEqual((rep['summary']['sideEdges'], rep['summary']['sideExemptEdges']), (4, 4))
                self.assertEqual(rep['summary']['minMeasuredSide'], 300)

    def test_rule_off_inventories_only(self):
        rep = check_sides(level([element('A', rect(600, 100))]), None)
        self.assertTrue(rep['summary']['pass'])
        self.assertFalse(rep['summary']['minSideEnforced'])
        self.assertEqual(rep['summary']['sideViolations'], 2)

    def test_custom_minimum(self):
        self.assertTrue(check_sides(level([element('A', rect(600, 100))]), 100)['summary']['pass'])
        self.assertFalse(check_sides(level([element('A', rect(600, 100))]), 101)['summary']['pass'])

    def test_corner_and_self_intersection_checks_stay_active(self):
        h = math.radians(15 / 2)
        sliver = [(0, 0), (2000 * math.cos(h), -2000 * math.sin(h)), (2000 * math.cos(h), 2000 * math.sin(h))]
        rep = check_sides(level([element('S', sliver)]))
        self.assertFalse(rep['summary']['pass'])
        self.assertEqual(rep['summary']['sideViolations'], 0)
        self.assertTrue(any('interior angle' in m for m in rep['failureMessages']))
        bowtie = [(0, 0), (1000, 1000), (1000, 0), (0, 1000)]
        rep = check_sides(level([element('X', bowtie)]))
        self.assertFalse(rep['summary']['pass'])
        self.assertTrue(any('self-intersecting' in m for m in rep['failureMessages']))

    def test_distinct_from_internal_gap(self):
        self.assertEqual(MIN_SIDE_LENGTH, NO_GRAPPLE_INTERNAL_GAP)
        self.assertIsNot(geometry.MIN_SIDE_LENGTH, None)
        # Same number, different quantity: a minimum edge length, not a maximum gap.
        self.assertTrue(check_sides(level([element('A', rect(5400, 2700), 'no-grapple')]))['summary']['pass'])


def world_polygons(lvl):
    return {e['id']: (e['role'], [(e['x'] + p['x'], e['y'] + p['y']) for p in e['points']]) for e in lvl['elements']}


def independent_inventory(lvl):
    """Edge lengths straight from the level JSON points, without the checker."""
    out = []
    for eid, (role, poly) in sorted(world_polygons(lvl).items()):
        for i in range(len(poly)):
            (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
            out.append((eid, role, i, math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)))
    return out


class RealLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.level = json.loads(LEVEL_JSON.read_text())
        cls.svg = LEVEL_SVG.read_bytes()
        cls.ref = json.loads(REFERENCE.read_text())

    def test_inventory_matches_independent_lengths(self):
        rep = check(self.level, self.svg, self.ref)
        mine = independent_inventory(self.level)
        self.assertEqual(len(rep['sides']), len(mine))
        self.assertGreater(len(mine), 0)
        for s, (eid, role, i, length) in zip(rep['sides'], mine):
            self.assertEqual((s['element'], s['role'], s['edge']), (eid, role, i))
            self.assertLessEqual(abs(s['length'] - length), 1e-6)
        roles = {s['role'] for s in rep['sides']}
        self.assertTrue({'bounce', 'drag', 'no-grapple'} <= roles)

    def test_shipped_layout_passes_with_rule_off(self):
        rep = check(self.level, self.svg, self.ref)
        self.assertTrue(rep['summary']['pass'], rep['failureMessages'])
        self.assertFalse(rep['summary']['minSideEnforced'])

    def test_shipped_layout_passes_with_rule_on(self):
        # v16 ships the rule: every gameplay edge of the shipped level is >= 270, none exempt.
        rep = check(self.level, self.svg, self.ref, MIN_SIDE_LENGTH)
        self.assertTrue(rep['summary']['pass'], rep['failureMessages'])
        self.assertTrue(rep['summary']['minSideEnforced'])
        self.assertEqual(rep['summary']['sideViolations'], 0)
        self.assertGreaterEqual(rep['summary']['minMeasuredSide'], MIN_SIDE_LENGTH - COORD_TOL)
        self.assertEqual({eid for eid, role, i, length in independent_inventory(self.level)
                          if length < MIN_SIDE_LENGTH - COORD_TOL}, set())

    def test_rule_on_reports_exact_short_edges(self):
        rep = check(self.level, self.svg, self.ref, MIN_SIDE_LENGTH)
        short = {(eid, i) for eid, role, i, length in independent_inventory(self.level) if length < 270 - COORD_TOL}
        bad = {(s['element'], s['edge']) for s in rep['sides'] if not s['pass']}
        self.assertEqual(bad, short)
        self.assertEqual(rep['summary']['pass'], not short)
        self.assertEqual(sum('side length' in m for m in rep['failureMessages']), len(short))
        # Everything except sides is unchanged by the option.
        off = check(self.level, self.svg, self.ref)
        self.assertEqual([m for m in rep['failureMessages'] if 'side length' not in m], off['failureMessages'])
        self.assertEqual(rep['angles'], off['angles'])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        report = Path('/tmp') / ('min-sides-cli-%d.json' % abs(hash(args)))
        p = subprocess.run([sys.executable, str(CHECKER), '--report', str(report)] + list(args),
                           capture_output=True, text=True)
        return p, json.loads(report.read_text()) if report.exists() and p.returncode in (0, 1) else None

    def test_fixtures(self):
        for name, code in (('positive.level.json', 0), ('negative.level.json', 1)):
            with self.subTest(name=name):
                p, rep = self.run_cli('--sides-only', '--level', str(FIXTURES / name), '--min-side-length')
                self.assertEqual(p.returncode, code, p.stderr)
                self.assertIn('SIDES_RESULT %s' % ('PASS' if code == 0 else 'FAIL'), p.stdout)
                self.assertIn('min_side_rule=270.0', p.stdout)
        # The rule is the CLI default; --no-min-side-length is the explicit legacy inventory mode.
        p, rep = self.run_cli('--sides-only', '--level', str(FIXTURES / 'negative.level.json'))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('min_side_rule=270.0', p.stdout)
        self.assertTrue(rep['summary']['minSideEnforced'])
        p, rep = self.run_cli('--sides-only', '--level', str(FIXTURES / 'negative.level.json'), '--no-min-side-length')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('min_side_rule=off', p.stdout)
        self.assertGreater(rep['summary']['sideViolations'], 0)
        p, rep = self.run_cli('--sides-only', '--level', str(FIXTURES / 'positive.level.json'))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('min_side_rule=270.0', p.stdout)

    def test_default_rule_on_full_check(self):
        # Default full check on the shipped level: every rule plus min side 270, exit 0.
        p, rep = self.run_cli('--svg', str(LEVEL_SVG), '--level', str(LEVEL_JSON), '--reference', str(REFERENCE))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('GEOMETRY_RESULT PASS', p.stdout)
        self.assertIn('min_side_rule=270.0', p.stdout)
        self.assertEqual(rep['summary']['sideViolations'], 0)
        self.assertGreater(rep['summary']['sideEdges'], 0)

    def test_usage_errors(self):
        self.assertEqual(self.run_cli('--level', str(FIXTURES / 'positive.level.json'))[0].returncode, 2)
        self.assertEqual(self.run_cli('--sides-only', '--level', str(FIXTURES / 'positive.level.json'),
                                      '--min-side-length', '-5')[0].returncode, 2)
        self.assertEqual(self.run_cli('--sides-only', '--level', str(FIXTURES / 'positive.level.json'),
                                      '--min-side-length', '300', '--no-min-side-length')[0].returncode, 2)


def write_evidence(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for label, poly, role in [('rect-269', rect(600, 269), 'bounce'), ('rect-270', rect(600, 270), 'bounce'),
                              ('rect-271', rect(600, 271), 'bounce'),
                              ('rect-269.991', rect(600, 269.991), 'bounce'),
                              ('rect-269.989', rect(600, 269.989), 'bounce'),
                              ('rot37-269', rotated(rect(800, 269), 37), 'bounce'),
                              ('rot37-270', rotated(rect(800, 270), 37), 'bounce'),
                              ('rot37-271', rotated(rect(800, 271), 37), 'bounce'),
                              ('bevel-269', bevelled(1200, 900, 269)[0], 'solid'),
                              ('bevel-270', bevelled(1200, 900, 270)[0], 'solid'),
                              ('bevel-271', bevelled(1200, 900, 271)[0], 'solid')] + \
            [('role-%s-%d' % (role, v), rect(1600, v), role) for role in GAMEPLAY_ROLES for v in (269, 270, 271)] + \
            [('decorative-10', rect(10, 5), 'decorative')]:
        rep = check_sides(level([element('E', poly, role)]))
        cases.append({'case': label, 'role': role, 'lengths': [s['length'] for s in rep['sides']],
                      'pass': rep['summary']['pass'], 'violations': rep['summary']['sideViolations'],
                      'exemptEdges': rep['summary']['sideExemptEdges']})
    (out / 'boundary-cases.json').write_text(json.dumps({'minimum': MIN_SIDE_LENGTH, 'tolerance': COORD_TOL,
                                                         'cases': cases}, indent=1) + '\n')
    lvl = json.loads(LEVEL_JSON.read_text())
    ref = json.loads(REFERENCE.read_text())
    rep = check(lvl, LEVEL_SVG.read_bytes(), ref, MIN_SIDE_LENGTH)
    sha = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
           for p in (LEVEL_JSON, LEVEL_SVG, REFERENCE, ROOT / 'leveldata.js', CHECKER)}
    inventory = {'layoutId': lvl['layoutId'], 'inputSha256': sha, 'minimum': MIN_SIDE_LENGTH,
                 'summary': {k: v for k, v in rep['summary'].items() if k.startswith(('side', 'minSide', 'minMeasured'))},
                 'violations': [s for s in rep['sides'] if not s['pass']],
                 'edges': [{k: s[k] for k in ('element', 'role', 'fragment', 'body', 'semantic', 'edge', 'length',
                                              'pass')} for s in rep['sides']]}
    (out / ('%s-side-inventory.json' % lvl['layoutId'].rsplit('-', 1)[-1])).write_text(json.dumps(inventory, indent=1) + '\n')
    return cases, inventory


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', help='write boundary-cases.json and <layout>-side-inventory.json to this directory')
    args, rest = parser.parse_known_args()
    if args.write:
        cases, inventory = write_evidence(args.write)
        print('MIN_SIDES_EVIDENCE cases=%d level=%s edges=%d violations=%d' % (
            len(cases), inventory['layoutId'], inventory['summary']['sideEdges'],
            inventory['summary']['sideViolations']))
    else:
        unittest.main(argv=[sys.argv[0]] + rest)
