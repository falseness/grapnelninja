"""Momentum audit 5/14: edge-tile pixels hidden by later polygons (TASK-092).

The crystal rim (LightmapRenderer.addCrystalRim) lights the edge tiles
BackgroundRenderer.paintCrystalTile/paintNearTile build with edgesOnly. An
edge-tile pixel must only hold an edge the real tile shows. Per layer (far,
near) the probe paints, with the layer's seed and the game's tile code:
- the edge tile (edgesOnly, alpha);
- a marker tile: the real tile (edgesOnly off) with every stroke opaque white
  and every fill black at its own alpha, so its red channel is how much of
  the edges the real tile leaves visible.
hidden = edge pixels (alpha > 0) whose marker red is 0 (inside a later opaque
polygon or rock row), split into hidden (alpha > ROUNDING_ALPHA) and
roundingResidue (alpha <= ROUNDING_ALPHA: the 1/255 left where the edge tile's
destination-out and the marker's source-over round the same coverage to
different 8-bit values; invisible, the rim adds it at rimStrength); excess = edge pixels whose alpha exceeds the marker red
by more than EXCESS_TOLERANCE (an edge brighter in the edge tile than it shows,
e.g. under a translucent back shard).

Usage: python3 momentum_edge_occlusion_probe.py REV OUT.json
(REV 'worktree' or a git revision). Viewports 1280x720 and 844x390@3.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
import render_snapshot

VIEWPORTS = [(1280, 720, 1), (844, 390, 3)]
EXCESS_TOLERANCE = 8
ROUNDING_ALPHA = 1

PROBE = r'''([tolerance, rounding]) => {
    const bg = visualEffects.background
    const W = LOGICAL_VIEWPORT.width, H = LOGICAL_VIEWPORT.height
    const alphaOf = c => c[0] == '#' ? 1 : Number(c.slice(c.lastIndexOf(',') + 1, c.lastIndexOf(')')))
    // marker: fills black at their own alpha, strokes opaque white (STYLE is
    // frozen, so the context's style setters translate the colours)
    const proto = CanvasRenderingContext2D.prototype
    const setFill = Object.getOwnPropertyDescriptor(proto, 'fillStyle').set
    const setStroke = Object.getOwnPropertyDescriptor(proto, 'strokeStyle').set
    const tile = (config, paint, edgesOnly, marker) => {
        const pixelScale = Math.max(0.25, Math.min(config.maxPixelScale, bg.canvas.width / W || 1))
        const c = document.createElement('canvas')
        c.width = Math.max(1, Math.round(W * pixelScale))
        c.height = Math.max(1, Math.round(H * pixelScale))
        const ctx = c.getContext('2d')
        if (marker) {
            Object.defineProperty(ctx, 'fillStyle', {set: v => setFill.call(ctx, 'rgba(0, 0, 0, ' + alphaOf(v) + ')')})
            Object.defineProperty(ctx, 'strokeStyle', {set: v => setStroke.call(ctx, '#ffffff')})
        }
        ctx.setTransform(c.width / W, 0, 0, c.height / H, 0, 0)
        paint.call(bg, ctx, W, H, config, bg.getTileTools(ctx, W, config.seed), edgesOnly)
        return ctx.getImageData(0, 0, c.width, c.height)
    }
    const out = {logical: [W, H], canvas: [bg.canvas.width, bg.canvas.height], layers: []}
    for (const [name, config, paint] of [['far', STYLE.caveLayers.crystals, bg.paintCrystalTile],
                                         ['near', STYLE.caveLayers.nearRocks, bg.paintNearTile]]) {
        const edge = tile(config, paint, true)
        const marker = tile(config, paint, false, true)
        let edgePixels = 0, hidden = 0, residue = 0, excess = 0, hiddenAlphaSum = 0
        for (let i = 3; i < edge.data.length; i += 4) {
            const a = edge.data[i], r = marker.data[i - 3]
            if (!a) continue
            ++edgePixels
            if (r == 0 && a <= rounding) ++residue
            else if (r == 0) { ++hidden; hiddenAlphaSum += a }
            if (a > r + tolerance) ++excess
        }
        out.layers.push({layer: name, tile: [edge.width, edge.height], edgePixels, hidden,
                         hiddenMeanAlpha: hidden ? Math.round(hiddenAlphaSum / hidden * 10) / 10 : 0,
                         roundingResidue: residue, excess})
    }
    return out
}'''


def open_page(tree, w, h, dpr):
    touch = dpr > 1
    context = tree.browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=dpr,
                                       is_mobile=touch, has_touch=touch)
    context.add_init_script(fx.SEED_SCRIPT % fx.SEED)
    context.add_init_script(render_snapshot.CLOCK_SCRIPT)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(tree.url + 'index.html', wait_until='load')
    render_snapshot.boot_frozen(page)
    page.evaluate(render_snapshot.SETUP_SCRIPT, [[], touch])
    page.evaluate(fx.SEED_COURSE, fx.SCRIPT)
    page.evaluate("() => startGame('momentum')")
    page.errors = errors
    return context, page


def main(rev, out):
    tree = fx.harness(rev)
    runs = []
    try:
        for w, h, dpr in VIEWPORTS:
            context, page = open_page(tree, w, h, dpr)
            try:
                row = page.evaluate(PROBE, [EXCESS_TOLERANCE, ROUNDING_ALPHA])
                if page.errors:
                    raise RuntimeError(f'page errors: {page.errors}')
            finally:
                context.close()
            row['viewport'] = f'{w}x{h}@{dpr}'
            print(rev, row)
            runs.append(row)
    finally:
        fx.close()
    result = {'rev': tree.rev, 'excessTolerance': EXCESS_TOLERANCE, 'roundingAlpha': ROUNDING_ALPHA,
              'hiddenTotal': sum(l['hidden'] for r in runs for l in r['layers']),
              'excessTotal': sum(l['excess'] for r in runs for l in r['layers']), 'runs': runs}
    Path(out).write_text(json.dumps(result, separators=(',', ':')))
    return result


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
