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
TASK-676: the whole starting rightward section is varied. Candidate selection
(recorded in opening-patterns.json): OPENING_VARIETY_CANDIDATE=DIR, else
OPENING_VARIETY_EVIDENCE_DIR/candidate when it holds a generation, else the
shipped artifacts/levels. test_13 classifies every rightward transfer from the
imported polygons (release jump, ceiling catch, descending slope landing,
upward rebound, exposed traverse) and requires no adjacent repeat after the
first two; test_14 compares the candidate with the TASK-675 candidate by
semantic id (purple extension and later route unchanged, lower terrain under
the late route, original source, corner/clearance rules, opening span).
test_15 replays tools/fixtures/opening-section-inputs.json from the spawn with
production inputs through the whole section to the upward-turn departure;
test_16 drops the three leftmost late panels onto lower terrain; test_17 draws
opening.png (candidate SVG vs runtime draw()).
Set OPENING_VARIETY_EVIDENCE_DIR to write contact-vectors.json, geometry.json,
angles.json and preservation.json, plus combination-replay.json,
route-regressions.json and local-shortcuts.json, and (TASK-676)
opening-patterns.json, opening-replay.json and opening.png.
"""
import base64
import copy
import hashlib
import io
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
NAMES = ('extended-mountain.svg', 'extended-mountain-measurements.json', 'extended-mountain.level.json')


def candidate_dir():
    """The layout under test: explicit candidate, the evidence candidate, else the shipped files."""
    if os.environ.get('OPENING_VARIETY_CANDIDATE'):
        return Path(os.environ['OPENING_VARIETY_CANDIDATE']), 'OPENING_VARIETY_CANDIDATE'
    if EVIDENCE and all((Path(EVIDENCE) / 'candidate' / n).exists() for n in NAMES):
        return Path(EVIDENCE) / 'candidate', 'OPENING_VARIETY_EVIDENCE_DIR/candidate'
    return SHIPPED, 'shipped artifacts/levels'


CANDIDATE, SELECTED_BY = candidate_dir()
# The TASK-675 candidate (purple extension, eight-platform lower chain): the
# comparison point for what the varied section must preserve.
PREVIOUS = ROOT / 'artifacts/TASK-675/candidate'
SECTION_INPUTS = TOOLS / 'fixtures/opening-section-inputs.json'
# The preserved concept source, unchanged since TASK-650 (artifacts/TASK-650/hashes.json).
ORIGINAL_SOURCE = {
    'artifacts/level/extended-mountain.svg': '0606d25f6afc903f7946a6441844654fae4701128ce48b6393b61c0afaf40756',
    'artifacts/level/extended-mountain-measurements.json':
        '30bc5400d49b6e45b16a9c9d579eb622c7958ed28046d326ae799f1c924d5edc',
}
MECHANICS = ('ceiling-catch', 'descending-slope', 'upward-rebound', 'exposed-traverse')
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
        ok = {'ceiling': move == 'rise' and dy < 0, 'descent': move == 'descent', 'rebound': dx > 0 and dy < 0,
              'horizontal': move == 'horizontal' and abs(dy) <= .25 * abs(dx)}[want]
        if not ok:
            out.append('%s moves %s (dx %.1f, dy %.1f), expected %s' % (eid, move, dx, dy, want))
        if want == 'descent' and dep['kind'] != 'underside':
            out.append('%s departs from %s, expected the ceiling underside' % (eid, dep['kind']))
        if want == 'descent' and arr['slopeDegrees'] < 5:
            out.append('%s landing face is not sloped' % eid)
    return out, vectors


def merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


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


def classify(dep, arr, dx, dy):
    """A rightward transfer's pattern from its departure/arrival surfaces and contact vector."""
    if dx <= 0:
        return 'not rightward'
    if arr['kind'] == 'underside' and dy < 0:
        return 'ceiling-catch'
    if arr['kind'] == 'slope' and dy > 0:
        return 'descending-slope'
    if dep['kind'] == 'slope' and arr['kind'] == 'top' and dy < 0:
        return 'upward-rebound'
    if dep['kind'] == 'top' and arr['kind'] == 'top':
        return 'exposed-traverse' if abs(dy) <= .25 * dx else 'release-jump' if dy < 0 else 'other'
    return 'other'


