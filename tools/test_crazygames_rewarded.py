"""Rewarded ad behind "Watch ad to continue" (TASK-082).

Runs against the fake SDK (tools/fixtures/fake-crazygames-sdk.js). The ninja
is pinned by the TASK-080 physics wrapper; window.__respawns counts
respawnNinja() calls and re-pins the ninja at the respawn point.

Env: CG_REWARDED_EVIDENCE_DIR receives calls/<case>.json, screens/<state>.png
and console/page-errors.log.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import SDK_ROUTE
from crazygames_harness import (FAKE_SDK, canvas_to_viewport, click_canvas, collect_errors,
                                open_game, sdk_calls, start_crazygames_test)
import test_crazygames_continue as continue_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
START, STOP = 'game.gameplayStart', 'game.gameplayStop'
FLOW = (START, STOP, 'ad.requestAd', 'ad.adStarted', 'ad.adFinished', 'ad.adError')

INSTRUMENT_RESPAWN = '''() => {
    window.__respawns = 0
    const original = window.respawnNinja
    window.respawnNinja = function() {
        const result = original.apply(this, arguments)
        window.__respawns++
        window.__pin = {x: ninja.x, y: ninja.y}
        return result
    }
}'''

STATE = '''() => ({offer: continueOffer.visible, score: scoreText.count[version],
    reStarts: window.__reStarts, respawns: window.__respawns, continueUsed: continueUsed,
    adPending: continueOffer.adPending, watchVisible: continueOffer.watchVisible(),
    watchClickable: continueOffer.continueButton.clickable,
    restartClickable: continueOffer.restartButton.clickable,
    notice: continueOffer.notice(), invulnerable: ninja.isInvulnerable(),
    grapnelThrown: grapnel.throwed, grapnelPos: grapnel.pos.length,
    x: ninja.x, y: ninja.y})'''


def log(msg):
    print('  ' + msg, file=sys.stderr)


def flow(page):
    return [c['name'] for c in sdk_calls(page) if c['name'] in FLOW]


class CrazyGamesRewardedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_crazygames_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('CG_REWARDED_EVIDENCE_DIR')
        cls.errors = []

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

    def boot(self, fake=None, block_sdk=False, touch=False):
        if touch:
            context = self.browser.new_context(viewport=VIEWPORT, has_touch=True)
            context.route(SDK_ROUTE, lambda route: route.fulfill(
                path=str(FAKE_SDK), content_type='application/javascript'))
            context.add_init_script(f'window.__cgFake = {json.dumps(fake or {})}')
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
        page.wait_for_function('CG.environment !== "pending" && menu.visible')
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

    def kill(self, page, score=6):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(150)
        self.assertTrue(self.state(page)['offer'])

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

    def test_a_ad_finished_continues(self):
        page = self.boot({'adDurationMs': 8000})
        self.kill(page)
        self.save(page, 'offer')
        before = self.state(page)
        self.assertTrue(before['watchVisible'] and before['watchClickable'])
        self.click_button(page, 'continueButton')
        page.wait_for_function('window.__cgFake.calls.some(c => c.name == "ad.adStarted")')
        page.wait_for_timeout(100)
        during = self.state(page)
        self.assertTrue(during['offer'] and during['adPending'])
        self.assertFalse(during['watchClickable'] or during['restartClickable'])
        self.assertEqual((during['x'], during['y'], during['respawns']),
                         (before['x'], before['y'], 0))
        self.save(page, 'during-ad')
        self.assertFalse(page.evaluate('window.__cgFake.calls.some(c => c.name == "ad.adFinished")'),
                         'during-ad screenshot taken after adFinished')
        page.wait_for_function('!continueOffer.visible', timeout=30000)
        page.wait_for_timeout(150)
        after = self.state(page)
        self.save(page, 'after-finished')
        calls = self.save_calls(page, 'finished')
        names = flow(page)
        self.assertEqual(names, [START, STOP, 'ad.requestAd', 'ad.adStarted',
                                 'ad.adFinished', START])
        request = next(c for c in calls if c['name'] == 'ad.requestAd')
        self.assertEqual(request['args'][0], 'rewarded')
        finished_t = next(c['t'] for c in calls if c['name'] == 'ad.adFinished')
        self.assertGreater([c['t'] for c in calls if c['name'] == START][-1], finished_t)
        self.assertEqual((after['respawns'], after['continueUsed'], after['score'],
                          after['reStarts']), (1, True, 6, 0))
        self.assertTrue(after['invulnerable'])
        log(f'ASSERT (a) finished: {names}; respawns 1, score 6, invulnerable: pass')

    def test_b_ad_error_keeps_score_and_restart(self):
        page = self.boot({'adOutcome': 'error'})
        self.kill(page)
        before = self.state(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('window.__cgFake.calls.some(c => c.name == "ad.adError")')
        self.wait_input(page)
        s = self.state(page)
        self.assertTrue(s['offer'])
        self.assertEqual((s['notice'], s['watchVisible'], s['watchClickable'],
                          s['restartClickable'], s['respawns'], s['score']),
                         ('Ad unavailable', False, False, True, 0, 6))
        self.assertEqual((s['x'], s['y']), (before['x'], before['y']))
        self.save(page, 'error')
        # A click on the old watch button spot does nothing
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        self.assertEqual(self.state(page)['respawns'], 0)
        self.click_button(page, 'restartButton')
        self.wait_input(page)
        s = self.state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                         (False, 1, 0, False))
        names = flow(page)
        self.save_calls(page, 'error')
        self.assertEqual(names, [START, STOP, 'ad.requestAd', 'ad.adError', START])
        log(f'ASSERT (b) error: {names}; no respawn, score 6 kept, "Ad unavailable",'
            ' Restart works: pass')

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
        names = flow(page)
        self.save_calls(page, 'doubleclick')
        self.assertEqual(names.count('ad.requestAd'), 1)
        self.assertEqual(names, [START, STOP, 'ad.requestAd', 'ad.adStarted',
                                 'ad.adFinished', START])
        self.assertEqual(self.state(page)['respawns'], 1)
        log(f'ASSERT (c) 5 Watch clicks -> requestAd x{names.count("ad.requestAd")}: pass')

    def test_d_adblock_hides_watch(self):
        page = self.boot({'adblock': True})
        page.wait_for_function('window.__cgFake.calls.some(c => c.name == "ad.hasAdblock")')
        self.kill(page)
        s = self.state(page)
        self.assertEqual((s['watchVisible'], s['watchClickable'], s['notice']),
                         (False, False, 'Ads unavailable'))
        self.save(page, 'adblock')
        self.click_button(page, 'continueButton')
        self.wait_input(page)
        self.click_button(page, 'restartButton')
        self.wait_input(page)
        s = self.state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score']), (False, 1, 0))
        names = flow(page)
        self.save_calls(page, 'adblock')
        self.assertNotIn('ad.requestAd', names)
        self.assertEqual(names, [START, STOP, START])
        log(f'ASSERT (d) adblock: no watch button, "Ads unavailable", Restart works {names}: pass')

    def test_e_blocked_sdk_hides_watch(self):
        page = self.boot(block_sdk=True)
        self.assertEqual(page.evaluate('CG.environment'), 'disabled')
        self.kill(page)
        s = self.state(page)
        self.assertEqual((s['watchVisible'], s['watchClickable'], s['notice']),
                         (False, False, 'Ads unavailable'))
        self.click_button(page, 'restartButton')
        self.wait_input(page)
        s = self.state(page)
        self.assertEqual((s['offer'], s['reStarts'], s['score']), (False, 1, 0))
        self.assertEqual(sdk_calls(page), [])
        log('ASSERT (e) block_sdk: no watch button, Restart works, no page errors: pass')

    def test_f_input_during_ad_throws_no_grapnel(self):
        # Long ad: input rounds can take seconds on a loaded machine
        page = self.boot({'adDurationMs': 15000}, touch=True)
        self.kill(page)
        self.click_button(page, 'continueButton')
        page.wait_for_function('window.__cgFake.calls.some(c => c.name == "ad.adStarted")')
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
        self.assertEqual(flow(page).count('ad.requestAd'), 1)
        log(f'ASSERT (f) {len(points)} mousedowns + taps during ad: no grapnel, frozen: pass')


if __name__ == '__main__':
    unittest.main()
