"""Focused browser evidence for TASK-447 solid contacts and legacy reflection."""
import hashlib
import json
import math
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


# TASK-463 tick-100 exit boxes, re-frozen for both ranges, plus the drag_zone
# landing box: the damped flight lands well short of the undamped release.
TASK503_BOXES = {
    'launch': {'x': [1190, 1270], 'y': [680, 730]},
    'release': {'x': [1040, 1140], 'y': [715, 840]},
    'braking': {'x': [1390, 1600], 'y': [970, 1035], 'speedX': [0, 0.6]},
    'angled_bounce': {'x': [-650, -400], 'y': [0, 250]},
    'corner_wrap': {'x': [970, 1090], 'y': [2250, 2380]},
    'moving_transfer': {'x': [780, 840], 'y': [645, 690]},
    'drag_zone': {'x': [1040, 1140], 'y': [715, 840]}}
# Landing contact after the drag band: undamped release lands with |vx| ~0.58.
TASK503_DRAG_LANDING = {'x': [1200, 1540], 'speedX': [0, 0.2]}
TASK503_FAMILIES = ('launch', 'release', 'braking', 'angled_bounce', 'corner_wrap', 'moving_transfer', 'drag_zone')
TASK503_RANGES = {540: False, 810: True}
# Frozen v2 mandatory-gap targets: 85-90% of each range, as rope-to-anchor reach.
TASK503_GAP_TARGETS = {540: [459, 486], 810: [689, 729]}


