"""Momentum lighting 5/17: blue pieces are area lights, greens emit nothing (TASK-055).

With MOMENTUM_FX on a MomentumBlue lights the cave from its outline outward
(LightmapRenderer.collectEmitters / fillAreaLight: the obstacle spill sprite
widened to momentumLight.blueSpread, multiplied over the background plus a
'lighter' haze), shadowed by the other pieces and the walls from its centre
(TASK-054 cutShadows, the blue itself skipped), scaled by its fade alpha.
Momentum pieces add no obstacle spill outside the player trail band
(LightmapRenderer.draw clips it to the band, so the trail's pixels stay as
with the lighting off). Lone-piece frames
put one piece on the run-right scene of tools/momentum_fx_support.py at
1280x720 (pattern floor emptied, ninja moved > 700 px away, motes hidden).
Light-off frames keep the blue but drop its light (collectEmitters skips the
blues); no-piece frames drop the piece. Checks:
- blue-light.json: per shape (rect, triangle, rotated polygon) the ring of
  background pixels RING_PX (+-2) outside the outline: mean luminance on /
  light-off >= 1.4 (also reported vs no-piece), hue of the ring's mean colour
  and of the added light within 25 deg of momentum.blueStroke; blue fill
  pixels (the polygon eroded by FILL_INSET px) maxDelta <= 3 vs MOMENTUM_FX off;
- blue-fade.json: ring gain (luminance on / light-off - 1) of a blue rect
  untouched and used at fade progress 0 and 0.5 (frozen clock): > 0.4
  untouched, <= 1 % used (TASK-076: a used blue vanishes at once; one ring,
  background in all six frames);
- green-dark.json: a lone green at the same positions: pixels outside the
  green's own pixels (the diff with / without it with the lightmap disabled)
  equal the no-piece frame (maxDelta 0); parentMaxDelta shows the old spill;
- blue-shadow.json: a green between a blue and the corridor floor: gain of the
  blue's light (on - light-off luminance) at the point SHADOW_BEHIND_PX past
  the green on the ray from the blue's centre / gain at the mirrored point
  above the blue <= 0.45 (luminance ratio reported too);
- blue-wall-leak.json: a blue next to the floor's corner (the down shaft
  behind it): background grid samples whose rays to the blue's centre (and
  from LEAK_MARGIN px round them) cross a wall stay within 2 % of the
  light-off frame; unshadowedRise is what the light adds there uncut;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0);
- shots/: blue-corner, blue-hit, a blue triangle and a rotated blue polygon
  (each with a green beside it) at 1280x720, compare-blue-corner.png and
  compare-blue-hit.png.

MOMENTUM_BLUE_LIGHT_EVIDENCE_DIR (default /tmp/momentum-blue-light) receives
the json files (compact) and shots/. MOMENTUM_BLUE_LIGHT_PARENT is the parent
revision (default: the parent of the commit that added this file, or HEAD
while uncommitted). Requires Playwright Chromium. No remote requests.
"""
import colorsys
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_ninja_light import gallery_frames

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_blue_light.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_LIGHT_EVIDENCE_DIR', '/tmp/momentum-blue-light'))
VIEWPORT = (1280, 720)
SCENE = 'run-right'
RING_PX = 40
RING_HALF = 2
FILL_INSET = 4
MIN_RATIO = 1.4
MAX_HUE_DEG = 25
MAX_FILL_DELTA = 3
SHADOW_BEHIND_PX = 30
MAX_SHADOW_RATIO = 0.45
BLUE_STROKE = '#2f86ff'
# Ninja far right in the corridor (canvas px); the pieces sit round x 300
NINJA_PX = (1100, 200)
# Lone pieces in canvas px of the 1280x720 run-right frame (the corridor
# runs from the ceiling at y 70 to the floor at y 397 at x < 599 since
# TASK-128's 1.0-height corridor; the pieces sit round its centre line)
SHAPES = {
    'rect': {'shape': 'rect', 'x': 300, 'y': 234, 'w': 140, 'h': 100},
    'triangle': {'shape': 'triangle', 'x': 300, 'y': 234, 'radius': 90},
    'polygon': {'shape': 'polygon', 'x': 300, 'y': 234, 'angle': 0.6,
                'points': [[-80, -40], [10, -75], [85, -10], [40, 60], [-60, 50]]},
}
# Green between a blue and the floor (y 397 at x < 599)
SHADOW_PIECES = [('blue', {'shape': 'rect', 'x': 300, 'y': 250, 'w': 140, 'h': 50}),
                 ('green', {'shape': 'rect', 'x': 300, 'y': 300, 'w': 160, 'h': 24})]
