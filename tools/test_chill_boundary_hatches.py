"""Baseline-controlled production Chill strips, collisions, phase and cache probes."""
from contextlib import ExitStack
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
from test_obstacle_hatches import decoded, CACHE

ROOT = Path(__file__).resolve().parents[1]
SETUP = r'''mode => {
    startGame(mode); screen.x=screen.y=0;screen.leftWall.update(screen);
    window.strips=[floors[0],floors[floors.length-1]];
    draw();draw();
    return {mode,width,height,u:scale[version],backing:[canvas.width,canvas.height],
        clock:performance.now(),camera:[screen.x,screen.y],
        bounds:strips.map(f=>f.getContinuousSurfaceBounds()),
        geometry:strips.map(f=>f.elements.map(e=>e.getPoints())),
        hudClearTop:height/scale[version]*STYLE.ui.hudClearTopRatio};
}'''
# Invoke the actual production strip renderer on a transparent backing store.
ISOLATE = r'''kind => {
    const original=ctx,c=document.createElement('canvas');c.width=canvas.width;c.height=canvas.height;
    try {ctx=c.getContext('2d');ctx.setTransform(original.getTransform());ctx.scale(scale[version],scale[version]);
        for(const f of strips) {
            if(kind==='body')f.draw();
            else if(kind==='split') {
                const b=f.getContinuousSurfaceBounds();
                for(const e of f.elements)f.drawClassicBoundaryHatch({...b,left:e.getLeftPointX(),right:e.getRightPointX()});
            } else {
                const b=f.getContinuousSurfaceBounds();
                f.drawClassicBoundaryHatch(kind==='reference'?{...b,left:b.left-100,right:b.right+100}:b);
            }
        }
        return c.toDataURL();
    }finally {ctx=original}
}'''
COLLISIONS = r'''mode => {
    const results=[];
    for(const which of [0,2])for(const offset of [-.5,0,.5]) {
        startGame(mode);floors[1].elements=[];
        const f=floors[which],b=f.getContinuousSurfaceBounds();
        const seam=f.elements.find(e=>e.getRightPointX()>width*.3/scale[version]).getRightPointX();
        const lower=b.boundaryY===b.top;
        ninja.x=seam+offset;ninja.y=b.boundaryY+(lower?-1:1)*ninja.radius*.75;
        ninja.speedX=0;ninja.speedY=lower?4:-4;
        const old=ninja,hit=ninja.collision();
        results.push({which,offset,hit:!!hit,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,
            samePlayer:old===ninja,frozen:isRunFrozen()});
    }
    return results;
}'''


def pixels(page, kind):
    return np.array(decoded(page.evaluate(ISOLATE, kind)))


