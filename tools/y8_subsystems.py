"""Simulation, particles/trails and HUD costs: physics-only / drawing-only diagnostics, then allocation profiling (TASK-278).

Two strictly separate evidence passes on the TASK-271/272/273 stack, never mixed:

  capture  UNINSTRUMENTED TIMING: requestAnimationFrame intervals plus the read-only
           TASK-273 sampler and a COUNT-ONLY loop probe (how many physics()/draw() calls
           each frame executed, nothing timed, no readback, no tracing). Arms:
             full-loop        the unchanged game (reference)
             simulation-only  physics runs, draw() replaced by one black fill (TASK-271
                              'all-draw' hook): what the loop costs without drawing
             drawing-only     physics frozen once the warmup ends (runFixedPhysics skipped,
                              inputs blocked); draw() keeps rendering the frozen mid-run
                              state reached by the same replay. EXPLICITLY NOT EQUIVALENT
                              to normal gameplay: nothing moves, no deaths, particle emission
                              follows the frozen state.
             particles-off / player-trail-off / hud-off   TASK-272 feature hooks in the
                              full loop (draw stages skipped, state updates kept).
  profile  INSTRUMENTED DIAGNOSTIC PASS, one session per mode, full loop under rAF:
           per-frame JS spans (runFixedPhysics, draw, particle update, trail, HUD), activity
           counters (particles drawn/emitted/allocated, ribbon points, HUD text calls), the
           CDP sampling heap profiler (all allocations, incl. those collected), a CDP CPU
           profile (self time per function, bucketed by subsystem), a trace with GC events
           (devtools.timeline MinorGC/MajorGC + v8.gc), and memory counters
           (performance.memory, Performance.getMetrics; unsupported APIs are recorded as
           'unavailable', never as zero).

Actions: prepare, capture, profile, run, report, audit. Nothing here certifies 60 FPS,
physical devices or release readiness; every shortcut is diagnostic and page-only.
"""
import argparse
from contextlib import ExitStack
import gzip
import json
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
TASK = 'TASK-278'
MODULE_AT_CAPTURE = 'module-at-capture'
PROFILE = 'desktop'
VIEWPORT = [1280, 720]
DPR = 1
MAIN, CHILL = 'bad', 'classic'
MODES = (MAIN, CHILL)
MODE_SETUP = {MAIN: {'seed': 4, 'replay_style': 'screening'}, CHILL: {'seed': 7, 'replay_style': 'chill-ceiling'}}
CONTROL = 'full-loop'
ARMS = {
    'full-loop': {'feature': None, 'ablate': [], 'state': 'live replay: physics + draw every active frame',
                  'label': 'unchanged game loop (reference)'},
    'simulation-only': {'feature': None, 'ablate': ['all-draw'],
                        'state': 'live replay, physics only: draw() replaced by one black fillRect (particle update, which lives '
                                 'inside draw(), does not run)',
                        'label': 'physics-only diagnostic (TASK-271 all-draw hook)'},
    'drawing-only': {'feature': None, 'ablate': [],
                     'state': 'FROZEN STATE: physics stepped only during the warmup, then runFixedPhysics is skipped and inputs are '
                              'blocked; draw() renders the frozen mid-run state every frame. NOT EQUIVALENT TO NORMAL GAMEPLAY',
                     'label': 'drawing-only diagnostic (frozen replayed state after warmup)'},
    'particles-off': {'feature': 'particles', 'ablate': [], 'state': 'live replay; ParticleSystem.draw/drawBehindForeground skipped',
                      'label': 'TASK-272 particles hook (emission/ageing kept)'},
    'player-trail-off': {'feature': 'player-trail', 'ablate': [], 'state': 'live replay; drawPlayerTrailLayer skipped',
                         'label': 'TASK-272 player-trail hook (track points kept)'},
    'hud-off': {'feature': 'hud', 'ablate': [], 'state': 'live replay; drawUILayer skipped',
                'label': 'TASK-272 hud hook (score text and menu button)'},
}
DIAGNOSTIC_ARMS = ('simulation-only', 'drawing-only')
FEATURE_ARMS = ('particles-off', 'player-trail-off', 'hud-off')
ARM_ORDER = ('simulation-only', 'drawing-only', 'particles-off', 'player-trail-off', 'hud-off')
REPS = ('r1', 'r2')
ALL_DRAW_ABLATED = 'draw -> clear only (all-draw)'
TRACE_CATEGORIES = 'devtools.timeline,disabled-by-default-v8.gc,v8,blink.user_timing'
GC_TIMELINE_NAMES = ('MinorGC', 'MajorGC')
HEAP_SAMPLING_INTERVAL = 16384
CPU_SAMPLING_INTERVAL_US = 1000
MATERIAL_FRACTION = 0.10
# CPU-profile / heap-profile buckets: a (url suffix, class or function) classification of self time / self bytes.
SIMULATION_URLS = ('physics.js', 'moveScreen.js', 'respawn.js', 'collision/broadphase.js', 'collision/circlewithcircle.js',
                   'collision/circlewithline.js', 'collision/linewithline.js', 'elements/factory.js')
EFFECTS_CLASS_BUCKETS = {'ParticleSystem': 'particles', 'PlayerTrailRenderer': 'player-trail', 'UIStylingHooks': 'hud',
                         'BackgroundRenderer': 'background', 'LightmapRenderer': 'lighting', 'BloomRenderer': 'glow',
                         'AmbientGlowRenderer': 'glow', 'PlayerGlowRenderer': 'glow', 'ColorGradeRenderer': 'color-grade',
                         'ScreenEffects': 'screen-effects', 'FpsCounter': 'hud', 'VisualEffects': 'drawing-other'}
AMBIENT_MOTE_FUNCTIONS = ('shouldDrawAmbientMotes', 'getAmbientMotes', 'drawAmbientMotes', 'getFrameMoteLayout', 'layoutAmbientMotes')
DRAW_NAME_MARKERS = ('draw', 'Draw', 'paint', 'Paint', 'glow', 'Glow', 'render', 'Render', 'sprite', 'Sprite', 'shape', 'Shape')


def utc():
    return fc.utc()


def case_name(mode, arm, rep, index):
    return f'{mode}-{arm}-{rep}-i{index}'


def sequence(rep):
    """Bracketed: the reference first and last, the arms between (reversed in r2)."""
    arms = list(ARM_ORDER) if rep == 'r1' else list(reversed(ARM_ORDER))
    return [CONTROL] + arms + [CONTROL]


def preserve_module(out):
    folder = Path(out) / MODULE_AT_CAPTURE
    folder.mkdir(parents=True, exist_ok=True)
    digest = fc.sha_file(MODULE)
    target = folder / f'y8_subsystems-{digest[:8]}.py'
    if not target.exists():
        shutil.copyfile(MODULE, target)
    return digest


# ------------------------------------------------------------ page code --

# Installed after fc.INSTRUMENT, ab.FEATURE_INSTRUMENT and ch.SAMPLER, before startGame, in EVERY timing arm.
# Count-only: no performance.now, no readback. Wraps the globals gameLoop reaches by name.
LOOP_PROBE = '''(cfg) => {
    const FC = window.__featureCost
    const P = FC.loopProbe = {arm: cfg.arm, label: cfg.label, kind: 'count-only loop probe (no timing, no readback)',
        physicsCalls: 0, drawCalls: 0, runFixedPhysicsCalls: 0, stepsPerFrame: [], frozen: false, frozenAtActiveMs: null,
        frozenFrames: 0, physicsCallsWhileFrozen: 0, inputsBlocked: 0, freezeState: null,
        drawReplaced: FC.ablated.includes(%s)}
    const snapshot = () => ({sx: screen.x, sy: screen.y, nx: ninja.x, ny: ninja.y, speed: [ninja.speedX, ninja.speedY],
        grapnelThrowed: !!grapnel.throwed, particles: visualEffects.particles.particles.length,
        track: ninja.track.pos.length, elements: floors.reduce((a, f) => a + f.elements.length, 0),
        score: scoreText.count[version], deaths: FC.deaths.length, activeMs: FC.activeMs, drawFrameId})
    const physics = window.physics
    window.physics = function() { P.physicsCalls++; if (P.frozen) P.physicsCallsWhileFrozen++; return physics.apply(this, arguments) }
    const rfp = window.runFixedPhysics
    window.runFixedPhysics = function() {
        P.runFixedPhysicsCalls++
        if (cfg.arm === 'drawing-only' && !P.frozen && FC.warmupEndMs !== null) {
            P.frozen = true; P.frozenAtActiveMs = FC.activeMs; P.freezeState = snapshot()
        }
        if (P.frozen) { P.frozenFrames++; P.stepsPerFrame.push(0); return }
        const before = P.physicsCalls
        try { return rfp.apply(this, arguments) } finally { P.stepsPerFrame.push(P.physicsCalls - before) }
    }
    const draw = window.draw
    window.draw = function() { P.drawCalls++; return draw.apply(this, arguments) }
    if (cfg.arm === 'drawing-only')
        for (const type of ['mousedown', 'mouseup', 'touchstart', 'touchend'])
            window.addEventListener(type, e => { if (P.frozen) { P.inputsBlocked++; e.stopImmediatePropagation() } }, true)
}''' % json.dumps(ALL_DRAW_ABLATED)

