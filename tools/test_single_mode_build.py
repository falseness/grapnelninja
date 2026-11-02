"""TASK-854: single-mode builds (buildconfig.js BUILD_CONFIG.modes).

Boots the real index.html twice per case: once with buildconfig.js served
with modes: ['grapple_over'] (a single-mode release build, injected by a
route; the repo file is untouched) and once with the repo default.

Single mode: the boot run is Grapple Over; the pause, death (continue offer)
and win screens draw no mode button or mode switch and none is hit-testable;
menu.selectMode('bad'/'classic') and startGame('bad'/'classic') leave version
'grapple_over'; a saved store and a URL asking for another mode still boot
Grapple Over. Default: the same screens offer Bad and Classic, and both modes
are selectable as before.

SINGLE_MODE_EVIDENCE_DIR=DIR writes single-mode.json and the pause
screenshots pause-single-en.png, pause-single-ru.png, pause-default-en.png
(1706x932) there.

    python3 tools/test_single_mode_build.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = (ROOT / 'buildconfig.js').read_text()
DEFAULT_MODES = "modes: ['grapple_over', 'bad', 'classic']"
SINGLE_SOURCE = DEFAULT_SOURCE.replace(DEFAULT_MODES, "modes: ['grapple_over']")
OTHER_MODES = ('bad', 'classic')

# Records the label of every Button drawn while window.__drawn is an array
HOOKS = '''() => {
    if (window.__drawHook) return
    window.__drawHook = true
    const draw = Button.prototype.draw
    Button.prototype.draw = function(...args) {
        if (window.__drawn) window.__drawn.push(this.text.text)
        return draw.apply(this, args)
    }
}'''

# Draws the current overlays; returns the drawn and clickable button labels
SCREEN = '''() => {
    window.__drawn = []
    redrawOverlays()
    const drawn = window.__drawn
    window.__drawn = null
    const buttons = [...CLIMB_UI.buttons, ...menu.modeButtons, menu.resume,
        continueOffer.restartButton, continueOffer.switchButton]
    // A press at a button's centre, routed as the input handlers do (menu.click,
    // continueOffer.click), with every action stubbed: which button answers
    const saved = buttons.map(b => b.click)
    let pressed = null
    buttons.forEach(b => { b.click = () => { pressed = pressed || b } })
    const hit = b => {
        const r = b.background, c = {x: r.x + r.width / 2, y: r.y + r.height / 2}
        pressed = null
        if (menu.gamePaused) menu.click(c)
        if (continueOffer.visible) continueOffer.click(c)
        return pressed === b
    }
    const clickable = buttons.filter(hit).map(b => b.text.text)
    buttons.forEach((b, i) => { b.click = saved[i] })
    return {version, paused: menu.gamePaused, drawn, clickable,
        modeButtons: menu.modeButtons.map(b => b.mode)}
}'''

# Every label a mode button or the death screen's switch can carry, per language
LABELS = '''() => {
    const keys = ['mode.bad', 'mode.classic', 'menu.chillVersion', 'menu.mainVersion']
    return keys.map(k => I18N.t(k))
}'''


class SingleModeBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert SINGLE_SOURCE != DEFAULT_SOURCE, 'buildconfig.js default modes line changed'
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.evidence = {}
        cls.out = os.environ.get('SINGLE_MODE_EVIDENCE_DIR')

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            Path(cls.out, 'single-mode.json').write_text(
                json.dumps(cls.evidence, indent=1, sort_keys=True, ensure_ascii=False) + '\n')

    def open(self, single, viewport=(1706, 932), query='', store=None, lang=None):
        context = self.browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
        self.addCleanup(context.close)
        body = SINGLE_SOURCE if single else DEFAULT_SOURCE
        context.route('**/buildconfig.js', lambda route: route.fulfill(
            content_type='application/javascript', body=body))
        if store:
            context.add_init_script('(store => { for (const [k, v] of Object.entries(store))'
                                    ' localStorage.setItem(k, v) })(%s)' % json.dumps(store))
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.on('console', lambda m: m.type == 'error' and page.errors.append('console: %s' % m.text))
        page.goto(self.url + 'index.html' + query)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('BUILD_CONFIG.modes'),
                         ['grapple_over'] if single else ['grapple_over', 'bad', 'classic'])
        page.evaluate(HOOKS)
        if lang:
            page.evaluate('l => setLanguage(l)', lang)
        self.addCleanup(lambda: self.assertEqual(page.errors, []))
        return page

    def pause(self, page):
        page.evaluate('() => { if (!menu.gamePaused) menu.startPause() }')
        return page.evaluate(SCREEN)

    def assert_no_mode_ui(self, page, screen, name):
        labels = page.evaluate(LABELS)
        self.assertEqual(screen['modeButtons'], [], name)
        for label in labels:
            self.assertNotIn(label, screen['drawn'], name)
            self.assertNotIn(label, screen['clickable'], name)

    def test_01_single_boot_and_screens(self):
        page = self.open(True)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        result = {}
        # Pause
        pause = self.pause(page)
        self.assertTrue(pause['paused'])
        self.assertIn(page.evaluate("I18N.t('pause.resume')"), pause['drawn'])
        self.assert_no_mode_ui(page, pause, 'pause')
        result['pause'] = pause
        # Restart confirmation and back
        page.evaluate('() => { CLIMB_UI.confirming = true }')
        confirm = page.evaluate(SCREEN)
        self.assert_no_mode_ui(page, confirm, 'confirm')
        page.evaluate('() => { CLIMB_UI.confirming = false }')
        # Death screen (continue offer) over the run
        page.evaluate('() => { menu.unPause(); continueOffer.show() }')
        death = page.evaluate(SCREEN)
        self.assertIn(page.evaluate("I18N.t('continue.restart')"), death['drawn'])
        self.assertFalse(page.evaluate('continueOffer.switchButton.clickable'))
        self.assert_no_mode_ui(page, death, 'death')
        result['death'] = death
        page.evaluate('() => continueOffer.hide()')
        # Win screen, in a short and a wide (one row of buttons) view
        page.evaluate('() => CLIMB_UI.complete()')
        win = page.evaluate(SCREEN)
        self.assertIn(page.evaluate("I18N.t('climb.replay')"), win['drawn'])
        self.assertEqual(len(page.evaluate('CLIMB_UI.buttons')), 2)
        self.assert_no_mode_ui(page, win, 'win')
        result['win'] = win
        page.set_viewport_size({'width': 1280, 'height': 600})
        page.wait_for_timeout(200)
        wide = page.evaluate(SCREEN)
        self.assert_no_mode_ui(page, wide, 'win-wide')
        # The two win buttons are centred
        centre = page.evaluate('''() => {
            const b = CLIMB_UI.buttons.map(b => b.background)
            return [(b[0].x + b[1].x + b[1].width) / 2, menu.width / 2]
        }''')
        self.assertAlmostEqual(centre[0], centre[1], delta=1)
        result['winWide'] = wide
        self.evidence['single_screens'] = result

    def test_02_single_refuses_other_modes(self):
        page = self.open(True)
        rows = {}
        for mode in OTHER_MODES:
            rows['selectMode:' + mode] = page.evaluate('''mode => {
                if (!menu.gamePaused) menu.startPause()
                menu.selectMode(mode)
                return version
            }''', mode)
            rows['startGame:' + mode] = page.evaluate('mode => { startGame(mode); return version }', mode)
            # The continue offer's switch leads nowhere else either
            rows['switchFromOffer:' + mode] = page.evaluate('''() => {
                continueOffer.show(); switchFromOffer(); return version }''')
            page.wait_for_function("version === 'grapple_over' && !continueOffer.visible")
        for key, value in rows.items():
            self.assertEqual(value, 'grapple_over', key)
        self.evidence['single_refuses'] = rows

    def test_03_single_saved_and_url_state(self):
        store = {key: 'bad' for key in ('mode', 'version', 'lastMode', 'gameMode', 'grapnelninja.mode')}
        rows = {}
        for query in ('?mode=bad', '?version=classic&mode=classic', '#bad'):
            page = self.open(True, query=query, store=store)
            rows[query] = page.evaluate('version')
            self.assertEqual(rows[query], 'grapple_over', query)
        self.evidence['single_saved_url'] = rows

    def test_04_default_all_modes(self):
        page = self.open(False)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        pause = self.pause(page)
        labels = page.evaluate(LABELS)
        for label in labels[:2]:
            self.assertIn(label, pause['drawn'])
            self.assertIn(label, pause['clickable'])
        self.assertEqual(pause['modeButtons'], ['grapple_over', 'bad', 'classic'])
        page.evaluate('() => CLIMB_UI.complete()')
        win = page.evaluate(SCREEN)
        self.assertEqual(len(page.evaluate('CLIMB_UI.buttons')), 4)
        for label in labels[:2]:
            self.assertIn(label, win['drawn'])
        rows = {'pause': pause, 'win': win}
        for mode in ('bad', 'classic', 'grapple_over', 'classic', 'bad'):
            page.evaluate('''mode => { if (!menu.gamePaused) menu.startPause(); menu.selectMode(mode) }''', mode)
            # (back in Grapple Over the completed climb is restored: no run in progress)
            page.wait_for_function('mode => version === mode', arg=mode)
            rows['selected:' + mode] = page.evaluate('version')
        # Classic/Bad pause: three mode buttons, all clickable, centred
        classic = self.pause(page)
        self.assertEqual(classic['version'], 'bad')
        for label in [page.evaluate("I18N.t('mode.%s')" % m) for m in ('grapple_over', 'bad', 'classic')]:
            self.assertIn(label, classic['drawn'])
            self.assertIn(label, classic['clickable'])
        rows['badPause'] = classic
        # Death screen in Bad: the switch to Classic is drawn and clickable
        page.evaluate('() => { menu.unPause(); continueOffer.show() }')
        death = page.evaluate(SCREEN)
        switch = page.evaluate("I18N.t('menu.chillVersion')")
        self.assertIn(switch, death['drawn'])
        self.assertIn(switch, death['clickable'])
        page.evaluate('() => switchFromOffer()')
        page.wait_for_function("version === 'classic'")
        rows['death'] = death
        self.evidence['default'] = rows

    def test_05_pause_screenshots(self):
        shots = {}
        for name, single, lang in (('pause-single-en', True, 'en'), ('pause-single-ru', True, 'ru'),
                                   ('pause-default-en', False, 'en')):
            page = self.open(single, lang=lang)
            screen = self.pause(page)
            size = page.evaluate('() => [window.innerWidth, window.innerHeight]')
            self.assertEqual(size, [1706, 932])
            if single:
                self.assert_no_mode_ui(page, screen, name)
            shots[name] = {'drawn': screen['drawn'], 'viewport': size,
                           'language': page.evaluate('I18N.language')}
            if self.out:
                Path(self.out).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(self.out, name + '.png')))
        self.assertEqual(shots['pause-single-ru']['language'], 'ru')
        self.assertTrue(any(re.search('[А-Яа-я]', t) for t in shots['pause-single-ru']['drawn']))
        self.evidence['screenshots'] = shots


if __name__ == '__main__':
    unittest.main()
