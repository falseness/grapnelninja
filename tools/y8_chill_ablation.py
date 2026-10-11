"""Chill-mode feature costs on the TASK-271 harness with the TASK-272 ablations (TASK-273).

Chill is the menu's "chill version", runtime mode 'classic'; Main is runtime
mode 'bad'. TASK-272 screened both modes together on seed 4, where every Chill
capture died once or twice (camera reset, world regenerated). Here Chill is
measured as its own population: a seed screen picks a documented replay segment
that keeps the camera moving without a death, every arm samples camera position
and particle/trail/world counts per frame, the eight draw-only hooks of
tools/y8_feature_ablation.py are reused unchanged, and the result is joined to
the TASK-272 Main (bad-mode) raw files feature by feature without pooling any
sample across modes or populations.

Actions
  prepare    verified HEAD tree, environment ceiling, identity.json
  capture    one browser session with the TASK-272 feature hook (control when
             --feature is omitted) plus the read-only camera/density sampler
  segment    Chill control captures for several seeds; segment.json documents
             deaths, camera travel and density per seed and the chosen segment
  run        control/candidate/candidate/control quads for the eight features
             in Chill with the chosen seed; receipts in commands.jsonl
  reference  Main density reference: control captures with the sampler on the
             TASK-272 protocol (seed 4); counts only, never paired with Chill
  prove      state equality with the sampler installed (synthetic clock, Chill)
  report     ablation.json, mode-comparison.json, decision.json, manifest.json
  audit      recompute every per-arm delta and density figure, verify seals,
             hooks, flags, samples and the join against the TASK-272 raw files

Nothing here certifies 60 FPS, physical devices or release readiness; the
hooks live in the diagnostic clone page only (marker __featureCost).
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
import y8_feature_ablation as ab  # noqa: E402

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
TASK = 'TASK-273'
PROFILE = 'desktop'
CHILL, MAIN = 'classic', 'bad'
MODE_NAMES = {CHILL: 'Chill (menu "chill version", runtime mode classic)', MAIN: 'Main (menu "main version", runtime mode bad)'}
MAIN_SOURCE = ROOT / 'artifacts/TASK-272'
MAIN_SEED = 4
DEFAULT_SCREEN_SEEDS = (4, 1, 49, 7, 11, 23)
QUAD = ab.QUAD
FEATURES = ab.FEATURES
# Draw pipeline stage each feature hook replaces (names from render/draw.js / render/effects.js).
STAGES = {
    'ambient-glow': 'ParticleSystem.drawAmbientMotes (+ AmbientGlowRenderer chain)',
    'player-glow': 'drawPlayerGlowLayer',
    'obstacle-lighting': 'drawLightsLayer',
    'cave-background': 'drawBackgroundLayer',
    'player-trail': 'drawPlayerTrailLayer',
    'particles': 'ParticleSystem.draw + drawBehindForeground',
    'world-geometry': 'drawWorldLayer',
    'hud': 'drawUILayer',
}
MODULE_AT_CAPTURE = 'module-at-capture/y8_chill_ablation.py'
# Replay styles. 'screening' is the TASK-271 script unchanged (random throws at 40-85 % width,
# 15-60 % height): in Chill it lets the ninja fall to the lethal floor 7-9 s after every start
# (segment screen, all six seeds). The Chill styles aim up and ahead so the grapnel hooks the
# ceiling band / upper obstacles and the pull (4x gravity) carries the ninja right: the camera
# follows once the ninja passes 35 % of the width. Same event format, same active-clock scheduling,
# same SHA256 pairing rule; the style name and SHA256 are recorded in every raw file.
REPLAY_STYLES = {
    'screening': None,
    'chill-ceiling': {'x': (0.70, 0.92), 'y': (0.03, 0.09), 'hold': (350, 650), 'gap': (80, 250)},
    'chill-upper': {'x': (0.60, 0.90), 'y': (0.08, 0.25), 'hold': (400, 800), 'gap': (80, 300)},
    'chill-swing': {'x': (0.75, 0.95), 'y': (0.05, 0.20), 'hold': (300, 550), 'gap': (60, 200)},
}


def replay_script(seed, profile, total_ms, style='screening'):
    """Bounded seeded grapnel throws [{t_ms, type: start|end, x, y}] in CSS px, scheduled on the active clock."""
    box = REPLAY_STYLES[style]
    if box is None:
        return fc.replay_script(seed, profile, total_ms)
    width, height = fc.PROFILES[profile]['viewport']
    import random
    rng = random.Random(seed * 1000003 + total_ms + sum(map(ord, style)))
    events, t = [], 400
    while True:
        hold = rng.randint(*box['hold'])
        if t + hold > total_ms:
            break
        x = round(rng.uniform(*box['x']) * width, 1)
        y = round(rng.uniform(*box['y']) * height, 1)
        events.append({'t_ms': t, 'type': 'start', 'x': x, 'y': y})
        events.append({'t_ms': t + hold, 'type': 'end', 'x': x, 'y': y})
        t += hold + rng.randint(*box['gap'])
    return events
SAMPLE_KEYS = ('sx', 'sy', 'nx', 'ny', 'particles', 'pool', 'motes', 'track', 'obstacleTrack', 'elements', 'lights', 'score')

# Installed after fc.INSTRUMENT and ab.FEATURE_INSTRUMENT, before startGame. Read-only:
# one sample per active frame (the frame fc.INSTRUMENT just recorded), taken after the
# game loop ran, so camera motion and density are visible per frame and per window.
SAMPLER = '''() => {
    const FC = window.__featureCost
    FC.samples = []
    FC.sampler = 'read-only per active frame after gameLoop: camera screen.x/y, ninja x/y, particles, pool, ambient motes, '
        + 'player track points, obstacle track points, world elements, lightmap hasLights, score, deaths so far'
    const read = f => { try { const v = f(); return typeof v === 'number' ? v : (v === true ? 1 : v === false ? 0 : v) } catch (e) { return null } }
    const inner = window.gameLoop
    window.gameLoop = function(t) {
        const n = FC.frames.length
        const r = inner.call(this, t)
        if (FC.frames.length > n && FC.frames[n].t === t)
            FC.samples.push({t,
                sx: read(() => screen.x), sy: read(() => screen.y),
                nx: read(() => ninja.x), ny: read(() => ninja.y),
                particles: read(() => visualEffects.particles.particles.length),
                pool: read(() => visualEffects.particles.pool.length),
                motes: read(() => visualEffects.particles.ambientMotes ? visualEffects.particles.ambientMotes.length : 0),
                track: read(() => ninja.track.pos.length),
                obstacleTrack: read(() => floors.reduce((a, f) => a + f.elements.reduce((m, e) => m + (e.track ? e.track.pos.length : 0), 0), 0)),
                elements: read(() => floors.reduce((a, f) => a + f.elements.length, 0)),
                lights: read(() => visualEffects.lightmap.hasLights),
                score: read(() => scoreText.count[version]),
                deaths: FC.deaths.length})
        return r
    }
}'''


def utc():
    return fc.utc()


def case_name(feature, arm, mode, seed, rep):
    return f'{feature}-{arm}-{mode}-{PROFILE}-s{seed}-w{rep}'


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {'mean': statistics.fmean(values), 'min': min(values), 'max': max(values), 'n': len(values)}


def window_density(raw):
    """Camera motion and density of the measured window, from the per-frame samples.

    Camera travel sums |dx|+|dy| of screen (logical px) between consecutive samples
    of the same life; the jump of a death reset is excluded and counted separately.
    """
    s = raw['settings']
    w = fc.split_windows(raw['frames'], s['warmup_ms'], s['window_ms'], s['windows'])[0]
    t0, t1 = w[0]['t'], w[-1]['t']
    samples = [x for x in raw['samples'] if t0 <= x['t'] <= t1]
    if len(samples) != len(w):
        raise fc.EvidenceError(f'{raw["case"]}: {len(samples)} samples for {len(w)} window frames')
    pairs = list(zip(samples, samples[1:]))
    same_life = [(a, b) for a, b in pairs if a['deaths'] == b['deaths']]
    travel = sum(abs(b['sx'] - a['sx']) + abs(b['sy'] - a['sy']) for a, b in same_life)
    moving = sum(1 for a, b in same_life if a['sx'] != b['sx'] or a['sy'] != b['sy'])
    return {'window_frames': len(w), 'samples': len(samples), 'window_t': [t0, t1],
            'deaths_in_window': samples[-1]['deaths'] - samples[0]['deaths'],
            'deaths_total': len(raw['deaths']),
            'camera': {'travel_px': travel, 'moving_fraction': moving / len(pairs) if pairs else None,
                       'x_start': samples[0]['sx'], 'x_end': samples[-1]['sx'],
                       'x_range': [min(x['sx'] for x in samples), max(x['sx'] for x in samples)],
                       'y_range': [min(x['sy'] for x in samples), max(x['sy'] for x in samples)],
                       'resets_excluded': len(pairs) - len(same_life)},
            'counts': {k: stats([x[k] for x in samples]) for k in ('particles', 'pool', 'motes', 'track', 'obstacleTrack', 'elements', 'lights', 'score')}}


# -------------------------------------------------------------- capture --

def capture(args):
    from browser_test_support import start_browser_test
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    if args.feature is not None and args.feature not in FEATURES:
        raise SystemExit(f'unknown --feature {args.feature}; choose one of {list(FEATURES)}')
    profile = fc.PROFILES[args.profile]
    total = args.warmup_ms + args.windows * args.window_ms
    replay = replay_script(args.seed, args.profile, total + 1000, args.replay_style)
    settings = {'mode': args.mode, 'mode_name': MODE_NAMES[args.mode], 'population': args.population,
                'replay_style': args.replay_style, 'replay_box': REPLAY_STYLES[args.replay_style],
                'profile': args.profile, 'viewport': profile['viewport'],
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
           'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
           'chill_sha256': fc.sha_file(MODULE),
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
        page.evaluate(ab.FEATURE_INSTRUMENT, ab.feature_cfg(args.feature))
        page.evaluate(SAMPLER)
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
    raw['samples_sha256'] = fc.frames_sha256(raw['samples'])
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
        if len(raw['samples']) != len(raw['frames']):
            raise fc.EvidenceError(f'{len(raw["samples"])} samples for {len(raw["frames"])} active frames')
        raw['summary'] = fc.summarize(raw)
        raw['density'] = window_density(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw['summary'], raw['density'], raw['result'] = None, None, 'FAILED: ' + str(e)
    path = fc.raw_path(args.output, args.case)
    fc.dump(path, raw)
    c = raw['summary']['combined'] if raw['summary'] else None
    d = raw['density']
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'mode=%s backing=%s' % (args.mode, raw['dimensions']['canvas']),
          'feature=%s active=%s skipped=%s' % (args.feature, raw['featureActive'].get(args.feature) if args.feature else None,
                                               raw['skipped'].get(args.feature) if args.feature else None),
          'fps=%.2f mean_ms=%.2f p50=%.2f p95=%.2f max=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], 1000 / c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'],
              c['frame_ms']['max'], c['active_ms'], raw['summary']['deaths']) if c else '',
          'camera_travel=%.0f moving=%.2f deaths_in_window=%d particles_mean=%.1f track_mean=%.1f elements_mean=%.1f' % (
              d['camera']['travel_px'], d['camera']['moving_fraction'] or 0, d['deaths_in_window'],
              d['counts']['particles']['mean'], d['counts']['track']['mean'], d['counts']['elements']['mean']) if d else '', flush=True)
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
                                    'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
                                    'chill_sha256': fc.sha_file(MODULE),
                                    'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py')})
    print('PASS identity written', out / 'identity.json', 'HEAD', identity['current_commit'],
          'dirty_runtime=%r' % identity['current_dirty_runtime'], 'ceiling_fps=%.2f' % ceiling['average_fps'])
    return 0


def verified_root(out):
    identity = fc.load(out / 'identity.json')['identity']
    root = identity['trees']['current']
    if fc.tree_hashes(root) != identity['current_files_sha256']:
        raise fc.EvidenceError('current tree changed since prepare')
    return root


def capture_argv(root, out, mode, seed, case, population, args, feature=None, style='screening'):
    argv = [sys.executable, 'tools/y8_chill_ablation.py', 'capture', '--root', root, '--output', str(out),
            '--mode', mode, '--seed', str(seed), '--case', case, '--profile', PROFILE, '--windows', '1',
            '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms), '--population', population,
            '--replay-style', style]
    if feature:
        argv += ['--feature', feature]
    return argv


# -------------------------------------------------------------- segment --

def segment(args):
    """Seed screen: one Chill control capture per seed; pick the surviving, moving-camera segment."""
    out = Path(args.output)
    root = verified_root(out)
    seg = out / 'segment'
    started = utc()
    rows = []
    for style in args.styles:
        for seed in args.seeds:
            case = f'segment-control-{CHILL}-{PROFILE}-s{seed}' + ('' if style == 'screening' else f'-{style}')
            argv = capture_argv(root, seg, CHILL, seed, case, 'segment-screen', args, style=style)
            raw = ab.complete_case(ab.load_raws(seg), case)
            if raw is not None:  # already screened in an earlier segment pass: reuse, receipt is in commands.jsonl
                code, reused = 0, True
            else:
                code, reused = ab.receipt(out, f'segment/{CHILL}/s{seed}/{style}', argv), False
                raw = ab.complete_case(ab.load_raws(seg), case)
            row = {'seed': seed, 'style': style, 'case': case, 'exit_code': code, 'reused_earlier_capture': reused,
                   'raw': f'segment/raw/{case}.json' if raw else None}
            rows.append(row)
            if not raw:
                continue
            d = raw['density']
            row.update({'deaths_total': d['deaths_total'], 'deaths_in_window': d['deaths_in_window'],
                        'camera_travel_px': d['camera']['travel_px'], 'camera_moving_fraction': d['camera']['moving_fraction'],
                        'camera_x_range': d['camera']['x_range'], 'particles_mean': d['counts']['particles']['mean'],
                        'track_mean': d['counts']['track']['mean'], 'elements_mean': d['counts']['elements']['mean'],
                        'mean_ms': 1000 / raw['summary']['combined']['average_fps'],
                        'replay_sha256': raw['settings']['replay_sha256']})
    complete = [r for r in rows if r['raw']]
    rule = ('prefer no death in the whole capture (warmup + window), then no death inside the window, then the '
            'largest camera moving fraction, then the largest camera travel, then the highest mean particle count')
    ranked = sorted(complete, key=lambda r: (r['deaths_total'], r['deaths_in_window'], -(r['camera_moving_fraction'] or 0),
                                             -r['camera_travel_px'], -r['particles_mean']))
    chosen = ranked[0] if ranked else None
    fc.dump(out / 'segment.json', {
        'task': TASK, 'utc_start': started, 'utc_end': utc(), 'argv': sys.argv, 'mode': CHILL, 'mode_name': MODE_NAMES[CHILL],
        'protocol': f'{args.warmup_ms} ms warmup + one {args.window_ms} ms window, desktop 1280x720 DPR 1, CPU throttle 1, '
                    'control arm (no hook), sampler installed; one capture per seed',
        'selection_rule': rule, 'seeds_screened': list(args.seeds), 'styles_screened': list(args.styles),
        'replay_styles': REPLAY_STYLES, 'rows': rows, 'ranked': [[r['seed'], r['style']] for r in ranked],
        'chosen': chosen,
        'note': 'The chosen segment is documented by its seed, replay SHA256, per-frame camera samples and counts in the raw '
                'file; deaths in the screened capture do not guarantee survival in every arm (frame timing varies the physics '
                'step count between inputs), so every arm records its own deaths and camera travel.'})
    print('PASS segment written', out / 'segment.json', 'chosen seed', chosen and chosen['seed'], 'style', chosen and chosen['style'],
          'deaths', chosen and chosen['deaths_total'], 'moving_fraction', chosen and round(chosen['camera_moving_fraction'] or 0, 3),
          'travel', chosen and round(chosen['camera_travel_px']))
    return 0 if chosen else 1


# ------------------------------------------------------------------ run --

def chosen_segment(out):
    seg = fc.load(Path(out) / 'segment.json')
    if not seg['chosen']:
        raise fc.EvidenceError('segment.json has no chosen seed')
    return seg['chosen']['seed'], seg['chosen']['style']


def chosen_seed(out):
    return chosen_segment(out)[0]


def run(args):
    out = Path(args.output)
    root = verified_root(out)
    seed, style = chosen_segment(out)
    if args.seed is not None:
        seed = args.seed
    if args.replay_style is not None:
        style = args.replay_style
    features = list(FEATURES) if args.features == ['all'] else args.features
    for f in features:
        if f not in FEATURES:
            raise SystemExit(f'unknown feature {f}')
    failures = 0
    for feature in features:
        for rep, arm in enumerate(QUAD, 1):
            case = case_name(feature, arm, CHILL, seed, rep)
            argv = capture_argv(root, out, CHILL, seed, case, 'chill-ablation', args, feature if arm == 'candidate' else None, style)
            failures += ab.receipt(out, f'{feature}/{arm}/{CHILL}/{rep}', argv) != 0
    print(f'RUN DONE mode={CHILL} seed={seed} style={style} features={features} failed_captures={failures}', flush=True)
    return 1 if failures else 0


def reference(args):
    """Main density reference: TASK-272 protocol controls (seed 4, bad) with the sampler; counts only."""
    out = Path(args.output)
    root = verified_root(out)
    ref = out / 'reference'
    failures = 0
    for rep in range(1, args.repeats + 1):
        case = f'main-density-reference-control-{MAIN}-{PROFILE}-s{MAIN_SEED}-r{rep}'
        argv = capture_argv(root, ref, MAIN, MAIN_SEED, case, 'main-density-reference', args)
        failures += ab.receipt(out, f'reference/{MAIN}/{rep}', argv) != 0
    print(f'REFERENCE DONE mode={MAIN} seed={MAIN_SEED} repeats={args.repeats} failed_captures={failures}', flush=True)
    return 1 if failures else 0


# ---------------------------------------------------------------- prove --

def simulate(feature, mode, frames, seed, sampler=True, root=ROOT, style='screening'):
    from browser_test_support import start_browser_test
    cfg = {'dpr': 1, 'input': 'mouse', 'ablate': [], 'diagnostic': True,
           'replay': replay_script(seed, PROFILE, frames * 17, style), 'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
    with ExitStack() as stack:
        url, browser = start_browser_test(Path(root), stack.callback)
        ctx = fc.new_context(browser, PROFILE, seed, [])
        stack.callback(ctx.close)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html', wait_until='domcontentloaded')
        page.wait_for_function(fc.BOOTED, timeout=60000)
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate(ab.FEATURE_INSTRUMENT, ab.feature_cfg(feature))
        if sampler:
            page.evaluate(SAMPLER)
        result = page.evaluate(ab.SIMULATION, {'mode': mode, 'frames': frames})
        result['samples'] = page.evaluate(f'() => ({fc.MARKER}.samples || []).length')
        result['errors'] = errors
    result['particleDigestSha'] = fc.sha_bytes(json.dumps(result.pop('particleDigest')).encode())
    return result


def prove(args):
    out = Path(args.output)
    seed, style = chosen_segment(out)
    if args.seed is not None:
        seed = args.seed
    started = utc()
    reference_ = simulate(None, CHILL, args.frames, seed, sampler=False, style=style)
    with_sampler = simulate(None, CHILL, args.frames, seed, sampler=True, style=style)
    arms = {'reference-no-sampler': reference_, 'reference-sampler': with_sampler}
    checks = {'reference-sampler': {'differs': ab.equality(reference_, with_sampler), 'samples': with_sampler['samples']}}
    ok = not checks['reference-sampler']['differs'] and with_sampler['samples'] == args.frames and reference_['steps'] > 0
    print(f'{"PASS" if ok else "FAIL"} sampler {CHILL}: reference with/without sampler differs={checks["reference-sampler"]["differs"]} '
          f'samples={with_sampler["samples"]} physics_steps={reference_["steps"]} particle_updates={reference_["particleUpdates"]}', flush=True)
    for feature in FEATURES:
        r = simulate(feature, CHILL, args.frames, seed, sampler=True, style=style)
        arms[feature] = r
        diff = ab.equality(reference_, r)
        check = {'differs': diff, 'skipped_draw_calls': r['skipped'].get(feature, 0), 'ablated': r['ablated'],
                 'active': r['featureActive'].get(feature), 'errors': r['errors'], 'samples': r['samples'],
                 'pass': not diff and not r['errors'] and r['skipped'].get(feature, 0) > 0
                 and r['ablated'] == [FEATURES[feature]['removes']] and r['samples'] == args.frames}
        ok &= check['pass']
        checks[feature] = check
        print(f'{"PASS" if check["pass"] else "FAIL"} equality {CHILL} {feature}: differs={diff} '
              f'skipped_draw_calls={check["skipped_draw_calls"]} physics_steps={r["steps"]} particle_updates={r["particleUpdates"]} '
              f'particles={r["particleCount"]} track_points={r["trackPoints"]} score={r["score"]} screen={r["screen"]}', flush=True)
    report = {'task': TASK, 'utc_start': started, 'utc_end': utc(), 'argv': sys.argv, 'frames': args.frames, 'seed': seed, 'replay_style': style,
              'method': 'synthetic 60 Hz requestAnimationFrame timestamps, performance.now pinned, seeded Math.random, '
                        'fc.INSTRUMENT physics counter (--diagnostic, never paired with primary captures), sampler installed in '
                        'every arm except reference-no-sampler; fresh page per arm; equality over ' + ', '.join(ab.EQUALITY_KEYS),
              'equality_keys': list(ab.EQUALITY_KEYS), 'modes': {CHILL: {'arms': arms, 'checks': checks}}, 'pass': ok}
    fc.dump(out / 'state-equality.json', report)
    print(('PASS' if ok else 'FAIL'), 'state equality written', out / 'state-equality.json')
    return 0 if ok else 1


# --------------------------------------------------------------- report --

def mean_ms(raw):
    return 1000 / raw['summary']['combined']['average_fps']


def arm_record(raw, path):
    rec = ab.arm_record(raw, path)
    rec.update({'mode': raw['settings']['mode'], 'population': raw['settings']['population'], 'seed': raw['settings']['seed'],
                'samples_sha256': raw['samples_sha256'], 'density': raw['density'], 'death_times_active_ms': [d['activeMs'] for d in raw['deaths']]})
    return rec


def quads_from(raws, mode, seed, with_density):
    """Quads of the eight features for one population (own raw files); never mixes modes."""
    arms, quads, spread = {}, [], []
    for feature in FEATURES:
        cases = [case_name(feature, arm, mode, seed, rep) for rep, arm in enumerate(QUAD, 1)]
        paths = {c: next((p for p, r in raws.items() if r['case'] == c and r.get('result') == 'COMPLETE'), None) for c in cases}
        got = {c: ab.complete_case(raws, c) for c in cases}
        quad = {'feature': feature, 'stage': STAGES[feature], 'mode': mode, 'seed': seed, 'order': list(QUAD), 'cases': cases,
                'attempts': [p for p, r in raws.items() if r['case'] in cases],
                'failed_attempts': [p for p, r in raws.items() if r['case'] in cases and r.get('result') != 'COMPLETE']}
        if not all(got.values()):
            quad['result'] = 'MISSING: ' + ', '.join(c for c, r in got.items() if not r)
            quads.append(quad)
            continue
        for c, r in got.items():
            arms[c] = arm_record(r, paths[c]) if with_density else ab.arm_record(r, paths[c])
        ctl1, cand2, cand3, ctl4 = (got[c] for c in cases)
        try:
            quad['pairs'] = [dict(ab.pair_delta(ctl1, cand2), order='control-first'),
                             dict(ab.pair_delta(ctl4, cand3), order='candidate-first')]
            cc = ab.pair_delta(ctl1, ctl4)
        except fc.EvidenceError as e:
            quad['result'] = 'REJECTED: ' + str(e)
            quads.append(quad)
            continue
        quad['control_control'] = {'control': ctl1['case'], 'repeat': ctl4['case'], 'delta_mean_ms': cc['delta_mean_ms'],
                                   'delta_average_fps': cc['delta_average_fps'], 'delta_p50_ms': cc['delta_p50_ms']}
        spread.append(abs(cc['delta_mean_ms']))
        active = {c: r['featureActive'].get(feature) for c, r in got.items()}
        quad['feature_active'] = active
        quad['hook_installed'] = {c: r['ablated'] for c, r in got.items()}
        quad['skipped_draw_calls'] = {c: r['skipped'].get(feature, 0) for c, r in got.items()}
        quad['mean_ms'] = {c: mean_ms(r) for c, r in got.items()}
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
        if with_density:
            quad['density'] = {c: {'deaths_in_window': r['density']['deaths_in_window'],
                                   'camera_travel_px': r['density']['camera']['travel_px'],
                                   'camera_moving_fraction': r['density']['camera']['moving_fraction'],
                                   'particles_mean': r['density']['counts']['particles']['mean'],
                                   'track_mean': r['density']['counts']['track']['mean'],
                                   'obstacle_track_mean': r['density']['counts']['obstacleTrack']['mean'],
                                   'elements_mean': r['density']['counts']['elements']['mean'],
                                   'motes': r['density']['counts']['motes']['max']} for c, r in got.items()}
            quad['deaths_equal_across_arms'] = len({r['summary']['deaths'] for r in got.values()}) == 1
        quad['result'] = 'PAIRED' if all(v is True for k, v in quad['matched'].items()
                                        if k not in ('backing', 'deaths', 'excluded_frames', 'dispatched_inputs')) \
            and len(quad['matched']['backing']) == 1 else 'MISMATCH'
        quads.append(quad)
    return arms, quads, spread


def tiers(quads, spread):
    """Per-population tiers: the noise thresholds come from this population's own control-control spread."""
    threshold = max(spread) if spread else None
    typical = statistics.median(spread) if spread else None
    rows = {}
    for q in quads:
        if q['result'] != 'PAIRED':
            rows[q['feature']] = {'feature': q['feature'], 'stage': q['stage'], 'tier': 'MISSING', 'delta_mean_ms': [],
                                  'result': q['result']}
            continue
        deltas = [p['delta_mean_ms'] for p in q['pairs']]
        active = all(q['feature_active'].values())
        rows[q['feature']] = {'feature': q['feature'], 'stage': q['stage'], 'result': q['result'],
                              'tier': ab.classify(deltas, active, threshold, typical),
                              'delta_mean_ms': deltas, 'delta_average_fps': [p['delta_average_fps'] for p in q['pairs']],
                              'delta_p50_ms': [p['delta_p50_ms'] for p in q['pairs']],
                              'median_delta_mean_ms': statistics.median(deltas), 'saving_range_ms': [-max(deltas), -min(deltas)],
                              'control_control_ms': q['control_control']['delta_mean_ms'],
                              'control_mean_ms': [q['mean_ms'][q['cases'][0]], q['mean_ms'][q['cases'][3]]],
                              'candidate_mean_ms': [q['mean_ms'][q['cases'][1]], q['mean_ms'][q['cases'][2]]],
                              'control_fps': [p['control_fps'] for p in q['pairs']],
                              'candidate_fps': [p['candidate_fps'] for p in q['pairs']],
                              'feature_active': active, 'deaths': list(q['matched']['deaths'].values()),
                              'skipped_draw_calls': list(q['skipped_draw_calls'].values())}
        if 'density' in q:
            rows[q['feature']]['density_by_case'] = q['density']
    return {'noise_threshold_mean_ms': threshold, 'noise_typical_mean_ms': typical, 'spread': spread, 'rows': rows}


