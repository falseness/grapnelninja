"""Momentum camera (TASK-005): elements/momentumcamera.js.

Starts momentum on the scripted course R U R R D R ... (the TASK-004 draws,
see test_momentum_borders), stops the rAF loop and drives the ninja along the
course centre line: every frame sets ninja position/speed through
page.evaluate, then runs one physics() frame (cyclesPerTick physics steps).
Asserts, with the camera's own segment (screen.getSegment()):
- screen.y grows monotonically in the up segment (camera moves up) and
  shrinks monotonically in the down segment; it stays put in right segments
  that follow no vertical one;
- the camera never scrolls back in x: screen.x (= -camera left) never grows;
- borders and obstacles left behind below/above the view are deleted
  (screen.deletedBehind > 0);
- a ninja pushed out of view behind the travel direction (below the view in
  the up segment, above it in the down segment) is a lethal death, while
  out of view ahead of it is not.
BadCameraTests: in bad mode screen.y stays 0 for 600 frames of real play.

MOMENTUM_CAMERA_EVIDENCE_DIR (default: artifacts/TASK-005) receives
camera-trace.json ([frame, segDir, screen.x, screen.y, ninja.x, ninja.y]
every 10 frames) and up-segment.png.
Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import DIRS, SCRIPT

ROOT = Path(__file__).resolve().parents[1]
# Scripted MomentumCourse.generate draws; resetCourseScript() restarts them,
# so every momentum run gets the same course
SEED_COURSE = '''(script) => {
    let k = 0, s = 12345
    window.resetCourseScript = () => { k = 0; s = 12345 }
    const next = () => k < script.length ? script[k++]
        : ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648)
    const generate = MomentumCourse.prototype.generate
    MomentumCourse.prototype.generate = function() {
        const random = Math.random
        Math.random = next
        try { return generate.call(this) } finally { Math.random = random }
    }
    window.lethalDeaths = 0
    const lethal = onLethalDeath
    onLethalDeath = function() { lethalDeaths++; return lethal.apply(this, arguments) }
}'''
START = '''() => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
}'''
# Centre-line points from the ninja's start through segment last plus half
# of the next, step apart
PATH = '''([last, step]) => {
    const points = []
    for (let i = 0; i <= last + 1; ++i) {
        const s = momentumCourse.segment(i)
        const length = i <= last ? s.length : s.length / 2
        // The run starts with the ninja inside segment 0
        for (let d = i == 0 ? ninja.x - s.x0 : 0; d < length; d += step)
            points.push([s.x0 + (s.x1 - s.x0) * d / s.length, s.y0 + (s.y1 - s.y0) * d / s.length, s.dir])
    }
    return points
}'''
# Holds the ninja on the given path points, one physics() frame each
DRIVE = '''([points, step, first]) => {
    const frames = []
    const v = step / cyclesPerTick
    points.forEach(([x, y, dir], k) => {
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y
        ninja.speedX = dir == 'right' ? v : 0
        ninja.speedY = dir == 'up' ? -v : dir == 'down' ? v : 0
        physics()
        const frame = first + k
        if (frame % 10 == 0) draw()
        frames.push([frame, screen.getSegment().dir, screen.x, screen.y, ninja.x, ninja.y,
                     screen.hasLeftBehind(ninja), screen.segmentIndex])
    })
    return frames
}'''


def course_index(dir_name, occurrence=0):
    return [i for i, d in enumerate(DIRS) if d == dir_name][occurrence]


class MomentumCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_CAMERA_EVIDENCE_DIR',
                                      ROOT / 'artifacts/TASK-005'))
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
        cls.page.evaluate(SEED_COURSE, SCRIPT)
        cls.run_course()

    @classmethod
    def run_course(cls):
        page = cls.page
        page.evaluate(START)
        cls.step = page.evaluate('0.04 * height')
        # R U R R D, then half of the next right
        last = course_index('down')
        points = page.evaluate(PATH, [last, cls.step])
        cls.frames = []
        shot_frame = None
        up = course_index('up')
        while len(cls.frames) < len(points):
            chunk = points[len(cls.frames):len(cls.frames) + 50]
            cls.frames += page.evaluate(DRIVE, [chunk, cls.step, len(cls.frames)])
            if shot_frame is None and cls.frames[-1][7] == up and \
                    cls.frames[-1][3] > cls.frames[0][3] + page.evaluate('height'):
                page.evaluate('draw()')
                page.screenshot(path=str(cls.out / 'up-segment.png'))
                shot_frame = cls.frames[-1][0]
        cls.state = page.evaluate('''({deletedBehind: screen.deletedBehind, lethalDeaths,
            segments: momentumCourse.segments.slice(0, 6).map(s => s.dir),
            viewHeight: height / scale[version], runInProgress, version})''')
        trace = [f[:6] for f in cls.frames if f[0] % 10 == 0]
        (cls.out / 'camera-trace.json').write_text(json.dumps(
            {'fields': ['frame', 'segDir', 'screen.x', 'screen.y', 'ninja.x', 'ninja.y'],
             'course': cls.state['segments'], 'step': cls.step, 'frames': len(cls.frames),
             'upScreenshotFrame': shot_frame, 'samples': trace}, separators=(',', ':')))
        print('frames driven:', len(cls.frames), 'course:', cls.state['segments'],
              'deletedBehind:', cls.state['deletedBehind'], file=__import__('sys').stderr)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def frames_in(self, segment_index):
        return [f for f in self.frames if f[7] == segment_index]

    def test_course_and_drive(self):
        self.assertEqual(self.state['segments'], DIRS[:6])
        seen = []
        for f in self.frames:
            if not seen or seen[-1] != f[7]:
                seen.append(f[7])
        print('camera segments in order:', seen, [DIRS[i] for i in seen])
        self.assertEqual(seen, list(range(course_index('down') + 2)))
        self.assertEqual(self.state['lethalDeaths'], 0)
        self.assertTrue(all(not f[6] for f in self.frames), 'driven ninja never behind the camera')

    def assert_monotone(self, name, values, sign):
        steps = [b - a for a, b in zip(values, values[1:])]
        bad = [s for s in steps if s * sign < 0]
        print(f'{name}: {len(values)} frames, first {values[0]:.1f}, last {values[-1]:.1f}, '
              f'moving steps {sum(1 for s in steps if s)}, steps against direction {len(bad)}')
        self.assertEqual(bad, [], name)

    def test_screen_y_up_segment_monotone_up(self):
        ys = [f[3] for f in self.frames_in(course_index('up'))]
        self.assert_monotone('up segment screen.y non-decreasing', ys, 1)
        # The camera really climbed: most of the segment length
        segment_length = self.page.evaluate(f'momentumCourse.segment({course_index("up")}).length')
        self.assertGreater(ys[-1] - ys[0], 0.5 * segment_length)

    def test_screen_y_down_segment_monotone_down(self):
        ys = [f[3] for f in self.frames_in(course_index('down'))]
        self.assert_monotone('down segment screen.y non-increasing', ys, -1)
        segment_length = self.page.evaluate(f'momentumCourse.segment({course_index("down")}).length')
        self.assertGreater(ys[0] - ys[-1], 0.5 * segment_length)

    def test_screen_y_still_before_first_vertical(self):
        ys = {f[3] for f in self.frames_in(0)}
        print('segment 0 (right) screen.y values:', sorted(ys))
        self.assertEqual(ys, {0})

    def test_right_segments_settle_towards_previous_vertical(self):
        # After the up segment the camera only moves up; after down only down
        up, down = course_index('up'), course_index('down')
        ys = [f[3] for f in self.frames if up < f[7] < down]
        self.assert_monotone('right segments after up: screen.y non-decreasing', ys, 1)
        ys = [f[3] for f in self.frames if f[7] > down]
        self.assert_monotone('right segment after down: screen.y non-increasing', ys, -1)

    def test_screen_x_never_scrolls_back(self):
        # screen.x is the world -> view offset (= -camera left): a camera
        # moving right lowers it, so never scrolling back means it never grows
        xs = [f[2] for f in self.frames]
        self.assert_monotone('screen.x non-increasing (camera x non-decreasing)', xs, -1)
        self.assertLess(xs[-1], xs[0])

    def test_left_behind_vertically_deleted(self):
        print('elements deleted behind vertically:', self.state['deletedBehind'])
        self.assertGreater(self.state['deletedBehind'], 0)

    def push_out(self, segment_dir, side):
        """Restarts, drives into the middle of the segment, then pushes a
        vulnerable ninja just out of view on side ('behind' or 'ahead')."""
        page = self.page
        page.evaluate(START)
        index = course_index(segment_dir)
        # Up to the middle of the segment
        points = page.evaluate(PATH, [index - 1, self.step])
        for start in range(0, len(points), 100):
            page.evaluate(DRIVE, [points[start:start + 100], self.step, start])
        return page.evaluate('''([dir, side]) => {
            const before = {deaths: lethalDeaths, ninja, screen, camera: screen.y,
                            segment: screen.getSegment().dir}
            ninja.invulnerableMs = 0
            // Only the camera may kill: no obstacle where the ninja lands
            floors.forEach(f => { if (f instanceof MomentumObstacleFloor) f.elements = [] })
            const r = ninja.radius, view = height / scale[version]
            const below = -screen.y + view + 3 * r, above = -screen.y - 3 * r
            const behind = dir == 'up' ? below : above
            ninja.y = side == 'behind' ? behind : (dir == 'up' ? above : below)
            ninja.speedX = 0; ninja.speedY = 0
            calcPhysics()
            return {segment: before.segment, cameraY: before.camera,
                    deaths: lethalDeaths - before.deaths,
                    restarted: ninja !== before.ninja && screen !== before.screen,
                    newScreenY: screen.y, version, runInProgress}
        }''', [segment_dir, side])

    def test_out_of_view_behind_is_game_over(self):
        results = {}
        for dir_name in ('up', 'down'):
            for side in ('behind', 'ahead'):
                with self.subTest(dir=dir_name, side=side):
                    r = self.push_out(dir_name, side)
                    results[f'{dir_name}-{side}'] = r
                    print(f'{dir_name} segment, ninja out of view {side}:', r)
                    self.assertEqual(r['segment'], dir_name)
                    if side == 'behind':
                        self.assertEqual(r['deaths'], 1, r)
                        self.assertTrue(r['restarted'], r)
                        self.assertEqual(r['newScreenY'], 0, r)
                    else:
                        self.assertEqual(r['deaths'], 0, r)
                        self.assertFalse(r['restarted'], r)
                    self.assertEqual(r['version'], 'momentum')
                    self.assertTrue(r['runInProgress'], r)


class BadCameraTests(unittest.TestCase):
    def test_bad_screen_y_stays_zero(self):
        url, browser = start_browser_test(ROOT, self.addCleanup)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        wait_for_boot_run(page)
        page.evaluate("startGame('bad')")
        # Real play: the rAF loop runs physics; the ninja is thrown upwards
        # every 60 frames so the camera has vertical motion to (not) follow
        r = page.evaluate('''() => new Promise(resolve => {
            const ys = new Set(), modes = new Set()
            let frames = 0, minNinjaY = Infinity, maxNinjaY = -Infinity
            const tick = () => {
                if (frames % 60 == 0) ninja.speedY = -0.02 * height
                ys.add(screen.y); modes.add(version + ':' + screen.yAxisMotion)
                minNinjaY = Math.min(minNinjaY, ninja.y); maxNinjaY = Math.max(maxNinjaY, ninja.y)
                if (++frames < 600) requestAnimationFrame(tick)
                else resolve({frames, ys: [...ys], modes: [...modes],
                              ninjaYRange: maxNinjaY - minNinjaY, screenClass: screen.constructor.name})
            }
            requestAnimationFrame(tick)
        })''')
        print('bad mode:', r)
        self.assertEqual(r['frames'], 600)
        self.assertEqual(r['ys'], [0])
        self.assertEqual(r['modes'], ['bad:false'])
        self.assertEqual(r['screenClass'], 'Screen')
        self.assertGreater(r['ninjaYRange'], 0)
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
