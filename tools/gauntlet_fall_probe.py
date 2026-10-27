#!/usr/bin/env python3
"""No-input fall probe for the SEC-ext-summit gauntlet (TASK-742): does a failed jump fall through yellow onto geometry?

The gauntlet copy of tools/ext_summit_fall_probe.py (same production run: the player is placed at rest at each point,
then physics() once per tick with no input, in the real index.html on importedMountainLevel(); the fall ends at the
first upward contact, ny < -0.3; reaching the below-spawn fall recovery first is a void fall). Drop points come from
extSummit.gauntlet: on every zone's exit side (just past the exit ledge's outer end, further out over the column, and
in the slot between the zone and the exit ledge) and in every safe-space gap where a missed grapple falls (under both
sides and the middle of each grapple panel, and the middle of each climb transfer's flight line). A point outside the
map width (extSummit.xRange, x -1100..62534 in level-guidelines.md; beside a panel that reaches the map edge) is listed
under outsideMap, not dropped. Each drop also
records every yellow (drag) rectangle the player circle overlaps before the landing, in order.

    python3 tools/gauntlet_fall_probe.py --level-dir DIR --out FALLS.json [--budget TICKS] [--after TICKS]
Exit 0 when there are >= 40 drops, every drop lands on a solid/bounce element above the recovery depth before any
recovery with no rope thrown, and >= 50% of the drops pass through a yellow rectangle before landing; 1 otherwise.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from ext_summit_fall_probe import NAMES, PROBE as BASE_PROBE, RECOVERY_DEPTH, SIDE_GAP, inside_solid  # noqa: E402

MIN_DROPS, MIN_YELLOW_SHARE = 40, 0.5
OUT_OVER = 300.0  # the "further out" exit-side drop, past the exit ledge's outer end

# The base probe plus a per-tick record of the yellow rectangles the player circle overlaps before the landing.
_TICK = 'physics(); tick++'
_RECORD = ('physics(); tick++\n                if (!landing) for (const d of o.drags) if (ninja.x + 10.8 > d[1] && ninja.x - 10.8 < d[3] && '
           'ninja.y + 10.8 > d[2] && ninja.y - 10.8 < d[4] && !yellow.includes(d[0])) yellow.push(d[0])')
assert BASE_PROBE.count(_TICK) == 1 and BASE_PROBE.count('const trail = []') == 1 and BASE_PROBE.count('maxY: +maxY.toFixed(2), thrown}') == 1
PROBE = BASE_PROBE.replace(_TICK, _RECORD).replace('const trail = []', 'const trail = [], yellow = []') \
    .replace('maxY: +maxY.toFixed(2), thrown}', 'maxY: +maxY.toFixed(2), thrown, yellow}')


def drop_points(m, level=None):
    """Probe points (kind, of, side, x, y) on the gauntlet's zone exit sides and safe-space gaps."""
    g = m['extSummit']['gauntlet']
    pts = []
    for z in g['zones']:
        e, r = z['exit'], z['rect']
        right = z['direction'] == 'RIGHT'          # the exit ledge sits past the zone's right side
        y = e['y0'] - SIDE_GAP / 2
        outer = e['x1'] + SIDE_GAP if right else e['x0'] - SIDE_GAP
        slot = (r['x'] + r['width'] + e['x0']) / 2 if right else (e['x1'] + r['x']) / 2
        pts.append(dict(kind='zoneExit', of=z['id'], side='pastExitLedge', x=outer, y=y))
        pts.append(dict(kind='zoneExit', of=z['id'], side='farPastExitLedge', x=outer + (OUT_OVER if right else -OUT_OVER), y=y))
        pts.append(dict(kind='zoneExit', of=z['id'], side='zoneLedgeSlot', x=slot, y=y))
    for s in g['safeSpaces']:
        for k, p in enumerate(s['grapplePanels'], 1):
            y = p['y1'] + SIDE_GAP
            for side, x in (('left', p['x0'] - SIDE_GAP), ('under', (p['x0'] + p['x1']) / 2), ('right', p['x1'] + SIDE_GAP)):
                pts.append(dict(kind='safeSpace', of='%s-G%d' % (s['id'], k), side=side, x=x, y=y))
    fs = {f['id']: f for f in m['fragments']}
    for r in m['encounters']:
        if r['id'] not in m['extSummit']['encounters'] or r.get('noGrappleZone') or r['id'].endswith(('-CROSS', '-ENTRY', '-EXIT')):
            continue
        (ax, ay), (bx, by) = r['flight']
        for t in (0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65, 0.3, 0.7):
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            if not level or not inside_solid(level, x, y):
                break
        pts.append(dict(kind='midGap', of=r['id'], side='%s->%s' % (fs[r['fromFragment']]['semanticId'], fs[r['toFragment']]['semanticId']),
                        x=x, y=y, t=t))
    for p in pts:
        p['x'], p['y'] = round(p['x'], 3), round(p['y'], 3)
    return pts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--level-dir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--budget', type=int, default=20000)
    ap.add_argument('--after', type=int, default=600, help='ticks followed after the landing (outcome only, not a pass condition)')
    a = ap.parse_args()
    d = Path(a.level_dir)
    level, m = (json.loads((d / n).read_text()) for n in NAMES)
    pts = drop_points(m, level)
    bl, br = m['extSummit']['xRange']
    outside = [p for p in pts if not bl <= p['x'] <= br]
    pts = [p for p in pts if bl <= p['x'] <= br]
    bad_start = [dict(p, overlaps=e) for p in pts for e in [inside_solid(level, p['x'], p['y'])] if e]
    drags = []
    for e in level['elements']:
        if e['role'] == 'drag':
            xs = [e['x'] + q['x'] for q in e['points']]; ys = [e['y'] + q['y'] for q in e['points']]
            drags.append([e['id'], min(xs), min(ys), max(xs), max(ys)])
    from browser_test_support import start_browser_test, wait_for_boot_run
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        wait_for_boot_run(page)
        page.add_script_tag(path=str(TOOLS / 'opening_combination_replay.js'))
        res = page.evaluate(PROBE, dict(level=level, points=pts, budget=a.budget, after=a.after, drags=drags))
    ids = {f['id']: f.get('semanticId') or f['id'] for f in m['fragments']}
    roles = {e['id']: e['role'] for e in level['elements']}
    depth = res['spawn']['y'] + RECOVERY_DEPTH
    rows = []
    for r in res['rows']:
        land = r['landing']
        ok = r['recovered'] is None or (land is not None and land['tick'] < r['recovered']['tick'])
        ok = ok and land is not None and r['maxY'] < depth and land['y'] < depth and r['thrown'] == 0 and roles.get(land['id']) in ('solid', 'bounce')
        rows.append(dict(kind=r['kind'], of=r['of'], side=r['side'], start=[r['x'], r['y']], yellowBefore=r['yellow'],
                         throughYellow=bool(r['yellow']), landingElement=land and land['id'],
                         landingFragment=land and ids.get(land['id'].split('-')[0]), landingRole=land and roles.get(land['id']),
                         landingY=land and land['y'], landingTick=land and land['tick'], fallDepth=land and round(land['y'] - r['y'], 2),
                         void=land is None, afterLanding=r['after'], final=r['final'], **{'pass': bool(ok)}))
    through = sum(r['throughYellow'] for r in rows)
    kinds = {k: sum(r['kind'] == k for r in rows) for k in ('zoneExit', 'safeSpace', 'midGap')}
    summary = dict(drops=len(rows), byKind=kinds, voidFalls=sum(r['void'] for r in rows), failed=sum(not r['pass'] for r in rows),
                   invalidStarts=len(bad_start), outsideMap=len(outside), throughYellow=through, throughYellowShare=round(through / max(1, len(rows)), 4),
                   zonesCovered=sorted({r['of'] for r in rows if r['kind'] == 'zoneExit'}),
                   safeSpacesCovered=sorted({r['of'].split('-')[0] for r in rows if r['kind'] == 'safeSpace'}),
                   yellowHits={y[0]: sum(y[0] in r['yellowBefore'] for r in rows) for y in drags},
                   maxLandingTick=max((r['landingTick'] or 0) for r in rows), recoveryDepthY=depth, pageErrors=errors)
    summary['pass'] = summary['failed'] == 0 and summary['voidFalls'] == 0 and not bad_start and not errors and \
        len(rows) >= MIN_DROPS and through >= MIN_YELLOW_SHARE * len(rows) and \
        len(summary['zonesCovered']) == len(m['extSummit']['gauntlet']['zones'])
    hashes = {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in NAMES}
    out = dict(method=__doc__.split('\n\n')[1].replace('\n', ' '), levelDir=str(d), layoutId=res['layoutId'], levelHashes=hashes,
               budget=a.budget, after=a.after, summary=summary, invalidStarts=bad_start, outsideMap=outside, drops=rows)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + '\n')
    print('GAUNTLET_FALL_PROBE %s drops=%d void=%d failed=%d invalidStarts=%d outsideMap=%d throughYellow=%d (%.1f%%) zones=%s byKind=%s' % (
        'PASS' if summary['pass'] else 'FAIL', len(rows), summary['voidFalls'], summary['failed'], len(bad_start), len(outside), through,
        100 * summary['throughYellowShare'], ','.join(summary['zonesCovered']), kinds))
    for r in rows:
        if not r['pass'] or not r['throughYellow']:
            print('  %s %s %s %s %s -> %s y=%s yellow=%s' % ('FAIL' if not r['pass'] else 'noYellow', r['kind'], r['of'], r['side'],
                                                          r['start'], r['landingFragment'], r['landingY'], r['yellowBefore']))
    return 0 if summary['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
