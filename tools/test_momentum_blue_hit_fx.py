"""Momentum lighting 10/17: blue-hit flash and shockwave ring (TASK-060).

A blue touch (MomentumBlue.onNinjaPass) calls
ScreenEffects.triggerBlueHit: for STYLE.momentumFx.blueHitMs of render clock
the blue's light and haze are multiplied by 1 + (flashGain - 1)(1 - t)^2 and
an elliptical blueStroke ring (plus an echo) grows from the blue's centre,
ringFrom -> ringTo times its circumscribed radius, fading out. MOMENTUM_FX
only; nothing of the game reads it. Checks (tools/momentum_fx_support.py
blue-hit scene, 1280x720; the touch is scripted as blue.onNinjaPass(ninja) at
the frozen clock's T0, then one draw() at T0 + dt):
- blue-hit-fx.json: at dt 0, 100, 250, 450 ms: ringRadiusPx (the hook
  ScreenEffects.getBlueRingRadius, canvas px) and measuredRingPx (widest
  |dx| from the blue's centre of the ring pixels) strictly increasing over
  0/100/250; ringPixels = pixels whose max channel differs by >= RING_DELTA
  from the same frame served with ringAlpha 0 (both flashGain 1): > 0 at 100
  and 250; fxPixels = pixels differing at all from the same frame with
  flashGain 1 and ringAlpha 0: 0 at 450. Flash: at dt 50 the blue's light
  (mean luminance over the frame with blueAlpha 0 / blueHazeAlpha 0, ring
  off everywhere) in the background px (of the unlit frames) BAND_PX +-
  BAND_HALF from the blue's outline is >= FLASH_RATIO x the steady light of the same frame with
  flashGain 1 (also reported against the untouched blue);
- physics-identical.json: 600 frozen ticks (10 s) of a momentum run with two
  tall blues across the corridor ahead of the ninja, MOMENTUM_FX on and off:
  per physics cycle ninja x/y/speedX/speedY, hp and score identical, 2 blue
  touches;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: the blue-hit scene at dt 0, 100, 250, 450 (1280x720) and
  compare-100ms.png (vs concept 8-blue-hit-fx.png).

MOMENTUM_BLUE_HIT_FX_EVIDENCE_DIR (default /tmp/momentum-blue-hit-fx)
receives the json files (compact) and shots/. MOMENTUM_BLUE_HIT_FX_PARENT is
the parent revision (default: the parent of the commit that added this file,
or HEAD while uncommitted). Requires Playwright Chromium. No remote requests.
"""
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
import render_snapshot
from test_momentum_ninja_light import gallery_frames

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_blue_hit_fx.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_HIT_FX_EVIDENCE_DIR', '/tmp/momentum-blue-hit-fx'))
VIEWPORT = (1280, 720)
SCENE = 'blue-hit'
TIMES = (0, 100, 250, 450)
FLASH_MS = 50
RING_DELTA = 6
BAND_PX = 40
BAND_HALF = 4
FLASH_RATIO = 1.3
TICKS = 600
RING_OFF = [('ringAlpha: 0.9', 'ringAlpha: 0')]
FLASH_OFF = [('flashGain: 2.5', 'flashGain: 1')]
BLUE_LIGHT_OFF = RING_OFF + [('blueAlpha: 0.9', 'blueAlpha: 0'), ('blueHazeAlpha: 0.25', 'blueHazeAlpha: 0')]

# The scene's blue touched (touch true) at T0, then one draw at T0 + dt;
# returns the ring radius (canvas px) and the blue's centre
HIT = r'''([touch, dt]) => {
    const blue = floors.find(f => f instanceof MomentumPatternFloor).elements.find(e => e instanceof MomentumBlue)
    const t0 = __snap.now
    if (touch)
        blue.onNinjaPass(ninja)
    __snap.now = t0 + dt
    const k = canvas.width / width * scale[version]
    const effects = visualEffects.screenEffects
    const hit = effects.blueHits.find(h => h.element === blue)
    const t = hit ? effects.getBlueHitProgress(hit, __snap.now) : -1
    return {touched: !!hit, hp: momentumState.hp, t: t,
            ringRadiusPx: t < 0 ? 0 : effects.getBlueRingRadius(blue, t) * k,
            flash: effects.getBlueFlash(blue, __snap.now),
            centre: [(blue.x + blue.circle.x + screen.x) * k, (blue.y + blue.circle.y + screen.y) * k]}
}'''

