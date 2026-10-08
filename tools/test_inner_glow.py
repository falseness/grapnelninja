"""Frozen-clock pixel tests of actual obstacle draw paths in both modes.

Outside bands cover the whole outline, excluding the crisp stroke plus one
pixel. Interior samples follow the normal to the middle of the top edge.
Also captures identical desktop scenes at parent/HEAD for visual comparison.
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import unittest

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get('INNER_GLOW_OUT', ROOT / 'artifacts/TASK-205'))
SCENE = r'''mode => {
    startGame(mode); version = mode; scale[mode] = 1; screen.x = screen.y = 0;

                visualEffects.particles.drawAmbientMotes = () => {};
                visualEffects.particles.drawLayer = () => {};
                visualEffects.playerTrail.drawSmoothPlayerTrailIfEnabled = () => {};
                visualEffects.playerTrail.shouldDraw = () => false;
                visualEffects.screenEffects.drawShockwaveGlow = () => {};
                grapnel.draw = grapnel.drawHook = () => {};
            
    ctx.setTransform(1,0,0,1,0,0); ctx.globalAlpha = 1;
    ctx.fillStyle = '#14103c'; ctx.fillRect(0,0,canvas.width,canvas.height);
    const items = [
        ['green', new Rect({x:100,y:150,width:150,height:140,stroke:STYLE.colors.cube.greenStroke,fill:STYLE.colors.cube.greenFill})],
        ['cube', new Rect({x:350,y:150,width:150,height:140,stroke:STYLE.colors.cube.blueStroke})],
        ['triangle', new Triangle({x:680,y:220,radius:140,yMin:0,yMax:1000,stroke:STYLE.colors.hazard.stroke})],
        ['trampoline', new Trampoline({x:900,y:150,points:[{x:0,y:0},{x:150,y:0},{x:130,y:140},{x:20,y:140}]})],
        ['side', new Side({x:100,y:650,width:300,height:140})],
        ['ground', new Ground({x:500,y:650,points:[{x:0,y:0},{x:0,y:140},{x:300,y:140},{x:300,y:0}]})]
    ];
    const results = [];
    for (const [name,e] of items) {
        ctx.save(); e.draw(); ctx.restore();
        const points = e.getPoints();
        const top = Math.min(...points.map(p=>p.y));
        results.push({name,points,sample:[(Math.min(...points.map(p=>p.x))+Math.max(...points.map(p=>p.x)))/2,top]});
    }
    // Real continuous floor and ceiling paths, including the HUD branch.
    for (const [name, top, bottom, boundary] of [['floor',900,1040,900],['ceiling',400,540,540],['hud-ceiling',20,100,100]]) {
        const bounds = {left:1200,right:1800,top,bottom,boundaryY:boundary};
        const floor = Object.create(SideFloor.prototype);
        floor.getContinuousSurfaceBounds = () => bounds;
        ctx.save();
        if (name === 'hud-ceiling') floor.drawHudZoneCeilingBoundary();
        else floor.drawContinuousSurface();
        ctx.restore();
        results.push({name,points:[{x:1200,y:top},{x:1800,y:top},{x:1800,y:bottom},{x:1200,y:bottom}],
            sample:[1500,boundary],direction:boundary===top?1:-1});
    }
    let obstacleBloomCalls = 0;
    visualEffects.bloom.drawEmissiveShapes({floors:[{drawGlow(){obstacleBloomCalls++},drawTracks(){}}],ninja:{track:{}}});
    return {items:results,coreWidth:STYLE.strokes.neonOutline.width,obstacleBloomCalls};
}'''


def capture(rev, enabled=True):
    result = {}
    with ExitStack() as stack:
        root, revision = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for mode in ('bad', 'classic'):
            context = browser.new_context(viewport={'width':1920,'height':1080})
            if not enabled:
                def disable(route):
                    response = route.fetch()
                    route.fulfill(response=response,body=response.text().replace('innerGlow: true','innerGlow: false'))
                context.route('**/style.js',disable)
            context.add_init_script(SEED_SCRIPT % 1)
            context.add_init_script(snap.CLOCK_SCRIPT)
            page = context.new_page()
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url+'index.html',wait_until='load'); snap.boot_frozen(page)
            # Isolate obstacles from unrelated bloom sources, leaving the real
            # floor dispatch observable when probing drawEmissiveShapes.
            data=page.evaluate(SCENE,mode)
            img=Image.open(io.BytesIO(snap.png_bytes(page.evaluate('() => canvas.toDataURL()')))).convert('RGB')
            result[mode]=(img,dict(data,rev=revision,page_errors=errors))
            context.close()
    return result


class InnerGlowTests(unittest.TestCase):
    def test_clipped_obstacle_pixels(self):
        OUT.mkdir(parents=True,exist_ok=True)
        on,off=capture('worktree'),capture('worktree',False)
        commits=subprocess.check_output(['git','log','--format=%H','--grep=^TASK-205:'],cwd=ROOT,text=True).splitlines()
        parent=os.environ.get('INNER_GLOW_PARENT',commits[-1]+'^' if commits else 'HEAD')
        before=capture(parent)
        sheet=Image.new('RGB',(1600,640),'#14103c');draw=ImageDraw.Draw(sheet)
        report={'parent_rev':before['bad'][1]['rev'], 'modes':{}}
        for row,mode in enumerate(('bad','classic')):
            img,meta=on[mode];other=off[mode][0]
            img.save(OUT/f'probe-{mode}.png')
            report['modes'][mode]=dict(meta,samples=[])
            for item in meta['items']:
                points=item['points']
                box=(int(min(p['x'] for p in points))-20,int(min(p['y'] for p in points))-20,
                     int(max(p['x'] for p in points))+21,int(max(p['y'] for p in points))+21)
                local,local_off=img.crop(box),other.crop(box)
                mask=Image.new('L',local.size)
                ImageDraw.Draw(mask).polygon([(p['x']-box[0],p['y']-box[1]) for p in points],fill=255)
                # Band begins > half the full outline width + 1 pixel away.
                radius=int(meta['coreWidth']/2+1)+1
                inner=mask.filter(ImageFilter.MaxFilter(2*radius+1))
                outer=mask.filter(ImageFilter.MaxFilter(2*(radius+7)+1))
                band=ImageChops.subtract(outer,inner)
                delta=ImageChops.difference(local,local_off)
                measured=Image.composite(delta,Image.new('RGB',local.size),band)
                maximum=max(v[1] for v in measured.getextrema())
                x,y=item['sample'];direction=item.get('direction',1)
                locations=[(round(x),round(y+direction*d)) for d in (5,11)]
                locations.append((round(sum(p['x'] for p in points)/len(points)),
                                  round(sum(p['y'] for p in points)/len(points))))
                values=[sum(img.getpixel(location))/3 for location in locations]
                report['modes'][mode]['samples'].append(dict(name=item['name'],outside_band_max_delta=maximum,sample_pixels=locations,edge=values[0],mid=values[1],centre=values[2]))
            for col,source in enumerate((before[mode][0],img)):
                sheet.paste(source.crop((70,100,870,390)),(col*800,row*320+30))
                draw.text((col*800+10,row*320+8),f'{mode}: {"parent" if col==0 else "HEAD"} green block / cube / triangle',fill='white')
        sheet.save(OUT/'before-after.png')
        (OUT/'probe.json').write_text(json.dumps(report,indent=2)+'\n')
        for mode,data in report['modes'].items():
            self.assertEqual(data['page_errors'],[])
            self.assertEqual(data['obstacleBloomCalls'],0)
            for sample in data['samples']:
                print(mode,sample,flush=True)
                self.assertLessEqual(sample['outside_band_max_delta'],2)
                self.assertGreater(sample['edge'],sample['mid'])
                self.assertGreater(sample['mid'],sample['centre'])
        print('PASS: all outside bands <= 2; edge > mid > centre; obstacle bloom calls = 0',flush=True)

if __name__=='__main__':
    unittest.main()
