"""Compare the viewport checker's real effects scenario in Chromium."""
import importlib.util
import json
from io import BytesIO
from pathlib import Path
import subprocess
import unittest

from PIL import Image, ImageChops

from browser_test_support import start_browser_test
from verification_support import baseline_route, load_baseline_sources


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'viewport_checker', ROOT / 'tools/verify-viewport-percentages.py')
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


# TASK-137 resized and centred the main menu 'fps counter' checkbox on
# purpose: the menu and pause screenshots are compared with that row (box + label +
# glow, screenshot px) masked out on both sides.
FPS_ROW = '''() => {
    const c = menu.mainFpsCounterCheckbox
    ctx.save()
    ctx.font = c.fontSize
    const labelWidth = ctx.measureText(c.label).width
    ctx.restore()
    const r = canvas.getBoundingClientRect()
    const sx = r.width / width, sy = r.height / height
    const pad = 2 * STYLE.ui.buttonShadowBlur + STYLE.ui.buttonLineWidth
    return [Math.floor(r.left + (c.x - pad) * sx), Math.floor(r.top + (c.y - c.size / 2 - pad) * sy),
            Math.ceil(r.left + (c.x + c.size * 1.55 + labelWidth + pad) * sx),
            Math.ceil(r.top + (c.y + c.size / 2 + pad) * sy)]
}'''
# The masked row stays a small part of the 1920x1080 menu
FPS_ROW_MAX_HEIGHT = 0.2


def mask_fps_row(image, box):
    masked = image.copy()
    masked.paste((0, 0, 0, 0) if masked.mode == 'RGBA' else (0, 0, 0), box)
    return masked


def strip_fps_row(calls):
    """Menu canvas calls without the save..restore blocks that measure or draw the 'fps counter' label."""
    calls = list(calls)
    while True:
        hits = [i for i, c in enumerate(calls) if c[0] in ('fillText', 'measureText') and c[1] == 'fps counter']
        if not hits:
            return calls
        start = max(i for i in range(hits[0]) if calls[i] == ['save'])
        end = next(i for i in range(hits[0], len(calls)) if calls[i] == ['restore'])
        calls[start:end + 1] = []


GRADIENT_CALLS = ('createLinearGradient', 'createRadialGradient')


def split_gradients(parts):
    """Per-part draw calls without the gradient constructors, plus the distinct constructors.

    The TASK-161 merge builds the base vignette together with the linear gradient
    and caches both by bounds (render/effects.js getGradients): the vignette's
    createRadialGradient moves ahead of the first fillStyle, and later parts reuse
    the cached pair instead of building it again. The gradients and every draw
    stay the same."""
    created = {json.dumps(c) for calls in parts.values() for c in calls if c[0] in GRADIENT_CALLS}
    return ({part: [c for c in calls if c[0] not in GRADIENT_CALLS] for part, calls in parts.items()},
            sorted(created))


class ViewportEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        # Files of the baseline tree: later additions (platform.js) do not exist there
        files = subprocess.check_output(
            ['git', 'ls-tree', '-r', '--name-only', 'a6b41aa'],
            cwd=ROOT, text=True).splitlines()
        cls.baseline = load_baseline_sources('a6b41aa', files)
        # TASK-112 capitalised the menu title on purpose; apply it to the baseline too
        cls.baseline['menu.js'] = cls.baseline['menu.js'].replace(b"'Grapnel ninja'", b"'Grapnel Ninja'")
        # TASK-126 added the language toggle to the menu: draw the current
        # languagebutton.js (with i18n.js) in the baseline too
        # TASK-127: the button reports to LAYOUT_PROBE (menu.js) and sizes from
        # minTouchSize (gameoptions.js), both newer than the baseline
        cls.baseline['buttonshim.js'] = (
            b"const LAYOUT_PROBE = {rect() {}, text() {}}\n"
            b"function minTouchSize() { const h = canvas.getBoundingClientRect().height\n"
            b"    return h > 0 ? 44 * height / h : 0 }\n")
        # TASK-127 capped button labels at 0.8 of the button height
        for old in [b"this.getFittedTextSize(text.text, this.background.height)",
                    b"button.getFittedTextSize(button.text.text, height)"]:
            assert cls.baseline['menu.js'].count(old) == 1, old
            cls.baseline['menu.js'] = cls.baseline['menu.js'].replace(old, old[:-1] + b" * 0.8)")
        for name, old, new in [
                ('index.html', b"<script src = 'menu.js'></script>",
                 b"<script src = 'menu.js'></script><script src = 'buttonshim.js'></script>"
                 b"<script src = 'i18n.js'></script><script src = 'languagebutton.js'></script>"),
                ('menu.js', b"this.timeInGame.draw()\n",
                 b"this.timeInGame.draw()\nLANGUAGE_BUTTON.draw()\n")]:
            assert cls.baseline[name].count(old) == 1, (name, old)
            cls.baseline[name] = cls.baseline[name].replace(old, new)

    def sample(self, mode, baseline):
        page = self.browser.new_page(viewport={'width': 1920, 'height': 1080})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        try:
            page.add_init_script(CHECKER.init)
            if baseline:
                page.route('**/*', baseline_route(self.baseline))
            page.goto(self.url)
            if not baseline:
                # Since TASK-117 boot() waits for animation frames before start(),
                # and the checker's init script stubs requestAnimationFrame: run
                # the rest of boot by hand (draw the menu, hide #loading)
                page.wait_for_function("document.getElementById('loading-progress')"
                                       ".textContent == 'Starting...'")
                page.evaluate("() => { start(); document.getElementById('loading').hidden = true }")
            effects = page.evaluate(CHECKER.scenario, mode)
            for part in ['particles', 'trails', 'hud', 'screenEffects']:
                self.assertGreater(len(effects['parts'][part]), 5, part)
            images = {}
            for stage, function in [('game', 'drawTestGame'),
                                    ('menu', 'drawTestMenu'),
                                    ('pause', 'drawTestPause')]:
                page.evaluate(function + '()')
                with Image.open(BytesIO(page.screenshot())) as image:
                    images[stage] = image.copy()
                if stage == 'menu':
                    images['menu_fps_row'] = page.evaluate(FPS_ROW)
            return effects, images
        finally:
            page.close()
            self.assertEqual(errors, [], f'{mode} baseline={baseline}: browser errors')

    def test_deterministic_effects_baseline_current(self):
        passed = []
        for mode in ['classic', 'bad']:
            with self.subTest(mode=mode):
                old, old_images = self.sample(mode, baseline=True)
                new, new_images = self.sample(mode, baseline=False)
                a, b = old_images['menu_fps_row'], new_images['menu_fps_row']
                row = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                self.assertLess(row[3] - row[1], FPS_ROW_MAX_HEIGHT * old_images['menu'].height, row)
                # drawTestPause paints the panel over the menu frame, so the row shows there too
                for image in (old_images, new_images):
                    for stage in ['menu', 'pause']:
                        image[stage] = mask_fps_row(image[stage], row)
                for stage in ['game', 'menu', 'pause']:
                    self.assertEqual(old_images[stage].size, new_images[stage].size)
                    self.assertIsNone(ImageChops.difference(
                        old_images[stage], new_images[stage]).getbbox(), (mode, stage))
                for effects in (old, new):
                    effects['parts']['menu'] = strip_fps_row(effects['parts']['menu'])
                    effects['parts'], effects['gradients'] = split_gradients(effects['parts'])
                for field in ['parts', 'gradients', 'particles', 'shake', 'quality', 'panel']:
                    CHECKER.near(old[field], new[field], mode + '.' + field)
                CHECKER.near(CHECKER.normalized_style(old['style']),
                             CHECKER.normalized_style(new['style']))
                print(f'PASS {mode} baseline a6b41aa/current 1920x1080: '
                      f'game/menu/pause pixel equality (menu fps row {row} masked on menu/pause); '
                      'normalized effects equality (menu fps row calls stripped); '
                      'browser console/page errors=0', flush=True)
                passed.append(mode)
        self.assertEqual(passed, ['classic', 'bad'])
        print('PASS deterministic effects baseline/current: classic,bad', flush=True)


if __name__ == '__main__':
    unittest.main()