def dominant(tier_rows):
    """Largest median saving among REPEATED/CONSISTENT tiers; None is a valid negative finding."""
    eligible = [r for r in tier_rows.values() if r['tier'] in ('REPEATED_SAVING', 'CONSISTENT_SAVING')]
    eligible.sort(key=lambda r: ({'REPEATED_SAVING': 0, 'CONSISTENT_SAVING': 1}[r['tier']], r['median_delta_mean_ms']))
    ranked = sorted([r for r in tier_rows.values() if r.get('median_delta_mean_ms') is not None], key=lambda r: r['median_delta_mean_ms'])
    return {'dominant': eligible[0]['feature'] if eligible else None,
            'eligible_in_tier_order': [r['feature'] for r in eligible],
            'ranked_by_median_saving': [{'feature': r['feature'], 'tier': r['tier'], 'median_delta_mean_ms': r['median_delta_mean_ms']} for r in ranked],
            'negative_finding': not eligible}


def main_inputs():
    """TASK-272 Main (bad-mode) raw files, verified against the TASK-272 manifest seal; read-only."""
    manifest = fc.load(MAIN_SOURCE / 'manifest.json')
    raws, shas = {}, {}
    for name, digest in manifest['sha256'].items():
        if not (name.startswith('raw/') and f'-{MAIN}-' in name):
            continue
        if fc.sha_file(MAIN_SOURCE / name) != digest:
            raise fc.EvidenceError(f'TASK-272 input changed: {name}')
        raws[name] = fc.load(MAIN_SOURCE / name)
        shas[name] = digest
    classic = {}
    for name, digest in manifest['sha256'].items():
        if name.startswith('raw/') and f'-{CHILL}-' in name:
            if fc.sha_file(MAIN_SOURCE / name) != digest:
                raise fc.EvidenceError(f'TASK-272 input changed: {name}')
            classic[name] = fc.load(MAIN_SOURCE / name)
            shas[name] = digest
    return {'manifest': manifest, 'manifest_sha256': fc.sha_file(MAIN_SOURCE / 'manifest.json'), 'raws': raws,
            'classic_raws': classic, 'sha256': shas, 'source_revision': manifest['source_revision'],
            'decision_sha256': fc.sha_file(MAIN_SOURCE / 'decision.json')}


