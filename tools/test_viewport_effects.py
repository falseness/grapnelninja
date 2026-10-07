"""Run the viewport checker's real effects scenario in Chromium.

What must stay true whatever the art looks like: obstacle geometry scales with
the logical viewport (the checker's check_geometry, which test_scaled_geometry
also exercises), no canvas call gets a NaN/Infinity argument, and both modes,
the menu and the pause screen draw without browser errors.

This suite no longer requires pixel-identical screenshots or matching draw-call
traces against rev a6b41aa: the graphics overhaul changes the look on purpose.
Look changes are reviewed by eye with tools/visual_gallery.py and rev-vs-rev
with tools/render_snapshot.py.
"""
import ast
import importlib.util
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image

from browser_test_support import logical_size, start_browser_test
from verification_scenarios import expected, frames, setup
from verification_support import assert_near


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / 'tools/verify-viewport-percentages.py'
SPEC = importlib.util.spec_from_file_location('viewport_checker', CHECKER_PATH)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def load_check_geometry():
    """The checker's check_geometry, which is nested in its main()."""
    tree = ast.parse(CHECKER_PATH.read_text())
    near = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'near')
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    check = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == 'check_geometry')
    namespace = {'assert_near': assert_near}
    exec(compile(ast.Module(body=[near, check], type_ignores=[]), str(CHECKER_PATH), 'exec'), namespace)
    return namespace['check_geometry']


CHECK_GEOMETRY = load_check_geometry()

# Records every 2D canvas/gradient call or numeric property set whose arguments
# hold a non-finite number (canvas silently ignores most of those)
FINITE_GUARD = '''(() => {
    window.canvasCalls = 0
    window.nonFinite = []
    const bad = v => typeof v === 'number' && !Number.isFinite(v)
    for (const proto of [CanvasRenderingContext2D.prototype, CanvasGradient.prototype]) {
        for (const key of Object.getOwnPropertyNames(proto)) {
            const d = Object.getOwnPropertyDescriptor(proto, key)
            if (typeof d.value == 'function' && key != 'constructor') {
                const f = d.value
                proto[key] = function (...args) {
                    canvasCalls++
                    if (args.some(bad))
                        nonFinite.push([key, ...args.map(String)])
                    return f.apply(this, args)
                }
            } else if (d.set) {
                Object.defineProperty(proto, key, {...d, set(v) {
                    canvasCalls++
                    if (bad(v))
                        nonFinite.push(['set', key, String(v)])
                    d.set.call(this, v)
                }})
            }
        }
    }
})()'''

# The checker's 1920x1080 reference, a 4:3 window and a window wider than 2:1
# (both clamp the logical width; the logical height is always 1080)
REFERENCE = (1920, 1080)
VIEWPORTS = [(1440, 1080), (1600, 720)]


class ViewportEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open_page(self, viewport):
        page = self.browser.new_page(viewport={'width': viewport[0], 'height': viewport[1]})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        page.add_init_script(CHECKER.init)
        page.add_init_script(FINITE_GUARD)
        page.goto(self.url)
        # Since TASK-117 boot() waits for animation frames before start(),
        # and the checker's init script stubs requestAnimationFrame: run
        # the rest of boot by hand (draw the menu, hide #loading)
        page.wait_for_function("document.getElementById('loading-progress')"
                               ".textContent == 'Starting...'")
        page.evaluate("() => { start(); document.getElementById('loading').hidden = true }")
        self.assertEqual(page.evaluate('[width, height]'), list(logical_size(*viewport)), viewport)
        return page, errors

    def assert_clean(self, page, errors, label):
        guard = page.evaluate('({calls: canvasCalls, nonFinite: nonFinite.slice(0, 20)})')
        self.assertGreater(guard['calls'], 0, label)
        self.assertEqual(guard['nonFinite'], [], f'{label}: non-finite canvas arguments')
        self.assertEqual(errors, [], f'{label}: browser errors')
        return guard['calls']

    def test_effects_render_finite_without_errors(self):
        passed = []
        for viewport in [REFERENCE, *VIEWPORTS]:
            for mode in ['classic', 'bad']:
                label = f'{mode} {viewport[0]}x{viewport[1]}'
                with self.subTest(mode=mode, viewport=viewport):
                    page, errors = self.open_page(viewport)
                    try:
                        effects = page.evaluate(CHECKER.scenario, mode)
                        for part in ['particles', 'trails', 'hud', 'screenEffects']:
                            self.assertGreater(len(effects['parts'][part]), 5, part)
                        for stage in ['game', 'menu', 'pause']:
                            page.evaluate(f'drawTest{stage.title()}()')
                            with Image.open(BytesIO(page.screenshot())) as image:
                                # Something was drawn: not a single flat colour
                                self.assertIsNone(image.getcolors(1), (label, stage))
                        calls = self.assert_clean(page, errors, label)
                    finally:
                        page.close()
                    print(f'PASS {label}: effects scenario + game/menu/pause drawn; '
                          f'{calls} canvas calls, non-finite args=0, browser errors=0', flush=True)
                    passed.append(label)
        self.assertEqual(len(passed), 6)

    def sample_geometry(self, viewport):
        page, errors = self.open_page(viewport)
        try:
            raw = {}
            for name, types in zip(frames, expected):
                sample = page.evaluate(setup, name)
                self.assertEqual([e['type'] for e in sample['initial']], types, name)
                raw[name] = sample['raw']
            self.assert_clean(page, errors, f'geometry {viewport}')
            return raw
        finally:
            page.close()

    def test_logical_viewport_geometry(self):
        reference = self.sample_geometry(REFERENCE)
        for viewport in VIEWPORTS:
            logical = logical_size(*viewport)
            scaled = self.sample_geometry(viewport)
            for name in frames:
                with self.subTest(viewport=viewport, frame=name):
                    CHECK_GEOMETRY(reference[name], scaled[name], *logical)
            print(f'PASS {viewport[0]}x{viewport[1]} (logical {logical[0]}x{logical[1]}): '
                  f'{len(frames)} obstacle templates scale from 1920x1080 by the logical axes '
                  '(check_geometry); non-finite args=0, browser errors=0', flush=True)


if __name__ == '__main__':
    unittest.main()
