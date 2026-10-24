"""Purple no-grapple route extension (TASK-675).

After the first right -> up -> left sequence the route continues leftward from
its arrival (original P4) to an approach ledge, through one 5400 x 2700 purple
zone on rope-free bounces off varied internal surfaces, and out to an exit
ledge that copies the original departure, so the upward turn and every later
panel keep their geometry (translated). Encounters are found by semantic id
through the generated route map, never by numeric index.

Candidate selection (recorded in route.json): PURPLE_ROUTE_CANDIDATE=DIR, else
NO_GRAPPLE_EVIDENCE_DIR/candidate when it exists, else the shipped
artifacts/levels data. DIR holds extended-mountain.svg,
extended-mountain-measurements.json and extended-mountain.level.json.

NO_GRAPPLE_EVIDENCE_DIR=DIR writes route.json, traversal.json,
preservation.json and purple-route.png.

    NO_GRAPPLE_EVIDENCE_DIR=artifacts/TASK-675 python3 -m unittest discover -s tools -p test_purple_route.py -v
"""
from contextlib import ExitStack
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import check_level_geometry as geometry  # noqa: E402
import convert_extended_mountain_svg as conv  # noqa: E402
import retune_extended_level as retune  # noqa: E402

EVIDENCE = os.environ.get('NO_GRAPPLE_EVIDENCE_DIR')
SHIPPED = ROOT / 'artifacts' / 'levels'
SOURCE = ROOT / 'artifacts' / 'level' / 'extended-mountain-measurements.json'
INPUTS = TOOLS / 'fixtures' / 'purple-route-inputs.json'
NAMES = ('extended-mountain.svg', 'extended-mountain-measurements.json', 'extended-mountain.level.json')
# The preserved concept source, unchanged since TASK-650 (artifacts/TASK-650/hashes.json).
ORIGINAL_SOURCE = {
    'artifacts/level/extended-mountain.svg': '0606d25f6afc903f7946a6441844654fae4701128ce48b6393b61c0afaf40756',
    'artifacts/level/extended-mountain-measurements.json':
        '30bc5400d49b6e45b16a9c9d579eb622c7958ed28046d326ae799f1c924d5edc',
}
R = 540.0
INTERNAL_GAP = 270.0
CANONICAL_TRANSFER = 1080.0  # 200% R: every added outside transfer
CLEARANCE = R + geometry.PLAYER_DIAMETER  # grapple clearance for every non-transfer pair
SOURCES = ('tools/retune_extended_level.py', 'tools/convert_extended_mountain_svg.py', 'tools/import_level_svg.py',
           'tools/check_level_geometry.py', 'tools/test_purple_route.py', 'tools/opening_combination_replay.js',
           'tools/fixtures/purple-route-inputs.json', 'fixedlevel.js', 'physics.js', 'events.js', 'sprites/grapnel.js',
           'sprites/ninja.js', 'sprites/trampoline.js', 'artifacts/levels/level-guidelines.md')
OUT = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidate_dir():
    if os.environ.get('PURPLE_ROUTE_CANDIDATE'):
        return Path(os.environ['PURPLE_ROUTE_CANDIDATE']), 'PURPLE_ROUTE_CANDIDATE'
    if EVIDENCE and (Path(EVIDENCE) / 'candidate' / NAMES[0]).exists():
        return Path(EVIDENCE) / 'candidate', 'NO_GRAPPLE_EVIDENCE_DIR/candidate'
    return SHIPPED, 'shipped artifacts/levels'


CANDIDATE, SELECTED_BY = candidate_dir()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def rp(p):
    return [round(p[0], 3), round(p[1], 3)]


def write(name, body):
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / name).write_text(json.dumps(body, separators=(',', ':')) + '\n')


def provenance():
    return {'revision': git('rev-parse', 'HEAD'), 'candidate': os.path.relpath(CANDIDATE.resolve(), ROOT),
            'candidateSelectedBy': SELECTED_BY,
            'candidateHashes': {n: sha(CANDIDATE / n) for n in NAMES},
            'sourceHashes': {s: sha(ROOT / s) for s in SOURCES if (ROOT / s).exists()}}


def tearDownModule():
    for name, body in OUT.items():
        write(name, dict(provenance(), **body))


def load():
    m = json.loads((CANDIDATE / NAMES[1]).read_text())
    level = json.loads((CANDIDATE / NAMES[2]).read_text())
    return m, level


