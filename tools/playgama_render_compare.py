"""Current immutable runtime comparison; desktop emulation, never device FPS proof.

capture defaults to the full AB/BA/AB protocol. --smoke is plumbing validation
only. --engine selects firefox, actual Google chrome, or chromium; omitted keeps
the historical Firefox/Chromium matrix. visuals uses a manual clock and explicit fixtures, never performance data.
Every attempt has a fresh output directory; failed command output is retained.
"""
import argparse
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
import json
import importlib.metadata
import math
from pathlib import Path
import platform
import signal
import statistics
import sys
from threading import Thread
import time

import numpy as np
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
from playgama_firefox_perf import (ROOT, SDK, FAKE, SEED, INPUT, PROBE, LAYOUT,
                                  sha, read, write, utc, git, runtime_files,
                                  capture_command, QuietHandler, SEED_SCRIPT)
from render_snapshot import CLOCK_SCRIPT, boot_frozen

# Shared historical helpers are reused without changing their experiment semantics.
TIMING_PROBE = PROBE.replace(
    'activeMs:p.activeMs};',
    'activeMs:p.activeMs, gameplay:{x:ninja.x,y:ninja.y,score:scoreText.count[version],mode:version}};')

FIXTURE = "const FAULT='normal'; const SAVED_LANGUAGE='en';\n" + FAKE
PROTOCOL = {
    'engines': ['firefox', 'chromium'], 'modes': ['classic', 'bad'],
    'mode_labels': {'classic': 'Chill', 'bad': 'Main'},
    'execution': 'sequential engines, modes, pairs and arms; AB, BA, AB',
    'orders': [['control', 'candidate'], ['candidate', 'control'], ['control', 'candidate']],
    'viewport': [844, 390], 'dpr': 2, 'identical_backing': True,
    'seed': SEED, 'input': INPUT, 'input_policy': 'active-time mouse events; restart via normal death button; retain actual input/state traces',
    'warmup_ms': 5000, 'measured_ms': 30000,
    'interval_policy': 'Exclude inactive gaps; retain every slow active interval including death-ending intervals; warmup boundary interval wholly warmup.',
    'statistics': 'raw RAF intervals; arithmetic mean and nearest-rank p95; individual paired reductions/regressions and medians of three paired ratios',
    'acceptance': '>=10% median paired mean-frame reduction in at least one Firefox mode; <=5% median paired mean AND p95 regression in every engine/mode',
    'visual_checkpoints': ['menu', 'classic', 'bad', 'pause', 'death', 'touch-portrait', 'touch-landscape', 'resize', 'screen-edges', 'player-trail-sparks-shake'],
    'visual_policy': 'Save images, per-channel pixel differences, changed-pixel counts and state JSON. Deterministic manual-clock fixtures are separate from natural-timing gameplay. No automatic pixel tolerance excuses visible changes; nonzero differences require recorded visual review. Never lower effect resolution or remove effects.',
    'claims': 'No guaranteed device FPS target. Desktop headless touch emulation; native Android Firefox UNVERIFIED. Synthetic fixtures establish arithmetic only.'}
STATE = '''() => ({mode:version,menu:menu.visible,pause:menu.gamePaused,
 death:continueOffer.visible,score:scoreText.count[version],x:ninja?.x,y:ninja?.y,
 held:grapnel?.throwed,track:ninja?.track.pos, floors:floors?.map(f=>({x:f.x,y:f.y})),
 shake:QUALITY.screenShake && performance.now()<visualEffects.screenEffects.shakeUntil,
 shake_offset:visualEffects.screenEffects.shakeOffset, particles:visualEffects.particles.particles.length,
 portrait:isViewRotated(),backing:[canvas.width,canvas.height]})'''


# Only this exact historical display mapping is compatible. Raw mode IDs and
# sealed files are never rewritten; every other protocol field stays strict.
LEGACY_MODE_LABELS = {'classic': 'Main', 'bad': 'Chill'}


