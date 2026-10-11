#!/usr/bin/env python3
"""TASK-281: test a redundant-update reduction at the next independently measured bottleneck (the cave
background), separate from the mechanisms of TASK-279 (far-stack reuse) and TASK-280 (glow region clip).

Evidence base (sealed): TASK-273 decision.json ranks cave-background second in both modes (median
saving when switched off 15.9 ms Main / 24.8 ms Chill, REPEATED_SAVING in both); TASK-274 confirms
it (MEDIUM, additive); TASK-277 measures its structure: per frame 1 clear + 3 full-frame gradient
fills + 2 full-frame tile copies at backing resolution (visible tile px per frame = exactly 2 x
backing), 0 tile/gradient rebuilds and 0 reconstruction allocations in steady state (background-off
saves 22-25 ms of a 95-110 ms frame at dpr1). The remaining costs outside the glow chain are smaller
(world 5-6 ms in both modes) or one-mode only (obstacle lighting 15.9 ms Main, -1 ms Chill), so the
background is the next target; TASK-278 found no CPU/GC candidate.

One candidate (tools/y8_background_rows_candidate.js, page-injected, runtime untouched): keep every
pass exactly as shipped (clear, gradients, tile copies, same order, same submissions, same Math.random
draws) and skip only the pixel updates that provably have no effect: the tile-copy rows whose texels
are all transparent (the tiles are transparent canvases with crystals/rocks anchored at the top and
bottom edges; source-over with a transparent source leaves the destination unchanged), clipped to
padded, integer-aligned device-row bands. Content rows are read once per tile build, never per frame.
An earlier smoke variant also skipped the clearRect under the opaque base gradient; it changed 1-2 LSB
on world edges in bad mode once the transform had drifted (a full-canvas clearRect is not a pure no-op
in Chromium there), so that part was dropped before pre-registration. Rejected designs, isolated and
never installed, are listed in hypothesis.json.

Actions:
  prepare  trees/identity + hypothesis.json (pre-registered target, expectation, provenance)
  visual   controlled deterministic comparisons candidate vs current (synthetic 60 Hz clock,
           readback confined to this pass): menu/start, early/mid/late gameplay with the moving
           camera, trails/sparks, forced shake, player glow exclusion, settled resizes incl.
           letterbox bars and odd backing sizes; both modes, seeds 1/4/49, dpr1 + dpr2, Chromium
           (+ Firefox when available). Source = a background-only scratch paint; bars compared too.
  capture  one untraced timing capture (rAF intervals + read-only sampler; no readback, no observer)
  run      visual pass, then (only if visuals are exact) 3 alternating 30 s pairs per mode on
           the natural replay + 1 moving-x pair per mode
  report   visual-validation.json, rows.json, timings.json, decision.json, manifest.json
  audit    recompute everything from the raws; verify the shipped runtime matches the decision
"""

import argparse
import base64
from contextlib import ExitStack
import io
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_cost as fc  # noqa: E402
import y8_chill_ablation as ch  # noqa: E402
import y8_cache_profile as cp  # noqa: E402

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
CANDIDATE = MODULE.parent / 'y8_background_rows_candidate.js'
TASK = 'TASK-281'
MODULE_AT_CAPTURE = 'module-at-capture'
PROFILE = 'desktop'
VIEWPORT = [1280, 720]
DPR = 1
MAIN, CHILL = 'bad', 'classic'
MODES = (MAIN, CHILL)
MODE_SETUP = {MAIN: {'seed': 4, 'replay_style': 'screening'}, CHILL: {'seed': 7, 'replay_style': 'chill-ceiling'}}
ARMS = {'current': 'current runtime (control): nothing injected; BackgroundRenderer paints clear + gradient + far tile + haze + '
                   'near tile + vignette over the full frame',
        'candidate': 'far and near tile copies clipped to the device rows that can receive a non-transparent texel; clear, '
                     'gradients and submissions unchanged (tools/y8_background_rows_candidate.js injected per page before startGame)'}
BODY_BEGIN, BODY_END = '// BEGIN TASK-281 candidate body', '// END TASK-281 candidate body'
CANDIDATE_MARKERS = ('TASK-281 candidate body', 'getLayerContentRows', '__backgroundRowsCandidate', 'contentRowRuns')
TILES = ('far', 'near')
SCENES = {'replay': 'natural seeded replay (gameplay; acceptance scene)',
          'moving-x': 'natural replay + render-time camera drive in x only (y ratio 0): the camera motion of '
                      'full-speed play where this environment starves physics; gameplay identical to replay'}
ACCEPTANCE_SCENES = ('replay',)
NO_WORSE_SCENES = ('replay', 'moving-x')
MIN_MEDIAN_REDUCTION = 0.05
MAX_WORSE = 0.05
REPS = ('p1', 'p2', 'p3')
# Alternating order: control first, candidate first, control first; moving-x candidate first.
SEQUENCE = [('replay', 'p1', 'current'), ('replay', 'p1', 'candidate'),
            ('replay', 'p2', 'candidate'), ('replay', 'p2', 'current'),
            ('replay', 'p3', 'current'), ('replay', 'p3', 'candidate'),
            ('moving-x', 'p1', 'candidate'), ('moving-x', 'p1', 'current')]
CAMERA_DRIVE = {'moving-x': {'amplitude_ratio': cp.CAMERA_DRIVE_AMPLITUDE_RATIO, 'steps_per_half': cp.CAMERA_DRIVE_STEPS_PER_HALF,
                             'y_ratio': 0.0}}

VISUAL_SEEDS = (1, 4, 49)
VISUAL_CONTEXTS = {
    'dpr1': {'viewport': [1280, 720], 'dpr': 1, 'seeds': VISUAL_SEEDS,
             'checkpoints': [('start', 1), ('early', 30), ('mid', 120), ('shake', 152), ('late', 240)], 'shake_at': 150,
             'resizes': [[960, 540], [640, 540], [1366, 768], [1000, 700], [1280, 720]], 'frames_after_resize': 10},
    'dpr2': {'viewport': [1280, 720], 'dpr': 2, 'seeds': (4,),
             'checkpoints': [('start', 1), ('early', 30), ('mid', 90), ('shake', 102), ('late', 120)], 'shake_at': 100,
             'resizes': [[960, 540], [640, 540], [1280, 720]], 'frames_after_resize': 6},
}
VISUAL_ENGINES = {'chromium': {'contexts': ('dpr1', 'dpr2')}, 'firefox': {'contexts': ('dpr1',), 'seeds': (4,)}}
VISUAL_ARMS = ('current', 'candidate')
STATE_KEYS = ('frame', 'clock', 'frames', 'dispatched', 'deaths', 'steps', 'menu', 'version', 'ninja', 'screen', 'grapnel',
              'score', 'elements', 'particles', 'pool', 'trackPoints', 'trackLast', 'obstacleTrackPoints', 'accumulator',
              'drawFrameId', 'canvas', 'css', 'logical', 'dpr', 'shaking', 'shockwaves', 'landings', 'playerGlow',
              'ambientGlow', 'motes', 'moteHash', 'barsVisible', 'lightmapHasLights', 'randomDraws', 'tileKeys', 'tileSizes',
              'gradientCacheSize', 'layerShift')
MEASURED_TARGET = {
    'source': ['artifacts/TASK-273/decision.json', 'artifacts/TASK-274/decision.json', 'artifacts/TASK-277/timings.json',
               'artifacts/TASK-277/cache-profile.json', 'artifacts/TASK-277/decision.json', 'artifacts/TASK-278/decision.json',
               'artifacts/TASK-279/decision.json', 'artifacts/TASK-280/decision.json'],
    'cave_background_off_median_saving_ms': {'bad': 15.93, 'classic': 24.77},
    'cave_background_tier': {'bad': 'REPEATED_SAVING', 'classic': 'REPEATED_SAVING'},
    'task274_single_stage_saving_ms': {'bad': [28.1, 24.3], 'classic': [19.4, 22.0], 'confidence': 'MEDIUM', 'interaction': 'ADDITIVE'},
    'task277_background_off_saving_ms_dpr1': {'bad_stationary': [23.5, 21.8], 'bad_moving': [33.8, 40.5], 'classic_stationary': [23.7, 24.9],
                                             'classic_moving': [26.6, 40.1], 'tier': 'REPEATED'},
    'task277_structure': '6 full-frame passes per frame at backing resolution: clearRect, base linear gradient, far crystal tile '
                         'copy (device-snapped drawImage), haze linear gradient, near rock tile copy, vignette radial gradient; '
                         'visible tile px per frame = exactly 2 x backing; 0 tile builds / 0 gradient builds / 0 reconstruction '
                         'allocations over 60 identical + 30 shifted frames (steady state is already cached)',
    'other_costs_outside_the_glow_chain_ms': {'world-geometry': {'bad': 6.26, 'classic': 5.35, 'note': 'whole layer <= 6 % per mode'},
                                              'obstacle-lighting': {'bad': 15.86, 'classic': -1.08, 'note': 'Main only; Chill NO_BENEFIT'},
                                              'player-trail': {'bad': 7.37, 'classic': 3.26, 'note': 'within noise in both'},
                                              'hud': {'bad': -4.89, 'classic': 1.59}, 'particles': {'bad': 3.37, 'classic': -7.35}},
    'control_frame_ms': 'about 90-105 ms at 1280x720 dpr1 in this environment after TASK-280 (its control/candidate means)',
    'excluded_mechanisms': {'TASK-279': 'reuse/caching of the far background stack (base gradient + far tile + haze) keyed on sizes and shift: '
                                        'REJECT, Chromium dithers gradient fills per device pixel so a translated cached raster differs by 1-2 LSB',
                            'TASK-280': 'glow composite region clip (union of dilated primitive rectangles): ACCEPT, integrated; the glow '
                                        'composite is not touched here'},
}
# Filled from the smoke run before `prepare` (scratch folder, not sealed evidence); see hypothesis.json
SMOKE_FINDINGS = [
    'smoke 1 (chromium dpr1 seed 4, both modes, scratch folder artifacts/TASK-281/smoke, not sealed evidence), candidate = clear '
    'skip + row clip: Chill EXACT at 11/11 checkpoints (final, background-only source, bars, 38-key state, Math.random counts); '
    'Main EXACT at menu/start/early (frames 1-30) but DIFFERENT from frame 120 on at 8/11 checkpoints (613 px at mid, 283 at late, '
    '18-880 after resizes; max channel delta 2) while source, bars and state stayed exact. The differing pixels lie on world '
    'outlines, translucent obstacle faces and crystal/rock edges (overlay kept: smoke/visual/png/*-mid.png).',
    'smoke 2, same candidate with a Path2D clip (current default path untouched): identical pixel counts -> not the path state. '
    'probe_transform.py: ctx.getTransform() identical in both arms on all 130 frames (d drifts 0.66666672 -> 0.66667115).',
    'smoke 3, clip restricted to pixel-aligned 1:1 copies (off in Main from frame 3 on): identical pixel counts again -> the '
    'differences come from the skipped clearRect alone, which is therefore not a no-op in Chromium once the bad-mode transform '
    'has drifted; the clear skip was dropped from the candidate (rejected_designs_isolated).',
    'smoke 4 (observer bug, 4 FAILED attempts preserved) and smoke 5, candidate = row clip only with the shipped clear kept: '
    'Main and Chill EXACT at 11/11 checkpoints each; the clip applied on 100 % of frames; copy area far 0.785 / near 0.498 of the '
    'frame rows (0.717 tile passes removed per frame); far tile 165/720 rows transparent, near 374/720 (two content runs each at '
    'every tested backing). dpr2 (2560x1440 backing, 1920x1080 tiles copied at 4:3): Main EXACT at 9/9 checkpoints, clip applied '
    'on 100 % of frames, copy area far 0.778 / near 0.492 (0.731 tile passes removed).',
    'no timing smoke was run: the timing expectation stays pre-registered from the measured row fractions and the TASK-277 pass costs.']


def utc():
    return fc.utc()


def candidate_text():
    return CANDIDATE.read_text()


def candidate_sha():
    return fc.sha_file(CANDIDATE)


def candidate_body(text=None):
    """The body between the BEGIN/END markers (what an ACCEPT appends to render/effects.js)."""
    text = candidate_text() if text is None else text
    if BODY_BEGIN not in text or BODY_END not in text:
        return None
    return text[text.index(BODY_BEGIN):text.index(BODY_END) + len(BODY_END)]


