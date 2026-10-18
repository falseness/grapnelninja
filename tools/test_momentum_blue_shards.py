"""Momentum lighting 11/17: a used blue breaks into shards (TASK-061).

MomentumOneTime.use() lays out STYLE.momentumFx.shardCount shards of a blue
(MomentumBlue.hasShards) from its own geometry (hash of its points and
position, no Math.random); while it fades, its glow pass draws them instead
of the plain fading outline: neon triangles starting on the outline, drifting
outward with a slight fall and spinning, alpha = getAlpha(). MOMENTUM_FX only;
greens keep their fade. Checks (the blue-hit harness scene with its green
moved clear of the blue, both used at the same time, fade progress f of
GAMEPLAY.momentumFadeMs, 1280x720):
- shards.json: at f 0, 0.25, 0.5, 1: shardPixels = pixels whose max channel
  differs by >= SHARD_DELTA from the same frame served with shardCount 0:
  > 0 at 0.25 and 0.5, 0 at 1; meanDistancePx of those pixels from the
  blue's centre strictly increasing over 0 / 0.25 / 0.5; a second run of
  every frame gives maxDelta 0 (deterministic); the green's mask (its
  polygon dilated by GREEN_PAD px) has maxDelta 0 against the parent commit
  at every f;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports (plus usedBlueSwitchOff: this scene at f 0.25 / 0.5 switch off) and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: the blue touched (hit ring started with its fade) at 0, 25, 50 and
  100 % of the fade (1280x720) and compare-25.png (vs concept
  8-blue-hit-fx.png).

MOMENTUM_BLUE_SHARDS_EVIDENCE_DIR (default /tmp/momentum-blue-shards) receives
the json files (compact) and shots/. MOMENTUM_BLUE_SHARDS_PARENT is the parent
revision (default: the parent of the commit that added this file, or HEAD
while uncommitted). Requires Playwright Chromium. No remote requests.
"""
import copy
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
TEST_PATH = 'tools/test_momentum_blue_shards.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_SHARDS_EVIDENCE_DIR', '/tmp/momentum-blue-shards'))
VIEWPORT = (1280, 720)
FRACTIONS = (0, 0.25, 0.5, 1)
SHARD_DELTA = 6
GREEN_PAD = 12
SHARDS_OFF = [('shardCount: 12', 'shardCount: 0')]

# blue-hit with the green 225 px left of its place (clear of the shards)
SPEC = copy.deepcopy(fx.SCENE_SPECS['blue-hit'])
SPEC['pieces'][1]['x'] = -150

