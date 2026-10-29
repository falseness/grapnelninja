"""No-rest-inside-purple rule of tools/check_level_geometry.py (TASK-694; CLI default since TASK-698).

    python3 -m unittest discover -s tools -p test_no_grapple_rest.py -v

Fixtures are single-fragment levels with one purple zone; their face slopes are
written by hand (rise/run), so the expected side of each comparison does not
come from the checker. Set NO_GRAPPLE_REST_EVIDENCE_DIR to also write
fixtures.json (per-fixture checker result and flagged faces/pockets).
"""
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

from import_level_svg import import_svg  # noqa: E402
import check_level_geometry as geometry  # noqa: E402

EVIDENCE = os.environ.get('NO_GRAPPLE_REST_EVIDENCE_DIR')
SHIPPED_SVG = ROOT / 'artifacts' / 'levels' / 'extended-mountain.svg'
SHIPPED_LEVEL = ROOT / 'artifacts' / 'levels' / 'extended-mountain.level.json'
SHIPPED_REFERENCE = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'
ZONE = ('purple', 0, 0, 3000, 1500)
RESULTS = {}

# Panel outlines (y grows down). Each top face rises 300 over a run of 600: atan(0.5) = 26.565 deg.
SLOPED = [(600, 900), (1200, 600), (1800, 900), (1800, 1200), (600, 1200)]   # ridge: faces slope away
FLAT = [(600, 900), (1800, 900), (1800, 1200), (600, 1200)]                  # 0 deg top
POCKET = [(600, 600), (1200, 900), (1800, 600), (1800, 1200), (600, 1200)]   # V: both faces slope toward (1200, 900)
SLOPE = math.degrees(math.atan2(300, 600))


def tearDownModule():
    if EVIDENCE:
        os.makedirs(EVIDENCE, exist_ok=True)
        with open(os.path.join(EVIDENCE, 'fixtures.json'), 'w') as f:
            json.dump(RESULTS, f, separators=(',', ':'), sort_keys=True)
            f.write('\n')


# Start panel left of the zone. Every fixture panel has a vertical left edge spanning y 900..1200, so the
# A -> START transfer gap is min x(A) - (-1600), written by hand below.
START = [(-2000, 900), (-1600, 900), (-1600, 1200), (-2000, 1200)]


def level(panels, zones=(ZONE,)):
    """SVG text and hand-written reference for one-body fragments {id: absolute polygon} (plus START) and zones."""
    panels = {'START': START, **panels}
    gap = min(x for x, _ in panels['A']) + 1600
    geo = ['<g id="%s" data-fragment="true"><polygon id="%s-body" points="%s" data-role="bounce" '
           'data-grapplable="true"/></g>' % (fid, fid, ' '.join('%r,%r' % p for p in poly))
           for fid, poly in panels.items()]
    geo += ['<rect id="%s" x="%s" y="%s" width="%s" height="%s" data-role="no-grapple" data-grapplable="false"/>' % z
            for z in zones]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:gn="urn:grapnelninja:level-svg:1" '
           'data-level-format="grapnelninja-level" data-level-version="1" data-layout-id="rest" '
           'data-grapple-range="540" data-bounds="-20000 -20000 20000 20000">'
           '<g id="geometry" data-layer="geometry">%s</g><g id="markers" data-layer="markers">'
           '<circle id="spawn" data-marker="spawn" cx="0" cy="-30" r="10"/>'
           '<rect id="finish" data-marker="finish" x="0" y="-5000" width="10" height="10"/></g>'
           '<metadata id="level-route"><gn:section id="S" encounters="E0"/>'
           '<gn:encounter id="E0" elements="START-body A-body"/>'
           '<gn:transfer id="T0" from="START" to="A" encounter="E0" gap-percent="%r"/></metadata></svg>') % (
               ''.join(geo), gap / 540 * 100)
    reference = {'fragments': [{'id': fid, 'x': 0, 'y': 0, 'polys': [[list(p) for p in poly]]}
                               for fid, poly in panels.items()],
                 'encounters': [{'id': 'E0', 'fromFragment': 'START', 'toFragment': 'A', 'distance': gap,
                                 'percent': gap / 540 * 100}], 'yellowBands': []}
    return svg.encode(), reference


