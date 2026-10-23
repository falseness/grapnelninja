"""TASK-665: Grapple Over long-fall detection and message selection.

Boots the real index.html, freezes the frame loop and drives the production
physics()/calcPhysics(), LONG_FALL.step() (called from calcPhysics) and the
real mouse/keyboard handlers. A continuous descent of strictly more than 4000
world units emits one transient event; upward movement or a new grapple catch
rearms the detector. Recovery, restart, reload and the spawn never count as falls.

LONG_FALL_EVIDENCE_DIR=DIR writes compact fall-events.json, lifecycle.json,
message-pool.json and isolation.json there.

    python3 -m unittest discover -s tools -p test_long_fall_messages.py -v
"""
from contextlib import ExitStack
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


def compact(steps, keep):
    """Only the steps an assertion uses: first, last and listed indexes."""
    idx = sorted({0, len(steps) - 1, *[i for i in keep if 0 <= i < len(steps)]})
    return [dict(steps[i], i=i) for i in idx]


class LongFallMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.evidence = {'fall-events': {'threshold': THRESHOLD}, 'lifecycle': {}, 'message-pool': {}, 'isolation': {}}

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        out = os.environ.get('LONG_FALL_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            for key, data in cls.evidence.items():
                Path(out, key + '.json').write_text(json.dumps(data, separators=(',', ':'), sort_keys=True) + '\n')

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
        self.assertIn(above['event']['message'], MESSAGES)
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
                                                             'player', 'input', 'upgrades', 'elements', 'grapple']))
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


if __name__ == '__main__':
    unittest.main()
