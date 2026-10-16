"""TASK-451: exercise real browser input and production swept hook collision."""
import hashlib
import json
import math
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
        page.evaluate("mode => {startGame(mode);cancelAnimationFrame(game)}", mode)
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
            for(let i=0;i<1000 && grapnel.throwed && !grapnel.grappled;i++){
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
            return {attached:grapnel.grappled,active:grapnel.throwed,
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
                self.assertFalse(row['active'], name)
                self.assertTrue(row['stale'], name)
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
                state=self.run_case(page,name,False,**config)
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
        print('PASS zero-distance aim: finite and rejected; expired/blocked/zero shots require release and fresh press')

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
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
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
