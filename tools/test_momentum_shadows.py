"""Momentum lighting 4/17: hard shadows of the ninja light (TASK-054).

Every momentum piece and the walls (border bands and the TASK-044 wall
mass) cut the quads they sweep away from each light out of that light on
the low-resolution light canvas. On the reference scenes of
tools/momentum_fx_support.py this suite checks:
- shadows (mid-shaft, 1280x720): per green, shadowPoint is the background
  point 60 px past the green's far side on the ray from the ninja through its
  centre; mirrorPoint is at the same distance from the ninja in the nearest
  unoccluded direction (the ray clear of every piece by MIRROR_CLEARANCE px,
  searched from the mirrored direction outwards). Luminance is the mean over
  a PATCH px disc (2 PATCH where fewer than 20 are left) of background
  pixels, captured with the ambient motes hidden (they float in front of the
  cave); ratio shadow / mirror <= 0.45 for every green whose shadowPoint lies
  on visible background, at least 3 (lightRatio: the same with each point
  divided by its fx-off luminance, the cave texture taken out, reported only);
- wall leak (blue-corner and run-right, plus a variant of each with the
  ninja moved next to a wall corner so the area behind the wall lies inside
  the light radius): background samples on a grid whose rays to the ninja
  (and to the ninja from LEAK_MARGIN px around them) cross a wall have a
  luminance within 2% of the ambient-only frame (the ninja light and haze
  removed); unshadowedRise reports what the light would add there with the
  shadows disabled; blue area lights (TASK-055) are off in these frames, and
  the tree's are taken with LEAK_LATER_EFFECTS_OFF served in style.js (the
  TASK-058 lit motes take light unshadowed);
- perf: median and p95 of draw() + a 1 px readback over PERF_FRAMES frames
  of mid-shaft at 1280x720, parent vs tree (interleaved batches); tree
  median <= 1.25x parent median;
- switch off: the 4 scenes with MOMENTUM_FX off at both viewports and the
  classic and bad frames of test_visual_gallery with the switch on equal the
  parent commit (decoded maxDelta 0).

MOMENTUM_SHADOWS_EVIDENCE_DIR (default /tmp/momentum-shadows) receives
shadows.json, wall-leak.json, perf.json, switch-off-identical.json
(compact) and shots/ (mid-shaft, blue-corner, run-right at 1280x720,
mid-shaft at 390x844, compare-mid-shaft.png, compare-blue-corner.png).
MOMENTUM_SHADOWS_PARENT is the parent revision (default: the parent of the
commit that added this file, or HEAD while uncommitted).
Requires Playwright Chromium. No remote requests.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_ninja_light import gallery_frames

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_shadows.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_SHADOWS_EVIDENCE_DIR', '/tmp/momentum-shadows'))
BEHIND_PX = 60
PATCH = 6
# The ambient motes float in front of the cave and are not shadowed: the
# shadow captures hide them
NO_MOTES = '''() => { visualEffects.particles.drawAmbientMotes = () => {} }'''
MIRROR_CLEARANCE = 10
MAX_SHADOW_RATIO = 0.45
LEAK_TOLERANCE = 0.02
LEAK_GRID = 12
LEAK_MARGIN = 12
PERF_FRAMES = 300
# Later effects that are not the shadowed ninja light: the TASK-058 lit
# motes take light unshadowed (behind a wall too), so the wall-leak frames
# of the tree are taken with them off (style.js served with moteGain 0)
LEAK_LATER_EFFECTS_OFF = [('moteGain: 5', 'moteGain: 0')]
PERF_BATCH = 50
MAX_PERF_RATIO = 1.25
# The ninja light and haze removed: the ambient-only frame
NO_NINJA_LIGHT = '''() => {
    const lightmap = visualEffects.lightmap
    lightmap.collectMomentumLights = function() { this.momentumLights.length = 0; return this.momentumLights }
    lightmap.addMomentumHaze = () => {}
}'''
# Blue pieces emit no area light (trees before TASK-055 have none)
NO_BLUE_LIGHT = '''() => { const l = visualEffects.lightmap, collect = l.collectEmitters
    if (collect) l.collectEmitters = function(s) { const e = collect.call(this, s)
        for (let i = e.length - 1; i >= 0; --i) if (e[i].element) e.splice(i, 1)
        return e } }'''
# The light without any shadow (what would leak through the walls)
NO_SHADOWS = '''() => { const lightmap = visualEffects.lightmap
    lightmap.cutShadows = () => {}; lightmap.addDeepShadows = () => {} }'''
# Ninja next to a wall corner (canvas px of the 1280x720 frame; the scene's
# k converts): blue-corner under the overhang left of its corner, run-right
# above the floor left of the green, the down shaft past the floor's corner
NEAR_CORNER = {'blue-corner': (585, 395), 'run-right': (420, 640)}
MOVE_NINJA = '''([x, y]) => {
    const k = canvas.width / width * scale[version]
    ninja.x = x / k - screen.x; ninja.y = y / k - screen.y
    ninja.track.pos = [{x: ninja.x - 40, y: ninja.y}, {x: ninja.x, y: ninja.y}]
}'''
PERF_SCRIPT = r'''frames => {
    const now = () => Performance.prototype.now.call(performance)
    const probe = canvas.getContext('2d')
    const times = []
    for (let i = 0; i < frames; ++i) {
        const t0 = now()
        draw()
        probe.getImageData(0, 0, 1, 1)
        times.push(now() - t0)
    }
    return times
}'''
SHOTS = [('mid-shaft', (1280, 720)), ('blue-corner', (1280, 720)), ('run-right', (1280, 720)),
         ('mid-shaft', (390, 844))]


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_SHADOWS_PARENT'):
        return os.environ['MOMENTUM_SHADOWS_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def disc(shape, x, y, r):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    return np.hypot(xx + 0.5 - x, yy + 0.5 - y) <= r


def patch_luminance(frame, mask, x, y):
    """Mean luminance of mask pixels within PATCH px of (x, y) (2 * PATCH
    where fewer than 20 are left there), or None."""
    for r in (PATCH, 2 * PATCH):
        region = mask & disc(frame.shape, x, y, r)
        if region.sum() >= 20:
            return fx.region_luminance(frame, region)
    return None


def ray_exit(origin, direction, box):
    """Distance along the ray where it leaves box [x0, y0, x1, y1]."""
    t_far = math.inf
    for o, d, lo, hi in ((origin[0], direction[0], box[0], box[2]), (origin[1], direction[1], box[1], box[3])):
        if abs(d) > 1e-9:
            t_far = min(t_far, max((lo - o) / d, (hi - o) / d))
    return t_far


def segment_hits_box(a, b, box, pad):
    """Whether segment a-b passes within pad px of box."""
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    for i in range(65):
        t = i / 64
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def shadow_metrics(on, off):
    background = fx.background_mask(on) & fx.background_mask(off)
    nx, ny = on.info['ninja']
    h, w = on.shape[:2]
    boxes = [p['bbox'] for p in on.info['pieces']]
    rows = []
    for index, piece in enumerate(on.info['pieces']):
        if piece['kind'] != 'green':
            continue
        b = piece['bbox']
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        angle = math.atan2(cy - ny, cx - nx)
        direction = (math.cos(angle), math.sin(angle))
        dist = ray_exit((nx, ny), direction, b) + BEHIND_PX
        sx, sy = nx + direction[0] * dist, ny + direction[1] * dist
        shadow = patch_luminance(on, background, sx, sy)
        if shadow is None:
            # The shadow point is off screen or not on the cave background
            rows.append({'piece': index, 'bbox': b, 'shadowPoint': [round(sx, 1), round(sy, 1)],
                         'skipped': 'shadowPoint not on visible background'})
            continue
        mirror_angle = math.pi - angle
        mirror = None
        for step in range(0, 180):
            for sign in (1, -1):
                a = mirror_angle + sign * math.radians(step)
                mx, my = nx + math.cos(a) * dist, ny + math.sin(a) * dist
                if not (PATCH < mx < w - PATCH and PATCH < my < h - PATCH):
                    continue
                if any(segment_hits_box((nx, ny), (mx, my), box, MIRROR_CLEARANCE) for box in boxes):
                    continue
                lum = patch_luminance(on, background, mx, my)
                if lum is not None:
                    mirror = (mx, my, lum, math.degrees(a))
                    break
            if mirror:
                break
        shadow_off = patch_luminance(off, background, sx, sy)
        mirror_off = patch_luminance(off, background, mirror[0], mirror[1])
        rows.append({
            'piece': index, 'bbox': b, 'distance': round(dist, 1),
            'shadowPoint': [round(sx, 1), round(sy, 1)], 'mirrorPoint': [round(mirror[0], 1), round(mirror[1], 1)],
            'mirrorAngleDeg': round(mirror[3], 1),
            'shadowLum': round(shadow, 5), 'mirrorLum': round(mirror[2], 5),
            'ratio': round(shadow / mirror[2], 4),
            'lightRatio': round((shadow / shadow_off) / (mirror[2] / mirror_off), 4),
        })
    return rows


def crosses_wall(walls, a, b):
    """Whether the segment a-b (canvas px) crosses a wall pixel."""
    n = int(math.hypot(b[0] - a[0], b[1] - a[1]))
    h, w = walls.shape
    for i in range(1, n):
        x = int(a[0] + (b[0] - a[0]) * i / n)
        y = int(a[1] + (b[1] - a[1]) * i / n)
        if 0 <= x < w and 0 <= y < h and walls[y, x]:
            return True
    return False


def leak_metrics(on, ambient, unshadowed):
    walls = fx.wall_mask(on)
    background = fx.background_mask(on) & fx.background_mask(ambient)
    nx, ny = on.info['ninja']
    h, w = on.shape[:2]
    samples = []
    for y in range(LEAK_GRID // 2, h, LEAK_GRID):
        for x in range(LEAK_GRID // 2, w, LEAK_GRID):
            if not background[y, x]:
                continue
            if not all(crosses_wall(walls, (x + dx, y + dy), (nx, ny))
                       for dx, dy in ((0, 0), (LEAK_MARGIN, 0), (-LEAK_MARGIN, 0), (0, LEAK_MARGIN), (0, -LEAK_MARGIN))):
                continue
            lum = patch_luminance(on, background, x, y)
            base = patch_luminance(ambient, background, x, y)
            free = patch_luminance(unshadowed, background, x, y)
            if lum is None or base is None or free is None:
                continue
            samples.append((x, y, lum, base, free))
    deviations = [abs(lum - base) / base for _, _, lum, base, _ in samples]
    rises = [(free - base) / base for _, _, _, base, free in samples]
    worst = int(np.argmax(deviations)) if samples else None
    return {
        'samples': len(samples), 'ninja': [round(nx, 1), round(ny, 1)],
        'maxDeviation': round(max(deviations), 5) if samples else None,
        'worstSample': [samples[worst][0], samples[worst][1]] if samples else None,
        'maxUnshadowedRise': round(max(rises), 4) if samples else None,
        'leak': bool(samples) and max(deviations) > LEAK_TOLERANCE,
    }


def stats(times):
    ordered = sorted(times)
    return {'frames': len(times), 'median': round(float(np.median(ordered)), 3),
            'p95': round(float(np.percentile(ordered, 95)), 3), 'mean': round(float(np.mean(ordered)), 3)}


class MomentumShadowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()

    @classmethod
    def tearDownClass(cls):
        fx.close()

    def test_0_greens_cast_shadows(self):
        on = fx.capture('mid-shaft', (1280, 720), fx_on=True, extra_js=NO_MOTES)
        off = fx.capture('mid-shaft', (1280, 720), fx_on=False, extra_js=NO_MOTES)
        rows = shadow_metrics(on, off)
        skipped = [r for r in rows if 'skipped' in r]
        rows = [r for r in rows if 'skipped' not in r]
        for r in rows:
            print('green', r['piece'], 'ratio', r['ratio'], 'lightRatio', r['lightRatio'],
                  'shadow', r['shadowPoint'], 'mirror', r['mirrorPoint'])
        all_pass = len(rows) >= 3 and all(r['ratio'] <= MAX_SHADOW_RATIO for r in rows)
        (EVIDENCE_DIR / 'shadows.json').write_text(compact({
            'scene': 'mid-shaft', 'viewport': [1280, 720], 'tree': fx.harness().rev, 'ninja': on.info['ninja'],
            'motes': 'hidden', 'behindPx': BEHIND_PX, 'patchPx': PATCH, 'maxRatio': MAX_SHADOW_RATIO, 'greens': rows,
            'skipped': skipped,
            'allPass': all_pass}))
        self.assertGreaterEqual(len(rows), 3)
        for r in rows:
            with self.subTest(piece=r['piece']):
                self.assertLessEqual(r['ratio'], MAX_SHADOW_RATIO)

    def test_1_no_light_through_walls(self):
        tree = fx.harness()
        later_off = [patch for patch in LEAK_LATER_EFFECTS_OFF if patch[0] in (tree.root / 'style.js').read_text()]
        leak_harness = fx.FxHarness('worktree', tree.browser, style_patch=later_off) if later_off else tree
        try:
            self.check_leaks(leak_harness, [patch[1] for patch in later_off])
        finally:
            if leak_harness is not tree:
                leak_harness.close()

    def check_leaks(self, harness, later_off):
        rows = []
        for scene in ('blue-corner', 'run-right'):
            for variant in ('scene', 'near-corner'):
                move = '' if variant == 'scene' else \
                    f'(() => ({MOVE_NINJA})({list(NEAR_CORNER[scene])}))();'
                # The ninja light only: blue area lights (TASK-055, tested by
                # test_momentum_blue_light) are off in all three frames
                def js(extra):
                    body = extra.strip()
                    return f'() => {{ {move} ({NO_BLUE_LIGHT})(); ({body})() }}'
                on = harness.capture(scene, (1280, 720), extra_js=js('() => {}'))
                ambient = harness.capture(scene, (1280, 720), extra_js=js(NO_NINJA_LIGHT))
                unshadowed = harness.capture(scene, (1280, 720), extra_js=js(NO_SHADOWS))
                metrics = leak_metrics(on, ambient, unshadowed)
                metrics.update(scene=scene, variant=variant)
                rows.append(metrics)
                print(scene, variant, metrics)
                if variant == 'near-corner':
                    fx.save_png(on, EVIDENCE_DIR / 'leak-frames' / f'{scene}-near-corner.png')
        (EVIDENCE_DIR / 'wall-leak.json').write_text(compact({
            'viewport': [1280, 720], 'tree': fx.harness().rev, 'tolerance': LEAK_TOLERANCE, 'gridPx': LEAK_GRID,
            'marginPx': LEAK_MARGIN, 'laterEffectsOff': later_off, 'results': rows, 'leak': any(r['leak'] for r in rows)}))
        for scene in ('blue-corner', 'run-right'):
            self.assertGreater(sum(r['samples'] for r in rows if r['scene'] == scene), 20, scene)
        for r in rows:
            with self.subTest(scene=r['scene'], variant=r['variant']):
                if r['samples']:
                    self.assertLessEqual(r['maxDeviation'], LEAK_TOLERANCE)
                self.assertFalse(r['leak'])
        # The near-corner variants put lit area behind the walls: the
        # shadows, not the radius, keep it dark
        self.assertTrue(any(r['maxUnshadowedRise'] > 0.1 for r in rows if r['variant'] == 'near-corner'))

    def test_2_perf(self):
        pages = {}
        try:
            for name, rev in (('parent', self.parent), ('tree', 'worktree')):
                context, page = fx.harness(rev).open((1280, 720))
                pages[name] = (context, page)
                page.evaluate(fx.BUILD, [fx.SCENE_SPECS['mid-shaft'], True])
                page.evaluate(PERF_SCRIPT, 30)
            times = {'parent': [], 'tree': []}
            for _ in range(PERF_FRAMES // PERF_BATCH):
                for name in times:
                    times[name] += pages[name][1].evaluate(PERF_SCRIPT, PERF_BATCH)
            for name, (_, page) in pages.items():
                self.assertEqual(page.errors, [], name)
        finally:
            for context, _ in pages.values():
                context.close()
        result = {'scene': 'mid-shaft', 'viewport': [1280, 720], 'fx': True, 'parent': fx.harness(self.parent).rev,
                  'tree': fx.harness().rev, 'parentMs': stats(times['parent']), 'treeMs': stats(times['tree'])}
        result['medianRatio'] = round(result['treeMs']['median'] / result['parentMs']['median'], 4)
        result['pass'] = result['medianRatio'] <= MAX_PERF_RATIO
        (EVIDENCE_DIR / 'perf.json').write_text(compact(result))
        print('perf', result)
        self.assertEqual(len(times['tree']), PERF_FRAMES)
        self.assertLessEqual(result['medianRatio'], MAX_PERF_RATIO)

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
        for scene, viewport in SHOTS:
            frames[scene, viewport] = frame = fx.capture(scene, viewport, fx_on=True)
            fx.save_png(frame, shots / f'{viewport[0]}x{viewport[1]}-{scene}.png')
        for scene in ('mid-shaft', 'blue-corner'):
            fx.compare_png(frames[scene, (1280, 720)], fx.CONCEPTS[scene], shots / f'compare-{scene}.png',
                           labels=('new frame (shadows)', 'concept'))
        self.assertEqual(len(list(shots.glob('*.png'))), 6)


if __name__ == '__main__':
    unittest.main()
