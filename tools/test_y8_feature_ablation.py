"""Cheap checks for tools/y8_feature_ablation.py (TASK-272).

Feature table completeness, classification rules against the control-control
spread, inactive arms never credited, no hooks in the shipped runtime, and one
short browser run per feature proving that disabling a feature's drawing leaves
physics steps, particle updates, trail points, score and world state unchanged.
"""
import subprocess
import unittest

import y8_feature_ablation as ab
import y8_feature_cost as fc

EIGHT = ['ambient-glow', 'player-glow', 'obstacle-lighting', 'cave-background', 'player-trail', 'particles',
         'world-geometry', 'hud']


class FeatureTableTests(unittest.TestCase):
    def test_eight_named_features_with_hooks(self):
        self.assertEqual(list(ab.FEATURES), EIGHT)
        for name, spec in ab.FEATURES.items():
            self.assertIn(f'skip("{name}"', spec['install'], name)
            self.assertTrue(spec['removes'] and spec['active'] and spec['flags'], name)
        self.assertEqual(ab.QUAD, ('control', 'candidate', 'candidate', 'control'))
        self.assertEqual(ab.case_name('hud', 'control', 'bad', 1), 'hud-control-bad-desktop-s4-w1')

    def test_classification_against_control_spread(self):
        self.assertEqual(ab.classify([-8.0, -6.0, -9.0, -7.5], True, 3.0), 'REPEATED_SAVING')
        self.assertEqual(ab.classify([-8.0, -6.0, -9.0, -7.5], True, 3.0, 1.0), 'REPEATED_SAVING')
        self.assertEqual(ab.classify([-8.0, -2.0, -9.0, -7.5], True, 3.0, 1.0), 'CONSISTENT_SAVING')
        self.assertEqual(ab.classify([-8.0, -0.5, -9.0, -7.5], True, 3.0, 1.0), 'INCONSISTENT')
        self.assertEqual(ab.classify([-8.0, 6.0, -9.0, -7.5], True, 3.0), 'INCONSISTENT')
        self.assertEqual(ab.classify([-1.0, 2.0, -2.5, 0.5], True, 3.0), 'NO_BENEFIT')
        self.assertEqual(ab.classify([-2.5, 2.0, -2.5, 0.5], True, 3.0, 1.0), 'NO_BENEFIT')
        self.assertEqual(ab.classify([-80.0, -60.0, -90.0, -75.0], False, 3.0), 'INACTIVE')
        self.assertEqual(ab.classify([], True, 3.0), 'MISSING')

    def test_no_diagnostic_hooks_in_shipped_runtime(self):
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=fc.ROOT, text=True).splitlines()
        runtime = [n for n in tracked if n.endswith(fc.RUNTIME_SUFFIXES) and not n.startswith('tools/')]
        self.assertGreater(len(runtime), 20)
        for name in runtime:
            text = (fc.ROOT / name).read_text(errors='replace')
            self.assertNotIn(fc.MARKER, text, name)
            self.assertNotIn('skip("', text, name)
            self.assertNotIn('featureActive', text, name)


class StateEqualityTests(unittest.TestCase):
    def test_disabled_feature_drawing_keeps_simulation_unchanged(self):
        frames = 150
        reference = ab.simulate(None, 'bad', frames)
        self.assertEqual(reference['errors'], [])
        self.assertEqual(reference['ablated'], [])
        self.assertEqual(reference['skipped'], {})
        self.assertEqual(reference['frames'], frames)
        self.assertGreaterEqual(reference['steps'], 100)
        self.assertGreaterEqual(reference['particleUpdates'], frames)
        self.assertGreater(reference['particleCount'], 0)
        self.assertGreater(reference['trackPoints'], 1)
        self.assertEqual(ab.equality(reference, ab.simulate(None, 'bad', frames)), [], 'reference not deterministic')
        for feature in EIGHT:
            with self.subTest(feature=feature):
                r = ab.simulate(feature, 'bad', frames)
                self.assertEqual(r['errors'], [])
                self.assertEqual(r['ablated'], [ab.FEATURES[feature]['removes']])
                self.assertGreater(r['skipped'].get(feature, 0), 0, 'hook never reached')
                self.assertEqual(ab.equality(reference, r), [], feature)
                print(f'PASS {feature} drawing disabled ({r["skipped"][feature]} skipped draw calls): physics steps='
                      f'{r["steps"]} particle updates={r["particleUpdates"]} particles={r["particleCount"]} '
                      f'track points={r["trackPoints"]} score={r["score"]} ninja={r["ninja"]} unchanged', flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
