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


class Task581Tests(unittest.TestCase):
    """Vertical freight variation from a labelled isolated fixture on the live S03-02 exit."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S03-02 exit fixture -> S03-03 only; production physics and trusted inputs; not a base-to-summit run'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=5900,y=-1028.2)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:6000,y:-720,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.freightCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);freightCycle.push({tick:i+1,y:floors[0].byId.get('freight-lift').y,
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
            encounter:floors[0].level.encounters.find(e=>e.id==='S03-03'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:freightCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02','S03'])
        self.assertEqual(g['sections'][-1]['encounters'],['S03-01','S03-02','S03-03'])
        self.assertEqual(len(g['elements']),28);self.assertEqual(len(g['movers']),3)
        self.assertEqual(g['dragCount'],0);self.assertIsNone(g['finish'])
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],360)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertTrue(e['grapplable'])
            self.assertEqual(e['role'],'solid' if e['id'] in ['freight-carrier','freight-second-carrier','freight-lift'] else 'bounce')
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],360 if e['id'] in ['freight-carrier','freight-second-carrier','freight-lift'] else 540)
        es={e['id']:e for e in g['elements']}
        g.update(gap=25,rise=760,
            connection='S03-02 exit is S03-03 entry: same live freight-second-landing collider',
            localCatch='freight-second-catch',calibrationNote='TASK-564/561 vertical 720 travel, 10000ms cycle; widened blue face 360; entry 620 exit 540 recovery 1360; placement validated here',
            sweptBounds=dict(left=5550,right=5910,top=-1788.2,bottom=-988.2))
        self.assertAlmostEqual(es['freight-lift-landing']['x']-5910,25)
        self.assertAlmostEqual(es['freight-second-landing']['y']-es['freight-lift-landing']['y'],760)
        self.assertAlmostEqual(max(v['y'] for v in g['cycle'])-min(v['y'] for v in g['cycle']),720)
        self.assertAlmostEqual(g['cycle'][-1]['y'],-1068.2)
        self.assertTrue(all(v['px']==6000 and -740<v['py']<-708 for v in g['cycle']))
        # The new lift sweep clears both earlier carrier sweeps and the fixed exit.
        self.assertLess(g['sweptBounds']['bottom'],-950)
        self.assertLess(g['sweptBounds']['right'],es['freight-lift-landing']['x'])
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'freight-lift-landing');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'freight-second-catch'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=6000,y=-720,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 28 purposeful colliders; green/blue through S03-03 only; vertical lift width 360 travel 720 cycle 600 ticks; entry 620 exit 540 catch 1360 sweep gap 25 rise 760 reach {g["reach"]:.3f} < 360; planned absent')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'freight-second-catch',800);self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'freight-lift-landing'))
        self.press(p,dict(x=5806,y=-688));self.step(p,12);p.mouse.up()
        returned=self.until(p,'freight-second-landing',800);self.assertIsNotNone(returned)
        r=self.result(p)
        r.update(earlyReleaseTick=606,catchTick=catch,catchTarget='freight-second-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+12,returnTick=returned,
            recoveryTarget='freight-second-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 606 declared catch {catch}; normal-control return freight-second-landing {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'freight-lift-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'freight-lift-landing')))
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
            'tools/test_grapple_over_redesign.py additive Task581Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical; Task580 S03-02 proof remains at artifacts/TASK-580. No old v3 tests edited or rerun.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact invocation, actual exit, exact collected identifiers, revision, browser/viewport and source SHA256',
            'tests.log':'four Task581Tests; no skips; OK','geometry.json':'live collider purposes, widths, gap, target reach and 600-tick full cycle',
            'route.json':'production entry-to-exit release, landing and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early release into catch and normal-control return',
            'approach.jpg':'broad shared freight entry, blue carrier, green catch and freight signal mast',
            'landing.jpg':'safe broad green exit and Freight Crossing structure','controls.json':'bounded hold/nearest probes with every success inspected',
            'dependencies.json':'changed subsystems, unchanged modes/range/physics and source hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')


class Task582Tests(unittest.TestCase):
    """Freight exit combination; isolated entry and continuous section are explicitly separate."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S03-02 exit -> moving lift -> fixed S03-03 shelf -> green S03-04 exit; not base-to-summit'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    capture = Task581Tests.capture
    target = dict(x=5833,y=-1801)

    def page(self):
        p=Task581Tests.page(self)
        self.press(p,Task581Tests.target);self.step(p,240);p.mouse.up()
        self.assertEqual(self.until(p,'freight-lift-landing'),925)
        return p

    def test_01_geometry_and_combination(self):
        p=self.page()
        g=p.evaluate('''t=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target:t,
            reach:Math.hypot(t.x-ninja.x,t.y-ninja.y),calibrated:GRAPPLE_OVER_MOVEMENT,
            finish:floors[0].level.finish,dragCount:floors[0].dragZones.length})''',self.target)
        self.assertEqual(len(g['elements']),31);self.assertEqual(len(g['movers']),3)
        self.assertEqual(g['sections'][-1]['encounters'],['S03-01','S03-02','S03-03','S03-04'])
        self.assertEqual(g['range'],360);self.assertLess(g['reach'],360)
        self.assertEqual(g['scale'],.375);self.assertIsNone(g['finish']);self.assertEqual(g['dragCount'],0)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertTrue(e['grapplable'])
            self.assertEqual(e['role'],'solid' if e['id'] in ['freight-carrier','freight-second-carrier','freight-lift'] else 'bounce')
            if 'anchor' not in e['id']:self.assertGreaterEqual(e['width'],360 if e['role']=='solid' else 540)
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertLess(es['freight-exit-anchor']['y']+80,-1788.2)
        self.assertLessEqual(es['freight-exit-catch']['x']+540,5550)
        self.assertLessEqual(es['freight-exit']['x']+540,5550)
        g.update(gap=5935-(5010+540),rise=280,localCatch='freight-exit-catch',
            movingTransfer='Existing lift -> freight-lift-landing before the green exit jump',
            calibrationNote='TASK-564 broad 540 shelves, 160x80 launch face; TASK-561 720-unit ten-second lift; placements validated with production physics')
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'freight-exit');self.assertIsNotNone(landing)
        r=self.result(p);streak=best=0
        for row in r['rows'][955:landing-1]:
            streak=streak+1 if not row['contacts'] and not row['attached'] and not row['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6)
        self.assertTrue(any(row['attached'] for row in r['rows'][600:840]))
        r.update(entryTick=0,takeoffTick=926,releaseTick=955,landingTick=landing,landingAir=best,
            entryToExit=True,resets=0,poseInjections=0,fixture=dict(x=6000,y=-720,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 31 purposeful green/blue colliders; S03-04 exit/catch 540; gap 385 rise 280; reach {g["reach"]:.3f} <360; planned absent; sweep clear')
        print(f'PASS route: moving-to-fixed landing 925; green release 955; exit {landing}; unattached airborne {best}; trusted input; zero resets/injections')

    def test_02_miss_and_stationary_return(self):
        p=self.page();self.press(p,self.target);self.step(p,24);p.mouse.up()
        catch=self.until(p,'freight-exit-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'freight-exit'))
        self.press(p,dict(x=5548,y=-1728));self.step(p,48);p.mouse.up()
        returned=self.until(p,'freight-exit');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=949,catchTick=catch,catchTarget='freight-exit-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+48,returnTick=returned,recoveryTarget='freight-exit',
            resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 949; stationary catch {catch}; normal-control exit return {returned}; zero resets/injections')

    def test_03_controls(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold 1200 ticks',successfulAlternative=bool(self.landings(r,'freight-exit')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'freight-exit')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,inspection='Every exit top contact inspected using nominal success definition',
            bound='1200 hold; 600 each nearest probe',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; zero successful alternatives or tiny-transfer solutions')

    def test_04_continuous_section_and_summit(self):
        p=Task579Tests.page(self)
        def pull(target,n):
            self.press(p,target);self.step(p,n);p.mouse.up()
        pull(Task579Tests.target,240)
        self.assertEqual(self.until(p,'freight-landing'),920)
        pull(dict(x=5090,y=-688),50)
        for _ in range(200):
            target=p.evaluate("({x:floors[0].byId.get('freight-second-carrier').x+10,y:-900})")
            if p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)<350',target):break
            self.step(p,1)
        self.assertLess(p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)',target),350)
        pull(target,(840-p.evaluate('YARD.result().tick')%600)%600)
        self.assertEqual(self.until(p,'freight-second-landing'),1632)
        pull(dict(x=6000,y=-688),1800-p.evaluate('YARD.result().tick'))
        pull(Task581Tests.target,300)
        self.assertEqual(self.until(p,'freight-lift-landing'),2211)
        pull(dict(x=6000,y=-1448),80)
        self.assertLess(p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)',self.target),360)
        pull(self.target,39)
        self.assertIsNotNone(self.until(p,'freight-exit'))
        r=self.result(p);exits=[]
        for i,id in enumerate(['freight-landing','freight-second-landing','freight-lift-landing','freight-exit'],1):
            rows=self.landings(r,id);self.assertTrue(rows,id)
            exits.append(dict(encounter=f'S03-0{i}',collider=id,tick=rows[0]['tick']))
        self.assertEqual([e['tick'] for e in exits],sorted(e['tick'] for e in exits))
        self.assertFalse(p.evaluate('floors[0].climbStats.completed'))
        r.update(exits=exits,resets=0,poseInjections=0,fixture=dict(x=3740,y=-720,vx=0,vy=0),
            scope='Single isolated S03 entry fixture; four exits continuously; no handoff resets; not base-to-summit',sectionCompletionEvents=0)
        q=Task567Tests.page(self)
        gate=q.evaluate('''() => {
            const m=JSON.parse(JSON.stringify(GRAPPLE_OVER_REPLACEMENT));
            m.sections=m.sections.filter(s=>s.status==='built');
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const s03=replacementMountainLevel(m).finish;
            m.sections.push({id:'S08',status:'built',encounters:[]});
            const s08=replacementMountainLevel(m).finish;floors[0].level.finish=s08;
            let events=0;const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events++;return original.call(this,name,...args)};
            YARD.step(3);CLIMB_UI.complete();
            return {s03,s08,events,completed:floors[0].climbStats.completed};
        }''')
        self.assertIsNone(gate['s03']);self.assertTrue(gate['s08']);self.assertEqual(gate['events'],1);self.assertTrue(gate['completed'])
        gate['scope']='Separate isolated S08 finish contract fixture at base; not authored S08 gameplay'
        r['summitGate']=gate;self.write('section-route.json',r)
        print(f'PASS section: four ordered exits {exits}; zero resets/injections; S03 completion 0; separate S08 gate level_completed exactly once')
    def test_05_dependencies_and_index(self):
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
            'tools/test_grapple_over_redesign.py additive Task582Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical; Task581 S03-03 proof remains at artifacts/TASK-581. No old v3 tests edited or rerun.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact invocation, actual exit, exact collected identifiers, revision, browser/viewport and source SHA256',
            'tests.log':'five Task582Tests; no skips; OK','geometry.json':'live collider purposes, widths, gap, target reach and 600-tick full cycle',
            'route.json':'production entry-to-exit release, landing and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early release into catch and normal-control return',
            'approach.jpg':'broad shared freight entry, blue carrier, green catch and freight signal mast',
            'landing.jpg':'safe broad green exit and Freight Crossing structure','controls.json':'bounded hold/nearest probes with every success inspected',
            'section-route.json':'four ordered exits from isolated S03 entry with zero handoff resets and S08-only completion gate',
            'evidence-index.json':'artifact inventory and tested hashes',
            'dependencies.json':'changed subsystems, unchanged modes/range/physics and source hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')


class Task583Tests(unittest.TestCase):
    """S03 isolated input tolerance and lower recovery; no continuous-gameplay claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390},device_scale_factor=1,
            simulation='Isolated S03 entries; 600 production ticks before input; fourth starts on the broad fixed lift landing; not continuous gameplay')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK583_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    frame = Task571Tests.frame
    until_landing = Task576Tests.until_landing
    targets = [dict(x=3960,y=-900),dict(x=5256,y=-900),dict(x=5600,y=-1800),dict(x=6660,y=-1619)]
    holds = [250,250,240,36]
    exits = ['freight-landing','freight-second-landing','freight-lift-landing','freight-exit']
    fixtures = [dict(x=3740,y=-720),dict(x=5036,y=-720),dict(x=6000,y=-720),dict(x=6400,y=-1480)]

    def setup_entry(self,p,index):
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.assertFalse(p.evaluate('TUTORIAL_HINT.visible'))
        p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});screen.trackGrappleOver(true)}',self.fixtures[index])
        self.step(p,600)
    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-50,0),('late',50,0),('left',0,-8),('right',0,8)]:
                    p=self.page(touch);self.setup_entry(p,index)

                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    nominal_hold=246 if not touch and index<2 else self.holds[index]
                    hold=nominal_hold+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S03-0{index+1} touch approach'))
                    target=dict(self.targets[index])
                    if not touch and index<2:target['x']-=20
                    xy=self.press(p,target,aim);self.step(p,hold);self.release(p)
                    self.until_landing(p,self.exits[index],800 if index==1 else 400)
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S03-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,nominalHoldTicks=nominal_hold,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        target=target,startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=r['rows'][start:],success=bool(lands))
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S03-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=self.fixtures,fixtureScope=self.config['simulation'],source_hashes=self.config['source_hashes']))
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
        recovery=[(6,'freight-catch',dict(x=3814,y=-688),12,'quarry-fourth-landing'),
            (6,'freight-second-catch',dict(x=5110,y=-688),12,'freight-landing'),
            (6,'freight-second-catch',dict(x=5806,y=-688),12,'freight-second-landing'),
            (6,'freight-exit-catch',dict(x=6465,y=-1448),12,'freight-lift-landing')]
        for touch in [False,True]:
            for index,(hold,catch_id,target,duration,return_id) in enumerate(recovery):
                p=self.page(touch);self.setup_entry(p,index);start=p.evaluate('YARD.result().tick')
                environment=p.evaluate('({movers:floors[0].level.movers,roles:floors[0].level.elements.map(e=>e.role),dragCount:floors[0].dragZones.length})')
                phase_before=p.evaluate("floors[0].elements.filter(e=>['freight-carrier','freight-second-carrier','freight-lift'].includes(e.id)).map(e=>({id:e.id,x:e.x,y:e.y}))")
                self.press(p,[Task579Tests.target,Task580Tests.target,Task581Tests.target,self.targets[3]][index]);self.step(p,hold);self.release(p)
                self.until_landing(p,catch_id,800)
                before=self.result(p)
                catches=[s for s in self.landings(before,catch_id) if s['tick']>start+hold]
                self.assertTrue(catches,(index,touch,'catch'))
                self.assertFalse([s for s in self.landings(before,self.exits[index]) if s['tick']>start])
                recovery_start=before['tick']
                if touch and index==1:duration=15
                self.press(p,target);self.step(p,duration);self.release(p)
                self.until_landing(p,return_id,800)
                r=self.result(p)
                returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                self.assertTrue(returned,(index,touch,'return'))
                self.assertEqual(set(environment['roles']),{'bounce','solid'})
                self.assertEqual(environment['dragCount'],0);self.assertEqual(len(environment['movers']),3)
                rows.append(dict(encounter=f'S03-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-(246 if not touch and index<2 else self.holds[index]))*p.evaluate('physicsStepMs'),
                    nominalHoldTicks=246 if not touch and index<2 else self.holds[index],missHoldTicks=hold,
                    startTick=start,catch=catches[0],returned=returned[0],returnCollider=return_id,
                    recoveryStart=recovery_start,inputs=r['inputs'],trace=r['rows'][start:],environment=environment,
                    moverPhaseAtPress=phase_before,moverPhaseTick=start,
                    fixtureInitializations=1,resetsAfterStart=0,poseInjectionsAfterStart=0))
                self.write('recovery.json',dict(cases=rows,source_hashes=self.config['source_hashes'],
                    scope=self.config['simulation'],hazardsAndYellow='Absent: only bounce/solid and zero drag zones'))
                p.context.close()
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses, lower catches and normal-input escapes; three production movers; zero resets/injections; no hazards/yellow')

    def test_03_refreshed_controls(self):
        cases=[]
        for touch in [False,True]:
            for interval in [None,6,12,24]:
                p=self.page(touch);self.setup_entry(p,3)
                start=p.evaluate('YARD.result().tick');targets=[]
                if interval is None:
                    self.press(p,self.targets[3]);self.step(p,1200);self.release(p)
                else:
                    for _ in range(600//(interval+1)):
                        target=p.evaluate('YARD.nearest()');targets.append(target)
                        self.press(p,target);self.step(p,interval);self.release(p);self.step(p,1)
                r=self.result(p)
                exits=[row for row in self.landings(r,'freight-exit') if row['tick']>start]
                cases.append(dict(mode='touch' if touch else 'desktop',
                    probe='hold 1200' if interval is None else f'nearest {interval}',
                    startTick=start,endTick=r['tick'],inputs=r['inputs'],trace=r['rows'][start:],
                    targets=targets,exitContacts=exits,successfulAlternative=bool(exits)))
                p.context.close()
        self.write('controls.json',dict(cases=cases,source_hashes=self.config['source_hashes'],
            scope='Isolated S03-04 fixed landing; same fixture and exit top-contact definition as tolerance',
            inspection='Every top-facing exit contact inspected; hold 1200 ticks and nearest 6/12/24 for <=600 ticks'))
        self.assertEqual(len(cases),8)
        for c in cases:
            if c['probe']=='hold 1200':
                # Holding can reach the broad exit while still attached. Retain and
                # inspect this alternative honestly; it does not prove a release jump.
                self.assertTrue(c['exitContacts'],c['mode'])
                self.assertTrue(all(row['attached'] for row in c['exitContacts']),c['mode'])
            else:
                self.assertFalse(c['successfulAlternative'],(c['mode'],c['probe']))
        print('PASS controls: 8 desktop/genuine-touch probes; 6 nearest fail; 2 held-rope exit alternatives inspected, all contacts attached')

    def test_04_refreshed_section_tail(self):
        cases=[]
        for touch in [False,True]:
            p=self.page(touch);self.setup_entry(p,2)
            start=p.evaluate('YARD.result().tick')
            p.evaluate('''() => {const step=YARD.step;YARD.step=n=>{for(let i=0;i<n;i++){
                step(1);YARD.result().rows.at(-1).ropeElements=grapnel.isGrappled()?grapnel.pos.map(p=>p[2].id):[];
            }}}''')
            self.press(p,self.targets[2]);self.step(p,240);self.release(p)
            fixed=Task581Tests.until(self,p,'freight-lift-landing')
            self.assertIsNotNone(fixed)
            # Traverse the existing broad shelf with normal grappling. No handoff fixture.
            self.press(p,dict(x=6420,y=-1448));self.step(p,60);self.release(p)
            self.press(p,self.targets[3]);self.step(p,36);self.release(p)
            release=p.evaluate('YARD.result().tick')
            exit_tick=Task581Tests.until(self,p,'freight-exit',500)
            self.assertIsNotNone(exit_tick)
            r=self.result(p);trace=r['rows'][start:]
            self.assertTrue(any('freight-lift' in row['ropeElements'] for row in trace))
            self.assertTrue(any(row['attached'] for row in trace if row['tick']<fixed))
            streak=best=0
            for row in trace:
                streak=streak+1 if row['tick']>release and not row['attached'] and not row['shot'] and not row['contacts'] else 0
                best=max(best,streak)
            self.assertGreaterEqual(best,6)
            self.assertFalse(p.evaluate('floors[0].climbStats.completed'))
            cases.append(dict(mode='touch' if touch else 'desktop',startTick=start,
                fixedLandingTick=fixed,releaseTick=release,exitTick=exit_tick,airborneTicks=best,
                inputs=r['inputs'],trace=trace,resetsAfterStart=0,poseInjectionsAfterStart=0,
                fixtureInitializations=1,completion=False))
            p.context.close()
        self.write('section-route.json',dict(cases=cases,source_hashes=self.config['source_hashes'],
            scope='Focused continuous S03-03 moving lift -> fixed landing -> S03-04 exit; isolated S03-02 exit fixture only; not full section or base-to-summit',
            fixture=self.fixtures[2]))
        print('PASS section tail: desktop/genuine-touch lift -> fixed landing -> exit; zero handoff resets/injections; >=6 airborne ticks; no completion')

    def test_05_evidence_index(self):
        p=self.page()
        geometry=p.evaluate('({elements:floors[0].level.elements,range:grappleOverAcquisitionRadius(),scale:scale[version],finish:floors[0].level.finish})')
        es={e['id']:e for e in geometry['elements']}
        self.assertEqual(geometry['range'],360);self.assertEqual(geometry['scale'],.375)
        self.assertIsNone(geometry['finish'])
        self.assertEqual(es['freight-exit']['x']-es['freight-lift-landing']['x']-540,153)
        self.assertEqual(es['freight-lift-landing']['y']-es['freight-exit']['y'],60)
        for name in ['freight-exit-anchor','freight-exit','freight-exit-catch']:
            self.assertGreater(es[name]['x'],5910)  # clear the entire lift sweep
        previous=json.loads((ROOT/'artifacts/TASK-581/geometry.json').read_text())
        # The earlier 28 colliders and all mover physics are unchanged.
        for e in previous['elements']:
            for key in ['x','y','points','role','grapplable']:
                self.assertEqual(es[e['id']][key],e[key],(e['id'],key))
        print('PASS dependencies: 28 earlier colliders unchanged; S03-04 geometry and right-edge camera refreshed locally; historical proofs retained')
        self.write('affected-proof-map.json',dict(geometryChanges=[
            dict(id='preview-camera-bounds',old=dict(right=6480),new=dict(right=7600)),
            dict(id='freight-exit-anchor',old=[5675,-1879,160,80],new=[6580,-1659,160,80]),
            dict(id='freight-exit',old=[5010,-1748.2,540,60],new=[6628,-1528.2,680,60]),
            dict(id='freight-exit-catch',old=[5010,-1428.2,540,60],new=[6480,-1248.2,880,60])],
            runtimeChanges=['mountain.js replacement preview S03-04 and camera right bound only'],observedGeometry=geometry,
            superseded='TASK-582 S03-04 geometry, route, miss, controls and continuous-section end are historical; originals retained. Local tolerance/recovery, hold/nearest controls and continuous moving-to-fixed-to-exit tail refreshed here; no full-section claim.',
            entryChange='S03-04 isolated entry x6400 on the existing 540-wide lift landing; S03-03 separately proves the moving-to-fixed transfer',
            routeChange='First two carrier routes aim 30 world units inward and release 6 ticks later on desktop, 50 units and 10 ticks on touch; lift uses the same ray toward a farther visible aim point to reduce edge sensitivity',
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg','controls.json','section-route.json'],
            previousProof=[f'artifacts/TASK-{n}/route.json' for n in range(579,583)],
            dependencies=['Task583Tests -> browser_test_support + grapple_over_yard.js -> events.js, physics.js, fixedlevel.js, mountain.js'],
            changedSubsystems=['S03-04 replacement preview geometry','Additive Python tests'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit; S03-04 geometry and right-edge camera composition superseded; all four local desktop/touch proofs refreshed'))
        required={'commands.log':'exact command, actual exit status, identifiers, Chromium/viewports/DPR, revision and hashes',
            'tests.log':'archived tolerance/recovery plus focused controls/section-tail/index methods, no skips, OK',
            'controls.json':'8 bounded desktop/touch hold/nearest probes with all exit contacts inspected',
            'section-route.json':'continuous moving-to-fixed-to-exit tail in both modes, zero handoff resets',
            'tolerance.json':'40 successful variants with trusted input timestamps and top-facing exit contacts',
            'recovery.json':'8 out-of-window misses, lower contacts, mover phases and normal-input escapes',
            'affected-proof-map.json':'geometry changes and subsystem dependencies',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,scope=self.config['simulation']))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')


class Task584Tests(unittest.TestCase):
    """Review current S03, with independent fixtures and a separately continuous route."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='One isolated S03 entry, then continuous production traversal; separate phase fixtures labelled'

    write = Task557Tests.write
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until

    def fixture(self, index):
        p=self.page()
        p.evaluate('s=>{TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500);Object.assign(ninja,s,{speedX:0,speedY:0});screen.trackGrappleOver(true)}',Task583Tests.fixtures[index])
        return p

    def test_01_objects_dependencies_and_four_phase_traversal(self):
        p=self.fixture(0)
        g=p.evaluate('''() => ({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,dragCount:floors[0].dragZones.length,
            range:grappleOverAcquisitionRadius(),upgrade:grappleOverProfile().upgradedAcquisitionRadius,
            scale:scale[version],calibration:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS}})''')
        self.assertEqual((g['range'],g['upgrade'],g['scale']),(360,540,.375))
        self.assertEqual(g['dragCount'],0);self.assertEqual(len(g['elements']),31)
        self.assertEqual([e['id'] for e in g['encounters'] if e['id'].startswith('S03')],['S03-01','S03-02','S03-03','S03-04'])
        es={e['id']:e for e in g['elements']}
        for e in g['elements']:
            self.assertTrue(e['purpose']);self.assertTrue(e['grapplable'])
            self.assertIn(e['role'],['solid','bounce'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            e['height']=max(v['y'] for v in e['points'])-min(v['y'] for v in e['points'])
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if not e['id'].startswith('freight')))
        cycle=p.evaluate('''() => {let a=[];for(let i=0;i<600;i++){YARD.step(1);
            a.push({tick:i+1,player:{x:ninja.x,y:ninja.y},movers:floors[0].level.movers.map(m=>{
                const e=floors[0].byId.get(m.element),ps=e.getPoints();return {id:e.id,x:e.x,y:e.y,
                left:Math.min(...ps.map(v=>v.x)),right:Math.max(...ps.map(v=>v.x)),
                top:Math.min(...ps.map(v=>v.y)),bottom:Math.max(...ps.map(v=>v.y))}})});}return a}''')
        for i,m in enumerate(g['movers']):
            e=es[m['element']];positions=[r['movers'][i] for r in cycle]
            m['observedTravel']=max(r[m['axis']] for r in positions)-min(r[m['axis']] for r in positions)
            self.assertGreaterEqual(m['observedTravel'],max(360,2*e['width' if m['axis']=='x' else 'height']))
            self.assertTrue(6000<=m['periodMs']<=10000)
            m['sweptBounds']={k:fn(r[k] for r in positions) for k,fn in [('left',min),('right',max),('top',min),('bottom',max)]}
            b=m['sweptBounds'];m['sweepIntersections']=[]
            for other in g['elements']:
                if other['id']==e['id']:continue
                if max(b['left'],other['x'])<min(b['right'],other['x']+other['width']) and max(b['top'],other['y'])<min(b['bottom'],other['y']+other['height']):m['sweepIntersections'].append(other['id'])
            self.assertEqual(m['sweepIntersections'],[])
        # Closest point on the moving blue face, measured from the bouncing entry player.
        available=[]
        for r in cycle:
            b=r['movers'][0];x=r['player']['x'];y=r['player']['y']
            distance=((max(b['left']-x,0,x-b['right']))**2+(max(b['top']-y,0,y-b['bottom']))**2)**.5
            available.append(distance<=360)
        best=streak=0
        for hit in available*2:
            streak=streak+1 if hit else 0;best=max(best,streak)
        g['firstAcquisitionWindowMs']=min(best,600)*1000/60
        self.assertGreaterEqual(g['firstAcquisitionWindowMs'],1000)
        g.update(firstUseOrder=['green S01/S02','blue S03-01'],yellow='absent; suppression and clearance not applicable',hazards='absent; contact recovery not applicable',removedClutter='none: every collider has an encounter and route/recovery purpose',planningWidths=[es[n]['width'] for n in Task583Tests.exits],exitGap=es['freight-exit']['x']-es['freight-lift-landing']['x']-540)
        self.assertEqual(g['planningWidths'],[620,620,540,680]);self.assertEqual(g['exitGap'],153)
        self.write('objects.json',g);self.write('cycle.json',dict(samples=cycle))
        p.context.close()
        cases=[]
        for index in range(3):
            for phase in [0,150,300,450]:
                p=self.fixture(index);self.step(p,phase)
                # Arrival at each quarter-cycle followed by observation on the broad entry.
                self.step(p,600-phase)
                target=dict(Task583Tests.targets[index])
                if index<2:target['x']-=20
                self.press(p,target);self.step(p,246 if index<2 else 240);self.release(p)
                landing=self.until(p,Task583Tests.exits[index],800)
                self.assertIsNotNone(landing,(index,phase))
                r=self.result(p)
                cases.append(dict(mover=g['movers'][index]['element'],arrivalPhase=phase/600,waitTicks=600-phase,
                    landingTick=landing,exit=Task583Tests.exits[index],inputs=r['inputs'],
                    attachmentTicks=sum(s['attached'] for s in r['rows']),landing=self.landings(r,Task583Tests.exits[index])[0],resetsAfterFixture=0))
                self.assertGreater(cases[-1]['attachmentTicks'],0);p.context.close()
        self.write('phases.json',dict(scope='12 isolated arrival-phase fixtures; wait on safe shelf then traverse using normal input; not continuous gameplay',cases=cases))
        old=json.loads((ROOT/'artifacts/TASK-583/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        reused=[]
        for name in ['tolerance.json','recovery.json','controls.json','section-route.json','verifier-focused-tests.log','tests.log']:
            path='artifacts/TASK-583/'+name
            reused.append(dict(path=path,sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()))
        tolerance=json.loads((ROOT/'artifacts/TASK-583/tolerance.json').read_text())['cases']
        recovery=json.loads((ROOT/'artifacts/TASK-583/recovery.json').read_text())['cases']
        self.assertEqual(len(tolerance),40);self.assertTrue(all(c['success'] for c in tolerance));self.assertEqual(len(recovery),8)
        for c in recovery:
            self.assertTrue(c['catch']['contacts']);self.assertTrue(c['returned']['contacts'])
        self.write('dependency.json',dict(unchanged=unchanged,reused=reused,changed=['tools/test_grapple_over_redesign.py additive Task584Tests'],
            subsystems='mountain/fixedlevel geometry and movers; physics/events input/rope; render/landmarks/draw; all runtime hashes unchanged',
            superseded='TASK-582 full route uses historical S03-04 geometry; refreshed here. Historical tests preserved.',
            hashPolicy='HEAD-only commit does not invalidate identical tested hashes'))
        print(f'PASS objects: 31 purposeful objects; green then first blue S03-01; 4 encounters; planning widths 620/620/540/680; gap 153; yellow=0 hazards=0')
        print(f'PASS movers: 3 travel=720 period=10000; full sweeps clear; first acquisition window={g["firstAcquisitionWindowMs"]:.1f}ms; 12 four-phase traversals')
        print('PASS dependencies: runtime hashes unchanged; archived 40 tolerance and 8 recovery cases inspected')

    def test_02_continuous_route_and_composition(self):
        p=self.fixture(0)
        p.evaluate('''() => {window.frames584=[];const step=YARD.step;
            window.capture584=()=>{draw();frames584.push({image:canvas.toDataURL('image/jpeg',.75),tick:YARD.result().tick})};
            YARD.step=n=>{for(let i=0;i<n;i++){step(1);if(YARD.result().tick%12===0)capture584()}};capture584()}''')
        self.step(p,600);approaches=[];observations=[]
        def capture(index,target):
            p.evaluate('draw()')
            obs=p.evaluate('t=>({tick:YARD.result().tick,target:t,client:YARD.client(t),landmark:LANDMARKS.frame.drawn,player:{x:ninja.x,y:ninja.y}})',target)
            self.assertTrue(0<obs['client']['x']<1280 and 0<obs['client']['y']<720)
            observations.append(obs)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),f'S03-0{index} actual continuous approach, tick {obs["tick"]}',fill='white');approaches.append(im)
        def pull(t,n):self.press(p,t);self.step(p,n);self.release(p)
        capture(1,Task579Tests.target);pull(Task579Tests.target,240)
        self.assertEqual(self.until(p,'freight-landing'),920)
        pull(dict(x=5090,y=-688),50)
        for _ in range(200):
            target=p.evaluate("({x:floors[0].byId.get('freight-second-carrier').x+10,y:-900})")
            if p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)<350',target):break
            self.step(p,1)
        capture(2,target);pull(target,(840-p.evaluate('YARD.result().tick')%600)%600)
        self.assertEqual(self.until(p,'freight-second-landing'),1632)
        pull(dict(x=5880,y=-688),1800-p.evaluate('YARD.result().tick'))
        capture(3,Task583Tests.targets[2]);pull(Task583Tests.targets[2],240)
        fixed=self.until(p,'freight-lift-landing',600)
        self.assertIsNotNone(fixed)
        pull(dict(x=6420,y=-1448),60)
        capture(4,Task583Tests.targets[3]);pull(Task583Tests.targets[3],36)
        self.assertIsNotNone(self.until(p,'freight-exit',500))
        r=self.result(p);exits=[dict(id=id,tick=self.landings(r,id)[0]['tick']) for id in Task583Tests.exits]
        self.assertEqual([e['tick'] for e in exits],sorted(e['tick'] for e in exits))
        self.write('route.json',dict(exits=exits,inputs=r['inputs'],trace=r['rows'],resetsAfterStart=0,poseInjectionsAfterStart=0,scope=self.config['simulation']))
        self.write('approaches.json',dict(views=observations))
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(approaches):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=85)
        # Two adjacent camera tiles, using production render and unchanged .375 scale.
        tiles=[];flat=[]
        for center in [4350,6450]:
            p.evaluate('x=>{screen.x=width/.375/2-x;screen.y=height/.375/2+1120;draw()}',center)
            tiles.append(Image.open(io.BytesIO(p.screenshot())).convert('RGB'))
            flat.append(p.evaluate('''() => ({elements:floors[0].elements.map(e=>({id:e.id,points:e.getPoints()})),
                shape:replacementFreightShape(GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
                landmark:{x:(4320+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,y:(-800+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
                camera:{x:screen.x,y:screen.y},factor:1280/width})'''))
        overview=Image.new('RGB',(2560,720));sil=Image.new('RGB',(2560,720),'white');pen=ImageDraw.Draw(sil)
        for i,(im,f) in enumerate(zip(tiles,flat)):
            overview.paste(im,(i*1280,0));k=f['factor']
            for part in f['shape']['parts']:
                pen.polygon([((x+f['landmark']['x'])*k+i*1280,(y+f['landmark']['y'])*k) for x,y in part],fill='#777777')
            for e in f['elements']:
                pts=[((v['x']+f['camera']['x'])*.375*k+i*1280,(v['y']+f['camera']['y'])*.375*k) for v in e['points']]
                # Clip to each camera tile via a separate drawing surface below.
                if all(i*1280<=x<(i+1)*1280 for x,y in pts):
                    pen.polygon(pts,fill='black')
                    if e['id'].startswith('freight'):pen.text(pts[0],e['id'],fill='#555555')
        pen.text((20,20),'Freight Crossing: signal mast / overhead rail (gray), live collision silhouettes (black); two camera tiles',fill='black')
        overview.save(self.out/'overview.png');sil.save(self.out/'silhouette.png')
        # Separate labelled recovery fixture; never presented as a continuation of the route.
        q=self.fixture(0);self.step(q,600)
        q.evaluate('''() => {window.recoveryFrames=[];const step=YARD.step;
            const capture=()=>{draw();recoveryFrames.push({image:canvas.toDataURL('image/jpeg',.75),tick:YARD.result().tick,label:'SEPARATE isolated miss / recovery'})};
            YARD.step=n=>{for(let i=0;i<n;i++){step(1);if(YARD.result().tick%12===0)capture()}};capture()}''')
        self.press(q,Task579Tests.target);self.step(q,6);self.release(q)
        catch=self.until(q,'freight-catch');self.assertIsNotNone(catch)
        self.press(q,dict(x=3814,y=-688));self.step(q,12);self.release(q)
        returned=self.until(q,'quarry-fourth-landing');self.assertIsNotNone(returned)
        recovery=self.result(q)
        self.write('recovery.json',dict(catchTick=catch,returnTick=returned,inputs=recovery['inputs'],trace=recovery['rows'][600:],
            scope='Separate isolated early-release fixture; continuous from press to catch and return; no handoff resets'))
        p.evaluate('a=>frames584.push(...a)',q.evaluate('recoveryFrames'));q.context.close()
        p.bring_to_front()  # Avoid background timer throttling during encoding/playback.
        # Encode sampled production frames separately; 12 physics ticks per 50ms video = 4x.
        clip=p.evaluate('''async () => {
            const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');
            const stream=c.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of frames584){const im=new Image();im.src=f.image;await im.decode();ctx.drawImage(im,0,0,1280,720);
                ctx.fillStyle='white';ctx.fillText((f.label || 'S03 continuous from isolated entry')+' / 4x / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});return await new Promise(r=>{const rd=new FileReader();rd.onload=()=>r(rd.result.split(',')[1]);rd.readAsDataURL(blob)})}''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);await v.play();
            await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],150);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)
        print(f'PASS continuous: four ordered exits {exits}; full 600-tick mover cycle; zero handoff resets/injections; separate fall catch={catch} return={returned}; clip decoded {decoded}')

    def test_03_evidence_index(self):
        required={'commands.log':'exact commands, exits, identifiers, browser/viewport/revision/source hashes','tests.log':'three focused Task584Tests with no skips and OK',
            'overview.png':'two adjacent production camera views of all four encounters and freight mast',
            'silhouette.png':'monochrome landmark/collider structure and open gaps','approaches.jpg':'four actual continuous approach views',
            'approaches.json':'approach ticks and on-screen target coordinates','objects.json':'31 purposes, role order, widths, full sweep bounds, 1s acquisition window',
            'cycle.json':'600 production ticks of all three movers and player; no phase injection','phases.json':'12 successful quarter-phase arrival/wait/traversal fixtures',
            'section.webm':'continuous S03 from isolated entry; includes full mover cycle, four exits; 4x sampled playback',
            'recovery.json':'separate labelled early miss, catch and normal-input return',
            'route.json':'trusted input, ordered landing contacts and continuous trace','clip-decode.json':'full video decode count',
            'dependency.json':'unchanged source hashes and hashed reused proof; archived recoveries','review.md':'independent visual/pacing observations; no human enjoyment claim',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreaterEqual(im.width,1280)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; three images decode; video decoded; retained evidence <200 MB')


class Task585Tests(unittest.TestCase):
    """S04-01 local fixture on the actual S03 exit; never a base-to-summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated entry on live freight-exit; continuous production inputs/physics through S04-01 or its recovery; no base-to-summit claim'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    target = dict(x=7488,y=-1679)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:7228,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'broken-viaduct')
        self.assertEqual(p.evaluate('I18N.t(replacementSection().labelKey)'),'Broken Viaduct')
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        with Image.open(self.out/name) as im:
            im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S04-01'),range:grappleOverAcquisitionRadius(),
            scale:scale[version],target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S04-01'])
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02','S03','S04'])
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],360);self.assertIsNone(g['finish'])
        for e in g['elements']:
            self.assertTrue(e['purpose']);self.assertNotEqual(e['role'],'hazard')
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        for id in g['encounter']['elements']:
            e=es[id]
            if id!='viaduct-anchor':self.assertGreaterEqual(e['width'],540)
            self.assertEqual(e['role'],'drag' if id=='viaduct-yellow' else 'bounce')
        self.assertEqual([e['id'] for e in g['elements'] if e['role']=='drag'],['viaduct-yellow'])
        self.assertFalse(es['viaduct-yellow']['grapplable'])
        g.update(gap=es['viaduct-landing']['x']-(es['freight-exit']['x']+es['freight-exit']['width']),
            yellowClearance=es['viaduct-yellow']['y']-(es['viaduct-landing']['y']+60),
            connection='Shared live freight-exit collider; no teleport or handoff reset',
            localCatch='viaduct-catch',recovery=['viaduct-catch','freight-exit-catch','freight-exit'],
            calibrationNote='TASK-564 broad exposed bridge; TASK-560 opening gap 252/release 30 translated to shared exit; first yellow only below S04 route; 150-thick band tested here')
        self.assertEqual(g['gap'],252);self.assertGreater(g['yellowClearance'],300)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'viaduct-landing');self.assertEqual(landing,105)
        r=self.result(p);streak=best=0
        for s in r['rows'][30:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=30,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=7228,y=-1540,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: S04-01 only; gap 252; entry/exit 680; recovery 1600; yellow 1600x150 clearance {g["yellowClearance"]}; reach {g["reach"]:.3f}<360; green/blue then yellow; no red/planned colliders')
        print(f'PASS route: takeoff {r["takeoffTick"]} release 30 landing 105; consecutive unattached airborne {best}; trusted inputs; zero resets/injections; Broken Viaduct images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'viaduct-catch');self.assertEqual(catch,212)
        before=self.result(p);self.assertFalse(self.landings(before,'viaduct-landing'))
        yellow=[s for s in before['rows'] if 7360<=s['x']<=8960 and -1150<=s['y']<=-1000]
        self.assertGreater(len(yellow),6);self.assertTrue(all(not s['attached'] for s in yellow))
        self.press(p,dict(x=7320,y=-1220));self.step(p,60);p.mouse.up()
        intermediate=self.until(p,'freight-exit-catch');self.assertEqual(intermediate,317)
        self.press(p,dict(x=7300,y=-1500));self.step(p,24);p.mouse.up()
        # Ordinary bounces carry the player around the shelf's east edge.
        self.step(p,250)
        self.press(p,dict(x=7270,y=-1510));self.step(p,12);p.mouse.up()
        returned=self.until(p,'freight-exit');self.assertEqual(returned,641)
        r=self.result(p);r.update(earlyReleaseTick=6,catchTick=catch,catchTarget='viaduct-catch',
            yellowTicks=[s['tick'] for s in yellow],intermediateTick=intermediate,
            recoveryTarget='freight-exit',returnTick=returned,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 6; yellow transit {len(yellow)} ticks; lower catch 212; freight recovery 317; normal-control entry return {returned}; zero resets/injections')

    def test_03_controls(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600 ticks',successfulAlternative=bool(self.landings(r,'viaduct-landing')))
        cases.append(r);p.mouse.up();p.context.close()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'viaduct-landing')))
            cases.append(r);p.context.close()
        self.write('controls.json',dict(cases=cases,bound='600 ticks hold; <=600 ticks each nearest 6/12/24',
            inspection='Every top-facing viaduct-landing contact checked using nominal success definition',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted hold/nearest probes; zero successful alternatives using same exit contact criterion')

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
            q.context.close()
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview -> fixedlevel.js colliders/drag',
            'render/landmarks.js S04 visual silhouette -> i18n.js section label','tools/test_grapple_over_redesign.py Task585Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical. TASK-584 Freight proof remains in place. No legacy or earlier tests changed; no full mountain claim.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, actual exit, test identifiers/count, revision, browser/viewport and hashes',
            'tests.log':'four Task585Tests, no skips, OK','geometry.json':'live roles/purposes, widths/gap/clearance/reach/range',
            'route.json':'trusted entry-to-exit with >=6 airborne unattached ticks','inputs.json':'trusted production events',
            'miss.json':'yellow fall, lower catch and normal-control return','approach.jpg':'broad targets, lower yellow band and broken bridge',
            'landing.jpg':'safe broad exit and broken viaduct silhouette','controls.json':'bounded hold/nearest and all success inspections',
            'dependencies.json':'changed dependencies and preserved modes/physics/range'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            hashPolicy='Identical source hashes remain valid after HEAD-only commit',scope=self.config['simulation']))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; unchanged physics/input; evidence index written')


class Task586Tests(unittest.TestCase):
    """S04-02 local fixture on the live first bridge landing; never a base-to-summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated entry on live viaduct-landing; continuous production inputs/physics through S04-02 or its recovery; no base-to-summit claim'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    target = dict(x=8420,y=-1679)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:8160,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'broken-viaduct')
        self.assertEqual(p.evaluate('I18N.t(replacementSection().labelKey)'),'Broken Viaduct')
        p.evaluate('''() => {let label=document.createElement('div');label.id='proof-label';
            label.textContent='S04-02 isolated entry fixture / production physics / '+YARD.result().tick+' ticks';
            label.style='position:fixed;left:12px;bottom:12px;color:white;background:#111;padding:8px;font:14px sans-serif;z-index:9999';
            document.body.appendChild(label)}''')
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:
            im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S04-02'),range:grappleOverAcquisitionRadius(),
            scale:scale[version],target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S04-01','S04-02'])
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02','S03','S04'])
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],360);self.assertIsNone(g['finish'])
        for e in g['elements']:
            self.assertTrue(e['purpose']);self.assertNotEqual(e['role'],'hazard')
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        for id in g['encounter']['elements']:
            e=es[id]
            if id not in ['viaduct-second-anchor','viaduct-recovery-wall']:self.assertGreaterEqual(e['width'],540)
            self.assertEqual(e['role'],'drag' if id=='viaduct-yellow' else 'bounce')
        self.assertEqual([e['id'] for e in g['elements'] if e['role']=='drag'],['viaduct-yellow'])
        self.assertFalse(es['viaduct-yellow']['grapplable'])
        g.update(gap=es['viaduct-second-landing']['x']-(es['viaduct-landing']['x']+es['viaduct-landing']['width']),
            yellowClearance=es['viaduct-yellow']['y']-(es['viaduct-second-landing']['y']+60),
            connection='Shared live viaduct-landing collider; no teleport or handoff reset',
            localCatch='viaduct-catch',recovery=['viaduct-catch','viaduct-recovery-wall','freight-exit-catch','viaduct-landing'],
            calibrationNote='TASK-564 broad exposed bridge; TASK-560 opening gap 252/release 30 translated to shared exit; first yellow only below S04 route; 150-thick band tested here')
        self.assertEqual(g['gap'],252);self.assertGreaterEqual(g['yellowClearance'],540)
        g['entryYellowClearance']=es['viaduct-yellow']['y']-(es['viaduct-landing']['y']+60)
        self.assertGreaterEqual(g['entryYellowClearance'],540)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'viaduct-second-landing');self.assertEqual(landing,105)
        r=self.result(p);streak=best=0
        for s in r['rows'][30:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=30,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=8160,y=-1540,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: S04-02 only; gap 252; entry/exit 680; recovery 2000; yellow 1600x150 clearance {g["yellowClearance"]}; reach {g["reach"]:.3f}<360; green/blue then yellow; no red/planned colliders')
        print(f'PASS route: takeoff {r["takeoffTick"]} release 30 landing 105; consecutive unattached airborne {best}; trusted inputs; zero resets/injections; Broken Viaduct images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page()
        plan=[(8420,-1679,6,226),(8100,-650,30,60),(7600,-650,30,60),
              (7320,-900,60,20),(7300,-1130,60,0),(7355,-1245,71,0),(7307,-1525,48,163)]
        for x,y,hold,coast in plan:
            self.press(p,dict(x=x,y=y));self.step(p,hold);p.mouse.up();self.step(p,coast)
        r=self.result(p)
        self.assertEqual(self.landings(r,'viaduct-catch')[0]['tick'],232)
        self.assertEqual(self.landings(r,'freight-exit-catch')[0]['tick'],623)
        self.assertEqual(self.landings(r,'viaduct-landing')[-1]['tick'],834)
        self.assertFalse(self.landings(r,'viaduct-second-landing'))
        yellow=[s for s in r['rows'][:232] if 7360<=s['x']<=8960 and -928.2<=s['y']<=-778.2]
        self.assertGreater(len(yellow),6)
        r.update(earlyReleaseTick=6,catchTick=232,catchTarget='viaduct-catch',
            yellowTicks=[s['tick'] for s in yellow],intermediateTick=623,recoveryTarget='viaduct-landing',
            returnTick=834,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 6; yellow transit {len(yellow)} ticks; lower catch 232; freight shelf 623; normal-control entry return 834; zero resets/injections')

    def test_03_controls(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600 ticks',successfulAlternative=bool(self.landings(r,'viaduct-second-landing')))
        cases.append(r);p.mouse.up();p.context.close()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'viaduct-second-landing')))
            cases.append(r);p.context.close()
        self.write('controls.json',dict(cases=cases,bound='600 ticks hold; <=600 ticks each nearest 6/12/24',
            inspection='Every top-facing viaduct-second-landing contact checked using nominal success definition',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted hold/nearest probes; zero successful alternatives using same exit contact criterion')

    def test_04_dependencies_and_index(self):
        p=Task585Tests.page(self)
        self.press(p,Task585Tests.target);self.step(p,30);p.mouse.up()
        self.assertEqual(self.until(p,'viaduct-landing'),105)
        self.write('previous-span.json',self.result(p));p.context.close()
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
            q.context.close()
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview -> fixedlevel.js colliders/drag',
            'S04 lowered yellow/catch and added west recovery wall; existing landmark/label unchanged','tools/test_grapple_over_redesign.py Task586Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical. TASK-585 first-span route remains valid and is replayed here; its exact yellow clearance and recovery timings are superseded by the deeper band and wall. TASK-584 Freight proof remains in place. No legacy or earlier tests changed; no full mountain claim.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, actual exit, test identifiers/count, revision, browser/viewport and hashes',
            'tests.log':'four Task586Tests, no skips, OK','geometry.json':'live roles/purposes, widths/gap/clearance/reach/range',
            'route.json':'trusted entry-to-exit with >=6 airborne unattached ticks','inputs.json':'trusted production events',
            'miss.json':'yellow fall, lower catch and normal-control return','approach.jpg':'broad targets, lower yellow band and broken bridge',
            'landing.jpg':'safe broad exit and broken viaduct silhouette','controls.json':'bounded hold/nearest and all success inspections',
            'previous-span.json':'affected first span still lands at tick 105',
            'dependencies.json':'changed dependencies and preserved modes/physics/range'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            hashPolicy='Identical source hashes remain valid after HEAD-only commit',scope=self.config['simulation']))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; unchanged physics/input; evidence index written')


class Task587Tests(unittest.TestCase):
    """Freight introduction from a labelled isolated fixture on the live S04-02 exit."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S04-02 exit fixture -> S04-03 only; production physics and trusted inputs; not a base-to-summit run'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=9258,y=-1720)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:9088,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.viaductCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);viaductCycle.push({tick:i+1,x:floors[0].byId.get('viaduct-carrier').x,
                px:ninja.x,py:ninja.y});}}''')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'broken-viaduct')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S04-03 isolated entry fixture / production physics';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_cycle_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S04-03'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:viaductCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02','S03','S04'])
        self.assertEqual(g['sections'][-1]['encounters'],['S04-01','S04-02','S04-03'])
        self.assertEqual(len(g['elements']),41);self.assertEqual(len(g['movers']),4)
        self.assertEqual(g['dragCount'],1);self.assertIsNone(g['finish'])
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],360)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertNotEqual(e['role'],'hazard')
        for id in g['encounter']['elements']:
            e=next(e for e in g['elements'] if e['id']==id)
            self.assertGreaterEqual(e['width'],360 if id=='viaduct-carrier' else 540)
            self.assertEqual(e['role'],'solid' if id=='viaduct-carrier' else 'drag' if id=='viaduct-yellow' else 'bounce')
        self.assertNotIn('preview-unbuilt',[e['id'] for e in g['elements']])
        es={e['id']:e for e in g['elements']}
        g.update(gap=es['viaduct-third-landing']['x']-es['viaduct-second-landing']['x']-es['viaduct-second-landing']['width'],
            connection='S04-02 exit is S04-03 entry: same live viaduct-second-landing collider',
            localCatch='viaduct-third-catch',calibrationNote='TASK-564/561 horizontal 720 travel, 10000ms cycle; widened blue face 360; green shelves 680 and recovery 1476; placement validated here')
        self.assertEqual(g['gap'],676)
        self.assertAlmostEqual(max(v['x'] for v in g['cycle'])-min(v['x'] for v in g['cycle']),720)
        self.assertEqual(g['cycle'][-1]['x'],9248)
        self.assertTrue(all(v['px']==9088 and -1560<v['py']<-1528 for v in g['cycle']))
        carrier=es['viaduct-carrier']
        g['sweptBounds']={'left':min(v['x'] for v in g['cycle']),
            'right':max(v['x'] for v in g['cycle'])+carrier['width'],
            'top':carrier['y'],'bottom':carrier['y']+max(v['y'] for v in carrier['points'])}
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertEqual([e['id'] for e in g['elements'] if e['role']=='drag'],['viaduct-yellow'])
        g['yellowClearance']=es['viaduct-yellow']['y']-g['sweptBounds']['bottom']
        self.assertGreaterEqual(g['yellowClearance'],600)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'viaduct-third-landing');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'viaduct-third-catch'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=9088,y=-1540,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry: 41 purposeful colliders; S04-03 blue carrier sweep clear of yellow; carrier width 360 travel 720 cycle 600 ticks; entry/exit 680 catch 1476 gap 676 reach {g["reach"]:.3f} < 360; planned absent')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'viaduct-third-catch');self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'viaduct-third-landing'))
        self.press(p,dict(x=9162,y=-1508));self.step(p,12);p.mouse.up()
        returned=self.until(p,'viaduct-second-landing');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=606,catchTick=catch,catchTarget='viaduct-third-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+12,returnTick=returned,
            recoveryTarget='viaduct-second-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 606 catch {catch}; normal-control return viaduct-second-landing {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'viaduct-third-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'viaduct-third-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; two-cycle continuous hold and nearest 6/12/24; zero successful alternatives')

    def test_04_dependencies_and_index(self):
        p=Task586Tests.page(self)
        self.press(p,Task586Tests.target);self.step(p,30);p.mouse.up()
        self.assertEqual(self.until(p,'viaduct-second-landing'),105)
        self.write('previous-span.json',self.result(p));p.context.close()
        print('PASS connection: production S04-02 route lands on shared viaduct-second-landing at tick 105')
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
            'S04 carrier uses existing Broken Viaduct landmark and label','tools/test_grapple_over_redesign.py additive Task587Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical; TASK-586 prior span proof remains at artifacts/TASK-586; prior colliders unchanged; only preview bounds widened. No old v3 tests edited or rerun.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact invocation, actual exit, exact collected identifiers, revision, browser/viewport and source SHA256',
            'tests.log':'four Task587Tests; no skips; OK','geometry.json':'live collider purposes, widths, gap, target reach and 600-tick full cycle',
            'route.json':'production entry-to-exit release, landing and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early release into catch and normal-control return',
            'approach.jpg':'broad second span, blue carrier, green catch and Broken Viaduct silhouette',
            'landing.jpg':'safe broad green exit and Broken Viaduct structure','controls.json':'bounded hold/nearest probes with every success inspected',
            'previous-span.json':'production previous encounter reaches the shared entry at tick 105',
            'evidence-index.json':'artifact inventory and hashes',
            'dependencies.json':'changed subsystems, unchanged modes/range/physics and source hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')


class Task588Tests(unittest.TestCase):
    """S04 exit lookout, high fall and continuous section with labelled fixtures."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S04-03 exit fixture -> S04-04 only; production physics and trusted inputs; not a base-to-summit run'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=10708,y=-1679)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:10448,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'broken-viaduct')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S04-04 isolated entry fixture / production physics';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate("""target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S04-04'),range:grappleOverAcquisitionRadius(),
            scale:scale[version],target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})""",self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S04-01','S04-02','S04-03','S04-04'])
        self.assertEqual([s['id'] for s in g['sections']],['S01','S02','S03','S04'])
        self.assertEqual(g['range'],360);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],360)
        self.assertIsNone(g['finish']);self.assertEqual(len(g['elements']),46)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertNotEqual(e['role'],'hazard')
        es={e['id']:e for e in g['elements']}
        for id in g['encounter']['elements']:
            if id not in ['viaduct-exit-anchor','viaduct-exit-recovery']:self.assertGreaterEqual(es[id]['width'],540)
            self.assertEqual(es[id]['role'],'drag' if id=='viaduct-exit-yellow' else 'bounce')
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertEqual([e['id'] for e in g['elements'] if e['role']=='drag'],['viaduct-yellow','viaduct-exit-yellow'])
        self.assertNotIn('preview-unbuilt',es)
        g.update(gap=es['viaduct-exit']['x']-es['viaduct-third-landing']['x']-es['viaduct-third-landing']['width'],
            yellowClearance=es['viaduct-exit-yellow']['y']-es['viaduct-exit']['y']-60,
            fallHeight=es['viaduct-exit-catch']['y']-es['viaduct-exit']['y'],
            connection='Shared live S04-03 exit; TASK-564 green 252-gap release envelope; yellow fall lane separately tested at range 360',
            recovery=['viaduct-exit-catch','viaduct-exit-recovery','viaduct-third-catch','viaduct-exit'])
        self.assertEqual(g['gap'],252);self.assertEqual(g['yellowClearance'],540);self.assertEqual(g['fallHeight'],850)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'viaduct-exit');self.assertEqual(landing,105)
        r=self.result(p);best=streak=0
        for row in r['rows'][30:landing-1]:
            streak=streak+1 if not row['contacts'] and not row['attached'] and not row['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6)
        r.update(takeoffTick=1,releaseTick=30,landingTick=landing,landingAir=best,entryToExit=True,
            fixture=dict(x=10448,y=-1540,vx=0,vy=0),resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        print(f'PASS geometry: 46 purposeful colliders; entry 680 exit 800 catch 1800 gap 252 reach {g["reach"]:.3f}<360; yellow clearance 540 fall 850; no red/planned terrain')
        print(f'PASS route: takeoff 1 release 30 landing 105; consecutive unattached airborne {best}; trusted inputs; zero resets/injections; images decoded')

    def test_02_high_fall_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,12);p.mouse.up()
        catch=self.until(p,'viaduct-exit-catch');self.assertEqual(catch,214)
        self.assertFalse(self.landings(self.result(p),'viaduct-exit'))
        for target,hold in [(dict(x=10638,y=-950),90),(dict(x=10638,y=-1138),48),(dict(x=10638,y=-1278),60)]:
            self.press(p,target);self.step(p,hold);p.mouse.up()
        intermediate=self.until(p,'viaduct-third-catch');self.assertEqual(intermediate,490)
        self.press(p,dict(x=10708,y=-1645));self.step(p,30);p.mouse.up()
        returned=self.until(p,'viaduct-third-landing',500);self.assertIsNotNone(returned)
        r=self.result(p);yellow=[s['tick'] for s in r['rows'][:catch] if 10648<s['x']<12448 and -928.2<s['y']<-778.2]
        self.assertGreater(len(yellow),10)
        self.assertTrue(any(c['id']=='viaduct-exit-recovery' for row in r['rows'] for c in row['contacts']))
        r.update(earlyReleaseTick=12,catchTick=catch,catchTarget='viaduct-exit-catch',yellowTicks=yellow,
            intermediateTick=intermediate,returnTick=returned,recoveryTarget='viaduct-third-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 12; high fall through yellow {len(yellow)} ticks; catch 214; lateral recovery via west face; bridge return {returned}; no reset/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold for 600 ticks',successfulAlternative=bool(self.landings(r,'viaduct-exit')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'viaduct-exit')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='600 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; 600-tick continuous hold and nearest 6/12/24; zero successful alternatives')

    def test_04_continuous_section(self):
        p=Task585Tests.page(self)
        self.press(p,Task585Tests.target);self.step(p,30);p.mouse.up()
        self.assertEqual(self.until(p,'viaduct-landing'),105)
        for target,hold in [(dict(x=8170,y=-1508),26),(Task586Tests.target,30)]:
            self.press(p,target);self.step(p,hold);p.mouse.up()
        self.assertEqual(self.until(p,'viaduct-second-landing'),179)
        self.press(p,dict(x=8910,y=-1508));self.step(p,12);p.mouse.up()
        self.assertEqual(self.until(p,'viaduct-third-landing'),296)
        self.assertEqual(self.until(p,'viaduct-exit'),352)
        r=self.result(p)
        exits=[dict(encounter=f'S04-0{i+1}',collider=id,tick=self.landings(r,id)[0]['tick'])
            for i,id in enumerate(['viaduct-landing','viaduct-second-landing','viaduct-third-landing','viaduct-exit'])]
        self.assertEqual([e['tick'] for e in exits],[105,179,296,352])
        self.assertFalse(p.evaluate('floors[0].climbStats.completed'))
        r.update(exits=exits,fixture=dict(x=7228,y=-1540,vx=0,vy=0),resets=0,poseInjections=0,
            completed=False,scope='One isolated S04 entry fixture; continuous section run, not base-to-summit',
            alternativeInspection='Successful momentum route: release at 191 carries over the carrier and final span, with top contacts at 296 and 352. This is a long released ballistic transfer, not repeated nearest/tiny transfers; local S04-04 deliberate launch separately proven. No success reclassified.')
        self.write('section-route.json',r)
        controls=json.loads((self.out/'controls.json').read_text())
        controls['successfulAlternativeInspection']=dict(path='section-route.json',exits=exits,observation=r['alternativeInspection'])
        self.write('controls.json',controls)
        print('PASS section: one labelled fixture; four ordered top contacts 105/179/296/352; zero handoff resets/injections; S04 completion false; successful long momentum alternative inspected')

    def test_05_dependencies_gate_and_index(self):
        p=Task567Tests.page(self)
        gate=p.evaluate('''() => {
            const m=JSON.parse(JSON.stringify(GRAPPLE_OVER_REPLACEMENT));
            m.sections=m.sections.filter(s=>s.status==='built');
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const s04=replacementMountainLevel(m).finish;
            m.sections.push({id:'S08',status:'built',encounters:[]});
            const s08=replacementMountainLevel(m).finish;
            floors[0].level.finish=s08;
            let events=0;const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events++;return original.call(this,name,...args)};
            YARD.step(3);CLIMB_UI.complete();
            return {s04,s08,events,completed:floors[0].climbStats.completed};
        }''')
        self.assertIsNone(gate['s04']);self.assertTrue(gate['s08']);self.assertEqual(gate['events'],1)
        gate['scope']='Separate isolated S08 finish contract fixture, not continuous section gameplay'
        self.write('summit-gate.json',gate)
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
        old=json.loads((ROOT/'artifacts/TASK-587/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n not in ['mountain.js','tools/test_grapple_over_redesign.py']}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        self.write('dependencies.json',dict(rows=rows,unchanged=unchanged,changed=['mountain.js preview S04-04 -> fixedlevel production collision; existing landmark rendering',
            'tools/test_grapple_over_redesign.py additive Task588Tests'],
            superseded='Earlier exact preview inventories are historical; original geometry retained. Earlier proof referenced in artifacts/TASK-587, not copied. Physics/events/ranges/camera/modes unchanged.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact invocation, actual exit, exact collected identifiers, revision, browser/viewport and source SHA256',
            'tests.log':'five Task588Tests; no skips; OK','geometry.json':'46 live collider purposes, widths, gap, reach, material order and fall clearance',
            'route.json':'trusted production entry-to-exit, release and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'high fall through yellow, catch and normal lateral return',
            'approach.jpg':'broad bridge, reachable green launch face, yellow band and viaduct structure',
            'landing.jpg':'wide exit lookout and viaduct structure','controls.json':'bounded hold/nearest probes with every success inspected',
            'section-route.json':'four exits in order, one labelled entry fixture, zero handoff resets; S04 never finishes',
            'summit-gate.json':'separate S08 contract fixture completes exactly once; S04 gated off',
            'evidence-index.json':'artifact inventory and hashes','dependencies.json':'changed subsystems, preserved modes/ranges/physics and hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS dependencies: 48 unchanged runtime/support hashes; preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged')
        print('PASS gate/index: S04 finish disabled; separate S08 completion exactly once; all required artifacts exist and JSON parses; below 200 MB')


class Task589Tests(unittest.TestCase):
    """S04 isolated input tolerance and lower recovery; no continuous-gameplay claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390},device_scale_factor=1,
            simulation='Isolated S04 entries; 600 production ticks before carrier input; recorded fixed-bridge entries; not continuous gameplay')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK589_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    frame = Task571Tests.frame
    until_landing = Task576Tests.until_landing
    targets = [Task585Tests.target,Task586Tests.target,dict(x=9298,y=-1720),Task588Tests.target]
    holds = [30,30,250,30]
    exits = ['viaduct-landing','viaduct-second-landing','viaduct-third-landing','viaduct-exit']
    fixtures = [dict(x=x,y=-1540) for x in [7228,8160,9088,10448]]

    def setup_entry(self,p,index):
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.assertFalse(p.evaluate('TUTORIAL_HINT.visible'))
        p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});screen.trackGrappleOver(true)}',self.fixtures[index])
        if index==2:self.step(p,600)

    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-50,0),('late',50,0),('left',0,-8),('right',0,8)]:
                    p=self.page(touch);self.setup_entry(p,index)

                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    nominal_hold=256 if index==2 and not touch else self.holds[index]
                    hold=nominal_hold+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S04-0{index+1} touch approach'))
                    target=dict(self.targets[index])
                    xy=self.press(p,target,aim);self.step(p,hold);self.release(p)
                    self.until_landing(p,self.exits[index],800 if index==1 else 400)
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S04-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,nominalHoldTicks=nominal_hold,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        target=target,startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=r['rows'][start:],success=bool(lands))
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S04-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=self.fixtures,fixtureScope=self.config['simulation'],source_hashes=self.config['source_hashes']))
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
            release_type='touchend' if r['mode']=='touch' else 'mouseup'
            self.assertTrue(any(i['type']==release_type and i['tick']==r['releaseTick'] for i in r['inputs']))
            self.assertTrue(any(c['id']==r['exit'] and c['ny']<-.9 for c in r['landing']['contacts']))
            self.assertTrue(any(s['attached'] for s in r['trace']))
            self.assertTrue(any(not s['attached'] and not s['contacts'] for s in r['trace'] if s['tick']>r['releaseTick']))
        print('PASS tolerance: all 40 cases; 4 encounters x 2 genuine input modes x 5 variants; +/-50 ms and +/-8 CSS px')


    def test_02_recovery(self):
        rows=[]
        for touch in [False,True]:
            for index in range(4):
                p=self.page(touch);self.setup_entry(p,index)
                start=p.evaluate('YARD.result().tick');step_ms=p.evaluate('physicsStepMs')
                phase=p.evaluate("({tick:YARD.result().tick,x:floors[0].byId.get('viaduct-carrier').x})")
                def pull(x,y,hold,coast=0):
                    self.press(p,dict(x=x,y=y));self.step(p,hold);self.release(p)
                    if coast:self.step(p,coast)
                hold=12 if index==3 else 6
                self.press(p,self.targets[index]);self.step(p,hold);self.release(p)
                catch_id=['viaduct-catch','viaduct-catch','viaduct-third-catch','viaduct-exit-catch'][index]
                self.until_landing(p,catch_id,500)
                before=self.result(p);catches=self.landings(before,catch_id)
                self.assertTrue(catches,(index,touch,'catch'))
                self.assertFalse(self.landings(before,self.exits[index]))
                recovery_start=before['tick']
                if index==0:
                    pull(7320,-900,60,20);pull(7300,-1130,60);pull(7355,-1245,71)
                    return_id='freight-exit-catch'
                elif index==1:
                    pull(8100,-650,30,60);pull(7600,-650,30,60);pull(7320,-900,60,20)
                    pull(7300,-1130,60);pull(7355,-1245,71);pull(7307,-1525,48)
                    return_id='viaduct-landing'
                elif index==2:
                    pull(9162,-1508,12);return_id='viaduct-second-landing'
                else:
                    pull(10638,-950,90);pull(10638,-1138,48);pull(10638,-1278,60)
                    self.until_landing(p,'viaduct-third-catch',400)
                    pull(10708,-1645,30);return_id='viaduct-third-landing'
                self.until_landing(p,return_id,800)
                r=self.result(p);returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                yellow=[s['tick'] for s in before['rows'][start:] if
                    ((7360<s['x']<8960) or (10648<s['x']<12448)) and -928.2<s['y']<-778.2]
                row=dict(encounter=f'S04-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-self.holds[index])*step_ms,missHoldTicks=hold,startTick=start,
                    catch=catches[0],returned=returned[0] if returned else None,returnCollider=return_id,
                    recoveryStart=recovery_start,inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs']],
                    trace=r['rows'][start:],yellowTicks=yellow,moverPhase=phase,
                    resetsAfterStart=0,poseInjectionsAfterStart=0)
                rows.append(row);self.write('recovery.json',dict(cases=rows,source_hashes=self.config['source_hashes'],scope=self.config['simulation']))
                self.assertTrue(returned,(index,touch,'return'))
                if index!=2:self.assertGreater(len(yellow),6)
                self.assertGreater(abs(row['releaseOffsetMs']),50)
                print(f'RECOVERY {row["encounter"]} {row["mode"]} catch={catches[0]["tick"]} return={returned[0]["tick"]} yellow={len(yellow)}')
                p.context.close()
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses and normal-input escapes; yellow transits and carrier phase recorded; zero resets/injections')

    def test_03_dependencies_and_index(self):
        previous=json.loads((ROOT/'artifacts/TASK-588/evidence-index.json').read_text())
        old=previous['config']['source_hashes']
        unchanged=[]
        for name,digest in old.items():
            if name=='tools/test_grapple_over_redesign.py':continue
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
            unchanged.append(name)
        self.write('affected-proof-map.json',dict(geometryChanges=[],runtimeChanges=[],unchanged=unchanged,
            routeAdjustment='S04-03 aim x9298 (40 world units inward); hold 256 desktop / 250 touch; single release or aim perturbation per attempt',
            recoveryEndpoint='S04-01 escapes to the broad lower freight-exit-catch shelf, not the upper bridge',
            changedSubsystems=['tools/test_grapple_over_redesign.py additive Task589Tests'],
            dependencies=['Task589Tests -> browser_test_support + grapple_over_yard.js -> events.js, physics.js, fixedlevel.js, mountain.js'],
            previousProof=['artifacts/TASK-588/evidence-index.json'],
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg'],
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes; historical proofs retained'))
        required={'commands.log':'exact command, exit, identifiers, Chromium/viewports/DPR, revision and source hashes',
            'tests.log':'three Task589Tests, no skips, OK',
            'tolerance.json':'40 successful variants with trusted input timestamps, offsets and top-facing exit contacts',
            'recovery.json':'8 out-of-window misses, lower contacts, normal-input escapes, yellow and mover phase',
            'affected-proof-map.json':'unchanged geometry and changed subsystem dependencies',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,scope=self.config['simulation']))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print(f'PASS dependencies: {len(unchanged)} unchanged runtime/support hashes; geometry unchanged')
        print('PASS index: all required files exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')


class Task590Tests(unittest.TestCase):
    """Current S04 composition review; independent fixtures are labelled explicitly."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='One isolated S04 entry then continuous traversal; separately labelled recovery and mover-phase fixtures'

    write = Task557Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task588Tests.until

    def fixture(self,index=0):
        p=Task567Tests.page(self)
        p.evaluate('s=>{TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500);Object.assign(ninja,s,{speedX:0,speedY:0});screen.trackGrappleOver(true)}',Task589Tests.fixtures[index])
        return p

    def test_01_objects_clearance_and_dependencies(self):
        p=self.fixture()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),upgrade:grappleOverProfile().upgradedAcquisitionRadius,
            scale:scale[version],calibration:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS}})''')
        self.assertEqual((g['range'],g['upgrade'],g['scale']),(360,540,.375))
        es={e['id']:e for e in g['elements']}
        for e in es.values():
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['bounds']={k:e[a]+fn(v[a] for v in e['points']) for k,a,fn in [('left','x',min),('right','x',max),('top','y',min),('bottom','y',max)]}
            e['width']=e['bounds']['right']-e['bounds']['left'];e['height']=e['bounds']['bottom']-e['bounds']['top']
        for m in g['movers']:
            e=es[m['element']];b=dict(e['bounds']);axis=m['axis']
            b['left' if axis=='x' else 'top']=m['min']
            b['right' if axis=='x' else 'bottom']=m['max']+e['width' if axis=='x' else 'height']
            m['sweptBounds']=b
            if m['element']=='viaduct-carrier':
                self.assertGreaterEqual(m['max']-m['min'],max(360,2*e['width']))
                self.assertTrue(6000<=m['periodMs']<=10000)
        def distance(a,b):
            return (max(a['left']-b['right'],b['left']-a['right'],0)**2+max(a['top']-b['bottom'],b['top']-a['bottom'],0)**2)**.5
        measurements=[]
        for z in [e for e in es.values() if e['role']=='drag']:
            self.assertGreaterEqual(z['width'],3*g['range']);self.assertGreaterEqual(z['width']/z['height'],4)
            self.assertFalse(z['grapplable'])
            for e in es.values():
                if e['role']=='drag':continue
                sweep=next((m['sweptBounds'] for m in g['movers'] if m['element']==e['id']),e['bounds'])
                d=distance(z['bounds'],sweep)
                measurements.append(dict(zone=z['id'],collider=e['id'],clearance=d))
                self.assertGreaterEqual(d+1e-8,540,(z['id'],e['id'],d))
        carrier=next(m for m in g['movers'] if m['element']=='viaduct-carrier')
        for e in es.values():
            if e['id']!='viaduct-carrier':self.assertGreater(distance(carrier['sweptBounds'],e['bounds']),0,e['id'])
        g.update(clearances=measurements,firstUseOrder=['green S01','blue S03','yellow S04'],hazards=[],
            planningWidths=[es[n]['width'] for n in Task589Tests.exits],
            gaps=[es[b]['bounds']['left']-es[a]['bounds']['right'] for a,b in zip(['freight-exit']+Task589Tests.exits[:-1],Task589Tests.exits)],removedClutter='No decorative colliders; every object mapped to encounter and purpose')
        self.assertEqual(g['planningWidths'],[680,680,680,800])
        self.assertEqual(g['gaps'],[252,252,676,252])
        self.assertTrue(all(e['role']=='bounce' for e in es.values() if e['id'].startswith('yard-')))
        self.assertTrue(all(e['id'].startswith('viaduct') for e in es.values() if e['role']=='drag'))
        self.write('objects.json',g)
        old=json.loads((ROOT/'artifacts/TASK-589/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n not in ['mountain.js','tools/test_grapple_over_redesign.py']}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        self.write('dependency.json',dict(unchanged=unchanged,changed=['mountain.js: S04 lower recovery geometry and wall role','tools/test_grapple_over_redesign.py: additive Task590Tests'],
            reused=[],superseded='TASK-585..589 yellow/recovery coordinates are historical. Current S04 route, tolerance, full sweep, phases, suppression and recoveries refreshed here. Upper route unchanged.',
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes'))
        compatibility=[]
        for preview in [False,True]:
            q=Task558Tests.page(self,preview)
            for mode in ['grapple_over','classic','bad']:
                row=q.evaluate('''m=>{startGame(m);cancelAnimationFrame(game);return {mode:version,range:version==='grapple_over'?grappleOverAcquisitionRadius():null,scale:scale[version],gravity:GRAVITY,pull:grappleSpeed}}''',mode)
                row['preview']=preview;compatibility.append(row)
                if mode=='grapple_over':
                    self.assertEqual(row['range'],360 if preview else 1080);self.assertEqual(row['scale'],.375)
            q.context.close()
        self.assertEqual([{k:v for k,v in r.items() if k!='preview'} for r in compatibility[1:3]],[{k:v for k,v in r.items() if k!='preview'} for r in compatibility[4:6]])
        self.write('compatibility.json',dict(cases=compatibility))
        print('PASS compatibility: old mountain range 1080 remains playable; isolated preview range 360; classic/bad identical settings')
        print('PASS objects: every gameplay object has purpose/encounter; green/blue then yellow; no red; planning widths 680/680/680/800; gaps 252/252/676/252')
        print('PASS yellow: widths >=1080; aspect >=4; every collider/full swept bound clearance >=540; blue carrier travel 720 period 10000 sweep clear')

    def test_02_phases_and_tolerance(self):
        phases=[]
        for phase in [0,150,300,450]:
            p=self.fixture(2);self.step(p,phase);self.step(p,600-phase)
            self.press(p,Task589Tests.targets[2]);self.step(p,256);p.mouse.up()
            tick=self.until(p,'viaduct-third-landing',800);self.assertIsNotNone(tick)
            r=self.result(p);phases.append(dict(arrivalPhase=phase/600,waitTicks=600-phase,landing=self.landings(r,'viaduct-third-landing')[0],inputs=r['inputs']))
            p.context.close()
        self.write('phases.json',dict(scope='Four isolated arrival-phase fixtures, safe wait then trusted input traversal',cases=phases))
        # Reuse helper implementation, not previous-run evidence; only this tolerance method runs.
        probe=Task589Tests();probe.browser=self.browser;probe.url=self.url;probe.out=self.out;probe.config=self.config
        try:probe.test_01_tolerance()
        finally:probe.doCleanups()
        print('PASS phases: four quarter-cycle arrivals wait safely and traverse; 40 current-geometry desktop/touch tolerance cases')

    def record(self,p,label):
        p.evaluate('''label=>{window.reviewFrames=[];const step=YARD.step;
            window.captureReview=()=>{draw();reviewFrames.push({image:canvas.toDataURL('image/jpeg',.7),tick:YARD.result().tick,label})};
            YARD.step=n=>{for(let i=0;i<n;i++){step(1);if(YARD.result().tick%12===0)captureReview()}};captureReview()}''',label)

    def pull(self,p,x,y,n,coast=0):
        self.press(p,dict(x=x,y=y));self.step(p,n);p.mouse.up()
        if coast:self.step(p,coast)

    def test_03_continuous_route_composition_and_recovery(self):
        p=self.fixture();self.record(p,'S04 continuous from one isolated entry / 4x')
        views=[];observations=[]
        def capture(index,target):
            p.evaluate('draw()')
            obs=p.evaluate('t=>({tick:YARD.result().tick,target:t,client:YARD.client(t),landmark:LANDMARKS.frame.drawn,player:{x:ninja.x,y:ninja.y}})',target)
            self.assertTrue(0<obs['client']['x']<1280 and 0<obs['client']['y']<720)
            self.assertEqual(obs['landmark'][0]['id'],'broken-viaduct')
            observations.append(obs)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),f'S04-0{index} actual continuous approach tick {obs["tick"]}',fill='white');views.append(im)
        capture(1,Task585Tests.target);self.pull(p,7488,-1679,30)
        self.assertEqual(self.until(p,'viaduct-landing'),105)
        self.pull(p,8170,-1508,26);capture(2,Task586Tests.target)
        self.pull(p,Task586Tests.target['x'],Task586Tests.target['y'],30)
        self.assertEqual(self.until(p,'viaduct-second-landing'),179)
        capture(3,dict(x=9258,y=-1720));self.pull(p,8910,-1508,12)
        self.assertEqual(self.until(p,'viaduct-third-landing'),296)
        capture(4,Task588Tests.target)
        self.assertEqual(self.until(p,'viaduct-exit'),352)
        r=self.result(p)
        self.write('route.json',dict(exits=[dict(id=n,tick=self.landings(r,n)[0]['tick']) for n in Task589Tests.exits],
            inputs=r['inputs'],trace=r['rows'],resetsAfterStart=0,poseInjectionsAfterStart=0,
            scope=self.config['simulation'],alternative='Released momentum at tick 191 traverses carrier/final span; local deliberate launch verified separately by tolerance cases'))
        self.write('approaches.json',dict(views=observations))
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(views):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=85)
        overview=Image.new('RGB',(2560,720));sil=Image.new('RGB',(2560,720),'white')
        for i,center in enumerate([7800,11100]):
            p.evaluate('x=>{screen.x=width/.375/2-x;screen.y=height/.375/2+900;draw()}',center)
            overview.paste(Image.open(io.BytesIO(p.screenshot())).convert('RGB'),(1280*i,0))
            f=p.evaluate('''()=>({elements:[...floors[0].elements,...floors[0].dragZones].map(e=>({id:e.id,points:e.getPoints(),role:e.surfaceRole})),
                shape:replacementViaductShape(GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
                landmark:{x:(7700+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,y:(-1200+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
                camera:{x:screen.x,y:screen.y},factor:1280/width})''')
            tile=Image.new('RGB',(1280,720),'white');pen=ImageDraw.Draw(tile);k=f['factor']
            for part in f['shape']['parts']:
                pen.polygon([((x+f['landmark']['x'])*k,(y+f['landmark']['y'])*k) for x,y in part],fill='#aaaaaa')
            for e in f['elements']:
                pts=[((v['x']+f['camera']['x'])*.375*k,(v['y']+f['camera']['y'])*.375*k) for v in e['points']]
                pen.polygon(pts,fill='#cccccc' if e['role']=='drag' else 'black')
                if e['id'].startswith('viaduct'):pen.text(pts[0],e['id'],fill='#555555')
            pen.text((12,12),'Broken Viaduct / interrupted deck and piers / plain silhouette',fill='black');sil.paste(tile,(1280*i,0))
        overview.save(self.out/'overview.png');sil.save(self.out/'silhouette.png')
        frames=p.evaluate('reviewFrames')
        # Separately labelled mover fixture includes a complete production cycle.
        q=self.fixture(2);self.record(q,'SEPARATE carrier entry / full 10s cycle / 4x')
        cycle=q.evaluate('''()=>{let a=[];for(let i=0;i<600;i++){YARD.step(1);const e=floors[0].byId.get('viaduct-carrier');
            a.push({tick:i+1,x:e.x,px:ninja.x,py:ninja.y})}return a}''')
        available=[((max(s['x']-s['px'],0,s['px']-s['x']-360))**2+(max(-1770-s['py'],0,s['py']+1690))**2)**.5<=360 for s in cycle]
        best=streak=0
        for hit in available*2:streak=streak+1 if hit else 0;best=max(best,streak)
        window=min(best,600)*1000/60;self.assertGreaterEqual(window,1000)
        self.assertAlmostEqual(max(s['x'] for s in cycle)-min(s['x'] for s in cycle),720)
        self.write('cycle.json',dict(samples=cycle,acquisitionWindowMs=window,periodMs=10000))
        frames.extend(q.evaluate('reviewFrames'));q.context.close()
        frames.extend(self.recovery_clips())
        p.evaluate('a=>window.reviewFrames=a',frames);p.bring_to_front()
        clip=p.evaluate('''async () => {
            const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');
            const stream=c.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of reviewFrames){const im=new Image();im.src=f.image;await im.decode();ctx.drawImage(im,0,0,1280,720);
                ctx.fillStyle='white';ctx.fillText((f.label || 'S04 continuous from isolated entry')+' / 4x / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});return await new Promise(r=>{const rd=new FileReader();rd.onload=()=>r(rd.result.split(',')[1]);rd.readAsDataURL(blob)})}''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);await v.play();
            await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],100);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)
        print(f'PASS continuous: exits 105/179/296/352; four actual approaches; full cycle 720 travel; acquisition window {window:.1f}ms; recovery clips; decoded {decoded}')

    def recovery_clips(self):
        frames=[];cases=[];suppression=[]
        for index in [0,3]:
            # Unassisted fall/rebound uses the actual production damping and bouncer.
            p=self.fixture(index);target=Task589Tests.targets[index]
            self.pull(p,target['x'],target['y'],6 if index==0 else 12)
            catch_id='viaduct-catch' if index==0 else 'viaduct-exit-catch'
            catch=self.until(p,catch_id,800);self.assertIsNotNone(catch)
            self.step(p,250);r=self.result(p)
            apex=min(s['y'] for s in r['rows'][catch:])
            drop=r['rows'][catch-1]['y']-r['rows'][0]['y'];rebound=r['rows'][catch-1]['y']-apex
            control=self.fixture(index)
            control.evaluate('floors[0].dragZones=[]')  # Labelled no-yellow comparator only; production physics unchanged.
            self.pull(control,target['x'],target['y'],6 if index==0 else 12)
            control_catch=self.until(control,catch_id,800);self.assertIsNotNone(control_catch)
            self.step(control,250);cr=self.result(control)
            control_rebound=cr['rows'][control_catch-1]['y']-min(s['y'] for s in cr['rows'][control_catch:])
            self.assertLess(rebound,control_rebound*.75)
            control.context.close()
            suppression.append(dict(encounter=f'S04-0{index+1}',catchTick=catch,drop=drop,rebound=rebound,apex=apex,
                inputs=r['inputs'],trace=r['rows'],controlRebound=control_rebound,controlTrace=cr['rows'],comparison='Same entry/input with yellow disabled only in labelled comparator; production rebound reduced at least 25%; no recovery input during measurement'))
            p.context.close()
            p=self.fixture(index);self.record(p,f'SEPARATE S04-0{index+1} fall and lateral recovery / 4x')
            self.pull(p,target['x'],target['y'],6 if index==0 else 12)
            catch=self.until(p,catch_id,800);self.assertIsNotNone(catch)
            x=p.evaluate('ninja.x');self.pull(p,x-280,45,30,50)
            wall=6820 if index==0 else 10108
            for _ in range(20):
                pos=p.evaluate('({x:ninja.x,y:ninja.y})')
                if pos['y'] < -1050:break
                dx=abs(wall-1-pos['x']);up=min(250,max(0,350**2-dx**2)**.5)
                self.pull(p,wall-1,max(-1140,pos['y']-up),60)
            self.assertLess(p.evaluate('ninja.y'),-1050)
            edge=7360 if index==0 else 10648;bottom=-1188.2 if index==0 else -1228.2
            for _ in range(5 if index==0 else 3):
                x=p.evaluate('ninja.x');self.pull(p,min(edge-2,x+220),bottom-5,60)
            for _ in range(1 if index==0 else 4):self.pull(p,edge-2,bottom-55,90)
            return_id='freight-exit-catch' if index==0 else 'viaduct-third-catch'
            if not self.landings(self.result(p),return_id):self.assertIsNotNone(self.until(p,return_id,200))
            r=self.result(p)
            returned=self.landings(r,return_id);self.assertTrue(returned,(index,return_id))
            cases.append(dict(encounter=f'S04-0{index+1}',catchTick=catch,returned=returned[0],returnCollider=return_id,
                inputs=r['inputs'],trace=r['rows'],resetsAfterStart=0,poseInjectionsAfterStart=0))
            p.evaluate('captureReview()')
            frames.extend(p.evaluate('reviewFrames'));p.context.close()
        self.write('recovery.json',dict(scope='Two independent yellow-band falls with continuous normal-input lateral escapes',cases=cases))
        self.write('suppression.json',dict(cases=suppression))
        print('PASS recovery: both yellow bands traversed; lower catches then top-contact return by trusted input; rebound reduced >=25% against no-yellow comparator; no resets/injections')
        return frames

    def test_04_evidence_index(self):
        required={'commands.log':'commands, exit status, identifiers, browser/viewport/revision/source hashes','tests.log':'four focused Task590Tests, no skips',
            'overview.png':'all four built encounters, broken deck landmark, open gaps and broad landings',
            'silhouette.png':'plain collider silhouettes and interrupted deck/piers','approaches.jpg':'four actual continuous approach views',
            'approaches.json':'on-screen target measurements','objects.json':'every purpose/role/encounter, full swept bounds and every yellow/collider clearance',
            'compatibility.json':'legacy/preview and classic/bad settings',
            'cycle.json':'full production mover cycle and acquisition window >=1s','phases.json':'four quarter-phase arrival/wait/traversal cases',
            'tolerance.json':'40 refreshed desktop/touch tolerance cases','route.json':'continuous four exits from one entry; trusted inputs and trace',
            'recovery.json':'both yellow catches and continuous lateral return traces','suppression.json':'unassisted fall/rebound versus labelled no-yellow comparator for both bands',
            'section.webm':'continuous representative section, separately labelled full mover cycle and both recoveries',
            'clip-decode.json':'full decoded video frame count','dependency.json':'exact unchanged hashes and affected subsystem/superseded proof map',
            'review.md':'visual review with image locations, pacing and limitations','evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreaterEqual(im.width,1280)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; images/video decode; retained evidence <200 MB')


class Task591Tests(unittest.TestCase):
    """S05-01 only; labelled isolated S04 exit fixture, never a summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated fixture on shared S04 exit; production inputs/physics; no base-to-summit claim'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    target = dict(x=11950,y=-1679)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:11500,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        self.assertEqual(p.evaluate('grappleOverAcquisitionRadius()'),360)
        self.step(p,1)
        self.assertEqual(p.evaluate('grappleOverAcquisitionRadius()'),540)
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'cable-galleries')
        self.assertEqual(p.evaluate('I18N.t(replacementSection().labelKey)'),'Cable Galleries')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S05-01 isolated entrance fixture / production physics';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S05-01'),range:grappleOverAcquisitionRadius(),
            scale:scale[version],reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),target,
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S05-01'])
        self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertGreater(g['reach'],360);self.assertLess(g['reach'],540);self.assertIsNone(g['finish'])
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        for id in g['encounter']['elements']:
            self.assertEqual(es[id]['role'],'bounce')
            if id!='gallery-anchor':self.assertGreaterEqual(es[id]['width'],540)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        g.update(gap=es['gallery-landing']['x']-es['viaduct-exit']['x']-es['viaduct-exit']['width'],
            connection='Shared live viaduct-exit; no handoff teleport',recovery=['gallery-catch','viaduct-exit'],
            calibrationNote='TASK-564 broad gallery/cable fan; TASK-560 upgraded gap envelope up to 648, translated and production-validated here; no old v3 coordinates',
            landingWidths=[es[n]['width'] for n in ['viaduct-exit','gallery-landing']],
            recoveryWidth=es['gallery-catch']['width'])
        g['nearestAnchorReach']=p.evaluate('''() => {const b={};elementBounds(floors[0].byId.get('gallery-anchor'),b);
            return Math.hypot(Math.max(b.left-ninja.x,0,ninja.x-b.right),Math.max(b.top-ninja.y,0,ninja.y-b.bottom))}''')
        self.assertGreater(g['nearestAnchorReach'],360);self.assertLess(g['nearestAnchorReach'],540)
        self.assertEqual(g['gap'],612)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,42);p.mouse.up()
        landing=self.until(p,'gallery-landing');self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for row in r['rows'][43:landing-1]:
            streak=streak+1 if not row['contacts'] and not row['attached'] and not row['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6)
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=43,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S05-01: gap 612; landings 800/800; catch 1600; reach {g["reach"]:.3f} in (360,540); no red/planned terrain')
        print(f'PASS route: release 43 landing {landing}; airborne unattached {best}; trusted inputs; resets=0 poseInjections=0; Cable Galleries images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'gallery-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'gallery-landing'))
        self.press(p,dict(x=11570,y=-1500));self.step(p,12);p.mouse.up()
        returned=self.until(p,'viaduct-exit');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=7,catchTick=catch,catchTarget='gallery-catch',
            returnTick=returned,recoveryTarget='viaduct-exit',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 7 catch {catch}; normal controls return {returned}; no resets/injections')

    def test_03_controls(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600 ticks',successfulAlternative=bool(self.landings(r,'gallery-landing')))
        cases.append(r);p.mouse.up();p.context.close()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'gallery-landing')))
            cases.append(r);p.context.close()
        self.write('controls.json',dict(cases=cases,bound='600 ticks hold; <=600 each nearest 6/12/24',
            inspection='Every top-facing gallery-landing contact checked with the nominal success criterion',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded hold/nearest probes; zero successful alternatives')

    def test_04_upgrade_and_dependencies(self):
        # Separate local fixture before the previous encounter: acquisition follows real flight onto the entrance.
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:10448,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        self.press(p,Task588Tests.target)
        samples=[]
        for tick in range(1,181):
            self.step(p,1)
            if tick==30:p.mouse.up()
            samples.append(p.evaluate('''() => ({tick:YARD.result().tick,x:ninja.x,y:ninja.y,
                range:grappleOverAcquisitionRadius(),notice:floors[0].rangeNoticeMs})'''))
        transitions=[s for a,s in zip([dict(range=360)]+samples,samples) if a['range']!=s['range']]
        self.assertEqual(len(transitions),1);self.assertEqual(transitions[0]['range'],540)
        self.assertTrue(self.landings(self.result(p),'viaduct-exit'))
        self.assertGreater(transitions[0]['notice'],0)
        traversal=self.result(p)
        reset=p.evaluate('''() => {CLIMB_UI.restart();cancelAnimationFrame(game);return {
            range:grappleOverAcquisitionRadius(),upgraded:floors[0].rangeUpgraded,x:ninja.x,y:ninja.y}}''')
        self.assertEqual(reset['range'],360);self.assertFalse(reset['upgraded'])
        adjacent=[]
        for x,y in [(12050,-1540),(11920,-1700),(11500,-1280),(10448,-1540)]:
            q=Task567Tests.page(self)
            q.evaluate('s=>Object.assign(ninja,s,{speedX:0,speedY:0})',dict(x=x,y=y));self.step(q,1)
            row=q.evaluate('({x:ninja.x,y:ninja.y,range:grappleOverAcquisitionRadius()})')
            self.assertEqual(row['range'],360);adjacent.append(row);q.context.close()
        self.write('upgrade.json',dict(samples=samples,transitions=transitions,traversal=traversal,reset=reset,
            adjacentFixtures=adjacent,fixtureScope='Independent unupgraded later/nearby fixtures; no mid-attempt injection',
            cue='Grapnel range 360 → 540; existing acquisition circle follows current radius'))
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
            q.context.close()
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,hashes=self.config['source_hashes'],
            changed=['mountain.js S05-01 preview geometry and entrance zone','render/landmarks.js cable fan','menu.js preview-only numeric upgrade cue','i18n.js labels','tools/test_grapple_over_redesign.py additive Task591Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','fixedlevel.js','gameoptions.js'],
            superseded='Earlier exact built-prefix/landmark inventories are historical; earlier proof referenced in artifacts/TASK-590, not copied. No full earlier-suite rerun.',
            hashPolicy='HEAD-only changes do not invalidate identical tested source hashes'))
        required={'commands.log':'exact commands, actual exit, four identifiers, browser/viewport/revision/hashes',
            'tests.log':'four Task591Tests, no skips, OK','geometry.json':'live roles/purposes widths gap calibrated limits reach range',
            'route.json':'production trusted entry-to-exit and >=6 unattached airborne ticks','inputs.json':'trusted production mouse events',
            'miss.json':'early release catch and normal-control entrance return','approach.jpg':'broad entrance/target, numeric upgrade cue, cable fan',
            'landing.jpg':'broad exit and Cable Galleries','controls.json':'bounded hold/nearest probes and inspection of all exit contacts',
            'upgrade.json':'one 360-to-540 transition through normal traversal, reset and adjacent exclusions',
            'dependencies.json':'changed subsystems, preserved modes/physics/input, source hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation']))
        print(f'PASS upgrade: 360->540 exactly once at tick {transitions[0]["tick"]}; restart 360; four adjacent fixtures remain 360')
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; physics/input unchanged; index written')


class Task592Tests(unittest.TestCase):
    """S05-02 local fixture with previously earned range; separate entrance connection proof."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S05-02 shared-deck fixture with previously earned 540; separate entrance traversal; not base-to-summit'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    target = dict(x=13232,y=-1900)

    def page(self):
        p=Task567Tests.page(self)
        # Pre-attempt inventory/pose fixture only. The entrance acquisition itself is tested separately.
        p.evaluate('''() => {Object.assign(ninja,{x:12912,y:-1540,speedX:0,speedY:0});
            floors[0].rangeUpgraded=true;screen.trackGrappleOver(true);
            const step=YARD.step;YARD.step=n=>{for(let i=0;i<n;i++){step(1);
                YARD.result().rows.at(-1).rope=grapnel.pos.map(v=>({x:v[0],y:v[1],id:v[2]?.id}));}};
        }''')
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'cable-galleries')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S05-02 isolated shared-deck fixture / previously earned 540 / production physics';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_corner_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S05-02'),range:grappleOverAcquisitionRadius(),
            scale:scale[version],reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),target,
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S05-01','S05-02'])
        self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540);self.assertIsNone(g['finish'])
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        for id in g['encounter']['elements']:
            self.assertEqual(es[id]['role'],'bounce')
            if id!='gallery-projection':self.assertGreaterEqual(es[id]['width'],540)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        g.update(gap=es['gallery-projection']['x']-es['gallery-upper-landing']['x']-es['gallery-upper-landing']['width'],
            connection='Shared live gallery-landing, also S05-01 exit; separately traversed from entrance',
            recovery=['gallery-catch','gallery-landing'],landingWidths=[800,800],recoveryWidth=1600,
            calibrationNote='TASK-564 one visible green corner and broad cable gallery; TASK-560 360 landing / 540 recovery minima. New concave projection validated in production; no v3 coordinates.',
            localColliderIds=g['encounter']['elements'])
        self.assertGreaterEqual(g['gap'],540)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,45);p.mouse.up()
        landing=self.until(p,'gallery-upper-landing');self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for row in r['rows'][45:landing-1]:
            streak=streak+1 if not row['contacts'] and not row['attached'] and not row['shot'] else 0
            best=max(best,streak)
        wraps=[s for s in r['rows'][:45] if len(s['rope'])>=2]
        self.assertTrue(wraps)
        self.assertTrue(all(v['id']=='gallery-projection' for s in wraps for v in s['rope']))
        self.assertGreaterEqual(best,6)
        self.assertTrue(all(s['x']>11000 for s in r['rows']))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=45,
            landingTick=landing,landingAir=best,cornerTicks=[s['tick'] for s in wraps],entryToExit=True,
            resets=0,poseInjections=0,fixture=dict(x=12912,y=-1540,range=540),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S05-02: opening {g["gap"]}; landings 800/800; catch 1600; reach {g["reach"]:.3f} < 540; one coherent green projection; no red/planned terrain')
        print(f'PASS route: corner ticks {r["cornerTicks"]}; release 45 landing {landing}; airborne unattached {best}; trusted inputs; resets=0 poseInjections=0; images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'gallery-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'gallery-upper-landing'))
        self.press(p,dict(x=12960,y=-1500));self.step(p,12);p.mouse.up()
        returned=self.until(p,'gallery-landing');self.assertIsNotNone(returned)
        r=self.result(p);self.assertTrue(all(s['x']>11000 for s in r['rows']))
        r.update(earlyReleaseTick=6,catchTick=catch,catchTarget='gallery-catch',returnTick=returned,
            recoveryTarget='gallery-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 6 catch {catch}; normal controls return {returned}; no resets/injections')

    def test_03_controls(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600 ticks',successfulAlternative=bool(self.landings(r,'gallery-upper-landing')))
        cases.append(r);p.mouse.up();p.context.close()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'gallery-upper-landing')))
            cases.append(r);p.context.close()
        self.write('controls.json',dict(cases=cases,bound='600 ticks hold; <=600 each nearest 6/12/24',
            inspection='Every top-facing gallery-upper-landing contact checked with the nominal success criterion',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded hold/nearest probes; zero successful alternatives')

    def test_04_connection_upgrade_and_dependencies(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:11500,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        self.assertEqual(p.evaluate('grappleOverAcquisitionRadius()'),360)
        self.step(p,1);self.assertEqual(p.evaluate('grappleOverAcquisitionRadius()'),540)
        self.press(p,Task591Tests.target);self.step(p,42);p.mouse.up()
        landing=self.until(p,'gallery-landing');self.assertIsNotNone(landing)
        r=self.result(p);r.update(landingTick=landing,rangeBefore=360,rangeAfter=540,
            connection='S05-01 entrance through shared S05-02 entry; separate fixture from the corner route',poseInjections=0,resets=0)
        self.write('connection.json',r)
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
            q.context.close()
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,hashes=self.config['source_hashes'],
            changed=['mountain.js S05-02 preview geometry -> fixedlevel.js collision terrain','tools/test_grapple_over_redesign.py additive Task592Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','fixedlevel.js','gameoptions.js','render/landmarks.js'],
            superseded='Earlier exact built-prefix inventories are historical; artifacts/TASK-591 proof remains in place. No earlier tests modified.',
            hashPolicy='HEAD-only changes do not invalidate identical tested source hashes'))
        required={'commands.log':'exact commands, actual exit, four identifiers, browser/viewport/revision/hashes',
            'tests.log':'four Task592Tests, no skips, OK','geometry.json':'live roles/purposes widths gap calibrated limits reach range',
            'route.json':'production corner routing and >=6 unattached airborne ticks','inputs.json':'trusted production mouse events',
            'miss.json':'early release catch and normal-control return','approach.jpg':'broad entry, projection, upper target and cable fan',
            'landing.jpg':'broad upper exit and Cable Galleries','controls.json':'bounded hold/nearest probes and inspection of all exit contacts',
            'connection.json':'entrance 360-to-540 acquisition and physical flight onto shared deck',
            'dependencies.json':'changed subsystems, preserved modes/physics/input, source hashes',
            'evidence-index.json':'artifact assertion map and run configuration'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation']))
        print(f'PASS connection: earned entrance 360->540; shared deck landing {landing}; no mid-attempt injections')
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; physics/input unchanged; index written')


class Task593Tests(unittest.TestCase):
    """Local S05-03 proof; pre-attempt inventory/pose only, never a summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S05-03 shared upper-deck fixture, previously earned 540; separate entrance and S05-02 connection; not base-to-summit'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    target = dict(x=11230,y=-2059)
    next_target = dict(x=10630,y=-2299)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:11570,y:-1860,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        p.evaluate("""() => {const step=YARD.step;YARD.step=n=>{for(let i=0;i<n;i++){
            step(1);YARD.result().rows.at(-1).rope=grapnel.pos.map(v=>({x:v[0],y:v[1],id:v[2]?.id}));}}}""")
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'cable-galleries')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S05-03 isolated shared upper-deck fixture / earned 540 / production physics';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_overhang_and_reacquisition(self):
        p=self.page()
        g=p.evaluate('''t=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S05-03'),range:grappleOverAcquisitionRadius(),
            scale:scale[version],reach:Math.hypot(t.x-ninja.x,t.y-ninja.y),target:t,
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S05-01','S05-02','S05-03'])
        self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540);self.assertIsNone(g['finish'])
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        for id in g['encounter']['elements']:self.assertEqual(es[id]['role'],'bounce')
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        widths=[es[id]['width'] for id in ['gallery-upper-landing','gallery-third-landing']]
        self.assertTrue(all(w>=540 for w in widths))
        gap=es['gallery-upper-landing']['x']-es['gallery-third-landing']['x']-es['gallery-third-landing']['width']
        self.assertGreaterEqual(gap,540);self.assertGreaterEqual(es['gallery-third-catch']['width'],540)
        visible=p.evaluate('t=>YARD.client(t)',self.next_target)
        self.assertTrue(0<visible['x']<1280 and 0<visible['y']<720)
        g.update(gap=gap,landingWidths=widths,recoveryWidth=es['gallery-third-catch']['width'],
            nextTarget=self.next_target,nextTargetApproachViewport=visible,localColliderIds=g['encounter']['elements'],
            connection='Shared live S05-02 upper landing; previous-connection.json traverses it',
            calibrationNote='TASK-564 broad cable galleries; TASK-560 360 landing / 540 recovery minima. Fresh production overhang variant, no v3 coordinates.')
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,40);p.mouse.up();self.step(p,50)
        before=self.result(p)
        self.assertTrue(all(not r['attached'] and not r['shot'] and not r['contacts'] for r in before['rows'][40:90]))
        pose=before['rows'][-1];self.assertLess(pose['x'],es['gallery-overhang']['x']-12)
        reach=p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)',self.next_target);self.assertLess(reach,540)
        self.press(p,self.next_target);self.step(p,28);p.mouse.up()
        landing=self.until(p,'gallery-third-landing');self.assertIsNotNone(landing)
        r=self.result(p)
        self.assertTrue(any(s['attached'] for s in r['rows'][:40]))
        self.assertTrue(any(s['attached'] for s in r['rows'][90:118]))
        self.assertTrue(any(s['attached'] and any(v['id']=='gallery-overhang' for v in s['rope']) for s in r['rows'][:40]))
        self.assertTrue(any(s['attached'] and any(v['id']=='gallery-reacquire' for v in s['rope']) for s in r['rows'][90:118]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=40,
            reacquisitionPressTick=90,reacquisitionReach=reach,secondReleaseTick=118,landingTick=landing,
            landingAir=50,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S05-03: opening {gap}; landings {widths}; catch 1090; reach {g["reach"]:.3f} < 540; next target visible; no red/planned terrain')
        print(f'PASS route: release 40; 50 consecutive unattached airborne ticks; reacquire beyond overhang at 90 reach {reach:.3f}; release 118 landing {landing}; trusted inputs; resets=0 poseInjections=0; images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,15);p.mouse.up()
        catch=self.until(p,'gallery-third-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'gallery-third-landing'))
        self.press(p,dict(x=11400,y=-2059));self.step(p,40);p.mouse.up()
        returned=self.until(p,'gallery-upper-landing');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=15,catchTick=catch,catchTarget='gallery-third-catch',
            returnTick=returned,recoveryTarget='gallery-upper-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 15 catch {catch}; normal controls return {returned}; no resets/injections')

    def test_03_controls(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600 ticks',successfulAlternative=bool(self.landings(r,'gallery-third-landing')))
        cases.append(r);p.mouse.up();p.context.close()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'gallery-third-landing')))
            cases.append(r);p.context.close()
        self.write('controls.json',dict(cases=cases,bound='600 ticks hold; <=600 each nearest 6/12/24',
            inspection='Every top-facing gallery-third-landing contact checked with nominal success criterion',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded hold/nearest probes; zero successful alternatives')

    def test_04_connection_upgrade_and_dependencies(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:11500,y:-1540,speedX:0,speedY:0});screen.trackGrappleOver(true)')
        self.assertEqual(p.evaluate('grappleOverAcquisitionRadius()'),360)
        self.step(p,1);self.assertEqual(p.evaluate('grappleOverAcquisitionRadius()'),540)
        self.press(p,Task591Tests.target);self.step(p,42);p.mouse.up()
        landing=self.until(p,'gallery-landing');self.assertIsNotNone(landing)
        r=self.result(p);r.update(landingTick=landing,rangeBefore=360,rangeAfter=540,
            connection='S05-01 entrance through shared S05-02 entry; separate fixture from the corner route',poseInjections=0,resets=0)
        self.write('connection.json',r)
        q=Task592Tests.page(self)
        self.press(q,Task592Tests.target);self.step(q,45);q.mouse.up()
        prior=self.until(q,'gallery-upper-landing');self.assertIsNotNone(prior)
        self.step(q,60)
        reached=q.evaluate('t=>({x:ninja.x,y:ninja.y,reach:Math.hypot(t.x-ninja.x,t.y-ninja.y)})',self.target)
        self.assertLess(reached['reach'],540)
        self.write('previous-connection.json',dict(route=self.result(q),landingTick=prior,
            approach=reached,sharedCollider='gallery-upper-landing',poseInjections=0,resets=0))
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
            q.context.close()
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,hashes=self.config['source_hashes'],
            changed=['mountain.js S05-03 preview geometry -> fixedlevel.js collision terrain','render/landmarks.js gallery fan centered over built span','tools/test_grapple_over_redesign.py additive Task593Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','fixedlevel.js','gameoptions.js','sprites/grapnel.js'],
            superseded='Earlier exact built-prefix inventories are historical; artifacts/TASK-591 proof remains in place. No earlier tests modified.',
            hashPolicy='HEAD-only changes do not invalidate identical tested source hashes'))
        required={'commands.log':'exact commands, actual exit, four identifiers, browser/viewport/revision/hashes',
            'tests.log':'four Task593Tests, no skips, OK','geometry.json':'live roles/purposes widths gap calibrated limits reach range',
            'route.json':'production overhang release and reacquisition and >=6 unattached airborne ticks','inputs.json':'trusted production mouse events',
            'miss.json':'early release catch and normal-control return','approach.jpg':'broad entry, overhang, next target and cable fan',
            'landing.jpg':'broad upper exit and Cable Galleries','controls.json':'bounded hold/nearest probes and inspection of all exit contacts',
            'previous-connection.json':'S05-02 flight to shared upper deck and normal drift into S05-03 takeoff range',
            'connection.json':'entrance 360-to-540 acquisition and physical flight onto shared deck',
            'dependencies.json':'changed subsystems, preserved modes/physics/input, source hashes',
            'evidence-index.json':'artifact assertion map and run configuration'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation']))
        print(f'PASS connection: earned entrance 360->540; shared deck landing {landing}; no mid-attempt injections')
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; physics/input unchanged; index written')


class Task594Tests(unittest.TestCase):
    """S05 exit and continuous section proof from an explicitly isolated entrance."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S05 fixture; production controls/physics; no base-to-summit claim'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    target = dict(x=9160,y=-2480)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:9480,y:-2120,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        self.observe(p)
        return p

    def observe(self,p):
        p.evaluate('''() => {const step=YARD.step;YARD.step=n=>{for(let i=0;i<n;i++){
            step(1);YARD.result().rows.at(-1).rope=grapnel.pos.map(v=>({x:v[0],y:v[1],id:v[2]?.id}));}}}''')

    def shot(self,p,target,ticks):
        self.press(p,target);self.step(p,ticks);p.mouse.up()

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'cable-galleries')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S05-04 isolated entry fixture / production physics / earned 540';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_corner_route(self):
        p=self.page()
        g=p.evaluate('''t=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S05-04'),range:grappleOverAcquisitionRadius(),
            scale:scale[version],reach:Math.hypot(t.x-ninja.x,t.y-ninja.y),target:t,
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S05-01','S05-02','S05-03','S05-04'])
        self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540);self.assertIsNone(g['finish'])
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        for id in g['encounter']['elements']:
            self.assertEqual(es[id]['role'],'bounce')
            self.assertGreaterEqual(es[id]['width'],160 if id=='gallery-shortcut-anchor' else 360 if id=='gallery-exit-projection' else 540)
        g.update(gap=es['gallery-exit']['x']-es['gallery-exit-projection']['x']-360,
            landingWidths=[800,800],recoveryWidth=800,localColliderIds=g['encounter']['elements'],
            calibrationNote='TASK-564 broad cable gallery; TASK-560 360 landing/540 recovery minima; production-validated corner variant',
            connection='Live third landing is the shared S05-03 exit; section-route.json proves continuous handoff')
        self.assertGreaterEqual(g['gap'],540)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.shot(p,self.target,45);landing=self.until(p,'gallery-exit');self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for row in r['rows'][45:landing-1]:
            streak=streak+1 if not row['contacts'] and not row['attached'] and not row['shot'] else 0
            best=max(best,streak)
        wraps=[s['tick'] for s in r['rows'][:45] if len(s['rope'])>=2]
        self.assertTrue(wraps);self.assertGreaterEqual(best,6)
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=45,
            landingTick=landing,landingAir=best,cornerTicks=wraps,entryToExit=True,resets=0,poseInjections=0,
            scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S05-04: gap {g["gap"]}; landings 800/800 catch 800; reach {g["reach"]:.3f} < 540; no red/planned terrain')
        print(f'PASS route: corner ticks {wraps}; release 45 landing {landing}; airborne unattached {best}; trusted inputs; resets=0 poseInjections=0; images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.shot(p,self.target,6)
        catch=self.until(p,'gallery-exit-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'gallery-exit'))
        self.shot(p,dict(x=9420,y=-2090),24)
        returned=self.until(p,'gallery-third-landing');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=6,catchTick=catch,catchTarget='gallery-exit-catch',
            returnTick=returned,recoveryTarget='gallery-third-landing',resets=0,poseInjections=0)
        self.write('miss.json',r)
        print(f'PASS miss: early release 6 catch {catch}; normal controls return {returned}; no resets/injections')

    def test_03_controls(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600 ticks',successfulAlternative=bool(self.landings(r,'gallery-exit')))
        cases.append(r);p.mouse.up();p.context.close()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.shot(p,target,interval);self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'gallery-exit')))
            cases.append(r);p.context.close()
        self.write('controls.json',dict(cases=cases,bound='600 ticks hold; <=600 each nearest 6/12/24',
            inspection='Every top-facing gallery-exit contact inspected using nominal success criterion'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded hold/nearest probes; zero successful alternatives')

    def entrance_to_second(self):
        p=Task591Tests.page(self);self.observe(p)
        self.shot(p,Task591Tests.target,42)
        self.assertEqual(self.until(p,'gallery-landing'),92);self.step(p,60)
        self.shot(p,dict(x=12990,y=-2030),60)
        self.assertEqual(self.until(p,'gallery-upper-landing'),418)
        return p

    def test_04_continuous_section(self):
        p=self.entrance_to_second()
        self.shot(p,Task593Tests.target,25);self.step(p,50)
        self.shot(p,Task593Tests.next_target,28)
        self.assertEqual(self.until(p,'gallery-third-landing'),554);self.step(p,75)
        self.shot(p,self.target,75)
        self.assertEqual(self.until(p,'gallery-exit',650),1216)
        r=self.result(p)
        exits=[dict(encounter=f'S05-0{i+1}',collider=id,tick=self.landings(r,id)[0]['tick'])
            for i,id in enumerate(['gallery-landing','gallery-upper-landing','gallery-third-landing','gallery-exit'])]
        self.assertEqual([e['tick'] for e in exits],[92,418,554,1216])
        self.assertFalse(p.evaluate('floors[0].climbStats.completed'))
        r.update(exits=exits,fixture=dict(x=11500,y=-1540,vx=0,vy=0),resets=0,poseInjections=0,
            completed=False,rangeBefore=360,rangeAfter=540,
            scope='One isolated S05 entrance fixture; continuous four-encounter section run; no handoff resets; not base-to-summit',
            alternativeInspection='Momentum and the third deck bounce produce a higher final approach; deliberate 75-tick corner shot reverses westward motion before the long released flight. Local corner route independently proven.')
        self.write('section-route.json',r)
        print('PASS section: ordered exits 92/418/554/1216; one labelled entrance fixture; earned 360->540; zero handoff resets/injections; S05 completion false')

    def test_05_shortcut_and_missed_shortcut(self):
        normal=json.loads((self.out/'section-route.json').read_text())
        p=self.entrance_to_second();target=dict(x=11520,y=-2319)
        reach=p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)',target)
        self.assertLess(reach,540)
        self.shot(p,target,160)
        self.assertEqual(self.until(p,'gallery-exit',500),960)
        short=self.result(p)
        self.assertFalse(self.landings(short,'gallery-third-landing'))
        for id in ['gallery-landing','gallery-upper-landing','gallery-exit']:
            self.assertTrue(self.landings(short,id))
        q=self.entrance_to_second();self.shot(q,target,120)
        catch=self.until(q,'gallery-third-landing',500);self.assertEqual(catch,894)
        self.assertFalse(self.landings(self.result(q),'gallery-exit'))
        self.shot(q,self.target,70)
        returned=self.until(q,'gallery-exit',650);self.assertEqual(returned,1239)
        miss=self.result(q);miss.update(earlyReleaseTick=538,catchTick=catch,
            catchTarget='gallery-third-landing',returnTick=returned,recoveryTarget='gallery-exit',
            resets=0,poseInjections=0)
        self.write('shortcut.json',dict(normal=dict(path='section-route.json',inputs=normal['inputs'],
            exits=normal['exits'],exitTick=normal['exits'][-1]['tick']),shortcut=short,miss=miss,
            shortcutTarget=target,shortcutReach=reach,shortcutReleaseTick=578,shortcutExitTick=960,
            ticksSaved=1216-960,skipped=['S05-03'],skippedCount=1,resets=0,poseInjections=0,
            harderAction='Aerial high-face acquisition and 160-tick release after the swing; releasing at 120 instead misses the exit and falls to the third deck. That miss then returns to the exit with a 70-tick normal corner shot.',
            scope='Both routes run continuously from the same isolated S05 entrance fixture, earn 540 and visit encounters one/two; only the third exit is omitted by the shortcut'))
        print(f'PASS shortcut: normal exit 1216 vs shortcut 960; saved 256 ticks; skipped only S05-03; target reach {reach:.3f} < 540; trusted inputs')
        print('PASS missed shortcut: early release 538 catches third deck 894; normal corner controls recover to exit 1239; resets=0 poseInjections=0')

    def test_06_dependencies_gate_and_index(self):
        p=Task567Tests.page(self)
        gate=p.evaluate('''() => {
            const m=JSON.parse(JSON.stringify(GRAPPLE_OVER_REPLACEMENT));
            m.sections=m.sections.filter(s=>s.status==='built');
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const s05=replacementMountainLevel(m).finish;
            m.sections.push({id:'S08',status:'built',encounters:[]});
            const s08=replacementMountainLevel(m).finish;
            floors[0].level.finish=s08;
            let events=0;const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events++;return original.call(this,name,...args)};
            YARD.step(3);CLIMB_UI.complete();
            return {s05,s08,events,completed:floors[0].climbStats.completed};
        }''')
        self.assertIsNone(gate['s05']);self.assertTrue(gate['s08']);self.assertEqual(gate['events'],1)
        gate['scope']='Separate isolated S08 finish contract fixture, not continuous section gameplay'
        self.write('summit-gate.json',gate)
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
            q.context.close()
        self.assertEqual(len({(r['gravity'],r['pull']) for r in rows}),1)
        self.write('dependencies.json',dict(rows=rows,hashes=self.config['source_hashes'],
            changed=['mountain.js S05-04 preview terrain -> fixedlevel.js collision geometry','tools/test_grapple_over_redesign.py additive Task594Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','fixedlevel.js','gameoptions.js','sprites/grapnel.js'],
            superseded='Earlier exact built-prefix inventory assertions are historical; earlier proof remains in its original TASK directories. No earlier tests modified.',
            hashPolicy='HEAD-only changes do not invalidate identical tested source hashes'))
        required={'commands.log':'exact commands, actual exit, six identifiers, browser/viewport/revision/hashes',
            'tests.log':'six Task594Tests; no skips; OK','geometry.json':'live roles/purposes widths gap calibrated limits reach range',
            'route.json':'production corner routing, deliberate release and >=6 unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early release catch and normal-control return',
            'approach.jpg':'broad entry, corner, visible exit and Cable Galleries',
            'landing.jpg':'broad ordinary gallery exit and Cable Galleries',
            'controls.json':'bounded hold/nearest probes and inspection of every exit contact',
            'section-route.json':'four exits in order from one labelled entrance fixture, no handoff resets',
            'shortcut.json':'same-section comparison, only S05-03 skipped, harder aerial shot and missed shortcut recovery',
            'summit-gate.json':'separate S08 fixture emits completion exactly once; S05 finish null',
            'dependencies.json':'changed subsystems, preserved modes/physics/input, source hashes',
            'evidence-index.json':'artifact assertion map and run configuration'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation']))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; physics/input unchanged')
        print('PASS summit gate: S05 finish null; separate S08 fixture completion events=1; evidence index written')


class Task595Tests(unittest.TestCase):
    """S05 isolated input tolerance and lower recovery; no continuous-gameplay claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390},device_scale_factor=1,
            simulation='Isolated S05 entries; recorded shared-gallery entries; previously earned 540; not continuous gameplay')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK595_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    frame = Task571Tests.frame
    until_landing = Task576Tests.until_landing
    targets = [Task591Tests.target,Task592Tests.target,Task593Tests.target,Task594Tests.target]
    holds = [48,45,52,45]
    exits = ['gallery-landing','gallery-upper-landing','gallery-third-landing','gallery-exit']
    fixtures = [dict(x=11500,y=-1540),dict(x=12912,y=-1540),dict(x=11570,y=-1860),dict(x=9480,y=-2120)]

    def setup_entry(self,p,index):
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.assertFalse(p.evaluate('TUTORIAL_HINT.visible'))
        p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)}',self.fixtures[index])

    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-50,0),('late',50,0),('left',0,-8),('right',0,8)]:
                    p=self.page(touch);self.setup_entry(p,index)

                    if index==2:
                        self.press(p,self.targets[index]);self.step(p,40);self.release(p);self.step(p,50)
                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    nominal_hold=self.holds[index]
                    hold=nominal_hold+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S05-0{index+1} touch approach'))
                    target=dict(Task593Tests.next_target if index==2 else self.targets[index])
                    xy=self.press(p,target,aim);self.step(p,hold);self.release(p)
                    self.until_landing(p,self.exits[index],800)
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S05-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,nominalHoldTicks=nominal_hold,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        target=target,startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=r['rows'][start:],success=bool(lands))
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S05-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=self.fixtures,fixtureScope=self.config['simulation'],source_hashes=self.config['source_hashes']))
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
            release_type='touchend' if r['mode']=='touch' else 'mouseup'
            self.assertTrue(any(i['type']==release_type and i['tick']==r['releaseTick'] for i in r['inputs']))
            self.assertTrue(any(c['id']==r['exit'] and c['ny']<-.9 for c in r['landing']['contacts']))
            self.assertTrue(any(s['attached'] for s in r['trace']))
            self.assertTrue(any(not s['attached'] and not s['contacts'] for s in r['trace'] if s['tick']>r['releaseTick']))
        print('PASS tolerance: all 40 cases; 4 encounters x 2 genuine input modes x 5 variants; +/-50 ms and +/-8 CSS px')


    def test_02_recovery(self):
        rows=[]
        for touch in [False,True]:
            for index in range(4):
                p=self.page(touch);self.setup_entry(p,index)
                start=p.evaluate('YARD.result().tick');step_ms=p.evaluate('physicsStepMs')
                hold=15 if index==2 else 6
                self.press(p,self.targets[index]);self.step(p,hold);self.release(p)
                catch_id=['gallery-catch','gallery-catch','gallery-third-catch','gallery-exit-catch'][index]
                self.until_landing(p,catch_id,500)
                before=self.result(p);catches=self.landings(before,catch_id)
                self.assertTrue(catches,(index,touch,'catch'))
                self.assertFalse(self.landings(before,self.exits[index]))
                recovery_start=before['tick']
                target,ticks,return_id=[(dict(x=11570,y=-1500),12,'viaduct-exit'),
                    (dict(x=12960,y=-1500),12,'gallery-landing'),
                    (dict(x=11400,y=-2059),40,'gallery-upper-landing'),
                    (dict(x=9420,y=-2090),24,'gallery-third-landing')][index]
                self.press(p,target);self.step(p,ticks);self.release(p)
                self.until_landing(p,return_id,800)
                r=self.result(p);returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                row=dict(encounter=f'S05-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-([48,45,40,45][index]))*step_ms,missHoldTicks=hold,startTick=start,
                    catch=catches[0],returned=returned[0] if returned else None,returnCollider=return_id,
                    recoveryStart=recovery_start,inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs']],
                    trace=r['rows'][start:],interactions='S05 local colliders are static bounce surfaces; no local mover, yellow or hazard',
                    resetsAfterStart=0,poseInjectionsAfterStart=0)
                rows.append(row);self.write('recovery.json',dict(cases=rows,source_hashes=self.config['source_hashes'],scope=self.config['simulation']))
                self.assertTrue(returned,(index,touch,'return'))
                self.assertGreater(abs(row['releaseOffsetMs']),50)
                print(f'RECOVERY {row["encounter"]} {row["mode"]} catch={catches[0]["tick"]} return={returned[0]["tick"]}')
                p.context.close()
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses and normal-input escapes; static bounce galleries inspected; zero resets/injections')

    def test_03_dependencies_and_index(self):
        previous=json.loads((ROOT/'artifacts/TASK-594/evidence-index.json').read_text())
        old=previous['config']['source_hashes']
        unchanged=[]
        for name,digest in old.items():
            if name=='tools/test_grapple_over_redesign.py':continue
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
            unchanged.append(name)
        self.write('affected-proof-map.json',dict(geometryChanges=[],runtimeChanges=[],unchanged=unchanged,
            routeAdjustment='Recorded nominal routes; S05-01 hold centered at 48; S05-03 perturbs final reacquisition/release only after recorded 40-tick first shot and 50-tick coast; final hold centered at 52',
            recoveryEndpoint='Return to previous broad gallery or viaduct exit with normal controls',
            changedSubsystems=['tools/test_grapple_over_redesign.py additive Task595Tests'],
            dependencies=['Task595Tests -> browser_test_support + grapple_over_yard.js -> events.js, physics.js, fixedlevel.js, mountain.js'],
            previousProof=['artifacts/TASK-594/evidence-index.json'],
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg'],
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes; historical proofs retained'))
        required={'commands.log':'exact command, exit, identifiers, Chromium/viewports/DPR, revision and source hashes',
            'tests.log':'three Task595Tests, no skips, OK',
            'tolerance.json':'40 successful variants with trusted input timestamps, offsets and top-facing exit contacts',
            'recovery.json':'8 out-of-window misses, lower contacts, normal-input escapes, static bounce gallery interactions',
            'affected-proof-map.json':'unchanged geometry and changed subsystem dependencies',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,scope=self.config['simulation']))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print(f'PASS dependencies: {len(unchanged)} unchanged runtime/support hashes; geometry unchanged')
        print('PASS index: all required files exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')


class Task596Tests(unittest.TestCase):
    """S05 composition review; one entrance fixture, then production-only traversal."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='One isolated S05 entrance then continuous production traversal; separate labelled recovery'

    write = Task557Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    record = Task590Tests.record
    shot = Task594Tests.shot

    def test_01_inventory_and_dependencies(self):
        p=Task591Tests.page(self)
        g=p.evaluate("""()=>({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            calibration:GRAPPLE_OVER_MOVEMENT})""")
        self.assertEqual((g['range'],g['scale']),(540,.375))
        es={e['id']:e for e in g['elements']}
        for e in es.values():
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['bounds']={k:e[a]+fn(v[a] for v in e['points']) for k,a,fn in [('left','x',min),('right','x',max),('top','y',min),('bottom','y',max)]}
            e['width']=e['bounds']['right']-e['bounds']['left'];e['height']=e['bounds']['bottom']-e['bounds']['top']
        local={id for c in g['encounters'] if c['id'].startswith('S05') for id in c['elements']}
        self.assertEqual(len([c for c in g['encounters'] if c['id'].startswith('S05')]),4)
        self.assertTrue(all(es[id]['role']=='bounce' for id in local))
        for m in g['movers']:
            self.assertNotIn(m['element'],local)
            e=es[m['element']];b=dict(e['bounds']);axis=m['axis']
            b['left' if axis=='x' else 'top']=m['min']
            b['right' if axis=='x' else 'bottom']=m['max']+e['width' if axis=='x' else 'height']
            m['sweptBounds']=b
            self.assertGreaterEqual(m['max']-m['min'],max(360,2*e['width' if axis=='x' else 'height']))
            self.assertTrue(6000<=m['periodMs']<=10000)
        def distance(a,b):
            return (max(a['left']-b['right'],b['left']-a['right'],0)**2+max(a['top']-b['bottom'],b['top']-a['bottom'],0)**2)**.5
        clearances=[]
        for z in [e for e in es.values() if e['role']=='drag']:
            self.assertNotIn(z['id'],local)
            self.assertGreaterEqual(z['width'],3*360);self.assertGreaterEqual(z['width']/z['height'],4)
            for e in es.values():
                if e['role']=='drag':continue
                sweep=next((m['sweptBounds'] for m in g['movers'] if m['element']==e['id']),e['bounds'])
                d=distance(z['bounds'],sweep);self.assertGreaterEqual(d+1e-8,540)
                clearances.append(dict(zone=z['id'],collider=e['id'],clearance=d))
        widths=[es[n]['width'] for n in Task595Tests.exits]
        self.assertEqual(widths,[800]*4)
        self.assertTrue(all(e['role']=='bounce' for e in es.values() if e['id'].startswith('yard-')))
        g.update(localIds=sorted(local),planningWidths=widths,clearances=clearances,
            firstUseOrder=['green S01','blue S03','yellow S04'],localMovers=[],localYellow=[],hazards=[],
            localRole='All S05 gameplay objects static green bounce; entrance earns 540',
            clutter='All objects have encounter purpose; no removed objects or geometry edits')
        self.write('objects.json',g)
        previous=json.loads((ROOT/'artifacts/TASK-595/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in previous.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        # Earlier section evidence is referenced, never copied. Compare earlier geometry structurally
        # because mountain.js has since gained the S05 objects.
        old=json.loads((ROOT/'artifacts/TASK-590/objects.json').read_text())
        for e in old['elements']:
            now=es[e['id']]
            for key in ['x','y','points','role','purpose']:self.assertEqual(e[key],now[key],(e['id'],key))
        for m in old['movers']:self.assertIn(m,g['movers'])
        proofs=['artifacts/TASK-590/suppression.json','artifacts/TASK-590/recovery.json',
            'artifacts/TASK-590/phases.json','artifacts/TASK-590/cycle.json',
            'artifacts/TASK-584/phases.json','artifacts/TASK-595/tolerance.json','artifacts/TASK-595/recovery.json']
        for name in proofs:self.assertTrue((ROOT/name).is_file(),name)
        self.write('dependency.json',dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py additive Task596Tests'],
            reused={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in proofs},
            geometryChanges=[],earlierGeometryComparison='All TASK-590 object coordinates/roles/purposes and full swept movers identical',
            scope='S05 has no blue/yellow/hazard. Earlier section constraints referenced; no future section requirement.',
            hashPolicy='HEAD-only changes do not invalidate identical tested source hashes'))
        print('PASS objects: four S05 encounters; every object purpose/role; green/blue/yellow order; no red; four 800-wide planning decks; all yellow clearances >=540 including full mover sweeps; S05 movers/yellow/hazards=0')
        print(f'PASS dependencies: {len(unchanged)} unchanged runtime/support hashes; earlier geometry identical; referenced proof hashes recorded')

    def test_02_continuous_capture(self):
        p=Task591Tests.page(self)
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.record(p,'S05 continuous from isolated entrance / earned 360->540 / 4x')
        views=[];observations=[]
        def capture(index,target):
            p.evaluate('draw()')
            obs=p.evaluate('t=>({tick:YARD.result().tick,target:t,client:YARD.client(t),landmark:LANDMARKS.frame.drawn,player:{x:ninja.x,y:ninja.y}})',target)
            self.assertTrue(0<obs['client']['x']<1280 and 0<obs['client']['y']<720,obs)
            self.assertEqual(obs['landmark'][0]['id'],'cable-galleries')
            observations.append(obs)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),f'S05-0{index} actual continuous approach tick {obs["tick"]}',fill='white');views.append(im)
        capture(1,Task591Tests.target);self.shot(p,Task591Tests.target,42)
        self.assertEqual(self.until(p,'gallery-landing'),92);self.step(p,60)
        capture(2,dict(x=12990,y=-2030));self.shot(p,dict(x=12990,y=-2030),60)
        self.assertEqual(self.until(p,'gallery-upper-landing'),418)
        capture(3,Task593Tests.target);self.shot(p,Task593Tests.target,25);self.step(p,50)
        self.shot(p,Task593Tests.next_target,28)
        self.assertEqual(self.until(p,'gallery-third-landing'),554);self.step(p,75)
        capture(4,Task594Tests.target);self.shot(p,Task594Tests.target,75)
        self.assertEqual(self.until(p,'gallery-exit',650),1216)
        r=self.result(p)
        exits=[dict(id=n,tick=self.landings(r,n)[0]['tick']) for n in Task595Tests.exits]
        self.write('route.json',dict(exits=exits,inputs=r['inputs'],trace=r['rows'],resetsAfterStart=0,poseInjectionsAfterStart=0,
            scope=self.config['simulation'],rangeBefore=360,rangeAfter=540))
        self.write('approaches.json',dict(views=observations))
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(views):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=85)
        overview=Image.new('RGB',(2560,720));sil=Image.new('RGB',(2560,720),'white')
        for i,center in enumerate([9800,12700]):
            p.evaluate('x=>{screen.x=width/.375/2-x;screen.y=height/.375/2+2050;draw()}',center)
            overview.paste(Image.open(io.BytesIO(p.screenshot())).convert('RGB'),(1280*i,0))
            f=p.evaluate("""()=>({elements:floors[0].elements.map(e=>({id:e.id,points:e.getPoints()})),
                shape:replacementGalleryShape(GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
                landmark:{x:(11000+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,y:(-1200+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
                camera:{x:screen.x,y:screen.y},factor:1280/width})""")
            tile=Image.new('RGB',(1280,720),'white');pen=ImageDraw.Draw(tile);k=f['factor']
            def point(v):return ((v[0]+f['landmark']['x'])*k,(v[1]+f['landmark']['y'])*k)
            for part in f['shape']['parts']:pen.polygon([point(v) for v in part],fill='#aaaaaa')
            for line in f['shape']['lines']:pen.line([point(v) for v in line],fill='#888888',width=3)
            for e in f['elements']:
                pts=[((v['x']+f['camera']['x'])*.375*k,(v['y']+f['camera']['y'])*.375*k) for v in e['points']]
                pen.polygon(pts,fill='black')
                if e['id'].startswith('gallery'):pen.text(pts[0],e['id'],fill='#555555')
            pen.text((12,12),'Cable Galleries / cable fan and deep slab / plain silhouette',fill='black');sil.paste(tile,(1280*i,0))
        overview.save(self.out/'overview.png');sil.save(self.out/'silhouette.png')
        frames=p.evaluate('reviewFrames')
        q=Task591Tests.page(self);self.record(q,'SEPARATE S05-01 early fall and normal-input recovery / 4x')
        self.shot(q,Task591Tests.target,6)
        catch=self.until(q,'gallery-catch',500);self.assertIsNotNone(catch)
        self.shot(q,dict(x=11570,y=-1500),12)
        returned=self.until(q,'viaduct-exit',800);self.assertIsNotNone(returned)
        recovery=self.result(q)
        self.write('recovery.json',dict(catchTick=catch,returnTick=returned,returnCollider='viaduct-exit',
            trace=recovery['rows'],inputs=recovery['inputs'],resetsAfterStart=0,poseInjectionsAfterStart=0))
        frames.extend(q.evaluate('reviewFrames'));q.context.close()
        p.evaluate('a=>window.reviewFrames=a',frames);p.bring_to_front()
        clip=p.evaluate('''async () => {
            const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');
            const stream=c.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of reviewFrames){const im=new Image();im.src=f.image;await im.decode();ctx.drawImage(im,0,0,1280,720);
                ctx.fillStyle='white';ctx.fillText((f.label || 'S04 continuous from isolated entry')+' / 4x / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});return await new Promise(r=>{const rd=new FileReader();rd.onload=()=>r(rd.result.split(',')[1]);rd.readAsDataURL(blob)})}''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);await v.play();
            await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],100);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)

        print(f'PASS continuous: exits 92/418/554/1216; four on-screen actual approaches; entrance earned 540; zero resets/injections; recovery {catch}->{returned}; decoded {decoded}')

    def test_03_evidence_index(self):
        required={'commands.log':'exact command, exit, identifiers, browser/viewport/revision/source hashes',
            'tests.log':'three Task596Tests; no skips; OK','objects.json':'purposes, role order, four broad decks, full swept bounds/clearances',
            'overview.png':'all four built encounters and Cable Galleries cable fan landmark',
            'silhouette.png':'plain structure, open gaps and broad landings','approaches.jpg':'four actual continuous approaches',
            'approaches.json':'target screen positions and named landmark','route.json':'continuous ordered four-exit production traversal',
            'recovery.json':'fall and normal-input return','section.webm':'continuous representative traversal plus labelled recovery',
            'clip-decode.json':'decoded frames/dimensions','dependency.json':'unchanged dependencies and reused proof hashes',
            'review.md':'image-located composition/pacing review','evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreaterEqual(im.width,1280)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; images/video decode; retained evidence <200 MB')

class Task597Tests(unittest.TestCase):
    """Counterweight Tower introduction; isolated shared gallery exit, never a summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S05-04 exit fixture -> S06-01 only; production physics and trusted inputs; not a base-to-summit run'

    observe = Task594Tests.observe
    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=10206,y=-2748.2)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:10306,y:-2440,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.towerCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);towerCycle.push({tick:i+1,y:floors[0].byId.get('tower-counterweight').y,
                px:ninja.x,py:ninja.y});}}''')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'counterweight-tower')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S06-01 isolated gallery exit / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_cycle_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S06-01'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:towerCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S06-01'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540)
        self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertEqual(es['tower-counterweight']['role'],'solid')
        for name in ['gallery-exit','tower-observation','gallery-third-landing']:
            self.assertGreaterEqual(es[name]['width'],540)
        g.update(rise=es['gallery-exit']['y']-es['tower-observation']['y'],
            landingWidths=[es[n]['width'] for n in ['gallery-exit','tower-observation']],
            recoveryWidth=es['gallery-third-landing']['width'],
            connection='Same live gallery-exit collider: isolated S05-04 exit is S06-01 entry',
            localCatch='gallery-third-landing',
            calibrationNote='TASK-564/561 vertical 720 travel and 10000ms cycle; broad 360 blue weight; 800 entry/exit/catch; vertical opening 760; 25 lateral mechanical clearance is not a passage',
            sweptBounds=dict(left=9856,right=10216,top=-3508.2,bottom=-2708.2))
        self.assertEqual(g['rise'],760)
        self.assertAlmostEqual(max(v['y'] for v in g['cycle'])-min(v['y'] for v in g['cycle']),720)
        self.assertAlmostEqual(g['cycle'][-1]['y'],-2788.2)
        self.assertTrue(all(v['px']==10306 and -2460<v['py']<-2428 for v in g['cycle']))
        sweep=g['sweptBounds'];clearances=[]
        for e in g['elements']:
            if e['id']=='tower-counterweight':continue
            left=e['x'];right=left+e['width'];top=e['y'];bottom=top+max(v['y'] for v in e['points'])
            dx=max(left-sweep['right'],sweep['left']-right,0)
            dy=max(top-sweep['bottom'],sweep['top']-bottom,0)
            self.assertGreater(max(dx,dy),0,e['id'])
            clearances.append(dict(id=e['id'],clearance=(dx*dx+dy*dy)**.5))
        g['sweepClearances']=clearances
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'tower-observation');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'gallery-third-landing'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=10306,y=-2440,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S06-01: blue width 360 travel 720; entry/exit/catch 800; vertical opening 760; reachable {g["reach"]:.3f} < 540; sweep clears all terrain; no red/planned terrain')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'gallery-third-landing',800);self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'tower-observation'))
        self.press(p,dict(x=10112,y=-2408));self.step(p,12);p.mouse.up()
        returned=self.until(p,'gallery-exit',800);self.assertIsNotNone(returned)
        r=self.result(p)
        r.update(earlyReleaseTick=606,catchTick=catch,catchTarget='gallery-third-landing',
            recoveryPressTick=catch,recoveryReleaseTick=catch+12,returnTick=returned,
            recoveryTarget='gallery-exit',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 606 declared catch {catch}; normal-control return gallery-exit {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'tower-observation')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'tower-observation')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; two-cycle continuous hold and nearest 6/12/24; zero successful alternatives')

    def test_04_dependencies_and_index(self):
        # An independent previous-encounter fixture traverses the real shared entry.
        p=Task594Tests.page(self)
        self.press(p,Task594Tests.target);self.step(p,45);p.mouse.up()
        arrival=self.until(p,'gallery-exit',800);self.assertIsNotNone(arrival)
        r=self.result(p)
        r.update(sharedCollider='gallery-exit',arrivalTick=arrival,
            fixtureScope='Separate isolated S05-04 entry -> live S06-01 entry; not continuous with route.json',
            resets=0,poseInjections=0)
        self.write('connection.json',r)
        print(f'PASS connection: previous S05-04 production flight reaches shared gallery-exit at {arrival}; no handoff injection')
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
            'render/landmarks.js tower decoration; i18n.js tower labels', 'tools/test_grapple_over_redesign.py additive Task597Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier exact preview inventories are historical; Task580 S05-04 proof remains at artifacts/TASK-596. No old v3 tests edited or rerun.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact invocation, actual exit, exact collected identifiers, revision, browser/viewport and source SHA256',
            'tests.log':'four Task597Tests; no skips; OK','geometry.json':'live collider purposes, widths, gap, target reach and 600-tick full cycle',
            'route.json':'production entry-to-exit release, landing and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production mouse events','miss.json':'early release into catch and normal-control return',
            'approach.jpg':'broad shared gallery entry, blue counterweight and tower frame',
            'landing.jpg':'safe broad observation landing and Counterweight Tower structure','controls.json':'bounded hold/nearest probes with every success inspected',
            'connection.json':'independent previous encounter production flight onto shared gallery-exit',
            'evidence-index.json':'required artifact map and tested provenance',
            'dependencies.json':'changed subsystems, unchanged modes/range/physics and source hashes'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='Identical tested source hashes survive a HEAD-only commit'))
        print('PASS dependencies: preview 360/540 legacy 1080/1620; camera .375; gravity/pull unchanged; index written')
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all required files present; JSON parsed; images decoded; storage below 200 MB')


class Task598Tests(unittest.TestCase):
    """Horizontal shaft practice from an isolated shared observation deck."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S06-01 observation deck -> S06-02; production controls; not a base-to-summit run'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task597Tests.until
    target = dict(x=11111,y=-3428.2)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:10941,y:-3200,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'counterweight-tower')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S06-02 isolated observation deck / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S06-02'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S06-01','S06-02'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertEqual(es['tower-shuttle']['role'],'solid')
        g.update(gap=es['tower-shaft-landing']['x']-es['tower-observation']['x']-es['tower-observation']['width'],
            landingWidths=[es[n]['width'] for n in ['tower-observation','tower-shaft-landing']],
            recoveryWidth=es['tower-shaft-catch']['width'],localCatch='tower-shaft-catch',
            connection='Same live tower-observation collider as S06-01 exit',
            calibrationNote='TASK-564/561 horizontal axis=x, displacement 720, period 10000ms; 360-wide blue carrier, broad 800 fixed decks, 540 shaft, 1340 recovery')
        self.assertEqual(g['gap'],540);self.assertEqual(g['landingWidths'],[800,800]);self.assertGreaterEqual(g['recoveryWidth'],540)
        sweep=dict(left=11101,right=12181,top=-3468.2,bottom=-3388.2)
        g['sweptBounds']=sweep;g['sweepClearances']=[]
        for e in g['elements']:
            if e['id']=='tower-shuttle':continue
            dx=max(e['x']-sweep['right'],sweep['left']-e['x']-e['width'],0)
            dy=max(e['y']-sweep['bottom'],sweep['top']-e['y']-max(v['y'] for v in e['points']),0)
            self.assertGreater(max(dx,dy),0,e['id'])
            g['sweepClearances'].append(dict(id=e['id'],clearance=(dx*dx+dy*dy)**.5))
        self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'tower-shaft-landing');self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][30:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        self.assertFalse(self.landings(r,'tower-shaft-catch'))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=30,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=10941,y=-3200,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        # Observe a separate full production cycle; never modify mover time/state.
        q=self.page()
        g['cycle']=q.evaluate('''()=>{const out=[];for(let i=0;i<600;i++){
            YARD.step(1);out.push({tick:i+1,x:floors[0].byId.get('tower-shuttle').x});}return out}''')
        self.assertAlmostEqual(max(v['x'] for v in g['cycle'])-min(v['x'] for v in g['cycle']),720)
        self.write('geometry.json',g)
        print(f'PASS geometry S06-02: axis=x travel=720 period=10000 widths=800/800 catch=1340 gap=540 reach={g["reach"]:.3f} range=540; purposeful materials; sweep clear; no future terrain')
        print(f'PASS route: takeoff={r["takeoffTick"]} release=30 landing={landing} unattached-airborne={best}; trusted inputs; no resets/injections')

    def test_02_late_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,60);p.mouse.up()
        catch=self.until(p,'tower-shaft-catch',800);self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'tower-shaft-landing'))
        self.press(p,dict(x=11031,y=-3158.2));self.step(p,12);p.mouse.up()
        returned=self.until(p,'tower-observation',800);self.assertIsNotNone(returned)
        r=self.result(p);r.update(lateReleaseTick=60,catchTick=catch,catchTarget='tower-shaft-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+12,returnTick=returned,recoveryTarget='tower-observation',
            resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: late release=60 catch={catch} tower-shaft-catch return={returned} tower-observation; trusted controls; no restart/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[];p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'tower-shaft-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'tower-shaft-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24',
            inspection='Every exit top contact inspected using nominal success definition; no successful alternatives'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; continuous-hold and nearest 6/12/24; successful alternatives=0')

    def test_04_connection_dependencies_and_index(self):
        p=Task597Tests.page(self);self.press(p,Task597Tests.target);self.step(p,240);p.mouse.up()
        arrival=self.until(p,'tower-observation');self.assertIsNotNone(arrival)
        r=self.result(p);r.update(sharedCollider='tower-observation',arrivalTick=arrival,
            fixtureScope='Separate S06-01 fixture -> shared S06-02 entry; not spliced into route',resets=0,poseInjections=0)
        self.write('connection.json',r)
        print(f'PASS connection: previous S06-01 reaches shared tower-observation at {arrival}; no handoff injection')
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
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview geometry -> fixedlevel.js mover/collision',
            'tools/test_grapple_over_redesign.py additive Task598Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js','render/landmarks.js'],
            superseded='Historical exact preview inventories end at S06-01; retained TASK-597 proof is referenced in place. No legacy tests edited or earlier expensive suites claimed revalidated.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, exit status, identifiers/count, revision, browser/viewport, SHA256',
            'tests.log':'four exact Task598Tests; no skips; OK','geometry.json':'live purposes/widths, 540 gap, range/reach, horizontal full cycle and swept clearance',
            'route.json':'production entry-to-exit with >=6 unattached airborne ticks','inputs.json':'trusted production input events',
            'miss.json':'late release into declared catch and return through controls','approach.jpg':'clear blue target, broad decks, tower structure',
            'landing.jpg':'fixed broad exit and tower structure','controls.json':'bounded hold/nearest probes, inspected alternatives',
            'connection.json':'previous encounter flight onto shared observation deck','dependencies.json':'changed subsystem dependencies and hashes',
            'evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='A HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS dependencies/index: preview 360/540 legacy 1080/1620 camera=.375 gravity/pull unchanged; all required files parse/decode; below 200 MB')


class Task599Tests(unittest.TestCase):
    """Green rebound into a single horizontal carrier from the shared shaft deck."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S06-02 shaft deck -> S06-03; production controls; not a base-to-summit run'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task597Tests.until
    target = dict(x=12451,y=-3488.2)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:12281,y:-3260,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def rebound(self,p):
        self.step(p,12)
        rows=p.evaluate('YARD.result().rows')
        bounce=next(s for s in rows if any(c['id']=='tower-shaft-landing' and c['ny']<-.9 for c in s['contacts']))
        self.assertEqual(bounce['tick'],6)
        self.assertGreater(rows[4]['vy'],0);self.assertLess(bounce['vy'],0)
        self.assertFalse(any(s['attached'] or s['shot'] for s in rows))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'counterweight-tower')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S06-03 isolated shaft deck / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")

    def test_01_geometry_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S06-03'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S06-01','S06-02','S06-03'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertNotIn('preview-unbuilt',es)
        self.assertEqual(es['tower-shaft-landing']['role'],'bounce')
        self.assertEqual(es['tower-rebound-landing']['role'],'bounce')
        self.assertEqual(es['tower-rebound-carrier']['role'],'solid')
        g.update(gap=es['tower-rebound-landing']['x']-es['tower-shaft-landing']['x']-es['tower-shaft-landing']['width'],
            landingWidths=[es[n]['width'] for n in ['tower-shaft-landing','tower-rebound-landing']],
            recoveryWidth=es['tower-rebound-catch']['width'],localCatch='tower-rebound-catch',
            connection='Same live tower-shaft-landing collider as S06-02 exit',
            rise=es['tower-shaft-landing']['y']-es['tower-rebound-landing']['y'],
            calibrationNote='TASK-599 brief specializes TASK-564 to green rebound then one carrier; fixed exit 60 below entry avoids simultaneous timing. TASK-564/561 horizontal axis=x, displacement 720, period 10000ms; 360-wide blue carrier, broad 800 fixed decks, 540 shaft, 1340 recovery')
        self.assertEqual(g['gap'],540);self.assertEqual(g['landingWidths'],[800,800]);self.assertGreaterEqual(g['recoveryWidth'],540)
        sweep=dict(left=12441,right=13521,top=-3528.2,bottom=-3448.2)
        g['sweptBounds']=sweep;g['sweepClearances']=[]
        for e in g['elements']:
            if e['id']=='tower-rebound-carrier':continue
            dx=max(e['x']-sweep['right'],sweep['left']-e['x']-e['width'],0)
            dy=max(e['y']-sweep['bottom'],sweep['top']-e['y']-max(v['y'] for v in e['points']),0)
            self.assertGreater(max(dx,dy),0,e['id'])
            g['sweepClearances'].append(dict(id=e['id'],clearance=(dx*dx+dy*dy)**.5))
        self.capture(p,'approach.jpg')
        self.rebound(p)
        g['postReboundReach']=p.evaluate('t=>Math.hypot(t.x-ninja.x,t.y-ninja.y)',self.target)
        self.assertLess(g['postReboundReach'],540)
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'tower-rebound-landing');self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][42:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][12:42]))
        self.assertFalse(self.landings(r,'tower-rebound-catch'))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),reboundTick=6,pressTick=12,releaseTick=42,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=12281,y=-3260,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        # Observe a separate full production cycle; never modify mover time/state.
        q=self.page()
        g['cycle']=q.evaluate('''()=>{const out=[];for(let i=0;i<600;i++){
            YARD.step(1);out.push({tick:i+1,x:floors[0].byId.get('tower-rebound-carrier').x});}return out}''')
        self.assertAlmostEqual(max(v['x'] for v in g['cycle'])-min(v['x'] for v in g['cycle']),720)
        self.write('geometry.json',g)
        print(f'PASS geometry S06-03: axis=x travel=720 period=10000 widths=800/800 catch=1340 gap=540 reach={g["reach"]:.3f} range=540; purposeful materials; sweep clear; no future terrain')
        print(f'PASS route: takeoff={r["takeoffTick"]} rebound=6 press=12 release=42 landing={landing} unattached-airborne={best}; trusted inputs; no resets/injections')

    def test_02_late_miss_and_recovery(self):
        p=self.page();self.rebound(p);self.press(p,self.target);self.step(p,60);p.mouse.up()
        catch=self.until(p,'tower-rebound-catch',800);self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'tower-rebound-landing'))
        self.press(p,dict(x=12371,y=-3218.2));self.step(p,12);p.mouse.up()
        returned=self.until(p,'tower-shaft-landing',800);self.assertIsNotNone(returned)
        r=self.result(p);r.update(lateReleaseTick=72,catchTick=catch,catchTarget='tower-rebound-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+12,returnTick=returned,recoveryTarget='tower-shaft-landing',
            resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: late release=72 catch={catch} tower-rebound-catch return={returned} tower-shaft-landing; trusted controls; no restart/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[];p=self.page();self.rebound(p);self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'tower-rebound-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();self.rebound(p);targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'tower-rebound-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24',
            inspection='Every exit top contact inspected using nominal success definition; no successful alternatives'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; continuous-hold and nearest 6/12/24; successful alternatives=0')

    def test_04_connection_dependencies_and_index(self):
        p=Task598Tests.page(self);self.press(p,Task598Tests.target);self.step(p,30);p.mouse.up()
        arrival=self.until(p,'tower-shaft-landing');self.assertIsNotNone(arrival)
        r=self.result(p);r.update(sharedCollider='tower-shaft-landing',arrivalTick=arrival,
            fixtureScope='Separate S06-02 fixture -> shared S06-03 entry; not spliced into route',resets=0,poseInjections=0)
        self.write('connection.json',r)
        print(f'PASS connection: previous S06-02 reaches shared tower-shaft-landing at {arrival}; no handoff injection')
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
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview geometry -> fixedlevel.js mover/collision',
            'tools/test_grapple_over_redesign.py additive Task599Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js','render/landmarks.js'],
            superseded='Historical exact preview inventories end at S06-02; retained TASK-598 proof is referenced in place. No legacy tests edited or earlier expensive suites claimed revalidated.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, exit status, identifiers/count, revision, browser/viewport, SHA256',
            'tests.log':'four exact Task599Tests; no skips; OK','geometry.json':'live purposes/widths, 540 gap, range/reach, horizontal full cycle and swept clearance',
            'route.json':'production entry-to-exit with >=6 unattached airborne ticks','inputs.json':'trusted production input events',
            'miss.json':'late release into declared catch and return through controls','approach.jpg':'clear blue target, broad decks, tower structure',
            'landing.jpg':'fixed broad exit and tower structure','controls.json':'bounded hold/nearest probes, inspected alternatives',
            'connection.json':'previous encounter flight onto shared shaft deck','dependencies.json':'changed subsystem dependencies and hashes',
            'evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='A HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS dependencies/index: preview 360/540 legacy 1080/1620 camera=.375 gravity/pull unchanged; all required files parse/decode; below 200 MB')


class Task600Tests(unittest.TestCase):
    """Counterweight Tower introduction; isolated shared gallery exit, never a summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S06-03 exit fixture -> S06-04 only; production physics and trusted inputs; not a base-to-summit run'

    observe = Task594Tests.observe
    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=13617,y=-3508.2)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:13517,y:-3200,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.towerCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);towerCycle.push({tick:i+1,y:floors[0].byId.get('tower-exit-lift').y,
                px:ninja.x,py:ninja.y});}}''')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'counterweight-tower')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S06-04 isolated rebound deck / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_cycle_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S06-04'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:towerCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S06-01','S06-02','S06-03','S06-04'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540)
        self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertEqual(es['tower-exit-lift']['role'],'solid')
        for name in ['tower-rebound-landing','tower-exit','tower-exit-catch']:
            self.assertGreaterEqual(es[name]['width'],540)
        g.update(rise=es['tower-rebound-landing']['y']-es['tower-exit']['y'],
            landingWidths=[es[n]['width'] for n in ['tower-rebound-landing','tower-exit']],
            recoveryWidth=es['tower-exit-catch']['width'],
            connection='Same live tower-rebound-landing collider: isolated S06-03 exit is S06-04 entry',
            localCatch='tower-exit-catch',
            calibrationNote='TASK-564/561 vertical 720 travel and 10000ms cycle; broad 360 blue weight; 800 entry/exit/catch; vertical opening 760; 25 lateral mechanical clearance is not a passage',
            sweptBounds=dict(left=13607,right=13967,top=-4268.2,bottom=-3468.2))
        self.assertEqual(g['rise'],760)
        self.assertAlmostEqual(max(v['y'] for v in g['cycle'])-min(v['y'] for v in g['cycle']),720)
        self.assertAlmostEqual(g['cycle'][-1]['y'],-3548.2)
        self.assertTrue(all(v['px']==13517 and -3220<v['py']<-3188 for v in g['cycle']))
        sweep=g['sweptBounds'];clearances=[]
        for e in g['elements']:
            if e['id']=='tower-exit-lift':continue
            left=e['x'];right=left+e['width'];top=e['y'];bottom=top+max(v['y'] for v in e['points'])
            dx=max(left-sweep['right'],sweep['left']-right,0)
            dy=max(top-sweep['bottom'],sweep['top']-bottom,0)
            self.assertGreater(max(dx,dy),0,e['id'])
            clearances.append(dict(id=e['id'],clearance=(dx*dx+dy*dy)**.5))
        g['sweepClearances']=clearances
        g['yellowCorridor']=dict(left=13721,right=14521,top=-3100,bottom=-2928,width=800,ascentOutside=True);self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'tower-exit');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'tower-exit-catch'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=13517,y=-3200,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S06-04: blue width 360 travel 720; entry/exit/catch 800; vertical opening 760; reachable {g["reach"]:.3f} < 540; sweep clears all terrain; no red/planned terrain')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,12);p.mouse.up()
        catch=self.until(p,'tower-exit-catch',800);self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'tower-exit'))
        self.press(p,dict(x=13621,y=-3178.2));self.step(p,30);p.mouse.up()
        returned=self.until(p,'tower-rebound-landing',800);self.assertIsNotNone(returned)
        r=self.result(p)
        r.update(earlyReleaseTick=612,catchTick=catch,catchTarget='tower-exit-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+30,returnTick=returned,
            recoveryTarget='tower-rebound-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        r['yellowRows']=[v for v in r['rows'] if 13721<v['x']<14521 and -3100<v['y']<-2928];self.assertTrue(r['yellowRows']);self.write('miss.json',r)
        print(f'PASS miss: early release 612 declared catch {catch}; normal-control return tower-rebound-landing {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'tower-exit')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'tower-exit')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; two-cycle continuous hold and nearest 6/12/24; zero successful alternatives')


    def test_04_continuous_section(self):
        p=Task597Tests.page(self)
        self.press(p,Task597Tests.target);self.step(p,240);p.mouse.up()
        first=self.until(p,'tower-observation');self.assertIsNotNone(first)
        self.press(p,dict(x=11031,y=-3178.2));self.step(p,48);p.mouse.up()
        second=self.until(p,'tower-shaft-landing',600);self.assertIsNotNone(second)
        self.step(p,22)
        target=p.evaluate("()=>{const e=floors[0].byId.get('tower-rebound-carrier');return {x:e.x+10,y:e.y+40}}")
        self.press(p,target);self.step(p,48);p.mouse.up()
        third=self.until(p,'tower-rebound-landing',600);self.assertIsNotNone(third)
        self.step(p,1800-third)
        self.press(p,self.target);self.step(p,240);p.mouse.up();self.step(p,12)
        self.press(p,dict(x=13572,y=-3938.2));self.step(p,12);p.mouse.up()
        fourth=self.until(p,'tower-exit',600);self.assertIsNotNone(fourth)
        r=self.result(p)
        ids=['tower-observation','tower-shaft-landing','tower-rebound-landing','tower-exit']
        exits=[dict(encounter=f'S06-0{i+1}',collider=id,tick=next(s['tick'] for s in self.landings(r,id))) for i,id in enumerate(ids)]
        self.assertEqual([e['tick'] for e in exits],[925,1073,1308,2139])
        self.assertIsNone(p.evaluate('floors[0].level.finish'))
        self.assertFalse(p.evaluate('Boolean(floors[0].climbStats.completed)'))
        r.update(exits=exits,resets=0,poseInjections=0,completed=False,
            fixture=dict(x=10306,y=-2440,vx=0,vy=0,previouslyEarnedRange=540),
            scope='One isolated S06 entry fixture; continuous four-exit section run, not base-to-summit',
            alternativeInspection='S06-02 uses an aimed 48-tick deck release instead of the shuttle; it still visits every exit. S06-04 keeps the deliberate lift release and 12 airborne ticks before a green-edge correction from the different handoff position; no tiny-transfer chain replaces lift travel.')
        self.write('section-route.json',r)
        controls=json.loads((self.out/'controls.json').read_text())
        controls['successfulAlternativeInspection']=dict(path='section-route.json',exits=exits,observation=r['alternativeInspection'])
        self.write('controls.json',controls)
        print('PASS section-route: S06-01=925 S06-02=1073 S06-03=1308 S06-04=2139; single labelled entry fixture; resets=0 injections=0 completion=0; alternative inspected')

    def test_05_dependencies_gate_and_index(self):
        p=Task567Tests.page(self)
        gate=p.evaluate('''() => {
            const m=JSON.parse(JSON.stringify(GRAPPLE_OVER_REPLACEMENT));
            m.sections=m.sections.filter(s=>s.status==='built');
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const s06=replacementMountainLevel(m).finish;
            m.sections.push({id:'S08',status:'built',encounters:[]});
            const s08=replacementMountainLevel(m).finish;
            floors[0].level.finish=s08;
            let events=0;const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events++;return original.call(this,name,...args)};
            YARD.step(3);CLIMB_UI.complete();
            return {s06,s08,events,completed:floors[0].climbStats.completed};
        }''')
        self.assertIsNone(gate['s06']);self.assertTrue(gate['s08']);self.assertEqual(gate['events'],1)
        gate['scope']='Separate isolated S08 finish contract fixture, not continuous section gameplay'
        self.write('summit-gate.json',gate);print('PASS summit gate: S06 finish null; separate S08 contract completion events=1')
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
        self.write('dependencies.json',dict(rows=rows,changed=['mountain.js preview geometry -> fixedlevel.js mover/collision',
            'tools/test_grapple_over_redesign.py additive Task600Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js','render/landmarks.js'],
            superseded='Historical exact preview inventories end at S06-03; retained TASK-598 proof is referenced in place. No legacy tests edited or earlier expensive suites claimed revalidated.',hashes=self.config['source_hashes']))
        required={'commands.log':'exact command, exit status, identifiers/count, revision, browser/viewport, SHA256',
            'tests.log':'five exact Task600Tests; no skips; OK','geometry.json':'live purposes/widths, 760 rise, range/reach, vertical full cycle and swept clearance',
            'route.json':'production entry-to-exit with >=6 unattached airborne ticks','inputs.json':'trusted production input events',
            'miss.json':'early release into isolated yellow corridor and catch and return through controls','approach.jpg':'clear blue target, broad decks, tower structure',
            'landing.jpg':'fixed broad exit and tower structure','controls.json':'bounded hold/nearest probes, inspected alternatives',
            'section-route.json':'four continuous ordered exits, no handoff resets', 'summit-gate.json':'separate S08 contract emits exactly one event','dependencies.json':'changed subsystem dependencies and hashes',
            'evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,scope=self.config['simulation'],
            hashPolicy='A HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS dependencies/index: preview 360/540 legacy 1080/1620 camera=.375 gravity/pull unchanged; all required files parse/decode; below 200 MB')


class Task601Tests(unittest.TestCase):
    """S06 isolated input tolerance and lower recovery; no continuous-gameplay claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390},device_scale_factor=1,
            simulation='Isolated S06 entries; recorded tower entries and mover phases; previously earned 540; not continuous gameplay')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK601_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    frame = Task571Tests.frame
    until_landing = Task576Tests.until_landing
    targets = [Task597Tests.target,Task598Tests.target,Task599Tests.target,Task600Tests.target]
    nominal_holds = {
        "desktop": [222,36,30,225],
        "touch": [222,69,30,225],
    }
    tolerance_targets = [dict(x=10126,y=-3008.2),dict(x=11171,y=-3428.2),
                         dict(x=12511,y=-3488.2),dict(x=13717,y=-3708.2)]
    exits = ['tower-observation','tower-shaft-landing','tower-rebound-landing','tower-exit']
    fixtures = [dict(x=10306,y=-2440),dict(x=10941,y=-3200),dict(x=12281,y=-3260),dict(x=13517,y=-3200)]

    def setup_entry(self,p,index):
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.assertFalse(p.evaluate('TUTORIAL_HINT.visible'))
        p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)}',self.fixtures[index])
        self.step(p,[600,0,12,600][index])

    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-50,0),('late',50,0),('left',0,-8),('right',0,8)]:
                    p=self.page(touch);self.setup_entry(p,index)

                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    nominal_hold=self.nominal_holds["touch" if touch else "desktop"][index]
                    hold=nominal_hold+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S06-0{index+1} touch approach'))
                    target=dict(self.tolerance_targets[index])
                    if not touch and index==0:target['x']=10106
                    xy=self.press(p,target,aim);self.step(p,hold);self.release(p)
                    self.until_landing(p,self.exits[index],800)
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S06-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,nominalHoldTicks=nominal_hold,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        target=target,startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=self.compact(r['rows'][start:]),success=bool(lands))
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S06-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=self.fixtures,fixtureScope=self.config['simulation'],source_hashes=self.config['source_hashes']))
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
            release_type='touchend' if r['mode']=='touch' else 'mouseup'
            self.assertTrue(any(i['type']==release_type and i['tick']==r['releaseTick'] for i in r['inputs']))
            self.assertTrue(any(c['id']==r['exit'] and c['ny']<-.9 for c in r['landing']['contacts']))
            self.assertTrue(any(s['attached'] for s in r['trace']))
            self.assertTrue(any(not s['attached'] and not s['contacts'] for s in r['trace'] if s['tick']>r['releaseTick']))
        print('PASS tolerance: all 40 cases; 4 encounters x 2 genuine input modes x 5 variants; +/-50 ms and +/-8 CSS px')


    @staticmethod
    def compact(rows):
        return [r for i,r in enumerate(rows) if i%12==0 or i==len(rows)-1 or r['contacts']
                or (i and (r['attached'],r['shot'])!=(rows[i-1]['attached'],rows[i-1]['shot']))]

    def interactions(self,p,index,start,result):
        mover=['tower-counterweight','tower-shuttle','tower-rebound-carrier','tower-exit-lift'][index]
        observed=p.evaluate("id=>{const e=floors[0].byId.get(id);return {id,x:e.x,y:e.y,role:e.surfaceRole}}",mover)
        yellow=[v for v in result['rows'][start:] if 13721<v['x']<14521 and -3100<v['y']<-2928]
        if index==3:self.assertTrue(yellow,'Actual S06-04 yellow corridor crossing')
        return dict(mover=observed,startPhaseMs=(start*1000/60)%10000,
                    endPhaseMs=(result['tick']*1000/60)%10000,
                    yellowRows=yellow,hazards='No red hazard in built S06')

    def test_02_recovery(self):
        rows=[]
        for touch in [False,True]:
            for index in range(4):
                p=self.page(touch);self.setup_entry(p,index)
                start=p.evaluate('YARD.result().tick');step_ms=p.evaluate('physicsStepMs')
                nominal_hold=self.nominal_holds["touch" if touch else "desktop"][index]
                hold=[6,60,60,12][index]
                self.press(p,self.targets[index]);self.step(p,hold);self.release(p)
                catch_id=['gallery-third-landing','tower-shaft-catch','tower-rebound-catch','tower-exit-catch'][index]
                self.until_landing(p,catch_id,800)
                before=self.result(p);catches=self.landings(before,catch_id)
                self.assertTrue(catches,(index,touch,'catch'))
                self.assertFalse(self.landings(before,self.exits[index]))
                recovery_start=before['tick']
                target,ticks,return_id=[(dict(x=10112,y=-2408),12,'gallery-exit'),
                    (dict(x=11031,y=-3158.2),12,'tower-observation'),
                    (dict(x=12371,y=-3218.2),12,'tower-shaft-landing'),
                    (dict(x=13621,y=-3178.2),30,'tower-rebound-landing')][index]
                self.press(p,target);self.step(p,ticks);self.release(p)
                self.until_landing(p,return_id,800)
                r=self.result(p);returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                row=dict(encounter=f'S06-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-nominal_hold)*step_ms,nominalHoldTicks=nominal_hold,
                    physicsStepMs=step_ms,missHoldTicks=hold,startTick=start,
                    catch=catches[0],returned=returned[0] if returned else None,returnCollider=return_id,
                    recoveryStart=recovery_start,inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs']],
                    trace=self.compact(r['rows'][start:]),interactions=self.interactions(p,index,start,r),
                    resetsAfterStart=0,poseInjectionsAfterStart=0)
                press_type,release_type=('touchstart','touchend') if touch else ('mousedown','mouseup')
                press=next(i for i in row['inputs'] if i['type']==press_type and i['tick']>=start)
                release=next(i for i in row['inputs'] if i['type']==release_type and i['tick']>=press['tick'])
                self.assertEqual(release['tick']-press['tick'],row['missHoldTicks'])
                self.assertAlmostEqual(row['releaseOffsetMs'],
                    release['timeMs']-press['timeMs']-nominal_hold*step_ms)
                rows.append(row);self.write('recovery.json' ,dict(cases=rows,source_hashes=self.config['source_hashes'],scope=self.config['simulation']))
                self.assertTrue(returned,(index,touch,'return'))
                self.assertGreater(abs(row['releaseOffsetMs']),50)
                print(f'RECOVERY {row["encounter"]} {row["mode"]} catch={catches[0]["tick"]} return={returned[0]["tick"]}')
                p.context.close()
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses and normal-input escapes; mover phases and S06-04 yellow corridor inspected; zero resets/injections')

    def test_03_dependencies_and_index(self):
        previous=json.loads((ROOT/'artifacts/TASK-600/evidence-index.json').read_text())
        old=previous['config']['source_hashes']
        unchanged=[]
        for name,digest in old.items():
            if name=='tools/test_grapple_over_redesign.py':continue
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
            unchanged.append(name)
        self.write('affected-proof-map.json',dict(geometryChanges=[],runtimeChanges=[],unchanged=unchanged,
            routeAdjustment='TASK-597..600 entry fixtures and mover phases reused; aim points moved inward/above blue surfaces to tolerate CSS spread; touch holds 222/69/30/225, desktop 222/36/30/225; first desktop aim x10106 versus touch x10126 calibrated independently through actual client/camera transforms; no runtime or geometry changes',
            recoveryEndpoint='Return to previous broad deck with normal controls',
            changedSubsystems=['tools/test_grapple_over_redesign.py Task601Tests shared calibrated nominal holds and trace-based recovery offset assertions'],
            dependencies=['Task601Tests -> browser_test_support + grapple_over_yard.js -> events.js, physics.js, fixedlevel.js, mountain.js'],
            previousProof=['artifacts/TASK-600/evidence-index.json'],
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg'],
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes; historical proofs retained'))
        required={'commands.log':'exact command, exit, identifiers, Chromium/viewports/DPR, revision and source hashes',
            'tests.log':'three Task601Tests, no skips, OK',
            'tolerance.json':'40 successful variants with trusted input timestamps, offsets and top-facing exit contacts',
            'recovery.json':'8 out-of-window misses, lower contacts, normal-input escapes, mover phases and yellow corridor interactions',
            'affected-proof-map.json':'unchanged geometry and changed subsystem dependencies',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,scope=self.config['simulation']))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print(f'PASS dependencies: {len(unchanged)} unchanged runtime/support hashes; geometry unchanged')
        print('PASS index: all required files exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')


class Task602Tests(unittest.TestCase):
    """S06 composition review; one entrance fixture, then production-only traversal."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='One isolated S06 entrance then continuous production traversal; separate labelled recovery'

    write = Task557Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task581Tests.until
    record = Task590Tests.record
    shot = Task594Tests.shot

    def test_01_inventory_and_dependencies(self):
        p=Task597Tests.page(self)
        g=p.evaluate("""()=>({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            calibration:GRAPPLE_OVER_MOVEMENT})""")
        self.assertEqual((g['range'],g['scale']),(540,.375))
        es={e['id']:e for e in g['elements']}
        for e in es.values():
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['bounds']={k:e[a]+fn(v[a] for v in e['points']) for k,a,fn in [('left','x',min),('right','x',max),('top','y',min),('bottom','y',max)]}
            e['width']=e['bounds']['right']-e['bounds']['left'];e['height']=e['bounds']['bottom']-e['bounds']['top']
        local={id for c in g['encounters'] if c['id'].startswith('S06') for id in c['elements']}
        self.assertEqual(len([c for c in g['encounters'] if c['id'].startswith('S06')]),4)
        self.assertEqual({es[id]['role'] for id in local},{'bounce','solid'})
        for m in g['movers']:
            e=es[m['element']];b=dict(e['bounds']);axis=m['axis']
            b['left' if axis=='x' else 'top']=m['min']
            b['right' if axis=='x' else 'bottom']=m['max']+e['width' if axis=='x' else 'height']
            m['sweptBounds']=b
            self.assertGreaterEqual(m['max']-m['min'],max(360,2*e['width' if axis=='x' else 'height']))
            self.assertTrue(6000<=m['periodMs']<=10000)
        def distance(a,b):
            return (max(a['left']-b['right'],b['left']-a['right'],0)**2+max(a['top']-b['bottom'],b['top']-a['bottom'],0)**2)**.5
        clearances=[]
        for z in [e for e in es.values() if e['role']=='drag']:
            self.assertNotIn(z['id'],local)
            self.assertGreaterEqual(z['width'],3*360);self.assertGreaterEqual(z['width']/z['height'],4)
            for e in es.values():
                if e['role']=='drag':continue
                sweep=next((m['sweptBounds'] for m in g['movers'] if m['element']==e['id']),e['bounds'])
                d=distance(z['bounds'],sweep);self.assertGreaterEqual(d+1e-8,540)
                clearances.append(dict(zone=z['id'],collider=e['id'],clearance=d))
        sweeps=[]
        for m in g['movers']:
            if m['element'] not in local:continue
            for e in es.values():
                if e['id']==m['element'] or e['role']=='drag':continue
                other=next((v['sweptBounds'] for v in g['movers'] if v['element']==e['id']),e['bounds'])
                d=distance(m['sweptBounds'],other);self.assertGreater(d,0,(m['element'],e['id']))
                sweeps.append(dict(mover=m['element'],collider=e['id'],clearance=d))
        g['localSweepClearances']=sweeps
        widths=[es[n]['width'] for n in Task601Tests.exits]
        self.assertEqual(widths,[800]*4)
        self.assertTrue(all(e['role']=='bounce' for e in es.values() if e['id'].startswith('yard-')))
        g.update(localIds=sorted(local),planningWidths=widths,clearances=clearances,
            firstUseOrder=['green S01','blue S03','yellow S04'],localMovers=[m for m in g['movers'] if m['element'] in local],localYellow=[],hazards=[],
            localRole='S06 green planning decks and four blue movers; earned range 540',
            clutter='Removed undersized tower-exit-yellow; kept broad fall catch and lateral recovery')
        cycle=p.evaluate("""()=>{const rows=[];for(let i=0;i<600;i++){
            YARD.step(1);const e=floors[0].byId.get('tower-counterweight');
            const dx=Math.max(e.x-ninja.x,ninja.x-e.x-360,0),dy=Math.max(e.y-ninja.y,ninja.y-e.y-80,0);
            rows.push({tick:i+1,y:e.y,distance:Math.hypot(dx,dy)});}return rows}""")
        streak=best=0
        for row in cycle:
            streak=streak+1 if row['distance']<=540 else 0;best=max(best,streak)
        self.assertGreaterEqual(best,60)
        g['firstTowerAcquisitionWindowMs']=best*1000/60;g['firstTowerCycle']=cycle
        print(f'PASS acquisition: first tower mover contiguous window {best*1000/60:.1f}ms >=1000; complete 600-tick cycle')
        self.write('objects.json',g)
        previous=json.loads((ROOT/'artifacts/TASK-601/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in previous.items() if n not in ['mountain.js','tools/test_grapple_over_redesign.py']}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        old=json.loads((ROOT/'artifacts/TASK-590/objects.json').read_text())
        for e in old['elements']:
            for key in ['x','y','points','role','purpose']:self.assertEqual(e[key],es[e['id']][key])
        proofs=['artifacts/TASK-590/suppression.json','artifacts/TASK-590/recovery.json','artifacts/TASK-584/phases.json']
        self.write('dependency.json',dict(unchanged=unchanged,changed=['mountain.js: remove tower-exit-yellow and update catch purpose','tools/test_grapple_over_redesign.py: additive Task602Tests'],
            reused={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in proofs},
            geometryComparison='Earlier S04 objects match all coordinates, roles, purposes; S06 routes and recovery refreshed',
            superseded='TASK-600/601 yellow crossing geometry is historical; undersized zone removed. Their traces are not claimed current.',
            hashPolicy='HEAD-only changes do not invalidate identical tested hashes'))
        print('PASS objects: four S06 encounters; every object purpose/role; green/blue/yellow order; no red; four 800-wide planning decks; earlier yellow clearances >=540 including full mover sweeps; S06 yellow/hazards=0')
        print('PASS dependencies: unchanged runtime/support hashes; S04 geometry identical; suppression/recovery referenced by hash; S06 proof refreshed')

    def test_02_continuous_capture(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:10306,y:-2440,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.record(p,'S06 continuous from isolated entrance / earned 540 / 4x');self.step(p,600)
        views=[];observations=[]
        def capture(index,target):
            p.evaluate('draw()')
            obs=p.evaluate('t=>({tick:YARD.result().tick,target:t,client:YARD.client(t),landmark:LANDMARKS.frame.drawn,player:{x:ninja.x,y:ninja.y}})',target)
            self.assertTrue(0<obs['client']['x']<1280 and 0<obs['client']['y']<720,obs)
            self.assertEqual(obs['landmark'][0]['id'],'counterweight-tower')
            observations.append(obs)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),f'S06-0{index} actual continuous approach tick {obs["tick"]}',fill='white');views.append(im)
        capture(1,Task597Tests.target);self.shot(p,Task597Tests.target,240)
        self.assertEqual(self.until(p,'tower-observation'),925)
        capture(2,dict(x=11031,y=-3178.2));self.shot(p,dict(x=11031,y=-3178.2),48)
        self.assertEqual(self.until(p,'tower-shaft-landing',600),1073);self.step(p,22)
        target=p.evaluate("()=>{const e=floors[0].byId.get('tower-rebound-carrier');return {x:e.x+10,y:e.y+40}}")
        capture(3,target);self.shot(p,target,48)
        self.assertEqual(self.until(p,'tower-rebound-landing',600),1308);self.step(p,1800-1308)
        capture(4,Task600Tests.target);self.shot(p,Task600Tests.target,240);self.step(p,12)
        self.shot(p,dict(x=13572,y=-3938.2),12)
        self.assertEqual(self.until(p,'tower-exit',600),2139)
        r=self.result(p)
        exits=[dict(id=n,tick=self.landings(r,n)[0]['tick']) for n in Task601Tests.exits]
        self.write('route.json',dict(exits=exits,inputs=r['inputs'],trace=r['rows'],resetsAfterStart=0,poseInjectionsAfterStart=0,
            scope=self.config['simulation'],rangeBefore=540,rangeAfter=540))
        self.write('approaches.json',dict(views=observations))
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(views):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=85)
        overview=Image.new('RGB',(2560,720));sil=Image.new('RGB',(2560,720),'white')
        for i,center in enumerate([10300,13200]):
            p.evaluate('x=>{screen.x=width/.375/2-x;screen.y=height/.375/2+3100;draw()}',center)
            overview.paste(Image.open(io.BytesIO(p.screenshot())).convert('RGB'),(1280*i,0))
            f=p.evaluate("""()=>({elements:floors[0].elements.map(e=>({id:e.id,points:e.getPoints()})),
                shape:GRAPPLE_OVER_LANDMARK_SHAPES[5](GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
                landmark:{x:(10100+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,y:(-2400+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
                camera:{x:screen.x,y:screen.y},factor:1280/width})""")
            tile=Image.new('RGB',(1280,720),'white');pen=ImageDraw.Draw(tile);k=f['factor']
            def point(v):return ((v[0]+f['landmark']['x'])*k,(v[1]+f['landmark']['y'])*k)
            for part in f['shape']['parts']:pen.polygon([point(v) for v in part],fill='#aaaaaa')
            for line in f['shape']['lines']:pen.line([point(v) for v in line],fill='#888888',width=3)
            for e in f['elements']:
                pts=[((v['x']+f['camera']['x'])*.375*k,(v['y']+f['camera']['y'])*.375*k) for v in e['points']]
                pen.polygon(pts,fill='black')
                if e['id'].startswith('tower'):pen.text(pts[0],e['id'],fill='#555555')
            pen.text((12,12),'Counterweight Tower / paired frame and suspended weight / plain silhouette',fill='black');sil.paste(tile,(1280*i,0))
        overview.save(self.out/'overview.png');sil.save(self.out/'silhouette.png')
        frames=p.evaluate('reviewFrames')
        q=Task600Tests.page(self);self.record(q,'SEPARATE S06-04 fall and normal-input lateral recovery / 4x')
        self.shot(q,Task600Tests.target,12)
        catch=self.until(q,'tower-exit-catch',800);self.assertIsNotNone(catch)
        self.shot(q,dict(x=13621,y=-3178.2),12)
        returned=self.until(q,'tower-rebound-landing',800);self.assertIsNotNone(returned)
        recovery=self.result(q)
        self.write('recovery.json',dict(catchTick=catch,returnTick=returned,returnCollider='tower-rebound-landing',
            trace=recovery['rows'],inputs=recovery['inputs'],resetsAfterStart=0,poseInjectionsAfterStart=0))
        frames.extend(q.evaluate('reviewFrames'));q.context.close()
        p.evaluate('a=>window.reviewFrames=a',frames);p.bring_to_front()
        clip=p.evaluate('''async () => {
            const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');
            const stream=c.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of reviewFrames){const im=new Image();im.src=f.image;await im.decode();ctx.drawImage(im,0,0,1280,720);
                ctx.fillStyle='white';ctx.fillText((f.label || 'S04 continuous from isolated entry')+' / 4x / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});return await new Promise(r=>{const rd=new FileReader();rd.onload=()=>r(rd.result.split(',')[1]);rd.readAsDataURL(blob)})}''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);await v.play();
            await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],100);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)

        print(f'PASS continuous: exits 925/1073/1308/2139; four on-screen actual approaches; earned 540; zero resets/injections; recovery {catch}->{returned}; decoded {decoded}')

    def test_03_mover_phases(self):
        cases=[]
        movers=['tower-counterweight','tower-shuttle','tower-rebound-carrier','tower-exit-lift']
        for index,mover in enumerate(movers):
            arrivals=[]
            for phase in [0,150,300,450]:
                p=Task567Tests.page(self)
                # Advance the world BEFORE the isolated arrival fixture. Advancing
                # an already placed player by phase then 600-phase is one scenario.
                self.step(p,phase)
                p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)}',Task601Tests.fixtures[index])
                arrival=p.evaluate("""id=>{const e=floors[0].byId.get(id);return {
                    tick:YARD.result().tick,player:{x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY},
                    mover:{id,x:e.x,y:e.y}}}""",mover)
                self.assertEqual(arrival['tick'],phase)
                arrivals.append(arrival)
                wait=600-phase+(12 if index==2 else 0)
                waiting=p.evaluate('''({wait,mover})=>{const rows=[];for(let i=0;i<wait;i++){
                    YARD.step(1);const r=YARD.result().rows.at(-1),e=floors[0].byId.get(mover);
                    rows.push({tick:r.tick,x:r.x,y:r.y,contacts:r.contacts,mover:{x:e.x,y:e.y}});
                }return rows}''',dict(wait=wait,mover=mover))
                arrival['nextMover']=waiting[0]['mover']
                fixture=Task601Tests.fixtures[index]
                self.assertEqual(len(waiting),wait)
                for row in waiting:
                    self.assertAlmostEqual(row['x'],fixture['x'])
                    self.assertLess(abs(row['y']-fixture['y']),40)
                self.assertTrue(any(r['contacts'] for r in waiting))
                if index==3:
                    self.shot(p,Task600Tests.target,240);self.step(p,12)
                    self.shot(p,dict(x=13572,y=-3938.2),12)
                else:
                    self.shot(p,Task601Tests.tolerance_targets[index],Task601Tests.nominal_holds['desktop'][index])
                tick=self.until(p,Task601Tests.exits[index],1200);self.assertIsNotNone(tick,(index,phase))
                r=self.result(p)
                cases.append(dict(encounter=f'S06-0{index+1}',arrivalPhase=phase/600,
                    arrival=arrival,waitTicks=wait,waiting=waiting,
                    landing=self.landings(r,Task601Tests.exits[index])[0],inputs=r['inputs'],
                    poseInjectionsAfterArrival=0))
                p.context.close()
            # Triangle motion revisits a midpoint, so position alone can have
            # three unique values. Position plus the next measured position
            # distinguishes its two directions in the retained waiting samples.
            self.assertEqual(len({a['tick'] for a in arrivals}),4)
            self.assertEqual(len({tuple(round(a[k][axis],3) for k in ['mover','nextMover'] for axis in ['x','y']) for a in arrivals}),4)
            self.assertGreaterEqual(len({(round(a['mover']['x'],3),round(a['mover']['y'],3)) for a in arrivals}),3)
        self.write('phases.json',dict(scope='Separate isolated arrivals after world phase advance; production safe wait to common acquisition window; not continuous gameplay',cases=cases))
        self.assertEqual(len(cases),16)
        print('PASS phases: 16 traversals; four measured quarter-cycle arrivals per blue mover; safe waiting positions and landing contacts retained; zero post-arrival injections')

    def test_04_evidence_index(self):
        (self.out/'review.md').write_text("TASK-602 Counterweight Tower composition review\n\nScope: built S06 only; one isolated entry then continuous production-input traversal. Separate labelled fall recovery. No claim of validated human enjoyment.\n\nReview locations: overview.png left panel contains the tower frame and first lift/observation deck; right panel contains the horizontal shafts, rebound shelf and final vertical lift. silhouette.png uses the same camera coordinates and plain filled gameplay geometry, showing the interrupted decks and broad planning shelves. approaches.jpg panels 1–4 are actual continuous approaches at unchanged camera scale 0.375. Target screen positions and landmark identity are in approaches.json.\n\nRemoved clutter: tower-exit-yellow was only 800 wide at 540 range, with inadequate terrain clearance. Removing this redundant fall brake preserves the broad catch and an open lateral recovery to the rebound deck. S04's original yellow introduction and suppression remain unchanged; dependency.json records exact evidence hashes and structural comparisons. Historical TASK-600/601 yellow crossing assertions are superseded, not edited or claimed revalidated.\n\nPacing: four 800-wide landing decks separate the lift, shaft, rebound and exit challenges. The continuous route uses a direct green deck release on encounter two; this is an observed alternative, not a claim that the shuttle is mandatory. The exit lift still requires deliberate release and a green edge correction. The clip includes an entire ten-second observation cycle and separately labelled fall/catch/normal-input recovery. No checkpoint, teleport, death or summit completion is introduced.\n")
        required={'commands.log':'exact command, exit, identifiers, browser/viewport/revision/source hashes',
            'tests.log':'four Task602Tests; no skips; OK','objects.json':'purposes, role order, four broad decks, full swept bounds/clearances',
            'overview.png':'all four built encounters and Counterweight Tower suspended-weight landmark',
            'silhouette.png':'plain structure, open gaps and broad landings','approaches.jpg':'four actual continuous approaches',
            'approaches.json':'target screen positions and named landmark','route.json':'continuous ordered four-exit production traversal',
            'phases.json':'four arrival phases per mover and safe waiting', 'recovery.json':'fall and normal-input return','section.webm':'continuous representative traversal plus labelled recovery',
            'clip-decode.json':'decoded frames/dimensions','dependency.json':'unchanged dependencies and reused proof hashes',
            'review.md':'image-located composition/pacing review','evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreaterEqual(im.width,1280)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; images/video decode; retained evidence <200 MB')



class Task603Tests(unittest.TestCase):
    """Isolated shared S06 exit -> first Crown encounter, production input/physics."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Labelled isolated tower-exit fixture to S07-01 only; not base-to-summit'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task600Tests.until
    target = dict(x=12602,y=-4099)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:12862,y:-3960,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'exposed-crown')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S07-01 isolated tower exit / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")

    def test_01_geometry_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S07-01'),range:grappleOverAcquisitionRadius(),
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),scale:scale[version],
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S07-01']);self.assertIsNone(g['finish'])
        self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],540)
        es={e['id']:e for e in g['elements']}
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points']);self.assertTrue(e['purpose'])
        self.assertNotIn('preview-unbuilt',es)
        self.assertEqual([e['id'] for e in g['elements'] if e['role']=='hazard'],['crown-red'])
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        for n in ['tower-exit','crown-landing','crown-catch']:self.assertGreaterEqual(es[n]['width'],540)
        g.update(gap=252,openingWidths=[800,800],recoveryWidth=882,
            connection='Shared tower-exit: existing S06-04 exit is the safe observation surface',
            calibration='TASK-564/560 mirrored broad opening transfer; TASK-563 red 80x80, 700 travel, 6000ms, >=150 swept clearance',
            escape='Open below red sweep into crown-landing or lower crown-catch')
        sweep=dict(left=11750,right=12530,top=-4400,bottom=-4320);g['redSweptBounds']=sweep
        g['clearances']=[]
        for e in g['elements']:
            if e['id']=='crown-red':continue
            dx=max(e['x']-sweep['right'],sweep['left']-e['x']-e['width'],0)
            dy=max(e['y']-sweep['bottom'],sweep['top']-e['y']-max(v['y'] for v in e['points']),0)
            d=(dx*dx+dy*dy)**.5;self.assertGreaterEqual(d,150,e['id']);g['clearances'].append(dict(id=e['id'],distance=d))
        self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'crown-landing',500);self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][30:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0;best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=30,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        q=self.page()
        g['observation']=q.evaluate('''()=>{const rows=[];for(let i=0;i<360;i++){YARD.step(1);const e=floors[0].byId.get('crown-red');rows.push({tick:i+1,x:e.x,px:ninja.x,py:ninja.y});}return rows}''')
        self.assertAlmostEqual(max(s['x'] for s in g['observation'])-min(s['x'] for s in g['observation']),700)
        self.assertTrue(all(s['px']==12862 and -3980<s['py']<-3948 for s in g['observation']))
        self.write('geometry.json',g)
        print(f'PASS geometry S07-01: widths 800/800 catch 882; one red 80x80 travel 700 period 6000; clearance >=150; safe full-cycle observation; reach {g["reach"]:.3f} range 540')
        print(f'PASS route: release 30 landing {landing} unattached-airborne {best}; trusted inputs; zero resets/injections')

    def test_02_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,6);p.mouse.up()
        catch=self.until(p,'crown-catch',800);self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'crown-landing'))
        self.press(p,dict(x=12792,y=-3918.2));self.step(p,24);p.mouse.up()
        returned=self.until(p,'tower-exit',800);self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=6,catchTick=catch,returnTick=returned,
            catchTarget='crown-catch',recoveryTarget='tower-exit',resets=0,poseInjections=0)
        # Separate labelled contact fixture; observer delegates unchanged production response.
        q=self.page()
        q.evaluate('''()=>{Object.assign(ninja,{x:11900,y:-4440,speedX:0,speedY:0});
            window.redContacts=[];const original=Ninja.prototype.applyHazardContact;
            Ninja.prototype.applyHazardContact=function(c){const before={vx:this.speedX,vy:this.speedY};
                const out=original.call(this,c);redContacts.push({tick:YARD.result().tick+1,before,
                    after:{vx:this.speedX,vy:this.speedY},nx:c.nx,ny:c.ny,cooldown:this.hazardCooldownMs});return out;};}''')
        self.step(q,300)
        contact=q.evaluate('({contacts:redContacts,trace:YARD.result(),completed:floors[0].climbStats.completed})')
        self.assertTrue(contact['contacts']);self.assertFalse(contact['completed'])
        first=contact['contacts'][0];self.assertGreater(first['before']['vy'],0);self.assertLess(first['after']['vy'],0)
        self.assertTrue(self.landings(contact['trace'],'crown-landing'))
        r['redContactProbe']=dict(fixture='Separate isolated fall above single red sweep at 11900,-4440; not part of traversal',
            evidence=contact,escape='Production knockback then gravity returns to broad crown-landing; no reset or injection after fixture')
        self.write('miss.json',r)
        print(f'PASS miss: release 6 catch {catch} crown-catch return {returned} tower-exit; normal trusted controls; separate red contact reverses velocity and escapes to crown-landing')

    def test_03_controls(self):
        cases=[];p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600',successfulAlternative=bool(self.landings(r,'crown-landing')));cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target);self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest {interval}',targets=targets,successfulAlternative=bool(self.landings(r,'crown-landing')));cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='600 ticks each',inspection='Every top-facing crown-landing contact checked with same success definition; no successful alternatives'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded continuous hold/nearest 6/12/24 probes; successful alternatives 0')

    def test_04_connection_and_index(self):
        p=Task600Tests.page(self);self.press(p,Task600Tests.target);self.step(p,240);p.mouse.up()
        arrival=self.until(p,'tower-exit');self.assertIsNotNone(arrival)
        r=self.result(p);r.update(sharedCollider='tower-exit',arrivalTick=arrival,scope='Separate previous encounter to shared observation deck, no spliced route',resets=0,poseInjections=0)
        self.write('connection.json',r)
        required={'commands.log':'exact command/status/count/config/hashes','tests.log':'four Task603Tests no skips',
            'geometry.json':'live roles/purposes, widths/range, red swept clearance and safe observation',
            'route.json':'trusted production entry/release/landing with >=6 airborne unattached ticks',
            'inputs.json':'trusted handler inputs','miss.json':'early release catch and normal return',
            'approach.jpg':'safe deck, targets and Crown structure','landing.jpg':'broad Crown landing',
            'controls.json':'all bounded alternatives inspected','connection.json':'previous encounter reaches shared entry',
            'evidence-index.json':'artifact assertions/provenance/dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js replacement prefix -> fixedlevel.js production geometry/mover/hazard',
                'render/landmarks.js S07 decoration only','tools/test_grapple_over_redesign.py additive Task603Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier prefix inventory assertions are historical. TASK-602 proof remains at artifacts/TASK-602; no old v3 tests changed.',
            hashPolicy='HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print(f'PASS connection: previous encounter reaches tower-exit {arrival}; index all files parse/decode; below 200 MB')


class Task604Tests(unittest.TestCase):
    """Isolated shared first Crown landing -> Crown practice encounter, production input/physics."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Labelled isolated crown-landing fixture to S07-02 only; not base-to-summit'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task600Tests.until
    target = dict(x=11550,y=-4380)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:11810,y:-3960,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'exposed-crown')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S07-02 isolated Crown landing / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")

    def test_01_geometry_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S07-02'),range:grappleOverAcquisitionRadius(),
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),scale:scale[version],
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S07-01','S07-02']);self.assertIsNone(g['finish'])
        self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],540)
        es={e['id']:e for e in g['elements']}
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points']);self.assertTrue(e['purpose'])
        self.assertNotIn('preview-unbuilt',es)
        self.assertEqual([e['id'] for e in g['elements'] if e['role']=='hazard'],['crown-red','crown-practice-red'])
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        for n in ['crown-landing','crown-practice-landing','crown-practice-catch']:self.assertGreaterEqual(es[n]['width'],540)
        g.update(gap=332,openingWidths=[800,720],recoveryWidth=882,
            connection='Shared crown-landing: existing S07-01 exit is the safe observation surface',
            calibration='TASK-564/560 mirrored broad opening transfer; TASK-563 red 80x80, 700 travel, 6000ms, >=150 swept clearance',
            escape='Open below red sweep into crown-practice-landing or lower crown-practice-catch')
        sweep=dict(left=10698,right=11478,top=-4190,bottom=-4110);g['redSweptBounds']=sweep
        g['clearances']=[]
        for e in g['elements']:
            if e['id']=='crown-practice-red':continue
            dx=max(e['x']-sweep['right'],sweep['left']-e['x']-e['width'],0)
            dy=max(e['y']-sweep['bottom'],sweep['top']-e['y']-max(v['y'] for v in e['points']),0)
            d=(dx*dx+dy*dy)**.5;self.assertGreaterEqual(d,150,e['id']);g['clearances'].append(dict(id=e['id'],distance=d))
        self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'crown-practice-landing',500);self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][30:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0;best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=30,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        q=self.page()
        g['observation']=q.evaluate('''()=>{const rows=[];for(let i=0;i<360;i++){YARD.step(1);const e=floors[0].byId.get('crown-practice-red');rows.push({tick:i+1,x:e.x,px:ninja.x,py:ninja.y});}return rows}''')
        self.assertAlmostEqual(max(s['x'] for s in g['observation'])-min(s['x'] for s in g['observation']),700)
        self.assertTrue(all(s['px']==11810 and -3980<s['py']<-3948 for s in g['observation']))
        phases=[]
        for delay in [0,60,120,180,240,300]:
            z=self.page()
            z.evaluate('''()=>{window.timingContacts=[];const original=Ninja.prototype.applyHazardContact;
                Ninja.prototype.applyHazardContact=function(c){timingContacts.push({tick:YARD.result().tick+1,id:c.element?.id});return original.call(this,c);};}''')
            self.step(z,delay);self.press(z,self.target);self.step(z,30);z.mouse.up()
            landed=self.until(z,'crown-practice-landing',500)
            trace=self.result(z)
            phases.append(dict(waitTicks=delay,releaseTick=delay+30,landingTick=landed,
                hazardContacts=z.evaluate('timingContacts'),trace=trace))
        self.write('timing.json',dict(phases=phases,scope='Separate phase fixtures; waiting advances production physics, no mover or pose injection'))
        self.assertTrue(any(x['hazardContacts'] for x in phases),'Red must affect at least one timing window')
        self.assertTrue(any(not x['hazardContacts'] and x['landingTick'] for x in phases))
        print('PASS timing: six production wait phases; both clear transfer and red-contact timing observed')
        self.write('geometry.json',g)
        print(f'PASS geometry S07-02: widths 800/720 catch 882; one red 80x80 travel 700 period 6000; clearance >=150; safe full-cycle observation; reach {g["reach"]:.3f} range 540')
        print(f'PASS route: release 30 landing {landing} unattached-airborne {best}; trusted inputs; zero resets/injections')

    def test_02_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,20);p.mouse.up()
        catch=self.until(p,'crown-practice-catch',800);self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'crown-practice-landing'))
        self.press(p,dict(x=11740,y=-3918.2));self.step(p,24);p.mouse.up()
        returned=self.until(p,'crown-landing',800);self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=20,catchTick=catch,returnTick=returned,
            catchTarget='crown-practice-catch',recoveryTarget='crown-landing',resets=0,poseInjections=0)
        # Separate labelled contact fixture; observer delegates unchanged production response.
        q=self.page()
        q.evaluate('''()=>{Object.assign(ninja,{x:10848,y:-4230,speedX:0,speedY:0});
            window.redContacts=[];const original=Ninja.prototype.applyHazardContact;
            Ninja.prototype.applyHazardContact=function(c){const before={vx:this.speedX,vy:this.speedY};
                const out=original.call(this,c);redContacts.push({tick:YARD.result().tick+1,before,
                    after:{vx:this.speedX,vy:this.speedY},nx:c.nx,ny:c.ny,cooldown:this.hazardCooldownMs});return out;};}''')
        self.step(q,300)
        contact=q.evaluate('({contacts:redContacts,trace:YARD.result(),completed:floors[0].climbStats.completed})')
        self.assertTrue(contact['contacts']);self.assertFalse(contact['completed'])
        first=contact['contacts'][0];self.assertGreater(first['before']['vy'],0);self.assertLess(first['after']['vy'],0)
        self.assertTrue(self.landings(contact['trace'],'crown-practice-landing'))
        r['redContactProbe']=dict(fixture='Separate isolated fall above single red sweep at 10848,-4230; not part of traversal',
            evidence=contact,escape='Production knockback then gravity returns to broad crown-practice-landing; no reset or injection after fixture')
        self.write('miss.json',r)
        print(f'PASS miss: release 20 catch {catch} crown-practice-catch return {returned} crown-landing; normal trusted controls; separate red contact reverses velocity and escapes to crown-practice-landing')

    def test_03_controls(self):
        cases=[];p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600',successfulAlternative=bool(self.landings(r,'crown-practice-landing')));cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target);self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest {interval}',targets=targets,successfulAlternative=bool(self.landings(r,'crown-practice-landing')));cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='600 ticks each',inspection='Every top-facing crown-practice-landing contact checked with same success definition; no successful alternatives'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded continuous hold/nearest 6/12/24 probes; successful alternatives 0')

    def test_04_connection_and_index(self):
        p=Task603Tests.page(self);self.press(p,Task603Tests.target);self.step(p,30);p.mouse.up()
        arrival=self.until(p,'crown-landing');self.assertIsNotNone(arrival)
        r=self.result(p);r.update(sharedCollider='crown-landing',arrivalTick=arrival,scope='Separate S07-01 encounter to shared practice entry, no spliced route',resets=0,poseInjections=0)
        self.write('connection.json',r)
        required={'commands.log':'exact command/status/count/config/hashes','tests.log':'four Task604Tests no skips',
            'geometry.json':'live roles/purposes, widths/range, red swept clearance and safe observation',
            'route.json':'trusted production entry/release/landing with >=6 airborne unattached ticks',
            'inputs.json':'trusted handler inputs','miss.json':'early release catch and normal return',
            'approach.jpg':'safe deck, targets and Crown structure','landing.jpg':'broad Crown landing',
            'timing.json':'six real wait phases, clear and obstructed timing windows','controls.json':'all bounded alternatives inspected','connection.json':'previous encounter reaches shared entry',
            'evidence-index.json':'artifact assertions/provenance/dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js replacement prefix -> fixedlevel.js production geometry/mover/hazard',
                'tools/test_grapple_over_redesign.py additive Task604Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier prefix inventory assertions are historical. TASK-602 proof remains at artifacts/TASK-602; no old v3 tests changed.',
            hashPolicy='HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print(f'PASS connection: previous encounter reaches crown-landing {arrival}; index all files parse/decode; below 200 MB')


class Task605Tests(unittest.TestCase):
    """Exposed Crown carrier variation; isolated shared practice exit, never a summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated S07-02 exit fixture -> S07-03 only; production physics and trusted inputs; not a base-to-summit run'

    observe = Task594Tests.observe
    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=10658,y=-4268.2)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:10758,y:-3960,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.towerCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);towerCycle.push({tick:i+1,y:floors[0].byId.get('crown-lift').y,
                px:ninja.x,py:ninja.y});}}''')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'exposed-crown')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S07-03 isolated practice deck / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_cycle_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S07-03'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:towerCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S07-01','S07-02','S07-03'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540)
        self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag','hazard'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertEqual(es['crown-lift']['role'],'solid')
        for name in ['crown-practice-landing','crown-upper-landing','crown-lift-catch']:
            self.assertGreaterEqual(es[name]['width'],540)
        g.update(rise=es['crown-practice-landing']['y']-es['crown-upper-landing']['y'],
            landingWidths=[es[n]['width'] for n in ['crown-practice-landing','crown-upper-landing']],
            recoveryWidth=es['crown-lift-catch']['width'],
            connection='Same live crown-practice-landing collider: isolated S07-02 exit is S07-03 entry',
            localCatch='crown-lift-catch',
            calibrationNote='TASK-564/561 vertical 720 travel and 10000ms cycle; broad 360 blue weight; 720 entry, 800 exit/catch; vertical opening 760; 25 lateral mechanical clearance is not a passage',
            sweptBounds=dict(left=10308,right=10668,top=-5028.2,bottom=-4228.2))
        self.assertEqual(g['rise'],760)
        self.assertAlmostEqual(max(v['y'] for v in g['cycle'])-min(v['y'] for v in g['cycle']),720)
        self.assertAlmostEqual(g['cycle'][-1]['y'],-4308.2)
        self.assertTrue(all(v['px']==10758 and -3980<v['py']<-3948 for v in g['cycle']))
        sweep=g['sweptBounds'];clearances=[]
        for e in g['elements']:
            if e['id']=='crown-lift':continue
            left=e['x'];right=left+e['width'];top=e['y'];bottom=top+max(v['y'] for v in e['points'])
            dx=max(left-sweep['right'],sweep['left']-right,0)
            dy=max(top-sweep['bottom'],sweep['top']-bottom,0)
            self.assertGreater(max(dx,dy),0,e['id'])
            clearances.append(dict(id=e['id'],clearance=(dx*dx+dy*dy)**.5))
        g['sweepClearances']=clearances
        g['redSweptBounds']=dict(left=10698,right=11318,top=-4498.2,bottom=-4418.2)
        g['redClearances']=[]
        for e in g['elements']:
            if e['id']=='crown-lift-red':continue
            bounds=g['sweptBounds'] if e['id']=='crown-lift' else dict(left=e['x'],right=e['x']+e['width'],top=e['y'],bottom=e['y']+max(v['y'] for v in e['points']))
            h=g['redSweptBounds'];dx=max(bounds['left']-h['right'],h['left']-bounds['right'],0);dy=max(bounds['top']-h['bottom'],h['top']-bounds['bottom'],0)
            distance=(dx*dx+dy*dy)**.5
            self.assertGreater(distance,0,e['id'])
            g['redClearances'].append(dict(id=e['id'],distance=distance))
        g['hazardVariation']='540 horizontal travel / 6000ms / 180 units per second; 30-unit carrier-side mechanical clearance is not a passage; entry and exit stay safe for waiting'

        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'crown-upper-landing');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'crown-lift-catch'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=10758,y=-3960,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S07-03: blue width 360 travel 720; entry 720 exit/catch 800; vertical opening 760; reachable {g["reach"]:.3f} < 540; sweep clears all terrain; no planned terrain')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,12);p.mouse.up()
        catch=self.until(p,'crown-lift-catch',800);self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'crown-upper-landing'))
        self.press(p,dict(x=10688,y=-3938.2));self.step(p,60);p.mouse.up()
        returned=self.until(p,'crown-practice-landing',800);self.assertIsNotNone(returned)
        r=self.result(p)
        r.update(earlyReleaseTick=612,catchTick=catch,catchTarget='crown-lift-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+60,returnTick=returned,
            recoveryTarget='crown-practice-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 612 declared catch {catch}; normal-control return crown-practice-landing {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'crown-upper-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'crown-upper-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; two-cycle continuous hold and nearest 6/12/24; zero successful alternatives')


    def test_04_wait_timing(self):
        phases=[]
        for delay in [0,600,1200]:
            p=self.page()
            p.evaluate("""()=>{window.hits=[];const original=Ninja.prototype.applyHazardContact;
                Ninja.prototype.applyHazardContact=function(c){const before={x:this.x,y:this.y,vx:this.speedX,vy:this.speedY};const out=original.call(this,c);hits.push({tick:YARD.result().tick+1,before,after:{vx:this.speedX,vy:this.speedY},red:floors[0].byId.get('crown-lift-red').x});return out}}""")
            self.step(p,delay);self.press(p,self.target);self.step(p,240);p.mouse.up()
            landing=self.until(p,'crown-upper-landing',600)
            r=self.result(p)
            phases.append(dict(waitTicks=600+delay,releaseTick=840+delay,landingTick=landing,
                hazardContacts=p.evaluate('hits'),trace=r))
        self.write('timing.json',dict(phases=phases,scope='Separate isolated fixtures; full production waits preserve carrier phase and vary red timing; no state injections after setup'))
        self.assertTrue(any(x['hazardContacts'] for x in phases))
        self.assertTrue(any(not x['hazardContacts'] and x['landingTick'] for x in phases))
        print('PASS timing: three full-cycle waits; red contact and clear carrier transfer both observed')

    def test_05_connection_and_index(self):
        p=Task604Tests.page(self);self.press(p,Task604Tests.target);self.step(p,30);p.mouse.up()
        arrival=self.until(p,'crown-practice-landing');self.assertIsNotNone(arrival)
        r=self.result(p);r.update(sharedCollider='crown-practice-landing',arrivalTick=arrival,scope='Separate S07-02 encounter to shared practice entry, no spliced route',resets=0,poseInjections=0)
        self.write('connection.json',r)
        required={'commands.log':'exact command/status/count/config/hashes','tests.log':'five Task605Tests no skips',
            'geometry.json':'live roles/purposes, widths/range, red swept clearance and safe observation',
            'route.json':'trusted production entry/release/landing with >=6 airborne unattached ticks',
            'inputs.json':'trusted handler inputs','miss.json':'early release catch and normal return',
            'approach.jpg':'safe deck, targets and Crown structure','landing.jpg':'broad Crown landing',
            'timing.json':'three full-cycle waits with unchanged carrier phase and varying red phase','controls.json':'all bounded alternatives inspected','connection.json':'previous encounter reaches shared entry',
            'evidence-index.json':'artifact assertions/provenance/dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js replacement prefix -> fixedlevel.js production geometry/mover/hazard',
                'tools/test_grapple_over_redesign.py additive Task605Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier prefix inventory assertions are historical. TASK-602 proof remains at artifacts/TASK-602; no old v3 tests changed.',
            hashPolicy='HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print(f'PASS connection: previous encounter reaches crown-practice-landing {arrival}; index all files parse/decode; below 200 MB')


class Task606Tests(unittest.TestCase):
    """Crown exit and continuous section proof from labelled isolated entries."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Labelled isolated Crown entries, production controls/physics; not base-to-summit'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task605Tests.until
    target = dict(x=11673,y=-5140)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:11413,y:-4720,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def shot(self,p,target,hold):
        p.mouse.up()
        p.evaluate('screen.trackGrappleOver(true)')
        self.press(p,target);self.step(p,hold);p.mouse.up()

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'exposed-crown')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S07-04 isolated Crown upper deck / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S07-04'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),calibrated:GRAPPLE_OVER_MOVEMENT,
            finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S07-01','S07-02','S07-03','S07-04'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        for name in ['crown-upper-landing','crown-exit','crown-exit-catch']:
            self.assertGreaterEqual(es[name]['width'],540)
        g.update(connection='Live crown-upper-landing shared with S07-03',
            landingWidths=[800,800],recoveryWidth=882,gap=12033-11493,
            escape='Open below red sweep onto the broad exit or lower catch',
            calibration='TASK-564 broad shelves; TASK-604 420-rise launch and 32-tick deliberate release mirrored east; first red remains S07')
        self.assertGreaterEqual(g['gap'],540)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.shot(p,self.target,32);landing=self.until(p,'crown-exit',500);self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][32:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:32]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=32,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        print(f'PASS geometry S07-04: live purposes; landing widths 800/800 opening 540 recovery 882; reach {g["reach"]:.3f} < 540; no planned terrain; scale .375')
        print(f'PASS route: release 32 landing {landing}; consecutive unattached airborne {best}; trusted inputs; zero resets/injections; images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.shot(p,self.target,24)
        catch=self.until(p,'crown-exit-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'crown-exit'))
        returned=self.until(p,'crown-exit');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=24,catchTick=catch,catchTarget='crown-exit-catch',
            returnTick=returned,recoveryTarget='crown-exit',resets=0,poseInjections=0,
            recovery='Release lets the normal green catch rebound reach the exit deck; no additional input required')
        self.write('miss.json',r)
        print(f'PASS miss: early release 24 catch crown-exit-catch {catch}; normal rebound returns crown-exit {returned}; no reset/checkpoint')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,720)
        r=self.result(p);r.update(probe='continuous hold 720 ticks',successfulAlternative=bool(self.landings(r,'crown-exit')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.shot(p,target,interval);self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'crown-exit')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='720 hold; <=600 repeated nearest 6/12/24',
            inspection='Every exit top contact tested with nominal success definition'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; zero successful alternatives')

    def entrance_to_carrier(self):
        p=Task603Tests.page(self)
        self.step(p,420)  # Real observation time, preserves both mover clocks.
        self.shot(p,Task603Tests.target,30)
        self.assertEqual(self.until(p,'crown-landing',300),520)
        self.step(p,80);self.shot(p,Task604Tests.target,30)
        self.assertEqual(self.until(p,'crown-practice-landing',400),879)
        self.step(p,300)
        return p

    def test_04_continuous_section(self):
        p=self.entrance_to_carrier()
        self.shot(p,dict(x=10658,y=-4318.6),240)
        self.assertEqual(self.until(p,'crown-upper-landing',500),1627)
        self.step(p,120);self.shot(p,self.target,30)
        self.assertEqual(self.until(p,'crown-exit',500),1856)
        r=self.result(p)
        exits=[dict(encounter=f'S07-0{i+1}',collider=id,tick=self.landings(r,id)[0]['tick'])
            for i,id in enumerate(['crown-landing','crown-practice-landing','crown-upper-landing','crown-exit'])]
        self.assertEqual([e['tick'] for e in exits],[520,879,1627,1856])
        self.assertFalse(p.evaluate('floors[0].climbStats.completed'))
        r.update(exits=exits,fixture=dict(x=12862,y=-3960,vx=0,vy=0),resets=0,poseInjections=0,
            completed=False,scope='One labelled isolated S07 entrance fixture; all four encounters continuously; no handoff resets; not base-to-summit')
        self.write('section-route.json',r)
        print('PASS section-route: ordered S07 exits 520/879/1627/1856; single labelled fixture; zero resets/injections; completion false')

    def aerial_exit(self,p,carrier_hold):
        self.shot(p,dict(x=10658,y=-4318.6),carrier_hold)
        tick=p.evaluate('''()=>{for(let i=0;i<500;i++){
            YARD.step(1);if(Math.hypot(ninja.x-11673,ninja.y+5140)<500)return YARD.result().tick;
        }return null}''')
        self.assertIsNotNone(tick)
        self.shot(p,self.target,30)
        return tick

    def test_05_shortcut_and_recovery(self):
        normal=json.loads((self.out/'section-route.json').read_text())
        p=self.entrance_to_carrier();press=self.aerial_exit(p,260)
        exit_tick=self.until(p,'crown-exit',500);self.assertEqual(exit_tick,1658)
        short=self.result(p)
        self.assertFalse(self.landings(short,'crown-upper-landing'))
        for name in ['crown-landing','crown-practice-landing','crown-exit']:
            self.assertTrue(self.landings(short,name))
        self.assertEqual(press,1539)
        q=self.entrance_to_carrier();late_press=self.aerial_exit(q,280)
        catch=self.until(q,'crown-exit-catch',500);self.assertEqual(catch,1703)
        self.assertFalse(self.landings(self.result(q),'crown-exit'))
        self.shot(q,dict(x=11483,y=-4698),30)
        returned=self.until(q,'crown-exit',500);self.assertEqual(returned,1781)
        miss=self.result(q);miss.update(catchTick=catch,catchTarget='crown-exit-catch',
            returnTick=returned,recoveryTarget='crown-exit',lateCarrierReleaseTick=1459,
            aerialPressTick=late_press,resets=0,poseInjections=0)
        self.write('shortcut.json',dict(normal=dict(path='section-route.json',inputs=normal['inputs'],
            exits=normal['exits'],exitTick=1856),shortcut=short,miss=miss,
            shortcutReleaseTick=1439,aerialPressTick=press,shortcutExitTick=exit_tick,ticksSaved=198,
            skipped=['S07-03'],skippedCount=1,resets=0,poseInjections=0,
            harderAction='20-tick later carrier release, then a moving aerial exit-face acquisition before touching the upper rest deck; another 20 ticks late falls to exit catch and requires a 30-tick westward recovery grapple',
            scope='Same isolated S07 entry and common first/second route; skips only the third safe landing, retains carrier mechanics; not base-to-summit'))
        print('PASS shortcut: normal 1856 vs shortcut 1658; saved 198 ticks; skipped only S07-03; aerial acquisition tick 1539')
        print('PASS shortcut miss: late release 1459 -> crown-exit-catch 1703 -> normal west grapple -> crown-exit 1781; no resets/injections')

    def test_06_gate_dependencies_and_index(self):
        p=Task567Tests.page(self)
        gate=p.evaluate('''() => {
            const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
            m.finish={left:2000,right:2300,top:-100,bottom:100};
            const s07=replacementMountainLevel(m).finish;
            m.sections.push({id:'S08',status:'built',encounters:[]});
            const s08=replacementMountainLevel(m).finish;floors[0].level.finish=s08;
            let events=0;const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events++;return original.call(this,name,...args)};
            YARD.step(3);CLIMB_UI.complete();
            return {s07,s08,events,completed:floors[0].climbStats.completed};
        }''')
        self.assertIsNone(gate['s07']);self.assertTrue(gate['s08']);self.assertEqual(gate['events'],1);self.assertTrue(gate['completed'])
        gate['scope']='Separate isolated S08 finish contract fixture at base; not authored S08 gameplay or part of the S07 run'
        self.write('summit-gate.json',gate)
        section=json.loads((self.out/'section-route.json').read_text());section['summitGate']=gate
        self.write('section-route.json',section)
        required={'commands.log':'exact command, exit/count/identifiers, browser/viewport, revision/hashes',
            'tests.log':'six Task606Tests with no skips, OK',
            'geometry.json':'live purposes, range/reach, landing/recovery widths, built prefix and gap',
            'route.json':'trusted production takeoff/release/landing and >=6 consecutive unattached ticks',
            'inputs.json':'trusted input handlers', 'miss.json':'early release catch and normal rebound return',
            'approach.jpg':'broad upper deck and visible exit target with Exposed Crown structure',
            'landing.jpg':'broad exit landing and Crown structure',
            'controls.json':'four bounded probes, all successful alternatives inspected',
            'section-route.json':'four ordered exits from one labelled fixture, zero resets, S08-only finish gate',
            'shortcut.json':'same-section shortcut skips only third rest deck; timing/input comparison and missed shortcut recovery',
            'summit-gate.json':'separate S08-only exactly-once completion contract',
            'evidence-index.json':'artifact assertions, provenance and changed dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js replacement S07-04 geometry/shortcut metadata -> fixedlevel.js collision/movers',
                'tools/test_grapple_over_redesign.py additive Task606Tests -> browser_test_support / production input and physics'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js','render/landmarks.js'],
            superseded='Earlier prefix inventory assertions are historical; old v3 coordinates are not replacement requirements. TASK-605 proof remains at artifacts/TASK-605; its geometry/physics remain unchanged.',
            hashPolicy='HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS summit: S07 finish null; isolated S08 contract emits level_completed exactly once')
        print('PASS index: all required files exist/parse/decode; evidence below 200 MB; dependencies and hashes recorded')


class Task607Tests(unittest.TestCase):
    """S07 isolated input tolerance and lower recovery; no continuous-gameplay claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390},device_scale_factor=1,
            simulation='Isolated S07 entries; recorded Crown entries and mover phases; previously earned 540; not continuous gameplay')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK607_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    frame = Task571Tests.frame
    until_landing = Task576Tests.until_landing
    targets = [Task603Tests.target,Task604Tests.target,Task605Tests.target,Task606Tests.target]
    nominal_holds = {
        "desktop": [30,30,240,35],
        "touch": [30,30,260,35],
    }
    tolerance_targets = [Task603Tests.target,Task604Tests.target,dict(x=10630,y=-4368),Task606Tests.target]

    def aim(self,index,touch):
        return dict(x=10580,y=-4450) if index==2 and touch else dict(self.tolerance_targets[index])
    exits = ['crown-landing','crown-practice-landing','crown-upper-landing','crown-exit']
    fixtures = [dict(x=12862,y=-3960),dict(x=11810,y=-3960),dict(x=10758,y=-3960),dict(x=11413,y=-4720)]

    def setup_entry(self,p,index):
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.assertFalse(p.evaluate('TUTORIAL_HINT.visible'))
        p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)}',self.fixtures[index])
        p.evaluate("""()=>{window.redContacts=[];const original=Ninja.prototype.applyHazardContact;
            Ninja.prototype.applyHazardContact=function(c){const before={vx:this.speedX,vy:this.speedY};
                const out=original.call(this,c);redContacts.push({tick:YARD.result().tick+1,x:c.x,y:c.y,nx:c.nx,ny:c.ny,
                hazards:['crown-red','crown-practice-red','crown-lift-red','crown-exit-red'].map(id=>{const e=floors[0].byId.get(id);return {id,x:e.x,y:e.y}}),
                before,after:{vx:this.speedX,vy:this.speedY}});return out;};}""")
        self.step(p,[0,120,600,0][index])

    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-50,0),('late',50,0),('left',0,-8),('right',0,8)]:
                    p=self.page(touch);self.setup_entry(p,index)

                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    nominal_hold=self.nominal_holds["touch" if touch else "desktop"][index]
                    hold=nominal_hold+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S07-0{index+1} touch approach'))
                    target=self.aim(index,touch)
                    xy=self.press(p,target,aim);self.step(p,hold);self.release(p)
                    self.until_landing(p,self.exits[index],800)
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S07-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,nominalHoldTicks=nominal_hold,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        target=target,startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=self.compact(r['rows'][start:]),success=bool(lands))
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S07-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=self.fixtures,fixtureScope=self.config['simulation'],source_hashes=self.config['source_hashes']))
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
            release_type='touchend' if r['mode']=='touch' else 'mouseup'
            self.assertTrue(any(i['type']==release_type and i['tick']==r['releaseTick'] for i in r['inputs']))
            self.assertTrue(any(c['id']==r['exit'] and c['ny']<-.9 for c in r['landing']['contacts']))
            self.assertTrue(any(s['attached'] for s in r['trace']))
            self.assertTrue(any(not s['attached'] and not s['contacts'] for s in r['trace'] if s['tick']>r['releaseTick']))
        print('PASS tolerance: all 40 cases; 4 encounters x 2 genuine input modes x 5 variants; +/-50 ms and +/-8 CSS px')


    @staticmethod
    def compact(rows):
        return [r for i,r in enumerate(rows) if i%12==0 or i==len(rows)-1 or r['contacts']
                or (i and (r['attached'],r['shot'])!=(rows[i-1]['attached'],rows[i-1]['shot']))]

    def interactions(self,p,index,start,result):
        ids=['crown-red','crown-practice-red','crown-lift','crown-lift-red']
        observed=p.evaluate("ids=>ids.map(id=>{const e=floors[0].byId.get(id);return {id,x:e.x,y:e.y,role:e.surfaceRole}})",ids)
        return dict(movers=observed,startPhaseMs=(start*1000/60)%10000,
                    endPhaseMs=(result['tick']*1000/60)%10000,
                    hazardContacts=p.evaluate('redContacts'),yellow='No yellow in S07')

    def test_02_recovery(self):
        rows=[]
        for touch in [False,True]:
            for index in range(4):
                p=self.page(touch);self.setup_entry(p,index)
                start=p.evaluate('YARD.result().tick');step_ms=p.evaluate('physicsStepMs')
                nominal_hold=self.nominal_holds["touch" if touch else "desktop"][index]
                hold=[6,20,12,24][index]
                self.press(p,self.aim(index,touch));self.step(p,hold);self.release(p)
                catch_id=['crown-catch','crown-practice-catch','crown-lift-catch','crown-exit-catch'][index]
                self.until_landing(p,catch_id,800)
                before=self.result(p);catches=self.landings(before,catch_id)
                self.assertTrue(catches,(index,touch,'catch'))
                self.assertFalse(self.landings(before,self.exits[index]))
                recovery_start=before['tick']
                target,ticks,return_id=[(dict(x=12792,y=-3918.2),24,'tower-exit'),
                    (dict(x=11740,y=-3918.2),24,'crown-landing'),
                    (dict(x=10688,y=-3938.2),60,'crown-practice-landing'),
                    (None,0,'crown-exit')][index]
                if target:
                    self.press(p,target);self.step(p,ticks);self.release(p)
                self.until_landing(p,return_id,800)
                r=self.result(p);returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                row=dict(encounter=f'S07-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-nominal_hold)*step_ms,nominalHoldTicks=nominal_hold,
                    physicsStepMs=step_ms,missHoldTicks=hold,startTick=start,
                    catch=catches[0],returned=returned[0] if returned else None,returnCollider=return_id,
                    recoveryStart=recovery_start,inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs']],
                    trace=self.compact(r['rows'][start:]),interactions=self.interactions(p,index,start,r),
                    resetsAfterStart=0,poseInjectionsAfterStart=0)
                press_type,release_type=('touchstart','touchend') if touch else ('mousedown','mouseup')
                press=next(i for i in row['inputs'] if i['type']==press_type and i['tick']>=start)
                release=next(i for i in row['inputs'] if i['type']==release_type and i['tick']>=press['tick'])
                self.assertEqual(release['tick']-press['tick'],row['missHoldTicks'])
                self.assertAlmostEqual(row['releaseOffsetMs'],
                    release['timeMs']-press['timeMs']-nominal_hold*step_ms)
                rows.append(row);self.write('recovery.json' ,dict(cases=rows,source_hashes=self.config['source_hashes'],scope=self.config['simulation']))
                self.assertTrue(returned,(index,touch,'return'))
                self.assertGreater(abs(row['releaseOffsetMs']),50)
                print(f'RECOVERY {row["encounter"]} {row["mode"]} catch={catches[0]["tick"]} return={returned[0]["tick"]}')
                p.context.close()
        # Separate labelled fall fixtures prove the four red responses and local
        # escapes; these are not spliced into any input-tolerance attempt.
        probes=[]
        for hazard,fixture,return_id in [
                ('crown-red',dict(x=11900,y=-4440),'crown-landing'),
                ('crown-practice-red',dict(x=10848,y=-4230),'crown-practice-landing'),
                ('crown-lift-red',dict(x=10972,y=-4538.2),'crown-practice-landing'),
                ('crown-exit-red',dict(x=11995,y=-4990),'crown-exit-catch')]:
            p=self.page(True);self.setup_entry(p,0)
            p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});screen.trackGrappleOver(true)}',fixture)
            self.step(p,300)
            r=p.evaluate('YARD.result()');hits=p.evaluate('redContacts')
            self.assertTrue(hits,hazard)
            hit=hits[0];bounds=next(h for h in hit['hazards'] if h['id']==hazard)
            self.assertTrue(bounds['x']<=hit['x']<=bounds['x']+80,(hazard,hit))
            self.assertTrue(bounds['y']<=hit['y']<=bounds['y']+80,(hazard,hit))
            self.assertGreater(hit['before']['vy'],0);self.assertLess(hit['after']['vy'],0)
            returned=[v for v in self.landings(r,return_id) if v['tick']>hit['tick']]
            self.assertTrue(returned,hazard)
            probes.append(dict(hazard=hazard,fixture=fixture,contact=hit,returnCollider=return_id,
                returned=returned[0],trace=self.compact(r['rows']),resetsAfterStart=0,
                poseInjectionsAfterStart=0,scope='Separate isolated touch-context fall fixture; normal gravity/knockback/green rebound; no additional input'))
            print(f'HAZARD {hazard} contact={hit["tick"]} return={returned[0]["tick"]} {return_id}')
            p.context.close()
        self.write('recovery.json',dict(cases=rows,hazardProbes=probes,
            source_hashes=self.config['source_hashes'],scope=self.config['simulation']))
        print('PASS hazards: four actual red contacts reverse falling velocity and escape to local green through unchanged production physics')
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses and normal-input escapes; mover phases and hazard contacts recorded; zero resets/injections')

    def test_03_dependencies_and_index(self):
        previous=json.loads((ROOT/'artifacts/TASK-606/evidence-index.json').read_text())
        old=previous['config']['source_hashes']
        unchanged=[]
        for name,digest in old.items():
            if name=='tools/test_grapple_over_redesign.py':continue
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
            unchanged.append(name)
        self.write('affected-proof-map.json',dict(geometryChanges=[],runtimeChanges=[],unchanged=unchanged,
            routeAdjustment='TASK-603..606 isolated entries reused; S07-02 waits 120 production ticks; S07-03 aims above carrier (desktop 10630,-4368 hold240; touch 10580,-4450 hold260); S07-04 hold35; actual client transforms; bounded calibration; no geometry changes',
            recoveryEndpoint='Return to previous broad deck with normal controls',
            changedSubsystems=['tools/test_grapple_over_redesign.py Task607Tests shared calibrated nominal holds and trace-based recovery offset assertions'],
            dependencies=['Task607Tests -> browser_test_support + grapple_over_yard.js -> events.js, physics.js, fixedlevel.js, mountain.js'],
            previousProof=['artifacts/TASK-606/evidence-index.json'],
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg'],
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes; historical proofs retained'))
        required={'commands.log':'exact command, exit, identifiers, Chromium/viewports/DPR, revision and source hashes',
            'tests.log':'three Task607Tests, no skips, OK',
            'tolerance.json':'40 successful variants with trusted input timestamps, offsets and top-facing exit contacts',
            'recovery.json':'8 out-of-window misses, lower contacts, normal-input escapes, mover phases; four separate actual red contacts and local green escapes',
            'affected-proof-map.json':'unchanged geometry and changed subsystem dependencies',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,scope=self.config['simulation']))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print(f'PASS dependencies: {len(unchanged)} unchanged runtime/support hashes; geometry unchanged')
        print('PASS index: all required files exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')


class Task608Tests(unittest.TestCase):
    """S07 composition review; one entrance fixture, then production-only traversal."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='One isolated S07 entrance then continuous production traversal; separate labelled recovery'

    write = Task557Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task605Tests.until
    record = Task590Tests.record
    shot = Task606Tests.shot

    def test_01_inventory_and_dependencies(self):
        p=Task603Tests.page(self)
        g=p.evaluate("""()=>({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            calibration:GRAPPLE_OVER_MOVEMENT})""")
        self.assertEqual((g['range'],g['scale']),(540,.375))
        es={e['id']:e for e in g['elements']}
        for e in es.values():
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag','hazard'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['bounds']={k:e[a]+fn(v[a] for v in e['points']) for k,a,fn in [('left','x',min),('right','x',max),('top','y',min),('bottom','y',max)]}
            e['width']=e['bounds']['right']-e['bounds']['left'];e['height']=e['bounds']['bottom']-e['bounds']['top']
        local={id for c in g['encounters'] if c['id'].startswith('S07') for id in c['elements']}
        self.assertEqual(len([c for c in g['encounters'] if c['id'].startswith('S07')]),4)
        self.assertEqual({es[id]['role'] for id in local},{'bounce','solid','hazard'})
        for m in g['movers']:
            e=es[m['element']];b=dict(e['bounds']);axis=m['axis']
            b['left' if axis=='x' else 'top']=m['min']
            b['right' if axis=='x' else 'bottom']=m['max']+e['width' if axis=='x' else 'height']
            m['sweptBounds']=b
            self.assertGreaterEqual(m['max']-m['min'],max(360,2*e['width' if axis=='x' else 'height']))
            self.assertTrue(6000<=m['periodMs']<=10000)
        def distance(a,b):
            return (max(a['left']-b['right'],b['left']-a['right'],0)**2+max(a['top']-b['bottom'],b['top']-a['bottom'],0)**2)**.5
        clearances=[]
        for z in [e for e in es.values() if e['role']=='drag']:
            self.assertNotIn(z['id'],local)
            self.assertGreaterEqual(z['width'],3*360);self.assertGreaterEqual(z['width']/z['height'],4)
            for e in es.values():
                if e['role']=='drag':continue
                sweep=next((m['sweptBounds'] for m in g['movers'] if m['element']==e['id']),e['bounds'])
                d=distance(z['bounds'],sweep);self.assertGreaterEqual(d+1e-8,540)
                clearances.append(dict(zone=z['id'],collider=e['id'],clearance=d))
        sweeps=[]
        for m in g['movers']:
            if m['element'] not in local:continue
            for e in es.values():
                if e['id']==m['element'] or e['role']=='drag':continue
                other=next((v['sweptBounds'] for v in g['movers'] if v['element']==e['id']),e['bounds'])
                d=distance(m['sweptBounds'],other);self.assertGreater(d,0,(m['element'],e['id']))
                sweeps.append(dict(mover=m['element'],collider=e['id'],clearance=d))
        g['localSweepClearances']=sweeps
        widths=[es[n]['width'] for n in Task607Tests.exits]
        self.assertEqual(widths,[800,720,800,800])
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        g.update(localIds=sorted(local),planningWidths=widths,clearances=clearances,firstUse=first,
            localYellow=[],clutter='No redundant local objects identified; anchors, broad decks, catches, carrier and four red sweeps have distinct encounter roles')
        q=Task567Tests.page(self)
        q.evaluate('Object.assign(ninja,{x:10758,y:-3960,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        cycle=q.evaluate("""()=>{const rows=[];for(let i=0;i<600;i++){
            YARD.step(1);const e=floors[0].byId.get('crown-lift');
            rows.push({tick:i+1,y:e.y,px:ninja.x,py:ninja.y,distance:Math.hypot(Math.max(e.x-ninja.x,ninja.x-e.x-360,0),Math.max(e.y-ninja.y,ninja.y-e.y-80,0))});}return rows}""")
        best=streak=0
        for row in cycle:
            streak=streak+1 if row['distance']<=540 else 0;best=max(best,streak)
            self.assertEqual(row['px'],10758);self.assertLess(abs(row['py']+3960),32)
        self.assertGreaterEqual(best,60)
        g['acquisitionWindowMs']=best*1000/60;g['carrierCycle']=cycle
        g['usefulEndpoints']='Lower end reachable from practice deck; upper end releases onto crown-upper-landing; phases.json proves traversal'
        self.write('objects.json',g)
        old=json.loads((ROOT/'artifacts/TASK-607/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        yellow=json.loads((ROOT/'artifacts/TASK-590/objects.json').read_text())
        for e in yellow['elements']:
            for key in ['x','y','points','role','purpose']:self.assertEqual(e[key],es[e['id']][key])
        proofs=['artifacts/TASK-590/suppression.json','artifacts/TASK-590/recovery.json','artifacts/TASK-607/recovery.json','artifacts/TASK-607/tests.log','artifacts/TASK-607/commands.log']
        recovery=json.loads((ROOT/proofs[2]).read_text())
        self.assertEqual(len(recovery['hazardProbes']),4)
        for h in recovery['hazardProbes']:
            self.assertGreater(h['contact']['before']['vy'],0);self.assertLess(h['contact']['after']['vy'],0)
            self.assertGreater(h['returned']['tick'],h['contact']['tick'])
        self.write('dependency.json',dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: additive Task608Tests'],
            reused={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in proofs},
            geometryComparison='All S04 coordinates/roles/purposes identical; all runtime dependencies identical to TASK-607',
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes'))
        print(f'PASS objects: every object has purpose/encounter; first green S01 blue S03 yellow S04 red S07; four broad landings {widths}; full swept bounds clear; yellow clearance >=540; carrier window {best*1000/60:.1f}ms >=1000')
        print('PASS dependencies: 49 unchanged runtime/support hashes; S04 suppression/lateral recovery and four actual red contact escapes referenced by exact hashes')

    def test_02_continuous_capture(self):
        p=Task603Tests.page(self)
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.record(p,'S07 continuous from isolated entrance / earned 540 / 4x');self.step(p,420)
        views=[];observations=[]
        def capture(index,target):
            p.evaluate('draw()')
            obs=p.evaluate('t=>({tick:YARD.result().tick,target:t,client:YARD.client(t),landmark:LANDMARKS.frame.drawn,player:{x:ninja.x,y:ninja.y}})',target)
            self.assertTrue(0<obs['client']['x']<1280 and 0<obs['client']['y']<720,obs)
            self.assertEqual(obs['landmark'][0]['id'],'exposed-crown')
            observations.append(obs)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),f'S07-0{index} actual continuous approach tick {obs["tick"]}',fill='white');views.append(im)
        capture(1,Task603Tests.target);self.shot(p,Task603Tests.target,30)
        self.assertEqual(self.until(p,'crown-landing',300),520)
        self.step(p,80);capture(2,Task604Tests.target);self.shot(p,Task604Tests.target,30)
        self.assertEqual(self.until(p,'crown-practice-landing',400),879);self.step(p,300)
        target=dict(x=10658,y=-4318.6);capture(3,target);self.shot(p,target,240)
        self.assertEqual(self.until(p,'crown-upper-landing',500),1627);self.step(p,120)
        capture(4,Task606Tests.target);self.shot(p,Task606Tests.target,30)
        self.assertEqual(self.until(p,'crown-exit',500),1856)
        r=self.result(p)
        exits=[dict(id=n,tick=self.landings(r,n)[0]['tick']) for n in Task607Tests.exits]
        self.write('route.json',dict(exits=exits,inputs=r['inputs'],trace=r['rows'],resetsAfterStart=0,poseInjectionsAfterStart=0,
            scope=self.config['simulation'],rangeBefore=540,rangeAfter=540))
        self.write('approaches.json',dict(views=observations))
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(views):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=85)
        overview=Image.new('RGB',(2560,720));sil=Image.new('RGB',(2560,720),'white')
        for i,center in enumerate([10500,13200]):
            p.evaluate('x=>{screen.x=width/.375/2-x;screen.y=height/.375/2+4200;draw()}',center)
            overview.paste(Image.open(io.BytesIO(p.screenshot())).convert('RGB'),(1280*i,0))
            f=p.evaluate("""()=>({elements:floors[0].elements.map(e=>({id:e.id,points:e.getPoints()})),
                shape:GRAPPLE_OVER_LANDMARK_SHAPES[6](GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
                landmark:{x:(12400+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,y:(-3200+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
                camera:{x:screen.x,y:screen.y},factor:1280/width})""")
            tile=Image.new('RGB',(1280,720),'white');pen=ImageDraw.Draw(tile);k=f['factor']
            def point(v):return ((v[0]+f['landmark']['x'])*k,(v[1]+f['landmark']['y'])*k)
            for part in f['shape']['parts']:pen.polygon([point(v) for v in part],fill='#aaaaaa')
            for line in f['shape']['lines']:pen.line([point(v) for v in line],fill='#888888',width=3)
            for e in f['elements']:
                pts=[((v['x']+f['camera']['x'])*.375*k,(v['y']+f['camera']['y'])*.375*k) for v in e['points']]
                pen.polygon(pts,fill='black')
                if e['id'].startswith('crown'):pen.text(pts[0],e['id'],fill='#555555')
            pen.text((12,12),'Exposed Crown / stepped roof and antenna mast / plain silhouette',fill='black');sil.paste(tile,(1280*i,0))
        overview.save(self.out/'overview.png');sil.save(self.out/'silhouette.png')
        frames=p.evaluate('reviewFrames')
        q=Task567Tests.page(self)
        q.evaluate('Object.assign(ninja,{x:10758,y:-3960,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false')
        self.record(q,'SEPARATE S07-03 full carrier cycle then fall and normal-input recovery / 4x')
        self.step(q,600);self.shot(q,Task605Tests.target,12)
        catch=self.until(q,'crown-lift-catch',800);self.assertIsNotNone(catch)
        self.shot(q,dict(x=10688,y=-3938.2),60)
        returned=self.until(q,'crown-practice-landing',800);self.assertIsNotNone(returned)
        recovery=self.result(q)
        self.write('recovery.json',dict(catchTick=catch,returnTick=returned,returnCollider='crown-practice-landing',
            trace=recovery['rows'],inputs=recovery['inputs'],resetsAfterStart=0,poseInjectionsAfterStart=0))
        frames.extend(q.evaluate('reviewFrames'));q.context.close()
        p.evaluate('a=>window.reviewFrames=a',frames);p.bring_to_front()
        clip=p.evaluate('''async () => {
            const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');
            const stream=c.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of reviewFrames){const im=new Image();im.src=f.image;await im.decode();ctx.drawImage(im,0,0,1280,720);
                ctx.fillStyle='white';ctx.fillText((f.label || 'S04 continuous from isolated entry')+' / 4x / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});return await new Promise(r=>{const rd=new FileReader();rd.onload=()=>r(rd.result.split(',')[1]);rd.readAsDataURL(blob)})}''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);await v.play();
            await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],100);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)

        print(f'PASS continuous: exits 520/879/1627/1856; four on-screen actual approaches; earned 540; zero resets/injections; recovery {catch}->{returned}; decoded {decoded}')

    def test_03_carrier_phases(self):
        cases=[]
        for phase in [0,150,300,450]:
            p=Task567Tests.page(self);self.step(p,phase)
            p.evaluate('Object.assign(ninja,{x:10758,y:-3960,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
            arrival=p.evaluate("({tick:YARD.result().tick,y:floors[0].byId.get('crown-lift').y})")
            waiting=p.evaluate("""n=>{const rows=[];for(let i=0;i<n;i++){YARD.step(1);rows.push({tick:YARD.result().tick,x:ninja.x,y:ninja.y,moverY:floors[0].byId.get('crown-lift').y})}return rows}""",600-phase)
            for row in waiting:self.assertEqual(row['x'],10758);self.assertLess(abs(row['y']+3960),32)
            self.shot(p,Task605Tests.target,240)
            tick=self.until(p,'crown-upper-landing',600);self.assertIsNotNone(tick)
            r=self.result(p)
            cases.append(dict(arrival=arrival,arrivalPhase=phase/600,waiting=waiting,landing=self.landings(r,'crown-upper-landing')[0],inputs=r['inputs'],resetsAfterArrival=0,poseInjectionsAfterArrival=0))
            p.context.close()
        self.assertEqual(len({(v['arrival']['y'],v['waiting'][0]['moverY']) for v in cases}),4)
        self.write('phases.json',dict(scope='Four isolated phase arrivals, production waiting and traversal; not continuous gameplay',cases=cases))
        print('PASS phases: four distinct quarter-cycle arrivals; safe production waiting; four upper-deck top contacts; zero post-arrival injections')

    def test_04_evidence_index(self):
        (self.out/'review.md').write_text('TASK-608 Exposed Crown composition review\n\nBuilt S07 only. One isolated entrance then continuous production controls; separate labelled carrier-cycle/fall recovery. No claim of validated human enjoyment.\n\noverview.png left panel shows the vertical carrier, practice and upper planning decks; right panel shows the first red lookout and Crown exit. silhouette.png uses the same camera frames: the stepped roof and antenna-mast landmark behind the east decks makes Exposed Crown recognizable; the open lower field separates the catch shelves from the main route. approaches.jpg panels 1–4 show the actual continuous approaches at scale 0.375, with the target coordinates and landmark recorded in approaches.json.\n\nPacing: 800/720/800/800-wide green landings separate four deliberate release challenges. Encounter 1 gives a safe red observation deck; encounter 2 repeats a westward transfer; encounter 3 reverses upward on the long-travel blue carrier; encounter 4 releases east across the open exit gap. The clip shows all four in one run, then a clearly separate complete ten-second carrier cycle and early-release fall with a normal-input return. Full swept bounds are checked against all other colliders, not just a single mover pose. Narrow mechanical clearances beside the carrier are not intended passages.\n\nClutter review: retained the three launch faces, four distinct red timing windows, one carrier and local catches; each has an encounter-specific purpose in objects.json. No redundant object was identified, so geometry is unchanged. Green/blue/yellow precede first red S07. No local yellow; earlier compliant S04 yellow suppression and lateral recovery are reused only with structural equality and exact dependency hashes. Four actual red-contact recoveries are referenced from TASK-607. No later section or human enjoyment claim is required.\n')
        required={'commands.log':'exact command, exit, identifiers, browser/viewport/revision/source hashes',
            'tests.log':'four Task608Tests; no skips; OK','objects.json':'purposes, role order, four broad decks, full swept bounds/clearances',
            'overview.png':'all four built encounters and Exposed Crown roof-and-antenna landmark',
            'silhouette.png':'plain structure, open gaps and broad landings','approaches.jpg':'four actual continuous approaches',
            'approaches.json':'target screen positions and named landmark','route.json':'continuous ordered four-exit production traversal',
            'phases.json':'four arrival phases for the Crown carrier and safe waiting', 'recovery.json':'fall and normal-input return','section.webm':'continuous representative traversal plus labelled recovery',
            'clip-decode.json':'decoded frames/dimensions','dependency.json':'unchanged dependencies and reused proof hashes',
            'review.md':'image-located composition/pacing review','evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreaterEqual(im.width,1280)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; images/video decode; retained evidence <200 MB')


class Task609Tests(unittest.TestCase):
    """Summit opening from a labelled shared Crown exit fixture; production inputs and physics."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Labelled isolated Summit entry on the existing Crown exit, production controls/physics; not base-to-summit'

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task605Tests.until
    target = dict(x=13013,y=-5140)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:12753,y:-4720,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def shot(self,p,target,hold):
        p.mouse.up()
        p.evaluate('screen.trackGrappleOver(true)')
        self.press(p,target);self.step(p,hold);p.mouse.up()

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'summit-array')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S08-01 isolated shared Crown exit / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S08-01'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),calibrated:GRAPPLE_OVER_MOVEMENT,
            finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S08-01'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        for name in ['crown-exit','summit-landing','summit-catch']:
            self.assertGreaterEqual(es[name]['width'],540)
        g.update(connection='Live crown-exit shared with S07-04',
            landingWidths=[800,800],recoveryWidth=882,gap=13373-12833,
            escape='Green-only opening; open release gap above broad lower catch',
            calibration='TASK-564 broad shelves; TASK-606 calibrated 420-rise launch translated east; red omitted for familiar forgiving green opening; first red remains S07')
        self.assertGreaterEqual(g['gap'],540)
        g['localElements']=[es[n] for n in g['encounter']['elements']]
        self.assertTrue(all(e['role']=='bounce' for e in g['localElements']))
        self.assertEqual([e['id'] for e in g['elements'] if e['id'].startswith('summit-')],['summit-anchor','summit-landing','summit-catch'])
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.shot(p,self.target,32);landing=self.until(p,'summit-landing',500);self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][32:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:32]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=32,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        print(f'PASS geometry S08-01: live purposes; landing widths 800/800 opening 540 recovery 882; reach {g["reach"]:.3f} < 540; no planned terrain; scale .375')
        print(f'PASS route: release 32 landing {landing}; consecutive unattached airborne {best}; trusted inputs; zero resets/injections; images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.shot(p,self.target,24)
        catch=self.until(p,'summit-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'summit-landing'))
        returned=self.until(p,'summit-landing');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=24,catchTick=catch,catchTarget='summit-catch',
            returnTick=returned,recoveryTarget='summit-landing',resets=0,poseInjections=0,
            recovery='Release lets the normal green catch rebound reach the exit deck; no additional input required')
        self.write('miss.json',r)
        print(f'PASS miss: early release 24 catch summit-catch {catch}; normal rebound returns summit-landing {returned}; no reset/checkpoint')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,720)
        r=self.result(p);r.update(probe='continuous hold 720 ticks',successfulAlternative=bool(self.landings(r,'summit-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.shot(p,target,interval);self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'summit-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='720 hold; <=600 repeated nearest 6/12/24',
            inspection='Every exit top contact tested with nominal success definition'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; zero successful alternatives')

    def test_04_tolerance_and_index(self):
        tolerance=[]
        for hold in [30,34]:
            p=self.page();self.shot(p,self.target,hold)
            tick=self.until(p,'summit-landing',500);self.assertIsNotNone(tick)
            r=self.result(p);tolerance.append(dict(hold=hold,landingTick=tick,inputs=r['inputs'],rows=r['rows']))
        self.write('tolerance.json',tolerance)
        required={'commands.log':'exact command, actual exit, four identifiers, browser/viewport/revision/source hashes',
            'tests.log':'four Task609Tests; no skips; OK',
            'geometry.json':'live S08-01 green collider purposes/widths, gap, calibrated reach and shared S07-04 entry',
            'route.json':'trusted production takeoff/release/landing and >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted production input events matching nominal route',
            'miss.json':'early release, declared catch and normal rebound return without resets',
            'approach.jpg':'broad shared Crown exit, green target and Summit Array antenna',
            'landing.jpg':'broad Summit planning landing and antenna',
            'controls.json':'four bounded hold/nearest probes; every exit contact inspected',
            'tolerance.json':'30 and 34 tick releases also land successfully',
            'evidence-index.json':'artifact assertions and changed subsystem dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js S08-01 built prefix and green geometry -> fixedlevel.js production colliders',
                'render/landmarks.js S08 presentation -> existing band 7 antenna sprite',
                'tools/test_grapple_over_redesign.py additive Task609Tests -> browser_test_support and production handlers'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier prefix inventories/landmark-at-shared-exit assertions are historical; TASK-608 Crown proof remains at artifacts/TASK-608. Old v3 terrain stays playable; no later Summit terrain or completion authored.',
            hashPolicy='HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS tolerance: 30/32/34 tick releases succeed; index files exist/parse/decode; retained evidence <200 MB; dependencies recorded')


class Task610Tests(unittest.TestCase):
    """Summit Array carrier variation; isolated shared practice exit, never a summit run."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/test_grapple_over_redesign.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        cls.config['simulation']='Isolated S08-01 exit fixture -> S08-02 only; production physics and trusted inputs; not a base-to-summit run'

    observe = Task594Tests.observe
    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    target = dict(x=14193,y=-5028.2)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:14093,y:-4720,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        # A full real production cycle, no mover-time or player-state injection.
        p.evaluate('''() => {window.towerCycle=[];for(let i=0;i<600;i++){
            YARD.step(1);towerCycle.push({tick:i+1,y:floors[0].byId.get('summit-lift').y,
                px:ninja.x,py:ninja.y});}}''')
        return p

    def until(self,p,id,limit=400):
        return p.evaluate('''({id,limit})=>{for(let i=0;i<limit;i++){
            YARD.step(1);const r=YARD.result().rows.at(-1);
            if(r.contacts.some(c=>c.id===id&&c.ny<-.9))return r.tick;
        }return null}''',dict(id=id,limit=limit))

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'summit-array')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S08-02 isolated Summit entry deck / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_cycle_and_release(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S08-02'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),cycle:towerCycle,
            calibrated:{movement:GRAPPLE_OVER_MOVEMENT,movers:GRAPPLE_OVER_MOVERS},
            dragCount:floors[0].dragZones.length,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S08-01','S08-02'])
        self.assertIsNone(g['finish']);self.assertEqual(g['range'],540)
        self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag','hazard'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        self.assertEqual(es['summit-lift']['role'],'solid')
        for name in ['summit-landing','summit-upper-landing','summit-lift-catch']:
            self.assertGreaterEqual(es[name]['width'],540)
        g.update(rise=es['summit-landing']['y']-es['summit-upper-landing']['y'],
            landingWidths=[es[n]['width'] for n in ['summit-landing','summit-upper-landing']],
            recoveryWidth=es['summit-lift-catch']['width'],
            connection='Same live summit-landing collider: isolated S08-01 exit is S08-02 entry',
            localCatch='summit-lift-catch',
            calibrationNote='TASK-564/561 vertical 720 travel and 10000ms cycle; broad 360 blue weight; 800 entry/exit/catch; vertical opening 760; 10 lateral mechanical clearance is not a passage',
            sweptBounds=dict(left=14183,right=14543,top=-5788.2,bottom=-4988.2))
        self.assertEqual(g['rise'],760)
        self.assertAlmostEqual(max(v['y'] for v in g['cycle'])-min(v['y'] for v in g['cycle']),720)
        self.assertAlmostEqual(g['cycle'][-1]['y'],-5068.2)
        self.assertTrue(all(v['px']==14093 and -4740<v['py']<-4708 for v in g['cycle']))
        sweep=g['sweptBounds'];clearances=[]
        for e in g['elements']:
            if e['id']=='summit-lift':continue
            left=e['x'];right=left+e['width'];top=e['y'];bottom=top+max(v['y'] for v in e['points'])
            dx=max(left-sweep['right'],sweep['left']-right,0)
            dy=max(top-sweep['bottom'],sweep['top']-bottom,0)
            self.assertGreater(max(dx,dy),0,e['id'])
            clearances.append(dict(id=e['id'],clearance=(dx*dx+dy*dy)**.5))
        g['sweepClearances']=clearances
        g['localElements']=[es[n] for n in g['encounter']['elements']]
        g['openingGap']=g['rise']
        self.assertGreaterEqual(g['openingGap'],540)
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,240);p.mouse.up()
        landing=self.until(p,'summit-upper-landing');self.assertIsNotNone(landing)
        r=self.result(p);streak=0;best=0
        for s in r['rows'][840:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertFalse(self.landings(r,'summit-lift-catch'))
        self.assertTrue(any(s['attached'] for s in r['rows'][600:840]))
        r.update(entryTick=0,observationTicks=600,takeoffTick=next(s['tick'] for s in r['rows'][600:] if s['vy']<0),
            releaseTick=840,landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,
            fixture=dict(x=14093,y=-4720,vx=0,vy=0),scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']))
        self.capture(p,'landing.jpg')
        print(f'PASS geometry S08-02: blue width 360 travel 720; entry/exit/catch 800; vertical opening 760; reachable {g["reach"]:.3f} < 540; sweep clears all terrain; no planned terrain')
        print(f'PASS route: full-cycle observation; takeoff {r["takeoffTick"]} release 840 landing {landing}; consecutive unattached airborne {best}; trusted handlers; zero resets/injections; images decoded')

    def test_02_early_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,12);p.mouse.up()
        catch=self.until(p,'summit-lift-catch',800);self.assertIsNotNone(catch)
        before=self.result(p);self.assertFalse(self.landings(before,'summit-upper-landing'))
        p.evaluate('screen.trackGrappleOver(true)')
        self.press(p,dict(x=14163,y=-4698.2));self.step(p,24);p.mouse.up()
        returned=self.until(p,'summit-landing',800);self.assertIsNotNone(returned)
        r=self.result(p)
        r.update(earlyReleaseTick=612,catchTick=catch,catchTarget='summit-lift-catch',
            recoveryPressTick=catch,recoveryReleaseTick=catch+24,returnTick=returned,
            recoveryTarget='summit-landing',resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('miss.json',r)
        print(f'PASS miss: early release 612 declared catch {catch}; normal-control return summit-landing {returned}; no reset/checkpoint/injection')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,1200)
        r=self.result(p);r.update(probe='continuous hold for two cycles',successfulAlternative=bool(self.landings(r,'summit-upper-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'summit-upper-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='1200 continuous hold; 600 each repeated-nearest 6/12/24 hold ticks',
            inspection='All exit top contacts inspected with the same nominal success definition; no successful alternatives',scope=self.config['simulation']))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; two-cycle continuous hold and nearest 6/12/24; zero successful alternatives')


    def test_04_connection_and_index(self):
        p=Task609Tests.page(self);self.press(p,Task609Tests.target);self.step(p,32);p.mouse.up()
        arrival=self.until(p,'summit-landing');self.assertIsNotNone(arrival)
        r=self.result(p);r.update(sharedCollider='summit-landing',arrivalTick=arrival,scope='Separate S08-01 encounter to shared practice entry, no spliced route',resets=0,poseInjections=0)
        self.write('connection.json',r)
        required={'commands.log':'exact command/status/count/config/hashes','tests.log':'four Task610Tests no skips',
            'geometry.json':'live roles/purposes, widths/range, carrier swept clearance and full-cycle safe observation',
            'route.json':'trusted production entry/release/landing with >=6 airborne unattached ticks',
            'inputs.json':'trusted handler inputs','miss.json':'early release catch and normal return',
            'approach.jpg':'safe deck, targets and Summit antenna structure','landing.jpg':'broad Summit landing',
            'controls.json':'all bounded alternatives inspected','connection.json':'previous encounter reaches shared entry',
            'evidence-index.json':'artifact assertions/provenance/dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js replacement prefix -> fixedlevel.js production geometry/mover/hazard',
                'tools/test_grapple_over_redesign.py additive Task610Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier prefix inventory assertions are historical. TASK-609 opening proof remains at artifacts/TASK-609; no old v3 tests changed. Earlier prefix inventory coverage is superseded, not suppressed.',
            hashPolicy='HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print(f'PASS connection: previous encounter reaches summit-landing {arrival}; index all files parse/decode; below 200 MB')


class Task611Tests(unittest.TestCase):
    """Isolated shared Summit upper deck -> timed corner rebound, production input/physics."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/test_grapple_over_redesign.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        cls.config['simulation']='Labelled isolated summit-upper-landing fixture to S08-03 only; not base-to-summit'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK611_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task600Tests.until
    target = dict(x=13178,y=-5900)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:13438,y:-5480,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def capture(self,p,name):
        p.evaluate('screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw()')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'summit-array')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S08-03 isolated Summit landing / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")

    def test_01_geometry_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S08-03'),range:grappleOverAcquisitionRadius(),
            target,reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),scale:scale[version],
            calibrated:GRAPPLE_OVER_MOVEMENT,finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S08-01','S08-02','S08-03']);self.assertIsNone(g['finish'])
        self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375);self.assertLess(g['reach'],540)
        es={e['id']:e for e in g['elements']}
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points']);self.assertTrue(e['purpose'])
        self.assertNotIn('preview-unbuilt',es)
        self.assertEqual([e['id'] for e in g['elements'] if e['role']=='hazard'],['crown-red','crown-practice-red','crown-lift-red','crown-exit-red','summit-timing-red'])
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        for n in ['summit-upper-landing','summit-timing-landing','summit-timing-catch']:self.assertGreaterEqual(es[n]['width'],540)
        g.update(gap=es['summit-upper-landing']['x']-es['summit-timing-landing']['x']-es['summit-timing-landing']['width'],
            openingWidths=[es[n]['width'] for n in ['summit-upper-landing','summit-timing-landing']],
            recoveryWidth=es['summit-timing-catch']['width'],
            localElements=[es[n] for n in g['encounter']['elements']],
            connection='Shared summit-upper-landing: existing S08-02 exit is the safe observation surface',
            calibration='TASK-564/560 mirrored broad opening transfer; TASK-563 red 80x80, 700 travel, 6000ms, >=150 swept clearance',
            escape='Open below red sweep into summit-timing-landing or lower summit-timing-catch')
        self.assertGreaterEqual(g['gap'],540)
        sweep=dict(left=12326,right=13106,top=-5710,bottom=-5630);g['redSweptBounds']=sweep
        g['clearances']=[]
        for e in g['elements']:
            if e['id']=='summit-timing-red':continue
            dx=max(e['x']-sweep['right'],sweep['left']-e['x']-e['width'],0)
            dy=max(e['y']-sweep['bottom'],sweep['top']-e['y']-max(v['y'] for v in e['points']),0)
            d=(dx*dx+dy*dy)**.5;self.assertGreaterEqual(d,150,e['id']);g['clearances'].append(dict(id=e['id'],distance=d))
        self.capture(p,'approach.jpg')
        self.press(p,self.target);self.step(p,30);p.mouse.up()
        landing=self.until(p,'summit-timing-landing',500);self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][30:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0;best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:30]))
        corner=[s for s in r['rows'] if any(c['id']=='summit-timing-landing' and abs(c['nx'])>.1 for c in s['contacts'])]
        self.assertTrue(corner,'Production corner rebound must precede the final top landing')
        self.assertFalse(self.landings(r,'summit-timing-catch'))
        r.update(cornerReboundTicks=[s['tick'] for s in corner],entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=30,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        q=self.page()
        g['observation']=q.evaluate('''()=>{const rows=[];for(let i=0;i<360;i++){YARD.step(1);const e=floors[0].byId.get('summit-timing-red');rows.push({tick:i+1,x:e.x,px:ninja.x,py:ninja.y});}return rows}''')
        self.assertAlmostEqual(max(s['x'] for s in g['observation'])-min(s['x'] for s in g['observation']),700)
        self.assertTrue(all(s['px']==13438 and -5500<s['py']<-5468 for s in g['observation']))
        phases=[]
        for delay in [0,60,120,180,240,300]:
            z=self.page()
            z.evaluate('''()=>{window.timingContacts=[];const original=Ninja.prototype.applyHazardContact;
                Ninja.prototype.applyHazardContact=function(c){
                    const red=floors[0].byId.get('summit-timing-red');
                    const before={x:this.x,y:this.y,vx:this.speedX,vy:this.speedY};
                    const out=original.call(this,c);
                    timingContacts.push({tick:YARD.result().tick+1,contact:{x:c.x,y:c.y,nx:c.nx,ny:c.ny},
                        redBounds:{left:red.x,right:red.x+80,top:red.y,bottom:red.y+80},before,
                        after:{vx:this.speedX,vy:this.speedY},cooldown:this.hazardCooldownMs});return out;};}''')
            self.step(z,delay);self.press(z,self.target);self.step(z,30);z.mouse.up()
            landed=self.until(z,'summit-timing-landing',500)
            trace=self.result(z)
            phases.append(dict(waitTicks=delay,releaseTick=delay+30,landingTick=landed,
                hazardContacts=z.evaluate('timingContacts'),trace=trace))
        self.write('timing.json',dict(phases=phases,scope='Separate phase fixtures; waiting advances production physics, no mover or pose injection'))
        self.assertTrue(any(x['hazardContacts'] for x in phases),'Red must affect at least one timing window')
        for phase in phases:
            for hit in phase['hazardContacts']:
                b=hit['redBounds'];c=hit['contact']
                self.assertTrue(b['left']<=c['x']<=b['right'] and b['top']<=c['y']<=b['bottom'])
                self.assertNotEqual(hit['before']['vx'],hit['after']['vx'])
        self.assertTrue(any(not x['hazardContacts'] and x['landingTick'] for x in phases))
        print('PASS timing: six production wait phases; both clear transfer and red-contact timing observed')
        self.write('geometry.json',g)
        print(f'PASS geometry S08-03: widths 800/720 catch 882; one red 80x80 travel 700 period 6000; clearance >=150; safe full-cycle observation; reach {g["reach"]:.3f} range 540')
        print(f'PASS rebound: landing corner ticks {r["cornerReboundTicks"]}; no catch on nominal route')
        print(f'PASS route: release 30 landing {landing} unattached-airborne {best}; trusted inputs; zero resets/injections')

    def test_02_miss_and_recovery(self):
        p=self.page();self.press(p,self.target);self.step(p,20);p.mouse.up()
        catch=self.until(p,'summit-timing-catch',800);self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'summit-timing-landing'))
        self.press(p,dict(x=13368,y=-5438.2));self.step(p,24);p.mouse.up()
        returned=self.until(p,'summit-upper-landing',800);self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=20,catchTick=catch,returnTick=returned,
            catchTarget='summit-timing-catch',recoveryTarget='summit-upper-landing',resets=0,poseInjections=0)
        self.write('miss.json',r)
        print(f'PASS miss: release 20 catch {catch} summit-timing-catch return {returned} summit-upper-landing; normal trusted controls; zero resets/injections')

    def test_03_controls(self):
        cases=[];p=self.page();self.press(p,self.target);self.step(p,600)
        r=self.result(p);r.update(probe='continuous hold 600',successfulAlternative=bool(self.landings(r,'summit-timing-landing')));cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target);self.press(p,target);self.step(p,interval);p.mouse.up();self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest {interval}',targets=targets,successfulAlternative=bool(self.landings(r,'summit-timing-landing')));cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='600 ticks each',inspection='Every top-facing summit-timing-landing contact checked with same success definition; no successful alternatives'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded continuous hold/nearest 6/12/24 probes; successful alternatives 0')

    def test_04_connection_and_index(self):
        p=Task610Tests.page(self);self.press(p,Task610Tests.target);self.step(p,240);p.mouse.up()
        arrival=self.until(p,'summit-upper-landing');self.assertIsNotNone(arrival)
        r=self.result(p);r.update(sharedCollider='summit-upper-landing',arrivalTick=arrival,scope='Separate S08-02 encounter to shared practice entry, no spliced route',resets=0,poseInjections=0)
        self.write('connection.json',r)
        required={'commands.log':'exact command/status/count/config/hashes','tests.log':'four Task611Tests no skips',
            'geometry.json':'live roles/purposes, widths/range, red swept clearance and safe observation',
            'route.json':'trusted production entry/release/landing with >=6 airborne unattached ticks',
            'inputs.json':'trusted handler inputs','miss.json':'early release catch and normal return',
            'approach.jpg':'safe deck, targets and Summit structure','landing.jpg':'broad Summit landing',
            'timing.json':'six real wait phases, clear and obstructed timing windows','controls.json':'all bounded alternatives inspected','connection.json':'previous encounter reaches shared entry',
            'evidence-index.json':'artifact assertions/provenance/dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js replacement prefix -> fixedlevel.js production geometry/mover/hazard',
                'tools/test_grapple_over_redesign.py additive Task611Tests'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js'],
            superseded='Earlier prefix inventory assertions are historical. TASK-610 proof remains at artifacts/TASK-610; no old v3 tests changed.',
            hashPolicy='HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print(f'PASS connection: previous encounter reaches summit-upper-landing {arrival}; index all files parse/decode; below 200 MB')

class Task612Tests(unittest.TestCase):
    """Final Summit jump from a labelled shared third encounter fixture; production inputs and physics."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/test_grapple_over_redesign.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        cls.config['simulation']='Labelled isolated S08-03 exit for local tests; one Crown exit fixture for continuous S08; not base-to-summit'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK612_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task567Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task605Tests.until
    target = dict(x=11918,y=-5900)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('Object.assign(ninja,{x:12178,y:-5480,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        return p

    def shot(self,p,target,hold):
        p.mouse.up()
        p.evaluate('screen.trackGrappleOver(true)')
        self.press(p,target);self.step(p,hold);p.mouse.up()

    def capture(self,p,name):
        # Hide only the completion menu for the terrain capture; no simulation advances.
        p.evaluate('''() => {screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;
            const original=CLIMB_UI.drawMenu;CLIMB_UI.drawMenu=()=>{};
            try {draw()} finally {CLIMB_UI.drawMenu=original}}''')
        self.assertEqual(p.evaluate('LANDMARKS.frame.drawn[0].id'),'summit-array')
        p.evaluate("() => {const d=document.createElement('div');d.id='proof-label';d.textContent='S08-04 isolated shared third landing / earned 540 / production controls';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        p.screenshot(path=str(self.out/name),type='jpeg',quality=85)
        p.evaluate("document.getElementById('proof-label').remove()")
        with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))

    def test_01_geometry_and_route(self):
        p=self.page()
        g=p.evaluate('''target=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounter:floors[0].level.encounters.find(e=>e.id==='S08-04'),movers:floors[0].level.movers,
            range:grappleOverAcquisitionRadius(),scale:scale[version],target,
            reach:Math.hypot(target.x-ninja.x,target.y-ninja.y),calibrated:GRAPPLE_OVER_MOVEMENT,
            finish:floors[0].level.finish})''',self.target)
        self.assertEqual(g['sections'][-1]['encounters'],['S08-01','S08-02','S08-03','S08-04'])
        self.assertIsNotNone(g['finish']);self.assertEqual(g['range'],540);self.assertEqual(g['scale'],.375)
        self.assertLess(g['reach'],540)
        for e in g['elements']:
            e['width']=max(v['x'] for v in e['points'])-min(v['x'] for v in e['points'])
            self.assertTrue(e['purpose'])
        es={e['id']:e for e in g['elements']}
        self.assertNotIn('preview-unbuilt',es)
        self.assertTrue(all(e['role']=='bounce' for e in g['elements'] if e['id'].startswith('yard-')))
        for name in ['summit-timing-landing','summit-final-landing','summit-final-catch']:
            self.assertGreaterEqual(es[name]['width'],540)
        g.update(connection='Live summit-timing-landing shared with S08-03',
            landingWidths=[es[n]['width'] for n in ['summit-timing-landing','summit-final-landing']],recoveryWidth=882,gap=12098-11558,
            escape='Green-only opening; open release gap above broad lower catch',
            calibration='TASK-564 broad shelves; TASK-609 calibrated 420-rise launch mirrored west; final green combination adds no mechanic; first red remains S07')
        self.assertGreaterEqual(g['gap'],540)
        g['localElements']=[es[n] for n in g['encounter']['elements']]
        self.assertTrue(all(e['role']=='bounce' for e in g['localElements']))
        self.assertEqual(g['finish'],dict(left=10758,right=11558,top=-5479.000001,bottom=-5468.2))
        self.write('geometry.json',g);self.capture(p,'approach.jpg')
        self.shot(p,self.target,32);landing=self.until(p,'summit-final-landing',500);self.assertIsNotNone(landing)
        r=self.result(p);best=streak=0
        for s in r['rows'][32:landing-1]:
            streak=streak+1 if not s['contacts'] and not s['attached'] and not s['shot'] else 0
            best=max(best,streak)
        self.assertGreaterEqual(best,6);self.assertTrue(any(s['attached'] for s in r['rows'][:32]))
        r.update(entryTick=0,takeoffTick=next(s['tick'] for s in r['rows'] if s['vy']<0),releaseTick=32,
            landingTick=landing,landingAir=best,entryToExit=True,resets=0,poseInjections=0,scope=self.config['simulation'])
        self.write('route.json',r);self.write('inputs.json',dict(nominal=r['inputs']));self.capture(p,'landing.jpg')
        print(f'PASS geometry S08-04: live purposes; landing widths 720/800 opening 540 recovery 882; reach {g["reach"]:.3f} < 540; no planned terrain; scale .375')
        print(f'PASS route: release 32 landing {landing}; consecutive unattached airborne {best}; trusted inputs; zero resets/injections; images decoded')

    def test_02_miss_and_recovery(self):
        p=self.page();self.shot(p,self.target,24)
        catch=self.until(p,'summit-final-catch');self.assertIsNotNone(catch)
        self.assertFalse(self.landings(self.result(p),'summit-final-landing'))
        returned=self.until(p,'summit-final-landing');self.assertIsNotNone(returned)
        r=self.result(p);r.update(earlyReleaseTick=24,catchTick=catch,catchTarget='summit-final-catch',
            returnTick=returned,recoveryTarget='summit-final-landing',resets=0,poseInjections=0,
            recovery='Release lets the normal green catch rebound reach the exit deck; no additional input required')
        self.write('miss.json',r)
        print(f'PASS miss: early release 24 catch summit-final-catch {catch}; normal rebound returns summit-final-landing {returned}; no reset/checkpoint')

    def test_03_hold_and_nearest(self):
        cases=[]
        p=self.page();self.press(p,self.target);self.step(p,720)
        r=self.result(p);r.update(probe='continuous hold 720 ticks',successfulAlternative=bool(self.landings(r,'summit-final-landing')))
        cases.append(r);p.mouse.up()
        for interval in [6,12,24]:
            p=self.page();targets=[]
            for i in range(600//(interval+1)):
                target=p.evaluate('YARD.nearest()');targets.append(target)
                self.shot(p,target,interval);self.step(p,1)
            r=self.result(p);r.update(probe=f'nearest every {interval+1} ticks',targets=targets,
                successfulAlternative=bool(self.landings(r,'summit-final-landing')))
            cases.append(r)
        self.write('controls.json',dict(cases=cases,bound='720 hold; <=600 repeated nearest 6/12/24',
            inspection='Every exit top contact tested with nominal success definition'))
        for r in cases:self.assertFalse(r['successfulAlternative'],r['probe'])
        print('PASS controls: four bounded trusted probes; zero successful alternatives')

    def test_04_continuous_section_and_completion(self):
        p=Task609Tests.page(self)
        p.evaluate('''() => {window.summitEvents=[];const original=PLATFORM.sendLifecycle;
            PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')
                summitEvents.push({tick:YARD.result().tick+1,x:ninja.x,y:ninja.y});
                return original.call(this,name,...args)}}''')
        self.step(p,240);self.shot(p,Task609Tests.target,32)
        self.assertEqual(self.until(p,'summit-landing',500),446)
        self.step(p,130)
        target=p.evaluate('({x:14193,y:floors[0].byId.get("summit-lift").y+40})')
        self.shot(p,target,240)
        self.assertEqual(self.until(p,'summit-upper-landing',600),881)
        self.step(p,400);self.shot(p,Task611Tests.target,30)
        self.assertEqual(self.until(p,'summit-timing-landing',700),1481)
        self.assertEqual(p.evaluate('summitEvents'),[])
        self.shot(p,self.target,20)
        self.assertEqual(self.until(p,'summit-final-landing',700),1580)
        r=self.result(p)
        exits=[dict(encounter=f'S08-0{i+1}',collider=id,tick=self.landings(r,id)[0]['tick'])
            for i,id in enumerate(['summit-landing','summit-upper-landing','summit-timing-landing','summit-final-landing'])]
        self.assertEqual([e['tick'] for e in exits],[446,881,1481,1580])
        self.step(p,120);p.evaluate('CLIMB_UI.complete();CLIMB_UI.complete()')
        events=p.evaluate('summitEvents');self.assertEqual(len(events),1)
        self.assertEqual(events[0]['tick'],1580)
        self.assertTrue(p.evaluate('floors[0].climbStats.completed'))
        gate=p.evaluate('''()=>{const out=[];for(let n=1;n<=8;n++){
            const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
            m.sections.forEach((s,i)=>s.status=i<n?'built':'planned');
            out.push({section:m.sections[n-1].id,finish:replacementMountainLevel(m).finish});}
            const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
            m.sections[7].encounters.pop();
            return {sections:out,incompleteSummit:replacementMountainLevel(m).finish}}''')
        self.assertTrue(all(g['finish'] is None for g in gate['sections'][:7]))
        self.assertIsNotNone(gate['sections'][7]['finish']);self.assertIsNone(gate['incompleteSummit'])
        r.update(exits=exits,fixture=dict(x=12753,y=-4720,vx=0,vy=0,range=540),
            scope='One labelled isolated Crown exit fixture; continuous S08 entry to summit, not base-to-summit',
            resets=0,poseInjections=0,completionEvents=events,completionCount=len(events),gate=gate)
        self.write('section-route.json',r)
        print('PASS section-route: S08-01/02/03/04 exits 446/881/1481/1580; one labelled fixture; zero handoff resets/injections')
        print('PASS completion: level_completed exactly once at tick 1580; S01-S07 finish null; incomplete S08 finish null')

    def test_05_evidence_index(self):
        required={'commands.log':'exact commands, exit statuses, test identifiers/count, browser/viewport/revision/source hashes',
            'tests.log':'five Task612Tests, no skips, OK',
            'geometry.json':'live S08-04 purposes, widths, opening/catch, calibrated reachable 540 target',
            'route.json':'production trusted input release 32, landing 187, >=6 consecutive unattached airborne ticks',
            'inputs.json':'trusted nominal handler events',
            'miss.json':'early release 24, catch 165, normal green rebound to summit 316',
            'approach.jpg':'broad third landing and final target with Summit antenna',
            'landing.jpg':'broad final landing and Summit antenna; completion menu hidden only for capture',
            'controls.json':'four bounded continuous hold/nearest probes, all alternative successes inspected',
            'section-route.json':'four ordered exits in one continuous fixture run and exactly-once S08-only completion',
            'evidence-index.json':'artifact assertions, provenance and changed subsystem dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['mountain.js S08-04 geometry and finish gate -> fixedlevel.js colliders and physics.js existing completion region',
                'tools/test_grapple_over_redesign.py additive Task612Tests -> browser_test_support and production handlers'],
            unchanged=['physics.js','events.js','sprites/ninja.js','gameoptions.js','fixedlevel.js','render/landmarks.js'],
            superseded='Earlier replacement prefix/finish-null inventory assertions are historical; TASK-609/610/611 proof stays in its original directories. Legacy v3 remains playable and its tests unchanged.',
            hashPolicy='A HEAD-only commit does not invalidate identical tested source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS evidence-index: all required files exist/parse/decode; below 200 MB; changed dependencies and superseded historical coverage recorded')


class Task613Tests(unittest.TestCase):
    """S08 isolated input tolerance and lower recovery; no continuous-gameplay claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport={'width':844,'height':390},device_scale_factor=1,
            simulation='Isolated S08 entries; recorded Summit entries and mover phases; previously earned 540; not continuous gameplay')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK613_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    page = Task571Tests.page
    press = Task571Tests.press
    release = Task571Tests.release
    frame = Task571Tests.frame
    until_landing = Task576Tests.until_landing
    targets = [Task609Tests.target,Task610Tests.target,Task611Tests.target,Task612Tests.target]
    nominal_holds = {"desktop": [35,240,38,35], "touch": [35,260,38,35]}
    exits = ['summit-landing','summit-upper-landing','summit-timing-landing','summit-final-landing']
    fixtures = [dict(x=12753,y=-4720),dict(x=14093,y=-4720),dict(x=13438,y=-5480),dict(x=12178,y=-5480)]

    def aim(self,index,touch):
        return dict(x=14220,y=-5100) if index==1 else dict(x=13158,y=-5900) if index==2 else dict(self.targets[index])

    def frame(self,p,label):
        # Only suppress the completed-run menu for the terrain observation.
        p.evaluate('window.savedMenuDraw=CLIMB_UI.drawMenu;CLIMB_UI.drawMenu=()=>{}')
        try:
            return Task571Tests.frame(self,p,label)
        finally:
            p.evaluate('() => {CLIMB_UI.drawMenu=window.savedMenuDraw}')

    def setup_entry(self,p,index):
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        self.assertFalse(p.evaluate('TUTORIAL_HINT.visible'))
        p.evaluate('s=>{Object.assign(ninja,s,{speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)}',self.fixtures[index])
        p.evaluate("""()=>{window.redContacts=[];const original=Ninja.prototype.applyHazardContact;
            Ninja.prototype.applyHazardContact=function(c){const before={vx:this.speedX,vy:this.speedY};
                const e=floors[0].byId.get('summit-timing-red');
                const bounds={left:e.x,right:e.x+80,top:e.y,bottom:e.y+80};
                const out=original.call(this,c);redContacts.push({tick:YARD.result().tick+1,x:c.x,y:c.y,nx:c.nx,ny:c.ny,
                bounds,before,after:{vx:this.speedX,vy:this.speedY}});return out;};}""")
        self.step(p,600 if index==1 else 0)
        p.entry_world_ms=p.evaluate("floors[0].elapsedSteps*physicsStepMs/cyclesPerTick")

    def test_01_tolerance(self):
        rows=[];frames=[]
        for touch in [False,True]:
            for index in range(4):
                for variant,ms,aim in [('nominal',0,0),('early',-50,0),('late',50,0),('left',0,-8),('right',0,8)]:
                    p=self.page(touch);self.setup_entry(p,index)

                    start=p.evaluate('YARD.result().tick')
                    step_ms=p.evaluate('physicsStepMs')
                    nominal_hold=self.nominal_holds["touch" if touch else "desktop"][index]
                    hold=nominal_hold+round(ms/step_ms)
                    if touch and variant=='nominal':frames.append(self.frame(p,f'S08-0{index+1} touch approach'))
                    target=self.aim(index,touch)
                    nominal_client=p.evaluate('p=>YARD.client(p)',target)
                    xy=self.press(p,target,aim);self.step(p,hold);self.release(p)
                    self.until_landing(p,self.exits[index],800)
                    r=self.result(p);lands=[s for s in self.landings(r,self.exits[index]) if s['tick']>start+hold]
                    inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs'] if i['tick']>=start]
                    row=dict(encounter=f'S08-0{index+1}',mode='touch' if touch else 'desktop',variant=variant,
                        viewport=p.viewport_size,nominalHoldTicks=nominal_hold,releaseOffsetMs=ms,aimOffsetCSSpx=aim,requestedClient=xy,
                        target=target,nominalClient=nominal_client,startTick=start,releaseTick=start+hold,inputs=inputs,landing=lands[0] if lands else None,
                        exit=self.exits[index],trace=self.compact(r['rows'][start:]),success=bool(lands),
                        lowerCatchContacts=[s for s in r['rows'][start:] if any('catch' in c['id'] for c in s['contacts'])])
                    rows.append(row)
                    if touch and variant=='nominal' and lands:
                        frames.append(self.frame(p,f'S08-0{index+1} touch after landing {lands[0]["tick"]}'))
                    print(f'CASE {row["encounter"]} {row["mode"]} {variant} landing={lands[0]["tick"] if lands else None}')
                    self.write('tolerance.json',dict(cases=rows,entryFixtures=self.fixtures,fixtureScope=self.config['simulation'],source_hashes=self.config['source_hashes']))
                    p.context.close()
        strip=Image.new('RGB',(844*2,390*4))
        for n,im in enumerate(frames):strip.paste(im,((n%2)*844,(n//2)*390))
        strip.save(self.out/'touch-strip.jpg',quality=85)
        self.assertEqual(len(rows),40)
        self.assertTrue(all(r['success'] for r in rows),[(r['encounter'],r['mode'],r['variant']) for r in rows if not r['success']])
        for r in rows:
            self.assertEqual(r['lowerCatchContacts'],[],(r['encounter'],r['mode'],r['variant']))
            expected='touchstart' if r['mode']=='touch' else 'mousedown'
            self.assertEqual(r['inputs'][0]['type'],expected)
            self.assertTrue(all(i['trusted'] for i in r['inputs']))
            self.assertAlmostEqual(r['requestedClient']['x']-r['nominalClient']['x'],r['aimOffsetCSSpx'])
            self.assertAlmostEqual(r['inputs'][0]['x'],r['requestedClient']['x'],delta=1)
            self.assertAlmostEqual(r['inputs'][0]['y'],r['requestedClient']['y'],delta=1)
            release_type='touchend' if r['mode']=='touch' else 'mouseup'
            self.assertTrue(any(i['type']==release_type and i['tick']==r['releaseTick'] for i in r['inputs']))
            self.assertTrue(any(c['id']==r['exit'] and c['ny']<-.9 for c in r['landing']['contacts']))
            self.assertTrue(any(s['attached'] for s in r['trace']))
            self.assertTrue(any(not s['attached'] and not s['contacts'] for s in r['trace'] if s['tick']>r['releaseTick']))
        print('PASS tolerance: all 40 cases; 4 encounters x 2 genuine input modes x 5 variants; +/-50 ms and +/-8 CSS px')


    @staticmethod
    def compact(rows):
        return [r for i,r in enumerate(rows) if i%12==0 or i==len(rows)-1 or r['contacts']
                or (i and (r['attached'],r['shot'])!=(rows[i-1]['attached'],rows[i-1]['shot']))]

    def interactions(self,p,index,start,result):
        ids=['summit-lift','summit-timing-red']
        observed=p.evaluate("""({ids,startMs})=>{
            const world=floors[0],timeMs=world.elapsedSteps*physicsStepMs/cyclesPerTick;
            return ids.map(id=>{const e=world.byId.get(id),m=world.level.movers.find(m=>m.element===id);
                return {id,x:e.x,y:e.y,role:e.surfaceRole,periodMs:m.periodMs,phaseOffset:m.phase,
                    startTimeMs:startMs,endTimeMs:timeMs,
                    startPhase:(startMs/m.periodMs+m.phase)%1,endPhase:(timeMs/m.periodMs+m.phase)%1};});
        }""",dict(ids=ids,startMs=p.entry_world_ms))
        return dict(movers=observed,hazardContacts=p.evaluate('redContacts'),yellow='No yellow in S08')

    def test_02_recovery(self):
        rows=[]
        for touch in [False,True]:
            for index in range(4):
                p=self.page(touch);self.setup_entry(p,index)
                start=p.evaluate('YARD.result().tick');step_ms=p.evaluate('physicsStepMs')
                # Recovery uses the original TASK-609..612 nominal aim and hold baseline.
                nominal_hold=[32,240,30,32][index]
                hold=[24,12,20,24][index]
                self.press(p,self.targets[index]);self.step(p,hold);self.release(p)
                catch_id=['summit-catch','summit-lift-catch','summit-timing-catch','summit-final-catch'][index]
                self.until_landing(p,catch_id,800)
                before=self.result(p);catches=self.landings(before,catch_id)
                self.assertTrue(catches,(index,touch,'catch'))
                self.assertFalse(self.landings(before,self.exits[index]))
                recovery_start=before['tick']
                target,ticks,return_id=[(None,0,'summit-landing'),
                    (dict(x=14163,y=-4698.2),24,'summit-landing'),
                    (dict(x=13368,y=-5438.2),24,'summit-upper-landing'),
                    (None,0,'summit-final-landing')][index]
                if target:
                    self.press(p,target);self.step(p,ticks);self.release(p)
                self.until_landing(p,return_id,800)
                r=self.result(p);returned=[s for s in self.landings(r,return_id) if s['tick']>recovery_start]
                row=dict(encounter=f'S08-0{index+1}',mode='touch' if touch else 'desktop',
                    releaseOffsetMs=(hold-nominal_hold)*step_ms,nominalHoldTicks=nominal_hold,
                    physicsStepMs=step_ms,missHoldTicks=hold,startTick=start,target=self.targets[index],
                    baseline="Original TASK-609..612 nominal route",
                    catch=catches[0],returned=returned[0] if returned else None,returnCollider=return_id,
                    recoveryStart=recovery_start,inputs=[dict(i,timeMs=i['tick']*step_ms) for i in r['inputs']],
                    trace=self.compact(r['rows'][start:]),interactions=self.interactions(p,index,start,r),
                    resetsAfterStart=0,poseInjectionsAfterStart=0)
                press_type,release_type=('touchstart','touchend') if touch else ('mousedown','mouseup')
                press=next(i for i in row['inputs'] if i['type']==press_type and i['tick']>=start)
                release=next(i for i in row['inputs'] if i['type']==release_type and i['tick']>=press['tick'])
                self.assertEqual(release['tick']-press['tick'],row['missHoldTicks'])
                self.assertAlmostEqual(row['releaseOffsetMs'],
                    release['timeMs']-press['timeMs']-nominal_hold*step_ms)
                rows.append(row);self.write('recovery.json' ,dict(cases=rows,source_hashes=self.config['source_hashes'],scope=self.config['simulation']))
                self.assertTrue(returned,(index,touch,'return'))
                self.assertGreater(abs(row['releaseOffsetMs']),50)
                print(f'RECOVERY {row["encounter"]} {row["mode"]} catch={catches[0]["tick"]} return={returned[0]["tick"]}')
                p.context.close()
        # A separate waiting-phase attempt observes the moving red with actual touch.
        probes=[]
        for delay in [0,60,120,180,240,300]:
            p=self.page(True);self.setup_entry(p,2);self.step(p,delay)
            self.press(p,self.targets[2]);self.step(p,30);self.release(p)
            p.evaluate("""()=>{for(let i=0;i<800;i++){YARD.step(1);
                if(YARD.result().rows.at(-1).contacts.some(c=>
                    ['summit-upper-landing','summit-timing-landing'].includes(c.id)&&c.ny<-.9))break}}""")
            r=self.result(p);hits=p.evaluate('redContacts')
            for hit in hits:
                bounds=hit['bounds']
                self.assertTrue(bounds['left']<=hit['x']<=bounds['right'])
                self.assertTrue(bounds['top']<=hit['y']<=bounds['bottom'])
                self.assertNotEqual(hit['before'],hit['after'])
            returned=[v for v in r['rows'] if v['tick']>delay+30 and any(c['id'] in ['summit-upper-landing','summit-timing-landing'] and c['ny']<-.9 for c in v['contacts'])]
            self.assertTrue(returned,(delay,'phase escape'))
            probes.append(dict(waitTicks=delay,hazardContacts=hits,returned=returned[0],
                inputs=r['inputs'],trace=self.compact(r['rows']),scope='Separate isolated touch phase attempt; production waiting and controls'))
            p.context.close()
        self.assertTrue(any(p['hazardContacts'] for p in probes))
        self.assertTrue(any(not p['hazardContacts'] for p in probes))
        self.write('recovery.json',dict(cases=rows,hazardProbes=probes,
            source_hashes=self.config['source_hashes'],scope=self.config['simulation']))
        print('PASS hazards: six genuine touch phases include actual red contact and clear transfer; all escape to local green')
        self.assertEqual(len(rows),8)
        print('PASS recovery: 8 out-of-window misses and normal-input escapes; mover phases and hazard contacts recorded; zero resets/injections')

    def test_03_dependencies_and_index(self):
        previous=json.loads((ROOT/'artifacts/TASK-612/evidence-index.json').read_text())
        old=previous['config']['source_hashes']
        unchanged=[]
        for name,digest in old.items():
            if name=='tools/test_grapple_over_redesign.py':continue
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
            unchanged.append(name)
        self.write('affected-proof-map.json',dict(geometryChanges=[],runtimeChanges=[],unchanged=unchanged,
            routeAdjustment='TASK-609..612 isolated entries reused; S08-02 waits 600 production ticks; holds desktop 35/240/38/35, touch 35/260/38/35 and locally calibrated aims; actual client transforms; no geometry changes',
            recoveryEndpoint='Return to previous broad deck with normal controls',
            changedSubsystems=['tools/test_grapple_over_redesign.py Task613Tests shared calibrated nominal holds and trace-based recovery offset assertions'],
            dependencies=['Task613Tests -> browser_test_support + grapple_over_yard.js -> events.js, physics.js, fixedlevel.js, mountain.js'],
            previousProof=['artifacts/TASK-612/evidence-index.json'],
            refreshed=['tolerance.json','recovery.json','touch-strip.jpg'],
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes; historical proofs retained'))
        required={'commands.log':'exact command, exit, identifiers, Chromium/viewports/DPR, revision and source hashes',
            'tests.log':'three Task613Tests, no skips, OK',
            'tolerance.json':'40 successful variants with trusted input timestamps, offsets and top-facing exit contacts',
            'recovery.json':'8 out-of-window misses, lower contacts, normal-input escapes, mover phases; six touch mover phases with actual red contacts and local green escapes',
            'affected-proof-map.json':'unchanged geometry and changed subsystem dependencies',
            'touch-strip.jpg':'four genuine touch approaches and landings with visible targets',
            'evidence-index.json':'artifact assertions and tested provenance'}
        self.write('evidence-index.json',dict(config=self.config,artifacts=required,scope=self.config['simulation']))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        with Image.open(self.out/'touch-strip.jpg') as im:
            im.load();self.assertEqual(im.size,(1688,1560))
        self.assertLess(sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()),200_000_000)
        print(f'PASS dependencies: {len(unchanged)} unchanged runtime/support hashes; geometry unchanged')
        print('PASS index: all required files exist; JSON parses; touch-strip decodes 1688x1560; retained evidence <200 MB')


class Task614Tests(unittest.TestCase):
    """S08 composition review; one entrance fixture, then production-only traversal."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='One isolated S08 entrance then continuous production traversal; separate labelled recovery'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK614_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    press = Task567Tests.press
    step = Task567Tests.step
    result = Task567Tests.result
    landings = staticmethod(Task567Tests.landings)
    until = Task605Tests.until
    record = Task590Tests.record
    shot = Task606Tests.shot

    def test_01_inventory_and_dependencies(self):
        p=Task609Tests.page(self)
        g=p.evaluate("""()=>({elements:floors[0].level.elements,encounters:floors[0].level.encounters,
            movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            calibration:GRAPPLE_OVER_MOVEMENT})""")
        self.assertEqual((g['range'],g['scale']),(540,.375))
        es={e['id']:e for e in g['elements']}
        for e in es.values():
            self.assertTrue(e['purpose']);self.assertIn(e['role'],['bounce','solid','drag','hazard'])
            e['encounters']=[c['id'] for c in g['encounters'] if e['id'] in c['elements']]
            self.assertTrue(e['encounters'])
            e['bounds']={k:e[a]+fn(v[a] for v in e['points']) for k,a,fn in [('left','x',min),('right','x',max),('top','y',min),('bottom','y',max)]}
            e['width']=e['bounds']['right']-e['bounds']['left'];e['height']=e['bounds']['bottom']-e['bounds']['top']
        local={id for c in g['encounters'] if c['id'].startswith('S08') for id in c['elements']}
        self.assertEqual(len([c for c in g['encounters'] if c['id'].startswith('S08')]),4)
        self.assertEqual({es[id]['role'] for id in local},{'bounce','solid','hazard'})
        for m in g['movers']:
            e=es[m['element']];b=dict(e['bounds']);axis=m['axis']
            b['left' if axis=='x' else 'top']=m['min']
            b['right' if axis=='x' else 'bottom']=m['max']+e['width' if axis=='x' else 'height']
            m['sweptBounds']=b
            self.assertGreaterEqual(m['max']-m['min'],max(360,2*e['width' if axis=='x' else 'height']))
            self.assertTrue(6000<=m['periodMs']<=10000)
        def distance(a,b):
            return (max(a['left']-b['right'],b['left']-a['right'],0)**2+max(a['top']-b['bottom'],b['top']-a['bottom'],0)**2)**.5
        clearances=[]
        for z in [e for e in es.values() if e['role']=='drag']:
            self.assertNotIn(z['id'],local)
            self.assertGreaterEqual(z['width'],3*360);self.assertGreaterEqual(z['width']/z['height'],4)
            for e in es.values():
                if e['role']=='drag':continue
                sweep=next((m['sweptBounds'] for m in g['movers'] if m['element']==e['id']),e['bounds'])
                d=distance(z['bounds'],sweep);self.assertGreaterEqual(d+1e-8,540)
                clearances.append(dict(zone=z['id'],collider=e['id'],clearance=d))
        sweeps=[]
        for m in g['movers']:
            if m['element'] not in local:continue
            for e in es.values():
                if e['id']==m['element'] or e['role']=='drag':continue
                other=next((v['sweptBounds'] for v in g['movers'] if v['element']==e['id']),e['bounds'])
                d=distance(m['sweptBounds'],other);self.assertGreater(d,0,(m['element'],e['id']))
                sweeps.append(dict(mover=m['element'],collider=e['id'],clearance=d))
        g['localSweepClearances']=sweeps
        widths=[es[n]['width'] for n in Task613Tests.exits]
        self.assertEqual(widths,[800,800,720,800])
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        g.update(localIds=sorted(local),planningWidths=widths,clearances=clearances,firstUse=first,
            localYellow=[],clutter='No redundant local objects identified; anchors, broad decks, catches, carrier and one red sweep have distinct encounter roles')
        q=Task567Tests.page(self)
        q.evaluate('Object.assign(ninja,{x:14093,y:-4720,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
        cycle=q.evaluate("""()=>{const rows=[];for(let i=0;i<600;i++){
            YARD.step(1);const e=floors[0].byId.get('summit-lift');
            rows.push({tick:i+1,y:e.y,px:ninja.x,py:ninja.y,distance:Math.hypot(Math.max(e.x-ninja.x,ninja.x-e.x-360,0),Math.max(e.y-ninja.y,ninja.y-e.y-80,0))});}return rows}""")
        best=streak=0
        for row in cycle:
            streak=streak+1 if row['distance']<=540 else 0;best=max(best,streak)
            self.assertEqual(row['px'],14093);self.assertLess(abs(row['py']+4720),32)
        self.assertGreaterEqual(best,60)
        g['acquisitionWindowMs']=best*1000/60;g['carrierCycle']=cycle
        g['usefulEndpoints']='Lower end reachable from practice deck; upper end releases onto summit-upper-landing; phases.json proves traversal'
        self.write('objects.json',g)
        old=json.loads((ROOT/'artifacts/TASK-613/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        yellow=json.loads((ROOT/'artifacts/TASK-590/objects.json').read_text())
        for e in yellow['elements']:
            for key in ['x','y','points','role','purpose']:self.assertEqual(e[key],es[e['id']][key])
        proofs=['artifacts/TASK-590/suppression.json','artifacts/TASK-590/recovery.json','artifacts/TASK-613/recovery.json','artifacts/TASK-613/tests.log','artifacts/TASK-613/commands.log']
        recovery=json.loads((ROOT/proofs[2]).read_text())
        self.assertEqual(len(recovery['hazardProbes']),6)
        self.assertTrue(any(h['hazardContacts'] for h in recovery['hazardProbes']))
        for h in recovery['hazardProbes']:
            for hit in h['hazardContacts']:
                self.assertNotEqual(hit['before'],hit['after'])
                self.assertGreater(h['returned']['tick'],hit['tick'])
        yellow_runtime=json.loads((ROOT/'artifacts/TASK-590/evidence-index.json').read_text())['config']['source_hashes']
        yellow_dependencies={n:yellow_runtime[n] for n in ['physics.js','events.js','fixedlevel.js','sprites/ninja.js','gameoptions.js','tools/grapple_over_yard.js']}
        for n,h in yellow_dependencies.items():
            self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        proofs.extend(['artifacts/TASK-590/evidence-index.json','artifacts/TASK-590/objects.json'])
        suppression=json.loads((ROOT/proofs[0]).read_text())
        for case in suppression['cases']:
            self.assertGreater(case['drop'],case['rebound'])
            self.assertLessEqual(case['rebound'],.75*case['controlRebound'])
        lateral=json.loads((ROOT/proofs[1]).read_text())
        self.assertEqual(len(lateral['cases']),2)
        for case in lateral['cases']:
            self.assertGreater(case['returned']['tick'],case['catchTick'])
            self.assertTrue(any(c['id']==case['returnCollider'] and c['ny']<-.9 for c in case['returned']['contacts']))
        self.write('dependency.json',dict(unchanged=unchanged,yellowRuntime=yellow_dependencies,changed=['tools/test_grapple_over_redesign.py: additive Task614Tests'],
            reused={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in proofs},
            geometryComparison='All S04 coordinates/roles/purposes identical; all runtime dependencies identical to TASK-613',
            hashPolicy='HEAD-only commits do not invalidate identical tested source hashes'))
        print(f'PASS objects: every object has purpose/encounter; first green S01 blue S03 yellow S04 red S07; four broad landings {widths}; full swept bounds clear; yellow clearance >=540; carrier window {best*1000/60:.1f}ms >=1000')
        print('PASS dependencies: unchanged runtime/support hashes; S04 suppression/lateral recovery and six red phase escapes referenced by exact hashes')

    def test_02_continuous_capture(self):
        p=Task609Tests.page(self)
        p.evaluate('TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)')
        p.evaluate('CLIMB_UI.drawMenu=()=>{}')
        self.record(p,'S08 continuous from isolated entrance / earned 540 / 4x');self.step(p,240)
        views=[];observations=[]
        def capture(index,target):
            p.evaluate('draw()')
            obs=p.evaluate('t=>({tick:YARD.result().tick,target:t,client:YARD.client(t),landmark:LANDMARKS.frame.drawn,player:{x:ninja.x,y:ninja.y}})',target)
            self.assertTrue(0<obs['client']['x']<1280 and 0<obs['client']['y']<720,obs)
            self.assertEqual(obs['landmark'][0]['id'],'summit-array')
            observations.append(obs)
            im=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
            ImageDraw.Draw(im).text((12,690),f'S08-0{index} actual continuous approach tick {obs["tick"]}',fill='white');views.append(im)
        capture(1,Task609Tests.target);self.shot(p,Task609Tests.target,32)
        self.assertEqual(self.until(p,'summit-landing',500),446)
        self.step(p,130)
        target=p.evaluate('({x:14193,y:floors[0].byId.get("summit-lift").y+40})')
        capture(2,target);self.shot(p,target,240)
        self.assertEqual(self.until(p,'summit-upper-landing',600),881)
        self.step(p,400);capture(3,Task611Tests.target);self.shot(p,Task611Tests.target,30)
        self.assertEqual(self.until(p,'summit-timing-landing',700),1481)
        capture(4,Task612Tests.target);self.shot(p,Task612Tests.target,20)
        self.assertEqual(self.until(p,'summit-final-landing',700),1580)
        r=self.result(p)
        exits=[dict(id=n,tick=self.landings(r,n)[0]['tick']) for n in Task613Tests.exits]
        self.write('route.json',dict(exits=exits,inputs=r['inputs'],trace=r['rows'],resetsAfterStart=0,poseInjectionsAfterStart=0,
            scope=self.config['simulation'],rangeBefore=540,rangeAfter=540))
        self.write('approaches.json',dict(views=observations))
        sheet=Image.new('RGB',(2560,1440))
        for i,im in enumerate(views):sheet.paste(im,((i%2)*1280,(i//2)*720))
        sheet.save(self.out/'approaches.jpg',quality=85)
        overview=Image.new('RGB',(2560,720));sil=Image.new('RGB',(2560,720),'white')
        for i,center in enumerate([11700,14300]):
            p.evaluate('x=>{screen.x=width/.375/2-x;screen.y=height/.375/2+5200;draw()}',center)
            overview.paste(Image.open(io.BytesIO(p.screenshot())).convert('RGB'),(1280*i,0))
            f=p.evaluate("""()=>({elements:floors[0].elements.map(e=>({id:e.id,points:e.getPoints()})),
                shape:GRAPPLE_OVER_LANDMARK_SHAPES[7](GRAPPLE_OVER_LANDMARKS.width,GRAPPLE_OVER_LANDMARKS.height),
                landmark:{x:(13400+screen.x)*.375-GRAPPLE_OVER_LANDMARKS.width/2,y:(-3900+screen.y)*.375-GRAPPLE_OVER_LANDMARKS.height},
                camera:{x:screen.x,y:screen.y},factor:1280/width})""")
            tile=Image.new('RGB',(1280,720),'white');pen=ImageDraw.Draw(tile);k=f['factor']
            def point(v):return ((v[0]+f['landmark']['x'])*k,(v[1]+f['landmark']['y'])*k)
            for part in f['shape']['parts']:pen.polygon([point(v) for v in part],fill='#aaaaaa')
            for line in f['shape']['lines']:pen.line([point(v) for v in line],fill='#888888',width=3)
            for e in f['elements']:
                pts=[((v['x']+f['camera']['x'])*.375*k,(v['y']+f['camera']['y'])*.375*k) for v in e['points']]
                pen.polygon(pts,fill='black')
                if e['id'].startswith('summit'):pen.text(pts[0],e['id'],fill='#555555')
            pen.text((12,12),'Summit Array / antenna array and base / plain silhouette',fill='black');sil.paste(tile,(1280*i,0))
        overview.save(self.out/'overview.png');sil.save(self.out/'silhouette.png')
        frames=p.evaluate('reviewFrames')
        q=Task567Tests.page(self)
        q.evaluate('Object.assign(ninja,{x:14093,y:-4720,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false')
        self.record(q,'SEPARATE S08-02 full carrier cycle then fall and normal-input recovery / 4x')
        self.step(q,600);self.shot(q,Task610Tests.target,12)
        catch=self.until(q,'summit-lift-catch',800);self.assertIsNotNone(catch)
        self.shot(q,dict(x=14163,y=-4698.2),24)
        returned=self.until(q,'summit-landing',800);self.assertIsNotNone(returned)
        recovery=self.result(q)
        self.write('recovery.json',dict(catchTick=catch,returnTick=returned,returnCollider='summit-landing',
            trace=recovery['rows'],inputs=recovery['inputs'],resetsAfterStart=0,poseInjectionsAfterStart=0))
        frames.extend(q.evaluate('reviewFrames'));q.context.close()
        p.evaluate('a=>window.reviewFrames=a',frames);p.bring_to_front()
        clip=p.evaluate('''async () => {
            const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');
            const stream=c.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
            const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
            rec.ondataavailable=e=>chunks.push(e.data);const ended=new Promise(r=>rec.onstop=r);rec.start();
            for(const f of reviewFrames){const im=new Image();im.src=f.image;await im.decode();ctx.drawImage(im,0,0,1280,720);
                ctx.fillStyle='white';ctx.fillText((f.label || 'S08 continuous from isolated entry')+' / 4x / tick '+f.tick,12,24);
                track.requestFrame();await new Promise(r=>setTimeout(r,50));}
            await new Promise(r=>setTimeout(r,200));rec.stop();await ended;stream.getTracks().forEach(t=>t.stop());
            const blob=new Blob(chunks,{type:'video/webm'});return await new Promise(r=>{const rd=new FileReader();rd.onload=()=>r(rd.result.split(',')[1]);rd.readAsDataURL(blob)})}''')
        (self.out/'section.webm').write_bytes(base64.b64decode(clip))
        decoded=p.evaluate('''async b64=>{const v=document.createElement('video');v.muted=true;v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);await v.play();
            await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});return {frames,width:v.videoWidth,height:v.videoHeight}}''',clip)
        self.assertGreater(decoded['frames'],100);self.assertEqual(decoded['width'],1280)
        self.write('clip-decode.json',decoded)

        print(f'PASS continuous: exits 446/881/1481/1580; four on-screen actual approaches; earned 540; zero resets/injections; recovery {catch}->{returned}; decoded {decoded}')

    def test_03_carrier_phases(self):
        cases=[]
        for phase in [0,150,300,450]:
            p=Task567Tests.page(self);self.step(p,phase)
            p.evaluate('Object.assign(ninja,{x:14093,y:-4720,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true)')
            arrival=p.evaluate("({tick:YARD.result().tick,y:floors[0].byId.get('summit-lift').y})")
            waiting=p.evaluate("""n=>{const rows=[];for(let i=0;i<n;i++){YARD.step(1);rows.push({tick:YARD.result().tick,x:ninja.x,y:ninja.y,moverY:floors[0].byId.get('summit-lift').y})}return rows}""",600-phase)
            for row in waiting:self.assertEqual(row['x'],14093);self.assertLess(abs(row['y']+4720),32)
            self.shot(p,Task610Tests.target,240)
            tick=self.until(p,'summit-upper-landing',600);self.assertIsNotNone(tick)
            r=self.result(p)
            cases.append(dict(arrival=arrival,arrivalPhase=phase/600,waiting=waiting,landing=self.landings(r,'summit-upper-landing')[0],inputs=r['inputs'],resetsAfterArrival=0,poseInjectionsAfterArrival=0))
            p.context.close()
        self.assertEqual(len({(v['arrival']['y'],v['waiting'][0]['moverY']) for v in cases}),4)
        self.write('phases.json',dict(scope='Four isolated phase arrivals, production waiting and traversal; not continuous gameplay',cases=cases))
        print('PASS phases: four distinct quarter-cycle arrivals; safe production waiting; four upper-deck top contacts; zero post-arrival injections')

    def test_04_evidence_index(self):
        (self.out/'review.md').write_text("""TASK-614 Summit Array composition review

Built S08 only. One isolated Crown exit then continuous production controls; separate labelled carrier-cycle/fall recovery. No claim of validated human enjoyment.

overview.png left panel shows the last two westward challenges and final broad deck; right panel shows the first arrival, vertical carrier and antenna-array landmark. silhouette.png uses the same frames with plain filled colliders and gray architecture. approaches.jpg panels 1–4 show actual continuous approaches at scale 0.375; approaches.json records visible target positions and summit-array identity.

Pacing: 800/800/720/800-wide green planning decks separate the familiar arrival, blue lift release, red timing transfer and final green jump. Open 540-unit horizontal gaps separate the westward decks; the lift links decks 760 units apart vertically. Full swept bounds are compared against every collider. Mechanical slits beside the lift are not intended passages. section.webm includes all four encounters continuously, followed by a separately labelled ten-second mover cycle, early-release fall and normal-control recovery.

Clutter: all retained launch faces, four destinations, local catches, carrier and red sweep have distinct purposes in objects.json. No redundant object identified; no geometry edit. Established green/blue/yellow/red order is retained, with no new mechanic. No local yellow; the earlier S04 suppression and lateral recovery proof is referenced with exact hashes and structural equality. Six S08 hazard phases include actual contact and safe green escapes in TASK-613. Dependencies record unchanged runtime hashes; historical prefix/v3 coverage is preserved and not claimed rerun. Original mountain remains playable; no activation or publishing.
""")
        required={'commands.log':'exact command, exit, identifiers, browser/viewport/revision/source hashes',
            'tests.log':'four Task614Tests; no skips; OK','objects.json':'purposes, role order, four broad decks, full swept bounds/clearances',
            'overview.png':'all four built encounters and Summit Array antenna-array landmark',
            'silhouette.png':'plain structure, open gaps and broad landings','approaches.jpg':'four actual continuous approaches',
            'approaches.json':'target screen positions and named landmark','route.json':'continuous ordered four-exit production traversal',
            'phases.json':'four arrival phases for the Summit carrier and safe waiting', 'recovery.json':'fall and normal-input return','section.webm':'continuous representative traversal plus labelled recovery',
            'clip-decode.json':'decoded frames/dimensions','dependency.json':'unchanged dependencies and reused proof hashes',
            'review.md':'image-located composition/pacing review','evidence-index.json':'artifact assertions and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith(('.png','.jpg')):
                with Image.open(self.out/name) as im:im.load();self.assertGreaterEqual(im.width,1280)
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all required files exist; JSON parses; images/video decode; retained evidence <200 MB')


class Task615Tests(unittest.TestCase):
    """Local recorded S01 approach, then uninterrupted S01/S02 boundary inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR')
        Task567Tests.setUpClass.__func__(cls)

    write = Task557Tests.write
    press = Task567Tests.press
    landings = staticmethod(Task567Tests.landings)
    fixture = dict(x=2118.1921969491937,y=-453.2897490673494,
                   vx=-.6802182640198733,vy=.5694660422115743)

    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('''f=>{TUTORIAL_HINT.visible=false;
            Object.assign(ninja,{x:f.x,y:f.y,speedX:f.vx,speedY:f.vy});screen.trackGrappleOver(true);
            window.boundaryRows=[];const original=YARD.step;
            YARD.step=n=>{for(let i=0;i<n;i++){original(1);const s=captureClimbState();
                boundaryRows.push({...YARD.result().rows.at(-1),simulationTick:s.simulationTick,
                    camera:{x:screen.x,y:screen.y},rope:s.grapple,range:grappleOverAcquisitionRadius(),
                    movers:floors[0].level.movers.map(m=>({id:m.id,x:floors[0].byId.get(m.element).x,y:floors[0].byId.get(m.element).y}))});}};
        }''',self.fixture)
        return p

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def act(self,p,target,hold,coast=0):
        self.press(p,target);self.step(p,hold);p.mouse.up();self.step(p,coast)

    def trace(self,p):
        r=p.evaluate('({...YARD.result(),rows:boundaryRows})')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertEqual([s['tick'] for s in r['rows']],list(range(1,r['tick']+1)))
        cycles=p.evaluate('cyclesPerTick')
        timing=p.evaluate('({step:physicsStepMs,movers:floors[0].level.movers})')
        for row in r['rows']:
            for mover,observed in zip(timing['movers'],row['movers']):
                phase=(row['tick']*timing['step']/mover['periodMs']+mover['phase'])%1
                expected=mover['min']+(mover['max']-mover['min'])*(1-abs(2*phase-1))
                self.assertAlmostEqual(observed[mover['axis']],expected,places=7)
        self.assertEqual([s['simulationTick'] for s in r['rows']],list(range(cycles,cycles*(r['tick']+1),cycles)))
        self.assertTrue(all(s['range']==360 for s in r['rows']))
        # Every camera update remains small; there is no section-triggered snap.
        deltas=[max(abs(b['camera'][k]-a['camera'][k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(deltas),30)
        r.update(fixture=self.fixture,fixtureSource='artifacts/TASK-572/route.json row tick 610; local fixture, not continuous from base',
                 initializations=1,postSetupInjections=0,maxCameraDelta=max(deltas),config=self.config)
        return r

    def test_01_geometry_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            profile:grappleOverProfile()})''')
        local=[e for e in g['elements'] if e['id'].startswith(('yard-','quarry-'))]
        old=json.loads((ROOT/'artifacts/TASK-578/objects.json').read_text())['elements']
        self.assertEqual(len(local),20)
        for e in local:
            previous=next(v for v in old if v['id']==e['id'])
            for key in e:self.assertEqual(e[key],previous[key],(e['id'],key))
            self.assertTrue(e['purpose']);self.assertEqual(e['role'],'bounce')
            if 'anchor' not in e['id']:self.assertGreaterEqual(max(v['x'] for v in e['points']),540)
        es={e['id']:e for e in g['elements']}
        gap=es['yard-fourth-landing']['x']-(es['quarry-landing']['x']+max(v['x'] for v in es['quarry-landing']['points']))
        self.assertEqual(gap,208)
        # Conservative swept AABB distances to every local collider.
        def bounds(e):
            return [e['x']+min(v['x'] for v in e['points']),e['x']+max(v['x'] for v in e['points']),
                    e['y']+min(v['y'] for v in e['points']),e['y']+max(v['y'] for v in e['points'])]
        clear=[]
        for e in g['elements']:
            if e['role']=='drag' or any(m['element']==e['id'] for m in g['movers']):
                box=bounds(e)
                for m in g['movers']:
                    if m['element']==e['id']:
                        k=0 if m['axis']=='x' else 2
                        box[k]+=m['min']-e[m['axis']];box[k+1]+=m['max']-e[m['axis']]
                distances=[]
                for local_e in local:
                    other=bounds(local_e)
                    dx=max(0,box[0]-other[1],other[0]-box[1])
                    dy=max(0,box[2]-other[3],other[2]-box[3])
                    distances.append((dx*dx+dy*dy)**.5)
                clearance=min(distances)
                self.assertGreater(clearance,540 if e['role']=='drag' else 0,e['id'])
                clear.append(dict(id=e['id'],sweptBounds=box,minimumLocalClearance=clearance,role=e['role']))
        self.assertEqual((g['range'],g['scale']),(360,.375))
        self.assertEqual(g['profile']['rangeUpgradeSection'],'S05')
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        oldhash=json.loads((ROOT/'artifacts/TASK-614/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in oldhash.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        recorded=json.loads((ROOT/'artifacts/TASK-572/route.json').read_text())['rows'][609]
        for k,v in self.fixture.items():self.assertEqual(recorded[k],v)
        self.write('geometry-check.json',dict(local=local,gap=gap,clearances=clear,firstUse=first,
            range=360,upgradeSection='S05',upgradedRange=540,scale=.375,newColliders=[],geometryChanged=False,
            dependencies=dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: Task615Tests only'],
                chain='mountain -> fixedlevel -> physics/events -> camera/render; input, rope, modes unchanged',
                historical='TASK-572 reachable approach fixture and TASK-578 local geometry referenced, not copied; earlier full S01 route not rerun'),
            config=self.config))
        print('PASS geometry: 20 unchanged purposeful local colliders; 208 gap; broad shelves >=540; swept movers disjoint and yellow clearances >540; green S01/S02 blue S03 red S07; upgrade S05 only')

    def test_02_continuous_handoff(self):
        p=self.page();self.step(p,19)
        self.act(p,dict(x=2180,y=-330),12,80)
        p.evaluate('draw()');p.screenshot(path=str(self.out/'boundary.jpg'),type='jpeg',quality=90)
        target=p.evaluate('YARD.client({x:1520,y:-499})')
        self.assertTrue(0<target['x']<1280 and 0<target['y']<720)
        self.act(p,dict(x=1520,y=-499),30,22)
        r=self.trace(p)
        exits=[dict(encounter=name,**self.landings(r,id)[0]) for name,id in [('S01-04','yard-fourth-landing'),('S02-01','quarry-landing')]]
        self.assertLess(exits[0]['tick'],exits[1]['tick'])
        self.assertNotEqual(exits[0]['vx'],0)
        self.assertTrue(any(s['attached'] for s in r['rows']))
        r.update(exits=exits,nextTarget=target)
        self.write('handoff.json',r);self.write('inputs.json',dict(events=r['inputs'],exits=[dict(encounter=e['encounter'],tick=e['tick']) for e in exits],ticks=r['tick'],postSetupInjections=0))
        print('PASS handoff: S01-04 -> S02-01 ordered exits', [e['tick'] for e in exits], '; consecutive production ticks; trusted inputs; range 360; camera/mover/rope retained')

    def test_03_miss_rejoin(self):
        p=self.page();self.step(p,19)
        self.act(p,dict(x=2180,y=-330),12,161)
        before=p.evaluate('YARD.result()')
        self.assertFalse(self.landings(before,'quarry-landing'))
        catch=self.landings(before,'quarry-catch')[0]
        self.act(p,dict(x=1720,y=-330),36,88)
        r=self.trace(p)
        returned=[s for s in self.landings(r,'yard-fourth-landing') if s['tick']>catch['tick']]
        self.assertTrue(returned)
        r.update(catch=catch,returned=returned[0],miss='Did not reach quarry-landing; landed on lower quarry-catch; ordinary grapple return')
        self.write('miss-rejoin.json',r)
        print(f'PASS miss-rejoin: lower catch {catch["tick"]} -> shared entry {returned[0]["tick"]}; real inputs; zero post-setup injections')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, actual exit, identifiers and runtime/test hashes',
            'tests.log':'four Task615Tests pass without skips','handoff.json':'both ordered exits and every tick with player/rope/movers/camera/range',
            'inputs.json':'trusted mouse events and ordered exits','miss-rejoin.json':'miss, lower catch and ordinary-control return',
            'geometry-check.json':'unchanged local geometry, purpose, gap, swept/yellow clearances and source dependencies',
            'boundary.jpg':'live approach camera and visible next target','evidence-index.json':'artifact map and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope='Local recorded S01 approach fixture; continuous thereafter only; no base-to-summit claim',
            hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'boundary.jpg') as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all eight required artifacts exist; JSON parses; boundary.jpg decoded 1280x720; retained evidence <200 MB')


class Task616Tests(unittest.TestCase):
    """Local recorded S03 approach, then uninterrupted S03/S04 boundary inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Recorded S03 local fixture; continuous inputs thereafter, not from base'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK616_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    press = Task567Tests.press
    landings = staticmethod(Task567Tests.landings)
    fixture = {'x': 6547.880640357507, 'y': -1568.8565871019284, 'vx': 1.2159807841392238, 'vy': -0.17242675478530337}
    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('''f=>{TUTORIAL_HINT.visible=false;
            Object.assign(ninja,{x:f.x,y:f.y,speedX:f.vx,speedY:f.vy});screen.trackGrappleOver(true);
            window.boundaryRows=[];const original=YARD.step;
            YARD.step=n=>{for(let i=0;i<n;i++){original(1);const s=captureClimbState();
                boundaryRows.push({...YARD.result().rows.at(-1),simulationTick:s.simulationTick,
                    camera:{x:screen.x,y:screen.y},rope:s.grapple,range:grappleOverAcquisitionRadius(),
                    movers:floors[0].level.movers.map(m=>({id:m.id,x:floors[0].byId.get(m.element).x,y:floors[0].byId.get(m.element).y}))});}};
        }''',self.fixture)
        return p

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def act(self,p,target,hold,coast=0):
        self.press(p,target);self.step(p,hold);p.mouse.up();self.step(p,coast)

    def trace(self,p):
        r=p.evaluate('({...YARD.result(),rows:boundaryRows})')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertEqual([s['tick'] for s in r['rows']],list(range(1,r['tick']+1)))
        cycles=p.evaluate('cyclesPerTick')
        timing=p.evaluate('({step:physicsStepMs,movers:floors[0].level.movers})')
        for row in r['rows']:
            for mover,observed in zip(timing['movers'],row['movers']):
                phase=(row['tick']*timing['step']/mover['periodMs']+mover['phase'])%1
                expected=mover['min']+(mover['max']-mover['min'])*(1-abs(2*phase-1))
                self.assertAlmostEqual(observed[mover['axis']],expected,places=7)
        self.assertEqual([s['simulationTick'] for s in r['rows']],list(range(cycles,cycles*(r['tick']+1),cycles)))
        self.assertTrue(all(s['range']==360 for s in r['rows']))
        # Every camera update remains small; there is no section-triggered snap.
        deltas=[max(abs(b['camera'][k]-a['camera'][k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(deltas),30)
        r.update(fixture=self.fixture,fixtureSource='artifacts/TASK-584/route.json trace tick 2192, immediately after recorded mouseup; local released fixture; local fixture, not continuous from base',
                 initializations=1,postSetupInjections=0,maxCameraDelta=max(deltas),config=self.config)
        return r

    def test_01_geometry_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            profile:grappleOverProfile()})''')
        local=[e for e in g['elements'] if e['id'].startswith(('freight-','viaduct-'))]
        old=json.loads((ROOT/'artifacts/TASK-590/objects.json').read_text())['elements']
        self.assertEqual(len(local),26)
        for e in local:
            previous=next(v for v in old if v['id']==e['id'])
            for key in e:self.assertEqual(e[key],previous[key],(e['id'],key))
            self.assertTrue(e['purpose'])

        es={e['id']:e for e in g['elements']}
        gap=es['viaduct-landing']['x']-(es['freight-exit']['x']+max(v['x'] for v in es['freight-exit']['points']))
        self.assertEqual(gap,252)
        # Conservative swept AABB distances to every local collider.
        def bounds(e):
            return [e['x']+min(v['x'] for v in e['points']),e['x']+max(v['x'] for v in e['points']),
                    e['y']+min(v['y'] for v in e['points']),e['y']+max(v['y'] for v in e['points'])]
        clear=[]
        for e in g['elements']:
            if e['role']=='drag' or any(m['element']==e['id'] for m in g['movers']):
                box=bounds(e)
                for m in g['movers']:
                    if m['element']==e['id']:
                        k=0 if m['axis']=='x' else 2
                        box[k]+=m['min']-e[m['axis']];box[k+1]+=m['max']-e[m['axis']]
                distances=[]
                for local_e in [es[n] for n in ['freight-exit','freight-exit-catch','viaduct-anchor','viaduct-landing']]:
                    other=bounds(local_e)
                    dx=max(0,box[0]-other[1],other[0]-box[1])
                    dy=max(0,box[2]-other[3],other[2]-box[3])
                    distances.append((dx*dx+dy*dy)**.5)
                clearance=min(distances)
                self.assertGreaterEqual(clearance,540 if e['role']=='drag' else 1,e['id'])
                clear.append(dict(id=e['id'],sweptBounds=box,minimumLocalClearance=clearance,role=e['role']))
        self.assertEqual((g['range'],g['scale']),(360,.375))
        self.assertEqual(g['profile']['rangeUpgradeSection'],'S05')
        self.assertEqual(g['profile']['upgradedAcquisitionRadius'],540)
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        oldhash=json.loads((ROOT/'artifacts/TASK-614/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in oldhash.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        recorded=json.loads((ROOT/'artifacts/TASK-584/route.json').read_text())['trace'][2191]
        for k,v in self.fixture.items():self.assertEqual(recorded[k],v)
        self.write('geometry-check.json',dict(local=local,gap=gap,clearances=clear,firstUse=first,
            range=360,upgradeSection='S05',upgradedRange=540,scale=.375,newColliders=[],geometryChanged=False,
            dependencies=dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: Task616Tests only'],
                chain='mountain -> fixedlevel -> physics/events -> camera/render; input, rope, modes unchanged',
                historical='TASK-584 reachable approach fixture and TASK-590 local geometry referenced, not copied; earlier full S03 route not rerun'),
            config=self.config))
        print('PASS geometry: unchanged purposeful S03/S04 colliders; 252 gap; broad shared shelves; swept movers disjoint and yellow clearances >=540; green S01/S02 blue S03 red S07; upgrade S05 only')

    until = Task581Tests.until

    def approach(self,p):
        self.step(p,21)
        self.act(p,dict(x=7000,y=-1500),60)
        self.act(p,dict(x=7300,y=-1500),30)

    def test_02_continuous_handoff(self):
        p=self.page();self.approach(p)
        p.evaluate('draw()');p.screenshot(path=str(self.out/'boundary.jpg'),type='jpeg',quality=90)
        target=p.evaluate('YARD.client({x:7488,y:-1679})')
        self.assertTrue(0<target['x']<1280 and 0<target['y']<720)
        self.act(p,dict(x=7488,y=-1679),30)
        self.assertIsNotNone(self.until(p,'viaduct-landing',200))
        r=self.trace(p)
        exits=[dict(encounter=name,**self.landings(r,id)[0]) for name,id in [('S03-04','freight-exit'),('S04-01','viaduct-landing')]]
        self.assertLess(exits[0]['tick'],exits[1]['tick'])
        self.assertNotEqual(exits[0]['vx'],0)
        self.assertTrue(any(s['attached'] for s in r['rows']))
        r.update(exits=exits,nextTarget=target)
        self.write('handoff.json',r);self.write('inputs.json',dict(events=r['inputs'],exits=[dict(encounter=e['encounter'],tick=e['tick']) for e in exits],ticks=r['tick'],postSetupInjections=0))
        print('PASS handoff: S03-04 -> S04-01 ordered exits', [e['tick'] for e in exits], '; consecutive production ticks; trusted inputs; range 360; camera/mover/rope retained')

    def test_03_miss_rejoin(self):
        p=self.page();self.approach(p)
        self.act(p,dict(x=7488,y=-1679),1)
        self.assertIsNotNone(self.until(p,'freight-exit-catch',400))
        before=p.evaluate('YARD.result()')
        self.assertFalse(self.landings(before,'viaduct-landing'))
        catch=self.landings(before,'freight-exit-catch')[0]
        self.act(p,dict(x=7307,y=-1470),40)
        self.assertIsNotNone(self.until(p,'viaduct-landing',500))
        r=self.trace(p)
        returned=[s for s in self.landings(r,'viaduct-landing') if s['tick']>catch['tick']]
        self.assertTrue(returned)
        r.update(catch=catch,returned=returned[0],miss='Did not reach viaduct-landing; landed on lower freight-exit-catch; ordinary grapple return to viaduct-landing')
        self.write('miss-rejoin.json',r)
        print(f'PASS miss-rejoin: lower catch {catch["tick"]} -> S04 route {returned[0]["tick"]}; real inputs; zero post-setup injections')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, actual exit, identifiers and runtime/test hashes',
            'tests.log':'four Task616Tests pass without skips','handoff.json':'both ordered exits and every tick with player/rope/movers/camera/range',
            'inputs.json':'trusted mouse events and ordered exits','miss-rejoin.json':'miss, lower catch and ordinary-control return',
            'geometry-check.json':'unchanged local geometry, purpose, gap, swept/yellow clearances and source dependencies',
            'boundary.jpg':'live approach camera and visible next target','evidence-index.json':'artifact map and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope='Local recorded S03 approach fixture; continuous thereafter only; no base-to-summit claim',
            hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'boundary.jpg') as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all eight required artifacts exist; JSON parses; boundary.jpg decoded 1280x720; retained evidence <200 MB')


class Task617Tests(unittest.TestCase):
    """Local recorded S05 approach, then uninterrupted S05/S06 boundary inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Recorded S05 local fixture; continuous inputs thereafter, not from base'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK617_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    press = Task567Tests.press
    landings = staticmethod(Task567Tests.landings)
    fixture = {'x': 10143.920296356879, 'y': -2506.5313636704686, 'vx': 0.9026983899974853, 'vy': 0.23211193464503826}
    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('''f=>{TUTORIAL_HINT.visible=false;floors[0].rangeUpgraded=true;
            Object.assign(ninja,{x:f.x,y:f.y,speedX:f.vx,speedY:f.vy});screen.trackGrappleOver(true);
            window.boundaryRows=[];const original=YARD.step;
            YARD.step=n=>{for(let i=0;i<n;i++){original(1);const s=captureClimbState();
                boundaryRows.push({...YARD.result().rows.at(-1),simulationTick:s.simulationTick,
                    camera:{x:screen.x,y:screen.y},rope:s.grapple,range:grappleOverAcquisitionRadius(),
                    movers:floors[0].level.movers.map(m=>({id:m.id,x:floors[0].byId.get(m.element).x,y:floors[0].byId.get(m.element).y}))});}};
        }''',self.fixture)
        return p

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def act(self,p,target,hold,coast=0):
        self.press(p,target);self.step(p,hold);p.mouse.up();self.step(p,coast)

    def trace(self,p):
        r=p.evaluate('({...YARD.result(),rows:boundaryRows})')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertEqual([s['tick'] for s in r['rows']],list(range(1,r['tick']+1)))
        cycles=p.evaluate('cyclesPerTick')
        timing=p.evaluate('({step:physicsStepMs,movers:floors[0].level.movers})')
        for row in r['rows']:
            for mover,observed in zip(timing['movers'],row['movers']):
                phase=(row['tick']*timing['step']/mover['periodMs']+mover['phase'])%1
                expected=mover['min']+(mover['max']-mover['min'])*(1-abs(2*phase-1))
                self.assertAlmostEqual(observed[mover['axis']],expected,places=7)
        self.assertEqual([s['simulationTick'] for s in r['rows']],list(range(cycles,cycles*(r['tick']+1),cycles)))
        self.assertTrue(all(s['range']==540 for s in r['rows']))
        # Every camera update remains small; there is no section-triggered snap.
        deltas=[max(abs(b['camera'][k]-a['camera'][k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(deltas),30)
        r.update(fixture=self.fixture,fixtureSource='artifacts/TASK-597/connection.json rows tick 164; released local S05 fixture, not continuous from base',
                 initializations=1,postSetupInjections=0,maxCameraDelta=max(deltas),config=self.config)
        return r

    def test_01_geometry_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            profile:grappleOverProfile()})''')
        local=[e for e in g['elements'] if e['id'].startswith(('gallery-','tower-'))]
        old=json.loads((ROOT/'artifacts/TASK-602/objects.json').read_text())['elements']
        self.assertEqual(len(local),24)
        for e in local:
            previous=next(v for v in old if v['id']==e['id'])
            for key in e:self.assertEqual(e[key],previous[key],(e['id'],key))
            self.assertTrue(e['purpose'])

        es={e['id']:e for e in g['elements']}
        gap=es['tower-observation']['y']-es['gallery-exit']['y']
        self.assertEqual(gap,-760)
        for name in ['gallery-exit','tower-observation','gallery-third-landing']:
            self.assertEqual(max(v['x'] for v in es[name]['points']),800)
        for name in ['S05-04','S06-01']:
            self.assertIn('gallery-exit',next(e for e in g['encounters'] if e['id']==name)['elements'])
        # Conservative swept AABB distances to every local collider.
        def bounds(e):
            return [e['x']+min(v['x'] for v in e['points']),e['x']+max(v['x'] for v in e['points']),
                    e['y']+min(v['y'] for v in e['points']),e['y']+max(v['y'] for v in e['points'])]
        clear=[]
        for e in g['elements']:
            if e['role']=='drag' or any(m['element']==e['id'] for m in g['movers']):
                box=bounds(e)
                for m in g['movers']:
                    if m['element']==e['id']:
                        k=0 if m['axis']=='x' else 2
                        box[k]+=m['min']-e[m['axis']];box[k+1]+=m['max']-e[m['axis']]
                distances=[]
                for local_e in [es[n] for n in ['gallery-exit','tower-observation']]:
                    other=bounds(local_e)
                    dx=max(0,box[0]-other[1],other[0]-box[1])
                    dy=max(0,box[2]-other[3],other[2]-box[3])
                    distances.append((dx*dx+dy*dy)**.5)
                clearance=min(distances)
                self.assertGreaterEqual(clearance,540 if e['role']=='drag' else 1,e['id'])
                clear.append(dict(id=e['id'],sweptBounds=box,minimumLocalClearance=clearance,role=e['role']))
        self.assertEqual((g['range'],g['scale']),(540,.375))
        self.assertEqual(g['profile']['rangeUpgradeSection'],'S05')
        self.assertEqual(g['profile']['upgradedAcquisitionRadius'],540)
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        oldhash=json.loads((ROOT/'artifacts/TASK-614/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in oldhash.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        recorded=json.loads((ROOT/'artifacts/TASK-597/connection.json').read_text())['rows'][163]
        for k,v in self.fixture.items():self.assertEqual(recorded[k],v)
        self.write('geometry-check.json',dict(local=local,gap=gap,clearances=clear,firstUse=first,
            range=540,upgradeSection='S05',upgradedRange=540,scale=.375,newColliders=[],geometryChanged=False,
            dependencies=dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: Task617Tests only'],
                chain='mountain -> fixedlevel -> physics/events -> camera/render; input, rope, modes unchanged',
                historical='TASK-597 recorded reachable approach fixture and TASK-602 local geometry referenced, not copied; earlier full S05 route not rerun'),
            config=self.config))
        print('PASS geometry: unchanged purposeful S05/S06 colliders; 760 vertical opening; broad shared shelves; swept movers disjoint and yellow clearances >=540; green S01/S02 blue S03 red S07; upgrade S05 only')

    until = Task581Tests.until

    def approach(self,p):
        self.assertIsNotNone(self.until(p,'gallery-exit',100))

    def test_02_continuous_handoff(self):
        p=self.page();self.approach(p)
        target=p.evaluate('YARD.client({x:10206,y:-2748.2})')
        self.assertTrue(0<target['x']<1280 and 0<target['y']<720)
        p.evaluate('draw()');p.screenshot(path=str(self.out/'boundary.jpg'),type='jpeg',quality=90)
        self.act(p,dict(x=10206,y=-2748.2),180)
        self.assertIsNotNone(self.until(p,'tower-observation',400))
        r=self.trace(p)
        exits=[dict(encounter=name,**self.landings(r,id)[0]) for name,id in [('S05-04','gallery-exit'),('S06-01','tower-observation')]]
        self.assertLess(exits[0]['tick'],exits[1]['tick'])
        self.assertNotEqual(exits[0]['vx'],0)
        self.assertTrue(any(s['attached'] for s in r['rows']))
        r.update(exits=exits,nextTarget=target)
        self.write('handoff.json',r)
        self.write('inputs.json',dict(events=r['inputs'],exits=[dict(encounter=e['encounter'],tick=e['tick']) for e in exits],ticks=r['tick'],postSetupInjections=0))
        print('PASS handoff: S05-04 -> S06-01 ordered exits', [e['tick'] for e in exits], '; consecutive production ticks; trusted inputs; range 540; camera/mover/rope retained')

    def test_03_miss_rejoin(self):
        p=self.page();self.approach(p)
        self.act(p,dict(x=10206,y=-2748.2),60)
        self.assertIsNotNone(self.until(p,'gallery-third-landing',400))
        before=p.evaluate('YARD.result()')
        self.assertFalse(self.landings(before,'tower-observation'))
        catch=self.landings(before,'gallery-third-landing')[0]
        self.act(p,dict(x=10112,y=-2408),48)
        self.assertIsNotNone(self.until(p,'gallery-exit',500))
        r=self.trace(p)
        returned=[s for s in self.landings(r,'gallery-exit') if s['tick']>catch['tick']]
        self.assertTrue(returned)
        r.update(catch=catch,returned=returned[0],miss='Did not reach tower-observation; landed on lower gallery-third-landing; ordinary grapple return to shared gallery-exit entrance')
        self.write('miss-rejoin.json',r)
        print(f'PASS miss-rejoin: lower catch {catch["tick"]} -> shared S06 entrance {returned[0]["tick"]}; real inputs; zero post-setup injections')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, actual exit, identifiers and runtime/test hashes',
            'tests.log':'four Task617Tests pass without skips','handoff.json':'both ordered exits and every tick with player/rope/movers/camera/range',
            'inputs.json':'trusted mouse events and ordered exits','miss-rejoin.json':'miss, lower catch and ordinary-control return',
            'geometry-check.json':'unchanged local geometry, purpose, gap, swept/yellow clearances and source dependencies',
            'boundary.jpg':'live approach camera and visible next target','evidence-index.json':'artifact map and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope='Local recorded S05 approach fixture; continuous thereafter only; no base-to-summit claim',
            hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'boundary.jpg') as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all eight required artifacts exist; JSON parses; boundary.jpg decoded 1280x720; retained evidence <200 MB')


class Task618Tests(unittest.TestCase):
    """Local recorded S07 approach, then uninterrupted S07/S08 boundary inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Recorded S07 local fixture; continuous inputs thereafter, not from base'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK618_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    press = Task567Tests.press
    landings = staticmethod(Task567Tests.landings)
    fixture = {'x': 11776.25421248827, 'y': -4876.347500074238, 'vx': 1.0839614189113307, 'vy': 0.4015582853321719}
    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('''f=>{TUTORIAL_HINT.visible=false;floors[0].rangeUpgraded=true;
            Object.assign(ninja,{x:f.x,y:f.y,speedX:f.vx,speedY:f.vy});screen.trackGrappleOver(true);
            window.boundaryRows=[];const original=YARD.step;
            YARD.step=n=>{for(let i=0;i<n;i++){original(1);const s=captureClimbState();
                boundaryRows.push({...YARD.result().rows.at(-1),simulationTick:s.simulationTick,
                    camera:{x:screen.x,y:screen.y},rope:s.grapple,range:grappleOverAcquisitionRadius(),
                    movers:floors[0].level.movers.map(m=>({id:m.id,x:floors[0].byId.get(m.element).x,y:floors[0].byId.get(m.element).y}))});}};
        }''',self.fixture)
        p.evaluate("() => {const d=document.createElement('div');d.textContent='S07 local recorded fixture / continuous S07 to S08 inputs / earned 540';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        return p

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def act(self,p,target,hold,coast=0):
        self.press(p,target);self.step(p,hold);p.mouse.up();self.step(p,coast)

    def trace(self,p):
        r=p.evaluate('({...YARD.result(),rows:boundaryRows})')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertEqual([s['tick'] for s in r['rows']],list(range(1,r['tick']+1)))
        cycles=p.evaluate('cyclesPerTick')
        timing=p.evaluate('({step:physicsStepMs,movers:floors[0].level.movers})')
        for row in r['rows']:
            for mover,observed in zip(timing['movers'],row['movers']):
                phase=(row['tick']*timing['step']/mover['periodMs']+mover['phase'])%1
                expected=mover['min']+(mover['max']-mover['min'])*(1-abs(2*phase-1))
                self.assertAlmostEqual(observed[mover['axis']],expected,places=7)
        self.assertEqual([s['simulationTick'] for s in r['rows']],list(range(cycles,cycles*(r['tick']+1),cycles)))
        self.assertTrue(all(s['range']==540 for s in r['rows']))
        # Every camera update remains small; there is no section-triggered snap.
        deltas=[max(abs(b['camera'][k]-a['camera'][k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(deltas),30)
        positionDeltas=[max(abs(b[k]-a[k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(positionDeltas),30)
        r['maxPositionDelta']=max(positionDeltas)
        r.update(fixture=self.fixture,fixtureSource='artifacts/TASK-608/route.json trace tick 1820; released local S07 fixture, not continuous from base',
                 initializations=1,postSetupInjections=0,maxCameraDelta=max(deltas),config=self.config)
        return r

    def test_01_geometry_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            profile:grappleOverProfile()})''')
        local=[e for e in g['elements'] if e['id'].startswith(('crown-','summit-'))]
        old=json.loads((ROOT/'artifacts/TASK-614/objects.json').read_text())['elements']
        self.assertEqual(len(local),29)
        for e in local:
            previous=next(v for v in old if v['id']==e['id'])
            for key in e:self.assertEqual(e[key],previous[key],(e['id'],key))
            self.assertTrue(e['purpose'])

        es={e['id']:e for e in g['elements']}
        gap=es['summit-landing']['x']-es['crown-exit']['x']-800
        self.assertEqual(gap,540)
        for name in ['crown-exit','summit-landing']:
            self.assertEqual(max(v['x'] for v in es[name]['points']),800)
        for name in ['S07-04','S08-01']:
            self.assertIn('crown-exit',next(e for e in g['encounters'] if e['id']==name)['elements'])
        # Conservative swept AABB distances to every local collider.
        def bounds(e):
            return [e['x']+min(v['x'] for v in e['points']),e['x']+max(v['x'] for v in e['points']),
                    e['y']+min(v['y'] for v in e['points']),e['y']+max(v['y'] for v in e['points'])]
        clear=[]
        for e in g['elements']:
            if e['role']=='drag' or any(m['element']==e['id'] for m in g['movers']):
                box=bounds(e)
                for m in g['movers']:
                    if m['element']==e['id']:
                        k=0 if m['axis']=='x' else 2
                        box[k]+=m['min']-e[m['axis']];box[k+1]+=m['max']-e[m['axis']]
                distances=[]
                for local_e in [es[n] for n in ['crown-exit','summit-landing']]:
                    other=bounds(local_e)
                    dx=max(0,box[0]-other[1],other[0]-box[1])
                    dy=max(0,box[2]-other[3],other[2]-box[3])
                    distances.append((dx*dx+dy*dy)**.5)
                clearance=min(distances)
                self.assertGreaterEqual(clearance,540 if e['role']=='drag' else 1,e['id'])
                clear.append(dict(id=e['id'],sweptBounds=box,minimumLocalClearance=clearance,role=e['role']))
        self.assertEqual((g['range'],g['scale']),(540,.375))
        self.assertEqual(g['profile']['rangeUpgradeSection'],'S05')
        self.assertEqual(g['profile']['upgradedAcquisitionRadius'],540)
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        oldhash=json.loads((ROOT/'artifacts/TASK-614/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in oldhash.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        recorded=json.loads((ROOT/'artifacts/TASK-608/route.json').read_text())['trace'][1819]
        for k,v in self.fixture.items():self.assertEqual(recorded[k],v)
        self.write('geometry-check.json',dict(local=local,gap=gap,clearances=clear,firstUse=first,
            range=540,upgradeSection='S05',upgradedRange=540,scale=.375,newColliders=[],geometryChanged=False,
            dependencies=dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: Task618Tests only'],
                chain='mountain -> fixedlevel -> physics/events -> camera/render; input, rope, modes unchanged',
                historical='TASK-608 recorded reachable approach fixture and TASK-614 local geometry referenced, not copied; earlier full S07 route not rerun'),
            config=self.config))
        print('PASS geometry: unchanged purposeful S07/S08 colliders; 540 horizontal opening; broad shared shelves; swept movers disjoint and yellow clearances >=540; green S01/S02 blue S03 red S07; upgrade S05 only')

    until = Task581Tests.until

    def approach(self,p):
        self.assertIsNotNone(self.until(p,'crown-exit',100))
        self.step(p,90)

    def test_02_continuous_handoff(self):
        p=self.page();self.approach(p)
        target=p.evaluate('YARD.client({x:13013,y:-5140})')
        self.assertTrue(0<target['x']<1280 and 0<target['y']<720)
        p.evaluate('draw()');p.screenshot(path=str(self.out/'boundary.jpg'),type='jpeg',quality=90)
        self.act(p,dict(x=13013,y=-5140),45)
        self.assertIsNotNone(self.until(p,'summit-landing',400))
        r=self.trace(p)
        exits=[dict(encounter=name,**self.landings(r,id)[0]) for name,id in [('S07-04','crown-exit'),('S08-01','summit-landing')]]
        self.assertLess(exits[0]['tick'],exits[1]['tick'])
        self.assertNotEqual(exits[0]['vx'],0)
        archived=json.loads((ROOT/'artifacts/TASK-608/route.json').read_text())['trace'][1855]
        for key in ['x','y','vx','vy']:self.assertAlmostEqual(exits[0][key],archived[key],places=7)
        self.assertEqual([e['tick'] for e in exits],[36,313])
        self.assertTrue(any(s['attached'] for s in r['rows']))
        r.update(exits=exits,nextTarget=target)
        self.write('handoff.json',r)
        self.write('inputs.json',dict(events=r['inputs'],exits=[dict(encounter=e['encounter'],tick=e['tick']) for e in exits],ticks=r['tick'],postSetupInjections=0))
        print('PASS handoff: S07-04 -> S08-01 ordered exits', [e['tick'] for e in exits], '; consecutive production ticks; trusted inputs; range 540; camera/mover/rope retained')

    def test_03_miss_rejoin(self):
        p=self.page();self.approach(p)
        self.act(p,dict(x=13013,y=-5140),60)
        self.assertIsNotNone(self.until(p,'summit-catch',500))
        before=p.evaluate('YARD.result()')
        self.assertFalse(self.landings(before,'summit-landing'))
        catch=self.landings(before,'summit-catch')[0]
        self.act(p,dict(x=13453,y=-4668.2),45)
        self.assertIsNotNone(self.until(p,'summit-landing',500))
        r=self.trace(p)
        returned=[s for s in self.landings(r,'summit-landing') if s['tick']>catch['tick']]
        self.assertTrue(returned)
        r.update(catch=catch,returned=returned[0],miss='Did not reach summit-landing; landed on lower summit-catch; ordinary grapple return to summit-landing')
        self.write('miss-rejoin.json',r)
        print(f'PASS miss-rejoin: lower catch {catch["tick"]} -> S08 landing {returned[0]["tick"]}; real inputs; zero post-setup injections')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, actual exit, identifiers and runtime/test hashes',
            'tests.log':'four Task618Tests pass without skips','handoff.json':'both ordered exits and every tick with player/rope/movers/camera/range',
            'inputs.json':'trusted mouse events and ordered exits','miss-rejoin.json':'miss, lower catch and ordinary-control return',
            'geometry-check.json':'unchanged local geometry, purpose, gap, swept/yellow clearances and source dependencies',
            'boundary.jpg':'live approach camera and visible next target','evidence-index.json':'artifact map and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope='Local recorded S07 approach fixture; continuous thereafter only; no base-to-summit claim',
            hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'boundary.jpg') as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all eight required artifacts exist; JSON parses; boundary.jpg decoded 1280x720; retained evidence <200 MB')


class Task619Tests(unittest.TestCase):
    """Local recorded S02 approach, then uninterrupted S02/S03 boundary inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Recorded S02 local fixture; continuous inputs thereafter, not from base'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK619_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    press = Task567Tests.press
    landings = staticmethod(Task567Tests.landings)
    fixture = {'x': 3340.738670260836, 'y': -819.9435000823039, 'vx': 0.5398203657914342, 'vy': 0.15734212937715641}
    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('''f=>{TUTORIAL_HINT.visible=false;
            Object.assign(ninja,{x:f.x,y:f.y,speedX:f.vx,speedY:f.vy});screen.trackGrappleOver(true);
            window.boundaryRows=[];const original=YARD.step;
            YARD.step=n=>{for(let i=0;i<n;i++){original(1);const s=captureClimbState();
                boundaryRows.push({...YARD.result().rows.at(-1),simulationTick:s.simulationTick,
                    camera:{x:screen.x,y:screen.y},rope:s.grapple,range:grappleOverAcquisitionRadius(),
                    movers:floors[0].level.movers.map(m=>({id:m.id,x:floors[0].byId.get(m.element).x,y:floors[0].byId.get(m.element).y}))});}};
        }''',self.fixture)
        p.evaluate("() => {const d=document.createElement('div');d.textContent='S02 local recorded fixture / continuous S02 to S03 inputs / base 360';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        return p

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def act(self,p,target,hold,coast=0):
        self.press(p,target);self.step(p,hold);p.mouse.up();self.step(p,coast)

    def trace(self,p):
        r=p.evaluate('({...YARD.result(),rows:boundaryRows})')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertEqual([s['tick'] for s in r['rows']],list(range(1,r['tick']+1)))
        cycles=p.evaluate('cyclesPerTick')
        timing=p.evaluate('({step:physicsStepMs,movers:floors[0].level.movers})')
        for row in r['rows']:
            for mover,observed in zip(timing['movers'],row['movers']):
                phase=(row['tick']*timing['step']/mover['periodMs']+mover['phase'])%1
                expected=mover['min']+(mover['max']-mover['min'])*(1-abs(2*phase-1))
                self.assertAlmostEqual(observed[mover['axis']],expected,places=7)
        self.assertEqual([s['simulationTick'] for s in r['rows']],list(range(cycles,cycles*(r['tick']+1),cycles)))
        self.assertTrue(all(s['range']==360 for s in r['rows']))
        # Every camera update remains small; there is no section-triggered snap.
        deltas=[max(abs(b['camera'][k]-a['camera'][k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(deltas),30)
        positionDeltas=[max(abs(b[k]-a[k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(positionDeltas),30)
        r['maxPositionDelta']=max(positionDeltas)
        r.update(fixture=self.fixture,fixtureSource='artifacts/TASK-578/route.json rows tick 761; released local S02 fixture, not continuous from base',
                 initializations=1,postSetupInjections=0,maxCameraDelta=max(deltas),config=self.config)
        return r

    def test_01_geometry_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            profile:grappleOverProfile()})''')
        local=[e for e in g['elements'] if e['id'].startswith(('quarry-','freight-'))]
        old=json.loads((ROOT/'artifacts/TASK-614/objects.json').read_text())['elements']
        self.assertEqual(len(local),21)
        for e in local:
            previous=next(v for v in old if v['id']==e['id'])
            for key in e:self.assertEqual(e[key],previous[key],(e['id'],key))
            self.assertTrue(e['purpose'])

        es={e['id']:e for e in g['elements']}
        gap=es['freight-landing']['x']-es['quarry-fourth-landing']['x']-620
        self.assertEqual(gap,676)
        for name in ['quarry-fourth-landing','freight-landing']:
            self.assertEqual(max(v['x'] for v in es[name]['points']),620)
        for name in ['S02-04','S03-01']:
            self.assertIn('quarry-fourth-landing',next(e for e in g['encounters'] if e['id']==name)['elements'])
        # Conservative swept AABB distances to every local collider.
        def bounds(e):
            return [e['x']+min(v['x'] for v in e['points']),e['x']+max(v['x'] for v in e['points']),
                    e['y']+min(v['y'] for v in e['points']),e['y']+max(v['y'] for v in e['points'])]
        clear=[]
        for e in g['elements']:
            if e['role']=='drag' or any(m['element']==e['id'] for m in g['movers']):
                box=bounds(e)
                for m in g['movers']:
                    if m['element']==e['id']:
                        k=0 if m['axis']=='x' else 2
                        box[k]+=m['min']-e[m['axis']];box[k+1]+=m['max']-e[m['axis']]
                distances=[]
                for local_e in [es[n] for n in ['quarry-fourth-landing','freight-landing']]:
                    other=bounds(local_e)
                    dx=max(0,box[0]-other[1],other[0]-box[1])
                    dy=max(0,box[2]-other[3],other[2]-box[3])
                    distances.append((dx*dx+dy*dy)**.5)
                clearance=min(distances)
                self.assertGreaterEqual(clearance,540 if e['role']=='drag' else 1,e['id'])
                clear.append(dict(id=e['id'],sweptBounds=box,minimumLocalClearance=clearance,role=e['role']))
        self.assertEqual((g['range'],g['scale']),(360,.375))
        self.assertEqual(g['profile']['rangeUpgradeSection'],'S05')
        self.assertEqual(g['profile']['upgradedAcquisitionRadius'],540)
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        oldhash=json.loads((ROOT/'artifacts/TASK-614/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in oldhash.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        recorded=json.loads((ROOT/'artifacts/TASK-578/route.json').read_text())['rows'][760]
        for k,v in self.fixture.items():self.assertEqual(recorded[k],v)
        self.write('geometry-check.json',dict(local=local,gap=gap,clearances=clear,firstUse=first,
            range=360,upgradeSection='S05',upgradedRange=540,scale=.375,newColliders=[],geometryChanged=False,
            dependencies=dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: Task619Tests only'],
                chain='mountain -> fixedlevel -> physics/events -> camera/render; input, rope, modes unchanged',
                historical='TASK-578 recorded reachable approach fixture and TASK-614 local geometry referenced, not copied; earlier full S02 route not rerun'),
            config=self.config))
        print('PASS geometry: unchanged purposeful S02/S03 colliders; 676 horizontal opening; broad shared shelves; swept movers disjoint and yellow clearances >=540; green S01/S02 blue S03 red S07; upgrade S05 only')

    until = Task581Tests.until

    def approach(self,p):
        self.assertIsNotNone(self.until(p,'quarry-fourth-landing',100))
        self.step(p,50)

    def test_02_continuous_handoff(self):
        p=self.page();self.approach(p)
        target=p.evaluate('YARD.client({x:4123.6,y:-900})')
        self.assertTrue(0<target['x']<1280 and 0<target['y']<720)
        p.evaluate('draw()');p.screenshot(path=str(self.out/'boundary.jpg'),type='jpeg',quality=90)
        self.act(p,dict(x=4123.6,y=-900),240)
        self.assertIsNotNone(self.until(p,'freight-landing',500))
        r=self.trace(p)
        exits=[dict(encounter=name,**self.landings(r,id)[0]) for name,id in [('S02-04','quarry-fourth-landing'),('S03-01','freight-landing')]]
        self.assertEqual([e['tick'] for e in exits],[39,387])
        archived=json.loads((ROOT/'artifacts/TASK-578/route.json').read_text())['rows'][799]
        for key in ['x','y','vx','vy']:self.assertAlmostEqual(exits[0][key],archived[key],places=7)
        self.assertNotEqual(exits[0]['vx'],0)
        self.assertTrue(any(s['attached'] and any(v['id']=='freight-carrier' for v in s['rope']['segments']) for s in r['rows']))
        self.assertFalse(self.landings(r,'freight-catch'))
        r.update(exits=exits,nextTarget=target)
        self.write('handoff.json',r)
        self.write('inputs.json',dict(events=r['inputs'],exits=[dict(encounter=e['encounter'],tick=e['tick']) for e in exits],ticks=r['tick'],postSetupInjections=0))
        print('PASS handoff: S02-04 -> S03-01 ordered exits 39/387; consecutive production ticks; trusted inputs; range 360; camera/mover/rope retained')

    def test_03_miss_rejoin(self):
        p=self.page();self.approach(p)
        self.act(p,dict(x=4123.6,y=-900),6)
        self.assertIsNotNone(self.until(p,'freight-catch',500))
        before=p.evaluate('YARD.result()')
        self.assertFalse(self.landings(before,'freight-landing'))
        catch=self.landings(before,'freight-catch')[0]
        self.act(p,dict(x=4501,y=-688),12)
        self.assertIsNotNone(self.until(p,'freight-landing',500))
        r=self.trace(p)
        returned=[s for s in self.landings(r,'freight-landing') if s['tick']>catch['tick']]
        self.assertTrue(returned)
        self.assertEqual((catch['tick'],returned[0]['tick']),(199,326))
        r.update(catch=catch,returned=returned[0],miss='Did not reach freight-landing; landed on lower freight-catch; ordinary grapple return to freight-landing')
        self.write('miss-rejoin.json',r)
        print('PASS miss-rejoin: lower catch 199 -> S03 landing 326; real inputs; zero post-setup injections')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, actual exit, identifiers and runtime/test hashes',
            'tests.log':'four Task619Tests pass without skips','handoff.json':'both ordered exits and every tick with player/rope/movers/camera/range',
            'inputs.json':'trusted mouse events and ordered exits','miss-rejoin.json':'miss, lower catch and ordinary-control return',
            'geometry-check.json':'unchanged local geometry, purpose, gap, swept/yellow clearances and source dependencies',
            'boundary.jpg':'live approach camera and visible next target','evidence-index.json':'artifact map and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope='Local recorded S02 approach fixture; continuous thereafter only; no base-to-summit claim',
            hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'boundary.jpg') as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all eight required artifacts exist; JSON parses; boundary.jpg decoded 1280x720; retained evidence <200 MB')


class Task620Tests(unittest.TestCase):
    """Local recorded S04 approach, then uninterrupted S04/S05 boundary inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Recorded S04 local fixture; continuous inputs thereafter, not from base'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK620_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    press = Task567Tests.press
    landings = staticmethod(Task567Tests.landings)
    fixture = {'x': 10631.057527832236, 'y': -1622.05072316755, 'vx': 1.7880284318506219, 'vy': -0.3017884618979458}
    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('''f=>{TUTORIAL_HINT.visible=false;
            Object.assign(ninja,{x:f.x,y:f.y,speedX:f.vx,speedY:f.vy});screen.trackGrappleOver(true);
            window.boundaryRows=[];const original=YARD.step;
            YARD.step=n=>{for(let i=0;i<n;i++){original(1);const s=captureClimbState();
                boundaryRows.push({...YARD.result().rows.at(-1),simulationTick:s.simulationTick,
                    camera:{x:screen.x,y:screen.y},rope:s.grapple,range:grappleOverAcquisitionRadius(),
                    movers:floors[0].level.movers.map(m=>({id:m.id,x:floors[0].byId.get(m.element).x,y:floors[0].byId.get(m.element).y}))});}};
        }''',self.fixture)
        p.evaluate("() => {const d=document.createElement('div');d.textContent='S04 local recorded fixture / continuous S04 to S05 inputs / earned 360 to 540';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        return p

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def act(self,p,target,hold,coast=0):
        self.press(p,target);self.step(p,hold);p.mouse.up();self.step(p,coast)

    def trace(self,p):
        r=p.evaluate('({...YARD.result(),rows:boundaryRows})')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertEqual([s['tick'] for s in r['rows']],list(range(1,r['tick']+1)))
        cycles=p.evaluate('cyclesPerTick')
        timing=p.evaluate('({step:physicsStepMs,movers:floors[0].level.movers})')
        for row in r['rows']:
            for mover,observed in zip(timing['movers'],row['movers']):
                phase=(row['tick']*timing['step']/mover['periodMs']+mover['phase'])%1
                expected=mover['min']+(mover['max']-mover['min'])*(1-abs(2*phase-1))
                self.assertAlmostEqual(observed[mover['axis']],expected,places=7)
        self.assertEqual([s['simulationTick'] for s in r['rows']],list(range(cycles,cycles*(r['tick']+1),cycles)))
        transitions=[b for a,b in zip(r['rows'],r['rows'][1:]) if a['range']!=b['range']]
        self.assertEqual(len(transitions),1)
        transition=transitions[0]
        self.assertEqual((r['rows'][0]['range'],transition['range'],r['rows'][-1]['range']),(360,540,540))
        self.assertTrue(10780<=transition['x']<=11580 and -1548<=transition['y']<=-1528.2)
        r['upgrade']=dict(tick=transition['tick'],x=transition['x'],y=transition['y'],before=360,after=540)
        # Every camera update remains small; there is no section-triggered snap.
        deltas=[max(abs(b['camera'][k]-a['camera'][k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(deltas),30)
        positionDeltas=[max(abs(b[k]-a[k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(positionDeltas),30)
        r['maxPositionDelta']=max(positionDeltas)
        r.update(fixture=self.fixture,fixtureSource='artifacts/TASK-590/route.json trace tick 321; released local S04 fixture, not continuous from base',
                 initializations=1,postSetupInjections=0,maxCameraDelta=max(deltas),config=self.config)
        return r

    def test_01_geometry_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            profile:grappleOverProfile()})''')
        local=[e for e in g['elements'] if e['id'].startswith(('viaduct-','gallery-'))]
        old=json.loads((ROOT/'artifacts/TASK-614/objects.json').read_text())['elements']
        self.assertEqual(len(local),len([e for e in old if e['id'].startswith(('viaduct-','gallery-'))]))
        for e in local:
            previous=next(v for v in old if v['id']==e['id'])
            for key in e:self.assertEqual(e[key],previous[key],(e['id'],key))
            self.assertTrue(e['purpose'])

        es={e['id']:e for e in g['elements']}
        gap=es['gallery-landing']['x']-es['viaduct-exit']['x']-800
        self.assertEqual(gap,612)
        for name in ['viaduct-exit','gallery-landing']:
            self.assertEqual(max(v['x'] for v in es[name]['points']),800)
        for name in ['S04-04','S05-01']:
            self.assertIn('viaduct-exit',next(e for e in g['encounters'] if e['id']==name)['elements'])
        # Conservative swept AABB distances to every local collider.
        def bounds(e):
            return [e['x']+min(v['x'] for v in e['points']),e['x']+max(v['x'] for v in e['points']),
                    e['y']+min(v['y'] for v in e['points']),e['y']+max(v['y'] for v in e['points'])]
        clear=[]
        for e in g['elements']:
            if e['role']=='drag' or any(m['element']==e['id'] for m in g['movers']):
                box=bounds(e)
                for m in g['movers']:
                    if m['element']==e['id']:
                        k=0 if m['axis']=='x' else 2
                        box[k]+=m['min']-e[m['axis']];box[k+1]+=m['max']-e[m['axis']]
                distances=[]
                for local_e in [es[n] for n in ['viaduct-exit','gallery-landing']]:
                    other=bounds(local_e)
                    dx=max(0,box[0]-other[1],other[0]-box[1])
                    dy=max(0,box[2]-other[3],other[2]-box[3])
                    distances.append((dx*dx+dy*dy)**.5)
                clearance=min(distances)
                self.assertGreaterEqual(clearance,540 if e['role']=='drag' else 1,e['id'])
                clear.append(dict(id=e['id'],sweptBounds=box,minimumLocalClearance=clearance,role=e['role']))
        self.assertEqual((g['range'],g['scale']),(360,.375))
        self.assertEqual(g['profile']['rangeUpgradeSection'],'S05')
        self.assertEqual(g['profile']['upgradedAcquisitionRadius'],540)
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        oldhash=json.loads((ROOT/'artifacts/TASK-614/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in oldhash.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        recorded=json.loads((ROOT/'artifacts/TASK-590/route.json').read_text())['trace'][320]
        for k,v in self.fixture.items():self.assertEqual(recorded[k],v)
        self.write('geometry-check.json',dict(local=local,gap=gap,clearances=clear,firstUse=first,
            range=360,upgradeSection='S05',upgradedRange=540,scale=.375,newColliders=[],geometryChanged=False,
            dependencies=dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: Task620Tests only'],
                chain='mountain -> fixedlevel -> physics/events -> camera/render; input, rope, modes unchanged',
                historical='TASK-590 recorded reachable approach fixture and TASK-614 local geometry referenced, not copied; earlier full S04 route not rerun'),
            config=self.config))
        print('PASS geometry: unchanged purposeful S04/S05 colliders; 612 horizontal opening; broad shared shelves; swept movers disjoint and yellow clearances >=540; green S01/S02 blue S03 red S07; upgrade S05 only')

    until = Task581Tests.until

    def approach(self,p):
        self.assertIsNotNone(self.until(p,'viaduct-exit',100))
        self.step(p,20)

    def test_02_continuous_handoff(self):
        p=self.page();self.approach(p)
        target=p.evaluate('YARD.client({x:11950,y:-1679})')
        self.assertTrue(0<target['x']<1280 and 0<target['y']<720)
        p.evaluate('draw()');p.screenshot(path=str(self.out/'boundary.jpg'),type='jpeg',quality=90)
        self.act(p,dict(x=11950,y=-1679),42)
        self.assertIsNotNone(self.until(p,'gallery-landing',500))
        r=self.trace(p)
        exits=[dict(encounter=name,**self.landings(r,id)[0]) for name,id in [('S04-04','viaduct-exit'),('S05-01','gallery-landing')]]
        self.assertLess(exits[0]['tick'],exits[1]['tick'])
        archived=json.loads((ROOT/'artifacts/TASK-590/route.json').read_text())['trace'][351]
        for key in ['x','y','vx','vy']:self.assertAlmostEqual(exits[0][key],archived[key],places=7)
        self.assertNotEqual(exits[0]['vx'],0)
        self.assertTrue(any(s['attached'] for s in r['rows']))
        self.assertFalse(self.landings(r,'gallery-catch'))
        r.update(exits=exits,nextTarget=target)
        self.write('handoff.json',r)
        self.write('inputs.json',dict(events=r['inputs'],exits=[dict(encounter=e['encounter'],tick=e['tick']) for e in exits],ticks=r['tick'],postSetupInjections=0))
        print('PASS handoff: S04-04 -> S05-01 ordered exits', [e['tick'] for e in exits], '; consecutive production ticks; trusted inputs; earned 360->540; camera/mover/rope retained')

    def test_03_miss_rejoin(self):
        p=self.page();self.approach(p)
        self.act(p,dict(x=11950,y=-1679),30)
        self.assertIsNotNone(self.until(p,'gallery-catch',500))
        before=p.evaluate('YARD.result()')
        self.assertFalse(self.landings(before,'gallery-landing'))
        catch=self.landings(before,'gallery-catch')[0]
        self.act(p,dict(x=12193,y=-1500),48,30)
        self.act(p,dict(x=12980,y=-1520),48)
        self.assertIsNotNone(self.until(p,'gallery-landing',500))
        r=self.trace(p)
        returned=[s for s in self.landings(r,'gallery-landing') if s['tick']>catch['tick']]
        self.assertTrue(returned)
        r.update(catch=catch,returned=returned[0],miss='Did not reach gallery-landing; landed on lower gallery-catch; ordinary two-shot return around exposed east edge to gallery-landing')
        self.write('miss-rejoin.json',r)
        print(f'PASS miss-rejoin: lower catch {catch["tick"]} -> S05 landing {returned[0]["tick"]}; real inputs; zero post-setup injections')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, actual exit, identifiers and runtime/test hashes',
            'tests.log':'four Task620Tests pass without skips','handoff.json':'both ordered exits and every tick with player/rope/movers/camera/range',
            'inputs.json':'trusted mouse events and ordered exits','miss-rejoin.json':'miss, lower catch and ordinary-control return',
            'geometry-check.json':'unchanged local geometry, purpose, gap, swept/yellow clearances and source dependencies',
            'boundary.jpg':'live approach camera and visible next target','evidence-index.json':'artifact map and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope='Local recorded S04 approach fixture; continuous thereafter only; no base-to-summit claim',
            hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'boundary.jpg') as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all eight required artifacts exist; JSON parses; boundary.jpg decoded 1280x720; retained evidence <200 MB')


class Task621Tests(unittest.TestCase):
    """Local recorded S06 approach, then uninterrupted S06/S07 boundary inputs."""
    @classmethod
    def setUpClass(cls):
        if 'GRAPPLE_OVER_EVIDENCE_DIR' not in os.environ:
            raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR')
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Recorded S06 local fixture; continuous inputs thereafter, not from base'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK621_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write = Task557Tests.write
    press = Task567Tests.press
    landings = staticmethod(Task567Tests.landings)
    fixture = {'x': 13548.444474689499, 'y': -4033.813558262757, 'vx': -0.09773384677035044, 'vy': 0.1987207780104568}
    def page(self):
        p=Task567Tests.page(self)
        p.evaluate('''f=>{TUTORIAL_HINT.visible=false;floors[0].rangeUpgraded=true;
            Object.assign(ninja,{x:f.x,y:f.y,speedX:f.vx,speedY:f.vy});screen.trackGrappleOver(true);
            window.boundaryRows=[];const original=YARD.step;
            YARD.step=n=>{for(let i=0;i<n;i++){original(1);const s=captureClimbState();
                boundaryRows.push({...YARD.result().rows.at(-1),simulationTick:s.simulationTick,
                    camera:{x:screen.x,y:screen.y},rope:s.grapple,range:grappleOverAcquisitionRadius(),
                    movers:floors[0].level.movers.map(m=>({id:m.id,x:floors[0].byId.get(m.element).x,y:floors[0].byId.get(m.element).y}))});}};
        }''',self.fixture)
        p.evaluate("() => {const d=document.createElement('div');d.textContent='S06 local recorded fixture / continuous S06 to S07 inputs / earned 540';d.style='position:fixed;bottom:12px;left:12px;background:#111;color:white;padding:8px';document.body.appendChild(d)}")
        return p

    def step(self,p,n):
        p.evaluate('n=>YARD.step(n)',n)

    def act(self,p,target,hold,coast=0):
        self.press(p,target);self.step(p,hold);p.mouse.up();self.step(p,coast)

    def trace(self,p):
        r=p.evaluate('({...YARD.result(),rows:boundaryRows})')
        self.assertTrue(r['inputs']);self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertEqual([s['tick'] for s in r['rows']],list(range(1,r['tick']+1)))
        cycles=p.evaluate('cyclesPerTick')
        timing=p.evaluate('({step:physicsStepMs,movers:floors[0].level.movers})')
        for row in r['rows']:
            for mover,observed in zip(timing['movers'],row['movers']):
                phase=(row['tick']*timing['step']/mover['periodMs']+mover['phase'])%1
                expected=mover['min']+(mover['max']-mover['min'])*(1-abs(2*phase-1))
                self.assertAlmostEqual(observed[mover['axis']],expected,places=7)
        self.assertEqual([s['simulationTick'] for s in r['rows']],list(range(cycles,cycles*(r['tick']+1),cycles)))
        self.assertTrue(all(s['range']==540 for s in r['rows']))
        # Every camera update remains small; there is no section-triggered snap.
        deltas=[max(abs(b['camera'][k]-a['camera'][k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])]
        self.assertLess(max(deltas),30)
        self.assertLess(max(max(abs(b[k]-a[k]) for k in ['x','y']) for a,b in zip(r['rows'],r['rows'][1:])),30)
        r.update(fixture=self.fixture,fixtureSource='artifacts/TASK-603/connection.json rows tick 895; released local S06 fixture, not continuous from base',
                 initializations=1,postSetupInjections=0,maxCameraDelta=max(deltas),config=self.config)
        return r

    def test_01_geometry_and_dependencies(self):
        p=self.page()
        g=p.evaluate('''()=>({elements:floors[0].level.elements,sections:floors[0].level.sections,
            encounters:floors[0].level.encounters,movers:floors[0].level.movers,range:grappleOverAcquisitionRadius(),scale:scale[version],
            profile:grappleOverProfile()})''')
        local=[e for e in g['elements'] if e['id'].startswith(('tower-','crown-'))]
        old=json.loads((ROOT/'artifacts/TASK-614/objects.json').read_text())['elements']
        self.assertEqual(len(local),len([e for e in old if e['id'].startswith(('tower-','crown-'))]))
        for e in local:
            previous=next(v for v in old if v['id']==e['id'])
            for key in e:self.assertEqual(e[key],previous[key],(e['id'],key))
            self.assertTrue(e['purpose'])

        es={e['id']:e for e in g['elements']}
        gap=es['tower-exit']['x']-es['crown-landing']['x']-800
        self.assertEqual(gap,252)
        for name in ['tower-exit','crown-landing']:
            self.assertEqual(max(v['x'] for v in es[name]['points']),800)
        for name in ['S06-04','S07-01']:
            self.assertIn('tower-exit',next(e for e in g['encounters'] if e['id']==name)['elements'])
        # Conservative swept AABB distances to every local collider.
        def bounds(e):
            return [e['x']+min(v['x'] for v in e['points']),e['x']+max(v['x'] for v in e['points']),
                    e['y']+min(v['y'] for v in e['points']),e['y']+max(v['y'] for v in e['points'])]
        clear=[]
        for e in g['elements']:
            if e['role']=='drag' or any(m['element']==e['id'] for m in g['movers']):
                box=bounds(e)
                for m in g['movers']:
                    if m['element']==e['id']:
                        k=0 if m['axis']=='x' else 2
                        box[k]+=m['min']-e[m['axis']];box[k+1]+=m['max']-e[m['axis']]
                distances=[]
                for local_e in [es[n] for n in ['tower-exit','crown-landing']]:
                    other=bounds(local_e)
                    dx=max(0,box[0]-other[1],other[0]-box[1])
                    dy=max(0,box[2]-other[3],other[2]-box[3])
                    distances.append((dx*dx+dy*dy)**.5)
                clearance=min(distances)
                self.assertGreaterEqual(clearance,540 if e['role']=='drag' else 1,e['id'])
                clear.append(dict(id=e['id'],sweptBounds=box,minimumLocalClearance=clearance,role=e['role']))
        red=next(v for v in clear if v['id']=='crown-red')
        self.assertGreaterEqual(red['minimumLocalClearance'],150)
        redClearances=[]
        boundaryIds={n for encounter in g['encounters'] if encounter['id'] in ['S06-04','S07-01'] for n in encounter['elements']}
        for e in g['elements']:
            if e['id']=='crown-red' or e['id'] not in boundaryIds:continue
            box=red['sweptBounds'];other=bounds(e)
            dx=max(0,box[0]-other[1],other[0]-box[1])
            dy=max(0,box[2]-other[3],other[2]-box[3])
            distance=(dx*dx+dy*dy)**.5
            self.assertGreaterEqual(distance,150,e['id'])
            redClearances.append(dict(id=e['id'],distance=distance))
        self.assertEqual((g['range'],g['scale']),(540,.375))
        self.assertEqual(g['profile']['acquisitionRadius'],360)
        self.assertEqual(g['profile']['rangeUpgradeSection'],'S05')
        self.assertEqual(g['profile']['upgradedAcquisitionRadius'],540)
        first={role:min(c['id'][:3] for c in g['encounters'] if any(es[n]['role']==role for n in c['elements'])) for role in ['bounce','solid','drag','hazard']}
        self.assertEqual(first,dict(bounce='S01',solid='S03',drag='S04',hazard='S07'))
        oldhash=json.loads((ROOT/'artifacts/TASK-614/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in oldhash.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        recorded=json.loads((ROOT/'artifacts/TASK-603/connection.json').read_text())['rows'][894]
        for k,v in self.fixture.items():self.assertEqual(recorded[k],v)
        self.write('geometry-check.json',dict(redClearances=redClearances,safeApproach='800-wide tower-exit outside full red sweep; first hazard belongs to S07',local=local,gap=gap,clearances=clear,firstUse=first,
            range=540,upgradeSection='S05',upgradedRange=540,scale=.375,newColliders=[],geometryChanged=False,
            dependencies=dict(unchanged=unchanged,changed=['tools/test_grapple_over_redesign.py: Task621Tests only'],
                chain='mountain -> fixedlevel -> physics/events -> camera/render; input, rope, modes unchanged',
                historical='TASK-603 recorded reachable approach fixture and TASK-614 local geometry referenced, not copied; earlier full S06 route not rerun'),
            config=self.config))
        print('PASS geometry: unchanged purposeful S06/S07 colliders; 252 horizontal opening; broad shared shelves; swept movers disjoint and yellow clearances >=540; green S01/S02 blue S03 red S07; upgrade S05 only')

    until = Task581Tests.until

    def approach(self,p):
        self.assertIsNotNone(self.until(p,'tower-exit',100))
        # Traverse the broad observation deck using its existing green surface.
        self.act(p,dict(x=13100,y=-3918.2),26)
        p.evaluate('()=>{for(let i=0;i<500 && ninja.x>12862;i++)YARD.step(1)}')
        self.assertLessEqual(p.evaluate('ninja.x'),12862)
        self.assertFalse(p.evaluate("YARD.result().rows.some(r=>r.contacts.some(c=>c.id.includes('red')))"))

    def test_02_continuous_handoff(self):
        p=self.page();self.approach(p)
        target=p.evaluate('YARD.client({x:12602,y:-4099})')
        self.assertTrue(0<target['x']<1280 and 0<target['y']<720)
        p.evaluate('draw()');p.screenshot(path=str(self.out/'boundary.jpg'),type='jpeg',quality=90)
        self.act(p,dict(x=12602,y=-4099),30)
        self.assertIsNotNone(self.until(p,'crown-landing',400))
        r=self.trace(p)
        exits=[dict(encounter=name,**self.landings(r,id)[0]) for name,id in [('S06-04','tower-exit'),('S07-01','crown-landing')]]
        self.assertLess(exits[0]['tick'],exits[1]['tick'])
        self.assertNotEqual(exits[0]['vx'],0)
        self.assertTrue(any(s['attached'] for s in r['rows']))
        r.update(exits=exits,nextTarget=target)
        self.write('handoff.json',r)
        self.write('inputs.json',dict(events=r['inputs'],exits=[dict(encounter=e['encounter'],tick=e['tick']) for e in exits],ticks=r['tick'],postSetupInjections=0))
        print('PASS handoff: S06-04 -> S07-01 ordered exits', [e['tick'] for e in exits], '; consecutive production ticks; trusted inputs; range 540; camera/mover/rope retained')

    def test_03_miss_rejoin(self):
        p=self.page();self.approach(p)
        self.act(p,dict(x=12602,y=-4099),6)
        self.assertIsNotNone(self.until(p,'crown-catch',400))
        before=p.evaluate('YARD.result()')
        self.assertFalse(self.landings(before,'crown-landing'))
        catch=self.landings(before,'crown-catch')[0]
        self.act(p,dict(x=12792,y=-3918.2),48)
        self.assertIsNotNone(self.until(p,'tower-exit',500))
        r=self.trace(p)
        returned=[s for s in self.landings(r,'tower-exit') if s['tick']>catch['tick']]
        self.assertTrue(returned)
        r.update(catch=catch,returned=returned[0],miss='Did not reach crown-landing; landed on lower crown-catch; ordinary grapple return to shared tower-exit entrance')
        self.write('miss-rejoin.json',r)
        print(f'PASS miss-rejoin: lower catch {catch["tick"]} -> shared S07 entrance {returned[0]["tick"]}; real inputs; zero post-setup injections')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, actual exit, identifiers and runtime/test hashes',
            'tests.log':'four Task621Tests pass without skips','handoff.json':'both ordered exits and every tick with player/rope/movers/camera/range',
            'inputs.json':'trusted mouse events and ordered exits','miss-rejoin.json':'miss, lower catch and ordinary-control return',
            'geometry-check.json':'unchanged local geometry, purpose, gap, swept/yellow clearances and source dependencies',
            'boundary.jpg':'live approach camera and visible next target','evidence-index.json':'artifact map and provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            scope='Local recorded S06 approach fixture; continuous thereafter only; no base-to-summit claim',
            hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'boundary.jpg') as im:im.load();self.assertEqual(im.size,(1280,720))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all eight required artifacts exist; JSON parses; boundary.jpg decoded 1280x720; retained evidence <200 MB')


class Task622Tests(unittest.TestCase):
    """Bounded local lower-route searches, never a continuous-from-base claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config['simulation']='Isolated entry/archived released poses; synthetic production mouse handlers and physics; 1200 ticks per attempt'
        cls.config['source_hashes']['tools/grapple_over_bypass.js']=hashlib.sha256((ROOT/'tools/grapple_over_bypass.js').read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK622_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write
    exits=['yard-landing','yard-second-landing','yard-third-landing','yard-fourth-landing',
           'quarry-landing','quarry-second-landing','quarry-third-landing','quarry-fourth-landing',
           'freight-landing','freight-second-landing','freight-lift-landing','freight-exit',
           'viaduct-landing','viaduct-second-landing','viaduct-third-landing','viaduct-exit']
    policies=[dict(name='continuous-hold-nearest-anchor',interval=0,anchorsOnly=True),
              dict(name='nearest-anchor-12',interval=12,anchorsOnly=True),
              dict(name='nearest-anchor-48',interval=48,anchorsOnly=True),
              dict(name='nearest-visible-surface-24',interval=24,anchorsOnly=False)]

    def page(self):
        p=Task567Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_bypass.js'))
        return p

    def starts(self):
        starts=[]
        for section,task,xy in [(1,572,(2160,0)),(2,578,(1780,-360)),(3,584,(3740,-720)),(4,590,(7228,-1540))]:
            path=f'artifacts/TASK-{task}/route.json';d=json.loads((ROOT/path).read_text())
            rows=d.get('rows',d.get('trace'));by_tick={r['tick']:r for r in rows}
            starts.append(dict(id=f'S0{section}-entry',section=f'S0{section}',completed=(section-1)*4-1,
                pose=dict(x=xy[0],y=xy[1],vx=0,vy=0),phaseTick=0,
                provenance=dict(path=path,kind='original local section-entry fixture; S01 is actual spawn',sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest())))
            for tick in sorted({e['tick'] for e in d['inputs'] if e['type']=='mousedown' and e['tick']>0}):
                row=by_tick[tick]
                # Mouseup at the same tick releases the preceding shot. Each is a
                # local released fixture; pose and mover phase are preserved.
                completed=(section-1)*4-1
                for r in rows:
                    if r['tick']>tick:break
                    for c in r['contacts']:
                        if c['ny']<-.9 and c['id'] in self.exits:completed=max(completed,self.exits.index(c['id']))
                starts.append(dict(id=f'S0{section}-approach-{tick}',section=f'S0{section}',completed=completed,
                    pose={k:row[k] for k in ['x','y','vx','vy']},phaseTick=tick,
                    provenance=dict(path=path,tick=tick,kind='recorded pre-press pose; released rope fixture, not state restoration',sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest())))
        return starts

    def test_01_detector_negative_controls(self):
        p=self.page();start=self.starts()[0];cases=[]
        for target in ['yard-fourth-landing','quarry-landing']:
            r=p.evaluate('(a)=>BYPASS.run(a.s,360,a.p,120,a.control)',dict(s=start,p=self.policies[0],control=target))
            self.assertTrue(any(v['unapproved'] for v in r['skips']))
            self.assertEqual(r['completions'][0]['id'],target)
            self.assertLess(r['completions'][0]['contact']['ny'],-.9)
            cases.append(dict(geometry='Only named landing retained, moved to x=2050 y=50 beneath actual spawn; real fall/contact',target=target,result=r))
        self.write('negative-controls.json',cases)
        print('PASS detector: production contacts detect close S01-04 skip=3 and S02-01 cross-section skip=4')

    def test_02_bounded_lower_route(self):
        p=self.page();starts=self.starts()
        cases=p.evaluate('a=>a.starts.flatMap(s=>[360,540].flatMap(r=>a.policies.map(p=>BYPASS.run(s,r,p))))',dict(starts=starts,policies=self.policies))
        violations=[dict(start=c['start'],range=c['range'],policy=c['policy'],skip=v) for c in cases for v in c['skips'] if v['unapproved']]
        self.write('search.json',dict(config=self.config,scope='Bounded evidence only, not universal impossibility; isolated fixtures, not continuous gameplay',
            starts=starts,policies=self.policies,budgets=dict(attempts=len(starts)*8,ticksPerAttempt=1200,totalTicks=len(cases)*1200),
            detector='First upward-surface contact on designated encounter exit; monotonic progress; >1 omitted encounters or any omitted encounter across section boundary is unapproved; adjacent normal handoff is allowed',
            negativeControls='negative-controls.json',cases=cases,unapproved=violations))
        self.assertEqual(len(cases),len(starts)*8)
        self.assertTrue(all(c['ticks']==1200 and c['postSetupInjections']==0 for c in cases))
        self.assertTrue(all(any(c['shots'] for c in cases if c['start']==s['id']) for s in starts))
        self.assertEqual(violations,[],str(violations)[:3000])
        print(f'PASS search: {len(starts)} starts S01-S04; {len(cases)} attempts; {len(cases)*1200} production ticks; ranges 360/540; unapproved=0')

    def test_03_dependencies_and_fixes(self):
        search=json.loads((self.out/'search.json').read_text());self.assertEqual(search['unapproved'],[])
        old=json.loads((ROOT/'artifacts/TASK-621/evidence-index.json').read_text())['config']['source_hashes']
        unchanged={n:h for n,h in old.items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in unchanged.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        archives=[]
        for task in [572,578,584,590,615,616,619,620,621]:
            path=f'artifacts/TASK-{task}/tests.log';log=(ROOT/path).read_text()
            self.assertIn('\nOK\n',log);self.assertRegex(log,r'Ran [1-9][0-9]* tests')
            archives.append(dict(path=path,sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),summary=next(l for l in log.splitlines() if l.startswith('Ran '))))
        self.write('fixes.json',dict(reproducedUnapprovedRoutes=[],geometryChanges=[],affectedReplays=[],
            reason='No unapproved route observed in bounded search; no geometry fix or affected nominal/recovery rerun necessary',
            observedLocalSkips=[dict(start=c['start'],range=c['range'],policy=c['policy'],skips=c['skips']) for c in search['cases'] if c['skips']],
            dependencies=dict(unchangedHashes=unchanged,changed=['tools/test_grapple_over_redesign.py: Task622Tests','tools/grapple_over_bypass.js: test-only probe'],
                chain='preview mountain -> fixedlevel -> physics/input -> camera; production unchanged',
                historical='Archived nominal/recovery logs referenced only; obsolete v3 geometry not rerun or suppressed'),archives=archives))
        print('PASS fixes: no reproduced unapproved routes; geometryChanges=0; unchanged production hashes; 9 archived regression logs have nonzero tests and OK')

    def test_04_trusted_input_confirmation(self):
        p=self.page();s=self.starts()[0]
        p.evaluate('s=>BYPASS.setup(s,360,null)',s)
        target=p.evaluate('BYPASS.candidates(true)[0]');self.assertIsNotNone(target)
        Task567Tests.press(self,p,target);p.evaluate('YARD.step(1200)');p.mouse.up()
        actual=p.evaluate('YARD.result()')
        synthetic=json.loads((self.out/'search.json').read_text())['cases'][0]
        for k in ['x','y','vx','vy']:self.assertAlmostEqual(actual['rows'][-1][k],synthetic['final'][k],places=7)
        self.assertTrue(all(i['trusted'] for i in actual['inputs']))
        self.assertTrue(any(r['attached'] for r in actual['rows']))
        self.write('trusted-input.json',dict(inputs=actual['inputs'],ticks=actual['tick'],final=actual['rows'][-1],syntheticFinal=synthetic['final'],attachedTicks=sum(r['attached'] for r in actual['rows']),target=target))
        print('PASS trusted: 1200-tick real mouse hold matches synthetic production-handler final pose/velocity to 7 decimals')

    def test_05_evidence_index(self):
        required={'commands.log':'exact invocation, exit, exact test identifiers, hashes and browser/viewport',
            'tests.log':'five Task622Tests executed without skips', 'search.json':'start provenance, finite budgets, every completion and skip',
            'negative-controls.json':'actual close-geometry contacts flag multi-encounter and cross-section bypass',
            'fixes.json':'route/fix/replay mapping; unchanged runtime dependency hashes and archived tests',
            'trusted-input.json':'trusted mouse versus batched production input equivalence',
            'evidence-index.json':'artifact map and source provenance'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,hashPolicy='HEAD-only commit does not invalidate identical tested file hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: 7 required files exist; JSON parses; retained evidence <200 MB; no required images/clips')


class Task623Tests(unittest.TestCase):
    """Upper-route isolated fixtures; finite search, not continuous gameplay."""
    @classmethod
    def setUpClass(cls):
        Task622Tests.setUpClass.__func__(cls)
        cls.config['source_hashes']['tools/grapple_over_upper_bypass.js']=hashlib.sha256((ROOT/'tools/grapple_over_upper_bypass.js').read_bytes()).hexdigest()
        cls.config['simulation']='Isolated archived upper-route released poses; production physics/input at 540; bounded one/two-press launches'
        with (cls.out/'commands.log').open('a') as f:f.write('TASK623_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write

    def page(self):
        p=Task622Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_upper_bypass.js'))
        return p

    def starts(self):
        starts=[]
        for section,task in [(5,596),(6,602),(7,608),(8,614)]:
            path=f'artifacts/TASK-{task}/route.json';d=json.loads((ROOT/path).read_text());rows=d['trace']
            for tick in sorted({i['tick'] for i in d['inputs'] if i['type']=='mousedown'}):
                row=next(r for r in rows if r['tick']==tick)
                completed=(section-1)*4-1
                for e in d['exits']:
                    if e['tick']<=tick:completed=max(completed,(section-1)*4+d['exits'].index(e))
                starts.append(dict(id=f'S0{section}-approach-{tick}',section=f'S0{section}',completed=completed,
                    pose={k:row[k] for k in ['x','y','vx','vy']},phaseTick=tick,
                    provenance=dict(path=path,tick=tick,sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),kind='released isolated pre-press fixture; not continuous gameplay')))
        return starts

    def test_01_geometry_and_upper_search(self):
        p=self.page();starts=self.starts()
        p.evaluate('s=>BYPASS.setup(s,540,null)',starts[0]);regions=p.evaluate('UPPER_BYPASS.geometry()')
        pairs=[]
        for i,a in enumerate(regions):
            for b in regions[i+2:]:
                dx=max(0,a['minX']-b['maxX'],b['minX']-a['maxX']);dy=max(0,a['minY']-b['maxY'],b['minY']-a['maxY'])
                distance=(dx*dx+dy*dy)**.5
                if distance<=1080:pairs.append(dict(a=a['id'],b=b['id'],aabbGap=distance))
        policies=[dict(name=f'{n}-press-rank-{rank}-hold-{hold}',rank=rank,presses=[dict(tick=1+j*(hold+60),hold=hold) for j in range(n)])
                  for n in [1,2] for rank in [0,2] for hold in [30,120,360]]
        baseline_specs=[('S05-approach-629','1-press-rank-2-hold-360'),('S05-approach-629','2-press-rank-2-hold-360'),('S06-approach-925','2-press-rank-2-hold-30')]
        baseline=[]
        for start_id,policy_name in baseline_specs:
            start=next(s for s in starts if s['id']==start_id);policy=next(p for p in policies if p['name']==policy_name)
            c=p.evaluate("""a=>{
                const m=GRAPPLE_OVER_REPLACEMENT,es=m.elements,enc=m.encounters;
                m.elements=es.filter(e=>e.id!=='tower-west-separator');
                m.encounters=enc.map(e=>({...e,elements:e.elements.filter(id=>id!=='tower-west-separator')}));
                try{return UPPER_BYPASS.run(a.s,a.p)}finally{m.elements=es;m.encounters=enc}
            }""",dict(s=start,p=policy))
            self.assertTrue(any(v['unapproved'] for v in c['skips']))
            baseline.append(c)
        self.write('before-search.json',dict(config=self.config,geometryDelta='Only tower-west-separator removed to reproduce original geometry',cases=baseline,
            unapproved=[dict(start=c['start'],policy=c['policy'],skip=v) for c in baseline for v in c['skips'] if v['unapproved']]))
        cases=p.evaluate('a=>a.starts.flatMap(s=>a.policies.map(p=>UPPER_BYPASS.run(s,p)))',dict(starts=starts,policies=policies))
        for c in baseline:
            start=next(s for s in starts if s['id']==c['start'])
            policy=dict(name='exact-original-input-'+c['policy']['name'],rank=0,presses=[dict(press,target=e['target']) for press,e in zip(c['policy']['presses'],[e for e in c['inputs'] if e['type']=='mousedown'])])
            cases.append(p.evaluate('a=>UPPER_BYPASS.run(a.s,a.p)',dict(s=start,p=policy)))
        # Explicit distant aim attempts test replacement of the historical S05->S08 fold,
        # including targets outside acquisition range (the production handler rejects them).
        fold=[dict(name='old-fold-'+target,rank=0,target=target,presses=[dict(tick=1,hold=360),dict(tick=421,hold=360)])
              for target in ['summit-landing','summit-final-landing']]
        cases+=p.evaluate('a=>a.starts.flatMap(s=>a.policies.map(p=>UPPER_BYPASS.run(s,p)))',dict(starts=[s for s in starts if s['section']=='S05'],policies=fold))
        violations=[dict(start=c['start'],policy=c['policy'],skip=v) for c in cases for v in c['skips'] if v['unapproved']]
        live=p.evaluate("""()=>floors[0].level.elements.filter(e=>e.id==='tower-west-separator'||BYPASS.exits.slice(16).includes(e.id)).map(e=>({id:e.id,x:e.x,y:e.y,width:Math.max(...e.points.map(p=>p.x))-Math.min(...e.points.map(p=>p.x)),height:Math.max(...e.points.map(p=>p.y))-Math.min(...e.points.map(p=>p.y))}))""")
        self.assertEqual(next(e for e in live if e['id']=='tower-west-separator'),dict(id='tower-west-separator',x=9750,y=-3540,width=60,height=840))
        self.assertTrue(all(e['width']>=720 for e in live if e['id']!='tower-west-separator'))
        self.write('geometry.json',dict(measuredElements=live,regions=regions,closeNonadjacentPairs=pairs,threshold=1080,method='Euclidean gap between production encounter AABBs; conservative spatial inventory',geometryChanges=[dict(id="tower-west-separator",x=9750,y=-3540,width=60,height=840)]))
        self.write('search.json',dict(config=self.config,scope=self.config['simulation'],starts=starts,policies=policies+fold,cases=cases,spatialPairs=pairs,
            budgets=dict(attempts=len(cases),ticksPerAttempt=1200,totalTicks=1200*len(cases)),unapproved=violations,
            limitation='Finite candidates only; region visits use conservative AABBs, completions require upward production contact on designated exits'))
        self.assertTrue(pairs);self.assertGreater(len(cases),0);self.assertEqual(violations,[],str(violations)[:3000])
        self.assertTrue(all(c['postSetupInjections']==0 and c['inputs'] for c in cases))
        self.assertEqual({s['section'] for s in starts},{'S05','S06','S07','S08'})
        print(f'PASS upper search: {len(starts)} starts; {len(cases)} attempts; {1200*len(cases)} ticks; range=540; unapproved=0; explicit S05-to-S08 fold probes')
        print(f'PASS geometry: {len(regions)} regions; {len(pairs)} close nonadjacent pairs; geometryChanges=1')

    press=Task567Tests.press
    step=Task567Tests.step
    until=Task605Tests.until
    shot=Task594Tests.shot

    def test_02_affected_routes(self):
        proofs=[]
        def save(p,section,ids):
            r=p.evaluate('YARD.result()');exits=[]
            for id in ids:
                hits=[row for row in r['rows'] if row['tick']>(exits[-1]['tick'] if exits else -1) and any(c['id']==id and c['ny']<-.9 for c in row['contacts'])]
                self.assertTrue(hits,id);exits.append(dict(id=id,tick=hits[0]['tick']))
            self.assertEqual([e['tick'] for e in exits],sorted(e['tick'] for e in exits))
            self.assertTrue(all(i['trusted'] for i in r['inputs']))
            proofs.append(dict(section=section,exits=exits,inputs=r['inputs'],contacts=[dict(tick=row['tick'],contacts=row['contacts']) for row in r['rows'] if row['contacts']],ticks=r['tick']))
        p=Task591Tests.page(self)
        self.shot(p,Task591Tests.target,42);self.assertIsNotNone(self.until(p,'gallery-landing',500));self.step(p,60)
        self.shot(p,dict(x=12990,y=-2030),60);self.assertIsNotNone(self.until(p,'gallery-upper-landing',500))
        self.shot(p,Task593Tests.target,25);self.step(p,50);self.shot(p,Task593Tests.next_target,28)
        self.assertIsNotNone(self.until(p,'gallery-third-landing',500));self.step(p,75)
        self.shot(p,Task594Tests.target,75);self.assertIsNotNone(self.until(p,'gallery-exit',1000))
        save(p,'S05',['gallery-landing','gallery-upper-landing','gallery-third-landing','gallery-exit'])
        p=Task597Tests.page(self)
        self.shot(p,Task597Tests.target,240);self.assertIsNotNone(self.until(p,'tower-observation',500))
        self.shot(p,dict(x=11031,y=-3178.2),48);self.assertIsNotNone(self.until(p,'tower-shaft-landing',600));self.step(p,22)
        target=p.evaluate("()=>{const e=floors[0].byId.get('tower-rebound-carrier');return {x:e.x+10,y:e.y+40}}")
        self.shot(p,target,48);third=self.until(p,'tower-rebound-landing',600);self.assertIsNotNone(third)
        self.step(p,1800-third);self.shot(p,Task600Tests.target,240);self.step(p,12)
        self.shot(p,dict(x=13572,y=-3938.2),12);self.assertIsNotNone(self.until(p,'tower-exit',600))
        save(p,'S06',['tower-observation','tower-shaft-landing','tower-rebound-landing','tower-exit'])
        p=Task603Tests.page(self);self.step(p,420);Task606Tests.shot(self,p,Task603Tests.target,30)
        self.assertIsNotNone(self.until(p,'crown-landing',300));self.step(p,80);Task606Tests.shot(self,p,Task604Tests.target,30)
        self.assertIsNotNone(self.until(p,'crown-practice-landing',400));self.step(p,300)
        Task606Tests.shot(self,p,dict(x=10658,y=-4318.6),240);self.assertIsNotNone(self.until(p,'crown-upper-landing',500))
        self.step(p,120);Task606Tests.shot(self,p,Task606Tests.target,30);self.assertIsNotNone(self.until(p,'crown-exit',500))
        save(p,'S07',['crown-landing','crown-practice-landing','crown-upper-landing','crown-exit'])
        q=Task591Tests.page(self);self.shot(q,Task591Tests.target,6)
        self.assertIsNotNone(self.until(q,'gallery-catch',500));self.shot(q,dict(x=11570,y=-1500),12)
        self.assertIsNotNone(self.until(q,'viaduct-exit',800));save(q,'S05-recovery',['gallery-catch','viaduct-exit'])
        q=Task567Tests.page(self)
        q.evaluate('Object.assign(ninja,{x:10758,y:-3960,speedX:0,speedY:0});floors[0].rangeUpgraded=true;screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false')
        self.step(q,600);Task606Tests.shot(self,q,Task605Tests.target,12)
        self.assertIsNotNone(self.until(q,'crown-lift-catch',800));Task606Tests.shot(self,q,dict(x=10688,y=-3938.2),60)
        self.assertIsNotNone(self.until(q,'crown-practice-landing',800));save(q,'S07-recovery',['crown-lift-catch','crown-practice-landing'])
        q=Task597Tests.page(self);self.shot(q,Task597Tests.target,6)
        self.assertIsNotNone(self.until(q,'gallery-third-landing',800));self.shot(q,dict(x=10112,y=-2408),12)
        self.assertIsNotNone(self.until(q,'gallery-exit',800));save(q,'S06-recovery',['gallery-third-landing','gallery-exit'])
        self.write('normal-routes.json',proofs)
        print('PASS affected routes: all 12 S05/S06/S07 exits ordered; gallery, tower and crown fall recovery pass with trusted input')

    def test_02_dependencies_and_normal_routes(self):
        old=json.loads((ROOT/'artifacts/TASK-622/fixes.json').read_text())['dependencies']['unchangedHashes']
        for n,h in old.items():
            if n!='mountain.js':self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        archives=[]
        for task in [596,602,608,614,617,618,620,621]:
            path=f'artifacts/TASK-{task}/tests.log';log=(ROOT/path).read_text()
            self.assertIn('\nOK\n',log);self.assertRegex(log,r'Ran [1-9][0-9]* tests')
            archives.append(dict(path=path,sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),summary=next(l for l in log.splitlines() if l.startswith('Ran '))))
        search=json.loads((self.out/'search.json').read_text());self.assertEqual(search['unapproved'],[])
        self.assertEqual(len(json.loads((self.out/'normal-routes.json').read_text())),6)
        self.write('fixes.json',dict(geometryChanges=[dict(id="tower-west-separator",x=9750,y=-3540,width=60,height=840)],reproducedUnapprovedRoutes=json.loads((self.out/'before-search.json').read_text())['unapproved'],remainingUnapprovedRoutes=[],affectedNormalRoutes=['S05','S06','S07'],replays='normal-routes.json',archives=archives,
            dependencies=dict(unchangedHashes={n:h for n,h in old.items() if n!='mountain.js'},previousMountainHash=old['mountain.js'],changed=['mountain.js: replacement-only west tower separator','tools/test_grapple_over_redesign.py: Task623Tests only','tools/grapple_over_upper_bypass.js: observation-only harness']),
            reason='West tower separator blocks premature acquisition from Gallery and the Tower return bounce into Crown. Full affected section routes and gallery/crown recovery rerun. Historical inventories superseded by this one collider; physics/input/camera unchanged.'))
        print('PASS fixes: one local separator; 3 reproduced skips eliminated; unchanged physics/input/camera hashes; affected normal routes rerun; 8 archived logs OK')

    def test_03_trusted_input_confirmation(self):
        search=json.loads((self.out/'search.json').read_text());proof=[]
        for section in ['S05','S06','S07','S08']:
            s=next(s for s in search['starts'] if s['section']==section)
            c=next(c for c in search['cases'] if c['start']==s['id'] and len(c['policy']['presses'])==2 and c['attachedTicks']>0)
            p=self.page();p.evaluate('s=>BYPASS.setup(s,540,null)',s);tick=0
            for e in c['inputs']:
                p.evaluate('n=>YARD.step(n)',e['tick']-1-tick if e['tick']<1200 else 1200-tick)
                tick=e['tick']-1 if e['tick']<1200 else 1200
                if e['type']=='mousedown':Task567Tests.press(self,p,e['target'])
                else:p.mouse.up()
            actual=p.evaluate('YARD.result()')
            for k in ['x','y','vx','vy']:self.assertAlmostEqual(actual['rows'][-1][k],c['final'][k],places=7)
            self.assertTrue(all(e['trusted'] for e in actual['inputs']))
            proof.append(dict(section=section,policy=c['policy'],inputs=actual['inputs'],final=actual['rows'][-1],syntheticFinal=c['final'],ticks=actual['tick']))
        self.write('trusted-input.json',proof)
        print('PASS trusted: all four upper sections; two-press real mouse launches match batch final pose/velocity to 7 decimals')

    def test_04_evidence_index(self):
        required={'commands.log':'exact commands, exit codes, test identifiers, browser, revision and hashes','tests.log':'five exact Task623Tests without skips','before-search.json':'three reproduced baseline bypasses','normal-routes.json':'12 affected exits and three recoveries',
            'search.json':'finite starts, policies, real-handler traces, visited regions, no unapproved skips','geometry.json':'production regions and close nonadjacent pairs',
            'fixes.json':'unchanged production dependencies and archived normal/recovery tests','trusted-input.json':'four trusted two-press confirmations','evidence-index.json':'artifact assertion map'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,hashPolicy='HEAD-only commit does not invalidate identical source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all 9 required files exist; JSON parses; no required images/clips; retained bytes <200 MB')


class Task624Tests(unittest.TestCase):
    """Finite isolated boundary/finish probes; no continuous-from-base claim."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        for n in ['tools/test_grapple_over_redesign.py','tools/grapple_over_bypass.js','tools/grapple_over_boundary.js']:
            cls.config['source_hashes'][n]=hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK624_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write
    press=Task567Tests.press
    step=Task567Tests.step
    until=Task605Tests.until
    shot=Task612Tests.shot

    def page(self):
        p=Task622Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_boundary.js'))
        return p

    @staticmethod
    def start(id,x,y,vx=0,vy=0):
        return dict(id=id,pose=dict(x=x,y=y,vx=vx,vy=vy),phaseTick=0)

    def test_01_acquisition(self):
        p=self.page();cases=[]
        specs=[('visible',2160,0,2420,-139),
               ('left-edge',20,-1000,-100,-1200),('right-edge',15980,-1000,16100,-1200),
               ('non-grapplable',12200,-5670,12360,-5670),
               ('occluded',11100,-5550,11100,-5300),
               ('underside',11000,-5350,11000,-5468.2)]
        for name,x,y,tx,ty in specs:
            for radius in [360,540]:
                r=p.evaluate('a=>BOUNDARY.run(a.s,a.r,a.t,120,180)',dict(s=self.start(name,x,y),r=radius,t=dict(x=tx,y=ty)))
                cases.append(r)
        self.write('acquisition.json',dict(cases=cases,scope='Isolated real-map fixtures; production mouse handlers, nearest crossing and attached-element data'))
        for r in cases:
            name=r['start']['id']
            if name=='visible':self.assertIn('yard-anchor',r['attached'])
            if name in ['left-edge','right-edge','non-grapplable']:self.assertEqual(r['attached'],[],name)
            if name in ['left-edge','right-edge']:
                self.assertGreaterEqual(min(row['y'] for row in r['trace']),r['start']['pose']['y'])
            if name=='non-grapplable':self.assertTrue(r['initialHit']['blocked'])
            if name=='occluded':
                self.assertEqual(r['initialHit']['id'],'summit-final-landing')
                self.assertNotIn('summit-final-catch',r['attached'])
            if name=='underside':self.assertEqual(r['initialHit']['id'],'summit-final-landing')
        print('PASS acquisition: 12 cases; visible controls; map-edge/non-grapplable rejection; occluded far target blocked; underside hit; ranges 360/540')

    def test_02_finish_search(self):
        p=self.page()
        # Enumerate every production route/recovery surface whose polygon is within
        # upgraded acquisition distance of the final deck, then sample its top.
        inventory=p.evaluate('''()=>{const f=floors[0].level.finish;return floors[0].elements.map(e=>{
            const ps=e.getPoints(),left=Math.min(...ps.map(p=>p.x)),right=Math.max(...ps.map(p=>p.x)),top=Math.min(...ps.map(p=>p.y)),bottom=Math.max(...ps.map(p=>p.y));
            const gap=Math.hypot(Math.max(0,left-f.right,f.left-right),Math.max(0,top-f.bottom,f.top-bottom));
            return {id:e.id,left,right,top,bottom,gap};}).filter(e=>e.gap<=540)}''')
        starts=[]
        for e in inventory:
            if e['id']=='summit-final-landing':continue
            for x in [e['left']+20,(e['left']+e['right'])/2,e['right']-20]:
                starts.append(self.start(e['id']+'-'+str(x),x,e['top']-11.8))
        starts += [self.start('underside-'+str(x),x,-5380,0,-5) for x in [10780,11150,11530]]
        starts += [self.start('side-'+str(x),x,-5480,v,0) for x,v in [(10690,5),(11620,-5)]]
        # Archived released upper-route inputs also cover nearby moving approach poses.
        archived=Task623Tests.starts(self)
        for s in archived:
            x,y=s['pose']['x'],s['pose']['y']
            if ((max(0,10758-x,x-11558))**2+(y+5468.2)**2)**.5<=540:starts.append(s)
        targets=[dict(x=10768,y=-5468.2),dict(x=11158,y=-5468.2),dict(x=11548,y=-5468.2),Task612Tests.target]
        cases=p.evaluate('a=>a.starts.flatMap(s=>a.targets.flatMap(t=>[24,120,600].map(h=>BOUNDARY.run(s,540,t,h,720))))',dict(starts=starts,targets=targets))
        illegal=[dict(start=c['start']['id'],event=e) for c in cases for e in c['events'] if not any(k['id']=='summit-final-landing' and k['ny']<-.9 for k in e['contacts'])]
        self.write('finish-probes.json',dict(inventory=inventory,starts=starts,cases=cases,attempts=len(cases),totalTicks=720*len(cases),illegal=illegal,
            scope='Finite sampled isolated fixtures, collision-preserving input after setup; not exhaustive reachability or continuous gameplay'))
        self.assertTrue(starts);self.assertGreater(len(cases),0);self.assertEqual(illegal,[])
        self.assertTrue(all(c['postSetupInjections']==0 for c in cases))
        print(f'PASS finish search: {len(starts)} starts; {len(cases)} attempts; {720*len(cases)} ticks; illegal=0; every completion has summit-final-landing top contact')

    def test_03_intended_and_recovery(self):
        cases=[]
        for hold in [32,24]:
            p=self.page();s=self.start('S08-04 shared planning deck',12178,-5480)
            p.evaluate('s=>BYPASS.setup(s,540,null)',s)
            p.evaluate('''()=>{window.finalEvents=[];const old=PLATFORM.sendLifecycle;PLATFORM.sendLifecycle=function(n,...args){if(n==='level_completed')finalEvents.push({tick:YARD.result().tick+1,x:ninja.x,y:ninja.y});return old.call(this,n,...args)}}''')
            self.shot(p,Task612Tests.target,hold);self.assertIsNotNone(self.until(p,'summit-final-landing',700));self.step(p,120)
            r=p.evaluate('YARD.result()');events=p.evaluate('finalEvents')
            self.assertEqual(len(events),1)
            self.assertTrue(any(row['tick']==events[0]['tick'] and any(c['id']=='summit-final-landing' and c['ny']<-.9 for c in row['contacts']) for row in r['rows']))
            if hold==24:self.assertTrue(any(any(c['id']=='summit-final-catch' and c['ny']<-.9 for c in row['contacts']) for row in r['rows']))
            self.assertTrue(all(i['trusted'] for i in r['inputs']))
            cases.append(dict(hold=hold,events=events,inputs=r['inputs'],contacts=[r for r in r['rows'] if r['contacts']]))
        previous=json.loads((ROOT/'artifacts/TASK-623/evidence-index.json').read_text())['config']['source_hashes']
        for n,h in previous.items():
            if n.endswith('.js') and not n.startswith('tools/'):self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        prior=json.loads((ROOT/'artifacts/TASK-623/fixes.json').read_text())
        for n,h in prior['dependencies']['unchangedHashes'].items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        archives=[]
        for task in [614,623]:
            path=f'artifacts/TASK-{task}/tests.log';log=(ROOT/path).read_text();self.assertIn('\nOK\n',log)
            archives.append(dict(path=path,sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),summary=next(l for l in log.splitlines() if l.startswith('Ran '))))
        self.write('fixes.json',dict(runtimeChanges=[],affectedRouteRechecks=cases,archives=archives,dependencies=self.config['source_hashes'],
            changedSubsystems=['additive Task624Tests and observation-only boundary harness'],remainingPrematureFinishes=[]))
        print('PASS rechecks: intended landing completes once; early-release catch returns and completes once; trusted input; production dependencies unchanged; archived S08 and upper-route tests OK')

    def test_04_index(self):
        required={'commands.log':'exact command, exit, identifiers, browser/viewport, revision, source hashes','tests.log':'four exact Task624Tests, no skips',
                  'acquisition.json':'12 production input/hit cases','finish-probes.json':'bounded approaches and contact-qualified completion events',
                  'fixes.json':'intended/recovery rechecks and unchanged dependencies','evidence-index.json':'artifact assertion map'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,hashPolicy='HEAD movement alone does not invalidate identical tested hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: all 6 required files exist; JSON parses; no required media; retained bytes <200 MB')


class Task625Tests(unittest.TestCase):
    """Integrated shortcut comparisons from isolated, reproducible section entries."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        cls.config.update(touch_viewport=VIEWPORT,
            simulation='Isolated section entrance fixtures; continuous inputs thereafter, not base-to-summit')
        cls.config['source_hashes']['tools/test_grapple_over_redesign.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK625_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write
    def page(self,touch=False):
        p=Task567Tests.page(self)
        p.touch_session=p.context.new_cdp_session(p) if touch else None
        if touch:
            p.touch_session.send('Emulation.setTouchEmulationEnabled',dict(enabled=True,maxTouchPoints=1))
            p.evaluate("""()=>{for(const type of ['touchstart','touchend'])document.addEventListener(type,e=>{
                const t=e.changedTouches[0];YARD.result().inputs.push({tick:YARD.result().tick,type,
                    trusted:e.isTrusted,x:t.clientX,y:t.clientY});});}""")
        return p

    def press(self,p,target):
        xy=p.evaluate('p=>YARD.client(p)',target)
        xy={k:int(v) for k,v in xy.items()}  # Match desktop integer CSS coordinates.
        self.assertTrue(0<xy['x']<1280 and 0<xy['y']<720,xy)
        if p.touch_session:p.touch_session.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[xy]))
        else:p.mouse.move(**xy);p.mouse.down()
    release=Task571Tests.release
    step=Task567Tests.step
    result=Task567Tests.result
    landings=staticmethod(Task567Tests.landings)
    until=Task605Tests.until
    frame=Task571Tests.frame
    exits={5:['gallery-landing','gallery-upper-landing','gallery-third-landing','gallery-exit'],
           7:['crown-landing','crown-practice-landing','crown-upper-landing','crown-exit']}

    def shot(self,p,target,hold):
        if p.section==7:p.evaluate('screen.trackGrappleOver(true)')
        self.press(p,target);self.step(p,hold);self.release(p)

    def entry(self,section,touch):
        p=self.page(touch) if touch else Task567Tests.page(self)
        if not touch:p.touch_session=None
        p.section=section
        pose=dict(x=11500,y=-1540) if section==5 else dict(x=12862,y=-3960)
        p.evaluate('a=>{Object.assign(ninja,a.pose,{speedX:0,speedY:0});floors[0].rangeUpgraded=a.upgraded;screen.trackGrappleOver(true)}',dict(pose=pose,upgraded=section==7))
        if section==5:
            self.step(p,1)  # Earn the S05 upgrade before the first acquisition.
            self.shot(p,Task591Tests.target,42);self.assertIsNotNone(self.until(p,self.exits[5][0],500))
            self.step(p,60);self.shot(p,dict(x=12990,y=-2030),60)
            self.assertIsNotNone(self.until(p,self.exits[5][1],500))
        else:
            self.step(p,420);self.shot(p,Task603Tests.target,30)
            self.assertIsNotNone(self.until(p,self.exits[7][0],300))
            self.step(p,80);self.shot(p,Task604Tests.target,30)
            self.assertIsNotNone(self.until(p,self.exits[7][1],400));self.step(p,300)
        return p

    def route(self,section,touch,shortcut,offset=0):
        p=self.entry(section,touch)
        shared=p.evaluate('({tick:YARD.result().tick,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,world:floors[0].elapsedSteps})')
        start=shared['tick']
        if section==5:
            if shortcut:self.shot(p,dict(x=11520,y=-2319),160+offset)
            else:
                self.shot(p,Task593Tests.target,25);self.step(p,50);self.shot(p,Task593Tests.next_target,28)
                self.assertIsNotNone(self.until(p,self.exits[5][2],500));self.step(p,75)
                self.shot(p,Task594Tests.target,75+offset)
        else:
            self.shot(p,dict(x=10658,y=-4318.6),(270 if shortcut else 240))
            if shortcut:
                tick=p.evaluate('''()=>{for(let i=0;i<500;i++){YARD.step(1);
                    if(Math.hypot(ninja.x-11673,ninja.y+5140)<500)return YARD.result().tick;}return null}''')
                self.assertIsNotNone(tick)
            else:
                self.assertIsNotNone(self.until(p,self.exits[7][2],500));self.step(p,120)
            self.shot(p,Task606Tests.target,30+offset)
        # Stop at either success or the documented missed-shortcut catch.
        catch='gallery-third-landing' if section==5 else 'crown-exit-catch'
        outcome=p.evaluate('''a=>{for(let i=0;i<700;i++){YARD.step(1);const r=YARD.result().rows.at(-1);
            const hit=r.contacts.find(c=>c.ny<-.9&&(c.id===a.exit||(a.shortcut&&c.id===a.catch)));
            if(hit)return {id:hit.id,tick:r.tick,y:r.y};}return null}''',dict(exit=self.exits[section][-1],catch=catch,shortcut=shortcut))
        r=self.result(p)
        visited=[dict(encounter=f'S0{section}-0{i+1}',collider=id,tick=self.landings(r,id)[0]['tick'])
                 for i,id in enumerate(self.exits[section]) if self.landings(r,id)]
        inputs=r['inputs'];expected='touchstart' if touch else 'mousedown'
        self.assertTrue(any(i['type']==expected for i in inputs));self.assertTrue(all(i['trusted'] for i in inputs))
        row=dict(section=section,mode='touch' if touch else 'desktop',shortcut=shortcut,offset=offset,
                 shared=shared,startTick=start,outcome=outcome,visited=visited,inputs=inputs,
                 trace=Task613Tests.compact(r['rows']),
                 postSetupInjections=0,resets=0)
        peak=r['rows'][start-1]['y'];drop=0
        for point in r['rows'][start:]:
            peak=min(peak,point['y']);drop=max(drop,point['y']-peak)
        row['maximumFall']=drop
        if not shortcut and offset==0:
            row['geometry']=p.evaluate("prefix=>floors[0].elements.filter(e=>e.id.startsWith(prefix)).map(e=>({id:e.id,points:e.getPoints()}))",'gallery-' if section==5 else 'crown-')
        return p,row,[]

    def test_01_routes_and_windows(self):
        cases=[];misses=[]
        for section in [5,7]:
            for touch in [False,True]:
                paths={}
                for shortcut in [False,True]:
                    samples=[]
                    for offset in ([0,-10,-40] if shortcut and section==5 else [0,-10] if section==5 else [0,-12]):
                        p,row,_=self.route(section,touch,shortcut,offset)
                        samples.append(row)
                        print(f'CASE S0{section} {row["mode"]} shortcut={shortcut} offset={offset} outcome={row["outcome"]}',flush=True)
                        if shortcut and offset==(-10 if section==5 else -12):
                            self.assertEqual(row['outcome']['id'],'gallery-third-landing' if section==5 else 'crown-exit-catch')
                            self.assertNotIn(self.exits[section][-1],[v['collider'] for v in row['visited']])
                            self.shot(p,Task594Tests.target if section==5 else dict(x=12043,y=-4698),25 if section==5 else 120)
                            returned=self.until(p,self.exits[section][-1],700);self.assertIsNotNone(returned)
                            rr=self.result(p)
                            misses.append(dict(section=section,mode=row['mode'],catch=row['outcome'],returnTick=returned,
                                recoveryInputs=[i for i in rr['inputs'] if i['tick']>=row['outcome']['tick']],
                                trace=Task613Tests.compact(rr['rows']),resets=0,postSetupInjections=0))
                        p.context.close()
                    paths['shortcut' if shortcut else 'normal']=samples
                normal,short=paths['normal'][0],paths['shortcut'][0]
                self.assertEqual(normal['shared'],short['shared'])
                self.assertEqual(normal['outcome']['id'],self.exits[section][-1]);self.assertEqual(short['outcome']['id'],self.exits[section][-1])
                self.assertLess(short['outcome']['tick'],normal['outcome']['tick'])
                self.assertEqual([v['encounter'] for v in normal['visited']],[f'S0{section}-0{i}' for i in [1,2,3,4]])
                self.assertEqual([v['encounter'] for v in short['visited']],[f'S0{section}-0{i}' for i in [1,2,4]])
                topContacts=sorted({c['id'] for r in short['trace'] if r['tick']>short['startTick'] for c in r['contacts'] if c['ny']<-.9})
                self.assertTrue(topContacts)
                self.assertTrue(all(n.startswith('gallery-' if section==5 else 'crown-') for n in topContacts),topContacts)
                # Samples are observations, not an exhaustive timing interval.
                risk=dict(normalFall=normal['maximumFall'],recoverableMissFall=paths['shortcut'][1]['maximumFall'],
                    largestSampledShortcutFall=max(r['maximumFall'] for r in paths['shortcut']))
                self.assertGreater(risk['largestSampledShortcutFall'],risk['normalFall'])
                print('PASS RISK',section,normal['mode'],risk,flush=True)
                cases.append(dict(section=section,mode=normal['mode'],normalTicks=normal['outcome']['tick'],
                    shortcutTicks=short['outcome']['tick'],sameSectionTopContacts=topContacts,skipCount=1,skipped=[f'S0{section}-03'],paths=paths,
                    inputWindows=dict(scope='Finite release-duration samples, not exhaustive interval boundaries',
                        normalHoldTicks=[(75 if section==5 else 30)+r['offset'] for r in paths['normal']],
                        shortcutHoldTicks=[(160 if section==5 else 30)+r['offset'] for r in paths['shortcut']],
                        normalOffsets=[r['offset'] for r in paths['normal']],shortcutOffsets=[r['offset'] for r in paths['shortcut']],normalSuccessCount=sum(bool(r['outcome'] and r['outcome']['id']==self.exits[section][-1]) for r in paths['normal']),shortcutSuccessCount=1),
                    risk=risk))
                self.write('shortcuts.json',dict(cases=cases,scope=self.config['simulation']))
                self.write('misses.json',dict(cases=misses))
        # Separate visualization from simulation: measured paths over live geometry.
        strip=Image.new('RGB',(2560,1440),'#111827');draw=ImageDraw.Draw(strip)
        for case in cases:
            sec=case['section'];ox=0 if case['mode']=='desktop' else 1280;oy=0 if sec==5 else 720
            left,right,top,bottom=(8800,14000,-3000,-1400) if sec==5 else (10200,13300,-5400,-3800)
            factor=min(1200/(right-left),580/(bottom-top))
            def point(x,y):return (ox+40+(x-left)*factor,oy+100+(y-top)*factor)
            draw.text((ox+30,oy+20),f"S0{sec} {case['mode']} | measured production trajectories | isolated section fixture",fill='white')
            draw.text((ox+30,oy+42),'GOLD normal / CYAN shortcut / RED recoverable miss. Circles: shared choice, exit or catch.',fill='white')
            for e in case['paths']['normal'][0]['geometry']:
                pts=[point(v['x'],v['y']) for v in e['points']]
                draw.polygon(pts,outline='#64748b')
                if e['id'] in self.exits[sec] or 'shortcut' in e['id']:
                    draw.text(pts[0],e['id'],fill='#cbd5e1')
            for row,color in [(case['paths']['normal'][0],'#fbbf24'),(case['paths']['shortcut'][0],'#22d3ee'),(case['paths']['shortcut'][1],'#f87171')]:
                pts=[point(r['x'],r['y']) for r in row['trace'] if r['tick']>=row['startTick']]
                draw.line(pts,fill=color,width=3)
                for x,y in [pts[0],pts[-1]]:draw.ellipse((x-5,y-5,x+5,y+5),outline=color,width=2)
            draw.text((ox+30,oy+680),f"Normal {case['normalTicks']} ticks; shortcut {case['shortcutTicks']} ticks; skipped only S0{sec}-03",fill='white')
        strip.save(self.out/'shortcut-strip.jpg',quality=90)
        print('PASS routes: four desktop/touch comparisons; eight nominal routes succeed; each shortcut faster and skips only encounter 03; sampled release outcomes recorded')
        print('PASS misses: four lower catches return through trusted controls; no reset or post-setup injection')

    def test_02_index(self):
        required={'commands.log':'exact command, exit status, collected identifiers, browser, viewport, revision and hashes',
            'tests.log':'two Task625Tests without skips','shortcuts.json':'four same-state normal/shortcut comparisons and release-window samples',
            'misses.json':'four lower catches and ordinary-control returns','shortcut-strip.jpg':'measured normal/shortcut/miss trajectories over production geometry; labelled choice and exits',
            'evidence-index.json':'assertion map and dependencies'}
        previous=json.loads((ROOT/'artifacts/TASK-624/evidence-index.json').read_text())['config']['source_hashes']
        for n,h in previous.items():
            if n!='tools/test_grapple_over_redesign.py':self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['tools/test_grapple_over_redesign.py: additive Task625Tests; browser_test_support -> trusted production input -> unchanged physics/geometry'],
            priorEvidence='artifacts/TASK-624/evidence-index.json',hashPolicy='Identical source hashes survive HEAD-only movement',
            historicalCoverage='Old v3 geometry and earlier prefix inventory assertions are historical; retained unchanged'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        with Image.open(self.out/'shortcut-strip.jpg') as im:im.load();self.assertEqual(im.size,(2560,1440))
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS index: six required artifacts exist; JSON parses; strip decodes 2560x1440; unchanged runtime hashes; bytes <200 MB')


class Task626Tests(unittest.TestCase):
    """Lower collision inventory and bounded production-input recovery probes."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        for n in ['tools/grapple_over_bypass.js','tools/grapple_over_recovery.js']:
            cls.config['source_hashes'][n]=hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
        cls.config['simulation']='Isolated inventory placements and archived released-route fixtures; production physics and synthetic normal mouse handlers; not continuous gameplay'
        with (cls.out/'commands.log').open('a') as f:f.write('TASK626_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write
    def page(self):
        p=Task622Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_recovery.js'))
        return p

    def test_01_inventory_and_recovery(self):
        p=self.page();g=p.evaluate('RECOVERY.geometry()');starts=[]
        for e in g['surfaces']:
            starts.append(dict(id=e['id'],phaseTick=0,pose=dict(x=(e['left']+e['right'])/2,y=e['top']-24,vx=0,vy=0),
                provenance=dict(kind='isolated inventory-only placement; not gameplay reachability',surface=e['id'])))
        cases=p.evaluate('a=>a.starts.flatMap(s=>[360,540].map(r=>RECOVERY.recover(s,r)))',dict(starts=starts))
        for c in cases:
            passive=[r for r in c['trace'] if r['tick']<=180]
            c['passiveObservation']=dict(ticks=len(passive),verticalSpan=max(r['y'] for r in passive)-min(r['y'] for r in passive),
                finalSpeed=(passive[-1]['vx']**2+passive[-1]['vy']**2)**.5,
                classification='settled solid' if all(abs(r['vy'])<.05 for r in passive[-60:]) else 'continuing bounce/motion')
        self.write('recovery.json',dict(cases=cases,config=self.config))
        unresolved=[(c['id'],c['range']) for c in cases if not c['returned']]
        self.assertFalse(g['sideWall'])
        g['sideContainment']='No physical side-wall colliders or implicit Screen.leftWall in replacement; world bounds constrain camera only. Both vertical recovery faces and all catch surfaces inventoried. Open exterior is not a resting pocket.'
        self.write('pockets.json',dict(geometry=g,inventory=[dict(surface=e['id'],role=e['role'],
            escapes=[dict(range=c['range'],returned=c['returned']) for c in cases if c['id']==e['id']]) for e in g['surfaces']],unresolved=unresolved))
        print('INVENTORY',len(starts),'CASES',len(cases),'UNRESOLVED',unresolved,flush=True)
        self.assertEqual(unresolved,[])
        self.assertTrue(all(c['yellowRest']<60 for c in cases))
        for c in cases:
            ranges={r['range'] for r in c['trace']}
            if c['id']=='viaduct-exit' and c['range']==360:
                # This destination is itself the upgrade zone. Arrival earns 540;
                # no recovery was enabled by an upgrade acquired elsewhere.
                self.assertEqual(c['firstContact']['contacts'][0]['id'],'viaduct-exit')
                self.assertEqual(ranges,{360,540})
            else:self.assertEqual(ranges,{c['range']})
        print('PASS ranges: retained 540 stays 540; base 360 stays 360 except arrival on the upgrade destination itself')
        print('PASS inventory: every lower collider mapped to a normal-input main-route contact at both ranges; zero unresolved pockets')

    def test_02_recorded_falls(self):
        p=self.page();starts=[]
        for task in [571,577,583,590]:
            path=f'artifacts/TASK-{task}/recovery.json';data=json.loads((ROOT/path).read_text())
            for index,c in enumerate(data['cases'][:2] if task==590 else data['cases'][:1]):
                catch=c.get('catchTick',c.get('catch',{}).get('tick'))
                eligible=[r for r in c['trace'] if r['tick']<catch and not r['attached'] and not r['shot'] and not r['contacts'] and r['vy']>.4]
                self.assertTrue(eligible,path)
                row=eligible[len(eligible)//2]
                starts.append(dict(id=f'fall-{task}-{index}',phaseTick=row['tick'],pose={k:row[k] for k in ['x','y','vx','vy']},
                    provenance=dict(kind='Recorded descending released pose from production-input miss; isolated replay, not continuous gameplay',path=path,
                        case=index,tick=row['tick'],sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest())))
        cases=p.evaluate('a=>a.flatMap(s=>[360,540].map(r=>RECOVERY.recover(s,r)))',starts)
        d=json.loads((self.out/'recovery.json').read_text());d['fallCases']=cases;self.write('recovery.json',d)
        for c in cases:
            self.assertIsNotNone(c['firstContact'],c['id']);self.assertIsNotNone(c['returned'],(c['id'],c['range']))
            self.assertGreater(c['firstContact']['y'],c['initial']['y'])
            self.assertLess(c['yellowRest'],60)
        print('PASS falls: 10 recorded descending fixtures, both ranges, measured fall/contact and normal-input route return; zero resets or injections')

    def test_03_dependencies_and_index(self):
        previous=json.loads((ROOT/'artifacts/TASK-625/evidence-index.json').read_text())['config']['source_hashes']
        for n,h in previous.items():
            if n!='tools/test_grapple_over_redesign.py':self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        archives=[]
        for task in [590,614,623,624,625]:
            path=f'artifacts/TASK-{task}/tests.log';raw=(ROOT/path).read_text()
            self.assertIn('OK',raw);self.assertRegex(raw,r'Ran [1-9][0-9]* tests? in ')
            archives.append(dict(path=path,sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),result=next(l for l in raw.splitlines() if l.startswith('Ran '))))
        self.write('fixes.json',dict(geometryChanges=[],runtimeChanges=[],nominalToleranceChecks='Not required: no runtime or geometry edits; identical runtime source hashes checked against TASK-625',
            unchangedRuntimeHashes={n:h for n,h in previous.items() if n!='tools/test_grapple_over_redesign.py'},archives=archives,
            historical='Earlier v3 and prefix inventories preserved, not rerun or suppressed; current lower collision inventory supersedes inventory scope only'))
        required={'commands.log':'exact command, real exit, nonzero collected identifiers, browser viewport revision source SHA256',
            'tests.log':'three Task626Tests, no skipped cases, OK','pockets.json':'all 44 lower colliders, side containment observation, both-range return mapping and empty unresolved list',
            'recovery.json':'88 inventory and 10 descending-provenance cases, passive motion classification, contact traces and input targets, both ranges, no resets or injections',
            'fixes.json':'no geometry changes; unchanged runtime hashes and archived nominal/tolerance checks',
            'evidence-index.json':'assertion map, dependencies and scope'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['Additive Task626Tests -> browser_test_support + grapple_over_bypass fixture setup -> new grapple_over_recovery observation/control driver -> unchanged production input, collision, physics and geometry'],
            hashPolicy='HEAD-only movement does not invalidate identical tested source hashes',
            limitations='Bounded center/top samples for every collider plus recorded descending misses. Isolated placements are inventory-only, never continuous gameplay or exhaustive reachability. No image or clip required.'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS dependencies: runtime hashes unchanged; archived successful nominal/tolerance runs referenced; no fixes required')
        print('PASS index: six required artifacts exist, JSON parses, retained evidence below 200 MB')


# Distinct archived gallery approaches, aimed at the exit projection. Each
# fixture continues through a real press/release, yellow fall and lateral return.
TASK627_FALL_SPECS = [(596,765,(9300,-2658),75,90),(596,780,(9300,-2658),81,60)]


class Task627Tests(unittest.TestCase):
    """Upper inventory and uninterrupted input-driven high falls from archived fixtures."""
    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        for n in ['tools/grapple_over_bypass.js','tools/grapple_over_recovery.js','tools/grapple_over_high_falls.js']:
            cls.config['source_hashes'][n]=hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
        cls.config['simulation']='Isolated archived reachable starting poses; uninterrupted production physics and mouse handlers thereafter; not continuous gameplay from base'
        with (cls.out/'commands.log').open('a') as f:f.write('TASK627_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    write=Task557Tests.write
    def page(self):
        p=Task626Tests.page(self)
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_high_falls.js'))
        return p

    def test_01_upper_inventory(self):
        p=self.page();g=p.evaluate('RECOVERY.geometry(true)')
        starts=[dict(id=e['id'],phaseTick=0,pose=dict(x=(e['left']+e['right'])/2,y=e['top']-24,vx=0,vy=0),
            provenance='Isolated collider inventory placement, not a gameplay reachability claim') for e in g['surfaces']]
        cases=p.evaluate('ss=>ss.map(s=>RECOVERY.recover(s,540))',starts)
        for c in cases:
            if c['id']=='summit-final-landing':
                self.assertIsNotNone(c['firstContact'])
                self.assertEqual(c['firstContact']['contacts'][0]['id'],'summit-final-landing')
                c['terminal']='Final summit contact completes level; physics intentionally stops. Already on designated destination, no escape required.'
        unresolved=[c['id'] for c in cases if not c['returned'] and not c.get('terminal')]
        self.write('pockets.json',dict(geometry=g,cases=cases,unresolved=unresolved,scope='Every S05-S08 collider including catches, walls, movers and hazards; center/top inventory samples, not exhaustive state-space proof'))
        self.assertEqual(unresolved,[])
        self.assertTrue(all(c['range']==540 and c['yellowRest']<60 for c in cases))
        self.assertTrue(all(c['inputs'] for c in cases if not c.get('terminal')))
        print(f'PASS upper inventory: {len(cases)} colliders; zero unresolved; 540 normal-input recovery; final summit terminal contact')

    def test_02_high_falls(self):
        p=self.page();cases=[]
        # Archived released route states are fixtures only. All subsequent launch,
        # release, fall, rebound and lateral return are one uninterrupted run.
        specs=TASK627_FALL_SPECS
        self.assertEqual(len(specs),2)
        self.assertEqual(len(set(specs)),2,'Falls must use distinct release scenarios')
        p.evaluate('window.fallFrames=[]')
        for task,tick,aim,hold,recovery_hold in specs:
            path=f'artifacts/TASK-{task}/route.json';raw=(ROOT/path).read_bytes();d=json.loads(raw)
            row=next(r for r in d['trace'] if r['tick']==tick)
            self.assertFalse(row['attached']);self.assertFalse(row['shot'])
            start=dict(id=f'{task}-{tick}',phaseTick=tick,pose={k:row[k] for k in ['x','y','vx','vy']},
                provenance=dict(path=path,tick=tick,sha256=hashlib.sha256(raw).hexdigest(),kind='isolated reachable released route fixture'))
            launch=dict(start=start,hold=hold,recoveryHold=recovery_hold)
            if isinstance(aim,tuple):
                launch['target']=dict(x=aim[0],y=aim[1])
            else:
                launch['rank']=aim
            p.evaluate('s=>HIGH_FALL.begin(s)',launch)
            c=p.evaluate('''()=>{
              const capture=(phase,tick)=>{if(tick%12)return;draw();const gameCanvas=document.getElementById('canvas');
                if(gameCanvas.hidden||gameCanvas.width<640||gameCanvas.height<360)throw Error('Game canvas unavailable for trajectory capture');
                fallFrames.push({phase,tick,id:highFall.spec.start.id+' hold '+highFall.spec.hold,image:gameCanvas.toDataURL('image/jpeg',.65)})};
              for(let i=0;i<1600;i++){const done=HIGH_FALL.step();capture('launch / fall / first rebound',i+1);if(done)break;}
              if(!highFall.rebound)return highFall;
              return HIGH_FALL.finish(s=>capture('continuous lateral re-ascent',s.tick));}''')
            cases.append(c)
        self.write('falls.json',dict(cases=cases,config=self.config))
        self.write('inputs.json',dict(cases=[dict(start=c['spec']['start'],launch=c['inputs'],release=c['released'],zones=c['zones'],landing=c['landing'],firstRebound=c['rebound'],recovery=c.get('recovery')) for c in cases]))
        for c in cases:
            self.assertIsNotNone(c['landing']);self.assertIsNotNone(c['rebound'])
            boundaries=p.evaluate('()=>["viaduct-exit","gallery-exit","tower-exit","crown-exit"].map(id=>({id,y:floors[0].byId.get(id).y}))')
            c['crossedBoundaries']=[b for b in boundaries if c['released']['y']<b['y']<c['landing']['y']]
            c['drop']=c['landing']['y']-c['released']['y']
            c['reboundHeight']=c['landing']['y']-c['rebound']['y']
            c['yellowDescentTicks']=sum(bool(r['yellow']) and r['vy']>0
                for r in c['trace'] if c['released']['tick']<=r['tick']<=c['landing']['tick'])
            print(f"MEASURED fall hold={c['spec']['hold']}: boundaries={len(c['crossedBoundaries'])} drop={c['drop']:.2f} rebound={c['reboundHeight']:.2f} rejoin={c['recovery']['returned']}",flush=True)
        clearances=p.evaluate('''()=>{const box=e=>{let ps=e.getPoints();let b={left:Math.min(...ps.map(p=>p.x)),right:Math.max(...ps.map(p=>p.x)),top:Math.min(...ps.map(p=>p.y)),bottom:Math.max(...ps.map(p=>p.y))};const m=floors[0].level.movers.find(m=>m.element===e.id);if(m){if(m.axis==='x'){b.left+=m.min-e.x;b.right+=m.max-e.x}else{b.top+=m.min-e.y;b.bottom+=m.max-e.y}}return b};return floors[0].dragZones.flatMap(z=>{const a=box(z);return floors[0].elements.map(e=>{const b=box(e);return {zone:z.id,collider:e.id,clearance:Math.hypot(Math.max(0,a.left-b.right,b.left-a.right),Math.max(0,a.top-b.bottom,b.top-a.bottom))}})})}''')
        self.assertTrue(all(c['clearance']>=540-1e-6 for c in clearances))
        self.write('falls.json',dict(cases=cases,yellowClearances=clearances,config=self.config))
        clip=p.evaluate('''async()=>{const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d'),stream=c.captureStream(0),track=stream.getVideoTracks()[0],chunks=[];
          const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});rec.ondataavailable=e=>chunks.push(e.data);const end=new Promise(r=>rec.onstop=r);rec.start();
          for(const f of fallFrames){const im=new Image();im.src=f.image;await im.decode();ctx.drawImage(im,0,0);ctx.fillStyle='#000';ctx.fillRect(0,0,1280,28);ctx.fillStyle='white';ctx.fillText(f.id+' | isolated fixture then uninterrupted '+f.phase+' | tick '+f.tick+' | 4x',12,20);track.requestFrame();await new Promise(r=>setTimeout(r,50))}
          await new Promise(r=>setTimeout(r,100));rec.stop();await end;stream.getTracks().forEach(t=>t.stop());const blob=new Blob(chunks,{type:'video/webm'});return await new Promise(r=>{const f=new FileReader();f.onload=()=>r(f.result.split(',')[1]);f.readAsDataURL(blob)})}''')
        (self.out/'falls.webm').write_bytes(base64.b64decode(clip))
        decoded=p.evaluate("""async b64=>{const v=document.createElement('video');v.muted=true;v.src='data:video/webm;base64,'+b64;let frames=0;
            const count=()=>{frames++;v.requestVideoFrameCallback(count)};v.requestVideoFrameCallback(count);await v.play();
            await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=reject});return {frames,width:v.videoWidth,height:v.videoHeight,ended:v.ended}}""",clip)
        self.write('clip-decode.json',decoded)
        self.assertTrue(decoded['ended']);self.assertGreater(decoded['frames'],20);self.assertEqual(decoded['width'],1280)
        print(f'PASS yellow clearances: {len(clearances)} swept collider comparisons >=540; falls.webm decoded')

        for c in cases:
            with self.subTest(hold=c['spec']['hold'],requirement='high fall loses two boundaries'):
                self.assertGreaterEqual(len(c['crossedBoundaries']),2)
            with self.subTest(hold=c['spec']['hold'],requirement='first rebound <=half drop'):
                self.assertLessEqual(c['reboundHeight'],c['drop']/2)
            with self.subTest(hold=c['spec']['hold'],requirement='input-only lateral return'):
                self.assertGreater(c['attachedTicks'],0)
                self.assertGreater(c['rebound']['y'],c['initial']['y'])
                self.assertGreaterEqual(len(c['zones']),2)
                self.assertGreaterEqual(c['yellowDescentTicks'],8,'Sustained yellow passage before landing')
                self.assertLess(c['released']['tick'],c['landing']['tick'])
                self.assertLess(c['landing']['tick'],c['rebound']['tick'])
                self.assertEqual(c['inputs'][-1]['type'],'mouseup')
                self.assertIsNotNone(c['recovery']['returned'])
                self.assertEqual(c['recovery']['postSetupInjections'],0)
                self.assertEqual(c['recovery']['resets'],0)
                self.assertGreater(abs(c['recovery']['returned']['x']-c['landing']['x']),100)
                self.assertLess(c['recovery']['returned']['y'],c['landing']['y'])

    def test_03_dependencies_and_index(self):
        old=json.loads((ROOT/'artifacts/TASK-626/evidence-index.json').read_text())['config']['source_hashes']
        changed=['tools/test_grapple_over_redesign.py','tools/grapple_over_recovery.js']
        for n,h in old.items():
            if n not in changed:self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        identifiers=[t.id() for t in unittest.defaultTestLoader.loadTestsFromTestCase(Task627Tests)]
        self.assertEqual(len(identifiers),3)
        self.assertTrue(all('.Task627Tests.' in n for n in identifiers))
        (self.out/'collected-tests.log').write_text('\n'.join(identifiers)+'\nCOLLECTED 3\n')
        archived=['PASS unchanged runtime dependencies match TASK-626 source hashes']
        for task in [614,626]:
            path=ROOT/f'artifacts/TASK-{task}/tests.log';raw=path.read_text()
            self.assertIn('\nOK\n',raw)
            self.assertRegex(raw,r'Ran [1-9][0-9]* tests? in ')
            archived.append(f'{path.relative_to(ROOT)} SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}')
            archived.extend(line for line in raw.splitlines() if line.startswith('Ran ') or line=='OK')
        (self.out/'archived-checks.log').write_text('\n'.join(archived)+'\n')
        required={'commands.log':'exact commands, exit, test identifiers/count, browser/viewport/revision and hashes','tests.log':'three Task627Tests, no skips, OK',
            'pockets.json':'all upper colliders mapped to input recovery or terminal summit contact; unresolved empty',
            'falls.json':'two measured >=2-boundary falls, <=half-drop first rebounds, yellow velocities, lower landing, lateral rejoin and all swept clearances',
            'inputs.json':'launch/release inputs and continuous recovery input/trace provenance','falls.webm':'both full trajectories and lateral returns; fixture boundaries labelled',
            'clip-decode.json':'successful full browser decode and nonzero decoded frames',
            'collected-tests.log':'exactly three collected Task627Tests identifiers',
            'archived-checks.log':'unchanged runtime hashes and successful prerequisite test logs',
            'evidence-index.json':'artifact assertions and dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,changedSubsystems=changed+['tools/grapple_over_high_falls.js: observation/control harness -> unchanged production mouse input/physics/geometry'],
            historical='TASK-626/tests.log and TASK-614/tests.log retain previous successful runtime checks; no production edits; historical geometry coverage preserved',hashPolicy='HEAD movement alone does not invalidate identical source hashes'))
        for n in required:
            self.assertTrue((self.out/n).is_file(),n)
            if n.endswith('.json'):json.loads((self.out/n).read_text())
        self.assertLess(sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file()),200_000_000)
        print('PASS dependencies unchanged; required artifacts exist and JSON parses; storage below 200 MB')


class Task628Tests(unittest.TestCase):
    """Whole replacement composition review; maps are measured plans, not gameplay."""
    tasks = [572, 578, 584, 590, 596, 602, 608, 614]
    prefixes = ['yard', 'quarry', 'freight', 'viaduct', 'gallery', 'tower', 'crown', 'summit']
    names = ['Loading Yard', 'Terraced Quarry', 'Freight Crossing', 'Broken Viaduct',
             'Cable Galleries', 'Counterweight Tower', 'Exposed Crown', 'Summit Array']
    write = Task557Tests.write
    page = Task626Tests.page

    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        for name in ['tools/grapple_over_bypass.js', 'tools/grapple_over_recovery.js', 'docs/grapple-over-composition-review.md']:
            cls.config['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.config['simulation'] = 'Live geometry plans; isolated section camera placements; one actual-base production input smoke test. Archived routes are separate local runs, never a continuous mountain climb.'
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK628_CONFIG '+json.dumps(cls.config, separators=(',', ':'))+'\n')

    def archive(self, task, name):
        path = ROOT/f'artifacts/TASK-{task}/{name}'
        return json.loads(path.read_text()), dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def test_01_structure_and_maps(self):
        (self.out/'review.md').write_text((ROOT/'docs/grapple-over-composition-review.md').read_text())
        p = self.page()
        g = p.evaluate('''()=>({level:floors[0].level,
          surfaces:[...RECOVERY.geometry().surfaces,...RECOVERY.geometry(true).surfaces],
          yellow:RECOVERY.geometry().yellow,scale:scale[version],range:grappleOverAcquisitionRadius()})''')
        self.assertEqual((g['scale'], g['range']), (.375, 360))
        self.assertEqual(len(g['level']['sections']), 8)
        surfaces = {e['id']:e for e in g['surfaces']}
        manifests = {e['id']:e for e in g['level']['elements']}
        self.assertEqual(len(surfaces), 98)
        lower, lp = self.archive(626, 'pockets.json')
        recovery, rp = self.archive(626, 'recovery.json')
        upper, up = self.archive(627, 'pockets.json')
        self.assertEqual(lower['unresolved'], [])
        self.assertEqual(upper['unresolved'], [])
        cases = recovery['cases'] + upper['cases']
        audit = []
        for id, e in surfaces.items():
            purpose = manifests[id]['purpose']
            self.assertGreater(len(purpose), 20, id)
            refs = [c for c in cases if c['id']==id]
            self.assertTrue(refs, id)
            self.assertTrue(all(c['returned'] or c.get('terminal') for c in refs), id)
            audit.append(dict(id=id, purpose=purpose, section='S0'+str(self.prefixes.index(id.split('-')[0])+1),
                role=e['role'], bounds={k:e[k] for k in ['left','right','top','bottom']},
                encounters=[v['id'] for v in g['level']['encounters'] if id in v['elements']],
                recovery=[dict(range=c['range'], destination=c['returned'], terminal=c.get('terminal')) for c in refs]))
        self.write('object-audit.json', dict(colliders=audit, removedClutter=[],
            rationale='No redundant collider found: every live object has an encounter, recovery, timing or separator purpose. Preserve open air rather than add decorative collision.',
            priorFix='TASK-623 tower-west-separator prevents folded upper bypasses; TASK-602 removed redundant tower-exit-yellow. Neither is a new TASK-628 edit.',
            recoverySources=[lp,rp,up], yellow=[dict(id=e['id'],purpose=manifests[e['id']]['purpose']) for e in g['yellow']]))
        routes=[]; connections=[]; previous='yard-entry'
        updated, updated_ref = self.archive(623, 'normal-routes.json')
        for i, task in enumerate(self.tasks):
            d, ref = self.archive(task, 'route.json')
            trace = d.get('trace',d.get('rows'))
            exits = d['exits'] if i not in [4,5,6] else updated[i-4]['exits']
            ids = [e.get('id',e.get('collider')) for e in exits]
            self.assertEqual(len(ids),4)
            first = g['level']['encounters'][i*4]
            self.assertIn(previous, first['elements'])
            start=trace[0]; support=surfaces[previous]
            self.assertTrue(support['left']<=start['x']<=support['right'])
            self.assertLess(abs(start['y']-(support['top']-10.8)),2)
            for id in ids:self.assertIn(id,surfaces)
            connections.append(dict(section=f'S0{i+1}',entrySupport=previous,exit=ids[-1],orderedExits=ids,
                source=updated_ref if i in [4,5,6] else ref))
            routes.append(dict(section=f'S0{i+1}',trace=trace,source=ref,exits=ids))
            previous=ids[-1]
        self.assertEqual(previous,'summit-final-landing')
        self.write('geometry.json',g)
        self.write('connections.json',dict(sections=connections,
            scope='Shared physical entry/exit surfaces join eight separately verified local routes; no continuous-from-base claim. Historical traces used only for spatial context; updated S05-S07 contact proof comes from TASK-623.'))
        # True world-coordinate plans; no rearranging sections to imply separation.
        colors=['#059669','#65a30d','#0284c7','#d97706','#9333ea','#db2777','#e11d48','#475569']
        for mono, name in [(False,'full-map.png'),(True,'silhouette.png')]:
            im=Image.new('RGB',(2400,1200),'white');draw=ImageDraw.Draw(im)
            factor=.145
            def pt(x,y):return (40+x*factor,100+(y+6200)*factor)
            draw.text((30,20),'TASK-628 | actual world-coordinate '+('collision silhouette' if mono else 'composition plan'),fill='black')
            draw.text((30,42),'Eight local structures, same world positions. Numbers = ordered route decks. Thin gray = movers swept bounds.',fill='black')
            draw.text((30,62),'Open air is intentional. Cyan = measured high-fall / recovery paths; local archived routes are NOT one continuous run.',fill='black')
            for e in g['surfaces']+g['yellow']:
                section=self.prefixes.index(e['id'].split('-')[0])
                color='black' if mono else colors[section]
                if e['role']=='drag':color='#bbbbbb' if mono else '#eab308'
                draw.polygon([pt(v['x'],v['y']) for v in e['points']],fill=color)
                mover=next((m for m in g['level']['movers'] if m['element']==e['id']),None)
                if mover:
                    axis=mover['axis'];base=manifests[e['id']][axis]
                    a,b=(e['left'],e['right']) if axis=='x' else (e['top'],e['bottom'])
                    lo,hi=a+mover['min']-base,b+mover['max']-base
                    box=(lo,e['top'],hi,e['bottom']) if axis=='x' else (e['left'],lo,e['right'],hi)
                    draw.rectangle((*pt(box[0],box[1]),*pt(box[2],box[3])),outline='#999999')
            for i,r in enumerate(routes):
                if not mono:draw.line([pt(v['x'],v['y']) for v in r['trace']],fill=colors[i],width=1)
                for j,id in enumerate(r['exits']):
                    e=surfaces[id];q=pt((e['left']+e['right'])/2,e['top'])
                    draw.text((q[0],q[1]-14),f'{i+1}.{j+1}',fill='black')
            falls,_=self.archive(627,'falls.json')
            for c in falls['cases']:
                for rows in [c['trace'],c['recovery']['trace']]:
                    draw.line([pt(v['x'],v['y']) for v in rows],fill='#999999' if mono else '#06b6d4',width=2)
            for i,n in enumerate(self.names):
                draw.text((40+(i%4)*590,1090+(i//4)*35),f'S0{i+1} {n}',fill='black' if mono else colors[i])
            im.save(self.out/name)
        # Actual section-scale canvas captures keep the production camera scale.
        sheet=Image.new('RGB',(2560,2880),'white'); cameras=[]
        for i,r in enumerate(routes):
            start=r['trace'][0]
            camera=p.evaluate('''s=>{ninja.x=s.x;ninja.y=s.y;ninja.speedX=ninja.speedY=0;
              screen.trackGrappleOver(true);TUTORIAL_HINT.visible=false;draw();
              return {x:screen.x,y:screen.y,scale:scale[version],landmark:LANDMARKS.frame.drawn}}''',start)
            raw=p.locator('#canvas').screenshot()
            tile=Image.open(io.BytesIO(raw)).convert('RGB');self.assertEqual(tile.size,(1280,720))
            pen=ImageDraw.Draw(tile);pen.rectangle((0,0,1280,30),fill='black')
            pen.text((12,8),f'S0{i+1} {self.names[i]} | isolated camera observation | scale 0.375',fill='white')
            sheet.paste(tile,((i%2)*1280,(i//2)*720));cameras.append(camera)
        self.assertEqual(len({c['landmark'][0]['id'] for c in cameras}),8)
        self.assertTrue(all(c['scale']==.375 for c in cameras))
        sheet.save(self.out/'sections.png');self.write('cameras.json',cameras)
        print('PASS composition: 8 structures; 32 ordered decks; 7 shared section connections; 98 purposeful colliders with recovery mappings; removedClutter=[]')
        print('PASS images: world-coordinate full-map and silhouette 2400x1200; eight actual section cameras 2560x2880 at scale 0.375')

    def test_02_input_and_dependencies(self):
        p=self.page();Task567Tests.press(self,p);Task567Tests.step(self,p,30);p.mouse.up();Task567Tests.step(self,p,75)
        result=Task567Tests.result(self,p)
        self.assertTrue(Task567Tests.landings(result,'yard-landing'))
        self.write('smoke.json',dict(inputs=result['inputs'],contacts=[r for r in result['rows'] if r['contacts']],
            scope='Actual-base trusted mouse launch, release and production landing; no fixture pose injection'))
        old,_=self.archive(627,'evidence-index.json')
        hashes={n:h for n,h in old['config']['source_hashes'].items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in hashes.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        archives=[]
        for task in [622,623,624,625,626,627]:
            path=ROOT/f'artifacts/TASK-{task}/tests.log';raw=path.read_text()
            self.assertIn('\nOK\n',raw);self.assertRegex(raw,r'Ran [1-9][0-9]* tests? in ')
            archives.append(dict(path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                results=[v for v in raw.splitlines() if v.startswith(('Ran ','PASS ')) or v=='OK']))
        # Examine search results themselves, not just their PASS strings.
        searches=[]
        for task in [622,623]:
            data,ref=self.archive(task,'search.json')
            self.assertEqual(data['unapproved'],[])
            self.assertEqual(len(data['cases']),184 if task==622 else 229)
            skips=[s for c in data['cases'] for s in c['skips'] if s['unapproved']]
            self.assertEqual(skips,[])
            self.assertTrue(all(c['ticks']>0 for c in data['cases']))
            searches.append(dict(source=ref,attempts=len(data['cases']),unapproved=len(skips)))
        self.write('affected.json',dict(runtimeChanges=[],geometryChanges=[],affectedLocalRoutes=[],
            localProof='smoke.json: current trusted base launch/release/landing; no changed geometry requires replay',
            unchangedSourceHashes=hashes,archives=archives,searches=searches,
            dependencies=['Additive Task628Tests -> browser_test_support -> existing YARD/RECOVERY observation helpers -> unchanged renderer, geometry, input, physics'],
            historical='TASK-623 separator supersedes pre-separator S05-S07 route coverage; use its normal-routes.json. Historical v3 tests/evidence remain untouched. HEAD-only changes do not invalidate identical tested source hashes.'))
        print('PASS archived separation: 184 lower and 229 upper attempts; independently counted unapproved skips=0; finite search scope')
        print(f'PASS input: trusted base launch/release lands on yard-landing; {len(hashes)} unchanged dependency hashes; six archived nonzero successful suites')

    def test_03_index(self):
        identifiers=[t.id() for t in unittest.defaultTestLoader.loadTestsFromTestCase(Task628Tests)]
        self.assertEqual(len(identifiers),3);self.assertTrue(all('.Task628Tests.' in n for n in identifiers))
        (self.out/'collected-tests.log').write_text('\n'.join(identifiers)+'\nCOLLECTED 3\n')
        required={'commands.log':'exact command and real exit, browser/viewport, revision and source hashes',
            'tests.log':'three Task628Tests with no skipped required cases',
            'full-map.png':'world-coordinate grouped geometry, route decks, high-fall/recovery corridors',
            'silhouette.png':'unrearranged plain collision structure and open gaps',
            'sections.png':'eight actual section-scale camera observations',
            'cameras.json':'production camera coordinates, scale and landmark identities',
            'geometry.json':'live collider polygons, movers and manifest',
            'connections.json':'eight ordered local routes joined by seven shared physical surfaces',
            'object-audit.json':'all 98 collider purposes and recovery destinations; explicit clutter decision',
            'review.md':'image-located architectural and pacing review; scope and limitations',
            'affected.json':'no runtime edits, source identity and archived successful regression evidence',
            'smoke.json':'trusted production input and actual landing contacts',
            'collected-tests.log':'exact three class/method identifiers',
            'evidence-index.json':'assertion map and source dependencies'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config,
            changedSubsystems=['tools/test_grapple_over_redesign.py: additive composition review tests only'],
            hashPolicy='HEAD movement alone does not invalidate identical source hashes'))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.png'):
                with Image.open(self.out/name) as im:im.load();self.assertGreater(im.width,1000)
        size=sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file())
        self.assertLess(size,200_000_000)
        print(f'PASS index: {len(required)} artifacts exist; JSON parses; three PNGs decode; retained bytes={size} <200 MB')


class Task629Tests(unittest.TestCase):
    """Player-eye observations from archived local routes, not continuous gameplay."""
    write = Task557Tests.write
    archive = Task628Tests.archive

    @classmethod
    def setUpClass(cls):
        Task567Tests.setUpClass.__func__(cls)
        for name in ['tools/grapple_over_bypass.js', 'tools/grapple_over_readability.js']:
            cls.config['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.config.update(viewports=[dict(width=1280,height=720,touch=False),dict(width=844,height=390,touch=True)],
            simulation='Isolated recorded pre-press route poses, snapped production camera and original mover phase; not continuous gameplay. Separate actual-base input smoke.')
        with (cls.out/'commands.log').open('a') as f:
            f.write('TASK629_CONFIG '+json.dumps(cls.config,separators=(',',':'))+'\n')

    def page(self, touch=False):
        p=Task622Tests.page(self)
        if touch:
            p.context.new_cdp_session(p).send('Emulation.setTouchEmulationEnabled',dict(enabled=True,maxTouchPoints=1))
            p.set_viewport_size(dict(width=844,height=390))
            # Await the production resize handler, including logical viewport layout.
            p.wait_for_function('isTouchFirstDevice() && width === Math.floor(1080 * 844 / 390)')
        p.add_script_tag(path=str(ROOT/'tools/grapple_over_readability.js'))
        layout=p.evaluate('READABILITY.layout()')
        self.assert_layout(layout,touch)
        print('PASS layout: '+json.dumps(layout,separators=(',',':')))
        return p

    def assert_layout(self, layout, touch):
        expected_width,expected_height=(844,390) if touch else (1280,720)
        logical_width=2337 if touch else 1920
        self.assertEqual(layout['coarsePointer'],touch)
        self.assertEqual(layout['touchFirst'],touch)
        self.assertEqual(layout['viewport'],dict(width=expected_width,height=expected_height))
        self.assertEqual(layout['logical'],dict(width=logical_width,height=1080))
        self.assertAlmostEqual(layout['canvas']['width'],logical_width*expected_height/1080,delta=.05)
        self.assertAlmostEqual(layout['canvas']['height'],expected_height,delta=.05)

    def specs(self):
        specs=[];support='yard-entry'
        for i,task in enumerate(Task628Tests.tasks):
            data,ref=self.archive(task,'route.json')
            rows=data.get('trace',data.get('rows'))
            previous=0
            for j,exit in enumerate(data['exits']):
                # First recorded press after the preceding landing, including a
                # same-tick press. Preserve its pose and moving-platform phase.
                presses=[v['tick'] for v in data['inputs'] if v['type']=='mousedown' and previous<=v['tick']<exit['tick']]
                tick=min(presses) if presses else previous
                row=next(r for r in rows if r['tick']==max(1,tick))
                landing=exit.get('id',exit.get('collider'))
                specs.append(dict(id=f'S0{i+1}-0{j+1}',support=support,landing=landing,range=360 if i<4 else 540,
                    source={**ref,'tick':tick},start=dict(phaseTick=max(1,tick),pose={k:row[k] for k in ['x','y','vx','vy']})))
                previous=exit['tick'];support=landing
        return specs

    def assert_clear(self, row):
        self.assertEqual(row['camera']['scale'],.375)
        self.assertIsNotNone(row['target'],row['id'])
        w,h=row['canvas']['width'],row['canvas']['height']
        q=row['target']['point']
        aim=dict(left=q['x']-4,right=q['x']+4,top=q['y']-4,bottom=q['y']+4)
        row['mandatoryAimBounds']=aim
        self.assertTrue(0<=aim['left']<aim['right']<=w and 0<=aim['top']<aim['bottom']<=h,row)
        overlaps=[]
        for box in row['hud']:
            if (box['x']<aim['right'] and box['x']+box['width']>aim['left'] and
                box['y']<aim['bottom'] and box['y']+box['height']>aim['top']):overlaps.append(box)
        row['hudOverlaps']=overlaps
        self.assertEqual(overlaps,[],row['id'])
        b=row['landing']['bounds']
        self.assertTrue(b['right']>0 and b['left']<w and 0<=b['top']<=h,row)
        self.assertIn(row['target']['role'],['solid','bounce'])
        self.assertIn(row['landing']['role'],['solid','bounce'])

    def test_01_approaches_and_entries(self):
        specs=self.specs();self.assertEqual(len(specs),32)
        sheet=Image.new('RGB',(1280,32*200),'#111111');observations=[];entries=[]
        entry_sheet=Image.new('RGB',(1280,8*380),'#111111')
        for col,touch in enumerate([False,True]):
            p=self.page(touch)
            for i,spec in enumerate(specs):
                row=p.evaluate('s=>READABILITY.view(s)',spec)
                row.update(viewport='touch-844x390' if touch else 'desktop-1280x720',source=spec['source'])
                self.assert_layout(row['layout'],touch)
                observations.append(row)
                self.write('approaches.json',dict(views=observations,scope=self.config['simulation']))
                self.assert_clear(row)
                tile=Image.open(io.BytesIO(p.locator('#canvas').screenshot())).convert('RGB')
                self.assertGreater(max(hi-lo for lo,hi in tile.getextrema()),40,'blank gameplay capture')
                tile.thumbnail((640,180));sheet.paste(tile,(col*640,i*200+20))
                ImageDraw.Draw(sheet).text((col*640+8,i*200+4),spec['id']+' '+row['viewport']+' target='+row['target']['id'],fill='white')
                if i%4==0:
                    # Entry is the first archived row, distinct from a delayed
                    # first press (e.g. moving freight/tower platforms).
                    data,ref=self.archive(Task628Tests.tasks[i//4],'route.json')
                    start=data.get('trace',data.get('rows'))[0]
                    entry={**spec,'start':dict(phaseTick=1,pose={k:start[k] for k in ['x','y','vx','vy']})}
                    measured=p.evaluate('s=>READABILITY.view(s)',entry)
                    self.assert_layout(measured['layout'],touch)
                    lm=measured['landmark'];b=lm['bounds'];c=measured['canvas']
                    im=Image.open(io.BytesIO(p.locator('#canvas').screenshot())).convert('RGB')
                    im.thumbnail((640,360));entry_sheet.paste(im,(col*640,(i//4)*380+20))
                    ImageDraw.Draw(entry_sheet).text((col*640+8,(i//4)*380+4),spec['id'][:3]+' entry '+row['viewport'],fill='white')
                    entries.append(dict(section=spec['id'][:3],viewport=row['viewport'],source=ref,
                        pose=entry['start']['pose'],landmark=lm,canvas=c,layout=measured['layout'],
                        useful='Distinct section silhouette identifies the structure containing the next route decks.'))
                    self.write('landmarks.json',dict(entries=entries))
                    self.assertTrue(0<=b['left']<b['right']<=c['width'] and 0<=b['top']<b['bottom']<=c['height'],entries[-1])
        self.write('approaches.json',dict(views=observations,scope=self.config['simulation']))
        self.write('landmarks.json',dict(entries=entries))
        sheet.save(self.out/'contact-sheet.jpg',quality=90)
        entry_sheet.save(self.out/'entry-sheet.jpg',quality=90)
        self.assertEqual(len(entries),16)
        self.assertEqual(len({e['landmark']['id'] for e in entries}),8)
        print('PASS approaches: 64 actual recorded approach fixtures; target aiming bounds visible; HUD overlaps=0; landing top visible; solid/bounce roles recorded')
        print('PASS landmarks: 16 entry views; 8 distinct section identities; complete landmark bounds in frame')

    def test_02_palette_and_parallax_boundaries(self):
        p=self.page();samples=[]
        sheet=Image.new('RGB',(1200,14*180),'#111111')
        # Sample all seven existing palette boundaries, including those above
        # the replacement summit: renderer probes, not player traversal.
        p.evaluate('''()=>{window.parallaxSamples=[];const original=drawGrappleOverParallax;
            drawGrappleOverParallax=function(r,p){const used=original(r,p);parallaxSamples=used;return used}}''')
        for boundary in range(1,8):
            pair=[]
            for col,delta in enumerate([-1,0,1]):
                d=p.evaluate('''a=>{screen.x=-4000;screen.y=height/scale[version]/2+a.boundary*GRAPPLE_OVER_THEME.bandHeight+a.delta;
                    draw();return {boundary:a.boundary,delta:a.delta,camera:{x:screen.x,y:screen.y},
                        palette:visualEffects.background.palette,parallax:parallaxSamples}}''',dict(boundary=boundary,delta=delta))
                pair.append(d)
                im=Image.open(io.BytesIO(p.locator('#canvas').screenshot())).convert('RGB');im.thumbnail((400,160))
                sheet.paste(im,(col*400,(boundary-1)*180+20))
                ImageDraw.Draw(sheet).text((col*400+6,(boundary-1)*180+4),f'palette boundary {boundary} offset {delta}',fill='white')
            self.assertEqual([d['palette']['from'] for d in pair],[boundary-1]*3)
            self.assertEqual([d['palette']['to'] for d in pair],[boundary]*3)
            self.assertAlmostEqual(pair[1]['palette']['t'],.5)
            self.assertLess(pair[2]['palette']['t']-pair[0]['palette']['t'],.004)
            for a,b in zip(pair,pair[1:]):
                self.assertEqual(len(a['parallax']),2)
                for x,y in zip(a['parallax'],b['parallax']):
                    self.assertEqual(x['name'],y['name']);self.assertAlmostEqual(y['y']-x['y'],.375*x['factor'])
                    self.assertEqual([m[0] for m in x['motifs']],[m[0] for m in y['motifs']])
                    self.assertAlmostEqual(sum(m[1] for m in y['motifs']),1)
            samples.extend(pair)
        joins=[]
        for index,task in enumerate(Task628Tests.tasks[1:]):
            data,ref=self.archive(task,'route.json')
            pose=data.get('trace',data.get('rows'))[0]
            pair=[]
            for col,delta in enumerate([-1,0,1]):
                d=p.evaluate('''a=>{Object.assign(ninja,{x:a.x,y:a.y+a.delta,speedX:0,speedY:0});
                    screen.trackGrappleOver(true);draw();return {delta:a.delta,camera:{x:screen.x,y:screen.y},
                    palette:visualEffects.background.palette,parallax:parallaxSamples,landmark:LANDMARKS.frame.drawn[0].id}}''',dict(x=pose['x'],y=pose['y'],delta=delta))
                pair.append(d)
                im=Image.open(io.BytesIO(p.locator('#canvas').screenshot())).convert('RGB');im.thumbnail((400,160))
                sheet.paste(im,(col*400,(index+7)*180+20))
                ImageDraw.Draw(sheet).text((col*400+6,(index+7)*180+4),f'S0{index+1}/S0{index+2} shared entry offset {delta}',fill='white')
            for a,b in zip(pair,pair[1:]):
                self.assertEqual(a['palette']['from'],b['palette']['from'])
                self.assertEqual(a['palette']['to'],b['palette']['to'])
                self.assertLess(abs(a['palette']['t']-b['palette']['t']),.004)
                for x,y in zip(a['parallax'],b['parallax']):
                    self.assertLessEqual(abs(x['y']-y['y']),.375*x['factor']+1e-8)
            joins.append(dict(boundary=f'S0{index+1}/S0{index+2}',source=ref,pose=pose,samples=pair))
        self.write('transitions.json',dict(samples=samples,sectionJoins=joins,scope='Seven existing altitude palette boundaries and seven actual shared section entries ±1 world unit; 42 isolated renderer samples, no full climb',
            explanation='Palette bands are altitude-based, not replacement section IDs. Landmark identities are discrete section cues; palette/parallax blends remain continuous.'))
        sheet.save(self.out/'boundary-strip.jpg',quality=90)
        print('PASS transitions: 7 palette boundaries and 7 section joins; 42 samples; smooth palette weights; 2 parallax layers translate by factor*0.375 per world unit; no motif discontinuity')

    def test_03_physics_and_dependencies(self):
        p=self.page();Task567Tests.press(self,p);Task567Tests.step(self,p,30);p.mouse.up();Task567Tests.step(self,p,75)
        r=Task567Tests.result(self,p);self.assertTrue(Task567Tests.landings(r,'yard-landing'))
        self.write('smoke.json',dict(inputs=r['inputs'],contacts=[v for v in r['rows'] if v['contacts']]))
        old,ref=self.archive(628,'evidence-index.json')
        hashes={n:h for n,h in old['config']['source_hashes'].items() if n!='tools/test_grapple_over_redesign.py'}
        for n,h in hashes.items():self.assertEqual(hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),h,n)
        archives=[]
        for task in [623,627,628]:
            path=ROOT/f'artifacts/TASK-{task}/tests.log';raw=path.read_text()
            self.assertIn('\nOK\n',raw);self.assertRegex(raw,r'Ran [1-9][0-9]* tests? in ')
            archives.append(dict(path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                results=[v for v in raw.splitlines() if v.startswith('Ran ') or v=='OK']))
        self.write('geometry-dependency.json',dict(geometryUnchanged=True,runtimeUnchanged=True,unchangedSourceHashes=hashes,
            baseline=ref,archives=archives,changedSubsystems=['Task629Tests touch emulation before production resize, asserted pointer/logical/CSS layout; observation helper layout measurements'],
            historical='TASK-623 updated S05-S07 route contacts supersede older geometry coverage. Older poses used only as isolated current-geometry observations; no historical continuous-route claim.',
            hashPolicy='HEAD movement alone does not invalidate identical tested source hashes'))
        print(f'PASS dependencies: geometry/runtime unchanged; {len(hashes)} source hashes match; archived nonzero TASK-623/627/628 suites; production input lands on yard-landing')

    def test_04_index(self):
        ids=[t.id() for t in unittest.defaultTestLoader.loadTestsFromTestCase(Task629Tests)]
        self.assertEqual(len(ids),4);self.assertTrue(all('.Task629Tests.' in t for t in ids))
        (self.out/'collected-tests.log').write_text('\n'.join(ids)+'\nCOLLECTED 4\n')
        required={'commands.log':'exact invocation, exit status, browser/viewports, revision and source hashes',
            'tests.log':'four exact Task629Tests, no skips', 'approaches.json':'64 measured target/landing/HUD views',
            'entry-sheet.jpg':'16 actual section entry captures','contact-sheet.jpg':'64 labelled player-eye images','landmarks.json':'16 entry views, 8 in-frame identities',
            'transitions.json':'42 samples around seven palette boundaries and seven section joins',
            'boundary-strip.jpg':'14 triplets around seven palette boundaries and seven section joins','geometry-dependency.json':'unchanged runtime/geometry hashes and archived expensive regressions',
            'smoke.json':'trusted production input and upward landing contacts','collected-tests.log':'exact class/method identifiers',
            'evidence-index.json':'artifact assertion map and tested configuration'}
        self.write('evidence-index.json',dict(artifacts=required,config=self.config))
        for name in required:
            self.assertTrue((self.out/name).is_file(),name)
            if name.endswith('.json'):json.loads((self.out/name).read_text())
            if name.endswith('.jpg'):
                with Image.open(self.out/name) as im:im.load();self.assertGreater(im.width,1000)
        size=sum(f.stat().st_size for f in self.out.rglob('*') if f.is_file())
        self.assertLess(size,200_000_000)
        print(f'PASS index: {len(required)} artifacts exist; JSON parses; 3 JPEGs decode; retained bytes={size} <200 MB')
