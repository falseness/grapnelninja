"""TASK-792: Grapple Over 'Go back?' dialog after a long fall.

Boots the real index.html, freezes the frame loop, sets the go-back
checkpoint with a real grapnel catch (test_go_back helpers) and drives the
production physics() through scripted free falls in open air left of the
mountain. A fall of more than GO_BACK_FALL_THRESHOLD (10000) from the last
catch (LONG_FALL tracking) with the checkpoint above the player pauses the run
on the dialog, before the spawn fall recovery; 'Go back' hangs the player at
the checkpoint, 'Keep falling' resumes and (TASK-853) the dialog is offered
again more than 10000 below the point where it was shown (a new catch, a rise
or a go back restart that reference).
Mouse, touch and keyboard close it without throwing the grapnel; a pause key
or a tab hide leaves it open.

GO_BACK_DIALOG_EVIDENCE_DIR=DIR writes compact dialog.json and the
dialog-en.png / dialog-ru.png (1706x932) and dialog-touch.png (932x430
touch) screenshots there.

    python3 -m unittest discover -s tools -p test_go_back_dialog.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_go_back import SETUP, CANDIDATES, CATCH, AFTER

ROOT = Path(__file__).resolve().parent.parent
THRESHOLD = 10000
DEPTH = 1500

# Drop the rope and put the player at rest `height` above the spawn in open
# air left of the mountain; the fall is measured from here (a catch's baseline).
START = '''(height) => {
    const w = floors[0], minX = Math.min(...w.elements.flatMap(e => e.getPoints().map(p => p.x)))
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null,
        traveled: 0, speedX: 0, speedY: 0})
    ninja.x = minX - 3000; ninja.y = w.level.spawn.y - height; ninja.speedX = ninja.speedY = 0
    ninja.track.pos = []
    ninja.track.addPos(ninja.x, ninja.y, true)
    LONG_FALL.restartTracking()
    screen.trackGrappleOver(true)
}'''

# Production ticks until the run pauses, the fall passes stop or a recovery.
FALL = '''([ticks, stop]) => {
    const w = floors[0], falls = w.climbStats.falls
    let maxOpen = 0, n = 0
    for (; n < ticks && !menu.gamePaused && w.climbStats.falls === falls; n++) {
        physics()
        const d = LONG_FALL.tracking().displacement
        if (!menu.gamePaused) maxOpen = Math.max(maxOpen, d)
        if (stop && d >= stop) { n++; break }
    }
    return {ticks: n, maxOpen, ...STATE()}
}'''

# TASK-853: production ticks until the run pauses, a recovery, or the player
# is `stop` below fromY; maxBelow is the deepest point below fromY while open.
FALL_FROM = '''([ticks, fromY, stop]) => {
    const w = floors[0], falls = w.climbStats.falls
    let maxBelow = -Infinity, n = 0
    for (; n < ticks && !menu.gamePaused && w.climbStats.falls === falls; n++) {
        physics()
        if (!menu.gamePaused) maxBelow = Math.max(maxBelow, ninja.y - fromY)
        if (stop !== null && ninja.y - fromY >= stop) { n++; break }
    }
    return {ticks: n, maxBelow, ...STATE()}
}'''

# Drop the rope and move the player at its current height (no rise, so no
# reset of the fall start) and speed into the open air left of the mountain.
TO_OPEN_AIR = '''() => {
    const w = floors[0], minX = Math.min(...w.elements.flatMap(e => e.getPoints().map(p => p.x)))
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null,
        traveled: 0, speedX: 0, speedY: 0})
    ninja.x = minX - 3000; ninja.speedX = 0
    ninja.track.pos = []
    ninja.track.addPos(ninja.x, ninja.y, true)
    screen.trackGrappleOver(true)
}'''

STATE = '''() => {
    const w = floors[0], t = LONG_FALL.tracking()
    return {paused: menu.gamePaused, dialog: CLIMB_UI.goingBack, open: CLIMB_UI.goBackOpen(),
        displacement: t.displacement, goBackFromY: LONG_FALL.goBackFromY, ninja: [ninja.x, ninja.y],
        speed: [ninja.speedX, ninja.speedY], height: w.climbStats.currentHeight,
        elapsed: w.climbStats.elapsedActiveMs, falls: w.climbStats.falls, goBacks: w.climbStats.goBacks,
        grapnel: {throwed: grapnel.throwed, grappled: grapnel.grappled, aim: grapnel.aim,
            anchor: grapnel.pos.length ? [grapnel.pos[0][0], grapnel.pos[0][1]] : null},
        input: {pressHeld, stalePress, gameplayPressOwned}, timeInGame: getTimeInGame(),
        buttons: CLIMB_UI.buttons.map(b => b.text.text), focus: CLIMB_UI.goBackFocus,
        spawn: [w.level.spawn.x, w.level.spawn.y], recoveries: window.RECOVERIES.length}
}'''

# Count recoveries through the production function.
HOOKS = '''() => {
    window.STATE = ''' + STATE + '''
    window.RECOVERIES = []
    const recover = recoverClimbFall
    recoverClimbFall = function() { RECOVERIES.push(floors[0].climbStats.currentHeight); return recover() }
}'''


class GoBackDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.evidence = {}
        cls.out = os.environ.get('GO_BACK_DIALOG_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            Path(cls.out, 'dialog.json').write_text(json.dumps(cls.evidence, indent=1, sort_keys=True) + '\n')

    def open(self, viewport=(1280, 720), touch=False, lang=None):
        options = {'viewport': {'width': viewport[0], 'height': viewport[1]}}
        if touch:
            options.update(has_touch=True, is_mobile=True)
        context = self.browser.new_context(**options)
        self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        page.evaluate(SETUP)
        page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        if lang:
            page.evaluate('l => setLanguage(l)', lang)
        page.evaluate(HOOKS)
        self.addCleanup(lambda: self.assertEqual(page.errors, []))
        return page

    def catch(self, page, target):
        """Real mouse throw from 400 units under target's lowest vertex, then
        one production tick so LONG_FALL sees the catch."""
        page.mouse.up()
        page.evaluate(CATCH, [target['x'], target['y']])
        p = page.evaluate('''([x, y]) => canvasCoordsToViewportCoords({
            x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})''', [target['x'], target['y']])
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        row = page.evaluate(AFTER)
        if row['grappled'] and row['target'] == target['id']:
            page.evaluate('() => { ninja.speedX = ninja.speedY = 0; physics() }')
        page.mouse.up()
        return row

    def checkpoint(self, page):
        """The first static candidate the real throw catches becomes the checkpoint."""
        for target in page.evaluate(CANDIDATES)['static']:
            row = self.catch(page, target)
            if row['grappled'] and row['target'] == target['id'] and row['checkpoint']:
                return row['checkpoint']
        self.fail('no catchable checkpoint')

    def long_fall(self, page, height=9000):
        """A fall from `height` that opens the dialog past 10000."""
        page.evaluate(START, height)
        return page.evaluate(FALL, [2000, None])

    def high_checkpoint(self, page, height=60000):
        """TASK-853: the first static candidate more than `height` above the
        spawn that the real throw catches becomes the checkpoint, so falls of
        more than 2 x 10000 under it end long before the spawn recovery."""
        spawn = page.evaluate('floors[0].level.spawn.y')
        for target in page.evaluate(CANDIDATES)['static']:
            if spawn - target['y'] <= height:
                continue
            row = self.catch(page, target)
            if row['grappled'] and row['target'] == target['id'] and row['checkpoint']:
                self.assertGreater(spawn - row['checkpoint']['anchorY'], 21500)
                return row['checkpoint'], spawn
        self.fail('no catchable high checkpoint')

    def keep_falling(self, page):
        page.keyboard.press('Escape')
        row = page.evaluate('() => STATE()')
        self.assertFalse(row['paused'] or row['dialog'])
        return row

    def button(self, page, i):
        """Viewport centre of dialog button i."""
        return page.evaluate('''i => { const r = CLIMB_UI.buttons[i].background
            return canvasCoordsToViewportCoords({x: r.x + r.width / 2, y: r.y + r.height / 2}) }''', i)

    def test_01_long_fall_opens_dialog(self):
        page = self.open()
        cp = self.checkpoint(page)
        row = self.long_fall(page)
        self.assertTrue(row['paused'] and row['dialog'] and row['open'])
        self.assertEqual(row['buttons'], ['Go back', 'Keep falling'])
        # Opened at the first step past the threshold, before any recovery
        self.assertGreater(row['displacement'], THRESHOLD)
        self.assertLessEqual(row['maxOpen'], THRESHOLD)
        self.assertGreater(row['height'], -DEPTH)
        self.assertEqual(row['recoveries'], 0)
        self.assertLess(cp['anchorY'], row['ninja'][1])
        # TASK-853: the next offer measures from the dialog point
        self.assertEqual(row['goBackFromY'], row['ninja'][1])
        # Timer and physics stopped: production ticks change nothing
        page.wait_for_timeout(1200)
        frozen = page.evaluate('() => { for (let i = 0; i < 200; i++) physics(); return STATE() }')
        for key in ('ninja', 'speed', 'elapsed', 'timeInGame', 'height', 'falls', 'paused', 'dialog'):
            self.assertEqual(frozen[key], row[key], key)
        self.evidence['a_long_fall'] = {'checkpoint': cp, 'opened': row, 'after_200_ticks': frozen}

    def test_02_short_fall_no_dialog(self):
        page = self.open()
        self.checkpoint(page)
        # Two 9000 falls from 20000, an upward kick between them (a new apex)
        page.evaluate(START, 20000)
        first = page.evaluate(FALL, [2000, 9000])
        page.evaluate('() => { ninja.speedY = -1; physics() }')
        second = page.evaluate(FALL, [2000, 9000])
        for row in (first, second):
            self.assertFalse(row['paused'] or row['dialog'])
            self.assertGreaterEqual(row['displacement'], 9000)
            self.assertLess(row['displacement'], THRESHOLD)
            self.assertEqual(row['recoveries'], 0)
        # The reference follows the new apex like the long-fall start
        self.assertEqual(second['ninja'][1] - second['goBackFromY'], second['displacement'])
        self.evidence['b_9000_fall'] = {'first': first, 'second': second}

    def test_03_no_checkpoint_recovers(self):
        page = self.open()
        self.assertIsNone(page.evaluate('floors[0].climbCheckpoint'))
        none = self.long_fall(page)
        # Past 10000 without a dialog, then the spawn recovery as today
        self.assertFalse(none['paused'] or none['dialog'])
        self.assertEqual(none['recoveries'], 1)
        self.assertEqual(none['falls'], 1)
        self.assertEqual(none['ninja'], none['spawn'])
        self.assertGreater(none['maxOpen'], THRESHOLD)
        # A checkpoint under the player does not offer either
        cp = self.checkpoint(page)
        page.evaluate('cp => { floors[0].climbCheckpoint = {...cp, anchorY: floors[0].level.spawn.y + 5000} }', cp)
        below = self.long_fall(page)
        self.assertFalse(below['paused'] or below['dialog'])
        self.assertEqual(below['recoveries'], 2)
        self.evidence['c_no_checkpoint'] = {'none': none, 'checkpoint_below': below}

    def test_04_go_back_mouse(self):
        page = self.open()
        cp = self.checkpoint(page)
        opened = self.long_fall(page)
        self.assertTrue(opened['dialog'])
        p = self.button(page, 0)
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        held = page.evaluate('() => { for (let i = 0; i < 30; i++) physics(); return STATE() }')
        page.mouse.up()
        rest = page.evaluate('''() => { const s = STATE(); let maxMove = 0
            for (let i = 0; i < 600; i++) { physics(); maxMove = Math.max(maxMove, Math.hypot(ninja.x - s.ninja[0], ninja.y - s.ninja[1])) }
            return {maxMove, ...STATE()} }''')
        self.assertFalse(held['paused'] or held['dialog'])
        anchor = [cp['anchorX'], cp['anchorY']]
        for row in (held, rest):
            self.assertTrue(row['grapnel']['grappled'])
            self.assertEqual(row['grapnel']['anchor'], anchor)
            self.assertEqual(row['goBacks'], opened['goBacks'] + 1)
            self.assertEqual(row['falls'], opened['falls'])
            self.assertEqual(row['recoveries'], 0)
        self.assertEqual(held['ninja'][0], cp['anchorX'])
        self.assertLessEqual(rest['maxMove'], 50)
        self.assertGreater(rest['elapsed'], opened['elapsed'])
        # (g) the closing press neither steered nor released
        self.assertIsNone(held['grapnel']['aim'])
        self.assertEqual(held['input'], {'pressHeld': True, 'stalePress': True, 'gameplayPressOwned': False})
        # A go back restarts the offer's reference at the hang
        self.assertLessEqual(abs(rest['ninja'][1] - rest['goBackFromY']), 50)
        self.evidence['d_go_back'] = {'checkpoint': cp, 'opened': opened, 'held': held, 'rest': rest}

    def test_05_keep_falling_mouse(self):
        page = self.open()
        cp = self.checkpoint(page)
        opened = self.long_fall(page, 12000)
        self.assertTrue(opened['dialog'])
        p = self.button(page, 1)
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        resumed = page.evaluate('() => { physics(); return STATE() }')
        page.mouse.up()
        released = page.evaluate('() => STATE()')
        # Keeps falling to the spawn recovery without a second dialog
        down = page.evaluate(FALL, [2000, None])
        # Keep falling measures the next offer from the dialog point (TASK-853);
        # the spawn recovery comes first here (3500 below it) and restarts it
        self.assertFalse(resumed['paused'] or resumed['dialog'])
        self.assertGreater(resumed['ninja'][1], opened['ninja'][1])
        self.assertEqual(resumed['goBackFromY'], opened['ninja'][1])
        self.assertFalse(down['paused'] or down['dialog'])
        self.assertEqual(down['recoveries'], 1)
        self.assertLess(down['ninja'][1] - opened['ninja'][1], THRESHOLD)
        self.assertLessEqual(down['goBackFromY'], down['spawn'][1])
        self.checkpoint(page)
        reopened = self.long_fall(page)
        self.assertTrue(reopened['dialog'])
        # (g) the closing press does not throw
        for row in (resumed, released, down):
            self.assertFalse(row['grapnel']['throwed'])
        self.assertEqual(resumed['input'], {'pressHeld': True, 'stalePress': True, 'gameplayPressOwned': False})
        self.evidence['e_keep_falling'] = {'checkpoint': cp, 'opened': opened, 'resumed': resumed,
                                           'released': released, 'to_recovery': down, 'reopened': reopened}

    def test_06_dialog_before_recovery(self):
        page = self.open()
        cp = self.checkpoint(page)
        # One tick crosses both the 10000 fall and the 1500 recovery depth
        page.evaluate(START, 8400)
        both = page.evaluate('''() => { ninja.y += 10100; ninja.speedY = 5; physics(); return STATE() }''')
        self.assertTrue(both['dialog'] and both['paused'])
        self.assertLess(both['height'], -DEPTH)
        self.assertGreater(both['displacement'], THRESHOLD)
        self.assertEqual(both['recoveries'], 0)
        self.assertEqual(both['falls'], 0)
        page.keyboard.press('ArrowRight')
        page.keyboard.press('Enter')
        after = page.evaluate('() => { physics(); return STATE() }')
        self.assertFalse(after['paused'] or after['dialog'])
        self.assertEqual(after['recoveries'], 1)
        self.assertEqual(after['ninja'][0], after['spawn'][0])
        # Go back from the same both-thresholds tick skips the recovery
        page.evaluate(START, 8400)
        again = page.evaluate('''() => { ninja.y += 10100; ninja.speedY = 5; physics(); return STATE() }''')
        page.keyboard.press('Enter')
        back = page.evaluate('() => { for (let i = 0; i < 30; i++) physics(); return STATE() }')
        self.assertTrue(again['dialog'])
        self.assertEqual(back['recoveries'], 1)
        self.assertEqual(back['grapnel']['anchor'], [cp['anchorX'], cp['anchorY']])
        self.evidence['f_before_recovery'] = {'checkpoint': cp, 'both': both, 'keep_falling': after,
                                              'both_again': again, 'go_back': back}

    def test_07_keyboard_touch_pause_hide(self):
        page = self.open()
        cp = self.checkpoint(page)
        self.long_fall(page)
        keys = []
        for key in ('ArrowRight', 'ArrowLeft', 'ArrowDown', 'p', 'Escape'):
            page.keyboard.press(key)
            keys.append([key, page.evaluate('() => STATE()')])
        self.assertEqual([k[1]['focus'] for k in keys[:4]], [1, 0, 1, 1])
        # P keeps it open; Escape keeps falling
        self.assertTrue(all(k[1]['dialog'] and k[1]['paused'] for k in keys[:4]))
        self.assertFalse(keys[4][1]['dialog'] or keys[4][1]['paused'])
        # A pause (blur, tab hide, host pause) while open keeps it open
        self.checkpoint(page)
        self.long_fall(page)
        hidden = page.evaluate('''() => {
            pauseRun()
            window.onblur()
            Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'})
            document.dispatchEvent(new Event('visibilitychange'))
            const s = STATE()
            delete document.visibilityState
            return s }''')
        self.assertTrue(hidden['dialog'] and hidden['open'] and hidden['paused'])
        page.keyboard.press('Enter')
        entered = page.evaluate('() => { physics(); return STATE() }')
        self.assertFalse(entered['dialog'])
        self.assertEqual(entered['grapnel']['anchor'], [cp['anchorX'], cp['anchorY']])
        # Touch: a tap on Keep falling, not passed to gameplay
        touch = self.open(viewport=(932, 430), touch=True)
        self.checkpoint(touch)
        self.long_fall(touch)
        p = self.button(touch, 1)
        touch.touchscreen.tap(p['x'], p['y'])
        tapped = touch.evaluate('() => { for (let i = 0; i < 10; i++) physics(); return STATE() }')
        self.assertFalse(tapped['dialog'] or tapped['paused'])
        self.assertFalse(tapped['grapnel']['throwed'])
        self.evidence['keys_touch_hide'] = {'keys': keys, 'hidden': hidden, 'enter': entered, 'touch_tap': tapped}

    def test_09_asks_again_after_keep_falling(self):
        """(a) no second dialog 9000 below the dialog point; (b) it opens again
        once more than 10000 below it, and a third 10000 below that."""
        page = self.open()
        cp, spawn = self.high_checkpoint(page)
        page.evaluate(START, spawn - cp['anchorY'] - 100)
        first = page.evaluate(FALL, [4000, None])
        self.assertTrue(first['dialog'] and first['paused'])
        self.assertGreater(first['displacement'], THRESHOLD)
        self.assertEqual(first['goBackFromY'], first['ninja'][1])
        y1 = first['ninja'][1]
        resumed = self.keep_falling(page)
        self.assertEqual(resumed['goBackFromY'], y1)
        near = page.evaluate(FALL_FROM, [4000, y1, 9000])
        self.assertFalse(near['paused'] or near['dialog'])
        self.assertGreaterEqual(near['ninja'][1] - y1, 9000)
        self.assertLess(near['ninja'][1] - y1, THRESHOLD)
        second = page.evaluate(FALL_FROM, [4000, y1, None])
        self.assertTrue(second['dialog'] and second['paused'] and second['open'])
        self.assertEqual(second['buttons'], ['Go back', 'Keep falling'])
        self.assertGreater(second['ninja'][1] - y1, THRESHOLD)
        self.assertLessEqual(second['maxBelow'], THRESHOLD)
        self.assertLess(cp['anchorY'], second['ninja'][1])
        y2 = second['ninja'][1]
        self.keep_falling(page)
        third = page.evaluate(FALL_FROM, [4000, y2, None])
        self.assertTrue(third['dialog'])
        self.assertGreater(third['ninja'][1] - y2, THRESHOLD)
        self.assertLessEqual(third['maxBelow'], THRESHOLD)
        for row in (first, near, second, third):
            self.assertEqual(row['recoveries'], 0)
            self.assertEqual(row['falls'], 0)
            self.assertGreater(row['height'], -DEPTH)
        self.evidence['g_asks_again'] = {
            'checkpoint': cp, 'spawnY': spawn, 'first': first, 'resumed': resumed, 'near_9000': near,
            'second': second, 'third': third, 'second_minus_first_y': y2 - y1,
            'third_minus_second_y': third['ninja'][1] - y2}

    def test_10_catch_between_offers_resets(self):
        """(c) a new catch after Keep falling: the next offer needs 10000 from
        the catch, not from the dialog point."""
        page = self.open()
        cp, spawn = self.high_checkpoint(page)
        page.evaluate(START, spawn - cp['anchorY'] - 100)
        first = page.evaluate(FALL, [4000, None])
        self.assertTrue(first['dialog'])
        y1 = first['ninja'][1]
        self.keep_falling(page)
        mid = page.evaluate(FALL_FROM, [4000, y1, 5000])
        self.assertFalse(mid['dialog'])
        # A real catch whose hang is not above the falling player, so only the
        # catch (not a rise) can reset the reference; 10000 under it stays
        # well above the spawn recovery.
        targets = sorted((t for t in page.evaluate(CANDIDATES)['static']
                          if t['y'] + 400 >= mid['ninja'][1] and spawn - (t['y'] + 400) > 2 * THRESHOLD),
                         key=lambda t: t['y'])
        caught = None
        for target in targets:
            row = self.catch(page, target)
            if row['grappled'] and row['target'] == target['id']:
                caught = row
                break
        self.assertIsNotNone(caught, 'no catchable target under the player')
        # catch() ran one production tick on the rope (the catch), then released
        after = page.evaluate('() => STATE()')
        self.assertTrue(caught['grappled'])
        self.assertGreaterEqual(after['ninja'][1], mid['ninja'][1])
        self.assertEqual(after['goBackFromY'], after['ninja'][1])
        self.assertEqual(after['falls'], 0)
        # The checkpoint (higher) is kept
        self.assertEqual(page.evaluate('floors[0].climbCheckpoint'), cp)
        yc = after['ninja'][1]
        page.evaluate(TO_OPEN_AIR)
        # Past 10000 below the first dialog point and 9000 below the catch: no dialog
        near = page.evaluate(FALL_FROM, [4000, yc, 9000])
        self.assertFalse(near['paused'] or near['dialog'])
        self.assertGreater(near['ninja'][1] - y1, THRESHOLD)
        second = page.evaluate(FALL_FROM, [4000, yc, None])
        self.assertTrue(second['dialog'] and second['paused'])
        self.assertGreater(second['ninja'][1] - yc, THRESHOLD)
        self.assertLessEqual(second['maxBelow'], THRESHOLD)
        for row in (first, mid, near, second):
            self.assertEqual(row['recoveries'], 0)
        self.evidence['h_catch_resets'] = {
            'checkpoint': cp, 'first': first, 'mid': mid, 'catch': caught, 'after_catch': after,
            'near_9000': near, 'second': second, 'second_minus_catch_y': second['ninja'][1] - yc,
            'catch_minus_first_y': yc - y1}

    def test_11_no_offer_with_checkpoint_not_above(self):
        """(d) a fall that starts 12000 above the checkpoint: past 10000 with
        the checkpoint still below the player, no dialog; it opens on the
        first tick the checkpoint is above."""
        page = self.open()
        cp, spawn = self.high_checkpoint(page)
        page.evaluate(START, spawn - cp['anchorY'] + 12000)
        start_y = page.evaluate('ninja.y')
        above = page.evaluate(FALL_FROM, [4000, start_y, 11000])
        self.assertFalse(above['paused'] or above['dialog'])
        self.assertGreater(above['ninja'][1] - above['goBackFromY'], THRESHOLD)
        self.assertGreater(cp['anchorY'], above['ninja'][1])
        # Never under the checkpoint while open; open on the first tick under it
        opened = page.evaluate(FALL_FROM, [4000, cp['anchorY'], None])
        self.assertTrue(opened['dialog'])
        self.assertLess(cp['anchorY'], opened['ninja'][1])
        self.assertLessEqual(opened['maxBelow'], 0)
        self.assertGreater(opened['displacement'], 12000)
        self.assertEqual(opened['recoveries'], 0)
        # After Keep falling with the checkpoint moved under the player: no offer
        # 10000 below the dialog point, then the spawn recovery as today
        y1 = opened['ninja'][1]
        self.keep_falling(page)
        page.evaluate('y => { floors[0].climbCheckpoint = {...floors[0].climbCheckpoint, anchorY: y} }',
                      spawn + 5000)
        below = page.evaluate(FALL_FROM, [8000, y1, None])
        self.assertFalse(below['paused'] or below['dialog'])
        self.assertEqual(below['recoveries'], 1)
        self.assertGreater(below['maxBelow'], THRESHOLD)
        self.evidence['i_checkpoint_not_above'] = {'checkpoint': cp, 'start_y': start_y, 'above_11000': above,
                                                   'opened': opened, 'checkpoint_below_after_keep': below}

    def test_08_screenshots(self):
        shots = {}
        for name, viewport, touch, lang in (('dialog-en', (1706, 932), False, 'en'),
                                            ('dialog-ru', (1706, 932), False, 'ru'),
                                            ('dialog-touch', (932, 430), True, 'en')):
            page = self.open(viewport=viewport, touch=touch, lang=lang)
            self.checkpoint(page)
            row = self.long_fall(page)
            self.assertTrue(row['dialog'])
            page.evaluate('() => redrawOverlays()')
            size = page.evaluate('() => [window.innerWidth, window.innerHeight]')
            self.assertEqual(size, list(viewport))
            shots[name] = {'buttons': row['buttons'], 'title': page.evaluate("() => I18N.t('climb.goBackTitle')"),
                           'viewport': size}
            if self.out:
                Path(self.out).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(self.out, name + '.png')))
        self.assertEqual(shots['dialog-ru']['buttons'], ['Вернуться', 'Падать дальше'])
        self.assertEqual(shots['dialog-ru']['title'], 'Вернуться?')
        self.assertEqual(shots['dialog-en']['buttons'], ['Go back', 'Keep falling'])
        self.evidence['screenshots'] = shots


if __name__ == '__main__':
    unittest.main()
