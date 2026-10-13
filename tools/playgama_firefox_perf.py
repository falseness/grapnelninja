"""Offline published-baseline performance receipts; desktop engines, never native Android.

baseline rebuilds the historical ZIP byte-for-byte, serves its unmodified members,
then measures sequential arms (no competing browsers). audit uses saved timestamps
only. Death screens are restarted through normal button events; inactive gaps are
explicit and excluded, never slow active frames. No rendering/physics overrides.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import partial
import hashlib
from http.server import ThreadingHTTPServer
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from threading import Thread
import uuid

from playwright.sync_api import sync_playwright
from browser_test_support import QuietHandler
from test_playgama2_bridge import FAKE, SDK
from perf_mobile import SEED_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'a570592a1a52b9af0278efa7583874ae25419d0d'
ZIP_SHA = '78473df0ecdb9f959351c517cc60c10c141a1e451ac03ac10232425a29ef88c7'
SEED = 292
INPUT = [{'at_active_ms': t, 'type': 'mousedown' if i % 2 == 0 else 'mouseup',
          'x': 650, 'y': 100} for i, t in enumerate(range(500, 35000, 500))]


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def read(path):
    return json.loads(path.read_text())


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


# Each row brackets the actual gameLoop callback. Its RAF timestamp, rather than
# a timer or a sampled FPS counter, is the basis of every reported interval.
PROBE = r'''async ({mode, inputs, seed}) => {
    const state = () => ({pause: menu.gamePaused,
        death: continueOffer.visible, ad: adOpen || interstitialPending,
        host: hostPaused, portrait: isViewRotated(), hidden: document.hidden});
    const active = s => !Object.values(s).some(Boolean);
    const p = window.perfReceipt = {frames: [], inputs: [], transitions: [],
        activeMs: 0, done: false, accepted_input_ms: null, first_active_frame_ms: null};
    let previous = null, nextInput = 0, lastRestart = -Infinity, lastState = '';
    function dispatch(type, x, y) {
        document.dispatchEvent(new MouseEvent(type, {bubbles:true, clientX:x, clientY:y}));
    }
    function button(b, s = 1) {
        const r = canvas.getBoundingClientRect();
        const x = r.x + (b.x + b.width/2) * s * r.width/width;
        const y = r.y + (b.y + b.height/2) * s * r.height/height;
        dispatch('mousedown', x, y); dispatch('mouseup', x, y);
    }
    const frame = () => new Promise(requestAnimationFrame);
    async function until(test) {
        for (let i = 0; i < 600 && !test(); i++) await frame();
        if (!test()) throw new Error('START timed out in '+version);
    }
    // Reset immediately before the start input so boot-run and pause frame
    // counts do not consume a different portion of the seeded random sequence.
    function seedRandom() {
        let a = seed >>> 0;
        Math.random = () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
            t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    }
    // The page boots straight into a 'bad' run (TASK-360/364). 'bad' is that
    // run: its accepted input is the first press that throws the grapnel.
    // 'classic' is reached through the HUD button and the pause mode switch.
    await until(() => bootComplete && runInProgress && !unTouch);
    if (version !== mode) {
        if (!menu.gamePaused) button(menu.button.background, scale[version]);
        await until(() => menu.gamePaused && !unTouch);
        seedRandom();
        button(menu.backToMenu.background);
        // The switch leaves the paused run first (leaveFinishedRun)
        await until(() => version === mode && runInProgress && !menu.gamePaused);
        p.accepted_input_ms = performance.now();
    } else {
        await until(() => !menu.gamePaused && !continueOffer.visible && !grapnel.throwed);
        seedRandom();
        const r = canvas.getBoundingClientRect();
        dispatch('mousedown', r.x + r.width*.7, r.y + r.height*.3);
        if (grapnel.throwed) p.accepted_input_ms = performance.now();
        dispatch('mouseup', r.x + r.width*.7, r.y + r.height*.3);
    }
    if (p.accepted_input_ms === null) throw new Error('START input not accepted in '+version);
    // Measure from the started run only; the boot run before it is not counted.
    const original = gameLoop;
    gameLoop = function(t) {
        const before = state();
        if (previous && active(previous.after) && active(before))
            p.activeMs += t - previous.t;
        const signature = JSON.stringify(before);
        if (signature !== lastState) {
            p.transitions.push({t, state: before}); lastState = signature;
        }
        if (active(before)) {
            if (p.first_active_frame_ms === null) p.first_active_frame_ms = t;
            while (nextInput < inputs.length && inputs[nextInput].at_active_ms <= p.activeMs) {
                const input = inputs[nextInput++];
                dispatch(input.type, input.x, input.y);
                p.inputs.push({...input, actual_active_ms:p.activeMs, t});
            }
        } else if (before.death && !before.ad && t - lastRestart >= 500) {
            p.transitions.push({t, action:'restart-button'});
            button(continueOffer.restartButton.background); lastRestart = t;
        }
        original(t);
        const row = {t, before, after:state(), activeMs:p.activeMs};
        p.frames.push(row); previous = row;
        if (p.activeMs >= 35000) p.done = true;
    };
}'''

LAYOUT = '''() => {
 const c = document.getElementById('canvas');
 const gl = document.createElement('canvas').getContext('webgl');
 const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
 return {viewport:[innerWidth,innerHeight], dpr:devicePixelRatio,
 backing:[c.width,c.height], css:[c.clientWidth,c.clientHeight],
 logical:[width,height], portrait:isViewRotated(), paused:menu.gamePaused,
 graphics:gl ? {version:gl.getParameter(gl.VERSION),
 renderer:ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
 vendor:ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR)} :
 {renderer:'UNAVAILABLE: WebGL context unsupported; Canvas2D renderer not exposed'},
 user_agent:navigator.userAgent};
}'''


def metrics(raw):
    intervals, gaps = [], []
    active_ms = 0
    warmup_ms = 0
    for prev, row in zip(raw['frames'], raw['frames'][1:]):
        dt = row['t'] - prev['t']
        assert dt > 0, 'nonmonotonic frame timestamp'
        if not any(prev['after'].values()) and not any(row['before'].values()):
            # Keep the entire boundary interval as warmup, never trim a slow frame.
            if active_ms < 5000:
                warmup_ms += dt
            else:
                intervals.append(dt)
            active_ms += dt
        else:
            gaps.append({'start': prev['t'], 'end': row['t'], 'ms': dt,
                         'after': prev['after'], 'before': row['before']})
    ordered = sorted(intervals)
    def percentile(q):
        return ordered[max(0, math.ceil(len(ordered)*q)-1)] if ordered else None
    return {'average_fps': len(intervals)*1000/sum(intervals) if intervals else None,
            'p50_frame_ms': percentile(.5), 'p95_frame_ms': percentile(.95),
            'active_ms': active_ms, 'warmup_ms': warmup_ms,
            'measured_ms': sum(intervals), 'frame_intervals_ms': intervals,
            'excluded_gaps': gaps, 'slow_frames_dropped': 0}


def baseline(args):
    out = args.out
    # Existing attempts are immutable. A rerun belongs in a new --out directory.
    if (out/'manifest.json').exists():
        raise ValueError('Output already has an attempt; use a fresh --out directory')
    out.mkdir(parents=True, exist_ok=True)
    revision = git('rev-parse', args.revision+'^{commit}').decode().strip()
    assert revision == REVISION, 'baseline must be the published revision'
    builder = git('show', revision+':tools/build_playgama.py')
    ns = {'__name__':'historical_builder', '__file__':str(ROOT/'tools/build_playgama.py')}
    exec(compile(builder, revision+':tools/build_playgama.py', 'exec'), ns)
    blobs = {p:git('show', revision+':'+p) for p in ('index.html','playgama-bridge-config.json')}
    refs = ns['References'](); refs.feed(blobs['index.html'].decode())
    for path in refs.paths:
        if path != SDK:
            blobs[path] = git('show', revision+':'+path)
    packed = ns['bundle'](blobs)
    archive = ns['archive'](packed)
    assert sha(archive) == ZIP_SHA, 'published build bytes differ'
    (out/'baseline.zip').write_bytes(archive)
    root = out/'served'; root.mkdir()
    for path, data in packed.items():
        dest = root/path; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
    build = {'revision':revision, 'zip_sha256':sha(archive),
             'source_sha256':{p:sha(b) for p,b in blobs.items()},
             'served_sha256':{p:sha(b) for p,b in packed.items()},
             'quality':'Unmodified published bundle; no density, rendering or physics overrides'}
    write(out/'build.json', build)
    print(f'BUILD revision={revision} zip_sha256={sha(archive)}', flush=True)
    runs, startup, layouts = [], [], []
    environment = {'os':platform.platform(), 'os_release':Path('/etc/os-release').read_text(),
                   'playwright':importlib.metadata.version('playwright'), 'browsers':{},
                   'native_android':'UNVERIFIED', 'execution':'headless desktop engines; mobile sizes are emulation'}
    graphics_command=['dpkg-query','-W','libgl1-mesa-dri','libegl-mesa0']
    graphics_started=utc()
    graphics=subprocess.run(graphics_command,capture_output=True,text=True,cwd=ROOT)
    environment['host_graphics_packages']={'command':graphics_command,'cwd':str(ROOT),
        'started_utc':graphics_started,'ended_utc':utc(),'exit_code':graphics.returncode,
        'stdout':graphics.stdout,'stderr':graphics.stderr}
    environment['graphics_note']='Installed Mesa versions; actual Canvas2D renderer unavailable when not exposed by browser'
    with ExitStack() as stack:
        server = ThreadingHTTPServer(('127.0.0.1',0), partial(QuietHandler,directory=str(root.resolve())))
        stack.callback(server.server_close)
        Thread(target=server.serve_forever,daemon=True).start(); stack.callback(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        network = stack.enter_context((out/'network.log').open('w'))
        def route_request(route):
            url = route.request.url
            action = 'LOCAL' if url.startswith(origin+'/') else 'SDK_STUB' if url == SDK else 'BLOCKED'
            network.write(json.dumps({'url':url,'action':action,'utc':utc()})+'\n'); network.flush()
            if action == 'LOCAL': route.continue_()
            elif action == 'SDK_STUB':
                route.fulfill(content_type='application/javascript',body="const FAULT='normal'; const SAVED_LANGUAGE='en';\n"+FAKE)
            else: route.abort()
        pw = stack.enter_context(sync_playwright())
        for engine in ('firefox','chromium'):
            kind = getattr(pw,engine)
            browser = kind.launch(headless=True)
            environment['browsers'][engine] = {'version':browser.version,'executable':kind.executable_path,
                'executable_sha256':sha(Path(kind.executable_path).read_bytes())}
            try:
                def open_page(w,h,dpr):
                    context = browser.new_context(viewport={'width':w,'height':h},device_scale_factor=dpr,
                                                  has_touch=True,service_workers='block',locale='en-US')
                    context.route('**/*',route_request)
                    context.add_init_script(SEED_SCRIPT % SEED)
                    page = context.new_page(); page.set_default_timeout(15000)
                    page.goto(origin+'/index.html')
                    page.wait_for_function('bootComplete && document.getElementById("loading").hidden')
                    return context,page
                for w,h,dpr in ((1280,720,1),(390,844,2),(844,390,2)):
                    context,page = open_page(w,h,dpr)
                    data = page.evaluate(LAYOUT)
                    data.update(engine=engine,kind='desktop' if dpr==1 else 'desktop-engine mobile-size emulation',
                                purpose='orientation/start/layout probe; no sustained FPS')
                    data['interactive_menu_ms'] = page.evaluate('performance.now()')
                    if w < h:
                        page.evaluate("document.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,clientX:200,clientY:420}))")
                        # The rotated boot run stays paused: the press must not resume it.
                        data['portrait_start_blocked'] = page.evaluate('runInProgress && menu.gamePaused && isViewRotated()')
                    layouts.append(data); context.close()
                for mode in ('classic','bad'):
                    for repetition in (1,2):
                        key = f'{engine}-{mode}-{repetition}'
                        context,page = open_page(844,390,2)
                        errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
                        layout=page.evaluate(LAYOUT)
                        menu_ms=page.evaluate('performance.now()')
                        page.evaluate(PROBE,{'mode':mode,'inputs':INPUT,'seed':SEED})
                        # Wait for 5s warmup plus at least 30s of complete active intervals.
                        page.wait_for_function('perfReceipt.done',timeout=120000)
                        raw=page.evaluate('perfReceipt')
                        result=metrics(raw)
                        # Boundary warmup can exceed 5s by a frame; collect until measured >=30s.
                        if result['measured_ms'] < 30000:
                            page.wait_for_timeout(150)
                            raw=page.evaluate('perfReceipt'); result=metrics(raw)
                        raw.update(engine=engine,mode=mode,repetition=repetition,seed=SEED,
                                   input_sequence=INPUT,layout=layout,build_sha256=sha(archive),
                                   emulation=True,page_errors=errors)
                        write(out/(key+'-raw.json'),raw)
                        result.update(key=key,raw=key+'-raw.json',engine=engine,mode=mode,
                                      repetition=repetition,seed=SEED,input_sha256=sha(json.dumps(INPUT).encode()),
                                      layout=layout,build_sha256=sha(archive),emulation=True,
                                      transitions=raw['transitions'])
                        runs.append(result)
                        startup.append({'key':key,'interactive_menu_ms':menu_ms,
                                        'accepted_input_ms':raw['accepted_input_ms'],
                                        'first_active_frame_ms':raw['first_active_frame_ms'],
                                        'timing_origin':'navigation performance time; menu is observed-ready upper bound'})
                        write(out/'baseline-performance.json',{'runs':runs,'layouts':layouts,
                              'scope':'Measured baseline only; no performance improvement or native reproduction claimed'})
                        write(out/'startup.json',{'runs':startup,'known_android_firefox_report':
                              'Poor gameplay performance despite successful load; native Android UNVERIFIED'})
                        environment['layouts']=layouts
                        environment['active_layouts']={r['key']:r['layout'] for r in runs}
                        write(out/'environment.json',environment)
                        print(f"RECORDED {key} active={result['measured_ms']:.1f}ms FPS={result['average_fps']:.2f}",flush=True)
                        context.close()
            finally:
                browser.close()
        network.write(json.dumps({'verdict':'PASS no production analytics or ads; external requests stubbed or blocked',
                                  'external_requests_allowed':0})+'\n')
    audit_data(out)


def audit_data(out):
    manifest_path=out/'manifest.json'
    if manifest_path.exists():
        manifest=read(manifest_path)
        for path, expected in manifest['evidence_sha256'].items():
            assert sha((out/path).read_bytes()) == expected, path+' hash mismatch'
        assert manifest['result']=='PASS', 'baseline attempt failed'
        lines=(out/'baseline-command.log').read_text().splitlines()
        identity=json.loads(lines[0].removeprefix('EXECUTION '))
        ending=json.loads(lines[-1].removeprefix('EXIT '))
        for key, value in identity.items():
            assert manifest[key]==value, 'console execution identity mismatch: '+key
        assert ending['execution_id']==manifest['execution_id'] and ending['exit_code']==0
        assert manifest['started_utc']<=ending['ended_utc']<=manifest['ended_utc']
        assert f'BUILD revision={REVISION} zip_sha256={ZIP_SHA}' in lines
        for engine in ('firefox','chromium'):
            for mode in ('classic','bad'):
                for repetition in (1,2):
                    marker=f'RECORDED {engine}-{mode}-{repetition} '
                    assert sum(line.startswith(marker) for line in lines)==1, marker
        assert 'PASS experiment completion; performance success not asserted; native Android UNVERIFIED' in lines
        print('PASS original console capture; matching execution identity, exit, build and eight samples')
    build=read(out/'build.json')
    assert build['zip_sha256']==ZIP_SHA==sha((out/'baseline.zip').read_bytes())
    for path, expected in build['served_sha256'].items():
        assert sha((out/'served'/path).read_bytes())==expected
    report=read(out/'baseline-performance.json'); runs=report['runs']
    assert len(runs)==8
    assert {(r['engine'],r['mode'],r['repetition']) for r in runs} == {
        (e,m,n) for e in ('firefox','chromium') for m in ('classic','bad') for n in (1,2)}
    identities=[]
    for run in runs:
        raw=read(out/run['raw']); actual=metrics(raw)
        for k,v in actual.items(): assert run[k]==v, run['key']+' metric mismatch '+k
        assert actual['measured_ms']>=30000 and actual['warmup_ms']>=5000
        assert raw['seed']==SEED and raw['input_sequence']==INPUT
        assert [{k:i[k] for k in INPUT[0]} for i in raw['inputs']]==INPUT
        assert not raw['page_errors'], raw['page_errors']
        assert raw['build_sha256']==run['build_sha256']==ZIP_SHA
        layout=raw['layout']; assert layout==run['layout']
        assert layout['viewport']==[844,390] and layout['dpr']==2
        identities.append((layout['backing'],layout['logical'],layout['css']))
        print(f"PASS {run['key']}: 5s warmup + 30s active; actual timestamps; all slow frames retained; input/seed/build verified")
    assert all(i==identities[0] for i in identities), 'INVALID: differing backing/layout dimensions'
    layouts=report['layouts']; assert len(layouts)==6
    for e in ('firefox','chromium'):
        probes=[p for p in layouts if p['engine']==e]
        assert {(tuple(p['viewport']),p['dpr']) for p in probes}=={((1280,720),1),((390,844),2),((844,390),2)}
        assert next(p for p in probes if p['viewport']==[390,844])['portrait_start_blocked']
    startup=read(out/'startup.json')['runs']; assert len(startup)==8
    for r in startup:
        assert 0<r['interactive_menu_ms']<=r['accepted_input_ms']<=r['first_active_frame_ms']+50
    network=[json.loads(line) for line in (out/'network.log').read_text().splitlines()]
    assert network[-1]['external_requests_allowed']==0
    assert all(r.get('action') in ('LOCAL','BLOCKED','SDK_STUB') for r in network[:-1])
    assert all(r['url'].startswith('http://127.0.0.1:') for r in network[:-1] if r['action']=='LOCAL')
    assert all(r['url']==SDK for r in network[:-1] if r['action']=='SDK_STUB')
    print('PASS matching viewport/DPR/backing/input; separate portrait/layout and startup; network isolation; published build')
    print('PASS experiment completion; performance success not asserted; native Android UNVERIFIED')


def capture_command(command, log_path, identity):
    """Archive the child's original merged output before hashing the receipt."""
    with log_path.open('x') as log:
        log.write('EXECUTION ' + json.dumps(identity, sort_keys=True) + '\n')
        log.flush()
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        for line in iter(process.stdout.readline, b''):
            text = line.decode('utf-8', errors='replace')
            log.write(text); log.flush()
            sys.stdout.write(text); sys.stdout.flush()
        process.stdout.close()
        code = process.wait()
        log.write('EXIT ' + json.dumps({'execution_id':identity['execution_id'],
                  'ended_utc':utc(), 'exit_code':code}) + '\n')
    return code