SHOT_PIECES = {
    'triangle': [('blue', {'shape': 'triangle', 'x': 330, 'y': 250, 'radius': 110}),
                 ('green', {'shape': 'rect', 'x': 600, 'y': 234, 'w': 60, 'h': 150})],
    'rotated': [('blue', {'shape': 'rect', 'x': 330, 'y': 250, 'w': 200, 'h': 70, 'angle': 0.45}),
                ('green', {'shape': 'polygon', 'x': 640, 'y': 234, 'angle': -0.3,
                           'points': [[-60, -40], [60, -40], [70, 40], [-50, 50]]})],
}
# Blue left of the floor's corner (599, 397): the down shaft lies behind it
LEAK_PIECES = [('blue', {'shape': 'rect', 'x': 530, 'y': 348, 'w': 60, 'h': 30})]
LEAK_GRID = 12
LEAK_MARGIN = 12
LEAK_TOLERANCE = 0.02
NO_SHADOWS = '() => { visualEffects.lightmap.cutShadows = () => {} }'
NO_MOTES = '() => { visualEffects.particles.drawAmbientMotes = () => {} }'
# Pieces [kind, spec in canvas px, fade or null], ninja canvas px; the
# pattern floor is emptied first
PLACE = r'''([pieces, ninjaPx, noMotes]) => {
    const k = canvas.width / width * scale[version]
    for (const f of floors)
        if (f instanceof MomentumPatternFloor) { f.elements = []; if (f.groups) f.groups = [] }
    const placed = []
    for (const [kind, s, fade] of pieces) {
        const spec = {shape: s.shape, x: s.x / k - screen.x, y: s.y / k - screen.y, angle: s.angle || 0}
        if (s.shape == 'rect') { spec.w = s.w / k; spec.h = s.h / k }
        else if (s.shape == 'triangle') spec.radius = s.radius / k
        else spec.points = s.points.map(p => ({x: p[0] / k, y: p[1] / k}))
        const element = momentumPlacePiece(kind, spec).element
        if (fade !== null && fade !== undefined) {
            element.use()
            element.fadeStartMs = performance.now() - fade * GAMEPLAY.momentumFadeMs
        }
        placed.push(element.getAlpha())
    }
    ninja.x = ninjaPx[0] / k - screen.x; ninja.y = ninjaPx[1] / k - screen.y
    ninja.track.pos = [{x: ninja.x + 40, y: ninja.y}, {x: ninja.x, y: ninja.y}]
    if (noMotes) visualEffects.particles.drawAmbientMotes = () => {}
    window.__placedAlphas = placed
}'''
LIGHT_OFF = '''() => { const l = visualEffects.lightmap, collect = l.collectEmitters
    l.collectEmitters = function(s) { const e = collect.call(this, s)
        for (let i = e.length - 1; i >= 0; --i) if (e[i].element) e.splice(i, 1)
        return e } }'''
