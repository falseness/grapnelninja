"""TASK-668: the four added rightward opening transfers form a mixed combination.

Generates the extended layout twice through tools/retune_extended_level.py,
imports the SVG and checks the opening from imported polygons: a right/up
ceiling underside catch, a descent onto a sloped bounce face, a right/up
rebound and a mostly horizontal transfer to the upward-turn departure. Surface
edges are found independently of the generator: the contact must lie on a
polygon edge whose interior side matches the intended surface. The pre-change
v7 generation frozen under artifacts/TASK-668/before is the comparison point;
relabelling that stair with the new actions must fail the same checks.
Set OPENING_VARIETY_EVIDENCE_DIR to write contact-vectors.json, geometry.json
and preservation.json.
"""
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from check_level_geometry import (COORD_TOL, GRAPPLE_RANGE, MIN_INTERIOR_ANGLE, PLAYER_DIAMETER, check,  # noqa: E402
                                  inside, point_segment)
from import_level_svg import import_svg  # noqa: E402
import retune_extended_level as retune  # noqa: E402

SOURCE = ROOT / 'artifacts/level/extended-mountain-measurements.json'
GUIDELINES = ROOT / 'artifacts/levels/level-guidelines.md'
BEFORE = ROOT / 'artifacts/TASK-668/before'
EVIDENCE = os.environ.get('OPENING_VARIETY_EVIDENCE_DIR')
RADIUS = PLAYER_DIAMETER / 2
MIN_SPAN = 720.0
ADDED = ['OPEN-P2-R1', 'OPEN-R1-R2', 'OPEN-R2-R3', 'OPEN-R3-R4']
EXPECTED = [('ceiling', 'underside'), ('descent', 'slope'), ('rebound', 'top'), ('horizontal', 'top')]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def generate(dest):
    out = subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source', str(SOURCE),
                          '--output-dir', str(dest), '--guidelines', str(GUIDELINES)],
                         capture_output=True, text=True, cwd=str(TOOLS))
    if out.returncode:
        raise AssertionError(out.stdout + out.stderr)
    return (dest / 'extended-mountain.svg').read_bytes(), (dest / 'extended-mountain-measurements.json').read_bytes()


def fragment_polys(level):
    elements = {e['id']: e for e in level['elements']}
    return {f['id']: [[(elements[eid]['x'] + p['x'], elements[eid]['y'] + p['y']) for p in elements[eid]['points']]
                      for eid in f['elements']] for f in level['svgFormat']['fragments']}


def surface_at(polys, centre):
    """Classify the collision edge the player centre rests against.

    The edge is the one nearest the centre among all polygon edges; its probe
    points just above and below show which side is solid. Returns kind
    ('top', 'underside' or 'slope'), the edge, the surface point, the gap from
    the centre and the edge's horizontal projection.
    """
    best = None
    for poly in polys:
        for a, b in zip(poly, poly[1:] + poly[:1]):
            d, c = point_segment(centre, a, b)
            if best is None or d < best[0]:
                best = (d, c, a, b, poly)
    d, c, a, b, poly = best
    slope = math.degrees(math.atan2(abs(b[1] - a[1]), abs(b[0] - a[0])))
    above, below = inside((c[0], c[1] - .5), poly), inside((c[0], c[1] + .5), poly)
    if below and not above:
        kind = 'top' if slope < .01 else 'slope'
    elif above and not below:
        kind = 'underside'
    else:
        kind = 'unknown'
    return dict(kind=kind, edge=[list(a), list(b)], point=list(c), centreGap=d, slopeDegrees=slope,
                span=abs(b[0] - a[0]), centreAbove=centre[1] < c[1])


def movement(dx, dy):
    """Intended movement implied by a contact vector (world y down)."""
    if dx <= 0:
        return 'not rightward'
    if abs(dy) <= .25 * dx:
        return 'horizontal'
    return 'rise' if dy < 0 else 'descent'


