"""Offline TASK-254 baseline. Run capture, then audit saved evidence independently.

Headless Chromium cannot reproduce an interactive DevTools or physical GPU case.
Density is pinned at DPR 2; the candidate's adaptive fallback is disabled only
inside the benchmark page. The reported ZIP is also the original Y8 comparison
when every archive member is byte-identical to its recorded Git revision.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import tarfile
import time
import zipfile

from browser_test_support import start_browser_test, wait_for_boot
from perf_mobile import SEED_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/TASK-254'
ARCHIVE = ROOT / 'artifacts/TASK-098/grapnelninja-y8.zip'
EXPECTED = 'a9aed755a55e799a621adb31e1da518d573d5168391971d07948aefb8ac20c91'
SDK = 'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def stats(values):
    ordered = sorted(values)
    return {f'p{p}': ordered[min(len(ordered)-1, int(len(ordered)*p/100))]
            for p in (50, 95, 99)}


INSTRUMENT = '''() => {
    // Pin before startGame creates the first active frame.
    if (typeof RENDER_BUDGET !== 'undefined') {
        RENDER_BUDGET.densityLimit = 2;
        RENDER_BUDGET.observe = () => false;
    }
    const state = () => ({menu:!!menu.visible, paused:!!menu.gamePaused,
        offer:typeof continueOffer !== 'undefined' && !!continueOffer.visible,
        hidden:document.hidden});
    const active = s => !s.menu && !s.paused && !s.offer && !s.hidden;
    window.measure = {frames:[], excluded:[], activeMs:0, done:false,
        input:'startGame(bad) once; no subsequent pointer/key/touch input', start:performance.now()};
    let frame=null, previous=null;
    for (const name of ['physics','draw','drawBackgroundLayer','drawLightsLayer',
        'drawWorldLayer','drawPlayerTrailLayer','drawParticlesAndTrailsLayer','drawUILayer']) {
        const original = window[name];
        if (typeof original !== 'function') continue;
        window[name] = function(...args) {
            const t=performance.now();
            try { return original.apply(this,args); }
            finally { if(frame) (frame.stages[name] ||= []).push(performance.now()-t); }
        };
    }
    const original=window.gameLoop;
    window.gameLoop=function(t) {
        const s=state();
        if(!measure.done) {
            if(active(s)) {
                const dt=previous===null ? null : t-previous;
                frame={t, dt, state:s, canvas:[canvas.width,canvas.height], stages:{}};
                measure.frames.push(frame);
                if(dt!==null) measure.activeMs+=dt;
                previous=t;
            } else {measure.excluded.push({t,state:s}); previous=null;}
        }
        try {return original.call(this,t);}
        finally {
            frame=null;
            if(measure.activeMs>=30000) {measure.done=true; measure.end=performance.now();}
        }
    };
}'''


def capture():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'traces').mkdir(exist_ok=True)
    commands = []

    def command(argv):
        result = subprocess.run(argv, cwd=ROOT, capture_output=True)
        commands.append({'argv': argv, 'utc': datetime.now(timezone.utc).isoformat(),
                         'exit_code': result.returncode,
                         'stdout': result.stdout.decode(errors='replace') if argv[1] != 'archive' else '<source.tar>',
                         'stderr': result.stderr.decode(errors='replace')})
        result.check_returncode()
        return result.stdout

    revision = command(['git', 'rev-parse', 'HEAD']).decode().strip()
    original = command(['git', 'rev-parse', 'b588d69']).decode().strip()
    assert sha(ARCHIVE) == EXPECTED
    source = command(['git', 'archive', '--format=tar', revision])
    (OUT / 'source.tar').write_bytes(source)
    candidate = OUT / 'candidate'
    candidate.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(source)) as tar:
        tar.extractall(candidate, filter='data')
    old = OUT / 'reported'
    old.mkdir(exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as z:
        members = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
        for name, digest in members.items():
            data = command(['git', 'show', original + ':' + name])
            assert hashlib.sha256(data).hexdigest() == digest, name
        z.extractall(old)
    # Avoid embedding source contents in the command ledger.
    for c in commands:
        if c['argv'][1] == 'show':
            c['stdout'] = 'SHA256=' + hashlib.sha256(c['stdout'].encode()).hexdigest()
    identity = {'candidate_commit': revision, 'candidate_tar_sha256': sha(OUT/'source.tar'),
                'original_y8_commit': original, 'reported_archive': str(ARCHIVE.relative_to(ROOT)),
                'archive_sha256': EXPECTED, 'archive_members': members,
                'original_alias': 'PASS all 28 reported ZIP files byte-identical to original Y8; one shared baseline'}
    environment = {'os': platform.platform(), 'python': platform.python_version(),
                   'display': 'headless; interactive DevTools unavailable', 'browser_args': ['--no-sandbox'],
                   'measurement': 'instrumented gameLoop trace; no Chrome timeline profiler overhead'}
    cases, runs = [], []
    network = (OUT/'network.log').open('w')
    started = datetime.now(timezone.utc).isoformat()
    with ExitStack() as stack:
        url, browser = start_browser_test(OUT, stack.callback)
        environment['browser'] = browser.version
        environment['gpu'] = browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu']
        for mobile in (False, True):
            for tree in ('reported', 'candidate'):
                case = {'id': f'{tree}-emulation-{mobile}', 'source': identity,
                        'tree': tree, 'viewport': [780,390], 'device_emulation': mobile,
                        'DPR': 2, 'cpu_throttle': 1, 'seed': 1, 'devtools': 'closed/headless',
                        'density': 'pinned 2; adaptive observe disabled in candidate only',
                        'input': 'startGame(bad) once; no subsequent pointer/key/touch input',
                        'warmup': 'boot/menu excluded; no additional active warmup',
                        'duration': '>=30000ms contiguous active frame intervals; interrupted intervals excluded'}
                cases.append(case)
                for rep in (1,2,3):
                    runid = case['id'] + '-' + str(rep)
                    c = browser.new_context(viewport={'width':780,'height':390},
                          device_scale_factor=2, is_mobile=mobile, has_touch=mobile, service_workers='block')
                    errors=[]
                    def route(r):
                        u=r.request.url
                        if u == SDK:
                            network.write(f'{runid} FAKE_SDK {u}\n')
                            r.fulfill(content_type='text/javascript', body=(ROOT/'tools/fixtures/fake-y8-sdk.js').read_text())
                        elif u.startswith(url):
                            network.write(f'{runid} LOCAL {u}\n'); r.continue_()
                        else:
                            network.write(f'{runid} BLOCKED {u}\n'); r.abort()
                        network.flush()
                    c.route('**/*', route)
                    c.add_init_script(SEED_SCRIPT % 1)
                    p=c.new_page(); p.on('pageerror', lambda e: errors.append(str(e)))
                    responses=[]
                    p.on('response', lambda r: responses.append(r.url))
                    c.new_cdp_session(p).send('Emulation.setCPUThrottlingRate', {'rate':1})
                    p.goto(url+tree+'/index.html', wait_until='domcontentloaded'); wait_for_boot(p)
                    p.evaluate(INSTRUMENT); p.evaluate("startGame('bad')")
                    p.wait_for_function('measure.done', timeout=180000)
                    raw=p.evaluate('measure')
                    dimensions=p.evaluate('''() => {const r=canvas.getBoundingClientRect(); return {
                        canvas:[canvas.width,canvas.height],css:[r.width,r.height],dpr:devicePixelRatio,
                        viewport:[innerWidth,innerHeight],sdk:PLATFORM.environment};}''')
                    raw.update({'id':runid, 'case':case, 'dimensions':dimensions,'errors':errors})
                    trace='traces/'+runid+'.json'; save(trace,raw)
                    intervals=[f['dt'] for f in raw['frames'] if f['dt'] is not None]
                    stages={}
                    for f in raw['frames']:
                        for k,v in f['stages'].items(): stages.setdefault(k,[]).extend(v)
                    row={'id':runid, 'case':case['id'], 'rep':rep,'trace':trace,
                         'fps':len(intervals)*1000/sum(intervals),'frame_ms':stats(intervals),
                         'active_ms':sum(intervals),'stage_ms':{k:stats(v) for k,v in stages.items()},
                         'dimensions':dimensions,'errors':errors,'excluded_frames':len(raw['excluded'])}
                    runs.append(row); save('baseline-runs.json', runs)
                    assert not errors, errors
                    assert dimensions['sdk']=='y8', dimensions
                    assert all(u.startswith(url) or u==SDK for u in responses), responses
                    network.write(f'{runid} PASS production_responses=0 fake_sdk=1\n'); network.flush()
                    print('PASS',runid,round(row['fps'],2),dimensions,flush=True)
                    c.close()
        save('baseline.json', {'identity':identity,'environment':environment,'cases':cases,
            'actual_dimensions_by_case': {case['id']: [r['dimensions'] for r in runs if r['case']==case['id']] for case in cases},
            'unsupported': ['DevTools open docked: unsupported without interactive desktop',
                'DevTools open undocked: unsupported without interactive desktop',
                'physical phone/GPU and user 60-to-10 FPS reproduction: unavailable'],
            'viewport_control':'equal 780x390 viewport, DPR2, CPU throttle1 for every available case'})
    network.close()
    assert sha(ARCHIVE)==EXPECTED
    save('diagnosis.json', {
        'result':'Reproduction unavailable for reported interactive DevTools 60-to-10 FPS regression; no fix claimed.',
        'source_effects': {case['id']:[round(r['fps'],3) for r in runs if r['case']==case['id']] for case in cases},
        'viewport':'Held equal; docked viewport changes not measured.',
        'emulation':'Off/on measured at equal viewport and DPR2; touch/mobile flags are the only emulation differences.',
        'gpu':'Single recorded Chromium GPU backend; no hardware/backend causal comparison available.',
        'quality':'Pinned identical canvas dimensions audited per frame. Previous adaptive-density results are superseded; reduced resolution is not equal-quality improvement.',
        'next_hotspot':'Profile drawLightsLayer and draw/world rendering on the user hardware with interactive DevTools; instrumented stage times here identify candidates, not raster/GPU causality.',
        'limitations':'Fixed seed and no-action input do not guarantee identical world state across sources or frame rates. Shared-host noise and instrumentation affect absolute FPS. Legacy probe/isolate/benchmark artifacts are not evidence for this handoff.'})
    save('manifest.json', {'identity':identity,'environment':environment,'commands':commands,
        'capture':{'argv':['python3','tools/y8_fps_baseline.py','capture'], 'utc':started,'exit_code':0},
        'runner_sha256':sha(Path(__file__)), 'fake_sdk_sha256':sha(ROOT/'tools/fixtures/fake-y8-sdk.js'),
        'evidence_paths':['baseline.json','baseline-runs.json','diagnosis.json','network.log','traces/','source.tar'],
        'sha256':{str(p.relative_to(OUT)):sha(p) for p in [OUT/'baseline.json',OUT/'baseline-runs.json',OUT/'diagnosis.json',OUT/'network.log',OUT/'source.tar',*sorted((OUT/'traces').glob('*.json'))]}})


def audit():
    m=json.loads((OUT/'manifest.json').read_text())
    for name,digest in m['sha256'].items():
        assert sha(OUT/name)==digest,name
        print('PASS SHA256', name, digest)
    assert sha(ARCHIVE)==EXPECTED
    assert sha(Path(__file__))==m['runner_sha256']
    baseline=json.loads((OUT/'baseline.json').read_text())
    runs=json.loads((OUT/'baseline-runs.json').read_text())
    assert len(runs)==12
    assert len(baseline['actual_dimensions_by_case'])==4
    sizes=[]
    for case in baseline['cases']:
        rows=[r for r in runs if r['case']==case['id']]
        assert [r['rep'] for r in rows]==[1,2,3]
        for r in rows:
            raw=json.loads((OUT/r['trace']).read_text())
            dt=[f['dt'] for f in raw['frames'] if f['dt'] is not None]
            assert not raw['errors'] and not r['errors']
            assert sum(dt)>=30000 and abs(sum(dt)-r['active_ms'])<1e-6
            assert stats(dt)==r['frame_ms']
            assert abs(len(dt)*1000/sum(dt)-r['fps'])<1e-9
            assert raw['case']==case
            assert all(not any(f['state'].values()) for f in raw['frames'])
            assert all(f['canvas']==r['dimensions']['canvas'] for f in raw['frames'])
            assert all(f['dt'] is None or f['dt']>0 for f in raw['frames'])
            stage={}
            for f in raw['frames']:
                for k,v in f['stages'].items(): stage.setdefault(k,[]).extend(v)
            assert {k:stats(v) for k,v in stage.items()}==r['stage_ms']
            assert 'draw' in stage and 'physics' in stage
            sizes.append(r['dimensions'])
            print('PASS trace',r['trace'],'active_ms='+str(round(sum(dt),3)), 'FPS/percentiles/stages recomputed; menu/background excluded')
    assert all(s==sizes[0] for s in sizes),sizes
    assert sizes[0]['canvas']==[1560,780] and sizes[0]['dpr']==2
    network=(OUT/'network.log').read_text()
    assert network.count('PASS production_responses=0 fake_sdk=1')==12
    assert len(baseline['unsupported'])==3
    print('PASS baseline.json: archive/source/browser/OS/GPU/dimensions/DPR/viewport/throttle/seed/input; unsupported DevTools/hardware explicit')
    print('PASS baseline-runs.json and traces/: 12 sequential runs; 3 x 30-second active runs per source/emulation case; equal canvas 1560x780')
    print('PASS network.log: production_responses=0 fake_sdk=1 in all 12 runs')
    diagnosis=json.loads((OUT/'diagnosis.json').read_text())
    assert all(k in diagnosis for k in ('viewport','emulation','gpu','source_effects','next_hotspot'))
    assert 'no fix claimed' in diagnosis['result']
    print('PASS diagnosis.json: viewport/emulation/GPU/source effects separated; reproduction unavailable; no fix claimed')
    assert m['capture']['exit_code']==0 and all(c['exit_code']==0 for c in m['commands'])
    print('PASS manifest.json: commands/exit codes/UTC/identity/environment/evidence hashes verified')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['capture','audit'])
    args=parser.parse_args()
    capture() if args.action=='capture' else audit()