def selected_protocol(engine=None, support=False):
    if support:
        from playgama_support_visuals import CHECKPOINTS
        return dict(selected_protocol(engine), support_visuals=True,
                    visual_checkpoints=PROTOCOL['visual_checkpoints'] + CHECKPOINTS)
    if engine is None:
        return dict(PROTOCOL)
    assert engine in ('firefox', 'chrome', 'chromium'), 'unknown engine'
    return dict(PROTOCOL, protocol_version='selected-engine-v1', engines=[engine],
                acceptance='Selected-engine diagnostics only; no historical matrix acceptance')


def launch_browser(pw, engine):
    """Read the actual Linux process, never infer provenance from a UA."""
    before = {p.name for p in Path('/proc').iterdir() if p.name.isdigit()}
    kind = pw.firefox if engine == 'firefox' else pw.chromium
    options = {'headless': True}
    if engine == 'chrome':
        options['channel'] = 'chrome'  # Errors propagate; never substitute Chromium.
    browser = kind.launch(**options)
    try:
        matches = []
        marker = '-juggler-pipe' if engine == 'firefox' else '--remote-debugging-pipe'
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit() or proc.name in before:
                continue
            try:
                argv = (proc/'cmdline').read_bytes().decode().rstrip('\0').split('\0')
                if marker in argv and not any(a.startswith('--type=') for a in argv):
                    executable = (proc/'exe').resolve(strict=True)
                    matches.append(dict(pid=int(proc.name), executable_path=str(executable),
                        executable_sha256=sha(executable.read_bytes()), launch_arguments=argv))
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
        assert len(matches) == 1, 'cannot resolve launched browser process'
        provenance = dict(matches[0], version=browser.version, engine=engine,
                          channel=options.get('channel'), launch_options=options)
        if engine == 'chrome':
            assert provenance['executable_path'] == '/opt/google/chrome/chrome', 'not official Google Chrome executable'
        print('LAUNCH ' + json.dumps(provenance, sort_keys=True), flush=True)
        return browser, provenance
    except BaseException:
        browser.close()
        raise


def audit_browsers(environment, protocol, lines):
    browsers = environment['browsers']
    assert set(browsers) == set(protocol['engines']), 'browser inventory'
    launches = [json.loads(line[7:]) for line in lines if line.startswith('LAUNCH ')]
    assert launches == [browsers[e] for e in protocol['engines']], 'launch identity/inventory'
    for engine, info in browsers.items():
        assert info['engine'] == engine and info['version'] and info['pid'] > 0, 'browser identity'
        path = Path(info['executable_path'])
        assert path.is_absolute() and path.resolve() == path, 'resolved executable'
        assert sha(path.read_bytes()) == info['executable_sha256'], 'executable hash'
        marker = '-juggler-pipe' if engine == 'firefox' else '--remote-debugging-pipe'
        assert marker in info['launch_arguments'], 'launch arguments'
        assert Path(info['launch_arguments'][0]).resolve() == path, 'launched executable'
        options = dict(headless=True)
        if engine == 'chrome':
            options['channel'] = 'chrome'
            assert str(path) == '/opt/google/chrome/chrome', 'not official Google Chrome executable'
        assert info['channel'] == options.get('channel') and info['launch_options'] == options, 'launch channel'
    print('PASS selected engine inventory; launched executable path/version/SHA256/arguments bound to original log')


def validate_protocol(protocol):
    normalized = dict(protocol)
    legacy = normalized.get('mode_labels') == LEGACY_MODE_LABELS
    if legacy:
        normalized['mode_labels'] = PROTOCOL['mode_labels']
    expected = PROTOCOL
    if 'protocol_version' in normalized:
        engines = normalized.get('engines', [])
        assert len(engines) == 1 and engines[0] in ('firefox', 'chrome', 'chromium'), 'protocol differs: engine inventory'
        expected = selected_protocol(engines[0], normalized.get('support_visuals', False))
        assert not legacy, 'protocol differs: selected labels'
    assert normalized == expected, 'protocol differs'
    if legacy:
        print('PASS known legacy labels explicitly normalized; '
              'classic=Chill, bad=Main for reporting only; sealed metadata unchanged')
    return normalized


