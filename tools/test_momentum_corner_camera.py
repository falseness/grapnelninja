"""Momentum camera on a corner shortcut (TASK-033 reproduction, TASK-034 fix, TASK-069 into shafts).

User report: "if we take a short cut on the corner, the camera moves too
soon". Course scripts right -> up -> right and right -> down -> right
(test_momentum_shaft_view) give the four joins right->up, up->right,
right->down and down->right. The corner box of a join is the square where
the two corridors overlap: the vertical segment's half width across x, the
right segment's half width across y, centred on the join point.

With the rAF loop stopped and the obstacle floor emptied, the ninja is
driven (invulnerable, one calcPhysics() per point, 0.9 * momentumMaxSpeed
apart) along the centre line up to the corner box, then diagonally through
it from the old corridor's centre line on the entry edge to the new
corridor's centre line on the exit edge (the shortcut), then on along the
next corridor. The earlier join of a course (right->up/down) is taken along
the centre lines, and the shaft is climbed long enough for the camera to
settle on it.

Into a shaft (right->up, right->down, right-up-inner), user decision of
TASK-069: "I would prefer it to change direction earlier. e.g. if there is a
tunnel down, i see nothing down and i have to go there blindly." This
overrides the TASK-033 "camera moves too soon on shortcuts" rule there: the
camera previews the shaft before and in the corner box
(GAMEPLAY.momentumCamera.preview), so per cycle of the whole drive the camera
motion along the next axis (velocityY) is never away from the shaft (away
0), and in the box it never goes past its old-axis cap (x past the shaft cap
getShaftCapX; pastCap 0).

Out of a shaft (up->right, down->right; TASK-034 until TASK-070), per cycle
while the ninja centre is inside the corner box (not yet past its exit edge
into the next corridor):
- the camera velocity along the next segment's axis (velocityX) is 0: no
  early horizontal scroll out of a shaft;
- the camera never goes past its cap along the old axis (y past the
  corridor-centred stop; once the camera is on the right segment, past its
  preview stop of a following shaft, MomentumScreen.getPreviewStop: the
  'up' script's right corridor after the shaft is shorter than a view, so
  the next up shaft's preview starts as the camera switches to it).

The camera switches to a turn's next segment (MomentumScreen.hasPassed) once
the ninja has left the corner box into the next corridor, or, in the box,
once the ninja's margin to the view edge ahead along the next axis drops
below GAMEPLAY.momentumCamera.holdMargin (holding on would let it run out of
the view; TASK-034 amended rule). So out of a shaft the camera must not move
along the next axis in the box before that margin drops below holdMargin, and
it must start later (the ninja closer to the next corridor, toNext) than on
8be0b76.

MOMENTUM_CORNER_CAMERA_EVIDENCE_DIR (default artifacts/TASK-034) receives
corner-trace.json ({join: {box, rows: [{cycle, nx, ny, camVx, camVy, seg, margin}]}}
for the cycles from 8 before the box to 24 after it: every 4th one, and every
one within 16 of the first early cycle or 8 of the box exit or the camera
start), corner-camera.json (per join summary: released, the first box cycle
with the margin below holdMargin; start, the first cycle from the box entry
with the camera moving along the next axis) and, at 1280x720 with the corner box and the ninja
marked in a DOM overlay (not drawn by the game), shots/<join>-1-enter.png
(the ninja enters the box), -2-mid.png (halfway to the camera start) and
-3-turn.png (the camera starts moving along the next axis) for the four
shortcut joins (none for the contrast case).
Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_camera import SEED_COURSE
from test_momentum_shaft_view import SCRIPTS

ROOT = Path(__file__).resolve().parents[1]
# Camera velocity tolerance: 1% of the view height per second (about 0.2 px
# a frame), above the TASK-031 creep toward a shaft's centre (a few world
# units per second), far below a scroll
EPS_VIEW = 0.01
# World units between the ninja and the next corridor when the camera started
# moving along the next axis on 8be0b76 (artifacts/TASK-033/head-fail.log)
BASELINE_TO_NEXT = {'right-up': 758.76, 'right-down': 758.76, 'up-right': 1522.19, 'down-right': 1522.19}
# case: (course script, index of the segment before the join, route).
# right-up-inner is the contrast case: the corner cut on its inner side,
# straight from the old centre line on the entry edge to the new centre line
# on the exit edge, which crosses the join line (where the course segment
# switches) only as it leaves the box.
JOINS = {'right-up': ('up', 0, 'shortcut'), 'up-right': ('up', 1, 'shortcut'),
         'right-down': ('down', 0, 'shortcut'), 'down-right': ('down', 1, 'shortcut'),
         'right-up-inner': ('up', 0, 'inner')}

# Builds the path and the corner box; window.cornerState drives RUN
SETUP = '''([index, route]) => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const a = momentumCourse.segment(index), b = momentumCourse.segment(index + 1)
    const hwA = momentumSegmentHalfWidth(a), hwB = momentumSegmentHalfWidth(b)
    const vertical = a.dir == 'right' ? b : a
    const W = momentumSegmentHalfWidth(vertical), H = GAMEPLAY.momentumBorders.halfWidth
    const jx = a.x1, jy = a.y1
    const box = {left: jx - W, right: jx + W, top: jy - H, bottom: jy + H}
    const da = segmentDirection(a.dir), db = segmentDirection(b.dir)
    const v = 0.9 * GAMEPLAY.momentumMaxSpeed
    const path = []
    const line = (x0, y0, x1, y1) => {
        const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / v))
        for (let i = 0; i < n; ++i)
            path.push([x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, (x1 - x0) / n, (y1 - y0) / n])
    }
    // Earlier segments along the centre line
    let x = ninja.x, y = momentumCourse.segment(0).y0
    for (let i = 0; i < index; ++i) {
        const s = momentumCourse.segment(i)
        line(x, y, s.x1, s.y1)
        x = s.x1; y = s.y1
    }
    // The shortcut: across the box through its centre, from the entry edge
    // (0.8 of the way to the outer side) to the exit edge (0.8 of the way to
    // the far side), cutting the corner diagonally. The inner route enters
    // and leaves on the centre lines.
    const sx = da.x + db.x, sy = da.y + db.y
    const inner = route == 'inner'
    const entry = inner ? [jx - da.x * W, jy - da.y * H]
        : a.dir == 'right' ? [jx - W, jy - sy * 0.8 * H] : [jx - sx * 0.8 * W, jy - da.y * H]
    const exit = inner ? [jx + db.x * W, jy + db.y * H]
        : b.dir == 'right' ? [jx + W, jy + sy * 0.8 * H] : [jx + sx * 0.8 * W, jy + db.y * H]
    // A lead-in along the old centre line, a quarter view before the box
    const view = height / scale[version]
    const lead = [jx - da.x * (W + view / 4), jy - da.y * (H + view / 4)]
    line(x, y, lead[0], lead[1])
    line(lead[0], lead[1], entry[0], entry[1])
    const boxStart = path.length
    line(entry[0], entry[1], exit[0], exit[1])
    // On along the next corridor, half a view
    line(exit[0], exit[1], exit[0] + db.x * view / 2, exit[1] + db.y * view / 2)
    window.cornerState = {path, boxStart, box, a, b, index, i: 0, n0: ninja, deaths0: lethalDeaths}
    return {box, joinIndex: index, route, dirs: [a.dir, b.dir], halfWidths: [hwA, hwB],
            pathLength: path.length, boxStart, entry, exit}
}'''

# Runs the path up to stop ('early': the first cycle with the camera moving
# early, 'exit': the first cycle with the ninja out of the box, 'start': the
# first cycle from the box entry with the camera moving along the next axis,
# a number: that cycle) or its end. Early: moving along the next axis in the
# box before the ninja's margin to the view edge ahead along it (share of the
# view) has dropped below GAMEPLAY.momentumCamera.holdMargin (released).
RUN = '''([stop, epsView]) => {
    const st = window.cornerState, box = st.box, a = st.a, b = st.b
    const view = height / scale[version], viewW = width / scale[version]
    const eps = epsView * view
    const inBox = () => b.dir == 'right' ? ninja.x <= box.right
        : b.dir == 'up' ? ninja.y >= box.top : ninja.y <= box.bottom
    // World units between the ninja centre and the next corridor
    const toNext = () => b.dir == 'right' ? box.right - ninja.x
        : b.dir == 'up' ? ninja.y - box.top : box.bottom - ninja.y
    const nextV = () => b.dir == 'right' ? screen.velocityX : screen.velocityY
    // The ninja's margin to the view edge ahead along the next axis
    const hold = GAMEPLAY.momentumCamera.holdMargin
    const margin = () => b.dir == 'right' ? (viewW - screen.x - ninja.x) / viewW
        : b.dir == 'up' ? (ninja.y + screen.y) / view : (view - screen.y - ninja.y) / view
    // Past the old-axis cap (world units): x past the shaft cap / y past the
    // corridor-centred stop
    const pastCap = () => {
        if (a.dir == 'right')
            return -screen.x - (b.x0 - viewW / 2)
        // Once the camera is on the right segment, its preview of a
        // following shaft (TASK-069) moves the stop toward that shaft
        let stop = a.y1 - view / 2
        const preview = screen.segmentIndex > st.index ? screen.getPreviewStop(b) : null
        if (preview !== null)
            stop = a.dir == 'up' ? Math.min(stop, preview) : Math.max(stop, preview)
        return a.dir == 'up' ? stop + screen.y : -screen.y - stop
    }
    st.rows = st.rows || []
    st.early = st.early || null
    st.pastCap = st.pastCap || 0
    st.inBoxCycles = st.inBoxCycles || 0
    st.away = st.away || 0
    // Into a shaft: camera motion along the next axis away from it
    const towards = b.dir == 'down' ? 1 : b.dir == 'up' ? -1 : 0
    st.wasInBox = st.wasInBox || false
    while (st.i < st.path.length) {
        const [x, y, vx, vy] = st.path[st.i]
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy - GRAVITY
        calcPhysics()
        const cycle = st.i++
        if (ninja !== st.n0)
            return {stop: 'gameOver', cycle}
        const row = {cycle, nx: +ninja.x.toFixed(2), ny: +ninja.y.toFixed(2),
                     camVx: +screen.velocityX.toFixed(3), camVy: +screen.velocityY.toFixed(3),
                     seg: screen.segmentIndex, margin: +margin().toFixed(4)}
        if (cycle >= st.boxStart - 8 && (!st.exitCycle || cycle < st.exitCycle + 24 || !st.start || cycle < st.start.cycle + 8))
            st.rows.push(row)
        if (towards && screen.velocityY * towards < -eps) {
            st.away++
            st.firstAway = st.firstAway || {cycle, camVy: row.camVy}
        }
        const inside = cycle >= st.boxStart && inBox()
        if (inside) {
            st.inBoxCycles++
            st.wasInBox = true
            const past = pastCap()
            st.maxPastCap = Math.max(st.maxPastCap || 0, past)
            if (past > 1e-6)
                st.pastCap++
            // The course segment switches to the next one (the camera
            // starts following it) while the ninja is still in the box
            if (screen.segmentIndex > st.index && !st.switched)
                st.switched = {cycle, toNext: +toNext().toFixed(2)}
            if (!st.released && margin() < hold)
                st.released = {cycle, toNext: +toNext().toFixed(2), margin: +margin().toFixed(4)}
            if (Math.abs(nextV()) > eps && !st.early && !st.released) {
                st.early = {cycle, toNext: +toNext().toFixed(2), camV: +nextV().toFixed(3), seg: screen.segmentIndex,
                            ninja: [row.nx, row.ny]}
                if (stop == 'early')
                    return {stop, cycle}
            }
        } else if (st.wasInBox && !st.exitCycle) {
            st.exitCycle = cycle
            if (stop == 'exit')
                return {stop, cycle}
        }
        if (cycle >= st.boxStart && !st.start && Math.abs(nextV()) > eps) {
            st.start = {cycle, toNext: +toNext().toFixed(2), camV: +nextV().toFixed(3), inBox: inside,
                        margin: +margin().toFixed(4)}
            if (stop == 'start')
                return {stop, cycle}
        }
        if (stop === cycle)
            return {stop, cycle}
    }
    return {stop: null, away: st.away, firstAway: st.firstAway || null, early: st.early, switched: st.switched || null, pastCap: st.pastCap, maxPastCap: +(st.maxPastCap || 0).toFixed(4), inBoxCycles: st.inBoxCycles,
            exitCycle: st.exitCycle || null, released: st.released || null, start: st.start || null, hold, deaths: lethalDeaths - st.deaths0, rows: st.rows}
}'''

# The ninja's margin to the view edge ahead along the next axis (as in RUN)
MARGIN = '''(() => {
    const b = window.cornerState.b, view = height / scale[version], viewW = width / scale[version]
    return b.dir == 'right' ? (viewW - screen.x - ninja.x) / viewW
        : b.dir == 'up' ? (ninja.y + screen.y) / view : (view - screen.y - ninja.y) / view
})()'''
DRAW = '(() => { visualEffects.screenEffects.landings.length = 0; draw() })()'
# DOM overlay (screenshot only): the corner box and the ninja in CSS pixels
OVERLAY = '''(label) => {
    const st = window.cornerState, box = st.box
    const rect = canvas.getBoundingClientRect(), k = scale[version] * rect.width / width
    const px = (x, y) => [rect.left + (x + screen.x) * k, rect.top + (y + screen.y) * k]
    const [l, t] = px(box.left, box.top), [r, b] = px(box.right, box.bottom)
    const [nx, ny] = px(ninja.x, ninja.y)
    const div = document.createElement('div')
    div.id = 'corner-overlay'
    div.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:99999'
    div.innerHTML = `<svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <rect x="${l}" y="${t}" width="${r - l}" height="${b - t}" fill="none" stroke="#ff00ff" stroke-width="3" stroke-dasharray="10 6"/>
        <circle cx="${nx}" cy="${ny}" r="14" fill="none" stroke="#00ffff" stroke-width="3"/>
        <line x1="${nx - 22}" y1="${ny}" x2="${nx + 22}" y2="${ny}" stroke="#00ffff" stroke-width="2"/>
        <line x1="${nx}" y1="${ny - 22}" x2="${nx}" y2="${ny + 22}" stroke="#00ffff" stroke-width="2"/>
        <rect x="8" y="${rect.top + rect.height - 44}" width="1100" height="36" fill="rgba(0,0,0,0.75)"/>
        <text x="16" y="${rect.top + rect.height - 18}" fill="#ffffff" font-family="monospace" font-size="18">${label}</text>
    </svg>`
    document.body.appendChild(div)
}'''
UNOVERLAY = '(() => document.getElementById("corner-overlay").remove())()'


class MomentumCornerCameraTests(unittest.TestCase):
    results = {}
    traces = {}

    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_CORNER_CAMERA_EVIDENCE_DIR', ROOT / 'artifacts/TASK-034'))
        (cls.out / 'shots').mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'corner-trace.json').write_text(json.dumps(cls.traces, separators=(',', ':')) + '\n')
        (cls.out / 'corner-camera.json').write_text(json.dumps(cls.results, separators=(',', ':')) + '\n')

    def shoot(self, page, name, label):
        page.evaluate(DRAW)
        page.evaluate(OVERLAY, label)
        page.screenshot(path=str(self.out / 'shots' / f'{name}.png'))
        page.evaluate(UNOVERLAY)

    def check(self, name):
        script, index, route = JOINS[name]
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE, SCRIPTS[script])
        setup = page.evaluate(SETUP, [index, route])
        self.assertEqual('-'.join(setup['dirs']), name.removesuffix('-inner'))
        into_shaft = name.startswith('right-')
        first = {'stop': None} if into_shaft else page.evaluate(RUN, ['early', EPS_VIEW])
        shot = None
        if first['stop'] == 'early':
            shot = first['cycle']
            st = page.evaluate('window.cornerState.early')
            self.shoot(page, name, f'{name} cycle {shot}: camera moving early, ninja {st["toNext"]} '
                                   f'from the next corridor (camV {st["camV"]})')
        r = page.evaluate(RUN, [None, EPS_VIEW])
        if first['stop'] is None and route == 'shortcut' and r['exitCycle'] and r['start']:
            # Never early: a rerun shot as the ninja enters the box, halfway
            # through the shortcut to the camera start and as it starts turning
            page.evaluate(SETUP, [index, route])
            mid = (setup['boxStart'] + r['start']['cycle']) // 2
            shot = []
            for suffix, stop, what in (('1-enter', setup['boxStart'], 'ninja enters the corner box'),
                                       ('2-mid', mid, 'mid shortcut'),
                                       ('3-turn', 'start', 'camera starts turning')):
                at = page.evaluate(RUN, [stop, EPS_VIEW])['cycle']
                st = page.evaluate('[screen.velocityX, screen.velocityY]')
                m = page.evaluate(MARGIN)
                self.shoot(page, f'{name}-{suffix}', f'{name} cycle {at}: {what} (box exit {r["exitCycle"]}), '
                                                     f'cam v ({st[0]:.1f}, {st[1]:.1f}), margin {m:.3f} '
                                                     f'(hold {r["hold"]})')
                shot.append(at)
        # Every 4th cycle, every one near the early cycle, the box exit and the start
        early_cycle = r['early']['cycle'] if r['early'] else None
        turn_cycle = r['start']['cycle'] if r['start'] else None
        self.traces[name] = {'box': setup['box'], 'rows': [
            row for row in r.pop('rows') if row['cycle'] % 4 == 0 or abs(row['cycle'] - r['exitCycle']) <= 8 or
            early_cycle is not None and abs(row['cycle'] - early_cycle) <= 16 or
            turn_cycle is not None and abs(row['cycle'] - turn_cycle) <= 8]}
        result = dict(r, setup=setup, shot=shot)
        result.pop('stop')
        self.results[name] = result
        print(name, json.dumps(result, separators=(',', ':')), file=sys.stderr)
        self.assertEqual(errors, [])
        self.assertEqual(r['deaths'], 0)
        self.assertGreater(r['inBoxCycles'], 0)
        self.assertIsNotNone(r['exitCycle'])
        self.assertEqual(r['pastCap'], 0, f'{name}: camera past its old-axis cap in {r["pastCap"]} cycles')
        if into_shaft:
            # TASK-069: the preview may move the camera toward the shaft
            # before and in the box, never away from it
            self.assertEqual(r['away'], 0, f'{name}: camera moves away from the shaft in {r["away"]} cycles '
                                           f'(first {r["firstAway"]})')
            if route == 'shortcut':
                self.assertIsNotNone(r['start'], f'{name}: camera never moves along the next axis')
            return
        early = r['early']
        self.assertIsNone(early, f'{name}: camera moves along the next axis at cycle '
                                 f'{early and early["cycle"]} with the ninja '
                                 f'{early and early["toNext"]} world units from the next corridor '
                                 f'(camV {early and early["camV"]}, seg {early and early["seg"]}; the segment '
                                 f'switched in the box at {r["switched"]}); '
                                 f'old-axis cap passed in {r["pastCap"]} box cycles, by up to {r["maxPastCap"]}')
        if route == 'shortcut':
            # Then it does follow the next corridor, later than on 8be0b76
            start = r['start']
            self.assertIsNotNone(start, f'{name}: camera never moves along the next axis')
            print(f'{name}: camera starts at cycle {start["cycle"]}, toNext {start["toNext"]} '
                  f'(8be0b76: {BASELINE_TO_NEXT[name]}), in box {start["inBox"]}, margin {start["margin"]}, '
                  f'released {r["released"]}, box exit {r["exitCycle"]}', file=sys.stderr)
            self.assertLess(start['toNext'], BASELINE_TO_NEXT[name])


def make_test(name):
    def test(self):
        self.check(name)
    return test


for i, join in enumerate(JOINS):
    setattr(MomentumCornerCameraTests, f'test_{chr(97 + i)}_{join.replace("-", "_")}', make_test(join))


if __name__ == '__main__':
    unittest.main(verbosity=2)
