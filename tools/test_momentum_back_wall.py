"""Momentum BackWall: a ninja falling back after vertical travel bounces (TASK-032).

Course scripts right -> up and right -> down (test_momentum_shaft_view). With
the rAF loop stopped and the obstacle floor emptied, the ninja is driven
(invulnerable, one calcPhysics() per point) along the corridor and into the
shaft until the camera has scrolled at least half a view along it. Then it is
made vulnerable and its speed is scripted straight back (down after going up,
up after going down) at 0.9 * GAMEPLAY.momentumMaxSpeed every cycle until the
first bounce off screen.backWall; after that physics runs freely, 5 s in
total (300 frames * cyclesPerTick cycles). Asserts: no game over (same ninja,
no lethal death, run not frozen), >= 1 bounce off the boundary, the ninja's
body inside the view every cycle. On a tree without the boundary the ninja
leaves the view behind and dies.

MOMENTUM_BACK_WALL_EVIDENCE_DIR (default artifacts/TASK-032) receives
bounce-trace.json ({case: [{cycle, ninjaY, boundaryY, speedY, gameOver}]}
for the cycles around each of the first bounces), back-wall.json (per case
summary) and shots/<case>-before-bounce.png, shots/<case>-bounce.png at
1280x720, plus shots/zoom/ with a 4x crop of each around the ninja. Requires Playwright Chromium.
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
SECONDS = 5
FPS = 60

CLIMB = '''() => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const s0 = momentumCourse.segment(0), s1 = momentumCourse.segment(1)
    const view = height / scale[version]
    const v = 0.9 * GAMEPLAY.momentumMaxSpeed, sy = s1.dir == 'up' ? -1 : 1
    const path = []
    for (let x = Math.max(ninja.x, s0.x0); x < s1.x0; x += v) path.push([x, s0.y0, v, 0])
    for (let y = s0.y0; (s1.y1 - y) * sy > 0; y += sy * v) path.push([s1.x0, y, 0, sy * v])
    const n0 = ninja, cam0 = screen.y
    for (const [x, y, vx, vy] of path) {
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy - GRAVITY
        calcPhysics()
        if (screen.getSegment().dir == s1.dir && Math.abs(screen.y - cam0) >= view / 2)
            break
    }
    ninja.invulnerableMs = 0
    ninja.speedX = 0
    let backBounces = 0
    if (!window.backWallPatched) {
        window.backWallPatched = true
        const apply = Ninja.prototype.applyBounce
        Ninja.prototype.applyBounce = function(c) {
            if (typeof BackWall != 'undefined' && c.element instanceof BackWall && c.approaching)
                ++window.backWallState.bounces
            return apply.apply(this, arguments)
        }
    }
    window.backWallState = {n0, sy, v, cycle: 0, bounces: 0, trace: [], recent: [], after: 0,
                            outside: 0, gameOver: false, cameraScrolled: Math.abs(screen.y - cam0) / view,
                            deaths0: lethalDeaths}
    return {dir: s1.dir, sameRun: ninja === n0, cameraScrolled: window.backWallState.cameraScrolled,
            verticalTravel: screen.verticalTravel}
}'''

# Runs cycles until done or a requested stop: 'before' (the next cycle
# touches the boundary) or 'bounce' (this cycle bounced first)
RUN = '''([cycles, stop]) => {
    const st = window.backWallState
    const view = height / scale[version]
    const boundaryY = () => screen.backWall ? screen.backWall.y
        : st.sy < 0 ? view - screen.y : -screen.y
    const row = () => ({cycle: st.cycle, ninjaY: +ninja.y.toFixed(3), boundaryY: +boundaryY().toFixed(3),
                        speedY: +ninja.speedY.toFixed(4), gameOver: st.gameOver})
    while (st.cycle < cycles && !st.gameOver) {
        if (!st.bounces) {
            ninja.speedX = 0
            ninja.speedY = -st.sy * st.v - GRAVITY
            const gap = -st.sy * (boundaryY() - ninja.y) - ninja.radius
            if (stop == 'before' && gap <= st.v + GRAVITY)
                return {stop, cycle: st.cycle, gap}
        }
        const before = st.bounces
        calcPhysics()
        ++st.cycle
        if (st.cycle % cyclesPerTick == 0)
            ninja.tickInvulnerability(physicsStepMs)
        st.gameOver = ninja !== st.n0 || lethalDeaths > st.deaths0 || isRunFrozen()
        if (!st.gameOver && (ninja.y - ninja.radius < -screen.y - 1 || ninja.y + ninja.radius > view - screen.y + 1))
            ++st.outside
        // Rows around the first 4 bounces: 4 before, 4 after
        const r = row()
        st.recent.push(r)
        if (st.recent.length > 5)
            st.recent.shift()
        if (st.bounces > before && st.bounces <= 4) {
            st.trace.push(...st.recent.splice(0))
            st.after = 4
        } else if (st.after > 0) {
            st.trace.push(r)
            --st.after
        }
        if (st.gameOver && st.trace[st.trace.length - 1] !== r)
            st.trace.push(...st.recent.splice(0))
        if (stop == 'bounce' && st.bounces > before && before == 0)
            return {stop, cycle: st.cycle}
    }
    return {stop: null, cycle: st.cycle, bounces: st.bounces, gameOver: st.gameOver, outside: st.outside,
            deaths: lethalDeaths - st.deaths0, trace: st.trace}
}'''

DRAW = '(() => { visualEffects.screenEffects.landings.length = 0; draw() })()'
# The ninja's CSS pixel position
NINJA_CSS = '''(() => {
    const rect = canvas.getBoundingClientRect(), k = scale[version] * rect.width / width
    return [rect.left + (ninja.x + screen.x) * k, rect.top + (ninja.y + screen.y) * k]
})()'''
ZOOM = 4


def save_zoom(shot, centre, out):
    """A ZOOM x crop of shot around centre, the same size as shot."""
    from PIL import Image
    with Image.open(shot) as image:
        w, h = image.size[0] // ZOOM, image.size[1] // ZOOM
        x = min(max(0, round(centre[0] - w / 2)), image.size[0] - w)
        y = min(max(0, round(centre[1] - h / 2)), image.size[1] - h)
        image.crop((x, y, x + w, y + h)).resize(image.size, Image.NEAREST).save(out)


class MomentumBackWallTests(unittest.TestCase):
    results = {}
    traces = {}

    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_BACK_WALL_EVIDENCE_DIR', ROOT / 'artifacts/TASK-032'))
        (cls.out / 'shots' / 'zoom').mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'bounce-trace.json').write_text(json.dumps(cls.traces, separators=(',', ':')) + '\n')
        (cls.out / 'back-wall.json').write_text(json.dumps(cls.results, separators=(',', ':')) + '\n')

    def check(self, dir):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE, SCRIPTS[dir])
        climb = page.evaluate(CLIMB)
        self.assertEqual(climb['dir'], dir)
        self.assertTrue(climb['sameRun'])
        self.assertGreaterEqual(climb['cameraScrolled'], 0.5)
        cycles = SECONDS * FPS * page.evaluate('cyclesPerTick')
        shots = []
        for stop in ('before', 'bounce'):
            r = page.evaluate(RUN, [cycles, stop])
            if r['stop'] == stop:
                name = f'{dir}-{"before-bounce" if stop == "before" else "bounce"}.png'
                page.evaluate(DRAW)
                page.screenshot(path=str(self.out / 'shots' / name))
                save_zoom(self.out / 'shots' / name, page.evaluate(NINJA_CSS),
                          self.out / 'shots' / 'zoom' / name)
                shots.append([name, r['cycle']])
        r = page.evaluate(RUN, [cycles, None])
        self.traces[dir] = r.pop('trace')
        result = dict(r, climb=climb, shots=shots)
        result.pop('stop')
        self.results[dir] = result
        print(dir, json.dumps(result, separators=(',', ':')), file=sys.stderr)
        self.assertFalse(r['gameOver'])
        self.assertEqual(r['deaths'], 0)
        self.assertEqual(r['cycle'], cycles)
        self.assertGreaterEqual(r['bounces'], 1)
        self.assertEqual(r['outside'], 0)
        self.assertEqual(len(shots), 2)
        self.assertEqual(errors, [])

    def test_a_up_shaft_fall_back(self):
        self.check('up')

    def test_b_down_shaft_jump_back(self):
        self.check('down')


if __name__ == '__main__':
    unittest.main(verbosity=2)
