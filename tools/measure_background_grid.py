"""TASK-713: locate the static fine grid over the Grapple Over background.

Measurement only. Headless Chromium at 1280x720 (DPR 2 and DPR 1). The game loop
is frozen and draw() is called directly with the ninja (and camera) snapped to fixed
poses on the shipped level; the canvas backing store is read back with toDataURL
(what the compositor shows 1:1 at the device resolution).

Grid score of a region (luma, device px): hp = image - 5x5 box blur; rms = RMS(hp);
corrY2 / corrX4 = autocorrelation of hp at (dx 0, dy 2) / (dx 4, dy 0) over the
zero-lag value. Regions are 128x128 device-px blocks of the default frame picked by a
flatness test (no edges: max |hp| <= FLAT_MAX_HP and the 5x5-blurred luma spans at most
FLAT_MAX_SPAN grey levels) and reused for every configuration of that DPR and pose.

Configurations: the default frame; each background layer stubbed out in turn; the
adaptive-quality states (?adaptive=1, forced: full, FAST_SCALE 0.5 backdrop, each
RESOLUTION_STEPS entry). Headless numbers are relative only.

Example: python3 tools/measure_background_grid.py --out artifacts/TASK-713
"""
import argparse
import base64
import io
import json
import sys
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
VIEWPORT = {'width': 1280, 'height': 720}
DPRS = (2, 1)
BLOCK = 128
REGIONS = 3
FLAT_MAX_HP = 6.0
FLAT_MAX_SPAN = 12.0
CROPS = ('default', 'float16', 'adaptive-fast0.5', 'float16-fast0.5')
GRID = 0.3
CLEAN = 0.15

# name -> JS run before the draw (undone by reload of the stubs: each config draws
# from the saved originals, see HELPER.reset)
LAYERS = {
    'crystals': "bg.drawCrystalLayer = () => {}",
    'parallax': "bg.parallaxEnabled = false",
    'nearRocks': "bg.drawNearLayer = () => {}",
    'paletteWash': "window.drawGrappleOverPalette = () => {}",
    'landmarks': "window.drawGrappleOverLandmarks = () => {}",
    'bgVignette': "bg.drawVignette = () => {}",
    'lightmap': "visualEffects.lightmap.enabled = false",
    'ambientMotes': "visualEffects.particles.drawAmbientMotes = () => {}",
    'moteGlow': "visualEffects.ambientGlow.shouldDraw = () => false",
    'playerGlow': "visualEffects.playerGlow.shouldDraw = () => false",
    'world': "window.drawWorldLayer = () => {}",
    'wholeBackground': "bg.paint = function() { this.clearAll() }",
    # every background layer that fills a gradient, at once (parallax tiles and
    # landmarks stay)
    'gradientLayers': "bg.drawCrystalLayer = bg.drawNearLayer = bg.drawVignette = () => {};"
                      " window.drawGrappleOverPalette = () => {}",
    # every layer kept, but each CanvasGradient painted with its first stop only
    # (a flat gradient: nothing left to dither); all gradient-built caches rebuilt
    'gradientsFlat': "T713.flatGradients('flat')",
    # every layer kept, but each gradient replaced by its first stop as a solid
    # colour (fillStyle takes the stand-in's toString()): no gradient shader at all
    'gradientsSolid': "T713.flatGradients('solid')",
}
# backdrop scale, canvas resolution
ADAPTIVE = {'adaptive-full': (1, 1), 'adaptive-fast0.5': (0.5, 1),
            'adaptive-res0.75': (0.5, 0.75), 'adaptive-res0.5': (0.5, 0.5)}
# The dither-free twin: every 2D context (the frame canvas, the backdrop, every tile
# and sprite cache) gets a float16 backing store. Skia dithers only when it writes
# 8-bit colour, so the same gradients are drawn without the ordered dither;
# toDataURL rounds to 8 bits without dithering (a smooth band, no pattern).
FLOAT16_INIT = '''(() => {
    const getContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function(type, options) {
        return type === '2d' ? getContext.call(this, type, {...(options || {}), colorType: 'float16'})
                             : getContext.call(this, type, options)
    }
})()'''
FLOAT16 = {'float16': (1, 1), 'float16-fast0.5': (0.5, 1), 'float16-res0.75': (0.5, 0.75),
           'float16-res0.5': (0.5, 0.5)}
