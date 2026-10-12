#!/usr/bin/env python3
"""Offline owner benchmark runner for Grapnel Ninja (TASK-283).

Actions
  build     assemble a self-contained package: the committed runtime (HEAD) with
            the public SDK <script> replaced by bench.js, build.json identity,
            this tool, docs, schema, tests
  serve     local HTTP server for the package (127.0.0.1 by default, --lan for
            phones on the same Wi-Fi); accepts result POSTs into results/
  validate  schema + build identity + frame arithmetic + pause gaps + verdict
            inputs recomputed from the raw intervals of an exported result
  summarize per-run table over a results directory
  inspect   static network-isolation / measurement-invariance report
  replay    print the deterministic replay for a seed (cross-check with bench.js)

Nothing here certifies a device or 60 FPS: the validator checks evidence
integrity and recomputes verdict inputs; the verdict belongs to the evaluator.
"""
import argparse
import difflib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
SCHEMA_ID = 'grapnelninja-bench-result/1'
SDK_TAG_RE = re.compile(r'^(\s*)<script src="https://cdn\.y8\.com/minimal-sdk/2-0/y8\.min\.js" async></script>\s*$', re.M)
BENCH_TAG = '<script src="bench.js"></script>'
PACKAGE_FILES = ['benchtool.py', 'bench.js', 'README.md', 'OWNER-CHECKLIST.txt', 'result-schema.json',
                 'test_bench_runner.py', 'index.html']
STANDARD = {'warmup_ms': 5000, 'run_ms': 60000, 'repetitions_target': 3}
ROLLING_MS = 10000
MAX_POST = 32 * 1024 * 1024


class Rejected(Exception):
    """Evidence that cannot be used."""


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    return sha_bytes(Path(p).read_bytes())


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(v):
    """== bench.js canonical(): sorted keys, no spaces, no ASCII escaping."""
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha_canonical(v):
    return sha_bytes(canonical(v).encode())


# ------------------------------------------------------------------ PRNG --

def mulberry32(a):
    a &= 0xFFFFFFFF
    M = 0xFFFFFFFF

    def imul(x, y):
        return (x * y) & M

    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & M
        t = a
        t = imul(t ^ (t >> 15), t | 1)
        t = (t ^ ((t + imul(t ^ (t >> 7), t | 61)) & M)) & M
        return ((t ^ (t >> 14)) & M) / 4294967296
    return rnd


def replay_fractions(seed, total_ms):
    """Mirror of bench.js replayFractions: bounded seeded grapnel throws."""
    rnd = mulberry32(seed * 1000003 + total_ms)

    def randint(a, b):
        return a + math.floor(rnd() * (b - a + 1))

    def uniform(a, b):
        return a + rnd() * (b - a)

    def r4(x):
        return math.floor(x * 10000 + 0.5) / 10000
    events, t = [], 400
    while True:
        hold = randint(250, 900)
        if t + hold > total_ms:
            break
        fx, fy = r4(uniform(0.40, 0.85)), r4(uniform(0.15, 0.60))
        events.append({'t_ms': t, 'type': 'start', 'fx': fx, 'fy': fy})
        events.append({'t_ms': t + hold, 'type': 'end', 'fx': fx, 'fy': fy})
        t += hold + randint(80, 450)
    return events


# ------------------------------------------------------------------ seed --

_JS_DECIMAL_RE = re.compile(r'^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$')
_JS_RADIX_RE = re.compile(r'^0([xXoObB])([0-9a-fA-F]+)$')
SEED_NONE_INSTALLED = 'none (native Math.random)'


def js_number(text):
    """Mirror of JavaScript Number(string) for the ?seed= query value: trimmed
    decimal / exponent / 0x 0o 0b / Infinity forms, '' -> 0, anything else NaN."""
    t = str(text).strip()
    if t == '':
        return 0.0
    if _JS_DECIMAL_RE.match(t):
        return float(t)
    m = _JS_RADIX_RE.match(t)
    if m:
        base = {'x': 16, 'o': 8, 'b': 2}[m.group(1).lower()]
        try:
            return float(int(m.group(2), base))
        except ValueError:
            return math.nan
    if re.match(r'^[+-]?Infinity$', t):
        return -math.inf if t.startswith('-') else math.inf
    return math.nan


def to_uint32(x):
    """JavaScript `x >>> 0`: NaN / +-Infinity -> 0, truncate toward zero, modulo 2**32."""
    if math.isnan(x) or math.isinf(x):
        return 0
    return int(math.trunc(x)) % 0x100000000


def seed_value(seed_setting):
    """bench.js: settings.seed === 'none' ? null : (Number(settings.seed) >>> 0)."""
    return None if seed_setting == 'none' else to_uint32(js_number(seed_setting))


