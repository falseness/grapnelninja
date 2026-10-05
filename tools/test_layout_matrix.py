"""Layout rules on the sizes that failed before TASK-127 (layout_matrix.py).

Menu, HUD, pause, continue offer and ad unavailable, in en and ru, at a
phone portrait, a phone landscape, a 21:9 desktop and a short desktop
window and a 2.6:1 phone landscape with browser bars: play field <= 2:1 on
desktop and the whole window on touch, no scrollbar, text and buttons inside
the canvas and apart, text >= 12 CSS px, buttons >= 44 CSS px on touch.

Env: LAYOUT_EVIDENCE_DIR receives layout-matrix.json.
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
SIZES = [(360, 640, True), (844, 390, True), (892, 340, True), (2560, 1080, False), (1280, 500, False)]


class LayoutMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.rows = []
        cls.addClassCleanup(cls.save)

    @classmethod
    def save(cls):
        out = os.environ.get('LAYOUT_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / 'layout-matrix.json').write_text(
                json.dumps(cls.rows, indent=1, ensure_ascii=False))

    def check(self, lang):
        for w, h, touch in SIZES:
            rows = lm.walk(self.browser, self.url, lang, (w, h), touch)
            self.rows.extend(rows)
            for r in rows:
                with self.subTest(size=r['size'], screen=r['screen']):
                    print(f"  {lang} {r['size']} {r['screen']}: aspect={r['aspect']} "
                          f"font={r['min_font_px']} button={r['min_button_px']} "
                          f"{'pass' if r['pass'] else r['failures']}", file=sys.stderr)
                    self.assertEqual(r['failures'], [], {k: r[k] for k in
                                     ('overlaps', 'clipped', 'aspect', 'min_font_px', 'min_button_px')})

    def test_en(self):
        self.check('en')

    def test_ru(self):
        self.check('ru')


if __name__ == '__main__':
    unittest.main()