QUALITY_OF = {**ADAPTIVE, **FLOAT16}
# page name -> query, init script, configurations
PAGES = {'default': ('', None, ['default'] + list(LAYERS)),
         'adaptive': ('?adaptive=1', None, list(ADAPTIVE)),
         'float16': ('?adaptive=1', FLOAT16_INIT, list(FLOAT16))}

HELPER = r'''
window.T713 = (() => {
  const bg = visualEffects.background
  const saved = {
    bg: {drawCrystalLayer: bg.drawCrystalLayer, drawNearLayer: bg.drawNearLayer, drawVignette: bg.drawVignette,
         paint: bg.paint, parallaxEnabled: bg.parallaxEnabled},
    win: {drawGrappleOverPalette, drawGrappleOverLandmarks, drawWorldLayer},
    motes: visualEffects.particles.drawAmbientMotes,
    glow: visualEffects.ambientGlow.shouldDraw, pglow: visualEffects.playerGlow.shouldDraw,
  }
  const r3 = v => Math.round(v * 1000) / 1000
  const addColorStop = CanvasGradient.prototype.addColorStop
  const proto = CanvasRenderingContext2D.prototype
  const linear = proto.createLinearGradient, radial = proto.createRadialGradient
  const solid = () => ({addColorStop(offset, color) { if (this.color === undefined) this.color = color },
    toString() { return this.color === undefined ? '#000000' : this.color }})
  let flat = false
  const flush = () => {
    bg.layerCache = {}; bg.gradientCache = new Map(); bg.lastGameGradients = null
    drawGrappleOverPalette.cache = null; GLOW_SPRITES.cache.clear()
    visualEffects.lightmap.gradients = new Map()
  }
  return {
    flatGradients(on) {
      if (on === flat) return
      flat = on
      CanvasGradient.prototype.addColorStop = on === 'flat' ? function(offset, color) {
        if (this.firstStop === undefined) this.firstStop = color
        return addColorStop.call(this, offset, this.firstStop)
      } : addColorStop
      proto.createLinearGradient = on === 'solid' ? solid : linear
      proto.createRadialGradient = on === 'solid' ? solid : radial
      flush()
    },
    // One full-backing linear gradient fill (two palette stops) on a fresh canvas the
    // size of the frame, plus the same rect filled solid: the gradient dither alone
    dither(color0, color1) {
      const c = document.createElement('canvas'); c.width = canvas.width; c.height = canvas.height
      const x = c.getContext('2d', {alpha: false})
      const g = x.createLinearGradient(0, 0, 0, c.height); g.addColorStop(0, color0); g.addColorStop(1, color1)
      x.fillStyle = g; x.fillRect(0, 0, c.width, c.height >> 1)
      x.fillStyle = color0; x.fillRect(0, c.height >> 1, c.width, c.height - (c.height >> 1))
      return c.toDataURL('image/png')
    },
    freeze() {
      window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
      // One clock for every frame: panel pulses, background drift and mote
      // twinkle read performance.now(), so each configuration draws the same instant
      const now = performance.now()
      performance.now = () => now
      if (typeof PERF_OVERLAY != 'undefined') PERF_OVERLAY.enabled = false
      TUTORIAL_HINT.visible = false
    },
    reset() {
      this.flatGradients(false)
      delete bg.drawCrystalLayer; delete bg.drawNearLayer; delete bg.drawVignette; delete bg.paint
      bg.parallaxEnabled = saved.bg.parallaxEnabled
      Object.assign(window, saved.win)
      delete visualEffects.particles.drawAmbientMotes
      delete visualEffects.ambientGlow.shouldDraw; delete visualEffects.playerGlow.shouldDraw
      visualEffects.lightmap.enabled = true
    },
    stub(js) { (new Function('bg', js))(bg) },
    quality(backdrop, resolution) {
      BACKDROP.adaptive = false
      BACKDROP.scale = backdrop
      if (BACKDROP.resolution !== resolution) {
        BACKDROP.resolution = resolution
        window.dispatchEvent(new Event('resize'))
      }
    },
    poses() {
      const f = floors[0], zones = f.noGrappleZones
      const center = z => { const p = z.getPoints(), xs = p.map(q => q.x), ys = p.map(q => q.y)
        return {x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2} }
      const s = f.level.spawn, fin = f.level.finish
      // the zones run bottom to top: mid level is the middle one, upper level the last
      const byY = zones.map(center).sort((a, b) => b.y - a.y)
      const mid = byY[Math.floor(byY.length / 2)], up = byY[byY.length - 1]
      return [{name: 'spawn', x: s.x, y: s.y}, {name: 'mid', ...mid}, {name: 'upper', ...up},
        // the ninja standing still on the finish landing: the camera after a settled track
        {name: 'rest', x: (fin.left + fin.right) / 2, y: (fin.top + fin.bottom) / 2, settle: true}].map(p => ({...p, x: r3(p.x), y: r3(p.y)}))
    },
    place(p) {
      ninja.x = p.x; ninja.y = p.y; ninja.speedX = ninja.speedY = 0
      grapnel.endShot(); screen.trackGrappleOver(true)
      if (p.settle) for (let i = 0; i < 120; ++i) screen.trackGrappleOver(false)
    },
    capture() { draw(); draw(); return canvas.toDataURL('image/png') },
    state() { return {canvas: [canvas.width, canvas.height], dpr: devicePixelRatio, backdropScale: BACKDROP.scale,
      resolution: BACKDROP.resolution, adaptive: BACKDROP.adaptive, cameraX: r3(screen.x), cameraY: r3(screen.y)} },
  }
})()
'''


