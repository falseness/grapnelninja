"""Third (upper) purple no-grapple encounter NGU (TASK-684, candidate only).

retune_extended_level.py --min-side-scope all --middle-purple --upper-purple
adds a third purple encounter after EXT-13, higher and later than the middle NGM
chute, with the normal grapple transfers S08-02 .. EXT-13 between them. NGU runs
leftward with NG1's unmirrored slabs and post (NGM is NG1 mirrored, rightward):
the approach is left of P13, the zone left of the approach at NG1's height below
it, and the exit ledge copies P13 7500 to the left, so EXT-14 and every later
panel keep their geometry translated by -7500. NG1 and NGM stay exactly as in
the --middle-purple candidate (TASK-683). Everything is found by semantic ids
(purpleExtensions, routeMap), never by numeric index. Traversal of NGU is later work.

UPPER_PURPLE_CANDIDATE=DIR (extended-mountain.svg, -measurements.json,
.level.json, .level.js) selects the candidate. Without it, the candidate is
generated into a temporary directory. UPPER_PURPLE_EVIDENCE_DIR=DIR writes
route.json, geometry.json and runtime.json.

    UPPER_PURPLE_CANDIDATE=artifacts/TASK-684/candidate python3 -m unittest discover -s tools -p test_upper_purple_route.py -v
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

EVIDENCE = os.environ.get('UPPER_PURPLE_EVIDENCE_DIR')
SOURCE = ROOT / 'artifacts' / 'level' / 'extended-mountain-measurements.json'
ARGS = ['--min-side-scope', 'all', '--middle-purple', '--upper-purple']
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
    if os.environ.get('UPPER_PURPLE_CANDIDATE'):
        return Path(os.environ['UPPER_PURPLE_CANDIDATE']).resolve()
    if not _TMP:
        _TMP.append(tempfile.TemporaryDirectory())
        generate(_TMP[0].name)
    return Path(_TMP[0].name)


def bodies_box(f):
    pts = [p for b in conv.bodies(f) for p in b]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def rp(p):
    return [round(p[0], 6), round(p[1], 6)]


SEQ = lambda p: [p + '-APPROACH', p + '-ENTRY'] + ['%s-%s%d-%s%d' % (p, p, i, p, i + 1) for i in range(1, 5)] + [p + '-EXIT']
UPPER = ['NGU-APPROACH', 'NGU-EXIT'] + ['NGU%d' % i for i in range(1, 6)]


class UpperPurpleTests(unittest.TestCase):
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
        # The same generator without the upper encounter: the TASK-683 middle-purple candidate (cmp in commands.log).
        cls.base = retune.tune(json.loads(SOURCE.read_text()), opening=retune.OPENING,
                               yellow_clearance=retune.YELLOW_CLEARANCE, min_sides='all', middle_purple=True)
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

    def test_02_three_zones_in_route_order(self):
        self.assertEqual([e['zone'] for e in self.exts], ['NG1', 'NGM', 'NGU'])
        self.assertEqual(sorted(self.zones), ['NG1', 'NGM', 'NGU'])
        self.assertEqual([z['id'] for z in self.m['noGrappleZones']], ['NG1', 'NGM', 'NGU'])
        self.assertEqual(self.m['purpleExtension'], self.exts[0])
        first, mid, up = self.exts
        zs = [self.zones[e['zone']] for e in self.exts]
        self.assertTrue(all((z['width'], z['height']) == (zs[0]['width'], zs[0]['height']) for z in zs))
        self.assertEqual((self.zones['NGU'].get('copyOf'), self.zones['NGU'].get('mirrorOf')), ('NG1', None))
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertGreater(geometry.union_distance([zs[i]['polygon']], [zs[j]['polygon']])[0], 0)
        for ext, p in zip(self.exts, ('NG', 'NGM', 'NGU')):
            self.assertEqual(ext['encounters'], SEQ(p))
        order = [r['id'] for r in self.m['encounters']]
        nums = [[self.rows[i]['number'] for i in e['encounters']] for e in self.exts]
        for n in nums:
            self.assertEqual(n, list(range(n[0], n[0] + 7)))
        self.assertTrue(nums[0][-1] < nums[1][0] and nums[1][-1] < nums[2][0])
        between = [order[nums[0][-1]:nums[1][0] - 1], order[nums[1][-1]:nums[2][0] - 1]]
        self.assertEqual(between[0], ['S07-03', 'S07-04', 'S08-01'])
        self.assertEqual(between[1], ['S08-02', 'S08-03', 'S08-04', 'EXT-11', 'EXT-12', 'EXT-13'])
        for group in between:
            self.assertTrue(all(not self.rows[i].get('noGrappleZone') for i in group))
            self.assertTrue(all(self.rows[i]['distance'] >= 2 * R * .75 for i in group))
        # Each chain: arrival -> approach -> internal -> exit, then the original transfer leaves the exit copy.
        for ext, upid, before in ((first, 'S07-03', 'OPEN-L2-P4'), (mid, 'S08-02', 'S08-01'), (up, 'EXT-14', 'EXT-13')):
            chain = [ext['arrival'], ext['approach']] + ext['internal'] + [ext['exit']]
            rows = [self.rows[i] for i in ext['encounters']]
            self.assertEqual([(r['fromFragment'], r['toFragment']) for r in rows], list(zip(chain, chain[1:])))
            self.assertEqual(self.rows[upid]['fromFragment'], ext['exit'])
            self.assertEqual(self.rows[before]['toFragment'], ext['arrival'])
            self.assertTrue(all(r.get('noGrappleZone') == (ext['zone'] if 2 <= k <= 5 else None) for k, r in enumerate(rows)))
        semantic = lambda e: dict(zone=e['zone'], arrival=self.fs[e['arrival']]['semanticId'],
                                  approach=self.fs[e['approach']]['semanticId'], exit=self.fs[e['exit']]['semanticId'],
                                  internal=[self.fs[i]['semanticId'] for i in e['internal']])
        self.assertEqual(semantic(up), dict(zone='NGU', arrival='P13', approach='NGU-APPROACH', exit='NGU-EXIT',
                                            internal=['NGU%d' % i for i in range(1, 6)]))
        cx = lambda fid: conv.contact(self.fs[fid])[0]
        way = lambda e: [e['arrival'], e['approach']] + e['internal']
        self.assertTrue(all(cx(b) > cx(a) for a, b in zip(way(mid), way(mid)[1:])))  # NGM rightward (mirrored)
        self.assertTrue(all(cx(b) < cx(a) for a, b in zip(way(up), way(up)[1:])))    # NGU leftward: opposite
        box = lambda fid: bodies_box(self.fs[fid])
        zu = self.zones['NGU']
        self.assertLess(zu['x'] + zu['width'], box(up['approach'])[0])
        self.assertGreater(box(up['exit'])[0], zu['x'])        # the exit overhangs the zone's upper-left part
        self.assertLess(box(up['exit'])[3], zu['y'])           # ... above its top edge
        # Higher and later: the upper zone lies above the middle one, which lies above NG1.
        self.assertLess(zu['y'] + zu['height'], self.zones['NGM']['y'])
        self.assertLess(self.zones['NGM']['y'] + self.zones['NGM']['height'], self.zones['NG1']['y'])
        OUT['route.json']['encounters'] = [dict(
            zone=e['zone'], semantic=semantic(e), ids={k: e[k] for k in ('arrival', 'approach', 'exit', 'internal')},
            direction='rightward' if e.get('mirror') else 'leftward',
            sequence=[dict(id=i, number=self.rows[i]['number'], direction=self.rows[i]['direction'],
                           fromSemantic=self.fs[self.rows[i]['fromFragment']]['semanticId'],
                           toSemantic=self.fs[self.rows[i]['toFragment']]['semanticId'],
                           fromFragment=self.rows[i]['fromFragment'], toFragment=self.rows[i]['toFragment'],
                           gap=self.rows[i]['distance'], noGrappleZone=self.rows[i].get('noGrappleZone'))
                      for i in e['encounters']],
            upperTranslation=e['upperTranslation'], mirrorOf=e.get('mirrorOf'), copyOf=e.get('copyOf'))
            for e in self.exts]
        # Encounter sections: each zone's seven rows form one contiguous route segment, in route order, disjoint and
        # separated by normal grapple transfers (the level format's own sections are recorded alongside).
        level_sections = {i: s['id'] for s in self.level['sections'] for i in s['encounters']}
        segments = [dict(zone=e['zone'], numbers=[n[0], n[-1]], encounters=e['encounters'],
                         levelSections=sorted({level_sections[i] for i in e['encounters']}, key=list(
                             s['id'] for s in self.level['sections']).index)) for e, n in zip(self.exts, nums)]
        self.assertTrue(all(a['numbers'][1] < b['numbers'][0] for a, b in zip(segments, segments[1:])))
        self.assertEqual(sorted(i for g in segments for i in g['encounters']),
                         sorted({i for g in segments for i in g['encounters']}))
        OUT['route.json']['encounterSections'] = dict(
            segments=segments, ordered=True, disjoint=True,
            separatedBy={'NG1->NGM': between[0], 'NGM->NGU': between[1]},
            note='Encounter sections are route segments (routeMap/encounter numbers). The importer derives level '
                 'sections from the jump combinations, so NG1 and NGM rows sit in SEC-baseline (as in TASK-682/683) '
                 'and NGU rows (after chain1) are single-jump sections.')
        OUT['route.json']['placement'] = dict(
            zoneCount=len(self.zones), zoneIdsUnique=len(set(self.zones)) == len(self.m['noGrappleZones']),
            encounterNumbers={e['zone']: [n[0], n[-1]] for e, n in zip(self.exts, nums)},
            separatingGrappleTransfers=[[dict(id=i, number=self.rows[i]['number'], gap=self.rows[i]['distance'],
                                              direction=self.rows[i]['direction']) for i in g] for g in between],
            zones={k: dict(x=z['x'], y=z['y'], width=z['width'], height=z['height'], mirrorOf=z.get('mirrorOf'),
                           copyOf=z.get('copyOf')) for k, z in self.zones.items()},
            orientation=dict(NGM='rightward, NG1 mirrored', NGU='leftward, NG1 unmirrored (opposite to NGM)'),
            upperExitAboveZoneTop=zu['y'] - box(up['exit'])[3], upperExitLeftOffsetInZone=box(up['exit'])[0] - zu['x'])

    def test_03_copy_of_ng1_and_containment(self):
        z1, zu = self.zones['NG1'], self.zones['NGU']
        rel = lambda f, z: [sorted((round(x - z['x'], 6), round(y - z['y'], 6)) for x, y in b) for b in conv.bodies(f)]
        for i in range(1, 6):
            a, b = self.by['NG%d' % i], self.by['NGU%d' % i]
            self.assertEqual(b['surfaceAngle'], a['surfaceAngle'])
            self.assertEqual(rel(a, z1), rel(b, zu), i)
        a1, au = self.by['NG-APPROACH'], self.by['NGU-APPROACH']
        self.assertAlmostEqual(a1['x'] - (z1['x'] + z1['width']), au['x'] - (zu['x'] + zu['width']), places=6)
        self.assertAlmostEqual(a1['y'] - z1['y'], au['y'] - zu['y'], places=6)
        self.assertEqual(a1['polys'], au['polys'])
        zones = [(z, self.zones[z]['polygon']) for z in self.zones]
        up = self.exts[2]
        for fid in up['internal']:
            self.assertTrue(all(geometry.convex_contains(zu['polygon'], p) for b in conv.bodies(self.fs[fid]) for p in b))
        touching = sorted(f['id'] for f in self.m['fragments'] if geometry.union_distance(conv.bodies(f), [zu['polygon']])[0] <= 0)
        self.assertEqual(touching, sorted(up['internal']))
        internal = []
        for rid in up['encounters']:
            r = self.rows[rid]
            a, b = self.fs[r['fromFragment']], self.fs[r['toFragment']]
            d, witness, _, _ = geometry.union_distance(conv.bodies(a), conv.bodies(b))
            zone = geometry.containing_zone(zones, conv.bodies(a) + conv.bodies(b), witness)
            twin = rid.replace('NGU', 'NG')
            if r.get('noGrappleZone'):
                self.assertEqual((r['noGrappleZone'], zone), ('NGU', 'NGU'))
                self.assertTrue(0 < d <= retune.NO_GRAPPLE_INTERNAL_GAP)
                self.assertAlmostEqual(d, self.rows[twin]['distance'], places=6)
            else:
                self.assertIsNone(zone, rid)
                self.assertGreaterEqual(d, CANONICAL_TRANSFER - .01, rid)
            internal.append(dict(id=rid, gap=d, witness=[rp(p) for p in witness], containingZone=zone,
                                 ng1Twin=twin, ng1TwinGap=self.rows[twin]['distance']))
        self.assertAlmostEqual(self.rows['NGU-ENTRY']['distance'], self.rows['NG-ENTRY']['distance'], places=6)
        self.assertAlmostEqual(self.rows['NGU-APPROACH']['distance'], self.rows['NG-APPROACH']['distance'], places=6)
        posts = self.m['shortcutShields']['posts']
        self.assertEqual([p['semanticId'] for p in posts], ['NG1', 'NGM1', 'NGU1'])
        self.assertAlmostEqual(posts[0]['entryGap'], posts[2]['entryGap'], places=6)
        OUT['route.json']['upperZone'] = dict(
            copyOf='NG1', internalShapesEqualNG1RelativeToZone=True,
            approachZoneGap=[a1['x'] - (z1['x'] + z1['width']), au['x'] - (zu['x'] + zu['width'])],
            approachAboveZoneTop=[z1['y'] - a1['y'], zu['y'] - au['y']], transfers=internal,
            fragmentsTouchingZone=touching, posts=posts,
            note='NG1\'s bounce semantics (kicker slope, low ceiling, chute floor, overhang, launch ramp) in NG1\'s '
                 'leftward orientation, the opposite of the rightward mirrored NGM. The exit ledge copies P13 (3300 x '
                 '360), so it sits %.0f above the zone instead of NG1\'s 60 and NGU-EXIT is longer. Traversal and '
                 'tuning are later work.' % (zu['y'] - bodies_box(self.by['NGU-EXIT'])[3]))

    def test_04_earlier_route_preserved_later_translated(self):
        base = {f['semanticId']: f for f in self.base['fragments']}
        order = [f['semanticId'] for f in self.base['fragments']]
        cut = order.index('P13')
        added = sorted(set(self.by) - set(base))
        self.assertEqual(added, sorted(UPPER))
        self.assertEqual(set(base) - set(self.by), set())
        dx, dy = self.exts[2]['upperTranslation']
        self.assertEqual((dx, dy), (-7500, 0))
        self.assertEqual(self.exts[:2], retune.purple_extensions(self.base))
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
        self.assertTrue({'P0', 'P2', 'R1', 'X10', 'P4', 'NG1', 'NG5', 'NGM1', 'NGM5', 'P8', 'P13'} <= set(same))
        e, p13 = self.by['NGU-EXIT'], self.by['P13']
        self.assertEqual((e['polys'], e['width'], e['height']), (p13['polys'], p13['width'], p13['height']))
        self.assertAlmostEqual(e['x'] - p13['x'], dx, places=9)
        self.assertEqual(e['y'], p13['y'])
        rows_b = {r['id']: r for r in self.base['encounters']}
        gaps = {i: abs(rows_b[i]['distance'] - self.rows[i]['distance']) for i in rows_b}
        self.assertLess(max(gaps.values()), 1e-6)
        self.assertEqual([r['id'] for r in self.m['encounters'] if r['id'] in rows_b], [r['id'] for r in self.base['encounters']])
        ids = lambda m: [[m['encounters'][n - 1]['id'] for n in g] for g in m['combinations']]
        self.assertEqual(ids(self.m), ids(self.base))
        fsl = self.m['fragments']; fid = [f['id'] for f in fsl]
        lower = fsl[:fid.index(self.m['lowerCatchExtension']['firstUpDeparture']) + 1]
        late = fsl[fid.index(self.exts[2]['exit']) + 1:]
        lx = [x for f in lower for b in conv.bodies(f) for x, _ in b]
        xs = [x for f in late for b in conv.bodies(f) for x, _ in b]
        self.assertGreaterEqual(min(xs), min(lx))
        self.assertLessEqual(max(xs), max(lx))
        bands = lambda m: {b['id']: [round(v, 3) for v in (b['x'], b['y'], b['width'], b['height'])] for b in m['yellowBands']}
        bb, bn = bands(self.base), bands(self.m)
        OUT['route.json']['preservation'] = dict(
            comparedWith='retune --min-side-scope all --middle-purple without --upper-purple (= artifacts/TASK-683/candidate, '
                         'cmp in commands.log)',
            identicalFragments=same, translatedFragments=moved, translation=[dx, dy], addedSemanticIds=added,
            earlierEncountersIdentical=['NG1', 'NGM'],
            maxPreexistingTransferGapChange=max(gaps.values()), preexistingTransfers=len(rows_b),
            lateRouteX=[min(xs), max(xs)], lowerRouteX=[min(lx), max(lx)],
            yellowBands=dict(unchanged=sorted(k for k in bb if bn.get(k) == bb[k]),
                             changedOrNew={k: dict(before=bb.get(k), after=v) for k, v in bn.items() if bb.get(k) != v},
                             removed={k: bb[k] for k in set(bb) - set(bn)},
                             note='Bands and shortcut guards are regenerated from the final geometry; every band keeps '
                                  '>= 1620 from green (independent checker).'))

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
        self.assertTrue(all(rm['addedFragments'][s] == self.by[s]['id'] for s in UPPER))
        self.assertTrue(all(set(e['encounters']) <= set(rm['addedEncounters']) for e in self.exts))
        self.assertTrue(all(1 <= n <= len(enc) for g in self.m['combinations'] for n in g))
        # Every purple encounter row has its guide and arrow, between the same fragments.
        by_num = {t['id']: t for t in tr}
        refs = []
        for e in self.exts:
            for rid in e['encounters']:
                r = self.rows[rid]
                t = by_num['T%02d' % r['number']]
                self.assertEqual((t['from'], t['to']), (r['fromFragment'], r['toFragment']))
                self.assertIn(('T%02d' % r['number']).encode(), [a[0] for a in arrows])
                refs.append(dict(zone=e['zone'], encounter=rid, transfer=t['id'], arrow='arrow-' + t['id'],
                                 **{'from': t['from'], 'to': t['to']}))
        OUT['route.json']['ids'] = dict(svgIds=len(ids), duplicateSvgIds=dup, levelElements=len(els),
                                        fragments=len(frag_ids), transfers=len(tr), guides=len(tr), arrows=len(arrows),
                                        encounterIds=len(enc), danglingReferences=dangling,
                                        purpleRouteArrowReferences=refs)

    def test_06_geometry_min_sides_and_zone_rules(self):
        s = self.check['summary']
        self.assertTrue(s['pass'], self.check['failureMessages'][:5])
        self.assertEqual((s['noGrappleZones'], s['noGrappleZonesPass']), (3, 3))
        self.assertEqual(s['noGrappleInternalPairs'], 12)
        rows = {z['id']: z for z in self.check['noGrappleZones']}
        for ext in self.exts:
            want = sorted(sorted(p) for p in zip(ext['internal'], ext['internal'][1:]))
            self.assertEqual(rows[ext['zone']]['internalPairs'], want)
            self.assertTrue(rows[ext['zone']]['pass'] and rows[ext['zone']]['convex'])
        sides = self.check['sides']
        measured = [e for e in sides if not e['exempt']]
        self.assertTrue(s['minSideEnforced'])
        self.assertEqual((s['sideViolations'], s['sideExemptEdges']), (0, 0))
        self.assertGreaterEqual(s['minMeasuredSide'], 270)
        upper = {self.by[k]['id'] for k in UPPER}
        up_edges = [e for e in measured if e['fragment'] in upper]
        self.assertTrue(up_edges and all(e['pass'] for e in up_edges))
        outside = [p for p in self.check['pairs'] if p['rule'] != 'noGrappleInternal']
        self.assertTrue(outside and all(p['pass'] for p in outside))
        internal = [p for p in self.check['pairs'] if p['rule'] == 'noGrappleInternal']
        self.assertEqual(len(internal), 12)
        self.assertTrue(all(p['pass'] for p in internal))
        OUT['geometry.json'].update(
            method='tools/check_level_geometry.check(level, svg, measurements, min_side=270) on the candidate '
                   '(every rule; the 270 minimum side enforced with no exemptions)',
            summary=s, noGrappleZones=self.check['noGrappleZones'],
            internalPairs=[dict(source=p.get('source'), target=p.get('target'), gap=p.get('gap', p.get('distance')),
                                zone=p.get('zone'), passed=p['pass']) for p in internal],
            upperEncounterEdges=dict(count=len(up_edges), minLength=min(e['length'] for e in up_edges),
                                     byFragment={f: min(e['length'] for e in up_edges if e['fragment'] == f) for f in sorted(upper)}),
            shortEdges=[e for e in measured if not e['pass']],
            outsidePairs=dict(count=len(outside), allPass=True))

    def test_07_runtime_loads_three_zones(self):
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
        self.assertEqual(r['zones'], [dict(id=z, grapplable=False, points=4) for z in ('NG1', 'NGM', 'NGU')])
        for z in ('NG1', 'NGM', 'NGU'):
            self.assertNotIn(z, r['elements'] + r['grapplable'] + r['drag'])
        OUT['runtime.json'] = dict(method='production fixedlevel.js validateFixedLevel/loadFixedLevel in booted Chromium',
                                   zones=r['zones'], elements=len(r['elements']), pageErrors=errors)


def tearDownModule():
    if not EVIDENCE:
        return
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    srcs = {p: sha(ROOT / p) for p in ('tools/retune_extended_level.py', 'tools/convert_extended_mountain_svg.py',
                                       'tools/import_level_svg.py', 'tools/check_level_geometry.py',
                                       'tools/test_upper_purple_route.py', 'fixedlevel.js')}
    cand = candidate_dir()
    for name, body in OUT.items():
        if body:
            Path(EVIDENCE, name).write_text(json.dumps(dict(candidate=str(cand), candidateSha256={n: sha(cand / n) for n in NAMES},
                                                            sources=srcs, **body), indent=1) + '\n')


if __name__ == '__main__':
    unittest.main()
