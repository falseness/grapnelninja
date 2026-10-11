"""Cheap checks for tools/y8_feature_interaction.py (TASK-274): no browser.

Selection rule (summed positive median savings, tie-break by stage name, fewer
than three eligible), combination enumeration (all-on control first, reversed
order in repetition 2), interaction arithmetic (sum of singles, discrepancy,
classification, inconsistent repeats) and no hook marker in the shipped runtime.
"""
import subprocess
import unittest

import y8_feature_ablation as ab
import y8_feature_cost as fc
import y8_feature_interaction as fi


def decision(chill, main):
    """Synthetic TASK-273 decision.json block: {feature: (tier, median_delta_mean_ms)} per mode."""
    def block(d):
        return {'tiers': {f: d.get(f, ('NO_BENEFIT', 0.0))[0] for f in fi.FEATURES},
                'median_delta_mean_ms': {f: d.get(f, ('NO_BENEFIT', 0.0))[1] for f in fi.FEATURES},
                'noise_threshold_mean_ms': 10.0, 'noise_typical_mean_ms': 4.0}
    return {'chill': block(chill), 'main': block(main)}


class SelectionTests(unittest.TestCase):
    def test_sums_positive_medians_and_breaks_ties_by_name(self):
        d = decision(chill={'hud': ('REPEATED_SAVING', -30.0), 'particles': ('CONSISTENT_SAVING', -10.0),
                            'player-glow': ('NO_BENEFIT', 5.0), 'world-geometry': ('REPEATED_SAVING', -20.0)},
                     main={'hud': ('NO_BENEFIT', 8.0), 'particles': ('REPEATED_SAVING', -10.0),
                           'player-glow': ('REPEATED_SAVING', -20.0), 'world-geometry': ('NO_BENEFIT', 0.0)})
        r = fi.rank_stages(d)
        scores = {row['feature']: row['summed_positive_median_saving_ms'] for row in r['rows']}
        self.assertEqual(scores['hud'], 30.0)  # the +8 ms Main loss is not subtracted (positive part only)
        self.assertEqual(scores['particles'], 20.0)
        self.assertEqual(scores['player-glow'], 20.0)
        self.assertEqual(scores['world-geometry'], 20.0)
        # three-way tie at 20 ms resolved by stage name: particles < player-glow < world-geometry
        self.assertEqual(r['selected'], ['hud', 'particles', 'player-glow'])
        self.assertEqual(r['ties_resolved_by_stage_name'], [('particles', 'player-glow'), ('player-glow', 'world-geometry')])
        self.assertFalse(r['fewer_than_three'])
        self.assertEqual([row['feature'] for row in r['rows']][:4], ['hud', 'particles', 'player-glow', 'world-geometry'])

    def test_fewer_than_three_eligible_uses_all_and_records_why(self):
        d = decision(chill={'hud': ('REPEATED_SAVING', -30.0), 'particles': ('INCONSISTENT', -25.0)},
                     main={'hud': ('NO_BENEFIT', 1.0), 'particles': ('NO_BENEFIT', -40.0)})
        r = fi.rank_stages(d)
        self.assertEqual(r['selected'], ['hud'])  # particles saves more but is repeatable in neither mode
        self.assertTrue(r['fewer_than_three'])
        self.assertIn('only 1 stage(s) eligible', r['why'])
        none = fi.rank_stages(decision({}, {}))
        self.assertEqual(none['selected'], [])
        self.assertIn('negative selection result', none['why'])
        self.assertEqual(fi.combinations([]), [{'id': 'c', 'off': [], 'on': [], 'is_control': True, 'label': 'all-on (control)'}])


