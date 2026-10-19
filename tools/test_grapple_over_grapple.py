"""TASK-451: exercise real browser input and production swept hook collision."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from perf_mobile import SEED_SCRIPT


class Task451Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-451')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_grapple.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes, browser=cls.browser.version, viewport=VIEWPORT,
            device_scale_factor=1, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, mode='grapple_over'):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        # A run now opens paused; the first press would only resume it.
        page.evaluate("mode => {startGame(mode);menu.unPause();cancelAnimationFrame(game)}", mode)
        page.wait_for_function('!unTouch')
        page.evaluate('''() => {
            window.pressWorld=(x,y)=>{
                const p=canvasCoordsToViewportCoords({x:(x+screen.x)*scale[version],
                    y:(y+screen.y)*scale[version]});
                document.dispatchEvent(new MouseEvent('mousedown',{clientX:p.x,clientY:p.y}));
            };
            window.release=()=>document.dispatchEvent(new MouseEvent('mouseup'));
            window.prepare=c=>{
                release();
                for(const f of floors) f.elements=[];
                screen.leftWall=null;
                ninja.x=1000;ninja.y=1000;ninja.speedX=ninja.speedY=0;
                screen.x=-500;screen.y=-500;
                const angle=c.angle||0, ux=Math.cos(angle), uy=Math.sin(angle);
                window.fixtureTargets=(c.targets||[{distance:c.distance,id:'target'}]).map(t=>{
                    const e=new Rect({x:1000+ux*t.distance,y:1000+uy*t.distance-100,
                        width:0.1,height:200});
                    // Negative direction hits the right side of the rectangle.
                    if(ux<0) e.x-=0.1;
                    e.id=t.id;e.grapplable=t.grapplable!==false;
                    floors[0].elements.push(e);return e;
                });
                pressWorld(1000+Math.sign(ux)*100,1000+(Math.abs(uy)<1e-10?0:Math.sign(uy)*100));
                return {speed:Math.hypot(grapnel.speedX,grapnel.speedY),
                    vector:[grapnel.speedX,grapnel.speedY]};
            };
        }''')
        return page

    def run_case(self, page, name, expected, **config):
        initial = page.evaluate('prepare', config)
        row = page.evaluate('''c=>{
            const trace=[];
            // A held miss parks at the range edge instead of ending (TASK-534).
            for(let i=0;i<1000 && grapnel.throwed && !grapnel.grappled && !grapnel.isParked();i++){
                if(i===1){
                    ninja.x+=c.playerShift||0;
                    for(const t of fixtureTargets) t.x+=c.targetShift||0;
                    screen.x+=321;screen.y-=217;
                }
                if(c.follow) ninja.x+=grapnel.speedX;
                const before=grapnel.pos[0].slice(0,2);
                grapnel.move();
                const end=grapnel.pos[0].slice(0,2);
                grapnel.collision();
                trace.push({before,end,traveled:grapnel.traveled});
            }
            const last=trace.at(-1);
            const length=Math.hypot(last.end[0]-last.before[0],last.end[1]-last.before[1]);
            const prior=trace.length>1?trace.at(-2).traveled:0;
            const fraction=length?(grapnel.traveled-prior)/length:0;
            const contact=grapnel.grappled ? grapnel.pos[0].slice(0,2) : [last.before[0]+(last.end[0]-last.before[0])*fraction,
                last.before[1]+(last.end[1]-last.before[1])*fraction];
            const tip=grapnel.throwed?grapnel.pos[0].slice(0,2):null;
            return {attached:grapnel.grappled,active:grapnel.throwed,parked:grapnel.isParked(),
                clip:grapnel.clip&&[grapnel.clip.x,grapnel.clip.y],
                tip_distance:tip&&Math.hypot(tip[0]-ninja.x,tip[1]-ninja.y),
                target:grapnel.grappled?grapnel.pos[0][2].id:null,
                anchor:grapnel.grappled?grapnel.pos[0].slice(0,2):null,
                player:[ninja.x,ninja.y],contact,contact_distance:Math.hypot(contact[0]-ninja.x,contact[1]-ninja.y),
                traveled_distance:grapnel.traveled,steps:trace.length,last_step:last,
                stale:stalePress,finite:trace.every(t=>t.end.every(Number.isFinite))};
        }''', config)
        row.update(name=name, config=config, initial=initial, expected=expected)
        self.assertEqual(row['attached'], expected, name)
        self.assertTrue(row['finite'], name)
        self.assertGreater(row['steps'], 0)
        if page.evaluate('version') == 'grapple_over':
            self.assertLessEqual(row['traveled_distance'], 540+1e-8, name)
            if expected:
                self.assertLessEqual(row['contact_distance'], 540+1e-8, name)
                self.assertEqual(row['target'], config.get('expected_target','target'))
            else:
                # Held through a miss: the same shot stays out, parked on the
                # range circle and not stale, until its press is released.
                self.assertTrue(row['active'], name)
                self.assertTrue(row['parked'], name)
                self.assertFalse(row['stale'], name)
                self.assertAlmostEqual(row['traveled_distance'], 540, places=8, msg=name)
                self.assertAlmostEqual(row['tip_distance'], 540, places=8, msg=name)
                blockers = [t for t in config.get('targets', []) if t.get('grapplable') is False]
                if blockers:
                    # A blocker clips the held line where it crosses, never hooks.
                    self.assertIsNotNone(row['clip'], name)
                    self.assertAlmostEqual(row['clip'][0]-row['player'][0], blockers[0]['distance'],
                                           places=6, msg=name)
                row['released'] = page.evaluate('''()=>{release();
                    return {active:grapnel.throwed,stale:stalePress,attached:grapnel.grappled}}''')
                self.assertEqual(row['released'], dict(active=False, stale=False, attached=False), name)
        return row

    def test_range_occlusion_motion(self):
        page = self.open()
        rows=[]
        for angle in (0, math.pi/4, -math.pi/4, 3*math.pi/4):
            for distance in (539,540,541):
                rows.append(self.run_case(page,f'range_{distance}_angle_{angle}',distance<=540,
                                          distance=distance,angle=angle))
        for name,expected,config in (
            ('moving_player_away',False,dict(distance=530,playerShift=-20)),
            ('moving_player_toward',True,dict(distance=530,playerShift=100)),
            ('cumulative_even_when_player_follows',False,dict(distance=541,follow=True)),
            ('moving_target_into_range',True,dict(distance=550,targetShift=-20)),
            ('moving_target_out_of_range',False,dict(distance=530,targetShift=20)),
            ('thin_obstacle_inside_one_step',True,dict(distance=5)),
            ('nearest_reversed_order',True,dict(targets=[dict(distance=200,id='far'),
                dict(distance=100,id='near')],expected_target='near')),
            ('nearest_forward_order',True,dict(targets=[dict(distance=100,id='near'),
                dict(distance=200,id='far')],expected_target='near')),
            ('nongrapplable_blocker',False,dict(targets=[dict(distance=200,id='far'),
                dict(distance=100,id='blocker',grapplable=False)])),
            ('shared_edge_blocker_first',False,dict(targets=[dict(distance=100,id='blocker',grapplable=False),
                dict(distance=100,id='target')])),
            ('shared_edge_blocker_last',False,dict(targets=[dict(distance=100,id='target'),
                dict(distance=100,id='blocker',grapplable=False)]))):
            rows.append(self.run_case(page,name,expected,**config))
        self.assertLess(rows[17]['traveled_distance'], rows[17]['initial']['speed'])
        self.evidence.write('range.json',dict(self.proof,observations=rows))
        print(f'PASS range: {len(rows)} observed boundary, diagonal, moving player/target, thin obstacle, occlusion and blocker cases')

    def test_zero_aim_and_fresh_press(self):
        page = self.open()
        rows=[]
        for name,config in [('expired',dict(distance=541)),('blocked',dict(targets=[
                dict(distance=5,id='blocker',grapplable=False)])),('zero',dict(distance=100))]:
            if name=='zero':
                page.evaluate('prepare',config)
                page.evaluate('release();pressWorld(ninja.x,ninja.y)')
                state=page.evaluate('({active:grapnel.throwed,stale:stalePress,contact_distance:0,contact:[ninja.x,ninja.y],finite:Number.isFinite(grapnel.speedX)&&Number.isFinite(grapnel.speedY),traveled_distance:grapnel.traveled})')
            else:
                # Expired and blocked shots stay parked while held and end on
                # release (run_case); a fresh press after that starts a new shot.
                state=self.run_case(page,name,False,**config)
                self.assertTrue(state['finite'])
                self.assertEqual(state['released'],dict(active=False,stale=False,attached=False))
                retry=page.evaluate('''()=>{pressWorld(ninja.x+100,ninja.y);
                    return {after_release:grapnel.throwed,reset_travel:grapnel.traveled}}''')
                self.assertTrue(retry['after_release'])
                self.assertEqual(retry['reset_travel'],0)
                rows.append(dict(name=name,state=state,retry=retry))
                continue
            self.assertFalse(state['active'])
            self.assertTrue(state['stale'])
            self.assertTrue(state['finite'])
            retry=page.evaluate('''()=>{
                pressWorld(ninja.x+100,ninja.y);
                const withoutRelease=grapnel.throwed;
                release();pressWorld(ninja.x+100,ninja.y);
                return {without_release:withoutRelease,after_release:grapnel.throwed,
                    reset_travel:grapnel.traveled};
            }''')
            self.assertFalse(retry['without_release'])
            self.assertTrue(retry['after_release'])
            self.assertEqual(retry['reset_travel'],0)
            rows.append(dict(name=name,state=state,retry=retry))
        path=self.evidence.path('range.json')
        proof=json.loads(path.read_text()) if path.exists() else dict(self.proof)
        proof['input_observations']=rows
        self.evidence.write('range.json',proof)
        print('PASS zero-distance aim: finite and rejected, needs release and fresh press; expired/blocked shots stay parked while held, end on release, fresh press restarts')

    def test_legacy_range(self):
        rows=[]
        for mode in ('classic','bad'):
            page=self.open(mode)
            row=self.run_case(page,mode,True,distance=700)
            self.assertGreater(row['contact_distance'],540)
            row['mode']=mode
            # Legacy does not maintain the new shot counter; derive flight from
            # the recorded launch vector and the executed free-flight steps.
            row['traveled_distance']=row['steps']*row['initial']['speed']
            rows.append(row)
        self.evidence.write('legacy-range.json',dict(self.proof,observations=rows))
        print('PASS legacy: classic and bad attach beyond 540 world units')


class Task452Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-452')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_grapple.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes, browser=cls.browser.version, viewport=VIEWPORT)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))
        cls.rows = {}

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('attachment.json', dict(cls.proof, observations=cls.rows))

    def open(self, video=False):
        options = dict(viewport=VIEWPORT, device_scale_factor=1)
        if video:
            options.update(record_video_dir=str(self.evidence.path('video')),
                           record_video_size=VIEWPORT)
        context = self.browser.new_context(**options)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        # A run now opens paused; the first press would only resume it.
        page.evaluate("startGame('grapple_over');menu.unPause();cancelAnimationFrame(game)")
        page.wait_for_function('!unTouch')
        page.evaluate('''() => {
            for(const f of floors) f.elements=[];
            screen.leftWall=null;screen.x=-450;screen.y=-300;
            ninja.x=800;ninja.y=700;ninja.speedX=ninja.speedY=0;
            window.rect=(id,x,y,w,h)=>{
                const e=new Rect({x,y,width:w,height:h});e.id=id;e.surfaceRole='solid';
                floors[0].elements.push(e);return e;
            };
            window.snapshot=()=>({player:[ninja.x,ninja.y],velocity:[ninja.speedX,ninja.speedY],
                attached:grapnel.grappled,active:grapnel.throwed,
                rope:grapnel.pos.map(p=>({point:p.slice(0,2),id:p[2].id,
                    local:[p[0]-p[2].x,p[1]-p[2].y],element:[p[2].x,p[2].y]})),
                distance:grapnel.pos.length?Math.hypot(grapnel.pos[0][0]-ninja.x,grapnel.pos[0][1]-ninja.y):0});
            window.pullStep=()=>{
                const before=snapshot();calcPhysics();const after=snapshot();
                return {before,after,gravity:GRAVITY,pull:grappleSpeed};
            };
        }''')
        return page

    def press(self, page, x, y):
        point = page.evaluate('''([x,y])=>canvasCoordsToViewportCoords({
            x:(x+screen.x)*scale[version],y:(y+screen.y)*scale[version]})''',[x,y])
        page.mouse.move(point['x'],point['y'])
        page.mouse.down()

    def acquire(self, page, x=1100, y=700):
        self.press(page,x,y)
        page.evaluate('''()=>{for(let i=0;i<100 && !grapnel.grappled && grapnel.throwed;i++){
            grapnel.move();grapnel.collision();}}''')
        self.assertTrue(page.evaluate('grapnel.grappled'))

    def assert_pull(self, row):
        before, after = row['before'], row['after']
        anchor = after['rope'][-1]['point']
        dx,dy = [anchor[i]-after['player'][i] for i in range(2)]
        length = math.hypot(dx,dy)
        expected = [row['pull']*dx/length if length else 0,
                    row['gravity']+(row['pull']*dy/length if length else 0)]
        for i in range(2):
            self.assertAlmostEqual(after['velocity'][i]-before['velocity'][i],expected[i],places=9)
        self.assertTrue(after['attached'])
        return expected

    def test_long_moving_and_coincident(self):
        page = self.open()
        page.evaluate("""window.target=rect('moving-anchor',1100,680,30,40);
            floors[0].byId.set(target.id,target);
            floors[0].level.movers=[{id:'motion',element:target.id,axis:'y',
                min:680,max:780,periodMs:1000,phase:0}];""")
        self.acquire(page)
        initial=page.evaluate('snapshot()')
        page.evaluate('ninja.x=200;ninja.y=700')
        trace=[]
        for _ in range(12):
            row=page.evaluate('pullStep()')
            row['expected_acceleration']=self.assert_pull(row)
            self.assertGreater(row['after']['distance'],540)
            self.assertEqual(row['after']['rope'][0]['id'],'moving-anchor')
            for i in range(2):
                self.assertAlmostEqual(row['after']['rope'][0]['local'][i],initial['rope'][0]['local'][i],places=9)
            trace.append(row)
        self.assertNotEqual(trace[0]['after']['rope'][0]['point'],trace[-1]['after']['rope'][0]['point'])
        # An exact coincident direction must be finite and contribute no pull.
        coincident=page.evaluate('''()=>{
            ninja.x=grapnel.pos.at(-1)[0];ninja.y=grapnel.pos.at(-1)[1];
            return {state:snapshot(),direction:grapnel.calcSpeed({x:ninja.x,y:ninja.y})};}''')
        self.assertEqual(coincident['direction'],dict(sin=0,cos=0))
        before=page.evaluate('snapshot()');page.mouse.up();after=page.evaluate('snapshot()')
        self.assertEqual(before['velocity'],after['velocity'])
        self.assertFalse(after['attached'])
        self.rows['long_moving']=dict(initial=initial,trace=trace,coincident=coincident,release=dict(before=before,after=after))
        print('PASS long/moving: 12 attached steps beyond R; stable local anchor; acceleration and release velocity; coincident direction finite')

    def test_input_wrap_release(self):
        page=self.open(video=True)
        page.evaluate("rect('anchor',1100,680,30,40);rect('corner',900,800,80,50);draw()")
        page.wait_for_timeout(200)
        self.acquire(page)
        page.evaluate('ninja.speedY=3;draw()')
        trace=[]
        for i in range(200):
            row=page.evaluate('''()=>{const row=pullStep();draw();return row}''')
            trace.append(row)
            page.wait_for_timeout(16)
            if len(row['after']['rope'])>=2:
                break
        self.rows['wrap']=dict(trace=trace)
        self.assertGreaterEqual(len(trace[-1]['after']['rope']),2)
        anchor=trace[-1]['after']['rope'][-1]
        self.assertEqual(anchor['id'],'corner')
        self.assertIn(anchor['point'],[[900,800],[980,800],[980,850],[900,850]])
        row=page.evaluate('pullStep()');self.assert_pull(row)
        self.rows['wrap']['pull']=row
        page.evaluate('draw()');page.wait_for_timeout(400)
        before=page.evaluate('snapshot()');page.mouse.up();after=page.evaluate('snapshot()')
        self.assertEqual(before['velocity'],after['velocity'])
        self.assertFalse(after['attached']);self.assertFalse(after['active'])
        self.rows['wrap']['release']=dict(before=before,after=after,tolerance=1e-9)
        for _ in range(25):
            page.evaluate('calcPhysics();draw()');page.wait_for_timeout(16)
        page.context.close()
        page.video.save_as(str(self.evidence.path('wrapping.webm')))
        print('PASS input wrap/release: mouse press, physical motion, convex corner, last-corner acceleration, unchanged release velocity; wrapping.webm')

    def test_multiple_segments_beyond_range(self):
        page=self.open()
        page.evaluate("rect('anchor',1100,680,30,40)")
        self.acquire(page)
        initial=page.evaluate('snapshot()')
        page.evaluate("""rect('far-corner',900,800,80,50);
            rect('near-corner',600,952,40,80);
            rect('boundary',400,1000,20,100).grapplable=false;
            ninja.x=200;ninja.y=1160;grapnel.collision();""")
        wrapped=page.evaluate('snapshot()')
        self.rows['multi_segment']=dict(initial=initial,wrapped=wrapped)
        self.assertTrue(wrapped['attached'])
        self.assertGreater(wrapped['distance'],540)
        self.assertEqual([p['id'] for p in wrapped['rope']],['anchor','far-corner','near-corner'])
        self.assertEqual(wrapped['rope'][0],initial['rope'][0])
        self.assertEqual(wrapped['rope'][1]['point'],[900,800])
        self.assertEqual(wrapped['rope'][2]['point'],[600,952])
        trace=[]
        for _ in range(8):
            row=page.evaluate('pullStep()')
            self.assert_pull(row)
            self.assertEqual(len(row['after']['rope']),3)
            trace.append(row)
        self.rows['multi_segment']['trace']=trace
        print('PASS multi-segment: original anchor preserved; wrapping contact beyond R; three stable anchors; boundary does not reacquire/detach; last-corner pull')


class Task534Tests(unittest.TestCase):
    """A held miss parks at the active radius and follows trusted mouse/touch aim."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-534')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_grapple.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes, browser=cls.browser.version, viewport=VIEWPORT,
            device_scale_factor=1, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))
        cls.held = {}

    @classmethod
    def tearDownClass(cls):
        if cls.held:
            cls.evidence.write('held.json', dict(cls.proof, **cls.held))

    def open(self, touch):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate("startGame('grapple_over');menu.unPause();cancelAnimationFrame(game);"
                      "window.requestAnimationFrame=()=>0")
        page.wait_for_function('!unTouch')
        page.evaluate('''() => {
            // No anchor anywhere: every shot is a miss.
            for(const f of floors) f.elements=[];
            floors[0].level.movers=[];
            screen.leftWall=null;
            ninja.x=1000;ninja.y=-2000;ninja.speedX=2;ninja.speedY=0;
            screen.trackGrappleOver(true);
            window.events=[];
            // Record what the game will see for each trusted move (capture phase).
            for(const type of ['mousemove','touchmove']) document.addEventListener(type,e=>{
                const c=e.changedTouches?e.changedTouches[0]:e;
                const p=viewportCoordsToCanvasCoords({x:c.clientX,y:c.clientY});
                const w={x:p.x/scale[version]-screen.x,y:p.y/scale[version]-screen.y};
                events.push({type,trusted:e.isTrusted,client:[c.clientX,c.clientY],world:[w.x,w.y],
                    ninja:[ninja.x,ninja.y],angle:Math.atan2(w.y-ninja.y,w.x-ninja.x),
                    zero:w.x===ninja.x&&w.y===ninja.y});
            },true);
            window.radius=MODE_DEFINITIONS.grapple_over.acquisitionRadius;
            // Distance from a point to the nearest edge of an element, this tick.
            window.edgeDistance=(p,e)=>Math.min(...e.getLines().map(l=>{
                const dx=l.x2-l.x1,dy=l.y2-l.y1;
                const t=Math.max(0,Math.min(1,((p[0]-l.x1)*dx+(p[1]-l.y1)*dy)/(dx*dx+dy*dy)));
                return Math.hypot(p[0]-l.x1-t*dx,p[1]-l.y1-t*dy)}));
            window.tickRow=()=>{
                physics();
                const tip=grapnel.throwed?grapnel.pos[0].slice(0,2):null;
                const hook=grapnel.grappled?grapnel.pos[0]:null;
                return {tick:floors[0].elapsedSteps,ninja:[ninja.x,ninja.y],throwed:grapnel.throwed,
                    grappled:grapnel.grappled,parked:grapnel.isParked(),traveled:grapnel.traveled,tip,
                    distance:tip?Math.hypot(tip[0]-ninja.x,tip[1]-ninja.y):null,
                    tip_angle:tip?Math.atan2(tip[1]-ninja.y,tip[0]-ninja.x):null,
                    aim_angle:grapnel.aim?Math.atan2(grapnel.aim.y,grapnel.aim.x):null,
                    stale:stalePress,held:pressHeld,owned:gameplayPressOwned};
            };
            window.client=(x,y)=>{const p=canvasCoordsToViewportCoords({x:(x+screen.x)*scale[version],
                y:(y+screen.y)*scale[version]});return [Math.round(p.x),Math.round(p.y)]};
        }''')
        return page

    def client_at(self, page, angle, reach=300):
        return page.evaluate('a=>client(ninja.x+Math.cos(a[0])*a[1],ninja.y+Math.sin(a[0])*a[1])',
                             [angle, reach])

    def angle_error(self, a, b):
        return abs((a - b + math.pi) % (2 * math.pi) - math.pi)

    def assert_parked(self, row, radius):
        self.assertTrue(row['throwed'])
        self.assertFalse(row['grappled'])
        self.assertTrue(row['parked'])
        self.assertLessEqual(abs(row['distance'] - radius), 1e-6, row)

    def run_held(self, touch):
        page = self.open(touch)
        radius = page.evaluate('radius')
        self.assertEqual(radius, 540)
        if touch:
            cdp = page.context.new_cdp_session(page)
            def down(p): cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart',
                                  'touchPoints': [dict(x=p[0], y=p[1], id=1)]})
            def move(p): cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove',
                                  'touchPoints': [dict(x=p[0], y=p[1], id=1)]})
            def up(): cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        else:
            def down(p): page.mouse.move(*p); page.mouse.down()
            def move(p): page.mouse.move(*p)
            def up(): page.mouse.up()
        down(self.client_at(page, 0.3))
        flight = []
        for _ in range(300):
            row = page.evaluate('tickRow()')
            flight.append(row)
            if row['parked']:
                break
        self.assertTrue(flight[-1]['parked'], 'shot never parked')
        self.assertTrue(all(r['throwed'] and not r['grappled'] for r in flight))
        parked_tick = flight[-1]['tick']
        # Hold with no aim change: ninja keeps moving, tip stays at the radius.
        held = [flight[-1]] + [page.evaluate('tickRow()') for _ in range(10)]
        for row in held:
            self.assert_parked(row, radius)
            self.assertLessEqual(self.angle_error(row['tip_angle'], held[0]['aim_angle']), 1e-6)
        self.assertGreater(math.dist(held[0]['ninja'], held[-1]['ninja']), 1)
        sweep = []
        for target in [0.3 + i * math.pi / 6 for i in range(1, 13)]:
            page.evaluate('events.length=0')
            move(self.client_at(page, target))
            events = page.evaluate('events')
            self.assertEqual(len(events), 1, events)
            event = events[0]
            self.assertTrue(event['trusted'])
            self.assertEqual(event['type'], 'touchmove' if touch else 'mousemove')
            row = page.evaluate('tickRow()')
            self.assert_parked(row, radius)
            row.update(target_angle=target, event=event,
                       aim_error=self.angle_error(row['aim_angle'], event['angle']),
                       tip_error=self.angle_error(row['tip_angle'], event['angle']))
            self.assertLessEqual(row['aim_error'], 1e-6)
            self.assertLessEqual(row['tip_error'], 1e-6)
            self.assertLessEqual(self.angle_error(event['angle'], target), 0.01)
            sweep.append(row)
        self.assertGreater(math.dist(sweep[0]['ninja'], sweep[-1]['ninja']), 1)
        # Zero-length aim: the pointer lands exactly on the ninja; keep the last direction.
        before = page.evaluate('Math.atan2(grapnel.aim.y,grapnel.aim.x)')
        point = self.client_at(page, -2.0)
        page.evaluate('''p=>{const c=viewportCoordsToCanvasCoords({x:p[0],y:p[1]});
            ninja.x=c.x/scale[version]-screen.x;ninja.y=c.y/scale[version]-screen.y}''', point)
        page.evaluate('events.length=0')
        move(point)
        zero_event = page.evaluate('events')[0]
        self.assertTrue(zero_event['zero'] and zero_event['trusted'])
        zero_row = page.evaluate('tickRow()')
        self.assert_parked(zero_row, radius)
        self.assertLessEqual(self.angle_error(zero_row['aim_angle'], before), 1e-12)
        self.assertLessEqual(self.angle_error(zero_row['tip_angle'], before), 1e-6)
        if not touch:
            # The first-run hint would cover the parked line in the proof image.
            page.evaluate('TUTORIAL_HINT.visible=false;draw()')
            page.screenshot(path=str(self.evidence.path('held.png')))
        up()
        released = page.evaluate('tickRow()')
        self.assertFalse(released['throwed'])
        self.assertIsNone(released['tip'])
        retry = page.evaluate('({stale:stalePress,held:pressHeld,owned:gameplayPressOwned})')
        self.assertEqual(retry, dict(stale=False, held=False, owned=False))
        distances = [r['distance'] for r in held + sweep + [zero_row]]
        result = dict(input='touch (CDP Input.dispatchTouchEvent)' if touch else 'mouse (page.mouse)',
                      radius=radius, parked_tick=parked_tick, flight=flight, held=held, sweep=sweep,
                      zero_aim=dict(previous_angle=before, event=zero_event, row=zero_row),
                      released=released, input_after_release=retry,
                      max_radius_error=max(abs(d - radius) for d in distances),
                      max_angle_error=max(max(r['tip_error'], r['aim_error']) for r in sweep),
                      ninja_travel_while_held=math.dist(held[0]['ninja'], sweep[-1]['ninja']))
        self.held['touch' if touch else 'mouse'] = result
        return result

    def test_01_mouse_held_parks_and_follows(self):
        r = self.run_held(False)
        print(f"PASS mouse: parked at tick {r['parked_tick']}, {len(r['held'])+len(r['sweep'])+1} held ticks "
              f"at R={r['radius']} (max err {r['max_radius_error']:.2e}), 12-step sweep max angle err "
              f"{r['max_angle_error']:.2e} rad, ninja moved {r['ninja_travel_while_held']:.1f}, tip absent after release")

    def test_02_touch_held_parks_and_follows(self):
        r = self.run_held(True)
        print(f"PASS touch: parked at tick {r['parked_tick']}, {len(r['held'])+len(r['sweep'])+1} held ticks "
              f"at R={r['radius']} (max err {r['max_radius_error']:.2e}), 12-step sweep max angle err "
              f"{r['max_angle_error']:.2e} rad, ninja moved {r['ninja_travel_while_held']:.1f}, tip absent after release")

    def test_03_classic_bad_baseline(self):
        from grapple_over_test_support import STATE, open_fixture, step
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())
        modes = {}
        for mode in ('classic', 'bad'):
            page, errors = open_fixture(self.browser, self.url, mode, self.addCleanup)
            initial = page.evaluate(STATE)
            trace = step(page, 12)
            self.assertEqual(initial, baseline['modes'][mode]['initial'])
            self.assertEqual(trace, baseline['modes'][mode]['movement_trace'])
            self.assertEqual(errors, [])
            modes[mode] = dict(initial=initial, movement_trace=trace, initial_equal=True, trace_equal=True)
        self.evidence.write('baseline.json', dict(self.proof, baseline_path='artifacts/TASK-444/baseline.json',
                                                  modes=modes))
        print('PASS classic/bad: initial state and 12-step seeded traces equal TASK-444 baseline')


