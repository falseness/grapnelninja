"""Pause screen 'lighting' checkbox: MOMENTUM_FX.enabled on/off (TASK-051).

The switch lives under the fps counter checkbox. A click flips
MOMENTUM_FX.enabled, PROGRESS stores it as grapnelninja.lighting
('true'/'false') and a reload brings it back; a stored blob from before the
key existed loads as on. window.setMomentumFx(bool) is the test hook.
Layout: at 1280x720, 844x390 (touch) and 390x844 (mouse, letterboxed: a
touch portrait phone shows the rotate overlay) the checkbox hit rect lies
inside the canvas and intersects no other pause-screen button
(LAYOUT_PROBE boxes of menu.drawPauseScreen()).
The switch acts on momentum only, so the classic and bad pause screens
neither draw it nor take clicks on it (TASK-095); switching modes leaves
the stored setting as it is.

Env: MOMENTUM_LIGHTING_SWITCH_EVIDENCE_DIR receives switch.json, layout.json
and shots/pause-<w>x<h>-lighting-{on,off}.png.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import READY, canvas_to_viewport, local_store, open_game, seed_store, start_game_test, switch_mode
import layout_matrix as lm

ROOT = Path(__file__).resolve().parent.parent
KEY = 'grapnelninja.lighting'
VIEWPORT = {'width': 1280, 'height': 720}
SIZES = [(1280, 720, False), (844, 390, True), (390, 844, False)]
FREEZE = '''() => {
    runFixedPhysics = function () {}
    reuseTimeInGame = function () {}
    time = null
}'''
# A stored progress blob written before grapnelninja.lighting existed
OLD_BLOB = {
    'grapnelninja.records': json.dumps({'classic': 3, 'bad': 2, 'momentum': 4}),
    'grapnelninja.time': '120', 'grapnelninja.lang': 'en', 'grapnelninja.tutorialDone': 'true',
}


def log(message):
    print('  ' + message, file=sys.stderr)


class MomentumLightingSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.out = os.environ.get('MOMENTUM_LIGHTING_SWITCH_EVIDENCE_DIR')
        cls.switch, cls.layout = [], {}
        cls.addClassCleanup(cls.save)

    @classmethod
    def save(cls):
        if not cls.out:
            return
        out = Path(cls.out)
        out.mkdir(parents=True, exist_ok=True)
        if cls.switch:
            (out / 'switch.json').write_text(json.dumps(cls.switch, separators=(',', ':')))
        if cls.layout:
            overlaps = sum(len(v['overlaps']) for v in cls.layout.values())
            (out / 'layout.json').write_text(json.dumps({'sizes': cls.layout, 'overlaps': overlaps},
                                                        separators=(',', ':')))

    def boot(self, viewport=VIEWPORT, **options):
        context, page, errors = open_game(self.browser, 'about:blank', viewport, **options)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual((errors['console'], errors['page']), ([], [])))
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY, timeout=30000)
        page.evaluate(FREEZE)
        return page

    def reload(self, page):
        page.evaluate('PROGRESS.flush()')
        page.wait_for_timeout(100)
        page.reload()
        page.wait_for_function(READY)
        page.evaluate(FREEZE)

    def seed_and_reload(self, page, store):
        # From a same-origin non-game page: the boot run's pagehide flush
        # would otherwise overwrite the seeded store
        page.goto(self.url + 'progress.js')
        seed_store(page, store)
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        page.evaluate(FREEZE)

    def enabled(self, page):
        return page.evaluate('MOMENTUM_FX.enabled')

    def stored(self, page):
        return local_store(page).get(KEY)

    def click_lighting(self, page):
        """A real mouse click on the centre of the checkbox hit rect."""
        r = page.evaluate('menu.pauseLightingCheckbox.hitRect()')
        point = canvas_to_viewport(page, r['x'] + r['width'] / 2, r['y'] + r['height'] / 2)
        page.mouse.click(point['x'], point['y'])

    def record(self, case, before, after, stored):
        self.switch.append({'case': case, 'before': before, 'after': after, 'storedValue': stored})
        log(f'{case}: before={before} after={after} stored={stored!r}')

    def test_a_default_on(self):
        """A fresh store boots with the switch on and stores 'true' on save."""
        page = self.boot()
        before = self.enabled(page)
        page.evaluate('menu.startPause()')
        # Nothing changed since boot, so nothing is written yet: a time
        # change makes the next write carry every key
        self.assertIsNone(self.stored(page))
        page.evaluate('PROGRESS.setTime(PROGRESS.getTime() + 1); PROGRESS.flush()')
        page.wait_for_timeout(100)
        self.record('default-on', before, self.enabled(page), self.stored(page))
        self.assertIs(before, True)
        self.assertEqual(page.evaluate('menu.pauseLightingCheckbox.checked()'), True)
        self.assertEqual(self.stored(page), 'true')
        self.assertIn(KEY, page.evaluate('PROGRESS.keys'))
        self.assertEqual(page.evaluate("I18N.t('menu.lighting')"), 'lighting')

    def test_b_click_toggles(self):
        """A click on the pause checkbox flips the flag and redraws; a second click flips it back."""
        page = self.boot()
        page.evaluate('menu.startPause()')
        before = self.enabled(page)
        page.evaluate('window.__draws = 0; const d = menu.drawPauseScreen; '
                      'menu.drawPauseScreen = (...args) => { ++window.__draws; return d.apply(menu, args) }')
        self.click_lighting(page)
        after = self.enabled(page)
        page.evaluate('PROGRESS.flush()')
        page.wait_for_timeout(100)
        self.record('click-toggles', before, after, self.stored(page))
        self.assertEqual((before, after), (True, False))
        self.assertTrue(page.evaluate('menu.gamePaused'))
        self.assertGreaterEqual(page.evaluate('window.__draws'), 1)
        self.assertEqual(page.evaluate('menu.pauseLightingCheckbox.checked()'), False)
        self.assertEqual(self.stored(page), 'false')
        self.click_lighting(page)
        page.evaluate('PROGRESS.flush()')
        page.wait_for_timeout(100)
        self.record('click-toggles-back', False, self.enabled(page), self.stored(page))
        self.assertIs(self.enabled(page), True)
        self.assertEqual(self.stored(page), 'true')
        # Unpaused the checkbox takes no clicks
        page.evaluate('menu.unPause()')
        self.assertFalse(page.evaluate('menu.pauseLightingCheckbox.clickable'))
        # Test hook
        page.evaluate('setMomentumFx(false)')
        self.assertIs(self.enabled(page), False)
        page.evaluate('setMomentumFx(true)')
        self.assertIs(self.enabled(page), True)

    def test_c_persisted_across_reload(self):
        """Off survives a reload, and so does on again."""
        page = self.boot()
        page.evaluate('menu.startPause()')
        before = self.enabled(page)
        self.click_lighting(page)
        self.reload(page)
        self.record('persisted-off', before, self.enabled(page), self.stored(page))
        self.assertIs(self.enabled(page), False)
        self.assertEqual(self.stored(page), 'false')
        page.evaluate('menu.startPause()')
        self.assertEqual(page.evaluate('menu.pauseLightingCheckbox.checked()'), False)
        self.click_lighting(page)
        self.reload(page)
        self.record('persisted-on', False, self.enabled(page), self.stored(page))
        self.assertIs(self.enabled(page), True)
        self.assertEqual(self.stored(page), 'true')

    def test_d_old_blob_without_key_loads_on(self):
        """A store without grapnelninja.lighting loads as on and keeps its other values."""
        page = self.boot()
        page.evaluate('setMomentumFx(false)')
        self.seed_and_reload(page, OLD_BLOB)
        before = self.stored(page)
        self.record('old-blob-on', before, self.enabled(page), before)
        self.assertIsNone(before)
        self.assertIs(self.enabled(page), True)
        self.assertEqual(page.evaluate('[scoreText.record.classic, scoreText.record.bad, '
                                       'scoreText.record.momentum, PROGRESS.getTime(), PROGRESS.getLang()]'),
                         [3, 2, 4, 120, 'en'])

    def test_f_hidden_outside_momentum(self):
        """Classic/bad: a click at the momentum checkbox rect changes nothing; it is not drawn."""
        page = self.boot()
        self.assertEqual(page.evaluate('version'), 'momentum')
        page.evaluate('menu.startPause()')
        r = page.evaluate('menu.pauseLightingCheckbox.hitRect()')
        drawn = page.evaluate(lm.PROBE, 'menu.drawPauseScreen()')
        label = page.evaluate('menu.pauseLightingCheckbox.label')
        self.assertIn(label, [b['name'] for b in drawn['boxes'] if b['kind'] == 'button'])
        page.evaluate('menu.unPause()')
        for mode in ['classic', 'bad']:
            with self.subTest(mode=mode):
                switch_mode(page, mode)
                page.evaluate(FREEZE)
                page.evaluate('menu.startPause()')
                before = self.enabled(page)
                shot = page.evaluate(lm.PROBE, 'menu.drawPauseScreen()')
                names = [b['name'] for b in shot['boxes'] if b['kind'] == 'button']
                point = canvas_to_viewport(page, r['x'] + r['width'] / 2, r['y'] + r['height'] / 2)
                page.mouse.click(point['x'], point['y'])
                # The same point through the menu's own hit test
                page.evaluate('p => menu.click(p)', {'x': r['x'] + r['width'] / 2, 'y': r['y'] + r['height'] / 2})
                after = self.enabled(page)
                self.record(f'{mode}-click-at-momentum-rect', before, after, self.stored(page))
                self.assertEqual(page.evaluate('version'), mode)
                self.assertNotIn(label, names)
                self.assertIs(before, True)
                self.assertIs(after, True)
                page.evaluate('menu.unPause()')
        # Off in momentum survives a round trip through classic
        switch_mode(page, 'momentum')
        page.evaluate(FREEZE)
        page.evaluate('menu.startPause()')
        self.click_lighting(page)
        self.assertIs(self.enabled(page), False)
        page.evaluate('menu.unPause()')
        switch_mode(page, 'classic')
        page.evaluate(FREEZE)
        switch_mode(page, 'momentum')
        self.record('off-across-mode-switches', False, self.enabled(page), self.stored(page))
        self.assertIs(self.enabled(page), False)

    def test_e_layout(self):
        """The hit rect is inside the canvas and overlaps no other pause button; shots on/off."""
        for w, h, touch in SIZES:
            size = f'{w}x{h}'
            with self.subTest(size=size):
                options = {'has_touch': True, 'is_mobile': True, 'device_scale_factor': 2} if touch else {}
                page = self.boot({'width': w, 'height': h}, **options)
                page.evaluate('TUTORIAL_HINT.visible = false; draw(); menu.startPause()')
                shot = page.evaluate(lm.PROBE, 'menu.drawPauseScreen()')
                boxes = lm.dedupe(shot['boxes'])
                buttons = [b for b in boxes if b['kind'] == 'button']
                label = page.evaluate('menu.pauseLightingCheckbox.label')
                hit = next(b for b in buttons if b['name'] == label)
                others = [b for b in buttons if b is not hit]
                canvas = shot['canvas']
                field = {'x': 0, 'y': 0, 'width': canvas['width'], 'height': canvas['height']}
                overlaps = [b['name'] for b in others if lm.intersect(hit, b)]
                self.layout[size] = {'touch': touch, 'canvas': field, 'hit': hit,
                                     'others': [{k: b[k] for k in ('name', 'x', 'y', 'width', 'height')}
                                                for b in others],
                                     'inside': lm.inside(hit, field), 'overlaps': overlaps}
                log(f'{size}: hit={[round(hit[k], 1) for k in ("x", "y", "width", "height")]} '
                    f'buttons={len(others)} overlaps={overlaps}')
                self.assertTrue(lm.inside(hit, field), size)
                self.assertEqual(overlaps, [], size)
                self.assertGreaterEqual(len(others), 3, size)
                if self.out:
                    shots = Path(self.out) / 'shots'
                    shots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shots / f'pause-{size}-lighting-on.png'))
                self.click_lighting(page)
                self.assertIs(self.enabled(page), False)
                if self.out:
                    page.screenshot(path=str(shots / f'pause-{size}-lighting-off.png'))


if __name__ == '__main__':
    unittest.main()
