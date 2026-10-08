"""Frozen-clock lightmap and bloom/pulse probes of ring and obstacle edges.

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


def probe(out=None, effect="lightmap"):
    out = Path(out) if out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
    report = {'rev': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                             text=True).strip(), 'effect': effect, 'captures': {}}
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
                        # Exercise both paths even when production bloom is off.
                        def with_effect(route):
                            response = route.fetch()
                            route.fulfill(response=response, body=response.text().replace(
                                f'{effect}: false' if enabled else f'{effect}: true',
                                f'{effect}: true' if enabled else f'{effect}: false', 1).replace(
                                'pulseAmount: 0.08', 'pulseAmount: 0' if effect == 'bloom' and not enabled else 'pulseAmount: 0.08'))
                        context.route('**/style.js', with_effect)
                        context.add_init_script(SEED_SCRIPT % 1)
                        context.add_init_script(CLOCK_SCRIPT)
                        page = context.new_page()
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(url)
                        boot_frozen(page)
                        assert page.evaluate(f'STYLE.features.{effect}') == enabled
                        if effect == 'bloom':
                            assert page.evaluate('STYLE.ambient.pulseAmount') == (0.08 if enabled else 0)
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
                                (out.parent / f'{name}-{effect}-{enabled}.png').write_bytes(data)
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
                        if effect == 'bloom' and p['kind'] != 'ring':
                            continue
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
        assert {s['kind'] for s in capture['samples']} == (
            {'ring'} if report['effect'] == 'bloom' else {'ring', 'obstacle'}), name
        assert capture['background_changed_pixels'] > 100, f'{name}: {report["effect"]} must visibly affect background'
        assert capture['max_delta'] <= 2, (name, capture['max_delta'])
        # Some projected obstacle edges are occluded by other geometry. Require
        # visible coverage for each kind without calling an occluded point an edge.
        for kind in {s['kind'] for s in capture['samples']}:
            visible = sum(s['kind'] == kind and max(s['on']) > 60 for s in capture['samples'])
            assert visible >= 8, (name, kind, 'insufficient visible edge samples', visible)



class LightIsolationTests(unittest.TestCase):
    def test_player_after_effects_with_visible_ring_and_sparks(self):
        lines = ['rev=' + subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'Ring strokes are cached offscreen; force one rebuild per probe frame and also record the main-canvas sprite composite.']
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            for vp in VIEWPORTS:
                for mode in ['bad', 'classic']:
                    context = browser.new_context(
                        viewport={'width': vp['width'], 'height': vp['height']},
                        device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
                    try:
                        # Grade is optional and currently disabled; exercise its enabled path.
                        def with_grade(route):
                            response = route.fetch()
                            route.fulfill(response=response, body=response.text().replace(
                                'colorGrade: false', 'colorGrade: true'))
                        context.route('**/style.js', with_grade)
                        context.add_init_script(SEED_SCRIPT % 1)
                        context.add_init_script(CLOCK_SCRIPT)
                        page = context.new_page()
                        page.goto(url)
                        boot_frozen(page)
                        page.evaluate(SETUP_SCRIPT, [input_script(1, 100, vp['width'], vp['height']), vp['touch']])
                        page.evaluate('mode => startGame(mode)', mode)
                        page.evaluate('''() => {
                            window.orderProbe = {ops: [], layer: null, points: []}
                            for (const name of ['drawParticlesAndTrailsLayer', 'drawBloomLayer',
                                                'drawColorGradeLayer', 'drawPlayerLayer']) {
                                const original = window[name]
                                window[name] = function(...args) {
                                    orderProbe.layer = name
                                    if (name === 'drawPlayerLayer') {
                                        Ninja.glowSprite = null
                                        const r = ninja.getRingOuterRadius() * (1 - STYLE.playerVisuals.ringWidthRatio / 2)
                                        orderProbe.points = Array.from({length: 16}, (_, i) => {
                                            const a = i * Math.PI / 8
                                            const p = ctx.getTransform().transformPoint({
                                                x: ninja.x + screen.x + r * Math.cos(a),
                                                y: ninja.y + screen.y + r * Math.sin(a)})
                                            return {x: Math.floor(p.x), y: Math.floor(p.y)}
                                        })
                                    }
                                    try { return original(...args) }
                                    finally { orderProbe.layer = null }
                                }
                            }
                            const proto = CanvasRenderingContext2D.prototype
                            for (const op of ['stroke', 'fill', 'fillRect', 'drawImage']) {
                                const original = proto[op]
                                proto[op] = function(...args) {
                                    if (orderProbe.layer) orderProbe.ops.push({
                                        layer: orderProbe.layer, op, main: this === ctx,
                                        color: this.strokeStyle,
                                        ringSprite: op === 'drawImage' && args[0] === Ninja.glowSprite?.canvas})
                                    return original.apply(this, args)
                                }
                            }
                            const background = drawBackgroundLayer
                            drawBackgroundLayer = function() { orderProbe.ops = []; background() }
                        }''')
                        for tick in range(60, 65):
                            page.evaluate(ADVANCE_SCRIPT, tick)
                            result = page.evaluate('''() => ({...orderProbe,
                                ringColor: ninja.stroke,
                                sparks: visualEffects.particles.particles.filter(p => p.spark).length,
                                pixels: orderProbe.points.map(p => Array.from(ctx.getImageData(p.x, p.y, 1, 1).data))})''')
                            ops = result['ops']
                            last = {layer: max((i for i, op in enumerate(ops) if op['layer'] == layer and op['main']), default=-1)
                                    for layer in ['drawParticlesAndTrailsLayer', 'drawBloomLayer', 'drawColorGradeLayer']}
                            ring = next(i for i, op in enumerate(ops) if op['layer'] == 'drawPlayerLayer'
                                        and op['op'] == 'stroke' and op['color'] == result['ringColor'])
                            composite = next(i for i, op in enumerate(ops) if op['main'] and op['ringSprite'])
                            visible = sum(g > 100 and b > 100 and g > r + 25 and b > r + 25
                                          for r, g, b, a in result['pixels'])
                            self.assertLess(max(last.values()), ring, result)
                            self.assertLess(ring, composite, result)
                            self.assertGreater(result['sparks'], 0, result)
                            self.assertGreaterEqual(visible, 8, result)
                            line = (f'PASS {vp["name"]} {mode} tick={tick}: last={last} < '
                                    f'ninja_ring_stroke={ring} < sprite_composite={composite}; '
                                    f'ring_visible={visible}/16 sparks={result["sparks"]}')
                            lines.append(line)
                            lines.append('ops=' + json.dumps(ops))
                            print(line, flush=True)
                    finally:
                        context.close()
        if os.environ.get('PLAYER_ORDER_OUT'):
            Path(os.environ['PLAYER_ORDER_OUT']).write_text('\n'.join(lines) + '\n')

    def test_bloom_and_pulse_leave_ring_unchanged(self):
        assert_report(probe(os.environ.get('BLOOM_ISOLATION_OUT'), effect='bloom'))

    def test_lightmap_leaves_ring_and_obstacle_edges_unchanged(self):
        assert_report(probe(os.environ.get("LIGHT_ISOLATION_OUT")))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--effect', choices=['lightmap', 'bloom'], default='lightmap')
    args = parser.parse_args()
    assert_report(probe(args.out, args.effect))
