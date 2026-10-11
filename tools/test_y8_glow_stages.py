"""Cheap checks for tools/y8_glow_stages.py (TASK-276): no browser.

Arm enumeration and bracketing order, stage cost arithmetic and tiers from
synthetic means, frozen level-0 box conversion, trace span attribution,
timing/trace instrumentation separation and no hook marker in the shipped
runtime.
"""
import subprocess
import unittest

import y8_feature_cost as fc
import y8_glow_stages as gs


class ArmTests(unittest.TestCase):
    def test_arms_per_renderer_and_bracketing_controls(self):
        self.assertEqual(gs.arms_for('ambient'), ['source-replay', 'blur-frozen', 'composite-off', 'chain-off', 'feature-off'])
        self.assertEqual(gs.arms_for('player'), ['source-replay', 'blur-frozen', 'composite-off', 'exclusion-off', 'chain-off'])
        r1, r2 = gs.sequence('player', 'r1'), gs.sequence('player', 'r2')
        self.assertEqual(r1[0], gs.CONTROL) and self.assertEqual(r1[-1], gs.CONTROL)
        self.assertEqual(r2[1:-1], r1[1:-1][::-1])
        self.assertEqual(len({gs.case_name('player', a, 'bad', 'r1', i) for i, a in enumerate(r1)}), len(r1))

    def test_every_arm_names_a_stage_and_frozen_arms_are_labelled_replay(self):
        for name, arm in gs.ARMS.items():
            self.assertIn(arm['stage'], ('source', 'blur', 'composite', 'exclusion', 'chain', 'feature'))
            if arm['needs_frozen']:
                self.assertIn('DIAGNOSTIC REPLAY', arm['label'])
        self.assertEqual(gs.RENDERERS['player']['exclusion'], True)
        self.assertEqual(gs.RENDERERS['ambient']['exclusion'], False)
        self.assertNotIn('ambient', gs.ARMS['exclusion-off']['renderers'])


class CostTests(unittest.TestCase):
    def table(self, renderer, controls, arms):
        by_rep = {rep: {gs.CONTROL: list(controls[rep]), **arms[rep]} for rep in gs.REPS}
        return gs.stage_table(by_rep, noise_max=5.0, renderer=renderer)

    def test_savings_against_mean_of_bracketing_controls_and_tiers(self):
        t = self.table('player', {'r1': (100.0, 104.0), 'r2': (98.0, 102.0)},
                       {'r1': {'source-replay': 80.0, 'blur-frozen': 101.0, 'composite-off': 70.0, 'exclusion-off': 96.0, 'chain-off': 50.0},
                        'r2': {'source-replay': 90.0, 'blur-frozen': 99.0, 'composite-off': 72.0, 'exclusion-off': 103.0, 'chain-off': 52.0}})
        rows = t['rows']
        self.assertEqual(rows['source-replay']['saving_ms'], [22.0, 10.0])
        self.assertEqual(rows['source-replay']['tier'], 'REPEATED_SAVING')
        self.assertEqual(rows['blur-frozen']['tier'], 'WITHIN_NOISE')  # +1 / +1 ms
        self.assertEqual(rows['composite-off']['tier'], 'REPEATED_SAVING')
        self.assertEqual(rows['exclusion-off']['saving_ms'], [6.0, -3.0])
        self.assertEqual(rows['exclusion-off']['tier'], 'WITHIN_NOISE')  # sign flips
        self.assertEqual(t['derived']['update']['tier'], 'NONE_BY_CONSTRUCTION')
        self.assertEqual(t['derived']['additivity']['sum_source_blur_composite_ms'], [55.0, 39.0])
        self.assertEqual(t['derived']['additivity']['discrepancy_ms'], [3.0, -9.0])

    def test_ambient_update_is_feature_off_minus_chain_off(self):
        t = self.table('ambient', {'r1': (120.0, 120.0), 'r2': (120.0, 120.0)},
                       {'r1': {'source-replay': 110.0, 'blur-frozen': 118.0, 'composite-off': 90.0, 'chain-off': 70.0, 'feature-off': 60.0},
                        'r2': {'source-replay': 108.0, 'blur-frozen': 119.0, 'composite-off': 88.0, 'chain-off': 72.0, 'feature-off': 64.0}})
        self.assertEqual(t['derived']['update']['saving_ms'], [10.0, 8.0])
        self.assertEqual(t['derived']['update']['tier'], 'REPEATED_SAVING')

    def test_classify_edge_cases(self):
        self.assertEqual(gs.classify([6.0, 4.0], 5.0), 'CONSISTENT_SAVING')
        self.assertEqual(gs.classify([-6.0, -7.0], 5.0), 'REPEATED_COST')
        self.assertEqual(gs.classify([None, 7.0], 5.0), 'INCOMPLETE')
        self.assertEqual(gs.classify([2.0, 3.0], 5.0), 'WITHIN_NOISE')

    def test_missing_arm_gives_none_not_crash(self):
        by_rep = {'r1': {gs.CONTROL: [100.0, 100.0], 'source-replay': 90.0, 'blur-frozen': None, 'composite-off': 80.0,
                         'exclusion-off': 99.0, 'chain-off': 60.0},
                  'r2': {gs.CONTROL: [100.0, 100.0], 'source-replay': 90.0, 'blur-frozen': 95.0, 'composite-off': 80.0,
                         'exclusion-off': 99.0, 'chain-off': 60.0}}
        t = gs.stage_table(by_rep, 5.0, 'player')
        self.assertEqual(t['rows']['blur-frozen']['tier'], 'INCOMPLETE')
        self.assertEqual(t['derived']['additivity']['sum_source_blur_composite_ms'][0], None)


