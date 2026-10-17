"""Momentum hp / green-streak HUD (sprites/scoretext.js drawMomentumHud).

Starts a run, cancels its rAF loop and calls draw() with LAYOUT_PROBE.boxes on
(menu.js), so the score, record and menu button boxes and the momentum boxes
('momentum-hearts' rect named 'hp:N', the '×N' and 'n/5' texts) come out in
canvas CSS px. Checks at 1280x720 and an upright 390x844 phone (touch, the
stage turned to landscape) that the momentum boxes stay inside the canvas and
never intersect the score, record or menu button, with 5-digit score and
record and the widest hp forms (10 hearts, '×123'). Checks the HUD state
after onGreenTouch/onBlueTouch calls, and that bad draws no momentum boxes.

PNGs are the canvas (toDataURL, so the phone one is the landscape stage)
written to MOMENTUM_HUD_EVIDENCE_DIR (default artifacts/TASK-011) with
hud-boxes.json (compact).

Requires Playwright Chromium. No remote requests.
"""
import base64
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_HUD_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-011'))
DESKTOP = ({'width': 1280, 'height': 720}, False)
PHONE = ({'width': 390, 'height': 844}, True)
MOMENTUM_KINDS = ('momentum-hearts',)
BOXES = {}

DRAW = '''() => {
    LAYOUT_PROBE.boxes = []
    draw()
    const boxes = LAYOUT_PROBE.boxes
    LAYOUT_PROBE.boxes = null
    const r = getCanvasCssRect()
    return {boxes: boxes, canvas: {width: r.width, height: r.height},
            state: version == 'momentum' ? scoreText.getMomentumHudState() : null}
}'''


def intersects(a, b):
    return (a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] and
            a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height'])


class MomentumHudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / 'hud-boxes.json').write_text(
            json.dumps(BOXES, separators=(',', ':'), sort_keys=True) + '\n')

    def open(self, viewport=DESKTOP, mode='momentum'):
        size, touch = viewport
        context = self.browser.new_context(viewport=size, is_mobile=touch, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.evaluate(f"() => {{ startGame('{mode}'); cancelAnimationFrame(game) }}")
        return page

    def touch(self, page, sequence):
        calls = {'G': 'onGreenTouch()', 'B': 'onBlueTouch()'}
        for key in sequence:
            page.evaluate(f'momentumState.{calls[key]}')

    def probe(self, page):
        return page.evaluate(DRAW)

    def split(self, result):
        boxes = result['boxes']
        hud = [b for b in boxes if b['kind'] in MOMENTUM_KINDS or
               (b['kind'] == 'text' and (b['name'].endswith('/5') or b['name'].startswith('×')))]
        others = [b for b in boxes if b not in hud]
        return hud, others

    def save_png(self, page, name):
        url = page.evaluate('canvas.toDataURL("image/png")')
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / name).write_bytes(base64.b64decode(url.split(',', 1)[1]))

    def check_layout(self, label, viewport):
        page = self.open(viewport)
        page.evaluate("() => { scoreText.count.momentum = 99999; scoreText.record.momentum = 99999 }")
        for hp, streak in ((5, 0), (10, 4), (123, 4)):
            with self.subTest(viewport=label, hp=hp):
                page.evaluate(f'() => {{ momentumState.hp = {hp}; momentumState.greenStreak = {streak} }}')
                result = self.probe(page)
                hud, others = self.split(result)
                names = sorted(b['name'] for b in others)
                print(label, 'hp', hp, 'hud', [(b['name'], round(b['x'], 1), round(b['x'] + b['width'], 1)) for b in hud],
                      'others', [(b['name'], round(b['x'], 1), round(b['x'] + b['width'], 1)) for b in others])
                BOXES[f'{label}-hp{hp}'] = {'hud': hud, 'others': others, 'canvas': result['canvas']}
                self.assertEqual(names, ['RECORD: 99999', 'SCORE: 99999', 'icon'])
                self.assertIn('hp:%d' % hp, [b['name'] for b in hud])
                self.assertIn('%d/5' % streak, [b['name'] for b in hud])
                if hp > 10:
                    self.assertIn('×%d' % hp, [b['name'] for b in hud])
                canvas = result['canvas']
                for box in hud:
                    self.assertGreaterEqual(box['x'], 0)
                    self.assertGreaterEqual(box['y'], 0)
                    self.assertLessEqual(box['x'] + box['width'], canvas['width'])
                    self.assertLessEqual(box['y'] + box['height'], canvas['height'])
                    for other in others:
                        self.assertFalse(intersects(box, other), (box, other))
                print(label, 'hp', hp, 'no overlap with score/record/menu button: OK')
        return page

    def test_layout_desktop(self):
        self.check_layout('desktop-1280x720', DESKTOP)

    def test_layout_phone(self):
        page = self.check_layout('phone-390x844', PHONE)
        page.evaluate('() => { scoreText.count.momentum = 0; scoreText.record.momentum = 0; '
                      'momentumState.reset(); momentumState.onGreenTouch(); momentumState.onGreenTouch() }')
        self.probe(page)
        self.save_png(page, 'hud-phone.png')

    def test_state_follows_touches(self):
        page = self.open()
        start = self.probe(page)['state']
        print('start', start)
        self.assertEqual(start, {'hp': 5, 'hearts': 5, 'hpText': '', 'streakText': '0/5'})
        self.save_png(page, 'hud-hp5.png')

        self.touch(page, 'G' * 13)
        result = self.probe(page)
        hud, _ = self.split(result)
        print('G x13', result['state'], [b['name'] for b in hud])
        self.assertEqual(result['state'], {'hp': 7, 'hearts': 7, 'hpText': '', 'streakText': '3/5'})
        self.assertEqual(sorted(b['name'] for b in hud), ['3/5', 'hp:7'])
        self.save_png(page, 'hud-hp7-streak3.png')

        self.touch(page, 'B')
        result = self.probe(page)
        hud, _ = self.split(result)
        print('G x13 B', result['state'], [b['name'] for b in hud])
        self.assertEqual(result['state'], {'hp': 6, 'hearts': 6, 'hpText': '', 'streakText': '0/5'})
        self.assertEqual(sorted(b['name'] for b in hud), ['0/5', 'hp:6'])

        # 6 + 6 * 5 greens = hp 12: the number form
        self.touch(page, 'G' * 32)
        result = self.probe(page)
        hud, _ = self.split(result)
        print('G x13 B G x32', result['state'], [b['name'] for b in hud])
        self.assertEqual(result['state'], {'hp': 12, 'hearts': 1, 'hpText': '×12', 'streakText': '2/5'})
        self.assertEqual(sorted(b['name'] for b in hud), ['2/5', 'hp:12', '×12'])
        heart = next(b for b in hud if b['kind'] == 'momentum-hearts')
        self.assertLess(heart['width'], heart['height'] * 1.01)
        self.save_png(page, 'hud-hp12.png')

    def test_bad_has_no_momentum_hud(self):
        for label, viewport in (('desktop', DESKTOP), ('phone', PHONE)):
            page = self.open(viewport, 'bad')
            result = self.probe(page)
            hud, others = self.split(result)
            names = sorted(b['name'] for b in result['boxes'])
            print('bad', label, names)
            self.assertEqual(hud, [])
            self.assertEqual(names, ['RECORD: 0', 'SCORE: 0', 'icon'])
            BOXES['bad-' + label] = others
            if label == 'desktop':
                self.save_png(page, 'bad-hud.png')


if __name__ == '__main__':
    unittest.main()
