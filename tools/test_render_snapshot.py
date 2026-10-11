"""Tests for the pixel-identity harness (tools/render_snapshot.py)."""
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import browser_test_support as support
import render_snapshot

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent

# Draws one opaque red device pixel after every draw(): a deliberate one-pixel
# canvas change that the menu capture does not see but every game tick does.
ONE_PIXEL_CHANGE = '''window.addEventListener('load', () => {
    const draw0 = window.draw
    window.draw = function() {
        draw0()
        ctx.save()
        ctx.setTransform(1, 0, 0, 1, 0, 0)
        ctx.globalAlpha = 1
        ctx.globalCompositeOperation = 'source-over'
        ctx.fillStyle = '#ff0000'
        ctx.fillRect(7, 7, 1, 1)
        ctx.restore()
    }
})'''


class RenderSnapshotTest(unittest.TestCase):
    def test_input_script_is_seeded(self):
        self.assertEqual(render_snapshot.input_script(1), render_snapshot.input_script(1))
        self.assertNotEqual(render_snapshot.input_script(1), render_snapshot.input_script(2))
        ticks = [e['tick'] for e in render_snapshot.input_script(1)]
        self.assertTrue(ticks)
        self.assertLessEqual(max(ticks), render_snapshot.TICKS[-1])
        self.assertEqual(len(render_snapshot.capture_names()), 18)

    def test_two_captures_of_head_are_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = render_snapshot.capture('HEAD', Path(tmp) / 'one')
            second = render_snapshot.capture('HEAD', Path(tmp) / 'two')
        self.assertEqual(first['page_errors'], [])
        self.assertEqual(len(first['captures']), 18)
        hashes = {n: c['sha256'] for n, c in first['captures'].items()}
        self.assertEqual(hashes, {n: c['sha256'] for n, c in second['captures'].items()})
        # Ticks of one game are different frames, not one frozen image.
        for vp in ('mobile', 'desktop'):
            for mode in render_snapshot.MODES:
                ticks = {hashes[f'{vp}-{mode}-tick{t:04d}'] for t in render_snapshot.TICKS}
                self.assertEqual(len(ticks), len(render_snapshot.TICKS), f'{vp}-{mode}')

    def test_injected_one_pixel_change_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            init = Path(tmp) / 'one_pixel.js'
            init.write_text(ONE_PIXEL_CHANGE)
            out = Path(tmp) / 'cmp'
            proc = subprocess.run([sys.executable, str(TOOLS / 'render_snapshot.py'), '--compare',
                                   'HEAD', 'HEAD', '--init-script-b', str(init), '--out', str(out)],
                                  capture_output=True, text=True)
            print(proc.stdout[-2000:], proc.stderr[-2000:])
            self.assertEqual(proc.returncode, 1)
            report = json.loads((out / 'compare.json').read_text())
            captures = report['captures']
            for vp in ('mobile', 'desktop'):
                self.assertEqual(captures[f'{vp}-menu']['differing_pixels'], 0)
                for mode in render_snapshot.MODES:
                    for t in render_snapshot.TICKS:
                        entry = captures[f'{vp}-{mode}-tick{t:04d}']
                        self.assertGreaterEqual(entry['differing_pixels'], 1)
                        self.assertTrue(Path(entry['diff_png']).exists())
            self.assertEqual(len(report['differing_captures']), 16)


class BootFastForwardTest(unittest.TestCase):
    """boot_frozen must finish a boot that awaits a timeout, without leaking the jump."""
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = support.start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def frozen_page(self, abort_sdk):
        context = self.browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.addCleanup(context.close)
        if abort_sdk:
            # Registered after OfflineBrowser's stub route, so it wins: the
            # SDK script fails and PLATFORM.init() waits for its 2900 ms timer.
            context.route(support.Y8_SDK_URL, support.block_external)
        context.add_init_script(render_snapshot.CLOCK_SCRIPT)
        page = context.new_page()
        page.goto(self.url + 'index.html', wait_until='load')
        return page

    def test_aborted_sdk_boot_fast_forwards_then_resets_clock(self):
        page = self.frozen_page(abort_sdk=True)
        before = page.evaluate('() => ({now: __snap.now, booted: __snap.booted,'
                               ' env: PLATFORM.environment, timers: __snap.pendingTimers()})')
        self.assertEqual(before['env'], 'pending', before)
        self.assertEqual([t['due'] for t in before['timers']], [2900], before)
        render_snapshot.boot_frozen(page)
        self.assertEqual(page.evaluate('() => __snap.bootJumps'), [2900])
        self.assertEqual(page.evaluate('() => PLATFORM.environment'), 'disabled')
        self.assertTrue(page.evaluate('() => typeof menu != "undefined" && menu.visible'))
        script = render_snapshot.input_script(render_snapshot.SEED, 60, 1920, 1080)
        page.evaluate(render_snapshot.SETUP_SCRIPT, [script, False])
        self.assertEqual(page.evaluate('() => __snap.now'), 0)
        self.assertEqual(page.evaluate('() => __snap.tick'), 0)
        self.assertEqual(page.evaluate('() => __snap.pendingTimers()'), [])
        # Gameplay ticks count from 0 after boot: tick 60 is reached at 60 steps.
        page.evaluate('mode => startGame(mode)', 'classic')
        self.assertEqual(page.evaluate(render_snapshot.ADVANCE_SCRIPT, 60), 60)
        self.assertAlmostEqual(page.evaluate('() => performance.now()'), 60 * 1000 / 60)
        self.assertEqual(page.evaluate('() => __snap.bootJumps'), [2900])

    def test_stubbed_sdk_boot_needs_no_jump(self):
        page = self.frozen_page(abort_sdk=False)
        render_snapshot.boot_frozen(page)
        self.assertEqual(page.evaluate('() => __snap.bootJumps'), [])
        self.assertEqual(page.evaluate('() => __snap.now'), 0)
        self.assertEqual(page.evaluate('() => __snap.pendingTimers()'), [])

    def test_unfinishable_boot_raises_with_pending_timers(self):
        context = self.browser.new_context(viewport={'width': 640, 'height': 480})
        self.addCleanup(context.close)
        context.add_init_script(render_snapshot.CLOCK_SCRIPT)
        page = context.new_page()
        # #loading never hides; the timer re-arms itself, so every round jumps.
        page.set_content('<div id="loading"></div>'
                         '<script>setTimeout(function again() { setTimeout(again, 1000) }, 1000)</script>')
        with self.assertRaises(RuntimeError) as cm:
            render_snapshot.boot_frozen(page, rounds=3)
        message = str(cm.exception)
        self.assertIn('after 3 rounds', message)
        # Each jump skips the 1000 ms to the re-armed timer, then the clock resets.
        self.assertIn('now=0 tick=0 bootJumps=[1000, 1000, 1000]', message)
        self.assertIn("pending timers=[{'id': 4, 'due': 1000", message)
        self.assertIn('function again()', message)


if __name__ == '__main__':
    unittest.main()
