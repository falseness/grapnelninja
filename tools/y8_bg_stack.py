#!/usr/bin/env python3
"""TASK-279: test reuse/caching at the largest proven repeated cost (the far background stack).

Evidence base (sealed in artifacts/TASK-276, TASK-277, TASK-278): the ambient glow composite
(30-52 ms/frame) has no invariant intermediate (the mote layout is a function of
performance.now() every frame, render/effects.js layoutAmbientMotes), so the caching
mechanism has no target there. The background (22-40 ms/frame at dpr1, 24 % of the frame) is
6 full-frame raster passes; its tiles and gradient objects are already cached (TASK-277:
0 rebuilds in steady state), the repeated work is the raster. Three of the six passes (base
gradient, far crystal tile, haze) depend only on the viewport, backing store, transform,
colours, the far tile and the far layer's y shift; the camera x shift is a periodic offset.
In both shipped modes the camera has no vertical motion (index.html: new Screen(false)), so
that stack is invariant across every gameplay frame while the camera moves horizontally.

One candidate (tools/y8_background_stack_candidate.js, page-injected, runtime untouched):
paint the far stack once into a backing-resolution canvas keyed by those inputs and tile it at
the x shift with the existing device-snapped 1:1 copies. Rejected design, isolated here and
never installed: a whole-background composite memo (key includes both shifts) has a 0 % hit
rate while the camera moves (TASK-277 natural replays: screen.x changes every frame in
classic).

Actions:
  prepare  trees/identity + hypothesis.json (pre-registered target, expectation, provenance)
  visual   controlled deterministic comparisons candidate vs current (synthetic 60 Hz clock,
           readback confined to this pass): menu/start, early/mid/late gameplay with the moving
           camera, trails/sparks, forced shake, player glow exclusion, settled resizes incl.
           letterbox bars and odd backing sizes; both modes, seeds 1/4/49, dpr1 + dpr2, Chromium
           (+ Firefox when available)
  capture  one untraced timing capture (rAF intervals + read-only sampler; no readback)
  run      visual pass, then (only if visuals are exact) 3 alternating 30 s pairs per mode on
           the natural replay + 1 moving-x pair + 1 moving-xy diagnostic pair per mode
  report   visual-validation.json, deps.json, timings.json, decision.json, manifest.json
  audit    recompute everything from the raws; verify the shipped runtime matches the decision
"""

import argparse
import base64
from contextlib import ExitStack
import io
import json
from pathlib import Path
import platform
import re
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
CANDIDATE = MODULE.parent / 'y8_background_stack_candidate.js'
TASK = 'TASK-279'
MODULE_AT_CAPTURE = 'module-at-capture'
PROFILE = 'desktop'
VIEWPORT = [1280, 720]
DPR = 1
MAIN, CHILL = 'bad', 'classic'
MODES = (MAIN, CHILL)
MODE_SETUP = {MAIN: {'seed': 4, 'replay_style': 'screening'}, CHILL: {'seed': 7, 'replay_style': 'chill-ceiling'}}
ARMS = {'current': 'current runtime (control): nothing injected',
        'candidate': 'far background stack cache (tools/y8_background_stack_candidate.js injected per page before startGame)'}
CANDIDATE_METHODS = ('paint', 'paintMenu', 'drawFarStack', 'buildFarStack')
CANDIDATE_MARKERS = ('farStack', 'drawFarStack', 'buildFarStack')
SCENES = {'replay': 'natural seeded replay (gameplay; acceptance scene)',
          'moving-x': 'natural replay + render-time camera drive in x only (y ratio 0): the camera motion of '
                      'full-speed play where this environment starves physics; gameplay identical to replay',
          'moving-xy': 'DIAGNOSTIC: render-time camera drive in x and y (y ratio 0.1). Vertical camera motion '
                       'does not exist in the shipped game (index.html: new Screen(false) in both modes); this '
                       'scene measures the miss penalty when the far stack key changes every frame'}
ACCEPTANCE_SCENES = ('replay',)
NO_WORSE_SCENES = ('replay', 'moving-x')
MIN_MEDIAN_REDUCTION = 0.05
MAX_WORSE = 0.05
REPS = ('p1', 'p2', 'p3')
# Alternating order: control first, candidate first, control first.
SEQUENCE = [('replay', 'p1', 'current'), ('replay', 'p1', 'candidate'),
            ('replay', 'p2', 'candidate'), ('replay', 'p2', 'current'),
            ('replay', 'p3', 'current'), ('replay', 'p3', 'candidate'),
            ('moving-x', 'p1', 'current'), ('moving-x', 'p1', 'candidate'),
            ('moving-xy', 'p1', 'candidate'), ('moving-xy', 'p1', 'current')]
CAMERA_DRIVE = {'moving-x': {'amplitude_ratio': cp.CAMERA_DRIVE_AMPLITUDE_RATIO, 'steps_per_half': cp.CAMERA_DRIVE_STEPS_PER_HALF,
                             'y_ratio': 0.0},
                'moving-xy': {'amplitude_ratio': cp.CAMERA_DRIVE_AMPLITUDE_RATIO, 'steps_per_half': cp.CAMERA_DRIVE_STEPS_PER_HALF,
                              'y_ratio': cp.CAMERA_DRIVE_Y_RATIO}}

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
              'ambientGlow', 'motes', 'moteHash', 'barsVisible', 'lightmapHasLights', 'randomDraws')
