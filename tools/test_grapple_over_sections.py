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
                     'tools/grapple_over_injector.js'):
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
        for e in m['geometry']['elements'][3:]:
            self.assertGreaterEqual(e['y']+min(p['y'] for p in e['points']),-1700)
        self.evidence.write('geometry.json', dict(self.proof, **result,
            calibration_reference='artifacts/TASK-463/calibration.json',
            design=dict(entrance_width=600, landing_width=560, landing_top=-120,
                acquisition_range=540, short_miss_floor=18, catch_floor=120,
                opening_rest='loading bay with raised end stop',
                intended_actions=[e['action'] for e in m['encounters'][:2]])))
        print('PASS geometry: S01-01/02/03/04 built; 28 planned; structural_validations_pass; matching runtime polygons; solid roles; base connector; loading bay rest')

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
        self.assertTrue(all(e['status']=='planned' for e in m['encounters'][4:]))
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
        cls.evidence = EvidenceWriter('TASK-467')
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
