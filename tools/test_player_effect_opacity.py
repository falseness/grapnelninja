"""TASK-223: frozen production draw-call alpha and controlled composite probes.

Save PLAYER_BASE_REV before editing. PLAYER_EVIDENCE_DIR receives native scenes,
actual isolated invariant pixels and source/composite alpha measurements. Canvas
8-bit probe deltas corroborate draw-call alpha; full-scene brightness is not an
alpha estimator. Shared bloom weights must stay unchanged.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import unittest

from PIL import Image, ImageChops, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap
from test_ball_size import PROBE_SCRIPT
from test_player_ball import PROBE as CACHE_PROBE

BASE = os.environ['PLAYER_BASE_REV']
OUT = Path(os.environ.get('PLAYER_EVIDENCE_DIR', '../artifacts/TASK-223')).resolve()
VIEWPORTS = [dict(name='desktop', width=1920, height=1080, dpr=1, touch=False),
             dict(name='phone', width=844, height=390, dpr=3, touch=True)]

PROBE = r'''() => {
    const records=[], proto=CanvasRenderingContext2D.prototype, originals={};
    let path='', index=0;
    // Controlled single contribution over the SAME backdrop for each revision.
    // Read alpha from the actual production draw, then exercise both blend modes.
    function sample(alpha, operation) {
        const c=document.createElement('canvas');c.width=c.height=8;
        const q=c.getContext('2d');q.fillStyle='rgb(12,18,24)';q.fillRect(0,0,8,8);
        q.globalCompositeOperation=operation;q.globalAlpha=alpha;
        q.fillStyle='rgb(120,160,200)';q.fillRect(0,0,8,8);
        return [...q.getImageData(4,4,1,1).data];
    }
    for(const name of ['fill','stroke','fillRect','drawImage']) {
        originals[name]=proto[name];
        proto[name]=function(...args) {
            if(path) {
                // Do not instrument the controlled probe itself.
                const saved=path;path='';
                const alpha=this.globalAlpha;
                records.push({path:saved,index:index++,method:name,alpha,
                    color:name==='stroke'?this.strokeStyle:this.fillStyle,
                    composite:this.globalCompositeOperation,
                    transform:[this.getTransform().a,this.getTransform().d],
                    sourceOver:sample(alpha,'source-over'),lighter:sample(alpha,'lighter')});
                path=saved;
            }
            return originals[name].apply(this,args);
        };
    }
    const trail=visualEffects.playerTrail, particles=visualEffects.particles;
    const spark=particles.particles.find(p=>p.spark);
    if(!spark)throw Error('Required live square spark missing');
    const geometry=[], fill=trail.fillRibbon;
    trail.fillRibbon=function(points,start,width,color,alpha) {
        geometry.push({start,width,color,outline:this.getRibbonOutline(points,start,width).map(p=>({...p}))});
        return fill.call(this,points,start,width,color,alpha);
    };
    function trace(name, fn) {path=name;index=0;fn();path='';}
    const rotation=ninja.visualRotation;
    ctx.save();ctx.scale(scale[version],scale[version]);
    try {
        trace('normal/ribbon',()=>trail.drawSmoothPlayerTrail(ninja.track));
        trace('normal/spark',()=>particles.drawSpark(spark,.5,spark.x+screen.x,spark.y+screen.y));
        trace('normal/ball',()=>ninja.draw());
        // Real renderGlow swaps both global ctx and particle context. Inspect the
        // actual source draws, then real blur and final composite weights.
        const glow=visualEffects.playerGlow;glow.resize();
        const draw=glow.drawEmissiveShapes;
        glow.drawEmissiveShapes=function(state) {
            trace('emissive/ribbon',()=>trail.drawSmoothPlayerTrail(state.ninja.track));
            trace('emissive/spark',()=>particles.drawSpark(spark,.5,spark.x+screen.x,spark.y+screen.y));
            const oldTrail=trail.drawSmoothPlayerTrailIfEnabled,oldLayer=particles.drawLayer;
            trail.drawSmoothPlayerTrailIfEnabled=()=>{};particles.drawLayer=()=>{};
            try {trace('emissive/ring',()=>draw.call(this,state));}
            finally {trail.drawSmoothPlayerTrailIfEnabled=oldTrail;particles.drawLayer=oldLayer;}
        };
        try {glow.drawGlowPass({ninja}, {x:0,y:0});}
        finally {glow.drawEmissiveShapes=draw;}
        trace('blur',()=>glow.blur());
        trace('composite',()=>glow.composite(ninja));
    } finally {
        path='';ctx.restore();ninja.visualRotation=rotation;trail.fillRibbon=fill;
        for(const name in originals)proto[name]=originals[name];
    }
    const isolated={};
    function isolate(name,fn) {
        ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=1;
        ctx.fillStyle='#12102c';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.restore();
        ctx.save();ctx.scale(scale[version],scale[version]);fn();ctx.restore();
        isolated[name]=canvas.toDataURL();
    }
    // Suppress only halo image draws, so the production body and marker remain.
    const drawImage=proto.drawImage;
    proto.drawImage=function(image,...args) {
        if(image===Ninja.glowSprite.halo)return;
        return drawImage.call(this,image,...args);
    };
    try {isolate('body-marker',()=>ninja.draw());}
    finally {proto.drawImage=drawImage;ninja.visualRotation=rotation;}
    // Tick 60 can have no thrown rope: exercise a visible deterministic fixture
    // through the real rope, anchor and flying-tip paths, then restore state.
    const saved={pos:grapnel.pos,throwed:grapnel.throwed,grappled:grapnel.grappled};
    grapnel.pos=[[ninja.x-80,ninja.y-60]];grapnel.throwed=true;
    try {
        isolate('rope',()=>grapnel.draw());
        grapnel.grappled=true;isolate('hook',()=>grapnel.drawHook());
        grapnel.grappled=false;isolate('hook-tip',()=>grapnel.drawHook());
    } finally {Object.assign(grapnel,saved);}
    return {records,geometry,isolated,spark,particles:particles.particles,
        points:ninja.track.pos,pointsLimit:ninja.track.pointsLimit,
        style:{trails:STYLE.trails,particles:STYLE.particles,colors:STYLE.colors,
               glow:STYLE.player.glow,ball:STYLE.playerVisuals,timing:STYLE.timing}};
}'''


def capture(label, rev):
    records = {}
    with ExitStack() as stack:
        root, revision = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for vp in VIEWPORTS:
            for mode in ('bad', 'classic'):
                context = browser.new_context(viewport={k:vp[k] for k in ('width','height')},
                    device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
                context.add_init_script(SEED_SCRIPT % snap.SEED)
                context.add_init_script(snap.CLOCK_SCRIPT)
                if vp['touch']:
                    context.add_init_script("Object.defineProperty(window,'devicePixelRatio',{get:()=>2})")
                page=context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url);snap.boot_frozen(page)
                page.evaluate(snap.SETUP_SCRIPT,[snap.input_script(snap.SEED,60,vp['width'],vp['height']),vp['touch']])
                page.evaluate('mode=>startGame(mode)',mode);page.evaluate(snap.ADVANCE_SCRIPT,60)
                key=f'{vp["name"]}-{mode}'
                scene=f'{label}-{key}-scene.png'
                (OUT/scene).write_bytes(snap.png_bytes(page.evaluate('()=>__snap.capture()')))
                detailed=f'{label}-{key}-detailed.png'
                if label!='reference':
                    data=page.evaluate(r'''() => {
                        const rotation=ninja.visualRotation;
                        ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=1;
                        for(let y=0;y<canvas.height;y+=12)for(let x=0;x<canvas.width;x+=12) {
                            ctx.fillStyle=((x+y)/12)%2?'#292344':'#101830';ctx.fillRect(x,y,12,12);
                            ctx.fillStyle='#45405a';ctx.fillRect(x,y,2,2);
                        }
                        ctx.restore();ctx.save();ctx.scale(scale[version],scale[version]);
                        visualEffects.playerTrail.drawSmoothPlayerTrail(ninja.track);
                        visualEffects.particles.drawLayer(p=>p.spark);
                        visualEffects.playerGlow.draw({ninja},{x:0,y:0});ninja.draw();
                        ctx.restore();ninja.visualRotation=rotation;
                        return canvas.toDataURL();
                    }''')
                    (OUT/detailed).write_bytes(snap.png_bytes(data))
                pos=page.evaluate(PROBE_SCRIPT)
                state=page.evaluate('''()=>({x:ninja.x,y:ninja.y,speedX:ninja.speedX,speedY:ninja.speedY,
                    cameraX:screen.x,cameraY:screen.y,radius:ninja.radius,rope:grapnel.pos})''')
                probes={};cache={}
                if label!='reference':
                    probes=page.evaluate(PROBE)
                    for name,data in probes.pop('isolated').items():
                        path=f'{label}-{key}-{name}.png'
                        (OUT/path).write_bytes(snap.png_bytes(data))
                        probes.setdefault('isolated',{})[name]=path
                    cache=page.evaluate(CACHE_PROBE)
                records[key]=dict(scene=scene,detailed=detailed if label!='reference' else scene,position=pos,state=state,probes=probes,cache=cache,errors=errors)
                context.close()
    return revision,records


class PlayerEffectOpacityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True,exist_ok=True)
        cls.report=dict(baseline=BASE,seed=snap.SEED,tick=60,viewports=VIEWPORTS,
                        phone_backing_dpr=2,revisions={},captures={})
        for label,rev in [('reference','e430f92'),('before',BASE),('final','worktree')]:
            revision,records=capture(label,rev)
            cls.report['revisions'][label]=revision;cls.report['captures'][label]=records
        sheet=Image.new('RGB',(1800,4*640),'#12102c');d=ImageDraw.Draw(sheet)
        for row,key in enumerate(cls.report['captures']['final']):
            # Identical crop: trail and ball plus surrounding detailed background.
            b=cls.report['captures']['before'][key];p=b['position']
            points=b['probes']['geometry'][0]['outline']
            # Geometry is world+camera; convert via player's known canvas scale.
            k=p['hitbox']/b['state']['radius']
            xs=[(v['x']-b['state']['x']-b['state']['cameraX'])*k+p['x'] for v in points]
            ys=[(v['y']-b['state']['y']-b['state']['cameraY'])*k+p['y'] for v in points]
            box=(min(xs+[p['x']])-60,min(ys+[p['y']])-60,max(xs+[p['x']])+60,max(ys+[p['y']])+60)
            for col,label in enumerate(('reference','before','final')):
                r=cls.report['captures'][label][key]
                crop=Image.open(OUT/r['scene']).crop(tuple(round(x) for x in box))
                crop.save(OUT/f'{label}-{key}-crop.png')
                crop.thumbnail((590,300));sheet.paste(crop,(col*600,row*640+25))
                d.text((col*600+5,row*640+5),f'{label} {key} tick=60',fill='white')
                if label!='reference':
                    tile=Image.open(OUT/r['detailed']).crop(tuple(round(x) for x in box))
                    tile.thumbnail((590,290));sheet.paste(tile,(col*600,row*640+345))
                    d.text((col*600+5,row*640+325),'Same detailed backdrop / production player draws',fill='white')
        sheet.save(OUT/'before-after.png')
        root=Path(__file__).resolve().parent.parent
        cls.report['source_sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for pattern in ('*.js','render/*.js','sprites/*.js','tools/test_player_effect_opacity.py') for p in root.glob(pattern)}
        cls.report['outputs']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.png')}
        (OUT/'manifest.json').write_text(json.dumps(cls.report,indent=2)+'\n')

    def test_effective_alpha_composites_and_invariants(self):
        results={}
        for key,f in self.report['captures']['final'].items():
            b=self.report['captures']['before'][key]
            self.assertEqual(f['state'],b['state'])
            for label in self.report['captures']:self.assertEqual(self.report['captures'][label][key]['errors'],[])
            bp,fp=b['probes'],f['probes']
            for field in ('geometry','spark','particles','points','pointsLimit','style'):
                self.assertEqual(fp[field],bp[field],f'{key}: {field}')
            for name,path in fp['isolated'].items():
                image=Image.open(OUT/path).convert('RGB')
                self.assertIsNotNone(ImageChops.difference(image,Image.new('RGB',image.size,'#12102c')).getbbox(),name)
                self.assertEqual(image.tobytes(),Image.open(OUT/bp['isolated'][name]).convert('RGB').tobytes(),name)
            self.assertEqual(f['cache'],b['cache'])
            self.assertTrue(f['cache']['reused']);self.assertEqual(f['cache']['gradients'],0)
            self.assertEqual(f['cache']['shadows'],0)
            br,fr=bp['records'],fp['records'];self.assertEqual(len(br),len(fr))
            rows=[];sources=[];weights=[]
            for before,final in zip(br,fr):
                path=before['path'];i=before['index']
                self.assertEqual((path,i,before['method']),(final['path'],final['index'],final['method']))
                for field in ('color','composite','transform'):self.assertEqual(before[field],final[field])
                affected=path.startswith(('normal/ribbon','normal/spark','emissive/')) or (path=='normal/ball' and i==0)
                ratio=final['alpha']/before['alpha']
                self.assertAlmostEqual(ratio,.5 if affected else 1,delta=.01,msg=f'{key} {path} {i}')
                if affected:
                    for blend in ('sourceOver','lighter'):
                        bd=sum(x-y for x,y in zip(before[blend][:3],[12,18,24]))
                        fd=sum(x-y for x,y in zip(final[blend][:3],[12,18,24]))
                        self.assertGreater(fd,0);self.assertLess(fd,bd)
                        self.assertAlmostEqual(fd/bd,.5,delta=.04)
                    if path.startswith('emissive/'):sources.append((path,i,before['alpha'],final['alpha']))
                if path=='composite':weights.append((before['alpha'],final['alpha']))
                rows.append(dict(path=path,index=i,before=before,final=final,ratio=ratio,affected=affected))
            self.assertEqual(len(weights),4)
            self.assertEqual(len(sources),8)  # five ribbon, two spark, one ring
            effective=[]
            for path,i,ba,fa in sources:
                for level,(bw,fw) in enumerate(weights):
                    self.assertAlmostEqual(fa*fw/(ba*bw),.5,delta=.01)
                    effective.append(dict(path=path,index=i,level=level,before=ba*bw,final=fa*fw,ratio=fa*fw/(ba*bw)))
            results[key]=dict(contributions=rows,offscreen_composite=effective,
                invariants='PASS identical body-marker rope hook pixels, geometry width length lifetime counts colors state; warm cache reused')
            print(f'PASS {key}: normal/emissive ribbon body/core/halo, spark body/halo, player halo/ring ratios=0.500; '
                  '32 offscreen/composite ratios=0.500; controlled source-over/lighter probes reduced; '
                  'identical body-marker rope hook pixels, geometry width length lifetime counts colors state; cache reused',flush=True)
        (OUT/'opacity.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':unittest.main()
