"""Fast restart when no game over interstitial is due (TASK-370).

8519216 (TASK-242) made every lethal death open the death screen
(ContinueOffer) and wait for Restart. Before it, a death without a continue
called leaveFinishedRun(reStart) at once. Now the death screen is shown only
when PLATFORM.isInterstitialDue() (the ad then plays on leaving it); any
other death sends level_failed and restarts the same mode immediately, with
no interstitial request.

Uses the fake Bridge of test_playgama2_bridge.py with interstitials
supported and PLATFORM.now() replaced by a frozen clock (window.fakeNow).
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
from browser_test_support import SDK_URL, start_browser_test, wait_for_boot
from test_playgama2_bridge import FAKE

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get('FAST_RESTART_EVIDENCE_DIR', ROOT / 'artifacts/TASK-370'))

# Interstitials supported: each request is recorded, then opens and closes.
# probe.messages holds every platform.sendMessage as [name, data].
ADS = r"""
probe.messages = [];
probe.interstitials = [];
const sendMessage = bridge.platform.sendMessage;
bridge.platform.sendMessage = (name, data) => {
    probe.messages.push([name, data ?? null]);
    return sendMessage(name, data);
};
Object.assign(bridge.advertisement, {
    isInterstitialSupported: true,
    interstitialState: 'closed',
    showInterstitial(placement) {
        probe.interstitials.push(placement);
        const set = state => { bridge.advertisement.interstitialState = state; emitHost('interstitial', state); };
        set('loading');
        setTimeout(() => set('opened'), 20);
        setTimeout(() => set('closed'), 60);
    }
});
"""

FRAMES = '''n => new Promise(resolve => {
    const seen = []
    const step = () => {
        seen.push(continueOffer.visible)
        if (seen.length === n) resolve(seen)
        else requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
})'''

PRESS = '''name => {
    const b = continueOffer[name].background
    if (!continueOffer.click({x: b.x + b.width / 2, y: b.y + b.height / 2}))
        throw Error(name + ' click ignored')
}'''

# isInterstitialDue() and what showInterstitial('game_over') does on a death
# screen: a 'skipped' resolution without an SDK call, or an SDK request
AGREE = '''async () => {
    const due = PLATFORM.isInterstitialDue()
    const before = window.probe ? probe.interstitials.length : 0
    const wasOver = runOver, wasVisible = continueOffer.visible
    runOver = true
    continueOffer.visible = true
    const pending = PLATFORM.showInterstitial('game_over')
    const requested = (window.probe ? probe.interstitials.length : 0) - before
    const result = await pending
    runOver = wasOver
    continueOffer.visible = wasVisible
    return {due, requested, result}
}'''


class FastRestartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self, bridge=True):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
        self.addCleanup(context.close)
        if bridge:
            context.route(SDK_URL, lambda route: route.fulfill(content_type='application/javascript',
                body='const FAULT = "normal"; const SAVED_LANGUAGE = null;\n' + FAKE + ADS))
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(self.url + 'index.html')
        wait_for_boot(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.wait_for_function('bootComplete && runInProgress && !!ninja')
        page.evaluate('window.fakeNow = 1000000; PLATFORM.now = () => window.fakeNow')
        if bridge:
            page.evaluate('PLATFORM.gameReady()')
            page.wait_for_function("probe.messages.some(m => m[0] === 'game_ready')")
            page.wait_for_function("probe.messages.some(m => m[0] === 'level_started')")
        return page

    def death_screen_restart(self, page):
        """A due death shows the death screen; Restart requests one ad."""
        before = page.evaluate('probe.interstitials.length')
        page.evaluate('scoreText.count[version] = 5; onLethalDeath()')
        self.assertTrue(page.evaluate('continueOffer.visible'))
        page.evaluate(PRESS, 'restartButton')
        page.wait_for_function('!continueOffer.visible && !interstitialPending && runInProgress')
        self.assertEqual(page.evaluate('probe.interstitials').count('game_over') - before, 1)
        self.assertEqual(page.evaluate('probe.interstitials.length') - before, 1)

    def test_fast_restart_when_no_ad_due(self):
        page = self.open()
        # (b) none requested yet: death screen, Restart -> one interstitial
        self.assertTrue(page.evaluate('PLATFORM.isInterstitialDue()'))
        self.death_screen_restart(page)
        print('PASS (b) no earlier request: death screen, Restart -> 1 showInterstitial(game_over)', flush=True)

        # (a) the request above was 0 s ago on the frozen clock: fast restart
        page.evaluate('window.fakeNow += 119999')
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        page.evaluate('scoreText.count.bad = 7')
        # One evaluate: headless frames take ~120 ms, so separate round trips
        # would outlast the 420 ms death shockwave. Frame 3 is read from the
        # canvas in the rAF callback queued after that frame's gameLoop.
        result = page.evaluate('''async () => {
            const version0 = version, ninja0 = ninja
            const from = probe.messages.length, ads = probe.interstitials.length
            const burst = visualEffects.screenEffects.triggerDeath
            let bursts = 0
            visualEffects.screenEffects.triggerDeath = function() { bursts++; return burst.apply(this, arguments) }
            onLethalDeath()
            visualEffects.screenEffects.triggerDeath = burst
            const state = {before: version0, version, newNinja: ninja !== ninja0, bursts,
                offer: continueOffer.visible, pending: interstitialPending, runOver,
                score: scoreText.count.bad, messages: probe.messages.slice(from),
                ads: probe.interstitials.length - ads, from, frames: []}
            for (let i = 1; i <= 10; ++i)
            {
                await new Promise(resolve => requestAnimationFrame(resolve))
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
            return state
        }''')
        png = result.pop('png')
        (OUT / 'fast-restart.png').write_bytes(base64.b64decode(png.split(',', 1)[1]))
        frames = result.pop('frames')
        print('ASSERT fast-restart.png (frame 3 after the restart)', json.dumps(result['frame3']), flush=True)
        self.assertFalse(result['frame3']['offer'])
        self.assertEqual(len(result['frame3']['shockwaves']), 1)
        after = page.evaluate('m => probe.messages.slice(m).filter(x => x[0].startsWith("level_"))', result['from'])
        print('ASSERT fast restart', json.dumps({**result, 'frames': frames, 'lifecycleAfter': after}), flush=True)
        self.assertEqual(result['before'], 'bad')
        self.assertEqual(result['version'], 'bad')
        self.assertTrue(result['newNinja'])
        self.assertEqual(result['bursts'], 1)
        self.assertFalse(result['offer'])
        self.assertFalse(result['pending'])
        self.assertFalse(result['runOver'])
        self.assertEqual(result['score'], 0)
        self.assertEqual(result['messages'], [['level_failed', {'world': 'bad'}], ['level_started', {'world': 'bad'}]])
        self.assertEqual(after, [['level_failed', {'world': 'bad'}], ['level_started', {'world': 'bad'}]])
        self.assertEqual(result['ads'], 0)
        self.assertEqual(len(frames), 10)
        self.assertNotIn(True, frames)
        self.assertEqual(page.evaluate('probe.interstitials.length'), 1)
        print('PASS (a) ad not due (119.999 s): no death screen over 10 frames, same mode, score 0, '
              'messages [level_failed bad, level_started bad], 0 showInterstitial', flush=True)

        # (b) 120 s since the last request: due again
        page.evaluate('window.fakeNow += 1')
        self.assertTrue(page.evaluate('PLATFORM.isInterstitialDue()'))
        self.death_screen_restart(page)
        self.assertEqual(page.evaluate('probe.interstitials.length'), 2)
        print('PASS (b) 120 s since last request: death screen, Restart -> 1 showInterstitial(game_over)', flush=True)

    def test_predicate_agrees_with_show_interstitial(self):
        cases = {}
        page = self.open(bridge=False)
        cases['no bridge'] = page.evaluate(AGREE)
        page = self.open()
        page.evaluate('bridge.advertisement.isInterstitialSupported = false')
        cases['unsupported'] = page.evaluate(AGREE)
        page.evaluate("bridge.advertisement.isInterstitialSupported = true; bridge.advertisement.interstitialState = 'opened'")
        cases['busy'] = page.evaluate(AGREE)
        page.evaluate("bridge.advertisement.interstitialState = 'closed'")
        cases['due'] = page.evaluate(AGREE)
        page.wait_for_function("bridge.advertisement.interstitialState === 'closed'")
        page.evaluate('window.fakeNow += 60000')
        cases['inside gap'] = page.evaluate(AGREE)
        print('ASSERT predicate vs showInterstitial', json.dumps(cases), flush=True)
        for name in ('no bridge', 'unsupported', 'busy', 'inside gap'):
            self.assertEqual(cases[name], {'due': False, 'requested': 0, 'result': 'skipped'}, name)
        self.assertEqual(cases['due'], {'due': True, 'requested': 1, 'result': 'closed'})
        print('PASS (c) isInterstitialDue() false and showInterstitial skipped without a request: '
              'no bridge, unsupported, busy, inside gap; both true/requested when due', flush=True)

    def test_host_paused_fast_restart_stays_paused(self):
        page = self.open()
        page.evaluate('bridge.advertisement.isInterstitialSupported = false')
        page.evaluate("emitHost('pause', true)")
        self.assertTrue(page.evaluate('menu.gamePaused'))
        result = page.evaluate('''() => {
            const from = probe.messages.length
            onLethalDeath()
            return {offer: continueOffer.visible, paused: menu.gamePaused, version, runInProgress,
                messages: probe.messages.slice(from).filter(m => m[0].startsWith('level_'))}
        }''')
        frames = page.evaluate(FRAMES, 5)
        print('ASSERT host-paused fast restart', json.dumps({**result, 'frames': frames}), flush=True)
        self.assertFalse(result['offer'])
        self.assertTrue(result['paused'])
        self.assertTrue(page.evaluate('menu.gamePaused'))
        self.assertEqual(result['version'], 'bad')
        self.assertEqual(result['messages'][:2], [['level_failed', {'world': 'bad'}], ['level_started', {'world': 'bad'}]])
        self.assertNotIn(True, frames)
        print('PASS (d) host-paused fast restart ends with menu.gamePaused === true', flush=True)


if __name__ == '__main__':
    unittest.main()
