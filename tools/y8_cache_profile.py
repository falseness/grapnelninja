"""Background/world cost, cache reuse and resize allocation behaviour (TASK-277).

Two separate evidence passes on the TASK-271/272/273 stack, never mixed:

  profile  INSTRUMENTED DIAGNOSTIC PASS (counters, rAF cancelled, draw() called
           by the harness): canvas allocations, backing-store writes/changes,
           cave tile builds, gradient builds, lightmap/glow-level resizes,
           letterbox bar repaints, cull-rect rebuilds, tile blits and their
           device-pixel area. Scenarios: repeated identical frames, harness
           camera shifts, ten settled viewport-resize cycles (real resize
           event -> 100 ms debounce -> onViewportResize), a duplicate resize,
           letterboxed identical frames and a DPR-only change. The draw()
           timings it records are JS submission only (the deferred canvas
           raster lands at commit, outside these spans: TASK-276).
  capture  UNINSTRUMENTED TIMING: requestAnimationFrame intervals plus the
           read-only TASK-273 sampler (camera travel), no counters, no per-call
           timing, no readback, no tracing. Scenes: stationary (empty replay:
           the ninja never leaves the camera dead zone, screen.x/y stay 0) and
           moving (seeded replay). Arms: control, background-off (TASK-272
           cave-background hook: clear + black fill), world-off (world-geometry
           hook). Contexts: dpr1 and dpr2, both 1280x720 CSS.

Actions: prepare, profile, capture, run, report, audit. Nothing here certifies
60 FPS, physical devices or release readiness; feature removal is diagnostic.
"""
import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_cost as fc  # noqa: E402
import y8_feature_ablation as ab  # noqa: E402
import y8_chill_ablation as ch  # noqa: E402

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
TASK = 'TASK-277'
MODULE_AT_CAPTURE = 'module-at-capture'
# Both contexts share the CSS viewport; only the device scale factor differs.
CONTEXTS = {
    'dpr1': {'profile': 'desktop', 'viewport': [1280, 720], 'dpr': 1},
    'dpr2': {'profile': 'desktop-dpr2', 'viewport': [1280, 720], 'dpr': 2},
}
fc.PROFILES.setdefault('desktop-dpr2', {'viewport': [1280, 720], 'dpr': 2, 'is_mobile': False,
                                        'has_touch': False, 'input': 'mouse'})
MAIN, CHILL = 'bad', 'classic'
MODES = (MAIN, CHILL)
MODE_SETUP = {MAIN: {'seed': 4, 'replay_style': 'screening'}, CHILL: {'seed': 7, 'replay_style': 'chill-ceiling'}}
SCENES = {
    'stationary': 'empty replay: no input, the ninja stays inside the camera dead zone (screen.x = screen.y = 0)',
    'moving': 'RENDER-TIME CAMERA DRIVE (page-only diagnostic): same empty replay and physics as stationary, but draw() runs with '
              'screen.x/y offset by a triangle wave (constant travel per frame, bounded amplitude) and restored afterwards; '
              'the only difference to stationary is a moving camera in rendering (parallax, culling, tile wrap, world translation)',
    'replay': 'seeded input replay (TASK-272 screening seed 4 for bad, TASK-273 chill-ceiling seed 7 for classic), control only, '
              'dpr1 only: natural camera travel is recorded, not guaranteed (bad mode and dpr2 never move the camera within 30 s: probe)',
}
REPLAY_CONTEXTS = ('dpr1',)
CAMERA_DRIVE_AMPLITUDE_RATIO = 0.2   # of the visible world width (width / scale[version])
CAMERA_DRIVE_STEPS_PER_HALF = 25     # frames from -amplitude to +amplitude
CAMERA_DRIVE_Y_RATIO = 0.1
ARMS = {
    'control': {'feature': None, 'label': 'unchanged renderer'},
    'background-off': {'feature': 'cave-background',
                       'label': 'drawBackgroundLayer -> clearAll + black fill (TASK-272 hook, RNG consumption kept)'},
    'world-off': {'feature': 'world-geometry', 'label': 'drawWorldLayer skipped (grapnel, floors, obstacles, walls)'},
}
ARM_ORDER = ('control', 'background-off', 'world-off')
SCENE_ORDER = ('stationary', 'moving')
REPS = ('r1', 'r2')
IDENTICAL_FRAMES = 60
CAMERA_STEPS = 30
RESIZE_CYCLES = 10
# Each cycle visits a smaller same-aspect window, a letterboxed 4:3 window, a wide window and the base size.
RESIZE_STEPS = ([960, 540], [640, 540], [1600, 800], [1280, 720])
LETTERBOX_FRAMES = 40
LOGICAL_HEIGHT = 1080
CACHE_BOUNDS = {'layerCache_entries': 2, 'gradientCache_entries': 3, 'glow_levels_per_renderer': 4,
                'tile_builds_per_settled_resize': 2, 'steady_state_reconstruction_allocations': 0,
                'steady_state_tile_builds': 0, 'steady_state_gradient_builds': 0, 'steady_state_main_backing_changes': 0,
                'steady_state_level_or_lightmap_changes': 0}
# Canvas allocations are attributed to the first non-hook stack frame. Reconstruction = a surface that already
# existed for the same viewport is built again; lazy = a sprite cache filled on first use (bounded by its key space).
RECONSTRUCTION_ORIGIN_MARKERS = ('getLayerTile', 'resize', 'configureCanvasViewport', 'VisualEffects')
KNOWN_LAZY_ORIGIN_MARKERS = ('drawElementLight', 'ShapeLight', 'shapeLight', 'GlowSprite', 'glowSprite', 'GLOW_SPRITES', 'Menu', 'Button',
                             'warmGlowSprites', 'HatchPattern', 'hatchPattern', 'drawRadialLight', 'getSprite', 'buildSprite')


def utc():
    return fc.utc()


def round_half_up(x):
    return math.floor(x + 0.5)


def debounce_ms_from_source(root=ROOT):
    """The resize debounce the runtime actually uses (index.html), not an assumed value."""
    text = (Path(root) / 'index.html').read_text()
    m = re.search(r'setTimeout\(onViewportResize,\s*(\d+)\)', text)
    if not m:
        raise fc.EvidenceError('resize debounce not found in index.html')
    return int(m.group(1))


def settle_extra_ms(debounce_ms):
    """Extra wait after the debounced handler ran: at least three debounces and 250 ms."""
    return max(250, 3 * debounce_ms)


