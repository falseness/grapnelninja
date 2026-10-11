"""Glow stage cost split on the TASK-271/272/273 stack (TASK-276).

The two live glow chains (AmbientGlowRenderer behind the ambient motes,
PlayerGlowRenderer behind the player ribbon/sparks/ring; both BloomRenderer
subclasses, the global bloom feature is off) are split into their stages:

  update     outside the chain: mote layout + direct mote fill (ambient only)
  source     renderGlow: clear the level-0 glow canvas and draw the emissive
             shapes into it through the live geometry bounds hooks
  blur       blur: three half-size downsample drawImage transfers
  composite  composite: save/transform, per-level destination clip from the
             geometry bounds, N 'lighter' drawImage upscales, restore
  exclusion  the even-odd player exclusion clip inside composite (player only)

Every arm is a page-only diagnostic hook on the current geometry-clipped
renderer (marker __featureCost, runtime untouched). Stages that consume the
source texture (blur, composite) are measured with a frozen source texture
exported once per mode from a deterministic replay (freeze action) and blitted
back in place of the live source drawing: DIAGNOSTIC REPLAY, not a shippable
runtime. Primary timing arms carry no per-call timing, no readback and no
tracing; a separate trace pass (trace action) times the stages in JS, counts
canvas operations and records Chrome trace events for the same captures.

Actions
  prepare  verified HEAD tree + environment ceiling; identity.json
  freeze   frozen source textures/bounds per mode from a deterministic replay;
           frozen/frozen.json + PNGs (readback used here only)
  capture  one timing arm (--renderer ambient|player --arm <arm>)
  run      both repetitions of every arm for --modes; commands.jsonl
  trace    profiling pass per renderer/mode: JS stage timing, op counts,
           geometry boxes, Chrome trace (traces/*.json.gz)
  report   stages.json, trace-summary.json, decision.json, manifest.json
  audit    recompute every figure from raw files, verify seals, hooks, frozen
           texture binding, trace/timing separation and no runtime marker

Prior rejected approaches (TASK-265 readback oracle, CanvasPattern composite,
winding clip) are exclusions here, not repeated. Nothing certifies 60 FPS,
physical devices or release readiness.
"""
import argparse
import base64
import bisect
from contextlib import ExitStack
import gzip
import json
from pathlib import Path
import statistics
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_cost as fc  # noqa: E402
import y8_feature_ablation as ab  # noqa: E402
import y8_chill_ablation as ch  # noqa: E402

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
TASK = 'TASK-276'
PROFILE = 'desktop'
MAIN, CHILL = ch.MAIN, ch.CHILL
MODES = (MAIN, CHILL)
# Same mode setup as TASK-274 selection.json (Main: TASK-272 screening replay seed 4;
# Chill: TASK-273 chosen segment seed 7 chill-ceiling).
MODE_SETUP = {MAIN: {'seed': 4, 'replay_style': 'screening'}, CHILL: {'seed': 7, 'replay_style': 'chill-ceiling'}}
REPS = ('r1', 'r2')
MODULE_AT_CAPTURE = 'module-at-capture'  # every module variant that executed a capture, named by sha256 prefix
RENDERERS = {
    'ambient': {'instance': 'visualEffects.ambientGlow', 'entry': 'drawScreen', 'config': 'STYLE.ambient.glow',
                'exclusion': False, 'parent_feature': 'ambient-glow',
                'note': 'AmbientGlowRenderer.drawScreen called from ParticleSystem.drawAmbientMotes once per frame; '
                        'composite() without a player: no exclusion clip'},
    'player': {'instance': 'visualEffects.playerGlow', 'entry': 'draw', 'config': 'STYLE.player.glow',
               'exclusion': True, 'parent_feature': 'player-glow',
               'note': 'PlayerGlowRenderer.draw called from drawPlayerGlowLayer once per frame; composite(ninja) clips the '
                       'player ring neighbourhood out with an even-odd path (ringClearanceRatio)'},
}
# Diagnostic arms. 'replaces' is the renderer method (or other function) replaced in the page;
# 'needs_frozen' arms blit the frozen source texture (diagnostic replay).
ARMS = {
    'source-replay': {'stage': 'source', 'needs_frozen': True, 'renderers': ('ambient', 'player'),
                      'label': 'DIAGNOSTIC REPLAY: renderGlow replaced by one opaque drawImage of the frozen level-0 source '
                               'texture plus an alpha-0 bounds rectangle (so the geometry clip stays the frozen box); blur '
                               'and composite run unchanged on identical content every frame'},
    'blur-frozen': {'stage': 'blur', 'needs_frozen': True, 'renderers': ('ambient', 'player'),
                    'label': 'DIAGNOSTIC REPLAY: blur replaced; levels 1..N filled once from the frozen texture with the '
                             'same half-size chain, then left untouched; live source and composite unchanged'},
    'composite-off': {'stage': 'composite', 'needs_frozen': False, 'renderers': ('ambient', 'player'),
                      'label': 'composite replaced by a no-op (no clip, no level upscales); source and blur unchanged'},
    'exclusion-off': {'stage': 'exclusion', 'needs_frozen': False, 'renderers': ('player',),
                      'label': 'composite called without the player: same levels, alphas, blend and geometry clip, no '
                               'even-odd exclusion path (appearance differs: diagnostic only)'},
    'chain-off': {'stage': 'chain', 'needs_frozen': False, 'renderers': ('ambient', 'player'),
                  'label': 'the whole chain entry (drawScreen / draw) replaced by a no-op; the direct mote fill and mote '
                           'layout keep running for ambient'},
    'feature-off': {'stage': 'feature', 'needs_frozen': False, 'renderers': ('ambient',),
                    'label': 'TASK-272 ambient-glow hook: ParticleSystem.drawAmbientMotes replaced (layout, direct fill and '
                             'chain all skipped); update cost = chain-off minus feature-off'},
}
ARM_ORDER = ['source-replay', 'blur-frozen', 'composite-off', 'exclusion-off', 'chain-off', 'feature-off']
CONTROL = 'control'
TRACE_CATEGORIES = ('devtools.timeline,disabled-by-default-devtools.timeline,blink.user_timing,'
                    'skia,disabled-by-default-skia,cc,gpu')
PRIOR_EXCLUSIONS = [
    {'name': 'readback oracle', 'path': 'artifacts/TASK-265/readback-oracle/decision.md',
     'verdict': 'REJECT_READBACK_HYPOTHESIS', 'excluded_here': 'no getImageData/readback in any timing arm; the freeze pass '
                                                                 'reads pixels once, outside timing'},
    {'name': 'full-source CanvasPattern composite', 'path': 'artifacts/TASK-265/glow-pattern/decision.md',
     'verdict': 'REJECT_IDENTITY_MISMATCH', 'excluded_here': 'composite keeps native drawImage; no pattern arm'},
    {'name': 'winding (nonzero) exclusion clip', 'path': 'artifacts/TASK-265/glow-winding/decision.md',
     'verdict': 'REJECT_INCONSISTENT_BENEFIT', 'excluded_here': 'the exclusion arm removes the clip entirely to bound its '
                                                                'cost; the winding variant is not re-measured'},
    {'name': 'live geometry destination clip', 'path': 'artifacts/TASK-265/live-geometry/decision.md',
     'verdict': 'PURSUE (integrated in render/effects.js)', 'excluded_here': 'all arms run on the geometry-clipped renderer; '
                                                                             'full-composite versus clipped is not re-measured'},
]


def arms_for(renderer):
    return [a for a in ARM_ORDER if renderer in ARMS[a]['renderers']]


def sequence(renderer, rep):
    """Arms in capture order: bracketing controls, candidate arms forward (r1) or reversed (r2)."""
    arms = arms_for(renderer)
    if rep == 'r2':
        arms = arms[::-1]
    return [CONTROL] + arms + [CONTROL]


def case_name(renderer, arm, mode, rep, index):
    return f'{renderer}-{arm}-{mode}-{rep}-i{index}'


def utc():
    return fc.utc()


def level0_box(dest_box, level0, canvas):
    """Frozen level-0 bounds from the observed level-0 destination box (inverse of the outward scaling)."""
    if dest_box is None:
        return None
    sx, sy = level0[0] / canvas[0], level0[1] / canvas[1]
    return [max(0, int(dest_box[0] * sx)), max(0, int(dest_box[1] * sy)),
            min(level0[0], int(dest_box[2] * sx + 0.999999)), min(level0[1], int(dest_box[3] * sy + 0.999999))]


# ------------------------------------------------------------- in-page --