def contact_edge(fragment):
    """The collision edge under svg.contact() and its outward unit normal."""
    cx, cy = conv.contact(fragment)
    best = None
    for poly in conv.bodies(fragment):
        for a, b in zip(poly, poly[1:] + poly[:1]):
            d = geometry.point_segment((cx, cy), a, b)[0]
            if best is None or d < best[0]:
                best = (d, a, b, poly)
    d, a, b, poly = best
    ex, ey = b[0] - a[0], b[1] - a[1]
    n = math.hypot(ex, ey)
    nx, ny = ey / n, -ex / n
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if nx * (cx - mx) + ny * (cy - my) < 0:
        nx, ny = -nx, -ny
    return dict(distance=d, edge=[rp(a), rp(b)], normal=[round(nx, 6), round(ny, 6)])


class PurpleRouteGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.level = load()
        cls.fs = {f['id']: f for f in cls.m['fragments']}
        cls.order = [f['id'] for f in cls.m['fragments']]
        cls.ext = cls.m['purpleExtension']
        cls.zone = next(z for z in cls.m['noGrappleZones'] if z['id'] == cls.ext['zone'])
        cls.rows = {r['id']: r for r in cls.m['encounters']}
        cls.check = geometry.check(cls.level, (CANDIDATE / NAMES[0]).read_bytes(), cls.m)
        cls.route = {}

    def frag(self, semantic):
        return self.fs[self.m['routeMap']['addedFragments'].get(semantic) or self.m['routeMap']['fragmentIds'][semantic]]

    def test_01_candidate_regenerates_byte_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source', str(SOURCE),
                            '--output-dir', tmp], check=True, capture_output=True, cwd=TOOLS)
            subprocess.run([sys.executable, str(TOOLS / 'import_level_svg.py'), '--input', tmp + '/' + NAMES[0],
                            '--output', tmp + '/' + NAMES[2]], check=True, capture_output=True, cwd=TOOLS)
            same = {n: sha(Path(tmp) / n) == sha(CANDIDATE / n) for n in NAMES}
        self.assertEqual(same, {n: True for n in NAMES})
        self.route['regeneration'] = dict(command='retune_extended_level.py --source %s; import_level_svg.py'
                                          % SOURCE.relative_to(ROOT), byteIdentical=same)

    def test_02_zone_dimensions_and_leftward_placement(self):
        z, ext = self.zone, self.ext
        self.assertEqual((z['width'], z['height']), (5400, 2700))
        self.assertEqual(len(self.m['noGrappleZones']), 1)
        el = {e['id']: e for e in self.level['elements']}[z['id']]
        self.assertEqual((el['role'], el['grapplable']), ('no-grapple', False))
        pts = [(el['x'] + p['x'], el['y'] + p['y']) for p in el['points']]
        self.assertEqual([rp(p) for p in pts], [rp(p) for p in z['polygon']])
        self.assertTrue(geometry.is_convex(pts))
        self.assertNotIn(z['id'], [e for f in self.level['svgFormat']['fragments'] for e in f['elements']])
        arrival, approach, exit_ = self.fs[ext['arrival']], self.fs[ext['approach']], self.fs[ext['exit']]
        box = lambda f: [min(p[0] for b in conv.bodies(f) for p in b), min(p[1] for b in conv.bodies(f) for p in b),
                         max(p[0] for b in conv.bodies(f) for p in b), max(p[1] for b in conv.bodies(f) for p in b)]
        zx0, zy0, zx1, zy1 = z['x'], z['y'], z['x'] + z['width'], z['y'] + z['height']
        # Leftward: the zone lies left of the first leftward arrival and of the approach ledge.
        self.assertEqual(arrival['id'], self.m['routeMap']['fragmentIds']['P4'])
        self.assertLess(zx1, box(approach)[0])
        self.assertLess(zx1, box(arrival)[0])
        cx = lambda f: conv.contact(f)[0]
        chain = [arrival, approach] + [self.fs[i] for i in ext['internal']]
        self.assertTrue(all(cx(b) < cx(a) for a, b in zip(chain, chain[1:])), [cx(f) for f in chain])
        self.assertLess(cx(exit_), cx(approach))
        self.assertGreater(box(exit_)[0], zx0)          # the exit ledge overhangs the zone's upper-left part
        self.assertLess(box(exit_)[3], zy0)             # ... above its top edge
        # Approach and exit are outside the zone; every internal panel is completely inside.
        zpoly = z['polygon']
        for f in (arrival, approach, exit_):
            self.assertGreater(geometry.union_distance(conv.bodies(f), [zpoly])[0], 0, f['id'])
        for fid in ext['internal']:
            self.assertTrue(all(geometry.convex_contains(zpoly, p) for b in conv.bodies(self.fs[fid]) for p in b), fid)
        # Exactly the internal panels lie in the zone; nothing else touches it.
        touching = sorted(f['id'] for f in self.m['fragments']
                          if geometry.union_distance(conv.bodies(f), [zpoly])[0] <= 0)
        self.assertEqual(touching, sorted(ext['internal']))
        self.route['zone'] = dict(id=z['id'], x=z['x'], y=z['y'], width=z['width'], height=z['height'],
                                  widthOverR=z['width'] / R, heightOverR=z['height'] / R, convex=True,
                                  grapplable=False, insideFragment=False)
        self.route['placement'] = dict(
            arrival=dict(id=arrival['id'], semantic='P4', box=box(arrival)),
            approach=dict(id=approach['id'], semantic='NG-APPROACH', box=box(approach)),
            exit=dict(id=exit_['id'], semantic='NG-EXIT', box=box(exit_)),
            zoneRightOfApproachLeft=box(approach)[0] - zx1, zoneLeftOfArrival=box(arrival)[0] - zx1,
            exitAboveZoneTop=zy0 - box(exit_)[3], contactX=[round(cx(f), 3) for f in chain + [exit_]],
            internalInsideZone=ext['internal'], fragmentsTouchingZone=touching)

    def test_03_connections_gaps_containment_and_contacts(self):
        ext, fs = self.ext, self.fs
        zones = [(self.zone['id'], self.zone['polygon'])]
        chain = [ext['arrival'], ext['approach']] + ext['internal'] + [ext['exit']]
        rows = [r for r in self.m['encounters'] if r['id'] in ext['encounters']]
        self.assertEqual([(r['fromFragment'], r['toFragment']) for r in rows], list(zip(chain, chain[1:])))
        nums = [r['number'] for r in rows]
        self.assertEqual(nums, list(range(nums[0], nums[0] + len(nums))))
        # Route connection on exit: the original upward transfer now leaves the exit ledge, unchanged.
        up = self.rows['S07-03']
        self.assertEqual(up['fromFragment'], ext['exit'])
        self.assertEqual(up['number'], nums[-1] + 1)
        before = self.rows['OPEN-L2-P4']
        self.assertEqual(before['toFragment'], ext['arrival'])
        self.assertEqual(before['number'], nums[0] - 1)
        transfers = []
        for r in rows:
            a, b = fs[r['fromFragment']], fs[r['toFragment']]
            d, witness, relation, _ = geometry.union_distance(conv.bodies(a), conv.bodies(b))
            zone = geometry.containing_zone(zones, conv.bodies(a) + conv.bodies(b), witness)
            internal = r['fromFragment'] in ext['internal'] and r['toFragment'] in ext['internal']
            dep, arr = conv.contact(a), conv.contact(b)
            row = dict(id=r['id'], fromFragment=a['id'], toFragment=b['id'],
                       fromSemantic=a['semanticId'], toSemantic=b['semanticId'], gap=round(d, 6),
                       percent=round(d / R * 100, 4), witness=[rp(p) for p in witness], containingZone=zone,
                       rule='noGrappleInternal' if internal else 'canonical', departure=rp(dep), arrival=rp(arr),
                       dx=round(arr[0] - dep[0], 3), rise=round(dep[1] - arr[1], 3),
                       arrivalSurface=b.get('surface'), arrivalContactEdge=contact_edge(b))
            if internal:
                self.assertEqual(zone, self.zone['id'], r['id'])
                self.assertTrue(0 < d <= INTERNAL_GAP, (r['id'], d))
                self.assertEqual(r.get('noGrappleZone'), self.zone['id'])
            else:
                self.assertIsNone(zone, r['id'])
                self.assertGreaterEqual(d, CANONICAL_TRANSFER - .01, (r['id'], d))
            self.assertAlmostEqual(r['distance'], d, places=6)
            transfers.append(row)
        # Every other pair touching the extension keeps the grapple clearance (> 540 + diameter).
        new = set(chain[1:])
        pairs = [r for r in self.check['pairs'] if (r['a'] in new or r['b'] in new) and not r['transfer']]
        self.assertTrue(pairs)
        self.assertTrue(all(p['rule'] == 'grappleClearance' and p['clearance'] > CLEARANCE and p['pass'] for p in pairs))
        internal_nonconsecutive = [p for p in pairs if p['a'] in ext['internal'] and p['b'] in ext['internal']]
        self.assertEqual(len(internal_nonconsecutive), (len(ext['internal']) - 1) * (len(ext['internal']) - 2) // 2)
        # Several distinct contact surface orientations inside the zone.
        normals = [tuple(contact_edge(fs[i])['normal']) for i in ext['internal']]
        self.assertTrue(all(contact_edge(fs[i])['distance'] < geometry.PLAYER_DIAMETER / 2 + 1e-6 for i in ext['internal']))
        angles = sorted({round(math.degrees(math.atan2(nx, -ny)), 1) for nx, ny in normals})
        distinct = [a for i, a in enumerate(angles) if i == 0 or a - angles[i - 1] >= 10]
        self.assertGreaterEqual(len(distinct), 4, angles)
        self.assertTrue(any(ny > .95 for _, ny in normals))   # an underside (normal down)
        self.assertTrue(any(ny < -.95 for _, ny in normals))  # a flat top
        self.assertTrue(any(abs(nx) > .3 for nx, _ in normals))  # a slope
        self.route['transfers'] = transfers
        self.route['nonTransferPairsTouchingExtension'] = dict(
            count=len(pairs), minClearance=min(p['clearance'] for p in pairs), required='> %.1f' % CLEARANCE,
            internalNonConsecutive=[dict(a=p['a'], b=p['b'], clearance=p['clearance']) for p in internal_nonconsecutive])
        self.route['surfaceOrientations'] = dict(
            normals={i: list(n) for i, n in zip(ext['internal'], normals)},
            normalAnglesFromUpDeg=angles, distinctAt10Deg=len(distinct))

    def test_04_independent_checker_and_canonical_thresholds(self):
        s = self.check['summary']
        self.assertTrue(s['pass'], self.check['failureMessages'][:5])
        self.assertEqual(s['noGrappleZones'], 1)
        self.assertEqual(s['noGrappleInternalPairs'], len(self.ext['internal']) - 1)
        self.assertGreaterEqual(s['minDragSolidClearance'], 1620 - 1e-6)
        self.assertGreaterEqual(s['minYellowPairClearance'], 540 - 1e-6)
        self.assertGreaterEqual(s['minInteriorAngle'], 20)
        outside = [p for p in self.check['pairs'] if p['rule'] != 'noGrappleInternal']
        self.assertTrue(all(p['pass'] for p in outside))
        # Outside the zone, every transfer added since the opening keeps the 200% release gap.
        rows = [r for r in self.m['encounters'] if not r.get('noGrappleZone') and r.get('originalNumber') not in retune.TARGETS]
        self.assertTrue(all(r['distance'] >= CANONICAL_TRANSFER - .01 for r in rows))
        self.route['checker'] = {k: s[k] for k in ('pass', 'failures', 'transfers', 'transfersPass', 'fragmentPairs',
                                                    'pairsPass', 'noGrappleZones', 'noGrappleInternalPairs',
                                                    'minDragSolidClearance', 'minYellowPairClearance', 'dragZones',
                                                    'yellowPairs', 'minInteriorAngle', 'anglePolygons')}
        self.route['checker']['outsidePairsPass'] = len(outside)
        self.route['checker']['minOutsideTransferGap'] = min(r['distance'] for r in rows)
        OUT['route.json'] = dict(method='Offline geometry of the candidate; complete-polygon gaps via '
                                        'tools/check_level_geometry.py (union_distance, containing_zone).',
                                 **self.route)


class PurplePreservationTests(unittest.TestCase):
    """The original source, the opening and lower catch terrain, and the later route (translated)."""

    @classmethod
    def setUpClass(cls):
        cls.m, cls.level = load()
        source = json.loads(SOURCE.read_text())
        # The same generator with the purple extension switched off: the pre-ticket layout.
        saved = retune.extend_purple_route
        retune.extend_purple_route = lambda m, spec: None
        try:
            cls.base = retune.tune(source, opening=retune.OPENING, yellow_clearance=retune.YELLOW_CLEARANCE)
        finally:
            retune.extend_purple_route = saved
        cls.shipped = json.loads((SHIPPED / NAMES[1]).read_text())
        cls.out = {}

    def by_semantic(self, m):
        out = {}
        for f in m['fragments']:
            self.assertNotIn(f['semanticId'], out)
            out[f['semanticId']] = f
        return out

    def test_01_original_source_unchanged(self):
        now = {p: sha(ROOT / p) for p in ORIGINAL_SOURCE}
        self.assertEqual(now, ORIGINAL_SOURCE)
        self.assertEqual(self.m['baselineSha256'], self.shipped['baselineSha256'])
        self.out['originalSource'] = dict(expected=ORIGINAL_SOURCE, now=now, unchanged=True,
                                          baselineSha256=self.m['baselineSha256'])

    def test_02_lower_route_identical_and_later_route_translated(self):
        new, old = self.by_semantic(self.m), self.by_semantic(self.base)
        ext = self.m['purpleExtension']
        added = {self.m['fragments'][i]['semanticId'] for i, f in enumerate(self.m['fragments'])
                 if f['id'] in [ext['approach'], ext['exit']] + ext['internal']}
        self.assertEqual(set(new) - set(old), added)
        self.assertEqual(set(old) - set(new), set())
        order = [f['semanticId'] for f in self.base['fragments']]
        cut = order.index('P4')
        dx, dy = ext['upperTranslation']
        same, moved = [], []
        for k, s in enumerate(order):
            a, b = old[s], new[s]
            self.assertEqual(a['polys'], b['polys'], s)
            self.assertEqual((a['width'], a['height'], a['kind']), (b['width'], b['height'], b['kind']), s)
            if k <= cut:
                self.assertEqual((a['x'], a['y']), (b['x'], b['y']), s)
                same.append(s)
            else:
                self.assertAlmostEqual(b['x'] - a['x'], dx, places=9)
                self.assertAlmostEqual(b['y'] - a['y'], dy, places=9)
                moved.append(s)
        # Shipped lower route (v13 since TASK-677): the same coordinates as the candidate.
        shipped = self.by_semantic(self.shipped)
        lower = [s for s in order[:cut + 1]]
        for s in lower:
            self.assertEqual((shipped[s]['x'], shipped[s]['y'], shipped[s]['polys']), (new[s]['x'], new[s]['y'], new[s]['polys']), s)
        catch = ['X%d' % i for i in range(1, 11)]  # TASK-676: X1..X10
        self.assertTrue(set(catch) <= set(lower))
        # Every pre-existing transfer keeps its measured gap (the upward turn now leaves the exit copy).
        rows_old = {r['id']: r for r in self.base['encounters']}
        rows_new = {r['id']: r for r in self.m['encounters']}
        self.assertEqual(set(rows_old) - set(rows_new), set())
        gaps = {i: abs(rows_old[i]['distance'] - rows_new[i]['distance']) for i in rows_old}
        self.assertLess(max(gaps.values()), 1e-6)
        self.out['fragments'] = dict(identical=same, translated=moved, translation=[dx, dy],
                                     lowerCatch=catch, lowerMatchesShippedV12=lower,
                                     added=sorted(added), maxPreexistingTransferGapChange=max(gaps.values()))
        ext_lower = self.m['lowerCatchExtension']
        self.assertEqual(ext_lower['fragments'], [new[s]['id'] for s in catch])
        self.out['lowerCatchExtension'] = ext_lower

    def test_03_late_route_over_lower_extent(self):
        fs = self.m['fragments']
        ids = [f['id'] for f in fs]
        lower = fs[:ids.index(self.m['lowerCatchExtension']['firstUpDeparture']) + 1]
        late = fs[ids.index(self.m['purpleExtension']['exit']) + 1:]
        left = min(x for f in lower for b in conv.bodies(f) for x, _ in b)
        right = max(x for f in lower for b in conv.bodies(f) for x, _ in b)
        xs = [x for f in late for b in conv.bodies(f) for x, _ in b]
        self.assertGreaterEqual(min(xs), left)
        self.assertLessEqual(max(xs), right)
        self.out['lateExtent'] = dict(lowerRoute=[left, right], lateRoute=[min(xs), max(xs)],
                                      lateFragments=[f['id'] for f in late])

    def test_04_yellow_bands_reported(self):
        old = {b['id']: [round(v, 3) for v in (b['x'], b['y'], b['width'], b['height'])] for b in self.base['yellowBands']}
        new = {b['id']: [round(v, 3) for v in (b['x'], b['y'], b['width'], b['height'])] for b in self.m['yellowBands']}
        self.assertTrue(all(b['nearestSolidClearance'] >= 1620 - 1e-6 for b in self.m['yellowBands']))
        self.out['yellowBands'] = dict(beforeIds=sorted(old), afterIds=sorted(new),
                                       unchanged=sorted(k for k in old if new.get(k) == old[k]),
                                       changedOrNew=sorted(k for k in new if old.get(k) != new[k]),
                                       removed=sorted(set(old) - set(new)),
                                       note='Bands and guards are regenerated from the final geometry; every '
                                            'band keeps >= 1620 from green (independent checker in route.json).')
        OUT['preservation.json'] = dict(method='Candidate vs the same generator with the purple extension '
                                               'disabled (pre-ticket layout) and the shipped measurements.',
                                        **self.out)


TRAVERSE = '''o => {
    const level = o.level, ids = o.ids, frag = s => floors[0].byId.get(ids[s] + '-body0')
    const c = OPENING_REPLAY.start({level, fixture: {panel: ids[o.fixture.panel], fraction: o.fixture.fraction,
                                                      drop: o.fixture.drop}})
    const aim = a => { const p = OPENING_REPLAY.topAt(frag(a.panel), a.fraction); return [p.x, p.y + (a.dy || 0)] }
    const queue = [...o.inputs].sort((a, b) => a.tick - b.tick)
    const boundary = [], presses = []
    let inside = floors[0].playerInNoGrapple === true
    const start = {inside, ...c.state()}
    let insideTicks = 0, insideAttached = 0, insideThrown = 0, landed = null
    const exitBody = ids['NG-EXIT'] + '-body0'
    while (c.tick < o.budget) {
        while (queue.length && queue[0].tick === c.tick) {
            const ev = queue.shift()
            if (ev.type === 'down') {
                const where = floors[0].playerInNoGrapple === true
                c.press(aim(ev))
                presses.push({tick: c.tick, inside: where, stale: stalePress, thrown: grapnel.throwed})
            } else c.release()
        }
        const fresh = c.step()
        const now = floors[0].playerInNoGrapple === true
        if (now !== inside) { boundary.push({event: now ? 'enter' : 'exit', ...c.state()}); inside = now }
        if (now) { insideTicks++; if (grapnel.grappled) insideAttached++; if (grapnel.throwed) insideThrown++ }
        const land = fresh.find(k => k.id === exitBody && k.ny < -0.99)
        if (land && boundary.some(b => b.event === 'exit')) { landed = land; break }
    }
    if (c.held) c.release()
    return {start, boundary, presses, insideTicks, insideAttached, insideThrown, landed, ticks: c.tick,
            layoutId: c.log.layoutId, acquisitionRadius: c.log.acquisitionRadius, fixture: c.log.fixture,
            inputs: c.log.inputs, contacts: c.log.contacts, grapple: c.log.grapple, maxStep: c.log.maxStep,
            final: c.state()}
}'''

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

FRAME = '''([level, wx, wy, k, at]) => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    // The candidate through the production loader; the player stands on the approach ledge.
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
    return {png: canvas.toDataURL('image/png'), canvas: [canvas.width, canvas.height], drawn: NO_GRAPPLE_ZONES.drawn.slice()}
}'''


def image(data_url):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(',', 1)[1]))).convert('RGB')