def main_case_name(feature, arm, mode, rep):
    return ab.case_name(feature, arm, mode, rep)


def main_quads(raws, mode):
    """TASK-272 quads of one mode, recomputed with ab.pair_delta from the raw files (seed 4 case names)."""
    renamed = {}
    for p, r in raws.items():
        renamed[p] = r
    arms, quads, spread = {}, [], []
    for feature in FEATURES:
        cases = [main_case_name(feature, arm, mode, rep) for rep, arm in enumerate(QUAD, 1)]
        got = {c: ab.complete_case(renamed, c) for c in cases}
        quad = {'feature': feature, 'stage': STAGES[feature], 'mode': mode, 'seed': MAIN_SEED, 'order': list(QUAD), 'cases': cases,
                'source': f'artifacts/TASK-272/raw ({MODE_NAMES[mode]})'}
        if not all(got.values()):
            quad['result'] = 'MISSING'
            quads.append(quad)
            continue
        ctl1, cand2, cand3, ctl4 = (got[c] for c in cases)
        quad['pairs'] = [dict(ab.pair_delta(ctl1, cand2), order='control-first'), dict(ab.pair_delta(ctl4, cand3), order='candidate-first')]
        cc = ab.pair_delta(ctl1, ctl4)
        quad['control_control'] = {'control': ctl1['case'], 'repeat': ctl4['case'], 'delta_mean_ms': cc['delta_mean_ms'],
                                   'delta_average_fps': cc['delta_average_fps'], 'delta_p50_ms': cc['delta_p50_ms']}
        spread.append(abs(cc['delta_mean_ms']))
        quad['feature_active'] = {c: r['featureActive'].get(feature) for c, r in got.items()}
        quad['skipped_draw_calls'] = {c: r['skipped'].get(feature, 0) for c, r in got.items()}
        quad['mean_ms'] = {c: mean_ms(r) for c, r in got.items()}
        quad['matched'] = {'deaths': {c: r['summary']['deaths'] for c, r in got.items()},
                           'backing': sorted({tuple(f['canvas']) for r in got.values() for f in r['frames']}),
                           'replay_sha256': sorted({r['settings']['replay_sha256'] for r in got.values()})}
        quad['result'] = 'PAIRED'
        quads.append(quad)
    return quads, spread


