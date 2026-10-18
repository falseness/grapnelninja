"""Momentum lighting 7/17: crystal edges catch the light (TASK-057).

With MOMENTUM_FX on, LightmapRenderer.addCrystalRim adds the background's
edge tiles (BackgroundRenderer.drawLayerEdges: the far crystals' edges and the
near rocks' rims, each a cached tile built once per viewport and drawn with
its layer's getLayerShift parallax) masked by the frame's shadowed lights
(rimLightCanvas, source-in) over the dimmed background at
momentumLight.rimStrength. Checks (tools/momentum_fx_support.py scenes,
1280x720), the parent commit being the TASK-056 look:
- rim.json (later effects off, LATER_EFFECTS_OFF): the edge mask is drawLayerEdges into a blank canvas of the
  frame (alpha >= EDGE_ALPHA), restricted to the background mask of both
  frames. run-right and mid-shaft: edge pixels within NEAR_PX of the ninja
  are on average >= MIN_EDGE_RATIO x the parent's luminance; background
  pixels at least NON_EDGE_GAP px off every edge within NEAR_PX change by
  <= MAX_NON_EDGE_CHANGE (mean relative luminance change). far: run-right
  with the ninja moved to the left of the view and no trail; edge pixels more
  than FAR_PX from every light (ninja, trail, blue lights) have maxDelta <=
  MAX_FAR_DELTA vs the parent;
- cache.json: FRAMES frames with the camera swinging (screen.x/y, ninja with
  it) at both harness viewports: farEdges/nearEdges built exactly once,
  0 CanvasGradient created after frame 1, the rim drawn every frame;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: run-right and mid-shaft at 1280x720, a 2x zoom crop round the
  ninja (run-right), compare-run-right.png (vs concept 5-rim-slow.png).

MOMENTUM_CRYSTAL_RIM_EVIDENCE_DIR (default /tmp/momentum-crystal-rim)
receives the json files (compact) and shots/. MOMENTUM_CRYSTAL_RIM_PARENT is
the parent revision (default: the parent of the commit that added this file,
or HEAD while uncommitted). Requires Playwright Chromium. No remote requests.
"""
import base64
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
TEST_PATH = 'tools/test_momentum_crystal_rim.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_CRYSTAL_RIM_EVIDENCE_DIR', '/tmp/momentum-crystal-rim'))
VIEWPORT = (1280, 720)
NEAR_SCENES = ('run-right', 'mid-shaft')
EDGE_ALPHA = 128
NEAR_PX = 250
FAR_PX = 700
NON_EDGE_GAP = 3
MIN_EDGE_RATIO = 1.30
MAX_NON_EDGE_CHANGE = 0.05
MAX_FAR_DELTA = 2
FRAMES = 300
CONCEPT = fx.CONCEPT_DIR / '5-rim-slow.png'
# Later effects (the TASK-058 lit motes) switched off by a STYLE override in
# the rim and far checks, so only the rim is compared with the parent
LATER_EFFECTS_OFF = [('moteGain: 5', 'moteGain: 0')]
# Ninja to the left edge of the view, no trail: most of the view is far
NINJA_LEFT = '''() => { ninja.x = -screen.x + 60 * width / scale[version] / 1280; ninja.track.pos = [] }'''

# Edge mask of the current frame (drawLayerEdges into a blank canvas) and the
# lights' centres in canvas px
EDGES = r'''() => {
    const c = document.createElement('canvas')
    c.width = canvas.width; c.height = canvas.height
    const x = c.getContext('2d')
    visualEffects.background.drawLayerEdges(x)
    const data = x.getImageData(0, 0, c.width, c.height).data
    const alpha = new Uint8Array(c.width * c.height)
    for (let i = 0; i < alpha.length; ++i) alpha[i] = data[i * 4 + 3]
    let s = ''
    for (let i = 0; i < alpha.length; i += 0x8000) s += String.fromCharCode.apply(null, alpha.subarray(i, i + 0x8000))
    const k = canvas.width / width * scale[version]
    const lights = visualEffects.lightmap.momentumLights.map(l => [l.x * k, l.y * k])
    return {alpha: btoa(s), lights: lights}
}'''

