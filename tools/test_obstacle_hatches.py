"""Rendered obstacle hatches: native scenes, exact controls, motion and cache."""
from contextlib import ExitStack
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
from render_snapshot import CLOCK_SCRIPT, boot_frozen

ROOT = Path(__file__).resolve().parents[1]
SCENE = r'''mode => {
    startGame(mode); screen.x=screen.y=0;
    for (const f of floors) f.elements=[];
    const u=scale[version];
    const cube=new JumpingCube({x:width*.36/u,y:height*.4/u,width:180,height:180,
        stroke:STYLE.colors.cube.blueStroke,speedX:2,speedY:1});
    cube.x=width*.36/u;cube.y=height*.4/u;cube.track.pos=[];
    cube.track.addPos(cube.x+90-80,cube.y+90-35,true);
    cube.track.addPos(cube.x+90,cube.y+90);
    const orange=new Rect({x:width*.62/u,y:height*.4/u,width:180,height:180,isDangerRect:true});
    const green=new Rect({x:width*.18/u,y:height*.4/u,width:130,height:130,stroke:STYLE.colors.cube.greenStroke});
    const tri=new Triangle({x:width*.83/u,y:height*.48/u,radius:65,stroke:STYLE.colors.hazard.classicTriangleStroke,yMin:0,yMax:height/u});
    floors[1].elements=[cube,orange,green,tri];ninja.x=width*.1/u;ninja.y=height*.7/u;
    window.hatchFixture={cube,orange,green,tri,u};draw();draw();
    return {width,height,u,backing:[canvas.width,canvas.height],camera:[screen.x,screen.y],
        clock:performance.now(),cube:[cube.x,cube.y,cube.width,cube.height],
        canvasBounds:canvas.getBoundingClientRect().toJSON()};
}'''
MOTION = r'''i => {
    const {cube,u}=hatchFixture;
    cube.move();
    // Actual physics motion plus fractional camera movement; net backing shift
    // is integral so registered samples can be compared without resampling.
    screen.x=i*7/(u*canvas.width/width)-(cube.x-hatchFixture.startX);
    screen.y=i*5/(u*canvas.height/height)-(cube.y-hatchFixture.startY);
    draw();return {cube:[cube.x,cube.y],camera:[screen.x,screen.y],shift:[i*7,i*5]};
}'''
ISOLATE = r'''() => {
    const {cube}=hatchFixture;
    const original=ctx, scratch=document.createElement('canvas');
    scratch.width=canvas.width;scratch.height=canvas.height;
    try {ctx=scratch.getContext('2d');ctx.setTransform(original.getTransform());ctx.scale(scale[version],scale[version]);
        cube.drawDangerHatch(cube.x+screen.x,cube.y+screen.y);
        return scratch.toDataURL();
    }finally{ctx=original}
}'''
CACHE = r'''() => {
    const contexts=[document.createElement('canvas').getContext('2d'),document.createElement('canvas').getContext('2d')];
    const variants=['bold','thin','cross','chevron'];const colours=['#1c5099','#99501c','#8fdcff'];
    const entries=[];
    for(const c of contexts)for(const v of variants)for(const colour of colours)
        entries.push(dangerHatchPattern(c,v,colour));
    const distinct=new Set(entries).size;
    let patterns=0,tiles=0;
    const cp=CanvasRenderingContext2D.prototype.createPattern,ce=document.createElement;
    CanvasRenderingContext2D.prototype.createPattern=function(...a){patterns++;return cp.apply(this,a)};
    document.createElement=function(...a){if(a[0]==='canvas')tiles++;return ce.apply(this,a)};
    try {for(let i=0;i<60;i++){
        draw();for(const c of contexts)for(const v of variants)for(const colour of colours)dangerHatchPattern(c,v,colour);
    }}finally{CanvasRenderingContext2D.prototype.createPattern=cp;document.createElement=ce}
    return {frames:60,patterns,tiles,distinct,expectedEntries:contexts.length*variants.length*colours.length};
}'''


def decoded(data):
    return Image.open(io.BytesIO(base64.b64decode(data.split(',')[1]))).convert('RGBA')


