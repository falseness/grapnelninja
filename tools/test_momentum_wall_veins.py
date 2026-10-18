"""Momentum lighting 14/17: crystal veins in the shaft walls (TASK-064).

With MOMENTUM_FX on, WALL_VEINS.draw (render/wallveins.js, called from
drawMomentumOutsideMask before the borders' caps and neon faces) adds thin
angular veins inside the corridor's wall bodies (MomentumBorder bands between
the cap and the back): world-anchored squares of the wall thickness, each a
cached tile seeded from its world position, masked by the frame's lights
(unshadowed, STYLE.momentumFx.veins.reach / gain). Checks
(tools/momentum_fx_support.py scenes; "no veins" = the same scene with the
WALL_VEINS.enabled test hook off, each frame from its own page):
- veins.json:
  lit: blue-corner at 1280x720 and mid-shaft at 390x844: vein pixels
  (decoded maxDelta > 0 against the no-veins frame) inside the wall-body mask
  (the corridor borders' getShapePath filled in the page, alpha > 0) > 0
  within NEAR_PX of the ninja (blue-corner), 0 farther than FAR_PX from every
  light of the frame (lightmap.momentumLights, canvas px), 0 outside the
  wall-body mask; a second capture of each veins frame has maxDelta 0;
  anchored: one page (blue-corner, 1280x720, WALL_VEINS.fullLight: veins
  unmasked) reads the vein canvas (WALL_VEINS.work), moves the camera by
  SHIFT whole canvas px and reads it again: inside the overlap the second
  equals the first shifted by SHIFT (veins alpha > 0 IoU >= MIN_IOU, mean
  alpha delta <= MAX_MEAN_DELTA) and differs from it unshifted (the layout
  moves with the world); a redraw at the same camera builds no tile;
- collision-identical.json: the TASK-050 scripted 20 s momentum run (R U R D
  R course, 1200 ticks, ninja steered past both faces) on the tree and the
  parent: per-cycle ninja x/y/speedX/speedY and every border's getLines()
  (logged whenever the set changes) identical;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  harness viewports and the classic and bad test_visual_gallery frames with
  the switch on equal the parent commit (decoded maxDelta 0);
- shots/: blue-corner at 1280x720, a 2x crop of the overhang wall over the
  ninja, mid-shaft at 390x844, compare-blue-corner.png (vs concept
  9-wall-veins.png).
MOMENTUM_WALL_VEINS_EVIDENCE_DIR (default /tmp/momentum-wall-veins) receives
the json files (compact) and shots/. MOMENTUM_WALL_VEINS_PARENT is the parent
revision (default: the parent of the commit that added this file, or HEAD
while uncommitted). Requires Playwright Chromium. No remote requests.
"""
import base64
import hashlib
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
from browser_test_support import wait_for_boot_run
import momentum_fx_support as fx
import render_snapshot
from test_momentum_borders import SEED_COURSE
from test_momentum_ninja_light import gallery_frames
from test_momentum_patterns_turn import SCRIPT

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_wall_veins.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_WALL_VEINS_EVIDENCE_DIR', '/tmp/momentum-wall-veins'))
LIT_CASES = [('blue-corner', (1280, 720)), ('mid-shaft', (390, 844))]
NEAR_PX = 150
FAR_PX = 500
SHIFT = (-37, 23)
MIN_IOU = 0.99
MAX_MEAN_DELTA = 0.5
TICKS = 1200
CONCEPT = fx.CONCEPT_DIR / '9-wall-veins.png'
NO_VEINS = '() => { WALL_VEINS.enabled = false }'

# The corridor borders' bodies (the WALL_VEINS input) filled into a canvas,
# and the frame's lights, in canvas px
BODIES = r'''() => {
    const k = canvas.width / width * scale[version]
    const segments = momentumOutsideCells().segments
    const mask = document.createElement('canvas')
    mask.width = canvas.width; mask.height = canvas.height
    const c = mask.getContext('2d')
    c.setTransform(k, 0, 0, k, 0, 0)
    c.fillStyle = '#ffffff'
    let borders = 0
    for (const f of floors)
        if (f instanceof MomentumBorderFloor)
            for (const e of f.elements)
                if (segments.includes(e.line.segment)) { c.fill(e.getShapePath()); ++borders }
    const lights = visualEffects.lightmap.momentumLights.map(l => ({x: l.x * k, y: l.y * k,
        kind: l.element ? 'blue' : (l.gradient === visualEffects.lightmap.momentumGradient ? 'ninja' : 'other')}))
    return {mask: mask.toDataURL('image/png'), borders: borders, lights: lights,
            tileBuilds: WALL_VEINS.builds, veinFrames: WALL_VEINS.frames, box: WALL_VEINS.box}
}'''

