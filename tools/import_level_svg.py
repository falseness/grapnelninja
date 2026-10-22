#!/usr/bin/env python3
"""Import a Grapple Over level SVG (format v1) into a fixed-level JSON object.

The contract is docs/level-svg-format.md. The output is accepted by
validateFixedLevel() in fixedlevel.js. Only the geometry layer, the markers
layer and metadata#level-route are read; annotations are skipped.

    python3 tools/import_level_svg.py --input LEVEL.svg --output LEVEL.level.json

Exit 0 on success, 1 on a rejected input (one `ERROR <Category>: <where>:
<message>` line per problem on stderr, output left untouched), 2 on usage
errors.
"""
import argparse
import json
import math
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

SVG = '{http://www.w3.org/2000/svg}'
GN = '{urn:grapnelninja:level-svg:1}'
FORMAT = 'grapnelninja-level'
GRAPPLE_RANGE = 540
ROLES = ('solid', 'bounce', 'hazard', 'drag')
NUMBER = re.compile(r'\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*$')
NON_FINITE = re.compile(r'\s*[+-]?(nan|inf|infinity)\s*$', re.IGNORECASE)
ID = re.compile(r'^[A-Za-z][A-Za-z0-9_.:-]*$')
# CSS properties that move an element (transform plus the individual transform properties)
CSS_TRANSFORMS = {'transform', '-webkit-transform', '-moz-transform', '-ms-transform', 'translate', 'rotate', 'scale'}
# Paint-only presentation attributes: they never change a shape's outline.
DISPLAY = {'class', 'fill', 'stroke', 'stroke-width', 'style', 'opacity', 'fill-opacity', 'stroke-opacity',
           'stroke-dasharray', 'stroke-dashoffset', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit'}
ELEMENT_ATTRS = {'id', 'data-role', 'data-grapplable', 'data-name'} | DISPLAY
RECT_ATTRS = ELEMENT_ATTRS | {'x', 'y', 'width', 'height', 'rx', 'ry'}
POLYGON_ATTRS = ELEMENT_ATTRS | {'points'}
FRAGMENT_ATTRS = {'id', 'data-fragment', 'data-name'} | DISPLAY
SPAWN_ATTRS = {'id', 'data-marker', 'cx', 'cy', 'r'} | DISPLAY
FINISH_ATTRS = {'id', 'data-marker', 'x', 'y', 'width', 'height'} | DISPLAY
ROUTE_ATTRS = {
    'section': ({'id', 'encounters'}, {'label-key'}),
    'encounter': ({'id', 'elements'}, set()),
    'transfer': ({'id', 'from', 'to', 'encounter', 'gap-percent'}, set()),
}
IGNORED = (SVG + 'title', SVG + 'desc')


class Rejected(Exception):
    """The input breaks the contract; errors is a list of (category, where, message)."""
    def __init__(self, errors):
        super().__init__('\n'.join(format_error(e) for e in errors))
        self.errors = errors

    @property
    def categories(self):
        return [category for category, _, _ in self.errors]


def format_error(error):
    return 'ERROR %s: %s: %s' % error


def local(tag):
    return tag.split('}', 1)[-1]


def plain(v):
    """Integral floats become ints so the JSON writes `60`, not `60.0`."""
    return int(v) if v.is_integer() else v


class Importer:
    def __init__(self, data):
        self.errors = []
        try:
            self.root = ET.fromstring(data)
        except ET.ParseError as e:
            raise Rejected([('MalformedXml', 'document', str(e))])
        self.parents = {c: p for p in self.root.iter() for c in p}

    # ---- diagnostics
    def where(self, e, use_id=True):
        if use_id and e.get('id'):
            return e.get('id')
        steps = []
        while e is not None:
            parent = self.parents.get(e)
            name = local(e.tag)
            if parent is not None:
                same = [c for c in parent if c.tag == e.tag]
                if len(same) > 1:
                    name += '[%d]' % (same.index(e) + 1)
            steps.append(name)
            e = parent
        return '/' + '/'.join(reversed(steps))

    def error(self, category, e, message):
        self.errors.append((category, e if isinstance(e, str) else self.where(e), message))
        return None

    def check(self):
        if self.errors:
            raise Rejected(self.errors)

    # ---- numbers (§2)
    def number(self, e, attr, required=True):
        raw = e.get(attr)
        if raw is None:
            return self.error('MissingMetadata', e, '%s is required' % attr) if required else None
        return self.parse_number(e, attr, raw)

    def parse_number(self, e, attr, raw):
        if NON_FINITE.match(raw):
            return self.error('NonFiniteGeometry', e, '%s=%r is not finite' % (attr, raw))
        if not NUMBER.match(raw):
            return self.error('MalformedNumber', e, '%s=%r is not a plain decimal number (no units)' % (attr, raw))
        v = float(raw)
        if not math.isfinite(v):
            return self.error('NonFiniteGeometry', e, '%s=%r overflows to a non-finite value' % (attr, raw))
        return v

    def numbers(self, e, attr, raw):
        tokens = [t for t in re.split(r'[\s,]+', raw.strip()) if t]
        values = [self.parse_number(e, attr, t) for t in tokens]
        return None if any(v is None for v in values) else values

    # ---- attribute rules shared by gameplay nodes
    def transformed(self, e):
        if e.get('transform') is not None:
            return True
        for declaration in (e.get('style') or '').split(';'):
            if declaration.split(':', 1)[0].strip().lower() in CSS_TRANSFORMS and ':' in declaration:
                return True
        return False

    def gameplay_attrs(self, e, allowed, what):
        """TransformedGameplay before UnknownAttribute: a transform is the actionable cause."""
        if self.transformed(e):
            self.error('TransformedGameplay', e, '%s must not carry a transform (gameplay uses root user space)' % what)
            return False
        extra = sorted(a for a in e.attrib if a not in allowed)
        if extra:
            self.error('UnknownAttribute', e, '%s does not allow %s' % (what, ', '.join(extra)))
            return False
        return True

    # ---- document
    def run(self):
        root = self.root
        if root.tag != SVG + 'svg':
            raise Rejected([('UnsupportedFormat', 'document', 'root element is <%s>, expected SVG <svg>' % local(root.tag))])
        if root.get('data-level-format') != FORMAT:
            raise Rejected([('UnsupportedFormat', 'svg', 'data-level-format=%r, expected %r' % (root.get('data-level-format'), FORMAT))])
        version = root.get('data-level-version')
        if version is None:
            raise Rejected([('MissingMetadata', 'svg', 'data-level-version is required')])
        if version != '1':
            raise Rejected([('UnsupportedVersion', 'svg', 'data-level-version=%r; this importer reads version "1" only' % version)])
        if self.transformed(root):
            self.error('TransformedGameplay', 'svg', 'the root <svg> is an ancestor of all gameplay and must not carry a transform')
        layout = root.get('data-layout-id')
        if layout is None:
            self.error('MissingMetadata', 'svg', 'data-layout-id is required')
        elif not ID.match(layout):
            self.error('InvalidId', 'svg', 'data-layout-id=%r does not match %s' % (layout, ID.pattern))
        raw = root.get('data-grapple-range')
        if raw is None or not NUMBER.match(raw) or float(raw) != GRAPPLE_RANGE:
            self.error('UnsupportedGrappleRange', 'svg', 'data-grapple-range=%r, v1 requires %d' % (raw, GRAPPLE_RANGE))
        bounds = self.world_bounds(root)
        self.ids()
        geometry, markers, route = self.layers()
        self.check()

        elements, fragments = self.geometry(geometry)
        spawn, finish = self.markers(markers)
        self.check()
        sections, encounters, transfers = self.route(route, elements, fragments)
        self.check()
        return {
            'version': 1,
            'layoutId': layout,
            'bounds': bounds,
            'spawn': spawn,
            'finish': finish,
            'sections': sections,
            'encounters': encounters,
            'elements': [{k: v for k, v in el.items() if k != 'fragment'} for el in elements],
            'movers': [],
            'svgFormat': {
                'version': 1,
                'grappleRange': GRAPPLE_RANGE,
                'fragments': [{'id': f, 'elements': members} for f, members in fragments.items()],
                'transfers': transfers,
            },
        }

    def world_bounds(self, root):
        raw = root.get('data-bounds')
        if raw is None:
            return self.error('MissingMetadata', 'svg', 'data-bounds="left top right bottom" is required (world bounds are never inferred)')
        values = self.numbers(root, 'data-bounds', raw)
        if values is None:
            return None
        if len(values) != 4:
            return self.error('MalformedNumber', 'svg', 'data-bounds needs 4 numbers, got %d' % len(values))
        left, top, right, bottom = values
        if not (left < right and top < bottom):
            return self.error('InvalidBounds', 'svg', 'data-bounds needs left < right and top < bottom, got %r' % raw)
        return {'left': plain(left), 'top': plain(top), 'right': plain(right), 'bottom': plain(bottom)}

    def ids(self):
        seen = set()
        for e in self.root.iter():
            i = e.get('id')
            if i is None:
                continue
            if not ID.match(i):
                self.error('InvalidId', self.where(e, use_id=False), 'id=%r does not match %s' % (i, ID.pattern))
            elif i in seen:
                self.error('DuplicateId', i, 'id is used more than once (ids are unique document-wide, annotations included)')
            seen.add(i)

    def layers(self):
        found = {'geometry': [], 'markers': [], 'level-route': []}
        for c in self.root:
            if c.tag == SVG + 'g' and c.get('data-layer') in ('geometry', 'markers'):
                found[c.get('data-layer')].append(c)
            elif c.tag == SVG + 'metadata' and c.get('id') == 'level-route':
                found['level-route'].append(c)
            elif c.tag == SVG + 'g' and c.get('data-layer') == 'annotations':
                pass
            elif c.tag in IGNORED or c.tag in (SVG + 'defs', SVG + 'style'):
                pass
            else:
                self.error('UnexpectedTopLevel', c, '<%s> is not allowed at top level; put display content in a data-layer="annotations" group' % local(c.tag))
        result = []
        for name, nodes in found.items():
            if not nodes:
                self.error('MissingLayer', 'svg', 'missing %s' % ('metadata#level-route' if name == 'level-route' else 'g[data-layer=%s]' % name))
            elif len(nodes) > 1:
                self.error('DuplicateLayer', nodes[1], 'more than one %s' % name)
            result.append(nodes[0] if nodes else None)
        for layer in result[:2]:
            if layer is not None:
                self.layer_attrs(layer)
        return result

    def layer_attrs(self, layer):
        if self.transformed(layer):
            return self.error('TransformedGameplay', layer, 'the %s layer is an ancestor of gameplay and must not carry a transform' % layer.get('data-layer'))
        extra = sorted(a for a in layer.attrib if a.startswith('data-') and a != 'data-layer' or a.startswith('{'))
        if extra:
            self.error('UnknownAttribute', layer, 'layer does not allow %s' % ', '.join(extra))

    # ---- geometry (§4.3)
    def geometry(self, layer):
        elements, fragments = [], {}
        for c in layer:
            if c.tag in IGNORED:
                continue
            if c.tag == SVG + 'g' and c.get('data-fragment') == 'true':
                self.fragment(c, elements, fragments)
            else:
                self.element(c, None, elements)
        return elements, fragments

    def fragment(self, g, elements, fragments):
        if not g.get('id'):
            return self.error('InvalidId', g, 'a fragment needs an id (transfers refer to it)')
        if not self.gameplay_attrs(g, FRAGMENT_ATTRS, 'fragment'):
            return
        members = []
        for c in g:
            if c.tag in IGNORED:
                continue
            if c.tag == SVG + 'g':
                self.error('UnsupportedShape', c, 'groups inside fragment %s are not allowed (fragments do not nest)' % g.get('id'))
                continue
            el = self.element(c, g.get('id'), elements)
            if el is not None:
                members.append(el['id'])
        if not any(c.tag not in IGNORED for c in g):
            self.error('EmptyFragment', g, 'fragment has no rect/polygon elements')
        fragments[g.get('id')] = members

    def element(self, e, fragment, elements):
        kind = e.tag[len(SVG):] if e.tag.startswith(SVG) else None
        if kind not in ('rect', 'polygon'):
            hint = ' (a plain <g> needs data-fragment="true")' if kind == 'g' else ''
            return self.error('UnsupportedShape', e, '<%s> is not a gameplay shape; use <rect> or <polygon>%s' % (local(e.tag), hint))
        if not e.get('id'):
            return self.error('InvalidId', e, 'gameplay %s needs an id' % kind)
        if not self.gameplay_attrs(e, RECT_ATTRS if kind == 'rect' else POLYGON_ATTRS, kind):
            return None
        role, grapplable = e.get('data-role'), e.get('data-grapplable')
        if role is None:
            return self.error('MissingMetadata', e, 'data-role is required (one of %s)' % ', '.join(ROLES))
        if role not in ROLES:
            return self.error('InvalidSurfaceRole', e, 'data-role=%r is not one of %s' % (role, ', '.join(ROLES)))
        if grapplable is None:
            return self.error('MissingMetadata', e, 'data-grapplable="true|false" is required')
        if grapplable not in ('true', 'false'):
            return self.error('InvalidGrapplable', e, 'data-grapplable=%r must be exactly "true" or "false"' % grapplable)
        if role == 'hazard' and grapplable == 'true':
            return self.error('InvalidGrapplable', e, 'a hazard is never hooked by the runtime; set data-grapplable="false"')
        if role == 'drag' and grapplable == 'true':
            return self.error('InvalidDragZone', e, 'a drag zone can never be grappled; set data-grapplable="false"')
        if role == 'drag' and fragment is not None:
            return self.error('InvalidDragZone', e, 'drag zones may not be inside fragment %s; move it directly into the geometry layer' % fragment)
        points = self.rect(e) if kind == 'rect' else self.polygon(e)
        if points is None:
            return None
        x, y = points[0]
        relative = [(px - x, py - y) for px, py in points]
        if not self.polygon_ok(e, relative):
            return None
        el = {'id': e.get('id'), 'x': plain(x), 'y': plain(y), 'role': role, 'grapplable': grapplable == 'true',
              'points': [{'x': plain(px), 'y': plain(py)} for px, py in relative], 'fragment': fragment}
        elements.append(el)
        return el

    def rect(self, e):
        x, y, w, h = (self.number(e, k) for k in ('x', 'y', 'width', 'height'))
        for k in ('rx', 'ry'):
            r = self.number(e, k, required=False)
            if r not in (None, 0):
                return self.error('UnsupportedShape', e, '%s must be absent or 0 (rounded rects are not gameplay shapes)' % k)
        if None in (x, y, w, h):
            return None
        if not (w > 0 and h > 0):
            return self.error('MalformedPolygon', e, 'width and height must be > 0, got %r x %r' % (w, h))
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    def polygon(self, e):
        raw = e.get('points')
        if raw is None:
            return self.error('MissingMetadata', e, 'points is required')
        v = self.numbers(e, 'points', raw)
        if v is None:
            return None
        if len(v) % 2:
            return self.error('MalformedPolygon', e, 'points has an odd count of numbers (%d)' % len(v))
        if len(v) < 6:
            return self.error('MalformedPolygon', e, 'a polygon needs at least 3 vertices, got %d' % (len(v) // 2))
        return [(v[i], v[i + 1]) for i in range(0, len(v), 2)]

    def polygon_ok(self, e, p):
        """The same structural checks as validateFixedLevel, on the same relative points."""
        def cross(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        area = 0.0
        n = len(p)
        for i in range(n):
            a, b = p[i], p[(i + 1) % n]
            if a == b:
                self.error('MalformedPolygon', e, 'repeated consecutive vertex at index %d' % ((i + 1) % n))
                return False
            area += a[0] * b[1] - b[0] * a[1]
            for j in range(i + 1, n):
                if j == i + 1 or (i == 0 and j == n - 1):
                    continue
                c, d = p[j], p[(j + 1) % n]
                if (max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]) or
                        max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1])):
                    continue
                if cross(a, b, c) * cross(a, b, d) <= 0 and cross(c, d, a) * cross(c, d, b) <= 0:
                    self.error('MalformedPolygon', e, 'edges %d and %d intersect (self-intersecting polygon)' % (i, j))
                    return False
        if not math.isfinite(area) or area == 0:
            self.error('MalformedPolygon', e, 'polygon has zero or non-finite area')
            return False
        return True

    # ---- markers (§4.5)
    def markers(self, layer):
        spawns, finishes = [], []
        for c in layer:
            if c.tag in IGNORED:
                continue
            if c.tag == SVG + 'circle' and c.get('data-marker') == 'spawn':
                spawns.append(c)
            elif c.tag == SVG + 'rect' and c.get('data-marker') == 'finish':
                finishes.append(c)
            else:
                self.error('UnsupportedShape', c, 'markers layer holds only circle[data-marker=spawn] and rect[data-marker=finish]')
        spawn = finish = None
        if not spawns:
            self.error('MissingSpawn', layer, 'add <circle id="spawn" data-marker="spawn" cx=".." cy=".." r=".."/>')
        elif len(spawns) > 1:
            self.error('DuplicateSpawn', spawns[1], 'exactly one spawn marker is allowed')
        elif self.marker(spawns[0], SPAWN_ATTRS, 'spawn'):
            s = spawns[0]
            cx, cy = self.number(s, 'cx'), self.number(s, 'cy')
            self.number(s, 'r', required=False)
            if None not in (cx, cy):
                spawn = {'x': plain(cx), 'y': plain(cy)}
        if not finishes:
            self.error('MissingFinish', layer, 'add <rect id="finish" data-marker="finish" x y width height/>')
        elif len(finishes) > 1:
            self.error('DuplicateFinish', finishes[1], 'exactly one finish marker is allowed')
        elif self.marker(finishes[0], FINISH_ATTRS, 'finish'):
            f = finishes[0]
            x, y, w, h = (self.number(f, k) for k in ('x', 'y', 'width', 'height'))
            if None not in (x, y, w, h):
                if w > 0 and h > 0:
                    finish = {'left': plain(x), 'top': plain(y), 'right': plain(x + w), 'bottom': plain(y + h)}
                else:
                    self.error('InvalidBounds', f, 'finish width and height must be > 0')
        return spawn, finish

    def marker(self, e, allowed, what):
        if not e.get('id'):
            self.error('InvalidId', e, 'the %s marker needs an id' % what)
            return False
        return self.gameplay_attrs(e, allowed, what + ' marker')

    # ---- route (§4.6)
    def route(self, meta, elements, fragments):
        extra = sorted(a for a in meta.attrib if a != 'id')
        if extra:
            self.error('UnknownAttribute', meta, 'level-route does not allow %s' % ', '.join(extra))
        nodes = {'section': [], 'encounter': [], 'transfer': []}
        for c in meta:
            kind = c.tag[len(GN):] if c.tag.startswith(GN) else None
            if kind not in nodes:
                self.error('UnknownAttribute', c, '<%s> is not a level-route node (gn:section, gn:encounter, gn:transfer in %s)' % (c.tag, GN[1:-1]))
                continue
            required, optional = ROUTE_ATTRS[kind]
            unknown = sorted(a for a in c.attrib if a not in required | optional)
            if unknown:
                self.error('UnknownAttribute', c, 'gn:%s does not allow %s' % (kind, ', '.join(unknown)))
                continue
            missing = sorted(a for a in required if not (c.get(a) or '').strip())
            if missing:
                self.error('MissingMetadata', c, 'gn:%s requires non-empty %s' % (kind, ', '.join(missing)))
                continue
            nodes[kind].append(c)
        for kind, items in nodes.items():
            if not items:
                self.error('MissingMetadata', meta, 'at least one gn:%s is required' % kind)
        self.check()

        element_ids = {el['id'] for el in elements}
        encounter_ids = {c.get('id') for c in nodes['encounter']}
        listed = set()

        def refs(node, attr, targets, what):
            values = node.get(attr).split()
            for i, v in enumerate(values):
                if v in values[:i]:
                    self.error('MissingReference', node, '%s lists %r twice' % (attr, v))
                elif v not in targets:
                    self.error('MissingReference', node, '%s -> %r is not a %s' % (attr, v, what))
            return values

        sections = []
        for s in nodes['section']:
            section = {'id': s.get('id'), 'encounters': refs(s, 'encounters', encounter_ids, 'gn:encounter id')}
            listed.update(section['encounters'])
            if s.get('label-key') is not None:
                section['labelKey'] = s.get('label-key')
            sections.append(section)
        encounters = []
        for c in nodes['encounter']:
            if c.get('id') not in listed:
                self.error('MissingReference', c, 'orphan encounter: no gn:section lists it')
            encounters.append({'id': c.get('id'), 'elements': refs(c, 'elements', element_ids, 'geometry element id (not a fragment or marker)')})
        transfers = []
        for t in nodes['transfer']:
            source, target = t.get('from'), t.get('to')
            for attr in ('from', 'to'):
                if t.get(attr) not in fragments:
                    self.error('MissingReference', t, '%s -> %r is not a fragment id' % (attr, t.get(attr)))
            if source == target:
                self.error('InvalidTransfer', t, 'from and to are both %r' % source)
            if t.get('encounter') not in encounter_ids:
                self.error('MissingReference', t, 'encounter -> %r is not a gn:encounter id' % t.get('encounter'))
            raw = t.get('gap-percent')
            gap = float(raw) if NUMBER.match(raw) else None
            if gap is None or not math.isfinite(gap) or gap < 0:
                self.error('InvalidTransfer', t, 'gap-percent=%r must be a finite number >= 0' % raw)
                continue
            transfers.append({'id': t.get('id'), 'from': source, 'to': target, 'encounter': t.get('encounter'), 'gapPercent': plain(gap)})
        return sections, encounters, transfers