def section_patterns(m, level, report=None):
    """Every transfer of the starting rightward section, classified from imported geometry."""
    fs = m['fragments']
    right_end, _, _ = retune.opening_sections([tuple(r['flight'][0]) for r in m['encounters']] +
                                              [tuple(m['encounters'][-1]['flight'][1])])
    polys = fragment_polys(level)
    sem = {f['id']: f['semanticId'] for f in fs}
    checker = {t['encounter']: t for t in (report or {}).get('transfers', [])}
    out = []
    for k, r in enumerate(m['encounters'][:right_end]):
        a, b = r['flight']
        dx, dy = b[0] - a[0], b[1] - a[1]
        dep, arr = surface_at(polys[r['fromFragment']], a), surface_at(polys[r['toFragment']], b)
        t = checker.get(r['id'])
        out.append(dict(index=k + 1, encounter=r['id'], semantic='%s->%s' % (sem[r['fromFragment']], sem[r['toFragment']]),
                        fromFragment=r['fromFragment'], toFragment=r['toFragment'],
                        pattern=classify(dep, arr, dx, dy), labelledPattern=r.get('pattern'),
                        departureSurface=dep['kind'], arrivalSurface=arr['kind'], contactSurface=arr['edge'],
                        arrivalSlopeDegrees=arr['slopeDegrees'], dx=dx, dy=dy, rise=-dy,
                        absDyOverDx=abs(dy) / dx if dx else None,
                        measuredGap=r['distance'], gapPercent=r['percent'],
                        checkerGap=t and t['computedDistance'], usableSpan=arr['span'], departureSpan=dep['span'],
                        departureContact=a, arrivalContact=b, action=r['action']))
    return out, fs[right_end]['id']


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
        shields = retune.add_shortcut_shields
        retune.add_shortcut_shields = lambda m, spec: None
        try:
            cls.unshielded = retune.tune(json.loads(SOURCE.read_text()), opening=retune.OPENING,
                                         yellow_clearance=retune.YELLOW_CLEARANCE)
        finally:
            retune.add_shortcut_shields = shields
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
        # The selected candidate (TASK-676; the shipped files when none is selected) is this generation.
        self.assertEqual(self.svg, (CANDIDATE / NAMES[0]).read_bytes())
        self.assertEqual(self.runs[0][1], (CANDIDATE / NAMES[1]).read_bytes())
        self.assertEqual(self.level, json.loads((CANDIDATE / NAMES[2]).read_text()))

    def test_02_combination_follows_actual_geometry(self):
        violations, vectors = combination_violations(self.m, self.level)
        self.assertEqual(violations, [])
        self.assertEqual(self.m['routeMap']['openingCombination'], ADDED)
        # The departure of the upward turn is the horizontal transfer's arrival.
        up = next(r for r in self.m['encounters'] if r['id'] == 'S07-01')
        self.assertEqual(up['fromFragment'], self.m['lowerCatchExtension']['firstUpDeparture'])
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

    def test_07_preserves_opening_shapes_and_later_connectivity(self):
        keys = ('width', 'height', 'kind', 'polys')
        for fid in ('P0', 'P1', 'P2'):
            self.assertEqual({k: self.frag(self.m, fid)[k] for k in keys},
                             {k: self.frag(self.before, fid)[k] for k in keys}, fid)
        for row, target in zip(self.m['encounters'][:2], (120,160)):
            self.assertAlmostEqual(row['percent'], target, places=5)
        # Later terrain may be reshaped to remove bypasses; preserve semantic
        # route connectivity and the deliberate 150% turn, not old positions.
        up = next(r for r in self.m['encounters'] if r['id'] == 'S07-01')
        self.assertAlmostEqual(up['distance'],1.5*GRAPPLE_RANGE,delta=COORD_TOL)
        # The purple extension (TASK-675) inserts NG-* encounters after the first leftward section;
        # the varied lower chain (TASK-676) changes the count before the upward turn.
        ids = [r['id'] for r in self.m['encounters']]
        self.assertEqual([i for i in ids[ids.index('S07-01'):] if not i.startswith('NG-')],
                         [r['id'] for r in self.before['encounters'][6:]])
        self.__class__.shift=None

    def test_08_geometry_rules(self):
        s = self.report['summary']
        self.assertTrue(s['pass'], self.report['failureMessages'])
        n = len(self.m['fragments'])
        self.assertEqual((s['fragments'], s['transfers'], s['fragmentPairs']), (n, n - 1, n * (n - 1) // 2))
        self.assertEqual(s['pairsPass'], n * (n - 1) // 2)
        self.assertGreaterEqual(s['minInteriorAngle'], MIN_INTERIOR_ANGLE)
        self.assertGreaterEqual(s['minDragSolidClearance'], 1620)
        self.assertGreaterEqual(s['minYellowPairClearance'], 540)
        self.assertEqual(s['solidBounceGrapplable'], s['solidElements'])
        allowed = {frozenset(p) for p in self.m['allowedGrapplePairs']}
        self.assertEqual(allowed, set())
        for p in self.report['pairs']:
            # Only the checker's scoped purple-internal transfers (0 < gap <= 270) are exempt.
            if frozenset((p['a'], p['b'])) not in allowed and p['rule'] != 'noGrappleInternal':
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

    def test_13_opening_patterns(self):
        rows, departure = section_patterns(self.m, self.level, self.report)
        sem = {f['id']: f['semanticId'] for f in self.m['fragments']}
        # The section ends at the upward-turn departure (X10), the start of S07-01.
        up = next(r for r in self.m['encounters'] if r['id'] == 'S07-01')
        self.assertEqual(up['fromFragment'], departure)
        self.assertEqual(sem[departure], 'X10')
        self.assertEqual(rows[-1]['toFragment'], departure)
        for r in rows:
            self.assertEqual(r['pattern'], r['labelledPattern'], r)
            self.assertGreater(r['dx'], 0, r)
            self.assertGreaterEqual(r['usableSpan'], MIN_SPAN, r)
        self.assertGreaterEqual(rows[0]['departureSpan'], MIN_SPAN)
        # The first two stay the easier 120% / 160% release jumps between unchanged shapes.
        self.assertEqual([r['pattern'] for r in rows[:2]], ['release-jump'] * 2)
        self.assertEqual([round(r['gapPercent'], 3) for r in rows[:2]], [120, 160])
        keys = ('width', 'height', 'kind', 'polys')
        for fid in ('P0', 'P1', 'P2'):
            self.assertEqual({k: self.frag(self.m, fid)[k] for k in keys}, {k: self.frag(self.before, fid)[k] for k in keys})
        # The required ordered combination R1-R4 is intact.
        self.assertEqual([r['semantic'] for r in rows[2:6]], ['P2->R1', 'R1->R2', 'R2->R3', 'R3->R4'])
        self.assertEqual([r['pattern'] for r in rows[2:6]], list(MECHANICS))
        rest = [r['pattern'] for r in rows[2:]]
        repeats = [(rows[k + 1]['semantic'], rows[k + 2]['semantic']) for k in range(1, len(rows) - 2)
                   if rows[k + 1]['pattern'] == rows[k + 2]['pattern']]
        self.assertEqual(repeats, [])
        self.assertTrue(set(MECHANICS) <= set(rest[4:]), rest)
        self.assertEqual(set(rest), set(MECHANICS))
        # Added gaps are measured release gaps >= 200% R; the checker measures the same polygons.
        for r in rows[2:]:
            self.assertGreaterEqual(r['measuredGap'], 2 * GRAPPLE_RANGE - .01, r)
            self.assertAlmostEqual(r['checkerGap'], r['measuredGap'], delta=.01)
        base = self.m['routeMap']['baselineSpans']['rightward']
        span = rows[-1]['arrivalContact'][0] - rows[0]['departureContact'][0]
        self.assertGreaterEqual(span / base, 3)
        self.__class__.patterns = dict(transfers=rows, departure=dict(id=departure, semantic=sem[departure]),
                                       rightwardContactSpan=span, baselineRightwardSpan=base, ratio=span / base,
                                       adjacentRepeatsAfterFirstTwo=repeats, sequence=[r['pattern'] for r in rows])

    def test_14_section_preservation(self):
        prev = json.loads((PREVIOUS / NAMES[1]).read_text())
        new, old = ({f['semanticId']: f for f in m['fragments']} for m in (self.m, prev))
        order = [f['semanticId'] for f in self.m['fragments']]
        cut = order.index('X10')
        keys = ('x', 'y', 'width', 'height', 'kind', 'polys')
        # The upward-turn departure: X10 now, X8 (the legacy endpoint) in the eight-platform chain.
        dep_old = next(f['semanticId'] for f in prev['fragments'] if f['id'] == prev['lowerCatchExtension']['firstUpDeparture'])
        twin = lambda s: dep_old if s == 'X10' else s
        # TASK-677 shortcut shields (R1 fin, X1 trim, NG1 post) are the only reshaped panels: the same
        # generator without them reproduces the previous geometry, and the shipped layout differs from
        # that shield-free generation in exactly the shielded fragments.
        unshielded = {f['semanticId']: f for f in self.unshielded['fragments']}
        shielded = sorted({k['semanticId'] for k in self.m['shortcutShields']['fins']}
                          | {self.m['shortcutShields'][k]['semanticId'] for k in ('trim', 'post')})
        self.assertEqual(shielded, ['NG1', 'R1', 'X1'])
        self.assertEqual(sorted(s for s in order if any(new[s][k] != unshielded[s][k] for k in keys)), shielded)
        same = lambda s: {k: unshielded[s][k] for k in keys} == {k: old[twin(s)][k] for k in keys}
        # Easy opening, R1-R4, X10 and later terrain except the raised L1/L2 are identical.
        kept = [s for s in order[:7]] + [s for s in order[cut:] if s not in ('L1', 'L2')]
        changed = [s for s in kept if not same(s)]
        self.assertEqual(changed, [])
        # v15 adds vertical variety within the existing right/left runs. The
        # upper turn, purple chute and all later panels remain frozen.
        for sem in ('X2', 'X5', 'X9'):
            row = next(r for r in self.m['encounters'] if r['toFragment'] == new[sem]['id'])
            a, b = row['flight']
            self.assertGreaterEqual(a[1] - b[1], 1000 - .01, sem)
            self.assertGreater(b[0] - a[0], a[1] - b[1], sem)
        for sem in ('L1', 'L2'):
            row = next(r for r in self.m['encounters'] if r['toFragment'] == new[sem]['id'])
            a, b = row['flight']
            self.assertLess(b[0], a[0], sem)
            self.assertGreaterEqual(a[1] - b[1], 700 - .01, sem)
            self.assertLess(a[1] - b[1], a[0] - b[0], sem)
            self.assertEqual(new[sem]['polys'], old[sem]['polys'])
        self.assertEqual(dep_old, 'X8')
        self.assertEqual(sorted(set(order) - set(old)), ['X10', 'X9'])
        self.assertEqual(sorted(set(old) - set(order)), [])
        # Route successors after the section keep their ids and measured gaps.
        rows_new = {r['id']: r for r in self.m['encounters']}
        ids_new = [r['id'] for r in self.m['encounters']]
        ids_old = [r['id'] for r in prev['encounters']]
        tail_new, tail_old = ids_new[ids_new.index('S07-01'):], ids_old[ids_old.index('S07-01'):]
        self.assertEqual(tail_new, tail_old)
        gaps = {r['id']: abs(r['distance'] - rows_new[r['id']]['distance']) for r in prev['encounters'] if r['id'] in tail_new}
        # Only shield transfers and the raised leftward ledges may change here; all keep the 200% minimum.
        ids_by_sem = {f['semanticId']: f['id'] for f in self.m['fragments']}
        touching = {r['id'] for r in self.m['encounters'] if {r['fromFragment'], r['toFragment']} & {ids_by_sem[s] for s in shielded + ['L1', 'L2']}}
        moved_gaps = sorted(k for k, v in gaps.items() if v >= 1e-6)
        self.assertTrue(set(moved_gaps) <= touching, moved_gaps)
        self.assertEqual(moved_gaps, ['NG-ENTRY', 'OPEN-L1-L2', 'OPEN-L2-P4'])
        for k in moved_gaps:
            self.assertGreaterEqual(rows_new[k]['distance'], 2 * GRAPPLE_RANGE - .01, k)
        self.assertLess(max(v for k, v in gaps.items() if k not in moved_gaps), 1e-6)
        sem = lambda m, fid: next(f['semanticId'] for f in m['fragments'] if f['id'] == fid)
        self.assertEqual([tuple(twin(sem(self.m, r[k])) for k in ('fromFragment', 'toFragment')) for r in self.m['encounters'] if r['id'] in tail_new],
                         [(sem(prev, r['fromFragment']), sem(prev, r['toFragment'])) for r in prev['encounters'] if r['id'] in tail_old])
        # Purple extension: the same zone, panels (semantic NG-*) and encounters.
        self.assertEqual(self.m['noGrappleZones'], prev['noGrappleZones'])
        pe, po = self.m['purpleExtension'], prev['purpleExtension']
        self.assertEqual([sem(self.m, i) for i in [pe['approach'], pe['exit']] + pe['internal']],
                         [sem(prev, i) for i in [po['approach'], po['exit']] + po['internal']])
        self.assertEqual(pe['encounters'], po['encounters'])
        self.assertEqual(pe['upperTranslation'], po['upperTranslation'])
        ext, ext_old = self.m['lowerCatchExtension'], prev['lowerCatchExtension']
        self.assertEqual(ext['upperTranslation'], ext_old['upperTranslation'])
        # Lower terrain under the late route: the late route stays inside the lower extent.
        fs = self.m['fragments']
        fids = [f['id'] for f in fs]
        lower = fs[:fids.index(ext['firstUpDeparture']) + 1]
        late = fs[fids.index(pe['exit']) + 1:]
        xs = lambda group: [x for f in group for b in retune.svg.bodies(f) for x, _ in b]
        cover = lambda group, span: sum(max(0, min(b, span[1]) - max(a, span[0])) for a, b in
                                        merge([(min(xs([f])), max(xs([f]))) for f in group]))
        late_span = (min(xs(late)), max(xs(late)))
        self.assertGreaterEqual(late_span[0], min(xs(lower)))
        self.assertLessEqual(late_span[1], max(xs(lower)))
        lower_old = prev['fragments'][:[f['id'] for f in prev['fragments']].index(ext_old['firstUpDeparture']) + 1]
        coverage = dict(lateRouteSpan=late_span, lowerRouteSpan=(min(xs(lower)), max(xs(lower))),
                        coveredByLowerPanels=cover(lower, late_span) / (late_span[1] - late_span[0]),
                        previousCoveredByLowerPanels=cover(lower_old, late_span) / (late_span[1] - late_span[0]),
                        lowerFragments=[f['semanticId'] for f in lower])
        # Original concept source untouched.
        now = {p: sha((ROOT / p).read_bytes()) for p in ORIGINAL_SOURCE}
        self.assertEqual(now, ORIGINAL_SOURCE)
        self.assertEqual(self.m['baselineSha256'], prev['baselineSha256'])
        # Corner and clearance rules (independent checker on the candidate files).
        s = self.report['summary']
        self.assertTrue(s['pass'])
        self.assertGreaterEqual(s['minInteriorAngle'], MIN_INTERIOR_ANGLE)
        self.assertGreaterEqual(s['minDragSolidClearance'], 1620)
        self.assertEqual(s['pairsPass'], s['fragmentPairs'])
        self.__class__.section_preservation = dict(
            comparedWith=dict(path=os.path.relpath(PREVIOUS, ROOT), measurementsSha=sha((PREVIOUS / NAMES[1]).read_bytes())),
            identicalFragments=kept, departureTwin=dict(candidate='X10', previous=dep_old),
            shortcutShields=dict(fragments=shielded, spec=self.m['shortcutShields'],
                                 rule='identical fragments compare the shield-free generation; shields reshape only these'),
            changedOrAdded=[s for s in order[7:cut]] + ['L1', 'L2'],
            addedSemanticIds=sorted(set(order) - set(old)), removedSemanticIds=[],
            routeSuccessorsAfterSection=tail_new,
            maxSuccessorGapChange=max(v for k, v in gaps.items() if k not in moved_gaps),
            shieldGapChanges={k: dict(previous=next(r['distance'] for r in prev['encounters'] if r['id'] == k),
                                      now=rows_new[k]['distance'], minimum=2 * GRAPPLE_RANGE) for k in moved_gaps if k == 'NG-ENTRY'},
            diagonalOpening=dict(raisedRightward=['X2', 'X5', 'X9'], raisedLeftward=['L1', 'L2'],
                                 changedLeftwardGaps={k: gaps[k] for k in moved_gaps if k != 'NG-ENTRY'}),
            purpleExtension=dict(zone=self.m['noGrappleZones'], panels=[sem(self.m, i) for i in [pe['approach'], pe['exit']] + pe['internal']],
                                 encounters=pe['encounters'], upperTranslation=pe['upperTranslation'], identicalToPrevious=True),
            lowerCatch=dict(coverage, upperTranslation=ext['upperTranslation'],
                            previousUpperTranslation=ext_old['upperTranslation'], patterns=ext['patterns']),
            originalSource=dict(expected=ORIGINAL_SOURCE, now=now, unchanged=True, baselineSha256=self.m['baselineSha256']),
            rules=dict(checkerPass=s['pass'], minInteriorAngle=s['minInteriorAngle'], minimumAngle=MIN_INTERIOR_ANGLE,
                       pairsPass=s['pairsPass'], fragmentPairs=s['fragmentPairs'], transfersPass=s['transfersPass'],
                       transfers=s['transfers'], minDragSolidClearance=s['minDragSolidClearance'],
                       minYellowPairClearance=s['minYellowPairClearance']))

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
             for f in t.m['fragments'][start:] if f['semanticId'] in t.before_ids]
    sp = t.section_preservation
    falls = out / 'late-falls.json'
    if falls.exists():  # written by CombinationReplayTests (test_16), whichever class runs first
        sp['lowerCatch']['lateFallLandings'] = json.loads(falls.read_text())
    candidate = dict(path=os.path.relpath(CANDIDATE.resolve(), ROOT), selectedBy=SELECTED_BY,
                     hashes={n: sha((CANDIDATE / n).read_bytes()) for n in NAMES},
                     generatorSha=sha((TOOLS / 'retune_extended_level.py').read_bytes()),
                     guidelinesSha=sha(GUIDELINES.read_bytes()))
    dump('opening-patterns.json', dict(
        method='Rightward section = transfers before the first upward transfer (retune.opening_sections on the '
               'measurement contacts). Each contact surface comes from the imported polygons (surface_at: nearest '
               'edge, probed 0.5 above/below); the pattern is classified from departure/arrival surface and the '
               'contact vector (world y down), then compared with the generator label. measuredGap is the generator\'s '
               'complete-polygon gap, checkerGap the independent check_level_geometry distance; usableSpan is the '
               'horizontal projection of the arrival contact edge.',
        candidate=candidate, **t.patterns))
    dump('preservation.json', dict(
        candidate=candidate,
        purpleExtension=sp['purpleExtension'],
        laterRoute=dict(comparedWith=sp['comparedWith'], identicalFragments=sp['identicalFragments'],
                        departureTwin=sp['departureTwin'],
                        changedOrAdded=sp['changedOrAdded'], addedSemanticIds=sp['addedSemanticIds'],
                        removedSemanticIds=sp['removedSemanticIds'], routeSuccessorsAfterSection=sp['routeSuccessorsAfterSection'],
                        maxSuccessorGapChange=sp['maxSuccessorGapChange']),
        lowerCatch=sp['lowerCatch'], originalSource=sp['originalSource'], rules=sp['rules'],
        openingSpan=dict(ratio=t.patterns['ratio'], rightwardContactSpan=t.patterns['rightwardContactSpan'],
                         baseline=t.patterns['baselineRightwardSpan'], minimumRatio=3,
                         minUsableSpan=min(r['usableSpan'] for r in t.patterns['transfers']), minimumUsableSpan=MIN_SPAN),
        v7Comparison=dict(
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
                         '1620/540 rules; ids are regenerated per run.'))))


# TASK-669 production replay. Fixture: a zero-speed drop 30 units above the
# middle of P2 (the end of the easy opening); gravity makes the entry state.
# Inputs are real document mouse events at fixed ticks; aims are derived from
# the shipped polygons. Nothing writes position, velocity or grapple state
# after the fixture (tools/opening_combination_replay.js).
FIXTURE = json.loads((TOOLS / 'fixtures/harder-opening-inputs.json').read_text())['fixture']
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
    record = json.loads((TOOLS / 'fixtures/harder-opening-inputs.json').read_text())
    inputs = record['inputs']
    end = next(i for i,e in enumerate(inputs) if e['type']=='up' and e['tick']>record['ceilingCatchTick'])
    return inputs[:end+1]



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
        cls.level = json.loads((CANDIDATE / NAMES[2]).read_text())
        cls.m = json.loads((CANDIDATE / NAMES[1]).read_text())
        cls.ids = cls.m['routeMap']['addedFragments']
        cls.sem = {f['id']: f['semanticId'] for f in cls.m['fragments']}
        cls.browser_version = cls.browser.version
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
            # Browser-measured lower-catch falls join the offline preservation proof.
            pres = out / 'preservation.json'
            if getattr(cls, 'late_falls', None) is not None and pres.exists():
                data = json.loads(pres.read_text())
                data['lowerCatch']['lateFallLandings'] = cls.late_falls
                pres.write_text(json.dumps(data, separators=(',', ':')) + '\n')

    def bounds(self, level):
        polys = fragment_polys(level or self.level)
        ids = self.ids
        out = {}
        for sem, fid in [('P2', 'P2')] + [(k, ids[k]) for k in ('R1', 'R2', 'R3', 'R4')] + [('P7', 'P7')]:
            # The panel body only: R1's second body is the TASK-677 shortcut fin below its underside.
            pts = list(polys[fid][0])
            out[sem] = dict(id=fid, x0=min(x for x, _ in pts), x1=max(x for x, _ in pts),
                            y0=min(y for _, y in pts), y1=max(y for _, y in pts))
        return out

    def replay(self, inputs, level=None, budget=None):
        level = level or self.level
        if budget is None: budget=json.loads((TOOLS / 'fixtures/harder-opening-inputs.json').read_text())['budget']
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
        self.assertTrue(all(e['type'] in ('down','up','move') for e in log['inputs']))
        self.assertEqual(log['fixture']['vx'], 0)
        self.assertEqual(log['fixture']['vy'], 0)
        self.assertLess(log['maxStep'], 200)
        # The first seven inputs are the P2 pumps and the in-range ceiling shot.
        early = [c['id'] for c in log['contacts'] if c['tick'] < next(c['tick'] for c in log['contacts'] if c['id']==ids['R1']+'-body0')]
        self.assertEqual(early, ['P2-body0'] * len(early))
        self.assertGreaterEqual(len(early), 1)
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
        # A new successful policy may use different pump counts. Contacts and
        # attachments must still follow the intended sequence without skipping.
        high = 2
        events = [(c['tick'], c['id']) for c in log['contacts']] + [
            (g['tick'], g['id']) for g in log['grapple'] if g['event']=='attach']
        for tick, pid in sorted(events):
            n = int(pid.split('-')[0][1:])
            self.assertLessEqual(n, high+1, (tick,pid))
            high = max(high,n)
        transitions = []
        for name, enc, c in (('ceiling catch', 'OPEN-P2-R1', catch), ('down-right slope landing', 'OPEN-R1-R2', slope),
                             ('right/up rebound arrival', 'OPEN-R2-R3', r3), ('horizontal arrival', 'OPEN-R3-R4', r4)):
            transitions.append(dict(transfer=name, encounter=enc, contact=c))
        self.__class__.evidence['combination-replay.json'] = dict(
            method='Real index.html with the shipped leveldata.js; tools/opening_combination_replay.js dispatches '
                   'document mousedown/mousemove/mouseup at the listed ticks and calls production physics() once per '
                   'tick. The fixture is the only placement; no position, velocity or grapple state is written later.',
            fixture=dict(log['fixture'], note='recorded zero-speed drop above P2 (end of the easier '
                                              'opening); the entry velocity is produced by gravity and a P2 bounce'),
            layoutId=log['layoutId'], inputs=log['inputs'], transitions=transitions,
            r3ToR4=dict(dx=dx, dy=dy, absDyOverDx=abs(dy) / dx), grapple=log['grapple'],
            contacts=log['contacts'], ticks=log['ticks'], maxStepPerTick=log['maxStep'],
            secondRunIdentical=runs[0] == runs[1], sequence=first_seq(after),
            semantic=dict(R1=ids['R1'], R2=ids['R2'], R3=ids['R3'], R4=ids['R4']))

    def test_11_route_regressions(self):
        ids = self.ids
        cases = [('S06-03', 'P0', 'P1', dict(fraction=.2, pumps=1,drop=300,lastAimOffset=.15)), ('S06-04', 'P1', 'P2', dict(fraction=.2, pumps=1,drop=300,lastAimOffset=.15)),
                 ('S07-01 upward turn', self.m['lowerCatchExtension']['firstUpDeparture'], self.m['routeMap']['fragmentIds']['P3'],
                  dict(fraction=.9, pumps=1,drop=300,lastAimOffset=.05,targetWhenInRange=True))]
        out = []
        for name, source, target, policy in cases:
            # The selected candidate, not the page's shipped leveldata.js.
            r = self.probe(level=self.level, source=source, target=target, budget=1800, **policy)
            self.assertIsNotNone(r['arrival'], name)
            self.assertIsNotNone(r['hit'], name)
            self.assertEqual(r['hit']['id'], target + '-body0', name)
            out.append(dict(case=name, intended=target, reached=r['hit']['id'], **r))
        # The replay's R4 arrival is the upward turn's departure surface.
        up = next(e for e in self.m['encounters'] if e['id'] == 'S07-01')
        self.assertEqual(up['fromFragment'], self.m['lowerCatchExtension']['firstUpDeparture'])
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
            level=level, fixture=FIXTURE, inputs=i1[:-1], budget=1000, stopOn=dict(id=b['R1']['id'], ny='down')))
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
        # The selected candidate (TASK-676), not the page's shipped leveldata.js.
        shipped, before, old = self.grid(self.level), self.grid(self.before_level), self.grid(self.before_v8)
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
        flights = self.free_flights(self.level)
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

    def section(self):
        return section_patterns(self.m, self.level)

    def run_section(self, snapshot_every=0):
        rec = json.loads(SECTION_INPUTS.read_text())
        _, departure = self.section()
        return self.pages['replay'].evaluate('o => OPENING_REPLAY.run(o)', dict(
            level=self.level, fixture=rec['fixture'], inputs=rec['inputs'], budget=rec['budget'],
            stopOn=dict(id=departure, ny='up'), maxDrift=20000, snapshotEvery=snapshot_every)), rec

    def test_15_complete_section_replay(self):
        rows, departure = self.section()
        (log, rec), (again, _) = self.run_section(), self.run_section()
        self.assertEqual(log, again)                                  # deterministic
        self.assertEqual(self.pages['replay'].errors, [])
        self.assertEqual(log['layoutId'], self.level['layoutId'])
        self.assertEqual(log['acquisitionRadius'], 540)
        # Initialization is a new run's spawn at rest; afterwards only document mouse events.
        self.assertTrue(log['fixture']['spawn'])
        self.assertEqual((log['fixture']['x'], log['fixture']['y']), (self.level['spawn']['x'], self.level['spawn']['y']))
        self.assertEqual((log['fixture']['vx'], log['fixture']['vy']), (0, 0))
        self.assertTrue(all(e['type'] in ('down', 'up', 'move') for e in log['inputs']))
        self.assertEqual(log['recoveries'], [])
        self.assertLess(log['maxStep'], 200)
        order = [rows[0]['fromFragment']] + [r['toFragment'] for r in rows]
        contacts = [c for c in log['contacts'] if c['id'].startswith('P')]
        seq = first_seq(contacts)
        self.assertEqual(seq, order)
        # Every contact and attachment is on the current panel or its successor (no skip).
        events = sorted([(c['tick'], c['id'].split('-')[0]) for c in contacts] +
                        [(g['tick'], g['id'].split('-')[0]) for g in log['grapple'] if g['event'] == 'attach'])
        pos = 0
        for tick, pid in events:
            k = order.index(pid)
            self.assertIn(k, (pos, pos + 1), (tick, pid))
            pos = max(pos, k)
        self.assertEqual(log['stopped']['id'], departure + '-body0')
        transitions = []
        for k, r in enumerate(rows):
            dep_id, arr_id = order[k] + '-body0', order[k + 1] + '-body0'
            arrival = next(c for c in contacts if c['id'] == arr_id)
            before = [c for c in contacts if c['tick'] <= arrival['tick'] and c['id'] == dep_id]
            self.assertTrue(before, r['semantic'])
            last, p = before[-1], r['pattern']
            if p == 'ceiling-catch':
                self.assertGreater(arrival['ny'], .99, r)
                self.assertLess(arrival['vyIn'], 0, r)
            elif p == 'descending-slope':
                self.assertTrue(0 < arrival['nx'] < .2 and arrival['ny'] < -.98, (r['semantic'], arrival))
                self.assertGreater(arrival['vyIn'], 0, r)
                self.assertGreater(arrival['y'], last['y'], r)
            elif p == 'upward-rebound':
                self.assertTrue(0 < last['nx'] < .2 and last['ny'] < -.98, (r['semantic'], last))
                self.assertLess(last['vyOut'], 0, r)
                self.assertEqual((arrival['nx'], arrival['ny']), (0, -1), r)
                self.assertLess(arrival['y'], last['y'], r)
            else:
                # The last departure contact may be the top or a panel end (recorded as departureContact).
                self.assertEqual((arrival['nx'], arrival['ny']), (0, -1), r)
                self.assertLess(last['ny'], 1, r)
                self.assertGreater(arrival['x'], last['x'], r)
                if p == 'exposed-traverse':
                    self.assertLessEqual(abs(arrival['y'] - last['y']), .25 * (arrival['x'] - last['x']), r)
            transitions.append(dict(encounter=r['encounter'], semantic=r['semantic'], pattern=p,
                                    departureContact=last, arrivalContact=arrival))
        self.__class__.evidence['opening-replay.json'] = dict(
            method='Real index.html; the candidate goes through production importedMountainLevel() (540 acquisition). '
                   'tools/opening_combination_replay.js places the player once exactly as a new run (level spawn, zero '
                   'speed), then dispatches document mousedown/mousemove/mouseup at the recorded ticks '
                   '(tools/fixtures/opening-section-inputs.json, aims in world units) and calls production physics() '
                   'once per tick. Nothing writes position, velocity or grapple state afterwards; recoverClimbFall '
                   'calls are logged (recoveries) and must be empty. departureContact is the last contact on the '
                   'departure panel at or before the arrival.',
            browser=self.browser_version,
            candidate=dict(path=os.path.relpath(CANDIDATE.resolve(), ROOT), selectedBy=SELECTED_BY,
                           levelSha=sha((CANDIDATE / NAMES[2]).read_bytes())),
            inputsSha=sha(SECTION_INPUTS.read_bytes()), layoutId=log['layoutId'],
            acquisitionRadius=log['acquisitionRadius'], fixture=log['fixture'], stateInjectionsAfterInit=0,
            recoveries=log['recoveries'], maxStepPerTick=log['maxStep'], ticks=log['ticks'],
            secondRunIdentical=log == again, intendedOrder=[self.sem[o] for o in order],
            contactSequence=[self.sem[p.split('-')[0]] for p in seq],
            departure=dict(id=departure, semantic=self.sem[departure]), stopped=log['stopped'],
            transitions=transitions, inputs=log['inputs'], grapple=log['grapple'], contactCount=len(log['contacts']))

    def test_16_late_falls_on_lower_terrain(self):
        fs = self.m['fragments']
        ids = [f['id'] for f in fs]
        lower = set(ids[:ids.index(self.m['lowerCatchExtension']['firstUpDeparture']) + 1])
        late = fs[ids.index(self.m['purpleExtension']['exit']) + 1:]
        # The three leftmost late panels by contact point (semantic geometry, not frozen indices).
        sources = sorted(late, key=lambda f: retune.svg.contact(f)[0])[:3]
        out = []
        for f in sources:
            r = self.pages['replay'].evaluate(FALL, [self.level, f['id']])
            self.assertIn('hit', r, r)
            self.assertIn(r['hit']['id'].split('-')[0], lower, r)
            self.assertLess(r['maxStep'], 200)
            out.append(dict(r, semantic=f['semanticId'], landedSemantic=self.sem[r['hit']['id'].split('-')[0]]))
        self.__class__.evidence['late-falls.json'] = self.__class__.late_falls = dict(
            method='Gravity-only fall from just below each of the three leftmost late panels (no input), production '
                   'physics; the first contact must be lower terrain (fragments up to the upward-turn departure).',
            falls=out)

    def test_17_opening_png(self):
        from PIL import Image, ImageDraw
        from browser_test_support import wait_for_boot_run
        import re
        rows, _ = self.section()
        order = [rows[0]['fromFragment']] + [r['toFragment'] for r in rows]
        frag = {f['id']: f for f in self.m['fragments']}
        log, _ = self.run_section(snapshot_every=4)
        path = [(p['x'], p['y']) for p in log['snapshots']]
        art_svg = (CANDIDATE / NAMES[0]).read_text()
        # Front labels are sized for the full-map canvas; at this zoom they would cover the geometry.
        art_svg = art_svg.replace('<g id="annotations-front"', '<g id="annotations-front" display="none"', 1)
        cw, ch = 1280, 360
        groups = [order[:8], order[7:12], order[11:]]
        shot = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        shot.errors = []
        shot.on('pageerror', lambda e: shot.errors.append(str(e)))
        shot.goto(self.url)
        wait_for_boot_run(shot)
        tiles, boxes = [], []
        for g in groups:
            pts = [p for fid in g for b in retune.svg.bodies(frag[fid]) for p in b]
            x0, y0 = min(p[0] for p in pts) - 300, min(p[1] for p in pts) - 900
            x1, y1 = max(p[0] for p in pts) + 300, max(p[1] for p in pts) + 300
            k = min(cw / (x1 - x0), ch / (y1 - y0))
            wx, wy = (x0 + x1) / 2 - cw / k / 2, (y0 + y1) / 2 - ch / k / 2
            info = shot.evaluate(FRAME, [self.level, wx, wy, k, list(retune.svg.contact(frag[g[0]]))])
            runtime = image(info['png'])
            runtime = runtime.crop((0, 0, runtime.width, runtime.width * ch // cw)).resize((cw, ch))
            head, rest = art_svg.split('>', 1)
            head = re.sub(r' viewBox="[^"]*"', ' viewBox="%r %r %r %r"' % (wx, wy, cw / k, ch / k), head)
            head = re.sub(r' width="[^"]*"', ' width="%d"' % cw, head, count=1)
            head = re.sub(r' height="[^"]*"', ' height="%d"' % ch, head, count=1)
            page = self.browser.new_page(viewport={'width': cw, 'height': ch})
            page.set_content('<html><body style="margin:0;background:#09141e">' + head + '>' + rest + '</body></html>')
            art = Image.open(io.BytesIO(page.screenshot(clip=dict(x=0, y=0, width=cw, height=ch)))).convert('RGB')
            page.close()
            d = ImageDraw.Draw(runtime)
            to_px = lambda p: ((p[0] - wx) * k, (p[1] - wy) * k)
            d.line([to_px(p) for p in path], fill=(0, 255, 255), width=1)
            for fid in g:
                c = to_px(retune.svg.contact(frag[fid]))
                d.text((c[0] - 8, c[1] + 8), self.sem[fid], fill=(255, 255, 255))
            tiles.append((art, runtime))
            boxes.append([wx, wy, wx + cw / k, wy + ch / k])
        self.assertEqual(shot.errors, [])
        shot.close()
        sheet = Image.new('RGB', (cw + 16, len(tiles) * (2 * ch + 40) + 40), (12, 12, 16))
        d = ImageDraw.Draw(sheet)
        d.text((8, 8), 'TASK-676 starting rightward section (%s): candidate SVG (upper) vs runtime draw() with the '
                       'from-spawn replay path in cyan (lower), same world box per pair' % SELECTED_BY, fill=(235, 235, 235))
        y = 32
        for (art, runtime), box, g in zip(tiles, boxes, groups):
            d.text((8, y), '%s .. %s  world box [%.0f, %.0f, %.0f, %.0f]' % ((self.sem[g[0]], self.sem[g[-1]]) + tuple(box)),
                   fill=(200, 200, 200))
            sheet.paste(art, (8, y + 14))
            sheet.paste(runtime, (8, y + 18 + ch))
            y += 2 * ch + 40
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            sheet.save(Path(EVIDENCE) / 'opening.png')
        self.assertGreater(len(path), 100)
        self.__class__.evidence['opening-png.json'] = dict(
            image='opening.png', worldBoxes=boxes, groups=[[self.sem[f] for f in g] for g in groups],
            replayPathPoints=len(path), svgLayersHidden=['annotations-front (labels sized for the full-map view)'])


FALL = '''([level, id]) => {
    const el = level.elements.find(e => e.id === id + '-body0')
    const top = Math.min(...el.points.map(p => p.y)) + el.y, bottom = Math.max(...el.points.map(p => p.y)) + el.y
    // Gravity-only fall from just below the source panel; no input or later writes.
    const c = OPENING_REPLAY.start({level, fixture: {panel: id, fraction: .5, drop: top - bottom - 100}})
    for (let i = 0; i < 6000; i++) {
        const fresh = c.step()
        const hit = fresh.find(k => k.id.split('-')[0] !== id)
        if (hit) return {source: id, hit, ticks: c.tick, maxStep: c.log.maxStep, start: c.log.fixture}
        if (c.log.maxStep > 200) return {source: id, recovered: true, ticks: c.tick}
    }
    return {source: id, timeout: true}
}'''

# A production draw() of the candidate at a fixed world box (the clock frozen).
FRAME = '''([level, wx, wy, k, at]) => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    floors = [loadFixedLevel(importedMountainLevel(structuredClone(level)))]
    ninja.x = at[0]; ninja.y = at[1]; ninja.speedX = ninja.speedY = 0
    menu.unPause()
    const now = performance.now(); performance.now = () => now
    TUTORIAL_HINT.visible = false
    scale[version] = k * width / canvas.width
    screen.x = -wx
    screen.y = -wy
    ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
    draw()
    return {png: canvas.toDataURL('image/png')}
}'''


def image(data_url):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(',', 1)[1]))).convert('RGB')