# Diagnostic injection only: the served build is never rewritten. Suppress paint
# calls, not layer functions, so RNG, caches and effect updates still execute.
PROFILE_PROBE = r'''async ({mode, suppressed, frames}) => {
 const now = performance.now.bind(performance);
 let rng = 292, randomCalls = 0;
 Math.random = () => { randomCalls++; rng = (rng + 0x6D2B79F5) >>> 0;
   let t = rng; t = Math.imul(t ^ (t >>> 15), t | 1);
   t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
   return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
 startGame(mode); cancelAnimationFrame(game);
 const names = Object.keys(window).filter(n => /^draw.*Layer$/.test(n));
 let current = '', costs = {}, skipped = 0;
 for (const name of names) {
   const original = window[name];
   window[name] = function(...args) {
     const previous = current; current = name; const t = now();
     try { return original.apply(this,args); }
     finally { costs[name] = (costs[name] || 0) + now()-t; current = previous; }
   };
 }
 for (const method of ['drawImage','fill','stroke','fillRect','strokeRect','fillText','strokeText']) {
   const original = CanvasRenderingContext2D.prototype[method];
   CanvasRenderingContext2D.prototype[method] = function(...args) {
     if (current === suppressed) { skipped++; return; }
     return original.apply(this,args);
   };
 }
 const rows = [];
 const state = () => ({version, ninja:[ninja.x,ninja.y], camera:[screen.x,screen.y],
   floors:floors.map(f => [f.constructor.name,f.x,f.y,f.width,f.height]),
   randomCalls, rng, drawFrameId, transform:Array.from(['a','b','c','d','e','f'],k=>ctx.getTransform()[k]),
   pause:menu.gamePaused, death:continueOffer.visible});
 for (let i=0; i<frames+8; i++) {
   const t = await new Promise(requestAnimationFrame);
   costs = {}; skipped = 0;
   // The effects' wall clock is matched while timings retain the real clock.
   Object.defineProperty(performance,'now',{configurable:true,value:()=>1000+i*16.6666667});
   const before = state(), begin = now();
   draw();
   const drawMs = now()-begin, after = state();
   delete performance.now;
   rows.push({t,draw_ms:drawMs,costs,skipped,before,after});
 }
 const end = await new Promise(requestAnimationFrame);
 return {rows,end,names,frames,warmup:8,suppressed,mode};
}'''