def seed_installed_label(seed_setting):
    """bench.js installSeed(): 'mulberry32(<uint32>)' or 'none (native Math.random)'."""
    v = seed_value(seed_setting)
    return SEED_NONE_INSTALLED if v is None else f'mulberry32({v})'


# --------------------------------------------------------------- metrics --

def percentile(ordered, p):
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * p / 100) - 1))]


def check_frames(frames):
    """Frame arithmetic: increasing timestamps; dt equals the timestamp difference
    whenever it is not null; null dt only as the first frame or after a gap."""
    if not isinstance(frames, list) or len(frames) < 2:
        raise Rejected('fewer than two frames')
    for i, f in enumerate(frames):
        if not (isinstance(f, list) and len(f) == 2 and isinstance(f[0], (int, float))
                and (f[1] is None or isinstance(f[1], (int, float)))):
            raise Rejected(f'frame {i} malformed: {f!r}')
        if i == 0:
            if f[1] is not None:
                raise Rejected('first frame carries an interval')
            continue
        prev = frames[i - 1]
        if f[0] <= prev[0]:
            raise Rejected(f'non-increasing timestamp at frame {i}')
        if f[1] is not None:
            if f[1] <= 0:
                raise Rejected(f'non-positive interval at frame {i}')
            if abs(f[1] - (f[0] - prev[0])) > 1e-6:
                raise Rejected(f'interval does not equal timestamp difference at frame {i}')


def metrics(frames):
    check_frames(frames)
    dts = [f[1] for f in frames[1:] if f[1] is not None]
    if not dts:
        raise Rejected('no active intervals')
    ordered = sorted(dts)
    active = sum(dts)
    return {'frames': len(frames), 'intervals': len(dts), 'gaps': sum(1 for f in frames[1:] if f[1] is None),
            'active_ms': active, 'wall_ms': frames[-1][0] - frames[0][0], 'average_fps': len(dts) * 1000 / active,
            'frame_ms': {'p50': percentile(ordered, 50), 'p95': percentile(ordered, 95),
                         'p99': percentile(ordered, 99), 'max': ordered[-1]}}


def rolling_windows(frames, window_ms=ROLLING_MS):
    """Every window of >= window_ms contiguous active intervals (a gap breaks it)."""
    out = []
    for i in range(len(frames)):
        acc, n, j = 0.0, 0, i + 1
        while j < len(frames):
            if frames[j][1] is None:
                break
            acc += frames[j][1]
            n += 1
            if acc >= window_ms:
                break
            j += 1
        if acc >= window_ms:
            out.append({'start': i, 'end': j, 'intervals': n, 'active_ms': acc, 'fps': n * 1000 / acc})
    return out


GAP_TOLERANCE_MS = 250.0  # an inactive-state sample / stretch edge must fall inside the gap, with this slack at either edge


def gap_covered_by(run, gap_frame_index, tolerance_ms=GAP_TOLERANCE_MS):
    """What explains the null interval at frames[gap_frame_index] (the first active frame
    after an inactive stretch): 'stretch' when a recorded inactive stretch (TASK-300:
    {first_t, last_t, frames, state}, one per maximal inactive run, never capped) starts or
    ends inside the gap, 'sample' when an excluded_samples entry (older exports: at most 500
    per run) falls inside it, 'interruption' for a visibilitychange / blur stamp inside it;
    None when nothing recorded covers the gap (dropped frames)."""
    frames = run['frames']
    t1 = frames[gap_frame_index][0]
    t0 = frames[gap_frame_index - 1][0]
    lo, hi = t0 - tolerance_ms, t1 + tolerance_ms
    inside = lambda t: isinstance(t, (int, float)) and not isinstance(t, bool) and lo <= t <= hi
    for st in run.get('inactive_stretches') or []:
        if isinstance(st, dict) and (inside(st.get('first_t')) or inside(st.get('last_t'))):
            return 'stretch'
    for smp in run.get('excluded_samples') or []:
        if isinstance(smp, dict) and inside(smp.get('t')):
            return 'sample'
    for it in run.get('interruptions') or []:
        if isinstance(it, dict) and inside(it.get('t') if isinstance(it.get('t'), (int, float)) else it.get('t_ms')):
            return 'interruption'
    return None


def gap_explained(run, gap_frame_index, tolerance_ms=GAP_TOLERANCE_MS):
    """True when the page recorded an inactive stretch, an inactive-state sample or an
    interruption between the previous active frame and this one (see gap_covered_by)."""
    return gap_covered_by(run, gap_frame_index, tolerance_ms) is not None


def unexplained_gaps(run, start_frame):
    """Indices of null intervals at or after start_frame (exclusive of the region's own first frame)
    that no recorded inactive state covers."""
    return [i for i in range(start_frame + 1, len(run['frames'])) if run['frames'][i][1] is None and not gap_explained(run, i)]


