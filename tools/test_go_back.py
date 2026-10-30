"""TASK-790/791: Grapple Over go-back checkpoint and returnToCheckpoint().

Boots the real index.html, freezes the frame loop and throws the production
grapnel (real mouse press, grapnel.move()/collision()) at chosen elements of
the shipped level. A new catch on a static (non-mover) element that is higher
than the current checkpoint records world.climbCheckpoint = {anchorX, anchorY,
ropeLength, section, bodyId}; movers never do. The checkpoint round-trips
through the climb save, older saves and saves naming a missing body load
without one, a restart clears it and the fall recovery keeps it.
returnToCheckpoint() (TASK-791) hangs the player hooked and at rest under the
checkpoint anchor, keeps time, best height and falls, counts goBacks, and a
press held through it neither throws nor releases until pressed again.

GO_BACK_EVIDENCE_DIR=DIR writes compact checkpoint.json there.

    python3 -m unittest discover -s tools -p test_go_back.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
CLIMB_KEY = 'grapnelninja.grappleOver'
# gameoptions.js local selector for the layout v3 mountain (it has movers).
LEGACY_V3_QUERY = '?grappleFixture=legacy-v3'

# Freeze the frame loop, past the first-death double grapnel offer.
SETUP = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    floors[0].doubleOfferShown = true
}'''

# Catch candidates: grapplable solid elements with a lowest vertex in open air
# 400 units under it. A static list and a mover list, lowest anchor first.
CANDIDATES = '''() => {
    const w = floors[0], moverIds = new Set(w.level.movers.map(m => m.element))
    const blocked = (x, y) => w.elements.some(e => pointInPolygon(e.getPoints(), x, y))
    const out = {static: [], movers: []}
    for (const e of w.elements) {
        if (e.grapplable === false) continue
        const pts = e.getPoints(), ys = pts.map(p => p.y)
        const {x, y} = pts[ys.indexOf(Math.max(...ys))]
        if ([0, 100, 200, 300, 400].some(d => blocked(x + 1e-3, y + 20 + d))) continue
        ;(moverIds.has(e.id) ? out.movers : out.static).push({id: e.id, x, y})
    }
    out.static.sort((a, b) => b.y - a.y)
    return out
}'''

# Release any rope, put the player 400 units under (x, y) at rest and throw
# with a real press at the anchor; step only the grapnel until it settles.
CATCH = '''async ([x, y]) => {
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,
        aim: null, clip: null, traveled: 0, speedX: 0, speedY: 0})
    ninja.x = x + 1e-3; ninja.y = y + 400; ninja.speedX = ninja.speedY = 0
    screen.trackGrappleOver(true)
    return true
}'''

AFTER = '''() => {
    for (let i = 0; i < 400 && grapnel.throwed && !grapnel.grappled && !grapnel.isParked(); i++) {
        grapnel.move(); grapnel.collision()
    }
    const g = grapnel, a = g.grappled ? g.pos[0] : null
    return {grappled: g.grappled, target: a ? a[2].id : null, anchor: a ? [a[0], a[1]] : null,
        ninja: [ninja.x, ninja.y], section: CLIMB_UI.currentSection().id,
        checkpoint: floors[0].climbCheckpoint}
}'''


class GoBackCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.evidence = {}

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        out = os.environ.get('GO_BACK_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            Path(out, 'checkpoint.json').write_text(json.dumps(cls.evidence, indent=1, sort_keys=True) + '\n')

    def open(self, seed=None, query=''):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        if seed is not None:
            context.add_init_script('localStorage.setItem(%s, %s)' % (json.dumps(CLIMB_KEY), json.dumps(seed)))
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url + query)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        # A restored save stays paused (as restoreClimb leaves it) and unchanged.
        page.evaluate(SETUP)
        if seed is None:
            page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        self.addCleanup(lambda: self.assertEqual(page.errors, []))
        return page

    def catch(self, page, target):
        """Real mouse throw from 400 units under target's lowest vertex."""
        page.mouse.up()
        page.evaluate(CATCH, [target['x'], target['y']])
        p = page.evaluate('''([x, y]) => canvasCoordsToViewportCoords({
            x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})''', [target['x'], target['y']])
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        row = page.evaluate(AFTER)
        page.mouse.up()
        return row

    def catches(self, page, pool, count):
        """The first `count` targets of pool that the real throw catches."""
        rows = []
        for target in pool:
            row = self.catch(page, target)
            if row['grappled'] and row['target'] == target['id']:
                rows.append(row)
                if len(rows) == count:
                    break
        self.assertEqual(len(rows), count, 'not enough catchable targets')
        return rows

    def test_01_static_catch_sets_checkpoint(self):
        page = self.open()
        self.assertIsNone(page.evaluate('floors[0].climbCheckpoint'))
        pool = page.evaluate(CANDIDATES)
        row = self.catches(page, pool['static'], 1)[0]
        c = row['checkpoint']
        self.assertEqual(set(c), {'anchorX', 'anchorY', 'ropeLength', 'section', 'bodyId'})
        self.assertEqual([c['anchorX'], c['anchorY']], row['anchor'])
        self.assertEqual(c['bodyId'], row['target'])
        rope = ((row['ninja'][0] - c['anchorX']) ** 2 + (row['ninja'][1] - c['anchorY']) ** 2) ** .5
        self.assertLess(abs(c['ropeLength'] - rope), 1)
        self.assertEqual(c['section'], row['section'])
        self.evidence['static_catch'] = row

    def test_02_lower_keeps_higher_replaces(self):
        page = self.open()
        pool = page.evaluate(CANDIDATES)['static']
        # Lowest anchors first: the first catch is the low one.
        low, high = self.catches(page, pool, 2)
        self.assertLess(high['anchor'][1], low['anchor'][1])
        self.assertEqual(high['checkpoint']['bodyId'], high['target'])
        # Catching the low anchor again does not replace the higher one.
        again = self.catch(page, next(t for t in pool if t['id'] == low['target']))
        self.assertTrue(again['grappled'])
        self.assertEqual(again['target'], low['target'])
        self.assertEqual(again['checkpoint'], high['checkpoint'])
        # Holding the rope (no new catch) records nothing either.
        page.evaluate('() => { floors[0].climbCheckpoint = null; grapnel.collision() }')
        self.assertIsNone(page.evaluate('floors[0].climbCheckpoint'))
        self.evidence['lower_higher'] = {'low': low['checkpoint'], 'high': high['checkpoint'],
                                         'after_low_again': again['checkpoint']}

    def test_03_mover_never_sets(self):
        # The shipped level has no movers; the legacy-v3 mountain has.
        page = self.open(query=LEGACY_V3_QUERY)
        pool = page.evaluate(CANDIDATES)
        self.assertTrue(pool['movers'], 'level has no catchable movers')
        rows = self.catches(page, pool['movers'], 1)
        self.assertIsNone(rows[0]['checkpoint'])
        # Nor replaces an existing lower static checkpoint.
        first = self.catches(page, pool['static'], 1)[0]
        mover = self.catch(page, next(t for t in pool['movers'] if t['id'] == rows[0]['target']))
        self.assertTrue(mover['grappled'])
        self.assertLess(mover['anchor'][1], first['anchor'][1])
        self.assertEqual(mover['checkpoint'], first['checkpoint'])
        self.evidence['mover'] = {'target': rows[0]['target'], 'checkpoint_after': mover['checkpoint'],
                                  'static_before': first['checkpoint'], 'static_y': first['anchor'][1],
                                  'mover_y': mover['anchor'][1]}

    def test_04_save_reload(self):
        page = self.open()
        self.catches(page, page.evaluate(CANDIDATES)['static'], 1)
        save = page.evaluate('captureClimbState()')
        self.assertIsNotNone(save['climbCheckpoint'])
        seeds = {'with': save, 'without': {k: v for k, v in save.items() if k != 'climbCheckpoint'},
                 'missing_body': {**save, 'climbCheckpoint': {**save['climbCheckpoint'], 'bodyId': 'NO-SUCH-BODY'}}}
        loaded = {}
        for name, seed in seeds.items():
            p = self.open(json.dumps(seed))
            loaded[name] = p.evaluate('''() => ({tick: floors[0].elapsedSteps,
                checkpoint: floors[0].climbCheckpoint, saved: captureClimbState().climbCheckpoint})''')
            # The save was accepted (not reset to a fresh run).
            self.assertEqual(loaded[name]['tick'], save['simulationTick'])
        self.assertEqual(loaded['with']['checkpoint'], save['climbCheckpoint'])
        self.assertEqual(loaded['with']['saved'], save['climbCheckpoint'])
        self.assertIsNone(loaded['without']['checkpoint'])
        self.assertIsNone(loaded['missing_body']['checkpoint'])
        # A malformed checkpoint is an invalid save, like any other bad field.
        bad = page.evaluate('s => { try { restoreClimbState(s); return "accepted" } catch (e) { return e.message } }',
                            {**save, 'climbCheckpoint': {**save['climbCheckpoint'], 'ropeLength': 'x'}})
        self.assertEqual(bad, 'InvalidClimbState')
        self.evidence['save_reload'] = {'saved': save['climbCheckpoint'], 'loaded': loaded, 'malformed': bad}

    def test_05_restart_clears_recovery_keeps(self):
        page = self.open()
        cp = self.catches(page, page.evaluate(CANDIDATES)['static'], 1)[0]['checkpoint']
        recovered = page.evaluate('''() => {
            Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null, traveled: 0})
            const s = floors[0].level.spawn, falls = floors[0].climbStats.falls
            ninja.x = s.x; ninja.y = s.y + 1600; ninja.speedX = 0; ninja.speedY = 0
            physics()
            return {falls: floors[0].climbStats.falls - falls, at: [ninja.x, ninja.y], spawn: [s.x, s.y],
                checkpoint: floors[0].climbCheckpoint}
        }''')
        self.assertEqual(recovered['falls'], 1)
        self.assertEqual(recovered['at'], recovered['spawn'])
        self.assertEqual(recovered['checkpoint'], cp)
        restarted = page.evaluate('() => { CLIMB_UI.restart(); return {tick: floors[0].elapsedSteps, checkpoint: floors[0].climbCheckpoint} }')
        self.assertIsNone(restarted['checkpoint'])
        self.evidence['restart_recovery'] = {'checkpoint': cp, 'after_recovery': recovered, 'after_restart': restarted}

    def test_06_other_modes(self):
        page = self.open()
        rows = page.evaluate('''() => {
            const out = {}
            for (const mode of ['classic', 'bad']) {
                if (!menu.gamePaused) menu.startPause()
                menu.selectMode(mode)
                const e = floors[0].elements?.find(e => !e.isEmpty?.()) ?? floors[0].elements?.[0]
                recordClimbCheckpoint(false, 0, -1e9, e)
                out[mode] = {version, checkpoint: floors[0].climbCheckpoint ?? null}
            }
            return out
        }''')
        for mode in ('classic', 'bad'):
            self.assertEqual(rows[mode]['version'], mode)
            self.assertIsNone(rows[mode]['checkpoint'])
        self.evidence['other_modes'] = rows

    def go_back_setup(self):
        """A shipped-level page with a real static catch as the checkpoint,
        the rope dropped and the player falling far below it."""
        page = self.open()
        cp = self.catches(page, page.evaluate(CANDIDATES)['static'], 1)[0]['checkpoint']
        page.evaluate('''() => {
            window.DESIGN = []
            const design = ANALYTICS.design
            ANALYTICS.design = (...args) => { DESIGN.push(args); return design.apply(ANALYTICS, args) }
            Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null, traveled: 0})
            ninja.x += 300; ninja.y += 900; ninja.speedX = 7; ninja.speedY = 20
            Object.assign(floors[0].climbStats, {elapsedActiveMs: 123456, maxHeight: 4321, falls: 3})
        }''')
        return page, cp

    def test_07_return_hangs_at_rest(self):
        page, cp = self.go_back_setup()
        row = page.evaluate('''() => {
            const s = floors[0].climbStats, before = {...s}
            const returned = returnToCheckpoint()
            const camera = {x: screen.x, y: screen.y}
            screen.trackGrappleOver(true)
            const after = {...s}, start = [ninja.x, ninja.y]
            const g = grapnel, a = g.pos[0]
            const at = {returned, before, after, ninja: start, speed: [ninja.speedX, ninja.speedY],
                radius: ninja.radius, grappled: g.grappled, throwed: g.throwed, anchor: [a[0], a[1]], body: a[2].id, segments: g.pos.length,
                track: ninja.track.pos.length, cameraSnapped: camera.x === screen.x && camera.y === screen.y,
                input: {pressHeld, stalePress, gameplayPressOwned}, design: DESIGN.filter(d => d[0].startsWith('goback:')),
                save: captureClimbState().stats}
            let maxMove = 0
            for (let i = 0; i < 600; i++) {
                physics()
                maxMove = Math.max(maxMove, Math.hypot(ninja.x - start[0], ninja.y - start[1]))
            }
            at.rest = {maxMove, grappled: grapnel.grappled, anchor: [grapnel.pos[0][0], grapnel.pos[0][1]],
                falls: floors[0].climbStats.falls, final: [ninja.x, ninja.y]}
            return at
        }''')
        self.assertTrue(row['returned'])
        self.assertTrue(row['grappled'] and row['throwed'])
        self.assertEqual(row['anchor'], [cp['anchorX'], cp['anchorY']])
        self.assertEqual(row['body'], cp['bodyId'])
        self.assertEqual(row['segments'], 1)
        # Straight below the anchor, within the saved rope, not moving.
        self.assertEqual(row['ninja'][0], cp['anchorX'])
        self.assertGreater(row['ninja'][1], cp['anchorY'])
        self.assertLessEqual(row['ninja'][1] - cp['anchorY'], max(cp['ropeLength'], row['radius']) + 1e-9)
        self.assertEqual(row['speed'], [0, 0])
        self.assertTrue(row['cameraSnapped'])
        for key in ('elapsedActiveMs', 'maxHeight', 'falls', 'grapples', 'completed'):
            self.assertEqual(row['after'][key], row['before'][key], key)
        self.assertEqual(row['after']['goBacks'], row['before']['goBacks'] + 1)
        self.assertEqual(row['save']['goBacks'], row['after']['goBacks'])
        self.assertEqual(row['design'], [['goback:' + cp['section']]])
        # At rest: 600 ticks with no input keep it hooked and in place.
        self.assertTrue(row['rest']['grappled'])
        self.assertEqual(row['rest']['anchor'], row['anchor'])
        self.assertEqual(row['rest']['falls'], row['before']['falls'])
        self.assertLessEqual(row['rest']['maxMove'], 50)
        self.evidence['return'] = {'checkpoint': cp, **row}

    def test_08_held_press(self):
        page, cp = self.go_back_setup()
        # A press made before the call (it throws a shot) and held through it.
        page.mouse.move(100, 100)
        page.mouse.down()
        held = page.evaluate('''() => {
            const thrown = grapnel.throwed && !grapnel.grappled
            const returned = returnToCheckpoint()
            const anchor = () => grapnel.pos.length ? [grapnel.pos[0][0], grapnel.pos[0][1]] : null
            const input = {pressHeld, stalePress, gameplayPressOwned}
            for (let i = 0; i < 60; i++) physics()
            return {thrown, returned, input, grappled: grapnel.grappled, anchor: anchor()}
        }''')
        page.mouse.move(400, 300)
        steered = page.evaluate('() => ({aim: grapnel.aim, grappled: grapnel.grappled})')
        page.mouse.up()
        released = page.evaluate('''() => { for (let i = 0; i < 30; i++) physics()
            return {grappled: grapnel.grappled, throwed: grapnel.throwed,
                anchor: [grapnel.pos[0][0], grapnel.pos[0][1]], input: {pressHeld, stalePress, gameplayPressOwned}} }''')
        page.mouse.move(640, 100)
        page.mouse.down()
        pressed = page.evaluate('''() => ({grappled: grapnel.grappled, throwed: grapnel.throwed,
            fromNinja: grapnel.pos[0][2].isEmpty(), owned: gameplayPressOwned})''')
        page.mouse.up()
        self.assertTrue(held['thrown'])
        self.assertTrue(held['returned'])
        self.assertEqual(held['input'], {'pressHeld': True, 'stalePress': True, 'gameplayPressOwned': False})
        anchor = [cp['anchorX'], cp['anchorY']]
        # Held: still hooked at the checkpoint, the move does not steer.
        self.assertTrue(held['grappled'])
        self.assertEqual(held['anchor'], anchor)
        self.assertTrue(steered['grappled'])
        self.assertIsNone(steered['aim'])
        # The release of that press does not drop the rope.
        self.assertTrue(released['grappled'] and released['throwed'])
        self.assertEqual(released['anchor'], anchor)
        self.assertEqual(released['input'], {'pressHeld': False, 'stalePress': False, 'gameplayPressOwned': False})
        # The next press throws a new shot.
        self.assertEqual(pressed, {'grappled': False, 'throwed': True, 'fromNinja': True, 'owned': True})
        self.evidence['held_press'] = {'held': held, 'steered': steered, 'released': released, 'pressed': pressed}

    def test_09_no_checkpoint(self):
        page = self.open()
        rows = page.evaluate('''() => {
            const state = () => JSON.stringify([ninja.x, ninja.y, ninja.speedX, ninja.speedY, grapnel.throwed,
                grapnel.grappled, floors[0].climbStats])
            const before = state(), returned = returnToCheckpoint()
            const out = {climb: {returned, unchanged: state() === before}}
            if (!menu.gamePaused) menu.startPause()
            menu.selectMode('classic')
            out.classic = {version, returned: returnToCheckpoint()}
            return out
        }''')
        self.assertEqual(rows, {'climb': {'returned': False, 'unchanged': True},
                                'classic': {'version': 'classic', 'returned': False}})
        self.evidence['no_checkpoint'] = rows


if __name__ == '__main__':
    unittest.main()
