#!/usr/bin/env python3
"""No-input fall probe for SEC-ext-summit (TASK-723): where does a failed jump in the extension land?

Drop points come from the level measurements (extSummit): beside both sides of every body of every extension panel
at its top height (ceilings: under their underside), beside each big zone's exit side (the zone's left edge, half-way down,
and just outside the exit ledge), and the middle of every transfer between consecutive panels outside a zone
(the flight line between the recorded contact points; the nearest free point along it when the middle is inside a body). The player is placed at rest at each point (the only
write, like a replay fixture), then production physics() runs once per tick with no input, in the real
index.html on the production importedMountainLevel(). The fall ends at the first upward contact (normal
ny < -0.3): that element is the landing; a drop that reaches the below-spawn fall recovery first is a void fall.
After the landing the run continues (--after ticks) only to record what follows (rest; stillOnLanding = the last
upward contact is still the landing element, e.g. bouncing on it; moving = on another element; laterRecovery =
bounced off into the recovery); that outcome is reported, not judged.

    python3 tools/ext_summit_fall_probe.py --level-dir DIR --out FALLS.json [--budget TICKS] [--after TICKS]
Exit 0 when every drop lands on a solid/bounce element above the recovery depth before any recovery, 1 otherwise.
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
NAMES = ('extended-mountain.level.json', 'extended-mountain-measurements.json')
RECOVERY_DEPTH = 1500  # physics.js CLIMB_FALL_RECOVERY_DEPTH
SIDE_GAP = 40.0        # drop point distance from a panel's bounding box (player radius 10.8)

PROBE = '''o => {
    let contacts = [], recovered = null, tick = 0
    const bounce = Ninja.prototype.applyBounce
    Ninja.prototype.applyBounce = function (c) { bounce.call(this, c); if (c.approaching) contacts.push({tick, id: c.element.id, nx: c.nx, ny: c.ny,
        x: +this.x.toFixed(2), y: +this.y.toFixed(2)}) }
    const recover = recoverClimbFall
    recoverClimbFall = function () { if (!recovered) recovered = {tick, x: +ninja.x.toFixed(2), y: +ninja.y.toFixed(2)}; return recover.apply(this, arguments) }
    const level = importedMountainLevel(structuredClone(o.level)), out = []
    try {
        for (const p of o.points) {
            floors = [loadFixedLevel(structuredClone(level))]
            floors[0].doubleOfferShown = true; floors[0].fallHintShown = true
            grapnel = new Grapnel({stroke: STYLE.colors.player.cyan})
            ninja = new Ninja({x: p.x, y: p.y, radius: 10.8, fill: STYLE.colors.player.cyan})
            ninja.speedX = ninja.speedY = 0
            pressHeld = stalePress = gameplayPressOwned = false; menu.gamePaused = false; hostPaused = false; unTouch = false
            screen.trackGrappleOver(true)
            contacts = []; recovered = null; tick = 0
            let landing = null, landedAt = null, maxY = p.y, thrown = 0, after = null
            const trail = []
            while (tick < o.budget && !recovered) {
                physics(); tick++
                if (grapnel.throwed) thrown++
                if (!landing) {
                    maxY = Math.max(maxY, ninja.y)
                    landing = contacts.find(k => k.ny < -0.3) || null
                    if (landing) landedAt = tick
                } else {
                    trail.push([ninja.x, ninja.y]); if (trail.length > 60) trail.shift()
                    if (trail.length === 60 && Math.max(...trail.map(q => Math.hypot(q[0] - ninja.x, q[1] - ninja.y))) < 1) { after = 'rest'; break }
                    if (tick - landedAt >= o.after) { after = 'moving'; break }   // e.g. still bouncing (elastic contacts)
                }
            }
            if (landing && recovered) after = 'laterRecovery'
            const last = contacts.filter(k => k.ny < -0.3).at(-1) || null
            out.push({...p, ticks: tick, landedAt, recovered, landing: landing && {id: landing.id, tick: landing.tick, x: landing.x, y: landing.y},
                      after, afterElement: last && last.id, final: [+ninja.x.toFixed(2), +ninja.y.toFixed(2)], maxY: +maxY.toFixed(2), thrown})
        }
    } finally { Ninja.prototype.applyBounce = bounce; recoverClimbFall = recover }
    return {layoutId: level.layoutId, spawn: level.spawn, rows: out}
}'''


def drop_points(m, level=None):
    """Probe points (x, y, kind, of) for the extension in measurements m."""
    sys.path.insert(0, str(TOOLS))
    import convert_extended_mountain_svg as svg
    xs = m['extSummit']; fs = {f['id']: f for f in m['fragments']}
    ext = [fs[i] for i in xs['fragments']]
    zones = {z['id']: z for z in m['noGrappleZones'] if z['id'] in xs['zones']}
    pts = []
    for f in ext:
        for k, b in enumerate(svg.bodies(f)):
            x0, x1, y0, y1 = min(p[0] for p in b), max(p[0] for p in b), min(p[1] for p in b), max(p[1] for p in b)
            y = y1 + SIDE_GAP if f['kind'] == 'ceiling' and k == 0 else y0 - SIDE_GAP / 2
            tag = '' if k == 0 else 'body%d-' % k
            for side, x in (('left', x0 - SIDE_GAP), ('right', x1 + SIDE_GAP)):
                pts.append(dict(kind='panel', of=f['semanticId'], side=tag + side, x=round(x, 3), y=round(y, 3)))
            if f['kind'] == 'ceiling' and k == 0:
                pts.append(dict(kind='panel', of=f['semanticId'], side='under', x=round((x0 + x1) / 2, 3), y=round(y, 3)))
    for zid, z in zones.items():
        exit_ = next(f for f in ext if f['semanticId'] == zid + '-EXIT')
        pts.append(dict(kind='zoneExit', of=zid, side='zoneLeftEdge', x=round(z['x'] - SIDE_GAP, 3), y=round(z['y'] + z['height'] / 2, 3)))
        pts.append(dict(kind='zoneExit', of=zid, side='pastExitLedge', x=round(exit_['x'] - SIDE_GAP, 3), y=round(exit_['y'] - SIDE_GAP / 2, 3)))
    # A point inside the finish region would complete the run (physics freezes); start it just below that region.
    s = fs[xs['summit']]; fl, fr, ft, fb = s['x'] - svg.FINISH_PAD[0], s['x'] + s['width'] + svg.FINISH_PAD[0], s['y'] - svg.FINISH_PAD[1], s['y']
    for p in pts:
        if fl <= p['x'] <= fr and ft <= p['y'] <= fb:
            p['y'] = round(fb + SIDE_GAP / 2, 3); p['side'] += '-belowFinish'
    for r in m['encounters']:
        if r['id'] not in xs['encounters'] or r.get('noGrappleZone'):
            continue
        (ax, ay), (bx, by) = r['flight']
        # The middle of the flight line, or the nearest free point along it when the middle is inside a body.
        for t in (0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65, 0.3, 0.7, 0.25, 0.75, 0.2, 0.8):
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            if not level or not inside_solid(level, x, y):
                break
        pts.append(dict(kind='midGap', of=r['id'], side='%s->%s' % (fs[r['fromFragment']]['semanticId'], fs[r['toFragment']]['semanticId']),
                        x=round(x, 3), y=round(y, 3), t=t))
    return pts


def inside_solid(level, x, y, r=10.8):
    """True when the player circle at (x, y) overlaps a solid/bounce body (an invalid drop point)."""
    def seg(px, py, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]; t = max(0, min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy or 1)))
        return ((px - a[0] - t * dx) ** 2 + (py - a[1] - t * dy) ** 2) ** .5
    for e in level['elements']:
        if e['role'] in ('no-grapple', 'drag', 'decoration'):
            continue
        poly = [(e['x'] + p['x'], e['y'] + p['y']) for p in e['points']]
        n, c = len(poly), False
        for i in range(n):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                c = not c
        if c or min(seg(x, y, poly[i], poly[(i + 1) % n]) for i in range(n)) < r:
            return e['id']
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--level-dir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--budget', type=int, default=20000)
    ap.add_argument('--after', type=int, default=1500, help='ticks followed after the landing (outcome only, not a pass condition)')
    a = ap.parse_args()
    d = Path(a.level_dir)
    level, m = (json.loads((d / n).read_text()) for n in NAMES)
    pts = drop_points(m, level)
    bad_start = [(p, inside_solid(level, p['x'], p['y'])) for p in pts]
    bad_start = [dict(p, overlaps=e) for p, e in bad_start if e]
    from browser_test_support import start_browser_test, wait_for_boot_run
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        wait_for_boot_run(page)
        page.add_script_tag(path=str(TOOLS / 'opening_combination_replay.js'))
        res = page.evaluate(PROBE, dict(level=level, points=pts, budget=a.budget, after=a.after))
    ids = {}
    for f in m['fragments']:
        ids[f['id']] = f.get('semanticId') or f['id']
    roles = {e['id']: e['role'] for e in level['elements']}
    depth = res['spawn']['y'] + RECOVERY_DEPTH
    rows = []
    for r in res['rows']:
        land = r['landing']
        # Pass: the fall ends on an element (first upward contact) of a solid/bounce role, above the recovery depth,
        # before any fall recovery, with no grapple thrown. What follows the landing is recorded, not judged.
        ok = r['recovered'] is None or (land is not None and land['tick'] < r['recovered']['tick'])
        ok = ok and land is not None and r['maxY'] < depth and land['y'] < depth and r['thrown'] == 0 and roles.get(land['id']) in ('solid', 'bounce')
        rows.append(dict(kind=r['kind'], of=r['of'], side=r['side'], start=[r['x'], r['y']], landingElement=land and land['id'],
                         landingFragment=land and ids.get(land['id'].split('-')[0]), landingRole=land and roles.get(land['id']),
                         landingY=land and land['y'], landingTick=land and land['tick'], fallDepth=land and round(land['y'] - r['y'], 2),
                         void=land is None, afterLanding=('stillOnLanding' if r['after'] == 'moving' and r['afterElement'] == land['id'] else r['after']),
                         afterFragment=r['afterElement'] and ids.get(r['afterElement'].split('-')[0]), final=r['final'],
                         pass_=bool(ok)))
    for r in rows:
        r['pass'] = r.pop('pass_')
    kinds = {k: sum(r['kind'] == k for r in rows) for k in ('panel', 'zoneExit', 'midGap')}
    ext_ids = set(m['extSummit']['fragments'])
    summary = dict(drops=len(rows), byKind=kinds, voidFalls=sum(r['void'] for r in rows), failed=sum(not r['pass'] for r in rows),
                   invalidStarts=len(bad_start), panelsCovered=len({r['of'] for r in rows if r['kind'] == 'panel'}), extensionPanels=len(ext_ids),
                   zonesCovered=sorted({r['of'] for r in rows if r['kind'] == 'zoneExit'}),
                   landingsOnExtension=sum(r['landingElement'] is not None and r['landingElement'].split('-')[0] in ext_ids for r in rows),
                   maxLandingTick=max((r['landingTick'] or 0) for r in rows), recoveryDepthY=depth,
                   afterLanding={k: sum(r['afterLanding'] == k for r in rows) for k in ('rest', 'stillOnLanding', 'moving', 'laterRecovery')}, pageErrors=errors)
    summary['pass'] = summary['failed'] == 0 and summary['voidFalls'] == 0 and not bad_start and not errors and \
        summary['panelsCovered'] == summary['extensionPanels'] and len(summary['zonesCovered']) == 3 and kinds['midGap'] > 0 and len(rows) >= 20
    hashes = {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in NAMES}
    out = dict(method=__doc__.split('\n\n')[1].replace('\n', ' '), levelDir=str(d), layoutId=res['layoutId'], levelHashes=hashes, budget=a.budget, after=a.after,
               summary=summary, invalidStarts=bad_start, drops=rows)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, separators=(',', ':')) + '\n')
    print('FALL_PROBE %s drops=%d void=%d failed=%d invalidStarts=%d panels=%d/%d zones=%s midGaps=%d landingsOnExtension=%d afterLanding=%s' % (
        'PASS' if summary['pass'] else 'FAIL', len(rows), summary['voidFalls'], summary['failed'], len(bad_start),
        summary['panelsCovered'], summary['extensionPanels'], ','.join(summary['zonesCovered']), kinds['midGap'],
        summary['landingsOnExtension'], summary['afterLanding']))
    for r in rows:
        if not r['pass']:
            print('  FAIL', r['kind'], r['of'], r['side'], r['start'], 'void' if r['void'] else '', r['landingFragment'], r['landingY'])
    return 0 if summary['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