# Profile pass only. Per-frame JS spans and activity counters, memory API availability.
PROFILE_INSTRUMENT = '''() => {
    const FC = window.__featureCost
    const P = FC.profile = {spans: [], memory: {}, kind: 'INSTRUMENTED DIAGNOSTIC PASS'}
    const newFrame = () => ({physics_ms: 0, draw_ms: 0, steps: 0, particlesDrawn: 0, particleLayers: 0, particleUpdate_ms: 0,
        particlesAfterUpdate: null, particlePool: null, particlesEmitted: 0, particleObjectsAllocated: 0, trail_ms: 0, ribbons: 0,
        ribbonPoints: 0, hud_ms: 0, hudDraws: 0, hudFillText: 0, fillText: 0, strokeText: 0, measureText: 0, trackPoints: 0})
    let cur = newFrame()
    const physics = window.physics
    window.physics = function() { cur.steps++; return physics.apply(this, arguments) }
    const rfp = window.runFixedPhysics
    window.runFixedPhysics = function() { const t0 = performance.now(); try { return rfp.apply(this, arguments) } finally { cur.physics_ms += performance.now() - t0 } }
    const draw = window.draw
    window.draw = function() { const t0 = performance.now(); try { return draw.apply(this, arguments) } finally { cur.draw_ms += performance.now() - t0 } }
    const PS = ParticleSystem.prototype
    const drawLayer = PS.drawLayer
    PS.drawLayer = function(filter) { let n = 0; for (const p of this.particles) if (filter(p)) n++; cur.particlesDrawn += n; cur.particleLayers++; return drawLayer.apply(this, arguments) }
    const update = PS.update
    PS.update = function() { const t0 = performance.now(); try { return update.apply(this, arguments) } finally { cur.particleUpdate_ms += performance.now() - t0; cur.particlesAfterUpdate = this.particles.length; cur.particlePool = this.pool.length } }
    const push = PS.pushParticle
    PS.pushParticle = function() { cur.particlesEmitted++; return push.apply(this, arguments) }
    const acquire = PS.acquireParticle
    PS.acquireParticle = function() { if (this.pool.length === 0) cur.particleObjectsAllocated++; return acquire.apply(this, arguments) }
    const PT = PlayerTrailRenderer.prototype
    const ptDraw = PT.draw
    PT.draw = function() { const t0 = performance.now(); try { return ptDraw.apply(this, arguments) } finally { cur.trail_ms += performance.now() - t0 } }
    const ribbon = PT.drawRibbon
    PT.drawRibbon = function(positions, visibleStart) { cur.ribbons++; cur.ribbonPoints += Math.max(0, positions.length - (visibleStart || 0)); return ribbon.apply(this, arguments) }
    const UI = UIStylingHooks.prototype
    const uiDraw = UI.draw
    UI.draw = function() { const t0 = performance.now(); const ft = cur.fillText; try { return uiDraw.apply(this, arguments) } finally { cur.hud_ms += performance.now() - t0; cur.hudDraws++; cur.hudFillText += cur.fillText - ft } }
    const C2 = CanvasRenderingContext2D.prototype
    for (const name of ['fillText', 'strokeText', 'measureText']) { const f = C2[name]; C2[name] = function() { cur[name]++; return f.apply(this, arguments) } }
    const inner = window.gameLoop
    window.gameLoop = function(t) {
        const n = FC.frames.length
        cur = newFrame()
        const r = inner.call(this, t)
        if (FC.frames.length > n && FC.frames[n].t === t) { cur.t = t; cur.activeMs = FC.activeMs; cur.trackPoints = ninja.track.pos.length; P.spans.push(cur) }
        return r
    }
    const pm = performance.memory
    P.memory.performance_memory = (pm && typeof pm.usedJSHeapSize === 'number') ? 'available' : 'unavailable: performance.memory absent'
    P.memory.measureUserAgentSpecificMemory = typeof performance.measureUserAgentSpecificMemory !== 'function'
        ? 'unavailable: API absent' : (self.crossOriginIsolated ? 'available' : 'unavailable: requires crossOriginIsolated (not isolated here)')
    P.readMemory = () => P.memory.performance_memory === 'available'
        ? {usedJSHeapSize: performance.memory.usedJSHeapSize, totalJSHeapSize: performance.memory.totalJSHeapSize,
           jsHeapSizeLimit: performance.memory.jsHeapSizeLimit, activeMs: FC.activeMs, t: performance.now(), frames: FC.frames.length}
        : {unavailable: P.memory.performance_memory, activeMs: FC.activeMs, t: performance.now(), frames: FC.frames.length}
}'''

STATUS = '''() => { const FC = window.__featureCost; return {done: FC.done, error: FC.error, warmupEndMs: FC.warmupEndMs, activeMs: FC.activeMs, frames: FC.frames.length} }'''


# -------------------------------------------------------------- prepare --

def prepare(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = utc()
    identity = fc.build_trees(out)
    ceiling = fc.environment_ceiling(PROFILE)
    module_sha = preserve_module(out)
    fc.dump(out / 'identity.json', {'task': TASK, 'utc_start': started, 'utc_end': utc(), 'argv': sys.argv,
                                    'identity': identity, 'environment_ceiling': ceiling,
                                    'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
                                    'chill_sha256': fc.sha_file(ch.MODULE), 'module_sha256': module_sha,
                                    'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py')})
    print('PASS identity written', out / 'identity.json', 'HEAD', identity['current_commit'],
          'dirty_runtime=%r' % identity['current_dirty_runtime'], 'ceiling_fps=%.2f' % ceiling['average_fps'])
    return 0


# -------------------------------------------------------------- shared --

def common_raw(args, extra):
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    return root, {'case': args.case, 'task': TASK, 'argv': sys.argv, 'started_utc': utc(),
                  'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
                  'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
                  'chill_sha256': fc.sha_file(ch.MODULE), 'module_sha256': preserve_module(args.output),
                  'network': [], 'errors': [], 'console_errors': [], **extra}


def open_page(stack, root, raw, seed, cpu_throttle):
    from browser_test_support import start_browser_test
    url, browser = start_browser_test(root, stack.callback)
    raw['environment'] = fc.environment(browser)
    ctx = fc.new_context(browser, PROFILE, seed, raw['network'])
    stack.callback(ctx.close)
    page = ctx.new_page()
    page.on('pageerror', lambda e: raw['errors'].append(str(e)))
    page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
    cdp = ctx.new_cdp_session(page)
    cdp.send('Emulation.setCPUThrottlingRate', {'rate': cpu_throttle})
    page.goto(url + 'index.html', wait_until='domcontentloaded')
    page.wait_for_function(fc.BOOTED, timeout=60000)
    return page, ctx, cdp


def base_settings(mode, args, extra):
    setup = MODE_SETUP[mode]
    return {'mode': mode, 'mode_name': ch.MODE_NAMES[mode], 'profile': PROFILE, 'viewport': VIEWPORT, 'dpr': DPR,
            'is_mobile': False, 'has_touch': False, 'input': 'mouse', 'cpu_throttle': args.cpu_throttle, 'seed': setup['seed'],
            'replay_style': setup['replay_style'], 'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows,
            'density': 'pinned to DPR 1; adaptive observe disabled',
            'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                             'PLATFORM falls back to the local adapter (no ads, instant restart on death)', **extra}


def unique_path(folder, case, suffix):
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f'{case}{suffix}', 1
    while path.exists():
        n += 1
        path = folder / f'{case}.attempt{n}{suffix}'
    return path


# -------------------------------------------------------------- capture --

def capture(args):
    arm = ARMS[args.arm]
    setup = MODE_SETUP[args.mode]
    replay = ch.replay_script(setup['seed'], PROFILE, args.warmup_ms + args.windows * args.window_ms + 1000, setup['replay_style'])
    settings = base_settings(args.mode, args, {
        'population': 'subsystems-timing', 'arm': args.arm, 'arm_label': arm['label'], 'arm_state': arm['state'],
        'feature': arm['feature'], 'ablate': list(arm['ablate']), 'replay_sha256': fc.replay_sha256(replay), 'diagnostic': False,
        'instrumentation': 'timing arm: rAF intervals + read-only sampler + count-only loop probe; no per-call timing, '
                           'no readback, no tracing, no profiler'})
    root, raw = common_raw(args, {'pass': 'timing', 'settings': settings, 'replay': replay,
                                  'feature_spec': ab.FEATURES.get(arm['feature'])})
    cfg = {'dpr': DPR, 'input': 'mouse', 'ablate': list(arm['ablate']), 'diagnostic': False, 'replay': replay,
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    exit_code = 1
    with ExitStack() as stack:
        page, ctx, cdp = open_page(stack, root, raw, setup['seed'], args.cpu_throttle)
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate(ab.FEATURE_INSTRUMENT, ab.feature_cfg(arm['feature']))
        page.evaluate(ch.SAMPLER)
        page.evaluate(LOOP_PROBE, {'arm': args.arm, 'label': arm['state']})
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
        raw['probe_summary'] = probe_summary(raw)
        check_probe(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw.setdefault('summary', None)
        raw.setdefault('density', None)
        raw.setdefault('probe_summary', None)
        raw['result'] = 'FAILED: ' + str(e)
    path = fc.raw_path(args.output, args.case)
    fc.dump(path, raw)
    c = raw['summary']['combined'] if raw.get('summary') else None
    d = raw.get('density')
    ps = raw.get('probe_summary') or {}
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'backing=%s' % raw['dimensions']['canvas'],
          'fps=%.2f mean_ms=%.2f p50=%.2f p95=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], 1000 / c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'], c['active_ms'],
              raw['summary']['deaths']) if c else '',
          'travel=%.0f' % d['camera']['travel_px'] if d else '',
          'steps/frame=%s frozen=%s' % (ps.get('window_steps_per_frame_mean'), ps.get('frozen')), flush=True)
    return exit_code


def expected_ablated(arm):
    spec = ARMS[arm]
    out = [ALL_DRAW_ABLATED] if 'all-draw' in spec['ablate'] else []
    if spec['feature']:
        out.append(ab.FEATURES[spec['feature']]['removes'])
    return out


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
    if raw['dimensions']['dpr'] != DPR or raw['dimensions']['viewport'] != VIEWPORT:
        raise fc.EvidenceError('viewport/dpr differ from the fixed context')
    if raw['ablated'] != expected_ablated(s['arm']):
        raise fc.EvidenceError(f'hook mismatch: installed {raw["ablated"]} expected {expected_ablated(s["arm"])}')
    if s['feature'] and not raw['skipped'].get(s['feature']):
        raise fc.EvidenceError('disabled hook was never reached by draw()')
    if len(raw['samples']) != len(raw['frames']):
        raise fc.EvidenceError(f'{len(raw["samples"])} samples for {len(raw["frames"])} active frames')
    if 'profile' in raw or 'stage_profile' in raw or 'trace_profile' in raw:
        raise fc.EvidenceError('timing raw carries profile instrumentation')
    if not raw.get('loopProbe'):
        raise fc.EvidenceError('loop probe missing')


