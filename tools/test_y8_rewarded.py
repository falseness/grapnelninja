"""Rewarded ad behind "Watch ad to continue" (TASK-082, Y8 port TASK-093).

Runs against the fake Y8 SDK (tools/fixtures/fake-y8-sdk.js); window.__y8Fake
.rewardOutcome picks the outcome. The ninja is pinned by the TASK-080 physics
wrapper; window.__respawns counts respawnNinja() calls and re-pins the ninja
at the respawn point, window.__ticks counts physics() calls.

Env: Y8_REWARDED_EVIDENCE_DIR receives calls/<case>.json, screens/<state>.png,
outcome-matrix.json and console/page-errors.log.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from y8_harness import (FAKE_SDK, Y8_SDK_ROUTE, canvas_to_viewport, click_canvas,
                        collect_errors, open_game, sdk_calls, start_y8_test)
import test_continue as continue_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
WATCH_LABEL = 'Watch ad to continue'
AD_ERROR = 'Ad unavailable'
ADS_UNAVAILABLE = 'Ads unavailable'
# Fake outcomes that end without a reward (window.__y8Fake.rewardOutcome)
NO_REWARD = ('dismissed', 'noAdPreloaded', 'frequencyCapped', 'notReady', 'reject')

INSTRUMENT_RESPAWN = '''() => {
    window.__respawns = 0
    const original = window.respawnNinja
    window.respawnNinja = function() {
        const result = original.apply(this, arguments)
        window.__respawns++
        window.__pin = {x: ninja.x, y: ninja.y}
        return result
    }
    window.__ticks = 0
    const physicsStep = window.physics
    window.physics = function() {
        window.__ticks++
        return physicsStep.apply(this, arguments)
    }
}'''

STATE = '''() => ({offer: continueOffer.visible, score: scoreText.count[version],
    reStarts: window.__reStarts, respawns: window.__respawns, continueUsed: continueUsed,
    adPending: continueOffer.adPending, adFailed: continueOffer.adFailed,
    watchVisible: continueOffer.watchVisible(),
    watchClickable: continueOffer.continueButton.clickable,
    restartClickable: continueOffer.restartButton.clickable,
    notice: continueOffer.notice(), invulnerable: ninja.isInvulnerable(),
    grapnelThrown: grapnel.throwed, grapnelPos: grapnel.pos.length,
    ticks: window.__ticks, version: version, floors: floors.length,
    x: ninja.x, y: ninja.y})'''


def log(msg):
    print('  ' + msg, file=sys.stderr)


def call_names(page):
    return [c['name'] for c in sdk_calls(page)]


def show_ads(page):
    return call_names(page).count('showAd')


def offer_text(s):
    """What the offer shows in the watch button's place."""
    return WATCH_LABEL if s['watchVisible'] else s['notice']


