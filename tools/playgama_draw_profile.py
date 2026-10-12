"""Bounded current-runtime Firefox AB/BA timer-only diagnostic (not an FPS gate)."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from threading import Thread
import time

from playwright.sync_api import sync_playwright
from playgama_render_compare import (TIMING_PROBE, FIXTURE, hashes, summarize,
                                    SDK, SEED, INPUT, LAYOUT)
from playgama_firefox_perf import QuietHandler, SEED_SCRIPT, sha, utc, write, read, git

TIMERS = r'''() => {
 window.drawProfile = [];
 let current = null;
 const add = (name, elapsed) => {
   if (!current) return;
   const row = current.costs[name] ||= {ms:0, calls:0};
   row.ms += elapsed; row.calls++;
 };
 const wrap = (obj, key, name) => {
   const original = obj[key];
   if (typeof original !== 'function') throw Error('Missing timer target '+name);
   obj[key] = function(...args) {
     const start = performance.now();
     try {return original.apply(this,args)}
     finally {add(name,performance.now()-start)}
   };
 };
 for (const key of Object.keys(window).filter(k=>/^draw.*Layer$/.test(k)))
   wrap(window,key,key);
 for (const key of ['draw','paint','clearAll','drawBaseGradient','drawCrystalLayer',
                    'drawHaze','drawNearLayer','drawVignette'])
   wrap(visualEffects.background,key,'background.'+key);
 for (const key of ['drawScreen','resize','renderGlow','blur','composite'])
   wrap(visualEffects.ambientGlow,key,'ambient.'+key);
 for (const key of ['update','drawAmbientMotes','drawBehindForeground'])
   wrap(visualEffects.particles,key,'particles.'+key);
 // Count/time real operations only. No readback, flush, replacement drawing,
 // altered dimensions or quality. Costs are nested and must not be summed.
 for (const key of ['fillRect','clearRect','drawImage']) {
   const original = CanvasRenderingContext2D.prototype[key];
   CanvasRenderingContext2D.prototype[key] = function(...args) {
     const ambient = visualEffects.ambientGlow;
     const name = this===ambient.ctx ? 'main.'+key :
       ambient.levels.some(l=>l.ctx===this) ? 'ambient.surface.'+key : null;
     if (!current || !name) return original.apply(this,args);
     const start=performance.now();
     try {return original.apply(this,args)} finally {add(name,performance.now()-start)}
   };
 }
 for (const key of ['width','height']) {
   const d=Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype,key);
   Object.defineProperty(HTMLCanvasElement.prototype,key,{...d,set(value) {
     const player=visualEffects.playerGlow.levels.some(l=>l.canvas===this);
     const start=performance.now();
     try {return d.set.call(this,value)}
     finally {if(player) add('player.surface.resize.'+key,performance.now()-start)}
   }});
 }
 const original=draw;
 draw=function(...args) {
   const row={start:performance.now(),costs:{},frameId:drawFrameId+1};
   current=row;
   try {return original.apply(this,args)}
   finally {
     row.end=performance.now(); row.ms=row.end-row.start;
     row.playerResizes=visualEffects.playerGlow.prototypeResizes||0;
     window.drawProfile.push(row); current=null;
   }
 };
}'''


def summarize_profile(raw):
    metrics = summarize(raw)
    active = 0
    selected = []
    for a, b in zip(raw['frames'], raw['frames'][1:]):
        if not any(a['after'].values()) and not any(b['before'].values()):
            if active >= 5000:
                # Drawing in previous callback contributes to this RAF interval.
                rows = a.get('draws', [])
                selected.append({'raf_ms': b['t']-a['t'],
                                 'draw_ms': sum(r['ms'] for r in rows), 'draws': rows})
            active += b['t']-a['t']
    result = {'fps': 1000/metrics['mean_ms'], 'metrics': metrics}
    if raw['arm'] == 'B':
        assert selected and all(r['draws'] for r in selected), 'missing timed draw'
        names = sorted({k for r in selected for d in r['draws'] for k in d['costs']})
        result.update(draw_mean_ms=statistics.mean(r['draw_ms'] for r in selected),
            untimed_mean_ms=statistics.mean(r['raf_ms']-r['draw_ms'] for r in selected),
            costs={k: {'mean_ms': sum(d['costs'].get(k,{}).get('ms',0)
                                     for r in selected for d in r['draws'])/len(selected),
                       'calls': sum(d['costs'].get(k,{}).get('calls',0)
                                    for r in selected for d in r['draws'])} for k in names})
    return result


def worker(args):
    root=args.out/'snapshot'
    key=f'{args.index}-{args.arm}'
    errors=[]; network=[]
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(root)))
    Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    def route(r):
        url=r.request.url
        action='LOCAL' if url.startswith(origin+'/') else 'SDK_STUB' if url==SDK else 'BLOCKED'
        network.append({'url':url,'action':action})
        if action=='LOCAL':r.continue_()
        elif action=='SDK_STUB':r.fulfill(content_type='application/javascript',body=FIXTURE)
        else:r.abort()
    try:
        with sync_playwright() as pw:
            browser=pw.firefox.launch(headless=True)
            env={'os':platform.platform(),'browser':browser.version,
                 'executable':pw.firefox.executable_path,
                 'executable_sha256':sha(Path(pw.firefox.executable_path).read_bytes()),
                 'launch':{'headless':True,'firefox_user_prefs':{}},
                 'canvas2d_backend':'UNKNOWN; WebGL renderer does not identify Canvas2D backend',
                 'cpu_throttling':False}
            write(args.out/(key+'-environment.json'),env)
            context=browser.new_context(viewport={'width':844,'height':390},device_scale_factor=2,
                                       has_touch=True,locale='en-US',service_workers='block')
            context.route('**/*',route)
            context.add_init_script(SEED_SCRIPT % SEED)
            page=context.new_page()
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.goto(origin+'/index.html')
            page.wait_for_function('bootComplete && document.getElementById("loading").hidden')
            layout=page.evaluate(LAYOUT)
            env['layout']=layout
            env['context_attributes']=page.evaluate('ctx.getContextAttributes ? ctx.getContextAttributes() : null')
            write(args.out/(key+'-environment.json'),env)
            probe=TIMING_PROBE
            if args.arm=='B':
                page.evaluate(TIMERS)
                probe=probe.replace('original(t);','const firstDraw=drawProfile.length; original(t);').replace(
                    'p.frames.push(row);','row.draws=drawProfile.slice(firstDraw); p.frames.push(row);')
            page.evaluate(probe,{'mode':'classic','inputs':INPUT,'seed':SEED})
            while True:
                page.wait_for_timeout(200)
                raw=page.evaluate('perfReceipt')
                raw.update(arm=args.arm,layout=layout,seed=SEED,input_policy=INPUT,source_sha256=hashes(root))
                # Preserve partial traces even if an external arm deadline kills us.
                write(args.out/(key+'-raw.json'),raw)
                try: result=summarize_profile(raw)
                except AssertionError: continue
                if result['metrics']['measured_ms']>=30000:break
            assert layout['backing']==[1688,780] and layout['dpr']==2
            assert not errors,errors
            write(args.out/(key+'-result.json'),result)
            print(f'PASS arm {key} FPS={result["fps"]:.6f} warmup_ms={result["metrics"]["warmup_ms"]} measured_ms={result["metrics"]["measured_ms"]}',flush=True)
            browser.close()
    finally:
        write(args.out/(key+'-network.json'),network)
        write(args.out/(key+'-errors.json'),errors)
        server.shutdown();server.server_close()


def audit(out):
    manifest=read(out/'manifest.json')
    for p,h in manifest['evidence_sha256'].items():
        assert sha((out/p).read_bytes())==h,p
    assert hashes(out/'snapshot')==manifest['source_sha256']
    results=[]
    for i,arm in enumerate('ABBA'):
        key=f'{i}-{arm}'
        command=manifest['commands'][i]
        assert command['exit']==0 and command['duration_seconds']<=120,command
        raw=read(out/(key+'-raw.json'))
        result=summarize_profile(raw)
        assert result==read(out/(key+'-result.json'))
        assert raw['source_sha256']==manifest['source_sha256']
        assert raw['inputs'] and raw['transitions']
        assert raw['layout']['backing']==[1688,780] and raw['layout']['viewport']==[844,390] and raw['layout']['dpr']==2
        assert result['metrics']['warmup_ms']>=5000 and result['metrics']['measured_ms']>=30000
        assert raw['seed']==292 and raw['input_policy']==INPUT
        assert f'PASS arm {key}' in (out/(key+'-command.log')).read_text()
        assert not read(out/(key+'-errors.json'))
        results.append(result)
        print(f'PASS {key}: hashes, traces, backing, duration, raw recomputation; FPS={result["fps"]:.6f}')
    for a,b in [(0,1),(3,2)]:
        print(f'OBSERVER pair A{a}/B{b}: RAF mean change {(results[b]["metrics"]["mean_ms"]/results[a]["metrics"]["mean_ms"]-1)*100:.3f}%')
    for i in [1,2]:
        r=results[i]
        print(f'TIMING B{i}: draw={r["draw_mean_ms"]:.3f}ms untimed={r["untimed_mean_ms"]:.3f}ms')
        for k,v in sorted(r['costs'].items(),key=lambda kv:-kv[1]['mean_ms']):
            print(f'  {k}: mean_ms={v["mean_ms"]:.3f} calls={v["calls"]}')
    print('PASS diagnostic only; no improvement or FPS acceptance claim')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--arm',choices=['A','B'])
    p.add_argument('--index',type=int)
    p.add_argument('--audit',action='store_true')
    args=p.parse_args();args.out=args.out.resolve()
    if args.audit: return audit(args.out)
    if args.arm:return worker(args)
    assert not args.out.exists(),'use a fresh output directory'
    args.out.mkdir(parents=True)
    source=read(Path('artifacts/TASK-312/source.json'))['source_sha256']
    for name,h in source.items():
        data=Path(name).read_bytes();assert sha(data)==h,name
        dest=args.out/'snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(data);dest.chmod(0o444)
    tested=Path(__file__).read_bytes();(args.out/'tested-harness.py').write_bytes(tested)
    manifest={'started_utc':utc(),'cwd':str(Path.cwd()),'head':git('rev-parse','HEAD').decode().strip(),
              'source_sha256':source,'commands':[], 'harness_sha256':sha(tested),
              'protocol':'AB then BA; 120s per arm, <=600s experiment; Main/classic; timer-only; nested timings are inclusive'}
    start=time.monotonic()
    for i,arm in enumerate('ABBA'):
        command=[sys.executable,str(Path(__file__).resolve()),'--out',str(args.out),'--arm',arm,'--index',str(i)]
        began=time.monotonic();record={'command':command,'started_utc':utc()}
        with (args.out/f'{i}-{arm}-command.log').open('w') as log:
            log.write('COMMAND '+json.dumps(command)+'\n');log.flush()
            try:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=min(120,600-(began-start))).returncode
            except subprocess.TimeoutExpired:code=124
            log.write(f'EXIT {code}\n')
        record.update(exit=code,ended_utc=utc(),duration_seconds=time.monotonic()-began)
        manifest['commands'].append(record)
        print(f'ARM {i}-{arm} EXIT {code}',flush=True)
        write(args.out/'manifest.json',manifest)
    manifest.update(ended_utc=utc(),duration_seconds=time.monotonic()-start,
        evidence_sha256={str(f.relative_to(args.out)):sha(f.read_bytes()) for f in args.out.rglob('*') if f.is_file() and f.name!='manifest.json'})
    write(args.out/'manifest.json',manifest)
    audit(args.out)


if __name__=='__main__':main()
