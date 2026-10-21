"""Smooth momentum camera (TASK-006; the camera rule of 2026-10-20).

Starts momentum on the scripted course R R U R R D R (the TASK-004 draws, see
test_momentum_borders, after two long right segments), stops the rAF loop and drives the ninja along the
course centre line at the ninja's speed cap (GAMEPLAY.momentumMaxSpeed) through
the turns right->up->right->down->right, to the middle of segment 6. The bad
obstacle floor is removed: obstacles still overlap the centre line (TASK-018)
and would hit the driven ninja, so the only lethal checks left are the
camera's (left behind, left edge).

Frame rate: frame-skip emulation of the fixed-step loop. runFixedPhysics runs
one physics() per rendered frame at 60 fps and two at 30 fps
(computePhysicsSteps, maxPhysicsStepsPerFrame 2), so the 30 fps run calls
physics() twice per frame and samples the camera once per frame.

Per frame, from camera positions (top-left world corner = -screen.x,
-screen.y) in view heights, dt = 1/fps:
- the camera's displacement is at most the ninja's (the driven speed along
  the centre line) * 1.05 + the X catch-up step
  (GAMEPLAY.momentumCamera.catchUpHeightRatio a cycle) + 1 world unit (no
  snap at a turn),
  and its progress (segmentIndex, then its position along the segment's
  direction) never decreases (never backwards). The per-axis speed rule
  (never faster than the ninja on either axis) is
  test_momentum_view_trigger's;
- the ninja stays inside the view, >= 10% of the view from the edge in its
  travel direction; no lethal death, no restart;
- the 30 fps trajectory matches the 60 fps one at the same physics ticks.

MOMENTUM_SMOOTH_EVIDENCE_DIR (default /tmp/momentum-camera-smooth: a bare
run must not rewrite the TASK-006 evidence) receives
camera-trace-60.json / camera-trace-30.json ([frame, segDir, camX, camY, vX,
vY, ninjaX, ninjaY, progress], world units and world units per second), smoothness.json and
turn-strip.png (before / during / after the right->up turn, 60 fps run).

BadCameraXTests: bad mode on a seeded Math.random with the rAF loop stopped,
600 physics() frames; screen.y stays 0 and screen.x per frame equals
BAD_CAMERA_REFERENCE (a capture of the same drive on the pre-change tree, see
capture_bad_camera). Requires Playwright Chromium. No remote requests.
"""
import json
import math
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import DIRS, SCRIPT
from test_momentum_camera import SEED_COURSE, START

ROOT = Path(__file__).resolve().parents[1]
SPEED_HEIGHT_RATIO = 0.06
# The drive runs at the effective cap GAMEPLAY.momentumMaxSpeed *
# momentumMotionScale(1) per physics cycle, the fastest the ninja moves (the
# camera follows its speed per axis, like bad mode); MOMENTUM_SMOOTH_SPEED=fast
# drives at SPEED_HEIGHT_RATIO height per tick instead (above the cap: a
# teleport the camera does not follow)
AT_CAP = os.environ.get('MOMENTUM_SMOOTH_SPEED') != 'fast'
# The TASK-004 draws after two long right segments (draws: segment 0 length,
# right-after-right, its length): the camera cruises for more than 10 frames
# at 30 fps before the first turn (the TASK-004 segment 0 ends 2 frames in)
SMOOTH_SCRIPT = [0.99, 0.1, 0.99] + SCRIPT[1:]
SMOOTH_DIRS = ['right'] + DIRS[:6]
LAST_SEGMENT = 6
# Centre-line points, one per physics tick, from the ninja's start through
# segment last - 1 plus half of segment last: [x, y, dir, segment index]
PATH = '''([last, step]) => {
    const points = []
    for (let i = 0; i <= last; ++i) {
        const s = momentumCourse.segment(i)
        // At least out of the corner box, where the camera switches (TASK-034)
        const box = momentumSegmentHalfWidth(momentumCourse.segment(last - 1)) + 2 * step
        const length = i < last ? s.length : Math.min(s.length, Math.max(s.length / 2, box))
        for (let d = i == 0 ? ninja.x - s.x0 : 0; d < length; d += step)
            points.push([s.x0 + (s.x1 - s.x0) * d / s.length, s.y0 + (s.y1 - s.y0) * d / s.length, s.dir, i])
    }
    return points
}'''
# ticks: per frame, the path points of its physics() calls
DRIVE = '''([frames, step, first]) => {
    const out = []
    const v = step / cyclesPerTick
    frames.forEach((ticks, k) => {
        for (const [x, y, dir] of ticks) {
            grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
            ninja.invulnerableMs = 1e9
            ninja.x = x; ninja.y = y
            ninja.speedX = dir == 'right' ? v : 0
            ninja.speedY = dir == 'up' ? -v : dir == 'down' ? v : 0
            physics()
        }
        out.push([first + k, screen.getSegment().dir, -screen.x, -screen.y, ninja.x, ninja.y,
                  screen.segmentIndex, screen.hasLeftBehind(ninja),
                  // progress: segment, then the camera's position along it
                  screen.segmentIndex * 1e7 + (-screen.x * segmentDirection(screen.getSegment().dir).x -
                                               screen.y * segmentDirection(screen.getSegment().dir).y)])
    })
    return out
}'''
BAD_DRIVE = '''() => {
    let s = 987654321
    Math.random = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648
    startGame('bad')
    cancelAnimationFrame(game)
    const xs = [], ys = new Set()
    for (let frame = 0; frame < 600; ++frame) {
        ninja.invulnerableMs = 1e9
        if (frame % 60 == 0) { ninja.speedY = -0.004 * height; ninja.speedX = 0.004 * height }
        physics()
        xs.push(screen.x); ys.add(screen.y)
    }
    return {xs, ys: [...ys], screenClass: screen.constructor.name, version}
}'''


