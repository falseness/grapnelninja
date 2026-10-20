"""Momentum lighting 16/17: cave colour by depth (score) (TASK-066).

BackgroundRenderer.getDepthGrade hue-rotates the far tile (base gradient,
crystals, haze), the near rocks and their edge fills about the RGB grey axis
by the hue of STYLE.momentumFx.depthStages reached by
scoreText.count.momentum, moving linearly over depthBlend points before each
stage in depthSteps steps; graded copies are built only when the step changes.
MOMENTUM_FX only; lights, neon, pieces, trail, motes and HUD keep their
colours. Checks (tools/momentum_fx_support.py run-right scene, 1280x720, the
score set before the one draw()):
- depth.json: mean colour of the light-free background (fx.background_mask
  of the score 0 frame, past LIGHT_FREE_PX from the ninja) at score 0, 150,
  400: score 0 hue within HUE_TOL of the same tree with the depth grade off
  (STYLE.momentumFx.depthStages null), shift at 150 -70 and at 400 +85 within
  HUE_TOL; neon (emissive px on the walls), pieces and HUD maxDelta <=
  REGION_MAX vs the same score with every stage hue 0; the score 0 frame
  equals the grade-off frame (maxDelta 0), and with
  MOMENTUM_DEPTH_GRADE_PARENT set also the parent's (hue and maxDelta 0;
  without it the parent comparison is skipped: later game changes such as
  the TASK-073 slow motion move the frame, TASK-100); after a restart (startGame) from
  score 400 the depth hue is 0 and the frame equals the same restart from
  score 0 (maxDelta 0; the restart lays another course than the scene's).
- rebuilds.json: a score ramp 0 -> 450 (one draw() per point) rebuilds the
  graded tiles once per distinct non-zero blend step (<= MAX_STEPS), and 300
  draws at a constant score (in a stage and inside a blend) rebuild nothing.
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at
  both viewports (and run-right at score 400) and the classic and bad
  test_visual_gallery frames with the switch on equal the same tree with the
  depth grade off, or the parent commit when MOMENTUM_DEPTH_GRADE_PARENT is
  set (decoded maxDelta 0);
- shots/: run-right at score 0, 150, 400 (1280x720), compare-teal.png (vs
  concept 11-depth-teal.png), compare-crimson.png (vs 12-depth-crimson.png).

MOMENTUM_DEPTH_GRADE_EVIDENCE_DIR (default /tmp/momentum-depth-grade)
receives the json files (compact) and shots/. MOMENTUM_DEPTH_GRADE_PARENT, when set, is
the parent revision the checks above also compare against (TASK-100: the
old default, the parent of the commit that added this file, predates the
TASK-073 slow motion and later game changes). Requires Playwright Chromium. No remote requests.
"""
import colorsys
import io
import json
import os
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_ninja_light import gallery_frames

EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_DEPTH_GRADE_EVIDENCE_DIR', '/tmp/momentum-depth-grade'))
VIEWPORT = (1280, 720)
SCENE = 'run-right'
SCORES = (0, 150, 400)
TARGET_SHIFT = {0: 0, 150: -70, 400: 85}
HUE_TOL = 15
REGION_MAX = 3
LIGHT_FREE_PX = 400
MAX_STEPS = 40
GRADE_OFF = [('score: 150, hue: -82', 'score: 150, hue: 0'), ('score: 400, hue: 92', 'score: 400, hue: 0')]
# The depth grade switched off: every getDepthGrade/prepareDepthGrade path
# returns at once
NO_GRADE = [('depthStages: Object.freeze([', 'depthStages: null && Object.freeze([')]

SET_SCORE = '() => { scoreText.count.momentum = %d }'

# Score ramp 0 -> 450 one draw() per point, then 300 draws at a constant
# score in a stage (450) and inside a blend (120), then a restart
RAMP = r'''() => {
    const bg = visualEffects.background, grade = bg.depthGrade
    const start = grade.rebuilds, hues = new Set(), steps = []
    for (let s = 0; s <= 450; ++s) {
        scoreText.count.momentum = s
        draw()
        const hue = bg.getDepthHue(s)
        if (hue && !hues.has(hue)) { hues.add(hue); steps.push([s, hue]) }
    }
    const ramp = grade.rebuilds - start
    const constant = []
    for (const s of [450, 120]) {
        scoreText.count.momentum = s
        draw()
        const before = grade.rebuilds
        for (let i = 0; i < 300; ++i)
            draw()
        constant.push({score: s, hue: bg.getDepthHue(s), frames: 300, rebuilds: grade.rebuilds - before})
    }
    return {rampFrom: 0, rampTo: 450, rampRebuilds: ramp, distinctSteps: hues.size, steps: steps,
            constant: constant}
}'''

