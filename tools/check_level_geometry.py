#!/usr/bin/env python3
"""Independent geometry checks for an imported level (level SVG format v1).

Recomputes every distance from the imported polygons. Recorded distances,
gap-percent attributes and printed labels are only ever the expected side of
a comparison, never the computed result (docs/level-svg-format.md §7).

    python3 tools/check_level_geometry.py --svg LEVEL.svg --level LEVEL.json --report REPORT.json \
        [--reference MEASUREMENTS.json] [--min-side-length UNITS | --no-min-side-length] [--no-grapple-rest]
    python3 tools/check_level_geometry.py --sides-only --level LEVEL.json --report REPORT.json \
        [--min-side-length UNITS | --no-min-side-length]

Checks:
- level JSON polygons match the SVG geometry layer and the reference fragments
  and yellow bands within 0.01 unit;
- each transfer's computed gap percentage (minimum edge-to-edge distance
  between the two fragments' polygon unions / 540 * 100) matches the SVG
  gap-percent, the level JSON gapPercent and the reference percent within
  0.01 percentage point;
- fragment pairs keep clearance - player diameter > 540, except explicitly
  authored allowedGrapplePairs, which must have a positive gap below 540, and
  internal no-grapple transfers: a route transfer whose two complete fragments
  and witness segment lie inside one convex no-grapple zone needs
  0 < gap <= 270 instead (any other pair keeps the 540 rule);
- every polygon is simple, non-degenerate and has interior angles >= 20 degrees;
- every actual polygon edge of a gameplay element (solid/bounce/hazard bodies,
  extra bodies, posts and bevels, yellow drag and purple no-grapple zones) is
  measured from the imported vertices and inventoried; an edge shorter than
  the minimum (default 270 = 0.5 R, --min-side-length UNITS) minus COORD_TOL
  fails. --no-min-side-length only inventories the sides (legacy layouts
  before v16); the CLI enforces the rule by default since TASK-687. This is unrelated to the 270 maximum internal
  no-grapple transfer gap. Elements without a gameplay role are decorative and
  exempt. --sides-only checks sides, corners and self-intersections from the
  level JSON alone, so old levels stay checkable during candidate migration;
- drag zones are axis-aligned horizontal non-grapplable rectangles with a
  minimum solid clearance >= 1080 (no-grapple zones are not solids or brakes);
- no-grapple zones are non-grapplable convex polygons outside fragments;
- opt-in --no-grapple-rest (off by default): every upward-facing solid/bounce
  edge that overlaps a no-grapple zone slopes >= 15 degrees from horizontal,
  and no two such edges meet in a pocket (a vertex both slope down toward), so
  the player cannot come to rest where it cannot grapple (report noGrappleRest).

Exit 0 when every check passes, 1 on a failed check, 2 on usage errors.
"""
import argparse
import itertools
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

GRAPPLE_RANGE = 540.0
PLAYER_DIAMETER = 21.6
COORD_TOL = 0.01
# Largest edge-to-edge gap of a transfer inside one no-grapple zone (0.5 R).
NO_GRAPPLE_INTERNAL_GAP = 270.0
PERCENT_TOL = 0.01
# Shortest allowed polygon side (0.5 R); enforced by the CLI by default, check(min_side=None) only inventories.
MIN_SIDE_LENGTH = 0.5 * GRAPPLE_RANGE
# Roles whose polygon edges are collision/zone geometry; anything else is decorative.
GAMEPLAY_ROLES = ('solid', 'bounce', 'hazard', 'drag', 'no-grapple')
PERCENT_KEYS = ('svgGapPercent', 'levelGapPercent', 'referencePercent')
SVG = '{http://www.w3.org/2000/svg}'
GN = '{urn:grapnelninja:level-svg:1}'
DEFAULT_REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'artifacts', 'levels',
                                 'extended-mountain-measurements.json')


# --- geometry -------------------------------------------------------------

def cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_cross(p1, p2, q1, q2):
    """Proper crossing only; touching and collinear contact give distance 0 anyway."""
    d1, d2 = cross(q1, q2, p1), cross(q1, q2, p2)
    d3, d4 = cross(p1, p2, q1), cross(p1, p2, q2)
    return ((d1 > 0) != (d2 > 0)) and d1 != 0 and d2 != 0 and ((d3 > 0) != (d4 > 0)) and d3 != 0 and d4 != 0


