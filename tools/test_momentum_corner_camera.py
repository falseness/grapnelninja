"""Momentum camera on a corner shortcut (TASK-033 reproduction, TASK-034 fix, TASK-069 into shafts, TASK-070 out of shafts, TASK-085 rail camera).

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

User decision of TASK-068..071: "I would prefer it to change direction
earlier. e.g. if there is a tunnel down, i see nothing down and i have to go
there blindly." This overrides the TASK-033/034 "camera moves too soon on
shortcuts" rule (no motion along the next axis in the corner box). Since
TASK-084 the camera rides the rail (MomentumScreen, the course centre line
with every join a quarter circle): its view centre is lead() ahead of the
trigger point along the rail, so it turns along the arc before and in the
corner box. Per cycle of the whole drive (camera velocity camVx, camVy: the
camera top-left world corner's displacement over the cycle, world units a
second):
- the camera motion along the next axis is never away from the next
  corridor (away 0): along a quarter arc the tangent never points back;
- the camera never goes backwards along the rail (back 0: screen.railS never
  decreases). TASK-085: replaces the TASK-034/069/070 pastCap check (x past
  the shaft cap getShaftCapX, y past the corridor-centred / preview stop
  getPreviewStop), removed with them; the speed rules on this same shortcut
  drive (camera speed <= the ninja's along the rail, no jump, direction
  turning only on the arc, ninja in view with a 0.10 margin) are
  test_momentum_camera_speed's *_diagonal_* cases;
- on a shortcut the camera does move along the next axis (start).

The camera's segment switches to the next one (screen.segmentIndex) once its
trigger point passes the join; 'switched' reports that cycle (not asserted).
TASK-085: the corner-box hold (holdMargin, 'released' / 'early') and its
release are gone with the follow camera.

MOMENTUM_CORNER_CAMERA_EVIDENCE_DIR (default /tmp/momentum-corner-camera:
a bare run must not rewrite the TASK-034 evidence) receives
corner-trace.json ({join: {box, rows: [{cycle, nx, ny, camVx, camVy, railS, seg, margin}]}}
for the cycles from 8 before the box to 24 after it: every 4th one, and every
one within 8 of the box exit or the camera start), corner-camera.json (per
join summary: start, the first cycle from the box entry with the camera
moving along the next axis) and, at 1280x720 with the corner box and the ninja
marked in a DOM overlay (not drawn by the game), shots/<join>-1-enter.png
(the ninja enters the box), -2-mid.png (halfway to the camera start) and
-3-turn.png (the camera starts moving along the next axis; if it already
moves at the box entry, -2-mid halfway to the box exit and -3-turn at it) for the four
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

# Runs the path up to stop ('exit': the first cycle with the ninja out of
# the box, 'start': the first cycle from the box entry with the camera moving
# along the next axis, a number: that cycle) or its end. Camera velocity:
# displacement of the camera top-left world corner over the cycle, world
# units a second
RUN = '''([stop, epsView]) => {
    const st = window.cornerState, box = st.box, a = st.a, b = st.b
    const view = height / scale[version], viewW = width / scale[version]
    const eps = epsView * view
    const perSecond = 60 * cyclesPerTick
    const inBox = () => b.dir == 'right' ? ninja.x <= box.right
        : b.dir == 'up' ? ninja.y >= box.top : ninja.y <= box.bottom
    // World units between the ninja centre and the next corridor
    const toNext = () => b.dir == 'right' ? box.right - ninja.x
        : b.dir == 'up' ? ninja.y - box.top : box.bottom - ninja.y
    // The ninja's margin to the view edge ahead along the next axis
    const margin = () => b.dir == 'right' ? (viewW - screen.x - ninja.x) / viewW
        : b.dir == 'up' ? (ninja.y + screen.y) / view : (view - screen.y - ninja.y) / view
    st.rows = st.rows || []
    st.inBoxCycles = st.inBoxCycles || 0
    st.away = st.away || 0
    st.back = st.back || 0
    // Camera motion along the next axis away from the next corridor
    const towards = b.dir == 'up' ? -1 : 1
    st.wasInBox = st.wasInBox || false
    while (st.i < st.path.length) {
        const [x, y, vx, vy] = st.path[st.i]
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy - GRAVITY
        const cam0 = [-screen.x, -screen.y], rail0 = screen.railS
        calcPhysics()
        const cycle = st.i++
        if (ninja !== st.n0)
            return {stop: 'gameOver', cycle}
        const camVx = (-screen.x - cam0[0]) * perSecond, camVy = (-screen.y - cam0[1]) * perSecond
        const nextV = b.dir == 'right' ? camVx : camVy
        const row = {cycle, nx: +ninja.x.toFixed(2), ny: +ninja.y.toFixed(2),
                     camVx: +camVx.toFixed(3), camVy: +camVy.toFixed(3), railS: +screen.railS.toFixed(2),
                     seg: screen.segmentIndex, margin: +margin().toFixed(4)}
        if (cycle >= st.boxStart - 8 && (!st.exitCycle || cycle < st.exitCycle + 24 || !st.start || cycle < st.start.cycle + 8))
            st.rows.push(row)
        if (nextV * towards < -eps) {
            st.away++
            st.firstAway = st.firstAway || {cycle, camV: +nextV.toFixed(3)}
        }
        // Never backwards along the rail
        if (rail0 !== null && screen.railS < rail0 - 1e-6) {
            st.back++
            st.firstBack = st.firstBack || {cycle, from: rail0, to: screen.railS}
        }
        const inside = cycle >= st.boxStart && inBox()
        if (inside) {
            st.inBoxCycles++
            st.wasInBox = true
            // The camera's segment switches to the next one while the ninja
            // is still in the box
            if (screen.segmentIndex > st.index && !st.switched)
                st.switched = {cycle, toNext: +toNext().toFixed(2)}
        } else if (st.wasInBox && !st.exitCycle) {
            st.exitCycle = cycle
            if (stop == 'exit')
                return {stop, cycle, camV: [camVx, camVy]}
        }
        if (cycle >= st.boxStart && !st.start && Math.abs(nextV) > eps) {
            st.start = {cycle, toNext: +toNext().toFixed(2), camV: +nextV.toFixed(3), inBox: inside,
                        margin: +margin().toFixed(4)}
            if (stop == 'start')
                return {stop, cycle, camV: [camVx, camVy]}
        }
        if (stop === cycle)
            return {stop, cycle, camV: [camVx, camVy]}
    }
    return {stop: null, away: st.away, firstAway: st.firstAway || null, back: st.back, firstBack: st.firstBack || null,
            switched: st.switched || null, inBoxCycles: st.inBoxCycles,
            exitCycle: st.exitCycle || null, start: st.start || null, deaths: lethalDeaths - st.deaths0, rows: st.rows}
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
        cls.out = Path(os.environ.get('MOMENTUM_CORNER_CAMERA_EVIDENCE_DIR', '/tmp/momentum-corner-camera'))
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
        shot = None
        r = page.evaluate(RUN, [None, EPS_VIEW])
        if route == 'shortcut' and r['exitCycle'] and r['start']:
            # A rerun shot as the ninja enters the box, halfway through the
            # shortcut to the camera start and as it starts turning; a camera
            # already turning at the box entry (on the rail arc): halfway to
            # the box exit and at it
            page.evaluate(SETUP, [index, route])
            enter, turn = setup['boxStart'], r['start']['cycle']
            end, end_what = (turn, 'camera starts turning') if turn > enter + 1 else \
                (r['exitCycle'] - 1, 'ninja leaves the box (camera turning since the entry)')
            shot = []
            for suffix, stop, what in (('1-enter', enter, 'ninja enters the corner box'),
                                       ('2-mid', (enter + end) // 2, 'mid shortcut'),
                                       ('3-turn', end, end_what)):
                stopped = page.evaluate(RUN, [stop, EPS_VIEW])
                at, st = stopped['cycle'], stopped['camV']
                m = page.evaluate(MARGIN)
                self.shoot(page, f'{name}-{suffix}', f'{name} cycle {at}: {what} (box exit {r["exitCycle"]}), '
                                                     f'cam v ({st[0]:.1f}, {st[1]:.1f}), margin {m:.3f}')
                shot.append(at)
        # Every 4th cycle, every one near the box exit and the start
        turn_cycle = r['start']['cycle'] if r['start'] else None
        self.traces[name] = {'box': setup['box'], 'rows': [
            row for row in r.pop('rows') if row['cycle'] % 4 == 0 or abs(row['cycle'] - r['exitCycle']) <= 8 or
            turn_cycle is not None and abs(row['cycle'] - turn_cycle) <= 8]}
        result = dict(r, setup=setup, shot=shot)
        result.pop('stop')
        self.results[name] = result
        print(name, json.dumps(result, separators=(',', ':')), file=sys.stderr)
        self.assertEqual(errors, [])
        self.assertEqual(r['deaths'], 0)
        self.assertGreater(r['inBoxCycles'], 0)
        self.assertIsNotNone(r['exitCycle'])
        # TASK-085: the rail camera never goes backwards (replaces the
        # removed shaft cap / preview stop pastCap check)
        self.assertEqual(r['back'], 0, f'{name}: camera goes back along the rail in {r["back"]} cycles '
                                       f'(first {r["firstBack"]})')
        # The camera turns toward the next corridor along the rail arc
        # before and in the box, never away from it
        self.assertEqual(r['away'], 0, f'{name}: camera moves away from the next corridor in {r["away"]} cycles '
                                       f'(first {r["firstAway"]})')
        if route == 'shortcut':
            start = r['start']
            self.assertIsNotNone(start, f'{name}: camera never moves along the next axis')
            print(f'{name}: camera starts at cycle {start["cycle"]}, toNext {start["toNext"]}, in box '
                  f'{start["inBox"]}, margin {start["margin"]}, switched {r["switched"]}, '
                  f'box exit {r["exitCycle"]}', file=sys.stderr)


def make_test(name):
    def test(self):
        self.check(name)
    return test


for i, join in enumerate(JOINS):
    setattr(MomentumCornerCameraTests, f'test_{chr(97 + i)}_{join.replace("-", "_")}', make_test(join))


if __name__ == '__main__':
    unittest.main(verbosity=2)
