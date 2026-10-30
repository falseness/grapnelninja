"""TASK-790: Grapple Over go-back checkpoint.

Boots the real index.html, freezes the frame loop and throws the production
grapnel (real mouse press, grapnel.move()/collision()) at chosen elements of
the shipped level. A new catch on a static (non-mover) element that is higher
than the current checkpoint records world.climbCheckpoint = {anchorX, anchorY,
ropeLength, section, bodyId}; movers never do. The checkpoint round-trips
through the climb save, older saves and saves naming a missing body load
without one, a restart clears it and the fall recovery keeps it.

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


if __name__ == '__main__':
    unittest.main()