def expected_dimensions(snapshot, constants):
    """Settled sizes recomputed from the runtime's own formulas, from recorded viewport/css/dpr."""
    vw, vh = snapshot['viewport']
    dpr = snapshot['density']
    aspect = min(2, max(4 / 3, vw / vh))
    logical_width = round_half_up(LOGICAL_HEIGHT * aspect)
    fit = min(vw / logical_width, vh / LOGICAL_HEIGHT)
    css = [logical_width * fit, LOGICAL_HEIGHT * fit]
    backing = [max(1, round_half_up(css[0] * dpr)), max(1, round_half_up(css[1] * dpr))]
    light = constants['lights_resolutionScale']
    tile_scale = max(0.25, min(constants['crystals_maxPixelScale'], backing[0] / logical_width))
    levels = {}
    for name in ('ambientGlow', 'playerGlow'):
        cfg = constants['glow'][name]
        w, h = max(1, math.floor(backing[0] * cfg['resolutionScale'])), max(1, math.floor(backing[1] * cfg['resolutionScale']))
        chain = []
        for _ in range(cfg['blurLevels']):
            chain.append([w, h])
            w, h = max(1, w // 2), max(1, h // 2)
        levels[name] = chain
    bar_scale = constants['window_background_scale']
    bars = []
    left, top = (vw - css[0]) / 2, (vh - css[1]) / 2
    overlap = 2 + 2 / bar_scale
    if left >= 0.5:
        boxes = [[left + overlap, vh], [vw - (left + css[0]) + overlap, vh]]
    elif top >= 0.5:
        boxes = [[vw, top + overlap], [vw, vh - (top + css[1]) + overlap]]
    else:
        boxes = []
    for bw, bh in boxes:
        bars.append([max(1, math.ceil(bw * bar_scale)), max(1, math.ceil(bh * bar_scale))])
    return {'logical_width': logical_width, 'css': css, 'backing': backing,
            'lightmap': [max(1, math.ceil(logical_width * light)), max(1, math.ceil(LOGICAL_HEIGHT * light))],
            'tile': [max(1, round_half_up(logical_width * tile_scale)), max(1, round_half_up(LOGICAL_HEIGHT * tile_scale))],
            'tile_key': [logical_width, LOGICAL_HEIGHT, tile_scale], 'glow_levels': levels, 'bars': bars}


def settled_assertions(snapshot, constants):
    """Compare a recorded snapshot with the recomputed expectations; every entry must pass."""
    exp = expected_dimensions(snapshot, constants)
    checks = {
        'resize_timer_idle': snapshot['resizeTimerNull'] is True,
        'logical_width': snapshot['logical'][0] == exp['logical_width'] == snapshot['computedLogicalWidth'],
        'css_rect': all(abs(a - b) < 0.51 for a, b in zip([snapshot['css']['width'], snapshot['css']['height']], exp['css'])),
        'main_backing_equals_round_css_times_dpr': snapshot['canvas'] == exp['backing'],
        'lightmap_backing': snapshot['lightmap'] == exp['lightmap'],
        'tile_backings': all(snapshot['tiles'].get(n, {}).get('size') == exp['tile'] for n in ('far', 'near')),
        'tile_keys_match_viewport': all(_key_matches(snapshot['tiles'].get(n, {}).get('key'), exp['tile_key']) for n in ('far', 'near')),
        'glow_levels': all(snapshot['glowLevels'].get(n) == exp['glow_levels'][n] for n in exp['glow_levels']),
        'bar_backings': sorted(snapshot['bars']) == sorted(exp['bars']),
    }
    return {'expected': exp, 'checks': checks, 'settled': all(checks.values())}


def _key_matches(key, expected):
    if not key:
        return False
    parts = key.split('|')
    if len(parts) != 3:
        return False
    try:
        return all(abs(float(p) - e) < 1e-9 for p, e in zip(parts, expected))
    except ValueError:
        return False


def delta(before, after):
    keys = set(before) | set(after)
    return {k: round(after.get(k, 0) - before.get(k, 0), 6) for k in sorted(keys) if after.get(k, 0) != before.get(k, 0)}


def case_name(context, mode, arm, scene, rep, index):
    return f'{context}-{mode}-{arm}-{scene}-{rep}-i{index}'


def sequence(rep, context='dpr1'):
    seq = [(arm, scene) for arm in ARM_ORDER for scene in SCENE_ORDER]
    if context in REPLAY_CONTEXTS:
        seq.append(('control', 'replay'))
    return seq if rep == 'r1' else list(reversed(seq))


def preserve_module(out):
    folder = Path(out) / MODULE_AT_CAPTURE
    folder.mkdir(parents=True, exist_ok=True)
    digest = fc.sha_file(MODULE)
    target = folder / f'y8_cache_profile-{digest[:8]}.py'
    if not target.exists():
        shutil.copyfile(MODULE, target)
    return digest


# ------------------------------------------------------------ page code --

PROFILE_INSTRUMENT = '''(cfg) => {
    const P = window.__cacheProfile = {cfg, counters: {}, log: [], frames: 0}
    const C = P.counters
    const inc = (k, n) => { C[k] = (C[k] || 0) + (n === undefined ? 1 : n) }
    P.densityPin = 'absent'
    if (typeof RENDER_BUDGET !== 'undefined') {
        RENDER_BUDGET.densityLimit = cfg.dpr
        RENDER_BUDGET.observe = () => false
        P.densityPin = 'pinned: RENDER_BUDGET.densityLimit=' + cfg.dpr + '; adaptive observe disabled (page only)'
    }
    const create = Document.prototype.createElement
    const origin = () => {
        const lines = String(new Error().stack || '').split('\\n').slice(1)
        const frame = lines.find(l => l.includes(' at ') && !l.includes('createElement') && !l.includes('origin')) || 'unknown'
        const m = frame.match(/at (?:new )?([^ (]+)/)
        return m ? m[1] : 'anonymous'
    }
    Document.prototype.createElement = function(name) {
        const el = create.apply(this, arguments)
        if (String(name).toLowerCase() === 'canvas') { inc('canvasAllocations'); inc('alloc:' + origin()) }
        return el
    }
    for (const key of ['width', 'height']) {
        const d = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, key)
        Object.defineProperty(HTMLCanvasElement.prototype, key, {...d, set(v) {
            inc('backingWrites')
            if (d.get.call(this) !== v) {
                inc('backingChanges')
                inc(this === canvas ? 'mainBackingChanges' : (this.classList && this.classList.contains('window-bar') ? 'barBackingChanges' : 'offscreenBackingChanges'))
            }
            return d.set.call(this, v)
        }})
    }
    const di = CanvasRenderingContext2D.prototype.drawImage
    CanvasRenderingContext2D.prototype.drawImage = function(img) {
        inc('drawImageCalls')
        const tiles = (typeof visualEffects !== 'undefined' && visualEffects) ? visualEffects.background.layerCache : null
        if (tiles && ((tiles.far && img === tiles.far.canvas) || (tiles.near && img === tiles.near.canvas))) {
            const a = arguments
            let dw, dh
            if (a.length >= 9) { dw = a[7]; dh = a[8] } else if (a.length >= 5) { dw = a[3]; dh = a[4] } else { dw = img.width; dh = img.height }
            let dx, dy
            if (a.length >= 9) { dx = a[5]; dy = a[6] } else if (a.length >= 3) { dx = a[1]; dy = a[2] } else { dx = 0; dy = 0 }
            const m = this.getTransform()
            const x0 = m.a * dx + m.e, y0 = m.d * dy + m.f, x1 = x0 + m.a * dw, y1 = y0 + m.d * dh
            const cw = this.canvas.width, chh = this.canvas.height
            const vis = Math.max(0, Math.min(Math.max(x0, x1), cw) - Math.max(Math.min(x0, x1), 0)) * Math.max(0, Math.min(Math.max(y0, y1), chh) - Math.max(Math.min(y0, y1), 0))
            const onBar = this.canvas && this.canvas.classList && this.canvas.classList.contains('window-bar')
            inc(onBar ? 'tileBlitsBars' : 'tileBlits')
            inc(onBar ? 'tileBlitDevicePxBars' : 'tileBlitDevicePx', Math.abs(dw * m.a) * Math.abs(dh * m.d))
            inc(onBar ? 'tileBlitVisiblePxBars' : 'tileBlitVisiblePx', vis)
            if (vis < 1) inc(onBar ? 'tileBlitsClippedAwayBars' : 'tileBlitsClippedAway')
        }
        return di.apply(this, arguments)
    }
    const timed = (proto, name, key) => {
        const f = proto[name]
        if (typeof f !== 'function') { inc(key + ':ABSENT'); return }
        proto[name] = function() { const t0 = performance.now(); try { return f.apply(this, arguments) } finally { inc(key); inc(key + 'Ms', performance.now() - t0) } }
    }
    const BG = BackgroundRenderer.prototype
    timed(BG, 'buildGradients', 'gradientBuilds')
    timed(BG, 'paintCrystalTile', 'tileBuildsFar')
    timed(BG, 'paintNearTile', 'tileBuildsNear')
    timed(BG, 'draw', 'backgroundDraws')
    timed(BG, 'drawWindowBars', 'barChecks')
    const gc = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function() {
        if (this.classList && this.classList.contains('window-bar')) inc('barPaints')
        return gc.apply(this, arguments)
    }
    const resized = (proto, key, dims) => {
        const f = proto.resize
        proto.resize = function() { const before = JSON.stringify(dims(this)); const r = f.apply(this, arguments)
            inc(key + 'Calls'); if (JSON.stringify(dims(this)) !== before) inc(key + 'Changes'); return r }
    }
    resized(LightmapRenderer.prototype, 'lightmapResize', r => [r.lightCanvas.width, r.lightCanvas.height])
    resized(BloomRenderer.prototype, 'glowLevelResize', r => r.levels.map(l => [l.canvas.width, l.canvas.height]))
    const wrapGlobal = (name, key) => {
        const f = window[name]
        if (typeof f !== 'function') { inc(key + ':ABSENT'); return }
        window[name] = function() { inc(key); return f.apply(this, arguments) }
    }
    wrapGlobal('getCullPadding', 'cullRectRebuilds')
    wrapGlobal('configureCanvasViewport', 'configureCanvasViewportCalls')
    wrapGlobal('onViewportResize', 'onViewportResizeCalls')
    wrapGlobal('rebuildMenu', 'menuRebuilds')
    wrapGlobal('warmGlowSprites', 'glowSpriteWarmups')
    try {
        const Factory = ElementsFactory  // class declaration: a global lexical binding, not a window property
        ElementsFactory = class extends Factory { constructor() { super(...arguments); inc('factoryRebuilds') } }
    } catch (e) { inc('factoryRebuilds:ABSENT') }
    P.constants = {
        crystals_maxPixelScale: STYLE.caveLayers.crystals.maxPixelScale,
        nearRocks_maxPixelScale: STYLE.caveLayers.nearRocks.maxPixelScale,
        lights_resolutionScale: STYLE.lights.resolutionScale,
        window_background_scale: WINDOW_BACKGROUND_SCALE, window_bars_every_frames: WINDOW_BARS_EVERY_FRAMES,
        glow: {ambientGlow: {resolutionScale: STYLE.ambient.glow.resolutionScale, blurLevels: STYLE.ambient.glow.blurLevels},
               playerGlow: {resolutionScale: STYLE.player.glow.resolutionScale, blurLevels: STYLE.player.glow.blurLevels}},
        features: Object.assign({}, STYLE.features),
        quality: Object.fromEntries(Object.entries(QUALITY).filter(([k, v]) => typeof v !== 'function'))
    }
}'''

SNAPSHOT = '''() => {
    const seen = new Set(), canvases = []
    const push = (c, path) => { seen.add(c); canvases.push({path, width: c.width, height: c.height, area: c.width * c.height}) }
    push(canvas, 'dom#canvas')
    const bars = []
    document.querySelectorAll('canvas.window-bar').forEach((c, i) => { push(c, 'dom.window-bar[' + i + ']' + (c.hidden ? ':hidden' : '')); if (!c.hidden) bars.push([c.width, c.height]) })
    const visit = (v, path, depth) => {
        if (!v || typeof v !== 'object' || seen.has(v) || depth > 8) return
        if (v instanceof HTMLCanvasElement) { push(v, path); return }
        if (typeof CanvasRenderingContext2D !== 'undefined' && v instanceof CanvasRenderingContext2D) return
        if (v instanceof HTMLElement || v instanceof CanvasGradient || v instanceof CanvasPattern) return
        seen.add(v)
        if (v instanceof Map) { let i = 0; for (const x of v.values()) visit(x, path + '[' + (i++) + ']', depth + 1); return }
        if (Array.isArray(v)) { v.forEach((x, i) => visit(x, path + '[' + i + ']', depth + 1)); return }
        for (const k of Object.keys(v)) visit(v[k], path + '.' + k, depth + 1)
    }
    visit(visualEffects, 'visualEffects', 0)
    if (typeof GLOW_SPRITES !== 'undefined') visit(GLOW_SPRITES.cache, 'GLOW_SPRITES.cache', 0)
    const bg = visualEffects.background
    const tiles = {}
    for (const [n, l] of Object.entries(bg.layerCache)) tiles[n] = {key: l.key, size: [l.canvas.width, l.canvas.height]}
    const r = canvas.getBoundingClientRect()
    return {
        canvas: [canvas.width, canvas.height], css: getCanvasCssRect(), cssRect: [r.width, r.height],
        viewport: [innerWidth, innerHeight], dpr: devicePixelRatio, density: getRenderDensity(),
        logical: [width, height], computedLogicalWidth: computeLogicalWidth(), resizeTimerNull: resizeTimer === null,
        version: typeof version !== 'undefined' ? version : null, camera: [screen.x, screen.y],
        lightmap: [visualEffects.lightmap.lightCanvas.width, visualEffects.lightmap.lightCanvas.height],
        glowLevels: {ambientGlow: visualEffects.ambientGlow.levels.map(l => [l.canvas.width, l.canvas.height]),
                     playerGlow: visualEffects.playerGlow.levels.map(l => [l.canvas.width, l.canvas.height]),
                     bloom: visualEffects.bloom.levels.map(l => [l.canvas.width, l.canvas.height])},
        tiles, bars, gradientCacheSize: bg.gradientCache.size,
        glowSpriteCacheSize: typeof GLOW_SPRITES !== 'undefined' ? GLOW_SPRITES.cache.size : null,
        canvases, canvasCount: canvases.length,
        offscreenArea: canvases.filter(c => c.path !== 'dom#canvas').reduce((a, c) => a + c.area, 0),
        counters: Object.assign({}, __cacheProfile.counters)
    }
}'''

DRAW_FRAMES = '''(n) => { const times = []
    for (let i = 0; i < n; ++i) { const t0 = performance.now(); draw(); times.push(performance.now() - t0) }
    return times }'''

CAMERA_SHIFTS = '''(cfg) => { const out = [], P = __cacheProfile
    const start = [screen.x, screen.y]
    for (let i = 0; i < cfg.steps; ++i) {
        screen.x = start[0] - (i + 1) * cfg.dx
        screen.y = start[1] + (i % 2 ? -1 : 1) * cfg.dy
        const before = Object.assign({}, P.counters)
        const t0 = performance.now(); draw(); const ms = performance.now() - t0
        const c = P.counters
        out.push({camera: [screen.x, screen.y], draw_ms: ms, tileBlits: (c.tileBlits || 0) - (before.tileBlits || 0),
                  tileBlitDevicePx: (c.tileBlitDevicePx || 0) - (before.tileBlitDevicePx || 0),
                  tileBlitVisiblePx: (c.tileBlitVisiblePx || 0) - (before.tileBlitVisiblePx || 0),
                  drawImageCalls: (c.drawImageCalls || 0) - (before.drawImageCalls || 0)})
    }
    screen.x = start[0]; screen.y = start[1]
    return {start, steps: out} }'''

COUNTERS = '() => Object.assign({}, __cacheProfile.counters)'

# Installed after fc.INSTRUMENT and the sampler, before startGame, for the 'moving' scene only. Wraps the global
# draw(): physics never sees the offset (restored in finally), the sampler reads the restored camera, so its
# travel stays 0 and the drive records its own per-frame travel.
CAMERA_DRIVE = '''(cfg) => {
    const FC = window.__featureCost
    const D = FC.cameraDrive = {frames: 0, travel_px: 0, amplitude: null, step: null, y_ratio: cfg.y_ratio, offsets: [], label: cfg.label}
    const inner = window.draw
    let phase = 0, last = null
    window.draw = function() {
        if (D.amplitude === null) {
            D.amplitude = cfg.amplitude_ratio * width / scale[version]
            D.step = D.amplitude / cfg.steps_per_half
        }
        const period = 2 * cfg.steps_per_half
        const k = phase % period
        const tri = k < cfg.steps_per_half ? -D.amplitude + k * D.step : D.amplitude - (k - cfg.steps_per_half) * D.step
        const ox = tri, oy = cfg.y_ratio * tri
        const sx = screen.x, sy = screen.y
        screen.x = sx + ox; screen.y = sy + oy
        try { return inner.apply(this, arguments) }
        finally {
            screen.x = sx; screen.y = sy
            if (last) D.travel_px += Math.abs(ox - last[0]) + Math.abs(oy - last[1])
            last = [ox, oy]; D.frames++; phase++
            if (D.offsets.length < 4000) D.offsets.push([Math.round(ox * 10) / 10, Math.round(oy * 10) / 10])
        }
    }
}'''


# -------------------------------------------------------------- prepare --

def prepare(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = utc()
    identity = fc.build_trees(out)
    ceiling = fc.environment_ceiling('desktop')
    module_sha = preserve_module(out)
    fc.dump(out / 'identity.json', {'task': TASK, 'utc_start': started, 'utc_end': utc(), 'argv': sys.argv,
                                    'identity': identity, 'environment_ceiling': ceiling,
                                    'debounce_ms_from_source': debounce_ms_from_source(),
                                    'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
                                    'chill_sha256': fc.sha_file(ch.MODULE), 'module_sha256': module_sha,
                                    'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py')})
    print('PASS identity written', out / 'identity.json', 'HEAD', identity['current_commit'],
          'dirty_runtime=%r' % identity['current_dirty_runtime'], 'ceiling_fps=%.2f' % ceiling['average_fps'],
          'debounce_ms=%d' % debounce_ms_from_source())
    return 0


# -------------------------------------------------------------- profile --

def common_raw(args, context, extra):
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    return root, {'case': args.case, 'task': TASK, 'argv': sys.argv, 'started_utc': utc(),
                  'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
                  'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
                  'chill_sha256': fc.sha_file(ch.MODULE), 'module_sha256': preserve_module(args.output),
                  'network': [], 'errors': [], 'console_errors': [], **extra}


def open_page(stack, root, raw, context, seed, cpu_throttle):
    from browser_test_support import start_browser_test
    url, browser = start_browser_test(root, stack.callback)
    raw['environment'] = fc.environment(browser)
    ctx = fc.new_context(browser, context['profile'], seed, raw['network'])
    stack.callback(ctx.close)
    page = ctx.new_page()
    page.on('pageerror', lambda e: raw['errors'].append(str(e)))
    page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
    cdp = ctx.new_cdp_session(page)
    cdp.send('Emulation.setCPUThrottlingRate', {'rate': cpu_throttle})
    page.goto(url + 'index.html', wait_until='domcontentloaded')
    page.wait_for_function(fc.BOOTED, timeout=60000)
    return page, ctx, cdp


def wait_counter(page, key, minimum, timeout_ms):
    page.wait_for_function('([k, n]) => (__cacheProfile.counters[k] || 0) >= n', arg=[key, minimum], timeout=timeout_ms)


def settled_step(page, debounce_ms, requested, trigger, constants, raw_steps):
    """Trigger a viewport change, wait for the real debounced handler plus the extra settle, draw, snapshot."""
    before = page.evaluate(SNAPSHOT)
    calls = before['counters'].get('onViewportResizeCalls', 0)
    t0 = time.perf_counter()
    trigger()
    waited = {'handler_seen': True}
    try:
        wait_counter(page, 'onViewportResizeCalls', calls + 1, 5000)
    except Exception as e:
        waited = {'handler_seen': False, 'error': str(e).splitlines()[0]}
    page.wait_for_timeout(settle_extra_ms(debounce_ms))
    handler_wait_ms = (time.perf_counter() - t0) * 1000
    draw_ms = page.evaluate(DRAW_FRAMES, 1)
    after = page.evaluate(SNAPSHOT)
    settled = settled_assertions(after, constants)
    step = {'requested_viewport': requested, 'before': _dims(before), 'after': _dims(after),
            'dimensions_changed': {'viewport': before['viewport'] != after['viewport'], 'backing': before['canvas'] != after['canvas'],
                                   'logical_width': before['logical'][0] != after['logical'][0],
                                   'tiles': before['tiles'] != after['tiles'], 'lightmap': before['lightmap'] != after['lightmap'],
                                   'glow_levels': before['glowLevels'] != after['glowLevels'], 'bars': before['bars'] != after['bars']},
            'debounce_ms': debounce_ms, 'settle_extra_ms': settle_extra_ms(debounce_ms), 'wall_wait_ms': handler_wait_ms,
            'handler': waited, 'counters_delta': delta(before['counters'], after['counters']),
            'first_draw_js_ms': draw_ms[0], 'settled': settled, 'canvasCount': after['canvasCount'],
            'offscreenArea': after['offscreenArea'], 'canvases': after['canvases']}
    raw_steps.append(step)
    return step


def _dims(s):
    return {'viewport': s['viewport'], 'dpr': s['dpr'], 'density': s['density'], 'css': [s['css']['width'], s['css']['height']],
            'canvas': s['canvas'], 'logical': s['logical'], 'tiles': s['tiles'], 'lightmap': s['lightmap'],
            'glowLevels': s['glowLevels'], 'bars': s['bars'], 'gradientCacheSize': s['gradientCacheSize'],
            'glowSpriteCacheSize': s['glowSpriteCacheSize'], 'canvasCount': s['canvasCount'], 'offscreenArea': s['offscreenArea']}


def profile(args):
    context = CONTEXTS[args.context]
    debounce = debounce_ms_from_source(Path(args.root))
    seed = MODE_SETUP[args.mode]['seed']
    root, raw = common_raw(args, context, {
        'pass': 'profile', 'context': args.context, 'mode': args.mode,
        'settings': {'context': args.context, 'profile': context['profile'], 'viewport': context['viewport'], 'dpr': context['dpr'],
                     'cpu_throttle': args.cpu_throttle, 'seed': seed, 'mode': args.mode, 'debounce_ms_from_source': debounce,
                     'settle_extra_ms': settle_extra_ms(debounce), 'identical_frames': args.identical_frames,
                     'camera_steps': args.camera_steps, 'resize_cycles': args.resize_cycles, 'resize_steps': list(RESIZE_STEPS),
                     'letterbox_frames': args.letterbox_frames,
                     'instrumentation': 'INSTRUMENTED DIAGNOSTIC PASS: page-only counters on createElement, canvas width/height setters, '
                                        'drawImage, BackgroundRenderer tile/gradient builds, Lightmap/Bloom resize, bar getContext, '
                                        'getCullPadding; requestAnimationFrame cancelled, draw() called by the harness; '
                                        'draw() ms are JS submission only, never raster/GPU cost',
                     'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter'}})
    exit_code = 1
    with ExitStack() as stack:
        page, ctx, cdp = open_page(stack, root, raw, context, seed, args.cpu_throttle)
        page.evaluate(PROFILE_INSTRUMENT, {'dpr': context['dpr']})
        raw['densityPin'] = page.evaluate('() => __cacheProfile.densityPin')
        raw['constants'] = page.evaluate('() => __cacheProfile.constants')
        constants = raw['constants']
        raw['boot_counters'] = page.evaluate(COUNTERS)
        page.evaluate('mode => startGame(mode)', args.mode)
        # let the live loop render a few frames (glow sprite warm-up, first tiles), then take over
        page.wait_for_function('() => drawFrameId >= 3', timeout=30000)
        page.evaluate('() => { cancelAnimationFrame(game); game = null }')
        page.wait_for_timeout(50)
        raw['after_start'] = page.evaluate(SNAPSHOT)
        raw['raf_cancelled'] = page.evaluate('() => game === null')

        # 1. repeated identical frames (camera and viewport unchanged)
        before = page.evaluate(SNAPSHOT)
        times = page.evaluate(DRAW_FRAMES, args.identical_frames)
        after = page.evaluate(SNAPSHOT)
        raw['identical_frames'] = {'frames': args.identical_frames, 'camera': after['camera'],
                                   'counters_delta': delta(before['counters'], after['counters']),
                                   'draw_js_ms': times, 'inventory_before': _dims(before), 'inventory_after': _dims(after)}
        # 2. harness camera shifts (diagnostic: screen.x/y moved by the harness, physics not stepped)
        before = page.evaluate(SNAPSHOT)
        shifts = page.evaluate(CAMERA_SHIFTS, {'steps': args.camera_steps, 'dx': 37, 'dy': 9})
        after = page.evaluate(SNAPSHOT)
        raw['camera_shifts'] = {'steps': args.camera_steps, 'dx': 37, 'dy': 9, 'start': shifts['start'], 'per_step': shifts['steps'],
                                'counters_delta': delta(before['counters'], after['counters']),
                                'inventory_before': _dims(before), 'inventory_after': _dims(after)}
        # 3. ten resize cycles through the real resize event + debounce
        raw['resize_cycles'] = []
        for cycle in range(args.resize_cycles):
            steps = []
            for w, h in RESIZE_STEPS:
                settled_step(page, debounce, [w, h], lambda w=w, h=h: page.set_viewport_size({'width': w, 'height': h}), constants, steps)
            raw['resize_cycles'].append({'cycle': cycle, 'steps': steps})
        # 4. duplicate resize at the settled base size: the event fires, nothing may be rebuilt
        dup = []
        settled_step(page, debounce, list(RESIZE_STEPS[-1]), lambda: page.evaluate("() => window.dispatchEvent(new Event('resize'))"),
                     constants, dup)
        raw['duplicate_resize'] = dup[0]
        # 5. letterboxed identical frames (bars present)
        box = []
        settled_step(page, debounce, list(RESIZE_STEPS[1]), lambda: page.set_viewport_size({'width': RESIZE_STEPS[1][0], 'height': RESIZE_STEPS[1][1]}),
                     constants, box)
        before = page.evaluate(SNAPSHOT)
        times = page.evaluate(DRAW_FRAMES, args.letterbox_frames)
        after = page.evaluate(SNAPSHOT)
        raw['letterbox_identical_frames'] = {'resize_step': box[0], 'frames': args.letterbox_frames, 'camera': after['camera'],
                                             'bars': after['bars'], 'counters_delta': delta(before['counters'], after['counters']),
                                             'draw_js_ms': times, 'inventory_after': _dims(after)}
        back = []
        settled_step(page, debounce, list(RESIZE_STEPS[-1]), lambda: page.set_viewport_size({'width': RESIZE_STEPS[-1][0], 'height': RESIZE_STEPS[-1][1]}),
                     constants, back)
        raw['letterbox_identical_frames']['return_step'] = back[0]
        # 6. DPR-only change on an unchanged CSS viewport (matchMedia resolution path or resize path, whichever fires)
        other = 2 if context['dpr'] == 1 else 1
        before = page.evaluate(SNAPSHOT)
        calls = before['counters'].get('configureCanvasViewportCalls', 0)
        page.evaluate('d => { RENDER_BUDGET.densityLimit = d }', other)
        cdp.send('Emulation.setDeviceMetricsOverride', {'width': context['viewport'][0], 'height': context['viewport'][1],
                                                        'deviceScaleFactor': other, 'mobile': False})
        seen = True
        try:
            wait_counter(page, 'configureCanvasViewportCalls', calls + 1, 5000)
        except Exception as e:
            seen = False
        page.wait_for_timeout(settle_extra_ms(debounce))
        page.evaluate(DRAW_FRAMES, 1)
        after = page.evaluate(SNAPSHOT)
        raw['dpr_only'] = {'from_dpr': context['dpr'], 'to_dpr': other, 'density_pin_raised_to': other, 'configure_seen': seen,
                           'before': _dims(before), 'after': _dims(after), 'backing_changed': before['canvas'] != after['canvas'],
                           'counters_delta': delta(before['counters'], after['counters']),
                           'via_resize_handler': after['counters'].get('onViewportResizeCalls', 0) > before['counters'].get('onViewportResizeCalls', 0),
                           'settled': settled_assertions(after, constants)}
        page.evaluate('d => { RENDER_BUDGET.densityLimit = d }', context['dpr'])
        cdp.send('Emulation.setDeviceMetricsOverride', {'width': context['viewport'][0], 'height': context['viewport'][1],
                                                        'deviceScaleFactor': context['dpr'], 'mobile': False})
        page.wait_for_timeout(settle_extra_ms(debounce))
        page.evaluate(DRAW_FRAMES, 1)
        raw['final'] = page.evaluate(SNAPSHOT)
        raw['ended_utc'] = utc()
    try:
        check_profile(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw['result'] = 'FAILED: ' + str(e)
    path = unique_path(Path(args.output) / 'profile', args.case, '.json')
    fc.dump(path, raw)
    s = raw.get('after_start') or {}
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path, raw['result'], 'backing=%s logical=%s tiles=%s' % (
        s.get('canvas'), s.get('logical'), {n: t['size'] for n, t in (s.get('tiles') or {}).items()}),
          'identical_delta=%s' % json.dumps(raw.get('identical_frames', {}).get('counters_delta')),
          'resize_steps_settled=%d/%d' % profile_settled_counts(raw), flush=True)
    return exit_code


def unique_path(folder, case, suffix):
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f'{case}{suffix}', 1
    while path.exists():
        n += 1
        path = folder / f'{case}.attempt{n}{suffix}'
    return path


def profile_steps(raw):
    return [s for c in raw.get('resize_cycles', []) for s in c['steps']]


def profile_settled_counts(raw):
    steps = profile_steps(raw)
    return sum(1 for s in steps if s['settled']['settled']), len(steps)


def check_profile(raw):
    if raw['errors']:
        raise fc.EvidenceError('page errors: ' + json.dumps(raw['errors']))
    if raw['after_start']['version'] != raw['mode']:
        raise fc.EvidenceError('mode not started')
    if not raw['raf_cancelled']:
        raise fc.EvidenceError('requestAnimationFrame loop still running')
    absent = [k for k in raw['final']['counters'] if k.endswith(':ABSENT')]
    if absent:
        raise fc.EvidenceError('hooks absent: ' + ', '.join(absent))
    steps = profile_steps(raw)
    if len(steps) != raw['settings']['resize_cycles'] * len(RESIZE_STEPS):
        raise fc.EvidenceError('resize steps missing')
    for i, s in enumerate(steps):
        if not s['handler']['handler_seen']:
            raise fc.EvidenceError(f'resize step {i}: onViewportResize never ran')
        if s['wall_wait_ms'] <= s['debounce_ms']:
            raise fc.EvidenceError(f'resize step {i}: waited {s["wall_wait_ms"]:.0f} ms, not beyond the {s["debounce_ms"]} ms debounce')
        if not s['settled']['settled']:
            raise fc.EvidenceError(f'resize step {i}: dimensions not settled: {s["settled"]["checks"]}')
        if not (s['dimensions_changed']['viewport'] and s['dimensions_changed']['backing']):
            raise fc.EvidenceError(f'resize step {i}: viewport/backing did not change')
    if raw['duplicate_resize']['dimensions_changed']['backing'] or not raw['duplicate_resize']['handler']['handler_seen']:
        raise fc.EvidenceError('duplicate resize: handler missing or backing changed')


# -------------------------------------------------------------- capture --

def replay_for(mode, scene, profile, warmup_ms, window_ms, windows):
    if scene != 'replay':
        return []
    setup = MODE_SETUP[mode]
    return ch.replay_script(setup['seed'], profile, warmup_ms + windows * window_ms + 1000, setup['replay_style'])


def capture(args):
    context = CONTEXTS[args.context]
    arm = ARMS[args.arm]
    setup = MODE_SETUP[args.mode]
    replay = replay_for(args.mode, args.scene, context['profile'], args.warmup_ms, args.window_ms, args.windows)
    settings = {'mode': args.mode, 'mode_name': ch.MODE_NAMES[args.mode], 'population': 'cache-profile-timing',
                'context': args.context, 'profile': context['profile'], 'viewport': context['viewport'], 'dpr': context['dpr'],
                'is_mobile': False, 'has_touch': False, 'input': 'mouse', 'cpu_throttle': args.cpu_throttle, 'seed': setup['seed'],
                'scene': args.scene, 'scene_label': SCENES[args.scene], 'arm': args.arm, 'arm_label': arm['label'],
                'feature': arm['feature'], 'ablate': [arm['feature']] if arm['feature'] else [],
                'replay_style': setup['replay_style'] if args.scene == 'replay' else None,
                'camera_drive': {'amplitude_ratio': CAMERA_DRIVE_AMPLITUDE_RATIO, 'steps_per_half': CAMERA_DRIVE_STEPS_PER_HALF,
                                 'y_ratio': CAMERA_DRIVE_Y_RATIO} if args.scene == 'moving' else None,
                'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows,
                'replay_sha256': fc.replay_sha256(replay), 'diagnostic': False,
                'density': 'pinned to context DPR; adaptive observe disabled',
                'instrumentation': 'timing arm: rAF intervals + read-only sampler only; no counters, no per-call timing, '
                                   'no readback, no tracing',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                                 'PLATFORM falls back to the local adapter (no ads, instant restart on death)'}
    root, raw = common_raw(args, context, {'pass': 'timing', 'settings': settings, 'replay': replay,
                                            'feature_spec': ab.FEATURES.get(arm['feature'])})
    cfg = {'dpr': context['dpr'], 'input': 'mouse', 'ablate': [], 'diagnostic': False, 'replay': replay,
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    exit_code = 1
    with ExitStack() as stack:
        page, ctx, cdp = open_page(stack, root, raw, context, setup['seed'], args.cpu_throttle)
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate(ab.FEATURE_INSTRUMENT, ab.feature_cfg(arm['feature']))
        page.evaluate(ch.SAMPLER)
        if args.scene == 'moving':
            page.evaluate(CAMERA_DRIVE, dict(settings['camera_drive'], label=SCENES['moving']))
        page.evaluate('mode => startGame(mode)', args.mode)
        try:
            page.wait_for_function(f'{fc.MARKER}.done || {fc.MARKER}.error', timeout=args.timeout_ms)
        except Exception as e:
            raw['errors'].append('timeout: ' + str(e).splitlines()[0])
        page.evaluate(f'() => {{ {fc.MARKER}.cfg.replay = "<see raw.replay>" }}')
        raw.update(page.evaluate(fc.MARKER))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['ended_utc'] = utc()
    raw['frames_sha256'] = fc.frames_sha256(raw['frames'])
    raw['samples_sha256'] = fc.frames_sha256(raw['samples'])
    try:
        check_capture(raw)
        raw['summary'] = fc.summarize(raw)
        raw['density'] = ch.window_density(raw)
        check_scene(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw.setdefault('summary', None)
        raw.setdefault('density', None)
        raw['result'] = 'FAILED: ' + str(e)
    path = fc.raw_path(args.output, args.case)
    fc.dump(path, raw)
    c = raw['summary']['combined'] if raw.get('summary') else None
    d = raw.get('density')
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'backing=%s css=%s dpr=%s' % (raw['dimensions']['canvas'], raw['dimensions']['css'], raw['dimensions']['dpr']),
          'fps=%.2f mean_ms=%.2f p50=%.2f p95=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], 1000 / c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'], c['active_ms'],
              raw['summary']['deaths']) if c else '',
          'camera_travel=%.0f moving=%.2f' % (d['camera']['travel_px'], d['camera']['moving_fraction'] or 0) if d else '', flush=True)
    return exit_code


