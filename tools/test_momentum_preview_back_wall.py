"""Momentum back wall after a short corridor between opposite shafts (TASK-091).

Forced courses right -> A -> R -> B with R the shortest right corridor the
course allows between opposite shafts (max(minLen, oppositeShaftGap) + 1):
'up' = up A -> R -> down B, 'down' = down A -> R -> up B. With the rAF loop
stopped and the obstacle floor emptied, the ninja is driven (invulnerable, one
calcPhysics() per point, at the effective speed cap GAMEPLAY.momentumMaxSpeed
* momentumMotionScale(1)) along the centre line through A into R until the
camera's verticalTravel turns toward B or the ninja is past A's opening,
then back left to A's centre (still scripted). There it is made vulnerable
and released over A's opening moving back into A at the cap: 'up' then
falls under gravity alone (momentum's slowed gravity from rest would need
~4 s to cover the half view down to the back wall, so the 3 s rule would
only time gravity), 'down' is scripted straight up at the cap every cycle
until its first bounce (gravity can't take it back up). No grapnel.

Rule, over the 3 s (180 frames) after the release: the ninja is stopped by a
wall or back-wall face (an approaching applyBounce) or the run ends (lethal
death / restart / frozen run), and its body is never more than one view
height outside the view vertically. On bc954d5 the camera's preview of B
moves the back wall (and the left-behind side) to the far view edge while
the ninja is still over A's opening, so it leaves the view and falls on.

MOMENTUM_PREVIEW_BACK_WALL_ROOT: the tree served (default this repo).
MOMENTUM_PREVIEW_BACK_WALL_LABEL (default 'head'): key the results are stored
under (merged with existing keys) in result.json and trace.json in
MOMENTUM_PREVIEW_BACK_WALL_EVIDENCE_DIR (default /tmp/momentum-preview-back-wall),
with shots/<case>-drop-<label>.png: a 3x zoomed-out debug frame at the
drop-back (its first stop, the run end, its farthest point outside the view or
the last cycle),
the real view outlined white, the back wall face red, the ninja ringed yellow
(tutorial hint hidden).
trace.json: {label: {case: {fields, rows}}}, one row every 4th frame.
Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(os.environ.get('MOMENTUM_PREVIEW_BACK_WALL_ROOT', Path(__file__).resolve().parents[1]))
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PREVIEW_BACK_WALL_EVIDENCE_DIR', '/tmp/momentum-preview-back-wall'))
LABEL = os.environ.get('MOMENTUM_PREVIEW_BACK_WALL_LABEL', 'head')
SECONDS = 3
FPS = 60
TRACE_EVERY = 4
ZOOM = 3

# Course draws: segment 0 right (length), A (vertical, up/down, length),
# R (length 'R': the shortest that keeps B opposite), B (vertical, its
# direction, length), then a fixed LCG
SCRIPTS = {'up': [0.99, 0.9, 0.1, 0.5, 'R', 0.9, 0.9, 0.5],
           'down': [0.99, 0.9, 0.9, 0.5, 'R', 0.9, 0.1, 0.5]}

SEED = '''(script) => {
    const o = GAMEPLAY.momentumCourse, b = GAMEPLAY.momentumBorders
    const gap = 2 * momentumShaftHalfWidth() + b.thickness + b.backing
    const r = (Math.max(o.minLen, gap) + 1 - o.minLen) / (o.maxLen - o.minLen)
    const values = script.map(v => v == 'R' ? r : v)
    let k = 0, s = 12345
    const next = () => k < values.length ? values[k++]
        : ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648)
    const generate = MomentumCourse.prototype.generate
    MomentumCourse.prototype.generate = function() {
        const random = Math.random
        Math.random = next
        try { return generate.call(this) } finally { Math.random = random }
    }
    PLATFORM.isInterstitialDue = () => false
    window.lethalDeaths = 0
    const lethal = onLethalDeath
    onLethalDeath = function() { lethalDeaths++; return lethal.apply(this, arguments) }
    const apply = Ninja.prototype.applyBounce
    Ninja.prototype.applyBounce = function(c) {
        const st = window.pbw
        if (st && st.released && c.approaching && !st.stop)
            st.stop = {cycle: st.cycle, element: c.element && c.element.constructor ? c.element.constructor.name : null}
        return apply.apply(this, arguments)
    }
}'''

DRIVE = '''() => {
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const s0 = momentumCourse.segment(0), a = momentumCourse.segment(1)
    const r = momentumCourse.segment(2), b = momentumCourse.segment(3)
    const v = GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1)
    const sy = a.dir == 'up' ? -1 : 1, travelB = b.dir == 'up' ? -1 : 1
    const hwA = momentumSegmentHalfWidth(a)
    const view = height / scale[version]
    const n0 = ninja
    const st = window.pbw = {n0, deaths0: lethalDeaths, cycle: 0, released: false, stop: null, rows: [],
                             view, sy, maxOutside: 0, maxOutsideCycle: null, endCycle: null, flip: null}
    const row = (phase) => {
        const w = screen.backWall
        st.rows.push([st.cycle / cyclesPerTick, phase, screen.verticalTravel,
                      screen.backTravel === undefined ? null : screen.backTravel,
                      w ? w.side : null, w ? +w.y.toFixed(1) : null, +ninja.y.toFixed(1), +ninja.x.toFixed(1),
                      +(-screen.y).toFixed(1), screen.hasLeftBehind(ninja) ? 1 : 0, ninja === n0 ? 1 : 0])
    }
    st.row = row
    const step = (x, y, vx, vy, phase) => {
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy - GRAVITY
        calcPhysics()
        ++st.cycle
        if (st.flip === null && screen.verticalTravel == travelB)
            st.flip = {cycle: st.cycle, x: +(ninja.x - a.x0).toFixed(1), y: +(ninja.y - a.y1).toFixed(1)}
        if (st.cycle % (TRACE_EVERY * cyclesPerTick) == 0)
            row(phase)
    }
    for (let x = Math.max(ninja.x, s0.x0); x < a.x0; x += v) step(x, s0.y0, v, 0, 'drive')
    for (let y = s0.y0; (a.y1 - y) * sy > 0; y += sy * v) step(a.x0, y, 0, sy * v, 'drive')
    let x = a.x0
    for (; x < a.x0 + hwA && st.flip === null; x += v)
        step(x, a.y1, v, 0, 'drive')
    const turnX = x - a.x0
    for (; x > a.x0; x -= v) step(x, a.y1, -v, 0, 'back')
    // Moving back at the cap: 'up' drops from there under gravity alone,
    // 'down' is pushed up each cycle in RUN
    ninja.x = a.x0; ninja.y = a.y1; ninja.speedX = 0; ninja.speedY = -sy * v
    ninja.invulnerableMs = 0
    st.released = true
    st.releaseCycle = st.cycle
    row('release')
    return {dirs: [s0.dir, a.dir, r.dir, b.dir], rLength: r.length, view, hwA, cap: v, turnX, flip: st.flip,
            sameRun: ninja === n0, verticalTravel: screen.verticalTravel,
            backTravel: screen.backTravel === undefined ? null : screen.backTravel,
            wallSide: screen.backWall ? screen.backWall.side : null}
}'''

# Runs released cycles up to cycles (or until 'peak': the cycle to shoot)
RUN = '''([cycles, until]) => {
    const st = window.pbw
    const outside = () => Math.max(0, -(ninja.y + ninja.radius + screen.y),
                                   ninja.y - ninja.radius + screen.y - st.view) / st.view
    while (st.cycle - st.releaseCycle < cycles && st.endCycle === null) {
        if (st.sy > 0 && !st.stop) {
            ninja.speedX = 0
            ninja.speedY = -GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) - GRAVITY
        }
        calcPhysics()
        ++st.cycle
        if (st.cycle % cyclesPerTick == 0)
            ninja.tickInvulnerability(physicsStepMs)
        if (ninja !== st.n0 || lethalDeaths > st.deaths0 || isRunFrozen()) {
            st.endCycle = st.cycle - st.releaseCycle
            st.row('end')
            break
        }
        const out = outside()
        if (out > st.maxOutside) {
            st.maxOutside = out
            st.maxOutsideCycle = st.cycle - st.releaseCycle
        }
        if (st.cycle % (TRACE_EVERY * cyclesPerTick) == 0)
            st.row('drop')
        if (until !== null && st.cycle - st.releaseCycle >= until)
            break
    }
    return {cycle: st.cycle - st.releaseCycle, stop: st.stop && {cycle: st.stop.cycle - st.releaseCycle, element: st.stop.element},
            endCycle: st.endCycle, maxOutside: +st.maxOutside.toFixed(4), maxOutsideCycle: st.maxOutsideCycle,
            deaths: lethalDeaths - st.deaths0}
}'''

# Zoomed-out debug frame: the world drawn at scale / ZOOM around the real
# view, then the real view (white), the back wall face (red) and the ninja
# (yellow) outlined in canvas pixels
SHOOT = '''(zoom) => {
    visualEffects.screenEffects.landings.length = 0
    if (typeof TUTORIAL_HINT != 'undefined') { TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true }
    const s = scale[version], sx = screen.x, sy = screen.y
    const viewW = width / s, viewH = height / s
    scale[version] = s / zoom
    screen.x = sx + viewW * (zoom - 1) / 2
    screen.y = sy + viewH * (zoom - 1) / 2
    try { draw() } finally {
        scale[version] = s; screen.x = sx; screen.y = sy
    }
    const k = s / zoom * canvas.width / width, ox = viewW * (zoom - 1) / 2, oy = viewH * (zoom - 1) / 2
    const toX = wx => (wx + sx + ox) * k, toY = wy => (wy + sy + oy) * k
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.lineWidth = 3
    ctx.strokeStyle = '#ffffff'
    ctx.strokeRect(ox * k, oy * k, viewW * k, viewH * k)
    const w = screen.backWall
    if (w && w.side) {
        ctx.strokeStyle = '#ff2020'
        ctx.lineWidth = 5
        ctx.beginPath(); ctx.moveTo(0, toY(w.y)); ctx.lineTo(canvas.width, toY(w.y)); ctx.stroke()
    }
    ctx.strokeStyle = '#ffff00'
    ctx.lineWidth = 3
    ctx.beginPath(); ctx.arc(toX(ninja.x), toY(ninja.y), Math.max(12, 3 * ninja.radius * k), 0, 2 * Math.PI); ctx.stroke()
    ctx.restore()
    return {wallY: w ? w.y : null, wallSide: w ? w.side : null, ninjaY: ninja.y, viewTop: -sy}
}'''


def merge_json(path, data):
    stored = json.loads(path.read_text()) if path.exists() else {}
    stored[LABEL] = data
    path.write_text(json.dumps(stored, separators=(',', ':')))


class MomentumPreviewBackWallTests(unittest.TestCase):
    results = {}
    traces = {}

    @classmethod
    def setUpClass(cls):
        (EVIDENCE_DIR / 'shots').mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        merge_json(EVIDENCE_DIR / 'result.json', cls.results)
        merge_json(EVIDENCE_DIR / 'trace.json', cls.traces)

    def check(self, case):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SEED, SCRIPTS[case])
        drive = page.evaluate(DRIVE.replace('TRACE_EVERY', str(TRACE_EVERY)))
        cycles = SECONDS * FPS * page.evaluate('cyclesPerTick')
        # The drop is deterministic: run it to the end, then replay it on a
        # fresh page up to the cycle to shoot
        run = RUN.replace('TRACE_EVERY', str(TRACE_EVERY))
        r = page.evaluate(run, [cycles, None])
        self.traces[case] = {'fields': ['frame', 'phase', 'verticalTravel', 'backTravel', 'wallSide', 'wallY',
                                        'ninjaY', 'ninjaX', 'cameraY', 'leftBehind', 'alive'],
                             'rows': page.evaluate('window.pbw.rows')}
        shoot_at = r['stop']['cycle'] if r['stop'] else r['endCycle'] if r['endCycle'] else \
            r['maxOutsideCycle'] if r['maxOutsideCycle'] else cycles
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SEED, SCRIPTS[case])
        page.evaluate(DRIVE.replace('TRACE_EVERY', str(TRACE_EVERY)))
        page.evaluate(run, [cycles, max(0, shoot_at - 1)])
        name = f'{case}-drop-{LABEL}.png'
        shot = dict(page.evaluate(SHOOT, ZOOM), name=name, cycle=shoot_at)
        page.screenshot(path=str(EVIDENCE_DIR / 'shots' / name))
        stopped = r['stop'] is not None and r['stop']['cycle'] <= cycles
        ended = r['endCycle'] is not None
        result = dict(drive=drive, **r, stopped=stopped, ended=ended, cycles=cycles, shot=shot)
        self.results[case] = result
        print(LABEL, case, json.dumps(result, separators=(',', ':')), file=sys.stderr)
        self.assertEqual(drive['dirs'], ['right', case, 'right', 'down' if case == 'up' else 'up'])
        self.assertTrue(drive['sameRun'])
        self.assertTrue(stopped or ended, f'{case}: neither stopped by a wall face nor run ended within {SECONDS} s')
        self.assertLessEqual(r['maxOutside'], 1.0, f'{case}: ninja {r["maxOutside"]} view heights outside the view')
        self.assertEqual(errors, [])

    def test_a_up_right_down(self):
        self.check('up')

    def test_b_down_right_up(self):
        self.check('down')


if __name__ == '__main__':
    unittest.main(verbosity=2)
