"""Momentum lighting 13/17: foreground crystal silhouettes (TASK-063).

With MOMENTUM_FX on, FOREGROUND.draw (render/foreground.js, after the player,
before the fringe and the HUD) adds near-black crystals through side windows
of a bottom band and a top band under the HUD: one cached, softened strip per
band and viewport, scrolled at STYLE.momentumFx.foreground.parallax x the
camera shift (wrapping); their outline tile masked by the frame's lights is
added as a rim. Checks (tools/momentum_fx_support.py mid-shaft scene; "no
foreground" = the same frame with the FOREGROUND.enabled test hook off):
- foreground.json:
  bands: at 1280x720, 844x390 and 390x844 the silhouette mask (decoded
  maxDelta > 0 against the frame without foreground) lies inside the edge
  bands (x < BAND_W of the view width from the left or right edge and y <
  BAND_H of its height from the top or bottom edge): 0 pixels outside, 0 in
  the HUD rects (fx.hud_mask), 0 inside the shaft the ninja climbs (its
  corridor interior), at least MIN_MASK pixels;
  parallax: one page at 1280x720 (rim off), the camera moved by STEPS steps of
  STEP_PX canvas px (screen.x); each step's mask shift = the integer-then-
  parabola best overlap of the two masks inside the windows' fully opaque
  cores; their sum over the 200 px = PARALLAX_PX +- PARALLAX_TOL (masks
  restricted to the bands: one page's consecutive draws differ a little);
  rim: the frame minus the frame with FOREGROUND.rimEnabled off: pixels
  brighter by > 0 inside the bands, the count within the ninja light's reach
  (rimReach x its radius) > 0, 0 outside the bands;
- cache.json: FRAMES draws with the camera swinging at 1280x720 and 390x844:
  each strip built once, 0 shadowBlur / filter assignments inside
  FOREGROUND.draw over all frames, 0 gradients and 0 canvases created in it
  after frame 1, drawn every frame;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  harness viewports and the classic and bad test_visual_gallery frames with
  the switch on equal the parent commit (decoded maxDelta 0);
- shots/: mid-shaft at 1280x720, 844x390, 390x844, at 1280x720 after a 200 px
  camera move, compare-mid-shaft.png (vs concept 7-foreground.png).
MOMENTUM_FOREGROUND_EVIDENCE_DIR (default /tmp/momentum-foreground) receives
the json files (compact) and shots/. MOMENTUM_FOREGROUND_PARENT is the parent
revision (default: the parent of the commit that added this file, or HEAD
while uncommitted). Requires Playwright Chromium. No remote requests.
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
TEST_PATH = 'tools/test_momentum_foreground.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_FOREGROUND_EVIDENCE_DIR', '/tmp/momentum-foreground'))
SCENE = 'mid-shaft'
VIEWPORTS = [(1280, 720), (844, 390), (390, 844)]
BAND_W = 0.14
BAND_H = 0.30
MIN_MASK = 1000
STEPS = 8
STEP_PX = 25
PARALLAX_PX = 260
PARALLAX_TOL = 4
MAX_STEP_SHIFT = 80
FRAMES = 300
CONCEPT = fx.CONCEPT_DIR / '7-foreground.png'
NO_FOREGROUND = '() => { FOREGROUND.enabled = false }'
NO_RIM = '() => { FOREGROUND.rimEnabled = false }'

# Camera moved by dx canvas px; frames with and without the foreground
CAMERA_PAIR = r'''([dx, rim]) => {
    const k = canvas.width / width * scale[version]
    if (window.__fgX === undefined) window.__fgX = screen.x
    screen.x = window.__fgX + dx / k
    FOREGROUND.rimEnabled = rim
    FOREGROUND.enabled = true
    draw()
    const on = __snap.capture()
    const layout = FOREGROUND.layout.map(b => Object.assign({}, b))
    FOREGROUND.enabled = false
    draw()
    const off = __snap.capture()
    FOREGROUND.enabled = true
    return {on: on, off: off, layout: layout, screenX: screen.x}
}'''

# FRAMES draws with the camera swinging; strip builds, shadowBlur/filter
# assignments, gradients and canvases inside FOREGROUND.draw
CACHE = r'''(frames) => {
    const proto = CanvasRenderingContext2D.prototype
    let inside = false, shadowBlur = 0, filter = 0, gradients = 0, canvases = 0
    for (const [name, count] of [['shadowBlur', () => ++shadowBlur], ['filter', () => ++filter]]) {
        const d = Object.getOwnPropertyDescriptor(proto, name)
        Object.defineProperty(proto, name, {configurable: true, enumerable: d.enumerable, get: d.get,
            set(v) { if (inside) count(); d.set.call(this, v) }})
    }
    for (const name of ['createRadialGradient', 'createLinearGradient', 'createConicGradient', 'createPattern']) {
        const f = proto[name]
        if (f) proto[name] = function (...a) { if (inside) ++gradients; return f.apply(this, a) }
    }
    const createElement = document.createElement
    document.createElement = function (tag) {
        if (inside && String(tag).toLowerCase() == 'canvas') ++canvases
        return createElement.apply(this, arguments)
    }
    const fgDraw = FOREGROUND.draw
    FOREGROUND.draw = function () { inside = true; try { return fgDraw.call(this) } finally { inside = false } }
    const sx = screen.x, sy = screen.y, nx = ninja.x, ny = ninja.y
    const framesBefore = FOREGROUND.frames
    let gradientsFrame1 = 0, canvasesFrame1 = 0
    const builds = []
    for (let i = 0; i < frames; ++i) {
        const dx = 220 * Math.sin(i / 23), dy = 60 * Math.sin(i / 37)
        screen.x = sx + dx; screen.y = sy + dy; ninja.x = nx - dx; ninja.y = ny - dy
        draw()
        if (i == 0) { gradientsFrame1 = gradients; canvasesFrame1 = canvases }
        if (i == 0 || i == frames - 1)
            builds.push({frame: i + 1, bottom: FOREGROUND.builds.bottom, top: FOREGROUND.builds.top})
    }
    FOREGROUND.draw = fgDraw
    document.createElement = createElement
    return {frames: frames, builds: builds, bottomBuilt: FOREGROUND.builds.bottom, topBuilt: FOREGROUND.builds.top,
            drawnFrames: FOREGROUND.frames - framesBefore, shadowBlurSets: shadowBlur, filterSets: filter,
            gradientsFrame1: gradientsFrame1, gradientsAfterFrame1: gradients - gradientsFrame1,
            canvasesFrame1: canvasesFrame1, canvasesAfterFrame1: canvases - canvasesFrame1}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_FOREGROUND_PARENT'):
        return os.environ['MOMENTUM_FOREGROUND_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def decode(png_data):
    return np.asarray(Image.open(io.BytesIO(render_snapshot.png_bytes(png_data))).convert('RGB'))


def diff(a, b):
    return np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).max(axis=2)


def band_mask(shape):
    """The edge bands: within BAND_W of the left/right and BAND_H of the top/bottom edge."""
    h, w = shape[:2]
    xs = np.arange(w)
    ys = np.arange(h)
    side = (xs < BAND_W * w) | (xs >= w - BAND_W * w)
    end = (ys < BAND_H * h) | (ys >= h - BAND_H * h)
    return end[:, None] & side[None, :]


def shaft_mask(frame):
    """Interior of the corridor segment the scene's ninja climbs."""
    h, w = frame.shape[:2]
    seg = frame.info['screen'][2]
    x0, y0, x1, y1 = frame.info['corridors'][seg]
    mask = np.zeros((h, w), dtype=bool)
    mask[max(0, int(np.ceil(y0))):max(0, int(np.floor(y1))), max(0, int(np.ceil(x0))):max(0, int(np.floor(x1)))] = True
    return mask