def run(name, panels, rule=True, zones=(ZONE,)):
    svg, reference = level(panels, zones)
    report = geometry.check(import_svg(svg), svg, reference, no_grapple_rest=rule)
    rest = report.get('noGrappleRest')
    RESULTS[name] = {'rule': rule, 'pass': report['summary']['pass'], 'failureMessages': report['failureMessages'],
                     'faces': rest and [{k: f[k] for k in ('element', 'edge', 'angle', 'zone', 'pass')}
                                        for f in rest['faces']],
                     'pockets': rest and rest['pockets']}
    return report


def bad(report):
    rest = report['noGrappleRest']
    return [(f['element'], f['edge'], f['angle']) for f in rest['faces'] if not f['pass']], rest['pockets']


class RestRuleTests(unittest.TestCase):
    def test_01_sloped_fixture_passes(self):
        report = run('sloped', {'A': SLOPED})
        self.assertTrue(report['summary']['pass'], report['failureMessages'])
        faces = report['noGrappleRest']['faces']
        self.assertEqual([(f['edge'], f['zone']) for f in faces], [(0, 'purple'), (1, 'purple')])
        for f in faces:
            self.assertAlmostEqual(f['angle'], SLOPE, places=5)
        self.assertEqual(report['noGrappleRest']['pockets'], [])
        self.assertEqual(report['summary']['noGrappleRestFaceViolations'], 0)

    def test_02_flat_fixture_fails(self):
        report = run('flat', {'A': FLAT})
        self.assertFalse(report['summary']['pass'])
        faces, pockets = bad(report)
        self.assertEqual(faces, [('A-body', 0, 0.0)])
        self.assertEqual(pockets, [])
        self.assertIn('A-body edge 0', report['failureMessages'][0])
        self.assertIn('purple', report['failureMessages'][0])

    def test_03_pocket_fixture_fails(self):
        for name, poly in (('pocket', POCKET), ('pocket-reversed', POCKET[::-1])):
            with self.subTest(name):
                report = run(name, {'A': poly})
                self.assertFalse(report['summary']['pass'])
                faces, pockets = bad(report)
                self.assertEqual(faces, [], 'both faces are 26.6 deg; only the pocket fails')
                self.assertEqual(len(pockets), 1)
                self.assertEqual(pockets[0]['vertex'], [1200, 900])
                self.assertEqual(pockets[0]['zones'], ['purple'])
                self.assertEqual({pockets[0]['left']['element'], pockets[0]['right']['element']}, {'A-body'})
                self.assertEqual(report['summary']['noGrappleRestPockets'], 1)

    def test_04_rule_is_opt_in(self):
        for name, poly in (('flat', FLAT), ('pocket', POCKET)):
            report = run(name + '-default', {'A': poly}, rule=False)
            self.assertTrue(report['summary']['pass'], report['failureMessages'])
            self.assertNotIn('noGrappleRest', report)
            self.assertNotIn('noGrappleRestFaces', report['summary'])

    def test_05_threshold_and_scope(self):
        # 15 deg exactly passes, 14.9 fails (run 1000, rise from tan).
        for angle, ok in ((15.0, True), (14.9, False)):
            rise = 1000 * math.tan(math.radians(angle))
            poly = [(600, 900), (1600, 900 - rise), (1600, 1200), (600, 1200)]
            report = run('angle-%g' % angle, {'A': poly})
            self.assertIs(report['summary']['pass'], ok, report['failureMessages'])
        # A flat panel completely outside the zone, and the zone-free case, are not checked.
        report = run('flat-outside', {'A': SLOPED, 'B': [(p[0] + 5000, p[1]) for p in FLAT]})
        self.assertTrue(report['summary']['pass'], report['failureMessages'])
        self.assertEqual({f['element'] for f in report['noGrappleRest']['faces']}, {'A-body'})
        # A flat face that only partly overlaps the zone (x 2600..3800 vs zone 0..3000) is still checked.
        report = run('flat-straddling', {'A': [(p[0] + 2000, p[1]) for p in FLAT]})
        self.assertEqual(bad(report)[0], [('A-body', 0, 0.0)])

    def test_06_shipped_cli(self):
        # TASK-698: the rule is the CLI default for the full check. Shipped v17 passes it; the previous shipped v16
        # (retune --no-purple-rest) fails on the rest rule only; --allow-grapple-rest drops the report key.
        with tempfile.TemporaryDirectory() as tmp:
            v16 = Path(tmp) / 'v16'
            subprocess.run([sys.executable, str(TOOLS / 'retune_extended_level.py'), '--source',
                            str(ROOT / 'artifacts' / 'level' / 'extended-mountain-measurements.json'),
                            '--output-dir', str(v16), '--no-purple-rest'], check=True, capture_output=True)
            subprocess.run([sys.executable, str(TOOLS / 'import_level_svg.py'), '--input', str(v16 / 'extended-mountain.svg'),
                            '--output', str(v16 / 'extended-mountain.level.json')], check=True, capture_output=True)
            levels = {'v17': (SHIPPED_SVG, SHIPPED_LEVEL, SHIPPED_REFERENCE),
                      'v16': (v16 / 'extended-mountain.svg', v16 / 'extended-mountain.level.json',
                              v16 / 'extended-mountain-measurements.json')}
            out = {}
            for layout, (svg_path, level_path, ref) in levels.items():
                for name, extra in (('rest', ['--no-grapple-rest']), ('default', []), ('allow', ['--allow-grapple-rest'])):
                    path = os.path.join(tmp, layout + name + '.json')
                    proc = subprocess.run([sys.executable, str(TOOLS / 'check_level_geometry.py'), '--svg', str(svg_path),
                                           '--level', str(level_path), '--reference', str(ref), '--report', path] + extra,
                                          capture_output=True, text=True)
                    out[layout, name] = (proc.returncode, json.loads(Path(path).read_text()))
        self.assertEqual(json.loads(SHIPPED_LEVEL.read_text())['layoutId'], 'extended-mountain-v22')
        for layout in levels:
            self.assertEqual(out[layout, 'allow'][0], 0)
            self.assertNotIn('noGrappleRest', out[layout, 'allow'][1])
            self.assertEqual(out[layout, 'default'], out[layout, 'rest'])
        code, report = out['v17', 'default']
        self.assertEqual(code, 0)
        self.assertEqual(report['summary']['noGrappleRestFaceViolations'], 0)
        self.assertEqual(report['summary']['noGrappleRestPockets'], 0)
        self.assertGreaterEqual(report['summary']['minNoGrappleRestAngle'], geometry.NO_GRAPPLE_REST_SLOPE)
        code, report = out['v16', 'default']
        self.assertEqual(code, 1)
        flagged = {f['element']: f for f in report['noGrappleRest']['faces'] if not f['pass']}
        for eid in ('P23-body0', 'P24-body0', 'P25-body0'):
            self.assertEqual(flagged[eid]['zone'], 'NG1')
        self.assertEqual(sorted(f['zone'] for f in flagged.values()), ['NG1'] * 3 + ['NGM'] * 3 + ['NGU'] * 3)
        # Only rest messages are new: every other check still passes.
        self.assertTrue(report['failureMessages'])
        self.assertTrue(all(m.endswith('(rest)') for m in report['failureMessages']))
        RESULTS['shipped'] = {'v17DefaultExit': out['v17', 'default'][0], 'v16DefaultExit': code,
                              'allowExits': [out[k, 'allow'][0] for k in levels],
                              'flagged': {k: [f['zone'], f['edge'], f['angle']] for k, f in sorted(flagged.items())}}

if __name__ == '__main__':
    unittest.main()
