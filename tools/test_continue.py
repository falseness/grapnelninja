"""Lethal death without a continue (no rewarded ad).

The ad SDK build offered a rewarded Continue after an eligible death
(TASK-080/093/125). 8519216 (TASK-242) removed rewarded continues: every
lethal death, at any score, freezes the run on free Restart/Menu choices and
nothing brings the ninja back into the same run. Leaving the death sends one
level_failed (TASK-341); Restart starts a new run at score 0 and the mode
switch (TASK-361, formerly Menu) starts a run of the other mode.

e882a5e (TASK-370) shows that death screen only when a game over
interstitial is due (PLATFORM.isInterstitialDue()); any other death sends
level_failed and restarts the same mode at once (fast restart). The suite
serves the fake Bridge of test_playgama2_bridge.py with interstitials
supported (as test_fast_restart.py does) and freezes PLATFORM.now() at
window.fakeNow: advancing it by PLATFORM.interstitialMinGapMs makes the next
death due; a death right after the ad requested by leaving a death screen is
not due and fast-restarts.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import SDK_URL
from game_harness import collect_errors, start_game_test, switch_mode
from test_playgama2_bridge import FAKE

ROOT = Path(__file__).resolve().parent.parent

# Interstitials supported: each request is recorded, then opens and closes
# (the ADS fixture of test_fast_restart.py)
ADS = r"""
probe.interstitials = [];
Object.assign(bridge.advertisement, {
    isInterstitialSupported: true,
    interstitialState: 'closed',
    showInterstitial(placement) {
        probe.interstitials.push(placement);
        const set = state => { bridge.advertisement.interstitialState = state; emitHost('interstitial', state); };
        set('loading');
        setTimeout(() => set('opened'), 20);
        setTimeout(() => set('closed'), 60);
    }
});
"""

# Count reStart calls and pin the ninja at its start state after every physics
# tick so it never dies on its own. window.__kill puts it on the top edge of
# the lethal bottom Side under it before the next tick: a real lethal death
# through ninja.move(). (Falling behind the deletion border no longer kills:
# 2555291 (TASK-225) added the bouncing left wall.)
# window.__events records the lifecycle messages.
INSTRUMENT_RUN = '''() => {
    window.__reStarts = 0
    window.__events = []
    const send = PLATFORM.sendLifecycle
    PLATFORM.sendLifecycle = function(name, data) {
        window.__events.push([name, data && data.world])
        return send.apply(this, arguments)
    }
    const original = window.reStart
    window.reStart = function() {
        window.__reStarts++
        window.__pin = null
        return original.apply(this, arguments)
    }
    const physicsStep = window.physics
    window.physics = function() {
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        if (window.__kill) {
            window.__kill = false
            const side = floors[2].elements.find(e => e instanceof Side &&
                e.getLeftPointX() <= ninja.x && ninja.x <= e.getRightPointX())
            ninja.y = side.y
            ninja.speedX = 0
            ninja.speedY = 0
        }
        const result = physicsStep.apply(this, arguments)
        if (continueOffer.visible)
            return result
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        ninja.x = window.__pin.x
        ninja.y = window.__pin.y
        ninja.speedX = 0
        ninja.speedY = 0
        return result
    }
}'''

# Neither the rewarded API, the per-run continue flag nor a Continue button exists
NO_CONTINUE = '''() => [typeof PLATFORM.isRewardedSupported, typeof PLATFORM.requestRewarded,
    typeof continueUsed, 'continueButton' in continueOffer]'''

PRESS = '''name => {
    const b = continueOffer[name].background
    if (!continueOffer.click({x: b.x + b.width / 2, y: b.y + b.height / 2}))
        throw Error(name + ' click ignored')
}'''


def state(page):
    return page.evaluate('''() => ({offer: continueOffer.visible, score: scoreText.count[version],
        reStarts: window.__reStarts, events: window.__events.slice(),
        clickable: [continueOffer.restartButton.clickable, continueOffer.switchButton.clickable],
        gamePaused: menu.gamePaused, version, ads: probe.interstitials.slice(),
        due: PLATFORM.isInterstitialDue()})''')


class NoContinueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)

    def boot(self, viewport, **context_options):
        context = self.browser.new_context(viewport=viewport, **context_options)
        self.addCleanup(context.close)
        context.route(SDK_URL, lambda route: route.fulfill(content_type='application/javascript',
            body='const FAULT = "normal"; const SAVED_LANGUAGE = null;\n' + FAKE + ADS))
        page = context.new_page()
        errors = collect_errors(page)
        page.goto(self.url + 'index.html')
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('PLATFORM.environment === "playgama" && bootComplete && runInProgress'
                               ' && document.getElementById("loading").hidden', timeout=15000)
        page.evaluate('window.fakeNow = 1000000; PLATFORM.now = () => window.fakeNow')
        self.assertEqual(page.evaluate(NO_CONTINUE), ['undefined', 'undefined', 'undefined', False])
        # Boot runs 'bad'; the deaths below are classic deaths
        switch_mode(page, 'classic')
        page.evaluate(INSTRUMENT_RUN)
        page.wait_for_timeout(300)
        return page

    def kill(self, page, score):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(300)

    def press(self, page, button):
        page.evaluate(PRESS, button)
        page.wait_for_function('!continueOffer.visible && !interstitialPending')
        page.wait_for_timeout(100)

    def make_due(self, page):
        """Let PLATFORM.interstitialMinGapMs pass on the frozen clock."""
        page.evaluate('window.fakeNow += PLATFORM.interstitialMinGapMs')
        self.assertTrue(page.evaluate('PLATFORM.isInterstitialDue()'))

    def check_frozen_death(self, page, score, restarts, events, ads):
        """A death with an ad due freezes the run on Restart/switch; nothing
        restarts it yet and no ad is requested yet."""
        self.make_due(page)
        self.kill(page, score)
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['events'], s['clickable'], s['ads']),
                         (True, restarts, score, events, [True, True], ads), f'score {score}')
        self.assertEqual((s['gamePaused'], s['version']), (False, 'classic'), f'score {score}')
        print(f'  ASSERT score {score} death (ad due) -> frozen Restart/switch, no continue, no reStart: pass',
              file=sys.stderr)

    def check_fast_restart(self, page, score, restarts, events, ads):
        """A death with no ad due (one was just requested) restarts at once."""
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        self.kill(page, score)
        events = events + [['level_failed', 'classic'], ['level_started', 'classic']]
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['events'], s['ads']),
                         (False, restarts + 1, 0, events, ads), f'score {score}')
        self.assertEqual((s['gamePaused'], s['version']), (False, 'classic'), f'score {score}')
        print(f'  ASSERT score {score} death (no ad due) -> fast restart: one level_failed, '
              f'new classic run at score 0, no ad: pass', file=sys.stderr)
        return events

    def check_deaths(self, page, scores):
        events = []
        ads = []
        restarts = 0
        for score in scores:
            self.check_frozen_death(page, score, restarts, events, ads)
            self.press(page, 'restartButton')
            restarts += 1
            ads = ads + ['game_over']
            events = events + [['level_failed', 'classic'], ['level_started', 'classic']]
            s = state(page)
            self.assertEqual((s['offer'], s['reStarts'], s['score'], s['events'], s['ads']),
                             (False, restarts, 0, events, ads), f'score {score}')
            self.assertEqual((s['gamePaused'], s['version']), (False, 'classic'), f'score {score}')
            print(f'  ASSERT score {score} Restart -> one level_failed, one game_over ad, '
                  f'new run at score 0: pass', file=sys.stderr)
            events = self.check_fast_restart(page, score, restarts, events, ads)
            restarts += 1
        # One more death, left through the mode switch
        score = scores[-1]
        self.check_frozen_death(page, score, restarts, events, ads)
        self.press(page, 'switchButton')
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['version'], s['events'], s['ads']),
                         (False, restarts, 'bad', events + [['level_failed', 'classic'],
                                                            ['level_started', 'bad']],
                          ads + ['game_over']))
        print(f'  ASSERT score {score} switch -> one level_failed, one game_over ad, '
              f'bad run started, no reStart: pass', file=sys.stderr)

    def test_death_offers_restart_or_switch_mouse(self):
        page = self.boot({'width': 1280, 'height': 720})
        self.check_deaths(page, [4, 5, 7])

    def test_death_offers_restart_or_switch_touch_844x390(self):
        page = self.boot({'width': 844, 'height': 390}, has_touch=True, is_mobile=True)
        self.check_deaths(page, [5, 6])


if __name__ == '__main__':
    unittest.main()
