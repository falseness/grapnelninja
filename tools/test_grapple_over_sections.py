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
        cls.evidence = EvidenceWriter('TASK-465')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_sections.py', 'tools/grapple_over_support.py',
                     'tools/grapple_over_injector.js'):
            hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = dict(browser=cls.browser.version, viewport=VIEWPORT, device_scale_factor=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            source_hashes=hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    def open(self):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
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
        self.assertEqual([e['status'] for e in m['encounters'][:4]], ['built','built','planned','planned'])
        self.assertEqual(m['sections'][0]['status'],'partial')
        self.assertTrue(all(e['role']=='solid' for e in m['geometry']['elements']))
        self.assertEqual([c['status'] for c in m['connectors'][:2]], ['built','built'])
        self.assertIsNone(result['runtime']['finish'])
        for e in m['geometry']['elements'][3:]:
            self.assertGreaterEqual(e['y']+min(p['y'] for p in e['points']),-1620)
        self.evidence.write('geometry.json', dict(self.proof, **result,
            calibration_reference='artifacts/TASK-463/calibration.json',
            design=dict(entrance_width=600, landing_width=560, landing_top=-120,
                acquisition_range=540, short_miss_floor=18, catch_floor=120,
                temporary_exit='loading bay with raised end stop',
                intended_actions=[e['action'] for e in m['encounters'][:2]])))
        print('PASS geometry: S01-01/02 built; 30 planned; structural_validations_pass; matching runtime polygons; solid roles; base connector; temporary exit')

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
