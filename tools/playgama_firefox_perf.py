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
import subprocess
import sys
from threading import Thread
import traceback

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
PROBE = r'''({mode, inputs, seed}) => {
    const state = () => ({menu: menu.visible, pause: menu.gamePaused,
        death: continueOffer.visible, ad: adOpen || interstitialPending,
        host: hostPaused, portrait: isViewRotated(), hidden: document.hidden});
    const active = s => !Object.values(s).some(Boolean);
    const p = window.perfReceipt = {frames: [], inputs: [], transitions: [],
        activeMs: 0, done: false, accepted_input_ms: null, first_active_frame_ms: null};
    let previous = null, nextInput = 0, lastRestart = -Infinity, lastState = '';
    function dispatch(type, x, y) {
        document.dispatchEvent(new MouseEvent(type, {bubbles:true, clientX:x, clientY:y}));
    }
    function button(b) {
        const r = canvas.getBoundingClientRect();
        const x = r.x + (b.x + b.width/2) * r.width/width;
        const y = r.y + (b.y + b.height/2) * r.height/height;
        dispatch('mousedown', x, y); dispatch('mouseup', x, y);
    }
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
    // Reset immediately before the same start input so menu frame counts do not
    // consume a different portion of the seeded gameplay random sequence.
    let a = seed >>> 0;
    Math.random = () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    button(menu[mode+'VersionButton'].background);
    if (!menu.visible && version === mode) p.accepted_input_ms = performance.now();
}'''

LAYOUT = '''() => {
 const c = document.getElementById('canvas');
 const gl = document.createElement('canvas').getContext('webgl');
 const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
 return {viewport:[innerWidth,innerHeight], dpr:devicePixelRatio,
 backing:[c.width,c.height], css:[c.clientWidth,c.clientHeight],
 logical:[width,height], portrait:isViewRotated(), menu:menu.visible,
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
    runs, startup, layouts = [], [], []
    environment = {'os':platform.platform(), 'os_release':Path('/etc/os-release').read_text(),
                   'playwright':importlib.metadata.version('playwright'), 'browsers':{},
                   'native_android':'UNVERIFIED', 'execution':'headless desktop engines; mobile sizes are emulation'}
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
                        data['portrait_start_blocked'] = page.evaluate('menu.visible && isViewRotated()')
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('baseline'); b.add_argument('--revision',required=True); b.add_argument('--out',type=Path,required=True)
    a=sub.add_parser('audit'); a.add_argument('--input',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='audit':
        audit_data(args.input); return
    started=utc(); code=1
    try:
        baseline(args); code=0
    except Exception:
        traceback.print_exc()
    finally:
        if args.out.exists() and not (args.out/'manifest.json').exists():
            write(args.out/'manifest.json',{'task':'TASK-292','result':'PASS' if code==0 else 'FAIL',
                'command':[sys.executable,*sys.argv], 'cwd':str(Path.cwd()),
                'started_utc':started,'ended_utc':utc(),'exit_code':code,
                'source_head':git('rev-parse','HEAD').decode().strip(),
                'harness_sha256':sha(Path(__file__).read_bytes()),
                'source_build':'build.json','environment':'environment.json',
                'scope':'TASK-292; prerequisite TASK-287; experiment completion != performance success',
                'evidence_sha256':{str(p.relative_to(args.out)):sha(p.read_bytes())
                    for p in sorted(args.out.rglob('*')) if p.is_file()}})
    raise SystemExit(code)


if __name__=='__main__':
    main()