def hashes(root):
    return {p: sha(b) for p, b in runtime_files(root).items()}


def summarize(raw, warmup=5000):
    active = warm = 0
    samples, gaps = [], []
    for a, b in zip(raw['frames'], raw['frames'][1:]):
        dt = b['t'] - a['t']
        assert math.isfinite(dt) and dt > 0, 'timestamp order'
        if not any(a['after'].values()) and not any(b['before'].values()):
            if active < warmup:
                warm += dt
            else:
                samples.append(dt)
            active += dt
        else:
            gaps.append({'start': a['t'], 'end': b['t'], 'ms': dt})
    assert samples, 'no measured intervals'
    return {'mean_ms': statistics.mean(samples),
            'p95_ms': sorted(samples)[math.ceil(.95*len(samples))-1],
            'warmup_ms': warm, 'measured_ms': sum(samples),
            'intervals_ms': samples, 'excluded_gaps': gaps}


def validate_capture_layout(layout):
    """Full-resolution landscape capture only; visual checkpoints may resize."""
    viewport = PROTOCOL['viewport']
    assert layout['viewport'] == viewport and layout['dpr'] == PROTOCOL['dpr'], 'viewport/DPR'
    assert layout['backing'] == [v * PROTOCOL['dpr'] for v in viewport], 'capture backing dimensions'
    # Touch geometry in gameoptions.js fixes height at 1080 and floors the
    # aspect-scaled width; logical units are independent of CSS pixels/DPR.
    logical = [math.floor(1080 * viewport[0] / viewport[1]), 1080]
    assert layout['logical'] == logical, 'capture logical dimensions'
    assert layout['css'] == viewport, 'capture CSS dimensions'


def aggregate(runs, smoke=False, protocol=None):
    protocol = validate_protocol(PROTOCOL if protocol is None else protocol)
    expected = [(e, m, n, a) for e in protocol['engines'] for m in PROTOCOL['modes']
                for n, order in enumerate(PROTOCOL['orders'][:1] if smoke else PROTOCOL['orders'])
                for a in order]
    assert [(r['engine'], r['mode'], r['pair'], r['arm']) for r in runs] == expected, 'arm order'
    pairs, groups = [], {}
    for r in runs:
        validate_capture_layout(r['layout'])
        assert r['metrics']['warmup_ms'] >= (100 if smoke else 5000), 'warmup duration'
        assert r['metrics']['measured_ms'] >= (300 if smoke else 30000), 'measured duration'
    for i in range(0, len(runs), 2):
        arms = {r['arm']: r for r in runs[i:i+2]}
        a, b = arms['control'], arms['candidate']
        p = {'engine': a['engine'], 'mode': a['mode'], 'pair': a['pair'],
             'control': a['metrics'], 'candidate': b['metrics']}
        for metric in ('mean_ms', 'p95_ms'):
            p[metric+'_regression'] = b['metrics'][metric]/a['metrics'][metric]-1
        pairs.append(p)
    for e in protocol['engines']:
        for m in PROTOCOL['modes']:
            ps = [p for p in pairs if (p['engine'], p['mode']) == (e, m)]
            groups[e+'/'+m] = {k: statistics.median(p[k] for p in ps)
                              for k in ('mean_ms_regression', 'p95_ms_regression')}
    # Tiny epsilon handles floating representation of the inclusive boundaries only.
    accepted = ('protocol_version' not in protocol and any(groups['firefox/'+m]['mean_ms_regression'] <= -.10+1e-12 for m in PROTOCOL['modes'])
                and all(v <= .05+1e-12 for g in groups.values() for v in g.values()))
    return {'pairs': pairs, 'medians': groups, 'performance_accepted': accepted if not smoke else False,
            'scope': 'SMOKE_ONLY_NO_GAIN_CLAIM' if smoke else 'desktop comparison; visual review also required'}


