"""Sealed single-runtime desktop FPS gate; native Android remains UNVERIFIED.

Six sequential runs per engine, Chill=classic and Main=bad. --smoke exercises
collector plumbing only and is always INVALID for release. ZIP builds require
source.json beside the archive, as produced by build_playgama.py.
"""
import argparse
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
import importlib.metadata
import json
import math
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
from threading import Thread
import time
import zipfile

import build_playgama as build
from playgama_fps_gate import active_metrics
from playgama_render_compare import (ROOT, SDK, FIXTURE, SEED, INPUT, TIMING_PROBE,
    STATE, LAYOUT, SEED_SCRIPT, QuietHandler, sync_playwright, launch_browser,
    audit_browsers, validate_capture_layout, hashes, summarize, sha, read, write)
from playgama_firefox_perf import utc, git


def protocol(engine, identity):
    assert engine in ('firefox', 'chrome'), 'engine'
    return dict(schema='release-fps-v1', engine=engine, release=identity,
        order=[[m, n] for m in ('classic', 'bad') for n in (1, 2, 3)],
        execution='sequential modes and runs; one runtime; no control arm',
        mode_labels={'classic': 'Chill', 'bad': 'Main'}, viewport=[844, 390],
        dpr=2, backing=[1688, 780], logical=[2337, 1080], seed=SEED,
        input=INPUT, warmup_ms=5000, measured_ms=30000, cpu_throttling=False,
        interval_policy='inactive gaps excluded; slow active/death-ending retained; whole warmup boundary',
        statistics='interval count / summed interval seconds; nearest-rank p95',
        acceptance='each run strictly >30 FPS', fixture_sha256=sha(FIXTURE.encode()),
        native_android='UNVERIFIED')


def release_identity(runtime, archive=None, revision=None):
    runtime = runtime.resolve(strict=True)
    if archive is None:
        revision = git('rev-parse', (revision or 'HEAD')+'^{commit}').decode().strip()
        members = hashes(runtime)
        assert members and all(sha(git('show', revision+':'+p)) == h for p, h in members.items()), 'uncommitted runtime'
        source = members
        version = re.search(r"buildVersion:\s*'([^']+)'", (runtime/'platform.js').read_text()).group(1)
        packed = None
    else:
        archive = archive.resolve(strict=True)
        receipt = read(archive.parent/'source.json')
        revision, files = build.runtime(receipt['revision'], receipt.get('base_revision'))
        version = re.search(r"buildVersion:\s*'([^']+)'", files['platform.js'].decode()).group(1)
        assert receipt['source'] == 'git blobs only' and receipt['build_version'] == version, 'build identity'
        payload = archive.read_bytes()
        expected = build.bundle(files)
        assert payload == build.archive(expected), 'archive differs from recorded committed build'
        with zipfile.ZipFile(archive) as z:
            members = {}
            for info in z.infolist():
                p = PurePosixPath(info.filename)
                assert not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename, 'unsafe ZIP path'
                assert str(p) == info.filename and not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16), 'unsafe ZIP member'
                assert info.filename not in members, 'duplicate ZIP member'
                members[info.filename] = sha(z.read(info))
        disk = {}
        for p in runtime.rglob('*'):
            assert not p.is_symlink(), 'runtime symlink'
            if p.is_file(): disk[p.relative_to(runtime).as_posix()] = sha(p.read_bytes())
        assert disk == members, 'runtime is not exact ZIP extraction'
        source = {p: sha(b) for p, b in files.items()}
        packed = dict(bytes=len(payload), sha256=sha(payload), source_receipt_sha256=sha((archive.parent/'source.json').read_bytes()))
    return dict(revision=revision, build_version=version, source_sha256=source,
                members=members, zip=packed)


def tool_identity():
    return {name: sha((ROOT/'tools'/name).read_bytes()) for name in (
        'playgama_release_fps.py', 'playgama_render_compare.py', 'playgama_fps_gate.py',
        'playgama_firefox_perf.py', 'build_playgama.py')}


