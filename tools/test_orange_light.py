"""Matched native danger-spill pixels, controls, masks and warm-cache costs."""
from contextlib import ExitStack
import colorsys
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
SCENE = r'''([mode, control]) => {
    startGame(mode); screen.x = screen.y = 0;
    for (const f of floors) f.elements = [];
    const u = scale[version];
    const rect = new Rect({x:width*.4/u,y:height*.4/u,
        width:width*.2/u,height:height*.16/u,isDangerRect:!control,
        ...(control ? {stroke:STYLE.colors.cube.greenStroke} : {})});
    const tri = new Triangle({x:width*.72/u,y:height*.44/u,
        radius:height*.05/u,yMin:0,yMax:height/u,
        stroke:STYLE.colors.hazard.harmlessStroke});
    floors[1].elements = control ? [rect,tri] : [rect];
    ninja.x = (width*.4-height*24/1080)/u; ninja.y = height*.48/u;
    draw(); draw();
    const b = canvas.getBoundingClientRect();
    window.orangeFixture = {rect,tri};
    return {width,height,u,backing:[canvas.width,canvas.height],
        bounds:b.toJSON(), camera:[screen.x,screen.y],clock:performance.now(),
        player:[(ninja.x*u)/width*b.width,(ninja.y*u)/height*b.height],
        radius:ninja.radius*u/height*b.height};
}'''
COST = r'''() => {
    const l=visualEffects.lightmap, restores=[], counts={gradients:0,canvases:0,
        shapeSprites:0,drawImage:0,lightDrawImage:0,composites:0,fullScreenDraws:0};
    const wrap=(o,n,fn)=>{const orig=o[n];o[n]=function(...a){fn.call(this,a);return orig.apply(this,a)};
        restores.push(()=>o[n]=orig)};
    const sizes=[l.shapeLights.size,l.gradients.size];
    wrap(document,'createElement',a=>{if(a[0]==='canvas')counts.canvases++});
    for(const n of ['createLinearGradient','createRadialGradient'])
        wrap(CanvasRenderingContext2D.prototype,n,()=>counts.gradients++);
    wrap(l.shapeLights,'set',()=>counts.shapeSprites++);
    wrap(l,'composite',()=>counts.composites++);
    wrap(CanvasRenderingContext2D.prototype,'drawImage',function(a){
        counts.drawImage++; if(this===l.lightCtx)counts.lightDrawImage++;
        const w=a.length===3?a[0].width:a[a.length-2];
        const h=a.length===3?a[0].height:a[a.length-1];
        const m=this.getTransform();
        if(Math.abs(w*m.a)>=this.canvas.width-.1 && Math.abs(h*m.d)>=this.canvas.height-.1)
            counts.fullScreenDraws++;
    });
    try {for(let i=0;i<60;i++)draw()} finally {for(const restore of restores.reverse())restore()}
    return {frames:60,counts,cacheBefore:sizes,cacheAfter:[l.shapeLights.size,l.gradients.size],
        cacheLimit:[128,64]};
}'''


def rgb_hsv(pixels):
    rgb = np.median(pixels.reshape(-1, 3), axis=0).tolist()
    h,s,v = colorsys.rgb_to_hsv(*(c/255 for c in rgb))
    return {'rgb':rgb,'hsv':[h*360,s,v]}


