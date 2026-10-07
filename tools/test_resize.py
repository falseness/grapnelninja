"""Live resize mid-run in both modes, plus menu/HUD legibility at 800x450."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import logical_size
from game_harness import canvas_to_viewport, click_canvas, open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent
START_VIEWPORT = {'width': 1280, 'height': 720}
STEPS = [(800, 450), (1280, 720), (1920, 1080), (1024, 768), (2560, 1080), (844, 390),
         (1280, 720)]
MIN_CSS_FONT_PX = 12

# Count reStart calls and pin the ninja at its start state after every
# physics tick, so the run survives the whole sequence without input.
INSTRUMENT_RUN = '''() => {
    window.__reStarts = 0
    const original = window.reStart
    window.reStart = function() { window.__reStarts++; return original.apply(this, arguments) }
    const physicsStep = window.physics
    window.physics = function() {
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        const result = physicsStep.apply(this, arguments)
        ninja.x = window.__pin.x
        ninja.y = window.__pin.y
        ninja.speedX = 0
        ninja.speedY = 0
        return result
    }
}'''

# Measure visible UI text through the layout probe: glyphs may be drawn from
# cached sprites, while offscreen bloom text has no CSS box of its own.
INSTRUMENT_FONTS = '''() => {
    window.__fonts = []
    const original = LAYOUT_PROBE.text
    LAYOUT_PROBE.text = function(name, x, y) {
        if (!window.__fontTag) return original.call(this, name, x, y)
        const previous = this.boxes
        this.boxes = []
        try {
            original.call(this, name, x, y)
            for (const box of this.boxes)
                window.__fonts.push({tag: window.__fontTag, text: box.name,
                    css: Math.round(box.fontPx * 1e6) / 1e6})
        } finally { this.boxes = previous }
    }
}'''


def resize(page, viewport):
    """Resize and wait for the debounced (100 ms) live re-layout."""
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    expected = logical_size(*viewport)[0]
    page.wait_for_function('''([w, h, lw]) => { const r = canvas.getBoundingClientRect()
        return width == lw && menu.width == lw
            && Math.abs(r.width - Math.min(w, h * lw / 1080)) < 1 }''',
                           arg=[viewport[0], viewport[1], expected], timeout=5000)
    page.wait_for_timeout(50)


def mapped_click(page, x, y):
    """Click at logical (x, y); return the canvas coords the page mapped it to.

    A capturing listener swallows the event so the click has no game effect.
    """
    page.evaluate('''() => {
        window.__mapped = null
        window.__swallow = event => {
            window.__mapped = viewportCoordsToCanvasCoords({x: event.clientX, y: event.clientY})
            event.stopImmediatePropagation()
        }
        for (const type of ['mousedown', 'mouseup'])
            window.addEventListener(type, window.__swallow, true)
    }''')
    # Whole CSS px: Chromium truncates fractional mouse coordinates.
    point = canvas_to_viewport(page, x, y)
    page.mouse.click(round(point['x']), round(point['y']))
    return page.evaluate('''() => {
        for (const type of ['mousedown', 'mouseup'])
            window.removeEventListener(type, window.__swallow, true)
        return window.__mapped
    }''')


def run_state(page):
    return page.evaluate('''() => ({version: version, count: scoreText.count[version],
        reStarts: window.__reStarts, gamePaused: menu.gamePaused, menuVisible: menu.visible,
        width: width, height: height, menuWidth: menu.width,
        rect: canvas.getBoundingClientRect().toJSON(),
        hudButton: menu.button.background, scale: scale[version]})''')


class ResizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.screens = os.environ.get('RESIZE_SCREENS_DIR')
        cls.evidence = os.environ.get('RESIZE_EVIDENCE_DIR')
        cls.errors = []

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            for kind in ('console', 'page'):
                lines = [f'{name}: {msg}' for name, errors in cls.errors
                         for msg in errors[kind]]
                (out / f'{kind}-errors.log').write_text(''.join(
                    line + '\n' for line in lines))

    def boot(self, viewport):
        context, page, errors = open_game(self.browser, self.url + 'index.html', viewport)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('PLATFORM.environment === "local" && menu.visible')
        return page

    def write_evidence(self, name, data):
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / name).write_text(json.dumps(data, indent=1) + '\n')

    def start_run(self, page, mode):
        page.evaluate(INSTRUMENT_RUN)
        page.evaluate('''mode => {
            const b = (mode == 'bad' ? menu.badVersionButton : menu.classicVersionButton).background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
        }''', mode)
        page.wait_for_function('mode => !menu.visible && version === mode', arg=mode)

    def check_live_resize(self, mode):
        page = self.boot(START_VIEWPORT)
        self.start_run(page, mode)
        page.wait_for_timeout(2000)
        page.keyboard.press('p')
        start = run_state(page)
        self.assertEqual((start['version'], start['gamePaused'], start['reStarts']),
                         (mode, True, 0))
        steps = []
        for index, viewport in enumerate(STEPS, 1):
            tag = f'{viewport[0]}x{viewport[1]}'
            with self.subTest(step=index, viewport=tag):
                resize(page, viewport)
                after = run_state(page)
                centre = (after['width'] / 2, after['height'] / 2)
                mapped = mapped_click(page, *centre)
                mapping_error = max(abs(mapped['x'] - centre[0]), abs(mapped['y'] - centre[1]))
                toggles = []
                for _ in range(2):
                    page.keyboard.press('p')
                    toggles.append(page.evaluate('menu.gamePaused'))
                # Resume, then pause through the HUD button at its new position.
                page.keyboard.press('p')
                resumed = page.evaluate('menu.gamePaused')
                hud = after['hudButton']
                page.wait_for_function('!unTouch')
                click_canvas(page, (hud['x'] + hud['width'] / 2) * after['scale'],
                             (hud['y'] + hud['height'] / 2) * after['scale'])
                hud_paused = page.evaluate('menu.gamePaused')
                page.wait_for_timeout(50)
                if self.screens:
                    out = Path(self.screens) / mode
                    out.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(out / f'{index}_{tag}.png'))
                final = run_state(page)
                step = {'step': index, 'viewport': tag, 'logicalWidth': after['width'],
                        'expectedLogicalWidth': logical_size(*viewport)[0],
                        'version': final['version'], 'count': final['count'],
                        'reStarts': final['reStarts'], 'mapped': mapped,
                        'mappingError': mapping_error, 'pauseToggles': toggles,
                        'resumedPaused': resumed, 'hudButton': hud,
                        'hudClickPaused': hud_paused}
                steps.append(step)
                print(f'\n  {mode} {tag}: width={after["width"]} count={final["count"]} '
                      f'reStarts={final["reStarts"]} mapErr={mapping_error:.3g} '
                      f'toggles={toggles} hudPause={hud_paused}', file=sys.stderr, end='')
                self.assertEqual(after['width'], logical_size(*viewport)[0])
                self.assertEqual(final['version'], mode)
                self.assertEqual(final['count'], start['count'])
                self.assertEqual(final['reStarts'], 0)
                self.assertLessEqual(mapping_error, 1)
                self.assertEqual(toggles, [False, True])
                self.assertFalse(resumed)
                self.assertTrue(hud_paused)
        self.write_evidence(f'resize-{mode}.json', {'mode': mode, 'start': start, 'steps': steps})
        print(f'\n  ASSERT {mode}: {len(steps)} resizes keep version/score, no reStart, '
              'pause toggle, centre mapping <= 1, HUD pause button: pass', file=sys.stderr)

    def test_live_resize_classic(self):
        self.check_live_resize('classic')

    def test_live_resize_bad(self):
        self.check_live_resize('bad')

    def test_legibility_800x450(self):
        page = self.boot({'width': 800, 'height': 450})
        page.evaluate(INSTRUMENT_FONTS)

        def measure(tag, script, arg=None):
            page.evaluate('''([tag, script, arg]) => {
                window.__fontTag = tag
                try { (0, eval)(script)(arg) } finally { window.__fontTag = null }
            }''', [tag, script, arg])

        measure('menu', '() => menu.draw()')
        for mode in ('classic', 'bad'):
            self.start_run(page, mode)
            page.evaluate('fpsCounter.enabled = true')
            page.wait_for_timeout(300)
            measure(f'hud-{mode}', '() => draw()')
            page.keyboard.press('p')
            measure(f'pause-{mode}', '() => menu.drawPauseScreen()')
            page.evaluate('() => { fpsCounter.enabled = false; menu.backToMenu.click() }')
            page.wait_for_function('menu.visible')
        fonts = page.evaluate('window.__fonts')
        groups = {'menu': ['menu'], 'hud': ['hud-classic', 'hud-bad'],
                  'pause': ['pause-classic', 'pause-bad']}
        result = {'viewport': '800x450', 'minCssPx': MIN_CSS_FONT_PX, 'groups': {}}
        for group, tags in groups.items():
            drawn = [f for f in fonts if f['tag'] in tags]
            smallest = min(drawn, key=lambda f: f['css'])
            result['groups'][group] = {'samples': len(drawn), 'minCssPx': smallest['css'],
                                       'smallest': smallest}
            print(f'\n  {group}: {len(drawn)} texts, min {smallest["css"]:.2f} CSS px '
                  f'({smallest["tag"]} {smallest["text"]!r})', file=sys.stderr, end='')
        self.write_evidence('legibility.json', result)
        for group, data in result['groups'].items():
            self.assertGreater(data['samples'], 0, group)
            self.assertGreaterEqual(data['minCssPx'], MIN_CSS_FONT_PX, group)
        print('\n  ASSERT menu/HUD/pause min font >= 12 CSS px at 800x450: pass',
              file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
