"""Momentum blue touch ring (TASK-077): every blue touch plays the death ring
(ScreenEffects.triggerRing) where the ninja touched it, without the shake.

The frame-stepped touch of tools/test_momentum_blue.py (frozen clock,
momentum_fx_support scene, physics() per step, draw()) at FRAME_MS per frame
so +140/+210/+280/+420 ms fall on frames. The rings' arc calls in the main
canvas pass (strokeShockwaves at shockwaveLineWidth) are recorded with the
context matrix: the arc centre (view units) must be world + screen, cx/cy are
that x k in canvas px and the matrix-mapped centre is within MATRIX_PX of them.
The camera is moved CAMERA_DRIFT world units per frame on top of physics
after the touch.

- test_ring_trace_world_anchored: one touch (hp 5): one world ring; on every
  frame of RING_MS after it the drawn centre equals (world + screen) * k,
  radius and alpha follow the death formula (exact at +0/+210, gone at +420
  like a death ring), shakeUntil never changes;
- test_n_touches_n_rings: N scripted non-lethal touches (onNinjaPass) within
  shockwaveDurationMs push N rings, shakeUntil unchanged;
- test_lethal_touch_one_ring: a touch at hp 1 runs the real death flow:
  exactly 1 ring (the screen-anchored death ring) and the shake starts;
- test_classic_bad_death_identical: a scripted death (onLethalDeath) in
  classic and bad mode, frames at +0/+140/+280 ms, decoded pixels equal the
  parent commit.

Writes to MOMENTUM_BLUE_RING_EVIDENCE_DIR (default /tmp/momentum-blue-ring):
ring-trace.json (compact {nonLethal: [rows], lethal: [rows]}),
classic-bad-death.json, shots/ (touch +0/+140/+280 ms at 1280x720, +140 ms at
390x844, a death at +140 ms, ring-crop-touch-vs-death-plus140.png: 2x crops
round the touch ring and the death ring at +140 ms side by side). MOMENTUM_BLUE_RING_PARENT: the parent revision
(default: the parent of the commit that added this file, or HEAD while
uncommitted). Requires Playwright Chromium. No remote requests.
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
from test_momentum_blue import TOUCH_SPEC

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_blue_ring.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_RING_EVIDENCE_DIR', '/tmp/momentum-blue-ring'))
FRAME_MS = 17.5
RING_MS = 450
MAX_FRAMES = 120
# World units the camera is moved per frame after the touch
CAMERA_DRIFT = (-3, -2)
N_TOUCHES = 3
# Canvas px the Chromium context matrix may drift from the nominal scale k
# (float32 matrix: 0.30303063 for k 0.30303030 at 1280x720)
MATRIX_PX = 0.01
# Crop (canvas px) round the ring centre, upscaled CROP_ZOOM x, for the
# side-by-side touch/death shot
CROP = 200
CROP_ZOOM = 2
CROPS = {}
SHOTS = {0: 'touch-plus0.png', 8: 'touch-plus140.png', 16: 'touch-plus280.png'}

INIT = r'''([frameMs, hp]) => {
    const fl = floors.find(f => f instanceof MomentumPatternFloor)
    const blue = fl.elements.find(e => e instanceof MomentumBlue)
    const fxs = visualEffects.screenEffects
    momentumState.hp = hp
    ninja.invulnerableMs = 0
    // The camera stays on the built scene (as in test_momentum_blue): the
    // rail camera's first move would take the view off the touch (TASK-086 N2)
    screen.shouldStartMove = () => false
    const t = window.__t = {fl, blue, touch: null, frame: 0, arcs: [], frameMs,
        steps: Math.max(1, Math.round(frameMs / physicsStepMs))}
    const pass = blue.onNinjaPass
    blue.onNinjaPass = function(who) {
        const used = this.passThrough, x = who.x, y = who.y
        pass.apply(this, arguments)
        if (!used && this.passThrough)
            t.touch = {ms: performance.now(), x, y}
    }
    // Arcs of the main-canvas ring pass (the full-alpha stroke)
    const stroke = ScreenEffects.prototype.strokeShockwaves
    ScreenEffects.prototype.strokeShockwaves = function(context, now, lineWidth, alpha) {
        t.inRing = context === fxs.ctx && lineWidth === STYLE.screenEffects.shockwaveLineWidth && alpha === 1
        try { return stroke.apply(this, arguments) } finally { t.inRing = false }
    }
    const arc = CanvasRenderingContext2D.prototype.arc
    CanvasRenderingContext2D.prototype.arc = function(x, y, r) {
        if (t.inRing) {
            const m = this.getTransform()
            t.arcs.push({x, y, r, mx: m.a * x + m.c * y + m.e, my: m.b * x + m.d * y + m.f,
                         alpha: this.globalAlpha})
        }
        return arc.apply(this, arguments)
    }
    const c = STYLE.screenEffects
    return {hp: momentumState.hp, startRadius: c.shockwaveStartRadius, endRadius: c.shockwaveEndRadius,
            durationMs: c.shockwaveDurationMs, alpha: c.shockwaveAlpha,
            stable: STYLE.visualStability.stableBrightness ? STYLE.visualStability.stableEffectAlphaMultiplier : 1,
            shake: QUALITY.screenShake, apply: fxs.shouldApply()}
}'''

# One frame: clock + frameMs, physics per step, camera drift once touched, draw
FRAME = r'''([drift]) => {
    const t = window.__t, fxs = visualEffects.screenEffects
    __snap.now += t.frameMs
    const touched = t.touch !== null
    for (let s = 0; s < t.steps; ++s)
        physics()
    if (t.touch !== null) {
        screen.x += drift[0]; screen.y += drift[1]
    }
    t.arcs = []
    draw()
    const k = canvas.width / width * scale[version]
    return {frame: t.frame++, ms: performance.now(), touchFrame: !touched && t.touch !== null,
            touch: t.touch, rings: fxs.shockwaves.length, worldRings: fxs.shockwaves.filter(s => s.world).length,
            arcs: t.arcs, screenX: screen.x, screenY: screen.y, k, shakeUntil: fxs.shakeUntil,
            version, hp: momentumState.hp}
}'''

# N scripted touches on fresh blues at the ninja, one per call
SCRIPTED_TOUCH = r'''() => {
    const fxs = visualEffects.screenEffects
    __snap.now += 50
    const blue = MomentumBlue.box(ninja.x - 5, ninja.y - 5, 10, 10)
    blue.onNinjaPass(ninja)
    return {rings: fxs.shockwaves.length, world: fxs.shockwaves.filter(s => s.world).length,
            shakeUntil: fxs.shakeUntil, hp: momentumState.hp, x: ninja.x, y: ninja.y,
            last: fxs.shockwaves[fxs.shockwaves.length - 1]}
}'''

# Math.random is reseeded before startGame(mode): FxHarness.open() starts
# momentum first, and how many draws its spawner takes is not a classic/bad
# matter (TASK-111's spawn change shifted the classic/bad course otherwise)
DEATH_START = '''(mode) => {
    let a = 12345
    Math.random = () => {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    startGame(mode); cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    for (let i = 0; i < 30; ++i) { __snap.now += 1000 / 60; physics() }
    ninja.invulnerableMs = 0
    onLethalDeath()
    const fxs = visualEffects.screenEffects
    draw()
    return {version, rings: fxs.shockwaves.length, shaking: performance.now() < fxs.shakeUntil}
}'''
DEATH_ADVANCE = '''(ms) => { __snap.now += ms; draw(); return visualEffects.screenEffects.shockwaves.length }'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_BLUE_RING_PARENT'):
        return os.environ['MOMENTUM_BLUE_RING_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


def decode(page):
    png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGB'))


def death_formula(init, age):
    """Radius (view units, x k for canvas px) and alpha of a death ring age ms old, None once over."""
    if age >= init['durationMs']:
        return None
    p = age / max(1, init['durationMs'])
    eased = 1 - (1 - p) ** 2
    radius = init['startRadius'] + (init['endRadius'] - init['startRadius']) * eased
    return radius, init['alpha'] * init['stable'] * (1 - p)


def crop_around(img, centre):
    x, y = int(round(centre[0])), int(round(centre[1]))
    pad = np.zeros((img.shape[0] + 2 * CROP, img.shape[1] + 2 * CROP, 3), dtype=img.dtype)
    pad[CROP:CROP + img.shape[0], CROP:CROP + img.shape[1]] = img
    part = pad[y + CROP // 2:y + CROP + CROP // 2, x + CROP // 2:x + CROP + CROP // 2]
    return part.repeat(CROP_ZOOM, axis=0).repeat(CROP_ZOOM, axis=1)


def run_touch(harness, viewport, hp=5, shots=None, frames_after=None):
    """The frame-stepped touch; returns (init, rows from the touch frame on, touch)."""
    frames_after = frames_after if frames_after is not None else int(RING_MS // FRAME_MS) + 1
    context, page = harness.open(viewport)
    try:
        page.evaluate(fx.BUILD, [TOUCH_SPEC, True])
        init = page.evaluate(INIT, [FRAME_MS, hp])
        rows, touch = [], None
        for _ in range(MAX_FRAMES):
            row = page.evaluate(FRAME, [CAMERA_DRIFT])
            if touch is None and row['touchFrame']:
                touch = row['frame']
            if touch is None:
                continue
            row['offset'] = row['frame'] - touch
            rows.append(row)
            if shots and row['offset'] in shots:
                img = decode(page)
                fx.save_png(img, EVIDENCE_DIR / 'shots' / shots[row['offset']])
                arc = row['arcs'][0] if row['arcs'] else None
                CROPS[shots[row['offset']]] = (img, arc and (arc['mx'], arc['my']))
            if row['offset'] >= frames_after:
                break
        if page.errors:
            raise RuntimeError(f'page errors: {page.errors}')
    finally:
        context.close()
    return init, rows, touch


class MomentumBlueRingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (EVIDENCE_DIR / 'shots').mkdir(parents=True, exist_ok=True)
        cls.harness = fx.FxHarness()
        cls.addClassCleanup(cls.harness.close)
        cls.trace = {}

    @classmethod
    def tearDownClass(cls):
        if cls.trace:
            (EVIDENCE_DIR / 'ring-trace.json').write_text(compact(cls.trace) + '\n')
        # Touch ring (left) and death ring (right) at +140 ms, plain pixels
        names = ('touch-plus140.png', 'death-touch-plus140.png')
        if all(n in CROPS and CROPS[n][1] for n in names):
            parts = [crop_around(*CROPS[n]) for n in names]
            gap = np.full((parts[0].shape[0], 8, 3), 255, dtype=parts[0].dtype)
            fx.save_png(np.concatenate([parts[0], gap, parts[1]], axis=1),
                        EVIDENCE_DIR / 'shots' / 'ring-crop-touch-vs-death-plus140.png')

    def test_ring_trace_world_anchored(self):
        init, rows, touch = run_touch(self.harness, (1280, 720), shots=SHOTS)
        print('init', init, 'touch frame', touch)
        self.assertTrue(init['apply'])
        self.assertIsNotNone(touch, 'the ninja never touched the blue')
        start = rows[0]['touch']
        shake0 = rows[0]['shakeUntil']
        out = []
        for r in rows:
            age = r['ms'] - start['ms']
            expect = death_formula(init, age)
            arc = r['arcs'][0] if r['arcs'] else None
            row = {'ms': round(age, 3), 'rings': r['rings'], 'worldRings': r['worldRings'],
                   'cx': arc and round(arc['x'] * r['k'], 4), 'cy': arc and round(arc['y'] * r['k'], 4),
                   'matrixCx': arc and round(arc['mx'], 4), 'matrixCy': arc and round(arc['my'], 4),
                   'worldX': start['x'], 'worldY': start['y'], 'screenX': r['screenX'], 'screenY': r['screenY'],
                   'expectCx': round((start['x'] + r['screenX']) * r['k'], 4),
                   'expectCy': round((start['y'] + r['screenY']) * r['k'], 4),
                   'radius': arc and round(arc['r'] * r['k'], 4), 'alpha': arc and round(arc['alpha'], 6),
                   'shakeUntil': r['shakeUntil']}
            out.append(row)
            print('row', row)
            self.assertEqual(r['shakeUntil'], shake0, 'a blue touch must not shake')
            self.assertLessEqual(shake0, start['ms'])
            self.assertEqual(r['hp'], init['hp'] - 1)
            if expect is None:
                self.assertEqual((r['rings'], len(r['arcs'])), (0, 0), row)
                continue
            self.assertEqual((r['rings'], r['worldRings'], len(r['arcs'])), (1, 1, 1), row)
            # The arc centre (view units) is world + screen; in canvas px
            # through the context matrix it is within MATRIX_PX of that * k
            self.assertAlmostEqual(arc['x'], start['x'] + r['screenX'], delta=1e-9)
            self.assertAlmostEqual(arc['y'], start['y'] + r['screenY'], delta=1e-9)
            self.assertAlmostEqual(arc['mx'], arc['x'] * r['k'], delta=MATRIX_PX)
            self.assertAlmostEqual(arc['my'], arc['y'] * r['k'], delta=MATRIX_PX)
            self.assertAlmostEqual(arc['r'], expect[0], delta=1e-9)
            self.assertAlmostEqual(arc['alpha'], expect[1], delta=1e-6)
        self.trace['nonLethal'] = out
        ages = [x['ms'] for x in out]
        for a in (0, 140, 210, 280, 420):
            self.assertIn(a, ages)
        self.assertEqual(out[ages.index(420)]['rings'], 0)
        # The camera moved while the ring played
        drawn = [x for x in out if x['cx'] is not None]
        self.assertGreater(len({(x['screenX'], x['screenY']) for x in drawn}), 20)
        self.assertGreater(abs(drawn[-1]['cx'] - drawn[0]['cx']), 20)
        _, phone, _ = run_touch(self.harness, (390, 844), shots={8: 'touch-plus140-390x844.png'}, frames_after=8)
        self.assertEqual((phone[-1]['rings'], phone[-1]['worldRings']), (1, 1))

    def test_n_touches_n_rings(self):
        context, page = self.harness.open((1280, 720))
        try:
            page.evaluate(fx.BUILD, [TOUCH_SPEC, True])
            page.evaluate(INIT, [FRAME_MS, 5])
            shake0 = page.evaluate('visualEffects.screenEffects.shakeUntil')
            results = [page.evaluate(SCRIPTED_TOUCH) for _ in range(N_TOUCHES)]
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        for i, r in enumerate(results, 1):
            print('touch', i, r)
            self.assertEqual((r['rings'], r['world']), (i, i))
            self.assertEqual(r['shakeUntil'], shake0)
            self.assertEqual((r['last']['x'], r['last']['y']), (r['x'], r['y']))
        self.assertEqual(results[-1]['hp'], 5 - N_TOUCHES)

    def test_lethal_touch_one_ring(self):
        init, rows, touch = run_touch(self.harness, (1280, 720), hp=1, shots={8: 'death-touch-plus140.png'},
                                      frames_after=8)
        self.assertIsNotNone(touch)
        self.assertTrue(init['shake'])
        start = rows[0]['touch']
        out = []
        for r in rows:
            arc = r['arcs'][0] if r['arcs'] else None
            row = {'ms': round(r['ms'] - start['ms'], 3), 'rings': r['rings'], 'worldRings': r['worldRings'],
                   'arcs': len(r['arcs']), 'radius': arc and round(arc['r'] * r['k'], 4),
                   'touchMs': start['ms'], 'shakeUntil': r['shakeUntil'], 'version': r['version']}
            out.append(row)
            print('lethal', row)
            self.assertEqual((r['rings'], r['worldRings'], len(r['arcs'])), (1, 0, 1), row)
            self.assertGreater(r['shakeUntil'], start['ms'])
            self.assertEqual(r['version'], 'momentum')
        self.trace['lethal'] = out

    def test_classic_bad_death_identical(self):
        parent = parent_rev()
        result = {'parent': parent}
        frames = {}
        for rev in ('worktree', parent):
            h = fx.FxHarness(rev, browser=self.harness.browser)
            try:
                for mode in ('classic', 'bad'):
                    context, page = h.open((1280, 720))
                    try:
                        state = page.evaluate(DEATH_START, mode)
                        imgs = [decode(page)]
                        for _ in range(2):
                            page.evaluate(DEATH_ADVANCE, 140)
                            imgs.append(decode(page))
                        self.assertFalse(page.errors, page.errors)
                    finally:
                        context.close()
                    print(rev, mode, state)
                    self.assertEqual((state['version'], state['rings']), (mode, 1))
                    frames[rev, mode] = imgs
            finally:
                h.close()
        for mode in ('classic', 'bad'):
            deltas = [int(np.abs(a.astype(np.int16) - b.astype(np.int16)).max())
                      for a, b in zip(frames['worktree', mode], frames[parent, mode])]
            result[mode] = {'identical': max(deltas) == 0, 'maxDelta': deltas, 'framesMs': [0, 140, 280]}
            print(mode, result[mode])
        (EVIDENCE_DIR / 'classic-bad-death.json').write_text(compact(result) + '\n')
        for mode in ('classic', 'bad'):
            self.assertTrue(result[mode]['identical'], result[mode])


if __name__ == '__main__':
    unittest.main()