def body_sha(text=None):
    body = candidate_body(text)
    return fc.sha_bytes(body.encode()) if body else None


def runtime_has_candidate(root):
    src = (Path(root) / 'render/effects.js').read_text()
    return any(m in src for m in CANDIDATE_MARKERS)


def runtime_body_sha(root=ROOT):
    """sha256 of the candidate body as found in the runtime (None when absent)."""
    src = (Path(root) / 'render/effects.js').read_text()
    return body_sha(src) if BODY_BEGIN in src else None


def preserve_module(out):
    folder = Path(out) / MODULE_AT_CAPTURE
    folder.mkdir(parents=True, exist_ok=True)
    for src in (MODULE, CANDIDATE):
        digest = fc.sha_file(src)
        target = folder / f'{src.stem}-{digest[:8]}{src.suffix}'
        if not target.exists():
            shutil.copyfile(src, target)
    return fc.sha_file(MODULE)


def case_name(mode, scene, rep, arm, index):
    return f'{mode}-{scene}-{rep}-{arm}-i{index}'


def unique_path(folder, case, suffix):
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f'{case}{suffix}', 1
    while path.exists():
        n += 1
        path = folder / f'{case}.attempt{n}{suffix}'
    return path


# ------------------------------------------------------------------ JS --

# The candidate overrides BackgroundRenderer.prototype.paint / paintMenu / drawLayerTile and adds
# getLayerContentRows; the live instance picks the prototype methods up at once. Tiles already in
# layerCache get their content rows on the first copy (one getImageData, cached on the layer).
INSTALL_CANDIDATE = '''(src) => {
    (0, eval)(src)
    return !!(window.__backgroundRowsCandidate && window.__backgroundRowsCandidate.task === 'TASK-281')
}'''

CANDIDATE_PRESENT = '''() => !!window.__backgroundRowsCandidate'''

TILE_NAME = '''const tileName = layer => { const L = visualEffects.background.layerCache
        for (const k of ['far', 'near']) if (L[k] && L[k].canvas === layer.canvas) return k; return 'other' }'''

VISUAL_BEGIN = '''(cfg) => {
    cancelAnimationFrame(game)
    const V = window.__visual = {clock: 1000, frame: 0, samples: [], randomDraws: 0, rowsCalls: 0, clippedCalls: 0,
        realNow: performance.now.bind(performance), tiles: null}
    performance.now = () => V.clock
    const random = Math.random
    Math.random = function() { V.randomDraws++; return random() }
    ''' + TILE_NAME + '''
    V.reset = () => { V.tiles = {far: null, near: null, other: null} }
    V.reset()
    // Called by the candidate only, once per tile copy: the content rows and the device-row bands used
    window.__backgroundRowsObserve = (layer, content, bands, transform, shift, height, bounds, texel) => {
        V.rowsCalls++
        if (bands) V.clippedCalls++
        const top = transform.d * bounds.y + transform.f, bottom = transform.d * (bounds.y + bounds.height) + transform.f
        let inside = 0
        if (bands) for (const [y0, y1] of bands) inside += Math.max(0, Math.min(y1, bottom) - Math.max(y0, top))
        const entry = {clip: bands ? inside / (bottom - top) : 1, bands: bands ? bands.length : 0, runs: content.runs.length,
            rows: content.rows, transparentRows: content.transparentRows, transparentFraction: content.transparentRows / content.rows,
            deviceRows: bottom - top, texel: transform.d * height / content.rows, candidateTexel: texel,
            copyTop: transform.d * shift.y + transform.f, shiftY: shift.y}
        V.tiles[tileName(layer)] = entry
    }
    return {installed: !!window.__backgroundRowsCandidate}
}'''

VISUAL_START = '''(mode) => { startGame(mode); cancelAnimationFrame(game); return typeof version !== 'undefined' ? version : null }'''

MOTE_HASH = '''const moteHash = () => { const L = visualEffects.particles.moteLayout; if (!L) return null
        let h = 2166136261; for (let k = 0; k < L.length; k++) { h = Math.imul(h ^ Math.round(L[k] * 1000), 16777619) >>> 0 } return h }'''

VISUAL_STEP = '''(n) => {
    const V = window.__visual
    ''' + MOTE_HASH + '''
    for (let i = 0; i < n; i++) {
        V.frame++; V.clock = 1000 + V.frame * 1000 / 60
        V.reset()
        gameLoop(V.clock); cancelAnimationFrame(game)
        const sx = (typeof screen !== 'undefined' && screen && typeof screen.x === 'number') ? screen.x : null
        const sy = sx === null ? null : screen.y
        V.samples.push([V.frame, sx, sy, moteHash(), V.tiles.far ? {far: V.tiles.far.clip, near: V.tiles.near ? V.tiles.near.clip : null,
            farApplied: V.tiles.far.bands > 0, nearApplied: V.tiles.near ? V.tiles.near.bands > 0 : null} : null,
            [canvas.width, canvas.height]])
    }
    return V.frame
}'''

VISUAL_SHAKE = '''() => { visualEffects.screenEffects.triggerDeath(ninja.x, ninja.y); return visualEffects.screenEffects.shakeUntil }'''

VISUAL_CHECKPOINT = '''(cfg) => {
    const V = window.__visual, FC = window.__featureCost, B = visualEffects.background
    ''' + MOTE_HASH + '''
    const png = canvas.toDataURL('image/png')
    const bars = Array.from(document.getElementsByClassName('window-bar')).filter(c => !c.hidden && c.width > 0 && c.height > 0)
        .map(c => c.toDataURL('image/png'))
    // Source: the background layer alone, painted by the arm's own BackgroundRenderer into a scratch canvas
    // with the game transform (readback confined to this pass; Math.random draws during it are recorded)
    const scratch = document.createElement('canvas')
    scratch.width = canvas.width; scratch.height = canvas.height
    const sctx = scratch.getContext('2d'); const t = ctx.getTransform()
    sctx.setTransform(t.a, t.b, t.c, t.d, t.e, t.f)
    const gameCtx = B.ctx; B.ctx = sctx
    const draws = V.randomDraws
    const tilesBefore = {far: V.tiles.far, near: V.tiles.near}
    try { if (cfg.scene === 'menu') B.paintMenu(); else B.paint() } finally { B.ctx = gameCtx }
    const source = scratch.toDataURL('image/png')
    const rect = canvas.getBoundingClientRect()
    const S = visualEffects.screenEffects
    const hasGame = typeof version !== 'undefined' && version && typeof ninja !== 'undefined' && ninja
    const L = B.layerCache
    const W = LOGICAL_VIEWPORT.width, H = LOGICAL_VIEWPORT.height
    const state = {frame: V.frame, clock: V.clock, frames: FC.frames.length, dispatched: FC.dispatched.length,
        deaths: FC.deaths.length, steps: FC.physicsSteps, menu: !!menu.visible, version: hasGame ? version : null,
        ninja: hasGame ? [ninja.x, ninja.y, ninja.speedX, ninja.speedY] : null,
        screen: (typeof screen !== 'undefined' && screen && typeof screen.x === 'number') ? [screen.x, screen.y] : null,
        grapnel: hasGame && typeof grapnel !== 'undefined' && grapnel ? [grapnel.throwed, grapnel.isGrappled(), grapnel.pos.length] : null,
        score: hasGame ? scoreText.count[version] : null,
        elements: hasGame && typeof floors !== 'undefined' && floors ? floors.map(f => f.elements.length) : null,
        particles: visualEffects.particles.particles.length, pool: visualEffects.particles.pool.length,
        trackPoints: hasGame ? ninja.track.pos.length : null,
        trackLast: hasGame && ninja.track.pos.length ? [ninja.track.pos[ninja.track.pos.length - 1].x, ninja.track.pos[ninja.track.pos.length - 1].y] : null,
        obstacleTrackPoints: hasGame && floors ? floors.reduce((n, f) => n + f.elements.reduce((m, e) => m + (e.track ? e.track.pos.length : 0), 0), 0) : null,
        accumulator: typeof physicsTiming !== 'undefined' ? physicsTiming.accumulatorMs : null,
        drawFrameId, canvas: [canvas.width, canvas.height], css: [rect.width, rect.height], logical: [width, height],
        dpr: devicePixelRatio, shaking: S.shakeUntil > V.clock, shockwaves: S.shockwaves.length, landings: S.landings.length,
        playerGlow: visualEffects.playerGlow.shouldDraw(), ambientGlow: visualEffects.ambientGlow.shouldDraw(),
        motes: visualEffects.particles.ambientMotes ? visualEffects.particles.ambientMotes.length : 0, moteHash: moteHash(),
        barsVisible: Array.from(document.getElementsByClassName('window-bar')).filter(c => !c.hidden).length,
        lightmapHasLights: visualEffects.lightmap.hasLights, randomDraws: draws,
        tileKeys: {far: L.far ? L.far.key : null, near: L.near ? L.near.key : null},
        tileSizes: {far: L.far ? [L.far.canvas.width, L.far.canvas.height] : null, near: L.near ? [L.near.canvas.width, L.near.canvas.height] : null},
        gradientCacheSize: B.gradientCache.size,
        layerShift: {far: B.getLayerShift(W, H, STYLE.caveLayers.crystals), near: B.getLayerShift(W, H, STYLE.caveLayers.nearRocks)},
        randomDrawsDuringReadback: V.randomDraws - draws}
    const content = {}
    for (const k of ['far', 'near']) content[k] = L[k] && L[k].contentRows ? {runs: L[k].contentRows.runs, rows: L[k].contentRows.rows,
        transparentRows: L[k].contentRows.transparentRows, contentRowCount: L[k].contentRows.contentRowCount} : null
    const candidate = {present: !!window.__backgroundRowsCandidate, lastFrameTiles: tilesBefore, scratchTiles: {far: V.tiles.far, near: V.tiles.near},
        rowsCalls: V.rowsCalls, clippedCalls: V.clippedCalls, contentRows: content}
    return {png, bars, source, state, candidate}
}'''

VISUAL_SAMPLES = '''() => ({samples: window.__visual.samples, randomDraws: window.__visual.randomDraws,
    rowsCalls: window.__visual.rowsCalls, clippedCalls: window.__visual.clippedCalls})'''


# ------------------------------------------------------------- browser --

def start_engine(root, stack, engine):
    from browser_test_support import start_browser_test, QuietHandler
    if engine == 'chromium':
        return start_browser_test(root, stack.callback)
    from functools import partial
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from playwright.sync_api import sync_playwright
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
    stack.callback(server.server_close)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stack.callback(thread.join)
    stack.callback(server.shutdown)
    pw = sync_playwright().start()
    stack.callback(pw.stop)
    browser = getattr(pw, engine).launch()
    stack.callback(browser.close)
    return f'http://127.0.0.1:{server.server_port}/', browser


def environment(browser, engine):
    if engine == 'chromium':
        return dict(fc.environment(browser), engine=engine)
    import importlib.metadata
    import os
    return {'os': platform.platform(), 'python': platform.python_version(), 'engine': engine,
            'playwright': importlib.metadata.version('playwright'), 'browser': browser.version,
            'cpu_count': os.cpu_count(), 'loadavg': os.getloadavg(), 'gpu': 'not readable (no CDP on ' + engine + ')'}


def new_context(browser, viewport, dpr, seed, network):
    ctx = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]}, device_scale_factor=dpr,
                              service_workers='block')

    def route(r):
        u = r.request.url
        if u == fc.SDK_URL:
            network.append('SDK_BLOCKED ' + u); r.abort()
        elif u.startswith('http://127.0.0.1'):
            network.append('LOCAL ' + u); r.continue_()
        else:
            network.append('BLOCKED ' + u); r.abort()
    ctx.route('**/*', route)
    ctx.add_init_script(fc.SEED_SCRIPT % seed)
    return ctx


def open_page(stack, root, raw, viewport, dpr, seed, engine='chromium', cpu_throttle=None):
    url, browser = start_engine(root, stack, engine)
    raw['environment'] = environment(browser, engine)
    ctx = new_context(browser, viewport, dpr, seed, raw['network'])
    stack.callback(ctx.close)
    page = ctx.new_page()
    page.on('pageerror', lambda e: raw['errors'].append(str(e)))
    page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
    if engine == 'chromium' and cpu_throttle is not None:
        ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': cpu_throttle})
    page.goto(url + 'index.html', wait_until='domcontentloaded')
    page.wait_for_function(fc.BOOTED, timeout=60000)
    return page


