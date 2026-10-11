"""Continue offer and rewarded outcomes on the Y8 adapter (TASK-080/093/125,
Y8 re-port TASK-289).

Without an SDK (OfflineBrowser's rejecting stub: PLATFORM.environment
"disabled") rewarded ads are unsupported, so every lethal death, at any
score, restarts the run at once and the offer never shows. With the fake SDK
(tools/fixtures/fake-y8-sdk.js, environment "y8") an eligible death (score
>= CONTINUE_MIN_SCORE) shows the offer and freezes the run; the rewarded
request's outcome decides between a safe respawn (rewarded) and an
"Ad unavailable" offer with Restart only (dismissed, no-fill, reject,
timeout). PLATFORM.requestRewarded is observed, never stubbed: the results
the game received are recorded in window.__rewarded.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import (READY, canvas_to_viewport, click_canvas, install_kill, open_game,
                          sdk_calls, start_game_test)

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = {'width': 1280, 'height': 720}
TOUCH = {'width': 844, 'height': 390}
AD_ERROR = 'Ad unavailable'
# Fake SDK callbacks of one rewarded break, in the order the game sees them
REWARDED_CALLS = ['showAd', 'beforeReward', 'showAdFn', 'beforeAd', 'adViewed', 'afterAd',
                  'adBreakDone']

# Count reStart/respawnNinja calls and pin the ninja at its start state (or
# its respawn point) after every physics tick so it never dies on its own.
# window.__kill places it on the top side floor before the next tick (a real
# lethal death through ninja.move(), see game_harness.PLACE_ON_TOP_SIDE).
# While the offer is shown the ninja is left alone, so a frozen run shows as
# unchanged x/y. Every result the game gets back from PLATFORM.requestRewarded
# lands in window.__rewarded.
INSTRUMENT_RUN = '''() => {
    window.__reStarts = 0
    window.__respawns = 0
    window.__rewarded = []
    const original = window.reStart
    window.reStart = function() {
        window.__reStarts++
        window.__pin = null
        return original.apply(this, arguments)
    }
    const respawn = window.respawnNinja
    window.respawnNinja = function() {
        const result = respawn.apply(this, arguments)
        window.__respawns++
        window.__pin = {x: ninja.x, y: ninja.y}
        return result
    }
    const request = PLATFORM.requestRewarded
    PLATFORM.requestRewarded = function() {
        return request.apply(PLATFORM, arguments).then(result => {
            window.__rewarded.push(result)
            return result
        })
    }
    const physicsStep = window.physics
    window.physics = function() {
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        if (window.__kill) {
            window.__kill = false
            window.__killed = window.__placeOnTopSide()
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

STATE = '''() => ({offer: continueOffer.visible, score: scoreText.count[version],
    reStarts: window.__reStarts, respawns: window.__respawns, continueUsed: continueUsed,
    rewarded: window.__rewarded, adPending: continueOffer.adPending,
    adFailed: continueOffer.adFailed, watchVisible: continueOffer.watchVisible(),
    watchClickable: continueOffer.continueButton.clickable,
    restartClickable: continueOffer.restartButton.clickable,
    notice: continueOffer.notice(), invulnerable: ninja.isInvulnerable(),
    adOpen: adOpen, x: ninja.x, y: ninja.y,
    gamePaused: menu.gamePaused, menuVisible: menu.visible})'''


def state(page):
    return page.evaluate(STATE)


def log(message):
    print('  ' + message, file=sys.stderr)


def show_ads(page):
    return sum(c['name'] == 'showAd' for c in sdk_calls(page))


class ContinueTestCase(unittest.TestCase):
    environment = None

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)

    def boot(self, viewport, fake_sdk=None, **context_options):
        context, page, errors = open_game(self.browser, self.url + 'index.html', viewport,
                                          fake_sdk=fake_sdk, **context_options)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function(READY, timeout=15000)
        self.assertEqual(page.evaluate('[PLATFORM.environment, PLATFORM.platformId]'),
                         [self.environment, 'y8'])
        self.assertEqual(page.evaluate('PLATFORM.isRewardedSupported()'),
                         self.environment == 'y8')
        install_kill(page)
        page.evaluate(INSTRUMENT_RUN)
        page.evaluate('''() => {
            const b = menu.classicVersionButton.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
        }''')
        page.wait_for_timeout(300)
        self.assertEqual(show_ads(page), 0)
        return page

    def kill(self, page, score, offer):
        """A lethal death at score; wait for the offer or the instant restart."""
        restarts = page.evaluate('window.__reStarts')
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_function('continueOffer.visible || window.__reStarts > %d' % restarts,
                               timeout=5000)
        page.wait_for_timeout(150)
        s = state(page)
        self.assertEqual(s['offer'], offer, f'score {score}')
        self.assertEqual(page.evaluate('window.__killed.element'), 'Side')
        return s

    def center(self, page, name):
        return page.evaluate(f'''(() => {{ const b = continueOffer.{name}.background
            return {{x: b.x + b.width / 2, y: b.y + b.height / 2}} }})()''')

    def wait_input(self, page):
        # events.js ignores input for STYLE.timing.inputUntouchMs after a button click
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def click_button(self, page, name):
        c = self.center(page, name)
        click_canvas(page, c['x'], c['y'])
        self.wait_input(page)

    def tap_button(self, page, name):
        c = self.center(page, name)
        p = canvas_to_viewport(page, c['x'], c['y'])
        page.touchscreen.tap(round(p['x']), round(p['y']))
        self.wait_input(page)


class NoContinueTests(ContinueTestCase):
    """SDK stubbed/absent: environment "disabled", no offer at any score."""
    environment = 'disabled'

    def check_instant_restarts(self, page, scores):
        for i, score in enumerate(scores, 1):
            s = self.kill(page, score, offer=False)
            self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                             (False, i, 0, False), f'score {score}')
            self.assertFalse(s['gamePaused'] or s['menuVisible'], f'score {score}')
            log(f'ASSERT score {score} death -> instant reStart, no offer: pass')
        self.assertEqual((s['rewarded'], s['respawns'], show_ads(page)), ([], 0, 0))

    def test_death_restarts_instantly_mouse(self):
        page = self.boot(DESKTOP)
        self.assertEqual(page.evaluate('CONTINUE_MIN_SCORE'), 5)
        self.check_instant_restarts(page, [4, 5, 7])

    def test_death_restarts_instantly_touch_844x390(self):
        page = self.boot(TOUCH, has_touch=True, is_mobile=True)
        self.check_instant_restarts(page, [5, 6])


class ContinueOutcomeTests(ContinueTestCase):
    """Fake SDK: environment "y8", one rewarded request per continue."""
    environment = 'y8'

    def restart_from_offer(self, page, restarts, tap=False):
        """Restart on the offer: a fresh run with score 0, no continue used."""
        (self.tap_button if tap else self.click_button)(page, 'restartButton')
        s = state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                         (False, restarts, 0, False))
        self.assertFalse(s['gamePaused'] or s['menuVisible'])
        return s

    def test_rewarded_continues_mouse(self):
        page = self.boot(DESKTOP, fake_sdk={'rewardOutcome': 'viewed'})

        # (a) score < CONTINUE_MIN_SCORE: instant restart, no offer, no ad
        self.assertEqual(page.evaluate('CONTINUE_MIN_SCORE'), 5)
        s = self.kill(page, 4, offer=False)
        self.assertEqual((s['reStarts'], s['score'], s['rewarded'], show_ads(page)),
                         (1, 0, [], 0))
        log('ASSERT (a) score 4 death -> instant reStart, no offer: pass')

        # (b) score >= 5: the offer, frozen physics, no ad requested yet
        before = self.kill(page, 5, offer=True)
        self.assertEqual((before['reStarts'], before['score'], before['watchVisible'],
                          before['watchClickable'], before['restartClickable']),
                         (1, 5, True, True, True))
        page.wait_for_timeout(500)
        s = state(page)
        self.assertEqual((s['offer'], s['x'], s['y'], show_ads(page)),
                         (True, before['x'], before['y'], 0))
        # Pause keys and blur do nothing while the offer is shown
        page.keyboard.press('Escape')
        page.evaluate('window.dispatchEvent(new Event("blur"))')
        self.assertFalse(state(page)['gamePaused'])
        log(f'ASSERT (b) score 5 death -> offer; ninja ({before["x"]:.3f}, {before["y"]:.3f})'
            ' unchanged over 0.5 s; no showAd: pass')

        # (c) Continue: the rewarded ad plays, the ninja respawns, physics resumes
        self.click_button(page, 'continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=10000)
        page.wait_for_timeout(150)
        s = state(page)
        names = [c['name'] for c in sdk_calls(page) if c['name'] in REWARDED_CALLS]
        self.assertEqual(names, REWARDED_CALLS)
        self.assertEqual(s['rewarded'], [{'status': 'rewarded', 'reason': 'viewed'}])
        self.assertEqual((s['respawns'], s['continueUsed'], s['score'], s['reStarts'],
                          s['adFailed'], s['adOpen']), (1, True, 5, 1, False, False))
        self.assertTrue(s['invulnerable'])
        log(f'ASSERT (c) Continue -> {names}; rewarded, respawn 1, score 5 kept: pass')

        # (d) a second eligible death in the same run restarts instantly
        # (once the respawn invulnerability has run out)
        page.wait_for_function('!ninja.isInvulnerable()', timeout=30000)
        s = self.kill(page, 7, offer=False)
        self.assertEqual((s['reStarts'], s['score'], s['continueUsed'], show_ads(page)),
                         (2, 0, False, 1))
        log('ASSERT (d) second eligible death after continue -> instant reStart: pass')

    def no_reward_case(self, outcome, reason, timeout_ms=None):
        page = self.boot(DESKTOP, fake_sdk={'rewardOutcome': outcome})
        if timeout_ms:
            page.evaluate(f'PLATFORM.rewardTimeoutMs = {timeout_ms}')
        before = self.kill(page, 6, offer=True)
        self.assertTrue(before['watchVisible'] and before['watchClickable'])
        t0 = page.evaluate('performance.now()')
        self.click_button(page, 'continueButton')
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        waited = page.evaluate('performance.now()') - t0
        self.wait_input(page)
        s = state(page)
        # No reward: the offer stays with the score, Restart only
        self.assertEqual(s['rewarded'], [{'status': 'unavailable', 'reason': reason}])
        self.assertEqual((s['offer'], s['notice'], s['watchVisible'], s['watchClickable'],
                          s['restartClickable'], s['adPending'], s['continueUsed']),
                         (True, AD_ERROR, False, False, True, False, True))
        self.assertEqual((s['respawns'], s['reStarts'], s['score'], s['x'], s['y'], s['adOpen']),
                         (0, 0, 6, before['x'], before['y'], False))
        self.assertEqual(show_ads(page), 1)
        if timeout_ms:
            self.assertGreaterEqual(waited, timeout_ms - 100)
        # A click on the old watch button spot does nothing
        self.click_button(page, 'continueButton')
        s = state(page)
        self.assertEqual((s['offer'], s['respawns'], len(s['rewarded']), show_ads(page)),
                         (True, 0, 1, 1))
        self.restart_from_offer(page, restarts=1)
        log(f'ASSERT {outcome}: result unavailable/{reason} after {waited:.0f} ms, '
            f'"{AD_ERROR}", score 6 kept, Restart -> score 0: pass')

    def test_dismissed_keeps_offer(self):
        self.no_reward_case('dismissed', 'dismissed')

    def test_no_fill_keeps_offer(self):
        self.no_reward_case('noAdPreloaded', 'noAdPreloaded')

    def test_reject_keeps_offer(self):
        self.no_reward_case('reject', 'rejected')

    def test_timeout_keeps_offer(self):
        # showAd resolves but never ends the break: the watchdog answers
        self.no_reward_case('silent', 'timeout', timeout_ms=800)

    def test_touch_restart_and_continue_844x390(self):
        page = self.boot(TOUCH, fake_sdk={'rewardOutcome': 'viewed'},
                         has_touch=True, is_mobile=True)
        self.kill(page, 5, offer=True)
        self.restart_from_offer(page, restarts=1, tap=True)
        self.assertEqual(show_ads(page), 0)

        self.kill(page, 5, offer=True)
        self.tap_button(page, 'continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=10000)
        page.wait_for_timeout(150)
        s = state(page)
        self.assertEqual(s['rewarded'], [{'status': 'rewarded', 'reason': 'viewed'}])
        self.assertEqual((s['offer'], s['continueUsed'], s['respawns'], s['score'], show_ads(page)),
                         (False, True, 1, 5, 1))
        log('ASSERT touch tap Restart and Continue at 844x390: pass')


if __name__ == '__main__':
    unittest.main()
