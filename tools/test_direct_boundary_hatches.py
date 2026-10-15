"""Native boundary migration controls, world phase, joins, clipping and allocation checks."""
from contextlib import ExitStack
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image
from browser_test_support import start_browser_test
from perf_mobile import ROOT, export_rev, SEED_SCRIPT
from render_snapshot import CLOCK_SCRIPT, boot_frozen
from test_chill_boundary_hatches import SETUP, ISOLATE as OLD_ISOLATE
from test_obstacle_hatches import decoded

# Compare the actual generated segment collection with a single equivalent
# continuous element through production bounds calculation and hatch drawing.
ISOLATE = OLD_ISOLATE.replace("for(const e of f.elements)f.drawClassicBoundaryHatch({...b,left:e.getLeftPointX(),right:e.getRightPointX()});", """
 const saved=f.elements;
 try {
  f.elements=[{getLeftPointX:()=>b.left,getRightPointX:()=>b.right,
   getPoints:()=>[{x:b.left,y:b.top},{x:b.right,y:b.bottom}]}];
  f.drawClassicBoundaryHatch(f.getContinuousSurfaceBounds());
 }finally{f.elements=saved;}
""")

HUD = r'''() => {
 const vw=width/scale[version],vh=height/scale[version],font=getHudFontSize(vw,vh,version);
 ctx.save();ctx.font=font+'px '+scoreText.fontFamily;
 const right=vw*.03+ctx.measureText(scoreText.text+scoreText.count[version]).width+font*.4;
 const left=scoreText.getRecordX(vw)-ctx.measureText(scoreText.rtext+scoreText.record[version]).width-font*.4;
 const bottom=Math.max(getHudCenterY(vh,version)+font*.8,menu.button.background.y+menu.button.background.height);
 ctx.restore();return [[0,0,right,bottom],[left,0,vw-left,bottom]];
}'''
STATE = r'''() => {
 const original=ctx,c=document.createElement('canvas');c.width=canvas.width;c.height=canvas.height;
 ctx=c.getContext('2d');let tiles=0,patterns=0;
 const ce=document.createElement,cp=CanvasRenderingContext2D.prototype.createPattern;
 try {
  ctx.setTransform(.8,0,0,.8,.125,.375);ctx.globalAlpha=.37;ctx.strokeStyle='#123456';ctx.setLineDash([2,5]);
  const clip=new Path2D();clip.rect(0,0,100,100);ctx.clip(clip);
  const state=()=>JSON.stringify([Array.from(ctx.getTransform().toFloat64Array()),ctx.globalAlpha,ctx.strokeStyle,ctx.getLineDash(),ctx.font]);
  const before=state();
  document.createElement=function(...a){if(a[0]==='canvas')tiles++;return ce.apply(this,a)};
  CanvasRenderingContext2D.prototype.createPattern=function(...a){patterns++;return cp.apply(this,a)};
  for(let i=0;i<60;i++)for(const v of ['bold','thin','cross','chevron','off']){
   STYLE.dangerHatch.variant=v;for(const f of strips)f.drawClassicBoundaryHatch(f.getContinuousSurfaceBounds());
  }
  const preserved=before===state();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);
  return {draws:600,tiles,patterns,statePreserved:preserved,clipOutsideAlpha:ctx.getImageData(200,200,1,1).data[3]};
 }finally{document.createElement=ce;CanvasRenderingContext2D.prototype.createPattern=cp;ctx=original;}
}'''

def grab(page,kind):
 return np.array(decoded(page.evaluate(ISOLATE,kind)))

def premult(a):
 a=a.astype(np.int32);a[:,:,:3]=(a[:,:,:3]*a[:,:,3:4]+127)//255;return a

