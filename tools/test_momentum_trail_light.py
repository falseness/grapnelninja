"""Momentum lighting 6/17: the player trail is a faint light (TASK-056).

With MOMENTUM_FX on, LightmapRenderer.collectTrailLights adds
momentumLight.trailSamples lights spread evenly along the visible player
ribbon (PlayerTrailRenderer.getLightSamples): the ninja's light at
trailIntensity of its alpha, times the ribbon's own fade there (0 at the tail,
1 at the head), radius trailRadius, shadowed like the ninja light
(cutShadows, no deep shadows), outside the nearest-emitter cap. Samples and
lights are reused objects. Checks (tools/momentum_fx_support.py scenes,
1280x720):
- trail-light.json: run-right, background patches (PATCH px square, background
  mask of both frames) BESIDE_PX above the trail at 3 points >= MIN_NINJA_PX
  from the ninja: mean luminance / the same scene with the trail light
  disabled by a STYLE override (style.js served with trailIntensity 0) >=
  1.10; with an empty trail (ninja.track.pos = []) the frame (later
  effects such as the TASK-057 crystal rim off by a STYLE override) equals the parent
  commit's (maxDelta 0); the sample/light objects are the same after a second
  draw (no per-frame allocation); with the tail sample off screen on an
  empty pool the later samples still get lights (no hole, TASK-071);
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: run-right and blue-hit at 1280x720, compare-run-right.png and
  compare-blue-hit.png (vs the concepts).

MOMENTUM_TRAIL_LIGHT_EVIDENCE_DIR (default /tmp/momentum-trail-light)
receives the json files (compact) and shots/. MOMENTUM_TRAIL_LIGHT_PARENT is
the parent revision (default: the parent of the commit that added this file,
or HEAD while uncommitted). Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_ninja_light import gallery_frames

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_trail_light.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_TRAIL_LIGHT_EVIDENCE_DIR', '/tmp/momentum-trail-light'))
VIEWPORT = (1280, 720)
SCENE = 'run-right'
BESIDE_PX = 40
PATCH = 9
MIN_NINJA_PX = 300
MIN_RATIO = 1.10
# Canvas x of the 3 points along the run-right trail (ninja at x 523)
POINT_X = (80, 140, 200)
TRAIL_OFF = [('trailIntensity: 0.35', 'trailIntensity: 0')]
EMPTY_TRAIL = '() => { ninja.track.pos = [] }'
LATER_EFFECTS_OFF = [('rimStrength: 1', 'rimStrength: 0'), ('moteGain: 5', 'moteGain: 0'),
                     ('speedLight: true', 'speedLight: false'), ('show: true,\n            parallax', 'show: false,\n            parallax'),
                     ('show: true,\n            veinCount', 'show: false,\n            veinCount')]
REUSE = r'''() => {
    const l = visualEffects.lightmap
    draw()
    const lights = l.trailLights.slice(), samples = l.trailSamples.slice()
    const count = l.momentumLights.filter(x => x.trail).length
    draw()
    return {count: count, trailLights: l.trailLights.length, trailSamples: l.trailSamples.length,
            sameLights: lights.every((x, i) => l.trailLights[i] === x) && lights.length == l.trailLights.length,
            sameSamples: samples.every((x, i) => l.trailSamples[i] === x) && samples.length == l.trailSamples.length,
            inFrame: l.momentumLights.filter(x => x.trail).every(x => l.trailLights.includes(x)),
            alphas: l.momentumLights.filter(x => x.trail).map(x => Math.round(x.alpha * 1000) / 1000)}
}'''
# The tail sample off screen on an empty pool (TASK-071: MOMENTUM_RUN_SEED 6
# threw in collectTrailLights once the corner preview moved the camera)
TAIL_OFF_SCREEN = r'''() => {
    const l = visualEffects.lightmap
    draw()
    l.trailLights.length = 0
    let calls = 0
    l.isLightOnScreen = () => calls++ > 0
    const lights = []
    let error = null
    try { l.collectTrailLights(lights) } catch (e) { error = String(e) }
    delete l.isLightOnScreen
    return {error, count: lights.length, pool: l.trailLights.length,
            holes: Array.from(l.trailLights, x => !x).some(x => x)}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_TRAIL_LIGHT_PARENT'):
        return os.environ['MOMENTUM_TRAIL_LIGHT_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


class MomentumTrailLightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'trail-light.json').write_text(compact(cls.result))
        fx.close()

    def test_0_trail_lights_the_cave_beside_it(self):
        on = fx.capture(SCENE, VIEWPORT, fx_on=True)
        off_harness = fx.FxHarness('worktree', fx.harness().browser, style_patch=TRAIL_OFF)
        try:
            off = off_harness.capture(SCENE, VIEWPORT, fx_on=True)
        finally:
            off_harness.close()
        background = fx.background_mask(on) & fx.background_mask(off)
        lum_on, lum_off = fx.luminance(on), fx.luminance(off)
        trail = np.array(on.info['trail'], dtype=np.float64)
        nx, ny = on.info['ninja']
        rows = []
        half = PATCH // 2
        for x in POINT_X:
            y = int(round(np.interp(x, trail[:, 0], trail[:, 1]))) - BESIDE_PX
            mask = np.zeros(background.shape, dtype=bool)
            mask[y - half:y + half + 1, x - half:x + half + 1] = True
            mask &= background
            ratio = float(lum_on[mask].mean() / lum_off[mask].mean())
            rows.append({'x': x, 'y': y, 'ninjaDist': round(float(np.hypot(x - nx, y - ny)), 1),
                         'pixels': int(mask.sum()), 'lumOn': round(float(lum_on[mask].mean()), 4),
                         'lumOff': round(float(lum_off[mask].mean()), 4), 'ratio': round(ratio, 4),
                         'pass': ratio >= MIN_RATIO})
            print('beside trail', rows[-1])
        self.result.update(scene=SCENE, viewport=list(VIEWPORT), tree=on.info['rev'],
                           offOverride='style.js trailIntensity 0', besidePx=BESIDE_PX, minRatio=MIN_RATIO,
                           points=rows, frameMaxDelta=fx.max_delta(on, off))
        for row in rows:
            self.assertGreaterEqual(row['ninjaDist'], MIN_NINJA_PX)
            self.assertGreater(row['pixels'], PATCH * PATCH // 2)
            self.assertGreaterEqual(row['ratio'], MIN_RATIO)

    def test_1_empty_trail_equals_parent(self):
        # Later effects (the TASK-057 crystal rim, the TASK-058 lit motes) are
        # switched off by a STYLE override, so only the trail light is compared
        tree = fx.harness()
        later_off = [patch for patch in LATER_EFFECTS_OFF if patch[0] in (tree.root / 'style.js').read_text()]
        rim_harness = fx.FxHarness('worktree', tree.browser, style_patch=later_off) if later_off else None
        try:
            new = (rim_harness or tree).capture(SCENE, VIEWPORT, fx_on=True, extra_js=EMPTY_TRAIL)
        finally:
            if rim_harness:
                rim_harness.close()
        old = fx.capture(SCENE, VIEWPORT, fx_on=True, extra_js=EMPTY_TRAIL, rev=self.parent)
        self.assertEqual(new.info['trailPoints'], 0)
        d = fx.max_delta(new, old)
        print('empty trail maxDelta', d)
        self.result['emptyTrail'] = {'parent': old.info['rev'], 'trailPoints': 0, 'maxDelta': d,
                                     'laterEffectsOff': [patch[1] for patch in later_off],
                                     'identical': d == 0}
        self.assertEqual(d, 0)

    def test_2_lights_are_reused(self):
        context, page = fx.harness().open(VIEWPORT)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            reuse = page.evaluate(REUSE)
        finally:
            context.close()
        print('reuse', reuse)
        self.result['reuse'] = reuse
        self.assertGreaterEqual(reuse['count'], 3)
        self.assertLessEqual(reuse['trailLights'], 6)
        self.assertEqual(reuse['trailSamples'], 6)
        self.assertTrue(reuse['sameLights'])
        self.assertTrue(reuse['sameSamples'])
        self.assertTrue(reuse['inFrame'])

    def test_2b_tail_off_screen_grows_the_pool(self):
        context, page = fx.harness().open(VIEWPORT)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            r = page.evaluate(TAIL_OFF_SCREEN)
        finally:
            context.close()
        print('tail off screen', r)
        self.assertIsNone(r['error'])
        self.assertGreaterEqual(r['count'], 2)
        self.assertFalse(r['holes'])

    def test_3_switch_off_and_other_modes_equal_parent(self):
        rows = []
        pairs = {}
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                new = fx.capture(scene, viewport, fx_on=False)
                base = fx.capture(scene, viewport, fx_on=False, rev=self.parent)
                self.assertFalse(new.info['fx'])
                name = f'momentum-{scene}-{viewport[0]}x{viewport[1]}'
                pairs[name] = (new, base)
                d = fx.assert_equal_outside_pieces(new, base, check=False)
                rows.append({'scene': name, 'fx': 'off', **d, 'identical': d['differingPixels'] == 0})
        tree = fx.harness()
        parent = fx.harness(self.parent)
        new = gallery_frames(tree.browser, tree.url, ['classic', 'bad'])
        old = gallery_frames(parent.browser, parent.url, ['classic', 'bad'])
        for name in new:
            self.assertIs(new[name][1], True)
            d = fx.max_delta(new[name][0], old[name][0])
            rows.append({'scene': name, 'fx': 'on', 'maxDelta': d, 'identical': d == 0})
        for row in rows:
            print(row['scene'], 'fx', row['fx'], 'maxDelta', row['maxDelta'])
        (EVIDENCE_DIR / 'switch-off-identical.json').write_text(compact({
            'parent': parent.rev, 'tree': tree.rev, 'count': len(rows),
            'allIdentical': all(r['identical'] for r in rows), 'frames': rows}))
        self.assertEqual(len(rows), 16)
        for row in rows:
            with self.subTest(scene=row['scene']):
                if row['scene'] in pairs:
                    # TASK-122 crystal pieces: momentum scenes equal outside the blue pieces
                    fx.assert_equal_outside_pieces(*pairs[row['scene']])
                else:
                    self.assertEqual(row['maxDelta'], 0)

    def test_4_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        for scene in ('run-right', 'blue-hit'):
            frame = fx.capture(scene, VIEWPORT, fx_on=True)
            fx.save_png(frame, shots / f'1280x720-{scene}.png')
            fx.compare_png(frame, fx.CONCEPTS[scene], shots / f'compare-{scene}.png',
                           labels=('new frame (trail light)', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 4)


if __name__ == '__main__':
    unittest.main()