# Installed after fc.INSTRUMENT (gameLoop wrapped) and before ch.SAMPLER / startGame.
STAGE_INSTRUMENT = '''(cfg) => {
    const FC = window.__featureCost
    FC.stage = {renderer: cfg.renderer, arm: cfg.arm, frozen_sha256: cfg.frozen_sha256}
    FC.stageCalls = {}
    FC.featureActive = %s
    FC.stageFlags = %s
    const count = n => { FC.stageCalls[n] = (FC.stageCalls[n] || 0) + 1 }
    const R = cfg.renderer === 'ambient' ? visualEffects.ambientGlow : visualEffects.playerGlow
    const img = FC.frozenImage || null
    const box = cfg.frozen_box || null
    if (cfg.arm === 'source-replay') {
        R.renderGlow = function(a, b, c, d, e, f, drawShapes, arg) {
            count('renderGlow:source-replay')
            const glow = this.levels[0], g = glow.ctx
            g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'source-over'; g.globalAlpha = 1
            g.drawImage(img, 0, 0, glow.canvas.width, glow.canvas.height)
            window.__geometryBegin(g)
            g.save(); g.globalAlpha = 0
            if (box) g.fillRect(box[0], box[1], box[2] - box[0], box[3] - box[1])
            g.restore()
            window.__geometryEnd(g)
        }
    } else if (cfg.arm === 'blur-frozen') {
        R.blur = function() {
            count('blur:frozen')
            if (this.__frozenBlurred) return
            this.__frozenBlurred = true
            let previous = img
            for (let i = 1; i < this.levels.length; ++i) {
                const target = this.levels[i]
                target.ctx.drawImage(previous, 0, 0, target.canvas.width, target.canvas.height)
                previous = target.canvas
            }
        }
    } else if (cfg.arm === 'composite-off') {
        R.composite = function() { count('composite:off') }
    } else if (cfg.arm === 'exclusion-off') {
        const base = Object.getPrototypeOf(Object.getPrototypeOf(R)).composite
        R.composite = function(player) { count('composite:no-exclusion'); return base.call(this, undefined) }
    } else if (cfg.arm === 'chain-off') {
        const entry = cfg.renderer === 'ambient' ? 'drawScreen' : 'draw'
        R[entry] = function() { count(entry + ':off') }
    } else if (cfg.arm === 'feature-off') {
        visualEffects.particles.drawAmbientMotes = function() { count('drawAmbientMotes:off') }
    } else if (cfg.arm !== 'control') throw new Error('unknown arm ' + cfg.arm)
    FC.ablated.push(cfg.renderer + '/' + cfg.arm)
}''' % (ab.js_object({k: v['active'] for k, v in ab.FEATURES.items()}), ab.js_object(ab.STAGE_FLAGS))

LOAD_FROZEN = '''async cfg => { const img = new Image(); img.src = cfg.data_url; await img.decode()
    window.__featureCost.frozenImage = img; return [img.naturalWidth, img.naturalHeight] }'''

RENDERER_STATE = '''() => {
    const info = R => ({shouldDraw: R.shouldDraw(), config: R.getConfig(),
        levels: R.levels.map(l => [l.canvas.width, l.canvas.height]), frozenBlurred: !!R.__frozenBlurred})
    return {ambient: info(visualEffects.ambientGlow), player: info(visualEffects.playerGlow),
        bloom: {shouldDraw: visualEffects.bloom.shouldDraw(), levels: visualEffects.bloom.levels.length},
        canvas: [canvas.width, canvas.height], neonPulse: typeof neonPulse === 'number' ? neonPulse : null} }'''

# Deterministic replay for the frozen textures: synthetic rAF timestamps and performance.now pinned
# (same clock as TASK-272 prove). The last frame's level-0 textures are read back here only.
FREEZE = '''(cfg) => {
    const FC = window.__featureCost
    cancelAnimationFrame(game)
    const realNow = performance.now.bind(performance)
    let clock = 1000
    performance.now = () => clock
    const observed = {}
    window.__geometryObserve = (renderer, i, b, full) => {
        const name = renderer === visualEffects.ambientGlow ? 'ambient' : renderer === visualEffects.playerGlow ? 'player' : 'other'
        if (!observed[name]) observed[name] = {}
        observed[name][i] = {box: b, full}
    }
    try {
        startGame(cfg.mode)
        cancelAnimationFrame(game)
        for (let i = 0; i < cfg.frames; i++) {
            clock = 1000 + i * 1000 / 60
            for (const k in observed) delete observed[k]
            gameLoop(clock); cancelAnimationFrame(game)
        }
    } finally { performance.now = realNow }
    const out = R => ({levels: R.levels.map(l => [l.canvas.width, l.canvas.height]), shouldDraw: R.shouldDraw(),
        png: R.levels.length ? R.levels[0].canvas.toDataURL('image/png') : null})
    return {frames: FC.frames.length, dispatched: FC.dispatched.length, deaths: FC.deaths.length,
        ninja: [ninja.x, ninja.y, ninja.speedX, ninja.speedY], screen: [screen.x, screen.y],
        score: scoreText.count[version], trackPoints: ninja.track.pos.length,
        particleCount: visualEffects.particles.particles.length,
        motes: visualEffects.particles.ambientMotes ? visualEffects.particles.ambientMotes.length : 0,
        canvas: [canvas.width, canvas.height], drawFrameId, observed,
        ambient: out(visualEffects.ambientGlow), player: out(visualEffects.playerGlow)}
}'''

# Trace pass only: per-stage JS submission timing, level-0 operation counts, geometry boxes,
# user-timing measures for the Chrome trace. Never installed in timing arms.
TRACE_INSTRUMENT = '''(cfg) => {
    const FC = window.__featureCost
    FC.trace = {renderer: cfg.renderer, stages: {}, ops: {}, boxes: [], frames: [], windowMark: null}
    const R = cfg.renderer === 'ambient' ? visualEffects.ambientGlow : visualEffects.playerGlow
    const T = FC.trace
    let frame = null
    const timed = (name, fn, after) => function() {
        const t0 = performance.now()
        performance.mark(name + ':start')
        try { return fn.apply(this, arguments) }
        finally {
            const dt = performance.now() - t0
            performance.measure(name, name + ':start')
            if (frame) frame[name] = (frame[name] || 0) + dt
            if (after) after.call(this)
        }
    }
    const ops = {}
    const countOps = g => {
        if (g.__countedOps) return
        g.__countedOps = true
        for (const name of ['fillRect', 'fill', 'stroke', 'drawImage', 'arc', 'clip', 'beginPath', 'fillText', 'strokeText'])
            { const original = g[name]; g[name] = function() { if (T.counting) ops[name] = (ops[name] || 0) + 1; return original.apply(this, arguments) } }
    }
    R.resize = timed('resize', R.resize)
    const renderGlow = R.renderGlow
    R.renderGlow = timed('source', function() { countOps(this.levels[0].ctx); T.counting = true
        try { return renderGlow.apply(this, arguments) } finally { T.counting = false } })
    R.blur = timed('blur', R.blur)
    R.composite = timed('composite', R.composite)
    const geometryDraw = window.__geometryDraw
    window.__geometryDraw = function(renderer, i) {
        if (renderer !== R) return geometryDraw.apply(this, arguments)
        const t0 = performance.now()
        try { return geometryDraw.apply(this, arguments) }
        finally { if (frame) frame['levelDraw'] = (frame['levelDraw'] || 0) + performance.now() - t0 }
    }
    window.__geometryObserve = (renderer, i, b, full) => {
        if (renderer === R && frame) frame.boxes.push([i, b, full]) }
    const inner = window.gameLoop
    window.gameLoop = function(t) {
        const n = FC.frames.length
        frame = {t, boxes: []}
        for (const k in ops) delete ops[k]
        const r = inner.call(this, t)
        if (FC.frames.length > n && FC.frames[n].t === t) {
            frame.ops = Object.assign({}, ops)
            frame.inWindow = FC.warmupEndMs !== null
            if (frame.inWindow && T.windowMark === null) { T.windowMark = t; performance.mark('fcWindowStart') }
            T.frames.push(frame)
        }
        frame = null
        return r
    }
}'''


# -------------------------------------------------------------- prepare --

def prepare(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = utc()
    identity = fc.build_trees(out)
    ceiling = fc.environment_ceiling(PROFILE)
    fc.dump(out / 'identity.json', {'task': TASK, 'utc_start': started, 'utc_end': utc(), 'argv': sys.argv,
                                    'identity': identity, 'environment_ceiling': ceiling,
                                    'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
                                    'chill_sha256': fc.sha_file(ch.MODULE), 'stages_sha256': fc.sha_file(MODULE),
                                    'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py')})
    print('PASS identity written', out / 'identity.json', 'HEAD', identity['current_commit'],
          'dirty_runtime=%r' % identity['current_dirty_runtime'], 'ceiling_fps=%.2f' % ceiling['average_fps'])
    return 0


# --------------------------------------------------------------- freeze --

def replay_for(mode, warmup_ms, window_ms, windows):
    total = warmup_ms + windows * window_ms
    setup = MODE_SETUP[mode]
    return ch.replay_script(setup['seed'], PROFILE, total + 1000, setup['replay_style'])


