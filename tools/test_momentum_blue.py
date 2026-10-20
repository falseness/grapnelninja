"""Momentum blue objects (sprites/momentumblue.js).

One MomentumBlue box is put on the (emptied) momentum obstacle floor below
and right of the ninja of a momentum run whose rAF loop is cancelled, after
three green touches (MomentumGreen.onNinjaBounce, the call Ninja.applyBounce
makes). The ninja flies into it diagonally through ninja.move() alone (no
gravity, camera or replenish in between): on the contact it passes through,
its velocity keeps its direction and is scaled by GAMEPLAY.momentumBlueSlow,
hp goes 5 -> 4 and the green streak 3 -> 0. The used blue vanishes at once
(TASK-076: faded, alpha 0, no fade) and the floor's next moveElements drops
it; a second pass from the same spot changes nothing.

MomentumBlueTouchFrameTests step a frozen-clock scene (momentum_fx_support)
frame by frame (physics() per step, draw()) while the ninja falls onto a blue:
from the frame after the touch the blue is out of its floor and not drawn,
hp -1, speed x momentumBlueSlow, no screen shake; its outline pop lasts
STYLE.momentum.bluePopMs +- one frame (scale 1 -> bluePopScale, alpha 1 -> 0,
eased like the shockwave) and the death ring starts; at touch+1 frame the
blue's inside equals the frame drawn without the pop; a green used on the same
frame still fades over GAMEPLAY.momentumFadeMs.

Writes to MOMENTUM_BLUE_EVIDENCE_DIR (default /tmp/momentum-blue):
pass-trace.json (compact [frame, vx, vy, hp], AFTER moves before to AFTER after
the contact move, frame 0 = contact), blue-trace.json (compact
{frame, ms, inFloor, drawn, popCount, popAlpha, popScale, hp, speedRatio}
per frame from TRACE_BEFORE before to TRACE_AFTER after the touch frame) and
shots/ (before, touch+1, +100 ms, +250 ms with the green fading at 1280x720,
touch+1 at 390x844).

Requires Playwright Chromium. No remote requests.
"""
import copy
import io
import json
import math
import os
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot_run
import momentum_fx_support as fx
import render_snapshot

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_EVIDENCE_DIR', '/tmp/momentum-blue'))
# Diagonal flight in world units per physics cycle, |v| 1.25 under the
# effective cap GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) (1.39 at
# h 1080 since the TASK-073 slow motion; (1.5, 2) = 2.5 under 2.78 and (3, 4)
# = 5 are above it and Ninja.move clamps them)
SPEED = (0.75, 1)
MAX_MOVES = 480
# moves recorded after the contact (5 at |v| 5, 10 at 2.5; doubled with each
# halved speed so the slowed ninja still gets past the box top)
AFTER = 20

SETUP = '''() => {
    startGame('momentum')
    cancelAnimationFrame(game)
    window.__deaths = 0
    const lethal = window.onLethalDeath
    window.onLethalDeath = function() { ++window.__deaths; return lethal.apply(this, arguments) }
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    floor.elements = []
    ninja.__tag = 'blue-test'
    const r = ninja.radius
    const blue = MomentumBlue.box(ninja.x - 10 * r, ninja.y + 6 * r, 40 * r, 20 * r)
    floor.elements.push(blue)
    window.__blue = {floor, blue, x: ninja.x, y: ninja.y}
    return {x: ninja.x, y: ninja.y, radius: r, top: blue.y}
}'''

GREENS = '''() => {
    for (let i = 0; i < 3; ++i)
        MomentumGreen.box(0, 0, 10, 10).onNinjaBounce()
    return [momentumState.hp, momentumState.greenStreak]
}'''

# Flies from the start spot; frame = one ninja.move(). Stops AFTER moves past
# the contact move, or at MAX_MOVES.
FLY = '''([vx, vy, maxMoves, after]) => {
    const b = window.__blue
    ninja.x = b.x
    ninja.y = b.y
    ninja.speedX = vx
    ninja.speedY = vy
    const rows = []
    let contact = null
    const used = b.blue.passThrough
    for (let moves = 1; moves <= maxMoves; ++moves)
    {
        ninja.move()
        if (contact === null && !used && b.blue.passThrough)
            contact = moves
        rows.push([moves, ninja.speedX, ninja.speedY, momentumState.hp])
        if (contact !== null && moves >= contact + after)
            break
    }
    const inFloorBefore = b.floor.elements.includes(b.blue)
    b.floor.moveElements()
    return {rows, contact, x: ninja.x, y: ninja.y,
        hp: momentumState.hp, streak: momentumState.greenStreak,
        passThrough: b.blue.passThrough, alpha: b.blue.getAlpha(), faded: b.blue.faded,
        inFloorBefore, inFloor: b.floor.elements.includes(b.blue), deaths: window.__deaths,
        sameNinja: ninja.__tag === 'blue-test', version, runInProgress}
}'''

class MomentumBlueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        print('setup', page.evaluate(SETUP))
        return page

    def assert_alive(self, result):
        self.assertEqual(result['version'], 'momentum')
        self.assertTrue(result['runInProgress'])
        self.assertTrue(result['sameNinja'])
        self.assertEqual(result['deaths'], 0)

    def test_pass_through_slow_hp_streak_vanish(self):
        page = self.open()
        slow = page.evaluate('GAMEPLAY.momentumBlueSlow')
        print('momentumBlueSlow', slow)
        self.assertGreater(slow, 0)
        self.assertLess(slow, 1)
        greens = page.evaluate(GREENS)
        print('after 3 greens [hp, greenStreak]', greens)
        self.assertEqual(greens, [5, 3])

        first = page.evaluate(FLY, [SPEED[0], SPEED[1], MAX_MOVES, AFTER])
        contact = first['contact']
        print('first pass: contact at move', contact, 'hp', first['hp'], 'streak', first['streak'],
              'alpha', round(first['alpha'], 4))
        self.assertIsNotNone(contact)
        self.assertGreater(contact, AFTER, 'need AFTER moves before the contact')
        rows = first['rows']
        trace = [[r[0] - contact, r[1], r[2], r[3]] for r in rows if contact - AFTER <= r[0] <= contact + AFTER]
        self.assertEqual(len(trace), 2 * AFTER + 1)
        (EVIDENCE_DIR / 'pass-trace.json').write_text(json.dumps(trace, separators=(',', ':')) + '\n')
        for row in trace:
            print('trace', row)

        before = [r for r in trace if r[0] < 0]
        after = [r for r in trace if r[0] >= 0]
        for r in before:
            self.assertEqual((r[1], r[2], r[3]), (SPEED[0], SPEED[1], 5))
        for r in after:
            self.assertEqual(r[3], 4)
            self.assertEqual((r[1], r[2]), (after[0][1], after[0][2]))
        vx, vy = after[0][1], after[0][2]
        angle_diff = abs(math.atan2(vy, vx) - math.atan2(SPEED[1], SPEED[0]))
        ratio = math.hypot(vx, vy) / math.hypot(*SPEED)
        print('angle diff', angle_diff, 'magnitude ratio', ratio)
        self.assertLess(angle_diff, 1e-6)
        self.assertAlmostEqual(ratio, slow, delta=1e-6)
        # Passed into the box instead of bouncing off its top
        self.assertGreater(first['y'], page.evaluate('window.__blue.blue.y'))
        self.assertEqual((first['hp'], first['streak']), (4, 0))
        self.assertTrue(first['passThrough'])
        # Gone at once: no fade, dropped by the floor's next pass
        self.assertTrue(first['faded'])
        self.assertEqual(first['alpha'], 0)
        self.assertTrue(first['inFloorBefore'])
        self.assertFalse(first['inFloor'])
        self.assert_alive(first)

        second = page.evaluate(FLY, [SPEED[0], SPEED[1], 2 * contact, AFTER])
        print('second pass: moves', len(second['rows']), 'hp', second['hp'], 'streak', second['streak'],
              'alpha', round(second['alpha'], 4), 'end', second['rows'][-1])
        self.assertIsNone(second['contact'])
        self.assertTrue(all((r[1], r[2], r[3]) == (SPEED[0], SPEED[1], 4) for r in second['rows']))
        self.assertGreater(second['y'], page.evaluate('window.__blue.blue.y'))
        self.assertEqual((second['hp'], second['streak']), (4, 0))
        self.assertEqual(second['alpha'], 0)
        self.assertFalse(second['inFloor'])
        self.assert_alive(second)

    def test_bad_mode_untouched(self):
        page = self.open()
        result = page.evaluate('''() => {
            startGame('bad')
            cancelAnimationFrame(game)
            return {version, hp: momentumState.hp,
                blueOnlyHook: floors.every(f => f.elements.every(e => !e.onNinjaPass))}
        }''')
        print('bad', result)
        self.assertEqual(result['version'], 'bad')
        self.assertTrue(result['blueOnlyHook'])