def pixel_diff(a, b, dest=None):
    a, b = Image.open(a).convert('RGBA'), Image.open(b).convert('RGBA')
    assert a.size == b.size, 'image dimensions'
    delta = np.abs(np.array(a).astype('int16')-np.array(b).astype('int16'))
    if dest:
        ImageChops.difference(a, b).save(dest)
    return {'changed_pixels': int(np.any(delta != 0, axis=2).sum()),
            'max_per_channel': delta.max(axis=(0, 1)).tolist(),
            'sum_per_channel': delta.sum(axis=(0, 1)).tolist()}


def audit(out):
    receipt = read(out/'manifest.json')
    assert receipt['exit_code'] == 0, 'failed attempt'
    identity_keys = ('command', 'cwd', 'started_utc', 'execution_id')
    assert all(receipt.get(k) for k in identity_keys), 'missing execution identity'
    assert receipt.get('ended_utc') and receipt.get('harness_sha256'), 'missing execution identity'
    seals = receipt['evidence_sha256']
    def require_seals(paths):
        for p in sorted(set(paths)):
            assert p in seals, 'missing evidence seal: ' + p
            assert (out/p).is_file(), 'missing evidence file: ' + p
    require_seals(('results.json', 'protocol.json', 'network.json',
                   'command.log', 'tested-harness.py'))
    for p, h in receipt['evidence_sha256'].items():
        assert sha((out/p).read_bytes()) == h, p+' hash mismatch'
    lines = (out/'command.log').read_text().splitlines()
    assert lines and lines[0].startswith('EXECUTION ') and lines[-1].startswith('EXIT '), 'command identity'
    identity = json.loads(lines[0].removeprefix('EXECUTION '))
    ending = json.loads(lines[-1].removeprefix('EXIT '))
    assert all(identity.get(k) == receipt[k] for k in identity_keys), 'command identity'
    assert ending['execution_id'] == receipt['execution_id'] and ending['exit_code'] == 0, 'command exit identity'
    assert receipt['started_utc'] <= ending['ended_utc'] <= receipt['ended_utc'], 'command timing'
    assert 'PASS capture completed; no device FPS claim' in lines
    assert sha((out/'tested-harness.py').read_bytes()) == receipt['harness_sha256'], 'harness hash mismatch'
    protocol = validate_protocol(read(out/'protocol.json'))
    if 'protocol_version' in protocol:
        require_seals(('environment.json',))
        audit_browsers(read(out/'environment.json'), protocol, lines)
        command = receipt['command']
        selections = [command[i+1] if token == '--engine' else token.split('=', 1)[1]
                      for i, token in enumerate(command) if token == '--engine' or token.startswith('--engine=')]
        assert selections == protocol['engines'], 'command engine'
    data = read(out/'results.json')
    assert data['kind'] in ('capture', 'visuals'), 'unknown receipt kind'
    if data['kind'] == 'capture':
        require_seals(r['raw'] for r in data['runs'])
    else:
        require_seals(r[k] for r in data['comparisons']
                      for k in ('control', 'candidate', 'control_state', 'candidate_state'))
    for arm, root in data['roots'].items():
        assert hashes(Path(root)) == data['sources'][arm], 'runtime hash mismatch'
    assert data['fixture_sha256'] == sha(FIXTURE.encode()), 'SDK fixture mismatch'
    assert not data['errors'], 'browser errors'
    network = read(out/'network.json')
    assert network and all(n['action'] in ('LOCAL', 'SDK_STUB', 'BLOCKED') for n in network)
    assert all(n['url'] == SDK for n in network if n['action'] == 'SDK_STUB')
    if data['kind'] == 'capture':
        for r in data['runs']:
            raw = read(out/r['raw'])
            assert summarize(raw, 100 if data['smoke'] else 5000) == r['metrics'], 'raw metric mismatch'
            assert raw['layout'] == r['layout'], 'raw layout mismatch'
            assert raw['source_sha256'] == data['sources'][r['arm']], 'raw source mismatch'
            assert raw['seed'] == SEED and raw['input_policy'] == INPUT, 'input policy mismatch'
            assert raw['inputs'] and raw['transitions'], 'missing input/state traces'
        assert aggregate(data['runs'], data['smoke'], protocol) == data['comparison'], 'aggregate mismatch'
        print('PASS raw metric recomputation; duration/order/backing/hash; inactive gaps excluded; slow active/death-ending retained')
    else:
        expected = [(e, c) for e in protocol['engines'] for c in protocol['visual_checkpoints']]
        assert [(r['engine'], r['checkpoint']) for r in data['comparisons']] == expected
        for r in data['comparisons']:
            actual = pixel_diff(out/r['control'], out/r['candidate'])
            assert actual == r['pixels'], 'pixel recomputation'
            states = [read(out/r[a+'_state']) for a in ('control', 'candidate')]
            assert (states[0] == states[1]) == r['state_equal'], 'state equality mismatch'
            assert r['state_equal'], 'gameplay state differs'
        print('PASS deterministic screenshots/state; per-channel differences and changed-pixel counts recomputed')
    print('PASS snapshot hashes; identical SDK boundary; zero browser errors; network isolated')


