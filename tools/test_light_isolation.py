"""Frozen-clock lightmap on/off pixel probes of actual ring and obstacle edges.

Run directly with --out to save the sampled RGB values and comparison PNGs.
The STYLE feature is switched before load; each side replays identical input.
"""
import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import unittest

import numpy as np
from PIL import Image

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT
from render_snapshot import (ADVANCE_SCRIPT, CLOCK_SCRIPT, SETUP_SCRIPT,
                             boot_frozen, input_script, png_bytes)
from visual_gallery import VIEWPORTS

ROOT = Path(__file__).resolve().parents[1]
TICKS = [60, 300]
# Observe the transform at the actual draw call, including shake and DPR.
PROBES = '''() => {
    window.lightSamples = []
    const background = drawBackgroundLayer
    drawBackgroundLayer = function() { lightSamples = []; background() }
    const point = (kind, x, y) => {
        const p = ctx.getTransform().transformPoint({x, y})
        const px = Math.floor(p.x), py = Math.floor(p.y)
        if (px > 2 && py > 2 && px < canvas.width - 3 && py < canvas.height - 3)
            lightSamples.push({kind, x: px, y: py})
    }
    const player = Ninja.prototype.draw
    Ninja.prototype.draw = function() {
        const r = this.getRingOuterRadius() * (1 - STYLE.playerVisuals.ringWidthRatio / 2)
        for (let i = 0; i < 8; i++) {
            const a = i * Math.PI / 4
            point('ring', this.x + screen.x + r * Math.cos(a),
                this.y + screen.y + r * Math.sin(a))
        }
        player.call(this)
    }
    for (const Type of [Rect, Trampoline, Triangle]) {
        const original = Type.prototype.draw
        Type.prototype.draw = function() {
            const vertices = this.getPoints()
            for (let i = 0; i < vertices.length; i++) {
                const a = vertices[(i + vertices.length - 1) % vertices.length]
                const b = vertices[i]
                // Curved edges are sampled on their quadratic path.
                for (let j = 1; j < 40; j++) {
                    const t = j / 40, u = 1 - t, c = b.curvature
                    const x = c ? u*u*a.x + 2*u*t*c.x + t*t*b.x : a.x*u + b.x*t
                    const y = c ? u*u*a.y + 2*u*t*c.y + t*t*b.y : a.y*u + b.y*t
                    point('obstacle', x + screen.x, y + screen.y)
                }
            }
            original.call(this)
        }
    }
}'''


