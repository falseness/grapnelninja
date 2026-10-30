"""tools/freeze_report.py on the hand-made exports in tools/fixtures/freeze-report/ (TASK-777, TASK-786).

One fixture per label (two for tab-hidden, after-tab-return, main-thread-script
and render-or-present: each has two ways in), a schema-1 export without the
schema 2/3 fields, and a schema-2 export with stray bytes before the first
'{' and null fields. after-tab-return.json is schema 4 (the recorder's
sinceVisibleMs and a canvasSnapshot with 11 creators); after-tab-return-schema3
has only visibility events. No browser.
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
    'after-tab-return': 'after-tab-return',
    'after-tab-return-schema3': 'after-tab-return',
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


def freeze_lines(text):
    """The freeze table's rows (between its header and the creators block)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.lstrip().startswith('t s')) + 1
    end = lines.index('', start)
    return lines[start:end]


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
                self.assertTrue(freeze_lines(text)[-1].endswith(expected), text)

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
        lines = freeze_lines(text)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertGreaterEqual(line.split().count('unknown'), 4, line)

    def test_stray_prefix(self):
        code, text = run('stray-prefix')
        self.assertEqual(code, 0)
        self.assertIn('warning: skipped 11 bytes before the first {', text)
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

    def test_prefix_warning(self):
        # the user's TASK-786 paste accident: 'tifact' before the first '{'
        report = json.loads((FIXTURES / 'after-tab-return-schema3.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'prefixed.json'
            path.write_text('tifact' + json.dumps(report))
            out = io.StringIO()
            with redirect_stdout(out):
                code = freeze_report.main([str(path)])
            clean = Path(tmp) / 'clean.json'
            clean.write_text(json.dumps(report))
            clean_out = io.StringIO()
            with redirect_stdout(clean_out):
                freeze_report.main([str(clean)])
        self.assertEqual(code, 0)
        warnings = [line for line in out.getvalue().splitlines() if line.startswith('warning: skipped')]
        self.assertEqual(warnings, ['warning: skipped 6 bytes before the first { (stray text, not part of the export)'])
        self.assertTrue(freeze_lines(out.getvalue())[-1].endswith('after-tab-return'))
        self.assertNotIn('warning', clean_out.getvalue())

    def test_after_tab_return_schema_4(self):
        summary, got = rows('after-tab-return')
        self.assertEqual(summary['schemaVersion'], 4)
        self.assertEqual(got[0]['sinceVisibleMs'], 4000)
        self.assertEqual(got[0]['label'], 'after-tab-return')
        self.assertEqual(summary['labels'], {'after-tab-return': 1})
        # the recorder's own field wins over the visibility events (10000 - 6000 too here)
        report, _ = freeze_report.load(FIXTURES / 'after-tab-return.json')
        report['freezes'][0]['sinceVisibleMs'] = 10000
        self.assertEqual(freeze_report.analyse(report)[1][0]['label'], 'after-tab-return')
        report['freezes'][0]['sinceVisibleMs'] = 10000.1
        self.assertEqual(freeze_report.analyse(report)[1][0]['label'], 'render-or-present')
        # null: the tab never went hidden while recording
        report['freezes'][0]['sinceVisibleMs'] = None
        _, got = freeze_report.analyse(report)
        self.assertIsNone(got[0]['sinceVisibleMs'])
        self.assertEqual(got[0]['label'], 'render-or-present')

    def test_after_tab_return_schema_3(self):
        code, text = run('after-tab-return-schema3')
        self.assertEqual(code, 0)
        summary, got = rows('after-tab-return-schema3')
        self.assertEqual(summary['schemaVersion'], 3)
        self.assertNotIn('sinceVisibleMs', json.loads((FIXTURES / 'after-tab-return-schema3.json').read_text())['freezes'][0])
        # visible again at 5500, freeze at 15000
        self.assertAlmostEqual(got[0]['sinceVisibleMs'], 9500)
        self.assertEqual(got[0]['label'], 'after-tab-return')
        self.assertIn('9.50', text)
        report, _ = freeze_report.load(FIXTURES / 'after-tab-return-schema3.json')
        report['freezes'][0]['t'] = 15600
        self.assertEqual(freeze_report.analyse(report)[1][0]['label'], 'render-or-present')
        # hidden samples alone (no visibility events): hidden until 7000
        report['visibility'] = []
        report['samples'] = [{'t': 7000, 'gapMs': 3000, 'hidden': True}, {'t': 7017, 'gapMs': 17, 'hidden': False}]
        _, got = freeze_report.analyse(report)
        self.assertAlmostEqual(got[0]['sinceVisibleMs'], 8600)
        self.assertEqual(got[0]['label'], 'after-tab-return')
        # never hidden
        report['samples'] = []
        _, got = freeze_report.analyse(report)
        self.assertIsNone(got[0]['sinceVisibleMs'])
        self.assertEqual(got[0]['label'], 'render-or-present')

    def test_canvas_by_creator(self):
        code, text = run('after-tab-return')
        self.assertEqual(code, 0)
        self.assertIn('live canvases by creator (top 8 by MB, from canvasSnapshot):', text)
        self.assertIn('13.5 MB    10  render/c9.js:90', text)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.json'
            code, _ = run('after-tab-return', '--json', str(out))
            self.assertEqual(code, 0)
            data = json.loads(out.read_text())
        creators = data['summary']['canvasByCreator']
        self.assertEqual(len(creators), 8)
        self.assertEqual([c['creator'] for c in creators],
                         ['render/c9.js:90', 'render/c8.js:80', 'render/c7.js:70', 'render/c6.js:60',
                          'render/c5.js:50', 'render/c4.js:40', 'render/c3.js:30', 'unknown'])
        self.assertEqual(creators[0], {'creator': 'render/c9.js:90', 'count': 10, 'mb': 13.5})
        self.assertEqual(data['summary']['canvasByCreatorFrom'], 'canvasSnapshot')
        # no snapshot: the last freeze's context
        report, _ = freeze_report.load(FIXTURES / 'after-tab-return.json')
        del report['canvasSnapshot']
        summary, _ = freeze_report.analyse(report)
        self.assertEqual(summary['canvasByCreator'], [{'creator': 'render/c1.js:10', 'count': 1, 'mb': 13.3}])
        self.assertEqual(summary['canvasByCreatorFrom'], 'last freeze')
        # schema 3: neither
        summary, got = rows('render-or-present')
        self.assertIsNone(summary['canvasByCreator'])
        self.assertIn('live canvases by creator: unknown', freeze_report.render('x', 0, summary, got))

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
