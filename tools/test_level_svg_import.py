"""Tests for tools/import_level_svg.py (level SVG format v1, docs/level-svg-format.md).

    python3 -m unittest discover -s tools -p test_level_svg_import.py -v

Set LEVEL_SVG_IMPORT_EVIDENCE_DIR to also write determinism.json and
roundtrip.json (transfer guides) there.
"""
from contextlib import ExitStack
import hashlib
import json
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

from import_level_svg import Rejected, dumps, import_svg  # noqa: E402

IMPORTER = TOOLS / 'import_level_svg.py'
FIXTURES = TOOLS / 'fixtures' / 'level_svg'
VALID = (FIXTURES / 'valid.svg').read_text()
EXTENDED = ROOT / 'artifacts' / 'level' / 'extended-mountain.import.svg'
EVIDENCE = os.environ.get('LEVEL_SVG_IMPORT_EVIDENCE_DIR')


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def edit(text, old, new, count=1):
    assert text.count(old) == count, (old, text.count(old))
    return text.replace(old, new)


def run_cli(*args):
    return subprocess.run([sys.executable, str(IMPORTER), *args], capture_output=True, text=True)


class ImportCase(unittest.TestCase):
    def assertRejects(self, svg, category, where=None):
        with self.assertRaises(Rejected) as ctx:
            import_svg(svg.encode())
        self.assertIn(category, ctx.exception.categories, str(ctx.exception))
        if where is not None:
            self.assertIn(where, [w for _, w, _ in ctx.exception.errors], str(ctx.exception))
        for line in str(ctx.exception).splitlines():
            self.assertRegex(line, r'^ERROR [A-Za-z]+: \S.*: \S')
        return ctx.exception


class FixtureTests(ImportCase):
    def test_manifest_fixtures(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text())
        self.assertEqual(len(manifest), 21)
        for entry in manifest:
            with self.subTest(fixture=entry['file']):
                data = (FIXTURES / entry['file']).read_bytes()
                if entry['expect'] == 'accept':
                    self.assertEqual(dumps(import_svg(data)).encode(), (FIXTURES / entry['expectedOutput']).read_bytes())
                else:
                    self.assertRejects(data.decode(), entry['category'])


