"""URL A/B switches (render/abswitches.js, TASK-416).

?off=<name> skips that draw() layer: over 60 draw() calls its function runs
0 times while every other layer runs 60 times (bloom only when
STYLE.features.bloom, which draw() checks itself). Counts are spied on the
original layer functions, so they are independent of the switch's no-op.
?scale=0.5 halves canvas.width/height versus no params while
clientWidth/clientHeight stay equal, and a tap still throws the grapnel.
?off=bogus logs exactly one console.warn naming it. Physics is untouched.
Set AB_SWITCHES_EVIDENCE_DIR=<absolute dir> to write off-lights.png,
off-colorGrade.png and scale-0.5.png there.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import wait_for_boot
from game_harness import READY, canvas_to_viewport, open_game, start_game_test, switch_mode

ROOT = Path(__file__).resolve().parent.parent
LAYERS = {
    'background': 'drawBackgroundLayer',
    'lights': 'drawLightsLayer',
    'behindForegroundParticles': 'drawBehindForegroundParticlesLayer',
    'playerTrail': 'drawPlayerTrailLayer',
    'world': 'drawWorldLayer',
    'particlesAndTrails': 'drawParticlesAndTrailsLayer',
    'bloom': 'drawBloomLayer',
    'playerGlow': 'drawPlayerGlowLayer',
    'colorGrade': 'drawColorGradeLayer',
    'player': 'drawPlayerLayer',
    'tutorialHint': 'drawTutorialHintLayer',
    'ui': 'drawUILayer',
    'fpsCounter': 'drawFpsCounterLayer',
}
FRAMES = 60
VIEWPORT = {'width': 844, 'height': 390}

# Prepended to render/abswitches.js: wraps the original layer functions
# right before the switch replaces any of them, so a skipped layer counts 0.
SPY_PREFIX = '''window.__layerCalls = {}
for (const [name, global] of Object.entries(%s)) {
    const fn = window[global]
    window[global] = function() {
        window.__layerCalls[name] = (window.__layerCalls[name] || 0) + 1
        return fn.apply(this, arguments)
    }
}
'''


def evidence_dir():
    path = os.environ.get('AB_SWITCHES_EVIDENCE_DIR')
    if not path:
        return None
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


class AbSwitchesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = evidence_dir()

    def open(self, query, touch=False, spy=False):
        options = dict(has_touch=True, is_mobile=True, device_scale_factor=2) if touch else {}
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT, **options)
        self.addCleanup(context.close)
        warnings = []
        # The offline SDK stub's own 'Playgama Bridge disabled' warning is not ours
        page.on('console', lambda m: warnings.append(m.text)
                if m.type == 'warning' and not m.text.startswith('Playgama Bridge') else None)
        if spy:
            source = (ROOT / 'render' / 'abswitches.js').read_text()
            body = SPY_PREFIX % json.dumps(LAYERS) + source
            page.route('**/render/abswitches.js', lambda route: route.fulfill(
                content_type='application/javascript', body=body))
        page.goto(self.url + 'index.html' + query)
        wait_for_boot(page)
        page.wait_for_function(READY)
        self.addCleanup(lambda: self.assertEqual((errors['console'], errors['page']), ([], [])))
        return page, warnings

    def count_layer_calls(self, page):
        return page.evaluate('''frames => {
            cancelAnimationFrame(game)
            window.__layerCalls = {}
            for (let i = 0; i < frames; i++) draw()
            return window.__layerCalls
        }''', FRAMES)

    def test_off_each_layer(self):
        for name in LAYERS:
            with self.subTest(layer=name):
                page, warnings = self.open('?off=' + name, spy=True)
                page.evaluate('() => { TUTORIAL_HINT.visible = true }')
                bloom = page.evaluate('() => STYLE.features.bloom')
                calls = self.count_layer_calls(page)
                expected = {n: FRAMES for n in LAYERS if n != name and (n != 'bloom' or bloom)}
                actual = {n: calls.get(n, 0) for n in LAYERS}
                print(f'off={name}: {name}={actual[name]} others={dict((n, actual[n]) for n in LAYERS if n != name)}'
                      f' (bloom feature={bloom})', flush=True)
                self.assertEqual(actual[name], 0)
                for n, count in expected.items():
                    self.assertEqual(actual[n], count, n)
                self.assertEqual(page.evaluate('AB_SWITCHES.off'), [name])
                self.assertEqual(warnings, [])
                if self.evidence and name in ('lights', 'colorGrade'):
                    page.screenshot(path=str(self.evidence / f'off-{name}.png'))
        print(f'PASS off: each of {len(LAYERS)} layers skipped alone ({FRAMES} frames)', flush=True)

    def test_scale_half(self):
        dims = '() => ({width: canvas.width, height: canvas.height, clientWidth: canvas.clientWidth, clientHeight: canvas.clientHeight})'
        plain, _ = self.open('', touch=True)
        base = plain.evaluate(dims)
        page, warnings = self.open('?scale=0.5', touch=True)
        half = page.evaluate(dims)
        print(f'default: {base}', flush=True)
        print(f'scale=0.5: {half}', flush=True)
        self.assertEqual((half['width'], half['height']), (round(base['width'] / 2), round(base['height'] / 2)))
        self.assertEqual((half['clientWidth'], half['clientHeight']), (base['clientWidth'], base['clientHeight']))
        self.assertEqual(warnings, [])

        switch_mode(page, 'classic')
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 300)
        page.evaluate('''() => {
            window.__throws = 0
            const orig = Grapnel.prototype.calcSpeed
            Grapnel.prototype.calcSpeed = function () { window.__throws++; return orig.apply(this, arguments) }
        }''')
        point = canvas_to_viewport(page, page.evaluate('menu.width') * 0.6, page.evaluate('menu.height') * 0.3)
        page.touchscreen.tap(point['x'], point['y'])
        page.wait_for_timeout(300)
        throws = page.evaluate('window.__throws')
        print(f'scale=0.5 tap at {point}: grapnel throws={throws}', flush=True)
        self.assertEqual(throws, 1)
        if self.evidence:
            page.screenshot(path=str(self.evidence / 'scale-0.5.png'))
        print('PASS scale: backing store halved, CSS size equal, tap throws the grapnel', flush=True)

    def test_bogus_warns_once(self):
        page, warnings = self.open('?off=bogus')
        print(f'off=bogus warnings: {warnings}', flush=True)
        self.assertEqual(len(warnings), 1)
        self.assertIn('bogus', warnings[0])
        self.assertEqual(page.evaluate('AB_SWITCHES'), {'off': [], 'scale': 1})
        page2, warnings2 = self.open('?scale=3&off=lights,nope')
        print(f'scale=3&off=lights,nope warnings: {warnings2}', flush=True)
        self.assertEqual(len(warnings2), 1)
        self.assertIn('scale=3', warnings2[0])
        self.assertIn('nope', warnings2[0])
        self.assertEqual(page2.evaluate('AB_SWITCHES'), {'off': ['lights'], 'scale': 1})
        print('PASS warn: unknown names / bad scale -> exactly one console.warn naming them', flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