# Revision before TASK-535: the pre-change reference for ordinary shots and pulls.
TASK535_PRE_CHANGE = '40a8f2be021a3dd86cca89c7a13ee888b2ed5084'


class Task535Tests(unittest.TestCase):
    """Any part of the held line acquires; blockers clip it; ordinary shots are unchanged."""

    @classmethod
    def setUpClass(cls):
        from functools import partial
        from http.server import ThreadingHTTPServer
        import io
        import tarfile
        import tempfile
        from threading import Thread
        from browser_test_support import QuietHandler
        cls.evidence = EvidenceWriter('TASK-535')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        # A temporary checkout of the pre-change tree, served the same way.
        old = tempfile.TemporaryDirectory(prefix='task535-pre-')
        cls.addClassCleanup(old.cleanup)
        archive = subprocess.run(['git', 'archive', TASK535_PRE_CHANGE], cwd=ROOT,
                                 check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(old.name, filter='data')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=old.name))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.old_url = f'http://127.0.0.1:{server.server_port}/'
        hashes = source_hashes()
        name = 'tools/test_grapple_over_grapple.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            pre_change_revision=TASK535_PRE_CHANGE,
            source_hashes=hashes, browser=cls.browser.version, viewport=VIEWPORT,
            device_scale_factor=1, seed=1, input='trusted page.mouse')
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))
        cls.sweep = {}

    @classmethod
    def tearDownClass(cls):
        if cls.sweep:
            cls.evidence.write('sweep.json', dict(cls.proof, scenarios=cls.sweep))

    def open(self, url):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(url)
        wait_for_boot(page)
        page.evaluate("startGame('grapple_over');menu.unPause();cancelAnimationFrame(game);"
                      "window.requestAnimationFrame=()=>0;TUTORIAL_HINT.visible=false")
        page.wait_for_function('!unTouch')
        page.evaluate('''() => {
            for(const f of floors) f.elements=[];
            floors[0].level.movers=[];floors[0].byId=new Map();
            screen.leftWall=null;
            window.radius=MODE_DEFINITIONS.grapple_over.acquisitionRadius;
            window.place=(x,y)=>{ninja.x=x;ninja.y=y;ninja.speedX=ninja.speedY=0;screen.trackGrappleOver(true)};
            window.rect=(id,x,y,w,h,extra)=>{
                const e=new Rect({x,y,width:w,height:h});e.id=id;e.surfaceRole='solid';e.dx=e.dy=0;
                Object.assign(e,extra||{});floors[0].elements.push(e);floors[0].byId.set(id,e);return e;
            };
            window.client=(x,y)=>{const p=canvasCoordsToViewportCoords({x:(x+screen.x)*scale[version],
                y:(y+screen.y)*scale[version]});return [p.x,p.y]};
            window.clientAt=(a,r)=>client(ninja.x+Math.cos(a)*r,ninja.y+Math.sin(a)*r);
            window.events=[];
            for(const type of ['mousedown','mousemove']) document.addEventListener(type,
                e=>events.push({type,trusted:e.isTrusted}),true);
            // Distance from a point to the nearest edge of an element, this tick.
            window.edgeDistance=(p,e)=>Math.min(...e.getLines().map(l=>{
                const dx=l.x2-l.x1,dy=l.y2-l.y1;
                const t=Math.max(0,Math.min(1,((p[0]-l.x1)*dx+(p[1]-l.y1)*dy)/(dx*dx+dy*dy)));
                return Math.hypot(p[0]-l.x1-t*dx,p[1]-l.y1-t*dy)}));
            window.tickRow=()=>{
                physics();
                const tip=grapnel.throwed?grapnel.pos[0].slice(0,2):null;
                const hook=grapnel.grappled?grapnel.pos[0]:null;
                return {tick:floors[0].elapsedSteps,ninja:[ninja.x,ninja.y],velocity:[ninja.speedX,ninja.speedY],
                    throwed:grapnel.throwed,grappled:grapnel.grappled,
                    parked:typeof grapnel.isParked==='function'?grapnel.isParked():null,
                    tip,clip:grapnel.clip?[grapnel.clip.x,grapnel.clip.y]:null,
                    rope:grapnel.throwed?grapnel.pos.map(p=>({point:p.slice(0,2),id:p[2].id||null,
                        local:p[2].id?[p[0]-p[2].x,p[1]-p[2].y]:null})):[],
                    tip_distance:tip?Math.hypot(tip[0]-ninja.x,tip[1]-ninja.y):null,
                    anchor_edge_distance:hook?edgeDistance(hook,hook[2]):null};
            };
        }''')
        return page

    def press(self, page, point):
        page.mouse.move(*point)
        page.mouse.down()

    def park(self, page, angle):
        """Throw into an empty world along angle and tick until the held miss parks."""
        page.evaluate('place(1000,-2000)')
        self.press(page, page.evaluate('a=>clientAt(a,300)', angle))
        flight = []
        for _ in range(300):
            row = page.evaluate('tickRow()')
            flight.append(row)
            if row['parked']:
                break
        self.assertTrue(flight[-1]['parked'], 'never parked')
        self.assertTrue(all(r['throwed'] and not r['grappled'] for r in flight))
        return flight

    def ticks(self, page, count, until_attached=True, since=None):
        rows = []
        for _ in range(count):
            rows.append(page.evaluate('tickRow()'))
            if since is not None:
                rows[-1]['since_press'] = rows[-1]['tick'] - since
            if until_attached and rows[-1]['grappled']:
                break
        return rows

    def assert_attached(self, page, rows, element_id):
        last = rows[-1]
        self.assertTrue(last['grappled'], f'{element_id}: never attached')
        self.assertEqual(last['rope'][0]['id'], element_id)
        anchor = last['rope'][0]['point']
        self.assertLessEqual(last['anchor_edge_distance'], 1e-9)
        # The contact lies on the held line from the ninja and inside the radius.
        self.assertLessEqual(math.dist(anchor, last['ninja']), 540 + 1e-9)
        return anchor

    def trusted(self, page):
        events = page.evaluate('events')
        self.assertTrue(events and all(e['trusted'] for e in events), events)
        return dict(count=len(events), types=sorted({e['type'] for e in events}), all_trusted=True)

    def scenario_fall(self, url):
        page = self.open(url)
        flight = self.park(page, 0)
        # A grapplable ledge just below the parked line; the ninja falls past it.
        ledge = page.evaluate('''()=>{const e=rect('ledge',ninja.x+200,ninja.y+60,100,40);
            return {x:e.x,y:e.y,width:e.width,height:e.height}}''')
        rows = self.ticks(page, 200)
        return page, dict(ledge=ledge, flight_ticks=len(flight), parked=flight[-1], trace=rows,
                          input=self.trusted(page))

    def scenario_mover(self, url):
        page = self.open(url)
        flight = self.park(page, 0)
        # A tall blue bar, beyond the tip, moving left into the parked line.
        mover = page.evaluate('''()=>{
            const e=rect('mover',0,ninja.y-400,30,1600,{fill:STYLE.colors.cube.blueFill,
                stroke:STYLE.colors.cube.blueStroke});
            const min=ninja.x+150,max=ninja.x+radius+150,periodMs=4000;
            const now=floors[0].elapsedSteps*physicsStepMs/cyclesPerTick;
            // Start at max (phase .5) and move toward min.
            const phase=((0.5-now/periodMs)%1+1)%1;
            floors[0].level.movers=[{id:'motion',element:'mover',axis:'x',min,max,periodMs,phase}];
            floors[0].applyMovers(now);e.dx=e.dy=0;
            return {min,max,periodMs,start_x:e.x}}''')
        rows = self.ticks(page, 400)
        after = self.ticks(page, 20, until_attached=False) if rows[-1]['grappled'] else []
        return page, dict(mover=mover, flight_ticks=len(flight), trace=rows, after_attach=after,
                          input=self.trusted(page))

    def scenario_sweep(self, url):
        page = self.open(url)
        flight = self.park(page, 0.6)
        anchor = page.evaluate('''()=>{const a=-0.6,r=350;
            const e=rect('anchor',ninja.x+Math.cos(a)*r-20,ninja.y+Math.sin(a)*r-20,40,40);
            return {x:e.x,y:e.y,width:40,height:40}}''')
        rows = []
        for i in range(1, 41):
            angle = 0.6 - 0.05 * i
            page.mouse.move(*page.evaluate('a=>clientAt(a,300)', angle))
            row = page.evaluate('tickRow()')
            row['aim_angle'] = angle
            rows.append(row)
            if row['grappled']:
                break
        return page, dict(anchor=anchor, flight_ticks=len(flight), trace=rows, input=self.trusted(page))

    def scenario_blocked(self, url):
        page = self.open(url)
        flight = self.park(page, 0)
        setup = page.evaluate('''()=>{
            const wall=rect('wall',ninja.x+200,ninja.y-800,20,1600,{grapplable:false});
            const hazard=rect('hazard',ninja.x+300,ninja.y-800,20,1600,{surfaceRole:'hazard',
                fill:STYLE.colors.hazard.fill,stroke:STYLE.colors.hazard.stroke});
            const anchor=rect('anchor',ninja.x+420,ninja.y-800,30,1600);
            return {wall_x:wall.x,hazard_x:hazard.x,anchor_x:anchor.x}}''')
        rows = self.ticks(page, 30)
        # Remove the wall: the hazard alone still clips and never attaches.
        page.evaluate("floors[0].elements=floors[0].elements.filter(e=>e.id!=='wall')")
        hazard_rows = self.ticks(page, 30)
        # Restore a wall for the proof image: the line ends at the wall, short of the anchor.
        page.evaluate("rect('wall2',ninja.x+200,ninja.y-800,20,1600,{grapplable:false})")
        clipped_png = None
        if url == self.url:
            page.evaluate('tickRow();draw()')
            clipped_png = str(self.evidence.path('clipped.png').relative_to(ROOT))
            page.screenshot(path=clipped_png)
        return page, dict(setup=setup, flight_ticks=len(flight), trace=rows, hazard_trace=hazard_rows,
                          screenshot=clipped_png, input=self.trusted(page))

    def scenario_ordinary(self, url):
        page = self.open(url)
        page.evaluate("place(600,700);rect('target',1100,500,30,400)")
        # Boot timing varies the absolute step count between page loads.
        since = page.evaluate('floors[0].elapsedSteps')
        self.press(page, page.evaluate('client(1100,700)'))
        rows = self.ticks(page, 200, since=since)
        return page, dict(trace=rows, input=self.trusted(page))

    def both(self, scenario):
        page, new = scenario(self.url)
        old_page, old = scenario(self.old_url)
        return page, new, old

    def test_01_fall_past_ledge(self):
        page, new, old = self.both(self.scenario_fall)
        anchor = self.assert_attached(page, new['trace'], 'ledge')
        self.assertTrue(new['trace'][0]['parked'] and not new['trace'][0]['grappled'])
        self.assertFalse(old['trace'][-1]['grappled'])
        self.sweep['a_fall_past_ledge'] = dict(expected='attached to ledge', anchor=anchor,
                                              attach_tick=new['trace'][-1]['tick'], new=new,
                                              pre_change=dict(attached=False, trace=old['trace'][-5:]))
        print(f"PASS (a) fall past ledge: parked line attached to ledge at {anchor} after "
              f"{len(new['trace'])} ticks; pre-change never attached in {len(old['trace'])} ticks")

    def test_02_mover_into_parked_line(self):
        page, new, old = self.both(self.scenario_mover)
        anchor = self.assert_attached(page, new['trace'], 'mover')
        self.assertTrue(all(not r['grappled'] for r in new['trace'][:-1]))
        local = new['trace'][-1]['rope'][0]['local']
        after = new['after_attach']
        self.assertTrue(all(r['grappled'] and r['rope'][0]['id'] == 'mover' for r in after))
        for r in after:
            for i in range(2):
                self.assertAlmostEqual(r['rope'][0]['local'][i], local[i], places=9)
        moved = abs(after[-1]['rope'][0]['point'][0] - anchor[0])
        self.assertGreater(moved, 1)
        self.assertFalse(old['trace'][-1]['grappled'])
        self.sweep['b_mover_into_parked_line'] = dict(expected='attached to mover; anchor tracks it',
            anchor=anchor, anchor_local=local, anchor_moved_x=moved, new=new,
            pre_change=dict(attached=False, trace=old['trace'][-5:]))
        print(f"PASS (b) blue mover: attached at {anchor}; anchor tracked mover {moved:.1f} over "
              f"{len(after)} ticks with constant local offset; pre-change never attached")

    def test_03_aim_sweep_across_anchor(self):
        page, new, old = self.both(self.scenario_sweep)
        anchor = self.assert_attached(page, new['trace'], 'anchor')
        self.assertGreater(len(new['trace']), 1)
        self.assertFalse(old['trace'][-1]['grappled'])
        self.sweep['c_aim_sweep_across_anchor'] = dict(expected='attached at crossing', anchor=anchor,
            attach_aim_angle=new['trace'][-1]['aim_angle'], new=new,
            pre_change=dict(attached=False, trace=old['trace'][-5:]))
        print(f"PASS (c) aim sweep: attached to anchor at {anchor} on sweep step {len(new['trace'])} "
              f"(aim {new['trace'][-1]['aim_angle']:.2f} rad); pre-change never attached")

    def test_04_blocker_clips_line(self):
        page, new, old = self.both(self.scenario_blocked)
        setup = new['setup']
        for rows, x in ((new['trace'], setup['wall_x']), (new['hazard_trace'], setup['hazard_x'])):
            self.assertEqual(len(rows), 30)
            for r in rows:
                self.assertTrue(r['throwed'] and r['parked'] and not r['grappled'], r)
                self.assertIsNotNone(r['clip'], r)
                self.assertAlmostEqual(r['clip'][0], x, places=6)
                self.assertAlmostEqual(r['clip'][1], r['ninja'][1], places=6)
        self.assertTrue((ROOT / new['screenshot']).exists())
        self.sweep['d_blocker_clips_line'] = dict(expected='clipped at blocker, never attached',
            never_attached=True, ticks=60, new=new,
            pre_change=dict(attached=old['trace'][-1]['grappled'], trace=old['trace'][-5:]))
        print(f"PASS (d) blocker: 30 ticks clipped at nongrapplable wall x={setup['wall_x']:.1f} and 30 at "
              f"hazard x={setup['hazard_x']:.1f}; never attached to anchor; clipped.png")

    def test_05_ordinary_shot_unchanged(self):
        page, new, old = self.both(self.scenario_ordinary)
        anchor = self.assert_attached(page, new['trace'], 'target')
        self.assertTrue(old['trace'][-1]['grappled'])
        self.assertEqual(new['trace'][-1]['since_press'], old['trace'][-1]['since_press'])
        self.assertEqual(len(new['trace']), len(old['trace']))
        self.assertEqual(new['trace'][-1]['rope'], old['trace'][-1]['rope'])
        strip = lambda rows: [{k: v for k, v in r.items() if k not in ('parked', 'clip', 'tick')} for r in rows]
        self.assertEqual(strip(new['trace']), strip(old['trace']))
        self.sweep['e_ordinary_shot_unchanged'] = dict(expected='same tick and contact as pre-change',
            attach_ticks_since_press=new['trace'][-1]['since_press'],
            pre_change_attach_ticks_since_press=old['trace'][-1]['since_press'], contact=anchor, old_contact=old['trace'][-1]['rope'][0]['point'],
            same_tick=True, same_contact=True, traces_equal=True, new=new, pre_change=old)
        print(f"PASS (e) ordinary shot: attached {new['trace'][-1]['since_press']} physics steps after the press at {anchor}, "
              f"identical to pre-change {TASK535_PRE_CHANGE[:7]} (tick and contact; {len(new['trace'])}-tick traces equal)")

    def pull_trace(self, url):
        page = self.open(url)
        page.evaluate("place(800,700);rect('anchor',1100,680,30,40);rect('corner',900,800,80,50)")
        since = page.evaluate('floors[0].elapsedSteps')
        self.press(page, page.evaluate('client(1100,700)'))
        acquire = self.ticks(page, 100, since=since)
        self.assertTrue(acquire[-1]['grappled'])
        page.evaluate('ninja.speedY=3')
        trace = self.ticks(page, 150, until_attached=False, since=since)
        return acquire, trace

    def test_06_pull_and_wrap_unchanged(self):
        acquire, trace = self.pull_trace(self.url)
        old_acquire, old_trace = self.pull_trace(self.old_url)
        self.assertEqual(acquire[-1]['rope'], old_acquire[-1]['rope'])
        self.assertEqual(acquire[-1]['since_press'], old_acquire[-1]['since_press'])
        strip = lambda rows: [{k: v for k, v in r.items() if k not in ('parked', 'clip', 'tick')} for r in rows]
        self.assertEqual(strip(trace), strip(old_trace))
        wrapped = [r for r in trace if len(r['rope']) >= 2]
        self.assertTrue(wrapped, 'no corner wrap')
        self.assertEqual(wrapped[0]['rope'][-1]['id'], 'corner')
        self.assertTrue(all(r['grappled'] for r in trace))
        self.evidence.write('pull.json', dict(self.proof, anchor='anchor', corner='corner',
            attach=dict(new=acquire[-1], pre_change=old_acquire[-1], equal=True),
            first_wrap_ticks_since_press=wrapped[0]['since_press'],
            comparison='rows equal except absolute tick (boot-dependent); since_press compared', wrapped_ticks=len(wrapped), ticks=len(trace),
            traces_equal=True, new=trace, pre_change=old_trace))
        print(f"PASS pull/wrap: {len(trace)} post-attachment ticks equal pre-change; wrap onto corner "
              f"{wrapped[0]['since_press']} physics steps after the press ({len(wrapped)} wrapped ticks)")


