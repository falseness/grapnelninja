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
OUT = Path(os.environ.get('INNER_GLOW_OUT', ROOT / 'artifacts/TASK-206'))
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
        (OUT/'obstacle-probe.json').write_text(json.dumps(report,indent=2)+'\n')
        for mode,data in report['modes'].items():
            self.assertEqual(data['page_errors'],[])
            self.assertEqual(data['obstacleBloomCalls'],0)
            for sample in data['samples']:
                print(mode,sample,flush=True)
                self.assertLessEqual(sample['outside_band_max_delta'],2)
                self.assertGreater(sample['edge'],sample['mid'])
                self.assertGreater(sample['mid'],sample['centre'])
        print('PASS: all outside bands <= 2; edge > mid > centre; obstacle bloom calls = 0',flush=True)


# The pan is an isolated world-space green edge with a rope attached nearby.
# Whole-pixel camera steps eliminate main-canvas subpixel coverage changes;
# the parent bloom still moves through its quarter-resolution sampling grid.
PAN_SETUP = r"""() => {
    startGame('bad'); version='bad'; scale.bad=1; screen.x=screen.y=0;
    visualEffects.particles.drawAmbientMotes=()=>{};
    visualEffects.particles.drawLayer=()=>{};
    visualEffects.playerTrail.drawSmoothPlayerTrailIfEnabled=()=>{};
    visualEffects.playerTrail.shouldDraw=()=>false;
    visualEffects.screenEffects.drawShockwaveGlow=()=>{};
    grapnel.drawHook=()=>{};
    ninja.x=500; ninja.y=240;
    grapnel.throwed=true; grapnel.pos=[[300,240]];
    window.panBlock=new Rect({x:300,y:250,width:200,height:150,
        stroke:STYLE.colors.cube.greenStroke,fill:STYLE.colors.cube.greenFill});
}"""
PAN_FRAME = r"""i => {
    screen.x=-i; screen.y=0;
    ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=1;
    ctx.fillStyle='#14103c';ctx.fillRect(0,0,canvas.width,canvas.height);
    panBlock.draw();grapnel.draw();
    if(STYLE.features.bloom) drawBloomLayer({floors:[],ninja});
    const band=ctx.getImageData(330-i,242,100,17).data;
    const crop=document.createElement('canvas');crop.width=260;crop.height=215;
    crop.getContext('2d').drawImage(canvas,270-i,210,260,215,0,0,260,215);
    return {pixels:Array.from(band),png:crop.toDataURL()};
}"""

