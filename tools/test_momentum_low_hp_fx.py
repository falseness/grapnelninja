"""Momentum lighting 15/17: last-heart state (TASK-065).

While momentumState.hp == 1 the ninja light (and its haze) takes
STYLE.momentum.heartStroke and its alpha pulses on the render clock
(LightmapRenderer.updateLowHp: x 1 - lowHpPulse (1 - cos(2 pi t /
lowHpPulseMs)) / 2), and a red vignette (cached tile per canvas size, alpha
0 inside lowHpVignetteInner of the half diagonal, lowHpVignette at the
corners) is laid under the HUD with the HUD boxes left out. Both blend over
lowHpBlendMs of render clock. MOMENTUM_FX only. Checks (tools/
momentum_fx_support.py blue-corner scene, 1280x720; hp is set before the one
draw(), the pulse phase via the hook visualEffects.lightmap.lowHp
.pulseShiftMs so nothing else of the frame moves; the ninja speed is pinned
at PIN_SPEED of the effective cap GAMEPLAY.momentumMaxSpeed *
momentumMotionScale(1): the scene's own speed is 0.9 of the unscaled cap,
which saturates the speed light since the slow motion (9174492), and the
hp 1 haze, 2.5x and 1.58x as wide at s 1, then reaches the centre box,
TASK-099):
- low-hp.json: at hp 1 the mean colour of the background px (fx
  .background_mask of the hp 1 frame with the ninja light and haze alpha 0,
  past 1.5 ninja radii) within NEAR_PX of the ninja has a hue within
  HUE_TOL of heartStroke's (the hue of the light alone, mean colour minus
  that of the unlit frame, is recorded too); corners (4 boxes of 1/8 of the view
  each, HUD boxes out) mean red >= +CORNER_RED vs hp 2; the centre box (1/10
  of the view each way) maxDelta <= CENTRE_MAX vs hp 2. Pulse: at phases 0,
  1/4, 1/2, 3/4 of lowHpPulseMs the ninja light (mean luminance in the
  background px (of the dark frame) LIGHT_RING from the ninja minus the same frame with the ninja
  light and haze alpha 0) max/min >= PULSE_RATIO, and each phase one period
  later equals it (maxDelta 0). hp 2 and hp 5 equal the same tree with the
  last-heart style neutralised (LOW_HP_OFF) at maxDelta 0, so hp >= 2 is
  checked on any later tree (TASK-147: the TASK-064 parent's corridors and
  camera predate TASK-128/133; MOMENTUM_LOW_HP_FX_PARENT set: that revision,
  outside the pieces).
  HUD boxes (fx.hud_mask) maxDelta 0 vs the hp 1 frame without
  the vignette (lowHpVignette 0). Blend: hp 2 drawn at T0, hp 1 at T0 + 150,
  T0 + 300 gives blend 0.5, 1; back to hp 2 at + 450 gives 0.5.
- switch-off-identical.json: the classic and bad test_visual_gallery frames
  with the switch on equal the parent commit (decoded maxDelta 0); the 4
  harness scenes with MOMENTUM_FX off at both viewports and blue-corner at hp
  1 equal the same tree with LOW_HP_OFF (TASK-147: the parent's corridors and
  camera predate TASK-128/133; MOMENTUM_LOW_HP_FX_PARENT set: that revision
  instead), outside the pieces;
- shots/: blue-corner hp 1 at pulse phases 0 and 1/2 and hp 2 (1280x720), hp
  1 at 390x844, compare-hp1.png (vs concept 10-low-hp.png).

MOMENTUM_LOW_HP_FX_EVIDENCE_DIR (default /tmp/momentum-low-hp-fx) receives
the json files (compact) and shots/. MOMENTUM_LOW_HP_FX_PARENT is the parent
revision of the classic/bad frames and, when set, the momentum baselines (default DEFAULT_PARENT d7d96c0: after the slow motion 9174492,
which moved the speed light's cap, the TASK-084 phone boot RNG shift and the
TASK-092 crystal rim edge tiles, the last change of the lit hp 2 frame; the
file's own parent d3ce2fc predates all three). Requires Playwright Chromium. No remote requests.
"""
import colorsys
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
TEST_PATH = 'tools/test_momentum_low_hp_fx.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_LOW_HP_FX_EVIDENCE_DIR', '/tmp/momentum-low-hp-fx'))
VIEWPORT = (1280, 720)
PHONE = (390, 844)
SCENE = 'blue-corner'
HEART = '#ff4f8b'
NEAR_PX = 80
HUE_TOL = 25
CORNER_RED = 8
CENTRE_MAX = 2
LIGHT_RING = (40, 200)
PULSE_RATIO = 1.2
PHASES = (0, 0.25, 0.5, 0.75)
NINJA_LIGHT_OFF = [('slow: Object.freeze({radius: 360, alpha: 0.6', 'slow: Object.freeze({radius: 360, alpha: 0'),
                   ('fast: Object.freeze({radius: 820, alpha: 1,', 'fast: Object.freeze({radius: 820, alpha: 0,'),
                   ('hazeAlpha: 0.4', 'hazeAlpha: 0')]