def measured_region(frames, warmup_ms):
    acc = 0.0
    for i, f in enumerate(frames):
        if f[1] is not None:
            acc += f[1]
        if acc >= warmup_ms:
            return i, [[frames[i][0], None]] + [list(x) for x in frames[i + 1:]]
    return None, None


def verdict_inputs(run, settings):
    """Recompute every verdict input from the raw frames (independent of the page)."""
    warmup, run_ms = settings['warmup_ms'], settings['run_ms']
    start, region = measured_region(run['frames'], warmup)
    if region is None:
        raise Rejected('warmup never completed')
    m = metrics(region)
    windows = rolling_windows(region)
    return {'measured_start_frame': start, 'measured': m, 'rolling_10s_windows': len(windows),
            'rolling_10s_min_fps': min(w['fps'] for w in windows) if windows else None,
            'rolling_10s_windows_detail': [{k: w[k] for k in ('start', 'intervals', 'active_ms', 'fps')} for w in windows],
            'backing_constant': len(run['backing']['changes']) == 0,
            'backing_sizes': [run['backing']['initial']] + [c['backing'] for c in run['backing']['changes']],
            'inactive_frames_excluded': run['excluded'], 'deaths': len(run['deaths']),
            'dispatched_inputs': len(run['dispatched']),
            'measured_active_ms_reached': m['active_ms'] >= run_ms, 'warmup_ms': warmup, 'run_ms': run_ms}


# ------------------------------------------------------- schema validator --

def load_schema():
    return json.loads((HERE / 'result-schema.json').read_text())


def validate_schema(value, schema, path='$', errors=None, root=None):
    """Minimal JSON-schema subset: type, properties, required, additionalProperties,
    items, enum, const, minimum, minLength, minItems, if/then/else, local $ref. Returns the error list."""
    errors = [] if errors is None else errors
    root = schema if root is None else root
    if '$ref' in schema:
        target = root
        for part in schema['$ref'].lstrip('#/').split('/'):
            target = target[part]
        return validate_schema(value, target, path, errors, root)
    if 'if' in schema:
        branch = schema.get('then') if not validate_schema(value, schema['if'], path, [], root) else schema.get('else')
        if branch is not None:
            validate_schema(value, branch, path, errors, root)
    types = {'object': dict, 'array': list, 'string': str, 'number': (int, float), 'integer': int,
             'boolean': bool, 'null': type(None)}
    if 'type' in schema:
        allowed = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        ok = False
        for t in allowed:
            if t == 'number' and isinstance(value, bool):
                continue
            if t == 'integer' and (isinstance(value, bool) or (isinstance(value, float) and not value.is_integer())):
                continue
            if isinstance(value, types[t]):
                ok = True
        if not ok:
            errors.append(f'{path}: expected {schema["type"]}, got {type(value).__name__}')
            return errors
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: {value!r} not in {schema["enum"]}')
    if 'const' in schema and value != schema['const']:
        errors.append(f'{path}: expected {schema["const"]!r}')
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 'minimum' in schema and value < schema['minimum']:
        errors.append(f'{path}: {value} < minimum {schema["minimum"]}')
    if isinstance(value, str) and 'minLength' in schema and len(value) < schema['minLength']:
        errors.append(f'{path}: string shorter than {schema["minLength"]}')
    if isinstance(value, list):
        if 'minItems' in schema and len(value) < schema['minItems']:
            errors.append(f'{path}: fewer than {schema["minItems"]} items')
        if 'items' in schema:
            for i, item in enumerate(value):
                validate_schema(item, schema['items'], f'{path}[{i}]', errors, root)
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{path}.{key}: missing required field')
        props = schema.get('properties', {})
        for key, sub in props.items():
            if key in value:
                validate_schema(value[key], sub, f'{path}.{key}', errors, root)
        if schema.get('additionalProperties') is False:
            for key in value:
                if key not in props:
                    errors.append(f'{path}.{key}: unexpected field')
    return errors


# ----------------------------------------------------------------- build --

def git(root, *argv):
    return subprocess.check_output(['git', *argv], cwd=root, text=True).strip()


