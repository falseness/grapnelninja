"""Focused native object-hatch migration checks; evidence defaults to TASK-440."""
from contextlib import ExitStack
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import ROOT, export_rev, SEED_SCRIPT
from render_snapshot import CLOCK_SCRIPT, boot_frozen
from test_obstacle_hatches import TRI_SCENE, TRI_ISOLATE, decoded, triangle_clip

PROBE = r'''() => {
 const original=ctx, c=document.createElement('canvas');c.width=512;c.height=384;
 ctx=c.getContext('2d'); const results={variants:{}, motion:[], instrumentation:{}};
 const objects=[hatchFixture.orange,hatchFixture.cube,hatchFixture.pink,hatchFixture.red];
 function paint(o,dx=0,dy=0) {
  ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,512,384);
  const x=150.25+dx,y=140.375+dy;
  if(o instanceof Triangle){ctx.beginPath();ctx.moveTo(x-70,y-55);ctx.lineTo(x+70,y-55);ctx.lineTo(x,y+90);ctx.closePath();}
  o.drawDangerHatch(x,y);return c.toDataURL();
 }
 try {
  for(const v of ['bold','thin','cross','chevron','off']) {
   STYLE.dangerHatch.variant=v;results.variants[v]=objects.map(o=>paint(o));
  }
  STYLE.dangerHatch.variant='bold';
  // Fractional camera and object translations combine to the same local phase.
  for(const o of objects){results.motion.push([paint(o,.25,.375),paint(o,3.25,5.375)]);}
  let tiles=0,patterns=0,lines=0;
  const ce=document.createElement,cp=CanvasRenderingContext2D.prototype.createPattern,lt=Path2D.prototype.lineTo;
  document.createElement=function(...a){if(a[0]==='canvas')tiles++;return ce.apply(this,a)};
  CanvasRenderingContext2D.prototype.createPattern=function(...a){patterns++;return cp.apply(this,a)};
  Path2D.prototype.lineTo=function(...a){lines++;return lt.apply(this,a)};
  try {
   for(let i=0;i<60;i++)for(const v of ['bold','thin','cross','chevron']){
    STYLE.dangerHatch.variant=v;for(const o of objects)paint(o);
   }
   results.instrumentation={draws:60,tiles,patterns};results.bounds={};
   for(const v of ['bold','thin','cross','chevron']){
    const counts=[];for(const size of [1000,1e9]){
     lines=0;drawDangerHatchLines(ctx,v,'#99501c',-size,-size,size,size);counts.push(lines);
    }results.bounds[v]=counts;
   }
  }finally{document.createElement=ce;CanvasRenderingContext2D.prototype.createPattern=cp;Path2D.prototype.lineTo=lt;}
  ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,512,384);
  ctx.setTransform(1.25,0,0,1.5,.125,.375);ctx.globalAlpha=.37;ctx.strokeStyle='#123456';ctx.lineWidth=7;ctx.setLineDash([2,5]);
  const clip=new Path2D();clip.rect(10,10,80,80);ctx.clip(clip);
  ctx.beginPath();ctx.rect(20,20,20,20);
  const state=()=>JSON.stringify([Array.from(ctx.getTransform().toFloat64Array()),ctx.globalAlpha,ctx.strokeStyle,ctx.lineWidth,ctx.getLineDash(),ctx.isPointInPath(30,40)]);
  const before=state();drawDangerHatchLines(ctx,'cross','#99501c',0,0,512,384);results.state=before===state();
  ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,512,384);ctx.fillStyle='white';ctx.fillRect(0,0,512,384);
  results.clipOutsideAlpha=ctx.getImageData(300,300,1,1).data[3];
  // Record actual line spacing/width/color without relying on raster AA.
  results.geometry={};const stroke=ctx.stroke,move=Path2D.prototype.moveTo;
  for(const v of ['bold','thin','cross','chevron']){
   const starts=[];Path2D.prototype.moveTo=function(x,y){starts.push([x,y]);return move.call(this,x,y)};
   ctx.stroke=function(p){results.geometry[v]={starts,width:this.lineWidth,colour:this.strokeStyle};return stroke.call(this,p)};
   drawDangerHatchLines(ctx,v,undefined,0,0,200,200);
  }
  ctx.stroke=stroke;Path2D.prototype.moveTo=move;
  return results;
 }finally{ctx=original;STYLE.dangerHatch.variant='bold';}
}'''