def freeze_once(root, mode, replay, frames):
    from browser_test_support import start_browser_test
    cfg = {'dpr': fc.PROFILES[PROFILE]['dpr'], 'input': 'mouse', 'ablate': [], 'diagnostic': True,
           'replay': replay, 'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
    with ExitStack() as stack:
        url, browser = start_browser_test(Path(root), stack.callback)
        ctx = fc.new_context(browser, PROFILE, MODE_SETUP[mode]['seed'], [])
        stack.callback(ctx.close)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html', wait_until='domcontentloaded')
        page.wait_for_function(fc.BOOTED, timeout=60000)
        page.evaluate(fc.INSTRUMENT, cfg)
        result = page.evaluate(FREEZE, {'mode': mode, 'frames': frames})
        result['errors'] = errors
        result['platform'] = page.evaluate(fc.DIMENSIONS)['platform']
    return result


def freeze(args):
    out = Path(args.output).resolve()
    root = ch.verified_root(out)
    frozen_dir = out / 'frozen'
    frozen_dir.mkdir(parents=True, exist_ok=True)
    started = utc()
    frames = round(args.warmup_ms * 60 / 1000)
    record = {'task': TASK, 'utc_start': started, 'argv': sys.argv, 'frames': frames,
              'clock': 'synthetic 60 Hz rAF timestamps, performance.now pinned (TASK-272 prove clock)',
              'readback': 'level-0 canvas toDataURL(image/png) once per renderer per mode in this pass only',
              'label': 'DIAGNOSTIC REPLAY source: frozen state after the warmup-equivalent frame count; identical '
                       'texture reused by every source-replay / blur-frozen arm of the mode', 'modes': {}}
    status = 0
    for mode in args.modes:
        replay = replay_for(mode, args.warmup_ms, args.window_ms, 1)
        runs = [freeze_once(root, mode, replay, frames) for _ in range(2)]
        entry = {'seed': MODE_SETUP[mode]['seed'], 'replay_style': MODE_SETUP[mode]['replay_style'],
                 'replay_sha256': fc.replay_sha256(replay), 'frames': frames, 'renderers': {},
                 'state': {k: runs[0][k] for k in ('frames', 'dispatched', 'deaths', 'ninja', 'screen', 'score',
                                                  'trackPoints', 'particleCount', 'motes', 'canvas', 'drawFrameId')},
                 'errors': runs[0]['errors'] + runs[1]['errors'], 'platform': runs[0]['platform'],
                 'repeat_state_equal': all(runs[0][k] == runs[1][k] for k in ('ninja', 'screen', 'score', 'trackPoints',
                                                                            'particleCount', 'frames', 'deaths'))}
        for name in RENDERERS:
            r = runs[0][name]
            if not r['png']:
                entry['renderers'][name] = {'error': 'renderer has no levels (never drew)'}
                status = 1
                continue
            data = base64.b64decode(r['png'].split(',', 1)[1])
            png = frozen_dir / f'{name}-{mode}.png'
            png.write_bytes(data)
            repeat_sha = fc.sha_bytes(base64.b64decode(runs[1][name]['png'].split(',', 1)[1])) if runs[1][name]['png'] else None
            observed = runs[0]['observed'].get(name, {}).get('0') or runs[0]['observed'].get(name, {}).get(0)
            dest_box = observed['box'] if observed else None
            entry['renderers'][name] = {
                'png': f'frozen/{png.name}', 'png_sha256': fc.sha_file(png), 'repeat_png_sha256': repeat_sha,
                'repeat_png_equal': repeat_sha == fc.sha_file(png), 'levels': r['levels'], 'should_draw': r['shouldDraw'],
                'level0_dest_box_observed': dest_box, 'level0_full': observed['full'] if observed else None,
                'level0_box': level0_box(dest_box, r['levels'][0], runs[0]['canvas']) if observed and not observed['full'] else None,
                'observed_levels': runs[0]['observed'].get(name)}
        record['modes'][mode] = entry
        if entry['errors'] or not entry['repeat_state_equal']:
            status = 1
        print('PASS' if not entry['errors'] else 'FAIL', 'frozen', mode, 'frames', frames,
              {n: (v.get('levels'), v.get('level0_box'), v.get('repeat_png_equal')) for n, v in entry['renderers'].items()},
              'repeat_state_equal', entry['repeat_state_equal'], flush=True)
    record['utc_end'] = utc()
    fc.dump(frozen_dir / 'frozen.json', record)
    return status


def load_frozen(out, mode, renderer):
    record = fc.load(Path(out) / 'frozen/frozen.json')
    entry = record['modes'][mode]['renderers'][renderer]
    png = Path(out) / entry['png']
    if fc.sha_file(png) != entry['png_sha256']:
        raise fc.EvidenceError('frozen texture changed since freeze')
    data_url = 'data:image/png;base64,' + base64.b64encode(png.read_bytes()).decode()
    return {'sha256': entry['png_sha256'], 'data_url': data_url, 'box': entry['level0_box'], 'levels': entry['levels'],
            'replay_sha256': record['modes'][mode]['replay_sha256'], 'png': entry['png']}


# -------------------------------------------------------------- capture --

def settings_for(args, replay, extra):
    profile = fc.PROFILES[args.profile]
    setup = MODE_SETUP[args.mode]
    return {'mode': args.mode, 'mode_name': ch.MODE_NAMES[args.mode], 'population': 'glow-stages',
            'replay_style': setup['replay_style'], 'replay_box': ch.REPLAY_STYLES[setup['replay_style']],
            'profile': args.profile, 'viewport': profile['viewport'], 'dpr': profile['dpr'],
            'is_mobile': profile['is_mobile'], 'has_touch': profile['has_touch'], 'input': profile['input'],
            'cpu_throttle': args.cpu_throttle, 'seed': setup['seed'], 'warmup_ms': args.warmup_ms,
            'window_ms': args.window_ms, 'windows': args.windows, 'replay_sha256': fc.replay_sha256(replay),
            'diagnostic': False, 'density': 'pinned to profile DPR; adaptive observe disabled',
            'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                             'PLATFORM falls back to the local adapter (no ads, instant restart on death)', **extra}


def session(args, root, raw, before_start, after_done, trace=None):
    """Shared browser session: instrument, start the mode, wait for the window, collect."""
    from browser_test_support import start_browser_test
    profile = fc.PROFILES[args.profile]
    cfg = {'dpr': profile['dpr'], 'input': profile['input'], 'ablate': [], 'diagnostic': False, 'replay': raw['replay'],
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        raw['environment'] = fc.environment(browser)
        ctx = fc.new_context(browser, args.profile, raw['settings']['seed'], raw['network'])
        stack.callback(ctx.close)
        page = ctx.new_page()
        page.on('pageerror', lambda e: raw['errors'].append(str(e)))
        page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
        cdp = ctx.new_cdp_session(page)
        cdp.send('Emulation.setCPUThrottlingRate', {'rate': args.cpu_throttle})
        page.goto(url + 'index.html', wait_until='domcontentloaded')
        page.wait_for_function(fc.BOOTED, timeout=60000)
        page.evaluate(fc.INSTRUMENT, cfg)
        before_start(page)
        page.evaluate(ch.SAMPLER)
        ended = []
        if trace is not None:
            # Fresh session on the booted page (TASK-265 trace calibration pattern) so the renderer is traced
            tcdp = ctx.new_cdp_session(page)
            tcdp.on('Tracing.dataCollected', lambda e: trace.extend(e['value']))
            tcdp.on('Tracing.tracingComplete', lambda e: ended.append(True))
            tcdp.send('Tracing.start', {'categories': TRACE_CATEGORIES, 'transferMode': 'ReportEvents'})
        page.evaluate('mode => startGame(mode)', args.mode)
        try:
            page.wait_for_function(f'{fc.MARKER}.done || {fc.MARKER}.error', timeout=args.timeout_ms)
        except Exception as e:  # keep the partial record as a failed attempt
            raw['errors'].append('timeout: ' + str(e).splitlines()[0])
        if trace is not None:
            page.evaluate('() => performance.mark("fcWindowEnd")')
            tcdp.send('Tracing.end')
            for _ in range(2400):
                if ended:
                    break
                page.wait_for_timeout(25)
        page.evaluate(f'() => {{ {fc.MARKER}.cfg.replay = "<see raw.replay>"; delete {fc.MARKER}.frozenImage }}')
        raw.update(page.evaluate(fc.MARKER))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['renderers'] = page.evaluate(RENDERER_STATE)
        after_done(page)
        raw['ended_utc'] = utc()


def check_common(raw, mode):
    if raw['errors'] or raw['error']:
        raise fc.EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw['error']]))
    if raw['dimensions']['platform'] not in ('disabled', 'absent'):
        raise fc.EvidenceError('SDK isolation failed: ' + str(raw['dimensions']['platform']))
    if raw['dimensions']['version'] != mode:
        raise fc.EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
    if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
        raise fc.EvidenceError('backing size changed during the capture')
    if len(raw['samples']) != len(raw['frames']):
        raise fc.EvidenceError(f'{len(raw["samples"])} samples for {len(raw["frames"])} active frames')


def check_arm(raw):
    """The requested arm's hook was installed, reached by draw(), and the renderer is live."""
    renderer, arm = raw['settings']['renderer'], raw['settings']['arm']
    if raw['ablated'] != [f'{renderer}/{arm}']:
        raise fc.EvidenceError(f'hook mismatch: {raw["ablated"]}')
    calls = raw['stageCalls']
    if arm == CONTROL:
        if calls:
            raise fc.EvidenceError(f'control arm has replaced calls {calls}')
    elif not calls or any(v <= 0 for v in calls.values()):
        raise fc.EvidenceError(f'arm {arm} hook never reached: {calls}')
    state = raw['renderers'][renderer]
    # chain-off/feature-off never run the chain in game: level canvases then exist only if the menu screen created them
    # (ambient motes glow on the menu; the player glow does not), so levels are required for the other arms only.
    if not state['shouldDraw'] or (arm not in ('chain-off', 'feature-off') and not state['levels']):
        raise fc.EvidenceError(f'renderer {renderer} inactive: {state}')
    if ARMS.get(arm, {}).get('needs_frozen'):
        if raw['frozen']['loaded_size'] != state['levels'][0]:
            raise fc.EvidenceError(f'frozen texture size {raw["frozen"]["loaded_size"]} != level 0 {state["levels"][0]}')
        if raw['frozen']['replay_sha256'] != raw['settings']['replay_sha256']:
            raise fc.EvidenceError('frozen replay differs from the timing replay')
    if arm == 'blur-frozen' and not state['frozenBlurred']:
        raise fc.EvidenceError('blur-frozen never filled the levels')
    if raw['renderers']['bloom']['shouldDraw']:
        raise fc.EvidenceError('global bloom unexpectedly active')
    if raw['featureActive'].get(RENDERERS[renderer]['parent_feature']) is not True:
        raise fc.EvidenceError('parent feature inactive')