def window_frame_indices(raw):
    s = raw['settings']
    w = fc.split_windows(raw['frames'], s['warmup_ms'], s['window_ms'], s['windows'])[0]
    t0, t1 = w[0]['t'], w[-1]['t']
    return [i for i, f in enumerate(raw['frames']) if t0 <= f['t'] <= t1]


def probe_summary(raw):
    """What the loop executed, overall and inside the measured window (steps per frame index-aligned with frames)."""
    p = raw['loopProbe']
    steps = p['stepsPerFrame']
    idx = window_frame_indices(raw)
    window_steps = [steps[i] for i in idx if i < len(steps)]
    return {'arm': p['arm'], 'kind': p['kind'], 'physics_calls': p['physicsCalls'], 'draw_calls': p['drawCalls'],
            'run_fixed_physics_calls': p['runFixedPhysicsCalls'], 'frames_recorded': len(raw['frames']),
            'steps_per_frame_entries': len(steps), 'draw_replaced': p['drawReplaced'],
            'window_frames': len(idx), 'window_steps_total': sum(window_steps),
            'window_steps_per_frame_mean': statistics.fmean(window_steps) if window_steps else None,
            'window_steps_histogram': {str(k): window_steps.count(k) for k in sorted(set(window_steps))},
            'frozen': p['frozen'], 'frozen_at_active_ms': p['frozenAtActiveMs'], 'frozen_frames': p['frozenFrames'],
            'physics_calls_while_frozen': p['physicsCallsWhileFrozen'], 'inputs_blocked': p['inputsBlocked'],
            'freeze_state': p['freezeState'], 'warmup_end_ms': raw.get('warmupEndMs'),
            'executes': {'physics': p['physicsCalls'] > 0 and not p['frozen'],
                         'physics_in_window': sum(window_steps) > 0,
                         'draw': p['drawCalls'] > 0 and not p['drawReplaced'],
                         'draw_replaced_by_clear': p['drawReplaced']},
            'timing_represents': ('frozen state rendering (not gameplay)' if p['frozen'] else
                                  'physics without drawing (not gameplay)' if p['drawReplaced'] else 'active replayed gameplay')}


def check_probe(raw):
    arm = raw['settings']['arm']
    ps = raw['probe_summary']
    if ps['draw_calls'] < ps['frames_recorded'] or ps['run_fixed_physics_calls'] < ps['frames_recorded']:
        raise fc.EvidenceError('probe: fewer draw/runFixedPhysics calls than active frames')
    if arm == 'drawing-only':
        if not ps['frozen'] or ps['physics_calls_while_frozen'] != 0 or ps['frozen_at_active_ms'] is None:
            raise fc.EvidenceError('drawing-only: physics not frozen cleanly')
        if ps['window_steps_total'] != 0 or ps['frozen_at_active_ms'] > ps['warmup_end_ms']:
            raise fc.EvidenceError('drawing-only: physics steps inside the measured window')
        if ps['draw_replaced'] or not ps['freeze_state']:
            raise fc.EvidenceError('drawing-only: draw replaced or no freeze snapshot')
    else:
        if ps['frozen'] or ps['window_steps_total'] == 0:
            raise fc.EvidenceError(f'{arm}: physics did not run in the window')
        if ps['draw_replaced'] != (arm == 'simulation-only'):
            raise fc.EvidenceError(f'{arm}: draw replacement state wrong')
        if ps['inputs_blocked']:
            raise fc.EvidenceError(f'{arm}: inputs blocked')


# -------------------------------------------------------------- profile --

def profile(args):
    setup = MODE_SETUP[args.mode]
    replay = ch.replay_script(setup['seed'], PROFILE, args.warmup_ms + args.windows * args.window_ms + 1000, setup['replay_style'])
    settings = base_settings(args.mode, args, {
        'population': 'subsystems-profile', 'arm': CONTROL, 'replay_sha256': fc.replay_sha256(replay), 'diagnostic': True,
        'instrumentation': 'INSTRUMENTED DIAGNOSTIC PASS: per-frame JS spans (runFixedPhysics, draw, particle update, trail, HUD), '
                           'activity counters, CDP sampling heap profiler (%d B, collected objects included), CDP CPU profile '
                           '(%d us), Tracing (%s), Performance.getMetrics and performance.memory samples; frame intervals of '
                           'this pass are never used as timing evidence' % (HEAP_SAMPLING_INTERVAL, CPU_SAMPLING_INTERVAL_US, TRACE_CATEGORIES),
        'trace_categories': TRACE_CATEGORIES, 'heap_sampling_interval': HEAP_SAMPLING_INTERVAL,
        'cpu_sampling_interval_us': CPU_SAMPLING_INTERVAL_US})
    root, raw = common_raw(args, {'pass': 'profile', 'settings': settings, 'replay': replay})
    cfg = {'dpr': DPR, 'input': 'mouse', 'ablate': [], 'diagnostic': False, 'replay': replay,
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    out = Path(args.output)
    trace, ended = [], []
    exit_code = 1
    with ExitStack() as stack:
        page, ctx, cdp = open_page(stack, root, raw, setup['seed'], args.cpu_throttle)
        cdp.send('Performance.enable')
        cdp.send('HeapProfiler.enable')
        cdp.send('Profiler.enable')
        cdp.send('Profiler.setSamplingInterval', {'interval': CPU_SAMPLING_INTERVAL_US})
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate(ab.FEATURE_INSTRUMENT, ab.feature_cfg(None))
        page.evaluate(ch.SAMPLER)
        page.evaluate(PROFILE_INSTRUMENT)
        raw['memory_api'] = page.evaluate(f'() => {fc.MARKER}.profile.memory')
        raw['memory_api']['measureUserAgentSpecificMemory_call'] = page.evaluate('''async () => {
            if (typeof performance.measureUserAgentSpecificMemory !== 'function') return 'unavailable: API absent'
            try { const r = await performance.measureUserAgentSpecificMemory(); return {available: true, bytes: r.bytes} }
            catch (e) { return 'unavailable: ' + String(e) } }''')
        raw['memory_samples'] = []
        raw['metrics_samples'] = []

        def sample_memory(label):
            m = page.evaluate(f'() => {fc.MARKER}.profile.readMemory()')
            m['label'] = label
            raw['memory_samples'].append(m)
            metrics = cdp.send('Performance.getMetrics')['metrics']
            raw['metrics_samples'].append({'label': label, 'activeMs': m['activeMs'], 'frames': m['frames'],
                                           'metrics': {x['name']: x['value'] for x in metrics}})
        sample_memory('before-start')
        tcdp = ctx.new_cdp_session(page)
        tcdp.on('Tracing.dataCollected', lambda e: trace.extend(e['value']))
        tcdp.on('Tracing.tracingComplete', lambda e: ended.append(True))
        tcdp.send('Tracing.start', {'categories': TRACE_CATEGORIES, 'transferMode': 'ReportEvents'})
        raw['profiling'] = {'started_active_ms': None, 'stopped_active_ms': None, 'polls': 0}
        page.evaluate('mode => startGame(mode)', args.mode)
        started = False
        t_begin = time.monotonic()
        last_sample = t_begin
        status = None
        while time.monotonic() - t_begin < args.timeout_ms / 1000:
            status = page.evaluate(STATUS)
            raw['profiling']['polls'] += 1
            if not started and status['warmupEndMs'] is not None:
                cdp.send('HeapProfiler.startSampling', {'samplingInterval': HEAP_SAMPLING_INTERVAL,
                                                        'includeObjectsCollectedByMajorGC': True,
                                                        'includeObjectsCollectedByMinorGC': True})
                cdp.send('Profiler.start')
                page.evaluate('() => performance.mark("fcWindowStart")')
                raw['profiling']['started_active_ms'] = page.evaluate(STATUS)['activeMs']
                sample_memory('window-start')
                started = True
            if status['done'] or status['error']:
                break
            if time.monotonic() - last_sample >= 1.0:
                sample_memory('periodic')
                last_sample = time.monotonic()
            page.wait_for_timeout(100)
        else:
            raw['errors'].append('timeout waiting for the measured window')
        if started:
            page.evaluate('() => performance.mark("fcWindowEnd")')
            raw['profiling']['stopped_active_ms'] = page.evaluate(STATUS)['activeMs']
            sample_memory('window-end')
            cpu = cdp.send('Profiler.stop')['profile']
            heap = cdp.send('HeapProfiler.stopSampling')['profile']
        else:
            cpu = heap = None
        tcdp.send('Tracing.end')
        for _ in range(2400):
            if ended:
                break
            page.wait_for_timeout(25)
        page.evaluate(f'() => {{ {fc.MARKER}.cfg.replay = "<see raw.replay>"; delete {fc.MARKER}.profile.readMemory }}')
        raw.update(page.evaluate(fc.MARKER))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['ended_utc'] = utc()
    traces = out / 'traces'
    traces.mkdir(parents=True, exist_ok=True)
    trace_path = unique_path(traces, args.case, '.trace.json.gz')
    with gzip.open(trace_path, 'wt') as f:
        json.dump(trace, f)
    raw['trace_file'] = str(trace_path.relative_to(out))
    raw['trace_sha256'] = fc.sha_file(trace_path)
    raw['trace_events'] = len(trace)
    raw['trace_complete'] = bool(ended)
    for name, data in (('cpuprofile', cpu), ('heapprofile', heap)):
        path = unique_path(traces, args.case, f'.{name}.json.gz')
        with gzip.open(path, 'wt') as f:
            json.dump(data, f)
        raw[f'{name}_file'] = str(path.relative_to(out))
        raw[f'{name}_sha256'] = fc.sha_file(path)
    raw['frames_sha256'] = fc.frames_sha256(raw['frames'])
    try:
        check_profile_raw(raw, cpu, heap)
        raw['summary'] = fc.summarize(raw)
        raw['density'] = ch.window_density(raw)
        raw['analysis'] = analyze_profile(raw, trace, cpu, heap, root)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw.setdefault('summary', None)
        raw.setdefault('density', None)
        raw.setdefault('analysis', None)
        raw['result'] = 'FAILED: ' + str(e)
    path = unique_path(out / 'profile', args.case, '.json')
    fc.dump(path, raw)
    a = raw.get('analysis') or {}
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path, raw['result'], 'trace_events=%d' % len(trace),
          'frames=%d' % len(raw['frames']),
          'physics_js=%.2f draw_js=%.2f ms/frame gc=%s' % (a['spans']['physics_ms']['mean'], a['spans']['draw_ms']['mean'],
                                                             json.dumps(a['gc']['timeline_totals'])) if a else '',
          'memory=%s' % json.dumps(raw['memory_api']), flush=True)
    return exit_code


