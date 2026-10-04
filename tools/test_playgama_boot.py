"""Boot index.html against the fake, blocked, rejecting or never-ready Playgama Bridge."""
import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playgama_harness import (bridge_calls, bridge_errors, open_game,
                              start_playgama_test)

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
READY = 'window.__boot.readyAt !== undefined'
LOADING_HIDDEN = 'document.getElementById("loading").hidden'

# Counts rAF callbacks, records the first menu draw on the game canvas and
# snapshots both when the game sends game_ready to the Bridge.
BOOT_HOOK = '''(() => {
    const boot = window.__boot = {frames: 0, inputs: 0}
    const raf = window.requestAnimationFrame
    window.requestAnimationFrame = function (fn) {
        return raf.call(window, (t) => { boot.frames++; return fn(t) })
    }
    const fillText = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function () {
        if (boot.menuDrawnAt === undefined && this.canvas.id === 'canvas') {
            boot.menuDrawnAt = performance.now()
            boot.menuDrawnFrame = boot.frames
        }
        return fillText.apply(this, arguments)
    }
    const wrap = () => {
        if (!window.bridge || !window.bridge.platform)
            return
        const send = window.bridge.platform.sendMessage
        window.bridge.platform.sendMessage = function (name) {
            if (name === 'game_ready') {
                boot.readyAt = performance.now()
                boot.framesAtReady = boot.frames
                boot.loadingHiddenAtReady = document.getElementById('loading').hidden
            }
            return send.apply(this, arguments)
        }
    }
    document.addEventListener('DOMContentLoaded', wrap)
})()'''

# Without a Bridge game_ready is never sent; mark readiness from the overlay.
DISABLED_READY = '''() => {
    if (document.getElementById('loading').hidden && window.__boot.readyAt === undefined)
        window.__boot.readyAt = performance.now()
    return window.__boot.readyAt !== undefined
}'''


class PlaygamaBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('PLAYGAMA_BOOT_EVIDENCE_DIR')

    @classmethod
    def out(cls):
        out = Path(cls.evidence)
        (out / 'screens').mkdir(parents=True, exist_ok=True)
        return out

    def boot(self, block_bridge=False, **fake_options):
        context, page, errors = open_game(
            self.browser, 'about:blank', VIEWPORT,
            fake_options=fake_options, block_bridge=block_bridge)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        page.add_init_script(BOOT_HOOK)
        self.responses = []
        page.on('response', lambda r: self.responses.append(
            {'url': r.url, 'status': r.status}))
        page.goto(self.url + 'index.html')
        return page

    def calls(self, page, name, *args):
        return [c for c in bridge_calls(page)
                if c['name'] == name and list(c['args'][:len(args)]) == list(args)]

    def assert_disabled_boot(self, page, timeout):
        t0 = time.monotonic()
        page.wait_for_function(DISABLED_READY, timeout=timeout)
        seconds = time.monotonic() - t0
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'disabled')
        self.assertTrue(page.evaluate('menu.visible'))
        self.assertTrue(page.evaluate(LOADING_HIDDEN))
        self.assertEqual(self.calls(page, 'platform.sendMessage', 'game_ready'), [])
        # The menu still starts a run, with ads reported unavailable
        page.evaluate('startGame("classic")')
        self.assertFalse(page.evaluate('menu.visible'))
        self.assertEqual(page.evaluate('continueOffer.adsAvailable'), False)
        return seconds

    def test_normal_boot_order(self):
        """initialize < storage.get < game_ready (once), after the first menu frame."""
        page = self.boot()
        page.wait_for_function(READY, timeout=5000)
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'playgama')
        self.assertTrue(page.evaluate('menu.visible'))
        self.assertTrue(page.evaluate(LOADING_HIDDEN))
        calls = bridge_calls(page)
        names = [c['name'] for c in calls]
        init = names.index('initialize')
        gets = [i for i, n in enumerate(names) if n == 'storage.get']
        ready = [i for i, c in enumerate(calls) if c['name'] == 'platform.sendMessage'
                 and c['args'][:1] == ['game_ready']]
        self.assertEqual(len(gets), 1)
        self.assertEqual(calls[gets[0]]['args'][0],
                         page.evaluate('PROGRESS.keys'))
        self.assertEqual(len(ready), 1)
        self.assertLess(init, gets[0])
        self.assertLess(gets[0], ready[0])
        self.assertNotIn('storage.set', names[:ready[0]])
        boot = page.evaluate('window.__boot')
        self.assertGreaterEqual(boot['menuDrawnFrame'], 1)
        self.assertGreaterEqual(boot['framesAtReady'], 1)
        self.assertGreater(boot['framesAtReady'], boot['menuDrawnFrame'])
        self.assertLess(boot['menuDrawnAt'], boot['readyAt'])
        self.assertTrue(boot['loadingHiddenAtReady'])
        print(f'\n  order initialize={init} storage.get={gets[0]} game_ready={ready[0]}'
              f' framesAtReady={boot["framesAtReady"]}', file=sys.stderr)
        if self.evidence:
            out = self.out()
            (out / 'call-order.json').write_text(json.dumps(
                {'calls': calls, 'boot': boot,
                 'order': {'initialize': init, 'storage.get': gets[0],
                           'game_ready': ready[0]},
                 'game_ready_count': len(ready)}, indent=1) + '\n')
            page.screenshot(path=str(out / 'screens' / 'menu.png'))

    def test_bridge_missing(self):
        """Blocked Bridge script: 'disabled', menu boots, no Bridge calls."""
        page = self.boot(block_bridge=True)
        self.assert_disabled_boot(page, 5000)
        self.assertEqual(bridge_calls(page), [])

    def test_init_reject(self):
        """initialize() rejects: 'disabled', menu boots with local storage."""
        page = self.boot(init='reject')
        self.assert_disabled_boot(page, 5000)
        self.assertEqual(self.calls(page, 'storage.get'), [])

    def test_init_never(self):
        """initialize() never settles: boots 'disabled' within 10 s."""
        page = self.boot(init='never')
        seconds = self.assert_disabled_boot(page, 10000)
        print(f'\n  init never -> disabled after {seconds:.1f} s', file=sys.stderr)
        self.assertLess(seconds, 10)

    def test_input_before_ready_ignored(self):
        """Clicks and keys during loading do nothing; the menu shows after."""
        page = self.boot(initDelayMs=1500)
        page.wait_for_selector('#loading', state='visible', timeout=2000)
        self.assertFalse(page.evaluate(LOADING_HIDDEN))
        if self.evidence:
            page.screenshot(path=str(self.out() / 'screens' / 'loading.png'))
        for i in range(1, 6):
            for j in range(1, 6):
                page.mouse.click(VIEWPORT['width'] * i / 6, VIEWPORT['height'] * j / 6)
        for key in ('Space', 'Enter', 'Escape', 'KeyP'):
            page.keyboard.press(key)
        self.assertEqual(page.evaluate('window.__boot.readyAt'), None)
        page.wait_for_function(READY, timeout=5000)
        page.wait_for_timeout(200)
        self.assertTrue(page.evaluate('menu.visible'))
        self.assertFalse(page.evaluate('menu.gamePaused'))
        self.assertEqual(page.evaluate('typeof ninja'), 'undefined')
        self.assertEqual(page.evaluate('version'), None)
        self.assertEqual(len(self.calls(page, 'platform.sendMessage', 'game_ready')), 1)

    def test_config_served(self):
        """playgama-bridge-config.json is fetched next to index.html with 200."""
        page = self.boot()
        page.wait_for_function(READY, timeout=5000)
        got = page.evaluate('''async () => {
            const r = await fetch('./playgama-bridge-config.json')
            return {status: r.status, url: r.url, body: await r.json()}
        }''')
        local = json.loads((ROOT / 'playgama-bridge-config.json').read_text())
        self.assertEqual(got['status'], 200)
        self.assertEqual(got['body'], local)
        served = [r for r in self.responses
                  if r['url'].endswith('/playgama-bridge-config.json')]
        self.assertEqual([r['status'] for r in served], [200])
        print(f'\n  config fetch {got["url"]} -> {got["status"]}', file=sys.stderr)
        if self.evidence:
            (self.out() / 'config-fetch.json').write_text(
                json.dumps({'fetch': got, 'responses': served}, indent=1) + '\n')


if __name__ == '__main__':
    unittest.main()