def capture(args):
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    if args.renderer not in RENDERERS or (args.arm != CONTROL and args.renderer not in ARMS.get(args.arm, {}).get('renderers', ())):
        raise SystemExit(f'unknown renderer/arm {args.renderer}/{args.arm}')
    replay = replay_for(args.mode, args.warmup_ms, args.window_ms, args.windows)
    settings = settings_for(args, replay, {'renderer': args.renderer, 'arm': args.arm,
                                           'arm_label': ARMS[args.arm]['label'] if args.arm != CONTROL else 'unchanged renderer',
                                           'ablate': [f'{args.renderer}/{args.arm}'] if args.arm != CONTROL else [],
                                           'instrumentation': 'timing arm: rAF intervals + read-only sampler only; '
                                                              'no per-call timing, no readback, no tracing'})
    frozen = load_frozen(args.output, args.mode, args.renderer) if ARMS.get(args.arm, {}).get('needs_frozen') else None
    raw = {'case': args.case, 'task': TASK, 'settings': settings,
           'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
           'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
           'chill_sha256': fc.sha_file(ch.MODULE), 'stages_sha256': fc.sha_file(MODULE),
           'frozen': {k: v for k, v in frozen.items() if k != 'data_url'} if frozen else None,
           'argv': sys.argv, 'started_utc': utc(), 'replay': replay, 'network': [], 'errors': [], 'console_errors': []}

    def before_start(page):
        if frozen:
            raw['frozen']['loaded_size'] = page.evaluate(LOAD_FROZEN, {'data_url': frozen['data_url']})
        page.evaluate(STAGE_INSTRUMENT, {'renderer': args.renderer, 'arm': args.arm,
                                         'frozen_sha256': frozen['sha256'] if frozen else None,
                                         'frozen_box': frozen['box'] if frozen else None})
    exit_code = 1
    session(args, root, raw, before_start, lambda page: None)
    raw['frames_sha256'] = fc.frames_sha256(raw['frames'])
    raw['samples_sha256'] = fc.frames_sha256(raw['samples'])
    try:
        check_common(raw, args.mode)
        check_arm(raw)
        raw['summary'] = fc.summarize(raw)
        raw['density'] = ch.window_density(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw['summary'], raw['density'], raw['result'] = None, None, 'FAILED: ' + str(e)
    path = fc.raw_path(args.output, args.case)
    fc.dump(path, raw)
    c = raw['summary']['combined'] if raw['summary'] else None
    d = raw['density']
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'mode=%s backing=%s arm=%s calls=%s levels=%s' % (
              args.mode, raw['dimensions']['canvas'], args.arm, raw.get('stageCalls'),
              raw.get('renderers', {}).get(args.renderer, {}).get('levels')),
          'fps=%.2f mean_ms=%.2f p50=%.2f p95=%.2f max=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], 1000 / c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'],
              c['frame_ms']['max'], c['active_ms'], raw['summary']['deaths']) if c else '',
          'camera_travel=%.0f moving=%.2f deaths_in_window=%d' % (
              d['camera']['travel_px'], d['camera']['moving_fraction'] or 0, d['deaths_in_window']) if d else '', flush=True)
    return exit_code


def capture_argv(root, out, mode, renderer, arm, case, args):
    return [sys.executable, 'tools/y8_glow_stages.py', 'capture', '--root', root, '--output', str(out),
            '--mode', mode, '--renderer', renderer, '--arm', arm, '--case', case, '--profile', PROFILE,
            '--windows', '1', '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms)]


def run(args):
    out = Path(args.output).resolve()
    root = ch.verified_root(out)
    failures = 0
    for mode in args.modes:
        for renderer in args.renderers:
            for rep in REPS:
                for index, arm in enumerate(sequence(renderer, rep)):
                    case = case_name(renderer, arm, mode, rep, index)
                    if args.resume and ab.complete_case(ab.load_raws(out), case):
                        print('INFO resume: complete raw exists for', case, flush=True)
                        continue
                    argv = capture_argv(root, out, mode, renderer, arm, case, args)
                    failures += ab.receipt(out, f'{renderer}/{arm}/{mode}/{rep}/{index}', argv) != 0
    print(f'RUN DONE modes={args.modes} renderers={args.renderers} failed_captures={failures}', flush=True)
    return 1 if failures else 0


# ---------------------------------------------------------------- trace --

def unique_path(folder, case, suffix):
    """Never overwrite: failed or repeated attempts keep their own file."""
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f'{case}{suffix}', 1
    while path.exists():
        n += 1
        path = folder / f'{case}.attempt{n}{suffix}'
    return path


def trace(args):
    """Profiling pass: control pipeline with JS stage timing, op counts, geometry boxes and a Chrome trace."""
    out = Path(args.output).resolve()
    root = Path(ch.verified_root(out))
    (out / 'traces').mkdir(exist_ok=True)
    replay = replay_for(args.mode, args.warmup_ms, args.window_ms, args.windows)
    settings = settings_for(args, replay, {'renderer': args.renderer, 'arm': CONTROL, 'ablate': [],
                                           'instrumentation': 'TRACE PASS: per-stage performance.now timing, user-timing '
                                                              'measures, level-0 operation counts, geometry boxes, Chrome '
                                                              'tracing (' + TRACE_CATEGORIES + '); not a timing arm'})
    raw = {'case': args.case, 'task': TASK, 'settings': settings, 'pass': 'trace',
           'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
           'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
           'chill_sha256': fc.sha_file(ch.MODULE), 'stages_sha256': fc.sha_file(MODULE),
           'argv': sys.argv, 'started_utc': utc(), 'replay': replay, 'network': [], 'errors': [], 'console_errors': []}
    events = []

    def before_start(page):
        page.evaluate(STAGE_INSTRUMENT, {'renderer': args.renderer, 'arm': CONTROL, 'frozen_sha256': None, 'frozen_box': None})
        page.evaluate(TRACE_INSTRUMENT, {'renderer': args.renderer})
    session(args, root, raw, before_start, lambda page: None, trace=events)
    raw['frames_sha256'] = fc.frames_sha256(raw['frames'])
    trace_path = unique_path(out / 'traces', args.case, '.trace.json.gz')
    with gzip.open(trace_path, 'wt') as f:
        json.dump(events, f)
    raw['trace_file'] = f'traces/{trace_path.name}'
    raw['trace_events'] = len(events)
    raw['trace_sha256'] = fc.sha_file(trace_path)
    exit_code = 1
    try:
        check_common(raw, args.mode)
        if not raw['trace']['frames'] or not any(f['inWindow'] for f in raw['trace']['frames']):
            raise fc.EvidenceError('no traced window frames')
        if not events:
            raise fc.EvidenceError('empty Chrome trace')
        raw['summary'] = fc.summarize(raw)
        raw['stage_profile'] = stage_profile(raw)
        raw['trace_profile'] = trace_profile(events)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw['summary'], raw['result'] = None, 'FAILED: ' + str(e)
    path = unique_path(out / 'traces', args.case, '.json')
    fc.dump(path, raw)
    p = raw.get('stage_profile')
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, raw['result'], 'events=%d' % len(events),
          'stage_ms_per_frame=%s' % json.dumps({k: round(v['mean_ms'], 3) for k, v in p['stages'].items()}) if p else '',
          'ops=%s' % json.dumps(p['ops_per_frame']) if p else '', flush=True)
    return exit_code


def stage_profile(raw):
    """Per-stage JS submission time per window frame, operation counts and geometry boxes."""
    frames = [f for f in raw['trace']['frames'] if f['inWindow']]
    names = ('resize', 'source', 'blur', 'composite', 'levelDraw')
    stages = {}
    for n in names:
        values = [f.get(n, 0.0) for f in frames]
        ordered = sorted(values)
        stages[n] = {'mean_ms': statistics.fmean(values), 'p50_ms': fc.percentile(ordered, 50),
                     'p95_ms': fc.percentile(ordered, 95), 'max_ms': ordered[-1], 'frames': len(values)}
    composite_setup = [f.get('composite', 0.0) - f.get('levelDraw', 0.0) for f in frames]
    stages['composite_minus_level_draws'] = {'mean_ms': statistics.fmean(composite_setup), 'max_ms': max(composite_setup),
                                             'meaning': 'composite save/transform/clip path/alpha setup and restore, i.e. the '
                                                        'part of composite outside the per-level drawImage calls'}
    ops = {}
    for f in frames:
        for k, v in f['ops'].items():
            ops[k] = ops.get(k, 0) + v
    ops_per_frame = {k: v / len(frames) for k, v in ops.items()}
    levels = {}
    canvas = raw['dimensions']['canvas']
    for f in frames:
        for i, b, full in f['boxes']:
            d = levels.setdefault(str(i), {'frames': 0, 'full': 0, 'none': 0, 'area_fraction_sum': 0.0})
            d['frames'] += 1
            if full:
                d['full'] += 1
            if b is None:
                d['none'] += 1
            else:
                d['area_fraction_sum'] += max(0, b[2] - b[0]) * max(0, b[3] - b[1]) / (canvas[0] * canvas[1])
    for d in levels.values():
        d['mean_area_fraction'] = d['area_fraction_sum'] / d['frames'] if d['frames'] else None
    return {'window_frames': len(frames), 'stages': stages, 'ops_per_frame': ops_per_frame,
            'geometry_levels': levels, 'canvas': canvas, 'levels': raw['renderers'][raw['settings']['renderer']]['levels'],
            'js_timing_note': 'performance.now around synchronous canvas submission in the renderer main thread; Skia '
                              'software raster of 2D canvas runs synchronously here but no GPU completion is fenced'}