MEASURED_TARGET = {
    'source': ['artifacts/TASK-277/timings.json', 'artifacts/TASK-277/cache-profile.json', 'artifacts/TASK-277/decision.json',
               'artifacts/TASK-276/stages.json', 'artifacts/TASK-278/decision.json'],
    'background_saving_ms_dpr1': {'bad': {'stationary': [23.5, 21.8], 'moving': [33.8, 40.5]},
                                  'classic': {'stationary': [23.7, 24.9], 'moving': [26.6, 40.1]}},
    'background_fraction_of_frame_dpr1': 0.24,
    'background_passes_per_frame': ['clear', 'base gradient fill', 'far crystal tile copies', 'haze fill',
                                    'near rock tile copies', 'vignette fill'],
    'steady_state_reconstruction': 'RULED_OUT in TASK-277 (0 tile/gradient builds over 60 identical + 30 shifted frames): '
                                   'the repeated cost is raster, not object construction',
    'ambient_glow_saving_ms': {'bad': [30.5, 48.1], 'classic': [43.0, 51.9]},
    'ambient_glow_invariant': 'NONE: layoutAmbientMotes uses performance.now() every frame (render/effects.js), the level-0 '
                              'source, blur levels and composite change every frame; composite-off ~ chain-off (TASK-276). '
                              'No cacheable intermediate exists; rejected as a target with measured mote-layout evidence (deps.json).',
}


def utc():
    return fc.utc()


def candidate_text():
    return CANDIDATE.read_text()


def candidate_sha():
    return fc.sha_file(CANDIDATE)


def extract_methods(text, names):
    """Method bodies (4-space class/object-literal indentation) by name; trailing commas dropped."""
    lines = text.splitlines()
    out = {}
    for name in names:
        start = next((i for i, l in enumerate(lines) if l.startswith(f'    {name}(')), None)
        if start is None:
            out[name] = None
            continue
        body = []
        for l in lines[start:]:
            body.append(l)
            if l in ('    }', '    },'):
                break
        body[-1] = '    }'
        out[name] = '\n'.join(body)
    return out


def methods_sha(text):
    m = extract_methods(text, CANDIDATE_METHODS)
    return {k: (fc.sha_bytes(v.encode()) if v else None) for k, v in m.items()}


def runtime_has_candidate(root):
    src = (Path(root) / 'render/effects.js').read_text()
    return any(m in src for m in CANDIDATE_MARKERS)


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

INSTALL_CANDIDATE = '''(src) => { (0, eval)(src); return typeof BackgroundRenderer.prototype.drawFarStack === 'function' }'''

VISUAL_BEGIN = '''(cfg) => {
    const FC = window.__featureCost
    cancelAnimationFrame(game)
    const V = window.__visual = {clock: 1000, frame: 0, samples: [], builds: 0, randomDraws: 0,
        realNow: performance.now.bind(performance)}
    performance.now = () => V.clock
    const random = Math.random
    Math.random = function() { V.randomDraws++; return random() }
    if (cfg.arm === 'candidate') {
        const build = BackgroundRenderer.prototype.buildFarStack
        BackgroundRenderer.prototype.buildFarStack = function() { V.builds++; return build.apply(this, arguments) }
    }
    return {installed: typeof BackgroundRenderer.prototype.drawFarStack === 'function'}
}'''

VISUAL_START = '''(mode) => { startGame(mode); cancelAnimationFrame(game); return typeof version !== 'undefined' ? version : null }'''

MOTE_HASH = '''const moteHash = () => { const L = visualEffects.particles.moteLayout; if (!L) return null
        let h = 2166136261; for (let k = 0; k < L.length; k++) { h = Math.imul(h ^ Math.round(L[k] * 1000), 16777619) >>> 0 } return h }'''

VISUAL_STEP = '''(n) => {
    const V = window.__visual
    ''' + MOTE_HASH + '''
    for (let i = 0; i < n; i++) {
        V.frame++; V.clock = 1000 + V.frame * 1000 / 60
        gameLoop(V.clock); cancelAnimationFrame(game)
        const sx = (typeof screen !== 'undefined' && screen && typeof screen.x === 'number') ? screen.x : null
        const sy = sx === null ? null : screen.y
        const B = visualEffects.background, t = ctx.getTransform()
        V.samples.push([V.frame, sx, sy, moteHash(), B.farStack ? B.farStack.key : null, t.a, canvas.width / width,
            t.b === 0 && t.c === 0 && t.e === 0 && t.f === 0 && (t.a === canvas.width / width || t.a === Math.fround(canvas.width / width))
            && (t.d === canvas.height / height || t.d === Math.fround(canvas.height / height))])
    }
    return V.frame
}'''

VISUAL_SHAKE = '''() => { visualEffects.screenEffects.triggerDeath(ninja.x, ninja.y); return visualEffects.screenEffects.shakeUntil }'''

VISUAL_CHECKPOINT = '''(cfg) => {
    const V = window.__visual, FC = window.__featureCost, B = visualEffects.background
    ''' + MOTE_HASH + '''
    const png = canvas.toDataURL('image/png')
    const scratch = document.createElement('canvas')
    scratch.width = canvas.width; scratch.height = canvas.height
    const sctx = scratch.getContext('2d'); const t = ctx.getTransform()
    sctx.setTransform(t.a, t.b, t.c, t.d, t.e, t.f)
    const gameCtx = B.ctx; B.ctx = sctx
    const draws = V.randomDraws
    try { if (cfg.scene === 'menu') B.paintMenu(); else B.paint() } finally { B.ctx = gameCtx }
    const bg = scratch.toDataURL('image/png')
    const stack = B.farStack ? B.farStack.canvas.toDataURL('image/png') : null
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
        lightmapHasLights: visualEffects.lightmap.hasLights, randomDraws: draws,
        randomDrawsDuringReadback: V.randomDraws - draws}
    const candidate = {farStack: B.farStack ? {key: B.farStack.key, size: [B.farStack.canvas.width, B.farStack.canvas.height]} : null,
        builds: V.builds}
    return {png, bg, stack, state, candidate}
}'''

