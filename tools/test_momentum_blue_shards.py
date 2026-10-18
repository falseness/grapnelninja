"""Momentum lighting 11/17: a used blue breaks into shards (TASK-061),
retired by TASK-076.

TASK-061 drew a used blue's fading outline as shards. TASK-076 makes a
touched blue vanish at once (no fade, no shards; its outline pop and the
death ring are checked by tools/test_momentum_blue.py), so the shard checks
are retired. What is left (the blue-hit harness scene with its green moved
clear of the blue, both used at the same time, fade progress f of
GAMEPLAY.momentumFadeMs, 1280x720):
- shards.json: at f 0, 0.25, 0.5, 1: the used blue has no shards
  (blue.shards undefined) and alpha 0, and the frame equals the same frame
  with the blue taken off its floor (maxDelta 0: nothing of it is drawn, lit
  or occluding); a second run gives maxDelta 0 (deterministic); the used
  green still fades (alpha 1 - f);
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the
  switch on equal the parent commit (decoded maxDelta 0). (The TASK-061
  usedBlueSwitchOff frames are retired: a used blue no longer fades with
  either switch.)

MOMENTUM_BLUE_SHARDS_EVIDENCE_DIR (default /tmp/momentum-blue-shards) receives
the json files (compact). MOMENTUM_BLUE_SHARDS_PARENT is the parent
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

# blue-hit with the green 225 px left of its place (clear of the blue)
SPEC = copy.deepcopy(fx.SCENE_SPECS['blue-hit'])
SPEC['pieces'][1]['x'] = -150

# Both pieces used at fade progress f (same start); drop: the blue taken off
# its floor afterwards (reference frame)
USE = r'''([f, drop]) => {
    const floor = floors.find(e => e instanceof MomentumPatternFloor)
    const els = floor.elements
    const start = __snap.now - f * GAMEPLAY.momentumFadeMs
    for (const e of els) {
        if (!e.passThrough) e.use()
        e.fadeStartMs = start
    }
    const blue = els.find(e => e instanceof MomentumBlue)
    const green = els.find(e => !(e instanceof MomentumBlue))
    if (drop)
        floor.elements = els.filter(e => e !== blue)
    return {alpha: blue.getAlpha(), faded: blue.faded, shards: blue.shards === undefined ? null : 'present',
            greenAlpha: green.getAlpha()}
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


def fade_frame(harness, f, drop=False, fx_on=True):
    """The scene with both pieces f through their fade, as a Frame."""
    context, page = harness.open(VIEWPORT)
    try:
        page.evaluate(fx.BUILD, [SPEC, fx_on])
        state = page.evaluate(USE, [f, drop])
        info = page.evaluate(fx.DRAW)
        png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        if page.errors:
            raise RuntimeError(f'page errors: {page.errors}')
    finally:
        context.close()
    info.update(scene='blue-shards', viewport=list(VIEWPORT), rev=harness.rev, use=state)
    fx._HUD_BOXES[VIEWPORT] = (info['canvas'], info['hud'])
    return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info)


class MomentumBlueShardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'shards.json').write_text(compact(cls.result))
        fx.close()

    def test_0_used_blue_draws_nothing(self):
        rows = []
        for f in FRACTIONS:
            on = fade_frame(fx.harness(), f)
            again = fade_frame(fx.harness(), f)
            dropped = fade_frame(fx.harness(), f, drop=True)
            use = on.info['use']
            rows.append({'fraction': f, 'fadeMs': round(f * 800), 'alpha': use['alpha'], 'faded': use['faded'],
                         'shards': use['shards'], 'greenAlpha': use['greenAlpha'],
                         'maxDeltaVsBlueOffFloor': fx.max_delta(on, dropped),
                         'rerunMaxDelta': fx.max_delta(on, again)})
            print('used blue', rows[-1])
        self.result.update({'scene': 'blue-hit (green at x -150)', 'viewport': list(VIEWPORT),
                            'tree': fx.harness().rev, 'rows': rows})
        for r in rows:
            with self.subTest(fraction=r['fraction']):
                self.assertEqual((r['alpha'], r['faded'], r['shards']), (0, True, None))
                self.assertEqual(r['maxDeltaVsBlueOffFloor'], 0)
                self.assertEqual(r['rerunMaxDelta'], 0)
                self.assertAlmostEqual(r['greenAlpha'], max(0, 1 - r['fraction']), delta=1e-9)

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

if __name__ == '__main__':
    unittest.main()