def seal(out, metadata):
    write(out/'manifest.json', dict(metadata, evidence_sha256={
        p.name: sha(p.read_bytes()) for p in sorted(out.iterdir())
        if p.is_file() and p.name not in ('manifest.json', 'seal.json')}))
    write(out/'seal.json', {'manifest_sha256': sha((out/'manifest.json').read_bytes())})


ACTIVITY_FLAGS = frozenset(('menu', 'pause', 'death', 'ad', 'host', 'portrait', 'hidden'))


def validate_activity_states(raw):
    """Require complete probe snapshots before release FPS arithmetic."""
    for index, frame in enumerate(raw['frames']):
        for side in ('before', 'after'):
            state = frame.get(side)
            if (not isinstance(state, dict) or set(state) != ACTIVITY_FLAGS
                    or any(type(value) is not bool for value in state.values())):
                raise ValueError(f'invalid activity state: frame={index} {side}; '
                                 'expected exactly seven boolean probe flags')


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_input_timing(raw):
    """Replay PROBE accumulation and require each input on its first eligible frame."""
    frames, inputs = raw['frames'], raw['inputs']
    active, at, previous = 0, {}, None
    eligible = []
    for index, frame in enumerate(frames):
        t = frame.get('t')
        if not number(t) or (previous is not None and t <= previous['t']):
            raise ValueError(f'invalid frame timestamp: frame={index}')
        live = not any(frame['before'].values())
        # PROBE: accumulate only across active after -> active before boundaries.
        if previous is not None and live and not any(previous['after'].values()):
            active += t - previous['t']
        if live: eligible.append((index, active))
        at[t] = (index, active, live)
        previous = frame
    cursor = 0
    for position, event in enumerate(inputs):
        actual, t = event.get('actual_active_ms'), event.get('t')
        if not number(actual) or not number(t) or actual < 0 or t < 0:
            raise ValueError(f'invalid input timing: input={position}; '
                             'expected finite non-negative actual_active_ms and t')
        if t not in at:
            raise ValueError(f'input timing outside trace: input={position} t={t}')
        index, accumulated, live = at[t]
        if not live or actual != accumulated:
            raise ValueError(f'input timing not bound to active frame: input={position} frame={index}')
        while cursor < len(eligible) and eligible[cursor][1] < event['at_active_ms']: cursor += 1
        if cursor == len(eligible) or eligible[cursor][0] != index:
            raise ValueError(f'input not dispatched on first eligible active frame: input={position} frame={index}')