# Score 400 drawn, then startGame (the restart path: chooseVersion resets the
# score) and the scene built again
RESTART = '''() => { const scoreBefore = scoreText.count.momentum
    const hueBefore = visualEffects.background.getDepthHue(scoreBefore)
    startGame('momentum'); cancelAnimationFrame(game)
    window.__restart = {scoreBefore: scoreBefore, hueBefore: hueBefore, scoreAfter: scoreText.count.momentum,
                        hueAfter: visualEffects.background.getDepthHue(scoreText.count.momentum)} }'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    """The MOMENTUM_DEPTH_GRADE_PARENT revision, or None (no parent comparisons)."""
    return os.environ.get('MOMENTUM_DEPTH_GRADE_PARENT') or None


def hue_deg(rgb):
    return colorsys.rgb_to_hsv(*[c / 255 for c in rgb])[0] * 360


def hue_shift(a, b):
    """Signed b - a in (-180, 180]."""
    return (b - a + 180) % 360 - 180


def score_frame(harness, score, fx_on=True):
    return harness.capture(SCENE, VIEWPORT, fx_on=fx_on, extra_js=SET_SCORE % score)


def light_free_mask(frame):
    h, w = frame.shape[:2]
    nx, ny = fx.ninja_screen_pos(frame)
    yy, xx = np.mgrid[0:h, 0:w]
    return fx.background_mask(frame) & (np.hypot(xx - nx, yy - ny) > LIGHT_FREE_PX)


def mean_rgb(frame, mask):
    return [float(v) for v in np.asarray(frame)[mask].mean(axis=0)]


def region_deltas(frame, reference):
    delta = np.abs(np.asarray(frame, np.int16) - np.asarray(reference, np.int16)).max(axis=2)
    neon = fx.emissive_mask(reference) & fx.wall_mask(reference)
    regions = {'neon': neon, 'pieces': fx.piece_mask(reference),
               'hud': fx.hud_mask(reference.info['viewport'], reference.shape)}
    return {name: {'pixels': int(mask.sum()), 'maxDelta': int(delta[mask].max())} for name, mask in regions.items()}


class MomentumDepthGradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        tree = fx.harness()
        cls.grade_off = fx.FxHarness('worktree', tree.browser, style_patch=GRADE_OFF)
        cls.no_grade = fx.FxHarness('worktree', tree.browser, style_patch=NO_GRADE)
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'depth.json').write_text(compact(cls.result))
        cls.grade_off.close()
        cls.no_grade.close()
        fx.close()

    def test_0_hue_by_score(self):
        tree = fx.harness()
        frames = {score: score_frame(tree, score) for score in SCORES}
        off0 = score_frame(self.no_grade, 0)
        parent0 = score_frame(fx.harness(self.parent), 0) if self.parent else None
        mask = light_free_mask(frames[0])
        off_hue = hue_deg(mean_rgb(off0, mask))
        hue0 = hue_deg(mean_rgb(frames[0], mask))
        rows = []
        for score in SCORES:
            mean = mean_rgb(frames[score], mask)
            shift = hue_shift(hue0, hue_deg(mean))
            regions = region_deltas(frames[score], score_frame(self.grade_off, score))
            rows.append({'score': score, 'meanRgb': [round(v, 2) for v in mean], 'hue': round(hue_deg(mean), 2),
                         'shift': round(shift, 2), 'targetShift': TARGET_SHIFT[score],
                         'shiftError': round(abs(shift - TARGET_SHIFT[score]), 2), 'regions': regions})
            print('score', rows[-1])
        result = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': tree.rev,
                  'lightFree': {'pastNinjaPx': LIGHT_FREE_PX, 'pixels': int(mask.sum())},
                  'gradeOffHue': round(off_hue, 2), 'hue0VsGradeOff': round(abs(hue_shift(off_hue, hue0)), 2),
                  'score0MaxDeltaVsGradeOff': fx.max_delta(frames[0], off0),
                  'parent': None, 'tolerance': HUE_TOL, 'regionMax': REGION_MAX, 'scores': rows}
        if parent0 is not None:
            parent_hue = hue_deg(mean_rgb(parent0, mask))
            result.update(parent=fx.harness(self.parent).rev, parentHue=round(parent_hue, 2),
                          hue0VsParent=round(abs(hue_shift(parent_hue, hue0)), 2),
                          score0MaxDeltaVsParent=fx.max_delta(frames[0], parent0))
        self.result['depth'] = result
        print('score 0', {k: v for k, v in result.items() if k != 'scores'})
        self.assertGreater(mask.sum(), 50000)
        self.assertLessEqual(result['hue0VsGradeOff'], HUE_TOL)
        self.assertEqual(result['score0MaxDeltaVsGradeOff'], 0)
        if parent0 is not None:
            self.assertLessEqual(result['hue0VsParent'], HUE_TOL)
            self.assertEqual(result['score0MaxDeltaVsParent'], 0)
        for row in rows:
            with self.subTest(score=row['score']):
                self.assertLessEqual(row['shiftError'], HUE_TOL)
                for name, region in row['regions'].items():
                    self.assertGreater(region['pixels'], 0, name)
                    self.assertLessEqual(region['maxDelta'], REGION_MAX, name)

    def restart_frame(self, score_before):
        """Frame after a restart (startGame) from score_before, the scene built again."""
        context, page = fx.harness().open(VIEWPORT)
        try:
            spec = fx.SCENE_SPECS[SCENE]
            page.evaluate(fx.BUILD, [spec, True])
            page.evaluate(SET_SCORE % score_before)
            page.evaluate(fx.DRAW)
            page.evaluate(RESTART)
            page.evaluate(fx.BUILD, [spec, True])
            info = page.evaluate(fx.DRAW)
            info.update(scene=SCENE, viewport=list(VIEWPORT))
            png = fx.render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
            state = page.evaluate('() => window.__restart')
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info), state

    def test_1_restart(self):
        # The restart rebuilds the course (another layout than the seeded
        # scene), so the control is the same restart path from score 0
        after, state = self.restart_frame(400)
        control, control_state = self.restart_frame(0)
        mask = light_free_mask(control)
        hue_after, hue0 = hue_deg(mean_rgb(after, mask)), hue_deg(mean_rgb(control, mask))
        state = {'deep': state, 'control': control_state, 'lightFreePixels': int(mask.sum()),
                 'backgroundHueAfter': round(hue_after, 2), 'backgroundHueStage0': round(hue0, 2),
                 'hueDistance': round(abs(hue_shift(hue0, hue_after)), 2),
                 'maxDeltaVsRestartFromScore0': fx.max_delta(after, control)}
        print('restart', state)
        self.result['restart'] = state
        self.assertEqual(state['deep']['hueBefore'], 92)
        self.assertEqual(state['deep']['scoreAfter'], 0)
        self.assertEqual(state['deep']['hueAfter'], 0)
        self.assertGreater(mask.sum(), 20000)
        self.assertLessEqual(state['hueDistance'], 1)
        self.assertEqual(state['maxDeltaVsRestartFromScore0'], 0)

    def test_2_rebuilds(self):
        context, page = fx.harness().open(VIEWPORT)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            result = page.evaluate(RAMP)
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        result['maxSteps'] = MAX_STEPS
        print('rebuilds', {k: v for k, v in result.items() if k != 'steps'})
        (EVIDENCE_DIR / 'rebuilds.json').write_text(compact(result))
        self.assertGreater(result['distinctSteps'], 0)
        self.assertLessEqual(result['distinctSteps'], MAX_STEPS)
        self.assertEqual(result['rampRebuilds'], result['distinctSteps'])
        for row in result['constant']:
            self.assertEqual(row['rebuilds'], 0)

    def test_3_switch_off_and_other_modes_equal_parent(self):
        tree = fx.harness()
        ref = fx.harness(self.parent) if self.parent else self.no_grade
        rows = []
        pairs = {}
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                new = tree.capture(scene, viewport, fx_on=False)
                base = ref.capture(scene, viewport, fx_on=False)
                self.assertFalse(new.info['fx'])
                name = f'momentum-{scene}-{viewport[0]}x{viewport[1]}'
                pairs[name] = (new, base)
                d = fx.assert_equal_outside_pieces(new, base, check=False)
                rows.append({'scene': name, 'fx': 'off', **d, 'identical': d['differingPixels'] == 0})
        # The switch off deep in the run too
        new = score_frame(tree, 400, fx_on=False)
        base = score_frame(ref, 400, fx_on=False)
        name = f'momentum-{SCENE}-score400-1280x720'
        pairs[name] = (new, base)
        d = fx.assert_equal_outside_pieces(new, base, check=False)
        rows.append({'scene': name, 'fx': 'off', **d, 'identical': d['differingPixels'] == 0})
        new = gallery_frames(tree.browser, tree.url, ['classic', 'bad'])
        old = gallery_frames(ref.browser, ref.url, ['classic', 'bad'], prepare=ref.patch_context)
        for name in new:
            self.assertIs(new[name][1], True)
            d = fx.max_delta(new[name][0], old[name][0])
            rows.append({'scene': name, 'fx': 'on', 'maxDelta': d, 'identical': d == 0})
        for row in rows:
            print(row['scene'], 'fx', row['fx'], 'maxDelta', row['maxDelta'])
        (EVIDENCE_DIR / 'switch-off-identical.json').write_text(compact({
            'reference': ref.rev + (' depth grade off' if ref is self.no_grade else ''), 'tree': tree.rev,
            'count': len(rows),
            'allIdentical': all(r['identical'] for r in rows), 'frames': rows}))
        self.assertEqual(len(rows), 17)
        for row in rows:
            with self.subTest(scene=row['scene']):
                if row['scene'] in pairs:
                    # TASK-122 crystal pieces: momentum scenes equal outside the blue pieces
                    fx.assert_equal_outside_pieces(*pairs[row['scene']])
                else:
                    self.assertEqual(row['maxDelta'], 0)

    def test_4_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        tree = fx.harness()
        frames = {score: score_frame(tree, score) for score in SCORES}
        for score, frame in frames.items():
            fx.save_png(frame, shots / f'1280x720-run-right-score{score}.png')
        fx.compare_png(frames[150], fx.CONCEPT_DIR / '11-depth-teal.png', shots / 'compare-teal.png',
                       labels=('new frame, score 150 (teal stage)', 'concept'))
        fx.compare_png(frames[400], fx.CONCEPT_DIR / '12-depth-crimson.png', shots / 'compare-crimson.png',
                       labels=('new frame, score 400 (crimson stage)', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