class PositiveTests(ImportCase):
    def setUp(self):
        self.level = import_svg(VALID.encode())

    def test_key_order_and_metadata(self):
        self.assertEqual(list(self.level), ['version', 'layoutId', 'bounds', 'spawn', 'finish', 'sections',
                                            'encounters', 'elements', 'movers', 'svgFormat'])
        self.assertEqual(self.level['version'], 1)
        self.assertEqual(self.level['layoutId'], 'fixture-valid-v1')
        self.assertEqual(self.level['bounds'], {'left': -200, 'top': -1400, 'right': 1600, 'bottom': 400})
        self.assertEqual(self.level['movers'], [])

    def test_exact_roles_and_grapplable(self):
        got = {e['id']: (e['role'], e['grapplable']) for e in self.level['elements']}
        self.assertEqual(got, {
            'P0-shelf': ('solid', True), 'P0-post': ('solid', True), 'P1-ramp': ('solid', True),
            'ceiling-hold': ('solid', True), 'bounce-pad': ('bounce', True), 'hazard-spikes': ('hazard', False),
            'drag-brake': ('drag', False), 'catch-floor': ('solid', True)})
        for e in self.level['elements']:
            self.assertIs(type(e['grapplable']), bool)

    def test_stable_ids_in_document_order(self):
        doc_ids = re.findall(r'<(?:rect|polygon) id="([^"]+)"[^>]*data-role', VALID.split('data-layer="geometry"')[1])
        self.assertEqual([e['id'] for e in self.level['elements']], doc_ids)
        # Renaming nothing but geometry keeps every id.
        moved = import_svg(edit(VALID, 'x="300" y="-700"', 'x="310" y="-690"').encode())
        self.assertEqual([e['id'] for e in moved['elements']], doc_ids)

    def test_coordinates(self):
        el = {e['id']: e for e in self.level['elements']}
        self.assertEqual((el['ceiling-hold']['x'], el['ceiling-hold']['y']), (300, -700))
        self.assertEqual(el['ceiling-hold']['points'], [{'x': 0, 'y': 0}, {'x': 500, 'y': 0}, {'x': 500, 'y': 80}, {'x': 0, 'y': 80}])
        self.assertEqual((el['P1-ramp']['x'], el['P1-ramp']['y']), (724, -40))
        self.assertEqual(el['P1-ramp']['points'], [{'x': 0, 'y': 0}, {'x': 400, 'y': -40}, {'x': 400, 'y': 100}, {'x': 0, 'y': 100}])
        frac = import_svg(edit(VALID, 'points="724,-40 ', 'points="724.25,-40.5 ').encode())
        ramp = next(e for e in frac['elements'] if e['id'] == 'P1-ramp')
        self.assertEqual((ramp['x'], ramp['y'], ramp['points'][1]), (724.25, -40.5, {'x': 399.75, 'y': -39.5}))

    def test_spawn_and_finish(self):
        self.assertEqual(self.level['spawn'], {'x': 200, 'y': -20})
        self.assertEqual(self.level['finish'], {'left': 1200, 'top': -1300, 'right': 1400, 'bottom': -1200})

    def test_sections_encounters_transfers(self):
        self.assertEqual(self.level['sections'], [{'id': 'S01', 'encounters': ['E01', 'E02'], 'labelKey': 'climb.section.S01'}])
        self.assertEqual(self.level['encounters'], [{'id': 'E01', 'elements': ['P0-shelf', 'P0-post', 'P1-ramp']},
                                                    {'id': 'E02', 'elements': ['ceiling-hold', 'bounce-pad', 'hazard-spikes']}])
        self.assertEqual(self.level['svgFormat'], {
            'version': 1, 'grappleRange': 540,
            'fragments': [{'id': 'P0', 'elements': ['P0-shelf', 'P0-post']}, {'id': 'P1', 'elements': ['P1-ramp']}],
            'transfers': [{'id': 'T01', 'from': 'P0', 'to': 'P1', 'encounter': 'E01', 'gapPercent': 60}]})
        no_label = import_svg(edit(VALID, ' label-key="climb.section.S01"', '').encode())
        self.assertNotIn('labelKey', no_label['sections'][0])

    def test_drag_semantics(self):
        drag = [e for e in self.level['elements'] if e['role'] == 'drag']
        self.assertEqual([(e['id'], e['grapplable'], e['x'], e['y']) for e in drag], [('drag-brake', False, -100, 150)])
        fragment_members = {i for f in self.level['svgFormat']['fragments'] for i in f['elements']}
        self.assertNotIn('drag-brake', fragment_members)
        self.assertRejects(edit(VALID, 'data-role="drag" data-grapplable="false"', 'data-role="drag" data-grapplable="true"'),
                           'InvalidDragZone', 'drag-brake')
        inside = edit(VALID, '      <rect id="P0-shelf"', '      <rect id="frag-drag" x="0" y="100" width="10" height="10" '
                      'data-role="drag" data-grapplable="false"/>\n      <rect id="P0-shelf"')
        self.assertRejects(inside, 'InvalidDragZone', 'frag-drag')

    def test_no_grapple_semantics(self):
        level = import_svg((FIXTURES / 'valid-no-grapple.svg').read_bytes())
        zones = [e for e in level['elements'] if e['role'] == 'no-grapple']
        self.assertEqual([(e['id'], e['grapplable'], e['x'], e['y']) for e in zones], [('no-grapple-zone', False, -150, -1350)])
        self.assertEqual([e for e in level['elements'] if e['role'] != 'no-grapple'], self.level['elements'])
        self.assertNotIn('no-grapple-zone', {m for f in level['svgFormat']['fragments'] for m in f['elements']})
        valid = (FIXTURES / 'valid-no-grapple.svg').read_text()
        self.assertRejects(edit(valid, 'data-role="no-grapple" data-grapplable="false"', 'data-role="no-grapple" data-grapplable="true"'),
                           'InvalidNoGrappleZone', 'no-grapple-zone')
        concave = edit(valid, '<rect id="no-grapple-zone" x="-150" y="-1350" width="1200" height="600"',
                       '<polygon id="no-grapple-zone" points="-150,-1350 1050,-1350 450,-1050 1050,-750 -150,-750"')
        self.assertRejects(concave, 'InvalidNoGrappleZone', 'no-grapple-zone')
        inside = edit(VALID, '      <rect id="P0-shelf"', '      <rect id="frag-zone" x="0" y="-400" width="10" height="10" '
                      'data-role="no-grapple" data-grapplable="false"/>\n      <rect id="P0-shelf"')
        self.assertRejects(inside, 'InvalidNoGrappleZone', 'frag-zone')

    def test_annotations_ignored(self):
        ids = {e['id'] for e in self.level['elements']}
        self.assertNotIn('annotation-decoy', ids)
        self.assertNotIn('60%', json.dumps(self.level))

    def test_extended_level_matches_svg(self):
        text = EXTENDED.read_text()
        level = import_svg(text.encode())
        geometry = text.split('data-layer="geometry"', 1)[1].split('</g>\n<g id="markers"', 1)[0]
        shapes = re.findall(r'<(rect|polygon) id="([^"]+)"([^>]*)>', geometry)
        self.assertEqual(len(shapes), 41)
        self.assertEqual([e['id'] for e in level['elements']], [i for _, i, _ in shapes])
        for (kind, i, attrs), e in zip(shapes, level['elements']):
            a = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
            self.assertEqual((e['role'], e['grapplable']), (a['data-role'], a['data-grapplable'] == 'true'), i)
            if kind == 'rect':
                x, y, w, h = (float(a[k]) for k in ('x', 'y', 'width', 'height'))
                absolute = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            else:
                v = [float(t) for t in re.split(r'[ ,]', a['points'])]
                absolute = list(zip(v[::2], v[1::2]))
            got = [(e['x'] + p['x'], e['y'] + p['y']) for p in e['points']]
            for (gx, gy), (ax, ay) in zip(got, absolute):
                self.assertAlmostEqual(gx, ax, delta=1e-9, msg=i)
                self.assertAlmostEqual(gy, ay, delta=1e-9, msg=i)
        roles = {}
        for e in level['elements']:
            roles[e['role']] = roles.get(e['role'], 0) + 1
        self.assertEqual(roles, {'drag': 6, 'solid': 31, 'bounce': 4})
        self.assertTrue(all(not e['grapplable'] for e in level['elements'] if e['role'] == 'drag'))
        self.assertEqual(level['spawn'], {'x': 500, 'y': -30})
        self.assertEqual(level['bounds'], {'left': -5393, 'top': -33632, 'right': 8961, 'bottom': 1180})
        self.assertEqual([f['id'] for f in level['svgFormat']['fragments']], ['P%d' % i for i in range(25)])
        self.assertEqual(len(level['svgFormat']['transfers']), 24)
        self.assertEqual(len(level['encounters']), 24)
        self.assertEqual([s['id'] for s in level['sections']],
                         re.findall(r'<gn:section id="([^"]+)"', text))
        meta = re.findall(r'<gn:transfer id="([^"]+)" from="([^"]+)" to="([^"]+)" encounter="([^"]+)" gap-percent="([^"]+)"', text)
        self.assertEqual([(t['id'], t['from'], t['to'], t['encounter'], float(t['gapPercent'])) for t in level['svgFormat']['transfers']],
                         [(a, b, c, d, float(g)) for a, b, c, d, g in meta])
        listed = {e for s in level['sections'] for e in s['encounters']}
        self.assertEqual(listed, {e['id'] for e in level['encounters']})


