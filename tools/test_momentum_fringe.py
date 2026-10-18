"""Momentum lighting 12/17: blue-hit colour fringe (TASK-062).

For STYLE.momentumFx.fringeMs after a blue touch (ScreenEffects.blueHits, the
TASK-060 trigger) ScreenEffects.drawBlueFringe scales the frame's red channel
away from the screen centre and its blue channel toward it, fringePx (px at
1080) each at the screen edges and 0 at the centre, strength 1 - t^2; the HUD
boxes are clipped out. Checks (tools/momentum_fx_support.py blue-hit scene,
1280x720, the touch scripted as blue.onNinjaPass(ninja) at the frozen clock's
T0, one draw() at T0 + dt; two tall thin green pieces are added for the
measurement: one near the left screen side, one at the screen centre):
- fringe.json: at 50 ms the red-blue offset of each piece's left (vertical)
  edge: per channel, the sub-pixel shift that best maps the no-fringe
  frame's column profile (mean over the piece's middle rows) onto the
  fringed one; offset = |shiftRed - shiftBlue|: >= SIDE_MIN near the side,
  <= CENTRE_MAX at the centre. At 200 ms the frame equals the no-fringe frame
  (style fringePx 0; maxDelta 0). HUD boxes (fx.hud_mask) maxDelta 0 against
  the no-fringe frame at 0, 50, 100 ms;
- allocations.json: canvases created (document.createElement('canvas'),
  OffscreenCanvas) during the draws at T0 + 10..140 ms after the first fringe
  draw at T0: 0;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: the blue-hit scene at 50 and 200 ms (1280x720), a 3x crop of the
  left screen side at 50 ms (fringe | no fringe) and compare-50ms.png against
  artifacts/lighting-concept/8-blue-hit-fx.png.
MOMENTUM_FRINGE_EVIDENCE_DIR sets the output dir; MOMENTUM_FRINGE_PARENT the
parent rev (default: the parent of the commit that added this test, HEAD while
it is uncommitted).
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
TEST_PATH = 'tools/test_momentum_fringe.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_FRINGE_EVIDENCE_DIR', '/tmp/momentum-fringe'))
VIEWPORT = (1280, 720)
SCENE = 'blue-hit'
FRINGE_OFF = [('fringePx: 5', 'fringePx: 0')]
MEASURE_MS = 50
CLEAN_MS = 200
HUD_TIMES = (0, 50, 100)
SIDE_MIN = 3
CENTRE_MAX = 1
# Measurement pieces: canvas px centre x, top, bottom, width
EDGE_PIECES = {'side': (110, 430, 610, 24), 'centre': (652, 470, 610, 24)}
MAX_SHIFT = 8
WINDOW = 14

PLACE = r'''(pieces) => {
    const k = canvas.width / width * scale[version]
    for (const [cx, top, bottom, w] of pieces)
        momentumPlacePiece('green', {shape: 'rect', x: cx / k - screen.x, y: (top + bottom) / 2 / k - screen.y,
                                     w: w / k, h: (bottom - top) / k})
}'''

# The scene's blue touched (touch true) at T0, then the clock at T0 + dt
HIT = r'''([touch, dt]) => {
    const blue = floors.find(f => f instanceof MomentumPatternFloor).elements.find(e => e instanceof MomentumBlue)
    const t0 = __snap.now
    if (touch)
        blue.onNinjaPass(ninja)
    __snap.now = t0 + dt
    const effects = visualEffects.screenEffects
    return {touched: effects.blueHits.length > 0, dtMs: dt, fringe: effects.getBlueFringe(__snap.now)}
}'''

# First fringe draw at T0, then canvases created during draws at T0 + dts
ALLOC = r'''(dts) => {
    const blue = floors.find(f => f instanceof MomentumPatternFloor).elements.find(e => e instanceof MomentumBlue)
    const t0 = __snap.now
    blue.onNinjaPass(ninja)
    const effects = visualEffects.screenEffects
    draw()
    const firstUse = !!effects.fringe
    let created = 0
    const createElement = document.createElement
    document.createElement = function(tag) {
        if (String(tag).toLowerCase() == 'canvas')
            ++created
        return createElement.apply(this, arguments)
    }
    const Offscreen = window.OffscreenCanvas
    if (Offscreen)
        window.OffscreenCanvas = function() { ++created; return new Offscreen(...arguments) }
    const fringe = effects.fringe ? effects.fringe.slice() : []
    const strengths = []
    try {
        for (const dt of dts) {
            __snap.now = t0 + dt
            strengths.push(Math.round(effects.getBlueFringe(__snap.now) * 1e4) / 1e4)
            draw()
        }
    } finally {
        document.createElement = createElement
        if (Offscreen)
            window.OffscreenCanvas = Offscreen
    }
    return {firstUse: firstUse, draws: dts.length, dtsMs: dts, strengths: strengths, canvasesCreated: created,
            sameCanvases: fringe.length == 3 && fringe.every((c, i) => c === effects.fringe[i])}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_FRINGE_PARENT'):
        return os.environ['MOMENTUM_FRINGE_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def hit_frame(harness, dt, edges=True):
    """The blue-hit scene (with the measurement pieces) dt ms after the touch."""
    context, page = harness.open(VIEWPORT)
    try:
        page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
        if edges:
            page.evaluate(PLACE, list(EDGE_PIECES.values()))
        state = page.evaluate(HIT, [True, dt])
        info = page.evaluate(fx.DRAW)
        png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        if page.errors:
            raise RuntimeError(f'page errors: {page.errors}')
    finally:
        context.close()
    info.update(scene=SCENE, viewport=list(VIEWPORT), rev=harness.rev, hit=state)
    fx._HUD_BOXES[VIEWPORT] = (info['canvas'], info['hud'])
    return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info)


def best_shift(ref, cur):
    """Sub-pixel s minimising sum (cur(x) - ref(x - s))^2 over |s| <= MAX_SHIFT."""
    n = len(ref)
    xs = np.arange(n, dtype=float)
    cost = []
    for s in range(-MAX_SHIFT, MAX_SHIFT + 1):
        shifted = np.interp(xs - s, xs, ref)
        inner = slice(MAX_SHIFT, n - MAX_SHIFT)
        cost.append(float(((cur[inner] - shifted[inner]) ** 2).sum()))
    i = int(np.argmin(cost))
    if 0 < i < len(cost) - 1:
        a, b, c = cost[i - 1], cost[i], cost[i + 1]
        den = a - 2 * b + c
        frac = 0.5 * (a - c) / den if den > 0 else 0.0
    else:
        frac = 0.0
    return i - MAX_SHIFT + frac


def edge_offset(fringed, plain, piece):
    """Shift of red and blue of a piece's left edge (fringed vs plain), canvas px."""
    cx, top, bottom, w = piece
    edge = int(round(cx - w / 2))
    rows = slice(top + (bottom - top) // 4, bottom - (bottom - top) // 4)
    cols = slice(edge - WINDOW - MAX_SHIFT, edge + WINDOW + MAX_SHIFT)
    out = {'edgeX': edge}
    for name, ch in (('red', 0), ('green', 1), ('blue', 2)):
        ref = np.asarray(plain, dtype=float)[rows, cols, ch].mean(axis=0)
        cur = np.asarray(fringed, dtype=float)[rows, cols, ch].mean(axis=0)
        out[name] = round(best_shift(ref, cur), 3)
    out['offset'] = round(abs(out['red'] - out['blue']), 3)
    return out


class MomentumFringeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.no_fringe = fx.FxHarness('worktree', fx.harness().browser, style_patch=FRINGE_OFF)
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'fringe.json').write_text(compact(cls.result))
        cls.no_fringe.close()
        fx.close()

    def test_0_offset_side_and_centre(self):
        on = hit_frame(fx.harness(), MEASURE_MS)
        off = hit_frame(self.no_fringe, MEASURE_MS)
        self.assertTrue(on.info['hit']['touched'])
        edges = {name: edge_offset(on, off, piece) for name, piece in EDGE_PIECES.items()}
        result = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev, 'dtMs': MEASURE_MS,
                  'strength': round(on.info['hit']['fringe'], 4), 'pieces': EDGE_PIECES, 'edges': edges,
                  'sideOffsetPx': edges['side']['offset'], 'centreOffsetPx': edges['centre']['offset'],
                  'sideMin': SIDE_MIN, 'centreMax': CENTRE_MAX}
        result['pass'] = result['sideOffsetPx'] >= SIDE_MIN and result['centreOffsetPx'] <= CENTRE_MAX
        self.result['offset'] = result
        print('offset', result)
        self.assertGreaterEqual(result['sideOffsetPx'], SIDE_MIN)
        self.assertLessEqual(result['centreOffsetPx'], CENTRE_MAX)

    def test_1_clean_after_and_hud(self):
        rows = []
        for dt in HUD_TIMES + (CLEAN_MS,):
            on = hit_frame(fx.harness(), dt)
            off = hit_frame(self.no_fringe, dt)
            hud = fx.hud_mask(VIEWPORT, on.shape)
            diff = np.abs(np.asarray(on, dtype=np.int16) - np.asarray(off, dtype=np.int16)).max(axis=2)
            rows.append({'dtMs': dt, 'strength': round(on.info['hit']['fringe'], 4),
                         'hudBoxes': len(on.info['hud']), 'hudPixels': int(hud.sum()),
                         'hudMaxDelta': int(diff[hud].max()), 'frameMaxDelta': int(diff.max()),
                         'changedPixels': int((diff > 0).sum())})
            print('frame', rows[-1])
        by = {r['dtMs']: r for r in rows}
        self.result['frames'] = {'rows': rows, 'cleanAt200': by[CLEAN_MS]['frameMaxDelta'] == 0,
                                 'hudMaxDeltaAll': max(by[dt]['hudMaxDelta'] for dt in HUD_TIMES)}
        self.assertEqual(by[CLEAN_MS]['frameMaxDelta'], 0)
        for dt in HUD_TIMES:
            self.assertGreater(by[dt]['hudBoxes'], 3)
            self.assertEqual(by[dt]['hudMaxDelta'], 0)
            self.assertGreater(by[dt]['changedPixels'], 0)

    def test_2_allocations(self):
        context, page = fx.harness().open(VIEWPORT)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            result = page.evaluate(ALLOC, list(range(10, 150, 10)))
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        print('allocations', result)
        (EVIDENCE_DIR / 'allocations.json').write_text(compact(result))
        self.assertTrue(result['firstUse'])
        self.assertTrue(all(s > 0 for s in result['strengths']))
        self.assertEqual(result['canvasesCreated'], 0)
        self.assertTrue(result['sameCanvases'])

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
        for dt in (MEASURE_MS, CLEAN_MS):
            frame = hit_frame(fx.harness(), dt, edges=False)
            fx.save_png(frame, shots / f'1280x720-blue-hit-{dt}ms.png')
            if dt == MEASURE_MS:
                fx.compare_png(frame, fx.CONCEPT_DIR / '8-blue-hit-fx.png', shots / 'compare-50ms.png',
                               labels=('new frame 50 ms after the blue touch', 'concept'))
        on = hit_frame(fx.harness(), MEASURE_MS)
        off = hit_frame(self.no_fringe, MEASURE_MS)
        crop = (slice(400, 640), slice(0, 240))
        zoom = [np.asarray(Image.fromarray(np.asarray(f, dtype=np.uint8)[crop]).resize((720, 720), Image.NEAREST))
                for f in (on, off)]
        gap = np.full((720, 8, 3), 24, dtype=np.uint8)
        fx.save_png(np.concatenate([zoom[0], gap, zoom[1]], axis=1), shots / 'edge-crop-50ms-x3.png')
        self.assertEqual(len(list(shots.glob('*.png'))), 4)


if __name__ == '__main__':
    unittest.main()