# Last revision before the held grapnel (TASK-534/535).
TASK536_PRE_HELD = '15b55b5a08cc9070c675379febc5ae19355cdb51'
TASK536_FAMILIES = ('launch', 'release', 'braking', 'angled_bounce', 'corner_wrap', 'moving_transfer')


def task536_scan(unit):
    """Presses in one recorded proof that stay held after their shot ended.

    The pre-held runtime ended a shot that missed (range or blocker) and marked
    the still-held press stale; a held grapnel now stays out and can acquire.
    """
    import math
    import os
    task, label, files = unit
    inputs, acquisitions, stale = None, set(), set()
    has_events = False

    def walk(value, tick):
        nonlocal inputs, has_events
        if isinstance(value, dict):
            if isinstance(value.get('events'), list) and any(
                    isinstance(e, dict) and 'type' in e for e in value['events']):
                has_events = True
            if isinstance(value.get('tick'), int):
                tick = value['tick']
            if value.get('type') == 'acquisition' and tick is not None:
                acquisitions.add(tick)
            state = value.get('input')
            if isinstance(state, dict) and state.get('pressHeld') and state.get('stalePress') and tick is not None:
                stale.add(tick)
            found = value.get('inputs')
            if inputs is None and isinstance(found, list) and found and isinstance(found[0], dict) \
                    and 'tick' in found[0] and 'event' in found[0]:
                inputs = found
            for item in value.values():
                walk(item, tick)
        elif isinstance(value, list):
            for item in value:
                walk(item, tick)

    files = list(files)
    for name in files:
        with open(name) as stream:
            data = json.load(stream)
        # A summary may name its full trace file instead of embedding it.
        linked = data.get('trace') if isinstance(data, dict) else None
        if isinstance(linked, str) and linked.endswith('.json'):
            path = os.path.join(os.path.dirname(name), linked)
            if os.path.exists(path) and path not in files:
                files.append(path)
        walk(data, None)
    rows = []
    if not inputs:
        return dict(task=task, proof=label, files=files, inputs=0, presses=0, has_events=has_events, held_misses=rows)
    if not has_events:
        # Without a recorded event log a missing acquisition proves nothing.
        return dict(task=task, proof=label, files=files, inputs=len(inputs), presses=None,
                    has_events=False, held_misses=rows)
    flight = math.ceil(540 / 216)  # ticks for a full-range throw: 27 units x 8 substeps
    last = max([i['tick'] for i in inputs] + list(stale) + list(acquisitions) + [0])
    presses = 0
    for index, item in enumerate(inputs):
        if item['event'] not in ('mousedown', 'touchstart'):
            continue
        presses += 1
        up = next((i['tick'] for i in inputs[index + 1:] if i['event'] in ('mouseup', 'touchend', 'touchcancel')), last)
        acquired = sorted(t for t in acquisitions if item['tick'] <= t <= up)
        stale_ticks = sorted(t for t in stale if item['tick'] < t <= up)
        if stale_ticks or (not acquired and up - item['tick'] >= flight):
            rows.append(dict(input_index=index, event=item['event'], press_tick=item['tick'], release_tick=up,
                             held_ticks=up - item['tick'], acquired_ticks=acquired,
                             stale_held_ticks=len(stale_ticks), first_stale_tick=stale_ticks[0] if stale_ticks else None,
                             world=item.get('world')))
    return dict(task=task, proof=label, files=files, inputs=len(inputs), presses=presses,
                has_events=True, held_misses=rows)


