"""TASK-719: Grapple Over pause-menu grapnel toggle (single / double range).

The pause menu's last button toggles setGrapnelMode; a note under it says
single grapnel is the intended way to play and double range makes the game
easier. A switch keeps the run (position, time, best) and sets usedDouble.

GRAPNEL_MENU_EVIDENCE_DIR=DIR writes toggle.json, menu-en.png and menu-ru.png.

    python3 -m unittest discover -s tools -p test_grapnel_menu_toggle.py -v
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
OUT = os.environ.get('GRAPNEL_MENU_EVIDENCE_DIR')

STATE = '''() => { const s = floors[0].climbStats
    return {mode: floors[0].grapnelMode, usedDouble: floors[0].usedDouble, range: grappleOverAcquisitionRadius(),
        x: ninja.x, y: ninja.y, elapsedActiveMs: s.elapsedActiveMs, maxHeight: s.maxHeight,
        paused: menu.gamePaused, label: CLIMB_UI.buttons[CLIMB_UI.buttons.length - 1].text.text} }'''

# Viewport centre of the toggle (the last pause button) after a fresh draw.
TOGGLE = '''() => { redrawOverlays(); const b = CLIMB_UI.buttons[CLIMB_UI.buttons.length - 1].background
    return canvasCoordsToViewportCoords({x: b.x + b.width / 2, y: b.y + b.height / 2}) }'''

# Canvas rect (logical units) spanning the pause buttons, note and fps row.
CROP = '''() => { const first = CLIMB_UI.buttons[0].background, check = menu.pauseFpsCounterCheckbox.hitRect()
    const a = canvasCoordsToViewportCoords({x: first.x - 220, y: first.y - 10})
    const b = canvasCoordsToViewportCoords({x: first.x + first.width + 220, y: check.y + check.height + 10})
    return [a.x, a.y, b.x, b.y] }'''

EVIDENCE = {}


def tearDownModule():
    if OUT and EVIDENCE:
        Path(OUT).mkdir(parents=True, exist_ok=True)
        Path(OUT, 'toggle.json').write_text(json.dumps(EVIDENCE, separators=(',', ':'), sort_keys=True) + '\n')


class GrapnelMenuToggleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
        self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        return page

    def pause(self, page):
        # Some climbing first, so position, time and best are non-trivial.
        page.evaluate('''() => { cancelAnimationFrame(game); window.requestAnimationFrame = () => 0
            floors[0].climbStats.elapsedActiveMs = 12345; floors[0].climbStats.maxHeight = 678
            ninja.x += 37; ninja.y -= 91; menu.startPause() }''')
        page.wait_for_function('menu.gamePaused && !unTouch')

    def click_toggle(self, page):
        page.wait_for_function('!unTouch')
        xy = page.evaluate(TOGGLE)
        page.mouse.click(xy['x'], xy['y'])
        page.wait_for_function('!unTouch')
        page.evaluate('redrawOverlays()')
        return page.evaluate(STATE)

    def test_01_toggle_single_double_single(self):
        page = self.open()
        self.pause(page)
        states = [page.evaluate(STATE)]
        for _ in range(2):
            states.append(self.click_toggle(page))
        names = ['initial', 'afterDouble', 'afterSingle']
        rows = dict(zip(names, states))
        self.assertEqual([s['mode'] for s in states], ['single', 'double', 'single'])
        self.assertEqual([s['usedDouble'] for s in states], [False, True, True])
        self.assertEqual([s['range'] for s in states], [540, 1080, 540])
        self.assertEqual([s['label'] for s in states], ['Grapnel: single', 'Grapnel: double range', 'Grapnel: single'])
        for key in ('x', 'y', 'elapsedActiveMs', 'maxHeight'):
            self.assertEqual({s[key] for s in states}, {states[0][key]}, key)
        self.assertTrue(all(s['paused'] for s in states))
        saved = page.evaluate('PROGRESS.flushClimb(); captureClimbState()')
        self.assertEqual((saved['grapnelMode'], saved['usedDouble']), ('single', True))
        # Resume continues the same run.
        page.evaluate('menu.unPause()')
        resumed = page.evaluate(STATE)
        self.assertFalse(resumed['paused'])
        self.assertEqual((resumed['x'], resumed['y'], resumed['elapsedActiveMs'], resumed['maxHeight']),
                         (states[0]['x'], states[0]['y'], states[0]['elapsedActiveMs'], states[0]['maxHeight']))
        self.assertEqual(page.errors, [])
        EVIDENCE['toggle'] = dict(rows, input='trusted page.mouse.click on CLIMB_UI toggle button',
                                  savedAfter={'grapnelMode': saved['grapnelMode'], 'usedDouble': saved['usedDouble']},
                                  resumed={k: resumed[k] for k in ('x', 'y', 'elapsedActiveMs', 'maxHeight', 'paused')},
                                  checks={'rangeFollowsMode': True, 'positionTimeBestUnchanged': True,
                                          'usedDoubleStaysTrue': True})

    def test_02_menu_text_en_ru(self):
        from PIL import Image
        out = {}
        for lang in ('en', 'ru'):
            page = self.open()
            page.evaluate('l => { I18N.language = l; applyLanguage() }', lang)
            self.pause(page)
            page.evaluate('redrawOverlays()')
            labels = page.evaluate('CLIMB_UI.buttons.map(b => b.text.text)')
            expected = page.evaluate("['climb.grapnelSingle', 'climb.grapnelNote'].map(k => I18N.t(k))")
            self.assertEqual(labels[-1], expected[0])
            self.assertEqual(len(labels), 5)
            # The note is drawn under the toggle: catch its Text.draw.
            drawn = page.evaluate('''() => { const f = Text.prototype.draw, seen = []
                Text.prototype.draw = function() { seen.push(this.text); return f.apply(this, arguments) }
                try { redrawOverlays() } finally { Text.prototype.draw = f }
                return seen }''')
            self.assertIn(expected[1], drawn)
            check_y = page.evaluate('menu.pauseFpsCounterCheckbox.hitRect()')
            self.assertLessEqual(check_y['y'] + check_y['height'], page.evaluate('menu.height'))
            box = page.evaluate(CROP)
            png = page.screenshot()
            img = Image.open(io.BytesIO(png))
            box = [max(0, round(box[0])), max(0, round(box[1])), min(img.width, round(box[2])), min(img.height, round(box[3]))]
            if OUT:
                Path(OUT).mkdir(parents=True, exist_ok=True)
                img.crop(box).save(Path(OUT, f'menu-{lang}.png'), optimize=True)
            out[lang] = {'toggleLabel': labels[-1], 'note': expected[1], 'noteDrawn': True,
                         'fpsRowInsideView': True, 'crop': box}
            self.assertEqual(page.errors, [])
        self.assertIn('intended way to play', out['en']['note'])
        self.assertIn('задуманный способ игры', out['ru']['note'])
        EVIDENCE['menuText'] = out


if __name__ == '__main__':
    unittest.main()
