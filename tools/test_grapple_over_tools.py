"""TASK-461: real browser inputs, physics recording and production isolation."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from grapple_over_support import install_recorder, recorded_attempt, export_recording, state_hash
from perf_mobile import SEED_SCRIPT


class Task461Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-461')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('grapple_over_support.py','grapple_over_injector.js','test_grapple_over_tools.py'):
            path = 'tools/' + name
            hashes[path] = hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            source_hashes=hashes,browser=cls.browser.version,viewport=VIEWPORT,
            device_scale_factor=1,has_touch=True,seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof,sort_keys=True))

    def open(self):
        context = self.browser.new_context(viewport=VIEWPORT,device_scale_factor=1,has_touch=True)
        self.addCleanup(context.close)
        page = context.new_page()
        errors=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors,[]))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate("startGame('grapple_over'); menu.unPause(); cancelAnimationFrame(game); window.requestAnimationFrame=()=>0")
        page.wait_for_function('!unTouch')
        page.mouse.up()
        return page

    def test_mouse_touch_recording_and_failed_attempt_retention(self):
        page = self.open()
        install_recorder(page)
        cdp = page.context.new_cdp_session(page)
        for device in ('mouse','touch'):
            with recorded_attempt(page,device,self.evidence):
                page.evaluate('''() => {
                    const level=structuredClone(GRAPPLE_OVER_LEVEL);
                    level.movers=[{id:'moving-step',element:'top-step',axis:'x',min:650,max:750,
                        periodMs:2000,phase:0}];
                    GRAPPLE_OVER_TEST.spawn({level,player:{x:360,y:980,speedX:0,speedY:0},
                        camera:{x:0,y:0}});
                }''')
                point=page.evaluate('GRAPPLE_OVER_TEST.client({x:700,y:800})')
                if device=='mouse':
                    page.mouse.move(point['x'],point['y']);page.mouse.down()
                else:
                    cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[dict(x=point['x'],y=point['y'],id=1)]})
                page.evaluate('GRAPPLE_OVER_TEST.step(30)')
                if device=='mouse': page.mouse.up()
                else: cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                page.evaluate('GRAPPLE_OVER_TEST.step(150)')
                with self.assertRaisesRegex(Exception,'SetupOnly'):
                    page.evaluate('GRAPPLE_OVER_TEST.spawn({player:{x:0,y:0}})')
                attempt=export_recording(page)[-1]
                inputs=[e for e in attempt['events'] if e['type']=='input']
                self.assertEqual([e['event'] for e in inputs],['mousedown','mouseup'] if device=='mouse' else ['touchstart','touchend'])
                self.assertTrue(all(e['trusted'] for e in inputs))
                self.assertEqual(inputs[0]['world'],inputs[0]['resolvedTarget'])
                self.assertTrue(inputs[0]['after']['simulation']['grapple']['throwed'])
                self.assertFalse(inputs[1]['after']['simulation']['grapple']['throwed'])
                self.assertEqual([e['tick'] for e in inputs],[0,30])
                self.assertIn('acquisition',[e['type'] for e in attempt['events']])
                self.assertIn('release',[e['type'] for e in attempt['events']])
                self.assertIn('contact',[e['type'] for e in attempt['events']])
                snapshots=attempt['snapshots']
                self.assertEqual(len(snapshots),181)
                self.assertNotEqual(snapshots[0]['state']['simulation']['player'],snapshots[-1]['state']['simulation']['player'])
                self.assertNotEqual(snapshots[0]['state']['simulation']['elements'],snapshots[-1]['state']['simulation']['elements'])
                self.assertEqual([e['sequence'] for e in attempt['events']],list(range(len(attempt['events']))))
                self.assertEqual([e['tick'] for e in attempt['events']],sorted(e['tick'] for e in attempt['events']))
                for row in snapshots: self.assertEqual(row['sha256'],state_hash(row['state']))
        with self.assertRaisesRegex(RuntimeError,'intentional failure'):
            with recorded_attempt(page,'retained-failure',self.evidence):
                raise RuntimeError('intentional failure')
        attempts=export_recording(page)
        self.assertEqual([a['outcome'] for a in attempts],['passed','passed','failed'])
        retained=list(self.evidence.path('attempts').glob('*/recording.json'))
        self.assertTrue(any(json.loads(p.read_text())['outcome']=='failed' for p in retained))
        self.evidence.write('recorder.json',dict(self.proof,attempts=attempts,
            real_mouse_touch_pass=True,production_physics_pass=True,failed_attempt_retained_pass=True))
        print('PASS recorder: real mouse/touch handlers; ordered ticks/world aims; acquisition/release/contacts; production physics/movers; SHA256 snapshots; setup-only spawn; failed attempt retained')

    def test_wrap_and_knockback_events(self):
        page=self.open()
        install_recorder(page)
        observations=[]
        for kind in ('wrap','knockback'):
            with recorded_attempt(page,kind,self.evidence):
                page.evaluate('''kind=>{
                    const level=structuredClone(GRAPPLE_OVER_LEVEL);
                    const rect=(id,x,y,w,h,role='solid')=>({id,x,y,role,
                        points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
                    level.elements=kind==='wrap' ? [rect('anchor',1100,680,30,40),
                        rect('corner',900,800,80,50)] : [rect('hazard',400,700,600,100,'hazard')];
                    level.encounters[0].elements=level.elements.map(e=>e.id);
                    GRAPPLE_OVER_TEST.spawn({level,player:kind==='wrap' ?
                        {x:800,y:700,speedX:0,speedY:3} :
                        {x:700,y:680,speedX:0,speedY:3,hazardCooldownMs:0},
                        camera:{x:-450,y:-300}});
                }''',kind)
                if kind=='wrap':
                    point=page.evaluate('GRAPPLE_OVER_TEST.client({x:1100,y:700})')
                    page.mouse.move(point['x'],point['y']);page.mouse.down()
                page.evaluate('GRAPPLE_OVER_TEST.step(100)')
                if kind=='wrap': page.mouse.up()
                attempt=export_recording(page)[-1]
                matches=[e for e in attempt['events'] if e['type']==kind]
                self.assertTrue(matches,kind)
                if kind=='wrap':
                    self.assertNotEqual(len(matches[0]['before']['rope']),len(matches[0]['after']['rope']))
                else:
                    self.assertGreater(matches[0]['after']['simulation']['player']['hazardCooldownMs'],0)
                observations.append(attempt)
        self.evidence.write('events.json',dict(self.proof,attempts=observations,wrap_knockback_pass=True))
        print('PASS events: production physics generated recorded wrap and knockback transitions')

    def test_production_has_no_injector_or_teleport_controls(self):
        page=self.open()
        before=page.evaluate('captureClimbState()')
        scripts=page.eval_on_selector_all('script[src]','els=>els.map(e=>e.src)')
        self.assertFalse(any('grapple_over_injector' in s or '/tools/' in s for s in scripts))
        self.assertTrue(page.evaluate("typeof GRAPPLE_OVER_TEST === 'undefined'"))
        for key in ('t','F2','F8','Control+Shift+t'): page.keyboard.press(key)
        after=page.evaluate('captureClimbState()')
        self.assertEqual(before,after)
        self.assertNotIn('grapple_over_injector',(ROOT/'index.html').read_text())
        self.evidence.write('production-check.json',dict(self.proof,scripts=scripts,before=before,after=after,
            tested_keys=['t','F2','F8','Control+Shift+t'],debug_api_absent=True,
            index_does_not_load_injector_pass=True,normal_users_no_teleport_pass=True))
        print('PASS production: index does not load injector; debug API absent; teleport keys cannot change simulation')


class Task462Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        cls.evidence = EvidenceWriter('TASK-462')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.evidence.log('CONFIG ' + json.dumps(dict(browser=cls.browser.version,
            viewport=VIEWPORT, device_scale_factor=1, has_touch=True, hz=60, seed=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            source_hashes=hashes()), sort_keys=True))

    def fixture(self, kind='base-start'):
        from grapple_over_verify import metadata
        return dict(metadata=metadata(kind), ticks=45, inputs=[
            dict(tick=0,event='mousedown',world=dict(x=700,y=800)),
            dict(tick=30,event='mouseup',world=dict(x=700,y=800))],
            expected_exit={'x':[-2000,3000],'y':[-2000,3000]},
            required_events=['input','release'])

    def test_input_only_replay_clip_and_corruption_rejection(self):
        import copy
        from grapple_over_verify import execute, verify
        m = self.fixture()
        out = self.evidence.path('fixture-run')
        m['trace'] = execute(m,self.browser,self.url,out,clip=True)
        final = m['trace']['snapshots'][-1]['state']['simulation']['player']
        m['expected_exit'] = {k:[final[k]-0.001,final[k]+0.001] for k in ('x','y')}
        self.evidence.write('fixture-run/inputs.json',m)
        result = verify(m,self.browser,self.url,self.evidence.path('test-replayed'))
        self.assertGreater(self.evidence.path('fixture-run/clip.webm').stat().st_size,1000)
        cases = {}
        for name in ('inputs','hash','level_hash','exit','injection','trace_mutation','tick_gap','mechanic'):
            bad = copy.deepcopy(m)
            if name == 'inputs': bad['inputs'][0]['world']['x'] += 100
            elif name == 'hash': bad['metadata']['source_hashes']['fixedlevel.js'] = 'corrupt'
            elif name == 'level_hash': bad['metadata']['level_sha256'] = 'corrupt'
            elif name == 'exit': bad['expected_exit']['x'] = [99999,100000]
            elif name == 'injection': bad['inputs'][1]['state'] = {'x':99999}
            elif name == 'trace_mutation':
                row=bad['trace']['snapshots'][10]
                row['state']['simulation']['player']['x'] += 1
                row['sha256']=state_hash(row['state'])
            elif name == 'tick_gap': bad['trace']['snapshots'][10]['tick'] = 11
            elif name == 'mechanic': bad['required_events'].append('nonexistent')
            with self.assertRaises(ValueError) as caught:
                verify(bad,self.browser,self.url,self.evidence.path('rejected/'+name))
            cases[name] = dict(rejected=True,reason=str(caught.exception))
        self.evidence.write('replay.json',dict(result,corruptions=cases,
            recorded_trace='fixture-run/trace.json',replayed_trace='test-replayed/trace.json',
            clip='fixture-run/clip.webm'))
        print('PASS base-start: matching recorded/replayed state traces; input-only route; rendered clip')
        print('PASS corruption: inputs/hash/level_hash/exit/injection/trace_mutation/tick_gap/mechanic rejected')

    def test_isolated_snapshot_cannot_claim_base_start(self):
        import copy
        from grapple_over_verify import execute, verify
        m=self.fixture('isolated')
        m['initial_setup']={'player':{'x':420,'y':980,'speedX':0,'speedY':0},'camera':{'x':0,'y':0}}
        m['trace']=execute(m,self.browser,self.url,self.evidence.path('isolated'))
        result=verify(m,self.browser,self.url,self.evidence.path('isolated-replayed'))
        bad=copy.deepcopy(m)
        bad['metadata']['kind']='base-start'
        with self.assertRaisesRegex(ValueError,'base-start state injection'):
            verify(bad,self.browser,self.url,self.evidence.path('invalid-base'))
        snapshot=self.fixture('isolated')
        snapshot['initial_snapshot']=m['trace']['snapshots'][0]['state']['simulation']
        snapshot['trace']=execute(snapshot,self.browser,self.url,self.evidence.path('snapshot'))
        snap_result=verify(snapshot,self.browser,self.url,self.evidence.path('snapshot-replayed'))
        self.evidence.write('isolated.json',dict(result,snapshot=snap_result,base_claim_rejected=True))
        print('PASS isolated: setup and initial snapshot replay; base-start injection rejected')

    def test_bounded_timing_and_aim_variations(self):
        from grapple_over_verify import execute, verify, variations
        m=self.fixture()
        m['inputs']=variations(m['inputs'],tick_offset=2,aim_offset=(4,-3))
        self.assertEqual(m['inputs'][0],dict(tick=2,event='mousedown',world=dict(x=704,y=797)))
        m['trace']=execute(m,self.browser,self.url,self.evidence.path('variation'))
        result=verify(m,self.browser,self.url,self.evidence.path('variation-replayed'))
        with self.assertRaisesRegex(ValueError,'bounds'):
            variations(m['inputs'],tick_offset=4)
        with self.assertRaisesRegex(ValueError,'bounds'):
            variations(m['inputs'],aim_offset=(13,0))
        self.evidence.write('variation.json',dict(result,bounds_rejected=True,inputs=m['inputs']))
        print('PASS variation: bounded timing/aim replay through production handlers; excess rejected')