def check_profile_raw(raw, cpu, heap):
    if raw['errors'] or raw['error']:
        raise fc.EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw['error']]))
    if raw['dimensions']['platform'] not in ('disabled', 'absent'):
        raise fc.EvidenceError('SDK isolation failed')
    if raw['dimensions']['version'] != raw['settings']['mode']:
        raise fc.EvidenceError('mode not started')
    if cpu is None or heap is None:
        raise fc.EvidenceError('profilers never started (warmup not reached)')
    if not raw['trace_complete']:
        raise fc.EvidenceError('trace did not complete')
    if len(raw['samples']) != len(raw['frames']) or len(raw['profile']['spans']) != len(raw['frames']):
        raise fc.EvidenceError('sample/span count differs from the active frame count')


# ---------------------------------------------------------- profile math --

def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    ordered = sorted(values)
    return {'mean': statistics.fmean(values), 'p50': fc.percentile(ordered, 50), 'p95': fc.percentile(ordered, 95),
            'max': ordered[-1], 'min': ordered[0], 'n': len(values), 'sum': sum(values)}


def effects_class_ranges(root):
    """class Name { ... } line ranges (1-based, inclusive start of the next class exclusive) of render/effects.js."""
    text = (Path(root) / 'render/effects.js').read_text()
    starts = [(i + 1, m.group(1)) for i, line in enumerate(text.splitlines()) for m in [re.match(r'^class (\w+)', line)] if m]
    ranges = []
    for k, (line, name) in enumerate(starts):
        end = starts[k + 1][0] - 1 if k + 1 < len(starts) else len(text.splitlines())
        ranges.append((line, end, name))
    return ranges


def class_at(ranges, line_1based):
    for start, end, name in ranges:
        if start <= line_1based <= end:
            return name
    return None


def bucket_for(url, function_name, line_number, ranges):
    """Subsystem bucket of a call frame (CDP lineNumber is 0-based)."""
    name = function_name or ''
    if name in ('(garbage collector)',):
        return 'gc'
    if name in ('(idle)', '(program)', '(root)'):
        return name.strip('()')
    path = url.split('/', 3)[-1] if url.startswith('http') else url
    if not path or url == '':
        return 'native'
    if any(path.endswith(u) for u in SIMULATION_URLS):
        return 'simulation'
    if path.endswith('render/effects.js'):
        if name in AMBIENT_MOTE_FUNCTIONS:
            return 'ambient-glow'
        cls = class_at(ranges, (line_number or 0) + 1)
        return EFFECTS_CLASS_BUCKETS.get(cls, 'drawing-other')
    if path.endswith('sprites/scoretext.js'):
        return 'hud'
    if path.endswith('render/draw.js') or path.endswith('render/glowsprites.js') or path.endswith('render/culling.js'):
        return 'drawing-other'
    if path.endswith('menu.js'):
        return 'hud' if ('Button' in name or 'draw' in name.lower()) else 'menu-other'
    if '/sprites/' in path or path.endswith('.js') and path.startswith('sprites/'):
        return 'drawing-other' if any(m in name for m in DRAW_NAME_MARKERS) else 'simulation'
    if path.endswith('index.html'):
        if name in ('gameLoop', 'runFixedPhysics', 'computePhysicsSteps'):
            return 'loop'
        return 'drawing-other' if any(m in name for m in DRAW_NAME_MARKERS) else 'index-other'
    if path.endswith('gameoptions.js'):
        return 'loop' if 'Physics' in name else 'index-other'
    return 'other'


def aggregate_cpu_profile(cpu, ranges):
    """Self time per function from a CDP Profiler profile (samples + timeDeltas), bucketed by subsystem."""
    nodes = {n['id']: n for n in cpu['nodes']}
    self_us = {}
    for node_id, delta in zip(cpu['samples'], cpu['timeDeltas']):
        self_us[node_id] = self_us.get(node_id, 0) + max(0, delta)
    total = sum(self_us.values())
    per_function, per_bucket = {}, {}
    for node_id, us in self_us.items():
        f = nodes[node_id]['callFrame']
        key = f"{f.get('functionName') or '(anonymous)'} @ {f.get('url', '').split('/')[-1]}:{f.get('lineNumber', -1) + 1}"
        b = bucket_for(f.get('url', ''), f.get('functionName', ''), f.get('lineNumber', 0), ranges)
        per_function[key] = per_function.get(key, 0) + us
        per_bucket[b] = per_bucket.get(b, 0) + us
    top = sorted(per_function.items(), key=lambda kv: -kv[1])[:25]
    return {'total_sampled_ms': total / 1000, 'samples': len(cpu['samples']), 'nodes': len(cpu['nodes']),
            'bucket_ms': {k: v / 1000 for k, v in sorted(per_bucket.items(), key=lambda kv: -kv[1])},
            'bucket_fraction': {k: (v / total if total else None) for k, v in per_bucket.items()},
            'top_functions_ms': [{'function': k, 'ms': v / 1000, 'fraction': v / total if total else None} for k, v in top]}


def aggregate_heap_profile(heap, ranges):
    """Self bytes per function from a CDP sampling heap profile tree, bucketed by subsystem."""
    per_function, per_bucket = {}, {}
    total = 0
    stack = [heap['head']]
    while stack:
        node = stack.pop()
        f = node['callFrame']
        size = node.get('selfSize', 0)
        if size:
            key = f"{f.get('functionName') or '(anonymous)'} @ {f.get('url', '').split('/')[-1]}:{f.get('lineNumber', -1) + 1}"
            b = bucket_for(f.get('url', ''), f.get('functionName', ''), f.get('lineNumber', 0), ranges)
            per_function[key] = per_function.get(key, 0) + size
            per_bucket[b] = per_bucket.get(b, 0) + size
            total += size
        stack.extend(node.get('children', []))
    top = sorted(per_function.items(), key=lambda kv: -kv[1])[:25]
    return {'total_sampled_bytes': total, 'samples': len(heap.get('samples', [])),
            'bucket_bytes': {k: v for k, v in sorted(per_bucket.items(), key=lambda kv: -kv[1])},
            'bucket_fraction': {k: (v / total if total else None) for k, v in per_bucket.items()},
            'top_functions_bytes': [{'function': k, 'bytes': v, 'fraction': v / total if total else None} for k, v in top],
            'note': 'sampled allocation bytes between fcWindowStart and fcWindowEnd, objects collected by minor/major GC included; '
                    'a sampling estimate (interval %d B), not an exact byte count' % HEAP_SAMPLING_INTERVAL}


def gc_from_trace(events):
    """GC events of the traced renderer inside the user-timing window marks."""
    window = {'start': None, 'end': None, 'pid': None, 'tid': None}
    for e in events:
        if e.get('cat') == 'blink.user_timing' and e.get('ph') in ('R', 'I', 'i', 'n'):
            if e.get('name') == 'fcWindowStart':
                window.update(start=e['ts'], pid=e.get('pid'), tid=e.get('tid'))
            elif e.get('name') == 'fcWindowEnd':
                window['end'] = e['ts']
    if window['start'] is None or window['end'] is None:
        return {'window_found': False, 'window': window, 'timeline_totals': {}, 'v8_totals': {}}
    by_name, pauses = {}, []
    for e in events:
        if e.get('ph') != 'X' or e.get('pid') != window['pid'] or e.get('tid') != window['tid']:
            continue
        name = e.get('name', '')
        cat = e.get('cat', '')
        if not (name in GC_TIMELINE_NAMES or name.startswith('V8.GC') or 'v8.gc' in cat):
            continue
        ts, dur = e['ts'], e.get('dur', 0)
        if ts < window['start'] or ts + dur > window['end']:
            continue
        rec = by_name.setdefault(name, {'count': 0, 'total_ms': 0.0, 'max_ms': 0.0, 'category': cat})
        rec['count'] += 1
        rec['total_ms'] += dur / 1000
        rec['max_ms'] = max(rec['max_ms'], dur / 1000)
        if name in GC_TIMELINE_NAMES:
            pauses.append(dur / 1000)
    timeline = {n: by_name[n] for n in GC_TIMELINE_NAMES if n in by_name}
    v8 = {n: r for n, r in by_name.items() if n not in GC_TIMELINE_NAMES}
    wall = (window['end'] - window['start']) / 1000
    total = sum(r['total_ms'] for r in timeline.values())
    return {'window_found': True, 'window': window, 'window_wall_ms': wall,
            'timeline_totals': {n: {'count': r['count'], 'total_ms': r['total_ms'], 'max_ms': r['max_ms']} for n, r in timeline.items()},
            'timeline_gc_ms': total, 'timeline_gc_count': sum(r['count'] for r in timeline.values()),
            'timeline_gc_fraction_of_window': total / wall if wall else None,
            'pause_ms': stats(pauses), 'v8_totals': v8,
            'note': 'devtools.timeline MinorGC/MajorGC are the primary totals (main-thread pauses); V8.GC* events from the v8 / '
                    'disabled-by-default-v8.gc categories nest inside them and are listed as detail, not added'}


