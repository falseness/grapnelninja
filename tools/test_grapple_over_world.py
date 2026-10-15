"""TASK-446 runtime proof for authored, persistent fixture loading."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, STATE, source_hashes, step
from perf_mobile import SEED_SCRIPT

GEOMETRY = '''world => world.elements.map(e => ({id:e.id, role:e.surfaceRole,
    x:e.x,y:e.y,points:e.points}))'''


class Task446Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter(getattr(cls, 'TASK', 'TASK-446'))
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('fixedlevel.js', 'tools/test_grapple_over_world.py', 'tools/test_left_wall.py'):
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=ROOT, text=True).strip(), 'source_hashes': hashes,
            'browser': cls.browser.version,
            'viewports': [[1280, 720]] if getattr(cls, 'TASK', None) == 'TASK-448' else [[1280, 720], [960, 720]],
            'device_scale_factor': 1, 'seed': 1}
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, width=1280, mode='grapple_over'):
        context = self.browser.new_context(viewport={'width': width, 'height': 720},
                                           device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate(SEED_SCRIPT % 1)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def test_repeated_loads_validation_and_movers(self):
        observations = []
        for width in (1280, 960):
            page = self.open(width)
            for repeat in range(2):
                rows = page.evaluate('() => (' + GEOMETRY + ')(loadFixedLevel())')
                observations.append(dict(viewport=[width, 720], repeat=repeat, geometry=rows))
        self.assertEqual([e['id'] for e in rows], ['base', 'right-step', 'left-step', 'top-step',
                                                     'left-bound', 'right-bound', 'catch-floor'])
        for observation in observations:
            self.assertEqual(observation['geometry'], observations[0]['geometry'])
        errors = page.evaluate('''() => {
            const cases = {
                duplicate: d => d.elements[1].id = d.elements[0].id,
                nonfinite: d => d.elements[0].x = Infinity,
                polygon: d => d.elements[0].points = [{x:0,y:0},{x:1,y:1}],
                crossed: d => d.elements[0].points = [{x:0,y:0},{x:3,y:3},{x:0,y:3},{x:3,y:0}],
                repeated: d => d.elements[0].points[1] = d.elements[0].points[0],
                mover: d => d.movers = [{id:'move',element:'base',axis:'x',min:200,max:100,periodMs:1000,phase:0}],
                moverOutside: d => d.movers = [{id:'move',element:'base',axis:'x',min:100,max:1800,periodMs:1000,phase:0}],
                reference: d => d.encounters[0].elements.push('absent'),
                section: d => d.sections[0].encounters.push('absent'),
                moverReference: d => d.movers = [{id:'move',element:'absent'}],
                bounds: d => d.bounds.right = d.bounds.left,
                spawn: d => d.spawn.y = NaN,
                finish: d => d.finish = {left:0,right:1,top:0,bottom:NaN},
                role: d => d.elements[0].role = 'lethal',
                version: d => d.version = 2
            };
            return Object.entries(cases).map(([name, mutate]) => {
                const d = structuredClone(GRAPPLE_OVER_LEVEL); mutate(d);
                try {loadFixedLevel(d); return {name,error:null}}
                catch (e) {return {name,error:e.message}}
            });
        }''')
        expected = ['DuplicateId', 'NonFiniteGeometry', 'MalformedPolygon', 'MalformedPolygon',
                    'MalformedPolygon', 'InvalidMoverBounds', 'InvalidMoverBounds', 'MissingReference',
                    'MissingReference', 'MissingReference', 'InvalidBounds', 'NonFiniteGeometry',
                    'NonFiniteGeometry', 'InvalidSurfaceRole', 'UnsupportedVersion']
        for row, name in zip(errors, expected):
            self.assertTrue(row['error'].startswith(name + ':'), row)
        movers = page.evaluate('''() => {
            const d = structuredClone(GRAPPLE_OVER_LEVEL);
            d.movers = [{id:'move',element:'right-step',axis:'x',min:600,max:700,periodMs:1000,phase:0}];
            const a = loadFixedLevel(d), b = loadFixedLevel(d);
            d.elements[1].points[0].x = 99;
            const rows = [];
            for (let i=0;i<960;i++) {
                a.moveElements(); b.moveElements();
                if ([239,479,719,959].includes(i)) rows.push({step:i+1,
                    x:a.byId.get('right-step').x, otherX:b.byId.get('right-step').x,
                    dx:a.byId.get('right-step').dx});
            }
            return {rows, isolated:a.elements[1].points[0].x === 0};
        }''')
        self.assertTrue(movers['isolated'])
        for row, x in zip(movers['rows'], (700, 600, 700, 600)):
            self.assertAlmostEqual(row['x'], x)
            self.assertEqual(row['x'], row['otherX'])
        self.evidence.write('loader.json', dict(self.proof, observations=observations,
            identical_geometry_ids=True, invalid_fixtures=errors, movers=movers,
            camera_travel_proof='world-trace.json'))
        print('PASS loader: 4 repeated loads at 2 viewports; identical geometry/IDs; 15 named validation errors; deterministic movers')

    def test_camera_travel_preserves_world(self):
        page = self.open()
        trace = page.evaluate('''() => {
            let proceduralCalls = 0;
            const originals = [];
            for (const [proto, names] of [[Floor.prototype,['generateElements','generatePrimaryElements','replenishElements']],
                                         [ElementsFactory.prototype,['create']]])
                for (const name of names) {
                    originals.push([proto,name,proto[name]]);
                    proto[name] = function() {proceduralCalls++; throw new Error('Procedural spawning: '+name)};
                }
            try {
                startGame('grapple_over'); cancelAnimationFrame(game);
                const world = floors[0], elements = world.elements, refs = elements.slice();
                const geometry = () => elements.map(e => ({id:e.id,x:e.x,y:e.y,points:e.points}));
                const before = geometry(), rows = [];
                for (const [direction,x,y] of [['origin',0,0],['forward',-10000,0],
                    ['backward',10000,0],['up',0,10000],['down',0,-10000],['return',0,0]]) {
                    screen.x=x; screen.y=y;
                    physics(); draw();
                    world.deleteElements(); world.replenishElements();
                    world.generatePrimaryElements(); world.generateElements();
                    rows.push({direction,camera:[screen.x,screen.y],count:world.elements.length,
                        sameGroup:floors[0]===world, sameArray:world.elements===elements,
                        sameObjects:refs.every((e,i)=>world.elements[i]===e),geometry:geometry()});
                }
                return {before,rows,proceduralCalls};
            } finally {for (const [proto,name,fn] of originals) proto[name]=fn}
        }''')
        self.assertEqual(trace['proceduralCalls'], 0)
        for row in trace['rows']:
            self.assertEqual(row['count'], 7)
            self.assertTrue(row['sameGroup'] and row['sameArray'] and row['sameObjects'])
            self.assertEqual(row['geometry'], trace['before'])
        self.evidence.write('world-trace.json', dict(self.proof, **trace,
            constant_terrain_identity_count=True, no_procedural_spawning=True))
        print('PASS travel: forward/backward/up/down/return; count=7; same objects and geometry; proceduralCalls=0')

    def test_classic_bad_baseline(self):
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())
        for mode in ('classic', 'bad'):
            page = self.open(mode=mode)
            self.assertEqual(page.evaluate(STATE), baseline['modes'][mode]['initial'])
            self.assertEqual(step(page, 12), baseline['modes'][mode]['movement_trace'])
        print('PASS classic/bad: initial state and 12-step traces equal TASK-444 baseline')


class Task448Tests(unittest.TestCase):
    TASK = 'TASK-448'
    setUpClass = classmethod(Task446Tests.setUpClass.__func__)
    open = Task446Tests.open

    def test_fixed_boundaries_camera_backtracking_and_landings(self):
        page = self.open()
        observed = page.evaluate('''() => {
            const world = floors[0], player = ninja, refs = world.elements.slice();
            const geometry = () => world.elements.map(e => ({id:e.id,x:e.x,y:e.y}));
            const initial = geometry(), camera = [], sides = [], landings = [];
            // A real hook into the base; moving only the camera must not move it.
            ninja.x=360; ninja.y=1000; ninja.speedX=ninja.speedY=0;
            grapnel.throwed=true; grapnel.pos=[[360,1110,new Empty()]];
            grapnel.collision();
            const anchorBefore=grapnel.pos.map(p=>[p[0],p[1],p[2].id]);
            for (let i=0;i<12;i++) {
                screen.speedX=i%2 ? 20000 : -20000;
                screen.speedY=i%2 ? -8000 : 8000;
                screen.move(); grapnel.move(); grapnel.collision(); draw();
                world.deleteElements(); world.replenishElements();
                camera.push({camera:[screen.x,screen.y],wall:screen.leftWall,
                    anchor:grapnel.pos.map(p=>[p[0],p[1],p[2].id]), geometry:geometry(),
                    sameObjects:refs.every((e,j)=>e===world.elements[j])});
            }
            grapnel.throwed=grapnel.grappled=false; grapnel.pos=[];
            // Camera deletion border now lies far ahead of the player.
            screen.x=-20000;
            for (const [id,x,vx] of [['left-bound',-950,-500],['right-bound',1950,500]]) {
                ninja.x=x; ninja.y=0; ninja.speedX=vx; ninja.speedY=0;
                ninja.move();
                sides.push({id,x:ninja.x,y:ninja.y,radius:ninja.radius,vx:ninja.speedX,
                    samePlayer:ninja===player, frozen:isRunFrozen()});
            }
            for (const x of [-800,0,1500,1900]) {
                ninja.x=x; ninja.y=1500; ninja.speedX=0; ninja.speedY=30;
                for(let i=0;i<240;i++) physics();
                landings.push({startX:x,x:ninja.x,y:ninja.y,radius:ninja.radius,vy:ninja.speedY,
                    samePlayer:ninja===player,sameWorld:floors[0]===world,frozen:isRunFrozen(),
                    sameObjects:refs.every((e,j)=>e===world.elements[j])});
            }
            // No wall appears, even after production physics and drawing.
            draw();
            return {initial,anchorBefore,camera,sides,landings,wall:screen.leftWall,
                finalGeometry:geometry()};
        }''')
        self.assertEqual(observed['anchorBefore'], [[360, 1100, 'base']])
        self.assertIsNone(observed['wall'])
        for row in observed['camera']:
            self.assertIsNone(row['wall'])
            self.assertEqual(row['anchor'], observed['anchorBefore'])
            self.assertEqual(row['geometry'], observed['initial'])
            self.assertTrue(row['sameObjects'])
        for row in observed['sides']:
            self.assertTrue(row['samePlayer'])
            self.assertFalse(row['frozen'])
            self.assertGreaterEqual(row['x']-row['radius'], -1000-1e-6)
            self.assertLessEqual(row['x']+row['radius'], 2000+1e-6)
            self.assertEqual(row['vx'], 0)
        for row in observed['landings']:
            self.assertTrue(row['samePlayer'] and row['sameWorld'] and row['sameObjects'])
            self.assertFalse(row['frozen'])
            self.assertAlmostEqual(row['y']+row['radius'], 2000, places=5)
            self.assertEqual(row['vy'], 0)
        self.assertEqual(observed['finalGeometry'], observed['initial'])
        shots = page.evaluate('''() => {
            const world=floors[0], rows=[];
            for(const [id,x,y,tx,ty] of [
                ['left-bound',-900,0,-1200,0],['right-bound',1900,0,2200,0],
                ['catch-floor',1500,1900,1500,2200]]) {
                ninja.x=x; ninja.y=y;
                grapnel.throwed=true; grapnel.grappled=false;
                grapnel.pos=[[tx,ty,new Empty()]];
                grapnel.collision();
                rows.push({id,throwed:grapnel.throwed,attached:grapnel.isGrappled(),count:grapnel.pos.length});
            }
            // Place a legitimate target behind a blocker, first in iteration order.
            const target=new Trampoline({x:-1250,y:-50,points:[{x:0,y:0},{x:40,y:0},{x:40,y:100},{x:0,y:100}]});
            target.id='occluded-target'; world.elements.unshift(target);
            ninja.x=-900; ninja.y=0; grapnel.throwed=true; grapnel.grappled=false;
            grapnel.pos=[[-1300,0,new Empty()]]; grapnel.collision();
            rows.push({id:'occluded-target',throwed:grapnel.throwed,attached:grapnel.isGrappled(),count:grapnel.pos.length});
            world.elements.shift();
            return rows;
        }''')
        for shot in shots:
            self.assertFalse(shot['throwed'] or shot['attached'])
            self.assertEqual(shot['count'], 0)
        self.evidence.write('boundaries.json', dict(self.proof, observations=observed, shots=shots,
            camera_cannot_create_or_move_anchor=True, side_bounds_contain_without_attachment=True,
            bottom_landings_without_restart=True, backtracking_retains_terrain_ids=True,
            nongrapplable_blocks_shot=True))
        print('PASS boundaries: 12 camera/backtracking moves; 2 side impacts; 4 bottom landings; 4 blocked shots; no restart')

    def test_legacy_wall_and_deletion_death(self):
        from test_left_wall import PROBE
        rows = []
        for mode in ('classic', 'bad'):
            page = self.open(mode=mode)
            row = page.evaluate(PROBE)
            for contact in row['contacts']:
                for key in ('alive', 'nonpenetration', 'rightward', 'noRepeatedReflection'):
                    self.assertTrue(contact[key], contact)
            self.assertTrue(row['attached'])
            for anchor in row['anchors']:
                self.assertTrue(anchor['attached'])
                self.assertAlmostEqual(anchor['errorX'], 0)
                self.assertAlmostEqual(anchor['errorY'], 0)
            for transform in row['transforms']:
                self.assertLess(abs(transform['error']), .001)
            # The wall normally prevents reaching the old deletion border.
            # Isolate that death path by removing obstacles and bypassing wall
            # resolution only; run the real Ninja.move and onLethalDeath.
            row['deletion'] = page.evaluate('''() => {
                const player=ninja, wall=screen.leftWall;
                const due=PLATFORM.isInterstitialDue;
                const resolve=wall.resolve;
                for(const f of floors) f.elements=[];
                wall.resolve=()=>false; PLATFORM.isInterstitialDue=()=>false;
                ninja.invulnerableMs=0;
                ninja.x=screen.getDeletionBorder()-screen.x-100;
                ninja.speedX=ninja.speedY=0;
                const before={x:ninja.x,cameraX:screen.x,border:screen.getDeletionBorder()};
                try {ninja.move()} finally {wall.resolve=resolve; PLATFORM.isInterstitialDue=due}
                cancelAnimationFrame(game);
                return {before,restarted:ninja!==player,newWall:screen.leftWall!==wall,
                    frozen:isRunFrozen(),ropeCleared:grapnel.pos.length===0};
            }''')
            self.assertTrue(row['deletion']['restarted'] and row['deletion']['newWall'])
            self.assertTrue(row['deletion']['ropeCleared'])
            self.assertFalse(row['deletion']['frozen'])
            rows.append(row)
        self.evidence.write('old-wall.json', dict(self.proof, modes=rows,
            classic_bad_camera_wall_pass=True, classic_bad_deletion_death_pass=True))
        print('PASS legacy: classic/bad camera wall contacts, anchor tracking, rendering and deletion-border restart')


MOVER_FIXTURE = '''() => {
    const d=structuredClone(GRAPPLE_OVER_LEVEL);
    d.elements.push(
        {id:'triangle',x:500,y:700,role:'solid',points:[{x:0,y:0},{x:120,y:0},{x:60,y:80}]},
        {id:'counterweight',x:950,y:600,role:'solid',points:[{x:0,y:0},{x:60,y:0},{x:60,y:60},{x:0,y:60}]},
        {id:'red',x:1400,y:500,role:'hazard',grapplable:false,points:[{x:0,y:0},{x:80,y:0},{x:80,y:80},{x:0,y:80}]});
    d.movers=[
        {id:'triangle-motion',element:'triangle',axis:'x',min:500,max:700,periodMs:4000,phase:0,velocity:100},
        {id:'counterweight-motion',element:'counterweight',axis:'y',min:500,max:700,periodMs:2000,phase:.75,velocity:-200},
        {id:'red-motion',element:'red',axis:'y',min:500,max:800,periodMs:3000,phase:0,velocity:200}];
    return d;
}'''


class Task455Tests(unittest.TestCase):
    TASK = 'TASK-455'
    setUpClass = classmethod(Task446Tests.setUpClass.__func__)
    open = Task446Tests.open

    def test_3600_tick_trajectories_and_caches(self):
        page = self.open()
        page.evaluate('window.moverFixture=' + MOVER_FIXTURE)
        runs = []
        for offscreen in (False, False, True):
            runs.append(page.evaluate('''offscreen => {
                const oldRandom=Math.random; Math.random=()=>{throw Error('random authored mover')};
                let w; try {w=loadFixedLevel(moverFixture())} finally {Math.random=oldRandom}
                floors=[w]; screen.x=offscreen ? -10000 : 0; screen.y=0;
                const movers=w.level.movers.map(m=>w.byId.get(m.element));
                grapnel.throwed=grapnel.grappled=true;
                grapnel.pos=movers.map(e=>[e.x+20,e.y,e]);
                const initial=movers.map(e=>({id:e.id,x:e.x,y:e.y,dx:e.dx,dy:e.dy,
                    role:e.surfaceRole,grapplable:e.grapplable,stroke:e.stroke}));
                const rows=[],reversals=[]; let last=movers.map(e=>Math.sign(e.speedX||e.speedY));
                let cacheError=0,anchorError=0,visible=0;
                for(let tick=1;tick<=3600;tick++) {
                    for(let sub=0;sub<cyclesPerTick;sub++) {
                        w.moveElements(); grapnel.move();
                        movers.forEach((e,i)=>{
                            const sign=Math.sign(e.speedX||e.speedY);
                            if(sign!==last[i])reversals.push({tick,sub,id:e.id,x:e.x,y:e.y});
                            last[i]=sign;
                            const p=e.getPoints(),b={},c=e.getCircumscribedCircle(),lines=e.getLines();e.writeBounds(b);
                            if(lines.length!==e.points.length || e.linesX!==e.x || e.linesY!==e.y)throw Error('stale lines');
                            cacheError=Math.max(cacheError,Math.abs(p[0].x-e.x),Math.abs(p[0].y-e.y),
                                Math.abs(b.left-e.x),Math.abs(c.x-e.x-e.circle.x));
                            anchorError=Math.max(anchorError,Math.abs(grapnel.pos[i][0]-e.x-20),
                                Math.abs(grapnel.pos[i][1]-e.y));
                        });
                    }
                    visible+=movers.filter(e=>isCullBoxVisible(getElementCullBox(e),getCullRect())).length;
                    if(tick%60===0)draw();
                    rows.push(movers.map((e,i)=>[e.x,e.y,e.dx,e.dy,...grapnel.pos[i].slice(0,2)]));
                }
                return {offscreen,initial,rows,reversals,cacheError,anchorError,visible};
            }''', offscreen))
        for run in runs:
            self.assertEqual(len(run['rows']), 3600)
            self.assertGreater(len(run['reversals']), 50)
            self.assertLessEqual(run['cacheError'], 1e-6)
            self.assertLessEqual(run['anchorError'], 1e-6)
            self.assertEqual(run['rows'], runs[0]['rows'])
            self.assertEqual(run['reversals'], runs[0]['reversals'])
            for e in run['initial']:
                self.assertEqual([e['dx'], e['dy']], [0, 0])
                self.assertEqual(e['role'], 'hazard' if e['id']=='red' else 'solid')
        self.assertGreater(runs[0]['visible'], 0)
        self.assertEqual(runs[2]['visible'], 0)
        invalid = page.evaluate('''() => ['velocity','position','phase'].map(key=>{
            const d=moverFixture();
            if(key==='velocity')d.movers[0].velocity=-100;
            if(key==='position')d.elements.find(e=>e.id==='triangle').x=550;
            if(key==='phase')d.movers[0].phase=.25;
            try {loadFixedLevel(d);return 'accepted'}catch(e){return e.message}
        })''')
        self.assertTrue(all(s.startswith('InvalidMoverInitialState:') for s in invalid))
        self.evidence.write('movers.json', dict(self.proof, runs=runs, invalid=invalid,
            ticks=3600, tolerance=1e-6, identical_runs=True, culling_independent=True))
        print('PASS 3600 ticks x3: identical trajectories/reversals/anchors; offscreen visible=0; cache/anchor error <=1e-6')

    def test_input_attachment_reversal_release_video(self):
        context=self.browser.new_context(viewport={'width':1280,'height':720},
            record_video_dir=str(self.evidence.path('video')),record_video_size={'width':1280,'height':720})
        self.addCleanup(context.close)
        page=context.new_page(); page.goto(self.url); wait_for_boot(page)
        page.evaluate("() => {startGame('grapple_over');cancelAnimationFrame(game)}")
        page.wait_for_function('!unTouch')
        page.evaluate('window.moverFixture=' + MOVER_FIXTURE)
        point=page.evaluate('''() => {
            floors=[loadFixedLevel(moverFixture())];
            TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500);
            ninja.x=550;ninja.y=600;ninja.speedX=ninja.speedY=0;
            screen.x=300;screen.y=-200;draw();
            return canvasCoordsToViewportCoords({x:(550+screen.x)*scale[version],y:(720+screen.y)*scale[version]});
        }''')
        page.mouse.move(point['x'],point['y']);page.mouse.down()
        attached=page.evaluate('''() => {
            for(let i=0;i<15 && !grapnel.isGrappled();i++)physics();
            return {attached:grapnel.isGrappled(),id:grapnel.pos.at(-1)?.[2].id};
        }''')
        self.assertEqual(attached,dict(attached=True,id='triangle'))
        rows=page.evaluate('''async () => {
            const rows=[],e=floors[0].byId.get('triangle');
            const offset=[grapnel.pos.at(-1)[0]-e.x,grapnel.pos.at(-1)[1]-e.y];
            for(let i=0;i<180;i++) {
                physics();draw();
                const p=grapnel.pos.find(p=>p[2]===e);
                rows.push({tick:i,x:e.x,vx:e.speedX,attached:grapnel.isGrappled(),
                    error:p ? Math.hypot(p[0]-e.x-offset[0],p[1]-e.y-offset[1]) : null});
                await new Promise(r=>setTimeout(r,17));
            }
            return rows;
        }''')
        self.assertTrue(any(r['vx']<0 for r in rows))
        self.assertTrue(all(r['attached'] and r['error'] is not None and r['error']<=1e-6 for r in rows))
        page.mouse.up()
        released=page.evaluate('''() => {physics();draw();return !grapnel.throwed&&!grapnel.isGrappled()}''')
        self.assertTrue(released);page.wait_for_timeout(300)
        video=page.video;context.close();video.save_as(str(self.evidence.path('movers.webm')));video.delete()
        self.evidence.write('attachment.json',dict(attached=attached,rows=rows,released=released))
        print('PASS movers.webm: mouse press attaches triangle; physics reversal; anchor drift <=1e-6; mouse release detaches')

    def test_mover_player_contacts(self):
        page=self.open()
        page.evaluate('window.moverFixture=' + MOVER_FIXTURE)
        rows=page.evaluate('''() => {
            floors=[loadFixedLevel(moverFixture())];const w=floors[0],player=ninja;
            return ['triangle','counterweight','red'].map(id=>{
                w.moveElements();const e=w.byId.get(id);
                ninja.x=e.x+30;ninja.y=e.y-ninja.radius+2;
                ninja.speedX=0;ninja.speedY=.2;ninja.hazardCooldownMs=0;
                ninja.collision();
                return {id,vy:ninja.speedY,cooldown:ninja.hazardCooldownMs,
                    penetration:ninja.y+ninja.radius-e.y,samePlayer:ninja===player,
                    grapplable:e.grapplable,stroke:e.stroke};
            });
        }''')
        for row in rows:
            self.assertTrue(row['samePlayer'])
            self.assertLessEqual(row['penetration'],1e-6)
            if row['id']=='red':
                self.assertLessEqual(row['vy'],-420/480)
                self.assertEqual(row['cooldown'],350)
            else:
                self.assertEqual(row['vy'],0)
                self.assertEqual(row['cooldown'],0)
                self.assertTrue(row['grapplable'])
                self.assertEqual(row['stroke'],'#2f86ff')
        self.evidence.write('contacts.json',rows)
        print('PASS blue triangle/counterweight: solid and grappleable; red mover: nonlethal knockback')
