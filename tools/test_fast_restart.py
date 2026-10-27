"""Fast restart when no game over interstitial is due (TASK-370).

8519216 (TASK-242) made every lethal death open the death screen
(ContinueOffer) and wait for Restart. Before it, a death without a continue
called leaveFinishedRun(reStart) at once. Now the death screen is shown only
when PLATFORM.isInterstitialDue() (the ad then plays on leaving it); any
other death restarts the same mode immediately.

The local adapter (platform.js) has no ads: no interstitial is ever due, so
every death fast-restarts. PLATFORM.now() is replaced by a frozen clock
(window.fakeNow).
TASK-371: a press held across a fast restart (stalePress in events.js) throws
no grapnel in the new run until it is released.

Saves fast-restart.png to FAST_RESTART_EVIDENCE_DIR (default
artifacts/TASK-370).
"""
import base64
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot
from game_harness import switch_mode

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get('FAST_RESTART_EVIDENCE_DIR', ROOT / 'artifacts/TASK-370'))

FRAMES = '''n => new Promise(resolve => {
    const seen = []
    const step = () => {
        seen.push(continueOffer.visible)
        if (seen.length === n) resolve(seen)
        else requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
})'''

# isInterstitialDue() and what showInterstitial('game_over') resolves to on a
# death screen
AGREE = '''async () => {
    const due = PLATFORM.isInterstitialDue()
    const wasOver = runOver, wasVisible = continueOffer.visible
    runOver = true
    continueOffer.visible = true
    const result = await PLATFORM.showInterstitial('game_over')
    runOver = wasOver
    continueOffer.visible = wasVisible
    return {due, result}
}'''


class FastRestartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        # Printed after the run so `test_held_press_across_fast_restart ... ok`
        # stays on one line of the -v output
        cls.report = []

    @classmethod
    def tearDownClass(cls):
        for line in cls.report:
            print(line, flush=True)

    def open(self, has_touch=False):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US',
                                           has_touch=has_touch)
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(self.url + 'index.html')
        wait_for_boot(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.wait_for_function('bootComplete && runInProgress && !!ninja')
        page.evaluate('window.fakeNow = 1000000; PLATFORM.now = () => window.fakeNow')
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'local')
        return page

    def fast_restart(self, page):
        """No ad is due locally: a death restarts at once, no death screen."""
        state = page.evaluate('''() => {
            scoreText.count[version] = 5
            onLethalDeath()
            return {offer: continueOffer.visible, pending: interstitialPending,
                running: runInProgress, score: scoreText.count[version]}
        }''')
        self.assertEqual(state, {'offer': False, 'pending': False, 'running': True, 'score': 0})

    def test_fast_restart_when_no_ad_due(self):
        page = self.open()
        # Boot starts Grapple Over; these checks are about the classic 'bad' run
        switch_mode(page, 'bad')
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialSupported()'))
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        page.evaluate('scoreText.count.bad = 7')
        # One evaluate, and performance.now() (the effect clock) is a virtual
        # clock advanced 16 ms per frame, so the 420 ms death shockwave's age
        # at frame 3 does not depend on how slow headless frames are. Frame 3
        # is read from the canvas in the rAF callback after its gameLoop.
        result = page.evaluate('''async () => {
            const version0 = version, ninja0 = ninja
            const burst = visualEffects.screenEffects.triggerDeath
            let bursts = 0
            visualEffects.screenEffects.triggerDeath = function() { bursts++; return burst.apply(this, arguments) }
            const realNow = performance.now
            let clock = realNow.call(performance)
            performance.now = () => clock
            onLethalDeath()
            visualEffects.screenEffects.triggerDeath = burst
            const state = {before: version0, version, newNinja: ninja !== ninja0, bursts,
                offer: continueOffer.visible, pending: interstitialPending, runOver,
                score: scoreText.count.bad, frames: []}
            for (let i = 1; i <= 10; ++i)
            {
                await new Promise(resolve => requestAnimationFrame(resolve))
                clock += 16
                state.frames.push(continueOffer.visible)
                if (i === 3)
                {
                    state.png = canvas.toDataURL('image/png')
                    const now = performance.now()
                    state.frame3 = {offer: continueOffer.visible, version, score: scoreText.count.bad,
                        shockwaves: visualEffects.screenEffects.shockwaves.filter(s => now < s.end)
                            .map(s => ({x: Math.round(s.x), y: Math.round(s.y), ageMs: Math.round(now - s.start)}))}
                }
            }
            performance.now = realNow
            resetPhysicsTiming()
            return state
        }''')
        png = result.pop('png')
        (OUT / 'fast-restart.png').write_bytes(base64.b64decode(png.split(',', 1)[1]))
        frames = result.pop('frames')
        print('ASSERT fast-restart.png (frame 3 after the restart)', json.dumps(result['frame3']), flush=True)
        self.assertFalse(result['frame3']['offer'])
        self.assertEqual([s['ageMs'] for s in result['frame3']['shockwaves']], [48])
        print('ASSERT fast restart', json.dumps({**result, 'frames': frames}), flush=True)
        self.assertEqual(result['before'], 'bad')
        self.assertEqual(result['version'], 'bad')
        self.assertTrue(result['newNinja'])
        self.assertEqual(result['bursts'], 1)
        self.assertFalse(result['offer'])
        self.assertFalse(result['pending'])
        self.assertFalse(result['runOver'])
        self.assertEqual(result['score'], 0)
        self.assertEqual(len(frames), 10)
        self.assertNotIn(True, frames)
        print('PASS (a) no ad due: no death screen over 10 frames, same mode, score 0', flush=True)

        # (b) 120 s later still not due: fast restart again
        page.evaluate('window.fakeNow += 120000')
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        self.fast_restart(page)
        print('PASS (b) 120 s later: still not due, death restarts at once', flush=True)

    def test_predicate_agrees_with_show_interstitial(self):
        cases = {}
        page = self.open()
        cases['local'] = page.evaluate(AGREE)
        page.evaluate('window.fakeNow += 120000')
        cases['after gap'] = page.evaluate(AGREE)
        print('ASSERT predicate vs showInterstitial', json.dumps(cases), flush=True)
        for name in ('local', 'after gap'):
            self.assertEqual(cases[name], {'due': False, 'result': 'skipped'}, name)
        print('PASS (c) isInterstitialDue() false and showInterstitial skipped: local, after the 120 s gap',
              flush=True)

    def test_paused_fast_restart_stays_paused(self):
        page = self.open()
        switch_mode(page, 'bad')
        page.evaluate('menu.startPause()')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        result = page.evaluate('''() => {
            onLethalDeath()
            return {offer: continueOffer.visible, paused: menu.gamePaused, version, runInProgress}
        }''')
        frames = page.evaluate(FRAMES, 5)
        print('ASSERT paused fast restart', json.dumps({**result, 'frames': frames}), flush=True)
        self.assertFalse(result['offer'])
        self.assertTrue(result['paused'])
        self.assertTrue(page.evaluate('menu.gamePaused'))
        self.assertEqual(result['version'], 'bad')
        self.assertNotIn(True, frames)
        print('PASS (d) paused fast restart ends with menu.gamePaused === true', flush=True)

    def held_press_across_fast_restart(self, page, down, extra, up):
        """down() holds a trusted press, extra() presses again while it is
        held, up() releases every press; returns the observed states."""
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        down()
        page.wait_for_function('grapnel.throwed && pressHeld')
        state = page.evaluate('''() => {
            const ninja0 = ninja
            onLethalDeath()
            return {newNinja: ninja !== ninja0, offer: continueOffer.visible, paused: menu.gamePaused,
                throwed: grapnel.throwed, pressHeld, stalePress}
        }''')
        state['frames'] = page.evaluate('''n => new Promise(resolve => {
            const seen = []
            const step = () => {
                seen.push(grapnel.throwed)
                if (seen.length === n) resolve(seen)
                else requestAnimationFrame(step)
            }
            requestAnimationFrame(step)
        })''', 30)
        extra()
        state['afterExtraPress'] = page.evaluate('({throwed: grapnel.throwed, stalePress})')
        up()
        state['afterRelease'] = page.evaluate('({throwed: grapnel.throwed, pressHeld, stalePress})')
        down()
        page.wait_for_function('grapnel.throwed')
        state['afterNextPress'] = page.evaluate('({throwed: grapnel.throwed, stalePress})')
        up()
        self.assertTrue(state['newNinja'])
        self.assertFalse(state['offer'])
        self.assertFalse(state['paused'])
        self.assertFalse(state['throwed'])
        self.assertTrue(state['pressHeld'])
        self.assertTrue(state['stalePress'])
        self.assertEqual(state['frames'], [False] * 30)
        self.assertEqual(state['afterExtraPress'], {'throwed': False, 'stalePress': True})
        self.assertEqual(state['afterRelease'], {'throwed': False, 'pressHeld': False, 'stalePress': False})
        self.assertEqual(state['afterNextPress'], {'throwed': True, 'stalePress': False})
        return state

    def test_held_press_across_fast_restart(self):
        page = self.open()
        mouse = page.mouse
        mouse.move(640, 300)
        state = self.held_press_across_fast_restart(page, mouse.down,
            lambda: mouse.down(button='right'), lambda: (mouse.up(button='right'), mouse.up()))
        self.report.append('ASSERT held mouse press ' + json.dumps(state))
        self.report.append('PASS (e) mouse: held across fast restart -> 30 frames throwed false (and a second '
                           'button press ignored); mouseup then mousedown -> throwed true')

        page = self.open(has_touch=True)
        cdp = page.context.new_cdp_session(page)
        finger = {'x': 640, 'y': 300, 'id': 0}
        second = {'x': 700, 'y': 320, 'id': 1}
        touch = lambda kind, points: cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': points})
        state = self.held_press_across_fast_restart(page, lambda: touch('touchStart', [finger]),
            lambda: touch('touchStart', [finger, second]), lambda: touch('touchEnd', []))
        self.report.append('ASSERT held touch press ' + json.dumps(state))
        self.report.append('PASS (f) touch (has_touch): held across fast restart -> 30 frames throwed false '
                           '(and a second finger ignored); touchend then touchstart -> throwed true')


if __name__ == '__main__':
    unittest.main()
