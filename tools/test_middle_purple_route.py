"""Second (middle) purple no-grapple encounter NGM (TASK-682, candidate only).

retune_extended_level.py --min-side-scope all --middle-purple inserts a second
purple encounter after S08-01, with the normal grapple transfers S07-03, S07-04
and S08-01 between it and the original NG1 chute. NGM is NG1 mirrored: the
approach is right of P7, the zone is right of the approach and holds NG1's slabs
and post reflected about the zone centre, and the exit ledge copies P7 7500 to
the right. The tests find everything by semantic ids (purpleExtensions,
routeMap), never by numeric index.

MIDDLE_PURPLE_CANDIDATE=DIR (extended-mountain.svg, -measurements.json,
.level.json, .level.js) selects the candidate. Without it, the candidate is
generated into a temporary directory. MIDDLE_PURPLE_EVIDENCE_DIR=DIR writes
route.json, geometry.json and runtime.json.

    MIDDLE_PURPLE_CANDIDATE=artifacts/TASK-682/candidate python3 -m unittest discover -s tools -p test_middle_purple_route.py -v
"""
from contextlib import ExitStack
import copy
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

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import check_level_geometry as geometry  # noqa: E402
import convert_extended_mountain_svg as conv  # noqa: E402
from import_level_svg import dumps, import_svg  # noqa: E402
import retune_extended_level as retune  # noqa: E402

EVIDENCE = os.environ.get('MIDDLE_PURPLE_EVIDENCE_DIR')
SOURCE = ROOT / 'artifacts' / 'level' / 'extended-mountain-measurements.json'
ARGS = ['--min-side-scope', 'all', '--middle-purple']
NAMES = ('extended-mountain.svg', 'extended-mountain-measurements.json', 'extended-mountain.level.json',
         'extended-mountain.level.js')
R = 540.0
CANONICAL_TRANSFER = 1080.0
OUT = {'route.json': {}, 'geometry.json': {}}
_TMP = []


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else Path(data).read_bytes()).hexdigest()


def generate(dest):
    dest = Path(dest)
    subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source', str(SOURCE),
                    '--output-dir', str(dest)] + ARGS, check=True, capture_output=True, cwd=ROOT)
    for name, fmt in ((NAMES[2], []), (NAMES[3], ['--format', 'javascript'])):
        subprocess.run([sys.executable, str(TOOLS / 'import_level_svg.py'), '--input', str(dest / NAMES[0]),
                        '--output', str(dest / name)] + fmt, check=True, capture_output=True, cwd=ROOT)
    return dest


def candidate_dir():
    if os.environ.get('MIDDLE_PURPLE_CANDIDATE'):
        return Path(os.environ['MIDDLE_PURPLE_CANDIDATE']).resolve()
    if not _TMP:
        _TMP.append(tempfile.TemporaryDirectory())
        generate(_TMP[0].name)
    return Path(_TMP[0].name)


def bodies_box(f):
    pts = [p for b in conv.bodies(f) for p in b]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def rp(p):
    return [round(p[0], 6), round(p[1], 6)]


class MiddlePurpleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = candidate_dir()
        cls.m = json.loads((cls.dir / NAMES[1]).read_text())
        cls.svg = (cls.dir / NAMES[0]).read_bytes()
        cls.level = json.loads((cls.dir / NAMES[2]).read_text())
        cls.fs = {f['id']: f for f in cls.m['fragments']}
        cls.by = {f['semanticId']: f for f in cls.m['fragments']}
        cls.rows = {r['id']: r for r in cls.m['encounters']}
        cls.exts = retune.purple_extensions(cls.m)
        cls.zones = {z['id']: z for z in cls.m['noGrappleZones']}
        # The same generator without the middle encounter: the TASK-681 candidate (byte-identical, run.sh).
        cls.base = retune.tune(json.loads(SOURCE.read_text()), opening=retune.OPENING,
                               yellow_clearance=retune.YELLOW_CLEARANCE, min_sides='all')
        cls.check = geometry.check(cls.level, cls.svg, cls.m, min_side=geometry.MIN_SIDE_LENGTH)

    def test_01_deterministic_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = [generate(Path(tmp) / ('run%d' % i)) for i in range(2)]
            got = {n: [sha(r / n) for r in runs] for n in NAMES}
        want = {n: sha(self.dir / n) for n in NAMES}
        self.assertEqual({n: v[0] == v[1] == want[n] for n, v in got.items()}, {n: True for n in NAMES})
        OUT['route.json']['regeneration'] = dict(
            command='retune_extended_level.py --source %s --output-dir <dir> %s; import_level_svg.py (json, javascript)'
                    % (SOURCE.relative_to(ROOT), ' '.join(ARGS)), runs=2, sha256=want, byteIdenticalTwice=True)

    def test_02_two_zones_in_route_order(self):
        self.assertEqual([e['zone'] for e in self.exts], ['NG1', 'NGM'])
        self.assertEqual(sorted(self.zones), ['NG1', 'NGM'])
        self.assertEqual(self.m['purpleExtension'], self.exts[0])
        first, mid = self.exts
        z1, z2 = self.zones['NG1'], self.zones['NGM']
        self.assertEqual((z2['width'], z2['height']), (z1['width'], z1['height']))
        self.assertEqual(z2.get('mirrorOf'), 'NG1')
        self.assertGreater(geometry.union_distance([z1['polygon']], [z2['polygon']])[0], 0)
        # Semantic sequences: approach, entry, four rope-free bounces, exit.
        seq = lambda p: [p + '-APPROACH', p + '-ENTRY'] + ['%s-%s%d-%s%d' % (p, p, i, p, i + 1) for i in range(1, 5)] + [p + '-EXIT']
        self.assertEqual(first['encounters'], seq('NG'))
        self.assertEqual(mid['encounters'], seq('NGM'))
        order = [r['id'] for r in self.m['encounters']]
        n1, n2 = [[self.rows[i]['number'] for i in e['encounters']] for e in self.exts]
        for nums in (n1, n2):
            self.assertEqual(nums, list(range(nums[0], nums[0] + 7)))
        between = order[n1[-1]:n2[0] - 1]
        self.assertEqual(between, ['S07-03', 'S07-04', 'S08-01'])
        self.assertTrue(all(not self.rows[i].get('noGrappleZone') for i in between))
        self.assertTrue(all(self.rows[i]['distance'] >= 2 * R * .75 for i in between))
        # Every chain: arrival -> approach -> internal -> exit, then the original upward transfer from the exit.
        for ext, up, before in ((first, 'S07-03', 'OPEN-L2-P4'), (mid, 'S08-02', 'S08-01')):
            chain = [ext['arrival'], ext['approach']] + ext['internal'] + [ext['exit']]
            rows = [self.rows[i] for i in ext['encounters']]
            self.assertEqual([(r['fromFragment'], r['toFragment']) for r in rows], list(zip(chain, chain[1:])))
            self.assertEqual(self.rows[up]['fromFragment'], ext['exit'])
            self.assertEqual(self.rows[before]['toFragment'], ext['arrival'])
        semantic = lambda e: dict(zone=e['zone'], arrival=self.fs[e['arrival']]['semanticId'],
                                  approach=self.fs[e['approach']]['semanticId'], exit=self.fs[e['exit']]['semanticId'],
                                  internal=[self.fs[i]['semanticId'] for i in e['internal']])
        self.assertEqual(semantic(mid), dict(zone='NGM', arrival='P7', approach='NGM-APPROACH', exit='NGM-EXIT',
                                             internal=['NGM%d' % i for i in range(1, 6)]))
        cx = lambda fid: conv.contact(self.fs[fid])[0]
        chain = [mid['arrival'], mid['approach']] + mid['internal']
        self.assertTrue(all(cx(b) > cx(a) for a, b in zip(chain, chain[1:])))  # rightward, NG1 mirrored
        box = lambda fid: bodies_box(self.fs[fid])
        zx0, zy0, zx1 = z2['x'], z2['y'], z2['x'] + z2['width']
        self.assertGreater(zx0, box(mid['approach'])[2])
        self.assertLess(box(mid['exit'])[2], zx1)       # the exit overhangs the zone's upper-right part
        self.assertLess(box(mid['exit'])[3], zy0)       # ... above its top edge
        OUT['route.json']['encounters'] = [dict(
            zone=e['zone'], semantic=semantic(e), ids={k: e[k] for k in ('arrival', 'approach', 'exit', 'internal')},
            sequence=[dict(id=i, number=self.rows[i]['number'], direction=self.rows[i]['direction'],
                           fromSemantic=self.fs[self.rows[i]['fromFragment']]['semanticId'],
                           toSemantic=self.fs[self.rows[i]['toFragment']]['semanticId'],
                           gap=self.rows[i]['distance'], noGrappleZone=self.rows[i].get('noGrappleZone'))
                      for i in e['encounters']],
            upperTranslation=e['upperTranslation'], mirrorOf=e.get('mirrorOf')) for e in self.exts]
        OUT['route.json']['placement'] = dict(
            originalLastNumber=n1[-1], middleFirstNumber=n2[0], separatingGrappleTransfers=[
                dict(id=i, number=self.rows[i]['number'], gap=self.rows[i]['distance'], direction=self.rows[i]['direction'])
                for i in between],
            zones={k: dict(x=z['x'], y=z['y'], width=z['width'], height=z['height'], mirrorOf=z.get('mirrorOf'))
                   for k, z in self.zones.items()},
            zoneGap=geometry.union_distance([z1['polygon']], [z2['polygon']])[0],
            middleExitAboveZoneTop=zy0 - box(mid['exit'])[3], middleExitRightOfZoneRight=zx1 - box(mid['exit'])[2],
            originalExitAboveZoneTop=z1['y'] - box(first['exit'])[3])

    def test_03_mirror_of_ng1_and_containment(self):
        z1, z2 = self.zones['NG1'], self.zones['NGM']
        rel = lambda f, z, mirror: [sorted((round(z['x'] + z['width'] - x if mirror else x - z['x'], 6), round(y - z['y'], 6))
                                           for x, y in b) for b in conv.bodies(f)]
        diffs = {}
        for i in range(1, 6):
            a, b = self.by['NG%d' % i], self.by['NGM%d' % i]
            self.assertEqual(rel(a, z1, False), rel(b, z2, True), i)
            self.assertEqual(b['surfaceAngle'], -a['surfaceAngle'])
            diffs['NGM%d' % i] = 0.0
        a1, a2 = self.by['NG-APPROACH'], self.by['NGM-APPROACH']
        self.assertAlmostEqual(a1['x'] - (z1['x'] + z1['width']), z2['x'] - (a2['x'] + a2['width']), places=6)
        self.assertAlmostEqual(a1['y'] - z1['y'], a2['y'] - z2['y'], places=6)
        self.assertEqual(a1['polys'], a2['polys'])
        # Every internal polygon and every internal transfer witness lies in NGM; nothing else touches it.
        zones = [(z, self.zones[z]['polygon']) for z in self.zones]
        mid = self.exts[1]
        for fid in mid['internal']:
            self.assertTrue(all(geometry.convex_contains(z2['polygon'], p) for b in conv.bodies(self.fs[fid]) for p in b))
        touching = sorted(f['id'] for f in self.m['fragments'] if geometry.union_distance(conv.bodies(f), [z2['polygon']])[0] <= 0)
        self.assertEqual(touching, sorted(mid['internal']))
        internal = []
        for rid in mid['encounters']:
            r = self.rows[rid]
            a, b = self.fs[r['fromFragment']], self.fs[r['toFragment']]
            d, witness, _, _ = geometry.union_distance(conv.bodies(a), conv.bodies(b))
            zone = geometry.containing_zone(zones, conv.bodies(a) + conv.bodies(b), witness)
            if r.get('noGrappleZone'):
                self.assertEqual((r['noGrappleZone'], zone), ('NGM', 'NGM'))
                self.assertTrue(0 < d <= retune.NO_GRAPPLE_INTERNAL_GAP)
                twin = self.rows[rid.replace('NGM', 'NG')]
                self.assertAlmostEqual(d, twin['distance'], places=6)
            else:
                self.assertIsNone(zone, rid)
                self.assertGreaterEqual(d, CANONICAL_TRANSFER - .01, rid)
            internal.append(dict(id=rid, gap=d, witness=[rp(p) for p in witness], containingZone=zone,
                                 ng1Twin=rid.replace('NGM', 'NG'), ng1TwinGap=self.rows[rid.replace('NGM', 'NG')]['distance']))
        self.assertAlmostEqual(self.rows['NGM-ENTRY']['distance'], self.rows['NG-ENTRY']['distance'], places=6)
        posts = self.m['shortcutShields']['posts']
        self.assertEqual([p['semanticId'] for p in posts], ['NG1', 'NGM1'])
        self.assertAlmostEqual(posts[0]['entryGap'], posts[1]['entryGap'], places=6)
        OUT['route.json']['middleZone'] = dict(
            mirrorOf='NG1', reflectedAbout=z2['x'] + z2['width'] / 2, internalShapesEqualReflectedNG1=diffs,
            approachZoneGap=[a1['x'] - (z1['x'] + z1['width']), z2['x'] - (a2['x'] + a2['width'])],
            approachAboveZoneTop=[z1['y'] - a1['y'], z2['y'] - a2['y']], transfers=internal,
            fragmentsTouchingZone=touching, posts=posts,
            note='Momentum/bounce semantics are NG1\'s (kicker slope, low ceiling, chute floor, overhang, launch ramp) '
                 'mirrored for a rightward run. The exit ledge copies P7, which sits 200 above the zone instead of '
                 'the 60 of NG1\'s exit (a copy of P4), so NGM-EXIT is longer. Traversal is TASK-683.')

    def test_04_rest_of_route_preserved_or_translated(self):
        base = {f['semanticId']: f for f in self.base['fragments']}
        order = [f['semanticId'] for f in self.base['fragments']]
        cut = order.index('P7')
        added = sorted(set(self.by) - set(base))
        self.assertEqual(added, sorted(['NGM-APPROACH', 'NGM-EXIT'] + ['NGM%d' % i for i in range(1, 6)]))
        self.assertEqual(set(base) - set(self.by), set())
        dx, dy = self.exts[1]['upperTranslation']
        self.assertEqual((dx, dy), (7500, 0))
        same, moved = [], []
        for k, s in enumerate(order):
            a, b = base[s], self.by[s]
            self.assertEqual((a['polys'], a['width'], a['height'], a['kind']), (b['polys'], b['width'], b['height'], b['kind']), s)
            if k <= cut:
                self.assertEqual((a['x'], a['y']), (b['x'], b['y']), s)
                same.append(s)
            else:
                self.assertAlmostEqual(b['x'] - a['x'], dx, places=9)
                self.assertEqual(b['y'], a['y'], s)
                moved.append(s)
        # The exit copies P7 (translated) after both are resized identically.
        e, p7 = self.by['NGM-EXIT'], self.by['P7']
        self.assertEqual((e['polys'], e['width'], e['height']), (p7['polys'], p7['width'], p7['height']))
        self.assertAlmostEqual(e['x'] - p7['x'], dx, places=9)
        rows_b = {r['id']: r for r in self.base['encounters']}
        gaps = {i: abs(rows_b[i]['distance'] - self.rows[i]['distance']) for i in rows_b}
        self.assertLess(max(gaps.values()), 1e-6)
        self.assertEqual([r['id'] for r in self.m['encounters'] if r['id'] in rows_b], [r['id'] for r in self.base['encounters']])
        # Combinations keep their encounter ids.
        ids = lambda m: [[m['encounters'][n - 1]['id'] for n in g] for g in m['combinations']]
        self.assertEqual(ids(self.m), ids(self.base))
        # Late route still above the lower terrain (falls land on it).
        fsl = self.m['fragments']; fid = [f['id'] for f in fsl]
        lower = fsl[:fid.index(self.m['lowerCatchExtension']['firstUpDeparture']) + 1]
        late = fsl[fid.index(self.exts[1]['exit']) + 1:]
        lx = [x for f in lower for b in conv.bodies(f) for x, _ in b]
        xs = [x for f in late for b in conv.bodies(f) for x, _ in b]
        self.assertGreaterEqual(min(xs), min(lx))
        self.assertLessEqual(max(xs), max(lx))
        bands = lambda m: {b['id']: [round(v, 3) for v in (b['x'], b['y'], b['width'], b['height'])] for b in m['yellowBands']}
        bb, bn = bands(self.base), bands(self.m)
        OUT['route.json']['preservation'] = dict(
            comparedWith='retune --min-side-scope all without --middle-purple (= artifacts/TASK-681/candidate, cmp in commands.log)',
            identicalFragments=same, translatedFragments=moved, translation=[dx, dy], addedSemanticIds=added,
            maxPreexistingTransferGapChange=max(gaps.values()), preexistingTransfers=len(rows_b),
            lateRouteX=[min(xs), max(xs)], lowerRouteX=[min(lx), max(lx)],
            yellowBands=dict(unchanged=sorted(k for k in bb if bn.get(k) == bb[k]),
                             changedOrNew={k: dict(before=bb.get(k), after=v) for k, v in bn.items() if bb.get(k) != v},
                             removed={k: bb[k] for k in set(bb) - set(bn)},
                             note='Bands and shortcut guards are regenerated from the final geometry; Y2 stays under '
                                  'P7 and the pre-shift P8 (band_endpoints), every band keeps >= 1620 from green.'))

    def test_05_ids_and_references(self):
        ids = re.findall(rb'\sid="([^"]+)"', self.svg)
        dup = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(dup, [])
        els = [e['id'] for e in self.level['elements']]
        self.assertEqual(len(els), len(set(els)))
        frag_ids = {f['id'] for f in self.level['svgFormat']['fragments']}
        self.assertEqual(frag_ids, set(self.fs))
        tr = self.level['svgFormat']['transfers']
        self.assertEqual([(t['id'], t['from'], t['to']) for t in tr],
                         [('T%02d' % r['number'], r['fromFragment'], r['toFragment']) for r in self.m['encounters']])
        self.assertTrue(all(len(t['guide']) == 4 for t in tr))
        arrows = re.findall(rb'<g id="arrow-(T\d+)" class="transfer-arrow" data-transfer="(T\d+)" data-from="(P\d+)" data-to="(P\d+)"', self.svg)
        self.assertEqual([tuple(x.decode() for x in a[1:]) for a in arrows], [(t['id'], t['from'], t['to']) for t in tr])
        enc = [r['id'] for r in self.m['encounters']]
        self.assertEqual(len(enc), len(set(enc)))
        self.assertEqual(len(self.m['fragments']), len(set(self.by)))
        rm = self.m['routeMap']
        dangling = [v for v in list(rm['fragmentIds'].values()) + list(rm['addedFragments'].values()) if v not in self.fs]
        dangling += [i for e in self.exts for k in ('arrival', 'approach', 'exit', 'exitCopiesDeparture')
                     for i in [e[k]] if i not in self.fs]
        dangling += [i for e in self.exts for i in e['internal'] if i not in self.fs]
        dangling += [i for e in self.exts for i in e['encounters'] if i not in self.rows]
        dangling += [z for z in (e['zone'] for e in self.exts) if z not in self.zones or z not in els]
        dangling += [b[k] for b in self.m['yellowBands'] for k in ('source', 'target') if b.get(k) and b[k] not in self.fs]
        dangling += [p['fragment'] for p in self.m['shortcutShields']['posts'] if p['fragment'] not in self.fs]
        dangling += [i for i in self.m['lowerCatchExtension']['fragments'] if i not in self.fs]
        dangling += [c['fragment'] for c in self.m['minimumSides']['laterChanged'] if c['fragment'] not in self.fs]
        self.assertEqual(dangling, [])
        self.assertTrue(all(rm['addedFragments'][s] == self.by[s]['id'] for s in
                            ['NGM-APPROACH', 'NGM-EXIT'] + ['NGM%d' % i for i in range(1, 6)]))
        self.assertTrue(set(self.exts[1]['encounters']) <= set(rm['addedEncounters']))
        self.assertTrue(all(1 <= n <= len(enc) for g in self.m['combinations'] for n in g))
        OUT['route.json']['ids'] = dict(svgIds=len(ids), duplicateSvgIds=dup, levelElements=len(els),
                                        fragments=len(frag_ids), transfers=len(tr), guides=len(tr), arrows=len(arrows),
                                        encounterIds=len(enc), danglingReferences=dangling,
                                        remappedGuidesArrows=[dict(id=t['id'], **{'from': t['from'], 'to': t['to']},
                                                                   encounter=r['id']) for t, r in zip(tr, self.m['encounters'])
                                                              if r['id'].startswith('NGM') or r['id'] == 'S08-02'])

    def test_06_geometry_min_sides_and_zone_rules(self):
        s = self.check['summary']
        self.assertTrue(s['pass'], self.check['failureMessages'][:5])
        self.assertEqual((s['noGrappleZones'], s['noGrappleZonesPass']), (2, 2))
        self.assertEqual(s['noGrappleInternalPairs'], 8)
        rows = {z['id']: z for z in self.check['noGrappleZones']}
        for zid, ext in zip(('NG1', 'NGM'), self.exts):
            want = sorted(sorted(p) for p in zip(ext['internal'], ext['internal'][1:]))
            self.assertEqual(rows[zid]['internalPairs'], want)
        sides = self.check['sides']
        measured = [e for e in sides if not e['exempt']]
        self.assertTrue(s['minSideEnforced'])
        self.assertEqual((s['sideViolations'], s['sideExemptEdges']), (0, 0))
        self.assertGreaterEqual(s['minMeasuredSide'], 270)
        mid = {self.by[k]['id'] for k in ['NGM-APPROACH', 'NGM-EXIT'] + ['NGM%d' % i for i in range(1, 6)]}
        mid_edges = [e for e in measured if e['fragment'] in mid]
        self.assertTrue(mid_edges and all(e['pass'] for e in mid_edges))
        outside = [p for p in self.check['pairs'] if p['rule'] != 'noGrappleInternal']
        self.assertTrue(outside and all(p['pass'] for p in outside))
        OUT['geometry.json'].update(
            method='tools/check_level_geometry.check(level, svg, measurements, min_side=270) on the candidate '
                   '(every rule; the 270 minimum side enforced with no exemptions)',
            summary=s, noGrappleZones=self.check['noGrappleZones'],
            middleEncounterEdges=dict(count=len(mid_edges), minLength=min(e['length'] for e in mid_edges),
                                      byFragment={f: min(e['length'] for e in mid_edges if e['fragment'] == f) for f in sorted(mid)}),
            shortEdges=[e for e in measured if not e['pass']],
            outsidePairs=dict(count=len(outside), allPass=True))

    def test_07_runtime_loads_both_zones(self):
        from browser_test_support import start_browser_test, wait_for_boot
        script = '''data => { validateFixedLevel(structuredClone(data)); const w = loadFixedLevel(structuredClone(data))
            return {zones: w.noGrappleZones.map(z => ({id: z.id, grapplable: z.grapplable, points: z.getPoints().length})),
                    elements: w.elements.map(e => e.id), grapplable: w.elements.filter(e => e.grapplable).map(e => e.id),
                    drag: w.dragZones.map(e => e.id)} }'''
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url)
            wait_for_boot(page)
            r = page.evaluate(script, self.level)
        self.assertEqual(errors, [])
        self.assertEqual(r['zones'], [dict(id='NG1', grapplable=False, points=4), dict(id='NGM', grapplable=False, points=4)])
        for z in ('NG1', 'NGM'):
            self.assertNotIn(z, r['elements'] + r['grapplable'] + r['drag'])
        OUT['runtime.json'] = dict(method='production fixedlevel.js validateFixedLevel/loadFixedLevel in booted Chromium',
                                   zones=r['zones'], elements=len(r['elements']), pageErrors=errors)


def tearDownModule():
    if not EVIDENCE:
        return
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    srcs = {p: sha(ROOT / p) for p in ('tools/retune_extended_level.py', 'tools/convert_extended_mountain_svg.py',
                                       'tools/import_level_svg.py', 'tools/check_level_geometry.py',
                                       'tools/test_middle_purple_route.py', 'fixedlevel.js')}
    cand = candidate_dir()
    for name, body in OUT.items():
        if body:
            Path(EVIDENCE, name).write_text(json.dumps(dict(candidate=str(cand), candidateSha256={n: sha(cand / n) for n in NAMES},
                                                            sources=srcs, **body), indent=1) + '\n')


if __name__ == '__main__':
    unittest.main()
