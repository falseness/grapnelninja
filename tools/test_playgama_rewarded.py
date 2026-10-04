"""Rewarded continue on the Playgama Bridge (TASK-122, ports test_y8_rewarded).

Runs against the fake Bridge (tools/fixtures/fake-playgama-bridge.js);
window.__fakeBridge.rewardedSeq scripts the rewarded states. The continue is
granted ONLY on 'rewarded'; 'closed' without it and 'failed' leave
'Ad unavailable' plus Restart. The ninja is pinned by test_continue's
INSTRUMENT_RUN; window.__respawns counts respawnNinja() calls.

Env: REWARDED_EVIDENCE_DIR receives outcome-matrix.json, calls/<case>.json,
screens/{1280x720,390x844}/<state>.png and no-reward-on-close.txt.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playgama_harness import (bridge_calls, bridge_errors, open_game,
                              start_playgama_test)
from test_audio_wiring import READY, SET_VISIBILITY, canvas_to_viewport
import test_continue as continue_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
PHONE = {'width': 390, 'height': 844}
AD_BADGE = 'AD'
REWARD_TEXT = 'Watch an ad to continue this run'
AD_ERROR = 'Ad unavailable'
ADS_UNAVAILABLE = 'Ads unavailable'
# The ad stays 'opened' long enough to act while it plays
SLOW_REWARD = ['loading', 'opened', {'state': 'rewarded', 'delayMs': 3000}, 'closed']

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
    notice: continueOffer.notice(), badge: continueOffer.adBadgeLabel,
    rewardText: continueOffer.rewardText.text, label: continueOffer.continueButton.text.text,
    invulnerable: ninja.isInvulnerable(), paused: menu.gamePaused, adOpen: adOpen,
    muted: AUDIO.getState().muted, grapnelThrown: grapnel.throwed,
    ticks: window.__ticks, version: version, floors: floors.length,
    x: ninja.x, y: ninja.y})'''

# Badge and reward text sit inside the panel, the badge inside the button,
# and the reward line fits the panel width
LAYOUT = '''() => {
    const o = continueOffer, b = o.continueButton.background, a = o.adBadge()
    ctx.save(); ctx.font = o.rewardText.fontSize
    const textWidth = ctx.measureText(o.rewardText.text).width; ctx.restore()
    return {badgeInButton: a.x >= b.x && a.y >= b.y && a.x + a.width <= b.x + b.width
                && a.y + a.height <= b.y + b.height,
            rewardFits: textWidth <= o.panel.width,
            rewardAboveButton: o.rewardText.y < b.y,
            badge: a, button: {x: b.x, y: b.y, width: b.width, height: b.height},
            rewardFontPx: parseFloat(o.rewardText.fontSize), textWidth: textWidth,
            panelWidth: o.panel.width}
}'''


def log(msg):
    print('  ' + msg, file=sys.stderr)


def call_names(page):
    return [c['name'] for c in bridge_calls(page)]


def show_rewarded(page):
    return call_names(page).count('advertisement.showRewarded')


class PlaygamaRewardedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('REWARDED_EVIDENCE_DIR')
        cls.matrix = {}

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'outcome-matrix.json').write_text(
                json.dumps(cls.matrix, indent=1, sort_keys=True) + '\n')

    def boot(self, seq=None, viewport=VIEWPORT, touch=False, block=False, fake=None):
        options = dict(fake or {})
        if seq is not None:
            options['rewardedSeq'] = seq
        if touch:
            # open_game has no touch option: the same routes on a touch context
            import playgama_harness as h
            context = self.browser.new_context(viewport=viewport, has_touch=True,
                                               is_mobile=True)
            context.route(h.BRIDGE_URL, lambda route: route.fulfill(
                path=str(h.FAKE_BRIDGE), content_type='application/javascript'))
            context.route(h.CONFIG_ROUTE, h.serve_config)
            context.add_init_script(f'window.__fakeBridge = {json.dumps(options)}')
            page = context.new_page()
            errors = h.collect_errors(page)
            page.goto(self.url + 'index.html')
        else:
            context, page, errors = open_game(self.browser, self.url + 'index.html',
                                              viewport, options, block)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        page.wait_for_function(READY, timeout=15000)
        self.assertEqual(page.evaluate('PLATFORM.environment'),
                         'disabled' if block else 'playgama')
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

    def point(self, page, name):
        c = page.evaluate(f'''(() => {{ const b = continueOffer.{name}.background
            return {{x: b.x + b.width / 2, y: b.y + b.height / 2}} }})()''')
        return canvas_to_viewport(page, c['x'], c['y'])

    def click_button(self, page, name):
        p = self.point(page, name)
        page.mouse.click(p['x'], p['y'])

    def wait_input(self, page):
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def wait_opened(self, page):
        page.wait_for_function('__fakeBridge.calls.some(c => c.name == "rewarded:opened")',
                               timeout=10000)
        page.wait_for_timeout(50)

    def save(self, page, name, size='1280x720'):
        if self.evidence:
            out = Path(self.evidence) / 'screens' / size
            out.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / f'{name}.png'))

    def save_calls(self, page, case):
        calls = bridge_calls(page)
        if self.evidence:
            out = Path(self.evidence) / 'calls'
            out.mkdir(parents=True, exist_ok=True)
            (out / f'{case}.json').write_text(json.dumps(calls, indent=1) + '\n')
        return calls

    def offer_state(self, s):
        if not s['offer']:
            return 'hidden'
        if s['watchVisible']:
            return 'watch (AD badge + reward text)'
        return s['notice']

    def record(self, case, expected, before, after, page, **extra):
        observed = {'respawned': after['respawns'] > 0,
                    'scoreKept': after['score'] == before['score'],
                    'score': after['score'], 'offerState': self.offer_state(after),
                    'showRewarded': show_rewarded(page)}
        observed.update(extra)
        self.matrix[case] = {'expected': expected, 'observed': observed,
                             'match': all(observed[k] == v for k, v in expected.items())}
        self.assertTrue(self.matrix[case]['match'], self.matrix[case])

    def assert_frozen_and_muted(self, page, before):
        """While the rewarded ad is open: paused, 'ad' muted, ninja still."""
        s = self.state(page)
        self.assertTrue(s['adOpen'] and s['adPending'] and s['offer'])
        self.assertTrue(s['muted']['ad'])
        self.assertFalse(s['watchClickable'] or s['restartClickable'])
        self.assertEqual((s['x'], s['y'], s['respawns']), (before['x'], before['y'], 0))
        return s

    def restart_from_offer(self, page):
        version = self.state(page)['version']
        self.click_button(page, 'restartButton')
        self.wait_input(page)
        s = self.state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed'],
                          s['version']), (False, 1, 0, False, version))
        page.wait_for_function(f'window.__ticks > {s["ticks"]} + 5')
        return True

    def no_reward_case(self, case, seq, timeout_ms=None, screen=None):
        page = self.boot(seq)
        if timeout_ms:
            page.evaluate(f'PLATFORM.rewardTimeoutMs = PLATFORM.rewardPlayingTimeoutMs = {timeout_ms}')
        self.kill(page)
        before = self.state(page)
        self.assertTrue(before['watchVisible'] and before['watchClickable'])
        self.click_button(page, 'continueButton')
        page.wait_for_function('continueOffer.adFailed', timeout=15000)
        self.wait_input(page)
        s = self.state(page)
        self.assertEqual((s['notice'], s['watchVisible'], s['watchClickable'],
                          s['restartClickable'], s['respawns'], s['adPending'], s['adOpen']),
                         (AD_ERROR, False, False, True, 0, False, False))
        self.assertFalse(s['muted']['ad'])
        self.assertEqual((s['x'], s['y'], s['score']), (before['x'], before['y'], before['score']))
        # The old watch spot does nothing; the ninja did not move on
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        again = self.state(page)
        self.assertEqual((again['respawns'], again['x'], again['y']), (0, before['x'], before['y']))
        self.record(case, {'respawned': False, 'scoreKept': True, 'offerState': AD_ERROR,
                           'showRewarded': 1}, before, again, page)
        self.save_calls(page, case)
        if screen:
            self.save(page, screen)
        self.matrix[case]['observed']['restartWorks'] = self.restart_from_offer(page)
        return page, before, again

    # Outcomes

    def test_a_rewarded_continues(self):
        page = self.boot(SLOW_REWARD)
        self.kill(page)
        self.save(page, 'offer')
        before = self.state(page)
        self.assertEqual((before['badge'], before['rewardText'], before['label']),
                         (AD_BADGE, REWARD_TEXT, 'Continue'))
        layout = page.evaluate(LAYOUT)
        self.assertTrue(layout['badgeInButton'] and layout['rewardFits']
                        and layout['rewardAboveButton'], layout)
        self.click_button(page, 'continueButton')
        self.wait_opened(page)
        self.assert_frozen_and_muted(page, before)
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        page.wait_for_timeout(150)
        after = self.state(page)
        calls = self.save_calls(page, 'rewarded')
        show = next(c for c in calls if c['name'] == 'advertisement.showRewarded')
        self.assertEqual(show['args'], ['continue'])
        self.assertEqual((after['respawns'], after['continueUsed'], after['score'],
                          after['reStarts'], after['version'], after['floors']),
                         (1, True, 6, 0, before['version'], before['floors']))
        self.assertTrue(after['invulnerable'])
        self.assertFalse(after['muted']['ad'] or after['adOpen'] or after['paused'])
        page.wait_for_function(f'window.__ticks > {after["ticks"]} + 5')
        self.record('rewarded', {'respawned': True, 'scoreKept': True,
                                 'offerState': 'hidden', 'showRewarded': 1},
                    before, after, page, layout=layout)
        log('ASSERT rewarded: AD badge + reward text, frozen+muted while open,'
            ' respawn, score 6 kept: pass')

    def test_b_failed(self):
        page, _, _ = self.no_reward_case('failed', ['loading', 'failed'])
        log('ASSERT failed: Ad unavailable, no respawn, Restart works: pass')

    def test_b_closed_without_reward(self):
        page, before, after = self.no_reward_case(
            'closedWithoutReward', ['loading', 'opened', {'state': 'closed', 'delayMs': 400}],
            screen='ad-unavailable')
        self.assertIn('rewarded:closed', call_names(page))
        self.assertNotIn('rewarded:rewarded', call_names(page))
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'no-reward-on-close.txt').write_text(
                'case: rewarded ad opened then closed without a rewarded state\n'
                f'states: {[n for n in call_names(page) if n.startswith("rewarded:")]}\n'
                f'respawned={after["respawns"] > 0}\n'
                f'respawns={after["respawns"]}\n'
                f'score_before={before["score"]} score_on_offer={after["score"]}\n'
                f'ninja_before=({before["x"]:.2f}, {before["y"]:.2f}) '
                f'ninja_after=({after["x"]:.2f}, {after["y"]:.2f})\n'
                f'score_continued={after["respawns"] > 0}\n'
                f'offer_notice={after["notice"]!r} watch_visible={after["watchVisible"]}\n'
                f'restart_works={self.matrix["closedWithoutReward"]["observed"]["restartWorks"]}\n')
        log('ASSERT closed without reward: no respawn, Ad unavailable, Restart: pass')

    def test_b_never_settles_watchdog(self):
        page, _, _ = self.no_reward_case('neverSettles', ['loading'], timeout_ms=1200)
        log('ASSERT never settles: watchdog -> Ad unavailable, Restart works: pass')

    def test_c_double_click_one_ad(self):
        page = self.boot(SLOW_REWARD)
        untouch = page.evaluate('STYLE.timing.inputUntouchMs')
        self.kill(page)
        before = self.state(page)
        p = self.point(page, 'continueButton')
        for i in range(5):
            page.mouse.click(round(p['x']), round(p['y']))
            if i >= 1:
                page.wait_for_timeout(untouch + 20)
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        page.wait_for_timeout(150)
        self.save_calls(page, 'doubleClick')
        after = self.state(page)
        self.assertEqual((show_rewarded(page), after['respawns']), (1, 1))
        self.record('doubleClick', {'respawned': True, 'scoreKept': True,
                                    'offerState': 'hidden', 'showRewarded': 1},
                    before, after, page, clicks=5)
        log('ASSERT 5 Watch clicks -> showRewarded x1, one respawn: pass')

    def test_d_restart_during_pending_ignored(self):
        page = self.boot(SLOW_REWARD)
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        self.wait_opened(page)
        self.click_button(page, 'restartButton')
        self.wait_input(page)
        during = self.assert_frozen_and_muted(page, before)
        self.assertEqual((during['reStarts'], during['score']), (0, 6))
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.assertEqual((after['reStarts'], after['respawns']), (0, 1))
        self.record('restartDuringPending', {'respawned': True, 'scoreKept': True,
                                             'offerState': 'hidden', 'showRewarded': 1},
                    before, after, page, restartsDuringAd=during['reStarts'])
        log('ASSERT Restart click while the ad is open is ignored, reward respawns: pass')

    # Interruptions while the ad plays

    def test_e_hidden_during_ad(self):
        page = self.boot(SLOW_REWARD)
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        self.wait_opened(page)
        page.evaluate(SET_VISIBILITY, 'hidden')
        during = self.assert_frozen_and_muted(page, before)
        self.assertTrue(during['muted']['hidden'])
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.assertTrue(after['paused'])
        self.assertTrue(after['muted']['hidden'])
        page.evaluate(SET_VISIBILITY, 'visible')
        page.wait_for_timeout(100)
        self.assertTrue(self.state(page)['paused'])
        self.record('hiddenDuringAd', {'respawned': True, 'scoreKept': True,
                                       'offerState': 'hidden', 'showRewarded': 1},
                    before, after, page, pausedAfterRespawn=after['paused'])
        log('ASSERT hidden during ad: muted, respawn lands paused: pass')

    def test_e_host_pause_during_ad(self):
        page = self.boot(SLOW_REWARD)
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        self.wait_opened(page)
        page.evaluate('__fakeBridge.fire("PAUSE_STATE_CHANGED", true)')
        self.assert_frozen_and_muted(page, before)
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.assertTrue(after['paused'])
        page.wait_for_timeout(300)
        self.assertEqual(self.state(page)['x'], after['x'])
        self.record('hostPauseDuringAd', {'respawned': True, 'scoreKept': True,
                                          'offerState': 'hidden', 'showRewarded': 1},
                    before, after, page, pausedAfterRespawn=after['paused'])
        log('ASSERT host pause during ad: respawn lands paused: pass')

    def test_e_resize_during_ad(self):
        page = self.boot(SLOW_REWARD)
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        self.wait_opened(page)
        page.set_viewport_size({'width': 900, 'height': 600})
        page.wait_for_timeout(200)
        during = self.state(page)
        self.assertTrue(during['adPending'] and during['offer'] and during['muted']['ad'])
        self.assertFalse(during['watchClickable'] or during['restartClickable'])
        self.assertEqual(during['respawns'], 0)
        layout = page.evaluate(LAYOUT)
        self.assertTrue(layout['badgeInButton'] and layout['rewardFits'], layout)
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.record('resizeDuringAd', {'respawned': True, 'scoreKept': True,
                                       'offerState': 'hidden', 'showRewarded': 1},
                    before, after, page)
        log('ASSERT resize during ad: still pending+locked, then respawn: pass')

    def test_f_phone_touch(self):
        page = self.boot(SLOW_REWARD, viewport=PHONE, touch=True)
        self.kill(page)
        self.save(page, 'offer', '390x844')
        before = self.state(page)
        layout = page.evaluate(LAYOUT)
        self.assertTrue(layout['badgeInButton'] and layout['rewardFits']
                        and layout['rewardAboveButton'], layout)
        p = self.point(page, 'continueButton')
        page.touchscreen.tap(round(p['x']), round(p['y']))
        page.touchscreen.tap(round(p['x']), round(p['y']))
        self.wait_opened(page)
        self.assert_frozen_and_muted(page, before)
        # Taps on the game field while the ad is open throw nothing
        page.touchscreen.tap(195, 300)
        page.wait_for_timeout(100)
        self.assertFalse(self.state(page)['grapnelThrown'])
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.save_calls(page, 'phoneTouch')
        self.record('phoneTouch390x844', {'respawned': True, 'scoreKept': True,
                                          'offerState': 'hidden', 'showRewarded': 1},
                    before, after, page, layout=layout)
        log('ASSERT 390x844 touch: double tap -> 1 showRewarded, respawn: pass')

    def test_f_phone_ad_unavailable_screen(self):
        page = self.boot(['loading', 'failed'], viewport=PHONE, touch=True)
        self.kill(page)
        p = self.point(page, 'continueButton')
        page.touchscreen.tap(round(p['x']), round(p['y']))
        page.wait_for_function('continueOffer.adFailed', timeout=10000)
        page.wait_for_timeout(100)
        self.save(page, 'ad-unavailable', '390x844')
        self.assertEqual(self.state(page)['notice'], AD_ERROR)

    # Once per run

    def test_g_second_death_no_offer(self):
        page = self.boot()
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=15000)
        self.assertEqual(self.state(page)['respawns'], 1)
        page.wait_for_function('!ninja.isInvulnerable()', timeout=30000)
        self.kill(page, 9, offer=False)
        after = self.state(page)
        self.assertEqual((after['offer'], after['reStarts'], after['score'],
                          after['continueUsed']), (False, 1, 0, False))
        self.matrix['secondDeath'] = {
            'expected': {'offerState': 'hidden', 'restarted': True, 'showRewarded': 1},
            'observed': {'offerState': self.offer_state(after), 'restarted': after['reStarts'] == 1,
                         'respawned': after['respawns'] > 1, 'score': after['score'],
                         'scoreKept': False, 'showRewarded': show_rewarded(page)}}
        m = self.matrix['secondDeath']
        m['match'] = all(m['observed'][k] == v for k, v in m['expected'].items())
        self.assertTrue(m['match'], m)
        log('ASSERT second death in the same run: no offer, instant restart: pass')

    def test_h_bridge_blocked_ads_unavailable(self):
        page = self.boot(block=True)
        self.kill(page)
        before = self.state(page)
        self.assertEqual((before['watchVisible'], before['notice']), (False, ADS_UNAVAILABLE))
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        after = self.state(page)
        self.record('bridgeBlocked', {'respawned': False, 'scoreKept': True,
                                      'offerState': ADS_UNAVAILABLE, 'showRewarded': 0},
                    before, after, page)
        self.restart_from_offer(page)


if __name__ == '__main__':
    unittest.main()