def profile_metrics(raw):
    rows=raw['rows']; active=rows[raw['warmup']:]
    assert len(active)==raw['frames'] and active
    times=[r['t'] for r in rows]+[raw['end']]
    intervals=[b-a for a,b in zip(times,times[1:])][raw['warmup']:]
    assert all(t>0 for t in intervals)
    return {'frame_ms':sum(intervals)/len(intervals),
            'draw_ms':sum(r['draw_ms'] for r in active)/len(active),
            'layer_ms':{n:sum(r['costs'].get(n,0) for r in active)/len(active) for n in raw['names']},
            'skipped':sum(r['skipped'] for r in active)}


def profile_conclusions(out, runs, selected):
    pairs=[]
    for engine in ('firefox','chromium'):
        for mode in ('classic','bad'):
            for layer in selected:
                savings=[]; controls=[]
                for repetition in (1,2):
                    arms={r['arm']:r for r in runs if (r['engine'],r['mode'],r['layer'],r['repetition'])==
                          (engine,mode,layer,repetition)}
                    assert set(arms)=={'control','suppressed'}
                    a,b=[read(out/arms[k]['raw']) for k in ('control','suppressed')]
                    assert [(r['before'],r['after']) for r in a['rows']]==[(r['before'],r['after']) for r in b['rows']], 'unmatched states'
                    assert a['layout']==b['layout'] and not a['errors'] and not b['errors']
                    am,bm=profile_metrics(a),profile_metrics(b)
                    assert bm['skipped']>0 and am['skipped']==0
                    controls.append(am['frame_ms']); savings.append(am['frame_ms']-bm['frame_ms'])
                noise=abs(controls[0]-controls[1])
                pairs.append({'engine':engine,'mode':mode,'layer':layer,'savings_ms':savings,
                    'control_spread_ms':noise,'mean_saving_ms':sum(savings)/2,
                    'repeatable':min(savings)>max(noise,1.0)})
    return pairs


