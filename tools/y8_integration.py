#!/usr/bin/env python3
"""TASK-282: integrate only the accepted optimisation(s) from TASK-279..281 and measure the combined runtime.

Candidates and their fate (sealed in artifacts/TASK-279..281/decision.json):
  TASK-279 far-background-stack cache ............ REJECT (Chromium gradient dither, bad-mode transform drift) - not in code
  TASK-280 glow composite union-of-rectangles clip ACCEPT - body pasted into render/effects.js at commit d253649
  TASK-281 transparent-row clip of tile copies ... REJECT (immaterial / inconsistent timing)        - not in code
So the integrated runtime is HEAD; the only runtime change since the frozen TASK-271 control is the TASK-280 body.

Actions
  prepare   trees/{integrated,control,original} + identity.json + integration.json (candidate -> code mapping,
            runtime diff control -> integrated, overlap analysis)
  identity  combined controlled visual/state check: the TASK-280 visual protocol (synthetic 60 Hz clock, menu/start,
            gameplay checkpoints, forced shake, settled resizes; Chromium dpr1 seeds 1/4/49 x modes, dpr2, Firefox)
            run on the CONTROL tree and on the INTEGRATED tree with nothing injected; decoded final pixels, glow level
            textures and the state digest must be equal at every checkpoint
  capture   one timing capture through the unchanged TASK-271 harness (tools/y8_feature_cost.py capture)
  run       prepare, identity, then the timing sequence: per profile (desktop, touch) and mode (bad, classic)
            nine 30 s captures in the order C I O / O I C / C I O (C = control, I = integrated, O = original ZIP),
            i.e. three alternating pairs integrated-vs-control and three alternating pairs integrated-vs-original,
            each capture = 5 s warmup + three 10 s windows (30 s measured, 10 s minima from the windows)
  report    integration.json (identity results), comparison.json, cost-ranking.json, manifest.json
  audit     recompute everything from the raws, verify seals and that the shipped runtime equals the integrated tree

Nothing here claims 60 FPS, device results or release readiness: software headless Chromium only.
"""

import argparse
from contextlib import ExitStack
import io
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_cost as fc  # noqa: E402
import y8_glow_region as gr  # noqa: E402
import y8_chill_ablation as ch  # noqa: E402

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
TASK = 'TASK-282'
CONTROL_TASK_DIR = ROOT / 'artifacts/TASK-271'
MODES = ('bad', 'classic')
PROFILES = ('desktop', 'touch')
SEED = 4
WARMUP_MS = 5000
WINDOW_MS = 10000
WINDOWS = 3
WINDOW_SLACK_MS = 500  # one frame interval of slack per 10 s window (cumulative cut at frame boundaries, see audit)
TREES = ('integrated', 'control', 'original')
TREE_LABELS = {'integrated': 'HEAD runtime with the accepted TASK-280 body (git archive HEAD)',
               'control': 'frozen TASK-271 current control (artifacts/TASK-271/trees/current, sealed by its manifest)',
               'original': 'historical TASK-098 ZIP (artifacts/TASK-271/trees/original, byte-identical to its commit)'}
# Three triples per cell; the integrated arm sits in the middle of each triple and the control/original order alternates.
SEQUENCE = [('p1', 'control'), ('p1', 'integrated'), ('p1', 'original'),
            ('p2', 'original'), ('p2', 'integrated'), ('p2', 'control'),
            ('p3', 'control'), ('p3', 'integrated'), ('p3', 'original')]
REPS = ('p1', 'p2', 'p3')
HIST_EDGES_MS = [0, 16.7, 33.3, 50, 66.7, 83.3, 100, 125, 150, 200, 300, 500, 1000, float('inf')]
CANDIDATES = {
    'TASK-279': {'name': 'far-background-stack cache (base gradient + far tile + haze painted once, tiled at the x shift)',
                 'decision': 'artifacts/TASK-279/decision.json', 'candidate': 'tools/y8_background_stack_candidate.js',
                 'markers': ('farStack', 'buildFarStack', 'drawFarStack'), 'region': 'BackgroundRenderer.paint / paintMenu'},
    'TASK-280': {'name': 'glow composite clipped to the union of dilated primitive rectangles instead of their bounding box',
                 'decision': 'artifacts/TASK-280/decision.json', 'candidate': 'tools/y8_glow_region_candidate.js',
                 'markers': gr.CANDIDATE_MARKERS, 'region': 'render/effects.js top block (TASK-265 geometry clip -> TASK-280 body)'},
    'TASK-281': {'name': 'transparent-row clip of the cave background tile copies (Path2D clip per tile copy)',
                 'decision': 'artifacts/TASK-281/decision.json', 'candidate': 'tools/y8_background_rows_candidate.js',
                 'markers': ('getLayerContentRows', 'contentRows'), 'region': 'BackgroundRenderer.drawLayerTile tile copies (drawLayerTile itself is a shipped method)'},
}
SEALED_COSTS = {  # ms per frame at 1280x720 dpr1, from the sealed decisions named in each entry
    'glow composite (ambient chain)': {'bad': 38.77, 'classic': 49.25, 'source': 'TASK-276 ranked_stage_arms composite-off median saving',
                                       'lever': 'TASK-280 region clip ACCEPTED and integrated (this ticket measures the combined effect); '
                                                'coarse levels 2-3 stay full-frame (dilation doubles per level)'},
    'cave background (6 full-frame passes)': {'bad': 15.93, 'classic': 24.77, 'source': 'TASK-273 feature-off median saving; TASK-277 22-25 ms stationary (24 % of the frame)',
                                              'lever': 'TASK-279 reuse REJECTED (gradient dither / transform drift); TASK-281 row clip REJECTED (immaterial); '
                                                       'no exact lever left before the bad-mode base-transform drift is fixed'},
    'obstacle lighting': {'bad': 15.86, 'classic': -1.08, 'source': 'TASK-273 feature-off saving (Main only; Chill NO_BENEFIT)',
                          'lever': 'untested as a single ticket: cannot reach 5 % in Chill'},
    'player glow chain': {'bad': 3.49, 'classic': 16.44, 'source': 'TASK-276 composite-off (bad WITHIN_NOISE, classic CONSISTENT_SAVING)',
                          'lever': 'covered by the TASK-280 clip (player chain clip/box 0.68-1.0)'},
    'world geometry': {'bad': 6.26, 'classic': 5.35, 'source': 'TASK-273 feature-off saving', 'lever': 'whole layer <= 6 %: no partial exact reduction can pass'},
    'player trail': {'bad': 7.37, 'classic': 3.26, 'source': 'TASK-273/278 (within noise in both modes)', 'lever': 'none'},
    'particles': {'bad': 3.37, 'classic': -7.35, 'source': 'TASK-273/278 (within noise)', 'lever': 'none'},
    'hud': {'bad': -4.89, 'classic': 1.59, 'source': 'TASK-273/278 (within noise)', 'lever': 'none'},
    'simulation (physics JS) + GC': {'bad': 0.83, 'classic': 0.71, 'source': 'TASK-278 profile JS span + trace GC pauses (0.8 % of the frame)',
                                     'lever': 'not material'},
}


def utc():
    return fc.utc()


def preserve_module(out):
    folder = Path(out) / 'module-at-capture'
    folder.mkdir(parents=True, exist_ok=True)
    digest = fc.sha_file(MODULE)
    target = folder / f'{MODULE.stem}-{digest[:8]}{MODULE.suffix}'
    if not target.exists():
        shutil.copyfile(MODULE, target)
    return digest


def receipt(out, label, argv, exit_code, t0, t1):
    line = {'label': label, 'argv': argv, 'utc_start': t0, 'utc_end': t1, 'exit_code': exit_code}
    with open(Path(out) / 'commands.jsonl', 'a') as f:
        f.write(json.dumps(line) + '\n')
    return line


def commands_seal(out, lines):
    """sha256 of the first `lines` receipts: later report/audit receipts append to commands.jsonl after the manifest is written."""
    text = (Path(out) / 'commands.jsonl').read_text().splitlines()[:lines]
    return fc.sha_bytes(('\n'.join(text) + '\n').encode())


def run_cmd(out, label, argv):
    t0 = utc()
    r = subprocess.run(argv, cwd=ROOT)
    return receipt(out, label, argv, r.returncode, t0, utc())


# ------------------------------------------------------------- prepare --

