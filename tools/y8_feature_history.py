"""Feature-history regression bisection on historical builds (TASK-275).

Which feature introduction between the original Y8 ZIP (TASK-098, commit b588d69) and the
current runtime caused the largest measured draw-cost regression? At most six
feature-boundary revisions relevant to the TASK-272/273/274 rankings are extracted with
`git archive` into local evidence directories (the working branch is never changed, nothing
is rolled back or shipped), checked for harness compatibility, and sampled with the
unchanged TASK-271 harness protocol (fixed desktop viewport, pinned density, seeded
active-clock replay) using two 15-second active windows per tree, with the current and
original controls in the same sequence.

Actions
  select   derive the most affected mode from the sealed TASK-271 controls, extract the
           trees, run static compatibility checks, write --output/history.json
  capture  one browser session on --root (one tree); writes --output/raw/<case>.json (+png)
  run      capture every tree twice (chronological order, then reversed); receipts in
           --output/commands.jsonl
  report   history-runs.json, decision.json, manifest.json (history.json gains the dynamic
           compatibility results)
  audit    recompute every metric from the raw files, re-verify tree hashes against
           `git show`, confirm failed/incompatible trees are excluded from the rankings

A revision that does not boot, lacks the harness APIs or fails the capture is UNTESTABLE:
preserved as a failed attempt and excluded from every ranking, never treated as fast.
A history correlation is not proof of one internal rendering operation. Nothing here claims
60 FPS, physical-device results or release readiness.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_feature_cost as fc  # noqa: E402  unchanged TASK-271 harness
import y8_chill_ablation as ch  # noqa: E402  unchanged TASK-273 replay styles + read-only sampler

ROOT = fc.ROOT
MODULE = Path(__file__).resolve()
TASK = 'TASK-275'
MODULE_AT_CAPTURE = 'module-at-capture/y8_feature_history.py'
CONTROLS_271 = ROOT / 'artifacts/TASK-271/controls.json'
RUNTIME_PATHS = ['render', 'elements', 'sprites', 'collision', 'physics.js', 'gameoptions.js', 'index.html',
                 'events.js', 'moveScreen.js', 'style.js', 'platform.js', 'progress.js', 'menu.js', 'respawn.js',
                 'i18n.js', 'languagebutton.js', 'y8config.js']
# Replay per mode: the segment each mode's ranking evidence used (TASK-271 screening seed 4 for
# Main; TASK-273 segment.json chose seed 7 / chill-ceiling for Chill because the screening replay
# kills the Chill ninja 7-9 s after every start).
REPLAY_BY_MODE = {'bad': (4, 'screening'), 'classic': (7, 'chill-ceiling')}
WINDOW_MS, WARMUP_MS, WINDOWS, REPS = 15000, 5000, 1, 2
ISOLATED_PLATFORMS = ('disabled', 'absent', 'local')
# The original (b588d69) shows its "Continue?" offer after a lethal death from CONTINUE_MIN_SCORE
# even without an ad SDK (only Restart is clickable) and freezes physics until the player answers;
# every later tree restarts instantly without rewarded ads. This page-only shim performs the
# offer's own Restart action (restartFromOffer: hide + reStart + resetPhysicsTiming) on the first
# frame the offer is visible, so the original follows the same instant-restart flow. Frames with
# the offer visible are excluded by the harness anyway; each auto-restart is recorded in the raw.
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
REQUIRED_API = ['function startGame', 'function gameLoop', 'function reStart', 'gamePaused']
# Identifiers whose presence in the served runtime marks a visual feature (static scan, counts of files).
FEATURE_IDS = {'ambient-motes': 'drawAmbientMotes', 'ambient-glow-chain': 'AmbientGlowRenderer',
               'obstacle-lightmap': 'LightmapRenderer', 'cave-crystals': 'crystal',
               'player-glow-layer': 'drawPlayerGlowLayer', 'bloom': 'BloomRenderer',
               'colour-grade': 'ColorGradeRenderer', 'neon-outlines': 'strokeNeonPath',
               'extrusion': 'extrusion', 'glow-sprites': 'drawGlowSprite', 'render-budget': 'RENDER_BUDGET',
               'left-wall': 'leftWall', 'danger-hatches': 'hatch'}
# Chronological feature-boundary revisions (oldest first). The original control (b588d69, the
# TASK-098 ZIP) precedes them and the current control (HEAD) follows them.
REVISIONS = [
    {'rev': 'e430f92', 'label': 'pre-overhaul', 'ranked_feature': None,
     'boundary': 'last revision before the TASK-176+ rendering overhaul: collision/physics TASK-145..158, '
                 'platform-neutral local adapter (ff50276), sound removed, landscape rotation; no restyle',
     'rationale': 'separates the non-rendering history (physics, platform, input) from every rendering feature'},
    {'rev': 'dc25e05', 'label': 'cave-background', 'ranked_feature': 'cave-background',
     'boundary': 'TASK-176..178: violet background gradient, far crystal layer, near rock layer + depth haze',
     'rationale': 'cave background introduced (TASK-272/273 REPEATED_SAVING, TASK-274 MEDIUM)'},
    {'rev': '42cf789', 'label': 'obstacle-lighting', 'ranked_feature': 'obstacle-lighting',
     'boundary': 'TASK-179..185: ninja/rope/trail restyle, fake-3D extrusion, neon outlines, bloom pass, '
                 'LightmapRenderer enabled as coloured light spill',
     'rationale': 'obstacle lighting introduced (Main REPEATED_SAVING in TASK-273 re-tiering)'},
    {'rev': 'bb32f03', 'label': 'ambient-motes', 'ranked_feature': 'ambient-glow',
     'boundary': 'TASK-186 (single commit): 40 seeded ambient motes behind the world, also fed into bloom; '
                 'neon pulse',
     'rationale': 'first form of the ambient-glow feature (dominant in TASK-272/273/274)'},
    {'rev': '5ccf512', 'label': 'player-glow', 'ranked_feature': 'player-glow',
     'boundary': 'TASK-187..216: colour grade, neon menu, polish, cached glow sprites, zero-churn caches, '
                 'touch DPR cap, ball size, parallax, light spill fades, bloom replaced by inner rim (TASK-206), '
                 'legacy decorations removed, embers, swept trails, player trail/spark halos with cached ball '
                 'glow and drawPlayerGlowLayer (TASK-216)',
     'rationale': 'player glow layer introduced (CONSISTENT_SAVING; TASK-274 LOW); widest interval'},
    {'rev': '8610b9b', 'label': 'ambient-glow-chain', 'ranked_feature': 'ambient-glow',
     'boundary': 'TASK-217, 218, 219, 208(backgrounds still), 209, 210, 218(strengthen), 208: indigo '
                 'silhouettes, cached obstacle light falloffs, anchor sizes, still cave backgrounds, orange '
                 'danger rects/hatches, AmbientGlowRenderer sparkle glow chain',
     'rationale': 'AmbientGlowRenderer chain introduced: the operation TASK-272/273 ablation skips as ambient-glow'},
]
CURRENT_INTERVAL = ('8610b9b..HEAD: TASK-221..233 (ball, trail widths, ring, landing ring, light spill fixes, '
                    'left wall, hatches, trail history), 81ba90e restoration with bounded rendering cost, '
                    'TASK-259, TASK-255 glow revert, TASK-256 DPR, TASK-265 bounded glow compositing, TASK-267')


class EvidenceError(fc.EvidenceError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def git(*argv):
    return subprocess.check_output(['git', *argv], cwd=ROOT, text=True).strip()


def case_name(tree, mode, rep):
    return f'{tree}-{mode}-desktop-r{rep}'


# ------------------------------------------------------------- selection --

def most_affected(controls):
    """Mode with the largest current-vs-original p50 frame-time regression in the sealed TASK-271 controls."""
    per = {}
    for p in controls['pairs']:
        if p.get('result') != 'PAIRED' or not p['candidate'].startswith('original-'):
            continue
        mode = p['candidate'].split('-')[1]
        per.setdefault(mode, []).append(-p['delta_p50_ms'])
    if not per:
        raise EvidenceError('no original pairs in TASK-271 controls')
    scores = {m: sum(v) / len(v) for m, v in per.items()}
    mode = max(scores, key=scores.get)
    return {'mode': mode, 'profile': 'desktop', 'regression_p50_ms_by_mode': scores, 'pairs_by_mode': per,
            'rule': 'mean over PAIRED current->original pairs of -(delta_p50_ms); largest wins',
            'source': str(CONTROLS_271.relative_to(ROOT)), 'source_sha256': fc.sha_file(CONTROLS_271)}


def static_compat(root):
    """Harness API presence, external script tags and platform adapter of an extracted tree."""
    root = Path(root)
    files = fc.runtime_files(root)
    text = {name: (root / name).read_text(errors='replace') for name in files}
    missing = [api for api in REQUIRED_API if not any(api in t for t in text.values())]
    html = text.get('index.html', '')
    external = re.findall(r'src\s*=\s*["\'](https?://[^"\']+)', html)
    platform = sorted(set(re.findall(r"environment\s*=\s*([^\n;]+)", text.get('platform.js', ''))))
    features = {k: sum(1 for t in text.values() if ident in t) for k, ident in FEATURE_IDS.items()}
    ok = bool(html) and not missing
    return {'index_html': bool(html), 'runtime_files': len(files), 'missing_api': missing,
            'external_scripts': external, 'platform_environment_assignments': platform,
            'feature_identifiers': features,
            'result': 'STATIC_OK' if ok else 'STATIC_FAIL: ' + ('no index.html' if not html else 'missing ' + ', '.join(missing))}


def extract(rev, dest):
    """git archive <rev> into dest (fresh); returns (full sha, tar sha256)."""
    full = git('rev-parse', rev + '^{commit}')
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    tar = subprocess.check_output(['git', 'archive', '--format=tar', full], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(dest, filter='data')
    return full, fc.sha_bytes(tar)


def git_show_hashes(full, names):
    """sha256 of each runtime file straight from the commit object (independent of the extraction)."""
    out = {}
    for name in names:
        data = subprocess.check_output(['git', 'show', f'{full}:{name}'], cwd=ROOT)
        out[name] = fc.sha_bytes(data)
    return out


def interval_changes(prev_full, full):
    subjects = git('log', '--first-parent', '--format=%h %s', f'{prev_full}..{full}').splitlines()
    stat = git('diff', '--stat=200', prev_full, full, '--', *RUNTIME_PATHS).splitlines()
    names = git('diff', '--name-status', prev_full, full, '--', *RUNTIME_PATHS).splitlines()
    return {'commits': len(subjects), 'subjects': [s[:160] for s in subjects], 'runtime_diffstat': stat[-1] if stat else '',
            'runtime_files_changed': names}


def select(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    t0 = utc()
    if len(REVISIONS) > 6:
        raise EvidenceError('at most six feature-boundary revisions')
    affected = most_affected(fc.load(CONTROLS_271))
    identity = fc.build_trees(out)  # current = HEAD archive (== worktree runtime), original = TASK-098 ZIP == b588d69
    trees = []
    original_full = identity['original_commit']
    original_root = Path(identity['trees']['original'])
    trees.append({'tree': 'original', 'rev': fc.ORIGINAL_COMMIT, 'full': original_full, 'role': 'control',
                  'label': 'original Y8 ZIP (TASK-098)', 'root': str(original_root.relative_to(ROOT)),
                  'tar_sha256': None, 'zip_sha256': identity['original_zip_sha256'],
                  'runtime_sha256': fc.tree_hashes(original_root),
                  'git_show_sha256': git_show_hashes(original_full, fc.runtime_files(original_root)),
                  'boundary': 'shipped original (b588d69)', 'ranked_feature': None,
                  'rationale': 'original control; byte-identical to the TASK-098 ZIP', 'interval': None})
    prev = original_full
    for spec in REVISIONS:
        dest = out / 'trees' / spec['rev']
        full, tar_sha = extract(spec['rev'], dest)
        subprocess.check_call(['git', 'merge-base', '--is-ancestor', full, 'HEAD'], cwd=ROOT)
        subprocess.check_call(['git', 'merge-base', '--is-ancestor', original_full, full], cwd=ROOT)
        names = fc.runtime_files(dest)
        trees.append({'tree': spec['rev'], 'rev': spec['rev'], 'full': full, 'role': 'revision',
                      'label': spec['label'], 'root': str(dest.relative_to(ROOT)), 'tar_sha256': tar_sha,
                      'committed_utc': git('log', '-1', '--format=%cI', full),
                      'subject': git('log', '-1', '--format=%s', full)[:200],
                      'runtime_sha256': fc.tree_hashes(dest), 'git_show_sha256': git_show_hashes(full, names),
                      'boundary': spec['boundary'], 'ranked_feature': spec['ranked_feature'],
                      'rationale': spec['rationale'], 'interval': interval_changes(prev, full)})
        prev = full
    current_root = Path(identity['trees']['current'])
    trees.append({'tree': 'current', 'rev': 'HEAD', 'full': identity['current_commit'], 'role': 'control',
                  'label': 'current committed runtime', 'root': str(current_root.relative_to(ROOT)),
                  'tar_sha256': identity['current_tar_sha256'], 'runtime_sha256': identity['current_files_sha256'],
                  'git_show_sha256': git_show_hashes(identity['current_commit'], fc.runtime_files(current_root)),
                  'boundary': CURRENT_INTERVAL, 'ranked_feature': None,
                  'rationale': 'current control (git archive HEAD, equal to the worktree runtime)',
                  'interval': interval_changes(prev, identity['current_commit'])})
    for t in trees:
        if t['runtime_sha256'] != t['git_show_sha256']:
            raise EvidenceError(f'{t["tree"]}: extracted runtime differs from git show')
        t['compatibility'] = {'static': static_compat(ROOT / t['root']), 'dynamic': None}
    seed, style = REPLAY_BY_MODE[affected['mode']]
    history = {'task': TASK, 'utc_start': t0, 'utc_end': utc(), 'source_revision': identity['current_commit'],
               'source_dirty_runtime': identity['current_dirty_runtime'],
               'most_affected': affected, 'protocol': {
                   'profile': 'desktop', 'viewport': fc.PROFILES['desktop']['viewport'], 'dpr': 1, 'cpu_throttle': 1,
                   'mode': affected['mode'], 'seed': seed, 'replay_style': style,
                   'replay_box': ch.REPLAY_STYLES[style], 'warmup_ms': WARMUP_MS, 'window_ms': WINDOW_MS,
                   'windows': WINDOWS, 'repetitions': REPS,
                   'order': 'chronological original..current, then reversed (no tree always first/last)',
                   'metric': 'mean active frame time (active_ms / intervals) per 15 s window from rAF timestamps',
                   'controls': ['original', 'current'],
                   'untestable_rule': 'boot/API/capture failures are UNTESTABLE: preserved, excluded from rankings'},
               'revision_limit': 6, 'revisions_selected': len(REVISIONS),
               'extraction': 'git archive <commit> into artifacts/TASK-275/trees/<rev>/ (working branch untouched)',
               'trees': trees,
               'pixel_equivalence': 'NOT claimed: every revision draws different features (see feature_identifiers, '
                                    'interval subjects, in-page STYLE.features and the per-capture screenshot)'}
    fc.dump(out / 'history.json', history)
    for t in trees:
        print('TREE', t['tree'], t['full'][:12], t['label'], t['compatibility']['static']['result'],
              'files=%d' % len(t['runtime_sha256']), 'features=%s' % json.dumps(t['compatibility']['static']['feature_identifiers'], sort_keys=True))
    print('PASS select: mode=%s (%s) seed=%d style=%s; %d trees written to history.json' % (
        affected['mode'], json.dumps({k: round(v, 1) for k, v in affected['regression_p50_ms_by_mode'].items()}),
        seed, style, len(trees)))
    return 0


# --------------------------------------------------------------- capture --

def capture(args):
    from browser_test_support import start_browser_test
    root = Path(args.root).resolve()
    profile = fc.PROFILES['desktop']
    total = args.warmup_ms + args.windows * args.window_ms
    replay = ch.replay_script(args.seed, 'desktop', total + 1000, args.replay_style)
    settings = {'mode': args.mode, 'profile': 'desktop', 'viewport': profile['viewport'], 'dpr': 1,
                'is_mobile': False, 'has_touch': False, 'input': 'mouse', 'cpu_throttle': args.cpu_throttle,
                'seed': args.seed, 'replay_style': args.replay_style, 'replay_box': ch.REPLAY_STYLES[args.replay_style],
                'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows,
                'replay_sha256': fc.replay_sha256(replay), 'ablate': [], 'diagnostic': False,
                'offer_shim': bool(args.offer_shim),
                'density': 'pinned to profile DPR when RENDER_BUDGET exists; otherwise devicePixelRatio=1 backing',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; PLATFORM falls '
                                 'back to the local/disabled adapter (no ads, instant restart on death)'}
    cfg = {'dpr': 1, 'input': 'mouse', 'ablate': [], 'diagnostic': False, 'replay': replay,
           'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows}
    raw = {'case': args.case, 'task': TASK, 'tree_name': args.tree, 'settings': settings,
           'tree': {'root': str(root), 'files_sha256': fc.tree_hashes(root) if (root / 'index.html').exists() else {}},
           'harness_sha256': fc.sha_file(fc.HARNESS), 'chill_sha256': fc.sha_file(ch.__file__),
           'history_sha256': fc.sha_file(MODULE), 'argv': sys.argv, 'started_utc': utc(), 'replay': replay,
           'network': [], 'errors': [], 'console_errors': [], 'error': None, 'frames': [], 'samples': [],
           'deaths': [], 'dispatched': [], 'excluded': [], 'dimensions': None, 'screenshot': None,
           'offerRestarts': [], 'offerShim': 'not requested'}
    network, exit_code, stage = raw['network'], 1, 'boot'
    try:
        if not (root / 'index.html').exists():
            raise EvidenceError('UNTESTABLE: no index.html')
        with ExitStack() as stack:
            url, browser = start_browser_test(root, stack.callback)
            raw['environment'] = fc.environment(browser)
            ctx = fc.new_context(browser, 'desktop', args.seed, network)
            stack.callback(ctx.close)
            page = ctx.new_page()
            page.on('pageerror', lambda e: raw['errors'].append(str(e)))
            page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
            ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': args.cpu_throttle})
            page.goto(url + 'index.html', wait_until='domcontentloaded')
            try:
                page.wait_for_function(fc.BOOTED, timeout=60000)
            except Exception as e:
                raise EvidenceError('UNTESTABLE: boot timeout (menu/startGame/loading/PLATFORM): ' + str(e).splitlines()[0])
            stage = 'instrument'
            page.evaluate(fc.INSTRUMENT, cfg)
            page.evaluate(ch.SAMPLER)
            if args.offer_shim:
                page.evaluate(OFFER_SHIM)
            stage = 'play'
            page.evaluate('mode => startGame(mode)', args.mode)
            try:
                page.wait_for_function(f'{fc.MARKER}.done || {fc.MARKER}.error', timeout=args.timeout_ms)
            except Exception as e:
                raw['errors'].append('timeout: ' + str(e).splitlines()[0])
            page.evaluate(f'() => {{ {fc.MARKER}.cfg.replay = "<see raw.replay>" }}')
            raw.update(page.evaluate(fc.MARKER))
            raw['dimensions'] = page.evaluate(fc.DIMENSIONS)
            png = Path(args.output) / 'raw' / (args.case + '.png')
            png.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(png))  # after the timed window: visual-difference evidence only
            raw['screenshot'] = {'path': 'raw/' + png.name, 'sha256': fc.sha_file(png),
                                 'note': 'taken after the measured window; never part of the timing'}
        raw['ended_utc'] = utc()
        if raw['errors'] or raw['error']:
            raise EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw['error']]))
        if raw['dimensions']['platform'] not in ISOLATED_PLATFORMS:
            raise EvidenceError('SDK isolation failed: ' + str(raw['dimensions']['platform']))
        if any(n.split(' ', 1)[0] not in ('SDK_BLOCKED', 'BLOCKED', 'LOCAL') or (n.startswith('LOCAL') and '127.0.0.1' not in n) for n in network):
            raise EvidenceError('non-local request was not aborted')
        if raw['dimensions']['version'] != args.mode:
            raise EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
        if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
            raise EvidenceError('backing size changed during the capture')
        raw['summary'] = fc.summarize(raw)
        raw['density'] = ch.window_density(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except EvidenceError as e:
        raw['summary'], raw['result'] = None, f'FAILED ({stage}): ' + str(e)
    except Exception as e:  # browser/server failure: still a preserved, failed attempt
        raw['summary'], raw['result'] = None, f'FAILED ({stage}): UNTESTABLE: {type(e).__name__}: ' + str(e).splitlines()[0][:300]
    raw.setdefault('ended_utc', utc())
    raw['frames_sha256'] = fc.frames_sha256(raw['frames'])
    path = fc.raw_path(args.output, args.case)
    fc.dump(path, raw)
    c = raw['summary']['combined'] if raw['summary'] else None
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'platform=%s backing=%s' % ((raw['dimensions'] or {}).get('platform'), (raw['dimensions'] or {}).get('canvas')),
          'fps=%.2f mean_ms=%.2f p50=%.2f p95=%.2f active_ms=%.0f deaths=%d travel=%.0f' % (
              c['average_fps'], c['active_ms'] / c['intervals'], c['frame_ms']['p50'], c['frame_ms']['p95'],
              c['active_ms'], raw['summary']['deaths'], raw['density']['camera']['travel_px']) if c else '', flush=True)
    return exit_code


def capture_argv(tree, out, proto, rep, offer_shim=False):
    return [sys.executable, 'tools/y8_feature_history.py', 'capture', '--root', str(ROOT / tree['root']),
            '--output', str(out), '--tree', tree['tree'], '--mode', proto['mode'], '--seed', str(proto['seed']),
            '--replay-style', proto['replay_style'], '--case', case_name(tree['tree'], proto['mode'], rep),
            '--warmup-ms', str(proto['warmup_ms']), '--window-ms', str(proto['window_ms']), '--windows', str(proto['windows'])] \
        + (['--offer-shim'] if offer_shim else [])


def run(args):
    out = Path(args.output)
    history = fc.load(out / 'history.json')
    proto = history['protocol']
    trees = history['trees']
    receipts = out / 'commands.jsonl'
    sequence = [(t, 1) for t in trees] + [(t, 2) for t in reversed(trees)]
    if args.only:  # bounded retry of one tree/repetition (receipt kept in the same file)
        sequence = [(t, rep) for t, rep in sequence if t['tree'] == args.only and (args.rep is None or rep == args.rep)]
    failed = 0
    for tree, rep in sequence:
        argv = capture_argv(tree, out, proto, rep, args.offer_shim)
        t0 = utc()
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        rec = {'label': f'capture/{tree["tree"]}/r{rep}' + ('/retry-offer-shim' if args.only else ''), 'argv': argv,
               'utc_start': t0, 'utc_end': utc(), 'retry_reason': args.reason,
               'exit_code': r.returncode, 'stdout': r.stdout[-3000:], 'stderr': r.stderr[-3000:]}
        with receipts.open('a') as f:
            f.write(json.dumps(rec, sort_keys=True) + '\n')
        print(r.stdout.strip() or r.stderr.strip()[-600:], flush=True)
        failed += r.returncode != 0
    print(f'PASS run: {len(sequence)} captures, {failed} failed (preserved)', flush=True)
    return 0


# ---------------------------------------------------------------- report --

def mean_ms(raw):
    c = raw['summary']['combined']
    return c['active_ms'] / c['intervals']


def arm_record(raw, name):
    s = raw['summary']['combined']
    return {'raw': name, 'case': raw['case'], 'result': raw['result'], 'started_utc': raw['started_utc'],
            'mean_ms': mean_ms(raw), 'average_fps': s['average_fps'], 'p50_ms': s['frame_ms']['p50'],
            'p95_ms': s['frame_ms']['p95'], 'p99_ms': s['frame_ms']['p99'], 'max_ms': s['frame_ms']['max'],
            'intervals': s['intervals'], 'active_ms': s['active_ms'], 'deaths': raw['summary']['deaths'],
            'backing': raw['dimensions']['canvas'], 'platform': raw['dimensions']['platform'],
            'density_pin': raw['densityPin'], 'features': raw.get('features'), 'quality': raw.get('quality'),
            'camera_travel_px': raw['density']['camera']['travel_px'],
            'moving_fraction': raw['density']['camera']['moving_fraction'],
            'counts': {k: v.get('mean') if isinstance(v, dict) else v for k, v in raw['density']['counts'].items()},
            'screenshot': raw['screenshot'], 'replay_sha256': raw['settings']['replay_sha256'],
            'offer_shim': raw['settings'].get('offer_shim', False), 'offer_auto_restarts': raw.get('offerRestarts', []),
            'excluded_offer_frames': sum(1 for e in raw['excluded'] if e['state'].get('offer')),
            'history_sha256': raw['history_sha256']}


def build(out):
    """Per-tree runs, rankings over valid trees only, chronological steps and the decision."""
    history = fc.load(out / 'history.json')
    proto = history['protocol']
    raw_files = sorted((out / 'raw').glob('*.json'))
    raws = {f'raw/{p.name}': fc.load(p) for p in raw_files}
    runs, order = {}, [t['tree'] for t in history['trees']]
    for t in history['trees']:
        mine = {n: r for n, r in raws.items() if r['tree_name'] == t['tree']}
        complete = {n: r for n, r in mine.items() if r.get('result') == 'COMPLETE'}
        reps = {}
        for n, r in complete.items():
            rep = int(r['case'].rsplit('-r', 1)[1])
            if rep in reps:
                raise EvidenceError(f'duplicate complete repetition {r["case"]}')
            reps[rep] = arm_record(r, n)
        failed = [{'raw': n, 'result': r['result']} for n, r in mine.items() if r.get('result') != 'COMPLETE']
        valid = t['compatibility']['static']['result'] == 'STATIC_OK' and len(reps) == REPS
        dynamic = {'complete_repetitions': len(reps), 'failed_attempts': failed,
                   'platform': sorted({a['platform'] for a in reps.values()}),
                   'result': 'VALID' if valid else 'UNTESTABLE: ' + (
                       t['compatibility']['static']['result'] if t['compatibility']['static']['result'] != 'STATIC_OK'
                       else f'{len(reps)} of {REPS} complete repetitions')}
        runs[t['tree']] = {'tree': t['tree'], 'full': t['full'], 'label': t['label'], 'role': t['role'],
                           'ranked_feature': t['ranked_feature'], 'boundary': t['boundary'],
                           'repetitions': {str(k): reps[k] for k in sorted(reps)}, 'failed_attempts': failed,
                           'valid': valid, 'dynamic_compatibility': dynamic,
                           'mean_ms_by_rep': [reps[k]['mean_ms'] for k in sorted(reps)],
                           'mean_ms': (sum(a['mean_ms'] for a in reps.values()) / len(reps)) if reps else None,
                           'repeat_spread_ms': (max(a['mean_ms'] for a in reps.values()) - min(a['mean_ms'] for a in reps.values())) if len(reps) == REPS else None,
                           'visual_features': {'identifiers': t['compatibility']['static']['feature_identifiers'],
                                               'in_page_style_features': [a['features'] for a in reps.values()][:1],
                                               'in_page_quality': [a['quality'] for a in reps.values()][:1],
                                               'screenshots': [a['screenshot'] for a in reps.values()],
                                               'interval_subjects': (t['interval'] or {}).get('subjects'),
                                               'pixel_equivalent': False}}
    valid_order = [n for n in order if runs[n]['valid']]
    ranking = sorted(valid_order, key=lambda n: runs[n]['mean_ms'], reverse=True)
    noise_max = max(runs[n]['repeat_spread_ms'] for n in valid_order) if valid_order else None
    steps = []
    for a, b in zip(valid_order, valid_order[1:]):
        ra, rb = runs[a], runs[b]
        per_rep = [rb['repetitions'][k]['mean_ms'] - ra['repetitions'][k]['mean_ms'] for k in ('1', '2')]
        steps.append({'from': a, 'to': b, 'interval': f'{ra["full"][:7]}..{rb["full"][:7]}',
                      'to_label': rb['label'], 'ranked_feature': rb['ranked_feature'],
                      'delta_mean_ms_by_rep': per_rep, 'delta_mean_ms': sum(per_rep) / 2,
                      'regression_beyond_noise_every_rep': all(d > noise_max for d in per_rep),
                      'commits_in_interval': (next(t for t in history['trees'] if t['tree'] == b)['interval'] or {}).get('commits')})
    runs_doc = {'task': TASK, 'protocol': proto, 'trees_in_order': order, 'valid_trees': valid_order,
                'excluded_trees': [{'tree': n, 'reason': runs[n]['dynamic_compatibility']['result']} for n in order if not runs[n]['valid']],
                'runs': runs, 'ranking_slowest_first': [{'tree': n, 'mean_ms': runs[n]['mean_ms'], 'mean_ms_by_rep': runs[n]['mean_ms_by_rep'],
                                                         'average_fps_by_rep': [runs[n]['repetitions'][k]['average_fps'] for k in sorted(runs[n]['repetitions'])]} for n in ranking],
                'noise': {'rule': 'max over valid trees of |rep1 - rep2| mean frame time', 'max_repeat_spread_ms': noise_max,
                          'spread_by_tree': {n: runs[n]['repeat_spread_ms'] for n in valid_order}},
                'steps_chronological': steps,
                'controls': {'original': runs['original']['mean_ms_by_rep'] if runs['original']['valid'] else None,
                             'current': runs['current']['mean_ms_by_rep'] if runs['current']['valid'] else None},
                'simulation_rate_note': 'maxPhysicsStepsPerFrame caps simulated time per frame in the newer trees, so '
                                        'slower arms traverse less world in the same active window; deaths and camera '
                                        'travel are recorded per repetition (TASK-273 gotcha)',
                'visual_differences': 'trees are NOT pixel-equivalent: see runs.<tree>.visual_features'}
    return history, runs_doc, steps, noise_max


def decide(runs_doc, steps, noise_max):
    valid = runs_doc['valid_trees']
    total = None
    if 'original' in valid and 'current' in valid:
        total = runs_doc['runs']['current']['mean_ms'] - runs_doc['runs']['original']['mean_ms']
    if not steps:
        return {'task': TASK, 'result': 'UNRESOLVED', 'reason': 'fewer than two valid trees', 'steps': steps}
    largest = max(steps, key=lambda s: s['delta_mean_ms'])
    ordered = sorted(steps, key=lambda s: s['delta_mean_ms'], reverse=True)
    runner = ordered[1] if len(ordered) > 1 else None
    separated = runner is None or all(largest['delta_mean_ms_by_rep'][i] - runner['delta_mean_ms_by_rep'][i] > noise_max for i in range(2))
    resolved = largest['regression_beyond_noise_every_rep'] and separated
    share = (largest['delta_mean_ms'] / total) if total else None
    return {
        'task': TASK, 'mode': runs_doc['protocol']['mode'], 'profile': runs_doc['protocol']['profile'],
        'result': 'NARROWED' if resolved else 'UNRESOLVED',
        'largest_regression_interval': largest['interval'], 'introduced_at': largest['to'],
        'introduced_label': largest['to_label'], 'ranked_feature': largest['ranked_feature'],
        'commits_in_interval': largest['commits_in_interval'],
        'delta_mean_ms_by_rep': largest['delta_mean_ms_by_rep'], 'delta_mean_ms': largest['delta_mean_ms'],
        'noise_max_repeat_spread_ms': noise_max,
        'beyond_noise_every_rep': largest['regression_beyond_noise_every_rep'],
        'separated_from_runner_up_every_rep': separated,
        'runner_up': None if runner is None else {'interval': runner['interval'], 'to': runner['to'], 'delta_mean_ms_by_rep': runner['delta_mean_ms_by_rep']},
        'total_original_to_current_ms': total, 'share_of_total': share,
        'steps_ranked_by_regression': [{'interval': s['interval'], 'to': s['to'], 'label': s['to_label'],
                                        'delta_mean_ms_by_rep': s['delta_mean_ms_by_rep'],
                                        'beyond_noise_every_rep': s['regression_beyond_noise_every_rep']} for s in ordered],
        'excluded_trees': runs_doc['excluded_trees'],
        'statement': (f'The largest measured frame-time regression on {runs_doc["protocol"]["mode"]}/desktop lies in '
                      f'{largest["interval"]} ({largest["to_label"]}; {largest["commits_in_interval"]} commits): '
                      f'+{largest["delta_mean_ms_by_rep"][0]:.1f}/+{largest["delta_mean_ms_by_rep"][1]:.1f} ms per frame '
                      f'in the two repetitions, noise max {noise_max:.1f} ms.'
                      + (' The interval is narrowed to this boundary.' if resolved else
                         ' The interval remains UNRESOLVED within the bounded experiment: the step is not separated '
                         'from noise or from the runner-up in every repetition.')),
        'limits': ['a history correlation is not proof of one internal rendering operation: an interval of several '
                   'commits may mix features, caches and gameplay changes; only the TASK-272/273/274 ablations '
                   'isolate operations inside the current runtime',
                   'software headless Chromium, fixed 1280x720 DPR 1, one mode/profile, two 15 s windows per tree',
                   'trees are not pixel-equivalent and the replay produces different gameplay on different physics '
                   '(deaths/camera travel recorded per repetition)',
                   'no 60 FPS, physical-device or release-readiness claim; nothing shipped or rolled back'],
    }


def report(args):
    out = Path(args.output)
    t0 = utc()
    history, runs_doc, steps, noise_max = build(out)
    decision = decide(runs_doc, steps, noise_max)
    for t in history['trees']:
        t['compatibility']['dynamic'] = runs_doc['runs'][t['tree']]['dynamic_compatibility']
    history['utc_report'] = utc()
    fc.dump(out / 'history.json', history)
    fc.dump(out / 'history-runs.json', runs_doc)
    fc.dump(out / 'decision.json', decision)
    commands = [json.loads(line) for line in (out / 'commands.jsonl').read_text().splitlines() if line.strip()]
    raws = {n: fc.load(out / n) for n in sorted(f'raw/{p.name}' for p in (out / 'raw').glob('*.json'))}
    first = next(iter(raws.values()))
    snapshots = sorted(str(p.relative_to(out)) for p in (out / 'module-at-capture').glob('*.py'))
    evidence = sorted(['history.json', 'history-runs.json', 'decision.json', 'commands.jsonl'] + list(raws)
                      + [r['screenshot']['path'] for r in raws.values() if r.get('screenshot')] + snapshots)
    manifest = {
        'task': TASK, 'utc_start': min([history['utc_start']] + [c['utc_start'] for c in commands]),
        'utc_end': utc(), 'report_utc_start': t0, 'report_argv': sys.argv, 'commands': commands,
        'exit_codes': sorted({c['exit_code'] for c in commands}),
        'source_revision': history['source_revision'], 'source_dirty_runtime': history['source_dirty_runtime'],
        'harness_sha256': fc.sha_file(fc.HARNESS), 'chill_sha256': fc.sha_file(ch.__file__),
        'history_sha256': fc.sha_file(MODULE),
        'history_sha256_at_capture': sorted({r['history_sha256'] for r in raws.values()}),
        'module_at_capture': snapshots,
        'support_sha256': fc.sha_file(ROOT / 'tools/browser_test_support.py'),
        'environment': first.get('environment'), 'tool_versions': {k: first.get('environment', {}).get(k) for k in ('os', 'python', 'playwright', 'browser')},
        'trees': {t['tree']: {'full': t['full'], 'root': t['root'], 'tar_sha256': t.get('tar_sha256'), 'zip_sha256': t.get('zip_sha256'),
                              'runtime_files': len(t['runtime_sha256']),
                              'runtime_tree_sha256': fc.sha_bytes(json.dumps(t['runtime_sha256'], sort_keys=True).encode())}
                  for t in history['trees']},
        'fixed': {'profile': fc.PROFILES['desktop'], 'viewport': [1280, 720], 'dpr': 1,
                  'backing_size_by_tree': {n: sorted({tuple(a['backing']) for a in r['repetitions'].values()}) for n, r in runs_doc['runs'].items()},
                  'mode': history['protocol']['mode'], 'seed': history['protocol']['seed'], 'replay_style': history['protocol']['replay_style'],
                  'replay_sha256': sorted({r['settings']['replay_sha256'] for r in raws.values()}),
                  'warmup_ms': WARMUP_MS, 'window_ms': WINDOW_MS, 'windows': WINDOWS, 'repetitions': REPS,
                  'input': 'seeded press/release replay scheduled on the active clock (same SHA256 in every arm)',
                  'state': 'per-frame menu/paused/offer/hidden/ad recorded; inactive frames excluded; deaths via reStart hook; '
                           'read-only sampler per active frame'},
        'sdk_isolation': first['settings']['sdk_isolation'], 'isolated_platform_values': list(ISOLATED_PLATFORMS),
        'evidence_paths': evidence, 'sha256': {name: fc.sha_file(out / name) for name in evidence},
        'failed_attempts_preserved': [c['label'] for c in commands if c['exit_code'] != 0]
                                     + [n for n, r in raws.items() if r.get('result') != 'COMPLETE'],
        'note': 'A successful evidence audit is separate from the actual performance verdict. Historical receipts '
                'are only the raw files written by this run; nothing is reconstructed.'}
    fc.dump(out / 'manifest.json', manifest)
    print('TREES valid:', runs_doc['valid_trees'], 'excluded:', runs_doc['excluded_trees'])
    for n in runs_doc['trees_in_order']:
        r = runs_doc['runs'][n]
        print('RUN %-18s valid=%s mean_ms=%s fps=%s deaths=%s travel=%s' % (
            n, r['valid'], [round(x, 2) for x in r['mean_ms_by_rep']],
            [round(a['average_fps'], 2) for a in r['repetitions'].values()],
            [a['deaths'] for a in r['repetitions'].values()],
            [round(a['camera_travel_px']) for a in r['repetitions'].values()]))
    for s in steps:
        print('STEP %s -> %-18s %+.2f/%+.2f ms beyond_noise=%s' % (s['interval'], s['to'], *s['delta_mean_ms_by_rep'], s['regression_beyond_noise_every_rep']))
    print('DECISION', decision['result'], decision.get('largest_regression_interval'), decision.get('statement'))
    print('PASS report written: history.json history-runs.json decision.json manifest.json; failed attempts preserved:',
          manifest['failed_attempts_preserved'])
    return 0


# ----------------------------------------------------------------- audit --

def audit(args):
    out = Path(args.output)
    m = fc.load(out / 'manifest.json')
    for name, digest in m['sha256'].items():
        if fc.sha_file(out / name) != digest:
            raise EvidenceError(f'SHA256 mismatch {name}')
    print(f'PASS manifest seal: {len(m["sha256"])} evidence files match SHA256')
    if fc.sha_file(fc.HARNESS) != m['harness_sha256'] or fc.sha_file(ch.__file__) != m['chill_sha256']:
        raise EvidenceError('TASK-271 harness or TASK-273 module changed since capture')
    print('PASS harness/chill modules unchanged', m['harness_sha256'][:12], m['chill_sha256'][:12])
    at_capture = m['history_sha256_at_capture']
    preserved = {fc.sha_file(out / name): name for name in m['module_at_capture']}
    for digest in at_capture:
        if fc.sha_file(MODULE) == digest:
            print('PASS capture-time history module equals the current module', digest[:12])
        elif digest in preserved:
            print('PASS capture-time history module preserved byte-for-byte at', preserved[digest], digest[:12],
                  '; current module', fc.sha_file(MODULE)[:12])
        else:
            raise EvidenceError(f'history module {digest} used for captures is neither current nor preserved')
    if len(at_capture) > 2:
        raise EvidenceError(f'raws captured by {len(at_capture)} module revisions')
    for c in m['commands']:
        assert c['argv'] and c['utc_start'] <= c['utc_end'] and isinstance(c['exit_code'], int)
    print(f'PASS {len(m["commands"])} command receipts with argv/UTC start-end/exit codes {m["exit_codes"]};',
          'failed attempts preserved:', m['failed_attempts_preserved'])
    history = fc.load(out / 'history.json')
    if len([t for t in history['trees'] if t['role'] == 'revision']) > 6:
        raise EvidenceError('more than six revisions')
    for t in history['trees']:
        names = sorted(t['runtime_sha256'])
        shown = git_show_hashes(t['full'], names)
        if shown != t['runtime_sha256'] or shown != t['git_show_sha256']:
            raise EvidenceError(f'{t["tree"]}: runtime hashes differ from git show {t["full"]}')
        root = ROOT / t['root']
        if root.exists() and fc.tree_hashes(root) != t['runtime_sha256']:
            raise EvidenceError(f'{t["tree"]}: extracted tree on disk changed')
        subprocess.check_call(['git', 'merge-base', '--is-ancestor', t['full'], 'HEAD'], cwd=ROOT)
        print(f'PASS tree {t["tree"]:<18} {t["full"][:12]} {len(names)} runtime files == git show; static {t["compatibility"]["static"]["result"]}; '
              f'dynamic {t["compatibility"]["dynamic"]["result"] if t["compatibility"]["dynamic"] else None}')
    if fc.sha_file(CONTROLS_271) != history['most_affected']['source_sha256']:
        raise EvidenceError('TASK-271 controls changed')
    if most_affected(fc.load(CONTROLS_271)) != history['most_affected']:
        raise EvidenceError('most affected mode not reproducible')
    print('PASS most affected mode re-derived from sealed TASK-271 controls:', history['most_affected']['mode'],
          json.dumps({k: round(v, 1) for k, v in history['most_affected']['regression_p50_ms_by_mode'].items()}))
    runs_doc = fc.load(out / 'history-runs.json')
    complete = 0
    for name in m['evidence_paths']:
        if not name.startswith('raw/') or not name.endswith('.json'):
            continue
        raw = fc.load(out / name)
        if raw['harness_sha256'] != m['harness_sha256'] or raw['history_sha256'] not in at_capture:
            raise EvidenceError(f'{name} captured by different modules')
        if fc.frames_sha256(raw['frames']) != raw['frames_sha256']:
            raise EvidenceError(f'{name} frames altered')
        tree = next(t for t in history['trees'] if t['tree'] == raw['tree_name'])
        if raw['tree']['files_sha256'] != tree['runtime_sha256']:
            raise EvidenceError(f'{name} served tree differs from history.json')
        if raw.get('result') != 'COMPLETE':
            print('INFO failed attempt preserved', name, raw['result'])
            if any(name == a['raw'] for r in runs_doc['runs'].values() for a in r['repetitions'].values()):
                raise EvidenceError(f'{name} failed but used in rankings')
            continue
        rec = fc.summarize(raw)
        if rec != raw['summary'] or ch.window_density(raw) != raw['density']:
            raise EvidenceError(f'{name} summary/density does not match recomputation')
        if rec['windows'][0]['active_ms'] < raw['settings']['window_ms']:
            raise EvidenceError(f'{name} short window')
        if raw['dimensions']['platform'] not in ISOLATED_PLATFORMS or raw['errors'] or raw['error']:
            raise EvidenceError(f'{name} not isolated or has errors')
        if any(e['state'].get('offer') for e in raw['excluded']) and not raw['settings'].get('offer_shim'):
            raise EvidenceError(f'{name} has continue-offer frames without the shim')
        if {tuple(f['canvas']) for f in raw['frames']} != {(1280, 720)}:
            raise EvidenceError(f'{name} backing is not 1280x720')
        if raw['screenshot'] and fc.sha_file(out / raw['screenshot']['path']) != raw['screenshot']['sha256']:
            raise EvidenceError(f'{name} screenshot changed')
        expected = arm_record(raw, name)
        got = runs_doc['runs'][raw['tree_name']]['repetitions'].get(raw['case'].rsplit('-r', 1)[1])
        if got != expected:
            raise EvidenceError(f'{name} run record differs from recomputation')
        complete += 1
        c = rec['combined']
        print(f'PASS recomputed {raw["case"]:<30} intervals={c["intervals"]} active_ms={c["active_ms"]:.0f} '
              f'mean_ms={mean_ms(raw):.2f} fps={c["average_fps"]:.2f} p50={c["frame_ms"]["p50"]:.2f} p95={c["frame_ms"]["p95"]:.2f} '
              f'deaths={rec["deaths"]} travel={raw["density"]["camera"]["travel_px"]:.0f} platform={raw["dimensions"]["platform"]} '
              f'offer_shim={raw["settings"].get("offer_shim", False)} offer_restarts={len(raw.get("offerRestarts", []))} '
              f'excluded_offer_frames={sum(1 for e in raw["excluded"] if e["state"].get("offer"))}')
    _, rebuilt, steps, noise_max = build(out)
    decision = decide(rebuilt, steps, noise_max)
    for key in ('valid_trees', 'excluded_trees', 'ranking_slowest_first', 'noise', 'steps_chronological', 'controls', 'runs'):
        if rebuilt[key] != runs_doc[key]:
            raise EvidenceError(f'history-runs.json {key} differs from recomputation')
    if decision != fc.load(out / 'decision.json'):
        raise EvidenceError('decision.json differs from recomputation')
    for n in runs_doc['valid_trees']:
        t = next(t for t in history['trees'] if t['tree'] == n)
        if t['compatibility']['static']['result'] != 'STATIC_OK' or t['compatibility']['dynamic']['result'] != 'VALID':
            raise EvidenceError(f'{n} ranked but not compatible')
        if len(runs_doc['runs'][n]['repetitions']) != REPS:
            raise EvidenceError(f'{n} ranked without {REPS} complete repetitions')
    ranked = {r['tree'] for r in runs_doc['ranking_slowest_first']} | {s['from'] for s in steps} | {s['to'] for s in steps}
    for e in runs_doc['excluded_trees']:
        if e['tree'] in ranked:
            raise EvidenceError(f'excluded tree {e["tree"]} appears in rankings')
    print(f'PASS {complete} complete raws recomputed; {len(runs_doc["valid_trees"])} valid trees ranked; '
          f'{len(runs_doc["excluded_trees"])} excluded (failed/incompatible) trees absent from rankings: {runs_doc["excluded_trees"]}')
    print('PASS ranking slowest first:', [(r['tree'], round(r['mean_ms'], 1)) for r in runs_doc['ranking_slowest_first']])
    for s in steps:
        print('PASS step %s -> %-18s %+.2f/%+.2f ms beyond_noise=%s' % (s['interval'], s['to'], *s['delta_mean_ms_by_rep'], s['regression_beyond_noise_every_rep']))
    print('PASS decision reproduced:', decision['result'], decision.get('largest_regression_interval'), '-', decision.get('statement'))
    for name in fc.runtime_files(ROOT):
        if 'artifacts' in Path(name).parts or 'output' in Path(name).parts or 'screenshots' in Path(name).parts:
            continue
        if fc.MARKER in (ROOT / name).read_text(errors='replace'):
            raise EvidenceError(f'diagnostic hook marker in shipped runtime: {name}')
    print('PASS no diagnostic hook marker in the shipped runtime; working branch untouched (trees live under artifacts/)')
    print('PASS evidence audit complete; the performance verdict is separate (decision.json)')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    for name, func in (('select', select), ('run', run), ('report', report), ('audit', audit)):
        p = sub.add_parser(name)
        p.add_argument('--output', required=True)
        p.set_defaults(func=func)
        if name == 'run':
            p.add_argument('--only', help='retry one tree only (changed hypothesis / measurement defect)')
            p.add_argument('--rep', type=int)
            p.add_argument('--offer-shim', action='store_true')
            p.add_argument('--reason', default=None)
    c = sub.add_parser('capture')
    c.add_argument('--root', required=True)
    c.add_argument('--output', required=True)
    c.add_argument('--tree', required=True)
    c.add_argument('--mode', required=True, choices=fc.MODES)
    c.add_argument('--seed', required=True, type=int)
    c.add_argument('--replay-style', default='screening', choices=sorted(ch.REPLAY_STYLES))
    c.add_argument('--case', required=True)
    c.add_argument('--cpu-throttle', type=int, default=1)
    c.add_argument('--warmup-ms', type=int, default=WARMUP_MS)
    c.add_argument('--window-ms', type=int, default=WINDOW_MS)
    c.add_argument('--windows', type=int, default=WINDOWS)
    c.add_argument('--timeout-ms', type=int, default=180000)
    c.add_argument('--offer-shim', action='store_true', help='page-only: answer a visible continue offer with its Restart action')
    c.set_defaults(func=capture)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
