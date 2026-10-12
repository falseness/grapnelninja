"""Unit tests for tools/y8_glow_region.py and the TASK-280 candidate (no browser; the region
union and dilation parity run under Playwright's bundled node)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_glow_region as gr  # noqa: E402
import y8_feature_cost as fc  # noqa: E402
from browser_test_support import node_binary  # noqa: E402


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


NODE_SELFTEST = r'''
const fs = require('fs');
globalThis.window = globalThis;
(0, eval)(fs.readFileSync(process.argv[2], 'utf8'));
const C = window.__geometryRegionCandidate;
let seed = 7; const rnd = () => { seed = (seed * 1103515245 + 12345) >>> 0; return seed / 4294967296 };
let fails = 0;
for (let trial = 0; trial < 150; trial++) {
  const n = 1 + Math.floor(rnd() * 60), rects = [];
  for (let k = 0; k < n; k++) { const x0 = Math.floor(rnd() * 100), y0 = Math.floor(rnd() * 60);
    rects.push([x0, y0, x0 + 1 + Math.floor(rnd() * 30), y0 + 1 + Math.floor(rnd() * 20)]) }
  const grid = new Uint8Array(140 * 90);
  for (const r of rects) for (let y = r[1]; y < r[3]; y++) for (let x = r[0]; x < r[2]; x++) grid[y * 140 + x] = 1;
  const brute = grid.reduce((a, b) => a + b, 0);
  const out = C.regionRects(rects), area = C.area(out);
  const g2 = new Uint8Array(140 * 90); let overlap = 0, outside = 0;
  for (const r of out) for (let y = r[1]; y < r[3]; y++) for (let x = r[0]; x < r[2]; x++) { if (g2[y * 140 + x]) overlap++; g2[y * 140 + x] = 1; if (!grid[y * 140 + x]) outside++ }
  const covered = g2.reduce((a, b) => a + b, 0);
  if (area !== brute || overlap || outside || covered !== brute) { fails++; console.log('FAIL union', {n, brute, area, overlap, outside, covered}) }
}
const renderer = {canvas: {width: 1280, height: 720}, levels: [{canvas: {width: 320, height: 180}}, {canvas: {width: 160, height: 90}}, {canvas: {width: 80, height: 45}}, {canvas: {width: 40, height: 22}}]};
for (let trial = 0; trial < 150; trial++) {
  const rects = []; for (let k = 0; k < 1 + Math.floor(rnd() * 40); k++) { const x0 = rnd() * 320 - 10, y0 = rnd() * 180 - 10; rects.push([x0, y0, x0 + 1 + rnd() * 8, y0 + 1 + rnd() * 8]) }
  const box = [Math.min(...rects.map(r => r[0])), Math.min(...rects.map(r => r[1])), Math.max(...rects.map(r => r[2])), Math.max(...rects.map(r => r[3]))];
  for (let i = 0; i < 4; i++) {
    const db = C.dilate(box.slice(), renderer, i), ds = rects.map(r => C.dilate(r.slice(), renderer, i));
    const bb = [Math.min(...ds.map(r => r[0])), Math.min(...ds.map(r => r[1])), Math.max(...ds.map(r => r[2])), Math.max(...ds.map(r => r[3]))];
    if (bb.join() !== db.join()) { fails++; console.log('FAIL dilate parity', i, db, bb) }
    for (const r of ds) if (r[0] < db[0] || r[1] < db[1] || r[2] > db[2] || r[3] > db[3]) { fails++; console.log('FAIL containment', i, r, db) }
    for (const r of ds) if (!r.every(Number.isInteger)) { fails++; console.log('FAIL non-integer', r) }
  }
}
console.log(JSON.stringify({ratio: C.ratio, task: C.task, fails}));
process.exit(fails ? 1 : 0);
'''


class CandidateFile(unittest.TestCase):
    def test_candidate_body_is_marked_and_keeps_the_conservative_dilation(self):
        text = gr.candidate_text()
        body = gr.candidate_body(text)
        self.assertIsNotNone(body)
        self.assertTrue(body.startswith(gr.BODY_BEGIN) and body.endswith(gr.BODY_END))
        self.assertEqual(gr.body_sha(text), fc.sha_bytes(body.encode()))
        # unchanged TASK-265 envelope rules (two source texels per transfer, rounded outwards, two target texels)
        for part in ('Math.floor((b[0]-2)*next.width/previous.width)-2', 'Math.ceil((b[2]+2)*next.width/previous.width)+2',
                     'Math.floor((b[0]-2)*renderer.canvas.width/target.width)', 'Math.ceil((b[2]+2)*renderer.canvas.width/target.width)',
                     'union(s,a-2,b-2,a+2,b+2)'):
            self.assertIn(part, body, part)
        # same submission: one full drawImage of the level per composite call, clipped
        self.assertIn('c.drawImage(target,0,0,renderer.canvas.width,renderer.canvas.height)', body)
        self.assertEqual(body.count('drawImage(target'), 1)
        self.assertIn("c.clip();", body)
        for forbidden in ('getImageData(', 'createPattern(', "clip('nonzero')", "clip('evenodd')", '.putImageData(', 'imageSmoothingQuality'):
            self.assertNotIn(forbidden, body, forbidden + ' would repeat a rejected mechanism or change sampling')
        self.assertIn(f'const REGION_MAX_AREA_RATIO = {gr.REGION_MAX_AREA_RATIO};', body)
        self.assertIn("regionArea<=REGION_MAX_AREA_RATIO*(b[2]-b[0])*(b[3]-b[1])", body)
        self.assertNotIn(fc.MARKER, text, 'the candidate carries no harness marker')
        self.assertNotIn('__regionObserve=', text, 'the candidate only calls an observer when the harness installs one')

    def test_shipping_runtime_state_matches_a_non_accept_unless_integrated(self):
        src = (gr.ROOT / 'render/effects.js').read_text()
        if gr.runtime_has_candidate(gr.ROOT):
            self.assertIn(gr.runtime_body_sha(gr.ROOT), gr.accepted_runtime_bodies(gr.body_sha()), 'integrated body must equal the tested body or the TASK-311 sealed body')
            self.assertEqual(src.count(gr.BODY_BEGIN), 1)
        else:
            self.assertFalse(any(m in src for m in gr.CANDIDATE_MARKERS))

    def test_region_union_and_dilation_parity_under_node(self):
        node = node_binary(fallback=False)
        if not node:
            self.skipTest('playwright node unavailable')
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, dir=tempfile.gettempdir()) as f:
            f.write(NODE_SELFTEST)
            script = f.name
        try:
            p = subprocess.run([node, script, str(gr.CANDIDATE)], capture_output=True, text=True, timeout=120)
        finally:
            os.unlink(script)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        last = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(last['fails'], 0)
        self.assertEqual(last['ratio'], gr.REGION_MAX_AREA_RATIO)
        self.assertEqual(last['task'], gr.TASK)


class TimingRule(unittest.TestCase):
    def pairs(self, control, candidate, order='cf'):
        c = raw('c', 'bad', 'replay', 'p1', 'current', control, '2026-01-01T00:00:00Z' if order == 'cf' else '2026-01-01T00:01:00Z')
        k = raw('k', 'bad', 'replay', 'p1', 'candidate', candidate, '2026-01-01T00:01:00Z' if order == 'cf' else '2026-01-01T00:00:00Z')
        return gr.pair_record(c, k)

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
        rule = gr.timing_rule()
        self.assertEqual(rule['min_median_reduction'], 0.05)
        self.assertEqual(rule['max_worse'], 0.05)
        self.assertEqual(rule['acceptance_scenes'], ['replay'])
        self.assertEqual(rule['no_worse_scenes'], ['replay', 'moving-x'])
        self.assertIn('never pooled', rule['statement'])

    def test_sequence_alternates_and_covers_three_replay_pairs_per_mode(self):
        replay = [(rep, arm) for scene, rep, arm in gr.SEQUENCE if scene == 'replay']
        self.assertEqual(replay, [('p1', 'current'), ('p1', 'candidate'), ('p2', 'candidate'), ('p2', 'current'),
                                  ('p3', 'current'), ('p3', 'candidate')])
        self.assertEqual(sum(1 for s, _, _ in gr.SEQUENCE if s == 'moving-x'), 2)
        self.assertNotIn('moving-xy', gr.SCENES)

    def test_timing_verdicts_from_synthetic_raws(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            i = 0
            for mode in gr.MODES:
                for scene, rep, arm in gr.SEQUENCE:
                    ms = 100.0 if arm == 'current' else (92.0 if mode == 'bad' else 99.0)
                    r = raw(gr.case_name(mode, scene, rep, arm, i), mode, scene, rep, arm, ms, '2026-01-01T00:%02d:00Z' % i)
                    fc.dump(out / 'raw' / (r['case'] + '.json'), r)
                    i += 1
            t = gr.build_timings(out)
            self.assertEqual(t['modes']['bad']['verdict'], 'PASS')
            self.assertEqual(t['modes']['classic']['verdict'], 'IMMATERIAL')
            self.assertEqual(t['result'], 'FAIL', 'modes are never pooled: one failing mode fails the rule')
            self.assertEqual(t['modes']['bad']['scenes']['replay']['pair_count'], 3)
            self.assertAlmostEqual(t['modes']['bad']['median_reduction_fraction_replay'], 0.08)


class Decision(unittest.TestCase):
    def vv(self, exact):
        return {'exact_on_all_tested_engines': exact, 'engines_tested': ['chromium'], 'coverage': {}, 'cells': {}, 'failures': [] if exact else ['x']}

    def timings(self, result, verdicts):
        return {'result': result, 'modes': {m: {'verdict': v, 'median_reduction_fraction_replay': 0.1, 'worst_pair_worse_fraction_gameplay': 0.0}
                                            for m, v in verdicts.items()}}

    def test_accept_requires_exact_visuals_and_passing_timing_in_both_modes(self):
        d = gr.decide(self.vv(True), self.timings('PASS', {'bad': 'PASS', 'classic': 'PASS'}))
        self.assertEqual(d['verdict'], 'ACCEPT')
        d = gr.decide(self.vv(True), self.timings('FAIL', {'bad': 'PASS', 'classic': 'IMMATERIAL'}))
        self.assertEqual(d['verdict'], 'REJECT')
        self.assertTrue(any('classic' in r for r in d['reasons']))
        d = gr.decide(self.vv(False), {'result': 'OMITTED', 'reason': 'visual validation failed'})
        self.assertEqual(d['verdict'], 'REJECT')
        self.assertTrue(any('timing omitted' in r for r in d['reasons']))
        self.assertTrue(d['ticket_completion_is_not_60fps_acceptance'])

    def test_integration_status_is_consistent_with_runtime(self):
        status = gr.integration_status('REJECT')
        self.assertEqual(status['consistent_with_verdict'], not gr.runtime_has_candidate(gr.ROOT))
        status = gr.integration_status('ACCEPT')
        self.assertEqual(status['consistent_with_verdict'], status['tested_bodies_equal_runtime_bodies'])
        self.assertEqual(status['candidate_body_sha256'], gr.body_sha())


class VisualPlan(unittest.TestCase):
    def test_plan_covers_modes_seeds_contexts_and_arms(self):
        plan = gr.visual_plan(['chromium'])
        cells = {(p['context'], p['mode'], p['seed'], p['arm']) for p in plan}
        for mode in gr.MODES:
            for seed in (1, 4, 49):
                for arm in ('current', 'candidate'):
                    self.assertIn(('dpr1', mode, seed, arm), cells)
            self.assertIn(('dpr2', mode, 4, 'current'), cells)
        self.assertEqual(len(plan), 2 * 3 * 2 + 2 * 1 * 2)
        self.assertTrue(all(p['engine'] == 'chromium' for p in plan))

    def test_state_digest_ignores_candidate_only_fields(self):
        state = {k: 1 for k in gr.STATE_KEYS}
        self.assertEqual(gr.state_digest(dict(state, lastFrameAreas='x', regionCalls=3)), state)
        self.assertIn('levelSizes', gr.STATE_KEYS)

    def test_pixels_equal_prefers_decoded_pixels_over_png_bytes(self):
        a = {'final_sha256': 'png-a', 'final_pixels_sha256': 'px', 'source_sha256': 's', 'source_pixels_sha256': 'sp'}
        b = {'final_sha256': 'png-b', 'final_pixels_sha256': 'px', 'source_sha256': 't', 'source_pixels_sha256': 'sp'}
        self.assertTrue(gr.pixels_equal(a, b, 'final'))
        self.assertTrue(gr.pixels_equal(a, b, 'source'))
        self.assertFalse(gr.pixels_equal(dict(a, final_pixels_sha256=None), dict(b, final_pixels_sha256=None), 'final'))
        self.assertFalse(gr.pixels_equal(a, dict(b, source_pixels_sha256='sq'), 'source'))

    def test_area_summary_uses_region_when_used_else_box(self):
        amb = lambda box, region, used, rects: {'box': box, 'region': region, 'used': used, 'rects': rects}  # noqa: E731
        current = [[1, 0, 0, 1, amb([1.0, 1.0, 1.0, 1.0], [None] * 4, [None] * 4, [None] * 4), amb([0.1] * 4, [None] * 4, [None] * 4, [None] * 4), [1280, 720]],
                   [2, 0, 0, 2, amb([1.0, 1.0, 1.0, 1.0], [None] * 4, [None] * 4, [None] * 4), amb([0.1] * 4, [None] * 4, [None] * 4, [None] * 4), [1280, 720]]]
        candidate = [[1, 0, 0, 1, amb([1.0, 1.0, 1.0, 1.0], [0.1, 0.4, 0.95, 1.0], [True, True, False, False], [200, 100, 0, 0]),
                      amb([0.1] * 4, [0.05] * 4, [True] * 4, [10] * 4), [1280, 720]],
                     [None, None, None, None, None, None, [1280, 720]]]  # menu frame: ignored (no gameplay)
        a = gr.area_summary(current)['ambient']
        self.assertEqual(a['frames'], 2)
        self.assertEqual([l['mean_clip_fraction'] for l in a['levels']], [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(a['clipped_area_fraction_of_box'], 1.0)
        c = gr.area_summary(candidate)['ambient']
        self.assertEqual(c['frames'], 1)
        self.assertEqual([l['mean_clip_fraction'] for l in c['levels']], [0.1, 0.4, 1.0, 1.0])
        self.assertEqual([l['region_used_fraction'] for l in c['levels']], [1.0, 1.0, 0.0, 0.0])
        self.assertAlmostEqual(c['clipped_area_fraction_of_box'], 2.5 / 4)
        self.assertEqual(c['levels'][0]['mean_rects_when_used'], 200)

    def test_camera_and_mote_dependency(self):
        samples = [[1, 0, 0, 11, None, None, [1280, 720]], [2, -5, 0, 12, None, None, [1280, 720]],
                   [3, -10, 0, 13, None, None, [1280, 720]], [4, -10, 0, 14, None, None, [1280, 720]]]
        cam = gr.camera_dependency(samples)
        self.assertAlmostEqual(cam['x_changed_fraction'], 2 / 3)
        self.assertEqual(cam['y_changed_fraction'], 0.0)
        self.assertEqual(gr.mote_dependency(samples)['changed_fraction'], 1.0)
        self.assertEqual(gr.camera_dependency([[1, None, None, None, None, None, [1, 1]]])['pairs'], 0)

    def test_visual_contexts_name_the_required_scenarios(self):
        c = gr.VISUAL_CONTEXTS['dpr1']
        names = [n for n, _ in c['checkpoints']]
        self.assertEqual(names, ['start', 'early', 'mid', 'shake', 'late'])
        self.assertIn([640, 540], c['resizes'], 'letterbox bars')
        self.assertIn([1366, 768], c['resizes'], 'odd backing')
        self.assertEqual(gr.VISUAL_CONTEXTS['dpr2']['dpr'], 2)
        self.assertEqual(gr.VISUAL_ENGINES['chromium']['contexts'], ('dpr1', 'dpr2'))


class Hypothesis(unittest.TestCase):
    def test_hypothesis_is_pre_registered_with_provenance(self):
        h = gr.hypothesis({'current_commit': 'abc', 'current_tar_sha256': 'def'})
        self.assertEqual(h['candidate']['sha256'], gr.candidate_sha())
        self.assertEqual(h['candidate']['body_sha256'], gr.body_sha())
        self.assertEqual(h['control']['current_commit'], 'abc')
        self.assertIn('drawing-area reduction', h['mechanism'])
        self.assertIn('why_it_differs_from_the_integrated_geometry_clip', h)
        self.assertGreaterEqual(len(h['rejected_designs_isolated']), 3)
        self.assertTrue(all('Never installed' in d['reason'] for d in h['rejected_designs_isolated']))
        self.assertIn('60 FPS', h['not_claimed'])
        self.assertEqual(h['measured_target']['composite_off_median_saving_ms']['classic/ambient'], 49.25)
        json.dumps(h)


if __name__ == '__main__':
    unittest.main()
