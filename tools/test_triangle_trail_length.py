"""Measure production triangle history and raster envelopes against a saved revision."""
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
    startGame(mode); screen.x=screen.y=0; trackEnabled=true; QUALITY.playerTrail=true;
    for(const f of floors)f.elements=[];
    const u=scale[version], step=height*.0025/u;
    const triangles=[Triangle,Triangle,HarmlessTriangle].map((C,i)=>new C({
        x:width*(.25+i*.25)/u,y:height*.23/u,radius:height*.028/u,
        stroke:i===1?STYLE.colors.hazard.red:STYLE.colors.hazard.stroke,
        yMin:-1e8,yMax:1e8}));
    const states=[],cadence=[];
    for(const t of triangles)t.speedY=step/cyclesPerTick;
    for(let tick=0;tick<180;tick++)for(let c=0;c<cyclesPerTick;c++){
        firstCycleInThisTick=c===0;
        for(const t of triangles)t.move();
        if(tick<3)cadence.push(triangles.map(t=>t.track.pos.length));
        states.push(triangles.map(t=>({x:t.x,y:t.y,dy:t.dy,speedY:t.speedY,
            circle:{...t.getCircumscribedCircle()},lines:t.getLines(),
            collision:[-t.side,0,t.side].map(dx=>t.getLines().some(l=>
                collisionCircleWithLine(l,t.x+dx,t.getTopPointY(),2)))})));
    }
    firstCycleInThisTick=true;
    floors[1].elements=triangles;ninja.x=width*.1/u;ninja.y=height*.85/u;
    window.trailFixture={triangles,step,states,cadence};draw();draw();
    return {width,height,u,backing:[canvas.width,canvas.height],clock:performance.now(),
        camera:[screen.x,screen.y],cyclesPerTick,step,seed:1,
        triangles:triangles.map(t=>({type:t.constructor.name,x:t.x,y:t.y,side:t.side,height:t.height})),
        settings:{timing:STYLE.timing,trails:STYLE.trails,alpha:STYLE.alpha,
            strokes:STYLE.strokes,colours:STYLE.colors,obstacles:STYLE.badVersionEffects.obstacles},
        otherBounds:{player:ninja.track.pointsLimit,cube:new JumpingCube({x:0,y:0,width:20,height:20,
            stroke:STYLE.colors.cube.blueStroke,speedX:0,speedY:0}).track.pointsLimit}};
}'''
ISOLATE = r'''([index,kind]) => {
    const t=trailFixture.triangles[index],original=ctx,scratch=document.createElement('canvas');
    scratch.width=canvas.width;scratch.height=canvas.height;
    const saved=t.track.pos;
    try{ctx=scratch.getContext('2d');ctx.setTransform(original.getTransform());ctx.scale(scale[version],scale[version]);
        if(kind==='body')t.draw();
        else {if(kind==='stationary')t.track.pos=[t.getPoints(),t.getPoints()];t.track.draw()}
        return scratch.toDataURL();
    }finally{ctx=original;t.track.pos=saved}
}'''
PROBE = r'''() => {
    const {triangles,states,cadence}=trailFixture;
    const history=triangles.map(t=>({count:t.track.pos.length,limit:t.track.pointsLimit,
        positions:structuredClone(t.track.pos),distance:t.track.pos.at(-1)[0].y-t.track.pos[0][0].y}));
    const extended=[],reversal=[];
    for(const t of triangles){
        for(let i=0;i<900;i++)t.move();
        extended.push(t.track.pos.length);
        t.y=height*.5/scale[version];
        t.restrictionY={min:t.getTopPointY()-20,max:t.getBottomPointY()+20};
        let turns=0,old=t.speedY;
        for(let i=0;i<600;i++){t.move();if(t.speedY!==old)turns++;old=t.speedY}
        const e=t.track.getPointExtremes();
        reversal.push({count:t.track.pos.length,turns,extrema:e,positions:t.track.pos,
            finite:t.track.pos.flat().every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y))});
    }
    const originalDeath=onLethalDeath;let deaths=0;const collisionEffects=[];
    try{onLethalDeath=()=>deaths++;for(const t of triangles){const before=deaths;t.collision();collisionEffects.push(deaths-before)}}
    finally{onLethalDeath=originalDeath}
    return {history,extended,reversal,states,cadence,collisionEffects};
}'''
DISABLE = r'''control => {
    const result=[];trackEnabled=control!=='track';QUALITY.playerTrail=control!=='quality';
    for(const t of trailFixture.triangles){const before=t.track.pos.length;
        for(let i=0;i<200;i++)t.move();result.push({before,after:t.track.pos.length})}
    const fresh=new Triangle({x:100,y:100,radius:20,stroke:'#ff2d95',yMin:-1e8,yMax:1e8});
    for(let i=0;i<200;i++)fresh.move();
    return {existing:result,freshCount:fresh.track.pos?fresh.track.pos.length:0,
        freshTrack:fresh.track.constructor.name};
}'''


def decoded(data):
    return Image.open(io.BytesIO(base64.b64decode(data.split(',')[1]))).convert('RGBA')


def extent(im):
    y, x = np.where(np.array(im)[:, :, 3] > 0)
    return [int(x.min()), int(y.min()), int(x.max()), int(y.max())] if len(x) else None


class TriangleTrailTests(unittest.TestCase):
    def test_history_rendering_and_gameplay(self):
        out = ROOT / os.environ.get('TRIANGLE_TRAIL_EVIDENCE_DIR', 'artifacts/TASK-230')
        out.mkdir(parents=True, exist_ok=True)
        base = os.environ.get('TRIANGLE_TRAIL_BASE_REV') or (out/'BASE_REV').read_text().strip()
        measurements, settings, bodies, native, captures = {}, {}, {}, {}, []
        for phase, rev, bound in [('baseline', base, 75), ('final', 'worktree', 150)]:
            with ExitStack() as stack:
                root, _ = export_rev(rev, stack.callback)
                url, browser = start_browser_test(root, stack.callback)
                for mode in ['bad', 'classic']:
                    for label, w, h in [('desktop', 1920, 1080), ('phone', 844, 390)]:
                        name = f'{mode}-{label}'; key = f'{phase}-{name}'
                        context = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1,
                                                      is_mobile=label=='phone', has_touch=label=='phone')
                        try:
                            context.add_init_script(SEED_SCRIPT % 1); context.add_init_script(CLOCK_SCRIPT)
                            page = context.new_page(); errors = []
                            page.on('pageerror', lambda e: errors.append(str(e)))
                            page.goto(url); boot_frozen(page)
                            settings[key] = page.evaluate(SCENE, mode)
                            path = out/f'{key}.png'; page.screenshot(path=str(path)); captures.append(path)
                            native[key] = Image.open(path).convert('RGB')
                            raster = []
                            for i in range(3):
                                images = {}
                                for kind in ['trail', 'stationary', 'body']:
                                    im = decoded(page.evaluate(ISOLATE, [i, kind])); images[kind] = im
                                    path = out/f'{key}-{i}-{kind}.png'; im.save(path); captures.append(path)
                                b = extent(images['trail']); stationary = extent(images['stationary'])
                                self.assertIsNotNone(b); self.assertIsNotNone(stationary)
                                self.assertGreater(b[0], 0); self.assertGreater(b[1], 0)
                                self.assertLess(b[2], images['trail'].width-1); self.assertLess(b[3], images['trail'].height-1)
                                raster.append({'extent': b, 'stationaryExtent': stationary,
                                               'bodyExcludedPixels': stationary[1]-b[1], 'clipped': False})
                                bodies[f'{key}-{i}'] = np.array(images['body'])
                            r = page.evaluate(PROBE); r['raster'] = raster; r['scenario'] = settings[key]
                            self.assertEqual(r['extended'], [bound]*3)
                            self.assertEqual(r['collisionEffects'], [1,1,0])
                            self.assertEqual(r['cadence'], [[min(2+j//settings[key]['cyclesPerTick'],bound)]*3 for j in range(24)])
                            for i, hist in enumerate(r['history']):
                                self.assertEqual(hist['count'], bound); self.assertEqual(hist['limit'], bound)
                                self.assertAlmostEqual(hist['distance'], (bound-1)*settings[key]['step'])
                                positions = hist['positions']
                                self.assertTrue(all(abs(b[0]['y']-a[0]['y']-settings[key]['step'])<1e-8 for a,b in zip(positions,positions[1:])))
                                revcheck = r['reversal'][i]
                                self.assertEqual(revcheck['count'], bound); self.assertTrue(revcheck['finite'])
                                self.assertGreater(revcheck['turns'], 2)
                                for j, e in enumerate(revcheck['extrema']):
                                    ys = [p[j]['y'] for p in revcheck['positions']]
                                    self.assertEqual(e, {'min': min(ys), 'max': max(ys)})
                                # Rasterize the actual retraced envelope too (no doubling assertion).
                                im = decoded(page.evaluate(ISOLATE, [i, 'trail']))
                                revcheck['renderedExtent'] = extent(im)
                                self.assertIsNotNone(revcheck['renderedExtent'])
                            r['disabled'] = {}
                            for control in ['track', 'quality']:
                                d = page.evaluate(DISABLE, control)
                                self.assertTrue(all(x['before']==x['after'] for x in d['existing']))
                                self.assertEqual(d['freshCount'], 0 if control=='track' else 1)
                                d['visiblePixels'] = []
                                for i in range(3):
                                    pixels = int((np.array(decoded(page.evaluate(ISOLATE, [i,'trail'])))[:,:,3]>0).sum())
                                    d['visiblePixels'].append(pixels); self.assertEqual(pixels,0)
                                r['disabled'][control] = d
                            measurements[key] = r
                            if phase == 'final':
                                before = measurements['baseline-'+name]
                                self.assertEqual(r['states'], before['states'])
                                r['matchedSimulationStates'] = len(r['states'])
                                old = json.loads(json.dumps(settings['baseline-'+name]))
                                old['settings']['timing']['triangleTrailPoints'] = 150
                                self.assertEqual(settings[key], old)
                                r['ratios'] = []
                                for i in range(3):
                                    self.assertTrue(np.array_equal(bodies[f'{key}-{i}'], bodies[f'baseline-{name}-{i}']))
                                    ratio = r['history'][i]['distance']/before['history'][i]['distance']
                                    pixel_ratio = raster[i]['bodyExcludedPixels']/before['raster'][i]['bodyExcludedPixels']
                                    self.assertAlmostEqual(ratio, 2, delta=.05); self.assertAlmostEqual(pixel_ratio, 2, delta=.05)
                                    r['ratios'].append({'stored':ratio,'rendered':pixel_ratio,'bodyPixelsIdentical':True})
                                print(f'PASS {name}: Triangle pink/red + HarmlessTriangle; samples 75 -> 150; extended=150; '
                                      f'ratios={r["ratios"]}; reversal finite/bounded; disabled pixels=0; '
                                      f'matched motion/collision states={r["matchedSimulationStates"]}; cadence/settings/player/cube unchanged', flush=True)
                            self.assertFalse(errors, errors)
                        finally:
                            context.close()
        sheet = Image.new('RGB', (1280, 1200), '#111111'); d = ImageDraw.Draw(sheet)
        for row, name in enumerate(['bad-desktop','bad-phone','classic-desktop','classic-phone']):
            for col, phase in enumerate(['baseline','final']):
                key=f'{phase}-{name}'; im=native[key].copy(); im.thumbnail((640,270))
                sheet.paste(im,(col*640,row*300+25)); d.text((col*640+10,row*300+5),key,fill='white')
        sheet.save(out/'before-after.png'); captures.append(out/'before-after.png')
        (out/'measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
        files = subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
        files = [f for f in files if f.endswith(('.js','.html'))]+['tools/test_triangle_trail_length.py']
        manifest = {'baseline':base,'sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
                    'settings':settings,'seed':1,'clock':'CLOCK_SCRIPT frozen','dpr':1,
                    'viewports':{'desktop':[1920,1080],'phone':[844,390]},
                    'captures':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in captures}}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('PASS all eight baseline/final mode/viewport probes; no skipped probes',flush=True)


if __name__ == '__main__':
    unittest.main()
