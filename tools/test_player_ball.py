"""TASK-221: real frozen-clock historical/base/restored player pixels and cache probes.

PLAYER_BASE_REV is required: use the hash saved before editing, never HEAD^.
PLAYER_EVIDENCE_DIR receives native scenes, isolated bodies, labelled crops and
measured proof. Body size uses sharp RGB edge drops, excluding the soft halo.
"""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap
from test_ball_size import PROBE_SCRIPT, outer_radius

OUT = Path(os.environ.get('PLAYER_EVIDENCE_DIR', '../artifacts/TASK-221')).resolve()
BASE = os.environ['PLAYER_BASE_REV']
VIEWPORTS = [dict(name='desktop', width=1920, height=1080, dpr=1, touch=False),
             dict(name='phone', width=844, height=390, dpr=3, touch=True)]

# Isolate the real draw path on a common backdrop; retain the production halo.
ISOLATE = r'''() => {
    ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#12102c';
    ctx.fillRect(0,0,canvas.width,canvas.height);ctx.restore();
    ctx.save();ctx.scale(scale[version],scale[version]);ninja.draw();ctx.restore();
    return canvas.toDataURL();
}'''
PROBE = r'''() => {
    const rotation=ninja.visualRotation;
    const speed=Math.hypot(ninja.speedX,ninja.speedY);
    ninja.invulnerableMs=0;
    ctx.save();ctx.scale(scale[version],scale[version]);ninja.draw();
    const rotationDelta=ninja.visualRotation-rotation, cached=Ninja.glowSprite;
    let gradients=0,shadows=0;
    const proto=CanvasRenderingContext2D.prototype, originals={};
    for(const name of ['createRadialGradient','createLinearGradient']) {
        originals[name]=proto[name];proto[name]=function(...args){gradients++;return originals[name].apply(this,args)};
    }
    const descriptor=Object.getOwnPropertyDescriptor(proto,'shadowBlur');
    Object.defineProperty(proto,'shadowBlur',{...descriptor,set(v){if(v>0)shadows++;descriptor.set.call(this,v)}});
    try {for(let i=0;i<20;i++)ninja.draw();}
    finally {
        for(const name in originals)proto[name]=originals[name];
        Object.defineProperty(proto,'shadowBlur',descriptor);ctx.restore();
    }
    const alphas=[0,RESPAWN_BLINK_MS*2,RESPAWN_BLINK_MS*3].map(ms=>{
        ninja.invulnerableMs=ms;return ninja.getBlinkAlpha();});
    ninja.invulnerableMs=0;
    return {gradients,shadows,reused:cached===Ninja.glowSprite,alphas,
        rotationDelta,expectedRotationDelta:speed<STYLE.playerVisuals.rotationMinSpeed?0:speed*STYLE.playerVisuals.rotationSpeed,
        collisionRadius:ninja.radius,fill:ninja.fill,edge:ninja.stroke};
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
                # Match current backing density, preserving phone input/device DPR 3.
                if vp['touch']:
                    context.add_init_script("Object.defineProperty(window,'devicePixelRatio',{get:()=>2})")
                page = context.new_page(); errors=[]
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url);snap.boot_frozen(page)
                page.evaluate(snap.SETUP_SCRIPT,[snap.input_script(snap.SEED,60,vp['width'],vp['height']),vp['touch']])
                page.evaluate('mode=>startGame(mode)',mode);page.evaluate(snap.ADVANCE_SCRIPT,60)
                probe = page.evaluate(PROBE_SCRIPT)
                state = page.evaluate('''()=>({x:ninja.x,y:ninja.y,speedX:ninja.speedX,speedY:ninja.speedY,
                    cameraX:screen.x,cameraY:screen.y,radius:ninja.radius,rope:grapnel.pos})''')
                files={}
                for frame in ('normal','invulnerable','body'):
                    if frame=='invulnerable':
                        page.evaluate('()=>{ninja.invulnerableMs=RESPAWN_BLINK_MS*2;draw()}')
                    if frame=='body':
                        page.evaluate('()=>{ninja.invulnerableMs=0}')
                    data=snap.png_bytes(page.evaluate(ISOLATE if frame=='body' else '()=>__snap.capture()'))
                    path=OUT/f'{label}-{vp["name"]}-{mode}-{frame}.png';path.write_bytes(data)
                    files[frame]=path.name
                metrics=page.evaluate(PROBE) if label!='reference' else {}
                records[f'{vp["name"]}-{mode}']=dict(probe=probe,state=state,files=files,metrics=metrics,errors=errors)
                context.close()
    return revision,records


class PlayerBallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True,exist_ok=True)
        cls.report=dict(baseline=BASE,seed=snap.SEED,tick=60,viewports=VIEWPORTS,
                        phone_backing_dpr=2,revisions={},captures={})
        for label,rev in [('reference','e430f92'),('before',BASE),('restored','worktree')]:
            revision,records=capture(label,rev)
            cls.report['revisions'][label]=revision;cls.report['captures'][label]=records
        sheet=Image.new('RGB',(960,4*240),'#12102c');d=ImageDraw.Draw(sheet)
        cls.measurements={}
        for row,key in enumerate(cls.report['captures']['restored']):
            cls.measurements[key]={}
            for col,label in enumerate(('reference','before','restored')):
                r=cls.report['captures'][label][key];p=r['probe']
                body=np.asarray(Image.open(OUT/r['files']['body']).convert('RGB'))
                radius,samples=outer_radius(body,p['x'],p['y'],max(p['hitbox'],12*body.shape[0]/1080)*3)
                ys,xs=np.mgrid[:body.shape[0],:body.shape[1]]
                mask=np.hypot(xs+.5-p['x'],ys+.5-p['y'])<radius*.55
                rgb=np.median(body[mask],axis=0).tolist()
                cls.measurements[key][label]=dict(radius_css=radius/p['density'],edge_samples=samples,centre_rgb=rgb)
                d.text((col*320+4,row*240+3),f'{label} {key}',fill='white')
                for i,frame in enumerate(('normal','invulnerable','body')):
                    im=Image.open(OUT/r['files'][frame]);half=12*p['density']
                    crop=im.crop((round(p['x']-half),round(p['y']-half),round(p['x']+half),round(p['y']+half)))
                    crop.save(OUT/f'{label}-{key}-{frame}-crop.png')
                    sheet.paste(crop.resize((100,100),Image.NEAREST),(col*320+i*105,row*240+25))
                    d.text((col*320+i*105,row*240+210),frame,fill='white')
        sheet.save(OUT/'before-after.png')
        cls.report['measurements']=cls.measurements
        root=Path(__file__).resolve().parent.parent
        cls.report['source_sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for pattern in ('*.js','render/*.js','sprites/*.js','tools/test_player_ball.py') for p in root.glob(pattern)}
        cls.report['outputs']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.png')}
        (OUT/'manifest.json').write_text(json.dumps(cls.report,indent=2)+'\n')

    def test_pixels_size_and_blue_fill(self):
        for key,values in self.measurements.items():
            b,f,h=(values[x] for x in ('before','restored','reference'))
            delta=abs(f['radius_css']-b['radius_css']);limit=max(1,b['radius_css']*.1)
            self.assertLessEqual(delta,limit,key)
            r,g,blue=f['centre_rgb'];self.assertGreater(blue,g+40,key);self.assertGreater(g,r+30,key)
            self.assertLessEqual(max(abs(a-b) for a,b in zip(f['centre_rgb'],h['centre_rgb'])),65,key)
            print(f'PASS {key}: body edge delta={delta:.3f} CSS px <= {limit:.3f}; filled blue RGB={f["centre_rgb"]}; reference={h["centre_rgb"]}',flush=True)

    def test_state_blink_rotation_and_warm_cache(self):
        for key,r in self.report['captures']['restored'].items():
            b=self.report['captures']['before'][key]
            self.assertEqual(r['state'],b['state'],key)
            historical=self.report['captures']['reference'][key]['state']
            attachment=lambda state: dict(state,rope=[p[:2] for p in state['rope']])
            self.assertEqual(attachment(r['state']),attachment(historical),key)
            for label in self.report['captures']:self.assertEqual(self.report['captures'][label][key]['errors'],[])
            m=r['metrics'];self.assertEqual(m['alphas'],b['metrics']['alphas'])
            self.assertLess(m['alphas'][1],1);self.assertGreater(m['alphas'][1],0)
            self.assertAlmostEqual(m['rotationDelta'],m['expectedRotationDelta'])
            self.assertTrue(m['reused']);self.assertEqual(m['gradients'],0);self.assertEqual(m['shadows'],0)
            normal=np.asarray(Image.open(OUT/r['files']['normal']))
            blink=np.asarray(Image.open(OUT/r['files']['invulnerable']))
            self.assertGreater(np.count_nonzero(normal!=blink),0)
            print(f'PASS {key}: matched historical/base/final physics camera rope; blink={m["alphas"]}; rotation delta={m["rotationDelta"]}; cache reused; warmed gradients=0 shadowBlur=0',flush=True)

if __name__=='__main__':unittest.main()
