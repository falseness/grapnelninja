"""Real-input opening route proof; all retained output stays task-local."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from grapple_over_support import install_recorder, state_hash


class Task465Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter(getattr(cls, 'task_id', 'TASK-465'))
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_sections.py', 'tools/grapple_over_support.py',
                     'tools/grapple_over_injector.js', 'tools/grapple_over_verify.py'):
            hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = dict(browser=cls.browser.version, viewport=VIEWPORT, device_scale_factor=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            source_hashes=hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    def open(self, touch=False):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url); wait_for_boot(page)
        page.evaluate("startGame('grapple_over');menu.unPause();cancelAnimationFrame(game)")
        page.wait_for_function('!unTouch')
        install_recorder(page)
        return page

    def aim(self, page, x, y, down):
        p = page.evaluate('GRAPPLE_OVER_TEST.client', dict(x=x,y=y))
        self.assertTrue(0 <= p['x'] <= VIEWPORT['width'] and 0 <= p['y'] <= VIEWPORT['height'], p)
        page.mouse.move(p['x'],p['y'])
        if down: page.mouse.down()
        else: page.mouse.up()

    def test_01_geometry(self):
        page = self.open()
        result = page.evaluate('''() => {
            const m=GRAPPLE_OVER_MOUNTAIN,l=validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole})),
                structural_validations_pass:true};
        }''')
        m = result['manifest']
        self.assertEqual(result['runtime']['elements'], m['geometry']['elements'])
        for collider, model in zip(result['colliders'], m['geometry']['elements']):
            self.assertEqual(collider, {k:model[k] for k in ('id','x','y','points','role')})
        self.assertEqual([e['status'] for e in m['encounters'][:4]], ['built'] * 4)
        self.assertEqual(m['sections'][0]['status'],'built')
        self.assertTrue(all(e['role']=='solid' for e in m['geometry']['elements']))
        self.assertEqual([c['status'] for c in m['connectors'][:2]], ['built','built'])
        self.assertIsNone(result['runtime']['finish'])
        for e in (e for e in m['geometry']['elements'] if e['id'].startswith('S01')):
            self.assertGreaterEqual(e['y']+min(p['y'] for p in e['points']),-1700)
        self.evidence.write('geometry.json', dict(self.proof, **result,
            calibration_reference='artifacts/TASK-463/calibration.json',
            design=dict(entrance_width=600, landing_width=560, landing_top=-120,
                acquisition_range=540, short_miss_floor=18, catch_floor=120,
                opening_rest='loading bay with raised end stop',
                intended_actions=[e['action'] for e in m['encounters'][:2]])))
        print('PASS geometry: S01-01/02/03/04 built; structural_validations_pass; matching runtime polygons; solid roles; base connector; loading bay rest')

    def test_02_real_input_replays(self):
        results=[]
        for name,hold,offset in [('nominal',30,0),('early',27,0),('late',33,0),
                                 ('aim-left',30,-10.8),('aim-right',30,10.8),
                                 ('short-miss',8,0),('miss-anchor',30,0)]:
            page=self.open()
            page.evaluate('''name => {
                GRAPPLE_OVER_TEST.begin(name);
                GRAPPLE_OVER_TEST.spawn({level:validateMountainManifest(GRAPPLE_OVER_MOUNTAIN),
                    player:{x:2160,y:0,speedX:0,speedY:0}});
                window.sectionPlayer=ninja;window.sectionWorld=floors[0];
                window.sectionGeometry=JSON.stringify(floors[0].level.elements);
                screen.trackGrappleOver(true);GRAPPLE_OVER_TEST.step(30);
            }''',name)
            sight=page.evaluate('''() => ({player:captureClimbState().player,
                anchor:GRAPPLE_OVER_TEST.client({x:2390,y:-310}),
                next:GRAPPLE_OVER_TEST.client({x:2860,y:-425})})''')
            if name=='nominal':
                page.evaluate('draw()');page.screenshot(path=str(self.evidence.path('encounters/entrance.png')))
            self.aim(page,2390+offset, -650 if name=='miss-anchor' else -310,True)
            page.evaluate('n=>GRAPPLE_OVER_TEST.step(n)',hold)
            self.aim(page,2390+offset,-310,False)
            page.evaluate('GRAPPLE_OVER_TEST.step(300)')
            page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
            # Keep every tick and all semantic events, deduplicate steady ground contact spam.
            r=page.evaluate('''() => {const a=GRAPPLE_OVER_TEST.attempts.at(-1);
                const contacts=new Map();
                for(const e of a.events.filter(e=>e.type==='contact')) {
                    const k=[e.contact.nx,e.contact.ny,e.contact.y].join(':');
                    if(!contacts.has(k))contacts.set(k,{tick:e.tick,contact:e.contact,player:e.after.simulation.player});
                }
                return {setup:a.metadata,inputs:a.events.filter(e=>e.type==='input').map(e=>({tick:e.tick,
                    event:e.event,trusted:e.trusted,world:e.world})),
                    events:a.events.filter(e=>['acquisition','release','wrap','knockback'].includes(e.type)).map(e=>({
                        tick:e.tick,type:e.type,rope:e.after.rope,player:e.after.simulation.player})),
                    contacts:[...contacts.values()],rows:a.snapshots.map(s=>({tick:s.tick,...s.state.simulation.player})),
                    samePlayer:ninja===sectionPlayer,sameWorld:floors[0]===sectionWorld,
                    unchangedGeometry:JSON.stringify(floors[0].level.elements)===sectionGeometry,
                    final:captureClimbState().player,completed:floors[0].climbStats.completed,
                    next:GRAPPLE_OVER_TEST.client({x:2860,y:-425})};}''')
            r.update(name=name,hold=hold,aim_offset=offset,sightlines=sight)
            self.evidence.write('encounters/'+name+'.json',r)
            page.evaluate('draw()');page.screenshot(path=str(self.evidence.path('encounters/'+name+'.png')))
            self.assertTrue(all(i['trusted'] for i in r['inputs']))
            self.assertEqual(len(r['setup']['setupOnlySpawns']),1)
            self.assertFalse(r['completed'])
            self.assertTrue(r['samePlayer'] and r['sameWorld'] and r['unchangedGeometry'])
            acquired=any(e['type']=='acquisition' and e['rope'][0]['id']=='S01-crane-beam' for e in r['events'])
            success=name not in ('short-miss','miss-anchor')
            print('MEASURE',name,r['final'], 'acquired',acquired,flush=True)
            if success:
                self.assertTrue(acquired)
                self.assertTrue(any(e['type']=='release' for e in r['events']))
                self.assertAlmostEqual(r['final']['y']+r['final']['radius'],-120,delta=1e-5)
                self.assertAlmostEqual(r['final']['speedX'],0,delta=1e-5)
                self.assertAlmostEqual(r['final']['speedY'],0,delta=1e-5)
                self.assertTrue(2480<r['final']['x']<3020)
                landing=next(c for c in r['contacts'] if c['contact']['ny']==-1 and abs(c['contact']['y']+120)<1e-5)
                r['landing_margins']={'left':landing['player']['x']-2460-10.8,
                    'right':3020-landing['player']['x']-10.8}
                self.assertGreater(min(r['landing_margins'].values()),0)
            else:
                self.assertEqual(acquired,name=='short-miss')
                self.assertAlmostEqual(r['final']['y']+r['final']['radius'],18,delta=1e-5)
                self.assertTrue(1860<r['final']['x']<2460)
            for p in (sight['anchor'],sight['next'],r['next']):
                self.assertTrue(0<p['x']<1280 and 0<p['y']<720,p)
            r['pass']=True
            self.evidence.write('encounters/'+name+'.json',r)
            results.append(dict(name=name,pass_condition='broad ledge rest' if success else 'physical dock recovery',
                passed=True,landing_margins=r.get('landing_margins'),camera_sightlines=r['sightlines']))
        geometry=json.loads(self.evidence.path('geometry.json').read_text())
        geometry['observations']=results
        self.evidence.write('geometry.json',geometry)
        print('PASS replays: S01-01 acquisition and S01-02 release; nominal + 4 variants; 2 physical recoveries; trusted input; visible targets; no traversal mutation')

    def test_03_source_hashes(self):
        for path,digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        print('PASS source hashes: runtime and harness match tested worktree')


class Task466Tests(unittest.TestCase):
    task_id = 'TASK-466'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    aim = Task465Tests.aim
    test_04_source_hashes = Task465Tests.test_03_source_hashes

    def test_01_geometry(self):
        page = self.open()
        result = page.evaluate('''() => {
            const m=GRAPPLE_OVER_MOUNTAIN; validateMountainManifest(m);
            return {manifest:m, runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))};
        }''')
        m = result['manifest']
        self.assertEqual(result['runtime']['elements'], m['geometry']['elements'])
        self.assertEqual(m['sections'][0]['status'], 'built')
        self.assertEqual([e['status'] for e in m['encounters'][:4]], ['built']*4)
        self.assertEqual(len({e['action'] for e in m['encounters'][:4]}), 4)
        self.assertTrue(all(e['status']=='built' for e in m['encounters'][:4]))
        self.assertIsNone(result['runtime']['finish'])
        self.assertFalse(any(s['from'].startswith('S01') for s in m['shortcuts']))
        self.assertEqual(m['recoveries'][0]['status'], 'built')
        for actual, model in zip(result['colliders'], m['geometry']['elements']):
            self.assertEqual(actual,{k:model[k] for k in ('id','x','y','points','role')})
            self.assertEqual(model['role'],'solid')
        result.update(self.proof, structural_validations_pass=True,
            surface_roles={'solid':'gray collision terrain', 'bounce':'absent', 'hazard':'absent'},
            shortcut='none assigned to S01', encounters_built=['S01-01','S01-02','S01-03','S01-04'],
            rest_ledge='S01-rest-ledge',exit='S01-exit',recovery_route='S01-recovery-balcony -> S01-lower-anchor -> S01-exit-crane')
        self.evidence.write('geometry.json',result)
        # Annotated overview derived from the actual runtime collision vertices.
        svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#111827"/>',
             '<g fill="white" font-family="sans-serif" font-size="16"><text x="24" y="25">S01 Foundations — four built encounters | gray: solid | no hazards / bounce / shortcut</text></g>']
        def xy(x,y): return (60+(x-1800)*.45, 655+y*.34)
        for e in m['geometry']['elements'][3:]:
            points=' '.join('%g,%g'%xy(e['x']+p['x'],e['y']+p['y']) for p in e['points'])
            x,y=xy(e['x'],e['y'])
            svg.append(f'<polygon points="{points}" fill="#a3a3a3" stroke="white"/><text x="{x}" y="{y-8}" fill="white" font-size="12">{e["id"]}</text>')
        for label,x,y in [('01 acquire',2150,-170),('02 release / rest',2500,-40),('03 staggered transfer',2600,-840),('04 fall + lower-anchor recovery',3390,-650),('rest ledge',3800,-1000),('exit to next band',4000,-1780)]:
            x,y=xy(x,y);svg.append(f'<text x="{x}" y="{y}" fill="#67e8f9" font-size="16">{label}</text>')
        svg.append('</svg>')
        overview=self.browser.new_page(viewport=VIEWPORT);self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(svg))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        self.evidence.write('overview.json',dict(pass_condition='runtime polygons and labeled encounters/rest/exit/recovery; all surfaces solid',
            sha256=hashlib.sha256(self.evidence.path('overview.png').read_bytes()).hexdigest()))
        print('PASS geometry: four built S01 encounters; matching runtime colliders; rest ledge; next-band exit; lower-anchor recovery; all solid; no S01 shortcut')

    def run_route(self, touch=False):
        page=self.open(touch=touch)
        cdp=page.context.new_cdp_session(page) if touch else None
        name='touch' if touch else 'mouse'
        self.evidence.log('INPUT_CONFIG '+json.dumps(dict(device=name,has_touch=touch)))
        page.evaluate('''name => {
            GRAPPLE_OVER_TEST.begin(name);
            GRAPPLE_OVER_TEST.spawn({level:validateMountainManifest(GRAPPLE_OVER_MOUNTAIN),
                player:{x:2160,y:0,speedX:0,speedY:0}});
            window.sectionPlayer=ninja;window.sectionWorld=floors[0];
            window.sectionGeometry=JSON.stringify(floors[0].level.elements);
            screen.trackGrappleOver(true);GRAPPLE_OVER_TEST.step(30);
        }''',name)
        plan=[(2390,-310,30,300),(2970,-425,30,0),(3180,-730,55,0),
              (2890,-1040,45,0),(3290,-1070,80,180),(3290,-1070,20,0),
              (3630,-1280,55,0),(3840,-1680,45,0),(3840,-1680,45,0),
              (3840,-1680,50,0),(4070,-1620,30,180)]
        milestones=[]
        for index,(x,y,hold,free) in enumerate(plan):
            client=page.evaluate('GRAPPLE_OVER_TEST.client',dict(x=x,y=y))
            self.assertTrue(0<client['x']<1280 and 0<client['y']<720,client)
            if touch:
                cdp.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[dict(**client,id=0)]))
            else:
                self.aim(page,x,y,True)
            page.wait_for_function('n=>GRAPPLE_OVER_TEST.attempts.at(-1).events.filter(e=>e.type==="input").length===n', arg=index*2+1)
            page.evaluate('n=>GRAPPLE_OVER_TEST.step(n)',hold)
            if touch:
                cdp.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]))
            else:
                page.mouse.up()
            page.wait_for_function('n=>GRAPPLE_OVER_TEST.attempts.at(-1).events.filter(e=>e.type==="input").length===n', arg=index*2+2)
            page.evaluate('n=>GRAPPLE_OVER_TEST.step(n)',free)
            milestones.append(page.evaluate('''() => ({tick:GRAPPLE_OVER_TEST.attempts.at(-1).snapshots.at(-1).tick,
                player:captureClimbState().player,rope:GRAPPLE_OVER_TEST.snapshot().rope})'''))
            self.evidence.write(f'encounters/{name}-milestones.json',milestones)
            if index in (3,4,len(plan)-1):
                page.evaluate('draw()');page.screenshot(path=str(self.evidence.path(f'encounters/{name}-{index}.png')))
        page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
        r=page.evaluate('''() => {const a=GRAPPLE_OVER_TEST.attempts.at(-1);
            return {setup_count:a.metadata.setupOnlySpawns.length,
                inputs:a.events.filter(e=>e.type==='input').map(e=>({tick:e.tick,event:e.event,trusted:e.trusted,world:e.world})),
                events:a.events.filter(e=>['acquisition','release','wrap','knockback'].includes(e.type)).map(e=>({tick:e.tick,type:e.type,rope:e.after.rope})),
                rows:a.snapshots.map(s=>({tick:s.tick,...s.state.simulation.player})),
                samePlayer:ninja===sectionPlayer,sameWorld:floors[0]===sectionWorld,
                unchangedGeometry:JSON.stringify(floors[0].level.elements)===sectionGeometry,
                completed:floors[0].climbStats.completed};}''')
        r.update(name=name,plan=plan,milestones=milestones,source_hashes=self.proof['source_hashes'])
        self.evidence.write(f'encounters/{name}.json',r)
        self.assertEqual(r['setup_count'],1)
        self.assertEqual(len(r['inputs']),len(plan)*2)
        self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertTrue(r['samePlayer'] and r['sameWorld'] and r['unchangedGeometry'])
        self.assertFalse(r['completed'])
        for i,target in [(2,'S01-transfer-beam'),(3,'S01-upper-beam'),(5,'S01-lower-anchor')]:
            self.assertEqual(milestones[i]['rope'][0]['id'],target)
        miss=milestones[4]['player']
        self.assertAlmostEqual(miss['y']+miss['radius'],-780,delta=1e-5)
        self.assertTrue(3230<miss['x']<3650)
        self.assertEqual(miss['speedY'],0)
        self.assertLess(milestones[5]['player']['y'],miss['y']-15)
        final=milestones[-1]['player']
        self.assertAlmostEqual(final['y']+final['radius'],-1620,delta=1e-5)
        self.assertTrue(3940<final['x']<4260)
        self.assertAlmostEqual(final['speedX'],0,delta=1e-5)
        self.assertAlmostEqual(final['speedY'],0,delta=1e-5)
        r.update(passed=True, assertions=['S01-03 staggered acquisitions','S01-04 lower-anchor recovery',
            'local miss landed on broad balcony','section exit traversed at next band',
            'trusted input only; single initial spawn; unchanged world and player; no finish/checkpoint'])
        self.evidence.write(f'encounters/{name}.json',r)
        print(f'PASS {name}: S01-03 transfer; S01-04 lower-anchor recovery; local miss; section exit traversed; trusted inputs; no traversal mutation')

    def test_02_mouse_route(self):
        self.run_route()

    def test_03_touch_recovery_aim(self):
        page=self.open(touch=True)
        self.evidence.log('INPUT_CONFIG has_touch=true device=touch viewport=1280x720')
        page.evaluate("""() => {
            GRAPPLE_OVER_TEST.begin('touch-recovery');
            GRAPPLE_OVER_TEST.spawn({level:validateMountainManifest(GRAPPLE_OVER_MOUNTAIN),
                player:{x:3599.1999999,y:-790.8000001,speedX:0,speedY:0}});
            screen.trackGrappleOver(true);GRAPPLE_OVER_TEST.step(30);
        }""")
        client=page.evaluate('GRAPPLE_OVER_TEST.client',dict(x=3290,y=-1070))
        cdp=page.context.new_cdp_session(page)
        cdp.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[dict(**client,id=1)]))
        page.wait_for_function('GRAPPLE_OVER_TEST.attempts.at(-1).events.some(e=>e.type==="input")')
        page.evaluate('GRAPPLE_OVER_TEST.step(20)')
        cdp.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]))
        page.wait_for_function('GRAPPLE_OVER_TEST.attempts.at(-1).events.filter(e=>e.type==="input").length===2')
        page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
        r=page.evaluate("""() => {const a=GRAPPLE_OVER_TEST.attempts.at(-1);return {
            setup_count:a.metadata.setupOnlySpawns.length,
            inputs:a.events.filter(e=>e.type==='input').map(e=>({event:e.event,trusted:e.trusted,world:e.world})),
            acquisitions:a.events.filter(e=>e.type==='acquisition').map(e=>e.after.rope[0].id),
            rows:a.snapshots.map(s=>({tick:s.tick,...s.state.simulation.player})),
            final:captureClimbState().player,throwed:grapnel.throwed};}""")
        self.evidence.write('encounters/touch-recovery.json',r)
        self.assertEqual(r['setup_count'],1)
        self.assertEqual([i['event'] for i in r['inputs']],['touchstart','touchend'])
        self.assertTrue(all(i['trusted'] for i in r['inputs']))
        self.assertIn('S01-lower-anchor',r['acquisitions'])
        self.assertLess(r['final']['y'],-805)
        self.assertFalse(r['throwed'])
        r.update(passed=True,source_hashes=self.proof['source_hashes'],
            assertion='trusted touch acquires lower recovery anchor, lifts from balcony, releases')
        self.evidence.write('encounters/touch-recovery.json',r)
        page.evaluate('draw()');page.screenshot(path=str(self.evidence.path('encounters/touch-recovery.png')))
        print('PASS touch: trusted lower-anchor acquisition; physical lift from recovery balcony; release')


class Task467Tests(unittest.TestCase):
    """Measured S01 tolerance, with only initial isolated placement allowed."""
    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        cls.evidence = EvidenceWriter(getattr(cls, 'task_id', 'TASK-467'))
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.evidence.log('CONFIG '+json.dumps(dict(browser=cls.browser.version,
            viewports=[VIEWPORT,dict(width=844,height=390)], devices=['mouse','touch'],
            revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            source_hashes=hashes()),sort_keys=True))

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import metadata, hashes, execute, check_trace
        page=self.browser.new_page(viewport=VIEWPORT)
        page.goto(self.url); wait_for_boot(page)
        level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)')
        shortcuts=page.evaluate("GRAPPLE_OVER_MOUNTAIN.shortcuts.filter(s=>s.from.startsWith('S01'))")
        page.close()
        self.assertEqual(shortcuts, [])
        plan=[(2390,-310,30,300),(2970,-425,30,0),(3180,-730,55,0),
              (2890,-1040,45,0),(3290,-1070,80,180),(3290,-1070,20,0),
              (3630,-1280,55,0),(3840,-1680,45,0),(3840,-1680,45,0),
              (3840,-1680,50,0),(4070,-1620,30,180)]
        suite=dict(source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated: entrance placement, or touch S01-04 physical drop above recovery balcony; not base-start completion',
            encounters={},negative_control='negative-control.json',shortcuts='none assigned or observed',
            recovery='clips/S01-04-desktop-nominal/trace.json')
        failures=[]
        for encounter,limit,critical,exit_bounds in [
            ('S01-01',1,0,dict(x=[2480,3020],y=[-131,-130])),
            ('S01-02',1,0,dict(x=[2480,3020],y=[-131,-130],speedY=[-0.001,0.001])),
            ('S01-03',4,2,dict(x=[2800,3100],y=[-1025,-900])),
            ('S01-04',11,5,dict(x=[3940,4260],y=[-1631,-1630],speedY=[-0.001,0.001]))]:
            attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
                        player=dict(x=2160,y=0,speedX=0,speedY=0)),inputs=[],
                        expected_exit=exit_bounds,required_events=['acquisition','release'])
                    m['metadata']['compact_contacts']=True
                    if device=='touch': m['metadata']['viewport']=dict(width=844,height=390)
                    tick=30
                    selected=list(enumerate(plan[:limit]))
                    recovery_tick=750
                    if encounter=='S01-04' and device=='touch':
                        # Isolated physical fall: no checkpoint or mid-run placement.
                        m['initial_setup']['player']=dict(x=3599.1999999,y=-890.8000001,speedX=0,speedY=0)
                        tick=90;recovery_tick=90
                        selected=selected[5:]
                    for i,(x,y,hold,free) in selected:
                        if encounter=='S01-03' and i==2: x=3169.2
                        if i==critical: x+=offset;hold+=delta
                        m['inputs'].append(dict(tick=tick,event='touchstart' if device=='touch' else 'mousedown',world=dict(x=x,y=y)))
                        tick+=hold
                        m['inputs'].append(dict(tick=tick,event='touchend' if device=='touch' else 'mouseup',world=dict(x=x,y=y)))
                        tick+=free
                    m['ticks']=tick+1
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    self.evidence.write(prefix+'/input.json',m)
                    trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=variant=='nominal')
                    m['trace']=trace
                    success=True;reason='expected exit and mechanic events satisfied'
                    try: check_trace(m,trace)
                    except ValueError as error: success=False;reason=str(error)
                    acquisitions=[dict(tick=e['tick'],target=e['after']['rope'][0]['id']) for e in trace['events'] if e['type']=='acquisition']
                    transfers=[dict(from_target=a['target'],to_target=b['target'],tick=b['tick'])
                        for a,b in zip(acquisitions,acquisitions[1:]) if a['target']!=b['target']]
                    if encounter=='S01-03' and success:
                        self.assertTrue(any(t['to_target']=='S01-transfer-beam' for t in transfers))
                        self.assertTrue(any(t['to_target']=='S01-upper-beam' for t in transfers))
                    if encounter=='S01-04' and variant=='nominal':
                        players=[r['state']['simulation']['player'] for r in trace['snapshots']]
                        self.assertTrue(any(3230<p['x']<3650 and abs(p['y']+790.8)<0.01 and p['speedY']==0 for p in players))
                        self.assertTrue(any(a['target']=='S01-lower-anchor' and a['tick']>=recovery_tick for a in acquisitions))
                    self.evidence.write(prefix+'/input.json',m)
                    a=dict(name=name,device=device,variant=variant,critical_input_index=critical,
                        hold_delta=delta,tangent_aim_delta=offset,input=prefix+'/input.json',trace=prefix+'/trace.json',
                        success=success,reason=reason,acquisitions=acquisitions,transfers=transfers,
                        events=sorted({e['type'] for e in trace['events']}),final=trace['snapshots'][-1]['state']['simulation']['player'])
                    attempts.append(a)
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',a['final'],reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2:
                    failures.append(encounter+' '+device)
        # Same physical start and exit, aim deliberately beyond the 540-unit range.
        nominal=suite['encounters']['S01-02'][0]
        m=json.loads(self.evidence.path(nominal['input']).read_text());m.pop('trace')
        for event in m['inputs']: event['world']['y']=-650
        m['trace']=execute(m,self.browser,self.url,str(self.evidence.path('clips/negative')),filmstrip=True)
        self.evidence.write('clips/negative/input.json',m)
        with self.assertRaisesRegex(ValueError,'expected exit mismatch'):
            check_trace(m,m['trace'])
        self.evidence.write('negative-control.json',dict(name='range/pull/release: aim outside R',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=True,
            unchanged_physics=True,source_hashes=hashes(),
            final=m['trace']['snapshots'][-1]['state']['simulation']['player'],
            scope='This omission fails this exit; alternative solutions are not ruled out.'))
        self.assertEqual(failures,[])
        print('PASS four encounters: each viewport nominal + >=2/4 variants; all attempts retained; actual fall/recovery; negative outside R fails exit; no shortcuts')

    def test_02_source_hashes(self):
        from grapple_over_verify import hashes
        m=json.loads(self.evidence.path('manifest.json').read_text())
        self.assertEqual(m['source_hashes'],hashes())
        print('PASS source hashes: tested runtime, level and test harness match worktree')


class Task468Tests(unittest.TestCase):
    """S02 opening: trusted inputs, deterministic replay and physical recovery."""
    task_id = 'TASK-468'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    opening = [(3900,-1940,45,0),(4220,-2240,45,0),(4220,-2240,25,0)]

    def test_05_screenshot_inventory(self):
        """Bind the visual-review candidates to this run's replay evidence."""
        screenshots = {}
        for name, tick in [('S02-01-02-nominal', 145),
                           ('S02-01-02-nominal', 355),
                           ('S02-02-miss-recover', 335)]:
            prefix = 'encounters/' + name
            manifest = json.loads(self.evidence.path(prefix+'/input.json').read_text())
            self.assertIn(tick, [event['tick'] for event in manifest['inputs']]
                          + [manifest['ticks'] - 1])
            relative = f'{prefix}/frame-{tick:04d}.png'
            data = self.evidence.path(relative).read_bytes()
            self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertGreater(len(data), 10000)
            screenshots[relative] = hashlib.sha256(data).hexdigest()
        self.evidence.write('screenshot-inventory.json', dict(
            self.proof, screenshots=screenshots,
            review_required=True))
        print('PASS screenshot inventory: 3 replay frames hashed from this run; visual review required')

    def test_01_geometry(self):
        page = self.open()
        result = page.evaluate('''() => {
            const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))};
        }''')
        m=result['manifest']
        self.assertEqual(page.evaluate("I18N.t('climb.section.S02')"),'Switchback Shaft')
        self.assertEqual(m['sections'][1]['status'],'partial')
        self.assertEqual([e['status'] for e in m['encounters'][4:8]],['built','built','planned','planned'])
        self.assertEqual(result['runtime']['elements'],m['geometry']['elements'])
        for actual,model in zip(result['colliders'],m['geometry']['elements']):
            self.assertEqual(actual,{k:model[k] for k in ('id','x','y','points','role')})
        self.assertEqual([c['status'] for c in m['connectors'][4:6]],['built','built'])
        self.assertIsNone(result['runtime']['finish'])
        shaft=[e for e in m['geometry']['elements'] if e['id'].startswith('S02')]
        self.assertEqual(len(shaft),5)
        for e in shaft:
            self.assertEqual(e['role'],'solid')
            self.assertTrue(all(-3240 <= e['y']+p['y'] <= -1620 for p in e['points']))
        self.assertGreater(len({json.dumps(e['points']) for e in shaft}),3)
        result.update(self.proof,structural_validations_pass=True,
            calibration_reference='artifacts/TASK-463/calibration.json',range=540,radius=10.8,
            encounters=m['encounters'][4:6],surface_roles={'solid':'gray industrial silhouettes; same visible/collision vertices'},
            landing_margins={'temporary_exit':{'left':3700,'right':4050,'top':-2050,'safe_center':[3745.8,4039.2]},
                             'lower_catch':{'left':4260,'right':4820,'top':-1840}},
            camera_sightlines='Every replay press asserts target inside 1280x720 viewport; filmstrip at each press/release',
            recovery='Lower catch and open side route physically reconnect to S01-exit; no relocation',
            temporary_exit='S02-test-exit; no dependence on planned S02-03/04')
        self.evidence.write('geometry.json',result)
        print('PASS geometry: S02-01/02; structural_validations_pass; matching colliders; starts/exits; solid roles; landing margins; camera sightlines; partial section')

    def replay(self,name,plan,exit_bounds,start_y=-1630.8):
        from grapple_over_verify import metadata, execute, check_trace, hashes
        page=self.open();level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
            player=dict(x=4100,y=start_y,speedX=0,speedY=0)),inputs=[],
            expected_exit=exit_bounds,required_events=['acquisition','release'])
        m['metadata']['compact_contacts']=True
        tick=30;ends=[]
        for x,y,hold,free in plan:
            m['inputs'].append(dict(tick=tick,event='mousedown',world=dict(x=x,y=y)))
            tick+=hold
            m['inputs'].append(dict(tick=tick,event='mouseup',world=dict(x=x,y=y)))
            ends.append(tick);tick+=free
        m['ticks']=tick+1
        prefix='encounters/'+name
        self.evidence.write(prefix+'/input.json',m)
        trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=True)
        check_trace(m,trace)
        replay=execute(m,self.browser,self.url,str(self.evidence.path(prefix+'/replay')))
        check_trace(m,replay)
        self.assertEqual(trace,replay)
        self.assertEqual(len(trace['metadata']['setupOnlySpawns']),1)
        self.evidence.write(prefix+'/result.json',dict(passed=True,matching_traces=True,
            trusted_inputs=True,no_traversal_mutation=True,source_hashes=hashes(),
            scope='Single initial isolated placement at Foundations exit; production input/physics thereafter',
            final=trace['snapshots'][-1]['state']['simulation']['player']))
        return trace,ends

    def test_02_nominal_encounters(self):
        trace,ends=self.replay('S02-01-02-nominal',self.opening+[(3890,-2480,30,180)],
            dict(x=[3740,4040],y=[-2061,-2060],speedX=[-.001,.001],speedY=[-.001,.001]))
        players=[r['state']['simulation']['player'] for r in trace['snapshots']]
        acquired=[e['after']['rope'][0]['id'] for e in trace['events'] if e['type']=='acquisition']
        self.assertIn('S02-left-balcony',acquired)
        self.assertIn('S02-right-balcony',acquired)
        self.assertIn('S02-brake-girder',acquired)
        before,after=players[ends[2]],players[ends[3]]
        self.assertGreater(before['speedX'],.5)
        self.assertLess(after['speedX'],0)
        self.assertLess(abs(after['speedX']),abs(before['speedX']))
        self.assertTrue(4100<before['x']<4170 and -2020<before['y']<-1970)
        self.evidence.write('encounters/nominal-observations.json',dict(passed=True,
            encounters=['S02-01','S02-02'],acquisitions=acquired,
            braking={'before':before,'after':after,'reduced_and_reversed':True},
            landing=players[-1],landing_margin_left=players[-1]['x']-3700-10.8,
            landing_margin_right=4050-players[-1]['x']-10.8))
        print('PASS S02-01/02 nominal: alternating walls; opposing-anchor braking reduces/reverses speed; safe temporary exit; matching replay; visible targets; trusted inputs; no traversal mutation')

    def test_03_failure_recovery(self):
        # Out-of-range first attempt falls onto the actual Foundations exit,
        # then reacquires the left balcony using ordinary input.
        trace,_=self.replay('S02-01-miss-recover',[(4750,-1730,10,100),(3900,-1940,45,0)],
            dict(x=[3930,4000],y=[-1820,-1750]),start_y=-1730.8)
        players=[r['state']['simulation']['player'] for r in trace['snapshots']]
        self.assertTrue(any(abs(p['y']+1630.8)<.01 and p['speedY']==0 for p in players))
        self.assertLess(players[-1]['y'],-1750)
        trace,_=self.replay('S02-02-miss-recover',self.opening+[(3890,-2480,10,180),(4220,-2240,30,180)],
            dict(x=[3940,4260],y=[-1631,-1630],speedY=[-.001,.001]))
        players=[r['state']['simulation']['player'] for r in trace['snapshots']]
        self.assertTrue(any(4260<p['x']<4820 and abs(p['y']+1850.8)<.01 and p['speedY']==0 for p in players))
        self.evidence.write('encounters/recovery-observations.json',dict(passed=True,
            S02_01='missed acquisition; physical fall to S01-exit; real-input rejoin ascent',
            S02_02='early brake release misses upper rest; lower balcony catches fall; visible side route returns to S01-exit',
            matching_traces=True,no_traversal_mutation=True))
        print('PASS S02-01/02 recovery: missed targets/exits; physical catches; rejoin Foundations; matching replay; no relocation')


class Task469Tests(unittest.TestCase):
    """Completed shaft, measured with trusted mouse/touch and deterministic replay."""
    task_id = 'TASK-469'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    opening = Task468Tests.opening
    route = opening + [(3890,-2480,30,180),(3890,-2480,55,0),
        (4220,-2760,55,0),(4220,-2760,45,0),(3850,-3040,55,0),
        (4170,-3220,55,0),(4430,-3180,30,180)]

    def test_01_geometry(self):
        page=self.open()
        r=page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;
            validateMountainManifest(m);return {manifest:m,runtime:floors[0].level,
            colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))};}''')
        m=r['manifest']
        self.assertEqual(r['runtime']['elements'],m['geometry']['elements'])
        for actual,model in zip(r['colliders'],m['geometry']['elements']):
            self.assertEqual(actual,{k:model[k] for k in ('id','x','y','points','role')})
        self.assertEqual(m['sections'][1]['status'],'built')
        self.assertEqual([e['status'] for e in m['encounters'][4:8]],['built']*4)
        self.assertEqual(len({e['action'] for e in m['encounters'][4:8]}),4)
        self.assertEqual([c['status'] for c in m['connectors'][4:8]],['built']*4)
        self.assertEqual(m['connectors'][8]['authoredFrom'],'S02')
        self.assertEqual(m['recoveries'][1]['status'],'built')
        self.assertFalse(any(s['from'].startswith('S02') for s in m['shortcuts']))
        self.assertFalse(any('test-exit' in e['id'] for e in m['geometry']['elements']))
        self.assertIsNone(r['runtime']['finish'])
        shaft=[e for e in m['geometry']['elements'] if e['id'].startswith('S02')]
        self.assertEqual(len(shaft),9)
        self.assertTrue(all(e['role']=='solid' for e in shaft))
        r.update(self.proof,structural_validations_pass=True,encounters_built=[e['id'] for e in m['encounters'][4:8]],
            rest_ledge='S02-rest-ledge',exit='S02-exit',recovery_route='S02-catch-balcony -> open side -> S01-exit',
            surface_roles={'solid':'gray; rendered polygon equals collider','hazard':'absent','bounce':'absent'},
            shortcut='none assigned to S02',next_section_required=False)
        self.evidence.write('geometry.json',r)
        svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#111827"/>',
             '<text x="24" y="28" fill="white" font-size="20">S02 Switchback Shaft | gray: solid | hazard / bounce / shortcut: none</text>']
        def xy(x,y): return (300+(x-3700)*.55,650+(y+1620)*.34)
        for e in shaft+[next(e for e in m['geometry']['elements'] if e['id']=='S01-exit')]:
            points=' '.join('%g,%g'%xy(e['x']+p['x'],e['y']+p['y']) for p in e['points'])
            x,y=xy(e['x'],e['y'])
            svg.append(f'<polygon points="{points}" fill="#aaa" stroke="white"/><text x="{x}" y="{y+29}" fill="white" font-size="13">{e["id"]}</text>')
        for label,x,y in [('01 alternate walls',3480,-1800),('02 brake / rest',3480,-2180),
                          ('03 lateral reversal',3480,-2690),('04 recessed exit to next band',3900,-3300),
                          ('recovery: open side to Foundations',4480,-2070)]:
            x,y=xy(x,y);svg.append(f'<text x="{x}" y="{y}" fill="#67e8f9" font-size="15">{label}</text>')
        svg.append('</svg>')
        page.set_content('<style>body{margin:0}</style>'+''.join(svg))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        self.evidence.write('overview.json',dict(passed=True,sha256=hashlib.sha256(self.evidence.path('overview.png').read_bytes()).hexdigest(),
            assertion='runtime polygons: four encounters, rest, recessed exit, recovery; all solid; no assigned shortcut'))
        print('PASS geometry: S02-01/02/03/04 built; matching colliders; rest ledge; recessed exit; physical recovery; no temporary exit; no assigned shortcut')

    def replay(self,name,plan,exit_bounds,touch=False):
        from grapple_over_verify import metadata,execute,check_trace,hashes
        page=self.open();level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
            player=dict(x=4100,y=-1630.8,speedX=0,speedY=0)),inputs=[],
            expected_exit=exit_bounds,required_events=['acquisition','release'])
        m['metadata']['compact_contacts']=True
        tick=30;ends=[]
        for x,y,hold,free in plan:
            m['inputs'].append(dict(tick=tick,event='touchstart' if touch else 'mousedown',world=dict(x=x,y=y)))
            tick+=hold
            m['inputs'].append(dict(tick=tick,event='touchend' if touch else 'mouseup',world=dict(x=x,y=y)))
            ends.append(tick);tick+=free
        m['ticks']=tick+1
        prefix='encounters/'+name
        self.evidence.write(prefix+'/input.json',m)
        trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=True)
        check_trace(m,trace)
        replay=execute(m,self.browser,self.url,str(self.evidence.path(prefix+'/replay')))
        check_trace(m,replay);self.assertEqual(trace,replay)
        self.assertEqual(len(trace['metadata']['setupOnlySpawns']),1)
        self.evidence.write(prefix+'/result.json',dict(passed=True,matching_traces=True,
            source_hashes=hashes(),trusted_inputs=True,no_traversal_mutation=True,
            scope='Single initial placement at Foundations exit; production input/physics thereafter',
            final=trace['snapshots'][-1]['state']['simulation']['player']))
        return trace,ends

    def test_02_encounters_mouse_touch(self):
        for device in ('mouse','touch'):
            trace,ends=self.replay(device+'-S02-03-04-exit',self.route,
                dict(x=[4290,4600],y=[-3191,-3190],speedX=[-.001,.001],speedY=[-.001,.001]),touch=device=='touch')
            players=[s['state']['simulation']['player'] for s in trace['snapshots']]
            acquired=[e['after']['rope'][0]['id'] for e in trace['events'] if e['type']=='acquisition']
            for target in ('S02-reversal-balcony','S02-upper-return','S02-exit-anchor','S02-exit'):
                self.assertIn(target,acquired)
            before=players[ends[6]]
            reversed_player=min(players[ends[6]:ends[7]+1],key=lambda p:p['speedX'])
            self.assertGreater(before['speedX'],0)
            self.assertLess(reversed_player['speedX'],0)
            self.assertLess(reversed_player['x'],max(p['x'] for p in players[ends[6]:ends[7]+1]))
            self.evidence.write('encounters/'+device+'-observations.json',dict(passed=True,
                encounters=['S02-03','S02-04'],before=before,reversed=reversed_player,
                acquisitions=acquired,exit=players[-1],assertion='lateral reversal and recessed section exit traversed'))
            print('PASS '+device+': S02-03 lateral reversal; S02-04 recessed exit traversed; trusted inputs; matching replay; no traversal mutation')

    def test_03_local_miss_recovery(self):
        trace,_=self.replay('local-miss-recovery',self.opening+[(3890,-2480,10,180),(4220,-2240,30,190)],
            dict(x=[3940,4260],y=[-1631,-1630],speedY=[-.001,.001]))
        players=[s['state']['simulation']['player'] for s in trace['snapshots']]
        catches=[p for p in players if 4260<p['x']<4820 and abs(p['y']+1850.8)<.01 and p['speedY']==0]
        self.assertTrue(catches)
        self.evidence.write('encounters/recovery-observations.json',dict(passed=True,catch=catches[0],exit=players[-1],
            assertion='local miss physically caught on wide lower balcony; subsequent input returns through visible side to Foundations'))
        print('PASS recovery: local miss; wide lower balcony catch; input-driven side route to Foundations; matching replay')


class Task470Tests(unittest.TestCase):
    task_id = 'TASK-470'
    """S02 real-input tolerance; isolated entrance starts, never completion proof."""
    setUpClass = classmethod(Task467Tests.setUpClass.__func__)
    test_03_source_hashes = Task467Tests.test_02_source_hashes

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import metadata, hashes, execute, check_trace
        page=self.browser.new_page(viewport=VIEWPORT)
        page.goto(self.url); wait_for_boot(page)
        level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)')
        self.assertEqual(page.evaluate("GRAPPLE_OVER_MOUNTAIN.shortcuts.filter(s=>s.from.startsWith('S02'))"),[])
        page.close()
        self.level=level
        suite=dict(section='S02',source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated entrance placement; production physics and trusted inputs thereafter',
            encounters={},negative_control='negative-control.json',shortcuts='none assigned or observed',
            recovery='clips/recovery/input.json',
            earlier_attempts='exploratory/manifest.json',
            landing_release_probes='exploratory/probe',
            tolerance_scope='S02-04 varies final exit release/aim; preceding transfer sensitivity retained in earlier_attempts')
        failures=[]
        # Aim offsets follow the actual struck polygon edge, normalized to 10.8 units.
        for encounter,limit,critical,tangent,bounds in [
            ('S02-01',3,1,(170/177.2004514667,50/177.2004514667),dict(x=[4100,4170],y=[-2020,-1970])),
            ('S02-02',4,3,(1,0),dict(x=[3720,4030],y=[-2062,-2050])),
            ('S02-03',8,7,(110/115.433963806, -35/115.433963806),dict(x=[3800,4180],y=[-3000,-2700])),
            ('S02-04',10,9,(1,0),dict(x=[4280,4600],y=[-3200,-3180]))]:
            attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
                        player=dict(x=4100,y=-1630.8,speedX=0,speedY=0)),inputs=[],
                        expected_exit=bounds,required_events=['acquisition','release'])
                    m['metadata']['compact_contacts']=True
                    if device=='touch': m['metadata']['viewport']=dict(width=844,height=390)
                    tick=30;ends=[]
                    for i,(x,y,hold,free) in enumerate(Task469Tests.route[:limit]):
                        if i==critical: x+=offset*tangent[0];y+=offset*tangent[1];hold+=delta
                        m['inputs'].append(dict(tick=tick,event='touchstart' if device=='touch' else 'mousedown',world=dict(x=x,y=y)))
                        tick+=hold
                        m['inputs'].append(dict(tick=tick,event='touchend' if device=='touch' else 'mouseup',world=dict(x=x,y=y)))
                        ends.append(tick);tick+=free
                    m['ticks']=tick+1
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=variant=='nominal')
                    m['trace']=trace;self.evidence.write(prefix+'/input.json',m)
                    success=True;reason='expected exit and mechanic events satisfied'
                    try: check_trace(m,trace)
                    except ValueError as error: success=False;reason=str(error)
                    acquired=[dict(tick=e['tick'],target=e['after']['rope'][0]['id']) for e in trace['events'] if e['type']=='acquisition']
                    players=[r['state']['simulation']['player'] for r in trace['snapshots']]
                    mechanics=dict(acquisitions=acquired,release_ticks=[e['tick'] for e in trace['events'] if e['type']=='release'],
                        negative_speed_seen=any(p['speedX']<-.05 for p in players),positive_speed_seen=any(p['speedX']>.05 for p in players))
                    if success:
                        self.assertGreaterEqual(len(acquired),2)
                        self.assertTrue(mechanics['negative_speed_seen'] and mechanics['positive_speed_seen'])
                        if encounter=='S02-02':
                            self.assertGreater(players[ends[2]]['speedX'],0)
                            self.assertLess(players[ends[3]]['speedX'],0)
                        if encounter=='S02-03':
                            self.assertIn('S02-upper-return',[a['target'] for a in acquired])
                            self.assertLess(min(p['speedX'] for p in players[ends[6]:ends[7]+1]),0)
                    attempts.append(dict(name=name,device=device,variant=variant,critical_input_index=critical,
                        hold_delta=delta,tangent_aim_delta=offset,tangent=tangent,input=prefix+'/input.json',trace=prefix+'/trace.json',
                        success=success,reason=reason,mechanic_events=mechanics,final=players[-1]))
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2: failures.append(encounter+' '+device)
        nominal=suite['encounters']['S02-02'][0]
        m=json.loads(self.evidence.path(nominal['input']).read_text());m.pop('trace')
        m['inputs']=m['inputs'][:-2]  # Omit only the opposing girder press/release; same duration/start/physics.
        m['trace']=execute(m,self.browser,self.url,str(self.evidence.path('clips/negative')),filmstrip=True)
        self.evidence.write('clips/negative/input.json',m)
        with self.assertRaisesRegex(ValueError,'expected exit mismatch'): check_trace(m,m['trace'])
        players=[r['state']['simulation']['player'] for r in m['trace']['snapshots']]
        self.assertGreater(max(p['x'] for p in players[145:]),4170)
        self.evidence.write('negative-control.json',dict(name='braking: omit opposing-anchor input',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=True,
            unchanged_physics=True,source_hashes=hashes(),overshoot_max_x=max(p['x'] for p in players[145:]),
            final=players[-1],scope='Only this omission fails this exit; alternative solutions are not ruled out.'))
        self.assertEqual(failures,[])
        print('PASS four encounters: both viewports nominal + >=2/4 variants; all attempts retained; opposing acceleration/release/reacquisition; omitted brake overshoots; no shortcuts')

    def test_02_recovery(self):
        from grapple_over_verify import metadata, execute, check_trace
        page=self.browser.new_page(viewport=VIEWPORT);page.goto(self.url);wait_for_boot(page)
        level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,player=dict(x=4100,y=-1630.8,speedX=0,speedY=0)),
            inputs=[],expected_exit=dict(x=[3940,4260],y=[-1631,-1630]),required_events=['acquisition','release'])
        m['metadata']['compact_contacts']=True
        tick=30
        for x,y,hold,free in Task469Tests.opening+[(3890,-2480,10,180),(4220,-2240,30,190)]:
            m['inputs'].append(dict(tick=tick,event='mousedown',world=dict(x=x,y=y)));tick+=hold
            m['inputs'].append(dict(tick=tick,event='mouseup',world=dict(x=x,y=y)));tick+=free
        m['ticks']=tick+1
        m['trace']=execute(m,self.browser,self.url,str(self.evidence.path('clips/recovery')),filmstrip=True)
        check_trace(m,m['trace'])
        replay=execute(m,self.browser,self.url,str(self.evidence.path('clips/recovery/replay')))
        self.assertEqual(m['trace'],replay)
        players=[r['state']['simulation']['player'] for r in replay['snapshots']]
        self.assertTrue(any(4260<p['x']<4820 and abs(p['y']+1850.8)<.01 and p['speedY']==0 for p in players))
        self.evidence.write('clips/recovery/input.json',m)
        self.evidence.write('clips/recovery/result.json',dict(passed=True,matching_traces=True,physical_catch=True,returned_to_Foundations=True))
        print('PASS recovery: local miss, physical catch, input-driven return to Foundations; matching replay')


class Task471Tests(unittest.TestCase):
    """Broken Viaduct opening, with production physics and trusted inputs."""
    task_id = 'TASK-471'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_04_source_hashes = Task465Tests.test_03_source_hashes

    def test_01_geometry(self):
        page = self.open()
        r = page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;
            validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))};}''')
        m = r['manifest']
        self.assertEqual(m['sections'][2]['status'], 'partial')
        self.assertEqual([e['status'] for e in m['encounters'][8:12]], ['built','built','planned','planned'])
        self.assertEqual(r['runtime']['elements'],m['geometry']['elements'])
        for actual, model in zip(r['colliders'],m['geometry']['elements']):
            self.assertEqual(actual,{k:model[k] for k in ('id','x','y','points','role')})
        self.assertEqual([c['status'] for c in m['connectors'][8:10]],['built','built'])
        self.assertIsNone(r['runtime']['finish'])
        bridge = [e for e in m['geometry']['elements'] if e['id'].startswith('S03')]
        self.assertEqual(len(bridge),3)
        self.assertEqual(len({json.dumps(e['points']) for e in bridge}),3)
        self.assertTrue(all(e['role']=='solid' and e['grapplable'] for e in bridge))
        self.assertGreater(5180-4600, m['range'])
        self.assertTrue(all(-4860 <= e['y'] <= -3240 for e in bridge))
        r.update(self.proof,structural_validations_pass=True,
            encounters=m['encounters'][8:10],calibration_reference='artifacts/TASK-463/calibration.json',
            range=540,radius=10.8,gap_width=580,
            surface_roles={'solid':'gray industrial silhouettes; identical visible/collision polygons'},
            landing_margins={'temporary_exit':{'safe_center':[5190.8,5529.2],'top':-3280},
                             'lower_bridge':{'safe_center':[4640.8,4929.2],'top':-3245}},
            band_note='S03 anchor/deck tops in assigned band; bridge support legs overlap the S02 connector band',
            camera_sightlines='All presses checked inside 1280x720; nominal release screenshot shows far deck',
            temporary_exit='S03-test-exit; upper encounters remain planned',
            recovery='Lower bridge catches short release; pull left to physically rejoin S02-exit',
            shortcut='Earlier faster release from same beam skips the conservative swing; exposed overshoot risk')
        self.evidence.write('geometry.json',r)
        print('PASS geometry: S03-01/02; structural_validations_pass; matching colliders; starts/exits; roles; landing margins; camera sightlines; gap 580 > R 540')

    def replay(self, name, plan, ticks, bounds):
        from grapple_over_verify import metadata, execute, check_trace, hashes
        page=self.open();level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
            player=dict(x=4430,y=-3190.8,speedX=0,speedY=0)),inputs=[],ticks=ticks,
            expected_exit=bounds,required_events=['acquisition','release'])
        m['metadata']['compact_contacts']=True
        for tick,event,x,y in plan:
            m['inputs'].append(dict(tick=tick,event=event,world=dict(x=x,y=y)))
        prefix='encounters/'+name
        self.evidence.write(prefix+'/input.json',m)
        trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=True)
        check_trace(m,trace)
        replay=execute(m,self.browser,self.url,str(self.evidence.path(prefix+'/replay')))
        check_trace(m,replay)
        self.assertEqual(trace,replay)
        self.assertEqual(len(trace['metadata']['setupOnlySpawns']),1)
        self.evidence.write(prefix+'/result.json',dict(passed=True,matching_traces=True,
            trusted_inputs=True,no_traversal_mutation=True,source_hashes=hashes(),
            scope='One labeled initial placement on S02-exit; production input/physics thereafter'))
        return [r['state']['simulation']['player'] for r in trace['snapshots']]

    @staticmethod
    def launch(hold):
        return [(30,'mousedown',4740,-3480),(30+hold,'mouseup',4740,-3480)]

    def test_02_nominal_and_shortcut(self):
        landings={}
        for name,hold in [('nominal',65),('shortcut',55)]:
            players=self.replay(name,self.launch(hold),260,
                dict(x=[5191,5530],y=[-3291,-3290],speedX=[-.001,.001],speedY=[-.001,.001]))
            self.assertGreater(players[30+hold]['speedX'],.6)
            self.assertGreater(players[30+hold]['x'],4600)
            landing=next(i for i,p in enumerate(players) if 5190.8<p['x']<5530 and abs(p['y']+3290.8)<.01 and p['speedY']==0)
            landings[name]=landing
            self.assertGreater(players[-1]['x']-5180-10.8,0)
        self.assertLess(landings['shortcut'],landings['nominal'])
        self.evidence.write('encounters/nominal-observations.json',dict(passed=True,
            encounters=['S03-01','S03-02'],landing_ticks=landings,
            gap_beyond_direct_range=True,accelerated_under_departure_beam=True,
            safe_temporary_exit=True,optional_shortcut_faster=True))
        print('PASS S03-01/02 nominal: speed build; release across gap beyond R; safe exit; faster optional shortcut; matching trusted-input replays')

    def test_03_failure_recovery(self):
        first=self.replay('departure-failure',self.launch(15),180,
            dict(x=[4589,4590],y=[-3191,-3190],speedY=[-.001,.001]))
        self.assertLess(max(p['x'] for p in first),4600)
        lower=self.replay('gap-failure-recovery',self.launch(25)+[
            (130,'mousedown',4500,-3180),(165,'mouseup',4500,-3180)],255,
            dict(x=[4300,4500],y=[-3191,-3190],speedY=[-.001,.001]))
        self.assertTrue(any(4640<p['x']<4930 and abs(p['y']+3255.8)<.01 and p['speedY']==0 for p in lower))
        self.assertLess(max(p['x'] for p in lower),5180)
        self.evidence.write('encounters/recovery-observations.json',dict(passed=True,
            departure_failure_returns_to_S02=True,missed_far_deck=True,
            lower_broken_bridge_physical_catch=True,physical_rejoin_Switchback_Shaft=True,
            matching_traces=True,no_traversal_mutation=True))
        print('PASS failure/recovery: short departure returns to S02; lower broken bridge catches missed gap; physical rejoin Switchback Shaft; no relocation')


class Task472Tests(unittest.TestCase):
    """Complete viaduct: isolated S02 exit start, real physics through S03 exit."""
    task_id = 'TASK-472'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task471Tests.replay
    launch = staticmethod(Task471Tests.launch)
    test_03_failure_recovery = Task471Tests.test_03_failure_recovery
    test_04_source_hashes = Task465Tests.test_03_source_hashes

    def test_01_geometry(self):
        page = self.open()
        r = page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))};}''')
        m=r['manifest'];elements=m['geometry']['elements']
        self.assertEqual(r['runtime']['elements'],elements)
        for actual,model in zip(r['colliders'],elements):
            self.assertEqual(actual,{k:model[k] for k in ('id','x','y','points','role')})
        self.assertEqual(m['sections'][2]['status'],'built')
        self.assertEqual([e['status'] for e in m['encounters'][8:12]],['built']*4)
        self.assertEqual(len({e['action'] for e in m['encounters'][8:12]}),4)
        self.assertEqual([c['status'] for c in m['connectors'][8:12]],['built']*4)
        self.assertEqual(m['connectors'][12]['authoredFrom'],'S03')
        self.assertEqual(m['connectors'][12]['status'],'planned')
        self.assertEqual(m['recoveries'][2]['status'],'built')
        self.assertEqual(m['shortcuts'][0]['status'],'built')
        self.assertIsNone(r['runtime']['finish'])
        self.assertFalse(any('test-exit' in e['id'] for e in elements))
        roles={'departure':['S03-departure-beam'],'rest':['S03-rest-ledge'],
            'recovery':['S03-lower-bridge','S02-exit'],
            'airborne transfer':['S03-flight-beam','S03-return-beam','S03-upper-beam'],
            'braking':['S03-brake-beam','S03-exit-anchor'],'exit':['S03-exit']}
        r.update(self.proof,structural_validations_pass=True,encounters=m['encounters'][8:12],
            surface_roles=roles,collision_role='solid for every S03 polygon; colors in overview denote functional roles',
            normal_route_preserved=True,no_temporary_exit=True,
            exit_width=200,rest_width=360,recovery_rejoin='S02-04',
            connector='S03 authored departure at -4820; S04 remains planned')
        self.evidence.write('geometry.json',r)
        # An overview of the exact validated collision polygons, with authored route labels.
        colors=['#d9b35b','#8ccca0','#d28b9b','#83b6e5','#b79adf','#f5f0cf']
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="4200 -5050 1800 2100" style="background:#182028">']
        for (role,ids),color in zip(roles.items(),colors):
            for e in elements:
                if e['id'] in ids:
                    points=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                    parts.append(f'<polygon points="{points}" fill="{color}"/><text x="{e["x"]}" y="{e["y"]-18}" fill="white" font-size="23">{e["id"]}: {role} (solid)</text>')
        for x,y,label in [(4320,-3370,'S03-01 departure'),(4780,-3350,'S03-02 gap'),(4450,-3900,'S03-03 airborne transfers'),(4450,-4550,'S03-04 brake / narrow landing'),(4380,-4960,'Exit to S04 band (destination planned)'),(4300,-3020,'Recovery: lower bridge → S02'),(4300,-2980,'Optional shortcut: earlier exposed launch; normal route retained')]:
            parts.append(f'<text x="{x}" y="{y}" fill="white" font-size="26">{label}</text>')
        parts.append('</svg>')
        page.set_content(''.join(parts));page.set_viewport_size(dict(width=1000,height=1000))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S03-01 S03-02 S03-03 S03-04 built; distinct functional surface roles; rest; recovery; shortcut; authored exit; no temporary geometry; overview.png')

    def test_02_complete_routes(self):
        landings={}
        for name,hold,touch in [('normal',65,False),('shortcut',55,False),('touch',65,True)]:
            plan=[];tick=30
            for x,y,h,free in [(4740,-3480,hold,165),(5250,-3670,70,12),
                    (4910,-3990,110,5),(5270,-4310,135,1),
                    (5190,-4630,90,33 if touch else 30),(5270,-4880,60,360 if touch else 300)]:
                plan.append((tick,'touchstart' if touch else 'mousedown',x,y));tick+=h
                plan.append((tick,'touchend' if touch else 'mouseup',x,y));tick+=free
            players=self.replay(name,plan,tick+1,
                dict(x=[5050,5230],y=[-4831,-4830],speedY=[-.001,.001]))
            trace=json.loads(self.evidence.path('encounters/'+name+'/trace.json').read_text())
            acquisitions=[e for e in trace['events'] if e['type']=='acquisition']
            targets=[e['after']['rope'][0]['id'] for e in acquisitions]
            for target in ['S03-departure-beam','S03-flight-beam','S03-return-beam',
                           'S03-upper-beam','S03-brake-beam','S03-exit-anchor']:
                self.assertIn(target,targets)
            airborne=next(e for e in acquisitions if e['after']['rope'][0]['id']=='S03-return-beam')
            ap=players[airborne['tick']]
            self.assertGreater(abs(ap['speedY']),.01)
            self.assertLess(ap['y'],-3500)
            final_press=plan[-2][0];final_release=plan[-1][0]
            self.assertGreater(players[final_press]['speedX'],.5)
            self.assertLess(players[final_release]['speedX'],0)
            landing=next(i for i,p in enumerate(players) if 5050<p['x']<5230 and abs(p['y']+4830.8)<.01 and p['speedY']==0)
            landings[name]=landing
            self.evidence.write('encounters/'+name+'/observations.json',dict(passed=True,
                S03_03_airborne_acquisition=True,airborne_tick=airborne['tick'],airborne_player=ap,
                targets=targets,S03_04_opposing_brake=True,
                brake_before=players[final_press],brake_after=players[final_release],
                traversed_section_exit=True,landing_tick=landing,final=players[-1],
                normal_rest_visited=any(abs(p['y']+3290.8)<.01 and p['speedY']==0 for p in players)))
        self.assertLess(landings['shortcut'],landings['normal'])
        self.evidence.write('encounters/routes.json',dict(passed=True,landing_ticks=landings,
            shortcut_faster=True,mouse_and_touch=True,encounters=['S03-03','S03-04']))
        print('PASS S03-03/04: airborne acquisition; opposing brake; traversed section exit; normal + faster shortcut + touch; matching trusted-input replays')


class Task473Tests(unittest.TestCase):
    """S03 tolerance from labeled isolated entrance; no completion claim."""
    task_id = 'TASK-473'
    setUpClass = classmethod(Task467Tests.setUpClass.__func__)
    test_03_source_hashes = Task467Tests.test_02_source_hashes

    @staticmethod
    def route(touch=False):
        return [(4740,-3480,65,165),(5250,-3670,70,12),
                (4910,-3990,110,5),(5270,-4310,135,1),
                # TASK-489: touch re-timed for the real S02-exit lip entrance (was 33).
                (5190,-4630,90,36 if touch else 30),
                (5270,-4880,60,360 if touch else 300)]

    def make_input(self, device, limit, critical, delta, offset, bounds, departure_free=None):
        # TASK-489: the S02-exit mid lip stops the landing slide at x 4429.2, the real S03 entrance.
        from grapple_over_verify import metadata
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=self.level,
            player=dict(x=4429.2,y=-3190.8,speedX=0,speedY=0)),inputs=[],
            expected_exit=bounds,required_events=['acquisition','release'])
        m['metadata']['compact_contacts']=True
        touch=device=='touch'
        if touch: m['metadata']['viewport']=dict(width=844,height=390)
        tick=30
        for i,(x,y,hold,free) in enumerate(self.route(touch)[:limit]):
            if i==0 and departure_free is not None: free=departure_free
            if i==critical:
                # Departure underside has tangent (190,20); rectangular beams are horizontal.
                tx,ty=(190/(190**2+20**2)**.5,20/(190**2+20**2)**.5) if i==0 else (1,0)
                x+=offset*tx;y+=offset*ty
                if i==2: tick+=delta  # airborne acquisition timing
                else: hold+=delta  # departure/final braking release timing
            m['inputs'].append(dict(tick=tick,event='touchstart' if touch else 'mousedown',world=dict(x=x,y=y)))
            tick+=hold
            m['inputs'].append(dict(tick=tick,event='touchend' if touch else 'mouseup',world=dict(x=x,y=y)))
            tick+=free
        m['ticks']=tick+1
        return m

    def run_attempt(self,m,prefix,filmstrip=False):
        from grapple_over_verify import execute, check_trace
        trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=filmstrip)
        m['trace']=trace;self.evidence.write(prefix+'/input.json',m)
        success=True;reason='expected exit and mechanic events satisfied'
        try: check_trace(m,trace)
        except ValueError as error: success=False;reason=str(error)
        return trace,success,reason

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes
        page=self.browser.new_page(viewport=VIEWPORT);page.goto(self.url);wait_for_boot(page)
        self.level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        suite=dict(section='S03',source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated S02 exit placement; production physics and trusted inputs thereafter',
            encounters={},negative_control='negative-control.json',recovery='clips/recovery/input.json',
            shortcuts='clips/shortcut/input.json')
        failures=[]
        for encounter,limit,critical,bounds,free in [
            # TASK-489: from the lip rest the swing releases earlier and faster; check the
            # authored S03-01 exit box with rightward speed built under the beam.
            ('S03-01',1,0,dict(x=[4600,4900],y=[-3500,-3280],speedX=[.6,1.4]),0),
            ('S03-02',1,0,dict(x=[5190.8,5530],y=[-3291,-3290],speedY=[-.001,.001]),None),
            ('S03-03',3,2,dict(x=[4720,4940],y=[-4240,-4020],speedX=[.3,1.2]),None),
            ('S03-04',6,5,dict(x=[5050,5230],y=[-4831,-4830],speedY=[-.001,.001]),None)]:
            attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    m=self.make_input(device,limit,critical,delta,offset,bounds,free)
                    trace,success,reason=self.run_attempt(m,prefix,variant=='nominal')
                    players=[r['state']['simulation']['player'] for r in trace['snapshots']]
                    acquired=[e for e in trace['events'] if e['type']=='acquisition']
                    mechanics=dict(acquisitions=[dict(tick=e['tick'],target=e['after']['rope'][0]['id']) for e in acquired],
                        release_ticks=[e['tick'] for e in trace['events'] if e['type']=='release'])
                    if success:
                        if encounter=='S03-03':
                            e=next(e for e in acquired if e['after']['rope'][0]['id']=='S03-return-beam')
                            mechanics['airborne_acquisition']=abs(players[e['tick']]['speedY'])>.01
                            self.assertTrue(mechanics['airborne_acquisition'])
                        if encounter=='S03-04':
                            mechanics['opposing_brake']=players[m['inputs'][-2]['tick']]['speedX']>.5 and players[m['inputs'][-1]['tick']]['speedX']<0
                            self.assertTrue(mechanics['opposing_brake'])
                        if encounter=='S03-02':
                            release=m['inputs'][1]['tick']
                            mechanics['free_flight']=players[release+20]['x']>players[release]['x']+100 and not trace['snapshots'][release+20]['state']['simulation']['grapple']['grappled']
                            self.assertTrue(mechanics['free_flight'])
                    attempts.append(dict(name=name,device=device,variant=variant,critical_input_index=critical,
                        timing_delta=delta,tangent_aim_delta=offset,input=prefix+'/input.json',trace=prefix+'/trace.json',
                        success=success,reason=reason,mechanic_events=mechanics,final=players[-1]))
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2: failures.append(encounter+' '+device)
        m=self.make_input('desktop',1,0,0,0,dict(x=[5190.8,5530],y=[-3291,-3290]))
        m['inputs']=m['inputs'][:1]  # Hold departure anchor throughout the same trial duration.
        trace,success,reason=self.run_attempt(m,'clips/negative',True)
        self.assertFalse(success);self.assertIn('expected exit mismatch',reason)
        self.evidence.write('negative-control.json',dict(name='release timing: hold departure anchor',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=True,
            unchanged_physics=True,source_hashes=hashes(),reason=reason,
            final=trace['snapshots'][-1]['state']['simulation']['player'],
            scope='Only this held-anchor omission fails the intended far landing; alternatives are not ruled out.'))
        self.assertEqual(failures,[])
        print('PASS four encounters: both viewports nominal + >=2/4 variants; release/free-flight/airborne acquisition/braking; held departure fails far landing')

    def test_02_recovery_and_shortcut(self):
        from grapple_over_verify import execute
        page=self.browser.new_page(viewport=VIEWPORT);page.goto(self.url);wait_for_boot(page)
        self.level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        for name in ('recovery','shortcut'):
            if name=='recovery':
                m=self.make_input('desktop',1,0,-40,0,dict(x=[4300,4500],y=[-3191,-3190]))
                m['inputs'] += [dict(tick=130,event='mousedown',world=dict(x=4500,y=-3180)),
                                dict(tick=165,event='mouseup',world=dict(x=4500,y=-3180))]
                m['ticks']=255
            else:
                m=self.make_input('desktop',6,0,-10,0,dict(x=[5050,5230],y=[-4831,-4830]))
            trace,success,reason=self.run_attempt(m,'clips/'+name,True)
            self.assertTrue(success,reason)
            replay=execute(m,self.browser,self.url,str(self.evidence.path('clips/'+name+'/replay')))
            self.assertEqual(trace,replay)
            players=[r['state']['simulation']['player'] for r in trace['snapshots']]
            result=dict(passed=True,matching_traces=True)
            if name=='recovery':
                result['physical_catch']=any(4640<p['x']<4930 and abs(p['y']+3255.8)<.01 and p['speedY']==0 for p in players)
                self.assertTrue(result['physical_catch']);result['physical_rejoin_S02']=True
            else:
                nominal=json.loads(self.evidence.path('clips/S03-04-desktop-nominal/trace.json').read_text())
                def landing(rows):
                    return next(r['tick'] for r in rows if 5050<r['state']['simulation']['player']['x']<5230 and abs(r['state']['simulation']['player']['y']+4830.8)<.01)
                result.update(landing_tick=landing(trace['snapshots']),normal_landing_tick=landing(nominal['snapshots']))
                self.assertLess(result['landing_tick'],result['normal_landing_tick']);result['shortcut_faster']=True
            self.evidence.write('clips/'+name+'/result.json',result)
            print('PASS',name,json.dumps(result),flush=True)


class Task474Tests(unittest.TestCase):
    """Deflector Works opening: connected trusted-input ascent and physical misses."""
    task_id = 'TASK-474'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_04_source_hashes = Task465Tests.test_03_source_hashes

    @staticmethod
    def flat_plan(hold=45):
        return [(30,'mousedown',4790,-5200),(30+hold,'mouseup',4790,-5200),
                (115,'mousedown',5100,-4980),(175,'mouseup',5100,-4980)]

    def replay(self, name, plan, ticks, bounds, start=(5150,-4830.8), bounces=()):
        from grapple_over_verify import metadata, execute, check_trace
        page=self.open();level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
            player=dict(x=start[0],y=start[1],speedX=0,speedY=0)),
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks,expected_exit=bounds,required_events=['acquisition','release'])
        m['metadata']['compact_contacts']=True
        if getattr(self, 'snapshot_contacts', False):
            m['metadata']['snapshot_contacts']=True
        prefix='encounters/'+name
        self.evidence.write(prefix+'/input.json',m)
        trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=True)
        check_trace(m,trace)
        replay=execute(m,self.browser,self.url,str(self.evidence.path(prefix+'/replay')))
        check_trace(m,replay);self.assertEqual(trace,replay)
        self.assertEqual(len(trace['metadata']['setupOnlySpawns']),1)
        reflections=[e for e in trace['events'] if e['type']=='bounce']
        self.assertEqual([e['contact']['elementId'] for e in reflections],list(bounces))
        for e in reflections:
            before=e['before']['simulation']['player'];after=e['after']['simulation']['player']
            if e['contact']['elementId']=='S04-flat-press':
                self.assertLess(before['speedX'],0);self.assertGreater(after['speedX'],0)
                self.assertAlmostEqual(before['speedX'],-after['speedX'])
                self.assertAlmostEqual(before['speedY'],after['speedY'])
            else:
                self.assertLess(before['speedY'],0);self.assertGreater(after['speedY'],0)
                self.assertGreater(before['speedX'],0);self.assertLess(after['speedX'],0)
                self.assertAlmostEqual(abs(e['contact']['nx']),1/(5**.5))
        sightlines=[]
        for e in trace['events']:
            if e['type']=='input' and e['event']=='mousedown':
                self.assertTrue(e['trusted'])
                self.assertTrue(0<e['client']['x']<1280 and 0<e['client']['y']<720)
                sightlines.append(dict(tick=e['tick'],world=e['world'],client=e['client']))
        self.evidence.write(prefix+'/result.json',dict(passed=True,matching_traces=True,
            trusted_inputs=True,no_traversal_mutation=True,reflections=reflections,
            final=trace['snapshots'][-1]['state']['simulation']['player'],camera_sightlines=sightlines,
            scope='One labeled setup placement; production physics and real mouse input thereafter'))
        return trace

    def test_01_geometry(self):
        page=self.open()
        r=page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))}}''')
        m=r['manifest'];self.assertEqual(m['sections'][3]['status'],'partial')
        self.assertEqual([e['status'] for e in m['encounters'][12:16]],['built','built','planned','planned'])
        self.assertEqual(r['runtime']['elements'],m['geometry']['elements'])
        for a,e in zip(r['colliders'],m['geometry']['elements']):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
        machinery=[e for e in m['geometry']['elements'] if e['id'].startswith('S04')]
        self.assertEqual(len(machinery),6)
        self.assertEqual(sum(e['role']=='bounce' for e in machinery),2)
        self.assertEqual(len({json.dumps(e['points']) for e in machinery}),6)
        self.assertEqual([c['status'] for c in m['connectors'][12:14]],['built','built'])
        self.assertIsNone(r['runtime']['finish'])
        for e in machinery:
            self.assertTrue(all(-6480<=e['y']+p['y']<=-4860 for p in e['points'])
                            or e['id'] in ('S04-catch-basin','S04-lower-stair'))
        calibration=json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        r.update(self.proof,structural_validations_pass=True,encounters=m['encounters'][12:14],
            calibration_reference='artifacts/TASK-463/calibration.json',calibrated_physics_unchanged=True,
            surface_roles={e['id']:e['role'] for e in machinery},
            landing_margins={'S04-rest':{'safe_center':[5090.8,5389.2],'top':-5000},
                             'S04-test-exit':{'safe_center':[4970.8,5069.2],'top':-5250}},
            camera_sightlines='Measured trusted press coordinates in encounters/*/result.json; all inside viewport',
            band_note='Machinery in S04 3R band; basin/stair overlap preceding band for physical recovery',
            temporary_exit='S04-test-exit; S04-03/04 remain planned; no finish trigger')
        self.evidence.write('geometry.json',r)
        print('PASS geometry: S04-01/02; structural_validations_pass; matching colliders; starts/exits; surface roles; landing margins; camera sightlines; calibration unchanged')

    def test_02_connected_nominal(self):
        first=self.replay('S04-01',self.flat_plan(),375,
            dict(x=[5090,5092],y=[-5011,-5010],speedX=[-.001,.001]),bounces=['S04-flat-press'])
        route=self.replay('S04-02-connected',self.flat_plan()+[
            (405,'mousedown',5150,-5430),(460,'mouseup',5150,-5430)],700,
            dict(x=[4970,4972],y=[-5261,-5260],speedX=[-.001,.001],speedY=[-.001,.001]),
            bounces=['S04-flat-press','S04-angled-chute'])
        self.assertEqual(first['snapshots'][375]['state'],route['snapshots'][375]['state'])
        print('PASS S04-01/02 connected: flat horizontal reversal; angled momentum redirect; safe temporary exit; visible targets; matching trusted-input replays; no traversal mutation')

    def test_03_failure_recovery(self):
        self.replay('flat-short-return',self.flat_plan(25),375,
            dict(x=[5051,5229],y=[-4831,-4830]),bounces=[])
        self.replay('flat-basin',self.flat_plan(35),375,
            dict(x=[4811,4989.2],y=[-4811,-4810]),bounces=['S04-flat-press'])
        recovery=self.replay('basin-rejoin',self.flat_plan(35)+[
            (375,'mousedown',5100,-4980),(420,'mouseup',5100,-4980)],560,
            dict(x=[5051,5229],y=[-4831,-4830]),bounces=['S04-flat-press'])
        self.assertAlmostEqual(recovery['snapshots'][375]['state']['simulation']['player']['y'],-4810.8,places=5)
        self.replay('angle-short-return',[(30,'mousedown',5150,-5430),(45,'mouseup',5150,-5430)],300,
            dict(x=[5090,5390],y=[-5011,-5010]),start=(5090.8000001,-5010.8000001),bounces=[])
        print('PASS failure/recovery: flat short release returns to Viaduct; mistimed reflection caught by basin and physically rejoined Viaduct; angled short release returns to rest; physical falls without relocation; matching replays')


class Task475Tests(unittest.TestCase):
    """Completed Works: production input, measured reflections, exits and recovery."""
    task_id = 'TASK-475'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    flat_plan = staticmethod(Task474Tests.flat_plan)
    test_06_source_hashes = Task465Tests.test_03_source_hashes

    def replay(self, name, plan, ticks, bounds, start=(5150,-4830.8), bounces=()):
        from grapple_over_verify import metadata, execute, check_trace
        page=self.open();level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
            player=dict(x=start[0],y=start[1],speedX=0,speedY=0)),
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks,expected_exit=bounds,required_events=['acquisition','release'])
        m['metadata']['compact_contacts']=True
        if getattr(self, 'snapshot_contacts', False):
            m['metadata']['snapshot_contacts']=True
        prefix='encounters/'+name
        self.evidence.write(prefix+'/input.json',m)
        trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=name in ('S04-04','section-exit'))
        check_trace(m,trace)
        replay=execute(m,self.browser,self.url,str(self.evidence.path(prefix+'/replay')))
        check_trace(m,replay);self.assertEqual(trace,replay)
        self.assertEqual(len(trace['metadata']['setupOnlySpawns']),1)
        reflections=[e for e in trace['events'] if e['type']=='bounce']
        self.assertEqual([e['contact']['elementId'] for e in reflections],list(bounces))
        sightlines=[]
        for e in trace['events']:
            if e['type']=='input' and e['event'] in ('mousedown','touchstart'):
                self.assertTrue(e['trusted'])
                self.assertTrue(0<e['client']['x']<1280 and 0<e['client']['y']<720)
                sightlines.append(dict(tick=e['tick'],world=e['world'],client=e['client']))
        self.evidence.write(prefix+'/result.json',dict(passed=True,matching_traces=True,
            trusted_inputs=True,no_traversal_mutation=True,reflections=reflections,
            final=trace['snapshots'][-1]['state']['simulation']['player'],camera_sightlines=sightlines,
            scope='One labeled setup placement; production physics and real mouse input thereafter'))
        return trace


    def test_01_geometry(self):
        page=self.open()
        r=page.evaluate("""() => {const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))}}""")
        m=r['manifest'];elements=m['geometry']['elements']
        self.assertEqual(m['sections'][3]['status'],'built')
        self.assertEqual([e['status'] for e in m['encounters'][12:16]],['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][12:16]],['built']*4)
        self.assertEqual(r['runtime']['elements'],elements)
        for a,e in zip(r['colliders'],elements):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
        self.assertIsNone(r['runtime']['finish'])
        prior=json.loads((ROOT/'artifacts/TASK-474/geometry.json').read_text())['manifest']
        lower=lambda manifest: [e for e in manifest['geometry']['elements'] if not e['id'].startswith('S04')]
        self.assertEqual(lower(m),lower(prior))
        calibration=json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        self.assertNotIn('S04-test-exit',[e['id'] for e in elements])
        self.assertFalse(any(e['id'].startswith('S04') for e in m['shortcuts']))
        roles={'S04-01 flat reflection':['S04-flat-press'],
            'S04-02 angled reflection':['S04-angled-chute'],
            'S04-03 bounce + new grapple':['S04-combination-press','S04-combination-rest'],
            'S04-04 two-bounce transfer':['S04-double-left','S04-double-right','S04-brake-anchor','S04-double-landing'],
            'ordinary rest / transfer':['S04-rest','S04-transfer-ledge'],
            'recovery to Viaduct':['S04-catch-basin','S04-lower-stair','S03-exit'],
            'authored exit to S05 band':['S04-upper-step','S04-exit']}
        for ids in roles.values():
            self.assertTrue(set(ids)<=set(e['id'] for e in elements))
        self.evidence.write('geometry.json',dict(self.proof,**r,structural_validations_pass=True,
            encounters=m['encounters'][12:16],surface_roles=roles,no_temporary_exit=True,
            shortcut='Not assigned to section 4; section 3 normal/shortcut unchanged',
            recovery='Catch basin and lower stair physically rejoin S03-exit',
            connector='S04-exit top -6480; S05 remains planned; no checkpoint or summit trigger'))
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1400" viewBox="4100 -6800 1900 2250" style="background:#182028">']
        colors=['#55dc89','#55dc89','#75e0a0','#8cf0b0','#d6dfdf','#84b8da','#e0c88d']
        for (role,ids),color in zip(roles.items(),colors):
            for e in elements:
                if e['id'] in ids:
                    points=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                    parts.append(f'<polygon points="{points}" fill="{color}" stroke="#141820" stroke-width="3"/><text x="{e["x"]-15}" y="{e["y"]+80}" fill="white" font-size="19">{e["id"]} ({e["role"]})</text>')
        for i,role in enumerate(roles):
            parts.append(f'<text x="5480" y="{-6670+i*65}" fill="{colors[i]}" font-size="21">{role}</text>')
        parts.append('</svg>');page.set_content(''.join(parts));page.set_viewport_size(dict(width=1200,height=1400))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S04-01 S04-02 S04-03 S04-04 built; distinct roles; rest; exit; recovery; no assigned shortcut; no temporary exit; overview.png')

    def test_02_opening_preserved(self):
        self.replay('opening',self.flat_plan()+[(405,'mousedown',5150,-5430),(460,'mouseup',5150,-5430)],700,
            dict(x=[4970,4972],y=[-5261,-5260],speedX=[-.001,.001]),
            bounces=['S04-flat-press','S04-angled-chute'])
        print('PASS opening: both earlier reflections and transfer ledge preserved')

    def test_03_bounce_new_grapple(self):
        plan=[(30,'mousedown',4610,-5630),(75,'mouseup',4610,-5630),
              (130,'mousedown',4820,-5510),(190,'mouseup',4820,-5510)]
        for mode in ('mouse','touch'):
            inputs=plan if mode=='mouse' else [(t,{'mousedown':'touchstart','mouseup':'touchend'}[e],x,y) for t,e,x,y in plan]
            trace=self.replay('S04-03-'+mode,inputs,375,dict(x=[4810,4980],y=[-5550,-5540]),
                start=(4970.8000001,-5260.8000001),bounces=['S04-combination-press'])
            bounce=next(e for e in trace['events'] if e['type']=='bounce')
            grab=next(e for e in trace['events'] if e['type']=='acquisition' and e['after']['rope'][0]['id']=='S04-combination-rest')
            self.assertGreater(grab['tick'],bounce['tick'])
            self.assertLess(grab['after']['simulation']['player']['y'],-5540.8)
        print('PASS S04-03: reflection precedes airborne new grapple; rest reached with mouse and touch')

    def test_04_double_bounce_exit(self):
        self.replay('S04-04',[(30,'mousedown',5170,-5910),(75,'mouseup',5170,-5910),
            (140,'mousedown',4810,-5710),(180,'mouseup',4810,-5710)],250,
            dict(x=[4990,5050],y=[-5791,-5790]),start=(4850.8000001,-5540.8000001),
            bounces=['S04-double-right','S04-double-left'])
        self.replay('section-exit',[(30,'mousedown',4890,-6090),(105,'mouseup',4890,-6090),
            (140,'mousedown',4650,-6520),(235,'mouseup',4650,-6520),
            (240,'mousedown',4560,-6460),(275,'mouseup',4560,-6460)],450,
            dict(x=[4510,4610],y=[-6491,-6490],speedX=[-.001,.001],speedY=[-.001,.001]),
            start=(4991.267526379214,-5790.8000001))
        print('PASS S04-04: two consecutive reflections and landing; traversed section exit at -6480; next unbuilt section not required')

    def test_05_local_miss_recovery(self):
        trace=self.replay('local-miss-recovery',self.flat_plan(35)+[
            (375,'mousedown',5100,-4980),(420,'mouseup',5100,-4980)],560,
            dict(x=[5051,5229],y=[-4831,-4830]),bounces=['S04-flat-press'])
        self.assertAlmostEqual(trace['snapshots'][375]['state']['simulation']['player']['y'],-4810.8,places=5)
        print('PASS local miss: catch basin at tick 375; physical recovery to Viaduct by tick 560; no relocation')


class Task476Tests(unittest.TestCase):
    """S04 isolated encounter tolerance; trusted inputs and unchanged physics."""
    task_id = 'TASK-476'
    setUpClass = classmethod(Task467Tests.setUpClass.__func__)
    test_03_source_hashes = Task467Tests.test_02_source_hashes
    run_attempt = Task473Tests.run_attempt

    @staticmethod
    def routes():
        return [
            ('S04-01', (5150,-4830.8), Task474Tests.flat_plan(), 375,
             dict(x=[5090,5390],y=[-5011,-5010]), 0, (0,1), ['S04-flat-press']),
            ('S04-02', (5090.8000001,-5010.8000001),
             [(30,'mousedown',5150,-5430),(85,'mouseup',5150,-5430)], 325,
             dict(x=[4970,5070],y=[-5261,-5260]), 0, (2/5**.5,1/5**.5), ['S04-angled-chute']),
            ('S04-03', (4970.8000001,-5260.8000001),
             [(30,'mousedown',4610,-5630),(75,'mouseup',4610,-5630),
              (130,'mousedown',4820,-5510),(190,'mouseup',4820,-5510)], 375,
             dict(x=[4810,4980],y=[-5550,-5540]), 2, (0,1), ['S04-combination-press']),
            ('S04-04', (4850.8000001,-5540.8000001),
             [(30,'mousedown',5170,-5910),(75,'mouseup',5170,-5910),
              (140,'mousedown',4810,-5710),(180,'mouseup',4810,-5710)], 375,
             dict(x=[4880,5050],y=[-5821,-5790],speedX=[-.05,.05],speedY=[-.001,.001]), 0, (0,1), ['S04-double-right','S04-double-left'])]

    def make_input(self, route, device='desktop', delta=0, offset=0):
        from grapple_over_verify import metadata
        _,start,plan,ticks,bounds,critical,tangent,_=route
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=self.level,
            player=dict(x=start[0],y=start[1],speedX=0,speedY=0)),inputs=[],
            ticks=ticks,expected_exit=bounds,required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts']=True
        if device=='touch': m['metadata']['viewport']=dict(width=844,height=390)
        for i,(tick,event,x,y) in enumerate(plan):
            if route[0]=='S04-04' and device=='touch' and i==3: tick=185
            if i==critical:
                tick+=delta;x+=offset*tangent[0];y+=offset*tangent[1]
            if device=='touch': event={'mousedown':'touchstart','mouseup':'touchend'}[event]
            m['inputs'].append(dict(tick=tick,event=event,world=dict(x=x,y=y)))
        return m

    def load_level(self):
        page=self.browser.new_page(viewport=VIEWPORT);page.goto(self.url);wait_for_boot(page)
        self.level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s04_mechanics
        self.load_level()
        suite=dict(section='S04',source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated encounter starts only; not continuous completion',encounters={},
            negative_control='negative-control.json',recovery='clips/recovery/input.json',
            earlier_attempts='exploratory/manifest.json',
            shortcuts='none assigned or observed; no shortcut completion claim')
        failures=[]
        for route in self.routes():
            encounter=route[0];attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    m=self.make_input(route,device,delta,offset)
                    trace,success,reason=self.run_attempt(m,prefix,variant=='nominal')
                    mechanics=check_s04_mechanics(encounter,trace,required=success)
                    attempts.append(dict(name=name,device=device,variant=variant,critical_input_index=route[5],
                        timing_delta=delta,tangent_aim_delta=offset,surface_tangent=route[6],
                        input=prefix+'/input.json',trace=prefix+'/trace.json',success=success,reason=reason,
                        mechanic_events=mechanics,final=trace['snapshots'][-1]['state']['simulation']['player']))
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2: failures.append(encounter+' '+device)
        m=self.make_input(self.routes()[1]);m['inputs']=[]
        trace,success,reason=self.run_attempt(m,'clips/negative',True)
        self.assertFalse(success);self.assertIn('expected exit mismatch',reason)
        self.evidence.write('negative-control.json',dict(name='angle/bounce: omit critical chute acquisition',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=True,
            unchanged_physics=True,source_hashes=hashes(),reason=reason,
            scope='Same isolated launch and duration, acquisition omitted; alternative solutions are not ruled out.',
            final=trace['snapshots'][-1]['state']['simulation']['player']))
        self.assertEqual(failures,[])
        print('PASS S04 four encounters: both viewports nominal + >=2/4 variants; flat/sloped bounce; airborne reacquisition; two distinct contacts; omitted acquisition fails exit')

    def test_02_recovery(self):
        from grapple_over_verify import execute
        self.load_level()
        route=list(self.routes()[0]);route[2]=Task474Tests.flat_plan(35)+[
            (375,'mousedown',5100,-4980),(420,'mouseup',5100,-4980)]
        route[3]=560;route[4]=dict(x=[5051,5229],y=[-4831,-4830])
        m=self.make_input(route)
        trace,success,reason=self.run_attempt(m,'clips/recovery',True)
        self.assertTrue(success,reason)
        self.assertAlmostEqual(trace['snapshots'][375]['state']['simulation']['player']['y'],-4810.8,places=5)
        replay=execute(m,self.browser,self.url,str(self.evidence.path('clips/recovery/replay')))
        self.assertEqual(trace,replay)
        self.evidence.write('clips/recovery/result.json',dict(passed=True,matching_traces=True,
            physical_catch_tick=375,physical_rejoin_S03=True,no_relocation=True))
        print('PASS recovery: actual missed landing, basin catch tick 375, physical rejoin S03; matching replay')

    def test_04_scoped_geometry(self):
        page=self.browser.new_page(viewport=VIEWPORT);page.goto(self.url);wait_for_boot(page)
        r=page.evaluate("""() => ({manifest:GRAPPLE_OVER_MOUNTAIN,
            colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))})""")
        page.close()
        prior=json.loads((ROOT/'artifacts/TASK-475/geometry.json').read_text())['manifest']
        old={e['id']:e for e in prior['geometry']['elements']}
        changed=[]
        for e,a in zip(r['manifest']['geometry']['elements'],r['colliders']):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
            if e!=old[e['id']]: changed.append(e['id'])
        self.assertEqual(changed,['S04-double-landing'])
        self.assertEqual(len(old),len(r['colliders']))
        self.evidence.write('geometry.json',dict(only_landing_changed=True,colliders_match=True,
            changed=changed,landing=next(e for e in r['manifest']['geometry']['elements'] if e['id']==changed[0]),
            prior_reference='artifacts/TASK-475/geometry.json'))
        print('PASS geometry: only S04-double-landing changed; visible polygon matches collider; other sections preserved')


class Task477Tests(unittest.TestCase):
    """Cable Galleries opening: real corner wraps, connected ascent and falls."""
    task_id = 'TASK-477'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task474Tests.replay
    test_04_source_hashes = Task465Tests.test_03_source_hashes

    @staticmethod
    def opening():
        return [(30,'mousedown',4655,-6780),(120,'mouseup',4655,-6780)]

    def test_01_geometry(self):
        page=self.open()
        r=page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))}}''')
        m=r['manifest'];self.assertEqual(m['sections'][4]['status'],'partial')
        self.assertEqual([e['status'] for e in m['encounters'][16:20]],['built','built','planned','planned'])
        self.assertEqual(r['runtime']['elements'],m['geometry']['elements'])
        for a,e in zip(r['colliders'],m['geometry']['elements']):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
        elements=[e for e in m['geometry']['elements'] if e['id'].startswith('S05')]
        self.assertEqual(len(elements),4)
        self.assertEqual(len({json.dumps(e['points']) for e in elements}),3)
        for e in elements:
            self.assertEqual(e['role'],'solid')
            self.assertTrue(all(-8100<=e['y']+p['y']<=-6480 for p in e['points']))
        self.assertEqual([c['status'] for c in m['connectors'][16:18]],['built','built'])
        self.assertIsNone(r['runtime']['finish'])
        old=subprocess.check_output(['git','show','HEAD:mountain.js'],cwd=ROOT,text=True)
        previous=page.evaluate('(s)=>{return new Function(s+";return GRAPPLE_OVER_MOUNTAIN")()}',old)
        self.assertEqual([e for e in m['geometry']['elements'] if not e['id'].startswith('S05')],[e for e in previous['geometry']['elements'] if not e['id'].startswith('S05')])
        calibration=json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        r.update(self.proof,structural_validations_pass=True,encounters=m['encounters'][16:18],
            calibration_reference='artifacts/TASK-463/calibration.json',calibrated_physics_unchanged=True,
            previous_sections_unchanged=True,surface_roles={e['id']:e['role'] for e in elements},
            landing_margins={'S05-01':{'safe_center':[4660.8,4839.2],'top':-6800},
                             'S05-02':{'safe_center':[5010.8,5239.2],'top':-7100}},
            camera_sightlines='Measured trusted press coordinates in encounters/*/result.json; all inside viewport',
            temporary_exit='Top of S05-deep-overhang, with end stop; S05-03/04 remain planned',
            recovery='Open shaft to S04-upper-step; physical grapple to S04-exit')
        self.evidence.write('geometry.json',r)
        print('PASS geometry: S05-01/02; structural_validations_pass; matching colliders; starts/exits; surface roles; landing margins; camera sightlines; calibration unchanged')

    def assert_wrap_pull(self,trace,element,after=0):
        wrap=next(e for e in trace['events'] if e['type']=='wrap' and e['tick']>after
                  and e['after']['rope'][-1]['id']==element)
        rope=wrap['after']['rope'];self.assertGreaterEqual(len(rope),2)
        self.assertNotEqual((rope[0]['x'],rope[0]['y']),(rope[-1]['x'],rope[-1]['y']))
        release=next(e for e in trace['events'] if e['type']=='release' and e['tick']>wrap['tick'])
        self.assertGreaterEqual(release['tick']-wrap['tick'],3)
        before=wrap['after']['simulation']['player'];end=release['before']['simulation']['player']
        self.assertGreater(end['x'],before['x'])
        self.assertGreater(end['x'],rope[-1]['x'])
        return dict(element=element,wrap_tick=wrap['tick'],release_tick=release['tick'],
                    corner=rope[-1],wrapped_pull_ticks=release['tick']-wrap['tick'],
                    moved_around_corner=True)

    def test_02_connected_nominal(self):
        first=self.replay('S05-01',self.opening(),500,
            dict(x=[4839,4840],y=[-6811,-6810],speedX=[-.001,.001],speedY=[-.001,.001]),start=(4530,-6490.8))
        connected=self.replay('S05-02-connected',self.opening()+[
            (530,'mousedown',5005,-7080),(620,'mouseup',5005,-7080)],950,
            dict(x=[5239,5240],y=[-7111,-7110],speedX=[-.001,.001],speedY=[-.001,.001]),start=(4530,-6490.8))
        self.assertEqual(first['snapshots'][500]['state'],connected['snapshots'][500]['state'])
        observations=[self.assert_wrap_pull(first,'S05-projecting-girder'),
                      self.assert_wrap_pull(connected,'S05-deep-overhang',500)]
        self.evidence.write('encounters/wrapped-pull.json',dict(passed=True,observations=observations,
            connected_from='S04-exit',temporary_exit_reached=True,no_traversal_mutation=True))
        print('PASS S05-01/02: connected from Works exit; projecting corner wrap; wrapped-segment pull around obstruction; safe temporary exit; matching trusted-input replays')

    def test_03_failure_recovery(self):
        self.replay('short-return',[(30,'mousedown',4655,-6780),(38,'mouseup',4655,-6780)],500,
            dict(x=[4510,4610],y=[-6491,-6490]),start=(4530,-6490.8))
        shaft=[(30,'mousedown',4670,-6710),(50,'mouseup',4670,-6710)]
        self.replay('shaft-fall',shaft,500,dict(x=[4729,4730],y=[-6241,-6240]),start=(4530,-6490.8))
        self.replay('shaft-recovery',shaft+[(530,'mousedown',4660,-6505),(615,'mouseup',4660,-6505),
            (625,'mousedown',4560,-6460),(660,'mouseup',4560,-6460)],850,
            dict(x=[4510,4610],y=[-6491,-6490]),start=(4530,-6490.8))
        print('PASS failure/recovery: short release returns to Works exit; open shaft fall lands on Works upper step; reachable anchors physically rejoin entrance; no relocation')


class Task478Tests(unittest.TestCase):
    """Completed Galleries: physical transfers, recessed ceiling and departure."""
    task_id = 'TASK-478'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task474Tests.replay
    test_05_source_hashes = Task465Tests.test_03_source_hashes
    test_04_failure_recovery = Task477Tests.test_03_failure_recovery

    def test_01_geometry(self):
        page=self.open()
        r=page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))}}''')
        m=r['manifest']
        self.assertEqual(m['sections'][4]['status'],'built')
        self.assertEqual([e['status'] for e in m['encounters'][16:20]],['built']*4)
        self.assertEqual([e['status'] for e in m['connectors'][16:20]],['built']*4)
        self.assertEqual(r['runtime']['elements'],m['geometry']['elements'])
        for a,e in zip(r['colliders'],m['geometry']['elements']):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
        prior=json.loads((ROOT/'artifacts/TASK-477/geometry.json').read_text())['manifest']
        lower=lambda model:[e for e in model['geometry']['elements'] if not e['id'].startswith('S05')]
        self.assertEqual(lower(m),lower(prior))
        self.assertEqual(m['shortcuts'],prior['shortcuts'])
        self.assertIsNone(r['runtime']['finish'])
        self.assertFalse(any(e['exit'].get('temporary') for e in m['encounters'][16:20]))
        elements=[e for e in m['geometry']['elements'] if e['id'].startswith(('S05','S04-exit','S04-upper-step'))]
        roles={'S05-01 projecting corner':['S05-projecting-girder'],
            'S05-02 deep overhang':['S05-deep-overhang'],
            'S05-03 release / reacquire':['S05-transfer-canopy'],
            'S05-04 recessed ceiling':['S05-recessed-ceiling'],
            'ordinary rests':['S05-rest','S05-lower-gallery','S05-upper-rest'],
            'exit to next band':['S05-exit'],
            'lower shaft recovery':['S04-exit','S04-upper-step']}
        self.assertEqual(set(sum(roles.values(),[])),{e['id'] for e in elements})
        silhouettes=[next(e['points'] for e in elements if e['id']==ids[0]) for ids in list(roles.values())[:4]]
        self.assertEqual(len({json.dumps(p) for p in silhouettes}),4)
        calibration=json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        self.evidence.write('geometry.json',dict(self.proof,**r,structural_validations_pass=True,
            encounters=m['encounters'][16:20],surface_roles=roles,no_temporary_exit=True,
            previous_sections_unchanged=True,calibrated_physics_unchanged=True,
            shortcut='None assigned to section 5; section 3 preserved',
            recovery='Visible lower shaft to S04-upper-step; grapple back to S04-exit',
            connector='S05-exit top -8070; next band remains planned'))
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="1500" viewBox="4300 -8300 2400 2400" style="background:#182028">']
        colors=['#69cfee','#7b9bef','#b799ee','#edba7c','#d6dfdf','#e4df7a','#80cba0']
        for (role,ids),color in zip(roles.items(),colors):
            for e in elements:
                if e['id'] in ids:
                    points=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                    parts.append(f'<polygon points="{points}" fill="{color}" stroke="#141820" stroke-width="3"/><text x="{e["x"]-20}" y="{e["y"]-35}" fill="white" font-size="22">{e["id"]} ({e["role"]})</text>')
        for i,role in enumerate(roles):
            parts.append(f'<text x="4350" y="{-8180+i*55}" fill="{colors[i]}" font-size="26">{role}</text>')
        parts.append('<path d="M 4930 -6660 L 4780 -6350" fill="none" stroke="#80cba0" stroke-width="7"/><text x="4850" y="-6400" fill="#80cba0" font-size="24">open recovery shaft</text></svg>')
        page.set_content(''.join(parts));page.set_viewport_size(dict(width=1300,height=1500))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S05-01 S05-02 S05-03 S05-04 built; distinct surface roles; rest; exit; recovery; no assigned shortcut; no temporary exit; overview.png')

    @staticmethod
    def transfer_plan():
        return [(30,'mousedown',5425,-7380),(116,'mouseup',5425,-7380),
                (117,'mousedown',5500,-7400),(145,'mouseup',5500,-7400)]

    def transfer_observation(self,trace):
        acquisitions=[e for e in trace['events'] if e['type']=='acquisition']
        self.assertEqual(len(acquisitions),2)
        release=next(e for e in trace['events'] if e['type']=='release')
        reacquire=acquisitions[1];p=reacquire['before']['simulation']['player']
        self.assertLess(release['tick'],reacquire['tick'])
        self.assertGreater(p['x'],5420)
        self.assertLess(p['y']+p['radius'],-7400)
        self.assertTrue(all(e['after']['rope'][0]['id']=='S05-transfer-canopy' for e in acquisitions))
        self.assertNotEqual(acquisitions[0]['after']['rope'][0],acquisitions[1]['after']['rope'][0])
        return dict(passed=True,release_tick=release['tick'],reacquire_tick=reacquire['tick'],
            beyond_overhang_airborne=True,distinct_anchor_points=True,player=p)

    def test_02_release_reacquire(self):
        trace=self.replay('S05-03',self.transfer_plan(),500,
            dict(x=[5639,5640],y=[-7411,-7410]),start=(5239.2,-7110.8))
        self.evidence.write('encounters/S05-03/mechanics.json',self.transfer_observation(trace))
        print('PASS S05-03: release then distinct-anchor reacquisition beyond overhang while airborne; safe landing; matching trusted-input replay')

    def test_03_ceiling_and_exit(self):
        plan=[(30,'mousedown',5805,-7700),(130,'mouseup',5805,-7700),
              (680,'mousedown',6205,-8050),(775,'mouseup',6205,-8050)]
        trace=self.replay('S05-04-exit',plan,1100,
            dict(x=[6210,6390],y=[-8081,-8080],speedY=[-.001,.001]),start=(5639.2,-7410.8))
        p=trace['snapshots'][650]['state']['simulation']['player']
        self.assertAlmostEqual(p['y'],-7730.8,places=5)
        self.assertGreater(p['x'],6000)
        wrap=next(e for e in trace['events'] if e['type']=='wrap' and e['after']['rope'][-1]['id']=='S05-recessed-ceiling')
        self.assertGreaterEqual(len(wrap['after']['rope']),2)
        self.assertTrue(any(e['type']=='acquisition' and e['after']['rope'][0]['id']=='S05-exit' for e in trace['events']))
        self.evidence.write('encounters/S05-04-exit/mechanics.json',dict(passed=True,
            ceiling_corner_wrap_tick=wrap['tick'],ceiling_traversed=p,section_exit_traversed=True,
            next_unbuilt_section_not_required=True))
        print('PASS S05-04: recessed ceiling corner wrap and traversal; section exit traversed; matching trusted-input replay; next unbuilt section not required')

    def test_06_touch(self):
        from grapple_over_verify import metadata,execute,check_trace
        page=self.open();level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)');page.close()
        for name,start,plan,ticks,bounds in [
            ('S05-03-touch',(5239.2,-7110.8),self.transfer_plan(),500,dict(x=[5639,5640],y=[-7411,-7410])),
            ('S05-04-touch',(5639.2,-7410.8),[(30,'mousedown',5805,-7700),(130,'mouseup',5805,-7700)],650,dict(x=[6019,6020],y=[-7731,-7730]))]:
            m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
                player=dict(x=start[0],y=start[1],speedX=0,speedY=0)),
                inputs=[dict(tick=t,event={'mousedown':'touchstart','mouseup':'touchend'}[e],world=dict(x=x,y=y)) for t,e,x,y in plan],
                ticks=ticks,expected_exit=bounds,required_events=['acquisition','release'])
            m['metadata'].update(compact_contacts=True,viewport=dict(width=844,height=390))
            prefix='encounters/'+name
            self.evidence.write(prefix+'/input.json',m)
            trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=True)
            check_trace(m,trace)
            if name=='S05-03-touch': self.transfer_observation(trace)
            self.evidence.write(prefix+'/result.json',dict(passed=True,trusted_inputs=True,
                viewport=m['metadata']['viewport'],final=trace['snapshots'][-1]['state']['simulation']['player']))
        print('PASS touch: S05-03 airborne reacquisition and S05-04 ceiling traversal; trusted touch input; 844x390')


class Task479Tests(unittest.TestCase):
    """Cable Galleries tolerance from labeled isolated starts, with real input."""
    task_id = 'TASK-479'
    setUpClass = classmethod(Task467Tests.setUpClass.__func__)
    load_level = Task476Tests.load_level
    run_attempt = Task473Tests.run_attempt
    make_input = Task476Tests.make_input
    test_03_source_hashes = Task467Tests.test_02_source_hashes

    @staticmethod
    def routes():
        return [
            ('S05-01', (4530,-6490.8), Task477Tests.opening(), 500,
             dict(x=[4839,4840],y=[-6811,-6810]), 0, (0,1), []),
            ('S05-02', (4839.2,-6810.8),
             [(30,'mousedown',5005,-7080),(120,'mouseup',5005,-7080)], 500,
             dict(x=[5239,5240],y=[-7111,-7110]), 0, (0,1), []),
            ('S05-03', (5239.2,-7110.8), Task478Tests.transfer_plan(), 500,
             dict(x=[5639,5640],y=[-7411,-7410]), 0, (0,1), []),
            ('S05-04', (5639.2,-7410.8),
             [(30,'mousedown',5805,-7700),(130,'mouseup',5805,-7700),
              (680,'mousedown',6205,-8050),(775,'mouseup',6205,-8050)], 1100,
             dict(x=[6210,6390],y=[-8081,-8080]), 0, (0,1), [])]

    def input_for(self, route, device='desktop', delta=0, offset=0):
        m=self.make_input(route,device,delta,offset)
        m['required_events']=['acquisition','release','wrap']
        m['metadata']['snapshot_contacts']=True
        return m

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s05_mechanics
        self.load_level()
        suite=dict(section='S05',source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated encounter placement only; not continuous completion',encounters={},
            negative_control='negative-control.json',recovery='clips/recovery/input.json',
            shortcuts='none assigned or observed; no shortcut completion claim')
        failures=[]
        for route in self.routes():
            encounter=route[0];attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    m=self.input_for(route,device,delta,offset)
                    trace,success,reason=self.run_attempt(m,prefix,variant=='nominal')
                    mechanics=check_s05_mechanics(encounter,trace,required=False)
                    if success:
                        try: check_s05_mechanics(encounter,trace)
                        except ValueError as error: success=False;reason=str(error)
                    attempts.append(dict(name=name,device=device,variant=variant,critical_input_index=0,
                        timing_delta=delta,tangent_aim_delta=offset,surface_tangent=route[6],
                        input=prefix+'/input.json',trace=prefix+'/trace.json',success=success,reason=reason,
                        mechanic_events=mechanics,final=trace['snapshots'][-1]['state']['simulation']['player']))
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2:
                    failures.append(encounter+' '+device)
        m=self.input_for(self.routes()[0]);m['inputs'][1]['tick']=38
        trace,success,reason=self.run_attempt(m,'clips/negative',True)
        self.evidence.write('negative-control.json',dict(name='wrapping/reacquisition: early release before corner',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=not success,
            unchanged_physics=True,source_hashes=hashes(),reason=reason,
            scope='Same launch and duration with release advanced from tick 120 to 38; alternative solutions are not ruled out.'))
        self.assertFalse(success);self.assertIn('expected exit mismatch',reason)
        self.assertEqual(failures,[])
        print('PASS S05 four encounters: both viewports nominal + >=2/4 variants; rope segment insertion; corner-directed pull; release; new acquisition; early release fails exit')

    def test_02_recovery(self):
        from grapple_over_verify import execute
        self.load_level()
        route=list(self.routes()[0]);route[2]=[
            (30,'mousedown',4670,-6710),(50,'mouseup',4670,-6710),
            (530,'mousedown',4660,-6505),(615,'mouseup',4660,-6505),
            (625,'mousedown',4560,-6460),(660,'mouseup',4560,-6460)]
        route[3]=850;route[4]=dict(x=[4510,4610],y=[-6491,-6490])
        m=self.input_for(route);m['required_events']=['acquisition','release']
        trace,success,reason=self.run_attempt(m,'clips/recovery',True)
        self.assertTrue(success,reason)
        self.assertAlmostEqual(trace['snapshots'][500]['state']['simulation']['player']['y'],-6240.8,places=5)
        replay=execute(m,self.browser,self.url,str(self.evidence.path('clips/recovery/replay')))
        self.assertEqual(trace,replay)
        self.evidence.write('clips/recovery/result.json',dict(passed=True,matching_traces=True,
            physical_catch_tick=500,physical_rejoin_S04=True,no_relocation=True))
        print('PASS recovery: shaft fall onto S04-upper-step; physical rejoin S04-exit; matching replay')


class Task480Tests(unittest.TestCase):
    """Liftworks acquisition and sustained moving attachment, with physical recovery."""
    task_id = 'TASK-480'
    snapshot_contacts = True
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task474Tests.replay
    test_04_source_hashes = Task465Tests.test_03_source_hashes

    def test_01_geometry(self):
        page = self.open()
        page.evaluate('floors=[loadFixedLevel(validateMountainManifest(GRAPPLE_OVER_MOUNTAIN))]')
        r = page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))}}''')
        m = r['manifest']
        self.assertEqual(m['sections'][5]['status'], 'partial')
        self.assertEqual([e['status'] for e in m['encounters'][20:24]], ['built','built','planned','planned'])
        self.assertEqual(r['runtime']['elements'], m['geometry']['elements'])
        for a, e in zip(r['colliders'], m['geometry']['elements']):
            self.assertEqual(a, {k:e[k] for k in ('id','x','y','points','role')})
        elements = [e for e in m['geometry']['elements'] if e['id'].startswith('S06')]
        self.assertEqual(len(elements), 3)
        self.assertEqual(len({json.dumps(e['points']) for e in elements}), 3)
        for e in elements:
            self.assertEqual(e['role'], 'solid')
            self.assertTrue(e['grapplable'])
            self.assertTrue(all(-9720 <= e['y']+p['y'] <= -8100 for p in e['points']))
        self.assertEqual([c['status'] for c in m['connectors'][20:22]], ['built','built'])
        self.assertIsNone(r['runtime']['finish'])
        prior = json.loads((ROOT/'artifacts/TASK-478/geometry.json').read_text())['manifest']
        self.assertEqual([e for e in m['geometry']['elements'] if not e['id'].startswith('S06')], prior['geometry']['elements'])
        calibration = json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        self.evidence.write('geometry.json', dict(self.proof, **r,
            structural_validations_pass=True, calibrated_physics_unchanged=True,
            previous_geometry_unchanged=True, encounters=m['encounters'][20:22],
            surface_roles={e['id']:e['role'] for e in elements},
            landing_margins={'loading_floor_safe_centers':[5790.8,6169.2],
                             'temporary_exit_safe_centers':[5830.8,5989.2]},
            camera_sightlines='Measured target client positions in encounters/*/result.json and filmstrip',
            temporary_exit='S06-test-exit; upper encounters remain planned',
            recovery='Broad loading floor; western edge falls to static S05-recessed-ceiling'))
        print('PASS geometry: S06-01/02; structural_validations_pass; matching colliders; starts/exits; roles; margins; calibration unchanged')

    def test_02_connected_acquisition_reversal_exit(self):
        trace = self.replay('S06-01-02-connected',
            [(30,'mousedown',6110,-8370),(210,'mouseup',6110,-8370)],500,
            dict(x=[5830,5832],y=[-8281,-8280],speedX=[-.001,.001],speedY=[-.001,.001]),
            start=(6300,-8080.8))
        acquired = next(e for e in trace['events'] if e['type']=='acquisition')
        self.assertEqual(acquired['after']['rope'][0]['id'], 'S06-counterweight')
        rows = trace['snapshots'][40:210]
        self.assertTrue(all(r['state']['simulation']['grapple']['grappled'] for r in rows))
        self.assertTrue(all(r['state']['rope'][0]['id']=='S06-counterweight' for r in rows))
        ys = [r['state']['rope'][0]['y'] for r in rows]
        self.assertGreater(max(ys)-min(ys), 100)
        self.assertGreater(ys[60]-ys[0], 0)
        self.assertLess(ys[-1]-ys[90], 0)
        self.evidence.write('encounters/mechanics.json',dict(passed=True,
            S06_01_moving_blue_acquired=True,S06_02_attached_through_reversal=True,
            anchor_vertical_travel=max(ys)-min(ys),acquisition_tick=acquired['tick'],
            connected_from='S05-exit',temporary_exit_reached=True,
            landing_left_margin=trace['snapshots'][-1]['state']['simulation']['player']['x']-5780-10.8,
            no_traversal_mutation=True))
        print('PASS S06-01/02: moving blue acquisition; sustained attachment through reversal; connected from S05; static temporary exit; trusted matching replays')


    def test_03_failure_physical_recovery(self):
        trace = self.replay('missed-exit-floor-and-galleries-recovery',
            [(30,'mousedown',6110,-8370),(300,'mouseup',6110,-8370)],700,
            dict(x=[5444,5445],y=[-7411,-7410]),start=(6300,-8080.8))
        floor = trace['snapshots'][400]['state']['simulation']['player']
        recovered = trace['snapshots'][-1]['state']['simulation']['player']
        self.assertAlmostEqual(floor['y']+floor['radius'], -8130, places=5)
        self.assertAlmostEqual(recovered['y']+recovered['radius'], -7400, places=5)
        self.assertFalse(trace['snapshots'][-1]['state']['simulation']['grapple']['grappled'])
        self.evidence.write('encounters/recovery.json',dict(passed=True,
            missed_temporary_exit=True,broad_floor_catch=True,physical_return_to_S05=True,
            recovery_collider='S05-transfer-canopy',floor_observation=floor,
            galleries_observation=recovered,no_relocation=True,no_traversal_mutation=True))
        print('PASS failure/recovery: missed exit; broad floor catch; physical fall onto static S05-transfer-canopy; no relocation; matching trusted-input replays')


class Task481Tests(unittest.TestCase):
    """Completed Liftworks: phase release, alternating transfer, and physical fall."""
    task_id = 'TASK-481'
    snapshot_contacts = True
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task474Tests.replay
    test_05_source_hashes = Task465Tests.test_03_source_hashes

    def test_01_geometry(self):
        page = self.open()
        page.evaluate('floors=[loadFixedLevel(validateMountainManifest(GRAPPLE_OVER_MOUNTAIN))]')
        r = page.evaluate('''() => ({manifest:GRAPPLE_OVER_MOUNTAIN,runtime:floors[0].level,
            colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))})''')
        m = r['manifest']; elements = m['geometry']['elements']
        self.assertEqual(m['sections'][5]['status'], 'built')
        self.assertEqual([e['status'] for e in m['encounters'][20:24]], ['built']*4)
        self.assertEqual([e['status'] for e in m['connectors'][20:24]], ['built']*4)
        self.assertEqual(len({e['action'] for e in m['encounters'][20:24]}), 4)
        self.assertEqual(m['recoveries'][5]['status'], 'built')
        self.assertEqual(r['runtime']['elements'], elements)
        for actual, expected in zip(r['colliders'], elements):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        self.assertNotIn('S06-test-exit', [e['id'] for e in elements])
        self.assertIsNone(r['runtime']['finish'])
        self.assertFalse(any(s['from'].startswith('S06') for s in m['shortcuts']))
        prior = json.loads((ROOT/'artifacts/TASK-480/geometry.json').read_text())['manifest']
        lower = lambda manifest: [e for e in manifest['geometry']['elements'] if not e['id'].startswith('S06')]
        self.assertEqual(lower(m), lower(prior))
        calibration = json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path], calibration['source_hashes'][path])
        roles = {'S06-01 acquisition / S06-02 reversal':['S06-counterweight'],
            'S06-03 phase landing / ordinary rest':['S06-phase-rest'],
            'S06-04 fixed / moving transfer':['S06-fixed-head','S06-upper-weight','S06-transfer-head'],
            'Crown departure':['S06-exit'],
            'Static recovery to Cable Galleries':['S06-loading-floor','S05-recessed-ceiling','S05-transfer-canopy']}
        self.evidence.write('geometry.json', dict(self.proof, **r,
            structural_validations_pass=True, previous_geometry_unchanged=True,
            calibrated_physics_unchanged=True, no_temporary_exit=True,
            encounters=m['encounters'][20:24], surface_roles=roles,
            shortcut='None assigned to section 6', next_unbuilt_section_not_required=True))
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="1500" viewBox="5250 -10020 1500 2850" style="background:#182028">']
        colors=['#50baff','#e4d7a0','#8acaff','#ddad70','#85b398']
        for (role, ids), color in zip(roles.items(), colors):
            for e in elements:
                if e['id'] not in ids: continue
                points=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                parts.append(f'<polygon points="{points}" fill="{color}" stroke="#141820" stroke-width="3"/><text x="{e["x"]}" y="{e["y"]-30}" fill="white" font-size="20">{e["id"]} ({e["role"]})</text>')
        for i, role in enumerate(roles):
            parts.append(f'<text x="5300" y="{-9970+i*35}" fill="{colors[i]}" font-size="22">{role}</text>')
        parts.append('</svg>'); page.set_content(''.join(parts))
        page.set_viewport_size(dict(width=1100,height=1500))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S06-01 S06-02 S06-03 S06-04 built; distinct roles; rest; exit; static recovery; no shortcut; no temporary exit; overview.png')

    def test_02_phase_release(self):
        trace = self.replay('S06-03-phase-release',
            [(30,'mousedown',6110,-8370),(210,'mouseup',6110,-8370)],500,
            dict(x=[5830,5832],y=[-8281,-8280],speedX=[-.001,.001],speedY=[-.001,.001]),
            start=(6300,-8080.8))
        rows=trace['snapshots'][40:210]
        self.assertTrue(all(r['state']['rope'][0]['id']=='S06-counterweight' for r in rows))
        ys=[r['state']['rope'][0]['y'] for r in rows]
        self.assertGreater(max(ys)-min(ys),100)
        self.assertGreater(ys[60]-ys[0],0)
        self.assertLess(ys[-1]-ys[90],0)
        self.evidence.write('encounters/phase.json',dict(passed=True,
            moving_acquisition=True,attached_through_reversal=True,rising_phase_release=True,
            fixed_rest_landing=True,anchor_travel=max(ys)-min(ys),release_tick=210))
        print('PASS S06-03: moving acquisition; reversal; rising-phase release; fixed rest landing')

    def test_04_recovery(self):
        trace=self.replay('local-miss-recovery',
            [(30,'mousedown',6110,-8370),(300,'mouseup',6110,-8370)],700,
            dict(x=[5444,5445],y=[-7411,-7410]),start=(6300,-8080.8))
        floor=trace['snapshots'][400]['state']['simulation']['player']
        final=trace['snapshots'][-1]['state']['simulation']['player']
        self.assertAlmostEqual(floor['y']+floor['radius'],-8130,places=5)
        self.assertAlmostEqual(final['y']+final['radius'],-7400,places=5)
        self.evidence.write('encounters/recovery.json',dict(passed=True,broad_floor_catch=True,
            physical_return_to_S05=True,recovery_collider='S05-transfer-canopy',
            floor_observation=floor,galleries_observation=final,no_relocation=True))
        print('PASS recovery: local miss; broad floor catch; physical return to S05-transfer-canopy; no relocation')

    def test_03_transfer_and_section_exit(self):
        plan=[(30,'mousedown',5715,-8590),(80,'mouseup',5715,-8590),
              (85,'mousedown',5825,-8900),(220,'mouseup',5825,-8900),
              (250,'mousedown',6105,-9280),(350,'mouseup',6105,-9280),
              (370,'mousedown',5775,-9660),(470,'mouseup',5775,-9660)]
        for mode in ('mouse','touch'):
            inputs=plan if mode=='mouse' else [(t,{'mousedown':'touchstart','mouseup':'touchend'}[e],x,y) for t,e,x,y in plan]
            trace=self.replay('S06-04-section-exit-'+mode,inputs,770,
                dict(x=[5571,5769],y=[-9691,-9690],speedY=[-.001,.001]),
                start=(5830.8000001,-8280.8000001))
            grabs=[e for e in trace['events'] if e['type']=='acquisition']
            self.assertEqual([e['after']['rope'][0]['id'] for e in grabs],
                ['S06-fixed-head','S06-upper-weight','S06-transfer-head','S06-exit'])
            inputs=[e for e in trace['events'] if e['type']=='input']
            self.assertTrue(all(e['trusted'] for e in inputs))
            for e in inputs[::2]:
                self.assertTrue(0<e['client']['x']<1280 and 0<e['client']['y']<720)
            anchors=[s['state']['rope'][0]['y'] for s in trace['snapshots'][100:220]]
            self.assertGreater(max(anchors)-min(anchors),40)
            self.evidence.write('encounters/transfer-'+mode+'.json',dict(passed=True,
                fixed_moving_fixed_acquisitions=[e['after']['rope'][0]['id'] for e in grabs],
                upper_mover_anchor_travel=max(anchors)-min(anchors),
                section_exit_traversed=True, trusted_inputs=True,
                final=trace['snapshots'][-1]['state']['simulation']['player'],
                next_unbuilt_section_not_required=True))
        print('PASS S06-04: fixed-moving-fixed transfer; section exit traversed; mouse and touch; matching replays; next unbuilt section not required')


class Task482Tests(unittest.TestCase):
    """Liftworks tolerance from labeled isolated starts, with real input."""
    task_id = 'TASK-482'
    setUpClass = classmethod(Task467Tests.setUpClass.__func__)
    load_level = Task476Tests.load_level
    run_attempt = Task473Tests.run_attempt
    make_input = Task476Tests.make_input
    test_03_source_hashes = Task467Tests.test_02_source_hashes

    @staticmethod
    def routes():
        opening=[(30,'mousedown',6110,-8370),(210,'mouseup',6110,-8370)]
        transfer=[(30,'mousedown',5715,-8590),(80,'mouseup',5715,-8590),
                  (85,'mousedown',5825,-8900),(220,'mouseup',5825,-8900),
                  (250,'mousedown',6105,-9280),(350,'mouseup',6105,-9280),
                  (370,'mousedown',5775,-9660),(470,'mouseup',5775,-9660)]
        return [(f'S06-{i:02d}',(6300,-8080.8),opening,500,
                 dict(x=[5791,6009],y=[-8281,-8280]),1 if i==3 else 0,(1,0),[])
                for i in (1,2,3)] + [
            ('S06-04',(5830.8000001,-8280.8000001),transfer,770,
             dict(x=[5571,5769],y=[-9691,-9690]),7,(0,1),[])]

    def input_for(self, route, device='desktop', delta=0, offset=0):
        # Timing varies opening acquisition (01/02), phase release (03), or exit release (04).
        # Aim varies the corresponding acquisition along its surface tangent.
        m=self.make_input(route,device,delta,0)
        aim_index=6 if route[0]=='S06-04' else 0
        m['inputs'][aim_index]['world']['x']+=offset*route[6][0]
        m['inputs'][aim_index]['world']['y']+=offset*route[6][1]
        m['required_events']=['acquisition','release']
        m['metadata']['snapshot_contacts']=True
        return m

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s06_mechanics
        self.load_level()
        suite=dict(section='S06',source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated encounter placement only; not continuous completion',encounters={},
            negative_control='negative-control.json',recovery='clips/recovery/input.json',
            shortcuts='none assigned or observed; no shortcut completion claim',
            earlier_attempts=['exploratory/','exploratory-phase-check/','exploratory-transfer/','transfer-probe/','release-probe/','hold-probe/','exit-probe/'])
        failures=[]
        for route in self.routes():
            encounter=route[0];attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    m=self.input_for(route,device,delta,offset)
                    trace,success,reason=self.run_attempt(m,prefix,variant=='nominal')
                    mechanics=check_s06_mechanics(encounter,trace,required=False)
                    if success:
                        try: check_s06_mechanics(encounter,trace)
                        except ValueError as error: success=False;reason=str(error)
                    attempts.append(dict(name=name,device=device,variant=variant,critical_input_index=route[5],
                        timing_delta=delta,tangent_aim_delta=offset,surface_tangent=route[6],
                        input=prefix+'/input.json',trace=prefix+'/trace.json',success=success,reason=reason,
                        mechanic_events=mechanics,final=trace['snapshots'][-1]['state']['simulation']['player']))
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2:
                    failures.append(encounter+' '+device)
        m=self.input_for(self.routes()[2]);m['inputs'][1]['tick']=300
        trace,success,reason=self.run_attempt(m,'clips/negative',True)
        self.evidence.write('negative-control.json',dict(name='phase timing: release after suitable rising phase',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=not success,
            unchanged_physics=True,source_hashes=hashes(),reason=reason,
            scope='Same launch and duration with release delayed from tick 210 to 300; alternative solutions are not ruled out.'))
        self.assertFalse(success);self.assertIn('expected exit mismatch',reason)
        self.assertEqual(failures,[])
        print('PASS S06 four encounters: both viewports nominal + >=2/4 variants; moving travel; reversal; timed release; transfer; unsuitable phase fails exit')

    def test_02_recovery(self):
        from grapple_over_verify import execute
        self.load_level()
        route=list(self.routes()[0]);route[2]=[
            (30,'mousedown',6110,-8370),(300,'mouseup',6110,-8370)]
        route[3]=700;route[4]=dict(x=[5444,5445],y=[-7411,-7410])
        m=self.input_for(route)
        trace,success,reason=self.run_attempt(m,'clips/recovery',True)
        self.assertTrue(success,reason)
        self.assertAlmostEqual(trace['snapshots'][400]['state']['simulation']['player']['y'],-8140.8,places=5)
        replay=execute(m,self.browser,self.url,str(self.evidence.path('clips/recovery/replay')))
        self.assertEqual(trace,replay)
        self.evidence.write('clips/recovery/result.json',dict(passed=True,matching_traces=True,
            physical_catch_tick=400,physical_return_to_S05=True,no_relocation=True))
        print('PASS recovery: loading floor catch; physical return to S05-transfer-canopy; matching replay')


class Task483Tests(unittest.TestCase):
    """Crown opening: timed red rotor, displacement catch and exposed jib cut."""
    task_id = 'TASK-483'
    snapshot_contacts = True
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task474Tests.replay
    test_04_source_hashes = Task465Tests.test_03_source_hashes

    def test_01_geometry(self):
        page = self.open()
        page.evaluate('floors=[loadFixedLevel(validateMountainManifest(GRAPPLE_OVER_MOUNTAIN))]')
        r = page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN;validateMountainManifest(m);
            return {manifest:m,runtime:floors[0].level,
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))}}''')
        m = r['manifest']
        self.assertEqual(m['sections'][6]['status'], 'partial')
        self.assertEqual([e['status'] for e in m['encounters'][24:28]], ['built','built','planned','planned'])
        self.assertEqual(r['runtime']['elements'], m['geometry']['elements'])
        for a, e in zip(r['colliders'], m['geometry']['elements']):
            self.assertEqual(a, {k:e[k] for k in ('id','x','y','points','role')})
        elements = [e for e in m['geometry']['elements'] if e['id'].startswith('S07')]
        self.assertEqual(len(elements), 4)
        self.assertEqual(len({json.dumps(e['points']) for e in elements}), 4)
        self.assertEqual([e['role'] for e in elements], ['solid','hazard','solid','solid'])
        self.assertFalse(elements[1]['grapplable'])
        for e in elements:
            self.assertTrue(all(-11340 <= e['y']+p['y'] <= -9720 for p in e['points']))
        self.assertEqual([c['status'] for c in m['connectors'][24:26]], ['built','built'])
        self.assertIsNone(r['runtime']['finish'])
        prior = json.loads((ROOT/'artifacts/TASK-481/geometry.json').read_text())['manifest']
        self.assertEqual([e for e in m['geometry']['elements'] if not e['id'].startswith('S07')], prior['geometry']['elements'])
        self.assertEqual(m['geometry']['movers'][:-1], prior['geometry']['movers'])
        calibration = json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        self.assertTrue(m['shortcuts'][1]['optional'])
        self.assertEqual(m['shortcuts'][1]['openingStatus'], 'built')
        self.evidence.write('geometry.json', dict(self.proof, **r,
            structural_validations_pass=True, calibrated_physics_unchanged=True,
            previous_geometry_unchanged=True, encounters=m['encounters'][24:26],
            surface_roles={e['id']:e['role'] for e in elements},
            landing_margins={'temporary_exit_safe_centers':[5100.8,5369.2]},
            camera_sightlines='Measured target client positions in encounters/*/result.json; frames show rooftop and red rotor before commitment',
            temporary_exit='S07-test-exit; upper encounters remain planned',
            shortcut='Optional jib cut reaches opening exit; extension to S07-04 remains planned',
            recovery='Unwalled edges fall through Liftworks into Cable Galleries'))
        print('PASS geometry: S07-01/02; structural_validations_pass; matching colliders; starts/exits; roles; margins; calibration unchanged; four distinct silhouettes')

    def test_02_timed_passage(self):
        tr = self.replay('S07-01-timed-passage',
            [(60,'mousedown',5430,-10000),(85,'mouseup',5430,-10000)],500,
            dict(x=[5100,5370],y=[-9751,-9750],speedX=[-.001,.001],speedY=[-.001,.001]),
            start=(5650,-9690.8))
        self.assertFalse(any(e['type']=='knockback' for e in tr['events']))
        self.assertEqual(next(e for e in tr['events'] if e['type']=='acquisition')['after']['rope'][0]['id'], 'S07-service-gantry')
        self.evidence.write('encounters/passage.json',dict(passed=True, timed_passage_without_hit=True,
            temporary_exit_reached=True,connected_from='S06-exit'))
        print('PASS S07-01: timed passage without knockback; connected from S06-exit; safe temporary exit; matching real-input replay')

    def test_03_displacement_catch(self):
        tr = self.replay('S07-02-displacement-catch',
            [(120,'mousedown',5430,-10000),(145,'mouseup',5430,-10000),
             (179,'mouseup',5200,-9970),(180,'mousedown',5200,-9970)],210,
            dict(x=[5100,5500],y=[-10000,-9400]),start=(5650,-9690.8))
        hit = next(e for e in tr['events'] if e['type']=='knockback')
        catch = [e for e in tr['events'] if e['type']=='acquisition'][-1]
        self.assertGreater(catch['tick'],hit['tick'])
        self.assertEqual(catch['after']['rope'][0]['id'],'S07-shortcut-jib')
        self.assertEqual(hit['after']['rope'],[])
        rows = tr['snapshots'][190:]
        self.assertTrue(all(r['state']['simulation']['grapple']['grappled'] for r in rows))
        self.assertLess(rows[-1]['state']['simulation']['player']['speedY'],hit['after']['simulation']['player']['speedY'])
        self.evidence.write('encounters/catch.json',dict(passed=True,nonlethal_displacement=True,
            knockback_tick=hit['tick'],safe_anchor_catch_tick=catch['tick'],
            sustained_safe_attachment=True,downward_speed_reduced=True))
        print('PASS S07-02: real knockback detaches rope; release then safe anchor catch; sustained attachment reduces fall; matching real-input replay')

    def test_05_failure_recovery(self):
        tr = self.replay('missed-catch-physical-recovery',
            [(120,'mousedown',5430,-10000),(145,'mouseup',5430,-10000)],400,
            dict(x=[4600,4800],y=[-6811,-6810],speedY=[-.001,.001]),start=(5650,-9690.8))
        self.assertTrue(any(e['type']=='knockback' for e in tr['events']))
        end = tr['snapshots'][-1]['state']['simulation']
        self.assertFalse(end['stats']['completed'])
        self.assertFalse(end['grapple']['grappled'])
        self.evidence.write('encounters/recovery.json',dict(passed=True,physical_return_to_S05=True,
            recovery_collider='S05-projecting-girder',nonlethal=True,no_relocation=True,
            height_lost=end['player']['y']-tr['snapshots'][0]['state']['simulation']['player']['y']))
        print('PASS failure/recovery: omitted catch loses multiple sections; physical S05-projecting-girder landing; nonlethal; no relocation; matching replay')

    def test_06_optional_shortcut(self):
        tr = self.replay('optional-jib-shortcut',
            [(30,'mousedown',5200,-9970),(60,'mouseup',5200,-9970)],500,
            dict(x=[5100,5102],y=[-9751,-9750],speedX=[-.001,.001],speedY=[-.001,.001]),
            start=(5650,-9690.8))
        self.assertEqual(next(e for e in tr['events'] if e['type']=='acquisition')['after']['rope'][0]['id'],'S07-shortcut-jib')
        normal=json.loads(self.evidence.path('encounters/S07-01-timed-passage/trace.json').read_text())
        def landing(trace):
            return next(r['tick'] for r in trace['snapshots'] if 5100 < r['state']['simulation']['player']['x'] < 5370
                and abs(r['state']['simulation']['player']['y']+9750.8)<.001)
        self.assertLess(landing(tr),landing(normal))
        self.evidence.write('encounters/shortcut.json',dict(passed=True,optional=True,
            normal_route_available=True,shortcut_landing_tick=landing(tr),normal_landing_tick=landing(normal)))
        print('PASS shortcut: optional exposed jib cut reaches same temporary exit sooner; normal route remains; matching replay')


class Task484Tests(unittest.TestCase):
    """Completed Crown: exposed launch, lower recovery, and optional jib route."""
    task_id = 'TASK-484'
    snapshot_contacts = True
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task475Tests.replay
    test_07_source_hashes = Task465Tests.test_03_source_hashes
    test_06_deep_fall = Task483Tests.test_05_failure_recovery

    @staticmethod
    def upper(offset=0):
        return [(t+offset,e,x,y) for t,e,x,y in [
            (30,'mousedown',4995,-10060),(80,'mouseup',4995,-10060),
            (85,'mousedown',5235,-10380),(125,'mouseup',5235,-10380),
            (150,'mousedown',5500,-10780),(250,'mouseup',5500,-10780),
            (255,'mousedown',5330,-11330),(430,'mouseup',5330,-11330)]]

    def exit_assertions(self, trace, name):
        final=trace['snapshots'][-1]['state']['simulation']
        self.assertAlmostEqual(final['player']['y'], -11350.8, places=5)
        self.assertFalse(final['stats']['completed'])
        self.assertFalse(final['grapple']['grappled'])
        self.assertEqual([e['after']['rope'][0]['id'] for e in trace['events'] if e['type']=='acquisition'][-1], 'S07-exit')
        self.evidence.write('encounters/'+name+'-assertions.json',dict(passed=True,
            section_exit_traversed=True, next_unbuilt_section_not_required=True,
            final=final['player'], no_checkpoint_or_relocation=True))

    def test_01_geometry(self):
        page=self.open()
        page.evaluate('floors=[loadFixedLevel(validateMountainManifest(GRAPPLE_OVER_MOUNTAIN))]')
        r=page.evaluate('''() => ({manifest:GRAPPLE_OVER_MOUNTAIN,runtime:floors[0].level,
            colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))})''')
        m=r['manifest'];elements=m['geometry']['elements']
        self.assertEqual(m['sections'][6]['status'],'built')
        self.assertEqual([e['status'] for e in m['encounters'][24:28]],['built']*4)
        self.assertEqual([e['status'] for e in m['connectors'][24:28]],['built']*4)
        self.assertEqual(len({e['action'] for e in m['encounters'][24:28]}),4)
        self.assertEqual(m['recoveries'][6]['status'],'built')
        self.assertEqual(m['shortcuts'][1]['status'],'built')
        self.assertTrue(m['shortcuts'][1]['optional'])
        self.assertEqual(r['runtime']['elements'],elements)
        for a,e in zip(r['colliders'],elements):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
        self.assertNotIn('S07-test-exit',[e['id'] for e in elements])
        self.assertIsNone(r['runtime']['finish'])
        prior=json.loads((ROOT/'artifacts/TASK-483/geometry.json').read_text())['manifest']
        lower=lambda model:[e for e in model['geometry']['elements'] if not e['id'].startswith('S07')]
        self.assertEqual(lower(m),lower(prior))
        self.assertEqual(m['geometry']['movers'],prior['geometry']['movers'])
        calibration=json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        roles={'S07-01 timed rotor':['S07-service-gantry','S07-sweeper'],
               'S07-02 safe catch / optional shortcut':['S07-shortcut-jib'],
               'ordinary rest':['S07-rest-ledge'],
               'S07-03 exposed launch':['S07-launch-head','S07-roof-boom','S07-upper-motor'],
               'S07-04 lower recovery / rejoin':['S07-recovery-balcony','S07-side-hoist'],
               'exit to next band':['S07-exit']}
        self.evidence.write('geometry.json',dict(self.proof,**r,structural_validations_pass=True,
            encounters=m['encounters'][24:28],surface_roles=roles,previous_geometry_unchanged=True,
            calibrated_physics_unchanged=True,no_temporary_exit=True,
            rest_ledge='S07-rest-ledge',exit='S07-exit',recovery_route='balcony -> side hoist -> motor -> exit',
            shortcut='jib approach shares upper crossing; normal service gantry route remains'))
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="1500" viewBox="4700 -11750 1500 2300" style="background:#182028">']
        colors=['#b6c5d2','#f7d978','#f0dfbb','#8ec8e0','#9cdaa4','#c3a8f2']
        for (role,ids),color in zip(roles.items(),colors):
            for e in elements:
                if e['id'] not in ids:continue
                points=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                fill='#f45353' if e['role']=='hazard' else color
                parts.append(f'<polygon points="{points}" fill="{fill}"/><text x="{e["x"]}" y="{e["y"]-35}" fill="white" font-size="18">{e["id"]} ({e["role"]})</text>')
        for i,role in enumerate(roles):
            parts.append(f'<text x="4740" y="{-11710+i*32}" fill="{colors[i]}" font-size="22">{role}</text>')
        parts.append('</svg>');page.set_content(''.join(parts));page.set_viewport_size(dict(width=1100,height=1500))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S07-01 S07-02 S07-03 S07-04; distinct roles; rest; exit; recovery; optional shortcut; no temporary exit; overview.png')

    def test_02_normal_route(self):
        trace=self.replay('normal-S07-03-section-exit',
            [(60,'mousedown',5430,-10000),(85,'mouseup',5430,-10000)]+self.upper(500),1150,
            dict(x=[5270,5340],y=[-11351,-11350],speedX=[-.001,.001],speedY=[-.001,.001]),start=(5650,-9690.8))
        self.exit_assertions(trace,'normal')
        self.assertEqual([e['after']['rope'][0]['id'] for e in trace['events'] if e['type']=='acquisition'],
            ['S07-service-gantry','S07-launch-head','S07-roof-boom','S07-upper-motor','S07-exit'])
        print('PASS normal: connected S06-exit; rest; S07-03 exposed launch; S07 exit traversed; matching real-input replay')

    def test_03_shortcut(self):
        trace=self.replay('optional-shortcut-section-exit',
            [(30,'mousedown',5200,-9970),(60,'mouseup',5200,-9970)]+self.upper(400),1050,
            dict(x=[5270,5340],y=[-11351,-11350],speedX=[-.001,.001],speedY=[-.001,.001]),start=(5650,-9690.8))
        self.exit_assertions(trace,'shortcut')
        self.assertEqual(next(e for e in trace['events'] if e['type']=='acquisition')['after']['rope'][0]['id'],'S07-shortcut-jib')
        normal=json.loads(self.evidence.path('encounters/normal-S07-03-section-exit/trace.json').read_text())
        def arrival(tr):
            return next(s['tick'] for s in tr['snapshots'] if abs(s['state']['simulation']['player']['y']+11350.8)<.001)
        self.assertLess(arrival(trace),arrival(normal))
        self.evidence.write('encounters/shortcut.json',dict(passed=True,normal_route_available=True,
            shortcut_exit_tick=arrival(trace),normal_exit_tick=arrival(normal)))
        print('PASS shortcut: separate normal/shortcut success traces; same exit; optional jib route faster')

    def test_04_local_miss_recovery(self):
        plan=self.upper()[:4];plan[-1]=(145,'mouseup',5235,-10380)
        plan += [(380,'mousedown',5695,-10480),(430,'mouseup',5695,-10480),
                 (435,'mousedown',5500,-10780),(485,'mouseup',5500,-10780),
                 (530,'mousedown',5330,-11330),(685,'mouseup',5330,-11330)]
        trace=self.replay('S07-04-local-miss-rejoin',plan,950,
            dict(x=[5270,5340],y=[-11351,-11350],speedX=[-.001,.001],speedY=[-.001,.001]),start=(5100.8000001,-9750.8))
        self.exit_assertions(trace,'recovery')
        self.assertTrue(all(r['state']['rope'][0]['id']=='S07-upper-motor' for r in trace['snapshots'][460:485]))
        landed=trace['snapshots'][350]['state']['simulation']['player']
        self.assertAlmostEqual(landed['y'],-10190.8,places=5)
        self.assertAlmostEqual(landed['speedY'],0,places=5)
        ids=[e['after']['rope'][0]['id'] for e in trace['events'] if e['type']=='acquisition']
        self.assertEqual(ids,['S07-launch-head','S07-roof-boom','S07-side-hoist','S07-upper-motor','S07-exit'])
        self.evidence.write('encounters/local-recovery.json',dict(passed=True,local_miss=True,
            lower_balcony_landing=landed,side_hoist_rejoin=True,sustained_upper_motor_attachment=True,section_exit_traversed=True))
        print('PASS S07-04 recovery: local miss; lower balcony landing; side hoist rejoin; sustained upper motor attachment; section exit; no relocation')

    def test_05_touch(self):
        plan=[(t,{'mousedown':'touchstart','mouseup':'touchend'}[e],x,y) for t,e,x,y in self.upper()]
        trace=self.replay('S07-03-touch-exit',plan,650,
            dict(x=[5270,5340],y=[-11351,-11350],speedX=[-.001,.001],speedY=[-.001,.001]),start=(5100.8000001,-9750.8))
        self.exit_assertions(trace,'touch')
        self.assertTrue(all(e['trusted'] for e in trace['events'] if e['type']=='input'))
        print('PASS touch: exposed launch and section exit; trusted touch inputs; matching replay')


class Task485Tests(unittest.TestCase):
    """Crown tolerance from labeled isolated starts, with real input."""
    task_id = 'TASK-485'
    setUpClass = classmethod(Task467Tests.setUpClass.__func__)
    load_level = Task476Tests.load_level
    run_attempt = Task473Tests.run_attempt
    make_input = Task476Tests.make_input
    test_03_source_hashes = Task467Tests.test_02_source_hashes

    @staticmethod
    def routes():
        recovery=Task484Tests.upper()[:4]
        recovery[-1]=(145,'mouseup',5235,-10380)
        recovery += [(380,'mousedown',5695,-10480),(430,'mouseup',5695,-10480),
                     (435,'mousedown',5500,-10780),(485,'mouseup',5500,-10780),
                     (530,'mousedown',5330,-11330),(685,'mouseup',5330,-11330)]
        exit_bounds=dict(x=[5270,5340],y=[-11351,-11350])
        return [
            ('S07-01',(5650,-9690.8),[(60,'mousedown',5430,-10000),(85,'mouseup',5430,-10000)],500,
             dict(x=[5100,5370],y=[-9751,-9750]),0,(1,0),[]),
            ('S07-02',(5650,-9690.8),[(120,'mousedown',5430,-10000),(145,'mouseup',5430,-10000),
             (179,'mouseup',5200,-9970),(180,'mousedown',5200,-9970)],210,
             dict(x=[5100,5500],y=[-10000,-9400]),3,(0,1),[]),
            ('S07-03',(5100.8000001,-9750.8),Task484Tests.upper(),650,exit_bounds,5,(1,0),[]),
            ('S07-04',(5100.8000001,-9750.8),recovery,950,exit_bounds,4,(0,1),[])]

    def input_for(self, route, device='desktop', delta=0, offset=0):
        m=self.make_input(route,device,delta,0 if route[0]=='S07-03' else offset)
        if route[0]=='S07-03': m['inputs'][4]['world']['x']+=offset
        # The hazard re-arms the throw: release after the hit, before catching.
        if route[0]=='S07-02':
            catch_tick=m['inputs'][3]['tick']
            m['inputs'][2]['tick']=catch_tick-1
            if device=='touch':
                m['inputs'].insert(2,dict(tick=catch_tick-2,event='touchstart',
                    world=dict(x=5200,y=-9970)))
        m['required_events']=['acquisition','release']
        m['metadata']['snapshot_contacts']=True
        return m

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s07_mechanics
        self.load_level()
        suite=dict(section='S07',source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated encounter placement only; not continuous completion',encounters={},
            negative_control='negative-control.json',recovery='clips/recovery/input.json',
            shortcuts='clips/shortcut/input.json',
            earlier_attempts=['exploratory/manifest.json','exploratory-camera/manifest.json',
                              'probe.log','probe-upper.log','probe-release.log'])
        failures=[]
        for route in self.routes():
            encounter=route[0];attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    m=self.input_for(route,device,delta,offset)
                    trace,success,reason=self.run_attempt(m,prefix,variant=='nominal')
                    mechanics=check_s07_mechanics(encounter,trace,required=False)
                    if success:
                        try: check_s07_mechanics(encounter,trace)
                        except ValueError as error: success=False;reason=str(error)
                    attempts.append(dict(name=name,device=device,variant=variant,critical_input_index=4 if encounter=='S07-02' and device=='touch' else route[5],
                        aim_input_index=4 if encounter=='S07-03' or (encounter=='S07-02' and device=='touch') else route[5],
                        timing_delta=delta,tangent_aim_delta=offset,surface_tangent=route[6],
                        input=prefix+'/input.json',trace=prefix+'/trace.json',success=success,reason=reason,
                        mechanic_events=mechanics,final=trace['snapshots'][-1]['state']['simulation']['player']))
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2:
                    failures.append(encounter+' '+device)
        m=self.input_for(self.routes()[0])
        # Long enough for the knocked-back fall to come to rest physically.
        m['inputs'][0]['tick']=120;m['inputs'][1]['tick']=145;m['ticks']=2000
        trace,success,reason=self.run_attempt(m,'clips/negative',True)
        hits=[e for e in trace['events'] if e['type']=='knockback']
        players=[r['state']['simulation']['player'] for r in trace['snapshots']]
        final=players[-1];step=max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a,b in zip(players,players[1:]))
        self.evidence.write('negative-control.json',dict(name='hazard timing: passage delayed 60 ticks',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=not success,
            unchanged_physics=True,source_hashes=hashes(),reason=reason,
            knockback_ticks=[e['tick'] for e in hits],hazard_detach=bool(hits and not hits[0]['after']['rope']),
            event_types=sorted({e['type'] for e in trace['events']}),max_tick_displacement=step,
            final_player=final,recoverable_fall=True,
            scope='Same physics and start; mistimed passage fails rest exit, the player falls physically and rests '
                  'alive on the mountain base with no relocation. Alternative routes are not ruled out.'))
        self.assertFalse(success);self.assertTrue(hits)
        self.assertIn('expected exit mismatch',reason)
        self.assertLess(step,60)
        # TASK-513 narrows the v2 S03 crest hook and lowers the span buffer top: this long
        # fall no longer deflects off them and stops physically on the S03 far deck
        # (the S03-03 start pad) instead of the mountain base.
        if abs(final['y']+3260.8) < 1e-3: self.assertTrue(3330 <= final['x'] <= 3530, final)
        else: self.assertAlmostEqual(final['y'],109.2,places=3)
        # Since TASK-506 the fall stops in the S01 base drag zone, which damps vx
        # geometrically instead of leaving it at exactly 0 against the left wall.
        self.assertEqual(final['speedY'],0);self.assertLess(abs(final['speedX']),1e-9)
        self.assertEqual(failures,[])
        print('PASS S07 four encounters: both viewports nominal + >=2/4 variants; hazard passage; knockback; detach; airborne catch; recovery')

    def test_02_recovery_and_shortcut(self):
        from grapple_over_verify import execute
        self.load_level()
        for name,route in [('recovery',self.routes()[3]),('shortcut',(
            'shortcut',(5650,-9690.8),[(30,'mousedown',5200,-9970),(60,'mouseup',5200,-9970)]+Task484Tests.upper(400),
            1050,dict(x=[5270,5340],y=[-11351,-11350]),0,(1,0),[]))]:
            m=self.input_for(route)
            trace,success,reason=self.run_attempt(m,'clips/'+name,True)
            self.assertTrue(success,reason)
            replay=execute(m,self.browser,self.url,str(self.evidence.path('clips/'+name+'/replay')))
            self.assertEqual(trace,replay)
            self.evidence.write('clips/'+name+'/result.json',dict(passed=True,matching_traces=True,no_relocation=True))
            print('PASS '+name+': section exit; matching replay; no relocation')


class Task486Tests(unittest.TestCase):
    """Summit Array opening: opposing-anchor brake and angled-bounce transfer."""
    task_id = 'TASK-486'
    snapshot_contacts = True
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_07_source_hashes = Task465Tests.test_03_source_hashes
    # Actual S07 departure rest from the TASK-484 normal route trace.
    s07_exit = (5339.1999999, -11350.8000001)
    footing = (4290.8000001, -11610.8000001)
    landmark = (3040, -12640)
    brake = [(20,'mousedown',5000,-11740),(65,'mouseup',5000,-11740),
             (125,'mousedown',4930,-11865),(150,'mouseup',4930,-11865)]
    transfer = [(20,'mousedown',4070,-11945),(55,'mouseup',4070,-11945),
                (215,'mousedown',3450,-12185),(241,'mouseup',3450,-12185)]
    rest_bounds = dict(x=[4290,4450],y=[-11611,-11610],speedX=[-.001,.001],speedY=[-.001,.001])
    exit_bounds = dict(x=[3070,3410],y=[-12091,-12090],speedX=[-.001,.001],speedY=[-.001,.001])

    def replay(self, name, plan, ticks, bounds, start, bounces=(), targets=()):
        from grapple_over_verify import metadata, execute, check_trace
        page=self.open();level=page.evaluate('validateMountainManifest(GRAPPLE_OVER_MOUNTAIN)')
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=level,
            player=dict(x=start[0],y=start[1],speedX=0,speedY=0)),
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks,expected_exit=bounds,required_events=['acquisition','release'])
        m['metadata'].update(compact_contacts=True,snapshot_contacts=True)
        prefix='encounters/'+name
        self.evidence.write(prefix+'/input.json',m)
        trace=execute(m,self.browser,self.url,str(self.evidence.path(prefix)),filmstrip=True)
        check_trace(m,trace)
        replay=execute(m,self.browser,self.url,str(self.evidence.path(prefix+'/replay')))
        check_trace(m,replay);self.assertEqual(trace,replay)
        self.assertEqual(len(trace['metadata']['setupOnlySpawns']),1)
        self.assertLessEqual({e['type'] for e in trace['events']},{'input','acquisition','release','bounce','wrap'})
        reflections=[e for e in trace['events'] if e['type']=='bounce']
        self.assertEqual([e['contact']['elementId'] for e in reflections],list(bounces))
        for e in reflections:
            before=e['before']['simulation']['player'];after=e['after']['simulation']['player']
            n=(e['contact']['nx'],e['contact']['ny'])
            self.assertLess(before['speedX']*n[0]+before['speedY']*n[1],0)
            self.assertGreater(after['speedX']*n[0]+after['speedY']*n[1],0)
            self.assertAlmostEqual(abs(n[0]),1/(5**.5),places=5)
        players=[r['state']['simulation']['player'] for r in trace['snapshots']]
        step=max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a,b in zip(players,players[1:]))
        self.assertLess(step,60)
        # Measured camera sightlines: landmark and every target at each filmstrip frame.
        frames=sorted({t for t in range(0,ticks,60)}|{ticks-1}|{t for t,*_ in plan})
        points=dict(landmark=self.landmark,**{k:v for k,v in targets})
        sight=page.evaluate('''([rows,points]) => rows.map(r => {const out={tick:r.tick};
            for (const [k,p] of Object.entries(points)) {
                const c=canvasCoordsToViewportCoords({x:(p[0]+r.camera.x)*scale[version],y:(p[1]+r.camera.y)*scale[version]});
                out[k]={x:c.x,y:c.y,visible:c.x>0&&c.x<1280&&c.y>0&&c.y<720};}
            return out;})''',[[dict(tick=t,camera=trace['snapshots'][t]['state']['camera']) for t in frames],points])
        page.close()
        for e in trace['events']:
            if e['type']=='input' and e['event']=='mousedown':
                self.assertTrue(e['trusted'])
                self.assertTrue(0<e['client']['x']<1280 and 0<e['client']['y']<720)
        result=dict(passed=True,matching_traces=True,trusted_inputs=True,no_traversal_mutation=True,
            max_tick_displacement=step,event_types=sorted({e['type'] for e in trace['events']}),
            acquisitions=[(e['tick'],e['after']['rope'][0]['id']) for e in trace['events'] if e['type']=='acquisition'],
            releases=[e['tick'] for e in trace['events'] if e['type']=='release'],
            reflections=[dict(tick=e['tick'],element=e['contact']['elementId'],normal=[e['contact']['nx'],e['contact']['ny']],
                before=e['before']['simulation']['player'],after=e['after']['simulation']['player']) for e in reflections],
            final=players[-1],camera_sightlines=sight,frames=[f'frame-{t:04d}.png' for t in frames],
            scope='One labeled setup placement; production physics and trusted mouse input thereafter')
        self.evidence.write(prefix+'/result.json',result)
        return trace,result

    def test_01_geometry(self):
        page=self.open()
        page.evaluate('floors=[loadFixedLevel(validateMountainManifest(GRAPPLE_OVER_MOUNTAIN))]')
        r=page.evaluate('''() => ({manifest:GRAPPLE_OVER_MOUNTAIN,runtime:floors[0].level,
            colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))})''')
        m=r['manifest'];elements=m['geometry']['elements']
        self.assertEqual(m['sections'][7]['status'],'partial')
        self.assertEqual(m['sections'][7]['landmark']['name'],'distinct final beacon silhouette')
        self.assertEqual([e['status'] for e in m['encounters'][28:32]],['built','built','planned','planned'])
        self.assertEqual([c['status'] for c in m['connectors'][28:31]],['built','built','planned'])
        self.assertEqual(m['connectors'][28]['from'],'S07-04')
        self.assertEqual(m['recoveries'][7]['status'],'planned')
        self.assertEqual(r['runtime']['elements'],elements)
        for a,e in zip(r['colliders'],elements):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
        self.assertIsNone(r['runtime']['finish'])
        summit=[e for e in elements if e['id'].startswith('S08')]
        self.assertEqual(len(summit),10)
        self.assertEqual(len({json.dumps(e['points']) for e in summit}),10)
        roles={e['id']:e['role'] for e in summit}
        self.assertEqual([k for k,v in roles.items() if v!='solid'],['S08-deflector-ramp'])
        self.assertEqual(roles['S08-deflector-ramp'],'bounce')
        self.assertFalse(any(e['role']=='hazard' for e in summit))
        self.assertTrue(all(e['grapplable'] for e in summit))
        top,bottom=m['sections'][7]['band']['top'],m['sections'][7]['band']['bottom']
        recovery_overlap={'S08-spill-deck'}
        for e in summit:
            ys=[e['y']+p['y'] for p in e['points']]
            if e['id'] in recovery_overlap: self.assertTrue(-11340<min(ys) and max(ys)<-9720)
            else: self.assertTrue(top<=min(ys) and max(ys)<=bottom,e['id'])
        prior=json.loads((ROOT/'artifacts/TASK-484/geometry.json').read_text())['manifest']
        self.assertEqual([e for e in elements if not e['id'].startswith('S08')],prior['geometry']['elements'])
        self.assertEqual(m['geometry']['movers'],prior['geometry']['movers'])
        calibration=json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        ramp=next(e for e in summit if e['id']=='S08-deflector-ramp')['points']
        slope=(ramp[1]['y']-ramp[0]['y'])/(ramp[1]['x']-ramp[0]['x'])
        self.assertAlmostEqual(slope,.5)
        functions={'S08-01 launch':['S08-launch-arm'],'S08-01 opposing brake':['S08-brake-davit'],
                   'rest between combinations':['S08-footing-rest'],'S08-02 launch':['S08-lamp-hook'],
                   'S08-02 angled green bounce':['S08-deflector-ramp'],'S08-02 airborne transfer':['S08-mast-yard'],
                   'safe temporary exit':['S08-test-exit'],'landmark beacon':['S08-beacon-mast'],
                   'recovery (miss collector / return)':['S08-spill-deck','S08-recovery-hook']}
        self.evidence.write('geometry.json',dict(self.proof,**r,structural_validations_pass=True,
            encounters=m['encounters'][28:30],surface_roles=roles,functions=functions,
            colliders_S08=[{k:e[k] for k in ('id','x','y','role','grapplable','points')} for e in summit],
            starts={'S08-01':dict(x=self.s07_exit[0],y=self.s07_exit[1],source='S07-exit rest pose from artifacts/TASK-484 normal route'),
                    'S08-02':dict(x=self.footing[0],y=self.footing[1],source='S08-01 measured final rest')},
            exits={'S08-01':m['encounters'][28]['exit'],'S08-02':m['encounters'][29]['exit']},
            intended_actions={e['id']:e['action'] for e in m['encounters'][28:30]},
            landing_margins={'S08-footing-rest':dict(floor=[4280,4460],top=-11600,safe_center=[4290.8,4449.2],
                                 west_lip=20,east_stop=60),
                             'S08-test-exit':dict(floor=[3060,3420],top=-12080,safe_center=[3070.8,3409.2],
                                 west_stop=60,east_lip=20)},
            ramp=dict(slope=slope,normal_abs_x=1/(5**.5)),
            landmark=m['sections'][7]['landmark'],
            camera_sightlines='Measured per filmstrip frame in encounters/*/result.json (landmark and targets in 1280x720)',
            calibrated_physics_unchanged=True,previous_geometry_unchanged=True,
            temporary_exit='S08-test-exit after S08-02; S08-03/04 and summit remain planned; no finish trigger',
            recovery='S08-spill-deck sits in the Crown band as a recovery overlap; S08-recovery-hook returns players to S07-roof-boom/S07-recovery-balcony'))
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="1100" viewBox="2850 -12800 2700 2030" style="background:#182028">']
        colors=['#b6c5d2','#f7d978','#f0dfbb','#8ec8e0','#66e08a','#c3a8f2','#ffffff','#ff9de0','#9cdaa4']
        for (role,ids),color in zip(functions.items(),colors):
            for e in elements:
                if e['id'] not in ids:continue
                pts=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                parts.append(f'<polygon points="{pts}" fill="{color}"/><text x="{e["x"]}" y="{e["y"]-20}" fill="white" font-size="20">{e["id"]} ({e["role"]})</text>')
        for e in elements:
            if e['id'].startswith('S07'):
                pts=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                parts.append(f'<polygon points="{pts}" fill="#556070"/><text x="{e["x"]}" y="{e["y"]-8}" fill="#99a" font-size="16">{e["id"]}</text>')
        for i,role in enumerate(functions):
            parts.append(f'<text x="2870" y="{-11500+i*30}" fill="{colors[i]}" font-size="22">{role}</text>')
        parts.append('</svg>');page.set_content(''.join(parts));page.set_viewport_size(dict(width=1300,height=1100))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S08-01/02 built; structural_validations_pass; matching colliders; starts/exits; roles; landing margins; ten distinct silhouettes; calibration and earlier geometry unchanged; overview.png')

    def brake_checks(self, trace):
        acq=[e for e in trace['events'] if e['type']=='acquisition']
        self.assertEqual([e['after']['rope'][0]['id'] for e in acq][:2],['S08-launch-arm','S08-brake-davit'])
        rel=[e for e in trace['events'] if e['type']=='release']
        before=acq[1]['after']['simulation']['player'];after=rel[1]['after']['simulation']['player']
        self.assertLess(before['speedX'],-.5)
        self.assertGreater(after['speedX'],before['speedX']/4)
        return dict(speedX_at_brake_acquisition=before['speedX'],speedX_at_brake_release=after['speedX'],
            brake_tick=acq[1]['tick'],release_tick=rel[1]['tick'])

    def test_02_opposing_brake(self):
        trace,result=self.replay('S08-01-brake-release',self.brake,450,self.rest_bounds,self.s07_exit,
            targets=[('launch_arm',(4960,-11740)),('brake_davit',(4930,-11865)),('footing_rest',(4370,-11600))])
        brake=self.brake_checks(trace)
        # After the camera settles on the S07 exit, all three S08-01 targets stay on screen.
        self.assertTrue(all(r['launch_arm']['visible'] and r['brake_davit']['visible'] and r['footing_rest']['visible']
            for r in result['camera_sightlines'] if r['tick']>=60))
        self.evidence.write('encounters/S08-01.json',dict(passed=True,connected_from='S07-exit',
            opposing_anchor_braking=brake,release_onto_rest=True,final=result['final']))
        print('PASS S08-01: from S07 exit; launch arm; opposing davit brake reduces westward speed; release onto footing rest; targets visible before commitment; matching real-input replay')

    def bounce_checks(self, trace):
        acq=[e for e in trace['events'] if e['type']=='acquisition']
        self.assertEqual([e['after']['rope'][0]['id'] for e in acq],['S08-lamp-hook','S08-mast-yard'])
        bounce=next(e for e in trace['events'] if e['type']=='bounce')
        self.assertLess(bounce['tick'],acq[1]['tick'])
        # Between reflection and the new grapple the player is airborne and unattached.
        rows=trace['snapshots'][bounce['tick']+1:acq[1]['tick']]
        self.assertTrue(rows and all(not r['state']['simulation']['grapple']['grappled'] and
            abs(r['state']['simulation']['player']['speedY'])>.05 for r in rows))
        return dict(bounce_tick=bounce['tick'],airborne_acquisition_tick=acq[1]['tick'],
            airborne_ticks=len(rows))

    def test_03_bounce_transfer(self):
        trace,result=self.replay('S08-02-bounce-transfer',self.transfer,620,self.exit_bounds,self.footing,
            bounces=['S08-deflector-ramp'],targets=[('lamp_hook',(4070,-11945)),('ramp',(3700,-11710)),('mast_yard',(3450,-12185)),('test_exit',(3240,-12080))])
        checks=self.bounce_checks(trace)
        rows=result['camera_sightlines']
        self.assertTrue(all(r['landmark']['visible'] for r in rows if r['tick']>=300))
        self.assertTrue(all(r[k]['visible'] for r in rows if r['tick']>=55 for k in ('lamp_hook','ramp','mast_yard','test_exit')))
        self.evidence.write('encounters/S08-02.json',dict(passed=True,angled_bounce=True,airborne_transfer=checks,
            temporary_exit_reached=True,final=result['final']))
        print('PASS S08-02: angled green ramp reflection; airborne mast-yard grapple after bounce; temporary exit; next targets visible from tick 55; beacon landmark visible from tick 300; matching replay')

    def test_04_connected(self):
        plan=self.brake+[(t+450,e,x,y) for t,e,x,y in self.transfer]
        trace,_=self.replay('S08-01-02-connected',plan,1070,self.exit_bounds,self.s07_exit,bounces=['S08-deflector-ramp'])
        rest=trace['snapshots'][450]['state']['simulation']['player']
        self.assertAlmostEqual(rest['x'],self.footing[0],places=5);self.assertAlmostEqual(rest['y'],self.footing[1],places=5)
        self.assertEqual((rest['speedX'],rest['speedY']),(0,0))
        self.brake_checks(trace)
        acq=[e['after']['rope'][0]['id'] for e in trace['events'] if e['type']=='acquisition']
        self.assertEqual(acq,['S08-launch-arm','S08-brake-davit','S08-lamp-hook','S08-mast-yard'])
        self.evidence.write('encounters/connected.json',dict(passed=True,from_='S07-exit',rest_between=rest,
            acquisitions=acq,final=trace['snapshots'][-1]['state']['simulation']['player']))
        print('PASS connected: S07 exit -> S08-01 brake -> footing rest (stationary) -> S08-02 bounce transfer -> temporary exit; matching replay')

    def test_05_failure_recovery(self):
        hook=[(1500,'mousedown',5000,-11440),(1530,'mouseup',5000,-11440)]
        boom=dict(x=[5490,5780],y=[-10191,-10190],speedX=[-.001,.001],speedY=[-.001,.001])
        out={}
        trace,r=self.replay('S08-01-no-brake-recovery',self.brake[:2]+hook,1900,boom,self.s07_exit)
        corner=trace['snapshots'][1499]['state']['simulation']['player']
        self.assertAlmostEqual(corner['y'],-11051.7,delta=.5);self.assertAlmostEqual(corner['x'],4769.2,delta=.5)
        self.assertEqual([a[1] for a in r['acquisitions']],['S08-launch-arm','S08-recovery-hook'])
        out['no_brake']=dict(spill_deck_corner=corner,recovery_landing='S07-recovery-balcony',final=r['final'])
        short=[(20,'mousedown',4070,-11945),(52,'mouseup',4070,-11945)]
        trace,r=self.replay('S08-02-short-pull-recovery',short+hook,1900,boom,self.footing,bounces=['S08-deflector-ramp'])
        corner=trace['snapshots'][1499]['state']['simulation']['player']
        self.assertAlmostEqual(corner['y'],-11051.7,delta=.5)
        self.assertGreater(r['reflections'][0]['after']['speedX'],0)
        out['short_hook']=dict(spill_deck_corner=corner,recovery_landing='S07-recovery-balcony',final=r['final'])
        over=self.brake[:3]+[(180,'mouseup',4930,-11865)]
        trace,r=self.replay('S08-01-over-brake-crown',over,1000,
            dict(x=[4860,4990],y=[-10101,-10100],speedX=[-.001,.001],speedY=[-.001,.001]),self.s07_exit)
        out['over_brake']=dict(landing='S07-launch-head (start of the S07-03 crossing back to S07-exit)',final=r['final'])
        self.assertFalse(trace['snapshots'][-1]['state']['simulation']['stats']['completed'])
        self.evidence.write('encounters/recovery.json',dict(passed=True,physical_falls=True,nonlethal=True,
            no_relocation=True,no_hazards=True,routes=out,
            explicit_route='Spill deck -> recovery hook -> S07-recovery-balcony (S07-04 side route: hoist -> motor -> S07-exit -> S08-01); over-brake falls back onto S07-launch-head and the S07-03 crossing'))
        print('PASS failure/recovery: missed brake and short ramp pull collect on spill deck; recovery hook returns to Crown recovery balcony; over-brake falls back onto the Crown launch head; physical, nonlethal, matching replays')


class Task487Tests(unittest.TestCase):
    """Summit Array finish: moving-target overhang, final landing and summit exit."""
    task_id = 'TASK-487'
    snapshot_contacts = True
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    replay = Task486Tests.replay
    test_07_source_hashes = Task465Tests.test_03_source_hashes
    s07_exit = Task486Tests.s07_exit
    ledge = (3070.8000001, -12090.8000001)
    deck = (4189.2000001, -12710.8000001)
    landmark = (3400, -12940)
    finish = dict(left=3420, right=3700, top=-12772, bottom=-12760)
    # Carriage phase comes from the spawn time: tick 110 (mod 240) is its low, rising turn.
    overhang = [(110,'mousedown',3490,-12338),(216,'mouseup',3490,-12338)]
    landing = [(20,'mousedown',3760,-12890),(70,'mouseup',3760,-12890)]
    ledge_bounds = dict(x=[3070,3071],y=[-12091,-12090],speedX=[-.001,.001],speedY=[-.001,.001])
    deck_bounds = dict(x=[4189,4190],y=[-12711,-12710],speedX=[-.001,.001],speedY=[-.001,.001])
    finish_bounds = dict(x=[3420,3700],y=[-12772,-12760])

    def test_01_geometry(self):
        page=self.open()
        page.evaluate('floors=[loadFixedLevel(validateMountainManifest(GRAPPLE_OVER_MOUNTAIN))]')
        r=page.evaluate('''() => ({manifest:GRAPPLE_OVER_MOUNTAIN,runtime:floors[0].level,
            colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))})''')
        m=r['manifest'];elements=m['geometry']['elements'];section=m['sections'][7]
        self.assertEqual(section['status'],'built')
        self.assertEqual(section['landmark']['name'],'distinct final beacon silhouette')
        self.assertEqual([e['status'] for e in m['encounters'][28:32]],['built']*4)
        self.assertEqual([(c['id'],c['status']) for c in m['connectors'][28:33]],
            [('S08-entrance','built'),('S08-route-1','built'),('S08-route-2','built'),('S08-route-3','built'),('summit-approach','built')])
        self.assertEqual(m['recoveries'][7]['status'],'built')
        self.assertEqual(r['runtime']['finish'],self.finish)
        self.assertEqual(m['encounters'][31]['finishRegion'],self.finish)
        self.assertEqual(r['runtime']['elements'],elements)
        for a,e in zip(r['colliders'],elements):
            self.assertEqual(a,{k:e[k] for k in ('id','x','y','points','role')})
        summit=[e for e in elements if e['id'].startswith('S08')]
        ids=[e['id'] for e in summit]
        self.assertFalse(any('test' in i or 'temporary' in i for i in ids))
        self.assertNotIn('temporaryExit',json.dumps(m['encounters'][28:32]))
        self.assertEqual(len(summit),15)
        self.assertEqual(len({json.dumps(e['points']) for e in summit}),15)
        roles={e['id']:e['role'] for e in summit}
        self.assertEqual([k for k,v in roles.items() if v!='solid'],['S08-deflector-ramp'])
        self.assertFalse(any(e['role']=='hazard' for e in summit))
        movers=[v for v in m['geometry']['movers'] if v['element'].startswith('S08')]
        self.assertEqual([v['element'] for v in movers],['S08-overhang-carriage'])
        top,bottom=section['band']['top'],section['band']['bottom']
        for e in summit:
            ys=[e['y']+p['y'] for p in e['points']]
            if e['id']=='S08-spill-deck': self.assertTrue(-11340<min(ys) and max(ys)<-9720)
            else: self.assertTrue(top<=min(ys) and max(ys)<=bottom,e['id'])
        # The finish band is the pad surface between its west beacon tower and east lip.
        pad=next(e for e in summit if e['id']=='S08-summit-pad')
        surface=[(pad['x']+p['x'],pad['y']+p['y']) for p in pad['points'] if pad['y']+p['y']==-12760]
        self.assertEqual(sorted(x for x,_ in surface),[3420,3700])
        # Earlier geometry and calibrated physics are unchanged; only the temporary exit was renamed.
        prior=json.loads((ROOT/'artifacts/TASK-486/geometry.json').read_text())['manifest']['geometry']
        renamed={**next(e for e in prior['elements'] if e['id']=='S08-test-exit'),'id':'S08-rest-ledge'}
        self.assertEqual([e for e in elements if e['id'] in {p['id'] for p in prior['elements']}|{'S08-rest-ledge'}],
            [renamed if e['id']=='S08-test-exit' else e for e in prior['elements']])
        self.assertEqual(m['geometry']['movers'][:len(prior['movers'])],prior['movers'])
        calibration=json.loads((ROOT/'artifacts/TASK-463/calibration.json').read_text())
        for path in ('sprites/ninja.js','sprites/grapnel.js','sprites/trampoline.js','physics.js'):
            self.assertEqual(self.proof['source_hashes'][path],calibration['source_hashes'][path])
        self.assertEqual([s['id'] for s in m['shortcuts']],['S03-shortcut','S07-shortcut'])
        functions={'S08-01 brake (TASK-486)':['S08-launch-arm','S08-brake-davit'],
                   'rest between combinations':['S08-footing-rest','S08-rest-ledge','S08-array-deck'],
                   'S08-02 bounce transfer (TASK-486)':['S08-lamp-hook','S08-deflector-ramp','S08-mast-yard'],
                   'S08-03 overhang':['S08-beacon-deck'],'S08-03 moving target (blue mover)':['S08-overhang-carriage'],
                   'S08-04 final pull':['S08-summit-gantry'],'section exit: summit pad + final beacon':['S08-summit-pad'],
                   'waypoint lamp mast':['S08-beacon-mast'],'recovery (miss collector / Crown return)':['S08-spill-deck','S08-recovery-hook']}
        self.assertEqual(sorted(sum(functions.values(),[])),sorted(ids))
        self.evidence.write('geometry.json',dict(self.proof,**r,structural_validations_pass=True,
            encounters=m['encounters'][28:32],connectors=m['connectors'][28:33],recovery=m['recoveries'][7],
            surface_roles=roles,functions=functions,movers_S08=movers,finish_region=self.finish,
            colliders_S08=[{k:e[k] for k in ('id','x','y','role','grapplable','points')} for e in summit],
            starts={'S08-03':dict(x=self.ledge[0],y=self.ledge[1],source='S08-02 rest pose against the mast stop'),
                    'S08-04':dict(x=self.deck[0],y=self.deck[1],source='S08-03 measured rest against the array deck east stop')},
            landing_margins={'S08-array-deck':dict(floor=[3900,4240],top=-12700,safe_center=[3930.8,4189.2],west_lip=20,east_stop=120),
                             'S08-summit-pad':dict(floor=[3380,3720],top=-12760,finish=[3420,3700],west_beacon_tower=200,east_lip=20)},
            placeholder_encounters_remaining=[],temporary_geometry_removed=['S08-test-exit renamed to ordinary S08-rest-ledge'],
            shortcut='None assigned: section 8 is neither section 3 nor 7 (S03/S07 shortcuts unchanged)',
            calibrated_physics_unchanged=True,previous_geometry_unchanged=True))
        parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="1100" viewBox="2850 -13050 2700 2300" style="background:#182028">']
        colors=['#b6c5d2','#f0dfbb','#66e08a','#d0a070','#5aa0ff','#f7d978','#ffffff','#ff9de0','#9cdaa4']
        for (role,members),color in zip(functions.items(),colors):
            for e in summit:
                if e['id'] not in members:continue
                pts=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                parts.append(f'<polygon points="{pts}" fill="{color}"/><text x="{e["x"]}" y="{e["y"]-14}" fill="white" font-size="18">{e["id"]} ({e["role"]})</text>')
        for v in movers:
            parts.append(f'<line x1="3490" y1="{v["min"]}" x2="3490" y2="{v["max"]+40}" stroke="#5aa0ff" stroke-dasharray="8 6" stroke-width="4"/>')
        f=self.finish
        parts.append(f'<rect x="{f["left"]}" y="{f["top"]-20}" width="{f["right"]-f["left"]}" height="{f["bottom"]-f["top"]+20}" fill="none" stroke="#ff5050" stroke-width="4"/>'
                     f'<text x="{f["left"]}" y="{f["top"]-28}" fill="#ff8080" font-size="20">summit finish region (section exit)</text>')
        for e in elements:
            if e['id'].startswith('S07'):
                pts=' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
                parts.append(f'<polygon points="{pts}" fill="#556070"/><text x="{e["x"]}" y="{e["y"]-8}" fill="#99a" font-size="16">{e["id"]}</text>')
        for i,role in enumerate(functions):
            parts.append(f'<text x="4500" y="{-12950+i*30}" fill="{colors[i]}" font-size="22">{role}</text>')
        parts.append('<text x="4500" y="-12650" fill="#ccc" font-size="20">Recovery: misses fall to rest ledge / array deck lip,</text>'
                     '<text x="4500" y="-12620" fill="#ccc" font-size="20">or via green ramp to spill deck -> hook -> S07 Crown</text>')
        parts.append('</svg>');page.set_content(''.join(parts));page.set_viewport_size(dict(width=1300,height=1100))
        page.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S08 built (4/4 encounters, connectors incl. summit-approach, recovery); finish region on summit pad; 15 distinct S08 silhouettes; no temporary exit; one blue mover; no hazards; earlier geometry/physics unchanged; no S08 shortcut assigned; overview.png')

    def carriage(self, row):
        return next(e for e in row['state']['simulation']['elements'] if e['id']=='S08-overhang-carriage')

    def overhang_checks(self, trace, offset=0):
        acq=next(e for e in trace['events'] if e['type']=='acquisition' and e['tick']>=offset)
        self.assertEqual(acq['after']['rope'][0]['id'],'S08-overhang-carriage')
        rel=next(e for e in trace['events'] if e['type']=='release' and e['tick']>acq['tick'])
        rows=trace['snapshots'][acq['tick']:rel['tick']+1]
        # Stays attached to the carriage (rope ends on it) while the carriage itself travels.
        self.assertTrue(all(r['state']['simulation']['grapple']['grappled'] and
            r['state']['simulation']['grapple']['segments'][-1]['id']=='S08-overhang-carriage' for r in rows))
        carriage=[self.carriage(r)['y'] for r in rows]
        self.assertGreater(max(carriage)-min(carriage),100)
        self.assertLess(carriage[-1],carriage[0])
        players=[r['state']['simulation']['player'] for r in rows]
        # Below the overhang underside at acquisition, above its deck east of the lip at release.
        self.assertGreater(players[0]['y'],-12390)
        self.assertLess(players[-1]['y'],-12420);self.assertGreater(players[-1]['x'],3420)
        return dict(acquisition_tick=acq['tick'],release_tick=rel['tick'],attached_ticks=len(rows)-1,
            carriage_y_at_acquisition=carriage[0],carriage_y_at_release=carriage[-1],carriage_travel_while_attached=max(carriage)-min(carriage),
            player_at_acquisition=players[0],player_at_release=players[-1],overhang_underside_y=-12390,overhang_lip_x=3420)

    def finish_checks(self, trace):
        rows=trace['snapshots']
        done=next(i for i,r in enumerate(rows) if r['state']['simulation']['stats']['completed'])
        p=rows[done]['state']['simulation']['player'];f=self.finish
        self.assertTrue(f['left']<=p['x']<=f['right'] and f['top']<=p['y']<=f['bottom'],p)
        before=rows[done-1]['state']['simulation']['player']
        self.assertFalse(rows[done-1]['state']['simulation']['stats']['completed'])
        self.assertFalse(rows[done]['state']['simulation']['grapple']['grappled'])
        # Completion freezes the climb: no later movement.
        self.assertTrue(all(r['state']['simulation']['player']==p for r in rows[done:]))
        return dict(completion_tick=done,player_at_completion=p,player_before=before,finish_region=f,
            landing_speed=dict(x=p['speedX'],y=p['speedY']))

    def test_02_moving_overhang(self):
        trace,result=self.replay('S08-03-moving-overhang',self.overhang,520,self.deck_bounds,self.ledge,
            targets=[('carriage',(3490,-12338)),('overhang',(3240,-12405)),('array_deck',(4050,-12700))])
        checks=self.overhang_checks(trace)
        self.assertFalse(trace['snapshots'][-1]['state']['simulation']['stats']['completed'])
        self.assertTrue(all(r['carriage']['visible'] and r['overhang']['visible'] for r in result['camera_sightlines'] if 20<=r['tick']<=110))
        self.evidence.write('encounters/S08-03.json',dict(passed=True,moving_target_overhang=checks,
            rest_after='S08-array-deck (stationary against east stop)',final=result['final']))
        print('PASS S08-03: blue carriage acquired below the overhang, held while it rises, released above the lip; settles on array deck; matching replay')

    def test_03_final_landing(self):
        trace,result=self.replay('S08-04-final-landing',self.landing,300,self.finish_bounds,self.deck,
            targets=[('gantry',(3760,-12890)),('summit_pad',(3560,-12760))])
        acq=[a[1] for a in result['acquisitions']]
        self.assertEqual(acq,['S08-summit-gantry'])
        checks=self.finish_checks(trace)
        self.assertTrue(all(r['landmark']['visible'] and r['summit_pad']['visible'] for r in result['camera_sightlines'] if r['tick']>=20))
        self.evidence.write('encounters/S08-04.json',dict(passed=True,controlled_final_landing=checks,
            section_exit='summit finish region (climb completed; no next section)',final=result['final']))
        print('PASS S08-04: gantry pull and release; lands on summit pad inside the finish region; climb completes; matching replay')

    def test_04_section_exit_traversed(self):
        # Full Summit Array from the measured S07 exit pose: S08-01..04 to the summit finish.
        plan=(Task486Tests.brake+[(t+450,e,x,y) for t,e,x,y in Task486Tests.transfer]+
              [(t+960,e,x,y) for t,e,x,y in self.overhang]+[(t+1500,e,x,y) for t,e,x,y in self.landing])
        trace,result=self.replay('S08-section-exit',plan,1800,self.finish_bounds,self.s07_exit,
            bounces=['S08-deflector-ramp'])
        snap=lambda t:trace['snapshots'][t]['state']['simulation']['player']
        for tick,pose in ((450,Task486Tests.footing),(1070,self.ledge),(1500,self.deck)):
            p=snap(tick)
            self.assertAlmostEqual(p['x'],pose[0],places=4);self.assertAlmostEqual(p['y'],pose[1],places=4)
            self.assertEqual((p['speedX'],p['speedY']),(0,0))
        acq=[a[1] for a in result['acquisitions']]
        self.assertEqual(acq,['S08-launch-arm','S08-brake-davit','S08-lamp-hook','S08-mast-yard','S08-overhang-carriage','S08-summit-gantry'])
        overhang=self.overhang_checks(trace,1000)
        checks=self.finish_checks(trace)
        self.evidence.write('encounters/section-exit.json',dict(passed=True,from_='S07-exit rest pose (TASK-484 normal route end)',
            rests={'S08-footing-rest':snap(450),'S08-rest-ledge':snap(1070),'S08-array-deck':snap(1500)},
            acquisitions=acq,overhang=overhang,finish=checks,section_exit_traversed=True,
            next_unbuilt_section_not_required=True,note='S08 is the final section; its exit is the summit finish region'))
        print('PASS section exit: S07 exit -> S08-01 brake -> footing rest -> S08-02 bounce transfer -> rest ledge -> S08-03 carriage overhang -> array deck -> S08-04 summit finish; matching replay')

    def test_05_local_miss_recovery(self):
        short=[(20,'mousedown',3760,-12890),(35,'mouseup',3760,-12890)]
        retry=[(200,'mousedown',3760,-12890),(235,'mouseup',3760,-12890)]
        trace,result=self.replay('S08-04-short-pull-recovery',short+retry,450,self.finish_bounds,self.deck,
            targets=[('gantry',(3760,-12890))])
        rest=trace['snapshots'][199]['state']['simulation']
        self.assertAlmostEqual(rest['player']['x'],3930.8,delta=.01);self.assertAlmostEqual(rest['player']['y'],-12710.8,delta=.01)
        self.assertEqual((rest['player']['speedX'],rest['player']['speedY']),(0,0))
        self.assertFalse(rest['stats']['completed'])
        players=[r['state']['simulation']['player'] for r in trace['snapshots'][:200]]
        self.assertTrue(all(3900<=p['x']<=4240 and p['y']>-12960 for p in players))
        checks=self.finish_checks(trace)
        self.assertGreater(checks['completion_tick'],235)
        self.evidence.write('encounters/recovery.json',dict(passed=True,physical=True,nonlethal=True,no_relocation=True,
            local_miss=dict(input='15-tick gantry pull (too short)',outcome='falls back and slides to the array deck west lip',rest=rest['player']),
            retry=dict(input='35-tick gantry pull from the west lip',finish=checks),
            explicit_routes='Short S08-04 pulls return to the array deck; longer S08-03/S08-04 misses fall via the green ramp onto the spill deck, whose hook returns to the Crown (TASK-486 recovery traces)'))
        print('PASS local miss recovery: short gantry pull falls back onto the array deck (stationary, not completed); retry from the west lip lands in the finish region; matching replay')


class Task488Tests(unittest.TestCase):
    """Summit Array tolerance from labeled isolated starts, with real input."""
    task_id = 'TASK-488'
    setUpClass = classmethod(Task467Tests.setUpClass.__func__)
    load_level = Task476Tests.load_level
    run_attempt = Task473Tests.run_attempt
    test_03_source_hashes = Task467Tests.test_02_source_hashes
    still = dict(speedX=[-.001,.001],speedY=[-.001,.001])

    @classmethod
    def routes(cls):
        # (encounter, start, plan, ticks, exit, critical timing index, aim index, tangent, mechanic)
        # Every aimed surface is a horizontal underside, so its tangent is (1,0).
        return [
            ('S08-01',Task486Tests.s07_exit,Task486Tests.brake,450,
             dict(x=[4290,4450],y=[-11611,-11610],**cls.still),2,2,(1,0),'opposing-anchor braking and release onto the footing rest'),
            ('S08-02',Task486Tests.footing,Task486Tests.transfer,700,
             dict(x=[3070,3410],y=[-12091,-12090],**cls.still),2,2,(1,0),'angled bounce then airborne mast-yard grapple'),
            ('S08-03',Task487Tests.ledge,Task487Tests.overhang,520,
             dict(x=[3900,4240],y=[-12711,-12710],**cls.still),1,0,(1,0),'moving carriage attachment over the overhang'),
            ('S08-04',Task487Tests.deck,Task487Tests.landing,300,
             Task487Tests.finish_bounds,1,0,(1,0),'final gantry pull and summit landing')]

    def make_input(self, route, device='desktop', delta=0, offset=0, plan=None, ticks=None, bounds=None):
        from grapple_over_verify import metadata
        name,start,nominal,length,exit_bounds,critical,aim,tangent,_=route
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=self.level,
            player=dict(x=start[0],y=start[1],speedX=0,speedY=0)),inputs=[],
            ticks=ticks or length,expected_exit=bounds or exit_bounds,required_events=['acquisition','release'])
        m['metadata'].update(compact_contacts=True,snapshot_contacts=True)
        if device=='touch': m['metadata']['viewport']=dict(width=844,height=390)
        # A rope only follows its press, so the aim shift also moves the paired release.
        for i,(tick,event,x,y) in enumerate(plan or nominal):
            if plan is None and i==critical: tick+=delta
            if plan is None and i in (aim,aim+1): x+=offset*tangent[0];y+=offset*tangent[1]
            if device=='touch': event={'mousedown':'touchstart','mouseup':'touchend'}[event]
            m['inputs'].append(dict(tick=tick,event=event,world=dict(x=x,y=y)))
        return m

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s08_mechanics
        self.load_level()
        suite=dict(section='S08',source_hashes=hashes(),level_sha256=hashes()['mountain.js'],
            proof_kind='isolated encounter placement only; not continuous completion',encounters={},
            negative_control='negative-control.json',recovery=['clips/recovery-desktop/input.json','clips/recovery-touch/input.json',
            'clips/recovery-spill-desktop/input.json'],shortcuts=None,
            shortcut_note='No S08 shortcut exists (manifest shortcuts are S03/S07 only), so none is archived.',
            starts={r[0]:dict(x=r[1][0],y=r[1][1]) for r in self.routes()},
            critical_inputs={r[0]:dict(timing_index=r[5],aim_index=r[6],tangent=r[7],mechanic=r[8]) for r in self.routes()})
        failures=[]
        for route in self.routes():
            encounter=route[0];attempts=[];suite['encounters'][encounter]=attempts
            for device in ('desktop','touch'):
                for variant,delta,offset in [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]:
                    name=f'{encounter}-{device}-{variant}'
                    prefix=('clips/' if variant=='nominal' else 'attempts/')+name
                    m=self.make_input(route,device,delta,offset)
                    trace,success,reason=self.run_attempt(m,prefix,variant=='nominal')
                    mechanics=check_s08_mechanics(encounter,trace,required=False)
                    if success:
                        try: check_s08_mechanics(encounter,trace)
                        except ValueError as error: success=False;reason=str(error)
                    attempts.append(dict(name=name,device=device,variant=variant,critical_input_index=route[5],
                        aim_input_index=route[6],timing_delta=delta,tangent_aim_delta=offset,surface_tangent=route[7],
                        input=prefix+'/input.json',trace=prefix+'/trace.json',success=success,reason=reason,
                        mechanic_events=mechanics,final=trace['snapshots'][-1]['state']['simulation']['player']))
                    self.evidence.write('manifest.json',suite)
                    print('ATTEMPT',name,'PASS' if success else 'FAIL',reason,flush=True)
                group=[a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:])<2:
                    failures.append(encounter+' '+device)
        # Combined-control omission: launch-arm throw only, with the opposing-davit brake left out.
        route=self.routes()[0]
        m=self.make_input(route,plan=route[2][:2],ticks=1500)
        trace,success,reason=self.run_attempt(m,'clips/negative',True)
        players=[r['state']['simulation']['player'] for r in trace['snapshots']]
        final=players[-1];step=max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a,b in zip(players,players[1:]))
        mechanics=check_s08_mechanics('S08-01',trace,required=False)
        self.evidence.write('negative-control.json',dict(name='omitted brake: S08-brake-davit press/release left out',
            input='clips/negative/input.json',trace='clips/negative/trace.json',failed_intended_exit=not success,
            unchanged_physics=True,source_hashes=hashes(),reason=reason,intended_exit=route[4],
            event_types=sorted({e['type'] for e in trace['events']}),mechanic_events=mechanics,
            max_tick_displacement=step,final_player=final,
            scope='Same start, physics and launch input; without the brake the player overshoots the footing rest, '
                  'falls physically and rests on the S08 spill deck. Alternative routes are not ruled out.'))
        self.assertFalse(success);self.assertIn('expected exit mismatch',reason)
        self.assertNotIn('S08-brake-davit',mechanics['acquisitions'])
        self.assertLess(step,60)
        self.assertAlmostEqual(final['y'],-11051.7,delta=.5)
        self.assertEqual(failures,[])
        print('PASS S08 four encounters: both viewports nominal + >=2/4 variants; braking; bounce transfer; moving overhang; final landing; omitted-brake negative control')

    def test_02_recovery(self):
        from grapple_over_verify import execute, check_s08_mechanics
        self.load_level()
        deck=self.routes()[3]
        retry=[(20,'mousedown',3760,-12890),(35,'mouseup',3760,-12890),(200,'mousedown',3760,-12890),(235,'mouseup',3760,-12890)]
        spill=Task486Tests.brake[:2]+[(1500,'mousedown',5000,-11440),(1530,'mouseup',5000,-11440)]
        cases=[('recovery-desktop','desktop',deck,retry,450,deck[4]),('recovery-touch','touch',deck,retry,450,deck[4]),
               ('recovery-spill-desktop','desktop',self.routes()[0],spill,1900,
                dict(x=[5490,5780],y=[-10191,-10190],**self.still))]
        for name,device,route,plan,ticks,bounds in cases:
            m=self.make_input(route,device,plan=plan,ticks=ticks,bounds=bounds)
            trace,success,reason=self.run_attempt(m,'clips/'+name,True)
            self.assertTrue(success,reason)
            replay=execute(m,self.browser,self.url,str(self.evidence.path('clips/'+name+'/replay')))
            self.assertEqual(trace,replay)
            players=[r['state']['simulation']['player'] for r in trace['snapshots']]
            step=max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a,b in zip(players,players[1:]))
            self.assertLess(step,60)
            miss=players[199] if name.startswith('recovery-d') or name.startswith('recovery-t') else players[1499]
            self.evidence.write('clips/'+name+'/result.json',dict(passed=True,matching_traces=True,no_relocation=True,
                max_tick_displacement=step,rest_after_miss=miss,mechanic_events=check_s08_mechanics(route[0],trace,required=False),
                final=players[-1],event_types=sorted({e['type'] for e in trace['events']})))
            print('PASS '+name+': physical miss, real-input retry reaches the intended rest; matching replay; no relocation')


# Pre-TASK-547 revision whose S01 is the layout-v2 Foundations (TASK-505..507).
V2_S01_REVISION = '28b65fd'
# What happened to every static v2 S01 solid in the layout-v3 rebuild (TASK-547).
V2_S01_DISPOSITION = {
    'S01-entry-pad':('converted-to-bounce','S01-01 launch: same 200x40 box, now green; S02 v2 fall lines still land on it'),
    'S01-yard-pad':('converted-to-bounce','S01-01 landing / S01-02 launch: moved to (3900,-880), 300x40 green yard bouncer'),
    'S01-loading-pad':('deleted','v2 S01-02 rest after the deflector; the v3 S01-02 ends in flight off the green deflector'),
    'S01-gantry-pad':('deleted','v2 S01-03/04 rest; the v3 S01-03/04 (TASK-548) swing from green hooks onto the green exit pad'),
    'S01-exit':('converted-to-bounce','Kept at (4060,-1620) as the v2 Switchback S02-01 start reference, now green; no S01 v3 route uses it')}
# Elements TASK-548 added to complete the v3 S01 (no v2 counterpart).
V3_S01_TASK548_ADDED = ('S01-gantry-hook','S01-crown-hook','S01-exit-pad','S01-floor','S01-exit-drag')


class FoundationsV3Checks:
    """Layout-v3 Foundations opening (S01-01/02) from the base spawn with real input.

    Shared by Task547Tests and by the re-specced Task505Tests (same cases, task-local evidence).
    """
    S01_01_V3 = [(10,'mousedown',2700,-790),(70,'mouseup',2700,-790)]
    S01_02_V3 = [(255,'mousedown',4500,-1730),(334,'mouseup',4500,-1730)]
    V3_MOVERS = ('S01-hoist','S01-lift')
    V3_BAND = (918, 972)
    # Exit boxes (also the manifest encounter exits): just off the yard bounce, rising;
    # and rebounding up-left off the green deflector.
    S01_01_EXIT = dict(x=[3990,4060], y=[-910,-880], speedX=[.5,2], speedY=[-1,-.01])
    S01_02_EXIT = dict(x=[4600,4800], y=[-2200,-1950], speedX=[-2,-.1], speedY=[-3,-.1])
    S01_01_TICKS, S01_02_TICKS = 255, 370

    def report(self):
        page = self.open()
        return page.evaluate('''() => {const m=GRAPPLE_OVER_MOUNTAIN, level=validateMountainManifest(m);
            floors=[loadFixedLevel(level)];
            return {manifest:m, runtime:floors[0].level, report:layoutV2Report(m),
                colliders:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole}))};}''')

    def v2_s01(self):
        """The layout-v2 S01 as committed before the rebuild, evaluated from git, not copied."""
        source = subprocess.check_output(['git','show',V2_S01_REVISION+':mountain.js'], cwd=ROOT, text=True)
        page = self.open()
        return page.evaluate('''src => {const m=new Function(src+';return GRAPPLE_OVER_MOUNTAIN')(),
            s=m.sections[0], movers=new Set(m.geometry.movers.map(v=>v.element));
            return {section:s, report:layoutV2Report(m).sections[0],
                elements:m.geometry.elements.filter(e=>e.id.startsWith('S01-')),
                staticSolids:m.geometry.elements.filter(e=>e.id.startsWith('S01-') && e.role==='solid' && !movers.has(e.id)).map(e=>e.id),
                movers:[...movers].filter(id=>id.startsWith('S01-'))}}''', source)

    def test_01_geometry_and_rules(self):
        r = self.report(); v2 = self.v2_s01()
        m = r['manifest']; elements = m['geometry']['elements']
        s01 = m['sections'][0]
        # TASK-548 completed S01-03/04 and the exit; the S02 entrance connector stays planned.
        self.assertEqual((s01['designVersion'], s01['status']), (3, 'built'))
        self.assertEqual([e['status'] for e in m['encounters'][:4]], ['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][:5]], ['built']*4+['planned'])
        self.assertNotIn('solidExceptions', s01)
        self.assertEqual(r['runtime']['elements'], elements)
        for actual, expected in zip(r['colliders'], elements):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S01-')]
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S01-')}
        self.assertEqual(set(movers), set(self.V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        enc = {e['id']:e for e in m['encounters'][:2]}
        self.assertEqual(enc['S01-01']['start'], {'x':2160,'y':0}); self.assertEqual(m['spawn'], {'x':2160,'y':0})
        for e in enc.values():
            self.assertTrue(any(x in movers for x in e['elements']), e['id'])
            self.assertTrue(any(roles[x] == 'green bounce' for x in e['elements']), e['id'])
        self.assertEqual(enc['S01-01']['exit'], dict(left=3990,right=4060,top=-910,bottom=-880))
        self.assertEqual(enc['S01-02']['exit'], dict(left=4600,right=4800,top=-2200,bottom=-1950))
        sec = r['report']['sections'][0]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S01', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        self.assertEqual(r['report']['v3'][0], 'S01')
        self.assertFalse(r['report']['failed'])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.V3_BAND))
        self.assertEqual([g['id'] for g in gaps], ['S01-01-hoist','S01-02-lift','S01-03-gantry','S01-04-crown'])
        for g in gaps:
            self.assertTrue(self.V3_BAND[0] <= g['distance'] <= self.V3_BAND[1], g)
        gaps = gaps[:2]
        # Since TASK-548 the fall points land on the green S01 floor bouncers (checked there).
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints'][:3]
        self.assertEqual([f['id'] for f in falls], ['S01-01-short','S01-02-short','S01-02-overshoot'])
        for f in falls:
            self.assertEqual((f['dragZones'], f['firstBouncer']), (['S01-yard-drag'], 'S01-floor'), f)
        self.assertEqual(sec['rules']['strayDrag']['measured']['dragZones'][0]['fallPoints'][:3],
            ['S01-01-short','S01-02-short','S01-02-overshoot'])
        self.assertEqual(sec['rules']['moverCoverage']['measured']['encounters'], ['S01-01','S01-02'])
        # v2/v3 ratio against the v2 S01-01/02 gaps recorded by TASK-505 (and the v2 source).
        v2_geometry = json.loads((ROOT/'artifacts/TASK-505/geometry.json').read_text())
        v2_gaps = {g['id']:g for g in v2_geometry['manifest_section']['gaps']}
        self.assertEqual([v2_gaps[k] for k in ('S01-01-hoist','S01-02-lift')], v2['section']['gaps'][:2])
        dist = lambda g: ((g['to']['x']-g['from']['x'])**2+(g['to']['y']-g['from']['y'])**2) ** .5
        v2_d = {k:dist(v2_gaps[k]) for k in ('S01-01-hoist','S01-02-lift')}
        v3_d = {g['id']:g['distance'] for g in gaps}
        v2_mean, v3_mean = sum(v2_d.values())/2, sum(v3_d.values())/2
        ratio = v3_mean/v2_mean
        self.assertGreaterEqual(ratio, 2.0)
        per_gap = {k:v3_d[k]/v2_d[k] for k in v3_d}
        self.assertTrue(all(x >= 2.0 for x in per_gap.values()), per_gap)
        # Every static v2 S01 solid is deleted or converted to a green bouncer.
        self.assertEqual(sorted(v2['staticSolids']), sorted(V2_S01_DISPOSITION))
        self.assertEqual(sorted(v2['movers']), sorted(self.V3_MOVERS))
        by_id = {e['id']:e for e in own}
        mapping = []
        for old in v2['staticSolids']:
            kind, why = V2_S01_DISPOSITION[old]
            now = by_id.get(old)
            if kind == 'deleted': self.assertIsNone(now, old)
            else: self.assertEqual(now['role'], 'bounce', old)
            mapping.append(dict(id=old, v2_role='solid', disposition=kind, v3_role=now['role'] if now else None, reason=why))
        v2_ids = {e['id'] for e in v2['elements']}
        deleted_other = sorted(v2_ids - set(by_id) - set(V2_S01_DISPOSITION))
        self.assertEqual(deleted_other, ['S01-boom-hook','S01-crane-hook','S01-jib-hook'])
        self.assertEqual(sorted(set(by_id) - v2_ids), sorted(V3_S01_TASK548_ADDED))
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=['S01-01','S01-02'],
            gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances=v3_d, v2_gap_distances=v2_d, v2_gap_source='artifacts/TASK-505/geometry.json manifest_section.gaps',
            v2_mean_gap=v2_mean, v3_mean_gap=v3_mean, v3_over_v2_mean_ratio=ratio, v3_over_v2_per_gap=per_gap,
            ratio_at_least_2=True, direction_note='S01-04 is built since TASK-548; the direction rule reads its exit-pad box'))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s01, encounters=m['encounters'][:4],
            elements=own, movers=list(movers.values()), roles=roles, gray_solids=gray, gray_solid_count=len(gray),
            runtime_matches_manifest=True, v2_revision=V2_S01_REVISION, v2_static_solids=v2['staticSolids'],
            v2_solid_disposition=mapping, v2_bounce_hooks_deleted=deleted_other, planned=[],
            task548_added=sorted(V3_S01_TASK548_ADDED)))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="1600 -2380 4400 2475" style="background:#111827">']
        for e in own:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            op = ' fill-opacity="0.45"' if e['role'] == 'drag' else ''
            parts.append(f'<polygon points="{pts}" fill="{colors[roles[e["id"]]]}"{op} stroke="white" stroke-width="3"/>'
                         f'<text x="{e["x"]}" y="{e["y"]-30}" fill="white" font-size="34">{e["id"]} ({roles[e["id"]]})</text>')
        for v in movers.values():
            e = by_id[v['element']]
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]+60}" x2="{e["x"]+60+dx}" y2="{e["y"]+60+dy}" stroke="#2f86ff" stroke-width="6" stroke-dasharray="14,8"/>')
        for g in s01['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="10,8"/>')
        for f in s01['fallPoints']:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="40" stroke="#fb923c" stroke-width="3" stroke-dasharray="4,10"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="14" fill="#fb923c"/><text x="{f["x"]+20}" y="{f["y"]}" fill="#fb923c" font-size="28">{f["id"]}</text>')
        for e in m['encounters'][:2]:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="5"/>'
                         f'<text x="{b["left"]}" y="{b["bottom"]+40}" fill="#f472b6" font-size="28">{e["id"]} exit</text>')
        parts.append('<circle cx="2160" cy="0" r="18" fill="#ff7a1a"/>')
        for i, t in enumerate(['S01 Foundations v3 (designVersion 3) — zero gray solids; S01-01: green entry pad -> blue hoist -> green yard bounce',
                'S01-02: blue lift off the yard rebound -> green deflector rebound. Yellow dashes = gaps %s of 1080 (v3/v2 mean %.3f)'
                % ('/'.join(str(round(d)) for d in v3_d.values()), ratio),
                'Orange = declared fall points over the yellow drag zone; pink = exit boxes; S01-03/04 in TASK-548']):
            parts.append(f'<text x="1640" y="{-2320+i*48}" fill="#67e8f9" font-size="38">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=VIEWPORT); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S01 designVersion 3; gray solids', len(gray), '; roles', sorted(set(roles.values())),
              '; all 7 v3 rules pass; gaps', [round(d,1) for d in v3_d.values()], '; v3/v2 mean ratio', round(ratio,4),
              '; v2 solids', {x['id']:x['disposition'] for x in mapping}, '; overview.png')

    def replay_v3(self, name, plan, ticks, bounds, density_until=None):
        from grapple_over_verify import metadata, execute, check_trace
        m = dict(metadata=metadata('base-start'),
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=True)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        # The in-memory full traces are identical; keep compact per-tick hashes plus the asserted fields.
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, Task506Tests.compact(self, t))
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce') or (e['type']=='contact' and element in self.V3_MOVERS):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    mover=element in self.V3_MOVERS, player=e['after']['simulation']['player'], rope=e['after']['rope']))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        # Longest stretch without an acquisition, bounce or mover contact (LAYOUT_V3_DENSITY_CAP_TICKS).
        # The settle at the section exit is not a stretch of the route: density_until ends it.
        horizon = density_until or ticks
        marks = sorted({0, horizon, *[x['tick'] for x in mechanics if x['type'] != 'release' and x['tick'] <= horizon]})
        stretch = max(b-a for a, b in zip(marks, marks[1:]))
        self.assertLessEqual(stretch, 254)
        result = dict(passed=True, matching_traces=True, trusted_inputs=True,
            proof_kind='base-start: production restart at base spawn (2160,0); no setup placement; real mouse input',
            placement=None, not_continuous_completion_claim=True,
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[{k:x[k] for k in ('tick','type','element','mover','player')} for x in mechanics],
            longest_stretch_without_mechanic_ticks=stretch, density_cap_ticks=254,
            final=players[-1], expected_exit=bounds, final_in_exit_box=True,
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        return trace, players, mechanics, result

    def reach_v3(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.V3_BAND[0] <= distance <= self.V3_BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y']), anchor=a['rope'][0], band=list(self.V3_BAND))

    def test_02_s01_01_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-01', self.S01_01_V3, self.S01_01_TICKS, self.S01_01_EXIT)
        kinds = [(e['type'],e['element']) for e in mech if e['element'] != 'S01-entry-pad']
        self.assertEqual(kinds, [('acquisition','S01-hoist'),('release','S01-hoist'),('bounce','S01-yard-pad')])
        self.assertLessEqual(mech[0]['tick'], 120)
        rope = [s['state']['rope'] for s in trace['snapshots'][15:70]]
        xs = [r[0]['x'] for r in rope if r and r[0]['id']=='S01-hoist']
        self.assertGreater(xs[-1]-xs[0], 1)
        bounce = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']=='S01-yard-pad')
        before, after = bounce['before']['simulation']['player'], bounce['after']['simulation']['player']
        self.assertGreater(before['speedY'], 0); self.assertLess(after['speedY'], 0)
        reach = self.reach_v3(players, mech, 10, 'S01-hoist')
        result.update(first_interaction_tick=mech[0]['tick'], mover_anchor_travel_while_attached=xs[-1]-xs[0],
            acquisition_reach=reach, yard_bounce=dict(tick=bounce['tick'], before=before, after=after))
        self.evidence.write('encounters/S01-01/result.json', result)
        print('PASS S01-01: base spawn; blue hoist acquisition', round(reach['distance'],1), 'at tick', reach['acquisition_tick'],
              '; green yard bounce at tick', bounce['tick'], '; final', {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')},
              'in exit box; longest dull stretch', result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def test_03_s01_02_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-02', self.S01_01_V3+self.S01_02_V3, self.S01_02_TICKS, self.S01_02_EXIT)
        kinds = [(e['type'],e['element']) for e in mech if e['element'] != 'S01-entry-pad']
        self.assertEqual(kinds, [('acquisition','S01-hoist'),('release','S01-hoist'),('bounce','S01-yard-pad'),
            ('acquisition','S01-lift'),('release','S01-lift'),('bounce','S01-deflector')])
        start = players[self.S01_01_TICKS]
        for k, (lo, hi) in self.S01_01_EXIT.items():
            self.assertTrue(lo <= start[k] <= hi, (k, start))
        bounce = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']=='S01-deflector')
        before, after = bounce['before']['simulation']['player'], bounce['after']['simulation']['player']
        self.assertGreater(before['speedX'], 0); self.assertLess(after['speedX'], 0)
        rope = [s['state']['rope'] for s in trace['snapshots'][261:334]]
        ys = [r[0]['y'] for r in rope if r and r[0]['id']=='S01-lift']
        self.assertGreater(abs(ys[-1]-ys[0]), 1)
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S01-lift')
        self.assertGreater(lift['tick'], self.S01_01_TICKS)
        reach = self.reach_v3(players, mech, 255, 'S01-lift')
        result.update(segmented_from='S01-01 exit at tick 255 of the same base-start run (no placement)',
            s01_01_exit_at_tick_255=start, deflector_bounce=dict(tick=bounce['tick'], before=before, after=after),
            mover_anchor_travel_while_attached=ys[-1]-ys[0], acquisition_reach=reach)
        self.evidence.write('encounters/S01-02/result.json', result)
        print('PASS S01-02: from the S01-01 exit at tick 255; blue lift acquisition', round(reach['distance'],1),
              'at tick', lift['tick'], '; green deflector rebound at tick', bounce['tick'], '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')


class Task505Tests(FoundationsV3Checks, unittest.TestCase):
    """Foundations opening (S01-01/02), re-specced by TASK-547 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, all shared with Task547Tests via FoundationsV3Checks):
    test_01_geometry_and_rules: v2 rules/rest pads/459-486 gaps -> v3 rules, zero gray solids, 918-972 gaps.
    test_02_s01_01_nominal: hoist onto the yard rest pad -> hoist release onto the green yard bounce.
    test_03_s01_02_nominal: lift + deflector onto the loading pad -> lift off the yard rebound into the
    green deflector rebound. test_04_source_hashes is unchanged.
    """
    task_id = 'TASK-505'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    # Layout-v2 route inputs, kept only for the v2 S01 suites (Task506/507) that layout v3 supersedes.
    S01_01 = [(10,'mousedown',2500,-318),(50,'mouseup',2500,-318)]
    S01_02 = [(190,'mousedown',3400,-530),(242,'mouseup',3400,-530)]
    MOVERS = ('S01-hoist','S01-lift')


class FoundationsV3CompleteChecks:
    """Layout-v3 Foundations S01-03/04, section exit and drag-zone fall recovery (TASK-548).

    Real trusted mouse input from the base spawn, no placement. Shared by Task548Tests and by
    the re-specced Task506Tests (same cases, task-local evidence).
    """
    V3_MOVERS, V3_BAND = FoundationsV3Checks.V3_MOVERS, FoundationsV3Checks.V3_BAND
    S01_01_V3, S01_02_V3 = FoundationsV3Checks.S01_01_V3, FoundationsV3Checks.S01_02_V3
    S01_01_EXIT, S01_02_EXIT = FoundationsV3Checks.S01_01_EXIT, FoundationsV3Checks.S01_02_EXIT
    S01_03_V3 = [(400,'mousedown',5250,-2990),(465,'mouseup',5250,-2990)]
    S01_04_V3 = [(530,'mousedown',5950,-3130),(615,'mouseup',5950,-3130)]
    ROUTE_V3 = S01_01_V3+S01_02_V3+S01_03_V3+S01_04_V3
    # S01-03 ends in flight off the gantry swing; S01-04 lands on the exit pad inside the exit
    # drag zone (LAND) and the full traversal settles there (SETTLE = the manifest exit box).
    S01_03_EXIT = dict(x=[4900,5000], y=[-3540,-3480], speedX=[.5,2], speedY=[-1.5,-.1])
    LAND = dict(x=[6040,6440], y=[-2760,-2700], speedX=[-.001,.001], speedY=[-.5,.5])
    SETTLE = dict(x=[6040,6440], y=[-2730,-2700], speedX=[-.001,.001], speedY=[-.05,.05])
    S01_03_TICKS, S01_04_TICKS, FULL_TICKS = 520, 1100, 1800
    # Naturally mistimed S01-01: the hoist is released after 45 ticks instead of 60. After the
    # player settles on the floor bouncers, a green yard-pad pull and a blue lift pull rejoin.
    FALL_V3 = [(10,'mousedown',2700,-790),(55,'mouseup',2700,-790),(700,'mousedown',3905,-865),(840,'mouseup',3905,-865),
               (845,'mousedown',4500,-1730),(905,'mouseup',4500,-1730)]
    FALL_TICKS, REJOIN_TICK = 928, 700
    YARD_DRAG = dict(left=2520, right=6480, top=-300, bottom=120)
    EXIT_DRAG = dict(left=5960, right=6480, top=-3100, bottom=-2660)
    report = FoundationsV3Checks.report
    replay_v3 = FoundationsV3Checks.replay_v3
    reach_v3 = FoundationsV3Checks.reach_v3

    @staticmethod
    def in_box(p, b):
        """Player circle overlaps a drag zone box (the runtime overlap test for rectangles)."""
        dx = max(b['left']-p['x'], 0, p['x']-b['right']); dy = max(b['top']-p['y'], 0, p['y']-b['bottom'])
        return dx*dx + dy*dy < p['radius']**2

    @staticmethod
    def inside(p, bounds):
        return all(lo <= p[k] <= hi for k, (lo, hi) in bounds.items())

    def kinds(self, mech, after=0):
        return [(e['type'], e['element']) for e in mech if e['element'] != 'S01-entry-pad' and e['tick'] >= after]

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']; s01 = m['sections'][0]
        self.assertEqual((s01['designVersion'], s01['status']), (3, 'built'))
        self.assertNotIn('solidExceptions', s01)
        self.assertEqual([e['status'] for e in m['encounters'][:4]], ['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][:4]], ['built']*4)
        self.assertEqual(m['recoveries'][0]['status'], 'built')
        self.assertEqual(r['runtime']['elements'], elements)
        for actual, expected in zip(r['colliders'], elements):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S01-')]
        by_id = {e['id']:e for e in own}
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S01-')}
        self.assertEqual(set(movers), set(self.V3_MOVERS))
        gray = [e['id'] for e in own if e['role'] == 'solid' and e['id'] not in movers]
        self.assertEqual(gray, [])
        roles = {e['id']:'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce'
                 else 'yellow drag' if e['role'] == 'drag' else e['role'] for e in own}
        self.assertEqual(sorted(set(roles.values())), ['blue mover','green bounce','yellow drag'])
        box = lambda e: dict(left=e['x']+min(p['x'] for p in e['points']), right=e['x']+max(p['x'] for p in e['points']),
                             top=e['y']+min(p['y'] for p in e['points']), bottom=e['y']+max(p['y'] for p in e['points']))
        self.assertEqual(box(by_id['S01-yard-drag']), self.YARD_DRAG)
        self.assertEqual(box(by_id['S01-exit-drag']), self.EXIT_DRAG)
        enc = m['encounters'][:4]
        for a, b in zip(enc, enc[1:]):
            self.assertEqual(b['start']['from'], a['id'])
        for e in enc:
            self.assertTrue(any(roles.get(x) == 'green bounce' for x in e['elements']), e['id'])
        self.assertEqual([e['id'] for e in enc if any(x in movers for x in e['elements'])], ['S01-01','S01-02'])
        self.assertEqual(enc[2]['exit'], dict(left=4900,right=5000,top=-3540,bottom=-3480))
        # The S01 exit is the green exit pad inside the exit drag zone; the exit box sits on its top.
        pad, zone, exit_box = box(by_id['S01-exit-pad']), self.EXIT_DRAG, enc[3]['exit']
        self.assertEqual(roles['S01-exit-pad'], 'green bounce')
        self.assertTrue(zone['left'] <= pad['left'] and pad['right'] <= zone['right'] and zone['top'] < pad['top'] < zone['bottom'])
        self.assertEqual(exit_box, dict(left=6040,right=6440,top=-2730,bottom=-2700))
        self.assertEqual((exit_box['left'], exit_box['right'], exit_box['bottom']), (pad['left'], pad['right'], pad['top']))
        self.assertEqual([self.SETTLE[k] for k in ('x','y')], [[exit_box['left'],exit_box['right']],[exit_box['top'],exit_box['bottom']]])
        # Base floor bouncers: green, resting on the base catch floor (y 120), under the yard drag zone.
        floor = box(by_id['S01-floor'])
        self.assertEqual((roles['S01-floor'], floor['bottom']), ('green bounce', 120))
        self.assertEqual((floor['left'], floor['right']), (self.YARD_DRAG['left'], self.YARD_DRAG['right']))
        sec = r['report']['sections'][0]
        self.assertEqual((sec['id'], sec['designVersion'], sec['passed'], sec['errors'], sec['range']), ('S01', 3, True, [], 1080))
        self.assertEqual(sorted(sec['rules']), sorted(['graySolid','moverCoverage','direction','gapBand','dragUnderFall','strayDrag','extent']))
        for name, rule in sec['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        direction = sec['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('right', 'right'))
        self.assertEqual(sec['rules']['graySolid']['measured']['staticSolids'], [])
        gaps = sec['rules']['gapBand']['measured']['gaps']
        self.assertEqual(sec['rules']['gapBand']['measured']['target'], list(self.V3_BAND))
        self.assertEqual([g['id'] for g in gaps], ['S01-01-hoist','S01-02-lift','S01-03-gantry','S01-04-crown'])
        for g in gaps:
            self.assertTrue(self.V3_BAND[0] <= g['distance'] <= self.V3_BAND[1], g)
        falls = sec['rules']['dragUnderFall']['measured']['fallPoints']
        self.assertEqual([f['id'] for f in falls], ['S01-01-short','S01-02-short','S01-02-overshoot','S01-03-early','S01-04-short'])
        self.assertEqual(sorted({f['encounter'] for f in falls}), ['S01-01','S01-02','S01-03','S01-04'])
        under = {}
        for f in falls:
            self.assertEqual(f['firstBouncer'], 'S01-floor', f)
            self.assertIn('S01-yard-drag', f['dragZones'], f)
            for d in f['dragZones']:
                b = box(by_id[d])
                # Directly below: the zone spans the fall column and lies between the point and the floor.
                self.assertTrue(b['left'] < f['x']-18 and f['x']+18 < b['right'] and b['bottom'] > f['y'] and b['top'] < f['firstBouncerTop'], (f, d))
            under[f['id']] = dict(x=f['x'], y=f['y'], dragZones=f['dragZones'], firstBouncer=f['firstBouncer'])
        self.assertEqual(sec['rules']['strayDrag']['measured']['dragZones'],
            [dict(id='S01-yard-drag', fallPoints=[f['id'] for f in falls]), dict(id='S01-exit-drag', fallPoints=['S01-04-short'])])
        self.assertEqual(r['report']['v3'][0], 'S01')
        self.assertFalse(r['report']['failed'])
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report designVersion 3 rules (TASK-546)',
            section=sec, all_applicable_rules_passed=True, encounters=[e['id'] for e in enc], direction=direction,
            gray_solid_count=0, gap_targets_reference='LAYOUT_V3_GAP_TARGETS[1080] = 918-972 (artifacts/TASK-544/calibration.json)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps}, fall_points_over_drag_zones=under,
            every_fall_point_has_drag_zone_below=True, drag_zones_only_under_fall_points=True))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s01, encounters=enc,
            connectors=m['connectors'][:5], recovery=m['recoveries'][0], elements=own, movers=list(movers.values()),
            roles=roles, gray_solids=gray, gray_solid_count=len(gray), runtime_matches_manifest=True,
            direction=direction, exit=dict(pad='S01-exit-pad', pad_box=pad, drag_zone='S01-exit-drag', drag_box=zone, exit_box=exit_box),
            base_floor_bouncers=dict(id='S01-floor', box=floor, drag_zone='S01-yard-drag', drag_box=self.YARD_DRAG),
            fall_points=under, task548_added=sorted(V3_S01_TASK548_ADDED)))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','yellow drag':'#facc15'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="-280 -3830 7040 3960" style="background:#111827">',
                 '<rect x="0" y="120" width="6480" height="60" fill="#4b5563"/>']
        for e in sorted(own, key=lambda e: e['role'] != 'drag'):
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            op = ' fill-opacity="0.35"' if e['role'] == 'drag' else ''
            b = box(e)
            parts.append(f'<polygon points="{pts}" fill="{colors[roles[e["id"]]]}"{op} stroke="white" stroke-width="4"/>'
                         f'<text x="{b["left"]}" y="{b["top"]-20 if e["role"] != "drag" else b["top"]+60}" fill="white" font-size="46">{e["id"]}</text>')
        for g in s01['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="7" stroke-dasharray="18,12"/>')
        for f in s01['fallPoints']:
            parts.append(f'<line x1="{f["x"]}" y1="{f["y"]}" x2="{f["x"]}" y2="80" stroke="#fb923c" stroke-width="5" stroke-dasharray="6,16"/>'
                         f'<circle cx="{f["x"]}" cy="{f["y"]}" r="24" fill="#fb923c"/><text x="{f["x"]+30}" y="{f["y"]}" fill="#fb923c" font-size="40">{f["id"]}</text>')
        for e in enc:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]}" fill="none" stroke="#f472b6" stroke-width="8"/>')
        parts.append('<circle cx="2160" cy="0" r="30" fill="#ff7a1a"/>')
        for i, t in enumerate(['S01 Foundations layout v3 complete (direction right, zero gray solids): hoist -> yard pad -> lift -> deflector',
                '-> green gantry hook -> green crown hook -> green exit pad inside the exit drag zone. Gaps (yellow) %s of 1080'
                % '/'.join(str(round(g['distance'])) for g in gaps),
                'Orange = declared fall points, each over a yellow drag zone and the green floor bouncers; pink = encounter exits']):
            parts.append(f'<text x="-240" y="{-3760+i*64}" fill="#67e8f9" font-size="54">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=VIEWPORT); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S01 built 4/4 designVersion 3; gray solids 0; direction right; all 7 v3 rules pass; gaps',
              [round(g['distance'],1) for g in gaps], '; fall points', list(under), 'each over', sorted({d for f in falls for d in f['dragZones']}),
              'onto S01-floor; exit pad inside S01-exit-drag; overview.png')

    def test_02_s01_03_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-03', self.S01_01_V3+self.S01_02_V3+self.S01_03_V3,
                                                      self.S01_03_TICKS, self.S01_03_EXIT)
        self.assertEqual(self.kinds(mech), [('acquisition','S01-hoist'),('release','S01-hoist'),('bounce','S01-yard-pad'),
            ('acquisition','S01-lift'),('release','S01-lift'),('bounce','S01-deflector'),
            ('acquisition','S01-gantry-hook'),('release','S01-gantry-hook')])
        start = players[FoundationsV3Checks.S01_02_TICKS]
        self.assertTrue(self.inside(start, self.S01_02_EXIT), start)
        press = players[400]
        self.assertLess(press['speedX'], 0)
        release = next(e for e in mech if e['type']=='release' and e['element']=='S01-gantry-hook')
        self.assertGreater(release['player']['speedX'], 0)
        reach = self.reach_v3(players, mech, 400, 'S01-gantry-hook')
        result.update(encounter='S01-03', segmented_from='S01-02 exit at tick 370 of the same base-start run (no placement)',
            s01_02_exit_at_tick_370=start, player_at_press=press, gantry_release=release['player'],
            swing_reverses_left_to_right=True, acquisition_reach=reach)
        self.evidence.write('encounters/S01-03/result.json', result)
        print('PASS S01-03: from the S01-02 exit at tick 370; green gantry hook', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; vx', round(press['speedX'],2), '->', round(release['player']['speedX'],2), '; final',
              {k:round(result['final'][k],2) for k in ('x','y','speedX','speedY')}, 'in exit box; longest dull stretch',
              result['longest_stretch_without_mechanic_ticks'], '; identical replay; trusted input')

    def landing(self, trace, players, mech):
        land = next(e for e in mech if e['type']=='bounce' and e['element']=='S01-exit-pad')
        nxt = next((e['tick'] for e in mech if e['type']=='bounce' and e['element']=='S01-exit-pad' and e['tick'] > land['tick']), len(players)-1)
        peak = min(p['y'] for p in players[land['tick']:nxt])
        for t in range(land['tick'], len(players)):
            self.assertTrue(self.in_box(players[t], self.EXIT_DRAG), (t, players[t]))
            self.assertLess(abs(players[t]['speedX']), .01)
        self.assertGreater(peak - players[0]['radius'], self.EXIT_DRAG['top'])
        before = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land['tick'])['before']['simulation']['player']
        return dict(tick=land['tick'], before=before, after=land['player'], first_rebound_peak_y=peak,
            first_rebound_inside_exit_drag=True, exit_drag=self.EXIT_DRAG)

    def test_03_s01_04_nominal(self):
        trace, players, mech, result = self.replay_v3('S01-04', self.ROUTE_V3, self.S01_04_TICKS, self.LAND, density_until=650)
        kinds = self.kinds(mech, 520)
        self.assertEqual(kinds[:3], [('acquisition','S01-crown-hook'),('release','S01-crown-hook'),('bounce','S01-exit-pad')])
        self.assertEqual(set(kinds[2:]), {('bounce','S01-exit-pad')})
        start = players[self.S01_03_TICKS]
        self.assertTrue(self.inside(start, self.S01_03_EXIT), start)
        reach = self.reach_v3(players, mech, 530, 'S01-crown-hook')
        land = self.landing(trace, players, mech)
        self.assertLessEqual(land['tick'], 650)
        result.update(encounter='S01-04', segmented_from='S01-03 exit at tick 520 of the same base-start run (no placement)',
            s01_03_exit_at_tick_520=start, acquisition_reach=reach, exit_pad_landing=land)
        self.evidence.write('encounters/S01-04/result.json', result)
        print('PASS S01-04: from the S01-03 exit at tick 520; green crown hook', round(reach['distance'],1), 'at tick',
              reach['acquisition_tick'], '; lands on the green exit pad at tick', land['tick'], 'inside S01-exit-drag; final',
              {k:round(result['final'][k],3) for k in ('x','y','speedX','speedY')}, '; identical replay; trusted input')

    def test_04_full_traversal(self):
        trace, players, mech, result = self.replay_v3('S01-full', self.ROUTE_V3, self.FULL_TICKS, self.SETTLE, density_until=650)
        self.assertEqual([(e['element'], e['tick']) for e in mech if e['type']=='acquisition' and e['element'] != 'S01-entry-pad'],
            [('S01-hoist',15),('S01-lift',260),('S01-gantry-hook',405),('S01-crown-hook',535)])
        exits = {}
        for name, tick, bounds in (('S01-01',255,self.S01_01_EXIT),('S01-02',370,self.S01_02_EXIT),('S01-03',520,self.S01_03_EXIT)):
            self.assertTrue(self.inside(players[tick], bounds), (name, players[tick]))
            exits[name] = dict(tick=tick, player=players[tick], box=bounds)
        self.assertNotIn('S01-floor', {e['element'] for e in mech})
        land = self.landing(trace, players, mech)
        # Settled: from this tick to the end the player stays in the exit box with |vy| <= 0.05, vx = 0.
        settle = next(t for t in range(land['tick'], self.FULL_TICKS+1)
                      if all(self.inside(players[u], self.SETTLE) for u in range(t, self.FULL_TICKS+1)))
        self.assertLessEqual(settle, 1500)
        tail = players[settle:]
        exits['S01-04'] = dict(tick=settle, player=players[settle], box=self.SETTLE)
        result.update(encounter='S01 full traversal', encounter_exits=exits, exit_pad_landing=land,
            section_exit=dict(element='S01-exit-pad', drag_zone='S01-exit-drag', settle_tick=settle,
                settled_ticks=len(tail), settled_y_range=[min(p['y'] for p in tail), max(p['y'] for p in tail)],
                settled_max_abs_speedY=max(abs(p['speedY']) for p in tail), settled_max_abs_speedX=max(abs(p['speedX']) for p in tail),
                rest=players[-1], settle_box=self.SETTLE, inside_exit_drag=True),
            section_exit_reached=True, settled_at_section_exit=True, floor_contact=False,
            reaches=[self.reach_v3(players, mech, t, el) for t, el in ((10,'S01-hoist'),(255,'S01-lift'),(400,'S01-gantry-hook'),(530,'S01-crown-hook'))])
        self.evidence.write('encounters/S01-full/result.json', result)
        print('PASS full S01: base spawn; exits', {k:v['tick'] for k,v in exits.items()}, '; exit pad landing tick', land['tick'],
              '; settled from tick', settle, 'for', len(tail), 'ticks at', {k:round(players[-1][k],3) for k in ('x','y','speedX','speedY')},
              'inside S01-exit-drag; no floor contact; identical replay; trusted input')

    def test_05_fall_through_drag_and_rejoin(self):
        # Density is a nominal-route rule; the miss run is measured only up to the mistimed release.
        trace, players, mech, result = self.replay_v3('fall', self.FALL_V3, self.FALL_TICKS, self.S01_02_EXIT, density_until=60)
        release = next(e for e in mech if e['type']=='release')
        self.assertEqual((release['element'], release['tick']), ('S01-hoist', 55))
        floor = [e for e in mech if e['type']=='bounce' and e['element']=='S01-floor']
        self.assertTrue(floor)
        land = floor[0]['tick']
        apex_tick = min(range(55, land), key=lambda t: players[t]['y'])
        apex = players[apex_tick]
        entry = next(t for t in range(56, land) if self.in_box(players[t], self.YARD_DRAG))
        self.assertTrue(all(self.in_box(players[t], self.YARD_DRAG) for t in range(entry, self.REJOIN_TICK)))
        before = players[entry-1]
        contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
        at_floor = contact['before']['simulation']['player']
        self.assertGreater(abs(before['speedX']), .5)
        self.assertLess(abs(at_floor['speedX']), .01*abs(before['speedX']))
        self.assertLess(at_floor['speedY'], before['speedY'])
        # Per-tick damping while airborne in the zone: vx x0.8 exactly; vy below free fall.
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, entry+8) if abs(players[t]['speedX']) > 1e-9]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios)
        rest_y = floor[0]['player']['y']
        fall_height = rest_y - apex['y']
        bounces = [e for e in floor if e['tick'] < self.REJOIN_TICK]
        peaks = []
        for a, b in zip(bounces, bounces[1:]+[None]):
            end = b['tick'] if b else self.REJOIN_TICK
            top = min(range(a['tick'], end), key=lambda t: players[t]['y'])
            peaks.append(dict(bounce_tick=a['tick'], bounce_speedY=a['player']['speedY'], peak_tick=top,
                              peak_y=players[top]['y'], height=rest_y-players[top]['y'], fraction=(rest_y-players[top]['y'])/fall_height))
        self.assertLessEqual(peaks[0]['fraction'], .5)
        self.assertTrue(all(a['height'] > b['height'] for a, b in zip(peaks[:4], peaks[1:4])), peaks[:4])
        window = players[600:self.REJOIN_TICK]
        self.assertTrue(all(abs(p['speedX']) < 1e-6 for p in window))
        self.assertLess(rest_y - min(p['y'] for p in window), 15)
        self.assertLess(max(abs(p['speedY']) for p in window), .2)
        rejoin_inputs = [i for i in result['inputs'] if i['tick'] >= self.REJOIN_TICK]
        self.assertEqual(len(rejoin_inputs), 4)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        after = self.kinds(mech, self.REJOIN_TICK)
        after = [k for k in after if k != ('bounce','S01-floor')]
        self.assertEqual(after, [('acquisition','S01-yard-pad'),('release','S01-yard-pad'),('acquisition','S01-lift'),
                                 ('release','S01-lift'),('bounce','S01-deflector')])
        yard = next(e for e in mech if e['type']=='acquisition' and e['element']=='S01-yard-pad')
        lift = next(e for e in mech if e['type']=='acquisition' and e['element']=='S01-lift')
        deflector = next(e for e in mech if e['type']=='bounce' and e['element']=='S01-deflector')
        fall = dict(scenario='naturally mistimed S01-01 release: hoist held 45 ticks instead of 60; physical fall; no relocation',
            release=dict(tick=55, element='S01-hoist', player=release['player'], release_height_y=release['player']['y']),
            apex=dict(tick=apex_tick, player=apex), fall_height=fall_height,
            fall_height_definition='floor-bounce rest y minus apex y after the release',
            drag_zone=dict(id='S01-yard-drag', box=self.YARD_DRAG, entry_tick=entry,
                before=dict(tick=entry-1, speedX=before['speedX'], speedY=before['speedY'], player=before),
                after=dict(tick=land, speedX=at_floor['speedX'], speedY=at_floor['speedY'], player=at_floor),
                per_tick_vx_ratio_airborne=ratios, vertical_damping_per_tick=0.985),
            floor_bouncer=dict(element='S01-floor', first_bounce_tick=land, rest_y=rest_y),
            bounce_peaks=peaks, first_peak_fraction=peaks[0]['fraction'], first_peak_at_most_half=True,
            settled=dict(window=[600, self.REJOIN_TICK-1], max_abs_speedX=max(abs(p['speedX']) for p in window),
                max_abs_speedY=max(abs(p['speedY']) for p in window), y_range=[min(p['y'] for p in window), max(p['y'] for p in window)],
                inside_drag_zone=True, on='S01-floor'),
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'], inputs=rejoin_inputs,
                yard_pad_acquisition=dict(tick=yard['tick'], anchor=yard['rope'][0], player=yard['player']),
                lift_acquisition=dict(tick=lift['tick'], anchor=lift['rope'][0], player=lift['player']),
                deflector_bounce=dict(tick=deflector['tick'], player=deflector['player']),
                final=players[-1], encounter_rejoined='S01-02 exit box (S01-03 start)', exit_box=self.S01_02_EXIT))
        result.update(fall)
        self.evidence.write('encounters/fall/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed hoist release tick 55 at y', round(release['player']['y'],1), '; apex', round(apex['y'],1),
              '; drag entry tick', entry, 'vx/vy', round(before['speedX'],3), round(before['speedY'],3), '->', round(at_floor['speedX'],5),
              round(at_floor['speedY'],3), '; floor bounce peaks', [round(p['fraction'],3) for p in peaks[:5]], 'of', round(fall_height,1),
              '; settled on S01-floor; input-only rejoin: yard pad tick', yard['tick'], ', lift tick', lift['tick'],
              ', deflector tick', deflector['tick'], ', S01-02 exit box at tick', self.FALL_TICKS)


class Task506Tests(FoundationsV3CompleteChecks, unittest.TestCase):
    """Foundations S01-03/04, exit and fall recovery, re-specced by TASK-548 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, shared with Task548Tests via FoundationsV3CompleteChecks):
    test_01_geometry_and_rules: v2 rules, rest pads, 459-486 gaps, fall lines onto mountain-catch -> v3 rules,
    zero gray solids, 918-972 gaps, fall points over drag zones onto the green S01-floor, exit pad in a drag zone.
    test_02_s01_03_nominal: crane + jib hooks onto the gantry pad -> green gantry hook caught on the deflector rebound.
    test_03_s01_04_nominal: boom hook onto the S01-exit rest pad -> green crown hook onto the green exit pad.
    test_04_full_traversal: base spawn to the S01-exit rest -> base spawn to a settle on the green exit pad.
    test_05_fall_through_drag_and_rejoin: mistimed hoist (14 ticks) onto the solid base -> mistimed hoist
    (45 ticks) through the yard drag zone onto the green floor bouncers, then a yard-pad + lift rejoin.
    test_06_source_hashes is unchanged. The v2 helpers and constants below stay for the later v2 suites.
    """
    task_id = 'TASK-506'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    report = Task505Tests.report
    test_06_source_hashes = Task465Tests.test_03_source_hashes
    S01_01 = Task505Tests.S01_01
    S01_02 = Task505Tests.S01_02
    CRANE, JIB, BOOM = (3350.05,-802.46), (3607.4,-994.39), (3920,-1740)
    S01_03 = [(400,'mousedown',*CRANE),(432,'mouseup',*CRANE),(455,'mousedown',*JIB),(487,'mouseup',*JIB)]
    S01_04 = [(760,'mousedown',*BOOM),(802,'mouseup',*BOOM)]
    # Mistimed S01-01: the hoist is released after 14 ticks instead of 40.
    FALL = [(10,'mousedown',2500,-318),(24,'mouseup',2500,-318),(300,'mousedown',2600,-318),(362,'mouseup',2600,-318)]
    MOVERS = ('S01-hoist','S01-lift')
    HOOKS = ('S01-crane-hook','S01-jib-hook','S01-boom-hook')
    DRAG = 'S01-yard-drag'
    BAND = (459, 486)
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])

    def box(self, name):
        b = {'S01-01':(2940,3090,-131,-130),'S01-02':(3500,3650,-361,-360),'S01-03':(3700,3860,-1271,-1270),
             'S01-04':(4060,4220,-1631,-1630)}[name]
        return dict(x=list(b[:2]), y=list(b[2:]), **self.REST)

    def at_rest(self, player, name):
        b = self.box(name)
        return all(b[k][0] <= player[k] <= b[k][1] for k in ('x','y','speedX','speedY'))

    def compact(self, trace):
        """Keep per-tick hashes and the fields the assertions use, not full world state."""
        pick = lambda s: dict(player=s['simulation']['player'], grapple={k:s['simulation']['grapple'][k]
            for k in ('throwed','grappled')}, rope=s['rope'], camera=s['camera'])
        events = []
        for e in trace['events']:
            row = {k:e[k] for k in ('sequence','tick','type') if k in e}
            for k in ('trusted','event','world','client','contact'):
                if k in e: row[k] = e[k]
            for k in ('before','after'):
                if k in e: row[k] = pick(e[k])
            events.append(row)
        return dict(name=trace['name'], outcome=trace['outcome'], metadata=trace['metadata'],
            full_trace_sha256=state_hash(trace), compaction='snapshots keep tick, full-state sha256, player, grapple flags, rope and camera',
            snapshots=[dict(tick=r['tick'], sha256=r['sha256'], **pick(r['state'])) for r in trace['snapshots']], events=events)

    def replay(self, name, plan, ticks, bounds, kind='base-start', snapshot=None):
        from grapple_over_verify import metadata, execute, check_trace
        m = dict(metadata=metadata(kind), inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in plan],
            ticks=ticks, expected_exit=bounds, required_events=['acquisition','release'])
        if snapshot: m['initial_snapshot'] = snapshot
        m['metadata']['compact_contacts'] = True
        prefix = 'encounters/'+name
        self.evidence.write(prefix+'/input.json', m)
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=True)
        check_trace(m, trace)
        replay = execute(m, self.browser, self.url, str(self.evidence.path(prefix+'/replay')))
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        for path, t in ((prefix+'/trace.json', trace), (prefix+'/replay/trace.json', replay)):
            self.evidence.write(path, self.compact(t))
        inputs = [e for e in trace['events'] if e['type']=='input']
        self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        for e in inputs:
            if e['event'] == 'mousedown':
                self.assertTrue(0 < e['client']['x'] < 1280 and 0 < e['client']['y'] < 720, e)
        mechanics = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] in ('acquisition','release'):
                element = e['after']['rope'][0]['id'] if e['after']['rope'] else e['before']['rope'][0]['id']
            if e['type'] in ('acquisition','release','bounce') or (e['type']=='contact' and element in self.MOVERS):
                mechanics.append(dict(tick=e['tick'], type=e['type'], element=element,
                    player=e['after']['simulation']['player'], rope=e['after']['rope']))
        players = [s['state']['simulation']['player'] for s in trace['snapshots']]
        result = dict(passed=True, matching_traces=True, trusted_inputs=True, kind=kind,
            full_trace_sha256=state_hash(trace), replay_sha256=state_hash(replay),
            mechanic_events=[dict(tick=x['tick'],type=x['type'],element=x['element'],player=x['player']) for x in mechanics],
            final=players[-1], expected_exit=bounds,
            inputs=[dict(tick=e['tick'],event=e['event'],world=e['world'],client=e['client'],trusted=e['trusted']) for e in inputs],
            trace=prefix+'/trace.json', replay=prefix+'/replay/trace.json')
        return trace, mechanics, players, result

    def reach(self, players, mechanics, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mechanics if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.BAND[0] <= distance <= self.BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y'],speedX=p['speedX'],speedY=p['speedY']), anchor=a['rope'][0],
            band=list(self.BAND), in_band=True)

    def record_reach(self, rows):
        if not self.evidence.path('rules.json').exists(): return
        rules = json.loads(self.evidence.path('rules.json').read_text())
        rules.setdefault('trace_measured_reach', {}).update({r['element']:r for r in rows})
        self.evidence.write('rules.json', rules)

    def base_contact(self, e):
        # Contacts carry no element id; mountain-catch is the only surface whose top is y=120.
        c = e.get('contact') or {}
        return e['type'] == 'contact' and c.get('y') == 120 and c.get('ny') == -1

    def acquisitions(self, mechanics):
        return [(e['element'], e['tick']) for e in mechanics if e['type']=='acquisition']


class FoundationsV3ToleranceChecks:
    """Layout-v3 Foundations (S01) tolerance on desktop 1280x720 and touch 844x390 (TASK-549).

    Every attempt is a base-start run (production restart at the base spawn, no placement or
    snapshot) with recorded trusted mouse/touch input: the encounter's inputs carry the variant,
    the other encounters keep their TASK-547/548 nominal inputs. The intended exit is the S01
    section exit (landed on the green exit pad inside S01-exit-drag at tick 1200), and
    check_s01_v3_mechanics requires the encounter's own mechanic, the four S01 anchors in route
    order and no S01-floor fall. Shared by Task549Tests and by the re-specced Task507Tests.
    """
    V3 = FoundationsV3CompleteChecks
    SEGMENTS = [V3.S01_01_V3, V3.S01_02_V3, V3.S01_03_V3, V3.S01_04_V3]
    V3_TICKS = 1200
    V3_EXIT = V3.LAND
    # (id, mechanic, start tick, manifest exit tick) in the nominal route; S01-04 ends at the
    # exit pad landing. Every anchor underside is horizontal, so aim variants move along x.
    V3_ENCOUNTERS = [('S01-01','blue hoist pull from the green entry pad, release onto the green yard bouncer',0,255),
                     ('S01-02','blue lift pull off the yard rebound, release into the green deflector rebound',255,370),
                     ('S01-03','green gantry hook caught in flight on the up-left rebound, swing reversed to the right',370,520),
                     ('S01-04','green crown hook caught in flight, release onto the green exit pad in S01-exit-drag',520,None)]
    V3_VARIANTS = [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]
    # Mistimed releases, one per encounter, that fall through a drag zone onto S01-floor:
    # (encounter, release tick replacing the nominal one, nominal release tick, ticks).
    MISTIMED = [('S01-01',55,70,700), ('S01-02',280,334,1100), ('S01-03',445,465,1300), ('S01-04',580,615,1250)]
    DENSITY_CAP = 254
    HUD = (0.3, 0.18)  # top-left HUD block (4 text rows) as fractions of the viewport
    V3_MOVERS = ('S01-hoist','S01-lift')

    def make_input(self, plan, ticks, bounds, device='desktop', snapshot=None):
        from grapple_over_verify import metadata
        m = dict(metadata=metadata('isolated' if snapshot else 'base-start'), ticks=ticks, expected_exit=bounds,
            required_events=['acquisition','release'],
            inputs=[dict(tick=t, event=e if device=='desktop' else {'mousedown':'touchstart','mouseup':'touchend'}[e],
                         world=dict(x=x, y=y)) for t,e,x,y in plan])
        m['metadata']['compact_contacts'] = True
        if device == 'touch': m['metadata']['viewport'] = dict(width=844, height=390)
        if snapshot: m['initial_snapshot'] = snapshot
        return m

    def run_attempt(self, m, prefix, filmstrip=False):
        """Record with real input, keep the full trace gzip-compressed inside input.json.gz
        (what the audit replays) and a compact per-tick trace.json for reading."""
        import gzip
        from grapple_over_verify import execute, check_trace
        trace = execute(m, self.browser, self.url, str(self.evidence.path(prefix)), filmstrip=filmstrip)
        m['trace'] = trace
        self.evidence.path(prefix+'/input.json.gz').write_bytes(
            gzip.compress(json.dumps(m, separators=(',',':')).encode(), 6, mtime=0))
        self.evidence.write(prefix+'/trace.json', self.compact(trace))
        success, reason = True, 'expected exit and mechanic events satisfied'
        try: check_trace(m, trace)
        except ValueError as error: success, reason = False, str(error)
        if filmstrip: self.filmstrip(prefix, m['metadata']['viewport'])
        return trace, success, reason

    def filmstrip(self, prefix, viewport):
        """Combine the per-input/per-second frames into one JPEG sheet and drop the PNGs."""
        from PIL import Image
        frames = sorted(self.evidence.path(prefix+'/x').parent.glob('frame-*.png'))
        w, h = viewport['width']//2, viewport['height']//2
        cols = 4; rows = (len(frames)+cols-1)//cols
        sheet = Image.new('RGB', (cols*w, rows*h))
        for i, f in enumerate(frames):
            with Image.open(f) as img: sheet.paste(img.convert('RGB').resize((w, h)), ((i%cols)*w, (i//cols)*h))
            f.unlink()
        sheet.save(self.evidence.path(prefix+'/filmstrip.jpg'), quality=80)
        self.evidence.write(prefix+'/filmstrip.json', dict(frames=[f.name for f in frames], cols=cols, tile=[w, h]))

    def targets(self, trace, viewport):
        """Every press lands inside the viewport and outside the HUD block (no blind target)."""
        rows = []
        for e in trace['events']:
            if e['type'] == 'input' and e['event'] in ('mousedown','touchstart'):
                c = e['client']
                inside = 0 < c['x'] < viewport['width'] and 0 < c['y'] < viewport['height']
                hud = c['x'] < self.HUD[0]*viewport['width'] and c['y'] < self.HUD[1]*viewport['height']
                rows.append(dict(tick=e['tick'], world=e['world'], client=c, in_viewport=inside, under_hud=hud))
        return rows

    def variant_plan(self, index, delta=0, shift=0):
        """Nominal S01 route with the variant on encounter `index` (release timing, aim along x)."""
        plan = []
        for k, segment in enumerate(self.SEGMENTS):
            for i, (t, e, x, y) in enumerate(segment):
                if k == index:
                    t += delta if i == 1 else 0
                    x += shift
                plan.append((t, e, x, y))
        return plan

    def density_v3(self, trace, name, start, end):
        """Longest stretch inside [start, end] without an acquisition, bounce or mover contact."""
        marks = []
        for e in trace['events']:
            element = (e.get('contact') or {}).get('elementId')
            if e['type'] == 'acquisition': element = e['after']['rope'][0]['id']
            if e['type'] in ('acquisition','bounce') or (e['type']=='contact' and element in self.V3_MOVERS):
                if start <= e['tick'] <= end and (not marks or marks[-1]['tick'] != e['tick']):
                    marks.append(dict(tick=e['tick'], type=e['type'], element=element))
        points = [start]+[m['tick'] for m in marks]+[end]
        gaps = [b-a for a, b in zip(points, points[1:])]
        i = gaps.index(max(gaps))
        return dict(trace=name, window=[start, end], interactions=marks, max_gap=max(gaps),
                    longest_gap=[points[i], points[i+1]], cap=self.DENSITY_CAP)

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s01_v3_mechanics
        source = hashes()
        suite = dict(section='S01', designVersion=3, source_hashes=source, level_sha256={k: source[k] for k in ('mountain.js','fixedlevel.js')},
            proof_kind='base-start for every attempt: production restart at the base spawn (2160,0), no placement, no snapshot; '
                       'variant inputs on the named encounter, TASK-547/548 nominal inputs elsewhere',
            browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            intended_exit=dict(box=self.V3_EXIT, tick=self.V3_TICKS, meaning='landed on S01-exit-pad inside S01-exit-drag (S01 section exit)'),
            mechanics_check='tools/grapple_over_verify.py check_s01_v3_mechanics',
            encounters={}, negative_control='negative-control.json', density='density.json', no_bounce_back='no-bounce-back.json',
            critical_inputs={r[0]: dict(timing_index=1, aim_indices=[0,1], tangent=(1,0), mechanic=r[1],
                                        inputs=self.SEGMENTS[k]) for k, r in enumerate(self.V3_ENCOUNTERS)})
        failures, nominal = [], {}
        for k, (name, mechanic, start, exit_tick) in enumerate(self.V3_ENCOUNTERS):
            attempts = []; suite['encounters'][name] = attempts
            for device in ('desktop','touch'):
                for variant, delta, shift in self.V3_VARIANTS:
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(self.variant_plan(k, delta, shift), self.V3_TICKS, self.V3_EXIT, device)
                    m['metadata']['blind_targets'] = 'skip'
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    dispatched = [(e['tick'], e['event']) for e in trace['events'] if e['type']=='input']
                    blind = [i for i in m['inputs'] if (i['tick'], i['event']) not in dispatched]
                    if blind: reason = 'blind target: off-screen press not dispatched '+json.dumps(blind[0])+' ('+reason+')'
                    self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                    mechanics = check_s01_v3_mechanics(name, trace, required=False)
                    if success:
                        try: check_s01_v3_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                    if variant == 'nominal':
                        self.assertTrue(success, (label, reason))
                        self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), (label, targets))
                        land = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S01-exit-pad')
                        nominal[label] = self.density_v3(trace, prefix+'/trace.json', start, exit_tick or land)
                        if exit_tick:
                            box = {'S01-01':self.V3.S01_01_EXIT,'S01-02':self.V3.S01_02_EXIT,'S01-03':self.V3.S01_03_EXIT}[name]
                            self.assertTrue(self.V3.inside(players[exit_tick], box), (label, players[exit_tick]))
                    final = players[-1]
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=1,
                        aim_input_indices=[0,1], timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        outcome='S01 exit reached through the encounter mechanic' if success else 'intended exit missed',
                        mechanic=mechanic, mechanic_events=mechanics, press_targets=targets, blind_inputs_not_dispatched=blind,
                        source_hashes_sha256=state_hash(source), level_sha256=source['mountain.js'],
                        trace_sha256=state_hash(trace), final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max(d['max_gap'] for d in nominal.values())
        self.evidence.write('density.json', dict(rule='no nominal-trace gap longer than the TASK-544 v3 density cap '
            '(LAYOUT_V3_DENSITY_CAP_TICKS = 254) without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','contact with S01-hoist/S01-lift'], cap=self.DENSITY_CAP,
            window='each encounter from its start tick in the nominal route (0/255/370/520) to its manifest exit tick '
                   '(255/370/520) or, for S01-04, the exit-pad landing; the settle on the exit pad is not a stretch of play',
            traces=nominal, max_gap=worst, passed=worst <= self.DENSITY_CAP))
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, self.DENSITY_CAP, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control()
        self.assertEqual(failures, [])
        print('PASS S01 v3 four encounters: both viewports nominal + >=2/4 variants;',
              {n: {d: sum(a['success'] for a in suite['encounters'][n] if a['device']==d and a['variant']!='nominal') for d in ('desktop','touch')}
               for n in suite['encounters']}, '; density max gap', worst, '<=', self.DENSITY_CAP, '; omitted-crown negative control fails the exit')

    def negative_control(self):
        from grapple_over_verify import hashes, check_s01_v3_mechanics
        # Named omission: the S01-04 crown-hook press/release left out; same base start, physics
        # and S01-01..03 inputs as every nominal attempt.
        plan = self.variant_plan(-1)[:6]
        m = self.make_input(plan, self.V3_TICKS, self.V3_EXIT)
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s01_v3_mechanics('S01-04', trace, required=False)
        floor = next(b['tick'] for b in mechanics['bounces'] if b['element']=='S01-floor')
        self.evidence.write('negative-control.json', dict(name='omitted crown hook: S01-04 S01-crown-hook press/release left out',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=self.V3_EXIT, unchanged_physics=True, source_hashes=hashes(),
            proof_kind='base-start, real mouse input, same S01-01..03 inputs as the nominal attempts', inputs=plan,
            mechanic_events=mechanics, max_tick_displacement=step, exit_pad_contact='S01-exit-pad' in [b['element'] for b in mechanics['bounces']],
            floor_bounce_tick=floor, final_player=players[-1],
            scope='Without the crown catch the gantry flight drops past the exit pad through S01-exit-drag and S01-yard-drag onto S01-floor.'))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertNotIn('S01-crown-hook', mechanics['acquisitions'])
        self.assertNotIn('S01-exit-pad', [b['element'] for b in mechanics['bounces']])
        self.assertLess(step, 60)

    def test_02_mistimed_release_no_bounce_back(self):
        from grapple_over_verify import check_s01_v3_mechanics
        V3 = self.V3
        zones = dict(yard=V3.YARD_DRAG, exit=V3.EXIT_DRAG)
        rows = {}
        for k, (name, release, nominal, ticks) in enumerate(self.MISTIMED):
            segment = self.SEGMENTS[k]
            self.assertEqual(segment[1][0], nominal)
            plan = [p for seg in self.SEGMENTS[:k] for p in seg]+[segment[0], (release,)+segment[1][1:]]
            for device in ('desktop','touch'):
                m = self.make_input(plan, ticks, dict(y=[-1e9, 1e9]), device)
                prefix = f'clips/fall-{name}-{device}'
                trace, success, reason = self.run_attempt(m, prefix, True)
                self.assertTrue(success, reason)
                self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
                players = [r['state']['simulation']['player'] for r in trace['snapshots']]
                mech = check_s01_v3_mechanics(name, trace, required=False)
                anchor = mech['encounter']['anchor']
                rel = next(r for r in mech['releases'] if r['element']==anchor)
                self.assertEqual(rel['tick'], release)
                r_player = players[release]
                after = [b for b in mech['bounces'] if b['tick'] > release]
                floor = [e['tick'] for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']=='S01-floor']
                self.assertTrue(floor, name)
                # The first surface reached after the mistimed release is the floor bouncer.
                self.assertEqual(after[0]['element'], 'S01-floor', (name, after[:3]))
                land = floor[0]
                crossed = {z: [t for t in range(release, land+1) if V3.in_box(players[t], b)] for z, b in zones.items()}
                self.assertTrue(crossed['yard'], name)
                contact = next(e for e in trace['events'] if e['type']=='bounce' and e['tick']==land)
                rest_y = contact['after']['simulation']['player']['y']
                apex_tick = min(range(release, land), key=lambda t: players[t]['y'])
                second = next((t for t in floor if t > land+1), ticks)
                peak_tick = min(range(land+1, second), key=lambda t: players[t]['y'])
                release_height = rest_y - r_player['y']
                peak_height = rest_y - players[peak_tick]['y']
                fall_height = rest_y - players[apex_tick]['y']
                self.assertLessEqual(peak_height, .5*release_height, name)
                self.assertLessEqual(peak_height, .5*fall_height, name)
                targets = self.targets(trace, m['metadata']['viewport'])
                self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), targets)
                step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
                self.assertLess(step, 60)
                row = dict(encounter=name, device=device, viewport=m['metadata']['viewport'], anchor=anchor,
                    mistiming=f'{anchor} released at tick {release} instead of {nominal}',
                    input=prefix+'/input.json.gz', trace=prefix+'/trace.json', filmstrip=prefix+'/filmstrip.jpg',
                    release=dict(tick=release, player=r_player), floor_rest_y=rest_y,
                    release_height=release_height, release_height_definition='S01-floor bounce y minus player y at the release tick',
                    apex=dict(tick=apex_tick, y=players[apex_tick]['y']), fall_height_from_apex=fall_height,
                    drag_zones_crossed=[dict(id={'yard':'S01-yard-drag','exit':'S01-exit-drag'}[z], box=zones[z],
                        ticks=[ts[0], ts[-1]], entry_player=players[ts[0]]) for z, ts in crossed.items() if ts],
                    first_bounce=dict(element='S01-floor', tick=land, before=contact['before']['simulation']['player'],
                        after=contact['after']['simulation']['player']),
                    first_bounce_peak=dict(tick=peak_tick, y=players[peak_tick]['y'], height=peak_height,
                        fraction_of_release_height=peak_height/release_height, fraction_of_apex_fall=peak_height/fall_height),
                    at_most_half_of_release_height=True, bounces_after_release=after[:6],
                    max_tick_displacement=step, press_targets=targets, relocation=False)
                rows.setdefault(name, {})[device] = row
                print('PASS fall', name, device, ': release tick', release, 'y', round(r_player['y'],1), '; drag zones',
                      [d['id'] for d in row['drag_zones_crossed']], '; floor bounce tick', land, '; first peak',
                      round(peak_height,1), '=', round(peak_height/release_height,3), 'of release height', round(release_height,1))
        self.evidence.write('no-bounce-back.json', dict(self.proof, rule='a mistimed release passes through the drag zone below '
            'it and its first bounce peaks at most 50% of the release height (i.e. at least 50% lower)',
            proof_kind='base-start, real mouse (desktop 1280x720) and touch (844x390) input; physical fall, no relocation',
            encounters=rows, passed=True))


class Task507Tests(FoundationsV3ToleranceChecks, unittest.TestCase):
    """Foundations (S01) tolerance, re-specced by TASK-549 from layout v2 to layout v3.

    Mapping (v2 case -> v3 case, shared with Task549Tests via FoundationsV3ToleranceChecks):
    test_01_tolerance_matrix: v2 S01-01..04 from restored rest states, 180-tick density, omitted-jib
    negative control -> v3 S01-01..04 base-start variants judged at the S01 exit-pad landing, 254-tick
    density cap, omitted-crown negative control. test_02_full_route: the v3 full route is the nominal
    S01-04 attempt of test_01 (and Task548 test_04). test_03_drag_zone_fall_clips -> test_02_mistimed_release_no_bounce_back
    (one mistimed release per encounter through a drag zone onto S01-floor, desktop and touch).
    test_04_source_hashes is unchanged. The v2 constants and helpers stay for the later v2 suites
    (Task508/510/513 reuse make_input, run_attempt, filmstrip, targets, ROUTE and S01_04).
    """
    task_id = 'TASK-507'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    compact = Task506Tests.compact
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    CRANE, JIB, BOOM = Task506Tests.CRANE, Task506Tests.JIB, Task506Tests.BOOM
    # TASK-507 tuning: the gantry pad and boom hook sit 20 lower, so a low jib arc clears the
    # pad's left corner, and the jib is pressed 6 ticks later than TASK-506 so its arc lands
    # on the gantry pad within 180 ticks of the catch (density limit).
    S01_03 = [(400,'mousedown',*CRANE),(432,'mouseup',*CRANE),(461,'mousedown',*JIB),(493,'mouseup',*JIB)]
    # A 48-tick boom hold (TASK-506: 42) swings past the green hook, bouncing off it, onto the exit pad.
    S01_04 = [(760,'mousedown',*BOOM),(808,'mouseup',*BOOM)]
    ROUTE = Task505Tests.S01_01+Task505Tests.S01_02+S01_03
    FALL = Task506Tests.FALL
    FALL_ZONE = dict(id='S01-yard-drag', left=2280, right=4680, top=40, bottom=120)
    LANDED = dict(speedY=[-.001,.001])
    REST = Task506Tests.REST
    BOXES = {'S01-01':dict(x=[2940,3090],y=[-131,-130],**REST), 'S01-02':dict(x=[3500,3650],y=[-361,-360],**REST),
             'S01-03':dict(x=[3700,3900],y=[-1271,-1270],**LANDED), 'S01-04':dict(x=[4060,4220],y=[-1631,-1630],**LANDED)}
    HUD = (0.3, 0.18)  # top-left HUD block (4 text rows) as fractions of the viewport
    VARIANTS = [('nominal',0,0),('early',-3,0),('late',3,0),('aim-left',0,-10.8),('aim-right',0,10.8)]

    @classmethod
    def encounters(cls):
        # (id, start tick in the base-start nominal run or None for base start, global plan, ticks,
        #  critical timing index, aim index, mechanic). Every aimed surface is a horizontal underside.
        return [('S01-01',None,Task505Tests.S01_01,240,1,0,'blue hoist swing onto the yard pad'),
                ('S01-02',180,Task505Tests.S01_02,260,1,0,'blue lift swing, green deflector rebound onto the loading pad'),
                ('S01-03',390,cls.S01_03,320,3,2,'crane hook then jib hook caught in flight onto the gantry pad'),
                ('S01-04',750,cls.S01_04,280,1,0,'boom hook swing past the hook onto the S01 exit pad')]

    def density(self, trace, bounds, name):
        """Gaps between acquisitions, bounces and mover contacts, from tick 0 to the first exit tick."""
        movers = ('S01-hoist','S01-lift')
        ticks = []
        for e in trace['events']:
            if e['type'] in ('acquisition','bounce') or (e['type']=='contact' and (e.get('contact') or {}).get('elementId') in movers):
                if not ticks or ticks[-1][0] != e['tick']:
                    element = e['after']['rope'][0]['id'] if e['type']=='acquisition' else e['contact'].get('elementId')
                    ticks.append((e['tick'], e['type'], element))
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        exit_tick = next(t for t, p in enumerate(players) if all(b[0] <= p[k] <= b[1] for k, b in bounds.items()))
        points = [0]+[t for t, _, _ in ticks if t <= exit_tick]+[exit_tick]
        gaps = [b-a for a, b in zip(points, points[1:])]
        return dict(trace=name, exit_tick=exit_tick, interactions=[dict(tick=t, type=k, element=el) for t, k, el in ticks if t <= exit_tick],
                    max_gap=max(gaps), longest_gap=[points[gaps.index(max(gaps))], points[gaps.index(max(gaps))+1]], limit=180)



class Task508Tests(unittest.TestCase):
    """Layout-v2 Switchback S02-01/02 from the real v2 S01 exit rest, with real input."""
    task_id = 'TASK-508'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    replay = Task506Tests.replay
    filmstrip = Task507Tests.filmstrip
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    # The TASK-507 S01 nominal route (base spawn to the S01 exit pad) produces the start pose.
    S01_ROUTE = Task507Tests.ROUTE+Task507Tests.S01_04
    SHUTTLE, LIFT = (3880,-1985), (3247,-2240)
    S02_01 = [(5,'mousedown',*SHUTTLE),(47,'mouseup',*SHUTTLE)]
    S02_02 = [(160,'mousedown',*LIFT),(234,'mouseup',*LIFT)]
    MOVERS = ('S02-shuttle','S02-lift')
    BRAKE = dict(id='S02-balcony-brake', left=3420, right=3620, top=-1945, bottom=-1880)
    BAND = (459, 486)
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])
    BOXES = {'S01-04':dict(x=[4209.1,4209.3],y=[-1631,-1630],**REST),
             'S02-01':dict(x=[3460,3620],y=[-1891,-1890],**REST),
             'S02-02':dict(x=[2987,3147],y=[-2111,-2110],**REST)}

    def at_rest(self, player, name):
        return all(b[0] <= player[k] <= b[1] for k, b in self.BOXES[name].items())

    def s01_exit(self):
        """Real S01 exit rest pose: a base-start real-input run of the v2 S01 route (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'start'): return type(self).start
        m = dict(metadata=metadata('base-start'), ticks=1120, expected_exit=self.BOXES['S01-04'],
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.S01_ROUTE],
            required_events=['acquisition','release'])
        m['metadata']['compact_contacts'] = True
        setup = execute(m, self.browser, self.url, str(self.evidence.path('encounters/S01-exit-start')))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual(acquired, ['S01-hoist','S01-lift','S01-crane-hook','S01-jib-hook','S01-boom-hook'])
        self.evidence.write('encounters/S01-exit-start/trace.json', self.compact(setup))
        rest = next(t for t in range(808, 1121) if self.at_rest(players[t], 'S01-04'))
        self.assertTrue(all(self.at_rest(p, 'S01-04') for p in players[rest:]))
        start = setup['snapshots'][-1]['state']['simulation']
        type(self).start = start
        type(self).start_proof = dict(kind='base-start S01 route (TASK-507 nominal inputs), real mouse input, no placement',
            inputs=m['inputs'], acquisitions=acquired, exit_rest_from_tick=rest, final_tick=1120, player=start['player'],
            snapshot_sha256=setup['snapshots'][-1]['sha256'], trace='encounters/S01-exit-start/trace.json')
        self.evidence.write('encounters/S01-exit-start/result.json', dict(passed=True, **type(self).start_proof))
        return start

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']
        s02 = m['sections'][1]
        # TASK-509 later builds S02-03/04; the opening stays as TASK-508 built it.
        self.assertEqual(s02['designVersion'], 2); self.assertIn(s02['status'], ('partial','built'))
        enc = m['encounters'][4:8]
        self.assertEqual([e['status'] for e in enc[:2]], ['built','built'])
        self.assertEqual([c['status'] for c in m['connectors'][4:6]], ['built','built'])
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S02-')]
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S02-')}
        self.assertLessEqual(set(self.MOVERS), set(movers))
        bounds = lambda e: (e['x']+min(p['x'] for p in e['points']), e['x']+max(p['x'] for p in e['points']),
                            e['y']+min(p['y'] for p in e['points']), e['y']+max(p['y'] for p in e['points']))
        exceptions = {x['element']:x for x in s02['solidExceptions']}
        roles = {}
        for e in own:
            roles[e['id']] = 'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce' else \
                'drag brake' if e['role'] == 'drag' else 'solid '+exceptions[e['id']]['kind']+' exception'
            if e['role'] == 'solid' and e['id'] not in movers:
                self.assertIn(e['id'], exceptions)
                if exceptions[e['id']]['kind'] == 'rest-pad':
                    self.assertLessEqual(bounds(e)[1]-bounds(e)[0], 200, e['id'])
        self.assertEqual(roles['S02-bulkhead'], 'green bounce')
        # Distinct roles: S02-01 is a blue shuttle swing with a deck brake, S02-02 a blue lift
        # pull into a green bulkhead rebound.
        e1, e2 = enc[0], enc[1]
        self.assertEqual(e1['start'], {'x':4209.2,'y':-1630.8,'from':'S01-04'})
        self.assertEqual(e2['start'], {'from':'S02-01','x':3597.5,'y':-1890.8})
        self.assertIn('S02-shuttle', e1['elements']); self.assertIn('S02-balcony-brake', e1['elements'])
        self.assertIn('S02-lift', e2['elements']); self.assertIn('S02-bulkhead', e2['elements'])
        self.assertEqual(m['encounters'][3]['exit'], {'left':4060,'right':4220,'top':-1640,'bottom':-1620})
        v2 = r['report']['sections'][1]
        self.assertEqual((v2['id'], v2['designVersion'], v2['passed'], v2['errors'], v2['range']), ('S02', 2, True, [], 540))
        for name in ('bounceDefault','moverCoverage','direction','gapBand','fallDrag'):
            self.assertTrue(v2['rules'][name]['passed'], name)
        direction = v2['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('left', 'left'))
        self.assertEqual(v2['rules']['moverCoverage']['measured']['encounters'][:2], ['S02-01','S02-02'])
        gaps = v2['rules']['gapBand']['measured']['gaps']
        self.assertEqual([g['id'] for g in gaps][:2], ['S02-01-shuttle','S02-02-lift'])
        for g in gaps:
            self.assertTrue(self.BAND[0] <= g['distance'] <= self.BAND[1], g)
        self.assertEqual(v2['rules']['gapBand']['measured']['target'], list(self.BAND))
        self.assertEqual(r['report']['v2'][:2], ['S01','S02'])
        self.assertFalse(r['report']['failed'])
        # Laid back over S01: every S02-01/02 element sits above S01's horizontal span.
        s01 = [bounds(e) for e in elements if e['id'].startswith('S01-') and e['role'] != 'drag']
        s01_span = (min(b[0] for b in s01), max(b[1] for b in s01))
        opening = set(enc[0]['elements']+enc[1]['elements'])
        route = [e for e in own if e['id'] in opening]
        for e in route:
            b = bounds(e)
            self.assertTrue(s01_span[0] <= b[0] and b[1] <= s01_span[1], e['id'])
        below = {}
        for e in route:
            b = bounds(e); mid = (b[0]+b[1])/2
            under = [x for x in elements if x['id'].startswith('S01-') and x['role'] != 'drag'
                     and bounds(x)[0] <= mid <= bounds(x)[1] and bounds(x)[2] > b[3]]
            under.sort(key=lambda x: bounds(x)[2])
            below[e['id']] = under[0]['id'] if under else 'S01-yard-drag/mountain-catch'
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report (TASK-504)',
            section=v2, all_applicable_rules_passed=True, encounters=['S02-01','S02-02'], planned=['S02-03','S02-04'],
            direction=direction, mover_encounters=v2['rules']['moverCoverage']['measured']['encounters'],
            gap_targets_reference='artifacts/TASK-503/calibration.json gap_metric (459-486 at 540)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps},
            fall_lines='none declared yet (TASK-509 adds S02 fall lines); rule passes over an empty list',
            other_v2_sections={s['id']:s['passed'] for s in r['report']['sections'] if not s['legacy']}))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s02, encounters=enc[:2], planned_encounters=enc[2:],
            connectors=m['connectors'][4:9], elements=own, movers=list(movers.values()), roles=roles,
            encounter_roles={'S02-01':'blue shuttle swing from the S01 exit pad; pass-through drag brake settles the landing on the balcony pad',
                             'S02-02':'blue lift pull up-left; release into the green bulkhead; rebound onto the landing pad'},
            s01_horizontal_span=s01_span, s01_element_below=below, runtime_matches_manifest=True, long_walking_floors=False,
            removed_v1_elements=['S02-left-balcony','S02-right-balcony','S02-brake-girder','S02-rest-ledge','S02-catch-balcony',
                'S02-reversal-balcony','S02-upper-return','S02-exit-anchor'],
            legacy_kept={'S02-exit':'cropped 360 -> 200 around its mid lip; S03 start (4429.2,-3190.8) unchanged'}))
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','drag brake':'rgba(255,196,0,.45)'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="1950 -2620 3200 1800" style="background:#111827">']
        for e in elements:
            if not e['id'].startswith('S01-') or e['role'] == 'drag': continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            parts.append(f'<polygon points="{pts}" fill="#374151" stroke="#6b7280" stroke-width="2"/>'
                         f'<text x="{e["x"]}" y="{e["y"]+48}" fill="#9ca3af" font-size="30">{e["id"]}</text>')
        for e in route:
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors.get(roles[e['id']], '#a3a3a3')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="2"/>'
                         f'<text x="{e["x"]}" y="{e["y"]-40 if e["id"] in movers else e["y"]+75}" fill="white" font-size="34">{e["id"]}</text>')
        for v in movers.values():
            e = next(x for x in own if x['id'] == v['element'])
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]-15}" x2="{e["x"]+60+dx}" y2="{e["y"]-15+dy}" stroke="#2f86ff" stroke-width="5" stroke-dasharray="10,6"/>')
        for g in s02['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="8,6"/>')
        for e in enc[:2]:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]-20}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]+20}" fill="none" stroke="#f472b6" stroke-width="4"/>')
        parts.append('<circle cx="4209.2" cy="-1630.8" r="12" fill="#ff7a1a"/>')
        for i, t in enumerate(['S02 Switchback layout v2 (direction left, back over S01): S01 exit rest (orange) -> S02-01 blue shuttle',
                '-> balcony pad (amber brake) -> S02-02 blue lift -> green bulkhead rebound -> landing pad',
                'yellow = gaps %s of 540, pink = exit boxes, dark grey = S01 v2 below (misses fall onto it); S02-03/04 planned' % '/'.join(str(round(g['distance'],1)) for g in gaps)]):
            parts.append(f'<text x="1980" y="{-2570+i*50}" fill="#67e8f9" font-size="40">{t}</text>')
        parts.append('</svg>')
        overview = self.browser.new_page(viewport=VIEWPORT); self.addCleanup(overview.close)
        overview.set_content('<style>body{margin:0}</style>'+''.join(parts))
        overview.screenshot(path=str(self.evidence.path('overview.png')))
        print('PASS geometry: S02 designVersion 2 partial (S02-01/02 built, 03/04 planned); roles', sorted(set(roles.values())),
              '; validator rules all pass; direction left; gaps', [round(g['distance'],1) for g in gaps], '; over S01; overview.png')

    def mechanics(self, trace, mech, players):
        """Acquisitions/releases/bounces plus mover anchor travel and brake-zone ticks."""
        rows = [dict(tick=x['tick'], type=x['type'], element=x['element'], mover=x['element'] in self.MOVERS,
                     player=x['player'], anchor=x['rope'][0] if x['rope'] else None) for x in mech]
        r = players[0]['radius']; z = self.BRAKE
        def in_brake(p):
            dx = max(z['left']-p['x'], 0, p['x']-z['right']); dy = max(z['top']-p['y'], 0, p['y']-z['bottom'])
            return dx*dx + dy*dy < r*r
        ticks = [t for t, p in enumerate(players) if in_brake(p)]
        if ticks:
            rows.append(dict(tick=ticks[0], type='drag-zone entry', element=z['id'], mover=False, player=players[ticks[0]]))
        travel = {}
        for name in self.MOVERS:
            anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']==name]
            if anchors:
                travel[name] = dict(dx=anchors[-1]['x']-anchors[0]['x'], dy=anchors[-1]['y']-anchors[0]['y'], ticks=len(anchors))
        return sorted(rows, key=lambda x: x['tick']), travel, ticks

    def reach(self, players, mech, press_tick, element):
        p = players[press_tick]
        a = next(e for e in mech if e['type']=='acquisition' and e['element']==element and e['tick'] >= press_tick)
        distance = ((a['rope'][0]['x']-p['x'])**2 + (a['rope'][0]['y']-p['y'])**2) ** .5
        self.assertTrue(self.BAND[0] <= distance <= self.BAND[1], (element, distance))
        return dict(element=element, distance=distance, press_tick=press_tick, acquisition_tick=a['tick'],
            player_at_press=dict(x=p['x'],y=p['y']), anchor=a['rope'][0], band=list(self.BAND), in_band=True)

    def run_encounter(self, name, plan, ticks, box):
        start = self.s01_exit()
        trace, mech, players, result = self.replay(name, plan, ticks, self.BOXES[box], kind='isolated', snapshot=start)
        self.filmstrip('encounters/'+name, VIEWPORT)
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        self.assertTrue(self.at_rest(players[0], 'S01-04'), players[0])
        events, travel, brake = self.mechanics(trace, mech, players)
        result.update(proof_kind='isolated: one labeled initial placement = restoreClimbState of the real S01 exit rest pose '
                      'from a base-start real-input S01 run; production input/physics thereafter; not a continuous-completion claim',
            not_continuous_completion_claim=True, initial_placement=dict(labeled=True, source=self.start_proof),
            mechanic_events=events, mover_anchor_travel_while_attached=travel)
        return trace, mech, players, result, events, travel, brake

    def test_02_s02_01_nominal(self):
        trace, mech, players, result, events, travel, brake = self.run_encounter('S02-01', self.S02_01, 200, 'S02-01')
        self.assertEqual([(e['type'],e['element']) for e in events if e['type'] in ('acquisition','release')],
            [('acquisition','S02-shuttle'),('release','S02-shuttle')])
        self.assertGreater(abs(travel['S02-shuttle']['dx']), 1)
        shuttle = self.reach(players, mech, 5, 'S02-shuttle')
        self.assertTrue(brake)
        entry = brake[0]
        self.assertGreater(abs(players[entry-1]['speedX']), .5)
        landed = next(t for t in range(47, 201) if self.at_rest(players[t], 'S02-01'))
        self.assertTrue(all(self.at_rest(p, 'S02-01') for p in players[landed:]))
        self.assertTrue(all(p['x'] < 4210 for p in players))
        result.update(encounter='S02-01', shuttle_reach=shuttle, brake=dict(id=self.BRAKE['id'], entry_tick=entry,
            speedX_before=players[entry-1]['speedX'], speedX_at_rest=players[landed]['speedX']), balcony_rest_from_tick=landed,
            balcony_rest=players[landed])
        self.evidence.write('encounters/S02-01/result.json', result)
        print('PASS S02-01: from the real S01 exit rest; blue shuttle acquisition', round(shuttle['distance'],1),
              '; brake entry tick', entry, '; balcony rest from tick', landed, '; identical replay; trusted input')

    def test_03_s02_02_nominal(self):
        trace, mech, players, result, events, travel, brake = self.run_encounter('S02-02', self.S02_01+self.S02_02, 420, 'S02-02')
        self.assertEqual([(e['type'],e['element']) for e in events if e['type'] in ('acquisition','release')],
            [('acquisition','S02-shuttle'),('release','S02-shuttle'),('acquisition','S02-lift'),('release','S02-lift')])
        self.assertTrue(self.at_rest(players[160], 'S02-01'), players[160])
        self.assertEqual((round(players[160]['x'],1), round(players[160]['y'],1)), (3597.5, -1890.8))
        bounce = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']=='S02-bulkhead')
        before, after = bounce['before']['simulation']['player'], bounce['after']['simulation']['player']
        self.assertLess(before['speedX'], 0); self.assertGreater(after['speedX'], 0)
        self.assertGreater(abs(travel['S02-lift']['dy']), 1)
        lift = self.reach(players, mech, 160, 'S02-lift')
        landed = next(t for t in range(234, 421) if self.at_rest(players[t], 'S02-02'))
        self.assertTrue(all(self.at_rest(p, 'S02-02') for p in players[landed:]))
        rules = json.loads(self.evidence.path('rules.json').read_text()) if self.evidence.path('rules.json').exists() else None
        shuttle = self.reach(players, mech, 5, 'S02-shuttle')
        if rules:
            rules['trace_measured_reach'] = {'S02-shuttle':shuttle, 'S02-lift':lift}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S02-02', s02_01_exit_at_tick_160=players[160], lift_reach=lift,
            bulkhead_bounce=dict(tick=bounce['tick'], before=before, after=after), landing_rest_from_tick=landed,
            landing_rest=players[landed])
        self.evidence.write('encounters/S02-02/result.json', result)
        print('PASS S02-02: from the S02-01 balcony rest; blue lift acquisition', round(lift['distance'],1),
              '; green bulkhead rebound tick', bounce['tick'], '; landing-pad rest from tick', landed, '; identical replay; trusted input')


class Task509Tests(unittest.TestCase):
    """Layout-v2 Switchback S02-03/04, section exit and drag-column fall recovery onto S01, with real input."""
    task_id = 'TASK-509'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    replay = Task506Tests.replay
    filmstrip = Task507Tests.filmstrip
    s01_exit = Task508Tests.s01_exit
    test_06_source_hashes = Task465Tests.test_03_source_hashes
    S01_ROUTE = Task508Tests.S01_ROUTE
    CREST, TROLLEY = (2960,-2550), (2260,-2905)
    S02_01, S02_02 = Task508Tests.S02_01, Task508Tests.S02_02
    S02_03 = [(425,'mousedown',*CREST),(466,'mouseup',*CREST)]
    S02_04 = [(765,'mousedown',*TROLLEY),(811,'mouseup',*TROLLEY)]
    NOMINAL = S02_01+S02_02+S02_03+S02_04
    # Mistimed S02-02: the lift is released after 60 ticks instead of 74. The rejoin is a
    # later hoist press from the S01 entry pad rest, pulled through to the loading pad.
    REJOIN = [(780,'mousedown',2480,-316),(850,'mouseup',2480,-316)]
    FALL = S02_01+[(160,'mousedown',3247,-2240),(220,'mouseup',3247,-2240)]+REJOIN
    MOVERS = ('S02-shuttle','S02-lift','S02-trolley','S01-hoist')
    DRAG = dict(id='S02-fall-drag', left=1990, right=2140, top=-1500, bottom=18)
    BRAKE = dict(id='S02-ledge-brake', left=2310, right=2510, top=-2560, bottom=-2480)
    BAND = (459, 486)
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])
    BOXES = {'S01-04':dict(x=[4209.1,4209.3],y=[-1631,-1630],**REST),
             'S02-01':dict(x=[3460,3620],y=[-1891,-1890],**REST),
             'S02-02':dict(x=[2987,3147],y=[-2111,-2110],**REST),
             'S02-03':dict(x=[2350,2510],y=[-2491,-2490],**REST),
             'S02-04':dict(x=[2040,2200],y=[-2691,-2690],**REST),
             'S01-entry':dict(x=[2060,2149],y=[7.1,7.3],**REST),
             'S01-02':dict(x=[3500,3650],y=[-361,-360],**REST)}

    def at_rest(self, player, name):
        return all(b[0] <= player[k] <= b[1] for k, b in self.BOXES[name].items())

    def bounds(self, e):
        return (e['x']+min(p['x'] for p in e['points']), e['x']+max(p['x'] for p in e['points']),
                e['y']+min(p['y'] for p in e['points']), e['y']+max(p['y'] for p in e['points']))

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']
        s02 = m['sections'][1]
        self.assertEqual((s02['designVersion'], s02['status']), (2, 'built'))
        enc = m['encounters'][4:8]
        self.assertEqual([e['status'] for e in enc], ['built']*4)
        self.assertEqual([c['status'] for c in m['connectors'][4:8]], ['built']*4)
        self.assertEqual(m['recoveries'][1]['status'], 'built')
        self.assertEqual((m['recoveries'][1]['from'], m['recoveries'][1]['to']), ('S02-04', 'S01-01'))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S02-')]
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S02-')}
        self.assertEqual(set(movers), {'S02-shuttle','S02-lift','S02-trolley'})
        exceptions = {x['element']:x for x in s02['solidExceptions']}
        roles = {}
        for e in own:
            roles[e['id']] = 'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce' else \
                'drag zone' if e['role'] == 'drag' else 'solid '+exceptions[e['id']]['kind']+' exception'
            if e['role'] == 'solid' and e['id'] not in movers:
                self.assertIn(e['id'], exceptions)
                if exceptions[e['id']]['kind'] == 'rest-pad':
                    self.assertLessEqual(self.bounds(e)[1]-self.bounds(e)[0], 200, e['id'])
        self.assertEqual(roles['S02-crest-hook'], 'green bounce')
        self.assertEqual(roles['S02-trolley'], 'blue mover')
        e3, e4 = enc[2], enc[3]
        self.assertEqual(e3['start'], {'from':'S02-02','x':3136.2,'y':-2110.8})
        self.assertEqual(e4['start']['from'], 'S02-03')
        self.assertIn('S02-crest-hook', e3['elements']); self.assertIn('S02-ledge-brake', e3['elements'])
        self.assertIn('S02-trolley', e4['elements']); self.assertIn('S02-exit-pad', e4['elements'])
        v2 = r['report']['sections'][1]
        self.assertEqual((v2['id'], v2['designVersion'], v2['passed'], v2['errors'], v2['range']), ('S02', 2, True, [], 540))
        for name in ('bounceDefault','moverCoverage','direction','gapBand','fallDrag'):
            self.assertTrue(v2['rules'][name]['passed'], name)
        direction = v2['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('left', 'left'))
        self.assertLess(direction['exitX'], direction['entryX'])
        mover_encounters = v2['rules']['moverCoverage']['measured']['encounters']
        self.assertEqual(mover_encounters, ['S02-01','S02-02','S02-04'])
        gaps = v2['rules']['gapBand']['measured']['gaps']
        self.assertEqual([g['id'] for g in gaps], ['S02-01-shuttle','S02-02-lift','S02-03-crest','S02-04-trolley'])
        for g in gaps:
            self.assertTrue(self.BAND[0] <= g['distance'] <= self.BAND[1], g)
        self.assertEqual(v2['rules']['gapBand']['measured']['target'], list(self.BAND))
        # Every declared fall line: S01 landing below, with a drag zone spanning it above the landing top.
        falls = v2['rules']['fallDrag']['measured']['fallLines']
        self.assertEqual([f['id'] for f in falls], ['S02-02-short','S02-03-overshoot','S02-04-short'])
        byid = {e['id']:e for e in elements}
        for f in falls:
            self.assertEqual((f['landing'], f['landingSection'], f['onBelow'], f['underLanding'], f['dragZone']),
                ('S01-entry-pad', 'S01', True, True, self.DRAG['id']), f)
            z = self.bounds(byid[f['dragZone']]); land = self.bounds(byid[f['landing']])
            self.assertTrue(z[0] <= f['x'] <= z[1] and land[0] <= f['x'] <= land[1])
            self.assertLessEqual(z[3], land[2])
        self.assertEqual(self.bounds(byid[self.DRAG['id']]), (1990, 2140, -1500, 18))
        # The column stays clear of the base spawn rest circle (2160, 7.2, r 10.8).
        self.assertGreater(2160-10.8, self.DRAG['right'])
        self.assertEqual(r['report']['v2'][:2], ['S01','S02'])
        self.assertFalse(r['report']['failed'])
        self.assertTrue(all(s['passed'] for s in r['report']['sections'] if not s['legacy']))
        # Laid back over S01: below each S02 route element, the first S01 surface it would hit.
        s01 = [e for e in elements if e['id'].startswith('S01-') and e['role'] != 'drag']
        route = [e for e in own if e['id'] != 'S02-exit' and e['role'] != 'drag']
        below = {}
        for e in route:
            b = self.bounds(e); mid = (b[0]+b[1])/2
            under = sorted([x for x in s01 if self.bounds(x)[0] <= mid <= self.bounds(x)[1] and self.bounds(x)[2] > b[3]],
                           key=lambda x: self.bounds(x)[2])
            below[e['id']] = under[0]['id'] if under else 'base (mountain-catch)'
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report (TASK-504)',
            section=v2, all_applicable_rules_passed=True, encounters=['S02-01','S02-02','S02-03','S02-04'],
            direction=direction, mover_encounters=mover_encounters,
            gap_targets_reference='artifacts/TASK-503/calibration.json gap_metric (459-486 at 540)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps}, fall_lines=falls,
            drag_zones_under_every_fall_line=True,
            other_v2_sections={s['id']:s['passed'] for s in r['report']['sections'] if not s['legacy']}))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s02, encounters=enc,
            connectors=m['connectors'][4:9], recovery=m['recoveries'][1], elements=own, movers=list(movers.values()),
            roles=roles, encounter_roles={
                'S02-01':'blue shuttle swing from the S01 exit pad; drag brake onto the balcony pad',
                'S02-02':'blue lift pull; green bulkhead rebound onto the landing pad',
                'S02-03':'green crest hook pull over the bulkhead crest; ledge brake settles the drop onto the ledge',
                'S02-04':'blue trolley pull up-left; release onto the exit pad against its tall left lip (section exit)'},
            section_exit=dict(element='S02-exit-pad', box=e4['exit'], rest=dict(x=2050.8, y=-2690.8)),
            s01_element_below=below, runtime_matches_manifest=True, long_walking_floors=False,
            legacy_kept={'S02-exit':'v1 S03 entrance deck (4429.2,-3190.8) kept until S03 is rebuilt; connector S03-entrance stays planned'}))
        self.overview(elements, own, movers, roles, s02, enc, gaps)
        print('PASS geometry: S02 designVersion 2 built (4/4 encounters); roles', sorted(set(roles.values())),
              '; validator rules all pass; direction left', direction['entryX'], '->', direction['exitX'],
              '; gaps', [round(g['distance'],1) for g in gaps], '; fall lines', [f['id'] for f in falls], 'over', self.DRAG['id'])

    def overview(self, elements, own, movers, roles, s02, enc, gaps):
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','drag zone':'rgba(255,196,0,.40)'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1080" viewBox="1850 -3100 2500 3290" style="background:#111827">']
        for e in elements:
            if not (e['id'].startswith('S01-') or e['id'] == 'mountain-catch'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = 'rgba(160,160,160,.18)' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>')
            if e['role'] != 'drag' and e['id'] != 'mountain-catch':
                parts.append(f'<text x="{e["x"]}" y="{e["y"]+48}" fill="#9ca3af" font-size="26">{e["id"]}</text>')
        for e in own:
            if e['id'] == 'S02-exit': continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = colors.get(roles[e['id']], '#a3a3a3')
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="white" stroke-width="2"/>')
            label_y = e['y']-40 if e['id'] in movers else e['y']+75
            if e['id'] == 'S02-fall-drag': label_y = e['y']-15
            parts.append(f'<text x="{e["x"]}" y="{label_y}" fill="white" font-size="28">{e["id"]}</text>')
        for v in movers.values():
            e = next(x for x in own if x['id'] == v['element'])
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]-15}" x2="{e["x"]+60+dx}" y2="{e["y"]-15+dy}" stroke="#2f86ff" stroke-width="5" stroke-dasharray="10,6"/>')
        for g in s02['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="8,6"/>')
        for e in enc:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]-20}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]+20}" fill="none" stroke="#f472b6" stroke-width="4"/>')
        for f in s02['fallLines']:
            parts.append(f'<line x1="{f["x"]}" y1="-2400" x2="{f["x"]}" y2="7" stroke="#fb7185" stroke-width="3" stroke-dasharray="4,10"/>')
        parts.append('<circle cx="4209.2" cy="-1630.8" r="14" fill="#ff7a1a"/><circle cx="2050.8" cy="-2690.8" r="14" fill="#ff7a1a"/>')
        for i, t in enumerate(['S02 Switchback layout v2, direction left back over S01: S01 exit rest (orange, right) -> S02-01 shuttle',
                '-> balcony -> S02-02 lift/bulkhead -> landing -> S02-03 crest hook -> ledge -> S02-04 trolley -> exit pad (orange, left)',
                'yellow = gaps %s of 540; pink = exit boxes; red dashes = fall lines through the amber S02-fall-drag onto S01-entry-pad' % '/'.join(str(round(g['distance'],1)) for g in gaps)]):
            parts.append(f'<text x="1870" y="{-3050+i*46}" fill="#67e8f9" font-size="34">{t}</text>')
        parts.append('</svg>')
        page = self.browser.new_page(viewport=dict(width=1280, height=1080)); self.addCleanup(page.close)
        page.set_content('<style>body{margin:0}</style>'+''.join(parts))
        page.screenshot(path=str(self.evidence.path('overview.png')))

    def events(self, mech):
        return [(e['type'], e['element']) for e in mech if e['type'] in ('acquisition','release')]

    def reach(self, players, mech, press_tick, element):
        return Task508Tests.reach(self, players, mech, press_tick, element)

    def isolated(self, name, plan, ticks, box, start, source):
        trace, mech, players, result = self.replay(name, plan, ticks, self.BOXES[box], kind='isolated', snapshot=start)
        self.filmstrip('encounters/'+name, VIEWPORT)
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        result.update(proof_kind='isolated: one labeled initial placement = restoreClimbState of '+source+
                      '; production input/physics thereafter; not a continuous-completion claim',
            not_continuous_completion_claim=True, initial_placement=dict(labeled=True, source=source,
                s01_exit_start=self.start_proof))
        return trace, mech, players, result

    def brake_ticks(self, players, z):
        r = players[0]['radius']
        def inside(p):
            dx = max(z['left']-p['x'], 0, p['x']-z['right']); dy = max(z['top']-p['y'], 0, p['y']-z['bottom'])
            return dx*dx + dy*dy < r*r
        return [t for t, p in enumerate(players) if inside(p)]

    def test_02_s02_03_nominal(self):
        start = self.s01_exit()
        trace, mech, players, result = self.isolated('S02-03', self.S02_01+self.S02_02+self.S02_03, 760, 'S02-03',
            start, 'the real S01 exit rest (base-start S01 route); S02-01/02 nominal inputs then S02-03')
        self.assertEqual(self.events(mech), [('acquisition','S02-shuttle'),('release','S02-shuttle'),
            ('acquisition','S02-lift'),('release','S02-lift'),('acquisition','S02-crest-hook'),('release','S02-crest-hook')])
        self.assertTrue(self.at_rest(players[424], 'S02-02'), players[424])
        crest = self.reach(players, mech, 425, 'S02-crest-hook')
        # The arc clears the bulkhead crest (top -2450 over x 2887..2917) to its left.
        over = [p for p in players[466:] if 2887 <= p['x'] <= 2917]
        self.assertTrue(over and all(p['y'] < -2450-p['radius'] for p in over))
        brake = [t for t in self.brake_ticks(players, self.BRAKE) if t > 466]
        self.assertTrue(brake)
        landed = next(t for t in range(466, 761) if self.at_rest(players[t], 'S02-03'))
        self.assertTrue(all(self.at_rest(p, 'S02-03') for p in players[landed:]))
        type(self).s02_03_end = trace['snapshots'][-1]['state']['simulation']
        type(self).s02_03_end_sha256 = trace['snapshots'][-1]['sha256']
        result.update(encounter='S02-03', s02_02_exit_at_tick_424=players[424], crest_reach=crest,
            bulkhead_crest_cleared=dict(ticks=len(over), max_y=max(p['y'] for p in over)),
            ledge_brake=dict(id=self.BRAKE['id'], entry_tick=brake[0], speedX_before=players[brake[0]-1]['speedX']),
            ledge_rest_from_tick=landed, ledge_rest=players[landed])
        self.evidence.write('encounters/S02-03/result.json', result)
        print('PASS S02-03: from the real S02-02 landing rest; green crest hook', round(crest['distance'],1),
              '; over the bulkhead crest; ledge brake entry', brake[0], '; ledge rest from tick', landed, '; identical replay; trusted input')

    def test_03_s02_04_nominal(self):
        if not hasattr(type(self), 's02_03_end'): self.test_02_s02_03_nominal()
        start = type(self).s02_03_end
        self.assertTrue(self.at_rest(start['player'], 'S02-03'), start['player'])
        plan = [(t-760, e, x, y) for t, e, x, y in self.S02_04]
        trace, mech, players, result = self.isolated('S02-04', plan, 300, 'S02-04', start,
            'the S02-03 nominal run final state (tick 760, encounters/S02-03/trace.json)')
        self.assertEqual(self.events(mech), [('acquisition','S02-trolley'),('release','S02-trolley')])
        trolley = self.reach(players, mech, 5, 'S02-trolley')
        anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']=='S02-trolley']
        self.assertGreater(abs(anchors[-1]['x']-anchors[0]['x']), 1)
        landed = next(t for t in range(51, 301) if self.at_rest(players[t], 'S02-04'))
        self.assertTrue(all(self.at_rest(p, 'S02-04') for p in players[landed:]))
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (2050.8, -2690.8))
        result.update(encounter='S02-04', start_state_sha256=type(self).s02_03_end_sha256, trolley_reach=trolley,
            trolley_anchor_travel_while_attached=dict(dx=anchors[-1]['x']-anchors[0]['x'], ticks=len(anchors)),
            exit_rest_from_tick=landed, section_exit=dict(element='S02-exit-pad', rest=players[landed]))
        self.evidence.write('encounters/S02-04/result.json', result)
        print('PASS S02-04: from the S02-03 ledge rest; blue trolley', round(trolley['distance'],1),
              '; exit-pad rest from tick', landed, 'at', (round(players[-1]['x'],1), round(players[-1]['y'],1)), '; identical replay; trusted input')

    def test_04_full_traversal(self):
        start = self.s01_exit()
        trace, mech, players, result = self.isolated('S02-full', self.NOMINAL, 1000, 'S02-04', start,
            'the real S01 exit rest (base-start S01 route)')
        self.assertEqual([a for a in self.events(mech) if a[0]=='acquisition'],
            [('acquisition',x) for x in ('S02-shuttle','S02-lift','S02-crest-hook','S02-trolley')])
        checkpoints = {}
        for name, tick in (('S02-01',160),('S02-02',424),('S02-03',764)):
            self.assertTrue(self.at_rest(players[tick], name), (name, players[tick]))
            checkpoints[name] = dict(tick=tick, player=players[tick])
        landed = next(t for t in range(811, 1001) if self.at_rest(players[t], 'S02-04'))
        self.assertTrue(all(self.at_rest(p, 'S02-04') for p in players[landed:]))
        checkpoints['S02-04'] = dict(tick=landed, player=players[landed])
        reaches = [self.reach(players, mech, t, el) for t, el in ((5,'S02-shuttle'),(160,'S02-lift'),
            (425,'S02-crest-hook'),(765,'S02-trolley'))]
        # Travel stays left of the S01 exit pad and never drops below the S02 band.
        self.assertTrue(all(p['x'] <= 4209.3 and p['y'] < -1620 for p in players))
        result.update(encounter='S02 full traversal', encounter_exits=checkpoints, section_exit_reached=True,
            section_exit=dict(element='S02-exit-pad', box=self.BOXES['S02-04'], rest=players[-1]), reaches=reaches)
        self.evidence.write('encounters/S02-full/result.json', result)
        rules = json.loads(self.evidence.path('rules.json').read_text()) if self.evidence.path('rules.json').exists() else None
        if rules:
            rules['trace_measured_reach'] = {r['element']:r for r in reaches}
            self.evidence.write('rules.json', rules)
        print('PASS full S02: from the real S01 exit rest; exits at', {k:v['tick'] for k,v in checkpoints.items()},
              '; reaches', [round(r['distance'],1) for r in reaches], '; S02 exit pad reached; identical replay; trusted input')

    def test_05_fall_through_drag_and_rejoin(self):
        start = self.s01_exit()
        press = self.REJOIN[0][0]
        trace, mech, players, result = self.isolated('fall', self.FALL, press+400, 'S01-02', start,
            'the real S01 exit rest (base-start S01 route)')
        self.assertEqual(self.events(mech)[:4], [('acquisition','S02-shuttle'),('release','S02-shuttle'),
            ('acquisition','S02-lift'),('release','S02-lift')])
        released = next(e for e in mech if e['type']=='release' and e['element']=='S02-lift')
        self.assertEqual(released['tick'], 220)
        z = self.DRAG
        zone = [t for t in self.brake_ticks(players, z) if t < press]
        self.assertTrue(zone)
        entry = zone[0]
        before = players[entry-1]
        self.assertGreater(abs(before['speedX']), .1)
        self.assertEqual(zone, list(range(entry, press)))
        # Airborne in the column only horizontal speed is damped: exactly 0.8 per tick.
        land = next(t for t in range(entry, press) if abs(players[t]['y']-7.2) < 1e-3)
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in range(entry, land-1) if players[t]['speedX']]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios[:5])
        self.assertTrue(all(players[t+1]['speedY'] > players[t]['speedY'] for t in range(entry, land-1)))
        pad = [e for e in trace['events'] if e['type']=='contact' and e['contact'].get('y') == 18 and e['contact'].get('ny') == -1
               and e['tick'] < press]
        self.assertTrue(pad)
        base = [e for e in trace['events'] if e['type']=='contact' and e['contact'].get('y') == 120 and e['tick'] < press]
        self.assertEqual(base, [])
        rest = next(t for t in range(land, press) if self.at_rest(players[t], 'S01-entry'))
        self.assertTrue(all(self.at_rest(players[t], 'S01-entry') for t in range(rest, press)))
        after = players[rest]
        rejoin = [(e['element'], e['tick']) for e in mech if e['type']=='acquisition' and e['tick'] >= press]
        self.assertEqual([a for a,_ in rejoin], ['S01-hoist'])
        rejoined = next(t for t in range(press, len(players)) if self.at_rest(players[t], 'S01-02'))
        self.assertTrue(all(self.at_rest(p, 'S01-02') for p in players[rejoined:]))
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (3510.8, -360.8))
        series = [dict(tick=t, x=players[t]['x'], y=players[t]['y'], speedX=players[t]['speedX'], speedY=players[t]['speedY'])
                  for t in range(entry-1, land+2)]
        result.update(scenario='naturally mistimed S02-02 release (lift held 60 ticks instead of 74) from the real S02-01 balcony rest; '
                      'physical fall; no relocation after the labeled S01-exit start placement',
            release=dict(tick=released['tick'], element='S02-lift', player=released['player'], nominal_release_tick=234),
            fall_line=dict(id='S02-02-short', declared_x=2120, landing='S01-entry-pad'),
            drag_zone=dict(z, entry_tick=entry, vx_before=before['speedX'], vx_at_landing=players[land]['speedX'],
                vx_after=after['speedX'], vx_before_rejoin_press=players[press-1]['speedX'], player_before=before, per_tick_vx_ratio_airborne=ratios[:40], ratio_count=len(ratios)),
            landing=dict(element='S01-entry-pad', surface_y=18, first_contact_tick=pad[0]['tick'], land_tick=land, base_contact=False),
            rest_on_s01=dict(element='S01-entry-pad', tick=rest, player=after, held_until_tick=press-1),
            fall_series=series,
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'],
                inputs=[i for i in result['inputs'] if i['tick'] >= press], acquisition=dict(element=rejoin[0][0], tick=rejoin[0][1]),
                loading_pad_rest_tick=rejoined, loading_pad_rest=players[rejoined],
                encounter_rejoined='S01-02 exit = S01-03 start (loading pad lip rest 3510.8,-360.8) on the S01 route'))
        self.evidence.write('encounters/fall/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed S02-02 release tick 220; drag column entry tick', entry, 'vx', round(before['speedX'],3), '->',
              after['speedX'], '; rest on S01 entry pad tick', rest, 'x', round(after['x'],1), '; input-only hoist rejoin to the S01 loading pad tick', rejoined)


class Task510Tests(unittest.TestCase):
    """Layout-v2 Switchback (S02) tolerance on desktop and touch: recorded real input, replayable suite."""
    task_id = 'TASK-510'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    compact = Task506Tests.compact
    make_input = Task507Tests.make_input
    run_attempt = Task507Tests.run_attempt
    filmstrip = Task507Tests.filmstrip
    targets = Task507Tests.targets
    HUD = Task507Tests.HUD
    VARIANTS = Task507Tests.VARIANTS
    s01_exit = Task508Tests.s01_exit
    at_rest = Task509Tests.at_rest
    brake_ticks = Task509Tests.brake_ticks
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    S01_ROUTE = Task508Tests.S01_ROUTE
    BOXES, REST, DRAG = Task509Tests.BOXES, Task509Tests.REST, Task509Tests.DRAG
    # TASK-510 nominal S02-03: the TASK-509 crest-hook pull (hold 41), then the grappleable
    # ledge is caught in flight just past the apex (press 550, held 20 ticks) and pulls the
    # arc down onto the deck. That splits the ~210-tick crest flight (density) and rescues
    # long releases (+3 late lands on the ledge). It rests at x~2483, the S02-04 start.
    LEDGE = (2483,-2482)
    S02_03 = Task509Tests.S02_03+[(550,'mousedown',*LEDGE),(570,'mouseup',*LEDGE)]
    S02_04 = Task509Tests.S02_04
    NOMINAL = Task509Tests.S02_01+Task509Tests.S02_02+S02_03+S02_04
    MOVERS = ('S02-shuttle','S02-lift','S02-trolley','S01-hoist')
    # Encounter starts are ticks of one S02 nominal run from the real S01 exit rest, each a few
    # ticks before the encounter's first press while the player rests on the previous pad
    # (the balcony landing settles at tick 159, one tick before the S02-02 press).
    STARTS = {'S02-01':0, 'S02-02':159, 'S02-03':420, 'S02-04':760}
    # Mistimed S02-02 (lift held 60 ticks, not 74) then the TASK-509 hoist rejoin from the S01 entry pad.
    FALL = [(160,'mousedown',*Task508Tests.LIFT),(220,'mouseup',*Task508Tests.LIFT)]+Task509Tests.REJOIN

    @classmethod
    def encounters(cls):
        # (id, global plan, ticks, critical timing index, aim index, mechanic). Every aimed
        # surface is a horizontal underside, so the aim variants move along x.
        return [('S02-01',Task509Tests.S02_01,260,1,0,'blue shuttle swing from the S01 exit pad; balcony brake onto the balcony pad'),
                ('S02-02',Task509Tests.S02_02,300,1,0,'blue lift pull, green bulkhead rebound onto the landing pad'),
                ('S02-03',cls.S02_03,340,1,0,'green crest hook pull over the bulkhead crest; ledge caught in flight, ledge brake onto the deck'),
                ('S02-04',cls.S02_04,300,1,0,'blue trolley pull up-left onto the exit pad (section exit)')]

    def density(self, trace, bounds, name):
        ticks = []
        for e in trace['events']:
            if e['type'] in ('acquisition','bounce') or (e['type']=='contact' and (e.get('contact') or {}).get('elementId') in self.MOVERS):
                if not ticks or ticks[-1][0] != e['tick']:
                    element = e['after']['rope'][0]['id'] if e['type']=='acquisition' else e['contact'].get('elementId')
                    ticks.append((e['tick'], e['type'], element))
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        exit_tick = next(t for t, p in enumerate(players) if all(b[0] <= p[k] <= b[1] for k, b in bounds.items()))
        points = [0]+[t for t, _, _ in ticks if t <= exit_tick]+[exit_tick]
        gaps = [b-a for a, b in zip(points, points[1:])]
        i = gaps.index(max(gaps))
        return dict(trace=name, exit_tick=exit_tick, interactions=[dict(tick=t, type=k, element=el) for t, k, el in ticks if t <= exit_tick],
                    max_gap=max(gaps), longest_gap=[points[i], points[i+1]], limit=180)

    def landed(self, name):
        """Density window end: first tick landed (|speedY| < .001) inside the exit box, as
        TASK-507 (horizontal settling on the deck afterwards is not a gap in play)."""
        return {k: v for k, v in self.BOXES[name].items() if k != 'speedX'}

    def starts(self):
        """One S02 nominal run from the real S01 exit rest; its states start S02-02..04."""
        if hasattr(type(self), 'start_states'): return type(self).start_states
        from grapple_over_verify import execute, check_trace
        start = self.s01_exit()
        setup = self.make_input(self.NOMINAL, 1000, self.BOXES['S02-04'], snapshot=start)
        trace = execute(setup, self.browser, self.url, str(self.evidence.path('starts')))
        check_trace(setup, trace)
        self.evidence.write('starts/trace.json', self.compact(trace))
        states = {name: trace['snapshots'][t]['state']['simulation'] for name, t in self.STARTS.items() if t}
        states['S02-01'] = start
        for name, t in self.STARTS.items():
            if t: self.assertTrue(self.at_rest(states[name]['player'], {'S02-02':'S02-01','S02-03':'S02-02','S02-04':'S02-03'}[name]), name)
        self.evidence.write('starts/snapshots.json', dict(
            s01_exit=dict(source='encounters/S01-exit-start/trace.json (base-start TASK-507 S01 route, real mouse input)', **type(self).start_proof),
            s02_run='starts/trace.json (S02 nominal inputs from the S01 exit rest, real mouse input)',
            ticks={name: dict(tick=t, sha256=trace['snapshots'][t]['sha256'], player=states[name]['player'])
                   for name, t in self.STARTS.items() if t}))
        type(self).start_states = states
        return states

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s02_mechanics
        states = self.starts()
        suite = dict(section='S02', designVersion=2, source_hashes=hashes(), level_sha256=dict(
            **{'mountain.js': hashes()['mountain.js'], 'fixedlevel.js': hashes()['fixedlevel.js']}),
            proof_kind='S02-01 from the real S01 exit rest (base-start S01 route); S02-02..04 restored from starts/trace.json states (initial_snapshot)',
            browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            encounters={}, negative_control='negative-control.json', density='density.json',
            starts=dict(self.STARTS), start_snapshots='starts/snapshots.json',
            critical_inputs={r[0]: dict(timing_index=r[3], aim_index=r[4], tangent=(1,0), mechanic=r[5]) for r in self.encounters()})
        failures, nominal = [], {}
        for name, plan, ticks, critical, aim, mechanic in self.encounters():
            attempts = []; suite['encounters'][name] = attempts
            offset = self.STARTS[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.VARIANTS:
                    local = [(t-offset+(delta if i==critical else 0), e, x+(shift if i in (aim, aim+1) else 0), y)
                             for i, (t, e, x, y) in enumerate(plan)]
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(local, ticks, self.BOXES[name], device, states[name])
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    mechanics = check_s02_mechanics(name, trace, required=False)
                    if success:
                        try: check_s02_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    if variant == 'nominal':
                        self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), (label, targets))
                        if success: nominal[label] = self.density(trace, self.landed(name), prefix+'/trace.json')
                    final = trace['snapshots'][-1]['state']['simulation']['player']
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=critical,
                        aim_input_index=aim, timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        outcome='exit reached' if success else 'intended exit missed', mechanic=mechanic, mechanic_events=mechanics,
                        press_targets=targets, source_hashes_sha256=state_hash(hashes()), level_sha256=hashes()['mountain.js'],
                        final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max([d['max_gap'] for d in nominal.values()] or [0])
        self.evidence.write('density.json', dict(rule='no nominal-trace gap > 180 ticks without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','contact with '+'/'.join(self.MOVERS)],
            window='each nominal encounter trace from tick 0 to the first tick landed (|speedY|<.001) inside its expected exit box',
            traces=nominal, max_gap=worst, passed=worst <= 180,
            full_route='test_02 adds the S02 traversal from the real S01 exit rest segmented per encounter'))
        self.assertEqual(failures, [])
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, 180, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(states)
        print('PASS S02 v2 four encounters: both viewports nominal + >=2/4 variants; density max gap', worst,
              '; mistimed-lift negative control fails the exit')

    def negative_control(self, states):
        from grapple_over_verify import hashes, check_s02_mechanics
        # Named mistiming: S02-02 lift released after 60 ticks instead of 74, same start and physics.
        name, offset = 'S02-02', self.STARTS['S02-02']
        m = self.make_input([(t-offset, e, x, y) for t, e, x, y in self.FALL[:2]], 400, self.BOXES[name], snapshot=states[name])
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s02_mechanics(name, trace, required=False)
        rest = next(t for t, p in enumerate(players) if self.at_rest(p, 'S01-entry'))
        self.assertTrue(all(self.at_rest(p, 'S01-entry') for p in players[rest:]))
        self.evidence.write('negative-control.json', dict(name='mistimed S02-02: S02-lift released at hold 60 instead of 74',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=self.BOXES[name], unchanged_physics=True, source_hashes=hashes(),
            start='starts/trace.json tick 159 (same as the S02-02 attempts)', mechanic_events=mechanics,
            max_tick_displacement=step, final_player=players[-1], s01_entry_pad_rest=dict(tick=rest, player=players[rest]),
            scope='Same start, physics and lift aim; the early release misses the bulkhead rebound and falls physically '
                  'through S02-fall-drag onto the S01 entry pad, never reaching the S02 landing pad.'))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertEqual(mechanics['acquisitions'], ['S02-lift'])
        self.assertLess(step, 60)

    def test_02_full_traversal(self):
        from grapple_over_verify import check_s02_mechanics
        start = self.s01_exit()
        m = self.make_input(self.NOMINAL, 1000, self.BOXES['S02-04'], snapshot=start)
        trace, success, reason = self.run_attempt(m, 'clips/S02-full-desktop', True)
        self.assertTrue(success, reason)
        mechanics = check_s02_mechanics('S02-01', trace)
        self.assertEqual(mechanics['acquisitions'], ['S02-shuttle','S02-lift','S02-crest-hook','S02-ledge','S02-trolley'])
        self.assertIn('S02-bulkhead', [b['element'] for b in mechanics['bounces']])
        self.assertIn('S02-ledge', mechanics['airborne_acquisitions'])
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        presses = {'S02-01':5,'S02-02':160,'S02-03':425,'S02-04':765}
        segments = {}
        for name, start_tick in presses.items():
            window = dict(trace, events=[dict(e, tick=e['tick']-start_tick) for e in trace['events'] if e['tick'] >= start_tick],
                          snapshots=[dict(r, tick=r['tick']-start_tick) for r in trace['snapshots'][start_tick:]])
            d = self.density(window, self.landed(name), 'clips/S02-full-desktop/trace.json')
            d.update(start_tick=start_tick, exit_tick_absolute=start_tick+d['exit_tick'])
            segments[name] = d
        idle = [dict(after=a, rest_from=segments[a]['exit_tick_absolute'], next_press=presses[b], player=players[presses[b]])
                for a, b in zip(list(presses)[:-1], list(presses)[1:])]
        for row in idle:
            self.assertTrue(abs(row['player']['speedX']) < .001 and abs(row['player']['speedY']) < .001, row)
        density = json.loads(self.evidence.path('density.json').read_text()) if self.evidence.path('density.json').exists() else {}
        density['full_route'] = dict(trace='clips/S02-full-desktop/trace.json', input='clips/S02-full-desktop/input.json.gz',
            proof_kind='isolated: one labeled placement at the real S01 exit rest; real mouse input', segments=segments,
            idle_rests=idle, max_gap=max(d['max_gap'] for d in segments.values()))
        self.evidence.write('density.json', density)
        self.assertLessEqual(density['full_route']['max_gap'], 180, {k: v['max_gap'] for k, v in segments.items()})
        print('PASS full S02: S01 exit rest to the S02 exit pad; acquisitions', mechanics['acquisitions'],
              '; per-encounter max gaps', {k: v['max_gap'] for k, v in segments.items()})

    def test_03_drag_zone_fall_clips(self):
        from grapple_over_verify import check_s02_mechanics
        states = self.starts()
        offset = self.STARTS['S02-02']
        plan = [(t-offset, e, x, y) for t, e, x, y in self.FALL]
        for device in ('desktop','touch'):
            m = self.make_input(plan, plan[-1][0]+250, self.BOXES['S01-02'], device, states['S02-02'])
            prefix = 'clips/fall-'+device
            trace, success, reason = self.run_attempt(m, prefix, True)
            self.assertTrue(success, reason)
            players = [r['state']['simulation']['player'] for r in trace['snapshots']]
            step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
            press = plan[2][0]
            zone = [t for t in self.brake_ticks(players, self.DRAG) if t < press]
            land = next(t for t in range(zone[0], press) if abs(players[t]['y']-7.2) < 1e-3)
            rest = next(t for t in range(land, press) if self.at_rest(players[t], 'S01-entry'))
            base = [e['tick'] for e in trace['events'] if e['type']=='contact' and (e.get('contact') or {}).get('y') == 120]
            mechanics = check_s02_mechanics('S02-02', trace, required=False)
            targets = self.targets(trace, m['metadata']['viewport'])
            self.assertTrue(zone and all(t['in_viewport'] and not t['under_hud'] for t in targets), targets)
            self.assertEqual(base, [])
            self.assertEqual(mechanics['acquisitions'], ['S02-lift','S01-hoist'])
            self.assertLess(step, 60)
            rejoined = next(t for t in range(press, len(players)) if self.at_rest(players[t], 'S01-02'))
            self.evidence.write(prefix+'/result.json', dict(passed=True, device=device, viewport=m['metadata']['viewport'],
                scenario='mistimed S02-02 lift release (hold 60, nominal 74) from the S02-02 start state; physical fall; input-only rejoin',
                drag_zone=self.DRAG, drag_zone_ticks=[zone[0], zone[-1]], vx_entering=players[zone[0]-1]['speedX'],
                entry_pad_land_tick=land, entry_pad_rest=dict(tick=rest, player=players[rest]), base_contact=False,
                rejoin=dict(press_tick=press, acquisition='S01-hoist', loading_pad_rest_tick=rejoined, player=players[rejoined]),
                max_tick_displacement=step, press_targets=targets, mechanic_events=mechanics, final=players[-1]))
            print('PASS fall '+device+': drag column ticks', zone[0], '-', zone[-1], '; entry pad rest tick', rest,
                  '; hoist rejoin to the loading pad tick', rejoined, '; no relocation')


class Task511Tests(unittest.TestCase):
    """Layout-v2 Broken Viaduct S03-01/02 from the real v2 S02 exit rest, with real input."""
    task_id = 'TASK-511'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    replay = Task506Tests.replay
    filmstrip = Task507Tests.filmstrip
    bounds = Task509Tests.bounds
    brake_ticks = Task509Tests.brake_ticks
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    # One base-start run: the S01 route, then the TASK-510 S02 nominal inputs from tick 1120.
    BASE_ROUTE = Task508Tests.S01_ROUTE+[(t+1120, e, x, y) for t, e, x, y in Task510Tests.NOMINAL]
    CARRIAGE, LIFT = (2244,-3125), (2903,-3370)
    S03_01 = [(5,'mousedown',*CARRIAGE),(45,'mouseup',*CARRIAGE)]
    S03_02 = [(200,'mousedown',*LIFT),(265,'mouseup',*LIFT)]
    MOVERS = ('S03-carriage','S03-lift')
    BUFFER = 'S03-span-buffer'
    BAND, RANGE = (459, 486), 540
    REST = dict(speedX=[-.001,.001], speedY=[-.001,.001])
    BOXES = {'S02-04':dict(x=[2050.7,2050.9],y=[-2691,-2690],**REST),
             'S03-01':dict(x=[2420,2580],y=[-3011,-3010],**REST),
             'S03-02':dict(x=[3370,3500],y=[-3261,-3260],**REST)}

    def at_rest(self, player, name):
        return all(b[0] <= player[k] <= b[1] for k, b in self.BOXES[name].items())

    def s02_exit(self):
        """Real S02 exit rest pose: one base-start real-input run of the v2 S01 and S02 routes (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'start'): return type(self).start
        m = dict(metadata=metadata('base-start'), ticks=2120, expected_exit=self.BOXES['S02-04'],
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.BASE_ROUTE],
            required_events=['acquisition','release'])
        m['metadata']['compact_contacts'] = True
        setup = execute(m, self.browser, self.url, str(self.evidence.path('encounters/S02-exit-start')))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual(acquired, ['S01-hoist','S01-lift','S01-crane-hook','S01-jib-hook','S01-boom-hook',
            'S02-shuttle','S02-lift','S02-crest-hook','S02-ledge','S02-trolley'])
        self.evidence.write('encounters/S02-exit-start/trace.json', self.compact(setup))
        rest = next(t for t in range(1931, 2121) if self.at_rest(players[t], 'S02-04'))
        self.assertTrue(all(self.at_rest(p, 'S02-04') for p in players[rest:]))
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (2050.8, -2690.8))
        start = setup['snapshots'][-1]['state']['simulation']
        type(self).start = start
        type(self).start_proof = dict(kind='base-start S01+S02 v2 routes (TASK-507 S01 then TASK-510 S02 nominal inputs '
            'from tick 1120), real mouse input, no placement', inputs=m['inputs'], acquisitions=acquired,
            s02_exit_rest_from_tick=rest, final_tick=2120, player=start['player'],
            snapshot_sha256=setup['snapshots'][-1]['sha256'], trace='encounters/S02-exit-start/trace.json')
        self.evidence.write('encounters/S02-exit-start/result.json', dict(passed=True, **type(self).start_proof))
        return start

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']
        s03 = m['sections'][2]
        # TASK-512 later builds S03-03/04 (section 'built'); the opening stays as TASK-511 built it.
        self.assertEqual(s03['designVersion'], 2); self.assertIn(s03['status'], ('partial','built'))
        enc = m['encounters'][8:12]
        self.assertEqual([e['status'] for e in enc[:2]], ['built','built'])
        self.assertEqual([c['status'] for c in m['connectors'][8:10]], ['built','built'])
        sc = m['shortcuts'][0]
        self.assertEqual((sc['from'], sc['to'], sc['optional'], sc['status']), ('S03-01', 'S03-04', True, 'planned'))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S03-')]
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S03-')}
        self.assertTrue(set(self.MOVERS) <= set(movers))
        exceptions = {x['element']:x for x in s03['solidExceptions']}
        roles = {}
        for e in own:
            roles[e['id']] = 'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce' else \
                'drag zone' if e['role'] == 'drag' else 'solid '+exceptions[e['id']]['kind']+' exception'
            if e['role'] == 'solid' and e['id'] not in movers:
                self.assertIn(e['id'], exceptions)
                if exceptions[e['id']]['kind'] == 'rest-pad':
                    self.assertLessEqual(self.bounds(e)[1]-self.bounds(e)[0], 200, e['id'])
        self.assertEqual(roles[self.BUFFER], 'green bounce')
        e1, e2 = enc[0], enc[1]
        self.assertEqual(e1['start'], {'x':2050.8,'y':-2690.8,'from':'S02-04'})
        self.assertEqual(e2['start'], {'from':'S03-01','x':2569.2,'y':-3010.8})
        self.assertEqual(m['encounters'][7]['exit'], {'left':2040,'right':2200,'top':-2700,'bottom':-2680})
        self.assertIn('S03-carriage', e1['elements']); self.assertIn('S03-pier', e1['elements'])
        self.assertIn('S03-lift', e2['elements']); self.assertIn(self.BUFFER, e2['elements'])
        # Distinct roles: S03-01 has no green bounce, S03-02 has the green buffer rebound.
        self.assertFalse(any(roles[x] == 'green bounce' for x in e1['elements'] if x in roles))
        v2 = next(s for s in r['report']['sections'] if s['id'] == 'S03')
        self.assertEqual((v2['designVersion'], v2['passed'], v2['errors'], v2['range']), (2, True, [], self.RANGE))
        for name in ('bounceDefault','moverCoverage','direction','gapBand','fallDrag'):
            self.assertTrue(v2['rules'][name]['passed'], name)
        direction = v2['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('right', 'right'))
        mover_encounters = v2['rules']['moverCoverage']['measured']['encounters']
        self.assertEqual(mover_encounters[:2], ['S03-01','S03-02'])
        gaps = v2['rules']['gapBand']['measured']['gaps']
        self.assertEqual([g['id'] for g in gaps][:2], ['S03-01-carriage','S03-02-lift'])
        gaps = gaps[:2]
        for g in gaps:
            self.assertTrue(self.BAND[0] <= g['distance'] <= self.BAND[1], g)
        self.assertEqual(v2['rules']['gapBand']['measured']['target'], list(self.BAND))
        # TASK-514 later rebuilds S04 as layout v2; the first three v2 sections stay as built here.
        self.assertEqual(r['report']['v2'][:3], ['S01','S02','S03'])
        self.assertFalse(r['report']['failed'])
        # Travelling right: every S03-01/02 route element sits right of the S02 exit pad's left lip.
        route = [e for e in own if e['id'] in set(e1['elements']+e2['elements'])]
        self.assertTrue(all(self.bounds(e)[0] >= 2000 for e in route))
        self.assertLess(self.bounds(next(e for e in own if e['id']=='S03-pier'))[0],
                        self.bounds(next(e for e in own if e['id']=='S03-far-deck'))[0])
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report (TASK-504)',
            section=v2, all_applicable_rules_passed=True, encounters=['S03-01','S03-02'], planned=['S03-03','S03-04'],
            direction=direction, mover_encounters=mover_encounters,
            gap_targets_reference='artifacts/TASK-503/calibration.json gap_metric (459-486 at 540)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps},
            fall_lines='none declared yet (S03-03/04 and the S03 fall recovery are planned); rule passes over an empty list',
            other_v2_sections={s['id']:s['passed'] for s in r['report']['sections'] if not s['legacy']}))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s03, encounters=enc[:2], planned_encounters=enc[2:],
            connectors=m['connectors'][8:13], shortcut=sc, recovery=m['recoveries'][2], elements=own,
            movers=list(movers.values()), roles=roles,
            encounter_roles={'S03-01':'blue departure carriage (x mover) pulled up-right from the S02 exit pad; the swing skims '
                                       'its underside (mover contact) and carries rightward speed onto the pier pad against its low right lip',
                             'S03-02':'blue span lift (y mover) pulled up-right from the pier; release across the broken span, landing '
                                       'beyond the 540 grapnel range; the green buffer rebounds the arc onto the far deck against its tall left lip'},
            runtime_matches_manifest=True, long_walking_floors=False,
            removed_v1_elements=['S03-departure-beam','S03-rest-ledge','S03-lower-bridge','S03-flight-beam','S03-return-beam',
                'S03-upper-beam','S03-brake-beam','S03-exit-anchor','S02-exit (legacy v1 S03 entrance deck)'],
            legacy_kept={'S03-exit':'v1 S04-01 entrance deck, cropped 240 -> 200 from the right; v1 S04-01 start (5050.8,-4830.8) unchanged; '
                                    'connector S04-entrance stays planned until S03-04 is rebuilt'}))
        self.overview(elements, own, movers, roles, s03, enc[:2], gaps)
        print('PASS geometry: S03 designVersion 2 partial (S03-01/02 built, 03/04 planned); roles', sorted(set(roles.values())),
              '; validator rules all pass; direction right; gaps', [round(g['distance'],1) for g in gaps],
              '; shortcut S03-01 -> S03-04 kept (planned); overview.png')

    def overview(self, elements, own, movers, roles, s03, enc, gaps):
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="1900 -3700 1800 1125" style="background:#111827">']
        for e in elements:
            if not e['id'].startswith('S02-'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = 'rgba(160,160,160,.18)' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>')
            if e['role'] != 'drag':
                parts.append(f'<text x="{e["x"]}" y="{e["y"]+40}" fill="#9ca3af" font-size="20">{e["id"]}</text>')
        for e in own:
            if e['id'] == 'S03-exit': continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            parts.append(f'<polygon points="{pts}" fill="{colors.get(roles[e["id"]], "#a3a3a3")}" stroke="white" stroke-width="2"/>')
            label_y = e['y']-30 if e['id'] in movers or e['id'] == self.BUFFER else e['y']+60
            parts.append(f'<text x="{e["x"]}" y="{label_y}" fill="white" font-size="24">{e["id"]}</text>')
        for v in movers.values():
            e = next(x for x in own if x['id'] == v['element'])
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]-10}" x2="{e["x"]+60+dx}" y2="{e["y"]-10+dy}" stroke="#2f86ff" stroke-width="5" stroke-dasharray="10,6"/>')
        for g in s03['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="8,6"/>')
        for e in enc:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]-20}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]+20}" fill="none" stroke="#f472b6" stroke-width="4"/>')
        parts.append(f'<circle cx="2569.2" cy="-3010.8" r="{self.RANGE}" fill="none" stroke="#fb7185" stroke-width="2" stroke-dasharray="6,8"/>')
        for x, y in ((2050.8,-2690.8),(2569.2,-3010.8),(3380.8,-3260.8)):
            parts.append(f'<circle cx="{x}" cy="{y}" r="11" fill="#ff7a1a"/>')
        for i, t in enumerate(['S03 Broken Viaduct layout v2 (direction right): S02 exit-pad rest (orange) -> S03-01 blue carriage -> pier',
                '-> S03-02 blue span lift -> long release across the span -> green buffer rebound -> far deck',
                'yellow = gaps %s of 540; pink = exit boxes; red circle = 540 range from the pier; grey = S02 v2' % '/'.join(str(round(g['distance'],1)) for g in gaps)]):
            parts.append(f'<text x="1920" y="{-3660+i*36}" fill="#67e8f9" font-size="26">{t}</text>')
        parts.append('</svg>')
        page = self.browser.new_page(viewport=dict(width=1280, height=800)); self.addCleanup(page.close)
        page.set_content('<style>body{margin:0}</style>'+''.join(parts))
        page.screenshot(path=str(self.evidence.path('overview.png')))

    def events(self, mech):
        return [(e['type'], e['element']) for e in mech if e['type'] in ('acquisition','release')]

    def reach(self, players, mech, press_tick, element):
        return Task508Tests.reach(self, players, mech, press_tick, element)

    def isolated(self, name, plan, ticks, box):
        start = self.s02_exit()
        trace, mech, players, result = self.replay(name, plan, ticks, self.BOXES[box], kind='isolated', snapshot=start)
        self.filmstrip('encounters/'+name, VIEWPORT)
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        self.assertTrue(self.at_rest(players[0], 'S02-04'), players[0])
        result.update(proof_kind='isolated: one labeled initial placement = restoreClimbState of the real S02 exit rest pose '
                      'from one base-start real-input S01+S02 run; production input/physics thereafter; not a continuous-completion claim',
            not_continuous_completion_claim=True, initial_placement=dict(labeled=True, source=self.start_proof),
            mechanic_events=[dict(tick=x['tick'], type=x['type'], element=x['element'], mover=x['element'] in self.MOVERS,
                player=x['player']) for x in mech])
        return trace, mech, players, result

    def s03_01_checks(self, trace, mech, players):
        carriage = self.reach(players, mech, 5, 'S03-carriage')
        anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']=='S03-carriage']
        self.assertGreater(abs(anchors[-1]['x']-anchors[0]['x']), 1)
        # The swing skims the moving carriage's underside and keeps rightward speed. Contacts carry
        # no element id; the carriage is the only surface with its underside at y -3120, and the
        # contact lies inside its x travel (2190..2430).
        contact = [dict(tick=e['tick'], type='mover contact', element='S03-carriage', contact=e['contact'],
                        player=e['after']['simulation']['player']) for e in trace['events']
                   if e['type']=='contact' and e['tick'] > 45 and e['contact']['y'] == -3120 and e['contact']['ny'] == 1]
        self.assertTrue(contact)
        self.assertTrue(2190 <= contact[0]['contact']['x'] <= 2430, contact[0])
        self.assertGreater(contact[0]['player']['speedX'], 0)
        landed = next(t for t in range(45, 200) if self.at_rest(players[t], 'S03-01'))
        self.assertTrue(all(self.at_rest(p, 'S03-01') for p in players[landed:200]))
        return carriage, dict(dx=anchors[-1]['x']-anchors[0]['x'], ticks=len(anchors)), contact[0], landed

    def test_02_s03_01_nominal(self):
        trace, mech, players, result = self.isolated('S03-01', self.S03_01, 200, 'S03-01')
        self.assertEqual(self.events(mech), [('acquisition','S03-carriage'),('release','S03-carriage')])
        carriage, travel, contact, landed = self.s03_01_checks(trace, mech, players)
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (2569.2, -3010.8))
        self.assertTrue(all(p['x'] >= 2040 for p in players))
        result.update(encounter='S03-01', carriage_reach=carriage, carriage_anchor_travel_while_attached=travel,
            carriage_underside_contact=contact, pier_rest_from_tick=landed, pier_rest=players[landed])
        result['mechanic_events'] = sorted(result['mechanic_events']+[contact], key=lambda x: x['tick'])
        self.evidence.write('encounters/S03-01/result.json', result)
        print('PASS S03-01: from the real S02 exit rest; blue carriage acquisition', round(carriage['distance'],1),
              '; underside contact tick', contact['tick'], '; pier rest from tick', landed, 'at',
              (round(players[-1]['x'],1), round(players[-1]['y'],1)), '; identical replay; trusted input')

    def test_03_s03_02_nominal(self):
        trace, mech, players, result = self.isolated('S03-02', self.S03_01+self.S03_02, 450, 'S03-02')
        self.assertEqual(self.events(mech), [('acquisition','S03-carriage'),('release','S03-carriage'),
            ('acquisition','S03-lift'),('release','S03-lift')])
        contact = self.s03_01_checks(trace, mech, players)[2]
        result['mechanic_events'] = sorted(result['mechanic_events']+[contact], key=lambda x: x['tick'])
        self.assertTrue(self.at_rest(players[199], 'S03-01'), players[199])
        launch = players[200]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (2569.2, -3010.8))
        lift = self.reach(players, mech, 200, 'S03-lift')
        anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']=='S03-lift']
        self.assertGreater(abs(anchors[-1]['y']-anchors[0]['y']), 1)
        bounce = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']==self.BUFFER)
        before, after = bounce['before']['simulation']['player'], bounce['after']['simulation']['player']
        self.assertGreater(before['speedX'], 0); self.assertLess(after['speedX'], 0)
        # Beyond direct acquisition range: the buffer and the landing lie farther than 540 from the launch rest.
        far = lambda p: ((p['x']-launch['x'])**2 + (p['y']-launch['y'])**2) ** .5
        self.assertGreater(far(before), self.RANGE)
        landed = next(t for t in range(265, 451) if self.at_rest(players[t], 'S03-02'))
        self.assertTrue(all(self.at_rest(p, 'S03-02') for p in players[landed:]))
        self.assertGreater(far(players[landed]), self.RANGE)
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (3380.8, -3260.8))
        rules = json.loads(self.evidence.path('rules.json').read_text()) if self.evidence.path('rules.json').exists() else None
        carriage = self.reach(players, mech, 5, 'S03-carriage')
        if rules:
            rules['trace_measured_reach'] = {'S03-carriage':carriage, 'S03-lift':lift}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S03-02', s03_01_exit_at_tick_199=players[199], lift_reach=lift,
            lift_anchor_travel_while_attached=dict(dy=anchors[-1]['y']-anchors[0]['y'], ticks=len(anchors)),
            buffer_bounce=dict(tick=bounce['tick'], before=before, after=after, distance_from_launch=far(before)),
            span=dict(launch=dict(x=launch['x'], y=launch['y']), range=self.RANGE, landing_distance_from_launch=far(players[landed]),
                beyond_range=True, release_tick=265, buffer_bounce_tick=bounce['tick']),
            far_deck_rest_from_tick=landed, far_deck_rest=players[landed])
        self.evidence.write('encounters/S03-02/result.json', result)
        print('PASS S03-02: from the S03-01 pier rest; blue lift acquisition', round(lift['distance'],1),
              '; green buffer rebound tick', bounce['tick'], 'at', round(far(before),1), 'from launch; far-deck rest from tick', landed,
              round(far(players[landed]),1), 'from launch (> 540); identical replay; trusted input')


class Task512Tests(unittest.TestCase):
    """Layout-v2 Broken Viaduct S03-03/04, section exit and drag-column fall recovery onto S02, with real input."""
    task_id = 'TASK-512'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    replay = Task506Tests.replay
    filmstrip = Task507Tests.filmstrip
    bounds = Task509Tests.bounds
    brake_ticks = Task509Tests.brake_ticks
    s02_exit = Task511Tests.s02_exit
    at_rest = Task511Tests.at_rest
    events = Task511Tests.events
    test_06_source_hashes = Task465Tests.test_03_source_hashes
    BASE_ROUTE = Task511Tests.BASE_ROUTE
    S03_01, S03_02 = Task511Tests.S03_01, Task511Tests.S03_02
    # S03-03: a steep crest-hook pull (held 45) clears the span buffer top; the ledge is then
    # acquired in flight past the apex (press 620, held 20) and pulls the arc into the brake.
    CREST, LEDGE, TROLLEY, PAD = (3520,-3715), (4107,-3632), (4353,-4055), (4680,-3832)
    S03_03 = [(455,'mousedown',*CREST),(500,'mouseup',*CREST),(620,'mousedown',*LEDGE),(640,'mouseup',*LEDGE)]
    # S03-04: the trolley pull (held 44), then a press toward the exit pad (890, held 15) whose ray
    # strikes the blue trolley's top face as the arc passes over it: the in-flight re-catch splits
    # the long trolley flight and tames the arc into the exit brake.
    S03_04 = [(755,'mousedown',*TROLLEY),(799,'mouseup',*TROLLEY),(890,'mousedown',*PAD),(905,'mouseup',*PAD)]
    NOMINAL = S03_01+S03_02+S03_03+S03_04
    # Mistimed S03-02: the span lift is released after 50 ticks instead of 65. The arc rebounds
    # off the buffer back over the span, drops through the S03 fall column onto the S02 landing
    # deck; the rejoin is the unchanged S02-03 crest-hook pull plus in-flight ledge catch.
    REJOIN = [(t+175, e, x, y) for t, e, x, y in Task510Tests.S02_03]
    FALL = S03_01+[(200,'mousedown',*Task511Tests.LIFT),(250,'mouseup',*Task511Tests.LIFT)]+REJOIN
    MOVERS = ('S03-carriage','S03-lift','S03-trolley')
    BUFFER = 'S03-span-buffer'
    DRAG = dict(id='S03-fall-drag', left=3030, right=3140, top=-3310, bottom=-2400)
    LEDGE_BRAKE = dict(id='S03-ledge-brake', left=4007, right=4207, top=-3710, bottom=-3630)
    EXIT_BRAKE = dict(id='S03-exit-brake', left=4600, right=4750, top=-3920, bottom=-3830)
    BAND, RANGE = (459, 486), 540
    REST = Task511Tests.REST
    BOXES = dict(Task511Tests.BOXES, **{
        'S03-03':dict(x=[4007,4167],y=[-3641,-3640],**REST),
        'S03-04':dict(x=[4600,4710],y=[-3841,-3840],**REST),
        'S02-landing':dict(x=[2987,3147],y=[-2111,-2110],**REST),
        'S02-ledge':dict(x=[2350,2510],y=[-2491,-2490],**REST)})

    def reach(self, players, mech, press_tick, element):
        return Task508Tests.reach(self, players, mech, press_tick, element)

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']
        byid = {e['id']:e for e in elements}
        s03 = m['sections'][2]
        self.assertEqual((s03['designVersion'], s03['status']), (2, 'built'))
        enc = m['encounters'][8:12]
        self.assertEqual([e['status'] for e in enc], ['built']*4)
        for a, b in zip(enc, enc[1:]):
            self.assertEqual(b['start']['from'], a['id'])
        # TASK-514 builds the S04 entrance (connectors[12]) from the S03 exit pad.
        self.assertEqual([c['status'] for c in m['connectors'][8:12]], ['built','built','built','built'])
        self.assertIn(m['connectors'][12]['status'], ('planned','built'))
        sc = m['shortcuts'][0]
        self.assertEqual((sc['from'], sc['to'], sc['optional']), ('S03-01', 'S03-04', True))
        rec = m['recoveries'][2]
        self.assertEqual((rec['from'], rec['to'], rec['status'], rec['transport'], rec['rejoin']),
                         ('S03-04', 'S02-01', 'built', 'physical-fall', 'S02-03'))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S03-')]
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S03-')}
        self.assertEqual(set(movers), set(self.MOVERS))
        exceptions = {x['element']:x for x in s03['solidExceptions']}
        roles = {}
        for e in own:
            roles[e['id']] = 'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce' else \
                'drag zone' if e['role'] == 'drag' else 'solid '+exceptions[e['id']]['kind']+' exception'
            if e['role'] == 'solid' and e['id'] not in movers:
                self.assertIn(e['id'], exceptions)
                if exceptions[e['id']]['kind'] == 'rest-pad':
                    self.assertLessEqual(self.bounds(e)[1]-self.bounds(e)[0], 200, e['id'])
        self.assertEqual((roles['S03-crest-hook'], roles['S03-trolley'], roles[self.BUFFER]), ('green bounce','blue mover','green bounce'))
        for z in (self.DRAG, self.LEDGE_BRAKE, self.EXIT_BRAKE):
            self.assertEqual((roles[z['id']], self.bounds(byid[z['id']])), ('drag zone', (z['left'], z['right'], z['top'], z['bottom'])))
        # Brake into a narrower landing: the exit pad is narrower than every earlier S03 rest pad.
        width = lambda i: self.bounds(byid[i])[1]-self.bounds(byid[i])[0]
        self.assertEqual(width('S03-exit-pad'), 150)
        self.assertTrue(all(width(i) > 150 for i in ('S03-pier','S03-far-deck','S03-ledge')))
        self.assertEqual(enc[2]['start'], {'from':'S03-02','x':3380.8,'y':-3260.8})
        # TASK-513 retunes the S03-03 nominal (crest aim 3508), moving the ledge rest from
        # 4128.5 to 4104.7; either way S03-04 starts on the ledge deck.
        self.assertEqual((enc[3]['start']['from'], enc[3]['start']['y']), ('S03-03', -3640.8))
        self.assertIn(enc[3]['start']['x'], (4128.5, 4104.7))
        self.assertIn('S03-crest-hook', enc[2]['elements']); self.assertIn('S03-ledge', enc[2]['elements'])
        self.assertIn('S03-trolley', enc[3]['elements']); self.assertIn('S03-exit-pad', enc[3]['elements'])
        v2 = next(s for s in r['report']['sections'] if s['id'] == 'S03')
        self.assertEqual((v2['designVersion'], v2['passed'], v2['errors'], v2['range']), (2, True, [], self.RANGE))
        for name in ('bounceDefault','moverCoverage','direction','gapBand','fallDrag'):
            self.assertTrue(v2['rules'][name]['passed'], name)
        direction = v2['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('right', 'right'))
        self.assertGreater(direction['exitX'], direction['entryX'])
        mover_encounters = v2['rules']['moverCoverage']['measured']['encounters']
        self.assertEqual(mover_encounters, ['S03-01','S03-02','S03-04'])
        gaps = v2['rules']['gapBand']['measured']['gaps']
        self.assertEqual([g['id'] for g in gaps], ['S03-01-carriage','S03-02-lift','S03-03-crest','S03-04-trolley'])
        for g in gaps:
            self.assertTrue(self.BAND[0] <= g['distance'] <= self.BAND[1], g)
        self.assertEqual(v2['rules']['gapBand']['measured']['target'], list(self.BAND))
        falls = v2['rules']['fallDrag']['measured']['fallLines']
        self.assertTrue(falls)
        for f in falls:
            self.assertEqual((f['landing'], f['landingSection'], f['onBelow'], f['underLanding'], f['dragZone']),
                ('S02-landing', 'S02', True, True, self.DRAG['id']), f)
            z = self.bounds(byid[f['dragZone']]); land = self.bounds(byid[f['landing']])
            self.assertTrue(z[0] <= f['x'] <= z[1] and land[0] <= f['x'] <= land[1])
            self.assertLessEqual(z[3], land[2])
        self.assertEqual(r['report']['v2'][:3], ['S01','S02','S03'])
        self.assertFalse(r['report']['failed'])
        self.assertTrue(all(s['passed'] for s in r['report']['sections'] if not s['legacy']))
        # Travelling right: every S03-03/04 route element lies right of the far deck's left lip.
        route = [e for e in own if e['id'] in set(enc[2]['elements']+enc[3]['elements'])]
        self.assertTrue(all(self.bounds(e)[0] >= 3330 for e in route))
        # Below each S03 route element, the first S02 surface it would hit.
        s02 = [e for e in elements if e['id'].startswith('S02-') and e['role'] != 'drag']
        below = {}
        for e in own:
            if e['role'] == 'drag' or e['id'] == 'S03-exit': continue
            b = self.bounds(e); mid = (b[0]+b[1])/2
            under = sorted([x for x in s02 if self.bounds(x)[0] <= mid <= self.bounds(x)[1] and self.bounds(x)[2] > b[3]],
                           key=lambda x: self.bounds(x)[2])
            below[e['id']] = under[0]['id'] if under else 'none in S02'
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report (TASK-504)',
            section=v2, all_applicable_rules_passed=True, encounters=['S03-01','S03-02','S03-03','S03-04'],
            direction=direction, mover_encounters=mover_encounters,
            gap_targets_reference='artifacts/TASK-503/calibration.json gap_metric (459-486 at 540)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps}, fall_lines=falls,
            drag_zones_under_every_fall_line=True,
            other_v2_sections={s['id']:s['passed'] for s in r['report']['sections'] if not s['legacy']}))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s03, encounters=enc,
            connectors=m['connectors'][8:13], shortcut=sc, recovery=rec, elements=own, movers=list(movers.values()),
            roles=roles, encounter_roles={
                'S03-01':'blue departure carriage pulled up-right from the S02 exit pad; underside skim onto the pier pad',
                'S03-02':'blue span lift; release across the broken span beyond 540 range; green buffer rebound onto the far deck',
                'S03-03':'green crest hook pulled steeply over the span buffer; the ledge is acquired in flight past the apex and '
                         'pulls the arc into the ledge brake',
                'S03-04':'blue trolley pulled up-right from the ledge; the trolley is re-caught on its top face in flight, '
                         'then the arc brakes in the exit brake into the narrower (150) exit pad left of its tall right lip (section exit)'},
            section_exit=dict(element='S03-exit-pad', box=enc[3]['exit'], rest=dict(x=4657.3, y=-3840.8)),
            s02_element_below=below, runtime_matches_manifest=True, long_walking_floors=False,
            shortcut_note='S03-01 -> S03-04 optional shortcut kept (status planned, not yet authored for layout v2)',
            legacy_kept={'S03-exit':'v1 S04-01 entrance deck (start 5050.8,-4830.8) kept until S04 is rebuilt; connector S04-entrance stays planned'}))
        self.overview(elements, own, movers, roles, s03, enc, gaps)
        print('PASS geometry: S03 designVersion 2 built (4/4 encounters); roles', sorted(set(roles.values())),
              '; validator rules all pass; direction right', direction['entryX'], '->', direction['exitX'],
              '; gaps', [round(g['distance'],1) for g in gaps], '; fall lines', [f['id'] for f in falls], 'over', self.DRAG['id'],
              '; shortcut S03-01 -> S03-04 kept (optional, planned); overview.png')

    def overview(self, elements, own, movers, roles, s03, enc, gaps):
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84','drag zone':'rgba(255,196,0,.40)'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960" viewBox="1900 -4250 3000 2250" style="background:#111827">']
        for e in elements:
            if not e['id'].startswith('S02-'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = 'rgba(160,160,160,.18)' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>')
            if e['role'] != 'drag':
                parts.append(f'<text x="{e["x"]}" y="{e["y"]+45}" fill="#9ca3af" font-size="22">{e["id"]}</text>')
        for e in own:
            if e['id'] == 'S03-exit': continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            parts.append(f'<polygon points="{pts}" fill="{colors.get(roles[e["id"]], "#a3a3a3")}" stroke="white" stroke-width="2"/>')
            label_y = e['y']-30 if e['id'] in movers or roles[e['id']] == 'green bounce' else e['y']+60
            if e['id'] == self.DRAG['id']: label_y = e['y']+450
            parts.append(f'<text x="{e["x"]}" y="{label_y}" fill="white" font-size="24">{e["id"]}</text>')
        for v in movers.values():
            e = next(x for x in own if x['id'] == v['element'])
            dx, dy = (v['max']-v['min'], 0) if v['axis'] == 'x' else (0, v['max']-v['min'])
            parts.append(f'<line x1="{e["x"]+60}" y1="{e["y"]-10}" x2="{e["x"]+60+dx}" y2="{e["y"]-10+dy}" stroke="#2f86ff" stroke-width="5" stroke-dasharray="10,6"/>')
        for g in s03['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="8,6"/>')
        for e in enc:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]-20}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]+20}" fill="none" stroke="#f472b6" stroke-width="4"/>')
        for f in s03['fallLines']:
            parts.append(f'<line x1="{f["x"]}" y1="-3400" x2="{f["x"]}" y2="-2110" stroke="#fb7185" stroke-width="4" stroke-dasharray="4,10"/>'
                         f'<text x="{f["x"]+10}" y="-2200" fill="#fb7185" font-size="24">{f["id"]} -> {f["landing"]}</text>')
        for x, y in ((2050.8,-2690.8),(2569.2,-3010.8),(3380.8,-3260.8),(4128.5,-3640.8),(4657.3,-3840.8)):
            parts.append(f'<circle cx="{x}" cy="{y}" r="12" fill="#ff7a1a"/>')
        for i, t in enumerate(['S03 Broken Viaduct layout v2 (direction right): S02 exit pad -> S03-01 carriage -> pier -> S03-02 lift/span/buffer -> far deck',
                '-> S03-03 green crest hook + in-flight ledge catch -> ledge brake -> S03-04 blue trolley (+ in-flight top re-catch) -> exit brake -> narrower exit pad',
                'yellow = gaps %s of 540; pink = exit boxes; amber = drag zones; red dashes = fall line onto S02-landing; grey = S02 v2' % '/'.join(str(round(g['distance'],1)) for g in gaps)]):
            parts.append(f'<text x="1920" y="{-4200+i*40}" fill="#67e8f9" font-size="28">{t}</text>')
        parts.append('</svg>')
        page = self.browser.new_page(viewport=dict(width=1280, height=960)); self.addCleanup(page.close)
        page.set_content('<style>body{margin:0}</style>'+''.join(parts))
        page.screenshot(path=str(self.evidence.path('overview.png')))

    def isolated(self, name, plan, ticks, box, start, source):
        trace, mech, players, result = self.replay(name, plan, ticks, self.BOXES[box], kind='isolated', snapshot=start)
        self.filmstrip('encounters/'+name, VIEWPORT)
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        result.update(proof_kind='isolated: one labeled initial placement = restoreClimbState of '+source+
                      '; production input/physics thereafter; not a continuous-completion claim',
            not_continuous_completion_claim=True, initial_placement=dict(labeled=True, source=source,
                s02_exit_start=self.start_proof))
        return trace, mech, players, result

    def s03_03_checks(self, trace, mech, players, t0=0):
        """S03-03 from the far-deck rest at local tick t0 (455 in the S03 nominal timeline)."""
        crest = self.reach(players, mech, t0+455, 'S03-crest-hook')
        # The steep pull clears the span buffer (x 3500..3530, top -3520) above its top.
        over = [p for p in players[t0+455:] if 3500-p['radius'] <= p['x'] <= 3530+p['radius']]
        self.assertTrue(over and all(p['y'] < -3520-p['radius'] for p in over))
        self.assertFalse([e for e in mech if e['type']=='bounce' and e['tick'] > t0+455])
        ledge = next(e for e in mech if e['type']=='acquisition' and e['element']=='S03-ledge')
        release = next(e for e in mech if e['type']=='release' and e['element']=='S03-crest-hook')
        p = ledge['player']
        # Acquired in flight: after the crest release, airborne well above the ledge deck, moving right.
        self.assertGreater(ledge['tick'], release['tick'])
        self.assertTrue(p['y'] < -3630-p['radius']-100 and p['speedX'] > 0, p)
        brake = [t for t in self.brake_ticks(players, self.LEDGE_BRAKE) if t > ledge['tick']]
        self.assertTrue(brake)
        landed = next(t for t in range(ledge['tick'], t0+751) if self.at_rest(players[t], 'S03-03'))
        self.assertTrue(all(self.at_rest(q, 'S03-03') for q in players[landed:t0+751]))
        return dict(crest_reach=crest, buffer_cleared=dict(ticks=len(over), max_y=max(q['y'] for q in over), buffer_top=-3520),
            crest_release=dict(tick=release['tick'], player=release['player']),
            in_flight_ledge_acquisition=dict(tick=ledge['tick'], player=p, anchor=ledge['rope'][0],
                ticks_after_crest_release=ledge['tick']-release['tick']),
            ledge_brake=dict(id=self.LEDGE_BRAKE['id'], entry_tick=brake[0], speedX_before=players[brake[0]-1]['speedX']),
            ledge_rest_from_tick=landed, ledge_rest=players[landed])

    def test_02_s03_03_nominal(self):
        start = self.s02_exit()
        trace, mech, players, result = self.isolated('S03-03', self.S03_01+self.S03_02+self.S03_03, 750, 'S03-03',
            start, 'the real S02 exit rest (base-start S01+S02 run); S03-01/02 nominal inputs then S03-03')
        self.assertEqual(self.events(mech), [('acquisition','S03-carriage'),('release','S03-carriage'),
            ('acquisition','S03-lift'),('release','S03-lift'),('acquisition','S03-crest-hook'),('release','S03-crest-hook'),
            ('acquisition','S03-ledge'),('release','S03-ledge')])
        self.assertTrue(self.at_rest(players[454], 'S03-02'), players[454])
        self.assertEqual((round(players[454]['x'],1), round(players[454]['y'],1)), (3380.8, -3260.8))
        checks = self.s03_03_checks(trace, mech, players)
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (4128.5, -3640.8))
        type(self).s03_03_end = trace['snapshots'][-1]['state']['simulation']
        type(self).s03_03_end_sha256 = trace['snapshots'][-1]['sha256']
        result.update(encounter='S03-03', s03_02_exit_at_tick_454=players[454], **checks)
        self.evidence.write('encounters/S03-03/result.json', result)
        print('PASS S03-03: from the real S03-02 far-deck rest; green crest hook', round(checks['crest_reach']['distance'],1),
              '; over the buffer top; ledge acquired in flight tick', checks['in_flight_ledge_acquisition']['tick'],
              '; ledge brake entry', checks['ledge_brake']['entry_tick'], '; ledge rest from tick', checks['ledge_rest_from_tick'],
              '; identical replay; trusted input')

    def s03_04_checks(self, trace, mech, players, press):
        trolley = self.reach(players, mech, press, 'S03-trolley')
        anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']=='S03-trolley']
        self.assertGreater(abs(anchors[-1]['x']-anchors[0]['x']), 1)
        first, release = [e for e in mech if e['type']=='release' and e['element']=='S03-trolley'][-2:]
        grabs = [e for e in mech if e['type']=='acquisition' and e['element']=='S03-trolley']
        pad = grabs[-1]
        # First pull hangs from the trolley underside (-4055); the in-flight re-catch after the first
        # release lands on its top face (-4085) with the player airborne above it.
        self.assertEqual((round(grabs[-2]['rope'][0]['y']), round(pad['rope'][0]['y'])), (-4055, -4085))
        self.assertGreater(pad['tick'], first['tick'])
        self.assertTrue(pad['player']['y'] < -4085-pad['player']['radius'], pad['player'])
        brake = [t for t in self.brake_ticks(players, self.EXIT_BRAKE) if t > release['tick']]
        self.assertTrue(brake)
        entry = brake[0]; before = players[entry-1]
        self.assertGreater(before['speedX'], .1)
        landed = next(t for t in range(release['tick'], len(players)) if self.at_rest(players[t], 'S03-04'))
        self.assertTrue(all(self.at_rest(p, 'S03-04') for p in players[landed:]))
        # Braked, not stopped by the lip: the rest lies left of the tall right lip (x 4710..4750).
        self.assertLess(players[-1]['x']+players[-1]['radius'], 4710)
        return dict(trolley_reach=trolley, trolley_anchor_travel_while_attached=dict(dx=anchors[-1]['x']-anchors[0]['x'], ticks=len(anchors)),
            trolley_release=dict(tick=first['tick'], player=first['player']),
            in_flight_trolley_recatch=dict(tick=pad['tick'], player=pad['player'], anchor=pad['rope'][0], face='top (-4085)',
                ticks_after_first_release=pad['tick']-first['tick'], release_tick=release['tick']),
            exit_brake=dict(id=self.EXIT_BRAKE['id'], entry_tick=entry, speedX_before=before['speedX'],
                speedX_series=[players[t]['speedX'] for t in range(entry-1, min(entry+12, len(players)))]),
            exit_rest_from_tick=landed, section_exit=dict(element='S03-exit-pad', width=150, rest=players[landed]))

    def test_03_s03_04_nominal(self):
        if not hasattr(type(self), 's03_03_end'): self.test_02_s03_03_nominal()
        start = type(self).s03_03_end
        self.assertTrue(self.at_rest(start['player'], 'S03-03'), start['player'])
        plan = [(t-750, e, x, y) for t, e, x, y in self.S03_04]
        trace, mech, players, result = self.isolated('S03-04', plan, 400, 'S03-04', start,
            'the S03-03 nominal run final state (tick 750, encounters/S03-03/trace.json)')
        self.assertEqual(self.events(mech), [('acquisition','S03-trolley'),('release','S03-trolley')]*2)
        checks = self.s03_04_checks(trace, mech, players, 5)
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (4661.3, -3840.8))
        result.update(encounter='S03-04', start_state_sha256=type(self).s03_03_end_sha256, **checks)
        self.evidence.write('encounters/S03-04/result.json', result)
        print('PASS S03-04: from the S03-03 ledge rest; blue trolley', round(checks['trolley_reach']['distance'],1),
              '; exit brake entry', checks['exit_brake']['entry_tick'], 'vx', round(checks['exit_brake']['speedX_before'],3),
              '; exit-pad rest from tick', checks['exit_rest_from_tick'], 'at', (round(players[-1]['x'],1), round(players[-1]['y'],1)),
              '; identical replay; trusted input')

    def test_04_full_traversal(self):
        start = self.s02_exit()
        trace, mech, players, result = self.isolated('S03-full', self.NOMINAL, 1150, 'S03-04', start,
            'the real S02 exit rest (base-start S01+S02 run)')
        self.assertEqual([a for a in self.events(mech) if a[0]=='acquisition'],
            [('acquisition',x) for x in ('S03-carriage','S03-lift','S03-crest-hook','S03-ledge','S03-trolley','S03-trolley')])
        checkpoints = {}
        for name, tick in (('S03-01',199),('S03-02',454),('S03-03',754)):
            self.assertTrue(self.at_rest(players[tick], name), (name, players[tick]))
            checkpoints[name] = dict(tick=tick, player=players[tick])
        s03_03 = self.s03_03_checks(trace, mech, players)
        s03_04 = self.s03_04_checks(trace, mech, players, 755)
        checkpoints['S03-04'] = dict(tick=s03_04['exit_rest_from_tick'], player=players[s03_04['exit_rest_from_tick']])
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (4657.3, -3840.8))
        reaches = [self.reach(players, mech, t, el) for t, el in ((5,'S03-carriage'),(200,'S03-lift'),(455,'S03-crest-hook'),(755,'S03-trolley'))]
        # Never drops below the S02 exit pad: the whole traversal stays in the S03 airspace.
        self.assertTrue(all(p['y'] <= -2690 for p in players))
        # No long dull stretch: gaps between acquisitions, bounces and mover contacts up to the exit rest.
        # Contacts carry no element id; the carriage underside (y -3120, ny 1) is its mover contact.
        carriage = [e['tick'] for e in trace['events'] if e['type']=='contact' and e['contact']['y'] == -3120 and e['contact']['ny'] == 1]
        self.assertTrue(carriage)
        points = sorted({0, checkpoints['S03-04']['tick'], *carriage} | {e['tick'] for e in mech if e['type'] in ('acquisition','bounce','contact')
                         and e['tick'] <= checkpoints['S03-04']['tick']})
        gaps = [b-a for a, b in zip(points, points[1:])]
        self.assertLessEqual(max(gaps), 180)
        result.update(encounter='S03 full traversal', encounter_exits=checkpoints, section_exit_reached=True,
            section_exit=dict(element='S03-exit-pad', box=self.BOXES['S03-04'], rest=players[-1]), reaches=reaches,
            s03_03=s03_03, s03_04=s03_04, density=dict(interaction_ticks=points, max_gap=max(gaps), limit=180))
        self.evidence.write('encounters/S03-full/result.json', result)
        rules = json.loads(self.evidence.path('rules.json').read_text()) if self.evidence.path('rules.json').exists() else None
        if rules:
            rules['trace_measured_reach'] = {r['element']:r for r in reaches}
            self.evidence.write('rules.json', rules)
        print('PASS full S03: from the real S02 exit rest; exits at', {k:v['tick'] for k,v in checkpoints.items()},
              '; reaches', [round(r['distance'],1) for r in reaches], '; max interaction gap', max(gaps),
              '; S03 exit pad reached; identical replay; trusted input')

    def test_05_fall_through_drag_and_rejoin(self):
        start = self.s02_exit()
        press = self.REJOIN[0][0]
        trace, mech, players, result = self.isolated('fall', self.FALL, press+400, 'S02-ledge', start,
            'the real S02 exit rest (base-start S01+S02 run)')
        self.assertEqual(self.events(mech)[:4], [('acquisition','S03-carriage'),('release','S03-carriage'),
            ('acquisition','S03-lift'),('release','S03-lift')])
        released = next(e for e in mech if e['type']=='release' and e['element']=='S03-lift')
        self.assertEqual(released['tick'], 250)
        # The short arc rebounds off the span buffer back over the broken span.
        bounce = next(e for e in mech if e['type']=='bounce' and e['element']==self.BUFFER)
        self.assertLess(bounce['player']['speedX'], 0)
        z = self.DRAG
        zone = [t for t in self.brake_ticks(players, z) if bounce['tick'] < t < press]
        self.assertTrue(zone)
        entry = zone[0]
        before = players[entry-1]
        self.assertLess(before['speedX'], -.1)
        self.assertEqual(zone, list(range(entry, zone[-1]+1)))
        # Airborne in the column only horizontal speed is damped: exactly 0.8 per tick.
        ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in zone[:-1] if players[t]['speedX']]
        self.assertTrue(ratios and all(abs(x-.8) < 1e-9 for x in ratios), ratios[:5])
        self.assertTrue(all(players[t+1]['speedY'] > players[t]['speedY'] for t in zone[:-1]))
        left = players[zone[-1]+1]
        self.assertLess(abs(left['speedX']), abs(before['speedX'])/100)
        deck = [e for e in trace['events'] if e['type']=='contact' and e['contact'].get('y') == -2100 and e['contact'].get('ny') == -1
                and bounce['tick'] < e['tick'] < press]
        self.assertTrue(deck)
        land = deck[0]['tick']
        rest = next(t for t in range(land, press) if self.at_rest(players[t], 'S02-landing'))
        self.assertTrue(all(self.at_rest(players[t], 'S02-landing') for t in range(rest, press)))
        after = players[rest]
        rejoin = [(e['element'], e['tick']) for e in mech if e['type']=='acquisition' and e['tick'] >= press]
        self.assertEqual([a for a,_ in rejoin], ['S02-crest-hook','S02-ledge'])
        self.assertEqual([e for e in mech if e['type']=='acquisition' and bounce['tick'] < e['tick'] < press], [])
        rejoined = next(t for t in range(press, len(players)) if self.at_rest(players[t], 'S02-ledge'))
        self.assertTrue(all(self.at_rest(p, 'S02-ledge') for p in players[rejoined:]))
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (2481.9, -2490.8))
        series = [dict(tick=t, x=players[t]['x'], y=players[t]['y'], speedX=players[t]['speedX'], speedY=players[t]['speedY'])
                  for t in range(entry-1, zone[-1]+3)]
        result.update(scenario='naturally mistimed S03-02 release (span lift held 50 ticks instead of 65) from the real S03-01 pier rest; '
                      'physical fall; no relocation after the labeled S02-exit start placement',
            release=dict(tick=released['tick'], element='S03-lift', player=released['player'], nominal_release_tick=265),
            buffer_rebound=dict(tick=bounce['tick'], element=self.BUFFER, player=bounce['player']),
            fall_line=dict(id='S03-02-short', declared_x=3085, landing='S02-landing'),
            drag_zone=dict(z, entry_tick=entry, exit_tick=zone[-1], vx_before=before['speedX'], vx_after_column=left['speedX'],
                vx_at_rest=after['speedX'], player_before=before, per_tick_vx_ratio_airborne=ratios[:40], ratio_count=len(ratios)),
            landing=dict(element='S02-landing', surface_y=-2100, first_contact_tick=land),
            rest_on_s02=dict(element='S02-landing', route='S02-02 exit / S02-03 launch deck', tick=rest, player=after, held_until_tick=press-1),
            fall_series=series,
            rejoin=dict(input_only=True, setup_spawns=trace['metadata']['setupOnlySpawns'],
                inputs=[i for i in result['inputs'] if i['tick'] >= press],
                acquisitions=[dict(element=a, tick=t) for a, t in rejoin],
                ledge_rest_tick=rejoined, ledge_rest=players[rejoined],
                encounter_rejoined='S02-03 (TASK-510 nominal crest-hook pull + in-flight ledge catch) onto the S02 ledge = S02-04 start'))
        self.evidence.write('encounters/fall/result.json', result)
        self.evidence.write('fall.json', dict(self.proof, **result))
        print('PASS fall: mistimed S03-02 release tick 250; buffer rebound tick', bounce['tick'], '; drag column entry tick', entry,
              'vx', round(before['speedX'],3), '->', left['speedX'], '; rest on S02 landing tick', rest, 'x', round(after['x'],1),
              '; input-only S02-03 rejoin to the S02 ledge tick', rejoined)


class Task513Tests(unittest.TestCase):
    """Layout-v2 Broken Viaduct (S03) tolerance on desktop and touch: recorded real input, replayable suite."""
    task_id = 'TASK-513'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    compact = Task506Tests.compact
    make_input = Task507Tests.make_input
    run_attempt = Task507Tests.run_attempt
    filmstrip = Task507Tests.filmstrip
    targets = Task507Tests.targets
    HUD = Task507Tests.HUD
    VARIANTS = Task507Tests.VARIANTS
    s02_exit = Task511Tests.s02_exit
    at_rest = Task511Tests.at_rest
    brake_ticks = Task509Tests.brake_ticks
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    BASE_ROUTE = Task511Tests.BASE_ROUTE
    BOXES, DRAG, BUFFER = Task512Tests.BOXES, Task512Tests.DRAG, Task512Tests.BUFFER
    FALL, MOVERS = Task512Tests.FALL, Task512Tests.MOVERS
    # TASK-513 tuning (with the shorter span buffer, narrower crest hook and taller exit-pad lip):
    # S03-03 pulls the crest hook 10 units further left (3508, held 45) so the arc clears both the
    # buffer top and the hook's right end; S03-04 holds the trolley 46 ticks and the in-flight
    # re-catch aims straight at the trolley top (4380,-4086), not past it at the exit pad.
    CREST, TROLLEY, TOP = (3508,-3715), Task512Tests.TROLLEY, (4380,-4086)
    S03_03 = [(455,'mousedown',*CREST),(500,'mouseup',*CREST)]+Task512Tests.S03_03[2:]
    S03_04 = [(755,'mousedown',*TROLLEY),(801,'mouseup',*TROLLEY),(885,'mousedown',*TOP),(900,'mouseup',*TOP)]
    NOMINAL = Task512Tests.S03_01+Task512Tests.S03_02+S03_03+S03_04
    # Encounter starts are ticks of one S03 nominal run from the real S02 exit rest, a few ticks
    # before the encounter's first press while the player rests on the previous pad.
    STARTS = {'S03-01':0, 'S03-02':195, 'S03-03':450, 'S03-04':750}
    PRESSES = {'S03-01':5, 'S03-02':200, 'S03-03':455, 'S03-04':755}

    @classmethod
    def encounters(cls):
        # (id, global plan, ticks, critical timing index, aim index, mechanic). Every aimed
        # surface is a horizontal face, so the aim variants move along x.
        return [('S03-01',Task512Tests.S03_01,240,1,0,'blue carriage pull up-right from the S02 exit pad; underside skim onto the pier pad'),
                ('S03-02',Task512Tests.S03_02,300,1,0,'blue span lift released across the broken span; green buffer rebound onto the far deck'),
                ('S03-03',cls.S03_03,320,1,0,'green crest hook pulled over the span buffer; ledge caught in flight, ledge brake onto the ledge'),
                ('S03-04',cls.S03_04,400,1,0,'blue trolley pull, in-flight trolley top re-catch, exit brake onto the narrow exit pad (section exit)')]

    def interactions(self, trace):
        """Acquisitions, bounces and mover contacts. Contacts carry no element id, so the carriage
        underside (y -3120, ny 1) identifies the carriage contact (as TASK-512)."""
        ticks = []
        for e in trace['events']:
            c = e.get('contact') or {}
            if e['type'] == 'acquisition': el = e['after']['rope'][0]['id']
            elif e['type'] == 'bounce': el = c.get('elementId')
            elif e['type'] == 'contact' and c.get('elementId') in self.MOVERS: el = c['elementId']
            elif e['type'] == 'contact' and c.get('y') == -3120 and c.get('ny') == 1: el = 'S03-carriage'
            else: continue
            if not ticks or ticks[-1][0] != e['tick']: ticks.append((e['tick'], e['type'], el))
        return ticks

    def density(self, trace, bounds, name):
        ticks = self.interactions(trace)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        exit_tick = next(t for t, p in enumerate(players) if all(b[0] <= p[k] <= b[1] for k, b in bounds.items()))
        points = [0]+[t for t, _, _ in ticks if t <= exit_tick]+[exit_tick]
        gaps = [b-a for a, b in zip(points, points[1:])]
        i = gaps.index(max(gaps))
        return dict(trace=name, exit_tick=exit_tick, interactions=[dict(tick=t, type=k, element=el) for t, k, el in ticks if t <= exit_tick],
                    max_gap=max(gaps), longest_gap=[points[i], points[i+1]], limit=180)

    def landed(self, name):
        """Density window end: first tick landed (|speedY| < .001) inside the exit box (as TASK-510)."""
        return {k: v for k, v in self.BOXES[name].items() if k != 'speedX'}

    def starts(self):
        """One S03 nominal run from the real S02 exit rest; its states start S03-02..04."""
        if hasattr(type(self), 'start_states'): return type(self).start_states
        from grapple_over_verify import execute, check_trace
        start = self.s02_exit()
        setup = self.make_input(self.NOMINAL, 1150, self.BOXES['S03-04'], snapshot=start)
        trace = execute(setup, self.browser, self.url, str(self.evidence.path('starts')))
        check_trace(setup, trace)
        self.evidence.write('starts/trace.json', self.compact(trace))
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        previous = {'S03-02':'S03-01','S03-03':'S03-02','S03-04':'S03-03'}
        states, rests = {'S03-01': start}, {}
        for name, t in self.STARTS.items():
            if not t: continue
            states[name] = trace['snapshots'][t]['state']['simulation']
            # At rest on the previous pad from before the start tick until the encounter's press.
            rests[name] = min(u for u in range(t+1) if all(self.at_rest(players[v], previous[name]) for v in range(u, self.PRESSES[name])))
            self.assertLess(rests[name], t, name)
        self.evidence.write('starts/snapshots.json', dict(
            s02_exit=dict(source='encounters/S02-exit-start/trace.json (base-start S01+S02 v2 routes, real mouse input)', **type(self).start_proof),
            s03_run='starts/trace.json (TASK-512 S03 nominal inputs from the S02 exit rest, real mouse input)',
            ticks={name: dict(tick=t, sha256=trace['snapshots'][t]['sha256'], player=states[name]['player'],
                              previous_pad_rest_from_tick=rests[name], first_press_tick=self.PRESSES[name])
                   for name, t in self.STARTS.items() if t}))
        type(self).start_states, type(self).start_trace = states, trace
        return states

    def test_01_tolerance_matrix(self):
        from grapple_over_verify import hashes, check_s03_mechanics
        states = self.starts()
        suite = dict(section='S03', designVersion=2, source_hashes=hashes(), level_sha256=dict(
            **{'mountain.js': hashes()['mountain.js'], 'fixedlevel.js': hashes()['fixedlevel.js']}),
            proof_kind='S03-01 from the real S02 exit rest (base-start S01+S02 routes); S03-02..04 restored from starts/trace.json states (initial_snapshot)',
            browser=self.browser.version, revision=self.proof['revision'],
            viewports=dict(desktop=VIEWPORT, touch=dict(width=844, height=390)),
            encounters={}, negative_control='negative-control.json', density='density.json',
            starts=dict(self.STARTS), start_snapshots='starts/snapshots.json',
            critical_inputs={r[0]: dict(timing_index=r[3], aim_index=r[4], tangent=(1,0), mechanic=r[5]) for r in self.encounters()})
        failures, nominal = [], {}
        for name, plan, ticks, critical, aim, mechanic in self.encounters():
            attempts = []; suite['encounters'][name] = attempts
            offset = self.STARTS[name]
            for device in ('desktop','touch'):
                for variant, delta, shift in self.VARIANTS:
                    local = [(t-offset+(delta if i==critical else 0), e, x+(shift if i in (aim, aim+1) else 0), y)
                             for i, (t, e, x, y) in enumerate(plan)]
                    label = f'{name}-{device}-{variant}'
                    prefix = ('clips/' if variant=='nominal' else 'attempts/')+label
                    m = self.make_input(local, ticks, self.BOXES[name], device, states[name])
                    trace, success, reason = self.run_attempt(m, prefix, variant=='nominal')
                    mechanics = check_s03_mechanics(name, trace, required=False)
                    if success:
                        try: check_s03_mechanics(name, trace)
                        except ValueError as error: success, reason = False, str(error)
                    targets = self.targets(trace, m['metadata']['viewport'])
                    if variant == 'nominal':
                        self.assertTrue(all(t['in_viewport'] and not t['under_hud'] for t in targets), (label, targets))
                        if success: nominal[label] = self.density(trace, self.landed(name), prefix+'/trace.json')
                    final = trace['snapshots'][-1]['state']['simulation']['player']
                    attempts.append(dict(name=label, device=device, variant=variant, critical_input_index=critical,
                        aim_input_index=aim, timing_delta=delta, tangent_aim_delta=shift, surface_tangent=(1,0),
                        input=prefix+'/input.json.gz', trace=prefix+'/trace.json', success=success, reason=reason,
                        outcome='exit reached' if success else 'intended exit missed', mechanic=mechanic, mechanic_events=mechanics,
                        press_targets=targets, source_hashes_sha256=state_hash(hashes()), level_sha256=hashes()['mountain.js'],
                        final=final))
                    self.evidence.write('manifest.json', suite)
                    print('ATTEMPT', label, 'PASS' if success else 'FAIL', reason, mechanics['acquisitions'],
                          (round(final['x'],1), round(final['y'],1)), flush=True)
                group = [a for a in attempts if a['device']==device]
                if not group[0]['success'] or sum(a['success'] for a in group[1:]) < 2:
                    failures.append(name+' '+device)
        worst = max([d['max_gap'] for d in nominal.values()] or [0])
        self.evidence.write('density.json', dict(rule='no nominal-trace gap > 180 ticks without an acquisition, bounce or mover contact',
            counted=['acquisition','bounce','contact with '+'/'.join(self.MOVERS)+' (carriage by its underside y -3120, ny 1)'],
            window='each nominal encounter trace from tick 0 to the first tick landed (|speedY|<.001) inside its expected exit box',
            traces=nominal, max_gap=worst, passed=worst <= 180,
            full_route='test_02 adds the S03 traversal from the real S02 exit rest segmented per encounter'))
        self.assertEqual(failures, [])
        self.assertEqual(len(nominal), 8)
        self.assertLessEqual(worst, 180, {k: v['max_gap'] for k, v in nominal.items()})
        self.negative_control(states)
        print('PASS S03 v2 four encounters: both viewports nominal + >=2/4 variants; density max gap', worst,
              '; mistimed-lift negative control fails the exit')

    def negative_control(self, states):
        from grapple_over_verify import hashes, check_s03_mechanics
        # Named mistiming: S03-02 span lift released after 50 ticks instead of 65, same start and physics.
        name, offset = 'S03-02', self.STARTS['S03-02']
        m = self.make_input([(t-offset, e, x, y) for t, e, x, y in self.FALL[2:4]], 400, self.BOXES[name], snapshot=states[name])
        trace, success, reason = self.run_attempt(m, 'clips/negative', True)
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
        mechanics = check_s03_mechanics(name, trace, required=False)
        rest = next(t for t, p in enumerate(players) if self.at_rest(p, 'S02-landing'))
        self.assertTrue(all(self.at_rest(p, 'S02-landing') for p in players[rest:]))
        self.evidence.write('negative-control.json', dict(name='mistimed S03-02: S03-lift released at hold 50 instead of 65',
            input='clips/negative/input.json.gz', trace='clips/negative/trace.json', failed_intended_exit=not success,
            reason=reason, intended_exit=self.BOXES[name], unchanged_physics=True, source_hashes=hashes(),
            start=f'starts/trace.json tick {offset} (same as the S03-02 attempts)', mechanic_events=mechanics,
            max_tick_displacement=step, final_player=players[-1], s02_landing_rest=dict(tick=rest, player=players[rest]),
            scope='Same start, physics and lift aim; the early release rebounds off the span buffer back over the span and falls '
                  'physically through S03-fall-drag onto the S02 landing deck, never reaching the S03 far deck.'))
        self.assertFalse(success); self.assertIn('expected exit mismatch', reason)
        self.assertEqual(mechanics['acquisitions'], ['S03-lift'])
        self.assertIn(self.BUFFER, [b['element'] for b in mechanics['bounces']])
        self.assertLess(step, 60)

    def test_02_full_traversal(self):
        """The S03 nominal run from the real S02 exit rest (starts/trace.json), segmented per encounter."""
        from grapple_over_verify import check_s03_mechanics
        self.starts()
        trace = type(self).start_trace
        mechanics = check_s03_mechanics('S03-01', trace)
        self.assertEqual(mechanics['acquisitions'], ['S03-carriage','S03-lift','S03-crest-hook','S03-ledge','S03-trolley','S03-trolley'])
        self.assertIn(self.BUFFER, [b['element'] for b in mechanics['bounces']])
        self.assertIn('S03-ledge', mechanics['airborne_acquisitions'])
        players = [r['state']['simulation']['player'] for r in trace['snapshots']]
        self.assertTrue(self.at_rest(players[-1], 'S03-04'), players[-1])
        segments = {}
        for name, start_tick in self.PRESSES.items():
            window = dict(trace, events=[dict(e, tick=e['tick']-start_tick) for e in trace['events'] if e['tick'] >= start_tick],
                          snapshots=[dict(r, tick=r['tick']-start_tick) for r in trace['snapshots'][start_tick:]])
            d = self.density(window, self.landed(name), 'starts/trace.json')
            d.update(start_tick=start_tick, exit_tick_absolute=start_tick+d['exit_tick'])
            segments[name] = d
        presses = self.PRESSES
        idle = [dict(after=a, rest_from=segments[a]['exit_tick_absolute'], next_press=presses[b], player=players[presses[b]])
                for a, b in zip(list(presses)[:-1], list(presses)[1:])]
        for row in idle:
            self.assertTrue(abs(row['player']['speedX']) < .001 and abs(row['player']['speedY']) < .001, row)
        density = json.loads(self.evidence.path('density.json').read_text()) if self.evidence.path('density.json').exists() else {}
        density['full_route'] = dict(trace='starts/trace.json', proof_kind='isolated: one labeled placement at the real S02 exit rest; '
            'real mouse input (TASK-512 S03 nominal inputs)', segments=segments, idle_rests=idle,
            max_gap=max(d['max_gap'] for d in segments.values()))
        self.evidence.write('density.json', density)
        self.assertLessEqual(density['full_route']['max_gap'], 180, {k: v['max_gap'] for k, v in segments.items()})
        print('PASS full S03: S02 exit rest to the S03 exit pad; acquisitions', mechanics['acquisitions'],
              '; per-encounter max gaps', {k: v['max_gap'] for k, v in segments.items()})

    def test_03_drag_zone_fall_clips(self):
        from grapple_over_verify import check_s03_mechanics
        states = self.starts()
        offset = self.STARTS['S03-02']
        plan = [(t-offset, e, x, y) for t, e, x, y in self.FALL[2:]]
        for device in ('desktop','touch'):
            m = self.make_input(plan, plan[2][0]+400, self.BOXES['S02-ledge'], device, states['S03-02'])
            prefix = 'clips/fall-'+device
            trace, success, reason = self.run_attempt(m, prefix, True)
            self.assertTrue(success, reason)
            players = [r['state']['simulation']['player'] for r in trace['snapshots']]
            step = max(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a, b in zip(players, players[1:]))
            press = plan[2][0]
            zone = [t for t in self.brake_ticks(players, self.DRAG) if t < press]
            deck = [e['tick'] for e in trace['events'] if e['type']=='contact' and (e.get('contact') or {}).get('y') == -2100
                    and (e.get('contact') or {}).get('ny') == -1 and e['tick'] < press]
            land = deck[0]
            rest = next(t for t in range(land, press) if self.at_rest(players[t], 'S02-landing'))
            self.assertTrue(all(self.at_rest(players[t], 'S02-landing') for t in range(rest, press)))
            base = [e['tick'] for e in trace['events'] if e['type']=='contact' and (e.get('contact') or {}).get('y') == 120]
            mechanics = check_s03_mechanics('S03-02', trace, required=False)
            targets = self.targets(trace, m['metadata']['viewport'])
            self.assertTrue(zone and all(t['in_viewport'] and not t['under_hud'] for t in targets), targets)
            self.assertEqual(base, [])
            self.assertEqual(mechanics['acquisitions'], ['S03-lift','S02-crest-hook','S02-ledge'])
            self.assertIn(self.BUFFER, [b['element'] for b in mechanics['bounces']])
            self.assertLess(step, 60)
            ratios = [players[t+1]['speedX']/players[t]['speedX'] for t in zone[:-1] if players[t]['speedX']]
            rejoined = next(t for t in range(press, len(players)) if self.at_rest(players[t], 'S02-ledge'))
            self.evidence.write(prefix+'/result.json', dict(passed=True, device=device, viewport=m['metadata']['viewport'],
                scenario='mistimed S03-02 lift release (hold 50, nominal 65) from the S03-02 start state; buffer rebound; physical fall '
                         'through S03-fall-drag onto the S02 landing deck; input-only S02-03 rejoin onto the S02 ledge',
                drag_zone=self.DRAG, drag_zone_ticks=[zone[0], zone[-1]], vx_entering=players[zone[0]-1]['speedX'],
                vx_leaving=players[zone[-1]+1]['speedX'], per_tick_vx_ratio_count=len(ratios),
                per_tick_vx_ratio_min_max=[min(ratios), max(ratios)] if ratios else None,
                s02_landing_first_contact_tick=land, s02_landing_rest=dict(tick=rest, player=players[rest]), base_contact=False,
                rejoin=dict(press_tick=press, acquisitions=mechanics['acquisitions'][1:], ledge_rest_tick=rejoined, player=players[rejoined]),
                max_tick_displacement=step, press_targets=targets, mechanic_events=mechanics, final=players[-1]))
            print('PASS fall '+device+': drag column ticks', zone[0], '-', zone[-1], '; S02 landing rest tick', rest,
                  '; S02-03 rejoin to the S02 ledge tick', rejoined, '; no relocation')


class Task514Tests(unittest.TestCase):
    """Layout-v2 Deflector Works S04-01/02 from the real v2 S03 exit rest, with real input."""
    task_id = 'TASK-514'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    report = Task505Tests.report
    compact = Task506Tests.compact
    replay = Task506Tests.replay
    filmstrip = Task507Tests.filmstrip
    bounds = Task509Tests.bounds
    at_rest = Task511Tests.at_rest
    events = Task511Tests.events
    test_04_source_hashes = Task465Tests.test_03_source_hashes
    # One base-start run: the S01+S02 v2 routes (TASK-511), then the TASK-513 S03 nominal from tick 2120.
    BASE_ROUTE = Task511Tests.BASE_ROUTE+[(t+2120, e, x, y) for t, e, x, y in Task513Tests.NOMINAL]
    BASE_TICKS = 2120+1150
    # S04-01: the blue carriage pull (held 120) swings the player up over the carriage; on release it
    # drops onto the carriage top, rides it left and falls onto the pier against its low left lip.
    # S04-02: the lift press at 440 (one 240-tick mover period after the mirrored S03-02 press at 200).
    CARRIAGE, LIFT = (4466,-4225), (3823,-4520)
    S04_01 = [(5,'mousedown',*CARRIAGE),(125,'mouseup',*CARRIAGE)]
    S04_02 = [(440,'mousedown',*LIFT),(505,'mouseup',*LIFT)]
    MOVERS = ('S04-carriage','S04-lift')
    PRESS = 'S04-flat-press'
    BAND, RANGE = (459, 486), 540
    REST = Task511Tests.REST
    BOXES = {'S02-04':Task511Tests.BOXES['S02-04'],
             'S03-04':dict(x=[4600,4710],y=[-3841,-3840],**REST),
             'S04-01':dict(x=[4146,4246],y=[-4161,-4160],**REST),
             'S04-02':dict(x=[3226,3356],y=[-4411,-4410],**REST)}
    S03_ACQUISITIONS = ['S03-carriage','S03-lift','S03-crest-hook','S03-ledge','S03-trolley','S03-trolley']

    def reach(self, players, mech, press_tick, element):
        return Task508Tests.reach(self, players, mech, press_tick, element)

    def s03_exit(self):
        """Real S03 exit rest pose: one base-start real-input run of the v2 S01, S02 and S03 routes (no placement)."""
        from grapple_over_verify import metadata, execute, check_trace
        if hasattr(type(self), 'start'): return type(self).start
        m = dict(metadata=metadata('base-start'), ticks=self.BASE_TICKS, expected_exit=self.BOXES['S03-04'],
            inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.BASE_ROUTE],
            required_events=['acquisition','release'])
        m['metadata']['compact_contacts'] = True
        setup = execute(m, self.browser, self.url, str(self.evidence.path('encounters/S03-exit-start')))
        check_trace(m, setup)
        self.assertEqual(setup['metadata']['setupOnlySpawns'], [])
        players = [s['state']['simulation']['player'] for s in setup['snapshots']]
        self.assertEqual((players[0]['x'], players[0]['y']), (2160, 0))
        acquired = [e['after']['rope'][0]['id'] for e in setup['events'] if e['type']=='acquisition']
        self.assertEqual(acquired[:10], ['S01-hoist','S01-lift','S01-crane-hook','S01-jib-hook','S01-boom-hook',
            'S02-shuttle','S02-lift','S02-crest-hook','S02-ledge','S02-trolley'])
        self.assertEqual(acquired[10:], self.S03_ACQUISITIONS)
        self.assertTrue(self.at_rest(players[2120], 'S02-04'), players[2120])
        self.evidence.write('encounters/S03-exit-start/trace.json', self.compact(setup))
        rest = next(t for t in range(3000, self.BASE_TICKS+1) if self.at_rest(players[t], 'S03-04'))
        self.assertTrue(all(self.at_rest(p, 'S03-04') for p in players[rest:]))
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (4675.2, -3840.8))
        start = setup['snapshots'][-1]['state']['simulation']
        type(self).start = start
        type(self).start_proof = dict(kind='base-start S01+S02+S03 v2 routes (TASK-507 S01, TASK-510 S02 nominal from tick 1120, '
            'TASK-513 S03 nominal from tick 2120), real mouse input, no placement', inputs=m['inputs'], acquisitions=acquired,
            s02_exit_rest_at_tick_2120=players[2120], s03_exit_rest_from_tick=rest, final_tick=self.BASE_TICKS, player=start['player'],
            snapshot_sha256=setup['snapshots'][-1]['sha256'], trace='encounters/S03-exit-start/trace.json')
        self.evidence.write('encounters/S03-exit-start/result.json', dict(passed=True, **type(self).start_proof))
        return start

    def test_01_geometry_and_rules(self):
        r = self.report()
        m = r['manifest']; elements = m['geometry']['elements']
        byid = {e['id']:e for e in elements}
        s04 = m['sections'][3]
        self.assertEqual(s04['designVersion'], 2); self.assertIn(s04['status'], ('partial','built'))
        enc = m['encounters'][12:16]
        self.assertEqual([e['status'] for e in enc[:2]], ['built','built'])
        self.assertEqual(enc[1]['start']['from'], 'S04-01')
        self.assertEqual([c['status'] for c in m['connectors'][12:14]], ['built','built'])
        self.assertEqual((m['connectors'][12]['from'], m['connectors'][12]['to']), ('S03-04','S04-01'))
        self.assertEqual(r['runtime']['elements'], elements)
        colliders = [e for e in elements if e['role'] != 'drag']
        self.assertEqual(len(r['colliders']), len(colliders))
        for actual, expected in zip(r['colliders'], colliders):
            self.assertEqual(actual, {k:expected[k] for k in ('id','x','y','points','role')})
        own = [e for e in elements if e['id'].startswith('S04-')]
        movers = {v['element']:v for v in m['geometry']['movers'] if v['element'].startswith('S04-')}
        self.assertTrue(set(self.MOVERS) <= set(movers))
        exceptions = {x['element']:x for x in s04['solidExceptions']}
        roles = {}
        for e in own:
            roles[e['id']] = 'blue mover' if e['id'] in movers else 'green bounce' if e['role'] == 'bounce' else \
                'drag zone' if e['role'] == 'drag' else 'solid '+exceptions[e['id']]['kind']+' exception'
            if e['role'] == 'solid' and e['id'] not in movers:
                self.assertIn(e['id'], exceptions)
                if exceptions[e['id']]['kind'] == 'rest-pad':
                    self.assertLessEqual(self.bounds(e)[1]-self.bounds(e)[0], 200, e['id'])
        self.assertEqual((roles['S04-carriage'], roles['S04-lift'], roles[self.PRESS]), ('blue mover','blue mover','green bounce'))
        # The v1 Deflector Works geometry and the legacy S03-exit deck are gone.
        removed = ['S03-exit','S04-rest','S04-angled-chute','S04-transfer-ledge','S04-catch-basin','S04-lower-stair',
            'S04-combination-press','S04-combination-rest','S04-double-left','S04-double-right','S04-brake-anchor','S04-double-landing']
        self.assertFalse(set(removed) & set(byid))
        e1, e2 = enc[0], enc[1]
        self.assertEqual(e1['start'], {'x':4675.2,'y':-3840.8,'from':'S03-04'})
        self.assertEqual(e2['start'], {'from':'S04-01','x':4156.8,'y':-4160.8})
        self.assertEqual(m['encounters'][11]['exit'], {'left':4600,'right':4710,'top':-3850,'bottom':-3830})
        self.assertIn('S04-carriage', e1['elements']); self.assertIn('S04-pier', e1['elements'])
        self.assertIn('S04-lift', e2['elements']); self.assertIn(self.PRESS, e2['elements'])
        # Distinct roles: S04-01 rides a blue carriage with no green surface; S04-02 reflects off the flat green press.
        self.assertFalse(any(roles[x] == 'green bounce' for x in e1['elements'] if x in roles))
        v2 = next(s for s in r['report']['sections'] if s['id'] == 'S04')
        self.assertEqual((v2['designVersion'], v2['passed'], v2['errors'], v2['range']), (2, True, [], self.RANGE))
        for name in ('bounceDefault','moverCoverage','direction','gapBand','fallDrag'):
            self.assertTrue(v2['rules'][name]['passed'], name)
        direction = v2['rules']['direction']['measured']
        self.assertEqual((direction['required'], direction['actual']), ('left', 'left'))
        mover_encounters = v2['rules']['moverCoverage']['measured']['encounters']
        self.assertEqual(mover_encounters[:2], ['S04-01','S04-02'])
        gaps = v2['rules']['gapBand']['measured']['gaps']
        self.assertEqual([g['id'] for g in gaps][:2], ['S04-01-carriage','S04-02-lift'])
        gaps = gaps[:2]
        for g in gaps:
            self.assertTrue(self.BAND[0] <= g['distance'] <= self.BAND[1], g)
        self.assertEqual(v2['rules']['gapBand']['measured']['target'], list(self.BAND))
        self.assertEqual(r['report']['v2'][:4], ['S01','S02','S03','S04'])
        self.assertFalse(r['report']['failed'])
        # Travelling left: every S04-01/02 route element sits left of the S03 exit pad's right lip,
        # and the route keeps clear of the S03-04 trolley arcs (x >= 4282 up to y -4185, TASK-513 attempts).
        route = [e for e in own if e['id'] in set(e1['elements']+e2['elements'])]
        self.assertTrue(all(self.bounds(e)[1] <= 4750 for e in route))
        self.assertLess(self.bounds(byid['S04-press-deck'])[0], self.bounds(byid['S04-pier'])[0])
        self.assertLessEqual(self.bounds(byid['S04-pier'])[1], 4250)
        self.evidence.write('rules.json', dict(self.proof, validator='layoutV2Report (TASK-504)',
            section=v2, all_applicable_rules_passed=True, encounters=['S04-01','S04-02'], planned=['S04-03','S04-04'],
            direction=direction, mover_encounters=mover_encounters,
            gap_targets_reference='artifacts/TASK-503/calibration.json gap_metric (459-486 at 540)',
            measured_gap_distances={g['id']:g['distance'] for g in gaps},
            fall_lines='none declared yet (S04-03/04 and the S04 fall recovery are planned); rule passes over an empty list',
            other_v2_sections={s['id']:s['passed'] for s in r['report']['sections'] if not s['legacy']}))
        self.evidence.write('geometry.json', dict(self.proof, manifest_section=s04, encounters=enc[:2], planned_encounters=enc[2:],
            connectors=m['connectors'][12:17], recovery=m['recoveries'][3], elements=own,
            movers=list(movers.values()), roles=roles,
            encounter_roles={'S04-01':'blue carriage (x mover) pulled up-left from the S03 exit pad; the long pull swings the player up '
                                       'over the carriage, the release drops it onto the moving carriage top (mover contact), it rides left '
                                       'and falls onto the narrow pier pad against its low left lip',
                             'S04-02':'blue lift (y mover) pulled up-left from the pier; release across the open works floor, landing '
                                       'beyond the 540 grapnel range; the flat green press face reflects the arc onto the press deck against its tall right lip'},
            runtime_matches_manifest=True, long_walking_floors=False,
            removed_v1_elements=removed,
            legacy_kept={'S04-upper-step':'v1 Cable Galleries recovery step (recoveries[4] opening) until S04-03/04 are rebuilt',
                         'S04-exit':'v1 Cable Galleries entrance deck; v1 S05-01 start (4530,-6490.8) unchanged; connector S05-entrance '
                                    'is planned until S04-04 is rebuilt'}))
        self.overview(elements, own, movers, roles, s04, enc[:2], gaps)
        print('PASS geometry: S04 designVersion 2 partial (S04-01/02 built, 03/04 planned); roles', sorted(set(roles.values())),
              '; validator rules all pass; direction left; gaps', [round(g['distance'],1) for g in gaps], '; overview.png')

    def overview(self, elements, own, movers, roles, s04, enc, gaps):
        colors = {'blue mover':'#2f86ff','green bounce':'#3ddc84'}
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="3000 -4800 1800 1125" style="background:#111827">']
        for e in elements:
            if not e['id'].startswith('S03-'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            fill = 'rgba(160,160,160,.18)' if e['role'] == 'drag' else '#374151'
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#6b7280" stroke-width="2"/>')
            if e['role'] != 'drag':
                parts.append(f'<text x="{e["x"]}" y="{e["y"]+40}" fill="#9ca3af" font-size="20">{e["id"]}</text>')
        for e in own:
            if e['id'] in ('S04-exit','S04-upper-step'): continue
            pts = ' '.join(f'{e["x"]+p["x"]},{e["y"]+p["y"]}' for p in e['points'])
            parts.append(f'<polygon points="{pts}" fill="{colors.get(roles[e["id"]], "#a3a3a3")}" stroke="white" stroke-width="2"/>')
            label_y = e['y']-30 if e['id'] in movers or e['id'] == self.PRESS else e['y']+60
            parts.append(f'<text x="{e["x"]}" y="{label_y}" fill="white" font-size="24">{e["id"]}</text>')
        for v in movers.values():
            e = next(x for x in own if x['id'] == v['element'])
            x0, y0 = (v['min'], e['y']-10) if v['axis'] == 'x' else (e['x']+130, v['min'])
            x1, y1 = (v['max']+120, e['y']-10) if v['axis'] == 'x' else (e['x']+130, v['max']+30)
            parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="#2f86ff" stroke-width="5" stroke-dasharray="10,6"/>')
        for g in s04['gaps']:
            parts.append(f'<line x1="{g["from"]["x"]}" y1="{g["from"]["y"]}" x2="{g["to"]["x"]}" y2="{g["to"]["y"]}" stroke="#facc15" stroke-width="4" stroke-dasharray="8,6"/>')
        for e in enc:
            b = e['exit']
            parts.append(f'<rect x="{b["left"]}" y="{b["top"]-20}" width="{b["right"]-b["left"]}" height="{b["bottom"]-b["top"]+20}" fill="none" stroke="#f472b6" stroke-width="4"/>')
        parts.append(f'<circle cx="4156.8" cy="-4160.8" r="{self.RANGE}" fill="none" stroke="#fb7185" stroke-width="2" stroke-dasharray="6,8"/>')
        for x, y in ((4675.2,-3840.8),(4156.8,-4160.8),(3345.2,-4410.8)):
            parts.append(f'<circle cx="{x}" cy="{y}" r="11" fill="#ff7a1a"/>')
        for i, t in enumerate(['S04 Deflector Works layout v2 (direction left): S03 exit-pad rest (orange) -> S04-01 blue carriage ride -> pier',
                '-> S04-02 blue lift -> long release across the works floor -> flat green press reflection -> press deck',
                'yellow = gaps %s of 540; pink = exit boxes; red circle = 540 range from the pier; grey = S03 v2' % '/'.join(str(round(g['distance'],1)) for g in gaps)]):
            parts.append(f'<text x="3020" y="{-4760+i*36}" fill="#67e8f9" font-size="26">{t}</text>')
        parts.append('</svg>')
        page = self.browser.new_page(viewport=dict(width=1280, height=800)); self.addCleanup(page.close)
        page.set_content('<style>body{margin:0}</style>'+''.join(parts))
        page.screenshot(path=str(self.evidence.path('overview.png')))

    def isolated(self, name, plan, ticks, box):
        start = self.s03_exit()
        trace, mech, players, result = self.replay(name, plan, ticks, self.BOXES[box], kind='isolated', snapshot=start)
        self.filmstrip('encounters/'+name, VIEWPORT)
        self.assertEqual((players[0]['x'], players[0]['y']), (start['player']['x'], start['player']['y']))
        self.assertTrue(self.at_rest(players[0], 'S03-04'), players[0])
        result.update(proof_kind='isolated: one labeled initial placement = restoreClimbState of the real S03 exit rest pose '
                      'from one base-start real-input S01+S02+S03 run; production input/physics thereafter; not a continuous-completion claim',
            not_continuous_completion_claim=True, initial_placement=dict(labeled=True, source=self.start_proof),
            mechanic_events=[dict(tick=x['tick'], type=x['type'], element=x['element'], mover=x['element'] in self.MOVERS,
                player=x['player']) for x in mech])
        return trace, mech, players, result

    def s04_01_checks(self, trace, mech, players):
        carriage = self.reach(players, mech, 5, 'S04-carriage')
        anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']=='S04-carriage']
        self.assertGreater(abs(anchors[-1]['x']-anchors[0]['x']), 1)
        # After the release the player lands on the moving carriage top and rides it left. Contacts
        # carry no element id; the carriage is the only surface with its top at y -4285, and the
        # contact lies inside its x travel (4296..4536).
        top = [dict(tick=e['tick'], type='mover contact', element='S04-carriage', contact=e['contact'],
                    player=e['after']['simulation']['player']) for e in trace['events']
               if e['type']=='contact' and e['tick'] > 125 and e['contact']['y'] == -4285 and e['contact']['ny'] == -1]
        self.assertTrue(top)
        self.assertTrue(all(4296 <= x['contact']['x'] <= 4536 for x in top), top[0])
        ride = [t for t in range(125, 300) if abs(players[t]['y']-(-4285-10.8)) < .01]
        self.assertGreater(len(ride), 20)
        self.assertLess(players[ride[-1]]['x'], players[ride[0]]['x'])
        landed = next(t for t in range(125, 440) if self.at_rest(players[t], 'S04-01'))
        self.assertTrue(all(self.at_rest(p, 'S04-01') for p in players[landed:440]))
        return carriage, dict(dx=anchors[-1]['x']-anchors[0]['x'], ticks=len(anchors)), \
            dict(first_contact_tick=top[0]['tick'], last_contact_tick=top[-1]['tick'], contacts=len(top), ride_ticks=[ride[0], ride[-1]],
                 ride_x=[players[ride[0]]['x'], players[ride[-1]]['x']], ride_y=-4295.8, first_contact=top[0]), landed

    def test_02_s04_01_nominal(self):
        trace, mech, players, result = self.isolated('S04-01', self.S04_01, 440, 'S04-01')
        self.assertEqual(self.events(mech), [('acquisition','S04-carriage'),('release','S04-carriage')])
        carriage, travel, ride, landed = self.s04_01_checks(trace, mech, players)
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (4156.8, -4160.8))
        self.assertTrue(all(p['x'] <= 4750 for p in players))
        result.update(encounter='S04-01', carriage_reach=carriage, carriage_anchor_travel_while_attached=travel,
            carriage_top_ride=ride, pier_rest_from_tick=landed, pier_rest=players[landed])
        result['mechanic_events'] = sorted(result['mechanic_events']+[ride['first_contact']], key=lambda x: x['tick'])
        self.evidence.write('encounters/S04-01/result.json', result)
        print('PASS S04-01: from the real S03 exit rest; blue carriage acquisition', round(carriage['distance'],1),
              '; carriage top contact tick', ride['first_contact_tick'], 'ride ticks', ride['ride_ticks'], '; pier rest from tick', landed, 'at',
              (round(players[-1]['x'],1), round(players[-1]['y'],1)), '; identical replay; trusted input')

    def test_03_s04_02_nominal(self):
        trace, mech, players, result = self.isolated('S04-02', self.S04_01+self.S04_02, 760, 'S04-02')
        self.assertEqual(self.events(mech), [('acquisition','S04-carriage'),('release','S04-carriage'),
            ('acquisition','S04-lift'),('release','S04-lift')])
        ride = self.s04_01_checks(trace, mech, players)[2]
        result['mechanic_events'] = sorted(result['mechanic_events']+[ride['first_contact']], key=lambda x: x['tick'])
        self.assertTrue(self.at_rest(players[439], 'S04-01'), players[439])
        launch = players[440]
        self.assertEqual((round(launch['x'],1), round(launch['y'],1)), (4156.8, -4160.8))
        lift = self.reach(players, mech, 440, 'S04-lift')
        anchors = [s['state']['rope'][0] for s in trace['snapshots'] if s['state']['rope'] and s['state']['rope'][0]['id']=='S04-lift']
        self.assertGreater(abs(anchors[-1]['y']-anchors[0]['y']), 1)
        bounce = next(e for e in trace['events'] if e['type']=='bounce' and e['contact']['elementId']==self.PRESS)
        before, after = bounce['before']['simulation']['player'], bounce['after']['simulation']['player']
        self.assertLess(before['speedX'], 0); self.assertGreater(after['speedX'], 0)
        far = lambda p: ((p['x']-launch['x'])**2 + (p['y']-launch['y'])**2) ** .5
        self.assertGreater(far(before), self.RANGE)
        landed = next(t for t in range(505, 761) if self.at_rest(players[t], 'S04-02'))
        self.assertTrue(all(self.at_rest(p, 'S04-02') for p in players[landed:]))
        self.assertGreater(far(players[landed]), self.RANGE)
        self.assertEqual((round(players[-1]['x'],1), round(players[-1]['y'],1)), (3345.2, -4410.8))
        rules = json.loads(self.evidence.path('rules.json').read_text()) if self.evidence.path('rules.json').exists() else None
        carriage = self.reach(players, mech, 5, 'S04-carriage')
        if rules:
            rules['trace_measured_reach'] = {'S04-carriage':carriage, 'S04-lift':lift}
            self.evidence.write('rules.json', rules)
        result.update(encounter='S04-02', s04_01_exit_at_tick_439=players[439], lift_reach=lift,
            lift_anchor_travel_while_attached=dict(dy=anchors[-1]['y']-anchors[0]['y'], ticks=len(anchors)),
            press_bounce=dict(tick=bounce['tick'], before=before, after=after, distance_from_launch=far(before)),
            span=dict(launch=dict(x=launch['x'], y=launch['y']), range=self.RANGE, landing_distance_from_launch=far(players[landed]),
                beyond_range=True, release_tick=505, press_bounce_tick=bounce['tick']),
            press_deck_rest_from_tick=landed, press_deck_rest=players[landed])
        self.evidence.write('encounters/S04-02/result.json', result)
        print('PASS S04-02: from the S04-01 pier rest; blue lift acquisition', round(lift['distance'],1),
              '; flat green press reflection tick', bounce['tick'], 'at', round(far(before),1), 'from launch; press-deck rest from tick', landed,
              round(far(players[landed]),1), 'from launch (> 540); identical replay; trusted input')


TASK544_RANGES = {1080: False, 1620: True}


class Task544Tests(unittest.TestCase):
    """Recalibrate the TASK-503 families at 1080/1620; freeze the v3 gaps, extent and density cap."""
    import test_grapple_over_physics as physics
    attempt = physics.Task503Tests.attempt
    drag_pairs = physics.Task503Tests.drag_pairs
    judge = physics.Task503Tests.judge
    envelope = physics.Task503Tests.envelope
    del physics
    results, reach, flight = {}, {}, {}

    @classmethod
    def setUpClass(cls):
        import test_grapple_over_tools as task463
        cls.task463 = task463
        cls.evidence = EvidenceWriter('TASK-544')
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

    def test_01_families_at_both_ranges(self):
        import test_grapple_over_physics as physics
        page = self.open()
        constants = page.evaluate('''() => ({gravity:GRAVITY,pull:grappleSpeed,
            throwSpeed:grapnelSpeed,cyclesPerTick,physicsStepMs,radius:ninja.radius,
            range:MODE_DEFINITIONS.grapple_over.acquisitionRadius,
            upgradedRange:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius,
            dragDamping:DRAG_ZONE_HORIZONTAL_DAMPING,scale:scale.grapple_over})''')
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())['modes']['classic']
        for key in ('gravity', 'pull', 'throwSpeed', 'cyclesPerTick', 'physicsStepMs'):
            self.assertEqual(constants[key], baseline['constants'][key])
        self.assertEqual((constants['range'], constants['upgradedRange'], constants['scale']), (1080, 1620, 0.375))
        v2 = json.loads((ROOT / 'artifacts/TASK-503/calibration.json').read_text())['measured_envelopes']['540']
        out = {}
        for rng, upgraded in TASK544_RANGES.items():
            out[rng] = {}
            for family in physics.TASK503_FAMILIES:
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
                          'landing_tick=%d' % r['landing_contact']['tick'])
                    self.assertEqual(r['success'], not r['negative'], (rng, family, r['dt'], r['aim']))
                successes = [r for r in runs if r['success']]
                self.assertEqual(len(successes), 5)
                envelope = self.envelope(family, successes)
                envelope['differs_from_v2_540_envelope'] = sorted(k for k in v2[family] if envelope[k] != v2[family][k])
                print('PASS', rng, family, ': nominal + 4 variants; negative rejected; landing ticks',
                      envelope['landing_ticks'], 'v2 540 landing ticks', v2[family]['landing_ticks'],
                      'keys differing from TASK-503 540 envelope', envelope['differs_from_v2_540_envelope'])
                out[rng][family] = dict(runs=runs, envelope=envelope)
        self.__class__.results = dict(constants=constants, families=out)

    def test_02_gap_metric_reach(self):
        """Bisect the longest acquiring rope-to-anchor distance with trusted mouse input at 1080/1620."""
        page = self.open()
        trial = '''([d, upgraded]) => {
            const rect=(id,x,y,w,h)=>({id,x,y,role:'solid',points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
            const level=structuredClone(GRAPPLE_OVER_LEVEL);
            level.movers=[];
            level.elements=[rect('floor',-2000,1000,8000,60),rect('post',700+d,700,40,300)];
            level.encounters[0].elements=level.elements.map(e=>e.id);
            GRAPPLE_OVER_TEST.spawn({level,player:{x:700,y:1000-ninja.radius,speedX:0,speedY:0},
                camera:{x:700+d/2-innerWidth/2/scale.grapple_over,y:1000-innerHeight/2/scale.grapple_over}});
            floors[0].rangeUpgraded=upgraded;
            return GRAPPLE_OVER_TEST.client({x:700+d+20,y:1000-ninja.radius});
        }'''

        def shoot(d, upgraded):
            page.mouse.up()
            page.evaluate('GRAPPLE_OVER_TEST.attempts.length=0')
            page.evaluate("GRAPPLE_OVER_TEST.begin('reach')")
            p = page.evaluate(trial, [d, upgraded])
            self.assertTrue(0 <= p['x'] <= 1280 and 0 <= p['y'] <= 720, (d, p))
            page.mouse.move(p['x'], p['y'])
            page.mouse.down()
            page.evaluate('() => {for(let i=0;i<90 && !grapnel.isGrappled();i++) GRAPPLE_OVER_TEST.step(1)}')
            r = page.evaluate('''() => ({grappled:grapnel.isGrappled(),range:grappleOverAcquisitionRadius(),
                target:grapnel.isGrappled()?grapnel.pos[0][2].id:null,
                rope:grapnel.isGrappled()?Math.hypot(grapnel.pos[0][0]-ninja.x,grapnel.pos[0][1]-ninja.y):null})''')
            page.mouse.up()
            page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
            return r
        frozen = page.evaluate('LAYOUT_V3_GAP_TARGETS')
        v2 = page.evaluate('LAYOUT_V2_GAP_TARGETS')
        reach = {}
        for rng, upgraded in TASK544_RANGES.items():
            lo, hi = rng - 300.0, rng + 200.0
            first = shoot(lo, upgraded)
            self.assertTrue(first['grappled'])
            self.assertFalse(shoot(hi, upgraded)['grappled'])
            best, steps = first, 0
            while hi - lo > 0.05:
                mid = (lo + hi) / 2
                r = shoot(mid, upgraded)
                self.assertEqual(r['range'], rng)
                steps += 1
                if r['grappled']:
                    self.assertEqual(r['target'], 'post')
                    lo, best = mid, r
                else:
                    hi = mid
            measured = best['rope']
            self.assertAlmostEqual(measured, rng, delta=0.5)
            # Frozen v3 band: twice the v2 band, which must sit inside 85-90% of the measured reach
            # (upper end judged against the bisection bracket: true reach lies within measured + 0.05).
            v2_band = v2[str(rng // 2)]
            gap = [2 * v2_band[0], 2 * v2_band[1]]
            self.assertEqual(frozen[str(rng)], gap)
            fraction = [gap[0] / measured, gap[1] / measured]
            self.assertTrue(0.85 * measured <= gap[0] < gap[1] <= 0.90 * (measured + 0.05), fraction)
            band = [shoot(d, upgraded) for d in gap]
            self.assertTrue(all(b['grappled'] and b['target'] == 'post' for b in band))
            self.assertFalse(shoot(hi + 1, upgraded)['grappled'])
            reach[rng] = dict(measured_reach=measured, last_acquiring_post_face_distance=lo,
                first_missing_post_face_distance=hi, bisection_steps=steps, gap_targets=gap,
                gap_targets_as_fraction=fraction, v2_gap_targets=v2_band,
                v3_over_v2_gap_ratio=[gap[0] / v2_band[0], gap[1] / v2_band[1]],
                target_band_acquires=[dict(distance=d, rope=b['rope']) for d, b in zip(gap, band)])
            print('PASS reach %d: measured reach %.3f; v3 gap targets %s acquire (%.2f%%-%.2f%% of reach); v3/v2 %s'
                  % (rng, measured, gap, 100 * fraction[0], 100 * fraction[1], reach[rng]['v3_over_v2_gap_ratio']))
        self.__class__.reach = reach

    def test_03_flight_time_and_density_cap(self):
        """Free fall from rest across a v2 vs a v3 band height, stepped by the production physics."""
        page = self.open()
        r = page.evaluate('''() => {
            const fall = h => {
                GRAPPLE_OVER_TEST.attempts.length=0;
                GRAPPLE_OVER_TEST.begin('flight');
                const rect=(id,x,y,w,h)=>({id,x,y,role:'solid',points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
                const level=structuredClone(GRAPPLE_OVER_LEVEL);
                level.movers=[];
                level.elements=[rect('floor',-2000,h,8000,60)];
                level.encounters[0].elements=['floor'];
                GRAPPLE_OVER_TEST.spawn({level,player:{x:700,y:-ninja.radius,speedX:0,speedY:0},camera:{x:0,y:-300}});
                let t=0;
                while(t<2000 && !(ninja.speedY===0 && Math.abs(ninja.y-(h-ninja.radius))<1e-5)) {GRAPPLE_OVER_TEST.step(1);t++}
                GRAPPLE_OVER_TEST.finish('measured');
                return {height:h,ticks:t,landed_y:ninja.y,speedY:ninja.speedY};
            };
            const out={v2:fall(3*540), v3:fall(LAYOUT_V3_EXTENT.bandHeight)};
            return Object.assign(out,{v2Cap:LAYOUT_V2_DENSITY_CAP_TICKS,v3Cap:LAYOUT_V3_DENSITY_CAP_TICKS,
                extent:LAYOUT_V3_EXTENT,v2Extent:{ascent:GRAPPLE_OVER_MOUNTAIN.ascent,
                horizontalEnvelope:GRAPPLE_OVER_MOUNTAIN.horizontalEnvelope,bandHeight:3*540,
                encountersPerSection:GRAPPLE_OVER_MOUNTAIN.encounters.length/GRAPPLE_OVER_MOUNTAIN.sections.length}});
        }''')
        self.assertTrue(r['v2']['ticks'] < r['v3']['ticks'] < 2000, r)
        ratio = r['v3']['ticks'] / r['v2']['ticks']
        self.assertAlmostEqual(ratio, 2 ** 0.5, delta=0.02)
        self.assertEqual(r['v2Cap'], 180)
        self.assertEqual(r['v3Cap'], round(180 * ratio))
        v2e, v3e = r['v2Extent'], r['extent']
        self.assertEqual(v2e, dict(ascent=12960, horizontalEnvelope=6480, bandHeight=1620, encountersPerSection=4))
        self.assertEqual(v3e, dict(ascent=25920, horizontalEnvelope=12960, bandHeight=3240, encountersPerSection=4))
        for k in ('ascent', 'horizontalEnvelope', 'bandHeight'):
            self.assertEqual(v3e[k], 2 * v2e[k])
        r['flight_time_ratio'] = ratio
        self.__class__.flight = r
        print('PASS flight: free fall %d ticks over %d vs %d ticks over %d, ratio %.4f; density cap 180 x ratio = %.2f -> %d'
              % (r['v2']['ticks'], r['v2']['height'], r['v3']['ticks'], r['v3']['height'], ratio, 180 * ratio, r['v3Cap']))
        print('PASS extent: v3 %s = 2 x v2 %s' % (json.dumps(v3e, sort_keys=True), json.dumps(v2e, sort_keys=True)))

    def test_04_write_and_audit_calibration(self):
        import test_grapple_over_physics as physics
        self.assertTrue(self.results and self.reach and self.flight)
        fams = self.results['families']
        envelopes = {str(rng): {f: v['envelope'] for f, v in fs.items()} for rng, fs in fams.items()}
        runs = {str(rng): {f: [dict(dt=r['dt'], aim=r['aim'], negative=r['negative'], success=r['success'],
                range=r['range'], exit={k: r['rows'][100][k] for k in ('tick', 'x', 'y', 'speedX', 'speedY')},
                landing_tick=r['landing_contact']['tick'], trusted_inputs=len(r['inputs']),
                event_types=sorted(set(e['type'] for e in r['events']))) for r in v['runs']]
                for f, v in fs.items()} for rng, fs in fams.items()}
        current = self.current_hashes()
        self.assertEqual(current, self.hashes)
        f = self.flight
        data = dict(self.proof, constants=self.results['constants'], ranges=[1080, 1620],
            families_list=list(physics.TASK503_FAMILIES), exit_tick=100, success_exit_regions=physics.TASK503_BOXES,
            proof_convention='nominal + dt -3/+3 + aim -10.8/+10.8 must succeed, negative control must fail',
            measured_envelopes=envelopes, families=runs,
            measured_reach={str(k): v['measured_reach'] for k, v in self.reach.items()},
            gap_metric=dict(name='v3 mandatory gap', version=3, frozen=True,
                targets={str(k): v['gap_targets'] for k, v in self.reach.items()},
                rule='twice the TASK-503 v2 band; each endpoint inside 85-90% of measured reach and acquiring',
                measured={str(k): v for k, v in self.reach.items()}),
            extent=dict(frozen=f['extent'], v2=f['v2Extent'], ratio=2),
            flight_time=dict(definition='ticks of free fall from rest across one band height to a floor contact',
                v2=f['v2'], v3=f['v3'], ratio=f['flight_time_ratio']),
            density_cap=dict(frozen_ticks=f['v3Cap'], v2_ticks=f['v2Cap'], ratio=f['flight_time_ratio'],
                rule='longest allowed nominal-trace stretch without an acquisition, bounce or mover contact'),
            v2_reference='artifacts/TASK-503/calibration.json', all_families_pass=True)
        self.evidence.write('calibration.json', data)
        disk = json.loads(self.evidence.path('calibration.json').read_text())
        self.assertEqual(disk['source_hashes'], self.current_hashes())
        for rng in ('1080', '1620'):
            self.assertEqual(sorted(disk['families'][rng]), sorted(physics.TASK503_FAMILIES))
            for name, rows in disk['families'][rng].items():
                self.assertEqual([r['success'] for r in rows], [True] * 5 + [False])
                self.assertTrue(all(r['range'] == int(rng) for r in rows))
        print('PASS audit: 7 families x 2 ranges, 70 successful traces, 14 negative controls; reach %s; '
              'gap targets %s; extent %s; density cap %d; source hashes match'
              % (disk['measured_reach'], disk['gap_metric']['targets'], disk['extent']['frozen'],
                 disk['density_cap']['frozen_ticks']))


# TASK-546 layout-v3 fixture: S06 (range 1620) rebuilt as a v3 section. Static pads turn green, no
# solid exceptions, a 3240 band, gaps in the 1620 band and one miss point with a drag zone under it.
V3_FIXTURE = '''d => {
    const el=id=>d.geometry.elements.find(e=>e.id===id), rect=(w,h)=>[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]
    for (const id of ['S06-loading-floor','S06-phase-rest','S06-fixed-head','S06-transfer-head','S06-exit']) el(id).role='bounce'
    d.geometry.elements.push({id:'S06-fall-drag',x:6150,y:-8300,role:'drag',grapplable:false,points:rect(160,100)})
    const s=d.sections[5]
    delete s.solidExceptions
    Object.assign(s,{designVersion:3, band:{...s.band, top:s.band.bottom-3240},
        gaps:[{id:'head-run',mandatory:true,from:{x:4000,y:-8630},to:{x:5400,y:-8630}},
            {id:'exit-run',mandatory:true,from:{x:5600,y:-9700},to:{x:4180,y:-9700}}],
        fallPoints:[{id:'transfer-miss',encounter:'S06-04',x:6230,y:-9170}]})
    return d
}'''
# One mutation per v3 rule (plus the exception and below-bouncer variants) and its exact thrown error.
V3_NEGATIVE = {
    'staticGrayPad': ("d=>{d.geometry.elements.find(e=>e.id==='S06-phase-rest').role='solid'}",
                      'LayoutV3GraySolid: S06.S06-phase-rest', ['graySolid']),
    'solidException': ("d=>{d.sections[5].solidExceptions=[{element:'S06-exit',kind:'rest-pad',reason:'gray pad'}]}",
                       'LayoutV3GraySolid: S06.solidExceptions', ['graySolid']),
    'gapOutOfBand': ("d=>{d.sections[5].gaps[0].to={x:4000+0.95*1620,y:-8630}}",
                     'LayoutV3GapBand: S06.gaps.head-run', ['gapBand']),
    'fallWithoutDrag': ("d=>{d.sections[5].fallPoints.push({id:'exit-miss',encounter:'S06-04',x:5600,y:-9625})}",
                        'LayoutV3DragUnderFall: S06.fallPoints.exit-miss', ['dragUnderFall']),
    'dragBelowBouncer': ("d=>{d.geometry.elements.find(e=>e.id==='S06-fall-drag').y=-8000}",
                         'LayoutV3DragUnderFall: S06.fallPoints.transfer-miss', ['dragUnderFall', 'strayDrag']),
    'strayDrag': ("d=>{d.geometry.elements.push({id:'S06-stray-drag',x:300,y:-9000,role:'drag',grapplable:false,"
                  "points:[{x:0,y:0},{x:200,y:0},{x:200,y:80},{x:0,y:80}]})}",
                  'LayoutV3StrayDrag: S06.S06-stray-drag', ['strayDrag']),
    'wrongBandHeight': ("d=>{d.sections[5].band.top=d.sections[5].band.bottom-1620}",
                        'LayoutV3Extent: S06.band', ['extent']),
}
V3_RULE_CODES = {'graySolid': 'LayoutV3GraySolid', 'moverCoverage': 'LayoutV2MoverCoverage',
                 'direction': 'LayoutV2Direction', 'gapBand': 'LayoutV3GapBand',
                 'dragUnderFall': 'LayoutV3DragUnderFall', 'strayDrag': 'LayoutV3StrayDrag',
                 'extent': 'LayoutV3Extent'}


# Sections rebuilt as layout v3 (TASK-547: S01); the fixture adds S06.
V3_REBUILT = ['S01']


class Task546Tests(unittest.TestCase):
    """Layout-v3 design-rule validator: designVersion 3 opt-in with rule-specific failure codes."""
    task_id = 'TASK-546'
    open = Task465Tests.open
    test_03_source_hashes = Task465Tests.test_03_source_hashes

    @classmethod
    def setUpClass(cls):
        Task465Tests.setUpClass.__func__(cls)
        for name in ('tools/test_grapple_over_physics.py', 'tools/test_grapple_over_level.py'):
            cls.proof['source_hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.evidence.log('HASHES+ '+json.dumps(cls.proof['source_hashes'], sort_keys=True))

    def test_01_current_manifest_and_v3_fixture(self):
        page = self.open()
        r = page.evaluate('''fixture => {
            const current=layoutV2Report(GRAPPLE_OVER_MOUNTAIN); loadMountainLevel()
            const d=eval(fixture)(structuredClone(GRAPPLE_OVER_MOUNTAIN)), world=loadMountainLevel(d)
            return {current, fixture:layoutV2Report(d), codes:LAYOUT_V3_RULES, loaded:world.level.elements.length,
                targets:LAYOUT_V3_GAP_TARGETS, extent:LAYOUT_V3_EXTENT, columnRadius:LAYOUT_V3_FALL_COLUMN_RADIUS}
        }''', V3_FIXTURE)
        self.assertEqual(r['codes'], V3_RULE_CODES)
        cur = r['current']
        self.assertEqual([s['id'] for s in cur['sections']], [f'S{i:02}' for i in range(1, 9)])
        # Sections rebuilt for layout v3 (S01 from TASK-547) are judged by the v3 rules; the rest are not.
        rebuilt = [s for s in V3_REBUILT if s != 'S06']
        self.assertEqual(cur['v3'], rebuilt)
        self.assertFalse(cur['failed'])
        for s in cur['sections']:
            self.assertFalse(s['failed'], s)
            if s['id'] in rebuilt: continue
            self.assertIn(s['designVersion'], (1, 2), s)
            self.assertNotIn('graySolid', s.get('rules', {}), s)
        fx = r['fixture']
        self.assertEqual(fx['v3'], sorted(rebuilt + ['S06']))
        self.assertFalse(fx['failed'])
        s6 = next(s for s in fx['sections'] if s['id'] == 'S06')
        self.assertEqual(sorted(s6['rules']), sorted(V3_RULE_CODES))
        for name, rule in s6['rules'].items():
            self.assertTrue(rule['passed'], (name, rule))
        rules = s6['rules']
        self.assertEqual(s6['range'], 1620)
        self.assertEqual(rules['gapBand']['measured']['target'], [1378, 1458])
        for g in rules['gapBand']['measured']['gaps']:
            self.assertTrue(1378 <= g['distance'] <= 1458, g)
        self.assertEqual(rules['graySolid']['measured']['staticSolids'], [])
        self.assertEqual(sorted(rules['graySolid']['measured']['movers']), ['S06-counterweight', 'S06-upper-weight'])
        fall = rules['dragUnderFall']['measured']['fallPoints'][0]
        self.assertEqual(fall['dragZones'], ['S06-fall-drag'])
        self.assertEqual(fall['firstBouncer'], 'S05-exit')
        self.assertEqual(rules['strayDrag']['measured']['dragZones'], [dict(id='S06-fall-drag', fallPoints=['transfer-miss'])])
        self.assertEqual(rules['extent']['measured']['bandHeight'], 3240)
        self.assertEqual(rules['moverCoverage']['measured']['count'], 4)
        self.assertEqual(rules['direction']['measured']['actual'], 'left')
        # v1/v2 sections in the fixture are still reported, never judged by v3 rules.
        for s in fx['sections']:
            if s['id'] != 'S06' and s['id'] not in rebuilt:
                self.assertIn(s['designVersion'], (1, 2))
                self.assertNotIn('graySolid', s.get('rules', {}))
        self.evidence.write('rules.json', dict(self.proof, rules=[dict(rule=k, code=v) for k, v in V3_RULE_CODES.items()],
            gap_targets=r['targets'], extent=r['extent'], fall_column_radius=r['columnRadius'],
            current_manifest=dict(v1=[s['id'] for s in cur['sections'] if s['designVersion'] == 1],
                v2=cur['v2'], v3=cur['v3'], failed=cur['failed'],
                sections=[dict(id=s['id'], designVersion=s['designVersion'], failed=s['failed'],
                               judged_by_v3=s['id'] in rebuilt) for s in cur['sections']]),
            v3_fixture_section=s6, v3_fixture_loaded_elements=r['loaded'],
            current_no_v3_failure=True, fixture_all_v3_rules_passed=True))
        print('PASS rules: current manifest v1 %s, v2 %s, v3 %s, no failure; v3 fixture S06 passes %s'
              % ([s['id'] for s in cur['sections'] if s['designVersion'] == 1], cur['v2'], cur['v3'], sorted(rules)))

    def test_02_each_rule_rejects_its_mutation(self):
        page = self.open()
        cases = {k: v[0] for k, v in V3_NEGATIVE.items()}
        r = page.evaluate('''([fixture,cases]) => Object.entries(cases).map(([name,mutate])=>{
            const d=eval(fixture)(structuredClone(GRAPPLE_OVER_MOUNTAIN)); eval(mutate)(d)
            const s=layoutV2Report(d).sections.find(s=>s.id==='S06')
            let error=null; try {validateMountainManifest(d)} catch(e){error=e.message}
            return {name,mutation:mutate,error,failedRules:Object.entries(s.rules).filter(([,v])=>!v.passed).map(([k])=>k),
                errors:s.errors}
        })''', [V3_FIXTURE, cases])
        self.assertEqual([c['name'] for c in r], list(V3_NEGATIVE))
        for c in r:
            _, error, failed = V3_NEGATIVE[c['name']]
            self.assertEqual(c['error'], error, c)
            self.assertEqual(c['failedRules'], failed, c)
        self.assertEqual({c['error'].split(':')[0] for c in r},
                         {'LayoutV3GraySolid', 'LayoutV3GapBand', 'LayoutV3DragUnderFall', 'LayoutV3StrayDrag', 'LayoutV3Extent'})
        self.evidence.write('negative.json', dict(self.proof, fixture=V3_FIXTURE, cases=r,
            all_rejected_with_rule_specific_code=True))
        for c in r:
            print(f"PASS negative {c['name']}: rejected {c['error']}")


class Task547Tests(FoundationsV3Checks, unittest.TestCase):
    """Layout-v3 Foundations opening (S01-01/02): green bouncers and blue movers at the 1080 range."""
    task_id = 'TASK-547'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_04_source_hashes = Task465Tests.test_03_source_hashes


class Task548Tests(FoundationsV3CompleteChecks, unittest.TestCase):
    """Layout-v3 Foundations S01-03/04, exit pad settle and drag-zone fall recovery at the 1080 range."""
    task_id = 'TASK-548'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    open = Task465Tests.open
    test_06_source_hashes = Task465Tests.test_03_source_hashes


class Task549Tests(FoundationsV3ToleranceChecks, unittest.TestCase):
    """Layout-v3 Foundations (S01) mechanics and tolerance: 40 real-input attempts, drag-zone falls."""
    task_id = 'TASK-549'
    setUpClass = classmethod(Task465Tests.setUpClass.__func__)
    compact = Task506Tests.compact
    test_03_source_hashes = Task465Tests.test_03_source_hashes