def build(out):
    out = Path(out)
    raws = ab.load_raws(out)
    seed, style = chosen_segment(out)
    segment_ = fc.load(out / 'segment.json')
    equality_report = fc.load(out / 'state-equality.json') if (out / 'state-equality.json').exists() else None
    ref_raws = ab.load_raws(out / 'reference') if (out / 'reference' / 'raw').exists() else {}
    seg_raws = ab.load_raws(out / 'segment') if (out / 'segment' / 'raw').exists() else {}
    chill_arms, chill_quads, chill_spread = quads_from(raws, CHILL, seed, True)
    chill = tiers(chill_quads, chill_spread)
    inputs = main_inputs()
    main_q, main_spread = main_quads(inputs['raws'], MAIN)
    main = tiers(main_q, main_spread)
    old_q, old_spread = main_quads(inputs['classic_raws'], CHILL)
    old_chill = tiers(old_q, old_spread)
    for q in chill_quads:
        if q['result'] == 'PAIRED':
            q['population'] = 'chill-ablation'
    refs = {p: {'case': r['case'], 'mode': r['settings']['mode'], 'seed': r['settings']['seed'], 'result': r['result'],
                'mean_ms': mean_ms(r) if r.get('summary') else None, 'deaths': len(r['deaths']),
                'feature_active': r['featureActive'], 'stage_flags': r['stageFlags'], 'density': r.get('density')}
            for p, r in ref_raws.items()}
    stage_flags = {}
    for a in chill_arms.values():
        for k, v in a['stage_flags'].items():
            stage_flags.setdefault(k, set()).add(v)
    stage_flags = {k: sorted(v, key=str) for k, v in stage_flags.items()}

    def density_of(rows, which):
        vals = {}
        for r in rows.values():
            if 'density_by_case' not in r:
                continue
            for c, d in r['density_by_case'].items():
                if which in c:
                    for k, v in d.items():
                        vals.setdefault(k, []).append(v)
        return {k: stats(v) for k, v in vals.items()}

    chill_controls_density = density_of(chill['rows'], '-control-')
    main_ref_density = {k: stats([r['density']['counts'][k]['mean'] for r in ref_raws.values() if r.get('density')])
                        for k in ('particles', 'pool', 'motes', 'track', 'obstacleTrack', 'elements', 'lights', 'score')}
    main_ref_camera = {'travel_px': stats([r['density']['camera']['travel_px'] for r in ref_raws.values() if r.get('density')]),
                       'moving_fraction': stats([r['density']['camera']['moving_fraction'] for r in ref_raws.values() if r.get('density')]),
                       'deaths_in_window': stats([r['density']['deaths_in_window'] for r in ref_raws.values() if r.get('density')])}
    ablation = {
        'task': TASK, 'mode': CHILL, 'mode_name': MODE_NAMES[CHILL], 'seed': seed, 'replay_style': style,
        'replay_box': REPLAY_STYLES[style],
        'protocol': f'TASK-271 screening: control, candidate, candidate, control per feature; seed {seed} and replay style {style} '
                    'chosen by segment.json; 5 s warmup + one 10 s window per capture; desktop 1280x720 DPR 1; CPU throttle 1; Chill only',
        'segment': {'path': 'segment.json', 'chosen': segment_['chosen'], 'selection_rule': segment_['selection_rule'],
                    'seeds_screened': segment_['seeds_screened'], 'styles_screened': segment_.get('styles_screened'),
                    'replay_box_css_px': {'x': [REPLAY_STYLES[style]['x'][0] * 1280, REPLAY_STYLES[style]['x'][1] * 1280],
                                          'y': [REPLAY_STYLES[style]['y'][0] * 720, REPLAY_STYLES[style]['y'][1] * 720]} if REPLAY_STYLES[style] else None,
                    'hud_menu_button_css_px': 'Chill HUD menu button (menu.constButton) centre (0.965 w, 0.058 h), side 0.072 h: '
                                              'x 1209-1261, y 16-68 at 1280x720; a click inside pauses the game. chill-ceiling '
                                              'throws stay at x <= 1178; chill-swing (x up to 1216) paused two screen captures '
                                              '(preserved FAILED timeouts in segment/raw).',
                    'why_not_screening_replay': 'the TASK-271 screening replay (throws at 40-85 % width, 15-60 % height) lets the '
                                                'Chill ninja fall to the lethal floor 7-9 s after every start: all six screened '
                                                'seeds died once inside the window with the camera moving in 6-34 % of frames '
                                                '(segment.json rows, style screening)'},
        'simulation_rate_note': 'gameoptions.js maxPhysicsStepsPerFrame = 2: a frame advances the simulation by at most 2 x 16.7 ms, '
                                'so a slower arm simulates less game time per 10 s active window than a faster one. Equal input on the '
                                'active clock therefore does not mean equal world distance: camera travel per arm is recorded and '
                                'is larger in the faster candidate arms. This holds for TASK-271/272 as well.',
        'features': {k: dict(v, stage=STAGES[k]) for k, v in FEATURES.items()},
        'stage_flags_observed': stage_flags, 'inactive_pipeline_stages': {k: v for k, v in stage_flags.items() if v == [False]},
        'arms': chill_arms, 'quads': chill_quads,
        'control_control_spread_mean_ms': chill_spread, 'noise_threshold_mean_ms': chill['noise_threshold_mean_ms'],
        'noise_typical_mean_ms': chill['noise_typical_mean_ms'], 'tiers': chill['rows'],
        'chill_control_density': chill_controls_density,
        'simulation_equality': {'path': 'state-equality.json', 'pass': equality_report['pass'],
                                'checks': {k: {'differs': c['differs'], 'skipped_draw_calls': c.get('skipped_draw_calls'), 'samples': c.get('samples')}
                                           for k, c in equality_report['modes'][CHILL]['checks'].items()}} if equality_report else None,
        'sign_convention': 'delta = candidate - control; negative delta_mean_ms and positive delta_average_fps mean the arm '
                           'without the feature drawing was faster',
        'sampler': 'read-only per active frame: screen.x/y, ninja x/y, particle/pool/mote counts, player and obstacle track '
                   'points, world elements, lightmap hasLights, score, deaths so far; camera travel per window excludes death resets',
        'limits': 'software headless Chromium under shared host load; paired deltas within a quad are the signal; '
                  'no 60 FPS, device or readiness claim; nothing is removed from the shipped game'}
    stages = []
    for feature in FEATURES:
        c, m, o = chill['rows'][feature], main['rows'][feature], old_chill['rows'][feature]
        both = c['tier'] not in ('MISSING',) and m['tier'] not in ('MISSING',)
        stages.append({
            'feature': feature, 'stage': STAGES[feature], 'removes': FEATURES[feature]['removes'],
            'chill': c, 'main': m, 'chill_task272_seed4_context': o,
            'same_sign_every_pair_both_modes': both and all(d < 0 for d in c['delta_mean_ms'] + m['delta_mean_ms']),
            'eligible_both_modes': both and c['tier'] in ('REPEATED_SAVING', 'CONSISTENT_SAVING') and m['tier'] in ('REPEATED_SAVING', 'CONSISTENT_SAVING'),
            'median_saving_ms': {'chill': -c.get('median_delta_mean_ms') if c.get('median_delta_mean_ms') is not None else None,
                                 'main': -m.get('median_delta_mean_ms') if m.get('median_delta_mean_ms') is not None else None},
            'uncertainty_ms': {'chill': {'control_control': c.get('control_control_ms'), 'population_threshold': chill['noise_threshold_mean_ms'],
                                         'population_typical': chill['noise_typical_mean_ms']},
                               'main': {'control_control': m.get('control_control_ms'), 'population_threshold': main['noise_threshold_mean_ms'],
                                        'population_typical': main['noise_typical_mean_ms']}}})
    comparison = {
        'task': TASK,
        'populations': {
            'chill': {'mode': CHILL, 'mode_name': MODE_NAMES[CHILL], 'seed': seed, 'replay_style': style, 'source': 'artifacts/TASK-273/raw',
                      'captures': len([a for a in chill_arms]), 'noise_threshold_mean_ms': chill['noise_threshold_mean_ms'],
                      'noise_typical_mean_ms': chill['noise_typical_mean_ms'], 'control_control_spread_ms': chill_spread,
                      'density_sampled': True, 'segment': segment_['chosen']},
            'main': {'mode': MAIN, 'mode_name': MODE_NAMES[MAIN], 'seed': MAIN_SEED, 'source': 'artifacts/TASK-272/raw (bad-mode arms only)',
                     'source_revision': inputs['source_revision'], 'task272_manifest_sha256': inputs['manifest_sha256'],
                     'captures': len(inputs['raws']), 'noise_threshold_mean_ms': main['noise_threshold_mean_ms'],
                     'noise_typical_mean_ms': main['noise_typical_mean_ms'], 'control_control_spread_ms': main_spread,
                     'density_sampled': False, 'density_reference': 'reference/raw (Main controls with the sampler, seed 4; counts only, never paired)',
                     'note': 'tiers recomputed from the Main pairs against the Main control-control spread only; TASK-272 '
                             'decision.json pooled both modes and is not reused'},
            'chill_task272_seed4_context': {'mode': CHILL, 'seed': MAIN_SEED, 'source': 'artifacts/TASK-272/raw (classic arms)',
                                            'captures': len(inputs['classic_raws']), 'noise_threshold_mean_ms': old_chill['noise_threshold_mean_ms'],
                                            'noise_typical_mean_ms': old_chill['noise_typical_mean_ms'],
                                            'note': 'every capture died 1-2 times (camera reset); shown for context, not pooled with the new Chill population'},
            'main_density_reference': {'mode': MAIN, 'seed': MAIN_SEED, 'source': 'artifacts/TASK-273/reference/raw', 'captures': refs,
                                       'counts_mean_over_captures': main_ref_density, 'camera': main_ref_camera}},
        'density': {'chill_controls': chill_controls_density, 'main_reference': {'counts': main_ref_density, 'camera': main_ref_camera},
                    'note': 'per-window means of per-frame samples; particles = live particle objects, track = player ribbon '
                            'points, obstacleTrack = hazard track points (Main only draws them), elements = world obstacle '
                            'elements across floors, motes = fixed ambient mote set, camera travel in logical px without death resets'},
        'stages': stages,
        'not_pooled': 'No frame interval, FPS, delta or threshold is averaged across modes or across populations; each '
                      'population keeps its own control-control spread and tiers.',
        'sign_convention': ablation['sign_convention'],
        'limits': ablation['limits']}
    chill_dom, main_dom = dominant(chill['rows']), dominant(main['rows'])
    shared = [f for f in FEATURES if chill['rows'][f]['tier'] in ('REPEATED_SAVING', 'CONSISTENT_SAVING')
              and main['rows'][f]['tier'] in ('REPEATED_SAVING', 'CONSISTENT_SAVING')]
    chill_only = [f for f in FEATURES if chill['rows'][f]['tier'] in ('REPEATED_SAVING', 'CONSISTENT_SAVING') and f not in shared]
    main_only = [f for f in FEATURES if main['rows'][f]['tier'] in ('REPEATED_SAVING', 'CONSISTENT_SAVING') and f not in shared]
    same = chill_dom['dominant'] is not None and chill_dom['dominant'] == main_dom['dominant']
    deaths_chill = sorted({d for r in chill['rows'].values() for d in r.get('deaths', [])})
    verdict = (f'Chill dominant cost: {chill_dom["dominant"]} (tier {chill["rows"][chill_dom["dominant"]]["tier"]}, median saving '
               f'{-chill["rows"][chill_dom["dominant"]]["median_delta_mean_ms"]:.1f} ms vs Chill noise max {chill["noise_threshold_mean_ms"]:.1f} ms)'
               if chill_dom['dominant'] else f'Chill: no feature saves beyond its own control-control spread (negative finding)')
    verdict += ('; Main dominant cost: %s (tier %s, median saving %.1f ms vs Main noise max %.1f ms)' % (
        main_dom['dominant'], main['rows'][main_dom['dominant']]['tier'], -main['rows'][main_dom['dominant']]['median_delta_mean_ms'],
        main['noise_threshold_mean_ms']) if main_dom['dominant'] else '; Main: no eligible feature')
    verdict += '; the same feature explains both modes' if same else '; different features dominate the two modes'
    decision = {
        'task': TASK,
        'chill': {'mode': CHILL, 'mode_name': MODE_NAMES[CHILL], 'seed': seed, 'replay_style': style, **chill_dom,
                  'tiers': {f: chill['rows'][f]['tier'] for f in FEATURES},
                  'median_delta_mean_ms': {f: chill['rows'][f].get('median_delta_mean_ms') for f in FEATURES},
                  'noise_threshold_mean_ms': chill['noise_threshold_mean_ms'], 'noise_typical_mean_ms': chill['noise_typical_mean_ms'],
                  'deaths_per_capture_observed': deaths_chill,
                  'camera': {'control_travel_px': chill_controls_density.get('camera_travel_px'),
                             'control_moving_fraction': chill_controls_density.get('camera_moving_fraction')}},
        'main': {'mode': MAIN, 'mode_name': MODE_NAMES[MAIN], 'seed': MAIN_SEED, 'source': 'TASK-272 bad-mode raw files', **main_dom,
                 'tiers': {f: main['rows'][f]['tier'] for f in FEATURES},
                 'median_delta_mean_ms': {f: main['rows'][f].get('median_delta_mean_ms') for f in FEATURES},
                 'noise_threshold_mean_ms': main['noise_threshold_mean_ms'], 'noise_typical_mean_ms': main['noise_typical_mean_ms']},
        'same_feature_explains_both_modes': same,
        'eligible_in_both_modes': shared, 'eligible_chill_only': chill_only, 'eligible_main_only': main_only,
        'verdict': verdict,
        'negative_findings_valid': True,
        'uncertainty': 'maxPhysicsStepsPerFrame = 2 caps simulated time per frame, so faster arms traverse more world in the same '
                       'active window (camera travel recorded per arm; see ablation.json simulation_rate_note). '
                       'One software-rendered host under unrelated load; two pairs per feature per mode; thresholds are the '
                       'population\'s own control-control spread (max and median). Chill arms record their own deaths and camera '
                       'travel; a quad whose arms died a different number of times compares equal input but not equal level '
                       'content (flagged in ablation.json quads.deaths_equal_across_arms). Main numbers are the TASK-272 seed-4 '
                       'population re-tiered against Main-only noise; Main density comes from separate reference captures and '
                       'is never paired. Savings are for the diagnostic clone only.',
        'not_claimed': ['60 FPS', 'release readiness', 'physical-device performance', 'production feature removal']}
    return {'ablation': ablation, 'comparison': comparison, 'decision': decision, 'raws': raws, 'ref_raws': ref_raws,
            'seg_raws': seg_raws, 'inputs': inputs}


