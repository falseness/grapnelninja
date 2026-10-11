"""Unit tests for tools/y8_integration.py (TASK-282): no browser, no captures."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_cost as fc  # noqa: E402
import y8_glow_region as gr  # noqa: E402
import y8_integration as yi  # noqa: E402

ROOT = fc.ROOT


def synthetic_raw(case, dt_ms, backing=(1280, 720), total_ms=38000, order_utc='2026-10-11T00:00:00+00:00'):
    """A complete timing raw with constant frame intervals, summarised by the real harness code."""
    frames, t = [], 0.0
    while t <= total_ms:
        frames.append({'t': t, 'dt': None if not frames else dt_ms, 'canvas': list(backing),
                       'state': {'menu': False, 'paused': False, 'offer': False, 'hidden': False, 'ad': False}})
        t += dt_ms
    settings = {'mode': 'bad', 'profile': 'desktop', 'viewport': [1280, 720], 'dpr': 1, 'cpu_throttle': 1, 'seed': 4,
                'warmup_ms': yi.WARMUP_MS, 'window_ms': yi.WINDOW_MS, 'windows': yi.WINDOWS, 'replay_sha256': 'r', 'diagnostic': False, 'ablate': []}
    raw = {'case': case, 'settings': settings, 'frames': frames, 'excluded': [], 'deaths': [], 'dispatched': [],
           'dimensions': {'canvas': list(backing)}, 'densityPin': 'pinned', 'started_utc': order_utc, 'features': None, 'result': 'COMPLETE'}
    raw['summary'] = fc.summarize(raw)
    return raw


class SequenceTests(unittest.TestCase):
    def test_each_rep_has_all_three_trees_with_integrated_in_the_middle(self):
        for rep in yi.REPS:
            trees = [t for r, t in yi.SEQUENCE if r == rep]
            self.assertEqual(sorted(trees), sorted(yi.TREES))
            self.assertEqual(trees[1], 'integrated')

    def test_reference_order_alternates_between_reps(self):
        first = [[t for r, t in yi.SEQUENCE if r == rep][0] for rep in yi.REPS]
        self.assertEqual(first, ['control', 'original', 'control'])

    def test_identity_plan_covers_ten_cells_twice_with_unique_cases(self):
        plan = yi.identity_plan()
        cases = [yi.identity_case(p) for p in plan]
        self.assertEqual(len(plan), 20)
        self.assertEqual(len(set(cases)), 20)
        self.assertEqual(sum(1 for p in plan if p['tree'] == 'integrated'), 10)

    def test_case_name_tree_field_is_fourth(self):
        self.assertEqual(yi.case_name('touch', 'classic', 'p2', 'original', 14).split('-')[3], 'original')


class MetricTests(unittest.TestCase):
    def test_histogram_counts_every_interval_once(self):
        h = yi.histogram([5, 16.7, 40, 99.9, 100, 2000])
        self.assertEqual(sum(h['counts']), 6)
        self.assertEqual(h['counts'][0], 1)   # 5 ms in [0, 16.7)
        self.assertEqual(h['counts'][1], 1)   # 16.7 in [16.7, 33.3)
        self.assertEqual(h['counts'][-1], 1)  # 2000 in [1000, inf)

    def test_run_record_windows_and_minima(self):
        r = yi.run_record(synthetic_raw('desktop-bad-p1-control-i1', 100.0))
        self.assertEqual(len(r['windows_10s']), 3)
        self.assertAlmostEqual(r['mean_ms'], 100.0)
        self.assertAlmostEqual(r['min_10s_fps'], 10.0)
        self.assertEqual(r['tree'], 'control')
        self.assertEqual(sum(r['distribution']['counts']), r['intervals'])

    def test_pair_reduction_sign_and_order(self):
        a = synthetic_raw('desktop-bad-p1-control-i1', 100.0, order_utc='2026-10-11T00:00:00+00:00')
        b = synthetic_raw('desktop-bad-p1-integrated-i2', 90.0, order_utc='2026-10-11T00:01:00+00:00')
        p = yi.pair(a, b, 'control')
        self.assertAlmostEqual(p['reduction_fraction'], 0.1)
        self.assertEqual(p['worse_by_fraction'], 0.0)
        self.assertEqual(p['order'], 'reference first')
        slower = yi.pair(a, synthetic_raw('desktop-bad-p1-integrated-i2', 110.0), 'control')
        self.assertAlmostEqual(slower['worse_by_fraction'], 0.1)

    def test_pair_refuses_unequal_backing(self):
        a = synthetic_raw('desktop-bad-p1-control-i1', 100.0)
        b = synthetic_raw('desktop-bad-p1-integrated-i2', 100.0, backing=(1366, 768))
        with self.assertRaises(fc.EvidenceError):
            yi.pair(a, b, 'control')


class IdentityReportTests(unittest.TestCase):
    def write(self, out, p, pixels, state_extra=None, present=None):
        case = yi.identity_case(p)
        present = (p['tree'] == 'integrated') if present is None else present
        cps = [{'name': n, 'final_pixels_sha256': pixels, 'source_pixels_sha256': 's', 'final_sha256': 'f',
                'state': {**{k: 0 for k in gr.STATE_KEYS}, 'randomDraws': 7, 'canvas': [1280, 720], 'screen': [0, 0], **(state_extra or {})},
                'candidate': {'present': present}} for n in ('menu', 'start')]
        raw = {'case': case, 'result': 'COMPLETE', 'started_utc': '2026-10-11T00:00:00+00:00', 'settings': {'replay_sha256': 'same'},
               'checkpoints': cps, 'regionCalls': 10 if p['tree'] == 'integrated' else 0, 'runtime_body_sha256': 'b' if p['tree'] == 'integrated' else None}
        fc.dump(out / 'identity' / f'{case}.json', raw)

    def test_exact_different_and_missing_cells(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            plan = yi.identity_plan()
            cell_a = [p for p in plan if (p['engine'], p['context'], p['mode'], p['seed']) == ('chromium', 'dpr1', 'bad', 4)]
            cell_b = [p for p in plan if (p['engine'], p['context'], p['mode'], p['seed']) == ('chromium', 'dpr1', 'classic', 4)]
            for p in cell_a:
                self.write(out, p, 'px')
            for p in cell_b:
                self.write(out, p, 'px' if p['tree'] == 'control' else 'py', state_extra={'ninja': [1, 2, 3, 4]} if p['tree'] == 'integrated' else None)
            rep = yi.build_identity_report(out)
            self.assertEqual(rep['cells']['chromium/dpr1/bad/seed4']['result'], 'EXACT')
            diff = rep['cells']['chromium/dpr1/classic/seed4']
            self.assertEqual(diff['result'], 'DIFFERENT')
            self.assertEqual(diff['checkpoints'][0]['differing_state_keys'], ['ninja'])
            self.assertEqual(rep['cells']['firefox/dpr1/bad/seed4']['result'], 'MISSING')
            self.assertFalse(rep['exact_on_all_tested_engines'])
            self.assertFalse(rep['complete_matrix'])
            self.assertEqual(rep['exact_cells'], 1)


class IntegrationMapTests(unittest.TestCase):
    def test_runtime_markers_match_the_sealed_verdicts(self):
        src = (ROOT / 'render/effects.js').read_text()
        for task, c in yi.CANDIDATES.items():
            verdict = fc.load(ROOT / c['decision'])['verdict']
            present = any(m in src for m in c['markers'])
            self.assertEqual(present, verdict == 'ACCEPT', f'{task}: markers present={present} verdict={verdict}')
        self.assertEqual(gr.runtime_body_sha(ROOT), fc.load(ROOT / 'artifacts/TASK-280/decision.json')['candidate']['body_sha256'])

    def test_only_effects_js_changed_since_the_frozen_control(self):
        control = fc.load(yi.CONTROL_TASK_DIR / 'manifest.json')['source_revision']
        diff = yi.runtime_diff(control, fc.git('rev-parse', 'HEAD'))
        self.assertEqual([f['file'] for f in diff['changed_runtime_files']], ['render/effects.js'])

    def test_sealed_costs_cover_both_modes(self):
        for name, c in yi.SEALED_COSTS.items():
            self.assertIn('bad', c, name)
            self.assertIn('classic', c, name)
            self.assertTrue(c['source'] and c['lever'], name)


if __name__ == '__main__':
    unittest.main()