def trace_profile(events):
    """Skia / timeline events attributed to the user-timing stage spans inside the measured window."""
    spans, open_async = {}, {}
    window = {'start': None, 'end': None}
    for e in events:
        if e.get('cat') != 'blink.user_timing':
            continue
        name, ph = e.get('name'), e.get('ph')
        if name == 'fcWindowStart' and ph in ('R', 'I', 'i', 'n'):
            window['start'] = e['ts']
        elif name == 'fcWindowEnd' and ph in ('R', 'I', 'i', 'n'):
            window['end'] = e['ts']
        elif ph == 'X':
            spans.setdefault(name, []).append((e['ts'], e['ts'] + e.get('dur', 0)))
        elif ph == 'b':
            open_async[(name, e.get('id'))] = e
        elif ph == 'e':
            b = open_async.pop((name, e.get('id')), None)
            if b:
                spans.setdefault(name, []).append((b['ts'], e['ts']))
    stage_names = [n for n in ('resize', 'source', 'blur', 'composite') if n in spans]
    ordered = {n: sorted(spans[n]) for n in stage_names}
    counts = {n: {} for n in stage_names}
    totals = {}
    unattributed = {}
    lo, hi = window['start'], window['end']

    def inside(ts, n):
        s = ordered[n]
        i = bisect.bisect_right(s, (ts, float('inf'))) - 1
        return i >= 0 and s[i][0] <= ts <= s[i][1]
    for e in events:
        if e.get('ph') != 'X' or e.get('cat') == 'blink.user_timing':
            continue
        ts, dur, name = e['ts'], e.get('dur', 0), e['name']
        if lo is not None and ts < lo or hi is not None and ts > hi:
            continue
        key = f'{e.get("cat")}|{name}'
        totals[key] = totals.get(key, {'count': 0, 'dur_us': 0})
        totals[key]['count'] += 1
        totals[key]['dur_us'] += dur
        hit = next((n for n in stage_names if inside(ts, n)), None)
        if hit:
            c = counts[hit].setdefault(key, {'count': 0, 'dur_us': 0})
            c['count'] += 1
            c['dur_us'] += dur
        elif 'skia' in (e.get('cat') or ''):
            u = unattributed.setdefault(key, {'count': 0, 'dur_us': 0})
            u['count'] += 1
            u['dur_us'] += dur
    top = dict(sorted(totals.items(), key=lambda kv: -kv[1]['dur_us'])[:40])
    span_frames = {n: len(ordered[n]) for n in stage_names}
    skia_all = {k: v for k, v in totals.items() if 'SkCanvas' in k}
    skia_total_us = sum(v['dur_us'] for v in skia_all.values())
    skia_in_stages_us = sum(v['dur_us'] for n in stage_names for k, v in counts[n].items() if 'SkCanvas' in k)
    containers = {k.split('|')[-1]: v for k, v in totals.items()
                  if k.split('|')[-1] in ('LayerTreeHost::DoUpdateLayers', 'ProxyMain::BeginMainFrame', 'AnimationFrame',
                                          'FunctionCall', 'RunTask', 'Paint', 'RasterTask', 'CanvasRenderingContext2D::FinalizeFrame')}
    return {'window_us': window, 'events_total': len(events),
            'stage_spans': span_frames,
            'skia_ops_in_window': dict(sorted(skia_all.items(), key=lambda kv: -kv[1]['dur_us'])),
            'skia_total_ms': skia_total_us / 1000, 'skia_inside_glow_stage_spans_ms': skia_in_stages_us / 1000,
            'skia_inside_glow_stage_spans_fraction': (skia_in_stages_us / skia_total_us) if skia_total_us else None,
            'raster_containers': containers,
            'deferred_raster_note': 'Chromium records 2D canvas calls as paint ops and rasterises them when the frame is committed '
                                    '(LayerTreeHost::DoUpdateLayers inside ProxyMain::BeginMainFrame), after the JS stage spans have '
                                    'ended; SkCanvas events therefore fall outside the glow stage spans and cannot be attributed to '
                                    'one stage by time. drawImage/drawImageRect emit no SkCanvas event in this build, so the Skia totals under-cover '
                                    'the frame (level transfers and composites are invisible here). Per-stage raster cost is '
                                    'attributed by the untraced timing arms only.',
            'stage_span_ms_total': {n: sum(b - a for a, b in ordered[n]) / 1000 for n in stage_names},
            'per_stage_events': {n: dict(sorted(counts[n].items(), key=lambda kv: -kv[1]['dur_us'])[:25]) for n in stage_names},
            'skia_outside_glow_stages': dict(sorted(unattributed.items(), key=lambda kv: -kv[1]['dur_us'])[:25]),
            'top_events_in_window': top,
            'note': 'Chrome trace of the renderer process; SkCanvas events are the synchronous software raster of 2D canvas '
                    'calls on the main thread and nest inside the stage user-timing spans. No RasterTask/GPU events are '
                    'expected on this path (TASK-265 trace calibration); no GPU attribution is made.'}


# --------------------------------------------------------------- report --

def mean_ms(raw):
    return 1000 / raw['summary']['windows'][0]['average_fps']


def arm_record(raw, path):
    s = raw['summary']
    w = s['windows'][0]
    return {'case': raw['case'], 'raw': path, 'result': raw['result'], 'renderer': raw['settings']['renderer'],
            'arm': raw['settings']['arm'], 'arm_label': raw['settings'].get('arm_label'), 'ablated': raw['ablated'],
            'stage_calls': raw['stageCalls'], 'renderer_state': raw['renderers'][raw['settings']['renderer']],
            'bloom_active': raw['renderers']['bloom']['shouldDraw'], 'frozen': raw.get('frozen'),
            'feature_active': raw['featureActive'], 'stage_flags': raw['stageFlags'],
            'backing': raw['dimensions']['canvas'], 'replay_sha256': raw['settings']['replay_sha256'],
            'frames_sha256': raw['frames_sha256'], 'samples_sha256': raw['samples_sha256'],
            'started_utc': raw['started_utc'], 'deaths': s['deaths'], 'excluded_frames': s['excluded_frames'],
            'dispatched_inputs': s['dispatched_inputs'], 'window': w, 'mean_ms': 1000 / w['average_fps'],
            'density': raw['density'], 'stages_sha256': raw['stages_sha256'],
            'instrumentation': raw['settings']['instrumentation']}


def classify(deltas, noise_max):
    """Saving tiers on both repetitions' (control - arm) ms: REPEATED beyond noise twice, CONSISTENT same sign beyond once."""
    if any(d is None for d in deltas):
        return 'INCOMPLETE'
    if all(d > noise_max for d in deltas):
        return 'REPEATED_SAVING'
    if all(d > 0 for d in deltas) and any(d > noise_max for d in deltas):
        return 'CONSISTENT_SAVING'
    if all(d < -noise_max for d in deltas):
        return 'REPEATED_COST'
    return 'WITHIN_NOISE'


def stage_table(arms_by_rep, noise_max, renderer):
    """arms_by_rep: {rep: {arm: mean_ms, 'control': [c_a, c_b]}} -> per-stage cost rows."""
    def saving(rep, arm):
        if arm not in arms_by_rep[rep] or arms_by_rep[rep][arm] is None:
            return None
        return statistics.fmean(arms_by_rep[rep][CONTROL]) - arms_by_rep[rep][arm]
    rows = {}
    for arm in arms_for(renderer):
        d = [saving(rep, arm) for rep in REPS]
        rows[arm] = {'stage': ARMS[arm]['stage'], 'saving_ms': d, 'median_saving_ms': statistics.median(d) if None not in d else None,
                     'tier': classify(d, noise_max), 'label': ARMS[arm]['label']}
    derived = {}
    if renderer == 'ambient':
        u = [None if rows['chain-off']['saving_ms'][i] is None or rows['feature-off']['saving_ms'][i] is None
             else rows['feature-off']['saving_ms'][i] - rows['chain-off']['saving_ms'][i] for i in range(2)]
        derived['update'] = {'saving_ms': u, 'tier': classify(u, noise_max),
                             'meaning': 'feature-off minus chain-off: mote layout + direct mote fill outside the glow chain'}
    else:
        derived['update'] = {'saving_ms': [0.0, 0.0], 'tier': 'NONE_BY_CONSTRUCTION',
                             'meaning': 'the player chain has no per-frame update outside draw(); trail/spark state belongs to '
                                        'the player-trail/particles stages'}
    parts = ['source-replay', 'blur-frozen', 'composite-off']
    sums = [None if any(rows[p]['saving_ms'][i] is None for p in parts) else sum(rows[p]['saving_ms'][i] for p in parts)
            for i in range(2)]
    chain = rows['chain-off']['saving_ms']
    derived['additivity'] = {'sum_source_blur_composite_ms': sums, 'chain_off_ms': chain,
                             'discrepancy_ms': [None if s is None or c is None else s - c for s, c in zip(sums, chain)],
                             'note': 'source-replay keeps one full-level drawImage blit, so the source part is a lower bound '
                                     'and the sum may fall short of chain-off by about one level-0 transfer'}
    return {'rows': rows, 'derived': derived}


