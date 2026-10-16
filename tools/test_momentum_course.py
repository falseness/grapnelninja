"""Momentum course model: elements/momentumcourse.js segment generator.

Samples MomentumCourse in the page and checks the course rules over more
than 1000 segments: first segment 'right', no up<->down adjacency, segments
joined end-to-start, lengths inside GAMEPLAY.momentumCourse [minLen, maxLen]
and a right share of at least 40%. Math.random is drawn only while a
segment is generated.

MOMENTUM_COURSE_EVIDENCE_DIR (default: artifacts/TASK-003) receives
course-sample.json. Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
SEGMENTS = 1200


class MomentumCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.out = Path(os.environ.get('MOMENTUM_COURSE_EVIDENCE_DIR',
                                      ROOT / 'artifacts/TASK-003'))
        context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
        cls.addClassCleanup(context.close)
        cls.page = context.new_page()
        cls.errors = []
        cls.page.on('pageerror', lambda e: cls.errors.append(str(e)))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.options = cls.page.evaluate('({...GAMEPLAY.momentumCourse})')
        cls.segments = cls.page.evaluate(f'new MomentumCourse().take({SEGMENTS})')

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_sample_size(self):
        print('segments:', len(self.segments), 'options:', self.options)
        self.assertEqual(len(self.segments), SEGMENTS)
        self.assertGreater(len(self.segments), 1000)
        for s in self.segments:
            self.assertIn(s['dir'], ('right', 'up', 'down'))

    def test_first_segment_right(self):
        first = self.segments[0]
        print('first:', first)
        self.assertEqual(first['dir'], 'right')
        self.assertEqual((first['x0'], first['y0']), (0, 0))

    def test_no_up_down_adjacency(self):
        violations = adjacency_violations(self.segments)
        after_vertical = [b['dir'] for a, b in zip(self.segments, self.segments[1:])
                          if a['dir'] != 'right']
        print('adjacency violations:', violations,
              'non-right after vertical:', sum(d != 'right' for d in after_vertical))
        self.assertEqual(violations, 0)
        self.assertTrue(all(d == 'right' for d in after_vertical))

    def test_continuity(self):
        gaps = [(i, a['x1'], a['y1'], b['x0'], b['y0'])
                for i, (a, b) in enumerate(zip(self.segments, self.segments[1:]))
                if (a['x1'], a['y1']) != (b['x0'], b['y0'])]
        print('continuity gaps:', len(gaps))
        self.assertEqual(gaps, [])

    def test_segment_geometry(self):
        for s in self.segments:
            dx, dy = s['x1'] - s['x0'], s['y1'] - s['y0']
            expected = {'right': (s['length'], 0), 'up': (0, -s['length']),
                        'down': (0, s['length'])}[s['dir']]
            self.assertAlmostEqual(dx, expected[0], places=6)
            self.assertAlmostEqual(dy, expected[1], places=6)

    def test_length_bounds(self):
        lengths = [s['length'] for s in self.segments]
        print('length min/max:', min(lengths), max(lengths),
              'bounds:', self.options['minLen'], self.options['maxLen'])
        self.assertGreaterEqual(min(lengths), self.options['minLen'])
        self.assertLessEqual(max(lengths), self.options['maxLen'])

    def test_right_share(self):
        counts = direction_counts(self.segments)
        share = counts['right'] / len(self.segments)
        print('counts:', counts, 'right share:', round(share, 4))
        self.assertGreaterEqual(share, 0.40)
        # Both vertical directions occur
        self.assertGreater(counts['up'], 0)
        self.assertGreater(counts['down'], 0)

    def test_random_only_on_generation(self):
        draws = self.page.evaluate('''() => {
            const course = new MomentumCourse()
            const original = Math.random
            let calls = 0
            Math.random = () => { calls++; return original() }
            try {
                course.take(50)
                const generated = calls
                course.take(50); course.segment(10); course.segment(49)
                return {generated, reread: calls - generated}
            } finally { Math.random = original }
        }''')
        print('Math.random draws:', draws)
        self.assertGreater(draws['generated'], 0)
        self.assertEqual(draws['reread'], 0)

    def test_write_sample(self):
        sample = {
            'counts': direction_counts(self.segments),
            'adjacencyViolations': adjacency_violations(self.segments),
            'segments': len(self.segments),
            'options': self.options,
            'first20': [[s['dir'], round(s['length'], 3), round(s['x0'], 3),
                         round(s['y0'], 3), round(s['x1'], 3), round(s['y1'], 3)]
                        for s in self.segments[:20]],
        }
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / 'course-sample.json'
        path.write_text(json.dumps(sample, separators=(',', ':')))
        print('wrote', path)


def direction_counts(segments):
    counts = {'right': 0, 'up': 0, 'down': 0}
    for s in segments:
        counts[s['dir']] += 1
    return counts


def adjacency_violations(segments):
    return sum({a['dir'], b['dir']} == {'up', 'down'}
               for a, b in zip(segments, segments[1:]))


if __name__ == '__main__':
    unittest.main()
