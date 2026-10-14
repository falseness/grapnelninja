"""The pause screen shows the play time (menu.timeInGame, TASK-407).

TASK-364 removed the title menu, the only screen that drew the time in game.
The pause screen now draws it: in en and ru, at desktop and phone sizes, a
fillText spy must see I18N.t('menu.timeInGame', ...) and its LAYOUT_PROBE box
must pass layout_matrix's checks (no overlap with the title, buttons, fps
checkbox or language button, inside the canvas, >= 12 CSS px).

Env: PAUSE_TIME_SHOTS receives pause-<lang>.png (1920x1080) captures.
"""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
import layout_matrix as lm

ROOT = Path(__file__).resolve().parent.parent
SIZES = [(1920, 1080, False), (1280, 500, False), (844, 390, True), (892, 340, True), (390, 844, True)]
MINUTES = 37

PAUSE = '''minutes => {
    PROGRESS.setTime(minutes * 60)
    const texts = []
    const original = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function(text, ...rest) {
        texts.push(String(text))
        return original.call(this, text, ...rest)
    }
    try { menu.startPause() }
    finally { CanvasRenderingContext2D.prototype.fillText = original }
    return {texts, expected: I18N.t('menu.timeInGame', {minutes: getTimeInGame()})}
}'''


class PauseTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def check(self, lang, size, touch):
        context, page, errors = lm.open_page(self.browser, self.url, size, touch, lm.LANGS[lang])
        try:
            self.assertEqual(page.evaluate('I18N.language'), lang)
            drawn = page.evaluate(PAUSE, MINUTES)
            expected = drawn['expected']
            self.assertIn(str(MINUTES), expected)
            self.assertIn(expected, drawn['texts'])
            shot = page.evaluate(lm.PROBE, lm.DRAW['pause'])
            row, boxes = lm.evaluate(shot, touch)
            time_boxes = [b for b in boxes if b['kind'] == 'text' and b['name'] == expected]
            self.assertEqual(len(time_boxes), 1, boxes)
            print(lang, size, 'time box', {k: round(v, 1) for k, v in time_boxes[0].items()
                                           if isinstance(v, float)}, 'failures', row['failures'])
            self.assertEqual(row['overlaps'], [])
            self.assertEqual(row['clipped'], [])
            self.assertEqual(row['failures'], [])
            self.assertGreaterEqual(time_boxes[0]['fontPx'], lm.MIN_FONT_PX)
            out = os.environ.get('PAUSE_TIME_SHOTS')
            if out and size == (1920, 1080):
                Path(out).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(out) / f'pause-{lang}.png'))
            self.assertEqual((errors['console'], errors['page']), ([], []))
        finally:
            context.close()

    def test_en(self):
        for w, h, touch in SIZES:
            with self.subTest(size=(w, h)):
                self.check('en', (w, h), touch)

    def test_ru(self):
        for w, h, touch in SIZES:
            with self.subTest(size=(w, h)):
                self.check('ru', (w, h), touch)


if __name__ == '__main__':
    unittest.main()
