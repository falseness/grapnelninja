"""Offline fixed-scene resize/DPR evidence; Chromium emulation, not phone FPS."""
import argparse
import base64
import json
from contextlib import ExitStack
from pathlib import Path
from browser_test_support import start_browser_test, wait_for_boot
from verify_y8_release import point

INSTRUMENT = """() => {
 window.probe = {allocations:0, backingWrites:0, menuRebuilds:0, factoryRebuilds:0};
 const create = Document.prototype.createElement;
 Document.prototype.createElement = function(name,...args) {
   if (name.toLowerCase() === 'canvas') probe.allocations++;
   return create.call(this,name,...args);
 };
 for (const key of ['width','height']) {
   const d = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype,key);
   Object.defineProperty(HTMLCanvasElement.prototype,key,{...d,set(v){probe.backingWrites++;d.set.call(this,v)}});
 }
 const rebuild = rebuildMenu;
 rebuildMenu = function(){probe.menuRebuilds++; return rebuild.apply(this,arguments)};
 const Factory = ElementsFactory;
 ElementsFactory = class extends Factory {constructor(...args){super(...args);probe.factoryRebuilds++}};
} """
SNAPSHOT = """() => {
 const seen = new Set(), canvases = [], maps = [];
 function visit(v,path) {
   if (!v || typeof v !== 'object' || seen.has(v)) return;
   seen.add(v);
   if (v instanceof HTMLCanvasElement) {canvases.push({path,width:v.width,height:v.height});return}
   if (v instanceof CanvasRenderingContext2D) return;
   if (v instanceof Map) {maps.push({path,size:v.size});let i=0; for(const value of v.values())visit(value,path+'['+(i++)+']');return}
   for(const [k,value] of Object.entries(v)) visit(value,path+'.'+k);
 }
 visit(visualEffects,'effects');visit(GLOW_SPRITES.cache,'sprites');
 document.querySelectorAll('canvas').forEach((v,i)=>visit(v,'dom.'+i));
 const times=[];for(let i=0;i<12;i++){const t=performance.now();draw();times.push(performance.now()-t)}
 return {dpr:devicePixelRatio,density:getRenderDensity(),logical:[width,height],css:getCanvasCssRect(),
 backing:[canvas.width,canvas.height],rotated:isViewRotated(),canvases,maps,
 inventory:canvases.length,counters:{...probe},frame_time_samples_ms:times};
} """

