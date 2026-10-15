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


class Task463Tests(unittest.TestCase):
    """Measure isolated mechanics with production physics and trusted mouse input."""
    open = Task461Tests.open

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        cls.evidence = EvidenceWriter('TASK-463')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.hashes = hashes()
        cls.hashes['tools/grapple_over_calibration.js'] = hashlib.sha256(
            (ROOT/'tools/grapple_over_calibration.js').read_bytes()).hexdigest()
        cls.evidence.log('CONFIG ' + json.dumps(dict(browser=cls.browser.version,
            viewport=VIEWPORT,device_scale_factor=1,has_touch=True,hz=60,substeps=8,seed=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            source_hashes=cls.hashes),sort_keys=True))

    def attempt(self,page,family,dt=0,aim=0,negative=False):
        page.mouse.up()
        page.evaluate('GRAPPLE_OVER_TEST.attempts.length=0')
        page.evaluate('n=>GRAPPLE_OVER_TEST.begin(n)',family)
        page.evaluate('calibrationSetup',dict(family=family,negative=negative))
        if family=='angled_bounce':
            actions=[(0,'mousedown',700+aim,440),(3+dt,'mouseup',700,440)]
        elif family=='corner_wrap':
            actions=[(3+dt,'mousedown',1100,700+aim),(85,'mouseup',1100,700)]
        elif family=='braking':
            actions=[] if negative else [(3+dt,'mousedown',580,700+aim),(50,'mouseup',580,700)]
        else:
            actions=[] if negative else [(0,'mousedown',930+aim,660),
                (30+dt,'mouseup',930,660)]
            if family=='launch' and not negative:
                actions=[(3+dt,'mousedown',930+aim,660),(60,'mouseup',930,660)]
            if family=='moving_transfer' and not negative:
                actions += [(33+dt,'mousedown',680+aim,510),(85,'mouseup',680,510)]
        tick=0
        for at,event,x,y in actions:
            page.evaluate('n=>GRAPPLE_OVER_TEST.step(n)',at-tick);tick=at
            p=page.evaluate('GRAPPLE_OVER_TEST.client',dict(x=x,y=y))
            page.mouse.move(p['x'],p['y'])
            if event=='mousedown': page.mouse.down()
            else: page.mouse.up()
        page.evaluate('n=>GRAPPLE_OVER_TEST.step(n)',100-tick)
        page.evaluate('''() => {
            for(let i=100;i<600;i++) {
                const landing=floors[0].level.elements.find(e=>e.id==='landing');
                if(Math.abs(ninja.y-(landing.y-ninja.radius))<1e-5 && Math.abs(ninja.speedY)<1e-8) break;
                GRAPPLE_OVER_TEST.step(1);
            }
        }''')
        page.evaluate("GRAPPLE_OVER_TEST.finish('measured')")
        result=page.evaluate('calibrationResult()')
        result.update(dt=dt,aim=aim,negative=negative)
        return result

    def test_01_six_movement_families(self):
        page=self.open()
        install_recorder(page)
        page.add_script_tag(path=str(ROOT/'tools/grapple_over_calibration.js'))
        constants=page.evaluate('''() => ({gravity:GRAVITY,pull:grappleSpeed,
            throwSpeed:grapnelSpeed,cyclesPerTick,physicsStepMs,radius:ninja.radius,
            range:MODE_DEFINITIONS.grapple_over.acquisitionRadius,scale:scale.grapple_over})''')
        baseline=json.loads((ROOT/'artifacts/TASK-444/baseline.json').read_text())['modes']['classic']
        for key in ('gravity','pull','throwSpeed','cyclesPerTick','physicsStepMs'):
            self.assertEqual(constants[key],baseline['constants'][key])
        self.assertEqual(constants['radius'],baseline['initial']['radius'])
        self.assertEqual((constants['range'],constants['scale']),(540,0.75))
        families={}
        for family in ('launch','release','braking','angled_bounce','corner_wrap','moving_transfer'):
            families[family]=[self.attempt(page,family,dt,aim) for dt,aim in
                ((0,0),(-3,0),(3,0),(0,-10.8),(0,10.8))]
            families[family].append(self.attempt(page,family,negative=True))
            for r in families[family]:
                print('MEASURE',family,r['dt'],r['aim'],r['negative'],
                    {k:round(r['rows'][100][k],3) for k in ('x','y','speedX','speedY')},
                    sorted(set(e['type'] for e in r['events'])),len(r['bounces']))
        self.evidence.write('calibration.json',dict(constants=constants,source_hashes=self.hashes,families=families))
        # Freeze exit boxes independently of individual variant outcomes. These
        # are calibration fixture targets at tick 100, not mountain completion.
        boxes = {
            'launch': {'x':[1190,1270],'y':[680,730]},
            'release': {'x':[1040,1140],'y':[715,840]},
            'braking': {'x':[1390,1600],'y':[970,1035],'speedX':[0,0.6]},
            'angled_bounce': {'x':[-650,-400],'y':[0,250]},
            'corner_wrap': {'x':[970,1090],'y':[2250,2380]},
            'moving_transfer': {'x':[780,840],'y':[645,690]}}
        metrics=dict(hz=60,substeps=8,range=540,scale=0.75,exit_tick=100,
            position_epsilon=1e-5,velocity_epsilon=1e-8,
            proof_convention={'critical_action_ticks':[-3,0,3],
                'aim_tangent_offsets':[-10.8,0,10.8],
                'minimum_successes':'nominal plus at least two distinct variants',
                'aim_tangents':{'braking':[0,1],'corner_wrap':[0,1],
                    'launch':[1,0],'release':[1,0],'angled_bounce':[1,0],'moving_transfer':[1,0]},
                'critical_actions':{'launch':'press at tick 3','release':'release at tick 30',
                    'braking':'press at tick 3','angled_bounce':'release at tick 3',
                    'corner_wrap':'press at tick 3','moving_transfer':'release/second press at ticks 30/33'}},
            success_exit_regions=boxes,
            failure_exit_regions='complement of success box at tick 100 OR missing mechanic event',
            negative_controls={'launch':'omit grapple','release':'omit grapple',
                'braking':'omit opposing grapple','angled_bounce':'replace bounce slope with solid',
                'corner_wrap':'remove named corner','moving_transfer':'omit transfer inputs'},
            landing='first post-exit contact with landing top; sliding is allowed, not claimed stationary')
        self.evidence.write('metrics.json',metrics)
        envelopes={}
        for family,runs in families.items():
            for r in runs:
                row=r['rows'][100]
                events=r['events']
                ids=[p['id'] for e in events if e['type']=='acquisition' for p in e['rope']]
                if family=='angled_bounce':
                    mechanic=bool(r['bounces']) and r['bounces'][0]['after']['speedX'] < -1
                elif family=='corner_wrap':
                    mechanic=any(e['type']=='wrap' and any(p['id']=='corner' for p in e['rope']) for e in events)
                elif family=='moving_transfer':
                    mechanic=ids[:2]==['anchor','moving-target']
                    moving=[e for e in r['rows'][0]['elements'] if e['id']=='moving-target']
                    self.assertTrue(moving)
                    self.assertNotEqual(r['rows'][0]['elements'],r['rows'][100]['elements'])
                else:
                    mechanic='anchor' in ids and any(e['type']=='release' for e in events)
                r['success']=mechanic and all(lo<=row[k]<=hi for k,(lo,hi) in boxes[family].items())
                self.assertEqual(r['success'],not r['negative'],(family,r['dt'],r['aim'],row))
                self.assertTrue(all(i['trusted'] for i in r['inputs']))
                landing=next(e for e in r['setup']['level']['elements'] if e['id']=='landing')
                hits=[e for e in events if e['type']=='contact' and e.get('contact',{}).get('ny')==-1
                    and abs(e['contact']['y']-landing['y'])<1e-5]
                self.assertTrue(hits,(family,'landing absent'))
                r['landing_contact']=hits[0]
            successes=[r for r in runs if r['success']]
            self.assertGreaterEqual(len(successes),3)
            self.assertTrue(successes[0]['dt']==successes[0]['aim']==0)
            # Measured samples only: endpoints are not a continuous guarantee.
            window=sorted(set(3+r['dt'] if family in ('launch','braking','corner_wrap','angled_bounce')
                else 30+r['dt'] for r in successes))
            for r in runs: r['successful_action_tick_samples']=window
            envelopes[family]={
                'launch':{k:[min(r['rows'][0][k] for r in successes),
                    max(r['rows'][0][k] for r in successes)] for k in ('x','y','speedX','speedY')},
                'exit':{k:[min(r['rows'][100][k] for r in successes),
                    max(r['rows'][100][k] for r in successes)] for k in ('x','y','speedX','speedY')},
                'landing':{k:[min(r['landing_contact']['player'][k] for r in successes),
                    max(r['landing_contact']['player'][k] for r in successes)] for k in ('x','y','speedX','speedY')},
                'landing_ticks':[min(r['landing_contact']['tick'] for r in successes),
                    max(r['landing_contact']['tick'] for r in successes)],
                'successful_action_tick_samples':window}

            print('PASS',family,': nominal + 4 variants; negative rejected; measured landing contacts; action ticks',window)
        self.evidence.write('calibration.json',dict(constants=constants,source_hashes=self.hashes,
            families=families,measured_envelopes=envelopes,all_six_families_pass=True))
        self.evidence.path('notes.md').write_text('''Measured facts: calibration.json records production 60 Hz / 8-substep player positions,
velocities (world units/substep; multiply by 480 for units/second), contacts,
trusted input traces, moving elements and successful sampled action windows.
Each isolated setup records its launch position and velocity. Tick-100 exit boxes
are frozen in metrics.json. Landing contacts record the actual landing envelope;
sliding contact is not a stable rest. Corner wrap's exit is a fall, not ascent.
Timing endpoints are sampled, not a proof that every intermediate tick succeeds.
These six fixtures are calibration, not base-start or full mountain route proof.
Gravity, pull, throw speed, radius and timestep match artifacts/TASK-444/baseline.json;
range is 540 and scale 0.75. No runtime, classic/bad, neon, saves or checkpoint changes.

Design targets: encounter proof must include nominal plus at least two distinct
successful variants, testing critical action +/-3 ticks and aim +/-0.02R along
local surface tangent, with mechanic-specific negative controls. Require exit
region AND mechanic evidence, not mere reach. Use these fixture measurements to
choose launch/landing space; later encounters must supply their own input proofs.

Research inferences (motivation only, never gameplay evidence):
Foddy's interview describes crisis situations and the possibility of losing progress;
this motivates physical falls and testing release windows.
https://www.gamedeveloper.com/business/road-to-the-igf-bennett-foddy-s-i-getting-over-it-i-
Generating Levels That Teach Mechanics studies mechanic-focused level generation;
this motivates mechanic-specific negative controls rather than reach-only tests.
https://arxiv.org/html/1807.06734
Neither source validates Grapple Over parameters, tolerances or playability.
''')

    def test_02_independent_evidence_audit(self):
        from grapple_over_verify import hashes
        data=json.loads(self.evidence.path('calibration.json').read_text())
        metrics=json.loads(self.evidence.path('metrics.json').read_text())
        current=hashes()
        current['tools/grapple_over_calibration.js']=hashlib.sha256(
            (ROOT/'tools/grapple_over_calibration.js').read_bytes()).hexdigest()
        self.assertEqual(data['source_hashes'],current)
        self.assertTrue(data['all_six_families_pass'])
        for name,runs in data['families'].items():
            self.assertEqual(len(runs),6)
            for r in runs:
                row=next(p for p in r['rows'] if p['tick']==metrics['exit_tick'])
                in_box=all(a<=row[k]<=b for k,(a,b) in metrics['success_exit_regions'][name].items())
                if not r['negative']:
                    self.assertTrue(in_box)
                    self.assertTrue(r['inputs'])
                    self.assertEqual(r['landing_contact']['contact']['ny'],-1)
                else:
                    self.assertFalse(r['success'])
                self.assertEqual([p['tick'] for p in r['rows']],list(range(len(r['rows']))))
        print('PASS independent audit: 6 families, 30 successful traces, 6 negative controls, source hashes match')