class NegativeTests(ImportCase):
    def test_unsupported_version(self):
        self.assertRejects(edit(VALID, 'data-level-version="1"', 'data-level-version="2"'), 'UnsupportedVersion')
        self.assertRejects(edit(VALID, 'data-level-version="1"', 'data-level-version="1.0"'), 'UnsupportedVersion')
        self.assertRejects(edit(VALID, ' data-level-version="1"', ''), 'MissingMetadata')

    def test_unsupported_format_and_root(self):
        self.assertRejects(edit(VALID, 'data-level-format="grapnelninja-level"', 'data-level-format="other"'), 'UnsupportedFormat')
        self.assertRejects('<level xmlns="urn:x"/>', 'UnsupportedFormat')
        self.assertRejects(VALID[:-20], 'MalformedXml')
        self.assertRejects(edit(VALID, 'data-grapple-range="540"', 'data-grapple-range="400"'), 'UnsupportedGrappleRange')
        self.assertRejects(edit(VALID, ' data-layout-id="fixture-valid-v1"', ''), 'MissingMetadata')

    def test_transform_on_gameplay(self):
        self.assertRejects(edit(VALID, '<rect id="ceiling-hold" ', '<rect id="ceiling-hold" transform="translate(5 0)" '),
                           'TransformedGameplay', 'ceiling-hold')
        self.assertRejects(edit(VALID, '<polygon id="P1-ramp" ', '<polygon id="P1-ramp" style="transform: rotate(3deg)" '),
                           'TransformedGameplay', 'P1-ramp')
        self.assertRejects(edit(VALID, '<rect id="hazard-spikes" ', '<rect id="hazard-spikes" style="fill:red;translate:4px 0" '),
                           'TransformedGameplay', 'hazard-spikes')
        self.assertRejects(edit(VALID, '<circle id="spawn" ', '<circle id="spawn" transform="scale(2)" '), 'TransformedGameplay', 'spawn')

    def test_transform_on_ancestor(self):
        self.assertRejects(edit(VALID, '<g id="P0" data-fragment="true">', '<g id="P0" data-fragment="true" transform="translate(1 1)">'),
                           'TransformedGameplay', 'P0')
        self.assertRejects(edit(VALID, '<g id="geometry" data-layer="geometry">', '<g id="geometry" data-layer="geometry" transform="scale(2)">'),
                           'TransformedGameplay', 'geometry')
        self.assertRejects(edit(VALID, '<g id="markers" data-layer="markers">', '<g id="markers" data-layer="markers" style="transform:scale(2)">'),
                           'TransformedGameplay', 'markers')
        self.assertRejects(edit(VALID, ' width="900" height="900">', ' width="900" height="900" transform="rotate(90)">'),
                           'TransformedGameplay', 'svg')

    def test_transformed_annotation_is_allowed(self):
        self.assertIn('transform="translate(562 -60) scale(2)"', VALID)
        import_svg(VALID.encode())

    def test_duplicate_ids(self):
        self.assertRejects(edit(VALID, 'id="drag-brake"', 'id="catch-floor"'), 'DuplicateId', 'catch-floor')
        self.assertRejects(edit(VALID, 'id="route-curve"', 'id="P1-ramp"'), 'DuplicateId', 'P1-ramp')
        self.assertRejects(edit(VALID, '<gn:encounter id="E02"', '<gn:encounter id="E01"'), 'DuplicateId', 'E01')
        self.assertRejects(edit(VALID, '<g id="P1" data-fragment', '<g id="P0" data-fragment'), 'DuplicateId', 'P0')

    def test_invalid_ids(self):
        self.assertRejects(edit(VALID, 'id="bounce-pad"', 'id="9pad"'), 'InvalidId')
        self.assertRejects(edit(VALID, '<rect id="ceiling-hold" ', '<rect '), 'InvalidId')
        self.assertRejects(edit(VALID, '<g id="P1" data-fragment="true">', '<g data-fragment="true">'), 'InvalidId')

    def test_invalid_and_missing_references(self):
        self.assertRejects(edit(VALID, 'elements="ceiling-hold bounce-pad hazard-spikes"', 'elements="ceiling-hold bounce-pad ghost"'),
                           'MissingReference', 'E02')
        self.assertRejects(edit(VALID, 'encounters="E01 E02"', 'encounters="E01 E09"'), 'MissingReference', 'S01')
        self.assertRejects(edit(VALID, 'encounters="E01 E02"', 'encounters="E01"'), 'MissingReference', 'E02')  # orphan
        self.assertRejects(edit(VALID, 'from="P0" to="P1"', 'from="P0" to="P7"'), 'MissingReference', 'T01')
        self.assertRejects(edit(VALID, 'from="P0" to="P1"', 'from="P0-shelf" to="P1"'), 'MissingReference', 'T01')
        self.assertRejects(edit(VALID, 'encounter="E01" gap', 'encounter="E05" gap'), 'MissingReference', 'T01')
        self.assertRejects(edit(VALID, 'elements="P0-shelf P0-post P1-ramp"', 'elements="P0-shelf P0 P1-ramp"'), 'MissingReference', 'E01')
        self.assertRejects(edit(VALID, 'elements="P0-shelf P0-post P1-ramp"', 'elements="P0-shelf spawn P1-ramp"'), 'MissingReference', 'E01')
        self.assertRejects(edit(VALID, 'elements="P0-shelf P0-post P1-ramp"', 'elements="P0-shelf P0-shelf P1-ramp"'), 'MissingReference', 'E01')
        self.assertRejects(edit(VALID, 'from="P0" to="P1"', 'from="P1" to="P1"'), 'InvalidTransfer', 'T01')
        self.assertRejects(edit(VALID, 'gap-percent="60"', 'gap-percent="-1"'), 'InvalidTransfer', 'T01')
        self.assertRejects(edit(VALID, 'gap-percent="60"', 'gap-percent="NaN"'), 'InvalidTransfer', 'T01')
        self.assertRejects(edit(VALID, ' gap-percent="60"', ''), 'MissingMetadata', 'T01')
        self.assertRejects(edit(VALID, '    <gn:transfer id="T01" from="P0" to="P1" encounter="E01" gap-percent="60"/>\n', ''), 'MissingMetadata')
        self.assertRejects(edit(VALID, '<gn:transfer id="T01"', '<gn:transfer id="T01" speed="3"'), 'UnknownAttribute', 'T01')
        self.assertRejects(edit(VALID, '<gn:encounter id="E01"', '<gn:jump id="J1"/><gn:encounter id="E01"'), 'UnknownAttribute', 'J1')

    def test_missing_markers(self):
        self.assertRejects((FIXTURES / 'invalid-missing-spawn.svg').read_text(), 'MissingSpawn')
        self.assertRejects(re.sub(r'\s*<rect id="finish"[^>]*/>', '', VALID), 'MissingFinish')
        self.assertRejects(edit(VALID, '<circle id="spawn" data-marker="spawn" cx="200" cy="-20" r="18" fill="#8ad3b7"/>',
                                '<circle id="spawn" data-marker="spawn" cx="200" cy="-20" r="18"/><circle id="spawn2" data-marker="spawn" cx="1" cy="1" r="18"/>'),
                           'DuplicateSpawn', 'spawn2')
        self.assertRejects(edit(VALID, 'stroke="#efd571"/>', 'stroke="#efd571"/><rect id="finish2" data-marker="finish" x="0" y="0" width="5" height="5"/>'),
                           'DuplicateFinish', 'finish2')
        self.assertRejects(edit(VALID, ' cx="200"', ''), 'MissingMetadata', 'spawn')
        self.assertRejects(edit(VALID, 'x="1200" y="-1300" width="200"', 'x="1200" y="-1300" width="0"'), 'InvalidBounds', 'finish')
        self.assertRejects(re.sub(r'\s*<g id="markers".*?</g>', '', VALID, flags=re.S), 'MissingLayer')

    def test_malformed_polygons(self):
        post = 'points="100,-150 160,-150 160,0 100,0"'
        self.assertRejects(edit(VALID, post, 'points="100,-150 160,-150"'), 'MalformedPolygon', 'P0-post')
        self.assertRejects(edit(VALID, post, 'points="100,-150 160,-150 160"'), 'MalformedPolygon', 'P0-post')
        self.assertRejects(edit(VALID, post, 'points="100,-150 160,-150 160,-150 100,0"'), 'MalformedPolygon', 'P0-post')
        self.assertRejects(edit(VALID, post, 'points="100,-150 100,0 160,-150 160,0"'), 'MalformedPolygon', 'P0-post')  # bow tie
        self.assertRejects(edit(VALID, post, 'points="0,0 10,0 20,0"'), 'MalformedPolygon', 'P0-post')  # zero area
        self.assertRejects(edit(VALID, post, 'points="100,-150 160,-150 160,0 100;0"'), 'MalformedNumber', 'P0-post')
        self.assertRejects(edit(VALID, 'width="500" height="80"', 'width="500" height="-80"'), 'MalformedPolygon', 'ceiling-hold')
        self.assertRejects(edit(VALID, 'width="500" height="80"', 'width="500px" height="80"'), 'MalformedNumber', 'ceiling-hold')
        self.assertRejects(edit(VALID, ' points="100,-150 160,-150 160,0 100,0"', ''), 'MissingMetadata', 'P0-post')

    def test_nonfinite_polygons(self):
        for bad in ('NaN', 'inf', '-Infinity', '1e999'):
            with self.subTest(value=bad):
                self.assertRejects(edit(VALID, 'points="724,-40 ', 'points="%s,-40 ' % bad), 'NonFiniteGeometry', 'P1-ramp')
        self.assertRejects(edit(VALID, 'width="500" height="80"', 'width="NaN" height="80"'), 'NonFiniteGeometry', 'ceiling-hold')
        self.assertRejects(edit(VALID, 'cy="-20"', 'cy="inf"'), 'NonFiniteGeometry', 'spawn')
        self.assertRejects(edit(VALID, 'data-bounds="-200 -1400 1600 400"', 'data-bounds="-200 -1400 1e400 400"'), 'NonFiniteGeometry')
        self.assertRejects(edit(VALID, 'data-bounds="-200 -1400 1600 400"', 'data-bounds="1600 -1400 -200 400"'), 'InvalidBounds')
        self.assertRejects(edit(VALID, 'data-bounds="-200 -1400 1600 400"', 'data-bounds="-200 -1400 1600"'), 'MalformedNumber')

    def test_unknown_gameplay_shapes(self):
        rock = '<circle id="round-rock" cx="500" cy="-200" r="40" data-role="solid" data-grapplable="true"/>'
        anchor = '    <rect id="catch-floor"'
        for shape in (rock, '<path id="p" d="M0 0L10 0L10 10Z" data-role="solid" data-grapplable="true"/>',
                      '<use id="u" href="#catch-floor"/>', '<ellipse id="el" cx="0" cy="0" rx="4" ry="4"/>',
                      '<g id="plain"><rect id="inner" x="0" y="0" width="5" height="5" data-role="solid" data-grapplable="true"/></g>',
                      '<svg id="nested"/>', '<text id="label">x</text>'):
            with self.subTest(shape=shape[:12]):
                self.assertRejects(edit(VALID, anchor, shape + '\n' + anchor), 'UnsupportedShape')
        nested = edit(VALID, '      <rect id="P0-shelf"', '      <g id="P0-inner" data-fragment="true"><rect id="deep" x="0" y="0" width="5" height="5" '
                      'data-role="solid" data-grapplable="true"/></g>\n      <rect id="P0-shelf"')
        self.assertRejects(nested, 'UnsupportedShape', 'P0-inner')
        self.assertRejects(edit(VALID, 'width="500" height="80"', 'width="500" height="80" rx="6"'), 'UnsupportedShape', 'ceiling-hold')
        self.assertRejects(edit(VALID, '<g id="P1" data-fragment="true">\n      <polygon id="P1-ramp" points="724,-40 1124,-80 1124,60 724,60" '
                                'data-role="solid" data-grapplable="true" data-name="Ramp"/>\n    </g>', '<g id="P1" data-fragment="true"></g>'),
                           'EmptyFragment', 'P1')
        self.assertRejects(edit(VALID, '<g id="markers" data-layer="markers">', '<g id="markers" data-layer="markers"><rect id="m" x="0" y="0" width="1" height="1"/>'),
                           'UnsupportedShape', 'm')
        self.assertRejects(edit(VALID, '<title>Level', '<rect id="stray" x="0" y="0" width="1" height="1"/><title>Level'), 'UnexpectedTopLevel', 'stray')
        self.assertRejects(edit(VALID, '<g id="markers" data-layer="markers">', '<g id="g2" data-layer="geometry"/><g id="markers" data-layer="markers">'),
                           'DuplicateLayer', 'g2')

    def test_unknown_roles_and_flags(self):
        bounce = 'data-role="bounce" data-grapplable="true"'
        self.assertRejects(edit(VALID, bounce, 'data-role="spring" data-grapplable="true"'), 'InvalidSurfaceRole', 'bounce-pad')
        self.assertRejects(edit(VALID, bounce, 'data-role="Solid" data-grapplable="true"'), 'InvalidSurfaceRole', 'bounce-pad')
        self.assertRejects(edit(VALID, bounce, 'data-grapplable="true"'), 'MissingMetadata', 'bounce-pad')
        self.assertRejects(edit(VALID, bounce, 'data-role="bounce" data-grapplable="yes"'), 'InvalidGrapplable', 'bounce-pad')
        self.assertRejects(edit(VALID, bounce, 'data-role="bounce"'), 'MissingMetadata', 'bounce-pad')
        self.assertRejects(edit(VALID, 'data-role="hazard" data-grapplable="false"', 'data-role="hazard" data-grapplable="true"'),
                           'InvalidGrapplable', 'hazard-spikes')
        self.assertRejects(edit(VALID, bounce, bounce + ' data-restitution="2"'), 'UnknownAttribute', 'bounce-pad')
        self.assertRejects(edit(VALID, '<g id="P0" data-fragment="true">', '<g id="P0" data-fragment="true" data-mover="x">'), 'UnknownAttribute', 'P0')

    def test_reports_every_problem(self):
        broken = edit(edit(VALID, 'data-role="bounce"', 'data-role="spring"'), 'width="500" height="80"', 'width="NaN" height="80"')
        err = self.assertRejects(broken, 'InvalidSurfaceRole')
        self.assertIn('NonFiniteGeometry', err.categories)


