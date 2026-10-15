"""In-memory save/replay and atomic rejection evidence for TASK-456."""
import hashlib
import json
import unittest

from grapple_over_test_support import ROOT
from test_grapple_over_physics import Task447Tests


FIXTURE = '''kind => {
    const d=structuredClone(GRAPPLE_OVER_LEVEL);
    d.movers=[{id:'step-motion',element:'right-step',axis:'x',min:550,max:650,periodMs:1700,phase:.25}];
    d.elements.push({id:'red',x:1300,y:1400,role:'hazard',points:[{x:0,y:0},{x:300,y:0},{x:300,y:60},{x:0,y:60}]});
    d.encounters[0].elements.push('red');
    floors=[loadFixedLevel(d)];
    ninja.x=1100;ninja.y=600;ninja.speedX=.3;ninja.speedY=1;
    grapnel=new Grapnel({stroke:STYLE.colors.player.cyan});
    pressHeld=false;stalePress=false;
    for(let i=0;i<7;i++)physics();
    if(kind==='wrapped-moving') {
        const e=floors[0].byId.get('right-step');
        grapnel.throwed=grapnel.grappled=true;pressHeld=true;
        grapnel.pos=[[e.x,e.y,e],[e.x+300,e.y,e]];
        ninja.x=e.x+340;ninja.y=e.y+150;
    }
    if(kind==='flight') {
        grapnel.throwed=true;pressHeld=true;
        grapnel.speedX=-2;grapnel.speedY=1;grapnel.traveled=15;
        grapnel.pos=[[ninja.x-15,ninja.y+7,new Empty()]];
        grapnel.move(); // Include a pending swept collision step.
    }
    if(kind==='knockback') {
        ninja.x=1400;ninja.y=1400-ninja.radius+1;ninja.speedY=2;
        pressHeld=true;ninja.collision();
    }
    if(kind==='completed') floors[0].climbStats.completed=true;
    return captureClimbState();
}'''

REPLAY = '''() => {
    const trace=[],events=[];
    const solid=ninja.applySolidContact, hazard=ninja.applyHazardContact;
    ninja.applySolidContact=function(c){events.push(['solid',trace.length]);return solid.call(this,c)};
    ninja.applyHazardContact=function(c){events.push(['hazard',trace.length]);return hazard.call(this,c)};
    for(let i=0;i<600;i++) {physics();trace.push(captureClimbState())}
    delete ninja.applySolidContact;delete ninja.applyHazardContact;
    return {trace,events};
}'''