def mean_red(img, box):
    px = list(img.crop([int(v) for v in box]).getdata())
    return sum(p[0] for p in px) / max(1, len(px))


class PurpleTraversalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from browser_test_support import start_browser_test, wait_for_boot_run
        cls.m, cls.level = load()
        cls.inputs = json.loads(INPUTS.read_text())
        route = cls.m['routeMap']
        cls.ids = dict(route['fragmentIds'], **route['addedFragments'])
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.page = cls.browser.new_page(viewport={'width': 1280, 'height': 720})
        cls.page.errors = []
        cls.page.on('pageerror', lambda e: cls.page.errors.append(str(e)))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.add_script_tag(path=str(TOOLS / 'opening_combination_replay.js'))
        cls.browser_version = cls.browser.version

    def replay(self):
        rec = self.inputs
        return self.page.evaluate(TRAVERSE, dict(level=self.level, ids=self.ids, fixture=rec['fixture'],
                                                 inputs=rec['inputs'], budget=rec['budget']))

    def test_01_continuous_traversal(self):
        ext = self.m['purpleExtension']
        runs = [self.replay() for _ in range(2)]
        log = runs[0]
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(self.page.errors, [])
        self.assertEqual(log['layoutId'], self.level['layoutId'])
        self.assertEqual(log['acquisitionRadius'], 540)
        # Only the fixture places the player (zero speed above the approach); then real mouse events only.
        self.assertEqual((log['fixture']['vx'], log['fixture']['vy']), (0, 0))
        self.assertEqual(log['fixture']['panel'], self.ids['NG-APPROACH'])
        self.assertTrue(all(e['type'] in ('down', 'up', 'move') for e in log['inputs']))
        self.assertLess(log['maxStep'], 200)
        self.assertFalse(log['start']['inside'])
        # One entry and one exit, in that order.
        self.assertEqual([b['event'] for b in log['boundary']], ['enter', 'exit'])
        enter, leave = log['boundary']
        body = lambda c: c['id'].split('-')[0]
        before = [c for c in log['contacts'] if c['tick'] < enter['tick']]
        within = [c for c in log['contacts'] if enter['tick'] <= c['tick'] < leave['tick']]
        after = [c for c in log['contacts'] if c['tick'] >= leave['tick']]
        self.assertTrue(before)
        self.assertEqual({body(c) for c in before}, {ext['approach']})
        # Momentum earned outside: the zero-speed fixture leaves the approach moving left.
        speed = math.hypot(enter['vx'], enter['vy'])
        self.assertLess(enter['vx'], 0)
        self.assertGreater(speed, 1.0)
        # Inside: every intended surface, in route order, and nothing else.
        seq = []
        for c in within:
            if not seq or seq[-1] != body(c):
                seq.append(body(c))
        self.assertEqual(seq[:len(ext['internal'])], ext['internal'])
        self.assertTrue(set(seq) <= set(ext['internal']), seq)
        first = {i: next(c for c in within if body(c) == i) for i in ext['internal']}
        # Exit through the top, then land on the exit ledge's top face.
        self.assertLess(leave['vy'], 0)
        self.assertIsNotNone(log['landed'])
        self.assertEqual(body(log['landed']), ext['exit'])
        self.assertLess(log['landed']['ny'], -.99)
        self.assertTrue({body(c) for c in after} <= {ext['exit']}, after)
        # No rope while the circle overlaps purple; presses made inside are blocked (stale).
        self.assertEqual((log['insideAttached'], log['insideThrown']), (0, 0))
        inside_ticks = [(b['tick']) for b in log['boundary']]
        for g in log['grapple']:
            if g['event'] == 'attach':
                self.assertFalse(enter['tick'] <= g['tick'] < leave['tick'], g)
        blocked = [p for p in log['presses'] if p['inside']]
        self.assertTrue(blocked)
        self.assertTrue(all(p['stale'] and not p['thrown'] for p in blocked))
        contacts = [dict(surface=self.m['fragments'][int(i[1:])]['surface'], fragment=i,
                         semantic=self.m['fragments'][int(i[1:])]['semanticId'], **first[i]) for i in ext['internal']]
        OUT['traversal.json'] = dict(
            method='Real index.html; tools/opening_combination_replay.js loads the candidate level through the '
                   'production importedMountainLevel() (acquisition radius 540), places the player once at zero '
                   'speed above the approach ledge, then dispatches document mousedown/mousemove/mouseup at the '
                   'recorded ticks (tools/fixtures/purple-route-inputs.json, aims resolved on semantic panels) and '
                   'calls production physics() once per tick. No position, velocity or grapple state is written '
                   'after the fixture. Membership is the production floors[0].playerInNoGrapple.',
            browser=self.browser_version, layoutId=log['layoutId'], acquisitionRadius=log['acquisitionRadius'],
            fixture=log['fixture'], inputs=log['inputs'], inputPolicy=self.inputs,
            boundary=log['boundary'], entrySpeed=speed, insideTicks=log['insideTicks'],
            insideAttachedTicks=log['insideAttached'], insideThrownTicks=log['insideThrown'],
            pressesInside=blocked, presses=log['presses'], grapple=log['grapple'],
            internalSequence=seq, intendedInternal=ext['internal'], firstInternalContacts=contacts,
            approachContacts=before, exitContacts=after, landedOnExit=log['landed'], ticks=log['ticks'],
            maxStepPerTick=log['maxStep'], secondRunIdentical=runs[0] == runs[1], allContacts=log['contacts'])

    def test_02_late_falls_land_on_lower_terrain(self):
        fs = self.m['fragments']
        ids = [f['id'] for f in fs]
        lower = set(ids[:ids.index(self.m['lowerCatchExtension']['firstUpDeparture']) + 1])
        late = fs[ids.index(self.m['purpleExtension']['exit']) + 1:]
        # The three leftmost late panels by contact point (semantic geometry, not frozen indices).
        sources = sorted(late, key=lambda f: conv.contact(f)[0])[:3]
        results = []
        for f in sources:
            r = self.page.evaluate(FALL, [self.level, f['id']])
            self.assertIn('hit', r, r)
            self.assertIn(r['hit']['id'].split('-')[0], lower, r)
            self.assertLess(r['maxStep'], 200)
            results.append(dict(r, semantic=f['semanticId'],
                                landedSemantic=next(g['semanticId'] for g in fs if g['id'] == r['hit']['id'].split('-')[0])))
        OUT['traversal.json'] = dict(OUT.get('traversal.json', {}), lateFallLandings=results)

    def test_03_svg_runtime_comparison_png(self):
        from PIL import Image, ImageDraw
        z = self.m['noGrappleZones'][0]
        ext = self.m['purpleExtension']
        pts = [p for i in [ext['arrival'], ext['approach'], ext['exit']] + ext['internal']
               for b in conv.bodies(next(f for f in self.m['fragments'] if f['id'] == i)) for p in b] + z['polygon']
        x0, y0 = min(p[0] for p in pts) - 300, min(p[1] for p in pts) - 300
        x1, y1 = max(p[0] for p in pts) + 300, max(p[1] for p in pts) + 300
        from browser_test_support import wait_for_boot_run
        shot = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        shot.errors = []
        shot.on('pageerror', lambda e: shot.errors.append(str(e)))
        shot.goto(self.url)
        wait_for_boot_run(shot)
        info = shot.evaluate('() => ({canvas: [canvas.width, canvas.height]})')
        cw, ch = info['canvas']
        k = min(cw / (x1 - x0), ch / (y1 - y0))
        wx, wy = (x0 + x1) / 2 - cw / k / 2, (y0 + y1) / 2 - ch / k / 2
        approach = next(f for f in self.m['fragments'] if f['id'] == ext['approach'])
        at = list(conv.contact(approach))
        frame = shot.evaluate(FRAME, [self.level, wx, wy, k, at])
        self.assertEqual(shot.errors, [])
        shot.close()
        self.assertIn(z['id'], frame['drawn'])
        runtime = image(frame['png'])
        svg = (CANDIDATE / NAMES[0]).read_text()
        # Front labels are sized for the full-map canvas; at this zoom they would cover the geometry.
        svg = svg.replace('<g id="annotations-front"', '<g id="annotations-front" display="none"', 1)
        head, rest = svg.split('>', 1)
        import re
        head = re.sub(r' viewBox="[^"]*"', ' viewBox="%r %r %r %r"' % (wx, wy, cw / k, ch / k), head)
        head = re.sub(r' width="[^"]*"', ' width="%d"' % cw, head, count=1)
        head = re.sub(r' height="[^"]*"', ' height="%d"' % ch, head, count=1)
        page = self.browser.new_page(viewport={'width': cw, 'height': ch})
        page.set_content('<html><body style="margin:0;background:#09141e">' + head + '>' + rest + '</body></html>')
        artwork = Image.open(io.BytesIO(page.screenshot(clip=dict(x=0, y=0, width=cw, height=ch)))).convert('RGB')
        page.close()
        to_px = lambda p: ((p[0] - wx) * k, (p[1] - wy) * k)
        # The purple tint raises red: a band inside the zone's lower part (below every
        # internal panel) against the same rows just outside its left edge.
        low = max(p[1] for i in ext['internal'] for b in conv.bodies(next(f for f in self.m['fragments'] if f['id'] == i))
                  for p in b) + 60
        inner = to_px((z['x'] + 100, low)) + to_px((z['x'] + z['width'] - 100, z['y'] + z['height'] - 60))
        outer = to_px((x0, low)) + to_px((z['x'] - 60, z['y'] + z['height'] - 60))
        shares = {name: dict(insideRed=mean_red(img, inner), outsideRed=mean_red(img, outer))
                  for name, img in (('svg', artwork), ('runtime', runtime))}
        for v in shares.values():
            v['redGain'] = v['insideRed'] - v['outsideRed']
        scale = 0.5
        a = artwork.resize((int(cw * scale), int(ch * scale)))
        b = runtime.resize((int(cw * scale), int(ch * scale)))
        sheet = Image.new('RGB', (a.width + b.width + 24, a.height + 44), (12, 12, 16))
        d = ImageDraw.Draw(sheet)
        d.text((8, 6), 'TASK-675 purple route: candidate SVG artwork (left) vs runtime draw() (right), same world box '
                       '[%.0f, %.0f, %.0f, %.0f]' % (wx, wy, wx + cw / k, wy + ch / k), fill=(235, 235, 235))
        sheet.paste(a, (8, 36))
        sheet.paste(b, (16 + a.width, 36))
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            sheet.save(Path(EVIDENCE) / 'purple-route.png')
        self.assertGreater(shares['svg']['redGain'], 8, shares)
        self.assertGreater(shares['runtime']['redGain'], 8, shares)
        OUT['traversal.json'] = dict(OUT.get('traversal.json', {}), comparison=dict(
            image='purple-route.png', worldBox=[wx, wy, wx + cw / k, wy + ch / k], scale=k,
            purpleTint=shares, svgLayersHidden=['annotations-front (labels sized for the full-map view)'], runtimeDrawnZones=frame['drawn']))


if __name__ == '__main__':
    unittest.main()
