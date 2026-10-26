"""Runtime rest-drop probe for no-grapple (purple) zones. Measurement only.

For every upward solid/bounce face overlapping a no-grapple zone (the faces of
check_level_geometry.rest_faces), the part of the face inside its zone is sampled
at both ends and at most every --spacing units. The player is placed at rest
just above each sample (outward normal, radius + 0.5) and production physics is
stepped with no input for --seconds of game time. Outcome per sample:
  stuck  - never left the zone and, over the final --still-seconds of the run, every position fits in
           a box of side --still-speed * --still-seconds (window speed below --still-speed units/s);
           'tick' is the first tick of that rest (end of its first still window)
  left   - the player circle no longer overlaps any no-grapple zone
  moving - neither within the time budget
Usage: python3 tools/probe_purple_rest.py LEVEL_DIR --output stuck.json [--violations report.json]
       [--level-name big-zone.level.json --measurements-name big-zone-measurements.json]
"""
import argparse, json, math
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from browser_test_support import start_browser_test, wait_for_boot_run
import check_level_geometry as geo

ROOT = Path(__file__).resolve().parent.parent
LEVEL = 'extended-mountain.level.json'
MEASUREMENTS = 'extended-mountain-measurements.json'


def clip(a, b, zone):
    """Parameter range [t0, t1] of segment a-b inside the convex zone (None when outside)."""
    o = 1.0 if geo.signed_area(zone) > 0 else -1.0
    t0, t1 = 0.0, 1.0
    for p, q in geo.edges(zone):
        fa, fb = o * geo.cross(p, q, a), o * geo.cross(p, q, b)
        if fa < 0 and fb < 0:
            return None
        if fa < 0:
            t0 = max(t0, fa / (fa - fb))
        elif fb < 0:
            t1 = min(t1, fa / (fa - fb))
    return (t0, t1) if t1 > t0 else None


def samples(level_dir, spacing, level_name=LEVEL, measurements_name=MEASUREMENTS):
    level = json.loads((level_dir / level_name).read_text())
    ref_path = level_dir / measurements_name
    reference = json.loads(ref_path.read_text()) if ref_path.exists() else {}
    polys = geo.level_polygons(level)
    fragments = {f['id']: f['elements'] for f in level.get('svgFormat', {}).get('fragments', [])}
    names = {f['id']: f.get('semanticId') or f.get('name') for f in reference.get('fragments', [])}
    zones = [(eid, poly) for eid, (e, poly) in polys.items() if e['role'] == 'no-grapple']
    zone_poly = dict(zones)
    faces = geo.rest_faces(polys, zones, fragments, names)
    out = []
    for f in faces:
        poly = polys[f['element']][1]
        a, b = geo.edges(poly)[f['edge']]
        o = 1.0 if geo.signed_area(poly) > 0 else -1.0
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        nx, ny = o * dy / length, -o * dx / length
        t0, t1 = clip(a, b, zone_poly[f['zone']])
        n = max(1, math.ceil((t1 - t0) * length / spacing))
        ts = [t0 + (t1 - t0) * k / n for k in range(n + 1)]
        # vertex: the sample is a polygon corner (face end not clipped by the zone).
        pts = [(a[0] + dx * t, a[1] + dy * t, t in (0.0, 1.0)) for t in ts]
        out.append({'face': f, 'normal': (nx, ny), 'inZoneLength': (t1 - t0) * length, 'points': pts})
    return level, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('level_dir', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--violations', type=Path, help='check_level_geometry --no-grapple-rest report to cross-check')
    # TASK-707: other file names in LEVEL_DIR (the big-zone fixture writes big-zone.level.json ...).
    ap.add_argument('--level-name', default=LEVEL)
    ap.add_argument('--measurements-name', default=MEASUREMENTS)
    ap.add_argument('--spacing', type=float, default=150.0)
    ap.add_argument('--seconds', type=float, default=5.0)
    ap.add_argument('--still-speed', type=float, default=10.0)
    ap.add_argument('--still-seconds', type=float, default=1.0)
    a = ap.parse_args()
    level, faces = samples(a.level_dir, a.spacing, a.level_name, a.measurements_name)
    opts = {'seconds': a.seconds, 'stillSpeed': a.still_speed, 'stillSeconds': a.still_seconds}
    rows = []
    with ExitStack() as stack:
        url, b = start_browser_test(ROOT, stack.callback)
        p = b.new_page(viewport={'width': 1280, 'height': 720})
        p.goto(url); wait_for_boot_run(p)
        p.add_script_tag(path=str(ROOT / 'tools/probe_purple_rest.js'))
        p.evaluate('l=>PURPLE_REST.load(l)', level)
        for fc in faces:
            f, (nx, ny) = fc['face'], fc['normal']
            results = [dict(p.evaluate('([s,o])=>PURPLE_REST.drop(s,o)',
                                       [{'x': x, 'y': y, 'nx': nx, 'ny': ny}, opts]), at=[round(x, 2), round(y, 2)],
                            vertex=vertex)
                       for x, y, vertex in fc['points']]
            c = Counter(r['outcome'] for r in results)
            rows.append({'zone': f['zone'], 'element': f['element'], 'semantic': f['semantic'], 'edge': f['edge'],
                         'angle': f['angle'], 'geometryPass': f['pass'], 'a': f['a'], 'b': f['b'],
                         'inZoneLength': round(fc['inZoneLength'], 2), 'samples': len(results),
                         'stuck': c['stuck'], 'left': c['left'], 'moving': c['moving'],
                         'notStartedInZone': sum(not r['startInZone'] for r in results),
                         'stuckSamples': [r for r in results if r['outcome'] == 'stuck']})
            print(f['zone'], f['element'], 'edge', f['edge'], 'angle', f['angle'], dict(c), flush=True)
    zones = {}
    for r in rows:
        z = zones.setdefault(r['zone'], {'faces': 0, 'samples': 0, 'stuck': 0, 'left': 0, 'moving': 0})
        z['faces'] += 1
        for k in ('samples', 'stuck', 'left', 'moving'):
            z[k] += r[k]
    result = {'levelDir': str(a.level_dir), 'layoutId': level.get('layoutId'), 'options': dict(opts, spacing=a.spacing),
              'zones': zones, 'faces': rows,
              'totals': {k: sum(z[k] for z in zones.values()) for k in ('faces', 'samples', 'stuck', 'left', 'moving')}}
    if a.violations:
        bad = {(m['element'], m['edge']) for m in json.loads(a.violations.read_text())['noGrappleRest']['faces']
               if not m['pass']}
        result['crossCheck'] = {
            'violationsReport': str(a.violations), 'violatingFaces': sorted(f'{e}#{i}' for e, i in bad),
            'stuckFaces': sorted({f"{r['element']}#{r['edge']}" for r in rows if r['stuck']}),
            'stuckOutsideViolations': [{'element': r['element'], 'edge': r['edge'], 'angle': r['angle'], 'a': r['a'],
                                        'b': r['b'], 'stuckSamples': r['stuckSamples'],
                                        'allAtVertex': all(s['vertex'] for s in r['stuckSamples'])}
                                       for r in rows if r['stuck'] and (r['element'], r['edge']) not in bad]}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, separators=(',', ':')))
    print('totals', result['totals'], 'stuckOutsideViolations',
          len(result.get('crossCheck', {}).get('stuckOutsideViolations', [])))


if __name__ == '__main__':
    main()