class PlayerAndBloomTests(unittest.TestCase):
    def test_player_lines_and_glow_ops(self):
        OUT.mkdir(parents=True,exist_ok=True)
        report={}
        with ExitStack() as stack:
            root,rev=export_rev('worktree',stack.callback)
            url,browser=start_browser_test(root,stack.callback)
            images=[]
            for enabled in (True,False):
                context=browser.new_context(viewport={'width':1920,'height':1080})
                if not enabled:
                    def disable(route):
                        response=route.fetch()
                        route.fulfill(response=response,body=response.text().replace('innerGlow: true','innerGlow: false'))
                    context.route('**/style.js',disable)
                context.add_init_script(SEED_SCRIPT % 1);context.add_init_script(snap.CLOCK_SCRIPT)
                page=context.new_page();page.goto(url+'index.html');snap.boot_frozen(page)
                meta=page.evaluate(r"""() => {
                    startGame('bad');version='bad';scale.bad=1;screen.x=screen.y=0;
                    ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);
                    ninja.x=200;ninja.y=200;ninja.draw();
                    grapnel.throwed=true;grapnel.pos=[[100,400]];ninja.x=500;ninja.y=400;grapnel.draw();
                    const trail=visualEffects.playerTrail;trail.ribbonPathIndex=0;trail.ribbonPaths=[];
                    trail.drawRibbon([{x:100,y:600},{x:300,y:600},{x:500,y:600}],0,10,1);
                    return {radius:ninja.getRingOuterRadius(),ropeWidth:grapnel.getWidth(),
                        trailWidth:10*Math.max(STYLE.trails.player.headWidthRatio,STYLE.trails.player.tailWidthRatio)};
                }""")
                images.append(Image.open(io.BytesIO(snap.png_bytes(page.evaluate('()=>canvas.toDataURL()')))).convert('RGBA'))
                if enabled:
                    report=dict(meta,rev=rev)
                    report['glow_canvas_ops']=page.evaluate(r"""() => {
                        let ops=0;const proto=CanvasRenderingContext2D.prototype,originals={};
                        for(const name of ['drawImage','fill','stroke','fillRect','clearRect']) {
                            originals[name]=proto[name];proto[name]=function(...args){
                                if(visualEffects.bloom.levels.some(l=>l.ctx===this)) ++ops;
                                return originals[name].apply(this,args);
                            };
                        }
                        for(let i=0;i<3;i++)draw();
                        for(const name in originals)proto[name]=originals[name];
                        return ops;
                    }""")
                context.close()
        on,off=images;delta=ImageChops.difference(on,off)
        outside=[];inside=[]
        for y in range(150,250):
            for x in range(150,250):
                d=((x+.5-200)**2+(y+.5-200)**2)**.5
                (outside if d>report['radius']+1 else inside).append(max(delta.getpixel((x,y))))
        report['ninja_outside_edge_delta']=max(outside)
        report['ninja_inner_delta']=max(inside)
        report['ninja_outer_glow_pixels']=sum(
            max(on.getpixel((x,y))[:3]) > 0 for y in range(150,250) for x in range(150,250)
            if ((x+.5-200)**2+(y+.5-200)**2)**.5 > report['radius']+1)
        self.assertGreater(report['ninja_outer_glow_pixels'],0)

        for name,y,width in [('rope',400,report['ropeWidth']),('trail',600,report['trailWidth'])]:
            report[name+'_outside_width_pixels']=sum(max(on.getpixel((x,j))[:3])>0 for x in range(180,420) for j in range(y-40,y+41) if abs(j+.5-y)>width/2+1)
            self.assertGreater(max(on.getpixel((350,y))[:3]),0)
        on.save(OUT/'player-lines.png')
        (OUT/'probe.json').write_text(json.dumps(report,indent=2)+'\n')
        print('PLAYER PROBE',report,flush=True)
        # Cached clipped blur can round one channel by a byte at the sprite edge.
        self.assertLessEqual(report['ninja_outside_edge_delta'],2)
        for key in ('rope_outside_width_pixels','glow_canvas_ops'):
            self.assertEqual(report[key],0,key)
        self.assertGreater(report['ninja_inner_delta'],0)
        # TASK-216: the player ribbon is the explicit outer-glow exception.
        self.assertGreater(report['trail_outside_width_pixels'],0)

    def test_camera_pan(self):
        OUT.mkdir(parents=True,exist_ok=True)
        commits=subprocess.check_output(['git','log','--format=%H','--grep=^TASK-206:'],cwd=ROOT,text=True).splitlines()
        parent=os.environ.get('INNER_GLOW_PAN_PARENT',commits[-1]+'^' if commits else 'HEAD')
        report={'method':'60 frozen-clock frames, scripted camera x=-frame, fixed rope input, green top edge world band x=330..429 y=242..258; mean absolute RGB pixel change', 'runs':{}}
        for label,rev in [('parent',parent),('head','worktree')]:
            dest=OUT/'before-after'/label;dest.mkdir(parents=True,exist_ok=True)
            with ExitStack() as stack:
                root,revision=export_rev(rev,stack.callback)
                url,browser=start_browser_test(root,stack.callback)
                context=browser.new_context(viewport={'width':1920,'height':1080})
                context.add_init_script(SEED_SCRIPT % 1);context.add_init_script(snap.CLOCK_SCRIPT)
                page=context.new_page();page.goto(url+'index.html');snap.boot_frozen(page);page.evaluate(PAN_SETUP)
                changes=[];previous=None
                for i in range(60):
                    frame=page.evaluate(PAN_FRAME,i);pixels=[v for j,v in enumerate(frame['pixels']) if j%4!=3]
                    if previous is not None:changes.append(sum(abs(a-b) for a,b in zip(pixels,previous))/len(pixels))
                    previous=pixels
                    img=Image.open(io.BytesIO(snap.png_bytes(frame['png'])))
                    img.save(dest/f'{i:02d}.png')
                report['runs'][label]={'rev':revision,'frames':60,'changes':changes,'max':max(changes)}
                context.close()
        before=report['runs']['parent']['max'];after=report['runs']['head']['max']
        report['ratio']=after/before if before else None
        (OUT/'flicker.json').write_text(json.dumps(report,indent=2)+'\n')
        print('FLICKER',before,after,report['ratio'],flush=True)
        self.assertGreater(before,0)
        self.assertLessEqual(report['ratio'],.25)

if __name__=='__main__':
    unittest.main()