def evaluate(capture, runtime, archive=None):
    receipt = read(capture/'manifest.json')
    assert read(capture/'seal.json') == {'manifest_sha256': sha((capture/'manifest.json').read_bytes())}, 'seal mismatch'
    inventory = {p.name for p in capture.iterdir()}
    assert inventory == set(receipt['evidence_sha256']) | {'manifest.json', 'seal.json'}, 'seal inventory'
    for name, digest in receipt['evidence_sha256'].items():
        assert Path(name).name == name and not (capture/name).is_symlink(), 'unsafe evidence path'
        assert sha((capture/name).read_bytes()) == digest, 'tampering: '+name
    assert receipt['exit_code'] == 0, 'capture failed'
    assert git('rev-parse', receipt['source_revision']+'^{commit}').decode().strip() == receipt['source_revision'], 'source revision'
    assert set(receipt['tool_sha256']) == set(tool_identity()), 'tool inventory'
    assert all(re.fullmatch('[0-9a-f]{64}', h) for h in receipt['tool_sha256'].values()), 'tool identities'
    assert receipt['command'] and receipt['cwd'] and receipt['started_utc'] and receipt['ended_utc'], 'command receipt'
    assert 0 <= receipt['duration_seconds'] <= 720, 'invocation duration'
    p = read(capture/'protocol.json')
    identity = release_identity(runtime, archive, p['release']['revision'])
    assert p == protocol(p['engine'], identity), 'protocol/release identity mismatch'
    data = read(capture/'results.json')
    assert not data['smoke'], 'shortened smoke INVALID for release'
    assert data['fixture_sha256'] == sha(FIXTURE.encode()) and not data['errors'], 'SDK/errors'
    network = read(capture/'network.json')
    assert any(r['action'] == 'SDK_STUB' and r['url'] == SDK for r in network), 'SDK boundary'
    assert all(r['action'] == ('LOCAL' if r['url'].startswith(data['origin']+'/') else 'SDK_STUB' if r['url'] == SDK else 'BLOCKED') for r in network), 'network isolation'
    assert not any(r['action'] == 'BLOCKED' for r in network), 'unexpected network'
    audit_browsers(data['environment'], {'engines': [p['engine']]}, (capture/'command.log').read_text().splitlines())
    assert [[r['mode'], r['run']] for r in data['runs']] == p['order'], 'missing/duplicate/wrong-mode run'
    assert len({r['raw'] for r in data['runs']}) == 6, 'duplicate raw'
    rows = []
    for r in data['runs']:
        assert r['engine'] == p['engine'], 'run browser'
        assert r['raw'] in receipt['evidence_sha256'], 'unsealed raw'
        raw = read(capture/r['raw'])
        assert raw['mode'] == r['mode'] and raw['run'] == r['run'], 'raw ordering'
        assert raw['done'] and raw['inputs'] and raw['transitions'], 'incomplete trace'
        assert raw['state']['mode'] == r['mode'], 'wrong gameplay mode'
        assert [{k: event[k] for k in ('at_active_ms', 'type', 'x', 'y')} for event in raw['inputs']] == INPUT, 'actual input sequence'
        assert raw['seed'] == SEED and raw['input_policy'] == INPUT, 'input protocol'
        assert raw['source_sha256'] == identity['members'], 'raw identity'
        validate_capture_layout(raw['layout'])
        validate_activity_states(raw)
        validate_input_timing(raw)
        metrics = active_metrics(raw)
        assert metrics == r['metrics'], 'declared metrics differ'
        rows.append(dict(engine=p['engine'], mode=r['mode'], run=r['run'], **metrics))
    return dict(gate='PASS' if all(r['gate'] == 'PASS' for r in rows) else 'FAIL',
                release=identity, runs=rows, native_android='UNVERIFIED')


def combine(firefox, chrome, runtime, archive):
    a, b = evaluate(firefox, runtime, archive), evaluate(chrome, runtime, archive)
    assert all(r['engine'] == 'firefox' for r in a['runs']) and all(r['engine'] == 'chrome' for r in b['runs']), 'combine engines'
    assert a['release'] == b['release'], 'release mismatch'
    return dict(gate='PASS' if a['gate'] == b['gate'] == 'PASS' else 'FAIL',
                release=a['release'], runs=a['runs']+b['runs'], native_android='UNVERIFIED')