LIGHTMAP_OFF = '() => { visualEffects.lightmap.enabled = false }'


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_BLUE_LIGHT_PARENT'):
        return os.environ['MOMENTUM_BLUE_LIGHT_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def lone(pieces, fx_on=True, extra=None, motes=False, rev='worktree'):
    """run-right frame with only pieces ([kind, spec, fade?]) and the ninja far away."""
    rows = [[p[0], p[1], p[2] if len(p) > 2 else None] for p in pieces]
    body = f'(({PLACE}))({json.dumps([rows, NINJA_PX, not motes])});'
    if extra:
        body += f'({extra})();'
    frame = fx.capture(SCENE, VIEWPORT, fx_on=fx_on, extra_js=f'() => {{ {body} }}', rev=rev)
    return frame


def polygon_px(frame, index=0):
    return np.array(frame.info['pieces'][index]['poly'], dtype=np.float64)


def polygon_fill(shape, poly):
    image = Image.new('1', (shape[1], shape[0]), 0)
    ImageDraw.Draw(image).polygon([tuple(p) for p in poly], fill=1, outline=1)
    return np.asarray(image, dtype=bool)


def outline_distance(shape, poly):
    """Per pixel centre: distance (canvas px) to the polygon outline."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    px, py = xx + 0.5, yy + 0.5
    best = np.full(shape[:2], np.inf)
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        d = b - a
        t = np.clip(((px - a[0]) * d[0] + (py - a[1]) * d[1]) / max(d @ d, 1e-9), 0, 1)
        best = np.minimum(best, np.hypot(a[0] + t * d[0] - px, a[1] + t * d[1] - py))
    return best


def ring_mask(frames, poly, distance=RING_PX):
    shape = frames[0].shape
    dist = outline_distance(shape, poly)
    ring = (np.abs(dist - distance) <= RING_HALF) & ~polygon_fill(shape, poly)
    for f in frames:
        ring &= fx.background_mask(f)
    return ring


def mean_rgb(frame, mask):
    return np.asarray(frame, dtype=np.float64)[mask].mean(axis=0)


def hue_deg(rgb):
    r, g, b = (float(c) / 255 for c in rgb)
    return colorsys.rgb_to_hsv(max(r, 0), max(g, 0), max(b, 0))[0] * 360


def hue_gap(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def stroke_hue():
    return hue_deg([int(BLUE_STROKE[i:i + 2], 16) for i in (1, 3, 5)])


def masked_delta(a, b, mask):
    if not mask.any():
        return 0
    return int(np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16))[mask].max())


def diff_mask(a, b):
    return np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).max(axis=2) > 0


def crosses_wall(walls, a, b):
    """Whether the segment a-b (canvas px) crosses a wall pixel."""
    n = int(np.hypot(b[0] - a[0], b[1] - a[1]))
    h, w = walls.shape
    for i in range(1, n):
        x = int(a[0] + (b[0] - a[0]) * i / n)
        y = int(a[1] + (b[1] - a[1]) * i / n)
        if 0 <= x < w and 0 <= y < h and walls[y, x]:
            return True
    return False


def patch(frame, mask, x, y, r=6):
    yy, xx = np.mgrid[0:frame.shape[0], 0:frame.shape[1]]
    region = mask & (np.hypot(xx + 0.5 - x, yy + 0.5 - y) <= r)
    return fx.region_luminance(frame, region), int(region.sum())


class MomentumBlueLightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()

    @classmethod
    def tearDownClass(cls):
        fx.close()

    def test_0_blue_lights_its_surroundings(self):
        target = stroke_hue()
        rows = []
        for name, spec in SHAPES.items():
            on = lone([('blue', spec)])
            dark = lone([('blue', spec)], extra=LIGHT_OFF)
            empty = lone([])
            off = lone([('blue', spec)], fx_on=False)
            poly = polygon_px(on)
            ring = ring_mask([on, dark, empty], poly)
            lum_on, lum_dark, lum_empty = (fx.region_luminance(f, ring) for f in (on, dark, empty))
            rgb_on, rgb_dark = mean_rgb(on, ring), mean_rgb(dark, ring)
            fill = polygon_fill(on.shape, poly) & (outline_distance(on.shape, poly) > FILL_INSET)
            row = {'shape': name, 'bbox': on.info['pieces'][0]['bbox'],
                   'ninjaDistancePx': round(float(np.hypot(*(np.array(on.info['ninja']) - poly.mean(axis=0)))), 1),
                   'ringPx': RING_PX, 'ringPixels': int(ring.sum()),
                   'lumOn': round(lum_on, 5), 'lumLightOff': round(lum_dark, 5), 'lumNoPiece': round(lum_empty, 5),
                   'ratio': round(lum_on / lum_dark, 4), 'ratioNoPiece': round(lum_on / lum_empty, 4),
                   'ringRgb': [round(c, 1) for c in rgb_on], 'ringHueDeg': round(hue_deg(rgb_on), 1),
                   'addedRgb': [round(c, 1) for c in rgb_on - rgb_dark],
                   'addedHueDeg': round(hue_deg(rgb_on - rgb_dark), 1), 'strokeHueDeg': round(target, 1),
                   'fillPixels': int(fill.sum()), 'fillMaxDelta': masked_delta(on, off, fill)}
            row['hueGapDeg'] = round(hue_gap(row['ringHueDeg'], target), 1)
            row['addedHueGapDeg'] = round(hue_gap(row['addedHueDeg'], target), 1)
            row['pass'] = (row['ninjaDistancePx'] > 700 and row['ratio'] >= MIN_RATIO
                           and row['ratioNoPiece'] >= MIN_RATIO and row['hueGapDeg'] <= MAX_HUE_DEG
                           and row['addedHueGapDeg'] <= MAX_HUE_DEG and row['fillMaxDelta'] <= MAX_FILL_DELTA)
            print(row)
            rows.append(row)
        (EVIDENCE_DIR / 'blue-light.json').write_text(compact({
            'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev, 'minRatio': MIN_RATIO,
            'maxHueDeg': MAX_HUE_DEG, 'maxFillDelta': MAX_FILL_DELTA, 'shapes': rows,
            'allPass': all(r['pass'] for r in rows)}))
        for r in rows:
            with self.subTest(shape=r['shape']):
                self.assertGreater(r['ninjaDistancePx'], 700)
                self.assertGreater(r['ringPixels'], 100)
                self.assertGreaterEqual(r['ratio'], MIN_RATIO)
                self.assertGreaterEqual(r['ratioNoPiece'], MIN_RATIO)
                self.assertLessEqual(r['hueGapDeg'], MAX_HUE_DEG)
                self.assertLessEqual(r['addedHueGapDeg'], MAX_HUE_DEG)
                self.assertGreater(r['fillPixels'], 500)
                self.assertLessEqual(r['fillMaxDelta'], MAX_FILL_DELTA)

    def test_1_light_ends_with_the_touch(self):
        # TASK-076: a used blue vanishes at once (no fade), so its light goes
        # with it: untouched (fade None) vs used at fade progress 0 and 0.5
        spec = SHAPES['rect']
        rows = []
        pairs = {fade: (lone([('blue', spec, fade)]), lone([('blue', spec, fade)], extra=LIGHT_OFF))
                 for fade in (None, 0, 0.5)}
        # One ring for all three: background in every frame
        ring = ring_mask([f for pair in pairs.values() for f in pair], polygon_px(pairs[None][0]))
        for fade, (on, dark) in pairs.items():
            gain = fx.region_luminance(on, ring) / fx.region_luminance(dark, ring) - 1
            rows.append({'fade': fade, 'used': fade is not None, 'ringPixels': int(ring.sum()),
                         'gain': round(gain, 5)})
        g_full, g_used0, g_used05 = (r['gain'] for r in rows)
        result = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev, 'clock': 'frozen',
                  'ringPx': RING_PX, 'rows': rows, 'zeroGainMax': 0.01,
                  'pass': g_full > 0.4 and abs(g_used0) <= 0.01 and abs(g_used05) <= 0.01}
        print(result)
        (EVIDENCE_DIR / 'blue-fade.json').write_text(compact(result))
        self.assertGreater(g_full, 0.4)
        self.assertLessEqual(abs(g_used0), 0.01)
        self.assertLessEqual(abs(g_used05), 0.01)

    def test_2_greens_emit_nothing(self):
        rows = []
        empty = lone([])
        empty_dark = lone([], extra=LIGHTMAP_OFF)
        parent_empty = lone([], rev=self.parent)
        for name, spec in SHAPES.items():
            green = lone([('green', spec)])
            own = diff_mask(lone([('green', spec)], extra=LIGHTMAP_OFF), empty_dark)
            outside = ~own
            poly = polygon_px(green)
            dist = outline_distance(green.shape, poly)
            parent_green = lone([('green', spec)], rev=self.parent)
            row = {'shape': name, 'bbox': green.info['pieces'][0]['bbox'],
                   'ninjaDistancePx': round(float(np.hypot(*(np.array(green.info['ninja']) - poly.mean(axis=0)))), 1),
                   'ownPixels': int(own.sum()), 'ownMaxDistancePx': round(float(dist[own].max()), 1),
                   'outsidePixels': int(outside.sum()), 'maxDelta': masked_delta(green, empty, outside),
                   'parentMaxDelta': masked_delta(parent_green, parent_empty, outside)}
            row['pass'] = row['maxDelta'] == 0
            print(row)
            rows.append(row)
        (EVIDENCE_DIR / 'green-dark.json').write_text(compact({
            'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev, 'parent': fx.harness(self.parent).rev,
            'mask': 'own pixels = diff with/without the green, lightmap disabled', 'greens': rows,
            'allPass': all(r['pass'] for r in rows)}))
        for r in rows:
            with self.subTest(shape=r['shape']):
                self.assertGreater(r['ninjaDistancePx'], 700)
                self.assertEqual(r['maxDelta'], 0)

    def test_3_green_shadows_the_blue_light(self):
        on = lone(SHADOW_PIECES)
        dark = lone(SHADOW_PIECES, extra=LIGHT_OFF)
        blue, green = polygon_px(on, 0), polygon_px(on, 1)
        cx, cy = blue.mean(axis=0)
        background = fx.background_mask(on) & fx.background_mask(dark)
        walls = fx.wall_mask(on)
        sx, sy = cx, green[:, 1].max() + SHADOW_BEHIND_PX
        mx, my = cx, 2 * cy - sy
        wall_below = next((y for y in range(int(sy), on.shape[0]) if walls[y, int(sx)]), None)
        shadow_on, n_shadow = patch(on, background, sx, sy)
        shadow_dark, _ = patch(dark, background, sx, sy)
        mirror_on, n_mirror = patch(on, background, mx, my)
        mirror_dark, _ = patch(dark, background, mx, my)
        shadow_gain, mirror_gain = shadow_on - shadow_dark, mirror_on - mirror_dark
        result = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev,
                  'blueBbox': on.info['pieces'][0]['bbox'], 'greenBbox': on.info['pieces'][1]['bbox'],
                  'wallBelowY': wall_below, 'behindPx': SHADOW_BEHIND_PX,
                  'shadowPoint': [round(sx, 1), round(sy, 1)], 'mirrorPoint': [round(mx, 1), round(my, 1)],
                  'samples': [n_shadow, n_mirror],
                  'shadowGain': round(shadow_gain, 5), 'mirrorGain': round(mirror_gain, 5),
                  'ratio': round(shadow_gain / mirror_gain, 4), 'lumRatio': round(shadow_on / mirror_on, 4),
                  'maxRatio': MAX_SHADOW_RATIO}
        result['pass'] = wall_below is not None and mirror_gain > 0.01 and result['ratio'] <= MAX_SHADOW_RATIO
        print(result)
        (EVIDENCE_DIR / 'blue-shadow.json').write_text(compact(result))
        self.assertIsNotNone(wall_below)
        self.assertGreater(mirror_gain, 0.01)
        self.assertLessEqual(result['ratio'], MAX_SHADOW_RATIO)

    def test_3b_walls_stop_the_blue_light(self):
        on = lone(LEAK_PIECES)
        dark = lone(LEAK_PIECES, extra=LIGHT_OFF)
        free = lone(LEAK_PIECES, extra=NO_SHADOWS)
        walls = fx.wall_mask(on)
        background = fx.background_mask(on) & fx.background_mask(dark)
        cx, cy = polygon_px(on).mean(axis=0)
        h, w = walls.shape
        samples = []
        for y in range(LEAK_GRID // 2, h, LEAK_GRID):
            for x in range(LEAK_GRID // 2, w, LEAK_GRID):
                if not background[y, x]:
                    continue
                if not all(crosses_wall(walls, (x + dx, y + dy), (cx, cy))
                           for dx, dy in ((0, 0), (LEAK_MARGIN, 0), (-LEAK_MARGIN, 0), (0, LEAK_MARGIN), (0, -LEAK_MARGIN))):
                    continue
                lum, _ = patch(on, background, x, y)
                base, _ = patch(dark, background, x, y)
                uncut, _ = patch(free, background, x, y)
                if None not in (lum, base, uncut):
                    samples.append((x, y, lum, base, uncut))
        deviations = [abs(l - b) / b for _, _, l, b, _ in samples]
        rises = [(u - b) / b for _, _, _, b, u in samples]
        result = {'scene': SCENE, 'viewport': list(VIEWPORT), 'tree': fx.harness().rev,
                  'blueBbox': on.info['pieces'][0]['bbox'], 'gridPx': LEAK_GRID, 'marginPx': LEAK_MARGIN,
                  'tolerance': LEAK_TOLERANCE, 'samples': len(samples),
                  'maxDeviation': round(max(deviations), 5) if samples else None,
                  'maxUnshadowedRise': round(max(rises), 4) if samples else None}
        result['leak'] = not samples or max(deviations) > LEAK_TOLERANCE
        print(result)
        (EVIDENCE_DIR / 'blue-wall-leak.json').write_text(compact(result))
        self.assertGreater(len(samples), 5)
        self.assertGreater(result['maxUnshadowedRise'], 0.1)
        self.assertLessEqual(result['maxDeviation'], LEAK_TOLERANCE)

    def test_4_switch_off_and_other_modes_equal_parent(self):
        rows = []
        pairs = {}
        for scene in fx.SCENES:
            for viewport in fx.VIEWPORTS:
                new = fx.capture(scene, viewport, fx_on=False)
                base = fx.capture(scene, viewport, fx_on=False, rev=self.parent)
                self.assertFalse(new.info['fx'])
                name = f'momentum-{scene}-{viewport[0]}x{viewport[1]}'
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
            'allIdentical': all(r['identical'] for r in rows), 'frames': rows}))
        self.assertEqual(len(rows), 16)
        for row in rows:
            with self.subTest(scene=row['scene']):
                if row['scene'] in pairs:
                    # TASK-122 crystal pieces: momentum scenes equal outside the blue pieces
                    fx.assert_equal_outside_pieces(*pairs[row['scene']])
                else:
                    self.assertEqual(row['maxDelta'], 0)

    def test_5_shots(self):
        shots = EVIDENCE_DIR / 'shots'
        frames = {}
        for scene in ('blue-corner', 'blue-hit'):
            frames[scene] = frame = fx.capture(scene, VIEWPORT, fx_on=True)
            fx.save_png(frame, shots / f'1280x720-{scene}.png')
            fx.compare_png(frame, fx.CONCEPTS[scene], shots / f'compare-{scene}.png',
                           labels=('new frame (blue area light)', 'concept'))
        for name, pieces in SHOT_PIECES.items():
            fx.save_png(lone(pieces, motes=True), shots / f'1280x720-{name}-blue.png')
        self.assertEqual(len(list(shots.glob('*.png'))), 6)


if __name__ == '__main__':
    unittest.main()
