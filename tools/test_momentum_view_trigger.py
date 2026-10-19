"""Momentum camera follows the ninja: the view trigger rule (TASK-117).

User rule (2026-10-19, the spec): 1. choose the camera's direction of
movement; 2. move the camera only when the ninja moves in that same
direction AND has crossed a fixed percent of the screen along it, like bad
mode (moveScreen.js Screen.shouldStartMoveX: ninja.x > borderX - screen.x &&
ninja.speedX > 0, X = GAMEPLAY.cameraBorderWidthPercent = 35).

fwdFrac: the ninja's position along the camera's direction as a share of the
view extent along it, from the trailing edge (right: x share of the width
from the left edge; down: y share from the top; up: from the bottom).

(a) Scripted drives (tools/test_momentum_camera_speed.py style: rAF loop
stopped, obstacle floor emptied, invulnerable ninja, one calcPhysics() per
cycle) in a right corridor (segment 1 of right -> right -> right), an up
shaft (segment 1 of right -> up -> right) and a down shaft (segment 1 of
right -> down -> right). The ninja is first driven along the course centre
line at the effective speed cap v (a cycle) 0.6 view heights into the
segment, then held on the segment centre line through phases, its velocity
set every cycle:
- behind: placed at fwdFrac 0.15, moving forward at v for the cycles it takes
  to reach 0.33 in a still view: the camera does not move;
- cross: on forward at v for 1 s: the camera does not move while the
  cycle's starting fwdFrac is behind X - v / extent; once it is past X the
  camera moves on every cycle and the ninja stays on the line (fwdFrac after
  the cycle within X +- v / extent);
- still: placed at fwdFrac 0.55 with no velocity for 0.5 s: no move;
- backward: from there moving backward at v for the cycles it takes to reach
  0.40: no move;
and over the whole drive the camera never moves backward along the segment.
A placement is not motion: a camera that tracks the ninja's motion since the
last cycle (HEAD's MomentumScreen.lastNinja) is told the ninja was put there.
(b) Natural run, seed 1, through tools/momentum_natural_run.py (TASK-116):
framesBeyondTrigger == 0, framesMovedWithoutRule == 0, framesOutOfView == 0
(about 9 minutes).

Expected failures at HEAD (dc26b1c, the rail camera elements/
momentumcamera.js: it triggers on course centre line progress and advances
by a projected ninja speed, so the ninja is not held on the line, and in
shafts the trigger sits lead() behind the view centre, not at X), fixed by
TASK-118:
- test_right_cross (the camera moves with the ninja about 0.003 W behind
  the line: it never crosses it)
- test_up_behind, test_down_behind (the shaft trigger is at about 0.23 H)
- test_up_cross, test_down_cross (the ninja is kept at that 0.23, not on X)
- test_natural_seed1 (test_natural_seed1_ran only checks the run completed)
TASK-118 removes the expectedFailure marks.

MOMENTUM_VIEW_TRIGGER_EVIDENCE_DIR (default /tmp/momentum-view-trigger)
receives head-numbers.json (compact: per case the measured values) and
natural/ (the natural run's baseline.json, seed1/, shots/).
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
from test_momentum_shaft_view import SCRIPTS
import momentum_natural_run

ROOT = Path(__file__).resolve().parents[1]
# Course scripts (test_momentum_camera.SEED_COURSE draws): right -> right ->
# right (a low turn draw keeps the right direction; the first segment is too
# short for the view's travel before its exit arc), right -> up -> right and
# right -> down -> right (test_momentum_shaft_view)
COURSES = dict(SCRIPTS, right=[0.99, 0.0, 0.99, 0.0, 0.99])
# corridor: (course script, segment index)
CORRIDORS = {'right': ('right', 1), 'up': ('up', 1), 'down': ('down', 1)}
EPS = 1e-6
NATURAL_SEED = 1

# Builds the course, drives the ninja along the centre line into the middle
# of segment index, then through the phases; per cycle [phase, fracBefore,
# fracAfter, velAlong, camMove, camMoveAcross] along / across the segment
# direction
DRIVE = '''(index) => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const segs = []
    for (let i = 0; i <= index + 1; ++i)
        segs.push(momentumCourse.segment(i))
    const seg = segs[index], d = segmentDirection(seg.dir)
    const W = width / scale[version], H = height / scale[version]
    const extent = W * Math.abs(d.x) + H * Math.abs(d.y)
    const v = GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1)
    const g = GRAVITY * momentumMotionScale(2)
    const trigger = GAMEPLAY.cameraBorderWidthPercent / 100
    const n0 = ninja, deaths0 = lethalDeaths
    // fwdFrac of a world point in the current view
    const frac = (x, y) => d.x > 0 ? (x + screen.x) / W : d.y > 0 ? (y + screen.y) / H : 1 - (y + screen.y) / H
    // world point of fwdFrac f on the segment centre line
    const at = f => d.x > 0 ? [-screen.x + f * W, seg.y0] : d.y > 0 ? [seg.x0, -screen.y + f * H]
                                                                   : [seg.x0, -screen.y + (1 - f) * H]
    const place = ([x, y]) => {
        ninja.x = x; ninja.y = y
        if (screen.lastNinja !== undefined)
            screen.lastNinja = {ninja: ninja, x: x, y: y}
    }
    const cycle = (vx, vy) => {
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.speedX = vx; ninja.speedY = vy - g
        const before = frac(ninja.x, ninja.y), cam = [-screen.x, -screen.y]
        calcPhysics()
        const mx = -screen.x - cam[0], my = -screen.y - cam[1]
        return [before, frac(ninja.x, ninja.y), mx * d.x + my * d.y, mx * d.y - my * d.x]
    }
    const rows = []
    const record = (phase, r, vel) => rows.push([phase, r[0], r[1], vel, r[2], r[3]])
    // approach: the centre line through the earlier joins, then 0.6 view
    // heights into the segment past its start: the camera is moving along
    // the segment and the phases end before it turns toward the next join
    const pts = [[ninja.x, segs[0].y0]]
    for (let i = 0; i < index; ++i)
        pts.push([segs[i].x1, segs[i].y1])
    pts.push([seg.x0 + d.x * 0.6 * H, seg.y0 + d.y * 0.6 * H])
    for (let k = 0; k + 1 < pts.length; ++k) {
        const [x0, y0] = pts[k], [x1, y1] = pts[k + 1]
        const len = Math.hypot(x1 - x0, y1 - y0)
        const ux = (x1 - x0) / len, uy = (y1 - y0) / len
        for (let s = 0; s < len; s += v) {
            ninja.x = x0 + ux * s; ninja.y = y0 + uy * s
            record('approach', cycle(ux * v, uy * v), ux * v * d.x + uy * v * d.y)
        }
    }
    const second = physicsTicksPerSecond * cyclesPerTick
    // behind
    place(at(0.15))
    for (let n = 0; n < (0.33 - 0.15) * extent / v; ++n)
        record('behind', cycle(d.x * v, d.y * v), v)
    // cross
    for (let n = 0; n < second; ++n)
        record('cross', cycle(d.x * v, d.y * v), v)
    // still
    place(at(0.55))
    for (let n = 0; n < 0.5 * second; ++n)
        record('still', cycle(0, 0), 0)
    // backward
    for (let n = 0; n < (0.55 - 0.40) * extent / v; ++n)
        record('backward', cycle(-d.x * v, -d.y * v), -v)
    const end = Math.hypot(ninja.x - seg.x0, ninja.y - seg.y0)
    return {dir: seg.dir, segLength: seg.length, endAlong: end, extent, v, trigger,
            sameNinja: ninja === n0, deaths: lethalDeaths - deaths0, rows}
}'''


def r4(x):
    return round(x, 4)


def analyse(drive):
    """Per phase the rule checks and the values head-numbers.json keeps"""
    x, slack = drive['trigger'], drive['v'] / drive['extent']
    rows = drive['rows']
    phase = lambda name: [r for r in rows if r[0] == name]  # noqa: E731
    out = {'segLength': r4(drive['segLength']), 'endAlong': r4(drive['endAlong']), 'extent': r4(drive['extent']),
           'v': r4(drive['v']), 'slack': r4(slack),
           'phaseCyclesCamAcross': sum(1 for r in rows if r[0] != 'approach' and abs(r[5]) > EPS)}
    rs = phase('approach')
    out['approach'] = {'cycles': len(rs), 'endFwdFrac': r4(rs[-1][2])}
    for name in ('behind', 'still', 'backward'):
        rs = phase(name)
        moved = [r for r in rs if r[4] > EPS]
        out[name] = {'cycles': len(rs), 'fracRange': [r4(min(r[1] for r in rs)), r4(max(r[1] for r in rs))],
                     'cyclesCamMoved': len(moved), 'camMoveSum': r4(sum(r[4] for r in rs)),
                     'firstMovedFrac': r4(moved[0][1]) if moved else None}
    rs = phase('cross')
    first = next((k for k, r in enumerate(rs) if r[1] > x + EPS), None)
    after = rs[first:] if first is not None else []
    out['cross'] = {
        'cycles': len(rs), 'firstPastCycle': first,
        'cyclesPastNotMoved': sum(1 for r in after if r[4] <= EPS),
        'cyclesOffLine': sum(1 for r in after if abs(r[2] - x) > slack + EPS),
        'maxFwdFrac': r4(max(r[2] for r in rs)), 'minFwdFracPast': r4(min(r[2] for r in after)) if after else None,
        'endFwdFrac': r4(rs[-1][2]),
        'cyclesMovedBehind': sum(1 for r in rs if r[4] > EPS and r[1] < x - slack - EPS)}
    back = [r for r in rows if r[4] < -EPS]
    out['never'] = {'cycles': len(rows), 'cyclesCamBackward': len(back),
                    'minCamMove': r4(min(r[4] for r in rows))}
    return out


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
        (cls.out / 'head-numbers.json').write_text(json.dumps(cls.numbers, separators=(',', ':')) + '\n')

    def drive(self, corridor):
        if corridor not in self.drives:
            script, index = CORRIDORS[corridor]
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
            self.addCleanup(context.close)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(self.url)
            wait_for_boot_run(page)
            page.evaluate(SEED_COURSE, COURSES[script])
            drive = page.evaluate(DRIVE, index)
            drive['errors'] = errors
            result = analyse(drive)
            self.drives[corridor] = (drive, result)
            self.numbers[corridor] = result
            print(f'{corridor}: {json.dumps(result, separators=(",", ":"))}', file=sys.stderr)
        drive, result = self.drives[corridor]
        self.assertEqual(drive['dir'], corridor)
        self.assertEqual(drive['errors'], [])
        self.assertTrue(drive['sameNinja'])
        self.assertEqual(drive['deaths'], 0)
        # the phases ran with the camera on a straight piece of its path (no
        # motion across the segment), the ninja inside the segment
        self.assertEqual(result['phaseCyclesCamAcross'], 0)
        self.assertLess(drive['endAlong'], drive['segLength'])
        return result

    def check_no_move(self, corridor, phase):
        r = self.drive(corridor)[phase]
        self.assertGreater(r['cycles'], 0)
        self.assertEqual(r['cyclesCamMoved'], 0, f'{corridor} {phase}: camera moved ({r})')

    def check_cross(self, corridor):
        r = self.drive(corridor)['cross']
        self.assertIsNotNone(r['firstPastCycle'], f'{corridor}: the ninja never crossed the line ({r})')
        self.assertEqual(r['cyclesMovedBehind'], 0, f'{corridor}: camera moved before the line ({r})')
        self.assertEqual(r['cyclesPastNotMoved'], 0, f'{corridor}: camera stood with the ninja past the line ({r})')
        self.assertEqual(r['cyclesOffLine'], 0, f'{corridor}: the ninja left the line ({r})')

    def check_never_backward(self, corridor):
        r = self.drive(corridor)['never']
        self.assertEqual(r['cyclesCamBackward'], 0, f'{corridor}: camera moved backward ({r})')

    def test_right_behind(self):
        self.check_no_move('right', 'behind')

    @unittest.expectedFailure
    def test_right_cross(self):
        self.check_cross('right')

    def test_right_still(self):
        self.check_no_move('right', 'still')

    def test_right_backward(self):
        self.check_no_move('right', 'backward')

    def test_right_never_backward(self):
        self.check_never_backward('right')

    @unittest.expectedFailure
    def test_up_behind(self):
        self.check_no_move('up', 'behind')

    @unittest.expectedFailure
    def test_up_cross(self):
        self.check_cross('up')

    def test_up_still(self):
        self.check_no_move('up', 'still')

    def test_up_backward(self):
        self.check_no_move('up', 'backward')

    def test_up_never_backward(self):
        self.check_never_backward('up')

    @unittest.expectedFailure
    def test_down_behind(self):
        self.check_no_move('down', 'behind')

    @unittest.expectedFailure
    def test_down_cross(self):
        self.check_cross('down')

    def test_down_still(self):
        self.check_no_move('down', 'still')

    def test_down_backward(self):
        self.check_no_move('down', 'backward')

    def test_down_never_backward(self):
        self.check_never_backward('down')

    natural = None

    def run_natural(self):
        """The natural run in its own process (it starts its own Playwright),
        once per class; returns the seed's summary"""
        cls = type(self)
        if cls.natural is None:
            out = self.out / 'natural'
            out.mkdir(parents=True, exist_ok=True)
            with open(out / 'run.log', 'w') as log:
                proc = subprocess.run([sys.executable, str(Path(__file__).with_name('momentum_natural_run.py')),
                                       str(NATURAL_SEED), str(out)], stdout=log, stderr=subprocess.STDOUT)
            data = json.loads((out / 'baseline.json').read_text()) if proc.returncode == 0 else {}
            cls.natural = {'returncode': proc.returncode, 'summary': data.get('seeds', {}).get(str(NATURAL_SEED)),
                           'head': data.get('head')}
            s = cls.natural['summary']
            keep = ('frames', 'maxFwdFrac', 'maxFwdFracInView', 'framesBeyondTrigger', 'beyondByDir',
                    'framesMovedWithoutRule', 'movedWhileNinjaVelNotForward', 'movedWhileBehindTrigger',
                    'framesOutOfView', 'death', 'pageErrors')
            self.numbers['natural'] = {k: s[k] for k in keep} if s else cls.natural
            print(f'natural seed {NATURAL_SEED}: {json.dumps(self.numbers["natural"], separators=(",", ":"))}',
                  file=sys.stderr)
        return cls.natural

    # Must pass: the run itself completed (a crash is not an expected failure)
    def test_natural_seed1_ran(self):
        n = self.run_natural()
        self.assertEqual(n['returncode'], 0, 'see natural/run.log')
        self.assertEqual(n['head'], self.numbers['head'])
        self.assertEqual(n['summary']['pageErrors'], [])
        self.assertTrue(n['summary']['frames'] == momentum_natural_run.FRAMES or n['summary']['death'] is not None)

    @unittest.expectedFailure
    def test_natural_seed1(self):
        s = self.run_natural()['summary']
        self.assertIsNotNone(s)
        self.assertEqual(s['framesBeyondTrigger'], 0)
        self.assertEqual(s['framesMovedWithoutRule'], 0)
        self.assertEqual(s['framesOutOfView'], 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
