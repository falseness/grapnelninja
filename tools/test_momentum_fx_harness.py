"""Momentum lighting FX harness: determinism and scene content (TASK-052).

tools/momentum_fx_support.py builds the 4 reference scenes of the lighting
concept (blue-corner, blue-hit, mid-shaft, run-right) under the frozen
clock. This suite checks:
- determinism: every scene captured twice at 1280x720 and 390x844 (each
  capture a fresh page) gives identical decoded pixels (maxDelta 0);
- content: each scene has what it claims (pieces by kind, the corner /
  corridor walls where the source shot has them, the ninja on its spot,
  the trail), the pieces are drawn (neon of their colour inside their box),
  and backgroundPixels (background_mask) is over 20% of the frame;
- helpers: hud_mask covers the HUD text, emissive_mask / region_luminance /
  compare_png behave; fx_on=False reaches the page and, since the momentum
  lighting (TASK-053), differs from fx_on=True;
  the parent-commit export (rev 'HEAD~1') captures the same scene (fx off:
  every lighting ticket keeps the switch-off frame identical); extra_js
  runs before the frame.

MOMENTUM_FX_HARNESS_EVIDENCE_DIR (default /tmp/momentum-fx-harness, so a
re-run never rewrites a ticket's evidence) receives determinism.json,
scenes.json, helpers.json (compact) and shots/scene-<name>.png (1280x720)
with shots/compare-<name>.png (left the frame, right its source screenshot).
Requires Playwright Chromium. No remote requests.
"""
import json
import math
import os
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx

EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_FX_HARNESS_EVIDENCE_DIR', '/tmp/momentum-fx-harness'))
DESKTOP = (1280, 720)
MIN_BACKGROUND = 0.2
# Neon of a drawn piece: pixels of its colour family inside its box
NEON_MIN_PIXELS = 20


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def neon_pixels(frame, bbox, kind):
    x0, y0, x1, y1 = [int(round(v)) for v in bbox]
    region = np.asarray(frame)[max(0, y0):max(0, y1 + 1), max(0, x0):max(0, x1 + 1)].astype(int)
    r, g, b = region[..., 0], region[..., 1], region[..., 2]
    if kind == 'green':
        hit = (g > 150) & (g > r + 60) & (g > b + 30)
    else:
        hit = (b > 150) & (b > r + 60)
    return int(hit.sum())


class MomentumFxHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(fx.close)
        cls.frames = {}
        cls.determinism = {}
        cls.helpers = {}
        cls.addClassCleanup(cls.save)
        for viewport in fx.VIEWPORTS:
            for scene in fx.SCENES:
                a = fx.capture(scene, viewport)
                b = fx.capture(scene, viewport)
                key = f'{scene}@{viewport[0]}x{viewport[1]}'
                cls.frames[key] = a
                cls.determinism[key] = {'maxDelta': fx.max_delta(a, b),
                                        'differingPixels': int((np.asarray(a) != np.asarray(b)).any(axis=2).sum()),
                                        'shape': list(a.shape)}

    @classmethod
    def save(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / 'determinism.json').write_text(compact(cls.determinism))
        scenes = {}
        for key, f in cls.frames.items():
            bg = fx.background_mask(f)
            scenes[key] = {
                'canvas': f.info['canvas'], 'rev': f.info['rev'],
                'ninja': [round(v, 1) for v in f.info['ninja']],
                'ninjaRadius': round(f.info['ninjaRadius'], 2),
                'pieces': [{'kind': p['kind'], 'shape': p['shape'], 'bbox': [round(v, 1) for v in p['bbox']],
                            'used': p['used']} for p in f.info['pieces']],
                'walls': f.info['walls'], 'trailPoints': f.info['trailPoints'],
                'backgroundPixels': int(bg.sum()), 'framePixels': int(bg.size),
                'backgroundRatio': round(float(bg.mean()), 4),
                'backgroundLuminance': round(fx.region_luminance(f, bg), 4)}
        (EVIDENCE_DIR / 'scenes.json').write_text(compact(scenes))
        if cls.helpers:
            (EVIDENCE_DIR / 'helpers.json').write_text(compact(cls.helpers))

    def frame(self, scene, viewport=DESKTOP):
        return self.frames[f'{scene}@{viewport[0]}x{viewport[1]}']

    def pieces(self, f, kind):
        return [p for p in f.info['pieces'] if p['kind'] == kind]

    def test_a_deterministic(self):
        """Two captures of every scene and viewport have identical pixels."""
        for key, d in self.determinism.items():
            with self.subTest(key):
                print(f'  {key}: maxDelta {d["maxDelta"]} differingPixels {d["differingPixels"]}', file=sys.stderr)
                self.assertEqual(d['maxDelta'], 0)
        self.assertEqual(len(self.determinism), len(fx.SCENES) * len(fx.VIEWPORTS))

    def test_b_common_content(self):
        """Pieces drawn inside the view, ninja drawn, trail present, background > 20%."""
        for key, f in self.frames.items():
            with self.subTest(key):
                w, h = f.info['canvas']
                self.assertEqual(f.shape[:2], (h, w))
                spec = fx.SCENE_SPECS[f.info['scene']]
                self.assertEqual(len(f.info['pieces']), len(spec['pieces']))
                for p in f.info['pieces']:
                    x0, y0, x1, y1 = p['bbox']
                    self.assertTrue(x1 > 0 and y1 > 0 and x0 < w and y0 < h, p['bbox'])
                    n = neon_pixels(f, p['bbox'], p['kind'])
                    # A half-faded used piece is dimmer: its outline is still there
                    self.assertGreaterEqual(n, NEON_MIN_PIXELS if not p['used'] else 5, (p['kind'], p['bbox'], n))
                nx, ny = f.info['ninja']
                self.assertTrue(0 < nx < w and 0 < ny < h)
                # The ninja (or its trail head) is bright at its centre
                r = max(2, int(math.ceil(f.info['ninjaRadius'])) + 1)
                patch = np.asarray(f)[int(ny) - r:int(ny) + r + 1, int(nx) - r:int(nx) + r + 1]
                self.assertGreater(int(patch.max()), 140)
                self.assertGreaterEqual(f.info['trailPoints'], 2)
                bg = fx.background_mask(f)
                print(f'  {key}: background {bg.mean():.3f} pieces {len(f.info["pieces"])} '
                      f'walls {len(f.info["walls"])} trail {f.info["trailPoints"]}', file=sys.stderr)
                self.assertGreater(bg.mean(), MIN_BACKGROUND)
                self.assertGreater(len(f.info['walls']), 0)

    def corner_px(self, f, spec):
        """The scene anchor in canvas px (anchor at spec['at'] of the view)."""
        w, h = f.info['canvas']
        return spec['at'][0] * w, spec['at'][1] * h

    def test_c_blue_corner(self):
        """Large blue cube in the inner right->up corner under the ceiling overhang, greens up the shaft."""
        for vp in fx.VIEWPORTS:
            with self.subTest(vp):
                f = self.frame('blue-corner', vp)
                cx, cy = self.corner_px(f, fx.SCENE_SPECS['blue-corner'])
                blue, = self.pieces(f, 'blue')
                self.assertEqual(len(self.pieces(f, 'green')), 2)
                x0, y0, x1, y1 = blue['bbox']
                # Cube touches both faces of the corner
                self.assertLess(abs(x0 - cx), 2)
                self.assertLess(abs(y0 - cy), 2)
                self.assertAlmostEqual((x1 - x0) / (y1 - y0), 1, delta=0.02)
                self.assertGreater(y1 - y0, 0.2 * f.info['canvas'][1])
                # Overhang: wall mass left of the corner above it (canvas px)
                wall = fx.wall_mask(f)
                self.assertTrue(wall[int(cy) - 10, :int(cx) - 10].all())
                self.assertFalse(wall[int(cy) + 10, 10:int(cx)].any())
                # Ninja under the ceiling, left of the corner
                nx, ny = f.info['ninja']
                self.assertLess(nx, cx / 2)
                self.assertLess(abs(ny - cy), 3 * f.info['ninjaRadius'])

    def test_d_blue_hit(self):
        """Ninja sitting on a blue rect, a used green fading next to it, trail behind."""
        for vp in fx.VIEWPORTS:
            with self.subTest(vp):
                f = self.frame('blue-hit', vp)
                blue, = self.pieces(f, 'blue')
                green, = self.pieces(f, 'green')
                self.assertTrue(green['used'])
                self.assertFalse(blue['used'])
                nx, ny = f.info['ninja']
                x0, y0, x1, y1 = blue['bbox']
                self.assertTrue(x0 < nx < x1)
                self.assertLess(abs(ny + f.info['ninjaRadius'] - y0), 2)
                self.assertGreaterEqual(f.info['trailPoints'], 90)

    def test_e_mid_shaft(self):
        """Vertical shaft, 5 green rects, ninja in its centre, a straight vertical trail."""
        for vp in fx.VIEWPORTS:
            with self.subTest(vp):
                f = self.frame('mid-shaft', vp)
                greens = self.pieces(f, 'green')
                self.assertEqual(len(greens), 5)
                self.assertEqual(self.pieces(f, 'blue'), [])
                w, h = f.info['canvas']
                nx, ny = f.info['ninja']
                wall = fx.wall_mask(f)
                row = wall[int(ny)]
                left = int(np.nonzero(row[:int(nx)])[0].max())
                right = int(nx) + int(np.nonzero(row[int(nx):])[0].min())
                # Ninja on the shaft centre line, vertically centred; walls both sides
                self.assertLess(abs((left + right) / 2 - nx), 2)
                self.assertLess(abs(ny - h * 422 / 720), 0.02 * h)
                self.assertTrue(wall[:, left].all() and wall[:, right].all())
                # Greens 3 on the left of the ninja, 2 on the right
                self.assertEqual(sorted((p['bbox'][0] + p['bbox'][2]) / 2 < nx for p in greens),
                                 [False, False, True, True, True])
                xs = {round(p[0], 3) for p in f.info['trail']}
                self.assertEqual(len(xs), 1)

    def test_f_run_right(self):
        """Open right corridor, ninja mid-screen, a long trail behind it, the corner top right."""
        for vp in fx.VIEWPORTS:
            with self.subTest(vp):
                f = self.frame('run-right', vp)
                w, h = f.info['canvas']
                nx, ny = f.info['ninja']
                self.assertTrue(0.3 * w < nx < 0.6 * w)
                self.assertTrue(0.4 * h < ny < 0.6 * h)
                trail = f.info['trail']
                self.assertGreaterEqual(f.info['trailPoints'], 90)
                self.assertTrue(all(p[0] <= q[0] for p, q in zip(trail, trail[1:])))
                self.assertGreater(nx - trail[0][0], 0.3 * w)
                wall = fx.wall_mask(f)
                cx, cy = self.corner_px(f, fx.SCENE_SPECS['run-right'])
                # Ceiling above, right wall past the outer corner, corridor open between
                self.assertTrue(wall[int(cy) - 3, :].all())
                self.assertTrue(wall[int(cy) + 5:, int(cx) + 3].all())
                self.assertFalse(wall[int(cy) + 5:int(ny) + 1, 10:int(cx) - 3].any())

    def test_g_helpers(self):
        """hud_mask covers the HUD text; emissive and luminance masks; fx_on/off; parent export; extra_js."""
        f = self.frame('mid-shaft')
        hud = fx.hud_mask(DESKTOP)
        self.assertEqual(hud.shape, f.shape[:2])
        # 'SCORE: 0' top left and the menu button top right are emissive inside the HUD mask
        em = fx.emissive_mask(f)
        self.assertGreater(int((em & hud)[:80, :300].sum()), 50)
        self.assertGreater(int((em & hud)[:80, -120:].sum()), 20)
        self.assertLess(hud.mean(), 0.1)
        self.assertEqual(int((em & fx.background_mask(f)).sum()), 0)
        lum_bg = fx.region_luminance(f, fx.background_mask(f))
        lum_em = fx.region_luminance(f, em)
        self.assertLess(lum_bg, lum_em)
        self.assertIsNone(fx.region_luminance(f, np.zeros(f.shape[:2], bool)))
        # fx_on False reaches the page; the momentum lighting (TASK-053) changes the frame
        off = fx.capture('mid-shaft', DESKTOP, fx_on=False)
        self.assertIs(off.info['fx'], False)
        self.assertIs(f.info['fx'], True)
        # extra_js runs after the scene is built, before draw()
        hidden = fx.capture('mid-shaft', DESKTOP, extra_js='() => { ninja.track.pos = [{x: ninja.x, y: ninja.y}] }')
        self.assertEqual(hidden.info['trailPoints'], 1)
        # The parent commit (git archive export) captures the same scene
        parent = fx.parent_capture('mid-shaft', DESKTOP, fx_on=False)
        self.assertNotEqual(parent.info['rev'], f.info['rev'])
        self.assertEqual(parent.info['pieces'], f.info['pieces'])
        out = EVIDENCE_DIR / 'compare-selftest.png'
        fx.compare_png(f, fx.SOURCES['mid-shaft'], out)
        sheet = Image.open(out)
        out.unlink()
        self.helpers.update({
            'hudBoxes': len(f.info['hud']), 'hudRatio': round(float(hud.mean()), 4),
            'emissiveRatio': round(float(em.mean()), 4), 'backgroundLuminance': round(lum_bg, 4),
            'emissiveLuminance': round(lum_em, 4), 'fxOffMaxDelta': fx.max_delta(f, off),
            'extraJsDifferingPixels': int((np.asarray(f) != np.asarray(hidden)).any(axis=2).sum()),
            'parentRev': parent.info['rev'], 'headRev': f.info['rev'],
            'parentMaxDelta': fx.max_delta(off, parent), 'compareSize': list(sheet.size)})
        print('  helpers: ' + compact(self.helpers), file=sys.stderr)
        self.assertGreater(self.helpers['fxOffMaxDelta'], 0)
        self.assertGreater(self.helpers['extraJsDifferingPixels'], 0)
        self.assertEqual(self.helpers['parentMaxDelta'], 0)
        self.assertEqual(sheet.size, (1280 * 2 + 8, 720 + 22))

    def test_h_shots(self):
        """scene-<name>.png and compare-<name>.png (left the frame, right its source shot)."""
        shots = EVIDENCE_DIR / 'shots'
        for scene in fx.SCENES:
            f = self.frame(scene)
            fx.save_png(f, shots / f'scene-{scene}.png')
            fx.compare_png(f, fx.SOURCES[scene], shots / f'compare-{scene}.png',
                           labels=(f'TASK-052 harness: {scene} 1280x720', 'source'))
            self.assertTrue((shots / f'compare-{scene}.png').exists())


if __name__ == '__main__':
    unittest.main()