def combination_violations(m, level):
    """Directions and surfaces of the four added transfers from geometry, not labels."""
    polys = fragment_polys(level)
    rows = {r['id']: r for r in m['encounters']}
    out, vectors = [], []
    for eid, (want, surface) in zip(ADDED, EXPECTED):
        r = rows.get(eid)
        if r is None:
            out.append('%s missing' % eid)
            continue
        a, b = r['flight']
        dx, dy = b[0] - a[0], b[1] - a[1]
        dep, arr = surface_at(polys[r['fromFragment']], a), surface_at(polys[r['toFragment']], b)
        move = movement(dx, dy)
        vectors.append(dict(encounter=eid, dx=dx, dy=dy, movement=move, departure=dep, arrival=arr))
        if arr['kind'] != surface:
            out.append('%s arrives on %s, expected %s' % (eid, arr['kind'], surface))
        if arr['centreGap'] > RADIUS + COORD_TOL or (surface != 'slope' and abs(arr['centreGap'] - RADIUS) > COORD_TOL):
            out.append('%s contact %.3f from its surface' % (eid, arr['centreGap']))
        if surface == 'underside' and arr['centreAbove']:
            out.append('%s contact is above the ceiling' % eid)
        ok = {'ceiling': move == 'rise' and dy < 0, 'descent': move == 'descent', 'rebound': move == 'rise',
              'horizontal': move == 'horizontal' and abs(dy) <= .25 * abs(dx)}[want]
        if not ok:
            out.append('%s moves %s (dx %.1f, dy %.1f), expected %s' % (eid, move, dx, dy, want))
        if want == 'descent' and dep['kind'] != 'underside':
            out.append('%s departs from %s, expected the ceiling underside' % (eid, dep['kind']))
        if want == 'descent' and arr['slopeDegrees'] < 5:
            out.append('%s landing face is not sloped' % eid)
    return out, vectors


def guide_end_tangent(guide):
    return (guide[3][0] - guide[2][0], guide[3][1] - guide[2][1])


def relabel(m):
    """The pre-change stair with only its actions and directions renamed."""
    m = copy.deepcopy(m)
    for r in m['encounters']:
        if r['id'] in ADDED:
            k = ADDED.index(r['id'])
            r['action'] = r['direction'] = retune.OPENING['right'][k]['direction']
    return m


class OpeningJumpVarietyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.runs = [generate(Path(cls.tmp.name) / str(k)) for k in range(2)]
        cls.svg, raw = cls.runs[0]
        cls.m = json.loads(raw)
        cls.level = import_svg(cls.svg)
        cls.before_svg = (BEFORE / 'extended-mountain.svg').read_bytes()
        cls.before = json.loads((BEFORE / 'extended-mountain-measurements.json').read_text())
        cls.before_level = import_svg(cls.before_svg)
        cls.report = check(cls.level, cls.svg, cls.m)
        cls.ids = {f['semanticId']: f['id'] for f in cls.m['fragments']}
        cls.before_ids = {f['semanticId']: f['id'] for f in cls.before['fragments']}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def frag(self, m, fid):
        return next(f for f in m['fragments'] if f['id'] == fid)

    def test_01_generation_is_deterministic(self):
        self.assertEqual(self.runs[0], self.runs[1])
        self.assertEqual(json.dumps(self.level), json.dumps(import_svg(self.runs[1][0])))
        self.assertEqual(self.m['layoutId'], retune.EXTENDED_LAYOUT)
        self.assertNotEqual(self.m['layoutId'], self.before['layoutId'])

    def test_02_combination_follows_actual_geometry(self):
        violations, vectors = combination_violations(self.m, self.level)
        self.assertEqual(violations, [])
        self.assertEqual(self.m['routeMap']['openingCombination'], ADDED)
        # The departure of the upward turn is the horizontal transfer's arrival.
        up = next(r for r in self.m['encounters'] if r['id'] == 'S07-01')
        self.assertEqual(up['fromFragment'], self.ids['R4'])
        a, b = up['flight']
        self.assertTrue(b[1] - a[1] < 0 and abs(b[1] - a[1]) > abs(b[0] - a[0]))
        # The ceiling catch and descent share the real underside contact.
        self.assertEqual(vectors[0]['arrival']['point'], vectors[1]['departure']['point'])

    def test_03_relabelled_stair_is_rejected(self):
        violations, _ = combination_violations(relabel(self.before), self.before_level)
        self.assertGreaterEqual(len(violations), 3, violations)
        self.assertTrue(any('arrives on top, expected underside' in v for v in violations), violations)
        self.assertTrue(any('expected descent' in v for v in violations), violations)
        self.assertTrue(any('landing face is not sloped' in v or 'expected slope' in v for v in violations))

    def test_04_top_centre_substitution_is_rejected(self):
        # Moving the R1 catch to its top centre keeps the label but not the surface.
        m = copy.deepcopy(self.m)
        r1 = self.frag(m, self.ids['R1'])
        for r in m['encounters']:
            if r['id'] in ('OPEN-P2-R1', 'OPEN-R1-R2'):
                k = 1 if r['id'] == 'OPEN-P2-R1' else 0
                r['flight'][k] = [r1['x'] + r1['width'] / 2, r1['y'] - 90 - RADIUS]
        violations, _ = combination_violations(m, self.level)
        self.assertTrue(any('arrives on top' in v for v in violations), violations)
        self.assertTrue(any('departs from top' in v for v in violations), violations)
        # A flattened R2 (same label, flat top) is rejected as a descending slope landing.
        flat = copy.deepcopy(self.level)
        el = next(e for e in flat['elements'] if e['id'] == self.ids['R2'] + '-body0')
        el['points'][1]['y'] = el['points'][0]['y']
        violations, _ = combination_violations(self.m, flat)
        self.assertNotEqual(violations, [])

    def test_05_usable_surfaces_and_spans(self):
        polys = fragment_polys(self.level)
        rows = {r['id']: r for r in self.m['encounters']}
        spans = {}
        # Departure surfaces for P0..R3 (first transfers), arrival surfaces for R1..R4.
        for r in self.m['encounters'][:6]:
            for fid, point in ((r['fromFragment'], r['flight'][0]), (r['toFragment'], r['flight'][1])):
                s = surface_at(polys[fid], point)
                spans[fid] = dict(surface=s['kind'], span=s['span'], edge=s['edge'])
        for fid, s in spans.items():
            self.assertGreaterEqual(s['span'], MIN_SPAN, fid)
        self.assertEqual(spans[self.ids['R1']]['surface'], 'underside')
        self.assertEqual(spans[self.ids['R2']]['surface'], 'slope')
        # Spans from imported top-centre contacts, as in the guidelines.
        c = lambda lvl, fid: (lambda ps: ((min(x for p in ps for x, _ in p) + max(x for p in ps for x, _ in p)) / 2))(
            fragment_polys(lvl)[fid])
        base = self.m['routeMap']['baselineSpans']
        right = c(self.level, self.ids['R4']) - c(self.level, 'P0')
        left = c(self.level, self.ids['P3']) - c(self.level, self.ids['P4'])
        self.assertGreaterEqual(right / base['rightward'], 3)
        self.assertAlmostEqual(left / base['leftward'], 3, delta=.03)
        self.assertEqual(len(spans), 7)
        self.__class__.spans = dict(fragments=spans, rightwardRatio=right / base['rightward'],
                                    leftwardRatio=left / base['leftward'], rightwardSpan=right, leftwardSpan=left,
                                    baseline=base, rowsChecked=[rows[e]['id'] for e in ADDED])

    def test_06_generator_rejects_small_surfaces(self):
        src = json.loads(SOURCE.read_text())
        for k in range(4):
            spec = copy.deepcopy(retune.OPENING)
            spec['right'][k]['width'] = 719
            with self.assertRaisesRegex(ValueError, '720'):
                retune.tune(src, opening=spec, yellow_clearance=retune.YELLOW_CLEARANCE)

    def test_07_preserves_easy_opening_and_later_terrain(self):
        keys = ('x', 'y', 'width', 'height', 'kind', 'polys')
        for fid in ('P0', 'P1', 'P2'):
            self.assertEqual({k: self.frag(self.m, fid)[k] for k in keys},
                             {k: self.frag(self.before, fid)[k] for k in keys}, fid)
        els = lambda lvl: {e['id']: e for e in lvl['elements']}
        for eid in ('P0-body0', 'P1-body0', 'P2-body0'):
            self.assertEqual(json.dumps(els(self.level)[eid]), json.dumps(els(self.before_level)[eid]))
        for n in (1, 2):
            new, old = self.m['encounters'][n - 1], self.before['encounters'][n - 1]
            self.assertEqual((new['id'], new['percent'], new['distance'], new['flight']),
                             (old['id'], old['percent'], old['distance'], old['flight']))
        # Upward turn onward: one rigid translation, identical shapes.
        start = [f['semanticId'] for f in self.m['fragments']].index('P3')
        shifts = set()
        for f in self.m['fragments'][start:]:
            old = self.frag(self.before, self.before_ids[f['semanticId']])
            self.assertEqual(f['polys'], old['polys'], f['semanticId'])
            shifts.add((round(f['x'] - old['x'], 6), round(f['y'] - old['y'], 6)))
        self.assertEqual(len(shifts), 1, shifts)
        up = next(r for r in self.m['encounters'] if r['id'] == 'S07-01')
        self.assertAlmostEqual(up['distance'], 1.5 * GRAPPLE_RANGE, delta=COORD_TOL)
        self.assertEqual([r['id'] for r in self.m['encounters'][6:]], [r['id'] for r in self.before['encounters'][6:]])
        for new, old in zip(self.m['encounters'][6:], self.before['encounters'][6:]):
            self.assertAlmostEqual(new['distance'], old['distance'], delta=COORD_TOL, msg=new['id'])
        # Later guide curves keep their shape (the ceiling-departure clamp leaves them alone).
        rel = lambda g: [[round(p[i] - g[0][i], 6) for i in (0, 1)] for p in g]
        new_t, old_t = self.level['svgFormat']['transfers'][6:], self.before_level['svgFormat']['transfers'][6:]
        self.assertEqual([rel(x['guide']) for x in new_t], [rel(x['guide']) for x in old_t])
        self.__class__.shift = shifts.pop()

    def test_08_geometry_rules(self):
        s = self.report['summary']
        self.assertTrue(s['pass'], self.report['failureMessages'])
        self.assertEqual((s['fragments'], s['transfers'], s['fragmentPairs']), (31, 30, 465))
        self.assertEqual(s['pairsPass'], 465)
        self.assertGreaterEqual(s['minInteriorAngle'], MIN_INTERIOR_ANGLE)
        self.assertGreaterEqual(s['minDragSolidClearance'], 1620)
        self.assertGreaterEqual(s['minYellowPairClearance'], 540)
        self.assertEqual(s['solidBounceGrapplable'], s['solidElements'])
        allowed = {frozenset(p) for p in self.m['allowedGrapplePairs']}
        self.assertEqual(allowed, {frozenset(('P0', 'P1')), frozenset(('P1', 'P2'))})
        for p in self.report['pairs']:
            if frozenset((p['a'], p['b'])) not in allowed:
                self.assertGreater(p['clearanceMinusDiameter'], GRAPPLE_RANGE, p)
        rect = [d for d in self.report['dragZones'] if d['rect'][2] <= d['rect'][3]]
        self.assertEqual(rect, [])
        # Added transfers: measured release gaps above 100% R + diameter, written to SVG and metadata.
        transfers = {t['encounter']: t for t in self.report['transfers']}
        rows = {r['id']: r for r in self.m['encounters']}
        for eid in ADDED:
            t = transfers[eid]
            self.assertGreater(t['computedDistance'], GRAPPLE_RANGE + PLAYER_DIAMETER, eid)
            self.assertAlmostEqual(t['computedPercent'], rows[eid]['percent'], delta=.01)
            self.assertAlmostEqual(t['expected']['svgGapPercent'], rows[eid]['percent'], delta=.01)

    def test_09_guides_follow_surfaces(self):
        transfers = {t['encounter']: t for t in self.level['svgFormat']['transfers']}
        rows = {r['id']: r for r in self.m['encounters']}
        guides = {}
        for eid in ADDED:
            g = transfers[eid]['guide']
            self.assertEqual([list(map(float, p)) for p in (g[0], g[3])],
                             [list(map(float, p)) for p in rows[eid]['flight']], eid)
            guides[eid] = g
        # Ceiling catch arrives moving up; the descent arrives moving down onto the slope.
        self.assertLess(guide_end_tangent(guides['OPEN-P2-R1'])[1], 0)
        self.assertGreater(guide_end_tangent(guides['OPEN-R1-R2'])[1], 0)
        # The descent leaves the underside rightward and never above it.
        self.assertGreater(guides['OPEN-R1-R2'][1][0], guides['OPEN-R1-R2'][0][0])
        self.assertGreaterEqual(guides['OPEN-R1-R2'][1][1], guides['OPEN-R1-R2'][0][1])
        # Every guide point stays out of the solids it connects.
        polys = fragment_polys(self.level)
        for eid in ADDED:
            r = rows[eid]
            pts = [tuple(p) for p in guides[eid]]
            for t in [k / 20 for k in range(1, 20)]:
                u = 1 - t
                p = tuple(u ** 3 * pts[0][i] + 3 * u * u * t * pts[1][i] + 3 * u * t * t * pts[2][i] + t ** 3 * pts[3][i]
                          for i in (0, 1))
                for fid in (r['fromFragment'], r['toFragment']):
                    self.assertFalse(any(inside(p, poly) for poly in polys[fid]), (eid, t, fid))
        self.__class__.guides = guides

    def test_zz_write_evidence(self):
        if not EVIDENCE:
            self.skipTest('OPENING_VARIETY_EVIDENCE_DIR not set')
        write_evidence(self, Path(EVIDENCE))


