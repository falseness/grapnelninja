#!/usr/bin/env python3
"""Independent geometry checks for an imported level (level SVG format v1).

Recomputes every distance from the imported polygons. Recorded distances,
gap-percent attributes and printed labels are only ever the expected side of
a comparison, never the computed result (docs/level-svg-format.md §7).

    python3 tools/check_level_geometry.py --svg LEVEL.svg --level LEVEL.json --report REPORT.json \
        [--reference MEASUREMENTS.json]

Checks:
- level JSON polygons match the SVG geometry layer and the reference fragments
  and yellow bands within 0.01 unit;
- each transfer's computed gap percentage (minimum edge-to-edge distance
  between the two fragments' polygon unions / 540 * 100) matches the SVG
  gap-percent, the level JSON gapPercent and the reference percent within
  0.01 percentage point;
- every pair of distinct fragments keeps clearance - player diameter > 540,
  so no fragment can be grappled from another (no grapple shortcut);
- drag zones are axis-aligned horizontal non-grapplable rectangles with a
  minimum solid clearance >= 540.

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
PERCENT_TOL = 0.01
PERCENT_KEYS = ('svgGapPercent', 'levelGapPercent', 'referencePercent')
SVG = '{http://www.w3.org/2000/svg}'
GN = '{urn:grapnelninja:level-svg:1}'
DEFAULT_REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'artifacts', 'level',
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

def check(level, svg_data, reference):
    failures = []
    fail = failures.append
    polys = level_polygons(level)
    svg_shapes, svg_percents = svg_geometry(svg_data)
    fmt = level['svgFormat']
    if fmt.get('grappleRange') != GRAPPLE_RANGE:
        fail('grappleRange %r != 540' % fmt.get('grappleRange'))
    fragments = {f['id']: f['elements'] for f in fmt['fragments']}
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

    # All distinct fragment pairs: no grapple shortcut.
    ref_pairs = {frozenset((p['source'], p['target'])): p['minimumGap'] for p in reference.get('pairChecks', [])}
    transfer_pairs = {frozenset((t['from'], t['to'])) for t in fmt['transfers']}
    pairs = []
    for a, b in itertools.combinations(sorted(fragments, key=lambda s: int(s[1:]) if s[1:].isdigit() else s), 2):
        d, _, relation, _ = union_distance(frag_polys[a], frag_polys[b])
        margin = d - PLAYER_DIAMETER
        ref_gap = ref_pairs.get(frozenset((a, b)))
        ok = margin > GRAPPLE_RANGE
        if not ok:
            fail('pair %s/%s: clearance %.6f - %.1f = %.6f <= 540 (grapple shortcut)' % (
                a, b, d, PLAYER_DIAMETER, margin))
        ref_err = None if ref_gap is None else abs(d - ref_gap)
        if ref_err is not None and ref_err > COORD_TOL:
            fail('pair %s/%s: clearance %.6f vs reference %.6f' % (a, b, d, ref_gap))
        pairs.append({'a': a, 'b': b, 'transfer': frozenset((a, b)) in transfer_pairs, 'relation': relation,
                      'clearance': r(d), 'clearanceMinusDiameter': r(margin), 'referenceGap': r(ref_gap),
                      'referenceError': r(ref_err, 9), 'pass': ok and (ref_err is None or ref_err <= COORD_TOL)})

    # Drag zones.
    ref_bands = {b['id'] + '-drag': b for b in reference.get('yellowBands', [])}
    solid = [(eid, poly) for eid, (e, poly) in polys.items() if e['role'] != 'drag']
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
        if nearest[0] < GRAPPLE_RANGE:
            problems.append('solid clearance %.6f < 540 (%s)' % (nearest[0], nearest[1]))
        row['pass'] = not problems
        for p in problems:
            fail('%s: %s' % (eid, p))
        drags.append(row)
    if len(drags) != 6:
        fail('%d drag zones, expected 6' % len(drags))
    if set(d['id'] for d in drags) != set(ref_bands):
        fail('drag ids differ from reference bands: %s' % sorted(set(d['id'] for d in drags) ^ set(ref_bands)))

    summary = {
        'pass': not failures, 'failures': len(failures),
        'transfers': len(transfers), 'transfersPass': sum(t['pass'] for t in transfers),
        'maxTransferPercentError': r(max((t['percentErrors'][k] for t in transfers for k in PERCENT_KEYS
                                          if t['percentErrors'][k] is not None), default=None), 9),
        'maxTransferDistanceError': r(max((t['percentErrors']['referenceDistance'] for t in transfers
                                           if t['percentErrors']['referenceDistance'] is not None), default=None), 9),
        'fragmentPairs': len(pairs), 'pairsPass': sum(p['pass'] for p in pairs),
        'minPairClearanceMinusDiameter': r(min((p['clearanceMinusDiameter'] for p in pairs), default=None)),
        'dragZones': len(drags), 'dragZonesPass': sum(d['pass'] for d in drags),
        'minDragSolidClearance': r(min((d['minSolidClearance'] for d in drags), default=None)),
        'fragments': len(frag_rows), 'maxFragmentCoordError': r(frag_max, 9), 'maxSvgCoordError': r(svg_max, 9),
    }
    return {'grappleRange': GRAPPLE_RANGE, 'playerDiameter': PLAYER_DIAMETER, 'coordTolerance': COORD_TOL,
            'percentTolerance': PERCENT_TOL, 'summary': summary, 'failureMessages': failures,
            'transfers': transfers, 'pairs': pairs, 'dragZones': drags, 'fragments': frag_rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Recompute level geometry clearances and compare to references.')
    parser.add_argument('--svg', required=True, help='level SVG (format v1)')
    parser.add_argument('--level', required=True, help='imported level JSON (tools/import_level_svg.py output)')
    parser.add_argument('--report', required=True, help='report JSON to write')
    parser.add_argument('--reference', default=DEFAULT_REFERENCE, help='reference measurements JSON')
    args = parser.parse_args(argv)
    with open(args.svg, 'rb') as f:
        svg_data = f.read()
    with open(args.level) as f:
        level = json.load(f)
    with open(args.reference) as f:
        reference = json.load(f)
    report = check(level, svg_data, reference)
    with open(args.report, 'w') as f:
        json.dump(report, f, separators=(',', ':'))
        f.write('\n')
    s = report['summary']
    for message in report['failureMessages']:
        print('FAIL ' + message, file=sys.stderr)
    print('GEOMETRY_RESULT %s transfers=%d/%d pairs=%d/%d drag=%d/%d fragments=%d max_percent_error=%s '
          'min_pair_margin=%s min_drag_clearance=%s' % (
              'PASS' if s['pass'] else 'FAIL', s['transfersPass'], s['transfers'], s['pairsPass'],
              s['fragmentPairs'], s['dragZonesPass'], s['dragZones'], s['fragments'], s['maxTransferPercentError'],
              s['minPairClearanceMinusDiameter'], s['minDragSolidClearance']))
    return 0 if s['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