VIGNETTE_OFF = [('lowHpVignette: 0.15', 'lowHpVignette: 0')]
# Last-heart effect forced off: no pulse, haze gain 1, no vignette, the
# light colour the plain halo (lowHp.color still mixes heartStroke)
LOW_HP_OFF = [('lowHpPulse: 0.35', 'lowHpPulse: 0'), ('lowHpHaze: 2.5', 'lowHpHaze: 1'),
              ("lowHpLightColor: '#ff1f3a'", "lowHpLightColor: '#22c8ff'")] + VIGNETTE_OFF
DEFAULT_PARENT = 'd7d96c0'
PIN_SPEED = 0.9

# hp set (the next frame takes its blend as is, like a run's first frame),
# the pulse clock shifted so the frame's pulse phase is `phase`
# (0..1 of lowHpPulseMs) plus `periods` whole periods
SET_HP = '''() => { momentumState.hp = %d
    ninja.speedX = GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) * %r; ninja.speedY = 0
    const lowHp = visualEffects.lightmap && visualEffects.lightmap.lowHp
    if (lowHp) {
        const P = STYLE.momentumFx.lowHpPulseMs, now = Math.round(performance.now())
        lowHp.pulseShiftMs = Math.round(%r * P) - now %% P + %d * P
        lowHp.time = -1
    } }'''


def set_hp(hp, phase=0, periods=0):
    return SET_HP % (hp, PIN_SPEED, phase, periods)

