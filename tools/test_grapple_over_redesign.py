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
