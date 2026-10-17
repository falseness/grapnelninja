"""The first momentum shaft starts inside the view (TASK-024).

The camera never scrolls left, so a first join left of the start view would
hide the shaft's left wall for the whole shaft. At run start, the first
vertical segment's left wall face must be on screen and right of the camera
LeftWall, and the ninja must start before segment 0's end. Checked with the
shortest scripted first segment at three viewports and on 200 seeded courses.

MOMENTUM_COURSE_START_EVIDENCE_DIR (default artifacts/TASK-024) receives
course-start.json. Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('MOMENTUM_COURSE_START_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-024'))
# seg0: the shortest length; seg1: vertical (>= 40), up (< 50), mid length
SHORTEST_UP = [0.0, 0.9, 0.1, 0.5]
VIEWPORTS = [
    ('1280x720', {'viewport': {'width': 1280, 'height': 720}}),
    ('1024x768', {'viewport': {'width': 1024, 'height': 768}}),
    ('390x844-touch-landscape', {'viewport': {'width': 844, 'height': 390},
                                 'has_touch': True, 'is_mobile': True}),
]
RANDOM_COURSES = 200

# Draws come from the script, then from an LCG seeded per course
SEED_COURSE = '''() => {
    let script = [], k = 0, s = 1
    window.setCourseScript = (values, seed) => { script = values; k = 0; s = seed }
    const next = () => k < script.length ? script[k++]
        : ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648)
    const generate = MomentumCourse.prototype.generate
    MomentumCourse.prototype.generate = function() {
        const random = Math.random
        Math.random = next
        try { return generate.call(this) } finally { Math.random = random }
    }
}'''
START = '''([script, seed]) => {
    setCourseScript(script, seed)
    startGame('momentum')
    cancelAnimationFrame(game)
    let i = 0
    while (momentumCourse.segment(i).dir == 'right')
        ++i
    const shaft = momentumCourse.segment(i), s0 = momentumCourse.segment(0)
    const leftFace = shaft.x0 - GAMEPLAY.momentumBorders.halfWidth
    return {shaftIndex: i, shaftDir: shaft.dir, leftFace, screenX: screen.x,
            leftFaceOnScreen: leftFace + screen.x, leftWallX: screen.leftWall.x,
            ninjaX: ninja.x, seg0X1: s0.x1, seg0Length: s0.length}
}'''


class MomentumCourseStartTests(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / 'course-start.json').write_text(
            json.dumps(cls.results, separators=(',', ':')) + '\n')

    def open(self, options):
        context = self.browser.new_context(locale='en-US', **options)
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE)
        return page

    def check_start(self, r, label):
        self.assertGreaterEqual(r['leftFaceOnScreen'], 0, label)
        self.assertLessEqual(r['leftWallX'], r['leftFace'], label)
        self.assertLess(r['ninjaX'], r['seg0X1'], label)

    def test_shortest_first_segment(self):
        for name, options in VIEWPORTS:
            with self.subTest(viewport=name):
                r = self.open(options).evaluate(START, [SHORTEST_UP, 1])
                print(name, json.dumps(r, separators=(',', ':')))
                self.assertEqual((r['shaftIndex'], r['shaftDir']), (1, 'up'))
                self.check_start(r, name)
                MomentumCourseStartTests.results[name] = {
                    'leftFaceOnScreen': r['leftFaceOnScreen'], 'leftWallX': r['leftWallX'],
                    'seg0Length': r['seg0Length']}

    def test_random_courses(self):
        page = self.open(VIEWPORTS[0][1])
        worst = None
        for seed in range(1, RANDOM_COURSES + 1):
            r = page.evaluate(START, [[], seed])
            self.check_start(r, f'seed {seed}: {r}')
            if worst is None or r['leftFaceOnScreen'] < worst['leftFaceOnScreen']:
                worst = dict(r, seed=seed)
        print('random courses', RANDOM_COURSES, 'worst', json.dumps(worst, separators=(',', ':')))
        MomentumCourseStartTests.results['random-1280x720'] = {
            'courses': RANDOM_COURSES, 'minLeftFaceOnScreen': worst['leftFaceOnScreen'],
            'leftWallX': worst['leftWallX'], 'worstSeed': worst['seed']}


if __name__ == '__main__':
    unittest.main()