VISUAL_SAMPLES = '''() => ({samples: window.__visual.samples, builds: window.__visual.builds, randomDraws: window.__visual.randomDraws})'''

CANDIDATE_PRESENT = '''() => typeof BackgroundRenderer.prototype.drawFarStack === 'function' || !!visualEffects.background.farStack'''


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
                  'candidate_sha256': candidate_sha(), 'candidate_methods_sha256': methods_sha(candidate_text()),
                  'network': [], 'errors': [], 'console_errors': [], **extra}


# ------------------------------------------------------------- prepare --

def hypothesis(identity):
    return {
        'task': TASK, 'utc': utc(),
        'mechanism': 'reuse/caching of invariant intermediate rendering work with explicit invalidation keys',
        'measured_target': MEASURED_TARGET,
        'chosen_target': 'background far stack = base gradient fill + far crystal tile copies + haze fill (3 of the 6 '
                         'full-frame background passes). TASK-277 measured the whole background at 22-40 ms/frame '
                         '(dpr1, both modes); its tiles and gradient objects are already cached, so the repeated work '
                         'is the raster of those passes.',
        'invariant': 'The three passes depend on LOGICAL_VIEWPORT, canvas backing size, the base transform, the '
                     'background colours, the far tile key and the far layer y shift only. The x shift is a periodic '
                     'offset applied by drawLayerTile with device-snapped 1:1 copies. Camera y is constant (0) in both '
                     'shipped modes (index.html: new Screen(false) / new Screen(false, 0); TASK-277 natural replays: '
                     'screen.y == 0 in every sampled frame).',
        'invalidation_key': ['LOGICAL_VIEWPORT.width', 'LOGICAL_VIEWPORT.height', 'canvas.width', 'canvas.height',
                             'far shift.y', 'far tile key (width|height|pixelScale)',
                             'gradientTop/Middle/Bottom', 'hazeTop/Upper/Middle/Lower/Bottom', 'crystalRock'],
        'cache_condition_not_in_key': 'the stored context transform must equal the base transform exactly (see guard); it is a '
                                      'precondition, not a key part, because it drifts per frame in bad mode',
        'expected_work_reduction': {
            'per_frame_passes': 'hit: clear + stack copies + near copies + vignette = 4 full-frame passes instead of 6; '
                                'the gradient fill and the haze fill are removed, the crystal copies are replaced by stack copies',
            'expected_ms_dpr1': 'roughly one third of the measured background cost: ~7-13 ms of a 95-110 ms frame (7-12 %) '
                                'if a gradient fill costs about as much as a tile copy; less if fills are cheaper than copies',
            'threshold': f'>= {MIN_MEDIAN_REDUCTION:.0%} median active frame-time reduction in both modes over 3 alternating '
                         f'30 s pairs, no gameplay pair worse by > {MAX_WORSE:.0%}',
            'miss_penalty': 'a key change costs the 3 passes into the stack plus the stack copies (one extra pass); '
                            'measured by the moving-xy diagnostic scene, which does not occur in the shipped game'},
        'control': {'description': 'unchanged current runtime: the served tree is `git archive HEAD` (identity.json), '
                                   'no page injection in the current arm', **{k: identity[k] for k in ('current_commit', 'current_tar_sha256')}},
        'candidate': {'file': str(CANDIDATE.relative_to(ROOT)), 'sha256': candidate_sha(), 'methods_sha256': methods_sha(candidate_text()),
                      'installation': 'page.evaluate of the file text after boot and fc.INSTRUMENT, before startGame; '
                                      'Object.assign(BackgroundRenderer.prototype, methods); shipping runtime untouched',
                      'shipping_runtime_has_candidate_methods': runtime_has_candidate(ROOT)},
        'rejected_designs_isolated': [
            {'design': 'whole-background composite memo (key includes far and near x/y shifts)',
             'reason': 'hit rate 0 % while the camera moves: TASK-277 natural replays show screen.x changing on every '
                       'classic frame (deps.json recomputes this from the sealed raws); the shipped bad mode moves the '
                       'camera too at full speed (this environment starves its physics). Never installed.'},
            {'design': 'cache the near rocks + vignette', 'reason': 'the vignette is a radial gradient blended over the '
             'shifted near tile; no shift-invariant intermediate exists. Never installed.'},
            {'design': 'cache the ambient glow composite', 'reason': MEASURED_TARGET['ambient_glow_invariant']}],
        'visual_requirement': 'exact final pixels, exact background-only (source) pixels and equal gameplay state at every '
                              'checkpoint on every tested engine; unexplained differences reject the candidate',
        'smoke_findings_before_the_run': [
            'smoke1 (candidate keyed on the raw transform floats): pixels exact at 11/11 checkpoints but 299 builds in 292 frames: the '
            'stored canvas transform changes every frame.',
            'probe_transform: bad mode drifts the base x/y scale by ~5e-8 per frame (0.66666669 -> 0.66668220 after 300 frames, '
            'draw() scale(5/11)/scale(11/5) in single precision); classic (scale 1) does not drift; a viewport configuration resets it.',
            'smoke2 (candidate keyed on sizes, tolerance guard 1e-6): 5 builds for 6 key transitions, but 1-2 pixels off by 1 LSB at two '
            'post-resize checkpoints in bad mode: the stack was copied through a drifted (non 1:1) transform.',
            'final candidate: the stack is used only when the stored transform is exactly the base (float32-equal), otherwise the three '
            'passes paint directly. Expected consequence: cache hits on every classic frame, essentially none in bad mode -> the '
            'both-modes timing rule is expected to fail in bad unless the transform drift is fixed first (a separate change).',
            'smoke3 (final candidate, chromium dpr1 seed 4): bad EXACT at 11/11 checkpoints (cacheable 0 % of frames, 6 builds for 6 '
            'key transitions); classic EXACT at 9/11 but DIFFERENT at the two checkpoints with a moving camera (screen.x -587 and -1160): '
            '58 % / 28 % of pixels off by 1-2 LSB, row-alternating values 24/26 in the direct arm = device-anchored gradient dither. '
            'The direct base-gradient and haze fills are dithered per device pixel; a cached copy translated by the x shift moves the '
            'dither pattern. Pre-registered expectation for the full run: exact wherever the far shift x is 0 (menu, bad mode, '
            'post-death frames, resizes), 1-2 LSB dither-phase differences whenever the camera has moved in classic -> the exactness '
            'criterion is expected to REJECT the candidate and timing to be omitted.'],
        'guard': 'drawFarStack paints directly unless this.ctx.getTransform() equals (canvas.width/width, 0, 0, canvas.height/height, 0, 0) '
                 'exactly or in single precision',
        'prior_experiments_not_repeated': ['TASK-265 readback oracle (REJECT)', 'TASK-265 CanvasPattern (REJECT)',
                                           'TASK-265 winding (REJECT)', 'TASK-276 frozen source/blur arms (diagnostic only)',
                                           'TASK-277 background-off / world-off ablations (diagnostic only)'],
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
                                    'candidate_sha256': candidate_sha(),
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
                'readback': 'canvas.toDataURL(image/png) + background-only scratch paint + far stack canvas, this pass only',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter'}
    args.case = visual_case(p)
    root, raw = common_raw(args, {'settings': settings, 'replay': replay, 'checkpoints': [], 'resizes': []})
    cfg = {'dpr': context['dpr'], 'input': 'mouse', 'ablate': [], 'diagnostic': True, 'replay': replay,
           'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
    pngs = {}

    def checkpoint(page, name, scene):
        r = page.evaluate(VISUAL_CHECKPOINT, {'scene': scene})
        png, bg = png_bytes(r['png']), png_bytes(r['bg'])
        entry = {'name': name, 'scene': scene, 'final_sha256': fc.sha_bytes(png), 'background_sha256': fc.sha_bytes(bg),
                 'final_pixels_sha256': pixels_sha(png), 'background_pixels_sha256': pixels_sha(bg),
                 'final_bytes': len(png), 'state': r['state'], 'candidate': r['candidate'],
                 'stack_sha256': fc.sha_bytes(png_bytes(r['stack'])) if r['stack'] else None}
        pngs[name] = (png, bg)
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
    if p['arm'] == 'candidate' and not raw['candidate_present_in_page_end']:
        raw['result'] = 'FAILED: candidate not installed'
    if p['arm'] == 'current' and raw['candidate_present_in_page_end']:
        raw['result'] = 'FAILED: candidate present in the current arm'
    path = unique_path(out / 'visual', args.case, '.json')
    fc.dump(path, raw)
    print('PASS' if raw['result'] == 'COMPLETE' else 'FAIL', args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'checkpoints', len(raw['checkpoints']), 'builds', raw.get('builds'), 'frames', raw['checkpoints'][-1]['state']['frame']
          if raw['checkpoints'] else None, flush=True)
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
        # Keep PNG files small: the current arm of seed 4 at dpr1 on chromium, plus every mismatch.
        keep = p['engine'] == 'chromium' and p['context'] == 'dpr1' and p['seed'] == 4 and p['arm'] == 'current'
        if 'current' in results[key] and 'candidate' in results[key]:
            cur, cand = results[key]['current'], results[key]['candidate']
            for a, b in zip(cur[0]['checkpoints'], cand[0]['checkpoints']):
                if not pixels_equal(a, b, 'final') or not pixels_equal(a, b, 'background'):
                    save_png(out, visual_case(dict(p, arm='current')), a['name'], cur[1].get(a['name']))
                    save_png(out, visual_case(dict(p, arm='candidate')), b['name'], cand[1].get(b['name']))
        if keep:
            for name, pair in pngs.items():
                save_png(out, visual_case(p), name, pair)
    return status


def save_png(out, case, name, pair):
    if not pair:
        return
    folder = out / 'visual' / 'png'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{case}-{name}.png').write_bytes(pair[0])
    (folder / f'{case}-{name}-background.png').write_bytes(pair[1])


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
    channel_bbox = []
    for c in range(4):
        cy, cx = np.nonzero(delta[:, :, c])
        channel_bbox.append([int(cx.min()), int(cy.min()), int(cx.max()) + 1, int(cy.max()) + 1] if cx.size else None)
    return {'differing_pixels': differing, 'fraction': differing / (ia.size[0] * ia.size[1]),
            'max_channel_delta': int(per_pixel.max()), 'delta_histogram': {int(v): int(n) for v, n in zip(values, counts)},
            'bbox': [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if xs.size else None, 'size': list(ia.size),
            'channel_bbox': channel_bbox}


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
                                   'no build counter',
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
        page.evaluate('mode => startGame(mode)', args.mode)
        try:
            page.wait_for_function(f'{fc.MARKER}.done || {fc.MARKER}.error', timeout=args.timeout_ms)
        except Exception as e:
            raw['errors'].append('timeout: ' + str(e).splitlines()[0])
        page.evaluate(f'() => {{ {fc.MARKER}.cfg.replay = "<see raw.replay>" }}')
        raw.update(page.evaluate(fc.MARKER))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['candidate_present_in_page_end'] = page.evaluate(CANDIDATE_PRESENT)
        raw['far_stack_key_end'] = page.evaluate('() => visualEffects.background.farStack ? visualEffects.background.farStack.key : null')
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
    if raw['settings']['instrumentation'].find('no readback') < 0 or 'stage_profile' in raw:
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
    if scene == 'moving-xy' and len(ys) < 10:
        raise fc.EvidenceError('moving-xy drive did not move y')


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
                        'background_equal': pixels_equal(a, b, 'background'), 'state_equal': sa == sb,
                        'final_png_bytes_equal': a['final_sha256'] == b['final_sha256'],
                        'background_png_bytes_equal': a['background_sha256'] == b['background_sha256'],
                        'final_pixels_sha256': a.get('final_pixels_sha256'), 'candidate_final_pixels_sha256': b.get('final_pixels_sha256'),
                        'background_pixels_sha256': a.get('background_pixels_sha256'), 'candidate_background_pixels_sha256': b.get('background_pixels_sha256'),
                        'comparison_unit': 'decoded RGBA pixels' if a.get('final_pixels_sha256') else 'PNG bytes',
                        'final_sha256': a['final_sha256'], 'candidate_final_sha256': b['final_sha256'],
                        'background_sha256': a['background_sha256'], 'candidate_background_sha256': b['background_sha256'],
                        'candidate_stack_sha256': b.get('stack_sha256'), 'candidate_builds': (b.get('candidate') or {}).get('builds'),
                        'candidate_key': ((b.get('candidate') or {}).get('farStack') or {}).get('key'),
                        'backing': a['state']['canvas'], 'css': a['state']['css'], 'logical': a['state']['logical'],
                        'screen': a['state']['screen'], 'particles': a['state']['particles'], 'track_points': a['state']['trackPoints'],
                        'shaking': a['state']['shaking'], 'player_glow': a['state']['playerGlow'], 'bars_visible': a['state']['barsVisible'],
                        'menu': a['state']['menu'], 'random_draws': a['state']['randomDraws']}
            if not cp_entry['state_equal']:
                cp_entry['state_differences'] = {k: [sa[k], sb[k]] for k in STATE_KEYS if sa[k] != sb[k]}
            if not (cp_entry['final_equal'] and cp_entry['background_equal'] and cp_entry['state_equal']):
                ok = False
                failures.append(f'{name}/{a["name"]}: final_equal={cp_entry["final_equal"]} background_equal={cp_entry["background_equal"]} '
                                f'state_equal={cp_entry["state_equal"]}')
                pa = out / 'visual/png' / f'{cur["case"]}-{a["name"]}.png'
                pb = out / 'visual/png' / f'{cand["case"]}-{b["name"]}.png'
                if pa.exists() and pb.exists():
                    cp_entry['final_diff'] = png_diff(pa, pb)
                    cp_entry['final_png'] = [str(pa.relative_to(out)), str(pb.relative_to(out))]
                pa, pb = pa.with_name(pa.stem + '-background.png'), pb.with_name(pb.stem + '-background.png')
                if pa.exists() and pb.exists():
                    cp_entry['background_diff'] = png_diff(pa, pb)
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
        cell['candidate_builds_total'] = cand.get('builds')
        keys = [s[4] for s in cand.get('samples', []) if s[4]]
        cell['candidate_distinct_keys'] = len(set(keys))
        cell['candidate_key_transitions'] = key_transitions(keys)
        cell['candidate_builds_equal_key_transitions'] = cell['candidate_builds_total'] == cell['candidate_key_transitions']
        cell['samples_frames'] = len(cur.get('samples', []))
        cell['camera'] = camera_dependency(cur.get('samples', []))
        cell['transform'] = transform_dependency(cur.get('samples', []))
        cell['mote_layout'] = mote_dependency(cur.get('samples', []))
        cell['random_draws_equal'] = cur.get('randomDraws') == cand.get('randomDraws')
        if not cell['random_draws_equal']:
            ok = False
            failures.append(f'{name}: Math.random draw counts differ {cur.get("randomDraws")} vs {cand.get("randomDraws")}')
        cell['result'] = 'EXACT' if ok else 'DIFFERENT'
        cells[name] = cell
    explained = []
    for c in cells.values():
        for cp in c['checkpoints']:
            if not (cp['final_equal'] and cp['background_equal']):
                moved = bool(cp['screen']) and cp['screen'][0] != 0
                small = all((cp.get(k) or {}).get('max_channel_delta', 99) <= 2 for k in ('final_diff', 'background_diff') if cp.get(k))
                explained.append({'cell': f"{c['engine']}/{c['context']}/{c['mode']}/seed{c['seed']}", 'checkpoint': cp['name'],
                                  'camera_x': cp['screen'][0] if cp['screen'] else None, 'state_equal': cp['state_equal'],
                                  'max_channel_delta': max(((cp.get(k) or {}).get('max_channel_delta') or 0) for k in ('final_diff', 'background_diff')),
                                  'explained_by_dither_phase': moved and small and cp['state_equal']})
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
            'method': 'synthetic 60 Hz clock, harness-driven gameLoop; per checkpoint: final canvas PNG sha256, background-only '
                      'scratch paint PNG sha256 (source), gameplay-state digest (%d keys); readback confined to this pass' % len(STATE_KEYS),
            'engines_tested': sorted(engines_tested), 'engines_planned': list(VISUAL_ENGINES),
            'exact_on_all_tested_engines': exact and complete_matrix, 'complete_matrix': complete_matrix,
            'coverage': coverage, 'coverage_complete': all(coverage.values()), 'failures': failures, 'cells': cells,
            'differences': explained,
            'difference_explanation': ('All pixel differences occur at checkpoints with a non-zero far x shift, with equal gameplay state '
                                       'and channel deltas <= 2: the direct base-gradient/haze fills are dithered per device pixel '
                                       '(row-alternating values), so a cached copy translated by the x shift carries a displaced dither '
                                       'pattern. Explained, but the criterion requires exact pixels: the candidate is rejected.')
            if explained and all(e['explained_by_dither_phase'] for e in explained) else
            ('no pixel differences' if not explained else 'UNEXPLAINED differences present: see differences[]'),
            'all_differences_explained': bool(explained) and all(e['explained_by_dither_phase'] for e in explained),
            'raw_count': len(raws), 'complete_count': sum(1 for r in raws.values() if r.get('result') == 'COMPLETE'),
            'failed_attempts': sorted(p for p, r in raws.items() if r.get('result') != 'COMPLETE'),
            'separate_from_timing': True}


def camera_dependency(samples):
    """Per-frame camera change rates from [frame, sx, sy, moteHash, key] samples (gameplay frames only)."""
    game = [s for s in samples if s[1] is not None]
    pairs = list(zip(game, game[1:]))
    if not pairs:
        return {'frames': len(game), 'pairs': 0}
    dx = sum(1 for a, b in pairs if a[1] != b[1])
    dy = sum(1 for a, b in pairs if a[2] != b[2])
    return {'frames': len(game), 'pairs': len(pairs), 'x_changed_fraction': dx / len(pairs), 'y_changed_fraction': dy / len(pairs),
            'y_values': sorted({s[2] for s in game})[:5], 'x_range': [min(s[1] for s in game), max(s[1] for s in game)],
            'whole_composite_hit_fraction': sum(1 for a, b in pairs if a[1] == b[1] and a[2] == b[2]) / len(pairs),
            'far_stack_hit_fraction': sum(1 for a, b in pairs if a[2] == b[2]) / len(pairs)}


def transform_dependency(samples):
    """Base-transform stability: fraction of frames whose stored transform is exactly the base (the candidate's cache condition)
    and the per-frame drift of the x scale (bad mode: draw()'s scale(s)/scale(1/s) accumulates in single precision)."""
    rows = [s for s in samples if len(s) >= 8 and s[1] is not None]
    if not rows:
        return {'frames': 0}
    a0, a1 = rows[0][5], rows[-1][5]
    return {'frames': len(rows), 'cacheable_fraction': sum(1 for s in rows if s[7]) / len(rows),
            'scale_first': a0, 'scale_last': a1, 'base_scale': rows[0][6],
            'relative_drift_per_frame': ((a1 - a0) / a0 / (len(rows) - 1)) if len(rows) > 1 else 0.0}


def key_transitions(keys):
    """Builds a single-entry cache must perform: the first key plus every change between consecutive frames."""
    return (1 + sum(1 for a, b in zip(keys, keys[1:]) if a != b)) if keys else 0


def mote_dependency(samples):
    hashes = [s[3] for s in samples if s[3] is not None]
    pairs = list(zip(hashes, hashes[1:]))
    return {'frames_with_layout': len(hashes), 'changed_fraction': (sum(1 for a, b in pairs if a != b) / len(pairs)) if pairs else None}


def task277_dependency():
    """State/dependency evidence from the sealed TASK-277 natural-replay raws (dpr1, both modes)."""
    folder = ROOT / 'artifacts/TASK-277/raw'
    out = {}
    for p in sorted(folder.glob('dpr1-*-control-replay-*.json')) if folder.exists() else []:
        r = fc.load(p)
        if r.get('result') != 'COMPLETE':
            continue
        s = r['settings']
        w = fc.split_windows(r['frames'], s['warmup_ms'], s['window_ms'], s['windows'])[0]
        t0, t1 = w[0]['t'], w[-1]['t']
        ws = [x for x in r['samples'] if t0 <= x['t'] <= t1]
        pairs = list(zip(ws, ws[1:]))
        out[str(p.relative_to(ROOT))] = {
            'sha256': fc.sha_file(p), 'mode': s['mode'], 'window_frames': len(ws),
            'x_changed_fraction': sum(1 for a, b in pairs if a['sx'] != b['sx']) / len(pairs),
            'y_changed_fraction': sum(1 for a, b in pairs if a['sy'] != b['sy']) / len(pairs),
            'y_values': sorted({x['sy'] for x in ws}), 'x_range': [min(x['sx'] for x in ws), max(x['sx'] for x in ws)],
            'whole_composite_hit_fraction': sum(1 for a, b in pairs if a['sx'] == b['sx'] and a['sy'] == b['sy']) / len(pairs),
            'far_stack_hit_fraction': sum(1 for a, b in pairs if a['sy'] == b['sy']) / len(pairs),
            'note': 'bad mode: physics starved at ~10 fps in this environment keeps the camera at 0 (TASK-277 protocol note)'
                    if s['mode'] == 'bad' else 'classic: natural camera motion'}
    return out


def build_deps(out, vv):
    source_lines = {}
    src = (ROOT / 'render/effects.js').read_text().splitlines()
    for marker in ('const seconds = performance.now() / 1000', 'getLayerShift(width, height, layer)', 'drawLayerTile(layer, width, height, shift, edgeFill)'):
        for i, l in enumerate(src, 1):
            if marker in l:
                source_lines[marker] = f'render/effects.js:{i}'
                break
    idx = (ROOT / 'index.html').read_text().splitlines()
    screens = [f'index.html:{i}: {l.strip()}' for i, l in enumerate(idx, 1) if 'new Screen(' in l]
    visual_cells = {k: {'camera': c.get('camera'), 'mote_layout': c.get('mote_layout'), 'transform': c.get('transform'),
                        'candidate_builds_total': c.get('candidate_builds_total'),
                        'candidate_distinct_keys': c.get('candidate_distinct_keys'), 'candidate_key_transitions': c.get('candidate_key_transitions'),
                        'frames': c.get('samples_frames')} for k, c in vv['cells'].items() if c.get('camera')}
    t277 = task277_dependency()
    return {'task': TASK, 'utc': utc(),
            'question': 'which intermediate background/glow work is invariant across gameplay frames?',
            'camera_vertical_motion_disabled_in_source': screens,
            'source_lines': source_lines,
            'task277_natural_replays_dpr1': t277,
            'visual_pass_synthetic_60hz': visual_cells,
            'findings': {
                'far_stack_key_stable_across_gameplay_frames': all(v['far_stack_hit_fraction'] == 1.0 for v in t277.values()) and
                all(c['camera'].get('far_stack_hit_fraction') == 1.0 for c in visual_cells.values() if c['camera'].get('pairs')),
                'whole_composite_hit_fraction_classic_natural': [v['whole_composite_hit_fraction'] for v in t277.values() if v['mode'] == 'classic'],
                'ambient_mote_layout_changes_every_frame': all(c['mote_layout']['changed_fraction'] == 1.0 for c in visual_cells.values()
                                                               if c['mote_layout'] and c['mote_layout']['changed_fraction'] is not None),
                'candidate_builds_equal_key_transitions': all(c['candidate_builds_total'] == c['candidate_key_transitions'] for c in visual_cells.values()
                                                              if c['candidate_builds_total'] is not None),
                'candidate_builds_per_frame': {k: (c['candidate_builds_total'] / c['frames']) if c['frames'] else None for k, c in visual_cells.items()},
                'base_transform_cacheable_fraction': {k: c['transform'].get('cacheable_fraction') for k, c in visual_cells.items() if c.get('transform')},
                'transform_relative_drift_per_frame': {k: c['transform'].get('relative_drift_per_frame') for k, c in visual_cells.items() if c.get('transform')}},
            'transform_drift_finding': 'draw() scales the context by scale[version] and back by 1/scale[version] every frame; the canvas '
                                       'stores the transform in single precision, so in bad mode (scale 5/11) the base transform drifts '
                                       'by ~5e-8 per frame (smoke probe: a = 0.66666669 -> 0.66668220 after 300 frames) until the next '
                                       'configureCanvasViewport. Classic (scale 1) does not drift. Any cached raster copied through a '
                                       'drifted transform resamples (smoke2: 1-2 pixels off by 1 LSB after 10 frames), so the candidate '
                                       'paints directly whenever the stored transform is not exactly the base: no caching in bad mode '
                                       'beyond the first frame after a viewport configuration.',
            'per_engine_exactness': {k: c['result'] for k, c in vv['cells'].items()},
            'engine_comparison': 'Firefox cells are EXACT in both modes (no device-anchored gradient dither; its double-precision '
                                 'transform drifts far less: cacheable fraction %s in bad). Chromium classic cells differ at every '
                                 'checkpoint with a moved camera. The blocker is engine-specific rasterisation, not the candidate '
                                 'logic.' % next((c['transform'].get('cacheable_fraction') for k, c in visual_cells.items()
                                                  if k.startswith('firefox/') and '/bad/' in k and c.get('transform')), None),
            'dither_finding': 'Chromium/Skia dithers canvas gradient fills per device pixel (smoke3/full run: the direct arm shows '
                              'row-alternating gradient values, e.g. 24/26, 112/114). A cached gradient raster is therefore exact only '
                              'when copied at device offset 0; translated by the camera x shift it differs by 1-2 LSB on most pixels.',
            'conclusion': 'The far stack (gradient + far tile + haze) is the only invariant intermediate at the two largest repeated '
                          'costs: the ambient glow has none (layout from performance.now() every frame) and a whole-background '
                          'memo hits 0 % of moving-camera frames. The far stack content is invariant but its device placement is not: '
                          'the shifting crystal tile and the screen-fixed dithered gradient/haze cannot share one translated raster '
                          'exactly, and in bad mode the drifting base transform forbids any 1:1 copy. No exact reuse exists at this cost '
                          'in the current runtime.'}


def timing_rule():
    return {'acceptance_scenes': list(ACCEPTANCE_SCENES), 'no_worse_scenes': list(NO_WORSE_SCENES),
            'min_median_reduction': MIN_MEDIAN_REDUCTION, 'max_worse': MAX_WORSE,
            'statement': f'ACCEPT timing iff, in BOTH modes, the median over the 3 alternating 30 s replay pairs of '
                         f'(control mean active frame ms - candidate mean) / control mean >= {MIN_MEDIAN_REDUCTION:.0%}, and no replay or '
                         f'moving-x pair has the candidate worse by more than {MAX_WORSE:.0%}. Modes and repetitions are never pooled. '
                         f'moving-xy is a diagnostic of the miss penalty (vertical camera motion is absent from the shipped game) and is '
                         f'reported, not pooled.'}


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
            'candidate_far_stack_key_end': candidate.get('far_stack_key_end'),
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
                       'worst_pair_worse_fraction_gameplay': max((p['worse_by_fraction'] for p in no_worse), default=None),
                       'miss_penalty_moving_xy_fraction': -scenes['moving-xy']['pairs'][0]['reduction_fraction'] if 'moving-xy' in scenes else None}
    result = 'PASS' if all(m['verdict'] == 'PASS' for m in modes.values()) else (
        'INCOMPLETE' if any(m['verdict'] is None for m in modes.values()) else 'FAIL')
    return {'task': TASK, 'utc': utc(), 'result': result, 'rule': timing_rule(), 'modes': modes,
            'protocol': {'window_ms': sorted({r['settings']['window_ms'] for r in raws.values() if 'settings' in r}),
                         'warmup_ms': sorted({r['settings']['warmup_ms'] for r in raws.values() if 'settings' in r}),
                         'sequence': SEQUENCE, 'viewport': VIEWPORT, 'dpr': DPR, 'cpu_throttle': sorted({r['settings']['cpu_throttle'] for r in raws.values() if 'settings' in r}),
                         'untraced': 'rAF intervals + read-only sampler; no readback, no tracing, no counters',
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
                                          'methods into render/effects.js and link the hashes',
                                'REJECT': 'the candidate is not integrated; the shipping runtime stays unchanged',
                                'NO_CANDIDATE': 'not applicable: a candidate existed and was tested'}[verdict],
            'reasons': reasons, 'visual': {'exact_on_all_tested_engines': visual_ok, 'engines_tested': vv.get('engines_tested'),
                                           'coverage': vv.get('coverage'), 'cells': {k: c['result'] for k, c in vv.get('cells', {}).items()}},
            'timing': {'result': timings.get('result'), 'modes': {m: {'verdict': v['verdict'],
                                                                      'median_reduction_fraction_replay': v['median_reduction_fraction_replay'],
                                                                      'worst_pair_worse_fraction_gameplay': v['worst_pair_worse_fraction_gameplay'],
                                                                      'miss_penalty_moving_xy_fraction': v['miss_penalty_moving_xy_fraction']}
                                                                  for m, v in timings.get('modes', {}).items()}},
            'candidate': {'file': str(CANDIDATE.relative_to(ROOT)), 'sha256': candidate_sha(), 'methods_sha256': methods_sha(candidate_text())},
            'integration': integration_status(verdict),
            'ticket_completion_is_not_60fps_acceptance': True,
            'not_claimed': ['60 FPS', 'release readiness', 'device results']}