def main(out):
 out.mkdir(parents=True,exist_ok=True)
 base=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 report={'baseline':base,'sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['sprites/rect.js','sprites/floor.js','tools/test_direct_boundary_hatches.py']},'cases':{}}
 controls={}
 for phase,rev in [('before',base),('after','worktree')]:
  with ExitStack() as stack:
   root,_=export_rev(rev,stack.callback);url,browser=start_browser_test(root,stack.callback)
   report['browser']=browser.version
   for label,w,h,dpr in [('desktop',1920,1080,1),('phone',844,390,3)]:
    context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=dpr,is_mobile=label=='phone',has_touch=label=='phone')
    context.add_init_script(SEED_SCRIPT%1);context.add_init_script(CLOCK_SCRIPT)
    page=context.new_page();page.goto(url);boot_frozen(page)
    for mode in ['classic','bad']:
     meta=page.evaluate(SETUP,mode);z=meta['u']*meta['backing'][0]/meta['width']
     # Center a real generated join without changing the world origin.
     page.evaluate('z=>{for(const f of strips){const shift=canvas.width/z/2-f.elements[0].getRightPointX();for(const e of f.elements)e.x+=shift;}}',z)
     bounds=page.evaluate('strips.map(f=>f.getContinuousSurfaceBounds())')
     hud=page.evaluate(HUD)
     for v in ['bold','thin','cross','chevron','off']:
      for trajectory,dx,dy in [('static',0,0),('horizontal',.375,0),('diagonal',.375,.625)]:
       key=f'{label}-{mode}-{v}-{trajectory}'
       page.evaluate('p=>{STYLE.dangerHatch.variant=p[0];screen.x=p[1];screen.y=p[2]}',[v,dx/z,dy/z])
       body=grab(page,'body');Image.fromarray(body).save(out/f'{phase}-{key}.png')
       if phase=='before':controls[key]=body;continue
       yy,xx=np.indices(body.shape[:2]);allowed=np.zeros(body.shape[:2],bool)
       for b in bounds:
        inset=page.evaluate('b=>Math.max(STYLE.strokes.neonGlowWidth,(b.bottom-b.top)*.2)',b)
        allowed|=(yy>=(b['top']+inset)*z+dy-1)&(yy<=(b['bottom']-inset)*z+dy+1)&(xx>=b['left']*z+dx-1)&(xx<=b['right']*z+dx+1)
       hudmask=np.zeros_like(allowed)
       for x,y,bw,bh in hud:
        hudmask|=(xx>=np.ceil(x*z))&(xx<np.floor((x+bw)*z))&(yy>=np.ceil(y*z))&(yy<np.floor((y+bh)*z))
       diff=np.any(body!=controls[key],axis=2)
       r={'outsideInteriorDifferences':int((diff&~allowed).sum()),'hudDifferences':int((diff&hudmask).sum())}
       assert r['outsideInteriorDifferences']==r['hudDifferences']==0,(key,r)
       if mode=='bad' or v=='off':
        r['controlDifferences']=int(diff.sum());assert not diff.any(),key
       if mode=='classic':
        actual=grab(page,'hatch');split=grab(page,'split');reference=grab(page,'reference')
        assert not ((actual[:,:,3]>0)&(~allowed|hudmask)).any(),key
        r['coveredPixels']=int((actual[:,:,3]>0).sum());assert (r['coveredPixels']==0)==(v=='off'),key
        r['splitInteriorMaxDelta']=int(abs(premult(actual)-premult(split)).max())
        assert r['splitInteriorMaxDelta']==0,(key,r)
        join=int(actual.shape[1]/2+dx)
        r['joinVsContinuousDifferences']=int(np.any(actual[:,join-2:join+3]!=reference[:,join-2:join+3],axis=2).sum())
        assert r['joinVsContinuousDifferences']==0,(key,r)
        Image.fromarray(actual[:,join-32:join+33]).save(out/f'join-{key}.png')
        # Fractional starting phase followed by an integral backing displacement.
        page.evaluate('p=>{screen.x+=7/p;screen.y+=5/p}',z)
        moved=grab(page,'hatch');registered=np.roll(moved,(-5,-7),(0,1))
        # Compare interior away from outer strip clips and fixed HUD masks.
        mask=allowed&~hudmask&~np.roll(hudmask,(-5,-7),(0,1))
        mask[:,:int(w*.3)]=False;mask[:,int(body.shape[1]*.7):]=False
        for b in bounds:
         for yedge in [(b['top']+max(6,(b['bottom']-b['top'])*.2))*z+dy,(b['bottom']-max(6,(b['bottom']-b['top'])*.2))*z+dy]:
          mask[max(0,int(yedge)-4):max(0,int(yedge)+5)]=False
        pa,pb=premult(actual),premult(registered)
        delta=abs(pa[mask]-pb[mask])
        assert mask.any(),key
        r['registeredPhaseMaxDelta']=int(delta.max())
        r['registeredPhaseMeanDelta']=float(delta.mean())
        # Cross intersections can change individual AA samples after translation.
        # Bound average error and require the known world phase to beat a wrong phase.
        r['wrongPhaseMeanDelta']=float(abs(pa[mask]-np.roll(pb,4,axis=1)[mask]).mean())
        assert r['registeredPhaseMeanDelta']<1,(key,r)
        if v!='off':assert r['registeredPhaseMeanDelta']<r['wrongPhaseMeanDelta'],(key,r)
       report['cases'][key]=r
     if phase=='after':
      print(f'PASS {label} {mode}: all four variants and off; fractional horizontal/diagonal; outside interiors=0 HUD differences=0; '+('generated segments vs single continuous strip=0; join differences=0; registered phase mean <1 and better than incorrect phase' if mode=='classic' else 'main boundaries pixel-identical'),flush=True)
      if mode=='classic':
       r=page.evaluate(STATE);assert r==dict(draws=600,tiles=0,patterns=0,statePreserved=True,clipOutsideAlpha=0),r
       report[label+'State']=r
       print(f'PASS {label}: 600 boundary draws tiles=0 patterns=0; state preserved; clipOutsideAlpha=0',flush=True)
    context.close()
 report['pass']=True;(out/'boundary-checks.json').write_text(json.dumps(report,indent=2)+'\n')
 print(f'PASS boundary-checks.json: {len(report["cases"])} cases executed',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=ROOT/'artifacts/TASK-441');main(p.parse_args().out)
