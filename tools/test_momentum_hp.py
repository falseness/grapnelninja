"""Momentum hp and green streak (elements/momentumstate.js).

Calls momentumState.onGreenTouch/onBlueTouch/onBorderTouch directly on a
momentum run whose rAF loop is cancelled, so the ninja cannot die or restart
in between. Hp starts at 5; 5 greens in a row give +1 hp and reset the streak;
a blue costs 1 hp and resets the streak; a border bounce changes nothing. Hp 0
is a game over through onLethalDeath (continue offer when an interstitial is
due, else the fast restart) and saves record.momentum.

Writes hp-cases.json ([{case, hp, streak, gameOver}], compact) to
MOMENTUM_HP_EVIDENCE_DIR (default artifacts/TASK-008).

Requires Playwright Chromium. No remote requests.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_HP_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-008'))
RECORDS_KEY = 'grapnelninja.records'
TOUCH = {'G': 'onGreenTouch()', 'B': 'onBlueTouch()', 'W': 'onBorderTouch()'}
CASES = []


def state(page):
    return page.evaluate('''() => ({hp: momentumState.hp, streak: momentumState.greenStreak,
        borderTouches: momentumState.borderTouches, version, runInProgress, runOver,
        offer: continueOffer.visible, deaths: window.__deaths || 0})''')


class MomentumHpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / 'hp-cases.json').write_text(
            json.dumps(sorted(CASES, key=lambda c: c['case']), separators=(',', ':')) + '\n')

    def open(self, interstitial_due=False):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.evaluate(f'''() => {{
            PLATFORM.isInterstitialDue = () => {'true' if interstitial_due else 'false'}
            const realDeath = onLethalDeath
            window.__deaths = 0
            onLethalDeath = function() {{ ++window.__deaths; return realDeath() }}
            startGame('momentum')
            cancelAnimationFrame(game)
        }}''')
        return page

    def touch(self, page, sequence):
        for key in sequence:
            page.evaluate(f'momentumState.{TOUCH[key]}')

    def record_case(self, name, s, game_over):
        print(name, s)
        CASES.append({'case': name, 'hp': s['hp'], 'streak': s['streak'], 'gameOver': game_over})

    def check(self, name, sequence, hp, streak):
        page = self.open()
        self.touch(page, sequence)
        s = state(page)
        self.record_case(name, s, s['deaths'] > 0)
        self.assertEqual(s['version'], 'momentum')
        self.assertEqual((s['hp'], s['streak'], s['deaths']), (hp, streak, 0))
        return s

    def test_initial(self):
        self.check('initial', '', 5, 0)

    def test_green_x5(self):
        self.check('G5', 'G' * 5, 6, 0)

    def test_green_x10(self):
        self.check('G10', 'G' * 10, 7, 0)

    def test_green_x4_blue(self):
        self.check('G4B', 'GGGGB', 4, 0)

    def test_border_keeps_streak(self):
        s = self.check('G3W2G2', 'GGGWWGG', 6, 0)
        self.assertEqual(s['borderTouches'], 2)

    def test_border_bounce_calls_on_border_touch(self):
        page = self.open()
        result = page.evaluate('''() => {
            const border = floors[0].elements.find(e => e instanceof MomentumBorder)
            const line = border.getLines()[0]
            ninja.speedX = 0; ninja.speedY = 0
            const before = momentumState.borderTouches
            ninja.applyBounce({x: line.x1, y: line.y1, nx: 0, ny: -1, approaching: true,
                element: border, line: line})
            return {before, after: momentumState.borderTouches, hp: momentumState.hp,
                streak: momentumState.greenStreak}
        }''')
        print('applyBounce on a MomentumBorder:', result)
        self.assertEqual(result, {'before': 0, 'after': 1, 'hp': 5, 'streak': 0})

    def check_game_over_saves_record(self, page):
        # Nothing calls PROGRESS.save() on a record change itself, so 17 in
        # storage afterwards is the game over's save
        page.evaluate('scoreText.count.momentum = 17; scoreText.record.momentum = 17')
        self.touch(page, 'BBBB')
        before = state(page)
        self.assertEqual((before['hp'], before['deaths']), (1, 0))
        page.wait_for_timeout(1200)
        unsaved = page.evaluate(f'JSON.parse(localStorage.getItem({RECORDS_KEY!r}) || "{{}}").momentum')
        print('stored record.momentum before the last blue:', unsaved)
        self.assertNotEqual(unsaved, 17)
        self.touch(page, 'B')
        s = state(page)
        page.wait_for_function(
            f'JSON.parse(localStorage.getItem({RECORDS_KEY!r}) || "{{}}").momentum === 17', timeout=5000)
        stored = page.evaluate(f'JSON.parse(localStorage.getItem({RECORDS_KEY!r}))')
        print('stored records after game over:', stored)
        return s

    def test_blue_x5_continue_offer_then_restart(self):
        page = self.open(interstitial_due=True)
        s = self.check_game_over_saves_record(page)
        game_over = s['deaths'] == 1 and s['offer'] and s['runOver']
        self.record_case('B5-offer', s, game_over)
        self.assertEqual(s['hp'], 0)
        self.assertTrue(game_over, s)
        page.evaluate('restartFromOffer()')
        page.wait_for_function('runInProgress && !continueOffer.visible', timeout=10000)
        page.evaluate('cancelAnimationFrame(game)')
        r = state(page)
        self.record_case('B5-offer-restart', r, False)
        self.assertEqual((r['version'], r['hp'], r['streak']), ('momentum', 5, 0))

    def test_blue_x5_fast_restart(self):
        page = self.open()
        self.touch(page, 'GG')
        s = self.check_game_over_saves_record(page)
        # The fast restart already ran startMomentumVersion: hp is back to 5
        game_over = s['deaths'] == 1 and not s['offer']
        self.record_case('B5-fast-restart', s, game_over)
        self.assertTrue(game_over, s)
        self.assertEqual((s['version'], s['hp'], s['streak'], s['runInProgress']), ('momentum', 5, 0, True))

    def test_inert_in_bad(self):
        page = self.open()
        page.evaluate("startGame('bad'); cancelAnimationFrame(game)")
        self.touch(page, 'GGGGGBBBBBW')
        s = state(page)
        self.record_case('bad-inert', s, s['deaths'] > 0)
        self.assertEqual((s['version'], s['hp'], s['streak'], s['borderTouches'], s['deaths']),
                         ('bad', 5, 0, 0, 0))


if __name__ == '__main__':
    unittest.main()
