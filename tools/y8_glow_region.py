#!/usr/bin/env python3
"""TASK-280: test a drawing-area reduction at the dominant remaining renderer cost (the glow composite).

Evidence base (sealed in artifacts/TASK-276 stages.json, TASK-274, TASK-278, TASK-279): the glow
composite, N full-resolution 'lighter' upscales of the blur levels through the geometry
destination clip, is the dominant stage of every renderer/mode pair; for the ambient chain the
median saving of switching it off is 38.8 ms (bad) / 49.3 ms (classic) per ~95-110 ms frame,
REPEATED beyond noise. The integrated TASK-265 clip is the bounding box of everything drawn into
level 0, and for the ambient chain that box is the whole viewport (TASK-276 frozen profile:
level0_dest_box_observed [0,0,1280,719] bad / [0,0,1270,719] classic) because the 40 motes are
spread over the field: the box removes nothing there. TASK-279 showed the chain has no cacheable
intermediate (the mote layout changes every frame), so reuse is out; what remains is the area.

One candidate (tools/y8_glow_region_candidate.js, page-injected, runtime untouched): keep every
primitive's own device-pixel rectangle, dilate each with the unchanged conservative per-level
rules, merge them into a disjoint set of integer-aligned rectangles and clip the same full
drawImage to that region instead of the box (box kept when the region would not save >= 10 %).
Same drawImage submissions, alphas, blend order and bilinear sampling; black level texels add
nothing under 'lighter', so the result is pixel-identical by construction. Rejected designs,
isolated and never installed, are listed in hypothesis.json.

Actions:
  prepare  trees/identity + hypothesis.json (pre-registered target, expectation, provenance)
  visual   controlled deterministic comparisons candidate vs current (synthetic 60 Hz clock,
           readback confined to this pass): menu/start, early/mid/late gameplay with the moving
           camera, trails/sparks, forced shake, player glow exclusion, settled resizes incl.
           letterbox bars and odd backing sizes; both modes, seeds 1/4/49, dpr1 + dpr2, Chromium
           (+ Firefox when available). Source = the glow level textures of both chains.
  capture  one untraced timing capture (rAF intervals + read-only sampler; no readback)
  run      visual pass, then (only if visuals are exact) 3 alternating 30 s pairs per mode on
           the natural replay + 1 moving-x pair per mode
  report   visual-validation.json, region.json, timings.json, decision.json, manifest.json
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
CANDIDATE = MODULE.parent / 'y8_glow_region_candidate.js'
TASK = 'TASK-280'
MODULE_AT_CAPTURE = 'module-at-capture'
PROFILE = 'desktop'
VIEWPORT = [1280, 720]
DPR = 1
MAIN, CHILL = 'bad', 'classic'
MODES = (MAIN, CHILL)
MODE_SETUP = {MAIN: {'seed': 4, 'replay_style': 'screening'}, CHILL: {'seed': 7, 'replay_style': 'chill-ceiling'}}
ARMS = {'current': 'current runtime (control): nothing injected; TASK-265 bounding-box composite clip',
        'candidate': 'union-of-rectangles composite clip (tools/y8_glow_region_candidate.js injected per page before startGame)'}
BODY_BEGIN, BODY_END = '// BEGIN TASK-280 candidate body', '// END TASK-280 candidate body'
CANDIDATE_MARKERS = ('REGION_MAX_AREA_RATIO', 'regionRects', '__geometryRegionCandidate', 'TASK-280 candidate body')
REGION_MAX_AREA_RATIO = 0.9
RENDERERS = ('ambient', 'player')
LEVELS = 4
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
              'ambientGlow', 'motes', 'moteHash', 'barsVisible', 'lightmapHasLights', 'randomDraws', 'levelSizes')
MEASURED_TARGET = {
    'source': ['artifacts/TASK-276/stages.json', 'artifacts/TASK-276/decision.json', 'artifacts/TASK-274/decision.json',
               'artifacts/TASK-278/decision.json', 'artifacts/TASK-279/decision.json'],
    'composite_off_median_saving_ms': {'bad/ambient': 38.77, 'classic/ambient': 49.25, 'bad/player': 3.49, 'classic/player': 16.44},
    'composite_tier': {'bad/ambient': 'REPEATED_SAVING', 'classic/ambient': 'REPEATED_SAVING', 'bad/player': 'WITHIN_NOISE',
                       'classic/player': 'CONSISTENT_SAVING'},
    'control_frame_ms': 'about 95-110 ms at 1280x720 dpr1 in this environment (TASK-274/276 controls)',
    'dominant_stage_counts': {'composite': 4},
    'ambient_level0_dest_box_observed': {'bad': [0, 0, 1280, 719], 'classic': [0, 0, 1270, 719]},
    'ambient_box_fraction_of_viewport': 'about 1.0: the integrated TASK-265 bounding-box clip removes nothing for the ambient chain',
    'levels': 'ambient and player chains: 4 levels at 1/4, 1/8, 1/16, 1/32 of the backing size (style.js glow resolutionScale 0.25, '
              'blurLevels 4), each upscaled to the full backing with lighter at alphas 0.22/0.4/0.65/0.9',
    'no_cacheable_intermediate': 'TASK-279: the mote layout changes on 100 % of consecutive frames (performance.now()); reuse is not '
                                 'available at this cost, so the remaining lever is the drawn area per submission',
}


def utc():
    return fc.utc()


def candidate_text():
    return CANDIDATE.read_text()


def candidate_sha():
    return fc.sha_file(CANDIDATE)


def candidate_body(text=None):
    """The body between the BEGIN/END markers (what an ACCEPT pastes into render/effects.js)."""
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


# TASK-311: the shipped body is the TASK-280 tested body plus one sealed hunk in rectangle(): CanvasRenderingContext2D.filter is
# undefined in WebKit (artifacts/TASK-310/ctx-filter-probe.log), so `c.filter!=='none'` marked every frame full there
# (artifacts/TASK-310/webkit-region-live.log: webkit full=328 region=0). A missing filter property is now read as 'none'.
# Chromium/Firefox report 'none' so the change is a literal no-op there (artifacts/TASK-311/compare.json 18/18 identical).
# Any further edit of the body changes this sha and fails every accepted-body check.
TASK311_BODY_SHA256 = '522e0a215906fa06499303fe94e1819c6aa1fb70872dd6bb5e20cd51a612fc4a'


def accepted_runtime_bodies(tested_body_sha256):
    """Body shas the shipped runtime may carry when the TASK-280 verdict is ACCEPT: the tested body and the TASK-311 sealed hunk."""
    return {tested_body_sha256, TASK311_BODY_SHA256}


def runtime_body_accepted(tested_body_sha256, root=ROOT):
    return runtime_body_sha(root) in accepted_runtime_bodies(tested_body_sha256)


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

# The candidate replaces the four window.__geometry* hooks. Level contexts wrapped by the
# runtime hooks during the menu frames are dropped (levels = []) so resize() recreates them and
# the candidate wraps fresh contexts once; the level canvases are fully rewritten every frame.
INSTALL_CANDIDATE = '''(src) => {
    (0, eval)(src)
    for (const r of [visualEffects.ambientGlow, visualEffects.playerGlow, visualEffects.bloom]) if (r && r.levels) r.levels = []
    return !!(window.__geometryRegionCandidate && window.__geometryRegionCandidate.task === 'TASK-280')
}'''

CANDIDATE_PRESENT = '''() => !!window.__geometryRegionCandidate'''

RENDERER_KEY = '''const rendererKey = r => r === visualEffects.ambientGlow ? 'ambient' : r === visualEffects.playerGlow ? 'player' : 'other'
    const blank = () => ({box: [null, null, null, null], region: [null, null, null, null], used: [null, null, null, null], rects: [null, null, null, null]})'''

VISUAL_BEGIN = '''(cfg) => {
    const FC = window.__featureCost
    cancelAnimationFrame(game)
    const V = window.__visual = {clock: 1000, frame: 0, samples: [], randomDraws: 0, regionCalls: 0, boxCalls: 0,
        realNow: performance.now.bind(performance), areas: {ambient: null, player: null, other: null}}
    performance.now = () => V.clock
    const random = Math.random
    Math.random = function() { V.randomDraws++; return random() }
    ''' + RENDERER_KEY + '''
    V.reset = () => { V.areas = {ambient: blank(), player: blank(), other: blank()} }
    V.reset()
    // Called by the runtime and by the candidate: the destination box of level i
    window.__geometryObserve = (renderer, i, b, full) => {
        V.boxCalls++
        const a = V.areas[rendererKey(renderer)]
        if (!a || i > 3) return
        a.box[i] = b ? (b[2] - b[0]) * (b[3] - b[1]) / (renderer.canvas.width * renderer.canvas.height) : 0
    }
    // Called by the candidate only: the merged region and whether it replaced the box
    window.__regionObserve = (renderer, i, b, region, regionArea, rects) => {
        V.regionCalls++
        const a = V.areas[rendererKey(renderer)]
        if (!a || i > 3) return
        a.region[i] = regionArea === null ? null : regionArea / (renderer.canvas.width * renderer.canvas.height)
        a.used[i] = region !== null
        a.rects[i] = region ? region.length : 0
    }
    return {installed: !!window.__geometryRegionCandidate}
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
        V.samples.push([V.frame, sx, sy, moteHash(), V.areas.ambient, V.areas.player, [canvas.width, canvas.height]])
    }
    return V.frame
}'''

VISUAL_SHAKE = '''() => { visualEffects.screenEffects.triggerDeath(ninja.x, ninja.y); return visualEffects.screenEffects.shakeUntil }'''

VISUAL_CHECKPOINT = '''(cfg) => {
    const V = window.__visual, FC = window.__featureCost
    ''' + MOTE_HASH + '''
    const png = canvas.toDataURL('image/png')
    const draws = V.randomDraws
    const levels = {}, levelSizes = {}
    for (const [key, r] of [['ambient', visualEffects.ambientGlow], ['player', visualEffects.playerGlow]]) {
        levels[key] = r.levels.map(l => l.canvas.toDataURL('image/png'))
        levelSizes[key] = r.levels.map(l => [l.canvas.width, l.canvas.height])
    }
    const rect = canvas.getBoundingClientRect()
    const S = visualEffects.screenEffects
    const hasGame = typeof version !== 'undefined' && version && typeof ninja !== 'undefined' && ninja
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
        lightmapHasLights: visualEffects.lightmap.hasLights, randomDraws: draws, levelSizes,
        randomDrawsDuringReadback: V.randomDraws - draws}
    const candidate = {present: !!window.__geometryRegionCandidate, lastFrameAreas: V.areas, regionCalls: V.regionCalls, boxCalls: V.boxCalls}
    return {png, levels, state, candidate}
}'''

VISUAL_SAMPLES = '''() => ({samples: window.__visual.samples, randomDraws: window.__visual.randomDraws,
    regionCalls: window.__visual.regionCalls, boxCalls: window.__visual.boxCalls})'''


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
        'mechanism': 'drawing-area reduction: the composite upscales are clipped to the union of the dilated per-primitive '
                     'rectangles (a region) instead of their single bounding box; same submissions, alphas, blend order and '
                     'full-resolution bilinear sampling',
        'measured_target': MEASURED_TARGET,
        'chosen_target': 'the glow composite of the ambient chain (dominant stage in all four TASK-276 renderer/mode pairs; '
                         'REPEATED_SAVING 38.8 ms bad / 49.3 ms classic for ambient) and, by the same code path, of the player '
                         'chain (16.4 ms classic CONSISTENT, 3.5 ms bad within noise). Four full-backing lighter upscales per chain '
                         'per frame through a destination clip.',
        'unnecessary_work': 'the level textures are opaque black wherever nothing was drawn (renderGlow fills level 0 black; '
                            'blur rewrites each level from the previous one). Under lighter, Cr = Cs*alpha + Cd: a black source '
                            'pixel leaves the destination unchanged (the game canvas is opaque: index.html getContext(2d, '
                            '{alpha: false})). Upscale pixels outside the dilated support of the drawn primitives therefore change '
                            'nothing. The integrated clip bounds that support with ONE box; for 40 motes spread over the field the '
                            'box is the viewport (TASK-276: level0_dest_box_observed [0,0,1280,719]).',
        'why_it_differs_from_the_integrated_geometry_clip': 'TASK-265 integrated a bounding-box clip (one rectangle = the union '
                                                            'box of all primitives) and measured it on the player chain, where the '
                                                            'box is small. The candidate keeps the primitives apart: each is dilated '
                                                            'with the unchanged conservative rules and the clip is the disjoint union '
                                                            'of those rectangles. Its reduction is the empty area BETWEEN primitives '
                                                            'inside the box, which the box cannot remove; for the ambient chain that is '
                                                            'most of the frame at the fine levels. No CanvasPattern, no winding change '
                                                            'of the exclusion clip, no pixel readback (TASK-265 rejects are untouched).',
        'expected_work_reduction': {
            'area_by_level_ambient': 'self-test with 40 motes of 2.3-5.8 level-0 px (node, tools/test_y8_glow_region.py): region/box '
                                     'about 0.11 at level 0, 0.45 at level 1, 0.90 at level 2 (at the 0.9 ratio limit, so the box '
                                     'may be kept), 1.0 at level 3 (box kept). The dilation grows by ~2x per level, so the coarse '
                                     'levels stay full-frame.',
            'expected_ms_dpr1': 'if a level upscale costs in proportion to its clipped area, about 1.4-1.5 of the 4 ambient level '
                                'upscales are removed: ~14 ms of the 38.8 ms bad composite and ~17 ms of the 49.3 ms classic '
                                'composite, i.e. roughly 12-18 % of a 95-110 ms frame, plus a smaller player-chain share in '
                                'classic (ribbon rectangles vs their box). Less if the cost is per submission rather than per '
                                'pixel, or if the multi-rectangle anti-aliased clip costs a mask pass; the timing rule decides.',
            'threshold': f'>= {MIN_MEDIAN_REDUCTION:.0%} median active frame-time reduction in both modes over 3 alternating '
                         f'30 s pairs, no gameplay pair (replay or moving-x) worse by > {MAX_WORSE:.0%}',
            'overhead': 'per frame per chain: one rectangle per primitive (80 for the motes, one per ribbon point/spark for the '
                        'player), four dilations per rectangle, a scanline union (<= 200 rectangles) and up to a few hundred '
                        'ctx.rect calls; expected well under 1 ms of JS (TASK-276: composite JS submission 0.13-0.18 ms).'},
        'region_rule': f'the region replaces the box only when region area <= {REGION_MAX_AREA_RATIO} x box area; unknown/full '
                       f'drawing (paths, images, text, filters, shadows) keeps the full-canvas box exactly as today',
        'exactness_argument': 'integer-aligned rectangle edges give an anti-aliased clip coverage of exactly 0 or 1; the region is '
                              'a subset of the box and a superset of the dilated support of every primitive (dilation is applied '
                              'per rectangle with the same floor/ceil rules, so box(dilated rects) == dilated box, verified in the '
                              'node self-test); outside the support the source is black and lighter leaves the destination '
                              'unchanged. Any pixel difference rejects the candidate regardless of this argument.',
        'control': {'description': 'unchanged current runtime: the served tree is `git archive HEAD` (identity.json), '
                                   'no page injection in the current arm', **{k: identity[k] for k in ('current_commit', 'current_tar_sha256')}},
        'candidate': {'file': str(CANDIDATE.relative_to(ROOT)), 'sha256': candidate_sha(), 'body_sha256': body_sha(),
                      'installation': 'page.evaluate of the file text after boot and fc.INSTRUMENT, before startGame; the four '
                                      'window.__geometry* hooks are replaced and the glow level contexts recreated so the candidate '
                                      'wraps fresh contexts; shipping runtime untouched',
                      'shipping_runtime_has_candidate_methods': runtime_has_candidate(ROOT)},
        'rejected_designs_isolated': [
            {'design': 'pre-sum the four levels at level-0 resolution and upscale once (one submission instead of four)',
             'reason': 'changes sampling: a level upscaled to level-0 size and then to the backing is bilinear twice, not once, '
                       'and the 8-bit intermediate clamps the lighter sum; not pixel-identical. Never installed.'},
            {'design': 'crop the source rectangle per primitive (9-argument drawImage) instead of clipping the destination',
             'reason': 'bilinear sampling at a source-subset edge clamps to the subset instead of reading the neighbouring texels; '
                       'edge pixels differ from the full-level upscale. Never installed.'},
            {'design': 'tighter dilation (one texel per transfer) to shrink the coarse levels',
             'reason': 'the conservative rules are the integrated, validated envelope; shrinking them trades exactness for area '
                       'without evidence. The candidate keeps them unchanged. Never installed.'},
            {'design': 'skip the coarse levels entirely when their alpha-weighted content is dark',
             'reason': 'removes light that is present in the image (visible difference). Never installed.'}],
        'visual_requirement': 'exact final pixels, exact glow level textures (source) of both chains and equal gameplay state at '
                              'every checkpoint on every tested engine; unexplained differences reject the candidate',
        'smoke_findings_before_the_run': [
            'smoke (chromium dpr1 seed 4, both modes, scratch folder artifacts/TASK-280/smoke, not sealed evidence): EXACT at 11/11 '
            'checkpoints per mode (final pixels, all 8 level textures, 35-key state digest, Math.random draw counts); the candidate '
            'composite hook ran on every composite call (2328 per session) and never in the current arm.',
            'measured ambient area (fraction of the backing, mean over 290 gameplay frames): box 0.997-1.0 at every level in both arms '
            '(the integrated clip removes nothing for the ambient chain); candidate clip 0.093 / 0.42 / 0.87 / 1.0 by level, region '
            'used on 100 % / 100 % / 88-90 % / 0 % of frames, 208-211 rectangles at level 0; clipped area = 0.60 of the box area summed '
            'over the four levels (pre-registered estimate 0.11 / 0.45 / 0.90 / 1.0).',
            'player chain: classic clip/box 0.77 (ribbon rectangles vs their box, region used on 80 % of level-0 frames); bad 1.0 '
            '(the trail box is already small, 1-29 % of the backing, and the region saves < 10 % so the box is kept).',
            'no timing smoke was run: the timing expectation above stays pre-registered from the area and the TASK-276 composite costs.'],
        'prior_experiments_not_repeated': ['TASK-265 live geometry bounding-box clip (PURSUE, integrated; kept as the control)',
                                           'TASK-265 readback oracle (REJECT)', 'TASK-265 CanvasPattern (REJECT)',
                                           'TASK-265 winding (REJECT)', 'TASK-276 frozen source/blur arms (diagnostic only)',
                                           'TASK-279 far background stack cache (REJECT: dither phase / transform drift)'],
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
                'readback': 'canvas.toDataURL(image/png) of the game canvas (final) and of every glow level canvas of the ambient '
                            'and player chains (source), this pass only',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter'}
    args.case = visual_case(p)
    root, raw = common_raw(args, {'settings': settings, 'replay': replay, 'checkpoints': [], 'resizes': []})
    cfg = {'dpr': context['dpr'], 'input': 'mouse', 'ablate': [], 'diagnostic': True, 'replay': replay,
           'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
    pngs = {}

    def checkpoint(page, name, scene):
        r = page.evaluate(VISUAL_CHECKPOINT, {'scene': scene})
        png = png_bytes(r['png'])
        levels = {k: [png_bytes(u) for u in v] for k, v in r['levels'].items()}
        level_pixels = {k: [pixels_sha(b) for b in v] for k, v in levels.items()}
        entry = {'name': name, 'scene': scene, 'final_sha256': fc.sha_bytes(png), 'final_pixels_sha256': pixels_sha(png),
                 'final_bytes': len(png),
                 'source_levels_sha256': {k: [fc.sha_bytes(b) for b in v] for k, v in levels.items()},
                 'source_levels_pixels_sha256': level_pixels,
                 'source_pixels_sha256': fc.sha_bytes(json.dumps(level_pixels, sort_keys=True).encode()),
                 'source_sha256': fc.sha_bytes(json.dumps({k: [fc.sha_bytes(b) for b in v] for k, v in levels.items()}, sort_keys=True).encode()),
                 'state': r['state'], 'candidate': r['candidate']}
        pngs[name] = (png, levels)
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
    if p['arm'] == 'candidate' and raw['result'] == 'COMPLETE' and not raw.get('regionCalls'):
        raw['result'] = 'FAILED: candidate installed but its composite hook never ran'
    path = unique_path(out / 'visual', args.case, '.json')
    fc.dump(path, raw)
    print('PASS' if raw['result'] == 'COMPLETE' else 'FAIL', args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'checkpoints', len(raw['checkpoints']), 'regionCalls', raw.get('regionCalls'), 'boxCalls', raw.get('boxCalls'),
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
                if not pixels_equal(a, b, 'final') or not pixels_equal(a, b, 'source'):
                    save_png(out, visual_case(dict(p, arm='current')), a['name'], cur[1].get(a['name']), levels=True)
                    save_png(out, visual_case(dict(p, arm='candidate')), b['name'], cand[1].get(b['name']), levels=True)
        if keep:
            for name, pair in pngs.items():
                save_png(out, visual_case(p), name, pair)
    return status


def save_png(out, case, name, pair, levels=False):
    if not pair:
        return
    folder = out / 'visual' / 'png'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{case}-{name}.png').write_bytes(pair[0])
    if levels:
        for key, pngs in pair[1].items():
            for i, png in enumerate(pngs):
                (folder / f'{case}-{name}-{key}-level{i}.png').write_bytes(png)


def pixels_equal(a, b, kind):
    """Decoded-pixel equality (falls back to PNG bytes when PIL was absent)."""
    pa, pb = a.get(f'{kind}_pixels_sha256'), b.get(f'{kind}_pixels_sha256')
    if pa and pb:
        return pa == pb
    return a[f'{kind}_sha256'] == b[f'{kind}_sha256']


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
                                   'no region/box observers',
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
        raw['observers_absent'] = page.evaluate('() => !window.__geometryObserve && !window.__regionObserve')
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
    """The last COMPLETE record of a case (earlier failed attempts stay preserved)."""
    matches = [(p, r) for p, r in raws.items() if r.get('case') == case and r.get('result') == 'COMPLETE']
    return matches[-1] if matches else (None, None)


def state_digest(state):
    return {k: state.get(k) for k in STATE_KEYS}


def area_summary(samples):
    """Mean per-level box/region fractions and region-use fractions over the gameplay frames of one arm."""
    out = {}
    for key, idx in (('ambient', 4), ('player', 5)):
        rows = [s[idx] for s in samples if s[1] is not None and s[idx]]
        levels = []
        for i in range(LEVELS):
            box = [r['box'][i] for r in rows if r['box'][i] is not None]
            region = [r['region'][i] for r in rows if r['region'][i] is not None]
            used = [r['used'][i] for r in rows if r['used'][i] is not None]
            rects = [r['rects'][i] for r in rows if r['rects'][i] is not None]
            # clip fraction per frame: the region when the candidate used it, else the box (current arm: always the box)
            clip = [(r['region'][i] if r['used'][i] else r['box'][i]) for r in rows if r['box'][i] is not None]
            levels.append({'frames_with_box': len(box), 'mean_box_fraction': statistics.fmean(box) if box else None,
                           'frames_with_region': len(region), 'mean_region_fraction': statistics.fmean(region) if region else None,
                           'region_used_fraction': (sum(used) / len(used)) if used else None,
                           'mean_clip_fraction': statistics.fmean(clip) if clip else None,
                           'mean_rects_when_used': statistics.fmean(x for x, u in zip(rects, used) if u) if any(used) else None,
                           'max_rects': max(rects) if rects else None})
        total_box = [l['mean_box_fraction'] for l in levels if l['mean_box_fraction'] is not None]
        total_clip = [l['mean_clip_fraction'] for l in levels if l['mean_clip_fraction'] is not None]
        out[key] = {'levels': levels, 'frames': len(rows),
                    'box_area_sum_over_levels': sum(total_box) if total_box else None,
                    'clip_area_sum_over_levels': sum(total_clip) if total_clip else None,
                    'clipped_area_fraction_of_box': (sum(total_clip) / sum(total_box)) if total_box and sum(total_box) else None}
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
            per_level = {k: [pa == pb for pa, pb in zip(a['source_levels_pixels_sha256'][k], b['source_levels_pixels_sha256'][k])]
                         for k in a['source_levels_pixels_sha256']}
            cp_entry = {'name': a['name'], 'scene': a['scene'], 'final_equal': pixels_equal(a, b, 'final'),
                        'source_equal': pixels_equal(a, b, 'source'), 'source_levels_equal': per_level, 'state_equal': sa == sb,
                        'final_png_bytes_equal': a['final_sha256'] == b['final_sha256'],
                        'final_pixels_sha256': a.get('final_pixels_sha256'), 'candidate_final_pixels_sha256': b.get('final_pixels_sha256'),
                        'source_pixels_sha256': a.get('source_pixels_sha256'), 'candidate_source_pixels_sha256': b.get('source_pixels_sha256'),
                        'comparison_unit': 'decoded RGBA pixels' if a.get('final_pixels_sha256') else 'PNG bytes',
                        'final_sha256': a['final_sha256'], 'candidate_final_sha256': b['final_sha256'],
                        'level_sizes': a['state'].get('levelSizes'),
                        'candidate_last_frame_areas': (b.get('candidate') or {}).get('lastFrameAreas'),
                        'current_last_frame_areas': (a.get('candidate') or {}).get('lastFrameAreas'),
                        'backing': a['state']['canvas'], 'css': a['state']['css'], 'logical': a['state']['logical'],
                        'screen': a['state']['screen'], 'particles': a['state']['particles'], 'track_points': a['state']['trackPoints'],
                        'shaking': a['state']['shaking'], 'player_glow': a['state']['playerGlow'], 'bars_visible': a['state']['barsVisible'],
                        'menu': a['state']['menu'], 'random_draws': a['state']['randomDraws']}
            if not cp_entry['state_equal']:
                cp_entry['state_differences'] = {k: [sa[k], sb[k]] for k in STATE_KEYS if sa[k] != sb[k]}
            if not (cp_entry['final_equal'] and cp_entry['source_equal'] and cp_entry['state_equal']):
                ok = False
                failures.append(f'{name}/{a["name"]}: final_equal={cp_entry["final_equal"]} source_equal={cp_entry["source_equal"]} '
                                f'state_equal={cp_entry["state_equal"]}')
                pa = out / 'visual/png' / f'{cur["case"]}-{a["name"]}.png'
                pb = out / 'visual/png' / f'{cand["case"]}-{b["name"]}.png'
                if pa.exists() and pb.exists():
                    cp_entry['final_diff'] = png_diff(pa, pb)
                    cp_entry['final_png'] = [str(pa.relative_to(out)), str(pb.relative_to(out))]
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
        cell['mote_layout'] = mote_dependency(cur.get('samples', []))
        cell['areas_current'] = area_summary(cur.get('samples', []))
        cell['areas_candidate'] = area_summary(cand.get('samples', []))
        cell['candidate_region_calls'] = cand.get('regionCalls')
        cell['candidate_box_calls'] = cand.get('boxCalls')
        cell['current_region_calls'] = cur.get('regionCalls')
        cell['random_draws_equal'] = cur.get('randomDraws') == cand.get('randomDraws')
        if not cell['random_draws_equal']:
            ok = False
            failures.append(f'{name}: Math.random draw counts differ {cur.get("randomDraws")} vs {cand.get("randomDraws")}')
        if not cand.get('regionCalls'):
            ok = False
            failures.append(f'{name}: the candidate composite hook never ran')
        if cur.get('regionCalls'):
            ok = False
            failures.append(f'{name}: region hook ran in the current arm')
        cell['result'] = 'EXACT' if ok else 'DIFFERENT'
        cells[name] = cell
    differences = []
    for c in cells.values():
        for cp_entry in c['checkpoints']:
            if not (cp_entry['final_equal'] and cp_entry['source_equal'] and cp_entry['state_equal']):
                differences.append({'cell': f"{c['engine']}/{c['context']}/{c['mode']}/seed{c['seed']}", 'checkpoint': cp_entry['name'],
                                    'final_equal': cp_entry['final_equal'], 'source_equal': cp_entry['source_equal'],
                                    'state_equal': cp_entry['state_equal'], 'final_diff': cp_entry.get('final_diff'),
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
                      'sha256 of every glow level canvas of the ambient and player chains (source), gameplay-state digest (%d keys); '
                      'readback confined to this pass' % len(STATE_KEYS),
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
    """Per-frame camera change rates from [frame, sx, sy, moteHash, ...] samples (gameplay frames only)."""
    game = [s for s in samples if s[1] is not None]
    pairs = list(zip(game, game[1:]))
    if not pairs:
        return {'frames': len(game), 'pairs': 0}
    dx = sum(1 for a, b in pairs if a[1] != b[1])
    dy = sum(1 for a, b in pairs if a[2] != b[2])
    return {'frames': len(game), 'pairs': len(pairs), 'x_changed_fraction': dx / len(pairs), 'y_changed_fraction': dy / len(pairs),
            'x_range': [min(s[1] for s in game), max(s[1] for s in game)]}


def mote_dependency(samples):
    hashes = [s[3] for s in samples if s[3] is not None]
    pairs = list(zip(hashes, hashes[1:]))
    return {'frames_with_layout': len(hashes), 'changed_fraction': (sum(1 for a, b in pairs if a != b) / len(pairs)) if pairs else None}


def build_region(out, vv):
    """Measured drawing-area evidence: per cell the box (current and candidate) and clipped (candidate) area per level."""
    src = (ROOT / 'render/effects.js').read_text().splitlines()
    source_lines = {}
    for marker in ('window.__geometryDraw=', 'window.__geometryBegin=', 'renderer.ctx.drawImage(target,0,0', "globalCompositeOperation = config.compositeOperation",
                   'window.__geometryDraw(this, i)'):
        for i, l in enumerate(src, 1):
            if marker in l:
                source_lines[marker] = f'render/effects.js:{i}'
                break
    cells = {}
    for k, c in vv['cells'].items():
        if not c.get('areas_candidate'):
            continue
        cells[k] = {'current': c['areas_current'], 'candidate': c['areas_candidate'],
                    'frames': c.get('samples_frames'), 'mote_layout': c.get('mote_layout'), 'camera': c.get('camera')}
    summary = {}
    for renderer in RENDERERS:
        rows = [c['candidate'][renderer] for c in cells.values() if c['candidate'].get(renderer) and c['candidate'][renderer]['frames']]
        box_rows = [c['current'][renderer] for c in cells.values() if c['current'].get(renderer) and c['current'][renderer]['frames']]
        summary[renderer] = {
            'cells': len(rows),
            'current_mean_box_fraction_by_level': [statistics.fmean(x for x in (r['levels'][i]['mean_box_fraction'] for r in box_rows) if x is not None)
                                                   if any(r['levels'][i]['mean_box_fraction'] is not None for r in box_rows) else None for i in range(LEVELS)],
            'candidate_mean_box_fraction_by_level': [statistics.fmean(x for x in (r['levels'][i]['mean_box_fraction'] for r in rows) if x is not None)
                                                     if any(r['levels'][i]['mean_box_fraction'] is not None for r in rows) else None for i in range(LEVELS)],
            'candidate_mean_clip_fraction_by_level': [statistics.fmean(x for x in (r['levels'][i]['mean_clip_fraction'] for r in rows) if x is not None)
                                                      if any(r['levels'][i]['mean_clip_fraction'] is not None for r in rows) else None for i in range(LEVELS)],
            'candidate_region_used_fraction_by_level': [statistics.fmean(x for x in (r['levels'][i]['region_used_fraction'] for r in rows) if x is not None)
                                                        if any(r['levels'][i]['region_used_fraction'] is not None for r in rows) else None for i in range(LEVELS)],
            'clipped_area_fraction_of_box': [r['clipped_area_fraction_of_box'] for r in rows if r['clipped_area_fraction_of_box'] is not None]}
    return {'task': TASK, 'utc': utc(),
            'question': 'how much of the composite upscale area does the region clip remove, per chain and level, versus the integrated box?',
            'source_lines': source_lines, 'region_rule_ratio': REGION_MAX_AREA_RATIO,
            'unit': 'fractions of the backing canvas area (canvas.width x canvas.height); clip fraction = region when used, else box',
            'cells': cells, 'summary': summary,
            'expected_from_hypothesis': 'ambient region/box about 0.11 / 0.45 / 0.90 / 1.0 by level',
            'measured_composite_cost_ms': MEASURED_TARGET['composite_off_median_saving_ms'],
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
                                'REJECT': 'the candidate is not integrated; the shipping runtime stays unchanged',
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
    fc.dump(out / 'region.json', build_region(out, vv))
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
        amb = (c.get('areas_candidate') or {}).get('ambient') or {}
        print('  ', k, c['result'], 'checkpoints', len(c['checkpoints']), 'ambient clip/box',
              None if amb.get('clipped_area_fraction_of_box') is None else round(amb['clipped_area_fraction_of_box'], 3),
              'by level', [None if l['mean_clip_fraction'] is None else round(l['mean_clip_fraction'], 3) for l in amb.get('levels', [])])
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
            check(r.get('candidate_installed') and r.get('candidate_present_in_page_end') and r.get('regionCalls'),
                  f'{p}: candidate installed and its composite hook ran in the candidate arm')
        else:
            check(not r.get('candidate_present_in_page_end') and not r.get('regionCalls'), f'{p}: no candidate in the current arm')
        for rz in r.get('resizes', []):
            check(rz['backing_equals_round_css_times_dpr'], f'{p}: resize {rz["requested"]} backing == round(css x dpr)')
        for c in r['checkpoints']:
            check(c['state']['dpr'] == s['dpr'], f'{p}/{c["name"]}: dpr pinned')
            # the player chain only draws in a game frame: menu checkpoints legitimately record 0 player levels
            expected_player = 0 if c['scene'] == 'menu' else LEVELS
            check(len(c['source_levels_pixels_sha256'].get('ambient', [])) == LEVELS and len(c['source_levels_pixels_sha256'].get('player', [])) == expected_player,
                  f'{p}/{c["name"]}: {LEVELS} ambient and {expected_player} player level textures recorded')
    vv = build_visual(out)
    check(vv['exact_on_all_tested_engines'] == vv_file['exact_on_all_tested_engines'], 'visual verdict re-derived equals file')
    check({k: c['result'] for k, c in vv['cells'].items()} == {k: c['result'] for k, c in vv_file['cells'].items()}, 'visual cell results re-derived')
    check(vv['coverage'] == vv_file['coverage'], 'visual coverage re-derived')
    for k, c in vv['cells'].items():
        if c['result'] in ('EXACT', 'DIFFERENT'):
            check(c['areas_candidate'] == vv_file['cells'][k]['areas_candidate'], f'{k}: candidate area summary re-derived')
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
        check(runtime_body_accepted(hyp['candidate']['body_sha256']), 'integrated body sha == tested (hypothesis) body sha or the TASK-311 sealed body')
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