# A momentum run: pieces cleared, two tall blues across the corridor ahead
# of the ninja, the ninja sent right; every ninja.move() recorded
RUN = r'''([fxOn, ticks]) => {
    MOMENTUM_FX.enabled = fxOn
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor) {
            f.elements = []
            if (f.groups) f.groups = []
        }
    const r = ninja.radius
    for (const dx of [12, 40])
        momentumPlacePiece('blue', {shape: 'rect', x: ninja.x + dx * r, y: ninja.y, w: 3 * r, h: 80 * r})
    ninja.speedX = GAMEPLAY.momentumMaxSpeed * 0.8; ninja.speedY = 0
    let touches = 0
    const onBlueTouch = momentumState.onBlueTouch
    momentumState.onBlueTouch = function() { ++touches; return onBlueTouch.apply(this, arguments) }
    const rows = []
    const move = ninja.move
    ninja.move = function() {
        const out = move.apply(this, arguments)
        rows.push([this.x, this.y, this.speedX, this.speedY, momentumState.hp, scoreText.count[version]])
        return out
    }
    for (let i = 0; i < ticks; ++i)
        __snap.step()
    return {rows: rows, touches: touches, tick: __snap.tick, hits: visualEffects.screenEffects.blueHits.length}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_BLUE_HIT_FX_PARENT'):
        return os.environ['MOMENTUM_BLUE_HIT_FX_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def hit_frame(harness, dt, touch=True, keep_trail=True):
    """The blue-hit scene drawn dt ms after the scripted touch, as a Frame."""
    context, page = harness.open(VIEWPORT)
    try:
        page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
        if not keep_trail:
            page.evaluate('() => { ninja.track.pos = [] }')
        state = page.evaluate(HIT, [touch, dt])
        info = page.evaluate(fx.DRAW)
        png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        if page.errors:
            raise RuntimeError(f'page errors: {page.errors}')
    finally:
        context.close()
    info.update(scene=SCENE, viewport=list(VIEWPORT), rev=harness.rev, hit=state)
    fx._HUD_BOXES[VIEWPORT] = (info['canvas'], info['hud'])
    return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info)


def diff_mask(a, b, delta=1):
    return np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) >= delta


def blue_band(frame):
    """Background px BAND_PX +- BAND_HALF from the blue's outline (its box)."""
    blue = next(p for p in frame.info['pieces'] if p['kind'] == 'blue')
    x0, y0, x1, y1 = blue['bbox']
    h, w = frame.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(np.maximum(0, np.maximum(x0 - xx, xx - x1)), np.maximum(0, np.maximum(y0 - yy, yy - y1)))
    return fx.background_mask(frame) & (np.abs(dist - BAND_PX) <= BAND_HALF)


class MomentumBlueHitFxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        tree = fx.harness()
        cls.ring_off = fx.FxHarness('worktree', tree.browser, style_patch=RING_OFF)
        cls.flash_off = fx.FxHarness('worktree', tree.browser, style_patch=FLASH_OFF)
        cls.no_fx = fx.FxHarness('worktree', tree.browser, style_patch=FLASH_OFF + RING_OFF)
        cls.light_off = fx.FxHarness('worktree', tree.browser, style_patch=BLUE_LIGHT_OFF)
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'blue-hit-fx.json').write_text(compact(cls.result))
        for h in (cls.light_off, cls.no_fx, cls.flash_off, cls.ring_off):
            h.close()
        fx.close()

    def test_0_ring_grows_and_ends(self):
        rows = []
        for dt in TIMES:
            on = hit_frame(fx.harness(), dt)
            ring_only = hit_frame(self.flash_off, dt)
            plain = hit_frame(self.no_fx, dt)
            self.assertTrue(on.info['hit']['touched'])
            ring = diff_mask(ring_only, plain, RING_DELTA)
            cx, cy = on.info['hit']['centre']
            ys, xs = np.nonzero(ring)
            rows.append({'dtMs': dt, 'hp': on.info['hit']['hp'], 't': round(on.info['hit']['t'], 4),
                         'ringRadiusPx': round(on.info['hit']['ringRadiusPx'], 2),
                         'measuredRingPx': round(float(np.abs(xs - cx).max()), 1) if len(xs) else 0,
                         'flash': round(on.info['hit']['flash'], 4),
                         'ringPixels': int(ring.sum()), 'fxPixels': int(diff_mask(on, plain).sum()),
                         'fxMaxDelta': fx.max_delta(on, plain)})
            print('ring', rows[-1])
        by = {r['dtMs']: r for r in rows}
        radii = [by[dt]['ringRadiusPx'] for dt in (0, 100, 250)]
        measured = [by[dt]['measuredRingPx'] for dt in (0, 100, 250)]
        self.result['ring'] = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev,
                               'ringDelta': RING_DELTA, 'rows': rows,
                               'radiusIncreasing': all(a < b for a, b in zip(radii, radii[1:])),
                               'measuredIncreasing': all(a < b for a, b in zip(measured, measured[1:])),
                               'fxPixelsAt450': by[450]['fxPixels']}
        self.assertTrue(self.result['ring']['radiusIncreasing'])
        self.assertTrue(self.result['ring']['measuredIncreasing'])
        self.assertGreater(by[100]['ringPixels'], 0)
        self.assertGreater(by[250]['ringPixels'], 0)
        self.assertEqual(by[450]['fxPixels'], 0)

    def test_1_flash(self):
        flash = hit_frame(self.ring_off, FLASH_MS)
        steady = hit_frame(self.no_fx, FLASH_MS)
        dark = hit_frame(self.light_off, FLASH_MS)
        before = hit_frame(self.ring_off, FLASH_MS, touch=False)
        dark_before = hit_frame(self.light_off, FLASH_MS, touch=False)
        # Background in the frames without the blue's light (the lit ones pass
        # the emissive threshold round the blue)
        band = blue_band(dark) & blue_band(dark_before)
        lum = {name: fx.luminance(f)[band].mean() for name, f in
               [('flash', flash), ('steady', steady), ('dark', dark), ('before', before), ('darkBefore', dark_before)]}
        light = lum['flash'] - lum['dark']
        steady_light = lum['steady'] - lum['dark']
        untouched_light = lum['before'] - lum['darkBefore']
        result = {'dtMs': FLASH_MS, 'bandPx': BAND_PX, 'bandHalf': BAND_HALF, 'bandPixels': int(band.sum()),
                  'flashFactor': round(flash.info['hit']['flash'], 4),
                  'luminance': {k: round(float(v), 5) for k, v in lum.items()},
                  'flashLight': round(float(light), 5), 'steadyLight': round(float(steady_light), 5),
                  'untouchedLight': round(float(untouched_light), 5),
                  'ratio': round(float(light / steady_light), 4),
                  'ratioVsUntouched': round(float(light / untouched_light), 4),
                  'totalLuminanceRatio': round(float(lum['flash'] / lum['steady']), 4)}
        result['pass'] = result['ratio'] >= FLASH_RATIO
        self.result['flash'] = result
        print('flash', result)
        self.assertGreater(band.sum(), 100)
        self.assertGreater(steady_light, 0)
        self.assertGreaterEqual(result['ratio'], FLASH_RATIO)

    def test_2_physics_identical(self):
        runs = {}
        for on in (True, False):
            context, page = fx.harness().open(VIEWPORT)
            try:
                runs[on] = page.evaluate(RUN, [on, TICKS])
                self.assertFalse(page.errors, page.errors)
            finally:
                context.close()
        a, b = runs[True], runs[False]
        first = next((i for i, (x, y) in enumerate(zip(a['rows'], b['rows'])) if x != y), None)
        result = {'ticks': TICKS, 'seconds': TICKS / 60, 'cycles': [len(a['rows']), len(b['rows'])],
                  'blueTouches': [a['touches'], b['touches']], 'hitsRecorded': [a['hits'], b['hits']],
                  'fields': ['x', 'y', 'speedX', 'speedY', 'hp', 'score'],
                  'final': [a['rows'][-1], b['rows'][-1]], 'firstDifference': first,
                  'identical': a['rows'] == b['rows']}
        print('physics', {k: v for k, v in result.items() if k != 'final'})
        (EVIDENCE_DIR / 'physics-identical.json').write_text(compact(result))
        self.assertEqual(a['touches'], 2)
        self.assertTrue(result['identical'])

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
        for dt in TIMES:
            frame = hit_frame(fx.harness(), dt)
            fx.save_png(frame, shots / f'1280x720-blue-hit-{dt}ms.png')
            if dt == 100:
                fx.compare_png(frame, fx.CONCEPT_DIR / '8-blue-hit-fx.png', shots / 'compare-100ms.png',
                               labels=('new frame 100 ms after the blue touch', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
