"""TASK-721: the first death of a Grapple Over run offers double grapnel mode.

Boots the real index.html with its real frame loop and drops the player
below the recovery depth, so the production recoverClimbFall() runs from
physics(). On the run's first recovery in single mode the game pauses on the
CLIMB_UI offer (Continue / Try double grapnel mode, plus the intended-way
note); the run clock stays frozen for 2 s of wall time. Continue resumes with
the spawn launch; Try switches to double keeping time and best height and
setting usedDouble. Death 2 shows no offer, nor does a death 1 already in
double mode, nor a death after a save and page reload past the offer.
Answers are given by trusted clicks on the drawn buttons.

DOUBLE_OFFER_EVIDENCE_DIR=DIR writes offer.json, offer-en.png and offer-ru.png.

    DOUBLE_OFFER_EVIDENCE_DIR=DIR python3 -m unittest discover -s tools -p test_double_offer.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import time
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
OUT = os.environ.get('DOUBLE_OFFER_EVIDENCE_DIR')
CLIMB_KEY = 'grapnelninja.grappleOver'
RESULT = {}

STATE = '''() => {
    const w = floors[0], s = w.level.spawn
    return {paused: menu.gamePaused, offering: CLIMB_UI.offering, mode: w.grapnelMode,
        usedDouble: w.usedDouble, offerShown: w.doubleOfferShown,
        elapsedMs: w.climbStats.elapsedActiveMs, best: w.climbStats.maxHeight,
        tick: w.elapsedSteps, x: ninja.x, y: ninja.y, speedY: ninja.speedY,
        atSpawn: ninja.x === s.x, launch: getSpawnLaunchSpeed(), recoveries: window.RECOVERIES || 0,
        buttons: CLIMB_UI.buttons.map(b => b.text.text)}
}'''

# Wrap the production recovery to count it, then drop the player 3000 under the spawn.
DIE = '''() => {
    if (!window.RECOVERY_WRAPPED) {
        const recover = recoverClimbFall
        window.RECOVERIES = 0
        recoverClimbFall = function() { RECOVERIES++; return recover() }
        window.RECOVERY_WRAPPED = true
    }
    const s = floors[0].level.spawn
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null})
    ninja.x = s.x; ninja.y = s.y + 3000; ninja.speedX = 0; ninja.speedY = 0
    floors[0].climbStats.currentHeight = -3000
    return RECOVERIES
}'''


class DoubleOfferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if OUT and RESULT:
            Path(OUT).mkdir(parents=True, exist_ok=True)
            (Path(OUT) / 'offer.json').write_text(json.dumps(RESULT, ensure_ascii=False, separators=(',', ':')),
                                                  encoding='utf-8')

    def open(self, context=None, lang='en'):
        if context is None:
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
            self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate('l => setLanguage(l)', lang)
        if page.evaluate('menu.gamePaused'):
            page.evaluate('menu.unPause()')
        return page

    def state(self, page):
        return page.evaluate(STATE)

    def die(self, page):
        """A real death through the live loop; returns the state once recovered."""
        before = page.evaluate(DIE)
        page.wait_for_function('n => RECOVERIES > n', arg=before, timeout=10000)
        page.wait_for_timeout(100)
        return self.state(page)

    def click(self, page, index):
        b = page.evaluate('''i => { const b = CLIMB_UI.buttons[i].background, c = getCanvasCssRect(), k = c.width / menu.width
            return {x: c.left + (b.x + b.width / 2) * k, y: c.top + (b.y + b.height / 2) * k} }''', index)
        page.mouse.click(b['x'], b['y'])
        page.wait_for_timeout(50)

    def frozen(self, page):
        """The run clock and simulation over 2 s of wall time under the offer."""
        a = self.state(page)
        t = time.monotonic()
        page.wait_for_timeout(2000)
        b = self.state(page)
        return {'wallMs': round((time.monotonic() - t) * 1000), 'elapsedBefore': a['elapsedMs'],
                'elapsedAfter': b['elapsedMs'], 'tickBefore': a['tick'], 'tickAfter': b['tick'],
                'yBefore': a['y'], 'yAfter': b['y'], 'stillOffering': b['offering'] and b['paused']}

    def check_offer(self, s, frozen):
        self.assertEqual((s['paused'], s['offering'], s['mode'], s['offerShown'], s['atSpawn']),
                         (True, True, 'single', True, True), s)
        self.assertEqual(s['buttons'], ['Continue', 'Try double grapnel mode'])
        self.assertAlmostEqual(s['speedY'], -s['launch'], places=6)
        self.assertGreaterEqual(frozen['wallMs'], 2000)
        self.assertEqual(frozen['elapsedAfter'], frozen['elapsedBefore'])
        self.assertEqual(frozen['tickAfter'], frozen['tickBefore'])
        self.assertEqual(frozen['yAfter'], frozen['yBefore'])
        self.assertTrue(frozen['stillOffering'])

    def check_no_offer(self, s):
        self.assertEqual((s['paused'], s['offering']), (False, False), s)

    def test_01_continue_run(self):
        page = self.open()
        page.wait_for_timeout(500)
        death1 = self.die(page)
        frozen = self.frozen(page)
        self.check_offer(death1, frozen)
        self.click(page, 0)
        resumed = self.state(page)
        page.wait_for_timeout(300)
        after = self.state(page)
        self.check_no_offer(resumed)
        self.assertEqual(after['mode'], 'single')
        self.assertFalse(after['usedDouble'])
        # The launch plays: the player rises from the spawn and the clock runs again.
        self.assertLess(after['y'], death1['y'])
        self.assertGreater(after['elapsedMs'], death1['elapsedMs'])
        death2 = self.die(page)
        page.wait_for_timeout(300)
        death2_later = self.state(page)
        self.check_no_offer(death2)
        self.assertGreater(death2_later['elapsedMs'], death2['elapsedMs'])
        RESULT['continueRun'] = {
            'death1': {k: death1[k] for k in ('paused', 'offering', 'mode', 'buttons', 'speedY', 'launch', 'offerShown')},
            'frozen2s': frozen,
            'afterContinue': {'paused': resumed['paused'], 'offering': resumed['offering'], 'mode': after['mode'],
                              'usedDouble': after['usedDouble'], 'yAtOffer': death1['y'], 'y300ms': after['y'],
                              'rose': after['y'] < death1['y'], 'clockRunning': after['elapsedMs'] > death1['elapsedMs']},
            'death2': {'paused': death2['paused'], 'offering': death2['offering'], 'recoveries': death2['recoveries'],
                       'clockRunning': death2_later['elapsedMs'] > death2['elapsedMs']}}
        self.assertEqual(page.errors, [])

    def test_02_try_double_run(self):
        page = self.open()
        page.wait_for_timeout(500)
        death1 = self.die(page)
        frozen = self.frozen(page)
        self.check_offer(death1, frozen)
        self.click(page, 1)
        resumed = self.state(page)
        self.check_no_offer(resumed)
        self.assertEqual((resumed['mode'], resumed['usedDouble']), ('double', True))
        self.assertEqual(resumed['best'], death1['best'])
        self.assertTrue(resumed['atSpawn'])
        # Time kept: the clock resumes from where the offer froze it.
        self.assertGreaterEqual(resumed['elapsedMs'], death1['elapsedMs'])
        self.assertLess(resumed['elapsedMs'] - death1['elapsedMs'], 200)
        range_ = page.evaluate('grappleOverAcquisitionRadius()')
        death2 = self.die(page)
        self.check_no_offer(death2)
        RESULT['tryDoubleRun'] = {
            'atOffer': {'mode': death1['mode'], 'elapsedMs': death1['elapsedMs'], 'best': death1['best'],
                        'usedDouble': death1['usedDouble']},
            'frozen2s': frozen,
            'afterTry': {'paused': resumed['paused'], 'mode': resumed['mode'], 'usedDouble': resumed['usedDouble'],
                         'elapsedMs': resumed['elapsedMs'], 'best': resumed['best'], 'atSpawn': resumed['atSpawn'],
                         'bestUnchanged': resumed['best'] == death1['best'],
                         'timeKeptMsDelta': resumed['elapsedMs'] - death1['elapsedMs'], 'range': range_},
            'death2': {'paused': death2['paused'], 'offering': death2['offering']}}
        self.assertEqual(page.errors, [])

    def test_03_already_double(self):
        page = self.open()
        page.evaluate('() => { CLIMB_UI.restart(); setGrapnelMode("double") }')
        page.wait_for_timeout(300)
        death1 = self.die(page)
        self.check_no_offer(death1)
        self.assertTrue(death1['offerShown'])
        RESULT['alreadyDouble'] = {'death1': {'paused': death1['paused'], 'offering': death1['offering'],
                                              'mode': death1['mode']}}
        self.assertEqual(page.errors, [])

    def test_04_reload_past_offer(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
        self.addCleanup(context.close)
        page = self.open(context)
        page.evaluate('() => CLIMB_UI.restart()')
        page.wait_for_timeout(300)
        death1 = self.die(page)
        self.assertTrue(death1['offering'])
        self.click(page, 0)
        page.evaluate('() => PROGRESS.flushClimb()')
        page.wait_for_function('k => { const v = JSON.parse(localStorage.getItem(k) || "null")'
                               '; return v && v.doubleOfferShown === true }', arg=CLIMB_KEY)
        saved = json.loads(page.evaluate('k => localStorage.getItem(k)', CLIMB_KEY))['doubleOfferShown']
        errors = list(page.errors)
        page.close()
        page2 = self.open(context)
        reloaded = page2.evaluate('floors[0].doubleOfferShown')
        death = self.die(page2)
        self.check_no_offer(death)
        # Saves from before the offer load as a run that has not seen it.
        old = page2.evaluate('''() => { const s = captureClimbState(); delete s.doubleOfferShown
            restoreClimbState(s); return floors[0].doubleOfferShown }''')
        self.assertIs(old, False)
        RESULT['reload'] = {'savedDoubleOfferShown': saved, 'afterReload': reloaded,
                            'deathAfterReload': {'paused': death['paused'], 'offering': death['offering'],
                                                 'mode': death['mode']}, 'oldSaveDefault': old}
        self.assertIs(saved, True)
        self.assertIs(reloaded, True)
        self.assertEqual(errors + page2.errors, [])

    def test_05_crops(self):
        RESULT['crops'] = {}
        for lang, title, buttons in (('en', 'Back to the start', ['Continue', 'Try double grapnel mode']),
                                     ('ru', 'Снова в начале', ['Продолжить', 'Попробовать двойной крюк'])):
            page = self.open(lang=lang)
            page.evaluate('() => CLIMB_UI.restart()')
            page.wait_for_timeout(300)
            s = self.die(page)
            self.assertTrue(s['offering'])
            self.assertEqual(s['buttons'], buttons)
            got_title = page.evaluate('I18N.t("climb.offerTitle")')
            note = page.evaluate('I18N.t("climb.grapnelNote")')
            self.assertEqual(got_title, title)
            # Title through the note, centred on the overlay
            c = page.evaluate('''() => { const c = getCanvasCssRect()
                return {x: c.left + c.width * 0.15, y: c.top + c.height * 0.06, width: c.width * 0.7, height: c.height * 0.85} }''')
            if OUT:
                Path(OUT).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(OUT) / ('offer-%s.png' % lang)), clip=c, scale='css', type='png')
            RESULT['crops'][lang] = {'title': got_title, 'buttons': s['buttons'], 'note': note}
            self.assertEqual(page.errors, [])


if __name__ == '__main__':
    unittest.main()
