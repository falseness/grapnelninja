"""Validate advance coverage using complete fixtures through real checker main."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from test_obstacle_evidence_catalog import CHECKER_PATH, VIEWPORTS, checker


class ObstacleEvidenceFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)
        spacing, self.advance = [], []
        for width, height in VIEWPORTS:
            scale = height / 1000
            viewport_width = width / scale
            camera_x = -123.5
            visible_right = -camera_x + viewport_width
            left = visible_right + 100
            spacing.append(dict(width=width, height=height, measurements=[
                dict(template=name, passed=True, predecessorRight=left,
                     newGroupLeft=left + .1 * width / scale, scale=scale)
                for name in sorted(checker.TEMPLATES)
            ]))
            creations = [dict(template=name, passed=True, initializing=False,
                              canvasWidth=width, canvasHeight=height, id=index + 1,
                              left=left, predecessorRight=left - .1 * width / scale,
                              cameraX=camera_x, scale=scale, visibleRight=visible_right)
                         for index, name in enumerate(sorted(checker.TEMPLATES))]
            coverage = [dict(phase=phase, frame=index, cameraX=camera_x, scale=scale,
                             viewportWidth=viewport_width, visibleRight=visible_right,
                             requiredRight=visible_right + viewport_width,
                             generatedRight=visible_right + viewport_width, passed=True)
                        for index, phase in enumerate(sorted(checker.COVERAGE_PHASES))]
            self.advance.append(dict(width=width, height=height,
                                     creations=creations, coverage=coverage))
        self.write('spacing.json', spacing)
        (self.out / 'live').mkdir()
        events = [dict(self.advance[0]['creations'][i], run=0, gapPassed=True,
                       offscreenPassed=True, expectedPixelGap=.1 * VIEWPORTS[0][0])
                  for i in range(3)]
        initial = dict(events[0], id=0, initializing=True)
        samples = []
        for index in range(11):
            name = f'sample-{index}.png'
            Image.new('RGB', (2, 2), (index, 0, 0)).save(self.out / 'live' / name)
            samples.append(dict(screenshot=name, elapsed=index * 3 + .05))
        hashes = {str(CHECKER_PATH): hashlib.sha256(CHECKER_PATH.read_bytes()).hexdigest()}
        self.write('live/run.json', dict(passed=True, wallSeconds=30, spawns=[initial] + events,
                                       gameplayEventCount=3, restarts=0, runs=[dict(id=0)],
                                       samples=samples, sourceHashes=hashes))
        for name in ('live/console-errors.log', 'live/page-errors.log', 'browser-errors.log'):
            (self.out / name).write_text('')
        (self.out / 'unit-tests.log').write_text('OK\n')
        (self.out / 'spawn.log').write_text('\n'.join(
            f'PASS {name}:' for name in sorted(checker.TEMPLATES) + ['classic']))
        self.write('exit-statuses.json', {f'command-{i}': 0 for i in range(5)})
        self.write('source-hashes.json', hashes)

    def write(self, name, value):
        (self.out / name).write_text(json.dumps(value))

    def run_checker(self):
        self.write('advance.json', self.advance)
        with patch.object(sys, 'argv', [str(CHECKER_PATH), str(self.out)]), redirect_stdout(io.StringIO()):
            checker.main()


class ObstacleEvidenceCoverageTests(ObstacleEvidenceFixture, unittest.TestCase):
    def test_valid_coverage_accepted_and_preserved(self):
        self.run_checker()
        measurements = json.loads((self.out / 'measurements.json').read_text())
        self.assertEqual(len(measurements), 3)
        for row, original in zip(measurements, self.advance):
            self.assertEqual((row['width'], row['height']), (original['width'], original['height']))
            self.assertEqual(row['coverage'], original['coverage'])
        print('PASS valid coverage accepted', flush=True)

    def test_invalid_coverage_rejected_at_every_viewport(self):
        mutations = [
            ('missing', 'missing or empty records', lambda row: row.pop('coverage')),
            ('empty', 'missing or empty records', lambda row: row.update(coverage=[])),
            ('failed flag', 'failed flag', lambda row: row['coverage'][0].update(passed=False)),
            ('shortfall', 'generatedRight shortfall', lambda row: row['coverage'][0].update(
                generatedRight=row['coverage'][0]['requiredRight'] - 1, passed=True)),
        ]
        for phase in sorted(checker.COVERAGE_PHASES):
            mutations.append(('missing phase', 'missing phase',
                              lambda row, phase=phase: row.update(coverage=[
                                  r for r in row['coverage'] if r['phase'] != phase])))
        for field in ('viewportWidth', 'visibleRight', 'requiredRight'):
            mutations.append(('inconsistent bounds', f'inconsistent {field}',
                              lambda row, field=field: row['coverage'][0].update(
                                  {field: row['coverage'][0][field] + 1})))
        for field in ('cameraX', 'scale', 'viewportWidth', 'visibleRight',
                      'requiredRight', 'generatedRight'):
            for value in (float('nan'), float('inf'), -float('inf')):
                mutations.append(('nonfinite', f'nonfinite or invalid {field}',
                                  lambda row, field=field, value=value:
                                  row['coverage'][0].update({field: value})))
        for value in (0, -1):
            mutations.append(('invalid scale', 'scale must be positive',
                              lambda row, value=value: row['coverage'][0].update(scale=value)))
        # Also defeat mutually consistent reported bounds based on a false camera.
        mutations.append(('inconsistent bounds', 'inconsistent visibleRight',
                          lambda row: row['coverage'][0].update(cameraX=0)))
        for index, viewport in enumerate(VIEWPORTS):
            for label, reason, mutate in mutations:
                with self.subTest(viewport=viewport, mutation=label, reason=reason):
                    original = json.loads(json.dumps(self.advance[index]))
                    try:
                        mutate(self.advance[index])
                        with self.assertRaisesRegex(AssertionError, '^coverage: ' + reason + '$'):
                            self.run_checker()
                        self.assertFalse((self.out / 'measurements.json').exists())
                    finally:
                        self.advance[index] = original
            print(f'PASS invalid coverage rejected at {viewport[0]}x{viewport[1]}: '
                  f'{len(mutations)} separate mutations', flush=True)
        print('PASS invalid coverage rejected: missing, empty, missing phase, failed flag, '
              'shortfall, inconsistent bounds, nonfinite', flush=True)


if __name__ == '__main__':
    unittest.main()