def main(out):
 out.mkdir(parents=True,exist_ok=True)
 base=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 report={'baseline':base,'sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['sprites/rect.js','sprites/triangle.js','tools/test_direct_object_hatches.py']},'scenes':{}}
 captures={};controls={};rows=[]
 for phase,rev in [('before',base),('after','worktree')]:
  with ExitStack() as stack:
   root,_=export_rev(rev,stack.callback);url,browser=start_browser_test(root,stack.callback)
   for mode in ['bad','classic']:
    context=browser.new_context(viewport={'width':960,'height':540})
    context.add_init_script(SEED_SCRIPT%1);context.add_init_script(CLOCK_SCRIPT)
    page=context.new_page();page.goto(url);boot_frozen(page);meta=page.evaluate(TRI_SCENE,mode)
    for variant in ['bold','thin','cross','chevron','off']:
     key=f'{mode}-{variant}';page.evaluate('v=>{STYLE.dangerHatch.variant=v;draw()}',variant)
     im=decoded(page.evaluate('canvas.toDataURL()'));im.save(out/f'{phase}-{key}.png');captures[phase,key]=np.array(im)
     # The off scene preserves all borders, harmless objects, glow and trails.
     if phase=='after' and variant=='off':
      assert np.array_equal(captures['before',key],np.array(im)),key
    for kind in ['trail','glow']:
     im=decoded(page.evaluate(TRI_ISOLATE,kind));controls[phase,mode,kind]=np.array(im)
     if phase=='after':assert np.array_equal(controls['before',mode,kind],np.array(im)),kind
    if phase=='after':
     # Allowed interior bounds, expanded one backing pixel for clip AA.
     shape=captures[phase,f'{mode}-bold'].shape[:2];yy,xx=np.indices(shape);mask=triangle_clip(meta,shape) if mode=='bad' else np.zeros(shape,bool)
     rects=page.evaluate('[hatchFixture.cube,hatchFixture.orange].map(o=>[o.x,o.y,o.width,o.height])')
     z=meta['u']*meta['backing'][0]/meta['width']
     for x,y,w,h in rects:
      inset=max(2,min(w,h)*.2);mask|=(xx>=(x+inset)*z-1)&(xx<=(x+w-inset)*z+1)&(yy>=(y+inset)*z-1)&(yy<=(y+h-inset)*z+1)
     for v in ['bold','thin','cross','chevron']:
      diff=np.any(captures[phase,f'{mode}-{v}']!=captures['before',f'{mode}-{v}'],axis=2)
      outside=int((diff&~mask).sum());assert outside==0,(mode,v,outside)
      report['scenes'][f'{mode}-{v}']={'outsideInteriorDifferences':outside}
     print(f'PASS {mode}: all variants outside hatch interiors=0; off/border/harmless/glow/trail controls=0',flush=True)
     if mode=='bad':
      r=page.evaluate(PROBE)
      variant_images=r.pop('variants');r['variants']={}
      for v,imgs in variant_images.items():
       r['variants'][v]=[]
       for n,data in enumerate(imgs):
        a=np.array(decoded(data));decoded(data).save(out/f'isolated-{v}-{n}.png')
        assert (a[:,:,3].sum()==0)==(v=='off'),(v,n)
        r['variants'][v].append({'object':n,'coveredPixels':int((a[:,:,3]>0).sum())})
        if v!='off':
         rgb=np.unique(a[:,:,:3][a[:,:,3]==255],axis=0).tolist()
         expected=[[153,80,28] if v=='bold' else [181,96,32],[28,80,153],[153,27,89],[153,37,68]][n]
         assert rgb==[expected],(v,n,rgb)
         r['variants'][v][-1]['opaqueRGB']=rgb
      for pair in r.pop('motion'):
       a,b=[np.array(decoded(x)) for x in pair];b=np.roll(b,(-5,-3),(0,1));assert np.array_equal(a,b),'local motion'
      r['fractionalMotionRegisteredDifferences']=[0,0,0,0]
      assert r['instrumentation']=={'draws':60,'tiles':0,'patterns':0},r
      assert r['state'] and r['clipOutsideAlpha']==0,r
      for v,counts in r['bounds'].items():assert counts[0]==counts[1] and counts[0]<1000,(v,counts)
      for v,g in r['geometry'].items():
       assert g['width']=={'bold':9,'thin':2,'cross':3,'chevron':3}[v]
       starts=g['starts'];assert len(starts)>2
       assert starts[1][0]-starts[0][0]==32,(v,starts)
      report['focused']=r
      print('PASS four variants: original RGB, 32-unit spacing, widths 9/2/3/3, off empty; fractional local motion exact',flush=True)
      print('PASS 60 warmed draws: tiles=0 patterns=0; enlarged offscreen bounds bounded; transform/alpha/clip/current triangle path preserved',flush=True)
    context.close()
 for mode in ['bad','classic']:
  for v in ['bold','thin','cross','chevron']:
   pair=[Image.open(out/f'{p}-{mode}-{v}.png').convert('RGB') for p in ['before','after']]
   row=Image.new('RGB',(pair[0].width*2,pair[0].height+24));ImageDraw.Draw(row).text((4,4),f'{mode} {v}: before / after',fill='white')
   for i,im in enumerate(pair):row.paste(im,(i*im.width,24))
   rows.append(row)
 sheet=Image.new('RGB',(rows[0].width,sum(i.height for i in rows)))
 y=0
 for row in rows:sheet.paste(row,(0,y));y+=row.height
 sheet.save(out/'before-after.png');report['pass']=True
 (out/'render-checks.json').write_text(json.dumps(report,indent=2)+'\n')
 print('PASS render-checks.json: all focused assertions passed',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=ROOT/'artifacts/TASK-440');main(p.parse_args().out)