class Task536Tests(unittest.TestCase):
    """Calibration families and v1 encounter proofs under the held grapnel."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-536')
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_grapple.py', 'tools/test_grapple_over_visuals.py',
                     'tools/test_grapple_over_tools.py', 'tools/grapple_over_calibration.js'):
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            pre_held_revision=TASK536_PRE_HELD, source_hashes=hashes, viewport=VIEWPORT,
            device_scale_factor=1, seed=1, range=540)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def calibrate(self, root, out):
        """Run the TASK-463 calibration suite against the tree at root."""
        import os
        import sys
        command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tools',
                   '-p', 'test_grapple_over_tools.py', '-k', 'Task463Tests', '-v']
        run = subprocess.run(command, cwd=root, env=dict(os.environ, GRAPPLE_OVER_EVIDENCE_DIR=str(out)),
                             capture_output=True, text=True)
        return run, ' '.join(command)

    def test_01_calibration_families(self):
        import shutil
        import tempfile
        current_dir = self.evidence.path('calibration-run/current')
        run, command = self.calibrate(ROOT, current_dir)
        self.evidence.path('calibration-run/current.log').write_text(run.stdout + run.stderr)
        self.evidence.log(f'COMMAND (cwd=worktree) GRAPPLE_OVER_EVIDENCE_DIR={current_dir} {command}\nEXIT {run.returncode}')
        self.assertEqual(run.returncode, 0, run.stderr[-3000:])
        self.assertIn('Ran 2 tests', run.stderr)
        # The same suite on the last tree before the held grapnel attributes any change.
        with tempfile.TemporaryDirectory(prefix='task536-pre-') as parent:
            # A detached worktree: the suite hashes `git ls-files` and records HEAD.
            old = Path(parent) / 'tree'
            subprocess.run(['git', 'worktree', 'add', '--detach', str(old), TASK536_PRE_HELD],
                           cwd=ROOT, check=True, capture_output=True)
            self.addCleanup(subprocess.run, ['git', 'worktree', 'prune'], cwd=ROOT, capture_output=True)
            baseline = Path(old) / 'artifacts/TASK-444/baseline.json'
            baseline.parent.mkdir(parents=True)
            shutil.copy(ROOT / 'artifacts/TASK-444/baseline.json', baseline)
            pre_out = Path(old) / 'artifacts/TASK-536-pre'
            pre, _ = self.calibrate(old, pre_out)
            pre_calibration = self.evidence.path('calibration-run/pre-held/calibration.json')
            if (pre_out / 'calibration.json').exists():
                shutil.copy(pre_out / 'calibration.json', pre_calibration)
        self.evidence.path('calibration-run/pre-held.log').write_text(pre.stdout + pre.stderr)
        self.evidence.log(f'COMMAND (cwd=git worktree {TASK536_PRE_HELD}) {command}\nEXIT {pre.returncode}')
        self.assertEqual(pre.returncode, 0, pre.stderr[-3000:])
        current = json.loads((current_dir / 'calibration.json').read_text())
        previous = json.loads((ROOT / 'artifacts/TASK-463/calibration.json').read_text())
        held_before = json.loads(pre_calibration.read_text())
        self.assertTrue(current['all_six_families_pass'])
        self.assertEqual(current['constants']['range'], 540)

        def outline(run):
            return dict(dt=run['dt'], aim=run['aim'], negative=run['negative'], success=run['success'],
                        exit=run['rows'][100], landing_tick=run.get('landing_contact', {}).get('tick'),
                        # Grapnel events only: the recorder has since added bounce events.
                        grapnel_events=[(e['type'], e['tick']) for e in run['events']
                                        if e['type'] in ('acquisition', 'release', 'wrap')])

        families = {}
        for family in TASK536_FAMILIES:
            now, then, pre_runs = (d['families'][family] for d in (current, previous, held_before))
            self.assertEqual(len(now), 6)
            envelope, before = current['measured_envelopes'][family], previous['measured_envelopes'][family]
            variants = []
            for a, b, c in zip(now, then, pre_runs):
                x, y, z = outline(a), outline(b), outline(c)
                if x != y:
                    variants.append(dict(dt=x['dt'], aim=x['aim'], negative=x['negative'],
                                         current=x, task463=y, pre_held=z, same_as_pre_held=x == z))
            unchanged = envelope == before
            self.assertEqual(unchanged, not variants, family)
            families[family] = dict(
                status='unchanged' if unchanged else 'changed',
                envelopes=dict(current=envelope, task463=before,
                               pre_held=held_before['measured_envelopes'][family]),
                landing_ticks=dict(current=envelope['landing_ticks'], task463=before['landing_ticks']),
                changed_variants=variants,
                # A difference that is absent from the pre-held tree comes from the held grapnel.
                caused_by_held_grapnel=any(not v['same_as_pre_held'] for v in variants),
                successes=sum(r['success'] for r in now), negative_rejected=not now[-1]['success'])
            print('CALIBRATION', family, families[family]['status'], 'landing_ticks',
                  envelope['landing_ticks'], 'task463', before['landing_ticks'],
                  'changed_variants', [(v['dt'], v['aim'], v['negative']) for v in variants])
        self.evidence.write('calibration.json', dict(
            self.proof, baseline='artifacts/TASK-463/calibration.json',
            calibration_source_hashes=current['source_hashes'],
            task463_source_hashes=previous['source_hashes'],
            pre_held_source_hashes=held_before['source_hashes'],
            families=families, all_six_families_pass=current['all_six_families_pass']))
        print('PASS calibration: six families rerun; ' + ', '.join(
            f"{k} {v['status']}" for k, v in families.items()))

    def test_02_v1_encounter_proofs(self):
        from concurrent.futures import ProcessPoolExecutor
        artifacts = ROOT / 'artifacts'
        units = []
        for number in range(465, 491):
            task = artifacts / f'TASK-{number}'
            # A recorded attempt directory keeps its inputs and its trace apart;
            # its replay/ and result files repeat the same run.
            runs = sorted({p.parent for d in ('encounters', 'attempts') for p in (task / d).rglob('input.json')})
            for run in runs:
                files = [str(run / n) for n in ('input.json', 'trace.json') if (run / n).exists()]
                units.append((task.name, str(run.relative_to(ROOT)) + '/', files))
            for name in sorted((task / 'encounters').rglob('*.json')):
                if not any(name.is_relative_to(run) for run in runs):
                    units.append((task.name, str(name.relative_to(ROOT)), [str(name)]))
            for proof, extra in (('trace.json', 'inputs.json'), ('recovery.json', 'recovery-inputs.json')):
                if (task / proof).exists():
                    files = [str(task / proof)] + ([str(task / extra)] if (task / extra).exists() else [])
                    units.append((task.name, str((task / proof).relative_to(ROOT)), files))
        with ProcessPoolExecutor(8) as pool:
            scanned = list(pool.map(task536_scan, units))
        with_inputs = [s for s in scanned if s['inputs'] and s['has_events']]
        no_log = [s['proof'] for s in scanned if s['inputs'] and not s['has_events']]
        affected = [s for s in scanned if s['held_misses']]
        tasks = sorted({s['task'] for s in scanned})
        self.assertEqual(len(tasks), 26, tasks)
        self.assertGreater(len(with_inputs), 100)
        self.assertEqual(no_log, [])
        self.evidence.write('held-misses.json', dict(
            self.proof, criterion='press with no acquisition while held for >= 3 ticks (full-range flight), '
            'or a recorded snapshot with pressHeld && stalePress during the press',
            proofs_scanned=len(scanned), proofs_with_inputs=len(with_inputs), affected=affected,
            unaffected=[s['proof'] for s in with_inputs if not s['held_misses']],
            inputs_without_event_log=no_log,
            no_inputs=[s['proof'] for s in scanned if not s['inputs']]))
        lines = ['# TASK-536: v1 encounter proofs that hold through a miss', '',
                 f'Revision {self.proof["revision"]}. Scanned {len(scanned)} recorded proofs from '
                 f'TASK-465..TASK-490 ({len(with_inputs)} with input lists): every recorded run directory '
                 '(`input.json` + `trace.json` under `encounters/` or `attempts/`), every other `encounters/**/*.json`, '
                 'and the TASK-489/490 `trace.json`/`recovery.json` runs.', '',
                 'A press counts as held through a miss when it stays held for at least 3 ticks (a full 540-unit '
                 'flight) without an acquisition, or when a recorded snapshot shows `pressHeld && stalePress` during it. '
                 'The pre-held runtime ended such a shot. The held grapnel now keeps it parked and able to acquire '
                 '(TASK-534/535), so these recorded inputs depend on the old behaviour. This is a report and handoff '
                 'to the layout-v2 rebuild and legacy re-spec tickets; those proofs are not re-run here.', '',
                 f'Affected proofs: {len(affected)} across {len({s["task"] for s in affected})} tasks. '
                 f'Proofs with inputs but no event log (not judged): {no_log or "none"}.', '',
                 '| Task | Proof | Input index | Event | Press tick | Release tick | Held ticks | Acquired while held | Stale held snapshots |',
                 '|---|---|---|---|---|---|---|---|---|']
        for s in affected:
            for r in s['held_misses']:
                lines.append(f"| {s['task']} | `{s['proof']}` | {r['input_index']} | {r['event']} | {r['press_tick']} | "
                             f"{r['release_tick']} | {r['held_ticks']} | {r['acquired_ticks'] or 'none'} | {r['stale_held_ticks']} |")
        lines += ['', '## Per task', '']
        for task in tasks:
            mine = [s for s in scanned if s['task'] == task]
            hit = [s for s in mine if s['held_misses']]
            lines.append(f"- {task}: {len(hit)} of {len([s for s in mine if s['inputs']])} proofs with inputs affected")
        self.evidence.path('changed-behaviour.md').write_text('\n'.join(lines) + '\n')
        print(f'PASS encounter audit: {len(scanned)} proofs scanned, {len(with_inputs)} with inputs, '
              f'{len(affected)} hold through a miss across {len({s["task"] for s in affected})} tasks')


# TASK-543 browser helpers. placeInS04Column() is a labeled test placement in
# S04; the S05 entry itself is physical (physics() carries the ninja upward).
TASK543_HELPERS = '''() => {
    window.bandOf=id=>floors[0].level.sections.find(s=>s.id===id).band;
    window.placeAt=(x,y)=>{ninja.x=x;ninja.y=y;ninja.speedX=ninja.speedY=0;
        grapnel.endShot();pressHeld=stalePress=gameplayPressOwned=false;
        if(ninja.track)ninja.track.pos.length=0;screen.trackGrappleOver(true)};
    // Radius argument actually passed to ctx.arc by the range circle.
    window.drawnRadius=()=>{const radii=[],arc=ctx.arc,circle=drawAcquisitionCircle;
        window.drawAcquisitionCircle=()=>{ctx.arc=function(x,y,radius,...rest){radii.push(radius);return arc.call(this,x,y,radius,...rest)};
            try{circle()}finally{ctx.arc=arc}};
        try{draw()}finally{window.drawAcquisitionCircle=circle}
        if(radii.length!==1)throw Error('range circle arcs: '+radii.length);return radii[0]};
    // TASK-529: the range is earned in S05's rangeUpgradeZone (the top of the S04-04
    // exit box, i.e. landing on the S04 exit ledge), not anywhere in the S05 band.
    window.upgradeZone=()=>floors[0].level.sections.find(s=>s.id==='S05').rangeUpgradeZone;
    // TEST-ONLY PLACEMENT: at rest 120 above the zone middle, inside S04-exit-drag with a
    // clear column down to the ledge, so the drop enters the zone physically.
    window.placeAboveUpgradeZone=()=>{const z=upgradeZone(),x=(z.left+z.right)/2,y=z.top-120;
        if(grapnel.nearestCrossing({x,y},[x,z.top]))throw Error('column above the zone is not clear');
        placeAt(x,y);return {x,y,label:'TEST-ONLY placement above the S05 range-upgrade zone'}};
    // TEST-ONLY PLACEMENT: a point 200 below the S05 band bottom whose column up
    // to 200 inside S05 is clear, so an upward launch enters S05 physically.
    window.placeInS04Column=()=>{const b=bandOf('S05'),y=b.bottom+200,mid=(b.left+b.right)/2;
        for(let d=0;d<mid-b.left-100;d+=40) for(const x of [mid-d,mid+d])
            if(![-60,0,60].some(dx=>grapnel.nearestCrossing({x:x+dx,y:y+60},[x+dx,b.bottom-200])))
                {placeAt(x,y);return {x,y,label:'TEST-ONLY placement in S04'}}
        throw Error('no clear S04 column')};
    // Screen box (CSS px) of the drawn range circle, from the same transform draw() uses.
    window.circleBox=()=>{const r=grappleOverAcquisitionRadius(),k=scale[version];
        const pts=[[r,0],[-r,0],[0,r],[0,-r]].map(([dx,dy])=>canvasCoordsToViewportCoords(
            {x:(ninja.x+dx+screen.x)*k,y:(ninja.y+dy+screen.y)*k}));
        const c=getCanvasCssRect(),box={left:Math.min(...pts.map(p=>p.x)),right:Math.max(...pts.map(p=>p.x)),
            top:Math.min(...pts.map(p=>p.y)),bottom:Math.max(...pts.map(p=>p.y))};
        const view={left:0,top:0,right:innerWidth,bottom:innerHeight};
        const canvas={left:c.left,top:c.top,right:c.left+c.width,bottom:c.top+c.height};
        const inside=o=>box.left>=o.left&&box.top>=o.top&&box.right<=o.right&&box.bottom<=o.bottom;
        return {radius:r,cameraScale:k,box,viewport:view,canvas,insideViewport:inside(view),insideCanvas:inside(canvas),
            margins:{left:box.left-canvas.left,top:box.top-canvas.top,right:canvas.right-box.right,bottom:canvas.bottom-box.bottom}}};
}'''


class Task543Tests(unittest.TestCase):
    """Doubled grapnel range (1080/1620) and the 0.375 Grapple Over camera that fits it."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-543')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_grapple.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes, browser=cls.browser.version, device_scale_factor=1)
        cls.evidence.log('CONFIG ' + json.dumps(dict(cls.proof, viewports=dict(
            desktop=dict(width=1280, height=720, touch=False, lang='en'),
            touch=dict(width=844, height=390, touch=True, lang='ru'))), sort_keys=True))
        cls.fit = {}

    @classmethod
    def tearDownClass(cls):
        if cls.fit:
            cls.evidence.write('fit.json', dict(cls.proof, **cls.fit))

    def open(self, width, height, touch, lang='en'):
        context = self.browser.new_context(viewport=dict(width=width, height=height),
                                           device_scale_factor=1, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.wait_for_function('runInProgress && !menu.gamePaused')
        page.evaluate("lang=>{setLanguage(lang);cancelAnimationFrame(game);window.requestAnimationFrame=()=>0}", lang)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        page.evaluate(TASK543_HELPERS)
        return page

    def test_01_range_and_camera_scales(self):
        page = self.open(1280, 720, False)
        modes = page.evaluate('''()=>({definitions:JSON.parse(JSON.stringify(MODE_DEFINITIONS)),
            scale:{...scale},manifestRange:GRAPPLE_OVER_MOUNTAIN.range,levelUpgradeBand:MODE_DEFINITIONS.grapple_over.rangeUpgradeSection})''')
        go = modes['definitions']['grapple_over']
        self.assertEqual((go['acquisitionRadius'], go['upgradedAcquisitionRadius'], go['rangeUpgradeSection']),
                         (1080, 1620, 'S05'))
        self.assertEqual(modes['manifestRange'], dict(base=1080, upgraded=1620, upgradeBand='S05'))
        self.assertEqual(modes['scale'], dict(classic=1, bad=1 / 2.2, grapple_over=0.375))
        self.assertEqual(modes['definitions']['classic'], dict(cameraScale=1, hudStyle='classic'))
        self.assertEqual(modes['definitions']['bad'], dict(cameraScale=1 / 2.2, hudStyle='bad'))
        # TASK-529: the S05 band no longer grants the range (the v3 S03/S04 routes climb through it); S05's
        # rangeUpgradeZone does, on landing on the S04 exit ledge (the S05-01 start).
        before = page.evaluate('''()=>{const s=placeAboveUpgradeZone(),z=upgradeZone();return {placement:s,zone:z,
            upgraded:floors[0].rangeUpgraded,radius:grappleOverAcquisitionRadius(),drawn:drawnRadius(),inZone:ninja.y>=z.top}}''')
        self.assertFalse(before['upgraded'] or before['inZone'])
        self.assertEqual((before['radius'], before['drawn']), (1080, 1080))
        # Physical entry: a drop from rest onto the S04 exit ledge; physics() decides the flip.
        entry = page.evaluate('''()=>{const z=upgradeZone();const rows=[];
            for(let n=0;n<600&&!floors[0].rangeUpgraded;n++){const y0=ninja.y;physics();
                if(n%10===0||floors[0].rangeUpgraded)rows.push({tick:floors[0].elapsedSteps,y_before:y0,y:ninja.y,
                    vy:ninja.speedY,upgraded:floors[0].rangeUpgraded,radius:grappleOverAcquisitionRadius()})}
            return {zoneTop:z.top,samples:rows,last:rows[rows.length-1],drawn:drawnRadius(),
                noticeMs:floors[0].rangeNoticeMs,saved:captureClimbState().upgrades}}''')
        last = entry['last']
        self.assertTrue(last['upgraded'], entry)
        self.assertLess(last['y_before'], entry['zoneTop'])
        self.assertGreaterEqual(last['y'], entry['zoneTop'])
        self.assertEqual((last['radius'], entry['drawn']), (1620, 1620))
        self.assertEqual(entry['saved'], dict(range=True))
        # Classic/bad: unchanged initial state and seeded movement vs the TASK-444 baseline.
        from grapple_over_test_support import STATE, open_fixture, step
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())
        legacy = {}
        for mode in ('classic', 'bad'):
            fixture, errors = open_fixture(self.browser, self.url, mode, self.addCleanup)
            initial = fixture.evaluate(STATE)
            trace = step(fixture, 12)
            self.assertEqual(initial, baseline['modes'][mode]['initial'])
            self.assertEqual(trace, baseline['modes'][mode]['movement_trace'])
            self.assertEqual(errors, [])
            legacy[mode] = dict(cameraScale=modes['scale'][mode], definition=modes['definitions'][mode],
                                range=None, baseline_initial_equal=True, baseline_trace_equal=True)
        self.evidence.write('range.json', dict(self.proof, viewport=dict(width=1280, height=720),
            grapple_over=dict(cameraScale=modes['scale']['grapple_over'], definition=go,
                              manifest_range=modes['manifestRange']),
            before_s05=before, s05_entry=dict(kind='physical drop onto the S04 exit ledge from a TEST-ONLY placement above the S05 range-upgrade zone',
                                              zone_top=entry['zoneTop'], flip=last, samples=entry['samples'],
                                              drawn_radius=entry['drawn'], notice_ms=entry['noticeMs'],
                                              saved_upgrades=entry['saved']),
            classic_bad=dict(legacy, baseline_path='artifacts/TASK-444/baseline.json'),
            pass_=True))
        print(f"PASS range: 1080 before S05 (drawn {before['drawn']}), physical S05 entry at tick {last['tick']} "
              f"-> 1620 (drawn {entry['drawn']}); scales {modes['scale']}; classic/bad equal TASK-444 baseline")

    def fit_case(self, key, width, height, touch, lang, png):
        page = self.open(width, height, touch, lang)
        # A mid-climb spot (S03 band centre) away from the world-edge camera clamps.
        spot = page.evaluate('''()=>{const b=bandOf('S03');TUTORIAL_HINT.visible=false;
            placeAt((b.left+b.right)/2,(b.top+b.bottom)/2);
            physics();screen.trackGrappleOver(true);draw();return {x:ninja.x,y:ninja.y,height:floors[0].climbStats.currentHeight}}''')
        fit = page.evaluate('circleBox()')
        self.assertEqual(fit['radius'], 1080)
        self.assertEqual(fit['cameraScale'], 0.375)
        self.assertTrue(fit['insideViewport'] and fit['insideCanvas'], fit)
        # Worst ordinary-tracking case: the ninja at the 0.4/0.6 vertical and 0.35/0.65
        # horizontal camera edges (world units of the visible area).
        worst = page.evaluate('''()=>{const k=scale[version],w=width/k,h=height/k,r=grappleOverAcquisitionRadius();
            return {view_world:[w,h],top:0.4*h-r,bottom:h-0.6*h-r,left:0.35*w-r,right:w-0.65*w-r}}''')
        self.assertTrue(all(worst[s] >= 0 for s in ('top', 'bottom', 'left', 'right')), worst)
        hud = page.evaluate('''()=>{LAYOUT_PROBE.boxes=[];draw();const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;
            return b.filter(x=>x.kind==='text').map(x=>({text:x.name,x:x.x,y:x.y,width:x.width,fontPx:x.fontPx}))}''')
        self.assertGreaterEqual(len(hud), 4)
        for b in hud:
            self.assertGreaterEqual(b['fontPx'], 12 - 1e-6)
            self.assertGreaterEqual(b['x'], 0)
            self.assertLessEqual(b['x'] + b['width'], width)
        if lang == 'ru':
            self.assertTrue(any(any('Ѐ' <= ch <= 'ӿ' for ch in b['text']) for b in hud), hud)
        # The upgraded circle at the same spot, recorded for the TASK-544 handoff.
        upgraded = page.evaluate('()=>{floors[0].rangeUpgraded=true;const f=circleBox();floors[0].rangeUpgraded=false;draw();return f}')
        page.screenshot(path=str(self.evidence.path(png)))
        self.fit[key] = dict(viewport=dict(width=width, height=height), touch=touch, lang=lang, spot=spot,
                             screenshot=png, base_circle=fit, tracking_worst_case_world_margins=worst,
                             hud_text=hud, upgraded_circle_1620_info=upgraded)
        return fit

    def test_02_fit_desktop(self):
        f = self.fit_case('desktop', 1280, 720, False, 'en', 'range-desktop.png')
        print(f"PASS desktop 1280x720: R=1080 circle box {f['box']} inside canvas (margins {f['margins']})")

    def test_03_fit_touch_ru(self):
        f = self.fit_case('touch', 844, 390, True, 'ru', 'range-touch-ru.png')
        print(f"PASS touch 844x390 ru: R=1080 circle box {f['box']} inside canvas (margins {f['margins']})")

    def test_04_manifest_check(self):
        page = self.open(1280, 720, False)
        rows = page.evaluate('''()=>{const run=range=>{const m=structuredClone(GRAPPLE_OVER_MOUNTAIN);m.range=range;
                try{validateMountainManifest(m);return {range,accepted:true}}catch(e){return {range,accepted:false,error:e.message}}};
            const v2=layoutV2Report(GRAPPLE_OVER_MOUNTAIN).sections?.filter?.(s=>!s.legacy)
                ?? layoutV2Report(GRAPPLE_OVER_MOUNTAIN);
            return {live:GRAPPLE_OVER_MOUNTAIN.range,
                cases:[run({base:1080,upgraded:1620,upgradeBand:'S05'}),run({base:540,upgraded:810,upgradeBand:'S05'})],
                v2:Array.isArray(v2)?v2.map(s=>({id:s.id,passed:s.passed,gap:s.rules?.gapBand?.measured?.target})):v2}}''')
        new, old = rows['cases']
        self.assertTrue(new['accepted'], new)
        self.assertFalse(old['accepted'])
        self.assertTrue(old['error'].startswith('InvalidRange: '), old)
        self.assertTrue(all(s['passed'] for s in rows['v2']), rows['v2'])
        lines = [f"revision {self.proof['revision']}",
                 f"live GRAPPLE_OVER_MOUNTAIN.range {json.dumps(rows['live'], sort_keys=True)}",
                 f"validateMountainManifest range={json.dumps(new['range'], sort_keys=True)} -> ACCEPTED",
                 f"validateMountainManifest range={json.dumps(old['range'], sort_keys=True)} -> REJECTED {old['error']}",
                 'layoutV2Report v2 sections (gap bands stay at the 540/810 design range): ' +
                 json.dumps(rows['v2'], separators=(',', ':')),
                 'PASS manifest-check']
        self.evidence.path('manifest-check.log').write_text('\n'.join(lines) + '\n')
        print(f"PASS manifest: {{1080,1620,'S05'}} accepted; {{540,810,'S05'}} -> {old['error']}")
