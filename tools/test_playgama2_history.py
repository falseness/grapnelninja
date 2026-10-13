"""Bounded real-input soak and actual back/forward navigation, local SDK fixture.

No physics/state overrides. SDK storage persists across documents in Python,
so navigation cannot accidentally reset the fake remote account. This is local
Chromium coverage, not hosted QA, native certification or a human playtest.

The title menu is gone (TASK-364): the page boots straight into a 'bad' run,
'classic' is reached through the pause screen's mode switch, and with
interstitials unsupported a death restarts the run at once. The language
button sits on the pause screen. Back therefore restores a running game,
which must keep exactly one gameLoop scheduled. Runnable from the repo root
or tools/: git and source hashes resolve against ROOT.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import unittest

from browser_test_support import start_browser_test, wait_for_boot
import test_playgama2_bridge as support


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', support.ROOT / 'artifacts/TASK-394/history'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(support.ROOT, cls.addClassCleanup)
        cls.results, cls.errors = {}, []
        paths = subprocess.check_output(['git', 'ls-files'], text=True, cwd=support.ROOT).splitlines()
        paths.append('tools/test_playgama2_history.py')
        cls.write('tested-source-hashes.json', {
            p: hashlib.sha256((support.ROOT / p).read_bytes()).hexdigest() for p in sorted(set(paths))
            if not p.startswith(('artifacts/', 'screenshots/'))})

    @classmethod
    def write(cls, name, value):
        (cls.out / name).write_text(json.dumps(value, indent=2) + '\n')

    @classmethod
    def tearDownClass(cls):
        cls.write('history.json', {'browser': cls.browser.version, 'cases': cls.results})
        (cls.out / 'browser-errors.log').write_text(''.join(e + '\n' for e in cls.errors))

    def click(self, page, expression):
        page.wait_for_function('!unTouch')
        point = page.evaluate('''() => {const b=''' + expression + ''', r=canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width,
                    y:r.y+(b.y+b.height/2)*r.height/height}}''')
        page.mouse.click(**point)

    def snapshot(self, page):
        return page.evaluate('''() => ({time:PROGRESS.getTime(), records:{...scoreText.record},
            muted:PROGRESS.getMuted(), language:I18N.language})''')

    def assert_one_run(self, page):
        """Back restored a running game with a single gameLoop."""
        page.wait_for_function('bootComplete && runInProgress && !!ninja')
        page.wait_for_timeout(300)
        state = page.evaluate('({pending: gameLoops.pending.size, max: gameLoops.max})')
        self.assertLessEqual(state['max'], 1, 'a second game loop was scheduled')
        self.assertEqual(state['pending'], 1, 'the game loop is not running')

    def assert_retained(self, snapshot, before, committed, since):
        """Records and preferences are exact through Back. Back restores a
        live run, so leaving it commits real play time: the time is never
        reset and grows by at most the wall-clock seconds since the last check."""
        self.assertEqual({k: v for k, v in snapshot.items() if k != 'time'},
                         {k: v for k, v in before.items() if k != 'time'},
                         'progress/preferences changed through Back')
        now = time.monotonic()
        self.assertGreaterEqual(snapshot['time'], committed, 'play time was reset through Back')
        self.assertLessEqual(snapshot['time'], committed + math.ceil(now - since) + 1,
                             'play time grew beyond the elapsed wall clock')
        return snapshot['time'], now

    def run_case(self, mode):
        result = self.results[mode] = {'samples': [], 'navigation': [], 'verdict': 'INCOMPLETE'}
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        remote = {'grapnelninja.lang': 'en', 'grapnelninja.time': '0'}
        context.expose_function('fixtureGet', lambda keys: [remote.get(k) for k in keys])

        def save(keys, values):
            remote.update(zip(keys, values))

        context.expose_function('fixtureSet', save)
        context.add_init_script("window.inputs=[]; addEventListener('mousedown',e=>inputs.push(e.isTrusted));")
        # Pending gameLoop frames of this document: one loop keeps at most one
        context.add_init_script('''(() => {
            const raf = requestAnimationFrame.bind(window), caf = cancelAnimationFrame.bind(window);
            const pending = new Set();
            window.gameLoops = {pending, max: 0};
            window.requestAnimationFrame = cb => {
                if (cb.name !== 'gameLoop') return raf(cb);
                const id = raf(t => { pending.delete(id); cb(t) });
                pending.add(id);
                gameLoops.max = Math.max(gameLoops.max, pending.size);
                return id;
            };
            window.cancelAnimationFrame = id => { pending.delete(id); caf(id) };
        })()''')
        context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body=
            'const FAULT="normal", SAVED_LANGUAGE="en";\n' + support.FAKE + '''
            bridge.storage.get = keys => fixtureGet(keys);
            bridge.storage.set = (keys, values) => fixtureSet(keys, values);
            bridge.platform.language = 'en';'''))
        context.route(self.url + 'history-away', lambda r: r.fulfill(
            content_type='text/html', body='<title>Away</title><p>History navigation fixture</p>'))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        self.addCleanup(lambda: self.errors.extend(mode + ': ' + e for e in errors))
        page.goto(self.url + 'index.html')
        wait_for_boot(page)
        page.wait_for_function('bootComplete && runInProgress && !!ninja')
        self.assertEqual(page.evaluate('version'), 'bad')
        support.Playgama2BridgeTests.click_mode(self, page, mode)
        page.wait_for_function('!menu.gamePaused && !unTouch')
        started = time.monotonic()
        failed = "probe.calls.filter(c => c.name === 'level_failed').length"
        failed_before = page.evaluate(failed)
        while time.monotonic() - started < 120:
            # No interstitial is due, so a death restarts at once (no offer)
            self.assertFalse(page.evaluate('continueOffer.visible'))
            page.mouse.move(900, 160)
            page.mouse.down()
            # Give the hook time to reach a surface before releasing it. A
            # 150ms tap often only free-falls in Chill's randomly spaced course.
            page.wait_for_timeout(1000)
            page.mouse.up()
            page.wait_for_timeout(350)
            sample = page.evaluate('''() => ({x:ninja.x,y:ninja.y,camera:screen.x,
                score:scoreText.count[version],time:PROGRESS.getTime(),
                elements:floors.reduce((n,f)=>n+f.elements.length,0),dead:continueOffer.visible})''')
            sample['elapsed'] = time.monotonic() - started
            result['samples'].append(sample)
            self.assertTrue(all(math.isfinite(sample[k]) for k in ('x', 'y', 'camera', 'time')))
            self.assertLess(sample['elements'], 500, 'obstacle queue exceeded bounded soak limit')
            self.assertEqual(errors, [])
        deaths = page.evaluate(failed) - failed_before
        result['elapsed_seconds'], result['deaths'] = time.monotonic() - started, deaths
        self.assertGreater(len({s['x'] for s in result['samples']}), 20, 'no sustained real movement')
        self.assertTrue(page.evaluate('inputs.length>20 && inputs.every(Boolean)'))
        result['trusted_inputs'] = page.evaluate('inputs.length')
        page.screenshot(path=str(self.out / (mode + '-soak.png')))
        page.keyboard.press('p')
        page.wait_for_function('menu.gamePaused')
        # The production timer commits elapsed play on pause/death, not on
        # every frame. A surviving run legitimately has zero cached time.
        result['active_seconds'] = page.evaluate('PROGRESS.getTime()')
        self.assertGreater(result['active_seconds'], 30, 'insufficient active gameplay')
        page.locator('#mute-button').click()
        self.click(page, 'LANGUAGE_BUTTON.rect()')
        page.wait_for_timeout(1200)
        before = self.snapshot(page)
        self.assertTrue(before['muted'])
        self.assertEqual(before['language'], 'ru')
        committed, since = before['time'], time.monotonic()
        for cycle in range(3):
            page.goto(self.url + 'history-away')
            self.assertEqual(page.title(), 'Away')
            page.go_back()
            wait_for_boot(page)
            self.assert_one_run(page)
            after = self.snapshot(page)
            committed, since = self.assert_retained(after, before, committed, since)
            page.go_forward()
            self.assertEqual(page.title(), 'Away')
            page.go_back()
            wait_for_boot(page)
            self.assert_one_run(page)
            committed, since = self.assert_retained(self.snapshot(page), before, committed, since)
            result['navigation'].append({'cycle': cycle, 'before': before, 'after': after,
                                          'back_forward_back': 'PASS'})
        # Confirm the restored document still accepts gameplay input.
        support.Playgama2BridgeTests.click_mode(self, page, mode)
        if page.evaluate('menu.gamePaused'):
            page.keyboard.press('p')
        page.wait_for_function('!menu.gamePaused && !unTouch && runInProgress')
        self.assertEqual(page.evaluate("probe.calls.filter(c => c.name === 'level_started').at(-1).data"),
                         {'world': mode})
        page.mouse.move(900, 160)
        page.mouse.down()
        page.wait_for_function('grapnel.throwed')
        # The per-load tutorial hint never blocks the first throw
        self.assertTrue(page.evaluate('TUTORIAL_HINT.pressed'))
        page.mouse.up()
        self.assertFalse(page.evaluate('grapnel.throwed'))
        page.screenshot(path=str(self.out / (mode + '-restored.png')))
        self.assertEqual(page.evaluate('gameLoops.max'), 1, 'a second game loop was scheduled')
        self.assertEqual(errors, [])
        result.update(verdict='PASS', remote=remote, restored_input='PASS')
        print(f'PASS {mode}: 120s real-input soak; {deaths} natural deaths/restarts; '
              '3 Back/Forward/Back cycles, one game loop; exact records/preferences, play time never reset; restored grapnel input', flush=True)

    def test_classic(self):
        self.run_case('classic')

    def test_bad(self):
        self.run_case('bad')


if __name__ == '__main__':
    unittest.main()
