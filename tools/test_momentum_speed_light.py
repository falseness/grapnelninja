"""Momentum lighting 9/17: speed-driven ninja light and speed streaks (TASK-059).

With MOMENTUM_FX on, LightmapRenderer.updateSpeedLight eases s toward
|ninja speed| / GAMEPLAY.momentumMaxSpeed over momentumLight.speedSmoothMs of
render clock; the ninja light's radius and alpha go from momentumLight.slow to
.fast with s (its haze radius with it), the trail lights' alpha times
trailGain. From s >= streakFrom drawSpeedStreaks draws 3-6 thin lines behind
the ninja against its velocity, placed from the render clock (no
Math.random). Checks (tools/momentum_fx_support.py run-right scene, 1280x720,
empty trail so the trail lights do not mix in; s set through the ninja's speed
along +x, then SETTLE_FRAMES draws 1/60 s apart):
- speed-light.json: lit radius = the first ring (RING_PX wide, past 2 ninja
  radii, >= MIN_RING_PIXELS background px of both frames) where the mean
  background luminance over the same frame with the ninja light and haze at
  alpha 0 (style.js served with slow/fast alpha 0 and hazeAlpha 0; both frames
  streakAlpha 0) drops below 1.10, at s 0.2, 0.6, 1.0: radius(1.0) >=
  1.7 x radius(0.2), monotonic. streakPixels = pixels behind the ninja (box
  BEHIND_PX long, +-BEHIND_HALF tall, against the velocity) whose max channel
  differs by >= STREAK_DELTA from the same frame with streakAlpha 0: 0 at s 0.2
  and 0.5, > 0 at 0.7 and 1.0; none outside that box (streakOutside 0);
- smoothing.json: settled at s 0.2, the speed steps to 1.0 and STEP_FRAMES
  frames follow at 60 fps: the lit radius grows over >= 3 frames, no single
  frame jump > 50% of the settled change radius(1.0) - radius(0.2);
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: run-right (its trail kept) at s 0.2 and 1.0 at 1280x720, s 1.0 at
  390x844, compare-slow.png / compare-fast.png (vs concepts 5-rim-slow.png and
  6-rim-fast.png).

MOMENTUM_SPEED_LIGHT_EVIDENCE_DIR (default /tmp/momentum-speed-light)
receives the json files (compact) and shots/. MOMENTUM_SPEED_LIGHT_PARENT is
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
TEST_PATH = 'tools/test_momentum_speed_light.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_SPEED_LIGHT_EVIDENCE_DIR', '/tmp/momentum-speed-light'))
VIEWPORT = (1280, 720)
PHONE = (390, 844)
SCENE = 'run-right'
RADIUS_S = (0.2, 0.6, 1.0)
STREAK_S = (0.2, 0.5, 0.7, 1.0)
SETTLE_FRAMES = 40
STEP_FRAMES = 12
RING_PX = 4
MIN_RING_PIXELS = 30
GAIN = 0.10
MIN_RADIUS_RATIO = 1.7
MAX_STEP_SHARE = 0.5
BEHIND_PX = 320
BEHIND_HALF = 90
STREAK_DELTA = 6
STREAKS_OFF = [('streakAlpha: 0.9', 'streakAlpha: 0')]
LIGHT_OFF = STREAKS_OFF + [('alpha: 0.6, trailGain', 'alpha: 0, trailGain'),
                           ('alpha: 1, trailGain', 'alpha: 0, trailGain'),
                           ('hazeAlpha: 0.4', 'hazeAlpha: 0')]
EMPTY_TRAIL = '() => { ninja.track.pos = [] }'
# Sets the ninja's speed to s of the cap along the scene's direction, then
# draws frames 1/60 s apart; returns the speed light state
SETTLE = r'''([s, dir, frames]) => {
    const v = GAMEPLAY.momentumMaxSpeed * s
    ninja.speedX = dir[0] * v; ninja.speedY = dir[1] * v
    for (let i = 0; i < frames; ++i) {
        __snap.now += 1000 / 60
        draw()
    }
    const l = visualEffects.lightmap.speedLight
    return {s: l.s, radius: l.radius, alpha: l.alpha, trailGain: l.trailGain, now: __snap.now}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_SPEED_LIGHT_PARENT'):
        return os.environ['MOMENTUM_SPEED_LIGHT_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def grab(page):
    info = page.evaluate(fx.DRAW)
    png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
    info.update(scene=SCENE)
    return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info)


def frames_at(harness, viewport, steps, empty_trail=True):
    """Frames of SCENE at viewport after each (s, frames) step, with the speed state."""
    context, page = harness.open(viewport)
    spec = fx.SCENE_SPECS[SCENE]
    out = []
    try:
        page.evaluate(fx.BUILD, [spec, True])
        if empty_trail:
            page.evaluate(EMPTY_TRAIL)
        for s, frames, keep in steps:
            state = page.evaluate(SETTLE, [s, spec['speed'], frames])
            if keep:
                frame = grab(page)
                frame.info.update(viewport=list(viewport), rev=harness.rev, speed=state)
                fx._HUD_BOXES[tuple(viewport)] = (frame.info['canvas'], frame.info['hud'])
                out.append(frame)
        if page.errors:
            raise RuntimeError(f'page errors: {page.errors}')
    finally:
        context.close()
    return out


def lit_radius(on, ref):
    """First ring past 2 ninja radii whose background gain drops below GAIN (canvas px)."""
    background = fx.background_mask(on) & fx.background_mask(ref)
    lum_on, lum_ref = fx.luminance(on), fx.luminance(ref)
    nx, ny = on.info['ninja']
    h, w = background.shape
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(xx - nx, yy - ny)
    r = 2 * on.info['ninjaRadius']
    gains = []
    while r < max(w, h):
        ring = background & (dist >= r) & (dist < r + RING_PX)
        if ring.sum() >= MIN_RING_PIXELS:
            gain = float(lum_on[ring].mean() / max(1e-6, lum_ref[ring].mean()) - 1)
            gains.append((r + RING_PX / 2, gain))
            if gain < GAIN:
                return r + RING_PX / 2, gains
        r += RING_PX
    return None, gains


def streak_masks(on, off):
    diff = np.abs(on.astype(np.int16) - off.astype(np.int16)).max(axis=2) >= STREAK_DELTA
    nx, ny = on.info['ninja']
    h, w = diff.shape
    behind = np.zeros((h, w), dtype=bool)
    # Velocity +x: behind is to the left of the ninja
    behind[max(0, int(ny - BEHIND_HALF)):int(ny + BEHIND_HALF), max(0, int(nx - BEHIND_PX)):int(nx)] = True
    return int((diff & behind).sum()), int((diff & ~behind).sum())


class MomentumSpeedLightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        tree = fx.harness()
        cls.streaks_off = fx.FxHarness('worktree', tree.browser, style_patch=STREAKS_OFF)
        cls.light_off = fx.FxHarness('worktree', tree.browser, style_patch=LIGHT_OFF)
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'speed-light.json').write_text(compact(cls.result))
        cls.light_off.close()
        cls.streaks_off.close()
        fx.close()

    def test_0_radius_grows_with_speed(self):
        rows = []
        for s in RADIUS_S:
            on, = frames_at(self.streaks_off, VIEWPORT, [(s, SETTLE_FRAMES, True)])
            ref, = frames_at(self.light_off, VIEWPORT, [(s, SETTLE_FRAMES, True)])
            radius, gains = lit_radius(on, ref)
            rows.append({'s': s, 'settledS': round(on.info['speed']['s'], 4),
                         'lightRadius': round(on.info['speed']['radius'], 1),
                         'lightAlpha': round(on.info['speed']['alpha'], 3), 'litRadiusPx': radius,
                         'gainNearNinja': round(gains[0][1], 3) if gains else None,
                         'gainAtLitRadius': round(gains[-1][1], 4) if gains else None})
            print('radius', rows[-1])
        radii = [row['litRadiusPx'] for row in rows]
        ratio = radii[-1] / radii[0] if None not in radii else None
        self.result['radius'] = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev,
                                 'gainThreshold': GAIN, 'ringPx': RING_PX,
                                 'refOverride': 'slow/fast alpha 0, hazeAlpha 0 (streakAlpha 0 both)',
                                 'rows': rows, 'ratio': round(ratio, 4) if ratio else None,
                                 'monotonic': None not in radii and all(a < b for a, b in zip(radii, radii[1:])),
                                 'pass': bool(ratio and ratio >= MIN_RADIUS_RATIO)}
        self.assertNotIn(None, radii)
        self.assertTrue(self.result['radius']['monotonic'])
        self.assertGreaterEqual(ratio, MIN_RADIUS_RATIO)

    def test_1_streaks_only_when_fast(self):
        rows = []
        for s in STREAK_S:
            on, = frames_at(fx.harness(), VIEWPORT, [(s, SETTLE_FRAMES, True)])
            off, = frames_at(self.streaks_off, VIEWPORT, [(s, SETTLE_FRAMES, True)])
            inside, outside = streak_masks(on, off)
            rows.append({'s': s, 'streakPixels': inside, 'streakOutside': outside})
            print('streaks', rows[-1])
        expect = {s: s >= 0.6 for s in STREAK_S}
        self.result['streaks'] = {'behindPx': BEHIND_PX, 'behindHalf': BEHIND_HALF, 'minDelta': STREAK_DELTA,
                                  'offOverride': 'streakAlpha 0', 'rows': rows,
                                  'pass': all((r['streakPixels'] > 0) == expect[r['s']] and r['streakOutside'] == 0
                                              for r in rows)}
        for row in rows:
            with self.subTest(s=row['s']):
                self.assertEqual(row['streakOutside'], 0)
                if expect[row['s']]:
                    self.assertGreater(row['streakPixels'], 0)
                else:
                    self.assertEqual(row['streakPixels'], 0)

    def test_2_smoothing(self):
        steps = [(0.2, SETTLE_FRAMES, True)] + [(1.0, 1, True)] * STEP_FRAMES + [(1.0, SETTLE_FRAMES, True)]
        on = frames_at(self.streaks_off, VIEWPORT, steps)
        ref = frames_at(self.light_off, VIEWPORT, steps)
        radii = [lit_radius(a, b)[0] for a, b in zip(on, ref)]
        self.assertNotIn(None, radii)
        change = radii[-1] - radii[0]
        jumps = [b - a for a, b in zip(radii[:-1], radii[1:STEP_FRAMES + 1])]
        growing = sum(1 for j in jumps if j > 0)
        rows = [{'frame': i, 's': round(f.info['speed']['s'], 4), 'lightRadius': round(f.info['speed']['radius'], 1),
                 'litRadiusPx': r} for i, (f, r) in enumerate(zip(on, radii))]
        result = {'scene': SCENE, 'viewport': list(VIEWPORT), 'fps': 60, 'from': 0.2, 'to': 1.0,
                  'frames': rows, 'settledChangePx': change, 'jumps': jumps, 'growingFrames': growing,
                  'maxJumpPx': max(jumps), 'maxJumpShare': round(max(jumps) / change, 4),
                  'pass': growing >= 3 and max(jumps) <= MAX_STEP_SHARE * change}
        print('smoothing', result['jumps'], result['maxJumpShare'])
        (EVIDENCE_DIR / 'smoothing.json').write_text(compact(result))
        self.assertGreater(change, 0)
        self.assertGreaterEqual(growing, 3)
        self.assertLessEqual(max(jumps), MAX_STEP_SHARE * change)

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
        tree = fx.harness()
        slow, = frames_at(tree, VIEWPORT, [(0.2, SETTLE_FRAMES, True)], empty_trail=False)
        fast, = frames_at(tree, VIEWPORT, [(1.0, SETTLE_FRAMES, True)], empty_trail=False)
        phone, = frames_at(tree, PHONE, [(1.0, SETTLE_FRAMES, True)], empty_trail=False)
        fx.save_png(slow, shots / '1280x720-run-right-s0.2.png')
        fx.save_png(fast, shots / '1280x720-run-right-s1.0.png')
        fx.save_png(phone, shots / '390x844-run-right-s1.0.png')
        fx.compare_png(slow, fx.CONCEPT_DIR / '5-rim-slow.png', shots / 'compare-slow.png',
                       labels=('new frame s 0.2', 'concept'))
        fx.compare_png(fast, fx.CONCEPT_DIR / '6-rim-fast.png', shots / 'compare-fast.png',
                       labels=('new frame s 1.0', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
