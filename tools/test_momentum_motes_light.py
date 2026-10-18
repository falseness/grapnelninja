"""Momentum lighting 8/17: floating motes react to light (TASK-058).

With MOMENTUM_FX on, ParticleSystem.drawAmbientMotes samples the frame's
momentum lights (LightmapRenderer.getFrameLights / getLightAt: the radial
falloff of STYLE.lights.falloff, a blue from its outline, reach
momentumLight.moteReach, unshadowed) at every mote of moteLayout; a lit mote
grows and brightens by up to momentumLight.moteBoost and takes the brightest
light's colour. Checks (tools/momentum_fx_support.py scenes, 1280x720), the
parent commit being the TASK-057 look:
- motes.json: per mote of moteLayout in view whose (lit) halo box is clear of
  walls, pieces and HUD: distance to the ninja, to the nearest light (a blue
  measured from its outline, its circumscribed circle) and to the nearest
  blue; its brightness on (this tree) and on the parent; its hue. A mote's
  emitted light is the frame minus the same tree's frame with the motes
  hidden (QUALITY.ambient off), so the cave, the lights and nearby neon do
  not count; its pixels are where that excess is >= 1/4 of its max. brightness = peak of that excess luminance after a box filter
  the size of the unlit mote's halo (a pixel peak clips at 255 for the
  brightest motes, the filtered peak measures how much light the mote gives
  off where it is brightest); pixelPeak is recorded too. hue = hue of the
  mean colour of its pixels in the frame (the excess alone loses a channel
  clipped at 255). run-right: motes within
  NINJA_PX of the ninja are >= MIN_RATIO x brighter, hue within MAX_HUE_DEG
  of colors.player.halo. blue-corner: motes within BLUE_PX of the blue and
  more than LONE_PX from the ninja and every trail light: hue within
  MAX_HUE_DEG of momentum.blueStroke. run-right with the ninja at the left
  edge and no trail: motes more than FAR_PX from every light have maxDelta
  <= MAX_FAR_DELTA vs the parent over their halo box. The mote layout of
  both trees is the same (deterministic);
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: run-right and blue-corner at 1280x720, a 2x zoom crop round the
  ninja (run-right), compare-run-right.png (vs concept 5-rim-slow.png).

MOMENTUM_MOTES_LIGHT_EVIDENCE_DIR (default /tmp/momentum-motes-light)
receives the json files (compact) and shots/. MOMENTUM_MOTES_LIGHT_PARENT is
the parent revision (default: the parent of the commit that added this file,
or HEAD while uncommitted). Requires Playwright Chromium. No remote requests.
"""
import colorsys
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_ninja_light import gallery_frames

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_motes_light.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_MOTES_LIGHT_EVIDENCE_DIR', '/tmp/momentum-motes-light'))
VIEWPORT = (1280, 720)
NINJA_PX = 200
BLUE_PX = 150
LONE_PX = 400
FAR_PX = 700
MIN_RATIO = 1.3
MAX_HUE_DEG = 25
MAX_FAR_DELTA = 2
CONCEPT = fx.CONCEPT_DIR / '5-rim-slow.png'
NINJA_LIGHT = '#22c8ff'
BLUE_LIGHT = '#2f86ff'
HIDE_MOTES = '() => { QUALITY.ambient = false }'
# Ninja to the left edge of the view, no trail: most of the view is far
NINJA_LEFT = '''() => { ninja.x = -screen.x + 60 * width / scale[version] / 1280; ninja.track.pos = [] }'''