def build_trees(out):
    trees = Path(out) / 'trees'
    head = fc.git('rev-parse', 'HEAD')
    dirty = fc.git('status', '--porcelain', '--untracked-files=no')
    integrated = trees / 'integrated'
    if integrated.exists():
        shutil.rmtree(integrated)
    integrated.mkdir(parents=True)
    tar = subprocess.check_output(['git', 'archive', '--format=tar', head], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(integrated, filter='data')
    for name in fc.runtime_files(integrated):
        if (ROOT / name).read_bytes() != (integrated / name).read_bytes():
            raise fc.EvidenceError(f'worktree runtime differs from HEAD: {name}')
    control_manifest = fc.load(CONTROL_TASK_DIR / 'manifest.json')
    control_src = CONTROL_TASK_DIR / 'trees/current'
    if fc.tree_hashes(control_src) != control_manifest['candidate_hashes']['current_files_sha256']:
        raise fc.EvidenceError('TASK-271 current control tree no longer matches its manifest seal')
    control = trees / 'control'
    if control.exists():
        shutil.rmtree(control)
    shutil.copytree(control_src, control)
    if fc.sha_file(fc.ORIGINAL_ZIP) != fc.ORIGINAL_ZIP_SHA256:
        raise fc.EvidenceError('original ZIP changed')
    with zipfile.ZipFile(fc.ORIGINAL_ZIP) as z:
        members = {n: fc.sha_bytes(z.read(n)) for n in z.namelist() if not n.endswith('/')}
    original_src = CONTROL_TASK_DIR / 'trees/original'
    for name, digest in members.items():
        if fc.sha_file(original_src / name) != digest:
            raise fc.EvidenceError(f'TASK-271 original tree member {name} differs from the ZIP')
    original = trees / 'original'
    if original.exists():
        shutil.rmtree(original)
    shutil.copytree(original_src, original)
    return {'head': head, 'dirty_runtime': dirty, 'integrated_tar_sha256': fc.sha_bytes(tar),
            'control_commit': control_manifest['source_revision'], 'control_manifest_sha256': fc.sha_file(CONTROL_TASK_DIR / 'manifest.json'),
            'original_zip_sha256': fc.ORIGINAL_ZIP_SHA256, 'original_commit': fc.git('rev-parse', fc.ORIGINAL_COMMIT),
            'files_sha256': {t: fc.tree_hashes(trees / t) for t in TREES}, 'trees': {t: str(trees / t) for t in TREES}}


def runtime_diff(control_commit, head):
    names = fc.git('diff', '--name-only', control_commit, head, '--', '.', ':!tools', ':!artifacts').splitlines()
    files = []
    for name in names:
        patch = fc.git('diff', control_commit, head, '--', name)
        hunks = [l for l in patch.splitlines() if l.startswith('@@')]
        files.append({'file': name, 'hunks': hunks, 'patch_sha256': fc.sha_bytes(patch.encode()), 'patch_lines': len(patch.splitlines())})
    return {'control_commit': control_commit, 'head': head, 'changed_runtime_files': files,
            'tools_only_commits_between': fc.git('log', '--oneline', f'{control_commit}..{head}').splitlines()}


def candidate_map(identity):
    integrated_root = Path(identity['trees']['integrated'])
    control_root = Path(identity['trees']['control'])
    out = []
    for task, c in CANDIDATES.items():
        decision = fc.load(ROOT / c['decision'])
        src_int = (integrated_root / 'render/effects.js').read_text()
        src_ctl = (control_root / 'render/effects.js').read_text()
        present_int = {m: src_int.count(m) for m in c['markers']}
        present_ctl = {m: src_ctl.count(m) for m in c['markers']}
        entry = {'task': task, 'candidate': c['name'], 'candidate_file': c['candidate'],
                 'candidate_sha256': fc.sha_file(ROOT / c['candidate']) if (ROOT / c['candidate']).exists() else None,
                 'verdict': decision['verdict'], 'code_region': c['region'],
                 'markers_in_integrated_runtime': present_int, 'markers_in_control_runtime': present_ctl}
        if decision['verdict'] == 'ACCEPT':
            entry['integrated_body_sha256'] = gr.runtime_body_sha(integrated_root)
            entry['tested_body_sha256'] = decision['candidate']['body_sha256']
            entry['final_code'] = 'render/effects.js lines between the BEGIN/END TASK-280 candidate body markers'
            entry['in_final_code'] = entry['integrated_body_sha256'] == entry['tested_body_sha256'] and any(present_int.values())
            entry['consistent'] = entry['in_final_code']
        else:
            entry['final_code'] = 'none (rejected candidate never integrated)'
            entry['in_final_code'] = any(present_int.values())
            entry['consistent'] = not entry['in_final_code']
        out.append(entry)
    return out


def prepare(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    t0 = utc()
    identity = build_trees(out)
    diff = runtime_diff(identity['control_commit'], identity['head'])
    mapping = candidate_map(identity)
    accepted = [m for m in mapping if m['verdict'] == 'ACCEPT']
    changed = [f['file'] for f in diff['changed_runtime_files']]
    overlap = {'accepted_candidates': [m['task'] for m in accepted],
               'runtime_files_changed_control_to_integrated': changed,
               'overlapping_changes': 'none: a single accepted candidate (TASK-280) touches one region of render/effects.js (the top '
                                      'geometry-clip block); the rejected TASK-279/281 candidates targeted BackgroundRenderer and were never '
                                      'installed, so no two candidates edit the same code and no conflict resolution was needed',
               'only_effects_js_changed': changed == ['render/effects.js'],
               'combination_tested': 'control tree vs integrated tree, nothing injected, identity action (identity-visual.json)'}
    integration = {'task': TASK, 'utc': utc(), 'candidates': mapping, 'runtime_diff': diff, 'overlap': overlap,
                   'all_candidates_consistent_with_final_code': all(m['consistent'] for m in mapping),
                   'identity': 'pending (identity action)'}
    ident = {'task': TASK, 'utc_start': t0, 'utc_end': utc(), **identity,
             'harness_sha256': fc.sha_file(fc.HARNESS), 'glow_region_sha256': fc.sha_file(gr.MODULE), 'chill_sha256': fc.sha_file(ch.MODULE),
             'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py'), 'module_sha256': preserve_module(out),
             'tree_labels': TREE_LABELS,
             'environment_ceiling': fc.load(CONTROL_TASK_DIR / 'controls.json')['environment_ceiling'],
             'control_numbers_task271': {k: v['average_fps_per_window'] for k, v in fc.load(CONTROL_TASK_DIR / 'controls.json')['arms'].items()}}
    fc.dump(out / 'identity.json', ident)
    fc.dump(out / 'integration.json', integration)
    print('PASS prepare: head', identity['head'][:12], 'control', identity['control_commit'][:12], 'changed runtime files', changed,
          'candidates consistent', integration['all_candidates_consistent_with_final_code'], flush=True)
    return 0 if integration['all_candidates_consistent_with_final_code'] else 1


# ------------------------------------------------------------ identity --

def identity_plan(engines=None):
    plan = []
    for engine, e in gr.VISUAL_ENGINES.items():
        if engines and engine not in engines:
            continue
        for context in e['contexts']:
            c = gr.VISUAL_CONTEXTS[context]
            for seed in e.get('seeds', c['seeds']):
                for mode in MODES:
                    for tree in ('control', 'integrated'):
                        plan.append({'engine': engine, 'context': context, 'seed': seed, 'mode': mode, 'tree': tree})
    return plan


def identity_case(p):
    return f"identity-{p['engine']}-{p['context']}-{p['mode']}-seed{p['seed']}-{p['tree']}"


def identity_session(out, root, p):
    """TASK-280 visual protocol on one tree with nothing injected; raw written to identity/<case>.json."""
    context = gr.VISUAL_CONTEXTS[p['context']]
    style = gr.MODE_SETUP[p['mode']]['replay_style'] if p['seed'] == gr.MODE_SETUP[p['mode']]['seed'] else 'screening'
    replay = ch.replay_script(p['seed'], gr.PROFILE, 60000, style)
    case = identity_case(p)
    raw = {'case': case, 'task': TASK, 'argv': sys.argv, 'started_utc': utc(), 'tree': {'name': p['tree'], 'root': str(root), 'files_sha256': fc.tree_hashes(root)},
           'tree_has_candidate_methods': gr.runtime_has_candidate(root), 'runtime_body_sha256': gr.runtime_body_sha(root),
           'harness_sha256': fc.sha_file(fc.HARNESS), 'glow_region_sha256': fc.sha_file(gr.MODULE), 'chill_sha256': fc.sha_file(ch.MODULE),
           'module_sha256': preserve_module(out),
           'settings': {'pass': 'identity', 'engine': p['engine'], 'context': p['context'], 'viewport': context['viewport'], 'dpr': context['dpr'],
                        'mode': p['mode'], 'seed': p['seed'], 'tree': p['tree'], 'tree_label': TREE_LABELS[p['tree']], 'replay_style': style,
                        'replay_sha256': fc.replay_sha256(replay), 'injected': 'nothing (no candidate install; the runtime of the tree is what runs)',
                        'clock': 'synthetic 60 Hz rAF timestamps, performance.now pinned; rAF cancelled, gameLoop driven by the harness',
                        'checkpoints': context['checkpoints'], 'shake_at': context['shake_at'], 'resizes': context['resizes'],
                        'frames_after_resize': context['frames_after_resize'],
                        'readback': 'canvas.toDataURL(image/png) of the game canvas (final) and of every glow level canvas (source), this pass only',
                        'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter'},
           'replay': replay, 'checkpoints': [], 'resizes': [], 'network': [], 'errors': [], 'console_errors': []}
    cfg = {'dpr': context['dpr'], 'input': 'mouse', 'ablate': [], 'diagnostic': True, 'replay': replay, 'warmup_ms': 0, 'window_ms': 10 ** 7, 'windows': 1}
    pngs = {}

    def checkpoint(page, name, scene):
        r = page.evaluate(gr.VISUAL_CHECKPOINT, {'scene': scene})
        png = gr.png_bytes(r['png'])
        levels = {k: [gr.png_bytes(u) for u in v] for k, v in r['levels'].items()}
        level_pixels = {k: [gr.pixels_sha(b) for b in v] for k, v in levels.items()}
        entry = {'name': name, 'scene': scene, 'final_sha256': fc.sha_bytes(png), 'final_pixels_sha256': gr.pixels_sha(png), 'final_bytes': len(png),
                 'source_levels_pixels_sha256': level_pixels,
                 'source_pixels_sha256': fc.sha_bytes(json.dumps(level_pixels, sort_keys=True).encode()),
                 'state': r['state'], 'candidate': r['candidate']}
        pngs[name] = (png, levels)
        raw['checkpoints'].append(entry)

    with ExitStack() as stack:
        page = gr.open_page(stack, root, raw, context['viewport'], context['dpr'], p['seed'], p['engine'])
        page.evaluate(fc.INSTRUMENT, cfg)
        page.evaluate('() => cancelAnimationFrame(game)')
        raw['begin'] = page.evaluate(gr.VISUAL_BEGIN, {'arm': p['tree']})
        raw['candidate_global_present'] = page.evaluate(gr.CANDIDATE_PRESENT)
        page.evaluate(gr.VISUAL_STEP, 2)
        checkpoint(page, 'menu', 'menu')
        raw['started_version'] = page.evaluate(gr.VISUAL_START, p['mode'])
        frame = 0
        for name, target in context['checkpoints']:
            if frame < context['shake_at'] <= target:
                page.evaluate(gr.VISUAL_STEP, context['shake_at'] - frame)
                frame = context['shake_at']
                raw['shake_until'] = page.evaluate(gr.VISUAL_SHAKE)
            page.evaluate(gr.VISUAL_STEP, target - frame)
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
            page.evaluate(gr.VISUAL_STEP, context['frames_after_resize'])
            dims = page.evaluate(fc.DIMENSIONS)
            raw['resizes'].append({'requested': size, 'before': before, 'handler_seen': handler_seen, 'wait_ms': round((time.time() - t0) * 1000), 'dimensions': dims})
            checkpoint(page, f'resize-{size[0]}x{size[1]}', 'game')
        raw.update(page.evaluate(gr.VISUAL_SAMPLES))
        raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
        raw['candidate_global_present_end'] = page.evaluate(gr.CANDIDATE_PRESENT)
        raw['ended_utc'] = utc()
    raw['result'] = 'COMPLETE' if not raw['errors'] else 'FAILED: page errors ' + json.dumps(raw['errors'])[:300]
    if raw['dimensions']['platform'] not in ('disabled', 'absent'):
        raw['result'] = 'FAILED: SDK isolation ' + str(raw['dimensions']['platform'])
    expect_candidate = p['tree'] == 'integrated'
    if raw['result'] == 'COMPLETE' and bool(raw['candidate_global_present_end']) != expect_candidate:
        raw['result'] = f"FAILED: TASK-280 body global present={raw['candidate_global_present_end']} in the {p['tree']} tree"
    if raw['result'] == 'COMPLETE' and expect_candidate and not raw.get('regionCalls'):
        raw['result'] = 'FAILED: integrated body never ran its composite hook'
    path = gr.unique_path(out / 'identity', case, '.json')
    fc.dump(path, raw)
    print('PASS' if raw['result'] == 'COMPLETE' else 'FAIL', case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path, raw['result'],
          'checkpoints', len(raw['checkpoints']), 'regionCalls', raw.get('regionCalls'), 'frames', raw['checkpoints'][-1]['state']['frame'] if raw['checkpoints'] else None, flush=True)
    return raw, pngs


def identity(args):
    out = Path(args.output).resolve()
    ident = fc.load(out / 'identity.json')
    plan = identity_plan(args.engines)
    if args.only:
        plan = [p for p in plan if identity_case(p) in args.only]
    status, results = 0, {}
    for p in plan:
        root = Path(ident['trees'][p['tree']])
        try:
            raw, pngs = identity_session(out, root, p)
        except Exception as e:  # engine unavailable or crashed: preserve the failure
            fail = {'case': identity_case(p), 'task': TASK, 'argv': sys.argv, 'started_utc': utc(), 'ended_utc': utc(),
                    'settings': {'pass': 'identity', **p}, 'result': 'FAILED: ' + str(e).splitlines()[0][:300], 'checkpoints': []}
            fc.dump(gr.unique_path(out / 'identity', identity_case(p), '.json'), fail)
            print('FAIL', identity_case(p), fail['result'], flush=True)
            if p['engine'] == 'chromium':
                status = 1
            continue
        if raw['result'] != 'COMPLETE' and p['engine'] == 'chromium':
            status = 1
        key = (p['engine'], p['context'], p['mode'], p['seed'])
        results.setdefault(key, {})[p['tree']] = (raw, pngs)
        cell = results[key]
        if 'control' in cell and 'integrated' in cell:  # keep the PNG pair of every mismatch (evidence of a conflict)
            for a, b in zip(cell['control'][0]['checkpoints'], cell['integrated'][0]['checkpoints']):
                if not gr.pixels_equal(a, b, 'final') or not gr.pixels_equal(a, b, 'source'):
                    gr.save_png(out, identity_case(dict(p, tree='control')), a['name'], cell['control'][1].get(a['name']), levels=True)
                    gr.save_png(out, identity_case(dict(p, tree='integrated')), b['name'], cell['integrated'][1].get(b['name']), levels=True)
    return status


# ------------------------------------------------------------- capture --

# The original ZIP (b588d69) shows its "Continue?" offer after a lethal death once score >= CONTINUE_MIN_SCORE even
# with the SDK blocked and freezes physics until answered (TASK-275 finding); every later tree restarts instantly.
# Page-only shim (same as tools/y8_feature_history.py): restartFromOffer() on the first frame the offer is visible,
# so the original arm keeps the instant-restart segment of the other arms. Installed on the original tree only.
OFFER_SHIM = '''() => {
    const FC = window.__featureCost
    FC.offerRestarts = []
    FC.offerShim = (typeof continueOffer !== 'undefined' && typeof restartFromOffer === 'function')
        ? 'installed: restartFromOffer() on the first frame continueOffer.visible (page only)' : 'not applicable'
    const inner = window.gameLoop
    window.gameLoop = function(t) {
        if (typeof continueOffer !== 'undefined' && continueOffer.visible && typeof restartFromOffer === 'function') {
            FC.offerRestarts.push({t, activeMs: Math.round(FC.activeMs * 10) / 10,
                score: (typeof scoreText !== 'undefined' && scoreText.count) ? scoreText.count[version] : null})
            restartFromOffer()
        }
        return inner.call(this, t)
    }
}'''


def capture_tree(root, out, mode, case, profile, cpu_throttle=1, offer_shim=True, timeout_ms=240000):
    """fc.capture (TASK-271 harness, unchanged) with the offer shim installed after INSTRUMENT: original tree only."""
    from browser_test_support import start_browser_test
    root = Path(root).resolve()
    prof = fc.PROFILES[profile]
    total = WARMUP_MS + WINDOWS * WINDOW_MS
    replay = fc.replay_script(SEED, profile, total + 1000)
    settings = {'mode': mode, 'profile': profile, 'viewport': prof['viewport'], 'dpr': prof['dpr'], 'is_mobile': prof['is_mobile'],
                'has_touch': prof['has_touch'], 'input': prof['input'], 'cpu_throttle': cpu_throttle, 'seed': SEED, 'warmup_ms': WARMUP_MS,
                'window_ms': WINDOW_MS, 'windows': WINDOWS, 'replay_sha256': fc.replay_sha256(replay), 'ablate': [], 'diagnostic': False,
                'offer_shim': bool(offer_shim), 'density': 'pinned to profile DPR; adaptive observe disabled',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                                 'PLATFORM falls back to the local adapter (no ads, instant restart on death)'}
    cfg = {'dpr': prof['dpr'], 'input': prof['input'], 'ablate': [], 'diagnostic': False, 'replay': replay,
           'warmup_ms': WARMUP_MS, 'window_ms': WINDOW_MS, 'windows': WINDOWS}
    raw = {'case': case, 'settings': settings, 'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root)},
           'harness_sha256': fc.sha_file(fc.HARNESS), 'capture_module_sha256': fc.sha_file(MODULE), 'module_sha256': preserve_module(out),
           'argv': sys.argv, 'started_utc': utc(),
           'replay': replay, 'network': [], 'errors': [], 'console_errors': [], 'offerRestarts': [], 'offerShim': 'not requested'}
    network, exit_code = raw['network'], 1
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        raw['environment'] = fc.environment(browser)
        ctx = fc.new_context(browser, profile, SEED, network)
        stack.callback(ctx.close)
        page = ctx.new_page()
        page.on('pageerror', lambda e: raw['errors'].append(str(e)))
        page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
        ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': cpu_throttle})
        page.goto(url + 'index.html', wait_until='domcontentloaded')
        page.wait_for_function(fc.BOOTED, timeout=60000)
        page.evaluate(fc.INSTRUMENT, cfg)
        if offer_shim:
            page.evaluate(OFFER_SHIM)
        page.evaluate('mode => startGame(mode)', mode)
        try:
            page.wait_for_function(f'{fc.MARKER}.done || {fc.MARKER}.error', timeout=timeout_ms)
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
        if raw['dimensions']['version'] != mode:
            raise fc.EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
        if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
            raise fc.EvidenceError('backing size changed during the capture')
        raw['summary'] = fc.summarize(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except fc.EvidenceError as e:
        raw['summary'], raw['result'] = None, 'FAILED: ' + str(e)
    path = fc.raw_path(out, case)
    fc.dump(path, raw)
    c = raw['summary']['combined'] if raw['summary'] else None
    print(('PASS' if exit_code == 0 else 'FAIL'), case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path, raw['result'],
          'backing=' + str(raw['dimensions']['canvas']), 'offerRestarts=%d' % len(raw.get('offerRestarts') or []),
          'fps=%.2f p50=%.2f p95=%.2f p99=%.2f max=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'], c['frame_ms']['p99'], c['frame_ms']['max'], c['active_ms'],
              raw['summary']['deaths']) if c else '', flush=True)
    return exit_code