# Both pieces used at fade progress f (same start); hit: the blue's hit ring
# started with its fade (as a touch does)
USE = r'''([f, hit]) => {
    const els = floors.find(e => e instanceof MomentumPatternFloor).elements
    const start = __snap.now - f * GAMEPLAY.momentumFadeMs
    for (const e of els) {
        if (!e.passThrough) e.use()
        e.fadeStartMs = start
    }
    const blue = els.find(e => e instanceof MomentumBlue)
    if (hit) {
        visualEffects.screenEffects.triggerBlueHit(blue)
        visualEffects.screenEffects.blueHits[visualEffects.screenEffects.blueHits.length - 1].start = start
    }
    return {alpha: blue.getAlpha(), shards: blue.shards ? blue.shards.length : 0,
            greenShards: els.filter(e => !(e instanceof MomentumBlue)).map(e => e.shards)}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_BLUE_SHARDS_PARENT'):
        return os.environ['MOMENTUM_BLUE_SHARDS_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def fade_frame(harness, f, hit=False, fx_on=True):
    """The scene with both pieces f through their fade, as a Frame."""
    context, page = harness.open(VIEWPORT)
    try:
        page.evaluate(fx.BUILD, [SPEC, fx_on])
        state = page.evaluate(USE, [f, hit])
        info = page.evaluate(fx.DRAW)
        png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        if page.errors:
            raise RuntimeError(f'page errors: {page.errors}')
    finally:
        context.close()
    info.update(scene='blue-shards', viewport=list(VIEWPORT), rev=harness.rev, use=state)
    fx._HUD_BOXES[VIEWPORT] = (info['canvas'], info['hud'])
    return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info)


def diff_mask(a, b, delta=1):
    return np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) >= delta


def piece(frame, kind):
    return next(p for p in frame.info['pieces'] if p['kind'] == kind)


def green_mask(frame):
    x0, y0, x1, y1 = piece(frame, 'green')['bbox']
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), dtype=bool)
    mask[max(0, int(y0) - GREEN_PAD):int(np.ceil(y1)) + GREEN_PAD + 1,
         max(0, int(x0) - GREEN_PAD):int(np.ceil(x1)) + GREEN_PAD + 1] = True
    return mask


class MomentumBlueShardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        tree = fx.harness()
        cls.shards_off = fx.FxHarness('worktree', tree.browser, style_patch=SHARDS_OFF)
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'shards.json').write_text(compact(cls.result))
        cls.shards_off.close()
        fx.close()

    def test_0_shards_spread_and_end(self):
        rows = []
        parent = fx.harness(self.parent)
        for f in FRACTIONS:
            on = fade_frame(fx.harness(), f)
            again = fade_frame(fx.harness(), f)
            off = fade_frame(self.shards_off, f)
            old = fade_frame(parent, f)
            self.assertEqual(on.info['use']['shards'], 12)
            self.assertEqual(on.info['use']['greenShards'], [None])
            mask = diff_mask(on, off, SHARD_DELTA)
            blue = np.asarray(piece(on, 'blue')['poly'])
            cx, cy = blue.mean(axis=0)
            ys, xs = np.nonzero(mask)
            green = green_mask(on)
            rows.append({'fraction': f, 'fadeMs': round(f * 800), 'alpha': on.info['use']['alpha'],
                         'shardPixels': int(mask.sum()),
                         'meanDistancePx': round(float(np.hypot(xs - cx, ys - cy).mean()), 2) if len(xs) else 0,
                         'maxDistancePx': round(float(np.hypot(xs - cx, ys - cy).max()), 2) if len(xs) else 0,
                         'rerunMaxDelta': fx.max_delta(on, again),
                         'greenMaskPixels': int(green.sum()),
                         'greenMaxDeltaVsParent': fx.max_delta(on[green], old[green]),
                         'greenShardOverlap': int((mask & green).sum())})
            print('shards', rows[-1])
        by = {r['fraction']: r for r in rows}
        dists = [by[f]['meanDistancePx'] for f in (0, 0.25, 0.5)]
        self.result.update({'scene': 'blue-hit (green at x -150)', 'viewport': list(VIEWPORT),
                            'tree': fx.harness().rev, 'parent': parent.rev, 'shardDelta': SHARD_DELTA,
                            'greenPad': GREEN_PAD, 'rows': rows,
                            'distanceIncreasing': all(a < b for a, b in zip(dists, dists[1:])),
                            'deterministic': all(r['rerunMaxDelta'] == 0 for r in rows),
                            'greenIdentical': all(r['greenMaxDeltaVsParent'] == 0 for r in rows)})
        self.assertGreater(by[0.25]['shardPixels'], 0)
        self.assertGreater(by[0.5]['shardPixels'], 0)
        self.assertEqual(by[1]['shardPixels'], 0)
        self.assertTrue(self.result['distanceIncreasing'])
        self.assertTrue(self.result['deterministic'])
        self.assertTrue(self.result['greenIdentical'])

    def test_1_switch_off_and_other_modes_equal_parent(self):
        rows = []
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                new = fx.capture(scene, viewport, fx_on=False)
                base = fx.capture(scene, viewport, fx_on=False, rev=self.parent)
                self.assertFalse(new.info['fx'])
                d = fx.max_delta(new, base)
                rows.append({'scene': f'momentum-{scene}-{viewport[0]}x{viewport[1]}', 'fx': 'off',
                             'maxDelta': d, 'identical': d == 0})
        # The used blue itself with the switch off: the parent's fading outline
        used = []
        for f in (0.25, 0.5):
            d = fx.max_delta(fade_frame(fx.harness(), f, fx_on=False), fade_frame(fx.harness(self.parent), f, fx_on=False))
            used.append({'scene': f'blue-shards-{round(f * 100)}pct-1280x720', 'fx': 'off', 'maxDelta': d,
                         'identical': d == 0})
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
            'allIdentical': all(r['identical'] for r in rows), 'frames': rows, 'usedBlueSwitchOff': used}))
        self.assertEqual(len(rows), 16)
        for row in rows + used:
            with self.subTest(scene=row['scene']):
                self.assertEqual(row['maxDelta'], 0)

    def test_2_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        for f in FRACTIONS:
            frame = fade_frame(fx.harness(), f, hit=True)
            pct = round(f * 100)
            fx.save_png(frame, shots / f'1280x720-blue-shards-{pct}pct.png')
            if pct == 25:
                fx.compare_png(frame, fx.CONCEPT_DIR / '8-blue-hit-fx.png', shots / 'compare-25.png',
                               labels=('new frame 25% through the used blue fade', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
