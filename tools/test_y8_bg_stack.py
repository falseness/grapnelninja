"""Unit tests for tools/y8_bg_stack.py (no browser)."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_bg_stack as bs  # noqa: E402
import y8_feature_cost as fc  # noqa: E402


def raw(case, mode, scene, rep, arm, mean_ms, started, frames=300):
    """A synthetic COMPLETE timing raw with a constant active frame interval."""
    t, fr = 0.0, []
    for i in range(frames):
        fr.append({'t': t, 'dt': None if i == 0 else mean_ms, 'canvas': [1280, 720], 'state': {}})
        t += mean_ms
    settings = {'mode': mode, 'profile': 'desktop', 'viewport': [1280, 720], 'dpr': 1, 'cpu_throttle': 1, 'seed': 4,
                'warmup_ms': 0, 'window_ms': mean_ms * (frames - 2), 'windows': 1, 'replay_sha256': 'r', 'diagnostic': False,
                'scene': scene, 'rep': rep, 'arm': arm, 'instrumentation': 'no readback'}
    r = {'case': case, 'settings': settings, 'frames': fr, 'excluded': [], 'deaths': [], 'dispatched': [],
         'dimensions': {'canvas': [1280, 720]}, 'started_utc': started, 'result': 'COMPLETE', 'density': None}
    r['summary'] = fc.summarize(r)
    return r


class CandidateFile(unittest.TestCase):
    def test_candidate_defines_the_four_methods_and_installs_on_the_prototype(self):
        text = bs.candidate_text()
        methods = bs.extract_methods(text, bs.CANDIDATE_METHODS)
        for name in bs.CANDIDATE_METHODS:
            self.assertIsNotNone(methods[name], name)
            self.assertTrue(methods[name].startswith(f'    {name}('))
            self.assertTrue(methods[name].endswith('    }'))
        self.assertIn('Object.assign(BackgroundRenderer.prototype, methods)', text)
        self.assertNotIn(fc.MARKER, text, 'the candidate carries no harness marker')

    def test_candidate_keeps_the_gameplay_rng_reservation_and_draw_order(self):
        m = bs.extract_methods(bs.candidate_text(), bs.CANDIDATE_METHODS)
        self.assertIn('preserveGameplayRandomSequence(1, 40)', m['paint'])
        self.assertIn('preserveGameplayRandomSequence(2, 18)', m['paintMenu'])
        for body in (m['paint'], m['paintMenu']):
            order = [body.index(s) for s in ('clearAll', 'drawFarStack', 'preserveGameplayRandomSequence', 'drawNearLayer', 'drawVignette')]
            self.assertEqual(order, sorted(order))
        # the stack is keyed by every input except the x shift, which is applied at tiling time
        for part in ('this.canvas.width', 'this.canvas.height', 'shift.y', 'layer.key', 'colors.gradientTop', 'colors.hazeBottom'):
            self.assertIn(part, m['drawFarStack'])
        self.assertNotIn('transform.a,', m['drawFarStack'], 'raw transform floats drift per frame and must not be key parts')
        self.assertIn('transform.a === Math.fround(baseA)', m['drawFarStack'], 'exact base-transform guard')
        self.assertIn('const direct = this.bounds || !isBase', m['drawFarStack'])
        self.assertIn('setTransform(this.canvas.width / width, 0, 0, this.canvas.height / height, 0, 0)', m['buildFarStack'])
        self.assertIn("{x: shift.x, y: 0}", m['drawFarStack'])
        self.assertIn("{x: 0, y: shift.y}", m['buildFarStack'])
        self.assertIn('const direct = this.bounds || !isBase', m['drawFarStack'], 'window bars keep the direct path')

    def test_shipping_runtime_state_matches_a_non_accept_unless_integrated(self):
        src = (bs.ROOT / 'render/effects.js').read_text()
        if bs.runtime_has_candidate(bs.ROOT):
            runtime, cand = bs.methods_sha(src), bs.methods_sha(bs.candidate_text())
            self.assertEqual(runtime, cand, 'integrated bodies must equal the tested bodies')
        else:
            self.assertFalse(any(m in src for m in bs.CANDIDATE_MARKERS))

    def test_extract_methods_drops_object_literal_commas(self):
        text = "class X\n{\n    a()\n    {\n        return 1\n    }\n}\nconst o = {\n    a()\n    {\n        return 1\n    },\n}\n"
        first = bs.extract_methods(text.split('const o')[0], ('a',))['a']
        second = bs.extract_methods('const o' + text.split('const o')[1], ('a',))['a']
        self.assertEqual(first, second)


class TimingRule(unittest.TestCase):
    def pairs(self, control, candidate, order='cf'):
        c = raw('c', 'bad', 'replay', 'p1', 'current', control, '2026-01-01T00:00:00Z' if order == 'cf' else '2026-01-01T00:01:00Z')
        k = raw('k', 'bad', 'replay', 'p1', 'candidate', candidate, '2026-01-01T00:01:00Z' if order == 'cf' else '2026-01-01T00:00:00Z')
        return bs.pair_record(c, k)

    def test_pair_record_reduction_and_order(self):
        p = self.pairs(100.0, 90.0)
        self.assertAlmostEqual(p['reduction_fraction'], 0.10)
        self.assertEqual(p['worse_by_fraction'], 0.0)
        self.assertEqual(p['order'], 'control first')
        p = self.pairs(100.0, 108.0, order='kf')
        self.assertAlmostEqual(p['worse_by_fraction'], 0.08)
        self.assertEqual(p['order'], 'candidate first')

    def test_compare_refuses_mismatched_settings(self):
        c = raw('c', 'bad', 'replay', 'p1', 'current', 100.0, '2026-01-01T00:00:00Z')
        k = raw('k', 'classic', 'replay', 'p1', 'candidate', 90.0, '2026-01-01T00:01:00Z')
        with self.assertRaises(fc.EvidenceError):
            fc.compare(c, k)

    def test_rule_constants_and_statement(self):
        rule = bs.timing_rule()
        self.assertEqual(rule['min_median_reduction'], 0.05)
        self.assertEqual(rule['max_worse'], 0.05)
        self.assertEqual(rule['acceptance_scenes'], ['replay'])
        self.assertIn('moving-x', rule['no_worse_scenes'])
        self.assertNotIn('moving-xy', rule['no_worse_scenes'])
        self.assertIn('never pooled', rule['statement'])

    def test_sequence_alternates_and_covers_three_replay_pairs_per_mode(self):
        replay = [(rep, arm) for scene, rep, arm in bs.SEQUENCE if scene == 'replay']
        self.assertEqual(replay, [('p1', 'current'), ('p1', 'candidate'), ('p2', 'candidate'), ('p2', 'current'),
                                  ('p3', 'current'), ('p3', 'candidate')])
        self.assertEqual(sum(1 for s, _, _ in bs.SEQUENCE if s == 'moving-x'), 2)
        self.assertEqual(sum(1 for s, _, _ in bs.SEQUENCE if s == 'moving-xy'), 2)


class Decision(unittest.TestCase):
    def vv(self, exact):
        return {'exact_on_all_tested_engines': exact, 'engines_tested': ['chromium'], 'coverage': {}, 'cells': {}, 'failures': [] if exact else ['x']}

    def timings(self, result, verdicts):
        return {'result': result, 'modes': {m: {'verdict': v, 'median_reduction_fraction_replay': 0.1, 'worst_pair_worse_fraction_gameplay': 0.0,
                                                 'miss_penalty_moving_xy_fraction': 0.02} for m, v in verdicts.items()}}

    def test_accept_requires_exact_visuals_and_passing_timing_in_both_modes(self):
        d = bs.decide(self.vv(True), self.timings('PASS', {'bad': 'PASS', 'classic': 'PASS'}))
        self.assertEqual(d['verdict'], 'ACCEPT' if bs.runtime_has_candidate(bs.ROOT) or True else 'REJECT')
        self.assertEqual(d['verdict'], 'ACCEPT')
        d = bs.decide(self.vv(True), self.timings('FAIL', {'bad': 'PASS', 'classic': 'IMMATERIAL'}))
        self.assertEqual(d['verdict'], 'REJECT')
        self.assertTrue(any('classic' in r for r in d['reasons']))
        d = bs.decide(self.vv(False), {'result': 'OMITTED', 'reason': 'visual validation failed'})
        self.assertEqual(d['verdict'], 'REJECT')
        self.assertTrue(any('timing omitted' in r for r in d['reasons']))

    def test_integration_status_is_consistent_with_runtime(self):
        status = bs.integration_status('REJECT')
        self.assertEqual(status['consistent_with_verdict'], not bs.runtime_has_candidate(bs.ROOT))
        status = bs.integration_status('ACCEPT')
        self.assertEqual(status['consistent_with_verdict'], status['tested_bodies_equal_runtime_bodies'])


class VisualPlan(unittest.TestCase):
    def test_plan_covers_modes_seeds_contexts_and_arms(self):
        plan = bs.visual_plan(['chromium'])
        cells = {(p['context'], p['mode'], p['seed'], p['arm']) for p in plan}
        for mode in bs.MODES:
            for seed in (1, 4, 49):
                for arm in ('current', 'candidate'):
                    self.assertIn(('dpr1', mode, seed, arm), cells)
            self.assertIn(('dpr2', mode, 4, 'current'), cells)
        self.assertEqual(len(plan), 2 * 3 * 2 + 2 * 1 * 2)
        self.assertTrue(all(p['engine'] == 'chromium' for p in plan))

    def test_state_digest_ignores_candidate_only_fields(self):
        state = {k: 1 for k in bs.STATE_KEYS}
        self.assertEqual(bs.state_digest(dict(state, farStack='x', builds=3)), state)

    def test_pixels_equal_prefers_decoded_pixels_over_png_bytes(self):
        a = {'final_sha256': 'png-a', 'final_pixels_sha256': 'px'}
        b = {'final_sha256': 'png-b', 'final_pixels_sha256': 'px'}
        self.assertTrue(bs.pixels_equal(a, b, 'final'))
        self.assertFalse(bs.pixels_equal(dict(a, final_pixels_sha256=None), dict(b, final_pixels_sha256=None), 'final'))
        self.assertFalse(bs.pixels_equal(a, dict(b, final_pixels_sha256='py'), 'final'))

    def test_transform_dependency_and_key_transitions(self):
        samples = [[1, 0, 0, 1, 'k', 0.5, 0.5, True], [2, 0, 0, 2, 'k', 0.50000005, 0.5, False], [3, 0, 0, 3, 'k2', 0.5000001, 0.5, False]]
        tr = bs.transform_dependency(samples)
        self.assertAlmostEqual(tr['cacheable_fraction'], 1 / 3)
        self.assertGreater(tr['relative_drift_per_frame'], 0)
        self.assertEqual(bs.key_transitions(['k', 'k', 'k2', 'k2', 'k']), 3)
        self.assertEqual(bs.key_transitions([]), 0)

    def test_camera_and_mote_dependency(self):
        samples = [[1, 0, 0, 11, 'k'], [2, -5, 0, 12, 'k'], [3, -10, 0, 13, 'k'], [4, -10, 0, 14, 'k']]
        cam = bs.camera_dependency(samples)
        self.assertAlmostEqual(cam['x_changed_fraction'], 2 / 3)
        self.assertEqual(cam['y_changed_fraction'], 0.0)
        self.assertEqual(cam['far_stack_hit_fraction'], 1.0)
        self.assertAlmostEqual(cam['whole_composite_hit_fraction'], 1 / 3)
        self.assertEqual(bs.mote_dependency(samples)['changed_fraction'], 1.0)
        self.assertEqual(bs.camera_dependency([[1, None, None, None, None]])['pairs'], 0)

    def test_visual_contexts_name_the_required_scenarios(self):
        c = bs.VISUAL_CONTEXTS['dpr1']
        names = [n for n, _ in c['checkpoints']]
        self.assertEqual(names, ['start', 'early', 'mid', 'shake', 'late'])
        self.assertIn([640, 540], c['resizes'], 'letterbox bars')
        self.assertIn([1366, 768], c['resizes'], 'odd backing')
        self.assertEqual(bs.VISUAL_CONTEXTS['dpr2']['dpr'], 2)
        self.assertEqual(bs.VISUAL_ENGINES['chromium']['contexts'], ('dpr1', 'dpr2'))


class Hypothesis(unittest.TestCase):
    def test_hypothesis_is_pre_registered_with_provenance(self):
        h = bs.hypothesis({'current_commit': 'abc', 'current_tar_sha256': 'def'})
        self.assertEqual(h['candidate']['sha256'], bs.candidate_sha())
        self.assertEqual(h['control']['current_commit'], 'abc')
        self.assertIn('far shift.y', h['invalidation_key'])
        self.assertEqual(len(h['rejected_designs_isolated']), 3)
        self.assertIn('60 FPS', h['not_claimed'])
        json.dumps(h)


if __name__ == '__main__':
    unittest.main()