def build(out):
    raws = ab.load_raws(out)
    complete = {}
    for path, r in raws.items():
        if r.get('result') == 'COMPLETE' and r.get('pass') != 'trace':
            if r['case'] in complete:
                raise fc.EvidenceError(f'duplicate complete case {r["case"]}')
            complete[r['case']] = (path, r)
    arms, groups = {}, {}
    for case, (path, r) in complete.items():
        rec = arm_record(r, path)
        arms[case] = rec
        s = r['settings']
        groups.setdefault((s['mode'], s['renderer']), {}).setdefault(s['arm'], []).append(rec)
    prior = {}
    for p, key in (('artifacts/TASK-274/interaction.json', 'task274'),):
        if (ROOT / p).exists():
            prior[key] = {'path': p, 'sha256': fc.sha_file(ROOT / p)}
    results = {}
    for mode in MODES:
        for renderer in RENDERERS:
            expected = {rep: sequence(renderer, rep) for rep in REPS}
            by_rep, paired, missing = {}, True, []
            for rep in REPS:
                by_rep[rep] = {CONTROL: []}
                for index, arm in enumerate(expected[rep]):
                    case = case_name(renderer, arm, mode, rep, index)
                    rec = arms.get(case)
                    if rec is None:
                        missing.append(case)
                        if arm == CONTROL:
                            by_rep[rep][CONTROL].append(None)
                        else:
                            by_rep[rep][arm] = None
                        continue
                    if arm == CONTROL:
                        by_rep[rep][CONTROL].append(rec['mean_ms'])
                    else:
                        by_rep[rep][arm] = rec['mean_ms']
            group_cases = [c for c in arms if arms[c]['renderer'] == renderer and complete[c][1]['settings']['mode'] == mode]
            settings_keys = ('mode', 'replay_sha256', 'warmup_ms', 'window_ms', 'windows', 'cpu_throttle', 'seed', 'dpr', 'viewport')
            distinct = {k: sorted({json.dumps(complete[c][1]['settings'][k]) for c in group_cases}) for k in settings_keys}
            backings = sorted({tuple(arms[c]['backing']) for c in group_cases})
            trees = sorted({fc.sha_bytes(json.dumps(complete[c][1]['tree']['files_sha256'], sort_keys=True).encode()) for c in group_cases})
            paired = (not missing and all(len(v) == 1 for v in distinct.values()) and len(backings) == 1 and len(trees) == 1
                      and all(None not in by_rep[rep][CONTROL] for rep in REPS))
            control_spread = [abs(by_rep[rep][CONTROL][0] - by_rep[rep][CONTROL][1]) if None not in by_rep[rep][CONTROL] else None
                              for rep in REPS]
            # Capture order: a case whose started_utc is later than the next case of its sequence was re-captured
            # (resume after a failed attempt) outside its bracketing controls; reported, never hidden.
            order_check = {}
            for rep in REPS:
                seq = [case_name(renderer, arm, mode, rep, i) for i, arm in enumerate(expected[rep])]
                times = [arms[c]['started_utc'] if c in arms else None for c in seq]
                out = [c for c, t, nxt in zip(seq, times, times[1:] + [None]) if t and nxt and t > nxt]
                order_check[rep] = {'started_utc': times, 'in_sequence': not out, 'out_of_sequence_cases': out}
            noise_max = max(v for v in control_spread if v is not None) if any(v is not None for v in control_spread) else None
            table = stage_table(by_rep, noise_max, renderer) if paired else None
            results[f'{mode}/{renderer}'] = {
                'mode': mode, 'mode_name': ch.MODE_NAMES[mode], 'renderer': renderer, 'renderer_note': RENDERERS[renderer]['note'],
                'result': 'PAIRED' if paired else 'UNPAIRED', 'missing_cases': missing, 'distinct_settings': distinct,
                'backing': backings, 'tree_sets': trees, 'order': expected,
                'control_mean_ms': {rep: by_rep[rep][CONTROL] for rep in REPS},
                'arm_mean_ms': {rep: {a: by_rep[rep].get(a) for a in arms_for(renderer)} for rep in REPS},
                'control_spread_ms': control_spread, 'noise_max_ms': noise_max, 'capture_order': order_check,
                'stages': table['rows'] if table else None, 'derived': table['derived'] if table else None,
                'deaths_by_case': {c: arms[c]['deaths'] for c in group_cases},
                'camera_travel_by_case': {c: arms[c]['density']['camera']['travel_px'] for c in group_cases}}
    return {'raws': raws, 'complete': {c: p for c, (p, _) in complete.items()}, 'arms': arms, 'results': results, 'prior': prior}


def load_traces(out):
    traces = {}
    for p in sorted((Path(out) / 'traces').glob('*.json')):
        traces[f'traces/{p.name}'] = fc.load(p)
    return traces


def trace_summary(out, traces):
    passes = {}
    for path, t in traces.items():
        s = t['settings']
        key = f'{s["mode"]}/{s["renderer"]}'
        entry = {'raw': path, 'result': t['result'], 'case': t['case'], 'trace_file': t.get('trace_file'),
                 'trace_sha256': t.get('trace_sha256'), 'trace_events': t.get('trace_events'),
                 'instrumentation': s['instrumentation'], 'argv': t['argv'], 'started_utc': t['started_utc']}
        if t['result'] == 'COMPLETE':
            p = t['stage_profile']
            entry.update({'window_frames': p['window_frames'], 'window_mean_frame_ms': 1000 / t['summary']['windows'][0]['average_fps'],
                          'js_stage_ms_per_frame': {k: v['mean_ms'] for k, v in p['stages'].items()},
                          'js_stage_detail': p['stages'], 'ops_per_frame': p['ops_per_frame'],
                          'geometry_levels': p['geometry_levels'], 'canvas': p['canvas'], 'levels': p['levels'],
                          'level_pixels': [w * h for w, h in p['levels']],
                          'trace_profile': t['trace_profile']})
        passes[key] = entry
    return {'task': TASK, 'separate_profiling_pass': True,
            'statement': 'The trace pass is a separate set of captures (traces/*.json) from the primary timing arms (raw/*.json). '
                         'Timing raws carry no per-call timing, no readback and no Chrome tracing; their argv is the capture '
                         'action and their settings.instrumentation says so. Trace figures describe the control pipeline only.',
            'trace_categories': TRACE_CATEGORIES, 'passes': passes}


def decide(results, summary):
    stages_rank = {}
    for key, r in results.items():
        if r['result'] != 'PAIRED':
            stages_rank[key] = {'result': r['result'], 'missing': r['missing_cases']}
            continue
        rows = r['stages']
        ranked = sorted(((a, rows[a]['median_saving_ms'], rows[a]['tier']) for a in rows if a not in ('chain-off', 'feature-off')),
                        key=lambda x: -(x[1] or 0))
        stages_rank[key] = {'result': 'PAIRED', 'noise_max_ms': r['noise_max_ms'],
                            'chain_total_saving_ms': rows['chain-off']['saving_ms'], 'chain_tier': rows['chain-off']['tier'],
                            'ranked_stage_arms': [{'arm': a, 'stage': ARMS[a]['stage'], 'median_saving_ms': m, 'tier': t} for a, m, t in ranked],
                            'dominant': {'arm': ranked[0][0], 'stage': ARMS[ranked[0][0]]['stage'], 'tier': ranked[0][2],
                                         'beyond_noise_both_reps': ranked[0][2] == 'REPEATED_SAVING'} if ranked else None,
                            'update': r['derived']['update'], 'additivity': r['derived']['additivity'],
                            'out_of_sequence_cases': [c for rep in REPS for c in r['capture_order'][rep]['out_of_sequence_cases']],
                            'js_submission_ms_per_frame': summary['passes'].get(key, {}).get('js_stage_ms_per_frame')}
    paired = [v for v in stages_rank.values() if v['result'] == 'PAIRED']
    dominant = {}
    for v in paired:
        if v['dominant']:
            dominant[v['dominant']['stage']] = dominant.get(v['dominant']['stage'], 0) + 1
    verdict = ('RESOLVED' if paired and all(v['dominant'] and v['dominant']['tier'] == 'REPEATED_SAVING' for v in paired)
               else 'PARTIAL' if paired else 'UNPAIRED')
    return {'task': TASK, 'verdict': verdict,
            'verdict_meaning': {'RESOLVED': 'every paired renderer/mode has a dominant stage arm beyond control noise in both repetitions',
                                'PARTIAL': 'at least one paired renderer/mode has no dominant stage beyond noise twice; a valid '
                                           'negative/partial result', 'UNPAIRED': 'no paired population'}[verdict],
            'dominant_stage_counts': dominant, 'per_renderer_mode': stages_rank,
            'cost_split_definition': {
                'update': 'feature-off minus chain-off (ambient): mote layout and direct fill outside the chain',
                'source': 'control minus source-replay: live emissive drawing into level 0 (lower bound: the replay keeps one '
                          'opaque level-0 drawImage and an alpha-0 bounds rectangle)',
                'blur': 'control minus blur-frozen: the N-1 half-size downsample transfers',
                'composite': 'control minus composite-off: save/transform, geometry destination clips, N lighter upscales, '
                             'restore, and (player) the exclusion clip',
                'exclusion': 'control minus exclusion-off (player): the even-odd exclusion path alone, levels and clips otherwise equal'},
            'attribution': {
                'basis': 'mean active rAF interval of one window per capture, each candidate arm against the mean of the two '
                         'bracketing controls of the same repetition, mode and renderer; noise = control-control spread',
                'gpu_attribution': 'UNSUPPORTED: headless software (SwiftShader) Chromium; 2D canvas raster runs synchronously '
                                   'in the renderer; no GPU fence, no RasterTask events; trace Skia spans are CPU raster of this '
                                   'host and are not device GPU time',
                'js_timing_role': 'trace pass only, descriptive; the decision uses the untraced timing arms'},
            'previous_rejected_approaches': PRIOR_EXCLUSIONS,
            'not_claimed': ['60 FPS', 'release readiness', 'physical-device behaviour', 'that glow can be made fast',
                            'that the diagnostic replay arms are shippable'],
            'no_requirement_to_make_glow_fast': True,
            'uncertainty': ['faster arms simulate more world per window (gameoptions maxPhysicsStepsPerFrame cap): camera travel '
                            'and deaths recorded per case', 'host load varies between captures; paired deltas, not absolute FPS, '
                            'are the signal', 'source-replay replaces the live source with one opaque drawImage: the source '
                            'estimate is a lower bound', 'the frozen texture is one fixed frame; live sources vary per frame',
                            'arms listed in out_of_sequence_cases were re-captured after a failed first attempt, later than their '
                            'bracketing controls (host load may have drifted in between); the failed attempts are preserved']}