def probe(out=None):
    out = Path(out) if out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
    report = {'rev': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                             text=True).strip(), 'captures': {}}
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        for vp in VIEWPORTS:
            for mode in ['bad', 'classic']:
                sides = {}
                for enabled in [True, False]:
                    context = browser.new_context(
                        viewport={'width': vp['width'], 'height': vp['height']},
                        device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
                    try:
                        if not enabled:
                            def without_lightmap(route):
                                response = route.fetch()
                                route.fulfill(response=response, body=response.text().replace(
                                    'lightmap: true', 'lightmap: false', 1))
                            context.route('**/style.js', without_lightmap)
                        context.add_init_script(SEED_SCRIPT % 1)
                        context.add_init_script(CLOCK_SCRIPT)
                        page = context.new_page()
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(url)
                        boot_frozen(page)
                        assert page.evaluate('STYLE.features.lightmap') == enabled
                        page.evaluate(SETUP_SCRIPT, [input_script(1, 300, vp['width'], vp['height']), vp['touch']])
                        page.evaluate(PROBES)
                        page.evaluate('mode => startGame(mode)', mode)
                        for tick in TICKS:
                            page.evaluate(ADVANCE_SCRIPT, tick)
                            name = f'{vp["name"]}-{mode}-{tick}'
                            data = png_bytes(page.evaluate('() => __snap.capture()'))
                            pixels = np.asarray(Image.open(io.BytesIO(data)).convert('RGB'), dtype=np.int16)
                            sides[enabled, tick] = (pixels, page.evaluate('lightSamples'))
                            if out:
                                (out.parent / f'{name}-light-{enabled}.png').write_bytes(data)
                        assert not errors, errors
                    finally:
                        context.close()
                for tick in TICKS:
                    name = f'{vp["name"]}-{mode}-{tick}'
                    on, points = sides[True, tick]
                    off, off_points = sides[False, tick]
                    assert points == off_points, name
                    samples = []
                    for p in points:
                        a, b = on[p['y'], p['x']], off[p['y'], p['x']]
                        samples.append(dict(p, on=a.tolist(), off=b.tolist(), max_delta=int(abs(a - b).max())))
                    report['captures'][name] = {
                        'samples': samples, 'max_delta': max(s['max_delta'] for s in samples),
                        'background_changed_pixels': int(np.any(on != off, axis=2).sum())}
                    print(f'{name}: samples={len(samples)} max_delta={report["captures"][name]["max_delta"]}', flush=True)
    if out:
        out.write_text(json.dumps(report, indent=2) + '\n')
    return report


def assert_report(report):
    for name, capture in report['captures'].items():
        assert {s['kind'] for s in capture['samples']} == {'ring', 'obstacle'}, name
        assert capture['background_changed_pixels'] > 100, f'{name}: lightmap must visibly affect background'
        assert capture['max_delta'] <= 2, (name, capture['max_delta'])
        for s in capture['samples']:
            assert max(s['on']) > 60, (name, 'sample must land on a visible edge', s)


class LightIsolationTests(unittest.TestCase):
    def test_obstacle_trails_fade_without_filled_envelopes(self):
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            page = browser.new_page()
            page.add_init_script(CLOCK_SCRIPT)
            page.goto(url)
            boot_frozen(page)
            result = page.evaluate("""() => {
                startGame('bad')
                const target = document.createElement('canvas')
                target.width = 220; target.height = 260
                ctx = target.getContext('2d')
                screen.x = screen.y = 0
                const alpha = (x, y) => ctx.getImageData(x, y, 1, 1).data[3]
                const results = []
                for (const mode of ['bad', 'classic']) {
                    version = mode
                    ctx.clearRect(0, 0, 220, 260)
                    const cube = new CubeTrackLine(20, 20, '#00ffff', 20)
                    cube.pos = Array.from({length: 13}, (_, i) => ({x: 30 + i*10, y: 40}))
                    cube.draw()
                    const triangle = new MultipointTrackLine(80, '#ffffff', 20)
                    triangle.pos = Array.from({length: 5}, (_, i) => [
                        {x: 60, y: 100 + i*30}, {x: 140, y: 100 + i*30},
                        {x: 100, y: 120 + i*30}])
                    triangle.draw()
                    results.push({mode, cubeOld: alpha(35, 40), cubeNew: alpha(145, 40),
                        triangleOld: alpha(100, 100), triangleNew: alpha(100, 190),
                        envelopeInterior: alpha(100, 105), oldCubeCorner: alpha(30, 49)})
                }
                return results
            }""")
            for r in result:
                self.assertLess(r['cubeOld'], r['cubeNew'], r)
                self.assertGreater(r['cubeNew'], 0, r)
                self.assertLessEqual(r['cubeNew'], 57, r)  # No overlapping alpha accumulation
                self.assertLess(r['triangleOld'], r['triangleNew'], r)
                self.assertGreater(r['triangleNew'], 0, r)
                self.assertEqual(r['envelopeInterior'], 0, r)
                self.assertEqual(r['oldCubeCorner'], 0, r)
                print('PASS obstacle trail pixels:', r, flush=True)

    def test_lightmap_leaves_ring_and_obstacle_edges_unchanged(self):
        assert_report(probe(os.environ.get("LIGHT_ISOLATION_OUT")))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert_report(probe(args.out))
