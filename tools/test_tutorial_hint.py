"""The canvas tutorial hint (render/tutorialhint.js) over a running 'bad' run.

The rendering tests force TUTORIAL_HINT.visible. Rendering checks: the hint is
drawn between the player and the HUD; a visible hint adds no shadowBlur sets
to the main context once its sprite is built; a language change rebuilds the
sprite once, with Russian text. test_lifecycle drives the real lifecycle on
the manual clock from render_snapshot (one 1000/60 ms physics step per
frame): shown from boot until the first press, then a 2.5 s fade of active
game time. test_fade_duration pins that length on the same clock. The local
adapter never makes an ad due, so every death takes the TASK-370 fast restart.

Requires Playwright Chromium. No remote requests.

TUTORIAL_HINT_EVIDENCE_DIR (default: artifacts/TASK-367) receives
hint-desktop.png, hint-mobile.png, hint-ru.png and compare.png;
TUTORIAL_LIFECYCLE_EVIDENCE_DIR (default: artifacts/TASK-367) receives
fade-0s.png, fade-1s.png, fade-1.25s.png, fade-2s.png and fade-2.5s.png;
TUTORIAL_FADE_EVIDENCE_DIR (default: artifacts/TASK-411) receives
hint-1.25s.png and hint-2.5s.png.
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from render_snapshot import CLOCK_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
CONCEPT = ROOT / 'artifacts/tutorial-concept'
BOOT_DONE = "PLATFORM.environment === 'local' && bootComplete && runInProgress"
# Stops the game loop and freezes the clock and randomness, so draw() can be
# repeated on identical frames
FREEZE = '''() => {
    cancelAnimationFrame(game)
    const now = performance.now()
    performance.now = () => now
    let seed = 1
    Math.random = () => (seed = (seed * 16807) % 2147483647) / 2147483647
}'''
# Counts shadowBlur sets on the main context
SPY = '''() => {
    const property = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, 'shadowBlur')
    window.__shadowBlurSets = 0
    Object.defineProperty(ctx, 'shadowBlur', {
        configurable: true,
        get() { return property.get.call(this) },
        set(value) { ++window.__shadowBlurSets; property.set.call(this, value) }
    })
}'''
# Centre region of the canvas (device pixels) after one draw()
CENTRE = '''() => {
    draw()
    const c = ctx.canvas, w = Math.round(c.width * 0.3), h = Math.round(c.height * 0.3)
    return Array.from(ctx.getImageData(Math.round((c.width - w) / 2), Math.round((c.height - h) / 2), w, h).data)
}'''


# On top of CLOCK_SCRIPT: rAF callbacks always queue (cancel works) and
# __frames(n) runs n animation frames, each one 1000/60 ms clock step later
FRAMES_SCRIPT = '''(() => {
    const snap = window.__snap, queue = new Map()
    window.requestAnimationFrame = cb => { queue.set(++snap.rafs, cb); return snap.rafs }
    window.cancelAnimationFrame = id => queue.delete(id)
    window.__frames = n => {
        for (let i = 0; i < n; ++i) {
            snap.tick++
            snap.now = snap.tick * 1000 / 60
            snap.runTimers()
            const due = [...queue.values()]
            queue.clear()
            for (const cb of due) cb(snap.now)
        }
        return snap.now
    }
})()'''
HINT = '({visible: TUTORIAL_HINT.visible, alpha: TUTORIAL_HINT.alpha, time: TUTORIAL_HINT.time})'
# A death on the current run and the run after it
DEATH = """() => {
    const ninja0 = ninja
    onLethalDeath()
    return {offer: continueOffer.visible, runInProgress, newNinja: ninja !== ninja0, version}
}"""
FAST = {'offer': False, 'runInProgress': True, 'newNinja': True, 'version': 'bad'}
# Records PLATFORM.startup stages (a no-op locally) in window.__startups
STARTUPS = """() => {
    window.__startups = []
    PLATFORM.startup = (stage, data) => { __startups.push({stage, data}) }
}"""
DISMISSED = "__startups.filter(s => s.stage === 'tutorial_dismissed')"


def changed_pixels(a, b, threshold=40):
    return sum(1 for i in range(0, len(a), 4)
               if max(abs(a[i + k] - b[i + k]) for k in range(3)) > threshold)


class TutorialHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('TUTORIAL_HINT_EVIDENCE_DIR', ROOT / 'artifacts/TASK-367'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.notes = []

    @classmethod
    def tearDownClass(cls):
        # test_lifecycle's lines, kept off its own '... ok' result line
        for line in cls.notes:
            print(line, flush=True)

    def note(self, *parts):
        self.notes.append(' '.join(str(p) for p in parts))

    def open(self, viewport=(1920, 1080), dpr=1, touch=False):
        context = self.browser.new_context(
            viewport={'width': viewport[0], 'height': viewport[1]}, device_scale_factor=dpr,
            is_mobile=touch, has_touch=touch, locale='en-US')
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(BOOT_DONE)
        self.assertEqual(page.evaluate('({version, runInProgress, paused: menu.gamePaused})'),
                         {'version': 'bad', 'runInProgress': True, 'paused': False})
        return page

    def frames(self, page, n, until=None, limit=2000):
        """Runs n frames, or batches of n frames until the JS condition holds."""
        if until is None:
            return page.evaluate('n => __frames(n)', n)
        for _ in range(limit // n):
            page.evaluate('n => __frames(n)', n)
            if page.evaluate(until):
                return
            page.wait_for_timeout(1)
        self.fail('timed out waiting for ' + until)

    def leave_run(self, page, action, check_hidden=False):
        """action (JS) leaves the run; frames until the new run plays."""
        page.evaluate(action)
        for _ in range(400):
            self.frames(page, 1)
            if check_hidden:
                self.assertFalse(page.evaluate('TUTORIAL_HINT.visible'))
            if page.evaluate('runInProgress && !continueOffer.visible && !interstitialPending'):
                break
            page.wait_for_timeout(1)
        if page.evaluate('menu.gamePaused'):
            page.evaluate('menu.unPause()')

    def open_clocked(self):
        """The game on the manual frame clock, booted and with the hint shown."""
        context = self.browser.new_context(viewport={'width': 1920, 'height': 1080}, locale='en-US')
        self.addCleanup(context.close)
        context.add_init_script(CLOCK_SCRIPT)
        context.add_init_script(FRAMES_SCRIPT)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        self.frames(page, 1, until=BOOT_DONE)
        page.evaluate('() => { window.onblur = null }')
        page.evaluate(STARTUPS)
        return page

    def test_fade_duration(self):
        out = Path(os.environ.get('TUTORIAL_FADE_EVIDENCE_DIR', ROOT / 'artifacts/TASK-411'))
        out.mkdir(parents=True, exist_ok=True)
        page = self.open_clocked()
        self.assertEqual(page.evaluate('TUTORIAL_HINT.fadeSeconds'), 2.5)
        self.assertEqual(page.evaluate(HINT), {'visible': True, 'alpha': 1, 'time': 0})
        # Keep the run alive: a death would freeze the fade on the death screen
        page.evaluate('() => { onLethalDeath = () => {} }')
        page.mouse.move(1300, 250)
        page.mouse.down()
        self.assertTrue(page.evaluate('grapnel.throwed'))
        # 75, 144 and 150 physics steps of 1000/60 ms
        self.frames(page, 75)
        page.screenshot(path=str(out / 'hint-1.25s.png'))
        state = page.evaluate(HINT)
        self.assertTrue(state['visible'], state)
        self.assertAlmostEqual(state['time'], 1.25, delta=1e-6)
        self.assertAlmostEqual(state['alpha'], 0.5 ** 1.6, delta=1e-6)
        print(f"FADE 1.25s: alpha={state['alpha']:.9f} expected={0.5 ** 1.6:.9f} "
              f"visible={state['visible']} time={state['time']:.9f} hint-1.25s.png", flush=True)
        self.frames(page, 69)
        state = page.evaluate(HINT)
        self.assertTrue(state['visible'] and state['alpha'] > 0, state)
        print(f"FADE 2.4s: alpha={state['alpha']:.9f} > 0 visible={state['visible']} "
              f"time={state['time']:.9f}", flush=True)
        self.frames(page, 6)
        page.screenshot(path=str(out / 'hint-2.5s.png'))
        state = page.evaluate('({visible: TUTORIAL_HINT.visible, alpha: TUTORIAL_HINT.alpha, '
                              'time: TUTORIAL_HINT.time, done: TUTORIAL_HINT.done})')
        self.assertEqual(state, {'visible': False, 'alpha': 0, 'time': 2.5, 'done': True})
        print(f"FADE 2.5s: alpha={state['alpha']} visible={state['visible']} done={state['done']} "
              f"time={state['time']} hint-2.5s.png", flush=True)
        page.mouse.up()

    def test_lifecycle(self):
        out = Path(os.environ.get('TUTORIAL_LIFECYCLE_EVIDENCE_DIR', ROOT / 'artifacts/TASK-367'))
        out.mkdir(parents=True, exist_ok=True)
        page = self.open_clocked()
        self.assertIsNone(page.evaluate('document.getElementById("tutorial")'))

        # Boot run: full strength, the game is not blocked, nothing pressed
        full = {'visible': True, 'alpha': 1, 'time': 0}
        self.assertEqual(page.evaluate(HINT), full)
        y0 = page.evaluate('ninja.y')
        self.frames(page, 30)
        y1 = page.evaluate('ninja.y')
        self.assertNotEqual(y0, y1)
        self.assertEqual(page.evaluate(HINT), full)
        self.note(f'PASS boot: hint visible alpha 1; ninja.y {y0:.1f} -> {y1:.1f} '
              'over 30 frames with no input')

        # A death before any press (an idle ninja lands on the ground, so the
        # normal death path is taken by hand). No ad is ever due: the new run
        # starts at once (TASK-370 fast restart) and shows it again
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        self.assertEqual(page.evaluate(DEATH), FAST)
        self.assertEqual(page.evaluate(HINT), full)
        self.frames(page, 10)
        self.assertEqual(page.evaluate('[continueOffer.visible, runInProgress]'), [False, True])
        self.assertEqual(page.evaluate(HINT), full)
        self.note('PASS death before any press -> fast restart, no death screen: hint visible alpha 1')

        # A death would freeze the fade on the death screen; the captures
        # keep the run alive instead
        page.evaluate('() => { window.__onLethalDeath = onLethalDeath; onLethalDeath = () => {} }')
        page.mouse.move(1300, 250)
        page.mouse.down()
        self.assertTrue(page.evaluate('grapnel.throwed'))
        page.evaluate('draw()')
        page.screenshot(path=str(out / 'fade-0s.png'))
        self.note('PASS fade-0s.png: trusted press threw the grapnel', page.evaluate(HINT))
        self.frames(page, 60)
        page.screenshot(path=str(out / 'fade-1s.png'))
        state = page.evaluate(HINT)
        self.assertTrue(state['visible'] and state['alpha'] < 1, state)
        self.assertAlmostEqual(state['alpha'], (1 - 1 / 2.5) ** 1.6, places=6)
        self.note('PASS fade-1s.png', state)
        self.frames(page, 15)
        page.screenshot(path=str(out / 'fade-1.25s.png'))
        self.note('PASS fade-1.25s.png', page.evaluate(HINT))
        page.mouse.up()

        # A 3 s pause halfway freezes the fade
        before = page.evaluate(HINT)
        page.evaluate('menu.startPause()')
        self.frames(page, 180)
        self.assertEqual(page.evaluate(HINT), before)
        page.evaluate('menu.unPause()')
        self.note('PASS 3 s pause at t=1.25 s: hint unchanged', before)

        self.frames(page, 45)
        page.screenshot(path=str(out / 'fade-2s.png'))
        self.note('PASS fade-2s.png', page.evaluate(HINT))
        self.frames(page, 30)
        page.screenshot(path=str(out / 'fade-2.5s.png'))
        self.assertEqual(page.evaluate(HINT), {'visible': False, 'alpha': 0, 'time': 2.5})
        self.note('PASS fade-2.5s.png: faded out after 2.5 s of active time', page.evaluate(HINT))

        # After the fade neither a fast restart nor the mode switch shows it
        # again
        page.evaluate('() => { onLethalDeath = window.__onLethalDeath }')
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialDue()'))
        self.assertEqual(page.evaluate(DEATH), FAST)
        for _ in range(30):
            self.frames(page, 1)
            self.assertFalse(page.evaluate('TUTORIAL_HINT.visible'))
        self.assertEqual(page.evaluate('[continueOffer.visible, runInProgress]'), [False, True])
        self.leave_run(page, '() => { menu.startPause(); menu.backToMenu.click() }', check_hidden=True)
        self.frames(page, 30)
        self.assertEqual(page.evaluate('({version, visible: TUTORIAL_HINT.visible})'),
                         {'version': 'classic', 'visible': False})
        self.note('PASS after the fade: fast restart and mode switch keep the hint hidden')

        dismissed = page.evaluate(DISMISSED)
        self.assertEqual(len(dismissed), 1, dismissed)
        self.note('PASS PLATFORM.startup tutorial_dismissed x1', dismissed)
        self.assertIsNone(page.evaluate('document.getElementById("tutorial")'))
        self.note('PASS document.getElementById("tutorial") is null')

    def capture(self, page, name):
        """Shows the hint over the live run for a few frames, then screenshots."""
        page.evaluate('TUTORIAL_HINT.visible = true')
        page.evaluate('() => new Promise(r => { let n = 10; (function f() { --n ? requestAnimationFrame(f) : r() })() })')
        state = page.evaluate('''() => ({version, runInProgress, lines: TUTORIAL_HINT.lines,
            ninja: ninja.x !== undefined, key: TUTORIAL_HINT.spriteKey})''')
        page.screenshot(path=str(self.out / name))
        print('PASS capture', name, json.dumps(state, ensure_ascii=False), flush=True)
        return state

    def test_hint_drawn_without_per_frame_shadow_blur(self):
        page = self.open()
        page.evaluate(FREEZE)
        # The boot run shows the hint; hide it for the baseline
        page.evaluate('TUTORIAL_HINT.visible = false')
        hidden = page.evaluate(CENTRE)
        hidden_again = page.evaluate(CENTRE)
        page.evaluate('TUTORIAL_HINT.visible = true')
        shown = page.evaluate(CENTRE)
        noise = changed_pixels(hidden, hidden_again)
        drawn = changed_pixels(hidden, shown)
        self.assertGreater(drawn, 20 * max(noise, 50), (drawn, noise))
        print(f'PASS hint pixels: {drawn} centre pixels changed by the hint '
              f'(hidden-vs-hidden noise {noise})', flush=True)

        # The sprite is built; count main-context shadowBlur sets per 60 frames
        page.evaluate(SPY)
        counts = page.evaluate('''() => {
            const count = visible => {
                TUTORIAL_HINT.visible = visible
                window.__shadowBlurSets = 0
                const built = TUTORIAL_HINT.buildCount
                for (let i = 0; i < 60; ++i) draw()
                return {sets: window.__shadowBlurSets, builds: TUTORIAL_HINT.buildCount - built}
            }
            return {hidden: count(false), visible: count(true)}
        }''')
        self.assertEqual(counts['visible']['builds'], 0)
        self.assertEqual(counts['visible']['sets'] - counts['hidden']['sets'], 0, counts)
        print('PASS shadowBlur sets over 60 frozen frames:', counts,
              '-> attributable to hint: 0', flush=True)

    def test_language_change_rebuilds_sprite_once(self):
        page = self.open()
        self.capture(page, 'hint-desktop.png')
        before = page.evaluate('({builds: TUTORIAL_HINT.buildCount, lines: TUTORIAL_HINT.lines})')
        self.assertEqual(before['lines'][0], 'HOLD')
        page.evaluate("setLanguage('ru')")
        state = self.capture(page, 'hint-ru.png')
        after = page.evaluate('({builds: TUTORIAL_HINT.buildCount, lines: TUTORIAL_HINT.lines})')
        self.assertEqual(after['builds'] - before['builds'], 1, (before, after))
        self.assertEqual(after['lines'], ['ДЕРЖИ', '— ЗАЦЕПИШЬСЯ', 'ДВИГАЙСЯ ВПРАВО  →'])
        self.assertTrue(state['key'].startswith('ru|mouse|'), state['key'])
        print('PASS language: builds', before['builds'], '->', after['builds'],
              json.dumps(after['lines'], ensure_ascii=False), flush=True)

    def test_mobile_touch_label(self):
        page = self.open((844, 390), dpr=3, touch=True)
        state = self.capture(page, 'hint-mobile.png')
        self.assertEqual(state['lines'][0], 'TOUCH & HOLD')
        self.assertTrue(state['key'].startswith('en|touch|'), state['key'])

    def test_zz_compare_sheet(self):
        """compare.png: each capture beside its concept-B reference."""
        from PIL import Image
        pairs = [('hint-desktop.png', 'concept-B-desktop.png'),
                 ('hint-mobile.png', 'concept-B-mobile.png'),
                 ('hint-ru.png', 'concept-B-desktop-ru.png')]
        rows = []
        for ours, concept in pairs:
            images = [Image.open(self.out / ours).convert('RGB'), Image.open(CONCEPT / concept).convert('RGB')]
            images = [im.resize((960, round(im.height * 960 / im.width))) for im in images]
            row = Image.new('RGB', (1940, max(im.height for im in images)), 'black')
            row.paste(images[0], (0, 0))
            row.paste(images[1], (980, 0))
            rows.append(row)
        sheet = Image.new('RGB', (1940, sum(r.height for r in rows) + 20 * (len(rows) - 1)), 'black')
        y = 0
        for row in rows:
            sheet.paste(row, (0, y))
            y += row.height + 20
        sheet.save(self.out / 'compare.png')
        print('PASS compare.png', sheet.size, 'left: game, right: concept B', flush=True)


if __name__ == '__main__':
    unittest.main()