def profile(args):
    out=args.out; base=args.baseline.resolve()
    audit_data(base)
    build=read(base/'build.json'); write(out/'build.json',build)
    sources={p:sha((ROOT/p).read_bytes()) for p in build['source_sha256']}
    write(out/'production-before.json',sources)
    # Read-only archival references, copied and hashed before any diagnosis.
    history={}
    for task,name in [('TASK-281','hypothesis.json'),('TASK-281','decision.json'),
                      ('TASK-280','decision.json'),('TASK-284','residual-deficit-notes.json')]:
        path=Path('/opt/grapnelninja/artifacts')/task/name
        data=path.read_bytes(); dest=f'history-{task}-{name}'
        (out/dest).write_bytes(data)
        history[str(path)]={'sha256':sha(data),'copy':dest}
    write(out/'history.json',history)
    environment={'os':platform.platform(),'playwright':importlib.metadata.version('playwright'),
        'native_android':'UNVERIFIED','browsers':{},'execution':'headless desktop; 844x390 DPR2 emulation',
        'limitations':'Frozen initial scene, no physics; RAF includes deferred rendering and scheduling. Layer timings measure JS/submission only, not exclusive raster costs. Suppression savings are nonadditive upper bounds, not quality-preserving optimizations. Chromium software graphics and unavailable Firefox Canvas2D renderer prevent native attribution.'}
    runs=[]; pilots=[]
    with ExitStack() as stack:
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(base/'served')))
        stack.callback(server.server_close); Thread(target=server.serve_forever,daemon=True).start()
        stack.callback(server.shutdown); origin=f'http://127.0.0.1:{server.server_port}'
        network=stack.enter_context((out/'network.log').open('w'))
        def route_request(route):
            url=route.request.url
            action='LOCAL' if url.startswith(origin+'/') else 'SDK_STUB' if url==SDK else 'BLOCKED'
            network.write(json.dumps({'url':url,'action':action})+'\n'); network.flush()
            if action=='LOCAL': route.continue_()
            elif action=='SDK_STUB': route.fulfill(content_type='application/javascript',body="const FAULT='normal'; const SAVED_LANGUAGE='en';\n"+FAKE)
            else: route.abort()
        pw=stack.enter_context(sync_playwright())
        def measure(browser,engine,mode,layer,repetition,arm):
            key=f'{engine}-{mode}-{layer}-{repetition}-{arm}'
            started=utc()
            with browser.new_context(viewport={'width':844,'height':390},device_scale_factor=2,
                    has_touch=True,service_workers='block',locale='en-US') as context:
                context.route('**/*',route_request); context.add_init_script(SEED_SCRIPT % SEED)
                page=context.new_page(); errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/index.html'); page.wait_for_function('bootComplete && document.getElementById("loading").hidden',timeout=15000)
                layout=page.evaluate(LAYOUT)
                raw=page.evaluate(PROFILE_PROBE,{'mode':mode,'suppressed':layer if arm=='suppressed' else '', 'frames':24})
                raw.update(layout=layout,errors=errors,engine=engine,build_sha256=ZIP_SHA)
                write(out/(key+'.json'),raw)
            result={'engine':engine,'mode':mode,'layer':layer,'repetition':repetition,'arm':arm,
                    'raw':key+'.json','metrics':profile_metrics(raw),'started_utc':started,'ended_utc':utc()}
            print('RECORDED '+key+' '+json.dumps(result['metrics']),flush=True)
            return result
        # Rank all instrumented layers using both Firefox modes before suppressing any.
        browser=pw.firefox.launch(headless=True)
        try:
            for mode in ('classic','bad'): pilots.append(measure(browser,'firefox',mode,'pilot',0,'control'))
        finally: browser.close()
        ranking={n:sum(p['metrics']['layer_ms'][n] for p in pilots)/len(pilots) for n in pilots[0]['metrics']['layer_ms']}
        selected=sorted(ranking,key=lambda n:(-ranking[n],n))[:3]
        write(out/'instrumentation.json',{'pilots':pilots,'ranking_ms':ranking,'selected':selected})
        for engine in ('firefox','chromium'):
            kind=getattr(pw,engine); browser=kind.launch(headless=True)
            environment['browsers'][engine]={'version':browser.version,'executable':kind.executable_path,
                'executable_sha256':sha(Path(kind.executable_path).read_bytes())}
            write(out/'environment.json',environment)
            try:
                for mode in ('classic','bad'):
                    for layer in selected:
                        for repetition in (1,2):
                            for arm in (('control','suppressed') if repetition==1 else ('suppressed','control')):
                                runs.append(measure(browser,engine,mode,layer,repetition,arm))
                                write(out/'runs.json',runs)
            finally: browser.close()
        network.write(json.dumps({'external_requests_allowed':0})+'\n')
    pairs=profile_conclusions(out,runs,selected)
    report={'runs':runs,'comparisons':pairs,'selected':selected,
        'dominant_repeatable':{f'{e}/{m}':next(iter(sorted([p for p in pairs if p['engine']==e and p['mode']==m and p['repeatable']],key=lambda p:-p['mean_saving_ms'])),None)
                               for e in ('firefox','chromium') for m in ('classic','bad')},
        'interpretation':environment['limitations'],
        'browser_comparison':'Compare savings and control spreads per mode/browser; a Firefox-only repeatable saving is local engine-specific evidence only. Repeated savings in both engines indicate shared drawing work, not proof of a native Firefox defect.'}
    write(out/'profile.json',report)
    write(out/'hypothesis.json',{'status':'no-supported-candidate',
        'reason':'Layer suppression locates cost but removes visible work. No new exact work-elimination mechanism is established by this bounded profile.',
        'source_references':['render/draw.js:draw','render/effects.js:BackgroundRenderer.paint','render/effects.js:BloomRenderer', 'history.json','profile.json'],
        'anticipated_removed_work':'None justified without changing quality; diagnostic suppressed paints are not a proposed optimization.',
        'history_review':'TASK-280 glow-region clipping already integrated; TASK-281 background row clipping rejected as inconsistent; TASK-279 background cache rejected for dither/transform differences (recorded in TASK-281 hypothesis). Do not repeat unchanged. TASK-284 transform pinning is unproven and cannot preserve the existing drifted pixels by assumption.',
        'native_android':'UNVERIFIED'})
    after={p:sha((ROOT/p).read_bytes()) for p in sources}
    write(out/'production-after.json',after); assert sources==after
    for p,h in build['served_sha256'].items(): assert sha((base/'served'/p).read_bytes())==h
    write(out/'quality.json',{'production_unchanged':sources==after,'served_unchanged':True,
        'suppression_location':'PROFILE_PROBE in tools/playgama_firefox_perf.py only; disposable browser contexts',
        'build_sha256':ZIP_SHA,'native_android':'UNVERIFIED'})
    audit_profile(out)