def run(root, out):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        for touch in [False, True]:
            for mode in ['bad', 'classic']:
                c = browser.new_context(viewport={'width':960,'height':540}, has_touch=touch, device_scale_factor=1)
                p = c.new_page(); errors=[]
                p.on('pageerror', lambda e: errors.append(str(e)))
                p.goto(url); wait_for_boot(p)
                p.evaluate(INSTRUMENT)
                p.mouse.click(**point(p,'menu.'+mode+'VersionButton.background'))
                p.wait_for_function('!menu.visible && !unTouch')
                # Hold scene and quality constant; timings below are CPU draw submission only.
                p.evaluate('cancelAnimationFrame(game); RENDER_BUDGET.densityLimit=Infinity; onViewportResize(); draw()')
                cd = c.new_cdp_session(p)
                def size(w,h,dpr):
                    p.set_viewport_size(dict(width=w,height=h))
                    cd.send('Emulation.setDeviceMetricsOverride',dict(width=w,height=h,deviceScaleFactor=dpr,mobile=False))
                    p.wait_for_timeout(180)
                    p.evaluate('draw()')
                samples=[]; inventories=[]
                configs=[(960,540,1),(640,540,1),(390,844,2),(844,390,3)]
                # Warm every cache key before assessing retention over ten complete cycles.
                for w,h,dpr in configs: size(w,h,dpr)
                for cycle in range(10):
                    counts=[]
                    for phase,(w,h,dpr) in enumerate(configs):
                        size(w,h,dpr)
                        snap=p.evaluate(SNAPSHOT)
                        assert snap['dpr']==dpr
                        assert snap['backing']==[max(1, int(x*min(dpr,2)+.5)) for x in [snap['css']['width'],snap['css']['height']]], snap
                        # Independent DOM bounding rectangle mapping, including clockwise portrait.
                        target=p.evaluate('''() => {const r=canvas.getBoundingClientRect(),u=.65,v=.3;
                          return {x:r.left+r.width*(isViewRotated()?1-v:u),y:r.top+r.height*(isViewRotated()?u:v),
                            expected:{x:width*u/scale[version]-screen.x,y:height*v/scale[version]-screen.y}}}''')
                        p.mouse.move(target['x'],target['y']);p.mouse.down()
                        coord=p.evaluate('''() => ({throwed:grapnel.throwed,origin:grapnel.pos[0].slice(0,2),
                          ninja:[ninja.x,ninja.y],speed:[grapnel.speedX,grapnel.speedY]})''')
                        assert coord['throwed'] and coord['origin']==coord['ninja'],coord
                        import math
                        dx=target['expected']['x']-coord['ninja'][0];dy=target['expected']['y']-coord['ninja'][1]
                        norm=math.hypot(*coord['speed']); dist=math.hypot(dx,dy)
                        assert abs(coord['speed'][0]/norm-dx/dist)<.005 and abs(coord['speed'][1]/norm-dy/dist)<.005,coord
                        p.evaluate('grapnel.move();draw()')
                        endpoint=p.evaluate('grapnel.pos[0].slice(0,2)')
                        assert all(abs(endpoint[i]-coord['origin'][i]-coord['speed'][i])<1e-7 for i in range(2))
                        if cycle in [0,9]:
                            name=f'{mode}-{"touch" if touch else "desktop"}-{cycle}-{phase}.png'
                            (out/name).write_bytes(base64.b64decode(cd.send('Page.captureScreenshot', {'format':'png'})['data']));snap['capture']=name
                        p.mouse.up()
                        snap.update(cycle=cycle,phase=phase,requested=[w,h,dpr],coordinate={'expected_world':target['expected'],**coord,'endpoint':endpoint,'result':'PASS'})
                        samples.append(snap);counts.append(snap['inventory'])
                    inventories.append(counts)
                assert all(x==inventories[0] for x in inventories),inventories
                # Settled duplicate resize must not allocate/reset/rebuild resources.
                before=p.evaluate('({...probe})')
                p.evaluate("window.dispatchEvent(new Event('resize'))")
                p.wait_for_timeout(180);p.evaluate('draw()')
                after=p.evaluate('({...probe})')
                assert before==after,(before,after)
                # DPR-only transition on unchanged CSS viewport (paused RAF).
                size(844,390,1)
                dpr_only=p.evaluate(SNAPSHOT)
                assert dpr_only['backing']!=samples[-1]['backing']
                assert dpr_only['css']==samples[-1]['css']
                assert not errors, errors
                rows.append(dict(mode=mode,touch=touch,browser=browser.version,samples=samples,dpr_only=dpr_only,
                                 duplicate_resize={'before':before,'after':after,'result':'PASS'},inventories=inventories,errors=errors))
                (out/'resize-profile.json').write_text(json.dumps({'limitations':'Fixed scene, fixed native/capped density; CPU draw samples are not FPS. Chromium emulation; physical phones unavailable. External network blocked.', 'runs':rows},indent=2)+'\n')
                print(f'PASS {mode} touch={touch}: ten resize cycles; stable canvas/cache inventory {inventories[0]}; coordinates/grapple endpoints; captures; DPR 1/2/3; duplicate resize zero allocation/rebuild; DPR-only backing update',flush=True)
                c.close()
    print('PASS resize-profile.json: canvas/offscreen dimensions, allocation/rebuild counters, before/after frame-time samples and DPR changes',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();run(a.root,a.out)
