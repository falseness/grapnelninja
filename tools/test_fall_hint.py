"""TASK-720: the first long fall of a Grapple Over run suggests double grapnel mode.

Boots the real index.html and drives genuine free falls (production physics()
and LONG_FALL.step()) from 9000 above the spawn: in single mode the run's first
long fall shows the climb.fallHint text, later falls the random LONG_FALL_MESSAGES
entries; in double mode no hint; after a save and real page reload following
fall 1 no second hint; a restart (new run) shows it again. The hint fades like
any message (FALL_MESSAGE.durationMs). Crops of the drawn hint in en and ru.

FALL_HINT_EVIDENCE_DIR=DIR writes messages.json, hint-en.png and hint-ru.png.

    FALL_HINT_EVIDENCE_DIR=DIR python3 -m unittest discover -s tools -p test_fall_hint.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_long_fall_messages import SETUP, RUN, OPEN_AIR, RENDER_SETUP, CLIMB_KEY, MESSAGES, HINT

ROOT = Path(__file__).resolve().parent.parent
OUT = os.environ.get('FALL_HINT_EVIDENCE_DIR')
RU_HINT = 'Может, попробуешь режим двойного крюка?'
RESULT = {}

# Genuine free fall from 9000 above the spawn until the detector emits; the
# player is then put back near the spawn and the message state is read.
FALL = '''() => {
    const before = LONG_FALL.emitted
    const l = floors[0].level
    ninja.x = l.bounds.right + 4000; ninja.y = l.spawn.y - 9000; ninja.speedX = 0; ninja.speedY = 0
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null})
    let ticks = 0
    for (; ticks < 4000 && LONG_FALL.emitted === before; ticks++) physics()
    const e = LONG_FALL.event
    ninja.x = l.spawn.x; ninja.y = l.spawn.y - 5; ninja.speedX = 0; ninja.speedY = 0
    return {emitted: LONG_FALL.emitted - before, ticks, id: e && e.id, hint: !!(e && e.hint),
        text: e && LONG_FALL.text(e), index: e && e.index, displacement: e && Math.round(e.displacement),
        mode: floors[0].grapnelMode, fallHintShown: floors[0].fallHintShown}
}'''

# Fade of the current event through the production FALL_MESSAGE.advance().
FADE = '''() => {
    const F = FALL_MESSAGE, out = {durationMs: F.durationMs}
    F.sync(); out.start = [F.elapsedMs, F.opacity(), F.expired]
    F.advance(3000); out.at3000 = [F.elapsedMs, +F.opacity().toFixed(6), F.expired]
    F.advance(2999); out.at5999 = [F.elapsedMs, +F.opacity().toFixed(6), F.expired]
    F.advance(1); out.at6000 = [F.elapsedMs, +F.opacity().toFixed(6), F.expired]
    return out
}'''


class FallHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if OUT and RESULT:
            Path(OUT).mkdir(parents=True, exist_ok=True)
            (Path(OUT) / 'messages.json').write_text(json.dumps(RESULT, ensure_ascii=False, separators=(',', ':')),
                                                     encoding='utf-8')

    def open(self, context=None, freeze=True):
        if context is None:
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
            self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        if page.evaluate('menu.gamePaused'):
            page.evaluate('menu.unPause()')
        page.evaluate(SETUP)
        return page

    def falls(self, page, n):
        return [page.evaluate(FALL) for _ in range(n)]

    def check_normal(self, fall):
        self.assertEqual(fall['emitted'], 1, fall)
        self.assertFalse(fall['hint'], fall)
        self.assertIn(fall['text'], MESSAGES)
        self.assertEqual(fall['text'], MESSAGES[fall['index']])

    def test_01_single_double_reload_restart(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
        self.addCleanup(context.close)
        page = self.open(context)
        # Single mode: 3 long falls.
        single = self.falls(page, 3)
        self.assertEqual(single[0]['emitted'], 1)
        self.assertEqual((single[0]['hint'], single[0]['text'], single[0]['index']), (True, HINT, -1))
        self.assertTrue(single[0]['displacement'] > 4000)
        for f in single[1:]:
            self.check_normal(f)
        fade_normal = page.evaluate(FADE)
        RESULT['single'] = {'mode': 'single', 'falls': single,
                            'fall1IsHint': single[0]['text'] == HINT,
                            'falls23FromPool': all(f['text'] in MESSAGES for f in single[1:])}
        # Restart: a new run shows the hint again on its first fall.
        page.evaluate('() => CLIMB_UI.restart()')
        page.evaluate('() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
        self.assertFalse(page.evaluate('floors[0].fallHintShown'))
        restart = self.falls(page, 2)
        self.assertEqual((restart[0]['hint'], restart[0]['text']), (True, HINT))
        self.check_normal(restart[1])
        fade_hint = page.evaluate(FADE)
        # Same fade timing as a normal message.
        self.assertEqual(fade_hint, fade_normal)
        self.assertEqual(fade_hint['durationMs'], 6000)
        self.assertEqual(fade_hint['at3000'], [3000, 0.25, False])
        self.assertEqual(fade_hint['at6000'][2], True)
        RESULT['restart'] = {'falls': restart, 'fall1IsHint': restart[0]['text'] == HINT}
        RESULT['fade'] = {'hint': fade_hint, 'normal': fade_normal, 'identical': fade_hint == fade_normal}
        self.assertEqual(page.errors, [])

        # Save and real reload after fall 1: no second hint.
        page = self.open(context)
        page.evaluate('() => CLIMB_UI.restart()')
        page.evaluate('() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
        first = page.evaluate(FALL)
        self.assertEqual((first['hint'], first['text']), (True, HINT))
        page.evaluate('() => PROGRESS.flushClimb()')
        page.wait_for_function('k => { const v = JSON.parse(localStorage.getItem(k) || "null")'
                               '; return v && v.player.y === ninja.y }', arg=CLIMB_KEY)
        saved = json.loads(page.evaluate('k => localStorage.getItem(k)', CLIMB_KEY))
        self.assertIs(saved['fallHintShown'], True)
        errors = list(page.errors)
        page.close()
        page2 = self.open(context)
        reloaded = page2.evaluate('floors[0].fallHintShown')
        self.assertIs(reloaded, True)
        after = self.falls(page2, 2)
        for f in after:
            self.check_normal(f)
        RESULT['reload'] = {'fall1': first, 'savedFallHintShown': saved['fallHintShown'],
                            'afterReloadFallHintShown': reloaded, 'fallsAfterReload': after,
                            'secondHint': any(f['hint'] for f in after)}
        self.assertEqual(errors + page2.errors, [])

        # Double mode: same 3 falls, no hint (the first fall uses the normal list).
        page3 = self.open()
        page3.evaluate('() => CLIMB_UI.restart()')
        page3.evaluate('() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game); setGrapnelMode("double") }')
        double = self.falls(page3, 3)
        for f in double:
            self.check_normal(f)
            self.assertEqual(f['mode'], 'double')
        RESULT['double'] = {'mode': 'double', 'falls': double, 'anyHint': any(f['hint'] for f in double)}
        # Old saves without the field load as a run whose first fall still shows the hint.
        old = page3.evaluate('''() => { CLIMB_UI.restart(); window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
            const s = captureClimbState(); delete s.fallHintShown; restoreClimbState(s)
            window.requestAnimationFrame = () => 0; return floors[0].fallHintShown }''')
        self.assertIs(old, False)
        RESULT['oldSaveDefault'] = old
        self.assertEqual(page3.errors, [])

    def test_02_crops(self):
        RESULT['crops'] = {}
        for lang, text in (('en', HINT), ('ru', RU_HINT)):
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
            self.addCleanup(context.close)
            page = self.open(context)
            page.evaluate('() => CLIMB_UI.restart()')
            page.evaluate('() => { window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
            page.evaluate('l => setLanguage(l)', lang)
            if page.evaluate('menu.gamePaused'):
                page.evaluate('menu.unPause()')
            page.evaluate(RENDER_SETUP)
            page.evaluate('() => FALL_MESSAGE.setRandom((s => () => s.shift())([3.5 / 6, 0.5]))')
            fall = page.evaluate(FALL)
            page.evaluate('() => { FALL_MESSAGE.setRandom(null); FRAMES(1) }')
            st = page.evaluate('''() => { const L = FALL_MESSAGE.layout, c = getCanvasCssRect()
                return {text: L && L.text, visible: FALL_MESSAGE.visible(), blits: BLITS.length, fitted: L && L.fitted,
                    bounds: L && L.bounds, canvas: {left: c.left, top: c.top}, opacity: FALL_MESSAGE.opacity(),
                    language: I18N.language} }''')
            self.assertEqual((fall['hint'], st['text'], st['visible'], st['fitted'], st['language']),
                             (True, text, True, True, lang))
            self.assertGreater(st['blits'], 0)
            b, c = st['bounds'], st['canvas']
            clip = {'x': c['left'] + b['left'] - 6, 'y': c['top'] + b['top'] - 6,
                    'width': b['right'] - b['left'] + 12, 'height': b['bottom'] - b['top'] + 12}
            if OUT:
                Path(OUT).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(OUT) / ('hint-%s.png' % lang)), clip=clip)
            RESULT['crops'][lang] = {'text': st['text'], 'fitted': st['fitted'], 'opacity': st['opacity'],
                                     'clip': {k: round(v, 1) for k, v in clip.items()}}
            self.assertEqual(page.errors, [])


if __name__ == '__main__':
    unittest.main()