class FrozenBoxTests(unittest.TestCase):
    def test_level0_box_inverts_destination_scaling_and_clamps(self):
        self.assertEqual(gs.level0_box([0, 0, 1280, 720], [320, 180], [1280, 720]), [0, 0, 320, 180])
        self.assertEqual(gs.level0_box([100, 380, 200, 500], [320, 180], [1280, 720]), [25, 95, 50, 125])
        self.assertEqual(gs.level0_box([-8, -8, 1300, 730], [320, 180], [1280, 720]), [0, 0, 320, 180])
        self.assertIsNone(gs.level0_box(None, [320, 180], [1280, 720]))


class TraceTests(unittest.TestCase):
    def test_skia_events_attributed_to_stage_spans_inside_window(self):
        ut = 'blink.user_timing'
        sk = 'disabled-by-default-skia'
        events = [
            {'cat': ut, 'name': 'fcWindowStart', 'ph': 'R', 'ts': 1000},
            {'cat': ut, 'name': 'source', 'ph': 'b', 'id': '1', 'ts': 1100},
            {'cat': sk, 'name': 'drawRect', 'ph': 'X', 'ts': 1150, 'dur': 20},
            {'cat': ut, 'name': 'source', 'ph': 'e', 'id': '1', 'ts': 1300},
            {'cat': ut, 'name': 'blur', 'ph': 'X', 'ts': 1400, 'dur': 100},
            {'cat': sk, 'name': 'drawImageRect', 'ph': 'X', 'ts': 1450, 'dur': 30},
            {'cat': sk, 'name': 'drawImageRect', 'ph': 'X', 'ts': 1600, 'dur': 5},  # between stages
            {'cat': sk, 'name': 'drawRect', 'ph': 'X', 'ts': 900, 'dur': 50},  # before the window
            {'cat': ut, 'name': 'fcWindowEnd', 'ph': 'R', 'ts': 2000},
            {'cat': sk, 'name': 'drawRect', 'ph': 'X', 'ts': 2100, 'dur': 50},  # after the window
        ]
        p = gs.trace_profile(events)
        self.assertEqual(p['window_us'], {'start': 1000, 'end': 2000})
        self.assertEqual(p['stage_spans'], {'source': 1, 'blur': 1})
        self.assertEqual(p['per_stage_events']['source'], {f'{sk}|drawRect': {'count': 1, 'dur_us': 20}})
        self.assertEqual(p['per_stage_events']['blur'], {f'{sk}|drawImageRect': {'count': 1, 'dur_us': 30}})
        self.assertEqual(p['skia_outside_glow_stages'], {f'{sk}|drawImageRect': {'count': 1, 'dur_us': 5}})
        self.assertEqual(p['top_events_in_window'][f'{sk}|drawRect']['count'], 1)

    def test_timing_instrumentation_has_no_trace_or_readback_calls(self):
        for script in (gs.STAGE_INSTRUMENT, gs.LOAD_FROZEN, gs.RENDERER_STATE, fc.INSTRUMENT):
            for forbidden in ('getImageData', 'toDataURL', 'performance.mark', 'performance.measure', 'Tracing'):
                self.assertNotIn(forbidden, script)
        self.assertIn('performance.measure', gs.TRACE_INSTRUMENT)
        self.assertIn('toDataURL', gs.FREEZE)  # readback confined to the freeze pass
        self.assertNotIn('--trace', ' '.join(gs.capture_argv('r', 'o', 'bad', 'player', 'control', 'c',
                                                              type('A', (), {'window_ms': 1, 'warmup_ms': 1})())))


class RuntimeTests(unittest.TestCase):
    def test_no_hook_marker_in_shipped_runtime(self):
        tracked = subprocess.check_output(['git', 'ls-files', '--', '*.html', '*.js', '*.css'], cwd=fc.ROOT, text=True).split()
        for name in tracked:
            if name.startswith('tools/'):
                continue
            self.assertNotIn(fc.MARKER, (fc.ROOT / name).read_text(errors='replace'), name)

    def test_prior_exclusions_exist(self):
        for p in gs.PRIOR_EXCLUSIONS:
            self.assertTrue((fc.ROOT / p['path']).exists(), p['path'])


if __name__ == '__main__':
    unittest.main()