def report(args):
    out = Path(args.output)
    built = build(out)
    identity_file = fc.load(out / 'identity.json')
    identity = identity_file['identity']
    commands = [json.loads(line) for line in (out / 'commands.jsonl').read_text().splitlines() if line.strip()]
    raws = built['raws']
    first = next(iter(raws.values()))
    fc.dump(out / 'ablation.json', built['ablation'])
    fc.dump(out / 'mode-comparison.json', built['comparison'])
    fc.dump(out / 'decision.json', built['decision'])
    eq = fc.load(out / 'state-equality.json') if (out / 'state-equality.json').exists() else None
    seg = fc.load(out / 'segment.json')
    evidence = sorted(['ablation.json', 'mode-comparison.json', 'decision.json', 'identity.json', 'commands.jsonl', 'segment.json']
                      + (['state-equality.json'] if eq else []) + list(raws)
                      + [f'reference/{p}' for p in built['ref_raws']] + [f'segment/{p}' for p in built['seg_raws']]
                      + ([MODULE_AT_CAPTURE] if (out / MODULE_AT_CAPTURE).exists() else []))
    all_raws = {**raws, **{f'reference/{p}': r for p, r in built['ref_raws'].items()}, **{f'segment/{p}': r for p, r in built['seg_raws'].items()}}
    manifest = {
        'task': TASK, 'utc_start': identity_file['utc_start'], 'utc_end': utc(), 'report_argv': sys.argv,
        'commands': [{'label': 'prepare', 'argv': identity_file['argv'], 'utc_start': identity_file['utc_start'],
                      'utc_end': identity_file['utc_end'], 'exit_code': 0}] + commands
                    + [{'label': 'segment', 'argv': seg['argv'], 'utc_start': seg['utc_start'], 'utc_end': seg['utc_end'],
                        'exit_code': 0 if seg['chosen'] else 1}]
                    + ([{'label': 'prove', 'argv': eq['argv'], 'utc_start': eq['utc_start'], 'utc_end': eq['utc_end'],
                         'exit_code': 0 if eq['pass'] else 1}] if eq else []),
        'source_revision': identity['current_commit'], 'source_revision_at_report': fc.git('rev-parse', 'HEAD'),
        'source_dirty_runtime': identity['current_dirty_runtime'],
        'source_dirty_at_report': fc.git('status', '--porcelain', '--untracked-files=no'),
        'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE), 'chill_sha256': fc.sha_file(MODULE),
        'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py'),
        'chill_sha256_at_capture': sorted({r['chill_sha256'] for r in all_raws.values()}),
        'module_at_capture': MODULE_AT_CAPTURE if (out / MODULE_AT_CAPTURE).exists() else None,
        'executed_hashes': {'harness_sha256_in_raws': sorted({r['harness_sha256'] for r in all_raws.values()}),
                            'ablation_sha256_in_raws': sorted({r['ablation_sha256'] for r in all_raws.values()}),
                            'chill_sha256_in_raws': sorted({r['chill_sha256'] for r in all_raws.values()}),
                            'note': 'captures were executed by chill_sha256_at_capture; report/audit by chill_sha256; when they '
                                    'differ the capture-time module is preserved byte-for-byte at module_at_capture'},
        'candidate_hashes': {'current_tar_sha256': identity['current_tar_sha256'], 'current_files_sha256': identity['current_files_sha256'],
                             'tree_sha256_sets_in_raws': sorted({fc.sha_bytes(json.dumps(r['tree']['files_sha256'], sort_keys=True).encode())
                                                                 for r in all_raws.values()})},
        'inputs_task272': {'manifest_sha256': built['inputs']['manifest_sha256'], 'decision_sha256': built['inputs']['decision_sha256'],
                           'source_revision': built['inputs']['source_revision'], 'raw_sha256': built['inputs']['sha256'],
                           'use': 'Main (bad-mode) raw files joined per feature in mode-comparison.json; classic raw files shown as '
                                  'seed-4 context; read-only, verified against the TASK-272 manifest seal'},
        'environment': {**first['environment'], 'ceiling': identity_file['environment_ceiling']},
        'fixed': {'profile': fc.PROFILES[PROFILE], 'backing_size_by_arm': {k: v['backing'] for k, v in built['ablation']['arms'].items()},
                  'mode': CHILL, 'seed': built['ablation']['seed'], 'replay_style': built['ablation']['replay_style'],
                  'replay_box': built['ablation']['replay_box'], 'warmup_ms': first['settings']['warmup_ms'],
                  'window_ms': first['settings']['window_ms'], 'windows_per_capture': first['settings']['windows'],
                  'cpu_throttle': first['settings']['cpu_throttle'],
                  'input': f'replay_script({built["ablation"]["seed"]}, {PROFILE}, total_ms, {built["ablation"]["replay_style"]}) scheduled on the active clock; '
                           f'replay_sha256 {sorted({r["settings"]["replay_sha256"] for r in raws.values()})}',
                  'state': 'per-frame menu/paused/offer/hidden/ad recorded; inactive frames excluded; deaths recorded via reStart '
                           'hook and never suppressed; feature active flags, stage flags, camera and density samples read in-page per arm'},
        'sdk_isolation': first['settings']['sdk_isolation'],
        'evidence_paths': evidence, 'sha256': {name: fc.sha_file(out / name) for name in evidence},
        'historical_attempts': [{'path': str(p.relative_to(out)), 'sha256': fc.sha_file(p), 'chill_sha256_at_capture': fc.load(p)['chill_sha256'],
                                 'case': fc.load(p)['case'], 'result': fc.load(p)['result'],
                                 'note': 'first segment pass, captured by an earlier uncommitted revision of this module whose bytes '
                                         'were not preserved; receipts are in commands.jsonl; re-screened under the capture-time module'}
                                for p in sorted((out / 'segment').glob('pass1-*/raw/*.json'))]
                               + [{'path': str(p.relative_to(out)), 'sha256': fc.sha_file(p), 'note': 'superseded segment.json of an earlier pass'}
                                  for p in sorted(out.glob('segment-pass*.json'))],
        'failed_attempts_preserved': sorted(set([c['label'] for c in commands if c['exit_code'] != 0]
                                                + [p for p, r in all_raws.items() if r.get('result') != 'COMPLETE'])),
        'note': 'A successful evidence audit is separate from the performance verdict; see decision.json.'}
    fc.dump(out / 'manifest.json', manifest)
    print('PASS report written', out / 'ablation.json', out / 'mode-comparison.json', out / 'decision.json', out / 'manifest.json')
    print('verdict:', built['decision']['verdict'])
    return 0


