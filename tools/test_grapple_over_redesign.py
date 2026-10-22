"""TASK-557 baseline only: production observations, not continuous gameplay.

Run with GRAPPLE_OVER_EVIDENCE_DIR pointing at this task's evidence directory.
No runtime code is changed. Future redesign tests must not overwrite this baseline.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest

from PIL import Image, ImageDraw
from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, STATE, source_hashes
from perf_mobile import SEED_SCRIPT

VIEWPORT = {'width': 1280, 'height': 720}

MEASURE = '''() => {
 const w=floors[0], all=[...w.elements,...w.dragZones];
 const elements=all.map(e=>{const p=e.getPoints(); const xs=p.map(p=>p.x),ys=p.map(p=>p.y);
 return {id:e.id,role:e.surfaceRole,points:p,left:Math.min(...xs),right:Math.max(...xs),
 top:Math.min(...ys),bottom:Math.max(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};});
 const cross=(a,b,c)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
 const on=(a,b,p)=>Math.abs(cross(a,b,p))<1e-8 && p.x>=Math.min(a.x,b.x)&&p.x<=Math.max(a.x,b.x)&&p.y>=Math.min(a.y,b.y)&&p.y<=Math.max(a.y,b.y);
 const hit=(a,b,c,d)=> (cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0)||on(a,b,c)||on(a,b,d)||on(c,d,a)||on(c,d,b);
 const overlap=(a,b)=>a.points.some(p=>pointInPolygon(b.points,p.x,p.y))||b.points.some(p=>pointInPolygon(a.points,p.x,p.y))||a.points.some((p,i)=>b.points.some((q,j)=>hit(p,a.points[(i+1)%a.points.length],q,b.points[(j+1)%b.points.length])));
 const intersections=[];
 for(const z of elements.filter(e=>e.role==='drag')) for(const e of elements.filter(e=>e.role!=='drag')) if(overlap(z,e)) intersections.push([z.id,e.id]);
 const movers=w.level.movers.map(m=>{const values=[0,.5].map(phase=>{w.applyMovers((phase-m.phase+1)*m.periodMs);return w.byId.get(m.element)[m.axis]});
 return {...m,observedMin:Math.min(...values),observedMax:Math.max(...values),travel:Math.max(...values)-Math.min(...values)};});
 w.applyMovers(0);
 return {range:MODE_DEFINITIONS.grapple_over,cameraScale:scale[version],player:{radius:ninja.radius,diameter:ninja.radius*2},
 constants:{gravity:GRAVITY,pull:grappleSpeed,throwSpeed:grapnelSpeed,cyclesPerTick,physicsStepMs},bounds:w.level.bounds,elements,movers,
 yellowColliderIntersections:intersections,observationTimeMs:w.elapsedSteps*physicsStepMs/cyclesPerTick,intersectionScope:'polygon intersection including touching boundaries at initial fixture time; not swept-volume coverage',
 sections:GRAPPLE_OVER_MOUNTAIN.sections.map(s=>({id:s.id,band:s.band,gaps:s.gaps}))};
}'''


class Task557Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('GRAPPLE_OVER_EVIDENCE_DIR', ROOT / 'artifacts/TASK-557')).resolve()
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.hashes = source_hashes()
        cls.hashes['tools/test_grapple_over_redesign.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        cls.config = dict(revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                          source_hashes=cls.hashes, browser=cls.browser.version, viewport=VIEWPORT,
                          device_scale_factor=1, seed=1, simulation='rAF disabled; explicit production physics; isolated fixtures')
        with (cls.out/'commands.log').open('a') as f:
            f.write('CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    def write(self, name, obj):
        (self.out/name).write_text(json.dumps(obj,separators=(',',':'))+'\n')

    def page(self, mode='grapple_over'):
        ctx=self.browser.new_context(viewport=VIEWPORT,device_scale_factor=1)
        self.addCleanup(ctx.close)
        p=ctx.new_page()
        errors=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        self.addCleanup(lambda:self.assertEqual(errors,[]))
        p.add_init_script(SEED_SCRIPT % 1)
        p.goto(self.url)
        wait_for_boot(p)
        p.evaluate('cancelAnimationFrame(game); window.requestAnimationFrame=()=>0')
        p.evaluate(SEED_SCRIPT % 1)
        p.evaluate('m=>{startGame(m);cancelAnimationFrame(game)}',mode)
        p.wait_for_function('!unTouch')
        return p

    def test_01_runtime_measurements(self):
        p=self.page()
        b=p.evaluate(MEASURE)
        self.assertEqual(b['cameraScale'],.375)
        self.assertEqual([b['range']['acquisitionRadius'],b['range']['upgradedAcquisitionRadius']],[1080,1620])
        self.assertGreater(b['player']['diameter'],0)
        self.assertGreater(len(b['elements']),0)
        self.assertGreater(len(b['yellowColliderIntersections']),0)
        for m in b['movers']:
            self.assertAlmostEqual(m['travel'],m['max']-m['min'])
        b.update(self.config)
        self.write('baseline.json',b)
        print('PASS runtime range=1080/1620 camera=0.375 elements=%d movers=%d yellow/collider=%d' % (len(b['elements']),len(b['movers']),len(b['yellowColliderIntersections'])))

    def test_02_actual_layout_captures(self):
        p=self.page()
        poses=p.evaluate('''() => GRAPPLE_OVER_MOUNTAIN.sections.map(s=>({id:s.id,...s.gaps[0].from}))''')
        sheet=Image.new('RGB',(1280,4*390),'#111111')
        for i,pose in enumerate(poses):
            p.evaluate('''p=>{ninja.x=p.x;ninja.y=p.y;screen.x=width/scale[version]/2-p.x;screen.y=height/scale[version]/2-p.y;draw()}''',pose)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB'); im.thumbnail((640,360))
            x,y=(i%2)*640,(i//2)*390
            sheet.paste(im,(x,y+30)); ImageDraw.Draw(sheet).text((x+10,y+8),pose['id']+' approach fixture, scale .375',fill='white')
        sheet.save(self.out/'approaches.jpg',quality=85)
        result=p.evaluate('''() => {
 const b=floors[0].level.bounds,k=scale[version],vw=width/k,vh=height/k,z=.12,top=b.top-1200;
 const map=document.createElement('canvas');map.width=Math.ceil((b.right-b.left)*z);map.height=Math.ceil((b.bottom-top)*z);const c=map.getContext('2d');
 const saved=[drawUILayer,drawFpsCounterLayer,drawAcquisitionCircle];drawUILayer=drawFpsCounterLayer=drawAcquisitionCircle=()=>{};
 let tiles=0;for(let y=top;y<b.bottom;y+=vh)for(let x=b.left;x<b.right;x+=vw){screen.x=-x;screen.y=-y;ninja.x=x+vw/2;ninja.y=y-vh*4;draw();tiles++;c.drawImage(canvas,(x-b.left)*z,(y-top)*z,vw*z,vh*z)}
 [drawUILayer,drawFpsCounterLayer,drawAcquisitionCircle]=saved;
 return {png:map.toDataURL(),tiles,bounds:b,top,mapScale:z};}''')
        (self.out/'overview.png').write_bytes(base64.b64decode(result.pop('png').split(',')[1]))
        self.write('capture-config.json',dict(approaches=poses,overview=result,limitations='camera/player placements are visual fixtures, not earned gameplay'))
        for name in ['overview.png','approaches.jpg']:
            with Image.open(self.out/name) as im:
                im.load(); self.assertGreater(im.width*im.height,100000)
                self.assertGreater(len(im.convert('RGB').getcolors(im.width*im.height)),100)
        print('PASS decoded actual production overview.png and approaches.jpg; 8 approach fixtures')

    def test_03_seeded_old_modes(self):
        result={'config':self.config,'fixture':'seed=1, 12 production ticks; trusted mouse press at (900,200), 3 ticks, release; flat/sloped isolated collision fixtures','modes':{}}
        for mode in ['classic','bad']:
            runs=[]
            for repeat in range(2):
                p=self.page(mode)
                movement=p.evaluate('''() => {let a=[];for(let i=0;i<12;i++){physics();a.push((STATE)())}return a}'''.replace('STATE',STATE))
                p.mouse.move(900,200);p.mouse.down()
                self.assertTrue(p.evaluate('grapnel.throwed'))
                shot=p.evaluate('''() => {for(let i=0;i<3;i++)physics();return (STATE)()}'''.replace('STATE',STATE))
                p.mouse.up();self.assertFalse(p.evaluate('grapnel.throwed'))
                collisions=[]
                for slope in [0,-.5]:
                    c=p.evaluate('''slope=>{for(const f of floors)f.elements=[]; const x=width*.4,y=height*.6,w=width*.2;
 const t=new Trampoline({x,y,points:[{x:0,y:120},{x:0,y:0},{x:w,y:slope*w},{x:w,y:slope*w+120}]});floors[1].elements=[t];
 const norm=Math.hypot(slope,1),nx=slope/norm,ny=-1/norm;
 Object.assign(ninja,{x:x+w/2+nx*(ninja.radius-2),y:y+slope*w/2+ny*(ninja.radius-2),speedX:-nx*9,speedY:-ny*9});
 const before=(STATE)();ninja.collision();return {slope,before,after:(STATE)(),incoming:before.speedX*nx+before.speedY*ny,outgoing:ninja.speedX*nx+ninja.speedY*ny,contact:!!ninja.bounce};}'''.replace('STATE',STATE),slope)
                    self.assertTrue(c['contact']);self.assertLess(c['incoming'],0);self.assertGreater(c['outgoing'],0)
                    collisions.append(c)
                constants=p.evaluate('() => ({gravity:GRAVITY,pull:grappleSpeed,throwSpeed:grapnelSpeed,cyclesPerTick,physicsStepMs,cameraScale:scale[version]})')
                runs.append(dict(movement=movement,shot=shot,bounces=collisions,constants=constants))
            self.assertEqual(runs[0],runs[1]);self.assertNotEqual(runs[0]['movement'][0]['y'],runs[0]['movement'][-1]['y'])
            result['modes'][mode]=runs[0]
            print('PASS '+mode+' seeded replay equal: 12 movement ticks, trusted throw/release, flat/sloped bounce')
        self.write('old-modes.json',result)

    def test_04_warmed_baseline_cost(self):
        rows=[]
        for mode in ['classic','bad','grapple_over']:
            for repeat in range(2):
                p=self.page(mode)
                row=p.evaluate('''() => {for(let i=0;i<120;i++){physics();draw()}
 const samples=[];for(let i=0;i<180;i++){let t=performance.now();physics();let u=performance.now();draw();samples.push([u-t,performance.now()-u])}
 return {samples,final:{x:ninja.x,y:ninja.y},logical:{width,height},cameraScale:scale[version]};}''')
                self.assertEqual(len(row['samples']),180)
                row.update(mode=mode,repeat=repeat)
                rows.append(row)
        self.write('baseline-perf.json',dict(config=self.config,warmup_ticks=120,measured_ticks=180,repeats=2,runs=rows,
            limitations='Short headless shared-host component timings, not device FPS or a difficulty estimate. No A/B speedup claim. Future comparison must match browser, viewport, seed, warmup, ticks, host and scene.'))
        print('PASS warmed matched baseline: 3 modes x 2 seeded runs x 180 measured ticks; warmup=120')


class Task558Tests(unittest.TestCase):
    """Isolated development fixtures; these are not continuous gameplay proof."""
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('GRAPPLE_OVER_EVIDENCE_DIR', ROOT / 'artifacts/TASK-558')).resolve()
        if not cls.out.is_relative_to((ROOT / 'artifacts').resolve()):
            raise ValueError('Evidence must be under artifacts/')
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        hashes['tools/test_grapple_over_redesign.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        cls.config = dict(revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                          source_hashes=hashes, browser=cls.browser.version, viewport=VIEWPORT,
                          device_scale_factor=1, seed=1, simulation='isolated fixtures, production physics and trusted mouse input')
        with (cls.out/'commands.log').open('a') as f:
            f.write('CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write

    def page(self, preview=True):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(context.close)
        p = context.new_page()
        errors = []
        p.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        p.add_init_script(SEED_SCRIPT % 1)
        if preview:
            p.add_init_script("localStorage.setItem('grapnelninja.grappleOver', 'legacy-save-sentinel')")
        p.goto(self.url + ('?grapplePreview=replacement-v1' if preview else ''))
        wait_for_boot(p)
        p.evaluate('cancelAnimationFrame(game); window.requestAnimationFrame=()=>0')
        p.wait_for_function('!unTouch')
        return p

    def press(self, p, x, y):
        xy = p.evaluate('p=>canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]})',dict(x=x,y=y))
        p.mouse.move(xy['x'],xy['y']); p.mouse.down()
        self.assertTrue(p.evaluate('grapnel.throwed'))

    def test_01_profiles_and_save_isolation(self):
        rows = []
        for preview in [False, True, False]:
            p = self.page(preview)
            for mode in ['boot','classic','bad','grapple_over']:
                if mode != 'boot':
                    p.evaluate('m=>{startGame(m);cancelAnimationFrame(game)}',mode)
                row = p.evaluate('''() => ({mode:version, layoutId:floors[0].level?.layoutId ?? null,
                    persistent:floors[0] instanceof PersistentWorld, camera:scale[version],
                    range:version==='grapple_over' ? grappleOverAcquisitionRadius():null,
                    profile:version==='grapple_over' ? grappleOverProfile():MODE_DEFINITIONS[version],
                    gravity:GRAVITY,pull:grappleSpeed})''')
                row['preview'] = preview; rows.append(row)
                climb = mode in ['boot','grapple_over']
                self.assertEqual(row['persistent'],climb)
                self.assertEqual(row['camera'],.375 if climb else 1 if mode=='classic' else 1/2.2)
                self.assertEqual(row['range'],(360 if preview else 1080) if climb else None)
                self.assertEqual(row['layoutId'],('grapple-over-replacement-v1' if preview else 'grapple-over-legacy-v3') if climb else None)
                if climb:
                    self.assertEqual(row['profile']['upgradedAcquisitionRadius'],540 if preview else 1620)
            if preview:
                p.evaluate('PROGRESS.resetClimb();physics();PROGRESS.flushClimb()')
                p.wait_for_timeout(1200)
                saved = p.evaluate("localStorage.getItem('grapnelninja.grappleOver')")
                self.assertEqual(saved,'legacy-save-sentinel')
                self.assertFalse(p.evaluate("!!document.getElementById('climb-save-notice')"))
        self.assertEqual(len(set((r['gravity'],r['pull']) for r in rows)),1)
        self.write('profiles.json',dict(config=self.config,rows=rows,saved=saved))
        self.write('preview-contract.json',dict(invocation='http://127.0.0.1:<port>/?grapplePreview=replacement-v1',
            allowedHosts=['localhost','127.0.0.1','[::1]'],mode='grapple_over',layoutId='grapple-over-replacement-v1',
            persistence='preview never restores or writes the legacy climb save',loader='loadMountainLevel -> replacementMountainLevel -> loadFixedLevel',
            prefix='Only built sections and their referenced encounters/elements/movers load; built after planned is rejected; unfinished prefix has null finish.',
            fixture='S01 green catch and anchor only; S05 planned and noncolliding; not continuous gameplay',
            ranges=[360,540],camera=.375,
            dependencies=['gameoptions.js profile and local selector','mountain.js loader and preview manifest','physics.js upgrade profile','progress.js save isolation','render/landmarks.js legacy landmark exclusion','tools/test_grapple_over_redesign.py'],
            historicalCoverage='TASK-557 and earlier v3 geometry evidence remains legacy-only; no historical tests removed or rerun.'))
        print('PASS profiles: 12 boot/mode observations, legacy 1080/1620, preview 360/540, classic/bad unchanged; saved=legacy-save-sentinel')

    def test_02_built_prefix_and_real_input(self):
        p = self.page()
        result = p.evaluate('''() => {
            startGame('grapple_over');cancelAnimationFrame(game);
            const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const filtered=loadMountainLevel(m).level;
            let invalid; m.sections.reverse();
            try{loadMountainLevel(m)}catch(e){invalid=e.message}
            return {layoutId:floors[0].level.layoutId,spawn:{x:ninja.x,y:ninja.y},
                declaredBuilt:GRAPPLE_OVER_REPLACEMENT.encounters[0].elements,
                colliders:floors[0].elements.map(e=>({id:e.id,role:e.surfaceRole})),
                sections:floors[0].level.sections.map(s=>s.id),finish:filtered.finish,invalid};
        }''')
        self.assertEqual([e['id'] for e in result['colliders']],result['declaredBuilt'])
        self.assertTrue(all(e['role']=='bounce' for e in result['colliders']))
        self.assertEqual(result['sections'],['S01']);self.assertIsNone(result['finish'])
        self.assertIn('InvalidBuiltPrefix',result['invalid'])
        self.press(p,2520,0)
        trace = p.evaluate('''() => {const rows=[];for(let i=0;i<6;i++){physics();rows.push({tick:i+1,x:ninja.x,y:ninja.y,
            attached:grapnel.isGrappled(),target:grapnel.pos[0]?.[2]?.id ?? null,traveled:grapnel.traveled,
            range:grappleOverAcquisitionRadius(),completed:floors[0].climbStats.completed})}return rows}''')
        self.assertTrue(any(r['attached'] and r['target']=='preview-anchor' for r in trace))
        self.assertTrue(all(r['traveled']<=360 and r['range']==360 and not r['completed'] for r in trace))
        p.evaluate('screen.x=width/scale[version]/2-ninja.x;screen.y=height/scale[version]/2-ninja.y;TUTORIAL_HINT.visible=false;draw()');p.screenshot(path=str(self.out/'preview.png'))
        p.mouse.up()
        # Probe the legacy summit and the unbuilt upgrade band with production ticks.
        probes = p.evaluate('''() => [{x:2400,y:-13200},{x:2160,y:-2200}].map(p=>{
            Object.assign(ninja,{...p,speedX:0,speedY:0});physics();
            return {pose:p,completed:floors[0].climbStats.completed,range:grappleOverAcquisitionRadius()}})''')
        self.assertTrue(all(not r['completed'] and r['range']==360 for r in probes))
        with Image.open(self.out/'preview.png') as im:
            im.load();self.assertEqual(im.size,(1280,720))
        self.write('preview.json',dict(**result,trace=trace,probes=probes,fixture='Production spawn and trusted mouse grapple; capture centers camera and hides tutorial only; later poses are isolated completion probes'))
        print('PASS preview: only preview-catch/preview-anchor, real-input grapple at range 360, planned S05 excluded, null finish, no summit completion; preview.png decoded 1280x720')

    def test_03_range_consumers_and_attached_rope(self):
        p = self.page()
        rows=[]
        for upgraded,radius in [(False,360),(True,540)]:
            p.evaluate('''upgraded=>{startGame('grapple_over');cancelAnimationFrame(game);
                floors[0].rangeUpgraded=upgraded;Object.assign(ninja,{x:2160,y:-600,speedX:0,speedY:0});screen.trackGrappleOver(true)}''',upgraded)
            self.press(p,3000,-600)
            row=p.evaluate('''() => {for(let i=0;i<8;i++)physics();
                const arcs=[],original=ctx.arc;ctx.arc=function(...a){arcs.push(a[2]);return original.apply(this,a)};
                try{drawAcquisitionCircle()}finally{ctx.arc=original}
                return {range:grappleOverAcquisitionRadius(),traveled:grapnel.traveled,parked:grapnel.isParked(),
                    attached:grapnel.isGrappled(),heldReach:Math.hypot(grapnel.pos[0][0]-ninja.x,grapnel.pos[0][1]-ninja.y),arcs};}''')
            self.assertEqual(row['range'],radius);self.assertEqual(row['traveled'],radius)
            self.assertAlmostEqual(row['heldReach'],radius);self.assertTrue(row['parked']);self.assertFalse(row['attached'])
            self.assertEqual(row['arcs'],[radius]);p.mouse.up()
            # Acquisition boundary from real input; one unit outside remains unacquired.
            row['boundary'] = []
            for distance in [radius+1,radius]:
                p.evaluate('''d=>{Object.assign(ninja,{x:2520-d,y:0,speedX:0,speedY:0});screen.trackGrappleOver(true)}''',distance)
                self.press(p,2520,0)
                attached=p.evaluate('''() => {for(let i=0;i<4;i++)physics();return grapnel.isGrappled()}''')
                row['boundary'].append(dict(distance=distance,attached=attached))
                self.assertEqual(attached,distance==radius)
                if attached:
                    rope=p.evaluate('''() => {ninja.x-=800;physics();return {attached:grapnel.isGrappled(),length:Math.hypot(grapnel.pos[0][0]-ninja.x,grapnel.pos[0][1]-ninja.y)}}''')
                    self.assertTrue(rope['attached']);self.assertGreater(rope['length'],radius)
                    row['attachedBeyondRange']=rope
                p.mouse.up()
            rows.append(row)
        upgrade=p.evaluate("""() => {
            const manifest=structuredClone(GRAPPLE_OVER_REPLACEMENT);
            manifest.sections[1].status='built';
            floors=[loadMountainLevel(manifest)];
            Object.assign(ninja,{x:2160,y:-2300,speedX:0,speedY:0});
            const before=grappleOverAcquisitionRadius();physics();
            const after=grappleOverAcquisitionRadius();
            ninja.y=0;physics();
            return {before,after,retained:grappleOverAcquisitionRadius(),noticeMs:floors[0].rangeNoticeMs,
                fixture:'Isolated future S05 built flag to exercise production upgrade trigger, not authored gameplay'};
        }""")
        self.assertEqual([upgrade['before'],upgrade['after'],upgrade['retained']],[360,540,540])
        self.assertGreater(upgrade['noticeMs'],0)
        self.write('ranges.json',dict(consumers=rows,upgrade=upgrade))
        print('PASS ranges: 360/540 acquisition boundary, shot travel, held reach, drawn circle; attached rope remains attached beyond range')


class Task559Tests(unittest.TestCase):
    """Reduced-range isolated fixtures, not continuous mountain gameplay.

    Historical v3 geometry remains covered by its archived tests. These tests
    exercise the replacement profile without activating it or building S05.
    """
    @classmethod
    def setUpClass(cls):
        # Share lifetime/configuration only, never inherit historical test cases.
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task559Tests')
        Task558Tests.setUpClass.__func__(cls)

    write = Task557Tests.write
    press = Task558Tests.press

    def page(self, preview=True, touch=False):
        if isinstance(preview, str):
            return Task557Tests.page(self, preview)
        viewport = {'width':844,'height':390} if touch else VIEWPORT
        ctx = self.browser.new_context(viewport=viewport, device_scale_factor=1, has_touch=touch)
        self.addCleanup(ctx.close)
        p = ctx.new_page()
        errors = []
        p.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        p.add_init_script(SEED_SCRIPT % 1)
        p.goto(self.url + ('?grapplePreview=replacement-v1' if preview else ''))
        wait_for_boot(p)
        p.evaluate("cancelAnimationFrame(game);window.requestAnimationFrame=()=>0;startGame('grapple_over');menu.unPause()")
        p.wait_for_function('!unTouch')
        return p

    def earn(self, p):
        return p.evaluate('''() => {
            const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
            m.sections[1].status='built';
            // A declared isolated zone, independent of final S05 geometry.
            m.sections[1].rangeUpgradeZone={left:2100,right:2300,top:-2300,bottom:-2200};
            floors=[loadMountainLevel(m)];
            Object.assign(ninja,{x:2200,y:-2301,speedX:0,speedY:2});
            const trace=[];
            for(let i=0;i<4;i++){const before={y:ninja.y,range:grappleOverAcquisitionRadius()};
                calcPhysics();trace.push({before,y:ninja.y,range:grappleOverAcquisitionRadius(),notice:floors[0].rangeNoticeMs})}
            return {zone:m.sections[1].rangeUpgradeZone,trace};
        }''')

    def test_01_range_and_rendered_circle(self):
        rows=[]
        for touch in [False,True]:
            p=self.page(touch=touch)
            for radius in [360,540]:
                earned=self.earn(p) if radius==540 else None
                for name,targets,expected in [
                    ('inside',[dict(distance=radius-1,id='inside')],'inside'),
                    ('outside',[dict(distance=radius+1,id='outside')],None),
                    ('nearest',[dict(distance=200,id='far'),dict(distance=100,id='near')],'near'),
                    ('blocker',[dict(distance=200,id='far'),dict(distance=100,id='blocker',grapplable=False)],None)]:
                    p.evaluate('''targets=>{
                        for(const f of floors)f.elements=[];screen.leftWall=null;
                        Object.assign(ninja,{x:1000,y:1000,speedX:0,speedY:0});screen.trackGrappleOver(true);
                        floors[0].elements=targets.map(t=>{const e=new Rect({x:1000+t.distance,y:900,width:.1,height:200});
                            e.id=t.id;e.grapplable=t.grapplable!==false;return e});
                    }''',targets)
                    if touch:
                        xy=p.evaluate('canvasCoordsToViewportCoords({x:(1500+screen.x)*scale[version],y:(1000+screen.y)*scale[version]})')
                        session=p.context.new_cdp_session(p)
                        session.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[xy]))
                    else:
                        self.press(p,1500,1000)
                    row=p.evaluate('''() => {
                        let steps=0;for(;steps<120&&!grapnel.grappled&&!grapnel.isParked();steps++){grapnel.move();grapnel.collision()}
                        for(let i=0;i<3;i++){grapnel.move();grapnel.collision()}
                        return {steps,range:grappleOverAcquisitionRadius(),target:grapnel.grappled?grapnel.pos[0][2].id:null,
                            traveled:grapnel.traveled,parked:grapnel.isParked(),heldReach:Math.hypot(grapnel.pos[0][0]-ninja.x,grapnel.pos[0][1]-ninja.y),clip:grapnel.clip};
                    }''')
                    self.assertGreater(row['steps'],0);self.assertEqual(row['target'],expected)
                    self.assertLessEqual(row['traveled'],radius)
                    if expected is None:
                        self.assertTrue(row['parked']);self.assertAlmostEqual(row['heldReach'],radius)
                        self.assertEqual(row['traveled'],radius)
                    if name=='blocker': self.assertAlmostEqual(row['clip']['x'],1100)
                    if touch:
                        session.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]));session.detach()
                    else: p.mouse.up()
                    row.update(name=name,targets=targets,touch=touch,earned=earned)
                    rows.append(row)
                circle=p.evaluate('''() => {
                    const original=ctx,c=document.createElement('canvas');c.width=canvas.width;c.height=canvas.height;
                    ctx=c.getContext('2d');const k=canvas.width/width*scale[version];ctx.scale(k,k);
                    ninja.x=1000;ninja.y=1000;screen.x=width/scale[version]/2-1000;screen.y=height/scale[version]/2-1000;
                    drawAcquisitionCircle();const pixels=ctx.getImageData(0,0,c.width,c.height).data;
                    const y=Math.floor(c.height/2),xs=[];
                    for(let x=0;x<c.width;x++)if(pixels[(y*c.width+x)*4+3])xs.push(x);
                    ctx=original;return {range:grappleOverAcquisitionRadius(),camera:scale[version],
                        canvasWidth:c.width,cssWidth:getCanvasCssRect().width,viewport:[innerWidth,innerHeight],
                        expectedPixels:grappleOverAcquisitionRadius()*k,measuredPixels:(xs.at(-1)-xs[0])/2,
                        edgePixels:xs.length,centerAlpha:pixels[(y*c.width+Math.floor(c.width/2))*4+3]};
                }''')
                self.assertGreater(circle['edgePixels'],0);self.assertEqual(circle['centerAlpha'],0)
                self.assertEqual(circle['camera'],.375)
                self.assertLessEqual(abs(circle['measuredPixels']-circle['expectedPixels']),1)
                rows[-1]['circle']=circle
        self.write('range.json',dict(config=self.config,observations=rows))
        print('PASS range: 16 desktop/touch cases; inside/outside 360/540, nearest, blockers, parked travel/reach; 4 raster circle radii within 1 pixel')

    def test_02_upgrade_lifecycle(self):
        p=self.page();earned=self.earn(p)
        self.assertEqual(earned['trace'][0]['before']['range'],360)
        self.assertEqual(earned['trace'][-1]['range'],540)
        self.assertLess(earned['trace'][0]['before']['y'],earned['zone']['top'])
        self.assertGreaterEqual(earned['trace'][0]['y'],earned['zone']['top'])
        row=p.evaluate('''() => {
            ninja.speedY=-5;for(let i=0;i<100;i++)calcPhysics();
            const persisted={y:ninja.y,range:grappleOverAcquisitionRadius(),flag:floors[0].rangeUpgraded};
            const saved=captureClimbState();restoreClimbState(saved);
            const restored={range:grappleOverAcquisitionRadius(),flag:floors[0].rangeUpgraded,exact:JSON.stringify(saved)===JSON.stringify(captureClimbState())};
            startGame('grapple_over');const restart=grappleOverAcquisitionRadius();
            return {persisted,restored,restart};
        }''')
        self.assertEqual(row['persisted']['range'],540);self.assertTrue(row['restored']['exact'])
        self.assertTrue(row['restored']['flag']);self.assertEqual(row['restored']['range'],540);self.assertEqual(row['restart'],360)
        modes=[]
        for mode in ['classic','bad']:
            self.earn(p)
            modes.append(p.evaluate('''m=>{startGame(m);const during=version;startGame('grapple_over');
                return {during,range:grappleOverAcquisitionRadius(),flag:floors[0].rangeUpgraded}}''',mode))
        self.assertTrue(all(r['range']==360 and not r['flag'] for r in modes))
        self.write('upgrade.json',dict(earned=earned,**row,modeChanges=modes))
        print('PASS upgrade: physical entry 360 -> 540, retained 100 steps, exact current-state restore, restart and classic/bad roundtrip -> 360')

    def test_03_classic_bad_baseline(self):
        Task557Tests.test_03_seeded_old_modes(self)
        path=self.out/'old-modes.json'
        actual=json.loads(path.read_text())
        baseline=ROOT/'artifacts/TASK-557/old-modes.json'
        expected=json.loads(baseline.read_text())
        self.assertEqual(actual['modes'],expected['modes'])
        actual.update(baseline=str(baseline.relative_to(ROOT)),baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),equal=True)
        self.write('old-mode-check.json',actual)
        path.unlink()
        print('PASS classic/bad: exact TASK-557 baseline movement, shot, bounce and physics constants')

    def test_04_attached_and_wrapped_profile_comparison(self):
        traces=[]
        for preview in [False,True]:
            p=self.page(preview)
            p.evaluate('''() => {
                floors[0].elements=[];screen.leftWall=null;
                Object.assign(ninja,{x:800,y:700,speedX:0,speedY:0});screen.trackGrappleOver(true);
                for(const [id,x,y,w,h] of [['anchor',1100,680,30,40],['corner',900,800,80,50]]){
                    const e=new Rect({x,y,width:w,height:h});e.id=id;e.surfaceRole='solid';floors[0].elements.push(e)}
            }''')
            self.press(p,1100,700)
            row=p.evaluate('''() => {
                for(let i=0;i<100&&!grapnel.grappled;i++){grapnel.move();grapnel.collision()}
                const snapshot=()=>({x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,attached:grapnel.grappled,
                    rope:grapnel.pos.map(p=>[p[0],p[1],p[2].id])});
                const acquired=snapshot();ninja.speedY=3;const trace=[];
                for(let i=0;i<200;i++){calcPhysics();trace.push(snapshot());if(grapnel.pos.length>=2)break}
                // Identical attached starting state outside both acquisition profiles.
                ninja.x=-1000;ninja.y=700;
                const long=[];for(let i=0;i<12;i++){calcPhysics();long.push(snapshot())}
                return {range:grappleOverAcquisitionRadius(),acquired,trace,long};
            }''')
            self.assertTrue(row['acquired']['attached']);self.assertGreaterEqual(len(row['trace'][-1]['rope']),2)
            self.assertTrue(all(r['attached'] for r in row['long']))
            self.assertTrue(all(abs(r['rope'][0][0]-r['x'])>1080 for r in row['long']))
            before=p.evaluate('[ninja.speedX,ninja.speedY]');p.mouse.up()
            after=p.evaluate('({velocity:[ninja.speedX,ninja.speedY],attached:grapnel.grappled})')
            self.assertEqual(before,after['velocity']);self.assertFalse(after['attached'])
            row['release']=after;traces.append(row)
        self.assertEqual(traces[0]['range'],1080);self.assertEqual(traces[1]['range'],360)
        self.assertEqual({k:v for k,v in traces[0].items() if k!='range'},{k:v for k,v in traces[1].items() if k!='range'})
        self.write('attached-rope.json',dict(profiles=traces,equal_except_range=True))
        print('PASS attached rope: legacy/replacement identical acquired, physical wrap, 12 attached steps beyond 1080, release velocity; no new automatic snap')


class Task560Tests(unittest.TestCase):
    """Bounded isolated movement measurements; not continuous gameplay."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task560Tests')
        Task558Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/grapple_over_metrics.js'] = hashlib.sha256(
            (ROOT/'tools/grapple_over_metrics.js').read_bytes()).hexdigest()
        cls.config['touch_viewport'] = {'width':844,'height':390}
        cls.config['simulation'] = 'isolated fixtures; production physics; synthetic bounded search, trusted final inputs'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK560_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write

    def page(self, touch=False):
        p=Task559Tests.page(self,touch=touch)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_metrics.js'))
        return p

    def check_transfer(self,r):
        self.assertTrue(r['acquired'])
        self.assertTrue(r['landed'])
        self.assertGreaterEqual(r['landingAir'],6)
        self.assertFalse(r['anchorTopContact'])
        landings=[s for s in r['rows'] if any(c['id']=='landing' and c['ny']<-.9 for c in s['contacts'])]
        self.assertTrue(landings)

    def test_01_bounded_grid_metrics(self):
        p=self.page()
        data=p.evaluate('''() => {
          const trials=[];
          for(const [name,radius,width,gaps] of [['opening',360,540,[144,198,252]],['base',360,360,[216,324,432]],['upgraded',540,360,[324,432,540,648]]])
          for(const gap of gaps)for(const dx of [120,180,240])for(const dy of [180,240,300])for(const release of [12,18,24,30,36]) {
            const c={name,radius,width,gap,dx,dy,release},r=METRICS.run(c);
            trials.push({...c,acquired:r.acquired,landed:r.landed,landingAir:r.landingAir,anchorTopContact:r.anchorTopContact,
              success:r.acquired&&r.landed&&r.landingAir>=6&&!r.anchorTopContact});
          }
          const selected=GRAPPLE_OVER_MOVEMENT.patterns.map(c=>({pattern:c,setup:METRICS.setup(c),result:METRICS.run(c)}));
          return {trials,selected,dimensions:GRAPPLE_OVER_MOVEMENT,cameraScale:scale[version],
            physics:{gravity:GRAVITY,pull:grappleSpeed,stepMs:physicsStepMs,cyclesPerTick},scope:'isolated fixtures, no continuous gameplay claim'};
        }''')
        self.assertEqual(len(data['trials']),450)
        self.assertTrue(any(r['success'] for r in data['trials']))
        self.assertTrue(any(not r['success'] for r in data['trials']))
        self.assertEqual(data['cameraScale'],.375)
        for s in data['selected']:
            self.check_transfer(s['result'])
            self.assertLessEqual(s['setup']['reach'],s['pattern']['radius'])
            self.assertGreaterEqual(s['pattern']['width'],540 if s['pattern']['name']=='opening' else 360)
        data.update(self.config)
        self.write('metrics.json',data)
        print('PASS metrics: 450 candidates; 3 selected; reachable anchors; landingAir>=6; no anchor-top landing; widths 540/360/360')

    def real_run(self,p,c,touch,dt=0,aim=0,held=False):
        setup=p.evaluate('c=>METRICS.setup(c)',c)
        xy=p.evaluate('p=>METRICS.client(p)',setup);xy['x']+=aim
        session=p.context.new_cdp_session(p) if touch else None
        if touch: session.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[xy]))
        else: p.mouse.move(xy['x'],xy['y']);p.mouse.down()
        release=c['release']+dt
        p.evaluate('n=>METRICS.step(n)',release)
        if not held:
            if touch: session.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]))
            else: p.mouse.up()
        p.evaluate('n=>METRICS.step(n)',150-release)
        result=p.evaluate('METRICS.result()')
        if held:
            if touch: session.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]))
            else: p.mouse.up()
        if session: session.detach()
        self.assertTrue(result['inputs'])
        self.assertTrue(all(i['trusted'] for i in result['inputs']))
        self.assertEqual(result['inputs'][0]['type'],'touchstart' if touch else 'mousedown')
        self.assertAlmostEqual(result['inputs'][0]['x'],xy['x'],delta=1)
        if not held:self.assertEqual(result['inputs'][1]['tick'],release)
        return dict(pattern=c,device='touch' if touch else 'mouse',viewport=p.viewport_size,
                    releaseOffsetMs=dt*setup['stepMs'],aimOffsetCSSpx=aim,aimAxis='x',
                    requestedClient=xy,setup=setup,result=result)

    def test_02_release_aim_tolerance(self):
        rows=[]
        for touch in [False,True]:
            p=self.page(touch)
            for c in p.evaluate('GRAPPLE_OVER_MOVEMENT.patterns'):
                ticks,px=(6,12) if c['name']=='opening' else (3,8)
                for label,dt,aim in [('nominal',0,0),('early',-ticks,0),('late',ticks,0),('aim-minus',0,-px),('aim-plus',0,px)]:
                    r=self.real_run(p,c,touch,dt,aim);r['case']=label
                    self.write('tolerance.json',dict(cases=rows+[r],source_hashes=self.config['source_hashes']))
                    with self.subTest(device=r['device'],pattern=c['name'],case=label): self.check_transfer(r['result'])
                    rows.append(r)
        self.assertEqual(len(rows),30)
        self.write('tolerance.json',dict(cases=rows,source_hashes=self.config['source_hashes']))
        print('PASS tolerance: 30 trusted mouse/touch cases; opening +/-100 ms and +/-12 CSS px; later +/-50 ms and +/-8 CSS px')

    def test_03_held_controls_and_capture(self):
        rows=[];images=[]
        for touch in [False,True]:
            p=self.page(touch)
            for c in p.evaluate('GRAPPLE_OVER_MOVEMENT.patterns'):
                r=self.real_run(p,c,touch,held=True)
                self.assertTrue(r['result']['acquired']);self.assertFalse(r['result']['landed'])
                self.assertEqual(r['result']['ticks'],150);rows.append(r)
                if not touch:
                    p.evaluate('''c=>{METRICS.setup(c);screen.x=250;screen.y=-200;TUTORIAL_HINT.visible=false;draw()}''',c)
                    im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
                    ImageDraw.Draw(im).text((30,100),f"{c['name']}: panels {c['width']} x 60; edge gap {c['gap']}; range {c['radius']}",fill='white')
                    images.append(im)
        sheet=Image.new('RGB',(1280,720*3))
        for i,im in enumerate(images):sheet.paste(im,(0,720*i))
        sheet.save(self.out/'metrics-sheet.jpg',quality=85)
        with Image.open(self.out/'metrics-sheet.jpg') as im: im.load();self.assertEqual(im.size,(1280,2160))
        self.write('controls.json',dict(observationTicks=150,observationMs=2500,cases=rows,source_hashes=self.config['source_hashes']))
        print('PASS controls: 6 acquired held-grapple controls fail top landing within 150 ticks / 2500 ms; metrics-sheet.jpg decoded 1280x2160')