class DeterminismTests(ImportCase):
    def test_hashes_and_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            runs = []
            for name in ('run1.json', 'run2.json'):
                r = run_cli('--input', str(EXTENDED), '--output', str(tmp / name))
                self.assertEqual(r.returncode, 0, r.stderr)
                runs.append(sha((tmp / name).read_bytes()))
            self.assertEqual(runs[0], runs[1])
            base = import_svg(VALID.encode())
            base_hash = sha(dumps(base))
            self.assertEqual(base_hash, sha((FIXTURES / 'valid.expected.json').read_bytes()))

            moved_svg = edit(VALID, 'points="724,-40 1124,-80', 'points="724,-40 1130,-80')
            moved = import_svg(moved_svg.encode())
            ramp = lambda level: next(e for e in level['elements'] if e['id'] == 'P1-ramp')
            self.assertEqual(ramp(base)['points'][1], {'x': 400, 'y': -40})
            self.assertEqual(ramp(moved)['points'][1], {'x': 406, 'y': -40})
            others = lambda level: [e for e in level['elements'] if e['id'] != 'P1-ramp']
            self.assertEqual(others(base), others(moved))
            moved_hash = sha(dumps(moved))
            self.assertNotEqual(moved_hash, base_hash)

            ext_text = EXTENDED.read_text()
            old = re.search(r'<polygon id="P1-body1" points="([^ ]+) ', ext_text).group(1)
            x0, y0 = (float(v) for v in old.split(','))
            ext_moved = import_svg(edit(ext_text, 'points="%s ' % old, 'points="%r,%r ' % (x0 + 12.5, y0)).encode())
            ext_base = json.loads((tmp / 'run1.json').read_text())
            body = lambda level: next(e for e in level['elements'] if e['id'] == 'P1-body1')
            self.assertEqual(body(ext_moved)['x'], body(ext_base)['x'] + 12.5)
            self.assertNotEqual(sha(dumps(ext_moved)), runs[0])

            annotated_svg = edit(edit(edit(VALID, '>60%<', '>99% (edited)<'), 'translate(562 -60) scale(2)', 'translate(10 10) rotate(30)'),
                                 '<path id="route-curve" d="M300 -10', '<path id="route-curve" d="M0 0')
            annotated_svg = edit(annotated_svg, 'x="-5" y="2" width="10" height="4" data-role="solid"', 'x="-50" y="20" width="100" height="40" data-role="hazard"')
            annotated = import_svg(annotated_svg.encode())
            annotated_hash = sha(dumps(annotated))
            self.assertEqual(annotated_hash, base_hash)
            ext_annotated = edit(ext_text, 'Hold the ceiling. Drop. Bounce back up.', 'EDITED ANNOTATION')
            ext_annotated_hash = sha(dumps(import_svg(ext_annotated.encode())))
            self.assertEqual(ext_annotated_hash, runs[0])

            if EVIDENCE:
                record = {
                    'extendedInputSha256': sha(EXTENDED.read_bytes()),
                    'twoRuns': {'run1': runs[0], 'run2': runs[1], 'identical': runs[0] == runs[1]},
                    'coordinateEdit': {
                        'fixture': 'valid.svg', 'edit': 'P1-ramp vertex 1 x 1124 -> 1130',
                        'before': {'points[1]': ramp(base)['points'][1], 'sha256': base_hash},
                        'after': {'points[1]': ramp(moved)['points'][1], 'sha256': moved_hash},
                        'otherElementsUnchanged': others(base) == others(moved), 'hashChanged': moved_hash != base_hash},
                    'extendedCoordinateEdit': {'element': 'P1-body1', 'edit': 'first vertex x +12.5',
                                               'xBefore': body(ext_base)['x'], 'xAfter': body(ext_moved)['x'],
                                               'sha256After': sha(dumps(ext_moved)), 'hashChanged': sha(dumps(ext_moved)) != runs[0]},
                    'annotationEdit': {'fixture': 'valid.svg', 'edits': ['label text', 'label transform', 'route-curve path', 'annotation-decoy rect size/role'],
                                       'sha256Before': base_hash, 'sha256After': annotated_hash, 'gameplayOutputUnchanged': annotated_hash == base_hash},
                    'extendedAnnotationEdit': {'edit': 'heading text', 'sha256After': ext_annotated_hash,
                                               'gameplayOutputUnchanged': ext_annotated_hash == runs[0]},
                }
                Path(EVIDENCE, 'determinism.json').write_text(json.dumps(record, separators=(',', ':')) + '\n')


