"""TASK-668: the four added rightward opening transfers form a mixed combination.

Generates the extended layout twice through tools/retune_extended_level.py,
imports the SVG and checks the opening from imported polygons: a right/up
ceiling underside catch, a descent onto a sloped bounce face, a right/up
rebound and a mostly horizontal transfer to the upward-turn departure. Surface
edges are found independently of the generator: the contact must lie on a
polygon edge whose interior side matches the intended surface. The pre-change
v7 generation frozen under artifacts/TASK-668/before is the comparison point;
relabelling that stair with the new actions must fail the same checks.
TASK-669: CombinationReplayTests boot the real index.html with the shipped
leveldata.js and replay the four added transfers continuously with real mouse
events and production physics() from one gravity-produced entry fixture (a
zero-speed drop onto P2), with the game's 540-unit acquisition radius. They
also probe the easy transfers and the upward turn, and run a bounded local
shortcut search around the changed panels: the v9 retune must add no skip
family beyond those of the pre-change v7 baseline, and the frozen v8 control
(the layout shipped before the retune) shows the families it fixes.
Set OPENING_VARIETY_EVIDENCE_DIR to write contact-vectors.json, geometry.json,
angles.json and preservation.json, plus combination-replay.json,
route-regressions.json and local-shortcuts.json.
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
from contextlib import ExitStack
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
SHIPPED = ROOT / 'artifacts/levels'
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
        # The shipped authoring files are this generation (TASK-669).
        self.assertEqual(self.svg, (SHIPPED / 'extended-mountain.svg').read_bytes())
        self.assertEqual(self.runs[0][1], (SHIPPED / 'extended-mountain-measurements.json').read_bytes())
        self.assertEqual(self.level, json.loads((SHIPPED / 'extended-mountain.level.json').read_text()))

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
        self.assertGreater(left, 0)
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
        # Later terrain may be reshaped to remove bypasses; preserve semantic
        # route connectivity and the deliberate 150% turn, not old positions.
        up = next(r for r in self.m['encounters'] if r['id'] == 'S07-01')
        self.assertAlmostEqual(up['distance'],1.5*GRAPPLE_RANGE,delta=COORD_TOL)
        self.assertEqual([r['id'] for r in self.m['encounters'][6:]],
                         [r['id'] for r in self.before['encounters'][6:]])
        self.__class__.shift=None

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
    dump('angles.json', dict(
        minimum=MIN_INTERIOR_ANGLE, minInteriorAngle=s['minInteriorAngle'], polygons=s['anglePolygons'],
        polygonsPass=s['anglePolygonsPass'], vertices=s['angleVertices'],
        perPolygon=[dict(id=a['id'], role=a['role'], minAngle=a['minAngle'], pass_=a['pass'])
                    for a in t.report['angles']],
        changedPanels={a['id']: a['angles'] for a in t.report['angles']
                       if a['id'] in {t.ids[k] + '-body0' for k in ('R1', 'R2', 'R3', 'R4')}}))
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


# TASK-669 production replay. Fixture: a zero-speed drop 30 units above the
# middle of P2 (the end of the easy opening); gravity makes the entry state.
# Inputs are real document mouse events at fixed ticks; aims are derived from
# the shipped polygons. Nothing writes position, velocity or grapple state
# after the fixture (tools/opening_combination_replay.js).
FIXTURE = dict(panel='P2', fraction=.5, drop=30)
# The added panels, the tested pairs (source -> beyond its successor) and the
# ROUTE_PROBE policy grid (tools/probe_level_routes.js).
SHORTCUT_PAIRS = [('P2', 'P4'), ('P2', 'P5'), ('P2', 'P6'), ('P3', 'P5'), ('P3', 'P6'),
                  ('P4', 'P6'), ('P4', 'P7'), ('P5', 'P7')]
PUMPS, FRACTIONS = (0, 1, 2, 3, 5), (.2, .5, .8)
# The v8 layout shipped before the v9 retune (frozen generation): its grid
# demonstrates the four skip families v9 fixes.
BEFORE_V8 = ROOT / 'artifacts/TASK-669/before-v8'


def surface_aim(bounds, panel, dx, dy=0.):
    """World aim dx right of a panel's left edge: dy below its top (R1: below its underside)."""
    b = bounds[panel]
    return [b['x0'] + dx, (b['y1'] if panel == 'R1' else b['y0']) + dy]