class Task561Tests(unittest.TestCase):
    """Isolated mover fixtures only; no continuous mountain gameplay claim."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task561Tests')
        Task558Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/grapple_over_movers.js']=hashlib.sha256((ROOT/'tools/grapple_over_movers.js').read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK561_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write

    def page(self):
        p=Task559Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_movers.js'))
        return p

    def test_01_dimensions_and_swept_clearance(self):
        p=self.page()
        data=p.evaluate('''() => GRAPPLE_OVER_MOVERS.examples.map(spec=>{
          const m=MOVERS.setup({axis:spec.axis,phase:spec.startPhase}),w=floors[0],positions=[],windows=[];
          for(let i=0;i<600;i++){w.applyMovers(i*10000/600);const e=w.byId.get('blue');
            positions.push({ms:i*10000/600,x:e.x,y:e.y});
            const q=MOVERS.target();windows.push(Math.hypot(q.x-ninja.x,q.y-ninja.y)<=360);}
          let longest=0,streak=0;for(const yes of [...windows,...windows]){streak=yes?streak+1:0;longest=Math.max(longest,streak)}
          const blue=spec.blue,bounds={left:spec.axis==='x'?spec.min:blue[0],right:(spec.axis==='x'?spec.max:blue[0])+160,
            top:spec.axis==='y'?spec.min:blue[1],bottom:(spec.axis==='y'?spec.max:blue[1])+80};
          const obstacles=m.elements.filter(e=>e.id!=='blue').map(e=>({id:e.id,role:e.role,left:e.x,right:e.x+e.points[1].x,top:e.y,bottom:e.y+e.points[2].y}));
          return {axis:spec.axis,dimensions:[160,80],endpoints:[spec.min,spec.max],displacement:720,fullCycleDistance:1440,
            periodMs:10000,speed:144,acquisitionWindowMs:Math.min(600,longest)*10000/600,bounds,positions,obstacles};
        })''')
        for r in data:
            self.assertGreaterEqual(r['displacement'],max(360,2*r['dimensions'][0 if r['axis']=='x' else 1]))
            self.assertGreaterEqual(r['acquisitionWindowMs'],1000)
            b=r['bounds']
            for o in r['obstacles']:
                self.assertTrue(b['right']<=o['left'] or b['left']>=o['right'] or b['bottom']<=o['top'] or b['top']>=o['bottom'])
            self.assertEqual(len(r['positions']),600)
        for r in data:
            r['acquisitionProbes']=[]
            for delay in [0,15,30,45,60]:
                p.evaluate('c=>MOVERS.setup(c)',dict(axis=r['axis'],phase=0 if r['axis']=='x' else .5))
                p.evaluate('n=>MOVERS.step(n)',delay)
                xy=p.evaluate('MOVERS.client(MOVERS.target())');p.mouse.move(**xy);p.mouse.down()
                p.evaluate('MOVERS.step(30)');probe=p.evaluate('MOVERS.result()');p.mouse.up()
                acquired=[s for s in probe['rows'] if s['attached']]
                self.assertTrue(acquired,(r['axis'],delay))
                self.assertTrue(probe['inputs'][0]['trusted'])
                r['acquisitionProbes'].append(dict(delayTicks=delay,firstAttached=acquired[0],input=probe['inputs'][0]))
        self.write('movers.json',dict(config=self.config,movers=data))
        self.write('swept-clearance.json',dict(method='Exact union AABB of axis-aligned translating rectangle, includes every intermediate position',checks=[dict(axis=r['axis'],swept=r['bounds'],obstacles=r['obstacles']) for r in data]))
        print('PASS dimensions: 2 axes; displacement=720; fullCycleDistance=1440; periodMs=10000; acquisitionWindowMs>=1000; complete swept bounds clear terrain and yellow')

    def test_02_four_phases_and_cycles(self):
        p=self.page();rows=[];trials=[]
        for axis in ['x','y']:
            # Bounded production-physics calibration; retain measurements, not full search traces.
            candidates=p.evaluate('''axis=>{const out=[];for(const periodMs of [6000,8000,10000]){
              for(let release=Math.round(periodMs/1000*60*1.35);release<=periodMs/1000*60*1.6;release+=5){
                MOVERS.setup({axis,periodMs,phase:axis==='x'?0:.5});MOVERS.shot();MOVERS.step(release);MOVERS.release();MOVERS.step(180);
                const r=MOVERS.result(),height=axis==='x'?1100:400;
                out.push({periodMs,release,landed:r.rows.some(s=>s.tick>release&&s.contacts.some(c=>c.ny<-.9&&Math.abs(c.y-height)<.01)),minClearance:r.minClearance});
              }}return out}''',axis)
            trials.extend(dict(axis=axis,**r) for r in candidates)
            valid=[r for r in candidates if r['landed'] and r['minClearance']>=-1e-5]
            self.assertTrue(valid)
            period=max(r['periodMs'] for r in valid);self.assertEqual(period,10000)
            release=next(r['release'] for r in valid if r['periodMs']==period)
            for phase in [0,.25,.5,.75]:
                m=p.evaluate('c=>MOVERS.setup(c)',dict(axis=axis,periodMs=period,phase=phase))
                wait=round((((0 if axis=='x' else .5)-phase)%1)*period/1000*60)
                p.evaluate('n=>MOVERS.step(n)',wait)
                xy=p.evaluate('MOVERS.client(MOVERS.target())');p.mouse.move(**xy);p.mouse.down()
                p.evaluate('n=>MOVERS.step(n)',release);p.mouse.up();p.evaluate('MOVERS.step(180)')
                r=p.evaluate('MOVERS.result()');height=1100 if axis=='x' else 400
                landed=[s for s in r['rows'] if s['tick']>wait+release and any(c['ny']<-.9 and abs(c['y']-height)<.01 for c in s['contacts'])]
                attached=[s for s in r['rows'] if s['attached']]
                self.assertTrue(landed,(axis,phase,release));self.assertTrue(attached)
                self.assertLessEqual(wait,period/1000*60);self.assertGreaterEqual(r['minClearance'],-1e-5)
                self.assertTrue(all(i['trusted'] for i in r['inputs']));self.assertEqual(len(r['inputs']),2)
                self.assertTrue(all(not s['attached'] for s in r['rows'] if s['tick']>wait+release))
                values=[s['mx' if axis=='x' else 'my'] for s in attached]
                self.assertAlmostEqual(max(values)-min(values),720,delta=3)
                self.assertTrue(any(values[i]>values[i-1] for i in range(1,len(values))))
                self.assertTrue(any(values[i]<values[i-1] for i in range(1,len(values))))
                rows.append(dict(axis=axis,phase=phase,periodMs=period,waitTicks=wait,releaseTicks=release,landing=landed[0],manifest=m,**r))
        self.write('phase-tests.json',dict(config=self.config,trials=trials,cases=rows))
        print('PASS phases: 8 trusted-input transfers; phases 0/0.25/0.5/0.75; attach travel reversal release; waits<one cycle; no penetration/crush/stuck attachment/restart; slowest successful tested cycle=10000 ms')

    def test_03_cycle_capture(self):
        import imageio_ffmpeg
        data=json.loads((self.out/'phase-tests.json').read_text())
        p=self.page();r=next(r for r in data['cases'] if r['axis']=='x' and r['phase']==0)
        p.evaluate("MOVERS.setup({axis:'x'})")
        xy=p.evaluate('MOVERS.client(MOVERS.target())');p.mouse.move(**xy);p.mouse.down()
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        encoder_log=(self.out/'encoder.log').open('wb')
        self.addCleanup(encoder_log.close)
        encoder=subprocess.Popen([ffmpeg,'-y','-loglevel','error','-threads','1','-filter_threads','1','-f','image2pipe','-vcodec','png','-r','15','-i','-','-c:v','libvpx-vp9','-threads','1','-cpu-used','6','-pix_fmt','yuv420p','-crf','35','-b:v','0',str(self.out/'cycle.webm')],stdin=subprocess.PIPE,stderr=encoder_log)
        total=r['releaseTicks']+180
        for tick in range(1,total+1):
            p.evaluate('MOVERS.step(1)')
            if tick==r['releaseTicks']:p.mouse.up()
            if tick%4==0:
                p.evaluate("screen.x=300;screen.y=-250;TUTORIAL_HINT.visible=false;draw();ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='white';ctx.font='20px sans-serif';ctx.fillText('TASK-561 isolated horizontal mover | '+(MOVERS.result().tick/60).toFixed(2)+' s',30,100);ctx.restore()")
                encoder.stdin.write(p.screenshot())
        encoder.stdin.close();code=encoder.wait();encoder_log.close();self.assertEqual(code,0,(self.out/'encoder.log').read_text())
        frames,seconds=imageio_ffmpeg.count_frames_and_secs(str(self.out/'cycle.webm'))
        self.assertGreater(seconds,10);self.assertGreater(frames,150)
        self.write('capture.json',dict(frames=frames,seconds=seconds,simulationHz=60,captureHz=15,sourceCase='x phase 0',releaseTick=r['releaseTicks']))
        print('PASS cycle.webm: decoded %d frames %.2f seconds; complete 10-second cycle and transfer' % (frames,seconds))


class Task562Tests(unittest.TestCase):
    """Isolated yellow envelope; setup poses are not continuous mountain play."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task562Tests')
        Task558Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/grapple_over_yellow.js']=hashlib.sha256((ROOT/'tools/grapple_over_yellow.js').read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK562_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write

    def page(self):
        p=Task559Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_yellow.js'))
        return p

    def test_01_geometry(self):
        p=self.page()
        r=p.evaluate('''()=>{const m=YELLOW.setup(),c=GRAPPLE_OVER_YELLOW,b=c.band;
          const obstacles=m.elements.filter(e=>e.role!=='drag').map(e=>{
            const mover=m.movers.find(v=>v.element===e.id),left=mover?mover.min:e.x,right=(mover?mover.max:e.x)+e.points[1].x,top=e.y,bottom=e.y+e.points[2].y;
            const dx=Math.max(left-b.left-b.width,b.left-right,0),dy=Math.max(top-b.top-b.height,b.top-bottom,0);
            return {id:e.id,swept:!!mover,left,right,top,bottom,clearance:Math.hypot(dx,dy)};});
          return {band:b,range:grappleOverAcquisitionRadius(),widthRatio:b.width/b.height,rangeRatio:b.width/grappleOverAcquisitionRadius(),obstacles,
            corridor:{left:-1100,right:1100},lateralAscent:{left:1220,right:1780,top:-1000,bottom:1200},
            manifest:m,physics:{horizontal:DRAG_ZONE_HORIZONTAL_DAMPING,vertical:DRAG_ZONE_VERTICAL_DAMPING,gravity:GRAVITY,pull:grappleSpeed,camera:scale[version]}};}''')
        self.assertGreaterEqual(r['widthRatio'],4);self.assertGreaterEqual(r['rangeRatio'],3)
        self.assertEqual(r['physics']['horizontal'],.8);self.assertEqual(r['physics']['vertical'],.985)
        self.assertEqual(r['physics']['camera'],.375)
        for o in r['obstacles']:self.assertGreaterEqual(o['clearance'],540,o)
        self.assertTrue(any(o['swept'] for o in r['obstacles']))
        self.assertLessEqual(r['band']['left'],r['corridor']['left'])
        self.assertGreaterEqual(r['band']['left']+r['band']['width'],r['corridor']['right'])
        self.assertGreater(r['lateralAscent']['left'],r['band']['left']+r['band']['width'])
        r['minimumClearance']=min(o['clearance'] for o in r['obstacles'])
        self.write('yellow-geometry.json',r)
        print('PASS geometry: width=2400 height=600 aspect=4 range=540 coverage=2200 minimumClearance=%.6f; full swept mover bounds; lateral ascent x=1220..1780' % r['minimumClearance'])

    def test_02_fall_control(self):
        p=self.page()
        cases=p.evaluate('''()=>[0,...GRAPPLE_OVER_YELLOW.thicknessCandidates].map(h=>{
          YELLOW.setup({band:!!h,height:h||600});YELLOW.step(1000);const r=YELLOW.result(),landing=r.bounces[0],second=r.bounces[1];
          const rebound=r.rows.filter(s=>s.tick>landing.tick&&s.tick<second.tick),apex=rebound.reduce((a,b)=>a.y<b.y?a:b);
          const entry=r.rows.find(s=>s.inDrag),exit=entry&&r.rows.find(s=>s.tick>entry.tick&&!s.inDrag);
          return {height:h,initial:r.rows[0],entry,exit,landing,apex,secondLanding:second,
            drop:landing.after.y-r.rows[0].y,reboundHeight:landing.after.y-apex.y,
            trace:r.rows.filter(s=>s.tick%5===0||[entry?.tick,exit?.tick,landing.tick,apex.tick].includes(s.tick))};})''')
        self.assertEqual(len(cases),5)
        base=cases[0];chosen=cases[-1]
        for c in cases:
            self.assertEqual(c['initial'],base['initial'])
            self.assertGreater(c['apex']['tick'],c['landing']['tick'])
            self.assertGreaterEqual(c['apex']['tick']-c['landing']['tick'],30)
        self.assertLessEqual(chosen['reboundHeight'],chosen['drop']*.5)
        self.assertGreater(chosen['apex']['y'],-2400)
        self.assertGreater(base['reboundHeight'],base['drop']*.9)
        self.assertLess(chosen['exit']['vy'],chosen['entry']['vy'])
        self.write('fall-control.json',dict(config=self.config,candidateBounds=[150,600],candidates=cases,selectedHeight=600,abandonedRouteY=-2400,
            rationale='600 maximizes braking within the tested finite thickness interval; width 2400 preserves aspect 4 and clearance simultaneously.'))
        print('PASS fall: 5 same-state production runs; selected rebound=%.6f <= half drop=%.6f; apex=%.6f below abandoned route=-2400; entry vy=%.6f exit vy=%.6f' % (chosen['reboundHeight'],chosen['drop']*.5,chosen['apex']['y'],chosen['entry']['vy'],chosen['exit']['vy']))

    def test_03_recovery_and_capture(self):
        import imageio_ffmpeg
        p=self.page();p.evaluate('YELLOW.setup()')
        actions=[]
        def press(target):
            xy=p.evaluate('p=>YELLOW.client(p)',target)
            p.mouse.move(**xy);p.mouse.down();actions.append(dict(tick=p.evaluate('YELLOW.result().tick'),target=target))
        # Production input from the first lower bounce, never a setup/reset mid-run.
        p.evaluate('YELLOW.step(352)');press(dict(x=1480,y=1140))
        p.evaluate('YELLOW.step(40)');p.mouse.up();p.evaluate('YELLOW.step(10)')
        for _ in range(2):
            y=p.evaluate('ninja.y');press(dict(x=1800,y=y-350))
            p.evaluate('YELLOW.step(60)');p.mouse.up()
        r=p.evaluate('YELLOW.result()')
        self.assertEqual(len(r['bounces']),1)
        self.assertEqual(len(r['inputs']),6);self.assertTrue(all(e['trusted'] for e in r['inputs']))
        self.assertFalse(any(s['inDrag'] for s in r['rows'] if s['tick']>=352))
        self.assertGreater(r['rows'][-1]['x'],1200+r['radius']);self.assertLess(r['rows'][-1]['y'],-r['radius'])
        self.assertTrue(any(s['attached'] for s in r['rows']))
        self.assertAlmostEqual(r['stats']['elapsedActiveMs'],522*1000/60,places=5)
        self.assertFalse(r['stats']['completed'])
        self.write('recovery.json',dict(config=self.config,actions=actions,**r))
        # Replay the verified controls for capture, independent of simulation search.
        p.evaluate('YELLOW.setup()')
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        with (self.out/'encoder.log').open('wb') as log:
            encoder=subprocess.Popen([ffmpeg,'-y','-loglevel','error','-threads','1','-filter_threads','1','-f','image2pipe','-vcodec','png','-r','7.5','-i','-','-c:v','libvpx-vp9','-threads','1','-cpu-used','6','-pix_fmt','yuv420p','-crf','35','-b:v','0',str(self.out/'fall.webm')],stdin=subprocess.PIPE,stderr=log)
            shots={a['tick']:a['target'] for a in actions};releases={392,462,522}
            for tick in range(0,523,2):
                if tick in releases:p.mouse.up()
                if tick in shots:
                    xy=p.evaluate('p=>YELLOW.client(p)',shots[tick]);p.mouse.move(**xy);p.mouse.down()
                if tick%8==0:
                    p.evaluate("TUTORIAL_HINT.visible=false;draw();ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='white';ctx.font='20px sans-serif';ctx.fillText('TASK-562 isolated fall and lateral recovery | '+(YELLOW.result().tick/60).toFixed(2)+' s',20,100);ctx.restore()")
                    encoder.stdin.write(p.screenshot())
                if tick<522:p.evaluate('YELLOW.step(2)')
            encoder.stdin.close();self.assertEqual(encoder.wait(),0)
        replay=p.evaluate('YELLOW.result()')
        self.assertAlmostEqual(replay['rows'][-1]['x'],r['rows'][-1]['x'],places=5)
        self.assertAlmostEqual(replay['rows'][-1]['y'],r['rows'][-1]['y'],places=5)
        frames,seconds=imageio_ffmpeg.count_frames_and_secs(str(self.out/'fall.webm'))
        self.assertGreaterEqual(frames,65);self.assertGreater(seconds,8)
        self.write('capture.json',dict(frames=frames,seconds=seconds,simulationHz=60,captureHz=7.5,replayFinal=replay['rows'][-1]))
        print('PASS recovery: 6 trusted inputs; one lower bounce; no drag reentry; escape x=%.6f y=%.6f; 522 uninterrupted ticks; fall.webm decoded %d frames %.2f seconds' % (r['rows'][-1]['x'],r['rows'][-1]['y'],frames,seconds))


