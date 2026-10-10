"""Nonshipping three-arm deterministic glow replay. Never a release FPS gate.

Bounds are recorded outside timing and valid ONLY for the identical replay.
Every frame is checked off-clock for source RGBA, state and output identity.
Timed passes check state keys and count readbacks; Chrome traces retain raster
work separately from JS submission and frame wall time (not additive metrics).
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT
from render_snapshot import CLOCK_SCRIPT, SETUP_SCRIPT, boot_frozen, input_script
from profile_y8_glow_bounds import OLD, sha, save
from y8_fps_baseline import SDK

ROOT = Path(__file__).resolve().parents[1]
ARMS = ('control', 'readback', 'oracle')
INIT = 'window.__realNow=performance.now.bind(performance); window.__realRAF=requestAnimationFrame.bind(window);\n'
HARNESS = r'''({arm, verify}) => {
 const p = window.__probe = {arm, verify, calls:[], buffers:[], reads:0, draws:0, area:0};
 const proto=CanvasRenderingContext2D.prototype, read=proto.getImageData, drawImage=proto.drawImage;
 proto.getImageData=function(...a){p.reads++;return read.apply(this,a)};
 proto.drawImage=function(...a){p.draws++;return drawImage.apply(this,a)};
 for(const method of ['drawImage','fill','stroke','fillRect','strokeRect','clearRect','fillText','strokeText','putImageData','getImageData']){
   const original=proto[method];proto[method]=function(...args){
     const start=__realNow();try{return original.apply(this,args)}finally{p.canvas_api_ms+=__realNow()-start}
   };
 }
 p.serialize=value=>{const seen=new WeakSet();return JSON.stringify(value,(k,v)=>{
   if(typeof v==='function')return undefined;
   if(v&&typeof v==='object'){
     if(v instanceof HTMLCanvasElement)return {canvas:[v.width,v.height]};
     if(v instanceof CanvasRenderingContext2D)return {transform:Array.from(['a','b','c','d','e','f'],k=>v.getTransform()[k])};
     if(seen.has(v))return '[reference]';seen.add(v);
   }return v;
 })};
 p.state=()=>p.serialize({tick:__snap.tick,clock:__snap.now,date:Date.now(),pulse:neonPulse,
   ninja,screen,grapnel,floors,version,drawFrameId,effects:visualEffects,
   timers:__snap.timers.map(t=>[t.id,t.due,t.ms,t.repeat]),rafs:__snap.rafs});
 p.hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
 window.__oracleDraw=(renderer,i)=>{
   const level=renderer.levels[i], w=level.canvas.width,h=level.canvas.height;
   const key=p.serialize({type:renderer.constructor.name,i,w,h,
     transform:renderer.ctx.getTransform().toJSON(),alpha:renderer.ctx.globalAlpha,
     composite:renderer.ctx.globalCompositeOperation});
   const expected=p.expected?.calls[p.calls.length];
   if(expected && key!==expected.key)throw Error('replay state mismatch tick '+__snap.tick);
   let bounds=expected?.bounds,bytes;
   if(p.verify || arm==='readback'){
     bytes=level.ctx.getImageData(0,0,w,h).data;
     let left=w,top=h,right=-1,bottom=-1;
     for(let y=0;y<h;y++)for(let x=0;x<w;x++){
       const o=(y*w+x)*4;if(bytes[o]||bytes[o+1]||bytes[o+2]){
         left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);
       }
     }
     const sx=renderer.canvas.width/w,sy=renderer.canvas.height/h;
     bounds=right<left?null:[Math.max(0,Math.floor((left-1)*sx)),Math.max(0,Math.floor((top-1)*sy)),
       Math.min(renderer.canvas.width,Math.ceil((right+2)*sx)),Math.min(renderer.canvas.height,Math.ceil((bottom+2)*sy))];
     if(expected && JSON.stringify(bounds)!==JSON.stringify(expected.bounds))throw Error('bounds mismatch');
   }
   if(p.verify)p.buffers.push(bytes);
   p.calls.push({key,bounds});
   if(arm==='control'){
     p.area+=renderer.canvas.width*renderer.canvas.height;
     renderer.ctx.drawImage(level.canvas,0,0,renderer.canvas.width,renderer.canvas.height);return;
   }
   if(!bounds)return;
   const [x0,y0,x1,y1]=bounds;p.area+=(x1-x0)*(y1-y0);
   renderer.ctx.save();renderer.ctx.beginPath();renderer.ctx.rect(x0,y0,x1-x0,y1-y0);renderer.ctx.clip();
   renderer.ctx.drawImage(level.canvas,0,0,renderer.canvas.width,renderer.canvas.height);renderer.ctx.restore();
 };
 const originalDraw=draw;
 draw=()=>{p.frameState=p.state();if(p.expected && p.frameState!==p.expected.state)throw Error("frame state mismatch tick "+__snap.tick);return originalDraw()};
 p.frame=async expected=>{
   p.expected=expected;
   p.calls=[];p.buffers=[];p.reads=0;p.draws=0;p.area=0;p.canvas_api_ms=0;
   const start=__realNow();__snap.step();const submitted=__realNow();
   await new Promise(resolve=>__realRAF(()=>__realRAF(resolve)));
   const end=__realNow();
   const row={tick:__snap.tick,submission_ms:submitted-start,frame_wall_ms:end-start,
     readbacks:p.reads,draw_calls:p.draws,area:p.area,canvas_api_ms:p.canvas_api_ms,state:p.frameState,calls:p.calls};
   if(p.verify){
     row.sources=await Promise.all(p.buffers.map(b=>p.hash(b)));
     row.output=await p.hash(ctx.getImageData(0,0,canvas.width,canvas.height).data);
   }
   if(canvas.width!==1560||canvas.height!==780)throw Error('backing mismatch');
   return row;
 };
}'''


def host():
    return dict(utc=datetime.now(timezone.utc).isoformat(), load=os.getloadavg(),
                proc_stat=Path('/proc/stat').read_text(), meminfo=Path('/proc/meminfo').read_text())


def capture(archive, out, frames):
    out.mkdir(parents=True, exist_ok=False)
    save(out/'command.json', dict(argv=sys.argv, utc=datetime.now(timezone.utc).isoformat()))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist()))
        assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist())
        for n in z.namelist():
            assert z.read(n) == subprocess.check_output(['git','show',f'HEAD:{n}']), n
        z.extractall(out/'fixture')
    effects=out/'fixture/render/effects.js'
    source=effects.read_text();assert source.count(OLD)==1
    effects.write_text(source.replace(OLD,'            window.__oracleDraw(this, i)'))
    save(out/'overrides.json',dict(init=INIT+SEED_SCRIPT%1+';\n'+CLOCK_SCRIPT,
         setup=SETUP_SCRIPT,harness=HARNESS,input=input_script(ticks=frames,width=780,height=390),
         replacement='window.__oracleDraw(this, i)',density='RENDER_BUDGET.densityLimit=2; RENDER_BUDGET.observe=()=>false'))
    runs=[]
    with ExitStack() as stack:
        url,browser=start_browser_test(out/'fixture',stack.callback)
        environment=dict(os=platform.platform(),python=sys.version,browser=browser.version,
            gpu=browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu'],cpu=Path('/proc/cpuinfo').read_text())
        save(out/'environment.json',environment)
        def run(mode,arm,verify,records,name):
            context=browser.new_context(viewport={'width':780,'height':390},device_scale_factor=2,service_workers='block')
            network=[];errors=[]
            def route(r):
                u=r.request.url
                if u==SDK:
                    network.append('FAKE_SDK '+u);r.fulfill(content_type='text/javascript',body=(ROOT/'tools/fixtures/fake-y8-sdk.js').read_text())
                elif u.startswith(url):network.append('LOCAL '+u);r.continue_()
                else:network.append('BLOCKED '+u);r.abort()
            context.route('**/*',route)
            context.add_init_script(INIT+SEED_SCRIPT%1+';\n'+CLOCK_SCRIPT)
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            # Menu rendering may invoke the patched composite before the probe exists.
            page.add_init_script('window.__oracleDraw=(r,i)=>r.ctx.drawImage(r.levels[i].canvas,0,0,r.canvas.width,r.canvas.height)')
            page.goto(url+'index.html',wait_until='load');boot_frozen(page)
            page.evaluate(SETUP_SCRIPT,[input_script(ticks=frames,width=780,height=390),False])
            page.evaluate('RENDER_BUDGET.densityLimit=2;RENDER_BUDGET.observe=()=>false')
            page.evaluate('(mode)=>startGame(mode)',mode)
            page.evaluate(HARNESS,dict(arm=arm,verify=verify))
            before=host();trace=[];cdp=context.new_cdp_session(page)
            if not verify:
                cdp.on('Tracing.dataCollected',lambda e:trace.extend(e['value']))
                cdp.send('Tracing.start',dict(categories='devtools.timeline,cc,gpu,skia,disabled-by-default-skia,disabled-by-default-gpu.service',transferMode='ReportEvents'))
            rows=[]
            try:
                for index in range(frames):
                    expected=None if records is None else {k:records[index][k] for k in ('state','calls')}
                    rows.append(page.evaluate('expected=>__probe.frame(expected)',expected))
            finally:
                save(out/(name+'-rows.json'),rows)
                save(out/(name+'-network.json'),network);save(out/(name+'-errors.json'),errors)
            if not verify:
                ended=[];cdp.on('Tracing.tracingComplete',lambda e:ended.append(True));cdp.send('Tracing.end')
                while not ended:page.wait_for_timeout(25)
                save(out/(name+'-trace.json'),trace)
            save(out/(name+'-host.json'),dict(before=before,after=host()))
            assert not errors,errors
            assert any(n.startswith('FAKE_SDK') for n in network)
            context.close()
            print('CAPTURE',name,'frames',len(rows),flush=True)
            return rows
        for mode in ('bad','classic'):
            record=run(mode,'control',True,None,mode+'-record')
            for arm in ARMS:
                rows=run(mode,arm,True,record,mode+'-verify-'+arm)
                for a,b in zip(record,rows):
                    assert (a['state'],a['calls'],a['sources'],a['output'])==(b['state'],b['calls'],b['sources'],b['output']), (mode,arm,a['tick'])
            print('PASS replay identity',mode,frames,'frames; source/state/final RGBA SHA256',flush=True)
            for repetition in range(3):
                for arm in ARMS[repetition:]+ARMS[:repetition]:
                    name=f'{mode}-r{repetition+1}-{arm}'
                    rows=run(mode,arm,False,record,name)
                    assert [r['state'] for r in rows]==[r['state'] for r in record]
                    assert all(len(r['calls'])==len(e['calls']) for r,e in zip(rows,record))
                    assert all(r['readbacks']==(len(r['calls']) if arm=='readback' else 0) for r in rows)
                    events=json.loads((out/(name+'-trace.json')).read_text())
                    raster=[e for e in events if 'SkCanvas::' in e.get('name','') and e.get('ph')=='X']
                    assert raster,'No SkCanvas trace evidence'
                    summary=dict(mode=mode,arm=arm,repetition=repetition+1,name=name,
                        frame_wall_ms=sum(r['frame_wall_ms'] for r in rows),submission_ms=sum(r['submission_ms'] for r in rows),
                        skia_observed_wall_ms=sum(e['dur'] for e in raster)/1000,skia_spans=len(raster),
                        canvas_api_ms=sum(r['canvas_api_ms'] for r in rows),readbacks=sum(r['readbacks'] for r in rows),draw_calls=sum(r['draw_calls'] for r in rows),
                        area=sum(r['area'] for r in rows))
                    runs.append(summary);save(out/'runs.json',runs);print(json.dumps(summary),flush=True)
    pursue=all(next(r for r in runs if r['mode']==m and r['arm']=='oracle' and r['repetition']==i)['frame_wall_ms'] <
               next(r for r in runs if r['mode']==m and r['arm']=='readback' and r['repetition']==i)['frame_wall_ms']
               for m in ('bad','classic') for i in (1,2,3))
    save(out/'manifest.json',dict(source_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        archive=str(archive),archive_sha256=sha(archive),frames=frames,runs=runs,
        decision='PURSUE_GEOMETRY_CANDIDATE' if pursue else 'REJECT_READBACK_HYPOTHESIS',
        performance_acceptance='NOT_RUN; inherited six FAIL_MEASURED_REGRESSION remain binding',package_ready=False,
        limitations='Deterministic oracle only; manual 60Hz simulation, double real rAF barrier, Chrome tracing overhead. RasterTask unavailable for this canvas path. canvas_api_ms measures synchronous canvas calls including native raster and readbacks, not GPU completion. SkCanvas spans cover only traced native operations and are NOT total raster time; sums may nest. Frame wall includes a double real-rAF barrier, not a GPU fence. Not acceptance FPS or a live cache.',
        tool_sha256=sha(Path(__file__)),dependencies={n:sha(ROOT/'tools'/n) for n in ('profile_y8_glow_bounds.py','render_snapshot.py','perf_mobile.py','browser_test_support.py','y8_fps_baseline.py','fixtures/fake-y8-sdk.js')},
        evidence_sha256={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    print('DECISION', 'PURSUE_GEOMETRY_CANDIDATE' if pursue else 'REJECT_READBACK_HYPOTHESIS',flush=True)


def audit(archive,out):
    m=json.loads((out/'manifest.json').read_text())
    assert sha(archive)==m['archive_sha256'];assert sha(Path(__file__))==m['tool_sha256']
    for n,h in m['dependencies'].items():assert sha(ROOT/'tools'/n)==h,n
    for n,h in m['evidence_sha256'].items():assert sha(out/n)==h,n
    for mode in ('bad','classic'):
        record=json.loads((out/(mode+'-record-rows.json')).read_text());assert len(record)==m['frames']
        for arm in ARMS:
            rows=json.loads((out/(mode+'-verify-'+arm+'-rows.json')).read_text());assert len(rows)==len(record)
            assert all((a['state'],a['calls'],a['sources'],a['output'])==(b['state'],b['calls'],b['sources'],b['output']) for a,b in zip(record,rows))
        print('PASS replay identity',mode,m['frames'],'frames; source/state/final RGBA SHA256')
    assert len(m['runs'])==18
    for r in m['runs']:
        rows=json.loads((out/(r['name']+'-rows.json')).read_text());assert len(rows)==m['frames']
        assert all(x['readbacks']==(len(x['calls']) if r['arm']=='readback' else 0) for x in rows)
        for metric in ('frame_wall_ms','submission_ms','readbacks','draw_calls','area','canvas_api_ms'):assert sum(x[metric] for x in rows)==r[metric]
        events=json.loads((out/(r['name']+'-trace.json')).read_text())
        raster=[e for e in events if 'SkCanvas::' in e.get('name','') and e.get('ph')=='X']
        assert len(raster)==r['skia_spans']>0;assert sum(e['dur'] for e in raster)/1000==r['skia_observed_wall_ms']
        print('PASS timed repetition',r['name'],'readbacks',r['readbacks'],'SkCanvas spans',len(raster))
    print('PASS evidence hashes',len(m['evidence_sha256']))
    print('DECISION',m['decision'])
    print('FAIL release acceptance: six inherited regressions unresolved; package_ready=false; TASK-265 pending')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=('capture','audit'))
    ap.add_argument('--archive',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--frames',type=int,default=120);args=ap.parse_args()
    if args.action=='capture':capture(args.archive.resolve(),args.out.resolve(),args.frames)
    else:audit(args.archive.resolve(),args.out.resolve())
