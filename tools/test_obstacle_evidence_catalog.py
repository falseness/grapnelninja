"""Exercise catalog coverage through the real evidence checker's CLI entry point."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

from verification_scenarios import frames


EXPECTED_TEMPLATES = {
    'frame1Elements', 'frame3Triangle', 'frame4Elements',
    'frame5Rects', 'frame6Rects', 'frame7Elements', 'frame8Elements',
    'frame10Elements', 'frame11Elements', 'frame12Elements', 'frame13Elements', 'frame14Rects',
}
VIEWPORTS = [(772, 630), (1280, 720), (1920, 1080)]
CHECKER_PATH = Path(__file__).with_name('check-obstacle-evidence.py')
spec = importlib.util.spec_from_file_location('obstacle_evidence_checker', CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ObstacleEvidenceCatalogTests(unittest.TestCase):
    def test_exact_twelve_templates(self):
        self.assertEqual(len(EXPECTED_TEMPLATES), 12)
        self.assertEqual(len(frames), 12)
        self.assertEqual(set(frames), EXPECTED_TEMPLATES)
        self.assertEqual(checker.TEMPLATES, EXPECTED_TEMPLATES)

    def assert_coverage_failure(self, first_viewport, missing_template=None):
        # Put the viewport under test first: the deliberately invalid advance
        # coverage otherwise stops main before it can inspect later spacing rows.
        viewports = [first_viewport] + [v for v in VIEWPORTS if v != first_viewport]
        spacing = []
        advance = []
        for width, height in viewports:
            spacing.append(dict(width=width, height=height, measurements=[
                dict(template=name, passed=True, predecessorRight=100,
                     newGroupLeft=100 + .25 * width / .5, scale=.5)
                for name in sorted(EXPECTED_TEMPLATES)
                if not ((width, height) == first_viewport and name == missing_template)
            ]))
            # All viewport keys exist, but gameplay template coverage is invalid.
            advance.append(dict(width=width, height=height, creations=[]))

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / 'spacing.json').write_text(json.dumps(spacing))
            (out / 'advance.json').write_text(json.dumps(advance))
            with patch.object(sys, 'argv', [str(CHECKER_PATH), directory]):
                try:
                    checker.main()
                except AssertionError as error:
                    failure = traceback.extract_tb(error.__traceback__)[-1]
                else:
                    self.fail('Checker accepted invalid evidence')
            self.assertEqual(Path(failure.filename), CHECKER_PATH)
            self.assertEqual(failure.name, 'main')
            expected_line = (
                "assert {r['template'] for r in row['measurements']} == TEMPLATES"
                if missing_template else
                "assert {r['template'] for r in gameplay} == TEMPLATES"
            )
            self.assertEqual(failure.line, expected_line)
            self.assertFalse((out / 'measurements.json').exists())

    def test_complete_spacing_coverage_reaches_advance_validation(self):
        for viewport in VIEWPORTS:
            with self.subTest(viewport=viewport):
                self.assert_coverage_failure(viewport)

    def test_missing_spacing_template_rejected(self):
        for viewport in VIEWPORTS:
            for template in sorted(EXPECTED_TEMPLATES):
                with self.subTest(viewport=viewport, missing=template):
                    self.assert_coverage_failure(viewport, template)


if __name__ == '__main__':
    unittest.main()