class Task563Tests(unittest.TestCase):
    """Late-game hazard calibration only; independent setup poses are not a run."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task563Tests')
        Task558Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/grapple_over_hazard.js'] = hashlib.sha256((ROOT/'tools/grapple_over_hazard.js').read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK563_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write

    def page(self):
        p = Task559Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_hazard.js'))
        return p

    def press(self, p, target):
        xy = p.evaluate('p=>HAZARD.client(p)', target)
        p.mouse.move(**xy); p.mouse.down()

    def test_01_observation_and_swept_clearance(self):
        p = self.page()
        r = p.evaluate('''()=>{
          const m=HAZARD.setup(),r=ninja.radius,k=scale[version];
          const warning={left:(650+screen.x)*k,right:(730+screen.x)*k,
            top:(-500+screen.y)*k,bottom:(280+screen.y)*k,canvasWidth:width,canvasHeight:height};
          HAZARD.step(360);const observation=HAZARD.result();
          const obstacles=m.elements.filter(e=>e.id!=='red').map(e=>{
            const left=e.x,right=e.x+e.points[1].x,top=e.y,bottom=e.y+e.points[2].y;
            return {id:e.id,role:e.role,left,right,top,bottom,
              clearance:Math.hypot(Math.max(left-730,650-right,0),Math.max(top-280,-500-bottom,0))};});
          return {manifest:m,warning,observation,obstacles,radius:r,camera:k,range:grappleOverAcquisitionRadius(),
            sweep:{left:650,right:730,top:-500,bottom:280},periodMs:6000};}''')
        w=r['warning']; self.assertGreater(w['left'],0); self.assertLess(w['right'],w['canvasWidth'])
        self.assertGreater(w['top'],0); self.assertLess(w['bottom'],w['canvasHeight'])
        self.assertGreater(w['right']-w['left'],25)
        self.assertEqual(r['camera'],.375); self.assertEqual(r['range'],540)
        rows=r['observation']['rows']
        self.assertEqual(r['observation']['contacts'],[])
        self.assertLess(max(s['x'] for s in rows)-min(s['x'] for s in rows),.01)
        self.assertLess(max(s['y'] for s in rows)-min(s['y'] for s in rows),.1)
        self.assertAlmostEqual(min(s['redY'] for s in rows),-500,places=5)
        self.assertAlmostEqual(max(s['redY'] for s in rows),200,places=5)
        for o in r['obstacles']: self.assertGreater(o['clearance'],2*r['radius'],o)
        self.assertEqual(len(r['manifest']['movers']),1)
        self.write('swept-clearance.json',r)
        print('PASS observation: 360 ticks / full 6000 ms cycle; warning 30 canvas pixels wide and entire sweep visible; safe stationary surface')
        print('PASS swept clearance: all terrain and yellow bounds separated from full red mover sweep by > player diameter; broad catch width=3000')

    def scenario(self, p, phase, recover=False, capture=None):
        p.evaluate('phase=>HAZARD.setup(phase)',phase)
        actions=[]
        def press(target):
            actions.append(dict(tick=p.evaluate('HAZARD.result().tick'),target=target))
            self.press(p,target)
        def step(n):
            if capture is None:p.evaluate('n=>HAZARD.step(n)',n)
            else:
                for _ in range(n//4):
                    p.evaluate('HAZARD.step(4)')
                    if p.evaluate('HAZARD.result().tick%8===0'):
                        p.evaluate("TUTORIAL_HINT.visible=false;draw();ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='white';ctx.font='20px sans-serif';ctx.fillText('TASK-563 isolated late-game hazard | '+(HAZARD.result().tick/60).toFixed(2)+' s | observe, contact, recover',20,100);ctx.restore()")
                        capture.stdin.write(p.screenshot())
        # Observe from the actual safe surface for one complete cycle before committing.
        step(360);press(dict(x=900,y=40));step(100 if recover else 60);p.mouse.up()
        if recover:
            step(100);press(dict(x=850,y=440));step(60);p.mouse.up()
            for _ in range(3):
                y=p.evaluate('Math.max(10,ninja.y-250)');press(dict(x=1100,y=y));step(60);p.mouse.up()
        result=p.evaluate('HAZARD.result()');result.update(phase=phase,actions=actions)
        return result

    def test_02_timing_contact_and_recovery(self):
        p=self.page();safe=self.scenario(p,0)
        self.assertEqual(safe['contacts'],[]);self.assertGreater(safe['rows'][-1]['x'],730+safe['radius'])
        self.assertLess(safe['rows'][-1]['y'],150)
        cases=[]
        for label,phase in [('early',.3),('late',.5)]:
            r=self.scenario(p,phase,True);r['timing']=label;cases.append(r)
            self.assertGreater(len(r['contacts']),0)
            c=r['contacts'][0];self.assertEqual(c['before']['cooldown'],0);self.assertEqual(c['after']['cooldown'],350)
            self.assertGreater((c['after']['vx']-c['before']['vx'])*c['nx']+(c['after']['vy']-c['before']['vy'])*c['ny'],0)
            self.assertFalse(c['after']['attached'])
            self.assertTrue(any(0<s['cooldown']<350 for s in r['rows']))
            self.assertEqual(r['rows'][-1]['cooldown'],0)
            self.assertTrue(any(s['y']>580 for s in r['rows']))
            self.assertGreater(r['rows'][-1]['x'],1000);self.assertLess(r['rows'][-1]['y'],200)
            self.assertEqual(len(r['inputs']),10);self.assertTrue(all(e['trusted'] for e in r['inputs']))
            for s in r['rows']:
                self.assertTrue(s['sameWorld']);self.assertTrue(s['run']);self.assertFalse(s['continueOffer'])
            self.assertLess(max(((b['x']-a['x'])**2+(b['y']-a['y'])**2)**.5 for a,b in zip(r['rows'],r['rows'][1:])),30)
            self.assertAlmostEqual(r['stats']['elapsedActiveMs'],800*1000/60,places=4)
            print('PASS %s contact/recovery: contacts=%d cooldown=350->0 trusted inputs=10 catch y>580 escape x=%.3f y=%.3f; 800 continuous ticks no restart/death/teleport' % (label,len(r['contacts']),r['rows'][-1]['x'],r['rows'][-1]['y']))
        self.write('hazard.json',dict(config=self.config,warning=json.loads((self.out/'swept-clearance.json').read_text())['warning'],warningEvidence='swept-clearance.json',timedTraversal=safe,contacts=[r['contacts'] for r in cases]))
        self.write('recovery.json',dict(config=self.config,cases=cases))
        print('PASS timed traversal: phase=0, 360 observation ticks then 60 traversal ticks, beyond red sweep without contact')

    def test_03_readable_introduction_capture(self):
        import imageio_ffmpeg
        p=self.page();ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        with (self.out/'encoder.log').open('wb') as log:
            encoder=subprocess.Popen([ffmpeg,'-y','-loglevel','error','-threads','1','-filter_threads','1','-f','image2pipe','-vcodec','png','-r','7.5','-i','-','-c:v','libvpx-vp9','-threads','1','-cpu-used','6','-pix_fmt','yuv420p','-crf','35','-b:v','0',str(self.out/'hazard.webm')],stdin=subprocess.PIPE,stderr=log)
            try:r=self.scenario(p,.3,True,encoder)
            finally:encoder.stdin.close()
            self.assertEqual(encoder.wait(),0)
        expected=json.loads((self.out/'recovery.json').read_text())['cases'][0]
        self.assertEqual(r['rows'],expected['rows'])
        frames,seconds=imageio_ffmpeg.count_frames_and_secs(str(self.out/'hazard.webm'))
        self.assertEqual(frames,100);self.assertGreater(seconds,13)
        self.write('capture.json',dict(frames=frames,seconds=seconds,replayMatches=True,final=r['rows'][-1]))
        print('PASS hazard.webm: decoded %d frames %.3f seconds; capture replay exactly matches measured early contact and recovery' % (frames,seconds))


class Task564Tests(unittest.TestCase):
    """Reservation design checks plus representative isolated production input."""
    @classmethod
    def setUpClass(cls):
        from grapple_over_blueprint import export
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task564Tests')
        Task558Tests.setUpClass.__func__(cls)
        cls.blueprint, cls.graph = export(cls.out)
        for name in ['docs/grapple-over-blueprint.json','docs/grapple-over-blueprint.md',
                     'tools/grapple_over_blueprint.py','tools/grapple_over_metrics.js']:
            cls.config['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK564_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    page = Task559Tests.page

    def test_01_complete_calibrated_blueprint(self):
        import math
        b = self.blueprint
        p = self.page()
        m = p.evaluate('({movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS,yellow:GRAPPLE_OVER_YELLOW})')
        sections = b['sections']
        self.assertEqual([s['name'] for s in sections], ['Loading Yard','Terraced Quarry','Freight Crossing','Broken Viaduct','Cable Galleries','Counterweight Tower','Exposed Crown','Summit Array'])
        self.assertEqual(b['firstUse'],dict(green='S01',blue='S03',yellow='S04',**{'540':'S05'},corner='S05',red='S07'))
        red=json.loads((ROOT/'artifacts/TASK-563/swept-clearance.json').read_text())
        red_face=next(e for e in red['manifest']['elements'] if e['id']=='red')
        red_mover=red['manifest']['movers'][0]
        observation=next(e for e in red['manifest']['elements'] if e['id']=='observation')
        checked=[]
        for i,s in enumerate(sections):
            self.assertEqual(len(s['encounters']),4)
            self.assertFalse(s['landmark']['collidable']); self.assertFalse(s['landmark']['grapplable'])
            self.assertEqual([e['phase'] for e in s['encounters']],['introduction','practice','variation','combination'])
            for e in s['encounters']:
                g=e['geometry']; pattern=next(c for c in m['movement']['patterns'] if c['name']==g['pattern'])
                for key in ['gap','dx','dy']: self.assertEqual(g[key],pattern[key])
                self.assertEqual(g['releaseTicks'],pattern['release'])
                self.assertEqual(g['landingLength'],pattern['width'])
                self.assertEqual(e['rangeStage'],pattern['radius'])
                self.assertEqual(g['panelThickness'],m['movement']['panelThickness'])
                self.assertEqual(g['anchorFace'],[m['movement']['anchorFace']['width'],m['movement']['anchorFace']['height']])
                self.assertLess(math.hypot(g['dx']+80,g['dy']-40),e['rangeStage'])
                self.assertEqual(e['planningLanding'][2:],[540,60])
                self.assertTrue(e['intendedJumpRelease']); self.assertTrue(e['landmark'])
                # Teaching briefs must agree with their structured actions and axes.
                brief = e['brief'].lower()
                self.assertIsInstance(e['intendedJumpRelease']['jump'], bool)
                if 'jump' in brief:
                    self.assertTrue(e['intendedJumpRelease']['jump'], e['id'])
                if 'moverEnvelope' in e:
                    self.assertIn(e['moverEnvelope']['axis'], ['x', 'y'], e['id'])
                    for direction, axis in [('horizontal', 'x'), ('vertical', 'y')]:
                        if direction in brief:
                            self.assertEqual(e['moverEnvelope']['axis'], axis, e['id'])
                self.assertTrue(all(c['purpose'] for c in e['colliderPurposes']))
                if i<2: self.assertEqual(e['mechanics'],['green'])
                if i<6: self.assertNotIn('red',e['mechanics'])
                if i>=2:
                    for key in ['displacement','periodMs']: self.assertEqual(e['moverEnvelope'][key],m['movers'][key])
                    self.assertEqual(e['moverEnvelope']['face'],[m['movers']['width'],m['movers']['height']])
                if i>=3:
                    z=e['yellowReservation']; self.assertEqual(z['band'][2:],[m['yellow']['band']['width'],m['yellow']['band']['height']])
                    self.assertEqual(z['clearance'],m['yellow']['clearance'])
                    self.assertEqual(z['catch'][1]-sum(z['band'][1::2]),600)
                    self.assertEqual(z['catch'][2:],m['yellow']['landing'][2:])
                    self.assertLess(z['band'][0]+z['band'][2],e['corridors']['ascent'][0])
                if i>=6:
                    env=e['redEnvelope']
                    self.assertEqual(env['size'],[red_face['points'][1]['x'],red_face['points'][2]['y']])
                    self.assertEqual(env['travel'],red_mover['max']-red_mover['min'])
                    self.assertEqual(env['periodMs'],red['periodMs'])
                    self.assertEqual(env['minimumSweptClearance'],min(o['clearance'] for o in red['obstacles']))
                    self.assertEqual(env['observationLandingLength'],observation['points'][1]['x'])
                    self.assertEqual(e['redEnvelope'],dict(size=[80,80],travel=700,periodMs=6000,minimumSweptClearance=150,observationLandingLength=500,status='isolated calibration; transformed sweep must be checked before building'))
                checked.append(dict(id=e['id'],reach=math.hypot(g['dx']+80,g['dy']-40),range=e['rangeStage']))
        self.assertEqual(len(checked),32)
        encounters = {e['id']: e for s in sections for e in s['encounters']}
        self.assertEqual(encounters['S06-E02']['moverEnvelope']['axis'], 'x')
        self.assertIs(encounters['S08-E02']['intendedJumpRelease']['jump'], True)
        print('PASS brief consistency: S06-E02 horizontal axis=x; S08-E02 jump=true; all jump/directional briefs checked')
        self.write('measurements.json',dict(checked=checked,productionEnvelopes=m,scope='dimensions calibrated; placements planned'))
        print('PASS 8 sections / 32 encounters; calibrated numeric envelopes; S01/S02 green-only; first red S07')

    def test_02_production_input_and_unchanged_runtime(self):
        p=self.page(); p.add_script_tag(path=str(ROOT/'tools/grapple_over_metrics.js'))
        results=[]
        for c in p.evaluate('GRAPPLE_OVER_MOVEMENT.patterns'):
            setup=p.evaluate('c=>METRICS.setup(c)',c)
            xy=p.evaluate('p=>METRICS.client(p)',setup)
            p.mouse.move(**xy);p.mouse.down()
            p.evaluate('n=>METRICS.step(n)',c['release']);p.mouse.up()
            p.evaluate('n=>METRICS.step(n)',150-c['release'])
            r=p.evaluate('METRICS.result()')
            self.assertTrue(r['acquired']);self.assertTrue(r['landed']);self.assertGreaterEqual(r['landingAir'],6)
            self.assertFalse(r['anchorTopContact']);self.assertEqual(len(r['inputs']),2)
            self.assertTrue(all(x['trusted'] for x in r['inputs']))
            results.append(dict(pattern=c,acquired=r['acquired'],landed=r['landed'],landingAir=r['landingAir'],inputs=r['inputs']))
        legacy=self.page(preview=False)
        self.assertEqual(legacy.evaluate('[grappleOverAcquisitionRadius(),scale[version]]'),[1080,.375])
        archived=[]
        for task in [560,561,562,563]:
            log=(ROOT/f'artifacts/TASK-{task}/tests.log').read_text()
            self.assertIn('\nOK\n',log);self.assertRegex(log,r'Ran [1-9][0-9]* tests')
            archived.append(dict(path=f'artifacts/TASK-{task}/tests.log',result=log[log.rfind('\nRan '):].strip()))
        # No runtime source changed since the immediate prerequisite's tested run.
        lines=(ROOT/'artifacts/TASK-563/commands.log').read_text().splitlines()
        cfg=json.loads(next(l.split(' ',1)[1] for l in lines if l.startswith('TASK563_CONFIG ')))
        runtime={k:v for k,v in cfg['source_hashes'].items() if not k.startswith('tools/')}
        self.assertGreater(len(runtime),20)
        for name,digest in runtime.items(): self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
        self.write('production-check.json',dict(cases=results,archived=archived,unchangedRuntimeHashes=runtime,scope='isolated fixture; not continuous gameplay'))
        print('PASS 3 isolated production transfers with trusted input; legacy 1080 camera .375; archived 560-563 pass; runtime hashes unchanged')

    def test_03_graph_clearances_and_decoded_map(self):
        import xml.etree.ElementTree as ET
        b=self.blueprint;g=self.graph
        ids=g['nodes']; self.assertEqual(len(set(ids)),33)
        for edge in g['edges']:
            self.assertLess(ids.index(edge['to']),ids.index(edge['from']))
            self.assertEqual(edge['status'],'planned')
            node=edge['from']; visited=set()
            while node!='base':
                self.assertNotIn(node,visited);visited.add(node)
                node=next(e['to'] for e in g['edges'] if e['from']==node)
        for s in b['sections']:
            for e in s['encounters']:
                c=list(e['corridors'].values())
                self.assertEqual([r[2] for r in c],[2600,1600,1400])
                self.assertEqual([c[k+1][0]-c[k][0]-c[k][2] for k in [0,1]],[200,200])
                self.assertEqual(e['reservation'][2:],[6000,3200])
                self.assertGreaterEqual(e['reservation'][1],s['band'][1])
                self.assertLessEqual(e['reservation'][1]+3200,s['band'][1]+s['band'][3])
        for lower,upper in zip(b['sections'],b['sections'][1:]):
            self.assertLessEqual(upper['band'][1]+upper['band'][3],lower['band'][1])
        self.assertEqual(len(b['shortcuts']),2)
        for s in b['shortcuts']:
            self.assertIn(s['from'][:3],['S05','S07']);self.assertEqual(s['from'][:3],s['to'][:3]);self.assertEqual(len(s['skips']),1)
            self.assertEqual(ids.index(s['to'])-ids.index(s['from']),2)
        ET.parse(self.out/'route-map.svg')
        p=self.browser.new_page(viewport={'width':1200,'height':2900},device_scale_factor=1)
        self.addCleanup(p.close)
        p.set_content((self.out/'route-map.svg').read_text())
        p.locator('svg').screenshot(path=str(self.out/'silhouette.png'))
        with Image.open(self.out/'silhouette.png') as im:
            im.load();self.assertEqual(im.size,(1200,2900));self.assertGreater(len(im.getcolors(im.width*im.height)),100)
        self.write('map-check.json',dict(nodes=33,recoveries=32,allReachBase=True,planned=True,shortcuts=2,skipsEach=1,sectionBands=[s['band'] for s in b['sections']],image=[1200,2900],capture='Chromium SVG screenshot, device scale 1'))
        print('PASS 32 planned recovery edges reach base; 2 shortcuts skip 1 each; 200-unit separators; no S05/S08 fold; decoded silhouette 1200x2900')

    def test_04_evidence_index(self):
        assertions={'commands.log':'exact invocation, exit status and source/browser configuration; outer runner appends exit',
                    'tests.log':'four Task564Tests identifiers and runner summary; outer runner completes log',
                    'blueprint.json':'eight sections and 32 phased briefs with mechanics and purpose',
                    'route-map.svg':'labelled ascent/fall/recovery reservations',
                    'silhouette.png':'decoded rendered reservation map',
                    'recovery-graph.json':'planned recovery connectivity to base',
                    'review.md':'identity, pacing, numeric ledger, limitations and subsystem dependencies',
                    'measurements.json':'32 envelope comparisons and production constants',
                    'production-check.json':'trusted production input and unchanged runtime hashes with archived pass logs',
                    'map-check.json':'connectivity, bounds and image decode',
                    'evidence-index.json':'artifact inventory and scope'}
        self.write('evidence-index.json',dict(artifacts=assertions,dependencies=['docs/grapple-over-blueprint.json','docs/grapple-over-blueprint.md','tools/grapple_over_blueprint.py','tools/test_grapple_over_redesign.py'],scope='planned design, not proof of fun; HEAD changes alone do not invalidate identical hashes'))
        for name in assertions:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200*1024**2)
        print('PASS evidence-index: all 11 artifacts exist; JSON parses; retained evidence below 200 MB')


class Task565Tests(unittest.TestCase):
    """Reusable bounded collection in isolated fixtures, not continuous gameplay."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task565Tests')
        Task558Tests.setUpClass.__func__(cls)
        for name in ['tools/grapple_over_collection.py', 'tools/grapple_over_collector.js',
                     'tools/grapple_over_metrics.js', 'docs/grapple-over-blueprint.json']:
            cls.config['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK565_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    page = Task559Tests.page

    def test_01_exact_selection_and_child_paths(self):
        import sys
        import types
        from grapple_over_collection import exact_suite
        from grapple_over_test_support import EvidenceWriter
        suite, ids = exact_suite(sys.modules[__name__], 'Task565Tests')
        self.assertEqual(len(ids), 4)
        lines = ['SELECTED '+i for i in ids] + ['COLLECTED 4 exact Task565Tests']
        for label, module, name in [
            ('substring', sys.modules[__name__], 'Task565'),
            ('duplicate', types.SimpleNamespace(a=Task565Tests,b=Task565Tests), 'Task565Tests'),
            ('missing', types.SimpleNamespace(), 'Task999999Tests'),
            ('empty', types.SimpleNamespace(a=type('Task999Tests',(unittest.TestCase,),{})), 'Task999Tests')]:
            with self.assertRaises(ValueError): exact_suite(module, name)
            lines.append('REJECTED '+label)
        writer=EvidenceWriter()
        with self.assertRaises(ValueError): writer.path('../escape.json')
        command=[sys.executable,'tools/grapple_over_collection.py','--class','Task565Tests','--export','S01','S01-E01']
        child=subprocess.run(command,cwd=ROOT,env=os.environ.copy(),text=True,capture_output=True)
        lines += ['COMMAND '+ ' '.join(command), child.stdout, child.stderr, 'EXIT '+str(child.returncode)]
        self.assertEqual(child.returncode,0)
        exported=self.out/'encounter.json'
        self.assertEqual(json.loads(exported.read_text())['encounter']['id'],'S01-E01')
        self.assertIn(str(exported),child.stdout)
        self.assertEqual(len([l for l in child.stdout.splitlines() if '.Task565Tests.test_' in l]),4)
        (self.out/'selection.log').write_text('\n'.join(lines)+'\n')
        print('PASS exact selection: 4 identifiers; rejected substring duplicate missing empty; child export confined')

    def test_02_bounded_collectors(self):
        import time
        start=time.monotonic()
        p=self.page()
        for name in ['grapple_over_metrics.js','grapple_over_collector.js']:
            p.add_script_tag(path=str(ROOT/'tools'/name))
        pattern=p.evaluate('GRAPPLE_OVER_MOVEMENT.patterns[0]')
        batch=p.evaluate('''c=>REDESIGN_COLLECTOR.collect(c,[
          {label:'nominal'},{label:'early',offset:-6},{label:'late',offset:6},
          {label:'aim-minus',aim:-12},{label:'aim-plus',aim:12},{label:'held-control',held:true}])''',pattern)
        for row in batch[:5]:
            self.assertTrue(row['success'], row['label'])
            self.assertGreaterEqual(row['landingAir'],6)
            self.assertTrue(any(c['id']=='landing' and c['ny']<-.9 for e in row['events'] for c in e['contacts']))
        self.assertTrue(batch[-1]['acquired']);self.assertFalse(batch[-1]['success']);self.assertFalse(batch[-1]['landed'])
        setup=p.evaluate('c=>METRICS.setup(c)',pattern)
        xy=p.evaluate('s=>METRICS.client(s)',setup)
        p.mouse.move(**xy);p.mouse.down()
        p.evaluate('n=>METRICS.step(n)',pattern['release']);p.mouse.up()
        p.evaluate('n=>METRICS.step(n)',150-pattern['release'])
        trusted=p.evaluate('s=>REDESIGN_COLLECTOR.compact(METRICS.result(),s,"trusted")',setup)
        self.assertTrue(trusted['success'])
        self.assertEqual([i['type'] for i in trusted['inputs']],['mousedown','mouseup'])
        self.assertTrue(all(i['trusted'] for i in trusted['inputs']))
        self.assertEqual(trusted['inputs'][1]['tick'],pattern['release'])
        for row in batch+[trusted]:
            self.assertEqual(row['ticks'],150)
            self.assertLess(len(row['events']),150)
            self.assertTrue(row['clearance']['passes'])
            self.assertEqual(row['clearance']['measured'],pattern['dy']-80+setup['diameter']/2)
            self.assertTrue(any(e['attached'] for e in row['events']))
            self.assertTrue(all(set(e)=={'tick','x','y','attached','throwed','contacts'} for e in row['events']))
        for variants in [[], [{}]*17, [{'offset':-999}], [{'offset':999}]]:
            result=p.evaluate('a=>{try{REDESIGN_COLLECTOR.collect(a.c,a.v);return false}catch(e){return true}}',dict(c=pattern,v=variants))
            self.assertTrue(result)
        data=dict(scope='isolated fixtures; synthetic batch and trusted mouse confirmation, not continuous gameplay',
                  pattern=pattern,cases=batch,trusted=trusted,childEvidencePaths=[str(self.out/'encounter.json')],
                  geometryCopiesPerTrace=0,bounds=dict(maxVariants=16,maxTicks=300),rejectedInvalidBatches=4)
        self.write('collector-check.json',data)
        elapsed=time.monotonic()-start
        self.assertLess(elapsed,60)
        size=(self.out/'collector-check.json').stat().st_size
        self.assertLess(size,100000)
        self.write('timings.json',dict(seconds=elapsed,limitSeconds=60,simulationTicks=1050,
            cases=7,batchEvaluateCalls=1,perTickRoundtrips=0,capturedFrames=0,
            collectorBytes=size,byteLimit=100000,traceRows=sum(len(r['events']) for r in batch+[trusted])))
        print('PASS collectors: 5 tolerance passes, held control fails, trusted input/contact events; 1050 ticks; bounded clearance and traces')

    def test_03_coverage_and_archived_dependencies(self):
        import importlib
        replaced=[
            dict(legacy='test_grapple_over_redesign.Task557Tests.test_01_runtime_measurements',
                 expectation='legacy v3 coordinates and 1080/1620 range',
                 replacement=['test_grapple_over_redesign.Task558Tests.test_03_range_consumers_and_attached_rope',
                              'test_grapple_over_redesign.Task564Tests.test_01_complete_calibrated_blueprint']),
            dict(legacy='test_grapple_over_level.Task464Tests.test_manifest_and_full_map',
                 expectation='legacy full mountain manifest; replacement currently partial preview',
                 replacement=['test_grapple_over_redesign.Task558Tests.test_02_built_prefix_and_real_input',
                              'test_grapple_over_redesign.Task564Tests.test_03_graph_clearances_and_decoded_map'])]
        preserved=['test_grapple_over_input.Task450Tests.test_input_touch_mouse_cancel_camera_ui',
                   'test_grapple_over_physics.Task447Tests.test_green_reflection_and_old_modes',
                   'test_grapple_over_save.Task456Tests.test_invalid_atomic_rejection',
                   'test_grapple_over_grapple.Task452Tests.test_multiple_segments_beyond_range']
        for identifier in preserved+[r['legacy'] for r in replaced]+[v for r in replaced for v in r['replacement']]:
            module,cls,method=identifier.split('.')
            self.assertTrue(callable(getattr(getattr(importlib.import_module(module),cls),method)))
        config=json.loads(next(l.split(' ',1)[1] for l in (ROOT/'artifacts/TASK-564/commands.log').read_text().splitlines() if l.startswith('TASK564_CONFIG ')))
        runtime={n:h for n,h in config['source_hashes'].items() if not n.startswith(('tools/','docs/'))}
        self.assertGreater(len(runtime),20)
        for name,digest in runtime.items(): self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
        archived=[]
        for task in range(560,565):
            path=f'artifacts/TASK-{task}/tests.log';log=(ROOT/path).read_text()
            self.assertIn('\nOK\n',log);self.assertRegex(log,r'Ran [1-9][0-9]* tests')
            archived.append(dict(path=path,summary=log[log.rfind('\nRan '):].strip()))
        self.write('coverage-map.json',dict(replacedGeometry=replaced,preservedBehavior=preserved,
            policy='Historical geometry stays runnable for legacy; no blanket skips or expected failures. Planned blueprint assertions are not full mountain gameplay proof.',
            broaderLegacyGeometry='test_grapple_over_sections v3 coordinate/tolerance fixtures remain legacy-only; replacement encounter assertions must be added as encounters are built',
            unchangedRuntimeHashes=runtime,archived=archived,
            changedDependencies=['tools/test_grapple_over_redesign.py','tools/grapple_over_collection.py','tools/grapple_over_collector.js'],
            reuse='Compare source hashes, not moving HEAD; historical calibration needs no regeneration'))
        print('PASS coverage: named legacy/replacement assertions resolve; input physics save rope preserved; runtime hashes match TASK-564; archived 560-564 OK')

    def test_04_evidence_inventory(self):
        assertions={'commands.log':'exact command, exit and browser/viewport/revision/source hashes',
            'tests.log':'four executed Task565Tests identifiers, nonzero count and OK',
            'selection.log':'COLLECTED 4 and rejection of substring/duplicate/missing/empty classes; child EXIT 0',
            'encounter.json':'only S01-E01 planned encounter exported by child',
            'collector-check.json':'five passing tolerance cases, failing held control, trusted inputs, compact contacts/route/clearance',
            'coverage-map.json':'named geometry replacements and preserved behavior; archived runtime hash identity',
            'timings.json':'bounded seconds, 1050 ticks and measured collector bytes',
            'evidence-index.json':'inventory and dependencies'}
        self.write('evidence-index.json',dict(artifacts=assertions,source_hashes=self.config['source_hashes'],
            scope='isolated fixture tooling; no capture needed; final runner audits completed logs',
            dependencies='collector -> existing METRICS -> production input/physics; exporter -> blueprint; no runtime changes'))
        for name in assertions:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'): json.loads((self.out/name).read_text())
        total=sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file())
        self.assertLess(total,200_000_000)
        print('PASS inventory: 8 artifacts exist; JSON parses; evidence below 200 MB')


