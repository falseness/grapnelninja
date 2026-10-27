"""TASK-665/666: Grapple Over long-fall detection, message selection and rendering.

Boots the real index.html, freezes the frame loop and drives the production
physics()/calcPhysics(), LONG_FALL.step() (called from calcPhysics) and the
real mouse/keyboard handlers. A continuous descent of strictly more than 4000
world units emits one transient event; upward movement or a new grapple catch
rearms the detector. Recovery, restart, reload and the spawn never count as falls.

TASK-666 (LongFallRenderTests) drives the production render/fallmessage.js
through the real gameLoop/draw(): layout of every phrase at every anchor and
the rotation endpoints against the 16 CSS px margins and the HUD boxes, the
max(0, 1 - t/6000)^2 fade in active time, the pause/hidden/restart/reload/
completion/teleport/replace lifecycle, and noninteractive isolation.

LONG_FALL_EVIDENCE_DIR=DIR writes compact fall-events.json, lifecycle.json,
message-pool.json and isolation.json there, and for TASK-666 layout.json,
timing.json, isolation.json's "render" entry and message-frames.png (needs PIL).

    python3 -m unittest discover -s tools -p test_long_fall_messages.py -v
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run, select_mode

ROOT = Path(__file__).resolve().parent.parent
CLIMB_KEY = 'grapnelninja.grappleOver'
THRESHOLD = 4000
DEPTH = 1500
MESSAGES = ['OOPS...', 'GG!', 'BRUH.', 'NOT AGAIN.', 'SO CLOSE...', 'GRAVITY WINS.', 'GOING DOWN!',
            'BACK SO SOON?', 'NICE SHORTCUT.', 'WRONG WAY.', 'ONE MORE TRY?', 'SEE YOU AT THE TOP.']
EXCLUDED = ['I MEANT THAT.', 'DEJA VU.', 'WELP.']
# TASK-720: the run's first long fall (single grapnel) shows this hint instead.
HINT = 'Maybe you should try double grapnel mode'
# Spend the run's first long fall, so the next one draws from MESSAGES.
HINT_SPENT = '() => { floors[0].fallHintShown = true }'

# Freeze the loop; count gameplay RNG use and recoveries through production functions.
SETUP = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    const rnd = Math.random
    window.GAMEPLAY_RNG_CALLS = 0
    Math.random = function() { GAMEPLAY_RNG_CALLS++; return rnd() }
    const recover = recoverClimbFall
    window.RECOVERIES = []
    recoverClimbFall = function() {
        RECOVERIES.push({y: ninja.y, height: floors[0].climbStats.currentHeight,
            eventBefore: LONG_FALL.event ? LONG_FALL.event.id : null})
        // TASK-721: past the first-death double grapnel offer (test_double_offer covers it)
        floors[0].doubleOfferShown = true
        return recover()
    }
}'''

# Detector snapshot after the last step.
DET = '''() => ({tracking: LONG_FALL.tracking(), event: LONG_FALL.event, emitted: LONG_FALL.emitted,
    y: ninja.y, speedY: ninja.speedY, grappled: grapnel.isGrappled(),
    height: floors[0].climbStats ? floors[0].climbStats.currentHeight : null})'''

# Open air beside the level, `height` units above the spawn.
OPEN_AIR = '''([height, speedY]) => {
    const l = floors[0].level
    ninja.x = l.bounds.right + 4000; ninja.y = l.spawn.y - height
    ninja.speedX = 0; ninja.speedY = speedY
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null})
}'''

# One production calcPhysics step. 'hold' cancels gravity (stationary sample),
# 'up' moves 1 unit upward (sets the descent baseline at the new position).
STEP = '''kind => {
    if (kind === 'hold') ninja.speedY = -GRAVITY
    if (kind === 'up') ninja.speedY = -1 - GRAVITY
    const r = calcPhysics() === true
    if (kind === 'up') ninja.speedY = 0
    return {recovered: r, y: ninja.y, tracking: LONG_FALL.tracking(),
        event: LONG_FALL.event, emitted: LONG_FALL.emitted}
}'''

# Move the player `dy` world units further down (a fixture displacement the
# detector sees on the next production step).
SHIFT = 'dy => { ninja.y += dy }'

# Run real physics() ticks, recording each detector step compactly.
RUN = '''([ticks, until]) => {
    const step = LONG_FALL.step.bind(LONG_FALL), out = []
    LONG_FALL.step = function() {
        const before = LONG_FALL.emitted
        step()
        const t = LONG_FALL.tracking()
        out.push({y: ninja.y, start: t.startY, d: t.displacement, armed: t.armed,
            g: grapnel.isGrappled(), e: LONG_FALL.emitted - before, h: floors[0].climbStats.currentHeight})
    }
    let i = 0
    for (; i < ticks; i++) {
        physics()
        if (until === 'event' && LONG_FALL.event && out.some(s => s.e)) break
        if (until === 'recovery' && RECOVERIES.length) break
        if (typeof until === 'number' && out.length && out[out.length - 1].d > until) break
    }
    LONG_FALL.step = step
    return {ticks: i, steps: out}
}'''

# Simulation and save state compared between inert and enabled detector runs.
STATE = '''() => {
    const w = floors[0], g = grapnel
    return {player: {x: ninja.x, y: ninja.y, speedX: ninja.speedX, speedY: ninja.speedY},
        grapple: {throwed: g.throwed, grappled: g.grappled, segments: g.pos.length, traveled: g.traveled ?? 0},
        stats: {...w.climbStats}, tick: w.elapsedSteps, upgrades: {range: w.rangeUpgraded},
        elements: w.elements.map(e => [e.id, e.x, e.y]), input: {pressHeld, stalePress, gameplayPressOwned},
        save: JSON.stringify(captureClimbState()), rngCalls: GAMEPLAY_RNG_CALLS, recoveries: RECOVERIES.length}
}'''


EVIDENCE = {}


def tearDownModule():
    out = os.environ.get('LONG_FALL_EVIDENCE_DIR')
    if out and EVIDENCE:
        Path(out).mkdir(parents=True, exist_ok=True)
        for key, data in EVIDENCE.items():
            Path(out, key + '.json').write_text(json.dumps(data, separators=(',', ':'), sort_keys=True) + '\n')


def compact(steps, keep):
    """Only the steps an assertion uses: first, last and listed indexes."""
    idx = sorted({0, len(steps) - 1, *[i for i in keep if 0 <= i < len(steps)]})
    return [dict(steps[i], i=i) for i in idx]


class LongFallMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.evidence = EVIDENCE
        EVIDENCE.update({'fall-events': {'threshold': THRESHOLD}, 'lifecycle': {}, 'message-pool': {}})
        EVIDENCE.setdefault('isolation', {})

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def open(self, context=None):
        if context is None:
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
            self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SETUP)
        return page

    def step(self, page, kind='fall'):
        return page.evaluate(STEP, kind)

    def baseline_at(self, page, height):
        """Open air at `height`, with the descent baseline set there by a real 1-unit upward step."""
        page.evaluate(OPEN_AIR, [height - 1, 0])
        return self.step(page, 'up')

    def test_01_threshold_and_continued_descent(self):
        page = self.open()
        ev = self.evidence['fall-events']
        base = self.baseline_at(page, 9000)
        y0 = base['tracking']['startY']
        self.assertEqual(base['tracking']['displacement'], 0)
        page.evaluate(SHIFT, THRESHOLD - (base['y'] - y0))
        at = self.step(page, 'hold')
        self.assertEqual(at['tracking']['displacement'], THRESHOLD)
        self.assertIsNone(at['event'])
        self.assertEqual(at['emitted'], 0)
        # A stationary sample at exactly 4000 keeps the baseline and does not emit.
        held = [self.step(page, 'hold') for _ in range(3)]
        self.assertTrue(all(h['tracking']['startY'] == y0 and h['emitted'] == 0 for h in held))
        page.evaluate(SHIFT, 1e-3)
        above = self.step(page, 'hold')
        self.assertGreater(above['tracking']['displacement'], THRESHOLD)
        self.assertEqual(above['emitted'], 1)
        self.assertEqual(above['event']['id'], 1)
        self.assertEqual((above['event']['message'], above['event']['hint']), (HINT, True))
        # Continued descent past 8000: still the same single event.
        page.evaluate(SHIFT, 4100)
        beyond = self.step(page, 'hold')
        later = self.step(page)
        self.assertGreater(beyond['tracking']['displacement'], 2 * THRESHOLD)
        self.assertEqual((beyond['emitted'], later['emitted']), (1, 1))
        self.assertEqual(beyond['event']['id'], 1)
        pick = lambda s: {'y': s['y'], 'displacement': s['tracking']['displacement'], 'startY': s['tracking']['startY'],
                          'armed': s['tracking']['armed'], 'emitted': s['emitted'],
                          'eventId': s['event']['id'] if s['event'] else None}
        ev['fixtureThreshold'] = {'baselineY': y0, 'exactly4000': pick(at), 'stationaryAt4000': [pick(h) for h in held],
                                  'above4000': dict(pick(above), message=above['event']['message']),
                                  'beyond8000': pick(beyond), 'afterBeyond': pick(later)}
        # Genuine free fall under production gravity from 9000 above the spawn.
        page.evaluate(OPEN_AIR, [9000, 0])
        self.step(page, 'up')
        n = page.evaluate('LONG_FALL.emitted')
        run = page.evaluate(RUN, [2000, 2 * THRESHOLD])
        steps = run['steps']
        first = next(i for i, s in enumerate(steps) if s['e'])
        self.assertEqual(sum(s['e'] for s in steps), 1)
        self.assertGreater(steps[first]['d'], THRESHOLD)
        self.assertLessEqual(steps[first - 1]['d'], THRESHOLD)
        self.assertTrue(all(s['start'] == steps[0]['start'] for s in steps))
        self.assertGreater(steps[-1]['d'], 2 * THRESHOLD)
        self.assertEqual(page.evaluate('LONG_FALL.emitted'), n + 1)
        self.assertEqual(page.evaluate('RECOVERIES.length'), 0)
        ev['freeFall'] = {'startHeight': 9000, 'ticks': run['ticks'], 'steps': len(steps), 'events': 1,
                          'firstEmittingStep': first, 'trace': compact(steps, [first - 1, first])}
        ev['pageErrorsThreshold'] = page.errors
        self.assertEqual(page.errors, [])

    def test_02_upward_and_catch_resets(self):
        page = self.open()
        ev = self.evidence['fall-events']
        # Upward movement rebaselines: 3000 down, 1 up, then 3500 more stays silent.
        base = self.baseline_at(page, 9000)
        page.evaluate(SHIFT, 3000)
        down = self.step(page, 'hold')
        up = self.step(page, 'up')
        page.evaluate(SHIFT, 3500)
        after = self.step(page, 'hold')
        self.assertEqual(down['tracking']['displacement'], 3000)
        self.assertEqual(up['tracking']['startY'], up['y'])
        self.assertEqual(after['emitted'], 0)
        self.assertEqual(after['tracking']['displacement'], 3500)
        page.evaluate(SHIFT, 600)
        crossed = self.step(page, 'hold')
        self.assertEqual(crossed['emitted'], 1)
        # After an event: continued descent stays silent; an upward move rearms.
        page.evaluate(SHIFT, 5000)
        silent = self.step(page, 'hold')
        rearm = self.step(page, 'up')
        page.evaluate(SHIFT, THRESHOLD + 1)
        second = self.step(page, 'hold')
        self.assertEqual(silent['emitted'], 1)
        self.assertTrue(rearm['tracking']['armed'])
        self.assertEqual(second['emitted'], 2)
        self.assertEqual(second['event']['id'], 2)
        brief = lambda s: {'y': s['y'], 'startY': s['tracking']['startY'], 'displacement': s['tracking']['displacement'],
                           'armed': s['tracking']['armed'], 'emitted': s['emitted']}
        ev['upwardReset'] = {'baseline': brief(base), 'after3000Down': brief(down), 'after1Up': brief(up),
                             'after3500More': brief(after), 'after4100FromRebound': brief(crossed),
                             'continuedDescent': brief(silent), 'upwardRearm': brief(rearm), 'secondFall': brief(second)}
        # A new catch rebaselines; holding the rope does not rearm. The anchor is
        # far below on a real grapplable element, so the rope pulls downward.
        base = self.baseline_at(page, 13000)
        page.evaluate(SHIFT, 3000)
        self.step(page, 'hold')
        n = page.evaluate('LONG_FALL.emitted')
        recoveries = page.evaluate('RECOVERIES.length')
        page.evaluate('''() => { const e = floors[0].elements.find(e => e.grapplable && e.surfaceRole !== 'hazard')
            Object.assign(grapnel, {throwed: true, grappled: true, shotStep: null, pos: [[ninja.x, ninja.y + 30000, e]]}) }''')
        caught = self.step(page, 'hold')
        self.assertTrue(caught['tracking']['wasGrappled'])
        self.assertEqual(caught['tracking']['startY'], caught['y'])
        self.assertEqual(caught['tracking']['displacement'], 0)
        run = page.evaluate(RUN, [4000, 2 * THRESHOLD])
        steps = run['steps']
        self.assertTrue(all(s['g'] for s in steps))
        self.assertTrue(all(s['start'] == caught['y'] for s in steps))
        self.assertGreater(steps[-1]['d'], 2 * THRESHOLD)
        self.assertEqual(page.evaluate('RECOVERIES.length'), recoveries)
        first = next(i for i, s in enumerate(steps) if s['e'])
        self.assertEqual(sum(s['e'] for s in steps), 1)
        self.assertGreater(steps[first]['d'], THRESHOLD)
        self.assertEqual(page.evaluate('LONG_FALL.emitted'), n + 1)
        ev['catchReset'] = {'before': {'startY': base['tracking']['startY'], 'displacementAtCatch': 3000},
                            'atCatch': brief(caught), 'heldRopeSteps': len(steps), 'eventsWhileHeld': 1,
                            'firstEmittingStep': first, 'trace': compact(steps, [first - 1, first])}
        # Real input: a mouse press while falling beside a grapplable element; the
        # production grapple flight acquires it and the catch step rebaselines.
        page.evaluate('''() => { const e = floors[0].elements.find(e => e.grapplable && e.surfaceRole !== 'hazard' && e.getPoints)
            const pts = e.getPoints(), xs = pts.map(p => p.x ?? p[0]), ys = pts.map(p => p.y ?? p[1])
            window.TARGET = {x: (Math.min(...xs) + Math.max(...xs)) / 2, y: Math.min(...ys)}
            ninja.x = TARGET.x; ninja.y = TARGET.y - 200; ninja.speedX = 0; ninja.speedY = 0
            Object.assign(grapnel, {throwed: false, grappled: false, pos: []}) }''')
        self.step(page, 'up')
        page.evaluate('() => { for (let i = 0; i < 3; i++) physics() }')
        falling = page.evaluate(DET)
        self.assertGreater(falling['tracking']['displacement'], 0)
        p = page.evaluate('''() => canvasCoordsToViewportCoords({
            x: (TARGET.x + screen.x) * scale[version], y: (TARGET.y + 2 + screen.y) * scale[version]})''')
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        run = page.evaluate('''() => { const out = [], step = LONG_FALL.step.bind(LONG_FALL)
            LONG_FALL.step = function() { const g = LONG_FALL.tracking().wasGrappled; step()
                out.push({y: ninja.y, start: LONG_FALL.tracking().startY, g: grapnel.isGrappled(), wasG: g}) }
            for (let i = 0; i < 120 && !out.some(s => s.g); i++) physics()
            for (let i = 0; i < 30; i++) physics()
            LONG_FALL.step = step
            return out }''')
        page.mouse.up()
        catch = next(i for i, s in enumerate(run) if s['g'])
        self.assertFalse(run[catch]['wasG'])
        self.assertEqual(run[catch]['start'], run[catch]['y'])
        self.assertLess(run[catch - 1]['start'], run[catch]['start'])
        # Held afterwards: the baseline moves only with upward motion, never per step from the rope.
        held = run[catch + 1:]
        self.assertTrue(all(s['g'] for s in held))
        for prev, s in zip(run[catch:], held):
            if s['start'] != prev['start']:
                self.assertLess(s['y'], prev['y'])
        ev['realInputCatch'] = {'displacementBeforePress': falling['tracking']['displacement'], 'catchStep': catch,
                                'aroundCatch': run[max(0, catch - 2):catch + 2], 'heldSteps': len(held),
                                'heldBaselineChangesOnlyOnUpwardSteps': True}
        ev['pageErrorsResets'] = page.errors
        self.assertEqual(page.errors, [])

    def test_03_yellow_drag_slows_without_reset(self):
        page = self.open()
        zone = page.evaluate('''() => { const z = floors[0].dragZones[0], pts = z.getPoints()
            const xs = pts.map(p => p.x ?? p[0]), ys = pts.map(p => p.y ?? p[1])
            return {id: z.id, left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys)} }''')
        cx = (zone['left'] + zone['right']) / 2
        cy = (zone['top'] + zone['bottom']) / 2
        # Baseline 3990 above the zone's centre via a real upward step in open air
        # beside the level, then shift into the zone, falling.
        page.evaluate(OPEN_AIR, [0, 0])
        page.evaluate('y => { ninja.y = y }', cy - 3990 + 1)
        base = self.step(page, 'up')
        page.evaluate('([x, y]) => { ninja.x = x; ninja.y = y; ninja.speedY = 12 }', [cx, cy])
        inside = page.evaluate('() => floors[0].dragZones.some(z => pointInPolygon(z.getPoints(), ninja.x, ninja.y))')
        run = page.evaluate('''() => { const out = [], step = LONG_FALL.step.bind(LONG_FALL)
            LONG_FALL.step = function() { const before = LONG_FALL.emitted; step(); const t = LONG_FALL.tracking()
                out.push({y: ninja.y, vy: ninja.speedY, start: t.startY, d: t.displacement, e: LONG_FALL.emitted - before,
                    inDrag: floors[0].dragZones.some(z => pointInPolygon(z.getPoints(), ninja.x, ninja.y))}) }
            const ticks = []
            for (let i = 0; i < 6; i++) { physics(); ticks.push({vyAfterDrag: ninja.speedY}) }
            LONG_FALL.step = step
            return {out, ticks} }''')
        steps = run['out']
        self.assertTrue(inside)
        self.assertTrue(any(s['inDrag'] for s in steps))
        speeds = [t['vyAfterDrag'] for t in run['ticks']]
        self.assertLess(speeds[0], 12 + 0.5)
        self.assertTrue(all(s['start'] == base['tracking']['startY'] for s in steps))
        first = next(i for i, s in enumerate(steps) if s['e'])
        self.assertEqual(sum(s['e'] for s in steps), 1)
        self.assertGreater(steps[first]['d'], THRESHOLD)
        self.evidence['fall-events']['yellowDrag'] = {'zone': zone, 'baselineY': base['tracking']['startY'],
            'startedInsideZone': inside, 'speedYAfterDragPerTick': speeds, 'baselineChanged': False,
            'events': 1, 'firstEmittingStep': first, 'trace': compact(steps, [first - 1, first])}
        self.evidence['fall-events']['pageErrorsDrag'] = page.errors
        self.assertEqual(page.errors, [])

    def test_04_recovery_teleport(self):
        page = self.open()
        lc = self.evidence['lifecycle']
        # Genuine free fall from 2600 above the spawn: 4000 is crossed before -1500.
        page.evaluate(OPEN_AIR, [2600, 0])
        self.step(page, 'up')
        run = page.evaluate(RUN, [2000, 'recovery'])
        steps = run['steps']
        first = next(i for i, s in enumerate(steps) if s['e'])
        rec = page.evaluate('RECOVERIES[0]')
        after = page.evaluate(DET)
        self.assertEqual(sum(s['e'] for s in steps), 1)
        self.assertEqual(rec['eventBefore'], 1)
        self.assertEqual(after['event']['id'], 1)
        spawn = page.evaluate('floors[0].level.spawn')
        self.assertEqual(after['y'], spawn['y'])
        self.assertEqual(after['tracking'], {'startY': spawn['y'], 'lastY': spawn['y'], 'armed': True,
                                             'wasGrappled': False, 'displacement': 0})
        rest = page.evaluate(RUN, [60, None])
        self.assertEqual(sum(s['e'] for s in rest['steps']), 0)
        self.assertEqual(page.evaluate('LONG_FALL.event.id'), 1)
        lc['genuineFallBeforeRecovery'] = {'startHeight': 2600, 'firstEmittingStep': first,
            'recoveryAfterSteps': len(steps), 'recovery': rec, 'trace': compact(steps, [first - 1, first]),
            'afterRecovery': after, 'spawn': spawn, 'eventsInNext60Ticks': 0, 'eventRetained': True}
        # Same-step crossing: 4000 and -1500 crossed by one production step; the
        # detector runs first, then the teleport keeps the event.
        cases = {}
        for name, height in (('crossesBoth', 2499.95), ('belowThreshold', 2499.8)):
            page.evaluate('() => { LONG_FALL.clearEvent(); RECOVERIES.length = 0 }')
            base = self.baseline_at(page, height)
            page.evaluate('y => { ninja.y = y; ninja.speedY = 0.1 - GRAVITY }', spawn['y'] + DEPTH - 0.01)
            n = page.evaluate('LONG_FALL.emitted')
            s = self.step(page)
            r = page.evaluate('RECOVERIES[0]')
            self.assertTrue(s['recovered'])
            cases[name] = {'baselineHeight': spawn['y'] - base['tracking']['startY'], 'heightAtRecovery': r['height'],
                           'displacementAtRecovery': r['y'] - base['tracking']['startY'],
                           'eventBeforeTeleport': r['eventBefore'], 'emitted': s['emitted'] - n,
                           'eventAfter': s['event'], 'trackingAfter': s['tracking']}
        self.assertEqual(cases['crossesBoth']['emitted'], 1)
        self.assertIsNotNone(cases['crossesBoth']['eventBeforeTeleport'])
        self.assertIsNotNone(cases['crossesBoth']['eventAfter'])
        self.assertGreater(cases['crossesBoth']['displacementAtRecovery'], THRESHOLD)
        self.assertEqual(cases['belowThreshold']['emitted'], 0)
        self.assertLessEqual(cases['belowThreshold']['displacementAtRecovery'], THRESHOLD)
        self.assertIsNone(cases['belowThreshold']['eventAfter'])
        for c in cases.values():
            self.assertEqual(c['trackingAfter']['displacement'], 0)
            self.assertEqual(c['trackingAfter']['startY'], spawn['y'])
        lc['sameStepRecovery'] = cases
        # Short falls from the spawn recover repeatedly; the 1500-unit upward teleport
        # and the next fall never add up to an event.
        page.evaluate('() => { LONG_FALL.clearEvent(); RECOVERIES.length = 0 }')
        n = page.evaluate('LONG_FALL.emitted')
        repeats = []
        for _ in range(4):
            page.evaluate(OPEN_AIR, [0, 0])
            page.evaluate('() => { window.RECOVERED = (window.RECOVERED || 0) + RECOVERIES.length; RECOVERIES.length = 0 }')
            r = page.evaluate(RUN, [400, 'recovery'])
            repeats.append({'steps': len(r['steps']), 'maxDisplacement': max(s['d'] for s in r['steps'])})
        self.assertEqual(page.evaluate('RECOVERED + RECOVERIES.length'), 4)
        self.assertEqual(page.evaluate('LONG_FALL.emitted'), n)
        self.assertTrue(all(r['maxDisplacement'] < THRESHOLD for r in repeats))
        lc['repeatedShortRecoveries'] = {'recoveries': 4, 'events': 0, 'falls': repeats}
        lc['pageErrorsRecovery'] = page.errors
        self.assertEqual(page.errors, [])

    def test_05_spawn_restart_reload(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = self.open(context)
        lc = self.evidence['lifecycle']
        # Spawn: boot ticks never emit.
        boot = page.evaluate(RUN, [120, None])
        self.assertEqual(page.evaluate('LONG_FALL.emitted'), 0)
        lc['spawn'] = {'ticks': 120, 'events': 0, 'maxDisplacement': max(s['d'] for s in boot['steps']),
                       'firstStep': boot['steps'][0]}
        # Restart from 9000 up, 3999 into a descent, with an event already shown.
        page.evaluate(OPEN_AIR, [13000, 0])
        self.step(page, 'up')
        page.evaluate(SHIFT, THRESHOLD + 1)
        self.assertEqual(self.step(page, 'hold')['emitted'], 1)
        self.baseline_at(page, 9000)
        page.evaluate(SHIFT, 3999)
        pre = self.step(page, 'hold')
        page.evaluate('() => CLIMB_UI.restart()')
        page.evaluate('() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
        eventAfterRestart = page.evaluate('LONG_FALL.event')
        run = page.evaluate(RUN, [120, None])
        self.assertIsNone(eventAfterRestart)
        self.assertEqual(sum(s['e'] for s in run['steps']), 0)
        self.assertEqual(page.evaluate('LONG_FALL.emitted'), 1)
        self.assertEqual(run['steps'][0]['start'], run['steps'][0]['y'])
        lc['restart'] = {'before': {'displacement': pre['tracking']['displacement'], 'y': pre['y'], 'eventId': pre['event']['id']},
                         'eventAfterRestart': eventAfterRestart, 'firstStepAfter': run['steps'][0],
                         'jumpToSpawn': run['steps'][0]['y'] - pre['y'], 'eventsIn120Ticks': 0}
        # Production save restore (the reload path) to a point 5000 below the current one.
        self.baseline_at(page, 9000)
        page.evaluate(SHIFT, 3000)
        self.step(page, 'hold')
        restore = page.evaluate('''() => { const s = captureClimbState(); s.player.y += 5000; s.player.speedY = 0
            restoreClimbState(s); window.requestAnimationFrame = () => 0; return {y: ninja.y} }''')
        run = page.evaluate(RUN, [30, None])
        self.assertEqual(sum(s['e'] for s in run['steps']), 0)
        self.assertEqual(run['steps'][0]['start'], run['steps'][0]['y'])
        lc['restoreClimbState'] = {'restoredY': restore['y'], 'discontinuity': 8000, 'firstStepAfter': run['steps'][0],
                                   'events': 0}
        # Real page reload: the saved state carries no reaction and the reloaded run emits nothing.
        page.evaluate('() => { const s = floors[0].level.spawn; ninja.x = s.x; ninja.y = s.y - 50; ninja.speedY = 0 }')
        self.baseline_at(page, 13000)
        page.evaluate(SHIFT, THRESHOLD + 1)
        self.assertIsNotNone(self.step(page, 'hold')['event'])
        page.evaluate('() => { const s = floors[0].level.spawn; ninja.x = s.x; ninja.y = s.y - 50 }')
        page.evaluate('() => PROGRESS.flushClimb()')
        page.wait_for_function('k => { const v = JSON.parse(localStorage.getItem(k) || "null")'
                               ' && JSON.parse(localStorage.getItem(k)); return v && v.player.y === ninja.y }', arg=CLIMB_KEY)
        saved = page.evaluate('k => localStorage.getItem(k)', CLIMB_KEY)
        errors = list(page.errors)
        page.close()
        page2 = context.new_page()
        page2.errors = []
        page2.on('pageerror', lambda e: page2.errors.append('pageerror: %s' % e))
        page2.goto(self.url)
        wait_for_boot_run(page2)
        page2.evaluate(SETUP)
        reloaded = page2.evaluate(DET)
        page2.evaluate('() => menu.unPause()')
        run = page2.evaluate(RUN, [60, None])
        self.assertIsNone(reloaded['event'])
        self.assertEqual(reloaded['emitted'], 0)
        self.assertEqual(page2.evaluate('LONG_FALL.emitted'), 0)
        for word in ['LONG_FALL', 'longFall', 'reaction', 'message'] + MESSAGES:
            self.assertNotIn(word, saved)
        self.assertEqual(sorted(json.loads(saved)), sorted(['version', 'levelVersion', 'layoutId', 'simulationTick', 'stats',
                                                             'player', 'input', 'upgrades', 'elements', 'grapple',
                                                             'grapnelMode', 'usedDouble', 'fallHintShown',
                                                             'doubleOfferShown']))
        lc['reload'] = {'eventBeforeReload': True, 'savedKeys': sorted(json.loads(saved)),
                        'savedContainsReaction': False, 'afterReload': reloaded, 'eventsIn60Ticks': 0,
                        'firstStepAfter': run['steps'][0] if run['steps'] else None}
        lc['pageErrorsLifecycle'] = errors + page2.errors
        self.assertEqual(errors + page2.errors, [])

    def test_06_paused_hidden_completed_other_modes(self):
        page = self.open()
        lc = self.evidence['lifecycle']
        frozen = {}

        def armed_fall():
            # A descent of 3999 that one more simulated step would carry past 4000.
            self.baseline_at(page, 9000)
            page.evaluate(SHIFT, 3999)
            self.step(page, 'hold')
            page.evaluate('() => { ninja.speedY = 20 }')
            return page.evaluate('LONG_FALL.emitted')

        def frozen_case(name, freeze, unfreeze):
            n = armed_fall()
            y = page.evaluate('ninja.y')
            page.evaluate(freeze)
            page.evaluate('() => { for (let i = 0; i < 30; i++) physics() }')
            s = page.evaluate(DET)
            self.assertEqual(s['emitted'], n)
            self.assertEqual(s['y'], y)
            frozen[name] = {'ticks': 30, 'events': s['emitted'] - n, 'yUnchanged': s['y'] == y,
                            'displacement': s['tracking']['displacement']}
            if unfreeze:
                page.evaluate(unfreeze)
                page.evaluate('() => physics()')
                frozen[name]['eventsAfterResume'] = page.evaluate('LONG_FALL.emitted') - n

        page.keyboard.press('p')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        page.keyboard.press('p')
        frozen_case('paused', "() => menu.startPause()", "() => menu.unPause()")
        frozen_case('hidden', '''() => { Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true})
            document.dispatchEvent(new Event('visibilitychange')) }''',
                    '''() => { delete document.visibilityState; menu.unPause() }''')
        frozen_case('hostPaused', '() => { hostPaused = true }', '() => { hostPaused = false }')
        self.assertTrue(frozen['hidden']['yUnchanged'])
        for name in ('paused', 'hidden', 'hostPaused'):
            self.assertEqual(frozen[name]['eventsAfterResume'], 1)
        frozen_case('completed', '() => CLIMB_UI.complete()', None)
        page.evaluate('() => { for (let i = 0; i < 10; i++) calcPhysics() }')
        self.assertEqual(page.evaluate('LONG_FALL.emitted'), 3)
        lc['frozen'] = frozen
        # Classic and bad never call the detector, even falling far.
        for mode in ('classic', 'bad'):
            select_mode(page, mode)
            page.evaluate('() => { menu.unPause(); window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
            r = page.evaluate('''() => { const step = LONG_FALL.step; let calls = 0
                LONG_FALL.step = function() { calls++; return step.apply(this, arguments) }
                const n = LONG_FALL.emitted, y = ninja.y
                for (let i = 0; i < 40; i++) { ninja.speedY = 60; physics() }
                LONG_FALL.step = step
                return {version, detectorCalls: calls, events: LONG_FALL.emitted - n, event: LONG_FALL.event,
                    descended: ninja.y - y} }''')
            self.assertEqual(r['version'], mode)
            self.assertEqual((r['detectorCalls'], r['events']), (0, 0))
            self.assertIsNone(r['event'])
            lc[mode] = r
        lc['pageErrorsFrozen'] = page.errors
        self.assertEqual(page.errors, [])

    def test_07_message_pool(self):
        page = self.open()
        mp = self.evidence['message-pool']
        pool = page.evaluate('[...LONG_FALL_MESSAGES]')
        self.assertEqual(pool, MESSAGES)
        self.assertEqual(len(set(pool)), 12)
        for phrase in EXCLUDED:
            self.assertNotIn(phrase, pool)
        sources = {p: (ROOT / p).read_text(encoding='utf-8') for p in ('longfall.js', 'i18n.js', 'index.html')}
        hits = [(p, x) for p, s in sources.items() for x in EXCLUDED if x in s]
        self.assertEqual(hits, [])
        # Equal intervals: index k covers exactly [k/12, (k+1)/12).
        intervals = page.evaluate('''() => { const n = 12, out = []
            for (let k = 0; k < n; k++) {
                const lo = k / n, hi = (k + 1) / n, below = hi - 1e-12
                out.push({k, lo, hi, atLo: LONG_FALL.pick(lo).index, mid: LONG_FALL.pick((k + 0.5) / n).index,
                    justBelowHi: LONG_FALL.pick(below).index, message: LONG_FALL.pick((k + 0.5) / n).message})
            }
            return out }''')
        for iv in intervals:
            self.assertEqual((iv['atLo'], iv['mid'], iv['justBelowHi']), (iv['k'],) * 3)
            self.assertAlmostEqual(iv['hi'] - iv['lo'], 1 / 12, places=15)
            self.assertEqual(iv['message'], MESSAGES[iv['k']])
        # Every float in a dense grid of [0, 1) maps in range; out-of-domain values clamp.
        grid = page.evaluate('''() => { const counts = Array(12).fill(0); let bad = 0
            for (let i = 0; i < 120000; i++) { const p = LONG_FALL.pick(i / 120000)
                if (!(p.index >= 0 && p.index < 12) || LONG_FALL_MESSAGES[p.index] !== p.message) bad++; else counts[p.index]++ }
            const edge = [0, 1 - Number.EPSILON / 2, -0.5, 1, 7, NaN].map(r => LONG_FALL.pick(r).index)
            return {counts, bad, edge} }''')
        self.assertEqual(grid['bad'], 0)
        self.assertEqual(grid['counts'], [10000] * 12)
        self.assertEqual(grid['edge'], [0, 11, 0, 11, 11, 0])
        # Injected source through production emission: every entry, consecutive repeats allowed.
        samples = [(k + 0.5) / 12 for k in range(12)] + [0.5 / 12, 0.5 / 12]
        page.evaluate('s => { let i = 0; LONG_FALL.setRandom(() => s[i++]) }', samples)
        page.evaluate(HINT_SPENT)
        emitted = []
        for _ in samples:
            self.baseline_at(page, 9000)
            page.evaluate(SHIFT, THRESHOLD + 1)
            emitted.append(self.step(page, 'hold')['event'])
        page.evaluate('() => LONG_FALL.setRandom(null)')
        self.assertEqual([e['message'] for e in emitted], MESSAGES + [MESSAGES[0], MESSAGES[0]])
        self.assertEqual(len({e['id'] for e in emitted}), len(samples))
        mp.update({'messages': pool, 'count': len(pool), 'excluded': EXCLUDED, 'excludedFoundInPool': [],
                   'excludedFoundInSources': hits, 'intervals': intervals, 'denseGrid': grid,
                   'injectedEmission': {'samples': samples, 'messages': [e['message'] for e in emitted],
                                        'consecutiveRepeat': True},
                   'pageErrors': page.errors})
        self.assertEqual(page.errors, [])

    def test_08_isolation_inert_vs_enabled(self):
        iso = self.evidence['isolation']
        runs = {}
        for mode in ('inert', 'enabled'):
            page = self.open()
            if mode == 'inert':
                page.evaluate('() => { LONG_FALL.step = function() {}; LONG_FALL.restartTracking = function() {} }')
            # Seed the shared gameplay RNG identically in both runs.
            page.evaluate('''() => { let s = 12345; const counted = Math.random
                Math.random = function() { counted(); s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648 } }''')
            # Boot runs real frames for a variable time; start both runs from one
            # canonical state through the production restore.
            page.evaluate('''() => { const s = captureClimbState(), sp = floors[0].level.spawn
                s.simulationTick = 0; s.stats = {elapsedActiveMs: 0, currentHeight: 0, maxHeight: 0, completed: false}
                Object.assign(s.player, {x: sp.x, y: sp.y, speedX: 0, speedY: 0})
                s.upgrades.range = true; s.input = {pressHeld: false, stalePress: false}
                s.grapple = {throwed: false, grappled: false, speedX: 0, speedY: 0, traveled: 0, shotStep: null, segments: []}
                restoreClimbState(s); RECOVERIES.length = 0; GAMEPLAY_RNG_CALLS = 0 }''')
            page.evaluate(OPEN_AIR, [9000, 0])
            page.evaluate('() => { for (let i = 0; i < 600; i++) physics() }')
            mid = page.evaluate(STATE)
            # Fall to recovery, then a real grapple press at the spawn and more ticks.
            page.evaluate(OPEN_AIR, [2600, 0])
            page.evaluate('() => { RECOVERIES.length = 0; for (let i = 0; i < 2000 && !RECOVERIES.length; i++) physics() }')
            p = page.evaluate('''() => canvasCoordsToViewportCoords({
                x: (ninja.x + 80 + screen.x) * scale[version], y: (ninja.y - 160 + screen.y) * scale[version]})''')
            page.mouse.move(p['x'], p['y'])
            page.mouse.up()
            page.mouse.down()
            page.evaluate('() => { for (let i = 0; i < 90; i++) physics() }')
            page.mouse.up()
            page.evaluate('() => { for (let i = 0; i < 30; i++) physics() }')
            end = page.evaluate(STATE)
            runs[mode] = {'mid': mid, 'end': end, 'emitted': page.evaluate('LONG_FALL.emitted'),
                          'pageErrors': page.errors}
            self.assertEqual(page.errors, [])
        self.assertEqual(runs['inert']['emitted'], 0)
        self.assertGreaterEqual(runs['enabled']['emitted'], 2)
        for phase in ('mid', 'end'):
            # TASK-720: only the saved first-fall flag may differ (set by the enabled detector).
            hint = {}
            for mode in runs:
                save = json.loads(runs[mode][phase]['save'])
                hint[mode] = save.pop('fallHintShown')
                runs[mode][phase]['save'] = json.dumps(save)
            self.assertEqual(hint, {'inert': False, 'enabled': True}, phase)
            for key in runs['inert'][phase]:
                self.assertEqual(runs['inert'][phase][key], runs['enabled'][phase][key], (phase, key))
        self.assertEqual(runs['enabled']['end']['recoveries'], 1)
        # The default reaction source never touches Math.random.
        page = self.open()
        self.baseline_at(page, 9000)
        n = page.evaluate('GAMEPLAY_RNG_CALLS')
        page.evaluate(SHIFT, THRESHOLD + 1)
        ev = self.step(page, 'hold')
        emitCalls = page.evaluate('GAMEPLAY_RNG_CALLS') - n
        self.assertIsNotNone(ev['event'])
        self.assertEqual(emitCalls, 0)
        save = runs['enabled']['end']['save']
        iso.update({'scenario': 'free fall from 9000 (600 ticks), fall from 2600 to recovery, real grapple press at spawn, 120 ticks',
                    'inertEvents': runs['inert']['emitted'], 'enabledEvents': runs['enabled']['emitted'],
                    'identical': {p: runs['inert'][p] == runs['enabled'][p] for p in ('mid', 'end')},
                    'gameplayRngCalls': {m: runs[m]['end']['rngCalls'] for m in runs},
                    'gameplayRngCallsDuringDefaultEmission': emitCalls,
                    'end': {k: v for k, v in runs['enabled']['end'].items() if k not in ('elements', 'save')},
                    'elementCount': len(runs['enabled']['end']['elements']),
                    'elementsIdentical': runs['inert']['end']['elements'] == runs['enabled']['end']['elements'],
                    'saveKeys': sorted(json.loads(save)), 'saveIdentical': runs['inert']['end']['save'] == save,
                    'pageErrors': runs['inert']['pageErrors'] + runs['enabled']['pageErrors'] + page.errors})
        self.assertEqual(page.errors, [])


# ---- TASK-666: rendering ----

ANCHORS = [[0.25, 0.30], [0.75, 0.30], [0.25, 0.50], [0.75, 0.50], [0.25, 0.70], [0.75, 0.70]]
MARGIN = 16
VIEWPORTS = {'desktop': dict(viewport={'width': 1280, 'height': 720}, device_scale_factor=1),
             # The 390x844 phone turned to landscape (upright, the run waits paused
             # under the turn-the-phone prompt; see test_climb_tutorial_legend)
             'touch': dict(viewport={'width': 844, 'height': 390}, device_scale_factor=2,
                           is_mobile=True, has_touch=True)}

# Freeze the loop, record blits of the message sprite on the game canvas, and
# drive the real gameLoop at one physics step per frame.
RENDER_SETUP = '''() => {
    TUTORIAL_HINT.visible = false
    window.BLITS = []
    const blit = ctx.drawImage
    ctx.drawImage = function(img) {
        if (img === FALL_MESSAGE.sprite) {
            const m = this.getTransform()
            BLITS.push({alpha: this.globalAlpha, a: m.a, b: m.b, e: m.e, f: m.f})
        }
        return blit.apply(this, arguments)
    }
    window.FT = 1000
    window.FRAMES = n => { for (let i = 0; i < n; i++) { FT += physicsStepMs; gameLoop(FT) } }
    resetPhysicsTiming(); FRAMES(1)
}'''

# A real long fall in open air beside the level (production detector), then the
# player back near the spawn; rf is the reaction (anchor, angle) source, msg the phrase pick.
EMIT = '''([rf, msg]) => {
    if (rf) { const s = rf.slice(); FALL_MESSAGE.setRandom(() => s.shift()) }
    if (msg !== null) LONG_FALL.setRandom(() => msg)
    const l = floors[0].level
    ninja.x = l.bounds.right + 4000; ninja.y = l.spawn.y - 9000; ninja.speedX = 0; ninja.speedY = -1 - GRAVITY
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null})
    calcPhysics(); ninja.speedY = 0; ninja.y += 4001; calcPhysics()
    ninja.x = l.spawn.x; ninja.y = l.spawn.y - 5; ninja.speedX = 0; ninja.speedY = 0
    FALL_MESSAGE.sync()
    LONG_FALL.setRandom(null); FALL_MESSAGE.setRandom(null)
    return LONG_FALL.event
}'''

# Message state after one production draw().
MSG = '''() => { BLITS.length = 0; draw(); const L = FALL_MESSAGE.layout
    return {eventId: FALL_MESSAGE.event ? FALL_MESSAGE.event.id : null, longFallEventId: LONG_FALL.event ? LONG_FALL.event.id : null,
        message: L ? L.text : null, anchorIndex: FALL_MESSAGE.anchorIndex, angle: FALL_MESSAGE.angle,
        elapsedMs: FALL_MESSAGE.elapsedMs, expired: FALL_MESSAGE.expired, opacity: FALL_MESSAGE.opacity(),
        visible: FALL_MESSAGE.visible(), blits: BLITS.slice(), layoutCount: FALL_MESSAGE.layoutCount,
        layout: L && {x: L.x, y: L.y, size: L.size, anchorIndex: L.anchorIndex, bounds: L.bounds, viewport: L.viewport},
        paused: menu.gamePaused, completed: !!floors[0].climbStats.completed} }'''

# Every phrase x anchor x angle through the production layout against the real
# HUD boxes, plus an independent check that a size reduction happened only
# after every anchor failed at the larger size.
LAYOUTS = '''([messages, angles]) => {
    const F = FALL_MESSAGE, css = getCanvasCssRect(), reserved = F.reservedRects(canvas)
    const W = css.width, H = css.height, m = F.marginCss, k = canvas.width / W
    const base = Math.max(F.minSizeCss, H * F.sizeRatio), c = document.createElement('canvas').getContext('2d')
    const hits = (b, r) => b.left < r.x + r.width && r.x < b.right && b.top < r.y + r.height && r.y < b.bottom
    const anchorFails = (text, size, angle) => F.anchors.map(([ax, ay]) => {
        const box = F.measure(c, text, size), rad = angle * Math.PI / 180
        box.right = box.left + Math.ceil((box.right - box.left) * k) / k
        box.bottom = box.top + Math.ceil((box.bottom - box.top) * k) / k
        const pts = [[box.left, box.top], [box.right, box.top], [box.right, box.bottom], [box.left, box.bottom]]
            .map(([x, y]) => [x * Math.cos(rad) - y * Math.sin(rad), x * Math.sin(rad) + y * Math.cos(rad)])
        const l = Math.min(...pts.map(p => p[0])), r = Math.max(...pts.map(p => p[0]))
        const t = Math.min(...pts.map(p => p[1])), b = Math.max(...pts.map(p => p[1]))
        if (r - l > W - 2 * m || b - t > H - 2 * m) return 'size'
        const x = Math.min(Math.max(ax * W, m - l), W - m - r), y = Math.min(Math.max(ay * H, m - t), H - m - b)
        return reserved.some(q => hits({left: x + l, right: x + r, top: y + t, bottom: y + b}, q)) ? 'hud' : null })
    const out = []
    for (const text of messages) for (let a = 0; a < 6; a++) for (const angle of angles) {
        const L = F.layoutFor(text, a, angle, canvas, reserved)
        const xs = L.corners.map(p => p[0]), ys = L.corners.map(p => p[1])
        const rect = {left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys)}
        const smaller = L.size < base - 1e-9
        out.push({text, preferred: a, angle, used: L.anchorIndex, size: +L.size.toFixed(3), center: [+L.x.toFixed(2), +L.y.toFixed(2)],
            rect: Object.fromEntries(Object.entries(rect).map(([key, v]) => [key, +v.toFixed(2)])),
            inMargins: rect.left >= m - 1e-6 && rect.top >= m - 1e-6 && rect.right <= W - m + 1e-6 && rect.bottom <= H - m + 1e-6,
            hudClear: !reserved.some(q => hits(rect, q)), fitted: L.fitted, shifted: L.shifted, attempts: L.attempts,
            reduced: smaller, allAnchorsFailedAtBase: smaller ? anchorFails(text, base, angle).every(f => f) : null,
            preferredFailedIfMoved: L.anchorIndex === a ? null : anchorFails(text, L.size, angle)[a] !== null})
    }
    return {viewport: {width: W, height: H, canvas: [canvas.width, canvas.height], margin: m, baseSize: base},
        reserved: reserved.map(r => ({kind: r.kind, name: r.name, x: +r.x.toFixed(1), y: +r.y.toFixed(1),
            width: +r.width.toFixed(1), height: +r.height.toFixed(1)})), layouts: out}
}'''

# Ink of the production draw() of the current message on a blank canvas of the
# game canvas's size at full opacity: alpha bounding box (CSS px), whether the
# baked sprite's border is empty (no glyph or glow clipped), and sampled colours.
INK = '''() => {
    const F = FALL_MESSAGE, css = getCanvasCssRect(), c = document.createElement('canvas')
    c.width = canvas.width; c.height = canvas.height
    const keep = F.elapsedMs; F.elapsedMs = 0
    F.draw(c.getContext('2d')); F.elapsedMs = keep
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data, kx = c.width / css.width
    let l = Infinity, r = -1, t = Infinity, b = -1, n = 0
    for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) if (d[(y * c.width + x) * 4 + 3] > 2) {
        n++; if (x < l) l = x; if (x > r) r = x; if (y < t) t = y; if (y > b) b = y }
    const s = F.sprite, sd = s.getContext('2d').getImageData(0, 0, s.width, s.height).data
    let border = 0
    for (let y = 0; y < s.height; y++) for (let x = 0; x < s.width; x++)
        if ((x === 0 || y === 0 || x === s.width - 1 || y === s.height - 1) && sd[(y * s.width + x) * 4 + 3] > 2) border++
    let face = null, halo = null
    for (let i = 0; i < sd.length; i += 4) {
        if (sd[i + 3] === 255 && sd[i] > 240 && !face) face = [sd[i], sd[i + 1], sd[i + 2]]
        if (sd[i + 3] > 30 && sd[i + 3] < 120 && sd[i + 2] > sd[i + 1] + 30 && !halo) halo = [sd[i], sd[i + 1], sd[i + 2], sd[i + 3]]
    }
    return {inkPixels: n, ink: {left: l / kx, right: (r + 1) / kx, top: t / kx, bottom: (b + 1) / kx},
        bounds: F.layout.bounds, viewport: {width: css.width, height: css.height}, spriteBorderInk: border,
        sprite: [s.width, s.height], face, halo}
}'''

ISO_KEYS = '''() => ({dom: document.querySelectorAll('*').length, world: Object.keys(floors[0]).sort(),
    ninja: Object.keys(ninja).sort(), grapnel: Object.keys(grapnel).sort(), elements: floors[0].elements.length,
    dragZones: (floors[0].dragZones || []).length, byId: floors[0].byId ? floors[0].byId.size : null,
    storage: Object.keys(localStorage).sort()})'''


def within(inner, outer, tol):
    return (inner['left'] >= outer['left'] - tol and inner['right'] <= outer['right'] + tol and
            inner['top'] >= outer['top'] - tol and inner['bottom'] <= outer['bottom'] + tol)


class LongFallRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        EVIDENCE.update({'layout': {}, 'timing': {}})
        EVIDENCE.setdefault('isolation', {})['render'] = {}
        cls.frames = {}

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        out = os.environ.get('LONG_FALL_EVIDENCE_DIR')
        if out and cls.frames:
            cls.compose(Path(out))

    @classmethod
    def compose(cls, out):
        from PIL import Image, ImageDraw, ImageFont
        try:
            font = ImageFont.truetype('DejaVuSans.ttf', 15)
        except OSError:
            font = ImageFont.load_default()
        cell, label = (560, 315), 46
        rows = [k for k in ('desktop', 'touch') if k in cls.frames]
        concept = Image.open(ROOT / 'artifacts/concepts/big-fall-message-v2.png').convert('RGB')
        concept.thumbnail((3 * cell[0], 10000))
        sheet = Image.new('RGB', (3 * cell[0] + 20, len(rows) * (cell[1] + label) + concept.height + 3 * label), '#0b0a1e')
        draw = ImageDraw.Draw(sheet)
        y = 0
        for kind in rows:
            for i, (name, png, note) in enumerate(cls.frames[kind]):
                img = Image.open(io.BytesIO(png)).convert('RGB')
                img.thumbnail(cell)
                sheet.paste(img, (10 + i * cell[0], y + label))
                draw.text((10 + i * cell[0], y + 4), f'PRODUCTION {kind} {name}\n{note}', fill='#e8e0ff', font=font)
            y += cell[1] + label
        draw.text((10, y + 10), 'CONCEPT REFERENCE (artifacts/concepts/big-fall-message-v2.png) - not gameplay output',
                  fill='#ffd27a', font=font)
        sheet.paste(concept, (10, y + 2 * label))
        Path(out).mkdir(parents=True, exist_ok=True)
        sheet.save(Path(out) / 'message-frames.png', optimize=True)

    def open(self, kind='desktop', context=None):
        if context is None:
            context = self.browser.new_context(locale='en-US', **VIEWPORTS[kind])
            self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.on('console', lambda m: m.type == 'error' and page.errors.append('console: %s' % m.text))
        page.goto(self.url)
        wait_for_boot_run(page)
        if page.evaluate('menu.gamePaused'):
            page.evaluate('menu.unPause()')
        page.evaluate(SETUP)
        page.evaluate(RENDER_SETUP)
        return page

    def emit(self, page, anchor=None, angle_r=None, msg=None):
        rf = None if anchor is None else [(anchor + 0.5) / 6, angle_r]
        return page.evaluate(EMIT, [rf, msg])

    def msg(self, page):
        return page.evaluate(MSG)

    def resize(self, page, size):
        page.set_viewport_size(size)
        page.wait_for_function('''() => { const r = getCanvasCssRect()
            return width === computeLogicalWidth() && Math.abs(parseFloat(canvas.style.width) - r.width) < 0.5 && Math.abs(parseFloat(canvas.style.height) - r.height) < 0.5 }''')

    def test_09_layout_all_phrases_anchors_angles(self):
        lay = EVIDENCE['layout']
        for kind in VIEWPORTS:
            page = self.open(kind)
            page.evaluate(HINT_SPENT)
            res = page.evaluate(LAYOUTS, [MESSAGES, [-15, 0, 15]])
            L = res['layouts']
            self.assertEqual(len(L), 12 * 6 * 3)
            self.assertEqual(sorted({x['text'] for x in L}), sorted(MESSAGES))
            names = {r['name'] for r in res['reserved']}
            self.assertTrue(any(n.startswith('Height') for n in names), names)
            self.assertIn('button', {r['kind'] for r in res['reserved']})
            for x in L:
                self.assertTrue(x['inMargins'], x)
                self.assertTrue(x['hudClear'], x)
                self.assertTrue(x['fitted'], x)
                if x['reduced']:
                    self.assertTrue(x['allAnchorsFailedAtBase'], x)
                if x['used'] != x['preferred']:
                    self.assertTrue(x['preferredFailedIfMoved'], x)
                if not x['shifted']:
                    ax, ay = ANCHORS[x['used']]
                    self.assertAlmostEqual(x['center'][0], ax * res['viewport']['width'], places=1)
                    self.assertAlmostEqual(x['center'][1], ay * res['viewport']['height'], places=1)
            longest = max(MESSAGES, key=len)
            # Measured ink of real draws (longest phrase at every anchor and both
            # endpoints, each phrase upright) inside the layout bounds and margins.
            ink = []
            cases = [(longest, a, r) for a in range(6) for r in (0.0, 1.0)] + [(m, 3, 0.5) for m in MESSAGES]
            for text, a, r in cases:
                self.emit(page, a, r, (MESSAGES.index(text) + 0.5) / 12)
                st = self.msg(page)
                self.assertEqual(st['message'], text)
                self.assertEqual(st['anchorIndex'], a)
                self.assertAlmostEqual(st['angle'], -15 + 30 * r, places=9)
                self.assertEqual(len(st['blits']), 1)
                i = page.evaluate(INK)
                W, H = i['viewport']['width'], i['viewport']['height']
                self.assertGreater(i['inkPixels'], 100)
                self.assertEqual(i['spriteBorderInk'], 0)
                self.assertTrue(within(i['ink'], i['bounds'], 1.0), i)
                self.assertTrue(within(i['ink'], {'left': MARGIN, 'top': MARGIN, 'right': W - MARGIN, 'bottom': H - MARGIN}, 1.0), i)
                hud = [q for q in res['reserved'] if i['ink']['left'] < q['x'] + q['width'] and q['x'] < i['ink']['right']
                       and i['ink']['top'] < q['y'] + q['height'] and q['y'] < i['ink']['bottom']]
                self.assertEqual(hud, [])
                ink.append({'text': text, 'anchor': a, 'angle': st['angle'], 'used': st['layout']['anchorIndex'],
                            'size': round(st['layout']['size'], 3), 'ink': {k: round(v, 2) for k, v in i['ink'].items()},
                            'bounds': {k: round(v, 2) for k, v in i['bounds'].items()}, 'inkPixels': i['inkPixels'],
                            'spriteBorderInk': i['spriteBorderInk']})
            face, halo = i['face'], i['halo']
            self.assertTrue(face and min(face) >= 220 and face[0] > face[2], face)
            self.assertTrue(halo and halo[2] > halo[1] + 30, halo)
            # Normal frames: no re-randomization, drift or re-layout.
            self.emit(page, 1, 1.0, (MESSAGES.index(longest) + 0.5) / 12)
            page.evaluate('FRAMES(3)')
            before = self.msg(page)
            page.evaluate('FRAMES(40)')
            steady = self.msg(page)
            self.assertEqual((steady['eventId'], steady['anchorIndex'], steady['angle'], steady['layout'], steady['layoutCount']),
                             (before['eventId'], before['anchorIndex'], before['angle'], before['layout'], before['layoutCount']))
            transforms = {(b['a'], b['b'], b['e'], b['f']) for b in before['blits'] + steady['blits']}
            self.assertEqual(len(transforms), 1)
            # Resize: same message, anchor and angle; safe bounds recomputed for the new size.
            vp = VIEWPORTS[kind]['viewport']
            small = {'width': vp['width'] * 3 // 4, 'height': vp['height']}
            self.resize(page, small)
            page.evaluate('FRAMES(1)')
            resized = self.msg(page)
            self.resize(page, vp)
            page.evaluate('FRAMES(1)')
            restored = self.msg(page)
            self.assertEqual((resized['eventId'], resized['message'], resized['anchorIndex'], resized['angle']),
                             (before['eventId'], before['message'], before['anchorIndex'], before['angle']))
            self.assertGreater(resized['layoutCount'], before['layoutCount'])
            self.assertNotEqual(resized['layout']['viewport'], before['layout']['viewport'])
            rv = resized['layout']['viewport']
            self.assertTrue(within(resized['layout']['bounds'], {'left': MARGIN, 'top': MARGIN, 'right': rv['width'] - MARGIN,
                                                                 'bottom': rv['height'] - MARGIN}, 1e-6), resized)
            self.assertEqual(restored['layout'], before['layout'])
            self.assertEqual((restored['eventId'], restored['angle']), (before['eventId'], before['angle']))
            self.assertGreater(restored['elapsedMs'], before['elapsedMs'])
            lay[kind] = dict(res, inkChecks=ink, colors={'face': face, 'halo': halo},
                             counts={'layouts': len(L), 'phrases': len({x['text'] for x in L}), 'anchors': 6, 'angles': [-15, 0, 15],
                                     'inMargins': sum(x['inMargins'] for x in L), 'hudClear': sum(x['hudClear'] for x in L),
                                     'reduced': sum(x['reduced'] for x in L), 'moved': sum(x['used'] != x['preferred'] for x in L),
                                     'shifted': sum(x['shifted'] for x in L), 'inkChecks': len(ink)},
                             resize={'before': before['layout'], 'steadyAfter40Frames': steady['layout'],
                                     'steadyBlitTransforms': len(transforms), 'resizedTo': small,
                                     'resized': resized['layout'], 'restored': restored['layout'],
                                     'eventId': [before['eventId'], resized['eventId'], restored['eventId']],
                                     'message': [before['message'], resized['message']],
                                     'anchorIndex': [before['anchorIndex'], resized['anchorIndex'], restored['anchorIndex']],
                                     'angle': [before['angle'], resized['angle'], restored['angle']],
                                     'layoutCount': [before['layoutCount'], steady['layoutCount'], resized['layoutCount'],
                                                     restored['layoutCount']]},
                             pageErrors=page.errors)
            self.assertEqual(page.errors, [])
            print('PASS layout %s: %d layouts in margins and clear of %d HUD boxes, %d ink checks' %
                  (kind, len(L), len(res['reserved']), len(ink)), flush=True)

    def test_10_timing_and_lifecycle(self):
        tm = EVIDENCE['timing']
        page = self.open()
        self.assertIsNotNone(self.emit(page, 2, 0.25, 0.5 / 12))
        samples = {'0': self.msg(page)}
        for target in (1500, 3000, 4500, 5983):
            page.evaluate('t => { while (FALL_MESSAGE.elapsedMs < t - 1e-6) FRAMES(1) }', target)
            samples[str(target)] = self.msg(page)
        page.evaluate('FRAMES(1)')
        samples['6000'] = self.msg(page)
        # TASK-703: 6000 ms with the same (1 - t)^2 curve, so opacity at t equals
        # the pre-TASK-703 3000 ms fade at t / 2.
        self.assertEqual(page.evaluate('FALL_MESSAGE.durationMs'), 6000)
        times = [0, 1500, 3000, 4500, 5999, 6000, 9000]
        exact = page.evaluate('ts => ts.map(t => FALL_MESSAGE.opacity(t))', times)
        pre = [max(0.0, 1 - (t / 2) / 3000) ** 2 for t in times]
        errors = [abs(a - b) for a, b in zip(exact, pre)]
        self.assertLessEqual(max(errors), 1e-9, list(zip(times, exact, pre)))
        self.assertEqual(exact[0], 1)
        self.assertEqual(exact[5:], [0, 0])
        self.assertGreater(exact[4], 0)
        for t, want in (('0', 1), ('1500', 9 / 16), ('3000', 1 / 4), ('4500', 1 / 16)):
            s = samples[t]
            self.assertAlmostEqual(s['elapsedMs'], float(t), places=6)
            self.assertEqual(len(s['blits']), 1)
            self.assertAlmostEqual(s['blits'][0]['alpha'], want, places=6)
        self.assertEqual(len(samples['5983']['blits']), 1)
        self.assertAlmostEqual(samples['5983']['blits'][0]['alpha'], max(0.0, 1 - samples['5983']['elapsedMs'] / 6000) ** 2, places=9)
        self.assertEqual((samples['6000']['elapsedMs'], samples['6000']['expired'], samples['6000']['blits']), (6000, True, []))
        page.evaluate('FRAMES(30)')
        after = self.msg(page)
        self.assertEqual((after['blits'], after['visible']), ([], False))
        tm['fade'] = {'formula': 'max(0,1-elapsedMs/6000)^2', 'durationMs': 6000,
                      'exact': [{'t': t, 'opacity': o, 'preAtHalf': p, 'err': e} for t, o, p, e in zip(times, exact, pre, errors)],
                      'maxError': max(errors),
                      'drawn': {t: {'elapsedMs': s['elapsedMs'], 'blitAlpha': s['blits'][0]['alpha'] if s['blits'] else None,
                                    'blits': len(s['blits']), 'expired': s['expired']} for t, s in samples.items()},
                      'blitsAfterExpiry30Frames': 0}

        def frozen(freeze, unfreeze):
            self.emit(page, 0, 0.5, 1.5 / 12)
            page.evaluate('FRAMES(30)')
            a = self.msg(page)
            page.evaluate(freeze)
            page.evaluate('FRAMES(120)')
            b = page.evaluate('''() => { BLITS.length = 0; draw(); if (menu.gamePaused) menu.drawPauseScreen()
                return {elapsedMs: FALL_MESSAGE.elapsedMs, blits: BLITS.length, paused: menu.gamePaused} }''')
            page.evaluate(unfreeze)
            page.evaluate('FRAMES(30)')
            c = self.msg(page)
            self.assertAlmostEqual(a['elapsedMs'], 500, places=6)
            self.assertEqual(b['elapsedMs'], a['elapsedMs'])
            self.assertAlmostEqual(c['elapsedMs'], 1000, places=6)
            self.assertEqual(c['eventId'], a['eventId'])
            self.assertEqual(len(c['blits']), 1)
            return {'before': a['elapsedMs'], 'frozenFrames': 120, 'during': b['elapsedMs'], 'blitsWhileFrozen': b['blits'],
                    'paused': b['paused'], 'after30Frames': c['elapsedMs'], 'sameEvent': True}

        fr = {'paused': frozen('() => menu.startPause()', '() => menu.unPause()'),
              'hidden': frozen('''() => { Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true})
                  document.dispatchEvent(new Event('visibilitychange')) }''', '() => { delete document.visibilityState; menu.unPause() }'),
              'hostPaused': frozen('() => { hostPaused = true }', '() => { hostPaused = false }'),
              'hiddenNoPauseHandler': frozen('''() => Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true})''',
                                             '() => { delete document.visibilityState }')}
        self.assertEqual((fr['paused']['blitsWhileFrozen'], fr['hidden']['blitsWhileFrozen']), (0, 0))
        self.assertTrue(fr['paused']['paused'] and fr['hidden']['paused'])
        tm['frozen'] = fr
        # Replacement: a second event replaces the first; never two blits in a frame.
        self.emit(page, 0, 0.0, 0.5 / 12)
        page.evaluate('FRAMES(60)')
        first = self.msg(page)
        self.emit(page, 5, 1.0, 1.5 / 12)
        second = self.msg(page)
        self.assertNotEqual(first['eventId'], second['eventId'])
        self.assertEqual((second['message'], second['anchorIndex'], second['angle']), (MESSAGES[1], 5, 15))
        self.assertEqual(second['elapsedMs'], 0)
        self.assertEqual((len(first['blits']), len(second['blits'])), (1, 1))
        self.assertAlmostEqual(second['blits'][0]['alpha'], 1, places=9)
        keys = ('eventId', 'message', 'anchorIndex', 'angle', 'elapsedMs')
        tm['replace'] = {'first': {k: first[k] for k in keys}, 'second': {k: second[k] for k in keys},
                         'blitsPerFrame': [len(first['blits']), len(second['blits'])]}
        # Recovery teleport keeps the message: a real fall to the -1500 recovery.
        self.emit(page, 3, 0.5, 2.5 / 12)
        pre = self.msg(page)
        rec = page.evaluate('''() => { const l = floors[0].level; ninja.x = l.bounds.right + 4000; ninja.y = l.spawn.y + 1300
            ninja.speedY = 0; RECOVERIES.length = 0; let n = 0; while (!RECOVERIES.length && n < 2000) { FRAMES(1); n++ }
            return {frames: n, recoveries: RECOVERIES.length, y: ninja.y, spawnY: l.spawn.y} }''')
        post = self.msg(page)
        self.assertEqual(rec['recoveries'], 1)
        self.assertLess(post['elapsedMs'], 6000)
        self.assertEqual((post['eventId'], post['layout'], post['angle']), (pre['eventId'], pre['layout'], pre['angle']))
        self.assertEqual(len(post['blits']), 1)
        tm['teleport'] = {'recovery': rec, 'eventBefore': pre['eventId'], 'eventAfter': post['eventId'],
                          'elapsedBefore': pre['elapsedMs'], 'elapsedAfter': post['elapsedMs'],
                          'layoutUnchanged': post['layout'] == pre['layout'], 'blitsAfter': len(post['blits'])}
        # Restart clears.
        self.emit(page, 1, 0.5, 2.5 / 12)
        page.evaluate('FRAMES(10)')
        live = self.msg(page)
        page.evaluate('() => { CLIMB_UI.restart(); window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
        page.evaluate('FRAMES(5)')
        after = self.msg(page)
        self.assertEqual(len(live['blits']), 1)
        self.assertEqual((after['eventId'], after['longFallEventId'], after['visible'], after['blits']), (None, None, False, []))
        tm['restart'] = {'before': {'eventId': live['eventId'], 'blits': 1}, 'after': {'eventId': None, 'blits': 0, 'visible': False}}
        # Completion clears; the completion screen draws no message.
        self.emit(page, 4, 0.5, 3.5 / 12)
        page.evaluate('FRAMES(10)')
        live = self.msg(page)
        page.evaluate('() => CLIMB_UI.complete()')
        page.evaluate('FRAMES(10)')
        done = self.msg(page)
        self.assertEqual(len(live['blits']), 1)
        self.assertTrue(done['completed'] and done['paused'])
        self.assertEqual((done['eventId'], done['longFallEventId'], done['blits']), (None, None, []))
        tm['completion'] = {'before': {'eventId': live['eventId'], 'blits': 1},
                            'after': {'eventId': None, 'longFallEvent': None, 'blits': 0, 'completed': True}}
        tm['pageErrors'] = page.errors
        self.assertEqual(page.errors, [])
        # Reload: a message on screen at save time does not come back.
        context = self.browser.new_context(locale='en-US', **VIEWPORTS['desktop'])
        self.addCleanup(context.close)
        p1 = self.open(context=context)
        self.emit(p1, 3, 0.5, 4.5 / 12)
        p1.evaluate('FRAMES(10)')
        live = self.msg(p1)
        p1.evaluate('() => PROGRESS.flushClimb()')
        p1.wait_for_function('k => { const v = localStorage.getItem(k); return v && JSON.parse(v).player.y === ninja.y }', arg=CLIMB_KEY)
        saved = p1.evaluate('k => localStorage.getItem(k)', CLIMB_KEY)
        errors = list(p1.errors)
        p1.close()
        p2 = self.open(context=context)
        p2.evaluate('FRAMES(10)')
        again = self.msg(p2)
        self.assertEqual(len(live['blits']), 1)
        self.assertEqual((again['eventId'], again['longFallEventId'], again['blits']), (None, None, []))
        for word in MESSAGES + ['FALL_MESSAGE', 'fallMessage', 'anchor', 'angle']:
            self.assertNotIn(word, saved)
        tm['reload'] = {'before': {'eventId': live['eventId'], 'blits': 1}, 'after': {'eventId': None, 'blits': 0},
                        'savedKeys': sorted(json.loads(saved)), 'savedContainsMessage': False}
        tm['pageErrorsReload'] = errors + p2.errors
        self.assertEqual(errors + p2.errors, [])
        print('PASS timing: opacity 1, 9/16, 1/4, 1/16, 0 at 0/1500/3000/4500/6000 ms; frozen paused/hidden/host; '
              'replace, teleport, restart, completion, reload', flush=True)

    def test_11_isolation_controls_language(self):
        iso = EVIDENCE['isolation']['render']
        page = self.open()
        before = page.evaluate(ISO_KEYS)
        self.emit(page, 2, 0.5, 11.5 / 12)
        page.evaluate('FRAMES(5)')
        st = self.msg(page)
        self.assertEqual(len(st['blits']), 1)
        after = page.evaluate(ISO_KEYS)
        self.assertEqual(before, after)
        # Real input on top of the message: the press still throws the grapnel.
        b = st['layout']['bounds']
        p = page.evaluate('([x, y]) => { const r = canvas.getBoundingClientRect(); return {x: r.left + x, y: r.top + y} }',
                          [(b['left'] + b['right']) / 2, (b['top'] + b['bottom']) / 2])
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        page.evaluate('FRAMES(2)')
        press = page.evaluate('({pressHeld, throwed: grapnel.throwed, visible: FALL_MESSAGE.visible(), paused: menu.gamePaused})')
        page.mouse.up()
        page.evaluate('FRAMES(2)')
        self.assertEqual(press, {'pressHeld': True, 'throwed': True, 'visible': True, 'paused': False})
        page.keyboard.press('p')
        paused = page.evaluate('menu.gamePaused')
        page.keyboard.press('p')
        self.assertTrue(paused)
        self.assertFalse(page.evaluate('menu.gamePaused'))
        iso['noninteractive'] = {'domNodesBefore': before['dom'], 'domNodesAfter': after['dom'],
                                 'worldPlayerGrapnelKeysUnchanged': True, 'elements': after['elements'],
                                 'dragZones': after['dragZones'], 'byId': after['byId'], 'storageKeys': after['storage'],
                                 'pressOnMessage': press, 'pauseKeyToggles': True}
        # Identical inputs with the renderer inert vs drawing: same physics and save.
        runs = {}
        for mode in ('inert', 'enabled'):
            pg = self.open()
            if mode == 'inert':
                pg.evaluate('() => { FALL_MESSAGE.draw = function() {}; FALL_MESSAGE.advance = function() {} }')
            pg.evaluate('''() => { let s = 777; const counted = Math.random
                Math.random = function() { counted(); s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648 } }''')
            pg.evaluate('''() => { const s = captureClimbState(), sp = floors[0].level.spawn
                s.simulationTick = 0; s.stats = {elapsedActiveMs: 0, currentHeight: 0, maxHeight: 0, completed: false}
                Object.assign(s.player, {x: sp.x, y: sp.y, speedX: 0, speedY: 0})
                s.upgrades.range = true; s.input = {pressHeld: false, stalePress: false}
                s.grapple = {throwed: false, grappled: false, speedX: 0, speedY: 0, traveled: 0, shotStep: null, segments: []}
                restoreClimbState(s); RECOVERIES.length = 0; GAMEPLAY_RNG_CALLS = 0
                window.TICK = n => { for (let i = 0; i < n; i++) { physics(); FALL_MESSAGE.advance(physicsStepMs); FALL_MESSAGE.draw(ctx) } } }''')
            out = pg.evaluate('''() => { const l = floors[0].level
                ninja.x = l.bounds.right + 4000; ninja.y = l.spawn.y - 2600; ninja.speedY = 0
                for (let i = 0; i < 2000 && !RECOVERIES.length; i++) TICK(1)
                TICK(90)
                return {events: LONG_FALL.emitted, blits: BLITS.length, recoveries: RECOVERIES.length} }''')
            mid = pg.evaluate(STATE)
            q = pg.evaluate('''() => canvasCoordsToViewportCoords({
                x: (ninja.x + 80 + screen.x) * scale[version], y: (ninja.y - 160 + screen.y) * scale[version]})''')
            pg.mouse.move(q['x'], q['y'])
            pg.mouse.down()
            pg.evaluate('TICK(60)')
            pg.mouse.up()
            pg.evaluate('TICK(30)')
            end = pg.evaluate(STATE)
            runs[mode] = {'out': out, 'mid': mid, 'end': end, 'errors': pg.errors}
            self.assertEqual(pg.errors, [])
        self.assertEqual(runs['inert']['out']['blits'], 0)
        self.assertGreater(runs['enabled']['out']['blits'], 0)
        self.assertEqual(runs['inert']['out']['events'], runs['enabled']['out']['events'])
        self.assertGreaterEqual(runs['enabled']['out']['events'], 1)
        self.assertNotEqual(runs['enabled']['mid']['player'], runs['enabled']['end']['player'])
        for phase in ('mid', 'end'):
            for key in runs['inert'][phase]:
                self.assertEqual(runs['inert'][phase][key], runs['enabled'][phase][key], (phase, key))
        iso['physics'] = {'scenario': 'fall from 2600 to recovery with the message drawn, 90 ticks, real grapple press 60 ticks, 30 ticks',
                          'runs': {m: runs[m]['out'] for m in runs},
                          'identical': {p: runs['inert'][p] == runs['enabled'][p] for p in ('mid', 'end')},
                          'gameplayRngCalls': {m: runs[m]['end']['rngCalls'] for m in runs},
                          'end': {k: v for k, v in runs['enabled']['end'].items() if k not in ('elements', 'save')},
                          'saveIdentical': runs['inert']['end']['save'] == runs['enabled']['end']['save']}
        # The default reaction source never touches the gameplay Math.random.
        n = page.evaluate('GAMEPLAY_RNG_CALLS')
        self.emit(page)
        page.evaluate('() => FALL_MESSAGE.draw(ctx)')
        self.assertEqual(page.evaluate('GAMEPLAY_RNG_CALLS'), n)
        iso['gameplayRngCallsDuringDefaultReaction'] = 0
        # Both languages draw only the approved English pool.
        lang = {}
        for code in ('ru', 'en'):
            page.evaluate('c => setLanguage(c)', code)
            if page.evaluate('menu.gamePaused'):
                page.evaluate('menu.unPause()')
            seen = []
            for k in range(12):
                self.emit(page, k % 6, 0.5, (k + 0.5) / 12)
                s = self.msg(page)
                self.assertEqual(len(s['blits']), 1)
                seen.append(s['message'])
            self.assertEqual(page.evaluate('I18N.language'), code)
            self.assertEqual(seen, MESSAGES)
            lang[code] = seen
        iso['language'] = {'drawn': lang, 'onlyApprovedPool': True}
        src = (ROOT / 'render/fallmessage.js').read_text(encoding='utf-8')
        banned = ('addEventListener', 'Audio', 'shake', 'speedX', 'speedY', 'Math.random', 'localStorage', 'PROGRESS',
                  'elements.push', 'appendChild', 'pointer', 'I18N')
        iso['sideEffects'] = {'bannedTokensInRenderer': [w for w in banned if w in src], 'checked': list(banned)}
        self.assertEqual(iso['sideEffects']['bannedTokensInRenderer'], [])
        iso['pageErrors'] = page.errors + runs['inert']['errors'] + runs['enabled']['errors']
        self.assertEqual(page.errors, [])
        print('PASS isolation: noninteractive, controls work, physics identical inert vs enabled, English pool in en/ru', flush=True)

    def test_12_production_captures(self):
        cases = {'desktop': (1, 1.0, 'OOPS...'), 'touch': (4, 0.0, 'SEE YOU AT THE TOP.')}
        caps = EVIDENCE['timing'].setdefault('captures', {})
        for kind, (anchor, r, text) in cases.items():
            page = self.open(kind)
            self.emit(page, anchor, r, (MESSAGES.index(text) + 0.5) / 12)
            frames, info = [], []
            for name, target in (('appear 0 ms', 0), ('mid-fade 3000 ms', 3000), ('expiry 6000 ms', 6000)):
                page.evaluate('t => { while (!FALL_MESSAGE.expired && FALL_MESSAGE.elapsedMs < t - 1e-6) FRAMES(1) }', target)
                st = self.msg(page)
                png = page.screenshot()
                alpha = st['blits'][0]['alpha'] if st['blits'] else 0
                note = (f"{st['message']} at {ANCHORS[st['layout']['anchorIndex']]} {st['angle']:+.0f} deg, alpha {alpha:.2f}"
                        if st['blits'] else 'no message drawn (expired)')
                frames.append((name, png, note))
                info.append({'frame': name, 'elapsedMs': st['elapsedMs'], 'blits': len(st['blits']), 'alpha': alpha,
                             'message': st['message'], 'anchorIndex': st['layout']['anchorIndex'] if st['layout'] else None,
                             'angle': st['angle'], 'bounds': st['layout']['bounds'] if st['layout'] else None})
            self.assertEqual([i['blits'] for i in info], [1, 1, 0])
            self.assertAlmostEqual(info[0]['alpha'], 1)
            self.assertAlmostEqual(info[1]['alpha'], 0.25, places=6)
            self.assertEqual(info[2]['elapsedMs'], 6000)
            self.assertEqual(abs(info[0]['angle']), 15)
            self.__class__.frames[kind] = frames
            caps[kind] = {'viewport': VIEWPORTS[kind]['viewport'], 'frames': info, 'pageErrors': page.errors}
            self.assertEqual(page.errors, [])
        print('PASS captures: desktop 1280x720 and touch 844x390 at 0/3000/6000 ms', flush=True)


if __name__ == '__main__':
    unittest.main()
