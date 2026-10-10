"""Finite isolated live-geometry experiment. Never claims release acceptance."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile
from browser_test_support import start_browser_test, wait_for_boot
from perf_mobile import SEED_SCRIPT
from render_snapshot import CLOCK_SCRIPT, SETUP_SCRIPT, boot_frozen, input_script
from profile_y8_glow_bounds import OLD, sha, save
from profile_y8_readback_oracle import HARNESS
from y8_fps_baseline import SDK

ROOT=Path(__file__).resolve().parents[1]
# Reuse only the serializer definition, not the old traced/timed replay.
SERIALIZER=HARNESS[HARNESS.index(' p.serialize='):HARNESS.index(' window.__oracleDraw=')]
VALIDATE='''() => {
 const p=window.__probe={};
'''+SERIALIZER+'''
 p.capture=async()=>{
  const sources=[];
  for(const r of [visualEffects.ambientGlow,visualEffects.playerGlow])
   for(const l of r.levels)sources.push(await p.hash(l.ctx.getImageData(0,0,l.canvas.width,l.canvas.height).data));
  return {state:p.state(),sources,output:await p.hash(ctx.getImageData(0,0,canvas.width,canvas.height).data),
    canvas:[canvas.width,canvas.height],geometry:window.__geometryCalls||[]};
 };
 window.__geometryObserve=(r,i,b,fallback)=>{window.__geometryCalls.push({type:r.constructor.name,i,b,fallback,full:r.canvas.width*r.canvas.height})};
 window.__geometryCalls=[];
}'''
MEASURE='''() => {
 RENDER_BUDGET.densityLimit=2;RENDER_BUDGET.observe=()=>false;
 window.measure={frames:[],activeMs:0,done:false,readbacks:0};let previous=null;
 // Count only readback calls: no clock calls or per-draw timing wrappers.
 const read=CanvasRenderingContext2D.prototype.getImageData;
 CanvasRenderingContext2D.prototype.getImageData=function(...a){measure.readbacks++;return read.apply(this,a)};
 const loop=gameLoop;
 gameLoop=function(t){
  if(!measure.done&&!menu.visible&&!menu.gamePaused&&!document.hidden){
   const dt=previous===null?null:t-previous;previous=t;
   measure.frames.push({t,dt,canvas:[canvas.width,canvas.height]});
   if(dt!==null)measure.activeMs+=dt;
   if(measure.activeMs>=30000)measure.done=true;
  } else previous=null;
  return loop.call(this,t);
 };
}'''

def capture(out):
 out.mkdir(parents=True,exist_ok=False)
 archive=ROOT/'artifacts/y8-release/grapnelninja-y8.zip'
 with zipfile.ZipFile(archive) as z:
  for n in z.namelist():assert z.read(n)==subprocess.check_output(['git','show','HEAD:'+n]),n
  for arm in ('control','candidate'):z.extractall(out/arm)
 f=out/'candidate/render/effects.js';original=f.read_text();changed=original
 replacements={OLD:'            window.__geometryDraw(this, i)',
  '            drawShapes.call(this, arg)':'            window.__geometryBegin(glowCtx)\n            drawShapes.call(this, arg)\n            window.__geometryEnd(glowCtx)',
  '        ctx.fill(path)':'        window.__geometryRibbon(ctx, positions, start, width)\n        ctx.fill(path)'}
 for a,b in replacements.items():assert changed.count(a)==1;changed=changed.replace(a,b)
 f.write_text(changed)
 js=(ROOT/'tools/y8_live_geometry.js').read_text()
 (out/'candidate/geometry.js').write_text(js)
 f=out/'candidate/index.html';f.write_text(f.read_text().replace('<head>','<head><script src="geometry.js"></script>'))
 (out/'candidate.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True))))
 save(out/'overrides.json',dict(validate=VALIDATE,measure=MEASURE,clock=CLOCK_SCRIPT,setup=SETUP_SCRIPT,seed=SEED_SCRIPT,input=input_script(ticks=180,width=780,height=390)))
 manifest=dict(source_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),archive_sha256=sha(archive),started_utc=datetime.now(timezone.utc).isoformat(),argv=sys.argv,tool_sha256=sha(Path(__file__)),geometry_sha256=sha(ROOT/'tools/y8_live_geometry.js'),package_ready=False,validation=[],pairs=[])
 save(out/'manifest.partial.json',manifest)
 with ExitStack() as stack:
  url,browser=start_browser_test(out,stack.callback)
  save(out/'environment.json',dict(browser=browser.version,os=platform.platform(),gpu=browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu'],cpu=Path('/proc/cpuinfo').read_text(),viewport=[780,390],DPR=2,cpu_throttle=1))
  def run(arm,mode,seed,validate,name):
   c=browser.new_context(viewport={'width':780,'height':390},device_scale_factor=2,service_workers='block');errors=[];network=[];rows=[]
   def route(r):
    u=r.request.url
    if u==SDK:network.append('FAKE_SDK '+u);r.fulfill(content_type='text/javascript',body=(ROOT/'tools/fixtures/fake-y8-sdk.js').read_text())
    elif u.startswith(url):network.append('LOCAL '+u);r.continue_()
    else:network.append('BLOCKED '+u);r.abort()
   c.route('**/*',route);c.add_init_script(SEED_SCRIPT%seed+ (';\n'+CLOCK_SCRIPT if validate else ''))
   p=c.new_page();p.on('pageerror',lambda e:errors.append(str(e)))
   c.new_cdp_session(p).send('Emulation.setCPUThrottlingRate',{'rate':1})
   before=dict(utc=datetime.now(timezone.utc).isoformat(),load=os.getloadavg())
   try:
    p.goto(url+arm+'/index.html',wait_until='load')
    if validate:
     boot_frozen(p);p.evaluate(SETUP_SCRIPT,[input_script(ticks=180,width=780,height=390),False]);p.evaluate('RENDER_BUDGET.densityLimit=2;RENDER_BUDGET.observe=()=>false');p.evaluate(VALIDATE)
     rows.append(dict(case='menu',**p.evaluate('__probe.capture()')))
     p.evaluate('(m)=>startGame(m)',mode)
     for tick in range(1,181):
      p.evaluate('window.__geometryCalls=[];screen.x-=0.125;screen.y+=0.0625;__snap.step()')
      if tick%10==0:rows.append(dict(case='moving-'+str(tick),**p.evaluate('__probe.capture()')))
     # Adversarial emitted geometry and camera/shake, then odd/fractional resize.
     p.evaluate('''ninja.track.pos=Array.from({length:80},(_,i)=>({x:ninja.x-900+i*14,y:ninja.y+Math.sin(i)*180}));
       for(const x of [-screen.x, width/scale[version]-screen.x]) visualEffects.particles.pushParticle(x,ninja.y,0,0,'#fff',1000,18,1,true,false,true);
       screen.x+=31.25;screen.y-=19.75;visualEffects.screenEffects.shakeStart=performance.now();visualEffects.screenEffects.shakeUntil=performance.now()+500;draw();''')
     rows.append(dict(case='long-trail-edge-sparks-shake',**p.evaluate('__probe.capture()')))
     assert p.evaluate('Math.hypot(visualEffects.screenEffects.shakeOffset.x,visualEffects.screenEffects.shakeOffset.y)>0')
     p.evaluate("window.__resizeObserved=false;window.addEventListener('resize',()=>{window.__resizeObserved=true},{once:true})")
     p.set_viewport_size({'width':781,'height':391});p.wait_for_function('__resizeObserved',polling=10)
     p.evaluate('for(let i=0;i<10;i++)__snap.step();draw()');rows.append(dict(case='resize',**p.evaluate('__probe.capture()')))
     assert rows[-1]['canvas']!=[1560,780], rows[-1]['canvas']
     p.evaluate('canvas.width=1559;canvas.height=779;draw()');rows.append(dict(case='odd-backing',**p.evaluate('__probe.capture()')))
     p.evaluate('visualEffects.ambientGlow.drawScreen(()=>{})');rows.append(dict(case='empty',**p.evaluate('__probe.capture()')))
    else:
     wait_for_boot(p);p.evaluate(MEASURE);p.evaluate('(m)=>startGame(m)',mode);p.wait_for_function('measure.done',timeout=180000);rows=p.evaluate('measure')
   finally:
    save(out/(name+'-rows.json'),rows);save(out/(name+'-errors.json'),errors);save(out/(name+'-network.json'),network);save(out/(name+'-host.json'),dict(before=before,after=dict(utc=datetime.now(timezone.utc).isoformat(),load=os.getloadavg())));c.close()
   assert not errors,errors
   print('CAPTURE',name,flush=True);return rows
  failed=False
  for mode in ('bad','classic'):
   for seed in (1,7,49):
    a=run('control',mode,seed,True,f'{mode}-{seed}-control');b=run('candidate',mode,seed,True,f'{mode}-{seed}-candidate')
    for x,y in zip(a,b):
     row=dict(mode=mode,seed=seed,case=x['case'],state=x['state']==y['state'],sources=x['sources']==y['sources'],output=x['output']==y['output'])
     manifest['validation'].append(row);failed|=not all(row[k] for k in ('state','sources','output'))
    print('IDENTITY',mode,seed,'FAIL' if failed else 'PASS',flush=True)
  if failed:manifest['decision']='REJECT_IDENTITY_MISMATCH'
  else:
   for mode in ('bad','classic'):
    for rep in range(1,4):
     results={}
     for arm in (('control','candidate') if rep%2 else ('candidate','control')):
      name=f'{mode}-r{rep}-{arm}';r=run(arm,mode,1,False,name)
      assert r['readbacks']==0 and r['activeMs']>=30000
      assert all(f['canvas']==[1560,780] for f in r['frames'])
      results[arm]=(len(r['frames'])-1)*1000/r['activeMs']
     row=dict(mode=mode,repetition=rep,**results,benefit=results['candidate']>results['control']);manifest['pairs'].append(row);print('PAIR',row,flush=True)
   manifest['decision']='PURSUE' if all(r['benefit'] for r in manifest['pairs']) else 'REJECT_INCONSISTENT_BENEFIT'
 manifest['ended_utc']=datetime.now(timezone.utc).isoformat()
 manifest['evidence_sha256']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
 save(out/'manifest.json',manifest);print('DECISION',manifest['decision'],flush=True)

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();capture(a.out.resolve())