class Task566Tests(unittest.TestCase):
    """Isolated minimal-preview save fixtures, not continuous gameplay."""
    key = 'grapnelninja.grappleOver.preview.replacement-v1'
    legacy = {'grapnelninja.records': '{"classic":123,"bad":456}',
              'grapnelninja.lang': 'en', 'grapnelninja.tutorialDone': 'true',
              'grapnelninja.time': '90', 'grapnelninja.grappleOver': 'legacy-save-sentinel'}

    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task566Tests')
        Task557Tests.setUpClass.__func__(cls)

    write = Task557Tests.write

    def page(self, seed=None, preview=True):
        ctx = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(ctx.close)
        p = ctx.new_page()
        errors = []
        p.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        p.add_init_script(SEED_SCRIPT % 1)
        p.add_init_script("const raf566=window.requestAnimationFrame;window.requestAnimationFrame=fn=>fn.name==='gameLoop'?0:raf566.call(window,fn)")
        # Seed only once, so reload actually consumes production-written storage.
        p.add_init_script('if (!sessionStorage.seeded566) { for (const [k,v] of Object.entries(' +
                          json.dumps({**self.legacy, **(seed or {})}) +
                          ')) localStorage.setItem(k,v); sessionStorage.seeded566="yes"; }')
        p.goto(self.url + ('?grapplePreview=replacement-v1' if preview else ''))
        self.enter(p)
        return p

    def enter(self, p):
        wait_for_boot(p)
        p.evaluate("cancelAnimationFrame(game);window.requestAnimationFrame=()=>0;if(version!=='grapple_over')startGame('grapple_over');cancelAnimationFrame(game)")
        p.wait_for_function('!unTouch')

    def flush(self, p):
        p.evaluate('PROGRESS.flushClimb()')
        p.wait_for_function('k=>localStorage.getItem(k)===JSON.stringify(captureClimbState())', arg=self.key)
        return json.loads(p.evaluate('k=>localStorage.getItem(k)', self.key))

    def test_01_layout_validation_and_safe_fallback(self):
        p = self.page()
        rows = p.evaluate('''() => {
            const before=captureClimbState(), rows=[];
            for (const identity of [null,'grapple-over-legacy-v3','wrong-layout']) {
                const s=structuredClone(before);s.player.x=987654;s.player.y=-987654;
                if(identity===null)delete s.layoutId;else s.layoutId=identity;
                const objects=[ninja,grapnel,floors[0]];let error=null;
                try{restoreClimbState(s)}catch(e){error=e.message}
                rows.push({identity,payload:s,error,before,after:captureClimbState(),
                    sameObjects:objects[0]===ninja&&objects[1]===grapnel&&objects[2]===floors[0]});
            }return rows;
        }''')
        fallback = []
        for row in rows:
            self.assertEqual(row['error'], 'InvalidClimbState')
            self.assertEqual(row['before'], row['after'])
            self.assertTrue(row['sameObjects'])
            q = self.page({self.key: json.dumps(row['payload'])})
            result = q.evaluate('''() => ({state:captureClimbState(),spawn:floors[0].level.spawn,
                range:grappleOverAcquisitionRadius(),notice:document.getElementById('climb-save-notice')?.textContent})''')
            self.assertIn('Starting at the replacement base.', result['notice'])
            self.assertEqual(result['state']['player']['x'], result['spawn']['x'])
            self.assertEqual(result['state']['player']['y'], result['spawn']['y'])
            self.assertEqual(result['state']['simulationTick'], 0)
            self.assertEqual(result['range'], 360)
            self.assertEqual(result['state']['stats']['maxHeight'], 0)
            fallback.append(result)
        reset = p.evaluate('''() => {floors[0].rangeUpgraded=true;ninja.y=-400;PROGRESS.resetClimb();
            return {state:captureClimbState(),spawn:floors[0].level.spawn,range:grappleOverAcquisitionRadius()}}''')
        self.assertEqual(reset['range'], 360)
        self.assertFalse(reset['state']['upgrades']['range'])
        self.assertEqual(reset['state']['simulationTick'], 0)
        self.assertEqual(reset['state']['player']['x'], reset['spawn']['x'])
        saved = self.flush(p)
        modes = []
        for mode in ['classic', 'bad']:
            modes.append(p.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);menu.unPause();
                for(let i=0;i<8;i++)physics();PROGRESS.flush();
                return {mode:version,record:scoreText.record[m],scale:scale[version]}}''', mode))
        p.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
        self.assertEqual(p.evaluate('captureClimbState()'), saved)
        storage = p.evaluate('keys=>Object.fromEntries(keys.map(k=>[k,localStorage.getItem(k)]))', list(self.legacy))
        self.assertGreaterEqual(int(storage['grapnelninja.time']), 90)
        for key in self.legacy:
            if key != 'grapnelninja.time':
                self.assertEqual(storage[key], self.legacy[key])
        self.assertEqual([r['record'] for r in modes], [123,456])
        # Legacy serialization version 1 without an identity remains playable
        # in the original layout, but cannot be imported into the preview.
        old = self.page({'grapnelninja.grappleOver': ''}, preview=False)
        legacy = old.evaluate('''() => {const s=captureClimbState();delete s.layoutId;
            restoreClimbState(s);return {state:captureClimbState(),range:grappleOverAcquisitionRadius()}}''')
        self.assertEqual(legacy['range'], 1080)
        self.write('save-compat.json', dict(config=self.config, atomic=rows, fallback=fallback,
                   reset=reset, sameLayout=saved, storageBefore=self.legacy, storageAfter=storage,
                   modes=modes, legacy=legacy))
        print('PASS save-compat: 3 layout identities rejected atomically; replacement-base notice; reset range=360; classic/bad records=123/456 and settings preserved; legacy range=1080')

    def test_02_current_state_continuation(self):
        p = self.page()
        rows = []
        for kind in ['in-air', 'moving-anchor']:
            initial = p.evaluate('''kind => {
                const level=structuredClone(replacementMountainLevel(GRAPPLE_OVER_REPLACEMENT));
                if(kind==='moving-anchor')level.movers=[{id:'fixture-motion',element:'preview-anchor',axis:'x',min:2490,max:2550,periodMs:1700,phase:.25}];
                floors=[loadFixedLevel(level)];
                ninja.x=2400;ninja.y=-250;ninja.speedX=.3;ninja.speedY=1;
                grapnel=new Grapnel({stroke:STYLE.colors.player.cyan});
                pressHeld=stalePress=gameplayPressOwned=false;
                floors[0].rangeUpgraded=true;
                floors[0].climbStats.maxHeight=9000;
                if(kind==='moving-anchor'){
                    const e=floors[0].byId.get('preview-anchor');
                    grapnel.throwed=grapnel.grappled=true;grapnel.pos=[[e.x,e.y,e]];
                }
                menu.unPause();for(let i=0;i<7;i++)physics();return captureClimbState();
            }''', kind)
            replay = '''() => {const trace=[];for(let i=0;i<60;i++){physics();if(i%10===9)trace.push(captureClimbState())}return trace}'''
            first = p.evaluate(replay)
            restored = p.evaluate('s=>{restoreClimbState(s);return captureClimbState()}', initial)
            second = p.evaluate(replay)
            self.assertEqual(restored, initial)
            self.assertEqual(first, second)
            self.assertTrue(restored['upgrades']['range'])
            self.assertEqual(p.evaluate('grappleOverAcquisitionRadius()'), 540)
            self.assertNotEqual(restored['player']['y'], -restored['stats']['maxHeight'])
            self.assertNotEqual(first[-1]['player']['y'], initial['player']['y'])
            if kind == 'moving-anchor':
                self.assertEqual(restored['grapple']['segments'][0]['id'], 'preview-anchor')
                self.assertNotEqual(first[0]['elements'][1]['x'], first[-1]['elements'][1]['x'])
            rows.append(dict(kind=kind, initial=initial, restored=restored,
                             uninterrupted=first, resumed=second, range=540))
        # Persist/reload the actual minimal fixture (no custom mover injection).
        q = self.page()
        q.evaluate('''menu.unPause();ninja.x=2350;ninja.y=-300;ninja.speedY=1;
            floors[0].rangeUpgraded=true;floors[0].climbStats.maxHeight=9000;
            for(let i=0;i<15;i++)physics()''')
        saved = self.flush(q)
        q.reload();self.enter(q)
        restored = q.evaluate('captureClimbState()')
        self.assertEqual(saved, restored)
        self.assertTrue(q.evaluate('menu.gamePaused'))
        self.assertEqual(q.evaluate('grappleOverAcquisitionRadius()'), 540)
        # Trusted release through the existing input path, then resume physics.
        q.mouse.up()
        q.evaluate('menu.unPause();for(let i=0;i<20;i++)physics()')
        continued = q.evaluate('captureClimbState()')
        self.assertGreater(continued['player']['y'], restored['player']['y'])
        self.write('preview-save.json', dict(config=self.config, fixtures=rows,
                   scope='Isolated minimal preview; moving-anchor is a test-only mover, not continuous gameplay',
                   persisted=saved, reloaded=restored, continued=continued))
        print('PASS preview-save: same-layout roundtrip; in-air/moving-anchor 60-tick exact continuation; upgrade range=540; reload preserves current position, maxHeight=9000 is statistics only')


class Task567Tests(unittest.TestCase):
    """Actual preview-base traversal. No pose/velocity fixtures or physics changes."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task567Tests')
        Task558Tests.setUpClass.__func__(cls)
        for name in ['tools/grapple_over_yard.js', 'render/landmarks.js',
                     'tools/browser_test_support.py', 'docs/grapple-over-blueprint.json']:
            cls.config['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.config['simulation'] = 'actual preview spawn, production handlers/physics, trusted mouse'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK567_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write

    def page(self):
        ctx=self.browser.new_context(viewport=VIEWPORT,device_scale_factor=1)
        self.addCleanup(ctx.close)
        p=ctx.new_page(); errors=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        self.addCleanup(lambda:self.assertEqual(errors,[]))
        p.add_init_script(SEED_SCRIPT % 1)
        p.add_init_script("const raf567=window.requestAnimationFrame;window.requestAnimationFrame=fn=>fn.name==='gameLoop'?0:raf567.call(window,fn)")
        p.goto(self.url+'?grapplePreview=replacement-v1');wait_for_boot(p)
        p.evaluate('cancelAnimationFrame(game);window.requestAnimationFrame=()=>0')
        p.wait_for_function('!unTouch')
        self.assertEqual(p.evaluate('({x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY})'),dict(x=2160,y=0,vx=0,vy=0))
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_yard.js'))
        return p

    def press(self,p,target=None):
        xy=p.evaluate('p=>YARD.client(p)',target or dict(x=2420,y=-139))
        p.mouse.move(xy['x'],xy['y']);p.mouse.down()

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def result(self,p):
        r=p.evaluate('YARD.result()')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        return r

    @staticmethod
    def landings(r,id='yard-landing'):
        return [s for s in r['rows'] if any(c['id']==id and c['ny']<-.9 for c in s['contacts'])]

    def capture(self,p,name):
        p.evaluate('TUTORIAL_HINT.visible=false;draw()')
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        with Image.open(self.out/name) as im:
            im.load();self.assertEqual(im.size,(1280,720))
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'loading-yard')

    def test_01_live_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''() => ({elements:floors[0].level.elements,sections:floors[0].level.sections,
          movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
          spawn:floors[0].level.spawn,calibrated:GRAPPLE_OVER_MOVEMENT.patterns[0],
          target:{x:2420,y:-139},reach:Math.hypot(2420-ninja.x,-139-ninja.y)})''')
        self.assertEqual([e['id'] for e in g['elements']],['yard-entry','yard-landing','yard-anchor','yard-catch'])
        self.assertEqual(g['movers'],[]);self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],g['range'])
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if e['id']!='yard-anchor':self.assertGreaterEqual(e['width'],540)
        g['gap']=g['elements'][1]['x']-g['elements'][0]['x']-g['elements'][0]['width']
        self.assertEqual(g['gap'],g['calibrated']['gap'])
        self.assertEqual(g['sections'][0]['labelKey'],'climb.section.loadingYard')
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p);self.step(p,30);p.mouse.up();self.step(p,75)
        r=self.result(p);land=self.landings(r);self.assertTrue(land)
        self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        streak=0;best=0
        for s in r['rows'][:land[0]['tick']-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(streak,6)
        self.assertFalse(self.landings(r,'yard-anchor'))
        r.update(takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=30,landingTick=land[0]['tick'],landingAir=streak,
                 entryToExit=True,scope='Actual base to S01-01 exit only; not base-to-summit')
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f"PASS geometry: 4 green colliders; shelves 540/540 catch 6480; gap 252; reach {g['reach']:.3f} < 360; planned terrain excluded")
        print(f"PASS route: trusted base entry -> exit; release 30 landing {land[0]['tick']}; consecutive unattached airborne ticks {streak}; images decoded 1280x720 with Loading Yard")

    def test_02_miss_and_normal_recovery(self):
        p=self.page();self.press(p);self.step(p,6);p.mouse.up();self.step(p,174)
        before=self.result(p);catch=self.landings(before,'yard-catch')
        self.assertTrue(catch);self.assertFalse(self.landings(before))
        self.press(p,dict(x=2230,y=30));self.step(p,24);p.mouse.up();self.step(p,36)
        r=self.result(p);returned=[s for s in self.landings(r,'yard-entry') if s['tick']>180]
        self.assertTrue(returned)
        r.update(earlyReleaseTick=6,catchTick=catch[0]['tick'],returnTick=returned[0]['tick'],
                 recoveryTarget='yard-entry',recoveryPressTick=180,recoveryReleaseTick=204,
                 resets=0,poseInjections=0,scope='One uninterrupted attempt from actual base through miss and return')
        self.write('miss.json',r)
        print(f"PASS miss: early release 6 -> catch {catch[0]['tick']} -> entry {returned[0]['tick']}; 4 trusted inputs; no reset or pose injection")

    def test_03_hold_and_repeated_nearest(self):
        cases=[]
        p=self.page();self.press(p);self.step(p,300)
        r=self.result(p);r['probe']='continuous hold';r['successfulAlternative']=bool(self.landings(r))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(300//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                  successfulAlternative=bool(self.landings(r)))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,inspection='Every landing contact inspected; success means top-facing exit contact, same definition as nominal',
                   bound='300 ticks continuous hold; repeated nearest 6/12/24 held ticks plus one release tick'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: 4 bounded trusted probes; continuous hold 300 ticks and repeated nearest 6/12/24; zero exit top contacts, no successful alternatives')
        required=['commands.log','tests.log','geometry.json','route.json','inputs.json','miss.json','approach.jpg','landing.jpg','controls.json']
        self.write('evidence-index.json',dict(config=self.config,artifacts={n:{
            'commands.log':'exact invocation, exit status and source/browser configuration',
            'tests.log':'three Task567Tests executed, no skips, OK',
            'geometry.json':'four live green colliders, purposes, widths, calibrated gap and reachable launch',
            'route.json':'production base-to-exit contacts and airborne streak',
            'inputs.json':'trusted nominal mouse events with release tick',
            'miss.json':'uninterrupted early-release catch and return to entry',
            'approach.jpg':'decoded actual base with broad targets and loading gantry',
            'landing.jpg':'decoded actual exit contact at tick 105',
            'controls.json':'all four bounded alternative traces and contact inspections'}[n] for n in required},
            dependencies=['mountain.js built preview prefix -> fixedlevel.js production colliders',
              'render/landmarks.js -> existing Loading Yard sprite; no collider',
              'mountain.js section labelKey -> menu.js HUD -> i18n.js Loading Yard translation',
              'tools/grapple_over_yard.js -> observes unchanged physics.js/events.js/sprites/ninja.js',
              'TASK-564 blueprint and TASK-560 calibrated opening envelope'],
            superseded='TASK-558/566 minimal preview-catch and preview-anchor geometry fixtures are historical; their input/save contracts are unchanged. Legacy v3 tests remain legacy-only.',
            scope='Only S01-01. No full mountain proof. Identical source hashes survive a HEAD-only change.'))


class Task568Tests(unittest.TestCase):
    """Continuous actual-base traversal through the second Loading Yard bay."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task568Tests')
        Task558Tests.setUpClass.__func__(cls)
        for name in ['tools/grapple_over_yard.js', 'render/landmarks.js',
                     'tools/browser_test_support.py', 'docs/grapple-over-blueprint.json']:
            cls.config['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.config['simulation'] = 'actual preview base; unchanged production physics and trusted mouse input'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK568_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task567Tests.write
    page = Task567Tests.page
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    capture = Task567Tests.capture
    target = dict(x=3152,y=-199)

    def approach(self):
        p=self.page()
        self.press(p);self.step(p,30);p.mouse.up();self.step(p,75)
        self.assertEqual(self.landings(self.result(p))[0]['tick'],105)
        # Reposition on the broad shared shelf through ordinary grapple input.
        self.press(p,dict(x=2900,y=30));self.step(p,26);p.mouse.up()
        self.assertEqual(self.landings(self.result(p))[-1]['tick'],131)
        return p

    def test_01_connected_geometry_and_release(self):
        p=self.approach()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),entry:{x:ninja.x,y:ninja.y},
            calibrated:GRAPPLE_OVER_MOVEMENT,dragCount:floors[0].dragZones.length})''',self.target)
        self.assertEqual(g['sections'][0]['encounters'],['S01-01','S01-02'])
        self.assertEqual(len(g['elements']),6);self.assertEqual(g['movers'],[])
        self.assertEqual(g['dragCount'],0);self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],360)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        es={e['id']:e for e in g['elements']}
        g['gap']=es['yard-second-landing']['x']-es['yard-landing']['x']-es['yard-landing']['width']
        g['rise']=es['yard-landing']['y']-es['yard-second-landing']['y']
        self.assertEqual(g['gap'],252);self.assertEqual(g['rise'],60)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,18);p.mouse.up();self.step(p,48)
        r=self.result(p);lands=self.landings(r,'yard-second-landing');self.assertTrue(lands)
        landing=lands[0]['tick'];streak=0
        for s in r['rows'][149:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
        self.assertGreaterEqual(streak,6)
        self.assertTrue(any(s['attached'] for s in r['rows'][131:149]))
        r.update(takeoffTick=132,releaseTick=149,landingTick=landing,landingAir=streak,
                 entryTick=131,entryToExit=True,resets=0,poseInjections=0,
                 scope='Continuous actual base through S01-01 to S01-02 only; no summit claim')
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: six green purposeful colliders; landing 540 catch 6480 gap 252 rise 60 reach {g["reach"]:.3f} < 360; planned excluded')
        print(f'PASS route: base -> S01-01 105 -> planning contact 131 -> release 149 -> S01-02 {landing}; unattached airborne {streak}; trusted inputs; images decoded')

    def test_02_late_miss_and_recovery(self):
        p=self.approach();self.press(p,self.target);self.step(p,45);p.mouse.up();self.step(p,38)
        before=self.result(p);catch=self.landings(before,'yard-catch')
        self.assertTrue(catch);self.assertFalse(self.landings(before,'yard-second-landing'))
        self.press(p,dict(x=3294,y=-30));self.step(p,24);p.mouse.up();self.step(p,499)
        r=self.result(p);returned=self.landings(r,'yard-second-landing');self.assertTrue(returned)
        r.update(lateReleaseTick=176,catchTick=catch[0]['tick'],recoveryPressTick=214,
                 recoveryReleaseTick=238,returnTick=returned[0]['tick'],recoveryTarget='yard-second-landing',
                 resets=0,poseInjections=0,scope='Uninterrupted base, late miss, catch and normal-control return')
        self.write('miss.json',r)
        print(f'PASS miss: late release 176 catch {catch[0]["tick"]} recovery press 214 release 238 return {returned[0]["tick"]}; no reset or injection')

    def test_03_hold_nearest_and_tolerance(self):
        cases=[]
        p=self.approach();self.press(p,self.target);self.step(p,300)
        r=self.result(p);r.update(probe='continuous hold',successfulAlternative=bool(self.landings(r,'yard-second-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.approach();targets=[]
            for i in range(300//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'yard-second-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,inspection='Every top-facing second-landing contact inspected, including all successful alternatives',bound='300 ticks after actual shared-shelf approach'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        tolerance=[]
        for hold in [12,24]:
            p=self.approach();self.press(p,self.target);self.step(p,hold);p.mouse.up();self.step(p,150)
            r=self.result(p);land=self.landings(r,'yard-second-landing');self.assertTrue(land)
            tolerance.append(dict(hold=hold,landingTick=land[0]['tick'],inputs=r['inputs'],rows=r['rows']))
        self.write('tolerance.json',tolerance)
        print('PASS controls: four bounded trusted probes, zero exit contacts; release tolerance 12/18/24 succeeds')
        required={'commands.log':'exact commands, exit status, revision, hashes and browser configuration',
            'tests.log':'three exact Task568Tests identifiers, no skips, OK',
            'geometry.json':'six live green colliders, widths, purposes, gap 252 rise 60 reachable target',
            'route.json':'continuous base through shared planning contact to second landing, airborne streak',
            'inputs.json':'trusted production mouse events matching route ticks',
            'miss.json':'late miss, catch and return without reset or injection',
            'approach.jpg':'shared planning shelf, green target and Loading Yard gantry',
            'landing.jpg':'second raised bay landing and Loading Yard structure',
            'controls.json':'four bounded hold/nearest probes with all contact traces inspected',
            'tolerance.json':'12/24-tick release successes surrounding nominal 18'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,
            dependencies=['mountain.js built preview -> fixedlevel.js colliders',
                'tools/grapple_over_yard.js observations -> unchanged physics.js/events.js/sprites/ninja.js',
                'TASK-564 blueprint opening pattern -> 252 gap/540 shelves; TASK-560 calibration',
                'render/landmarks.js unchanged Loading Yard art'],
            superseded='Task567 exact four-collider inventory is historical; its first route remains asserted here. Legacy v3 coverage is unchanged.',
            scope='S01-02 only plus physical connection; identical tested hashes remain valid after HEAD-only commit'))


class Task569Tests(unittest.TestCase):
    """Continuous actual-base traversal through the leftward upper return terrace."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task569Tests')
        Task558Tests.setUpClass.__func__(cls)
        for name in ['tools/grapple_over_yard.js', 'render/landmarks.js',
                     'tools/browser_test_support.py', 'docs/grapple-over-blueprint.json']:
            cls.config['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.config['simulation'] = 'actual preview base; unchanged production physics and trusted mouse input'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK569_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task567Tests.write
    page = Task567Tests.page
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    capture = Task567Tests.capture
    target = dict(x=3230,y=-350)

    def approach(self):
        p=Task568Tests.approach(self)
        self.press(p,Task568Tests.target);self.step(p,18);p.mouse.up();self.step(p,48)
        self.assertEqual(self.landings(self.result(p),'yard-second-landing')[0]['tick'],197)
        return p

    def test_01_connected_geometry_and_release(self):
        p=self.approach()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),entry:{x:ninja.x,y:ninja.y},
            calibrated:GRAPPLE_OVER_MOVEMENT,dragCount:floors[0].dragZones.length})''',self.target)
        self.assertEqual(g['sections'][0]['encounters'],['S01-01','S01-02','S01-03'])
        self.assertEqual(len(g['elements']),8);self.assertEqual(g['movers'],[])
        self.assertEqual(g['dragCount'],0);self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],360)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        es={e['id']:e for e in g['elements']}
        g['gap']=es['yard-second-landing']['x']-es['yard-third-landing']['x']-es['yard-third-landing']['width']
        g['rise']=es['yard-second-landing']['y']-es['yard-third-landing']['y']
        g['direction']='left and up; previous transfer right and up'
        g['localCatch']='yard-second-landing'
        g['calibrationNote']='TASK-564 opening widths/gap; production validation of 240-unit rise and leftward variation in route.json'
        self.assertEqual(g['gap'],252);self.assertEqual(g['rise'],240)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,45);p.mouse.up();self.step(p,208)
        r=self.result(p);lands=self.landings(r,'yard-third-landing');self.assertTrue(lands)
        landing=lands[0]['tick'];streak=0
        for s in r['rows'][242:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
        self.assertGreaterEqual(streak,6)
        self.assertLess(lands[0]['x'],g['entry']['x'])
        self.assertLess(r['rows'][197]['y'],g['entry']['y'])
        self.assertTrue(any(s['attached'] for s in r['rows'][197:242]))
        r.update(takeoffTick=198,releaseTick=242,landingTick=landing,landingAir=streak,
                 entryTick=197,entryToExit=True,resets=0,poseInjections=0,
                 scope='Continuous actual base through S01-01 and S01-02 to S01-03 only; no summit claim')
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: eight green purposeful colliders; landing 540 catch 6480 gap 252 rise 240 reach {g["reach"]:.3f} < 360; planned excluded')
        print(f'PASS route: base -> S01-01 105 -> second landing 197 -> leftward release 242 -> S01-03 {landing}; unattached airborne {streak}; trusted inputs; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.approach();self.press(p,self.target);self.step(p,36);p.mouse.up();self.step(p,251)
        before=self.result(p)
        catch=[s for s in self.landings(before,'yard-second-landing') if s['tick']>197]
        self.assertEqual(catch[0]['tick'],474)
        self.assertFalse(self.landings(before,'yard-third-landing'))
        self.press(p,self.target);self.step(p,12);p.mouse.up();self.step(p,350)
        r=self.result(p);returned=self.landings(r,'yard-third-landing');self.assertTrue(returned)
        r.update(earlyReleaseTick=233,catchTick=474,catchTarget='yard-second-landing',recoveryPressTick=484,
                 recoveryReleaseTick=496,returnTick=returned[0]['tick'],recoveryTarget='yard-third-landing',
                 resets=0,poseInjections=0,scope='Uninterrupted base, early miss, broad local catch and normal-control return')
        self.write('miss.json',r)
        print(f'PASS miss: early release 233 local catch 474 recovery press 484 release 496 return {returned[0]["tick"]}; no reset or injection')

    def test_03_hold_nearest_and_tolerance(self):
        cases=[]
        p=self.approach();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold',successfulAlternative=bool(self.landings(r,'yard-third-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.approach();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'yard-third-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,inspection='Every top-facing third-landing contact inspected, including all successful alternatives',bound='600 ticks after actual shared-shelf approach'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        tolerance=[]
        for hold in [46,48]:
            p=self.approach();self.press(p,self.target);self.step(p,hold);p.mouse.up();self.step(p,300)
            r=self.result(p);land=self.landings(r,'yard-third-landing');self.assertTrue(land)
            tolerance.append(dict(hold=hold,landingTick=land[0]['tick'],inputs=r['inputs'],rows=r['rows']))
        self.write('tolerance.json',tolerance)
        print('PASS controls: four bounded trusted probes, zero exit contacts; release tolerance 45/46/48 succeeds')
        required={'commands.log':'exact commands, exit status, revision, hashes and browser configuration',
            'tests.log':'three exact Task569Tests identifiers, no skips, OK',
            'geometry.json':'eight live green colliders, widths, purposes, gap 252 rise 240 reachable target',
            'route.json':'continuous base through shared planning contact to third landing, airborne streak',
            'inputs.json':'trusted production mouse events matching route ticks',
            'miss.json':'early miss, catch and return without reset or injection',
            'approach.jpg':'shared planning shelf, green target and Loading Yard gantry',
            'landing.jpg':'upper return terrace and Loading Yard structure',
            'controls.json':'four bounded hold/nearest probes with all contact traces inspected',
            'tolerance.json':'46/48-tick release successes after nominal 45'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,
            dependencies=['mountain.js built preview -> fixedlevel.js colliders',
                'tools/grapple_over_yard.js observations -> unchanged physics.js/events.js/sprites/ninja.js',
                'TASK-564 blueprint opening pattern -> 252 gap/540 shelves; TASK-560 calibration',
                'render/landmarks.js unchanged Loading Yard art'],
            superseded='Task567/568 exact four/six-collider inventories are historical; their earlier routes remain asserted here. Legacy v3 coverage is unchanged.',
            scope='S01-03 only plus physical connection; identical tested hashes remain valid after HEAD-only commit'))


class Task570Tests(unittest.TestCase):
    """Actual-base four-encounter run; summit gating is a separate labelled fixture."""
    @classmethod
    def setUpClass(cls):
        Task569Tests.setUpClass.__func__(cls)

    write = Task567Tests.write
    page = Task567Tests.page
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    capture = Task567Tests.capture
    target = dict(x=2780,y=-590)

    def approach(self):
        p=Task569Tests.approach(self)
        self.press(p,Task569Tests.target);self.step(p,45);p.mouse.up();self.step(p,208)
        self.assertEqual(self.landings(self.result(p),'yard-third-landing')[0]['tick'],450)
        return p

    def test_01_geometry_and_continuous_section(self):
        p=self.approach()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),entry:{x:ninja.x,y:ninja.y},
            calibrated:GRAPPLE_OVER_MOVEMENT,dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][0]['encounters'],['S01-01','S01-02','S01-03','S01-04'])
        self.assertEqual(len(g['elements']),10);self.assertEqual(g['movers'],[])
        self.assertEqual(g['dragCount'],0);self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertIsNone(g['finish']);self.assertLess(g['reach'],360)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        es={e['id']:e for e in g['elements']}
        g['gap']=es['yard-third-landing']['x']-es['yard-fourth-landing']['x']-es['yard-fourth-landing']['width']
        g['rise']=es['yard-third-landing']['y']-es['yard-fourth-landing']['y']
        g.update(localCatch='yard-third-landing',calibrationNote='TASK-564 widths/gap; fresh production proof for 240 rise, upper launch and leftward release')
        self.assertEqual(g['gap'],252);self.assertAlmostEqual(g['rise'],240)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,75);p.mouse.up();self.step(p,147)
        r=self.result(p);lands=self.landings(r,'yard-fourth-landing');self.assertTrue(lands)
        landing=lands[0]['tick'];streak=0
        for s in r['rows'][525:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
        self.assertGreaterEqual(streak,6)
        self.assertTrue(any(s['attached'] for s in r['rows'][450:525]))
        r.update(entryTick=450,takeoffTick=451,releaseTick=525,landingTick=landing,landingAir=streak,
                 entryToExit=True,resets=0,poseInjections=0,scope='Continuous actual preview base through S01-04; no summit claim')
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        exits=[dict(encounter=f'S01-0{i+1}',collider=id,tick=self.landings(r,id)[0]['tick'])
               for i,id in enumerate(['yard-landing','yard-second-landing','yard-third-landing','yard-fourth-landing'])]
        self.assertEqual([e['tick'] for e in exits],[105,197,450,672])
        self.assertFalse(p.evaluate('floors[0].climbStats.completed'))
        self.write('section-route.json',dict(entry='actual preview base, not fixture',exits=exits,resets=0,
            handoffs='same page and physics state throughout; route.json holds every tick',completionEvents=0))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 10 purposeful green colliders; shelves >=540 gap 252 rise 240 reach {g["reach"]:.3f} < 360; no planned terrain')
        print(f'PASS section: actual base exits 105/197/450/672; release 525; airborne unattached {streak}; zero resets/injections/completions; trusted inputs; images decoded')

    def test_02_late_miss_and_recovery(self):
        p=self.approach();self.press(p,self.target);self.step(p,90);p.mouse.up();self.step(p,240)
        before=self.result(p);catch=[s for s in self.landings(before,'yard-third-landing') if s['tick']>540]
        self.assertTrue(catch);self.assertFalse(self.landings(before,'yard-fourth-landing'))
        self.press(p,dict(x=3000,y=-270));self.step(p,48);p.mouse.up()
        self.press(p,self.target);self.step(p,75);p.mouse.up();self.step(p,400)
        r=self.result(p);returned=self.landings(r,'yard-fourth-landing');self.assertTrue(returned)
        r.update(lateReleaseTick=540,catchTick=catch[0]['tick'],catchTarget='yard-third-landing',
                 recoveryPressTick=780,repositionReleaseTick=828,recoveryReleaseTick=903,returnTick=returned[0]['tick'],
                 recoveryTarget='yard-fourth-landing',resets=0,poseInjections=0)
        self.write('miss.json',r)
        print(f'PASS miss: late release 540 local catch {catch[0]["tick"]}; normal-control return {returned[0]["tick"]}; zero resets/injections')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.approach();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold',successfulAlternative=bool(self.landings(r,'yard-fourth-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.approach();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'yard-fourth-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,inspection='All top-facing exit contacts inspected using same nominal success definition',bound='600 ticks from actual third landing'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four trusted 600-tick bounded hold/nearest probes; zero successful alternatives')

    def test_04_summit_gate_fixture_and_index(self):
        p=self.page()
        gate=p.evaluate('''() => {
            const m=JSON.parse(JSON.stringify(GRAPPLE_OVER_REPLACEMENT));
            m.sections=m.sections.filter(s=>s.status==='built');
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const s01=replacementMountainLevel(m).finish;
            m.sections.push({id:'S08',status:'built',encounters:[]});
            const s08=replacementMountainLevel(m).finish;
            // Isolated finish contract fixture, never part of the section route.
            floors[0].level.finish=s08;
            let events=0;const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events++;return original.call(this,name,...args)};
            YARD.step(3);CLIMB_UI.complete();
            return {s01,s08,events,completed:floors[0].climbStats.completed};
        }''')
        self.assertIsNone(gate['s01']);self.assertTrue(gate['s08'])
        self.assertEqual(gate['events'],1);self.assertTrue(gate['completed'])
        gate['scope']='Isolated S08 finish contract fixture at base, not authored S08 or continuous summit gameplay'
        self.write('summit-gate.json',gate)
        required={'commands.log':'exact invocation, exit status, browser, viewport, revision and hashes',
            'tests.log':'four exact Task570Tests identifiers with OK and no skips',
            'geometry.json':'10 green purposeful colliders; broad shelves, calibrated gap and reachable target',
            'route.json':'continuous production trace, release and airborne streak to exit',
            'inputs.json':'trusted production mouse events',
            'miss.json':'late release, third-terrace catch and normal-control return',
            'approach.jpg':'clear upper launch and Loading Yard structure',
            'landing.jpg':'broad section exit and Loading Yard structure',
            'controls.json':'four bounded alternative traces with all exit contacts inspected',
            'section-route.json':'all four exits in order from actual base without resets; zero completion',
            'summit-gate.json':'isolated S01 disabled/S08 enabled exactly-once completion contract'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,
            dependencies=['mountain.js preview geometry and S08 finish gating -> fixedlevel.js -> physics.js',
                'tools/grapple_over_yard.js observes unchanged production handlers/physics',
                'TASK-564 blueprint and TASK-560 calibration referenced in place',
                'render/landmarks.js unchanged Loading Yard artwork'],
            superseded='Task567/568/569 exact geometry inventories are historical; all earlier nominal routes asserted continuously here. Legacy v3 tests unchanged.',
            scope='S01-04 only; identical tested source hashes remain valid across HEAD-only commit'))
        print('PASS summit: isolated fixture S01 finish disabled; S08 completion exactly once; section itself never finishes')


class Task571Tests(unittest.TestCase):
    """Independent S01 attempts using trusted input and unchanged production physics."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task571Tests')
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390}, device_scale_factor=1)
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK571_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

        fixture=cls()
        cls.entries=[]
        for index in range(4):
            p=fixture.page();fixture.approach(p,index)
            cls.entries.append(p.evaluate('captureClimbState()'))
        # Local S01-04 launch fixture mirrors the recorded second-bay entry on the upper shelf.
        # This is explicitly isolated scenario setup, never continuous traversal.
        entry=cls.entries[1]['player']
        cls.entries[3]['player'].update(x=5524-entry['x'],y=entry['y']-300,
            speedX=-entry['speedX'],speedY=entry['speedY'])
        fixture.doCleanups()

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    targets = [dict(x=2420,y=-139), Task568Tests.target, Task569Tests.target, Task570Tests.target]
    holds = [30,18,45,75]
    exits = ['yard-landing','yard-second-landing','yard-third-landing','yard-fourth-landing']

    def page(self, touch=False):
        ctx=self.browser.new_context(viewport={'width':844,'height':390} if touch else VIEWPORT,
                                     device_scale_factor=1,has_touch=touch)
        self.addCleanup(ctx.close)
        p=ctx.new_page();errors=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        self.addCleanup(lambda:self.assertEqual(errors,[]))
        p.add_init_script(SEED_SCRIPT % 1)
        p.add_init_script("const raf571=window.requestAnimationFrame;window.requestAnimationFrame=fn=>fn.name==='gameLoop'?0:raf571.call(window,fn)")
        p.goto(self.url+'?grapplePreview=replacement-v1');wait_for_boot(p)
        p.evaluate('cancelAnimationFrame(game);window.requestAnimationFrame=()=>0')
        p.wait_for_function('!unTouch')
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_yard.js'))
        p.evaluate('''() => {for(const type of ['touchstart','touchend'])document.addEventListener(type,e=>{
            const t=e.changedTouches[0];YARD.result().inputs.push({tick:YARD.result().tick,type,
                trusted:e.isTrusted,x:t.clientX,y:t.clientY});});}''')
        p.touch_session=ctx.new_cdp_session(p) if touch else None
        return p

    def press(self,p,target,offset=0):
        xy=p.evaluate('p=>YARD.client(p)',target);xy['x']+=offset
        self.assertTrue(0<xy['x']<p.viewport_size['width'] and 0<xy['y']<p.viewport_size['height'],xy)
        if p.touch_session:
            p.touch_session.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[xy]))
        else:
            p.mouse.move(xy['x'],xy['y']);p.mouse.down()
        return xy

    def release(self,p):
        if p.touch_session:p.touch_session.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]))
        else:p.mouse.up()

    def approach(self,p,index):
        if index:
            self.press(p,self.targets[0]);self.step(p,30);self.release(p);self.step(p,75)
            self.press(p,dict(x=2900,y=30));self.step(p,26);self.release(p)
        if index>1:
            self.press(p,self.targets[1]);self.step(p,18);self.release(p);self.step(p,48)
        if index>2:
            self.press(p,self.targets[2]);self.step(p,45);self.release(p);self.step(p,208)

    def setup_entry(self,p,index):
        p.evaluate('s=>{restoreClimbState(s);menu.unPause();pressHeld=stalePress=gameplayPressOwned=false}',self.entries[index])

    def frame(self,p,label):
        p.evaluate('draw()')
        im=Image.open(io.BytesIO(p.screenshot(type='jpeg',quality=80))).convert('RGB')
        ImageDraw.Draw(im).text((8,im.height-18),label,fill='white')
        return im

    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-100,0),('late',100,0),('left',0,-12),('right',0,12)]:
                    p=self.page(touch);self.setup_entry(p,index)
                    if index==2:self.step(p,6)
                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    hold=[30,12,51,12][index]+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S01-0{index+1} touch approach'))
                    xy=self.press(p,[self.targets[0],self.targets[1],dict(x=3130,y=-404),dict(x=2372,y=-499)][index],aim);self.step(p,hold);self.release(p)
                    p.evaluate('''id=>{for(let n=0;n<400;n++){YARD.step(1);if(YARD.result().rows.at(-1).contacts.some(c=>c.id===id&&c.ny<-.9))break}}''',self.exits[index])
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S01-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=r['rows'][start:],success=bool(lands))
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S01-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=[s['player'] for s in self.entries],fixtureScope='Recorded entries for S01-01/02/03; mirrored second-bay entry on upper shelf for S01-04; not continuous gameplay',source_hashes=self.config['source_hashes']))
                    p.context.close()
        strip=Image.new('RGB',(844*2,390*4))
        for n,im in enumerate(frames):strip.paste(im,((n%2)*844,(n//2)*390))
        strip.save(self.out/'touch-strip.jpg',quality=85)
        self.assertEqual(len(rows),40)
        self.assertTrue(all(r['success'] for r in rows),[(r['encounter'],r['mode'],r['variant']) for r in rows if not r['success']])
        for r in rows:
            expected='touchstart' if r['mode']=='touch' else 'mousedown'
            self.assertEqual(r['inputs'][0]['type'],expected)
            self.assertTrue(all(i['trusted'] for i in r['inputs']))
        print('PASS tolerance: all 40 cases; 4 encounters x 2 genuine input modes x 5 variants; +/-100 ms and +/-12 CSS px')

    def test_02_recovery(self):
        rows=[]
        for touch in [False,True]:
            for index,(hold,wait,catch_id,actions,return_id) in enumerate([
                (6,174,'yard-catch',[(dict(x=2230,y=30),24,550)],'yard-entry'),
                (45,38,'yard-catch',[(dict(x=3294,y=-30),24,550)],'yard-second-landing'),
                (36,251,'yard-second-landing',[(self.targets[2],12,550)],'yard-third-landing'),
                (1,135,'yard-entry',[(dict(x=2200,y=-330),42,550)],'yard-fourth-landing')]):
                p=self.page(touch);self.setup_entry(p,index);start=p.evaluate('YARD.result().tick')
                self.press(p,self.targets[index] if index<3 else dict(x=2372,y=-499));self.step(p,hold);self.release(p);self.step(p,wait)
                before=self.result(p);catch=[s for s in self.landings(before,catch_id) if s['tick']>start+hold]
                self.assertTrue(catch);self.assertFalse([s for s in self.landings(before,self.exits[index]) if s['tick']>start])
                recovery_start=before['tick']
                for target,duration,coast in actions:
                    self.press(p,target);self.step(p,duration);self.release(p);self.step(p,coast)
                r=self.result(p);returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                self.assertTrue(returned)
                environment=p.evaluate('({movers:floors[0].level.movers,roles:floors[0].level.elements.map(e=>e.role),dragCount:floors[0].dragZones.length})')
                self.assertEqual(environment['movers'],[]);self.assertEqual(set(environment['roles']),{'bounce'})
                self.assertEqual(environment['dragCount'],0)
                rows.append(dict(encounter=f'S01-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-[30,12,51,12][index])*p.evaluate('physicsStepMs'),
                    catch=catch[0],returned=returned[0],returnCollider=return_id,recoveryStart=recovery_start,
                    inputs=r['inputs'],trace=r['rows'][start:],environment=environment,fixtureInitializations=1,resetsAfterStart=0,poseInjectionsAfterStart=0))
                self.write('recovery.json',dict(cases=rows,source_hashes=self.config['source_hashes'],
                    scope='Isolated recorded entry fixtures; ordinary controls after initialization, not continuous gameplay; no movers, hazards or yellow zones in built S01'))
                p.context.close()
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses, lower catches and normal-input escapes; no resets or injections; no mover/hazard/yellow elements present')

    def test_03_evidence_index(self):
        p=self.page()
        geometry=p.evaluate('({elements:floors[0].level.elements,range:grappleOverAcquisitionRadius(),scale:scale[version]})')
        es={e['id']:e for e in geometry['elements']}
        self.assertEqual(geometry['range'],360);self.assertEqual(geometry['scale'],.375)
        self.assertEqual(es['yard-fourth-anchor']['x'],2292)
        self.assertEqual(es['yard-fourth-anchor']['y'],-539)
        self.assertEqual(es['yard-fourth-landing']['y'],-348.2)
        self.assertEqual(max(v['x'] for v in es['yard-fourth-landing']['points']),540)
        p.context.close()
        self.write('affected-proof-map.json',dict(observedGeometry=geometry,geometryChanges=[dict(id='yard-fourth-landing',old=dict(x=1700,y=-528.2,width=540),new=dict(x=1700,y=-348.2,width=540),reason='60-unit rise and 252-unit gap retain a deliberate jump'),dict(id='yard-fourth-anchor',old=dict(x=2700,y=-659),new=dict(x=2292,y=-539),reason='Reachable launch from the left edge of the upper planning shelf, mirroring the calibrated second bay')],runtimeChanges=['mountain.js replacement S01-04 anchor and landing only'],
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg'],
            previousProof=['artifacts/TASK-570/section-route.json','artifacts/TASK-570/commands.log'],
            dependencies=['Task571Tests -> browser_test_support + grapple_over_yard.js -> production events.js, physics.js, fixedlevel.js, mountain.js',
                          'Source hashes, not a HEAD-only commit, determine proof validity'],
            historical='TASK-570 fourth landing geometry, route, recovery and hold controls are historical and superseded locally by this task; S01-01/02/03 geometry, classic/bad, legacy mountain and physics unchanged'))
        required={'commands.log':'command, actual exit, exact collected IDs, browser/viewports/DPR, revision and source hashes',
            'tests.log':'3 exact Task571Tests methods, nonzero count, no skipped cases, OK',
            'tolerance.json':'40 individual successful cases with trusted input timestamps, offsets and top-facing exit contacts',
            'recovery.json':'8 misses outside tolerance, lower contacts and later normal-control return contacts',
            'affected-proof-map.json':'local S01-04 geometry changes, dependencies and refreshed proof',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and source hash provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,
            scope='Isolated S01 fixtures: first three recorded route entries; fourth mirrors the second-bay entry on the upper planning shelf. No continuous gameplay or full-mountain claim'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print('PASS index: all required paths exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')


class Task572Tests(unittest.TestCase):
    """Current built S01 composition and continuous production route review."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)

    write = Task557Tests.write
    page = Task567Tests.page
    press = Task567Tests.press
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)

    def test_01_objects_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''() => ({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,dragCount:floors[0].dragZones.length,
            range:grappleOverAcquisitionRadius(),scale:scale[version],calibration:GRAPPLE_OVER_MOVEMENT})''')
        self.assertEqual(len(g['elements']),10)
        self.assertEqual(g['movers'],[]);self.assertEqual(g['dragCount'],0)
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['purpose'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        self.assertEqual([c['id'] for c in g['encounters']],['S01-01','S01-02','S01-03','S01-04'])
        es={e['id']:e for e in g['elements']}
        gaps=[es[b]['x']-es[a]['x']-es[a]['width'] for a,b in [('yard-entry','yard-landing'),('yard-landing','yard-second-landing'),('yard-third-landing','yard-second-landing'),('yard-fourth-landing','yard-third-landing')]]
        self.assertEqual(gaps,[252]*4)
        g.update(firstUseOrder=['green'],yellow='absent: suppression/clearance not applicable',
            blue='absent: swept bounds/period/acquisition window not applicable',hazards='absent: contact recovery not applicable',
            deliberateGaps=gaps,removedClutter='none: every emitted collider has a route or recovery purpose; planned preview-unbuilt is excluded')
        self.write('objects.json',g)
        old=json.loads((ROOT/'artifacts/TASK-571/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        self.write('dependency.json',dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: additive Task572Tests only'],
            reused=[dict(path='artifacts/TASK-571/tolerance.json',sha256=hashlib.sha256((ROOT/'artifacts/TASK-571/tolerance.json').read_bytes()).hexdigest(),supports='40 input tolerance variants'),
                    dict(path='artifacts/TASK-571/recovery.json',sha256=hashlib.sha256((ROOT/'artifacts/TASK-571/recovery.json').read_bytes()).hexdigest(),supports='8 nonlethal misses and ordinary-control returns')],
            refreshed='Current continuous four-bay route and composition captures; TASK-570 fourth-bay geometry/route superseded by TASK-571',
            dependencies='mountain -> fixedlevel -> production physics/events -> yard observer; render/landmarks -> draw; source hashes survive HEAD-only changes'))
        print('PASS objects: 10 purposeful green colliders; 4 ordered encounters; shelves >=540; gaps 252; movers=0 drag=0 hazards=0; 49 unchanged dependencies')

    def test_02_continuous_route_and_captures(self):
        p=self.page()
        p.evaluate("""() => {TUTORIAL_HINT.visible=false;window.frames572=[];window.capture572=()=>{
            draw();frames572.push({image:canvas.toDataURL('image/jpeg',.85),tick:YARD.result().tick});};capture572()}""")
        approaches=[]
        def capture(label):
            p.evaluate('draw()')
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),label,fill='white');approaches.append(im)
        def step(n):
            p.evaluate('n=>{for(let i=0;i<n;i++){YARD.step(1);if(YARD.result().tick%3===0)capture572()}}',n)
        capture('S01-01 actual base approach / Loading Yard gantry')
        # A composition camera only: preserve the live route camera and player.
        p.evaluate('window.cam572={x:screen.x,y:screen.y};screen.x=width/.375/2-2762;screen.y=height/.375/2+0;draw()')
        p.screenshot(path=str(self.out/'overview.png'))
        flat=p.evaluate("""() => ({elements:floors[0].elements.map(e=>e.getPoints()),
            shape:GRAPPLE_OVER_LANDMARK_SHAPES[0](GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
            landmark:{x:(2366+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,
                      y:(-150+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
            camera:{x:screen.x,y:screen.y},factor:1280/width})""")
        im=Image.new('RGB',(1280,720),'white');pen=ImageDraw.Draw(im);f=flat['factor']
        for part in flat['shape']['parts']:
            pen.polygon([((x+flat['landmark']['x'])*f,(y+flat['landmark']['y'])*f) for x,y in part],fill='#777777')
        for points in flat['elements']:
            pen.polygon([((v['x']+flat['camera']['x'])*.375*f,(v['y']+flat['camera']['y'])*.375*f) for v in points],fill='black')
        pen.text((12,16),'Loading Yard / gantry silhouette (gray), gameplay colliders (black)',fill='black')
        im.save(self.out/'silhouette.png')
        p.evaluate('screen.x=cam572.x;screen.y=cam572.y;draw()')
        actions=[(dict(x=2420,y=-139),30,75),(dict(x=2900,y=30),26,0),
                 (Task568Tests.target,18,48),(Task569Tests.target,45,208),
                 (dict(x=2550,y=-270),12,0),(dict(x=2372,y=-499),12,155)]
        for i,(target,hold,coast) in enumerate(actions):
            if i in [2,3,5]:capture(f'S01-0{[2,3,5].index(i)+2} actual continuous approach / green destination')
            self.press(p,target);step(hold);p.mouse.up();step(coast)
        p.evaluate('capture572()')  # Include the final landing even off the three-tick cadence.
        r=self.result(p)
        exits=[]
        for i,id in enumerate(Task571Tests.exits):
            landed=self.landings(r,id);self.assertTrue(landed,id)
            exits.append(dict(encounter=f'S01-0{i+1}',collider=id,tick=landed[0]['tick']))
        self.assertEqual([e['tick'] for e in exits],[105,197,450,629])
        r.update(exits=exits,scope='Continuous actual preview spawn; trusted input; unchanged production physics',resets=0,poseInjections=0)
        self.write('route.json',r)
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(approaches):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=88)
        # Render-only replay of sampled continuous simulation; no fixture is presented as gameplay.
        clip=p.evaluate('''async () => {
            const stream=canvas.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp9',videoBitsPerSecond:1800000});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of frames572){const image=new Image();image.src=f.image;await image.decode();
                ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(image,0,0);ctx.restore();
                ctx.fillStyle='white';ctx.font='14px sans-serif';ctx.fillText('Continuous S01 production trace replay / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));
            rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});
            return await new Promise(r=>{const reader=new FileReader();reader.onload=()=>r(reader.result.split(',')[1]);reader.readAsDataURL(blob)});
        }''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        # Decode the full retained clip in the browser, not just its container header.
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;
            v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);
            await v.play();await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});
            return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],100);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)
        print(f'PASS continuous route: four exits 105/197/450/629; trusted inputs; zero resets/injections; clip decoded {decoded}')

    def test_03_evidence_index(self):
        required={'commands.log':'exact command, exit status, collected identifiers, revision, hashes and browser configuration',
            'tests.log':'3 exact Task572Tests cases, no skips, OK','overview.png':'all four built bays and Loading Yard gantry',
            'silhouette.png':'plain monochrome structure and open gaps','approaches.jpg':'four actual continuous approach views',
            'objects.json':'all ten purposes, green-only role order and absent conditional obstacles',
            'section.webm':'continuous representative production traversal replay',
            'route.json':'trusted inputs and four ordered landing contacts; no resets or injections',
            'clip-decode.json':'full clip browser decode and frame count',
            'dependency.json':'exact unchanged dependencies and referenced prior proof',
            'review.md':'independent visual observations and pacing assessment',
            'evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreater(im.width,1000)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: JSON parses; three images decode; clip fully decoded; retained evidence <200 MB; visual review follows')


class Task573Tests(unittest.TestCase):
    """S02-01 isolated shared-entry fixture; never a base-to-summit claim."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task573Tests')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S02-01 entry on live yard-fourth-landing; production physics and trusted mouse'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    capture = Task567Tests.capture
    target = dict(x=1520,y=-499)

    def page(self):
        p=Task567Tests.page(self)
        # One explicitly labelled pre-attempt fixture. No later pose/velocity writes.
        p.evaluate('Object.assign(ninja,{x:1780,y:-360,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        return p

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S02-01'),movers:floors[0].level.movers,
            dragCount:floors[0].dragZones.length,range:grappleOverAcquisitionRadius(),scale:scale[version],
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),entry:{x:ninja.x,y:ninja.y},
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(len(g['elements']),13)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02'])
        self.assertEqual(g['sections'][1]['encounters'],['S02-01'])
        self.assertEqual(g['movers'],[]);self.assertEqual(g['dragCount'],0)
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertIsNone(g['finish']);self.assertLess(g['reach'],360)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['grapplable']);self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        es={e['id']:e for e in g['elements']}
        g['gap']=es['yard-fourth-landing']['x']-es['quarry-landing']['x']-es['quarry-landing']['width']
        g['rise']=es['yard-fourth-landing']['y']-es['quarry-landing']['y']
        g.update(localCatch='quarry-catch',connection='S01-04 exit is the S02-01 entry: same live collider',
            calibrationNote='TASK-564 green introduction, 360 minimum/540 opening recovery; 288 gap expands prior 252 and is validated by this production run; no v3 coordinates')
        self.assertEqual(g['gap'],288);self.assertAlmostEqual(g['rise'],60)
        self.assertEqual(es['quarry-catch']['width'],880)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up();self.step(p,41)
        r=self.result(p);land=self.landings(r,'quarry-landing');self.assertTrue(land)
        self.assertEqual(land[0]['tick'],71)
        self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        streak=0
        for s in r['rows'][30:70]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
        self.assertGreaterEqual(streak,6)
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),
            releaseTick=30,landingTick=71,landingAir=streak,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=1780,y=-360,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 13 purposeful green colliders; shared S01-04 entry; gap 288 rise 60; shelves 540 catch 880; reach {g["reach"]:.3f} < 360; no planned terrain')
        print(f'PASS route: isolated entry -> quarry-landing tick 71; release 30; airborne unattached {streak}; trusted inputs; zero mid-attempt injections')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up();self.step(p,144)
        before=self.result(p);catch=self.landings(before,'quarry-catch')
        self.assertTrue(catch);self.assertFalse(self.landings(before,'quarry-landing'))
        self.press(p,dict(x=1720,y=-330));self.step(p,12);p.mouse.up();self.step(p,240)
        r=self.result(p);returned=[s for s in self.landings(r,'yard-fourth-landing') if s['tick']>150]
        self.assertTrue(returned)
        r.update(earlyReleaseTick=6,catchTick=catch[0]['tick'],catchTarget='quarry-catch',
            recoveryPressTick=150,recoveryReleaseTick=162,returnTick=returned[0]['tick'],
            recoveryTarget='yard-fourth-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 6; quarry-catch {catch[0]["tick"]}; normal-control return {returned[0]["tick"]}; zero resets/injections')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold',successfulAlternative=bool(self.landings(r,'quarry-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'quarry-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='600 ticks per probe',
            inspection='All top-facing quarry-landing contacts inspected using the nominal success definition',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four trusted bounded hold/nearest probes; zero successful alternatives')

    def test_04_dependencies_and_index(self):
        p=self.page()
        rows=[]
        for preview in [True,False]:
            q=Task558Tests.page(self,preview)
            for mode in ['grapple_over','classic','bad']:
                row=q.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);return {mode:version,
                    range:version==='grapple_over'?grappleOverAcquisitionRadius():null,
                    upgraded:version==='grapple_over'?grappleOverProfile().upgradedAcquisitionRadius:null,
                    scale:scale[version],gravity:GRAVITY,pull:grappleSpeed}}''',mode)
                row['preview']=preview;rows.append(row)
                if mode=='grapple_over':
                    self.assertEqual(row['range'],360 if preview else 1080)
                    self.assertEqual(row['upgraded'],540 if preview else 1620)
                    self.assertEqual(row['scale'],.375)
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview built prefix -> fixedlevel.js colliders'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js'],
            superseded='Earlier exact S01-only inventories remain historical; no historical tests modified. TASK-572 S01 run archived in place; no base-to-summit claim.',
            hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, real exit, collected identifiers, git revision, browser/viewport and SHA256',
            'tests.log':'four Task573Tests, no skips, OK','geometry.json':'live collider purposes, widths, gap, reach and range',
            'route.json':'production entry-to-exit release and consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early miss catch and normal-control return',
            'approach.jpg':'broad shared entry and terraced quarry target','landing.jpg':'upper quarry landing and lower catch',
            'controls.json':'bounded hold and nearest probes with all successes inspected','dependencies.json':'changed subsystem and unchanged mode/range/physics contracts'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope=self.config['simulation'],hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')