# ---------------------------------------------------------------- audit --

def check_raw(name, raw, m, identity):
    if raw['harness_sha256'] != m['harness_sha256'] or raw['ablation_sha256'] != m['ablation_sha256'] \
            or raw['chill_sha256'] not in m['chill_sha256_at_capture']:
        raise fc.EvidenceError(f'{name} captured by a different harness/module')
    if fc.frames_sha256(raw['frames']) != raw['frames_sha256'] or fc.frames_sha256(raw['samples']) != raw['samples_sha256']:
        raise fc.EvidenceError(f'{name} frames or samples altered')
    if raw['tree']['files_sha256'] != identity['current_files_sha256']:
        raise fc.EvidenceError(f'{name} ran on a tree other than the verified HEAD archive')
    if raw.get('result') != 'COMPLETE':
        print('INFO failed attempt preserved', name, raw.get('result'))
        return False
    if fc.summarize(raw) != raw['summary']:
        raise fc.EvidenceError(f'{name} summary does not match recomputation')
    if json.loads(json.dumps(window_density(raw))) != raw['density']:
        raise fc.EvidenceError(f'{name} density does not match recomputation')
    if {tuple(f['canvas']) for f in raw['frames']} != {tuple(raw['dimensions']['canvas'])}:
        raise fc.EvidenceError(f'{name} backing size varies')
    if raw['dimensions']['platform'] not in ('disabled', 'absent') or raw['dimensions']['version'] != raw['settings']['mode']:
        raise fc.EvidenceError(f'{name} SDK not isolated or wrong mode')
    if raw['errors'] or raw['error'] or raw['settings']['diagnostic']:
        raise fc.EvidenceError(f'{name} has page errors or is diagnostic')
    if len(raw['samples']) != len(raw['frames']) or any(s['t'] != f['t'] for s, f in zip(raw['samples'], raw['frames'])):
        raise fc.EvidenceError(f'{name} samples do not cover every active frame')
    if any(s.get(k) is None for s in raw['samples'] for k in SAMPLE_KEYS):
        raise fc.EvidenceError(f'{name} sampler read failed for some key')
    feature = raw['settings']['feature']
    expected = [FEATURES[feature]['removes']] if feature else []
    if raw['ablated'] != expected or (feature and not raw['skipped'].get(feature)) or (not feature and raw['skipped']):
        raise fc.EvidenceError(f'{name} hook mismatch {raw["ablated"]} skipped {raw["skipped"]}')
    for w in raw['summary']['windows']:
        if w['active_ms'] < raw['settings']['window_ms']:
            raise fc.EvidenceError(f'{name} short window')
    c, d = raw['summary']['combined'], raw['density']
    print(f'PASS recomputed {raw["case"]}: mode={raw["settings"]["mode"]} population={raw["settings"]["population"]} '
          f'replay={raw["settings"].get("replay_style")} seed={raw["settings"]["seed"]} feature={feature} '
          f'active={raw["featureActive"].get(feature) if feature else "-"} skipped={raw["skipped"]} intervals={c["intervals"]} '
          f'active_ms={c["active_ms"]:.1f} fps={c["average_fps"]:.2f} mean_ms={1000 / c["average_fps"]:.2f} p50={c["frame_ms"]["p50"]:.2f} '
          f'p95={c["frame_ms"]["p95"]:.2f} max={c["frame_ms"]["max"]:.2f} backing={raw["dimensions"]["canvas"]} deaths={raw["summary"]["deaths"]} '
          f'deaths_in_window={d["deaths_in_window"]} camera_travel={d["camera"]["travel_px"]:.0f} moving={d["camera"]["moving_fraction"]:.2f} '
          f'particles_mean={d["counts"]["particles"]["mean"]:.1f} track_mean={d["counts"]["track"]["mean"]:.1f} '
          f'elements_mean={d["counts"]["elements"]["mean"]:.1f} stage_flags={json.dumps(raw["stageFlags"], sort_keys=True)}')
    return True