class CliTests(ImportCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_success_writes_output(self):
        out = self.dir / 'level.json'
        r = run_cli('--input', str(FIXTURES / 'valid.svg'), '--output', str(out))
        self.assertEqual((r.returncode, r.stderr), (0, ''))
        self.assertEqual(out.read_bytes(), (FIXTURES / 'valid.expected.json').read_bytes())
        self.assertEqual(len(r.stdout.splitlines()), 1)

    def test_failure_leaves_existing_output_byte_identical(self):
        out = self.dir / 'level.json'
        sentinel = b'{"pre-existing":true}\n'
        for fixture in sorted(FIXTURES.glob('invalid-*.svg')):
            with self.subTest(fixture=fixture.name):
                out.write_bytes(sentinel)
                before = os.stat(out)
                r = run_cli('--input', str(fixture), '--output', str(out))
                self.assertEqual(r.returncode, 1)
                self.assertRegex(r.stderr, r'^ERROR [A-Za-z]+: \S+: ')
                self.assertEqual(r.stdout, '')
                self.assertEqual(out.read_bytes(), sentinel)
                self.assertEqual(os.stat(out).st_ino, before.st_ino)
                self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['level.json'])

    def test_failure_does_not_create_output(self):
        out = self.dir / 'new.json'
        r = run_cli('--input', str(FIXTURES / 'invalid-missing-spawn.svg'), '--output', str(out))
        self.assertEqual(r.returncode, 1)
        self.assertFalse(out.exists())
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_usage_errors(self):
        svg = self.dir / 'level.svg'
        svg.write_text(VALID)
        self.assertEqual(run_cli('--input', str(svg)).returncode, 2)
        self.assertEqual(run_cli('--input', str(svg), '--output', str(svg)).returncode, 2)
        self.assertEqual(svg.read_text(), VALID)
        r = run_cli('--input', str(self.dir / 'missing.svg'), '--output', str(self.dir / 'o.json'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('ERROR InputError', r.stderr)


class GuideTests(ImportCase):
    """Optional gn:transfer guide (docs/level-svg-format.md §4.6): display data only."""
    GUIDE = '300 -10 500 -400 700 -400 924.5 -50'
    TRANSFER = '<gn:transfer id="T01" from="P0" to="P1" encounter="E01" gap-percent="60"/>'

    def with_guide(self, value, text=VALID):
        return edit(text, self.TRANSFER, self.TRANSFER[:-2] + ' guide="%s"/>' % value)

    @staticmethod
    def without_transfer_guides(level):
        out = json.loads(json.dumps(level))
        for t in out['svgFormat']['transfers']:
            t.pop('guide', None)
        return out

    def test_valid_guide(self):
        level = import_svg(self.with_guide(self.GUIDE).encode())
        self.assertEqual(level['svgFormat']['transfers'], [{'id': 'T01', 'from': 'P0', 'to': 'P1', 'encounter': 'E01',
                                                            'gapPercent': 60, 'guide': [[300, -10], [500, -400], [700, -400], [924.5, -50]]}])
        # Comma-free whitespace variants and exponents parse to the same world numbers.
        spaced = import_svg(self.with_guide('  3e2\t-10 500 -4E2  700 -400\n924.50 -5e1 ').encode())
        self.assertEqual(spaced, level)

    def test_legacy_transfer_without_guide(self):
        level = import_svg(VALID.encode())
        self.assertNotIn('guide', level['svgFormat']['transfers'][0])
        self.assertEqual(dumps(level).encode(), (FIXTURES / 'valid.expected.json').read_bytes())

    def test_guide_changes_nothing_else(self):
        plain_level = import_svg(VALID.encode())
        guided = import_svg(self.with_guide(self.GUIDE).encode())
        self.assertEqual(self.without_transfer_guides(guided), plain_level)
        for key in ('bounds', 'spawn', 'finish', 'elements', 'movers', 'sections', 'encounters'):
            self.assertEqual(guided[key], plain_level[key], key)
        self.assertEqual(guided['svgFormat']['fragments'], plain_level['svgFormat']['fragments'])
        # The route-curve annotation path is still not gameplay data.
        self.assertNotIn('route-curve', json.dumps(guided))
        self.assertNotIn('annotation-decoy', {e['id'] for e in guided['elements']})

    def test_malformed_guides(self):
        bad = {
            'empty': '', 'blank': '   ', 'seven': '300 -10 500 -400 700 -400 924.5',
            'nine': self.GUIDE + ' 1', 'word': '300 -10 left -400 700 -400 924.5 -50',
            'commas': '300,-10 500,-400 700,-400 924.5,-50', 'nan': '300 -10 500 nan 700 -400 924.5 -50',
            'inf': '300 -10 500 -400 inf -400 924.5 -50', 'overflow': '300 -10 500 -400 700 1e999 924.5 -50',
            'hex': '0x1 -10 500 -400 700 -400 924.5 -50', 'unit': '300px -10 500 -400 700 -400 924.5 -50',
        }
        for name, value in bad.items():
            with self.subTest(case=name):
                err = self.assertRejects(self.with_guide(value), 'InvalidTransfer', 'T01')
                self.assertTrue(any('guide=' in m for _, _, m in err.errors), str(err))

    def test_unknown_fragment_with_guide(self):
        text = edit(self.with_guide(self.GUIDE), 'from="P0"', 'from="P9"')
        self.assertRejects(text, 'MissingReference', 'T01')
        text = edit(self.with_guide(self.GUIDE), 'to="P1"', 'to="ceiling-hold"')
        self.assertRejects(text, 'MissingReference', 'T01')

    def test_guide_on_other_route_nodes_rejected(self):
        text = edit(VALID, '<gn:encounter id="E01"', '<gn:encounter guide="%s" id="E01"' % self.GUIDE)
        self.assertRejects(text, 'UnknownAttribute', 'E01')

    def test_cli_guide_failures_keep_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, 'level.json')
            sentinel = b'{"pre-existing":true}\n'
            for fixture in sorted(FIXTURES.glob('invalid-guide-*.svg')):
                with self.subTest(fixture=fixture.name):
                    out.write_bytes(sentinel)
                    r = run_cli('--input', str(fixture), '--output', str(out))
                    self.assertEqual((r.returncode, r.stdout), (1, ''))
                    self.assertIn('ERROR ', r.stderr)
                    self.assertEqual(out.read_bytes(), sentinel)
                    self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['level.json'])
            self.assertEqual(len(list(FIXTURES.glob('invalid-guide-*.svg'))), 4)

    def test_extended_roundtrip(self):
        import convert_extended_mountain_svg as conv
        meas_path = ROOT / 'artifacts' / 'level' / 'extended-mountain-measurements.json'
        meas = json.loads(meas_path.read_text())
        plain_svg, guided_svg = conv.build(meas), conv.build(meas, guides=True)
        self.assertNotIn(' guide=', plain_svg)
        self.assertEqual(guided_svg.count(' guide="'), 24)
        plain_level = import_svg(plain_svg.encode())
        runs = [dumps(import_svg(guided_svg.encode())) for _ in range(2)]
        self.assertEqual(runs[0], runs[1])
        level = json.loads(runs[0])
        fragments = {f['id'] for f in level['svgFormat']['fragments']}
        rows = {'T%02d' % r['number']: r for r in meas['encounters']}
        frags = meas['fragments']
        checks = []
        for t in level['svgFormat']['transfers']:
            r = rows[t['id']]
            expected = [list(p) for p in conv.curve(r, frags)]
            self.assertIn(t['from'], fragments)
            self.assertIn(t['to'], fragments)
            self.assertEqual((t['from'], t['to']), (r['fromFragment'], r['toFragment']))
            self.assertEqual(t['guide'], expected)
            # Endpoints are the measured departure / next-panel contacts (encounters[].flight).
            self.assertEqual([t['guide'][0], t['guide'][-1]], [list(p) for p in r['flight']])
            checks.append({'id': t['id'], 'from': t['from'], 'to': t['to'], 'guide': t['guide'],
                           'expectedFromCurve': expected, 'equal': t['guide'] == expected,
                           'flightContacts': r['flight'], 'startIsFromContact': t['guide'][0] == list(r['flight'][0]),
                           'endIsToContact': t['guide'][-1] == list(r['flight'][1])})
        self.assertEqual(len(checks), 24)
        stripped = self.without_transfer_guides(level)
        self.assertEqual(stripped, plain_level)
        same = {k: level[k] == plain_level[k] for k in ('bounds', 'spawn', 'finish', 'elements', 'movers', 'sections', 'encounters')}
        same['fragments'] = level['svgFormat']['fragments'] == plain_level['svgFormat']['fragments']
        self.assertTrue(all(same.values()), same)
        roles = sorted({(e['role'], e['grapplable']) for e in level['elements']})
        annotation_paths_in_output = [w for w in ('annotations', 'route-curve', '<path') if w in runs[0]]
        self.assertEqual(annotation_paths_in_output, [])
        small = import_svg(self.with_guide(self.GUIDE).encode())
        small_runs = [dumps(import_svg(self.with_guide(self.GUIDE).encode())) for _ in range(2)]
        if EVIDENCE:
            record = {
                'contract': 'gn:transfer guide="x0 y0 x1 y1 x2 y2 x3 y3" -> svgFormat.transfers[].guide [[x,y]x4], world units',
                'extended': {
                    'measurements': str(meas_path.relative_to(ROOT)), 'measurementsSha256': sha(meas_path.read_bytes()),
                    'guidedSvgSha256': sha(guided_svg), 'plainSvgSha256': sha(plain_svg),
                    'importRun1Sha256': sha(runs[0]), 'importRun2Sha256': sha(runs[1]), 'twoImportsByteIdentical': runs[0] == runs[1],
                    'plainImportSha256': sha(dumps(plain_level)), 'strippedGuidedEqualsPlain': stripped == plain_level,
                    'identicalWithAndWithoutGuides': same, 'roles': roles,
                    'annotationMarkersInOutput': annotation_paths_in_output,
                    'transfers': checks, 'allGuidesEqualCurve': all(c['equal'] for c in checks),
                    'allEndpointsAreContacts': all(c['startIsFromContact'] and c['endIsToContact'] for c in checks),
                    'allFromToResolve': all(c['from'] in fragments and c['to'] in fragments for c in checks),
                },
                'fixture': {
                    'input': 'tools/fixtures/level_svg/valid-guide.svg', 'guideAttribute': self.GUIDE,
                    'guide': small['svgFormat']['transfers'][0]['guide'],
                    'twoImportsByteIdentical': small_runs[0] == small_runs[1], 'importSha256': sha(small_runs[0]),
                    'strippedEqualsValidWithoutGuide': self.without_transfer_guides(small) == import_svg(VALID.encode()),
                },
            }
            path = Path(EVIDENCE, 'roundtrip.json')
            prior = json.loads(path.read_text()) if path.exists() else {}
            prior.update(record)
            path.write_text(json.dumps(prior, separators=(',', ':')) + '\n')

    def test_shipped_v6_roundtrip(self):
        """The shipped level SVG carries guides equal to the route curve() and nothing else differs from the unguided level."""
        import convert_extended_mountain_svg as conv
        svg_path = ROOT / 'artifacts' / 'levels' / 'extended-mountain.svg'
        meas_path = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'
        shipped_svg, meas = svg_path.read_text(), json.loads(meas_path.read_text())
        rows, frags = {'T%02d' % r['number']: r for r in meas['encounters']}, meas['fragments']
        # Since TASK-660 the shipped SVG carries the guides; strip them for the legacy shape.
        plain_svg = re.sub(r'(<gn:transfer id="T\d+"[^>]*?) guide="[^"]*"', r'\1', shipped_svg)
        guided_svg = re.sub(r'(<gn:transfer id="(T\d+)"[^>]*?)/>',
                            lambda m: '%s guide="%s"/>' % (m.group(1), conv.guide(rows[m.group(2)], frags)), plain_svg)
        self.assertNotIn(' guide=', plain_svg)
        self.assertEqual(guided_svg.count(' guide="'), 47)
        self.assertEqual(guided_svg, shipped_svg)
        plain_level = import_svg(plain_svg.encode())
        runs = [dumps(import_svg(guided_svg.encode())) for _ in range(2)]
        self.assertEqual(runs[0].encode(), (ROOT / 'artifacts' / 'levels' / 'extended-mountain.level.json').read_bytes())
        self.assertEqual(runs[0], runs[1])
        level = json.loads(runs[0])
        self.assertEqual(level['layoutId'], 'extended-mountain-v14')
        fragments = {f['id'] for f in level['svgFormat']['fragments']}
        checks = []
        for t in level['svgFormat']['transfers']:
            r = rows[t['id']]
            expected = [list(p) for p in conv.curve(r, frags)]
            self.assertEqual((t['from'], t['to']), (r['fromFragment'], r['toFragment']))
            self.assertIn(t['from'], fragments)
            self.assertIn(t['to'], fragments)
            self.assertEqual(t['guide'], expected)
            self.assertEqual([t['guide'][0], t['guide'][-1]], [list(p) for p in r['flight']])
            checks.append({'id': t['id'], 'from': t['from'], 'to': t['to'], 'encounter': t['encounter'], 'guide': t['guide'],
                           'equal': t['guide'] == expected, 'startIsFromContact': t['guide'][0] == list(r['flight'][0]),
                           'endIsToContact': t['guide'][-1] == list(r['flight'][1])})
        self.assertEqual(len(checks), 47)
        stripped = self.without_transfer_guides(level)
        self.assertEqual(stripped, plain_level)
        same = {k: level[k] == plain_level[k] for k in ('layoutId', 'bounds', 'spawn', 'finish', 'elements', 'movers', 'sections', 'encounters')}
        same['fragments'] = level['svgFormat']['fragments'] == plain_level['svgFormat']['fragments']
        same['grappleRange'] = level['svgFormat']['grappleRange'] == plain_level['svgFormat']['grappleRange']
        self.assertTrue(all(same.values()), same)
        annotation = [w for w in ('annotations', 'route-curve', '<path') if w in runs[0]]
        self.assertEqual(annotation, [])
        if EVIDENCE:
            path = Path(EVIDENCE, 'roundtrip.json')
            prior = json.loads(path.read_text()) if path.exists() else {}
            prior['shippedV6'] = {
                'svg': str(svg_path.relative_to(ROOT)), 'svgSha256': sha(plain_svg),
                'measurements': str(meas_path.relative_to(ROOT)), 'measurementsSha256': sha(meas_path.read_bytes()),
                'guidedSvgSha256': sha(guided_svg), 'plainImportEqualsShippedJson': True,
                'importRun1Sha256': sha(runs[0]), 'importRun2Sha256': sha(runs[1]), 'twoImportsByteIdentical': runs[0] == runs[1],
                'strippedGuidedEqualsPlain': stripped == plain_level, 'identicalWithAndWithoutGuides': same,
                'roles': sorted({(e['role'], e['grapplable']) for e in level['elements']}),
                'annotationMarkersInOutput': annotation, 'transfers': checks,
                'allGuidesEqualCurve': all(c['equal'] for c in checks),
                'allEndpointsAreContacts': all(c['startIsFromContact'] and c['endIsToContact'] for c in checks),
                'allFromToResolve': all(c['from'] in fragments and c['to'] in fragments for c in checks),
            }
            path.write_text(json.dumps(prior, separators=(',', ':')) + '\n')

    def test_mixed_guided_and_legacy_transfers(self):
        """Guides are per transfer: unguided siblings keep the legacy shape."""
        text = Path(ROOT, 'artifacts', 'levels', 'extended-mountain.svg').read_text()
        text = re.sub(r'(<gn:transfer id="T\d+"[^>]*?) guide="[^"]*"', r'\1', text)  # shipped guides (TASK-660) off
        text = edit(text, 'encounter="S06-04" gap-percent="160"/>', 'encounter="S06-04" gap-percent="160" guide="%s"/>' % self.GUIDE)
        transfers = import_svg(text.encode())['svgFormat']['transfers']
        self.assertEqual([t['id'] for t in transfers if 'guide' in t], ['T02'])
        self.assertEqual(transfers[1]['guide'], [[300, -10], [500, -400], [700, -400], [924.5, -50]])
        self.assertEqual(len(transfers), 47)


class LoaderTests(unittest.TestCase):
    """The page's own validateFixedLevel()/loadFixedLevel() accept imported levels."""
    def test_production_loader_accepts_imports(self):
        from check_level_loader import check_levels
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, svg in (('valid.json', FIXTURES / 'valid.svg'), ('extended.json', EXTENDED)):
                path = Path(tmp, name)
                path.write_text(dumps(import_svg(svg.read_bytes())))
                paths.append(str(path))
            _, results, errors = check_levels(paths)
        self.assertEqual(errors, [])
        for path, r in results:
            self.assertEqual(r['validate'], 'accept', r)
            self.assertEqual(r['world'], 'PersistentWorld')
        self.assertEqual([(r['elements'], r['dragZones']) for _, r in results], [(7, 1), (35, 6)])


if __name__ == '__main__':
    unittest.main()