class Task574Tests(unittest.TestCase):
    """S02-02 isolated shared-entry fixture; never a base-to-summit claim."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task574Tests')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S02-01 fixture, continuous left/right transfers through live quarry-landing; production physics and trusted mouse'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    capture = Task567Tests.capture
    target = dict(x=1462,y=-710)

    def page(self):
        p=Task567Tests.page(self)
        # One explicitly labelled pre-attempt fixture. No later pose/velocity writes.
        p.evaluate('Object.assign(ninja,{x:1780,y:-360,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        self.press(p,Task573Tests.target);self.step(p,30);p.mouse.up();self.step(p,41)
        self.assertEqual(self.landings(self.result(p),'quarry-landing')[0]['tick'],71)
        return p

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S02-02'),movers:floors[0].level.movers,
            dragCount:floors[0].dragZones.length,range:grappleOverAcquisitionRadius(),scale:scale[version],
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),entry:{x:ninja.x,y:ninja.y},
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(len(g['elements']),15)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02'])
        self.assertEqual(g['sections'][1]['encounters'],['S02-01','S02-02'])
        self.assertEqual(g['movers'],[]);self.assertEqual(g['dragCount'],0)
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertIsNone(g['finish']);self.assertLess(g['reach'],360)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['grapplable']);self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        es={e['id']:e for e in g['elements']}
        g['gap']=es['quarry-second-landing']['x']-es['quarry-landing']['x']-es['quarry-landing']['width']
        g['rise']=es['quarry-landing']['y']-es['quarry-second-landing']['y']
        g.update(localCatch='quarry-landing',connection='S02-01 exit is the S02-02 entry: same live collider',direction='leftward S02-01 then rightward S02-02',
            calibrationNote='TASK-564 green introduction, 360 minimum/540 opening recovery; 252 gap with 240 rise and is validated by this production run; no v3 coordinates')
        self.assertEqual(g['gap'],252);self.assertAlmostEqual(g['rise'],240)
        self.assertEqual(es['quarry-catch']['width'],880)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,54);p.mouse.up();self.step(p,196)
        r=self.result(p);land=self.landings(r,'quarry-second-landing');self.assertTrue(land)
        self.assertEqual(land[0]['tick'],321)
        self.assertTrue(any(s['attached'] for s in r['rows'][71:125]))
        streak=0
        for s in r['rows'][125:320]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
        self.assertGreaterEqual(streak,6)
        r.update(entryTick=71,takeoffTick=next(s['tick'] for s in r['rows'][71:] if s['vy']<0),
            releaseTick=125,landingTick=321,landingAir=streak,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=1780,y=-360,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 15 purposeful green colliders; shared S02-01 entry; gap 252 rise 240; shelves 540 catch 880; reach {g["reach"]:.3f} < 360; no planned terrain')
        print(f'PASS route: connected left/right terraces -> quarry-second-landing tick 321; release 125; airborne unattached {streak}; trusted inputs; zero mid-attempt injections')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,46);p.mouse.up();self.step(p,218)
        before=self.result(p)
        catch=[s for s in self.landings(before,'quarry-landing') if s['tick']>71]
        self.assertEqual(catch[0]['tick'],335)
        self.assertFalse(self.landings(before,'quarry-second-landing'))
        self.press(p,self.target);self.step(p,12);p.mouse.up();self.step(p,284)
        r=self.result(p);returned=self.landings(r,'quarry-second-landing')
        self.assertEqual(returned[0]['tick'],631)
        r.update(earlyReleaseTick=117,catchTick=335,catchTarget='quarry-landing',
            recoveryPressTick=335,recoveryReleaseTick=347,returnTick=631,
            recoveryTarget='quarry-second-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print('PASS miss: early release 117; quarry-landing catch 335; normal-control return to quarry-second-landing 631; zero resets/injections')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold',successfulAlternative=bool(self.landings(r,'quarry-second-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'quarry-second-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='600 ticks per probe',
            inspection='All top-facing quarry-second-landing contacts inspected using the nominal success definition',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four trusted bounded hold/nearest probes; zero successful alternatives')

    def test_04_dependencies_and_index(self):
        p=self.page()
        rows=[]
        for preview in [True,False]:
            q=Task558Tests.page(self,preview)
            for mode in ['grapple_over','classic','bad']:
                row=q.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);return {mode:version,
                    range:version==='grapple_over'?grappleOverAcquisitionRadius():null,
                    upgraded:version==='grapple_over'?grappleOverProfile().upgradedAcquisitionRadius:null,
                    scale:scale[version],gravity:GRAVITY,pull:grappleSpeed}}''',mode)
                row['preview']=preview;rows.append(row)
                if mode=='grapple_over':
                    self.assertEqual(row['range'],360 if preview else 1080)
                    self.assertEqual(row['upgraded'],540 if preview else 1620)
                    self.assertEqual(row['scale'],.375)
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview built prefix -> fixedlevel.js colliders'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js'],
            superseded='Earlier exact S01/S02-01 inventories remain historical; no historical tests modified. TASK-572 S01 run archived in place (119.924s, 3 tests OK; unchanged S01 geometry and physics); no base-to-summit claim.',
            hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, real exit, collected identifiers, git revision, browser/viewport and SHA256',
            'tests.log':'four Task574Tests, no skips, OK','geometry.json':'live collider purposes, widths, gap, reach and range',
            'route.json':'production entry-to-exit release and consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early miss catch and normal-control return',
            'approach.jpg':'broad shared entry and terraced quarry target','landing.jpg':'upper quarry landing and lower catch',
            'controls.json':'bounded hold and nearest probes with all successes inspected','dependencies.json':'changed subsystem and unchanged mode/range/physics contracts'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope=self.config['simulation'],hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')


class Task575Tests(unittest.TestCase):
    """S02-03 isolated shared-entry fixture; never a base-to-summit claim."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task575Tests')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S02-03 entry on live quarry-second-landing; production physics and trusted mouse; not continuous from base'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    def capture(self,p,name):
        p.evaluate('TUTORIAL_HINT.visible=false;draw()')
        observation=p.evaluate("""() => ({section:replacementSection().id,
            label:I18N.t(replacementSection().labelKey),drawn:LANDMARKS.frame.drawn,
            shape:replacementQuarryShape(GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height)})""")
        self.assertEqual(observation['section'],'S02')
        self.assertEqual(observation['label'],'Terraced Quarry')
        self.assertEqual([d['id'] for d in observation['drawn']],['terraced-quarry'])
        left,top,right,bottom=observation['drawn'][0]['rect']
        self.assertGreater(right,0);self.assertLess(left,1280)
        self.assertGreater(bottom,0);self.assertLess(top,720)
        self.assertEqual(len(observation['shape']['parts'][0]),12)
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        self.write(name+'.json',observation)
        print(f'PASS {name}: S02 / Terraced Quarry; visible terraced-quarry stepped-cut silhouette')
    target = dict(x=2384,y=-785)

    def page(self):
        p=Task567Tests.page(self)
        # One explicitly labelled pre-attempt fixture. No later pose/velocity writes.
        p.evaluate('Object.assign(ninja,{x:2124,y:-660,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        return p

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S02-03'),movers:floors[0].level.movers,
            dragCount:floors[0].dragZones.length,range:grappleOverAcquisitionRadius(),scale:scale[version],
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),entry:{x:ninja.x,y:ninja.y},
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(len(g['elements']),18)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02'])
        self.assertEqual(g['sections'][1]['encounters'],['S02-01','S02-02','S02-03'])
        self.assertEqual(g['movers'],[]);self.assertEqual(g['dragCount'],0)
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertIsNone(g['finish']);self.assertLess(g['reach'],360)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['grapplable']);self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        es={e['id']:e for e in g['elements']}
        g['gap']=es['quarry-third-landing']['x']-es['quarry-second-landing']['x']-es['quarry-second-landing']['width']
        g['rise']=es['quarry-second-landing']['y']-es['quarry-third-landing']['y']
        g.update(localCatch='quarry-third-catch',connection='S02-02 exit is S02-03 entry: same live collider',
            angleDegrees=__import__('math').degrees(__import__('math').atan2(28,160)),
            calibrationNote='TASK-564 green-only introduction; TASK-560 opening gap 252, shelves >=540; mild 9.93 degree face validated by production contact')
        self.assertEqual(g['gap'],252);self.assertEqual(g['rise'],0)
        self.assertEqual(es['quarry-third-catch']['width'],792)
        self.assertEqual(es['quarry-third-anchor']['points'],[dict(x=0,y=0),dict(x=160,y=28),dict(x=160,y=108),dict(x=0,y=80)])
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,36);p.mouse.up();self.step(p,34)
        r=self.result(p);land=self.landings(r,'quarry-third-landing');self.assertEqual(land[0]['tick'],70)
        rebound=[s for s in r['rows'] if any(c['id']=='quarry-third-anchor' and .1<abs(c['nx'])<.2 and c['ny']>.98 for c in s['contacts'])]
        self.assertEqual(rebound[0]['tick'],54)
        self.assertLess(r['rows'][52]['vy'],0);self.assertGreater(rebound[0]['vy'],0)
        streak=best=0
        for row in r['rows'][36:69]:
            streak=streak+1 if not row['contacts'] and not row['attached'] and not row['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6)
        self.assertTrue(any(s['attached'] for s in r['rows'][:36]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),
            releaseTick=36,reboundTick=54,landingTick=70,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=2124,y=-660,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 18 purposeful green colliders; shared S02-02 shelf; gap 252; landing 540 catch 792; reach {g["reach"]:.3f} <360; angle {g["angleDegrees"]:.3f}; planned absent')
        print(f'PASS route: release 36; angled rebound 54 reverses vertical velocity; landing 70; airborne unattached {best}; trusted inputs; zero mid-attempt injections')

    def test_02_late_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,72);p.mouse.up();self.step(p,179)
        before=self.result(p);catch=self.landings(before,'quarry-third-catch')
        self.assertEqual(catch[0]['tick'],251);self.assertFalse(self.landings(before,'quarry-third-landing'))
        self.press(p,dict(x=2194,y=-630));self.step(p,90);p.mouse.up();self.step(p,400)
        r=self.result(p);returned=self.landings(r,'quarry-second-landing');self.assertTrue(returned)
        r.update(lateReleaseTick=72,catchTick=251,catchTarget='quarry-third-catch',
            recoveryPressTick=251,recoveryReleaseTick=341,returnTick=returned[0]['tick'],
            recoveryTarget='quarry-second-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: late release 72; quarry-third-catch 251; normal-control return quarry-second-landing {returned[0]["tick"]}; zero resets/injections')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold',successfulAlternative=bool(self.landings(r,'quarry-third-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'quarry-third-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='600 ticks per probe',
            inspection='All top-facing quarry-third-landing contacts inspected using the nominal success definition',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four trusted bounded hold/nearest probes; zero successful alternatives')

    def test_04_dependencies_and_index(self):
        # Previous two transfers still reach the exact shared entry collider.
        p=Task574Tests.page(self)
        self.press(p,Task574Tests.target);self.step(p,54);p.mouse.up();self.step(p,196)
        self.assertEqual(self.landings(self.result(p),'quarry-second-landing')[0]['tick'],321)
        print('PASS connection: production S02-01/S02-02 route reaches shared quarry-second-landing at tick 321')
        rows=[]
        for preview in [True,False]:
            q=Task558Tests.page(self,preview)
            if preview:
                q.evaluate('draw()')
                self.assertEqual(q.evaluate('replacementSection().id'),'S01')
                self.assertEqual(q.evaluate('LANDMARKS.frame.drawn[0].id'),'loading-yard')
                print('PASS preview base: S01 loading-yard artwork preserved')
            for mode in ['grapple_over','classic','bad']:
                row=q.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);return {mode:version,
                    range:version==='grapple_over'?grappleOverAcquisitionRadius():null,
                    upgraded:version==='grapple_over'?grappleOverProfile().upgradedAcquisitionRadius:null,
                    scale:scale[version],gravity:GRAVITY,pull:grappleSpeed}}''',mode)
                row['preview']=preview;rows.append(row)
                if mode=='grapple_over':
                    self.assertEqual(row['range'],360 if preview else 1080)
                    self.assertEqual(row['upgraded'],540 if preview else 1620)
                    self.assertEqual(row['scale'],.375)
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['render/landmarks.js preview quarry silhouette and nearest built section', 'menu.js preview section label', 'tools/test_grapple_over_redesign.py capture assertions'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js'],
            superseded='Earlier exact S01/S02-01/S02-02 inventories remain historical; no historical tests modified. TASK-572 S01 run archived in place (119.924s, 3 tests OK; unchanged S01 geometry and physics); no base-to-summit claim.',
            hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, real exit, collected identifiers, git revision, browser/viewport and SHA256',
            'tests.log':'four Task575Tests, no skips, OK','geometry.json':'live collider purposes, widths, gap, reach and range',
            'route.json':'production entry-to-exit release and consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'late miss catch and normal-control return',
            'approach.jpg':'broad shared entry and terraced quarry target','landing.jpg':'upper quarry landing and lower catch',
            'approach.jpg.json':'S02 label and visible stepped-cut landmark bounds',
            'landing.jpg.json':'S02 label and visible stepped-cut landmark bounds',
            'controls.json':'bounded hold and nearest probes with all successes inspected','dependencies.json':'changed subsystem and unchanged mode/range/physics contracts',
            'evidence-index.json':'required artifact map and tested provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope=self.config['simulation'],hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: every required file exists; JSON parses; images decode; retained evidence below 200 MB')


class Task576Tests(unittest.TestCase):
    """S02-04 isolated shared-entry fixture; never a base-to-summit claim."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task576Tests')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S02-04 entry on live quarry-third-landing; separate continuous S02 fixture proof; production physics and trusted mouse; not continuous from base'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    def capture(self,p,name):
        p.evaluate('TUTORIAL_HINT.visible=false;draw()')
        observation=p.evaluate("""() => ({section:replacementSection().id,
            label:I18N.t(replacementSection().labelKey),drawn:LANDMARKS.frame.drawn,
            shape:replacementQuarryShape(GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height)})""")
        self.assertEqual(observation['section'],'S02')
        self.assertEqual(observation['label'],'Terraced Quarry')
        self.assertEqual([d['id'] for d in observation['drawn']],['terraced-quarry'])
        left,top,right,bottom=observation['drawn'][0]['rect']
        self.assertGreater(right,0);self.assertLess(left,1280)
        self.assertGreater(bottom,0);self.assertLess(top,720)
        self.assertEqual(len(observation['shape']['parts'][0]),12)
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        self.write(name+'.json',observation)
        print(f'PASS {name}: S02 / Terraced Quarry; visible terraced-quarry stepped-cut silhouette')
    target = dict(x=2776,y=-965)

    def page(self):
        p=Task567Tests.page(self)
        # One explicitly labelled pre-attempt fixture. No later pose/velocity writes.
        p.evaluate('Object.assign(ninja,{x:2830,y:-660,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        return p

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S02-04'),movers:floors[0].level.movers,
            dragCount:floors[0].dragZones.length,range:grappleOverAcquisitionRadius(),scale:scale[version],
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),entry:{x:ninja.x,y:ninja.y},
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(len(g['elements']),20)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02'])
        self.assertEqual(g['sections'][1]['encounters'],['S02-01','S02-02','S02-03','S02-04'])
        self.assertEqual(g['movers'],[]);self.assertEqual(g['dragCount'],0)
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertIsNone(g['finish']);self.assertLess(g['reach'],360)
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['grapplable']);self.assertTrue(e['purpose'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        es={e['id']:e for e in g['elements']}
        g['gap']=es['quarry-fourth-anchor']['x']-(es['quarry-fourth-landing']['x']+es['quarry-fourth-landing']['width'])
        g['rise']=es['quarry-third-landing']['y']-es['quarry-fourth-landing']['y']
        g.update(localCatch='quarry-third-landing',connection='S02-03 exit is S02-04 entry: same live collider',
            direction='rightward third transfer then leftward upper return',
            calibrationNote='TASK-564 green-only opening; broad >=540 shelves; angled face from TASK-575; signed horizontal overlap recorded, not a claimed gap',
            angleDegrees=__import__('math').degrees(__import__('math').atan2(28,160)))
        self.assertAlmostEqual(g['rise'],240)
        self.assertEqual(es['quarry-fourth-landing']['width'],580)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,28);p.mouse.up()
        self.until_landing(p,'quarry-fourth-landing',300)
        r=self.result(p);land=self.landings(r,'quarry-fourth-landing');self.assertTrue(land)
        rebound=[s for s in r['rows'] if any(c['id']=='quarry-fourth-anchor' and -.2<c['nx']<-.1 and c['ny']>.98 for c in s['contacts'])]
        self.assertTrue(rebound);rb=rebound[0]
        self.assertLess(r['rows'][rb['tick']-2]['vy'],0);self.assertGreater(rb['vy'],0)
        best=streak=0
        for row in r['rows'][28:land[0]['tick']-1]:
            streak=streak+1 if not row['contacts'] and not row['attached'] and not row['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6)
        self.assertLess(land[0]['x'],2830)
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),
            releaseTick=28,reboundTick=rb['tick'],landingTick=land[0]['tick'],landingAir=best,
            entryToExit=True,resets=0,poseInjections=0,fixture=dict(x=2830,y=-660,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 20 green purposeful colliders; upper shelf 580; rise 240; reach {g["reach"]:.3f} <360; planned absent')
        print(f'PASS route: release 28; angled rebound {rb["tick"]}; leftward landing {land[0]["tick"]}; unattached airborne {best}; zero injections')
        tolerance=[]
        for hold in [27,29,30]:
            q=self.page();self.press(q,self.target);self.step(q,hold);q.mouse.up();self.until_landing(q,'quarry-fourth-landing',300)
            rr=self.result(q);ll=self.landings(rr,'quarry-fourth-landing');self.assertTrue(ll,hold)
            tolerance.append(dict(hold=hold,landingTick=ll[0]['tick'],rows=rr['rows'],inputs=rr['inputs']))
        self.write('tolerance.json',tolerance)
        print('PASS tolerance: release holds 27/28/29/30 all reach upper terrace')

    def until_landing(self,p,id,bound):
        p.evaluate("""a=>{for(let n=0;n<a.bound;n++){YARD.step(1);if(YARD.result().rows.at(-1).contacts.some(c=>c.id===a.id&&c.ny<-.9))break}}""",dict(id=id,bound=bound))

    def test_02_late_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,60);p.mouse.up()
        self.until_landing(p,'quarry-third-landing',500)
        before=self.result(p);catch=self.landings(before,'quarry-third-landing');self.assertTrue(catch)
        self.assertFalse(self.landings(before,'quarry-fourth-landing'))
        press=before['tick'];self.press(p,dict(x=2600,y=-630));self.step(p,30);p.mouse.up()
        self.until_landing(p,'quarry-third-landing',500)
        r=self.result(p);returned=[s for s in self.landings(r,'quarry-third-landing') if s['tick']>press+30];self.assertTrue(returned)
        r.update(lateReleaseTick=60,catchTick=catch[0]['tick'],catchTarget='quarry-third-landing',
            recoveryPressTick=press,recoveryReleaseTick=press+30,returnTick=returned[0]['tick'],
            recoveryTarget='quarry-third-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: late release 60; third terrace catch {catch[0]["tick"]}; normal-control return {returned[0]["tick"]}; zero resets')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold',successfulAlternative=bool(self.landings(r,'quarry-fourth-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'quarry-fourth-landing')))
            cases.append(r)
        for r in cases[1:]:self.assertFalse(r['successfulAlternative'],r['probe'])
        successes=[]
        for r in cases:
            lands=self.landings(r,'quarry-fourth-landing')
            if lands:successes.append(dict(probe=r['probe'],firstLanding=lands[0],
                interpretation='Real successful alternative under the same top-contact definition; long attached swing, not repeated tiny nearest transfers'))
        self.write('controls.json',dict(cases=cases,successfulAlternatives=successes,bound='600 ticks each',
            inspection='Every upper-shelf top contact retained; continuous hold is an openly reported alternative; all three repeated nearest probes fail',scope=self.config['simulation']))
        print(f'PASS controls: 4 bounded probes; 3 nearest probes fail; {len(successes)} successful alternatives explicitly inspected')

    def test_04_continuous_section_and_summit_gate(self):
        p=Task574Tests.page(self)
        self.press(p,Task574Tests.target);self.step(p,54);p.mouse.up();self.step(p,196)
        self.press(p,dict(x=2180,y=-630));self.step(p,30);p.mouse.up()
        self.press(p,Task575Tests.target);self.step(p,18);p.mouse.up();self.step(p,37)
        self.assertEqual(self.landings(self.result(p),'quarry-third-landing')[0]['tick'],406)
        self.press(p,dict(x=2600,y=-630));self.step(p,50);p.mouse.up();self.step(p,1)
        reach=p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)',self.target)
        self.assertLess(reach,360)
        self.press(p,self.target);self.step(p,18);p.mouse.up()
        self.until_landing(p,'quarry-fourth-landing',200)
        r=self.result(p);exits=[]
        for i,id in enumerate(['quarry-landing','quarry-second-landing','quarry-third-landing','quarry-fourth-landing'],1):
            land=self.landings(r,id);self.assertTrue(land,id)
            exits.append(dict(encounter=f'S02-0{i}',collider=id,tick=land[0]['tick'],x=land[0]['x'],y=land[0]['y']))
        self.assertEqual([e['tick'] for e in exits],[71,321,406,540])
        self.assertTrue(any(any(c['id']=='quarry-fourth-anchor' and c['ny']>.98 for c in row['contacts']) for row in r['rows']))
        self.assertFalse(p.evaluate('floors[0].climbStats.completed'))
        r.update(exits=exits,resets=0,poseInjections=0,fixture=dict(x=1780,y=-360,vx=0,vy=0),
            scope='Single isolated S02 entry fixture; all four exits continuously, no handoff resets; not base-to-summit',
            fourthTargetReach=reach,sectionCompletionEvents=0)
        self.write('section-route.json',r)
        q=Task567Tests.page(self)
        gate=q.evaluate('''() => {
            const m=JSON.parse(JSON.stringify(GRAPPLE_OVER_REPLACEMENT));
            m.sections=m.sections.filter(s=>s.status==='built');
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const s02=replacementMountainLevel(m).finish;
            m.sections.push({id:'S08',status:'built',encounters:[]});
            const s08=replacementMountainLevel(m).finish;
            floors[0].level.finish=s08;
            let events=0;const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events++;return original.call(this,name,...args)};
            YARD.step(3);CLIMB_UI.complete();
            return {s02,s08,events,completed:floors[0].climbStats.completed};
        }''')
        self.assertIsNone(gate['s02']);self.assertTrue(gate['s08']);self.assertEqual(gate['events'],1);self.assertTrue(gate['completed'])
        gate['scope']='Separate isolated S08 finish contract fixture at base; not authored S08 gameplay'
        self.write('summit-gate.json',gate)
        print('PASS section: S02-01 71 -> S02-02 321 -> S02-03 406 -> S02-04 540; one labeled entry fixture; no handoff resets; no section completion')
        print('PASS summit: S02 finish null; separate S08 fixture emits level_completed exactly once')

    def test_05_dependencies_and_index(self):
        # Previous two transfers still reach the exact shared entry collider.
        p=Task574Tests.page(self)
        self.press(p,Task574Tests.target);self.step(p,54);p.mouse.up();self.step(p,196)
        self.assertEqual(self.landings(self.result(p),'quarry-second-landing')[0]['tick'],321)
        print('PASS connection: production S02-01/S02-02 route reaches shared quarry-second-landing at tick 321')
        rows=[]
        for preview in [True,False]:
            q=Task558Tests.page(self,preview)
            if preview:
                q.evaluate('draw()')
                self.assertEqual(q.evaluate('replacementSection().id'),'S01')
                self.assertEqual(q.evaluate('LANDMARKS.frame.drawn[0].id'),'loading-yard')
                print('PASS preview base: S01 loading-yard artwork preserved')
            for mode in ['grapple_over','classic','bad']:
                row=q.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);return {mode:version,
                    range:version==='grapple_over'?grappleOverAcquisitionRadius():null,
                    upgraded:version==='grapple_over'?grappleOverProfile().upgradedAcquisitionRadius:null,
                    scale:scale[version],gravity:GRAVITY,pull:grappleSpeed}}''',mode)
                row['preview']=preview;rows.append(row)
                if mode=='grapple_over':
                    self.assertEqual(row['range'],360 if preview else 1080)
                    self.assertEqual(row['upgraded'],540 if preview else 1620)
                    self.assertEqual(row['scale'],.375)
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js S02-04 preview colliders -> fixedlevel.js', 'tools/test_grapple_over_redesign.py Task576Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js'],
            superseded='Earlier exact S01/S02-01/S02-02 inventories remain historical; no historical tests modified. TASK-572 S01 run archived in place (119.924s, 3 tests OK; unchanged S01 geometry and physics); no base-to-summit claim.',
            hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, real exit, collected identifiers, git revision, browser/viewport and SHA256',
            'tests.log':'five Task576Tests, no skips, OK','geometry.json':'live collider purposes, widths, gap, reach and range',
            'route.json':'production entry-to-exit release and consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'late miss catch and normal-control return',
            'approach.jpg':'broad shared entry and terraced quarry target','landing.jpg':'upper quarry landing and lower catch',
            'approach.jpg.json':'S02 label and visible stepped-cut landmark bounds',
            'landing.jpg.json':'S02 label and visible stepped-cut landmark bounds',
            'controls.json':'bounded hold and nearest probes with all successes inspected','dependencies.json':'changed subsystem and unchanged mode/range/physics contracts',
            'section-route.json':'all four exits in order without handoff resets', 'summit-gate.json':'isolated S08-only exactly once completion contract', 'tolerance.json':'neighboring release timings succeed', 'evidence-index.json':'required artifact map and tested provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope=self.config['simulation'],hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: every required file exists; JSON parses; images decode; retained evidence below 200 MB')