# Frame-stepped touch (frozen clock, momentum_fx_support scene): a blue rect
# in the right corridor with a green beside it, the ninja above the blue
# falling onto it. One frame = __snap.now + 1000/60, physics() per physics
# step, draw(). The green is used (onNinjaBounce) on the touch frame for the
# fade contrast shot.
TOUCH_SPEC = copy.deepcopy(fx.SCENE_SPECS['blue-hit'])
TOUCH_SPEC['pieces'] = [{'kind': 'blue', 'x': 220, 'y': 330, 'w': 200, 'h': 100},
                        {'kind': 'green', 'x': -120, 'y': 330, 'w': 130, 'h': 30}]
TOUCH_SPEC['ninja'] = [220, 240]
TOUCH_SPEC['speed'] = [0.2, 0.3]
TOUCH_SPEC['trail'] = [[220, 150], [220, 240]]
# Trace window round the touch frame (frame 0: the frame whose physics
# touched the blue)
TRACE_BEFORE = 2
TRACE_AFTER = 20
MAX_FRAMES = 120
# Canvas px kept clear of the blue's outline when its inside is compared
# (the pop's neon stroke and inner glow reach about 20 px in at 720)
EDGE_PX = 26

TOUCH_INIT = r'''() => {
    const fl = floors.find(f => f instanceof MomentumPatternFloor)
    const blue = fl.elements.find(e => e instanceof MomentumBlue)
    const green = fl.elements.find(e => e instanceof MomentumGreen)
    const t = window.__t = {fl, blue, green, drawn: 0, touch: null, frame: 0, deaths: 0,
        steps: Math.max(1, Math.round(1000 / 60 / physicsStepMs))}
    window.onLethalDeath = () => { ++t.deaths }
    // The camera stays on the built scene: the rail camera's first move
    // would put the view back on the course from the trigger point
    screen.shouldStartMove = () => false
    // Every drawn blue runs its inner shell (the crystal draw of TASK-126
    // skips drawBadVersionPolygon at full alpha); none once it is faded
    const draw = blue.drawInnerShell
    blue.drawInnerShell = function() { ++t.drawn; return draw.apply(this, arguments) }
    const pass = blue.onNinjaPass
    blue.onNinjaPass = function(who) {
        const v0 = Math.hypot(who.speedX, who.speedY), used = this.passThrough
        pass.apply(this, arguments)
        if (!used && this.passThrough)
            t.touch = {ms: performance.now(), ratio: Math.hypot(who.speedX, who.speedY) / v0}
    }
    return {hp: momentumState.hp, streak: momentumState.greenStreak, slow: GAMEPLAY.momentumBlueSlow,
            popMs: STYLE.momentum.bluePopMs, popScale: STYLE.momentum.bluePopScale}
}'''

# One frame; clearPops: drop the pops just before the draw (reference frame)
TOUCH_FRAME = r'''([clearPops]) => {
    const t = window.__t, fxs = visualEffects.screenEffects
    __snap.now += 1000 / 60
    const touched = t.touch !== null
    for (let s = 0; s < t.steps; ++s)
        physics()
    const touchFrame = !touched && t.touch !== null
    if (touchFrame)
        t.green.onNinjaBounce()
    if (clearPops)
        fxs.bluePops.length = 0
    t.drawn = 0
    draw()
    const pop = fxs.bluePops[0]
    let popAlpha = null, popScale = null
    if (pop) {
        const p = fxs.getBluePopProgress(pop, performance.now())
        const eased = 1 - (1 - p) * (1 - p)
        popAlpha = 1 - p
        popScale = 1 + (STYLE.momentum.bluePopScale - 1) * eased
    }
    const lm = visualEffects.lightmap
    const k = canvas.width / width * scale[version]
    const box = t.blue.getPoints().map(q => [(q.x + screen.x) * k, (q.y + screen.y) * k])
    return {frame: t.frame++, ms: performance.now(), touchFrame,
        inFloor: t.fl.elements.includes(t.blue), drawn: t.drawn > 0,
        popCount: fxs.bluePops.length, popAlpha, popScale, hp: momentumState.hp,
        speedRatio: t.touch ? t.touch.ratio : null, streak: momentumState.greenStreak,
        faded: t.blue.faded, alpha: t.blue.getAlpha(), greenAlpha: t.green.getAlpha(),
        shockwaves: fxs.shockwaves.length, shaking: performance.now() < fxs.shakeUntil,
        touchMs: t.touch ? t.touch.ms : null, deaths: t.deaths, box,
        lit: (lm.emitterCandidates || []).some(e => e.element === t.blue),
        occludes: (lm.occluders || []).some(o => o.element === t.blue)}
}'''