def import_svg(data):
    """Return the level object for SVG bytes, or raise Rejected."""
    return Importer(data).run()


def dumps(level):
    return json.dumps(level, separators=(',', ':'), ensure_ascii=True) + '\n'


def write_atomic(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=directory)
    try:
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)  # mkstemp creates 0600; give the output normal file permissions
        with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Import a Grapple Over level SVG (format v1) to level JSON.')
    parser.add_argument('--input', required=True, help='level SVG file')
    parser.add_argument('--output', required=True, help='level JSON file to write (replaced atomically on success only)')
    parser.add_argument('--format', choices=('json', 'javascript'), default='json',
                        help='JSON data (default), or a classic script for file:// startup')
    args = parser.parse_args(argv)
    if os.path.abspath(args.input) == os.path.abspath(args.output) or (
            os.path.exists(args.output) and os.path.exists(args.input) and os.path.samefile(args.input, args.output)):
        parser.error('--input and --output must name different files')
    try:
        with open(args.input, 'rb') as f:
            data = f.read()
    except OSError as e:
        print(format_error(('InputError', args.input, e.strerror or str(e))), file=sys.stderr)
        return 1
    try:
        level = import_svg(data)
    except Rejected as e:
        for error in e.errors:
            print(format_error(error), file=sys.stderr)
        return 1
    try:
        payload = dumps(level)
        if args.format == 'javascript':
            payload = '// Generated by tools/import_level_svg.py; do not edit.\nwindow.GRAPPLE_OVER_BUNDLED_LEVEL = ' + payload.rstrip() + ';\n'
        write_atomic(args.output, payload)
    except OSError as e:
        print(format_error(('OutputError', args.output, e.strerror or str(e))), file=sys.stderr)
        return 1
    print('imported %s: %d elements, %d fragments, %d sections, %d encounters, %d transfers' % (
        level['layoutId'], len(level['elements']), len(level['svgFormat']['fragments']), len(level['sections']),
        len(level['encounters']), len(level['svgFormat']['transfers'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