def luma(png):
    rgb = np.asarray(Image.open(io.BytesIO(png)).convert('RGB'), dtype=np.float64)
    return rgb @ np.array([0.299, 0.587, 0.114]), rgb


def box5(a):
    p = np.pad(a, 2, mode='edge')
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = a.shape
    return (c[5:5 + h, 5:5 + w] - c[:h, 5:5 + w] - c[5:5 + h, :w] + c[:h, :w]) / 25


def highpass(y):
    return y - box5(y)


def score(hp):
    hp = hp - hp.mean()
    zero = (hp * hp).mean()
    if zero <= 1e-6:
        return {'rms': 0.0, 'corrY2': 0.0, 'corrX4': 0.0, 'bandFree': {'rms': 0.0, 'corrY2': 0.0, 'corrX4': 0.0}}
    y2 = (hp[2:, :] * hp[:-2, :]).mean() / zero
    x4 = (hp[:, 4:] * hp[:, :-4]).mean() / zero
    out = {'rms': round(float(np.sqrt(zero)), 4), 'corrY2': round(float(y2), 4), 'corrX4': round(float(x4), 4)}
    # Band-free variant (not the ticket's score, reported next to it): the row and
    # column means of hp removed first. A 1-level band step of an undithered
    # gradient is constant along x (corrX4 = 1 at any rms); a 2-D dither has
    # ~zero row/column means and keeps its correlations.
    hb = hp - hp.mean(axis=1, keepdims=True) - hp.mean(axis=0, keepdims=True)
    zb = (hb * hb).mean()
    out['bandFree'] = {'rms': round(float(np.sqrt(zb)), 4),
                       'corrY2': round(float((hb[2:, :] * hb[:-2, :]).mean() / zb), 4) if zb > 1e-6 else 0.0,
                       'corrX4': round(float((hb[:, 4:] * hb[:, :-4]).mean() / zb), 4) if zb > 1e-6 else 0.0}
    return out


def spectrum(hp):
    """Dominant periods of the high-pass (strongest autocorrelation lags 1..8 on each axis)."""
    hp = hp - hp.mean()
    zero = (hp * hp).mean() or 1
    ys = {d: round(float((hp[d:, :] * hp[:-d, :]).mean() / zero), 3) for d in range(1, 9)}
    xs = {d: round(float((hp[:, d:] * hp[:, :-d]).mean() / zero), 3) for d in range(1, 9)}
    return {'y': ys, 'x': xs}


def block_size(dpr):
    """BLOCK device px at DPR 2: the same CSS area (64 x 64 CSS px) at every DPR."""
    return BLOCK * dpr // 2


