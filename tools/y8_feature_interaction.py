"""Feature interaction measurement on the TASK-271/272/273 stack (TASK-274).

Selects the stages with the largest repeatable frame-time savings across
TASK-272 (Main, seed 4, screening replay) and TASK-273 (Chill, chosen segment),
ranked by the sum over both modes of the positive median milliseconds saved per
frame (tie-break: stage name), at most three. Every on/off combination of the
selected stages is then measured in both modes: all-on is the control, one
10-second window after a 5-second warmup per capture, two repetitions, the
second in reversed order. Measured combined savings are compared with the sums
of the single-stage savings measured in the same repetition; discrepancies and
inconsistent repeats are reported. All timing is the requestAnimationFrame
interval of paired arms: no JS function timing and no raster attribution.

Actions
  select   rank the stages from the sealed TASK-272/273 reports; selection.json
           (a quantitative negative result when nothing is eligible)
  prepare  verified HEAD tree, environment ceiling; identity.json
  capture  one browser session with several TASK-272 draw hooks installed
           (--off <stage>, repeatable) plus the TASK-273 read-only sampler
  run      both repetitions of every combination for --modes; commands.jsonl
  prove    deterministic simulation: every combination leaves the simulation
           state identical to the all-on reference; state-equality.json
  report   combinations.json, interaction.json, decision.json, manifest.json
  audit    re-derive the selection from the inputs, enumerate the expected
           combinations, recompute every figure from the raw files, verify
           seals, hooks, equal-state and settings checks

Nothing here certifies 60 FPS, physical devices or release readiness; hooks
live in the diagnostic clone page only (marker __featureCost).
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
import y8_chill_ablation as ch  # noqa: E402

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
TASK = 'TASK-274'
PROFILE = 'desktop'
MAIN, CHILL = ch.MAIN, ch.CHILL
MODES = (MAIN, CHILL)
MODE_KEY = {MAIN: 'main', CHILL: 'chill'}  # keys of the per-mode blocks in TASK-273 decision.json
FEATURES = ab.FEATURES
STAGES = ch.STAGES
ELIGIBLE_TIERS = ('REPEATED_SAVING', 'CONSISTENT_SAVING')
MAX_STAGES = 3
REPS = ('r1', 'r2')
INPUTS = {
    'task272_ranking': 'artifacts/TASK-272/ranking.json',
    'task272_manifest': 'artifacts/TASK-272/manifest.json',
    'task273_decision': 'artifacts/TASK-273/decision.json',
    'task273_segment': 'artifacts/TASK-273/segment.json',
    'task273_manifest': 'artifacts/TASK-273/manifest.json',
    'task271_controls': 'artifacts/TASK-271/controls.json',
}
SELECTION_RULE = ('eligible = tier REPEATED_SAVING or CONSISTENT_SAVING in at least one mode of the TASK-273 per-mode '
                  'tiers (Chill from the TASK-273 captures, Main from the sealed TASK-272 bad-mode raw files re-tiered '
                  'against Main-only noise); score = sum over both modes of max(0, -median_delta_mean_ms); rank by '
                  'score descending, tie-break by stage name ascending; take the first three eligible stages, or all '
                  'eligible stages when fewer than three are eligible')
MODULE_AT_CAPTURE = 'module-at-capture/y8_feature_interaction.py'
ATTRIBUTION = {
    'basis': 'mean active requestAnimationFrame interval of one 10 s window per capture (1000 / average_fps), paired '
             'against the all-on control captured in the same repetition and mode',
    'js_function_timing_used': False,
    'raster_attribution': 'not attempted: the rAF interval of this software-rendered headless Chromium includes JS, '
                          'raster and composite work together; no stage is timed individually and no asynchronous '
                          'raster cost is attributed from JS function timing',
}

# Installed after fc.INSTRUMENT (FC exists, gameLoop wrapped) and before ch.SAMPLER / startGame.
# Several TASK-272 hooks are installed at once; each counts its skipped draw calls by name.
COMBO_INSTRUMENT = '''(cfg) => {
    const FC = window.__featureCost
    FC.featureActive = %s
    FC.stageFlags = %s
    FC.skipped = {}
    const skip = (name, replacement) => function() {
        FC.skipped[name] = (FC.skipped[name] || 0) + 1
        if (replacement) return replacement.apply(this, arguments)
    }
    FC.featuresOff = cfg.off.slice()
    for (const name of cfg.off) {
        const spec = cfg.features[name]
        eval(spec.install)
        FC.ablated.push(spec.removes)
    }
}''' % (ab.js_object({k: v['active'] for k, v in FEATURES.items()}), ab.js_object(ab.STAGE_FLAGS))


def utc():
    return fc.utc()


def combo_cfg(off):
    return {'off': list(off), 'features': {k: {'install': v['install'], 'removes': v['removes']} for k, v in FEATURES.items()}}


# ------------------------------------------------------------- selection --

def rank_stages(decision, ranking=None):
    """Rank the eight stages from the TASK-273 per-mode tiers/medians (TASK-272 classification as context)."""
    rows = []
    r272 = {r['feature']: r for r in (ranking or {}).get('rows', [])}
    for f in FEATURES:
        tiers = {m: decision[MODE_KEY[m]]['tiers'][f] for m in MODES}
        medians = {m: decision[MODE_KEY[m]]['median_delta_mean_ms'][f] for m in MODES}
        saving = {m: (max(0.0, -medians[m]) if medians[m] is not None else 0.0) for m in MODES}
        repeatable = {m: tiers[m] in ELIGIBLE_TIERS for m in MODES}
        rows.append({'feature': f, 'stage': STAGES[f], 'tier_by_mode': tiers, 'median_delta_mean_ms_by_mode': medians,
                     'positive_median_saving_ms_by_mode': saving,
                     'summed_positive_median_saving_ms': sum(saving.values()),
                     'summed_over_repeatable_modes_ms': sum(v for m, v in saving.items() if repeatable[m]),
                     'repeatable_by_mode': repeatable, 'eligible': any(repeatable.values()),
                     'task272_classification': r272.get(f, {}).get('classification'),
                     'task272_median_delta_mean_ms': r272.get(f, {}).get('median_delta_mean_ms')})
    rows.sort(key=lambda r: (-r['summed_positive_median_saving_ms'], r['feature']))
    eligible = [r for r in rows if r['eligible']]
    selected = [r['feature'] for r in eligible[:MAX_STAGES]]
    alt = [r['feature'] for r in sorted(eligible, key=lambda r: (-r['summed_over_repeatable_modes_ms'], r['feature']))[:MAX_STAGES]]
    ties = [(a['feature'], b['feature']) for a, b in zip(eligible, eligible[1:])
            if a['summed_positive_median_saving_ms'] == b['summed_positive_median_saving_ms']]
    if not eligible:
        why = 'no stage has a repeatable (REPEATED_SAVING / CONSISTENT_SAVING) tier in either mode: negative selection result'
    elif len(selected) < MAX_STAGES:
        why = f'only {len(selected)} stage(s) eligible; all eligible stages are used'
    else:
        why = f'{len(eligible)} eligible stages; the three with the largest summed positive median saving are taken'
    return {'rule': SELECTION_RULE, 'rows': rows, 'eligible': [r['feature'] for r in eligible], 'selected': selected,
            'selected_count': len(selected), 'fewer_than_three': len(selected) < MAX_STAGES, 'why': why,
            'ties_resolved_by_stage_name': ties,
            'alternative_sum_over_repeatable_modes_only': alt, 'alternative_agrees': alt == selected}


def combinations(stages):
    """Every on/off combination of the selected stages; all-on first, then by number of stages off."""
    n = len(stages)
    out = []
    for mask in sorted(range(1 << n), key=lambda m: (bin(m).count('1'), m)):
        off = [s for i, s in enumerate(stages) if mask >> i & 1]
        out.append({'id': 'c' + ''.join('1' if mask >> i & 1 else '0' for i in range(n)), 'off': off,
                    'on': [s for s in stages if s not in off], 'is_control': not off,
                    'label': 'all-on (control)' if not off else 'off: ' + ' + '.join(off)})
    return out


def orders(combos):
    ids = [c['id'] for c in combos]
    return {'r1': ids, 'r2': ids[::-1]}


def case_name(cid, mode, seed, rep):
    return f'combo-{cid}-{mode}-{PROFILE}-s{seed}-{rep}'


def select(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    inputs = {k: {'path': p, 'sha256': fc.sha_file(ROOT / p)} for k, p in INPUTS.items()}
    m272, m273 = fc.load(ROOT / INPUTS['task272_manifest']), fc.load(ROOT / INPUTS['task273_manifest'])
    if m272['sha256']['ranking.json'] != inputs['task272_ranking']['sha256']:
        raise fc.EvidenceError('TASK-272 ranking.json does not match its manifest seal')
    for name in ('decision.json', 'segment.json'):
        if m273['sha256'][name] != inputs['task273_' + name.split('.')[0]]['sha256']:
            raise fc.EvidenceError(f'TASK-273 {name} does not match its manifest seal')
    decision, ranking = fc.load(ROOT / INPUTS['task273_decision']), fc.load(ROOT / INPUTS['task272_ranking'])
    seg = fc.load(ROOT / INPUTS['task273_segment'])
    ranked = rank_stages(decision, ranking)
    combos = combinations(ranked['selected'])
    modes = {MAIN: {'name': ch.MODE_NAMES[MAIN], 'seed': ch.MAIN_SEED, 'replay_style': 'screening',
                    'replay_box': None, 'source': 'TASK-272 protocol: seed 4, TASK-271 screening replay'},
             CHILL: {'name': ch.MODE_NAMES[CHILL], 'seed': seg['chosen']['seed'], 'replay_style': seg['chosen']['style'],
                     'replay_box': ch.REPLAY_STYLES[seg['chosen']['style']],
                     'source': 'TASK-273 segment.json chosen segment (no death, moving camera)'}}
    prior_noise = {m: {'max': decision[MODE_KEY[m]]['noise_threshold_mean_ms'], 'typical': decision[MODE_KEY[m]]['noise_typical_mean_ms']}
                   for m in MODES}
    sel = {'task': TASK, 'utc': utc(), 'argv': sys.argv, 'inputs': inputs, **ranked, 'modes': modes,
           'prior_noise_ms': prior_noise, 'combinations': combos, 'order': orders(combos),
           'expected_captures': len(combos) * len(REPS) * len(MODES),
           'protocol': f'{len(combos)} combinations x 2 repetitions x {len(MODES)} modes; one capture per combination and '
                       'repetition with a 5 s warmup and one 10 s measured window (two 10 s windows per combination); '
                       'repetition 2 runs the combinations in reversed order; all-on is the control; desktop 1280x720 DPR 1; '
                       'CPU throttle 1; TASK-272 draw-only hooks; TASK-273 read-only sampler',
           'negative_result': None if combos[1:] else
           {'quantitative': ranked['rows'], 'statement': 'no eligible stage: no combination captures are run'}}
    fc.dump(out / 'selection.json', sel)
    for r in ranked['rows']:
        print(f'INFO rank {r["feature"]:18} score={r["summed_positive_median_saving_ms"]:7.2f} ms '
              f'chill={r["positive_median_saving_ms_by_mode"][CHILL]:6.2f} ({r["tier_by_mode"][CHILL]}) '
              f'main={r["positive_median_saving_ms_by_mode"][MAIN]:6.2f} ({r["tier_by_mode"][MAIN]}) eligible={r["eligible"]}')
    print('PASS selection written', out / 'selection.json', 'selected', ranked['selected'], 'why:', ranked['why'],
          'combinations', [c['id'] for c in combos], 'expected captures', sel['expected_captures'])
    return 0


# -------------------------------------------------------------- capture --

def capture(args):
    from browser_test_support import start_browser_test
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    off = list(args.off)
    for f in off:
        if f not in FEATURES:
            raise SystemExit(f'unknown --off {f}; choose from {list(FEATURES)}')
    if len(set(off)) != len(off):
        raise SystemExit('duplicate --off')
    profile = fc.PROFILES[args.profile]
    total = args.warmup_ms + args.windows * args.window_ms
    replay = ch.replay_script(args.seed, args.profile, total + 1000, args.replay_style)
    settings = {'mode': args.mode, 'mode_name': ch.MODE_NAMES[args.mode], 'population': 'interaction',
                'replay_style': args.replay_style, 'replay_box': ch.REPLAY_STYLES[args.replay_style],
                'profile': args.profile, 'viewport': profile['viewport'],
                'dpr': profile['dpr'], 'is_mobile': profile['is_mobile'], 'has_touch': profile['has_touch'],
                'input': profile['input'], 'cpu_throttle': args.cpu_throttle, 'seed': args.seed,
                'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows,
                'replay_sha256': fc.replay_sha256(replay), 'ablate': off, 'features_off': off, 'diagnostic': False,
                'density': 'pinned to profile DPR; adaptive observe disabled',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                                 'PLATFORM falls back to the local adapter (no ads, instant restart on death)'}
    cfg = {'dpr': profile['dpr'], 'input': profile['input'], 'ablate': [], 'diagnostic': False, 'replay': replay,
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    raw = {'case': args.case, 'task': TASK, 'settings': settings,
           'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
           'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE),
           'chill_sha256': fc.sha_file(ch.MODULE), 'interaction_sha256': fc.sha_file(MODULE),
           'feature_specs': {f: FEATURES[f] for f in off}, 'argv': sys.argv, 'started_utc': utc(), 'replay': replay,
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
        page.evaluate(COMBO_INSTRUMENT, combo_cfg(off))
        page.evaluate(ch.SAMPLER)
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
        check_hooks(raw)
        if raw['errors'] or raw['error']:
            raise fc.EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw['error']]))
        if raw['dimensions']['platform'] not in ('disabled', 'absent'):
            raise fc.EvidenceError('SDK isolation failed: ' + str(raw['dimensions']['platform']))
        if raw['dimensions']['version'] != args.mode:
            raise fc.EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
        if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
            raise fc.EvidenceError('backing size changed during the capture')
        if len(raw['samples']) != len(raw['frames']):
            raise fc.EvidenceError(f'{len(raw["samples"])} samples for {len(raw["frames"])} active frames')
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
          raw['result'], 'mode=%s backing=%s off=%s skipped=%s' % (args.mode, raw['dimensions']['canvas'], off, raw.get('skipped')),
          'fps=%.2f mean_ms=%.2f p50=%.2f p95=%.2f max=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], 1000 / c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'],
              c['frame_ms']['max'], c['active_ms'], raw['summary']['deaths']) if c else '',
          'camera_travel=%.0f moving=%.2f deaths_in_window=%d particles_mean=%.1f' % (
              d['camera']['travel_px'], d['camera']['moving_fraction'] or 0, d['deaths_in_window'],
              d['counts']['particles']['mean']) if d else '', flush=True)
    return exit_code


def check_hooks(raw):
    """The hooks actually installed must be exactly the requested stages, each reached by draw()."""
    off = raw['settings']['features_off']
    expected = [FEATURES[f]['removes'] for f in off]
    if raw['ablated'] != expected:
        raise fc.EvidenceError(f'hook mismatch: installed {raw["ablated"]} expected {expected}')
    if raw.get('featuresOff') != off:
        raise fc.EvidenceError('in-page featuresOff differs from settings')
    for f in off:
        if not raw['skipped'].get(f):
            raise fc.EvidenceError(f'disabled hook {f} was never reached by draw()')
    if set(raw['skipped']) - set(off):
        raise fc.EvidenceError(f'unexpected skipped draw calls {raw["skipped"]}')
    for f in off:
        if raw['featureActive'].get(f) is not True:
            raise fc.EvidenceError(f'stage {f} not active in this arm: {raw["featureActive"].get(f)}')


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
                                    'chill_sha256': fc.sha_file(ch.MODULE), 'interaction_sha256': fc.sha_file(MODULE),
                                    'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py')})
    print('PASS identity written', out / 'identity.json', 'HEAD', identity['current_commit'],
          'dirty_runtime=%r' % identity['current_dirty_runtime'], 'ceiling_fps=%.2f' % ceiling['average_fps'])
    return 0


# ------------------------------------------------------------------ run --

def capture_argv(root, out, mode, seed, style, case, off, args):
    argv = [sys.executable, 'tools/y8_feature_interaction.py', 'capture', '--root', root, '--output', str(out),
            '--mode', mode, '--seed', str(seed), '--replay-style', style, '--case', case, '--profile', PROFILE,
            '--windows', '1', '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms)]
    for f in off:
        argv += ['--off', f]
    return argv


def run(args):
    out = Path(args.output)
    root = ch.verified_root(out)
    sel = fc.load(out / 'selection.json')
    combos = {c['id']: c for c in sel['combinations']}
    if not sel['selected']:
        print('RUN SKIPPED: no eligible stage (negative selection result recorded in selection.json)')
        return 0
    failures = 0
    for mode in args.modes:
        seed, style = sel['modes'][mode]['seed'], sel['modes'][mode]['replay_style']
        for rep in REPS:
            for cid in sel['order'][rep]:
                case = case_name(cid, mode, seed, rep)
                if args.resume and ab.complete_case(ab.load_raws(out), case):
                    print('INFO resume: complete raw exists for', case, flush=True)
                    continue
                argv = capture_argv(root, out, mode, seed, style, case, combos[cid]['off'], args)
                failures += ab.receipt(out, f'{cid}/{mode}/{rep}', argv) != 0
    print(f'RUN DONE modes={args.modes} stages={sel["selected"]} combinations={len(combos)} failed_captures={failures}', flush=True)
    return 1 if failures else 0


# ---------------------------------------------------------------- prove --

def simulate(off, mode, frames, seed, style, sampler=True, root=ROOT):
    from browser_test_support import start_browser_test
    cfg = {'dpr': 1, 'input': 'mouse', 'ablate': [], 'diagnostic': True,
           'replay': ch.replay_script(seed, PROFILE, frames * 17, style), 'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
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
        page.evaluate(COMBO_INSTRUMENT, combo_cfg(off))
        if sampler:
            page.evaluate(ch.SAMPLER)
        result = page.evaluate(ab.SIMULATION, {'mode': mode, 'frames': frames})
        result['samples'] = page.evaluate(f'() => ({fc.MARKER}.samples || []).length')
        result['featuresOff'] = page.evaluate(f'() => {fc.MARKER}.featuresOff')
        result['errors'] = errors
    result['particleDigestSha'] = fc.sha_bytes(json.dumps(result.pop('particleDigest')).encode())
    return result


def prove(args):
    out = Path(args.output)
    sel = fc.load(out / 'selection.json')
    started = utc()
    report = {'task': TASK, 'utc_start': started, 'argv': sys.argv, 'frames': args.frames, 'stages': sel['selected'],
              'method': 'synthetic 60 Hz requestAnimationFrame timestamps, performance.now pinned, seeded Math.random, '
                        'fc.INSTRUMENT physics counter (--diagnostic, never paired with primary captures), TASK-273 sampler '
                        'installed in every arm except reference-no-sampler; fresh page per arm; equality over '
                        + ', '.join(ab.EQUALITY_KEYS),
              'equality_keys': list(ab.EQUALITY_KEYS), 'modes': {}}
    ok = True
    for mode in args.modes:
        seed, style = sel['modes'][mode]['seed'], sel['modes'][mode]['replay_style']
        reference = simulate([], mode, args.frames, seed, style, sampler=True)
        repeat = simulate([], mode, args.frames, seed, style, sampler=True)
        no_sampler = simulate([], mode, args.frames, seed, style, sampler=False)
        arms = {'reference': reference, 'reference-repeat': repeat, 'reference-no-sampler': no_sampler}
        checks = {'reference-repeat': {'differs': ab.equality(reference, repeat)},
                  'reference-no-sampler': {'differs': ab.equality(reference, no_sampler)}}
        mode_ok = not checks['reference-repeat']['differs'] and not checks['reference-no-sampler']['differs'] \
            and reference['steps'] > 0 and reference['particleUpdates'] > 0 and reference['samples'] == args.frames
        print(f'{"PASS" if mode_ok else "FAIL"} determinism {mode} seed={seed} style={style}: repeat differs='
              f'{checks["reference-repeat"]["differs"]} no-sampler differs={checks["reference-no-sampler"]["differs"]} '
              f'physics_steps={reference["steps"]} particle_updates={reference["particleUpdates"]} samples={reference["samples"]}', flush=True)
        for c in sel['combinations']:
            if c['is_control']:
                continue
            r = simulate(c['off'], mode, args.frames, seed, style, sampler=True)
            arms[c['id']] = r
            diff = ab.equality(reference, r)
            expected = [FEATURES[f]['removes'] for f in c['off']]
            check = {'off': c['off'], 'differs': diff, 'skipped_draw_calls': {f: r['skipped'].get(f, 0) for f in c['off']},
                     'ablated': r['ablated'], 'errors': r['errors'], 'samples': r['samples'],
                     'pass': not diff and not r['errors'] and all(r['skipped'].get(f, 0) > 0 for f in c['off'])
                     and r['ablated'] == expected and r['samples'] == args.frames and r['featuresOff'] == c['off']}
            mode_ok &= check['pass']
            checks[c['id']] = check
            print(f'{"PASS" if check["pass"] else "FAIL"} equality {mode} {c["id"]} off={c["off"]}: differs={diff} '
                  f'skipped={check["skipped_draw_calls"]} physics_steps={r["steps"]} particle_updates={r["particleUpdates"]} '
                  f'particles={r["particleCount"]} track_points={r["trackPoints"]} score={r["score"]} screen={r["screen"]}', flush=True)
        ok &= mode_ok
        report['modes'][mode] = {'seed': seed, 'replay_style': style, 'arms': arms, 'checks': checks, 'pass': mode_ok}
    report['utc_end'] = utc()
    report['pass'] = ok
    fc.dump(out / 'state-equality.json', report)
    print(('PASS' if ok else 'FAIL'), 'state equality written', out / 'state-equality.json')
    return 0 if ok else 1


# --------------------------------------------------------------- report --

def mean_ms(raw):
    return 1000 / raw['summary']['combined']['average_fps']


def arm_record(raw, path):
    s, w = raw['summary'], raw['summary']['windows'][0]
    d = raw['density']
    return {'case': raw['case'], 'raw': path, 'result': raw['result'], 'mode': raw['settings']['mode'],
            'seed': raw['settings']['seed'], 'replay_style': raw['settings']['replay_style'],
            'features_off': raw['settings']['features_off'], 'ablated': raw['ablated'], 'skipped_draw_calls': raw['skipped'],
            'feature_active': raw['featureActive'], 'stage_flags': raw['stageFlags'], 'features': raw['features'],
            'quality': raw['quality'], 'density_pin': raw['densityPin'], 'backing': raw['dimensions']['canvas'],
            'replay_sha256': raw['settings']['replay_sha256'], 'frames_sha256': raw['frames_sha256'],
            'samples_sha256': raw['samples_sha256'], 'started_utc': raw['started_utc'], 'ended_utc': raw['ended_utc'],
            'deaths': s['deaths'], 'death_times_active_ms': [x['activeMs'] for x in raw['deaths']],
            'excluded_frames': s['excluded_frames'], 'dispatched_inputs': s['dispatched_inputs'],
            'warmup_frames': s['warmup_frames'], 'window': w, 'mean_ms': 1000 / w['average_fps'],
            'intervals_ms': [f['dt'] for f in fc.split_windows(raw['frames'], raw['settings']['warmup_ms'],
                                                               raw['settings']['window_ms'], raw['settings']['windows'])[0][1:]
                             if f['dt'] is not None],
            'density': {'deaths_in_window': d['deaths_in_window'], 'camera_travel_px': d['camera']['travel_px'],
                        'camera_moving_fraction': d['camera']['moving_fraction'],
                        'particles_mean': d['counts']['particles']['mean'], 'track_mean': d['counts']['track']['mean'],
                        'obstacle_track_mean': d['counts']['obstacleTrack']['mean'],
                        'elements_mean': d['counts']['elements']['mean'], 'motes': d['counts']['motes']['max']}}


def classify_interaction(discrepancies, noise):
    """discrepancy = measured combined saving - sum of single savings (same repetition)."""
    values = list(discrepancies.values())
    if all(abs(d) <= noise for d in values):
        return 'ADDITIVE'
    if all(d < -noise for d in values):
        return 'SUB_ADDITIVE'
    if all(d > noise for d in values):
        return 'SUPER_ADDITIVE'
    return 'INCONCLUSIVE'


def analyse(combos, means, prior_noise):
    """Per-mode interaction arithmetic from mean frame times {cid: {rep: ms}}; pure, unit-tested."""
    control = next(c['id'] for c in combos if c['is_control'])
    ctl = means[control]
    saving = {cid: {rep: ctl[rep] - means[cid][rep] for rep in REPS} for cid in means if cid != control}
    own_cc = abs(ctl['r1'] - ctl['r2'])
    noise_max = max(own_cc, prior_noise.get('max') or 0.0)
    noise_typical = max(own_cc, prior_noise.get('typical') or 0.0)
    singles = {c['off'][0]: c['id'] for c in combos if len(c['off']) == 1}
    rows = {}
    for c in combos:
        if c['is_control']:
            continue
        s = saving[c['id']]
        row = {'id': c['id'], 'off': c['off'], 'label': c['label'], 'measured_saving_ms': s,
               'median_measured_saving_ms': statistics.median(s.values()),
               'repeat_difference_ms': abs(s['r1'] - s['r2']), 'repeat_sign_agrees': (s['r1'] > 0) == (s['r2'] > 0),
               'beyond_noise_max_every_repeat': all(abs(v) > noise_max for v in s.values()),
               'beyond_noise_typical_every_repeat': all(abs(v) > noise_typical for v in s.values())}
        row['inconsistent_repeat'] = (not row['repeat_sign_agrees']) or row['repeat_difference_ms'] > noise_max
        if len(c['off']) >= 2:
            sums = {rep: sum(saving[singles[f]][rep] for f in c['off']) for rep in REPS}
            disc = {rep: s[rep] - sums[rep] for rep in REPS}
            row.update({'sum_of_single_savings_ms': sums, 'discrepancy_ms': disc,
                        'median_discrepancy_ms': statistics.median(disc.values()),
                        'discrepancy_beyond_typical_every_repeat': all(abs(d) > noise_typical for d in disc.values()),
                        'classification': classify_interaction(disc, noise_max)})
            if len(c['off']) == 3:
                pair_ids = [p['id'] for p in combos if len(p['off']) == 2]
                row['pairwise_discrepancy_sum_ms'] = {rep: sum(rows[p]['discrepancy_ms'][rep] for p in pair_ids) for rep in REPS}
                row['three_way_residual_ms'] = {rep: disc[rep] - row['pairwise_discrepancy_sum_ms'][rep] for rep in REPS}
        rows[c['id']] = row
    return {'control_id': control, 'control_mean_ms': ctl, 'control_control_ms': own_cc,
            'noise': {'own_control_control_ms': own_cc, 'prior_population_max_ms': prior_noise.get('max'),
                      'prior_population_typical_ms': prior_noise.get('typical'), 'noise_max_ms': noise_max,
                      'noise_typical_ms': noise_typical,
                      'rule': 'noise_max = max(|control r1 - control r2| of this run, prior population max control-control '
                              'spread from TASK-273 decision.json); noise_typical = same with the prior median spread; '
                              'ADDITIVE: every repetition |discrepancy| <= noise_max; SUB_ADDITIVE: every repetition '
                              'discrepancy < -noise_max (combined saving smaller than the sum); SUPER_ADDITIVE: every '
                              'repetition discrepancy > noise_max; otherwise INCONCLUSIVE; inconsistent_repeat: the two '
                              'repetitions disagree in sign or differ by more than noise_max'},
            'rows': rows}


def build(out):
    out = Path(out)
    sel = fc.load(out / 'selection.json')
    raws = ab.load_raws(out) if (out / 'raw').exists() else {}
    eq = fc.load(out / 'state-equality.json') if (out / 'state-equality.json').exists() else None
    combos = sel['combinations']
    control_id = next(c['id'] for c in combos if c['is_control'])
    per_mode, arms, interaction = {}, {}, {}
    for mode in MODES:
        seed, style = sel['modes'][mode]['seed'], sel['modes'][mode]['replay_style']
        cases = {rep: {c['id']: case_name(c['id'], mode, seed, rep) for c in combos} for rep in REPS}
        got = {rep: {cid: ab.complete_case(raws, case) for cid, case in cases[rep].items()} for rep in REPS}
        paths = {rep: {cid: next((p for p, r in raws.items() if r['case'] == case and r.get('result') == 'COMPLETE'), None)
                       for cid, case in cases[rep].items()} for rep in REPS}
        all_cases = [case for rep in REPS for case in cases[rep].values()]
        block = {'mode': mode, 'mode_name': sel['modes'][mode]['name'], 'seed': seed, 'replay_style': style,
                 'replay_box': sel['modes'][mode]['replay_box'], 'control_id': control_id,
                 'order': sel['order'], 'cases': cases,
                 'attempts': [p for p, r in raws.items() if r['case'] in all_cases],
                 'failed_attempts': [p for p, r in raws.items() if r['case'] in all_cases and r.get('result') != 'COMPLETE']}
        missing = [cases[rep][cid] for rep in REPS for cid in cases[rep] if not got[rep][cid]]
        if missing:
            block['result'] = 'MISSING: ' + ', '.join(missing)
            per_mode[mode] = block
            continue
        complete = {rep: {cid: got[rep][cid] for cid in got[rep]} for rep in REPS}
        for rep in REPS:
            for cid, r in complete[rep].items():
                arms[r['case']] = arm_record(r, paths[rep][cid])
        every = [r for rep in REPS for r in complete[rep].values()]
        first = every[0]
        order_ok = {}
        for rep in REPS:
            starts = [complete[rep][cid]['started_utc'] for cid in sel['order'][rep]]
            order_ok[rep] = starts == sorted(starts) and len(set(starts)) == len(starts)
        block['matched'] = {
            'settings': all(all(r['settings'].get(k) == first['settings'].get(k) for k in fc.PAIRED_SETTINGS) for r in every),
            'replay_sha256': len({r['settings']['replay_sha256'] for r in every}) == 1,
            'backing': sorted({tuple(f['canvas']) for r in every for f in r['frames']}),
            'features_quality': len({json.dumps([r['features'], r['quality']], sort_keys=True) for r in every}) == 1,
            'feature_active_equal': len({json.dumps(r['featureActive'], sort_keys=True) for r in every}) == 1,
            'selected_stages_active_every_arm': all(r['featureActive'].get(f) is True for r in every for f in sel['selected']),
            'stage_flags_equal': len({json.dumps(r['stageFlags'], sort_keys=True) for r in every}) == 1,
            'tree_identical': len({json.dumps(r['tree']['files_sha256'], sort_keys=True) for r in every}) == 1,
            'hooks_match_combination': all(r['ablated'] == [FEATURES[f]['removes'] for f in r['settings']['features_off']]
                                           and set(r['skipped']) == set(r['settings']['features_off'])
                                           and all(r['skipped'][f] > 0 for f in r['settings']['features_off']) for r in every),
            'order_r1_ascending_r2_reversed': order_ok,
            'deaths': {r['case']: r['summary']['deaths'] for r in every},
            'excluded_frames': {r['case']: r['summary']['excluded_frames'] for r in every},
            'dispatched_inputs': {r['case']: r['summary']['dispatched_inputs'] for r in every}}
        block['result'] = 'PAIRED' if all(v is True for k, v in block['matched'].items()
                                         if k not in ('backing', 'deaths', 'excluded_frames', 'dispatched_inputs', 'order_r1_ascending_r2_reversed')) \
            and len(block['matched']['backing']) == 1 and all(order_ok.values()) else 'MISMATCH'
        means = {cid: {rep: mean_ms(complete[rep][cid]) for rep in REPS} for cid in cases['r1']}
        ana = analyse(combos, means, sel['prior_noise_ms'][mode])
        rows = []
        for c in combos:
            cid = c['id']
            row = {'id': cid, 'label': c['label'], 'off': c['off'], 'on': c['on'], 'is_control': c['is_control'],
                   'cases': {rep: cases[rep][cid] for rep in REPS}, 'raw': {rep: paths[rep][cid] for rep in REPS},
                   'mean_ms': means[cid], 'average_fps': {rep: complete[rep][cid]['summary']['combined']['average_fps'] for rep in REPS},
                   'p50_ms': {rep: complete[rep][cid]['summary']['combined']['frame_ms']['p50'] for rep in REPS},
                   'p95_ms': {rep: complete[rep][cid]['summary']['combined']['frame_ms']['p95'] for rep in REPS},
                   'skipped_draw_calls': {rep: complete[rep][cid]['skipped'] for rep in REPS},
                   'deaths': {rep: complete[rep][cid]['summary']['deaths'] for rep in REPS},
                   'camera_travel_px': {rep: complete[rep][cid]['density']['camera']['travel_px'] for rep in REPS},
                   'particles_mean': {rep: complete[rep][cid]['density']['counts']['particles']['mean'] for rep in REPS}}
            if not c['is_control']:
                a = ana['rows'][cid]
                row.update({'saving_ms_vs_same_repetition_control': a['measured_saving_ms'],
                            'median_saving_ms': a['median_measured_saving_ms'], 'inconsistent_repeat': a['inconsistent_repeat']})
            rows.append(row)
        block.update({'rows': rows, 'control_mean_ms': ana['control_mean_ms'], 'control_control_ms': ana['control_control_ms'],
                      'noise': ana['noise']})
        per_mode[mode] = block
        interaction[mode] = {'mode': mode, 'mode_name': sel['modes'][mode]['name'], 'seed': seed, 'replay_style': style,
                             'result': block['result'], **ana}
    stage_flags = {}
    for a in arms.values():
        for k, v in a['stage_flags'].items():
            stage_flags.setdefault(k, set()).add(v)
    stage_flags = {k: sorted(v, key=str) for k, v in stage_flags.items()}
    combos_doc = {
        'task': TASK, 'selection': 'selection.json', 'selected_stages': sel['selected'], 'selection_why': sel['why'],
        'selection_rows': sel['rows'], 'protocol': sel['protocol'], 'combinations': combos, 'order': sel['order'],
        'expected_captures': sel['expected_captures'], 'complete_captures': len(arms),
        'negative_result': sel['negative_result'],
        'modes': per_mode, 'arms': arms, 'stage_flags_observed': stage_flags,
        'inactive_pipeline_stages': {k: v for k, v in stage_flags.items() if v == [False]},
        'simulation_equality': {'path': 'state-equality.json', 'pass': eq['pass'],
                                'checks': {m: {k: {'differs': c['differs'], 'skipped_draw_calls': c.get('skipped_draw_calls')}
                                               for k, c in v['checks'].items()} for m, v in eq['modes'].items()}} if eq else None,
        'simulation_rate_note': 'gameoptions.js maxPhysicsStepsPerFrame = 2 caps simulated time per frame: faster arms '
                                'traverse more world in the same 10 s active window (camera travel recorded per arm)',
        'sign_convention': 'saving = control mean frame time - combination mean frame time, within the same repetition '
                           'and mode; positive = the combination was faster',
        'limits': 'software headless Chromium under shared host load; paired within-repetition deltas are the signal; '
                  'no 60 FPS, device or readiness claim; nothing is removed from the shipped game'}
    singles_vs_prior = {}
    for mode in MODES:
        if mode not in interaction:
            continue
        row273 = {r['feature']: r for r in sel['rows']}
        singles_vs_prior[mode] = {
            f: {'this_run_saving_ms': interaction[mode]['rows'][next(c['id'] for c in combos if c['off'] == [f])]['measured_saving_ms'],
                'this_run_median_ms': interaction[mode]['rows'][next(c['id'] for c in combos if c['off'] == [f])]['median_measured_saving_ms'],
                'prior_median_saving_ms': (-row273[f]['median_delta_mean_ms_by_mode'][mode]
                                           if row273[f]['median_delta_mean_ms_by_mode'][mode] is not None else None),
                'prior_tier': row273[f]['tier_by_mode'][mode]}
            for f in sel['selected']}
    interaction_doc = {
        'task': TASK, 'stages': sel['selected'], 'attribution': ATTRIBUTION, 'modes': interaction,
        'single_stage_vs_prior_tasks': singles_vs_prior,
        'summary': {m: {cid: {'off': r['off'], 'median_measured_saving_ms': r['median_measured_saving_ms'],
                              'median_sum_of_singles_ms': statistics.median(r['sum_of_single_savings_ms'].values()) if 'sum_of_single_savings_ms' in r else None,
                              'median_discrepancy_ms': r.get('median_discrepancy_ms'), 'classification': r.get('classification'),
                              'inconsistent_repeat': r['inconsistent_repeat']} for cid, r in v['rows'].items()}
                    for m, v in interaction.items()},
        'inconsistent_repeats': {m: [cid for cid, r in v['rows'].items() if r['inconsistent_repeat']] for m, v in interaction.items()},
        'discrepancies_beyond_noise': {m: [cid for cid, r in v['rows'].items() if r.get('classification') in ('SUB_ADDITIVE', 'SUPER_ADDITIVE')]
                                       for m, v in interaction.items()},
        'sign_convention': combos_doc['sign_convention'], 'limits': combos_doc['limits']}
    decision_doc = decide(sel, combos, interaction, per_mode, eq, arms)
    return {'selection': sel, 'combinations': combos_doc, 'interaction': interaction_doc, 'decision': decision_doc, 'raws': raws}


def decide(sel, combos, interaction, per_mode, eq, arms):
    stages = sel['selected']
    singles = {f: next(c['id'] for c in combos if c['off'] == [f]) for f in stages}
    all_off = next((c['id'] for c in combos if len(c['off']) == len(stages) and stages), None)
    hyps = []
    for f in stages:
        per = {}
        for mode, ia in interaction.items():
            r = ia['rows'][singles[f]]
            per[mode] = {'saving_ms': r['measured_saving_ms'], 'median_saving_ms': r['median_measured_saving_ms'],
                         'beyond_noise_max_every_repeat': r['beyond_noise_max_every_repeat'],
                         'beyond_noise_typical_every_repeat': r['beyond_noise_typical_every_repeat'],
                         'repeat_sign_agrees': r['repeat_sign_agrees'], 'repeat_difference_ms': r['repeat_difference_ms'],
                         'size_repeatable_within_noise_max': r['repeat_difference_ms'] <= ia['noise']['noise_max_ms'],
                         'inconsistent_repeat': r['inconsistent_repeat'], 'noise_max_ms': ia['noise']['noise_max_ms'],
                         'control_mean_ms': ia['control_mean_ms'],
                         'share_of_control_frame_time': {rep: r['measured_saving_ms'][rep] / ia['control_mean_ms'][rep] for rep in REPS},
                         'interactions': {cid: {'with': [x for x in row['off'] if x != f], 'classification': row['classification'],
                                                'discrepancy_ms': row['discrepancy_ms']}
                                          for cid, row in ia['rows'].items() if f in row['off'] and len(row['off']) >= 2}}
        score = sum(max(0.0, p['median_saving_ms']) for p in per.values())
        strong = all(p['beyond_noise_max_every_repeat'] and p['repeat_sign_agrees'] and p['median_saving_ms'] > 0 for p in per.values())
        consistent = all(p['beyond_noise_typical_every_repeat'] and p['repeat_sign_agrees'] and p['median_saving_ms'] > 0 for p in per.values())
        hyps.append({'feature': f, 'stage': STAGES[f], 'removes': FEATURES[f]['removes'],
                     'claim': f'{STAGES[f]} is a frame-time bottleneck of the draw pipeline in both modes: skipping its drawing '
                              f'(diagnostic clone only) lowers the mean active frame interval by the amounts below',
                     'summed_median_saving_ms': score, 'by_mode': per,
                     'confidence': 'HIGH' if strong and per else 'MEDIUM' if consistent and per else 'LOW',
                     'confidence_rule': 'existence of the saving: HIGH when every repetition in both modes saves more than '
                                        'noise_max with agreeing signs; MEDIUM when the same holds beyond noise_typical; LOW '
                                        'otherwise. The size of the saving is judged separately per mode by '
                                        'size_repeatable_within_noise_max / inconsistent_repeat (repeat difference vs noise_max)',
                     'size_repeatable_every_mode': all(p['size_repeatable_within_noise_max'] for p in per.values()),
                     'prior': {m: {'tier': next(r for r in sel['rows'] if r['feature'] == f)['tier_by_mode'][m],
                                   'median_delta_mean_ms': next(r for r in sel['rows'] if r['feature'] == f)['median_delta_mean_ms_by_mode'][m]}
                               for m in MODES}})
    hyps.sort(key=lambda h: (-h['summed_median_saving_ms'], h['feature']))
    for i, h in enumerate(hyps, 1):
        h['rank'] = i
    residual = {}
    for mode, ia in interaction.items():
        if not all_off:
            continue
        r = ia['rows'][all_off]
        residual[mode] = {'all_off_id': all_off, 'control_mean_ms': ia['control_mean_ms'],
                          'all_off_mean_ms': {rep: ia['control_mean_ms'][rep] - r['measured_saving_ms'][rep] for rep in REPS},
                          'saving_ms': r['measured_saving_ms'],
                          'fraction_of_control_frame_time_explained': {rep: r['measured_saving_ms'][rep] / ia['control_mean_ms'][rep] for rep in REPS},
                          'sum_of_singles_ms': r['sum_of_single_savings_ms'], 'classification': r['classification'],
                          'note': 'frame time remaining with the three stages off is the cost of everything else '
                                  '(simulation, other draw layers, raster/composite of the remaining layers) plus the rAF floor'}
    interactions = {m: {cid: {'off': r['off'], 'classification': r['classification'], 'discrepancy_ms': r['discrepancy_ms'],
                              'inconsistent_repeat': r['inconsistent_repeat']}
                        for cid, r in ia['rows'].items() if 'classification' in r} for m, ia in interaction.items()}
    toggles = {
        'hooks_in_page_only': 'TASK-272 install strings evaluated inside the diagnostic clone page after boot (marker '
                              '__featureCost); the served tree is the unchanged git archive of HEAD',
        'runtime_defaults_recorded_per_arm': 'STYLE.features / QUALITY / stage flags / feature active flags read in-page '
                                             'and equal across every arm of a mode (combinations.json modes.*.matched)',
        'runtime_defaults_equal_every_arm': {m: (b.get('matched', {}).get('features_quality') is True and b.get('matched', {}).get('stage_flags_equal') is True
                                                 and b.get('matched', {}).get('feature_active_equal') is True) for m, b in per_mode.items()},
        'tree_identical_every_arm': {m: b.get('matched', {}).get('tree_identical') for m, b in per_mode.items()},
        'simulation_unchanged': {'path': 'state-equality.json', 'pass': eq['pass'] if eq else None,
                                 'modes': {m: v['pass'] for m, v in eq['modes'].items()} if eq else None},
        'raw_frames': sorted({a['raw'] for a in arms.values()}),
        'nothing_removed_from_shipped_game': True}
    modes_paired = all(b.get('result') == 'PAIRED' for b in per_mode.values()) and len(per_mode) == len(MODES)
    if not stages:
        verdict = 'negative selection result: no eligible stage, no combination measured (see selection.json)'
    elif not modes_paired:
        verdict = 'incomplete: not every mode has a paired combination set (see combinations.json modes.*.result)'
    else:
        top = hyps[0]
        verdict = (f'ranked bottleneck hypothesis: 1. {top["feature"]} (summed median saving {top["summed_median_saving_ms"]:.1f} ms, '
                   f'confidence {top["confidence"]})' + ''.join(f'; {h["rank"]}. {h["feature"]} ({h["summed_median_saving_ms"]:.1f} ms, {h["confidence"]})'
                                                           for h in hyps[1:]))
        verdict += '; interactions: ' + '; '.join(f'{m} ' + ', '.join(f'{r["off"]}={r["classification"]}' for r in v.values())
                                                  for m, v in interactions.items())
    return {'task': TASK, 'stages': stages, 'ranked_hypotheses': hyps, 'interactions': interactions, 'residual_after_all_off': residual,
            'temporary_toggles_isolated': toggles, 'attribution': ATTRIBUTION, 'verdict': verdict,
            'negative_findings_valid': True,
            'uncertainty': 'one software-rendered host under unrelated load; two repetitions per combination and mode; '
                           'noise bounds are this run\'s control-control spread and the prior population spreads; '
                           'maxPhysicsStepsPerFrame = 2 lets faster arms traverse more world per window (camera travel '
                           'recorded); hypotheses rank draw-pipeline stages of the diagnostic clone and do not attribute '
                           'raster cost from JS timing',
            'not_claimed': ['60 FPS', 'release readiness', 'physical-device performance', 'production feature removal']}


def report(args):
    out = Path(args.output)
    built = build(out)
    identity_file = fc.load(out / 'identity.json')
    identity = identity_file['identity']
    commands = [json.loads(line) for line in (out / 'commands.jsonl').read_text().splitlines() if line.strip()] \
        if (out / 'commands.jsonl').exists() else []
    raws = built['raws']
    sel = built['selection']
    eq = fc.load(out / 'state-equality.json') if (out / 'state-equality.json').exists() else None
    fc.dump(out / 'combinations.json', built['combinations'])
    fc.dump(out / 'interaction.json', built['interaction'])
    fc.dump(out / 'decision.json', built['decision'])
    evidence = sorted(['selection.json', 'combinations.json', 'interaction.json', 'decision.json', 'identity.json']
                      + (['commands.jsonl'] if commands else []) + (['state-equality.json'] if eq else []) + list(raws)
                      + ([MODULE_AT_CAPTURE] if (out / MODULE_AT_CAPTURE).exists() else []))
    first = next(iter(raws.values())) if raws else None
    manifest = {
        'task': TASK, 'utc_start': min([sel['utc'], identity_file['utc_start']]), 'utc_end': utc(), 'report_argv': sys.argv,
        'commands': [{'label': 'select', 'argv': sel['argv'], 'utc_start': sel['utc'], 'utc_end': sel['utc'], 'exit_code': 0},
                     {'label': 'prepare', 'argv': identity_file['argv'], 'utc_start': identity_file['utc_start'],
                      'utc_end': identity_file['utc_end'], 'exit_code': 0}] + commands
                    + ([{'label': 'prove', 'argv': eq['argv'], 'utc_start': eq['utc_start'], 'utc_end': eq['utc_end'],
                         'exit_code': 0 if eq['pass'] else 1}] if eq else []),
        'source_revision': identity['current_commit'], 'source_revision_at_report': fc.git('rev-parse', 'HEAD'),
        'source_dirty_runtime': identity['current_dirty_runtime'],
        'source_dirty_at_report': fc.git('status', '--porcelain', '--untracked-files=no'),
        'harness_sha256': fc.sha_file(fc.HARNESS), 'ablation_sha256': fc.sha_file(ab.MODULE), 'chill_sha256': fc.sha_file(ch.MODULE),
        'interaction_sha256': fc.sha_file(MODULE), 'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py'),
        'interaction_sha256_at_capture': sorted({r['interaction_sha256'] for r in raws.values()}),
        'module_at_capture': MODULE_AT_CAPTURE if (out / MODULE_AT_CAPTURE).exists() else None,
        'executed_hashes': {'harness_sha256_in_raws': sorted({r['harness_sha256'] for r in raws.values()}),
                            'ablation_sha256_in_raws': sorted({r['ablation_sha256'] for r in raws.values()}),
                            'chill_sha256_in_raws': sorted({r['chill_sha256'] for r in raws.values()}),
                            'interaction_sha256_in_raws': sorted({r['interaction_sha256'] for r in raws.values()}),
                            'note': 'every raw file records the hashes of the four modules that executed it; audit requires '
                                    'them to equal the committed modules, or (interaction module only) the capture-time '
                                    'module preserved byte-for-byte at module_at_capture (only report-side code may differ)'},
        'candidate_hashes': {'current_tar_sha256': identity['current_tar_sha256'], 'current_files_sha256': identity['current_files_sha256'],
                             'tree_sha256_sets_in_raws': sorted({fc.sha_bytes(json.dumps(r['tree']['files_sha256'], sort_keys=True).encode())
                                                                 for r in raws.values()})},
        'inputs': sel['inputs'],
        'environment': {**(first['environment'] if first else {}), 'ceiling': identity_file['environment_ceiling']},
        'fixed': {'profile': fc.PROFILES[PROFILE], 'backing_size_by_arm': {k: v['backing'] for k, v in built['combinations']['arms'].items()},
                  'modes': sel['modes'], 'warmup_ms': first['settings']['warmup_ms'] if first else None,
                  'window_ms': first['settings']['window_ms'] if first else None,
                  'windows_per_capture': first['settings']['windows'] if first else None,
                  'cpu_throttle': first['settings']['cpu_throttle'] if first else None,
                  'input': {m: f'ch.replay_script({v["seed"]}, {PROFILE}, total_ms, {v["replay_style"]}) scheduled on the active clock; '
                               f'replay_sha256 {sorted({r["settings"]["replay_sha256"] for r in raws.values() if r["settings"]["mode"] == m})}'
                            for m, v in sel['modes'].items()},
                  'state': 'per-frame menu/paused/offer/hidden/ad recorded; inactive frames excluded; deaths recorded via reStart '
                           'hook and never suppressed; feature active flags, stage flags, camera and density samples read in-page per arm',
                  'combinations': [c['id'] + '=' + c['label'] for c in sel['combinations']], 'order': sel['order']},
        'sdk_isolation': first['settings']['sdk_isolation'] if first else None,
        'evidence_paths': evidence, 'sha256': {name: fc.sha_file(out / name) for name in evidence},
        'failed_attempts_preserved': sorted(set([c['label'] for c in commands if c['exit_code'] != 0]
                                                + [p for p, r in raws.items() if r.get('result') != 'COMPLETE'])),
        'note': 'A successful evidence audit is separate from the performance verdict; see decision.json.'}
    fc.dump(out / 'manifest.json', manifest)
    print('PASS report written', out / 'combinations.json', out / 'interaction.json', out / 'decision.json', out / 'manifest.json')
    print('verdict:', built['decision']['verdict'])
    return 0


# ---------------------------------------------------------------- audit --

def audit(args):
    out = Path(args.output)
    m = fc.load(out / 'manifest.json')
    for name, digest in m['sha256'].items():
        if fc.sha_file(out / name) != digest:
            raise fc.EvidenceError(f'SHA256 mismatch {name}')
    print(f'PASS manifest seal: {len(m["sha256"])} evidence files match SHA256')
    for key, path in ((('harness_sha256', fc.HARNESS), ('ablation_sha256', ab.MODULE), ('chill_sha256', ch.MODULE), ('interaction_sha256', MODULE))):
        if fc.sha_file(path) != m[key]:
            raise fc.EvidenceError(f'{key} changed since report')
    for key in ('harness_sha256', 'ablation_sha256', 'chill_sha256'):
        if m['executed_hashes'][key + '_in_raws'] not in ([m[key]], []):
            raise fc.EvidenceError(f'captures executed by a different module: {key} {m["executed_hashes"][key + "_in_raws"]}')
    if len(m['interaction_sha256_at_capture']) > 1:
        raise fc.EvidenceError('captures executed by more than one interaction module version')
    if m['interaction_sha256_at_capture'] not in ([m['interaction_sha256']], []):
        if not m['module_at_capture'] or fc.sha_file(out / m['module_at_capture']) != m['interaction_sha256_at_capture'][0]:
            raise fc.EvidenceError('capture-time interaction module not preserved')
        print('INFO captures executed by interaction module', m['interaction_sha256_at_capture'][0], 'preserved at',
              m['module_at_capture'], '; report/audit module', m['interaction_sha256'], '(diff: only decision confidence-rule code differs)')
    print('PASS harness/ablation/chill/interaction modules unchanged since capture and report',
          m['harness_sha256'][:12], m['ablation_sha256'][:12], m['chill_sha256'][:12], m['interaction_sha256'][:12])
    for c in m['commands']:
        if not (c['argv'] and c['utc_start'] <= c['utc_end'] and isinstance(c['exit_code'], int)):
            raise fc.EvidenceError('command receipt incomplete: ' + json.dumps(c)[:200])
    print(f'PASS {len(m["commands"])} commands with argv/UTC start-end/exit codes; failed attempts preserved:', m['failed_attempts_preserved'])
    # Test step 1: selection against the sealed rankings, expected combinations enumerated.
    for key, rec in m['inputs'].items():
        if fc.sha_file(ROOT / rec['path']) != rec['sha256']:
            raise fc.EvidenceError(f'input {rec["path"]} changed since selection')
    sel = fc.load(out / 'selection.json')
    decision273 = fc.load(ROOT / INPUTS['task273_decision'])
    ranking272 = fc.load(ROOT / INPUTS['task272_ranking'])
    rederived = rank_stages(decision273, ranking272)
    for key in ('rows', 'eligible', 'selected', 'why', 'alternative_sum_over_repeatable_modes_only'):
        if json.loads(json.dumps(rederived[key])) != sel[key]:
            raise fc.EvidenceError(f'selection {key} differs from re-derivation')
    for r in rederived['rows']:
        print(f'PASS selection row {r["feature"]:18} score={r["summed_positive_median_saving_ms"]:7.2f} ms '
              f'chill={r["positive_median_saving_ms_by_mode"][CHILL]:6.2f} ({r["tier_by_mode"][CHILL]}) '
              f'main={r["positive_median_saving_ms_by_mode"][MAIN]:6.2f} ({r["tier_by_mode"][MAIN]}) '
              f'eligible={r["eligible"]} task272={r["task272_classification"]}')
    print(f'PASS selection re-derived from sealed inputs: selected={sel["selected"]} why={sel["why"]!r} '
          f'alternative_agrees={sel["alternative_agrees"]}')
    combos = combinations(sel['selected'])
    if json.loads(json.dumps(combos)) != sel['combinations'] or orders(combos) != sel['order']:
        raise fc.EvidenceError('combinations or orders differ from enumeration')
    expected_cases = {m_: {rep: [case_name(c['id'], m_, sel['modes'][m_]['seed'], rep) for c in combos] for rep in REPS} for m_ in MODES}
    for c in combos:
        print(f'PASS combination {c["id"]}: {c["label"]:45} off={c["off"]}')
    print(f'PASS enumerated {len(combos)} combinations x {len(REPS)} repetitions x {len(MODES)} modes = {sel["expected_captures"]} '
          f'expected captures; order r1={sel["order"]["r1"]} r2={sel["order"]["r2"]} (reversed={sel["order"]["r2"] == sel["order"]["r1"][::-1]})')
    identity = fc.load(out / 'identity.json')['identity']
    raws = ab.load_raws(out) if (out / 'raw').exists() else {}
    complete = {}
    for name, raw in raws.items():
        if name not in m['sha256']:
            raise fc.EvidenceError(f'{name} not sealed in manifest')
        if raw['harness_sha256'] != m['harness_sha256'] or raw['ablation_sha256'] != m['ablation_sha256'] \
                or raw['chill_sha256'] != m['chill_sha256'] or raw['interaction_sha256'] not in m['interaction_sha256_at_capture']:
            raise fc.EvidenceError(f'{name} captured by a different module')
        if fc.frames_sha256(raw['frames']) != raw['frames_sha256'] or fc.frames_sha256(raw['samples']) != raw['samples_sha256']:
            raise fc.EvidenceError(f'{name} frames or samples altered')
        if raw['tree']['files_sha256'] != identity['current_files_sha256']:
            raise fc.EvidenceError(f'{name} ran on a tree other than the verified HEAD archive')
        if raw.get('result') != 'COMPLETE':
            print('INFO failed attempt preserved', name, raw.get('result'))
            continue
        if raw['case'] in complete:
            raise fc.EvidenceError(f'duplicate complete case {raw["case"]}')
        complete[raw['case']] = raw
        # Test step 2: recompute from raw intervals, review equal-state and settings checks.
        if fc.summarize(raw) != raw['summary']:
            raise fc.EvidenceError(f'{name} summary does not match recomputation')
        if json.loads(json.dumps(ch.window_density(raw))) != raw['density']:
            raise fc.EvidenceError(f'{name} density does not match recomputation')
        if {tuple(f['canvas']) for f in raw['frames']} != {tuple(raw['dimensions']['canvas'])}:
            raise fc.EvidenceError(f'{name} backing size varies')
        if raw['dimensions']['platform'] not in ('disabled', 'absent') or raw['dimensions']['version'] != raw['settings']['mode']:
            raise fc.EvidenceError(f'{name} SDK not isolated or wrong mode')
        if raw['errors'] or raw['error'] or raw['settings']['diagnostic']:
            raise fc.EvidenceError(f'{name} has page errors or is diagnostic')
        if len(raw['samples']) != len(raw['frames']) or any(s['t'] != f['t'] for s, f in zip(raw['samples'], raw['frames'])):
            raise fc.EvidenceError(f'{name} samples do not cover every active frame')
        check_hooks(raw)
        for w in raw['summary']['windows']:
            if w['active_ms'] < raw['settings']['window_ms']:
                raise fc.EvidenceError(f'{name} short window')
        mode_ = raw['settings']['mode']
        if raw['settings']['seed'] != sel['modes'][mode_]['seed'] or raw['settings']['replay_style'] != sel['modes'][mode_]['replay_style']:
            raise fc.EvidenceError(f'{name} seed/replay differ from the selected segment')
        c, d = raw['summary']['combined'], raw['density']
        print(f'PASS recomputed {raw["case"]}: mode={mode_} seed={raw["settings"]["seed"]} replay={raw["settings"]["replay_style"]} '
              f'off={raw["settings"]["features_off"]} skipped={raw["skipped"]} intervals={c["intervals"]} active_ms={c["active_ms"]:.1f} '
              f'fps={c["average_fps"]:.2f} mean_ms={1000 / c["average_fps"]:.2f} p50={c["frame_ms"]["p50"]:.2f} p95={c["frame_ms"]["p95"]:.2f} '
              f'max={c["frame_ms"]["max"]:.2f} backing={raw["dimensions"]["canvas"]} deaths={raw["summary"]["deaths"]} '
              f'camera_travel={d["camera"]["travel_px"]:.0f} particles_mean={d["counts"]["particles"]["mean"]:.1f} '
              f'stage_flags={json.dumps(raw["stageFlags"], sort_keys=True)}')
    built = build(out)
    for name in ('combinations', 'interaction', 'decision'):
        if json.loads(json.dumps(built[name], sort_keys=True)) != fc.load(out / f'{name}.json'):
            raise fc.EvidenceError(f'{name}.json differs from recomputation')
    print(f'PASS combinations.json, interaction.json and decision.json match recomputation from {len(complete)} complete raw files')
    cb = built['combinations']
    for mode_ in MODES:
        block = cb['modes'][mode_]
        missing = [case for rep in REPS for case in expected_cases[mode_][rep] if case not in complete]
        if sel['selected'] and (missing or block['result'] != 'PAIRED'):
            raise fc.EvidenceError(f'{mode_}: {block["result"]}; missing {missing}')
        if not sel['selected']:
            print(f'INFO {mode_}: negative selection result, no captures expected')
            continue
        mt = block['matched']
        print(f'PASS {mode_} seed={block["seed"]} replay={block["replay_style"]}: {block["result"]} settings={mt["settings"]} '
              f'replay_sha_equal={mt["replay_sha256"]} backing={mt["backing"]} features_quality_equal={mt["features_quality"]} '
              f'feature_active_equal={mt["feature_active_equal"]} selected_active={mt["selected_stages_active_every_arm"]} '
              f'stage_flags_equal={mt["stage_flags_equal"]} tree_identical={mt["tree_identical"]} hooks={mt["hooks_match_combination"]} '
              f'order={mt["order_r1_ascending_r2_reversed"]} control_mean_ms={[round(v, 2) for v in block["control_mean_ms"].values()]} '
              f'control-control={block["control_control_ms"]:.2f} noise_max={block["noise"]["noise_max_ms"]:.2f}')
        for row in block['rows']:
            print(f'PASS   {mode_} {row["id"]} {row["label"]:40} mean_ms={[round(v, 2) for v in row["mean_ms"].values()]} '
                  f'saving={[round(v, 2) for v in row.get("saving_ms_vs_same_repetition_control", {}).values()]} '
                  f'deaths={list(row["deaths"].values())} camera_travel={[round(v) for v in row["camera_travel_px"].values()]} '
                  f'skipped={list(row["skipped_draw_calls"].values())}')
        ia = built['interaction']['modes'][mode_]
        for cid, r in ia['rows'].items():
            if 'classification' in r:
                print(f'PASS   {mode_} interaction {cid} off={r["off"]}: measured={[round(v, 2) for v in r["measured_saving_ms"].values()]} '
                      f'sum_singles={[round(v, 2) for v in r["sum_of_single_savings_ms"].values()]} '
                      f'discrepancy={[round(v, 2) for v in r["discrepancy_ms"].values()]} {r["classification"]} '
                      f'inconsistent_repeat={r["inconsistent_repeat"]}')
    if built['interaction']['attribution']['js_function_timing_used'] is not False:
        raise fc.EvidenceError('interaction attribution must not use JS function timing')
    print('PASS attribution basis:', built['interaction']['attribution']['basis'], '| js_function_timing_used=False')
    if sel['selected']:
        eq = fc.load(out / 'state-equality.json')
        if not eq['pass'] or any(c['differs'] for v in eq['modes'].values() for c in v['checks'].values()):
            raise fc.EvidenceError('state equality proof failed')
        if set(eq['modes']) != set(MODES) or any(set(v['checks']) != {'reference-repeat', 'reference-no-sampler'} | {c['id'] for c in combos if not c['is_control']}
                                                 for v in eq['modes'].values()):
            raise fc.EvidenceError('state equality does not cover every combination in every mode')
        print(f'PASS state equality: {len(eq["modes"])} modes x {len(combos) - 1} combinations + reference repeat + no-sampler reference '
              f'identical over {eq["equality_keys"]}')
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    runtime = [n for n in tracked if n.endswith(fc.RUNTIME_SUFFIXES) and not n.startswith('tools/')]
    for name in runtime:
        text = (ROOT / name).read_text(errors='replace')
        if fc.MARKER in text or 'skip("' in text or 'FC.samples' in text or 'featuresOff' in text:
            raise fc.EvidenceError(f'diagnostic hook in shipped runtime: {name}')
    print(f'PASS no diagnostic hook marker in {len(runtime)} git-tracked shipped runtime files')
    env = m['environment']
    print('PASS environment: os=%s browser=%s playwright=%s gpu=%s ceiling_fps=%.2f' % (
        env['os'], env['browser'], env['playwright'], env['gpu']['auxAttributes'].get('glRenderer'), env['ceiling']['average_fps']))
    d = built['decision']
    print('PASS evidence audit complete; performance verdict is separate:', d['verdict'])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    s = sub.add_parser('select')
    s.add_argument('--output', required=True)
    s.set_defaults(func=select)
    p = sub.add_parser('prepare')
    p.add_argument('--output', required=True)
    p.set_defaults(func=prepare)
    c = sub.add_parser('capture')
    c.add_argument('--root', required=True)
    c.add_argument('--output', required=True)
    c.add_argument('--mode', required=True, choices=fc.MODES)
    c.add_argument('--seed', required=True, type=int)
    c.add_argument('--replay-style', default='screening', choices=sorted(ch.REPLAY_STYLES))
    c.add_argument('--case', required=True)
    c.add_argument('--profile', default=PROFILE, choices=sorted(fc.PROFILES))
    c.add_argument('--cpu-throttle', type=int, default=1)
    c.add_argument('--warmup-ms', type=int, default=5000)
    c.add_argument('--window-ms', type=int, default=10000)
    c.add_argument('--windows', type=int, default=1)
    c.add_argument('--off', action='append', default=[], help='stage whose drawing is skipped (diagnostic only); repeatable')
    c.add_argument('--timeout-ms', type=int, default=240000)
    c.set_defaults(func=capture)
    r = sub.add_parser('run')
    r.add_argument('--output', required=True)
    r.add_argument('--modes', nargs='+', default=list(MODES), choices=MODES)
    r.add_argument('--warmup-ms', type=int, default=5000)
    r.add_argument('--window-ms', type=int, default=10000)
    r.add_argument('--resume', action='store_true', help='skip cases that already have a COMPLETE raw file')
    r.set_defaults(func=run)
    v = sub.add_parser('prove')
    v.add_argument('--output', required=True)
    v.add_argument('--modes', nargs='+', default=list(MODES), choices=MODES)
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
