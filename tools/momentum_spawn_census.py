"""Momentum spawn census (TASK-111): which frames MomentumObstacleFloor
spawns since it switched to the user's picked M frames (MOMENTUM_FRAMES_H,
MOMENTUM_FRAMES_V, MOMENTUM_FRAMES_TURN).

Seeds 1..8 at 1280x720 and seeds 1..4 at 390x844: a fresh page each,
Math.random seeded (test_momentum_run's generator), momentum started with the
rAF loop stopped and 90 s driven with test_momentum_run's DRIVE (the ninja
put on the course centre line DRIVE_SPEED * height further every frame,
invulnerable, hp topped up; no autopilot). Every spawned group is recorded at
spawn: id, kind (horizontal / vertical / corner), dir (a direction or a
join). Its pieces are checked then:
- outside: a piece box not covered by the union of the corridor interiors
  (the boxes between each generated segment's border lines,
  momentumSegmentBorderLines; test_momentum_pieces_inside's area check);
- gap: the shortest box distance from each piece (with its motion range:
  axis x the [xMin, xMax] sweep, axis y the [yMin, yMax] one) to every piece
  of every other group on the floor, in corridor W
  (2 * GAMEPLAY.momentumBorders.halfWidth).
Each vertical stretch the spawner planned is listed with its length and the
frames that fit it (for census-notes.md).

At 1280x720 the run also takes in-game screenshots with the seeded state
restored (test_momentum_run's DRAW): right.png (a right segment from second
5 on with >= 3 pieces in view), down.png / up.png (DRIVE's want: >= 2
pieces of that shaft's frames in view with the camera moving) and
corner-<id>.png for the first three different corner frames whose vertex
and all pieces are in view (DRIVE's want.turn).

MOMENTUM_CENSUS_OUT (default artifacts/TASK-111) receives census.json
(compact {perSeed: [{seed, viewport, ids: {id: count}, byDir: {dir: {id:
count}}, spawns, shafts}], totals, totalsByDir, badFrameSpawns,
minInterFrameGapW, minGapPair, outsidePieces, outside, errors}) and
shots/. Prints one line per run and a summary. Exit status 1 when a bad
frame spawned, a piece is outside or a page error occurred.
Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402
from test_momentum_run import DRAW, DRIVE, DRIVE_SPEED, FPS, VISIBLE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('MOMENTUM_CENSUS_OUT', ROOT / 'artifacts/TASK-111'))
SECONDS = 90
RUNS = [(seed, (1280, 720)) for seed in range(1, 9)] + [(seed, (390, 844)) for seed in range(1, 5)]
if os.environ.get('MOMENTUM_CENSUS_RUNS'):
    # Smoke runs: 'seed:WxH,...'
    RUNS = [(int(r.split(':')[0]), tuple(int(v) for v in r.split(':')[1].split('x')))
            for r in os.environ['MOMENTUM_CENSUS_RUNS'].split(',')]
CORNER_SHOTS = 3

# test_momentum_run's SETUP without its onSpawn (that one looks the ids up in
# the old turn registry); this one records the census per spawn
SETUP = '''(seed) => {
    let a = seed >>> 0
    Math.random = () => {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    window.runRngState = (v) => v === undefined ? a : (a = v)
    window.lethalCalls = 0
    window.runFrame = 0
    window.runTurns = []
    window.runShaftGroups = {}
    window.census = {spawns: [], outside: [], minGap: Infinity, minGapPair: null}
    const W = 2 * GAMEPLAY.momentumBorders.halfWidth
    const sweep = e => {
        const b = getElementBounds(e)
        const box = {l: b.left, r: b.right, t: b.top, b: b.bottom}
        if (e.motion && e.motion.axis == 'x') { box.l = e.motion.xMin; box.r = e.motion.xMax }
        else if (e.motion) { box.t = e.getMotionBound('yMin'); box.b = e.getMotionBound('yMax') }
        return box
    }
    const ids = {}
    MomentumObstacleFloor.onSpawn = (s) => {
        const floor = floors.find(f => f instanceof MomentumObstacleFloor)
        ids[s.group.id] = s.id
        if (s.kind == 'corner')
            runTurns.push({group: s.group.id, id: s.id, vertex: floor.plan.vertex})
        if (s.kind == 'vertical')
            runShaftGroups[s.group.id] = s.dir
        census.spawns.push([Math.round(runFrame / 6) / 10, s.id, s.kind, s.dir])
        const mine = floor.elements.filter(e => e.generationGroupId === s.group.id)
        // Corridor interiors of the segments generated so far (generating
        // more would draw Math.random)
        const course = momentumCourse
        const corridors = []
        for (let j = 0; j + 1 < course.segments.length; ++j) {
            const pts = momentumSegmentBorderLines(course, j).flatMap(l => [{x: l.x0, y: l.y0}, {x: l.x1, y: l.y1}])
            corridors.push({l: Math.min(...pts.map(p => p.x)), r: Math.max(...pts.map(p => p.x)),
                            t: Math.min(...pts.map(p => p.y)), b: Math.max(...pts.map(p => p.y))})
        }
        for (const e of mine) {
            const p = sweep(e)
            const rects = corridors.map(c => ({l: Math.max(c.l, p.l), r: Math.min(c.r, p.r),
                                               t: Math.max(c.t, p.t), b: Math.min(c.b, p.b)}))
                .filter(r => r.l < r.r && r.t < r.b)
            const xs = [...new Set([p.l, p.r, ...rects.flatMap(r => [r.l, r.r])])].sort((a, b) => a - b)
            const ys = [...new Set([p.t, p.b, ...rects.flatMap(r => [r.t, r.b])])].sort((a, b) => a - b)
            let outside = 0
            for (let x = 0; x + 1 < xs.length; ++x)
                for (let y = 0; y + 1 < ys.length; ++y) {
                    const cx = (xs[x] + xs[x + 1]) / 2, cy = (ys[y] + ys[y + 1]) / 2
                    if (!rects.some(r => r.l < cx && cx < r.r && r.t < cy && cy < r.b))
                        outside += (xs[x + 1] - xs[x]) * (ys[y + 1] - ys[y])
                }
            // Rounding of the catalog W values: below 1 world unit^2 is none
            if (outside >= 1)
                census.outside.push([s.id, s.dir, Math.round(outside), [p.l, p.t, p.r, p.b].map(Math.round)])
            for (const o of floor.elements) {
                if (o.generationGroupId === s.group.id)
                    continue
                const q = sweep(o)
                const dx = Math.max(0, q.l - p.r, p.l - q.r), dy = Math.max(0, q.t - p.b, p.t - q.b)
                const gap = Math.hypot(dx, dy) / W
                if (gap < census.minGap) {
                    census.minGap = gap
                    census.minGapPair = [ids[o.generationGroupId], s.id, s.dir]
                }
            }
        }
    }
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    window.runArc = floor.getNinjaArc()
    return {W}
}'''

# The vertical stretches planned so far: dir, length and room (minus the join
# margins) in shaft W, and the frames of that direction fitting the room
SHAFTS = '''(() => {
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    const out = []
    for (let i = 1; i < floor.segmentIndex; ++i) {
        const s = momentumCourse.segment(i)
        if (s.dir == 'right' || momentumCourse.segment(i - 1).dir == s.dir)
            continue
        const last = floor.getStretchEnd(i)
        const hw = momentumSegmentHalfWidth(s), W = 2 * hw
        const length = floor.getArcStart(last + 1) - floor.getArcStart(i)
        const room = length - floor.getJoinMargin(momentumCourse.segment(i - 1)) -
            floor.getJoinMargin(momentumCourse.segment(last + 1))
        out.push([s.dir, +(length / W).toFixed(3), +(room / W).toFixed(3),
                  momentumPatternsByDir[s.dir].filter(id => momentumPatternFactories[id].getLength(hw) <= room)])
    }
    return out
})()'''


def count(ids):
    out = {}
    for i in ids:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


def run(browser, url, seed, viewport, shots, shots_dir):
    w, h = viewport
    context = browser.new_context(viewport={'width': w, 'height': h})
    errors = []
    try:
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(url)
        wait_for_boot_run(page)
        page.evaluate(SETUP, seed)
        step = page.evaluate('height') * DRIVE_SPEED
        shoot = viewport == (1280, 720)
        for second in range(SECONDS):
            left = FPS
            while left:
                want = {}
                if shoot:
                    want = {d: 2 for d in ('up', 'down') if f'{d}.png' not in shots}
                    corners = [n for n in shots if n.startswith('corner-')]
                    if len(corners) < CORNER_SHOTS:
                        # Only corner frames not shot yet
                        page.evaluate('(done) => { runTurns = runTurns.filter(t => !done.includes(t.id)) }',
                                      [n[len('corner-'):-len('.png')] for n in corners])
                        want['turn'] = True
                driven = page.evaluate(DRIVE, [left, step, want])
                left -= driven['frames']
                if driven['hit']:
                    name = f'{driven["hit"]}.png'
                    if driven['hit'] == 'turn':
                        name = 'corner-' + page.evaluate('''(() => {
                            const w = width / scale[version], h = height / scale[version]
                            const floor = floors.find(f => f instanceof MomentumObstacleFloor)
                            const inside = e => { const b = getElementBounds(e)
                                return b.left >= -screen.x && b.right <= -screen.x + w && b.top >= -screen.y && b.bottom <= -screen.y + h }
                            return runTurns.find(t => { const g = floor.elements.filter(e => e.generationGroupId === t.group)
                                const v = t.vertex
                                return v.x >= -screen.x && v.x <= -screen.x + w && v.y >= -screen.y && v.y <= -screen.y + h &&
                                    g.length && g.every(inside) }).id })()''') + '.png'
                    page.evaluate(DRAW)
                    page.screenshot(path=str(shots_dir / name))
                    shots[name] = {'seed': seed, 'second': round(page.evaluate('runFrame') / FPS, 2),
                                   'pieces': driven['pieces']}
            if (shoot and second >= 5 and 'right.png' not in shots and
                    page.evaluate('screen.getSegment().dir') == 'right' and page.evaluate(VISIBLE) >= 3):
                page.evaluate(DRAW)
                page.screenshot(path=str(shots_dir / 'right.png'))
                shots['right.png'] = {'seed': seed, 'second': second + 1, 'pieces': page.evaluate(VISIBLE)}
        census = page.evaluate('census')
        shafts = page.evaluate(SHAFTS)
    finally:
        context.close()
    return census, shafts, errors


def main():
    shots_dir = OUT / 'shots'
    shots_dir.mkdir(parents=True, exist_ok=True)
    cleanups = []
    url, browser = start_browser_test(ROOT, cleanups.append)
    per_seed, shots, all_errors, outside = [], {}, [], []
    min_gap, min_pair = float('inf'), None
    try:
        for seed, viewport in RUNS:
            census, shafts, errors = run(browser, url, seed, viewport, shots, shots_dir)
            ids = [s[1] for s in census['spawns']]
            by_dir = {}
            for s in census['spawns']:
                by_dir.setdefault(s[3], []).append(s[1])
            vp = f'{viewport[0]}x{viewport[1]}'
            per_seed.append({'seed': seed, 'viewport': vp, 'ids': count(ids),
                             'byDir': {d: count(l) for d, l in sorted(by_dir.items())},
                             'spawns': len(ids), 'shafts': shafts})
            outside += [[seed, vp] + o for o in census['outside']]
            all_errors += [[seed, vp, e] for e in errors]
            if census['minGap'] is not None and census['minGap'] < min_gap:
                min_gap, min_pair = census['minGap'], [seed, vp] + census['minGapPair']
            print(f'seed {seed} {vp}: {len(ids)} spawns, ids {count(ids)}, outside {len(census["outside"])}, '
                  f'min gap {census["minGap"]:.3f} W {census["minGapPair"]}, shafts {shafts}, errors {len(errors)}',
                  flush=True)
    finally:
        for cleanup in reversed(cleanups):
            cleanup()
    totals, totals_by_dir = {}, {}
    for r in per_seed:
        for i, n in r['ids'].items():
            totals[i] = totals.get(i, 0) + n
        for d, c in r['byDir'].items():
            for i, n in c.items():
                totals_by_dir.setdefault(d, {})[i] = totals_by_dir.setdefault(d, {}).get(i, 0) + n
    desktop = {}
    for r in per_seed:
        if r['viewport'] == '1280x720':
            for i, n in r['ids'].items():
                desktop[i] = desktop.get(i, 0) + n
    bad = sum(n for i, n in totals.items() if i.startswith('bad-'))
    out = {'perSeed': per_seed, 'totals': dict(sorted(totals.items())),
           'totals1280x720': dict(sorted(desktop.items())),
           'totalsByDir': {d: dict(sorted(c.items())) for d, c in sorted(totals_by_dir.items())},
           'badFrameSpawns': bad, 'minInterFrameGapW': round(min_gap, 4), 'minGapPair': min_pair,
           'outsidePieces': len(outside), 'outside': outside[:20], 'shots': shots, 'errors': all_errors[:20]}
    (OUT / 'census.json').write_text(json.dumps(out, separators=(',', ':')))
    print('totals', out['totals'])
    print('totals 1280x720', out['totals1280x720'])
    print('totalsByDir', out['totalsByDir'])
    print('badFrameSpawns', bad, 'outsidePieces', len(outside), 'minInterFrameGapW', out['minInterFrameGapW'],
          'pair', min_pair, 'errors', len(all_errors))
    print('shots', shots)
    return 1 if bad or outside or all_errors else 0


if __name__ == '__main__':
    sys.exit(main())
