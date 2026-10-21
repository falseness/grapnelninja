"""Momentum camera rule (elements/momentumcamera.js, user rule 2026-10-20).

Y: the ninja stays in the vertical middle of the view, the camera re-centres
it every cycle; in an up shaft the camera never moves down and in a down
shaft never up (a ninja dropping back sees the floor / ceiling, the BackWall,
and the camera follows again once it is back in the middle).
X slides toward its target, at most at the ninja's x speed plus the catch-up
step (GAMEPLAY.momentumCamera.catchUpHeightRatio view heights) a cycle: in a
right corridor the ninja on the GAMEPLAY.cameraBorderWidthPercent = 35 line
(like bad mode, moveScreen.js Screen.shouldStartMoveX; only while the ninja is
past it, never left), in a shaft the shaft centre line in the view centre.
Y re-centres by the ninja's last step.

Scripted drives (rAF loop stopped, obstacle floor emptied, invulnerable
ninja, one calcPhysics() a cycle, the ninja's velocity set every cycle with
gravity cancelled) on scripted courses right -> right -> right, right -> up
-> right and right -> down -> right, in segment 1; 'noLeftUp' / 'noLeftDown'
drive on through the shaft into the right segment after it (the corridor X
target never goes right of the view centred on the next shaft, so the camera
never moves left); 'enter' (right course: the
ninja put at fracX 0.7 moving right at the speed cap) and 'upOffset' (up
course: the view put 600 world units right of the shaft centre line, the
ninja moving straight up) time the catch-up. Per cycle the drive keeps
[phase, fracX before, fracY before, fracX after, fracY after, camera move x,
camera move y, holdY, ninja velocity x, y] (fracX / fracY: the ninja's
position in the view as a share of its width / height; camera moves in world
units, + is right / down).

MOMENTUM_VIEW_TRIGGER_EVIDENCE_DIR (default /tmp/momentum-view-trigger)
receives numbers.json (compact: per case the measured values).
Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_camera import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
# Course scripts (test_momentum_camera.SEED_COURSE draws)
COURSES = {'right': [0.99, 0.0, 0.99, 0.0, 0.99],
           'up': [0.99, 0.9, 0.1, 0.99, 0.5],
           'down': [0.99, 0.9, 0.9, 0.99, 0.5]}
COURSES['enter'] = COURSES['right']
COURSES['upOffset'] = COURSES['up']
COURSES['noLeftUp'] = COURSES['up']
COURSES['noLeftDown'] = COURSES['down']
DIRS = {'enter': 'right', 'upOffset': 'up', 'noLeftUp': 'up', 'noLeftDown': 'down'}
EPS = 1e-6

DRIVE = '''(kind) => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const segs = [momentumCourse.segment(0), momentumCourse.segment(1), momentumCourse.segment(2)]
    const seg = segs[1], d = segmentDirection(seg.dir)
    const W = width / scale[version], H = height / scale[version]
    const v = GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1)
    const g = GRAVITY * momentumMotionScale(2)
    const catchUp = GAMEPLAY.momentumCamera.catchUpHeightRatio * H
    const second = physicsTicksPerSecond * cyclesPerTick
    const n0 = ninja, deaths0 = lethalDeaths
    const fx = () => (ninja.x + screen.x) / W, fy = () => (ninja.y + screen.y) / H
    const rows = []
    // One cycle; free: no velocity override (real physics)
    const cycle = (phase, vx, vy, free) => {
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        if (!free) { ninja.speedX = vx; ninja.speedY = vy - g }
        const row = [phase, fx(), fy()], cam = [-screen.x, -screen.y], vel = [ninja.speedX, ninja.speedY + g]
        calcPhysics()
        rows.push(row.concat([fx(), fy(), -screen.x - cam[0], -screen.y - cam[1], screen.holdY, vel[0], vel[1],
                              screen.ninjaSegment, -screen.x + W / 2]))
    }
    // approach: the centre line through segment 0, then 0.6 view heights
    // into segment 1
    const pts = [[ninja.x, segs[0].y0], [segs[0].x1, segs[0].y1], [seg.x0 + d.x * 0.6 * H, seg.y0 + d.y * 0.6 * H]]
    for (let k = 0; k + 1 < pts.length; ++k) {
        const [x0, y0] = pts[k], [x1, y1] = pts[k + 1]
        const len = Math.hypot(x1 - x0, y1 - y0), ux = (x1 - x0) / len, uy = (y1 - y0) / len
        for (let s = 0; s < len; s += v) {
            ninja.x = x0 + ux * s; ninja.y = y0 + uy * s
            cycle('approach', ux * v, uy * v)
        }
    }
    const segmentAtApproach = screen.segmentIndex
    let startCentreOff = null
    if (kind == 'noLeftUp' || kind == 'noLeftDown') {
        // on along the centre line: the rest of the shaft, then 0.6 view
        // heights into the right segment after it
        const rest = [[ninja.x, ninja.y], [seg.x1, seg.y1], [segs[2].x0 + 0.6 * H, segs[2].y0]]
        for (let k = 0; k + 1 < rest.length; ++k) {
            const [x0, y0] = rest[k], [x1, y1] = rest[k + 1]
            const len = Math.hypot(x1 - x0, y1 - y0), ux = (x1 - x0) / len, uy = (y1 - y0) / len
            for (let s = 0; s < len; s += v) {
                ninja.x = x0 + ux * s; ninja.y = y0 + uy * s
                cycle('through', ux * v, uy * v)
            }
        }
    } else if (kind == 'enter') {
        ninja.x = -screen.x + 0.7 * W
        for (let n = 0; n < Math.ceil(0.35 * W / catchUp) + 60; ++n) cycle('chase', v, 0)
    } else if (kind == 'upOffset') {
        for (let n = 0; n < 0.25 * second; ++n) cycle('settle', 0, 0)
        screen.x = -(seg.x0 + 600 - W / 2)
        startCentreOff = -screen.x + W / 2 - seg.x0
        for (let n = 0; n < Math.ceil(600 / catchUp) + 60; ++n) cycle('climb', 0, -v)
    } else if (kind == 'right') {
        ninja.x = -screen.x + 0.15 * W
        for (let n = 0; n < 0.18 * W / v; ++n) cycle('behind', v, 0)
        for (let n = 0; n < second; ++n) cycle('cross', v, 0)
        ninja.x = -screen.x + 0.55 * W
        for (let n = 0; n < 0.5 * second; ++n) cycle('still', 0, 0)
        for (let n = 0; n < 0.15 * W / v; ++n) cycle('backward', -v, 0)
        // up and down inside the corridor (half width 0.5 height)
        const reach = 0.3 * GAMEPLAY.momentumBorders.halfWidth
        for (let n = 0; n < reach / v; ++n) cycle('vertical', 0, -v)
        for (let n = 0; n < 2 * reach / v; ++n) cycle('vertical', 0, v)
    } else {
        const fwd = d.y
        // the catch-up centres the view during the approach: put it half a
        // shaft half width right of the centre line, the settle slides it back
        screen.x = -(seg.x0 + 0.5 * momentumSegmentHalfWidth(seg) - W / 2)
        startCentreOff = -screen.x + W / 2 - seg.x0
        for (let n = 0; n < second; ++n) cycle('settle', 0, 0)
        // sideways in the shaft, toward its centre line and back
        const across = 0.3 * momentumSegmentHalfWidth(seg), toward = startCentreOff > 0 ? v : -v
        for (let n = 0; n < across / v; ++n) cycle('sideways', toward, 0)
        for (let n = 0; n < across / v; ++n) cycle('sideways', -toward, 0)
        for (let n = 0; n < 0.5 * second; ++n) cycle('forward', 0, fwd * v)
        for (let n = 0; n < 0.5 * second; ++n) cycle('back', 0, -fwd * v)
        for (let n = 0; n < 1.5 * second; ++n) cycle('again', 0, fwd * v)
        if (kind == 'up') {
            // a free fall back from the middle onto the BackWall
            ninja.speedX = 0; ninja.speedY = v
            for (let n = 0; n < 2 * second; ++n) cycle('fall', 0, 0, true)
        }
    }
    return {dir: seg.dir, segX: seg.x0, W, H, v, catchUp, second, borderX: screen.borderX / W, segmentAtApproach,
            segmentIndex: screen.segmentIndex, viewCentreX: -screen.x + W / 2, startCentreOff,
            backTravel: screen.backTravel, shaftHalfWidth: momentumSegmentHalfWidth(seg),
            ninjaRadius: ninja.radius, sameNinja: ninja === n0, deaths: lethalDeaths - deaths0, rows}
}'''

PHASE, FX0, FY0, FX1, FY1, MX, MY, HOLD, VX, VY, SEG, VCX = range(12)


class MomentumViewTriggerTests(unittest.TestCase):
    drives = {}
    numbers = {}

    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_VIEW_TRIGGER_EVIDENCE_DIR', '/tmp/momentum-view-trigger'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.numbers['head'] = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                             text=True).stdout.strip()

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'numbers.json').write_text(json.dumps(cls.numbers, separators=(',', ':')) + '\n')

    def drive(self, kind):
        if kind not in self.drives:
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
            self.addCleanup(context.close)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(self.url)
            wait_for_boot_run(page)
            page.evaluate(SEED_COURSE, COURSES[kind])
            drive = page.evaluate(DRIVE, kind)
            drive['errors'] = errors
            self.drives[kind] = drive
        drive = self.drives[kind]
        self.assertEqual(drive['dir'], DIRS.get(kind, kind))
        self.assertEqual(drive['errors'], [])
        self.assertTrue(drive['sameNinja'])
        self.assertEqual(drive['deaths'], 0)
        self.assertEqual(drive['segmentAtApproach'], 1)
        return drive

    def rows(self, kind, *phases):
        return [r for r in self.drive(kind)['rows'] if r[PHASE] in phases]

    def note(self, key, value):
        self.numbers[key] = value
        print(key, json.dumps(value, separators=(',', ':')), file=sys.stderr)

    # Y: the ninja ends every cycle in the vertical middle (within its own
    # step: the camera moves before the ninja does)
    def check_centred(self, kind, rows):
        d = self.drive(kind)
        worst = max(abs(r[FY1] - 0.5) - abs(r[VY]) / d['H'] for r in rows)
        self.note(f'{kind}.centredWorstExcess', worst)
        self.assertLessEqual(worst, EPS)

    # Per axis no jump: |camera x step| <= |ninja vx| + the catch-up step,
    # |camera y step| <= the ninja's |vy| of this or the last cycle (Y
    # re-centres by its last step)
    def check_no_jump(self, kind):
        d = self.drive(kind)
        rows = d['rows']
        worst_x = max(abs(r[MX]) - abs(r[VX]) - d['catchUp'] for r in rows[1:] if r[PHASE] != 'fall')
        worst_y = max(abs(r[MY]) - max(abs(r[VY]), abs(p[VY]))
                      for p, r in zip(rows, rows[1:]) if r[PHASE] not in ('approach', 'fall'))
        self.note(f'{kind}.axisWorstExcess', [worst_x, worst_y])
        self.assertLessEqual(worst_x, EPS)
        self.assertLessEqual(worst_y, EPS)

    # Right corridor, X like bad mode
    def test_right_behind_no_move(self):
        rs = self.rows('right', 'behind')
        self.note('right.behind', {'cycles': len(rs), 'maxFrac': max(r[FX0] for r in rs),
                                   'moved': sum(1 for r in rs if abs(r[MX]) > EPS)})
        self.assertTrue(rs and max(r[FX0] for r in rs) < 0.35)
        self.assertTrue(all(abs(r[MX]) <= EPS for r in rs))

    def test_right_cross_moves_at_ninja_speed(self):
        # past the line and moving right: the camera moves at most at the
        # ninja's speed plus the catch-up step and keeps it within one step
        # of the line
        d = self.drive('right')
        rs = self.rows('right', 'cross')
        past = [r for r in rs if r[FX0] > d['borderX'] + EPS]
        before = [r for r in rs if r[FX0] <= d['borderX'] + EPS]
        self.note('right.cross', {'cycles': len(rs), 'past': len(past),
                                  'maxFracAfter': max(r[FX1] for r in rs)})
        self.assertGreater(len(past), 0.5 * len(rs))
        self.assertTrue(all(abs(r[MX]) <= EPS for r in before))
        self.assertTrue(all(EPS < r[MX] <= d['v'] + d['catchUp'] + EPS for r in past))
        self.assertLessEqual(max(r[FX1] for r in rs), d['borderX'] + d['v'] / d['W'] + EPS)

    def test_right_still_catches_up(self):
        # a still ninja past the line: the camera slides right by the
        # catch-up step until the ninja is on the line
        d = self.drive('right')
        rs = self.rows('right', 'still')
        want = [min(d['catchUp'], max(0, (r[FX0] - d['borderX']) * d['W'])) for r in rs]
        self.note('right.still', {'cycles': len(rs), 'startFrac': rs[0][FX0], 'endFrac': rs[-1][FX1]})
        self.assertTrue(rs)
        self.assertTrue(all(abs(r[MX] - w) <= EPS for r, w in zip(rs, want)))

    def test_right_backward_slides_to_line(self):
        # past the line moving left: the camera still slides right toward
        # the line, by at most the ninja's x speed plus the catch-up step,
        # until the ninja is on it
        d = self.drive('right')
        rs = self.rows('right', 'backward')
        want = [min(d['v'] + d['catchUp'], max(0, (r[FX0] - d['borderX']) * d['W'])) for r in rs]
        self.note('right.backward', {'cycles': len(rs), 'startFrac': rs[0][FX0], 'endFrac': rs[-1][FX1],
                                     'moved': sum(1 for r in rs if r[MX] > EPS)})
        self.assertTrue(all(abs(r[MX] - w) <= EPS for r, w in zip(rs, want)))
        self.assertLessEqual(rs[-1][FX1], d['borderX'] + EPS)

    def test_enter_past_line_catches_up(self):
        # entering at fracX 0.7 at the speed cap: on the line (within one
        # ninja step) within ceil(0.35 W / catch-up) + 10 cycles, never left
        d = self.drive('enter')
        rs = self.rows('enter', 'chase')
        limit = d['borderX'] + d['v'] / d['W'] + EPS
        reached = next((k + 1 for k, r in enumerate(rs) if r[FX1] <= limit), None)
        bound = -(-0.35 * d['W'] // d['catchUp']) + 10
        self.note('enter.catchUp', {'startFrac': rs[0][FX0], 'cyclesToLine': reached, 'bound': bound,
                                    'seconds': reached and reached / d['second'], 'catchUp': d['catchUp'],
                                    'v': d['v'], 'W': d['W'], 'H': d['H']})
        self.assertGreater(rs[0][FX0], 0.69)
        self.assertIsNotNone(reached)
        self.assertLessEqual(reached, bound)
        self.assertTrue(all(r[FX1] <= limit for r in rs[reached:]))
        self.assertGreaterEqual(min(r[MX] for r in rs), -EPS)

    def test_up_shaft_offset_recentres(self):
        # moving straight up (speedX 0) with the view 600 units off the
        # shaft centre: centred within ceil(600 / catch-up) + 10 cycles
        d = self.drive('upOffset')
        rs = self.rows('upOffset', 'climb')
        cam = d['startCentreOff']
        off = []
        for r in rs:
            cam += r[MX]
            off.append(cam)
        reached = next((k + 1 for k, o in enumerate(off) if abs(o) <= EPS), None)
        bound = -(-600 // d['catchUp']) + 10
        self.note('upOffset.recentre', {'startOff': d['startCentreOff'], 'cyclesToCentre': reached,
                                        'bound': bound, 'seconds': reached and reached / d['second'],
                                        'endOff': d['viewCentreX'] - d['segX'], 'segment': d['segmentIndex']})
        self.assertAlmostEqual(d['startCentreOff'], 600, places=6)
        self.assertIsNotNone(reached)
        self.assertLessEqual(reached, bound)
        self.assertLessEqual(abs(d['viewCentreX'] - d['segX']), EPS)
        self.assertTrue(all(-d['catchUp'] - EPS <= r[MX] <= EPS for r in rs))
        self.assertTrue(all(abs(r[VX]) <= EPS for r in rs))

    def test_right_never_left(self):
        rs = self.drive('right')['rows']
        self.assertGreaterEqual(min(r[MX] for r in rs), -EPS)

    def test_right_y_centred(self):
        rs = self.rows('right', 'behind', 'cross', 'still', 'backward', 'vertical')
        self.assertTrue(any(abs(r[MY]) > EPS for r in rs if r[PHASE] == 'vertical'))
        self.check_centred('right', rs)

    def test_right_no_jump(self):
        self.check_no_jump('right')

    # Driving right -> shaft -> right along the centre line at the speed cap:
    # the corridor X target is capped at the view centred on the shaft, so
    # the camera never moves left and the view is centred on the shaft's
    # first cycle
    def check_no_left(self, kind):
        d = self.drive(kind)
        rows = d['rows']
        first = next(k for k, r in enumerate(rows) if r[SEG] == 1)
        corridor = [r for r in rows[:first] if r[SEG] == 0]
        limit = 0.5 + d['shaftHalfWidth'] / d['W']
        self.note(f'{kind}.noLeft', {'cycles': len(rows), 'minCamStepX': min(r[MX] for r in rows),
                                     'firstShaftCycle': first, 'firstShaftCentreOff': rows[first][VCX] - d['segX'],
                                     'corridorMaxFracX': max(r[FX1] for r in corridor), 'fracXLimit': limit,
                                     'endSegment': d['segmentIndex']})
        self.assertGreaterEqual(min(r[MX] for r in rows), -1e-9)
        self.assertLessEqual(abs(rows[first][VCX] - d['segX']), EPS)
        self.assertTrue(corridor)
        self.assertLessEqual(max(r[FX1] for r in corridor), limit)
        self.assertEqual(d['segmentIndex'], 2)

    def test_no_left_right_up_right(self):
        self.check_no_left('noLeftUp')

    def test_no_left_right_down_right(self):
        self.check_no_left('noLeftDown')

    # Shafts
    # The view slides toward the shaft centre line while the ninja moves
    # sideways (the sideways phase), and never away from it
    def check_shaft_x_slides(self, kind):
        d = self.drive(kind)
        rows = [r for r in d['rows'] if r[PHASE] != 'approach']
        side = [r for r in rows if r[PHASE] == 'sideways']
        settle = [r for r in rows if r[PHASE] == 'settle']
        self.note(f'{kind}.slide', {'startOff': d['startCentreOff'], 'endOff': d['viewCentreX'] - d['segX'],
                                    'settleMoved': sum(1 for r in settle if abs(r[MX]) > EPS),
                                    'sidewaysCycles': len(side), 'moved': sum(1 for r in side if abs(r[MX]) > EPS)})
        self.assertGreater(abs(d['startCentreOff']), 1)
        self.assertTrue(all(r[MX] * d['startCentreOff'] <= EPS for r in rows), 'moved away from the centre')
        self.assertLess(abs(d['viewCentreX'] - d['segX']), abs(d['startCentreOff']))
        # moving straight along the shaft: only the catch-up step
        self.assertTrue(all(abs(r[MX]) <= d['catchUp'] + EPS for r in rows if r[PHASE] in ('forward', 'back', 'again')))
        self.assertLessEqual(abs(d['viewCentreX'] - d['segX']), EPS)

    def check_shaft_follows(self, kind):
        fwd = -1 if kind == 'up' else 1
        rs = self.rows(kind, 'forward')
        self.check_centred(kind, rs)
        # from the second cycle (the first re-centres the still ninja)
        self.assertTrue(all(r[MY] * fwd > 0 for r in rs[1:]))

    def check_shaft_holds(self, kind):
        fwd = -1 if kind == 'up' else 1
        # the first cycle back still re-centres the last forward step
        back = self.rows(kind, 'back')[1:]
        again = self.rows(kind, 'again')
        moved_back = [r for r in back + again if r[MY] * fwd < -EPS]
        resumed = [k for k, r in enumerate(again) if abs(r[MY]) > EPS]
        self.note(f'{kind}.hold', {'backCycles': len(back), 'held': sum(1 for r in back if r[HOLD]),
                                   'movedBack': len(moved_back), 'resumedAfter': resumed[0] if resumed else None,
                                   'endFracY': again[-1][FY1]})
        self.assertTrue(all(r[HOLD] and abs(r[MY]) <= EPS for r in back))
        self.assertEqual(moved_back, [])
        # the camera follows again once the ninja is back in the middle
        self.assertTrue(resumed)
        self.assertTrue(all(abs(r[MY]) <= EPS for r in again[:resumed[0]]))
        self.check_centred(kind, again[resumed[0]:])

    def test_up_x_slides_to_centre(self):
        self.check_shaft_x_slides('up')

    def test_up_follows(self):
        self.check_shaft_follows('up')

    def test_up_holds_when_falling_back(self):
        self.check_shaft_holds('up')

    def test_up_fall_bounces_on_floor(self):
        d = self.drive('up')
        rs = self.rows('up', 'fall')
        lowest = max(r[FY1] for r in rs)
        self.note('up.fall', {'cycles': len(rs), 'lowestFracY': lowest, 'backTravel': d['backTravel'],
                              'camDown': sum(1 for r in rs if r[MY] > EPS)})
        self.assertEqual(d['backTravel'], -1)
        self.assertTrue(all(r[MY] <= EPS for r in rs))
        self.assertGreater(lowest, 0.9)
        self.assertLessEqual(lowest, 1 + EPS)

    def test_up_no_jump(self):
        self.check_no_jump('up')

    def test_down_x_slides_to_centre(self):
        self.check_shaft_x_slides('down')

    def test_down_follows(self):
        self.check_shaft_follows('down')

    def test_down_holds_when_rising(self):
        self.check_shaft_holds('down')

    def test_down_no_jump(self):
        self.check_no_jump('down')


if __name__ == '__main__':
    unittest.main()
