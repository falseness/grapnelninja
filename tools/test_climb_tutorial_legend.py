"""TASK-663: the Grapple Over tutorial objective and obstacle legend.

Boots the real index.html, switches modes through the menu and languages
through the pause-screen language button, and reads what the production
tutorial sprite (render/tutorialhint.js) drew. In Grapple Over the hint's
objective is 'CLIMB TO THE TOP' with no arrow, over a legend: a green block
'= BOUNCE' and a yellow strip '= LOSE SPEED'. Classic and bad keep 'MOVE
RIGHT TO SCORE  →'. The legend follows the hint's lifecycle (shown until the
first press, then the 2.5 s fade) and draws no world objects.

Requires Playwright Chromium. No remote requests.

CLIMB_TUTORIAL_EVIDENCE_DIR=DIR writes tutorial-{desktop,touch}[-ru].png and
tutorial-text.json there.

    python3 -m unittest discover -s tools -p test_climb_tutorial_legend.py -v
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, select_mode
from render_snapshot import CLOCK_SCRIPT
from test_tutorial_hint import FRAMES_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
BOOT_DONE = "PLATFORM.environment === 'local' && bootComplete && runInProgress"
VIEWPORTS = {'desktop': dict(viewport={'width': 1280, 'height': 720}, device_scale_factor=1),
             # The 390x844 phone turned to landscape: upright, the stage is rotated and the
             # run waits paused under the turn-the-phone prompt (test_portrait_paused)
             'touch': dict(viewport={'width': 844, 'height': 390}, device_scale_factor=2,
                           is_mobile=True, has_touch=True),
             'portrait': dict(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                              is_mobile=True, has_touch=True)}
EXPECTED = {
    'en': {'hold': {'desktop': 'HOLD', 'touch': 'TOUCH & HOLD'}, 'grapple': 'TO GRAPPLE',
           'objective': 'CLIMB TO THE TOP', 'legend': ['BOUNCE', 'LOSE SPEED'],
           'right': 'MOVE RIGHT TO SCORE  →'},
    'ru': {'hold': {'desktop': 'ДЕРЖИ', 'touch': 'КОСНИСЬ И ДЕРЖИ'}, 'grapple': '— ЗАЦЕПИШЬСЯ',
           'objective': 'ПОДНИМИСЬ НА ВЕРШИНУ', 'legend': ['ОТСКОК', 'ЗАМЕДЛЕНИЕ'],
           'right': 'ДВИГАЙСЯ ВПРАВО  →'},
}
HINT = '({visible: TUTORIAL_HINT.visible, alpha: TUTORIAL_HINT.alpha, done: TUTORIAL_HINT.done})'
# What the sprite holds after a production draw() with the hint shown
SPRITE = '''() => {
    draw()
    const c = ctx.canvas, k = c.width / width, b = menu.constButton
    return {version, key: TUTORIAL_HINT.spriteKey, lines: TUTORIAL_HINT.lines,
        legend: TUTORIAL_HINT.legendBoxes, canvas: [c.width, c.height],
        menuButton: {x: b.x * k, y: b.y * k, w: b.width * k, h: b.height * k},
        touch: isTouchFirstDevice(), rotated: isViewRotated()}
}'''
# World collections that a legend drawing must never extend
WORLD = '''() => {
    const w = floors[0], g = grapnel
    return {elements: w.elements.length, dragZones: (w.dragZones || []).length,
        levelElements: w.level ? w.level.elements.length : null,
        movers: w.level ? w.level.movers.length : null, byId: w.byId ? w.byId.size : null,
        grapnel: g.pos.length, throwed: g.throwed}
}'''
# Pixel colour at a sprite point (device px) from the hint sprite
PIXEL = '''([x, y]) => Array.from(TUTORIAL_HINT.sprite.getContext('2d').getImageData(Math.round(x), Math.round(y), 1, 1).data)'''


def overlaps(a, b):
    return a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']


class ClimbTutorialLegendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = os.environ.get('CLIMB_TUTORIAL_EVIDENCE_DIR')
        cls.out = Path(out) if out else None
        if cls.out:
            cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.text = {}

    @classmethod
    def tearDownClass(cls):
        if cls.out and cls.text:
            path = cls.out / 'tutorial-text.json'
            old = json.loads(path.read_text()) if path.exists() else {}
            old.update(cls.text)
            path.write_text(json.dumps(old, ensure_ascii=False, separators=(',', ':')))

    def open(self, kind, clocked=False):
        context = self.browser.new_context(locale='en-US', **VIEWPORTS[kind])
        self.addCleanup(context.close)
        if clocked:
            context.add_init_script(CLOCK_SCRIPT)
            context.add_init_script(FRAMES_SCRIPT)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        if clocked:
            for _ in range(2000):
                page.evaluate('__frames(1)')
                if page.evaluate(BOOT_DONE):
                    break
            page.evaluate('() => { window.onblur = null }')
        page.wait_for_function(BOOT_DONE)
        self.assertEqual(page.evaluate('[I18N.language, isTouchFirstDevice()]'), ['en', kind != 'desktop'])
        return page

    def switch(self, page, mode):
        """Menu mode selection, then back to an unpaused run."""
        select_mode(page, mode)
        if page.evaluate("typeof __frames == 'function'"):
            for _ in range(400):
                if page.evaluate(f"version === '{mode}' && runInProgress && !interstitialPending"):
                    break
                page.evaluate('__frames(1)')
        if page.evaluate('menu.gamePaused'):
            page.evaluate('menu.unPause()')
        self.assertEqual(page.evaluate('[version, runInProgress, menu.gamePaused]'), [mode, True, False])

    def language_button(self, page):
        """The pause-screen language button, clicked at its centre."""
        page.evaluate('menu.startPause()')
        taken = page.evaluate('''() => { const r = LANGUAGE_BUTTON.rect()
            return LANGUAGE_BUTTON.click({x: r.x + r.width / 2, y: r.y + r.height / 2}) }''')
        self.assertTrue(taken)
        page.evaluate('menu.unPause()')

    def capture(self, page, name):
        page.evaluate('() => new Promise(r => { let n = 6; (function f() { --n ? requestAnimationFrame(f) : r() })() })')
        if self.out:
            page.screenshot(path=str(self.out / name))

    def check_climb(self, page, kind, lang):
        state = page.evaluate(SPRITE)
        exp = EXPECTED[lang]
        hold = 'desktop' if kind == 'desktop' else 'touch'
        self.assertEqual(state['lines'], [exp['hold'][hold], exp['grapple'], exp['objective']] + exp['legend'])
        self.assertTrue(state['key'].startswith(f"{lang}|grapple_over|{'mouse' if kind == 'desktop' else 'touch'}|"))
        self.assertNotIn('→', ''.join(state['lines']))
        W, H = state['canvas']
        legend = state['legend']
        self.assertEqual([b['label'] for b in legend], exp['legend'])
        # Inside the view, icon before its own label, no overlaps, clear of the menu button
        boxes = []
        for b in legend:
            icon = b['icon']
            text = {'x': b['text']['x'], 'y': icon['y'] + icon['h'] / 2 - H * 0.015, 'w': b['text']['width'], 'h': H * 0.03}
            self.assertGreater(icon['x'], 0)
            self.assertLess(text['x'] + text['w'], W)
            self.assertLessEqual(icon['x'] + icon['w'], text['x'])
            self.assertLess(text['x'] - (icon['x'] + icon['w']), H * 0.03)
            boxes += [icon, text]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(overlaps(a, b), (a, b))
            self.assertFalse(overlaps(a, state['menuButton']), (a, state['menuButton']))
        self.assertGreater(legend[1]['icon']['w'], 1.5 * legend[1]['icon']['h'])   # horizontal strip
        # Icon colours: green block, yellow strip (sampled inside, off the edge)
        colors = []
        for b in legend:
            icon = b['icon']
            px = page.evaluate(PIXEL, [icon['x'] + icon['w'] * 0.5, icon['y'] + icon['h'] * 0.1])
            colors.append(px)
        g, y = colors
        self.assertTrue(g[1] > 120 and g[1] > g[0] + 40 and g[1] > g[2] + 40, g)
        edge = page.evaluate(PIXEL, [legend[1]['icon']['x'] + 1, legend[1]['icon']['y'] + legend[1]['icon']['h'] / 2])
        self.assertTrue(edge[0] > 100 and edge[0] > edge[1] > 2 * edge[2] and edge[2] < 60, edge)
        record = {'lines': state['lines'], 'hold': state['lines'][0], 'grapple': state['lines'][1],
                  'objective': state['lines'][2], 'objectiveHasArrow': '→' in state['lines'][2],
                  'legend': [{'label': b['label'], 'text': '= ' + b['label'],
                              'icon': {k: round(v, 1) for k, v in b['icon'].items()}} for b in legend],
                  'iconPixels': {'bounceBody': g, 'dragEdge': edge}, 'canvas': state['canvas'],
                  'menuButton': {k: round(v, 1) for k, v in state['menuButton'].items()},
                  'rotated': state['rotated'], 'spriteKey': state['key'], 'noOverlap': True}
        self.text.setdefault(kind, {})[lang] = record
        return record

    def check_legacy(self, page, kind, lang, mode):
        state = page.evaluate(SPRITE)
        exp = EXPECTED[lang]
        self.assertEqual(state['lines'], [exp['hold'][kind], exp['grapple'], exp['right']])
        self.assertEqual(state['legend'], [])
        self.text.setdefault(kind, {}).setdefault('legacy', {})[f'{mode}-{lang}'] = {
            'lines': state['lines'], 'objective': state['lines'][2], 'legend': []}

    def run_viewport(self, kind):
        page = self.open(kind)
        # The boot run is the main mode, Grapple Over, with the hint shown
        self.assertEqual(page.evaluate('[version, TUTORIAL_HINT.visible]'), ['grapple_over', True])
        world = page.evaluate(WORLD)
        self.check_climb(page, kind, 'en')
        self.capture(page, f'tutorial-{kind}.png')
        self.language_button(page)
        self.assertEqual(page.evaluate('I18N.language'), 'ru')
        self.check_climb(page, kind, 'ru')
        self.capture(page, f'tutorial-{kind}-ru.png')
        # Many rebuilds and draws of the legend leave the world collections as they were
        page.evaluate('() => { for (let i = 0; i < 20; ++i) { TUTORIAL_HINT.invalidate(); draw() } }')
        self.assertEqual(page.evaluate(WORLD), world)
        self.text.setdefault(kind, {})['worldUnchanged'] = {'before': world, 'after': page.evaluate(WORLD)}
        for mode in ('classic', 'bad'):
            self.switch(page, mode)
            self.assertTrue(page.evaluate('TUTORIAL_HINT.visible'))
            self.check_legacy(page, kind, 'ru', mode)
        self.language_button(page)
        self.assertEqual(page.evaluate('I18N.language'), 'en')
        for mode in ('bad', 'classic'):
            self.switch(page, mode)
            self.check_legacy(page, kind, 'en', mode)
        print(f'PASS {kind}: en/ru objective+legend, classic/bad keep the score line, world unchanged {world}', flush=True)

    def test_desktop_text_and_legend(self):
        self.run_viewport('desktop')

    def test_touch_text_and_legend(self):
        self.run_viewport('touch')

    def lifecycle(self, kind):
        page = self.open(kind, clocked=True)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        self.assertEqual(page.evaluate(HINT), {'visible': True, 'alpha': 1, 'done': False})
        page.evaluate('__frames(30)')
        self.assertEqual(page.evaluate(HINT), {'visible': True, 'alpha': 1, 'done': False})
        self.assertEqual(page.evaluate('TUTORIAL_HINT.lines.length'), 5)
        page.evaluate('''() => { const draw0 = TUTORIAL_HINT.draw; window.__hintDraws = 0
            TUTORIAL_HINT.draw = function(...a) { ++__hintDraws; return draw0.apply(this, a) } }''')
        # The first real press (mouse down / touch) throws the grapnel and starts the fade
        if kind == 'touch':
            page.touchscreen.tap(300, 200)
        else:
            page.mouse.move(900, 200)
            page.mouse.down()
        self.assertTrue(page.evaluate('TUTORIAL_HINT.pressed'))
        page.evaluate('__frames(60)')
        mid = page.evaluate(HINT)
        self.assertTrue(mid['visible'] and 0 < mid['alpha'] < 1, mid)
        page.evaluate('__frames(100)')
        if kind != 'touch':
            page.mouse.up()
        self.assertEqual(page.evaluate(HINT), {'visible': False, 'alpha': 0, 'done': True})
        page.evaluate('window.__hintDraws = 0')
        page.evaluate('__frames(30)')
        self.assertEqual(page.evaluate('__hintDraws'), 0)
        # Leaving and re-entering Grapple Over does not bring it back
        self.switch(page, 'classic')
        self.switch(page, 'grapple_over')
        page.evaluate('__frames(30)')
        self.assertEqual(page.evaluate('[TUTORIAL_HINT.visible, __hintDraws]'), [False, 0])
        self.text.setdefault('lifecycle', {})[kind] = {'beforePress': {'visible': True, 'alpha': 1},
            'after1s': mid, 'after2.67s': {'visible': False, 'alpha': 0, 'done': True},
            'hintDrawsAfterFade': 0, 'reenterGrappleOverVisible': False}
        print(f'PASS lifecycle {kind}: shown until press, fade {mid}, hidden and not drawn after, '
              'not shown again on re-entry', flush=True)

    def test_portrait_paused(self):
        """Upright 390x844: the existing rule hides the hint under the paused climb;
        turning the phone to landscape shows the same legend."""
        page = self.open('portrait')
        page.evaluate('() => new Promise(r => setTimeout(r, 300))')
        state = page.evaluate('({rotated: isViewRotated(), paused: menu.gamePaused, visible: TUTORIAL_HINT.visible})')
        self.assertEqual(state, {'rotated': True, 'paused': True, 'visible': True})
        page.evaluate('''() => { const draw0 = TUTORIAL_HINT.draw; window.__hintDraws = 0
            TUTORIAL_HINT.draw = function(...a) { ++__hintDraws; return draw0.apply(this, a) } }''')
        page.evaluate('draw()')
        self.assertEqual(page.evaluate('__hintDraws'), 0)
        if self.out:
            page.screenshot(path=str(self.out / 'tutorial-portrait-390x844.png'))
        page.set_viewport_size({'width': 844, 'height': 390})
        page.wait_for_function('!isViewRotated() && canvas.width > canvas.height')
        page.evaluate('() => new Promise(r => setTimeout(r, 300))')
        page.evaluate('menu.unPause()')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        self.check_climb(page, 'portrait', 'en')
        self.assertGreater(page.evaluate('__hintDraws'), 0)
        self.text['portrait390x844'] = {'upright': dict(state, hintDraws=0),
            'turnedLandscape': {'hintDrawn': True, 'lines': self.text['portrait']['en']['lines']}}
        del self.text['portrait']
        print('PASS portrait 390x844: paused, hint not drawn; turned to landscape: legend drawn', flush=True)

    def test_lifecycle_desktop(self):
        self.lifecycle('desktop')

    def test_lifecycle_touch(self):
        self.lifecycle('touch')


if __name__ == '__main__':
    unittest.main()