def audit(args):
    out = Path(args.output)
    m = fc.load(out / 'manifest.json')
    for name, digest in m['sha256'].items():
        if fc.sha_file(out / name) != digest:
            raise fc.EvidenceError(f'SHA256 mismatch {name}')
    print(f'PASS manifest seal: {len(m["sha256"])} evidence files match SHA256')
    if fc.sha_file(fc.HARNESS) != m['harness_sha256'] or fc.sha_file(ab.MODULE) != m['ablation_sha256'] or fc.sha_file(MODULE) != m['chill_sha256']:
        raise fc.EvidenceError('harness, ablation or chill module changed since report')
    print('PASS harness/ablation/chill module sha256 unchanged since report', m['harness_sha256'][:12], m['ablation_sha256'][:12], m['chill_sha256'][:12])
    if len(m['chill_sha256_at_capture']) != 1:
        raise fc.EvidenceError('captures executed by more than one module version')
    if m['chill_sha256_at_capture'] != [m['chill_sha256']]:
        if not m['module_at_capture'] or fc.sha_file(out / m['module_at_capture']) != m['chill_sha256_at_capture'][0]:
            raise fc.EvidenceError('capture-time module not preserved')
        print('INFO captures executed by module', m['chill_sha256_at_capture'][0], 'preserved at', m['module_at_capture'])
    for c in m['commands']:
        if not (c['argv'] and c['utc_start'] <= c['utc_end'] and isinstance(c['exit_code'], int)):
            raise fc.EvidenceError('command receipt incomplete: ' + json.dumps(c)[:200])
    print(f'PASS {len(m["commands"])} commands with argv/UTC start-end/exit codes; failed attempts preserved:', m['failed_attempts_preserved'])
    for name, digest in m['inputs_task272']['raw_sha256'].items():
        if fc.sha_file(MAIN_SOURCE / name) != digest:
            raise fc.EvidenceError(f'TASK-272 input changed since report: {name}')
    if fc.sha_file(MAIN_SOURCE / 'manifest.json') != m['inputs_task272']['manifest_sha256']:
        raise fc.EvidenceError('TASK-272 manifest changed since report')
    print(f'PASS TASK-272 inputs unchanged: manifest + {len(m["inputs_task272"]["raw_sha256"])} raw files match the recorded SHA256')
    identity = fc.load(out / 'identity.json')['identity']
    raws = ab.load_raws(out)
    extra = {**{f'reference/{p}': r for p, r in ab.load_raws(out / 'reference').items()},
             **{f'segment/{p}': r for p, r in ab.load_raws(out / 'segment').items()}}
    complete = 0
    for name, raw in {**raws, **extra}.items():
        if name not in m['sha256']:
            raise fc.EvidenceError(f'{name} not sealed in manifest')
        complete += check_raw(name, raw, m, identity)
    built = build(out)
    for name, file in (('ablation', 'ablation.json'), ('comparison', 'mode-comparison.json'), ('decision', 'decision.json')):
        if json.loads(json.dumps(built[name], sort_keys=True)) != fc.load(out / file):
            raise fc.EvidenceError(f'{file} differs from recomputation')
    print(f'PASS ablation.json, mode-comparison.json and decision.json match recomputation from {complete} complete raw files')
    ab_ = built['ablation']
    paired = [q for q in ab_['quads'] if q['result'] == 'PAIRED']
    for q in ab_['quads']:
        if q['result'] == 'PAIRED':
            dens = q['density']
            print(f'PASS quad {q["feature"]}/{q["mode"]}/s{q["seed"]}: PAIRED active={sorted(set(map(str, q["feature_active"].values())))} '
                  f'backing={q["matched"]["backing"]} skipped={list(q["skipped_draw_calls"].values())} deaths={list(q["matched"]["deaths"].values())} '
                  f'deaths_equal={q["deaths_equal_across_arms"]} mean_ms={[round(v, 1) for v in q["mean_ms"].values()]} '
                  f'dMean_ms={[round(p["delta_mean_ms"], 2) for p in q["pairs"]]} dFPS={[round(p["delta_average_fps"], 2) for p in q["pairs"]]} '
                  f'control-control={q["control_control"]["delta_mean_ms"]:+.2f}ms '
                  f'camera_travel={[round(d["camera_travel_px"]) for d in dens.values()]} moving={[round(d["camera_moving_fraction"], 2) for d in dens.values()]} '
                  f'particles={[round(d["particles_mean"], 1) for d in dens.values()]} track={[round(d["track_mean"], 1) for d in dens.values()]} '
                  f'elements={[round(d["elements_mean"], 1) for d in dens.values()]}')
        else:
            print(f'INFO quad {q["feature"]}/{q["mode"]}: {q["result"]}')
    print(f'{"PASS" if len(paired) == len(FEATURES) else "FAIL"} {len(paired)} of {len(FEATURES)} Chill quads paired; '
          f'inactive pipeline stages {ab_["inactive_pipeline_stages"]}; Chill noise threshold {ab_["noise_threshold_mean_ms"]} '
          f'typical {ab_["noise_typical_mean_ms"]}')
    if len(paired) != len(FEATURES):
        raise fc.EvidenceError('incomplete quads')
    comp = fc.load(out / 'mode-comparison.json')
    # Join check against the TASK-272 raw files, recomputed independently of mode-comparison.json.
    inputs = main_inputs()
    for row in comp['stages']:
        f = row['feature']
        cases = [ab.case_name(f, arm, MAIN, rep) for rep, arm in enumerate(QUAD, 1)]
        got = [ab.complete_case(inputs['raws'], c) for c in cases]
        recomputed = [ab.pair_delta(got[0], got[1])['delta_mean_ms'], ab.pair_delta(got[3], got[2])['delta_mean_ms']]
        cc = ab.pair_delta(got[0], got[3])['delta_mean_ms']
        if any(abs(a - b) > 1e-9 for a, b in zip(recomputed, row['main']['delta_mean_ms'])) or abs(cc - row['main']['control_control_ms']) > 1e-9:
            raise fc.EvidenceError(f'mode-comparison main deltas differ from TASK-272 raw recomputation for {f}')
        if row['chill']['tier'] == 'MISSING' or row['main']['tier'] == 'MISSING':
            raise fc.EvidenceError(f'incomplete join for {f}')
        print(f'PASS join {f:18} stage={row["stage"]:55} chill dMean={[round(x, 1) for x in row["chill"]["delta_mean_ms"]]} tier={row["chill"]["tier"]:18} '
              f'cc={row["chill"]["control_control_ms"]:+.1f} | main(TASK-272 raw) dMean={[round(x, 1) for x in recomputed]} tier={row["main"]["tier"]:18} cc={cc:+.1f} '
              f'| same_sign_all_pairs={row["same_sign_every_pair_both_modes"]}')
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    # Structural check: no key that merges modes/populations (prose may say "not pooled").
    pooled_keys = [k for k in keys(comp) if any(w in k.lower() for w in ('pooled', 'all_modes', 'both_modes_delta', 'combined_fps', 'overall_fps'))
                   and k != 'not_pooled']
    if pooled_keys:
        raise fc.EvidenceError(f'mode-comparison contains pooled figures: {pooled_keys}')
    for row in comp['stages']:
        for mode_key in ('chill', 'main'):
            if not isinstance(row[mode_key].get('delta_mean_ms'), list) or 'control_control_ms' not in row[mode_key]:
                raise fc.EvidenceError(f'stage {row["feature"]} lacks per-mode deltas/uncertainty for {mode_key}')
    pops = comp['populations']
    if pops['chill']['noise_threshold_mean_ms'] == pops['main']['noise_threshold_mean_ms'] and pops['chill']['control_control_spread_ms'] == pops['main']['control_control_spread_ms']:
        raise fc.EvidenceError('populations share one spread')
    print(f'PASS populations separate: chill seed {pops["chill"]["seed"]} ({pops["chill"]["captures"]} captures, noise max {pops["chill"]["noise_threshold_mean_ms"]:.2f} ms) '
          f'vs main seed {pops["main"]["seed"]} ({pops["main"]["captures"]} TASK-272 captures, noise max {pops["main"]["noise_threshold_mean_ms"]:.2f} ms); '
          f'no pooled FPS or delta')
    dens = comp['density']
    print('PASS density visible: chill controls particles_mean=%s track_mean=%s elements_mean=%s camera_travel=%s moving=%s | main reference '
          'particles=%s track=%s obstacleTrack=%s elements=%s camera_travel=%s moving=%s' % (
              round(dens['chill_controls']['particles_mean']['mean'], 1), round(dens['chill_controls']['track_mean']['mean'], 1),
              round(dens['chill_controls']['elements_mean']['mean'], 1), round(dens['chill_controls']['camera_travel_px']['mean']),
              round(dens['chill_controls']['camera_moving_fraction']['mean'], 2),
              dens['main_reference']['counts']['particles'] and round(dens['main_reference']['counts']['particles']['mean'], 1),
              dens['main_reference']['counts']['track'] and round(dens['main_reference']['counts']['track']['mean'], 1),
              dens['main_reference']['counts']['obstacleTrack'] and round(dens['main_reference']['counts']['obstacleTrack']['mean'], 1),
              dens['main_reference']['counts']['elements'] and round(dens['main_reference']['counts']['elements']['mean'], 1),
              dens['main_reference']['camera']['travel_px'] and round(dens['main_reference']['camera']['travel_px']['mean']),
              dens['main_reference']['camera']['moving_fraction'] and round(dens['main_reference']['camera']['moving_fraction']['mean'], 2)))
    eq = fc.load(out / 'state-equality.json')
    if not eq['pass'] or any(c['differs'] for c in eq['modes'][CHILL]['checks'].values()):
        raise fc.EvidenceError('state equality proof failed')
    print(f'PASS state equality ({CHILL}, sampler installed): reference with/without sampler and {len(FEATURES)} feature arms identical over {eq["equality_keys"]}')
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    runtime = [n for n in tracked if n.endswith(fc.RUNTIME_SUFFIXES) and not n.startswith('tools/')]
    for name in runtime:
        text = (ROOT / name).read_text(errors='replace')
        if fc.MARKER in text or 'skip("' in text or 'FC.samples' in text:
            raise fc.EvidenceError(f'diagnostic hook in shipped runtime: {name}')
    print(f'PASS no diagnostic hook marker in {len(runtime)} git-tracked shipped runtime files')
    d = built['decision']
    env = m['environment']
    print('PASS environment: os=%s browser=%s playwright=%s gpu=%s ceiling_fps=%.2f' % (
        env['os'], env['browser'], env['playwright'], env['gpu']['auxAttributes'].get('glRenderer'), env['ceiling']['average_fps']))
    print(f'PASS evidence audit complete; performance verdict is separate: chill dominant={d["chill"]["dominant"]} '
          f'main dominant={d["main"]["dominant"]} same_feature_explains_both_modes={d["same_feature_explains_both_modes"]} '
          f'eligible_both={d["eligible_in_both_modes"]} chill_only={d["eligible_chill_only"]} main_only={d["eligible_main_only"]}')
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
    c.add_argument('--population', default='chill-ablation')
    c.add_argument('--replay-style', default='screening', choices=sorted(REPLAY_STYLES))
    c.add_argument('--profile', default=PROFILE, choices=sorted(fc.PROFILES))
    c.add_argument('--cpu-throttle', type=int, default=1)
    c.add_argument('--warmup-ms', type=int, default=5000)
    c.add_argument('--window-ms', type=int, default=10000)
    c.add_argument('--windows', type=int, default=1)
    c.add_argument('--feature', default=None, help='disable drawing of this feature (diagnostic only); omit for control')
    c.add_argument('--timeout-ms', type=int, default=240000)
    c.set_defaults(func=capture)
    s = sub.add_parser('segment')
    s.add_argument('--output', required=True)
    s.add_argument('--seeds', nargs='+', type=int, default=list(DEFAULT_SCREEN_SEEDS))
    s.add_argument('--styles', nargs='+', default=['screening'], choices=sorted(REPLAY_STYLES))
    s.add_argument('--warmup-ms', type=int, default=5000)
    s.add_argument('--window-ms', type=int, default=10000)
    s.set_defaults(func=segment)
    r = sub.add_parser('run')
    r.add_argument('--output', required=True)
    r.add_argument('--seed', type=int, default=None, help='default: segment.json chosen seed')
    r.add_argument('--replay-style', default=None, choices=sorted(REPLAY_STYLES), help='default: segment.json chosen style')
    r.add_argument('--features', nargs='+', default=['all'])
    r.add_argument('--warmup-ms', type=int, default=5000)
    r.add_argument('--window-ms', type=int, default=10000)
    r.set_defaults(func=run)
    f = sub.add_parser('reference')
    f.add_argument('--output', required=True)
    f.add_argument('--repeats', type=int, default=2)
    f.add_argument('--warmup-ms', type=int, default=5000)
    f.add_argument('--window-ms', type=int, default=10000)
    f.set_defaults(func=reference)
    v = sub.add_parser('prove')
    v.add_argument('--output', required=True)
    v.add_argument('--seed', type=int, default=None)
    v.add_argument('--frames', type=int, default=240)
    v.set_defaults(func=prove)
    e = sub.add_parser('report')
    e.add_argument('--output', required=True)
    e.set_defaults(func=report)
    a = sub.add_parser('audit')
    a.add_argument('--output', required=True)
    a.set_defaults(func=audit)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
