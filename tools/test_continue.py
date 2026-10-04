"""Continue offer after an eligible lethal death (TASK-080, Y8 port TASK-093).

Env: Y8_CONTINUE_EVIDENCE_DIR receives offer-*.png, button-rects.json and
console/page-errors.log.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import logical_size
from y8_harness import (FAKE_SDK, Y8_SDK_ROUTE, canvas_to_viewport, click_canvas,
                        collect_errors, open_game, sdk_calls, start_y8_test)

ROOT = Path(__file__).resolve().parent.parent

# Count reStart calls and pin the ninja at its start state after every physics
# tick so it never dies on its own. window.__kill moves it behind the deletion
# border before the next tick: a real lethal death through ninja.move().
# While the offer is shown the ninja is left alone, so a frozen run shows as
# unchanged x/y.
INSTRUMENT_RUN = '''() => {
    window.__reStarts = 0
    const original = window.reStart
    window.reStart = function() {
        window.__reStarts++
        window.__pin = null
        return original.apply(this, arguments)
    }
    const physicsStep = window.physics
    window.physics = function() {
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        if (window.__kill) {
            window.__kill = false
            ninja.x = screen.getDeletionBorder() - screen.x - 10 * ninja.radius
            ninja.speedX = 0
            ninja.speedY = 0
        }
        const result = physicsStep.apply(this, arguments)
        if (continueOffer.visible)
            return result
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        ninja.x = window.__pin.x
        ninja.y = window.__pin.y
        ninja.speedX = 0
        ninja.speedY = 0
        return result
    }
}'''

BUTTON_RECTS = '''() => {
    const rect = canvas.getBoundingClientRect()
    const css = rect.height / height
    const one = b => ({x: b.background.x, y: b.background.y,
        width: b.background.width, height: b.background.height,
        font: b.text.fontSize, fontPx: parseFloat(b.text.fontSize),
        cssWidth: b.background.width * css, cssHeight: b.background.height * css,
        cssFontPx: parseFloat(b.text.fontSize) * css,
        stroke: b.background.stroke, fill: b.background.fill, label: b.text.text})
    return {logical: {width: width, height: height}, canvasCss: rect.toJSON(),
            continue: one(continueOffer.continueButton), restart: one(continueOffer.restartButton)}
}'''


def show_ad_count(page):
    return sum(c['name'] == 'showAd' for c in sdk_calls(page))


def state(page):
    return page.evaluate('''() => ({offer: continueOffer.visible, score: scoreText.count[version],
        reStarts: window.__reStarts, continueUsed: continueUsed,
        x: ninja.x, y: ninja.y, gamePaused: menu.gamePaused, menuVisible: menu.visible})''')


class ContinueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_y8_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('Y8_CONTINUE_EVIDENCE_DIR')
        cls.errors = []
        cls.rects = {}

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
            if cls.rects:
                (out / 'button-rects.json').write_text(json.dumps(cls.rects, indent=1) + '\n')

    def boot(self, viewport, touch=False):
        if touch:
            context = self.browser.new_context(viewport=viewport, has_touch=True, is_mobile=True)
            context.route(Y8_SDK_ROUTE, lambda route: route.fulfill(
                path=str(FAKE_SDK), content_type='application/javascript'))
            page = context.new_page()
            errors = collect_errors(page)
            page.goto(self.url + 'index.html')
        else:
            context, page, errors = open_game(self.browser, self.url + 'index.html', viewport)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('PLATFORM.environment === "y8" && menu.visible')
        page.evaluate(INSTRUMENT_RUN)
        page.evaluate('''() => {
            const b = menu.classicVersionButton.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
        }''')
        page.wait_for_timeout(300)
        self.assertEqual(show_ad_count(page), 0)
        return page

    def kill(self, page, score):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(100)

    def wait_input(self, page):
        # events.js ignores input for STYLE.timing.inputUntouchMs after a button click
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def click_button(self, page, name):
        b = page.evaluate(f'''(() => {{ const b = continueOffer.{name}.background
            return {{x: b.x + b.width / 2, y: b.y + b.height / 2}} }})()''')
        click_canvas(page, b['x'], b['y'])
        self.wait_input(page)

    def tap_button(self, page, name):
        b = page.evaluate(f'''(() => {{ const b = continueOffer.{name}.background
            return {{x: b.x + b.width / 2, y: b.y + b.height / 2}} }})()''')
        p = canvas_to_viewport(page, b['x'], b['y'])
        page.touchscreen.tap(round(p['x']), round(p['y']))
        self.wait_input(page)

    def save(self, page, name):
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / name))

    def record_rects(self, page, key):
        rects = page.evaluate(BUTTON_RECTS)
        self.rects[key] = rects
        a, b = rects['continue'], rects['restart']
        for k in ('width', 'height', 'fontPx', 'stroke', 'fill'):
            self.assertEqual(a[k], b[k], f'{key}: buttons differ in {k}')
        # Inside the logical canvas and not overlapping each other
        for r in (a, b):
            self.assertGreaterEqual(r['x'], 0)
            self.assertLessEqual(r['x'] + r['width'], rects['logical']['width'])
            self.assertGreaterEqual(r['y'], 0)
            self.assertLessEqual(r['y'] + r['height'], rects['logical']['height'])
        self.assertLessEqual(a['y'] + a['height'], b['y'])
        self.assertGreaterEqual(min(a['cssFontPx'], b['cssFontPx']), 12)
        print(f'\n  {key}: buttons {a["width"]:.1f}x{a["height"]:.1f} font {a["fontPx"]:.2f}'
              f' (css {a["cssFontPx"]:.2f}px) equal: pass', file=sys.stderr)
        return rects

    def test_continue_flow_mouse(self):
        page = self.boot({'width': 1280, 'height': 720})

        # (a) score < CONTINUE_MIN_SCORE: instant restart, no overlay
        self.assertEqual(page.evaluate('CONTINUE_MIN_SCORE'), 5)
        self.kill(page, 4)
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score']), (False, 1, 0))
        self.assertEqual(show_ad_count(page), 0)
        print('  ASSERT (a) score 4 death -> instant reStart, no overlay: pass', file=sys.stderr)

        # (b) score >= 5: overlay, frozen physics, no ad requested yet
        self.kill(page, 5)
        before = state(page)
        self.assertTrue(before['offer'])
        self.assertEqual(before['reStarts'], 1)
        page.wait_for_timeout(1000)
        after = state(page)
        self.assertTrue(after['offer'])
        self.assertEqual((after['x'], after['y']), (before['x'], before['y']))
        self.assertEqual(show_ad_count(page), 0)
        print(f'  ASSERT (b) score 5 death -> overlay; ninja ({before["x"]:.3f},'
              f' {before["y"]:.3f}) unchanged over 1 s; no showAd: pass',
              file=sys.stderr)
        self.record_rects(page, '1280x720')
        self.save(page, 'offer-1280x720.png')

        # Live re-layout while the offer is shown (4:3 changes the logical width)
        page.set_viewport_size({'width': 1024, 'height': 768})
        page.wait_for_function('continueOffer.width == width && width == %d'
                               % logical_size(1024, 768)[0])
        page.wait_for_timeout(200)
        narrow = self.record_rects(page, '1024x768')
        self.assertLess(narrow['continue']['width'], self.rects['1280x720']['continue']['width'])
        self.save(page, 'offer-1024x768.png')
        page.set_viewport_size({'width': 800, 'height': 450})
        page.wait_for_function('continueOffer.width == width && width == %d'
                               % logical_size(800, 450)[0])
        page.wait_for_timeout(200)
        self.assertTrue(state(page)['offer'])
        self.record_rects(page, '800x450')
        self.save(page, 'offer-800x450.png')

        # Pause keys and blur do nothing while the offer is shown
        page.keyboard.press('Escape')
        page.evaluate('window.dispatchEvent(new Event("blur"))')
        self.assertFalse(state(page)['gamePaused'])

        # (c) Restart: score 0, overlay hidden
        self.click_button(page, 'restartButton')
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                         (False, 2, 0, False))
        self.assertEqual(show_ad_count(page), 0)
        print('  ASSERT (c) Restart -> score 0, overlay hidden: pass',
              file=sys.stderr)

        # (e) after a restart the run is eligible again
        self.kill(page, 6)
        self.assertTrue(state(page)['offer'])
        self.assertEqual(show_ad_count(page), 0)
        print('  ASSERT (e) eligible again after restart: pass', file=sys.stderr)

        # Continue: the ninja respawns at a safe point and resumes physics
        self.click_button(page, 'continueButton')
        # Continue is asynchronous since the rewarded ad (TASK-082)
        page.wait_for_function('!continueOffer.visible')
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                         (False, 2, 6, True))
        self.assertEqual(show_ad_count(page), 1)

        # (d) a second eligible death in the same run restarts instantly
        # (once the respawn invulnerability has run out)
        page.wait_for_function('!ninja.isInvulnerable()')
        self.kill(page, 7)
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score']), (False, 3, 0))
        self.assertEqual(show_ad_count(page), 1)
        print('  ASSERT (d) second eligible death after continue -> instant reStart: pass',
              file=sys.stderr)

    def test_touch_restart_844x390(self):
        page = self.boot({'width': 844, 'height': 390}, touch=True)
        self.kill(page, 5)
        self.assertTrue(state(page)['offer'])
        self.assertEqual(show_ad_count(page), 0)
        self.record_rects(page, '844x390')
        self.save(page, 'offer-844x390-touch.png')
        self.tap_button(page, 'restartButton')
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score']), (False, 1, 0))
        self.assertEqual(show_ad_count(page), 0)

        self.kill(page, 5)
        self.tap_button(page, 'continueButton')
        page.wait_for_function('!continueOffer.visible')
        s = state(page)
        self.assertEqual((s['offer'], s['continueUsed']), (False, True))
        self.assertEqual(show_ad_count(page), 1)
        print('  ASSERT touch tap Restart and Continue at 844x390: pass', file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