# FRAMES draws with the camera swinging; counts edge tile builds and gradients
CACHE = r'''(frames) => {
    const bg = visualEffects.background, lm = visualEffects.lightmap
    const proto = CanvasRenderingContext2D.prototype
    let gradients = 0, rims = 0, rimDrawn = 0
    const wrap = name => { const f = proto[name]; proto[name] = function (...a) { ++gradients; return f.apply(this, a) } }
    wrap('createRadialGradient'); wrap('createLinearGradient'); wrap('createConicGradient')
    const addRim = lm.addCrystalRim
    lm.addCrystalRim = function () {
        ++rims
        const before = rimDrawCount
        addRim.call(this)
        if (rimDrawCount > before) ++rimDrawn
    }
    let rimDrawCount = 0
    const rimCtx = lm.rimCtx, drawImage = rimCtx.drawImage
    rimCtx.drawImage = function (...a) { if (a[0] === lm.rimLightCanvas) ++rimDrawCount; return drawImage.apply(this, a) }
    const sx = screen.x, sy = screen.y, nx = ninja.x, ny = ninja.y
    const builds = [], gradientsAt = [], shifts = []
    for (let i = 0; i < frames; ++i) {
        const dx = 220 * Math.sin(i / 23), dy = 60 * Math.sin(i / 37)
        screen.x = sx + dx; screen.y = sy + dy; ninja.x = nx - dx; ninja.y = ny - dy
        draw()
        gradientsAt.push(gradients)
        if (i == 0 || i == frames - 1) builds.push({frame: i + 1, farEdges: bg.layerBuilds.farEdges || 0,
                                                   nearEdges: bg.layerBuilds.nearEdges || 0})
        if (i % 50 == 0) shifts.push(Math.round(bg.getLayerShift(LOGICAL_VIEWPORT.width, LOGICAL_VIEWPORT.height,
                                                               STYLE.caveLayers.crystals).x * 100) / 100)
    }
    return {frames: frames, builds: builds, farEdgesBuilt: bg.layerBuilds.farEdges || 0,
            nearEdgesBuilt: bg.layerBuilds.nearEdges || 0, gradientsFrame1: gradientsAt[0],
            gradientsAfterFrame1: gradients - gradientsAt[0], rimCalls: rims, rimDrawnFrames: rimDrawn,
            farShiftSamples: shifts}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_CRYSTAL_RIM_PARENT'):
        return os.environ['MOMENTUM_CRYSTAL_RIM_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


_RIM_HARNESS = []


def rim_harness():
    """The worktree harness, with LATER_EFFECTS_OFF served when its style.js has them."""
    tree = fx.harness()
    later_off = [patch for patch in LATER_EFFECTS_OFF if patch[0] in (tree.root / 'style.js').read_text()]
    if not later_off:
        return tree
    if not _RIM_HARNESS:
        _RIM_HARNESS.append(fx.FxHarness('worktree', tree.browser, style_patch=later_off))
    return _RIM_HARNESS[0]


def capture_with_edges(scene, extra_js=None):
    """(frame, edge alpha (h, w) uint8, light centres) of scene at VIEWPORT (worktree)."""
    context, page = rim_harness().open(VIEWPORT)
    try:
        page.evaluate(fx.BUILD, [fx.SCENE_SPECS[scene], True])
        if extra_js:
            page.evaluate(extra_js)
        info = page.evaluate(fx.DRAW)
        png = fx.render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        edges = page.evaluate(EDGES)
        if page.errors:
            raise RuntimeError(f'page errors in {scene}: {page.errors}')
    finally:
        context.close()
    info.update(scene=scene, viewport=list(VIEWPORT), rev='worktree')
    fx._HUD_BOXES[VIEWPORT] = (info['canvas'], info['hud'])
    frame = fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info)
    alpha = np.frombuffer(base64.b64decode(edges['alpha']), dtype=np.uint8).reshape(frame.shape[:2])
    return frame, alpha, edges['lights']


def dilate(mask, r):
    """mask grown by r px (square neighbourhood)."""
    out = mask.copy()
    h, w = mask.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] |= \
                mask[max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)]
    return out


def distance_map(shape, points):
    """Distance in px from every pixel to the nearest of points."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    best = np.full(shape, np.inf)
    for x, y in points:
        best = np.minimum(best, np.hypot(xx - x, yy - y))
    return best


class MomentumCrystalRimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.result = {'parent': cls.parent, 'viewport': list(VIEWPORT), 'edgeAlpha': EDGE_ALPHA}

    @classmethod
    def tearDownClass(cls):
        (EVIDENCE_DIR / 'rim.json').write_text(compact(cls.result))
        while _RIM_HARNESS:
            _RIM_HARNESS.pop().close()
        fx.close()

    def test_0_near_edges_lit_rest_kept(self):
        rows = []
        for scene in NEAR_SCENES:
            new, alpha, lights = capture_with_edges(scene)
            old = fx.capture(scene, VIEWPORT, fx_on=True, rev=self.parent)
            background = fx.background_mask(new) & fx.background_mask(old)
            near = distance_map(alpha.shape, [new.info['ninja']]) <= NEAR_PX
            edge = (alpha >= EDGE_ALPHA) & background & near
            off_edge = ~dilate(alpha > 0, NON_EDGE_GAP - 1)
            non_edge = off_edge & background & near
            lum_new, lum_old = fx.luminance(new), fx.luminance(old)
            ratio = float(lum_new[edge].mean() / lum_old[edge].mean())
            change = np.abs(lum_new[non_edge] - lum_old[non_edge]) / np.maximum(lum_old[non_edge], 1 / 255)
            row = {'scene': scene, 'ninja': [round(v, 1) for v in new.info['ninja']], 'lights': len(lights),
                   'edgePixels': int(edge.sum()), 'edgeLumNew': round(float(lum_new[edge].mean()), 4),
                   'edgeLumParent': round(float(lum_old[edge].mean()), 4), 'edgeRatio': round(ratio, 4),
                   'nonEdgePixels': int(non_edge.sum()), 'nonEdgeMeanChange': round(float(change.mean()), 5),
                   'nonEdgeMaxDelta': fx.max_delta(new[non_edge], old[non_edge]),
                   'pass': bool(ratio >= MIN_EDGE_RATIO and change.mean() <= MAX_NON_EDGE_CHANGE)}
            print('near', row)
            rows.append(row)
        self.result.update(nearPx=NEAR_PX, minEdgeRatio=MIN_EDGE_RATIO, nonEdgeGap=NON_EDGE_GAP,
                           maxNonEdgeChange=MAX_NON_EDGE_CHANGE, near=rows)
        for row in rows:
            with self.subTest(scene=row['scene']):
                self.assertGreater(row['edgePixels'], 200)
                self.assertGreater(row['nonEdgePixels'], 10000)
                self.assertGreaterEqual(row['edgeRatio'], MIN_EDGE_RATIO)
                self.assertLessEqual(row['nonEdgeMeanChange'], MAX_NON_EDGE_CHANGE)

    def test_1_far_edges_unchanged(self):
        new, alpha, lights = capture_with_edges('run-right', NINJA_LEFT)
        old = fx.capture('run-right', VIEWPORT, fx_on=True, extra_js=NINJA_LEFT, rev=self.parent)
        background = fx.background_mask(new) & fx.background_mask(old)
        far = distance_map(alpha.shape, lights) > FAR_PX
        edge = (alpha >= EDGE_ALPHA) & background & far
        anyEdge = (alpha > 0) & background & far
        row = {'scene': 'run-right', 'variant': 'ninja at the left, no trail',
               'ninja': [round(v, 1) for v in new.info['ninja']],
               'lights': [[round(v, 1) for v in p] for p in lights], 'farPx': FAR_PX,
               'edgePixels': int(edge.sum()), 'edgeMaxDelta': fx.max_delta(new[edge], old[edge]),
               'anyEdgePixels': int(anyEdge.sum()), 'anyEdgeMaxDelta': fx.max_delta(new[anyEdge], old[anyEdge]),
               'farBackgroundMaxDelta': fx.max_delta(new[background & far], old[background & far])}
        row['pass'] = row['edgeMaxDelta'] <= MAX_FAR_DELTA
        print('far', row)
        self.result['far'] = row
        self.assertGreater(row['edgePixels'], 200)
        self.assertLessEqual(row['edgeMaxDelta'], MAX_FAR_DELTA)

    def test_2_edge_tiles_built_once_no_gradients(self):
        rows = []
        for viewport in fx.VIEWPORTS:
            context, page = fx.harness().open(viewport)
            try:
                page.evaluate(fx.BUILD, [fx.SCENE_SPECS['run-right'], True])
                row = page.evaluate(CACHE, FRAMES)
                if page.errors:
                    raise RuntimeError(f'page errors: {page.errors}')
            finally:
                context.close()
            row['viewport'] = list(viewport)
            row['pass'] = (row['farEdgesBuilt'] == 1 and row['nearEdgesBuilt'] == 1
                           and row['gradientsAfterFrame1'] == 0 and row['rimDrawnFrames'] == FRAMES)
            print('cache', row)
            rows.append(row)
        (EVIDENCE_DIR / 'cache.json').write_text(compact({'scene': 'run-right', 'frames': FRAMES,
                                                          'allPass': all(r['pass'] for r in rows), 'runs': rows}))
        for row in rows:
            with self.subTest(viewport=row['viewport']):
                self.assertEqual(row['farEdgesBuilt'], 1)
                self.assertEqual(row['nearEdgesBuilt'], 1)
                self.assertEqual(row['gradientsAfterFrame1'], 0)
                self.assertEqual(row['rimDrawnFrames'], FRAMES)
                self.assertGreater(len(set(row['farShiftSamples'])), 3)

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
        for scene in NEAR_SCENES:
            frames[scene] = fx.capture(scene, VIEWPORT, fx_on=True)
            fx.save_png(frames[scene], shots / f'1280x720-{scene}.png')
        run = frames['run-right']
        nx, ny = (int(round(v)) for v in run.info['ninja'])
        w, h = VIEWPORT[0] // 2, VIEWPORT[1] // 2
        x0 = min(max(0, nx - w // 2), VIEWPORT[0] - w)
        y0 = min(max(0, ny - h // 2), VIEWPORT[1] - h)
        crop = Image.fromarray(np.asarray(run[y0:y0 + h, x0:x0 + w], dtype=np.uint8))
        crop.resize((w * 2, h * 2), Image.NEAREST).save(shots / f'zoom2x-run-right-{x0}-{y0}.png')
        fx.compare_png(run, CONCEPT, shots / 'compare-run-right.png', labels=('new frame (crystal rim)', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 4)


if __name__ == '__main__':
    unittest.main()
