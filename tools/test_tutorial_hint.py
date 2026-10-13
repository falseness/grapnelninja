"""The canvas tutorial hint (render/tutorialhint.js) over a running 'bad' run.

TUTORIAL_HINT.visible is forced by the tests (the tutorial lifecycle does not
drive it yet). Checks: the hint is drawn between the player and the HUD; a
visible hint adds no shadowBlur sets to the main context once its sprite is
built; a language change rebuilds the sprite once, with Russian text.

Uses the fake Playgama Bridge from test_playgama2_bridge. Requires Playwright
Chromium. No remote requests.

TUTORIAL_HINT_EVIDENCE_DIR (default: artifacts/TASK-366) receives
hint-desktop.png, hint-mobile.png, hint-ru.png and compare.png.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from test_playgama2_bridge import FAKE, SDK

ROOT = Path(__file__).resolve().parents[1]
CONCEPT = ROOT / 'artifacts/tutorial-concept'
BOOT_DONE = "probe.calls.some(c => c.name === 'game_ready') && " \
    "probe.calls.some(c => c.name === 'level_started')"
# Stops the game loop and freezes the clock and randomness, so draw() can be
# repeated on identical frames
FREEZE = '''() => {
    cancelAnimationFrame(game)
    const now = performance.now()
    performance.now = () => now
    let seed = 1
    Math.random = () => (seed = (seed * 16807) % 2147483647) / 2147483647
}'''
# Counts shadowBlur sets on the main context
SPY = '''() => {
    const property = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, 'shadowBlur')
    window.__shadowBlurSets = 0
    Object.defineProperty(ctx, 'shadowBlur', {
        configurable: true,
        get() { return property.get.call(this) },
        set(value) { ++window.__shadowBlurSets; property.set.call(this, value) }
    })
}'''
# Centre region of the canvas (device pixels) after one draw()
CENTRE = '''() => {
    draw()
    const c = ctx.canvas, w = Math.round(c.width * 0.3), h = Math.round(c.height * 0.3)
    return Array.from(ctx.getImageData(Math.round((c.width - w) / 2), Math.round((c.height - h) / 2), w, h).data)
}'''


def changed_pixels(a, b, threshold=40):
    return sum(1 for i in range(0, len(a), 4)
               if max(abs(a[i + k] - b[i + k]) for k in range(3)) > threshold)


class TutorialHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('TUTORIAL_HINT_EVIDENCE_DIR', ROOT / 'artifacts/TASK-366'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self, viewport=(1920, 1080), dpr=1, touch=False):
        context = self.browser.new_context(
            viewport={'width': viewport[0], 'height': viewport[1]}, device_scale_factor=dpr,
            is_mobile=touch, has_touch=touch, locale='en-US')
        self.addCleanup(context.close)
        context.route(SDK, lambda route: route.fulfill(content_type='application/javascript', body=
            'const FAULT = "normal"; const SAVED_LANGUAGE = "en";\n' + FAKE))
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(BOOT_DONE)
        self.assertEqual(page.evaluate('({version, runInProgress, paused: menu.gamePaused})'),
                         {'version': 'bad', 'runInProgress': True, 'paused': False})
        return page

    def capture(self, page, name):
        """Shows the hint over the live run for a few frames, then screenshots."""
        # The DOM first-run pop-up stays (lifecycle unchanged); it is hidden
        # here only so the capture shows the canvas hint alone
        page.evaluate('''() => { TUTORIAL.element.hidden = true; TUTORIAL_HINT.visible = true }''')
        page.evaluate('() => new Promise(r => { let n = 10; (function f() { --n ? requestAnimationFrame(f) : r() })() })')
        state = page.evaluate('''() => ({version, runInProgress, lines: TUTORIAL_HINT.lines,
            ninja: ninja.x !== undefined, key: TUTORIAL_HINT.spriteKey})''')
        page.screenshot(path=str(self.out / name))
        print('PASS capture', name, json.dumps(state, ensure_ascii=False), flush=True)
        return state

    def test_hint_drawn_without_per_frame_shadow_blur(self):
        page = self.open()
        page.evaluate(FREEZE)
        hidden = page.evaluate(CENTRE)
        hidden_again = page.evaluate(CENTRE)
        page.evaluate('TUTORIAL_HINT.visible = true')
        shown = page.evaluate(CENTRE)
        noise = changed_pixels(hidden, hidden_again)
        drawn = changed_pixels(hidden, shown)
        self.assertGreater(drawn, 20 * max(noise, 50), (drawn, noise))
        print(f'PASS hint pixels: {drawn} centre pixels changed by the hint '
              f'(hidden-vs-hidden noise {noise})', flush=True)

        # The sprite is built; count main-context shadowBlur sets per 60 frames
        page.evaluate(SPY)
        counts = page.evaluate('''() => {
            const count = visible => {
                TUTORIAL_HINT.visible = visible
                window.__shadowBlurSets = 0
                const built = TUTORIAL_HINT.buildCount
                for (let i = 0; i < 60; ++i) draw()
                return {sets: window.__shadowBlurSets, builds: TUTORIAL_HINT.buildCount - built}
            }
            return {hidden: count(false), visible: count(true)}
        }''')
        self.assertEqual(counts['visible']['builds'], 0)
        self.assertEqual(counts['visible']['sets'] - counts['hidden']['sets'], 0, counts)
        print('PASS shadowBlur sets over 60 frozen frames:', counts,
              '-> attributable to hint: 0', flush=True)

    def test_language_change_rebuilds_sprite_once(self):
        page = self.open()
        self.capture(page, 'hint-desktop.png')
        before = page.evaluate('({builds: TUTORIAL_HINT.buildCount, lines: TUTORIAL_HINT.lines})')
        self.assertEqual(before['lines'][0], 'HOLD')
        page.evaluate("setLanguage('ru')")
        state = self.capture(page, 'hint-ru.png')
        after = page.evaluate('({builds: TUTORIAL_HINT.buildCount, lines: TUTORIAL_HINT.lines})')
        self.assertEqual(after['builds'] - before['builds'], 1, (before, after))
        self.assertEqual(after['lines'], ['ДЕРЖИ', '— ЗАЦЕПИШЬСЯ', 'ДВИГАЙСЯ ВПРАВО  →'])
        self.assertTrue(state['key'].startswith('ru|mouse|'), state['key'])
        print('PASS language: builds', before['builds'], '->', after['builds'],
              json.dumps(after['lines'], ensure_ascii=False), flush=True)

    def test_mobile_touch_label(self):
        page = self.open((844, 390), dpr=3, touch=True)
        state = self.capture(page, 'hint-mobile.png')
        self.assertEqual(state['lines'][0], 'TOUCH & HOLD')
        self.assertTrue(state['key'].startswith('en|touch|'), state['key'])

    def test_zz_compare_sheet(self):
        """compare.png: each capture beside its concept-B reference."""
        from PIL import Image
        pairs = [('hint-desktop.png', 'concept-B-desktop.png'),
                 ('hint-mobile.png', 'concept-B-mobile.png'),
                 ('hint-ru.png', 'concept-B-desktop-ru.png')]
        rows = []
        for ours, concept in pairs:
            images = [Image.open(self.out / ours).convert('RGB'), Image.open(CONCEPT / concept).convert('RGB')]
            images = [im.resize((960, round(im.height * 960 / im.width))) for im in images]
            row = Image.new('RGB', (1940, max(im.height for im in images)), 'black')
            row.paste(images[0], (0, 0))
            row.paste(images[1], (980, 0))
            rows.append(row)
        sheet = Image.new('RGB', (1940, sum(r.height for r in rows) + 20 * (len(rows) - 1)), 'black')
        y = 0
        for row in rows:
            sheet.paste(row, (0, y))
            y += row.height + 20
        sheet.save(self.out / 'compare.png')
        print('PASS compare.png', sheet.size, 'left: game, right: concept B', flush=True)


if __name__ == '__main__':
    unittest.main()