def audit_profile(out):
    if (out/'manifest.json').exists():
        manifest=read(out/'manifest.json'); assert manifest['exit_code']==0
        for p,h in manifest['evidence_sha256'].items(): assert sha((out/p).read_bytes())==h,p
        lines=(out/'profile-command.log').read_text().splitlines()
        identity=json.loads(lines[0].removeprefix('EXECUTION '))
        for k,v in identity.items(): assert manifest[k]==v
        ending=json.loads(lines[-1].removeprefix('EXIT ')); assert ending['exit_code']==0
        assert ending['execution_id']==manifest['execution_id']
        assert manifest['started_utc']<=ending['ended_utc']<=manifest['ended_utc']
        assert sum(l.startswith('RECORDED ') for l in lines)==50
        assert 'PASS profile completion; performance success not asserted; native Android UNVERIFIED' in lines
    instrumentation=read(out/'instrumentation.json')
    ranking={}
    for p in instrumentation['pilots']:
        actual=profile_metrics(read(out/p['raw'])); assert actual==p['metrics']
        for n,v in actual['layer_ms'].items(): ranking[n]=ranking.get(n,0)+v/2
    assert ranking==instrumentation['ranking_ms']
    selected=sorted(ranking,key=lambda n:(-ranking[n],n))[:3]
    assert selected==instrumentation['selected']
    report=read(out/'profile.json'); assert selected==report['selected']
    assert len(report['runs'])==48
    for r in report['runs']:
        raw=read(out/r['raw']); assert profile_metrics(raw)==r['metrics']
        assert raw['build_sha256']==ZIP_SHA and raw['mode']==r['mode'] and raw['engine']==r['engine']
        assert raw['suppressed']==(r['layer'] if r['arm']=='suppressed' else '')
    pairs=profile_conclusions(out,report['runs'],selected); assert pairs==report['comparisons']
    for key,value in report['dominant_repeatable'].items():
        e,m=key.split('/')
        assert value==next(iter(sorted([p for p in pairs if p['engine']==e and p['mode']==m and p['repeatable']],key=lambda p:-p['mean_saving_ms'])),None)
    assert read(out/'production-before.json')==read(out/'production-after.json')
    quality=read(out/'quality.json'); assert quality['production_unchanged'] and quality['served_unchanged']
    assert read(out/'hypothesis.json')['status']=='no-supported-candidate'
    for item in read(out/'history.json').values(): assert sha((out/item['copy']).read_bytes())==item['sha256']
    network=[json.loads(l) for l in (out/'network.log').read_text().splitlines()]
    assert network[-1]['external_requests_allowed']==0
    for r in network[:-1]:
        assert r['action'] in ('LOCAL','SDK_STUB','BLOCKED')
        if r['action']=='LOCAL': assert r['url'].startswith('http://127.0.0.1:')
        if r['action']=='SDK_STUB': assert r['url']==SDK
    print('PASS top-three instrumentation ranking; 24 matched pairs; raw timings and noise recomputed')
    print('PASS production/quality hashes unchanged; prior-history review; no-supported-candidate; network isolated')
    print('PASS profile completion; performance success not asserted; native Android UNVERIFIED')


