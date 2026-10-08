"""Measure camera parallax and three seconds of stationary-camera motion in-page.

PARALLAX_REV selects a revision; the CLI --rev measures without asserting so
parent regressions can be recorded with exactly the same probe.
"""
import argparse
from contextlib import ExitStack
import json
import math
import os
import unittest

from browser_test_support import start_browser_test
from perf_mobile import export_rev
import render_snapshot

PROBE = '''mode => {
    startGame(mode)
    const bg = visualEffects.background
    const width = LOGICAL_VIEWPORT.width, height = LOGICAL_VIEWPORT.height
    const cssScale = getCanvasCssRect().width / width
    const geometry = STYLE.backgroundGeometry
    const layers = {
        crystals: () => bg.getLayerShift(width, height, geometry.crystals),
        nearRocks: () => bg.getLayerShift(width, height, geometry.nearRocks),
        geometry: () => {
            const a = bg.getParallaxShift(width, height, geometry.badVersion)
            const b = bg.getCameraParallaxShift(geometry.badVersion)
            return {x: a.x + b.x, y: a.y + b.y}
        }
    }
    const results = {}
    for (const [name, shift] of Object.entries(layers)) {
        __snap.now = 0
        screen.x = screen.y = 0
        const origin = shift()
        const ratios = []
        for (const delta of [-400, 400]) {
            screen.x = delta
            ratios.push((shift().x - origin.x) / (delta * scale[version]))
        }
        screen.x = 123
        const samples = []
        for (let ms = 0; ms <= 3000; ms += 50) {
            __snap.now = ms
            samples.push(shift())
        }
        let drift = 0
        for (const a of samples) for (const b of samples)
            drift = Math.max(drift, Math.hypot(a.x-b.x, a.y-b.y) * cssScale)
        results[name] = {k: ratios, max_still_drift_css_px: drift}
    }
    return results
}'''


def measure(rev):
    with ExitStack() as stack:
        root, revision = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        context = browser.new_context(viewport={'width': 844, 'height': 390},
                                      device_scale_factor=3, is_mobile=True, has_touch=True)
        stack.callback(context.close)
        context.add_init_script(render_snapshot.CLOCK_SCRIPT)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url + 'index.html', wait_until='load')
        render_snapshot.boot_frozen(page)
        return {'rev': revision, 'modes': {mode: page.evaluate(PROBE, mode)
                for mode in ('bad', 'classic')}, 'page_errors': errors}


def report(result):
    print('rev=' + result['rev'])
    for mode, layers in result['modes'].items():
        for name, layer in layers.items():
            print(f'{mode} {name} k={layer["k"]} '
                  f'max_still_drift_css_px={layer["max_still_drift_css_px"]:.6f}')
    print('page_errors=' + json.dumps(result['page_errors']))


class BackgroundParallaxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = measure(os.environ.get('PARALLAX_REV', 'worktree'))
        report(cls.result)

    def test_same_direction_and_slower_than_world(self):
        for mode, layers in self.result['modes'].items():
            for name, layer in layers.items():
                for k in layer['k']:
                    with self.subTest(mode=mode, layer=name, k=k):
                        self.assertGreater(k, 0)
                        self.assertLess(k, 1)
            self.assertGreater(layers['nearRocks']['k'][0], layers['crystals']['k'][0])
            self.assertAlmostEqual(layers['crystals']['k'][0], 0.08)
            self.assertAlmostEqual(layers['nearRocks']['k'][0], 0.25)

    def test_still_camera_drift(self):
        for mode, layers in self.result['modes'].items():
            for name, layer in layers.items():
                with self.subTest(mode=mode, layer=name):
                    self.assertTrue(math.isfinite(layer['max_still_drift_css_px']))
                    self.assertLessEqual(layer['max_still_drift_css_px'], 10)

    def test_no_page_errors(self):
        self.assertEqual(self.result['page_errors'], [])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rev', default='worktree')
    args = parser.parse_args()
    report(measure(args.rev))
