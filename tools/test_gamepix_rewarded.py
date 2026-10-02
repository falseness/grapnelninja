"""Rewarded ad behind "Watch ad to continue" (TASK-082, GamePix port TASK-106).

Runs against the fake GamePix SDK (tools/fixtures/fake-gamepix-sdk.js);
window.__fakeGamePix.reward picks the outcome: 'success', 'fail' (resolves
{success: false}), 'never' (never settles; the PLATFORM.rewardPlayingTimeoutMs
watchdog ends it) or 'throw'. The ninja is pinned by the TASK-080 physics
wrapper; window.__respawns counts respawnNinja() calls and re-pins the ninja
at the respawn point, window.__ticks counts physics() calls.

Env: GAMEPIX_REWARDED_EVIDENCE_DIR receives calls/<case>.json,
screens/<state>.png, outcome-matrix.json and console/page-errors.log.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamepix_harness import (canvas_to_viewport, click_canvas, collect_errors, fire,
                             open_game, route_fake_sdk, sdk_calls, sdk_errors,
                             set_fake_config, start_gamepix_test)
import test_continue as continue_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
WATCH_LABEL = 'Watch ad to continue'
RESTART_LABEL = 'Restart'
AD_ERROR = 'Ad unavailable'
ADS_UNAVAILABLE = 'Ads unavailable'
# Watchdog for the 'never' outcome, set on PLATFORM before the ad starts
WATCHDOG_MS = 1500

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


def reward_ads(page):
    return call_names(page).count('rewardAd')


def offer_text(s):
    """What the offer shows in the watch button's place."""
    return WATCH_LABEL if s['watchVisible'] else s['notice']


# Fake the Page Visibility API state and fire visibilitychange
SET_VISIBILITY = '''(state) => {
    Object.defineProperty(document, 'visibilityState',
        {configurable: true, get: () => state})
    Object.defineProperty(document, 'hidden',
        {configurable: true, get: () => state === 'hidden'})
    document.dispatchEvent(new Event('visibilitychange'))
}'''
PORTRAIT = {'width': 390, 'height': 844}
SMALL = {'width': 800, 'height': 450}

LABELS = '''() => ({watch: continueOffer.continueButton.text.text,
    restart: continueOffer.restartButton.text.text})'''


class GamePixRewardedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_gamepix_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('GAMEPIX_REWARDED_EVIDENCE_DIR')
        cls.errors = []
        cls.matrix = {}
        cls.edges = {}

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
            if cls.edges:
                (out / 'edge-matrix.json').write_text(json.dumps(
                    [cls.edges[k] for k in sorted(cls.edges)], indent=1) + '\n')

    def boot(self, fake=None, block_sdk=False, touch=False, viewport=VIEWPORT):
        if touch:
            context = self.browser.new_context(viewport=viewport, has_touch=True)
            route_fake_sdk(context)
            set_fake_config(context, fake)
            page = context.new_page()
            errors = collect_errors(page)
            page.goto(self.url + 'index.html')
        else:
            context, page, errors = open_game(self.browser, self.url + 'index.html',
                                              viewport, fake, block_sdk)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        if not block_sdk:
            self.addCleanup(lambda: self.assertEqual(sdk_errors(page), []))
        page.wait_for_function('PLATFORM.environment !== "pending" && menu.visible',
                               timeout=10000)
        expected = 'disabled' if block_sdk else 'gamepix'
        self.assertEqual(page.evaluate('PLATFORM.environment'), expected)
        page.evaluate(continue_test.INSTRUMENT_RUN)
        page.evaluate(INSTRUMENT_RESPAWN)
        page.evaluate('''() => {
            const b = menu.classicVersionButton.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
        }''')
        page.wait_for_timeout(300)
        self.context = context
        return page

    def state(self, page):
        return page.evaluate(STATE)

    def kill(self, page, score=6, offer=True):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(150)
        self.assertEqual(self.state(page)['offer'], offer)

    def assert_offer(self, page, watch=True):
        """The offer says what the ad gives and Restart is clickable (skippable)."""
        s = self.state(page)
        self.assertEqual(page.evaluate(LABELS),
                         {'watch': WATCH_LABEL, 'restart': RESTART_LABEL})
        self.assertTrue(s['offer'] and s['restartClickable'])
        self.assertEqual((s['watchVisible'], s['watchClickable']), (watch, watch))
        return s

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
        page = self.boot({'reward': outcome})
        if outcome == 'never':
            page.evaluate(f'PLATFORM.rewardPlayingTimeoutMs = {WATCHDOG_MS}')
        self.kill(page)
        before = self.assert_offer(page)
        self.click_button(page, 'continueButton')
        t0 = page.evaluate('performance.now()')
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        waited = page.evaluate('performance.now()') - t0
        self.wait_input(page)
        s = self.assert_no_reward(page, before)
        self.save(page, f'ad-error-{outcome}')
        # A click on the old watch button spot does nothing
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        self.assertEqual((self.state(page)['respawns'], reward_ads(page)), (0, 1))
        restarted = self.restart_from_offer(page)
        self.save_calls(page, outcome)
        self.record(outcome, offerText=offer_text(before), visibleResult=offer_text(s),
                    respawned=False, scoreKept=s['score'] == before['score'],
                    restartWorks=restarted, rewardAdCalls=reward_ads(page))
        log(f'ASSERT {outcome}: "{s["notice"]}" after {waited:.0f} ms, no respawn, '
            f'score {s["score"]} kept, Restart -> score 0: pass')
        return waited

    def test_a_success_continues(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 3000})
        self.kill(page)
        self.save(page, 'offer')
        before = self.assert_offer(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('window.__fakeGamePix.calls.some(c => c.name == "rewardAd")')
        page.wait_for_timeout(100)
        during = self.state(page)
        self.assertTrue(during['offer'] and during['adPending'])
        self.assertFalse(during['watchClickable'] or during['restartClickable'])
        self.assertEqual((during['x'], during['y'], during['respawns']),
                         (before['x'], before['y'], 0))
        self.save(page, 'ad-pending')
        page.wait_for_function('!continueOffer.visible', timeout=30000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.save(page, 'after-respawn')
        self.save_calls(page, 'success')
        self.assertEqual(reward_ads(page), 1)
        self.assertEqual((after['respawns'], after['continueUsed'], after['score'],
                          after['reStarts'], after['version'], after['floors']),
                         (1, True, 6, 0, before['version'], before['floors']))
        self.assertTrue(after['invulnerable'])
        # Gameplay resumes: physics ticks run on behind no offer
        page.wait_for_function(f'window.__ticks > {after["ticks"]} + 5')
        self.record('success', offerText=offer_text(before),
                    visibleResult='offer hidden, safe respawn (invulnerable), score kept',
                    respawned=True, scoreKept=after['score'] == before['score'],
                    rewardAdCalls=reward_ads(page))
        log('ASSERT success: rewardAd x1, respawns 1, score 6, invulnerable, resumed: pass')

    def test_b_fail(self):
        self.no_reward_case('fail')

    def test_b_never_hits_watchdog(self):
        waited = self.no_reward_case('never')
        self.assertGreater(waited, WATCHDOG_MS - 100)

    def test_b_throw(self):
        self.no_reward_case('throw')

    def test_c_double_click_requests_one_ad(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 3000})
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
        self.assertEqual(reward_ads(page), 1)
        self.assertEqual(self.state(page)['respawns'], 1)
        log(f'ASSERT 5 Watch clicks -> rewardAd x{reward_ads(page)}: pass')

    def test_d_second_death_after_continue_restarts(self):
        page = self.boot({'reward': 'success'})
        self.kill(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=30000)
        self.assertEqual(self.state(page)['respawns'], 1)
        page.wait_for_function('!ninja.isInvulnerable()', timeout=30000)
        self.kill(page, 9, offer=False)
        s = self.state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                         (False, 1, 0, False))
        self.assertEqual(reward_ads(page), 1)
        self.record('success', restartWorks=True)
        log('ASSERT second lethal death after continue -> instant restart, no offer: pass')

    def test_d_late_reward_after_watchdog_is_ignored(self):
        # The ad outlives the watchdog: {success: true} arrives after the error
        page = self.boot({'reward': 'success', 'rewardDelayMs': 2500})
        page.evaluate('PLATFORM.rewardPlayingTimeoutMs = 800')
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        page.wait_for_timeout(2500)
        self.assert_no_reward(page, before)
        self.restart_from_offer(page)
        log('ASSERT success after the watchdog error: no respawn, Restart works: pass')

    def test_e_sdk_blocked_ads_unavailable(self):
        page = self.boot(block_sdk=True)
        self.kill(page)
        s = self.assert_offer(page, watch=False)
        self.assertEqual(s['notice'], ADS_UNAVAILABLE)
        self.save(page, 'ads-unavailable')
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        s2 = self.state(page)
        self.assertEqual((s2['respawns'], s2['offer']), (0, True))
        restarted = self.restart_from_offer(page)
        self.assertEqual(sdk_calls(page), [])
        self.record('blocked', offerText=offer_text(s), visibleResult=s['notice'],
                    respawned=False, scoreKept=True, restartWorks=restarted,
                    rewardAdCalls=0)
        log('ASSERT SDK blocked: "Ads unavailable", no Watch ad, Restart works: pass')

    def test_f_input_during_ad_throws_no_grapnel(self):
        # Long ad: input rounds can take seconds on a loaded machine
        page = self.boot({'reward': 'success', 'rewardDelayMs': 15000}, touch=True)
        self.kill(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('window.__fakeGamePix.calls.some(c => c.name == "rewardAd")')
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
        self.assertEqual(reward_ads(page), 1)
        log(f'ASSERT {len(points)} mousedowns + taps during ad: no grapnel, frozen: pass')


    # Edge cases (TASK-107). Every boot() asserts no console/page errors and
    # an empty window.__fakeGamePix.errors list in cleanup.

    def edge(self, case, expected, observed):
        self.edges[case] = {'case': case, 'test': self._testMethodName,
                            'expected': expected, 'observed': observed}

    def watch(self, page):
        """Click Watch ad and wait until GamePix.rewardAd was called."""
        self.click_button(page, 'continueButton')
        page.wait_for_function(
            'window.__fakeGamePix.calls.some(c => c.name == "rewardAd")')

    def wait_respawn(self, page):
        page.wait_for_function('!continueOffer.visible', timeout=40000)
        page.wait_for_timeout(150)
        return self.state(page)

    def assert_plays_on(self, page, ms=1000):
        """The run keeps going: ticks advance, no restart, no offer."""
        ticks = self.state(page)['ticks']
        page.wait_for_timeout(ms)
        s = self.state(page)
        self.assertGreater(s['ticks'], ticks + 5)
        self.assertEqual((s['offer'], s['reStarts']), (False, 0))
        return s

    def test_g01_double_click_and_double_tap_one_ad(self):
        observed = {}
        for kind in ('dblclick', 'doubletap'):
            page = self.boot({'reward': 'success', 'rewardDelayMs': 1500},
                             touch=kind == 'doubletap')
            self.kill(page)
            c = self.center(page, 'continueButton')
            p = canvas_to_viewport(page, c['x'], c['y'])
            if kind == 'dblclick':
                page.mouse.dblclick(round(p['x']), round(p['y']))
            else:
                page.touchscreen.tap(round(p['x']), round(p['y']))
                page.touchscreen.tap(round(p['x']), round(p['y']))
            after = self.wait_respawn(page)
            observed[kind] = {'rewardAd': reward_ads(page), 'errors': sdk_errors(page),
                              'respawns': after['respawns']}
            self.assertEqual(observed[kind], {'rewardAd': 1, 'errors': [], 'respawns': 1})
        self.edge(1, 'rewardAd x1, fake errors [], respawns 1 for dblclick and double tap',
                  observed)
        log(f'ASSERT dblclick/double tap -> {observed}: pass')

    def test_g02_restart_during_pending_ad_no_respawn_into_new_run(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 1500})
        self.kill(page)
        self.watch(page)
        # The Restart button is disabled while the ad is pending
        self.click_button(page, 'restartButton')
        self.wait_input(page)
        s = self.state(page)
        self.assertEqual((s['offer'], s['adPending'], s['reStarts']), (True, True, 0))
        # Force a restart anyway (the offer's Restart callback)
        page.evaluate('restartFromOffer()')
        page.wait_for_timeout(2000)
        s = self.state(page)
        self.assertEqual((s['offer'], s['respawns'], s['reStarts'], s['score'],
                          s['continueUsed']), (False, 0, 1, 0, False))
        # The new run still gets its own working continue
        self.kill(page)
        self.assert_offer(page)
        self.click_button(page, 'continueButton')
        after = self.wait_respawn(page)
        self.assertEqual((after['respawns'], reward_ads(page)), (1, 2))
        self.edge(2, 'Restart click ignored while pending; forced restart -> late success '
                     'does not respawn; new run continue works',
                  {'clickIgnored': True, 'respawnsAfterLateSuccess': s['respawns'],
                   'newRunRespawns': after['respawns'], 'rewardAd': reward_ads(page)})
        log('ASSERT Restart during pending ad: late success ignored in the new run: pass')

    def test_g03_result_after_watchdog_ignored(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 2000})
        page.evaluate('PLATFORM.rewardPlayingTimeoutMs = 600')
        self.kill(page)
        before = self.state(page)
        self.watch(page)
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        page.wait_for_function('performance.now() - window.__fakeGamePix.calls'
                               '.find(c => c.name == "rewardAd").t > 2600')
        s = self.assert_no_reward(page, before)
        self.edge(3, 'watchdog -> "Ad unavailable"; later success ignored, no respawn',
                  {'notice': s['notice'], 'respawns': s['respawns'], 'offer': s['offer']})
        log('ASSERT result after watchdog ignored: pass')

    def test_g04_long_20s_ad_respawns(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 20000})
        self.kill(page)
        self.watch(page)
        page.wait_for_timeout(10000)
        self.assertTrue(self.state(page)['adPending'])
        after = self.wait_respawn(page)
        start = [c for c in sdk_calls(page) if c['name'] == 'rewardAd'][0]['t']
        took = page.evaluate('performance.now()') - start
        self.assertGreater(took, 19000)
        self.assertEqual((after['respawns'], after['score'], after['invulnerable']),
                         (1, 6, True))
        self.assert_plays_on(page, 500)
        self.edge(4, '20 s success -> respawn, score kept',
                  {'adMs': round(took), 'respawns': after['respawns'], 'score': after['score']})
        log(f'ASSERT 20 s ad ({took:.0f} ms) respawns: pass')

    def paused_after_ad(self, page, case, how):
        self.kill(page)
        self.watch(page)
        if how == 'hidden':
            page.evaluate(SET_VISIBILITY, 'hidden')
        else:
            fire(page, 'pause')
        after = self.wait_respawn(page)
        if how == 'hidden':
            page.evaluate(SET_VISIBILITY, 'visible')
        paused = page.evaluate('menu.gamePaused')
        self.save(page, f'paused-after-ad-{how}')
        self.assertTrue(paused, f'{how} during the ad: run not paused after the respawn')
        self.assertEqual(after['respawns'], 1)
        # Frozen behind the pause overlay
        inv = page.evaluate('ninja.invulnerableMs')
        page.wait_for_timeout(600)
        self.assertEqual(self.state(page)['ticks'], after['ticks'])
        self.assertEqual(page.evaluate('ninja.invulnerableMs'), inv)
        # Resume from the overlay: invulnerability left, no instant death
        page.evaluate('''() => { const b = menu.resume.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2}) }''')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        self.assertGreater(inv, 1500)
        s = self.assert_plays_on(page)
        self.edge(case, f'{how} during ad -> paused overlay after the ad, frozen, '
                        'resume -> no death',
                  {'pausedAfterAd': paused, 'invulnerableMsAtResume': inv,
                   'reStarts': s['reStarts'], 'respawns': s['respawns']})
        log(f'ASSERT {how} during ad -> paused after the ad, resume plays on: pass')

    def test_g05_hidden_during_ad_pauses_after(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 1500})
        self.paused_after_ad(page, 5, 'hidden')

    def test_g06_sdk_pause_during_ad_pauses_after(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 1500})
        self.paused_after_ad(page, 6, 'sdk-pause')

    def test_g07_resize_during_ad_respawn_safe(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 2000})
        self.kill(page)
        self.watch(page)
        rect = 'canvas.getBoundingClientRect().width'
        before = page.evaluate(rect)
        page.set_viewport_size(SMALL)
        # 1280x720 and 800x450 share 16:9: the logical width stays, the CSS size shrinks
        page.wait_for_function(f'{rect} < {before} && continueOffer.panel.width > 0',
                               timeout=5000)
        page.wait_for_timeout(300)
        after_css = page.evaluate(rect)
        self.assertTrue(self.state(page)['adPending'])
        after = self.wait_respawn(page)
        self.save(page, 'resize-during-ad')
        pos = page.evaluate('''() => ({x: ninja.x + screen.x, y: ninja.y + screen.y,
            width: width, height: height})''')
        self.assertTrue(0 < pos['x'] < pos['width'] and 0 < pos['y'] < pos['height'], pos)
        self.assertEqual((after['respawns'], after['invulnerable']), (1, True))
        self.assert_plays_on(page)
        self.edge(7, 'resize 1280x720 -> 800x450 during ad -> respawn on screen, '
                     'invulnerable, run goes on',
                  {'canvasCssWidth': [before, after_css], 'ninja': pos,
                   'respawns': after['respawns']})
        log(f'ASSERT resize during ad (CSS {before} -> {after_css}): safe respawn: pass')

    def test_g08_touch_portrait_cdp(self):
        page = self.boot({'reward': 'success', 'rewardDelayMs': 1000}, touch=True,
                         viewport=PORTRAIT)
        cdp = self.context.new_cdp_session(page)

        def tap(x, y, hold=40):
            """Touch for hold ms; return whether the grapnel was out meanwhile."""
            p = canvas_to_viewport(page, x, y)
            cdp.send('Input.dispatchTouchEvent', {
                'type': 'touchStart', 'touchPoints': [{'x': p['x'], 'y': p['y']}]})
            page.wait_for_timeout(hold)
            thrown = page.evaluate('grapnel.throwed')
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
            return thrown

        self.kill(page)
        c = self.center(page, 'continueButton')
        tap(c['x'], c['y'])
        after = self.wait_respawn(page)
        self.assertEqual((after['respawns'], reward_ads(page)), (1, 1))
        self.wait_input(page)
        self.save(page, 'respawn-after-touch')
        ticks, throws = after['ticks'], 0
        w = page.evaluate('width')
        for i in range(10):
            throws += tap(w * (0.3 + 0.05 * i), 300, hold=200)
            page.wait_for_timeout(100)
        s = self.state(page)
        self.assertGreater(s['ticks'], ticks + 60)
        self.assertGreater(throws, 0)
        self.assertEqual((s['offer'], s['reStarts'], s['respawns']), (False, 0, 1))
        self.edge(8, '390x844 CDP touch: Watch -> respawn, 3 s of taps play on',
                  {'respawns': s['respawns'], 'ticksPlayed': s['ticks'] - ticks,
                   'grapnelSeen': throws, 'reStarts': s['reStarts']})
        log(f'ASSERT portrait CDP touch: respawn + 3 s play ({throws} throws seen): pass')

    def test_g09_second_death_after_continue_rules(self):
        page = self.boot({'reward': 'success'})
        self.kill(page)
        self.assert_offer(page)
        self.click_button(page, 'continueButton')
        self.wait_respawn(page)
        page.wait_for_function('!ninja.isInvulnerable()', timeout=30000)
        # Continue used: the second lethal death restarts, no offer
        self.kill(page, 9, offer=False)
        s = self.state(page)
        self.assertEqual((s['reStarts'], s['score'], s['continueUsed']), (1, 0, False))
        # New run: below CONTINUE_MIN_SCORE -> restart; from it -> full offer
        self.kill(page, 2, offer=False)
        self.kill(page, 7)
        s = self.assert_offer(page)
        self.assertEqual(reward_ads(page), 1)
        self.edge(9, 'second death after continue -> restart, no offer; next run: '
                     'score 2 -> restart, score 7 -> Watch ad + Restart',
                  {'reStarts': page.evaluate('window.__reStarts'),
                   'labels': page.evaluate(LABELS), 'watchClickable': s['watchClickable'],
                   'restartClickable': s['restartClickable'], 'rewardAd': reward_ads(page)})
        log('ASSERT second death after continue follows the offer rules: pass')

    def test_g10_reward_ad_throws_synchronously(self):
        page = self.boot({'reward': 'throw'})
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        s = self.assert_no_reward(page, before)
        # Nothing stays in flight: the next run's ad request works
        self.restart_from_offer(page)
        page.evaluate('window.__fakeGamePix.reward = "success"')
        self.kill(page)
        self.click_button(page, 'continueButton')
        after = self.wait_respawn(page)
        self.assertEqual((after['respawns'], reward_ads(page)), (1, 2))
        self.edge(10, 'sync throw -> "Ad unavailable", Restart; next offer ad works',
                  {'notice': s['notice'], 'respawnsAfterThrow': s['respawns'],
                   'nextOfferRespawns': after['respawns'], 'rewardAd': reward_ads(page)})
        log('ASSERT rewardAd throws: Ad unavailable, nothing stuck: pass')

    def test_g11_fail_then_success_retry(self):
        page = self.boot({'reward': 'fail'})
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        self.wait_input(page)
        s = self.assert_no_reward(page, before)
        # The next answer is a success; the retry comes from the next offer
        # (the TASK-082 rule: a failed offer shows "Ad unavailable" + Restart)
        page.evaluate('window.__fakeGamePix.reward = "success"')
        self.restart_from_offer(page)
        self.kill(page)
        self.assert_offer(page)
        self.click_button(page, 'continueButton')
        after = self.wait_respawn(page)
        self.assertEqual((after['respawns'], after['score'], reward_ads(page)), (1, 6, 2))
        self.edge(11, "'fail' -> 'Ad unavailable' + Restart; retry with 'success' -> respawn",
                  {'failNotice': s['notice'], 'retryRespawns': after['respawns'],
                   'rewardAd': reward_ads(page)})
        log('ASSERT fail then success retry: pass')


if __name__ == '__main__':
    unittest.main()