def common_raw(args, extra):
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    return root, {'case': args.case, 'task': TASK, 'argv': sys.argv, 'started_utc': utc(),
                  'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
                  'tree_has_candidate_methods': runtime_has_candidate(root),
                  'harness_sha256': fc.sha_file(fc.HARNESS), 'chill_sha256': fc.sha_file(ch.MODULE),
                  'cache_profile_sha256': fc.sha_file(cp.MODULE), 'module_sha256': preserve_module(args.output),
                  'candidate_sha256': candidate_sha(), 'candidate_body_sha256': body_sha(),
                  'network': [], 'errors': [], 'console_errors': [], **extra}


# ------------------------------------------------------------- prepare --

def hypothesis(identity):
    return {
        'task': TASK, 'utc': utc(),
        'mechanism': 'redundant-update reduction at the cave background: skip the pixel updates that cannot change the image, '
                     'namely the far/near tile-copy rows whose texels are all transparent (each copy clipped to padded '
                     'integer-aligned device-row bands around its content rows). No pass is reordered, removed, cached, moved or '
                     'merged; the clear, every gradient fill and every tile copy are submitted exactly as today with the same '
                     'transform and the same Math.random draws.',
        'measured_target': MEASURED_TARGET,
        'chosen_target': 'the cave background (BackgroundRenderer.paint): the largest measured cost outside the glow composite '
                         'in BOTH modes (TASK-273 median saving when off 15.9 ms Main / 24.8 ms Chill, REPEATED_SAVING in both; '
                         'TASK-274 MEDIUM, additive; TASK-277 background-off 22-25 ms stationary at dpr1 in both modes = 24 % of '
                         'the frame). Six full-frame passes per frame: clear, base gradient, far tile copy, haze, near tile copy, '
                         'vignette. TASK-277 ruled out per-frame reconstruction (0 rebuilds, 0 allocations in steady state), so the '
                         'remaining redundancy is inside the passes themselves.',
        'why_not_the_other_remaining_costs': 'world-geometry costs 6.3 ms Main / 5.4 ms Chill (TASK-273): removing the WHOLE layer '
                                             'is at the 5 % threshold, so no partial exact reduction can pass in both modes; '
                                             'obstacle-lighting costs 15.9 ms in Main but -1.1 ms in Chill (NO_BENEFIT), so no '
                                             'reduction can reach 5 % in Chill; player-trail/hud/particles are within noise '
                                             '(TASK-273/278); physics + GC are 0.8 % of the frame (TASK-278); the glow composite '
                                             'and the player glow chain are the TASK-280 mechanism (excluded by the ticket).',
        'unnecessary_work': {
            'tile_rows': 'the far crystal and near rock tiles are transparent canvases (getLayerTile creates them, the painters '
                         'fill polygons anchored at y = -2 and y = height + 2 plus 1.2 % solid rows at both edges), so a band of '
                         'rows in the middle holds only fully transparent texels. drawLayerTile copies each tile over the whole '
                         'height with source-over: a transparent source sample leaves the destination unchanged, so every device '
                         'row whose bilinear footprint sees only transparent texels is work with no effect. Measured (smoke, '
                         '1280x720 tiles): far 165/720 rows transparent (runs [0,240) and [405,720)), near 374/720 (runs [0,103) '
                         'and [477,720)).',
            'clear_not_included': 'the clearRect under the opaque base gradient looks redundant by the same argument (opaque '
                                  'source-over fill over the same bounds), but smoke showed it is not a pure no-op in Chromium: see '
                                  'rejected_designs_isolated and smoke_findings_before_the_run.'},
        'why_it_differs_from_TASK_279_and_TASK_280': 'TASK-279 cached a far stack raster and re-drew it translated by the camera '
                                                      'shift (REJECT: the Chromium gradient dither pattern is fixed to device pixels, '
                                                      'and the drifted bad-mode transform resampled it). Here nothing is cached across '
                                                      'frames, nothing is translated, and every gradient is filled by the same '
                                                      'fillRect at the same device position: the dither cannot move. TASK-280 clipped '
                                                      'the glow composite upscales (black source under lighter). Here the clipped '
                                                      'operation is the background tile copy (transparent source under source-over), '
                                                      'a different renderer, pass and no-op argument; the glow chain is untouched.',
        'expected_work_reduction': {
            'measured_rows': 'smoke-measured (chromium dpr1 seed 4, both modes, 1280x720 backing): far tile 22.9 % transparent rows, '
                             'candidate copy clipped to 0.786 of the frame rows; near tile 51.9 % transparent, clipped to 0.496; '
                             'constant over the gameplay frames (the bands depend on the tile and the transform, not on the camera x '
                             'shift); 0.78 / 0.49-0.50 at the other tested backings (960x540, 640x480, 1366x768, 1000x700).',
            'passes_removed_equivalent': 'about (1 - 0.786) + (1 - 0.496) = 0.72 of one full-frame tile copy per frame.',
            'expected_ms_dpr1': 'TASK-277: 3 gradient fills + 2 tile copies cost 22-25 ms more than clear + one solid fill, about '
                                '4-5 ms per full-frame pass. If a tile copy costs in proportion to its clipped rows, the candidate '
                                'removes about 3-3.5 ms of tile raster per frame: roughly 3-4 % of a 90-105 ms frame in both modes, '
                                'i.e. probably BELOW the 5 % acceptance threshold (less if the cost is per submission rather than '
                                'per pixel, more if the mostly-transparent copies cost more per pixel than a gradient fill). The '
                                'experiment measures whether the structural bound is reached; an IMMATERIAL result is the expected '
                                'negative outcome and completes the ticket as a REJECT.',
            'threshold': f'>= {MIN_MEDIAN_REDUCTION:.0%} median active frame-time reduction in both modes over 3 alternating '
                         f'30 s pairs, no gameplay pair (replay or moving-x) worse by > {MAX_WORSE:.0%}',
            'overhead': 'one getImageData alpha scan per tile build (two per viewport size, never per frame: TASK-277 shows 0 tile '
                        'builds in steady state); per frame two Path2D clips (2 rects each) inside save/restore pairs and a handful '
                        'of arithmetic operations, expected well under 0.1 ms of JS.'},
        'exactness_argument': 'the clip bands are integer-aligned device rows containing every texel row with any '
                              'alpha > 0, padded by two texels (in device px, at least one px each) plus two device px, which '
                              'exceeds the bilinear footprint of the upscaled or 1:1 copy; outside the bands every sample is a '
                              'fully transparent texel, and source-over with a transparent source leaves the destination unchanged, '
                              'so even a partially covered clip-edge pixel is exact (dst*(1-c) + dst*c). The bands extend one tile '
                              'width beyond the fill bounds horizontally so no clip edge meets a copy edge. The clip is a Path2D '
                              'inside one save/restore pair, so the current default path and every other context state are left '
                              'as the shipped code leaves them. The argument does not depend on the copy being 1:1: a drifted or '
                              'scaled copy samples the same transparent texels outside the bands. Any pixel difference rejects the '
                              'candidate regardless of this argument.',
        'control': {'description': 'unchanged current runtime: the served tree is `git archive HEAD` (identity.json), '
                                   'no page injection in the current arm', **{k: identity[k] for k in ('current_commit', 'current_tar_sha256')}},
        'candidate': {'file': str(CANDIDATE.relative_to(ROOT)), 'sha256': candidate_sha(), 'body_sha256': body_sha(),
                      'installation': 'page.evaluate of the file text after boot and fc.INSTRUMENT, before startGame; the body '
                                      'overrides BackgroundRenderer.prototype.drawLayerTile and adds getLayerContentRows; '
                                      'paint()/paintMenu() and every other method stay the shipped ones; shipping runtime untouched',
                      'shipping_runtime_has_candidate_methods': runtime_has_candidate(ROOT)},
        'rejected_designs_isolated': [
            {'design': 'skip the clearRect under the opaque base gradient in paint()/paintMenu() (smoke variants 1-3)',
             'reason': 'exact in Chill, but in Main it changed 1-2 LSB on world outlines and translucent faces from about frame 100 '
                       'on (613 px at frame 120, max delta 2) while the background-only paint, bars and state stayed exact, with '
                       'the row clip on, with a Path2D clip, and with the clip switched off after frame 3 (identical pixel counts '
                       'each time); the per-frame ctx.getTransform() was identical in both arms. A full-canvas clearRect is '
                       'therefore not a pure no-op in Chromium once the bad-mode float32 transform has drifted (TASK-279: ~5e-8 '
                       'per frame; it evidently re-applies the stored matrix to the recording), so skipping it is rejected on '
                       'exactness. Smoke raws preserved under artifacts/TASK-281/smoke (not sealed evidence). Never installed in '
                       'the pre-registered candidate.'},
            {'design': 'cache the base gradient + far tile + haze as one far-stack raster keyed on sizes and shift',
             'reason': 'TASK-279 REJECT (dither phase under translation, bad-mode transform drift); not repeated. Never installed.'},
            {'design': 'merge the base gradient, haze and vignette into one fill (3 passes -> 1)',
             'reason': 'three gradients with different geometry and alpha cannot be expressed as one canvas gradient; the 8-bit '
                       'intermediate blending and the per-fill dither make a merged fill non-identical. Never installed.'},
            {'design': 'skip the base gradient under the far tile',
             'reason': 'the far tile is transparent between its crystals (paintCrystalTile paints polygons on a transparent canvas), '
                       'so the gradient shows through: not redundant. Never installed.'},
            {'design': 'exclude the alpha-0 centre disc of the vignette radial gradient from its fill',
             'reason': 'the disc (inner radius 0.18 x 0.58 x diagonal) is about 8 % of the frame, and the gradient dither at the disc '
                       'edge makes exactness uncertain for a tiny gain. Never installed.'},
            {'design': 'drop the second, zero-device-width tile copy submitted at camera shift 0 (TASK-277)',
             'reason': 'it rasterises nothing (clipped to < 1 device px); only a JS submission, far below any timing threshold. '
                       'Never installed.'}],
        'visual_requirement': 'exact final pixels, exact background-only (source) pixels, exact bar-canvas pixels and equal gameplay '
                              'state at every checkpoint on every tested engine; unexplained differences reject the candidate',
        'why_the_clip_is_not_guarded': 'a smoke variant restricted the clip to pixel-aligned 1:1 copies (|device px per texel - 1| '
                                       '<= 1e-7); it changed nothing (the bad-mode differences came from the skipped clear), and the '
                                       'exactness argument holds for any axis-aligned copy, so the candidate clips every copy, '
                                       'including the 4:3 upscale at dpr2 and the drifted bad-mode copies.',
        'smoke_findings_before_the_run': SMOKE_FINDINGS,
        'prior_experiments_not_repeated': ['TASK-265 live geometry bounding-box clip (PURSUE, integrated)',
                                           'TASK-265 readback oracle (REJECT; this candidate reads pixels once per tile build, never per frame)',
                                           'TASK-265 CanvasPattern (REJECT)', 'TASK-265 winding (REJECT)',
                                           'TASK-276 frozen source/blur arms (diagnostic only)',
                                           'TASK-279 far background stack cache (REJECT: dither phase / transform drift)',
                                           'TASK-280 glow composite region clip (ACCEPT, integrated; kept as part of the control)'],
        'not_claimed': ['60 FPS', 'release readiness', 'device results'],
    }


def prepare(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = utc()
    identity = fc.build_trees(out)
    ceiling = fc.environment_ceiling(PROFILE)
    module_sha = preserve_module(out)
    fc.dump(out / 'identity.json', {'task': TASK, 'utc_start': started, 'utc_end': utc(), 'argv': sys.argv,
                                    'identity': identity, 'environment_ceiling': ceiling,
                                    'harness_sha256': fc.sha_file(fc.HARNESS), 'chill_sha256': fc.sha_file(ch.MODULE),
                                    'cache_profile_sha256': fc.sha_file(cp.MODULE), 'module_sha256': module_sha,
                                    'candidate_sha256': candidate_sha(), 'candidate_body_sha256': body_sha(),
                                    'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py')})
    if (out / 'hypothesis.json').exists() and not (out / 'hypothesis-initial.json').exists():
        shutil.move(out / 'hypothesis.json', out / 'hypothesis-initial.json')
    fc.dump(out / 'hypothesis.json', hypothesis(identity))
    print('PASS identity + hypothesis written', out, 'HEAD', identity['current_commit'],
          'dirty_runtime=%r' % identity['current_dirty_runtime'], 'candidate', candidate_sha()[:12],
          'ceiling_fps=%.2f' % ceiling['average_fps'])
    return 0