def runtime_files(root):
    """Read the current runtime, including local start/telemetry fixes."""
    from build_playgama import References
    files = {p: (root/p).read_bytes() for p in ('index.html', 'playgama-bridge-config.json')}
    refs = References(); refs.feed(files['index.html'].decode())
    for path in refs.paths:
        if path == SDK:
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.[A-Za-z0-9]+', path):
            raise ValueError('Unsafe runtime reference: ' + path)
        files[path] = (root/path).read_bytes()
    return files


def no_candidate_decision(hypothesis, control):
    if hypothesis['status'] != 'no-supported-candidate':
        raise ValueError('Supported candidate requires a new bounded experiment implementation; refusing an untested decision')
    return {'decision': 'NO_SUPPORTED_CANDIDATE', 'hypothesis_tested': None,
            'reason': hypothesis['reason'], 'control_sha256': control,
            'candidate_sha256': None, 'candidate_status': 'NOT_CREATED',
            'runtime_sha256': control, 'performance_success': False,
            'experiment_status': 'NOT_RUN_NO_SUPPORTED_CANDIDATE',
            'native_android': 'UNVERIFIED'}


def compare(args):
    """Honor TASK-293's no-candidate outcome without inventing an optimization."""
    from build_playgama import archive, bundle
    out = args.out
    assert git('branch', '--show-current').decode().strip() == 'playgama-start-firefox'
    audit_profile(args.profile)
    hypothesis = read(args.profile/'hypothesis.json')
    # Fail before making a snapshot if evidence actually proposes a candidate.
    no_candidate_decision(hypothesis, '')
    sources = runtime_files(ROOT)
    source_hashes = {p: sha(b) for p, b in sources.items()}
    prior = read(args.start_evidence/'manifest.json')
    assert prior['verdict'].startswith('PASS')
    assert all(prior['source']['sha256'][p] == h for p, h in source_hashes.items()), 'TASK-291 runtime differs'
    head = git('rev-parse', 'HEAD').decode().strip()
    assert all(git('show', head+':'+p) == b for p, b in sources.items()), 'Uncommitted runtime; freeze it before comparing'
    shutil.copytree(args.profile, out/'profile-evidence')
    write(out/'start-manifest.json', prior)
    for p, b in sources.items():
        path = out/'control'/p; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b)
    packed = bundle(sources); build = archive(packed)
    (out/'control.zip').write_bytes(build)
    write(out/'build.json', {'revision': head, 'source_sha256': source_hashes,
          'served_sha256': {p: sha(b) for p, b in packed.items()},
          'zip_sha256': sha(build), 'candidate_sha256': None,
          'build_kind': 'Frozen repair-branch runtime, deterministic bundle; not published baseline'})
    write(out/'decision.json', no_candidate_decision(hypothesis, sha(build)))
    (out/'candidate.diff').write_text('')
    reason = 'NOT_APPLICABLE: no supported candidate, no timing or visual experiment performed'
    write(out/'paired-metrics.json', {'status': reason, 'pairs': [], 'raw_timings': []})
    write(out/'visual-state.json', {'status': reason, 'comparisons': [],
          'screenshots': [], 'state_digests': [], 'resize': 'NOT_RUN',
          'pixel_equality': 'NOT_TESTED', 'state_equality': 'NOT_TESTED'})
    write(out/'environment.json', {'os': platform.platform(), 'browsers': 'NOT_LAUNCHED',
          'graphics': 'NOT_APPLICABLE', 'external_requests_allowed': 0,
          'native_android': 'UNVERIFIED', 'profile_environment': 'profile-evidence/environment.json'})
    audit_compare(out)