def expected_backing(dimensions):
    css = dimensions['css']
    dpr = dimensions['dpr']
    return [max(1, round_half_up(css[0] * dpr)), max(1, round_half_up(css[1] * dpr))]


def check_capture(raw):
    s = raw['settings']
    if raw['errors'] or raw['error']:
        raise fc.EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw['error']]))
    if raw['dimensions']['platform'] not in ('disabled', 'absent'):
        raise fc.EvidenceError('SDK isolation failed: ' + str(raw['dimensions']['platform']))
    if raw['dimensions']['version'] != s['mode']:
        raise fc.EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
    if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
        raise fc.EvidenceError('backing size changed during the capture')
    if raw['dimensions']['dpr'] != s['dpr']:
        raise fc.EvidenceError(f'devicePixelRatio {raw["dimensions"]["dpr"]} != context {s["dpr"]}')
    if raw['dimensions']['canvas'] != expected_backing(raw['dimensions']):
        raise fc.EvidenceError(f'backing {raw["dimensions"]["canvas"]} != round(css * dpr) {expected_backing(raw["dimensions"])}')
    if raw['dimensions']['viewport'] != s['viewport']:
        raise fc.EvidenceError('viewport differs from the context')
    expected = [ab.FEATURES[s['feature']]['removes']] if s['feature'] else []
    if raw['ablated'] != expected:
        raise fc.EvidenceError(f'hook mismatch: installed {raw["ablated"]} expected {expected}')
    if s['feature'] and not raw['skipped'].get(s['feature']):
        raise fc.EvidenceError('disabled hook was never reached by draw()')
    if len(raw['samples']) != len(raw['frames']):
        raise fc.EvidenceError(f'{len(raw["samples"])} samples for {len(raw["frames"])} active frames')
    if 'stage_profile' in raw or 'trace_profile' in raw or '__cacheProfile' in json.dumps(raw['cfg']):
        raise fc.EvidenceError('timing raw carries instrumentation')


