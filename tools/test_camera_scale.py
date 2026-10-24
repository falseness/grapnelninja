"""TASK-688: fixed Grapple Over camera scale 0.25 (classic/bad unchanged, no zoom)."""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPPLE_OVER_SCALE = 0.25
PREVIOUS_SCALE = 0.375
# Production scripts: everything index.html loads, excluding tools/ fixtures.
PRODUCTION_JS = sorted(p for p in ROOT.rglob('*.js')
                       if not {'artifacts', 'screenshots', 'node_modules', 'tools', '.git'} & set(p.relative_to(ROOT).parts))


def mode_definitions():
    """Evaluate gameoptions.js's MODE_DEFINITIONS literal in node."""
    source = (ROOT / 'gameoptions.js').read_text()
    block = re.search(r'const MODE_DEFINITIONS = Object\.freeze\(\{.*?\n\}\)', source, re.S).group(0)
    script = block + '\nprocess.stdout.write(JSON.stringify(MODE_DEFINITIONS))'
    return json.loads(subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True).stdout)


class CameraScaleConfigTests(unittest.TestCase):
    def test_grapple_over_fixed_scale(self):
        modes = mode_definitions()
        self.assertEqual(modes['grapple_over']['cameraScale'], GRAPPLE_OVER_SCALE)
        # Range/profile fields are untouched by the camera change.
        self.assertEqual({k: v for k, v in modes['grapple_over'].items() if k != 'cameraScale'},
                         dict(acquisitionRadius=1080, upgradedAcquisitionRadius=1620,
                              rangeUpgradeSection='S05', hudStyle='classic'))

    def test_classic_and_bad_unchanged(self):
        modes = mode_definitions()
        self.assertEqual(modes['classic'], dict(cameraScale=1, hudStyle='classic'))
        self.assertEqual(modes['bad'], dict(cameraScale=1 / 2.2, hudStyle='bad'))
        self.assertEqual(sorted(modes), ['bad', 'classic', 'grapple_over'])

    def test_view_is_fifty_percent_larger(self):
        # Visible world extent is width/scale and height/scale: 0.375/0.25 = 1.5x per axis,
        # objects drawn at 0.25/0.375 = 2/3 of their former screen size.
        self.assertAlmostEqual(PREVIOUS_SCALE / GRAPPLE_OVER_SCALE, 1.5)
        self.assertAlmostEqual(GRAPPLE_OVER_SCALE / PREVIOUS_SCALE, 2 / 3)
        for width, height in ((1920, 1080), (1280, 720)):
            self.assertAlmostEqual((width / GRAPPLE_OVER_SCALE) / (width / PREVIOUS_SCALE), 1.5)
            self.assertAlmostEqual((height / GRAPPLE_OVER_SCALE) / (height / PREVIOUS_SCALE), 1.5)

    def test_scale_table_derives_from_definitions(self):
        source = (ROOT / 'gameoptions.js').read_text()
        self.assertIn('const scale = Object.fromEntries(Object.entries(MODE_DEFINITIONS)\n'
                      '    .map(([id, definition]) => [id, definition.cameraScale]))', source)
        # Exactly one fixed cameraScale per mode; no other assignment of the scale table.
        self.assertEqual(len(re.findall(r'cameraScale:', source)), 3)
        for path in PRODUCTION_JS:
            text = path.read_text(errors='replace')
            self.assertIsNone(re.search(r'\bscale\s*(\[[^\]]*\]|\.\w+)\s*[-+*/]?=(?!=)', text), path)

    def test_no_zoom_controls_or_automatic_zoom(self):
        zoom_identifiers = re.compile(r'\b(zoom\w*|setZoom|cameraZoom|autoZoom)\s*[=(:]', re.I)
        checked = 0
        for path in PRODUCTION_JS:
            text = path.read_text(errors='replace')
            checked += 1
            self.assertIsNone(zoom_identifiers.search(text), path)
            self.assertNotIn('cameraScale =', text, path)
        self.assertGreater(checked, 20)
        # The only wheel listener suppresses page scrolling; it never touches the scale.
        events = (ROOT / 'events.js').read_text()
        wheel = re.search(r"addEventListener\('wheel', function\(event\)\s*\{(.*?)\}", events, re.S).group(1)
        self.assertEqual(wheel.strip(), 'event.preventDefault()')
        html = (ROOT / 'index.html').read_text()
        self.assertNotRegex(html, r'(?i)id="[^"]*zoom')

    def test_hud_sizes_cancel_world_scale(self):
        # HUD text/markers are drawn inside the world transform and divide by scale[version],
        # so their screen size is independent of the camera scale.
        score = (ROOT / 'sprites/scoretext.js').read_text()
        for ratio in ('hudStageGapRatio', 'hudStageDotRatio', 'hudStageDiamondRatio', 'hudStageFontRatio'):
            self.assertRegex(score, r'height \* STYLE\.ui\.%s / scale\[version\]' % ratio)
        draw = (ROOT / 'render/draw.js').read_text()
        self.assertIn('ctx.scale(scale[version], scale[version])', draw)
        self.assertIn('ctx.scale(1 / scale[version], 1 / scale[version])', draw)


class CameraScaleRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from browser_test_support import start_browser_test
        cls._cleanups = []
        cls.url, cls.browser = start_browser_test(ROOT, cls._cleanups.append)

    @classmethod
    def tearDownClass(cls):
        while cls._cleanups:
            cls._cleanups.pop()()

    def test_live_runtime_scale_and_view(self):
        from browser_test_support import wait_for_boot_run
        page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        self.addCleanup(page.close)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        live = page.evaluate('''() => ({version, scale:{...scale}, width, height,
            view:[width/scale[version], height/scale[version]],
            hudFontScreenPx: height*STYLE.ui.hudStageFontRatio/scale[version]*scale[version]})''')
        self.assertEqual(live['version'], 'grapple_over')
        self.assertEqual(live['scale'], dict(classic=1, bad=1 / 2.2, grapple_over=GRAPPLE_OVER_SCALE))
        self.assertAlmostEqual(live['view'][0], live['width'] / GRAPPLE_OVER_SCALE)
        self.assertAlmostEqual(live['view'][1], live['height'] / GRAPPLE_OVER_SCALE)
        self.assertAlmostEqual(live['view'][0] / (live['width'] / PREVIOUS_SCALE), 1.5)
        self.assertAlmostEqual(live['hudFontScreenPx'], live['height'] * page.evaluate('STYLE.ui.hudStageFontRatio'))
        # Camera tracking keeps the ninja inside the larger view.
        inside = page.evaluate('''() => {screen.trackGrappleOver(true); draw();
            const x=(ninja.x+screen.x)*scale[version], y=(ninja.y+screen.y)*scale[version];
            return {x, y, ok: x>=0 && x<=width && y>=0 && y<=height}}''')
        self.assertTrue(inside['ok'], inside)
        print('PASS runtime scale=%s view=%s' % (live['scale'], live['view']))
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