def audit_compare(out):
    from build_playgama import archive, bundle
    manifest_path = out/'manifest.json'
    if manifest_path.exists():
        manifest = read(manifest_path)
        assert manifest['task'] == 'TASK-294' and manifest['result'] == 'PASS' and manifest['exit_code'] == 0
        for p, h in manifest['evidence_sha256'].items():
            assert sha((out/p).read_bytes()) == h, p+' hash mismatch'
        lines = (out/'compare-command.log').read_text().splitlines()
        identity = json.loads(lines[0].removeprefix('EXECUTION '))
        for k, v in identity.items(): assert manifest[k] == v
        ending = json.loads(lines[-1].removeprefix('EXIT '))
        assert ending['execution_id'] == manifest['execution_id'] and ending['exit_code'] == 0
        assert manifest['started_utc'] <= ending['ended_utc'] <= manifest['ended_utc']
        assert 'PASS NO_SUPPORTED_CANDIDATE; no performance success; native Android UNVERIFIED' in lines
        assert manifest['harness_sha256'] == sha(Path(__file__).read_bytes()), 'Harness changed since execution'
    audit_profile(out/'profile-evidence')
    build = read(out/'build.json')
    sources = runtime_files(out/'control')
    assert {p: sha(b) for p, b in sources.items()} == build['source_sha256']
    assert runtime_files(ROOT) == sources, 'Runtime differs from pre-candidate control'
    assert all(git('show', build['revision']+':'+p) == b for p, b in sources.items())
    prior = read(out/'start-manifest.json')
    assert prior['verdict'].startswith('PASS')
    assert all(prior['source']['sha256'][p] == h for p, h in build['source_sha256'].items())
    packed = bundle(sources); data = archive(packed)
    assert {p: sha(b) for p, b in packed.items()} == build['served_sha256']
    assert data == (out/'control.zip').read_bytes() and sha(data) == build['zip_sha256']
    assert build['candidate_sha256'] is None
    expected = no_candidate_decision(read(out/'profile-evidence/hypothesis.json'), sha(data))
    assert read(out/'decision.json') == expected
    assert (out/'candidate.diff').read_bytes() == b''
    reason = 'NOT_APPLICABLE: no supported candidate, no timing or visual experiment performed'
    assert read(out/'paired-metrics.json') == {'status': reason, 'pairs': [], 'raw_timings': []}
    assert read(out/'visual-state.json') == {'status': reason, 'comparisons': [],
          'screenshots': [], 'state_digests': [], 'resize': 'NOT_RUN',
          'pixel_equality': 'NOT_TESTED', 'state_equality': 'NOT_TESTED'}
    environment = read(out/'environment.json')
    assert environment['browsers'] == 'NOT_LAUNCHED' and environment['external_requests_allowed'] == 0
    print('PASS runtime/control/source/build hashes match; TASK-291 fixes preserved; candidate.diff empty')
    print('PASS paired metrics and same-engine visual/state/resize checks explicitly NOT_APPLICABLE; no candidate tested')
    print('PASS NO_SUPPORTED_CANDIDATE; no performance success; native Android UNVERIFIED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('baseline'); b.add_argument('--revision',required=True); b.add_argument('--out',type=Path,required=True)
    b.add_argument('--capture-worker', action='store_true', help=argparse.SUPPRESS)
    p=sub.add_parser('profile'); p.add_argument('--baseline',type=Path,required=True); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--capture-worker', action='store_true', help=argparse.SUPPRESS)
    c=sub.add_parser('compare'); c.add_argument('--profile',type=Path,required=True)
    c.add_argument('--start-evidence',type=Path,required=True); c.add_argument('--out',type=Path,required=True)
    c.add_argument('--capture-worker', action='store_true', help=argparse.SUPPRESS)
    a=sub.add_parser('audit'); a.add_argument('--input',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='audit':
        (audit_compare if (args.input/'decision.json').exists() else audit_profile if (args.input/'profile.json').exists() else audit_data)(args.input); return
    if args.capture_worker:
        (compare if args.command=='compare' else profile if args.command=='profile' else baseline)(args); return
    # Never overwrite an earlier attempt, including an interrupted capture.
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('Output already contains evidence; preserve it and use an empty directory')
    args.out.mkdir(parents=True, exist_ok=True)
    command=[sys.executable,*sys.argv]
    worker=[sys.executable,str(Path(__file__).resolve()),args.command,
            *(['--profile',str(args.profile.resolve()), '--start-evidence',str(args.start_evidence.resolve())] if args.command=='compare' else ['--baseline',str(args.baseline.resolve())] if args.command=='profile' else ['--revision',args.revision]),
            '--out',str(args.out.resolve()),'--capture-worker']
    identity={'execution_id':str(uuid.uuid4()), 'command':command,
              'cwd':str(Path.cwd()), 'started_utc':utc(),
              'worker_command':worker, 'worker_cwd':str(ROOT),
              'source_head':git('rev-parse','HEAD').decode().strip(),
              'harness_sha256':sha(Path(__file__).read_bytes())}
    code=capture_command(worker,args.out/(args.command+'-command.log'),identity)
    write(args.out/'manifest.json',dict(identity, task='TASK-294' if args.command=='compare' else 'TASK-293' if args.command=='profile' else 'TASK-292',
        result='PASS' if code==0 else 'FAIL', ended_utc=utc(), exit_code=code,
        source_build='build.json', environment='environment.json',
        scope='TASK-294; prerequisites TASK-291, TASK-293; completion != performance success' if args.command=='compare' else 'TASK-293; prerequisites TASK-292, TASK-287; experiment completion != performance success' if args.command=='profile' else 'TASK-292; prerequisite TASK-287; experiment completion != performance success',
        evidence_sha256={str(p.relative_to(args.out)):sha(p.read_bytes())
            for p in sorted(args.out.rglob('*')) if p.is_file()}))
    raise SystemExit(code)


if __name__=='__main__':
    main()