def point_segment(p, a, b):
    """Return (distance, closest point on ab)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    c = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(p[0] - c[0], p[1] - c[1]), c


def inside(p, poly):
    """Even-odd ray cast; works for concave polygons."""
    result = False
    for i in range(len(poly)):
        a, b = poly[i], poly[i - 1]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                result = not result
    return result


def convex_contains(poly, p, tol=1e-9):
    """p inside or on the boundary of convex poly (either winding)."""
    orientation = 1.0 if signed_area(poly) > 0 else -1.0
    return all(orientation * cross(a, b, p) >= -tol * max(1.0, math.dist(a, b)) for a, b in edges(poly))


def is_convex(poly):
    turns = {cross(poly[i - 1], poly[i], poly[(i + 1) % len(poly)]) > 0 for i in range(len(poly))
             if cross(poly[i - 1], poly[i], poly[(i + 1) % len(poly)]) != 0}
    return len(turns) == 1


def containing_zone(zones, polys, witness):
    """Id of the first convex zone holding every vertex of polys and both witness ends, else None."""
    for zid, zone in zones:
        if all(convex_contains(zone, p) for poly in polys for p in poly) and \
                all(convex_contains(zone, p) for p in witness):
            return zid
    return None


def edges(poly):
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def polygon_distance(a, b):
    """Minimum distance between two filled simple polygons, with witness points.

    0 when the boundaries intersect or touch, or one polygon contains the other.
    """
    ea, eb = edges(a), edges(b)
    for p1, p2 in ea:
        for q1, q2 in eb:
            if segments_cross(p1, p2, q1, q2):
                return 0.0, [p1, p1], 'intersect'
    if inside(a[0], b):
        return 0.0, [a[0], a[0]], 'contained'
    if inside(b[0], a):
        return 0.0, [b[0], b[0]], 'contains'
    best = (math.inf, None)
    for p1, p2 in ea:
        for q1, q2 in eb:
            for p, s1, s2, flip in ((p1, q1, q2, False), (p2, q1, q2, False), (q1, p1, p2, True), (q2, p1, p2, True)):
                d, c = point_segment(p, s1, s2)
                if d < best[0]:
                    best = (d, [c, p] if flip else [p, c])
    return best[0], best[1], ('touch' if best[0] == 0 else 'separated')


def union_distance(polys_a, polys_b):
    """Minimum distance between two unions of polygons (compound fragments)."""
    best = (math.inf, None, None, None)
    for ia, a in enumerate(polys_a):
        for ib, b in enumerate(polys_b):
            d, witness, relation = polygon_distance(a, b)
            if d < best[0]:
                best = (d, witness, relation, (ia, ib))
    return best


def axis_rect(poly):
    """(x, y, width, height) when poly is an axis-aligned rectangle, else None."""
    if len(poly) != 4:
        return None
    xs, ys = sorted({p[0] for p in poly}), sorted({p[1] for p in poly})
    if len(xs) != 2 or len(ys) != 2:
        return None
    for (x1, y1), (x2, y2) in edges(poly):
        if x1 != x2 and y1 != y2:
            return None
    return xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0]


MIN_INTERIOR_ANGLE = 20.0
# Exactly 20 degrees must pass despite float noise from world-space coordinates.
ANGLE_TOL_DEG = 1e-9


class AngleError(ValueError):
    """A polygon corner whose interior angle is undefined (vertex index in .vertex)."""

    def __init__(self, vertex, reason):
        super().__init__('vertex %s: %s' % (vertex, reason))
        self.vertex, self.reason = vertex, reason


def signed_area(poly):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(poly)) / 2.0


def interior_angles(poly):
    """Interior angle in degrees at every vertex of a simple polygon, either winding.

    Concave vertices get their reflex angle (> 180). Raises AngleError on fewer than
    three vertices, zero-length edges (repeated adjacent vertices, including a
    closing vertex equal to the first), zero area, or a corner whose edges fold
    back onto each other.
    """
    n = len(poly)
    if n < 3:
        raise AngleError(None, 'fewer than 3 vertices')
    for i, (a, b) in enumerate(edges(poly)):
        if a[0] == b[0] and a[1] == b[1]:
            raise AngleError(i, 'zero-length edge to vertex %d' % ((i + 1) % n))
    area = signed_area(poly)
    if area == 0:
        raise AngleError(None, 'zero area: winding undefined')
    orientation = 1.0 if area > 0 else -1.0
    angles = []
    for i in range(n):
        prev, cur, nxt = poly[i - 1], poly[i], poly[(i + 1) % n]
        ux, uy = cur[0] - prev[0], cur[1] - prev[1]
        vx, vy = nxt[0] - cur[0], nxt[1] - cur[1]
        turn_cross, turn_dot = ux * vy - uy * vx, ux * vx + uy * vy
        if turn_cross == 0 and turn_dot < 0:
            raise AngleError(i, 'edges fold back (0 or 360 degree spike)')
        turn = math.degrees(math.atan2(turn_cross, turn_dot))
        angles.append(180.0 - orientation * turn)
    return angles


def angle_report(poly, minimum=MIN_INTERIOR_ANGLE, tol=ANGLE_TOL_DEG):
    """Per-vertex angle results; ok is False on any too-sharp or undefined corner."""
    try:
        angles = interior_angles(poly)
    except AngleError as e:
        return {'ok': False, 'error': {'vertex': e.vertex, 'reason': e.reason}, 'vertices': []}
    vertices = [{'vertex': i, 'angle': a, 'kind': 'reflex' if a > 180 else ('straight' if a == 180 else 'convex'),
                 'ok': a >= minimum - tol} for i, a in enumerate(angles)]
    return {'ok': all(v['ok'] for v in vertices), 'error': None, 'vertices': vertices}


def self_intersections(poly):
    """Index pairs of non-adjacent edges that cross or touch; empty for a simple polygon."""
    n, found = len(poly), []
    for i, j in itertools.combinations(range(n), 2):
        if j == i + 1 or (i == 0 and j == n - 1):
            continue
        (a, b), (c, d) = (poly[i], poly[(i + 1) % n]), (poly[j], poly[(j + 1) % n])
        if segments_cross(a, b, c, d) or min(point_segment(a, c, d)[0], point_segment(b, c, d)[0],
                                             point_segment(c, a, b)[0], point_segment(d, a, b)[0]) == 0:
            found.append([i, j])
    return found


def side_lengths(poly):
    """Euclidean length of every edge i -> i+1 (closing edge last), from vertices alone."""
    return [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in edges(poly)]


def side_rows(polys, fragments=None, names=None, minimum=MIN_SIDE_LENGTH, tol=COORD_TOL):
    """Per-edge inventory of gameplay polygons; decorative roles are listed as exempt.

    polys: element id -> (element, absolute polygon). fragments: fragment id ->
    element ids (body index = position). names: fragment id -> semantic label.
    An edge passes when length >= minimum - tol.
    """
    owner = {eid: (fid, i) for fid, eids in (fragments or {}).items() for i, eid in enumerate(eids)}
    rows = []
    for eid in sorted(polys):
        element, poly = polys[eid]
        fid, body = owner.get(eid, (None, None))
        exempt = element.get('role') not in GAMEPLAY_ROLES
        for i, length in enumerate(side_lengths(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            rows.append({'element': eid, 'role': element.get('role'), 'fragment': fid, 'body': body,
                         'semantic': (names or {}).get(fid), 'edge': i, 'from': rp(a), 'to': rp(b),
                         'length': r(length), 'exempt': exempt, 'pass': exempt or length >= minimum - tol})
    return rows


def side_summary(rows, minimum, enforced):
    measured = [s for s in rows if not s['exempt']]
    return {'minSideLength': minimum, 'minSideEnforced': enforced, 'sideEdges': len(measured),
            'sideExemptEdges': len(rows) - len(measured), 'sideViolations': sum(not s['pass'] for s in rows),
            'minMeasuredSide': min((s['length'] for s in measured), default=None)}


def corner_rows(polys, fail):
    """Angle and self-intersection rows for every polygon; failures go to fail()."""
    angle_rows = []
    for eid in sorted(polys):
        report = angle_report(polys[eid][1])
        crossings = self_intersections(polys[eid][1])
        angles = [v['angle'] for v in report['vertices']]
        row = {'id': eid, 'role': polys[eid][0]['role'], 'error': report['error'], 'selfIntersections': crossings,
               'area': r(abs(signed_area(polys[eid][1]))), 'minAngle': r(min(angles, default=None), 9),
               'angles': [r(a, 9) for a in angles], 'pass': report['ok'] and not crossings}
        if report['error']:
            fail('%s: degenerate polygon (%s)' % (eid, report['error']['reason']))
        for v in report['vertices']:
            if not v['ok']:
                fail('%s vertex %d: interior angle %.6f < %.1f degrees' % (eid, v['vertex'], v['angle'],
                                                                          MIN_INTERIOR_ANGLE))
        if crossings:
            fail('%s: self-intersecting edges %s' % (eid, crossings))
        angle_rows.append(row)
    return angle_rows


def fail_sides(rows, minimum, fail):
    for s in rows:
        if not s['pass']:
            fail('%s edge %d (%s %s): side length %.6f < %.1f' % (
                s['element'], s['edge'], s['role'], s['semantic'] or s['fragment'] or '-', s['length'], minimum))


def check_sides(level, minimum=MIN_SIDE_LENGTH, names=None):
    """Sides + corners from the level JSON alone (no SVG/reference); minimum None = inventory only."""
    failures = []
    polys = level_polygons(level)
    fragments = {f['id']: f['elements'] for f in level.get('svgFormat', {}).get('fragments', [])}
    sides = side_rows(polys, fragments, names, MIN_SIDE_LENGTH if minimum is None else minimum)
    if minimum is not None:
        fail_sides(sides, minimum, failures.append)
    angle_rows = corner_rows(polys, failures.append)
    summary = {'pass': not failures, 'failures': len(failures), 'anglePolygons': len(angle_rows),
               'anglePolygonsPass': sum(a['pass'] for a in angle_rows),
               'minInteriorAngle': r(min((a['minAngle'] for a in angle_rows if a['minAngle'] is not None),
                                         default=None), 9)}
    summary.update(side_summary(sides, MIN_SIDE_LENGTH if minimum is None else minimum, minimum is not None))
    return {'layoutId': level.get('layoutId'), 'coordTolerance': COORD_TOL, 'summary': summary,
            'failureMessages': failures, 'sides': sides, 'angles': angle_rows}


# --- no rest inside purple (opt-in, --no-grapple-rest) ---------------------
# Shallowest upward face allowed where it overlaps a no-grapple zone (docs/level-svg-format.md §7.3).
NO_GRAPPLE_REST_SLOPE = 15.0
# Roles the ninja can stand on; a hazard kills on contact, so resting on it is no softlock.
REST_ROLES = ('solid', 'bounce')


def zone_overlap(a, b, zone):
    """Length of segment a-b inside convex zone (Cyrus-Beck clip, either winding)."""
    o = 1.0 if signed_area(zone) > 0 else -1.0
    t0, t1 = 0.0, 1.0
    for p, q in edges(zone):
        fa, fb = o * cross(p, q, a), o * cross(p, q, b)
        if fa < 0 and fb < 0:
            return 0.0
        if fa < 0:
            t0 = max(t0, fa / (fa - fb))
        elif fb < 0:
            t1 = min(t1, fa / (fa - fb))
    return max(0.0, t1 - t0) * math.dist(a, b)


def rest_faces(polys, zones, fragments=None, names=None, minimum=NO_GRAPPLE_REST_SLOPE):
    """Upward-facing solid/bounce edges (y grows down) that overlap a no-grapple zone, with slope from horizontal."""
    frag_of = {eid: (fid, i) for fid, eids in (fragments or {}).items() for i, eid in enumerate(eids)}
    rows = []
    for eid, (element, poly) in polys.items():
        if element.get('role') not in REST_ROLES or len(poly) < 3:
            continue
        o = 1.0 if signed_area(poly) > 0 else -1.0
        for i, (a, b) in enumerate(edges(poly)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            # Outward normal is o * (dy, -dx); the face looks up when its y component is negative.
            if o * dx <= COORD_TOL:
                continue
            overlaps = sorted(((zone_overlap(a, b, z), zid) for zid, z in zones), reverse=True)
            if not overlaps or overlaps[0][0] <= COORD_TOL:
                continue
            angle = math.degrees(math.atan2(abs(dy), abs(dx)))
            fid = frag_of.get(eid, (None, None))[0]
            rows.append({'element': eid, 'fragment': fid, 'semantic': (names or {}).get(fid), 'edge': i,
                         'angle': r(angle, 6), 'zone': overlaps[0][1],
                         'zones': [zid for length, zid in overlaps if length > COORD_TOL],
                         'a': rp(a), 'b': rp(b), 'pass': angle >= minimum - ANGLE_TOL_DEG})
    return rows


def rest_pockets(faces):
    """Vertices where two in-zone upward faces both slope down toward it from opposite sides."""
    sloped = []
    for f in faces:
        a, b = f['a'], f['b']
        if abs(a[1] - b[1]) <= COORD_TOL:
            continue
        low, high = (a, b) if a[1] > b[1] else (b, a)
        sloped.append((f, low, high))
    pockets = []
    for (f, low, high), (g, low2, high2) in itertools.combinations(sloped, 2):
        if max_point_error([low], [low2]) > COORD_TOL:
            continue
        if (high[0] - low[0]) * (high2[0] - low2[0]) >= 0:
            continue
        left, right = (f, g) if high[0] < low[0] else (g, f)
        pockets.append({'vertex': low, 'left': {'element': left['element'], 'edge': left['edge'], 'angle': left['angle']},
                        'right': {'element': right['element'], 'edge': right['edge'], 'angle': right['angle']},
                        'zones': sorted(set(left['zones']) | set(right['zones'])), 'pass': False})
    return pockets


def check_rest(polys, zones, fragments, names, fail, minimum=NO_GRAPPLE_REST_SLOPE):
    faces = rest_faces(polys, zones, fragments, names, minimum)
    pockets = rest_pockets(faces)
    for f in faces:
        if not f['pass']:
            fail('%s edge %d (%s) in no-grapple zone %s: upward face slopes %.6f deg < %.1f (rest)' % (
                f['element'], f['edge'], f['semantic'] or f['fragment'] or '-', f['zone'], f['angle'], minimum))
    for p in pockets:
        fail('no-grapple zone %s: pocket at %s between %s edge %d and %s edge %d (rest)' % (
            '/'.join(p['zones']), p['vertex'], p['left']['element'], p['left']['edge'], p['right']['element'],
            p['right']['edge']))
    summary = {'noGrappleRestSlope': minimum, 'noGrappleRestFaces': len(faces),
               'noGrappleRestFaceViolations': sum(not f['pass'] for f in faces), 'noGrappleRestPockets': len(pockets),
               'minNoGrappleRestAngle': min((f['angle'] for f in faces), default=None)}
    return {'minSlope': minimum, 'roles': list(REST_ROLES), 'faces': faces, 'pockets': pockets}, summary


def max_point_error(p, q):
    if len(p) != len(q):
        return math.inf
    return max((max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(p, q)), default=0.0)


# --- inputs ---------------------------------------------------------------

def level_polygons(level):
    """element id -> (element, absolute world polygon) from the imported level JSON."""
    return {e['id']: (e, [(e['x'] + p['x'], e['y'] + p['y']) for p in e['points']]) for e in level['elements']}


def svg_geometry(data):
    """Read gameplay polygons and transfer gap-percent straight from the SVG (no importer)."""
    root = ET.fromstring(data)
    shapes, percents = {}, {}
    for layer in root:
        if layer.tag == SVG + 'g' and layer.get('data-layer') == 'geometry':
            for e in layer.iter():
                if e.get('data-role') is None:
                    continue
                if e.tag == SVG + 'rect':
                    x, y, w, h = (float(e.get(k)) for k in ('x', 'y', 'width', 'height'))
                    shapes[e.get('id')] = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                elif e.tag == SVG + 'polygon':
                    n = [float(v) for v in e.get('points').replace(',', ' ').split()]
                    shapes[e.get('id')] = list(zip(n[0::2], n[1::2]))
    for t in root.iter(GN + 'transfer'):
        percents[t.get('id')] = float(t.get('gap-percent'))
    return shapes, percents


def r(v, digits=6):
    return None if v is None or v == math.inf else round(v, digits)


def rp(p):
    return [r(p[0], 4), r(p[1], 4)]


# --- checks ---------------------------------------------------------------

def check(level, svg_data, reference, min_side=None, no_grapple_rest=False):
    """min_side None inventories sides without failing (shipped layouts); a number enforces it.

    no_grapple_rest adds the opt-in no-rest-inside-purple rule (report key noGrappleRest); off, the report is unchanged.
    """
    failures = []
    fail = failures.append
    polys = level_polygons(level)
    svg_shapes, svg_percents = svg_geometry(svg_data)
    fmt = level['svgFormat']
    if fmt.get('grappleRange') != GRAPPLE_RANGE:
        fail('grappleRange %r != 540' % fmt.get('grappleRange'))
    fragments = {f['id']: f['elements'] for f in fmt['fragments']}
    zones = [(eid, poly) for eid, (e, poly) in polys.items() if e['role'] == 'no-grapple']
    frag_polys = {fid: [polys[eid][1] for eid in eids] for fid, eids in fragments.items()}

    # Coordinates: level JSON vs SVG geometry layer.
    svg_max = 0.0
    if set(svg_shapes) != set(polys):
        fail('SVG/level element ids differ: %s' % sorted(set(svg_shapes) ^ set(polys)))
    for eid in sorted(set(svg_shapes) & set(polys)):
        err = max_point_error(polys[eid][1], svg_shapes[eid])
        svg_max = max(svg_max, err)
        if err > COORD_TOL:
            fail('%s: level vs SVG coordinate error %.6g > %.2g' % (eid, err, COORD_TOL))

    # Corners: every final polygon, computed from level coordinates alone.
    angle_rows = corner_rows(polys, fail)
    names = {f['id']: f.get('semanticId') or f.get('name') for f in reference.get('fragments', [])}
    sides = side_rows(polys, fragments, names, MIN_SIDE_LENGTH if min_side is None else min_side)
    if min_side is not None:
        fail_sides(sides, min_side, fail)

    # Coordinates: level fragments vs reference fragments.
    ref_frags = {f['id']: f for f in reference['fragments']}
    frag_rows, frag_max = [], 0.0
    if set(ref_frags) != set(fragments):
        fail('reference/level fragment ids differ: %s' % sorted(set(ref_frags) ^ set(fragments)))
    for fid in sorted(set(ref_frags) & set(fragments), key=lambda s: int(s[1:]) if s[1:].isdigit() else s):
        rf = ref_frags[fid]
        ref_polys = [[(rf['x'] + p[0], rf['y'] + p[1]) for p in poly] for poly in rf['polys']]
        if len(ref_polys) != len(frag_polys[fid]):
            fail('%s: %d polygons, reference has %d' % (fid, len(frag_polys[fid]), len(ref_polys)))
            err = math.inf
        else:
            err = max(max_point_error(a, b) for a, b in zip(frag_polys[fid], ref_polys))
        frag_max = max(frag_max, err)
        if err > COORD_TOL:
            fail('%s: coordinate error vs reference %.6g > %.2g' % (fid, err, COORD_TOL))
        frag_rows.append({'id': fid, 'polygons': len(frag_polys[fid]), 'vertices': sum(map(len, frag_polys[fid])),
                          'maxCoordError': r(err, 9), 'pass': err <= COORD_TOL})

    # Transfers.
    ref_enc = {e['id']: e for e in reference['encounters']}
    transfers = []
    for t in fmt['transfers']:
        d, witness, relation, bodies = union_distance(frag_polys[t['from']], frag_polys[t['to']])
        pct = d / GRAPPLE_RANGE * 100
        enc = ref_enc.get(t['encounter'], {})
        expected = {'svgGapPercent': svg_percents.get(t['id']), 'levelGapPercent': t['gapPercent'],
                    'referencePercent': enc.get('percent'), 'referenceDistance': enc.get('distance')}
        errors = {
            'svgGapPercent': None if expected['svgGapPercent'] is None else abs(pct - expected['svgGapPercent']),
            'levelGapPercent': abs(pct - t['gapPercent']),
            'referencePercent': None if enc.get('percent') is None else abs(pct - enc['percent']),
            'referenceDistance': None if enc.get('distance') is None else abs(d - enc['distance']),
        }
        ok = True
        for key in PERCENT_KEYS:
            if errors[key] is None or errors[key] > PERCENT_TOL:
                ok = False
                fail('%s %s->%s: computed %.6f%% vs %s %r (error %s > %.2g pp)' % (
                    t['id'], t['from'], t['to'], pct, key, expected[key], r(errors[key]), PERCENT_TOL))
        if errors['referenceDistance'] is None or errors['referenceDistance'] > COORD_TOL:
            ok = False
            fail('%s: computed distance %.6f vs reference %r' % (t['id'], d, expected['referenceDistance']))
        if enc and (enc.get('fromFragment'), enc.get('toFragment')) != (t['from'], t['to']):
            ok = False
            fail('%s: fragments %s->%s, reference encounter has %s->%s' % (
                t['id'], t['from'], t['to'], enc.get('fromFragment'), enc.get('toFragment')))
        transfers.append({'id': t['id'], 'encounter': t['encounter'], 'from': t['from'], 'to': t['to'],
                          'computedDistance': r(d), 'computedPercent': r(pct), 'relation': relation,
                          'closestBodies': [fragments[t['from']][bodies[0]], fragments[t['to']][bodies[1]]],
                          'witness': [rp(p) for p in witness], 'expected': expected,
                          'percentErrors': {k: r(v, 9) for k, v in errors.items()}, 'pass': ok})

    # All distinct fragment pairs: explicit easy-opening exceptions only.
    ref_pairs = {frozenset((p['source'], p['target'])): p['minimumGap'] for p in reference.get('pairChecks', [])}
    transfer_pairs = {frozenset((t['from'], t['to'])) for t in fmt['transfers']}
    pairs = []
    for a, b in itertools.combinations(sorted(fragments, key=lambda s: int(s[1:]) if s[1:].isdigit() else s), 2):
        d, witness, relation, _ = union_distance(frag_polys[a], frag_polys[b])
        margin = d - PLAYER_DIAMETER
        ref_gap = ref_pairs.get(frozenset((a, b)))
        opening = frozenset((a, b)) in {frozenset(p) for p in reference.get('allowedGrapplePairs', [])}
        is_transfer = frozenset((a, b)) in transfer_pairs
        zone = None if opening or not is_transfer or witness is None else \
            containing_zone(zones, frag_polys[a] + frag_polys[b], witness)
        if zone is not None:
            rule = 'noGrappleInternal'
            ok = 0 < d <= NO_GRAPPLE_INTERNAL_GAP
            if not ok:
                fail('pair %s/%s: internal no-grapple transfer gap %.6f not in (0, %.0f] (%s)' % (
                    a, b, d, NO_GRAPPLE_INTERNAL_GAP, zone))
        else:
            rule = 'opening' if opening else 'grappleClearance'
            ok = (d > 0 and d < GRAPPLE_RANGE) if opening else margin > GRAPPLE_RANGE
            if not ok:
                fail('pair %s/%s: clearance %.6f - %.1f = %.6f <= 540 (grapple shortcut)' % (
                    a, b, d, PLAYER_DIAMETER, margin))
        ref_err = None if ref_gap is None else abs(d - ref_gap)
        if ref_err is not None and ref_err > COORD_TOL:
            fail('pair %s/%s: clearance %.6f vs reference %.6f' % (a, b, d, ref_gap))
        pairs.append({'a': a, 'b': b, 'transfer': is_transfer, 'relation': relation, 'rule': rule, 'noGrappleZone': zone,
                      'clearance': r(d), 'clearanceMinusDiameter': r(margin), 'referenceGap': r(ref_gap),
                      'referenceError': r(ref_err, 9), 'pass': ok and (ref_err is None or ref_err <= COORD_TOL)})

    # Counts and order follow the reference, never a fixed level size.
    n_frag = len(reference['fragments'])
    if len(fragments) != n_frag or len(pairs) != n_frag * (n_frag - 1) // 2:
        fail('%d fragments / %d pairs, reference implies %d / %d' % (
            len(fragments), len(pairs), n_frag, n_frag * (n_frag - 1) // 2))
    if len(fmt['transfers']) != len(reference['encounters']):
        fail('%d transfers, reference has %d encounters' % (len(fmt['transfers']), len(reference['encounters'])))
    chain = [(t['from'], t['to']) for t in fmt['transfers']]
    if any(chain[i][1] != chain[i + 1][0] for i in range(len(chain) - 1)):
        fail('transfers are not one connected ordered route')

    # Drag zones.
    ref_bands = {b['id'] + '-drag': b for b in reference.get('yellowBands', [])}
    solid = [(eid, poly) for eid, (e, poly) in polys.items() if e['role'] not in ('drag', 'no-grapple')]
    drags = []
    for eid, (e, poly) in polys.items():
        if e['role'] != 'drag':
            continue
        rect = axis_rect(poly)
        rb = ref_bands.get(eid)
        nearest = min(((polygon_distance(poly, sp)[0], sid) for sid, sp in solid), default=(math.inf, None))
        row = {'id': eid, 'grapplable': e['grapplable'], 'axisAligned': rect is not None,
               'rect': None if rect is None else [r(v, 6) for v in rect],
               'reference': None if rb is None else [rb['x'], rb['y'], rb['width'], rb['height']],
               'minSolidClearance': r(nearest[0]), 'nearestSolid': nearest[1],
               'referenceClearance': None if rb is None else rb.get('nearestSolidClearance')}
        problems = []
        if e['grapplable'] is not False:
            problems.append('grapplable')
        if rect is None:
            problems.append('not an axis-aligned rectangle')
        elif rect[2] <= rect[3]:
            problems.append('not horizontal (width %.3f <= height %.3f)' % (rect[2], rect[3]))
        if rb is None:
            problems.append('no reference band')
        elif rect is not None:
            row['maxRectError'] = r(max(abs(a - b) for a, b in zip(rect, row['reference'])), 9)
            if row['maxRectError'] > COORD_TOL:
                problems.append('rect error %.6g > %.2g' % (row['maxRectError'], COORD_TOL))
        if rb is not None and abs(nearest[0] - rb.get('nearestSolidClearance', math.inf)) > COORD_TOL:
            problems.append('solid clearance %.6f vs reference %r' % (nearest[0], rb.get('nearestSolidClearance')))
        # Reference metadata may strengthen the rule, never weaken it.
        minimum_clearance = max(2 * GRAPPLE_RANGE, rb.get('minimumSolidClearance', 0) if rb else 0)
        if nearest[0] < minimum_clearance:
            problems.append('solid clearance %.6f < %.6f (%s)' % (nearest[0], minimum_clearance, nearest[1]))
        row['pass'] = not problems
        for p in problems:
            fail('%s: %s' % (eid, p))
        drags.append(row)
    if len(drags) != len(ref_bands):
        fail('%d drag zones, expected %d' % (len(drags), len(ref_bands)))
    if set(d['id'] for d in drags) != set(ref_bands):
        fail('drag ids differ from reference bands: %s' % sorted(set(d['id'] for d in drags) ^ set(ref_bands)))

    drag_pairs=[]
    drag_polys=[(eid,poly) for eid,(element,poly) in polys.items() if element['role']=='drag']
    for i,(aid,apoly) in enumerate(drag_polys):
        for bid,bpoly in drag_polys[i+1:]:
            distance=polygon_distance(apoly,bpoly)[0]
            passed=distance>=GRAPPLE_RANGE
            drag_pairs.append({'source':aid,'target':bid,'clearance':r(distance),'pass':passed})
            if not passed:
                fail('yellow pair %s/%s: clearance %.6f < %.6f' % (aid,bid,distance,GRAPPLE_RANGE))

    # No-grapple zones: static convex regions outside fragments, never grapple targets.
    in_fragment = {eid for eids in fragments.values() for eid in eids}
    zone_rows = []
    for zid, zone in zones:
        problems = [p for p, bad in (('grapplable', polys[zid][0]['grapplable'] is not False),
                                     ('not convex', not is_convex(zone)), ('inside a fragment', zid in in_fragment)) if bad]
        for p in problems:
            fail('%s: no-grapple zone %s' % (zid, p))
        zone_rows.append({'id': zid, 'grapplable': polys[zid][0]['grapplable'], 'convex': is_convex(zone),
                          'internalPairs': sorted([p['a'], p['b']] for p in pairs if p['noGrappleZone'] == zid),
                          'pass': not problems})

    summary = {
        'pass': not failures, 'failures': len(failures),
        'transfers': len(transfers), 'transfersPass': sum(t['pass'] for t in transfers),
        'maxTransferPercentError': r(max((t['percentErrors'][k] for t in transfers for k in PERCENT_KEYS
                                          if t['percentErrors'][k] is not None), default=None), 9),
        'maxTransferDistanceError': r(max((t['percentErrors']['referenceDistance'] for t in transfers
                                           if t['percentErrors']['referenceDistance'] is not None), default=None), 9),
        'expectedFragmentPairs': len(reference['fragments']) * (len(reference['fragments']) - 1) // 2,
        'fragmentPairs': len(pairs), 'pairsPass': sum(p['pass'] for p in pairs),
        'minPairClearanceMinusDiameter': r(min((p['clearanceMinusDiameter'] for p in pairs), default=None)),
        'yellowPairs': len(drag_pairs), 'yellowPairsPass': sum(p['pass'] for p in drag_pairs),
        'minYellowPairClearance': r(min((p['clearance'] for p in drag_pairs), default=None)),
        'dragZones': len(drags), 'dragZonesPass': sum(d['pass'] for d in drags),
        'minDragSolidClearance': r(min((d['minSolidClearance'] for d in drags), default=None)),
        'anglePolygons': len(angle_rows), 'anglePolygonsPass': sum(a['pass'] for a in angle_rows),
        'angleVertices': sum(len(a['angles']) for a in angle_rows),
        'minInteriorAngle': r(min((a['minAngle'] for a in angle_rows if a['minAngle'] is not None), default=None), 9),
        'solidElements': len(solid),
        'noGrappleZones': len(zone_rows), 'noGrappleZonesPass': sum(z['pass'] for z in zone_rows),
        'noGrappleInternalPairs': sum(p['rule'] == 'noGrappleInternal' for p in pairs),
        'solidBounceGrapplable': sum(polys[eid][0]['role'] == 'bounce' and polys[eid][0]['grapplable'] is True
                                     for eid, _ in solid),
        'maxBodiesPerFragment': max((len(eids) for eids in fragments.values()), default=0),
        'yellowMergedFrom': {b['id']: b.get('mergedFrom', [b['id']]) for b in reference.get('yellowBands', [])},
        'fragments': len(frag_rows), 'maxFragmentCoordError': r(frag_max, 9), 'maxSvgCoordError': r(svg_max, 9),
    }
    summary.update(side_summary(sides, MIN_SIDE_LENGTH if min_side is None else min_side, min_side is not None))
    rest = None
    if no_grapple_rest:
        rest, rest_summary = check_rest(polys, zones, fragments, names, fail)
        summary.update(rest_summary)
        summary['pass'], summary['failures'] = not failures, len(failures)
    report = {'grappleRange': GRAPPLE_RANGE, 'playerDiameter': PLAYER_DIAMETER, 'coordTolerance': COORD_TOL,
            'percentTolerance': PERCENT_TOL, 'summary': summary, 'failureMessages': failures,
            'minInteriorAngle': MIN_INTERIOR_ANGLE, 'angleTolerance': ANGLE_TOL_DEG, 'angles': angle_rows,
            'transfers': transfers, 'pairs': pairs, 'dragZones': drags, 'yellowPairs': drag_pairs, 'fragments': frag_rows,
            'noGrappleZones': zone_rows, 'noGrappleInternalGap': NO_GRAPPLE_INTERNAL_GAP, 'sides': sides}
    if rest is not None:
        report['noGrappleRest'] = rest
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Recompute level geometry clearances and compare to references.')
    parser.add_argument('--svg', help='level SVG (format v1); required unless --sides-only')
    parser.add_argument('--level', required=True, help='imported level JSON (tools/import_level_svg.py output)')
    parser.add_argument('--report', required=True, help='report JSON to write')
    parser.add_argument('--reference', default=DEFAULT_REFERENCE, help='reference measurements JSON')
    sides = parser.add_mutually_exclusive_group()
    sides.add_argument('--min-side-length', type=float, nargs='?', const=MIN_SIDE_LENGTH, default=MIN_SIDE_LENGTH,
                       metavar='UNITS', help='fail gameplay polygon edges shorter than UNITS (default %g, also when '
                       'given without a value)' % MIN_SIDE_LENGTH)
    sides.add_argument('--no-min-side-length', dest='min_side_length', action='store_const', const=None,
                       help='inventory sides only (legacy layouts before v16)')
    parser.add_argument('--sides-only', action='store_true',
                        help='only side, corner and self-intersection checks from --level (no SVG/reference)')
    parser.add_argument('--no-grapple-rest', action='store_true',
                        help='also fail upward solid/bounce faces inside no-grapple zones sloped below %g deg, and '
                        'pockets between two of them (opt-in)' % NO_GRAPPLE_REST_SLOPE)
    args = parser.parse_args(argv)
    if args.sides_only and args.no_grapple_rest:
        parser.error('--no-grapple-rest needs the full check (not --sides-only)')
    if not args.sides_only and not args.svg:
        parser.error('--svg is required unless --sides-only')
    if args.min_side_length is not None and not (math.isfinite(args.min_side_length) and args.min_side_length > 0):
        parser.error('--min-side-length must be a positive finite number')
    with open(args.level) as f:
        level = json.load(f)
    if args.sides_only:
        report = check_sides(level, args.min_side_length)
    else:
        with open(args.svg, 'rb') as f:
            svg_data = f.read()
        with open(args.reference) as f:
            reference = json.load(f)
        report = check(level, svg_data, reference, args.min_side_length, args.no_grapple_rest)
    with open(args.report, 'w') as f:
        json.dump(report, f, separators=(',', ':'))
        f.write('\n')
    s = report['summary']
    for message in report['failureMessages']:
        print('FAIL ' + message, file=sys.stderr)
    sides = 'sides=%d violations=%d min_side=%s min_side_rule=%s' % (
        s['sideEdges'], s['sideViolations'], s['minMeasuredSide'],
        s['minSideLength'] if s['minSideEnforced'] else 'off')
    if args.sides_only:
        print('SIDES_RESULT %s %s angles=%d/%d min_angle=%s' % (
            'PASS' if s['pass'] else 'FAIL', sides, s['anglePolygonsPass'], s['anglePolygons'], s['minInteriorAngle']))
    else:
        print('GEOMETRY_RESULT %s transfers=%d/%d pairs=%d/%d drag=%d/%d fragments=%d max_percent_error=%s '
              'min_pair_margin=%s min_drag_clearance=%s angles=%d/%d min_angle=%s %s' % (
                  'PASS' if s['pass'] else 'FAIL', s['transfersPass'], s['transfers'], s['pairsPass'],
                  s['fragmentPairs'], s['dragZonesPass'], s['dragZones'], s['fragments'], s['maxTransferPercentError'],
                  s['minPairClearanceMinusDiameter'], s['minDragSolidClearance'], s['anglePolygonsPass'],
                  s['anglePolygons'], s['minInteriorAngle'], sides)
              + (' rest_faces=%d rest_violations=%d rest_pockets=%d min_rest_angle=%s' % (
                  s['noGrappleRestFaces'], s['noGrappleRestFaceViolations'], s['noGrappleRestPockets'],
                  s['minNoGrappleRestAngle']) if args.no_grapple_rest else ''))
    return 0 if s['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