# The mote layout (core centre, core size, halo size in canvas px) and the
# frame's lights (canvas px; a blue's circumscribed radius) after the draw
MOTES = r'''() => {
    const k = canvas.width / width * scale[version]
    const L = visualEffects.particles.moteLayout
    const motes = []
    for (let j = 0; j < L.length; j += 8)
        motes.push([(L[j + 5] + L[j + 7] / 2) * k, (L[j + 6] + L[j + 7] / 2) * k, L[j + 7] * k, L[j + 3] * k])
    const lights = visualEffects.lightmap.momentumLights.map(l => ({x: l.x * k, y: l.y * k,
        kind: l.element ? 'blue' : l.trail ? 'trail' : 'ninja', color: l.color || null,
        outline: l.element ? l.element.circle.radius * k : 0}))
    return {motes: motes, lights: lights, moteBoost: STYLE.momentumLight ? STYLE.momentumLight.moteBoost || 0 : 0}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_MOTES_LIGHT_PARENT'):
        return os.environ['MOMENTUM_MOTES_LIGHT_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def capture_with_motes(scene, rev='worktree', extra_js=None):
    """(frame, motes data) of scene at VIEWPORT with MOMENTUM_FX on."""
    context, page = fx.harness(rev).open(VIEWPORT)
    try:
        page.evaluate(fx.BUILD, [fx.SCENE_SPECS[scene], True])
        if extra_js:
            page.evaluate(extra_js)
        info = page.evaluate(fx.DRAW)
        png = fx.render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        data = page.evaluate(MOTES)
        if page.errors:
            raise RuntimeError(f'page errors in {scene}: {page.errors}')
    finally:
        context.close()
    info.update(scene=scene, viewport=list(VIEWPORT), rev=rev)
    fx._HUD_BOXES[VIEWPORT] = (info['canvas'], info['hud'])
    return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info), data


def hex_hue(color):
    value = int(color[1:7], 16)
    return colorsys.rgb_to_hsv((value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255)[0] * 360


def hue_of(rgb):
    rgb = np.asarray(rgb, dtype=np.float64)
    if rgb.max() <= 0:
        return None
    h, s, _ = colorsys.rgb_to_hsv(*(rgb / rgb.max()))
    return round(h * 360, 1), round(s, 3)


def hue_distance(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def box_slices(x, y, size, shape):
    r = int(np.ceil(size / 2)) + 1
    return (slice(max(0, int(y) - r), min(shape[0], int(y) + r + 1)),
            slice(max(0, int(x) - r), min(shape[1], int(x) + r + 1)))


def filtered_peak(lum, size):
    """Max of the mean of lum over size x size windows (size >= 1)."""
    k = max(1, int(round(size)))
    h, w = lum.shape
    if h < k or w < k:
        return float(lum.mean())
    c = np.pad(np.cumsum(np.cumsum(lum, 0), 1), ((1, 0), (1, 0)))
    sums = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return float(sums.max() / (k * k))


def light_distances(x, y, lights):
    """{kind: nearest distance}; a blue's from its outline."""
    out = {}
    for light in lights:
        d = max(0.0, float(np.hypot(x - light['x'], y - light['y'])) - light['outline'])
        out[light['kind']] = min(out.get(light['kind'], np.inf), d)
    return out


def measure_motes(scene, parent, extra_js=None):
    """Rows per mote in view and clear of walls, pieces and HUD."""
    new, data = capture_with_motes(scene, extra_js=extra_js)
    old, old_data = capture_with_motes(scene, parent, extra_js=extra_js)
    hide = HIDE_MOTES if not extra_js else f'() => {{ ({extra_js})(); ({HIDE_MOTES})() }}'
    bare_new, _ = capture_with_motes(scene, extra_js=hide)
    bare_old, _ = capture_with_motes(scene, parent, extra_js=hide)
    same_layout = np.allclose(np.asarray(data['motes']), np.asarray(old_data['motes']))
    free = ~(fx.hud_mask(VIEWPORT, new.shape) | fx.piece_mask(new) | fx.wall_mask(new))
    excess_new = np.clip(np.asarray(new, np.float64) - np.asarray(bare_new, np.float64), 0, None)
    excess_old = np.clip(np.asarray(old, np.float64) - np.asarray(bare_old, np.float64), 0, None)
    lum_weights = np.array([0.2126, 0.7152, 0.0722]) / 255
    grow = 1 + data['moteBoost']
    rows = []
    for i, (x, y, size, halo) in enumerate(data['motes']):
        if not (0 <= x < VIEWPORT[0] and 0 <= y < VIEWPORT[1]):
            continue
        box = box_slices(x, y, halo * grow, new.shape)
        if not free[box].all():
            continue
        dist = light_distances(x, y, data['lights'])
        lum_new = excess_new[box] @ lum_weights
        lum_old = excess_old[box] @ lum_weights
        b_new, b_old = filtered_peak(lum_new, halo), filtered_peak(lum_old, halo)
        # The mote as seen: its pixels where it adds at least a quarter of
        # its strongest light (the excess itself loses a channel clipped at 255)
        seen = lum_new >= 0.25 * lum_new.max() if lum_new.max() > 0 else np.zeros(lum_new.shape, bool)
        hue = hue_of(np.asarray(new[box], np.float64)[seen].mean(0)) if seen.any() else None
        rows.append({'i': i, 'x': round(x, 1), 'y': round(y, 1), 'size': round(size, 2),
                     'ninjaPx': round(dist.get('ninja', np.inf), 1),
                     'nearestLightPx': round(min(dist.values()), 1) if dist else None,
                     'nearestLight': min(dist, key=dist.get) if dist else None,
                     'bluePx': round(dist['blue'], 1) if 'blue' in dist else None,
                     'trailPx': round(dist['trail'], 1) if 'trail' in dist else None,
                     'brightness': round(b_new, 4), 'brightnessParent': round(b_old, 4),
                     'ratio': round(b_new / b_old, 3) if b_old > 0 else None,
                     'pixelPeak': round(float(lum_new.max()), 4), 'pixelPeakParent': round(float(lum_old.max()), 4),
                     'hue': hue[0] if hue else None, 'sat': hue[1] if hue else None,
                     'maxDelta': fx.max_delta(new[box], old[box])})
    return {'scene': scene, 'ninja': [round(v, 1) for v in new.info['ninja']], 'sameLayout': bool(same_layout),
            'lights': [{'kind': l['kind'], 'x': round(l['x'], 1), 'y': round(l['y'], 1), 'color': l['color']}
                       for l in data['lights']], 'motes': rows}


class MomentumMotesLightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.result = {'parent': cls.parent, 'viewport': list(VIEWPORT),
                      'brightness': 'peak of the mote excess luminance (frame - motes hidden) box-filtered at the '
                                    'unlit halo size', 'hue': 'hue of the mean frame colour of the mote pixels (excess >= 1/4 of its max)',
                      'ninjaPx': NINJA_PX, 'minRatio': MIN_RATIO, 'maxHueDeg': MAX_HUE_DEG, 'bluePx': BLUE_PX,
                      'lonePx': LONE_PX, 'farPx': FAR_PX, 'maxFarDelta': MAX_FAR_DELTA,
                      'ninjaHue': round(hex_hue(NINJA_LIGHT), 1), 'blueHue': round(hex_hue(BLUE_LIGHT), 1)}

    @classmethod
    def tearDownClass(cls):
        (EVIDENCE_DIR / 'motes.json').write_text(compact(cls.result))
        fx.close()

    def test_0_motes_near_ninja_brighter_and_cyan(self):
        scene = measure_motes('run-right', self.parent)
        near = [r for r in scene['motes'] if r['ninjaPx'] <= NINJA_PX]
        for r in near:
            r['hueOff'] = round(hue_distance(r['hue'], hex_hue(NINJA_LIGHT)), 1)
            r['pass'] = bool(r['ratio'] >= MIN_RATIO and r['hueOff'] <= MAX_HUE_DEG)
            print('near ninja', r)
        self.result['nearNinja'] = {'scene': scene, 'checked': [r['i'] for r in near],
                                    'allPass': bool(near) and all(r['pass'] for r in near)}
        self.assertTrue(scene['sameLayout'])
        self.assertGreaterEqual(len(near), 2)
        for r in near:
            with self.subTest(mote=r['i']):
                self.assertGreaterEqual(r['ratio'], MIN_RATIO)
                self.assertLessEqual(r['hueOff'], MAX_HUE_DEG)

    def test_1_motes_near_lone_blue_blue(self):
        scene = measure_motes('blue-corner', self.parent)
        near = [r for r in scene['motes'] if r['bluePx'] is not None and r['bluePx'] <= BLUE_PX
                and r['ninjaPx'] > LONE_PX and (r['trailPx'] is None or r['trailPx'] > LONE_PX)]
        for r in near:
            r['hueOff'] = round(hue_distance(r['hue'], hex_hue(BLUE_LIGHT)), 1)
            r['pass'] = bool(r['hueOff'] <= MAX_HUE_DEG)
            print('near blue', r)
        self.result['nearBlue'] = {'scene': scene, 'checked': [r['i'] for r in near],
                                   'allPass': bool(near) and all(r['pass'] for r in near)}
        self.assertTrue(scene['sameLayout'])
        self.assertGreaterEqual(len(near), 2)
        for r in near:
            with self.subTest(mote=r['i']):
                self.assertLessEqual(r['hueOff'], MAX_HUE_DEG)

    def test_2_far_motes_unchanged(self):
        scene = measure_motes('run-right', self.parent, NINJA_LEFT)
        far = [r for r in scene['motes'] if r['nearestLightPx'] is None or r['nearestLightPx'] > FAR_PX]
        for r in far:
            r['pass'] = r['maxDelta'] <= MAX_FAR_DELTA
            print('far', r)
        self.result['far'] = {'scene': scene, 'variant': 'ninja at the left, no trail',
                              'checked': [r['i'] for r in far],
                              'allPass': bool(far) and all(r['pass'] for r in far)}
        self.assertGreaterEqual(len(far), 3)
        for r in far:
            with self.subTest(mote=r['i']):
                self.assertLessEqual(r['maxDelta'], MAX_FAR_DELTA)

    def test_3_switch_off_and_other_modes_equal_parent(self):
        rows = []
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                new = fx.capture(scene, viewport, fx_on=False)
                base = fx.capture(scene, viewport, fx_on=False, rev=self.parent)
                self.assertFalse(new.info['fx'])
                d = fx.max_delta(new, base)
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
            'parent': parent.rev, 'tree': tree.rev, 'count': len(rows),
            'allIdentical': all(r['identical'] for r in rows), 'frames': rows}))
        self.assertEqual(len(rows), 16)
        for row in rows:
            with self.subTest(scene=row['scene']):
                self.assertEqual(row['maxDelta'], 0)

    def test_4_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        frames = {}
        for scene in ('run-right', 'blue-corner'):
            frames[scene] = fx.capture(scene, VIEWPORT, fx_on=True)
            fx.save_png(frames[scene], shots / f'1280x720-{scene}.png')
        run = frames['run-right']
        nx, ny = (int(round(v)) for v in run.info['ninja'])
        w, h = VIEWPORT[0] // 2, VIEWPORT[1] // 2
        x0 = min(max(0, nx - w // 2), VIEWPORT[0] - w)
        y0 = min(max(0, ny - h // 2), VIEWPORT[1] - h)
        crop = Image.fromarray(np.asarray(run[y0:y0 + h, x0:x0 + w], dtype=np.uint8))
        crop.resize((w * 2, h * 2), Image.NEAREST).save(shots / f'zoom2x-run-right-{x0}-{y0}.png')
        fx.compare_png(run, CONCEPT, shots / 'compare-run-right.png', labels=('new frame (lit motes)', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 4)


if __name__ == '__main__':
    unittest.main()