def worker(args):
    out = args.out
    protocol = selected_protocol(args.engine, args.support_visuals)
    def timeout(signum, frame):
        raise TimeoutError('arm exceeded 120 seconds' if signum == signal.SIGALRM else 'invocation budget exceeded')
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGTERM, timeout)
    roots = {a: getattr(args, a).resolve() for a in ('control', 'candidate')}
    sources = {a: hashes(r) for a, r in roots.items()}
    errors, network, runs, comparisons = [], [], [], []
    data = {'kind': args.command, 'smoke': args.smoke, 'roots': {a: str(r) for a, r in roots.items()},
            'sources': sources, 'fixture_sha256': sha(FIXTURE.encode()), 'errors': errors,
            'runs': runs, 'comparisons': comparisons,
            'visual_method': 'Manual clock and seeded gameLoop; explicit pause/death flags, edge player placement, emitPlayerParticles and triggerDeath fixtures. Full-page touch viewport screenshots. These are deterministic rendering fixtures, not natural-timing gameplay or device input proof.'}
    environment = {'os': platform.platform(), 'playwright': importlib.metadata.version('playwright'), 'browsers': {}, 'native_android': 'UNVERIFIED',
                   'kind': 'headless desktop; touch/viewport emulation', 'layouts': []}
    write(out/'protocol.json', protocol)
    with ExitStack() as stack:
        origins = {}
        for arm, root in roots.items():
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
            stack.callback(server.server_close)
            Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            origins[arm] = f'http://127.0.0.1:{server.server_port}'
        def route_request(route):
            url = route.request.url
            action = 'LOCAL' if any(url.startswith(o+'/') for o in origins.values()) else 'SDK_STUB' if url == SDK else 'BLOCKED'
            network.append({'url': url, 'action': action})
            if action == 'LOCAL': route.continue_()
            elif action == 'SDK_STUB': route.fulfill(content_type='application/javascript', body=FIXTURE)
            else: route.abort()
        pw = stack.enter_context(sync_playwright())
        try:
            for engine in protocol['engines']:
                browser, provenance = launch_browser(pw, engine)
                environment['browsers'][engine] = provenance
                try:
                    def open_page(arm, frozen=False):
                        context = browser.new_context(viewport={'width': 844, 'height': 390},
                            device_scale_factor=2, has_touch=True, locale='en-US', service_workers='block')
                        context.route('**/*', route_request)
                        context.add_init_script(SEED_SCRIPT % SEED)
                        if frozen: context.add_init_script(CLOCK_SCRIPT)
                        page = context.new_page()
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
                        page.goto(origins[arm]+'/index.html')
                        if frozen: boot_frozen(page)
                        else: page.wait_for_function('bootComplete && document.getElementById("loading").hidden')
                        environment['layouts'].append(page.evaluate(LAYOUT))
                        return context, page
                    if args.command == 'capture':
                        for mode in PROTOCOL['modes']:
                            for pair, order in enumerate(PROTOCOL['orders'][:1] if args.smoke else PROTOCOL['orders']):
                                for arm in order:
                                    signal.alarm(120)
                                    key = f'{engine}-{mode}-{pair}-{arm}'
                                    context, page = open_page(arm)
                                    layout = page.evaluate(LAYOUT)
                                    page.evaluate(TIMING_PROBE, {'mode': mode, 'inputs': INPUT, 'seed': SEED})
                                    # Wait in bounded chunks until whole measured intervals satisfy duration.
                                    deadline = time.monotonic() + (20 if args.smoke else 120)
                                    while True:
                                        page.wait_for_timeout(200)
                                        raw = page.evaluate('perfReceipt')
                                        try: result = summarize(raw, 100 if args.smoke else 5000)
                                        except AssertionError: result = {'measured_ms': 0}
                                        if result['measured_ms'] >= (600 if args.smoke else 30000): break
                                        assert time.monotonic() < deadline, 'arm active-time budget exceeded'
                                    raw.update(layout=layout, source_sha256=sources[arm], seed=SEED, input_policy=INPUT,
                                               state=page.evaluate(STATE))
                                    write(out/(key+'-raw.json'), raw)
                                    page.screenshot(path=str(out/(key+'.png')), timeout=15000)
                                    runs.append({'engine': engine, 'mode': mode, 'pair': pair, 'arm': arm,
                                        'layout': layout, 'metrics': result, 'raw': key+'-raw.json'})
                                    print(f'RECORDED {key} measured_ms={result["measured_ms"]}', flush=True)
                                    context.close()
                                    signal.alarm(0)
                                    write(out/'results.json', data)
                        data['comparison'] = aggregate(runs, args.smoke, protocol) if engine == protocol['engines'][-1] else None
                    else:
                        captures = {}
                        for arm in ('control', 'candidate'):
                            signal.alarm(120)
                            context, page = open_page(arm, True)
                            page.evaluate('''() => {window.stepVisual = n => {for(let i=0;i<n;i++) {
                                __snap.tick++; __snap.now=__snap.tick*1000/60; __snap.runTimers(); gameLoop(__snap.now);
                            }}; menu.draw();}''')
                            for checkpoint in protocol['visual_checkpoints']:
                                if checkpoint.startswith('support:'):
                                    from playgama_support_visuals import apply
                                    apply(page, checkpoint)
                                elif checkpoint in ('classic', 'bad'):
                                    page.evaluate('(mode)=>{startGame(mode); stepVisual(25)}', checkpoint)
                                elif checkpoint == 'pause': page.evaluate('menu.gamePaused=true; gameLoop(__snap.now)')
                                elif checkpoint == 'death': page.evaluate('menu.gamePaused=false; continueOffer.visible=true; gameLoop(__snap.now)')
                                elif checkpoint == 'touch-portrait':
                                    page.set_viewport_size({'width':390,'height':844})
                                    page.evaluate('onViewportResize()')
                                elif checkpoint in ('touch-landscape', 'resize'):
                                    page.set_viewport_size({'width':844 if checkpoint=='touch-landscape' else 900,'height':390})
                                    page.evaluate('onViewportResize(); gameLoop(__snap.now)')
                                elif checkpoint == 'screen-edges':
                                    page.evaluate('continueOffer.visible=false; ninja.x=-screen.x+2; draw()')
                                elif checkpoint == 'player-trail-sparks-shake':
                                    page.evaluate('''startGame('bad'); stepVisual(25);
                                        visualEffects.particles.emitPlayerParticles(ninja);
                                        visualEffects.screenEffects.triggerDeath(ninja.x,ninja.y); draw()''')
                                key = f'{engine}-{checkpoint}-{arm}'
                                page.screenshot(path=str(out/(key+'.png')), timeout=15000)
                                state = page.evaluate(STATE)
                                if checkpoint.startswith('support:'):
                                    from playgama_support_visuals import state as support_state
                                    state['support_fixture'] = support_state(page)
                                write(out/(key+'-state.json'), state)
                                captures[checkpoint, arm] = key
                            context.close()
                            signal.alarm(0)
                        for checkpoint in protocol['visual_checkpoints']:
                            a, b = [captures[checkpoint, arm] for arm in ('control', 'candidate')]
                            diff = pixel_diff(out/(a+'.png'), out/(b+'.png'), out/(a+'-diff.png'))
                            equal = read(out/(a+'-state.json')) == read(out/(b+'-state.json'))
                            comparisons.append({'engine': engine, 'checkpoint': checkpoint,
                                'control': a+'.png', 'candidate': b+'.png',
                                'control_state': a+'-state.json', 'candidate_state': b+'-state.json',
                                'pixels': diff, 'state_equal': equal,
                                'review': 'IDENTICAL' if not diff['changed_pixels'] else 'REQUIRES_RECORDED_VISUAL_REVIEW'})
                            print(f'VISUAL {engine} {checkpoint} state_equal={equal} changed_pixels={diff["changed_pixels"]}', flush=True)
                finally: browser.close()
        finally:
            signal.alarm(0)
            write(out/'results.json', data)
            write(out/'environment.json', environment)
            write(out/'network.json', network)
    assert not errors, errors
    assert all(hashes(roots[a]) == sources[a] for a in roots), 'snapshot mutated'
    print('PASS capture completed; no device FPS claim', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('capture', 'visuals'):
        p = subs.add_parser(name)
        for arg in ('control', 'candidate', 'out'): p.add_argument('--'+arg, type=Path, required=True)
        p.add_argument('--engine', choices=('firefox', 'chrome', 'chromium'),
                       help='select one engine; chrome uses official Google Chrome; default: historical Firefox/Chromium matrix')
        p.add_argument('--support-visuals', action='store_true', help='append both-mode support fixtures; requires --engine and visuals')
        p.add_argument('--smoke', action='store_true', help='bounded plumbing run; never performance acceptance')
        p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    p = subs.add_parser('audit'); p.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'audit': audit(args.input); return
    if args.support_visuals:
        assert args.command == 'visuals' and args.engine, 'support fixtures require selected-engine visuals'
    if args.worker: worker(args); return
    assert not args.out.exists(), 'preserve prior attempts; use a fresh output directory'
    args.out.mkdir(parents=True)
    tested_harness = Path(__file__).read_bytes()
    (args.out/'tested-harness.py').write_bytes(tested_harness)
    if args.support_visuals:
        (args.out/'tested-support-fixtures.py').write_bytes(Path(__file__).with_name('playgama_support_visuals.py').read_bytes())
    command = ['timeout', '--signal=TERM', '--kill-after=5s', '715s', sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
    identity = {'command': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
                'started_utc': utc(), 'execution_id': str(time.time_ns())}
    started = time.monotonic()
    code = capture_command(command, args.out/'command.log', identity)
    write(args.out/'manifest.json', dict(identity, ended_utc=utc(), duration_seconds=time.monotonic()-started,
        exit_code=code, harness_sha256=sha(tested_harness),
        evidence_sha256={str(p.relative_to(args.out)):sha(p.read_bytes()) for p in args.out.rglob('*') if p.is_file()}))
    if code == 0: audit(args.out)
    raise SystemExit(code)


if __name__ == '__main__': main()