def report(args):
    out = Path(args.output).resolve()
    built = build(out)
    traces = load_traces(out)
    summary = trace_summary(out, traces)
    identity_file = fc.load(out / 'identity.json')
    identity = identity_file['identity']
    frozen = fc.load(out / 'frozen/frozen.json') if (out / 'frozen/frozen.json').exists() else None
    commands = [json.loads(line) for line in (out / 'commands.jsonl').read_text().splitlines() if line.strip()] \
        if (out / 'commands.jsonl').exists() else []
    stages = {'task': TASK, 'renderers': RENDERERS, 'arms': ARMS, 'arm_order': ARM_ORDER, 'control': CONTROL,
              'protocol': {'sequence_per_rep': {r: {rep: sequence(r, rep) for rep in REPS} for r in RENDERERS},
                           'modes': MODE_SETUP, 'profile': fc.PROFILES[PROFILE],
                           'window': 'one window per capture after warmup; mean ms = 1000 / average_fps of the window'},
              'diagnostic_replay_statement': 'source-replay and blur-frozen arms consume the frozen textures in frozen/ '
                                             '(DIAGNOSTIC REPLAY, not shippable runtime); all other arms are page-only hooks '
                                             'on the unchanged geometry-clipped renderer; the shipped runtime is untouched',
              'frozen': {m: {n: {k: v for k, v in r.items() if k != 'observed_levels'} for n, r in e['renderers'].items()}
                         for m, e in frozen['modes'].items()} if frozen else None,
              'results': built['results'], 'arms_measured': built['arms']}
    fc.dump(out / 'stages.json', stages)
    fc.dump(out / 'trace-summary.json', summary)
    decision = decide(built['results'], summary)
    fc.dump(out / 'decision.json', decision)
    evidence = sorted(['stages.json', 'trace-summary.json', 'decision.json', 'identity.json']
                      + (['commands.jsonl'] if commands else []) + list(built['raws']) + list(traces)
                      + [t['trace_file'] for t in traces.values() if t.get('trace_file') and (out / t['trace_file']).exists()]
                      + (['frozen/frozen.json'] + [r['png'] for e in frozen['modes'].values() for r in e['renderers'].values() if 'png' in r]
                         if frozen else [])
                      + list(preserved_modules(out).values()))
    raws = {k: v for k, v in built['raws'].items()}
    first = next(iter(raws.values())) if raws else None
    manifest = {
        'task': TASK, 'utc_start': min([identity_file['utc_start']] + [r['started_utc'] for r in raws.values()]), 'utc_end': utc(),
        'report_argv': sys.argv,
        'commands': [{'label': 'prepare', 'argv': identity_file['argv'], 'utc_start': identity_file['utc_start'],
                      'utc_end': identity_file['utc_end'], 'exit_code': 0}]
                    + ([{'label': 'freeze', 'argv': frozen['argv'], 'utc_start': frozen['utc_start'], 'utc_end': frozen['utc_end'],
                         'exit_code': 0 if all(not e['errors'] and e['repeat_state_equal'] for e in frozen['modes'].values()) else 1}]
                       if frozen else []) + commands,
        'source_revision': identity['current_commit'], 'source_revision_at_report': fc.git('rev-parse', 'HEAD'),
        'source_dirty_runtime': identity['current_dirty_runtime'],
        'source_dirty_at_report': fc.git('status', '--porcelain', '--untracked-files=no'),
        'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE), 'chill_sha256': fc.sha_file(ch.MODULE),
        'stages_sha256': fc.sha_file(MODULE), 'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py'),
        'stages_sha256_at_capture': sorted({r['stages_sha256'] for r in list(raws.values()) + list(traces.values())}),
        'module_at_capture': preserved_modules(out),
        'executed_hashes': {'harness_sha256_in_raws': sorted({r['harness_sha256'] for r in raws.values()}),
                            'ablation_sha256_in_raws': sorted({r['ablation_sha256'] for r in raws.values()}),
                            'chill_sha256_in_raws': sorted({r['chill_sha256'] for r in raws.values()}),
                            'stages_sha256_in_raws': sorted({r['stages_sha256'] for r in raws.values()}),
                            'stages_sha256_in_traces': sorted({r['stages_sha256'] for r in traces.values()}),
                            'note': 'every raw/trace file records the four executing modules; audit requires them to equal the '
                                    'committed modules or the preserved capture-time module'},
        'candidate_hashes': {'current_tar_sha256': identity['current_tar_sha256'], 'current_files_sha256': identity['current_files_sha256'],
                             'tree_sha256_sets_in_raws': sorted({fc.sha_bytes(json.dumps(r['tree']['files_sha256'], sort_keys=True).encode())
                                                                 for r in list(raws.values()) + list(traces.values())})},
        'frozen_textures': {m: {n: r.get('png_sha256') for n, r in e['renderers'].items()} for m, e in frozen['modes'].items()} if frozen else None,
        'inputs': {'prior_noise_reference': built['prior'], 'prior_exclusions': [{**p, 'sha256': fc.sha_file(ROOT / p['path'])
                                                                                  if (ROOT / p['path']).exists() else None} for p in PRIOR_EXCLUSIONS],
                   'task274_selection': {'path': 'artifacts/TASK-274/selection.json',
                                         'sha256': fc.sha_file(ROOT / 'artifacts/TASK-274/selection.json')
                                         if (ROOT / 'artifacts/TASK-274/selection.json').exists() else None}},
        'environment': {**(first['environment'] if first else {}), 'ceiling': identity_file['environment_ceiling']},
        'fixed': {'profile': fc.PROFILES[PROFILE], 'backing_size_by_case': {k: v['backing'] for k, v in built['arms'].items()},
                  'modes': MODE_SETUP, 'warmup_ms': first['settings']['warmup_ms'] if first else None,
                  'window_ms': first['settings']['window_ms'] if first else None,
                  'windows_per_capture': first['settings']['windows'] if first else None,
                  'cpu_throttle': first['settings']['cpu_throttle'] if first else None,
                  'input': {m: f'ch.replay_script({v["seed"]}, {PROFILE}, total_ms, {v["replay_style"]}) scheduled on the active clock; '
                               f'replay_sha256 {sorted({r["settings"]["replay_sha256"] for r in raws.values() if r["settings"]["mode"] == m})}'
                            for m, v in MODE_SETUP.items()},
                  'state': 'per-frame menu/paused/offer/hidden/ad recorded; inactive frames excluded; deaths via reStart hook; '
                           'renderer level sizes, shouldDraw, config, feature/stage flags, camera and density read in-page per arm; '
                           'frozen state: frozen/frozen.json (frames, ninja, screen, score, track, particles)',
                  'timing_vs_trace_flags': {'timing': 'y8_glow_stages.py capture ... (no trace flags; settings.instrumentation = timing arm)',
                                            'trace': 'y8_glow_stages.py trace ... (Tracing.start ' + TRACE_CATEGORIES + ')'}},
        'sdk_isolation': first['settings']['sdk_isolation'] if first else None,
        'evidence_paths': evidence, 'sha256': {name: fc.sha_file(out / name) for name in evidence},
        'failed_attempts_preserved': sorted(set([c['label'] for c in commands if c['exit_code'] != 0]
                                                + [p for p, r in list(raws.items()) + list(traces.items()) if r.get('result') != 'COMPLETE'])),
        'note': 'A successful evidence audit is separate from the performance verdict; see decision.json.'}
    fc.dump(out / 'manifest.json', manifest)
    print('PASS report written', out / 'stages.json', out / 'trace-summary.json', out / 'decision.json', out / 'manifest.json')
    print('verdict:', decision['verdict'], json.dumps(decision['dominant_stage_counts']))
    return 0


# ---------------------------------------------------------------- audit --

def preserved_modules(out):
    return {fc.sha_file(p): f'{MODULE_AT_CAPTURE}/{p.name}' for p in sorted((Path(out) / MODULE_AT_CAPTURE).glob('*.py'))}


def module_hash_ok(out, m, digest):
    return digest == m['stages_sha256'] or digest in preserved_modules(out)