def worker(args):
    out = args.out
    assert not any((out/name).exists() for name in ('protocol.json', 'results.json', 'manifest.json', 'seal.json')), 'preserve historical evidence'
    identity = release_identity(args.runtime, args.zip)
    write(out/'protocol.json', protocol(args.engine, identity))
    data = dict(smoke=args.smoke, fixture_sha256=sha(FIXTURE.encode()), errors=[], runs=[],
                environment={'browsers': {}, 'playwright': importlib.metadata.version('playwright')})
    network = []
    def timeout(*_): raise TimeoutError('arm exceeded 120 seconds')
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGTERM, timeout)
    try:
        with ExitStack() as stack:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(args.runtime.resolve())))
            stack.callback(server.server_close)
            Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            data['origin'] = f'http://127.0.0.1:{server.server_port}'
            def route_request(route):
                url = route.request.url
                action = 'LOCAL' if url.startswith(data['origin']+'/') else 'SDK_STUB' if url == SDK else 'BLOCKED'
                network.append(dict(url=url, action=action))
                if action == 'LOCAL': route.continue_()
                elif action == 'SDK_STUB': route.fulfill(content_type='application/javascript', body=FIXTURE)
                else: route.abort()
            pw = stack.enter_context(sync_playwright())
            browser, provenance = launch_browser(pw, args.engine)
            stack.callback(browser.close)
            data['environment']['browsers'][args.engine] = provenance
            for mode, number in protocol(args.engine, identity)['order']:
                signal.alarm(120)
                context = browser.new_context(viewport={'width': 844, 'height': 390}, device_scale_factor=2,
                    has_touch=True, locale='en-US', service_workers='block')
                try:
                    context.route('**/*', route_request)
                    context.add_init_script(SEED_SCRIPT % SEED)
                    page = context.new_page()
                    page.on('pageerror', lambda e: data['errors'].append(str(e)))
                    page.on('console', lambda m: data['errors'].append(m.text) if m.type == 'error' else None)
                    page.goto(data['origin']+'/index.html')
                    page.wait_for_function('bootComplete && document.getElementById("loading").hidden')
                    layout = page.evaluate(LAYOUT)
                    validate_capture_layout(layout)
                    page.evaluate(TIMING_PROBE, {'mode': mode, 'inputs': INPUT, 'seed': SEED})
                    name = f'{args.engine}-{mode}-{number}-raw.json'
                    while True:
                        page.wait_for_timeout(200)
                        raw = page.evaluate('perfReceipt')
                        raw.update(mode=mode, run=number, layout=layout, seed=SEED, input_policy=INPUT,
                                   source_sha256=identity['members'], state=page.evaluate(STATE))
                        # Preserve the last raw trace even if this arm times out.
                        write(out/name, raw)
                        try:
                            metrics = summarize(raw, 100) if args.smoke else active_metrics(raw)
                            if not args.smoke or metrics['measured_ms'] >= 600: break
                        except (AssertionError, ValueError): pass
                    data['runs'].append(dict(engine=args.engine, mode=mode, run=number, raw=name, metrics=metrics))
                    print(f'RECORDED {args.engine}/{mode} run={number} measured_ms={metrics["measured_ms"]} smoke={args.smoke}', flush=True)
                finally:
                    context.close()
                    signal.alarm(0)
                write(out/'results.json', data)
    finally:
        write(out/'results.json', data)
        write(out/'network.json', network)


def capture(args):
    args.out.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
    metadata = dict(command=command, cwd=str(Path.cwd()), started_utc=utc(),
        source_revision=git('rev-parse', 'HEAD').decode().strip(),
        tool_sha256=tool_identity())
    started = time.monotonic()
    with (args.out/'command.log').open('w') as log:
        try:
            result = subprocess.run(['timeout', '--signal=TERM', '--kill-after=3s', '715s', *command], stdout=log, stderr=subprocess.STDOUT)
            code = result.returncode
        finally:
            metadata.update(ended_utc=utc(), duration_seconds=time.monotonic()-started, exit_code=locals().get('code', 2))
            seal(args.out, metadata)
    if code: return 2
    if args.smoke:
        print('INVALID for release: shortened smoke; collector evidence retained')
        return 2
    result = evaluate(args.out, args.runtime, args.zip)
    print(json.dumps(result, indent=2))
    return 0 if result['gate'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('capture', 'evaluate', 'combine'):
        p = subs.add_parser(name)
        p.add_argument('--runtime', type=Path, required=True)
        p.add_argument('--zip', type=Path, required=name == 'combine')
        if name == 'capture':
            p.add_argument('--engine', choices=('firefox', 'chrome'), required=True)
            p.add_argument('--out', type=Path, required=True)
            p.add_argument('--smoke', action='store_true', help='shortened plumbing only; exit 2 INVALID for release')
            p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
        elif name == 'evaluate': p.add_argument('--capture', type=Path, required=True)
        else:
            p.add_argument('--firefox', type=Path, required=True)
            p.add_argument('--chrome', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'capture':
            if args.worker: worker(args); return 0
            return capture(args)
        result = evaluate(args.capture, args.runtime, args.zip) if args.command == 'evaluate' else combine(args.firefox, args.chrome, args.runtime, args.zip)
        print(json.dumps(result, indent=2))
        return 0 if result['gate'] == 'PASS' else 1
    except (AssertionError, ValueError, KeyError, TypeError, IndexError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f'INVALID evidence: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