class Y8RewardedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_y8_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('Y8_REWARDED_EVIDENCE_DIR')
        cls.errors = []
        cls.matrix = {}

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            for kind in ('console', 'page'):
                lines = [f'{name}: {msg}' for name, errors in cls.errors
                         for msg in errors[kind]]
                (out / f'{kind}-errors.log').write_text(''.join(
                    line + '\n' for line in lines))
            (out / 'outcome-matrix.json').write_text(
                json.dumps(cls.matrix, indent=1, sort_keys=True) + '\n')

    def boot(self, fake=None, block_sdk=False, touch=False, environment=None):
        if touch:
            context = self.browser.new_context(viewport=VIEWPORT, has_touch=True)
            context.route(Y8_SDK_ROUTE, lambda route: route.fulfill(
                path=str(FAKE_SDK), content_type='application/javascript'))
            context.add_init_script(f'window.__y8Fake = {json.dumps(fake or {})}')
            page = context.new_page()
            errors = collect_errors(page)
            page.goto(self.url + 'index.html')
        else:
            context, page, errors = open_game(self.browser, self.url + 'index.html',
                                              VIEWPORT, fake, block_sdk)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('PLATFORM.environment !== "pending" && menu.visible',
                               timeout=10000)
        expected = environment or ('disabled' if block_sdk else 'y8')
        self.assertEqual(page.evaluate('PLATFORM.environment'), expected)
        page.evaluate(continue_test.INSTRUMENT_RUN)
        page.evaluate(INSTRUMENT_RESPAWN)
        page.evaluate('''() => {
            const b = menu.classicVersionButton.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
        }''')
        page.wait_for_timeout(300)
        return page

    def state(self, page):
        return page.evaluate(STATE)

    def kill(self, page, score=6, offer=True):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(150)
        self.assertEqual(self.state(page)['offer'], offer)

    def center(self, page, name):
        return page.evaluate(f'''(() => {{ const b = continueOffer.{name}.background
            return {{x: b.x + b.width / 2, y: b.y + b.height / 2}} }})()''')

    def click_button(self, page, name):
        c = self.center(page, name)
        click_canvas(page, c['x'], c['y'])

    def wait_input(self, page):
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def save_calls(self, page, case):
        calls = sdk_calls(page)
        if self.evidence:
            out = Path(self.evidence) / 'calls'
            out.mkdir(parents=True, exist_ok=True)
            (out / f'{case}.json').write_text(json.dumps(calls, indent=1) + '\n')
        return calls

    def save(self, page, name):
        if self.evidence:
            out = Path(self.evidence) / 'screens'
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / f'{name}.png'))

    def record(self, outcome, **entry):
        self.matrix.setdefault(outcome, {}).update(entry)

    def restart_from_offer(self, page):
        """Click Restart on the offer; assert a fresh run with score 0."""
        version = self.state(page)['version']
        self.click_button(page, 'restartButton')
        self.wait_input(page)
        s = self.state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed'],
                          s['version']), (False, 1, 0, False, version))
        ticks = s['ticks']
        page.wait_for_function(f'window.__ticks > {ticks} + 5')
        return True

    def assert_no_reward(self, page, before, notice=AD_ERROR):
        s = self.state(page)
        self.assertTrue(s['offer'])
        self.assertEqual((s['notice'], s['watchVisible'], s['watchClickable'],
                          s['restartClickable'], s['respawns'], s['score'], s['adPending']),
                         (notice, False, False, True, 0, before['score'], False))
        self.assertEqual((s['x'], s['y']), (before['x'], before['y']))
        return s

    def no_reward_case(self, outcome):
        page = self.boot({'rewardOutcome': outcome})
        self.kill(page)
        before = self.state(page)
        self.assertEqual(offer_text(before), WATCH_LABEL)
        self.click_button(page, 'continueButton')
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        self.wait_input(page)
        s = self.assert_no_reward(page, before)
        if outcome == 'dismissed':
            self.save(page, 'ad-error')
        # A click on the old watch button spot does nothing
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        self.assertEqual((self.state(page)['respawns'], show_ads(page)), (0, 1))
        restarted = self.restart_from_offer(page)
        self.save_calls(page, outcome)
        self.record(outcome, offerText=offer_text(s), respawned=False,
                    restartWorks=restarted, showAdCalls=show_ads(page))
        log(f'ASSERT {outcome}: no respawn, "{s["notice"]}", score {s["score"]} kept,'
            ' Restart -> score 0: pass')

    def test_a_viewed_continues(self):
        page = self.boot({'adDurationMs': 8000})
        self.kill(page)
        self.save(page, 'offer')
        before = self.state(page)
        self.assertTrue(before['watchVisible'] and before['watchClickable'])
        self.click_button(page, 'continueButton')
        page.wait_for_function('window.__y8Fake.calls.some(c => c.name == "beforeAd")')
        page.wait_for_timeout(100)
        during = self.state(page)
        self.assertTrue(during['offer'] and during['adPending'])
        self.assertFalse(during['watchClickable'] or during['restartClickable'])
        self.assertEqual((during['x'], during['y'], during['respawns']),
                         (before['x'], before['y'], 0))
        self.save(page, 'ad-pending')
        self.assertNotIn('adViewed', call_names(page),
                         'ad-pending screenshot taken after adViewed')
        page.wait_for_function('!continueOffer.visible', timeout=30000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.save(page, 'after-respawn')
        calls = self.save_calls(page, 'viewed')
        names = [n for n in call_names(page) if n in (
            'showAd', 'beforeReward', 'showAdFn', 'beforeAd', 'adViewed', 'afterAd',
            'adBreakDone')]
        self.assertEqual(names, ['showAd', 'beforeReward', 'showAdFn', 'beforeAd',
                                 'adViewed', 'afterAd', 'adBreakDone'])
        show = next(c for c in calls if c['name'] == 'showAd')
        self.assertIn('adViewed', show['args'][0])
        self.assertEqual((after['respawns'], after['continueUsed'], after['score'],
                          after['reStarts'], after['version'], after['floors']),
                         (1, True, 6, 0, before['version'], before['floors']))
        self.assertTrue(after['invulnerable'])
        # Gameplay resumes: physics ticks run on behind no offer
        page.wait_for_function(f'window.__ticks > {after["ticks"]} + 5')
        self.record('viewed', offerText=offer_text(before), respawned=True,
                    showAdCalls=show_ads(page))
        log(f'ASSERT viewed: {names}; respawns 1, score 6, invulnerable, resumed: pass')

    def test_b_dismissed(self):
        self.no_reward_case('dismissed')

    def test_b_no_ad_preloaded(self):
        self.no_reward_case('noAdPreloaded')

    def test_b_frequency_capped(self):
        self.no_reward_case('frequencyCapped')

    def test_b_not_ready(self):
        self.no_reward_case('notReady')

    def test_b_reject(self):
        self.no_reward_case('reject')

    def test_b_silent_hits_watchdog(self):
        page = self.boot({'rewardOutcome': 'silent'})
        page.evaluate('PLATFORM.rewardTimeoutMs = 1500')
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        page.wait_for_timeout(700)
        s = self.state(page)
        self.assertTrue(s['adPending'] and not s['restartClickable'])
        t0 = page.evaluate('performance.now()')
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        waited = page.evaluate('performance.now()') - t0
        self.assertGreater(waited + 700, 1400)
        self.wait_input(page)
        s = self.assert_no_reward(page, before)
        self.assertEqual(show_ads(page), 1)
        restarted = self.restart_from_offer(page)
        self.save_calls(page, 'silent')
        self.record('silent', offerText=offer_text(s), respawned=False,
                    restartWorks=restarted, showAdCalls=show_ads(page))
        log(f'ASSERT silent: watchdog error after ~{waited + 700:.0f} ms, Restart works: pass')

    def test_c_double_click_requests_one_ad(self):
        page = self.boot({'adDurationMs': 8000})
        untouch = page.evaluate('STYLE.timing.inputUntouchMs')
        self.kill(page)
        c = self.center(page, 'continueButton')
        p = canvas_to_viewport(page, c['x'], c['y'])
        # Two instant clicks plus three spaced past the input debounce
        for i in range(5):
            page.mouse.click(round(p['x']), round(p['y']))
            if i >= 1:
                page.wait_for_timeout(untouch + 20)
        self.assertTrue(self.state(page)['offer'])
        page.wait_for_function('!continueOffer.visible', timeout=30000)
        page.wait_for_timeout(150)
        self.save_calls(page, 'doubleclick')
        self.assertEqual(show_ads(page), 1)
        self.assertEqual(call_names(page).count('adViewed'), 1)
        self.assertEqual(self.state(page)['respawns'], 1)
        log(f'ASSERT 5 Watch clicks -> showAd x{show_ads(page)}: pass')

    def test_d_second_death_after_continue_restarts(self):
        page = self.boot()
        self.kill(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=30000)
        self.assertEqual(self.state(page)['respawns'], 1)
        page.wait_for_function('!ninja.isInvulnerable()', timeout=30000)
        self.kill(page, 9, offer=False)
        s = self.state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                         (False, 1, 0, False))
        self.assertEqual(show_ads(page), 1)
        self.record('viewed', restartWorks=True)
        log('ASSERT second lethal death after continue -> instant restart, no offer: pass')

    def test_d_late_reward_after_watchdog_is_ignored(self):
        # The break outlives the watchdog: adViewed arrives after the error
        page = self.boot({'adDurationMs': 2500})
        page.evaluate('PLATFORM.rewardTimeoutMs = PLATFORM.rewardPlayingTimeoutMs = 800')
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        page.wait_for_function('window.__y8Fake.calls.some(c => c.name == "adBreakDone")',
                               timeout=10000)
        page.wait_for_timeout(200)
        self.assertIn('adViewed', call_names(page))
        self.assert_no_reward(page, before)
        self.restart_from_offer(page)
        log('ASSERT adViewed after the watchdog error: no respawn, Restart works: pass')

    def disabled_case(self, **boot):
        page = self.boot(environment='disabled', **boot)
        self.kill(page)
        s = self.state(page)
        self.assertEqual((s['watchVisible'], s['watchClickable'], s['restartClickable'],
                          s['notice']), (False, False, True, ADS_UNAVAILABLE))
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        self.assertEqual((self.state(page)['respawns'], self.state(page)['offer']), (0, True))
        return page, s

    def test_e_sdk_blocked_ads_unavailable(self):
        page, s = self.disabled_case(block_sdk=True)
        self.save(page, 'ads-unavailable')
        restarted = self.restart_from_offer(page)
        self.assertEqual(sdk_calls(page), [])
        self.record('disabled', offerText=offer_text(s), respawned=False,
                    restartWorks=restarted, showAdCalls=0)
        log('ASSERT SDK blocked: "Ads unavailable", no Watch ad, Restart works: pass')

    def test_e_init_reject_ads_unavailable(self):
        page, _ = self.disabled_case(fake={'initReject': True})
        self.restart_from_offer(page)
        self.assertEqual(show_ads(page), 0)
        log('ASSERT init rejected: "Ads unavailable", Restart works, no showAd: pass')

    def test_e_ready_never_ads_unavailable(self):
        page, _ = self.disabled_case(fake={'readyNever': True})
        self.restart_from_offer(page)
        self.assertEqual(show_ads(page), 0)
        log('ASSERT never ready: "Ads unavailable", Restart works, no showAd: pass')

    def test_d_long_ad_outlives_request_watchdog(self):
        # A rewarded video longer than rewardTimeoutMs still pays out
        page = self.boot({'adDurationMs': 2500})
        page.evaluate('PLATFORM.rewardTimeoutMs = 800')
        self.kill(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=10000)
        s = self.state(page)
        self.assertEqual((s['respawns'], s['score'], s['adFailed']), (1, 6, False))
        log('ASSERT 2.5 s ad with an 0.8 s request watchdog -> respawn: pass')

    def test_f_input_during_ad_throws_no_grapnel(self):
        # Long ad (beyond rewardTimeoutMs): input rounds can take seconds on a loaded machine
        page = self.boot({'adDurationMs': 15000}, touch=True)
        self.kill(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('window.__y8Fake.calls.some(c => c.name == "beforeAd")')
        frozen = self.state(page)
        points = [(400, 300), (1500, 200), (960, 900)]
        for x, y in points:
            v = canvas_to_viewport(page, x, y)
            page.mouse.move(v['x'], v['y'])
            page.mouse.down()
            page.wait_for_timeout(30)
            s = self.state(page)
            self.assertFalse(s['grapnelThrown'])
            page.mouse.up()
            page.touchscreen.tap(round(v['x']), round(v['y']))
            page.wait_for_timeout(120)
            s = self.state(page)
            self.assertFalse(s['grapnelThrown'])
            self.assertTrue(s['adPending'])
            self.assertEqual((s['x'], s['y']), (frozen['x'], frozen['y']))
        page.wait_for_function('!continueOffer.visible', timeout=30000)
        self.assertEqual(show_ads(page), 1)
        log(f'ASSERT {len(points)} mousedowns + taps during ad: no grapnel, frozen: pass')


if __name__ == '__main__':
    unittest.main()
