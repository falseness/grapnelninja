"""Focused browser evidence for TASK-447 solid contacts and legacy reflection."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, STATE, open_fixture, source_hashes, step
from perf_mobile import SEED_SCRIPT
from test_ninja_bounce import REFLECTION_CHECK, OLD_FORMULA


SETUP = '''
    const d = structuredClone(GRAPPLE_OVER_LEVEL);
    d.elements = [{id:'surface',x:400,y:700,role:'solid',points}];
    d.encounters[0].elements=['surface'];
    floors=[loadFixedLevel(d)];
    const e=floors[0].elements[0];
    const snapshot = () => {
        const distance=Math.sqrt(Math.min(...e.getLines().map(l => segmentDistanceSquared(l,ninja.x,ninja.y))));
        const inside=pointInPolygon(e.getPoints(),ninja.x,ninja.y);
        return {position:[ninja.x,ninja.y],velocity:[ninja.speedX,ninja.speedY],
            penetration:ninja.radius-(inside ? -distance : distance),inside};
    };
'''
RECT = '[{x:0,y:0},{x:600,y:0},{x:600,y:100},{x:0,y:100}]'


class Task447Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter(getattr(cls, 'task_id', 'TASK-447'))
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_physics.py', 'tools/test_ninja_bounce.py'):
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT,
            text=True).strip(), source_hashes=hashes, browser=cls.browser.version,
            viewport=[1280,720], device_scale_factor=1, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, mode='grapple_over'):
        context=self.browser.new_context(viewport={'width':1280,'height':720}, device_scale_factor=1)
        self.addCleanup(context.close)
        page=context.new_page()
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate(SEED_SCRIPT % 1)
        page.evaluate('m => {startGame(m);cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def test_solid_contacts_and_600_tick_rest(self):
        page=self.open()
        rows=page.evaluate('''() => {
            const rows=[];
            for (const kind of ['flat','sloped','corner','edge','sunk','separating','reversed']) {
                let points=RECT;
                if(kind==='sloped') points=[{x:0,y:0},{x:600,y:-300},{x:600,y:100},{x:0,y:100}];
                if(kind==='reversed') points.reverse();
                SETUP
                let nx=0,ny=-1,px=700,py=700;
                if(kind==='sloped') {nx=-1/Math.sqrt(5);ny=-2/Math.sqrt(5);py=550;}
                if(kind==='corner') {nx=-Math.SQRT1_2;ny=-Math.SQRT1_2;px=400;}
                if(kind==='edge') {nx=-1;ny=0;px=400;py=750;}
                const offset=kind==='sunk' ? -2 : ninja.radius-2;
                ninja.x=px+nx*offset;ninja.y=py+ny*offset;
                const vn=kind==='separating' ? 9 : -9;
                ninja.speedX=vn*nx-3*ny;ninja.speedY=vn*ny+3*nx;
                // Deliberately green: collision semantics must come from role.
                e.stroke=STYLE.colors.cube.greenStroke;
                const before=snapshot();ninja.collision();const after=snapshot();
                rows.push({kind,normal:[nx,ny],before,after});
            }
            return rows;
        }'''.replace('RECT', RECT).replace('SETUP', SETUP))
        for row in rows:
            nx,ny=row['normal']; a=row['before']['velocity']; b=row['after']['velocity']
            self.assertLessEqual(row['after']['penetration'], 1e-7, row)
            self.assertFalse(row['after']['inside'], row)
            self.assertAlmostEqual(-a[0]*ny+a[1]*nx, -b[0]*ny+b[1]*nx, places=7)
            self.assertAlmostEqual(b[0]*nx+b[1]*ny, max(0,a[0]*nx+a[1]*ny), places=7)
        fast=page.evaluate('''() => {
            const points=RECT; SETUP
            ninja.x=700;ninja.y=600;ninja.speedX=0;ninja.speedY=1000;
            const before=snapshot(), contacts=[];
            const original=ninja.applySolidContact;
            ninja.applySolidContact=function(c) {
                const before=snapshot();original.call(this,c);
                contacts.push({normal:[c.nx,c.ny],before,after:snapshot()});
            };
            let cycles=0;
            while(!contacts.length && cycles<100) {ninja.move();cycles++;}
            delete ninja.applySolidContact;
            const impact=snapshot();
            let maxPenetration=-Infinity, maxSpeed=0, insideCount=0;
            for(let i=0;i<600;i++) {
                physics();const s=snapshot();
                maxPenetration=Math.max(maxPenetration,s.penetration);
                maxSpeed=Math.max(maxSpeed,Math.hypot(...s.velocity));
                insideCount+=Number(s.inside);
            }
            return {kind:'fast-impact',before,contacts,impact,cycles,
                rest:{ticks:600,maxPenetration,maxSpeed,insideCount,final:snapshot()}};
        }'''.replace('RECT', RECT).replace('SETUP', SETUP))
        self.assertGreater(len(fast['contacts']),0)
        self.assertLessEqual(fast['impact']['penetration'],1e-7)
        self.assertLess(fast['impact']['position'][1],700)
        self.assertEqual(fast['impact']['velocity'],[0,0])
        self.assertEqual(fast['rest']['insideCount'],0)
        self.assertLessEqual(fast['rest']['maxPenetration'],1e-7)
        self.assertEqual(fast['rest']['maxSpeed'],0)
        self.evidence.write('contacts.json', dict(self.proof,fixtures=rows,fast=fast,
            solid_projection_pass=True,rest_600_ticks_outside=True))
        print('PASS solid: flat/sloped/corner/edge/sunk/separating/reversed; inward removed, tangent retained; fast-impact; 600 ticks outside')

    def test_green_reflection_and_old_modes(self):
        baseline=json.loads((ROOT/'artifacts/TASK-444/baseline.json').read_text())
        results={}
        for mode in ('classic','bad','grapple_over'):
            page=self.open(mode)
            result={'formula':page.evaluate(REFLECTION_CHECK, 1)}
            self.assertEqual(result['formula']['maxAbsDiff'],0)
            if mode in baseline['modes']:
                result['initial']=page.evaluate(STATE)
                result['movement_trace']=step(page,12)
                self.assertEqual(result['initial'],baseline['modes'][mode]['initial'])
                self.assertEqual(result['movement_trace'],baseline['modes'][mode]['movement_trace'])
                result['baseline_equal']=True
            result['collisions']=page.evaluate('''() => {
                const old=OLD; const rows=[];
                for(const slope of [0,-0.5]) {
                    for(const f of floors) f.elements=[];
                    const e=new Trampoline({x:400,y:700,points:[{x:0,y:100},{x:0,y:0},
                        {x:600,y:slope*600},{x:600,y:slope*600+100}]});
                    // A solid tag outside Grapple Over still uses the old response.
                    e.surfaceRole=version==='grapple_over' ? 'bounce' : 'solid';
                    if(slope!==0) e.stroke='#a3adb8';
                    floors[0].elements=[e];
                    const nx=slope/Math.hypot(slope,1),ny=-1/Math.hypot(slope,1);
                    ninja.x=700+nx*(ninja.radius-2);ninja.y=700+slope*300+ny*(ninja.radius-2);
                    ninja.speedX=-9*nx-3*ny;ninja.speedY=-9*ny+3*nx;
                    const incoming={speedX:ninja.speedX,speedY:ninja.speedY};
                    const expected=old(incoming,e.getLines()[1]);ninja.collision();
                    rows.push({slope,stroke:e.stroke,role:e.surfaceRole,incoming,expected,outgoing:{speedX:ninja.speedX,speedY:ninja.speedY}});
                }
                return rows;
            }'''.replace('OLD',OLD_FORMULA))
            for row in result['collisions']:
                for key in ('speedX','speedY'):
                    self.assertAlmostEqual(row['outgoing'][key],row['expected'][key])
            results[mode]=result
        self.evidence.write('bounce-comparison.json',dict(self.proof,modes=results,
            baseline_path='artifacts/TASK-444/baseline.json',green_reflection_unchanged=True,
            classic_bad_baseline_equal=True))
        print('PASS green reflection: 60 velocities per mode plus flat/sloped runtime contacts; classic/bad baseline equal')


class Task454Tests(unittest.TestCase):
    task_id = 'TASK-454'
    setUpClass = classmethod(Task447Tests.setUpClass.__func__)
    open = Task447Tests.open

    def test_nonlethal_contacts_cooldown_and_input(self):
        page = self.open()
        rows = page.evaluate('''() => {
            const rows=[];
            const events={death:0,restart:0,offer:0,ad:0};
            for (const [name,key] of [['onLethalDeath','death'],['reStart','restart']]) {
                const original=window[name]; window[name]=(...args)=>{events[key]++;return original(...args)};
            }
            const show=continueOffer.show.bind(continueOffer);
            continueOffer.show=(...args)=>{events.offer++;return show(...args)};
            const due=PLATFORM.isInterstitialDue.bind(PLATFORM);
            PLATFORM.isInterstitialDue=(...args)=>{events.ad++;return due(...args)};
            const originalNinja=ninja;
            for(const kind of ['flat','fast','corner','sunk','separating','moving','simultaneous']) {
                const d=structuredClone(GRAPPLE_OVER_LEVEL);
                d.elements=[{id:'hazard',x:400,y:700,role:'hazard',points:RECT}];
                d.encounters[0].elements=['hazard'];
                if(kind==='moving') d.movers=[{id:'move',element:'hazard',axis:'y',min:690,max:710,periodMs:1000,phase:0.25}];
                if(kind==='simultaneous') {
                    d.elements.push({...d.elements[0],id:'shallow',y:701});
                    d.encounters[0].elements.push('shallow');
                }
                floors=[loadFixedLevel(d)];
                if(kind==='moving') floors[0].moveElements();
                const e=floors[0].elements[0];
                const nx=kind==='corner'?-Math.SQRT1_2:0, ny=kind==='corner'?-Math.SQRT1_2:-1;
                const offset=kind==='sunk'?-2:ninja.radius-2;
                ninja.x=(kind==='corner'?e.x:e.x+300)+nx*offset;ninja.y=e.y+ny*offset;
                const vn=kind==='fast'?-3:kind==='separating'?0.2:-0.2;
                ninja.speedX=vn*nx-0.4*ny;ninja.speedY=vn*ny+0.4*nx;
                ninja.hazardCooldownMs=0;
                pressHeld=true;stalePress=false;grapnel.throwed=grapnel.grappled=true;
                grapnel.pos=[[500,500,e]];
                const before=[ninja.speedX,ninja.speedY];
                let calls=0;const apply=ninja.applyHazardContact;
                ninja.applyHazardContact=function(c){calls++;return apply.call(this,c)};
                ninja.collision();delete ninja.applyHazardContact;
                const c=ninja.contactWith(nearestLine(e.getLines(),ninja.x,ninja.y),e.getPoints());
                rows.push({kind,normal:[nx,ny],before,after:[ninja.speedX,ninja.speedY],
                    normalSpeed:(ninja.speedX*nx+ninja.speedY*ny)*480,
                    penetration:c.depth,contacts:calls,cooldown:ninja.hazardCooldownMs,
                    detached:!grapnel.throwed&&!grapnel.grappled&&grapnel.pos.length===0,
                    held:pressHeld,stale:stalePress,moverDisplacement:e.dy||0});
            }
            // Repeat impacts during cooldown: separation but no renewed impulse.
            const e=floors[0].elements[0];
            const collide=()=>{ninja.x=700;ninja.y=700-ninja.radius+2;ninja.speedX=0.4;ninja.speedY=0.2;ninja.collision();
                return {velocity:[ninja.speedX,ninja.speedY],cooldown:ninja.hazardCooldownMs,
                    penetration:ninja.contactWith(nearestLine(e.getLines(),ninja.x,ninja.y),e.getPoints()).depth}};
            const repeated=Array.from({length:5},collide);
            menu.gamePaused=true;
            for(let i=0;i<60;i++){gameLoop(1000+i*16.7);cancelAnimationFrame(game)}
            const pausedCooldown=ninja.hazardCooldownMs;
            menu.gamePaused=false;
            floors[0].elements=[];ninja.x=700;ninja.y=400;ninja.speedX=ninja.speedY=0;
            for(let i=0;i<167;i++)calcPhysics();
            const beforeExpiry=ninja.hazardCooldownMs;
            floors[0].elements=[e];const blocked=collide();
            floors[0].elements=[];calcPhysics();floors[0].elements=[e];const expired=collide();
            return {rows,repeated,pausedCooldown,beforeExpiry,blocked,expired,events,
                sameNinja:ninja===originalNinja,continueVisible:continueOffer.visible};
        }'''.replace('RECT', RECT))
        for row in rows['rows']:
            self.assertLessEqual(row['penetration'], 1e-7, row)
            self.assertEqual(row['contacts'], 1)
            self.assertTrue(row['detached'] and row['held'] and row['stale'])
            self.assertEqual(row['cooldown'], 350)
            nx, ny = row['normal']
            a, b = row['before'], row['after']
            self.assertAlmostEqual(-a[0]*ny+a[1]*nx, -b[0]*ny+b[1]*nx)
            self.assertAlmostEqual(row['normalSpeed'], max(420, abs(a[0]*nx+a[1]*ny)*480))
        self.assertNotEqual(rows['rows'][5]['moverDisplacement'], 0)
        for row in rows['repeated'] + [rows['blocked']]:
            self.assertEqual(row['velocity'], [0.4, 0])
            self.assertLessEqual(row['penetration'], 1e-7)
        self.assertEqual(rows['pausedCooldown'], 350)
        self.assertAlmostEqual(rows['beforeExpiry'], 350/168)
        self.assertEqual(rows['expired']['velocity'], [0.4, -420/480])
        self.assertEqual(rows['expired']['cooldown'], 350)
        self.assertEqual(rows['events'], dict(death=0,restart=0,offer=0,ad=0))
        self.assertTrue(rows['sameNinja'])
        self.assertFalse(rows['continueVisible'])
        page.mouse.move(700, 300)
        page.mouse.down()
        self.assertFalse(page.evaluate('grapnel.throwed'))
        page.mouse.up()
        self.assertFalse(page.evaluate('stalePress'))
        page.mouse.down()
        self.assertTrue(page.evaluate('grapnel.throwed'))
        rows['release_then_new_press_throws'] = True
        self.evidence.write('knockback.json', dict(self.proof, observations=rows, assertions_pass=True))
        print('PASS flat/corner/moving/simultaneous: normal >=420, tangent preserved, detached, stale until release; cooldown 350ms, pause frozen, no penetration/death/continue/restart/ad')

    def test_legacy_hazards(self):
        rows=[]
        for mode in ('classic','bad'):
            for ad_due in (False, True):
                page=self.open(mode)
                row=page.evaluate('''adDue => {
                    PLATFORM.isInterstitialDue=()=>adDue;
                    const old=ninja;
                    floors[0].elements=[new Rect({x:400,y:700,width:600,height:100,isDangerRect:true})];
                    for(let i=1;i<floors.length;i++)floors[i].elements=[];
                    ninja.x=700;ninja.y=700-ninja.radius+2;ninja.speedY=1;
                    let deaths=0,restarts=0;const death=onLethalDeath,restart=reStart;
                    onLethalDeath=(...args)=>{deaths++;return death(...args)};
                    reStart=(...args)=>{restarts++;return restart(...args)};
                    ninja.collision();cancelAnimationFrame(game);
                    return {mode:version,adDue,deaths,restarts,replaced:ninja!==old,
                        continueVisible:continueOffer.visible,runOver};
                }''', ad_due)
                self.assertEqual(row['deaths'], 1)
                self.assertEqual(row['restarts'], int(not ad_due))
                self.assertEqual(row['replaced'], not ad_due)
                self.assertEqual(row['continueVisible'], ad_due)
                self.assertEqual(row['runOver'], ad_due)
                rows.append(row)
        self.evidence.write('legacy-hazards.json',dict(self.proof,observations=rows,original_lethal_flow_pass=True))
        print('PASS classic/bad lethal contacts: immediate restart without ad due; continue offer and frozen run when ad due (4 cases)')


DRAG_FIXTURE = '''
    window.dragWorld=(withZone,extra=[])=>{
        const d=structuredClone(GRAPPLE_OVER_LEVEL);
        d.elements=[...extra];
        if(withZone) d.elements.push({id:'drag',x:400,y:700,role:'drag',
            points:[{x:0,y:0},{x:600,y:0},{x:600,y:120},{x:0,y:120}]});
        d.encounters[0].elements=d.elements.map(e=>e.id);
        floors=[loadFixedLevel(d)];screen.leftWall=null;
        pressHeld=false;stalePress=false;grapnel.throwed=grapnel.grappled=false;grapnel.pos=[];
        return floors[0];
    };
    window.inZone=()=>floors[0].dragZones.some(z=>pointInPolygon(z.getPoints(),ninja.x,ninja.y)||
        z.getLines().some(l=>segmentDistanceSquared(l,ninja.x,ninja.y)<ninja.radius*ninja.radius));
    window.contactSpy=()=>{
        const calls={solid:0,hazard:0,bounce:0};
        for(const [name,key] of [['applySolidContact','solid'],['applyHazardContact','hazard']]){
            const original=ninja[name];ninja[name]=function(...a){calls[key]++;return original.apply(this,a)};
        }
        const bounce=Trampoline.prototype.collision;
        Trampoline.prototype.collision=function(...a){calls.bounce++;return bounce.apply(this,a)};
        return calls;
    };
'''


class Task501Tests(unittest.TestCase):
    task_id = 'TASK-501'
    setUpClass = classmethod(Task447Tests.setUpClass.__func__)

    def open(self, mode='grapple_over'):
        page = Task447Tests.open(self, mode)
        page.evaluate('menu.unPause();cancelAnimationFrame(game)')
        page.evaluate('() => {' + DRAG_FIXTURE + '}')
        return page

    def test_01_horizontal_drag_fall(self):
        page = self.open()
        run = '''withZone => {
            dragWorld(withZone);
            const calls=contactSpy();
            ninja.x=430;ninja.y=700-ninja.radius-40;ninja.speedX=1.0;ninja.speedY=0;
            const rows=[];
            for(let tick=1;tick<=400 && ninja.y-ninja.radius<=900;tick++){
                physics();
                rows.push({tick,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,inZone:inZone()});
            }
            return {rows,calls,radius:ninja.radius,damping:DRAG_ZONE_HORIZONTAL_DAMPING,
                collidable:floors[0].elements.map(e=>e.id),dragZones:floors[0].dragZones.map(z=>z.id),
                cyclesPerTick,gravity:GRAVITY};
        }'''
        zone = page.evaluate(run, True)
        plain = page.evaluate(run, False)
        rows = zone['rows']
        inside = [i for i, r in enumerate(rows) if r['inZone']]
        self.assertTrue(inside)
        first, last = inside[0], inside[-1]
        self.assertEqual(inside, list(range(first, last + 1)))
        entry = rows[first - 1]
        exit_ = rows[last]
        self.assertGreaterEqual(abs(entry['vx']), 0.9)
        self.assertLessEqual(abs(exit_['vx']), 0.2)
        for r in rows[last + 1:]:
            self.assertEqual(r['vx'], exit_['vx'])
        self.assertGreater(rows[-1]['y'] - zone['radius'], 820)
        zone_vy = [r['vy'] for r in rows]
        plain_vy = [r['vy'] for r in plain['rows']]
        self.assertEqual(zone_vy, plain_vy)
        self.assertEqual([r['y'] for r in rows], [r['y'] for r in plain['rows']])
        for a, b in zip(rows[first:last + 1], rows[first - 1:last]):
            self.assertAlmostEqual(a['vx'], b['vx'] * zone['damping'], places=12)
        self.assertTrue(all(r['vx'] == 1.0 for r in plain['rows']))
        self.assertEqual(zone['calls'], dict(solid=0, hazard=0, bounce=0))
        self.assertEqual(zone['collidable'], [])
        self.assertEqual(zone['dragZones'], ['drag'])
        self.__class__.fall = dict(zone_height=120, zone=dict(x=400, y=700, width=600, height=120),
            damping_constant=dict(name='DRAG_ZONE_HORIZONTAL_DAMPING', value=zone['damping'],
                applied='once per simulation tick (physics()) while the player circle overlaps a drag zone; speedX only'),
            cycles_per_tick=zone['cyclesPerTick'], gravity_per_cycle=zone['gravity'],
            entry=dict(tick=entry['tick'], vx=entry['vx']), exit=dict(tick=exit_['tick'], vx=exit_['vx']),
            ticks_overlapping=len(inside), player_radius=zone['radius'],
            player_contacts=zone['calls'], series=rows, no_zone_series=plain['rows'],
            vy_series_identical=True, y_series_identical=True, player_passed_through=True)
        print('PASS drag fall: entry |vx|=%.3f exit |vx|=%.4f over %d ticks; vy series identical to no-zone run; 0 contacts'
              % (abs(entry['vx']), abs(exit_['vx']), len(inside)))

    def test_02_grapnel_passes_through(self):
        page = self.open()
        run = '''withFloor => {
            const extra=withFloor ? [{id:'floor',x:400,y:900,role:'solid',
                points:[{x:0,y:0},{x:600,y:0},{x:600,y:60},{x:0,y:60}]}] : [];
            dragWorld(true,extra);
            const calls=contactSpy();
            ninja.x=700;ninja.y=600;ninja.speedX=ninja.speedY=0;
            screen.trackGrappleOver(true);
            const p=canvasCoordsToViewportCoords({x:(700+screen.x)*scale[version],y:(800+screen.y)*scale[version]});
            document.dispatchEvent(new MouseEvent('mousedown',{clientX:p.x,clientY:p.y}));
            const trace=[];
            for(let tick=1;tick<=40;tick++){
                physics();
                const tip=grapnel.pos.length?grapnel.pos[0].slice(0,2):null;
                trace.push({tick,tip,grappled:grapnel.isGrappled(),parked:grapnel.throwed&&grapnel.isParked(),
                    target:grapnel.isGrappled()?grapnel.pos[0][2].id:null,player:[ninja.x,ninja.y]});
                if(grapnel.isGrappled()) break;
            }
            document.dispatchEvent(new MouseEvent('mouseup'));
            return {trace,calls,thrown:trace.some(t=>t.tip)};
        }'''
        miss = page.evaluate(run, False)
        hit = page.evaluate(run, True)
        self.assertTrue(miss['thrown'])
        self.assertFalse(any(t['grappled'] for t in miss['trace']))
        tips = [t['tip'][1] for t in miss['trace'] if t['tip']]
        self.assertGreater(max(tips), 820)  # tip travelled through and beyond the zone
        self.assertTrue(miss['trace'][-1]['parked'])
        self.assertTrue(hit['trace'][-1]['grappled'])
        self.assertEqual(hit['trace'][-1]['target'], 'floor')
        self.assertAlmostEqual(hit['trace'][-1]['tip'][1], 900, places=6)
        for r in (miss, hit):
            self.assertEqual(r['calls'], dict(solid=0, hazard=0, bounce=0))
        self.__class__.grapnel = dict(zone_only_miss=miss, zone_then_solid_hit=hit,
            grapnel_passed_through=True, acquired_drag=False)
        print('PASS grapnel: zone-only throw passes through to y=%.1f and parks unattached; with solid behind it attaches to "floor" at y=900'
              % max(tips))

    def test_03_render_and_write_drag_json(self):
        page = self.open()
        meta = page.evaluate('''() => {
            const rect=(id,x,role,extra={})=>({id,x,y:300,role,...extra,
                points:[{x:0,y:0},{x:160,y:0},{x:160,y:120},{x:0,y:120}]});
            const d=structuredClone(GRAPPLE_OVER_LEVEL);
            d.elements=[rect('solid',100,'solid'),rect('bounce',320,'bounce'),rect('hazard',540,'hazard'),
                rect('mover',760,'solid'),rect('drag',980,'drag')];
            d.movers=[{id:'m',element:'mover',axis:'y',min:280,max:320,periodMs:1000,phase:0.5}];
            d.encounters[0].elements=d.elements.map(e=>e.id);
            floors=[loadFixedLevel(d)];screen.leftWall=null;
            ninja.x=-500;ninja.y=-500;grapnel.throwed=false;grapnel.pos=[];
            TUTORIAL_HINT.visible=false;TUTORIAL_HINT.done=true;
            screen.x=660;screen.y=400;
            const base=ctx.getTransform();draw();
            ctx.save();ctx.setTransform(base);ctx.scale(scale[version],scale[version]);
            ctx.font='bold 34px sans-serif';ctx.fillStyle='#fff';ctx.textAlign='center';
            for(const e of [...floors[0].elements,...floors[0].dragZones])
                ctx.fillText(e.id,e.x+80+screen.x,e.y+175+screen.y);
            ctx.restore();
            return [...floors[0].elements,...floors[0].dragZones].map(e=>({id:e.id,role:e.surfaceRole,fill:e.fill,stroke:e.stroke}));
        }''')
        png = self.evidence.path('drag.png')
        page.screenshot(path=png)
        strokes = {m['id']: m['stroke'] for m in meta}
        self.assertEqual(len(set(strokes.values())), 5, strokes)
        self.assertEqual(strokes['drag'], '#ffc400')
        self.evidence.write('drag.json', dict(self.proof, **getattr(self, 'fall', {}),
            grapnel=getattr(self, 'grapnel', None), render_samples=meta, screenshot='artifacts/TASK-501/drag.png'))
        self.assertTrue(hasattr(self, 'fall') and hasattr(self, 'grapnel'))
        print('PASS render: drag stroke %s distinct from %s' % (strokes['drag'],
              ', '.join('%s=%s' % (k, v) for k, v in strokes.items() if k != 'drag')))

    def test_04_classic_bad_baseline(self):
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())
        out = {}
        for mode in ('classic', 'bad'):
            page, errors = open_fixture(self.browser, self.url, mode, self.addCleanup)
            initial = page.evaluate(STATE)
            trace = step(page, 12)
            drag = page.evaluate("floors.some(f=>f.dragZones)")
            self.assertEqual(initial, baseline['modes'][mode]['initial'])
            self.assertEqual(trace, baseline['modes'][mode]['movement_trace'])
            self.assertFalse(drag)
            self.assertEqual(errors, [])
            out[mode] = dict(initial=initial, movement_trace=trace, baseline_equal=True, drag_zones_loaded=False)
        self.evidence.write('baseline.json', dict(self.proof, baseline_path='artifacts/TASK-444/baseline.json',
            modes=out, classic_bad_baseline_equal=True))
        print('PASS classic/bad: initial state and 12-tick seeded traces equal TASK-444 baseline; no drag zones loaded')