def decode(page):
    png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGB'))


def inner_mask(shape, box, edge):
    """Pixels of the axis-aligned box (canvas px) at least edge px inside it."""
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    mask = np.zeros(shape[:2], dtype=bool)
    x0, x1 = int(math.ceil(min(xs) + edge)), int(math.floor(max(xs) - edge))
    y0, y1 = int(math.ceil(min(ys) + edge)), int(math.floor(max(ys) - edge))
    mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    return mask


def run_touch(harness, viewport, shots=None, clear_pops_at=None):
    """Frames of the scripted touch at viewport up to TRACE_AFTER frames past
    the touch frame. shots {offset: png name}: frames saved by offset from the
    touch frame; clear_pops_at: the offset drawn without pops. Returns (init,
    rows, frames {offset: decoded array}, touch frame)."""
    wanted = set(shots or {}) | ({clear_pops_at} if clear_pops_at is not None else set())
    context, page = harness.open(viewport)
    try:
        page.evaluate(fx.BUILD, [TOUCH_SPEC, True])
        init = page.evaluate(TOUCH_INIT)
        rows, frames, history, touch = [], {}, [], None
        for _ in range(MAX_FRAMES):
            clear = touch is not None and len(rows) - touch == clear_pops_at
            row = page.evaluate(TOUCH_FRAME, [clear])
            rows.append(row)
            if touch is None and row['touchFrame']:
                touch = row['frame']
                for frame, img in history:
                    frames[frame - touch] = img
            if touch is None:
                if any(o < 0 for o in wanted):
                    history = (history + [(row['frame'], decode(page))])[-3:]
                continue
            offset = row['frame'] - touch
            if offset in wanted:
                frames[offset] = decode(page)
            if offset >= TRACE_AFTER:
                break
        if page.errors:
            raise RuntimeError(f'page errors: {page.errors}')
    finally:
        context.close()
    for offset, name in (shots or {}).items():
        fx.save_png(frames[offset], EVIDENCE_DIR / 'shots' / name)
    return init, rows, frames, touch


