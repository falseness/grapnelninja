"""Frozen player trail geometry/pixel regression; baseline must be saved before edits.

PLAYER_BASE_REV selects the pre-ticket commit. PLAYER_EVIDENCE_DIR receives
native scenes, isolated production ribbons, measured outlines and provenance.
The two clamp probes keep the real frozen centreline and change only the input
line width. Measurements come from production getRibbonOutline vertices, not
from the configured width ratios. Blur softness is deliberately not halved.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap
from test_ball_size import PROBE_SCRIPT

OUT = Path(os.environ.get('PLAYER_EVIDENCE_DIR', '../artifacts/TASK-222')).resolve()
BASE = os.environ['PLAYER_BASE_REV']
VIEWPORTS = [dict(name='desktop', width=1920, height=1080, dpr=1, touch=False),
             dict(name='phone', width=844, height=390, dpr=3, touch=True)]

GEOMETRY = r'''which => {
    const r = new PlayerTrailRenderer(), track = ninja.track, c = STYLE.trails.player;
    const points = r.getRibbonPoints(track.pos, track.lineWidth*c.minPointDistanceRatio).map(p=>({...p}));
    const inputWidth = which === 'clamped' ? 0.0001 : which === 'non-clamped' ? track.lineWidth*4 : track.lineWidth;
    const rawWidth = inputWidth*c.widthRatio*r.getBadVersionTrails().widthMultiplier;
    const minimum = c.minScreenWidth/scale[version];
    const layers = [], original = r.fillRibbon;
    r.fillRibbon = function(points,start,width,color,alpha) {
        const outline = this.getRibbonOutline(points,start,width).map(p=>({...p}));
        const n = outline.length/2, sections = [];
        for(let i=0;i<n;i++) {
            const a=outline[i],b=outline[outline.length-1-i];
            sections.push({center:{x:(a.x+b.x)/2,y:(a.y+b.y)/2},width:Math.hypot(a.x-b.x,a.y-b.y)});
        }
        layers.push({start,color,alpha,outline,sections});
        return original.call(this,points,start,width,color,alpha);
    };
    ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#000';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.restore();
    ctx.save();ctx.scale(scale[version],scale[version]);
    r.ribbonPathIndex=0;
    r.drawRibbon(points,Math.max(1,Math.floor(points.length*c.minSegmentRatio)),
        r.getRibbonWidth({lineWidth:inputWidth}),r.clampAlpha(c.maxAlpha*r.getBadVersionTrails().alphaMultiplier));
    ctx.restore();
    const config={...c};delete config.widthRatio;delete config.minScreenWidth;
    return {points,rawPoints:track.pos,pointCount:points.length,endpoints:[points[0],points[points.length-1]],
        longitudinalExtent:points.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p.x-points[i].x,p.y-points[i].y),0),
        lifetime:{pointsLimit:track.pointsLimit,timing:STYLE.timing},config,colors:STYLE.colors.playerTrail,
        glow:STYLE.player.glow,ball:STYLE.playerVisuals,trackWidth:track.lineWidth,
        inputWidth,rawWidth,minimum,clamped:rawWidth<minimum,layers,png:canvas.toDataURL()};
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
                probe=page.evaluate(PROBE_SCRIPT)
                state=page.evaluate('''()=>({x:ninja.x,y:ninja.y,speedX:ninja.speedX,speedY:ninja.speedY,
                    cameraX:screen.x,cameraY:screen.y,radius:ninja.radius,rope:grapnel.pos,
                    points:ninja.track.pos,pointsLimit:ninja.track.pointsLimit})''')
                cases={}
                if label!='reference':
                    for case in ('natural','clamped','non-clamped'):
                        g=page.evaluate(GEOMETRY,case)
                        path=f'{label}-{key}-{case}.png'
                        (OUT/path).write_bytes(snap.png_bytes(g.pop('png')))
                        g['path']=path;cases[case]=g
                records[key]=dict(scene=scene,probe=probe,state=state,cases=cases,errors=errors)
                context.close()
    return revision,records


class PlayerTrailWidthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True,exist_ok=True)
        cls.report=dict(baseline=BASE,seed=snap.SEED,tick=60,viewports=VIEWPORTS,
                        phone_backing_dpr=2,revisions={},captures={})
        for label,rev in [('reference','e430f92'),('before',BASE),('final','worktree')]:
            revision,records=capture(label,rev)
            cls.report['revisions'][label]=revision;cls.report['captures'][label]=records
        # One shared crop per viewport/mode, derived from the before ribbon pixels.
        sheet=Image.new('RGB',(1800,4*370),'#12102c');d=ImageDraw.Draw(sheet)
        for row,key in enumerate(cls.report['captures']['final']):
            before=cls.report['captures']['before'][key]
            im=Image.open(OUT/before['cases']['natural']['path']).convert('RGB')
            box=im.getbbox();x0,y0,x1,y1=box
            box=(x0-25,y0-25,x1+25,y1+25)
            for col,label in enumerate(('reference','before','final')):
                r=cls.report['captures'][label][key]
                crop=Image.open(OUT/r['scene']).crop(box)
                crop.save(OUT/f'{label}-{key}-crop.png')
                crop.thumbnail((590,160));sheet.paste(crop,(col*600,row*370+25))
                d.text((col*600+5,row*370+5),f'{label} {key} tick=60',fill='white')
                if label!='reference':
                    isolated=Image.open(OUT/r['cases']['natural']['path']).crop(box)
                    isolated.thumbnail((590,160));sheet.paste(isolated,(col*600,row*370+200))
                d.text((col*600+5,row*370+180),'scene above / isolated ribbon below',fill='white')
        sheet.save(OUT/'before-after.png')
        root=Path(__file__).resolve().parent.parent
        cls.report['source_sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for pattern in ('*.js','render/*.js','sprites/*.js','tools/test_player_trail_width.py') for p in root.glob(pattern)}
        cls.report['outputs']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.png')}
        (OUT/'manifest.json').write_text(json.dumps(cls.report,indent=2)+'\n')

    def test_outline_cross_sections_and_pixels(self):
        measurements={}
        for key,f in self.report['captures']['final'].items():
            b=self.report['captures']['before'][key];measurements[key]={}
            self.assertEqual(f['state'],b['state'],key)
            for label in self.report['captures']:
                self.assertEqual(self.report['captures'][label][key]['errors'],[])
            for case,fg in f['cases'].items():
                bg=b['cases'][case]
                for invariant in ('points','rawPoints','pointCount','endpoints','longitudinalExtent','lifetime',
                                  'config','colors','glow','ball','trackWidth','inputWidth','clamped'):
                    self.assertEqual(fg[invariant],bg[invariant],f'{key} {case} {invariant}')
                if case!='natural':self.assertEqual(fg['clamped'],case=='clamped')
                self.assertEqual(len(fg['layers']),5)
                sections={}
                for i,(bl,fl) in enumerate(zip(bg['layers'],fg['layers'])):
                    name=('halo','body-0','body-1','body-2','core')[i]
                    for invariant in ('start','color','alpha'):self.assertEqual(fl[invariant],bl[invariant])
                    self.assertEqual(len(bl['sections']),len(fl['sections']))
                    rows=[]
                    for bs,fs in zip(bl['sections'],fl['sections']):
                        self.assertGreater(bs['width'],0)
                        np.testing.assert_allclose(list(bs['center'].values()),list(fs['center'].values()),atol=1e-10)
                        ratio=fs['width']/bs['width'];self.assertAlmostEqual(ratio,.5,delta=.01)
                        rows.append(dict(before=bs,final=fs,ratio=ratio))
                    self.assertGreater(len(rows),2)
                    sections[name]=rows
                bp=np.asarray(Image.open(OUT/bg['path']).convert('RGB'))
                fp=np.asarray(Image.open(OUT/fg['path']).convert('RGB'))
                before_pixels=int(np.count_nonzero(bp.max(axis=2)>20))
                final_pixels=int(np.count_nonzero(fp.max(axis=2)>20))
                self.assertGreater(final_pixels,0);self.assertLess(final_pixels,before_pixels*.8)
                measurements[key][case]=dict(before=bg,final=fg,sections=sections,
                    pixel_area=dict(before=before_pixels,final=final_pixels,ratio=final_pixels/before_pixels))
                print(f'PASS {key} {case}: body/core/halo all cross-section ratios=0.500; '
                      f'identical centreline endpoints point count lifetime extent taper colors opacity sparks blur; '
                      f'pixel area {before_pixels}->{final_pixels}',flush=True)
        (OUT/'width.json').write_text(json.dumps(measurements,indent=2)+'\n')

if __name__=='__main__':unittest.main()
