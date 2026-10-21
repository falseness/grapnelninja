"""Mode switches and the death path with the local platform adapter.

With no ads (PLATFORM.isInterstitialDue() is always false) every death
fast-restarts the same mode: no death screen, no interstitial. The pause
screen's mode selector (menu.modeButtons: Grapple Over, main/bad, chill/classic;
TASK-445 replaced the two-mode backToMenu toggle) abandons the live run: one
level_failed, no interstitial, then level_started in the selected mode. Boot
starts Grapple Over, so the classic/bad cases select their mode explicitly. Lifecycle events are
read from a spy on PLATFORM.sendLifecycle.

Requires Playwright Chromium. No remote requests.

MODE_SWITCH_EVIDENCE_DIR (default: artifacts/TASK-363) receives
pause-classic.png, pause-bad.png and pause-ru.png.

The language button sits on the pause screen and relabels it in place.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test

ROOT = Path(__file__).resolve().parents[1]
BOOT_DONE = 'bootComplete && runInProgress'
# Records PLATFORM lifecycle events and interstitial requests
SPY = '''() => {
    window.lifecycle = []
    const send = PLATFORM.sendLifecycle, show = PLATFORM.showInterstitial
    PLATFORM.sendLifecycle = (name, data) => { lifecycle.push([name, data ?? null]); return send(name, data) }
    PLATFORM.showInterstitial = placement => { lifecycle.push(['interstitial_request', placement]); return show(placement) }
}'''
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
LANGUAGE = '(r => ({x: r.x, y: r.y, width: r.width, height: r.height}))(LANGUAGE_BUTTON.rect())'
MODE_BUTTON = {'grapple_over': 0, 'bad': 1, 'classic': 2}
PAUSE_BUTTON = '''(b => ({x: b.x * scale[version], y: b.y * scale[version],
    width: b.width * scale[version], height: b.height * scale[version]}))(menu.button.background)'''


def page_rect(expression):
    return f'(b => ({{x: b.x, y: b.y, width: b.width, height: b.height}}))({expression})'


class ModeSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MODE_SWITCH_EVIDENCE_DIR', ROOT / 'artifacts/TASK-363'))
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
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(BOOT_DONE)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'local')
        page.evaluate(SPY)
        return page

    # No ad is ever due: no death screen, the same mode restarts at once
    def die_fast_restart(self, page):
        page.wait_for_function('!ninja.isInvulnerable()')
        before = len(self.messages(page))
        page.evaluate(KILL)
        page.wait_for_function('n => lifecycle.length >= n', arg=before + 2)
        page.wait_for_timeout(300)
        return self.messages(page)[before:]

    def click(self, page, rect):
        page.mouse.click(**page.evaluate(CENTER, rect))

    def assert_apart(self, boxes):
        keys = list(boxes)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                p, q = boxes[a], boxes[b]
                overlap = (p['x'] < q['x'] + q['width'] and q['x'] < p['x'] + p['width'] and
                           p['y'] < q['y'] + q['height'] and q['y'] < p['y'] + p['height'])
                self.assertFalse(overlap, (a, b, p, q))

    def messages(self, page):
        return page.evaluate('lifecycle.slice()')

    def start(self, page, mode):
        page.evaluate('mode => startGame(mode)', mode)
        page.wait_for_function('mode => version === mode && runInProgress', arg=mode)
        page.wait_for_timeout(300)

    def test_death_fast_restart(self):
        page = self.open({'width': 1280, 'height': 720})
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        self.start(page, 'bad')
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        fast = self.die_fast_restart(page)
        self.assertEqual(fast, [['level_failed', {'world': 'bad'}], ['level_started', {'world': 'bad'}]])
        self.assertEqual(page.evaluate('[version, continueOffer.visible, interstitialPending, runOver, runInProgress]'),
                         ['bad', False, False, False, True])
        self.log('PASS bad death fast-restarts bad, no death screen:', json.dumps(fast))

        page.evaluate("startGame('classic')")
        page.wait_for_timeout(300)
        fast = self.die_fast_restart(page)
        self.assertEqual(fast, [['level_failed', {'world': 'classic'}], ['level_started', {'world': 'classic'}]])
        self.assertEqual(page.evaluate('[version, continueOffer.visible, interstitialPending, runOver, runInProgress]'),
                         ['classic', False, False, False, True])
        self.log('PASS classic death fast-restarts classic, no death screen:', json.dumps(fast))

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
        self.assertEqual(page.evaluate('menu.modeButtons.map(b => b.text.text)'),
                         ['Grapple Over', 'main version', 'chill version'])
        page.screenshot(path=str(self.out / 'pause-classic.png'))
        self.click(page, page.evaluate(self.pause_rect(f'modeButtons[{MODE_BUTTON["bad"]}]')))
        page.wait_for_function("version === 'bad' && !menu.gamePaused")
        page.wait_for_timeout(300)
        after = self.messages(page)[before:]
        self.assertEqual(after, [['level_paused', None], ['level_failed', {'world': 'classic'}],
                                 ['level_started', {'world': 'bad'}]])
        self.assertFalse(page.evaluate('continueOffer.visible || interstitialPending'))
        self.log('PASS pause switch classic -> bad, no interstitial:', json.dumps(after))

        # Resume keeps the same run going
        before = len(self.messages(page))
        self.pause(page)
        self.assertEqual(page.evaluate(f'menu.modeButtons[{MODE_BUTTON["classic"]}].text.text'), 'chill version')
        page.screenshot(path=str(self.out / 'pause-bad.png'))
        self.click(page, page.evaluate(self.pause_rect('resume')))
        page.wait_for_function('!menu.gamePaused')
        page.wait_for_timeout(200)
        after = self.messages(page)[before:]
        self.assertEqual(after, [['level_paused', None], ['level_resumed', None]])
        self.assertTrue(page.evaluate("version === 'bad' && runInProgress && !runOver"))
        self.log('PASS second pause + Resume resumes the bad run:', json.dumps(after))

    def test_language_on_pause(self):
        page = self.open({'width': 1280, 'height': 720})
        self.assertEqual(page.evaluate('[version, I18N.language]'), ['grapple_over', 'en'])
        self.start(page, 'bad')
        chill_ru = '\u0441\u043f\u043e\u043a\u043e\u0439\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c'

        # Pause: a real click on the language button relabels the screen in place
        self.pause(page)
        self.assertEqual(page.evaluate('menu.modeButtons[2].text.text'), 'chill version')
        page.wait_for_function('!unTouch')
        self.click(page, page.evaluate(LANGUAGE))
        self.assertEqual(page.evaluate('I18N.language'), 'ru')
        labels = page.evaluate('[menu.modeButtons[2].text.text, menu.resume.text.text]')
        self.assertEqual(labels, [chill_ru, '\u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c'])
        self.assertTrue(page.evaluate('menu.gamePaused'))
        boxes = {k: page.evaluate(self.pause_rect(k)) for k in
                 ('resume', 'modeButtons[0]', 'modeButtons[1]', 'modeButtons[2]')}
        boxes['fps'] = page.evaluate('menu.pauseFpsCounterCheckbox.hitRect()')
        boxes['language'] = page.evaluate(LANGUAGE)
        self.assert_apart(boxes)
        self.assert_apart({'panel': page.evaluate('menu.getPausePanel()'), 'language': boxes['language']})
        page.screenshot(path=str(self.out / 'pause-ru.png'))
        self.log('PASS pause language en -> ru, no overlap with panel/controls:', json.dumps(labels, ensure_ascii=False))

        # A second click switches back
        page.wait_for_function('!unTouch')
        self.click(page, page.evaluate(LANGUAGE))
        self.assertEqual(page.evaluate('I18N.language'), 'en')
        labels = page.evaluate('[menu.modeButtons[2].text.text, menu.resume.text.text]')
        self.assertEqual(labels, ['chill version', page.evaluate("I18N.t('pause.resume')")])
        self.log('PASS pause language ru -> en:', json.dumps(labels))


if __name__ == '__main__':
    unittest.main()
