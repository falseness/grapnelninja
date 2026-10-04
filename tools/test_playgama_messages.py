"""Lifecycle messages through PLATFORM.sendMessage (TASK-124).

Runs against the fake Bridge (tools/fixtures/fake-playgama-bridge.js), which
records every platform.sendMessage call. The game sends 'level_started'
{world} at each run start, 'level_paused' / 'level_resumed' on pause and
resume, 'level_failed' {world} on the final death of a run (a death the
rewarded continue does not undo) and 'player_got_achievement' once per run
that beats the record. PLATFORM.sendLifecycle drops all of them until
game_ready has been sent.

Env: MESSAGES_EVIDENCE_DIR receives session-messages.json (the scripted
session of test_a_session_order).
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
HOST = 'tools/fixtures/fake-playgama-platform-host.html'
VIEWPORT = {'width': 1280, 'height': 720}


def log(msg):
    print('  ' + msg, file=sys.stderr)


def messages(page):
    """Ordered sendMessage calls as {'name', 'data'?} dicts."""
    out = []
    for c in bridge_calls(page):
        if c['name'] != 'platform.sendMessage':
            continue
        m = {'name': c['args'][0]}
        if len(c['args']) > 1:
            m['data'] = c['args'][1]
        out.append(m)
    return out


def names(page):
    return [m['name'] for m in messages(page)]


class PlaygamaMessagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('MESSAGES_EVIDENCE_DIR')

    def open(self, path='index.html', block_bridge=False):
        context, page, errors = open_game(self.browser, self.url + path,
                                          VIEWPORT, block_bridge=block_bridge)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        return page

    def boot(self, block_bridge=False):
        page = self.open(block_bridge=block_bridge)
        page.wait_for_function(READY, timeout=15000)
        page.evaluate(continue_test.INSTRUMENT_RUN)
        return page

    def wait_input(self, page):
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def click_canvas(self, page, path, scaled=False):
        c = page.evaluate(f'''(() => {{ const b = {path}.background
            const s = {'scale[version]' if scaled else '1'}
            return {{x: (b.x + b.width / 2) * s, y: (b.y + b.height / 2) * s}} }})()''')
        p = canvas_to_viewport(page, c['x'], c['y'])
        page.mouse.click(p['x'], p['y'])
        self.wait_input(page)

    def start_run(self, page, mode):
        button = {'classic': 'menu.classicVersionButton', 'bad': 'menu.badVersionButton'}[mode]
        self.click_canvas(page, button)
        page.wait_for_timeout(300)
        self.assertFalse(page.evaluate('menu.visible'))
        self.assertEqual(page.evaluate('version'), mode)

    def pause(self, page):
        self.click_canvas(page, 'menu.button', scaled=True)
        self.assertTrue(page.evaluate('menu.gamePaused'))

    def resume(self, page):
        self.click_canvas(page, 'menu.resume')
        self.assertFalse(page.evaluate('menu.gamePaused'))

    def back_to_menu(self, page):
        self.click_canvas(page, 'menu.backToMenu')
        self.wait_settled(page)
        self.assertTrue(page.evaluate('menu.visible'))

    def kill(self, page, score):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(50)

    def wait_settled(self, page):
        page.wait_for_function('!interstitialPending', timeout=10000)
        page.wait_for_timeout(150)

    def score(self, page, n):
        page.evaluate('n => { for (let i = 0; i < n; ++i) changeScoreText() }', n)

    def test_a_session_order(self):
        """boot -> classic -> pause -> resume -> death -> bad record run -> death."""
        page = self.boot()
        self.assertEqual(names(page), ['game_ready'])
        self.start_run(page, 'classic')
        self.pause(page)
        self.resume(page)
        # Below the continue score: final death, interstitial, instant restart
        self.kill(page, 0)
        self.wait_settled(page)
        self.assertEqual(page.evaluate('window.__reStarts'), 1)
        # Mid-run back to menu is not a failed level
        self.pause(page)
        self.back_to_menu(page)
        self.start_run(page, 'bad')
        page.evaluate('scoreText.record.bad = 3')
        self.score(page, 6)
        self.kill(page, 0)
        self.wait_settled(page)
        self.assertEqual(page.evaluate('window.__reStarts'), 2)
        got = messages(page)
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'session-messages.json').write_text(json.dumps(got, indent=1) + '\n')
        classic, bad = {'world': 'classic'}, {'world': 'bad'}
        self.assertEqual(got, [
            {'name': 'game_ready'},
            {'name': 'level_started', 'data': classic},
            {'name': 'level_paused'},
            {'name': 'level_resumed'},
            {'name': 'level_failed', 'data': classic},
            {'name': 'level_started', 'data': classic},
            {'name': 'level_paused'},
            {'name': 'level_started', 'data': bad},
            {'name': 'player_got_achievement'},
            {'name': 'level_failed', 'data': bad},
            {'name': 'level_started', 'data': bad},
        ])
        log(f'ASSERT session order ({len(got)} messages): pass')

    def test_b_nothing_before_game_ready(self):
        page = self.open(HOST)
        page.wait_for_function('() => window.bridge && window.__fakeBridge')
        self.assertEqual(page.evaluate('PLATFORM.init()'), 'playgama')
        page.evaluate('''async () => {
            await PLATFORM.sendLifecycle('level_started', {world: 'classic'})
            await PLATFORM.sendLifecycle('level_paused')
            await PLATFORM.sendLifecycle('player_got_achievement')
        }''')
        self.assertEqual(messages(page), [])
        page.evaluate('''async () => { await PLATFORM.gameReady()
            await PLATFORM.sendLifecycle('level_started', {world: 'bad'}) }''')
        self.assertEqual(messages(page), [{'name': 'game_ready'},
                                          {'name': 'level_started', 'data': {'world': 'bad'}}])
        # In the game itself game_ready is always the first message
        game = self.boot()
        self.start_run(game, 'classic')
        self.assertEqual(names(game)[:2], ['game_ready', 'level_started'])
        log('ASSERT lifecycle messages dropped before game_ready: pass')

    def test_c_achievement_once_per_record_run(self):
        page = self.boot()
        self.start_run(page, 'classic')
        page.evaluate('scoreText.record.classic = 3')
        self.score(page, 6)
        self.assertEqual(names(page).count('player_got_achievement'), 1)
        self.kill(page, 0)
        self.wait_settled(page)
        # Record is 6 now: 4 points do not beat it, 3 more do
        self.score(page, 4)
        self.assertEqual(names(page).count('player_got_achievement'), 1)
        self.score(page, 3)
        self.assertEqual(names(page).count('player_got_achievement'), 2)
        log('ASSERT player_got_achievement once per record run (2 over 2 record runs): pass')

    def test_d_failed_only_on_final_death(self):
        page = self.boot()
        self.start_run(page, 'classic')
        # Death with the offer, then the rewarded continue: the run goes on
        self.kill(page, 6)
        self.assertTrue(page.evaluate('continueOffer.visible'))
        self.assertNotIn('level_failed', names(page))
        self.click_canvas(page, 'continueOffer.continueButton')
        page.wait_for_function('!continueOffer.visible', timeout=10000)
        page.wait_for_timeout(300)
        self.assertNotIn('level_failed', names(page))
        # Second death: continue already used, the run is over
        page.wait_for_function('!ninja.isInvulnerable()', timeout=10000)
        self.kill(page, 7)
        self.wait_settled(page)
        self.assertEqual(names(page).count('level_failed'), 1)
        # Death with the offer, then Restart: one more failed level
        self.kill(page, 6)
        self.assertTrue(page.evaluate('continueOffer.visible'))
        self.click_canvas(page, 'continueOffer.restartButton')
        self.wait_settled(page)
        self.assertEqual(names(page).count('level_failed'), 2)
        self.assertEqual(names(page).count('level_started'), 3)
        log('ASSERT level_failed only on the final death of a run: pass')

    def test_e_pause_resume_by_key(self):
        page = self.boot()
        self.start_run(page, 'bad')
        page.keyboard.press('p')
        page.wait_for_timeout(100)
        page.keyboard.press('p')
        page.wait_for_timeout(100)
        self.assertEqual(names(page), ['game_ready', 'level_started',
                                       'level_paused', 'level_resumed'])
        log('ASSERT p key -> level_paused, level_resumed: pass')

    def test_f_disabled_bridge_is_silent(self):
        page = self.boot(block_bridge=True)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'disabled')
        self.start_run(page, 'classic')
        self.pause(page)
        self.resume(page)
        page.evaluate('scoreText.record.classic = 0')
        self.score(page, 1)
        self.kill(page, 0)
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate('window.__reStarts'), 1)
        log('ASSERT disabled Bridge: a full run sends nothing and throws nothing: pass')


if __name__ == '__main__':
    unittest.main()