# -------------------------------------------------------------- visual --

def visual_plan(engines=None):
    plan = []
    for engine, e in VISUAL_ENGINES.items():
        if engines and engine not in engines:
            continue
        for context in e['contexts']:
            c = VISUAL_CONTEXTS[context]
            for seed in e.get('seeds', c['seeds']):
                for mode in MODES:
                    for arm in VISUAL_ARMS:
                        plan.append({'engine': engine, 'context': context, 'seed': seed, 'mode': mode, 'arm': arm})
    return plan


def visual_case(p):
    return f"visual-{p['engine']}-{p['context']}-{p['mode']}-seed{p['seed']}-{p['arm']}"


def png_bytes(data_url):
    return base64.b64decode(data_url.split(',', 1)[1])


def pixels_sha(png):
    """sha256 of the decoded RGBA bytes (the comparison unit); None when PIL is absent."""
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.open(io.BytesIO(png)).convert('RGBA')
    return fc.sha_bytes(im.tobytes()) + ':%dx%d' % im.size


def visual_session(args, p, out):
    """One deterministic page: menu checkpoint, start, gameplay checkpoints, forced shake, settled resizes."""
    context = VISUAL_CONTEXTS[p['context']]
    style = MODE_SETUP[p['mode']]['replay_style'] if p['seed'] == MODE_SETUP[p['mode']]['seed'] else 'screening'
    replay = ch.replay_script(p['seed'], PROFILE, 60000, style)
    settings = {'pass': 'visual', 'engine': p['engine'], 'context': p['context'], 'viewport': context['viewport'],
                'dpr': context['dpr'], 'mode': p['mode'], 'seed': p['seed'], 'arm': p['arm'], 'arm_label': ARMS[p['arm']],
                'replay_style': style, 'replay_sha256': fc.replay_sha256(replay),
                'clock': 'synthetic 60 Hz rAF timestamps, performance.now pinned (TASK-272 prove clock); rAF cancelled, '
                         'gameLoop driven by the harness', 'checkpoints': context['checkpoints'], 'shake_at': context['shake_at'],
                'resizes': context['resizes'], 'frames_after_resize': context['frames_after_resize'],
                'readback': 'canvas.toDataURL(image/png) of the game canvas (final), of every visible bar canvas (bars) and of a '
                            'background-only scratch paint by the arm\'s own BackgroundRenderer (source), this pass only',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter'}
    args.case = visual_case(p)
    root, raw = common_raw(args, {'settings': settings, 'replay': replay, 'checkpoints': [], 'resizes': []})
    cfg = {'dpr': context['dpr'], 'input': 'mouse', 'ablate': [], 'diagnostic': True, 'replay': replay,
           'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
    pngs = {}

    def checkpoint(page, name, scene):
        r = page.evaluate(VISUAL_CHECKPOINT, {'scene': scene})
        png = png_bytes(r['png'])
        source = png_bytes(r['source'])
        bars = [png_bytes(u) for u in r['bars']]
        bar_pixels = [pixels_sha(b) for b in bars]
        entry = {'name': name, 'scene': scene, 'final_sha256': fc.sha_bytes(png), 'final_pixels_sha256': pixels_sha(png),
                 'final_bytes': len(png), 'source_sha256': fc.sha_bytes(source), 'source_pixels_sha256': pixels_sha(source),
                 'bars_sha256': [fc.sha_bytes(b) for b in bars], 'bars_pixels_sha256': bar_pixels, 'bars_count': len(bars),
                 'state': r['state'], 'candidate': r['candidate']}
        pngs[name] = (png, source, bars)
        raw['checkpoints'].append(entry)
        return entry

    with ExitStack() as stack:
        page = open_page(stack, root, raw, context['viewport'], context['dpr'], p['seed'], p['engine'])
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate('() => cancelAnimationFrame(game)')
        if p['arm'] == 'candidate':
            raw['candidate_installed'] = page.evaluate(INSTALL_CANDIDATE, candidate_text())
        raw['begin'] = page.evaluate(VISUAL_BEGIN, {'arm': p['arm']})
        raw['candidate_present_in_page'] = page.evaluate(CANDIDATE_PRESENT)
        page.evaluate(VISUAL_STEP, 2)
        checkpoint(page, 'menu', 'menu')
        raw['started_version'] = page.evaluate(VISUAL_START, p['mode'])
        frame = 0
        for name, target in context['checkpoints']:
            if frame < context['shake_at'] <= target:
                page.evaluate(VISUAL_STEP, context['shake_at'] - frame)
                frame = context['shake_at']
                raw['shake_until'] = page.evaluate(VISUAL_SHAKE)
            page.evaluate(VISUAL_STEP, target - frame)
            frame = target
            checkpoint(page, name, 'game')
        for size in context['resizes']:
            before = page.evaluate('() => [canvas.width, canvas.height, width]')
            t0 = time.time()
            page.set_viewport_size({'width': size[0], 'height': size[1]})
            try:
                page.wait_for_function('b => canvas.width !== b[0] || canvas.height !== b[1]', arg=before, timeout=5000)
                handler_seen = True
            except Exception:
                handler_seen = False
            page.wait_for_timeout(350)
            frame += context['frames_after_resize']
            page.evaluate(VISUAL_STEP, context['frames_after_resize'])
            dims = page.evaluate(fc.DIMENSIONS)
            raw['resizes'].append({'requested': size, 'before': before, 'handler_seen': handler_seen, 'wait_ms': round((time.time() - t0) * 1000),
                                   'dimensions': dims, 'backing_equals_round_css_times_dpr':
                                   dims['canvas'] == [round(dims['css'][0] * dims['dpr']), round(dims['css'][1] * dims['dpr'])]})
            checkpoint(page, f'resize-{size[0]}x{size[1]}', 'game')
        raw.update(page.evaluate(VISUAL_SAMPLES))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['candidate_present_in_page_end'] = page.evaluate(CANDIDATE_PRESENT)
        raw['ended_utc'] = utc()
    raw['result'] = 'COMPLETE' if not raw['errors'] else 'FAILED: page errors ' + json.dumps(raw['errors'])[:300]
    if raw['dimensions']['platform'] not in ('disabled', 'absent'):
        raw['result'] = 'FAILED: SDK isolation ' + str(raw['dimensions']['platform'])
    if p['arm'] == 'candidate' and not (raw.get('candidate_installed') and raw['candidate_present_in_page_end']):
        raw['result'] = 'FAILED: candidate not installed'
    if p['arm'] == 'current' and raw['candidate_present_in_page_end']:
        raw['result'] = 'FAILED: candidate present in the current arm'
    if p['arm'] == 'candidate' and raw['result'] == 'COMPLETE' and not raw.get('rowsCalls'):
        raw['result'] = 'FAILED: candidate installed but its tile hook never ran'
    path = unique_path(out / 'visual', args.case, '.json')
    fc.dump(path, raw)
    print('PASS' if raw['result'] == 'COMPLETE' else 'FAIL', args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'checkpoints', len(raw['checkpoints']), 'rowsCalls', raw.get('rowsCalls'), 'clippedCalls', raw.get('clippedCalls'),
          'frames', raw['checkpoints'][-1]['state']['frame'] if raw['checkpoints'] else None, flush=True)
    return raw, pngs, path


def visual(args):
    out = Path(args.output).resolve()
    plan = visual_plan(args.engines)
    if args.only:
        plan = [p for p in plan if visual_case(p) in args.only]
    status = 0
    results = {}
    for p in plan:
        try:
            raw, pngs, path = visual_session(args, p, out)
        except Exception as e:  # engine unavailable or crashed: preserve the failure
            fail = {'case': visual_case(p), 'task': TASK, 'argv': sys.argv, 'started_utc': utc(), 'ended_utc': utc(),
                    'settings': {'pass': 'visual', **p}, 'result': 'FAILED: ' + str(e).splitlines()[0][:300], 'checkpoints': []}
            fc.dump(unique_path(out / 'visual', visual_case(p), '.json'), fail)
            print('FAIL', visual_case(p), fail['result'], flush=True)
            if p['engine'] == 'chromium':
                status = 1
            continue
        if raw['result'] != 'COMPLETE' and p['engine'] == 'chromium':
            status = 1
        key = (p['engine'], p['context'], p['mode'], p['seed'])
        results.setdefault(key, {})[p['arm']] = (raw, pngs)
        # Keep PNG files small: the current arm of seed 4 at dpr1 on chromium (final only), plus every mismatch.
        keep = p['engine'] == 'chromium' and p['context'] == 'dpr1' and p['seed'] == 4 and p['arm'] == 'current'
        if 'current' in results[key] and 'candidate' in results[key]:
            cur, cand = results[key]['current'], results[key]['candidate']
            for a, b in zip(cur[0]['checkpoints'], cand[0]['checkpoints']):
                if not pixels_equal(a, b, 'final') or not pixels_equal(a, b, 'source') or not bars_equal(a, b):
                    save_png(out, visual_case(dict(p, arm='current')), a['name'], cur[1].get(a['name']), full=True)
                    save_png(out, visual_case(dict(p, arm='candidate')), b['name'], cand[1].get(b['name']), full=True)
        if keep:
            for name, triple in pngs.items():
                save_png(out, visual_case(p), name, triple)
    return status


def save_png(out, case, name, triple, full=False):
    if not triple:
        return
    folder = out / 'visual' / 'png'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{case}-{name}.png').write_bytes(triple[0])
    if full:
        (folder / f'{case}-{name}-source.png').write_bytes(triple[1])
        for i, png in enumerate(triple[2]):
            (folder / f'{case}-{name}-bar{i}.png').write_bytes(png)


def pixels_equal(a, b, kind):
    """Decoded-pixel equality (falls back to PNG bytes when PIL was absent)."""
    pa, pb = a.get(f'{kind}_pixels_sha256'), b.get(f'{kind}_pixels_sha256')
    if pa and pb:
        return pa == pb
    return a[f'{kind}_sha256'] == b[f'{kind}_sha256']


def bars_equal(a, b):
    pa, pb = a.get('bars_pixels_sha256'), b.get('bars_pixels_sha256')
    if pa is not None and pb is not None and all(pa) and all(pb):
        return pa == pb
    return a.get('bars_sha256') == b.get('bars_sha256')


def png_diff(a, b):
    """Per-channel pixel difference statistics of two PNG files (PIL + numpy); RGBA getbbox is NOT used (alpha-only)."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {'unavailable': 'PIL/numpy absent'}
    ia, ib = Image.open(a).convert('RGBA'), Image.open(b).convert('RGBA')
    if ia.size != ib.size:
        return {'size_a': ia.size, 'size_b': ib.size, 'different_size': True}
    da, db = np.asarray(ia).astype(np.int16), np.asarray(ib).astype(np.int16)
    delta = np.abs(da - db)
    per_pixel = delta.max(axis=2)
    mask = per_pixel > 0
    differing = int(mask.sum())
    values, counts = np.unique(per_pixel[mask], return_counts=True)
    ys, xs = np.nonzero(mask)
    return {'differing_pixels': differing, 'fraction': differing / (ia.size[0] * ia.size[1]),
            'max_channel_delta': int(per_pixel.max()), 'delta_histogram': {int(v): int(n) for v, n in zip(values, counts)},
            'bbox': [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if xs.size else None, 'size': list(ia.size)}


# ------------------------------------------------------------- capture --

def replay_for(mode, warmup_ms, window_ms, windows):
    setup = MODE_SETUP[mode]
    return ch.replay_script(setup['seed'], PROFILE, warmup_ms + windows * window_ms + 1000, setup['replay_style'])


def capture(args):
    setup = MODE_SETUP[args.mode]
    replay = replay_for(args.mode, args.warmup_ms, args.window_ms, args.windows)
    settings = {'pass': 'timing', 'mode': args.mode, 'mode_name': ch.MODE_NAMES[args.mode], 'profile': PROFILE, 'viewport': VIEWPORT,
                'dpr': DPR, 'is_mobile': False, 'has_touch': False, 'input': 'mouse', 'cpu_throttle': args.cpu_throttle,
                'seed': setup['seed'], 'replay_style': setup['replay_style'], 'scene': args.scene, 'scene_label': SCENES[args.scene],
                'rep': args.rep, 'arm': args.arm, 'arm_label': ARMS[args.arm], 'ablate': [],
                'camera_drive': CAMERA_DRIVE.get(args.scene), 'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms,
                'windows': args.windows, 'replay_sha256': fc.replay_sha256(replay), 'diagnostic': False,
                'density': 'pinned to DPR 1; adaptive observe disabled',
                'instrumentation': 'timing arm: rAF intervals + read-only sampler only; no counters, no readback, no tracing, '
                                   'no tile-row observer',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                                 'PLATFORM falls back to the local adapter (no ads, instant restart on death)'}
    root, raw = common_raw(args, {'settings': settings, 'replay': replay})
    cfg = {'dpr': DPR, 'input': 'mouse', 'ablate': [], 'diagnostic': False, 'replay': replay,
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    exit_code = 1
    with ExitStack() as stack:
        page = open_page(stack, root, raw, VIEWPORT, DPR, setup['seed'], 'chromium', args.cpu_throttle)
        page.evaluate(fc.INSTRUMENT, cfg)
        if args.arm == 'candidate':
            raw['candidate_installed'] = page.evaluate(INSTALL_CANDIDATE, candidate_text())
        page.evaluate(ch.SAMPLER)
        if settings['camera_drive']:
            page.evaluate(cp.CAMERA_DRIVE, dict(settings['camera_drive'], label=SCENES[args.scene]))
        raw['candidate_present_in_page'] = page.evaluate(CANDIDATE_PRESENT)
        raw['observers_absent'] = page.evaluate('() => !window.__backgroundRowsObserve && !window.__visual')
        page.evaluate('mode => startGame(mode)', args.mode)
        try:
            page.wait_for_function(f'{fc.MARKER}.done || {fc.MARKER}.error', timeout=args.timeout_ms)
        except Exception as e:
            raw['errors'].append('timeout: ' + str(e).splitlines()[0])
        page.evaluate(f'() => {{ {fc.MARKER}.cfg.replay = "<see raw.replay>" }}')
        raw.update(page.evaluate(fc.MARKER))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['candidate_present_in_page_end'] = page.evaluate(CANDIDATE_PRESENT)
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
          raw['result'], 'backing=%s' % raw['dimensions']['canvas'],
          'fps=%.2f mean_ms=%.2f p50=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], 1000 / c['average_fps'], c['frame_ms']['p50'], c['active_ms'], raw['summary']['deaths']) if c else '',
          'camera_travel=%.0f moving=%.2f' % (d['camera']['travel_px'], d['camera']['moving_fraction'] or 0) if d else '',
          'drive_frames=%s' % (raw.get('cameraDrive') or {}).get('frames'), flush=True)
    return exit_code


def check_capture(raw):
    if raw['errors'] or raw.get('error'):
        raise fc.EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw.get('error')]))
    if raw['dimensions']['platform'] not in ('disabled', 'absent'):
        raise fc.EvidenceError('SDK isolation failed: ' + str(raw['dimensions']['platform']))
    if raw['dimensions']['version'] != raw['settings']['mode']:
        raise fc.EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
    if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
        raise fc.EvidenceError('backing size changed during the capture')
    if raw['dimensions']['canvas'] != [round(VIEWPORT[0] * DPR), round(VIEWPORT[1] * DPR)]:
        raise fc.EvidenceError('unexpected backing ' + str(raw['dimensions']['canvas']))
    if raw['settings']['arm'] == 'candidate' and not (raw.get('candidate_installed') and raw.get('candidate_present_in_page_end')):
        raise fc.EvidenceError('candidate arm without the candidate installed')
    if raw['settings']['arm'] == 'current' and (raw.get('candidate_present_in_page') or raw.get('candidate_present_in_page_end')):
        raise fc.EvidenceError('current arm with candidate methods present')
    if raw.get('tree_has_candidate_methods'):
        raise fc.EvidenceError('served tree already carries the candidate methods: arms would not differ')
    if raw['settings']['instrumentation'].find('no readback') < 0 or 'stage_profile' in raw or not raw.get('observers_absent'):
        raise fc.EvidenceError('timing raw carries instrumentation')


def check_scene(raw):
    drive = raw.get('cameraDrive')
    scene = raw['settings']['scene']
    if scene == 'replay':
        if drive:
            raise fc.EvidenceError('camera drive present in the replay scene')
        return
    if not drive or drive['frames'] < raw['summary']['combined']['frames']:
        raise fc.EvidenceError('camera drive missing or fewer drive frames than active frames')
    ys = {o[1] for o in drive['offsets']}
    if scene == 'moving-x' and ys != {0}:
        raise fc.EvidenceError('moving-x drive moved y: ' + str(sorted(ys)[:5]))


# ----------------------------------------------------------------- run --

def receipt(out, label, argv, exit_code, t0, t1):
    with (Path(out) / 'commands.jsonl').open('a') as f:
        f.write(json.dumps({'label': label, 'argv': argv, 'utc_start': t0, 'utc_end': t1, 'exit_code': exit_code}) + '\n')


def run_cmd(out, label, argv):
    t0 = utc()
    code = subprocess.call(argv, cwd=ROOT)
    receipt(out, label, argv, code, t0, utc())
    return code


def run(args):
    out = Path(args.output).resolve()
    root = ch.verified_root(out)
    if runtime_has_candidate(root):
        raise SystemExit('served tree already carries the candidate: integrate only after ACCEPT')
    base = [sys.executable, str(MODULE)]
    code = run_cmd(out, 'visual', base + ['visual', '--root', root, '--output', str(out)] +
                   (['--engines'] + list(args.engines) if args.engines else []))
    vv = build_visual(out)
    fc.dump(out / 'visual-validation.json', vv)
    if not vv['exact_on_all_tested_engines']:
        fc.dump(out / 'timings.json', {'task': TASK, 'utc': utc(), 'result': 'OMITTED',
                                       'reason': 'visual validation failed: ' + '; '.join(vv['failures'][:10]),
                                       'pairs': {}, 'rule': timing_rule()})
        print('FAIL visual validation; timing omitted', flush=True)
        return 1
    if args.skip_timing:
        return code
    for mode in MODES:
        for i, (scene, rep, arm) in enumerate(SEQUENCE):
            case = case_name(mode, scene, rep, arm, i)
            argv = base + ['capture', '--root', root, '--output', str(out), '--mode', mode, '--scene', scene, '--rep', rep,
                           '--arm', arm, '--case', case, '--warmup-ms', str(args.warmup_ms), '--window-ms', str(args.window_ms),
                           '--windows', str(args.windows), '--cpu-throttle', str(args.cpu_throttle)]
            c = run_cmd(out, 'capture', argv)
            if c != 0:
                c = run_cmd(out, 'capture-retry', argv)
            code = code or c
    return code


# -------------------------------------------------------------- report --

def load_visual(out):
    folder = Path(out) / 'visual'
    return {f'visual/{p.name}': fc.load(p) for p in sorted(folder.glob('*.json'))} if folder.exists() else {}


def complete_visual(raws, case):
    """The latest-started COMPLETE record of a case (earlier attempts stay preserved; '.attemptN' names sort
    before the first attempt alphabetically, so the start time decides, not the path)."""
    matches = [(p, r) for p, r in raws.items() if r.get('case') == case and r.get('result') == 'COMPLETE']
    return max(matches, key=lambda m: m[1].get('started_utc', '')) if matches else (None, None)


def state_digest(state):
    return {k: state.get(k) for k in STATE_KEYS}


def rows_summary(samples):
    """Mean clip fraction per tile over the gameplay frames of one arm (current arm: no tile info, clip = 1)."""
    game = [s for s in samples if s[1] is not None]
    out = {'frames': len(game)}
    for tile in TILES:
        clips = [s[4][tile] for s in game if s[4] and s[4].get(tile) is not None]
        applied = [s[4].get(tile + 'Applied') for s in game if s[4] and s[4].get(tile) is not None]
        applied = [a for a in applied if a is not None]
        out[tile] = {'frames_with_clip': len(clips), 'mean_clip_fraction': statistics.fmean(clips) if clips else None,
                     'min_clip_fraction': min(clips) if clips else None, 'max_clip_fraction': max(clips) if clips else None,
                     'clip_applied_fraction': (sum(1 for a in applied if a) / len(applied)) if applied else None,
                     'mean_clip_fraction_when_applied': statistics.fmean(c for c, a in zip(clips, applied) if a) if any(applied) else None}
    clips = [out[t]['mean_clip_fraction'] for t in TILES if out[t]['mean_clip_fraction'] is not None]
    out['copy_area_fraction_sum_over_tiles'] = sum(clips) if clips else None
    out['tile_pass_equivalents_removed'] = (len(TILES) - sum(clips)) if len(clips) == len(TILES) else None
    return out


def content_rows_summary(checkpoints):
    """Content rows recorded by the candidate at each checkpoint (per tile size)."""
    out = {}
    for c in checkpoints:
        rows = (c.get('candidate') or {}).get('contentRows') or {}
        for tile in TILES:
            r = rows.get(tile)
            if r:
                key = f'{tile}@{r["rows"]}'
                out[key] = {'tile': tile, 'rows': r['rows'], 'runs': r['runs'], 'run_count': len(r['runs']),
                            'transparent_rows': r['transparentRows'], 'transparent_fraction': r['transparentRows'] / r['rows']}
    return out


def build_visual(out):
    out = Path(out)
    raws = load_visual(out)
    cells, failures, coverage = {}, [], {'moving_camera': False, 'trails_or_sparks': False, 'shake': False, 'player_exclusion': False,
                                         'menu_start': False, 'settled_resize': False, 'odd_backing': False, 'letterbox_bars': False,
                                         'dpr2_backing': False}
    engines_tested = set()
    for key in sorted({(r['settings']['engine'], r['settings']['context'], r['settings']['mode'], r['settings']['seed'])
                       for r in raws.values() if 'engine' in r.get('settings', {})}):
        engine, context, mode, seed = key
        cur_p, cur = complete_visual(raws, visual_case({'engine': engine, 'context': context, 'mode': mode, 'seed': seed, 'arm': 'current'}))
        cand_p, cand = complete_visual(raws, visual_case({'engine': engine, 'context': context, 'mode': mode, 'seed': seed, 'arm': 'candidate'}))
        name = f'{engine}/{context}/{mode}/seed{seed}'
        cell = {'engine': engine, 'context': context, 'mode': mode, 'seed': seed, 'current': cur_p, 'candidate': cand_p,
                'checkpoints': [], 'result': None}
        if not cur or not cand:
            cell['result'] = 'INCOMPLETE'
            if engine == 'chromium':
                failures.append(f'{name}: missing COMPLETE arm(s)')
            else:
                cell['result'] = 'ENGINE_UNAVAILABLE'
            cells[name] = cell
            continue
        engines_tested.add(engine)
        ok = True
        if cur['settings']['replay_sha256'] != cand['settings']['replay_sha256']:
            ok = False
            failures.append(f'{name}: replay differs')
        for a, b in zip(cur['checkpoints'], cand['checkpoints']):
            sa, sb = state_digest(a['state']), state_digest(b['state'])
            cp_entry = {'name': a['name'], 'scene': a['scene'], 'final_equal': pixels_equal(a, b, 'final'),
                        'source_equal': pixels_equal(a, b, 'source'), 'bars_equal': bars_equal(a, b), 'state_equal': sa == sb,
                        'final_png_bytes_equal': a['final_sha256'] == b['final_sha256'],
                        'final_pixels_sha256': a.get('final_pixels_sha256'), 'candidate_final_pixels_sha256': b.get('final_pixels_sha256'),
                        'source_pixels_sha256': a.get('source_pixels_sha256'), 'candidate_source_pixels_sha256': b.get('source_pixels_sha256'),
                        'bars_count': [a.get('bars_count'), b.get('bars_count')],
                        'comparison_unit': 'decoded RGBA pixels' if a.get('final_pixels_sha256') else 'PNG bytes',
                        'final_sha256': a['final_sha256'], 'candidate_final_sha256': b['final_sha256'],
                        'candidate_tiles': (b.get('candidate') or {}).get('scratchTiles'),
                        'candidate_content_rows': (b.get('candidate') or {}).get('contentRows'),
                        'backing': a['state']['canvas'], 'css': a['state']['css'], 'logical': a['state']['logical'],
                        'screen': a['state']['screen'], 'particles': a['state']['particles'], 'track_points': a['state']['trackPoints'],
                        'shaking': a['state']['shaking'], 'player_glow': a['state']['playerGlow'], 'bars_visible': a['state']['barsVisible'],
                        'menu': a['state']['menu'], 'random_draws': a['state']['randomDraws'], 'tile_keys': a['state'].get('tileKeys'),
                        'layer_shift': a['state'].get('layerShift')}
            if not cp_entry['state_equal']:
                cp_entry['state_differences'] = {k: [sa[k], sb[k]] for k in STATE_KEYS if sa[k] != sb[k]}
            if not (cp_entry['final_equal'] and cp_entry['source_equal'] and cp_entry['bars_equal'] and cp_entry['state_equal']):
                ok = False
                failures.append(f'{name}/{a["name"]}: final_equal={cp_entry["final_equal"]} source_equal={cp_entry["source_equal"]} '
                                f'bars_equal={cp_entry["bars_equal"]} state_equal={cp_entry["state_equal"]}')
                pa = out / 'visual/png' / f'{cur["case"]}-{a["name"]}.png'
                pb = out / 'visual/png' / f'{cand["case"]}-{b["name"]}.png'
                if pa.exists() and pb.exists():
                    cp_entry['final_diff'] = png_diff(pa, pb)
                    cp_entry['final_png'] = [str(pa.relative_to(out)), str(pb.relative_to(out))]
                sa_p = out / 'visual/png' / f'{cur["case"]}-{a["name"]}-source.png'
                sb_p = out / 'visual/png' / f'{cand["case"]}-{b["name"]}-source.png'
                if sa_p.exists() and sb_p.exists():
                    cp_entry['source_diff'] = png_diff(sa_p, sb_p)
            cell['checkpoints'].append(cp_entry)
            st = a['state']
            if st['menu']:
                coverage['menu_start'] = True
            if st['shaking']:
                coverage['shake'] = True
            if (st['particles'] or 0) > 0 or (st['trackPoints'] or 0) > 1:
                coverage['trails_or_sparks'] = True
            if st['playerGlow'] and not st['menu']:
                coverage['player_exclusion'] = True
            if st['barsVisible']:
                coverage['letterbox_bars'] = True
            if st['canvas'][0] % 2 or st['canvas'] not in ([1280, 720], [2560, 1440], [960, 540], [1920, 1080], [640, 480], [1280, 960]):
                coverage['odd_backing'] = True
            if st['canvas'] == [2560, 1440]:
                coverage['dpr2_backing'] = True
        if len(cur['checkpoints']) != len(cand['checkpoints']):
            ok = False
            failures.append(f'{name}: checkpoint count differs')
        screens = [c['state']['screen'] for c in cur['checkpoints'] if c['state']['screen']]
        if len({tuple(s) for s in screens}) > 1:
            coverage['moving_camera'] = True
        resized = [r for r in cur['resizes'] if r['handler_seen'] and r['backing_equals_round_css_times_dpr']]
        if resized:
            coverage['settled_resize'] = True
        cell['resizes'] = [{'requested': r['requested'], 'handler_seen': r['handler_seen'], 'backing': r['dimensions']['canvas'],
                            'css': r['dimensions']['css'], 'logical': r['dimensions']['logical'],
                            'backing_equals_round_css_times_dpr': r['backing_equals_round_css_times_dpr']} for r in cur['resizes']]
        cell['samples_frames'] = len(cur.get('samples', []))
        cell['camera'] = camera_dependency(cur.get('samples', []))
        cell['rows_current'] = rows_summary(cur.get('samples', []))
        cell['rows_candidate'] = rows_summary(cand.get('samples', []))
        cell['content_rows_candidate'] = content_rows_summary(cand['checkpoints'])
        cell['candidate_rows_calls'] = cand.get('rowsCalls')
        cell['candidate_clipped_calls'] = cand.get('clippedCalls')
        cell['current_rows_calls'] = cur.get('rowsCalls')
        cell['random_draws_equal'] = cur.get('randomDraws') == cand.get('randomDraws')
        if not cell['random_draws_equal']:
            ok = False
            failures.append(f'{name}: Math.random draw counts differ {cur.get("randomDraws")} vs {cand.get("randomDraws")}')
        if not cand.get('rowsCalls'):
            ok = False
            failures.append(f'{name}: the candidate tile hook never ran')
        if cur.get('rowsCalls'):
            ok = False
            failures.append(f'{name}: tile hook ran in the current arm')
        cell['result'] = 'EXACT' if ok else 'DIFFERENT'
        cells[name] = cell
    differences = []
    for c in cells.values():
        for cp_entry in c['checkpoints']:
            if not (cp_entry['final_equal'] and cp_entry['source_equal'] and cp_entry['bars_equal'] and cp_entry['state_equal']):
                differences.append({'cell': f"{c['engine']}/{c['context']}/{c['mode']}/seed{c['seed']}", 'checkpoint': cp_entry['name'],
                                    'final_equal': cp_entry['final_equal'], 'source_equal': cp_entry['source_equal'],
                                    'bars_equal': cp_entry['bars_equal'], 'state_equal': cp_entry['state_equal'],
                                    'final_diff': cp_entry.get('final_diff'), 'source_diff': cp_entry.get('source_diff'),
                                    'explained': False})
    chromium_cells = [c for c in cells.values() if c['engine'] == 'chromium']
    exact = bool(chromium_cells) and all(c['result'] == 'EXACT' for c in cells.values() if c['result'] not in ('ENGINE_UNAVAILABLE',))
    required = {'dpr1': {(m, s) for m in MODES for s in VISUAL_SEEDS}, 'dpr2': {(m, 4) for m in MODES}}
    have = {ctx: {(c['mode'], c['seed']) for c in chromium_cells if c['context'] == ctx and c['result'] in ('EXACT', 'DIFFERENT')} for ctx in required}
    complete_matrix = all(required[ctx] <= have[ctx] for ctx in required)
    if not complete_matrix:
        failures.append('chromium matrix incomplete: ' + json.dumps({k: sorted(required[k] - have[k]) for k in required}))
    exact = exact and all(c['result'] == 'EXACT' for c in chromium_cells)
    return {'task': TASK, 'utc': utc(), 'arms': ARMS, 'comparison': 'candidate (page-injected) versus the current runtime served from the '
            'same tree, same seed/replay/clock/frame schedule; never different historical artwork',
            'method': 'synthetic 60 Hz clock, harness-driven gameLoop; per checkpoint: final canvas decoded-pixel sha256, decoded-pixel '
                      'sha256 of a background-only scratch paint by the arm\'s own BackgroundRenderer (source), decoded-pixel sha256 of '
                      'every visible bar canvas, gameplay-state digest (%d keys); readback confined to this pass' % len(STATE_KEYS),
            'engines_tested': sorted(engines_tested), 'engines_planned': list(VISUAL_ENGINES),
            'exact_on_all_tested_engines': exact and complete_matrix, 'complete_matrix': complete_matrix,
            'coverage': coverage, 'coverage_complete': all(coverage.values()), 'failures': failures, 'cells': cells,
            'differences': differences,
            'difference_explanation': 'no pixel or state differences' if not differences else
                                      'UNEXPLAINED differences present: see differences[]; the candidate is rejected',
            'all_differences_explained': False if differences else True,
            'raw_count': len(raws), 'complete_count': sum(1 for r in raws.values() if r.get('result') == 'COMPLETE'),
            'failed_attempts': sorted(p for p, r in raws.items() if r.get('result') != 'COMPLETE'),
            'separate_from_timing': True}


def camera_dependency(samples):
    """Per-frame camera change rates from [frame, sx, sy, moteHash, tiles, canvas] samples (gameplay frames only)."""
    game = [s for s in samples if s[1] is not None]
    pairs = list(zip(game, game[1:]))
    if not pairs:
        return {'frames': len(game), 'pairs': 0}
    dx = sum(1 for a, b in pairs if a[1] != b[1])
    dy = sum(1 for a, b in pairs if a[2] != b[2])
    return {'frames': len(game), 'pairs': len(pairs), 'x_changed_fraction': dx / len(pairs), 'y_changed_fraction': dy / len(pairs),
            'x_range': [min(s[1] for s in game), max(s[1] for s in game)]}


def build_rows(out, vv):
    """Measured redundant-update evidence: per cell the tile content rows and the clipped copy area per frame."""
    src = (ROOT / 'render/effects.js').read_text().splitlines()
    source_lines = {}
    for marker in ('this.clearAll()', 'this.drawBaseGradient(width, height)', 'this.ctx.drawImage(layer.canvas, left, shift.y, next - left, height)',
                   'drawLayerTile(layer, width, height, shift, edgeFill)', 'ctx.fillRect(0, height * 0.988, width, height * 0.012)'):
        for i, l in enumerate(src, 1):
            if marker in l:
                source_lines[marker] = f'render/effects.js:{i}'
                break
    cells = {}
    for k, c in vv['cells'].items():
        if not c.get('rows_candidate'):
            continue
        cells[k] = {'current': c['rows_current'], 'candidate': c['rows_candidate'], 'content_rows': c.get('content_rows_candidate'),
                    'frames': c.get('samples_frames'), 'camera': c.get('camera')}
    summary = {}
    for tile in TILES:
        rows = [c['candidate'][tile] for c in cells.values() if c['candidate'].get(tile) and c['candidate'][tile]['mean_clip_fraction'] is not None]
        fractions = sorted({(v['rows'], round(v['transparent_fraction'], 4)) for c in cells.values() for v in (c.get('content_rows') or {}).values()
                            if v['tile'] == tile})
        summary[tile] = {'cells': len(rows),
                         'mean_clip_fraction_of_copy_area': statistics.fmean(r['mean_clip_fraction'] for r in rows) if rows else None,
                         'clip_applied_fraction_by_cell': {k: c['candidate'][tile].get('clip_applied_fraction') for k, c in cells.items() if c['candidate'].get(tile)},
                         'mean_clip_fraction_when_applied_by_cell': {k: c['candidate'][tile].get('mean_clip_fraction_when_applied') for k, c in cells.items() if c['candidate'].get(tile)},
                         'clip_fraction_range': [min(r['min_clip_fraction'] for r in rows), max(r['max_clip_fraction'] for r in rows)] if rows else None,
                         'transparent_row_fraction_by_tile_height': [{'rows': r, 'transparent_fraction': f} for r, f in fractions]}
    removed = [c['candidate']['tile_pass_equivalents_removed'] for c in cells.values() if c['candidate'].get('tile_pass_equivalents_removed') is not None]
    return {'task': TASK, 'utc': utc(),
            'question': 'how much of the two full-frame tile copies does the row clip remove, and how many rows of each tile are transparent?',
            'source_lines': source_lines,
            'unit': 'fractions of the copy area (device rows inside the clip bands / device rows of the fill bounds); 1.0 = unclipped',
            'cells': cells, 'summary': summary,
            'tile_pass_equivalents_removed_per_cell': removed,
            'clear_pass': 'kept: the shipped clearRect runs unchanged in both arms (an earlier smoke variant that skipped it was not '
                          'exact in bad mode; see hypothesis.json rejected_designs_isolated)',
            'expected_from_hypothesis': 'far 0.79 / near 0.50 of the copy area, about 0.72 tile passes removed per frame',
            'measured_background_cost_ms': MEASURED_TARGET['cave_background_off_median_saving_ms'],
            'note': 'area is the mechanism\'s own measure of removed work; whether raster time follows area is what timings.json tests'}


def timing_rule():
    return {'acceptance_scenes': list(ACCEPTANCE_SCENES), 'no_worse_scenes': list(NO_WORSE_SCENES),
            'min_median_reduction': MIN_MEDIAN_REDUCTION, 'max_worse': MAX_WORSE,
            'statement': f'ACCEPT timing iff, in BOTH modes, the median over the 3 alternating 30 s replay pairs of '
                         f'(control mean active frame ms - candidate mean) / control mean >= {MIN_MEDIAN_REDUCTION:.0%}, and no replay or '
                         f'moving-x pair has the candidate worse by more than {MAX_WORSE:.0%}. Modes and repetitions are never pooled.'}


def mean_ms(raw):
    c = raw['summary']['combined']
    return c['active_ms'] / c['intervals']


def pair_record(control, candidate):
    a, b = mean_ms(control), mean_ms(candidate)
    return {'control': control['case'], 'candidate': candidate['case'], 'control_mean_ms': a, 'candidate_mean_ms': b,
            'control_p50_ms': control['summary']['combined']['frame_ms']['p50'], 'candidate_p50_ms': candidate['summary']['combined']['frame_ms']['p50'],
            'reduction_ms': a - b, 'reduction_fraction': (a - b) / a, 'worse_by_fraction': max(0.0, (b - a) / a),
            'control_fps': control['summary']['combined']['average_fps'], 'candidate_fps': candidate['summary']['combined']['average_fps'],
            'order': 'control first' if control['started_utc'] < candidate['started_utc'] else 'candidate first',
            'backing': control['dimensions']['canvas'],
            'control_camera': control['density']['camera'] if control.get('density') else None,
            'candidate_camera': candidate['density']['camera'] if candidate.get('density') else None,
            'control_deaths': control['summary']['deaths'], 'candidate_deaths': candidate['summary']['deaths'],
            'candidate_drive_frames': (candidate.get('cameraDrive') or {}).get('frames'),
            'window_active_ms': [control['summary']['combined']['active_ms'], candidate['summary']['combined']['active_ms']]}


def build_timings(out):
    raws = {f'raw/{p.name}': fc.load(p) for p in sorted((Path(out) / 'raw').glob('*.json'))} if (Path(out) / 'raw').exists() else {}
    complete = {}
    for p, r in raws.items():
        if r.get('result') == 'COMPLETE':
            complete[(r['settings']['mode'], r['settings']['scene'], r['settings']['rep'], r['settings']['arm'])] = r
    modes = {}
    for mode in MODES:
        scenes = {}
        for scene in SCENES:
            pairs = []
            for rep in REPS:
                c, k = complete.get((mode, scene, rep, 'current')), complete.get((mode, scene, rep, 'candidate'))
                if c and k:
                    fc.compare(c, k)  # refuses mismatched settings or backing
                    pairs.append(dict(pair_record(c, k), rep=rep))
            if pairs:
                reductions = [p['reduction_fraction'] for p in pairs]
                scenes[scene] = {'label': SCENES[scene], 'pairs': pairs, 'pair_count': len(pairs),
                                 'median_reduction_fraction': statistics.median(reductions),
                                 'median_reduction_ms': statistics.median(p['reduction_ms'] for p in pairs),
                                 'max_worse_fraction': max(p['worse_by_fraction'] for p in pairs),
                                 'all_reductions_fraction': reductions}
        acc = scenes.get('replay')
        no_worse = [p for s in NO_WORSE_SCENES if s in scenes for p in scenes[s]['pairs']]
        verdict = None
        if acc and acc['pair_count'] == len(REPS):
            ok_median = acc['median_reduction_fraction'] >= MIN_MEDIAN_REDUCTION
            ok_worse = all(p['worse_by_fraction'] <= MAX_WORSE for p in no_worse) and 'moving-x' in scenes
            verdict = 'PASS' if ok_median and ok_worse else ('IMMATERIAL' if not ok_median and ok_worse else 'INCONSISTENT')
        modes[mode] = {'mode_name': ch.MODE_NAMES[mode], 'scenes': scenes, 'verdict': verdict,
                       'median_reduction_fraction_replay': acc['median_reduction_fraction'] if acc else None,
                       'worst_pair_worse_fraction_gameplay': max((p['worse_by_fraction'] for p in no_worse), default=None)}
    result = 'PASS' if all(m['verdict'] == 'PASS' for m in modes.values()) else (
        'INCOMPLETE' if any(m['verdict'] is None for m in modes.values()) else 'FAIL')
    return {'task': TASK, 'utc': utc(), 'result': result, 'rule': timing_rule(), 'modes': modes,
            'protocol': {'window_ms': sorted({r['settings']['window_ms'] for r in raws.values() if 'settings' in r}),
                         'warmup_ms': sorted({r['settings']['warmup_ms'] for r in raws.values() if 'settings' in r}),
                         'sequence': SEQUENCE, 'viewport': VIEWPORT, 'dpr': DPR, 'cpu_throttle': sorted({r['settings']['cpu_throttle'] for r in raws.values() if 'settings' in r}),
                         'untraced': 'rAF intervals + read-only sampler; no readback, no tracing, no counters, no observers',
                         'metric': 'mean active frame ms = active_ms / intervals over the 30 s window (recomputed from raw frames)'},
            'raw_count': len(raws), 'complete_count': len(complete),
            'failed_attempts': sorted(p for p, r in raws.items() if r.get('result') != 'COMPLETE')}


def decide(vv, timings):
    reasons = []
    visual_ok = vv.get('exact_on_all_tested_engines', False)
    if not visual_ok:
        reasons.append('visual validation not exact/complete: ' + '; '.join(vv.get('failures', [])[:6]))
    timing_ok = timings.get('result') == 'PASS'
    if timings.get('result') == 'OMITTED':
        reasons.append('timing omitted: ' + timings.get('reason', ''))
    elif not timing_ok:
        for mode, m in timings.get('modes', {}).items():
            if m['verdict'] != 'PASS':
                reasons.append(f'{mode}: timing {m["verdict"]} (median replay reduction '
                               f'{m["median_reduction_fraction_replay"] if m["median_reduction_fraction_replay"] is None else round(m["median_reduction_fraction_replay"], 4)}, '
                               f'worst gameplay pair worse by {m["worst_pair_worse_fraction_gameplay"]})')
    verdict = 'ACCEPT' if visual_ok and timing_ok else 'REJECT'
    return {'task': TASK, 'utc': utc(), 'verdict': verdict,
            'verdict_meaning': {'ACCEPT': 'visuals exact on every tested engine and timing passes in both modes: integrate the candidate '
                                          'body into render/effects.js and link the hashes',
                                'REJECT': 'the candidate is not integrated; the shipping runtime stays unchanged (a valid negative experiment: '
                                          'the measured reduction is below the threshold or the visuals are not exact)',
                                'NO_CANDIDATE': 'not applicable: a candidate existed and was tested'}[verdict],
            'reasons': reasons, 'visual': {'exact_on_all_tested_engines': visual_ok, 'engines_tested': vv.get('engines_tested'),
                                           'coverage': vv.get('coverage'), 'cells': {k: c['result'] for k, c in vv.get('cells', {}).items()}},
            'timing': {'result': timings.get('result'), 'modes': {m: {'verdict': v['verdict'],
                                                                      'median_reduction_fraction_replay': v['median_reduction_fraction_replay'],
                                                                      'worst_pair_worse_fraction_gameplay': v['worst_pair_worse_fraction_gameplay']}
                                                                  for m, v in timings.get('modes', {}).items()}},
            'candidate': {'file': str(CANDIDATE.relative_to(ROOT)), 'sha256': candidate_sha(), 'body_sha256': body_sha()},
            'integration': integration_status(verdict),
            'ticket_completion_is_not_60fps_acceptance': True,
            'not_claimed': ['60 FPS', 'release readiness', 'device results']}


def integration_status(verdict):
    src = (ROOT / 'render/effects.js').read_text()
    in_runtime = runtime_has_candidate(ROOT)
    runtime_body = runtime_body_sha(ROOT)
    cand = body_sha()
    linked = in_runtime and runtime_body is not None and runtime_body == cand
    return {'runtime_has_candidate_methods': in_runtime, 'runtime_body_sha256': runtime_body, 'candidate_body_sha256': cand,
            'tested_bodies_equal_runtime_bodies': linked,
            'consistent_with_verdict': (verdict == 'ACCEPT' and linked) or (verdict != 'ACCEPT' and not in_runtime),
            'head': fc.git('rev-parse', 'HEAD'), 'effects_js_sha256': fc.sha_bytes(src.encode())}


def build_manifest(out, vv, timings, decision):
    identity = fc.load(out / 'identity.json')
    commands = [json.loads(l) for l in (out / 'commands.jsonl').read_text().splitlines() if l.strip()] if (out / 'commands.jsonl').exists() else []
    raws = {f'raw/{p.name}': fc.load(p) for p in sorted((out / 'raw').glob('*.json'))} if (out / 'raw').exists() else {}
    visuals = load_visual(out)
    pngs = sorted(f'visual/png/{p.name}' for p in (out / 'visual/png').glob('*.png')) if (out / 'visual/png').exists() else []
    evidence = sorted(list(raws) + list(visuals) + pngs + ['identity.json', 'hypothesis.json', 'hypothesis-initial.json', 'commands.jsonl'] +
                      sorted(f'{MODULE_AT_CAPTURE}/{p.name}' for p in (out / MODULE_AT_CAPTURE).glob('*')))
    evidence = [p for p in evidence if (out / p).exists()]
    everything = list(raws.values()) + list(visuals.values())
    envs = [r['environment'] for r in everything if r.get('environment')]
    starts = [r['started_utc'] for r in everything] + [c['utc_start'] for c in commands] + [identity['utc_start']]
    ends = [r['ended_utc'] for r in everything if r.get('ended_utc')] + [c['utc_end'] for c in commands] + [identity['utc_end']]
    return {'task': TASK, 'generated_utc': utc(), 'utc_start': min(starts), 'utc_end': max(ends),
            'commands': [{k: c[k] for k in ('label', 'argv', 'utc_start', 'utc_end', 'exit_code')} for c in commands],
            'exit_codes': sorted({c['exit_code'] for c in commands}),
            'environment': envs[0] if envs else None, 'environments_by_engine': {e['engine']: e for e in envs},
            'environment_ceiling': identity['environment_ceiling'],
            'source_revision': identity['identity']['current_commit'], 'source_dirty_runtime': identity['identity']['current_dirty_runtime'],
            'source_revision_at_report': fc.git('rev-parse', 'HEAD'), 'current_tar_sha256': identity['identity']['current_tar_sha256'],
            'tree_files_sha256': identity['identity']['current_files_sha256'],
            'harness_sha256': identity['harness_sha256'], 'chill_sha256': identity['chill_sha256'], 'cache_profile_sha256': identity['cache_profile_sha256'],
            'support_sha256': identity['support_sha256'], 'module_sha256_at_report': fc.sha_file(MODULE),
            'module_sha256_at_capture': sorted({r['module_sha256'] for r in everything if 'module_sha256' in r}),
            'candidate_sha256_at_report': candidate_sha(), 'candidate_sha256_at_capture': sorted({r['candidate_sha256'] for r in everything if 'candidate_sha256' in r}),
            'candidate_body_sha256_at_report': body_sha(),
            'candidate_body_sha256_at_capture': sorted({r['candidate_body_sha256'] for r in everything if 'candidate_body_sha256' in r}),
            'module_at_capture': sorted(p.name for p in (out / MODULE_AT_CAPTURE).glob('*')),
            'fixed': {'timing': {'viewport_css': VIEWPORT, 'dpr': DPR, 'backing_size_by_case': {r['case']: r['dimensions']['canvas'] for r in raws.values() if r.get('dimensions')},
                                 'modes': list(MODES), 'seeds': {m: MODE_SETUP[m]['seed'] for m in MODES}, 'replay_styles': {m: MODE_SETUP[m]['replay_style'] for m in MODES},
                                 'replay_sha256': sorted({r['settings']['replay_sha256'] for r in raws.values() if 'settings' in r}),
                                 'scenes': SCENES, 'camera_drive': CAMERA_DRIVE, 'sequence': SEQUENCE,
                                 'cpu_throttle': sorted({r['settings']['cpu_throttle'] for r in raws.values() if 'settings' in r}),
                                 'warmup_ms': sorted({r['settings']['warmup_ms'] for r in raws.values() if 'settings' in r}),
                                 'window_ms': sorted({r['settings']['window_ms'] for r in raws.values() if 'settings' in r}),
                                 'input': 'mouse (dispatched mousedown/mouseup on the active clock)',
                                 'state': 'fresh page per capture, seeded Math.random, menu -> startGame(mode); candidate arm installs the '
                                          'candidate before startGame'},
                      'visual': {'contexts': VISUAL_CONTEXTS, 'engines': VISUAL_ENGINES, 'seeds': list(VISUAL_SEEDS),
                                 'backing_size_by_case': {r['case']: sorted({tuple(c['state']['canvas']) for c in r.get('checkpoints', [])})
                                                          for r in visuals.values() if r.get('checkpoints')},
                                 'clock': 'synthetic 60 Hz, performance.now pinned', 'input': 'seeded replay on the active clock',
                                 'state': 'fresh page per session; menu checkpoint, startGame(mode), harness-driven frames, forced '
                                          'triggerDeath shake, Playwright viewport resizes settled past the 100 ms debounce'}},
            'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter',
            'decision': decision['verdict'], 'visual_exact': vv.get('exact_on_all_tested_engines'), 'timing_result': timings.get('result'),
            'evidence_paths': evidence, 'sha256': {p: fc.sha_file(out / p) for p in evidence},
            'failed_attempts_preserved': [p for p in evidence if ((p in raws and raws[p].get('result') != 'COMPLETE') or
                                                                  (p in visuals and visuals[p].get('result') != 'COMPLETE'))],
            'note': 'A successful evidence audit is separate from the performance verdict (decision.json). Failed attempts are preserved, '
                    'never rewritten. Historical receipts are never fabricated.'}


def report(args):
    out = Path(args.output).resolve()
    vv = build_visual(out)
    fc.dump(out / 'visual-validation.json', vv)
    fc.dump(out / 'rows.json', build_rows(out, vv))
    if (out / 'timings.json').exists() and fc.load(out / 'timings.json').get('result') == 'OMITTED' and not (out / 'raw').exists():
        timings = fc.load(out / 'timings.json')
    else:
        timings = build_timings(out)
        fc.dump(out / 'timings.json', timings)
    decision = decide(vv, timings)
    fc.dump(out / 'decision.json', decision)
    fc.dump(out / 'manifest.json', build_manifest(out, vv, timings, decision))
    print('visual exact_on_all_tested_engines =', vv['exact_on_all_tested_engines'], 'engines', vv['engines_tested'],
          'coverage', json.dumps(vv['coverage']), 'failures', len(vv['failures']))
    for k, c in vv['cells'].items():
        rc = c.get('rows_candidate') or {}
        print('  ', k, c['result'], 'checkpoints', len(c['checkpoints']), 'candidate copy area far/near',
              [None if not rc.get(t) or rc[t]['mean_clip_fraction'] is None else round(rc[t]['mean_clip_fraction'], 3) for t in TILES],
              'tile passes removed', None if rc.get('tile_pass_equivalents_removed') is None else round(rc['tile_pass_equivalents_removed'], 3),
              'content rows', {k2: round(v['transparent_fraction'], 3) for k2, v in (c.get('content_rows_candidate') or {}).items()})
    print('timing', timings['result'])
    for mode, m in timings.get('modes', {}).items():
        print('  ', mode, m['verdict'], 'median replay reduction', m['median_reduction_fraction_replay'], 'worst gameplay worse', m['worst_pair_worse_fraction_gameplay'])
        for scene, s in m['scenes'].items():
            for p in s['pairs']:
                print('     %-9s %s control %.2f ms candidate %.2f ms reduction %+.2f%% (%s)' % (scene, p['rep'], p['control_mean_ms'], p['candidate_mean_ms'],
                                                                                              100 * p['reduction_fraction'], p['order']))
    print('DECISION', decision['verdict'], decision['reasons'])
    return 0


# --------------------------------------------------------------- audit --

def audit(args):
    out = Path(args.output).resolve()
    passes, failures = [], []

    def check(ok, msg):
        (passes if ok else failures).append(msg)
        if not ok:
            print('FAIL', msg)

    identity = fc.load(out / 'identity.json')
    hyp = fc.load(out / 'hypothesis.json')
    vv_file = fc.load(out / 'visual-validation.json')
    timings_file = fc.load(out / 'timings.json')
    decision_file = fc.load(out / 'decision.json')
    manifest = fc.load(out / 'manifest.json')
    variants = {fc.sha_file(p) for p in (out / MODULE_AT_CAPTURE).glob('*')}
    body_variants = {body_sha(p.read_text()) for p in (out / MODULE_AT_CAPTURE).glob('*.js')}
    check(hyp['candidate']['sha256'] in variants, 'hypothesis candidate sha preserved in module-at-capture')
    check(hyp['candidate']['body_sha256'] in body_variants, 'hypothesis candidate body sha preserved in module-at-capture')
    check(hyp['control']['current_commit'] == identity['identity']['current_commit'], 'hypothesis control == identity commit')
    # visual raws
    visuals = load_visual(out)
    for p, r in visuals.items():
        if r.get('result') != 'COMPLETE':
            check(True, f'{p}: failed attempt preserved ({r.get("result")})')
            continue
        s = r['settings']
        check(r['candidate_body_sha256'] == hyp['candidate']['body_sha256'], f'{p}: candidate body sha matches hypothesis')
        check(r['module_sha256'] in variants, f'{p}: module variant preserved')
        check(not r.get('tree_has_candidate_methods'), f'{p}: served tree had no candidate methods')
        check(r['tree']['files_sha256'] == identity['identity']['current_files_sha256'], f'{p}: served tree == identity tree')
        if s['arm'] == 'candidate':
            check(r.get('candidate_installed') and r.get('candidate_present_in_page_end') and r.get('rowsCalls'),
                  f'{p}: candidate installed and its tile hook ran in the candidate arm')
            # both tiles always have transparent rows, so every copy of the candidate arm is clipped
            check(r.get('clippedCalls') == r.get('rowsCalls'),
                  f'{p}: every tile copy clipped in the candidate arm (clippedCalls {r.get("clippedCalls")} == rowsCalls {r.get("rowsCalls")})')
        else:
            check(not r.get('candidate_present_in_page_end') and not r.get('rowsCalls'), f'{p}: no candidate in the current arm')
        for rz in r.get('resizes', []):
            check(rz['backing_equals_round_css_times_dpr'], f'{p}: resize {rz["requested"]} backing == round(css x dpr)')
        for c in r['checkpoints']:
            check(c['state']['dpr'] == s['dpr'], f'{p}/{c["name"]}: dpr pinned')
            check(bool(c.get('source_pixels_sha256') or c.get('source_sha256')), f'{p}/{c["name"]}: background-only source recorded')
            check(c.get('bars_count') == c['state']['barsVisible'], f'{p}/{c["name"]}: bar canvases recorded == bars visible ({c["state"]["barsVisible"]})')
            if s['arm'] == 'candidate':
                rows = (c.get('candidate') or {}).get('contentRows') or {}
                check(all(rows.get(t) and rows[t]['transparentRows'] > 0 for t in TILES), f'{p}/{c["name"]}: content rows recorded for both tiles')
    vv = build_visual(out)
    check(vv['exact_on_all_tested_engines'] == vv_file['exact_on_all_tested_engines'], 'visual verdict re-derived equals file')
    check({k: c['result'] for k, c in vv['cells'].items()} == {k: c['result'] for k, c in vv_file['cells'].items()}, 'visual cell results re-derived')
    check(vv['coverage'] == vv_file['coverage'], 'visual coverage re-derived')
    for k, c in vv['cells'].items():
        if c['result'] in ('EXACT', 'DIFFERENT'):
            check(c['rows_candidate'] == vv_file['cells'][k]['rows_candidate'], f'{k}: candidate rows summary re-derived')
    # timing raws
    raws = {f'raw/{p.name}': fc.load(p) for p in sorted((out / 'raw').glob('*.json'))} if (out / 'raw').exists() else {}
    for p, r in raws.items():
        if r.get('result') != 'COMPLETE':
            check(True, f'{p}: failed attempt preserved ({r.get("result")})')
            continue
        s = fc.summarize(r)
        check(abs(mean_ms(r) - s['combined']['active_ms'] / s['combined']['intervals']) < 1e-9 and s == r['summary'], f'{p}: summary recomputed from frames')
        check(r['frames_sha256'] == fc.frames_sha256(r['frames']), f'{p}: frames seal')
        check(s['combined']['active_ms'] >= r['settings']['window_ms'], f'{p}: window >= {r["settings"]["window_ms"]} ms active')
        check(r['dimensions']['canvas'] == [1280, 720] and all(f['canvas'] == [1280, 720] for f in r['frames']), f'{p}: backing 1280x720 constant')
        check('stage_profile' not in r and r.get('observers_absent') is True, f'{p}: no instrumentation/observers in timing raw')
        check(r['candidate_body_sha256'] == hyp['candidate']['body_sha256'], f'{p}: candidate body sha matches hypothesis')
        check(not r.get('tree_has_candidate_methods'), f'{p}: served tree had no candidate methods')
        try:
            check_capture(r); check_scene(r)
            check(True, f'{p}: capture/scene checks')
        except fc.EvidenceError as e:
            check(False, f'{p}: {e}')
        check(ch.window_density(r) == r['density'], f'{p}: density recomputed')
    if raws:
        timings = build_timings(out)
        for mode in MODES:
            a, b = timings['modes'][mode], timings_file['modes'][mode]
            check(a['verdict'] == b['verdict'] and a['median_reduction_fraction_replay'] == b['median_reduction_fraction_replay'], f'{mode}: timing verdict re-derived')
            for scene, sc in a['scenes'].items():
                check([p['reduction_fraction'] for p in sc['pairs']] == [p['reduction_fraction'] for p in b['scenes'][scene]['pairs']], f'{mode}/{scene}: pair reductions re-derived')
        check(timings['result'] == timings_file['result'], 'timing result re-derived')
    else:
        timings = timings_file
        check(timings['result'] == 'OMITTED' and not vv['exact_on_all_tested_engines'], 'timing omitted only because visuals failed')
    decision = decide(vv, timings)
    check(decision['verdict'] == decision_file['verdict'], f'decision re-derived: {decision["verdict"]}')
    check(decision['integration']['consistent_with_verdict'], 'runtime state consistent with the verdict (candidate in runtime iff ACCEPT, bodies equal)')
    if decision['verdict'] == 'ACCEPT':
        check(runtime_body_sha(ROOT) == hyp['candidate']['body_sha256'], 'integrated body sha == tested (hypothesis) body sha')
    # manifest seals
    for p, digest in manifest['sha256'].items():
        check((out / p).exists() and fc.sha_file(out / p) == digest, f'seal {p}')
    check(set(manifest['sha256']) >= set(raws) | set(visuals), 'manifest seals every raw')
    check(manifest['source_revision'] == identity['identity']['current_commit'], 'manifest source revision == identity')
    check(all(c['exit_code'] in (0, 1) for c in manifest['commands']), 'manifest exit codes recorded')
    print(f'AUDIT {"PASS" if not failures else "FAIL"} passes={len(passes)} failures={len(failures)} visual_raws={len(visuals)} timing_raws={len(raws)} '
          f'decision={decision["verdict"]}')
    return 0 if not failures else 1


# ---------------------------------------------------------------- main --

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--output', required=True); p.set_defaults(func=prepare)
    v = sub.add_parser('visual'); v.add_argument('--root', required=True); v.add_argument('--output', required=True)
    v.add_argument('--engines', nargs='*', default=None); v.add_argument('--only', nargs='*', default=None); v.set_defaults(func=visual)
    c = sub.add_parser('capture')
    c.add_argument('--root', required=True); c.add_argument('--output', required=True); c.add_argument('--mode', choices=MODES, required=True)
    c.add_argument('--scene', choices=list(SCENES), required=True); c.add_argument('--rep', choices=REPS, required=True)
    c.add_argument('--arm', choices=list(ARMS), required=True); c.add_argument('--case', required=True)
    c.add_argument('--warmup-ms', type=int, default=5000); c.add_argument('--window-ms', type=int, default=30000)
    c.add_argument('--windows', type=int, default=1); c.add_argument('--cpu-throttle', type=int, default=1)
    c.add_argument('--timeout-ms', type=int, default=600000); c.set_defaults(func=capture)
    r = sub.add_parser('run'); r.add_argument('--output', required=True); r.add_argument('--engines', nargs='*', default=None)
    r.add_argument('--warmup-ms', type=int, default=5000); r.add_argument('--window-ms', type=int, default=30000)
    r.add_argument('--windows', type=int, default=1); r.add_argument('--cpu-throttle', type=int, default=1)
    r.add_argument('--skip-timing', action='store_true'); r.set_defaults(func=run)
    for name, func in (('report', report), ('audit', audit)):
        s = sub.add_parser(name); s.add_argument('--output', required=True); s.set_defaults(func=func)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