def memory_series(raw):
    samples = raw['memory_samples']
    avail = raw['memory_api']['performance_memory'] == 'available'
    used = [s['usedJSHeapSize'] for s in samples if 'usedJSHeapSize' in s]
    metrics = raw['metrics_samples']
    heap_used = [m['metrics'].get('JSHeapUsedSize') for m in metrics]
    labels = [s['label'] for s in samples]
    first_window = next((i for i, s in enumerate(samples) if s['label'] == 'window-start'), None)
    out = {'performance_memory': raw['memory_api']['performance_memory'],
           'measureUserAgentSpecificMemory': raw['memory_api']['measureUserAgentSpecificMemory'],
           'measureUserAgentSpecificMemory_call': raw['memory_api'].get('measureUserAgentSpecificMemory_call'),
           'samples': len(samples), 'labels': labels,
           'performance_getMetrics_keys': sorted(metrics[0]['metrics']) if metrics else [],
           'usedJSHeapSize_series': used if avail else 'unavailable',
           'JSHeapUsedSize_series': heap_used, 'JSHeapTotalSize_series': [m['metrics'].get('JSHeapTotalSize') for m in metrics],
           'Nodes_series': [m['metrics'].get('Nodes') for m in metrics],
           'JSEventListeners_series': [m['metrics'].get('JSEventListeners') for m in metrics],
           'activeMs_series': [s['activeMs'] for s in samples]}
    if first_window is not None and len(heap_used) > first_window + 1:
        win = heap_used[first_window:]
        out['window'] = {'JSHeapUsedSize_start': win[0], 'JSHeapUsedSize_end': win[-1], 'JSHeapUsedSize_min': min(win),
                         'JSHeapUsedSize_max': max(win), 'JSHeapUsedSize_range': max(win) - min(win),
                         'drops': sum(1 for a, b in zip(win, win[1:]) if b < a),
                         'note': 'drops between periodic samples = heap shrank (a GC ran); the sampling heap profile and the trace '
                                 'carry the allocation and GC detail'}
    return out


def analyze_profile(raw, trace, cpu, heap, root):
    idx = window_frame_indices(raw)
    spans = [raw['profile']['spans'][i] for i in idx]
    ranges = effects_class_ranges(root)
    keys = ('physics_ms', 'draw_ms', 'steps', 'particleUpdate_ms', 'trail_ms', 'hud_ms', 'particlesDrawn', 'particleLayers',
            'particlesEmitted', 'particleObjectsAllocated', 'particlesAfterUpdate', 'particlePool', 'ribbons', 'ribbonPoints',
            'hudDraws', 'hudFillText', 'fillText', 'strokeText', 'measureText', 'trackPoints')
    per = {k: stats([s.get(k) for s in spans]) for k in keys}
    frames = len(spans)
    w = raw['summary']['combined']
    return {'window_frames': frames, 'window_active_ms': w['active_ms'], 'frame_interval_ms_mean_profiled': 1000 / w['average_fps'],
            'profiled_pass_note': 'frame intervals of this instrumented pass are reported for context only; timing evidence comes '
                                  'from the uninstrumented captures',
            'spans': per,
            'per_frame_js': {'physics_ms': per['physics_ms']['mean'], 'draw_ms': per['draw_ms']['mean'],
                             'particle_update_ms': per['particleUpdate_ms']['mean'], 'trail_ms': per['trail_ms']['mean'],
                             'hud_ms': per['hud_ms']['mean'], 'steps_per_frame': per['steps']['mean'],
                             'note': 'JS submission spans; draw_ms excludes the deferred canvas raster (TASK-276/277), physics_ms '
                                     'is complete (pure JS)'},
            'activity': {'particles_drawn_per_frame': per['particlesDrawn']['mean'], 'particles_emitted_per_frame': per['particlesEmitted']['mean'],
                         'particle_objects_allocated_in_window': per['particleObjectsAllocated']['sum'],
                         'particles_live_mean': per['particlesAfterUpdate']['mean'], 'particle_pool_mean': per['particlePool']['mean'],
                         'ribbon_points_per_frame': per['ribbonPoints']['mean'], 'ribbons_per_frame': per['ribbons']['mean'],
                         'track_points_mean': per['trackPoints']['mean'],
                         'hud_draws_per_frame': per['hudDraws']['mean'], 'hud_fillText_per_frame': per['hudFillText']['mean'],
                         'fillText_per_frame': per['fillText']['mean'], 'strokeText_per_frame': per['strokeText']['mean'],
                         'measureText_per_frame': per['measureText']['mean']},
            'object_counts': raw['density']['counts'],
            'cpu_profile': aggregate_cpu_profile(cpu, ranges), 'heap_profile': aggregate_heap_profile(heap, ranges),
            'gc': gc_from_trace(trace), 'memory': memory_series(raw),
            'profiling_span': raw['profiling']}


# ------------------------------------------------------------------ run --