class OrangeLightTests(unittest.TestCase):
    def test_matched_pixels_controls_masks_and_cost(self):
        out = ROOT / os.environ.get('ORANGE_LIGHT_EVIDENCE_DIR','artifacts/TASK-227')
        out.mkdir(parents=True,exist_ok=True)
        base = os.environ.get('ORANGE_LIGHT_BASE_REV')
        if not base:
            base = (out/'BASE_REV').read_text().strip()
        report, costs, controls, images, settings = {}, {}, {}, {}, {}
        for phase,rev in [('baseline',base),('final','worktree')]:
            with ExitStack() as stack:
                root, resolved = export_rev(rev,stack.callback)
                url,browser = start_browser_test(root,stack.callback)
                for mode in ['bad','classic']:
                    for label,w,h,touch in [('desktop',1920,1080,False),('phone',844,390,True)]:
                        for control in [False,True]:
                            name=f'{mode}-{label}'+('-control' if control else '')
                            context=browser.new_context(viewport={'width':w,'height':h},
                                device_scale_factor=1,is_mobile=touch,has_touch=touch)
                            try:
                                context.add_init_script(SEED_SCRIPT%1)
                                context.add_init_script(CLOCK_SCRIPT)
                                page=context.new_page(); errors=[]
                                page.on('pageerror',lambda e:errors.append(str(e)))
                                page.goto(url);boot_frozen(page)
                                meta=page.evaluate(SCENE,[mode,control]);settings[phase+'-'+name]=meta
                                data=page.screenshot(path=str(out/f'{phase}-{name}.png'))
                                im=Image.open(io.BytesIO(data)).convert('RGB');images[phase,name]=np.asarray(im).astype('int16')
                                if not control:
                                    costs[phase+'-'+name]=page.evaluate(COST)
                                    # Three predetermined patches above the face; distance scales with height.
                                    patches=[]; marked=im.copy(); pen=ImageDraw.Draw(marked)
                                    for fraction in [.43,.5,.57]:
                                        x=round(w*fraction);y=round(h*(.4-12/1080));r=max(1,round(h*2/1080))
                                        box=[x-r,y-r,x+r+1,y+r+1]
                                        val=rgb_hsv(np.asarray(im)[box[1]:box[3],box[0]:box[2]])
                                        patches.append({'box':box,**val})
                                        pen.rectangle(box,outline='white',width=1);pen.text((x+5,y-16),f'{x},{y}',fill='white')
                                    report[phase+'-'+name]={'patches':patches}
                                    marked.crop((int(w*.34),int(h*.29),int(w*.66),int(h*.65))).save(out/f'{phase}-{name}-marked.png')
                                    # Production mask coverage, not merely the source colour.
                                    masks=page.evaluate(r'''() => {
                                        const l=visualEffects.lightmap, k=l.scale;
                                        const a=(x,y)=>l.lightCtx.getImageData(Math.floor(x*k),Math.floor(y*k),1,1).data[3];
                                        const u=scale[version], px=ninja.x*u,py=ninja.y*u,r=ninja.radius*u;
                                        const player=[];
                                        for(let y=-r*1.5;y<=r*1.5;y++)for(let x=-r*1.5;x<=r*1.5;x++)
                                            if(x*x+y*y<=r*r*2.25)player.push(a(px+x,py+y));
                                        const body=[];
                                        for(let y=height*.42;y<height*.54;y+=2)for(let x=width*.42;x<width*.58;x+=2)body.push(a(x,y));
                                        const result = {bodyMaskAlpha:Math.max(...body),playerMaskAlpha:Math.max(...player),
                                            playerLogicalRadius:r,
                                            falloff:[12,35,65,100].map(d=>a(width*.5,height*.4-height*d/1080)),
                                            geometry:[...l.shapeLights].map(([key,sprite])=>{const v=JSON.parse(key);
                                                return {shape:v[0],spread:v[2],scale:v[3],size:[sprite.width,sprite.height]}})};
                                        l.clear();l.lightCtx.save();l.drawElementLight(orangeFixture.rect);l.lightCtx.restore();
                                        result.unmaskedPlayerSpill=a(px,py);
                                        return result;
                                    }''')
                                    report[phase+'-'+name].update(masks)
                                self.assertFalse(errors,errors)
                            finally:context.close()
        for name in [n for phase,n in images if phase=='final']:
            a,b=images['baseline',name],images['final',name]
            self.assertEqual(settings['baseline-'+name],settings['final-'+name])
            if name.endswith('control'):
                controls[name]={'differentPixels':int(np.any(a!=b,axis=2).sum()),'maxDelta':int(abs(a-b).max())}
            else:
                # Complete body, including its bright outline, must not be brightened.
                h,w=a.shape[:2];body=(slice(round(h*.4)+3,round(h*.56)-3),slice(round(w*.4)+3,round(w*.6)-3))
                report['final-'+name]['bodyBeforeAfterDelta']=int(abs(a[body]-b[body]).max())
        for file,data in [('colour.json',report),('cost.json',{'observations':costs,'interpretation':'Same draw/composite/full-screen operations before and after; only orange cached sprite RGB and draw alpha change. Zero new warm-cache sprites, gradients or canvases. Counts measure operations, not FPS or GPU time.'}),('controls.json',controls)]:
            (out/file).write_text(json.dumps(data,indent=2)+'\n')
        # Inspection sheet preserves marked native-resolution crops.
        crops=[]
        for mode in ['bad','classic']:
            for label in ['desktop','phone']:
                pair=[Image.open(out/f'{phase}-{mode}-{label}-marked.png') for phase in ['baseline','final']]
                row=Image.new('RGB',(sum(i.width for i in pair),max(i.height for i in pair)+24))
                x=0
                for phase,im in zip(['baseline','final'],pair):
                    row.paste(im,(x,24));ImageDraw.Draw(row).text((x+4,4),f'{mode} {label} {phase}',fill='white');x+=im.width
                crops.append(row)
        sheet=Image.new('RGB',(max(i.width for i in crops),sum(i.height for i in crops)))
        y=0
        for row in crops:sheet.paste(row,(0,y));y+=row.height
        sheet.save(out/'before-after.png')
        files=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
        files=[f for f in files if f.endswith(('.js','.html'))]+['tools/test_orange_light.py']
        manifest={'baseline':base,'final':'worktree hashes','sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
            'settings':settings,'seed':1,'dpr':1,'pipeline':'production draw(), isolated fixtures on real cave',
            'evidence':[str(p.relative_to(ROOT)) for p in sorted(out.iterdir()) if p.is_file()]}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for name,c in controls.items():self.assertEqual(c['differentPixels'],0,name)
        for name,c in costs.items():
            for key in ['gradients','canvases','shapeSprites']:self.assertEqual(c['counts'][key],0,(name,c))
            self.assertEqual(c['cacheBefore'],c['cacheAfter']);self.assertLessEqual(c['cacheAfter'][0],128)
            if name.startswith('final'):
                self.assertEqual(c,costs[name.replace('final','baseline',1)],name)
        for name,r in report.items():
            self.assertEqual(r['bodyMaskAlpha'],0,(name,r))
            self.assertEqual(r['playerMaskAlpha'],0,(name,r))
            self.assertGreater(r['unmaskedPlayerSpill'],0,(name,r))
            self.assertGreater(r['falloff'][0],r['falloff'][1])
            self.assertGreater(r['falloff'][1],r['falloff'][2])
            self.assertEqual(r['falloff'][3],0)
            if name.startswith('final'):
                baseline=report[name.replace('final','baseline',1)]
                self.assertEqual(r['geometry'],baseline['geometry'])
                for a,b in zip(r['falloff'],baseline['falloff']):
                    self.assertLess(abs(a/r['falloff'][0]-b/baseline['falloff'][0]),.03)
            if name.startswith('final'):
                self.assertEqual(r['bodyBeforeAfterDelta'],0,name)
                for p in r['patches']:
                    self.assertTrue(20<=p['hsv'][0]<=45 and p['hsv'][1]>=.3,(name,p))
        print('PASS orange hue 20–45 degrees / saturation >=0.3: all 12 fixed patches',flush=True)
        print('PASS four native modes/viewports; identical green/triangle controls; body/player masks; unchanged obstacle bodies',flush=True)
        print('PASS 60 warm frames: zero new gradients/sprites/canvases; identical draw/composite/full-screen counts; bounded stable caches',flush=True)


if __name__=='__main__':unittest.main()