def pick_regions(ref, twin, dpr):
    """Flattest blocks with no edges, away from the HUD rows.

    A block must be flat (max |hp| <= FLAT_MAX_HP, blurred span <= FLAT_MAX_SPAN) in
    both the default frame and its dither-free twin: the twin's fine structure is
    then what is left of the background with the dither gone, not an element edge.
    """
    size = block_size(dpr)
    hp, blur, twin_hp, twin_blur = highpass(ref), box5(ref), highpass(twin), box5(twin)
    h, w = ref.shape
    top = int(90 * dpr)  # HUD strip (score, timer) stays out
    cands = []
    for by in range(top, h - size - 8, size // 4):
        for bx in range(8, w - size - 8, size // 4):
            sl = (slice(by, by + size), slice(bx, bx + size))
            mx = float(np.abs(hp[sl]).max())
            span = float(blur[sl].max() - blur[sl].min())
            smx = float(np.abs(twin_hp[sl]).max())
            tspan = float(twin_blur[sl].max() - twin_blur[sl].min())
            if max(mx, smx) <= FLAT_MAX_HP and max(span, tspan) <= FLAT_MAX_SPAN:
                cands.append((span + mx, bx, by, mx, span, smx))
    cands.sort()
    chosen = []
    for _, bx, by, mx, span, smx in cands:
        if all(abs(bx - c['box'][0]) >= size or abs(by - c['box'][1]) >= size for c in chosen):
            chosen.append({'box': [bx, by, size, size], 'maxAbsHp': round(mx, 3), 'blurSpan': round(span, 3),
                           'twinMaxAbsHp': round(smx, 3)})
        if len(chosen) == REGIONS:
            break
    return chosen


def scale_box(box, shape, ref_shape):
    sx, sy = shape[1] / ref_shape[1], shape[0] / ref_shape[0]
    return [round(box[0] * sx), round(box[1] * sy), round(box[2] * sx), round(box[3] * sy)]


def region_scores(y, boxes):
    hp = highpass(y)
    return [{'box': b, **score(hp[b[1]:b[1] + b[3], b[0]:b[0] + b[2]])} for b in boxes]


def summarize(rows):
    keys = ('rms', 'corrY2', 'corrX4')
    out = {k: round(float(np.mean([r[k] for r in rows])), 4) for k in keys}
    out['bandFree'] = {k: round(float(np.mean([r['bandFree'][k] for r in rows])), 4) for k in keys}
    return out


def is_grid(s):
    return s['corrY2'] >= GRID or s['corrX4'] >= GRID


def is_clean(rows, key=None):
    return all((r[key] if key else r)['corrY2'] < CLEAN and (r[key] if key else r)['corrX4'] < CLEAN for r in rows)


def save_crop(rgb, box, path):
    bx, by, bw, bh = box
    crop = Image.fromarray(rgb[by:by + bh, bx:bx + bw].astype(np.uint8))
    crop.save(path)
    crop.resize((bw * 8, bh * 8), Image.NEAREST).save(path.with_name(path.stem + '-x8.png'))


# Section palette stops (dark night band): any two close dark colours show it
DITHER_STOPS = ('#0b1024', '#1d2a4a')


def dither_probe(page, dpr):
    """Score a lone gradient fill and a solid fill: the browser's gradient dither alone."""
    y, _ = luma(base64.b64decode(page.evaluate('a => T713.dither(a[0], a[1])', list(DITHER_STOPS)).split(',', 1)[1]))
    h, w = y.shape
    hp = highpass(y)
    size = block_size(dpr)
    grad = (slice(size, size * 2), slice(w // 2 - size // 2, w // 2 + size // 2))
    solid = (slice(h - size * 2, h - size), grad[1])
    out = {'stops': DITHER_STOPS, 'gradient': score(hp[grad]), 'solid': score(hp[solid]),
           'gradientLags': spectrum(hp[grad])}
    print(f"dpr={dpr} dither gradient={out['gradient']} solid={out['solid']}", flush=True)
    return out


def png_of(page):
    return base64.b64decode(page.evaluate('() => T713.capture()').split(',', 1)[1])


def frame(page, dpr, config):
    """Luma, RGB and state of one draw() under config (stubs and quality reset first)."""
    page.evaluate('() => T713.reset()')
    page.evaluate('() => T713.quality(1, 1)')
    if config in LAYERS:
        page.evaluate('js => T713.stub(js)', LAYERS[config])
    backdrop, res = QUALITY_OF.get(config, (1, 1))
    page.evaluate('a => T713.quality(a[0], a[1])', [backdrop, res])
    # the resize handler is debounced (index.html, 100 ms)
    page.wait_for_function('w => canvas.width === w', arg=round(VIEWPORT['width'] * dpr * res))
    state = page.evaluate('() => T713.state()')
    y, rgb = luma(png_of(page))
    return y, rgb, state


def open_page(browser, url, dpr, query, init, errors):
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=dpr)
    if init:
        context.add_init_script(init)
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url + 'index.html' + query, wait_until='load')
    wait_for_boot_run(page)
    page.evaluate(HELPER)
    page.evaluate('() => T713.freeze()')
    return context, page


def measure(dprs, poses_only, configs_only):
    result = {'viewport': VIEWPORT, 'blockAtDpr2': BLOCK, 'flatMaxHp': FLAT_MAX_HP, 'flatMaxSpan': FLAT_MAX_SPAN,
              'gridThreshold': GRID, 'cleanThreshold': CLEAN, 'rows': [], 'dither': {}, 'pageErrors': []}
    crops = {}
    wanted = lambda c: not configs_only or c in configs_only or c in ('default', 'float16')
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        for dpr in dprs:
            pages = {}
            for name, (query, init, configs) in PAGES.items():
                configs = [c for c in configs if wanted(c)]
                if configs:
                    context, page = open_page(browser, url, dpr, query, init, result['pageErrors'])
                    stack.callback(context.close)
                    pages[name] = (page, configs)
            poses = pages['default'][0].evaluate('() => T713.poses()')
            for pose in poses:
                if poses_only and pose['name'] not in poses_only:
                    continue
                for page, _ in pages.values():
                    page.evaluate('p => T713.place(p)', pose)
                # Regions: blocks flat in both the default frame and its dither-free
                # twin (float16 page), reused for every configuration (scaled by the
                # backing size for the resolution steps)
                ref, _, _ = frame(pages['default'][0], dpr, 'default')
                again, _, _ = frame(pages['default'][0], dpr, 'default')
                # the frozen clock makes frames repeatable: a second default draw is
                # compared with the first (max abs luma difference, whole frame)
                result.setdefault('repeatability', []).append(
                    {'dpr': dpr, 'pose': pose['name'], 'maxAbsLumaDiff': round(float(np.abs(again - ref).max()), 4)})
                twin, _, _ = frame(pages['float16'][0], dpr, 'float16')
                regions = pick_regions(ref, twin, dpr)
                ref_blur = box5(ref)
                for page, configs in pages.values():
                    for config in configs:
                        y, rgb, state = frame(page, dpr, config)
                        use = [scale_box(r['box'], y.shape, ref.shape) for r in regions]
                        rows = region_scores(y, use)
                        if y.shape == ref.shape:
                            # low-frequency change against the default frame: the picture
                            # itself (not just its fine structure) differs by this much
                            blur = box5(y)
                            for row_, b in zip(rows, use):
                                sl = (slice(b[1], b[1] + b[3]), slice(b[0], b[0] + b[2]))
                                row_['lowpassDiff'] = round(float(np.abs(blur[sl] - ref_blur[sl]).mean()), 4)
                        s = summarize(rows) if rows else None
                        bx, by, bw, bh = use[0] if use else (0, 0, 0, 0)
                        row = {'dpr': dpr, 'pose': pose['name'], 'config': config, 'state': state,
                               'regions': rows, 'mean': s, 'grid': bool(s) and is_grid(s),
                               'clean': bool(rows) and is_clean(rows),
                               'cleanBandFree': bool(rows) and is_clean(rows, 'bandFree'),
                               'lags': spectrum(highpass(y)[by:by + bh, bx:bx + bw]) if use else None}
                        if config == 'default':
                            row['flatness'] = regions
                        result['rows'].append(row)
                        print(f"dpr={dpr} pose={pose['name']} config={config} canvas={state['canvas']} "
                              f"regions={len(rows)} mean={s} grid={row['grid']} clean={row['clean']} "
                              f"cleanBandFree={row['cleanBandFree']}", flush=True)
                        if dpr == 2 and pose['name'] == 'spawn' and use and config in CROPS:
                            crops[config] = (rgb, use[0])
            if not configs_only or 'dither' in configs_only:
                for page, _ in pages.values():
                    page.evaluate('() => T713.reset()')
                result['dither'][str(dpr)] = {name: dither_probe(pages[name][0], dpr)
                                              for name in ('default', 'float16')}
    return result, crops


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', required=True)
    parser.add_argument('--dpr', type=int, action='append')
    parser.add_argument('--pose', action='append')
    parser.add_argument('--config', action='append')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result, crops = measure(args.dpr or DPRS, args.pose, args.config)
    (out / 'grid.json').write_text(json.dumps(result, separators=(',', ':')))
    crop_dir = out / 'crops'
    crop_dir.mkdir(exist_ok=True)
    for config, (rgb, box) in crops.items():
        save_crop(rgb, box, crop_dir / f'dpr2-spawn-{config}.png')
    print(f"rows={len(result['rows'])} page_errors={len(result['pageErrors'])}")
    return 1 if result['pageErrors'] else 0


if __name__ == '__main__':
    sys.exit(main())