def capture_argv(root, out, mode, arm, case, args):
    return [sys.executable, 'tools/y8_subsystems.py', 'capture', '--root', root, '--output', str(out), '--mode', mode,
            '--arm', arm, '--case', case, '--windows', '1', '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms)]


def profile_argv(root, out, mode, case, args):
    return [sys.executable, 'tools/y8_subsystems.py', 'profile', '--root', root, '--output', str(out), '--mode', mode,
            '--case', case, '--windows', '1', '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms)]


def load_profiles(out):
    return {f'profile/{p.name}': fc.load(p) for p in sorted((Path(out) / 'profile').glob('*.json'))}


def complete_profile(out, case):
    hits = [r for r in load_profiles(out).values() if r['case'] == case and r.get('result') == 'COMPLETE']
    if len(hits) > 1:
        raise fc.EvidenceError(f'duplicate complete profile {case}')
    return hits[0] if hits else None


def run(args):
    out = Path(args.output).resolve()
    root = ch.verified_root(out)
    failures = 0
    if not args.skip_timing:
        for mode in args.modes:
            for rep in REPS:
                for index, arm in enumerate(sequence(rep)):
                    case = case_name(mode, arm, rep, index)
                    if args.resume and ab.complete_case(ab.load_raws(out), case):
                        print('INFO resume: complete raw exists for', case, flush=True)
                        continue
                    failures += ab.receipt(out, f'timing/{mode}/{rep}/{index}/{arm}', capture_argv(root, out, mode, arm, case, args)) != 0
    if not args.skip_profile:
        for mode in args.modes:
            case = f'profile-{mode}'
            if args.resume and complete_profile(out, case):
                print('INFO resume: complete profile exists for', case, flush=True)
                continue
            failures += ab.receipt(out, f'profile/{mode}', profile_argv(root, out, mode, case, args)) != 0
    print(f'RUN DONE modes={args.modes} failed={failures}', flush=True)
    return 1 if failures else 0


# --------------------------------------------------------------- report --

def mean_ms(raw):
    return 1000 / raw['summary']['combined']['average_fps']


def tier(deltas, noise):
    """Both repetitions beyond the control spread with one sign -> REPEATED; one -> CONSISTENT; else WITHIN_NOISE."""
    beyond = [abs(x) > noise for x in deltas]
    if all(beyond) and len({x > 0 for x in deltas}) == 1:
        return 'REPEATED'
    if any(beyond):
        return 'CONSISTENT'
    return 'WITHIN_NOISE'


def timing_record(raw, path):
    c = raw['summary']['combined']
    d = raw['density']
    s = raw['settings']
    ps = raw['probe_summary']
    return {'path': path, 'case': raw['case'], 'arm': s['arm'], 'mean_ms': mean_ms(raw), 'p50_ms': c['frame_ms']['p50'],
            'p95_ms': c['frame_ms']['p95'], 'average_fps': c['average_fps'], 'frames': c['frames'], 'active_ms': c['active_ms'],
            'deaths': raw['summary']['deaths'], 'backing': raw['dimensions']['canvas'],
            'identity': {'source': f"seeded input replay '{s['replay_style']}' seed {s['seed']} (sha256 {s['replay_sha256'][:12]})",
                         'state': s['arm_state'], 'timing_represents': ps['timing_represents'],
                         'equivalent_to_normal_gameplay': s['arm'] not in DIAGNOSTIC_ARMS,
                         'object_counts': {k: (v['mean'] if v else None) for k, v in d['counts'].items()},
                         'camera_travel_px': d['camera']['travel_px'], 'deaths_in_window': d['deaths_in_window'],
                         'freeze_state': ps['freeze_state']},
            'probe': {k: ps[k] for k in ('physics_calls', 'draw_calls', 'window_steps_total', 'window_steps_per_frame_mean',
                                         'window_steps_histogram', 'frozen', 'frozen_frames', 'physics_calls_while_frozen',
                                         'inputs_blocked', 'draw_replaced', 'executes')},
            'skipped': raw.get('skipped', {}), 'ablated': raw['ablated'], 'frames_sha256': raw['frames_sha256']}


def build_subsystems(out):
    raws = ab.load_raws(out)
    complete = {p: r for p, r in raws.items() if r.get('result') == 'COMPLETE'}
    identity = fc.load(out / 'identity.json')
    ceiling = identity['environment_ceiling']
    results = {}
    for mode in MODES:
        cell, missing = {}, []
        for rep in REPS:
            for index, arm in enumerate(sequence(rep)):
                case = case_name(mode, arm, rep, index)
                hit = [(p, r) for p, r in complete.items() if r['case'] == case]
                if len(hit) != 1:
                    missing.append(case)
                    continue
                cell[(arm, rep, index)] = timing_record(hit[0][1], hit[0][0])
        if missing:
            results[mode] = {'result': 'INCOMPLETE', 'missing': missing}
            continue
        controls = {rep: [cell[(CONTROL, rep, i)]['mean_ms'] for i in (0, len(sequence(rep)) - 1)] for rep in REPS}
        all_controls = [x for v in controls.values() for x in v]
        noise = max(abs(a - b) for a in all_controls for b in all_controls)
        arms = {}
        for arm in ARM_ORDER:
            recs = {rep: next(v for (a, r, i), v in cell.items() if a == arm and r == rep) for rep in REPS}
            saving = [statistics.mean(controls[rep]) - recs[rep]['mean_ms'] for rep in REPS]
            arms[arm] = {'mean_ms': [recs[rep]['mean_ms'] for rep in REPS], 'p50_ms': [recs[rep]['p50_ms'] for rep in REPS],
                         'saving_ms': saving, 'median_saving_ms': statistics.median(saving), 'tier': tier(saving, noise),
                         'fraction_of_control': statistics.median(saving) / statistics.mean(all_controls),
                         'identity': {rep: recs[rep]['identity'] for rep in REPS}, 'probe': {rep: recs[rep]['probe'] for rep in REPS},
                         'equivalent_to_normal_gameplay': arm not in DIAGNOSTIC_ARMS}
        sim = arms['simulation-only']
        sim['ceiling_p50_ms'] = ceiling['frame_ms']['p50']
        sim['excess_over_ceiling_ms'] = [m - ceiling['frame_ms']['p50'] for m in sim['mean_ms']]
        sim['at_environment_ceiling'] = all(m <= ceiling['frame_ms']['p50'] * 1.25 for m in sim['mean_ms'])
        sim['reading'] = ('physics + one clear fits inside the requestAnimationFrame cadence of this environment (%.1f ms); the '
                          'interval is an upper bound on the loop cost without drawing, not a measurement of physics alone' % ceiling['frame_ms']['p50']
                          if sim['at_environment_ceiling'] else 'physics + clear exceeds the rAF cadence: the loop without drawing costs more than one frame slot')
        sim['steps_per_frame'] = {rep: sim['probe'][rep]['window_steps_per_frame_mean'] for rep in REPS}
        sim['control_steps_per_frame'] = {rep: statistics.mean(cell[(CONTROL, rep, i)]['probe']['window_steps_per_frame_mean']
                                                              for i in (0, len(sequence(rep)) - 1)) for rep in REPS}
        sim['physics_steps_per_active_second'] = {rep: 1000 * sim['probe'][rep]['window_steps_total'] / next(
            v for (a, r, i), v in cell.items() if a == 'simulation-only' and r == rep)['active_ms'] for rep in REPS}
        sim['control_physics_steps_per_active_second'] = {rep: statistics.mean(
            1000 * cell[(CONTROL, rep, i)]['probe']['window_steps_total'] / cell[(CONTROL, rep, i)]['active_ms']
            for i in (0, len(sequence(rep)) - 1)) for rep in REPS}
        sim['game_time_note'] = ('simulation-only runs at the rAF cadence, so physics executes ~1 step per frame (~60 steps per active '
                                 'second) while the full loop at ~100 ms frames is capped at maxPhysicsStepsPerFrame = 2 (~20 steps per '
                                 'active second): the physics-only arm covers about three times more game time per wall second, '
                                 'which is why its camera travel and deaths differ from the full loop (identity recorded per capture)')
        drw = arms['drawing-only']
        drw['full_minus_drawing_only_ms'] = drw['saving_ms']
        drw['not_equivalent_statement'] = ('DRAWING-ONLY RENDERS A FROZEN REPLAYED STATE: NOT EQUIVALENT TO NORMAL GAMEPLAY. The frozen '
                                           'state differs from the live control in motion, particle emission, deaths and camera; '
                                           'full-loop minus drawing-only is therefore an indication, not the simulation cost')
        results[mode] = {'result': 'PAIRED', 'mode': mode, 'mode_name': ch.MODE_NAMES[mode],
                         'control': {'mean_ms_by_rep': controls, 'mean_ms': statistics.mean(all_controls), 'noise_max_ms': noise,
                                     'identity': {f'{rep}/i{i}': cell[(CONTROL, rep, i)]['identity'] for rep in REPS for i in (0, len(sequence(rep)) - 1)},
                                     'probe': {f'{rep}/i{i}': cell[(CONTROL, rep, i)]['probe'] for rep in REPS for i in (0, len(sequence(rep)) - 1)}},
                         'arms': arms, 'backing': sorted({tuple(v['backing']) for v in cell.values()}),
                         'captures': {f'{a}/{r}/i{i}': v for (a, r, i), v in cell.items()}}
    return {'task': TASK, 'generated_utc': utc(),
            'statement': 'Uninstrumented timing: requestAnimationFrame intervals of active frames plus the read-only sampler and a '
                         'count-only loop probe. Frame intervals include the main-thread deferred canvas raster of this '
                         'software-rendered Chromium; they are not physical-device figures and nothing here claims 60 FPS. '
                         'simulation-only and drawing-only are diagnostic arms that are NOT equivalent to normal gameplay.',
            'arms': {k: {'feature': v['feature'], 'ablate': v['ablate'], 'state': v['state'], 'label': v['label'],
                         'equivalent_to_normal_gameplay': k not in DIAGNOSTIC_ARMS} for k, v in ARMS.items()},
            'protocol': {'sequence_r1': sequence('r1'), 'sequence_r2': sequence('r2'),
                         'noise': 'max pairwise spread of the four full-loop controls (first/last of each repetition)',
                         'saving': 'mean of the repetition\'s two bracketing controls minus the arm',
                         'tiers': 'REPEATED: both repetitions beyond noise with one sign; CONSISTENT: one; WITHIN_NOISE: none',
                         'viewport': VIEWPORT, 'dpr': DPR, 'seeds': {m: MODE_SETUP[m]['seed'] for m in MODES},
                         'replay_styles': {m: MODE_SETUP[m]['replay_style'] for m in MODES}},
            'environment_ceiling': ceiling, 'results': results, 'raw_count': len(raws), 'complete_count': len(complete),
            'failed_attempts': sorted(p for p, r in raws.items() if r.get('result') != 'COMPLETE')}


def build_allocations(out):
    profiles = load_profiles(out)
    complete = {p: r for p, r in profiles.items() if r.get('result') == 'COMPLETE'}
    sessions = {}
    for mode in MODES:
        hit = [(p, r) for p, r in complete.items() if r['case'] == f'profile-{mode}']
        if len(hit) != 1:
            sessions[mode] = {'result': 'MISSING', 'case': f'profile-{mode}'}
            continue
        p, r = hit[0]
        a = r['analysis']
        sessions[mode] = {'result': 'COMPLETE', 'path': p, 'trace_file': r['trace_file'], 'trace_sha256': r['trace_sha256'],
                          'trace_events': r['trace_events'], 'cpuprofile_file': r['cpuprofile_file'], 'heapprofile_file': r['heapprofile_file'],
                          'memory_api': r['memory_api'], 'window_frames': a['window_frames'], 'window_active_ms': a['window_active_ms'],
                          'per_frame_js': a['per_frame_js'], 'activity': a['activity'], 'object_counts': a['object_counts'],
                          'cpu_profile': a['cpu_profile'], 'heap_profile': a['heap_profile'], 'gc': a['gc'], 'memory': a['memory'],
                          'profiling_span': a['profiling_span'], 'spans': a['spans'],
                          'frame_interval_ms_mean_profiled': a['frame_interval_ms_mean_profiled']}
    return {'task': TASK, 'generated_utc': utc(),
            'statement': 'INSTRUMENTED DIAGNOSTIC PASS, separate from the timing captures: per-frame JS spans, activity counters, '
                         'CDP sampling heap profile, CDP CPU profile, GC events from the trace and memory counters. Unsupported '
                         'browser memory counters are recorded as "unavailable", never as zero. Nothing here is frame-time evidence.',
            'trace_categories': TRACE_CATEGORIES, 'heap_sampling_interval': HEAP_SAMPLING_INTERVAL,
            'cpu_sampling_interval_us': CPU_SAMPLING_INTERVAL_US, 'sessions': sessions,
            'profile_files': sorted(profiles), 'failed_attempts': sorted(p for p, r in profiles.items() if r.get('result') != 'COMPLETE')}


def decide(subsystems, allocations):
    paired = {m: v for m, v in subsystems['results'].items() if v.get('result') == 'PAIRED'}
    sessions = {m: v for m, v in allocations['sessions'].items() if v.get('result') == 'COMPLETE'}
    per_mode = {}
    candidates = []
    for mode in MODES:
        t, s = paired.get(mode), sessions.get(mode)
        entry = {'timing': None, 'profile': None}
        if t:
            entry['timing'] = {'control_mean_ms': t['control']['mean_ms'], 'noise_max_ms': t['control']['noise_max_ms'],
                               'simulation_only_mean_ms': t['arms']['simulation-only']['mean_ms'],
                               'simulation_only_at_ceiling': t['arms']['simulation-only']['at_environment_ceiling'],
                               'full_minus_drawing_only_ms': t['arms']['drawing-only']['saving_ms'],
                               'full_minus_drawing_only_tier': t['arms']['drawing-only']['tier'],
                               'drawing_only_not_equivalent': True,
                               'feature_savings': {a: {'saving_ms': t['arms'][a]['saving_ms'], 'tier': t['arms'][a]['tier'],
                                                       'fraction_of_control': t['arms'][a]['fraction_of_control']} for a in FEATURE_ARMS}}
        if s:
            gc = s['gc']
            frames = s['window_frames'] or 1
            gc_ms_per_frame = (gc.get('timeline_gc_ms') or 0) / frames if gc.get('window_found') else None
            entry['profile'] = {'physics_js_ms_per_frame': s['per_frame_js']['physics_ms'], 'steps_per_frame': s['per_frame_js']['steps_per_frame'],
                                'draw_js_ms_per_frame': s['per_frame_js']['draw_ms'],
                                'gc_ms_per_frame': gc_ms_per_frame, 'gc_count_in_window': gc.get('timeline_gc_count'),
                                'gc_fraction_of_window': gc.get('timeline_gc_fraction_of_window'),
                                'cpu_profile_fraction': {k: s['cpu_profile']['bucket_fraction'].get(k) for k in
                                                         ('simulation', 'gc', 'particles', 'player-trail', 'hud', 'drawing-other',
                                                          'background', 'lighting', 'glow', 'ambient-glow', 'native', 'program', 'idle')},
                                'heap_profile_fraction': {k: s['heap_profile']['bucket_fraction'].get(k) for k in
                                                          ('simulation', 'particles', 'player-trail', 'hud', 'drawing-other', 'background',
                                                           'lighting', 'glow', 'ambient-glow', 'native')},
                                'particle_objects_allocated_in_window': s['activity']['particle_objects_allocated_in_window'],
                                'memory_api': s['memory_api'],
                                'allocation_hotspots': s['heap_profile']['top_functions_bytes'][:8],
                                'cpu_hotspots': [x for x in s['cpu_profile']['top_functions_ms'] if x['function'] != '(program) @ :0'][:8]}
        if t and s:
            control = t['control']['mean_ms']
            sim_gc = s['per_frame_js']['physics_ms'] + (gc_ms_per_frame or 0)
            entry['simulation_plus_gc_ms_per_frame'] = sim_gc
            entry['simulation_plus_gc_fraction_of_control'] = sim_gc / control
            entry['material_threshold_ms'] = max(MATERIAL_FRACTION * control, t['control']['noise_max_ms'])
            entry['material'] = sim_gc >= entry['material_threshold_ms']
            entry['timing_corroboration'] = ('full-loop minus drawing-only = %s ms (tier %s) on a frozen, non-equivalent state' % (
                [round(x, 1) for x in t['arms']['drawing-only']['saving_ms']], t['arms']['drawing-only']['tier']))
        per_mode[mode] = entry
    for mode, e in per_mode.items():
        if not (e['timing'] and e['profile']):
            continue
        t = e['timing']
        candidates.append({'subsystem': 'simulation (physics JS)', 'mode': mode, 'measured_ms_per_frame': e['profile']['physics_js_ms_per_frame'],
                           'source': 'profile pass JS span (complete: pure JS)', 'fraction_of_control': e['profile']['physics_js_ms_per_frame'] / t['control_mean_ms'],
                           'candidate': e['profile']['physics_js_ms_per_frame'] >= e['material_threshold_ms']})
        candidates.append({'subsystem': 'GC pauses', 'mode': mode, 'measured_ms_per_frame': e['profile']['gc_ms_per_frame'],
                           'source': 'trace MinorGC/MajorGC inside the window', 'fraction_of_control': (e['profile']['gc_ms_per_frame'] or 0) / t['control_mean_ms'],
                           'candidate': (e['profile']['gc_ms_per_frame'] or 0) >= e['material_threshold_ms']})
        gc_candidate = (e['profile']['gc_ms_per_frame'] or 0) >= e['material_threshold_ms']
        candidates.append({'subsystem': 'allocation pressure (top sampled allocators)', 'mode': mode,
                           'measured_ms_per_frame': e['profile']['gc_ms_per_frame'], 'hotspots': e['profile']['allocation_hotspots'][:5],
                           'source': 'CDP sampling heap profile (bytes, collected objects included) + trace GC pauses',
                           'fraction_of_control': (e['profile']['gc_ms_per_frame'] or 0) / t['control_mean_ms'], 'candidate': gc_candidate,
                           'reading': 'allocation reduction is a candidate only if the GC pauses it causes are material to the frame'})
        for a in FEATURE_ARMS:
            fsv = t['feature_savings'][a]
            candidates.append({'subsystem': a.replace('-off', ''), 'mode': mode, 'measured_ms_per_frame': statistics.median(fsv['saving_ms']),
                               'saving_ms': fsv['saving_ms'], 'tier': fsv['tier'], 'source': 'timing pass hook saving (frame intervals)',
                               'fraction_of_control': fsv['fraction_of_control'], 'candidate': fsv['tier'] == 'REPEATED'})
    complete = all(per_mode[m].get('material') is not None for m in MODES)
    if not complete:
        verdict = 'INCOMPLETE'
    elif all(per_mode[m]['material'] for m in MODES):
        verdict = 'CPU_SIMULATION_GC_MATERIAL'
    elif not any(per_mode[m]['material'] for m in MODES):
        verdict = 'CPU_SIMULATION_GC_NOT_MATERIAL'
    else:
        verdict = 'CPU_SIMULATION_GC_MATERIAL_IN_ONE_MODE'
    return {'task': TASK, 'generated_utc': utc(), 'verdict': verdict,
            'verdict_meaning': {
                'CPU_SIMULATION_GC_NOT_MATERIAL': 'physics JS + GC pauses per frame stay below max(10 %% of the control frame interval, control '
                                                  'noise) in both modes: rendering dominates; simulation/GC is not a separate material contributor',
                'CPU_SIMULATION_GC_MATERIAL': 'physics JS + GC pauses per frame reach the threshold in both modes',
                'CPU_SIMULATION_GC_MATERIAL_IN_ONE_MODE': 'threshold reached in one mode only',
                'INCOMPLETE': 'a timing cell or a profile session is missing'}[verdict],
            'rule': 'material if physics_js_ms_per_frame (profile pass) + MinorGC/MajorGC ms per frame (trace) >= max(%.0f %% of the '
                    'full-loop control mean, control noise). The timing pass corroborates: simulation-only at the rAF ceiling means physics '
                    'fits in a frame slot; full-loop minus drawing-only is reported but rests on a frozen non-equivalent state.' % (MATERIAL_FRACTION * 100),
            'per_mode': per_mode, 'candidates': candidates,
            'candidates_for_separate_optimization': [c for c in candidates if c['candidate']],
            'separation': {'timing': 'uninstrumented rAF intervals (subsystems.json, raw/*.json)',
                           'profiling': 'instrumented sessions (allocations.json, profile/*.json, traces/*.gz); never mixed',
                           'js_submission_not_raster': 'draw_ms spans are JS submission only; the deferred canvas raster is outside them',
                           'gpu_attribution': 'UNSUPPORTED: SwiftShader software raster, no GPU fence'},
            'drawing_only_statement': 'drawing-only renders a frozen replayed state and is NOT EQUIVALENT to normal gameplay',
            'not_claimed': ['60 FPS', 'release readiness', 'physical-device performance'],
            'diagnostic_only': 'simulation-only / drawing-only / feature hooks are page-only diagnostics; the shipped runtime is unchanged'}


def build_manifest(out):
    identity = fc.load(out / 'identity.json')
    commands = []
    cj = out / 'commands.jsonl'
    if cj.exists():
        commands = [json.loads(line) for line in cj.read_text().splitlines() if line.strip()]
    raws = ab.load_raws(out)
    profiles = load_profiles(out)
    trace_files = sorted(f'traces/{p.name}' for p in (out / 'traces').glob('*.gz')) if (out / 'traces').exists() else []
    evidence = sorted(list(raws) + list(profiles) + trace_files + ['identity.json', 'commands.jsonl'])
    evidence = [p for p in evidence if (out / p).exists()]
    module_variants = sorted(p.name for p in (out / MODULE_AT_CAPTURE).glob('*.py'))
    everything = list(raws.values()) + list(profiles.values())
    envs = [r['environment'] for r in everything if r.get('environment')]
    starts = [r['started_utc'] for r in everything] + [c['utc_start'] for c in commands] + [identity['utc_start']]
    ends = [r.get('ended_utc') for r in everything if r.get('ended_utc')] + [c['utc_end'] for c in commands]
    return {'task': TASK, 'generated_utc': utc(), 'utc_start': min(starts), 'utc_end': max(ends),
            'commands': [{k: c[k] for k in ('label', 'argv', 'utc_start', 'utc_end', 'exit_code')} for c in commands],
            'environment': envs[0] if envs else None, 'environment_ceiling': identity['environment_ceiling'],
            'source_revision': identity['identity']['current_commit'], 'source_dirty_runtime': identity['identity']['current_dirty_runtime'],
            'source_revision_at_report': fc.git('rev-parse', 'HEAD'), 'current_tar_sha256': identity['identity']['current_tar_sha256'],
            'candidate_hashes': {'current_files_sha256': identity['identity']['current_files_sha256']},
            'harness_sha256': identity['harness_sha256'], 'ablation_sha256': identity['ablation_sha256'], 'chill_sha256': identity['chill_sha256'],
            'support_sha256': identity['support_sha256'], 'module_sha256_at_report': fc.sha_file(MODULE),
            'module_sha256_at_capture': sorted({r['module_sha256'] for r in everything}), 'module_at_capture': module_variants,
            'fixed': {'viewport_css': VIEWPORT, 'dpr': DPR, 'backing_size_by_case': {r['case']: r['dimensions']['canvas'] for r in everything if r.get('dimensions')},
                      'modes': list(MODES), 'seeds': {m: MODE_SETUP[m]['seed'] for m in MODES},
                      'replay_styles': {m: MODE_SETUP[m]['replay_style'] for m in MODES},
                      'replay_sha256': sorted({r['settings']['replay_sha256'] for r in everything}),
                      'arms': {k: v['state'] for k, v in ARMS.items()}, 'sequence_r1': sequence('r1'), 'sequence_r2': sequence('r2'),
                      'input': 'mouse (dispatched mousedown/mouseup on the active clock; blocked after the freeze in drawing-only)',
                      'state': 'fresh page per capture, seeded Math.random, menu -> startGame(mode); drawing-only freezes physics at the '
                               'warmup end; profile sessions run the full loop under rAF with profilers attached',
                      'cpu_throttle': sorted({r['settings']['cpu_throttle'] for r in everything}),
                      'warmup_ms': sorted({r['settings']['warmup_ms'] for r in everything}),
                      'window_ms': sorted({r['settings']['window_ms'] for r in everything}),
                      'trace_categories': TRACE_CATEGORIES, 'heap_sampling_interval': HEAP_SAMPLING_INTERVAL,
                      'cpu_sampling_interval_us': CPU_SAMPLING_INTERVAL_US},
            'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter',
            'evidence_paths': evidence, 'sha256': {p: fc.sha_file(out / p) for p in evidence},
            'failed_attempts_preserved': [p for p in evidence if (p in raws and raws[p].get('result') != 'COMPLETE') or
                                          (p in profiles and profiles[p].get('result') != 'COMPLETE')],
            'exit_codes': sorted({c['exit_code'] for c in commands}),
            'note': 'A successful evidence audit is separate from the performance verdict (decision.json). Failed attempts are preserved, '
                    'never rewritten. Historical receipts are never fabricated.'}


def report(args):
    out = Path(args.output).resolve()
    subsystems = build_subsystems(out)
    allocations = build_allocations(out)
    decision = decide(subsystems, allocations)
    fc.dump(out / 'subsystems.json', subsystems)
    fc.dump(out / 'allocations.json', allocations)
    fc.dump(out / 'decision.json', decision)
    manifest = build_manifest(out)
    for name in ('subsystems.json', 'allocations.json', 'decision.json'):
        manifest['sha256'][name] = fc.sha_file(out / name)
        manifest['evidence_paths'].append(name)
    fc.dump(out / 'manifest.json', manifest)
    print('REPORT verdict', decision['verdict'])
    for mode, v in subsystems['results'].items():
        if v['result'] != 'PAIRED':
            print('  ', mode, v['result'], v.get('missing'))
            continue
        c = v['control']
        print('  %s control %s mean %.1f noise %.2f' % (mode, {r: [round(x, 1) for x in m] for r, m in c['mean_ms_by_rep'].items()}, c['mean_ms'], c['noise_max_ms']))
        for arm, a in v['arms'].items():
            extra = ''
            if arm == 'simulation-only':
                extra = 'at_ceiling=%s steps/frame=%s' % (a['at_environment_ceiling'], {r: round(x, 2) for r, x in a['steps_per_frame'].items()})
            print('     %-17s mean %s saving %s %s %s' % (arm, [round(x, 1) for x in a['mean_ms']], [round(x, 1) for x in a['saving_ms']], a['tier'], extra))
    for mode, s in allocations['sessions'].items():
        if s.get('result') != 'COMPLETE':
            print('  ', mode, s)
            continue
        print('  profile %s frames=%d physics_js=%.2f draw_js=%.2f particles_js=%.2f trail_js=%.2f hud_js=%.2f ms/frame gc=%s cpu=%s heap_top=%s memory=%s' % (
            mode, s['window_frames'], s['per_frame_js']['physics_ms'], s['per_frame_js']['draw_ms'], s['per_frame_js']['particle_update_ms'],
            s['per_frame_js']['trail_ms'], s['per_frame_js']['hud_ms'], json.dumps(s['gc']['timeline_totals']),
            {k: round(v, 3) for k, v in list(s['cpu_profile']['bucket_fraction'].items())[:8]},
            [(x['function'], x['bytes']) for x in s['heap_profile']['top_functions_bytes'][:3]], s['memory_api']['performance_memory']))
    for m, e in decision['per_mode'].items():
        if e.get('material') is not None:
            print('  decision %s sim+gc %.2f ms/frame = %.1f%% of control, threshold %.2f -> material=%s' % (
                m, e['simulation_plus_gc_ms_per_frame'], 100 * e['simulation_plus_gc_fraction_of_control'], e['material_threshold_ms'], e['material']))
    print('  candidates:', [(c['subsystem'], c['mode']) for c in decision['candidates_for_separate_optimization']])
    return 0 if decision['verdict'] != 'INCOMPLETE' else 1


# ---------------------------------------------------------------- audit --

def audit(args):
    out = Path(args.output).resolve()
    failures, passes = [], []

    def check(cond, msg):
        (passes if cond else failures).append(msg)
        print(('PASS ' if cond else 'FAIL ') + msg, flush=True)

    identity = fc.load(out / 'identity.json')
    root = Path(identity['identity']['trees']['current'])
    check(fc.tree_hashes(root) == identity['identity']['current_files_sha256'], 'served tree unchanged since prepare')
    variants = {fc.sha_file(p) for p in (out / MODULE_AT_CAPTURE).glob('*.py')}
    raws = ab.load_raws(out)
    profiles = load_profiles(out)
    for name, r in list(raws.items()) + list(profiles.items()):
        check(r['module_sha256'] in variants, f'{name}: module variant preserved ({r["module_sha256"][:8]})')
        check(r['tree']['files_sha256'] == identity['identity']['current_files_sha256'], f'{name}: captured tree == identity tree')
    complete = 0
    for name, r in raws.items():
        if r.get('result') != 'COMPLETE':
            check(True, f'{name}: preserved failed attempt ({r.get("result")})')
            continue
        complete += 1
        check(fc.frames_sha256(r['frames']) == r['frames_sha256'], f'{name}: frames seal')
        check(fc.summarize(r) == r['summary'], f'{name}: summary recomputed from frames')
        check(ch.window_density(r) == r['density'], f'{name}: density recomputed from samples')
        check(probe_summary(r) == r['probe_summary'], f'{name}: loop probe summary recomputed')
        check(r['settings']['instrumentation'].startswith('timing arm'), f'{name}: timing-only instrumentation statement')
        check('profile' not in r and 'stage_profile' not in r and 'trace_profile' not in r, f'{name}: no profiler/trace in timing raw')
        check(r['ablated'] == expected_ablated(r['settings']['arm']), f'{name}: hooks == arm definition {r["ablated"]}')
        try:
            check_probe(r)
            ps = r['probe_summary']
            check(True, f'{name}: probe executes {json.dumps(ps["executes"])} -> {ps["timing_represents"]} (steps/frame %.2f)' % (ps['window_steps_per_frame_mean'] or 0))
        except fc.EvidenceError as e:
            check(False, f'{name}: {e}')
        check(r['dimensions']['canvas'] == [VIEWPORT[0] * DPR, VIEWPORT[1] * DPR], f'{name}: backing {r["dimensions"]["canvas"]}')
    for name, r in profiles.items():
        if r.get('result') != 'COMPLETE':
            check(True, f'{name}: preserved failed attempt ({r.get("result")})')
            continue
        check(r['settings']['instrumentation'].startswith('INSTRUMENTED DIAGNOSTIC PASS'), f'{name}: labelled instrumented')
        check(r['settings']['population'] == 'subsystems-profile' and r['pass'] == 'profile', f'{name}: profile pass population')
        for key in ('trace_file', 'cpuprofile_file', 'heapprofile_file'):
            path = out / r[key]
            ok = path.exists() and fc.sha_file(path) == r[key.replace('_file', '_sha256')]
            check(ok, f'{name}: {key} sealed ({r[key]})')
        with gzip.open(out / r['trace_file'], 'rt') as f:
            trace = json.load(f)
        with gzip.open(out / r['cpuprofile_file'], 'rt') as f:
            cpu = json.load(f)
        with gzip.open(out / r['heapprofile_file'], 'rt') as f:
            heap = json.load(f)
        rebuilt = json.loads(json.dumps(analyze_profile(r, trace, cpu, heap, root)))
        check(rebuilt == r['analysis'], f'{name}: analysis re-derived from spans, trace, cpu and heap profiles')
        mem = r['memory_api']
        check(all(v == 'available' or (isinstance(v, str) and v.startswith('unavailable')) or isinstance(v, dict) for v in mem.values()),
              f'{name}: memory APIs marked available/unavailable, never zero: {json.dumps(mem)}')
        check(r['analysis']['gc']['window_found'], f'{name}: GC window marks found in trace (%d events)' % r['trace_events'])
        check(len(r['profile']['spans']) == len(r['frames']), f'{name}: one span record per active frame')
    for fname, builder in (('subsystems.json', lambda: build_subsystems(out)), ('allocations.json', lambda: build_allocations(out))):
        if (out / fname).exists():
            stored = fc.load(out / fname)
            rebuilt = json.loads(json.dumps(builder()))
            rebuilt['generated_utc'] = stored['generated_utc']
            check(rebuilt == stored, f'{fname} re-derived from raw files')
    if (out / 'decision.json').exists():
        stored = fc.load(out / 'decision.json')
        rebuilt = json.loads(json.dumps(decide(fc.load(out / 'subsystems.json'), fc.load(out / 'allocations.json'))))
        rebuilt['generated_utc'] = stored['generated_utc']
        check(rebuilt == stored, 'decision.json re-derived; verdict ' + stored['verdict'])
        check('NOT EQUIVALENT' in stored['drawing_only_statement'], 'decision states drawing-only is not equivalent to gameplay')
    if (out / 'manifest.json').exists():
        m = fc.load(out / 'manifest.json')
        bad = [p for p in m['evidence_paths'] if p != 'manifest.json' and fc.sha_file(out / p) != m['sha256'][p]]
        check(not bad, f'manifest seal: {len(m["sha256"])} files, mismatches {bad}')
        check(m['source_revision'] == identity['identity']['current_commit'], 'manifest source revision == identity')
    marker_hits = [n for n in fc.runtime_files(ROOT) if '__featureCost' in (ROOT / n).read_text(errors='ignore')]
    check(not marker_hits, f'no instrumentation marker in {len(fc.runtime_files(ROOT))} runtime files')
    print(f'AUDIT {"PASS" if not failures else "FAIL"} passes={len(passes)} failures={len(failures)} timing_complete={complete} profiles={len(profiles)}', flush=True)
    return 1 if failures else 0


# ----------------------------------------------------------------- main --

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='action', required=True)

    def common(sp):
        sp.add_argument('--output', default=f'artifacts/{TASK}')
        sp.add_argument('--root', default=str(ROOT))
        sp.add_argument('--cpu-throttle', type=float, default=1)
        sp.add_argument('--mode', choices=MODES, required=True)
        sp.add_argument('--case', required=True)
        sp.add_argument('--warmup-ms', type=int, default=5000)
        sp.add_argument('--window-ms', type=int, default=10000)
        sp.add_argument('--windows', type=int, default=1)
        sp.add_argument('--timeout-ms', type=int, default=180000)

    s = sub.add_parser('prepare'); s.add_argument('--output', default=f'artifacts/{TASK}')
    s = sub.add_parser('capture'); common(s); s.add_argument('--arm', choices=sorted(ARMS), required=True)
    s = sub.add_parser('profile'); common(s)
    s = sub.add_parser('run'); s.add_argument('--output', default=f'artifacts/{TASK}')
    s.add_argument('--modes', nargs='+', default=list(MODES)); s.add_argument('--warmup-ms', type=int, default=5000)
    s.add_argument('--window-ms', type=int, default=10000); s.add_argument('--resume', action='store_true')
    s.add_argument('--skip-profile', action='store_true'); s.add_argument('--skip-timing', action='store_true')
    s = sub.add_parser('report'); s.add_argument('--output', default=f'artifacts/{TASK}')
    s = sub.add_parser('audit'); s.add_argument('--output', default=f'artifacts/{TASK}')
    args = p.parse_args(argv)
    return {'prepare': prepare, 'capture': capture, 'profile': profile, 'run': run, 'report': report, 'audit': audit}[args.action](args)


if __name__ == '__main__':
    sys.exit(main())