def core_columns(layout, w):
    """Columns of the windows' fully opaque cores (window minus its fade)."""
    win = layout[0]['window']
    fade = round(0.035 * w) + 2
    cols = np.zeros(w, dtype=bool)
    cols[:win - fade] = True
    cols[w - win + fade:] = True
    return cols


def step_shift(a, b, rows, cols):
    """s with b(x) ~ a(x - s): best agreement inside rows x cols, sub-pixel."""
    a = a[rows].astype(float)
    b = b[rows].astype(float)
    w = a.shape[1]
    score = []
    for s in range(0, MAX_STEP_SHIFT + 1):
        xs = np.nonzero(cols)[0]
        xs = xs[(xs - s >= 0) & cols[np.clip(xs - s, 0, w - 1)]]
        if len(xs) < 8:
            score.append(-1.0)
            continue
        agree = (a[:, xs - s] == b[:, xs]).mean()
        score.append(float(agree))
    i = int(np.argmax(score))
    frac = 0.0
    if 0 < i < len(score) - 1:
        p, q, r = score[i - 1], score[i], score[i + 1]
        den = p - 2 * q + r
        frac = 0.5 * (p - r) / den if den < 0 else 0.0
    return i + frac, score[i]


class MomentumForegroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'foreground.json').write_text(compact(cls.result))
        fx.close()

    def test_0_silhouettes_in_edge_bands(self):
        rows = []
        for vp in VIEWPORTS:
            on = fx.capture(SCENE, vp)
            off = fx.capture(SCENE, vp, extra_js=NO_FOREGROUND)
            mask = diff(on, off) > 0
            bands = band_mask(mask.shape)
            hud = fx.hud_mask(vp, mask.shape)
            shaft = shaft_mask(on)
            ys, xs = np.nonzero(mask)
            row = {'viewport': list(vp), 'canvas': on.info['canvas'], 'maskPixels': int(mask.sum()),
                   'outsideBands': int((mask & ~bands).sum()), 'hudPixels': int((mask & hud).sum()),
                   'hudBoxes': len(on.info['hud']), 'shaftPixels': int((mask & shaft).sum()),
                   'maskBox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None,
                   'bandLimits': {'left': int(np.ceil(BAND_W * mask.shape[1])) - 1,
                                  'right': int(mask.shape[1] - BAND_W * mask.shape[1]),
                                  'top': int(np.ceil(BAND_H * mask.shape[0])) - 1,
                                  'bottom': int(mask.shape[0] - BAND_H * mask.shape[0])}}
            row['pass'] = (row['maskPixels'] >= MIN_MASK and row['outsideBands'] == 0 and row['hudPixels'] == 0
                           and row['shaftPixels'] == 0)
            rows.append(row)
            print('bands', row)
        self.result['bands'] = {'scene': SCENE, 'rows': rows, 'allInBands': all(r['outsideBands'] == 0 for r in rows),
                                'hudPixelsTotal': sum(r['hudPixels'] for r in rows),
                                'shaftPixelsTotal': sum(r['shaftPixels'] for r in rows)}
        for row in rows:
            with self.subTest(viewport=row['viewport']):
                self.assertGreaterEqual(row['maskPixels'], MIN_MASK)
                self.assertEqual(row['outsideBands'], 0)
                self.assertEqual(row['hudPixels'], 0)
                self.assertGreater(row['hudBoxes'], 3)
                self.assertEqual(row['shaftPixels'], 0)

    def test_1_parallax(self):
        vp = VIEWPORTS[0]
        context, page = fx.harness().open(vp)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            masks, layouts, outside = [], [], []
            for i in range(STEPS + 1):
                pair = page.evaluate(CAMERA_PAIR, [i * STEP_PX, False])
                # Consecutive draws of one page differ a little (particles,
                # trail), so only the bands count here; test_0 (one page per
                # frame) proves the mask stays inside them
                mask = diff(decode(pair['on']), decode(pair['off'])) > 0
                outside.append(int((mask & ~band_mask(mask.shape)).sum()))
                masks.append(mask & band_mask(mask.shape))
                layouts.append(pair['layout'])
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        h, w = masks[0].shape
        cols = core_columns(layouts[0], w)
        steps = []
        for i in range(STEPS):
            row = {'cameraPx': [i * STEP_PX, (i + 1) * STEP_PX]}
            for band in layouts[0]:
                rows = slice(band['y'], band['y'] + band['height'])
                s, agree = step_shift(masks[i], masks[i + 1], rows, cols)
                row[band['band']] = round(s, 3)
                row[band['band'] + 'Agree'] = round(agree, 4)
            row['shiftPx'] = round((row['bottom'] + row['top']) / 2, 3)
            steps.append(row)
            print('step', row)
        total = round(sum(r['shiftPx'] for r in steps), 3)
        strip = [round(l[0]['shift'], 3) for l in (layouts[0], layouts[-1])]
        result = {'viewport': list(vp), 'cameraMovePx': STEPS * STEP_PX, 'steps': steps, 'maskShiftPx': total,
                  'expectedPx': PARALLAX_PX, 'tolerancePx': PARALLAX_TOL, 'stripShiftFirstLast': strip,
                  'maskPixelsPerFrame': [int(m.sum()) for m in masks], 'samePageDrawNoiseOutsideBands': outside}
        result['pass'] = abs(total - PARALLAX_PX) <= PARALLAX_TOL
        self.result['parallax'] = result
        print('parallax', total, strip)
        self.assertLessEqual(abs(total - PARALLAX_PX), PARALLAX_TOL)

    def test_2_rim_near_ninja_light(self):
        vp = VIEWPORTS[0]
        rim = fx.capture(SCENE, vp)
        flat = fx.capture(SCENE, vp, extra_js=NO_RIM)
        lift = (np.asarray(rim, dtype=np.int16) - np.asarray(flat, dtype=np.int16)).max(axis=2)
        lit = lift > 0
        bands = band_mask(lit.shape)
        context, page = fx.harness().open(vp)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            page.evaluate(fx.DRAW)
            reach = page.evaluate('''() => {
                const k = canvas.width / width * scale[version]
                const l = visualEffects.lightmap.momentumLights[0]
                return {x: l.x * k, y: l.y * k, radius: l.radius * canvas.height / 1080 * STYLE.momentumFx.foreground.rimReach}
            }''')
        finally:
            context.close()
        h, w = lit.shape
        yy, xx = np.mgrid[0:h, 0:w]
        near = np.hypot(xx - reach['x'], yy - reach['y']) < reach['radius']
        result = {'viewport': list(vp), 'ninjaLight': {k: round(v, 2) for k, v in reach.items()},
                  'rimPixels': int(lit.sum()), 'rimPixelsNearNinjaLight': int((lit & near).sum()),
                  'rimOutsideBands': int((lit & ~bands).sum()), 'rimMaxLift': int(lift.max()),
                  'rimMeanLift': round(float(lift[lit].mean()), 3) if lit.any() else 0}
        result['pass'] = result['rimPixelsNearNinjaLight'] > 0 and result['rimOutsideBands'] == 0
        self.result['rim'] = result
        print('rim', result)
        self.assertGreater(result['rimPixelsNearNinjaLight'], 0)
        self.assertEqual(result['rimOutsideBands'], 0)

    def test_3_cache(self):
        rows = []
        for vp in (VIEWPORTS[0], VIEWPORTS[2]):
            context, page = fx.harness().open(vp)
            try:
                page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
                row = page.evaluate(CACHE, FRAMES)
                self.assertFalse(page.errors, page.errors)
            finally:
                context.close()
            row['viewport'] = list(vp)
            row['pass'] = (row['bottomBuilt'] == 1 and row['topBuilt'] == 1 and row['drawnFrames'] == FRAMES
                           and row['shadowBlurSets'] == 0 and row['filterSets'] == 0
                           and row['gradientsAfterFrame1'] == 0 and row['canvasesAfterFrame1'] == 0)
            rows.append(row)
            print('cache', row)
        (EVIDENCE_DIR / 'cache.json').write_text(compact({'scene': SCENE, 'frames': FRAMES, 'rows': rows,
                                                          'allPass': all(r['pass'] for r in rows)}))
        for row in rows:
            with self.subTest(viewport=row['viewport']):
                self.assertEqual(row['bottomBuilt'], 1)
                self.assertEqual(row['topBuilt'], 1)
                self.assertEqual(row['drawnFrames'], FRAMES)
                self.assertEqual(row['shadowBlurSets'], 0)
                self.assertEqual(row['filterSets'], 0)
                self.assertEqual(row['gradientsAfterFrame1'], 0)
                self.assertEqual(row['canvasesAfterFrame1'], 0)

    def test_4_switch_off_and_other_modes_equal_parent(self):
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

    def test_5_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        for vp in VIEWPORTS:
            frame = fx.capture(SCENE, vp)
            name = f'{vp[0]}x{vp[1]}-mid-shaft.png'
            fx.save_png(frame, shots / name)
            if vp == VIEWPORTS[0]:
                fx.compare_png(frame, CONCEPT, shots / 'compare-mid-shaft.png',
                               labels=('new frame (mid-shaft, foreground silhouettes)', 'concept'))
        moved = fx.capture(SCENE, VIEWPORTS[0], extra_js='''() => {
            screen.x += 200 / (canvas.width / width * scale[version])
            screen.leftWall.update(screen)
            for (const f of floors)
                if (f instanceof MomentumBorderFloor)
                    f.replenishElements()
        }''')
        fx.save_png(moved, shots / '1280x720-mid-shaft-camera-200px.png')
        self.assertEqual(len(list(shots.glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
