"""TASK-662: Grapple Over fall recovery.

Boots the real index.html, freezes the frame loop and drives the production
physics()/calcPhysics() and the real mouse/keyboard handlers. Falling strictly
below 1500 world units under the spawn teleports the player to the spawn
with the fresh-start upward launch (TASK-717), releases the grapple, drops press ownership and snaps the camera, while the
run (time, best height, upgrades, world and movers) continues.

FALL_RECOVERY_EVIDENCE_DIR=DIR writes compact recovery.json, state.json and
mode-checks.json there.

    python3 -m unittest discover -s tools -p test_climb_fall_recovery.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run, select_mode

ROOT = Path(__file__).resolve().parent.parent
CLIMB_KEY = 'grapnelninja.grappleOver'
DEPTH = 1500

# Freeze the frame loop; count recoveries through the production function.
SETUP = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    const recover = recoverClimbFall
    window.RECOVERIES = []
    recoverClimbFall = function() {
        RECOVERIES.push({y: ninja.y, height: floors[0].climbStats.currentHeight,
            speedY: ninja.speedY, step: floors[0].elapsedSteps})
        return recover()
    }
    window.CAMERA_AT_SPAWN = {x: screen.x, y: screen.y}
    // TASK-721: past the first-death double grapnel offer (test_double_offer covers it)
    floors[0].doubleOfferShown = true
}'''

STATE = '''() => {
    const w = floors[0], g = grapnel
    return {
        version, paused: menu.gamePaused,
        player: {x: ninja.x, y: ninja.y, speedX: ninja.speedX, speedY: ninja.speedY},
        spawn: w.level ? w.level.spawn : null,
        stats: w.climbStats ? {...w.climbStats} : null,
        tick: w.elapsedSteps ?? null, upgrades: w.level ? {range: w.rangeUpgraded} : null,
        grapple: {throwed: g.throwed, grappled: g.grappled, segments: g.pos.length,
            shotStep: g.shotStep ?? null, aim: g.aim ?? null, traveled: g.traveled ?? 0},
        input: {pressHeld, stalePress, gameplayPressOwned},
        camera: {x: screen.x, y: screen.y},
        recoveries: window.RECOVERIES ? RECOVERIES.length : null,
        launchSpeed: version === 'grapple_over' ? getSpawnLaunchSpeed() : null
    }
}'''

# Place the player `depth` units under the spawn in open air, not moving.
PLACE = '''([depth, speedY]) => {
    const s = floors[0].level.spawn
    ninja.x = s.x; ninja.y = s.y + depth; ninja.speedX = 0; ninja.speedY = speedY
}'''

# World identity and mover state, to show the world is neither reset nor rebuilt.
WORLD = '''() => {
    const w = floors[0]
    if (!w.probeTag) { w.probeTag = Math.random(); w.elements.forEach(e => e.probeOwner = w.probeTag) }
    const movers = w.level.movers.map(m => {
        const e = w.byId.get(m.element)
        return {id: m.id, axis: m.axis, value: e[m.axis]}
    })
    return {tag: w.probeTag, sameElements: w.elements.every(e => e.probeOwner === w.probeTag),
        elements: w.elements.length, tick: w.elapsedSteps, movers}
}'''


def mover_expected(page):
    """Each mover's position computed from the current simulation tick."""
    return page.evaluate('''() => {
        const w = floors[0], t = w.elapsedSteps * physicsStepMs / cyclesPerTick
        return w.level.movers.map(m => {
            const p = (t / m.periodMs + m.phase) % 1
            return {id: m.id, axis: m.axis, value: m.min + (m.max - m.min) * (1 - Math.abs(2 * p - 1))}
        })
    }''')


class ClimbFallRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.evidence = {'recovery': {'depth': DEPTH}, 'state': {}, 'modes': {}}

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        out = os.environ.get('FALL_RECOVERY_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            for name, key in (('recovery.json', 'recovery'), ('state.json', 'state'), ('mode-checks.json', 'modes')):
                Path(out, name).write_text(json.dumps(cls.evidence[key], separators=(',', ':'), sort_keys=True) + '\n')

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

    def state(self, page):
        return page.evaluate(STATE)

    def assert_recovered(self, s, camera):
        self.assertEqual((s['player']['x'], s['player']['y']), (s['spawn']['x'], s['spawn']['y']))
        # TASK-717: recovery launches upward like a fresh start (was at rest).
        self.assertEqual((s['player']['speedX'], s['player']['speedY']), (0, -s['launchSpeed']))
        self.assertEqual(s['stats']['currentHeight'], 0)
        self.assertFalse(s['grapple']['throwed'])
        self.assertFalse(s['grapple']['grappled'])
        self.assertEqual(s['grapple']['segments'], 0)
        self.assertIsNone(s['grapple']['shotStep'])
        self.assertFalse(s['input']['gameplayPressOwned'])
        self.assertEqual(s['camera'], camera)

    def press_at(self, page, dx, dy):
        """Real mousedown at the player + (dx, dy) world units."""
        p = page.evaluate('''([dx, dy]) => canvasCoordsToViewportCoords({
            x: (ninja.x + dx + screen.x) * scale[version], y: (ninja.y + dy + screen.y) * scale[version]})''', [dx, dy])
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()

    def test_01_boundary(self):
        page = self.open()
        rec = self.evidence['recovery']
        # One production simulation step (calcPhysics) with gravity cancelled so the
        # step evaluates exactly the fixture height.
        step = '''depth => {
            const s = floors[0].level.spawn
            ninja.x = s.x; ninja.y = s.y + depth; ninja.speedX = 0; ninja.speedY = -GRAVITY
            const returned = calcPhysics() === true
            return {returned, height: floors[0].climbStats.currentHeight, y: ninja.y}
        }'''
        at = page.evaluate(step, DEPTH)
        s_at = self.state(page)
        self.assertFalse(at['returned'])
        self.assertEqual(at['height'], -DEPTH)
        self.assertEqual(s_at['recoveries'], 0)
        self.assertEqual(s_at['player']['y'], s_at['spawn']['y'] + DEPTH)
        below = page.evaluate(step, DEPTH + 1e-6)
        s_below = self.state(page)
        camera = page.evaluate('CAMERA_AT_SPAWN')
        self.assertTrue(below['returned'])
        self.assertEqual(s_below['recoveries'], 1)
        recorded = page.evaluate('RECOVERIES[0]')
        self.assertLess(recorded['height'], -DEPTH)
        self.assert_recovered(s_below, camera)
        rec['boundary'] = {
            'atBoundary': {'fixtureDepth': DEPTH, 'heightAtStep': at['height'], 'recovered': at['returned'],
                           'recoveries': s_at['recoveries'], 'playerY': s_at['player']['y']},
            'belowBoundary': {'fixtureDepth': DEPTH + 1e-6, 'heightAtDetection': recorded['height'],
                              'recovered': below['returned'], 'recoveries': s_below['recoveries'],
                              'after': {k: s_below[k] for k in ('player', 'spawn', 'stats', 'grapple', 'camera')},
                              'cameraAtSpawn': camera},
            'pageErrors': page.errors}
        self.assertEqual(page.errors, [])

    def test_02_downward_crossing(self):
        page = self.open()
        camera = page.evaluate('CAMERA_AT_SPAWN')
        page.evaluate(PLACE, [DEPTH - 200, 0])
        # Real ticks: record the last pre-recovery height of every simulation step.
        trace = page.evaluate('''() => {
            const steps = [], calc = calcPhysics
            calcPhysics = function() {
                const r = calc()
                steps.push({tick: floors[0].elapsedSteps, height: floors[0].climbStats.currentHeight, recovered: r === true})
                return r
            }
            const ticks = []
            for (let i = 0; i < 400 && !RECOVERIES.length; i++) {
                physics()
                ticks.push({i, y: ninja.y, speedY: ninja.speedY})
            }
            calcPhysics = calc
            return {steps, ticks}
        }''')
        steps = trace['steps']
        first = next(i for i, st in enumerate(steps) if st['height'] < -DEPTH or st['recovered'])
        self.assertTrue(steps[first]['recovered'])
        self.assertEqual(first, len(steps) - 1)
        self.assertTrue(all(st['height'] >= -DEPTH for st in steps[:first]))
        detected = page.evaluate('RECOVERIES[0]')
        self.assertLess(detected['height'], -DEPTH)
        self.assertGreater(detected['speedY'], 0)
        after = self.state(page)
        self.assert_recovered(after, camera)
        self.assertEqual(after['recoveries'], 1)
        # Later ticks are ordinary simulation again: the launch carries the player up
        # while gravity slows it (TASK-717; before, gravity pulled it down from rest).
        later = page.evaluate('''() => { const out = []
            for (let i = 0; i < 3; i++) { physics(); out.push({y: ninja.y, speedY: ninja.speedY}) }
            return out }''')
        self.assertGreater(later[0]['speedY'], after['player']['speedY'])
        self.assertLess(later[0]['y'], after['player']['y'])
        self.assertEqual(self.state(page)['recoveries'], 1)
        self.evidence['recovery']['downwardCrossing'] = {
            'startDepth': DEPTH - 200, 'ticksRun': len(trace['ticks']), 'stepsRun': len(steps),
            'lastStepsBefore': steps[max(0, first - 3):first], 'recoveryStep': steps[first],
            'firstStepDetectingCrossing': first, 'detected': detected,
            'after': {k: after[k] for k in ('player', 'spawn', 'stats', 'grapple', 'camera')},
            'cameraAtSpawn': camera, 'laterTicks': later, 'pageErrors': page.errors}
        self.assertEqual(page.errors, [])

    def test_03_held_grapple_needs_fresh_press(self):
        page = self.open()
        camera = page.evaluate('CAMERA_AT_SPAWN')
        cases = {}
        for kind in ('grappled', 'flying'):
            page.evaluate('() => { ninja.speedX = ninja.speedY = 0 }')
            self.press_at(page, 0, -120)
            pressed = self.state(page)
            self.assertTrue(pressed['grapple']['throwed'])
            self.assertTrue(pressed['input']['pressHeld'] and pressed['input']['gameplayPressOwned'])
            if kind == 'grappled':
                # An attached rope on a real grapplable element, as an acquired shot leaves it.
                page.evaluate('''() => { const e = floors[0].elements.find(e => e.grapplable && e.surfaceRole !== 'hazard')
                    grapnel.pos = [[e.x, e.y, e]]; grapnel.grappled = true; grapnel.shotStep = null }''')
            page.evaluate(PLACE, [DEPTH - 1, 5])
            before = self.state(page)
            self.assertEqual(before['grapple']['grappled'], kind == 'grappled')
            self.assertTrue(before['grapple']['throwed'])
            n = before['recoveries']
            page.evaluate('() => { for (let i = 0; i < 200 && RECOVERIES.length === %d; i++) physics() }' % n)
            after = self.state(page)
            self.assertEqual(after['recoveries'], n + 1)
            self.assert_recovered(after, camera)
            self.assertTrue(after['input']['pressHeld'])
            self.assertTrue(after['input']['stalePress'])
            # Still held: moving the held pointer and ticking never reattaches.
            page.mouse.move(700, 300)
            held = page.evaluate('''() => { const seen = []
                for (let i = 0; i < 30; i++) { physics(); seen.push(grapnel.throwed || grapnel.grappled) }
                return seen.some(Boolean) }''')
            self.assertFalse(held)
            page.mouse.up()
            released = self.state(page)
            self.assertFalse(released['grapple']['throwed'])
            self.assertFalse(released['input']['stalePress'])
            self.press_at(page, 0, -120)
            fresh = self.state(page)
            self.assertTrue(fresh['grapple']['throwed'])
            self.assertTrue(fresh['input']['gameplayPressOwned'])
            page.mouse.up()
            cases[kind] = {'beforeFall': {'grapple': before['grapple'], 'input': before['input']},
                           'atRecovery': {k: after[k] for k in ('player', 'grapple', 'input', 'camera', 'recoveries')},
                           'reattachedWhileHeld': held, 'afterRelease': {'grapple': released['grapple'], 'input': released['input']},
                           'freshPress': {'grapple': fresh['grapple'], 'input': fresh['input']}}
        # Independent repeated falls; no loop at the spawn in between.
        repeats = []
        for _ in range(3):
            page.evaluate(PLACE, [DEPTH - 50, 2])
            r = page.evaluate('''() => { const n = RECOVERIES.length; let t = 0
                while (RECOVERIES.length === n && t < 200) { physics(); t++ }
                const at = {x: ninja.x, y: ninja.y, speedY: ninja.speedY}
                for (let i = 0; i < 120; i++) physics()
                return {ticksToRecover: t, recoveredAt: at, recoveriesAfterRest: RECOVERIES.length - n,
                        heightAfterRest: floors[0].climbStats.currentHeight} }''')
            self.assertEqual(r['recoveriesAfterRest'], 1)
            self.assertGreater(r['heightAfterRest'], -DEPTH)
            repeats.append(r)
        self.assertEqual(self.state(page)['recoveries'], 5)
        self.evidence['recovery']['inputCases'] = cases
        self.evidence['recovery']['repeatedFalls'] = repeats
        self.evidence['recovery']['inputPageErrors'] = page.errors
        self.assertEqual(page.errors, [])

    def test_04_run_state_preserved_and_saved(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = self.open(context)
        # Earn the upgrade and a best height, then fall.
        page.evaluate('''() => { floors[0].rangeUpgraded = true; for (let i = 0; i < 20; i++) physics()
            const s = floors[0].level.spawn; ninja.x = s.x; ninja.y = s.y - 900; ninja.speedX = ninja.speedY = 0
            physics() }''')
        world_before = page.evaluate(WORLD)
        before = self.state(page)
        self.assertGreaterEqual(before['stats']['maxHeight'], 899)
        page.evaluate(PLACE, [DEPTH - 1, 1])
        ticks = page.evaluate('() => { let t = 0; while (!RECOVERIES.length && t < 200) { physics(); t++ } return t }')
        after = self.state(page)
        world_after = page.evaluate(WORLD)
        expected_movers = mover_expected(page)
        self.assertEqual(after['recoveries'], 1)
        self.assertEqual(world_after['tag'], world_before['tag'])
        self.assertTrue(world_after['sameElements'])
        self.assertEqual(world_after['elements'], world_before['elements'])
        self.assertGreater(world_after['tick'], world_before['tick'])
        for got, want in zip(world_after['movers'], expected_movers):
            self.assertAlmostEqual(got['value'], want['value'], places=9)
        step_ms = page.evaluate('physicsStepMs / cyclesPerTick')
        advanced = (world_after['tick'] - before['tick']) * step_ms
        self.assertAlmostEqual(after['stats']['elapsedActiveMs'], before['stats']['elapsedActiveMs'] + advanced, places=6)
        self.assertEqual(after['stats']['maxHeight'], before['stats']['maxHeight'])
        self.assertEqual(after['upgrades'], {'range': True})
        self.assertFalse(after['stats']['completed'])
        self.assertTrue(page.evaluate('runInProgress'))
        # Recovery flushed the save: storage holds the spawn position, not the fall.
        page.wait_for_function('''k => { const v = JSON.parse(localStorage.getItem(k) || 'null')
            return v && v.player.y === floors[0].level.spawn.y && v.simulationTick === floors[0].elapsedSteps }''', arg=CLIMB_KEY)
        saved = json.loads(page.evaluate('k => localStorage.getItem(k)', CLIMB_KEY))
        errors = list(page.errors)
        page.close()
        reloaded = context.new_page()
        reloaded.errors = []
        reloaded.on('pageerror', lambda e: reloaded.errors.append('pageerror: %s' % e))
        reloaded.goto(self.url)
        wait_for_boot_run(reloaded)
        restored = reloaded.evaluate(STATE)
        self.assertTrue(restored['paused'])
        self.assertEqual((restored['player']['x'], restored['player']['y']), (after['spawn']['x'], after['spawn']['y']))
        # The save restore keeps the saved launch speed of the recovery; it adds no launch of its own.
        self.assertEqual(saved['player']['speedY'], after['player']['speedY'])
        self.assertEqual((restored['player']['speedX'], restored['player']['speedY']), (0, after['player']['speedY']))
        self.assertEqual(restored['stats'], after['stats'])
        self.assertEqual(restored['tick'], world_after['tick'])
        self.assertEqual(restored['upgrades'], {'range': True})
        self.assertFalse(restored['grapple']['throwed'])
        self.assertEqual(reloaded.errors, [])
        self.evidence['state'] = {
            'before': {k: before[k] for k in ('stats', 'tick', 'upgrades', 'player')}, 'worldBefore': world_before,
            'ticksUntilRecovery': ticks, 'after': {k: after[k] for k in ('stats', 'tick', 'upgrades', 'player')},
            'worldAfter': world_after, 'moversExpectedFromTick': expected_movers,
            'elapsedAdvanceMs': advanced, 'runInProgress': True,
            'savedAfterRecovery': {'player': saved['player'], 'stats': saved['stats'], 'simulationTick': saved['simulationTick'],
                                   'upgrades': saved['upgrades'], 'grappleThrowed': saved['grapple']['throwed']},
            'reloaded': {k: restored[k] for k in ('paused', 'player', 'stats', 'tick', 'upgrades', 'grapple')},
            'pageErrors': errors + reloaded.errors}
        self.assertEqual(errors, [])

    def test_05_paused_completed_and_other_modes(self):
        page = self.open()
        modes = self.evidence['modes']
        # Paused through the real pause key: no teleport while paused.
        page.keyboard.press('p')
        page.evaluate(PLACE, [DEPTH + 300, 0])
        paused = page.evaluate('() => { for (let i = 0; i < 30; i++) physics(); return null }')
        s_paused = self.state(page)
        self.assertTrue(s_paused['paused'])
        self.assertEqual(s_paused['recoveries'], 0)
        self.assertEqual(s_paused['player']['y'], s_paused['spawn']['y'] + DEPTH + 300)
        page.keyboard.press('p')
        page.evaluate('() => physics()')
        s_resumed = self.state(page)
        self.assertFalse(s_resumed['paused'])
        self.assertEqual(s_resumed['recoveries'], 1)
        self.assertEqual(s_resumed['player']['y'], s_resumed['spawn']['y'])
        modes['paused'] = {'pausedTicks': 30, 'whilePaused': {k: s_paused[k] for k in ('paused', 'player', 'recoveries')},
                           'afterUnpause': {k: s_resumed[k] for k in ('paused', 'player', 'recoveries')}}
        # Completed run: frozen in place.
        page.evaluate('() => CLIMB_UI.complete()')
        page.evaluate(PLACE, [DEPTH + 300, 0])
        page.evaluate('() => { for (let i = 0; i < 30; i++) { physics(); calcPhysics() } }')
        s_done = self.state(page)
        self.assertTrue(s_done['stats']['completed'])
        self.assertEqual(s_done['recoveries'], 1)
        self.assertEqual(s_done['player']['y'], s_done['spawn']['y'] + DEPTH + 300)
        modes['completed'] = {k: s_done[k] for k in ('paused', 'player', 'recoveries')}
        modes['completed']['completed'] = True
        # Classic and bad: the recovery never runs and every tick still runs all cycles.
        for mode in ('classic', 'bad'):
            select_mode(page, mode)
            page.evaluate('() => { menu.unPause(); window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
            r = page.evaluate('''() => {
                const calc = calcPhysics; let calls = 0, truthy = 0
                calcPhysics = function() { calls++; const r = calc(); if (r) truthy++; return r }
                const startY = ninja.y, n = RECOVERIES.length
                ninja.speedY = 40
                for (let i = 0; i < 20; i++) physics()
                calcPhysics = calc
                return {version, paused: menu.gamePaused, calls, truthy, cyclesPerTick, ticks: 20,
                        startY, endY: ninja.y, recoveries: RECOVERIES.length - n}
            }''')
            self.assertEqual(r['version'], mode)
            self.assertFalse(r['paused'])
            self.assertEqual(r['recoveries'], 0)
            self.assertEqual(r['truthy'], 0)
            self.assertEqual(r['calls'], 20 * r['cyclesPerTick'])
            self.assertNotEqual(r['endY'], r['startY'])
            modes[mode] = r
        modes['pageErrors'] = page.errors
        self.assertEqual(page.errors, [])


if __name__ == '__main__':
    unittest.main()