class ObstacleHatchTests(unittest.TestCase):
    def test_rendered_hatches_controls_motion_and_cache(self):
        out=ROOT/os.environ.get('HATCH_EVIDENCE_DIR','artifacts/TASK-229')/'cube-regression'
        out.mkdir(parents=True,exist_ok=True)
        # Retain TASK-228's pre-cube baseline and every original cube assertion.
        base='2b7ba0d8017236ee0ec3b905f1b4cfa2b9283f04'
        measurements={};settings={};pictures={};native={}
        for phase,rev in [('baseline',base),('final','worktree')]:
            with ExitStack() as stack:
                root,_=export_rev(rev,stack.callback);url,browser=start_browser_test(root,stack.callback)
                for mode in ['bad','classic']:
                    for label,w,h in [('desktop',1920,1080),('phone',844,390)]:
                        name=f'{mode}-{label}';key=f'{phase}-{name}'
                        context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=1,
                            is_mobile=label=='phone',has_touch=label=='phone')
                        try:
                            context.add_init_script(SEED_SCRIPT%1);context.add_init_script(CLOCK_SCRIPT)
                            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(url);boot_frozen(page);meta=page.evaluate(SCENE,mode);settings[key]=meta
                            if phase=='final':self.assertEqual(meta,settings['baseline-'+name])
                            native[key]=Image.open(io.BytesIO(page.screenshot(path=str(out/f'{key}.png')))).convert('RGB')
                            full=decoded(page.evaluate('canvas.toDataURL()'));full.save(out/f'{key}-backing.png');pictures[key]=np.array(full).astype(int)
                            # Hide only the cube: orange, triangle, green, lighting and cave controls.
                            page.evaluate('hatchFixture.saved=floors[1].elements;floors[1].elements=hatchFixture.saved.slice(1);draw()')
                            control=decoded(page.evaluate('canvas.toDataURL()'));pictures[key+'-control']=np.array(control)
                            page.screenshot(path=str(out/f'{key}-control.png'))
                            page.evaluate('floors[1].elements=hatchFixture.saved;draw()')
                            if phase=='final':
                                r=measurements[name]={}
                                r['cache']=page.evaluate(CACHE)
                                self.assertEqual(r['cache']['patterns'],0);self.assertEqual(r['cache']['tiles'],0)
                                self.assertEqual(r['cache']['distinct'],24)
                                isolated=decoded(page.evaluate(ISOLATE));isolated.save(out/f'{key}-stripes.png')
                                a=np.array(isolated);u=meta['u'];x,y,cw,ch=meta['cube'];inset=max(2,min(cw,ch)*.2)
                                sx=meta['backing'][0]/meta['width'];sy=meta['backing'][1]/meta['height']
                                bounds=[(x+inset)*u*sx,(y+inset)*u*sy,(x+cw-inset)*u*sx,(y+ch-inset)*u*sy]
                                yy,xx=np.indices(a.shape[:2]);clip=(xx>=int(bounds[0])-1)&(xx<=int(np.ceil(bounds[2]))+1)&(yy>=int(bounds[1])-1)&(yy<=int(np.ceil(bounds[3]))+1)
                                r['stripePixels']=int((a[:,:,3]>0).sum());r['leakedPixels']=int(((a[:,:,3]>0)&~clip).sum())
                                opaque=a[:,:,3]==255;r['opaqueRGB']=np.unique(a[:,:,:3][opaque],axis=0).tolist()
                                self.assertGreater(r['stripePixels'],100);self.assertEqual(r['leakedPixels'],0)
                                self.assertEqual(r['opaqueRGB'],[[28,80,153]])
                                # Production scene differences must be confined to the same inset.
                                diff=np.any(pictures[key]!=pictures['baseline-'+name],axis=2)
                                r['sceneChangedPixels']=int(diff.sum());r['sceneChangesOutsideInset']=int((diff&~clip).sum())
                                self.assertGreater(r['sceneChangedPixels'],100);self.assertEqual(r['sceneChangesOutsideInset'],0)
                                r['controlDifferentPixels']=int(np.any(pictures[key+'-control']!=pictures['baseline-'+name+'-control'],axis=2).sum())
                                self.assertEqual(r['controlDifferentPixels'],0)
                                # Off disables the actual hatch output.
                                page.evaluate("STYLE.dangerHatch.variant='off'")
                                r['offAlphaPixels']=int((np.array(decoded(page.evaluate(ISOLATE)))[:,:,3]>0).sum())
                                self.assertEqual(r['offAlphaPixels'],0)
                                page.evaluate("STYLE.dangerHatch.variant='bold';hatchFixture.startX=hatchFixture.cube.x;hatchFixture.startY=hatchFixture.cube.y")
                                r['motion']=[]
                                for i in [1,2,3]:
                                    motion=page.evaluate(MOTION,i);page.screenshot(path=str(out/f'{key}-motion-{i}.png'))
                                    m=decoded(page.evaluate(ISOLATE));m.save(out/f'{key}-motion-{i}-stripes.png')
                                    registered=np.roll(np.array(m),(-i*5,-i*7),axis=(0,1)).astype(int)
                                    # Compare premultiplied RGB: unpremultiplication amplifies tiny
                                    # edge-alpha rounding into misleading colour differences.
                                    reference=a.astype(int).copy()
                                    registered[:,:,:3]=(registered[:,:,:3]*registered[:,:,3:4]+127)//255
                                    reference[:,:,:3]=(reference[:,:,:3]*reference[:,:,3:4]+127)//255
                                    delta=abs(registered-reference);motion['maxRegisteredDelta']=int(delta.max())
                                    edge=((reference[:,:,3]>0)&(reference[:,:,3]<255))|((registered[:,:,3]>0)&(registered[:,:,3]<255))
                                    # Browser subpixel quantization may differ by 1/16 coverage
                                    # on AA edges; solid stripe and empty pixels remain exact.
                                    motion['aaAllowance']=16
                                    motion['pixelsOverAAAllowance']=int((np.any(delta>16,axis=2)|(np.any(delta>0,axis=2)&~edge)).sum())
                                    self.assertEqual(motion['pixelsOverAAAllowance'],0,motion);r['motion'].append(motion)
                                # All selectors retain the orange geometry for blue, with separate colours.
                                r['variants']={}
                                for variant in ['bold','thin','cross','chevron']:
                                    page.evaluate('v=>{STYLE.dangerHatch.variant=v;screen.x=screen.y=0;hatchFixture.cube.x=hatchFixture.startX;hatchFixture.cube.y=hatchFixture.startY}',variant)
                                    blue=np.array(decoded(page.evaluate(ISOLATE)))
                                    page.evaluate('hatchFixture.cube.hatchColour=undefined;hatchFixture.cube.isDangerRect=true')
                                    orange=np.array(decoded(page.evaluate(ISOLATE)))
                                    r['variants'][variant]={'alphaDifferences':int((blue[:,:,3]!=orange[:,:,3]).sum()),'coveredPixels':int((blue[:,:,3]>0).sum())}
                                    self.assertEqual(r['variants'][variant]['alphaDifferences'],0);self.assertGreater(r['variants'][variant]['coveredPixels'],0)
                                    page.evaluate("hatchFixture.cube.isDangerRect=false;hatchFixture.cube.hatchColour='#1c5099'")
                                print(f'PASS {name}: rendered RGB [28, 80, 153]; coverage={r["stripePixels"]}; outside inset=0; controls=0; off=0; 3 registered motion frames; 60 warm draws patterns=0 tiles=0; 24 distinct context/variant/colour entries',flush=True)
                            self.assertFalse(errors,errors)
                        finally:context.close()
        rows=[]
        for name in measurements:
            pair=[]
            for phase in ['baseline','final']:
                im=native[f'{phase}-{name}'];meta=settings[f'{phase}-{name}'];b=meta['canvasBounds'];u=meta['u'];x,y,cw,ch=meta['cube'];s=b['width']/meta['width'];t=b['height']/meta['height']
                crop=im.crop((int(b['x']+(x*u-30)*s),int(b['y']+(y*u-30)*t),int(b['x']+((x+cw)*u+30)*s),int(b['y']+((y+ch)*u+30)*t)))
                pair.append(crop)
            row=Image.new('RGB',(max(520,sum(i.width for i in pair)),max(i.height for i in pair)+24));dx=0
            for phase,im in zip(['baseline','final'],pair):
                row.paste(im,(dx,24));ImageDraw.Draw(row).text((dx,4),f'{name} {phase}',fill='white');dx+=max(im.width,240)
            rows.append(row)
        sheet=Image.new('RGB',(max(i.width for i in rows),sum(i.height for i in rows)));dy=0
        for row in rows:sheet.paste(row,(0,dy));dy+=row.height
        sheet.save(out/'before-after.png')
        (out/'measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
        files=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
        files=[f for f in files if f.endswith(('.js','.html'))]+['tools/test_obstacle_hatches.py']
        manifest={'baseline':base,'final':'worktree hashes','sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
            'settings':settings,'seed':1,'dpr':1,'evidence':[str(p.relative_to(ROOT)) for p in sorted(out.iterdir()) if p.is_file()]}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('PASS all four mode/viewport probes completed; no skipped probes; all four hatch variants match orange alpha geometry',flush=True)


TRI_SCENE = SCENE.replace('window.hatchFixture={cube,orange,green,tri,u};', '''
    // Construct with each actual hazard colour, including a red harmless control.
    const pink=new Triangle({x:width*.45/u,y:height*.48/u,radius:100,
        stroke:STYLE.colors.hazard.stroke,yMin:0,yMax:height/u});
    const red=new Triangle({x:width*.8/u,y:height*.48/u,radius:100,
        stroke:STYLE.colors.hazard.red,yMin:0,yMax:height/u});
    const harmless=new HarmlessTriangle({x:width*.18/u,y:height*.7/u,radius:70,
        stroke:STYLE.colors.hazard.stroke,yMin:0,yMax:height/u});
    cube.y=height*.7/u;orange.y=height*.7/u;
    for(const t of [pink,red]){t.y-=40;t.track.addPos(t.getPoints(),true);t.y+=40;t.track.addPos(t.getPoints(),true)}
    floors[1].elements=[pink,red,cube,orange,green,tri,harmless];
    window.hatchFixture={cube,orange,green,tri,pink,red,harmless,u};''').replace(
        'canvasBounds:canvas', '''triangles:[pink,red].map(t=>({x:t.x,y:t.y,side:t.side,height:t.height,
        stroke:t.stroke,innerScale:STYLE.badVersionEffects.obstacles.hazardInnerScale})),
        canvasBounds:canvas''')
TRI_ISOLATE = r'''kind => {
    const original=ctx,lightOriginal=visualEffects.lightmap.ctx,scratch=document.createElement('canvas');
    scratch.width=canvas.width;scratch.height=canvas.height;
    try {ctx=scratch.getContext('2d');ctx.setTransform(original.getTransform());ctx.scale(scale[version],scale[version]);
        if(kind==='stripes') {
            ctx.stroke=()=>{};
            if(version==='bad')for(const t of [hatchFixture.pink,hatchFixture.red])t.drawBadVersionInnerTreatment();
        } else if(kind==='trail') {
            for(const t of [hatchFixture.pink,hatchFixture.red])t.track.draw();
        } else if(kind==='glow') {
            bloomPassActive=true;
            for(const t of [hatchFixture.pink,hatchFixture.red])t.draw();
        } else {visualEffects.lightmap.ctx=ctx;visualEffects.lightmap.clear();visualEffects.lightmap.draw(visualEffects.getGameState());visualEffects.lightmap.composite();}
        return scratch.toDataURL();
    }finally{ctx=original;visualEffects.lightmap.ctx=lightOriginal;bloomPassActive=false}
}'''
TRI_MOTION = r'''i => {
    const {pink,red,u}=hatchFixture;
    for(const t of [pink,red]){t.speedY=1.25;t.move()}
    screen.x=i*7/(u*canvas.width/width);
    screen.y=i*5/(u*canvas.height/height)-i*1.25;
    draw();return {positions:[pink,red].map(t=>[t.x,t.y]),camera:[screen.x,screen.y],shift:[i*7,i*5]};
}'''


def triangle_clip(meta, shape):
    yy,xx=np.indices(shape);xx=xx+.5;yy=yy+.5
    mask=np.zeros(shape,dtype=bool)
    for t in meta['triangles']:
        sx=meta['u']*meta['backing'][0]/meta['width'];sy=meta['u']*meta['backing'][1]/meta['height']
        cx=t['x']*sx;top=(t['y']-t['height']/3*t['innerScale'])*sy
        bottom=(t['y']+t['height']*2/3*t['innerScale'])*sy
        half=t['side']/2*t['innerScale']*sx
        # Distance <= one backing pixel from each exact inner-triangle edge.
        slope=half/(bottom-top)
        mask|=(yy>=top-1)&(np.abs(xx-cx)+slope*(yy-top)<=half+np.sqrt(1+slope*slope))
    return mask


class TriangleHatchTests(unittest.TestCase):
    def test_triangles_rendered_controls_motion_cache(self):
        out=ROOT/os.environ.get('HATCH_EVIDENCE_DIR','artifacts/TASK-229');out.mkdir(parents=True,exist_ok=True)
        base=os.environ.get('HATCH_BASE_REV') or (out/'BASE_REV').read_text().strip()
        measurements={};settings={};pictures={};native={};rows=[]
        for phase,rev in [('baseline',base),('final','worktree')]:
            with ExitStack() as stack:
                root,_=export_rev(rev,stack.callback);url,browser=start_browser_test(root,stack.callback)
                for mode in ['bad','classic']:
                    for label,w,h in [('desktop',1920,1080),('phone',844,390)]:
                        name=f'{mode}-{label}';key=f'{phase}-{name}'
                        context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=1,is_mobile=label=='phone',has_touch=label=='phone')
                        try:
                            context.add_init_script(SEED_SCRIPT%1);context.add_init_script(CLOCK_SCRIPT)
                            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(url);boot_frozen(page);meta=page.evaluate(TRI_SCENE,mode);settings[key]=meta
                            if phase=='final':self.assertEqual(meta,settings['baseline-'+name])
                            native[key]=Image.open(io.BytesIO(page.screenshot(path=str(out/f'{key}.png')))).convert('RGB')
                            full=decoded(page.evaluate('canvas.toDataURL()'));full.save(out/f'{key}-backing.png');pictures[key]=np.array(full).astype(int)
                            page.evaluate('hatchFixture.saved=floors[1].elements;floors[1].elements=hatchFixture.saved.slice(2);draw()')
                            controls={'objects':np.array(decoded(page.evaluate('canvas.toDataURL()')))}
                            page.screenshot(path=str(out/f'{key}-control.png'))
                            page.evaluate('floors[1].elements=hatchFixture.saved;draw()')
                            for kind in ['trail','glow','light']:
                                im=decoded(page.evaluate(TRI_ISOLATE,kind));im.save(out/f'{key}-{kind}.png');controls[kind]=np.array(im)
                            pictures[key+'-controls']=controls
                            if phase=='final':
                                r=measurements[name]={};r['controls']={k:int(np.any(v!=pictures['baseline-'+name+'-controls'][k],axis=2).sum()) for k,v in controls.items()}
                                self.assertTrue(all(v==0 for v in r['controls'].values()),r)
                                r['controlCoverage']={k:int((v[:,:,3]>0).sum()) for k,v in controls.items()}
                                self.assertTrue(all(v>0 for v in r['controlCoverage'].values()),r)
                                r['cache']=page.evaluate(CACHE.replace("'#8fdcff'","'#8fdcff','#991b59','#992544'"))
                                self.assertEqual(r['cache'],dict(frames=60,patterns=0,tiles=0,distinct=40,expectedEntries=40))
                                im=decoded(page.evaluate(TRI_ISOLATE,'stripes'));im.save(out/f'{key}-stripes.png');a=np.array(im)
                                clip=triangle_clip(meta,a.shape[:2]);r['stripePixels']=int((a[:,:,3]>0).sum());r['leakedPixels']=int(((a[:,:,3]>0)&~clip).sum())
                                r['opaqueRGB']=np.unique(a[:,:,:3][a[:,:,3]==255],axis=0).tolist()
                                diff=np.any(pictures[key]!=pictures['baseline-'+name],axis=2)
                                r['changedPixels']=int(diff.sum());r['outsideClip']=int((diff&~clip).sum())
                                self.assertEqual(r['leakedPixels'],0);self.assertEqual(r['outsideClip'],0)
                                if mode=='bad':
                                    self.assertGreater(r['stripePixels'],50);self.assertGreater(r['changedPixels'],50)
                                    self.assertEqual(r['opaqueRGB'],[[153,27,89],[153,37,68]])
                                else:self.assertEqual(r['stripePixels'],0);self.assertEqual(r['changedPixels'],0)
                                page.evaluate("STYLE.dangerHatch.variant='off'")
                                r['offPixels']=int((np.array(decoded(page.evaluate(TRI_ISOLATE,'stripes')))[:,:,3]>0).sum());self.assertEqual(r['offPixels'],0)
                                page.evaluate("STYLE.dangerHatch.variant='bold'");r['motion']=[]
                                for i in [1,2,3]:
                                    motion=page.evaluate(TRI_MOTION,i);page.screenshot(path=str(out/f'{key}-motion-{i}.png'))
                                    im=decoded(page.evaluate(TRI_ISOLATE,'stripes'));im.save(out/f'{key}-motion-{i}-stripes.png')
                                    reg=np.roll(np.array(im),(-i*5,-i*7),axis=(0,1)).astype(int);ref=a.astype(int).copy()
                                    for z in [reg,ref]:z[:,:,:3]=(z[:,:,:3]*z[:,:,3:4]+127)//255
                                    delta=abs(reg-ref);edge=((ref[:,:,3]>0)&(ref[:,:,3]<255))|((reg[:,:,3]>0)&(reg[:,:,3]<255))
                                    motion['maxRegisteredDelta']=int(delta.max());motion['pixelsOverAAAllowance']=int((np.any(delta>16,axis=2)|(np.any(delta>0,axis=2)&~edge)).sum())
                                    self.assertEqual(motion['pixelsOverAAAllowance'],0,motion);r['motion'].append(motion)
                                r['variants']={}
                                if mode=='bad':
                                    for variant in ['bold','thin','cross','chevron']:
                                        page.evaluate('v=>STYLE.dangerHatch.variant=v',variant)
                                        coloured=np.array(decoded(page.evaluate(TRI_ISOLATE,'stripes')))
                                        page.evaluate("for(const t of [hatchFixture.pink,hatchFixture.red]){t.savedColour=t.hatchColour;t.hatchColour='#99501c'}")
                                        orange=np.array(decoded(page.evaluate(TRI_ISOLATE,'stripes')))
                                        page.evaluate('for(const t of [hatchFixture.pink,hatchFixture.red])t.hatchColour=t.savedColour')
                                        r['variants'][variant]={'alphaDifferences':int((coloured[:,:,3]!=orange[:,:,3]).sum()),'coverage':int((coloured[:,:,3]>0).sum())}
                                        self.assertEqual(r['variants'][variant]['alphaDifferences'],0)
                                        self.assertGreater(r['variants'][variant]['coverage'],0)
                                print(f'PASS triangles {name}: coverage={r["stripePixels"]}; RGB={r["opaqueRGB"]}; outsideClip=0; objects/trail/glow/light=0; off=0; motion=3; warm draws=60 patterns=0 tiles=0 distinct=40',flush=True)
                            self.assertFalse(errors,errors)
                        finally:context.close()
        for name in measurements:
            row=Image.new('RGB',(960,210));d=ImageDraw.Draw(row)
            for n,phase in enumerate(['baseline','final']):
                key=f'{phase}-{name}';meta=settings[key];b=meta['canvasBounds'];u=meta['u'];sx=b['width']/meta['width'];sy=b['height']/meta['height']
                for j,t in enumerate(meta['triangles']):
                    cx=b['x']+t['x']*u*sx;cy=b['y']+t['y']*u*sy
                    crop=native[key].crop((int(cx-110),int(cy-70),int(cx+110),int(cy+125)))
                    row.paste(crop,(n*480+j*240,20));d.text((n*480+j*240,2),key+(' pink' if j==0 else ' red'),fill='white')
            rows.append(row)
        sheet=Image.new('RGB',(960,840))
        for i,row in enumerate(rows):sheet.paste(row,(0,i*210))
        sheet.save(out/'before-after.png')
        (out/'measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
        files=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
        files=[f for f in files if f.endswith(('.js','.html'))]+['tools/test_obstacle_hatches.py']
        manifest={'baseline':base,'sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},'settings':settings,'seed':1,'dpr':1,'evidence':[str(p.relative_to(ROOT)) for p in sorted(out.rglob('*')) if p.is_file()]}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('PASS triangles all four modes/viewports; no skipped probes',flush=True)




if __name__=='__main__':unittest.main()