def capture_bad_camera(root):
    """Bad-mode screen.x/screen.y for 600 seeded frames on the tree at root."""
    cleanups = []
    try:
        url, browser = start_browser_test(Path(root), cleanups.append)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        cleanups.append(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        wait_for_boot_run(page)
        result = page.evaluate(BAD_DRIVE)
        result['errors'] = errors
        return result
    finally:
        for cleanup in reversed(cleanups):
            cleanup()


def norm(x, y):
    return math.hypot(x, y)


class SmoothCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_SMOOTH_EVIDENCE_DIR', '/tmp/momentum-camera-smooth'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
        cls.addClassCleanup(context.close)
        cls.page = context.new_page()
        cls.errors = []
        cls.page.on('pageerror', lambda e: cls.errors.append(str(e)))
        cls.page.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.evaluate(SEED_COURSE, SMOOTH_SCRIPT)
        cls.options = cls.page.evaluate('({...GAMEPLAY.momentumCamera})')
        print('method: frame-skip emulation of runFixedPhysics, 60 fps = 1 physics() per '
              'frame, 30 fps = 2 physics() per frame; ninja speed '
              + ('GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) per physics cycle (effective cap)' if AT_CAP else
                 f'{SPEED_HEIGHT_RATIO} height per physics tick'), file=sys.stderr)
        print('GAMEPLAY.momentumCamera:', cls.options, file=sys.stderr)
        cls.runs = {fps: cls.run_course(fps) for fps in (60, 30)}
        cls.write_evidence()

    @classmethod
    def run_course(cls, fps):
        page = cls.page
        page.evaluate(START)
        # Camera only: bad obstacles on the centre line (they overlap the
        # course until TASK-018) would hit the driven ninja
        page.evaluate('floors = floors.filter(f => !(f instanceof MomentumObstacleFloor))')
        before = page.evaluate('window.startNinja = ninja, window.startScreen = screen, lethalDeaths')
        step = page.evaluate('GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) * cyclesPerTick' if AT_CAP else f'{SPEED_HEIGHT_RATIO} * height')
        points = page.evaluate(PATH, [LAST_SEGMENT, step])
        per = 60 // fps
        frames = [points[i:i + per] for i in range(0, len(points) - per + 1, per)]
        # 60 fps: screenshots around the right->up turn (first tick of segment 1)
        turn_tick = next(i for i, p in enumerate(points) if p[2] == 'up')
        shots = {turn_tick - 20: 'before', turn_tick + 8: 'during', turn_tick + 40: 'after'} \
            if fps == 60 else {}
        rows = []
        while len(rows) < len(frames):
            n = 40
            for shot in shots:
                if len(rows) < shot:
                    n = min(n, shot - len(rows))
            rows += page.evaluate(DRIVE, [frames[len(rows):len(rows) + n], step, len(rows)])
            if len(rows) in shots:
                page.evaluate('draw()')
                page.screenshot(path=str(cls.out / f'turn-{shots[len(rows)]}.png'))
        state = page.evaluate('''() => ({deaths: lethalDeaths, sameRun: ninja === startNinja && screen === startScreen,
            runInProgress, version, viewHeight: height / scale[version], viewWidth: width / scale[version],
            catchUp: GAMEPLAY.momentumCamera.catchUpHeightRatio * cyclesPerTick,
            radius: ninja.radius, segments: momentumCourse.segments.slice(0, 7).map(s => s.dir)})''')
        state['deaths'] -= before
        print(f'{fps} fps: {len(rows)} frames, {len(points)} physics ticks, state {state}', file=sys.stderr)
        return {'fps': fps, 'rows': rows, 'state': state, 'step': step}

    @classmethod
    def write_evidence(cls):
        summary = {}
        for fps, run in cls.runs.items():
            rows, dt = run['rows'], 1 / fps
            trace = []
            for k, r in enumerate(rows):
                p = rows[k - 1] if k else r
                trace.append([r[0], r[1], r[2], r[3], (r[2] - p[2]) / dt, (r[3] - p[3]) / dt, r[4], r[5], r[8]])
            run['trace'] = trace
            (cls.out / f'camera-trace-{fps}.json').write_text(json.dumps(
                {'fields': ['frame', 'segDir', 'camX', 'camY', 'vX', 'vY', 'ninjaX', 'ninjaY', 'progress'], 'fps': fps,
                 'units': 'world, world/s (from camera displacement)', 'trace': trace},
                separators=(',', ':')))
            run['metrics'] = cls.metrics(run)
            summary[fps] = {k: run['metrics'][k] for k in
                            ('maxStepRatio', 'maxStepRatioFrame', 'fasterFrames', 'backFrames',
                             'minMargin', 'minMarginFrame', 'turns')}
        summary['limits'] = {'cameraStep': 'ninja step * 1.05 + X catch-up + 1 world unit', 'progress': 'non-decreasing',
                             'minMargin': 0.1,
                             'units': 'steps in view heights; margin share of view; maxStepRatio: camera step / '
                                      'ninja step, the largest over frames with the camera moving'}
        (cls.out / 'smoothness.json').write_text(json.dumps(summary, separators=(',', ':')))
        names = ['before', 'during', 'after']
        files = [cls.out / f'turn-{n}.png' for n in names]
        if all(f.exists() for f in files):
            from PIL import Image
            images = [Image.open(f).convert('RGB') for f in files]
            w, h = images[0].size
            strip = Image.new('RGB', (3 * w // 2, h // 2))
            for i, image in enumerate(images):
                strip.paste(image.resize((w // 2, h // 2)), (i * w // 2, 0))
            strip.save(cls.out / 'turn-strip.png')
            for f in files:
                f.unlink()

    @classmethod
    def metrics(cls, run):
        rows, trace, state = run['rows'], run['trace'], run['state']
        fps, dt = run['fps'], 1 / run['fps']
        H, W = state['viewHeight'], state['viewWidth']
        # Per frame camera step (k >= 1), view heights; the ninja moves
        # step world units a physics tick along the centre line, 60 / fps
        # ticks a frame (the first frame from the ninja's start)
        step = [norm(t[4], t[5]) * dt / H for t in trace]
        ninja_step = run['step'] * (60 // fps) / H
        # plus the X catch-up (view heights a physics tick)
        limit = ninja_step * 1.05 + state['catchUp'] * (60 // fps) + 1 / H
        faster = [(rows[k][0], round(step[k] / ninja_step, 4)) for k in range(1, len(rows)) if step[k] > limit]
        ratios = [(step[k] / ninja_step, rows[k][0]) for k in range(1, len(rows))]
        back = [rows[k][0] for k in range(1, len(rows)) if rows[k][8] < rows[k - 1][8] - 1e-6]
        # Turns: frames where the camera's segment direction changes
        turns = [k for k in range(1, len(rows)) if rows[k][1] != rows[k - 1][1]]
        turn_checks = [{'frame': t, 'turn': f'{rows[t - 1][1]}->{rows[t][1]}',
                        'maxStepRatio': round(max(step[max(1, t - 10):t + 11]) / ninja_step, 4)} for t in turns]
        margins, inside = [], []
        for r in rows:
            camX, camY, x, y, d = r[2], r[3], r[4], r[5], r[1]
            margins.append((camX + W - x) / W if d == 'right' else
                           (y - camY) / H if d == 'up' else (camY + H - y) / H)
            inside.append(min(x - camX, camX + W - x) / W >= 0 and min(y - camY, camY + H - y) >= 0)
        return {'turns': turn_checks, 'margins': margins, 'inside': inside,
                'ninjaStep': ninja_step, 'stepLimit': limit, 'fasterFrames': faster, 'backFrames': back,
                'maxStepRatio': round(max(ratios)[0], 4), 'maxStepRatioFrame': max(ratios)[1],
                'minMargin': min(margins), 'minMarginFrame': rows[margins.index(min(margins))][0], 'turnList': [c['turn'] for c in turn_checks]}

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_course_and_turns(self):
        for fps, run in self.runs.items():
            with self.subTest(fps=fps):
                m = run['metrics']
                print(f'{fps} fps turns:', m['turnList'], 'at frames', [c['frame'] for c in m['turns']])
                self.assertEqual(run['state']['segments'], SMOOTH_DIRS)
                self.assertEqual(m['turnList'], ['right->up', 'up->right', 'right->down', 'down->right'])

    def test_camera_not_faster_than_ninja(self):
        # TASK-085: replaces the damped follow's maxAccel / maxJerk and turn
        # snap checks; the camera moves at most at the ninja's speed
        for fps, run in self.runs.items():
            with self.subTest(fps=fps):
                m = run['metrics']
                print(f'{fps} fps: max camera step / ninja step {m["maxStepRatio"]} at frame '
                      f'{m["maxStepRatioFrame"]} (limit 1.05 + catch-up + 1 world unit), frames over it {len(m["fasterFrames"])}; '
                      'per turn (+-10 frames): ' + ', '.join(f'{c["turn"]} {c["maxStepRatio"]}' for c in m['turns']))
                self.assertEqual(m['fasterFrames'][:5], [])

    def test_camera_never_backwards(self):
        for fps, run in self.runs.items():
            with self.subTest(fps=fps):
                m, rows = run['metrics'], run['rows']
                print(f'{fps} fps: progress {rows[0][8]:.1f} -> {rows[-1][8]:.1f}, frames going back {len(m["backFrames"])}')
                self.assertEqual(m['backFrames'][:5], [])
                self.assertGreater(rows[-1][8], rows[0][8])

    def test_ninja_in_view_with_margin(self):
        for fps, run in self.runs.items():
            with self.subTest(fps=fps):
                m = run['metrics']
                print(f'{fps} fps: min margin in travel direction {m["minMargin"]:.4f} of the view '
                      f'(limit 0.10), frames {len(m["margins"])}, all inside view {all(m["inside"])}')
                self.assertTrue(all(m['inside']))
                self.assertGreaterEqual(m['minMargin'], 0.10)

    def test_no_game_over(self):
        for fps, run in self.runs.items():
            with self.subTest(fps=fps):
                s = run['state']
                print(f'{fps} fps: lethal deaths {s["deaths"]}, same run {s["sameRun"]}, '
                      f'left behind frames {sum(1 for r in run["rows"] if r[7])}')
                self.assertEqual(s['deaths'], 0)
                self.assertTrue(s['sameRun'])
                self.assertTrue(s['runInProgress'])
                self.assertEqual(s['version'], 'momentum')
                self.assertFalse(any(r[7] for r in run['rows']))

    def test_frame_rate_independent(self):
        a, b = self.runs[60]['rows'], self.runs[30]['rows']
        H = self.runs[60]['state']['viewHeight']
        # 30 fps frame k ends after physics tick 2k + 1 = 60 fps frame 2k + 1
        diffs = [norm(r[2] - a[2 * k + 1][2], r[3] - a[2 * k + 1][3]) / H
                 for k, r in enumerate(b) if 2 * k + 1 < len(a)]
        print(f'30 vs 60 fps camera position at the same physics tick: {len(diffs)} frames, '
              f'max difference {max(diffs):.3e} view heights (tolerance 0.01)')
        self.assertGreater(len(diffs), 100)
        self.assertLessEqual(max(diffs), 0.01)


class BadCameraXTests(unittest.TestCase):
    def test_bad_camera_matches_reference(self):
        reference = os.environ.get('BAD_CAMERA_REFERENCE')
        if not reference:
            self.skipTest('BAD_CAMERA_REFERENCE not set')
        expected = json.loads(Path(reference).read_text())
        r = capture_bad_camera(ROOT)
        moved = len(set(r['xs']))
        print(f'bad mode: 600 frames, screen.y values {r["ys"]}, distinct screen.x {moved}, '
              f'final screen.x {r["xs"][-1]}, reference final {expected["xs"][-1]}, '
              f'identical {r["xs"] == expected["xs"]}')
        self.assertEqual(r['errors'], [])
        self.assertEqual(r['version'], 'bad')
        self.assertEqual(r['screenClass'], 'Screen')
        self.assertEqual(r['ys'], [0])
        self.assertEqual(len(r['xs']), 600)
        self.assertGreater(moved, 1)
        self.assertEqual(r['xs'], expected['xs'])


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--capture-bad':
        # python3 test_momentum_camera_smooth.py --capture-bad <tree root> > out.json
        print(json.dumps(capture_bad_camera(sys.argv[2]), separators=(',', ':')))
    else:
        unittest.main()
