"""Mode-switch labels in en and ru, and trusted input -> runtime mode proof.

The title menu and its version buttons are gone (TASK-364): the mode labels
live on the pause switch (menu.backToMenu) and on the death screen's
continueOffer.switchButton, each labelled with the mode it leads to. A 'bad'
run reads menu.chillVersion, a 'classic' run menu.mainVersion; a real click
starts the other mode with exactly one level_started for it.

Uses the fake Playgama Bridge (test_playgama2_bridge) with interstitials
supported and a frozen interstitial clock, so a game over ad is due and the
death screen opens. Requires Playwright Chromium. No remote requests.

MODE_LABELS_EVIDENCE_DIR selects the output directory (default artifacts/TASK-392).
"""
import json
import os
import unittest

from browser_test_support import start_browser_test
from playgama_render_compare import PROTOCOL
from test_mode_switch import BOOT_DONE, CENTER, EXTRA, KILL, PAUSE_BUTTON, ROOT, page_rect
from test_playgama2_bridge import FAKE, SDK

LABELS = {'en': {'classic': 'chill version', 'bad': 'main version'},
          'ru': {'classic': 'спокойный режим', 'bad': 'основной режим'}}
OTHER = {'bad': 'classic', 'classic': 'bad'}


class ModeLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self, language):
        context = self.browser.new_context(viewport={'width': 844, 'height': 390}, locale=language)
        self.addCleanup(context.close)
        context.route(SDK, lambda r: r.fulfill(content_type='application/javascript', body=
            f'const FAULT = "normal"; const SAVED_LANGUAGE = {json.dumps(language)};\n' + FAKE + EXTRA))
        context.add_init_script("""
            window.labelInputs = [];
            document.addEventListener('mousedown', e => labelInputs.push({
                type:e.type, trusted:e.isTrusted, x:e.clientX, y:e.clientY}), true);
        """)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url + 'index.html')
        page.wait_for_function(BOOT_DONE)
        page.wait_for_function('lang => I18N.language === lang', arg=language)
        # Frozen interstitial clock (TASK-370): no request yet, so an ad is due
        page.evaluate('window.fakeNow = 1000000; PLATFORM.now = () => window.fakeNow')
        return page, errors

    def click(self, page, expression):
        page.wait_for_function('!unTouch')
        page.mouse.click(**page.evaluate(CENTER, page.evaluate(page_rect(expression))))

    def messages(self, page):
        return page.evaluate('''probe.calls.filter(c => c.name.startsWith('level_') ||
            c.name === 'interstitial_request').map(c => [c.name, c.data ?? null])''')

    # Shows the pause or death screen of the running mode; returns the switch
    def reach(self, page, screen):
        if screen == 'pause':
            page.wait_for_function('!unTouch')
            page.mouse.click(**page.evaluate(CENTER, page.evaluate(PAUSE_BUTTON)))
            page.wait_for_function('menu.gamePaused')
            return 'menu.backToMenu'
        self.assertTrue(page.evaluate('PLATFORM.isInterstitialDue()'))
        page.evaluate(KILL)
        page.wait_for_function('continueOffer.visible && !continueOffer.adPending')
        return 'continueOffer.switchButton'

    def test_switch_labels_and_handlers(self):
        observations = []
        for language, labels in LABELS.items():
            with self.subTest(language=language):
                page, errors = self.open(language)
                records = page.evaluate('scoreText.record')
                self.assertEqual(records, {'classic': 12, 'bad': 7})
                clicks = 0
                # Boot runs 'bad' (TASK-360): pause bad->classic, pause
                # classic->bad, death bad->classic, death classic->bad
                for screen in ('pause', 'pause', 'death', 'death'):
                    mode = page.evaluate('version')
                    target = OTHER[mode]
                    if screen == 'death' and mode == 'classic':
                        page.evaluate('window.fakeNow += PLATFORM.interstitialMinGapMs')
                    before = len(self.messages(page))
                    switch = self.reach(page, screen)
                    clicks += screen == 'pause'
                    label = page.evaluate(f'{switch}.text.text')
                    key = 'menu.chillVersion' if mode == 'bad' else 'menu.mainVersion'
                    self.assertEqual(label, labels[target])
                    self.assertEqual(label, page.evaluate('key => I18N.t(key)', key))
                    if language == 'en':
                        self.assertEqual(label, PROTOCOL['mode_labels'][target].lower() + ' version')
                    self.click(page, f'{switch}.background')
                    clicks += 1
                    page.wait_for_function('''want => version === want && !!ninja && !menu.gamePaused &&
                        !continueOffer.visible && !interstitialPending''', arg=target)
                    page.wait_for_timeout(300)
                    after = self.messages(page)[before:]
                    expected = ([['level_paused', None], ['level_failed', {'world': mode}],
                                 ['level_started', {'world': target}]] if screen == 'pause' else
                                [['level_failed', {'world': mode}], ['interstitial_request', 'game_over'],
                                 ['level_started', {'world': target}]])
                    self.assertEqual(after, expected)
                    self.assertEqual(page.evaluate('version'), target)
                    verdict = f'PASS {language} {screen} {mode}: {key}={label!r} -> {target}'
                    observation = dict(verdict=verdict, language=language, screen=screen, mode=mode,
                                       switch=switch, label=label, messages=after)
                    observations.append(observation)
                    print(verdict + '; ' + json.dumps(after, ensure_ascii=False), flush=True)
                inputs = page.evaluate('labelInputs')
                self.assertEqual(len(inputs), clicks)
                self.assertTrue(all(i['trusted'] for i in inputs))
                self.assertEqual(page.evaluate('scoreText.record'), records)
                self.assertEqual(errors, [])
                print(f'PASS {language}: {clicks} trusted clicks, records unchanged, no page errors', flush=True)
        out = os.environ.get('MODE_LABELS_EVIDENCE_DIR', ROOT / 'artifacts/TASK-392')
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, 'mode-labels.json'), 'w') as f:
            json.dump(observations, f, indent=2, ensure_ascii=False)
            f.write('\n')


if __name__ == '__main__':
    unittest.main()