class ChillBoundaryTests(unittest.TestCase):
    def test_boundaries_baseline_controls_motion_collision_and_cache(self):
        base=os.environ['CHILL_BOUNDARY_BASE_REV']
        out=ROOT/os.environ.get('CHILL_BOUNDARY_EVIDENCE_DIR','artifacts/TASK-233')
        out.mkdir(parents=True,exist_ok=True)
        settings={};results={};images={};controls={};bodies={};contacts={};native={}
        for phase,rev in [('baseline',base),('final','worktree')]:
            with ExitStack() as stack:
                root,_=export_rev(rev,stack.callback)
                url,browser=start_browser_test(root,stack.callback)
                for mode in ['classic','bad']:
                    for label,w,h in [('desktop',1920,1080),('phone',844,390)]:
                        name=f'{mode}-{label}';key=f'{phase}-{name}'
                        context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=1,
                            is_mobile=label=='phone',has_touch=label=='phone')
                        try:
                            context.add_init_script(SEED_SCRIPT%1);context.add_init_script(CLOCK_SCRIPT)
                            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(url);boot_frozen(page);meta=page.evaluate(SETUP,mode);settings[key]=meta
                            native[key]=Image.open(io.BytesIO(page.screenshot(path=str(out/f'{key}.png')))).convert('RGB')
                            images[key]=np.array(decoded(page.evaluate('canvas.toDataURL()')))
                            bodies[key]=pixels(page,'body')
                            Image.fromarray(bodies[key]).save(out/f'{key}-bodies.png')
                            # Whole scene with only boundary draw/glow suppressed: includes left wall,
                            # obstacles, HUD and lights, with exactly the same seeded game state.
                            page.evaluate('strips.forEach(f=>{f.saved=f.elements;f.elements=[]});draw()')
                            controls[key]=np.array(decoded(page.evaluate('canvas.toDataURL()')))
                            page.screenshot(path=str(out/f'{key}-controls.png'))
                            page.evaluate('strips.forEach(f=>f.elements=f.saved);draw()')
                            if phase=='final':
                                prior='baseline-'+name;r=results[name]={}
                                self.assertEqual(meta,settings[prior]);r['geometryAndHudClearanceMatch']=True
                                r['controlDifferentPixels']=int(np.any(controls[key]!=controls[prior],axis=2).sum())
                                self.assertEqual(r['controlDifferentPixels'],0)
                                r['cache']=page.evaluate(CACHE)
                                self.assertEqual(r['cache']['patterns'],0);self.assertEqual(r['cache']['tiles'],0)
                                if mode=='bad':
                                    r['mainSceneDifferentPixels']=int(np.any(images[key]!=images[prior],axis=2).sum())
                                    r['mainBoundaryDifferentPixels']=int(np.any(bodies[key]!=bodies[prior],axis=2).sum())
                                    self.assertEqual(r['mainSceneDifferentPixels'],0);self.assertEqual(r['mainBoundaryDifferentPixels'],0)
                                else:
                                    a=pixels(page,'hatch');Image.fromarray(a).save(out/f'{key}-hatches.png')
                                    sy=meta['backing'][1]/meta['height']*meta['u'];sx=meta['backing'][0]/meta['width']*meta['u']
                                    yy,xx=np.indices(a.shape[:2]);allowed=np.zeros(a.shape[:2],bool);r['boundaries']=[]
                                    for b in meta['bounds']:
                                        inset=page.evaluate('b=>Math.max(STYLE.strokes.neonGlowWidth,(b.bottom-b.top)*.20)',b)
                                        mask=(yy>=int((b['top']+inset)*sy)-1)&(yy<=int(np.ceil((b['bottom']-inset)*sy))+1)
                                        allowed|=mask
                                        coverage=int(((a[:,:,3]>0)&mask).sum())
                                        bodymask=(yy>int(b['top']*sy)+2)&(yy<int(b['bottom']*sy)-2)
                                        rgb=bodies[key][:,:,:3]
                                        fill=int((np.all(rgb==[38,22,8],axis=2)&bodymask).sum())
                                        stripe=int((np.all(rgb==[153,80,28],axis=2)&bodymask).sum())
                                        edgeMask=(rgb[:,:,0]>200)&(rgb[:,:,1]>80)&(rgb[:,:,1]<200)&(rgb[:,:,2]<80)&(abs(yy-b['boundaryY']*sy)<8)
                                        edge=int(edgeMask.sum())
                                        edgeRGB=np.unique(rgb[edgeMask],axis=0).tolist()
                                        green=int(((rgb[:,:,1]>rgb[:,:,0]*1.3)&(rgb[:,:,1]>100)&bodymask).sum())
                                        r['boundaries'].append({'bounds':b,'stripePixels':coverage,'darkOrangeFillPixels':fill,
                                            'orangeHatchPixels':stripe,'orangeEdgePixels':edge,'renderedEdgeRGB':edgeRGB,'greenPixels':green})
                                        self.assertGreater(coverage,100);self.assertGreater(fill,100);self.assertGreater(stripe,100)
                                        self.assertGreater(edge,10);self.assertEqual(green,0)
                                    r['leakedHatchPixels']=int(((a[:,:,3]>0)&~allowed).sum());self.assertEqual(r['leakedHatchPixels'],0)
                                    hud=page.evaluate('''() => {
                                        const vw=width/scale[version],vh=height/scale[version],font=getHudFontSize(vw,vh,version);
                                        ctx.save();ctx.font=font+'px '+scoreText.fontFamily;
                                        const boxes=[[vw*.03,getHudCenterY(vh,version)-font/2,ctx.measureText(scoreText.text+scoreText.count[version]).width,font],
                                            [scoreText.getRecordX(vw)-ctx.measureText(scoreText.rtext+scoreText.record[version]).width,getHudCenterY(vh,version)-font/2,ctx.measureText(scoreText.rtext+scoreText.record[version]).width,font]];
                                        const m=menu.button.background;boxes.push([m.x,m.y,m.width,m.height]);ctx.restore();return boxes;
                                    }''')
                                    hudMask=np.zeros(a.shape[:2],bool)
                                    for x,y,bw,bh in hud:
                                        hudMask|=(xx>=np.ceil(x*sx))&(xx<np.floor((x+bw)*sx))&(yy>=np.ceil(y*sy))&(yy<np.floor((y+bh)*sy))
                                    r['hudHatchPixels']=int(((a[:,:,3]>0)&hudMask).sum());self.assertEqual(r['hudHatchPixels'],0)
                                    r['variants']={}
                                    for variant in ['off','thin','cross','chevron','bold']:
                                        page.evaluate('v=>STYLE.dangerHatch.variant=v',variant)
                                        count=int((pixels(page,'hatch')[:,:,3]>0).sum());r['variants'][variant]=count
                                        if variant=='off':self.assertEqual(count,0)
                                        else:self.assertGreater(count,100)
                                    r['motionAndSeams']=[]
                                    # Move a real generated segment join into the viewport, then move
                                    # by integral backing pixels at fractional world camera positions.
                                    seam=page.evaluate('strips[0].elements[1].getLeftPointX()')
                                    origin=meta['width']*.5/meta['u']-seam+.375
                                    ref=None
                                    for i in range(3):
                                        camera=origin+i*7/sx
                                        page.evaluate('x=>{screen.x=x;screen.leftWall.update(screen);draw()}',camera)
                                        page.screenshot(path=str(out/f'{key}-motion-seam-{i}.png'))
                                        actual=pixels(page,'hatch');split=pixels(page,'split')
                                        Image.fromarray(actual).save(out/f'{key}-motion-seam-{i}-hatches.png')
                                        # Independently clipping adjoining pieces introduces AA at the
                                        # split column; production draws one uninterrupted strip.
                                        # Compare segment interiors, then compare the actual join to
                                        # an extended, unsegmented world-pattern reference exactly.
                                        join=int((seam+camera)*sx)
                                        interior=np.ones(actual.shape[1],bool)
                                        for worldX in page.evaluate('strips.flatMap(f=>f.elements.map(e=>e.getLeftPointX()))'):
                                            column=int((worldX+camera)*sx)
                                            if 0<=column<actual.shape[1]:interior[max(0,column-2):column+3]=False
                                        # Premultiply before comparing antialiased transparent pixels.
                                        def premult(im):
                                            im=im.astype(int).copy();im[:,:,:3]=(im[:,:,:3]*im[:,:,3:4]+127)//255
                                            return im
                                        seam_delta=int(abs(premult(actual)[:,interior]-premult(split)[:,interior]).max())
                                        self.assertLessEqual(seam_delta,16)
                                        reference=pixels(page,'reference')
                                        join_delta=int(abs(actual[:,join-2:join+3].astype(int)-reference[:,join-2:join+3].astype(int)).max())
                                        self.assertEqual(join_delta,0)
                                        if ref is None:ref=actual
                                        registered=np.roll(actual,-i*7,axis=1)
                                        delta=int(abs(premult(registered)[:,int(actual.shape[1]*.35):int(actual.shape[1]*.65)]-premult(ref)[:,int(actual.shape[1]*.35):int(actual.shape[1]*.65)]).max())
                                        self.assertLessEqual(delta,16)
                                        join=int((seam+camera)*sx)
                                        seam_coverage=int((actual[:,join-2:join+3,3]>0).sum())
                                        self.assertGreater(seam_coverage,0)
                                        r['motionAndSeams'].append({'cameraX':camera,'shiftPixels':i*7,'maxRegisteredDelta':delta,
                                            'segmentInteriorMaxDelta':seam_delta,'joinVsWorldReferenceDelta':join_delta,'seamStripePixels':seam_coverage})
                            contacts[key]=page.evaluate(COLLISIONS,mode)
                            self.assertTrue(all(c['hit'] for c in contacts[key]),contacts[key])
                            if phase=='final':
                                self.assertEqual(contacts[key],contacts['baseline-'+name])
                                results[name]['collisionOutcomes']=contacts[key];results[name]['collisionBaselineMatch']=True
                                print(f'PASS {name}: geometry/collisions/HUD match baseline; controls=0; warm patterns=0 tiles=0; '+
                                    ('orange floor/ceiling, clipped hatches, variants/off, fractional motion and segment seams' if mode=='classic' else 'Main scene and boundaries pixel-identical'),flush=True)
                            self.assertFalse(errors,errors)
                        finally:context.close()
        rows=[]
        for label in ['desktop','phone']:
            pair=[native[f'{phase}-classic-{label}'] for phase in ['baseline','final']]
            row=Image.new('RGB',(sum(p.width for p in pair),pair[0].height+24));x=0
            for phase,p in zip(['baseline','final'],pair):
                row.paste(p,(x,24));ImageDraw.Draw(row).text((x+4,4),f'{label} {phase}',fill='white');x+=p.width
            rows.append(row)
        sheet=Image.new('RGB',(max(r.width for r in rows),sum(r.height for r in rows)));y=0
        for row in rows:sheet.paste(row,(0,y));y+=row.height
        sheet.save(out/'before-after.png')
        (out/'measurements.json').write_text(json.dumps(results,indent=2)+'\n')
        files=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
        files=[f for f in files if f.endswith(('.js','.html'))]+['tools/test_chill_boundary_hatches.py']
        manifest={'baseline':base,'final':'worktree source hashes','sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
            'settings':settings,'cameraMotion':{k:v.get('motionAndSeams',[]) for k,v in results.items()},'seed':1,'dpr':1,'evidence':[str(p.relative_to(ROOT)) for p in sorted(out.glob('*.png'))]+['artifacts/TASK-233/measurements.json','artifacts/TASK-233/tests.log']}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('PASS all four mode/viewport probes; no skipped visual or behavioral probes',flush=True)