def check_scene(raw):
    d = raw['density']['camera']
    scene = raw['settings']['scene']
    drive = raw.get('cameraDrive')
    if scene in ('stationary', 'moving') and d['travel_px'] != 0:
        raise fc.EvidenceError(f'{scene} scene: physics camera moved: travel {d["travel_px"]}')
    if scene == 'moving':
        if not drive or drive['frames'] < len(raw['frames']) or drive['travel_px'] <= 0:
            raise fc.EvidenceError(f'moving scene: camera drive inactive: {drive and {k: drive[k] for k in ("frames", "travel_px")}}')
    elif drive:
        raise fc.EvidenceError(f'{scene} scene carries a camera drive')


def capture_argv(root, out, context, mode, arm, scene, case, args):
    return [sys.executable, 'tools/y8_cache_profile.py', 'capture', '--root', root, '--output', str(out), '--context', context,
            '--mode', mode, '--arm', arm, '--scene', scene, '--case', case, '--windows', '1',
            '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms)]


def profile_argv(root, out, context, mode, case):
    return [sys.executable, 'tools/y8_cache_profile.py', 'profile', '--root', root, '--output', str(out), '--context', context,
            '--mode', mode, '--case', case]


def run(args):
    out = Path(args.output).resolve()
    root = ch.verified_root(out)
    failures = 0
    if not args.skip_profile:
        for context in args.contexts:
            for mode in args.modes:
                case = f'profile-{context}-{mode}'
                if args.resume and complete_profile(out, case):
                    print('INFO resume: complete profile exists for', case, flush=True)
                    continue
                failures += ab.receipt(out, f'profile/{context}/{mode}', profile_argv(root, out, context, mode, case)) != 0
    if not args.skip_timing:
        for context in args.contexts:
            for mode in args.modes:
                for rep in REPS:
                    for index, (arm, scene) in enumerate(sequence(rep, context)):
                        case = case_name(context, mode, arm, scene, rep, index)
                        if args.resume and ab.complete_case(ab.load_raws(out), case):
                            print('INFO resume: complete raw exists for', case, flush=True)
                            continue
                        argv = capture_argv(root, out, context, mode, arm, scene, case, args)
                        failures += ab.receipt(out, f'timing/{context}/{mode}/{rep}/{index}/{arm}/{scene}', argv) != 0
    print(f'RUN DONE contexts={args.contexts} modes={args.modes} failed={failures}', flush=True)
    return 1 if failures else 0


def load_profiles(out):
    return {f'profile/{p.name}': fc.load(p) for p in sorted((Path(out) / 'profile').glob('*.json'))}


def complete_profile(out, case):
    hits = [r for r in load_profiles(out).values() if r['case'] == case and r.get('result') == 'COMPLETE']
    if len(hits) > 1:
        raise fc.EvidenceError(f'duplicate complete profile {case}')
    return hits[0] if hits else None


# --------------------------------------------------------------- report --

def mean_ms(raw):
    return 1000 / raw['summary']['combined']['average_fps']


def timing_record(raw, path):
    c = raw['summary']['combined']
    d = raw['density']
    return {'path': path, 'case': raw['case'], 'mean_ms': mean_ms(raw), 'p50_ms': c['frame_ms']['p50'], 'p95_ms': c['frame_ms']['p95'],
            'average_fps': c['average_fps'], 'frames': c['frames'], 'active_ms': c['active_ms'], 'deaths': raw['summary']['deaths'],
            'backing': raw['dimensions']['canvas'], 'css': raw['dimensions']['css'], 'dpr': raw['dimensions']['dpr'],
            'backing_equals_round_css_times_dpr': raw['dimensions']['canvas'] == expected_backing(raw['dimensions']),
            'camera_travel_px': d['camera']['travel_px'], 'camera_moving_fraction': d['camera']['moving_fraction'],
            'driven_travel_px': (raw.get('cameraDrive') or {}).get('travel_px', 0), 'driven_frames': (raw.get('cameraDrive') or {}).get('frames', 0),
            'driven_amplitude_px': (raw.get('cameraDrive') or {}).get('amplitude'),
            'elements_mean': d['counts']['elements']['mean'], 'particles_mean': d['counts']['particles']['mean'],
            'skipped': raw.get('skipped', {}), 'frames_sha256': raw['frames_sha256']}


def tier(deltas, noise):
    """Both repetitions beyond the control repeat spread -> REPEATED; one -> CONSISTENT; else WITHIN_NOISE."""
    beyond = [abs(x) > noise for x in deltas]
    if all(beyond) and len({x > 0 for x in deltas}) == 1:
        return 'REPEATED'
    if any(beyond):
        return 'CONSISTENT'
    return 'WITHIN_NOISE'


def build_timings(out):
    raws = ab.load_raws(out)
    complete = {p: r for p, r in raws.items() if r.get('result') == 'COMPLETE'}
    results = {}
    for context in CONTEXTS:
        for mode in MODES:
            key = f'{context}/{mode}'
            cell = {}
            missing = []
            for rep in REPS:
                for index, (arm, scene) in enumerate(sequence(rep, context)):
                    case = case_name(context, mode, arm, scene, rep, index)
                    hit = [(p, r) for p, r in complete.items() if r['case'] == case]
                    if len(hit) != 1:
                        missing.append(case)
                        continue
                    cell[(arm, scene, rep)] = timing_record(hit[0][1], hit[0][0])
            if missing:
                results[key] = {'result': 'INCOMPLETE', 'missing': missing}
                continue
            noise = max(abs(cell[('control', s, 'r1')]['mean_ms'] - cell[('control', s, 'r2')]['mean_ms']) for s in SCENE_ORDER)
            per_scene = {}
            for scene in SCENE_ORDER:
                ctrl = [cell[('control', scene, r)]['mean_ms'] for r in REPS]
                savings = {}
                for arm in ('background-off', 'world-off'):
                    d = [cell[('control', scene, r)]['mean_ms'] - cell[(arm, scene, r)]['mean_ms'] for r in REPS]
                    savings[arm] = {'saving_ms': d, 'median_saving_ms': statistics.median(d), 'tier': tier(d, noise),
                                    'fraction_of_control': statistics.median(d) / statistics.mean(ctrl) if statistics.mean(ctrl) else None}
                per_scene[scene] = {'control_mean_ms': ctrl, 'control_p50_ms': [cell[('control', scene, r)]['p50_ms'] for r in REPS],
                                    'camera_travel_px': [cell[('control', scene, r)]['camera_travel_px'] for r in REPS],
                                    'camera_moving_fraction': [cell[('control', scene, r)]['camera_moving_fraction'] for r in REPS],
                                    'driven_travel_px': [cell[('control', scene, r)]['driven_travel_px'] for r in REPS],
                                    'deaths': [cell[('control', scene, r)]['deaths'] for r in REPS], 'savings': savings}
            if ('control', 'replay', 'r1') in cell:
                rp = [cell[('control', 'replay', r)] for r in REPS]
                per_scene['replay'] = {'control_mean_ms': [x['mean_ms'] for x in rp], 'control_p50_ms': [x['p50_ms'] for x in rp],
                                       'camera_travel_px': [x['camera_travel_px'] for x in rp],
                                       'camera_moving_fraction': [x['camera_moving_fraction'] for x in rp], 'deaths': [x['deaths'] for x in rp],
                                       'replay_minus_stationary_ms': [x['mean_ms'] - cell[('control', 'stationary', r)]['mean_ms'] for x, r in zip(rp, REPS)],
                                       'natural_camera_moved': all(x['camera_travel_px'] > 0 for x in rp), 'savings': {}}
            moving_minus_stationary = [cell[('control', 'moving', r)]['mean_ms'] - cell[('control', 'stationary', r)]['mean_ms'] for r in REPS]
            backings = {tuple(v['backing']) for v in cell.values()}
            results[key] = {'result': 'PAIRED', 'context': context, 'mode': mode, 'noise_max_ms': noise,
                            'backing': sorted(backings), 'backing_consistent': len(backings) == 1,
                            'backing_equals_round_css_times_dpr': all(v['backing_equals_round_css_times_dpr'] for v in cell.values()),
                            'dpr': sorted({v['dpr'] for v in cell.values()}), 'scenes': per_scene,
                            'moving_minus_stationary_ms': moving_minus_stationary,
                            'moving_minus_stationary_tier': tier(moving_minus_stationary, noise),
                            'captures': {f'{a}/{s}/{r}': v for (a, s, r), v in cell.items()}}
    return {'task': TASK, 'generated_utc': utc(), 'statement': 'Uninstrumented timing: requestAnimationFrame intervals of active frames '
            'plus the read-only per-frame sampler; counters and draw() timings live in cache-profile.json from separate sessions. '
            'Frame intervals include the main-thread deferred canvas raster of this software-rendered Chromium; they are not '
            'physical-device figures and nothing here claims 60 FPS.', 'contexts': CONTEXTS, 'scenes': SCENES,
            'arms': {k: {'feature': v['feature'], 'label': v['label']} for k, v in ARMS.items()}, 'protocol': {
                'sequence_r1': {c: sequence('r1', c) for c in CONTEXTS}, 'sequence_r2': {c: sequence('r2', c) for c in CONTEXTS}, 'noise': 'max |control r1 - control r2| over the two scenes',
                'tiers': 'REPEATED: both repetitions beyond noise with one sign; CONSISTENT: one; WITHIN_NOISE: none'},
            'camera_drive': {'amplitude_ratio': CAMERA_DRIVE_AMPLITUDE_RATIO, 'steps_per_half': CAMERA_DRIVE_STEPS_PER_HALF, 'y_ratio': CAMERA_DRIVE_Y_RATIO,
                             'why': 'probe (smoke/probe_camera.log): with input replays the camera never left (0, 0) in bad mode (both replay '
                                    'styles, 30 s active) nor in classic at dpr2 (physics-step cap 2 steps/frame at ~2.5 fps); only classic '
                                    'at dpr1 moves naturally, so the paired moving scene drives the camera at render time'},
            'results': results, 'raw_count': len(raws), 'complete_count': len(complete),
            'failed_attempts': sorted(p for p, r in raws.items() if r.get('result') != 'COMPLETE')}


def summarize_profile(raw):
    steps = profile_steps(raw)
    per_cycle = []
    for c in raw['resize_cycles']:
        cd = {}
        for s in c['steps']:
            for k, v in s['counters_delta'].items():
                cd[k] = cd.get(k, 0) + v
        per_cycle.append({'cycle': c['cycle'], 'counters_delta': cd, 'canvasCount_end': c['steps'][-1]['canvasCount'],
                          'offscreenArea_end': c['steps'][-1]['offscreenArea'],
                          'all_settled': all(s['settled']['settled'] for s in c['steps'])})
    idf = raw['identical_frames']
    cam = raw['camera_shifts']
    tile_ms = [s['counters_delta'].get('tileBuildsFarMs', 0) + s['counters_delta'].get('tileBuildsNearMs', 0) for s in steps]
    tile_n = [s['counters_delta'].get('tileBuildsFar', 0) + s['counters_delta'].get('tileBuildsNear', 0) for s in steps]
    main = raw['after_start']
    offscreen = [c for c in main['canvases'] if c['path'] != 'dom#canvas' and not c['path'].endswith(':hidden')]
    main_area = main['canvas'][0] * main['canvas'][1]
    return {
        'case': raw['case'], 'context': raw['context'], 'mode': raw['mode'], 'result': raw['result'],
        'base': {'viewport': main['viewport'], 'dpr': main['dpr'], 'density': main['density'], 'css': [main['css']['width'], main['css']['height']],
                 'backing': main['canvas'], 'logical': main['logical'], 'tiles': main['tiles'], 'lightmap': main['lightmap'],
                 'glowLevels': main['glowLevels'], 'bars': main['bars'], 'gradientCacheSize': main['gradientCacheSize'],
                 'glowSpriteCacheSize': main['glowSpriteCacheSize'], 'canvasCount': main['canvasCount'],
                 'offscreenArea': main['offscreenArea'], 'offscreen_to_backing_area_ratio': main['offscreenArea'] / main_area,
                 'largest_offscreen': sorted(offscreen, key=lambda c: -c['area'])[:6],
                 'oversized_offscreen': [c for c in offscreen if c['area'] > main_area]},
        'identical_frames': {'frames': idf['frames'], 'counters_delta': idf['counters_delta'],
                             'draw_js_ms': {'mean': statistics.mean(idf['draw_js_ms']), 'p50': statistics.median(idf['draw_js_ms']),
                                            'max': max(idf['draw_js_ms'])},
                             'tile_blits_per_frame': idf['counters_delta'].get('tileBlits', 0) / idf['frames'],
                             'tile_blits_clipped_away_per_frame': idf['counters_delta'].get('tileBlitsClippedAway', 0) / idf['frames'],
                             'tile_blit_device_px_per_frame': idf['counters_delta'].get('tileBlitDevicePx', 0) / idf['frames'],
                             'tile_blit_visible_px_per_frame': idf['counters_delta'].get('tileBlitVisiblePx', 0) / idf['frames'],
                             'allocation_origins': alloc_origins(idf['counters_delta']),
                             'cull_rebuilds_per_frame': idf['counters_delta'].get('cullRectRebuilds', 0) / idf['frames']},
        'camera_shifts': {'steps': cam['steps'], 'dx': cam['dx'], 'dy': cam['dy'], 'counters_delta': cam['counters_delta'],
                          'draw_js_ms_mean': statistics.mean(s['draw_ms'] for s in cam['per_step']),
                          'tile_blits_per_frame': cam['counters_delta'].get('tileBlits', 0) / cam['steps'],
                          'tile_blits_clipped_away_per_frame': cam['counters_delta'].get('tileBlitsClippedAway', 0) / cam['steps'],
                          'tile_blit_device_px_per_frame': cam['counters_delta'].get('tileBlitDevicePx', 0) / cam['steps'],
                          'tile_blit_visible_px_per_frame': cam['counters_delta'].get('tileBlitVisiblePx', 0) / cam['steps'],
                          'allocation_origins': alloc_origins(cam['counters_delta']),
                          'tile_blits_per_frame_range': [min(s['tileBlits'] for s in cam['per_step']), max(s['tileBlits'] for s in cam['per_step'])]},
        'resize': {'cycles': len(raw['resize_cycles']), 'steps': len(steps), 'settled_steps': sum(1 for s in steps if s['settled']['settled']),
                   'steps_with_viewport_and_backing_change': sum(1 for s in steps if s['dimensions_changed']['viewport'] and s['dimensions_changed']['backing']),
                   'debounce_ms': raw['settings']['debounce_ms_from_source'], 'settle_extra_ms': raw['settings']['settle_extra_ms'],
                   'wall_wait_ms': {'min': min(s['wall_wait_ms'] for s in steps), 'max': max(s['wall_wait_ms'] for s in steps)},
                   'per_cycle': per_cycle, 'canvasCount_per_cycle_end': [c['canvasCount_end'] for c in per_cycle],
                   'inventory_stable_across_cycles': len({c['canvasCount_end'] for c in per_cycle}) == 1,
                   'tile_builds_per_step': tile_n, 'tile_build_js_ms_per_step': tile_ms,
                   'tile_key_changes_per_step': [int(bool(s['dimensions_changed']['tiles'])) for s in steps],
                   'tile_key_changes_after_first_cycle': sum(1 for s in steps[len(RESIZE_STEPS):] if s['dimensions_changed']['tiles']),
                   'tile_builds_after_first_cycle': sum(tile_n[len(RESIZE_STEPS):]),
                   'steps_with_backing_change_but_same_tile_key': sum(1 for s in steps if s['dimensions_changed']['backing'] and not s['dimensions_changed']['tiles']),
                   'tile_build_js_ms_per_tile': (sum(tile_ms) / sum(tile_n)) if sum(tile_n) else None,
                   'canvas_allocations_per_step': [s['counters_delta'].get('canvasAllocations', 0) for s in steps],
                   'allocation_origins_per_first_cycle': [alloc_origins(s['counters_delta']) for s in steps[:len(RESIZE_STEPS)]],
                   'allocation_origins_total': alloc_origins(merge_counters(*[s['counters_delta'] for s in steps])),
                   'gradient_builds_per_step': [s['counters_delta'].get('gradientBuilds', 0) for s in steps],
                   'first_draw_js_ms_per_step': [s['first_draw_js_ms'] for s in steps],
                   'backings_visited': sorted({tuple(s['after']['canvas']) for s in steps}),
                   'steps_summary': [{'requested': s['requested_viewport'], 'backing': s['after']['canvas'], 'logical': s['after']['logical'],
                                      'bars': s['after']['bars'], 'settled': s['settled']['settled'], 'wall_wait_ms': s['wall_wait_ms'],
                                      'counters_delta': s['counters_delta']} for s in steps[:len(RESIZE_STEPS)]]},
        'duplicate_resize': {'handler_seen': raw['duplicate_resize']['handler']['handler_seen'],
                             'counters_delta': raw['duplicate_resize']['counters_delta'],
                             'backing_changed': raw['duplicate_resize']['dimensions_changed']['backing']},
        'letterbox_identical_frames': {'frames': raw['letterbox_identical_frames']['frames'], 'bars': raw['letterbox_identical_frames']['bars'],
                                       'counters_delta': raw['letterbox_identical_frames']['counters_delta'],
                                       'bar_paints': raw['letterbox_identical_frames']['counters_delta'].get('barPaints', 0),
                                       'bar_check_js_ms_total': raw['letterbox_identical_frames']['counters_delta'].get('barChecksMs', 0),
                                       'draw_js_ms_mean': statistics.mean(raw['letterbox_identical_frames']['draw_js_ms'])},
        'dpr_only': {k: raw['dpr_only'][k] for k in ('from_dpr', 'to_dpr', 'configure_seen', 'via_resize_handler', 'counters_delta', 'backing_changed')} | {
            'backing_before': raw['dpr_only']['before']['canvas'], 'backing_after': raw['dpr_only']['after']['canvas'],
            'tiles_before': raw['dpr_only']['before']['tiles'], 'tiles_after': raw['dpr_only']['after']['tiles'],
            'settled': raw['dpr_only']['settled']['settled'], 'checks': raw['dpr_only']['settled']['checks']},
        'final': {'counters': raw['final']['counters'], 'canvasCount': raw['final']['canvasCount'], 'gradientCacheSize': raw['final']['gradientCacheSize'],
                  'layerCache_entries': len(raw['final']['tiles'])},
        'cache_bounds_check': cache_bounds_check(raw),
    }


def alloc_origins(counters):
    return {k[len('alloc:'):]: v for k, v in counters.items() if k.startswith('alloc:') and v}


def is_reconstruction_origin(origin):
    return any(m in origin for m in RECONSTRUCTION_ORIGIN_MARKERS)


def is_known_lazy_origin(origin):
    return any(m in origin for m in KNOWN_LAZY_ORIGIN_MARKERS)


def merge_counters(*deltas):
    out = {}
    for d in deltas:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def cache_bounds_check(raw):
    steps = profile_steps(raw)
    final = raw['final']
    steady = merge_counters(raw['identical_frames']['counters_delta'], raw['camera_shifts']['counters_delta'])
    steady_alloc = alloc_origins(steady)
    recon = {o: n for o, n in steady_alloc.items() if is_reconstruction_origin(o)}
    lazy = {o: n for o, n in steady_alloc.items() if not is_reconstruction_origin(o)}
    resize_alloc = merge_counters(*[{k: v for k, v in s['counters_delta'].items() if k.startswith('alloc:')} for s in steps])
    resize_origins = alloc_origins(resize_alloc)
    unknown = sorted(o for o in set(steady_alloc) | set(resize_origins) if not (is_reconstruction_origin(o) or is_known_lazy_origin(o)))
    tiles_per_step = [s['counters_delta'].get('tileBuildsFar', 0) + s['counters_delta'].get('tileBuildsNear', 0) for s in steps]
    keys = ('canvasAllocations', 'tileBuildsFar', 'tileBuildsNear', 'gradientBuilds', 'backingChanges')
    checks = {
        'layerCache_entries_le_bound': len(final['tiles']) <= CACHE_BOUNDS['layerCache_entries'],
        'gradientCache_entries_le_bound': final['gradientCacheSize'] <= CACHE_BOUNDS['gradientCache_entries'],
        'glow_levels_per_renderer_eq_bound': all(len(v) == CACHE_BOUNDS['glow_levels_per_renderer'] for k, v in final['glowLevels'].items() if k != 'bloom'),
        'steady_state_tile_builds_zero': steady.get('tileBuildsFar', 0) + steady.get('tileBuildsNear', 0) == CACHE_BOUNDS['steady_state_tile_builds'],
        'steady_state_gradient_builds_zero': steady.get('gradientBuilds', 0) == CACHE_BOUNDS['steady_state_gradient_builds'],
        'steady_state_main_backing_changes_zero': steady.get('mainBackingChanges', 0) == CACHE_BOUNDS['steady_state_main_backing_changes'],
        'steady_state_level_or_lightmap_changes_zero': steady.get('glowLevelResizeChanges', 0) + steady.get('lightmapResizeChanges', 0)
                                                       == CACHE_BOUNDS['steady_state_level_or_lightmap_changes'],
        'steady_state_reconstruction_allocations_zero': sum(recon.values()) == CACHE_BOUNDS['steady_state_reconstruction_allocations'],
        'steady_state_backing_changes_only_lazy_allocations': steady.get('backingChanges', 0) == 2 * sum(lazy.values()),
        'tile_builds_per_settled_resize_le_bound': all(n <= CACHE_BOUNDS['tile_builds_per_settled_resize'] for n in tiles_per_step),
        'tile_builds_two_iff_tile_key_changed': all(n == (2 if s['dimensions_changed']['tiles'] else 0) for n, s in zip(tiles_per_step, steps)),
        'allocation_origins_all_known': not unknown,
        'duplicate_resize_zero_allocations_and_builds': all(raw['duplicate_resize']['counters_delta'].get(k, 0) == 0 for k in keys),
        'canvas_inventory_stable_across_cycles': len({c['steps'][-1]['canvasCount'] for c in raw['resize_cycles']}) == 1,
    }
    return {'bounds': CACHE_BOUNDS, 'steady_state_counters': {k: steady.get(k, 0) for k in keys + ('mainBackingChanges', 'glowLevelResizeChanges', 'lightmapResizeChanges')},
            'steady_state_allocation_origins': {'reconstruction': recon, 'lazy': lazy},
            'resize_allocation_origins': resize_origins, 'unknown_origins': unknown,
            'checks': checks, 'all_pass': all(checks.values())}


def build_cache_profile(out):
    profiles = load_profiles(out)
    complete = {p: r for p, r in profiles.items() if r.get('result') == 'COMPLETE'}
    sessions = {}
    for context in CONTEXTS:
        for mode in MODES:
            case = f'profile-{context}-{mode}'
            hit = [(p, r) for p, r in complete.items() if r['case'] == case]
            sessions[f'{context}/{mode}'] = dict(summarize_profile(hit[0][1]), path=hit[0][0]) if len(hit) == 1 else {'result': 'MISSING', 'case': case}
    return {'task': TASK, 'generated_utc': utc(),
            'statement': 'INSTRUMENTED DIAGNOSTIC PASS, separate from the timing captures: counters and draw() JS-submission ms with '
                         'requestAnimationFrame cancelled. draw() ms exclude the deferred canvas raster/GPU work and are never reported '
                         'as frame cost. Resize cycles go through the real window resize event and the runtime debounce read from '
                         'index.html; every step waits for the handler plus settle_extra_ms and asserts the settled sizes against the '
                         'runtime formulas (logical width, round(css * dpr) backing, lightmap, tile keys, glow levels, bars).',
            'contexts': CONTEXTS, 'resize_steps': list(RESIZE_STEPS), 'cache_bounds': CACHE_BOUNDS, 'sessions': sessions,
            'profile_files': sorted(profiles), 'failed_attempts': sorted(p for p, r in profiles.items() if r.get('result') != 'COMPLETE')}


def decide(timings, cache):
    sessions = {k: v for k, v in cache['sessions'].items() if v.get('result') == 'COMPLETE'}
    paired = {k: v for k, v in timings['results'].items() if v.get('result') == 'PAIRED'}
    steady_keys = ('steady_state_reconstruction_allocations_zero', 'steady_state_tile_builds_zero', 'steady_state_gradient_builds_zero',
                   'steady_state_main_backing_changes_zero', 'steady_state_level_or_lightmap_changes_zero')
    steady_ok = all(all(v['cache_bounds_check']['checks'][k] for k in steady_keys) for v in sessions.values()) if sessions else None
    lazy = {k: v['cache_bounds_check']['steady_state_allocation_origins']['lazy'] for k, v in sessions.items()}
    unknown = {k: v['cache_bounds_check']['unknown_origins'] for k, v in sessions.items() if v['cache_bounds_check']['unknown_origins']}
    clipped = {k: {'identical_clipped_away_per_frame': v['identical_frames']['tile_blits_clipped_away_per_frame'],
                   'identical_visible_px_per_frame': v['identical_frames']['tile_blit_visible_px_per_frame'],
                   'identical_nominal_px_per_frame': v['identical_frames']['tile_blit_device_px_per_frame']} for k, v in sessions.items()}
    dpr_only = {k: {'backing_changed': v['dpr_only']['backing_changed'], 'settled': v['dpr_only']['settled'], 'via_resize_handler': v['dpr_only']['via_resize_handler'],
                    'tiles_rebuilt': v['dpr_only']['counters_delta'].get('tileBuildsFar', 0) + v['dpr_only']['counters_delta'].get('tileBuildsNear', 0),
                    'glow_level_changes': v['dpr_only']['counters_delta'].get('glowLevelResizeChanges', 0)} for k, v in sessions.items()}
    dup_ok = all(v['cache_bounds_check']['checks']['duplicate_resize_zero_allocations_and_builds'] for v in sessions.values()) if sessions else None
    oversized = {k: v['base']['oversized_offscreen'] for k, v in sessions.items()}
    ratios = {k: v['base']['offscreen_to_backing_area_ratio'] for k, v in sessions.items()}
    resize_rebuild = {k: {'tile_builds_per_step': sorted(set(v['resize']['tile_builds_per_step'])),
                          'allocations_per_step': sorted(set(v['resize']['canvas_allocations_per_step'])),
                          'tile_build_js_ms_per_tile': v['resize']['tile_build_js_ms_per_tile'],
                          'backings_visited': v['resize']['backings_visited'],
                          'inventory_stable': v['resize']['inventory_stable_across_cycles']} for k, v in sessions.items()}
    revisit_rebuilds = any(v['resize']['tile_key_changes_after_first_cycle'] > 0 and
                           v['resize']['tile_builds_after_first_cycle'] == 2 * v['resize']['tile_key_changes_after_first_cycle']
                           for v in sessions.values()) if sessions else None
    reused = {k: v['resize']['steps_with_backing_change_but_same_tile_key'] for k, v in sessions.items()}
    bars = {k: {'frames': v['letterbox_identical_frames']['frames'], 'bar_paints': v['letterbox_identical_frames']['bar_paints'],
                'bar_check_js_ms_total': v['letterbox_identical_frames']['bar_check_js_ms_total']} for k, v in sessions.items()}
    bar_repaints = any(b['bar_paints'] > 0 for b in bars.values()) if bars else None
    camera = {k: {'identical_tile_blits_per_frame': v['identical_frames']['tile_blits_per_frame'],
                  'shifted_tile_blits_per_frame': v['camera_shifts']['tile_blits_per_frame'],
                  'identical_device_px_per_frame': v['identical_frames']['tile_blit_device_px_per_frame'],
                  'shifted_device_px_per_frame': v['camera_shifts']['tile_blit_device_px_per_frame'],
                  'identical_draw_js_ms_mean': v['identical_frames']['draw_js_ms']['mean'],
                  'shifted_draw_js_ms_mean': v['camera_shifts']['draw_js_ms_mean']} for k, v in sessions.items()}
    background = {k: {s: {'saving_ms': v['scenes'][s]['savings']['background-off']['saving_ms'],
                          'tier': v['scenes'][s]['savings']['background-off']['tier'],
                          'fraction_of_control': v['scenes'][s]['savings']['background-off']['fraction_of_control']} for s in SCENE_ORDER}
                  | {'noise_max_ms': v['noise_max_ms']} for k, v in paired.items()}
    world = {k: {s: {'saving_ms': v['scenes'][s]['savings']['world-off']['saving_ms'], 'tier': v['scenes'][s]['savings']['world-off']['tier']}
                 for s in SCENE_ORDER} for k, v in paired.items()}
    scene_delta = {k: {'moving_minus_stationary_ms': v['moving_minus_stationary_ms'], 'tier': v['moving_minus_stationary_tier'],
                       'stationary_travel_px': v['scenes']['stationary']['camera_travel_px'], 'moving_travel_px': v['scenes']['moving']['camera_travel_px']}
                   for k, v in paired.items()}
    findings = []
    if steady_ok is True:
        findings.append('RULED_OUT steady-state reconstruction: zero tile builds, gradient builds, main-backing changes, glow-level/lightmap '
                        f'changes and reconstruction allocations over {IDENTICAL_FRAMES} identical frames + {CAMERA_STEPS} camera shifts in every session')
    elif steady_ok is False:
        findings.append('FOUND steady-state reconstruction: see cache_bounds_check.steady_state_counters')
    if any(lazy.values()):
        findings.append('BOUNDED lazy sprite caching during camera shifts (first-use fills, not reconstruction): ' + json.dumps(lazy))
    if unknown:
        findings.append('FOUND canvas allocations from unclassified origins: ' + json.dumps(unknown))
    if sessions and any(c['identical_clipped_away_per_frame'] > 0 for c in clipped.values()):
        findings.append('RULED_OUT as raster cost, noted as submission: with the camera at shift 0 drawLayerTile submits a second copy per '
                        'tile that the device-pixel rounding places at x = tile width, clipped to < 1 device px: '
                        + json.dumps({k: round(c['identical_clipped_away_per_frame'], 2) for k, c in clipped.items()}) + ' extra drawImage calls per frame')
    if sessions and not all(d['backing_changed'] and d['settled'] for d in dpr_only.values()):
        findings.append('FOUND DPR-only change did not settle the backing in every session: ' + json.dumps(dpr_only))
    if dup_ok is True:
        findings.append('RULED_OUT duplicate-resize reconstruction: a resize event at the settled size allocates/rebuilds nothing')
    elif dup_ok is False:
        findings.append('FOUND duplicate-resize reconstruction')
    if sessions and not any(oversized.values()):
        findings.append('RULED_OUT oversized surfaces: no offscreen canvas exceeds the main backing area; offscreen/backing area ratios '
                        + json.dumps({k: round(r, 3) for k, r in ratios.items()}))
    elif sessions:
        findings.append('FOUND oversized surfaces: ' + json.dumps(oversized))
    if revisit_rebuilds is True:
        findings.append('BOUNDED reconstruction on resize: both cave tiles are rebuilt exactly when their key (logical width, height, pixel '
                        'scale) changes, including a return to a size seen in the previous cycle (single-entry layerCache per tile name); '
                        'cost per tile = tile_build_js_ms_per_tile (JS submission, ~1 ms). Never triggered without a real key change; '
                        'backing changes that keep the key (pixel scale capped at maxPixelScale, dpr2) reuse the tiles: '
                        + json.dumps(reused) + ' such steps per session')
    if bar_repaints is True:
        findings.append('FOUND bounded periodic repaint: letterbox bar canvases are repainted every WINDOW_BARS_EVERY_FRAMES frames '
                        'with an unchanged camera and key (identical content); absent at the 1280x720 contexts (no bars)')
    elif bar_repaints is False:
        findings.append('RULED_OUT bar repaints on identical frames')
    verdict = 'INCOMPLETE'
    if sessions and paired and len(paired) == len(timings['results']) and len(sessions) == len(cache['sessions']):
        found = [f for f in findings if f.startswith('FOUND')]
        verdict = 'NO_UNNECESSARY_RECONSTRUCTION' if not found else 'BOUNDED_FINDINGS'
    return {'task': TASK, 'generated_utc': utc(), 'verdict': verdict,
            'verdict_meaning': {'NO_UNNECESSARY_RECONSTRUCTION': 'steady state allocates nothing, duplicate resizes rebuild nothing, no offscreen '
                                'surface exceeds the backing; resize rebuilds are bounded and tied to real size changes',
                                'BOUNDED_FINDINGS': 'at least one FOUND entry; each is quantified in findings and bounded in scope',
                                'INCOMPLETE': 'a profile session or timing cell is missing'}[verdict],
            'findings': findings,
            'reconstruction': {'steady_state_zero': steady_ok, 'duplicate_resize_zero': dup_ok, 'resize_rebuilds_on_revisit': revisit_rebuilds,
                               'steps_with_backing_change_but_same_tile_key': reused,
                               'per_session': resize_rebuild},
            'surfaces': {'oversized_offscreen_per_session': oversized, 'offscreen_to_backing_area_ratio': ratios},
            'bars': bars, 'camera_shift_vs_identical': camera, 'tile_blit_clipping': clipped, 'dpr_only': dpr_only,
            'moving_scene_definition': SCENES['moving'],
            'background_cost': background, 'world_cost': world, 'scene_delta': scene_delta,
            'attribution': {'js_submission_not_raster': 'draw() and tile-build ms in cache-profile.json are JS submission only; the deferred '
                            'canvas raster (LayerTreeHost::DoUpdateLayers, TASK-276) and any GPU work are outside those spans and are not '
                            'reported as frame cost. Frame-interval savings in timings.json are the only whole-frame figures.',
                            'gpu_attribution': 'UNSUPPORTED: SwiftShader software raster, no GPU fence'},
            'not_claimed': ['60 FPS', 'release readiness', 'physical-device performance'],
            'diagnostic_only': 'background-off / world-off hooks and harness camera shifts are page-only diagnostics; the runtime is unchanged'}


def build_manifest(out, timings, cache):
    identity = fc.load(out / 'identity.json')
    commands = []
    cj = out / 'commands.jsonl'
    if cj.exists():
        commands = [json.loads(line) for line in cj.read_text().splitlines() if line.strip()]
    raws = ab.load_raws(out)
    profiles = load_profiles(out)
    evidence = sorted(list(raws) + list(profiles) + ['identity.json', 'commands.jsonl'])
    evidence = [p for p in evidence if (out / p).exists()]
    module_variants = sorted(p.name for p in (out / MODULE_AT_CAPTURE).glob('*.py'))
    envs = [r['environment'] for r in list(raws.values()) + list(profiles.values()) if r.get('environment')]
    starts = [r['started_utc'] for r in list(raws.values()) + list(profiles.values())] + [c['utc_start'] for c in commands] + [identity['utc_start']]
    ends = [r.get('ended_utc') for r in list(raws.values()) + list(profiles.values()) if r.get('ended_utc')] + [c['utc_end'] for c in commands]
    backing_by_case = {r['case']: r['dimensions']['canvas'] for r in raws.values()}
    return {'task': TASK, 'generated_utc': utc(), 'utc_start': min(starts), 'utc_end': max(ends),
            'commands': [{k: c[k] for k in ('label', 'argv', 'utc_start', 'utc_end', 'exit_code')} for c in commands],
            'environment': envs[0] if envs else None, 'environment_ceiling': identity['environment_ceiling'],
            'source_revision': identity['identity']['current_commit'], 'source_dirty_runtime': identity['identity']['current_dirty_runtime'],
            'source_revision_at_report': fc.git('rev-parse', 'HEAD'), 'current_tar_sha256': identity['identity']['current_tar_sha256'],
            'candidate_hashes': {'current_files_sha256': identity['identity']['current_files_sha256']},
            'harness_sha256': identity['harness_sha256'], 'ablation_sha256': identity['ablation_sha256'], 'chill_sha256': identity['chill_sha256'],
            'support_sha256': identity['support_sha256'], 'module_sha256_at_report': fc.sha_file(MODULE),
            'module_sha256_at_capture': sorted({r['module_sha256'] for r in list(raws.values()) + list(profiles.values())}),
            'module_at_capture': module_variants,
            'fixed': {'contexts': CONTEXTS, 'viewport_css': [1280, 720], 'dprs': [1, 2], 'backing_size_by_case': backing_by_case,
                      'resize_steps': list(RESIZE_STEPS), 'resize_cycles': RESIZE_CYCLES, 'debounce_ms_from_source': identity['debounce_ms_from_source'],
                      'settle_extra_ms': settle_extra_ms(identity['debounce_ms_from_source']), 'modes': list(MODES),
                      'seeds': {m: MODE_SETUP[m]['seed'] for m in MODES}, 'replay_styles': {m: MODE_SETUP[m]['replay_style'] for m in MODES},
                      'scenes': SCENES, 'camera_drive': {'amplitude_ratio': CAMERA_DRIVE_AMPLITUDE_RATIO, 'steps_per_half': CAMERA_DRIVE_STEPS_PER_HALF,
                                                         'y_ratio': CAMERA_DRIVE_Y_RATIO},
                      'input': 'mouse (dispatched mousedown/mouseup on the active clock; replay scene only; stationary/moving = none)',
                      'state': 'fresh page per capture, seeded Math.random, menu -> startGame(mode); profile sessions cancel rAF after 3 frames',
                      'cpu_throttle': 1, 'warmup_ms': None, 'window_ms': None},
            'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter',
            'evidence_paths': evidence, 'sha256': {p: fc.sha_file(out / p) for p in evidence},
            'failed_attempts_preserved': [p for p in evidence if (p in raws and raws[p].get('result') != 'COMPLETE') or
                                          (p in profiles and profiles[p].get('result') != 'COMPLETE')],
            'exit_codes': sorted({c['exit_code'] for c in commands}),
            'note': 'A successful evidence audit is separate from the performance verdict (decision.json). Failed attempts are preserved, '
                    'never rewritten. Historical receipts are never fabricated.'}


def report(args):
    out = Path(args.output).resolve()
    timings = build_timings(out)
    cache = build_cache_profile(out)
    decision = decide(timings, cache)
    fc.dump(out / 'timings.json', timings)
    fc.dump(out / 'cache-profile.json', cache)
    fc.dump(out / 'decision.json', decision)
    manifest = build_manifest(out, timings, cache)
    # warmup/window come from the paired raws
    raws = [r for r in ab.load_raws(out).values() if r.get('result') == 'COMPLETE']
    manifest['fixed']['warmup_ms'] = sorted({r['settings']['warmup_ms'] for r in raws})
    manifest['fixed']['window_ms'] = sorted({r['settings']['window_ms'] for r in raws})
    for name in ('timings.json', 'cache-profile.json', 'decision.json'):
        manifest['sha256'][name] = fc.sha_file(out / name)
        manifest['evidence_paths'].append(name)
    fc.dump(out / 'manifest.json', manifest)
    print('REPORT verdict', decision['verdict'])
    for f in decision['findings']:
        print('  ', f[:200])
    for k, v in timings['results'].items():
        if v['result'] != 'PAIRED':
            print('  ', k, v['result'], v.get('missing'))
            continue
        print('  %s noise=%.2f backing=%s' % (k, v['noise_max_ms'], v['backing']))
        for s in SCENE_ORDER:
            sc = v['scenes'][s]
            print('     %-10s control %.1f/%.1f ms travel=%s bg-off %s %s world-off %s %s' % (
                s, sc['control_mean_ms'][0], sc['control_mean_ms'][1], [round(x) for x in sc['camera_travel_px']],
                [round(x, 1) for x in sc['savings']['background-off']['saving_ms']], sc['savings']['background-off']['tier'],
                [round(x, 1) for x in sc['savings']['world-off']['saving_ms']], sc['savings']['world-off']['tier']))
        print('     moving-stationary %s %s' % ([round(x, 1) for x in v['moving_minus_stationary_ms']], v['moving_minus_stationary_tier']))
    for k, v in cache['sessions'].items():
        if v.get('result') != 'COMPLETE':
            print('  ', k, v)
            continue
        print('  %s backing=%s tiles=%s identical_delta=%s resize settled %d/%d tile_ms/tile=%s bars=%s' % (
            k, v['base']['backing'], {n: t['size'] for n, t in v['base']['tiles'].items()}, v['identical_frames']['counters_delta'],
            v['resize']['settled_steps'], v['resize']['steps'], v['resize']['tile_build_js_ms_per_tile'],
            v['letterbox_identical_frames']['bar_paints']))
    return 0 if decision['verdict'] != 'INCOMPLETE' else 1


# ---------------------------------------------------------------- audit --

def audit(args):
    out = Path(args.output).resolve()
    failures = []
    passes = []

    def check(cond, msg):
        (passes if cond else failures).append(msg)
        print(('PASS ' if cond else 'FAIL ') + msg, flush=True)

    identity = fc.load(out / 'identity.json')
    root = Path(identity['identity']['trees']['current'])
    check(fc.tree_hashes(root) == identity['identity']['current_files_sha256'], 'served tree unchanged since prepare')
    check(identity['debounce_ms_from_source'] == debounce_ms_from_source(), 'debounce from source matches index.html (%d ms)' % identity['debounce_ms_from_source'])
    variants = {fc.sha_file(p) for p in (out / MODULE_AT_CAPTURE).glob('*.py')}
    raws = ab.load_raws(out)
    profiles = load_profiles(out)
    for name, r in list(raws.items()) + list(profiles.items()):
        check(r['module_sha256'] in variants, f'{name}: module variant preserved ({r["module_sha256"][:8]})')
        check(r['tree']['files_sha256'] == identity['identity']['current_files_sha256'], f'{name}: captured tree == identity tree')
    # timing raws: recompute everything, no instrumentation, backing checks
    complete = 0
    for name, r in raws.items():
        if r.get('result') != 'COMPLETE':
            check(True, f'{name}: preserved failed attempt ({r.get("result")})')
            continue
        complete += 1
        check(fc.frames_sha256(r['frames']) == r['frames_sha256'], f'{name}: frames seal')
        check(fc.summarize(r) == r['summary'], f'{name}: summary recomputed from frames')
        check(ch.window_density(r) == r['density'], f'{name}: density recomputed from samples')
        check(r['settings']['instrumentation'].startswith('timing arm'), f'{name}: timing-only instrumentation statement')
        check('stage_profile' not in r and 'trace_profile' not in r and 'counters' not in r, f'{name}: no counters/trace in timing raw')
        check(r['dimensions']['canvas'] == expected_backing(r['dimensions']), f'{name}: backing == round(css * dpr) {r["dimensions"]["canvas"]}')
        check(len({tuple(f['canvas']) for f in r['frames']}) == 1, f'{name}: backing constant across frames')
        check(r['dimensions']['dpr'] == r['settings']['dpr'] == CONTEXTS[r['settings']['context']]['dpr'], f'{name}: dpr matches context')
        try:
            check_scene(r)
            check(True, f'{name}: scene check (travel {r["density"]["camera"]["travel_px"]:.0f}, moving {r["density"]["camera"]["moving_fraction"]})')
        except fc.EvidenceError as e:
            check(False, f'{name}: {e}')
    # profile raws: dimensions changed, waits beyond debounce, settled, counters vs bounds
    for name, r in profiles.items():
        if r.get('result') != 'COMPLETE':
            check(True, f'{name}: preserved failed attempt ({r.get("result")})')
            continue
        steps = profile_steps(r)
        check(len(steps) == RESIZE_CYCLES * len(RESIZE_STEPS), f'{name}: {len(steps)} resize steps')
        check(all(s['dimensions_changed']['viewport'] and s['dimensions_changed']['backing'] for s in steps), f'{name}: viewport and backing changed on every resize step')
        check(all(s['wall_wait_ms'] > s['debounce_ms'] for s in steps), f'{name}: every wait beyond the {steps[0]["debounce_ms"]} ms debounce (min %.0f ms)' % min(s['wall_wait_ms'] for s in steps))
        check(all(s['handler']['handler_seen'] for s in steps), f'{name}: onViewportResize observed on every step')
        resettled = [settled_assertions(_snapshot_from_step(s), r['constants'])['settled'] for s in steps]
        check(all(resettled) and all(s['settled']['settled'] for s in steps), f'{name}: settled dimensions re-derived for all steps')
        bounds = cache_bounds_check(r)
        for k, v in bounds['checks'].items():
            check(v, f'{name}: {k}')
        check(r['raf_cancelled'], f'{name}: rAF cancelled (harness-driven draw)')
        check(not [k for k in r['final']['counters'] if k.endswith(':ABSENT')], f'{name}: all hooks present')
        check(r['settings']['instrumentation'].startswith('INSTRUMENTED DIAGNOSTIC PASS'), f'{name}: labelled instrumented')
    # report files re-derived
    for fname, builder in (('timings.json', lambda: build_timings(out)), ('cache-profile.json', lambda: build_cache_profile(out))):
        if (out / fname).exists():
            stored = fc.load(out / fname)
            rebuilt = json.loads(json.dumps(builder()))  # JSON round trip: tuples become lists, as in the stored file
            rebuilt['generated_utc'] = stored['generated_utc']
            check(rebuilt == stored, f'{fname} re-derived from raw files')
    if (out / 'decision.json').exists():
        stored = fc.load(out / 'decision.json')
        rebuilt = json.loads(json.dumps(decide(fc.load(out / 'timings.json'), fc.load(out / 'cache-profile.json'))))
        rebuilt['generated_utc'] = stored['generated_utc']
        check(rebuilt == stored, 'decision.json re-derived; verdict ' + stored['verdict'])
    if (out / 'manifest.json').exists():
        m = fc.load(out / 'manifest.json')
        bad = [p for p in m['evidence_paths'] if p != 'manifest.json' and fc.sha_file(out / p) != m['sha256'][p]]
        check(not bad, f'manifest seal: {len(m["sha256"])} files, mismatches {bad}')
        check(m['source_revision'] == identity['identity']['current_commit'], 'manifest source revision == identity')
    # runtime untouched
    marker_hits = [n for n in fc.runtime_files(ROOT) if '__cacheProfile' in (ROOT / n).read_text(errors='ignore') or '__featureCost' in (ROOT / n).read_text(errors='ignore')]
    check(not marker_hits, f'no instrumentation marker in {len(fc.runtime_files(ROOT))} runtime files')
    print(f'AUDIT {"PASS" if not failures else "FAIL"} passes={len(passes)} failures={len(failures)} timing_complete={complete} profiles={len(profiles)}', flush=True)
    return 1 if failures else 0


def _snapshot_from_step(step):
    a = step['after']
    return {'resizeTimerNull': step['settled']['checks']['resize_timer_idle'], 'logical': a['logical'],
            'computedLogicalWidth': a['logical'][0] if step['settled']['checks']['logical_width'] else None,
            'css': {'width': a['css'][0], 'height': a['css'][1]}, 'canvas': a['canvas'], 'lightmap': a['lightmap'], 'tiles': a['tiles'],
            'glowLevels': a['glowLevels'], 'bars': a['bars'], 'viewport': a['viewport'], 'density': a['density']}


# ----------------------------------------------------------------- main --

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='action', required=True)

    def common(sp):
        sp.add_argument('--output', default=f'artifacts/{TASK}')
        sp.add_argument('--root', default=str(ROOT))
        sp.add_argument('--cpu-throttle', type=float, default=1)

    s = sub.add_parser('prepare'); s.add_argument('--output', default=f'artifacts/{TASK}')
    s = sub.add_parser('profile'); common(s)
    s.add_argument('--context', choices=sorted(CONTEXTS), required=True); s.add_argument('--mode', choices=MODES, required=True)
    s.add_argument('--case', required=True); s.add_argument('--identical-frames', type=int, default=IDENTICAL_FRAMES)
    s.add_argument('--camera-steps', type=int, default=CAMERA_STEPS); s.add_argument('--resize-cycles', type=int, default=RESIZE_CYCLES)
    s.add_argument('--letterbox-frames', type=int, default=LETTERBOX_FRAMES)
    s = sub.add_parser('capture'); common(s)
    s.add_argument('--context', choices=sorted(CONTEXTS), required=True); s.add_argument('--mode', choices=MODES, required=True)
    s.add_argument('--arm', choices=sorted(ARMS), required=True); s.add_argument('--scene', choices=sorted(SCENES), required=True)
    s.add_argument('--case', required=True); s.add_argument('--warmup-ms', type=int, default=5000)
    s.add_argument('--window-ms', type=int, default=10000); s.add_argument('--windows', type=int, default=1)
    s.add_argument('--timeout-ms', type=int, default=180000)
    s = sub.add_parser('run'); s.add_argument('--output', default=f'artifacts/{TASK}')
    s.add_argument('--contexts', nargs='+', default=list(CONTEXTS)); s.add_argument('--modes', nargs='+', default=list(MODES))
    s.add_argument('--warmup-ms', type=int, default=5000); s.add_argument('--window-ms', type=int, default=10000)
    s.add_argument('--resume', action='store_true'); s.add_argument('--skip-profile', action='store_true'); s.add_argument('--skip-timing', action='store_true')
    s = sub.add_parser('report'); s.add_argument('--output', default=f'artifacts/{TASK}')
    s = sub.add_parser('audit'); s.add_argument('--output', default=f'artifacts/{TASK}')
    args = p.parse_args(argv)
    return {'prepare': prepare, 'profile': profile, 'capture': capture, 'run': run, 'report': report, 'audit': audit}[args.action](args)


if __name__ == '__main__':
    sys.exit(main())
