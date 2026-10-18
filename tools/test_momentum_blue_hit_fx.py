"""Momentum lighting 10/17: blue-hit flash and shockwave ring (TASK-060),
retired by TASK-076.

TASK-060 gave a blue touch a light flash and its own elliptical ring
(ScreenEffects.triggerBlueHit). TASK-076 replaced both: a touched blue
vanishes at once, its outline pops (ScreenEffects.bluePops) and the death
shockwave plays round the ninja without the shake (triggerBlueTouch; checked
by tools/test_momentum_blue.py). The ring growth, flash and shot checks are
retired; what is left (tools/momentum_fx_support.py blue-hit scene):
- test_0_flash_and_ring_replaced: the TASK-060 hooks (triggerBlueHit,
  getBlueFlash, drawBlueHits, blueHits, STYLE.momentumFx.flashGain/ring*) are
  gone; a scripted touch (blue.onNinjaPass(ninja)) records one shockwave and
  one pop and no shake;
- physics-identical.json: 600 frozen ticks (10 s) of a momentum run with two
  tall blues across the corridor ahead of the ninja, MOMENTUM_FX on and off:
  per physics cycle ninja x/y/speedX/speedY, hp and score identical, 2 blue
  touches;
- switch-off-identical.json: the 4 harness scenes with MOMENTUM_FX off at both
  viewports and the classic and bad test_visual_gallery frames with the switch
  on equal the parent commit (decoded maxDelta 0).

MOMENTUM_BLUE_HIT_FX_EVIDENCE_DIR (default /tmp/momentum-blue-hit-fx)
receives the json files (compact). MOMENTUM_BLUE_HIT_FX_PARENT is
the parent revision (default: the parent of the commit that added this file,
or HEAD while uncommitted). Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_ninja_light import gallery_frames

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = 'tools/test_momentum_blue_hit_fx.py'
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_HIT_FX_EVIDENCE_DIR', '/tmp/momentum-blue-hit-fx'))
VIEWPORT = (1280, 720)
SCENE = 'blue-hit'
TICKS = 600

# A momentum run: pieces cleared, two tall blues across the corridor ahead
# of the ninja, the ninja sent right; every ninja.move() recorded
RUN = r'''([fxOn, ticks]) => {
    MOMENTUM_FX.enabled = fxOn
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor) {
            f.elements = []
            if (f.groups) f.groups = []
        }
    const r = ninja.radius
    for (const dx of [12, 40])
        momentumPlacePiece('blue', {shape: 'rect', x: ninja.x + dx * r, y: ninja.y, w: 3 * r, h: 80 * r})
    ninja.speedX = GAMEPLAY.momentumMaxSpeed * 0.8; ninja.speedY = 0
    let touches = 0
    const onBlueTouch = momentumState.onBlueTouch
    momentumState.onBlueTouch = function() { ++touches; return onBlueTouch.apply(this, arguments) }
    const rows = []
    const move = ninja.move
    ninja.move = function() {
        const out = move.apply(this, arguments)
        rows.push([this.x, this.y, this.speedX, this.speedY, momentumState.hp, scoreText.count[version]])
        return out
    }
    for (let i = 0; i < ticks; ++i)
        __snap.step()
    return {rows: rows, touches: touches, tick: __snap.tick, pops: visualEffects.screenEffects.bluePops.length}
}'''


# The scene's blue touched at the frozen clock's T0: which TASK-060 hooks
# remain, and what the touch recorded
TOUCH = r'''() => {
    const blue = floors.find(f => f instanceof MomentumPatternFloor).elements.find(e => e instanceof MomentumBlue)
    const effects = visualEffects.screenEffects
    blue.onNinjaPass(ninja)
    const old = ['triggerBlueHit', 'getBlueFlash', 'drawBlueHits', 'getBlueRingRadius', 'blueHits']
        .filter(name => name in effects)
    const oldStyle = Object.keys(STYLE.momentumFx).filter(key => key == 'flashGain' || key == 'blueHitMs' ||
        key.startsWith('ring') || key.startsWith('shard'))
    return {old, oldStyle, shockwaves: effects.shockwaves.length, pops: effects.bluePops.length,
            shaking: __snap.now < effects.shakeUntil, hp: momentumState.hp}
}'''


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def parent_rev():
    if os.environ.get('MOMENTUM_BLUE_HIT_FX_PARENT'):
        return os.environ['MOMENTUM_BLUE_HIT_FX_PARENT']
    added = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH],
                                    cwd=ROOT, text=True).strip()
    return subprocess.check_output(['git', 'rev-parse', f'{added}~1' if added else 'HEAD'],
                                   cwd=ROOT, text=True).strip()


class MomentumBlueHitFxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.parent = parent_rev()
        cls.result = {}

    @classmethod
    def tearDownClass(cls):
        if cls.result:
            (EVIDENCE_DIR / 'blue-hit-fx.json').write_text(compact(cls.result))
        fx.close()

    def test_0_flash_and_ring_replaced(self):
        context, page = fx.harness().open(VIEWPORT)
        try:
            page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
            state = page.evaluate(TOUCH)
            self.assertFalse(page.errors, page.errors)
        finally:
            context.close()
        print('touch', state)
        self.result['replaced'] = state
        self.assertEqual(state['old'], [])
        self.assertEqual(state['oldStyle'], [])
        self.assertEqual((state['shockwaves'], state['pops'], state['shaking']), (1, 1, False))

    def test_2_physics_identical(self):
        runs = {}
        for on in (True, False):
            context, page = fx.harness().open(VIEWPORT)
            try:
                runs[on] = page.evaluate(RUN, [on, TICKS])
                self.assertFalse(page.errors, page.errors)
            finally:
                context.close()
        a, b = runs[True], runs[False]
        first = next((i for i, (x, y) in enumerate(zip(a['rows'], b['rows'])) if x != y), None)
        result = {'ticks': TICKS, 'seconds': TICKS / 60, 'cycles': [len(a['rows']), len(b['rows'])],
                  'blueTouches': [a['touches'], b['touches']], 'popsLeft': [a['pops'], b['pops']],
                  'fields': ['x', 'y', 'speedX', 'speedY', 'hp', 'score'],
                  'final': [a['rows'][-1], b['rows'][-1]], 'firstDifference': first,
                  'identical': a['rows'] == b['rows']}
        print('physics', {k: v for k, v in result.items() if k != 'final'})
        (EVIDENCE_DIR / 'physics-identical.json').write_text(compact(result))
        self.assertEqual(a['touches'], 2)
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

if __name__ == '__main__':
    unittest.main()