# The vein canvas (fullLight) at the camera moved by [dx, dy] canvas px
VEIN_CANVAS = r'''([dx, dy]) => {
    const k = canvas.width / width * scale[version]
    if (window.__veinX === undefined) { window.__veinX = screen.x; window.__veinY = screen.y }
    screen.x = window.__veinX + dx / k; screen.y = window.__veinY + dy / k
    screen.leftWall.update(screen)
    for (const f of floors)
        if (f instanceof MomentumBorderFloor)
            f.replenishElements()
    WALL_VEINS.fullLight = true
    draw()
    const builds = WALL_VEINS.builds
    draw()
    return {veins: WALL_VEINS.work.toDataURL('image/png'), box: WALL_VEINS.box,
            buildsFirstDraw: builds, buildsRedraw: WALL_VEINS.builds - builds, screen: [screen.x, screen.y]}
}'''

# TASK-050 scripted run (artifacts/TASK-050/scripts/collision.py)
RUN = r'''([ticks]) => {
    let a = 777
    Math.random = () => { a = (a * 1103515245 + 12345) % 2147483648; return a / 2147483648 }
    startGame('momentum'); cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const clear = () => { for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor) f.elements = [] }
    const course = momentumCourse
    const segs = course.take(6)
    const arcStart = [0]
    for (const s of segs) arcStart.push(arcStart[arcStart.length - 1] + Math.hypot(s.x1 - s.x0, s.y1 - s.y0))
    const goal = arcStart[4] + 0.5 * (arcStart[5] - arcStart[4])
    const step = goal / (ticks - 100)
    const cycles = [], lineLog = []
    const calc = calcPhysics
    calcPhysics = function() { calc.apply(this, arguments)
        cycles.push([ninja.x, ninja.y, ninja.speedX, ninja.speedY]) }
    let arc = 0, last = ''
    try {
        for (let k = 0; k < ticks; ++k) {
            clear()
            arc = Math.min(goal, arc + step)
            let i = 0
            while (arcStart[i + 1] <= arc) ++i
            const s = segs[i], d = momentumDirection(s.dir), n = momentumSideNormal(s.dir, 1)
            const half = momentumSegmentHalfWidth(s)
            const along = arc - arcStart[i]
            const lat = 1.6 * half * (Math.floor(k / 60) % 2 ? 1 : -1)
            const tx = s.x0 + d.x * along + n.x * lat, ty = s.y0 + d.y * along + n.y * lat
            const dx = tx - ninja.x, dy = ty - ninja.y, dist = Math.hypot(dx, dy) || 1
            grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
            ninja.invulnerableMs = 1e9
            ninja.speedX = 2.5 * dx / dist; ninja.speedY = 2.5 * dy / dist
            physics()
            draw()
            const lines = []
            for (const f of floors) if (f instanceof MomentumBorderFloor)
                for (const e of f.elements) lines.push([e.line.segment, e.line.side, e.getLines()])
            const key = JSON.stringify(lines)
            if (key != last) { lineLog.push([k, lines]); last = key }
        }
    } finally { calcPhysics = calc }
    return {cycles, lineLog, segmentIndex: screen.segmentIndex, borderTouches: momentumState.borderTouches,
            joins: segs.slice(0, 5).map(s => s.dir),
            veinFrames: typeof WALL_VEINS != 'undefined' ? WALL_VEINS.frames : null}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_WALL_VEINS_PARENT'):
        return os.environ['MOMENTUM_WALL_VEINS_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def data_url_alpha(url):
    """Alpha channel (0..255) of a canvas toDataURL PNG."""
    data = base64.b64decode(url.split(',', 1)[1])
    return np.asarray(Image.open(io.BytesIO(data)).convert('RGBA'))[..., 3]


def diff(a, b):
    return np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).max(axis=2)


def capture(scene, viewport, extra_js=None, bodies=False):
    """(Frame, page info) of scene at viewport from its own page."""
    context, page = fx.harness().open(viewport)
    try:
        page.evaluate(fx.BUILD, [fx.SCENE_SPECS[scene], True])
        if extra_js:
            page.evaluate(extra_js)
        info = page.evaluate(fx.DRAW)
        png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        extra = page.evaluate(BODIES) if bodies else None
        if page.errors:
            raise RuntimeError(f'page errors in {scene} {viewport}: {page.errors}')
    finally:
        context.close()
    info.update(scene=scene, viewport=list(viewport))
    return fx.Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info), extra


def collision_run(harness):
    context = harness.browser.new_context(viewport={'width': 1280, 'height': 720})
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(harness.url + 'index.html')
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE, SCRIPT)
        result = page.evaluate(RUN, [TICKS])
        if errors:
            raise RuntimeError(f'page errors: {errors}')
        return result
    finally:
        context.close()


class MomentumWallVeinsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'veins.json').write_text(compact(cls.result))
        fx.close()

    def test_0_veins_lit_only_near_lights(self):
        rows = []
        for scene, vp in LIT_CASES:
            on, extra = capture(scene, vp, bodies=True)
            again, _ = capture(scene, vp)
            off, _ = capture(scene, vp, extra_js=NO_VEINS)
            veins = diff(on, off) > 0
            body = data_url_alpha(extra['mask']) > 0
            h, w = veins.shape
            yy, xx = np.mgrid[0:h, 0:w]
            nx, ny = on.info['ninja']
            near = np.hypot(xx - nx, yy - ny) < NEAR_PX
            nearest = np.full((h, w), np.inf)
            for light in extra['lights']:
                nearest = np.minimum(nearest, np.hypot(xx - light['x'], yy - light['y']))
            far = nearest > FAR_PX
            inside = veins & body
            row = {'scene': scene, 'viewport': list(vp), 'canvas': on.info['canvas'], 'borders': extra['borders'],
                   'bodyPixels': int(body.sum()), 'veinPixels': int(veins.sum()),
                   'veinPixelsInBodies': int(inside.sum()), 'veinPixelsOutsideBodies': int((veins & ~body).sum()),
                   'veinPixelsNearNinja': int((inside & near).sum()), 'nearPx': NEAR_PX,
                   'veinPixelsBeyondFarFromEveryLight': int((veins & far).sum()), 'farPx': FAR_PX,
                   'bodyPixelsBeyondFar': int((body & far).sum()),
                   'lights': [{'kind': l['kind'], 'x': round(l['x'], 1), 'y': round(l['y'], 1)} for l in extra['lights']],
                   'maxVeinLift': int(diff(on, off).max()), 'twoRunsMaxDelta': fx.max_delta(on, again),
                   'veinFrames': extra['veinFrames'], 'tileBuilds': extra['tileBuilds']}
            if veins.any():
                vy, vx = np.nonzero(veins)
                row['veinMaxDistanceFromNearestLight'] = round(float(nearest[vy, vx].max()), 1)
            row['pass'] = (row['veinPixelsInBodies'] > 0 and row['veinPixelsOutsideBodies'] == 0
                           and row['veinPixelsBeyondFarFromEveryLight'] == 0 and row['twoRunsMaxDelta'] == 0
                           and (scene != 'blue-corner' or row['veinPixelsNearNinja'] > 0))
            rows.append(row)
            print('lit', {k: v for k, v in row.items() if k != 'lights'})
        self.result['lit'] = rows
        for row in rows:
            with self.subTest(scene=row['scene']):
                self.assertGreater(row['veinPixelsInBodies'], 0)
                self.assertEqual(row['veinPixelsOutsideBodies'], 0)
                self.assertEqual(row['veinPixelsBeyondFarFromEveryLight'], 0)
                self.assertEqual(row['twoRunsMaxDelta'], 0)
                if row['scene'] == 'blue-corner':
                    self.assertGreater(row['veinPixelsNearNinja'], 0)
                    self.assertGreater(row['bodyPixelsBeyondFar'], 0)

    def test_1_veins_world_anchored(self):
        context, page = fx.harness().open((1280, 720))
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS['blue-corner'], True])
            first = page.evaluate(VEIN_CANVAS, [0, 0])
            second = page.evaluate(VEIN_CANVAS, list(SHIFT))
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        a = data_url_alpha(first['veins']).astype(np.int16)
        b = data_url_alpha(second['veins']).astype(np.int16)
        dx, dy = SHIFT
        h, w = a.shape
        # b(x + dx, y + dy) should equal a(x, y)
        ys = slice(max(0, -dy), min(h, h - dy))
        xs = slice(max(0, -dx), min(w, w - dx))
        a_part = a[ys, xs]
        b_part = b[ys.start + dy:ys.stop + dy, xs.start + dx:xs.stop + dx]
        va, vb = a_part > 0, b_part > 0
        iou = float((va & vb).sum() / max(1, (va | vb).sum()))
        unshifted = b[ys, xs] > 0
        iou_unshifted = float((va & unshifted).sum() / max(1, (va | unshifted).sum()))
        delta = np.abs(a_part - b_part)
        result = {'scene': 'blue-corner', 'viewport': [1280, 720], 'shiftCanvasPx': list(SHIFT),
                  'veinPixelsFirst': int((a > 0).sum()), 'veinPixelsSecond': int((b > 0).sum()),
                  'overlapVeinPixels': int(va.sum()), 'iouShifted': round(iou, 5),
                  'iouUnshifted': round(iou_unshifted, 5), 'meanAlphaDelta': round(float(delta.mean()), 4),
                  'maxAlphaDelta': int(delta.max()), 'differingPixels': int((delta > 0).sum()),
                  'tileBuildsFirstDraw': first['buildsFirstDraw'], 'tileBuildsOnRedraw': [first['buildsRedraw'],
                                                                                     second['buildsRedraw']]}
        result['pass'] = (result['overlapVeinPixels'] > 1000 and iou >= MIN_IOU
                          and result['meanAlphaDelta'] <= MAX_MEAN_DELTA and iou_unshifted < 0.5
                          and result['tileBuildsOnRedraw'] == [0, 0])
        self.result['anchored'] = result
        print('anchored', result)
        self.assertGreater(result['overlapVeinPixels'], 1000)
        self.assertGreaterEqual(iou, MIN_IOU)
        self.assertLessEqual(result['meanAlphaDelta'], MAX_MEAN_DELTA)
        self.assertLess(iou_unshifted, 0.5)
        self.assertEqual(result['tileBuildsOnRedraw'], [0, 0])

    def test_2_collision_identical_to_parent(self):
        runs = {}
        for name, rev in (('tree', 'worktree'), ('parent', self.parent)):
            harness = fx.harness(rev)
            runs[name] = (harness.rev, collision_run(harness))
        sha = lambda v: hashlib.sha256(json.dumps(v).encode()).hexdigest()
        tree, parent = runs['tree'][1], runs['parent'][1]
        differing = sum(1 for p, q in zip(tree['cycles'], parent['cycles']) if p != q)
        side = lambda name, r: {'rev': runs[name][0], 'cycles': len(r['cycles']), 'cyclesSha': sha(r['cycles']),
                                'linesSha': sha(r['lineLog']), 'lineChanges': len(r['lineLog']),
                                'segmentIndex': r['segmentIndex'], 'borderTouches': r['borderTouches'],
                                'joins': r['joins'], 'veinFrames': r['veinFrames']}
        result = {'identical': tree['cycles'] == parent['cycles'] and tree['lineLog'] == parent['lineLog'],
                  'ticks': TICKS, 'seconds': TICKS / 60, 'cyclesCompared': len(tree['cycles']),
                  'differingCycles': differing, 'cycleCountsEqual': len(tree['cycles']) == len(parent['cycles']),
                  'lineSnapshotsCompared': len(tree['lineLog']), 'linesEqual': tree['lineLog'] == parent['lineLog'],
                  'tree': side('tree', tree), 'parent': side('parent', parent),
                  'script': 'TASK-050 scripted run (artifacts/TASK-050/scripts/collision.py) plus a draw() per '
                            'tick so the veins render during the run'}
        (EVIDENCE_DIR / 'collision-identical.json').write_text(compact(result))
        print('collision', {k: v for k, v in result.items() if k not in ('tree', 'parent')},
              result['tree']['borderTouches'], result['tree']['veinFrames'])
        self.assertGreater(tree['borderTouches'], 0)
        self.assertGreater(tree['veinFrames'], 0)
        self.assertTrue(result['identical'])

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
        frame = fx.capture('blue-corner', (1280, 720))
        fx.save_png(frame, shots / '1280x720-blue-corner.png')
        fx.compare_png(frame, CONCEPT, shots / 'compare-blue-corner.png',
                       labels=('new frame (blue-corner, wall veins)', 'concept'))
        # The overhang (ceiling) wall above and right of the ninja, 2x
        nx, ny = (int(v) for v in frame.info['ninja'])
        x0 = max(0, min(frame.shape[1] - 400, nx - 60))
        y0 = max(0, ny - 230)
        crop = Image.fromarray(np.asarray(frame[y0:y0 + 240, x0:x0 + 400], dtype=np.uint8))
        crop.resize((crop.width * 2, crop.height * 2), Image.NEAREST).save(shots / 'overhang-wall-near-ninja-2x.png')
        fx.save_png(fx.capture('mid-shaft', (390, 844)), shots / '390x844-mid-shaft.png')
        self.assertEqual(len(list(shots.glob('*.png'))), 4)


if __name__ == '__main__':
    unittest.main()
