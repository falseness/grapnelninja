"""Game over interstitial on the Playgama Bridge (TASK-123).

Runs against the fake Bridge (tools/fixtures/fake-playgama-bridge.js);
window.__fakeBridge.interstitialSeq scripts the interstitial states. Leaving
a run that ended in a death (instant restart, Restart on the continue offer,
Menu via pause after a death) calls showInterstitial('game_over') and waits
for it; a respawn by the rewarded continue, a run in progress and the first
run of the session never do. The game skips its own interstitial within
PLATFORM.interstitialMinGapMs of the last one; PLATFORM.now is replaced by a
fake clock to cross that gap.

Env: INTERSTITIAL_EVIDENCE_DIR receives calls.json (the 3-death session).
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playgama_harness import (bridge_calls, bridge_errors, open_game,
                              start_playgama_test)
from test_audio_wiring import READY, canvas_to_viewport
import test_continue as continue_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
# The interstitial stays 'opened' long enough to act while it plays
SLOW_AD = ['loading', 'opened', {'state': 'closed', 'delayMs': 3000}]
FAKE_CLOCK = '''() => { window.__clock = 0; PLATFORM.now = () => window.__clock }'''
TICKS = '''() => {
    window.__ticks = 0
    const physicsStep = window.physics
    window.physics = function() {
        window.__ticks++
        return physicsStep.apply(this, arguments)
    }
}'''
STATE = '''() => ({offer: continueOffer.visible, menu: menu.visible,
    paused: menu.gamePaused, reStarts: window.__reStarts, score: scoreText.count[version],
    pending: interstitialPending, runOver: runOver, adOpen: adOpen,
    muted: AUDIO.getState().muted, grapnelThrown: grapnel ? grapnel.throwed : false,
    ticks: window.__ticks, continueUsed: continueUsed})'''


def log(msg):
    print('  ' + msg, file=sys.stderr)


def interstitials(page):
    return [c for c in bridge_calls(page) if c['name'] == 'advertisement.showInterstitial']


class PlaygamaInterstitialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('INTERSTITIAL_EVIDENCE_DIR')

    def boot(self, seq=None, start=True):
        options = {}
        if seq is not None:
            options['interstitialSeq'] = seq
        context, page, errors = open_game(self.browser, self.url + 'index.html',
                                          VIEWPORT, options)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        page.wait_for_function(READY, timeout=15000)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'playgama')
        page.evaluate(continue_test.INSTRUMENT_RUN)
        page.evaluate(TICKS)
        if start:
            self.start_run(page)
        return page

    def start_run(self, page):
        self.click_canvas(page, 'menu.classicVersionButton')
        page.wait_for_timeout(300)
        self.assertFalse(self.state(page)['menu'])

    def state(self, page):
        return page.evaluate(STATE)

    def wait_input(self, page):
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def click_canvas(self, page, path, scaled=False):
        c = page.evaluate(f'''(() => {{ const b = {path}.background
            const s = {'scale[version]' if scaled else '1'}
            return {{x: (b.x + b.width / 2) * s, y: (b.y + b.height / 2) * s}} }})()''')
        p = canvas_to_viewport(page, c['x'], c['y'])
        page.mouse.click(p['x'], p['y'])
        self.wait_input(page)

    def kill(self, page, score):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(50)

    def wait_opened(self, page, n=1):
        page.wait_for_function(
            f'__fakeBridge.calls.filter(c => c.name == "interstitial:opened").length >= {n}',
            timeout=10000)
        page.wait_for_timeout(50)

    def wait_settled(self, page):
        page.wait_for_function('!interstitialPending', timeout=10000)
        page.wait_for_timeout(150)

    def pause_to_menu(self, page):
        """HUD menu button -> pause -> back to menu."""
        self.click_canvas(page, 'menu.button', scaled=True)
        self.assertTrue(self.state(page)['paused'])
        self.click_canvas(page, 'menu.backToMenu')

    # Where it is shown

    def test_a_restart_after_death(self):
        page = self.boot(SLOW_AD)
        self.kill(page, 6)
        self.assertTrue(self.state(page)['offer'])
        self.assertEqual(interstitials(page), [])
        self.click_canvas(page, 'continueOffer.restartButton')
        self.wait_opened(page)
        s = self.state(page)
        self.assertEqual((s['pending'], s['adOpen'], s['reStarts'], s['offer']),
                         (True, True, 0, True))
        self.wait_settled(page)
        s = self.state(page)
        self.assertEqual((s['reStarts'], s['offer'], s['score'], s['pending']), (1, False, 0, False))
        self.assertEqual([c['args'] for c in interstitials(page)], [['game_over']])
        log('ASSERT Restart on the continue offer -> showInterstitial(game_over), run waits: pass')

    def test_a_instant_restart_after_death(self):
        page = self.boot(SLOW_AD)
        self.kill(page, 0)
        self.wait_opened(page)
        self.assertEqual(self.state(page)['reStarts'], 0)
        self.wait_settled(page)
        self.assertEqual(self.state(page)['reStarts'], 1)
        self.assertEqual(len(interstitials(page)), 1)
        log('ASSERT death below the continue score -> interstitial, then restart: pass')

    def test_b_menu_after_death(self):
        page = self.boot(SLOW_AD)
        self.kill(page, 6)
        self.assertTrue(self.state(page)['offer'])
        self.pause_to_menu(page)
        self.wait_opened(page)
        s = self.state(page)
        self.assertEqual((s['menu'], s['pending']), (False, True))
        self.wait_settled(page)
        s = self.state(page)
        self.assertEqual((s['menu'], s['paused'], s['offer'], s['reStarts']),
                         (True, False, False, 0))
        self.assertEqual([c['args'] for c in interstitials(page)], [['game_over']])
        log('ASSERT Menu after a death -> interstitial, then the menu: pass')

    # Where it is not

    def test_c_not_on_first_launch(self):
        page = self.boot(start=False)
        page.wait_for_timeout(300)
        self.start_run(page)
        page.wait_for_timeout(500)
        self.assertEqual(interstitials(page), [])
        log('ASSERT no interstitial before or at the first run: pass')

    def test_c_not_mid_run(self):
        page = self.boot()
        page.wait_for_timeout(300)
        self.pause_to_menu(page)
        page.wait_for_timeout(300)
        self.assertTrue(self.state(page)['menu'])
        self.start_run(page)
        self.assertEqual(interstitials(page), [])
        log('ASSERT pause -> back to menu mid-run: no interstitial: pass')

    def test_c_not_after_continue_respawn(self):
        page = self.boot()
        self.kill(page, 6)
        self.click_canvas(page, 'continueOffer.continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=10000)
        page.wait_for_timeout(300)
        s = self.state(page)
        self.assertEqual((s['continueUsed'], s['runOver'], s['reStarts']), (True, False, 0))
        self.pause_to_menu(page)
        page.wait_for_timeout(300)
        self.assertTrue(self.state(page)['menu'])
        self.assertEqual(interstitials(page), [])
        log('ASSERT continue respawn, then Menu mid-run: no interstitial: pass')

    # Frequency and outcomes

    def test_d_three_deaths_second_skipped(self):
        page = self.boot()
        page.evaluate(FAKE_CLOCK)
        deaths = []
        for n, clock in ((1, 0), (2, 30000), (3, 91000)):
            page.evaluate(f'window.__clock = {clock}')
            if n == 3:
                # Past the Bridge's own minimumDelayBetweenInterstitial too
                page.evaluate('__fakeBridge.clearInterstitialCooldown()')
            before = len(interstitials(page))
            t = page.evaluate('performance.now()')
            self.kill(page, 0)
            self.wait_settled(page)
            shown = len(interstitials(page)) - before
            states = [c['name'] for c in bridge_calls(page)
                      if c['name'].startswith('interstitial:') and c['t'] >= t]
            deaths.append({'death': n, 'fakeClockMs': clock, 'deathT': round(t, 1),
                           'interstitialShown': bool(shown), 'states': states,
                           'reStarts': self.state(page)['reStarts']})
        self.assertEqual([d['interstitialShown'] for d in deaths], [True, False, True])
        self.assertEqual([d['reStarts'] for d in deaths], [1, 2, 3])
        self.assertEqual(deaths[0]['states'], ['interstitial:loading', 'interstitial:opened',
                                               'interstitial:closed'])
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            calls = [c for c in bridge_calls(page) if 'nterstitial' in c['name']]
            (out / 'calls.json').write_text(json.dumps(
                {'minGapMs': page.evaluate('PLATFORM.interstitialMinGapMs'),
                 'deaths': deaths, 'interstitialCalls': calls}, indent=1) + '\n')
        log('ASSERT 3 deaths at 0 s / 30 s / 91 s: shown, skipped, shown: pass')

    def test_e_failed_continues(self):
        page = self.boot(['loading', 'failed'])
        self.kill(page, 6)
        self.click_canvas(page, 'continueOffer.restartButton')
        self.wait_settled(page)
        s = self.state(page)
        self.assertEqual((s['reStarts'], s['offer'], s['pending'], s['adOpen']),
                         (1, False, False, False))
        self.assertFalse(s['muted']['ad'])
        # A failed ad does not start the local gap: the next death tries again
        self.assertIsNone(page.evaluate('lastInterstitialAt'))
        self.kill(page, 0)
        self.wait_settled(page)
        self.assertEqual(len(interstitials(page)), 2)
        self.assertEqual(self.state(page)['reStarts'], 2)
        log('ASSERT failed interstitial -> restart at once, next death tries again: pass')

    # While it is open

    def test_f_no_input_leaks_while_opened(self):
        page = self.boot(SLOW_AD)
        self.kill(page, 0)
        self.wait_opened(page)
        before = self.state(page)
        page.mouse.click(640, 360)
        page.mouse.down()
        page.keyboard.press('p')
        page.wait_for_timeout(300)
        during = self.state(page)
        page.mouse.up()
        self.assertTrue(during['pending'] and during['adOpen'])
        self.assertEqual((during['grapnelThrown'], during['paused'], during['ticks'],
                          during['reStarts']), (False, False, before['ticks'], 0))
        self.wait_settled(page)
        after = self.state(page)
        self.assertEqual((after['reStarts'], after['grapnelThrown']), (1, False))
        page.wait_for_function(f'window.__ticks > {after["ticks"]} + 5')
        log('ASSERT clicks/keys while opened: grapnel not thrown, no pause, physics frozen: pass')

    def test_f_sound_muted_while_opened(self):
        page = self.boot(SLOW_AD)
        self.assertFalse(self.state(page)['muted']['ad'])
        self.kill(page, 0)
        self.wait_opened(page)
        page.wait_for_timeout(100)
        state = page.evaluate('AUDIO.getState()')
        self.assertTrue(state['muted']['ad'])
        self.wait_settled(page)
        self.assertFalse(self.state(page)['muted']['ad'])
        log('ASSERT ad mute while opened, cleared after close: pass')


if __name__ == '__main__':
    unittest.main()
