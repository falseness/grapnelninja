"""Host pause, host audio, hidden tab and full-screen ad rules.

Host events are fired through window.__fakeBridge.fire (PAUSE_STATE_CHANGED,
AUDIO_STATE_CHANGED, INTERSTITIAL_STATE_CHANGED). Host pause pauses the run
like 'p' and host resume leaves it paused; host audio drives the 'host' mute
source, a hidden tab the 'hidden' one and an opened ad the 'ad' one (gameplay
and input stay frozen while the ad is open).

Env: PAUSE_EVIDENCE_DIR receives gain-log.json (master gain and
AudioContext state before/after each event, per case).
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playgama_harness import bridge_errors, open_game, start_playgama_test
from test_audio_wiring import (CENTER, PIN_NINJA, READY, SET_VISIBILITY,
                               canvas_to_viewport)

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}

# Counts physics ticks so a frozen run can be told from a running one
COUNT_PHYSICS = '''() => {
    window.__physicsTicks = 0
    const step = window.physics
    window.physics = function() {
        ++window.__physicsTicks
        return step.apply(this, arguments)
    }
}'''

AUDIO_STATE = '''() => { const s = AUDIO.getState()
    return {gain: s.gain, state: s.state, muted: s.muted} }'''


def log(message):
    print('  ' + message, file=sys.stderr)


class PlaygamaPauseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('PAUSE_EVIDENCE_DIR')
        cls.gain_log = {}

    @classmethod
    def tearDownClass(cls):
        if cls.evidence and cls.gain_log:
            out = Path(cls.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'gain-log.json').write_text(
                json.dumps(cls.gain_log, indent=2, sort_keys=True) + '\n')

    def boot(self, fake=None):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT, fake)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        page.evaluate(PIN_NINJA)
        page.evaluate(COUNT_PHYSICS)
        self.rows = self.gain_log.setdefault(self._testMethodName, [])
        return page

    def audio(self, page):
        return page.evaluate(AUDIO_STATE)

    def wait_audio(self, page, muted):
        """Wait until the master gain and context state match the mute."""
        page.wait_for_function(
            '''(muted) => { const s = AUDIO.getState()
                return muted ? s.gain === 0 && s.state === 'suspended'
                             : s.gain === 1 && s.state === 'running' }''',
            arg=muted, timeout=5000)

    def event(self, page, name, action, muted=None):
        """Run action, wait for the expected audio, log gain before/after."""
        before = self.audio(page)
        action()
        if muted is not None:
            self.wait_audio(page, muted)
        else:
            page.wait_for_timeout(100)
        after = self.audio(page)
        self.rows.append({'event': name, 'before': before, 'after': after,
                          'paused': page.evaluate('menu.gamePaused')})
        return after

    def fire(self, page, event, value):
        page.evaluate('([e, v]) => __fakeBridge.fire(e, v)', [event, value])

    def click_logical(self, page, x, y):
        p = canvas_to_viewport(page, x, y)
        page.mouse.click(p['x'], p['y'])
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def start_run(self, page):
        """Start the chill version with a real click (it also unlocks audio)."""
        c = page.evaluate(CENTER, 'menu.classicVersionButton')
        self.click_logical(page, c['x'], c['y'])
        self.assertFalse(page.evaluate('menu.visible'))
        self.assertFalse(page.evaluate('menu.gamePaused'))

    def ticks_over(self, page, ms=400):
        start = page.evaluate('__physicsTicks')
        page.wait_for_timeout(ms)
        return page.evaluate('__physicsTicks') - start

    def assert_running(self, page):
        self.assertFalse(page.evaluate('menu.gamePaused'))
        self.assertGreater(self.ticks_over(page), 5)

    def assert_paused(self, page):
        self.assertTrue(page.evaluate('menu.gamePaused'))
        self.assertEqual(self.ticks_over(page), 0)

    # Host pause

    def test_host_pause_mid_run(self):
        """PAUSE_STATE_CHANGED true pauses the run like 'p'."""
        page = self.boot()
        self.start_run(page)
        self.wait_audio(page, False)
        self.assert_running(page)
        self.event(page, 'host pause true',
                   lambda: self.fire(page, 'PAUSE_STATE_CHANGED', True))
        self.assert_paused(page)
        log('host pause -> menu.gamePaused, no physics ticks')

    def test_host_resume_does_not_resume(self):
        """PAUSE_STATE_CHANGED false leaves the run paused for the player."""
        page = self.boot()
        self.start_run(page)
        self.event(page, 'host pause true',
                   lambda: self.fire(page, 'PAUSE_STATE_CHANGED', True))
        self.event(page, 'host pause false',
                   lambda: self.fire(page, 'PAUSE_STATE_CHANGED', False))
        page.wait_for_timeout(300)
        self.assert_paused(page)
        page.keyboard.press('p')
        self.assert_running(page)
        log('host resume keeps the pause; the player resumes with p')

    # Host audio

    def test_audio_disabled_at_boot_muted_from_first_sound(self):
        """isAudioEnabled false at boot: the first sound is already muted."""
        page = self.boot({'isAudioEnabled': False})
        state = self.audio(page)
        self.assertTrue(state['muted']['host'])
        self.assertEqual(page.evaluate('__audioLog.length'), 0)
        self.event(page, 'first gesture (start run)',
                   lambda: self.start_run(page), muted=True)
        first = page.evaluate('__audioLog[0]')
        self.assertEqual(first['name'], 'click')
        self.assertTrue(first['muted'])
        self.assertTrue(all(e['muted'] for e in page.evaluate('__audioLog')))
        log(f'first sound {first["name"]} muted={first["muted"]}')

    def test_audio_event_toggles_host_mute(self):
        """AUDIO_STATE_CHANGED false mutes, true unmutes."""
        page = self.boot()
        self.start_run(page)
        self.wait_audio(page, False)
        after = self.event(page, 'host audio false',
                           lambda: self.fire(page, 'AUDIO_STATE_CHANGED', False), muted=True)
        self.assertTrue(after['muted']['host'])
        after = self.event(page, 'host audio true',
                           lambda: self.fire(page, 'AUDIO_STATE_CHANGED', True), muted=False)
        self.assertFalse(after['muted']['host'])
        after = self.event(page, 'host audio false again',
                           lambda: self.fire(page, 'AUDIO_STATE_CHANGED', False), muted=True)
        self.assertFalse(page.evaluate('menu.gamePaused'))

    def test_user_mute_stays_after_host_unmute(self):
        """The speaker button mute survives a host audio false -> true."""
        page = self.boot()
        self.start_run(page)
        self.wait_audio(page, False)
        r = page.evaluate('MUTE_BUTTON.rect(MUTE_BUTTON.current())')
        self.event(page, 'user mute click',
                   lambda: self.click_logical(page, r['x'] + r['width'] / 2,
                                              r['y'] + r['height'] / 2), muted=True)
        self.event(page, 'host audio false',
                   lambda: self.fire(page, 'AUDIO_STATE_CHANGED', False), muted=True)
        after = self.event(page, 'host audio true',
                           lambda: self.fire(page, 'AUDIO_STATE_CHANGED', True), muted=True)
        page.wait_for_timeout(300)
        after = self.audio(page)
        self.assertTrue(after['muted']['user'])
        self.assertFalse(after['muted']['host'])
        self.assertEqual((after['gain'], after['state']), (0, 'suspended'))

    # Hidden tab

    def test_tab_hidden_mutes_and_pauses(self):
        page = self.boot()
        self.start_run(page)
        self.wait_audio(page, False)
        after = self.event(page, 'visibility hidden',
                           lambda: page.evaluate(SET_VISIBILITY, 'hidden'), muted=True)
        self.assertTrue(after['muted']['hidden'])
        self.assert_paused(page)

    def test_tab_visible_unmutes_and_stays_paused(self):
        page = self.boot()
        self.start_run(page)
        self.wait_audio(page, False)
        self.event(page, 'visibility hidden',
                   lambda: page.evaluate(SET_VISIBILITY, 'hidden'), muted=True)
        after = self.event(page, 'visibility visible',
                           lambda: page.evaluate(SET_VISIBILITY, 'visible'), muted=False)
        self.assertFalse(after['muted']['hidden'])
        self.assert_paused(page)

    # Full-screen ads

    def test_ad_opened_mutes_and_freezes(self):
        page = self.boot()
        self.start_run(page)
        self.wait_audio(page, False)
        self.assert_running(page)
        after = self.event(page, 'interstitial opened',
                           lambda: self.fire(page, 'INTERSTITIAL_STATE_CHANGED', 'opened'),
                           muted=True)
        self.assertTrue(after['muted']['ad'])
        self.assertEqual(self.ticks_over(page), 0)
        # Input is frozen: no grapnel throw, 'p' does not pause
        sounds = page.evaluate('__audioLog.length')
        p = canvas_to_viewport(page, 0.7 * page.evaluate('width'), 0.5 * page.evaluate('height'))
        page.mouse.click(p['x'], p['y'])
        page.keyboard.press('p')
        page.wait_for_timeout(200)
        self.assertFalse(page.evaluate('grapnel.throwed'))
        self.assertFalse(page.evaluate('menu.gamePaused'))
        self.assertEqual(page.evaluate('__audioLog.length'), sounds)

    def test_ad_closed_unmutes_and_resumes(self):
        page = self.boot()
        self.start_run(page)
        self.wait_audio(page, False)
        self.event(page, 'interstitial opened',
                   lambda: self.fire(page, 'INTERSTITIAL_STATE_CHANGED', 'opened'), muted=True)
        after = self.event(page, 'interstitial closed',
                           lambda: self.fire(page, 'INTERSTITIAL_STATE_CHANGED', 'closed'),
                           muted=False)
        self.assertFalse(after['muted']['ad'])
        self.assert_running(page)
        self.event(page, 'rewarded opened',
                   lambda: self.fire(page, 'REWARDED_STATE_CHANGED', 'opened'), muted=True)
        after = self.event(page, 'rewarded failed',
                           lambda: self.fire(page, 'REWARDED_STATE_CHANGED', 'failed'),
                           muted=False)
        self.assertFalse(after['muted']['ad'])
        self.assert_running(page)


if __name__ == '__main__':
    unittest.main()
