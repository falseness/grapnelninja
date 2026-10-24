"""No-grapple (purple) zone format, loader and spacing checks (TASK-672).

    python3 -m unittest discover -s tools -p test_no_grapple_format.py -v

Set NO_GRAPPLE_EVIDENCE_DIR to also write format.json (SVG -> JSON -> runtime
acceptance, rejections, collection exclusion) and spacing.json (scoped
internal-transfer exception, unchanged outside/straddling and yellow rules).
Spacing fixtures are axis-aligned rects whose gaps are written by hand, so the
reference side of every comparison is independent of the checker.
"""
from contextlib import ExitStack
import hashlib
import importlib.util
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

from import_level_svg import Rejected, dumps, import_svg  # noqa: E402
import check_level_geometry as geometry  # noqa: E402

FIXTURES = TOOLS / 'fixtures' / 'level_svg'
EVIDENCE = os.environ.get('NO_GRAPPLE_EVIDENCE_DIR')
SHIPPED_SVG = ROOT / 'artifacts' / 'levels' / 'extended-mountain.svg'
SHIPPED_LEVEL = ROOT / 'artifacts' / 'levels' / 'extended-mountain.level.json'
SHIPPED_REFERENCE = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'
# Checker revision before TASK-672 added the no-grapple rule; the shipped level must check identically.
BASELINE_COMMIT = 'a7e528e'
RESULTS = {'format': {}, 'spacing': {}}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_evidence():
    if not EVIDENCE:
        return
    os.makedirs(EVIDENCE, exist_ok=True)
    sources = {p: sha(ROOT / p) for p in ('tools/import_level_svg.py', 'fixedlevel.js', 'tools/check_level_geometry.py',
                                          'tools/test_no_grapple_format.py', 'leveldata.js')}
    for name, body in RESULTS.items():
        with open(os.path.join(EVIDENCE, name + '.json'), 'w') as f:
            json.dump({'sources': sources, **body}, f, separators=(',', ':'), sort_keys=True)
            f.write('\n')


def tearDownModule():
    write_evidence()


# ---- runtime (production fixedlevel.js in the booted page) -----------------------------------

RUNTIME = '''data => {
    const out = {}
    try { validateFixedLevel(structuredClone(data)); out.validate = 'accept' }
    catch (e) { out.validate = 'reject'; out.error = e.message; return out }
    const world = loadFixedLevel(structuredClone(data))
    out.elements = world.elements.map(e => e.id)
    out.grapplable = world.elements.filter(e => e.grapplable).map(e => e.id)
    out.dragZones = world.dragZones.map(e => e.id)
    out.noGrappleZones = world.noGrappleZones.map(e => ({id: e.id, role: e.surfaceRole, grapplable: e.grapplable,
        points: e.getPoints().length}))
    out.byId = [...world.byId.keys()]
    out.roles = world.elements.reduce((n, e) => (n[e.surfaceRole] = (n[e.surfaceRole] || 0) + 1, n), {})
    return out
}'''


def run_runtime(levels):
    """name -> loader result for each level dict, in one booted Chromium page."""
    from browser_test_support import start_browser_test, wait_for_boot
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        wait_for_boot(page)
        out = {name: page.evaluate(RUNTIME, level) for name, level in levels.items()}
        out['shipped-bundle'] = page.evaluate('() => (' + RUNTIME + ')(window.GRAPPLE_OVER_BUNDLED_LEVEL)')
        return out, errors


def zone(**overrides):
    z = {'id': 'zone', 'x': -150, 'y': -1350, 'role': 'no-grapple', 'grapplable': False,
         'points': [{'x': 0, 'y': 0}, {'x': 1200, 'y': 0}, {'x': 1200, 'y': 600}, {'x': 0, 'y': 600}]}
    z.update(overrides)
    return z


class FormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.valid = import_svg((FIXTURES / 'valid-no-grapple.svg').read_bytes())
        cls.legacy = import_svg((FIXTURES / 'valid.svg').read_bytes())
        base = cls.legacy
        cls.bad = {
            'grapplable-true': dict(base, elements=base['elements'] + [zone(grapplable=True)]),
            'grapplable-missing': dict(base, elements=base['elements'] + [{k: v for k, v in zone().items() if k != 'grapplable'}]),
            'moving': dict(base, elements=base['elements'] + [zone()],
                           movers=[{'id': 'zone-mover', 'element': 'zone', 'axis': 'x', 'min': -150, 'max': 0,
                                    'periodMs': 2000, 'phase': 0}]),
            'concave': dict(base, elements=base['elements'] + [zone(points=[
                {'x': 0, 'y': 0}, {'x': 1200, 'y': 0}, {'x': 600, 'y': 300}, {'x': 1200, 'y': 600}, {'x': 0, 'y': 600}])]),
            'two-points': dict(base, elements=base['elements'] + [zone(points=[{'x': 0, 'y': 0}, {'x': 10, 'y': 0}])]),
            'zero-area': dict(base, elements=base['elements'] + [zone(points=[{'x': 0, 'y': 0}, {'x': 10, 'y': 0}, {'x': 20, 'y': 0}])]),
            'nonfinite': dict(base, elements=base['elements'] + [zone(x=None)]),
        }
        levels = {'valid-no-grapple': cls.valid, 'legacy-valid': cls.legacy,
                  'shipped-level-json': json.loads(SHIPPED_LEVEL.read_text()), **cls.bad}
        cls.runtime, cls.page_errors = run_runtime(levels)
        RESULTS['format']['pageErrors'] = cls.page_errors

    def test_01_svg_json_runtime_accepts_zone(self):
        zones = [e for e in self.valid['elements'] if e['role'] == 'no-grapple']
        self.assertEqual(zones, [{'id': 'no-grapple-zone', 'x': -150, 'y': -1350, 'role': 'no-grapple', 'grapplable': False,
                                  'points': [{'x': 0, 'y': 0}, {'x': 1200, 'y': 0}, {'x': 1200, 'y': 600}, {'x': 0, 'y': 600}]}])
        self.assertEqual(dumps(self.valid).encode(), (FIXTURES / 'valid-no-grapple.expected.json').read_bytes())
        r = self.runtime['valid-no-grapple']
        self.assertEqual(r['validate'], 'accept', r)
        self.assertEqual(r['noGrappleZones'], [{'id': 'no-grapple-zone', 'role': 'no-grapple', 'grapplable': False, 'points': 4}])
        self.assertEqual(self.page_errors, [])
        RESULTS['format']['accept'] = {'svg': 'tools/fixtures/level_svg/valid-no-grapple.svg',
                                       'svgSha256': sha(FIXTURES / 'valid-no-grapple.svg'),
                                       'jsonZone': zones[0], 'jsonMatchesExpectedFile': True,
                                       'runtime': {k: r[k] for k in ('validate', 'noGrappleZones')}, 'pass': True}

    def test_02_zone_excluded_from_solid_grapple_drag(self):
        r, legacy = self.runtime['valid-no-grapple'], self.runtime['legacy-valid']
        for key in ('elements', 'grapplable', 'dragZones', 'byId'):
            self.assertNotIn('no-grapple-zone', r[key], key)
            self.assertEqual(r[key], legacy[key], key)
        self.assertEqual(r['dragZones'], ['drag-brake'])
        self.assertNotIn('no-grapple', r['roles'])
        RESULTS['format']['exclusion'] = {
            'zoneInElements': 'no-grapple-zone' in r['elements'], 'zoneInGrapplable': 'no-grapple-zone' in r['grapplable'],
            'zoneInDragZones': 'no-grapple-zone' in r['dragZones'], 'zoneInById': 'no-grapple-zone' in r['byId'],
            'collectionsEqualLegacy': True, 'elements': len(r['elements']), 'dragZones': r['dragZones'],
            'noGrappleZones': [z['id'] for z in r['noGrappleZones']], 'pass': True}

    def test_03_legacy_levels_unchanged(self):
        shipped = json.loads(SHIPPED_LEVEL.read_text())
        rows = {}
        # Since TASK-677 the shipped level (v13, v14) carries one zone, NG1; the legacy fixture has none.
        for name, level in (('legacy-valid', self.legacy), ('shipped-level-json', shipped), ('shipped-bundle', None)):
            r = self.runtime[name]
            self.assertEqual(r['validate'], 'accept', r)
            expected = [] if name == 'legacy-valid' else [{'id': 'NG1', 'role': 'no-grapple', 'grapplable': False, 'points': 4}]
            self.assertEqual(r['noGrappleZones'], expected)
            self.assertNotIn('NG1', r['elements'])
            self.assertNotIn('NG1', r['dragZones'])
            rows[name] = {'validate': r['validate'], 'elements': len(r['elements']), 'dragZones': len(r['dragZones']),
                          'noGrappleZones': len(expected), 'roles': r['roles']}
        self.assertEqual(rows['legacy-valid']['elements'], 7)
        # 48 panel bodies plus R1's TASK-677 shortcut fin (a second R1 body).
        self.assertEqual((rows['shipped-bundle']['elements'], rows['shipped-bundle']['dragZones']), (49, 17))
        self.assertEqual(self.runtime['shipped-bundle'], self.runtime['shipped-level-json'])
        # Legacy imports are byte-identical to the committed expected outputs.
        for name in ('valid', 'valid-guide'):
            out = dumps(import_svg((FIXTURES / (name + '.svg')).read_bytes())).encode()
            self.assertEqual(out, (FIXTURES / (name + '.expected.json')).read_bytes(), name)
        shipped_import = dumps(import_svg(SHIPPED_SVG.read_bytes())).encode()
        self.assertEqual(shipped_import, SHIPPED_LEVEL.read_bytes())
        rows['legacyFixturesByteIdentical'] = ['valid', 'valid-guide']
        rows['shippedSvgReimportByteIdentical'] = True
        rows['pass'] = True
        RESULTS['format']['legacy'] = rows

    def test_04_runtime_rejections(self):
        expected = {'grapplable-true': 'InvalidNoGrappleZone: zone: grapplable',
                    'grapplable-missing': 'InvalidNoGrappleZone: zone: grapplable',
                    'moving': 'InvalidNoGrappleZone: zone-mover: no-grapple zones are static',
                    'concave': 'InvalidNoGrappleZone: zone: not convex',
                    'two-points': 'MalformedPolygon: zone',
                    'zero-area': 'MalformedPolygon: zone: area',
                    'nonfinite': 'NonFiniteGeometry: zone.x'}
        rows = {}
        for name, message in expected.items():
            r = self.runtime[name]
            with self.subTest(case=name):
                self.assertEqual(r, {'validate': 'reject', 'error': message})
            rows[name] = {'error': r.get('error'), 'pass': r == {'validate': 'reject', 'error': message}}
        RESULTS['format']['runtimeRejections'] = rows

    def test_05_importer_rejections(self):
        valid = (FIXTURES / 'valid-no-grapple.svg').read_text()
        attrs = 'data-role="no-grapple" data-grapplable="false"'
        cases = {
            'fixture:invalid-no-grapple-grapplable.svg': ((FIXTURES / 'invalid-no-grapple-grapplable.svg').read_text(), 'InvalidNoGrappleZone'),
            'fixture:invalid-no-grapple-concave.svg': ((FIXTURES / 'invalid-no-grapple-concave.svg').read_text(), 'InvalidNoGrappleZone'),
            'fixture:invalid-no-grapple-fragment.svg': ((FIXTURES / 'invalid-no-grapple-fragment.svg').read_text(), 'InvalidNoGrappleZone'),
            'grapplable-missing': (valid.replace(attrs, 'data-role="no-grapple"'), 'MissingMetadata'),
            'moving (data-mover)': (valid.replace(attrs, attrs + ' data-mover="x"'), 'UnknownAttribute'),
            'unit width': (valid.replace('width="1200" height="600" data-role="no-grapple"', 'width="1200px" height="600" data-role="no-grapple"'), 'MalformedNumber'),
            'nonfinite x': (valid.replace('x="-150" y="-1350"', 'x="inf" y="-1350"'), 'NonFiniteGeometry'),
            'zero height': (valid.replace('height="600" data-role="no-grapple"', 'height="0" data-role="no-grapple"'), 'MalformedPolygon'),
            'two-vertex polygon': (valid.replace('<rect id="no-grapple-zone" x="-150" y="-1350" width="1200" height="600"',
                                                 '<polygon id="no-grapple-zone" points="0,0 10,0"'), 'MalformedPolygon'),
            'transformed': (valid.replace(attrs, attrs + ' transform="translate(5 0)"'), 'TransformedGameplay'),
            'misspelled role': (valid.replace(attrs, 'data-role="nograpple" data-grapplable="false"'), 'InvalidSurfaceRole'),
        }
        rows = {}
        for name, (svg, category) in cases.items():
            with self.subTest(case=name):
                self.assertNotEqual(svg, valid)
                with self.assertRaises(Rejected) as ctx:
                    import_svg(svg.encode())
                self.assertIn(category, ctx.exception.categories, str(ctx.exception))
            rows[name] = {'expected': category, 'got': ctx.exception.categories, 'pass': category in ctx.exception.categories}
        RESULTS['format']['importerRejections'] = rows

    def test_06_cli_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, 'level.json')
            p = subprocess.run([sys.executable, str(TOOLS / 'import_level_svg.py'), '--input',
                                str(FIXTURES / 'valid-no-grapple.svg'), '--output', str(out)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(out.read_bytes(), (FIXTURES / 'valid-no-grapple.expected.json').read_bytes())
            bad = Path(tmp, 'bad.json')
            q = subprocess.run([sys.executable, str(TOOLS / 'import_level_svg.py'), '--input',
                                str(FIXTURES / 'invalid-no-grapple-grapplable.svg'), '--output', str(bad)], capture_output=True, text=True)
            self.assertEqual(q.returncode, 1)
            self.assertRegex(q.stderr, r'^ERROR InvalidNoGrappleZone: no-grapple-zone: ')
            self.assertFalse(bad.exists())
        RESULTS['format']['cli'] = {'acceptExit': p.returncode, 'acceptStdout': p.stdout.strip(), 'rejectExit': q.returncode,
                                    'rejectStderr': q.stderr.strip(), 'rejectOutputCreated': False, 'pass': True}


# ---- spacing (tools/check_level_geometry.py) --------------------------------------------------

PANEL_W, PANEL_H = 400, 60


def spacing_level(panels, transfers, zones=(), yellows=()):
    """SVG text plus hand-written reference for rect panels {id: (x, y)}, transfers [(from, to, gap)],
    zones [(id, x, y, w, h)] and yellows [(id, x, y, w, h, nearest)]."""
    geo = []
    for fid, (x, y) in panels.items():
        geo.append('<g id="%s" data-fragment="true"><rect id="%s-body" x="%s" y="%s" width="%d" height="%d" '
                   'data-role="bounce" data-grapplable="true"/></g>' % (fid, fid, x, y, PANEL_W, PANEL_H))
    for zid, x, y, w, h in zones:
        geo.append('<rect id="%s" x="%s" y="%s" width="%s" height="%s" data-role="no-grapple" data-grapplable="false"/>'
                   % (zid, x, y, w, h))
    for yid, x, y, w, h, _ in yellows:
        geo.append('<rect id="%s-drag" x="%s" y="%s" width="%s" height="%s" data-role="drag" data-grapplable="false"/>'
                   % (yid, x, y, w, h))
    route = ['<gn:section id="S" encounters="%s"/>' % ' '.join('E%d' % i for i in range(len(transfers)))]
    for i, (a, b, gap) in enumerate(transfers):
        route.append('<gn:encounter id="E%d" elements="%s-body %s-body"/>' % (i, a, b))
        route.append('<gn:transfer id="T%d" from="%s" to="%s" encounter="E%d" gap-percent="%r"/>' % (
            i, a, b, i, gap / 540 * 100))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:gn="urn:grapnelninja:level-svg:1" '
           'data-level-format="grapnelninja-level" data-level-version="1" data-layout-id="spacing" '
           'data-grapple-range="540" data-bounds="-20000 -20000 20000 20000">'
           '<g id="geometry" data-layer="geometry">%s</g><g id="markers" data-layer="markers">'
           '<circle id="spawn" data-marker="spawn" cx="0" cy="-30" r="10"/>'
           '<rect id="finish" data-marker="finish" x="0" y="-5000" width="10" height="10"/></g>'
           '<metadata id="level-route">%s</metadata></svg>') % (''.join(geo), ''.join(route))
    reference = {
        'fragments': [{'id': fid, 'x': x, 'y': y, 'polys': [[[0, 0], [PANEL_W, 0], [PANEL_W, PANEL_H], [0, PANEL_H]]]}
                      for fid, (x, y) in panels.items()],
        'encounters': [{'id': 'E%d' % i, 'fromFragment': a, 'toFragment': b, 'distance': gap, 'percent': gap / 540 * 100}
                       for i, (a, b, gap) in enumerate(transfers)],
        'yellowBands': [{'id': yid, 'x': x, 'y': y, 'width': w, 'height': h, 'nearestSolidClearance': nearest,
                         'minimumSolidClearance': 1620} for yid, x, y, w, h, nearest in yellows],
    }
    return svg, reference


def row_in_a_line(gaps):
    """Panels A, B, ... left to right at y=0 with the given edge-to-edge gaps."""
    panels, x = {}, 0
    for i in range(len(gaps) + 1):
        panels[chr(65 + i)] = (x, 0)
        if i < len(gaps):
            x += PANEL_W + gaps[i]
    names = list(panels)
    return panels, [(names[i], names[i + 1], g) for i, g in enumerate(gaps)]


def run_check(svg, reference):
    level = import_svg(svg.encode())
    return geometry.check(level, svg.encode(), reference)


class SpacingTests(unittest.TestCase):
    def record(self, name, report, expect_pass, description):
        pairs = [{k: p[k] for k in ('a', 'b', 'transfer', 'rule', 'noGrappleZone', 'clearance', 'pass')}
                 for p in report['pairs']]
        s = report['summary']
        row = {'description': description, 'expectPass': expect_pass, 'checkerPass': s['pass'], 'pairs': pairs,
               'failureMessages': report['failureMessages'], 'noGrappleInternalPairs': s['noGrappleInternalPairs'],
               'dragZones': [{k: d[k] for k in ('id', 'minSolidClearance', 'nearestSolid', 'pass')} for d in report['dragZones']],
               'yellowPairs': report['yellowPairs'], 'noGrappleZones': report['noGrappleZones'],
               'pass': s['pass'] is expect_pass}
        RESULTS['spacing'].setdefault('cases', {})[name] = row
        self.assertIs(s['pass'], expect_pass, report['failureMessages'])
        return row

    def internal(self, gaps, zone_pad=100, **kw):
        panels, transfers = row_in_a_line(gaps)
        width = len(panels) * PANEL_W + sum(gaps)
        zones = [('purple', -zone_pad, -zone_pad, width + 2 * zone_pad, PANEL_H + 2 * zone_pad)]
        return spacing_level(panels, transfers, zones, **kw)

    def test_01_internal_transfers_at_or_below_270_pass(self):
        for gaps in ([270], [120, 270, 200]):
            report = run_check(*self.internal(gaps))
            row = self.record('internal-%s' % '-'.join(map(str, gaps)), report, True,
                              'consecutive transfers with both panels inside one 5400-class convex zone')
            transfer_rows = [p for p in row['pairs'] if p['transfer']]
            self.assertTrue(all(p['rule'] == 'noGrappleInternal' and p['noGrappleZone'] == 'purple' for p in transfer_rows))
            self.assertEqual(report['summary']['noGrappleInternalPairs'], len(gaps))

    def test_02_zone_boundary_counts_as_inside(self):
        report = run_check(*self.internal([270], zone_pad=0))
        row = self.record('internal-270-zone-on-panel-edges', report, True,
                          'zone edges coincide with the panel outlines (boundary is inside)')
        self.assertEqual([p['rule'] for p in row['pairs']], ['noGrappleInternal'])

    def test_03_internal_gaps_above_270_fail(self):
        for gap in (270.5, 400, 600):
            report = run_check(*self.internal([gap]))
            row = self.record('internal-%s' % gap, report, False, 'internal transfer gap > 270 (even 600 > 561.6)')
            self.assertEqual([p['rule'] for p in row['pairs']], ['noGrappleInternal'])
            self.assertIn('internal no-grapple transfer gap', ' '.join(report['failureMessages']))

    def test_04_straddling_pair_keeps_existing_rule(self):
        panels, transfers = row_in_a_line([200])
        # Zone ends halfway across B: B is not completely inside.
        zones = [('purple', -100, -100, 400 + 200 + 200 + 100, 260)]
        report = run_check(*spacing_level(panels, transfers, zones))
        row = self.record('straddling-200', report, False, 'B straddles the zone boundary; 200 < 561.6 fails as before')
        self.assertEqual([p['rule'] for p in row['pairs']], ['grappleClearance'])
        self.assertIn('grapple shortcut', report['failureMessages'][0])

    def test_05_outside_pairs_keep_existing_rule(self):
        panels, transfers = row_in_a_line([200])
        report = run_check(*spacing_level(panels, transfers))
        self.record('outside-200', report, False, 'no zone: 200 fails the 540 + diameter rule')
        panels, transfers = row_in_a_line([600])
        report = run_check(*spacing_level(panels, transfers))
        row = self.record('outside-600', report, True, 'no zone: 600 passes as before')
        self.assertEqual([p['rule'] for p in row['pairs']], ['grappleClearance'])

    def test_06_separate_zones_do_not_combine(self):
        panels, transfers = row_in_a_line([200])
        zones = [('purple-a', -100, -100, 550, 260), ('purple-b', 550, -100, 550, 260)]
        report = run_check(*spacing_level(panels, transfers, zones))
        row = self.record('two-zones-200', report, False, 'each panel in a different zone: not one convex zone')
        self.assertEqual([p['rule'] for p in row['pairs']], ['grappleClearance'])

    def test_07_non_transfer_internal_pair_keeps_existing_rule(self):
        # A->B->C inside one zone; A/C (not a transfer) are 401 apart and keep the 540 rule.
        svg, ref = self.internal([0.5, 0.5])
        ref_panels = {'A': (0, 0), 'B': (400.5, 0), 'C': (801, 0)}
        self.assertEqual({f['id']: (f['x'], f['y']) for f in ref['fragments']}, ref_panels)
        report = run_check(svg, ref)
        row = self.record('internal-nonsuccessor-401', report, False, 'A/C share the zone but are not a transfer')
        ac = [p for p in row['pairs'] if (p['a'], p['b']) == ('A', 'C')][0]
        self.assertEqual((ac['transfer'], ac['rule'], ac['pass']), (False, 'grappleClearance', False))
        self.assertEqual(sum(p['pass'] for p in row['pairs'] if p['transfer']), 2)

    def test_08_internal_touching_panels_fail(self):
        report = run_check(*self.internal([0]))
        self.record('internal-0', report, False, 'gap 0 (touching) is not a transfer gap')

    def test_09_yellow_clearances_unchanged_and_purple_not_a_brake(self):
        panels, transfers = row_in_a_line([600])
        # Yellow 1620 below both panels; the purple zone sits 100 from the yellow and is not a solid.
        ok = run_check(*spacing_level(panels, transfers, zones=[('purple', 0, 1880, 1400, 300)],
                                      yellows=[('Y1', 0, 60 + 1620, 1400, 100, 1620)]))
        row = self.record('yellow-1620-with-purple-100', ok, True, 'yellow at 1620 from green, purple zone 100 from it')
        self.assertEqual(row['dragZones'][0]['nearestSolid'], 'A-body')
        self.assertEqual(ok['summary']['dragZones'], 1)
        self.assertEqual(ok['summary']['solidElements'], 2)
        near = run_check(*spacing_level(panels, transfers, yellows=[('Y1', 0, 60 + 1619, 1400, 100, 1619)]))
        self.record('yellow-1619', near, False, 'yellow 1619 from green fails the 1620 rule')
        pair_ok = run_check(*spacing_level(panels, transfers, yellows=[('Y1', 0, 1680, 600, 100, 1620),
                                                                        ('Y2', 1140, 1680, 260, 100, 1620)]))
        self.record('yellow-pair-540', pair_ok, True, 'yellow/yellow 540 passes')
        pair_bad = run_check(*spacing_level(panels, transfers, yellows=[('Y1', 0, 1680, 600, 100, 1620),
                                                                         ('Y2', 1139, 1680, 261, 100, 1620)]))
        self.record('yellow-pair-539', pair_bad, False, 'yellow/yellow 539 fails')
        alone = run_check(*spacing_level(panels, transfers, zones=[('purple', 0, 300, 1400, 300)]))
        row = self.record('purple-without-yellow-reference', alone, True,
                          'a purple zone 240 below green panels needs no yellow band and is not a drag zone')
        self.assertEqual(row['dragZones'], [])

    def test_10_checker_rejects_bad_zones(self):
        panels, transfers = row_in_a_line([600])
        svg, ref = spacing_level(panels, transfers, zones=[('purple', 0, 300, 1400, 300)])
        level = import_svg(svg.encode())
        level['elements'][-1]['grapplable'] = True
        report = geometry.check(level, svg.encode(), ref)
        self.record('checker-grapplable-zone', report, False, 'level JSON zone edited to grapplable')
        level = import_svg(svg.encode())
        level['elements'][-1]['points'] = [{'x': 0, 'y': 0}, {'x': 1400, 'y': 0}, {'x': 700, 'y': 150}, {'x': 1400, 'y': 300},
                                           {'x': 0, 'y': 300}]
        report = geometry.check(level, svg.encode(), ref)
        self.assertIn('purple: no-grapple zone not convex', report['failureMessages'])
        RESULTS['spacing'].setdefault('cases', {})['checker-concave-zone'] = {
            'expectPass': False, 'checkerPass': report['summary']['pass'],
            'failureMessages': [m for m in report['failureMessages'] if 'no-grapple' in m],
            'pass': report['summary']['pass'] is False}

    def test_11_shipped_level_unchanged(self):
        # The shipped level carries a zone since TASK-677, which the baseline checker cannot know.
        # The comparison runs on the same generator's zone-free layout (purple extension switched
        # off), and the shipped level's only differences are its noGrappleInternal pairs.
        import convert_extended_mountain_svg as conv
        import retune_extended_level as retune
        saved, layout = retune.extend_purple_route, conv.LAYOUT_ID
        try:
            retune.extend_purple_route = lambda m, spec: None
            reference = retune.tune(json.loads((ROOT / 'artifacts/level/extended-mountain-measurements.json').read_text()),
                                    opening=retune.OPENING, yellow_clearance=retune.YELLOW_CLEARANCE)
            conv.LAYOUT_ID = reference['layoutId']
            svg_bytes = conv.build(reference, guides=True, arrows=True).encode()
        finally:
            retune.extend_purple_route, conv.LAYOUT_ID = saved, layout
        level = import_svg(svg_bytes)
        self.assertEqual([e for e in level['elements'] if e['role'] == 'no-grapple'], [])
        new = geometry.check(level, svg_bytes, reference)
        head = subprocess.run(['git', 'show', BASELINE_COMMIT + ':tools/check_level_geometry.py'], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'check_level_geometry_head.py')
            path.write_text(head)
            spec = importlib.util.spec_from_file_location('check_level_geometry_head', path)
            old_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(old_module)
        old = old_module.check(level, svg_bytes, reference)
        self.assertTrue(new['summary']['pass'])
        self.assertEqual(new['failureMessages'], old['failureMessages'])
        strip = lambda p: {k: v for k, v in p.items() if k not in ('rule', 'noGrappleZone')}
        self.assertEqual([strip(p) for p in new['pairs']], old['pairs'])
        self.assertEqual(new['dragZones'], old['dragZones'])
        self.assertEqual(new['yellowPairs'], old['yellowPairs'])
        # TASK-678 side-length inventory keys are new too; the rule is off here, so pass is unaffected.
        added = {'noGrappleZones', 'noGrappleZonesPass', 'noGrappleInternalPairs', 'minSideLength', 'minSideEnforced',
                 'sideEdges', 'sideExemptEdges', 'sideViolations', 'minMeasuredSide'}
        self.assertEqual({k: v for k, v in new['summary'].items() if k not in added}, old['summary'])
        self.assertEqual((new['summary']['noGrappleZones'], new['summary']['noGrappleInternalPairs']), (0, 0))
        # Shipped v14: the scoped rule applies only inside NG1; every other pair keeps the 540+diameter rule.
        shipped = geometry.check(json.loads(SHIPPED_LEVEL.read_text()), SHIPPED_SVG.read_bytes(),
                                 json.loads(SHIPPED_REFERENCE.read_text()))
        self.assertTrue(shipped['summary']['pass'])
        internal = [p for p in shipped['pairs'] if p.get('rule') == 'noGrappleInternal']
        self.assertEqual(shipped['summary']['noGrappleZones'], 1)
        self.assertEqual(len(internal), shipped['summary']['noGrappleInternalPairs'])
        self.assertTrue(internal and all(p.get('noGrappleZone') == 'NG1' for p in internal))
        RESULTS['spacing']['shipped'] = {
            'comparedLevel': 'zone-free variant of the current generator (extend_purple_route off), imported from its SVG',
            'comparedLayoutId': level['layoutId'], 'comparedSvgSha256': hashlib.sha256(svg_bytes).hexdigest(),
            'shippedV13': {'level': str(SHIPPED_LEVEL.relative_to(ROOT)), 'pass': shipped['summary']['pass'],
                           'noGrappleZones': 1, 'noGrappleInternalPairs': len(internal),
                           'internalPairs': [[p.get('a'), p.get('b')] for p in internal]},
            'level': str(SHIPPED_LEVEL.relative_to(ROOT)), 'levelSha256': sha(SHIPPED_LEVEL), 'svgSha256': sha(SHIPPED_SVG),
            'referenceSha256': sha(SHIPPED_REFERENCE), 'pass': new['summary']['pass'],
            'pairs': '%d/%d' % (new['summary']['pairsPass'], new['summary']['fragmentPairs']),
            'dragZones': '%d/%d' % (new['summary']['dragZonesPass'], new['summary']['dragZones']),
            'minDragSolidClearance': new['summary']['minDragSolidClearance'],
            'minYellowPairClearance': new['summary']['minYellowPairClearance'],
            'noGrappleZones': 0, 'noGrappleInternalPairs': 0,
            'identicalToBaselineCheckerExceptAddedFields': True, 'baselineCommit': BASELINE_COMMIT,
            'headCommit': subprocess.run(
                ['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()}


if __name__ == '__main__':
    unittest.main()
