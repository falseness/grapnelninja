"""The death screen switches to the other mode and toggles the fps counter.

Restart, a switch to the other mode (labelled with that mode) and the shared
fps-counter checkbox. The switch sends one level_failed for the dead run, the
game over interstitial, then level_started in the other mode.

Uses the fake Playgama Bridge from test_playgama2_bridge with interstitials
supported. Requires Playwright Chromium. No remote requests.

MODE_SWITCH_EVIDENCE_DIR (default: artifacts/TASK-362) receives death-bad.png,
death-classic.png, death-phone.png, pause-classic.png and pause-bad.png.

The pause screen's switch (menu.backToMenu) abandons the live run: one
level_failed, no interstitial, then level_started in the other mode.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from test_playgama2_bridge import FAKE, SDK

ROOT = Path(__file__).resolve().parents[1]
# Interstitials are supported: a request is recorded, opens and closes
EXTRA = r"""
bridge.advertisement.isInterstitialSupported = true;
bridge.advertisement.showInterstitial = function(placement) {
    record('interstitial_request', placement);
    setTimeout(() => emitHost('interstitial', 'opened'), 50);
    setTimeout(() => emitHost('interstitial', 'closed'), 150);
};
"""
BOOT_DONE = "probe.calls.some(c => c.name === 'game_ready') && " \
    "probe.calls.some(c => c.name === 'level_started')"
# A real lethal hit inside ninja.move(): its next collision check is a
# lethal element's
KILL = '''() => {
    const n = ninja
    n.collision = function() { delete n.collision; Element.prototype.collision.call(n) }
}'''
# Canvas rect -> page coordinates of its centre
CENTER = '''rect => {
    const r = canvas.getBoundingClientRect()
    return {x: r.x + (rect.x + rect.width / 2) * r.width / width,
            y: r.y + (rect.y + rect.height / 2) * r.height / height}
}'''
RECTS = '''() => {
    const b = button => ({x: button.background.x, y: button.background.y,
        width: button.background.width, height: button.background.height})
    return {restart: b(continueOffer.restartButton), switch: b(continueOffer.switchButton),
        fps: continueOffer.fpsCounterCheckbox.hitRect(), touch: minTouchSize(), width, height}
}'''
PAUSE_BUTTON = '''(b => ({x: b.x * scale[version], y: b.y * scale[version],
    width: b.width * scale[version], height: b.height * scale[version]}))(menu.button.background)'''


def page_rect(expression):
    return f'(b => ({{x: b.x, y: b.y, width: b.width, height: b.height}}))({expression})'


class ModeSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MODE_SWITCH_EVIDENCE_DIR', ROOT / 'artifacts/TASK-362'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.lines = []

    # PASS lines are printed after the results, so unittest's
    # 'test_name ... ok' stays on one line
    @classmethod
    def tearDownClass(cls):
        print('\n'.join(cls.lines), flush=True)

    def log(self, *parts):
        self.lines.append(' '.join(str(p) for p in parts))

    def open(self, viewport, **options):
        context = self.browser.new_context(viewport=viewport, locale='en-US', **options)
        self.addCleanup(context.close)
        context.route(SDK, lambda route: route.fulfill(content_type='application/javascript', body=
            'const FAULT = "normal"; const SAVED_LANGUAGE = "en";\n' + FAKE + EXTRA))
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(BOOT_DONE)
        if page.evaluate("!document.getElementById('tutorial').hidden"):
            page.click('#tutorial button')
        return page

    def die(self, page):
        page.evaluate(KILL)
        page.wait_for_function('continueOffer.visible')
        page.wait_for_timeout(300)

    def click(self, page, rect):
        page.mouse.click(**page.evaluate(CENTER, rect))

    def check_layout(self, page, name):
        r = page.evaluate(RECTS)
        boxes = {k: r[k] for k in ('restart', 'switch', 'fps')}
        for key, box in boxes.items():
            self.assertGreaterEqual(box['height'], r['touch'] - 0.01, key)
            self.assertTrue(0 <= box['x'] and box['x'] + box['width'] <= r['width'] and
                            0 <= box['y'] and box['y'] + box['height'] <= r['height'], (key, box))
        keys = list(boxes)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                p, q = boxes[a], boxes[b]
                overlap = (p['x'] < q['x'] + q['width'] and q['x'] < p['x'] + p['width'] and
                           p['y'] < q['y'] + q['height'] and q['y'] < p['y'] + p['height'])
                self.assertFalse(overlap, (a, b, p, q))
        page.screenshot(path=str(self.out / name))
        self.log(f'PASS layout {name}: no overlap, touch >= {r["touch"]:.1f}:',
              json.dumps({k: [round(v) for v in b.values()] for k, b in boxes.items()}))

    def messages(self, page):
        return page.evaluate('''probe.calls.filter(c => c.name.startsWith('level_') ||
            c.name === 'interstitial_request').map(c => [c.name, c.data ?? null])''')

    def test_death_switch(self):
        page = self.open({'width': 1280, 'height': 720})
        self.assertEqual(page.evaluate('version'), 'bad')
        before = len(self.messages(page))
        self.die(page)
        self.assertEqual(page.evaluate('continueOffer.switchButton.text.text'), 'chill version')
        self.check_layout(page, 'death-bad.png')

        # The death-screen checkbox toggles the counter shared with the pause screen
        fps = page.evaluate('continueOffer.fpsCounterCheckbox.hitRect()')
        self.assertFalse(page.evaluate('fpsCounter.enabled'))
        self.click(page, fps)
        self.assertTrue(page.evaluate('fpsCounter.enabled'))
        self.click(page, fps)
        self.assertFalse(page.evaluate('fpsCounter.enabled'))
        page.evaluate('menu.pauseFpsCounterCheckbox.click()')
        self.assertTrue(page.evaluate('fpsCounter.enabled && continueOffer.visible'))
        self.click(page, fps)
        self.assertFalse(page.evaluate('fpsCounter.enabled'))
        self.log('PASS fps checkbox: death click on/off, pause checkbox state shared')

        self.click(page, page.evaluate('(b => ({x: b.x, y: b.y, width: b.width, height: b.height}))'
                                       '(continueOffer.switchButton.background)'))
        page.wait_for_function("version === 'classic' && !continueOffer.visible && !interstitialPending")
        page.wait_for_timeout(200)
        after = self.messages(page)[before:]
        self.assertEqual(after, [['level_failed', {'world': 'bad'}], ['interstitial_request', 'game_over'],
                                 ['level_started', {'world': 'classic'}]])
        self.assertFalse(page.evaluate('menu.visible || menu.gamePaused'))
        self.log('PASS switch bad -> classic:', json.dumps(after))

        self.die(page)
        self.assertEqual(page.evaluate('continueOffer.switchButton.text.text'), 'main version')
        self.check_layout(page, 'death-classic.png')
        self.log('PASS second death in classic: switch reads main version')

    def test_death_layout_phone(self):
        page = self.open({'width': 844, 'height': 390}, has_touch=True, is_mobile=True)
        self.die(page)
        self.assertEqual(page.evaluate('continueOffer.switchButton.text.text'), 'chill version')
        self.check_layout(page, 'death-phone.png')

    # A real click on the HUD menu button (drawn at scale[version])
    def pause(self, page):
        page.wait_for_function('!unTouch')
        self.click(page, page.evaluate(PAUSE_BUTTON))
        page.wait_for_function('menu.gamePaused')

    def pause_rect(self, name):
        return page_rect(f'menu.{name}.background')

    def test_pause_switch(self):
        page = self.open({'width': 1280, 'height': 720})
        page.evaluate("startGame('classic')")
        page.wait_for_timeout(300)
        before = len(self.messages(page))

        self.pause(page)
        self.assertEqual(page.evaluate('menu.backToMenu.text.text'), 'main version')
        page.screenshot(path=str(self.out / 'pause-classic.png'))
        self.click(page, page.evaluate(self.pause_rect('backToMenu')))
        page.wait_for_function("version === 'bad' && !menu.gamePaused")
        page.wait_for_timeout(300)
        after = self.messages(page)[before:]
        self.assertEqual(after, [['level_paused', None], ['level_failed', {'world': 'classic'}],
                                 ['level_started', {'world': 'bad'}]])
        self.assertFalse(page.evaluate("probe.calls.some(c => c.name === 'interstitial_request')"))
        self.assertFalse(page.evaluate('menu.visible || continueOffer.visible || interstitialPending'))
        self.log('PASS pause switch classic -> bad, no interstitial:', json.dumps(after))

        # Resume keeps the same run going
        before = len(self.messages(page))
        self.pause(page)
        self.assertEqual(page.evaluate('menu.backToMenu.text.text'), 'chill version')
        page.screenshot(path=str(self.out / 'pause-bad.png'))
        self.click(page, page.evaluate(self.pause_rect('resume')))
        page.wait_for_function('!menu.gamePaused')
        page.wait_for_timeout(200)
        after = self.messages(page)[before:]
        self.assertEqual(after, [['level_paused', None], ['level_resumed', None]])
        self.assertTrue(page.evaluate("version === 'bad' && runInProgress && !runOver"))
        self.log('PASS second pause + Resume resumes the bad run:', json.dumps(after))


if __name__ == '__main__':
    unittest.main()
