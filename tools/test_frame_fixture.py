"""Run the shared single-template fixture against real Chromium game objects."""
from pathlib import Path
import subprocess
import unittest

from browser_test_support import start_browser_test
from verification_scenarios import expected, frames, motion, setup
from verification_support import assert_near, baseline_route, load_baseline_sources


ROOT = Path(__file__).resolve().parents[1]
# 2201dd3 is the last intentional frame geometry change (Frame 4 cube, gray rects,
# obstacle distances). Frame 1 was added after it.
BASELINE = '2201dd3'
BASELINE_FRAMES = [frame for frame in frames if frame != 'frame1Elements']


class FrameFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        files = subprocess.check_output(
            ['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
        cls.baseline = load_baseline_sources(BASELINE, files)

    def assert_members(self, members, types):
        self.assertEqual(len(members), len(types))
        self.assertEqual([e['type'] for e in members], types)
        for element in members:
            self.assertEqual(len(element['points']),
                             3 if element['type'] == 'Triangle' else 4)

    def sample(self, frame, types, width, height, baseline=False):
        page = self.browser.new_page(viewport={'width': width, 'height': height})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        try:
            if baseline:
                page.route('**/*', baseline_route(self.baseline))
            page.goto(self.url)
            row = page.evaluate(setup, frame)
            for key in ['initial', 'raw']:
                self.assert_members(row[key], types)
            identity = '''() => {
                const elements = floors[1].elements;
                const targets = elements.filter(e => e instanceof Triangle || e instanceof JumpingCube);
                return elements.length > 0 &&
                    elements.every(e => e.generationGroupId === elements[0].generationGroupId) &&
                    dynamic.length === targets.length &&
                    dynamic.every((e, i) => e === targets[i]);
            }'''
            self.assertTrue(page.evaluate(identity))
            page.evaluate('window.fixtureMembers = floors[1].elements.slice()')
            moving = page.evaluate(motion)
            self.assertEqual(moving['substeps'], 14400)
            self.assertEqual(len(moving['samples']), 30)
            for sample in moving['samples']:
                self.assert_members(sample, types)
            self.assertEqual([s['type'] for s in moving['stats']],
                             [t for t in types if t in ['Triangle', 'JumpingCube']])
            self.assertTrue(page.evaluate(identity))
            self.assertTrue(page.evaluate('''() => floors[1].elements.length === fixtureMembers.length &&
                floors[1].elements.every((e, i) => e === fixtureMembers[i])'''))
            return row
        finally:
            page.close()
            self.assertEqual(errors, [], f'{frame}: browser errors')

    def test_current_and_baseline(self):
        current = {}
        cases = 0
        for width, height in [(1920, 1080), (1280, 720), (1600, 720)]:
            for frame, types in zip(frames, expected):
                row = self.sample(frame, types, width, height)
                if width == 1920:
                    current[frame] = row
                cases += 1
                print(f'PASS current {width}x{height} {frame}: initial/raw types and counts; '
                      'dynamic identity; 30 isolated motion samples; browser errors=0', flush=True)
        self.assertEqual(cases, 3 * len(frames))
        print(f'PASS current frame fixture: {cases} cases', flush=True)
        cases = 0
        for frame, types in zip(frames, expected):
            if frame not in BASELINE_FRAMES:
                continue
            row = self.sample(frame, types, 1920, 1080, baseline=True)
            # Match the viewport verifier's existing numeric tolerance and compare
            # complete snapshots, including exact object and polygon cardinality.
            assert_near(row, current[frame], frame, rel_tol=1e-12,
                        abs_tol=1e-10, require_finite=False)
            cases += 1
            print(f'PASS baseline {BASELINE} 1920x1080 {frame}: initial/raw match current; '
                  'dynamic identity; 30 isolated motion samples; browser errors=0', flush=True)
        self.assertEqual(cases, len(BASELINE_FRAMES))
        print(f'PASS baseline frame fixture: {cases} cases', flush=True)


if __name__ == '__main__':
    unittest.main()
