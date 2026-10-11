"""Feature ablation screening on top of tools/y8_feature_cost.py (TASK-272).

Eight Main-mode rendering features are disabled one at a time, drawing only,
inside the diagnostic clone page (marker __featureCost); update/state side
effects (physics, particle update, trail points, score, HUD state) keep running
and the shipped runtime is never modified. Each feature arm follows the TASK-271
screening protocol: control, candidate, candidate, control; fixed seed 4; one
10-second window after a 5-second warmup per capture; desktop 1280x720 DPR 1.

Actions
  prepare  build the verified current tree (git archive HEAD), measure the
           environment ceiling, write --output/identity.json
  capture  one browser session (control when --feature is omitted); writes
           --output/raw/<case>.json with the hook actually installed, the
           in-page active flags of every feature and the raw active frames
  run      control/candidate/candidate/control quads for --features x --modes;
           appends command receipts to --output/commands.jsonl
  prove    deterministic simulation (synthetic clock, no rAF) with every feature
           disabled in turn; writes --output/state-equality.json
  report   ablation.json, ranking.json, decision.json, manifest.json
  audit    recompute every metric and pair from the raw files, verify seals,
           hooks, active labels, paired settings and backing sizes

Nothing here certifies 60 FPS, physical devices or release readiness.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import statistics
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_cost as fc  # noqa: E402

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
TASK = 'TASK-272'
PROFILE = 'desktop'
SEED = 4
# Order of the eight arms; names are the CLI --feature values.
FEATURES = {
    'ambient-glow': {
        'removes': 'ParticleSystem.drawAmbientMotes: ambient motes and their AmbientGlowRenderer bloom chain '
                   '(renderGlow, blur, composite); mote layout/state untouched',
        'install': 'visualEffects.particles.drawAmbientMotes = skip("ambient-glow")',
        'active': 'visualEffects.particles.shouldDrawAmbientMotes() && visualEffects.ambientGlow.shouldDraw()',
        'flags': ['STYLE.features.ambient', 'QUALITY.ambient']},
    'player-glow': {
        'removes': 'drawPlayerGlowLayer: PlayerGlowRenderer.draw (ribbon/spark/ring glow pass, blur, composite)',
        'install': 'window.drawPlayerGlowLayer = skip("player-glow")',
        'active': 'visualEffects.playerGlow.shouldDraw()',
        'flags': ['STYLE.player.outerGlow', 'QUALITY.playerTrail']},
    'obstacle-lighting': {
        'removes': 'drawLightsLayer: LightmapRenderer clear, world lights, silhouette erase, composite',
        'install': 'window.drawLightsLayer = skip("obstacle-lighting")',
        'active': 'visualEffects.lightmap.shouldDraw()',
        'flags': ['STYLE.features.lightmap', 'QUALITY.lightmap']},
    'cave-background': {
        'removes': 'drawBackgroundLayer: BackgroundRenderer.draw (cave gradients, crystal/rock layers, window bars) '
                   'replaced by clearAll plus one black fillRect; the once-per-run gameplay RNG consumption '
                   '(preserveGameplayRandomSequence(1, 40)) is kept so level generation is unchanged',
        'install': 'window.drawBackgroundLayer = skip("cave-background", () => { '
                   'visualEffects.background.preserveGameplayRandomSequence(1, 40); visualEffects.background.clearAll(); '
                   'ctx.fillStyle = "#000"; ctx.fillRect(0, 0, width, height) })',
        'active': 'STYLE.features.background === true',
        'flags': ['STYLE.features.background', 'QUALITY.backgroundMotion']},
    'player-trail': {
        'removes': 'drawPlayerTrailLayer: PlayerTrailRenderer.draw (obstacle tracks and the smooth player ribbon, '
                   'main pass only; the glow-pass copy inside player-glow is untouched); track points keep updating',
        'install': 'window.drawPlayerTrailLayer = skip("player-trail")',
        'active': 'visualEffects.playerTrail.shouldDraw()',
        'flags': ['STYLE.features.playerTrail', 'QUALITY.playerTrail', 'trackEnabled']},
    'particles': {
        'removes': 'ParticleSystem.draw and drawBehindForeground: emitted particle layers (sparks, embers, splashes); '
                   'ParticleSystem.update (emission, ageing, pooling) keeps running',
        'install': 'visualEffects.particles.draw = skip("particles"); '
                   'visualEffects.particles.drawBehindForeground = skip("particles")',
        'active': 'visualEffects.particles.shouldDraw()',
        'flags': ['STYLE.features.particles', 'QUALITY.particles']},
    'world-geometry': {
        'removes': 'drawWorldLayer: grapnel rope and hook, floor/ceiling strips, obstacle elements, extrusions '
                   '(flag), left wall, screen',
        'install': 'window.drawWorldLayer = skip("world-geometry")',
        'active': 'typeof drawWorldLayer === "function"',
        'flags': ['STYLE.features.extrusion']},
    'hud': {
        'removes': 'drawUILayer: UIStylingHooks.draw (score text and HUD menu button); the FPS counter layer is a '
                   'separate stage (disabled by default) and is untouched',
        'install': 'window.drawUILayer = skip("hud")',
        'active': 'visualEffects.ui.shouldDraw()',
        'flags': ['STYLE.features.uiStyling']},
}
# Pipeline stages that are present in draw() but may be switched off by flags:
# recorded per arm and labelled inactive, never credited with savings.
STAGE_FLAGS = {
    'bloom': 'STYLE.features.bloom && QUALITY.bloom',
    'colorGrade': 'visualEffects.colorGrade.shouldDraw()',
    'extrusion': 'STYLE.features.extrusion === true',
    'fpsCounter': 'fpsCounter.enabled === true',
    'screenEffects': 'STYLE.features.screenEffects === true',
}
QUAD = ('control', 'candidate', 'candidate', 'control')
MODULE_AT_CAPTURE = 'module-at-capture/y8_feature_ablation.py'


def js_object(exprs):
    return '{' + ', '.join(f'{json.dumps(k)}: (() => {{ try {{ return !!({v}) }} catch (e) {{ return "ERROR: " + e }} }})()'
                           for k, v in exprs.items()) + '}'


# Evaluated after fc.INSTRUMENT (FC exists, gameLoop wrapped) and before startGame.
FEATURE_INSTRUMENT = '''(cfg) => {
    const FC = window.__featureCost
    FC.featureActive = %s
    FC.stageFlags = %s
    FC.skipped = {}
    const skip = (name, replacement) => function() {
        FC.skipped[name] = (FC.skipped[name] || 0) + 1
        if (replacement) return replacement.apply(this, arguments)
    }
    FC.feature = cfg.feature
    if (cfg.feature) {
        const spec = cfg.features[cfg.feature]
        eval(spec.install)
        FC.ablated.push(spec.removes)
    }
}''' % (js_object({k: v['active'] for k, v in FEATURES.items()}), js_object(STAGE_FLAGS))

# Deterministic simulation: synthetic rAF timestamps, performance.now pinned to
# the same clock, so particle ageing/emission is reproducible between runs.
SIMULATION = '''(cfg) => {
    const FC = window.__featureCost
    cancelAnimationFrame(game)
    const realNow = performance.now.bind(performance)
    let clock = 1000
    performance.now = () => clock
    const particles = visualEffects.particles
    const update = particles.update
    FC.particleUpdates = 0
    particles.update = function() { FC.particleUpdates++; return update.apply(this, arguments) }
    try {
        startGame(cfg.mode)
        cancelAnimationFrame(game)
        for (let i = 0; i < cfg.frames; i++) { clock = 1000 + i * 1000 / 60; gameLoop(clock); cancelAnimationFrame(game) }
    } finally { performance.now = realNow }
    const digest = particles.particles.map(p => [p.x, p.y, p.size, p.life, p.alpha, p.spark].map(v =>
        typeof v === 'number' ? Math.round(v * 1000) / 1000 : v))
    return {steps: FC.physicsSteps, frames: FC.frames.length, dispatched: FC.dispatched.length,
        ablated: FC.ablated, skipped: FC.skipped, deaths: FC.deaths.length, feature: FC.feature,
        featureActive: FC.featureActive, stageFlags: FC.stageFlags,
        ninja: [ninja.x, ninja.y, ninja.speedX, ninja.speedY], screen: [screen.x, screen.y],
        grapnel: [grapnel.throwed, grapnel.isGrappled(), grapnel.pos.length],
        score: scoreText.count[version], elements: floors.map(f => f.elements.length),
        accumulator: physicsTiming.accumulatorMs,
        particleUpdates: FC.particleUpdates, particleCount: particles.particles.length,
        particlePoolCount: particles.pool.length, particleDigestSha: null, particleDigest: digest,
        trackPoints: ninja.track.pos.length, trackLast: ninja.track.pos.length ? [ninja.track.pos[ninja.track.pos.length - 1].x,
            ninja.track.pos[ninja.track.pos.length - 1].y] : null,
        obstacleTrackPoints: floors.reduce((n, f) => n + f.elements.reduce((m, e) => m + (e.track ? e.track.pos.length : 0), 0), 0),
        lightmapHasLights: visualEffects.lightmap.hasLights, drawFrameId}
}'''
EQUALITY_KEYS = ('steps', 'frames', 'dispatched', 'deaths', 'ninja', 'screen', 'grapnel', 'score', 'elements',
                 'accumulator', 'particleUpdates', 'particleCount', 'particlePoolCount', 'particleDigestSha',
                 'trackPoints', 'trackLast', 'obstacleTrackPoints', 'drawFrameId')


def feature_cfg(feature):
    return {'feature': feature, 'features': {k: {'install': v['install'], 'removes': v['removes']} for k, v in FEATURES.items()}}


def utc():
    return fc.utc()


# -------------------------------------------------------------- capture --

def case_name(feature, arm, mode, rep):
    return f'{feature}-{arm}-{mode}-{PROFILE}-s{SEED}-w{rep}'


def capture(args):
    from browser_test_support import start_browser_test
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    if args.feature is not None and args.feature not in FEATURES:
        raise SystemExit(f'unknown --feature {args.feature}; choose one of {list(FEATURES)}')
    profile = fc.PROFILES[args.profile]
    total = args.warmup_ms + args.windows * args.window_ms
    replay = fc.replay_script(args.seed, args.profile, total + 1000)
    settings = {'mode': args.mode, 'profile': args.profile, 'viewport': profile['viewport'],
                'dpr': profile['dpr'], 'is_mobile': profile['is_mobile'], 'has_touch': profile['has_touch'],
                'input': profile['input'], 'cpu_throttle': args.cpu_throttle, 'seed': args.seed,
                'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows,
                'replay_sha256': fc.replay_sha256(replay), 'ablate': [args.feature] if args.feature else [],
                'feature': args.feature, 'diagnostic': False,
                'density': 'pinned to profile DPR; adaptive observe disabled',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                                 'PLATFORM falls back to the local adapter (no ads, instant restart on death)'}
    cfg = {'dpr': profile['dpr'], 'input': profile['input'], 'ablate': [], 'diagnostic': False, 'replay': replay,
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    raw = {'case': args.case, 'task': TASK, 'settings': settings,
           'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
           'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(MODULE),
           'feature_spec': FEATURES.get(args.feature), 'argv': sys.argv, 'started_utc': utc(), 'replay': replay,
           'network': [], 'errors': [], 'console_errors': []}
    network, exit_code = raw['network'], 1
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        raw['environment'] = fc.environment(browser)
        ctx = fc.new_context(browser, args.profile, args.seed, network)
        stack.callback(ctx.close)
        page = ctx.new_page()
        page.on('pageerror', lambda e: raw['errors'].append(str(e)))
        page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
        ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': args.cpu_throttle})
        page.goto(url + 'index.html', wait_until='domcontentloaded')
        page.wait_for_function(fc.BOOTED, timeout=60000)
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate(FEATURE_INSTRUMENT, feature_cfg(args.feature))
        page.evaluate('mode => startGame(mode)', args.mode)
        try:
            page.wait_for_function(f'{fc.MARKER}.done || {fc.MARKER}.error', timeout=args.timeout_ms)
        except Exception as e:  # keep the partial record as a failed attempt
            raw['errors'].append('timeout: ' + str(e).splitlines()[0])
        page.evaluate(f'() => {{ {fc.MARKER}.cfg.replay = "<see raw.replay>" }}')
        raw.update(page.evaluate(fc.MARKER))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['ended_utc'] = utc()
    raw['frames_sha256'] = fc.frames_sha256(raw['frames'])
    try:
        if raw['errors'] or raw['error']:
            raise fc.EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw['error']]))
        if raw['dimensions']['platform'] not in ('disabled', 'absent'):
            raise fc.EvidenceError('SDK isolation failed: ' + str(raw['dimensions']['platform']))
        if raw['dimensions']['version'] != args.mode:
            raise fc.EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
        if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
            raise fc.EvidenceError('backing size changed during the capture')
        expected = [FEATURES[args.feature]['removes']] if args.feature else []
        if raw['ablated'] != expected:
            raise fc.EvidenceError(f'hook mismatch: installed {raw["ablated"]} expected {expected}')
        if args.feature and not raw['skipped'].get(args.feature):
            raise fc.EvidenceError('disabled hook was never reached by draw()')
        raw['summary'] = fc.summarize(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw['summary'], raw['result'] = None, 'FAILED: ' + str(e)
    path = fc.raw_path(args.output, args.case)
    fc.dump(path, raw)
    c = raw['summary']['combined'] if raw['summary'] else None
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'backing=' + str(raw['dimensions']['canvas']),
          'feature=%s active=%s skipped=%s' % (args.feature, raw['featureActive'].get(args.feature) if args.feature else None,
                                               raw['skipped'].get(args.feature) if args.feature else None),
          'fps=%.2f p50=%.2f p95=%.2f p99=%.2f max=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'], c['frame_ms']['p99'],
              c['frame_ms']['max'], c['active_ms'], raw['summary']['deaths']) if c else '', flush=True)
    return exit_code


# -------------------------------------------------------------- prepare --

def prepare(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    started = utc()
    identity = fc.build_trees(out)
    ceiling = fc.environment_ceiling(PROFILE)
    fc.dump(out / 'identity.json', {'task': TASK, 'utc_start': started, 'utc_end': utc(), 'argv': sys.argv,
                                    'identity': identity, 'environment_ceiling': ceiling,
                                    'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(MODULE),
                                    'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py')})
    print('PASS identity written', out / 'identity.json', 'HEAD', identity['current_commit'],
          'dirty_runtime=%r' % identity['current_dirty_runtime'], 'ceiling_fps=%.2f' % ceiling['average_fps'])
    return 0


# ------------------------------------------------------------------ run --

def receipt(out, label, argv):
    t0 = utc()
    r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    entry = {'label': label, 'argv': argv, 'utc_start': t0, 'utc_end': utc(), 'exit_code': r.returncode,
             'stdout': r.stdout[-4000:], 'stderr': r.stderr[-4000:]}
    with open(Path(out) / 'commands.jsonl', 'a') as f:
        f.write(json.dumps(entry, sort_keys=True) + '\n')
    print(r.stdout.strip() or r.stderr.strip()[-500:], flush=True)
    return r.returncode


def run(args):
    out = Path(args.output)
    identity = fc.load(out / 'identity.json')['identity']
    root = identity['trees']['current']
    if fc.tree_hashes(root) != identity['current_files_sha256']:
        raise fc.EvidenceError('current tree changed since prepare')
    features = list(FEATURES) if args.features == ['all'] else args.features
    for f in features:
        if f not in FEATURES:
            raise SystemExit(f'unknown feature {f}')
    failures = 0
    for mode in args.modes:
        for feature in features:
            for rep, arm in enumerate(QUAD, 1):
                case = case_name(feature, arm, mode, rep)
                argv = [sys.executable, 'tools/y8_feature_ablation.py', 'capture', '--root', root, '--output', str(out),
                        '--mode', mode, '--seed', str(SEED), '--case', case, '--profile', PROFILE, '--windows', '1',
                        '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms)]
                if arm == 'candidate':
                    argv += ['--feature', feature]
                failures += receipt(out, f'{feature}/{arm}/{mode}/{rep}', argv) != 0
    print(f'RUN DONE modes={args.modes} features={features} failed_captures={failures}', flush=True)
    return 1 if failures else 0


# ---------------------------------------------------------------- prove --

def simulate(feature, mode, frames, root=ROOT):
    from browser_test_support import start_browser_test
    cfg = {'dpr': 1, 'input': 'mouse', 'ablate': [], 'diagnostic': True,
           'replay': fc.replay_script(SEED, PROFILE, frames * 17), 'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
    with ExitStack() as stack:
        url, browser = start_browser_test(Path(root), stack.callback)
        ctx = fc.new_context(browser, PROFILE, SEED, [])
        stack.callback(ctx.close)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html', wait_until='domcontentloaded')
        page.wait_for_function(fc.BOOTED, timeout=60000)
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate(FEATURE_INSTRUMENT, feature_cfg(feature))
        result = page.evaluate(SIMULATION, {'mode': mode, 'frames': frames})
        result['errors'] = errors
    result['particleDigestSha'] = fc.sha_bytes(json.dumps(result.pop('particleDigest')).encode())
    return result


def equality(reference, candidate):
    """Keys whose values differ between two simulation results (empty = equal)."""
    return [k for k in EQUALITY_KEYS if reference[k] != candidate[k]]


def prove(args, features=None, frames=None):
    out = Path(args.output)
    features = features or list(FEATURES)
    frames = frames or args.frames
    started = utc()
    report = {'task': TASK, 'utc_start': started, 'argv': sys.argv, 'frames': frames, 'modes': {},
              'method': 'synthetic requestAnimationFrame timestamps at 60 Hz and performance.now pinned to the same '
                        'clock; seeded Math.random; fc.INSTRUMENT physics counter (--diagnostic, never paired with '
                        'primary captures); each arm is a fresh page; equality over ' + ', '.join(EQUALITY_KEYS),
              'equality_keys': list(EQUALITY_KEYS)}
    ok = True
    for mode in args.modes:
        reference = simulate(None, mode, frames)
        repeat = simulate(None, mode, frames)
        arms = {'reference': reference, 'reference-repeat': repeat}
        checks = {'reference-repeat': {'differs': equality(reference, repeat)}}
        for feature in features:
            r = simulate(feature, mode, frames)
            arms[feature] = r
            diff = equality(reference, r)
            check = {'differs': diff, 'skipped_draw_calls': r['skipped'].get(feature, 0),
                     'ablated': r['ablated'], 'active': r['featureActive'].get(feature), 'errors': r['errors'],
                     'pass': not diff and not r['errors'] and r['skipped'].get(feature, 0) > 0 and r['ablated'] == [FEATURES[feature]['removes']]}
            ok &= check['pass']
            checks[feature] = check
            print(f'{"PASS" if check["pass"] else "FAIL"} equality {mode} {feature}: differs={diff} '
                  f'skipped_draw_calls={check["skipped_draw_calls"]} physics_steps={r["steps"]} '
                  f'particle_updates={r["particleUpdates"]} particles={r["particleCount"]} '
                  f'track_points={r["trackPoints"]} score={r["score"]} ninja={r["ninja"]}', flush=True)
        ok &= not checks['reference-repeat']['differs'] and reference['particleUpdates'] > 0 and reference['steps'] > 0
        print(f'{"PASS" if not checks["reference-repeat"]["differs"] else "FAIL"} determinism {mode}: '
              f'reference repeat differs={checks["reference-repeat"]["differs"]} physics_steps={reference["steps"]} '
              f'particle_updates={reference["particleUpdates"]} particles={reference["particleCount"]}', flush=True)
        report['modes'][mode] = {'arms': arms, 'checks': checks}
    report['utc_end'] = utc()
    report['pass'] = ok
    fc.dump(out / 'state-equality.json', report)
    print(('PASS' if ok else 'FAIL'), 'state equality written', out / 'state-equality.json')
    return 0 if ok else 1


# --------------------------------------------------------------- report --

def mean_ms(summary):
    return 1000 / summary['combined']['average_fps']


def pair_delta(control, candidate):
    """fc.compare plus mean frame-time delta; negative ms = candidate faster."""
    d = fc.compare(control, candidate)
    d['delta_mean_ms'] = mean_ms(candidate['summary']) - mean_ms(control['summary'])
    d['control_fps'] = control['summary']['combined']['average_fps']
    d['candidate_fps'] = candidate['summary']['combined']['average_fps']
    return d


def classify(deltas, active, threshold_max, threshold_typical=None):
    """Tiered against the control-control spread (negative delta = saving).

    REPEATED_SAVING: every pair saves more than the worst control-control spread.
    CONSISTENT_SAVING: every pair saves more than the typical (median) spread.
    INCONSISTENT: some pair exceeds the worst spread but the sign/size does not repeat.
    NO_BENEFIT: nothing beyond the worst spread and no consistent saving.
    """
    if threshold_typical is None:
        threshold_typical = threshold_max
    if not active:
        return 'INACTIVE'
    if not deltas:
        return 'MISSING'
    if all(d < -threshold_max for d in deltas):
        return 'REPEATED_SAVING'
    if all(d < -threshold_typical for d in deltas):
        return 'CONSISTENT_SAVING'
    if any(abs(d) > threshold_max for d in deltas):
        return 'INCONSISTENT'
    return 'NO_BENEFIT'


def load_raws(out, manifest_paths=None):
    raws = {}
    for p in sorted((Path(out) / 'raw').glob('*.json')):
        raws[f'raw/{p.name}'] = fc.load(p)
    return raws


def complete_case(raws, case):
    hits = [r for r in raws.values() if r['case'] == case and r.get('result') == 'COMPLETE']
    if len(hits) > 1:
        raise fc.EvidenceError(f'duplicate complete case {case}')
    return hits[0] if hits else None


def arm_record(raw, path):
    s = raw['summary']
    w = s['windows'][0]
    return {'case': raw['case'], 'raw': path, 'result': raw['result'], 'feature': raw['settings']['feature'],
            'ablated': raw['ablated'], 'skipped_draw_calls': raw['skipped'],
            'feature_active': raw['featureActive'], 'stage_flags': raw['stageFlags'],
            'features': raw['features'], 'quality': raw['quality'], 'density_pin': raw['densityPin'],
            'backing': raw['dimensions']['canvas'], 'replay_sha256': raw['settings']['replay_sha256'],
            'frames_sha256': raw['frames_sha256'], 'deaths': s['deaths'], 'excluded_frames': s['excluded_frames'],
            'dispatched_inputs': s['dispatched_inputs'], 'warmup_frames': s['warmup_frames'],
            'window': w, 'mean_ms': 1000 / w['average_fps'],
            'intervals_ms': [f['dt'] for f in fc.split_windows(raw['frames'], raw['settings']['warmup_ms'],
                                                               raw['settings']['window_ms'], raw['settings']['windows'])[0][1:]
                             if f['dt'] is not None]}


def build(out, modes):
    """ablation/ranking/decision structures recomputed from raw files (shared by report and audit)."""
    out = Path(out)
    raws = load_raws(out)
    equality_report = fc.load(out / 'state-equality.json') if (out / 'state-equality.json').exists() else None
    arms, quads, control_spread, pairs_by_feature = {}, [], [], {f: {m: [] for m in modes} for f in FEATURES}
    inactive = {}
    for mode in modes:
        for feature in FEATURES:
            cases = [case_name(feature, arm, mode, rep) for rep, arm in enumerate(QUAD, 1)]
            paths = {c: next((p for p, r in raws.items() if r['case'] == c and r.get('result') == 'COMPLETE'), None) for c in cases}
            got = {c: complete_case(raws, c) for c in cases}
            quad = {'feature': feature, 'mode': mode, 'order': list(QUAD), 'cases': cases,
                    'attempts': [p for p, r in raws.items() if r['case'] in cases],
                    'failed_attempts': [p for p, r in raws.items() if r['case'] in cases and r.get('result') != 'COMPLETE']}
            if not all(got.values()):
                quad['result'] = 'MISSING: ' + ', '.join(c for c, r in got.items() if not r)
                quads.append(quad)
                continue
            for c, r in got.items():
                arms[c] = arm_record(r, paths[c])
            ctl1, cand2, cand3, ctl4 = (got[c] for c in cases)
            try:
                quad['pairs'] = [dict(pair_delta(ctl1, cand2), order='control-first'),
                                 dict(pair_delta(ctl4, cand3), order='candidate-first')]
                cc = pair_delta(ctl1, ctl4)
                quad['control_control'] = {'control': ctl1['case'], 'repeat': ctl4['case'],
                                           'delta_mean_ms': cc['delta_mean_ms'], 'delta_average_fps': cc['delta_average_fps'],
                                           'delta_p50_ms': cc['delta_p50_ms']}
                control_spread.append(abs(cc['delta_mean_ms']))
            except fc.EvidenceError as e:
                quad['result'] = 'REJECTED: ' + str(e)
                quads.append(quad)
                continue
            active = {c: r['featureActive'].get(feature) for c, r in got.items()}
            quad['feature_active'] = active
            quad['hook_installed'] = {c: r['ablated'] for c, r in got.items()}
            quad['skipped_draw_calls'] = {c: r['skipped'].get(feature, 0) for c, r in got.items()}
            quad['matched'] = {
                'settings': all(all(r['settings'].get(k) == ctl1['settings'].get(k) for k in fc.PAIRED_SETTINGS) for r in got.values()),
                'replay_sha256': len({r['settings']['replay_sha256'] for r in got.values()}) == 1,
                'backing': sorted({tuple(f['canvas']) for r in got.values() for f in r['frames']}),
                'features_quality': len({json.dumps([r['features'], r['quality']], sort_keys=True) for r in got.values()}) == 1,
                'feature_active_equal': len(set(map(str, active.values()))) == 1,
                'stage_flags_equal': len({json.dumps(r['stageFlags'], sort_keys=True) for r in got.values()}) == 1,
                'deaths': {c: r['summary']['deaths'] for c, r in got.items()},
                'excluded_frames': {c: r['summary']['excluded_frames'] for c, r in got.items()},
                'dispatched_inputs': {c: r['summary']['dispatched_inputs'] for c, r in got.items()},
                'tree_identical': len({json.dumps(r['tree']['files_sha256'], sort_keys=True) for r in got.values()}) == 1}
            quad['result'] = 'PAIRED' if all(v is True for k, v in quad['matched'].items()
                                            if k not in ('backing', 'deaths', 'excluded_frames', 'dispatched_inputs')) \
                and len(quad['matched']['backing']) == 1 else 'MISMATCH'
            quads.append(quad)
            if quad['result'] == 'PAIRED':
                pairs_by_feature[feature][mode] = quad['pairs']
            if not all(active.values()):
                inactive[feature] = active
    threshold = max(control_spread) if control_spread else None
    typical = statistics.median(control_spread) if control_spread else None
    ranking_rows = []
    for feature in FEATURES:
        deltas = {m: [p['delta_mean_ms'] for p in pairs_by_feature[feature][m]] for m in modes}
        flat = [d for m in modes for d in deltas[m]]
        active = feature not in inactive
        cls = classify(flat, active, threshold, typical) if threshold is not None else 'MISSING'
        complete = all(len(deltas[m]) == 2 for m in modes)
        if not complete and cls not in ('INACTIVE',):
            cls = 'MISSING'
        row = {'feature': feature, 'removes': FEATURES[feature]['removes'], 'active': active,
               'classification': cls, 'pairs_measured': len(flat), 'pairs_expected': 2 * len(modes),
               'delta_mean_ms_by_mode': deltas,
               'delta_fps_by_mode': {m: [p['delta_average_fps'] for p in pairs_by_feature[feature][m]] for m in modes},
               'delta_p50_ms_by_mode': {m: [p['delta_p50_ms'] for p in pairs_by_feature[feature][m]] for m in modes},
               'delta_p95_ms_by_mode': {m: [p['delta_p95_ms'] for p in pairs_by_feature[feature][m]] for m in modes},
               'median_delta_mean_ms': statistics.median(flat) if flat else None,
               'min_saving_ms': -max(flat) if flat else None, 'max_saving_ms': -min(flat) if flat else None,
               'eligible': cls in ('REPEATED_SAVING', 'CONSISTENT_SAVING')}
        ranking_rows.append(row)
    order = {'REPEATED_SAVING': 0, 'CONSISTENT_SAVING': 1, 'INCONSISTENT': 2, 'NO_BENEFIT': 3, 'INACTIVE': 4, 'MISSING': 5}
    ranking_rows.sort(key=lambda r: (order[r['classification']], r['median_delta_mean_ms'] if r['median_delta_mean_ms'] is not None else 0))
    eligible = [r for r in ranking_rows if r['eligible']]
    stage_flags = {}
    for a in arms.values():
        for k, v in a['stage_flags'].items():
            stage_flags.setdefault(k, set()).add(v)
    stage_flags = {k: sorted(v, key=str) for k, v in stage_flags.items()}
    ablation = {
        'task': TASK, 'protocol': 'artifacts/TASK-271/protocol.json screening: control, candidate, candidate, control; '
                                  'fixed seed 4; 5 s warmup + one 10 s window per capture; desktop 1280x720 DPR 1; '
                                  'CPU throttle 1; two measured windows per arm per mode',
        'modes': modes, 'features': {k: dict(v) for k, v in FEATURES.items()},
        'inactive_pipeline_stages': {k: v for k, v in stage_flags.items() if v == [False]},
        'stage_flags_observed': stage_flags,
        'inactive_arms': inactive,
        'arms': arms, 'quads': quads,
        'control_control_spread_mean_ms': control_spread, 'noise_threshold_mean_ms': threshold,
        'noise_typical_mean_ms': typical,
        'simulation_equality': {'path': 'state-equality.json', 'pass': equality_report['pass'],
                                'checks': {m: {k: {'differs': c['differs'], 'skipped_draw_calls': c.get('skipped_draw_calls')}
                                               for k, c in v['checks'].items()} for m, v in equality_report['modes'].items()}}
        if equality_report else None,
        'sign_convention': 'delta = candidate - control; negative delta_mean_ms/delta_p50_ms and positive delta_average_fps '
                           'mean the arm without the feature drawing was faster',
        'limits': 'software headless Chromium under shared host load; paired deltas within a quad are the signal; '
                  'no 60 FPS, device or readiness claim'}
    ranking = {'task': TASK, 'metric': 'mean frame time per measured window (1000 / average_fps), candidate minus control, '
                                       'one pair per order within each quad, both modes',
               'noise_threshold_mean_ms': threshold, 'noise_typical_mean_ms': typical,
               'threshold_rule': 'noise_threshold = max |control - control| mean frame-time difference over every quad, '
                                 'noise_typical = its median; REPEATED_SAVING needs every pair of both modes beyond the max, '
                                 'CONSISTENT_SAVING every pair beyond the median, INCONSISTENT some pair beyond the max '
                                 'without repeating, NO_BENEFIT nothing beyond the max and no consistent saving',
               'rows': ranking_rows,
               'simulation_equality_pass': equality_report['pass'] if equality_report else None}
    repeated = [r for r in eligible if r['classification'] == 'REPEATED_SAVING']
    consistent = [r for r in eligible if r['classification'] == 'CONSISTENT_SAVING']
    verdict = (f'{len(repeated)} feature(s) save beyond the worst control-control spread ({threshold} ms) in every pair; '
               f'{len(consistent)} more save in every pair beyond the typical spread ({typical} ms) but not the worst; '
               f'{len(eligible)} eligible in total, top three taken in tier order')
    if not eligible:
        verdict = 'no feature shows a repeatable saving beyond the control-control spread'
    decision = {'task': TASK, 'top_three_eligible': [r['feature'] for r in eligible[:3]],
                'eligible': [{'feature': r['feature'], 'tier': r['classification'], 'median_delta_mean_ms': r['median_delta_mean_ms'],
                              'range_saving_ms': [r['min_saving_ms'], r['max_saving_ms']],
                              'delta_mean_ms_by_mode': r['delta_mean_ms_by_mode']} for r in eligible],
                'repeated_saving': [r['feature'] for r in repeated], 'consistent_saving': [r['feature'] for r in consistent],
                'inconsistent': [r['feature'] for r in ranking_rows if r['classification'] == 'INCONSISTENT'],
                'no_benefit': [r['feature'] for r in ranking_rows if r['classification'] == 'NO_BENEFIT'],
                'inactive': [r['feature'] for r in ranking_rows if r['classification'] == 'INACTIVE'],
                'missing': [r['feature'] for r in ranking_rows if r['classification'] == 'MISSING'],
                'noise_threshold_mean_ms': threshold, 'noise_typical_mean_ms': typical, 'verdict': verdict,
                'uncertainty': 'Deltas are from one software-rendered host under unrelated load (loadavg 4-10); the replay '
                               'can die at different times in different arms (deaths recorded, never suppressed), so '
                               'segments are equal in input but not always in level content, and the worst control-control '
                               'spread comes from such a quad. CONSISTENT_SAVING features repeat in sign across all four '
                               'pairs but their size is not separated from the worst-case control spread; treat their rank '
                               'order as provisional until the shortlist protocol (three 30 s pairs) measures them. '
                               'Savings measured here are for the diagnostic clone only; nothing is removed from the shipped game.',
                'not_claimed': ['60 FPS', 'release readiness', 'physical-device performance', 'production feature removal']}
    return {'ablation': ablation, 'ranking': ranking, 'decision': decision, 'raws': raws}


def report(args):
    out = Path(args.output)
    built = build(out, args.modes)
    identity_file = fc.load(out / 'identity.json')
    identity = identity_file['identity']
    commands = [json.loads(line) for line in (out / 'commands.jsonl').read_text().splitlines() if line.strip()]
    raws = built['raws']
    first = next(iter(raws.values()))
    fc.dump(out / 'ablation.json', built['ablation'])
    fc.dump(out / 'ranking.json', built['ranking'])
    fc.dump(out / 'decision.json', built['decision'])
    evidence = sorted(['ablation.json', 'ranking.json', 'decision.json', 'identity.json', 'commands.jsonl',
                       'state-equality.json'] + list(raws) +
                      ([MODULE_AT_CAPTURE] if (out / MODULE_AT_CAPTURE).exists() else []))
    arms = built['ablation']['arms']
    manifest = {
        'task': TASK, 'utc_start': identity_file['utc_start'], 'utc_end': utc(), 'report_argv': sys.argv,
        'commands': [{'label': 'prepare', 'argv': identity_file['argv'], 'utc_start': identity_file['utc_start'],
                      'utc_end': identity_file['utc_end'], 'exit_code': 0}] + commands +
                    ([{'label': 'prove', 'argv': fc.load(out / 'state-equality.json')['argv'],
                       'utc_start': fc.load(out / 'state-equality.json')['utc_start'],
                       'utc_end': fc.load(out / 'state-equality.json')['utc_end'],
                       'exit_code': 0 if fc.load(out / 'state-equality.json')['pass'] else 1}]
                     if (out / 'state-equality.json').exists() else []),
        'source_revision': identity['current_commit'], 'source_revision_at_report': fc.git('rev-parse', 'HEAD'),
        'source_dirty_runtime': identity['current_dirty_runtime'],
        'source_dirty_at_report': fc.git('status', '--porcelain', '--untracked-files=no'),
        'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(MODULE),
        'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py'),
        'ablation_sha256_at_capture': sorted({r['ablation_sha256'] for r in raws.values()}),
        'module_at_capture': MODULE_AT_CAPTURE if (out / MODULE_AT_CAPTURE).exists() else None,
        'executed_hashes': {'harness_sha256_in_raws': sorted({r['harness_sha256'] for r in raws.values()}),
                            'ablation_sha256_in_raws': sorted({r['ablation_sha256'] for r in raws.values()}),
                            'note': 'captures were executed by ablation_sha256_at_capture; report/audit by ablation_sha256; '
                                    'when they differ the capture-time module is preserved byte-for-byte at module_at_capture'},
        'candidate_hashes': {'current_tar_sha256': identity['current_tar_sha256'],
                             'current_files_sha256': identity['current_files_sha256'],
                             'tree_sha256_sets_in_raws': sorted({fc.sha_bytes(json.dumps(r['tree']['files_sha256'], sort_keys=True).encode())
                                                                 for r in raws.values()})},
        'environment': {**first['environment'], 'ceiling': identity_file['environment_ceiling']},
        'fixed': {'profile': fc.PROFILES[PROFILE], 'backing_size_by_arm': {k: v['backing'] for k, v in arms.items()},
                  'seed': SEED, 'warmup_ms': first['settings']['warmup_ms'], 'window_ms': first['settings']['window_ms'],
                  'windows_per_capture': first['settings']['windows'], 'cpu_throttle': first['settings']['cpu_throttle'],
                  'input': f'replay_script({SEED}, {PROFILE}, total_ms) scheduled on the active clock; '
                           f'replay_sha256 {sorted({r["settings"]["replay_sha256"] for r in raws.values()})}',
                  'state': 'per-frame menu/paused/offer/hidden/ad recorded; inactive frames excluded; deaths recorded via '
                           'reStart hook and never suppressed; feature active flags and stage flags read in-page per arm'},
        'sdk_isolation': first['settings']['sdk_isolation'],
        'evidence_paths': evidence, 'sha256': {name: fc.sha_file(out / name) for name in evidence},
        'failed_attempts_preserved': sorted(set([c['label'] for c in commands if c['exit_code'] != 0] +
                                                [p for p, r in raws.items() if r.get('result') != 'COMPLETE'])),
        'note': 'A successful evidence audit is separate from the performance verdict; see decision.json.'}
    fc.dump(out / 'manifest.json', manifest)
    print('PASS report written', out / 'ablation.json', out / 'ranking.json', out / 'decision.json', out / 'manifest.json')
    print('verdict:', built['decision']['verdict'], 'top_three_eligible:', built['decision']['top_three_eligible'])
    return 0


# ---------------------------------------------------------------- audit --

def audit(args):
    out = Path(args.output)
    m = fc.load(out / 'manifest.json')
    for name, digest in m['sha256'].items():
        if fc.sha_file(out / name) != digest:
            raise fc.EvidenceError(f'SHA256 mismatch {name}')
    print(f'PASS manifest seal: {len(m["sha256"])} evidence files match SHA256')
    if fc.sha_file(fc.HARNESS) != m['harness_sha256'] or fc.sha_file(MODULE) != m['ablation_sha256']:
        raise fc.EvidenceError('harness or ablation module changed since report')
    print('PASS harness sha256 unchanged', m['harness_sha256'], 'ablation sha256 unchanged since report', m['ablation_sha256'])
    if len(m['ablation_sha256_at_capture']) != 1:
        raise fc.EvidenceError('captures executed by more than one module version')
    if m['ablation_sha256_at_capture'] != [m['ablation_sha256']]:
        if not m['module_at_capture'] or fc.sha_file(out / m['module_at_capture']) != m['ablation_sha256_at_capture'][0]:
            raise fc.EvidenceError('capture-time module not preserved')
        print('INFO captures executed by module', m['ablation_sha256_at_capture'][0], 'preserved at', m['module_at_capture'],
              '; report/audit module', m['ablation_sha256'], '(diff the two files: only post-capture audit/report code may differ)')
    for c in m['commands']:
        if not (c['argv'] and c['utc_start'] <= c['utc_end'] and isinstance(c['exit_code'], int)):
            raise fc.EvidenceError('command receipt incomplete: ' + json.dumps(c)[:200])
    print(f'PASS {len(m["commands"])} commands with argv/UTC start-end/exit codes; failed attempts preserved:',
          m['failed_attempts_preserved'])
    identity = fc.load(out / 'identity.json')['identity']
    modes = fc.load(out / 'ablation.json')['modes']
    raws = load_raws(out)
    complete = 0
    for name, raw in raws.items():
        if name not in m['sha256']:
            raise fc.EvidenceError(f'{name} not sealed in manifest')
        if raw['harness_sha256'] != m['harness_sha256'] or raw['ablation_sha256'] not in m['ablation_sha256_at_capture']:
            raise fc.EvidenceError(f'{name} captured by a different harness')
        if fc.frames_sha256(raw['frames']) != raw['frames_sha256']:
            raise fc.EvidenceError(f'{name} frames altered')
        if raw['tree']['files_sha256'] != identity['current_files_sha256']:
            raise fc.EvidenceError(f'{name} ran on a tree other than the verified HEAD archive')
        if raw.get('result') != 'COMPLETE':
            print('INFO failed attempt preserved', name, raw.get('result'))
            continue
        if fc.summarize(raw) != raw['summary']:
            raise fc.EvidenceError(f'{name} summary does not match recomputation')
        if {tuple(f['canvas']) for f in raw['frames']} != {tuple(raw['dimensions']['canvas'])}:
            raise fc.EvidenceError(f'{name} backing size varies')
        if raw['dimensions']['platform'] not in ('disabled', 'absent'):
            raise fc.EvidenceError(f'{name} SDK not isolated')
        if raw['errors'] or raw['error']:
            raise fc.EvidenceError(f'{name} has page errors')
        if raw['settings']['diagnostic']:
            raise fc.EvidenceError(f'{name} diagnostic capture used as primary')
        feature = raw['settings']['feature']
        expected = [FEATURES[feature]['removes']] if feature else []
        if raw['ablated'] != expected:
            raise fc.EvidenceError(f'{name} hook mismatch {raw["ablated"]} != {expected}')
        if feature and not raw['skipped'].get(feature):
            raise fc.EvidenceError(f'{name} disabled hook never reached')
        if not feature and raw['skipped']:
            raise fc.EvidenceError(f'{name} control arm skipped drawing {raw["skipped"]}')
        for w in raw['summary']['windows']:
            if w['active_ms'] < raw['settings']['window_ms']:
                raise fc.EvidenceError(f'{name} short window')
        c = raw['summary']['combined']
        complete += 1
        print(f'PASS recomputed {raw["case"]}: feature={feature} active={raw["featureActive"].get(feature) if feature else "-"} '
              f'skipped={raw["skipped"]} intervals={c["intervals"]} active_ms={c["active_ms"]:.1f} fps={c["average_fps"]:.2f} '
              f'mean_ms={1000 / c["average_fps"]:.2f} p50={c["frame_ms"]["p50"]:.2f} p95={c["frame_ms"]["p95"]:.2f} '
              f'p99={c["frame_ms"]["p99"]:.2f} max={c["frame_ms"]["max"]:.2f} backing={raw["dimensions"]["canvas"]} '
              f'deaths={raw["summary"]["deaths"]} excluded_frames={raw["summary"]["excluded_frames"]}')
    built = build(out, modes)
    for name in ('ablation', 'ranking', 'decision'):
        if json.loads(json.dumps(built[name], sort_keys=True)) != fc.load(out / f'{name}.json'):
            raise fc.EvidenceError(f'{name}.json differs from recomputation')
    print(f'PASS ablation.json, ranking.json and decision.json match recomputation from {complete} complete raw files')
    ab = built['ablation']
    paired = [q for q in ab['quads'] if q['result'] == 'PAIRED']
    for q in ab['quads']:
        print(f'{"PASS" if q["result"] == "PAIRED" else "INFO"} quad {q["feature"]}/{q["mode"]}: {q["result"]} '
              + (f'active={sorted(set(map(str, q["feature_active"].values())))} backing={q["matched"]["backing"]} '
                 f'skipped={list(q["skipped_draw_calls"].values())} deaths={list(q["matched"]["deaths"].values())} '
                 f'dMean_ms={[round(p["delta_mean_ms"], 2) for p in q["pairs"]]} dFPS={[round(p["delta_average_fps"], 2) for p in q["pairs"]]} '
                 f'control-control={q["control_control"]["delta_mean_ms"]:+.2f}ms' if q['result'] == 'PAIRED' else ''))
    expected_quads = len(FEATURES) * len(modes)
    print(f'{"PASS" if len(paired) == expected_quads else "FAIL"} {len(paired)} of {expected_quads} quads paired; '
          f'inactive pipeline stages {ab["inactive_pipeline_stages"]}; inactive arms {list(ab["inactive_arms"])}; '
          f'noise threshold {ab["noise_threshold_mean_ms"]}')
    if len(paired) != expected_quads:
        raise fc.EvidenceError('incomplete quads')
    eq = fc.load(out / 'state-equality.json')
    if not eq['pass']:
        raise fc.EvidenceError('state equality proof failed')
    for mode, v in eq['modes'].items():
        for k, c in v['checks'].items():
            if c['differs']:
                raise fc.EvidenceError(f'state differs {mode} {k} {c["differs"]}')
    print(f'PASS state equality: {len(eq["modes"])} modes x {len(FEATURES)} features, physics steps / particle updates / '
          f'track points / score / world identical with each feature drawing disabled; keys {eq["equality_keys"]}')
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    runtime = [n for n in tracked if n.endswith(fc.RUNTIME_SUFFIXES) and not n.startswith('tools/')]
    for name in runtime:
        text = (ROOT / name).read_text(errors='replace')
        if fc.MARKER in text or 'skip("' in text:
            raise fc.EvidenceError(f'diagnostic hook in shipped runtime: {name}')
    print(f'PASS no diagnostic hook marker in {len(runtime)} git-tracked shipped runtime files')
    for row in built['ranking']['rows']:
        print(f'INFO rank {row["classification"]:16} {row["feature"]:18} median dMean={row["median_delta_mean_ms"]} '
              f'by mode {json.dumps({m: [round(x, 2) for x in v] for m, v in row["delta_mean_ms_by_mode"].items()})}')
    env = m['environment']
    print('PASS environment: os=%s browser=%s playwright=%s gpu=%s ceiling_fps=%.2f' % (
        env['os'], env['browser'], env['playwright'], env['gpu']['auxAttributes'].get('glRenderer'), env['ceiling']['average_fps']))
    print('PASS evidence audit complete; performance verdict is separate:', built['decision']['verdict'],
          'top_three_eligible=', built['decision']['top_three_eligible'])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--output', required=True)
    p.set_defaults(func=prepare)
    c = sub.add_parser('capture')
    c.add_argument('--root', required=True)
    c.add_argument('--output', required=True)
    c.add_argument('--mode', required=True, choices=fc.MODES)
    c.add_argument('--seed', required=True, type=int)
    c.add_argument('--case', required=True)
    c.add_argument('--profile', default=PROFILE, choices=sorted(fc.PROFILES))
    c.add_argument('--cpu-throttle', type=int, default=1)
    c.add_argument('--warmup-ms', type=int, default=5000)
    c.add_argument('--window-ms', type=int, default=10000)
    c.add_argument('--windows', type=int, default=1)
    c.add_argument('--feature', default=None, help='disable drawing of this feature (diagnostic only); omit for control')
    c.add_argument('--timeout-ms', type=int, default=240000)
    c.set_defaults(func=capture)
    r = sub.add_parser('run')
    r.add_argument('--output', required=True)
    r.add_argument('--features', nargs='+', default=['all'])
    r.add_argument('--modes', nargs='+', default=list(fc.MODES), choices=fc.MODES)
    r.add_argument('--warmup-ms', type=int, default=5000)
    r.add_argument('--window-ms', type=int, default=10000)
    r.set_defaults(func=run)
    v = sub.add_parser('prove')
    v.add_argument('--output', required=True)
    v.add_argument('--modes', nargs='+', default=list(fc.MODES), choices=fc.MODES)
    v.add_argument('--frames', type=int, default=240)
    v.set_defaults(func=prove)
    e = sub.add_parser('report')
    e.add_argument('--output', required=True)
    e.add_argument('--modes', nargs='+', default=list(fc.MODES), choices=fc.MODES)
    e.set_defaults(func=report)
    a = sub.add_parser('audit')
    a.add_argument('--output', required=True)
    a.set_defaults(func=audit)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