# Blend over render time: hp 2 at T0, hp 1 at +150 and +300, hp 2 at +450
BLEND = r'''() => {
    const t0 = __snap.now, rows = []
    for (const [dt, hp] of [[0, 2], [150, 1], [300, 1], [450, 2], [600, 2]]) {
        __snap.now = t0 + dt
        momentumState.hp = hp
        draw()
        rows.push({dtMs: dt, hp: hp, blend: visualEffects.lightmap.lowHp.blend,
                   gain: visualEffects.lightmap.lowHp.gain, color: visualEffects.lightmap.lowHp.color})
    }
    return rows
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_LOW_HP_FX_PARENT'):
        return os.environ['MOMENTUM_LOW_HP_FX_PARENT']
    return subprocess.check_output(['git', 'rev-parse', DEFAULT_PARENT], cwd=ROOT, text=True).strip()


def hp_frame(harness, hp, phase=0, periods=0, viewport=VIEWPORT, fx_on=True):
    return harness.capture(SCENE, viewport, fx_on=fx_on, extra_js=set_hp(hp, phase, periods))


def hue_deg(rgb):
    return colorsys.rgb_to_hsv(*[c / 255 for c in rgb])[0] * 360


def hue_distance(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def distance_from_ninja(frame):
    h, w = frame.shape[:2]
    nx, ny = fx.ninja_screen_pos(frame)
    yy, xx = np.mgrid[0:h, 0:w]
    return np.hypot(xx - nx, yy - ny)


def corner_mask(frame):
    h, w = frame.shape[:2]
    bw, bh = w // 8, h // 8
    mask = np.zeros((h, w), dtype=bool)
    for ys in (slice(0, bh), slice(h - bh, h)):
        for xs in (slice(0, bw), slice(w - bw, w)):
            mask[ys, xs] = True
    return mask & ~fx.hud_mask(frame.info['viewport'], frame.shape)


def centre_box(frame):
    h, w = frame.shape[:2]
    return (slice(h // 2 - h // 20, h // 2 + h // 20), slice(w // 2 - w // 20, w // 2 + w // 20))


class MomentumLowHpFxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        # momentum baseline of tests 2 and 4: None = the same tree with LOW_HP_OFF (TASK-147)
        cls.momentum_parent = os.environ.get('MOMENTUM_LOW_HP_FX_PARENT') or None
        tree = fx.harness()
        cls.light_off = fx.FxHarness('worktree', tree.browser, style_patch=NINJA_LIGHT_OFF)
        cls.vignette_off = fx.FxHarness('worktree', tree.browser, style_patch=VIGNETTE_OFF)
        cls.low_hp_off = fx.FxHarness('worktree', tree.browser, style_patch=LOW_HP_OFF)
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'low-hp.json').write_text(compact(cls.result))
        for h in (cls.low_hp_off, cls.vignette_off, cls.light_off):
            h.close()
        fx.close()

    def test_0_colour_vignette_hud(self):
        tree = fx.harness()
        low = hp_frame(tree, 1)
        hp2 = hp_frame(tree, 2)
        dist = distance_from_ninja(low)
        # Background px of the frame without the ninja light (its light lifts
        # the cave past the emissive threshold of fx.background_mask)
        dark = hp_frame(self.light_off, 1)
        near = fx.background_mask(dark) & (dist <= NEAR_PX) \
            & (dist > 1.5 * low.info['ninjaRadius'])
        mean = [float(v) for v in np.asarray(low)[near].mean(axis=0)]
        mean2 = [float(v) for v in np.asarray(hp2)[near].mean(axis=0)]
        unlit = [float(v) for v in np.asarray(dark)[near].mean(axis=0)]
        # The ninja light's own colour there (lit minus unlit), recorded
        added = [a - b for a, b in zip(mean, unlit)]
        heart_rgb = [int(HEART[i:i + 2], 16) for i in (1, 3, 5)]
        hue, heart_hue = hue_deg(added), hue_deg(heart_rgb)
        corners = corner_mask(low)
        red = (float(np.asarray(low)[corners][:, 0].mean()), float(np.asarray(hp2)[corners][:, 0].mean()))
        cy, cx = centre_box(low)
        centre = fx.max_delta(low[cy, cx], hp2[cy, cx])
        no_vignette = hp_frame(self.vignette_off, 1)
        hud = fx.hud_mask(VIEWPORT, low.shape)
        hud_delta = int(np.abs(np.asarray(low, np.int16) - np.asarray(no_vignette, np.int16)).max(axis=2)[hud].max())
        result = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': tree.rev,
                  'near': {'px': NEAR_PX, 'pixels': int(near.sum()), 'meanRgbHp1': [round(v, 2) for v in mean],
                           'meanRgbHp2': [round(v, 2) for v in mean2], 'meanRgbUnlit': [round(v, 2) for v in unlit],
                           'lightRgbHp1': [round(v, 2) for v in added], 'lightHueHp1': round(hue, 2),
                           'pixelHueHp1': round(hue_deg(mean), 2), 'pixelHueHp2': round(hue_deg(mean2), 2),
                           'heartHue': round(heart_hue, 2),
                           'hueDistance': round(hue_distance(hue_deg(mean), heart_hue), 2),
                           'lightHueDistance': round(hue_distance(hue, heart_hue), 2), 'tolerance': HUE_TOL},
                  'corners': {'pixels': int(corners.sum()), 'meanRedHp1': round(red[0], 3),
                              'meanRedHp2': round(red[1], 3), 'redGain': round(red[0] - red[1], 3),
                              'min': CORNER_RED},
                  'centre': {'box': [cx.start, cy.start, cx.stop, cy.stop], 'maxDeltaVsHp2': centre, 'max': CENTRE_MAX},
                  'hud': {'boxes': len(low.info['hud']), 'pixels': int(hud.sum()),
                          'maxDeltaVsNoVignette': hud_delta,
                          'frameMaxDeltaVsNoVignette': fx.max_delta(low, no_vignette)}}
        print('low-hp', result)
        self.result['colour'] = result
        self.assertGreater(near.sum(), 500)
        self.assertLessEqual(result['near']['hueDistance'], HUE_TOL)
        self.assertGreaterEqual(result['corners']['redGain'], CORNER_RED)
        self.assertLessEqual(centre, CENTRE_MAX)
        self.assertGreater(len(low.info['hud']), 3)
        self.assertEqual(hud_delta, 0)
        self.assertGreater(result['hud']['frameMaxDeltaVsNoVignette'], 0)

    def test_1_pulse(self):
        tree = fx.harness()
        dark = hp_frame(self.light_off, 1)
        dist = distance_from_ninja(dark)
        rows = []
        for phase in PHASES:
            frame = hp_frame(tree, 1, phase)
            later = hp_frame(tree, 1, phase, periods=1)
            ring = fx.background_mask(dark) \
                & (dist >= LIGHT_RING[0]) & (dist <= LIGHT_RING[1])
            light = fx.luminance(frame)[ring].mean() - fx.luminance(dark)[ring].mean()
            rows.append({'phase': phase, 'ringPixels': int(ring.sum()), 'light': round(float(light), 6),
                         'onePeriodLaterMaxDelta': fx.max_delta(frame, later)})
            print('pulse', rows[-1])
        lights = [r['light'] for r in rows]
        result = {'periodMs': 1000, 'ring': list(LIGHT_RING), 'rows': rows,
                  'maxOverMin': round(max(lights) / min(lights), 4), 'min': PULSE_RATIO}
        self.result['pulse'] = result
        self.assertGreater(min(lights), 0)
        self.assertGreaterEqual(result['maxOverMin'], PULSE_RATIO)
        for row in rows:
            self.assertEqual(row['onePeriodLaterMaxDelta'], 0)

    def test_2_higher_hp_equals_parent(self):
        rows = []
        pairs = []
        for hp in (2, 5):
            new = hp_frame(fx.harness(), hp)
            off = hp_frame(self.low_hp_off, hp)
            # the same tree with LOW_HP_OFF (TASK-147); MOMENTUM_LOW_HP_FX_PARENT set: that revision
            # (its own pulse hook is irrelevant at hp >= 2, gain 1)
            base = fx.switch_off_harness(LOW_HP_OFF, self.momentum_parent)
            old = hp_frame(base, hp)
            # TASK-122 crystal pieces: the blue-corner scene equals the baseline outside the blue pieces
            d, d_off = fx.assert_equal_outside_pieces(new, old, check=False), fx.max_delta(new, off)
            pairs.append((new, old))
            rows.append({'hp': hp, 'baseline': self.momentum_parent and base.rev or 'LOW_HP_OFF', **d,
                         'identical': d['differingPixels'] == 0, 'maxDeltaVsLowHpOff': d_off})
        # the forced-off tree does change hp 1 (else the check proves nothing)
        hp1_off = fx.max_delta(hp_frame(fx.harness(), 1), hp_frame(self.low_hp_off, 1))
        print('higher hp', rows, 'hp1 vs low-hp off', hp1_off)
        self.result['higherHp'] = {'rows': rows, 'lowHpOff': LOW_HP_OFF, 'hp1MaxDeltaVsLowHpOff': hp1_off}
        self.assertGreater(hp1_off, 0)
        for row, pair in zip(rows, pairs):
            fx.assert_equal_outside_pieces(*pair)
            self.assertEqual(row['maxDeltaVsLowHpOff'], 0)

    def test_3_blend(self):
        context, page = fx.harness().open(VIEWPORT)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            rows = page.evaluate(BLEND)
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        print('blend', rows)
        self.result['blend'] = {'blendMs': 300, 'rows': rows}
        self.assertEqual([round(r['blend'], 6) for r in rows], [0, 0.5, 1, 0.5, 0])
        self.assertEqual(rows[2]['color'], HEART)

    def test_4_switch_off_and_other_modes_equal_parent(self):
        rows = []
        pairs = {}
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                new = fx.capture(scene, viewport, fx_on=False)
                base = fx.switch_off_baseline(scene, viewport, LOW_HP_OFF, self.momentum_parent)
                self.assertFalse(new.info['fx'])
                name = f'momentum-{scene}-{viewport[0]}x{viewport[1]}'
                pairs[name] = (new, base)
                d = fx.assert_equal_outside_pieces(new, base, check=False)
                rows.append({'scene': name, 'fx': 'off', **d, 'identical': d['differingPixels'] == 0})
        # The switch off at the last heart too
        new = hp_frame(fx.harness(), 1, fx_on=False)
        base = hp_frame(fx.switch_off_harness(LOW_HP_OFF, self.momentum_parent), 1, fx_on=False)
        name = f'momentum-{SCENE}-hp1-1280x720'
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
            'momentumBaseline': self.momentum_parent or {'tree': tree.rev, 'stylePatch': LOW_HP_OFF},
            'allIdentical': all(r['identical'] for r in rows), 'frames': rows}))
        self.assertEqual(len(rows), 17)
        for row in rows:
            with self.subTest(scene=row['scene']):
                if row['scene'] in pairs:
                    # TASK-122 crystal pieces: momentum scenes equal outside the blue pieces
                    fx.assert_equal_outside_pieces(*pairs[row['scene']])
                else:
                    self.assertEqual(row['maxDelta'], 0)

    def test_5_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        tree = fx.harness()
        low = hp_frame(tree, 1, 0)
        fx.save_png(low, shots / '1280x720-blue-corner-hp1-phase0.png')
        fx.save_png(hp_frame(tree, 1, 0.5), shots / '1280x720-blue-corner-hp1-phase50.png')
        fx.save_png(hp_frame(tree, 2), shots / '1280x720-blue-corner-hp2.png')
        fx.save_png(hp_frame(tree, 1, 0, viewport=PHONE), shots / '390x844-blue-corner-hp1.png')
        fx.compare_png(low, fx.CONCEPT_DIR / '10-low-hp.png', shots / 'compare-hp1.png',
                       labels=('new frame, hp 1, pulse phase 0', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
