"""Synthetic bookkeeping tests; these are never browser performance evidence."""
import unittest

from playgama_draw_profile import summarize_profile


def frame(t, before=False, after=False, draw_ms=10):
    return {'t': t, 'before': {'inactive': before}, 'after': {'inactive': after},
            'draws': [{'ms': draw_ms, 'costs': {'layer': {'ms': draw_ms, 'calls': 1}}}]}


class ProfileTests(unittest.TestCase):
    def test_previous_callback_cost_and_death_ending_interval(self):
        raw = {'arm': 'B', 'frames': [frame(0), frame(5000, draw_ms=12),
                frame(5020, after=True, draw_ms=99),
                frame(9000, before=True, draw_ms=88), frame(9030)]}
        result = summarize_profile(raw)
        # The death-ending interval stays; the inactive gap is excluded.
        self.assertEqual(result['metrics']['intervals_ms'], [20, 30])
        self.assertEqual(result['draw_mean_ms'], 50)
        self.assertEqual(result['untimed_mean_ms'], -25)
        self.assertEqual(result['costs']['layer']['calls'], 2)
        # Negative residuals are retained, never clamped to fabricate a budget.

    def test_whole_warmup_boundary_interval_is_excluded(self):
        raw = {'arm': 'A', 'frames': [frame(0), frame(4990), frame(5010), frame(5050)]}
        result = summarize_profile(raw)
        self.assertEqual(result['metrics']['warmup_ms'], 5010)
        self.assertEqual(result['metrics']['intervals_ms'], [40])
        self.assertEqual(result['fps'], 25)
        self.assertNotIn('draw_mean_ms', result)

    def test_missing_draw_is_not_zero_cost(self):
        raw = {'arm': 'B', 'frames': [frame(0), frame(5000), frame(5020)]}
        raw['frames'][1]['draws'] = []
        with self.assertRaisesRegex(AssertionError, 'missing timed draw'):
            summarize_profile(raw)


if __name__ == '__main__':
    unittest.main()