def integration_status(verdict):
    src = (ROOT / 'render/effects.js').read_text()
    in_runtime = runtime_has_candidate(ROOT)
    runtime_methods = methods_sha(src)
    cand = methods_sha(candidate_text())
    linked = in_runtime and all(runtime_methods[m] == cand[m] for m in CANDIDATE_METHODS)
    return {'runtime_has_candidate_methods': in_runtime, 'runtime_methods_sha256': runtime_methods, 'candidate_methods_sha256': cand,
            'tested_bodies_equal_runtime_bodies': linked,
            'consistent_with_verdict': (verdict == 'ACCEPT' and linked) or (verdict != 'ACCEPT' and not in_runtime),
            'head': fc.git('rev-parse', 'HEAD'), 'effects_js_sha256': fc.sha_bytes(src.encode())}


def build_manifest(out, vv, timings, decision):
    identity = fc.load(out / 'identity.json')
    commands = [json.loads(l) for l in (out / 'commands.jsonl').read_text().splitlines() if l.strip()] if (out / 'commands.jsonl').exists() else []
    raws = {f'raw/{p.name}': fc.load(p) for p in sorted((out / 'raw').glob('*.json'))} if (out / 'raw').exists() else {}
    visuals = load_visual(out)
    pngs = sorted(f'visual/png/{p.name}' for p in (out / 'visual/png').glob('*.png')) if (out / 'visual/png').exists() else []
    evidence = sorted(list(raws) + list(visuals) + pngs + ['identity.json', 'hypothesis.json', 'commands.jsonl'] +
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
            'candidate_methods_sha256': methods_sha(candidate_text()), 'module_at_capture': sorted(p.name for p in (out / MODULE_AT_CAPTURE).glob('*')),
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
    fc.dump(out / 'deps.json', build_deps(out, vv))
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
        print('  ', k, c['result'], 'checkpoints', len(c['checkpoints']), 'builds', c.get('candidate_builds_total'), 'keys', c.get('candidate_distinct_keys'))
    print('timing', timings['result'])
    for mode, m in timings.get('modes', {}).items():
        print('  ', mode, m['verdict'], 'median replay reduction', m['median_reduction_fraction_replay'], 'worst gameplay worse', m['worst_pair_worse_fraction_gameplay'],
              'moving-xy miss penalty', m['miss_penalty_moving_xy_fraction'])
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
    check(hyp['candidate']['sha256'] in variants, 'hypothesis candidate sha preserved in module-at-capture')
    check(hyp['control']['current_commit'] == identity['identity']['current_commit'], 'hypothesis control == identity commit')
    # visual raws
    visuals = load_visual(out)
    for p, r in visuals.items():
        if r.get('result') != 'COMPLETE':
            continue
        s = r['settings']
        check(r['candidate_sha256'] == hyp['candidate']['sha256'], f'{p}: candidate sha matches hypothesis')
        check(r['module_sha256'] in variants, f'{p}: module variant preserved')
        check(not r.get('tree_has_candidate_methods'), f'{p}: served tree had no candidate methods')
        check(r['tree']['files_sha256'] == identity['identity']['current_files_sha256'], f'{p}: served tree == identity tree')
        if s['arm'] == 'candidate':
            check(r.get('candidate_installed') and r.get('candidate_present_in_page_end'), f'{p}: candidate installed in the candidate arm')
        else:
            check(not r.get('candidate_present_in_page_end'), f'{p}: no candidate in the current arm')
        for rz in r.get('resizes', []):
            check(rz['backing_equals_round_css_times_dpr'], f'{p}: resize {rz["requested"]} backing == round(css x dpr)')
        for c in r['checkpoints']:
            check(c['state']['dpr'] == s['dpr'], f'{p}/{c["name"]}: dpr pinned')
    vv = build_visual(out)
    check(vv['exact_on_all_tested_engines'] == vv_file['exact_on_all_tested_engines'], 'visual verdict re-derived equals file')
    check({k: c['result'] for k, c in vv['cells'].items()} == {k: c['result'] for k, c in vv_file['cells'].items()}, 'visual cell results re-derived')
    check(vv['coverage'] == vv_file['coverage'], 'visual coverage re-derived')
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
        check('stage_profile' not in r and 'readback' not in json.dumps(r['settings']['instrumentation']).replace('no readback', ''),
              f'{p}: no instrumentation in timing raw')
        check(r['candidate_sha256'] == hyp['candidate']['sha256'], f'{p}: candidate sha matches hypothesis')
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