class MomentumBlueTouchFrameTests(unittest.TestCase):
    """Instant removal, pop and ring on the frame-stepped scripted touch."""
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.harness = fx.FxHarness()
        cls.addClassCleanup(cls.harness.close)
        cls.init, cls.rows, cls.frames, cls.touch = run_touch(
            cls.harness, (1280, 720),
            shots={-1: 'blue-before.png', 1: 'blue-touch-plus1.png', 6: 'blue-plus100ms.png',
                   15: 'blue-plus250ms-green-fading.png'})
        print('init', cls.init, 'touch frame', cls.touch)

    def window(self):
        return [r for r in self.rows if self.touch - TRACE_BEFORE <= r['frame'] <= self.touch + TRACE_AFTER]

    def test_trace_instant_removal(self):
        self.assertIsNotNone(self.touch, 'the ninja never touched the blue')
        self.assertGreaterEqual(self.touch, TRACE_BEFORE)
        rows = self.window()
        self.assertEqual(len(rows), TRACE_BEFORE + TRACE_AFTER + 1)
        keys = ('frame', 'ms', 'inFloor', 'drawn', 'popCount', 'popAlpha', 'popScale', 'hp', 'speedRatio')
        trace = [{k: (r['frame'] - self.touch if k == 'frame' else r[k]) for k in keys} for r in rows]
        (EVIDENCE_DIR / 'blue-trace.json').write_text(json.dumps(trace, separators=(',', ':')) + '\n')
        for r in trace:
            print('trace', r)
        hp0 = self.init['hp']
        for r in rows:
            off = r['frame'] - self.touch
            self.assertEqual(r['deaths'], 0)
            if off < 0:
                self.assertEqual((r['inFloor'], r['drawn'], r['popCount'], r['hp']), (True, True, 0, hp0), r)
                self.assertTrue(r['lit'] and r['occludes'], r)
                self.assertIsNone(r['speedRatio'])
                continue
            self.assertEqual(r['hp'], hp0 - 1)
            self.assertAlmostEqual(r['speedRatio'], self.init['slow'], delta=1e-9)
            self.assertTrue(r['faded'])
            self.assertEqual(r['alpha'], 0)
            if off >= 1:
                self.assertFalse(r['inFloor'], r)
                self.assertFalse(r['drawn'], r)
                self.assertFalse(r['lit'] or r['occludes'], r)
            self.assertFalse(r['shaking'], 'a blue touch must not shake the screen')

    def test_pop_duration_and_ring(self):
        rows = self.window()
        pop_ms = self.init['popMs']
        frame_ms = 1000 / 60
        for r in rows:
            off = r['frame'] - self.touch
            if off < 0:
                continue
            age = r['ms'] - r['touchMs']
            if age < pop_ms - frame_ms:
                self.assertEqual(r['popCount'], 1, r)
                self.assertAlmostEqual(r['popAlpha'], 1 - age / pop_ms, delta=1e-9)
                p = age / pop_ms
                self.assertAlmostEqual(r['popScale'], 1 + (self.init['popScale'] - 1) * (1 - (1 - p) ** 2),
                                       delta=1e-9)
            elif age >= pop_ms + frame_ms:
                self.assertEqual(r['popCount'], 0, r)
        active = [r['ms'] - r['touchMs'] for r in rows if r['frame'] >= self.touch and r['popCount']]
        print('pop active for', round(max(active), 2), 'ms (bluePopMs', pop_ms, ')')
        self.assertLessEqual(abs(max(active) - pop_ms), frame_ms + 1e-9)
        self.assertEqual(rows[-1]['popCount'], 0)
        # The death ring plays on the touch frame (shockwaveDurationMs 420)
        self.assertEqual(rows[TRACE_BEFORE]['shockwaves'], 1)
        self.assertEqual(rows[TRACE_BEFORE - 1]['shockwaves'], 0)
        # The green keeps its 800 ms fade
        r250 = next(r for r in rows if r['frame'] == self.touch + 15)
        self.assertAlmostEqual(r250['greenAlpha'], 1 - 250 / 800, delta=1e-6)

    def test_body_not_drawn_after_touch(self):
        """At touch+1 frame the blue's inside (EDGE_PX clear of its outline)
        equals the same frame drawn without the pop, while the frame before
        the touch shows the body there."""
        _, rows, frames, touch = run_touch(self.harness, (1280, 720), clear_pops_at=1)
        self.assertEqual(touch, self.touch)
        ref = frames[1]
        box = next(r for r in self.rows if r['frame'] == self.touch + 1)['box']
        inner = inner_mask(ref.shape, box, EDGE_PX)
        with_pop = self.frames[1]
        before = self.frames[-1]
        delta = np.abs(with_pop.astype(np.int16) - ref.astype(np.int16)).max(axis=2)
        pop_band = delta >= 8
        body = np.abs(before.astype(np.int16) - ref.astype(np.int16)).max(axis=2)
        stats = {'innerPixels': int(inner.sum()), 'innerMaxDeltaVsNoPop': int(delta[inner].max()),
                 'popPixels': int(pop_band.sum()), 'beforeInnerMeanDelta': float(body[inner].mean())}
        print('touch+1 inside', stats)
        self.assertGreater(stats['innerPixels'], 2000)
        self.assertLessEqual(stats['innerMaxDeltaVsNoPop'], 2)
        self.assertGreater(stats['popPixels'], 200)
        self.assertGreater(stats['beforeInnerMeanDelta'], 10)

    def test_phone_touch_plus1(self):
        _, rows, frames, touch = run_touch(self.harness, (390, 844), shots={1: 'blue-touch-plus1-390x844.png'})
        self.assertIsNotNone(touch)
        r = next(r for r in rows if r['frame'] == touch + 1)
        self.assertEqual((r['inFloor'], r['drawn'], r['popCount']), (False, False, 1))


if __name__ == '__main__':
    unittest.main()
