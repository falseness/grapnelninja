"""Bounded feature-cost experiment harness (TASK-271 onwards).

Actions
  capture   one browser session: boot --root, pin density, replay bounded seeded
            input, record raw active frame intervals; write --output/raw/<case>.json
  audit     recompute every metric from the raw files named in --output/manifest.json
            and verify the evidence seals; exits zero for valid evidence whatever
            the performance verdict
  controls  build the control trees (current committed runtime, original TASK-098
            ZIP, almost-empty drawing clone), run the control arms and write
            protocol.json, controls.json and manifest.json under --output

Primary FPS is timed from the requestAnimationFrame timestamp only: one gameLoop
wrapper, no tracing, no readback, no per-call wrappers. Diagnostic hooks are
injected into the page by this script only (marker __featureCost) and never
enter the shipped runtime. Nothing here certifies physical devices or 60 FPS.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve()
ORIGINAL_ZIP = ROOT / 'artifacts/TASK-098/grapnelninja-y8.zip'
ORIGINAL_ZIP_SHA256 = 'a9aed755a55e799a621adb31e1da518d573d5168391971d07948aefb8ac20c91'
ORIGINAL_COMMIT = 'b588d69'
SDK_URL = 'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js'
MARKER = '__featureCost'
PROFILES = {
    'desktop': {'viewport': [1280, 720], 'dpr': 1, 'is_mobile': False, 'has_touch': False, 'input': 'mouse'},
    'touch': {'viewport': [844, 390], 'dpr': 2, 'is_mobile': True, 'has_touch': True, 'input': 'touch'},
}
MODES = ('bad', 'classic')
SEEDS = (1, 4, 49)
DRAW_HOOKS = ['drawBackgroundLayer', 'drawLightsLayer', 'drawBehindForegroundParticlesLayer',
              'drawPlayerTrailLayer', 'drawWorldLayer', 'drawParticlesAndTrailsLayer', 'drawBloomLayer',
              'drawPlayerGlowLayer', 'drawColorGradeLayer', 'drawPlayerLayer', 'drawUILayer',
              'drawFpsCounterLayer']
ALL_DRAW = 'all-draw'
# Settings that must be identical between the two arms of any comparison.
PAIRED_SETTINGS = ('mode', 'profile', 'viewport', 'dpr', 'cpu_throttle', 'seed', 'warmup_ms',
                   'window_ms', 'windows', 'replay_sha256', 'diagnostic')
RUNTIME_SUFFIXES = ('.html', '.js', '.css')


class EvidenceError(AssertionError):
    """Evidence that cannot be used: inconsistent, interrupted, mismatched or incomplete."""


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def utc():
    return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=1, sort_keys=True) + '\n')


def load(path):
    return json.loads(Path(path).read_text())


def runtime_files(root):
    """Served runtime files (html/js/css) below root, relative POSIX paths, sorted."""
    files = [p for p in Path(root).rglob('*') if p.is_file() and p.suffix in RUNTIME_SUFFIXES
             and 'tools' not in p.relative_to(root).parts]
    return sorted(str(p.relative_to(root).as_posix()) for p in files)


def tree_hashes(root):
    return {name: sha_file(Path(root) / name) for name in runtime_files(root)}


# ---------------------------------------------------------------- replay --

def replay_script(seed, profile, total_ms):
    """Bounded seeded grapnel throws: [{t_ms, type: start|end, x, y}] in CSS px.

    Scheduled on the ACTIVE clock (accumulated active frame intervals), so the
    same segment is replayed in every arm regardless of menu/pause gaps. The
    x/y box avoids the HUD menu button (top-right corner) and the left edge.
    """
    width, height = PROFILES[profile]['viewport']
    rng = random.Random(seed * 1000003 + total_ms)
    events, t = [], 400
    while True:
        hold = rng.randint(250, 900)
        if t + hold > total_ms:
            break
        x = round(rng.uniform(0.40, 0.85) * width, 1)
        y = round(rng.uniform(0.15, 0.60) * height, 1)
        events.append({'t_ms': t, 'type': 'start', 'x': x, 'y': y})
        events.append({'t_ms': t + hold, 'type': 'end', 'x': x, 'y': y})
        t += hold + rng.randint(80, 450)
    return events


def frames_sha256(frames):
    """Seal of the raw frame list, stable across JSON round trips (sorted keys)."""
    return sha_bytes(json.dumps(frames, sort_keys=True).encode())


def replay_sha256(script):
    return sha_bytes(json.dumps(script, sort_keys=True).encode())


# --------------------------------------------------------------- metrics --

def percentile(ordered, p):
    """Nearest-rank percentile of an ascending list."""
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * p / 100 + 0.999999) - 1))]


def check_frames(frames):
    """Reject frames that are inactive, non-increasing or arithmetically inconsistent."""
    if len(frames) < 2:
        raise EvidenceError('fewer than two frames')
    for prev, f in zip(frames, frames[1:]):
        if f['t'] <= prev['t']:
            raise EvidenceError('non-increasing timestamps')
        if f['dt'] is not None:
            if f['dt'] <= 0:
                raise EvidenceError('non-positive interval')
            if abs(f['dt'] - (f['t'] - prev['t'])) > 1e-6:
                raise EvidenceError('interval does not equal timestamp difference')
    for f in frames:
        if any(f.get('state', {}).values()):
            raise EvidenceError('inactive frame inside sample')


def metrics(frames):
    """Average FPS and frame-time percentiles from one window of active frames.

    frames[0]['dt'] is ignored (window start). Later dt=None entries are
    inactive gaps: excluded from every statistic and counted in 'gaps'.
    """
    check_frames(frames)
    dts = [f['dt'] for f in frames[1:] if f['dt'] is not None]
    if not dts:
        raise EvidenceError('no active intervals')
    ordered = sorted(dts)
    active = sum(dts)
    return {'frames': len(frames), 'intervals': len(dts),
            'gaps': sum(1 for f in frames[1:] if f['dt'] is None),
            'active_ms': active, 'wall_ms': frames[-1]['t'] - frames[0]['t'],
            'average_fps': len(dts) * 1000 / active,
            'frame_ms': {'p50': percentile(ordered, 50), 'p95': percentile(ordered, 95),
                         'p99': percentile(ordered, 99), 'max': ordered[-1]}}


def split_windows(frames, warmup_ms, window_ms, windows):
    """Cut the active timeline into warmup + N measured windows at frame boundaries.

    The warmup ends at the first frame whose cumulative active time reaches
    warmup_ms; window k ends at the first frame reaching that value plus
    k*window_ms, so every window holds >= window_ms of active intervals. The
    next window starts at the same frame (interval already counted, so its dt
    is reset to None). Raises when the record is too short.
    """
    check_frames(frames)
    acc, start, result, k, targets = 0.0, None, [], 0, None
    for i, f in enumerate(frames):
        if f['dt'] is not None:
            acc += f['dt']
        if start is None and acc >= warmup_ms:
            # Windows are anchored at the actual warmup-end frame, so each one
            # holds at least window_ms of active intervals.
            start, targets = i, [acc + k * window_ms for k in range(1, windows + 1)]
            continue
        if start is not None and k < windows and acc >= targets[k]:
            window = [dict(frames[start], dt=None)] + frames[start + 1:i + 1]
            result.append(window)
            start, k = i, k + 1
            if k == windows:
                return result
    raise EvidenceError(f'incomplete: {k} of {windows} windows after {acc:.0f} active ms')


def compare(control, candidate):
    """Paired comparison; refuses mismatched settings or unequal backing sizes."""
    for key in PAIRED_SETTINGS:
        if control['settings'].get(key) != candidate['settings'].get(key):
            raise EvidenceError(f'mismatched setting {key}: '
                                f'{control["settings"].get(key)!r} != {candidate["settings"].get(key)!r}')
    backing = {tuple(f['canvas']) for arm in (control, candidate) for f in arm['frames']}
    if len(backing) != 1:
        raise EvidenceError(f'unequal backing sizes {sorted(backing)}')
    if list(backing.pop()) != control['dimensions']['canvas']:
        raise EvidenceError('frame backing size differs from recorded dimensions')
    a, b = control['summary']['combined'], candidate['summary']['combined']
    return {'control': control['case'], 'candidate': candidate['case'],
            'backing': control['dimensions']['canvas'],
            'delta_average_fps': b['average_fps'] - a['average_fps'],
            'delta_p50_ms': b['frame_ms']['p50'] - a['frame_ms']['p50'],
            'delta_p95_ms': b['frame_ms']['p95'] - a['frame_ms']['p95'],
            'delta_p99_ms': b['frame_ms']['p99'] - a['frame_ms']['p99']}


def summarize(raw):
    """Windows + metrics recomputed from raw frames (what capture stores and audit checks)."""
    s = raw['settings']
    windows = split_windows(raw['frames'], s['warmup_ms'], s['window_ms'], s['windows'])
    per = [metrics(w) for w in windows]
    combined = metrics([dict(windows[0][0])] + [f for w in windows for f in w[1:]])
    return {'windows': per, 'combined': combined,
            'warmup_frames': raw['frames'].index(next(f for f in raw['frames'] if f['t'] == windows[0][0]['t'])),
            'excluded_frames': len(raw['excluded']), 'deaths': len(raw['deaths']),
            'dispatched_inputs': len(raw['dispatched'])}


# -------------------------------------------------------------- capture --

SEED_SCRIPT = '''(() => {
    let a = %d >>> 0
    Math.random = function() {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
})()'''

INSTRUMENT = '''(cfg) => {
    const FC = window.__featureCost = {cfg, frames: [], excluded: [], deaths: [], dispatched: [],
        activeMs: 0, done: false, error: null, physicsSteps: null, start: performance.now()}
    FC.densityPin = 'absent: no RENDER_BUDGET in this tree (fixed devicePixelRatio backing)'
    if (typeof RENDER_BUDGET !== 'undefined') {
        RENDER_BUDGET.densityLimit = cfg.dpr
        RENDER_BUDGET.observe = () => false
        FC.densityPin = 'pinned: RENDER_BUDGET.densityLimit=' + cfg.dpr + '; adaptive observe disabled (page only)'
    }
    FC.features = (typeof STYLE !== 'undefined' && STYLE.features) ? Object.assign({}, STYLE.features) : null
    FC.quality = typeof QUALITY !== 'undefined'
        ? Object.fromEntries(Object.entries(QUALITY).filter(([k, v]) => typeof v !== 'function')) : null
    FC.ablated = []
    for (const name of cfg.ablate) {
        if (name === 'all-draw') {
            window.draw = function() { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, width, height) }
            FC.ablated.push('draw -> clear only (all-draw)')
        } else if (typeof window[name] === 'function') {
            window[name] = function() {}
            FC.ablated.push(name)
        } else FC.ablated.push(name + ':ABSENT')
    }
    if (cfg.diagnostic && typeof window.physics === 'function') {
        const physics = window.physics
        FC.physicsSteps = 0
        window.physics = function() { FC.physicsSteps++; return physics.apply(this, arguments) }
    }
    if (typeof window.reStart === 'function') {
        const reStart = window.reStart
        window.reStart = function() { FC.deaths.push({activeMs: FC.activeMs, t: performance.now()}); return reStart.apply(this, arguments) }
    } else FC.deathHook = 'ABSENT'
    const state = () => ({menu: !!menu.visible, paused: !!menu.gamePaused,
        offer: typeof continueOffer !== 'undefined' && !!continueOffer.visible, hidden: !!document.hidden,
        ad: (typeof adOpen !== 'undefined' && !!adOpen) || (typeof interstitialPending !== 'undefined' && !!interstitialPending)})
    const queue = cfg.replay.slice()
    let touch = null
    const fire = ev => {
        const target = document.elementFromPoint(ev.x, ev.y) || document.body
        if (cfg.input === 'touch') {
            if (ev.type === 'start') touch = new Touch({identifier: 0, target, clientX: ev.x, clientY: ev.y})
            target.dispatchEvent(new TouchEvent(ev.type === 'start' ? 'touchstart' : 'touchend',
                {bubbles: true, cancelable: true, changedTouches: [touch], touches: ev.type === 'start' ? [touch] : []}))
        } else {
            document.dispatchEvent(new MouseEvent(ev.type === 'start' ? 'mousedown' : 'mouseup',
                {bubbles: true, cancelable: true, clientX: ev.x, clientY: ev.y, button: 0}))
        }
        FC.dispatched.push({t_ms: ev.t_ms, type: ev.type, activeMs: Math.round(FC.activeMs * 10) / 10})
    }
    FC.warmupEndMs = null
    const loop = window.gameLoop
    let previous = null
    window.gameLoop = function(t) {
        if (!FC.done) {
            const s = state()
            if (!s.menu && !s.paused && !s.offer && !s.hidden && !s.ad) {
                const dt = previous === null ? null : t - previous
                previous = t
                if (dt !== null) FC.activeMs += dt
                FC.frames.push({t, dt, canvas: [canvas.width, canvas.height], state: s})
                while (queue.length && FC.activeMs >= queue[0].t_ms) fire(queue.shift())
                if (FC.warmupEndMs === null && FC.activeMs >= cfg.warmup_ms) FC.warmupEndMs = FC.activeMs
                if (FC.warmupEndMs !== null && FC.activeMs >= FC.warmupEndMs + cfg.windows * cfg.window_ms) {
                    FC.done = true; FC.end = performance.now() }
            } else { FC.excluded.push({t, state: s}); previous = null }
        }
        try { return loop.call(this, t) }
        catch (e) { FC.error = String(e && e.stack || e); throw e }
    }
}'''

DIMENSIONS = '''() => { const r = canvas.getBoundingClientRect(); return {
    canvas: [canvas.width, canvas.height], css: [r.width, r.height], dpr: devicePixelRatio,
    viewport: [innerWidth, innerHeight], logical: [width, height],
    platform: typeof PLATFORM !== 'undefined' ? PLATFORM.environment : 'absent',
    version: typeof version !== 'undefined' ? version : null} }'''

BOOTED = '''() => typeof menu !== 'undefined' && typeof startGame === 'function'
    && (!document.getElementById('loading') || document.getElementById('loading').hidden)
    && (typeof PLATFORM === 'undefined' || PLATFORM.environment !== 'pending')'''


def environment(browser):
    gpu = browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu']
    return {'os': platform.platform(), 'python': platform.python_version(),
            'playwright': importlib.metadata.version('playwright'), 'browser': browser.version,
            'browser_args': ['--no-sandbox', 'headless'], 'cpu_count': os.cpu_count(),
            'loadavg': os.getloadavg(), 'gpu': gpu}


def new_context(browser, profile, seed, network):
    p = PROFILES[profile]
    ctx = browser.new_context(viewport={'width': p['viewport'][0], 'height': p['viewport'][1]},
                              device_scale_factor=p['dpr'], is_mobile=p['is_mobile'],
                              has_touch=p['has_touch'], service_workers='block')

    def route(r):
        u = r.request.url
        if u == SDK_URL:
            network.append('SDK_BLOCKED ' + u); r.abort()
        elif u.startswith('http://127.0.0.1'):
            network.append('LOCAL ' + u); r.continue_()
        else:
            network.append('BLOCKED ' + u); r.abort()
    ctx.route('**/*', route)
    ctx.add_init_script(SEED_SCRIPT % seed)
    return ctx


def raw_path(output, case):
    """Never overwrite: failed or repeated attempts keep their own file."""
    raw = Path(output) / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    path, n = raw / f'{case}.json', 1
    while path.exists():
        n += 1
        path = raw / f'{case}.attempt{n}.json'
    return path


def capture(args):
    from browser_test_support import start_browser_test
    root = Path(args.root).resolve()
    if not (root / 'index.html').exists():
        raise SystemExit(f'--root {root} has no index.html')
    for name in args.ablate:
        if name != ALL_DRAW and name not in DRAW_HOOKS:
            raise SystemExit(f'unknown --ablate {name}; choose {ALL_DRAW} or one of {DRAW_HOOKS}')
    profile = PROFILES[args.profile]
    total = args.warmup_ms + args.windows * args.window_ms
    replay = replay_script(args.seed, args.profile, total + 1000)
    settings = {'mode': args.mode, 'profile': args.profile, 'viewport': profile['viewport'],
                'dpr': profile['dpr'], 'is_mobile': profile['is_mobile'], 'has_touch': profile['has_touch'],
                'input': profile['input'], 'cpu_throttle': args.cpu_throttle, 'seed': args.seed,
                'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows': args.windows,
                'replay_sha256': replay_sha256(replay), 'ablate': list(args.ablate),
                'diagnostic': bool(args.diagnostic), 'density': 'pinned to profile DPR; adaptive observe disabled',
                'sdk_isolation': 'cdn.y8.com SDK request aborted; all non-local requests aborted; '
                                 'PLATFORM falls back to the local adapter (no ads, instant restart on death)'}
    cfg = {'dpr': profile['dpr'], 'input': profile['input'], 'ablate': list(args.ablate),
           'diagnostic': bool(args.diagnostic), 'replay': replay, 'warmup_ms': args.warmup_ms,
           'window_ms': args.window_ms, 'windows': args.windows}
    raw = {'case': args.case, 'settings': settings, 'tree': {'root': str(root), 'files_sha256': tree_hashes(root)},
           'harness_sha256': sha_file(HARNESS), 'argv': sys.argv, 'started_utc': utc(), 'replay': replay,
           'network': [], 'errors': [], 'console_errors': []}
    network, exit_code = raw['network'], 1
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        raw['environment'] = environment(browser)
        ctx = new_context(browser, args.profile, args.seed, network)
        stack.callback(ctx.close)
        page = ctx.new_page()
        page.on('pageerror', lambda e: raw['errors'].append(str(e)))
        page.on('console', lambda m: raw['console_errors'].append(m.text) if m.type == 'error' else None)
        ctx.new_cdp_session(page).send('Emulation.setCPUThrottlingRate', {'rate': args.cpu_throttle})
        page.goto(url + 'index.html', wait_until='domcontentloaded')
        page.wait_for_function(BOOTED, timeout=60000)
        page.evaluate(INSTRUMENT, cfg)
        page.evaluate('mode => startGame(mode)', args.mode)
        try:
            page.wait_for_function(f'{MARKER}.done || {MARKER}.error', timeout=args.timeout_ms)
        except Exception as e:  # keep the partial record as a failed attempt
            raw['errors'].append('timeout: ' + str(e).splitlines()[0])
        page.evaluate(f'() => {{ {MARKER}.cfg.replay = "<see raw.replay>" }}')
        raw.update(page.evaluate(MARKER))
        raw['dimensions'] = page.evaluate(DIMENSIONS)
        raw['ended_utc'] = utc()
    raw['frames_sha256'] = frames_sha256(raw['frames'])
    try:
        if raw['errors'] or raw['error']:
            raise EvidenceError('page errors: ' + json.dumps(raw['errors'] + [raw['error']]))
        if raw['dimensions']['platform'] not in ('disabled', 'absent'):
            raise EvidenceError('SDK isolation failed: ' + str(raw['dimensions']['platform']))
        if raw['dimensions']['version'] != args.mode:
            raise EvidenceError('mode not started: ' + str(raw['dimensions']['version']))
        if len({tuple(f['canvas']) for f in raw['frames']} | {tuple(raw['dimensions']['canvas'])}) != 1:
            raise EvidenceError('backing size changed during the capture')
        raw['summary'] = summarize(raw)
        raw['result'] = 'COMPLETE'
        exit_code = 0
    except EvidenceError as e:
        raw['summary'], raw['result'] = None, 'FAILED: ' + str(e)
    path = raw_path(args.output, args.case)
    dump(path, raw)
    c = raw['summary']['combined'] if raw['summary'] else None
    print(('PASS' if exit_code == 0 else 'FAIL'), args.case, path.relative_to(ROOT) if path.is_relative_to(ROOT) else path,
          raw['result'], 'backing=' + str(raw['dimensions']['canvas']),
          'fps=%.2f p50=%.2f p95=%.2f p99=%.2f max=%.2f active_ms=%.0f deaths=%d' % (
              c['average_fps'], c['frame_ms']['p50'], c['frame_ms']['p95'], c['frame_ms']['p99'],
              c['frame_ms']['max'], c['active_ms'], raw['summary']['deaths']) if c else '', flush=True)
    return exit_code


# ------------------------------------------------------------- controls --

def git(*argv):
    return subprocess.check_output(['git', *argv], cwd=ROOT, text=True).strip()


def build_trees(output):
    """current = `git archive HEAD`; original = verified TASK-098 ZIP. Returns identity."""
    trees = Path(output) / 'trees'
    head = git('rev-parse', 'HEAD')
    dirty = git('status', '--porcelain', '--untracked-files=no')
    current = trees / 'current'
    if current.exists():
        shutil.rmtree(current)
    current.mkdir(parents=True)
    tar = subprocess.check_output(['git', 'archive', '--format=tar', head], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(current, filter='data')
    for name in runtime_files(current):  # the served tree must equal the worktree runtime
        if (ROOT / name).read_bytes() != (current / name).read_bytes():
            raise EvidenceError(f'worktree runtime differs from HEAD: {name}')
    if sha_file(ORIGINAL_ZIP) != ORIGINAL_ZIP_SHA256:
        raise EvidenceError('original ZIP changed')
    original = trees / 'original'
    if original.exists():
        shutil.rmtree(original)
    original.mkdir(parents=True)
    with zipfile.ZipFile(ORIGINAL_ZIP) as z:
        members = {n: sha_bytes(z.read(n)) for n in z.namelist() if not n.endswith('/')}
        z.extractall(original)
    original_commit = git('rev-parse', ORIGINAL_COMMIT)
    for name, digest in members.items():
        data = subprocess.check_output(['git', 'show', f'{original_commit}:{name}'], cwd=ROOT)
        if sha_bytes(data) != digest:
            raise EvidenceError(f'ZIP member {name} differs from {original_commit}')
    return {'current_commit': head, 'current_dirty_runtime': dirty, 'current_tar_sha256': sha_bytes(tar),
            'current_files_sha256': tree_hashes(current),
            'original_zip': str(ORIGINAL_ZIP.relative_to(ROOT)), 'original_zip_sha256': ORIGINAL_ZIP_SHA256,
            'original_commit': original_commit, 'original_members_sha256': members,
            'original_alias': f'all {len(members)} ZIP members byte-identical to {original_commit}',
            'trees': {'current': str(current), 'original': str(original)}}


def environment_ceiling(profile):
    """requestAnimationFrame cadence of an empty page: the most this environment can show."""
    from browser_test_support import start_browser_test
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT / 'tools/fixtures', stack.callback)
        ctx = new_context(browser, profile, 1, [])
        stack.callback(ctx.close)
        page = ctx.new_page()
        page.set_content('<canvas id=c width=64 height=64></canvas>')
        dts = page.evaluate('''() => new Promise(done => { const ts = []
            const step = t => { ts.push(t); if (ts.length < 181) requestAnimationFrame(step)
                else done(ts.slice(1).map((v, i) => v - ts[i])) }
            requestAnimationFrame(step) })''')
        gpu = browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu']
    ordered = sorted(dts)
    return {'profile': profile, 'frames': len(dts), 'average_fps': len(dts) * 1000 / sum(dts),
            'frame_ms': {'p50': percentile(ordered, 50), 'p95': percentile(ordered, 95), 'max': ordered[-1]},
            'renderer': gpu['auxAttributes'].get('glRenderer'), 'software_rendering': True,
            'note': 'Headless software Chromium ceiling; failing to reach 60 here is not physical-device certification'}


def protocol():
    return {
        'task': 'TASK-271', 'harness': 'tools/y8_feature_cost.py', 'harness_sha256': sha_file(HARNESS),
        'profiles': {'desktop': {'viewport': [1280, 720], 'DPR': 1, 'input': 'mouse'},
                     'touch': {'viewport': [844, 390], 'DPR': 2, 'is_mobile': True, 'has_touch': True, 'input': 'touch'}},
        'density': 'pinned: RENDER_BUDGET.densityLimit = profile DPR and adaptive observe disabled inside the '
                   'diagnostic clone page only; trees without RENDER_BUDGET use devicePixelRatio; backing size '
                   'recorded per frame and must be equal in every paired arm',
        'cpu_throttle': 1, 'modes': list(MODES), 'seeds': list(SEEDS), 'screening_seed': 4,
        'feature_flags': 'STYLE.features and QUALITY are read from each arm page and recorded in raw files; '
                         'nothing assumes bloom/colorGrade/extrusion are active',
        'input': 'deterministic bounded replay: seeded grapnel press/release script generated by replay_script('
                 'seed, profile, total_ms), scheduled on the active clock, identical SHA256 in every paired arm; '
                 'mouse events on desktop, TouchEvents on touch',
        'state': 'every frame records menu/paused/offer/hidden/ad; inactive frames are excluded and reset the '
                 'interval; deaths (reStart) are recorded and never suppressed; a dying replay keeps the same '
                 'documented segment in every paired arm',
        'warmup_ms': 5000, 'window_ms': 10000,
        'screening': 'two 10-second measured windows per arm from alternating control/candidate order '
                     '(control, candidate, candidate, control), fixed seed 4, equal state segment (same replay '
                     'SHA256, same warmup, same windows)',
        'shortlist': 'three alternating 30-second pairs per mode (--window-ms 30000, order control/candidate '
                     'alternating); repeat target touch cases (--profile touch) in integration',
        'timing': 'primary FPS from the requestAnimationFrame timestamp via one gameLoop wrapper; no tracing, '
                  'readback or per-call wrappers; diagnostic captures (--diagnostic, stage timing, traces) '
                  'run separately and are never paired with primary captures',
        'metrics': 'raw intervals, average FPS, p50/p95/p99/max frame time, active-window duration (and wall '
                   'duration with gap count) per window and combined',
        'controls': ['current: unchanged committed runtime (git archive HEAD)',
                     'original: TASK-098 ZIP, byte-identical to its commit',
                     'almost-empty: current tree with draw() replaced by a clear in the page (all-draw)'],
        'ceiling': 'environment ceiling measured on an empty page before the arms',
        'limits': 'software headless Chromium; no physical-device, 60 FPS or release-readiness claim; '
                  'diagnostic hooks never enter the shipped runtime',
    }


def controls(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    started = utc()
    commands = []

    def run(argv, label):
        t0 = utc()
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        commands.append({'label': label, 'argv': argv, 'utc_start': t0, 'utc_end': utc(),
                         'exit_code': r.returncode, 'stdout': r.stdout[-4000:], 'stderr': r.stderr[-4000:]})
        print(r.stdout.strip() or r.stderr.strip()[-500:], flush=True)
        return r.returncode

    identity = build_trees(out)
    ceiling = environment_ceiling('desktop')
    arms = {'current': (identity['trees']['current'], []),
            'original': (identity['trees']['original'], []),
            'almost-empty': (identity['trees']['current'], [ALL_DRAW])}
    order = ['current', 'original', 'almost-empty']
    attempts = []
    for mode in MODES:
        sequence = order + order[::-1]  # alternating: no arm is always first or last
        for rep, arm in enumerate(sequence, 1):
            root, ablate = arms[arm]
            case = f'{arm}-{mode}-desktop-s4-w{rep}'
            argv = [sys.executable, 'tools/y8_feature_cost.py', 'capture', '--root', root, '--output', str(out),
                    '--mode', mode, '--seed', '4', '--case', case, '--profile', 'desktop', '--windows', '1',
                    '--window-ms', str(args.window_ms), '--warmup-ms', str(args.warmup_ms)]
            for a in ablate:
                argv += ['--ablate', a]
            code = run(argv, f'{arm}/{mode}/{rep}')
            attempts.append({'arm': arm, 'mode': mode, 'rep': rep, 'case': case, 'exit_code': code})
    if args.touch_smoke:
        argv = [sys.executable, 'tools/y8_feature_cost.py', 'capture', '--root', identity['trees']['current'],
                '--output', str(out), '--mode', 'bad', '--seed', '4', '--case', 'smoke-current-bad-touch-s4',
                '--profile', 'touch', '--windows', '1', '--window-ms', '5000', '--warmup-ms', '2000']
        run(argv, 'touch-smoke (CLI check, not a control)')
    raw_files = sorted(p for p in (out / 'raw').glob('*.json'))
    raws = {p.name: load(p) for p in raw_files}
    report = {'identity': {k: v for k, v in identity.items() if k != 'trees'}, 'environment_ceiling': ceiling,
              'protocol': 'protocol.json', 'arms': {}, 'pairs': [], 'attempts': attempts}
    for mode in MODES:
        for arm in order:
            runs = [r for r in raws.values() if r['case'].startswith(f'{arm}-{mode}-desktop')
                    and r.get('result') == 'COMPLETE']
            report['arms'][f'{arm}-{mode}'] = {
                'raw': [f'raw/{n}' for n, r in raws.items() if r in runs],
                'windows': [w for r in runs for w in r['summary']['windows']],
                'backing': sorted({tuple(r['dimensions']['canvas']) for r in runs}),
                'features': [r['features'] for r in runs][:1], 'quality': [r['quality'] for r in runs][:1],
                'density_pin': sorted({r['densityPin'] for r in runs}),
                'deaths': sum(r['summary']['deaths'] for r in runs),
                'average_fps_per_window': [w['average_fps'] for r in runs for w in r['summary']['windows']],
                'complete_windows': len(runs)}
        for candidate in ('original', 'almost-empty'):
            for rep_c, rep_k in ((1, 2), (6, 5)) if candidate == 'original' else ((1, 3), (6, 4)):
                a = next((r for r in raws.values() if r['case'] == f'current-{mode}-desktop-s4-w{rep_c}' and r.get('summary')), None)
                b = next((r for r in raws.values() if r['case'] == f'{candidate}-{mode}-desktop-s4-w{rep_k}' and r.get('summary')), None)
                if not a or not b:
                    report['pairs'].append({'control': f'current-{mode}-{rep_c}', 'candidate': f'{candidate}-{mode}-{rep_k}', 'result': 'MISSING'})
                    continue
                try:
                    report['pairs'].append(dict(compare(a, b), result='PAIRED'))
                except EvidenceError as e:
                    report['pairs'].append({'control': a['case'], 'candidate': b['case'], 'result': 'REJECTED: ' + str(e)})
    report['verdict'] = ('Controls established on software headless Chromium. Average FPS deltas describe this '
                         'environment only: not 60 FPS, not release readiness, not physical devices.')
    dump(out / 'protocol.json', protocol())
    dump(out / 'controls.json', report)
    ev = {'manifest.json', 'protocol.json', 'controls.json'}
    evidence = sorted(['protocol.json', 'controls.json'] + [f'raw/{p.name}' for p in raw_files])
    manifest = {'task': 'TASK-271', 'utc_start': started, 'utc_end': utc(),
                'controls_argv': sys.argv, 'commands': commands, 'source_revision': identity['current_commit'],
                'source_dirty_runtime': identity['current_dirty_runtime'],
                'harness_sha256': sha_file(HARNESS), 'support_sha256': sha_file(ROOT / 'tools/browser_test_support.py'),
                'candidate_hashes': {'current_tar_sha256': identity['current_tar_sha256'],
                                     'current_files_sha256': identity['current_files_sha256'],
                                     'original_zip_sha256': identity['original_zip_sha256'],
                                     'original_members_sha256': identity['original_members_sha256']},
                'environment': {**{k: v for k, v in next(iter(raws.values()))['environment'].items()}, 'ceiling': ceiling}
                if raws else {'ceiling': ceiling},
                'fixed': {'profile': PROFILES['desktop'], 'backing_size_by_arm': {k: v['backing'] for k, v in report['arms'].items()},
                          'seed': 4, 'warmup_ms': args.warmup_ms, 'window_ms': args.window_ms, 'windows_per_capture': 1,
                          'input': 'replay_script(4, desktop, total_ms) scheduled on the active clock',
                          'state': 'per-frame menu/paused/offer/hidden/ad recorded; deaths recorded via reStart hook'},
                'sdk_isolation': next(iter(raws.values()))['settings']['sdk_isolation'] if raws else None,
                'evidence_paths': evidence, 'sha256': {name: sha_file(out / name) for name in evidence},
                'failed_attempts_preserved': [c['label'] for c in commands if c['exit_code'] != 0],
                'note': 'A successful evidence audit is separate from the performance verdict.'}
    dump(out / 'manifest.json', manifest)
    print('PASS controls written:', out / 'controls.json', 'failed attempts:', manifest['failed_attempts_preserved'])
    return 0


# ---------------------------------------------------------------- audit --

def audit(args):
    out = Path(args.output)
    m = load(out / 'manifest.json')
    for name, digest in m['sha256'].items():
        if sha_file(out / name) != digest:
            raise EvidenceError(f'SHA256 mismatch {name}')
    print(f'PASS manifest seal: {len(m["sha256"])} evidence files match SHA256')
    if sha_file(HARNESS) != m['harness_sha256']:
        raise EvidenceError('harness changed since capture')
    print('PASS harness sha256 unchanged', m['harness_sha256'])
    if sha_file(ORIGINAL_ZIP) != m['candidate_hashes']['original_zip_sha256']:
        raise EvidenceError('original ZIP changed')
    for c in m['commands']:
        assert c['argv'] and c['utc_start'] <= c['utc_end'] and isinstance(c['exit_code'], int)
    print(f'PASS {len(m["commands"])} commands with argv/UTC start-end/exit codes;',
          'failed attempts preserved:', m['failed_attempts_preserved'])
    report = load(out / 'controls.json')
    raws, complete = {}, {}
    for name in m['evidence_paths']:
        if not name.startswith('raw/'):
            continue
        raw = load(out / name)
        raws[name] = raw
        if raw['harness_sha256'] != m['harness_sha256']:
            raise EvidenceError(f'{name} captured by a different harness')
        if frames_sha256(raw['frames']) != raw['frames_sha256']:
            raise EvidenceError(f'{name} frames altered')
        if raw.get('result') != 'COMPLETE':
            print('INFO failed attempt preserved', name, raw.get('result'))
            continue
        if raw['case'] in complete:
            raise EvidenceError(f'duplicate complete case {raw["case"]}')
        complete[raw['case']] = raw
        recomputed = summarize(raw)
        if recomputed != raw['summary']:
            raise EvidenceError(f'{name} summary does not match recomputation')
        sizes = {tuple(f['canvas']) for f in raw['frames']}
        if sizes != {tuple(raw['dimensions']['canvas'])}:
            raise EvidenceError(f'{name} backing size varies')
        if raw['dimensions']['platform'] not in ('disabled', 'absent'):
            raise EvidenceError(f'{name} SDK not isolated')
        if raw['errors'] or raw['error']:
            raise EvidenceError(f'{name} has page errors')
        for w in recomputed['windows']:
            if w['active_ms'] < raw['settings']['window_ms']:
                raise EvidenceError(f'{name} short window')
        c = recomputed['combined']
        print(f'PASS recomputed {raw["case"]}: intervals={c["intervals"]} active_ms={c["active_ms"]:.1f} '
              f'wall_ms={c["wall_ms"]:.1f} gaps={c["gaps"]} fps={c["average_fps"]:.2f} '
              f'p50={c["frame_ms"]["p50"]:.2f} p95={c["frame_ms"]["p95"]:.2f} p99={c["frame_ms"]["p99"]:.2f} '
              f'max={c["frame_ms"]["max"]:.2f} backing={raw["dimensions"]["canvas"]} '
              f'deaths={recomputed["deaths"]} excluded_frames={recomputed["excluded_frames"]} '
              f'features={json.dumps(raw["features"], sort_keys=True)}')
    for key, arm in report['arms'].items():
        runs = [raws[p] for p in arm['raw']]
        if any(r.get('result') != 'COMPLETE' for r in runs):
            raise EvidenceError(f'{key} lists an incomplete raw file')
        windows = [w for r in runs for w in summarize(r)['windows']]
        if windows != arm['windows']:
            raise EvidenceError(f'{key} windows differ from raw recomputation')
        print(f'PASS arm {key}: {len(windows)} windows, fps per window {[round(w["average_fps"], 2) for w in windows]}, '
              f'backing {arm["backing"]}, density {arm["density_pin"]}, deaths {arm["deaths"]}')
    for pair in report['pairs']:
        if pair['result'] == 'PAIRED':
            check = compare(complete[pair['control']], complete[pair['candidate']])
            if dict(check, result='PAIRED') != pair:
                raise EvidenceError('pair differs from recomputation')
            print(f'PASS pair {pair["control"]} -> {pair["candidate"]}: dFPS={pair["delta_average_fps"]:+.2f} '
                  f'dp50={pair["delta_p50_ms"]:+.2f}ms dp95={pair["delta_p95_ms"]:+.2f}ms backing={pair["backing"]}')
        else:
            print('INFO pair', pair['control'], pair['candidate'], pair['result'])
    for name in runtime_files(ROOT):
        if MARKER in (ROOT / name).read_text(errors='replace'):
            raise EvidenceError(f'diagnostic hook marker in shipped runtime: {name}')
    print('PASS no diagnostic hook marker in', len(runtime_files(ROOT)), 'shipped runtime files')
    env = m['environment']
    print('PASS environment: os=%s browser=%s playwright=%s gpu=%s ceiling_fps=%.2f (%s)' % (
        env['os'], env['browser'], env['playwright'], env['gpu']['auxAttributes'].get('glRenderer'),
        env['ceiling']['average_fps'], env['ceiling']['note']))
    print('PASS evidence audit complete; performance verdict is separate:', report['verdict'])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    c = sub.add_parser('capture')
    c.add_argument('--root', required=True, help='served game tree (directory with index.html)')
    c.add_argument('--output', required=True, help='evidence directory; raw/<case>.json is written there')
    c.add_argument('--mode', required=True, choices=MODES)
    c.add_argument('--seed', required=True, type=int)
    c.add_argument('--case', required=True, help='case id, used as the raw file name')
    c.add_argument('--profile', default='desktop', choices=sorted(PROFILES))
    c.add_argument('--cpu-throttle', type=int, default=1)
    c.add_argument('--warmup-ms', type=int, default=5000)
    c.add_argument('--window-ms', type=int, default=10000)
    c.add_argument('--windows', type=int, default=1)
    c.add_argument('--ablate', action='append', default=[], help=f'{ALL_DRAW} or a draw layer hook (diagnostic only)')
    c.add_argument('--diagnostic', action='store_true', help='add physics step counter (never paired with primary)')
    c.add_argument('--timeout-ms', type=int, default=240000)
    c.set_defaults(func=capture)
    a = sub.add_parser('audit')
    a.add_argument('--output', required=True)
    a.set_defaults(func=audit)
    k = sub.add_parser('controls')
    k.add_argument('--output', required=True)
    k.add_argument('--warmup-ms', type=int, default=5000)
    k.add_argument('--window-ms', type=int, default=10000)
    k.add_argument('--touch-smoke', action='store_true')
    k.set_defaults(func=controls)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