class Task503Tests(unittest.TestCase):
    """Recalibrate the movement families at 540/810 range, add drag_zone, freeze v2 gaps."""
    results = {}

    @classmethod
    def setUpClass(cls):
        import test_grapple_over_tools as task463
        from grapple_over_verify import hashes
        cls.task463 = task463
        cls.evidence = EvidenceWriter('TASK-503')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.hashes = cls.current_hashes()
        cls.proof = dict(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
            text=True).strip(), source_hashes=cls.hashes, browser=cls.browser.version,
            viewport=task463.VIEWPORT, device_scale_factor=1, has_touch=True, hz=60, substeps=8, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    @staticmethod
    def current_hashes():
        from grapple_over_verify import hashes
        result = hashes()
        for path in ('tools/grapple_over_calibration.js', 'tools/test_grapple_over_physics.py'):
            result[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        return result

    def open(self):
        page = self.task463.Task461Tests.open(self)
        self.task463.install_recorder(page)
        page.add_script_tag(path=str(ROOT / 'tools/grapple_over_calibration.js'))
        return page

    def attempt(self, page, family, upgraded, dt=0, aim=0, negative=False):
        """Task463Tests.attempt with a range switch; drag_zone's negative keeps its grapple."""
        page.mouse.up()
        page.evaluate('GRAPPLE_OVER_TEST.attempts.length=0')
        page.evaluate('n=>GRAPPLE_OVER_TEST.begin(n)', family)
        page.evaluate('calibrationSetup', dict(family=family, negative=negative, upgraded=upgraded))
        omit = negative and family != 'drag_zone'
        if family == 'angled_bounce':
            actions = [(0, 'mousedown', 700 + aim, 440), (3 + dt, 'mouseup', 700, 440)]
        elif family == 'corner_wrap':
            actions = [(3 + dt, 'mousedown', 1100, 700 + aim), (85, 'mouseup', 1100, 700)]
        elif family == 'braking':
            actions = [] if omit else [(3 + dt, 'mousedown', 580, 700 + aim), (50, 'mouseup', 580, 700)]
        elif family == 'launch':
            actions = [] if omit else [(3 + dt, 'mousedown', 930 + aim, 660), (60, 'mouseup', 930, 660)]
        else:
            actions = [] if omit else [(0, 'mousedown', 930 + aim, 660), (30 + dt, 'mouseup', 930, 660)]
            if family == 'moving_transfer' and not omit:
                actions += [(33 + dt, 'mousedown', 680 + aim, 510), (85, 'mouseup', 680, 510)]
        tick = 0
        for at, event, x, y in actions:
            page.evaluate('n=>GRAPPLE_OVER_TEST.step(n)', at - tick)
            tick = at
            p = page.evaluate('GRAPPLE_OVER_TEST.client', dict(x=x, y=y))
            page.mouse.move(p['x'], p['y'])
            if event == 'mousedown':
                page.mouse.down()
            else:
                page.mouse.up()
        page.evaluate('n=>GRAPPLE_OVER_TEST.step(n)', 100 - tick)
        page.evaluate('''() => {
            for(let i=100;i<600;i++) {
                const landing=floors[0].level.elements.find(e=>e.id==='landing');
                if(Math.abs(ninja.y-(landing.y-ninja.radius))<1e-5 && Math.abs(ninja.speedY)<1e-8) break;
                GRAPPLE_OVER_TEST.step(1);
            }
        }''')
        page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
        result = page.evaluate('calibrationResult()')
        result.update(dt=dt, aim=aim, negative=negative)
        return result

    def drag_pairs(self, r, damping):
        """Entry/exit speedX for each contiguous drag overlap, checked tick by tick."""
        rows, inside, pairs = r['rows'], r['inDrag'], []
        t = 1
        while t < len(rows):
            if inside[t] and not inside[t - 1]:
                start = t
                while t < len(rows) and inside[t]:
                    self.assertAlmostEqual(rows[t]['speedX'], rows[t - 1]['speedX'] * damping, places=12)
                    t += 1
                pairs.append(dict(entry_tick=start - 1, entry_vx=rows[start - 1]['speedX'],
                    exit_tick=t - 1, exit_vx=rows[t - 1]['speedX'], ticks_overlapping=t - start,
                    exit_over_entry=rows[t - 1]['speedX'] / rows[start - 1]['speedX']))
            elif not inside[t] and rows[t]['rope'] == [] and rows[t - 1]['rope'] == []:
                self.assertEqual(rows[t]['speedX'], rows[t - 1]['speedX'])
            t += 1
        return pairs

    def test_01_families_at_both_ranges(self):
        page = self.open()
        constants = page.evaluate('''() => ({gravity:GRAVITY,pull:grappleSpeed,
            throwSpeed:grapnelSpeed,cyclesPerTick,physicsStepMs,radius:ninja.radius,
            range:MODE_DEFINITIONS.grapple_over.acquisitionRadius,
            upgradedRange:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius,
            dragDamping:DRAG_ZONE_HORIZONTAL_DAMPING,scale:scale.grapple_over})''')
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())['modes']['classic']
        for key in ('gravity', 'pull', 'throwSpeed', 'cyclesPerTick', 'physicsStepMs'):
            self.assertEqual(constants[key], baseline['constants'][key])
        self.assertEqual((constants['range'], constants['upgradedRange'], constants['scale']), (540, 810, 0.75))
        out = {}
        for rng, upgraded in TASK503_RANGES.items():
            out[rng] = {}
            for family in TASK503_FAMILIES:
                runs = [self.attempt(page, family, upgraded, dt, aim) for dt, aim in
                        ((0, 0), (-3, 0), (3, 0), (0, -10.8), (0, 10.8))]
                runs.append(self.attempt(page, family, upgraded, negative=True))
                for r in runs:
                    self.assertEqual(r['range'], rng)
                    if family == 'drag_zone':
                        r['drag_pairs'] = self.drag_pairs(r, constants['dragDamping'])
                    self.judge(family, r)
                    print('MEASURE', rng, family, r['dt'], r['aim'], r['negative'], 'success=%s' % r['success'],
                          {k: round(r['rows'][100][k], 3) for k in ('x', 'y', 'speedX', 'speedY')},
                          'landing_tick=%d' % r['landing_contact']['tick'],
                          [(round(d['entry_vx'], 4), round(d['exit_vx'], 4)) for d in r.get('drag_pairs', [])])
                    self.assertEqual(r['success'], not r['negative'], (rng, family, r['dt'], r['aim']))
                successes = [r for r in runs if r['success']]
                self.assertEqual(len(successes), 5)
                envelope = self.envelope(family, successes)
                print('PASS', rng, family, ': nominal + 4 variants; negative rejected; landing ticks',
                      envelope['landing_ticks'])
                out[rng][family] = dict(runs=runs, envelope=envelope)
        # Every fixture anchor lies inside 540, so 810 must not change any trajectory.
        for family in TASK503_FAMILIES:
            for a, b in zip(out[540][family]['runs'], out[810][family]['runs']):
                self.assertEqual([(r['x'], r['y'], r['speedX'], r['speedY']) for r in a['rows']],
                                 [(r['x'], r['y'], r['speedX'], r['speedY']) for r in b['rows']])
        self.__class__.results = dict(constants=constants, families=out)

    def judge(self, family, r):
        row = r['rows'][100]
        events = r['events']
        ids = [p['id'] for e in events if e['type'] == 'acquisition' for p in e['rope']]
        landing = next(e for e in r['setup']['level']['elements'] if e['id'] == 'landing')
        hits = [e for e in events if e['type'] == 'contact' and e.get('contact', {}).get('ny') == -1
                and abs(e['contact']['y'] - landing['y']) < 1e-5]
        self.assertTrue(hits, (family, 'landing absent'))
        r['landing_contact'] = hits[0]
        if family == 'angled_bounce':
            mechanic = bool(r['bounces']) and r['bounces'][0]['after']['speedX'] < -1
        elif family == 'corner_wrap':
            mechanic = any(e['type'] == 'wrap' and any(p['id'] == 'corner' for p in e['rope']) for e in events)
        elif family == 'moving_transfer':
            mechanic = ids[:2] == ['anchor', 'moving-target']
            self.assertNotEqual(r['rows'][0]['elements'], r['rows'][100]['elements'])
        else:
            mechanic = 'anchor' in ids and any(e['type'] == 'release' for e in events)
        if family == 'drag_zone':
            land = hits[0]['player']
            mechanic = (mechanic and len(r['drag_pairs']) == 1 and r['dragZones'] == ['drag'] and
                        all(lo <= abs(land[k]) <= hi if k == 'speedX' else lo <= land[k] <= hi
                            for k, (lo, hi) in TASK503_DRAG_LANDING.items()))
        r['success'] = mechanic and all(lo <= row[k] <= hi for k, (lo, hi) in TASK503_BOXES[family].items())
        self.assertTrue(all(i['trusted'] for i in r['inputs']))

    def envelope(self, family, successes):
        span = lambda values: [min(values), max(values)]
        keys = ('x', 'y', 'speedX', 'speedY')
        result = {
            'launch': {k: span([r['rows'][0][k] for r in successes]) for k in keys},
            'exit': {k: span([r['rows'][100][k] for r in successes]) for k in keys},
            'landing': {k: span([r['landing_contact']['player'][k] for r in successes]) for k in keys},
            'landing_ticks': span([r['landing_contact']['tick'] for r in successes]),
            'successful_action_tick_samples': sorted(set(
                (3 if family in ('launch', 'braking', 'corner_wrap', 'angled_bounce') else 30) + r['dt']
                for r in successes))}
        if family == 'drag_zone':
            result['vx_entry_exit_pairs'] = [dict(dt=r['dt'], aim=r['aim'], **d)
                                             for r in successes for d in r['drag_pairs']]
        return result

    def test_02_gap_metric_reach(self):
        """Bisect the longest acquiring rope-to-anchor distance with trusted mouse input."""
        page = self.open()
        trial = '''([d, upgraded]) => {
            const rect=(id,x,y,w,h)=>({id,x,y,role:'solid',points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
            const level=structuredClone(GRAPPLE_OVER_LEVEL);
            level.movers=[];
            level.elements=[rect('floor',-2000,1000,8000,60),rect('post',700+d,700,40,300)];
            level.encounters[0].elements=level.elements.map(e=>e.id);
            GRAPPLE_OVER_TEST.spawn({level,player:{x:700,y:1000-ninja.radius,speedX:0,speedY:0},
                camera:{x:-300-d/2,y:-300}});
            floors[0].rangeUpgraded=upgraded;
            return GRAPPLE_OVER_TEST.client({x:700+d+20,y:1000-ninja.radius});
        }'''
        def shoot(d, upgraded):
            page.mouse.up()
            page.evaluate('GRAPPLE_OVER_TEST.attempts.length=0')
            page.evaluate("GRAPPLE_OVER_TEST.begin('reach')")
            p = page.evaluate(trial, [d, upgraded])
            page.mouse.move(p['x'], p['y'])
            page.mouse.down()
            page.evaluate('() => {for(let i=0;i<45 && !grapnel.isGrappled();i++) GRAPPLE_OVER_TEST.step(1)}')
            r = page.evaluate('''() => ({grappled:grapnel.isGrappled(),range:grappleOverAcquisitionRadius(),
                target:grapnel.isGrappled()?grapnel.pos[0][2].id:null,
                rope:grapnel.isGrappled()?Math.hypot(grapnel.pos[0][0]-ninja.x,grapnel.pos[0][1]-ninja.y):null,
                anchor:grapnel.isGrappled()?grapnel.pos[0].slice(0,2):null,player:[ninja.x,ninja.y]})''')
            page.mouse.up()
            page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
            return r
        reach = {}
        for rng, upgraded in TASK503_RANGES.items():
            lo, hi = 300.0, 1100.0
            first = shoot(lo, upgraded)
            self.assertTrue(first['grappled'])
            self.assertFalse(shoot(hi, upgraded)['grappled'])
            best, trials = first, []
            while hi - lo > 0.05:
                mid = (lo + hi) / 2
                r = shoot(mid, upgraded)
                self.assertEqual(r['range'], rng)
                trials.append(dict(distance=mid, **r))
                if r['grappled']:
                    self.assertEqual(r['target'], 'post')
                    lo, best = mid, r
                else:
                    hi = mid
            gap = TASK503_GAP_TARGETS[rng]
            measured = best['rope']
            self.assertAlmostEqual(measured, rng, delta=0.5)
            self.assertEqual(gap, [math.ceil(0.85 * rng), math.floor(0.90 * rng)])
            self.assertTrue(gap[1] < measured)
            # Inside the target band the shot must acquire; just past measured reach it must miss.
            band = [shoot(d, upgraded) for d in gap]
            self.assertTrue(all(b['grappled'] for b in band))
            self.assertFalse(shoot(hi + 1, upgraded)['grappled'])
            reach[rng] = dict(measured_reach=measured, last_acquiring_post_face_distance=lo,
                first_missing_post_face_distance=hi, gap_targets=gap,
                gap_targets_as_fraction=[gap[0] / measured, gap[1] / measured],
                target_band_acquires=[dict(distance=d, rope=b['rope']) for d, b in zip(gap, band)],
                bisection=trials)
            print('PASS reach %d: measured rope-to-anchor reach %.3f; gap targets %s acquire (%.1f%%-%.1f%% of reach)'
                  % (rng, measured, gap, 100 * gap[0] / measured, 100 * gap[1] / measured))
        self.assertTrue(reach[540]['measured_reach'] < 600 < reach[810]['measured_reach'])
        self.__class__.reach = reach

    def test_03_manifest_range_object(self):
        page = self.open()
        r = page.evaluate('''() => {
            const run = m => {try {validateMountainManifest(m); return 'valid'} catch(e) {return String(e.message)}};
            const fixture = patch => {const m=structuredClone(GRAPPLE_OVER_MOUNTAIN); patch(m); return run(m)};
            return {range:GRAPPLE_OVER_MOUNTAIN.range, ascent:GRAPPLE_OVER_MOUNTAIN.ascent,
                horizontalEnvelope:GRAPPLE_OVER_MOUNTAIN.horizontalEnvelope,
                current:run(GRAPPLE_OVER_MOUNTAIN),
                bare540:fixture(m=>{m.range=540}),
                wrongUpgraded:fixture(m=>{m.range.upgraded=800}),
                wrongBand:fixture(m=>{m.range.upgradeBand='S04'}),
                extraKey:fixture(m=>{m.range.extra=1}),
                wrongAscent:fixture(m=>{m.ascent=12961}),
                wrongEnvelope:fixture(m=>{m.horizontalEnvelope=6400}),
                modes:MODE_DEFINITIONS.grapple_over};
        }''')
        self.assertEqual(r['range'], dict(base=540, upgraded=810, upgradeBand='S05'))
        self.assertEqual((r['modes']['acquisitionRadius'], r['modes']['upgradedAcquisitionRadius'],
                          r['modes']['rangeUpgradeSection']), (540, 810, 'S05'))
        self.assertEqual(r['current'], 'valid')
        for key in ('bare540', 'wrongUpgraded', 'wrongBand', 'extraKey'):
            self.assertEqual(r[key], 'InvalidRange: mountain.range', key)
        for key in ('wrongAscent', 'wrongEnvelope'):
            self.assertEqual(r[key], 'InvalidMountainExtent: mountain', key)
        lines = ['revision ' + self.proof['revision'],
                 'mountain.js sha256 ' + self.hashes['mountain.js'],
                 'manifest.range = ' + json.dumps(r['range'], sort_keys=True),
                 'manifest.ascent = %s horizontalEnvelope = %s' % (r['ascent'], r['horizontalEnvelope']),
                 'MODE_DEFINITIONS.grapple_over = ' + json.dumps(r['modes'], sort_keys=True),
                 'CHECK current manifest -> ' + r['current'],
                 'CHECK fixture range=540 (bare number) -> REJECTED ' + r['bare540']]
        for key in ('wrongUpgraded', 'wrongBand', 'extraKey', 'wrongAscent', 'wrongEnvelope'):
            lines.append('CHECK fixture %s -> REJECTED %s' % (key, r[key]))
        lines.append('PASS manifest: current validates with range object; bare 540 rejected; ascent/envelope checks kept')
        self.evidence.path('manifest-check.log').write_text('\n'.join(lines) + '\n')
        print(lines[-1])

    def test_04_write_and_audit_calibration(self):
        self.assertTrue(self.results and getattr(self, 'reach', None))
        envelopes = {str(rng): {f: v['envelope'] for f, v in fams.items()}
                     for rng, fams in self.results['families'].items()}
        families = {str(rng): {f: [dict(dt=r['dt'], aim=r['aim'], negative=r['negative'], success=r['success'],
                    range=r['range'], launch=r['rows'][0], exit=r['rows'][100], landing_contact=r['landing_contact'],
                    inputs=r['inputs'], event_types=sorted(set(e['type'] for e in r['events'])),
                    drag_pairs=r.get('drag_pairs')) for r in v['runs']] for f, v in fams.items()}
                    for rng, fams in self.results['families'].items()}
        for rows in families.values():
            for runs in rows.values():
                for r in runs:
                    for key in ('launch', 'exit'):
                        r[key] = {k: r[key][k] for k in ('tick', 'x', 'y', 'speedX', 'speedY')}
        gap = dict(name='v2 mandatory gap', version=2, frozen=True,
            definition='measured rope-to-anchor reach distance: the longest straight distance from the player '
                       'center to the acquired anchor point of a held grapnel shot fired with trusted mouse input '
                       'at a solid face, bisected to 0.05 world units; mandatory gaps must sit at 85-90% of it',
            targets={str(k): v for k, v in TASK503_GAP_TARGETS.items()},
            measured={str(k): {key: v[key] for key in ('measured_reach', 'last_acquiring_post_face_distance',
                      'first_missing_post_face_distance', 'gap_targets_as_fraction', 'target_band_acquires')}
                      for k, v in self.reach.items()},
            range_upgrade=dict(base=540, upgraded=810, upgradeBand='S05'))
        current = self.current_hashes()
        self.assertEqual(current, self.hashes)
        data = dict(self.proof, constants=self.results['constants'], ranges=[540, 810],
            families_list=list(TASK503_FAMILIES), exit_tick=100, success_exit_regions=TASK503_BOXES,
            drag_zone_landing_region=TASK503_DRAG_LANDING,
            drag_zone_fixture='release fixture plus 600x10 drag band at (1150,900); negative omits the band',
            proof_convention='nominal + dt -3/+3 + aim -10.8/+10.8 must succeed, negative control must fail',
            measured_envelopes=envelopes, families=families, gap_metric=gap,
            trajectories_540_equal_810=True, baseline_reference='artifacts/TASK-463/calibration.json',
            all_families_pass=True)
        self.evidence.write('calibration.json', data)
        # Independent re-read of the file just written.
        disk = json.loads(self.evidence.path('calibration.json').read_text())
        self.assertEqual(disk['source_hashes'], self.current_hashes())
        for rng in ('540', '810'):
            self.assertEqual(sorted(disk['families'][rng]), sorted(TASK503_FAMILIES))
            for name, runs in disk['families'][rng].items():
                self.assertEqual(len(runs), 6)
                self.assertEqual([r['success'] for r in runs], [True] * 5 + [False])
                self.assertTrue(all(r['range'] == int(rng) for r in runs))
                env = disk['measured_envelopes'][rng][name]
                self.assertTrue(all(k in env for k in ('launch', 'exit', 'landing', 'landing_ticks')))
            pairs = disk['measured_envelopes'][rng]['drag_zone']['vx_entry_exit_pairs']
            self.assertEqual(len(pairs), 5)
            self.assertTrue(all(abs(p['exit_vx']) < abs(p['entry_vx']) for p in pairs))
        print('PASS audit: 7 families x 2 ranges, 70 successful traces, 14 negative controls, '
              '10 drag vx pairs, gap targets %s, source hashes match' % disk['gap_metric']['targets'])