def runtime_file_list(repo):
    spec = importlib.util.spec_from_file_location('build_y8_zip', repo / 'tools/build-y8-zip.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.RUNTIME_FILES)


def tree_identity(game_dir):
    """Hashes of every served file (bench.js included; build.json excluded)."""
    files = sorted(str(p.relative_to(game_dir).as_posix()) for p in Path(game_dir).rglob('*')
                   if p.is_file() and p.name not in ('build.json', 'PATCH.diff'))
    hashes = {name: sha_file(Path(game_dir) / name) for name in files}
    return hashes, sha_bytes('\n'.join(f'{k} {v}' for k, v in hashes.items()).encode())


def patch_index(committed):
    """Replace the public SDK tag (exactly once) with the local bench script tag."""
    matches = SDK_TAG_RE.findall(committed)
    if len(matches) != 1:
        raise Rejected(f'expected exactly one cdn.y8.com SDK script tag in index.html, found {len(matches)}')
    return SDK_TAG_RE.sub(lambda m: m.group(1) + BENCH_TAG, committed)


def build(args):
    repo = Path(args.repo).resolve()
    out = Path(args.output).resolve()
    head = git(repo, 'rev-parse', 'HEAD')
    dirty = git(repo, 'status', '--porcelain', '--untracked-files=no')
    files = runtime_file_list(repo)
    tar = subprocess.check_output(['git', 'archive', '--format=tar', head], cwd=repo)
    archived = {}
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        for name in files:
            archived[name] = t.extractfile(name).read()
    dirty_runtime = [n for n in files if (repo / n).read_bytes() != archived[n]]
    if dirty_runtime and not args.allow_dirty:
        raise Rejected('worktree runtime differs from HEAD: ' + ', '.join(dirty_runtime))
    game = out / 'game'
    if game.exists():
        shutil.rmtree(game)
    for name in files:
        dest = game / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((repo / name).read_bytes() if args.allow_dirty else archived[name])
    committed_index = (game / 'index.html').read_text()
    served_index = patch_index(committed_index)
    (game / 'index.html').write_text(served_index)
    shutil.copy2(HERE / 'bench.js', game / 'bench.js')
    diff = ''.join(difflib.unified_diff(committed_index.splitlines(True), served_index.splitlines(True),
                                        'committed/index.html', 'served/index.html'))
    (game / 'PATCH.diff').write_text(diff)
    hashes, tree_sha = tree_identity(game)
    build_version = re.search(r"buildVersion:\s*'([^']*)'", (game / 'platform.js').read_text())
    identity = {'package': 'grapnelninja-bench-runner', 'schema': SCHEMA_ID, 'built_utc': utc(),
                'source_revision': head, 'source_dirty_runtime': dirty_runtime, 'git_status_porcelain': dirty,
                'runtime_files': files, 'served_files_sha256': hashes, 'served_tree_sha256': tree_sha,
                'committed_index_html_sha256': sha_bytes(committed_index.encode()),
                'served_index_html_sha256': sha_bytes(served_index.encode()),
                'index_html_patch': 'the single cdn.y8.com SDK <script> line replaced by ' + BENCH_TAG + ' (see PATCH.diff)',
                'bench_js_sha256': sha_file(HERE / 'bench.js'), 'benchtool_sha256': sha_file(HERE / 'benchtool.py'),
                'build_version': build_version.group(1) if build_version else None,
                'network': 'no external URL is referenced by any served file; results POST only to the serving machine'}
    (game / 'build.json').write_text(json.dumps(identity, indent=1, sort_keys=True) + '\n')
    for name in PACKAGE_FILES:
        shutil.copy2(HERE / name, out / name)
    (out / 'results').mkdir(exist_ok=True)
    print(json.dumps({'output': str(out), 'source_revision': head, 'served_tree_sha256': tree_sha,
                      'files': len(hashes), 'dirty_runtime': dirty_runtime}, indent=1))
    return 0


# ----------------------------------------------------------------- serve --

class Handler(SimpleHTTPRequestHandler):
    """Static files below the package root; POST /save stores a result locally.
    No directory listings, no caching, no client address in the log."""
    server_version = 'GrapnelBench/1'
    log_lock = threading.Lock()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(403, 'directory listing disabled')
        return None

    def log_message(self, fmt, *args):
        line = f'{utc()} {fmt % args}\n'
        with self.log_lock:
            with open(Path(self.directory) / 'server.log', 'a') as f:
                f.write(line)
        if getattr(self.server, 'echo', False):
            sys.stderr.write(line)

    def do_POST(self):
        if self.path.split('?')[0] != '/save':
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > MAX_POST:
            self.reply(413, {'error': f'body length {length} not accepted'})
            return
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            if not isinstance(data, dict) or data.get('schema') != SCHEMA_ID:
                raise ValueError('not a ' + SCHEMA_ID + ' document')
        except ValueError as e:
            self.reply(400, {'error': str(e)})
            return
        results = Path(self.directory) / 'results'
        results.mkdir(exist_ok=True)
        model = re.sub(r'[^a-z0-9]+', '-', str(data.get('device', {}).get('model_supplied', 'device')).lower()).strip('-')[:40] or 'device'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        n = 0
        while True:
            name = f'{stamp}-{model}-runs{len(data.get("runs", []))}' + (f'-{n}' if n else '') + '.json'
            path = results / name
            if not path.exists():
                break
            n += 1
        path.write_bytes(body)
        self.log_message('SAVE %s %d bytes', name, len(body))
        self.reply(200, {'saved': 'results/' + name, 'bytes': len(body), 'sha256': sha_bytes(body)})

    def reply(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def make_server(root, bind='127.0.0.1', port=0, echo=False):
    root = str(Path(root).resolve())
    server = ThreadingHTTPServer((bind, port), lambda *a, **k: Handler(*a, directory=root, **k))
    server.daemon_threads = True
    server.echo = echo
    return server


def lan_addresses():
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except socket.gaierror:
        pass
    try:  # UDP connect() picks the default-route interface without sending anything
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        found.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith('127.'))


def serve(args):
    root = Path(args.root).resolve()
    if not (root / 'game' / 'index.html').exists():
        raise SystemExit(f'{root} is not a built package (no game/index.html)')
    bind = '0.0.0.0' if args.lan else args.bind
    server = make_server(root, bind, args.port, echo=True)
    host, port = server.server_address
    print(f'serving {root} on http://{host}:{port}/  (Ctrl-C stops)')
    if args.lan:
        print('phones on the same Wi-Fi open one of: ' + ', '.join(f'http://{a}:{port}/' for a in lan_addresses()))
    print('results POSTed by the page are written to results/; log in server.log')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


# -------------------------------------------------------------- validate --

def validate_result(data, package_root=None, allow_custom=False):
    """Returns a report dict; status ACCEPTED only when every check passes."""
    report = {'status': 'REJECTED', 'reasons': [], 'warnings': [], 'runs': [], 'acceptance_eligible': False}
    reasons, warnings = report['reasons'], report['warnings']
    schema_errors = validate_schema(data, load_schema())
    if schema_errors:
        reasons.extend('schema: ' + e for e in schema_errors)
        return report
    if not data['device']['model_supplied'].strip() or data['device']['model_supplied'].strip().lower() == 'unknown':
        reasons.append('device.model_supplied must name the actual device')
    disp = data['display']
    if disp['refresh_rate_marker'] == 'manual' and not (isinstance(disp['refresh_rate_hz_supplied'], (int, float)) and disp['refresh_rate_hz_supplied'] > 0):
        reasons.append('display.refresh_rate_marker manual requires a positive refresh_rate_hz_supplied')
    if disp['refresh_rate_marker'] == 'unknown' and disp['refresh_rate_hz_supplied'] is not None:
        reasons.append('display.refresh_rate_marker unknown must not carry a value')
    build = data['build']
    if package_root is not None:
        game = Path(package_root) / 'game'
        if not (game / 'build.json').exists():
            reasons.append(f'package {package_root} has no game/build.json')
        else:
            expected = json.loads((game / 'build.json').read_text())
            _, on_disk = tree_identity(game)
            if on_disk != expected['served_tree_sha256']:
                reasons.append('package game/ files no longer match their build.json (package tampered or rebuilt)')
            if build.get('served_tree_sha256') != expected['served_tree_sha256']:
                reasons.append(f'build mismatch: result served_tree_sha256 {str(build.get("served_tree_sha256"))[:12]} != package {expected["served_tree_sha256"][:12]}')
            if build.get('source_revision') != expected['source_revision']:
                reasons.append(f'build mismatch: result source_revision {build.get("source_revision")} != package {expected["source_revision"]}')
            report['package'] = {'source_revision': expected['source_revision'], 'served_tree_sha256': expected['served_tree_sha256']}
    if data['platform_at_session_start'] != 'disabled':
        reasons.append(f'SDK isolation: PLATFORM.environment was {data["platform_at_session_start"]!r}, expected disabled')
    s = data['settings']
    standard = all(s.get(k) == v for k, v in STANDARD.items())
    if s.get('protocol') != ('standard' if standard else 'custom'):
        reasons.append('settings.protocol label does not match warmup/run/repetitions')
    if not standard:
        (warnings if allow_custom else reasons).append(f'non-standard protocol: {s["warmup_ms"]} + {s["run_ms"]} ms x {s["repetitions_target"]} (standard {STANDARD})')
    if s['emulation'] != 'none':
        warnings.append('emulation=' + s['emulation'] + ': not a native-device result')
    if s['replay_kind'] == 'auto' and s['seed'] == 'none':
        warnings.append('auto replay without a seed')
    seed = seed_value(s['seed'])  # == bench.js Number(seed) >>> 0 (4.5 -> 4, 0x10 -> 16, garbage -> 0); never raises
    expected_installed = seed_installed_label(s['seed'])
    report['seed'] = {'setting': s['seed'], 'value': seed, 'installed_label': expected_installed}
    if s['seed_installed_at_load'] != expected_installed:
        reasons.append(f'settings.seed_installed_at_load {s["seed_installed_at_load"]!r} is not {expected_installed!r} '
                       f'(Number({s["seed"]!r}) >>> 0 = {seed})')
    complete = {'bad': 0, 'classic': 0}
    preserved = 0
    for run in data['runs']:
        r = {'index': run['index'], 'mode': run['mode'], 'result': run['result'], 'checks': []}
        report['runs'].append(r)
        try:
            if run['result'] != 'COMPLETE':
                # Aborted / short attempts are evidence of the session, never of performance: only the
                # seal is binding. Arithmetic and verdict inputs are recomputed when the frames allow it
                # (informational); an attempt stopped before the warmup or with < 2 frames is still fine.
                if sha_canonical(run['frames']) != run['frames_sha256']:
                    raise Rejected('frames_sha256 does not seal the frames')
                r['checks'].append('frames seal OK')
                try:
                    check_frames(run['frames'])
                    r['verdict_inputs'] = verdict_inputs(run, s)
                    r['checks'].append('frame arithmetic and verdict inputs recomputed (informational, not counted)')
                except Rejected as e:
                    r['checks'].append(f'verdict inputs not recomputable ({e}); informational only')
                r['checks'].append('preserved as a non-complete attempt (not counted)')
                preserved += 1
                continue
            check_frames(run['frames'])
            r['checks'].append('frame arithmetic OK')
            if sha_canonical(run['frames']) != run['frames_sha256']:
                raise Rejected('frames_sha256 does not seal the frames')
            r['checks'].append('frames seal OK')
            if run['seed_installed'] != expected_installed:
                raise Rejected(f'seed_installed {run["seed_installed"]!r} is not {expected_installed!r} derived from settings.seed {s["seed"]!r}')
            r['checks'].append('seed OK')
            if run['replay_kind'] == 'auto':
                expected_sha = sha_canonical(replay_fractions(0 if seed is None else seed, s['warmup_ms'] + s['run_ms'] + 1000))
                if run['replay_fractions_sha256'] != expected_sha:
                    raise Rejected('replay_fractions_sha256 differs from the deterministic replay for this seed')
                r['checks'].append('replay seal OK')
            if run['dimensions_at_start']['version'] != run['mode']:
                raise Rejected(f'mode {run["mode"]} not started (version {run["dimensions_at_start"]["version"]})')
            if run['dimensions_at_start']['platform'] != 'disabled':
                raise Rejected('SDK isolation failed during the run')
            if run['dimensions_at_start']['density_limit'] not in (None, 'Infinity') and run['dimensions_at_start']['density_limit'] != float('inf'):
                warnings.append(f'run {run["index"]}: adaptive density already reduced at start (limit {run["dimensions_at_start"]["density_limit"]})')
            vi = verdict_inputs(run, s)
            r['verdict_inputs'] = vi
            page = run.get('verdict_inputs') or {}
            pm = page.get('measured') or {}
            for key in ('intervals', 'gaps', 'active_ms', 'average_fps'):
                if key in pm and abs(pm[key] - vi['measured'][key]) > 1e-6 * max(1.0, abs(vi['measured'][key])):
                    raise Rejected(f'page-side {key} {pm[key]} differs from recomputed {vi["measured"][key]}')
            if page.get('rolling_10s_min_fps') is not None and vi['rolling_10s_min_fps'] is not None \
                    and abs(page['rolling_10s_min_fps'] - vi['rolling_10s_min_fps']) > 1e-6:
                raise Rejected('page-side rolling minimum differs from recomputed')
            r['checks'].append('page-side inputs match recomputation')
            if not vi['measured_active_ms_reached']:
                raise Rejected(f'measured active time {vi["measured"]["active_ms"]:.0f} ms < {s["run_ms"]} ms')
            if vi['measured']['gaps']:
                bad = unexplained_gaps(run, vi['measured_start_frame'])
                warnings.append(f'run {run["index"]}: {vi["measured"]["gaps"]} pause/hidden gap(s) excluded from the measured region'
                                + (f', {len(bad)} without a recorded inactive state at frames {bad[:5]} (the evaluator rejects the repetition)' if bad else
                                   ' (every gap covered by a recorded inactive stretch / sample / interruption)'))
            if not vi['backing_constant']:
                warnings.append(f'run {run["index"]}: backing size changed during the run (adaptive density) {vi["backing_sizes"]}')
            complete[run['mode']] += 1
            r['checks'].append('COMPLETE run accepted')
        except Rejected as e:
            r['rejected'] = str(e)
            reasons.append(f'run {run["index"]}: {e}')
    report['complete_runs'] = complete
    report['non_complete_attempts_preserved'] = preserved
    if not reasons:
        report['status'] = 'ACCEPTED'
        report['acceptance_eligible'] = standard and s['emulation'] == 'none'
        if not report['acceptance_eligible']:
            warnings.append('evidence accepted for integrity but NOT eligible as a native acceptance row (custom protocol or emulation)')
    return report


def validate(args):
    data = json.loads(Path(args.result).read_text())
    report = validate_result(data, args.package, args.allow_custom)
    report['result_file'] = str(Path(args.result).resolve())
    report['result_sha256'] = sha_file(args.result)
    text = json.dumps(report, indent=1, sort_keys=True)
    if args.report:
        Path(args.report).write_text(text + '\n')
    print(text)
    return 0 if report['status'] == 'ACCEPTED' else 1


def summarize(args):
    rows = []
    for path in sorted(Path(args.results).glob('*.json')):
        try:
            data = json.loads(path.read_text())
            rep = validate_result(data, args.package, True)
        except (ValueError, KeyError, TypeError) as e:
            rows.append(f'{path.name}: unreadable ({e})')
            continue
        for r in rep['runs']:
            vi = r.get('verdict_inputs')
            m = vi['measured'] if vi else None
            rows.append(f'{path.name} run {r["index"]} {r["mode"]:8s} {r["result"]:9s} ' + (
                f'avg {m["average_fps"]:7.2f} fps  min10s {vi["rolling_10s_min_fps"] if vi["rolling_10s_min_fps"] is None else round(vi["rolling_10s_min_fps"], 2)}  '
                f'p95 {m["frame_ms"]["p95"]:6.2f} ms  gaps {m["gaps"]}  backing {"const" if vi["backing_constant"] else "CHANGED"}' if m else r.get('rejected') or (r['checks'][-1] if r['checks'] else '')))
        rows.append(f'{path.name}: {rep["status"]} ' + '; '.join(rep['reasons'] + rep['warnings']))
    print('\n'.join(rows) if rows else 'no results')
    return 0


# ---------------------------------------------------------------- inspect --

NETWORK_RE = re.compile(r'https?://|wss?://|fetch\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|<script[^>]*src\s*=')
MUTATION_RE = re.compile(r'RENDER_BUDGET\s*\.\s*\w+\s*=|densityLimit\s*=|window\.draw\s*=|window\.physics\s*=|\bdraw\s*=\s*function|\bphysics\s*=\s*function|configureCanvasViewport\s*=|devicePixelRatio\s*=')


def inspect(args):
    root = Path(args.root).resolve()
    game = root / 'game'
    build_info = json.loads((game / 'build.json').read_text())
    repo = Path(args.repo).resolve() if args.repo else None
    lines, fail = [], False
    lines.append(f'package {root}')
    lines.append(f'source_revision {build_info["source_revision"]} served_tree_sha256 {build_info["served_tree_sha256"]}')
    hashes, tree_sha = tree_identity(game)
    lines.append(('OK' if tree_sha == build_info['served_tree_sha256'] else 'FAIL') + ' served tree hash matches build.json')
    fail |= tree_sha != build_info['served_tree_sha256']
    lines.append('== network references in served files (any http(s)/ws URL, fetch, XHR, beacon, socket, script src)')
    external = 0
    for name in sorted(hashes):
        text = (game / name).read_text(errors='replace')
        for i, line in enumerate(text.splitlines(), 1):
            if NETWORK_RE.search(line):
                stripped = line.strip()
                is_comment = stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*') or stripped.startswith('#') or stripped.startswith('<!--')
                if re.search(r'(https?|wss?)://', line) and not is_comment:
                    kind = 'EXTERNAL-URL'
                    external += 1
                elif is_comment:
                    kind = 'comment'
                elif re.search(r'<script[^>]*src\s*=\s*"(?!https?://)[^"]*"', line) or re.search(r"<script[^>]*src\s*=\s*'(?!https?://)[^']*'", line):
                    kind = 'local-script'
                elif 'fetch(' in line and ("'build.json'" in line or "'../save'" in line):
                    kind = 'same-origin-fetch'
                else:
                    kind = 'review'
                lines.append(f'  {kind:17s} {name}:{i}: {stripped[:140]}')
    lines.append(('OK' if external == 0 else 'FAIL') + f' external URLs in served non-comment code: {external}')
    fail |= external != 0
    lines.append('== committed SDK tag absent from served index.html')
    served_index = (game / 'index.html').read_text()
    sdk_present = 'cdn.y8.com' in served_index
    lines.append(('FAIL' if sdk_present else 'OK') + ' cdn.y8.com not referenced by served index.html')
    fail |= sdk_present
    if repo is not None:
        lines.append('== served runtime vs committed runtime (expected: only the SDK line in index.html)')
        differing = []
        for name in build_info['runtime_files']:
            committed = subprocess.check_output(['git', 'show', f'{build_info["source_revision"]}:{name}'], cwd=repo)
            if committed != (game / name).read_bytes():
                differing.append(name)
                if name == 'index.html':
                    delta = [l for l in difflib.unified_diff(committed.decode().splitlines(), served_index.splitlines(), lineterm='', n=0)
                             if (l.startswith('+') or l.startswith('-')) and not l.startswith('+++') and not l.startswith('---')]
                    for l in delta:
                        lines.append('  ' + l)
                    only_sdk = len(delta) == 2 and 'cdn.y8.com' in delta[0] and delta[1].lstrip('+').strip() == BENCH_TAG
                    lines.append(('OK' if only_sdk else 'FAIL') + ' index.html differs by exactly the SDK line -> bench.js line')
                    fail |= not only_sdk
        lines.append(('OK' if differing == ['index.html'] else 'FAIL') + f' files differing from the commit: {differing}')
        fail |= differing != ['index.html']
    lines.append('== measurement invariance: bench.js must not assign draw/physics/density/viewport functions')
    bench = (game / 'bench.js').read_text()
    hits = [f'  {i}: {l.strip()[:120]}' for i, l in enumerate(bench.splitlines(), 1) if MUTATION_RE.search(l)]
    lines.extend(hits)
    lines.append(('OK' if not hits else 'FAIL') + f' mutation patterns in bench.js: {len(hits)}')
    fail |= bool(hits)
    wrapped = re.findall(r'window\.(gameLoop|reStart)\s*=', bench)
    lines.append('  wrappers (installed at run start, restored at run end):')
    lines.extend(f'  {i}: {l.strip()[:120]}' for i, l in enumerate(bench.splitlines(), 1) if re.search(r'window\.(gameLoop|reStart)\s*=', l))
    lines.append(('OK' if sorted(wrapped) == ['gameLoop', 'gameLoop', 'reStart', 'reStart'] else 'FAIL') +
                 f' exactly two wrapper installs and two restores (gameLoop, reStart): {wrapped}')
    fail |= sorted(wrapped) != ['gameLoop', 'gameLoop', 'reStart', 'reStart']
    for pattern, label in ((r'Math\.random\s*=', 'seeded Math.random (protocol, recorded in settings.seed)'),):
        n = len(re.findall(pattern, bench))
        lines.append(f'  note: {label}: {n} assignment(s)')
    lines.append('RESULT ' + ('FAIL' if fail else 'PASS'))
    text = '\n'.join(lines)
    print(text)
    if args.report:
        Path(args.report).write_text(text + '\n')
    return 1 if fail else 0


def replay(args):
    seed = seed_value(args.seed)
    seed = 0 if seed is None else seed
    events = replay_fractions(seed, args.total_ms)
    print(json.dumps({'seed': seed, 'seed_setting': args.seed, 'total_ms': args.total_ms, 'events': len(events),
                      'sha256': sha_canonical(events), 'first': events[:4]}, indent=1))
    return 0


# ------------------------------------------------------------------- CLI --

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='action', required=True)
    b = sub.add_parser('build')
    b.add_argument('--repo', default=str(HERE.parents[1]))
    b.add_argument('--output', required=True)
    b.add_argument('--allow-dirty', action='store_true', help='serve worktree bytes instead of HEAD (recorded)')
    b.set_defaults(fn=build)
    s = sub.add_parser('serve')
    s.add_argument('--root', default=str(HERE))
    s.add_argument('--bind', default='127.0.0.1')
    s.add_argument('--lan', action='store_true', help='bind 0.0.0.0 for phones on the same local network')
    s.add_argument('--port', type=int, default=8765)
    s.set_defaults(fn=serve)
    v = sub.add_parser('validate')
    v.add_argument('result')
    v.add_argument('--package', default=str(HERE), help='package root whose game/build.json the result must match')
    v.add_argument('--allow-custom', action='store_true', help='accept non-standard durations (smoke tests)')
    v.add_argument('--report')
    v.set_defaults(fn=validate)
    m = sub.add_parser('summarize')
    m.add_argument('--results', default=str(HERE / 'results'))
    m.add_argument('--package', default=str(HERE))
    m.set_defaults(fn=summarize)
    i = sub.add_parser('inspect')
    i.add_argument('--root', default=str(HERE))
    i.add_argument('--repo')
    i.add_argument('--report')
    i.set_defaults(fn=inspect)
    r = sub.add_parser('replay')
    r.add_argument('--seed', default='4', help="as typed in ?seed= (converted like the page: Number(seed) >>> 0)")
    r.add_argument('--total-ms', type=int, default=STANDARD['warmup_ms'] + STANDARD['run_ms'] + 1000)
    r.set_defaults(fn=replay)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except Rejected as e:
        print('REJECTED: ' + str(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
