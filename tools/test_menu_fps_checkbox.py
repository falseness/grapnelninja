"""'fps counter' checkbox at play-rect aspects 4:3 to 2:1 (TASK-137, TASK-388).

The title menu and its checkbox are gone; the checkbox now lives on the
pause screen and on the death screen (continue offer). In en and ru, from
the LAYOUT_PROBE boxes of menu.drawPauseScreen() and continueOffer.draw():
the fps label font is no larger than the screen's button label fonts
(+1 px; font size, as the ink height differs with descenders: 'fps' vs
'resume'), the
label fits inside the checkbox hit area, the checkbox + label row is
centred on the screen's two buttons within 2% of the play-rect width, and
the row lies inside the play rect.

Env: MENU_FPS_EVIDENCE_DIR receives boxes.json and, with screens, the
PNGs (screens/<w>x<h>-<lang>-<screen>.png).
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from game_harness import switch_mode
import layout_matrix as lm

ROOT = Path(__file__).resolve().parent.parent
SIZES = [(925, 925, False), (1024, 768, False), (1280, 1024, False),
         (1920, 1080, False), (2560, 1080, False), (390, 844, True)]
FONT_SLACK_PX = 1
CENTER_RATIO = 0.02
# Probe call and the names of its two buttons per screen
SCREENS = {
    'pause': ('menu.drawPauseScreen()', '[menu.resume.text.text, menu.modeButtons[1].text.text]'),
    'death': ('continueOffer.draw()',
              '[continueOffer.restartButton.text.text, continueOffer.switchButton.text.text]'),
}


def measure(shot, lang, button_names):
    """Fps label, its hit area and the two button boxes of one probe."""
    boxes = lm.dedupe(shot['boxes'])
    fps_name = {'en': 'fps counter', 'ru': 'счётчик FPS'}[lang]
    label = next(b for b in boxes if b['kind'] == 'text' and b['name'] == fps_name)
    hit = next(b for b in boxes if b['kind'] == 'button' and b['name'] == fps_name)
    buttons = [b for b in boxes if b['kind'] == 'button' and b['name'] in button_names]
    assert len(buttons) == 2, [b['name'] for b in boxes if b['kind'] == 'button']
    button_labels = [b for b in boxes if b['kind'] == 'text' and b['name'] in button_names]
    assert len(button_labels) == 2, [b['name'] for b in boxes if b['kind'] == 'text']
    # Box (left of the label) to label end; the hit rect pads both sides equally
    group_left = hit['x']
    group_right = hit['x'] + hit['width']
    group_center = (group_left + group_right) / 2
    button_center = sum(b['x'] + b['width'] / 2 for b in buttons) / len(buttons)
    return {
        'fps_label': label, 'fps_hit': hit, 'button_labels': button_labels, 'buttons': buttons,
        'fps_font_px': label['fontPx'],
        'button_label_font_px': max(b['fontPx'] for b in button_labels),
        'group_center_x': group_center, 'buttons_center_x': button_center,
        'center_offset_ratio': abs(group_center - button_center) / shot['canvas']['width'],
        'canvas': shot['canvas'],
    }


def die(page):
    """A real lethal death that leaves the death screen up.

    The local PLATFORM (no Bridge since c232782) never has a game over ad
    due, so it is made due just before the kill (INSTRUMENT_RUN).
    """
    page.evaluate('() => { PLATFORM.isInterstitialDue = () => true; window.__kill = true }')
    page.wait_for_function('continueOffer.visible && !window.__kill && !menu.gamePaused')


class MenuFpsCheckboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.out = os.environ.get('MENU_FPS_EVIDENCE_DIR')
        cls.results = {}
        cls.addClassCleanup(cls.save)

    @classmethod
    def save(cls):
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            (Path(cls.out) / 'boxes.json').write_text(
                json.dumps(cls.results, indent=1, ensure_ascii=False))

    def check(self, lang):
        for w, h, touch in SIZES:
            size = f'{w}x{h}-{lang}'
            with self.subTest(case=size):
                context, page, errors = lm.open_page(self.browser, self.url, (w, h), touch, lm.LANGS[lang])
                shots = {}
                try:
                    self.assertEqual(page.evaluate('I18N.language'), lang)
                    switch_mode(page, 'classic')
                    page.evaluate(lm.INSTRUMENT_RUN)
                    page.wait_for_timeout(150)
                    page.evaluate('menu.startPause()')
                    shots['pause'] = self.probe(page, f'{size}-pause', 'pause')
                    page.evaluate('menu.resume.click()')
                    page.wait_for_function('!menu.gamePaused')
                    die(page)
                    page.wait_for_timeout(150)
                    shots['death'] = self.probe(page, f'{size}-death', 'death')
                    self.assertEqual((errors['console'], errors['page']), ([], []))
                finally:
                    context.close()
                for screen, (shot, names) in shots.items():
                    key = f'{size}-{screen}'
                    m = measure(shot, lang, names)
                    self.results[key] = m
                    c = m['canvas']
                    field = {'x': 0, 'y': 0, 'width': c['width'], 'height': c['height']}
                    print(f"  {key}: fps_font={m['fps_font_px']:.2f} button_font={m['button_label_font_px']:.2f} "
                          f"center_off={m['center_offset_ratio'] * 100:.2f}% play={c['width']:.0f}x{c['height']:.0f}",
                          file=sys.stderr)
                    self.assertLessEqual(m['fps_font_px'], m['button_label_font_px'] + FONT_SLACK_PX, key)
                    self.assertTrue(lm.inside(m['fps_label'], m['fps_hit']), key)
                    self.assertLessEqual(m['center_offset_ratio'], CENTER_RATIO, key)
                    self.assertTrue(lm.inside(m['fps_label'], field), key)
                    self.assertTrue(lm.inside(m['fps_hit'], field), key)

    def probe(self, page, key, screen):
        draw, names = SCREENS[screen]
        if self.out:
            screens = Path(self.out) / 'screens'
            screens.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screens / f'{key}.png'))
        return page.evaluate(lm.PROBE, draw), page.evaluate(names)

    def test_en(self):
        self.check('en')

    def test_ru(self):
        self.check('ru')


if __name__ == '__main__':
    unittest.main()
