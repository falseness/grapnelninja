"""Threefold opening candidate: counts, semantic mapping, spans and geometry.

    python3 -m unittest discover -s tools -p test_extended_opening.py -v

Generates the extended candidate twice and the pre-change (original opening)
layout once through tools/retune_extended_level.py, imports each SVG and
measures spans from imported polygons only. Set OPENING_EVIDENCE_DIR to keep
the candidate and write opening-baseline.json, section-lengths.json,
route-map.json and candidate-checks.json there.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from check_level_geometry import MIN_INTERIOR_ANGLE, check, interior_angles, union_distance  # noqa: E402
from import_level_svg import import_svg  # noqa: E402
import retune_extended_level as retune  # noqa: E402

SOURCE = ROOT / 'artifacts/level/extended-mountain-measurements.json'
GUIDELINES = ROOT / 'artifacts/levels/level-guidelines.md'
FROZEN = ROOT / 'artifacts/TASK-655/baseline/extended-mountain-measurements.json'
EVIDENCE = os.environ.get('OPENING_EVIDENCE_DIR')
GRAPPLE, DIAMETER = 540.0, 21.6
SPAN_TOLERANCE = 0.01


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(dest, opening):
    return subprocess.Popen([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source', str(SOURCE),
                             '--output-dir', str(dest), '--guidelines', str(GUIDELINES), '--opening', opening],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def fragment_polys(level):
    """World polygons per fragment id from imported elements only."""
    elements = {e['id']: e for e in level['elements']}
    return {f['id']: [[(elements[eid]['x'] + p['x'], elements[eid]['y'] + p['y']) for p in elements[eid]['points']]
                      for eid in f['elements']] for f in level['svgFormat']['fragments']}


def contact(polys):
    """Top-centre landing point of a fragment: bounding-box centre x, highest y."""
    xs = [x for poly in polys for x, _ in poly]
    return ((min(xs) + max(xs)) / 2, min(y for poly in polys for _, y in poly))


def route_contacts(level):
    polys = fragment_polys(level)
    transfers = level['svgFormat']['transfers']
    order = [transfers[0]['from']] + [t['to'] for t in transfers]
    return order, [contact(polys[f]) for f in order]


def sections(points):
    """Independent run split: rightward run, one upward transfer, leftward run."""
    def kind(i):
        dx, dy = points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]
        return 'up' if dy < 0 and abs(dy) > abs(dx) else 'right' if dx > 0 else 'left'
    i = 0
    while i + 1 < len(points) and kind(i) == 'right':
        i += 1
    up = i + 1
    j = up
    while j + 1 < len(points) and kind(j) == 'left':
        j += 1
    return dict(rightward=[0, i], upward=[i, up], leftward=[up, j], kinds=[kind(k) for k in range(j + 1)])


def opening_report(level, baseline_level):
    """Spans, ratios and directions from imported contact coordinates."""
    rows = {}
    for name, lvl in (('baseline', baseline_level), ('candidate', level)):
        order, pts = route_contacts(lvl)
        sec = sections(pts)
        r0, r1 = sec['rightward']
        l0, l1 = sec['leftward']
        rows[name] = dict(
            sections={k: dict(fragments=[order[a], order[b]], departure=list(pts[a]), arrival=list(pts[b]))
                      for k, (a, b) in ((k, sec[k]) for k in ('rightward', 'upward', 'leftward'))},
            rightwardSpan=pts[r1][0] - pts[r0][0], leftwardSpan=pts[l0][0] - pts[l1][0],
            rightwardContactsX=[pts[k][0] for k in range(r0, r1 + 1)],
            leftwardContactsX=[pts[k][0] for k in range(l0, l1 + 1)],
            upward=dict(dx=pts[sec['upward'][1]][0] - pts[sec['upward'][0]][0],
                        dy=pts[sec['upward'][1]][1] - pts[sec['upward'][0]][1]),
            rightwardTransfers=r1 - r0, leftwardTransfers=l1 - l0)
    b, c = rows['baseline'], rows['candidate']
    c['rightwardRatio'] = c['rightwardSpan'] / b['rightwardSpan']
    c['leftwardRatio'] = c['leftwardSpan'] / b['leftwardSpan']
    return rows


def opening_violations(report):
    c = report['candidate']
    out = []
    if c['rightwardRatio'] < 3 - 1e-6:
        out.append('rightward span below 3x minimum')
    xs = c['rightwardContactsX']
    if any(b <= a for a, b in zip(xs, xs[1:])):
        out.append('rightward contacts not strictly increasing in x')
    xs = c['leftwardContactsX']
    if any(b >= a for a, b in zip(xs, xs[1:])):
        out.append('leftward contacts not strictly decreasing in x')
    if not (c['upward']['dy'] < 0 and abs(c['upward']['dy']) > abs(c['upward']['dx'])):
        out.append('no upward section between rightward and leftward')
    # R1-R4 plus X1-X10 (TASK-676) rightward; L1/L2 plus the purple approach, entry and four
    # internal bounces (TASK-675) leftward.
    if c['rightwardTransfers'] != report['baseline']['rightwardTransfers'] + 14:
        out.append('rightward section has %d transfers' % c['rightwardTransfers'])
    if c['leftwardTransfers'] != report['baseline']['leftwardTransfers'] + 8:
        out.append('leftward section has %d transfers' % c['leftwardTransfers'])
    return out


def move_fragment(level, fid, dx, dy=0.0):
    level = copy.deepcopy(level)
    ids = next(f['elements'] for f in level['svgFormat']['fragments'] if f['id'] == fid)
    for e in level['elements']:
        if e['id'] in ids:
            e['x'] += dx
            e['y'] += dy
    return level


class ExtendedOpeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        first = Path(EVIDENCE) / 'candidate' if EVIDENCE else tmp / 'run1'
        runs = [(first, 'extended'), (tmp / 'run2', 'extended'), (tmp / 'original', 'original')]
        procs = [generate(d, o) for d, o in runs]
        cls.logs = [p.communicate()[0] for p in procs]
        for p, log in zip(procs, cls.logs):
            assert p.returncode == 0, log
        cls.dirs = [d for d, _ in runs]
        cls.svg = [(d / 'extended-mountain.svg').read_bytes() for d in cls.dirs]
        cls.meas = [json.loads((d / 'extended-mountain-measurements.json').read_text()) for d in cls.dirs]
        cls.levels = [import_svg(s) for s in cls.svg]
        cls.m, cls.level, cls.base, cls.base_level = cls.meas[0], cls.levels[0], cls.meas[2], cls.levels[2]
        cls.source = json.loads(SOURCE.read_text())
        cls.report = check(cls.level, cls.svg[0], cls.m)
        cls.opening = opening_report(cls.level, cls.base_level)
        if EVIDENCE:
            (first / 'extended-mountain.level.json').write_text(json.dumps(cls.levels[0], separators=(',', ':')) + '\n')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def frag(self, m, fid):
        return next(f for f in m['fragments'] if f['id'] == fid)

    def test_generation_and_import_are_deterministic(self):
        self.assertEqual(self.svg[0], self.svg[1])
        a, b = (json.dumps(m, separators=(',', ':')) for m in self.meas[:2])
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(self.levels[0]), json.dumps(import_svg(self.svg[1])))
        self.assertEqual(self.m['layoutId'], retune.EXTENDED_LAYOUT)

    def test_original_opening_reproduces_frozen_baseline(self):
        if not FROZEN.exists():
            self.skipTest('ticket-local baseline not present')
        frozen = json.loads(FROZEN.read_text())
        for key in ('fragments', 'encounters', 'yellowBands', 'combinations', 'allowedGrapplePairs', 'layoutId'):
            self.assertEqual(self.base[key], frozen[key], key)

    def test_counts_and_ordered_connected_route(self):
        frags = self.level['svgFormat']['fragments']
        transfers = self.level['svgFormat']['transfers']
        self.assertEqual(len(frags), 48)
        self.assertEqual(len({f['id'] for f in frags}), 48)
        self.assertEqual(len(transfers), 47)
        self.assertEqual([t['id'] for t in transfers], ['T%02d' % n for n in range(1, 48)])
        for a, b in zip(transfers, transfers[1:]):
            self.assertEqual(a['to'], b['from'])
        order = [transfers[0]['from']] + [t['to'] for t in transfers]
        self.assertEqual(len(set(order)), 48)
        self.assertEqual(len(self.report['pairs']), 48 * 47 // 2)
        # 48 panels, one body each, plus R1's second body (the TASK-677 shortcut fin).
        bodies = [e for e in self.level['elements'] if e['role'] not in ('drag', 'no-grapple')]
        self.assertEqual(len(bodies), 49)

    def test_threefold_spans_directions_and_counts(self):
        self.assertEqual(opening_violations(self.opening), [])
        c = self.opening['candidate']
        self.assertGreaterEqual(c['rightwardRatio'], 3 - 1e-6)
        self.assertGreater(c['leftwardSpan'], 0)
        self.assertEqual((c['rightwardTransfers'], c['leftwardTransfers']), (16, 9))

    def test_mutations_are_rejected(self):
        right = self.opening['candidate']['sections']['rightward']['fragments'][1]
        left = self.opening['candidate']['sections']['leftward']['fragments'][1]
        span = self.opening['candidate']['rightwardSpan']
        shorter = opening_report(move_fragment(self.level, right,
            2.9 * self.opening['baseline']['rightwardSpan'] - span), self.base_level)
        self.assertNotEqual(opening_violations(shorter), [])
        # Reversing one added rightward panel behind its predecessor breaks the run.
        order, pts = route_contacts(self.level)
        reversed_level = move_fragment(self.level, order[4], pts[2][0] - pts[4][0] - 300)
        self.assertNotEqual(opening_violations(opening_report(reversed_level, self.base_level)), [])
        # An oversized bounding box must not excuse an undersized landing face.
        spec = copy.deepcopy(retune.OPENING)
        spec['right'][0]['width'] = 719
        with self.assertRaisesRegex(ValueError, '720'):
            retune.extend_opening(self.base['fragments'], self.base['encounters'], spec)

    def test_opening_has_full_size_landing_surfaces(self):
        # Inspect the imported edge each transfer contact rests on (top, ceiling
        # underside or slope), independently of declared width metadata.
        from test_opening_jump_variety import surface_at
        polys = fragment_polys(self.level)
        order, pts = route_contacts(self.level)
        end = sections(pts)['rightward'][1]
        spans = {}
        for r in self.m['encounters'][:end + 1]:
            for fid, point in ((r['fromFragment'], r['flight'][0]), (r['toFragment'], r['flight'][1])):
                if fid in order[:end + 1]:
                    spans[fid] = max(spans.get(fid, 0), surface_at(polys[fid], point)['span'])
        self.assertEqual(sorted(spans), sorted(order[:end + 1]))
        for fid in spans:
            self.assertGreaterEqual(spans[fid], 720, fid)
        if EVIDENCE:
            (Path(EVIDENCE) / 'usable-surfaces.json').write_text(json.dumps(spans))

    def test_semantic_mapping_is_complete(self):
        route = self.m['routeMap']
        originals = [f['id'] for f in self.source['fragments']]
        self.assertEqual(sorted(route['fragmentIds']), sorted(originals))
        self.assertEqual(len(set(route['fragmentIds'].values())), 25)
        purple = ['NG-APPROACH', 'NG-EXIT'] + ['NG%d' % i for i in range(1, 6)]
        self.assertEqual(sorted(route['addedFragments']),
                         sorted(['L1', 'L2', 'R1', 'R2', 'R3', 'R4'] + ['X%d' % i for i in range(1, 11)] + purple))
        for f in self.m['fragments']:
            if f['originalId']:
                self.assertEqual(route['fragmentIds'][f['originalId']], f['id'])
                old = self.frag(self.base, f['originalId'])
                self.assertEqual(f['kind'], old['kind'])
                if f['id'] in ('P0','P1','P2'):
                    self.assertEqual(f['polys'], old['polys'])
        enc_ids = [r['id'] for r in self.m['encounters']]
        self.assertEqual(len(set(enc_ids)), 47)
        source_ids = [r['id'] for r in self.source['encounters']]
        self.assertTrue(set(source_ids) <= set(enc_ids))
        self.assertEqual(len(route['addedEncounters']), 23)
        for old in self.source['encounters']:
            n = route['encounterNumbers'][str(old['number'])]
            self.assertEqual(self.m['encounters'][n - 1]['id'], old['id'])
            self.assertEqual(self.level['svgFormat']['transfers'][n - 1]['encounter'], old['id'])

    def test_opening_transfers_and_targets_are_kept(self):
        for fid in ('P0', 'P1', 'P2'):
            new, old = self.frag(self.m, fid), self.frag(self.base, fid)
            self.assertEqual(new['polys'], old['polys'])
        t = self.report['transfers']
        self.assertEqual([(r['encounter'], r['from'], r['to']) for r in t[:2]],
                         [('S06-03', 'P0', 'P1'), ('S06-04', 'P1', 'P2')])
        for row, pct in zip(t[:2], (120,160)):
            self.assertAlmostEqual(row['computedPercent'], pct, places=5)
        up = self.opening['candidate']['sections']['upward']['fragments']
        row = next(r for r in t if (r['from'], r['to']) == tuple(up))
        self.assertEqual(row['encounter'], 'S07-01')
        self.assertAlmostEqual(row['computedPercent'], 150, places=5)
        # Every original numeric gap target resolves to the same semantic encounter.
        by_id = {r['encounter']: r for r in t}
        for old_n, pct in retune.OPENING_TARGETS.items():
            eid = self.m['routeMap']['encounterIds'][str(old_n)]
            self.assertEqual(eid, self.source['encounters'][old_n - 1]['id'])
            self.assertAlmostEqual(by_id[eid]['computedPercent'], pct, places=5)
        for old in self.base['encounters']:
            if old['number'] not in retune.TARGETS:
                self.assertGreaterEqual(by_id[old['id']]['computedPercent'],200-.01,old['id'])

    def test_old_numeric_references_resolve_semantically(self):
        nums = self.m['routeMap']['encounterNumbers']
        for old, new in zip(self.source['combinations'], self.m['combinations']):
            self.assertEqual([self.source['encounters'][n - 1]['id'] for n in old],
                             [self.m['encounters'][n - 1]['id'] for n in new])
            self.assertEqual(new, [nums[str(n)] for n in old])
        for band in self.m['yellowBands']:
            if band.get('belowEncounter'):
                self.assertEqual(self.m['encounters'][band['belowJump'] - 1]['id'], band['belowEncounter'])
        allowed = {frozenset(p) for p in self.m['allowedGrapplePairs']}
        self.assertEqual(allowed, set())
        # Old number 4 (P3->P4) no longer names the same encounter; the map does.
        self.assertNotEqual(self.m['encounters'][3]['id'], self.source['encounters'][3]['id'])

    def test_candidate_geometry_rules(self):
        s = self.report['summary']
        self.assertTrue(s['pass'], self.report['failureMessages'])
        self.assertEqual(s['fragmentPairs'], s['expectedFragmentPairs'])
        self.assertGreaterEqual(s['minInteriorAngle'], MIN_INTERIOR_ANGLE)
        self.assertEqual(s['solidBounceGrapplable'], s['solidElements'])
        self.assertGreaterEqual(s['minDragSolidClearance'], 1620)
        self.assertGreaterEqual(s['minYellowPairClearance'], 540)
        for p in self.report['pairs']:
            # Purple internal transfers use the scoped noGrappleInternal rule (TASK-672/675).
            if p.get('rule') == 'noGrappleInternal':
                self.assertTrue(p['pass'] and 0 < p['clearance'] <= 270, p)
            elif frozenset((p['a'], p['b'])) not in {frozenset(x) for x in self.m['allowedGrapplePairs']}:
                self.assertGreater(p['clearanceMinusDiameter'], GRAPPLE, p)
        for d in self.report['dragZones']:
            self.assertTrue(d['axisAligned'] and d['rect'][2] > d['rect'][3], d)
        internal = {r['id'] for r in self.m['encounters'] if r.get('noGrappleZone')}
        added = set(self.m['routeMap']['addedEncounters']) - internal
        for t in self.report['transfers']:
            if t['encounter'] in added:
                self.assertGreater(t['computedDistance'] - DIAMETER, GRAPPLE, t)

    def test_zz_write_evidence(self):
        if not EVIDENCE:
            self.skipTest('OPENING_EVIDENCE_DIR not set')
        write_evidence(self, Path(EVIDENCE))


def write_evidence(t, out):
    dump = lambda name, data: (out / name).write_text(
        json.dumps(data, separators=(',', ':')).replace('"pass_":', '"pass":') + '\n')
    b = t.opening['baseline']
    frozen_level = ROOT / 'artifacts/TASK-655/baseline/extended-mountain.level.json'
    frozen_report = opening_report(json.loads(frozen_level.read_text()), json.loads(frozen_level.read_text()))
    dump('opening-baseline.json', dict(
        source='artifacts/levels/extended-mountain-measurements.json as of TASK-654 (frozen copy in baseline/)',
        method='contact = top-centre of imported fragment polygons; span = |x(arrival) - x(departure)|',
        sections=b['sections'], rightwardSpan=b['rightwardSpan'], leftwardSpan=b['leftwardSpan'],
        rightwardContactsX=b['rightwardContactsX'], leftwardContactsX=b['leftwardContactsX'], upward=b['upward'],
        frozenLevelSpans=dict(rightward=frozen_report['baseline']['rightwardSpan'],
                              leftward=frozen_report['baseline']['leftwardSpan']),
        regeneratedEqualsFrozen=dict(rightward=frozen_report['baseline']['rightwardSpan'] == b['rightwardSpan'],
                                     leftward=frozen_report['baseline']['leftwardSpan'] == b['leftwardSpan']),
        semanticIds=dict(rightward=['S06-03', 'S06-04'], upward=['S07-01'], leftward=['S07-02']),
        inputSha256={str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / 'artifacts/TASK-655/baseline').glob('*'))
                     if p.is_file()} | {'artifacts/level/extended-mountain-measurements.json': sha(SOURCE)}))
    c = t.opening['candidate']
    dump('section-lengths.json', dict(
        method='Recomputed from imported candidate level JSON polygons, not generator measurements',
        candidate=c, baseline=dict(rightwardSpan=b['rightwardSpan'], leftwardSpan=b['leftwardSpan']),
        targets=dict(rightward=3 * b['rightwardSpan'], leftward=3 * b['leftwardSpan']),
        rightwardRatio=c['rightwardRatio'], leftwardRatio=c['leftwardRatio'],
        spanRequirementsMet=dict(rightward=c['rightwardRatio'] >= 3 - 1e-6, leftward=c['leftwardSpan'] > 0),
        monotonic=dict(rightward=all(b2 > a for a, b2 in zip(c['rightwardContactsX'], c['rightwardContactsX'][1:])),
                       leftward=all(b2 < a for a, b2 in zip(c['leftwardContactsX'], c['leftwardContactsX'][1:]))),
        upwardBetween=c['upward']['dy'] < 0 and abs(c['upward']['dy']) > abs(c['upward']['dx']),
        violations=opening_violations(t.opening)))
    by_enc = {r['encounter']: r for r in t.report['transfers']}
    route = t.m['routeMap']
    transfers = [dict(number=n, transfer=tr['id'], encounter=tr['encounter'], **{'from': tr['from'], 'to': tr['to']},
                      fromSemantic=t.frag(t.m, tr['from'])['semanticId'], toSemantic=t.frag(t.m, tr['to'])['semanticId'],
                      originalNumber=t.m['encounters'][n - 1].get('originalNumber'),
                      declaredPercent=tr['gapPercent'], computedPercent=by_enc[tr['encounter']]['computedPercent'],
                      computedDistance=by_enc[tr['encounter']]['computedDistance'])
                 for n, tr in enumerate(t.level['svgFormat']['transfers'], 1)]
    order = [transfers[0]['from']] + [x['to'] for x in transfers]
    numeric = dict(
        gapTargets={str(k): dict(originalEncounter=route['encounterIds'][str(k)], newNumber=route['encounterNumbers'][str(k)],
                                 newEncounter=t.m['encounters'][route['encounterNumbers'][str(k)] - 1]['id'], percent=v)
                    for k, v in retune.TARGETS.items()},
        combinations=[dict(original=o, new=n, encounters=[t.m['encounters'][k - 1]['id'] for k in n])
                      for o, n in zip(t.source['combinations'], t.m['combinations'])],
        yellowBands=[dict(id=z['id'], belowJump=z['belowJump'], belowEncounter=z.get('belowEncounter'))
                     for z in t.m['yellowBands']],
        allowedGrapplePairs=t.m['allowedGrapplePairs'])
    numeric['allResolveToSameEncounter'] = (
        all(v['originalEncounter'] == v['newEncounter'] for v in numeric['gapTargets'].values())
        and all([t.source['encounters'][k - 1]['id'] for k in c_['original']] == c_['encounters'] for c_ in numeric['combinations']))
    dump('route-map.json', dict(
        layoutId=t.m['layoutId'], panels=len(order), distinctPanels=len(set(order)), transfers=len(transfers),
        connected=all(a['to'] == b2['from'] for a, b2 in zip(transfers, transfers[1:])),
        fragmentIds=route['fragmentIds'], addedFragments=route['addedFragments'],
        addedRightward=[route['addedFragments'][k] for k in ('R1', 'R2', 'R3', 'R4')],
        addedLeftward=[route['addedFragments'][k] for k in ('L1', 'L2')],
        encounterNumbers=route['encounterNumbers'], encounterIds=route['encounterIds'],
        addedEncounters=route['addedEncounters'], transferOrder=transfers,
        firstTwoUnchanged=dict(fragments={fid: [t.frag(t.m, fid)['x'], t.frag(t.m, fid)['y']] == [t.frag(t.base, fid)['x'], t.frag(t.base, fid)['y']]
                                          and t.frag(t.m, fid)['polys'] == t.frag(t.base, fid)['polys'] for fid in ('P0', 'P1', 'P2')},
                               percents=[transfers[0]['computedPercent'], transfers[1]['computedPercent']]),
        firstUpward=next(x for x in transfers if x['encounter'] == 'S07-01'),
        numericReferences=numeric))
    s = t.report['summary']
    allowed = {frozenset(x) for x in t.m['allowedGrapplePairs']}
    non_opening = [p for p in t.report['pairs'] if frozenset((p['a'], p['b'])) not in allowed]
    added = set(route['addedEncounters'])
    dump('candidate-checks.json', dict(
        checker='tools/check_level_geometry.py check() on imported candidate', checkerPass=s['pass'],
        failureMessages=t.report['failureMessages'], summary=s,
        angles=dict(minimum=s['minInteriorAngle'], required=MIN_INTERIOR_ANGLE, polygons=s['anglePolygons'],
                    pass_=s['anglePolygonsPass'] == s['anglePolygons']),
        panelRoles=dict(solid=s['solidElements'], greenBounceGrapplable=s['solidBounceGrapplable'],
                        pass_=s['solidElements'] == s['solidBounceGrapplable'] == 31),
        polygonsValid=dict(polygons=len(t.report['angles']),
                           pass_=all(not a['selfIntersections'] and not a['error'] and a['area'] for a in t.report['angles'])),
        retainedTargets=[dict(encounter=e, percent=retune.TARGETS.get(int(n), next(r['percent'] for r in t.base['encounters'] if r['id'] == e)),
                              computedPercent=by_enc[e]['computedPercent'])
                         for n, e in route['encounterIds'].items()],
        retainedTargetsPass=all(abs(by_enc[e]['computedPercent'] - next(r['percent'] for r in t.base['encounters'] if r['id'] == e)) <= .01
                                for e in route['encounterIds'].values()),
        newGaps=[dict(encounter=x['encounter'], computedPercent=x['computedPercent'], computedDistance=x['computedDistance'],
                      releaseRequired=x['computedDistance'] - DIAMETER > GRAPPLE) for x in transfers if x['encounter'] in added],
        newGapsNote='Measured from imported geometry; not a multiple of any original gap.',
        nonOpeningPairs=dict(count=len(non_opening), allowedExceptions=t.m['allowedGrapplePairs'],
                             minClearanceMinusDiameter=min(p['clearanceMinusDiameter'] for p in non_opening),
                             pass_=all(p['clearanceMinusDiameter'] > GRAPPLE for p in non_opening)),
        yellowToGreen=dict(minimum=s['minDragSolidClearance'], required=1080, pass_=s['minDragSolidClearance'] >= 1080),
        yellowToYellow=dict(minimum=s['minYellowPairClearance'], required=540, pairs=s['yellowPairs'],
                            pass_=s['yellowPairs'] == s['yellowPairsPass']),
        yellowHorizontalRectangles=[dict(id=d['id'], rect=d['rect'], pass_=d['axisAligned'] and d['rect'][2] > d['rect'][3])
                                    for d in t.report['dragZones']]))


if __name__ == '__main__':
    unittest.main()
