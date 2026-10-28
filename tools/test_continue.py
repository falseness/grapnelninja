"""Lethal death without a continue (no rewarded ad).

The ad SDK build offered a rewarded Continue after an eligible death
(TASK-080/093/125). 8519216 (TASK-242) removed rewarded continues: every
lethal death, at any score, freezes the run on free Restart/Menu choices and
nothing brings the ninja back into the same run. Leaving the death sends one
level_failed (TASK-341); Restart starts a new run at score 0 and the mode
switch (TASK-361, formerly Menu) starts a run of the other mode.

e882a5e (TASK-370) shows that death screen only when a game over
interstitial is due (PLATFORM.isInterstitialDue()); any other death sends
level_failed and restarts the same mode at once (fast restart). The local
adapter (c232782) has no ads: no interstitial is ever due, so the death
screen is unreachable and every death fast-restarts, even with
PLATFORM.interstitialMinGapMs passed on a frozen PLATFORM.now().
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import collect_errors, start_game_test, switch_mode

ROOT = Path(__file__).resolve().parent.parent

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

# No rewarded ad is supported (TASK-746 added the facade's
# isRewardedSupported, false on the local backend) and neither the old
# requestRewarded, the per-run continue flag nor a Continue button exists
NO_CONTINUE = '''() => [PLATFORM.isRewardedSupported(), typeof PLATFORM.requestRewarded,
    typeof continueUsed, 'continueButton' in continueOffer]'''


def state(page):
    return page.evaluate('''() => ({offer: continueOffer.visible, score: scoreText.count[version],
        reStarts: window.__reStarts, events: window.__events.slice(),
        clickable: [continueOffer.restartButton.clickable, continueOffer.switchButton.clickable],
        gamePaused: menu.gamePaused, version, adPending: interstitialPending,
        due: PLATFORM.isInterstitialDue()})''')


class NoContinueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)

    def boot(self, viewport, **context_options):
        context = self.browser.new_context(viewport=viewport, **context_options)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = collect_errors(page)
        page.goto(self.url + 'index.html')
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('PLATFORM.environment === "local" && bootComplete && runInProgress'
                               ' && document.getElementById("loading").hidden', timeout=15000)
        page.evaluate('window.fakeNow = 1000000; PLATFORM.now = () => window.fakeNow')
        self.assertEqual(page.evaluate(NO_CONTINUE), [False, 'undefined', 'undefined', False])
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialSupported()'))
        # Boot runs 'bad'; the deaths below are classic deaths
        switch_mode(page, 'classic')
        page.evaluate(INSTRUMENT_RUN)
        page.wait_for_timeout(300)
        return page

    def kill(self, page, score):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(300)

    def check_fast_restart(self, page, score, restarts, events):
        """No ad is ever due locally: a death restarts at once."""
        page.evaluate('window.fakeNow += PLATFORM.interstitialMinGapMs')
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        self.kill(page, score)
        events = events + [['level_failed', 'classic'], ['level_started', 'classic']]
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['events'], s['adPending'], s['due']),
                         (False, restarts + 1, 0, events, False, False), f'score {score}')
        self.assertEqual((s['gamePaused'], s['version']), (False, 'classic'), f'score {score}')
        self.assertTrue(page.evaluate('Number.isFinite(time)'), f'score {score}: play clock stopped')
        print(f'  ASSERT score {score} death (local, no ad due) -> fast restart: one level_failed, '
              f'new classic run at score 0, no death screen: pass', file=sys.stderr)
        return events

    def check_deaths(self, page, scores):
        events = []
        for restarts, score in enumerate(scores):
            events = self.check_fast_restart(page, score, restarts, events)

    def test_death_fast_restarts_mouse(self):
        page = self.boot({'width': 1280, 'height': 720})
        self.check_deaths(page, [4, 5, 7])

    def test_death_fast_restarts_touch_844x390(self):
        page = self.boot({'width': 844, 'height': 390}, has_touch=True, is_mobile=True)
        self.check_deaths(page, [5, 6])


if __name__ == '__main__':
    unittest.main()
