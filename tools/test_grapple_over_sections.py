"""Real-input opening route proof; all retained output stays task-local."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from grapple_over_support import install_recorder


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
                (5190,-4630,90,33 if touch else 30),
                (5270,-4880,60,360 if touch else 300)]

    def make_input(self, device, limit, critical, delta, offset, bounds, departure_free=None):
        from grapple_over_verify import metadata
        m=dict(metadata=metadata('isolated'),initial_setup=dict(level=self.level,
            player=dict(x=4430,y=-3190.8,speedX=0,speedY=0)),inputs=[],
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
            ('S03-01',1,0,dict(x=[4750,4840],y=[-3480,-3390],speedX=[.6,1.2]),0),
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