def write_evidence(t, out):
    out.mkdir(parents=True, exist_ok=True)
    dump = lambda name, data: (out / name).write_text(json.dumps(data, separators=(',', ':')) + '\n')
    violations, vectors = combination_violations(t.m, t.level)
    bad, bad_vectors = combination_violations(relabel(t.before), t.before_level)
    rows = {r['id']: r for r in t.m['encounters']}
    for v in vectors:
        r = rows[v['encounter']]
        v.update(source=dict(id=r['fromFragment'], semantic=t.frag(t.m, r['fromFragment'])['semanticId']),
                 target=dict(id=r['toFragment'], semantic=t.frag(t.m, r['toFragment'])['semanticId']),
                 action=r['action'], gapPercent=r['percent'], gapDistance=r['distance'],
                 departureContact=r['flight'][0], arrivalContact=r['flight'][1],
                 absDyOverDx=abs(v['dy']) / v['dx'], guide=t.guides[v['encounter']])
    dump('contact-vectors.json', dict(
        method='Contacts are measurement flight endpoints (player centre). surface_at() finds the nearest imported '
               'polygon edge and probes 0.5 units above/below it to classify top/underside/slope; dy uses world y down.',
        playerRadius=RADIUS, tolerance=COORD_TOL, violations=violations, transfers=vectors,
        relabelledPreChange=dict(source=str(BEFORE / 'extended-mountain-measurements.json'), violations=bad,
                                 transfers=[dict(encounter=v['encounter'], dx=v['dx'], dy=v['dy'],
                                                 arrival=v['arrival']['kind'], departure=v['departure']['kind'])
                                            for v in bad_vectors])))
    s = t.report['summary']
    allowed = [sorted(p) for p in t.m['allowedGrapplePairs']]
    dump('geometry.json', dict(
        summary=s, failures=t.report['failureMessages'], allowedGrapplePairs=allowed,
        nonOpeningPairsBelowRange=[p for p in t.report['pairs'] if sorted((p['a'], p['b'])) not in allowed
                                   and p['clearanceMinusDiameter'] <= GRAPPLE_RANGE],
        transfers=[dict(id=x['id'], encounter=x['encounter'], distance=x['computedDistance'],
                        percent=x['computedPercent'], svgPercent=x['expected']['svgGapPercent'],
                        metadataPercent=x['expected']['referencePercent'], pass_=x['pass'])
                   for x in t.report['transfers']],
        dragZones=[dict(id=d['id'], rect=d['rect'], minSolidClearance=d['minSolidClearance'],
                        nearestSolid=d['nearestSolid'], pass_=d['pass']) for d in t.report['dragZones']],
        yellowPairs=t.report['yellowPairs'],
        angles=dict(min=s['minInteriorAngle'], polygons=s['anglePolygons'], pass_=s['anglePolygonsPass']),
        roles=dict(solid=s['solidElements'], bounceGrapplable=s['solidBounceGrapplable'])))
    keys = ('x', 'y', 'width', 'height', 'kind', 'polys')
    bands = lambda m: {z['id']: dict(x=z['x'], y=z['y'], width=z['width'], height=z['height'],
                                     mergedFrom=z.get('mergedFrom'), purpose=z.get('purpose')) for z in m['yellowBands']}
    nb, ob = bands(t.m), bands(t.before)
    start = [f['semanticId'] for f in t.m['fragments']].index('P3')
    later = [dict(semantic=f['semanticId'], id=f['id'],
                  shapeSha=sha(json.dumps(f['polys']).encode()),
                  beforeShapeSha=sha(json.dumps(t.frag(t.before, t.before_ids[f['semanticId']])['polys']).encode()))
             for f in t.m['fragments'][start:]]
    dump('preservation.json', dict(
        before=dict(path=str(BEFORE), layoutId=t.before['layoutId'],
                    measurementsSha=sha((BEFORE / 'extended-mountain-measurements.json').read_bytes()),
                    svgSha=sha(t.before_svg)),
        candidate=dict(layoutId=t.m['layoutId'], svgSha=sha(t.svg), measurementsSha=sha(t.runs[0][1]),
                       secondRunIdentical=t.runs[0] == t.runs[1]),
        easyOpening=[dict(id=fid, identical={k: t.frag(t.m, fid)[k] for k in keys} ==
                          {k: t.frag(t.before, fid)[k] for k in keys}) for fid in ('P0', 'P1', 'P2')] +
        [dict(encounter=r['id'], percent=r['percent'], distance=r['distance'],
              identical=(r['flight'], r['distance']) == (o['flight'], o['distance']))
         for r, o in zip(t.m['encounters'][:2], t.before['encounters'][:2])],
        spans=t.spans, minimumUsableSpan=MIN_SPAN,
        rightwardEndpoint=dict(before=[r for r in t.before['encounters'] if r['id'] == 'S07-01'][0]['flight'][0],
                               candidate=[r for r in t.m['encounters'] if r['id'] == 'S07-01'][0]['flight'][0]),
        upwardTurn=dict(encounter='S07-01', distance=rows['S07-01']['distance'], percent=rows['S07-01']['percent']),
        laterTerrain=dict(translation=t.shift, fragments=later,
                          allShapesIdentical=all(f['shapeSha'] == f['beforeShapeSha'] for f in later),
                          encounterIds=[r['id'] for r in t.m['encounters'][6:]]),
        yellow=dict(before=ob, candidate=nb, removed=sorted(set(ob) - set(nb)), added=sorted(set(nb) - set(ob)),
                    moved=sorted(k for k in set(ob) & set(nb) if ob[k] != nb[k]),
                    note='Yellow zones are re-placed by the generator from route contacts and re-merged under the '
                         '1620/540 rules; ids are regenerated per run.')))


if __name__ == '__main__':
    unittest.main()
