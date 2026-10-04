"""Main-menu 'fps counter' checkbox at play-rect aspects 4:3 to 2:1 (TASK-137).

In en and ru, from the LAYOUT_PROBE boxes of menu.draw(): the fps label
is no taller than the record label (+1 px), the checkbox + label row is
centred on the buttons within 2% of the play-rect width, and the row lies
inside the play rect.

Env: MENU_FPS_EVIDENCE_DIR receives boxes.json and, with screens, the
menu PNGs (screens/<w>x<h>-<lang>.png).
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
import layout_matrix as lm

ROOT = Path(__file__).resolve().parent.parent
SIZES = [(925, 925, False), (1024, 768, False), (1280, 1024, False),
         (1920, 1080, False), (2560, 1080, False), (390, 844, True)]
HEIGHT_SLACK_PX = 1
CENTER_RATIO = 0.02


def measure(shot, lang):
    """Fps label, record label and button boxes of one menu probe."""
    boxes = lm.dedupe(shot['boxes'])
    fps_name = {'en': 'fps counter', 'ru': 'счётчик FPS'}[lang]
    label = next(b for b in boxes if b['kind'] == 'text' and b['name'] == fps_name)
    hit = next(b for b in boxes if b['kind'] == 'button' and b['name'] == fps_name)
    record = [b for b in boxes if b['kind'] == 'text' and b['name'] != fps_name and
              b['name'].split(':')[0] in ('record', 'рекорд')]
    version_names = {'en': ('chill version', 'main version'),
                     'ru': ('спокойный режим', 'основной режим')}[lang]
    buttons = [b for b in boxes if b['kind'] == 'button' and b['name'] in version_names]
    assert len(buttons) == 2, [b['name'] for b in boxes if b['kind'] == 'button']
    # Box (left of the label) to label end; the hit rect pads both sides equally
    group_left = hit['x']
    group_right = hit['x'] + hit['width']
    group_center = (group_left + group_right) / 2
    button_center = sum(b['x'] + b['width'] / 2 for b in buttons) / len(buttons)
    return {
        'fps_label': label, 'fps_hit': hit, 'record_labels': record, 'buttons': buttons,
        'fps_height': label['height'],
        'record_height': max(b['height'] for b in record),
        'group_center_x': group_center, 'buttons_center_x': button_center,
        'center_offset_ratio': abs(group_center - button_center) / shot['canvas']['width'],
        'canvas': shot['canvas'],
    }


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
            key = f'{w}x{h}-{lang}'
            with self.subTest(case=key):
                context, page, errors = lm.open_page(self.browser, self.url, (w, h), touch, lm.LANGS[lang])
                try:
                    self.assertEqual(page.evaluate('I18N.language'), lang)
                    page.wait_for_timeout(150)
                    if self.out:
                        screens = Path(self.out) / 'screens'
                        screens.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screens / f'{key}.png'))
                    shot = page.evaluate(lm.PROBE, 'menu.draw()')
                    self.assertEqual((errors['console'], errors['page']), ([], []))
                finally:
                    context.close()
                m = measure(shot, lang)
                self.results[key] = m
                c = m['canvas']
                field = {'x': 0, 'y': 0, 'width': c['width'], 'height': c['height']}
                print(f"  {key}: fps_h={m['fps_height']:.2f} record_h={m['record_height']:.2f} "
                      f"center_off={m['center_offset_ratio'] * 100:.2f}% play={c['width']:.0f}x{c['height']:.0f}",
                      file=sys.stderr)
                self.assertLessEqual(m['fps_height'], m['record_height'] + HEIGHT_SLACK_PX, key)
                self.assertLessEqual(m['center_offset_ratio'], CENTER_RATIO, key)
                self.assertTrue(lm.inside(m['fps_label'], field), key)
                self.assertTrue(lm.inside(m['fps_hit'], field), key)

    def test_en(self):
        self.check('en')

    def test_ru(self):
        self.check('ru')


if __name__ == '__main__':
    unittest.main()
