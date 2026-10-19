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
    gameplayPressOwned=pressHeld && !stalePress;
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
        # Pausing a restored run now flushes legitimate active play time.
        self.assertGreaterEqual(int(intact['grapnelninja.time']),int(legacy['grapnelninja.time']))
        self.assertEqual({k:v for k,v in intact.items() if k!='grapnelninja.time'},
                         {k:v for k,v in legacy.items() if k!='grapnelninja.time'})
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


class Task458Tests(unittest.TestCase):
    task_id = 'TASK-458'
    setUpClass = classmethod(Task456Tests.setUpClass.__func__)

    def test_restore_resume_and_fresh_input(self):
        from browser_test_support import wait_for_boot
        context = self.browser.new_context(viewport={'width':1280,'height':720},
            device_scale_factor=1, has_touch=True, record_video_dir=str(self.evidence.path('video')),
            record_video_size={'width':1280,'height':720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        # A real moving level fixture, retained across page reloads.
        source=(ROOT/'fixedlevel.js').read_text()+'''\n
GRAPPLE_OVER_LEVEL.movers=[{id:'step-motion',element:'right-step',axis:'x',min:550,max:650,periodMs:1700,phase:.25}];
'''
        page.route('**/fixedlevel.js',lambda r:r.fulfill(body=source,content_type='application/javascript'))
        page.goto(self.url)
        wait_for_boot(page)
        self.proof['has_touch']=True
        self.evidence.log('CONFIG '+json.dumps(self.proof,sort_keys=True))
        rows=[]
        def state():
            return page.evaluate('captureClimbState()')
        def button(kind):
            page.wait_for_function('!unTouch')
            coords=page.evaluate('canvasCoordsToViewportCoords({x:menu.resume.text.x,y:menu.resume.text.y})')
            page.evaluate('''({coords,kind})=>{
                if(kind==='mouse') {
                    document.dispatchEvent(new MouseEvent('mousedown',{clientX:coords.x,clientY:coords.y,bubbles:true}));
                    document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
                } else {
                    const e=new Event('touchstart',{bubbles:true,cancelable:true});
                    e.changedTouches=[{clientX:coords.x,clientY:coords.y}];document.dispatchEvent(e);
                    document.dispatchEvent(new Event('touchend',{bubbles:true,cancelable:true}));
                }
            }''',dict(coords=coords,kind=kind))
        for kind in ('moving-attachment','free-fall'):
            page.evaluate('''kind=>{
                startGame('grapple_over');cancelAnimationFrame(game);
                ninja.x=1050;ninja.y=600;ninja.speedX=.3;ninja.speedY=1;
                for(let i=0;i<7;i++)physics();
                if(kind==='moving-attachment') {
                    const e=floors[0].byId.get('right-step');
                    ninja.x=e.x+340;ninja.y=e.y+150;
                    grapnel.throwed=grapnel.grappled=true;pressHeld=true;
                    grapnel.pos=[[e.x+150,e.y,e]];
                } else grapnel.endShot();
                PROGRESS.flushClimb();
            }''',kind)
            saved=state()
            page.reload();wait_for_boot(page)
            page.evaluate("startGame('grapple_over');TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500);redrawOverlays()")
            restored=state()
            self.assertTrue(page.evaluate('menu.gamePaused'))
            for key in ('player','elements','grapple','simulationTick','stats'):
                self.assertEqual(saved[key],restored[key],key)
            page.wait_for_timeout(1000)
            frozen=state();self.assertEqual(frozen,restored)
            framing=page.evaluate('''()=>({x:(ninja.x+screen.x)*scale[version],
                y:(ninja.y+screen.y)*scale[version],r:ninja.radius*scale[version],width,height})''')
            self.assertTrue(framing['r']<=framing['x']<=framing['width']-framing['r'])
            self.assertTrue(framing['r']<=framing['y']<=framing['height']-framing['r'])
            # Stop rAF only after observing a live paused loop. UI dispatch is
            # synchronous so exact momentum/rope comparisons precede physics.
            page.evaluate('cancelAnimationFrame(game)')
            ui=[]
            for input_kind in ('mouse','touch'):
                before=state();button(input_kind);after=state()
                self.assertFalse(page.evaluate('menu.gamePaused'))
                self.assertEqual(before,after)
                ui.append(dict(kind=input_kind,before=before,after=after))
                page.evaluate('draw();menu.startPause()')
            button('mouse')
            page.evaluate('game=requestAnimationFrame(gameLoop)')
            page.wait_for_timeout(1000)
            advanced=state();self.assertGreater(advanced['simulationTick'],frozen['simulationTick'])
            page.evaluate('cancelAnimationFrame(game)')
            page.wait_for_function('!unTouch')
            inputs=[]
            for input_kind in ('mouse','touch'):
                page.evaluate('s=>{restoreClimbState(s);pressHeld=false;stalePress=false;gameplayPressOwned=false}',restored)
                result=page.evaluate('''kind=>{
                    const before=captureClimbState();
                    const coords=canvasCoordsToViewportCoords({x:width*.7,y:height*.25});
                    const send=type=>{
                        const e=kind==='mouse'?new MouseEvent(type,{clientX:coords.x,clientY:coords.y,bubbles:true}):new Event(type,{bubbles:true,cancelable:true});
                        if(kind==='touch')e.changedTouches=[{clientX:coords.x,clientY:coords.y}];
                        document.dispatchEvent(e);
                    };
                    send(kind==='mouse'?'mousedown':'touchstart');const pressed=captureClimbState();
                    send(kind==='mouse'?'mouseup':'touchend');return {before,pressed,released:captureClimbState()};
                }''',input_kind)
                self.assertEqual(result['before']['grapple'],restored['grapple'])
                self.assertTrue(result['pressed']['grapple']['throwed'])
                self.assertFalse(result['pressed']['grapple']['grappled'])
                self.assertFalse(result['released']['grapple']['throwed'])
                inputs.append(dict(kind=input_kind,**result))
            rows.append(dict(kind=kind,saved=saved,restored=restored,frozen=frozen,framing=framing,
                ui=ui,advanced=advanced,inputs=inputs,no_physics_before_resume_pass=True,
                saved_movers_rope_unchanged_pass=True,ui_ownership_pass=True,new_gameplay_input_pass=True))
        # Visibility/rotation while a gameplay press is held requires a fresh
        # release/press, and must never auto-resume on returning to landscape.
        guards=[]
        for reason in ('hidden','portrait'):
            page.mouse.move(900,200);page.mouse.down()
            before=state()
            if reason=='hidden':
                page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
            else:
                page.set_viewport_size({'width':720,'height':1280})
                page.wait_for_timeout(180)
            page.evaluate('menu.unPause();game=requestAnimationFrame(gameLoop)')
            page.wait_for_timeout(180)
            blocked=state();self.assertTrue(page.evaluate('menu.gamePaused'),reason)
            self.assertEqual(before['simulationTick'],blocked['simulationTick'])
            self.assertEqual(before['grapple'],blocked['grapple'])
            if reason=='hidden':
                page.evaluate("delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'))")
            else:
                page.set_viewport_size({'width':1280,'height':720});page.wait_for_timeout(180)
            self.assertTrue(page.evaluate('menu.gamePaused'))
            page.evaluate('cancelAnimationFrame(game);menu.unPause()')
            page.mouse.down()
            stale=state();self.assertEqual(stale['grapple'],blocked['grapple'])
            page.mouse.up();page.mouse.down()
            fresh=state();self.assertTrue(fresh['grapple']['throwed'])
            self.assertFalse(fresh['input']['stalePress'])
            page.mouse.up()
            guards.append(dict(reason=reason,before=before,blocked=blocked,stale=stale,fresh=fresh,paused_pass=True,fresh_input_pass=True))
        # Real hazard collision sets the guard; held input cannot refire.
        page.evaluate(FIXTURE,'knockback')
        knocked=state();self.assertTrue(knocked['input']['stalePress'])
        page.mouse.down();held=state();self.assertFalse(held['grapple']['throwed'])
        page.mouse.up();page.mouse.down();fresh=state();self.assertTrue(fresh['grapple']['throwed'])
        page.mouse.up()
        self.assertEqual(errors,[])
        video=page.video
        context.close()
        video.save_as(str(self.evidence.path('resume.webm')))
        video.delete()
        self.evidence.write('resume.json',dict(self.proof,scenarios=rows,guards=guards,
            hazard=dict(knocked=knocked,held=held,fresh=fresh,fresh_input_pass=True),errors=errors))
        print('PASS moving-attachment and free-fall: frozen restore, movers/rope/momentum, mouse/touch Resume ownership, fresh gameplay, camera framing')
        print('PASS hidden/portrait remain paused; fresh input after pause and hazard knockback; resume.webm recorded')


# Test-only helpers for TASK-502. placeInUpgradeBand() is a labeled test
# placement into the S05 band, not a climb proof; shots use real mouse input.
RANGE_HELPERS = '''() => {
    window.bandOf=id=>floors[0].level.sections.find(s=>s.id===id).band;
    window.activeRadius=()=>grappleOverAcquisitionRadius();
    window.placeAt=(x,y)=>{ninja.x=x;ninja.y=y;ninja.speedX=ninja.speedY=0;
        grapnel.endShot();pressHeld=stalePress=gameplayPressOwned=false;
        if(ninja.track)ninja.track.pos.length=0;screen.trackGrappleOver(true)};
    // A point with nothing within 60 units on either axis.
    window.isFree=(x,y)=>!grapnel.nearestCrossing({x:x-60,y},[x+60,y])&&!grapnel.nearestCrossing({x,y:y-60},[x,y+60]);
    // TEST-ONLY PLACEMENT: put the player's center just inside the S05 band,
    // at the free point nearest the band's horizontal middle. TASK-529: when S05
    // has a rangeUpgradeZone (the top of the S04 exit box, against the ledge), the
    // player is put at the middle of that zone instead.
    window.placeInUpgradeBand=()=>{const z=floors[0].level.sections.find(s=>s.id==='S05').rangeUpgradeZone;
        if(z){const x=(z.left+z.right)/2,y=(z.top+z.bottom)/2;placeAt(x,y);return {x,y,zone:z,label:'TEST-ONLY'}}
        const b=bandOf('S05'),y=b.bottom-20,mid=(b.left+b.right)/2;
        for(let d=0;d<mid-b.left;d+=40) for(const x of [mid-d,mid+d]) if(isFree(x,y)){placeAt(x,y);return {x,y,label:'TEST-ONLY'}}
        throw Error('no free S05 placement')};
    // Radius argument actually passed to ctx.arc by the range circle.
    window.drawnRadius=()=>{const radii=[],arc=ctx.arc,circle=drawAcquisitionCircle;
        window.drawAcquisitionCircle=()=>{ctx.arc=function(x,y,radius,...rest){radii.push(radius);return arc.call(this,x,y,radius,...rest)};
            try{circle()}finally{ctx.arc=arc}};
        try{draw()}finally{window.drawAcquisitionCircle=circle}
        if(radii.length!==1)throw Error('range circle arcs: '+radii.length);return radii[0]};
    // An attachable anchor straight above a free S04 point, exactly 600 units away.
    window.findAnchor=()=>{const b=bandOf('S04');
        for(let y=b.bottom-100;y>b.top+100;y-=40) for(let x=b.left+200;x<b.right-200;x+=40){
            const hit=grapnel.nearestCrossing({x,y},[x,y-1000]);
            if(!hit||grapnel.blocksShot(hit.element)) continue;
            const sy=hit.hit.y+600;
            if(sy>b.bottom-60||sy<b.top+60) continue;
            const clear=grapnel.nearestCrossing({x,y:sy},[x,hit.hit.y-1]);
            const below=grapnel.nearestCrossing({x,y:sy},[x,sy+80]);
            const side=grapnel.nearestCrossing({x:x-40,y:sy},[x+40,sy]);
            if(clear&&clear.element===hit.element&&Math.abs(clear.hit.y-hit.hit.y)<1e-9&&!below&&!side)
                return {x,y:sy,anchor:{x,y:hit.hit.y,id:hit.element.id}};
        }
        return null};
}'''


class Task502Tests(unittest.TestCase):
    task_id = 'TASK-502'
    setUpClass = classmethod(Task456Tests.setUpClass.__func__)

    def open(self):
        page = Task447Tests.open(self)
        page.evaluate('menu.unPause();cancelAnimationFrame(game);window.requestAnimationFrame=()=>0')
        page.evaluate(RANGE_HELPERS)
        return page

    def shoot(self, page, spot, ticks=40):
        """Real mouse press toward the anchor; held while physics steps."""
        page.evaluate('s=>placeAt(s.x,s.y)', spot)
        page.wait_for_function('!unTouch')
        aim = page.evaluate('''s=>{const p=canvasCoordsToViewportCoords({x:(s.x+screen.x)*scale[version],
            y:(s.y-200+screen.y)*scale[version]});return p}''', spot)
        page.mouse.move(aim['x'], aim['y'])
        page.mouse.down()
        rows = page.evaluate('''n=>{const rows=[];for(let i=0;i<n;i++){physics();rows.push({tick:floors[0].elapsedSteps,
            x:ninja.x,y:ninja.y,throwed:grapnel.throwed,grappled:grapnel.grappled,traveled:grapnel.traveled,
            radius:activeRadius(),tip:grapnel.pos[0]?grapnel.pos[0].slice(0,2):null,
            anchor:grapnel.grappled?grapnel.pos[0][2].id:null})}return rows}''', ticks)
        page.mouse.up()
        return rows

    def test_01_range_upgrade(self):
        page = self.open()
        spot = page.evaluate('findAnchor()')
        self.assertIsNotNone(spot)
        self.assertEqual(spot['y'] - spot['anchor']['y'], 600)
        before_state = page.evaluate('s=>{placeAt(s.x,s.y);return captureClimbState()}', spot)
        self.assertFalse(before_state['upgrades']['range'])
        circle_before = page.evaluate('drawnRadius()')
        self.assertEqual(circle_before, 540)
        miss = self.shoot(page, spot)
        self.assertTrue(all(r['radius'] == 540 and not r['grappled'] for r in miss))
        self.assertTrue(miss[-1]['throwed'])  # held miss parked at the range edge
        self.assertAlmostEqual(miss[-1]['traveled'], 540)
        # Labeled test-only placement into S05, then physics decides the flip.
        placed = page.evaluate('placeInUpgradeBand()')
        flip = page.evaluate('''()=>{const rows=[];const band=bandOf('S05');
            for(let i=0;i<5;i++){const pre=floors[0].rangeUpgraded;physics();
                rows.push({tick:floors[0].elapsedSteps,before:pre,after:floors[0].rangeUpgraded,
                    x:ninja.x,y:ninja.y,inBand:ninja.y>=band.top&&ninja.y<=band.bottom,
                    radius:activeRadius(),noticeMs:floors[0].rangeNoticeMs})}
            return {rows,band}}''')
        first = flip['rows'][0]
        self.assertFalse(first['before'])
        self.assertTrue(first['after'] and first['inBand'] and first['radius'] == 810)
        circle_after = page.evaluate('drawnRadius()')
        self.assertEqual(circle_after, 810)
        # Fall physically back below the S05 band bottom into S04.
        fall = page.evaluate('''()=>{const b=bandOf('S05'),s4=bandOf('S04');let n=0;
            while(ninja.y<=b.bottom+40&&n<2000){physics();n++}
            return {ticks:n,y:ninja.y,inS04:ninja.y>s4.top&&ninja.y<=s4.bottom,upgraded:floors[0].rangeUpgraded,
                radius:activeRadius(),circle:drawnRadius()}}''')
        self.assertTrue(fall['inS04'])
        self.assertEqual((fall['radius'], fall['circle']), (810, 810))
        # Same shot from the same S04 spot, now with the earned range.
        upgraded_state = dict(before_state, upgrades={'range': True})
        page.evaluate('s=>restoreClimbState(s)', upgraded_state)
        hit = self.shoot(page, spot)
        grabbed = [r for r in hit if r['grappled']]
        self.assertTrue(grabbed)
        self.assertEqual(grabbed[0]['anchor'], spot['anchor']['id'])
        self.assertTrue(all(r['radius'] == 810 for r in hit))
        self.evidence.write('range.json', dict(self.proof, spot=spot, anchor_distance=spot['y']-spot['anchor']['y'],
            input='playwright page.mouse move/down/up toward the anchor; physics() stepped while held',
            before_upgrade=dict(circle_radius=circle_before, shot=miss, acquired=False),
            test_only_placement=dict(label='TEST-ONLY placeInUpgradeBand(); not a climb proof', position=placed),
            upgrade_flip=dict(tick=first['tick'], band=flip['band'], rows=flip['rows']),
            after_upgrade=dict(circle_radius=circle_after),
            fallen_to_s04=fall,
            after_upgrade_shot=dict(shot=hit, acquired=True, first_grapple_tick=grabbed[0]['tick'],
                anchor=grabbed[0]['anchor']),
            range_pass=True))
        print(f"PASS range: 600-unit shot misses at 540, flag flips at tick {first['tick']}, circle 540->810, "
              f"S04 after fall 810, same shot acquires {grabbed[0]['anchor']}")

    def test_02_persistence(self):
        from browser_test_support import wait_for_boot
        page = self.open()
        page.evaluate('placeInUpgradeBand();physics()')
        self.assertTrue(page.evaluate('floors[0].rangeUpgraded'))
        spot = page.evaluate('findAnchor()')
        page.evaluate('s=>{placeAt(s.x,s.y);ninja.speedX=.4;physics()}', spot)
        start = page.evaluate('captureClimbState()')
        self.assertTrue(start['upgrades']['range'])
        replay = '''n=>{const t=[];for(let i=0;i<n;i++){physics();t.push(captureClimbState())}return {trace:t,radius:activeRadius()}}'''
        uninterrupted = page.evaluate(replay, 300)
        page.evaluate('s=>restoreClimbState(s)', start)
        page.evaluate('PROGRESS.flushClimb()')
        page.wait_for_function("JSON.parse(localStorage.getItem('grapnelninja.grappleOver')||'{}').upgrades?.range===true")
        saved = page.evaluate("JSON.parse(localStorage.getItem('grapnelninja.grappleOver'))")
        self.assertEqual(saved, start)
        rows = []
        def check(name):
            state = page.evaluate('captureClimbState()')
            self.assertEqual(state, start, name)
            page.evaluate('menu.unPause();cancelAnimationFrame(game);window.requestAnimationFrame=()=>0;pressHeld=stalePress=gameplayPressOwned=false')
            run = page.evaluate(replay, 300)
            self.assertEqual(run, uninterrupted, name)
            rows.append(dict(name=name, restored_equal=True, continuation_equal=True, ticks=300,
                radius=run['radius'], upgraded=state['upgrades']['range']))
        page.evaluate('s=>restoreClimbState(s)', start)
        check('restore')
        page.evaluate('s=>{restoreClimbState(s);PROGRESS.flushClimb()}', start)
        page.wait_for_timeout(50)
        page.reload(); wait_for_boot(page)
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
        page.evaluate(RANGE_HELPERS)
        check('reload')
        page.evaluate("s=>{restoreClimbState(s);window.dispatchEvent(new Event('pagehide'))}", start)
        page.wait_for_timeout(50)
        page.reload(); wait_for_boot(page)
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
        page.evaluate(RANGE_HELPERS)
        check('pagehide-reload')
        page.evaluate("s=>{restoreClimbState(s);startGame('bad');cancelAnimationFrame(game)}", start)
        bad_mode = page.evaluate('version')
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
        check('mode-switch-bad')
        page.evaluate("s=>{restoreClimbState(s);startGame('classic');cancelAnimationFrame(game)}", start)
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
        check('mode-switch-classic')
        # Legacy save without an upgrades field restores as not upgraded.
        legacy = {k: v for k, v in start.items() if k != 'upgrades'}
        legacy_radius = page.evaluate('s=>{restoreClimbState(s);return activeRadius()}', legacy)
        self.assertEqual(legacy_radius, 540)
        # Restart through real mouse clicks on the pause menu buttons.
        page.evaluate('s=>{restoreClimbState(s);menu.startPause()}', start)
        def tap(key):
            page.wait_for_function('!unTouch')
            boxes = page.evaluate('''() => {LAYOUT_PROBE.boxes=[]; menu.drawPauseScreen();
                const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;return b}''')
            label = page.evaluate('k=>I18N.t(k)', key)
            box = next(b for b in boxes if b['kind'] == 'button' and b['name'] == label)
            rect = page.locator('#canvas').bounding_box()
            page.mouse.click(rect['x']+box['x']+box['width']/2, rect['y']+box['y']+box['height']/2)
            page.evaluate('cancelAnimationFrame(game)')
        tap('climb.restart'); self.assertTrue(page.evaluate('CLIMB_UI.confirming'))
        tap('climb.cancel'); self.assertFalse(page.evaluate('CLIMB_UI.confirming'))
        cancelled = page.evaluate('({state:captureClimbState(),radius:activeRadius()})')
        self.assertEqual(cancelled['state'], start)
        self.assertEqual(cancelled['radius'], 810)
        tap('climb.restart'); tap('climb.yes')
        page.wait_for_function("JSON.parse(localStorage.getItem('grapnelninja.grappleOver')).simulationTick===0")
        confirmed = page.evaluate('''()=>({state:captureClimbState(),radius:activeRadius(),circle:drawnRadius(),
            saved:JSON.parse(localStorage.getItem('grapnelninja.grappleOver'))})''')
        self.assertFalse(confirmed['state']['upgrades']['range'])
        self.assertFalse(confirmed['saved']['upgrades']['range'])
        self.assertEqual((confirmed['radius'], confirmed['circle']), (540, 540))
        self.evidence.write('persistence.json', dict(self.proof, start=start, saved_state=saved,
            saved_upgrade_flag=saved['upgrades']['range'], uninterrupted_final=uninterrupted['trace'][-1],
            continuations=rows, intermediate_mode=bad_mode, legacy_save_radius=legacy_radius,
            cancelled_restart=dict(upgraded=cancelled['state']['upgrades']['range'], radius=cancelled['radius'],
                state_unchanged=True),
            confirmed_restart=dict(upgraded=confirmed['state']['upgrades']['range'],
                saved_upgraded=confirmed['saved']['upgrades']['range'], radius=confirmed['radius'],
                circle=confirmed['circle'], tick=confirmed['state']['simulationTick']),
            persistence_pass=True))
        print('PASS persistence: saved upgrades.range=true; restore/reload/pagehide/mode-switch continue equal to '
              'uninterrupted 300 ticks at 810; cancelled restart keeps 810; confirmed restart resets to 540')

    def test_03_notice_once(self):
        rows = []
        for lang in ('en', 'ru'):
            page = self.open()
            page.evaluate("l=>{I18N.language=l;applyLanguage();TUTORIAL_HINT.press(version);TUTORIAL_HINT.advance(2500)}", lang)
            page.evaluate('placeInUpgradeBand();physics();draw()')
            boxes = page.evaluate('''()=>{LAYOUT_PROBE.boxes=[];draw();const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;return b}''')
            label = page.evaluate("I18N.t('climb.rangeUpgrade')")
            shown = [b for b in boxes if b['kind'] == 'text' and b.get('name') == label]
            self.assertTrue(shown, boxes)
            page.screenshot(path=str(self.evidence.path(f'notice-{lang}.png')))
            # Let the notice expire, leave the band, then enter S05 a second time.
            page.evaluate('''()=>{let n=0;while(floors[0].rangeNoticeMs>0&&n<5000){physics();n++}
                const b=bandOf('S04');placeAt(b.left+600,b.bottom-300);physics()}''')
            gone = page.evaluate("()=>{LAYOUT_PROBE.boxes=[];draw();const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;return b}")
            page.evaluate('placeInUpgradeBand();physics()')
            second = page.evaluate('''()=>{LAYOUT_PROBE.boxes=[];draw();const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;
                return {boxes:b,noticeMs:floors[0].rangeNoticeMs,upgraded:floors[0].rangeUpgraded,y:ninja.y}}''')
            again = [b for b in second['boxes'] if b['kind'] == 'text' and b.get('name') == label]
            self.assertEqual(again, [])
            self.assertEqual(second['noticeMs'], 0)
            self.assertFalse([b for b in gone if b['kind'] == 'text' and b.get('name') == label])
            page.screenshot(path=str(self.evidence.path(f'notice-{lang}-second-entry.png')))
            rows.append(dict(lang=lang, text=label, first_entry_boxes=shown, second_entry_y=second['y'],
                second_entry_notice_boxes=again, second_entry_noticeMs=second['noticeMs']))
        self.evidence.write('notice.json', dict(self.proof, notices=rows, once_pass=True))
        print('PASS notice: EN/RU one-time HUD notice on first S05 entry; none on second entry')
