"""Unit tests for tools/y8_background_rows.py and the TASK-281 candidate (no browser; the content-row
runs and device-band construction are brute-force checked under Playwright's bundled node)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_background_rows as br  # noqa: E402
import y8_feature_cost as fc  # noqa: E402


def raw(case, mode, scene, rep, arm, mean_ms, started, frames=300, window_ms=20000):
    """A synthetic COMPLETE timing raw with a constant active frame interval."""
    t, fr = 0.0, []
    for i in range(frames):
        fr.append({'t': t, 'dt': None if i == 0 else mean_ms, 'canvas': [1280, 720], 'state': {}})
        t += mean_ms
    settings = {'mode': mode, 'profile': 'desktop', 'viewport': [1280, 720], 'dpr': 1, 'cpu_throttle': 1, 'seed': 4,
                'warmup_ms': 0, 'window_ms': window_ms, 'windows': 1, 'replay_sha256': 'r', 'diagnostic': False,
                'scene': scene, 'rep': rep, 'arm': arm, 'instrumentation': 'no readback'}
    r = {'case': case, 'settings': settings, 'frames': fr, 'excluded': [], 'deaths': [], 'dispatched': [],
         'dimensions': {'canvas': [1280, 720]}, 'started_utc': started, 'result': 'COMPLETE', 'density': None}
    r['summary'] = fc.summarize(r)
    return r


def node_binary():
    try:
        import playwright
    except ImportError:
        return None
    node = Path(playwright.__file__).resolve().parent / 'driver' / 'node'
    return str(node) if node.exists() else None


# The candidate body references BackgroundRenderer.prototype: a stub class is enough to evaluate it.
NODE_SELFTEST = r'''
const fs = require('fs');
globalThis.window = globalThis;
globalThis.BackgroundRenderer = class {};
(0, eval)(fs.readFileSync(process.argv[2], 'utf8'));
const C = window.__backgroundRowsCandidate;
let seed = 11; const rnd = () => { seed = (seed * 1103515245 + 12345) >>> 0; return seed / 4294967296 };
let fails = 0;
// 1. contentRowRuns: every row with any alpha > 0 is inside exactly one run; runs are sorted, disjoint, non-empty
for (let trial = 0; trial < 200; trial++) {
  const w = 1 + Math.floor(rnd() * 12), h = 1 + Math.floor(rnd() * 40);
  const data = new Uint8ClampedArray(w * h * 4);
  const content = new Uint8Array(h);
  for (let y = 0; y < h; y++) if (rnd() < 0.5) { const x = Math.floor(rnd() * w); data[(y * w + x) * 4 + 3] = 1 + Math.floor(rnd() * 255); content[y] = 1;
    for (let k = 0; k < w; k++) { data[(y * w + k) * 4] = 200; data[(y * w + k) * 4 + 1] = 100; data[(y * w + k) * 4 + 2] = 50 } }
  else for (let k = 0; k < w; k++) { data[(y * w + k) * 4] = 255; data[(y * w + k) * 4 + 1] = 255; data[(y * w + k) * 4 + 2] = 255 }  // rgb without alpha: transparent
  const runs = C.contentRowRuns(data, w, h);
  const covered = new Uint8Array(h);
  for (const [a, b] of runs) { if (!(a < b) || a < 0 || b > h) { fails++; console.log('FAIL run bounds', a, b, h) } for (let y = a; y < b; y++) { if (covered[y]) { fails++; console.log('FAIL overlap') } covered[y] = 1 } }
  for (let i = 1; i < runs.length; i++) if (runs[i][0] <= runs[i - 1][1]) { fails++; console.log('FAIL unsorted/adjacent runs', runs) }
  for (let y = 0; y < h; y++) if (covered[y] !== content[y]) { fails++; console.log('FAIL row', y, covered[y], content[y]) }
}
// 2. deviceBands: integers, sorted, disjoint; every content texel row maps strictly inside a band with >= 2 texel + 2 px margin
for (let trial = 0; trial < 300; trial++) {
  const rows = 10 + Math.floor(rnd() * 1000);
  const runs = []; let y = 0;
  while (y < rows) { const gap = Math.floor(rnd() * 80), len = 1 + Math.floor(rnd() * 120); if (y + gap >= rows) break; runs.push([y + gap, Math.min(rows, y + gap + len)]); y = y + gap + len + 1 }
  if (!runs.length) continue;
  const texel = [0.25, 0.5, 1, 1.3333333, 2, 2.75][Math.floor(rnd() * 6)], top = (rnd() - 0.5) * 50;
  const pad = C.bandPad(texel), bands = C.deviceBands(runs, top, texel, pad);
  if (pad < Math.ceil(2 * Math.max(texel, 1)) + 2) { fails++; console.log('FAIL pad', texel, pad) }
  for (const b of bands) if (!Number.isInteger(b[0]) || !Number.isInteger(b[1]) || b[0] >= b[1]) { fails++; console.log('FAIL band', b) }
  for (let i = 1; i < bands.length; i++) if (bands[i][0] <= bands[i - 1][1]) { fails++; console.log('FAIL band order/overlap', bands[i - 1], bands[i]) }
  for (const [r0, r1] of runs) {
    const d0 = top + r0 * texel - 2 * Math.max(texel, 1) - 2, d1 = top + r1 * texel + 2 * Math.max(texel, 1) + 2;
    const inside = bands.some(b => b[0] <= d0 && d1 <= b[1]);
    if (!inside) { fails++; console.log('FAIL run not inside a padded band', [r0, r1], texel, top, bands) }
  }
}
console.log(JSON.stringify({task: C.task, fails}));
process.exit(fails ? 1 : 0);
'''


class CandidateFile(unittest.TestCase):
    def test_candidate_body_is_marked_and_bounded(self):
        text = br.candidate_text()
        body = br.candidate_body(text)
        self.assertIsNotNone(body)
        self.assertTrue(body.startswith(br.BODY_BEGIN) and body.endswith(br.BODY_END))
        for marker in br.CANDIDATE_MARKERS:
            self.assertIn(marker, body)
        # the two touched methods and nothing else of the renderer: paint()/paintMenu() (clear, gradients, RNG draws) stay shipped
        for method in ('P.drawLayerTile = function', 'P.getLayerContentRows = function'):
            self.assertIn(method, body)
        for untouched in ('P.paint = ', 'P.paintMenu = ', 'drawBaseGradient = ', 'drawHaze = ', 'drawVignette = ', 'getLayerTile = ',
                          'getLayerShift = ', 'drawWindowBars = ', 'clearAll', 'preserveGameplayRandomSequence', 'Math.random'):
            self.assertNotIn(untouched, body)
        # one readback per tile build, cached on the layer; no per-frame readback
        self.assertEqual(body.count('getImageData'), 1)
        self.assertIn('layer.contentRows && layer.contentRows.canvas === canvas', body)
        # the clip is a Path2D (current default path untouched) inside one save/restore pair; no pixel-alignment guard
        self.assertIn('new Path2D()', body)
        self.assertNotIn('beginPath', body)
        self.assertNotIn('PIXEL_ALIGNED', body)
        self.assertEqual(body.count('this.ctx.save()'), 1)
        self.assertEqual(body.count('this.ctx.restore()'), 1)
        # the shipped copy submission and edge fills are kept verbatim
        shipped = (Path(br.ROOT) / 'render/effects.js').read_text()
        for call in ('this.ctx.drawImage(layer.canvas, left, shift.y, next - left, height)',
                     'this.ctx.fillRect(bounds.x, bounds.y, bounds.width, shift.y - bounds.y)',
                     'this.ctx.fillRect(bounds.x, shift.y + height, bounds.width, bounds.y + bounds.height - shift.y - height)',
                     'const toDevice = x => Math.round(transform.a * x + transform.e)'):
            self.assertIn(call, shipped)
            self.assertIn(call, body)
        self.assertEqual(br.body_sha(text), fc.sha_bytes(body.encode()))

    def test_shipping_runtime_state_matches_a_non_accept_unless_integrated(self):
        in_runtime = br.runtime_has_candidate(br.ROOT)
        status = br.integration_status('ACCEPT' if in_runtime else 'REJECT')
        self.assertTrue(status['consistent_with_verdict'])
        if in_runtime:
            self.assertEqual(status['runtime_body_sha256'], br.body_sha())

    def test_content_runs_and_device_bands_under_node(self):
        node = node_binary()
        if not node:
            self.skipTest('playwright node unavailable')
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / 'selftest.js'
            script.write_text(NODE_SELFTEST)
            r = subprocess.run([node, str(script), str(br.CANDIDATE)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        summary = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(summary, {'task': 'TASK-281', 'fails': 0})


class TimingRule(unittest.TestCase):
    def test_pair_record_reduction_and_order(self):
        c = raw('c', 'bad', 'replay', 'p1', 'current', 100.0, '2026-10-11T00:00:00')
        k = raw('k', 'bad', 'replay', 'p1', 'candidate', 90.0, '2026-10-11T00:01:00')
        p = br.pair_record(c, k)
        self.assertAlmostEqual(p['reduction_fraction'], 0.1)
        self.assertEqual(p['worse_by_fraction'], 0.0)
        self.assertEqual(p['order'], 'control first')
        q = br.pair_record(raw('c2', 'bad', 'replay', 'p2', 'current', 100.0, '2026-10-11T00:03:00'),
                           raw('k2', 'bad', 'replay', 'p2', 'candidate', 103.0, '2026-10-11T00:02:00'))
        self.assertAlmostEqual(q['worse_by_fraction'], 0.03)
        self.assertEqual(q['order'], 'candidate first')

    def test_rule_constants_and_statement(self):
        rule = br.timing_rule()
        self.assertEqual(rule['min_median_reduction'], 0.05)
        self.assertEqual(rule['max_worse'], 0.05)
        self.assertIn('never pooled', rule['statement'])
        self.assertIn('BOTH modes', rule['statement'])

    def test_sequence_alternates_and_covers_three_replay_pairs_per_mode(self):
        replay = [s for s in br.SEQUENCE if s[0] == 'replay']
        self.assertEqual(len(replay), 6)
        firsts = [replay[i][2] for i in range(0, 6, 2)]
        self.assertEqual(firsts, ['current', 'candidate', 'current'])
        for i in range(0, 6, 2):
            self.assertEqual(replay[i][1], replay[i + 1][1])
            self.assertNotEqual(replay[i][2], replay[i + 1][2])
        self.assertEqual([s for s in br.SEQUENCE if s[0] == 'moving-x'], [('moving-x', 'p1', 'candidate'), ('moving-x', 'p1', 'current')])

    def test_timing_verdicts_from_synthetic_raws(self):
        def build(means_bad, means_classic, moving=(100.0, 100.0)):
            d = tempfile.mkdtemp()
            rawdir = Path(d) / 'raw'
            rawdir.mkdir()
            for mode, means in (('bad', means_bad), ('classic', means_classic)):
                for i, rep in enumerate(br.REPS):
                    c, k = means[i]
                    fc.dump(rawdir / f'{mode}-replay-{rep}-current.json', raw(f'{mode}-replay-{rep}-current', mode, 'replay', rep, 'current', c, f'2026-10-11T00:{i:02d}:00'))
                    fc.dump(rawdir / f'{mode}-replay-{rep}-candidate.json', raw(f'{mode}-replay-{rep}-candidate', mode, 'replay', rep, 'candidate', k, f'2026-10-11T00:{i:02d}:30'))
                fc.dump(rawdir / f'{mode}-moving-x-p1-current.json', raw(f'{mode}-mx-current', mode, 'moving-x', 'p1', 'current', moving[0], '2026-10-11T01:00:00'))
                fc.dump(rawdir / f'{mode}-moving-x-p1-candidate.json', raw(f'{mode}-mx-candidate', mode, 'moving-x', 'p1', 'candidate', moving[1], '2026-10-11T01:00:30'))
            return br.build_timings(d)
        t = build([(100, 94), (100, 93), (100, 90)], [(100, 90), (100, 88), (100, 85)])
        self.assertEqual(t['result'], 'PASS')
        t = build([(100, 97), (100, 96), (100, 98)], [(100, 90), (100, 88), (100, 85)])
        self.assertEqual(t['result'], 'FAIL')
        self.assertEqual(t['modes']['bad']['verdict'], 'IMMATERIAL')
        self.assertEqual(t['modes']['classic']['verdict'], 'PASS')
        t = build([(100, 94), (100, 93), (100, 90)], [(100, 90), (100, 88), (100, 85)], moving=(100.0, 107.0))
        self.assertEqual(t['result'], 'FAIL')
        self.assertEqual(t['modes']['bad']['verdict'], 'INCONSISTENT')


class Decision(unittest.TestCase):
    def test_accept_requires_exact_visuals_and_passing_timing_in_both_modes(self):
        vv_ok = {'exact_on_all_tested_engines': True, 'engines_tested': ['chromium'], 'coverage': {}, 'cells': {}, 'failures': []}
        timing_ok = {'result': 'PASS', 'modes': {m: {'verdict': 'PASS', 'median_reduction_fraction_replay': 0.08, 'worst_pair_worse_fraction_gameplay': 0.0} for m in br.MODES}}
        accept = br.decide(vv_ok, timing_ok)
        self.assertEqual(accept['verdict'], 'ACCEPT')
        timing_bad = {'result': 'FAIL', 'modes': {'bad': {'verdict': 'IMMATERIAL', 'median_reduction_fraction_replay': 0.03, 'worst_pair_worse_fraction_gameplay': 0.0},
                                                  'classic': {'verdict': 'PASS', 'median_reduction_fraction_replay': 0.08, 'worst_pair_worse_fraction_gameplay': 0.0}}}
        reject = br.decide(vv_ok, timing_bad)
        self.assertEqual(reject['verdict'], 'REJECT')
        self.assertTrue(any('IMMATERIAL' in r for r in reject['reasons']))
        vv_bad = dict(vv_ok, exact_on_all_tested_engines=False, failures=['x/y: final_equal=False'])
        omitted = {'result': 'OMITTED', 'reason': 'visual validation failed'}
        self.assertEqual(br.decide(vv_bad, omitted)['verdict'], 'REJECT')
        self.assertTrue(accept['ticket_completion_is_not_60fps_acceptance'])

    def test_integration_status_is_consistent_with_runtime(self):
        in_runtime = br.runtime_has_candidate(br.ROOT)
        self.assertEqual(br.integration_status('REJECT')['consistent_with_verdict'], not in_runtime)
        self.assertEqual(br.integration_status('ACCEPT')['consistent_with_verdict'], in_runtime and br.runtime_body_sha(br.ROOT) == br.body_sha())


class VisualPlan(unittest.TestCase):
    def test_plan_covers_modes_seeds_contexts_and_arms(self):
        plan = br.visual_plan()
        chromium = [p for p in plan if p['engine'] == 'chromium']
        self.assertEqual({(p['context'], p['seed']) for p in chromium if p['context'] == 'dpr1'}, {('dpr1', s) for s in (1, 4, 49)})
        self.assertEqual({p['seed'] for p in chromium if p['context'] == 'dpr2'}, {4})
        self.assertEqual({p['mode'] for p in plan}, {'bad', 'classic'})
        self.assertEqual({p['arm'] for p in plan}, {'current', 'candidate'})
        self.assertEqual(len(chromium), 2 * 2 * (3 + 1))
        self.assertEqual(len([p for p in plan if p['engine'] == 'firefox']), 4)

    def test_state_digest_ignores_candidate_only_fields(self):
        a = {k: 1 for k in br.STATE_KEYS}
        b = dict(a, randomDrawsDuringReadback=5)
        self.assertEqual(br.state_digest(a), br.state_digest(b))
        self.assertIn('tileKeys', br.STATE_KEYS)
        self.assertIn('layerShift', br.STATE_KEYS)

    def test_pixels_and_bars_equality_prefer_decoded_pixels(self):
        a = {'final_sha256': 'x', 'final_pixels_sha256': 'p', 'bars_sha256': ['b1'], 'bars_pixels_sha256': ['q']}
        b = {'final_sha256': 'y', 'final_pixels_sha256': 'p', 'bars_sha256': ['b2'], 'bars_pixels_sha256': ['q']}
        self.assertTrue(br.pixels_equal(a, b, 'final'))
        self.assertTrue(br.bars_equal(a, b))
        c = {'final_sha256': 'x', 'final_pixels_sha256': None, 'bars_sha256': [], 'bars_pixels_sha256': []}
        d = {'final_sha256': 'x', 'final_pixels_sha256': None, 'bars_sha256': ['z'], 'bars_pixels_sha256': ['w']}
        self.assertTrue(br.pixels_equal(c, dict(c), 'final'))
        self.assertFalse(br.bars_equal(c, d))

    def test_rows_summary_and_content_rows(self):
        samples = [[1, None, None, 0, None, [1280, 720]],
                   [2, 0.0, 0.0, 0, {'far': 0.8, 'near': 0.6, 'farApplied': True, 'nearApplied': True}, [1280, 720]],
                   [3, -1.0, 0.0, 0, {'far': 0.8, 'near': 0.5, 'farApplied': True, 'nearApplied': True}, [1280, 720]],
                   [4, -2.0, 0.0, 0, {'far': 1.0, 'near': 1.0, 'farApplied': False, 'nearApplied': False}, [1280, 720]]]
        s = br.rows_summary(samples)
        self.assertEqual(s['frames'], 3)
        self.assertAlmostEqual(s['far']['mean_clip_fraction'], (0.8 + 0.8 + 1.0) / 3)
        self.assertAlmostEqual(s['near']['mean_clip_fraction'], (0.6 + 0.5 + 1.0) / 3)
        self.assertAlmostEqual(s['far']['clip_applied_fraction'], 2 / 3)
        self.assertAlmostEqual(s['near']['mean_clip_fraction_when_applied'], 0.55)
        self.assertAlmostEqual(s['tile_pass_equivalents_removed'], 2 - (0.8 + 0.8 + 1.0) / 3 - (0.6 + 0.5 + 1.0) / 3)
        empty = br.rows_summary([[2, 0.0, 0.0, 0, None, [1280, 720]]])
        self.assertIsNone(empty['far']['mean_clip_fraction'])
        self.assertIsNone(empty['tile_pass_equivalents_removed'])
        cps = [{'candidate': {'contentRows': {'far': {'runs': [[0, 100], [500, 720]], 'rows': 720, 'transparentRows': 400, 'contentRowCount': 320},
                                              'near': None}}}]
        cr = br.content_rows_summary(cps)
        self.assertEqual(list(cr), ['far@720'])
        self.assertAlmostEqual(cr['far@720']['transparent_fraction'], 400 / 720)
        self.assertEqual(cr['far@720']['run_count'], 2)
        self.assertEqual(br.camera_dependency(samples)['x_changed_fraction'], 1.0)

    def test_visual_contexts_name_the_required_scenarios(self):
        c = br.VISUAL_CONTEXTS['dpr1']
        self.assertIn([640, 540], c['resizes'])    # letterbox bars
        self.assertIn([1366, 768], c['resizes'])   # odd backing
        self.assertIn([1000, 700], c['resizes'])
        self.assertTrue(any(n == 'shake' for n, _ in c['checkpoints']))
        self.assertEqual(br.VISUAL_CONTEXTS['dpr2']['dpr'], 2)
        self.assertEqual(br.VISUAL_SEEDS, (1, 4, 49))


class Hypothesis(unittest.TestCase):
    def test_hypothesis_is_pre_registered_with_provenance(self):
        h = br.hypothesis({'current_commit': 'abc', 'current_tar_sha256': 'def'})
        self.assertEqual(h['control']['current_commit'], 'abc')
        self.assertEqual(h['candidate']['sha256'], br.candidate_sha())
        self.assertEqual(h['candidate']['body_sha256'], br.body_sha())
        self.assertIn('threshold', h['expected_work_reduction'])
        self.assertIn('expected_ms_dpr1', h['expected_work_reduction'])
        self.assertTrue(all('Never installed' in d['reason'] for d in h['rejected_designs_isolated']))
        self.assertIn('cave_background_off_median_saving_ms', h['measured_target'])
        self.assertIn('TASK-279', h['measured_target']['excluded_mechanisms'])
        self.assertIn('TASK-280', h['measured_target']['excluded_mechanisms'])
        self.assertIn('60 FPS', h['not_claimed'])
        self.assertIn('TASK-279', h['why_it_differs_from_TASK_279_and_TASK_280'])


if __name__ == '__main__':
    unittest.main()
