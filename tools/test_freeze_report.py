"""tools/freeze_report.py on the hand-made exports in tools/fixtures/freeze-report/ (TASK-777).

One fixture per label (two for tab-hidden, main-thread-script and
render-or-present: each has two ways in), a schema-1 export without the
schema 2/3 fields, and a schema-2 export with stray bytes before the first
'{' and null fields. No browser.
"""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_report  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'freeze-report'

LABELLED = {
    'tab-hidden': 'tab-hidden',
    'tab-hidden-sample': 'tab-hidden',
    'first-draw': 'first-draw',
    'canvas-churn': 'canvas-churn',
    'main-thread-script': 'main-thread-script',
    'main-thread-silence': 'main-thread-script',
    'gc-suspect': 'gc-suspect',
    'render-or-present': 'render-or-present',
    'render-loaf': 'render-or-present',
    'game-work': 'game-work',
    'unknown': 'unknown',
}


def run(name, *extra):
    out = io.StringIO()
    with redirect_stdout(out):
        code = freeze_report.main([str(FIXTURES / f'{name}.json'), *extra])
    return code, out.getvalue()


def rows(name):
    report, _ = freeze_report.load(FIXTURES / f'{name}.json')
    return freeze_report.analyse(report)


class FreezeReportTest(unittest.TestCase):
    def test_every_label(self):
        for name, expected in LABELLED.items():
            with self.subTest(fixture=name):
                code, text = run(name)
                self.assertEqual(code, 0)
                _, got = rows(name)
                self.assertEqual([r['label'] for r in got], [expected])
                self.assertTrue(text.rstrip().endswith(expected), text)

    def test_all_labels_covered(self):
        self.assertEqual(set(LABELLED.values()), set(freeze_report.LABELS))

    def test_hidden_excluded_from_rate(self):
        summary, _ = rows('tab-hidden')
        self.assertEqual(summary['freezesTotal'], 1)
        self.assertEqual(summary['freezes'], 0)
        self.assertAlmostEqual(summary['hiddenMs'], 3400)
        self.assertAlmostEqual(summary['visibleMs'], 60000 - 3400)
        self.assertEqual(summary['freezesPerMinute'], 0)
        summary, _ = rows('unknown')
        self.assertEqual(summary['hiddenMs'], 0)
        self.assertAlmostEqual(summary['freezesPerMinute'], 1.0)

    def test_schema_1(self):
        code, text = run('schema-1')
        self.assertEqual(code, 0)
        summary, got = rows('schema-1')
        self.assertEqual(summary['buildId'], None)
        self.assertIn('build: unknown', text)
        self.assertAlmostEqual(summary['freezesPerMinute'], 1.0)
        # no firstDraws: any canvas created counts as churn; else nothing to go on
        self.assertEqual([r['label'] for r in got], ['unknown', 'canvas-churn'])
        for r in got:
            for key in ('mainThreadSilenceMs', 'heapDropMB', 'liveCanvasMB', 'topLoafScript'):
                self.assertIsNone(r[key])
        freeze_lines = text.splitlines()[-2:]
        for line in freeze_lines:
            self.assertGreaterEqual(line.split().count('unknown'), 4, line)

    def test_stray_prefix(self):
        code, text = run('stray-prefix')
        self.assertEqual(code, 0)
        self.assertIn('skipped 11 bytes before the first {', text)
        _, got = rows('stray-prefix')
        self.assertEqual([r['label'] for r in got], ['unknown'])
        self.assertEqual(got[0]['gapMs'], 767)

    def test_top_script_and_build(self):
        code, text = run('main-thread-script')
        self.assertEqual(code, 0)
        self.assertIn('physics.js:step 160ms', text)
        self.assertIn('build: ' + 'ab' * 32, text)

    def test_json_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.json'
            code, _ = run('gc-suspect', '--json', str(out))
            self.assertEqual(code, 0)
            data = json.loads(out.read_text())
        self.assertEqual(data['summary']['labels'], {'gc-suspect': 1})
        self.assertEqual(data['rows'][0]['heapDropMB'], 20)
        self.assertEqual(data['rows'][0]['label'], 'gc-suspect')

    def test_not_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'empty.json'
            path.write_text('no object here\n')
            err = io.StringIO()
            sys_stderr, sys.stderr = sys.stderr, err
            try:
                code = freeze_report.main([str(path)])
            finally:
                sys.stderr = sys_stderr
        self.assertEqual(code, 1)
        self.assertIn('no JSON object', err.getvalue())

    def test_empty_export(self):
        summary, got = freeze_report.analyse({})
        self.assertEqual(got, [])
        self.assertIsNone(summary['freezesPerMinute'])
        self.assertIn('build: unknown', freeze_report.render('x', 0, summary, got))


if __name__ == '__main__':
    unittest.main()
