"""Unit tests for the TASK-275 feature-history bisection module (no browser)."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_history as fh  # noqa: E402


def fake_runs(means, order=('original', 'a', 'b', 'current')):
    runs = {}
    for n in order:
        m = means.get(n)
        valid = m is not None
        reps = {str(i + 1): {'mean_ms': v, 'average_fps': 1000 / v} for i, v in enumerate(m)} if valid else {}
        runs[n] = {'tree': n, 'full': n * 10, 'label': n, 'role': 'control' if n in ('original', 'current') else 'revision',
                   'ranked_feature': None, 'repetitions': reps, 'valid': valid,
                   'dynamic_compatibility': {'result': 'VALID' if valid else 'UNTESTABLE: boot'},
                   'mean_ms_by_rep': list(m) if valid else [], 'mean_ms': sum(m) / 2 if valid else None,
                   'repeat_spread_ms': abs(m[0] - m[1]) if valid else None}
    return runs


def steps_from(runs, order):
    valid = [n for n in order if runs[n]['valid']]
    noise = max(runs[n]['repeat_spread_ms'] for n in valid)
    steps = []
    for a, b in zip(valid, valid[1:]):
        per = [runs[b]['repetitions'][k]['mean_ms'] - runs[a]['repetitions'][k]['mean_ms'] for k in ('1', '2')]
        steps.append({'from': a, 'to': b, 'interval': f'{a}..{b}', 'to_label': b, 'ranked_feature': None,
                      'delta_mean_ms_by_rep': per, 'delta_mean_ms': sum(per) / 2,
                      'regression_beyond_noise_every_rep': all(d > noise for d in per), 'commits_in_interval': 1})
    doc = {'protocol': {'mode': 'classic', 'profile': 'desktop'}, 'valid_trees': valid, 'runs': runs,
           'excluded_trees': [{'tree': n, 'reason': runs[n]['dynamic_compatibility']['result']} for n in order if not runs[n]['valid']]}
    return doc, steps, noise


class SelectionTests(unittest.TestCase):
    def test_at_most_six_revisions_all_ancestors_between_original_and_head(self):
        self.assertLessEqual(len(fh.REVISIONS), 6)
        original = fh.git('rev-parse', fh.fc.ORIGINAL_COMMIT)
        prev = original
        for spec in fh.REVISIONS:
            full = fh.git('rev-parse', spec['rev'] + '^{commit}')
            subprocess.check_call(['git', 'merge-base', '--is-ancestor', prev, full], cwd=fh.ROOT)
            subprocess.check_call(['git', 'merge-base', '--is-ancestor', full, 'HEAD'], cwd=fh.ROOT)
            prev = full
        self.assertEqual(len({s['rev'] for s in fh.REVISIONS}), len(fh.REVISIONS))

    def test_most_affected_mode_from_sealed_task271_controls(self):
        affected = fh.most_affected(fh.fc.load(fh.CONTROLS_271))
        self.assertEqual(affected['mode'], 'classic')
        self.assertGreater(affected['regression_p50_ms_by_mode']['classic'], affected['regression_p50_ms_by_mode']['bad'])
        self.assertIn(affected['mode'], fh.REPLAY_BY_MODE)

    def test_static_compat_detects_missing_api_and_external_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'index.html').write_text('<script src="https://cdn.example/x.js"></script><script src="game.js"></script>')
            (root / 'game.js').write_text('function startGame(){} function gameLoop(){} const menu = {gamePaused: false}\nAmbientGlowRenderer')
            c = fh.static_compat(root)
            self.assertEqual(c['result'], 'STATIC_FAIL: missing function reStart')
            self.assertEqual(c['external_scripts'], ['https://cdn.example/x.js'])
            self.assertEqual(c['feature_identifiers']['ambient-glow-chain'], 1)
            (root / 'game.js').write_text('function startGame(){} function gameLoop(){} function reStart(){} gamePaused')
            self.assertEqual(fh.static_compat(root)['result'], 'STATIC_OK')
            self.assertEqual(fh.static_compat(root / 'missing')['result'], 'STATIC_FAIL: no index.html')


class DecisionTests(unittest.TestCase):
    def test_failed_tree_excluded_from_steps_and_rankings(self):
        order = ('original', 'a', 'b', 'current')
        runs = fake_runs({'original': (50, 52), 'a': None, 'b': (90, 93), 'current': (100, 101)}, order)
        doc, steps, noise = steps_from(runs, order)
        self.assertEqual(doc['valid_trees'], ['original', 'b', 'current'])
        self.assertEqual([s['interval'] for s in steps], ['original..b', 'b..current'])
        self.assertEqual(doc['excluded_trees'], [{'tree': 'a', 'reason': 'UNTESTABLE: boot'}])
        decision = fh.decide(doc, steps, noise)
        self.assertEqual(decision['result'], 'NARROWED')
        self.assertEqual(decision['largest_regression_interval'], 'original..b')
        self.assertEqual({s['to'] for s in decision['steps_ranked_by_regression']}, {'b', 'current'})

    def test_unresolved_when_step_within_noise_or_not_separated(self):
        order = ('original', 'a', 'current')
        runs = fake_runs({'original': (50, 60), 'a': (55, 63), 'current': (58, 70)}, order)
        doc, steps, noise = steps_from(runs, order)
        self.assertEqual(noise, 12)
        self.assertEqual(fh.decide(doc, steps, noise)['result'], 'UNRESOLVED')
        runs = fake_runs({'original': (50, 51), 'a': (80, 81), 'current': (103, 106)}, order)
        doc, steps, noise = steps_from(runs, order)
        d = fh.decide(doc, steps, noise)
        self.assertEqual(d['result'], 'NARROWED')
        self.assertEqual(d['introduced_at'], 'a')
        self.assertAlmostEqual(d['total_original_to_current_ms'], 54)

    def test_no_steps_is_unresolved(self):
        self.assertEqual(fh.decide({'valid_trees': [], 'runs': {}, 'protocol': {'mode': 'classic', 'profile': 'desktop'}}, [], None)['result'], 'UNRESOLVED')


if __name__ == '__main__':
    unittest.main()