def catch_inputs(bounds):
    """Three pumps on P2, then the ceiling catch (released at the R1 underside contact)."""
    a = lambda *k: surface_aim(bounds, *k)
    return [dict(tick=1, type='down', aim=a('P2', 435)), dict(tick=13, type='up'),        # pump 1 (released at the bounce)
            dict(tick=59, type='down', aim=a('P2', 548.714)), dict(tick=80, type='up'),   # pump 2
            dict(tick=177, type='down', aim=a('P2', 730.579)), dict(tick=222, type='up'),  # pump 3
            dict(tick=332, type='down', aim=a('R1', 150, -2)),   # rising past R1's left end: grapple its underside
            dict(tick=344, type='up')]                           # release at the ceiling catch


def combination_inputs(bounds):
    # Recorded real inputs for the fixed v10 opening; geometry changes must
    # earn a new successful continuous replay rather than adapting the test.
    return json.loads((TOOLS / 'fixtures/harder-opening-inputs.json').read_text())['inputs']


def first_seq(contacts):
    seq = []
    for c in contacts:
        pid = c['id'].split('-')[0]
        if not seq or seq[-1] != pid:
            seq.append(pid)
    return seq


class CombinationReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from browser_test_support import start_browser_test, wait_for_boot_run
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.level = json.loads((SHIPPED / 'extended-mountain.level.json').read_text())
        cls.m = json.loads((SHIPPED / 'extended-mountain-measurements.json').read_text())
        cls.ids = cls.m['routeMap']['addedFragments']
        cls.before_level = import_svg((BEFORE / 'extended-mountain.svg').read_bytes())
        # Control: the v8 layout shipped before the v9 retune (frozen generation).
        cls.before_v8 = json.loads((BEFORE_V8 / 'extended-mountain.level.json').read_text())
        cls.pages = {}
        for name, script in (('replay', 'opening_combination_replay.js'), ('probe', 'probe_level_routes.js')):
            page = cls.browser.new_page(viewport={'width': 1280, 'height': 720})
            page.errors = []
            page.on('pageerror', lambda e, p=page: p.errors.append(str(e)))
            page.goto(cls.url)
            wait_for_boot_run(page)
            page.add_script_tag(path=str(TOOLS / script))
            cls.pages[name] = page
        cls.evidence = {}

    @classmethod
    def tearDownClass(cls):
        if EVIDENCE:
            out = Path(EVIDENCE)
            out.mkdir(parents=True, exist_ok=True)
            for name, data in cls.evidence.items():
                (out / name).write_text(json.dumps(data, separators=(',', ':')) + '\n')

    def bounds(self, level):
        polys = fragment_polys(level or self.level)
        ids = self.ids
        out = {}
        for sem, fid in [('P2', 'P2')] + [(k, ids[k]) for k in ('R1', 'R2', 'R3', 'R4')] + [('P7', 'P7')]:
            pts = [p for poly in polys[fid] for p in poly]
            out[sem] = dict(id=fid, x0=min(x for x, _ in pts), x1=max(x for x, _ in pts),
                            y0=min(y for _, y in pts), y1=max(y for _, y in pts))
        return out

    def replay(self, inputs, level=None, budget=2400):
        stop = dict(id=self.ids['R4'], ny='up')
        return self.pages['replay'].evaluate('o => OPENING_REPLAY.run(o)',
                                             dict(level=level, fixture=FIXTURE, inputs=inputs, budget=budget, stopOn=stop))

    def probe(self, level=None, **options):
        if level is not None:
            options['level'] = level
        # A passed level gets the shipped game's importedMountainLevel() profile (540-unit acquisition).
        r = self.pages['probe'].evaluate('o => ROUTE_PROBE.run(o.level ? {...o, level: importedMountainLevel(o.level)} : o)',
                                         options)
        return {k: r[k] for k in ('source', 'target', 'fraction', 'pumps', 'drop', 'aimOffset', 'budget', 'setup',
                                  'arrival', 'hit', 'bounces', 'ticks')}

    def test_10_continuous_combination(self):
        ids, b = self.ids, self.bounds(self.level)
        inputs = combination_inputs(b)
        runs = [self.replay(inputs) for _ in range(2)]
        log = runs[0]
        self.assertEqual(runs[0], runs[1])                     # deterministic
        self.assertEqual(log['layoutId'], self.level['layoutId'])
        self.assertEqual(self.pages['replay'].errors, [])
        # Only document mouse events after the fixture; the replay moves continuously.
        self.assertEqual(log['acquisitionRadius'], 540)
        self.assertEqual([e['type'] for e in log['inputs']], ['down', 'up'] * 13)
        self.assertEqual(log['fixture']['vx'], 0)
        self.assertEqual(log['fixture']['vy'], 0)
        self.assertLess(log['maxStep'], 200)
        # The first seven inputs are the P2 pumps and the in-range ceiling shot.
        early = [c['id'] for c in log['contacts'] if c['tick'] < inputs[6]['tick']]
        self.assertEqual(early, ['P2-body0'] * len(early))
        self.assertGreaterEqual(len(early), 3)
        after = [c for c in log['contacts'] if c['id'] != 'P2-body0']
        self.assertEqual(first_seq(after), [ids[k] for k in ('R1', 'R2', 'R3', 'R4')])
        by = lambda k: [c for c in after if c['id'] == ids[k] + '-body0']
        catch, slope, r3, r4 = by('R1')[0], by('R2')[0], by('R3')[0], by('R4')[0]
        # 1 ceiling catch: moving up-right into the R1 underside (contact normal points down).
        self.assertGreater(catch['ny'], .99)
        self.assertGreater(catch['vxIn'], 0)
        self.assertLess(catch['vyIn'], 0)
        self.assertGreater(catch['y'], b['R1']['y1'])
        # 2 release and down-right landing on the sloped face.
        self.assertGreater(slope['vxIn'], 0)
        self.assertGreater(slope['vyIn'], 0)
        self.assertTrue(0 < slope['nx'] < .2 and slope['ny'] < -.98, slope)
        self.assertGreater(slope['y'], catch['y'])
        # 3 right/up rebound off the slope onto the R3 top.
        self.assertGreater(slope['vxOut'], 0)
        self.assertLess(slope['vyOut'], 0)
        self.assertEqual((r3['nx'], r3['ny']), (0, -1))
        self.assertLess(r3['y'], slope['y'])
        # 4 mostly horizontal rightward arrival on the R4 top (the upward-turn departure).
        last_r3 = by('R3')[-1]
        dx, dy = r4['x'] - last_r3['x'], r4['y'] - last_r3['y']
        self.assertEqual((r4['nx'], r4['ny']), (0, -1))
        self.assertGreater(dx, 0)
        self.assertLessEqual(abs(dy), .25 * dx)
        self.assertGreater(r4['vxIn'], 0)
        self.assertEqual(log['stopped'], r4)
        attach = [(g['event'], g['id']) for g in log['grapple']]
        pair = lambda pid: [('attach', pid + '-body0'), ('detach', pid + '-body0')]
        # Three P2 pumps, the ceiling catch and six underside holds, then three R3 attachments (the press aimed
        # at the R2 face catches R3 after the rebound). Never a panel beyond the next one.
        self.assertEqual(attach, pair('P2') * 3 + pair(ids['R1']) * 7 + pair(ids['R3']) * 3)
        transitions = []
        for name, enc, c in (('ceiling catch', 'OPEN-P2-R1', catch), ('down-right slope landing', 'OPEN-R1-R2', slope),
                             ('right/up rebound arrival', 'OPEN-R2-R3', r3), ('horizontal arrival', 'OPEN-R3-R4', r4)):
            transitions.append(dict(transfer=name, encounter=enc, contact=c))
        self.__class__.evidence['combination-replay.json'] = dict(
            method='Real index.html with the shipped leveldata.js; tools/opening_combination_replay.js dispatches '
                   'document mousedown/mousemove/mouseup at the listed ticks and calls production physics() once per '
                   'tick. The fixture is the only placement; no position, velocity or grapple state is written later.',
            fixture=dict(log['fixture'], note='zero-speed drop 30 units above the middle of P2 (end of the easy '
                                              'opening); the entry velocity is produced by gravity and a P2 bounce'),
            layoutId=log['layoutId'], inputs=log['inputs'], transitions=transitions,
            r3ToR4=dict(dx=dx, dy=dy, absDyOverDx=abs(dy) / dx), grapple=log['grapple'],
            contacts=log['contacts'], ticks=log['ticks'], maxStepPerTick=log['maxStep'],
            secondRunIdentical=runs[0] == runs[1], sequence=first_seq(after),
            semantic=dict(R1=ids['R1'], R2=ids['R2'], R3=ids['R3'], R4=ids['R4']))

    def test_11_route_regressions(self):
        ids = self.ids
        cases = [('S06-03', 'P0', 'P1', dict(fraction=.8, pumps=1)), ('S06-04', 'P1', 'P2', dict(fraction=.8, pumps=1)),
                 ('S07-01 upward turn', ids['R4'], 'P7', dict(fraction=.2, pumps=1,lastAimOffset=.15))]
        out = []
        for name, source, target, policy in cases:
            r = self.probe(source=source, target=target, budget=1800, **policy)
            self.assertIsNotNone(r['arrival'], name)
            self.assertIsNotNone(r['hit'], name)
            self.assertEqual(r['hit']['id'], target + '-body0', name)
            out.append(dict(case=name, intended=target, reached=r['hit']['id'], **r))
        # The replay's R4 arrival is the upward turn's departure surface.
        up = next(e for e in self.m['encounters'] if e['id'] == 'S07-01')
        self.assertEqual(up['fromFragment'], ids['R4'])
        self.assertEqual(self.pages['probe'].errors, [])
        self.__class__.evidence['route-regressions.json'] = dict(
            method='ROUTE_PROBE (tools/probe_level_routes.js): zero-speed drop on the source, real pointer events, '
                   'production physics(); a hit is the first contact/attachment on a later panel.',
            cases=out)

    def grid(self, level):
        hits = []
        for source, target in SHORTCUT_PAIRS:
            for pumps in PUMPS:
                for fraction in FRACTIONS:
                    r = self.probe(level=level, source=source, target=target, pumps=pumps, fraction=fraction, budget=1500)
                    h = r['hit']
                    beyond = bool(h) and int(h['id'].split('-')[0][1:]) > int(source[1:]) + 1
                    hits.append(dict(source=source, target=target, pumps=pumps, fraction=fraction, beyond=beyond,
                                     hit=h and {k: h[k] for k in ('kind', 'id', 'tick', 'x', 'y', 'vx', 'vy')}))
        return hits

    def free_flights(self, level):
        """Every ceiling-release variant after the catch, then no input: what does the slope rebound reach first?"""
        b = self.bounds(level)
        r1, under = b['R1'], b['R1']['y1'] - 2
        i1 = catch_inputs(b)
        log = self.pages['replay'].evaluate('o => OPENING_REPLAY.run(o)', dict(
            level=level, fixture=FIXTURE, inputs=i1[:-1], budget=400, stopOn=dict(id=b['R1']['id'], ny='down')))
        if not log['stopped']:
            return dict(entry='no ceiling catch with the shipped catch inputs', variants=[])
        t1, out = log['stopped']['tick'], []
        # Contacts carry the tick they happen in; the release is the next tick's input, as in catch_inputs().
        t1 += 1
        i1 = i1[:-1] + [dict(tick=t1, type='up')]
        for d in (0, 4, 10):
            for ax in (r1['x0'] + 40, r1['x0'] + 250, (r1['x0'] + r1['x1']) / 2, r1['x1'] - 230, r1['x1'] - 30):
                for h in (3, 6, 10, 16, 24, 34, 48):
                    inputs = i1 + [dict(tick=t1 + d + 2, type='down', aim=[ax, under]),
                                   dict(tick=t1 + d + 2 + h, type='up')]
                    log = self.pages['replay'].evaluate('o => OPENING_REPLAY.run(o)', dict(
                        level=level, fixture=FIXTURE, inputs=inputs, budget=t1 + 700))
                    after = [c for c in log['contacts'] if c['tick'] > t1 + d + 2 + h]
                    r4top = [c for c in after if c['id'] == b['R4']['id'] + '-body0' and c['ny'] == -1]
                    r3top = [c for c in after if c['id'] == b['R3']['id'] + '-body0' and c['ny'] == -1]
                    skip = bool(r4top) and (not r3top or r3top[0]['tick'] > r4top[0]['tick'])
                    out.append(dict(releaseDelay=d, holdAimX=round(ax, 3), hold=h, sequence=first_seq(after)[:4],
                                    r4TopBeforeR3=skip, firstR4Top=r4top[0] if r4top else None))
        return dict(entry=dict(catchTick=t1, inputs=i1), variants=out)

    def test_12_local_shortcuts(self):
        shipped, before, old = self.grid(None), self.grid(self.before_level), self.grid(self.before_v8)
        sem = lambda pid: next((k for k, v in self.ids.items() if v == pid), pid)
        family = lambda h: [sem(h['source']), sem(h['hit']['id'].split('-')[0])]
        families = lambda hits: sorted({tuple(family(h)) for h in hits if h['beyond']})
        before_families = set(families(before))
        new = [list(f) for f in families(shipped) if f not in before_families]
        # No skip family beyond the v7 baseline's, at any pump count of the grid.
        self.assertEqual(new, [], [h for h in shipped if h['beyond']])
        self.assertEqual([h for h in shipped if h['beyond']], [])
        # The control (v8 before the retune) shows the four families the retune fixes.
        old_new = [list(f) for f in families(old) if f not in before_families]
        self.assertTrue(any(h['beyond'] for h in old), 'The preserved control must reproduce a bypass')
        flights = self.free_flights(None)
        free = flights['variants']
        # After the ceiling catch, no free slope rebound flies over R3 onto the R4 top.
        self.assertEqual(len(free), 105)
        self.assertFalse(any(f['r4TopBeforeR3'] for f in free), [f for f in free if f['r4TopBeforeR3']])
        self.assertEqual(self.pages['probe'].errors + self.pages['replay'].errors, [])
        self.__class__.evidence['local-shortcuts.json'] = dict(
            coverage='Bounded local policies only, not a proof of global shortcut absence and not a full-climb proof.',
            policies=dict(
                probeGrid=dict(tool='tools/probe_level_routes.js ROUTE_PROBE (importedMountainLevel, 540 radius)',
                               pairs=SHORTCUT_PAIRS, pumps=PUMPS, fractions=FRACTIONS,
                               entry='zero-speed drop 30 above the source top at fraction',
                               skip='first contact or attachment on a panel beyond the successor'),
                freeFlight=dict(entry=FIXTURE, prefix=flights['entry'],
                                variants='3 hold delays x 5 ceiling-hold aims x 7 hold lengths after the R1 catch, '
                                         'then no input', skip='R4 top before R3 top')),
            newFamiliesVersusV7=new,
            shippedBeyondSuccessor=[dict(h, family=family(h)) for h in shipped if h['beyond']],
            beforeV7Families=[list(f) for f in sorted(before_families)],
            demonstratedAndFixed=dict(
                control=dict(level=str(BEFORE_V8 / 'extended-mountain.level.json'), layoutId=self.before_v8['layoutId'],
                             newFamiliesVersusV7=old_new, hits=[dict(h, family=family(h)) for h in old if h['beyond']]),
                fix='v9 opening retune (tools/retune_extended_level.py OPENING): R1 lift 1250, width 2700, share .52; '
                    'R2 lift -650; R3 lift 550, width 1400; R4 lift 500, gap 1000. Later terrain moves with R4, so '
                    'L1/L2/P7 leave the pumped apex plus 540 radius of P2, R1, R2 and R3, and R1 shields P2',
                shippedFamilies=families(shipped)),
            freeFlightResults=dict(variants=len(free), r4TopBeforeR3=sum(f['r4TopBeforeR3'] for f in free),
                                   outcomes=sorted({'>'.join(f['sequence'][:3]) for f in free}), runs=free),
            probeGrid=dict(shipped=shipped, beforeV7=before, beforeV8=old))
