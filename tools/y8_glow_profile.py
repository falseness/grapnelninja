"""Offline, fixed-tick A/B diagnostic for the TASK-255 glow combination.

Only BloomRenderer.composite differs between variants. CPU profiles include
instrumentation; per-frame draw cost is CPU submission, not display FPS or GPU
completion. Fixed simulation ticks prevent frame-rate-dependent scene changes.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import argparse
import collections
import difflib
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import tarfile

import numpy as np
from PIL import Image
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT
from render_snapshot import CLOCK_SCRIPT, SETUP_SCRIPT, boot_frozen, input_script, png_bytes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/TASK-255'
DIRECT_REV = '81ba90e^'
COMBINED_REV = '81ba90e'
SDK = 'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js'
LAYERS = ['drawBackgroundLayer', 'drawLightsLayer', 'drawBehindForegroundParticlesLayer',
          'drawPlayerTrailLayer', 'drawWorldLayer', 'drawParticlesAndTrailsLayer',
          'drawBloomLayer', 'drawPlayerGlowLayer', 'drawColorGradeLayer',
          'drawPlayerLayer', 'drawUILayer', 'drawFpsCounterLayer']


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name, data):
    (OUT/name).write_text(json.dumps(data, indent=2)+'\n')


def composite(source):
    start = source.index('    composite(player, exclusionRadiusRatio')
    end = source.index('\n}\n', start)
    return source[start:end]


def capture():
    started = datetime.now(timezone.utc).isoformat()
    for d in ['traces', 'visual-comparison', 'sources']:
        (OUT/d).mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    archive = subprocess.check_output(['git', 'archive', '--format=tar', revision], cwd=ROOT)
    (OUT/'source.tar').write_bytes(archive)
    original = subprocess.check_output(['git', 'show', revision+':render/effects.js'], cwd=ROOT).decode()
    methods = {name: composite(subprocess.check_output(['git', 'show', rev+':render/effects.js'], cwd=ROOT).decode())
               for name, rev in [('direct', DIRECT_REV), ('combined', COMBINED_REV)]}
    identity = {'base_commit': revision, 'source_archive': 'source.tar', 'archive_sha256': sha(OUT/'source.tar'),
                'method_revisions': {'direct': DIRECT_REV, 'combined': COMBINED_REV}, 'variants': {}}
    for name, method in methods.items():
        target = OUT/'sources'/name
        target.mkdir(exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(target, filter='data')
        effects = original.replace(composite(original), method)
        (target/'render/effects.js').write_text(effects)
        identity['variants'][name] = {'effects_sha256': sha(target/'render/effects.js'),
            'runtime_hashes': {str(p.relative_to(target)): sha(p) for p in sorted(target.rglob('*'))
                               if p.is_file() and p.suffix in ('.js', '.css', '.html')}}
    a=(OUT/'sources/direct/render/effects.js').read_text().splitlines(True)
    b=(OUT/'sources/combined/render/effects.js').read_text().splitlines(True)
    (OUT/'source-diff.patch').write_text(''.join(difflib.unified_diff(a,b,fromfile='direct',tofile='combined')))
    env = {'os': platform.platform(), 'python': platform.python_version(), 'viewport': [780,390],
           'DPR': 2, 'density': 2, 'CPU_throttle': 1, 'seed': 1, 'warmup_ticks': 30,
           'measured_ticks': [31,150], 'clock': 'fixed 60Hz simulation; real clock for CPU timings',
           'input': input_script(ticks=150, width=780, height=390),
           'limitations': 'Headless shared host; no physical phone or interactive DevTools; CPU submission cost is not FPS or GPU raster time.'}
    runs=[]
    with ExitStack() as stack, (OUT/'network.log').open('w') as net:
        url,browser=start_browser_test(OUT/'sources', stack.callback)
        env['browser']=browser.version
        env['gpu']=browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu']
        for mode in ['bad','classic']:
            for rep in range(3):
                for variant in (['direct','combined'] if rep%2==0 else ['combined','direct']):
                    name=f'{mode}-{rep+1}-{variant}'
                    c=browser.new_context(viewport={'width':780,'height':390}, device_scale_factor=2,
                                          service_workers='block')
                    def route(r):
                        u=r.request.url
                        if u==SDK:
                            net.write(name+' FAKE_SDK\n')
                            r.fulfill(content_type='text/javascript', body=(ROOT/'tools/fixtures/fake-y8-sdk.js').read_text())
                        elif u.startswith(url): r.continue_()
                        else: net.write(name+' BLOCKED '+u+'\n'); r.abort()
                    c.route('**/*',route)
                    c.add_init_script(SEED_SCRIPT%1+'\nwindow.realNow=performance.now.bind(performance);\n'+CLOCK_SCRIPT)
                    p=c.new_page(); errors=[]
                    p.on('pageerror',lambda e: errors.append(str(e)))
                    p.goto(url+variant+'/index.html',wait_until='load');boot_frozen(p)
                    p.evaluate(SETUP_SCRIPT,[env['input'],False])
                    p.evaluate("RENDER_BUDGET.densityLimit=2; RENDER_BUDGET.observe=()=>false")
                    p.evaluate('(mode)=>startGame(mode)',mode)
                    p.evaluate('()=>{while(__snap.tick<30)__snap.step()}')
                    p.evaluate('''layers=>{
                        window.samples=[];window.currentSample=null;
                        for(const name of layers){const fn=window[name];window[name]=function(...args){
                            const t=realNow();try{return fn.apply(this,args)}finally{
                                if(currentSample)currentSample.layers[name]=(currentSample.layers[name]||0)+realNow()-t;
                            }};}
                        const fn=BloomRenderer.prototype.composite;
                        BloomRenderer.prototype.composite=function(...args){const t=realNow();
                            try{return fn.apply(this,args)}finally{if(currentSample)currentSample.composite+=realNow()-t;}};
                        window.nextSample=()=>{currentSample={tick:__snap.tick+1,layers:{},composite:0};
                            const t=realNow();__snap.step();currentSample.frame=realNow()-t;
                            currentSample.canvas=[canvas.width,canvas.height];
                            currentSample.state=[ninja.x,ninja.y,screen.x,screen.y,floors.length,ninja.track.length];
                            samples.push(currentSample);currentSample=null;};
                    }''',LAYERS)
                    cd=c.new_cdp_session(p);cd.send('Profiler.enable');cd.send('Profiler.start')
                    for tick in [60,150]:
                        p.evaluate('target=>{while(__snap.tick<target)nextSample()}',tick)
                        if rep==0:
                            (OUT/f'visual-comparison/{mode}-{variant}-{tick}.png').write_bytes(png_bytes(p.evaluate('()=>__snap.capture()')))
                    prof=cd.send('Profiler.stop')['profile']; save('traces/'+name+'.cpuprofile',prof)
                    raw=p.evaluate('samples'); save('traces/'+name+'.json',raw)
                    assert not errors, errors
                    assert all(f['canvas']==[1560,780] for f in raw)
                    runs.append({'id':name,'mode':mode,'rep':rep+1,'variant':variant,'frames':len(raw),
                                 'mean_frame_ms':float(np.mean([f['frame'] for f in raw])),
                                 'mean_composite_ms':float(np.mean([f['composite'] for f in raw])),
                                 'layers_ms':{k:float(np.mean([f['layers'].get(k,0) for f in raw])) for k in LAYERS}})
                    net.write(name+' PASS offline fake SDK; equal canvas 1560x780\n');net.flush()
                    print('PASS',name,runs[-1],flush=True);c.close()
    comparisons=[]
    for mode in ['bad','classic']:
        for tick in [60,150]:
            a=np.array(Image.open(OUT/f'visual-comparison/{mode}-direct-{tick}.png').convert('RGB')).astype(int)
            b=np.array(Image.open(OUT/f'visual-comparison/{mode}-combined-{tick}.png').convert('RGB')).astype(int)
            delta=np.abs(a-b)
            comparisons.append({'mode':mode,'tick':tick,'different_pixels':int(np.any(delta,axis=2).sum()),
                                'max_channel_difference':int(delta.max()),'mean_absolute_difference':float(delta.mean())})
            Image.fromarray(np.minimum(delta*8,255).astype('uint8')).save(OUT/f'visual-comparison/{mode}-diff-{tick}.png')
    save('profile-before-after.json',{'identity':identity,'environment':env,'runs':runs,'visual_comparison':comparisons,
        'capture': {'command': 'python3 tools/y8_glow_profile.py capture', 'utc_start': started,
                    'utc_end': datetime.now(timezone.utc).isoformat(), 'exit_code': 0},
        'comparison':'direct reference vs combined optimization; only composite method differs',
        'quality':'Equal density and simulation; no reduced-resolution FPS claim.'})
    print('PASS capture complete',comparisons,flush=True)


def audit():
    report=json.loads((OUT/'profile-before-after.json').read_text())
    assert sha(OUT/'source.tar')==report['identity']['archive_sha256']
    assert len(report['runs'])==12
    profiles=[]
    for row in report['runs']:
        raw=json.loads((OUT/('traces/'+row['id']+'.json')).read_text())
        assert len(raw)==120 and [f['tick'] for f in raw]==list(range(31,151))
        assert all(f['canvas']==[1560,780] for f in raw)
        assert row['mean_frame_ms']==float(np.mean([f['frame'] for f in raw]))
        assert row['mean_composite_ms']==float(np.mean([f['composite'] for f in raw]))
        assert row['layers_ms']=={k:float(np.mean([f['layers'].get(k,0) for f in raw])) for k in LAYERS}
        profile=json.loads((OUT/('traces/'+row['id']+'.cpuprofile')).read_text())
        assert len(profile['samples'])==len(profile['timeDeltas'])>0
        nodes={n['id']:n for n in profile['nodes']}; counts=collections.Counter()
        for node,dt in zip(profile['samples'],profile['timeDeltas']):
            counts[nodes[node]['callFrame']['functionName']]+=dt
        profiles.append({'id':row['id'],'top_self_sample_microseconds':counts.most_common(12)})
        print('PASS traces/'+row['id']+'.json and .cpuprofile: 120 equal-density frames; frame/composite/all layers recomputed; CPU samples present')
    changes=[]
    for mode in ['bad','classic']:
        for rep in range(1,4):
            a=json.loads((OUT/f'traces/{mode}-{rep}-direct.json').read_text())
            b=json.loads((OUT/f'traces/{mode}-{rep}-combined.json').read_text())
            assert [f['state'] for f in a]==[f['state'] for f in b]
        avg=lambda variant,key: float(np.mean([r[key] for r in report['runs'] if r['mode']==mode and r['variant']==variant]))
        before,after=avg('combined','mean_frame_ms'),avg('direct','mean_frame_ms')
        changes.append({'mode':mode,'before_combined_ms':before,'after_direct_ms':after,
                        'change_ms':after-before,'change_percent':(after/before-1)*100,
                        'before_composite_ms':avg('combined','mean_composite_ms'),
                        'after_composite_ms':avg('direct','mean_composite_ms')})
        print(f'PASS matched {mode}: combined={before:.4f} ms direct={after:.4f} ms delta={after-before:.4f} ms CPU submission only')
    for pair in report['visual_comparison']:
        mode,tick=pair['mode'],pair['tick']
        paths=[OUT/f'visual-comparison/{mode}-{v}-{tick}.png' for v in ['direct','combined']]
        a,b=[np.array(Image.open(p).convert('RGB')).astype(int) for p in paths]
        assert a.shape==b.shape==(780,1560,3)
        delta=np.abs(a-b)
        assert pair['different_pixels']==int(np.any(delta,axis=2).sum())
        assert pair['max_channel_difference']==int(delta.max())
        print(f'PASS visual-comparison/{mode}-{{direct,combined}}-{tick}.png: paired seed=1 tick={tick}; different_pixels={pair["different_pixels"]} max_channel_difference={pair["max_channel_difference"]}')
    for path,digest in report['identity']['variants']['direct']['runtime_hashes'].items():
        assert sha(ROOT/path)==digest,path
    print('PASS source-diff.patch: final runtime equals captured direct variant; only BloomRenderer.composite differs from combined')
    diagnosis={'result':'Reject combined-buffer optimization: higher measured CPU submission cost and changed additive pixels; restore direct compositing.',
               'changes':changes,'cpu_profiles':profiles,
               'dominant_cost':'Combined: ambient/player glow layers and drawImage CPU samples; direct: lighting is the largest measured layer. Composite timing is nested within layers, not additional cost.',
               'scope':'No new lighting optimization in this slice. Historical combine hypothesis ruled out on recorded backend; physical GPU result remains unproven.',
               'limitations':'Fixed simulation CPU submission, not presentation FPS. Profiler includes screenshot serialization/idle between batches, excluded from per-frame timers. Headless software backend and host noise limit generalization. Overall FPS remains unresolved for final audit; owner physical checks unavailable.'}
    save('diagnosis.json',diagnosis)
    print('PASS profile-before-after.json: matched settings, source delta, layer costs and recomputed frame changes; unresolved overall FPS tracked in diagnosis.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['capture','audit'])
    args=parser.parse_args()
    capture() if args.action=='capture' else audit()
