"""Momentum lighting 3/17: dimmed ambient and the ninja's point light (TASK-053).

With MOMENTUM_FX on, momentum multiplies the cave background by the
ambient grey (STYLE.momentumLight.ambient) plus a cyan light round the ninja
and adds a faint cyan haze; everything drawn after the lights layer keeps its
pixels. On the 4 reference scenes of tools/momentum_fx_support.py at
1280x720 and 390x844 this suite checks, fx on against fx off:
- farRatio: mean background luminance farther than 450 px at 1080 from the
  ninja <= 0.60 (the far cave is dimmed);
- nearRatio: mean background luminance within 80 px at 1080 of the ninja,
  outside its sprite (2 ninja radii), >= 1.25 (the cyan pool);
- emissiveMaxDelta: emissive art pixels (neon outlines, pieces, HUD, trail)
  differ by <= 3.
The cave itself passes the emissive_mask threshold in places (lit crystal
facets, the glow round the ninja), so the emissive art is emissive_mask of
both frames restricted to opaque bright art: the scene drawn once over a
black and once over a white background, lights off, equal there (opaque:
the background cannot show through) and emissive over black. The far
mask is background_mask of both frames; the near mask (where the trail and
player glow lift every pixel over the emissive threshold) is the corridor
interior outside pieces, HUD and the emissive art. The trail ribbon is
translucent, so the light leaves the cave under it undimmed: its emissive
pixels (emissive_mask of both frames within 3 px of the trail polyline) join
the emissive art in emissiveMaxDelta (artMaxDelta / trailMaxDelta apart).
Also:
- allocations: 120 frames with the ninja moving create no CanvasGradient
  inside the lightmap (clear/draw/composite) or the background after the
  first frame;
- switch off: the 4 scenes with MOMENTUM_FX off at both viewports, and the
  classic and bad frames of test_visual_gallery (same viewports and frozen
  ticks) with the switch on, equal the parent commit (decoded maxDelta 0).

MOMENTUM_NINJA_LIGHT_EVIDENCE_DIR (default /tmp/momentum-ninja-light)
receives ninja-light.json, allocations.json, switch-off-identical.json
(compact) and shots/: run-right and mid-shaft at 1280x720 fx on and off,
compare-run-right.png / compare-mid-shaft.png (left the new frame, right the
concept). MOMENTUM_NINJA_LIGHT_PARENT is the parent revision (default: the
parent of the commit that added this file, or HEAD while uncommitted).
Frames of the tree are taken with LATER_EFFECTS_OFF served in style.js
(later tickets' effects on emissive art, e.g. the TASK-058 lit motes).
Requires Playwright Chromium. No remote requests.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from perf_mobile import SEED_SCRIPT
from render_snapshot import ADVANCE_SCRIPT, CLOCK_SCRIPT, SEED, SETUP_SCRIPT, boot_frozen, input_script, png_bytes
import visual_gallery as vg

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_ninja_light.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_NINJA_LIGHT_EVIDENCE_DIR', '/tmp/momentum-ninja-light'))
FAR_PX = 450
NEAR_PX = 80
MAX_FAR_RATIO = 0.60
MIN_NEAR_RATIO = 1.25
MAX_EMISSIVE_DELTA = 3
LATER_EFFECTS_OFF = [('moteGain: 5', 'moteGain: 0')]
ALLOC_FRAMES = 120
# Opaque art: black- and white-background captures differ by at most this
OPAQUE_TOLERANCE = 2
# Background replaced by a flat colour and no lights (opaque-art captures)
FLAT_BACKGROUND = '''() => {
    drawBackgroundLayer = () => {
        ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0)
        ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'
        ctx.fillStyle = '%s'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.restore()
    }
    drawLightsLayer = () => {}
}'''
SHOT_SCENES = ['run-right', 'mid-shaft']


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_NINJA_LIGHT_PARENT'):
        return os.environ['MOMENTUM_NINJA_LIGHT_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def emissive_art(on, off, black, white):
    opaque = np.abs(np.asarray(black, dtype=np.int16) - np.asarray(white, dtype=np.int16)).max(axis=2) \
        <= OPAQUE_TOLERANCE
    return fx.emissive_mask(on) & fx.emissive_mask(off) & fx.emissive_mask(black) & opaque


def trail_mask(frame, half_width=3):
    image = Image.new('1', (frame.shape[1], frame.shape[0]), 0)
    ImageDraw.Draw(image).line([tuple(p) for p in frame.info['trail']], fill=1, width=2 * half_width + 1)
    return np.asarray(image, dtype=bool)


def light_metrics(on, off, black, white):
    h, w = on.shape[:2]
    unit = h / 1080
    nx, ny = on.info['ninja']
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(xx + 0.5 - nx, yy + 0.5 - ny)
    background = fx.background_mask(on) & fx.background_mask(off)
    far = background & (dist > FAR_PX * unit)
    emissive = emissive_art(on, off, black, white)
    scenery = ~(fx.wall_mask(on) | fx.piece_mask(on) | fx.hud_mask(on.info['viewport'], on.shape) | emissive)
    near = scenery & (dist <= NEAR_PX * unit) & (dist > 2 * on.info['ninjaRadius'])
    trail = trail_mask(on) & fx.emissive_mask(on) & fx.emissive_mask(off) & ~fx.hud_mask(on.info['viewport'], on.shape)
    delta = np.abs(np.asarray(on, dtype=np.int16) - np.asarray(off, dtype=np.int16)).max(axis=2)
    far_on, far_off = fx.region_luminance(on, far), fx.region_luminance(off, far)
    near_on, near_off = fx.region_luminance(on, near), fx.region_luminance(off, near)
    return {
        'farPixels': int(far.sum()), 'farOn': round(far_on, 5), 'farOff': round(far_off, 5),
        'farRatio': round(far_on / far_off, 4),
        'nearPixels': int(near.sum()), 'nearOn': round(near_on, 5), 'nearOff': round(near_off, 5),
        'nearRatio': round(near_on / near_off, 4),
        'emissivePixels': int((emissive | trail).sum()), 'emissiveMaxDelta': int(delta[emissive | trail].max()),
        'artPixels': int(emissive.sum()), 'artMaxDelta': int(delta[emissive].max()),
        'trailPixels': int(trail.sum()), 'trailMaxDelta': int(delta[trail].max()) if trail.any() else None,
    }


# Counts CanvasGradients made inside the lightmap and the background over
# ALLOC_FRAMES frames after the first, the ninja moving along the corridor
ALLOC_SCRIPT = r'''frames => {
    const proto = CanvasRenderingContext2D.prototype
    const counts = {lightmap: 0, other: 0}
    let inside = 0
    const wrapGradient = name => {
        const original = proto[name]
        proto[name] = function(...args) {
            ++counts[inside ? 'lightmap' : 'other']
            return original.apply(this, args)
        }
    }
    ;['createRadialGradient', 'createLinearGradient', 'createConicGradient'].forEach(wrapGradient)
    const wrapMethod = (object, name) => {
        const original = object[name]
        object[name] = function(...args) {
            ++inside
            try { return original.apply(this, args) } finally { --inside }
        }
    }
    const lightmap = visualEffects.lightmap
    ;['clear', 'draw', 'composite'].forEach(name => wrapMethod(lightmap, name))
    wrapMethod(visualEffects.background, 'draw')
    // Empty gradient caches: the first frame must build its gradients
    lightmap.gradients.clear()
    lightmap.momentumGradient = null
    visualEffects.background.gradientCache.clear()
    visualEffects.background.lastGameGradients = null
    draw()
    const first = {lightmap: counts.lightmap, other: counts.other}
    counts.lightmap = 0
    counts.other = 0
    const x0 = ninja.x
    for (let i = 0; i < frames; ++i) {
        ninja.x = x0 + i * 3
        ninja.y += (i % 2 ? 1 : -1) * 2
        draw()
    }
    return {firstFrame: first, afterFirst: {lightmap: counts.lightmap, other: counts.other},
            frames: frames, momentumLight: lightmap.shouldDrawMomentumLight(), ninjaMovedPx: (ninja.x - x0)}
}'''


def gallery_frames(browser, url, modes):
    """Decoded frames of modes at the test_visual_gallery viewports and ticks."""
    frames = {}
    for vp in vg.VIEWPORTS:
        script = input_script(SEED, max(vg.TICKS), vp['width'], vp['height'])
        for mode in modes:
            context = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                          device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
            context.add_init_script(SEED_SCRIPT % SEED)
            context.add_init_script(CLOCK_SCRIPT)
            page = context.new_page()
            try:
                page.goto(url + 'index.html', wait_until='load')
                boot_frozen(page)
                page.evaluate(SETUP_SCRIPT, [script, vp['touch']])
                page.evaluate('''mode => {
                    startGame(mode)
                    if (continueOffer.otherVersion) continueOffer.otherVersion = () => version
                    if (continueOffer.switchTarget) continueOffer.switchTarget = () => version
                }''', mode)
                fx_state = page.evaluate("typeof MOMENTUM_FX != 'undefined' ? MOMENTUM_FX.enabled : null")
                for tick in vg.TICKS:
                    page.evaluate(ADVANCE_SCRIPT, tick)
                    name = f'{vp["name"]}-{mode}-tick{tick:04d}'
                    png = png_bytes(page.evaluate('() => __snap.capture()'))
                    frames[name] = (np.asarray(Image.open(io.BytesIO(png)).convert('RGBA')), fx_state)
            finally:
                context.close()
    return frames


class MomentumNinjaLightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.frames = {}
        # Later effects that change emissive art on purpose (the TASK-058 lit
        # motes) are switched off by a STYLE override, so only the ninja
        # light is compared
        tree = fx.harness()
        later_off = [patch for patch in LATER_EFFECTS_OFF if patch[0] in (tree.root / 'style.js').read_text()]
        cls.light_harness = fx.FxHarness('worktree', tree.browser, style_patch=later_off) if later_off else None
        light = cls.light_harness or tree
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                for on in (True, False):
                    cls.frames[scene, viewport, on] = light.capture(scene, viewport, fx_on=on)
                for colour in ('black', 'white'):
                    cls.frames[scene, viewport, colour] = light.capture(
                        scene, viewport, extra_js=FLAT_BACKGROUND % colour)

    @classmethod
    def tearDownClass(cls):
        if cls.light_harness:
            cls.light_harness.close()
        fx.close()

    def test_0_far_dimmed_near_lit_emissive_kept(self):
        results = []
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                on, off = self.frames[scene, viewport, True], self.frames[scene, viewport, False]
                self.assertTrue(on.info['fx'])
                self.assertFalse(off.info['fx'])
                metrics = light_metrics(on, off, self.frames[scene, viewport, 'black'],
                                        self.frames[scene, viewport, 'white'])
                metrics.update(scene=scene, viewport=list(viewport))
                metrics['pass'] = (metrics['farRatio'] <= MAX_FAR_RATIO and metrics['nearRatio'] >= MIN_NEAR_RATIO
                                   and metrics['emissiveMaxDelta'] <= MAX_EMISSIVE_DELTA)
                results.append(metrics)
                print(f'{scene} {viewport[0]}x{viewport[1]}: farRatio {metrics["farRatio"]} '
                      f'nearRatio {metrics["nearRatio"]} emissiveMaxDelta {metrics["emissiveMaxDelta"]}')
        (EVIDENCE_DIR / 'ninja-light.json').write_text(compact({
            'thresholds': {'opaqueTolerance': OPAQUE_TOLERANCE, 'farPx1080': FAR_PX, 'nearPx1080': NEAR_PX, 'maxFarRatio': MAX_FAR_RATIO,
                           'minNearRatio': MIN_NEAR_RATIO, 'maxEmissiveDelta': MAX_EMISSIVE_DELTA},
            'tree': fx.harness().rev, 'results': results, 'allPass': all(r['pass'] for r in results)}))
        for r in results:
            with self.subTest(scene=r['scene'], viewport=r['viewport']):
                self.assertGreater(r['farPixels'], 1000)
                self.assertGreater(r['nearPixels'], 50)
                self.assertGreater(r['emissivePixels'], 1000)
                self.assertLessEqual(r['farRatio'], MAX_FAR_RATIO)
                self.assertGreaterEqual(r['nearRatio'], MIN_NEAR_RATIO)
                self.assertLessEqual(r['emissiveMaxDelta'], MAX_EMISSIVE_DELTA)

    def test_1_no_gradients_after_first_frame(self):
        harness = fx.harness()
        context, page = harness.open((1280, 720))
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS['run-right'], True])
            result = page.evaluate(ALLOC_SCRIPT, ALLOC_FRAMES)
            self.assertEqual(page.errors, [])
        finally:
            context.close()
        result.update(scene='run-right', viewport=[1280, 720], tree=harness.rev)
        (EVIDENCE_DIR / 'allocations.json').write_text(compact(result))
        print('allocations', result)
        self.assertTrue(result['momentumLight'])
        self.assertGreater(result['firstFrame']['lightmap'], 0)
        self.assertEqual(result['afterFirst']['lightmap'], 0)

    def test_2_switch_off_and_other_modes_equal_parent(self):
        rows = []
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                base = fx.capture(scene, viewport, fx_on=False, rev=self.parent)
                # The tree as served, without the LATER_EFFECTS_OFF override
                d = fx.max_delta(fx.capture(scene, viewport, fx_on=False), base)
                rows.append({'scene': f'momentum-{scene}-{viewport[0]}x{viewport[1]}', 'fx': 'off',
                             'maxDelta': d, 'identical': d == 0})
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
            'parent': parent.rev, 'tree': tree.rev, 'ticks': vg.TICKS, 'count': len(rows),
            'allIdentical': all(r['identical'] for r in rows), 'frames': rows}))
        self.assertEqual(len(rows), 16)
        for row in rows:
            with self.subTest(scene=row['scene']):
                self.assertEqual(row['maxDelta'], 0)

    def test_3_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        for scene in SHOT_SCENES:
            on, off = self.frames[scene, (1280, 720), True], self.frames[scene, (1280, 720), False]
            fx.save_png(on, shots / f'1280x720-{scene}-fx-on.png')
            fx.save_png(off, shots / f'1280x720-{scene}-fx-off.png')
            fx.compare_png(on, fx.CONCEPTS[scene], shots / f'compare-{scene}.png',
                           labels=('new frame (fx on)', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 6)


if __name__ == '__main__':
    unittest.main()
