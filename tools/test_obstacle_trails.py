"""Frozen-clock swept-trail regression against the pre-TASK-197 renderer.

Isolate actual obstacle tracks from unrelated cave/lighting changes. Classic
triangle hue is normalised by rendering both strokes with the reference colour;
raw colour captures remain in the comparison sheet. No style/geometry overrides
are applied to the other three crops. Fixed trajectories include a cube bounce.
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot as snap

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('OBSTACLE_EVIDENCE_DIR', ROOT / 'artifacts/TASK-215'))
REFERENCE = '294acb3'
PARENT = '0303aca7cbf9e7c35ba27239362dbc54d09f2ae1'
SCENE = '''([mode, kind, normalise]) => {
    startGame(mode)
    const target = document.createElement('canvas')
    target.width = 320; target.height = 260
    ctx = target.getContext('2d')
    screen.x = screen.y = 0
    trackEnabled = true
    const t = new Triangle({x: 160, y: 60, radius: 24,
        yMin: -1000, yMax: 1000, stroke: '#ff2d95'})
    const c = new CubeTrackLine(32, 32, '#00ccff', 30)
    t.track.pos = []; c.pos = []
    // Identical sampled physics positions; drawing never advances the clock.
    for (let tick = 0; tick < 24; tick++) {
        __snap.now = tick * 1000 / 60
        t.y = 60 + tick * 5
        t.track.addPos(t.getPoints(), true)
        c.addPos(65 + tick * 7, 165 - 0.55 * tick * (23 - tick), true)
    }
    if (t.syncTrackStyle) t.syncTrackStyle()
    const rawStroke = t.track.stroke
    if (normalise && mode === 'classic') t.track.stroke = '#ff2d95'
    const ops = {fill: 0, stroke: 0, lineTo: 0}
    for (const op of Object.keys(ops)) {
        const original = ctx[op].bind(ctx)
        ctx[op] = (...args) => { ops[op]++; return original(...args) }
    }
    const track = kind === 'triangle' ? t.track : c
    track.draw()
    return {png: target.toDataURL(), ops, rawStroke, points: track.pos.length}
}'''


def capture(rev):
    result = {}
    with ExitStack() as stack:
        root, sha = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        page = browser.new_page()
        page.add_init_script(SEED_SCRIPT % snap.SEED)
        page.add_init_script(snap.CLOCK_SCRIPT)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        snap.boot_frozen(page)
        for mode in ('classic', 'bad'):
            for kind in ('triangle', 'cube'):
                for normalise in (False, True):
                    r = page.evaluate(SCENE, [mode, kind, normalise])
                    r['image'] = Image.open(io.BytesIO(snap.png_bytes(r.pop('png')))).convert('RGBA')
                    result[mode, kind, normalise] = r
        assert not errors, errors
    return sha, result


class ObstacleTrailsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.runs = {name: capture(rev) for name, rev in
                    [('reference', REFERENCE), ('parent', PARENT), ('head', 'worktree')]}
        cls.report = {'revs': {k: v[0] for k, v in cls.runs.items()}, 'crops': {}}
        sheet = Image.new('RGB', (960, 4 * 290), '#050910')
        draw = ImageDraw.Draw(sheet)
        for row, (mode, kind) in enumerate((m, k) for m in ('classic', 'bad') for k in ('triangle', 'cube')):
            key = (mode, kind, mode == 'classic' and kind == 'triangle')
            a, b = [cls.runs[n][1][key] for n in ('reference', 'head')]
            # Compare premultiplied channels: transparent RGB is not visible.
            def pixels(r):
                bg = Image.new('RGBA', r['image'].size, '#050910')
                return np.asarray(Image.alpha_composite(bg, r['image']).convert('RGB'), dtype=np.int16)
            delta = int(np.abs(pixels(a) - pixels(b)).max())
            cls.report['crops'][f'{mode}-{kind}'] = {
                'max_channel_delta': delta, 'limit': 8,
                'hue_normalised': key[2], 'reference_ops': a['ops'], 'head_ops': b['ops'],
                'head_stroke': b['rawStroke'], 'points': b['points']}
            for col, name in enumerate(cls.runs):
                r = cls.runs[name][1][mode, kind, False]
                sheet.paste(r['image'], (col * 320, row * 290 + 30), r['image'])
                draw.text((col * 320 + 8, row * 290 + 8), f'{name}: {mode} {kind}', fill='white')
        sheet.save(OUT / 'before-after.png')
        (OUT / 'trails.json').write_text(json.dumps(cls.report, indent=2) + '\n')

    def test_reference_pixels_and_one_frame_ops(self):
        for name, r in self.report['crops'].items():
            with self.subTest(crop=name):
                self.assertLessEqual(r['max_channel_delta'], 8)
                self.assertEqual(r['head_ops'], r['reference_ops'])
                self.assertGreater(r['head_ops']['fill'], 0)
                self.assertGreater(r['head_ops']['lineTo'], 0)
                self.assertGreater(r['points'], 1)
                if name == 'classic-triangle':
                    self.assertEqual(r['head_stroke'], '#8fdcff')
                print(f'PASS {name}: max_channel_delta={r["max_channel_delta"]} <= 8; ops={r["head_ops"]}', flush=True)


if __name__ == '__main__':
    unittest.main()
