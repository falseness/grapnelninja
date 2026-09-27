"""Mutate complete live evidence independently and invoke actual checker main."""
from copy import deepcopy
import json
import unittest

from test_obstacle_evidence_coverage import ObstacleEvidenceFixture


class ObstacleEvidenceTimelineTests(ObstacleEvidenceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.live = json.loads((self.out / 'live/run.json').read_text())

    def test_valid_live_timeline(self):
        # Real TASK-058 probe times include browser startup/scheduling overhead.
        offsets = [i * 3 for i in range(11)], [
            .8233, 4.4953, 6.9632, 9.5772, 12.4608, 15.4621,
            18.4294, 21.3816, 24.5219, 27.3552, 30.3926,
        ], [1 + i * 2.9 for i in range(11)]
        for elapsed in offsets:
            with self.subTest(first=elapsed[0], last=elapsed[-1]):
                live = deepcopy(self.live)
                for sample, seconds in zip(live['samples'], elapsed):
                    sample['elapsed'] = seconds
                self.write('live/run.json', live)
                self.run_checker()
        print('PASS valid live timeline accepted', flush=True)
        print('PASS first-sample offset: 0.8233s to 30.3926s; 1s tolerance boundary accepted', flush=True)

    def test_invalid_live_timelines(self):
        mutations = [
            ('duplicate path', 'duplicate screenshot path',
             lambda s: s[1].update(screenshot=s[0]['screenshot'])),
            ('missing elapsed', 'elapsed must be finite numeric seconds',
             lambda s: s[1].pop('elapsed')),
            ('negative elapsed', 'elapsed must be nonnegative',
             lambda s: s[0].update(elapsed=-.01)),
            ('zero span', 'elapsed must be strictly increasing',
             lambda s: [r.update(elapsed=0) for r in s]),
            ('reversed order', 'elapsed must be strictly increasing', lambda s: s.reverse()),
            ('short capture', 'short capture',
             lambda s: [r.update(elapsed=i * 2.9) for i, r in enumerate(s)]),
            ('late start', 'first sample must be within 1 second',
             lambda s: [r.update(elapsed=r['elapsed'] + 2) for r in s]),
            ('path alias', 'duplicate screenshot path',
             lambda s: s[1].update(screenshot='./' + s[0]['screenshot'])),
        ]
        for value in (float('nan'), float('inf'), -float('inf'), '3', True, None):
            mutations.append(('nonfinite elapsed', 'elapsed must be finite numeric seconds',
                              lambda s, value=value: s[1].update(elapsed=value)))
        for label, diagnostic, mutate in mutations:
            with self.subTest(mutation=label):
                live = deepcopy(self.live)
                mutate(live['samples'])
                self.write('live/run.json', live)
                self.assertTrue(live['passed'])
                self.assertGreaterEqual(live['wallSeconds'], 30)
                with self.assertRaisesRegex(AssertionError, 'live timeline: .*' + diagnostic) as error:
                    self.run_checker()
                print(f'PASS rejected {label}: {error.exception}', flush=True)

        # Independently corrupt image contents while leaving all metadata valid.
        self.write('live/run.json', self.live)
        path = self.out / 'live' / self.live['samples'][0]['screenshot']
        valid_png = path.read_bytes()
        for label, content in [('invalid image', b'not an image'),
                               ('truncated image', valid_png[:45])]:
            with self.subTest(mutation=label):
                path.write_bytes(content)
                with self.assertRaisesRegex(AssertionError, 'live image: sample 0 cannot decode') as error:
                    self.run_checker()
                print(f'PASS rejected {label}: {error.exception}', flush=True)
        print('PASS invalid live timelines rejected: duplicate path, missing elapsed, nonfinite elapsed, '
              'negative elapsed, zero span, reversed order, short capture, invalid image', flush=True)


if __name__ == '__main__':
    unittest.main()
