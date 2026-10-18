"""Momentum grapnel release on used one-time objects (Grapnel.releaseElement).

A real grapnel throw (grapnel.move() + grapnel.collision(), the calls
calcPhysics makes for a flying grapnel, with the ninja held still) hooks an
element placed on the emptied obstacle floor of a run whose rAF loop is
cancelled. Then real calcPhysics() cycles run:

  green  - a MomentumGreen below the ninja; the rope pulls the ninja onto it,
           ninja.move() bounces off it (use()), and from that cycle on the
           grapnel is released: not grappled, not throwed, no rope point on
           the green, and the next calcPhysics changes the speed by gravity
           only (no grapple pull).
  blue   - the same with a MomentumBlue the ninja passes through.
  border - hooked on the momentum ceiling (MomentumBorder): stays hooked
           through 60 calcPhysics.
  bad    - bad mode, hooked on a Trampoline the ninja bounces off: stays
           hooked through the bounce and 60 more calcPhysics (unchanged).

Writes MOMENTUM_GRAPNEL_EVIDENCE_DIR (default artifacts/TASK-022)/
grapnel-release.json: compact {case: {grappledAfter, throwedAfter,
anchorsOnUsed, pullDx, pullDy}} (pull = speed change of one calcPhysics
minus gravity, measured right after the use / bounce / hook).

Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_GRAPNEL_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-022'))
TOL = 1e-9
HOLD_CYCLES = 60

HELPERS = '''
window.__throwAt = function(tx, ty) {
    grapnel.pos = [[ninja.x, ninja.y, new Empty()]]
    const r = grapnel.calcSpeed({x: tx, y: ty})
    grapnel.speedX = r.cos * grapnelSpeed
    grapnel.speedY = r.sin * grapnelSpeed
    grapnel.throwed = true
    grapnel.setGrappled(false)
    let steps = 0
    while (!grapnel.isGrappled() && steps < 20000) {
        grapnel.move()
        grapnel.collision()
        ++steps
    }
    return steps
}
// Speed change of one calcPhysics minus gravity (momentum gravity is
// GRAVITY * momentumMotionScale(2) since the TASK-073 slow motion)
window.__pull = function() {
    const vx = ninja.speedX, vy = ninja.speedY
    calcPhysics()
    return [ninja.speedX - vx, ninja.speedY - vy - GRAVITY * momentumMotionScale(2)]
}
window.__state = function(element) {
    return {grappled: grapnel.isGrappled(), throwed: grapnel.throwed,
        anchorsOn: grapnel.pos.filter(p => p[2] === element).length,
        anchorClass: grapnel.pos.length ? grapnel.pos[0][2].constructor.name : null}
}
'''

# One-time object below the ninja, hooked, then calcPhysics until it is used
ONE_TIME = HELPERS + '''
const kind = arguments[0]
startGame('momentum')
cancelAnimationFrame(game)
window.__deaths = 0
const lethal = window.onLethalDeath
window.onLethalDeath = function() { ++window.__deaths; return lethal.apply(this, arguments) }
const floor = floors.find(f => f instanceof MomentumObstacleFloor)
floor.elements = []
const n0 = ninja
const r = ninja.radius
ninja.speedX = 0
ninja.speedY = 0
const cls = kind == 'green' ? MomentumGreen : MomentumBlue
const el = cls.box(ninja.x - 15 * r, ninja.y + 3 * r, 30 * r, 10 * r)
floor.elements.push(el)
const steps = __throwAt(ninja.x, ninja.y + 10 * r)
const hooked = __state(el)
let cycles = 0
while (!el.passThrough && cycles < 400) {
    calcPhysics()
    ++cycles
}
const after = __state(el)
const pull = __pull()
return {kind, throwSteps: steps, hooked, cycles, used: el.passThrough,
    streak: momentumState.greenStreak, hp: momentumState.hp,
    after, afterPull: __state(el), pullDx: pull[0], pullDy: pull[1],
    deaths: window.__deaths, sameNinja: ninja === n0, version}
'''

BORDER = HELPERS + '''
startGame('momentum')
cancelAnimationFrame(game)
floors.find(f => f instanceof MomentumObstacleFloor).elements = []
const n0 = ninja
ninja.speedX = 0
ninja.speedY = 0
const steps = __throwAt(ninja.x + 0.3 * height, ninja.y - 3 * height)
const anchor = grapnel.isGrappled() ? grapnel.pos[0][2] : null
const hooked = __state(anchor)
const pull = __pull()
let heldCycles = 1
for (let i = 1; i < 60; ++i) {
    calcPhysics()
    if (grapnel.isGrappled() && grapnel.throwed && grapnel.pos[0][2] === anchor)
        ++heldCycles
}
return {throwSteps: steps, hooked, isBorder: anchor instanceof MomentumBorder,
    heldCycles, after: __state(anchor), pullDx: pull[0], pullDy: pull[1],
    sameNinja: ninja === n0, version}
'''

BAD = HELPERS + '''
startGame('bad')
cancelAnimationFrame(game)
const floor = floors[1]
floor.elements = []
const n0 = ninja
const r = ninja.radius
ninja.speedX = 0
ninja.speedY = 0
const t = new Trampoline(MomentumOneTime.boxObject(ninja.x - 15 * r, ninja.y + 3 * r, 30 * r, 10 * r))
floor.elements.push(t)
let bounces = 0
const applyBounce = Ninja.prototype.applyBounce
Ninja.prototype.applyBounce = function(contact) {
    if (contact && contact.element === t) ++bounces
    return applyBounce.apply(this, arguments)
}
const steps = __throwAt(ninja.x, ninja.y + 10 * r)
const hooked = __state(t)
let cycles = 0
while (!bounces && cycles < 400) {
    calcPhysics()
    ++cycles
}
const after = __state(t)
const pull = __pull()
let heldCycles = 1
for (let i = 1; i < 60; ++i) {
    calcPhysics()
    if (grapnel.isGrappled() && grapnel.throwed && grapnel.pos.some(p => p[2] === t))
        ++heldCycles
}
Ninja.prototype.applyBounce = applyBounce
return {throwSteps: steps, hooked, cycles, bounces, after, end: __state(t),
    pullDx: pull[0], pullDy: pull[1], heldCycles, sameNinja: ninja === n0, version}
'''


def wrap(body):
    return '(arg) => { return (function() {' + body + '}).call(null, arg) }'


class MomentumGrapnelReleaseTests(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        (EVIDENCE_DIR / 'grapnel-release.json').write_text(
            json.dumps(cls.results, separators=(',', ':')) + '\n')

    def run_case(self, body, arg=None):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page.evaluate(wrap(body), arg)

    def record(self, case, r, state, anchors):
        self.results[case] = {'grappledAfter': state['grappled'], 'throwedAfter': state['throwed'],
                              'anchorsOnUsed': anchors, 'pullDx': r['pullDx'], 'pullDy': r['pullDy']}
        print(case, json.dumps(self.results[case], separators=(',', ':')))

    def check_one_time(self, kind):
        r = self.run_case(ONE_TIME, kind)
        print(kind, json.dumps(r, separators=(',', ':')))
        self.assertEqual(r['version'], 'momentum')
        cls = 'MomentumGreen' if kind == 'green' else 'MomentumBlue'
        self.assertEqual(r['hooked'], {'grappled': True, 'throwed': True, 'anchorsOn': 1, 'anchorClass': cls})
        self.assertTrue(r['used'], 'the ninja never reached the object')
        if kind == 'green':
            self.assertEqual((r['streak'], r['hp']), (1, 5))
        else:
            self.assertEqual((r['streak'], r['hp']), (0, 4))
        for state in (r['after'], r['afterPull']):
            self.assertFalse(state['grappled'])
            self.assertFalse(state['throwed'])
            self.assertEqual(state['anchorsOn'], 0)
        self.assertAlmostEqual(r['pullDx'], 0, delta=TOL)
        self.assertAlmostEqual(r['pullDy'], 0, delta=TOL)
        self.assertEqual(r['deaths'], 0)
        self.assertTrue(r['sameNinja'])
        self.record(kind, r, r['after'], r['after']['anchorsOn'])

    def test_a_green_used_releases_grapnel(self):
        self.check_one_time('green')

    def test_b_blue_passed_releases_grapnel(self):
        self.check_one_time('blue')

    def test_c_border_stays_hooked(self):
        r = self.run_case(BORDER)
        print('border', json.dumps(r, separators=(',', ':')))
        self.assertEqual(r['version'], 'momentum')
        self.assertTrue(r['isBorder'], r['hooked'])
        self.assertEqual(r['heldCycles'], HOLD_CYCLES)
        self.assertTrue(r['after']['grappled'])
        self.assertTrue(r['after']['throwed'])
        self.assertTrue(r['sameNinja'])
        self.assertGreater(abs(r['pullDx']) + abs(r['pullDy']), 1e-3, 'hooked grapnel must pull')
        self.record('border', r, r['after'], 0)

    def test_d_bad_trampoline_stays_hooked(self):
        r = self.run_case(BAD)
        print('bad', json.dumps(r, separators=(',', ':')))
        self.assertEqual(r['version'], 'bad')
        self.assertEqual(r['hooked']['anchorClass'], 'Trampoline')
        self.assertEqual(r['bounces'], 1)
        self.assertTrue(r['after']['grappled'])
        self.assertTrue(r['after']['throwed'])
        self.assertGreaterEqual(r['after']['anchorsOn'], 1)
        self.assertEqual(r['heldCycles'], HOLD_CYCLES)
        self.assertTrue(r['sameNinja'])
        self.assertGreater(abs(r['pullDx']) + abs(r['pullDy']), 1e-3, 'hooked grapnel must pull')
        self.record('bad', r, r['after'], r['after']['anchorsOn'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