def case_name(profile, mode, rep, tree, index):
    return f'{profile}-{mode}-{rep}-{tree}-i{index}'


def capture(args):
    out = Path(args.output).resolve()
    ident = fc.load(out / 'identity.json')
    if args.tree == 'original':
        t0 = utc()
        code = capture_tree(ident['trees']['original'], out, args.mode, args.case, args.profile, args.cpu_throttle, offer_shim=True)
        receipt(out, f'capture {args.case} (in-process fc.capture + offer shim)', sys.argv, code, t0, utc())
        return code
    argv = [sys.executable, 'tools/y8_feature_cost.py', 'capture', '--root', ident['trees'][args.tree], '--output', str(out),
            '--mode', args.mode, '--seed', str(SEED), '--case', args.case, '--profile', args.profile, '--windows', str(WINDOWS),
            '--window-ms', str(WINDOW_MS), '--warmup-ms', str(WARMUP_MS), '--cpu-throttle', str(args.cpu_throttle)]
    return run_cmd(out, f'capture {args.case}', argv)['exit_code']


def run(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    me = [sys.executable, str(MODULE.relative_to(ROOT))]
    status = 0
    if not args.skip_prepare:
        status |= run_cmd(out, 'prepare', me + ['prepare', '--output', str(out)])['exit_code']
    if not args.skip_identity:
        argv = me + ['identity', '--output', str(out)] + (['--engines', *args.engines] if args.engines else [])
        status |= run_cmd(out, 'identity', argv)['exit_code']
    if not args.skip_timing:
        index = 0
        for profile in PROFILES:
            for mode in MODES:
                for rep, tree in SEQUENCE:
                    index += 1
                    case = case_name(profile, mode, rep, tree, index)
                    if args.resume and complete_latest(load_dir(out, 'raw'), case):
                        print('SKIP (resume) complete raw exists for', case, flush=True)
                        continue
                    argv = me + ['capture', '--output', str(out), '--profile', profile, '--mode', mode, '--tree', tree, '--case', case,
                                 '--cpu-throttle', str(args.cpu_throttle)]
                    status |= run_cmd(out, f'capture {case}', argv)['exit_code']
    status |= run_cmd(out, 'report', me + ['report', '--output', str(out)])['exit_code']
    status |= run_cmd(out, 'audit', me + ['audit', '--output', str(out)])['exit_code']
    print('run exit', status, flush=True)
    return status


# -------------------------------------------------------------- report --

def load_dir(out, sub):
    folder = Path(out) / sub
    return {f'{sub}/{p.name}': fc.load(p) for p in sorted(folder.glob('*.json'))} if folder.exists() else {}


def complete_latest(raws, case):
    """Latest complete raw of a case (by started_utc); failed attempts stay on disk."""
    found = [r for r in raws.values() if r.get('case') == case and r.get('result') == 'COMPLETE']
    return max(found, key=lambda r: r['started_utc']) if found else None


def build_identity_report(out):
    raws = load_dir(out, 'identity')
    cells = {}
    for p in identity_plan():
        key = f"{p['engine']}/{p['context']}/{p['mode']}/seed{p['seed']}"
        cells.setdefault(key, {})[p['tree']] = complete_latest(raws, identity_case(p))
    report = {}
    for key, pair in cells.items():
        c, i = pair.get('control'), pair.get('integrated')
        if not c or not i:
            report[key] = {'result': 'MISSING', 'control': bool(c), 'integrated': bool(i)}
            continue
        checkpoints = []
        for a, b in zip(c['checkpoints'], i['checkpoints']):
            sa, sb = {k: a['state'].get(k) for k in gr.STATE_KEYS}, {k: b['state'].get(k) for k in gr.STATE_KEYS}
            checkpoints.append({'name': a['name'], 'final_equal': a['final_pixels_sha256'] == b['final_pixels_sha256'],
                                'source_equal': a['source_pixels_sha256'] == b['source_pixels_sha256'],
                                'state_equal': sa == sb, 'random_draws_equal': a['state']['randomDraws'] == b['state']['randomDraws'],
                                'backing': a['state']['canvas'], 'screen': a['state']['screen'],
                                'differing_state_keys': sorted(k for k in gr.STATE_KEYS if sa.get(k) != sb.get(k)),
                                'control_body_global': a['candidate']['present'], 'integrated_body_global': b['candidate']['present']})
        same_count = len(c['checkpoints']) == len(i['checkpoints']) and len(checkpoints) > 0
        exact = same_count and all(x['final_equal'] and x['source_equal'] and x['state_equal'] and x['random_draws_equal'] for x in checkpoints)
        report[key] = {'result': 'EXACT' if exact else 'DIFFERENT', 'checkpoints': checkpoints, 'checkpoint_count': len(checkpoints),
                       'replay_sha256_equal': c['settings']['replay_sha256'] == i['settings']['replay_sha256'],
                       'control_region_calls': c.get('regionCalls'), 'integrated_region_calls': i.get('regionCalls'),
                       'integrated_body_sha256': i.get('runtime_body_sha256'), 'control_body_sha256': c.get('runtime_body_sha256'),
                       'raw': {'control': next(k for k, v in raws.items() if v is c), 'integrated': next(k for k, v in raws.items() if v is i)}}
    complete = [v for v in report.values() if v['result'] in ('EXACT', 'DIFFERENT')]
    return {'task': TASK, 'utc': utc(), 'comparison_unit': 'decoded RGBA pixels of the final canvas and of every glow level texture; '
                                                            f'{len(gr.STATE_KEYS)}-key state digest; Math.random draw count',
            'cells': report, 'cell_count': len(report), 'complete_cells': len(complete),
            'exact_cells': sum(1 for v in complete if v['result'] == 'EXACT'),
            'complete_matrix': all(v['result'] in ('EXACT', 'DIFFERENT') for v in report.values()),
            'exact_on_all_tested_engines': bool(complete) and all(v['result'] == 'EXACT' for v in complete)
            and all(v['result'] != 'MISSING' for k, v in report.items() if k.startswith('chromium')),
            'checkpoints_total': sum(v.get('checkpoint_count', 0) for v in complete),
            'failed_attempts': sorted(k for k, r in raws.items() if r.get('result') != 'COMPLETE')}


def histogram(dts):
    counts = [0] * (len(HIST_EDGES_MS) - 1)
    for d in dts:
        for k in range(len(counts)):
            if HIST_EDGES_MS[k] <= d < HIST_EDGES_MS[k + 1]:
                counts[k] += 1
                break
    return {'edges_ms': [e if e != float('inf') else 'inf' for e in HIST_EDGES_MS], 'counts': counts}


def run_record(raw):
    s = raw['summary']
    c = s['combined']
    dts = [f['dt'] for w in fc.split_windows(raw['frames'], raw['settings']['warmup_ms'], raw['settings']['window_ms'], raw['settings']['windows'])
           for f in w[1:] if f['dt'] is not None]
    ordered = sorted(dts)
    windows = [{'average_fps': w['average_fps'], 'mean_ms': w['active_ms'] / w['intervals'], 'p50_ms': w['frame_ms']['p50'], 'p95_ms': w['frame_ms']['p95'],
                'max_ms': w['frame_ms']['max'], 'intervals': w['intervals'], 'active_ms': w['active_ms']} for w in s['windows']]
    return {'case': raw['case'], 'tree': raw['case'].split('-')[3], 'started_utc': raw['started_utc'], 'backing': raw['dimensions']['canvas'],
            'density_pin': raw['densityPin'], 'intervals': c['intervals'], 'active_ms': c['active_ms'], 'wall_ms': c['wall_ms'], 'gaps': c['gaps'],
            'average_fps': c['average_fps'], 'mean_ms': c['active_ms'] / c['intervals'],
            'frame_ms': {'min': ordered[0], 'p50': c['frame_ms']['p50'], 'p95': c['frame_ms']['p95'], 'p99': c['frame_ms']['p99'], 'max': c['frame_ms']['max'],
                         'stdev': statistics.pstdev(dts) if len(dts) > 1 else 0.0},
            'distribution': histogram(dts), 'windows_10s': windows,
            'min_10s_fps': min(w['average_fps'] for w in windows), 'max_10s_mean_ms': max(w['mean_ms'] for w in windows),
            'deaths': s['deaths'], 'dispatched_inputs': s['dispatched_inputs'], 'excluded_frames': s['excluded_frames'],
            'offer_shim': raw['settings'].get('offer_shim', False), 'offer_restarts': len(raw.get('offerRestarts') or []),
            'features': raw.get('features'), 'replay_sha256': raw['settings']['replay_sha256']}


def pair(a, b, label):
    """b (integrated) against a (control or original); positive reduction = integrated faster."""
    fc.compare(a, b)  # refuses mismatched settings or unequal backing sizes
    ra, rb = run_record(a), run_record(b)
    return {'reference': label, 'reference_case': a['case'], 'integrated_case': b['case'],
            'order': 'reference first' if a['started_utc'] < b['started_utc'] else 'integrated first',
            'backing': a['dimensions']['canvas'], 'reference_mean_ms': ra['mean_ms'], 'integrated_mean_ms': rb['mean_ms'],
            'reference_fps': ra['average_fps'], 'integrated_fps': rb['average_fps'],
            'reference_min_10s_fps': ra['min_10s_fps'], 'integrated_min_10s_fps': rb['min_10s_fps'],
            'reduction_ms': ra['mean_ms'] - rb['mean_ms'], 'reduction_fraction': (ra['mean_ms'] - rb['mean_ms']) / ra['mean_ms'],
            'worse_by_fraction': max(0.0, (rb['mean_ms'] - ra['mean_ms']) / ra['mean_ms']),
            'delta_fps': rb['average_fps'] - ra['average_fps'], 'delta_p50_ms': rb['frame_ms']['p50'] - ra['frame_ms']['p50'],
            'delta_p95_ms': rb['frame_ms']['p95'] - ra['frame_ms']['p95'],
            'reference_deaths': ra['deaths'], 'integrated_deaths': rb['deaths'], 'window_active_ms': [ra['active_ms'], rb['active_ms']]}


def build_comparison(out):
    raws = load_dir(out, 'raw')
    cells = {}
    for profile in PROFILES:
        for mode in MODES:
            runs = {t: [] for t in TREES}
            index_of = {}
            k = 0
            for p_ in PROFILES:
                for m_ in MODES:
                    for rep, tree in SEQUENCE:
                        k += 1
                        if (p_, m_) == (profile, mode):
                            index_of[(rep, tree)] = k
            by_rep = {}
            for (rep, tree), idx in index_of.items():
                r = complete_latest(raws, case_name(profile, mode, rep, tree, idx))
                if r:
                    runs[tree].append(run_record(r))
                    by_rep.setdefault(rep, {})[tree] = r
            pairs_control, pairs_original = [], []
            for rep in REPS:
                trio = by_rep.get(rep, {})
                if 'integrated' in trio and 'control' in trio:
                    pairs_control.append(dict(pair(trio['control'], trio['integrated'], 'control'), rep=rep))
                if 'integrated' in trio and 'original' in trio:
                    pairs_original.append(dict(pair(trio['original'], trio['integrated'], 'original'), rep=rep))

            def summary(pairs):
                if not pairs:
                    return None
                red = [p['reduction_fraction'] for p in pairs]
                return {'pair_count': len(pairs), 'median_reduction_fraction': statistics.median(red), 'all_reductions_fraction': red,
                        'median_reduction_ms': statistics.median(p['reduction_ms'] for p in pairs),
                        'max_worse_fraction': max(p['worse_by_fraction'] for p in pairs),
                        'median_reference_mean_ms': statistics.median(p['reference_mean_ms'] for p in pairs),
                        'median_integrated_mean_ms': statistics.median(p['integrated_mean_ms'] for p in pairs),
                        'median_reference_fps': statistics.median(p['reference_fps'] for p in pairs),
                        'median_integrated_fps': statistics.median(p['integrated_fps'] for p in pairs),
                        'min_10s_fps_reference': min(p['reference_min_10s_fps'] for p in pairs),
                        'min_10s_fps_integrated': min(p['integrated_min_10s_fps'] for p in pairs),
                        'orders': [p['order'] for p in pairs]}
            backing = sorted({tuple(r['backing']) for t in TREES for r in runs[t]})
            vs_c, vs_o = summary(pairs_control), summary(pairs_original)
            complete = all(len(runs[t]) == len(REPS) for t in TREES)
            cells[f'{profile}/{mode}'] = {
                'profile': profile, 'mode': mode, 'mode_name': ch.MODE_NAMES[mode], 'viewport': fc.PROFILES[profile]['viewport'], 'dpr': fc.PROFILES[profile]['dpr'],
                'backing': backing, 'equal_backing_all_runs': len(backing) == 1, 'complete': complete,
                'runs': runs, 'pairs_vs_control': pairs_control, 'pairs_vs_original': pairs_original,
                'vs_control': vs_c, 'vs_original': vs_o,
                'verdict_vs_control': None if not vs_c or vs_c['pair_count'] < len(REPS) else (
                    'FASTER' if vs_c['median_reduction_fraction'] >= gr.MIN_MEDIAN_REDUCTION and vs_c['max_worse_fraction'] <= gr.MAX_WORSE else
                    'WITHIN_NOISE' if vs_c['max_worse_fraction'] <= gr.MAX_WORSE else 'INCONSISTENT'),
                'deficit_vs_original': None if not vs_o else {
                    'integrated_minus_original_ms_median': -vs_o['median_reduction_ms'],
                    'integrated_over_original_frame_time_ratio': vs_o['median_integrated_mean_ms'] / vs_o['median_reference_mean_ms'],
                    'integrated_slower_than_original': vs_o['median_reduction_fraction'] < 0}}
    all_pairs = [p for c in cells.values() for p in c['pairs_vs_control'] + c['pairs_vs_original']]
    return {'task': TASK, 'utc': utc(), 'harness': 'tools/y8_feature_cost.py capture (unchanged TASK-271 harness)',
            'protocol': {'profiles': {p: fc.PROFILES[p] for p in PROFILES}, 'modes': list(MODES), 'seed': SEED, 'warmup_ms': WARMUP_MS,
                         'window_ms': WINDOW_MS, 'windows_per_capture': WINDOWS, 'measured_ms_per_capture': WINDOW_MS * WINDOWS,
                         'sequence_per_cell': SEQUENCE, 'cpu_throttle': sorted({r['settings']['cpu_throttle'] for r in raws.values() if 'settings' in r}),
                         'pairs': 'per cell three alternating 30 s pairs integrated-vs-control (reps p1 control first, p2 integrated first, p3 control '
                                  'first) and three alternating 30 s pairs integrated-vs-original (p1 integrated first, p2 original first, p3 '
                                  'integrated first); the integrated arm is captured once per rep and used in both pairs',
                         'density': 'pinned to the profile DPR in every tree with RENDER_BUDGET (integrated, control); the original ZIP has no '
                                    'RENDER_BUDGET and uses devicePixelRatio; backing size recorded per frame and asserted equal in every pair',
                         'input': 'replay_script(seed 4, profile, 36 s) scheduled on the active clock; mouse on desktop, TouchEvents on touch',
                         'offer_shim': 'original tree only: page-only restartFromOffer() on the first frame its Continue? offer is visible (the ZIP '
                                       'freezes physics on the offer without an SDK; later trees restart instantly); the three desktop/bad original '
                                       'captures that completed before the shim was added had no offer frames (excluded_frames 0) and are kept',
                         'metric': 'mean active frame ms = active_ms / intervals over the three 10 s windows (30 s); 10 s minima = the lowest '
                                   'average FPS of the three windows; distribution = fixed-edge histogram of the active intervals',
                         'windows': 'split_windows (TASK-271 harness) cuts at frame boundaries on cumulative 10 s targets from the warmup end: '
                                    'the three windows together hold >= 30 s of active intervals, each one 10 s +- one frame interval',
                         'rule_vs_control': f'FASTER iff median reduction over the 3 pairs >= {gr.MIN_MEDIAN_REDUCTION:.0%} and no pair worse by '
                                            f'> {gr.MAX_WORSE:.0%} (the TASK-280 rule); WITHIN_NOISE when no pair is worse by > 5 % but the median '
                                            f'misses 5 %; INCONSISTENT otherwise; modes/profiles never pooled',
                         'adaptive_density': 'disabled in every arm (observe() -> false, densityLimit = profile DPR): no adaptive-density '
                                             'recovery can appear in these numbers; any FPS gain is at equal backing size',
                         'limits': 'software headless Chromium (SwiftShader); the camera never moves in bad mode or at dpr2 under this replay '
                                   '(physics-step cap); no 60 FPS, device or release-readiness claim'},
            'cells': cells, 'raw_count': len(raws), 'complete_count': sum(1 for r in raws.values() if r.get('result') == 'COMPLETE'),
            'failed_attempts': sorted(k for k, r in raws.items() if r.get('result') != 'COMPLETE'),
            'all_pairs_equal_backing': all(p['backing'] for p in all_pairs),
            'complete_matrix': all(c['complete'] for c in cells.values()),
            'result': 'COMPLETE' if all(c['complete'] for c in cells.values()) else 'INCOMPLETE'}


def build_cost_ranking(comparison, identity_report):
    cells = comparison['cells']
    ranking = {}
    for mode in MODES:
        desk = cells.get(f'desktop/{mode}', {})
        vs_c, vs_o = desk.get('vs_control'), desk.get('vs_original')
        integrated_ms = vs_c['median_integrated_mean_ms'] if vs_c else None
        control_ms = vs_c['median_reference_mean_ms'] if vs_c else None
        original_ms = vs_o['median_reference_mean_ms'] if vs_o else None
        measured_saving_ms = vs_c['median_reduction_ms'] if vs_c else None
        items = []
        for name, c in SEALED_COSTS.items():
            sealed = c[mode]
            remaining = sealed
            status = 'unchanged (sealed estimate)'
            if name.startswith('glow composite') and measured_saving_ms is not None:
                remaining = sealed - measured_saving_ms
                status = 'reduced by the integrated TASK-280 clip: sealed minus the measured combined saving of this ticket (estimate)'
            items.append({'subsystem': name, 'sealed_ms': sealed, 'sealed_source': c['source'], 'remaining_ms_estimate': remaining,
                          'fraction_of_integrated_frame': remaining / integrated_ms if integrated_ms else None, 'status': status, 'lever': c['lever']})
        items.sort(key=lambda x: -x['remaining_ms_estimate'])
        for n, it in enumerate(items, 1):
            it['rank'] = n
        touch = cells.get(f'touch/{mode}', {})
        ranking[mode] = {
            'mode_name': ch.MODE_NAMES[mode],
            'measured_desktop': {'integrated_mean_ms': integrated_ms, 'control_mean_ms': control_ms, 'original_mean_ms': original_ms,
                                 'integrated_fps': vs_c['median_integrated_fps'] if vs_c else None, 'control_fps': vs_c['median_reference_fps'] if vs_c else None,
                                 'original_fps': vs_o['median_reference_fps'] if vs_o else None,
                                 'saving_vs_control_ms': measured_saving_ms, 'saving_vs_control_fraction': vs_c['median_reduction_fraction'] if vs_c else None},
            'measured_touch': {'integrated_mean_ms': touch['vs_control']['median_integrated_mean_ms'] if touch.get('vs_control') else None,
                               'control_mean_ms': touch['vs_control']['median_reference_mean_ms'] if touch.get('vs_control') else None,
                               'original_mean_ms': touch['vs_original']['median_reference_mean_ms'] if touch.get('vs_original') else None,
                               'saving_vs_control_fraction': touch['vs_control']['median_reduction_fraction'] if touch.get('vs_control') else None,
                               'saving_vs_original_fraction': touch['vs_original']['median_reduction_fraction'] if touch.get('vs_original') else None},
            'remaining_deficits': {
                'vs_control_ms': (integrated_ms - control_ms) if integrated_ms and control_ms else None,
                'vs_original_ms': (integrated_ms - original_ms) if integrated_ms and original_ms else None,
                'vs_original_fraction_of_original': ((integrated_ms - original_ms) / original_ms) if integrated_ms and original_ms else None,
                'vs_environment_ceiling_ms': (integrated_ms - 1000 / 60) if integrated_ms else None,
                'reading': 'positive vs_original_ms = the integrated runtime still spends that much more per frame than the historical ZIP in this '
                           'environment; negative vs_control_ms = the integrated runtime is faster than the frozen current control'},
            'ranking': items,
            'statement': 'bottleneck ranking for the integrated result: the glow composite (reduced by TASK-280 but still first), the cave '
                         'background (TASK-279/281 rejected, no exact lever before the transform-drift fix), obstacle lighting (Main only), '
                         'then layers at or below the 5 % bar; CPU simulation and GC are not material (TASK-278)'}
    return {'task': TASK, 'utc': utc(), 'basis': 'sealed single-feature costs (TASK-273/276/277/278) at 1280x720 dpr1 combined with the '
                                                 'measured integrated/control/original frame times of this ticket (comparison.json)',
            'integrated_identity_exact': identity_report.get('exact_on_all_tested_engines'),
            'modes': ranking,
            'controls': {'frozen_current': 'artifacts/TASK-271 current control tree (commit ' + comparison.get('control_commit', '') + ')',
                         'historical_zip': 'artifacts/TASK-098/grapnelninja-y8.zip (commit b588d69)',
                         'task271_desktop_fps': comparison.get('task271_desktop_fps')},
            'not_claimed': ['60 FPS', 'release readiness', 'device results'],
            'diagnostic_completion': 'this ticket completes as a measured comparison; a remaining deficit relative to the ZIP is reported, not hidden, '
                                     'and no performance or release PASS is derived from it'}


def build_manifest(out, comparison, identity_report, integration):
    ident = fc.load(out / 'identity.json')
    commands = [json.loads(l) for l in (out / 'commands.jsonl').read_text().splitlines() if l.strip()] if (out / 'commands.jsonl').exists() else []
    raws, idents = load_dir(out, 'raw'), load_dir(out, 'identity')
    pngs = sorted(f'visual/png/{p.name}' for p in (out / 'visual/png').glob('*.png')) if (out / 'visual/png').exists() else []
    evidence = sorted(list(raws) + list(idents) + pngs + ['identity.json', 'commands.jsonl', 'integration.json', 'comparison.json', 'cost-ranking.json',
                                                           'identity-visual.json'] + sorted(f'module-at-capture/{p.name}' for p in (out / 'module-at-capture').glob('*')))
    evidence = [p for p in evidence if (out / p).exists()]
    everything = list(raws.values()) + list(idents.values())
    envs = [r['environment'] for r in everything if r.get('environment')]
    starts = [r['started_utc'] for r in everything] + [c['utc_start'] for c in commands] + [ident['utc_start']]
    ends = [r['ended_utc'] for r in everything if r.get('ended_utc')] + [c['utc_end'] for c in commands] + [ident['utc_end']]
    return {'task': TASK, 'generated_utc': utc(), 'utc_start': min(starts), 'utc_end': max(ends),
            'commands': [{k: c[k] for k in ('label', 'argv', 'utc_start', 'utc_end', 'exit_code')} for c in commands],
            'exit_codes': sorted({c['exit_code'] for c in commands}),
            'environment': next((e for e in envs if e.get('engine', 'chromium') == 'chromium'), envs[0] if envs else None),
            'environments_by_engine': {e.get('engine', 'chromium'): e for e in envs}, 'environment_ceiling': ident['environment_ceiling'],
            'source_revision': ident['head'], 'source_dirty_runtime': ident['dirty_runtime'], 'source_revision_at_report': fc.git('rev-parse', 'HEAD'),
            'control_commit': ident['control_commit'], 'original_commit': ident['original_commit'], 'original_zip_sha256': ident['original_zip_sha256'],
            'integrated_tar_sha256': ident['integrated_tar_sha256'], 'tree_files_sha256': ident['files_sha256'],
            'harness_sha256': ident['harness_sha256'], 'glow_region_sha256': ident['glow_region_sha256'], 'chill_sha256': ident['chill_sha256'],
            'support_sha256': ident['support_sha256'], 'module_sha256_at_report': fc.sha_file(MODULE),
            'module_sha256_at_capture': sorted({r[k] for r in everything for k in ('module_sha256', 'capture_module_sha256') if r.get(k)}),
            'module_at_capture': sorted(p.name for p in (out / 'module-at-capture').glob('*')),
            'candidate_hashes': {m['task']: {'candidate_sha256': m['candidate_sha256'], 'verdict': m['verdict'],
                                             'integrated_body_sha256': m.get('integrated_body_sha256')} for m in integration['candidates']},
            'runtime_body_sha256_at_report': gr.runtime_body_sha(ROOT),
            'fixed': {'timing': {'profiles': {p: fc.PROFILES[p] for p in PROFILES}, 'backing_size_by_case': {r['case']: r['dimensions']['canvas'] for r in raws.values() if r.get('dimensions')},
                                 'seed': SEED, 'warmup_ms': WARMUP_MS, 'window_ms': WINDOW_MS, 'windows': WINDOWS, 'sequence': SEQUENCE,
                                 'replay_sha256': sorted({r['settings']['replay_sha256'] for r in raws.values() if 'settings' in r}),
                                 'cpu_throttle': sorted({r['settings']['cpu_throttle'] for r in raws.values() if 'settings' in r}),
                                 'input': 'seeded replay on the active clock (mouse / TouchEvents)',
                                 'state': 'fresh page per capture, seeded Math.random, menu -> startGame(mode); per-frame menu/paused/offer/hidden/ad '
                                          'recorded, inactive frames excluded; deaths recorded via the reStart hook'},
                      'identity': {'contexts': gr.VISUAL_CONTEXTS, 'engines': gr.VISUAL_ENGINES, 'seeds': list(gr.VISUAL_SEEDS),
                                   'backing_size_by_case': {r['case']: sorted({tuple(c['state']['canvas']) for c in r.get('checkpoints', [])}) for r in idents.values() if r.get('checkpoints')},
                                   'clock': 'synthetic 60 Hz, performance.now pinned', 'input': 'seeded replay on the active clock',
                                   'state': 'fresh page per session; nothing injected; menu checkpoint, startGame(mode), harness-driven frames, forced '
                                            'triggerDeath shake, viewport resizes settled past the debounce'}},
            'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls back to the local adapter',
            'identity_exact': identity_report.get('exact_on_all_tested_engines'), 'comparison_result': comparison['result'],
            'evidence_paths': evidence, 'sha256': {p: (commands_seal(out, len(commands)) if p == 'commands.jsonl' else fc.sha_file(out / p)) for p in evidence},
            'commands_sealed_lines': len(commands),
            'failed_attempts_preserved': sorted(set(comparison['failed_attempts']) | set(identity_report['failed_attempts'])),
            'note': 'A successful evidence audit is separate from the performance verdict (comparison.json / cost-ranking.json). Failed attempts '
                    'are preserved, never rewritten. Historical receipts are never fabricated.'}


def report(args):
    out = Path(args.output).resolve()
    preserve_module(out)  # the report-time module variant is preserved next to the capture-time ones
    ident = fc.load(out / 'identity.json')
    identity_report = build_identity_report(out)
    fc.dump(out / 'identity-visual.json', identity_report)
    integration = fc.load(out / 'integration.json')
    integration['identity'] = {'result': 'EXACT' if identity_report['exact_on_all_tested_engines'] else 'DIFFERENT_OR_INCOMPLETE',
                               'exact_cells': identity_report['exact_cells'], 'complete_cells': identity_report['complete_cells'],
                               'cell_count': identity_report['cell_count'], 'checkpoints_total': identity_report['checkpoints_total'],
                               'detail': 'identity-visual.json', 'conflicts': [k for k, v in identity_report['cells'].items() if v['result'] == 'DIFFERENT'],
                               'action': 'none: nothing to revert' if identity_report['exact_on_all_tested_engines'] else
                                         'identity broken or incomplete: see conflicts; the integrated body stays only if the conflict is explained'}
    integration['utc_report'] = utc()
    fc.dump(out / 'integration.json', integration)
    comparison = build_comparison(out)
    comparison['control_commit'] = ident['control_commit']
    comparison['task271_desktop_fps'] = ident['control_numbers_task271']
    fc.dump(out / 'comparison.json', comparison)
    ranking = build_cost_ranking(comparison, identity_report)
    fc.dump(out / 'cost-ranking.json', ranking)
    manifest = build_manifest(out, comparison, identity_report, integration)
    fc.dump(out / 'manifest.json', manifest)
    print('REPORT identity', integration['identity']['result'], f"{identity_report['exact_cells']}/{identity_report['cell_count']} cells exact;",
          'comparison', comparison['result'], flush=True)
    for key, c in comparison['cells'].items():
        vc, vo = c['vs_control'], c['vs_original']
        print(f"  {key}: backing {c['backing']} vs control median {vc['median_reduction_fraction']:+.1%} ({vc['median_reduction_ms']:+.1f} ms, "
              f"worst pair worse {vc['max_worse_fraction']:.1%}) -> {c['verdict_vs_control']}; vs original median {vo['median_reduction_fraction']:+.1%} "
              f"(integrated {vo['median_integrated_mean_ms']:.1f} ms vs original {vo['median_reference_mean_ms']:.1f} ms); "
              f"10 s minima fps integrated {vc['min_10s_fps_integrated']:.2f} control {vc['min_10s_fps_reference']:.2f} original {vo['min_10s_fps_reference']:.2f}"
              if vc and vo else f'  {key}: incomplete', flush=True)
    return 0 if comparison['result'] == 'COMPLETE' and identity_report['exact_on_all_tested_engines'] else 1


# --------------------------------------------------------------- audit --

class Audit:
    def __init__(self):
        self.passes, self.failures = 0, []

    def check(self, ok, msg):
        if ok:
            self.passes += 1
        else:
            self.failures.append(msg)
            print('FAIL', msg, flush=True)


def audit(args):
    out = Path(args.output).resolve()
    A = Audit()
    m = fc.load(out / 'manifest.json')
    for name, digest in m['sha256'].items():
        actual = commands_seal(out, m['commands_sealed_lines']) if name == 'commands.jsonl' else (fc.sha_file(out / name) if (out / name).exists() else None)
        A.check(actual == digest, f'SHA256 mismatch {name}')
    print(f'PASS manifest seal: {len(m["sha256"])} evidence files checked, {len(A.failures)} mismatches', flush=True)
    A.check(fc.sha_file(fc.HARNESS) == m['harness_sha256'], 'timing harness changed since capture')
    A.check(fc.sha_file(MODULE) == m['module_sha256_at_report'] or any((out / 'module-at-capture' / f'{MODULE.stem}-{fc.sha_file(MODULE)[:8]}.py').exists() for _ in [0]),
            'module changed since report and not preserved')
    for c in m['commands']:
        A.check(bool(c['argv']) and c['utc_start'] <= c['utc_end'] and isinstance(c['exit_code'], int), f'bad command receipt {c["label"]}')
    ident = fc.load(out / 'identity.json')
    for t in TREES:
        A.check(fc.tree_hashes(out / 'trees' / t) == ident['files_sha256'][t], f'tree {t} differs from identity.json')
    A.check(all(fc.sha_file(ROOT / name) == digest for name, digest in ident['files_sha256']['integrated'].items()),
            'shipped runtime differs from the integrated tree')
    A.check(gr.runtime_body_sha(ROOT) == fc.load(ROOT / 'artifacts/TASK-280/decision.json')['candidate']['body_sha256'], 'runtime body != TASK-280 tested body')
    integration = fc.load(out / 'integration.json')
    A.check(integration['all_candidates_consistent_with_final_code'], 'integration map inconsistent with final code')
    for cand in integration['candidates']:
        A.check(cand['consistent'], f"candidate {cand['task']} inconsistent")
    # identity: recompute from raws
    idr = build_identity_report(out)
    stored = fc.load(out / 'identity-visual.json')
    for key, v in idr['cells'].items():
        A.check(v['result'] == stored['cells'][key]['result'], f'identity cell {key} result differs from stored')
        if v['result'] in ('EXACT', 'DIFFERENT'):
            A.check(v['replay_sha256_equal'], f'identity {key}: replay differs between trees')
            A.check(all(x['control_body_global'] is False and x['integrated_body_global'] is True for x in v['checkpoints']), f'identity {key}: body global presence wrong')
            A.check(v['control_region_calls'] in (None, 0) and (v['integrated_region_calls'] or 0) > 0, f'identity {key}: region hook calls wrong')
    A.check(idr['exact_on_all_tested_engines'] == stored['exact_on_all_tested_engines'], 'identity verdict differs')
    print(f"PASS identity recomputed: {idr['exact_cells']}/{idr['cell_count']} cells exact, {idr['checkpoints_total']} checkpoints,"
          f" exact_on_all_tested_engines={idr['exact_on_all_tested_engines']}", flush=True)
    # timing: recompute from raws
    raws = load_dir(out, 'raw')
    for name, r in raws.items():
        A.check(fc.frames_sha256(r['frames']) == r['frames_sha256'], f'{name} frames altered')
        A.check(r['harness_sha256'] == m['harness_sha256'], f'{name} captured by a different harness')
        if r.get('result') != 'COMPLETE':
            print('INFO failed attempt preserved', name, r.get('result'), flush=True)
            continue
        A.check(fc.summarize(r) == r['summary'], f'{name} summary differs from recomputation')
        A.check(r['dimensions']['platform'] in ('disabled', 'absent'), f'{name} SDK not isolated')
        A.check(not r['errors'] and not r['error'], f'{name} page errors')
        A.check(r['settings']['windows'] == WINDOWS and r['settings']['window_ms'] == WINDOW_MS and r['settings']['warmup_ms'] == WARMUP_MS, f'{name} wrong protocol')
        # split_windows cuts at frame boundaries on cumulative targets from the warmup end: the three windows together hold
        # >= 30 s, each one 10 s +- one frame interval (an overshoot of window k shortens window k+1 by that frame).
        A.check(len(r['summary']['windows']) == WINDOWS and r['summary']['combined']['active_ms'] >= WINDOWS * WINDOW_MS
                and all(w['active_ms'] >= WINDOW_MS - WINDOW_SLACK_MS for w in r['summary']['windows']), f'{name} short windows')
        A.check(not r['settings']['ablate'] and not r['settings']['diagnostic'], f'{name} not a primary capture')
        tree = r['case'].split('-')[3]
        A.check(r['tree']['files_sha256'] == ident['files_sha256'][tree], f'{name} tree hashes != {tree}')
        rr = run_record(r)
        A.check(tree == 'original' or not r['settings'].get('offer_shim', False), f'{name} offer shim on a non-original tree')
        print(f"PASS {r['case']}: fps={rr['average_fps']:.2f} mean={rr['mean_ms']:.1f}ms p50={rr['frame_ms']['p50']:.1f} p95={rr['frame_ms']['p95']:.1f} "
              f"min10s={rr['min_10s_fps']:.2f} backing={rr['backing']} deaths={rr['deaths']} gaps={rr['gaps']} excluded={rr['excluded_frames']} "
              f"offer_shim={rr['offer_shim']} offer_restarts={rr['offer_restarts']}", flush=True)
    comp = build_comparison(out)
    stored_comparison = fc.load(out / 'comparison.json')
    for key, c in comp['cells'].items():
        s = stored_comparison['cells'][key]
        A.check(c['equal_backing_all_runs'], f'{key}: unequal backing sizes')
        A.check(c['complete'] == s['complete'] and c['verdict_vs_control'] == s['verdict_vs_control'], f'{key}: verdict differs from stored')
        for kind in ('pairs_vs_control', 'pairs_vs_original'):
            A.check(len(c[kind]) == len(s[kind]) and all(abs(a['reduction_fraction'] - b['reduction_fraction']) < 1e-12 for a, b in zip(c[kind], s[kind])),
                    f'{key}: {kind} differ from stored')
            orders = [p['order'] for p in c[kind]]
            A.check(len(set(orders)) == 2 if len(orders) == 3 else True, f'{key}: {kind} order does not alternate')
            A.check(all(p['reference_case'].split('-')[3] != 'integrated' and p['integrated_case'].split('-')[3] == 'integrated' for p in c[kind]), f'{key}: {kind} arms mislabelled')
        if c['vs_control'] and c['vs_original']:
            print(f"PASS {key}: vs control median {c['vs_control']['median_reduction_fraction']:+.2%} -> {c['verdict_vs_control']}; "
                  f"vs original median {c['vs_original']['median_reduction_fraction']:+.2%}; backing {c['backing']}", flush=True)
    A.check(comp['result'] == stored_comparison['result'], 'comparison result differs from stored')
    rank = fc.load(out / 'cost-ranking.json')
    for mode in MODES:
        r = rank['modes'][mode]['ranking']
        A.check(all(r[i]['remaining_ms_estimate'] >= r[i + 1]['remaining_ms_estimate'] for i in range(len(r) - 1)), f'ranking {mode} not sorted')
        A.check(rank['modes'][mode]['remaining_deficits']['vs_original_ms'] is not None, f'ranking {mode} missing deficit vs original')
    for name in fc.runtime_files(ROOT):
        A.check(fc.MARKER not in (ROOT / name).read_text(errors='replace'), f'diagnostic marker in {name}')
    print(f'AUDIT {"PASS" if not A.failures else "FAIL"} passes={A.passes} failures={len(A.failures)} timing_raws={len(raws)} '
          f'identity_raws={len(load_dir(out, "identity"))} identity={stored["exact_on_all_tested_engines"]} comparison={comp["result"]}', flush=True)
    return 0 if not A.failures else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--output', required=True); p.set_defaults(func=prepare)
    i = sub.add_parser('identity'); i.add_argument('--output', required=True); i.add_argument('--engines', nargs='*', default=None)
    i.add_argument('--only', nargs='*', default=None); i.set_defaults(func=identity)
    c = sub.add_parser('capture'); c.add_argument('--output', required=True); c.add_argument('--profile', choices=PROFILES, required=True)
    c.add_argument('--mode', choices=MODES, required=True); c.add_argument('--tree', choices=TREES, required=True); c.add_argument('--case', required=True)
    c.add_argument('--cpu-throttle', type=int, default=1); c.set_defaults(func=capture)
    r = sub.add_parser('run'); r.add_argument('--output', required=True); r.add_argument('--engines', nargs='*', default=None)
    r.add_argument('--cpu-throttle', type=int, default=1); r.add_argument('--skip-prepare', action='store_true')
    r.add_argument('--skip-identity', action='store_true'); r.add_argument('--skip-timing', action='store_true')
    r.add_argument('--resume', action='store_true', help='skip captures that already have a COMPLETE raw'); r.set_defaults(func=run)
    for name, func in (('report', report), ('audit', audit)):
        s = sub.add_parser(name); s.add_argument('--output', required=True); s.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