def audit(args):
    out = Path(args.output).resolve()
    m = fc.load(out / 'manifest.json')
    for name, digest in m['sha256'].items():
        if fc.sha_file(out / name) != digest:
            raise fc.EvidenceError(f'SHA256 mismatch {name}')
    print(f'PASS manifest seal: {len(m["sha256"])} evidence files match SHA256')
    for mod, path in (('harness_sha256', fc.HARNESS), ('ablation_sha256', ab.MODULE), ('chill_sha256', ch.MODULE), ('stages_sha256', MODULE)):
        if fc.sha_file(path) != m[mod]:
            raise fc.EvidenceError(f'{mod} changed since report')
    print('PASS module hashes unchanged since report; capture-time stages module(s):', m['stages_sha256_at_capture'],
          'preserved at', m['module_at_capture'])
    for c in m['commands']:
        assert c['argv'] and c['utc_start'] <= c['utc_end'] and isinstance(c['exit_code'], int)
    print(f'PASS {len(m["commands"])} commands with argv/UTC start-end/exit codes; failed attempts preserved: {m["failed_attempts_preserved"]}')
    identity = fc.load(out / 'identity.json')['identity']
    frozen = fc.load(out / 'frozen/frozen.json')
    for mode, e in frozen['modes'].items():
        for n, r in e['renderers'].items():
            if fc.sha_file(out / r['png']) != r['png_sha256'] or not r['repeat_png_equal']:
                raise fc.EvidenceError(f'frozen texture {mode}/{n} unsealed or not reproducible')
        if e['errors'] or not e['repeat_state_equal']:
            raise fc.EvidenceError(f'frozen state {mode} not clean/deterministic')
    print('PASS frozen textures sealed and reproduced twice (state + PNG) for', list(frozen['modes']))
    stages = fc.load(out / 'stages.json')
    raws, complete = {}, {}
    for name in m['evidence_paths']:
        if not name.startswith('raw/'):
            continue
        raw = fc.load(out / name)
        raws[name] = raw
        for mod in ('harness_sha256', 'ablation_sha256', 'chill_sha256'):
            if raw[mod] != m[mod]:
                raise fc.EvidenceError(f'{name} captured by a different {mod}')
        if not module_hash_ok(out, m, raw['stages_sha256']):
            raise fc.EvidenceError(f'{name} captured by an unpreserved stages module')
        if fc.frames_sha256(raw['frames']) != raw['frames_sha256'] or fc.frames_sha256(raw['samples']) != raw['samples_sha256']:
            raise fc.EvidenceError(f'{name} frames/samples altered')
        if 'trace' in raw or 'stage_profile' in raw or raw.get('pass') == 'trace' or raw['argv'][1] != 'capture' \
                or any('trace' in a.lower() for a in raw['argv'][2:]) or 'no per-call timing' not in raw['settings']['instrumentation']:
            raise fc.EvidenceError(f'{name} carries trace/per-call instrumentation')
        if raw.get('result') != 'COMPLETE':
            print('INFO failed attempt preserved', name, raw.get('result'))
            continue
        if raw['case'] in complete:
            raise fc.EvidenceError(f'duplicate complete case {raw["case"]}')
        complete[raw['case']] = raw
        check_common(raw, raw['settings']['mode'])
        check_arm(raw)
        if fc.summarize(raw) != raw['summary'] or ch.window_density(raw) != raw['density']:
            raise fc.EvidenceError(f'{name} summary/density does not match recomputation')
        if raw['summary']['windows'][0]['active_ms'] < raw['settings']['window_ms']:
            raise fc.EvidenceError(f'{name} short window')
        if json.dumps(raw['tree']['files_sha256'], sort_keys=True) != json.dumps(identity['current_files_sha256'], sort_keys=True):
            raise fc.EvidenceError(f'{name} captured on a different tree')
        if raw['frozen'] and raw['frozen']['sha256'] != frozen['modes'][raw['settings']['mode']]['renderers'][raw['settings']['renderer']]['png_sha256']:
            raise fc.EvidenceError(f'{name} used a different frozen texture')
        c = raw['summary']['windows'][0]
        print(f'PASS recomputed {raw["case"]}: intervals={c["intervals"]} active_ms={c["active_ms"]:.1f} fps={c["average_fps"]:.2f} '
              f'mean_ms={1000 / c["average_fps"]:.2f} backing={raw["dimensions"]["canvas"]} calls={raw["stageCalls"]} '
              f'levels={raw["renderers"][raw["settings"]["renderer"]]["levels"]} frozen={(raw["frozen"] or {}).get("sha256", "-")[:12]} '
              f'deaths={raw["summary"]["deaths"]} travel={raw["density"]["camera"]["travel_px"]:.0f}')
    rebuilt = build(out)
    if json.dumps(rebuilt['results'], sort_keys=True) != json.dumps(stages['results'], sort_keys=True):
        raise fc.EvidenceError('stages.json results differ from recomputation')
    for key, r in rebuilt['results'].items():
        print(f'PASS {key}: {r["result"]} noise_max={r["noise_max_ms"]} controls={ {k: [round(x, 2) if x else x for x in v] for k, v in r["control_mean_ms"].items()} }')
        if r['stages']:
            for a, row in r['stages'].items():
                print(f'     {a:15s} stage={row["stage"]:9s} saving_ms={[round(x, 2) if x is not None else None for x in row["saving_ms"]]} tier={row["tier"]}')
            print(f'     update={r["derived"]["update"]["saving_ms"]} additivity={r["derived"]["additivity"]["discrepancy_ms"]}')
    traces = load_traces(out)
    for path, t in traces.items():
        if t['argv'][1] != 'trace' or t.get('pass') != 'trace':
            raise fc.EvidenceError(f'{path} is not a trace pass')
        if t.get('trace_file') and fc.sha_file(out / t['trace_file']) != t['trace_sha256']:
            raise fc.EvidenceError(f'{path} trace file altered')
        if not module_hash_ok(out, m, t['stages_sha256']):
            raise fc.EvidenceError(f'{path} traced by an unpreserved stages module')
        if t['result'] == 'COMPLETE':
            if stage_profile(t) != t['stage_profile']:
                raise fc.EvidenceError(f'{path} stage profile differs from recomputation')
            with gzip.open(out / t['trace_file'], 'rt') as f:
                events = json.load(f)
            if trace_profile(events) != t['trace_profile']:
                raise fc.EvidenceError(f'{path} trace profile differs from recomputation')
            p = t['stage_profile']
            print(f'PASS trace {t["case"]}: window_frames={p["window_frames"]} events={len(events)} '
                  f'js_ms={json.dumps({k: round(v["mean_ms"], 3) for k, v in p["stages"].items()})} ops={json.dumps(p["ops_per_frame"])} '
                  f'levels={p["levels"]} skia_spans={json.dumps(t["trace_profile"]["stage_spans"])}')
        else:
            print('INFO failed trace preserved', path, t['result'])
    if json.dumps(trace_summary(out, traces), sort_keys=True) != json.dumps(fc.load(out / 'trace-summary.json'), sort_keys=True):
        raise fc.EvidenceError('trace-summary.json differs from recomputation')
    summary = fc.load(out / 'trace-summary.json')
    if json.dumps(decide(rebuilt['results'], summary), sort_keys=True) != json.dumps(fc.load(out / 'decision.json'), sort_keys=True):
        raise fc.EvidenceError('decision.json differs from recomputation')
    print('PASS decision.json and trace-summary.json re-derived; timing argv:', sorted({r['argv'][1] for r in raws.values()}),
          'trace argv:', sorted({t['argv'][1] for t in traces.values()}))
    for p in PRIOR_EXCLUSIONS:
        if not (ROOT / p['path']).exists():
            raise fc.EvidenceError(f'prior decision missing {p["path"]}')
    print('PASS prior rejected approaches present:', [p['verdict'] for p in PRIOR_EXCLUSIONS])
    tracked = subprocess.check_output(['git', 'ls-files', '--', '*.html', '*.js', '*.css'], cwd=ROOT, text=True).split()
    runtime = [n for n in tracked if not n.startswith('tools/')]
    for name in runtime:
        if fc.MARKER in (ROOT / name).read_text(errors='replace'):
            raise fc.EvidenceError(f'diagnostic hook marker in shipped runtime: {name}')
    print('PASS no diagnostic hook marker in', len(runtime), 'shipped runtime files')
    env = m['environment']
    print('PASS environment: os=%s browser=%s playwright=%s gpu=%s ceiling_fps=%.2f' % (
        env['os'], env['browser'], env['playwright'], env['gpu']['auxAttributes'].get('glRenderer'), env['ceiling']['average_fps']))
    print('PASS evidence audit complete; performance verdict is separate:', fc.load(out / 'decision.json')['verdict'])
    return 0


# ----------------------------------------------------------------- main --

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)

    def common(p, window=True):
        p.add_argument('--output', default=f'artifacts/{TASK}')
        if window:
            p.add_argument('--warmup-ms', type=int, default=5000)
            p.add_argument('--window-ms', type=int, default=10000)
    common(sub.add_parser('prepare'), window=False)
    p = sub.add_parser('freeze'); common(p); p.add_argument('--modes', nargs='+', default=list(MODES))
    for name in ('capture', 'trace'):
        p = sub.add_parser(name); common(p)
        p.add_argument('--root', required=name == 'capture')
        p.add_argument('--mode', required=True, choices=MODES)
        p.add_argument('--renderer', required=True, choices=list(RENDERERS))
        p.add_argument('--arm', default=CONTROL)
        p.add_argument('--case', required=True)
        p.add_argument('--profile', default=PROFILE)
        p.add_argument('--windows', type=int, default=1)
        p.add_argument('--cpu-throttle', type=int, default=1)
        p.add_argument('--timeout-ms', type=int, default=240000)
    p = sub.add_parser('run'); common(p)
    p.add_argument('--modes', nargs='+', default=list(MODES)); p.add_argument('--renderers', nargs='+', default=list(RENDERERS))
    p.add_argument('--resume', action='store_true')
    common(sub.add_parser('report'), window=False)
    common(sub.add_parser('audit'), window=False)
    args = parser.parse_args(argv)
    return {'prepare': prepare, 'freeze': freeze, 'capture': capture, 'run': run, 'trace': trace,
            'report': report, 'audit': audit}[args.action](args)


if __name__ == '__main__':
    sys.exit(main())
