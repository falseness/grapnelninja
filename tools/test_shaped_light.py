"""Frozen-clock geometry, isolation and cache probes; --rev also captures the parent."""
import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import unittest

import numpy as np
from PIL import Image
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
from render_snapshot import CLOCK_SCRIPT, boot_frozen, png_bytes

SCENE = '''mode => {
    startGame(mode)
    screen.x = screen.y = 0
    const u = scale[version]
    const rect = new Rect({x: 220/u, y: 160/u, width: 300/u, height: 70/u,
        stroke: STYLE.colors.cube.greenStroke})
    const tri = new Triangle({x: 740/u, y: 180/u, radius: 65/u,
        yMin: 0, yMax: 1000, stroke: STYLE.colors.hazard.harmlessStroke})
    ninja.x = 550/u; ninja.y = 210/u
    const lights = visualEffects.lightmap
    window.scene = {rect, tri, lights, u}
    window.paint = enabled => {
        ctx.save()
        ctx.setTransform(1,0,0,1,0,0)
        ctx.clearRect(0,0,canvas.width,canvas.height)
        ctx.scale(canvas.width / LOGICAL_VIEWPORT.width, canvas.height / LOGICAL_VIEWPORT.height)
        visualEffects.background.draw()
        ctx.scale(u,u)
        lights.enabled = enabled
        lights.clear(); lights.draw({floors: [{elements: [rect,tri]}]}); lights.composite()
        rect.draw(); tri.draw(); ninja.draw()
        ctx.restore()
        return canvas.toDataURL('image/png')
    }
    paint(true)
    window.gradientCount = 0
    for (const name of ['createLinearGradient','createRadialGradient']) {
        const original = CanvasRenderingContext2D.prototype[name]
        CanvasRenderingContext2D.prototype[name] = function(...args) {
            gradientCount++; return original.apply(this,args)
        }
    }
    return {radius: ninja.radius*u, width: canvas.width, height: canvas.height}
}'''


def probe(out=None, rev='worktree'):
    out = Path(out) if out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
    report = {'limits': {'side_corner_relative_difference': 0.15, 'isolation_delta': 2,
                         'gradients_per_frame': 0}, 'captures': {}}
    with ExitStack() as stack:
        root, report['rev'] = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for mode in ['bad', 'classic']:
            context = browser.new_context(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1)
            try:
                context.add_init_script(SEED_SCRIPT % 1)
                context.add_init_script(CLOCK_SCRIPT)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url)
                boot_frozen(page)
                meta = page.evaluate(SCENE, mode)
                images = {}
                for enabled in [True, False]:
                    data = png_bytes(page.evaluate('enabled => paint(enabled)', enabled))
                    images[enabled] = np.asarray(Image.open(io.BytesIO(data)).convert('RGB'), dtype=np.int16)
                    if out:
                        (out.parent / f'scene-{mode}-{enabled}.png').write_bytes(data)
                # Sample the actual isolated lightmap in output coordinates so
                # background texture and tone blending cannot bias falloff.
                values = page.evaluate('''() => {
                    const {lights,rect,u} = scene
                    lights.enabled = true; lights.clear()
                    lights.lightCtx.save()
                    lights.drawElementLight(rect)
                    lights.lightCtx.restore()
                    const d = 14, k = lights.scale
                    const sample = (x,y) => lights.lightCtx.getImageData(
                        Math.round(x*k),Math.round(y*k),1,1).data[3]
                    const side = sample(370,160-d)
                    const corner = sample(220-d/Math.sqrt(2),160-d/Math.sqrt(2))
                    const spread = STYLE.lights.shapeSpread || 95
                    const radius = (STYLE.lights.cubeRadius + Math.min(
                        Math.hypot(150,35)*1080/height,STYLE.lights.maxElementRadius))*height/1080
                    const radial = distance => {
                        const t = distance/radius, stops = STYLE.lights.falloff
                        for (let i=1;i<stops.length;i++) if(t<=stops[i][0]) {
                            const [a,av]=stops[i-1], [b,bv]=stops[i]
                            return av+(bv-av)*(t-a)/(b-a)
                        }
                        return 0
                    }
                    return {side,corner,ratio:corner/side,
                        relative_difference:Math.abs(side-corner)/Math.max(side,corner),
                        radial_side:radial(35+d),
                        radial_corner:radial(Math.hypot(150+d/Math.sqrt(2),35+d/Math.sqrt(2)))}
                }''')
                delta = abs(images[True] - images[False]).max(axis=2)
                yy, xx = np.indices(delta.shape)
                player = (xx-550)**2 + (yy-210)**2 <= (meta['radius']*1.5)**2
                values.update(inside_obstacle_delta=int(delta[165:225,225:515].max()),
                              ninja_area_delta=int(delta[player].max()),
                              background_changed_pixels=int((delta > 2).sum()))
                values['gradients_per_frame'] = page.evaluate('''() => {
                    const counts=[]
                    for(let i=0;i<5;i++) { gradientCount=0; paint(true); counts.push(gradientCount) }
                    return counts
                }''')
                values['page_errors'] = errors
                # Inspect the complete mask, not only the unmasked light sprite.
                # The old four-lightmap-pixel stroke cleared the exterior too.
                values['edge_masks'] = page.evaluate('''() => {
                    const {lights,rect,u} = scene, results=[]
                    const savedScale=lights.scale
                    try {
                        for(const k of [STYLE.lights.resolutionScale, STYLE.lights.touchResolutionScale]) {
                            lights.scale=k; lights.resize(); lights.enabled=true
                            lights.clear(); lights.draw({floors:[{elements:[rect]}]})
                            const alpha=(x,y) => lights.lightCtx.getImageData(
                                Math.floor(x*k),Math.floor(y*k),1,1).data[3]
                            results.push({scale:k, exterior:alpha(370,155),
                                farther:alpha(370,140), interior:alpha(370,175)})
                        }
                    } finally { lights.scale=savedScale; lights.resize() }
                    return results
                }''')
                report['captures'][mode] = values
                print(mode, json.dumps(values), flush=True)
            finally:
                context.close()
    if out:
        out.write_text(json.dumps(report, indent=2)+'\n')
    return report


def assert_report(report):
    for mode, r in report['captures'].items():
        assert r['side'] > 5 and r['corner'] > 5, (mode, r)
        assert r['relative_difference'] <= .15, (mode, r)
        assert abs(r['radial_side']-r['radial_corner']) / r['radial_side'] > .15, r
        assert r['inside_obstacle_delta'] <= 2, (mode, r)
        assert r['ninja_area_delta'] <= 2, (mode, r)
        assert r['background_changed_pixels'] > 100, (mode, r)
        assert r['gradients_per_frame'] == [0]*5, (mode, r)
        assert not r['page_errors'], r
        for edge in r['edge_masks']:
            assert edge['exterior'] > 5, (mode, edge)
            assert edge['exterior'] >= edge['farther'], (mode, edge)
            assert edge['interior'] == 0, (mode, edge)
        print(f'PASS {mode}: shape difference <= 15%; isolation <= 2; gradients/frame = 0', flush=True)


class ShapedLightTests(unittest.TestCase):
    def test_shape_isolation_and_cache(self):
        assert_report(probe(os.environ.get('SHAPED_LIGHT_OUT')))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--rev', default='worktree')
    args = p.parse_args()
    result = probe(args.out, args.rev)
    if args.rev == 'worktree':
        assert_report(result)
