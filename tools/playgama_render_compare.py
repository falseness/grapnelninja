"""Current immutable runtime comparison; desktop emulation, never device FPS proof.

capture defaults to the full AB/BA/AB protocol. --smoke is plumbing validation
only. visuals uses a manual clock and explicit fixtures, never performance data.
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
    'mode_labels': {'classic': 'Main', 'bad': 'Chill'},
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


def aggregate(runs, smoke=False):
    expected = [(e, m, n, a) for e in PROTOCOL['engines'] for m in PROTOCOL['modes']
                for n, order in enumerate(PROTOCOL['orders'][:1] if smoke else PROTOCOL['orders'])
                for a in order]
    assert [(r['engine'], r['mode'], r['pair'], r['arm']) for r in runs] == expected, 'arm order'
    layout = runs[0]['layout']
    pairs, groups = [], {}
    for r in runs:
        assert r['layout']['viewport'] == [844, 390] and r['layout']['dpr'] == 2, 'viewport/DPR'
        assert all(r['layout'][k] == layout[k] for k in ('backing', 'logical', 'css')), 'backing/layout mismatch'
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
    for e in PROTOCOL['engines']:
        for m in PROTOCOL['modes']:
            ps = [p for p in pairs if (p['engine'], p['mode']) == (e, m)]
            groups[e+'/'+m] = {k: statistics.median(p[k] for p in ps)
                              for k in ('mean_ms_regression', 'p95_ms_regression')}
    # Tiny epsilon handles floating representation of the inclusive boundaries only.
    accepted = (any(groups['firefox/'+m]['mean_ms_regression'] <= -.10+1e-12 for m in PROTOCOL['modes'])
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
    for p, h in receipt['evidence_sha256'].items():
        assert sha((out/p).read_bytes()) == h, p+' hash mismatch'
    if 'execution_id' in receipt:
        lines = (out/'command.log').read_text().splitlines()
        identity = json.loads(lines[0].removeprefix('EXECUTION '))
        ending = json.loads(lines[-1].removeprefix('EXIT '))
        assert all(receipt[k] == v for k, v in identity.items()), 'command identity'
        assert ending['execution_id'] == receipt['execution_id'] and ending['exit_code'] == 0
        assert receipt['started_utc'] <= ending['ended_utc'] <= receipt['ended_utc']
        assert 'PASS capture completed; no device FPS claim' in lines
        assert sha((out/'tested-harness.py').read_bytes()) == receipt['harness_sha256']
    data = read(out/'results.json')
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
        assert aggregate(data['runs'], data['smoke']) == data['comparison'], 'aggregate mismatch'
        print('PASS raw metric recomputation; duration/order/backing/hash; inactive gaps excluded; slow active/death-ending retained')
    else:
        expected = [(e, c) for e in PROTOCOL['engines'] for c in PROTOCOL['visual_checkpoints']]
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
    roots = {a: getattr(args, a).resolve() for a in ('control', 'candidate')}
    sources = {a: hashes(r) for a, r in roots.items()}
    errors, network, runs, comparisons = [], [], [], []
    data = {'kind': args.command, 'smoke': args.smoke, 'roots': {a: str(r) for a, r in roots.items()},
            'sources': sources, 'fixture_sha256': sha(FIXTURE.encode()), 'errors': errors,
            'runs': runs, 'comparisons': comparisons,
            'visual_method': 'Manual clock and seeded gameLoop; explicit pause/death flags, edge player placement, emitPlayerParticles and triggerDeath fixtures. Full-page touch viewport screenshots. These are deterministic rendering fixtures, not natural-timing gameplay or device input proof.'}
    environment = {'os': platform.platform(), 'playwright': importlib.metadata.version('playwright'), 'browsers': {}, 'native_android': 'UNVERIFIED',
                   'kind': 'headless desktop; touch/viewport emulation', 'layouts': []}
    write(out/'protocol.json', PROTOCOL)
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
            for engine in PROTOCOL['engines']:
                kind = getattr(pw, engine)
                browser = kind.launch(headless=True)
                environment['browsers'][engine] = {'version': browser.version,
                    'executable_sha256': sha(Path(kind.executable_path).read_bytes())}
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
                                    write(out/'results.json', data)
                        data['comparison'] = aggregate(runs, args.smoke) if engine == 'chromium' else None
                    else:
                        captures = {}
                        for arm in ('control', 'candidate'):
                            context, page = open_page(arm, True)
                            page.evaluate('''() => {window.stepVisual = n => {for(let i=0;i<n;i++) {
                                __snap.tick++; __snap.now=__snap.tick*1000/60; __snap.runTimers(); gameLoop(__snap.now);
                            }}; menu.draw();}''')
                            for checkpoint in PROTOCOL['visual_checkpoints']:
                                if checkpoint in ('classic', 'bad'):
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
                                write(out/(key+'-state.json'), page.evaluate(STATE))
                                captures[checkpoint, arm] = key
                            context.close()
                        for checkpoint in PROTOCOL['visual_checkpoints']:
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
        p.add_argument('--smoke', action='store_true', help='bounded plumbing run; never performance acceptance')
        p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    p = subs.add_parser('audit'); p.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'audit': audit(args.input); return
    if args.worker: worker(args); return
    assert not args.out.exists(), 'preserve prior attempts; use a fresh output directory'
    args.out.mkdir(parents=True)
    tested_harness = Path(__file__).read_bytes()
    (args.out/'tested-harness.py').write_bytes(tested_harness)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
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