class Task577Tests(unittest.TestCase):
    """S02 local tolerance/recovery using production physics and genuine browser inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for Task577Tests')
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390},device_scale_factor=1,
            simulation='Isolated S02 entry fixtures with completed first-run hint; not continuous gameplay')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK577_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    frame = Task571Tests.frame
    until_landing = Task576Tests.until_landing
    targets = [Task573Tests.target,dict(x=1400,y=-740),Task575Tests.target,dict(x=3176,y=-785)]
    holds = [36,57,36,39]
    exits = ['quarry-landing','quarry-second-landing','quarry-third-landing','quarry-fourth-landing']
    fixtures = [dict(x=1780,y=-360),dict(x=1780,y=-360),dict(x=2124,y=-660),dict(x=2916,y=-660)]

    def setup_entry(self,p,index):
        # S02 is after the first-run hint. Use its production fade API in this UI fixture;
        # direct physics stepping intentionally bypasses the game-loop UI clock.
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.assertFalse(p.evaluate('TUTORIAL_HINT.visible'))
        p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});screen.trackGrappleOver(true)}',self.fixtures[index])
        if index==1:
            self.press(p,self.targets[0]);self.step(p,30);self.release(p);self.step(p,41)
            self.assertTrue(self.landings(self.result(p),self.exits[0]))
    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-50,0),('late',50,0),('left',0,-8),('right',0,8)]:
                    p=self.page(touch);self.setup_entry(p,index)

                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    nominal_hold=36 if index==3 and not touch else self.holds[index]
                    hold=nominal_hold+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S02-0{index+1} touch approach'))
                    xy=self.press(p,self.targets[index],aim);self.step(p,hold);self.release(p)
                    self.until_landing(p,self.exits[index],800 if index==1 else 400)
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S02-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,nominalHoldTicks=nominal_hold,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=r['rows'][start:],success=bool(lands))
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S02-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=self.fixtures,fixtureScope='Isolated S02 entry fixtures; second approached from first; fourth starts at x2916 on the same broad third terrace; not continuous gameplay',source_hashes=self.config['source_hashes']))
                    p.context.close()
        strip=Image.new('RGB',(844*2,390*4))
        for n,im in enumerate(frames):strip.paste(im,((n%2)*844,(n//2)*390))
        strip.save(self.out/'touch-strip.jpg',quality=85)
        self.assertEqual(len(rows),40)
        self.assertTrue(all(r['success'] for r in rows),[(r['encounter'],r['mode'],r['variant']) for r in rows if not r['success']])
        for r in rows:
            expected='touchstart' if r['mode']=='touch' else 'mousedown'
            self.assertEqual(r['inputs'][0]['type'],expected)
            self.assertTrue(all(i['trusted'] for i in r['inputs']))
            self.assertTrue(any(c['id']==r['exit'] and c['ny']<-.9 for c in r['landing']['contacts']))
            self.assertTrue(any(s['attached'] for s in r['trace']))
            self.assertTrue(any(not s['attached'] and not s['contacts'] for s in r['trace'] if s['tick']>r['releaseTick']))
        print('PASS tolerance: all 40 cases; 4 encounters x 2 genuine input modes x 5 variants; +/-50 ms and +/-8 CSS px')


    def test_02_recovery(self):
        rows=[]
        for touch in [False,True]:
            for index,(hold,wait,catch_id,target,duration,coast,return_id) in enumerate([
                (6,144,'quarry-catch',dict(x=1720,y=-330),12,240,'yard-fourth-landing'),
                (46,None,'quarry-landing',self.targets[1],54,500,'quarry-second-landing'),
                (6,None,'quarry-third-catch',dict(x=2194,y=-630),12,400,'quarry-second-landing'),
                (6,None,'quarry-third-landing',dict(x=2600,y=-630),30,None,'quarry-third-landing')]):
                p=self.page(touch);self.setup_entry(p,index);start=p.evaluate('YARD.result().tick')
                self.press(p,self.targets[index]);self.step(p,hold);self.release(p)
                if wait is None:self.until_landing(p,catch_id,500)
                else:self.step(p,wait)
                before=self.result(p)
                catches=[s for s in self.landings(before,catch_id) if s['tick']>start+hold]
                self.assertTrue(catches)
                self.assertFalse([s for s in self.landings(before,self.exits[index]) if s['tick']>start])
                recovery_start=before['tick']
                self.press(p,target);self.step(p,duration);self.release(p)
                if coast is None:self.until_landing(p,return_id,500)
                else:self.step(p,coast)
                r=self.result(p)
                returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                self.assertTrue(returned)
                environment=p.evaluate('({movers:floors[0].level.movers,roles:floors[0].level.elements.map(e=>e.role),dragCount:floors[0].dragZones.length})')
                self.assertEqual(environment['movers'],[]);self.assertEqual(set(environment['roles']),{'bounce'})
                self.assertEqual(environment['dragCount'],0)
                rows.append(dict(encounter=f'S02-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-(36 if index==3 and not touch else self.holds[index]))*p.evaluate('physicsStepMs'),
                    startTick=start,catch=catches[0],returned=returned[0],returnCollider=return_id,
                    recoveryStart=recovery_start,inputs=r['inputs'],trace=r['rows'][start:],environment=environment,
                    fixtureInitializations=1,resetsAfterStart=0,poseInjectionsAfterStart=0))
                self.write('recovery.json',dict(cases=rows,source_hashes=self.config['source_hashes'],
                    scope='Isolated entries; normal input after initialization; no movers/hazards/yellow in built S02'))
                p.context.close()
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses, lower catches and normal-input escapes; zero resets/injections; no movers/hazards/yellow present')

    def test_03_evidence_index(self):
        p=self.page()
        geometry=p.evaluate('({elements:floors[0].level.elements,range:grappleOverAcquisitionRadius(),scale:scale[version]})')
        self.assertEqual(geometry['range'],360);self.assertEqual(geometry['scale'],.375)
        es={e['id']:e for e in geometry['elements']}
        self.assertEqual(es['quarry-second-anchor']['x'],1332)
        self.assertEqual(max(v['x'] for v in es['quarry-second-anchor']['points']),280)
        self.assertEqual(es['quarry-fourth-landing']['y'],-708.2)
        self.assertAlmostEqual(es['quarry-third-landing']['y']-es['quarry-fourth-landing']['y'],60)
        self.assertTrue(all(max(v['x'] for v in e['points'])>=540 for e in geometry['elements'] if 'anchor' not in e['id']))
        self.write('affected-proof-map.json',dict(geometryChanges=[dict(id='quarry-landing',old=dict(width=540),new=dict(width=620),reason='Broad landing accepts touch aim spread; 208-unit gap retained'),dict(id='quarry-second-anchor',old=dict(x=1452,width=160),new=dict(x=1332,width=280),reason='Expose a forgiving launch face across +/-8 CSS px'),dict(id='quarry-second-landing',old=dict(x=1664,width=540),new=dict(x=1624,width=580),reason='Broad upper shelf catches the slower touch aim route after its anchor rebound'),dict(id='quarry-third-landing',old=dict(x=2456,width=540),new=dict(x=2416,width=580),reason='212-unit gap and broad landing prevent grazing the corner under touch spread'),dict(id='quarry-fourth-anchor',old=dict(x=2696,y=-1019),new=dict(x=3096,y=-839),reason='Rightward angled transfer avoids interference with earlier encounters'),dict(id='quarry-fourth-landing',old=dict(x=2160,y=-888.2,width=580),new=dict(x=3204,y=-708.2,width=620),reason='60-unit upward transfer retains deliberate jump and broad exit')],runtimeChanges=['mountain.js replacement preview only'],observedGeometry=geometry,
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg'],
            previousProof=[f'artifacts/TASK-{n}/route.json' for n in range(573,577)],
            superseded='TASK-573 first-landing and TASK-574 second-anchor geometry/routes/controls and TASK-576 upper-exit geometry/routes/controls/composition are historical; current local routes and recovery refreshed here. TASK-575 third-landing geometry/routes/controls are historical, with current local routes and recovery refreshed. No continuous-section claim.',
            entryChange='S02-04 isolated fixture starts x2916 on existing third terrace; no pose changes after attempt starts',
            dependencies=['Task577Tests -> browser_test_support + grapple_over_yard.js -> events.js, physics.js, fixedlevel.js, mountain.js'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit; geometry changes invalidate only affected local proof'))
        required={'commands.log':'exact command, real exit, collected IDs, browser/viewports/DPR, revision and hashes',
            'tests.log':'three exact Task577Tests methods, no skips, OK',
            'tolerance.json':'40 successful variants with trusted input timestamps and top-facing exit contacts',
            'recovery.json':'8 out-of-window misses, lower contacts and normal-input escapes',
            'affected-proof-map.json':'six local geometry changes, historical coverage superseded, subsystem dependencies',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,scope='Isolated S02 fixtures, not continuous gameplay'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')

class Task578Tests(unittest.TestCase):
    """Built S02 composition; one entry fixture followed by uninterrupted production traversal."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='One isolated S02 entry fixture; continuous thereafter; not from base'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK578_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)

    def test_01_objects_and_dependencies(self):
        p=self.page()
        g=p.evaluate("""() => ({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,dragCount:floors[0].dragZones.length,
            range:grappleOverAcquisitionRadius(),upgrade:grappleOverProfile().upgradedAcquisitionRadius,
            scale:scale[version],calibration:GRAPPLE_OVER_MOVEMENT})""")
        self.assertEqual(len(g['elements']),20)
        self.assertEqual(g['movers'],[]);self.assertEqual(g['dragCount'],0)
        self.assertEqual((g['range'],g['upgrade'],g['scale']),(360,540,.375))
        for e in g['elements']:
            self.assertEqual(e['role'],'bounce');self.assertTrue(e['purpose']);self.assertTrue(e['grapplable'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['width']=max(v['x'] for v in e['points'])
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],540)
        self.assertEqual([c['id'] for c in g['encounters'] if c['id'].startswith('S02')],
                         ['S02-01','S02-02','S02-03','S02-04'])
        es={e['id']:e for e in g['elements']}
        g['deliberateGaps']=[es[b]['x']-es[a]['x']-es[a]['width'] for a,b in
            [('quarry-landing','yard-fourth-landing'),('quarry-landing','quarry-second-landing'),
             ('quarry-second-landing','quarry-third-landing'),('quarry-third-landing','quarry-fourth-landing')]]
        self.assertEqual(g['deliberateGaps'],[208,132,212,208])
        g.update(firstUseOrder=['green'],yellow='absent: suppression/clearance not applicable',
            blue='absent: swept bounds/period/acquisition window not applicable',hazards='absent: contact recovery not applicable',
            removedClutter='none: all built colliders have route or recovery purposes; no future geometry emitted')
        self.write('objects.json',g)
        old=json.loads((ROOT/'artifacts/TASK-577/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        reused=[]
        for name in ['tests.log','tolerance.json','recovery.json','verifier-audit.log']:
            path='artifacts/TASK-577/'+name
            reused.append(dict(path=path,sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()))
        tolerance=json.loads((ROOT/'artifacts/TASK-577/tolerance.json').read_text())['cases']
        self.assertEqual(len(tolerance),40);self.assertTrue(all(c['success'] for c in tolerance))
        recovery=json.loads((ROOT/'artifacts/TASK-577/recovery.json').read_text())['cases']
        self.assertEqual(len(recovery),8)
        for c in recovery:
            self.assertTrue(c['catch']['contacts']);self.assertTrue(c['returned']['contacts'])
            self.assertEqual(c['poseInjectionsAfterStart'],0)
        self.write('dependency.json',dict(unchanged=unchanged,reused=reused,
            changed=['tools/test_grapple_over_redesign.py: additive Task578Tests only'],
            dependencies='mountain -> fixedlevel -> physics/events -> yard observer; render/landmarks -> draw; unchanged input/range/rope/modes',
            refreshed='Current S02 continuous route and composition. TASK-576 continuous geometry superseded by TASK-577; historical tests preserved.',
            hashPolicy='HEAD-only changes do not invalidate identical tested source hashes'))
        print('PASS objects: 20 purposeful green colliders; 4 ordered S02 encounters; shelves >=540; gaps 208/132/212/208; movers=0 drag=0 hazards=0')
        print('PASS dependencies: 49 unchanged source hashes; archived 40 tolerance and 8 recovery cases inspected')

    def test_02_continuous_route_and_captures(self):
        p=self.page()
        p.evaluate("""() => {TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500);
            Object.assign(ninja,{x:1780,y:-360,speedX:0,speedY:0});screen.trackGrappleOver(true);
            window.frames578=[];window.capture578=()=>{draw();frames578.push({image:canvas.toDataURL('image/jpeg',.85),tick:YARD.result().tick});};capture578()}""")
        approaches=[];observations=[]
        def capture(label,target):
            p.evaluate('draw()')
            observation=p.evaluate("""t=>({tick:YARD.result().tick,target:t,client:YARD.client(t),
                section:replacementSection().id,label:I18N.t(replacementSection().labelKey),landmark:LANDMARKS.frame.drawn})""",target)
            self.assertEqual(observation['section'],'S02')
            self.assertEqual(observation['landmark'][0]['id'],'terraced-quarry')
            self.assertTrue(0<observation['client']['x']<1280 and 0<observation['client']['y']<720)
            observations.append(observation)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),label,fill='white');approaches.append(im)
        def step(n):
            p.evaluate('n=>{for(let i=0;i<n;i++){YARD.step(1);if(YARD.result().tick%3===0)capture578()}}',n)
        def until(id,bound):
            p.evaluate("""a=>{for(let i=0;i<a.bound;i++){YARD.step(1);if(YARD.result().tick%3===0)capture578();
                if(YARD.result().rows.at(-1).contacts.some(c=>c.id===a.id&&c.ny<-.9))break}}""",dict(id=id,bound=bound))
            self.assertTrue(self.landings(self.result(p),id),id)
        targets=Task577Tests.targets
        capture('S02-01 shared entry / leftward first terrace',targets[0])
        # Composition-only camera; actual route uses the unchanged .375 camera.
        p.evaluate('window.cam578={x:screen.x,y:screen.y};screen.x=width/.375/2-2300;screen.y=height/.375/2+450;draw()')
        p.screenshot(path=str(self.out/'overview.png'))
        flat=p.evaluate("""() => ({elements:floors[0].elements.map(e=>({id:e.id,points:e.getPoints()})),
            shape:replacementQuarryShape(GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
            landmark:{x:(2366+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,
                      y:(-610+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
            camera:{x:screen.x,y:screen.y},factor:1280/width})""")
        im=Image.new('RGB',(1280,720),'white');pen=ImageDraw.Draw(im);f=flat['factor']
        for part in flat['shape']['parts']:
            pen.polygon([((x+flat['landmark']['x'])*f,(y+flat['landmark']['y'])*f) for x,y in part],fill='#777777')
        for e in flat['elements']:
            points=[((v['x']+flat['camera']['x'])*.375*f,(v['y']+flat['camera']['y'])*.375*f) for v in e['points']]
            pen.polygon(points,fill='black')
            if e['id'].startswith('quarry'):pen.text(points[0],e['id'],fill='#aa0000')
        pen.text((12,16),'Terraced Quarry / stepped-cut landmark (gray), live colliders (black)',fill='black')
        im.save(self.out/'silhouette.png')
        p.evaluate('screen.x=cam578.x;screen.y=cam578.y;draw()')
        self.press(p,targets[0]);step(30);self.release(p);step(41)
        capture('S02-02 first terrace / upper return',targets[1])
        self.press(p,targets[1]);step(57);self.release(p);until(Task577Tests.exits[1],800)
        self.press(p,dict(x=2180,y=-630));step(75);self.release(p)
        capture('S02-03 broad second terrace / angled cut',targets[2])
        self.press(p,targets[2]);step(36);self.release(p);until(Task577Tests.exits[2],400)
        capture('S02-04 third terrace / rightward upper exit',targets[3])
        self.press(p,targets[3]);step(90);self.release(p);until(Task577Tests.exits[3],400)
        p.evaluate('capture578()')
        r=self.result(p);exits=[]
        for i,id in enumerate(Task577Tests.exits):
            landed=self.landings(r,id);self.assertTrue(landed,id)
            exits.append(dict(encounter=f'S02-0{i+1}',collider=id,tick=landed[0]['tick']))
        self.assertEqual(sorted(e['tick'] for e in exits),[e['tick'] for e in exits])
        r.update(exits=exits,scope='Single isolated S02 entry fixture; uninterrupted production inputs thereafter; not from base',
                 fixture=dict(x=1780,y=-360,vx=0,vy=0),resets=0,poseInjections=0,approaches=observations)
        self.write('route.json',r)
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(approaches):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=88)
        # Render-only replay of sampled continuous simulation; no fixture is presented as gameplay.
        clip=p.evaluate('''async () => {
            const stream=canvas.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp9',videoBitsPerSecond:1800000});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of frames578){const image=new Image();image.src=f.image;await image.decode();
                ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(image,0,0);ctx.restore();
                ctx.fillStyle='white';ctx.font='14px sans-serif';ctx.fillText('Continuous S02 production trace replay / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));
            rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});
            return await new Promise(r=>{const reader=new FileReader();reader.onload=()=>r(reader.result.split(',')[1]);reader.readAsDataURL(blob)});
        }''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        # Decode the full retained clip in the browser, not just its container header.
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;
            v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);
            await v.play();await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});
            return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],100);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)
        print(f'PASS continuous route: four ordered exits {exits}; trusted inputs; zero resets/injections after entry fixture; clip decoded {decoded}')

    def test_03_evidence_index(self):
        required={'commands.log':'exact command, exit status, collected identifiers, revision, hashes and browser configuration',
            'tests.log':'3 exact Task578Tests cases, no skips, OK','overview.png':'all four quarry encounters and Terraced Quarry landmark',
            'silhouette.png':'plain monochrome structure and open gaps','approaches.jpg':'four actual continuous approach views',
            'objects.json':'all twenty built collider purposes, green-only role order and absent conditional obstacles',
            'section.webm':'continuous representative production traversal replay',
            'route.json':'trusted inputs and four ordered landing contacts; no resets or injections',
            'clip-decode.json':'full clip browser decode and frame count',
            'dependency.json':'exact unchanged dependencies and referenced prior proof',
            'review.md':'independent visual observations and pacing assessment',
            'evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreater(im.width,1000)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: JSON parses; three images decode; clip fully decoded; retained evidence <200 MB; visual review follows')




class Task579Tests(unittest.TestCase):
    """Freight introduction from a labelled isolated fixture on the live S02 exit."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S02-04 exit fixture -> S03-01 only; production physics and trusted inputs; not a base-to-summit run'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=3910,y=-900)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:3740,y:-720,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.freightCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);freightCycle.push({tick:i+1,x:floors[0].byId.get('freight-carrier').x,
                px:ninja.x,py:ninja.y});}}''')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'freight-crossing')
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_cycle_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S03-01'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:freightCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02','S03'])
        self.assertEqual(g['sections'][-1]['encounters'],['S03-01'])
        self.assertEqual(len(g['elements']),23);self.assertEqual(len(g['movers']),1)
        self.assertEqual(g['dragCount'],0);self.assertIsNone(g['finish'])
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],360)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertTrue(e['grapplable'])
            self.assertEqual(e['role'],'solid' if e['id']=='freight-carrier' else 'bounce')
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],360 if e['id']=='freight-carrier' else 540)
        es={e['id']:e for e in g['elements']}
        g.update(gap=es['freight-landing']['x']-es['quarry-fourth-landing']['x']-es['quarry-fourth-landing']['width'],
            connection='S02-04 exit is S03-01 entry: same live quarry-fourth-landing collider',
            localCatch='freight-catch',calibrationNote='TASK-564/561 horizontal 720 travel, 10000ms cycle; widened blue face 360; green shelves 620 and recovery 1476; placement validated here')
        self.assertEqual(g['gap'],676)
        self.assertAlmostEqual(max(v['x'] for v in g['cycle'])-min(v['x'] for v in g['cycle']),720)
        self.assertEqual(g['cycle'][-1]['x'],3900)
        self.assertTrue(all(v['px']==3740 and -740<v['py']<-708 for v in g['cycle']))
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'freight-landing');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'freight-catch'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=3740,y=-720,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 23 purposeful colliders; first blue S03-01 only; carrier width 360 travel 720 cycle 600 ticks; entry/exit 620 catch 1476 gap 676 reach {g["reach"]:.3f} < 360; planned absent')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'freight-catch');self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'freight-landing'))
        self.press(p,dict(x=3814,y=-688));self.step(p,12);p.mouse.up()
        returned=self.until(p,'quarry-fourth-landing');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=606,catchTick=catch,catchTarget='freight-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+12,returnTick=returned,
            recoveryTarget='quarry-fourth-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 606 catch {catch}; normal-control return quarry-fourth-landing {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'freight-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'freight-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; two-cycle continuous hold and nearest 6/12/24; zero successful alternatives')

    def test_04_dependencies_and_index(self):
        rows=[]
        for preview in [True,False]:
            q=Task558Tests.page(self,preview)
            for mode in ['grapple_over','classic','bad']:
                row=q.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);return {mode:version,
                    range:version==='grapple_over'?grappleOverAcquisitionRadius():null,
                    upgraded:version==='grapple_over'?grappleOverProfile().upgradedAcquisitionRadius:null,
                    scale:scale[version],gravity:GRAVITY,pull:grappleSpeed}}''',mode)
                row['preview']=preview;rows.append(row)
                if mode=='grapple_over':
                    self.assertEqual(row['range'],360 if preview else 1080)
                    self.assertEqual(row['upgraded'],540 if preview else 1620);self.assertEqual(row['scale'],.375)
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview prefix -> fixedlevel.js production mover/collision',
            'render/landmarks.js preview freight mast','i18n.js freight labels','tools/test_grapple_over_redesign.py additive Task579Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical; Task578 continuous S02 proof remains at artifacts/TASK-578. No old v3 tests edited or rerun.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact invocation, actual exit, exact collected identifiers, revision, browser/viewport and source SHA256',
            'tests.log':'four Task579Tests; no skips; OK','geometry.json':'live collider purposes, widths, gap, target reach and 600-tick full cycle',
            'route.json':'production entry-to-exit release, landing and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early release into catch and normal-control return',
            'approach.jpg':'broad quarry entry, blue carrier, green catch and freight signal mast',
            'landing.jpg':'safe broad green exit and Freight Crossing structure','controls.json':'bounded hold/nearest probes with every success inspected',
            'dependencies.json':'changed subsystems, unchanged modes/range/physics and source hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')


class Task580Tests(unittest.TestCase):
    """Freight introduction from a labelled isolated fixture on the live S03-01 exit."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S03-01 exit fixture -> S03-02 only; production physics and trusted inputs; not a base-to-summit run'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=5206,y=-900)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:5036,y:-720,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.freightCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);freightCycle.push({tick:i+1,x:floors[0].byId.get('freight-second-carrier').x,
                px:ninja.x,py:ninja.y});}}''')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'freight-crossing')
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_cycle_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S03-02'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:freightCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02','S03'])
        self.assertEqual(g['sections'][-1]['encounters'],['S03-01','S03-02'])
        self.assertEqual(len(g['elements']),26);self.assertEqual(len(g['movers']),2)
        self.assertEqual(g['dragCount'],0);self.assertIsNone(g['finish'])
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],360)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertTrue(e['grapplable'])
            self.assertEqual(e['role'],'solid' if e['id'] in ['freight-carrier','freight-second-carrier'] else 'bounce')
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],360 if e['id'] in ['freight-carrier','freight-second-carrier'] else 540)
        es={e['id']:e for e in g['elements']}
        g.update(gap=es['freight-second-landing']['x']-es['freight-landing']['x']-es['freight-landing']['width'],
            connection='S03-01 exit is S03-02 entry: same live freight-landing collider',
            localCatch='freight-second-catch',calibrationNote='TASK-564/561 horizontal 720 travel, 10000ms cycle; widened blue face 360; green shelves 620 and recovery 1360; placement validated here')
        self.assertEqual(g['gap'],676)
        self.assertAlmostEqual(max(v['x'] for v in g['cycle'])-min(v['x'] for v in g['cycle']),720)
        self.assertEqual(g['cycle'][-1]['x'],5196)
        self.assertTrue(all(v['px']==5036 and -740<v['py']<-708 for v in g['cycle']))
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'freight-second-landing');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'freight-second-catch'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=5036,y=-720,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 26 purposeful colliders; green/blue S03-01 and S03-02 only; carrier width 360 travel 720 cycle 600 ticks; entry/exit 620 catch 1360 gap 676 reach {g["reach"]:.3f} < 360; planned absent')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'freight-second-catch');self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'freight-second-landing'))
        self.press(p,dict(x=5110,y=-688));self.step(p,12);p.mouse.up()
        returned=self.until(p,'freight-landing');self.assertIsNotNone(returned)
        r=self.result(p)
        first_catch=self.landings(r,'freight-catch')[0]['tick']
        self.assertLess(first_catch,catch)
        r.update(earlyReleaseTick=606,firstCatchTick=first_catch,firstCatchTarget='freight-catch',
            recoveryNote='The connected aprons overlap by 180 units: the miss first bounces on S03-01 catch, then reaches the declared S03-02 catch before the recovery input',
            catchTick=catch,catchTarget='freight-second-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+12,returnTick=returned,
            recoveryTarget='freight-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 606 first apron {first_catch} declared catch {catch}; normal-control return freight-landing {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'freight-second-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'freight-second-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; two-cycle continuous hold and nearest 6/12/24; zero successful alternatives')

    def test_04_dependencies_and_index(self):
        rows=[]
        for preview in [True,False]:
            q=Task558Tests.page(self,preview)
            for mode in ['grapple_over','classic','bad']:
                row=q.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);return {mode:version,
                    range:version==='grapple_over'?grappleOverAcquisitionRadius():null,
                    upgraded:version==='grapple_over'?grappleOverProfile().upgradedAcquisitionRadius:null,
                    scale:scale[version],gravity:GRAVITY,pull:grappleSpeed}}''',mode)
                row['preview']=preview;rows.append(row)
                if mode=='grapple_over':
                    self.assertEqual(row['range'],360 if preview else 1080)
                    self.assertEqual(row['upgraded'],540 if preview else 1620);self.assertEqual(row['scale'],.375)
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview prefix -> fixedlevel.js production mover/collision',
            'tools/test_grapple_over_redesign.py additive Task580Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical; Task579 S03-01 proof remains at artifacts/TASK-579. No old v3 tests edited or rerun.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact invocation, actual exit, exact collected identifiers, revision, browser/viewport and source SHA256',
            'tests.log':'four Task580Tests; no skips; OK','geometry.json':'live collider purposes, widths, gap, target reach and 600-tick full cycle',
            'route.json':'production entry-to-exit release, landing and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early release into catch and normal-control return',
            'approach.jpg':'broad shared freight entry, blue carrier, green catch and freight signal mast',
            'landing.jpg':'safe broad green exit and Freight Crossing structure','controls.json':'bounded hold/nearest probes with every success inspected',
            'dependencies.json':'changed subsystems, unchanged modes/range/physics and source hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')