class CombinationTests(unittest.TestCase):
    def test_eight_combinations_control_first_reversed_second_repetition(self):
        combos = fi.combinations(['a', 'b', 'c'])
        self.assertEqual([c['id'] for c in combos], ['c000', 'c100', 'c010', 'c001', 'c110', 'c101', 'c011', 'c111'])
        self.assertTrue(combos[0]['is_control'] and combos[0]['off'] == [] and combos[0]['on'] == ['a', 'b', 'c'])
        self.assertEqual(combos[4]['off'], ['a', 'b'])
        self.assertEqual(combos[7]['off'], ['a', 'b', 'c'])
        self.assertEqual(len({tuple(c['off']) for c in combos}), 8)
        o = fi.orders(combos)
        self.assertEqual(o['r2'], o['r1'][::-1])
        self.assertEqual(o['r1'][0], 'c000')
        self.assertEqual(o['r2'][-1], 'c000')
        self.assertEqual(fi.case_name('c101', 'bad', 4, 'r2'), 'combo-c101-bad-desktop-s4-r2')
        self.assertEqual(len(fi.combinations(['a', 'b'])), 4)


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.combos = fi.combinations(['a', 'b', 'c'])

    def test_additive_and_sub_additive_with_consistent_repeats(self):
        means = {'c000': {'r1': 100.0, 'r2': 102.0},
                 'c100': {'r1': 70.0, 'r2': 72.0},      # a saves 30
                 'c010': {'r1': 90.0, 'r2': 92.0},      # b saves 10
                 'c001': {'r1': 95.0, 'r2': 97.0},      # c saves 5
                 'c110': {'r1': 60.0, 'r2': 62.0},      # a+b: 40 = 30 + 10 additive
                 'c101': {'r1': 80.0, 'r2': 82.0},      # a+c: 20 < 35 sub-additive
                 'c011': {'r1': 70.0, 'r2': 72.0},      # b+c: 30 > 15 super-additive
                 'c111': {'r1': 55.0, 'r2': 57.0}}      # all: 45 = 30+10+5 additive
        r = fi.analyse(self.combos, means, {'max': 3.0, 'typical': 1.0})
        self.assertEqual(r['control_control_ms'], 2.0)
        self.assertEqual(r['noise']['noise_max_ms'], 3.0)
        self.assertEqual(r['rows']['c100']['measured_saving_ms'], {'r1': 30.0, 'r2': 30.0})
        self.assertEqual(r['rows']['c110']['sum_of_single_savings_ms'], {'r1': 40.0, 'r2': 40.0})
        self.assertEqual(r['rows']['c110']['classification'], 'ADDITIVE')
        self.assertEqual(r['rows']['c101']['classification'], 'SUB_ADDITIVE')
        self.assertEqual(r['rows']['c101']['discrepancy_ms'], {'r1': -15.0, 'r2': -15.0})
        self.assertEqual(r['rows']['c011']['classification'], 'SUPER_ADDITIVE')
        self.assertEqual(r['rows']['c111']['classification'], 'ADDITIVE')
        self.assertEqual(r['rows']['c111']['pairwise_discrepancy_sum_ms'], {'r1': 0.0, 'r2': 0.0})
        self.assertEqual(r['rows']['c111']['three_way_residual_ms'], {'r1': 0.0, 'r2': 0.0})
        self.assertFalse(any(row['inconsistent_repeat'] for row in r['rows'].values()))
        self.assertTrue(r['rows']['c100']['beyond_noise_max_every_repeat'])
        self.assertTrue(r['rows']['c001']['beyond_noise_max_every_repeat'])  # 5 ms saving against noise_max 3
        weak = fi.analyse(self.combos, means, {'max': 6.0, 'typical': 4.0})
        self.assertFalse(weak['rows']['c001']['beyond_noise_max_every_repeat'])
        self.assertTrue(weak['rows']['c001']['beyond_noise_typical_every_repeat'])

    def test_inconsistent_repeat_and_inconclusive(self):
        means = {'c000': {'r1': 100.0, 'r2': 100.0},
                 'c100': {'r1': 70.0, 'r2': 99.0},      # a: 30 then 1 -> inconsistent (difference beyond noise)
                 'c010': {'r1': 90.0, 'r2': 90.0},
                 'c001': {'r1': 95.0, 'r2': 105.0},     # c: +5 then -5 -> sign disagrees
                 'c110': {'r1': 60.0, 'r2': 89.0},      # discrepancy 0 both -> additive even though a is inconsistent
                 'c101': {'r1': 80.0, 'r2': 80.0},      # discrepancy -15 then +24 -> inconclusive
                 'c011': {'r1': 85.0, 'r2': 85.0},
                 'c111': {'r1': 55.0, 'r2': 55.0}}
        r = fi.analyse(self.combos, means, {'max': 3.0, 'typical': 1.0})
        self.assertTrue(r['rows']['c100']['inconsistent_repeat'])
        self.assertTrue(r['rows']['c001']['inconsistent_repeat'])
        self.assertFalse(r['rows']['c001']['repeat_sign_agrees'])
        self.assertFalse(r['rows']['c010']['inconsistent_repeat'])
        self.assertEqual(r['rows']['c110']['classification'], 'ADDITIVE')
        self.assertEqual(r['rows']['c101']['classification'], 'INCONCLUSIVE')
        self.assertEqual(fi.classify_interaction({'r1': -4.0, 'r2': -3.5}, 3.0), 'SUB_ADDITIVE')
        self.assertEqual(fi.classify_interaction({'r1': 4.0, 'r2': 3.5}, 3.0), 'SUPER_ADDITIVE')
        self.assertEqual(fi.classify_interaction({'r1': 4.0, 'r2': -3.5}, 3.0), 'INCONCLUSIVE')
        self.assertEqual(fi.classify_interaction({'r1': 1.0, 'r2': -3.0}, 3.0), 'ADDITIVE')

    def test_noise_uses_own_control_spread_when_larger(self):
        means = {c['id']: {'r1': 100.0, 'r2': 100.0} for c in self.combos}
        means['c000'] = {'r1': 100.0, 'r2': 112.0}
        r = fi.analyse(self.combos, means, {'max': 3.0, 'typical': 1.0})
        self.assertEqual(r['noise']['noise_max_ms'], 12.0)
        self.assertEqual(r['noise']['noise_typical_ms'], 12.0)


class RuntimeIsolationTests(unittest.TestCase):
    def test_combo_instrument_installs_every_task272_hook_by_name(self):
        for name, spec in ab.FEATURES.items():
            self.assertIn(name, fi.FEATURES)
            self.assertIn('skip("%s"' % name, spec['install'])
        self.assertIn('FC.featuresOff', fi.COMBO_INSTRUMENT)
        self.assertEqual(fi.combo_cfg(['hud', 'particles'])['off'], ['hud', 'particles'])

    def test_no_diagnostic_hooks_in_shipped_runtime(self):
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=fc.ROOT, text=True).splitlines()
        runtime = [n for n in tracked if n.endswith(fc.RUNTIME_SUFFIXES) and not n.startswith('tools/')]
        self.assertGreater(len(runtime), 20)
        for name in runtime:
            text = (fc.ROOT / name).read_text(errors='replace')
            for marker in (fc.MARKER, 'skip("', 'FC.samples', 'featuresOff'):
                self.assertNotIn(marker, text, name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