class Task456Tests(unittest.TestCase):
    task_id='TASK-456'
    open=Task447Tests.open

    @classmethod
    def setUpClass(cls):
        Task447Tests.setUpClass.__func__(cls)
        for name in ('tools/test_grapple_over_save.py',):
            cls.proof['source_hashes'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.evidence.log('CONFIG '+json.dumps(cls.proof,sort_keys=True))

    def test_roundtrip_600_ticks(self):
        page=self.open()
        fixtures=[]
        kinds=('free-fall','flight','wrapped-moving','knockback','completed',
               'release-attached-mouse','release-flight-mouse',
               'release-attached-touch','release-flight-touch')
        for kind in kinds:
            fixture=('wrapped-moving' if 'attached' in kind else 'flight') if kind.startswith('release-') else kind
            original=page.evaluate(FIXTURE,fixture)
            release=None
            if kind.startswith('release-'):
                release=page.evaluate('''kind => {
                    const before=captureClimbState();
                    const event=kind.endsWith('mouse') ? new MouseEvent('mouseup',{bubbles:true}) :
                        new Event('touchend',{bubbles:true,cancelable:true});
                    document.dispatchEvent(event);
                    return {before,after:captureClimbState(),retainedSegments:grapnel.pos.length};
                }''',kind)
                original=release['after']
                self.assertTrue(release['before']['grapple']['throwed'])
                self.assertGreater(release['retainedSegments'],0)
                self.assertFalse(original['grapple']['throwed'])
                self.assertFalse(original['grapple']['grappled'])
                self.assertFalse(original['input']['pressHeld'])
                self.assertEqual(original['grapple']['segments'],[])
                self.assertIsNone(original['grapple']['shotStep'])
            if kind=='wrapped-moving':
                self.assertEqual([p['id'] for p in original['grapple']['segments']],['right-step']*2)
            if kind=='knockback':
                self.assertEqual(original['player']['hazardCooldownMs'],350)
                self.assertTrue(original['input']['stalePress'])
            first=page.evaluate(REPLAY)
            restored=page.evaluate('s=>{restoreClimbState(s);return captureClimbState()}',original)
            second=page.evaluate(REPLAY)
            # Compare every numeric leaf, all IDs, flags, lengths and gameplay events.
            errors=[]
            def compare(a,b):
                self.assertEqual(type(a),type(b))
                if isinstance(a,dict):
                    self.assertEqual(a.keys(),b.keys())
                    for k in a: compare(a[k],b[k])
                elif isinstance(a,list):
                    self.assertEqual(len(a),len(b))
                    for x,y in zip(a,b): compare(x,y)
                elif isinstance(a,(float,int)) and not isinstance(a,bool):
                    errors.append(abs(a-b));self.assertLessEqual(abs(a-b),1e-6)
                else: self.assertEqual(a,b)
            compare(original,restored);compare(first,second)
            fixtures.append(dict(kind=kind,original=original,restored=restored,
                original_run=first,restored_run=second,ticks=600,max_error=max(errors),
                exact_ids_and_events=True,release=release))
        self.evidence.write('roundtrip.json',dict(self.proof,fixtures=fixtures,roundtrip_pass=True))
        print(f'PASS roundtrip: {len(kinds)} fixtures x 600 physics ticks; max error <=1e-6; exact element IDs and gameplay events')
        print('PASS release: attached and flight mouseup/touchend captures restore and replay 600 ticks')

    def test_invalid_atomic_rejection(self):
        page=self.open()
        page.evaluate(FIXTURE,'wrapped-moving')
        rows=page.evaluate('''() => {
            const base=captureClimbState(),rows=[];
            const mutations={
                'save-version':s=>s.version=99,
                'level-version':s=>s.levelVersion=99,
                'missing-anchor':s=>s.grapple.segments[0].id='missing',
                'missing-element':s=>s.elements.pop(),
                'duplicate-element':s=>s.elements[0].id=s.elements[1].id,
                'nan':s=>s.player.x=NaN,
                'infinity':s=>s.elements[0].dx=Infinity,
                'invalid-local':s=>s.grapple.segments[0].x=-Infinity,
                'negative-tick':s=>s.simulationTick=-1,
                'fractional-tick':s=>s.simulationTick=.5,
                'missing-player':s=>delete s.player,
                'malformed-stats':s=>s.stats.completed='yes',
                'malformed-grapple':s=>s.grapple.segments={},
                'inconsistent-grapple':s=>s.grapple.throwed=false,
                'null':s=>null
            };
            for(const [kind,mutate] of Object.entries(mutations)) {
                let s=structuredClone(base);const changed=mutate(s);if(changed===null)s=null;
                const identities=[ninja,grapnel,floors[0]];let error=null;
                try{restoreClimbState(s)}catch(e){error=e.message}
                rows.push({kind,error,rejected:!!error,
                    unchanged:JSON.stringify(base)===JSON.stringify(captureClimbState()),
                    sameObjects:ninja===identities[0]&&grapnel===identities[1]&&floors[0]===identities[2]});
            }
            return rows;
        }''')
        for row in rows:
            self.assertTrue(row['rejected'] and row['unchanged'] and row['sameObjects'],row)
        self.evidence.write('invalid.json',dict(self.proof,cases=rows,atomic_rejection_pass=True))
        print('PASS invalid: 15 bad versions/references/numbers/malformed states rejected; no partial application')


class Task457Tests(unittest.TestCase):
    task_id = 'TASK-457'
    setUpClass = classmethod(Task456Tests.setUpClass.__func__)

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('storage.json', dict(cls.proof, scenarios=cls.observations))

    def open_storage(self, seed=None, delayed=False, unavailable=False):
        from browser_test_support import wait_for_boot
        if not hasattr(type(self), 'observations'):
            type(self).observations = []
        context = self.browser.new_context(viewport={'width':1280,'height':720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script('''(() => {
            window.storageCalls=[];
            const set=Storage.prototype.setItem;
            Storage.prototype.setItem=function(key,value) {
                storageCalls.push({key,value,at:performance.now()});
                return set.call(this,key,value);
            };
        })()''')
        if seed:
            page.add_init_script('for(const [k,v] of Object.entries('+json.dumps(seed)+')) localStorage.setItem(k,v)')
        if unavailable:
            page.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('blocked storage')}})")
        if delayed:
            source=(ROOT/'platform.js').read_text().replace('get remoteKnown() { return true }','get remoteKnown() { return false }').replace('onRecovery() {},','onRecovery(fn) { window.recoverStorage = fn },')
            page.route('**/platform.js', lambda r:r.fulfill(body=source,content_type='application/javascript'))
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate('''() => {
            window.adapterCalls=[];
            const set=PLATFORM.storage.setMany;
            PLATFORM.storage.setMany=async values => {
                adapterCalls.push({values,at:performance.now(),failure:window.failWrites||false});
                if(window.failWrites==='throw') throw Error('write failed');
                if(window.failWrites) return false;
                return set(values);
            };
            startGame('grapple_over');cancelAnimationFrame(game);
        }''')
        return page

    def observe(self, page, name, **data):
        type(self).observations.append(dict(name=name, **data, calls=page.evaluate('adapterCalls'),
            local_calls=page.evaluate('storageCalls')))

    def test_falling_throttle_pause_exit_pagehide_reload(self):
        legacy={'grapnelninja.records':'{"classic":123,"bad":456}',
                'grapnelninja.lang':'ru','grapnelninja.time':'90','grapnelninja.tutorialDone':'true'}
        page=self.open_storage(legacy)
        page.evaluate('ninja.x=1100;ninja.y=300;ninja.speedY=2;floors[0].climbStats.maxHeight=9000;physics()')
        page.wait_for_timeout(100)
        first=page.evaluate('captureClimbState()')
        for _ in range(5):
            page.evaluate('physics()')
            page.wait_for_timeout(230)
        current=page.evaluate('captureClimbState()')
        self.assertGreater(current['player']['y'],first['player']['y'])
        calls=page.evaluate("adapterCalls.filter(c=>c.values['grapnelninja.grappleOver'])")
        self.assertGreaterEqual(len(calls),2)
        self.assertTrue(all(b['at']-a['at']>=990 for a,b in zip(calls,calls[1:])))
        page.evaluate('menu.startPause()')
        saved=page.evaluate("JSON.parse(localStorage.getItem('grapnelninja.grappleOver'))")
        self.assertEqual(saved,current)
        page.evaluate("ninja.y+=17;startGame('bad');cancelAnimationFrame(game)")
        exit_save=page.evaluate("JSON.parse(localStorage.getItem('grapnelninja.grappleOver'))")
        self.assertEqual(exit_save['player']['y'], current['player']['y']+17)
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game);ninja.y+=21;window.dispatchEvent(new Event('pagehide'))")
        hidden=page.evaluate("JSON.parse(localStorage.getItem('grapnelninja.grappleOver'))")
        self.assertEqual(hidden['player']['y'],exit_save['player']['y']+21)
        self.observe(page,'falling/lifecycle',falling_positions=[first['player'],current['player']],
                     periodic_intervals=[b['at']-a['at'] for a,b in zip(calls,calls[1:])],pause=saved,mode_exit=exit_save,pagehide=hidden)
        page.reload()
        from browser_test_support import wait_for_boot
        wait_for_boot(page)
        restored=page.evaluate("() => {startGame('grapple_over');cancelAnimationFrame(game);return captureClimbState()}")
        self.assertEqual(restored,hidden)
        intact=page.evaluate('keys=>Object.fromEntries(keys.map(k=>[k,localStorage.getItem(k)]))',list(legacy))
        self.assertEqual(intact,legacy)
        type(self).observations.append(dict(name='reload',restored=restored,legacy=intact,reload_pass=True))
        print('PASS falling current-state saves; periodic throttle; pause; mode exit; pagehide; exact reload; legacy intact')

    def test_delayed_read_and_failed_writes(self):
        page=self.open_storage(delayed=True)
        old=page.evaluate('captureClimbState()')
        old['player']['y']-=200
        page.evaluate("s=>recoverStorage({'grapnelninja.grappleOver':JSON.stringify(s)})",old)
        self.assertEqual(page.evaluate('ninja.y'),old['player']['y'])
        page.evaluate("failWrites='throw';ninja.x=1100;physics()")
        page.wait_for_timeout(100)
        changed=page.evaluate('captureClimbState()')
        page.evaluate("s=>recoverStorage({'grapnelninja.grappleOver':JSON.stringify(s)})",old)
        self.assertEqual(page.evaluate('captureClimbState()'),changed)
        page.evaluate('failWrites=true;PROGRESS.flushClimb();physics()')
        page.wait_for_timeout(30)
        page.evaluate('failWrites=false;window.dispatchEvent(new Event("pagehide"))')
        page.wait_for_timeout(30)
        latest=page.evaluate('captureClimbState()')
        self.assertEqual(page.evaluate("JSON.parse(localStorage.getItem('grapnelninja.grappleOver'))"),latest)
        self.observe(page,'delayed-read/write-failure',old=old,modified=changed,latest=latest,delayed_read_pass=True,write_retry_pass=True)
        self.assertTrue(any(c['failure']=='throw' for c in page.evaluate('adapterCalls')))
        self.assertTrue(any(c['failure'] is True for c in page.evaluate('adapterCalls')))
        print('PASS delayed read restores untouched climb and cannot overwrite modified climb; thrown/false writes recover')

    def test_invalid_and_unavailable(self):
        for raw in ('{broken', '{"version":999}'):
            page=self.open_storage({'grapnelninja.grappleOver':raw,'grapnelninja.lang':'ru','grapnelninja.tutorialDone':'true'})
            notice=page.locator('#climb-save-notice')
            self.assertEqual(notice.inner_text(),'Сохранение недоступно. Начинаем у подножия.')
            base=page.evaluate('({x:ninja.x,y:ninja.y,spawn:GRAPPLE_OVER_LEVEL.spawn})')
            self.assertEqual(base['x'],base['spawn']['x'])
            self.assertEqual(base['y'],base['spawn']['y'])
            page.evaluate("TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500);draw()")
            page.screenshot(path=str(self.evidence.path('invalid-save.png')))
            page.evaluate('physics()')
            self.assertGreater(page.evaluate('floors[0].elapsedSteps'),0)
            self.observe(page,'invalid',raw=raw,base=base,notice=notice.inner_text(),base_usable_pass=True)
        page=self.open_storage(unavailable=True)
        page.evaluate('ninja.x=1100;physics();PROGRESS.flushClimb()')
        page.wait_for_timeout(30)
        saved=page.evaluate("async()=>JSON.parse((await PLATFORM.storage.getMany(PROGRESS.keys))['grapnelninja.grappleOver'])")
        self.assertEqual(saved,page.evaluate('captureClimbState()'))
        page.evaluate('physics()')
        self.assertGreater(page.evaluate('floors[0].elapsedSteps'),saved['simulationTick'])
        self.observe(page,'unavailable',saved=saved,memory_fallback_pass=True)
        print('PASS corrupt/incompatible saves: localized notice and usable base; unavailable storage keeps play and in-memory save')
