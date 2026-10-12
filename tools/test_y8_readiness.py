"""Unit test for the TASK-270 evaluator experiment (tools/y8_readiness_experiment.py).

Runs the experiment on the recorded fixture inputs under
artifacts/TASK-270/evaluator-experiment/ (the preserved old assembler, the
ticket snapshot it was run against, and the saved TASK-265 performance gate),
then asserts the report verdicts against the recorded fixtures-final/comparison.json.
Synthetic logic fixtures only: nothing here measures FPS or release acceptance.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import y8_readiness_experiment as experiment  # noqa: E402

FIXTURES = ROOT / 'artifacts/TASK-270/evaluator-experiment'
INPUTS = {
    'old-source': FIXTURES / 'old-assemble_y8_submission.py',
    'saved-gate': ROOT / 'artifacts/TASK-265/live-geometry/final-byte/performance/performance-gate.json',
    'tasks': FIXTURES / 'tasks-before.json',
}
RECORDED = FIXTURES / 'fixtures-final/comparison.json'
CASES = 18


def run_experiment(report):
    argv = ['y8_readiness_experiment.py', '--report', str(report)]
    for key, path in INPUTS.items():
        argv += ['--' + key, str(path)]
    with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()) as out:
        experiment.main()
    return out.getvalue()


class ReadinessExperiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [str(p) for p in [*INPUTS.values(), RECORDED] if not p.is_file()]
        if missing:
            raise unittest.SkipTest('recorded TASK-270 fixture inputs missing: ' + ', '.join(missing))
        cls.tmp = tempfile.TemporaryDirectory(prefix='test-y8-readiness-')
        cls.report = Path(cls.tmp.name) / 'report'
        cls.output = run_experiment(cls.report)
        cls.comparison = json.loads((cls.report / 'comparison.json').read_text())
        cls.recorded = json.loads(RECORDED.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_report_matches_recorded_verdicts(self):
        outcomes = self.comparison['outcomes']
        recorded = self.recorded['outcomes']
        self.assertEqual(len(outcomes), CASES)
        self.assertEqual([(o['case'], o['expected_ready']) for o in outcomes],
                         [(o['case'], o['expected_ready']) for o in recorded])
        self.assertTrue(self.comparison['synthetic'])
        self.assertFalse(self.comparison['release_acceptance'])
        for key in ('old_source_sha256', 'saved_gate_sha256'):
            self.assertEqual(self.comparison[key], self.recorded[key], key)
        for mine, theirs in zip(outcomes, recorded):
            with self.subTest(case=mine['case']):
                self.assertFalse(mine['old']['ready'], 'old readiness block must never pass a fixture')
                self.assertIs(mine['generalized']['all_required_local_pass'], mine['expected_ready'])
                self.assertIs(mine['generalized']['package_ready'], mine['expected_ready'])
                for flag in ('submission_ready', 'moderation_approved', 'uploaded'):
                    self.assertFalse(mine['generalized'][flag], flag)
                self.assertEqual(mine['generalized']['all_required_local_pass'],
                                 theirs['generalized']['all_required_local_pass'])
                self.assertEqual([r['verdict'] for r in mine['generalized']['performance_results']],
                                 [r['verdict'] for r in theirs['generalized']['performance_results']])
        by_case = {o['case']: o['generalized'] for o in outcomes}
        regressions = lambda name: sum(r['verdict'] == 'FAIL_MEASURED_REGRESSION' for r in by_case[name]['performance_results'])
        self.assertEqual(regressions('current_six_failures'), 6)
        self.assertEqual(regressions('one_failed_repetition'), 1)
        self.assertEqual(by_case['conditional_absolute_failure']['performance_results'][-1]['verdict'], 'FAIL_ABSOLUTE_THRESHOLD')
        self.assertEqual(sum(o['expected_ready'] for o in outcomes), 3)

    def test_report_directory_and_pass_lines(self):
        self.assertTrue((self.report / 'old-evaluator.py.txt').is_file())
        for outcome in self.comparison['outcomes']:
            case = self.report / outcome['case']
            self.assertTrue((case / 'outcome.json').is_file(), case)
            self.assertTrue((case / 'selection.json').is_file(), case)
            self.assertIn(f"PASS {outcome['case']}: old_ready=False generalized_ready={outcome['expected_ready']}", self.output)
        self.assertIn('PASS immutable snapshot survives changed upstream aliases; synthetic assembly rejected', self.output)
        self.assertIn(f'PASS finite comparison: {CASES} cases', self.output)
        pass_lines = [line for line in self.output.splitlines() if line.startswith('PASS ')]
        self.assertGreaterEqual(len(pass_lines), CASES + 2, pass_lines)
        self.assertFalse([line for line in self.output.splitlines() if line.startswith(('FAIL', 'Traceback'))], self.output)

    def test_refuses_to_overwrite_an_existing_report(self):
        with self.assertRaises(AssertionError):
            run_experiment(self.report)
        self.assertTrue((self.report / 'comparison.json').is_file(), 'existing report must be left untouched')


if __name__ == '__main__':
    unittest.main()
