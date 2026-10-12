"""Production death flow with trusted input; SDK and monotonic-clock boundary faults only."""
import hashlib
import json
import subprocess
import unittest
import test_playgama2_bridge as support

AD_FAKE = r"""
values['grapnelninja.tutorialDone']='true';
bridge.platform.language='en';
window.outcome='hold';
const originalEmitHost=window.emitHost;
window.emitHost=(event,value)=>{record('host-event',{event,value});originalEmitHost(event,value)};
bridge.advertisement.isInterstitialSupported=true;
bridge.advertisement.isRewardedSupported=true;
bridge.advertisement.off=(event,fn)=>probe.handlers[event]=probe.handlers[event].filter(h=>h!==fn);
bridge.advertisement.showRewarded=()=>record('REWARDED_REQUEST');
bridge.advertisement.showInterstitial=placement=>{
    record('ad-request',{placement,outcome,runOver,death:continueOffer.visible,menu:menu.visible});
    if(outcome==='late') return;
    if(outcome==='stuck') bridge.advertisement.interstitialState='opened';
    emitHost('interstitial','opened');
    if(outcome==='throw') throw Error('INJECTED SDK throw');
    if(outcome==='reject') return Promise.reject(Error('INJECTED SDK reject'));
    if(outcome==='failed') emitHost('interstitial','failed');
};
"""

class Playgama2AdsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.results={}
        paths=subprocess.check_output(['git','ls-files'],text=True).splitlines()+['tools/test_playgama2_ads.py']
        (cls.out/'tested-source-hashes.json').write_text(json.dumps({p:hashlib.sha256((support.ROOT/p).read_bytes()).hexdigest() for p in sorted(set(paths)) if not p.startswith(('artifacts/','screenshots/'))},indent=2))

    @classmethod
    def tearDownClass(cls):
        (cls.out/'ad-events.json').write_text(json.dumps(cls.results,indent=2)+'\n')

    def open(self,case):
        self.case=case
        self.results[case]=[]
        ctx=self.browser.new_context(viewport={'width':1280,'height':720})
        self.addCleanup(ctx.close)
        ctx.add_init_script("window.clockOffset=0; const nativeNow=performance.now.bind(performance); performance.now=()=>nativeNow()+clockOffset; window.inputs=[]; window.addEventListener('mousedown',e=>inputs.push({trusted:e.isTrusted,ms:performance.now()}),true)")
        ctx.route(support.SDK,lambda r:r.fulfill(content_type='application/javascript',body='const FAULT="normal", SAVED_LANGUAGE="en";\n'+support.FAKE+AD_FAKE))
        page=ctx.new_page();page.set_default_timeout(15000)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        self.addCleanup(lambda:self.assertEqual(errors,[]))
        page.goto(self.url+'current/index.html');support.wait_for_boot(page)
        self.snap(page,'startup')
        self.assertEqual(self.requests(page),[])
        self.assertEqual(page.evaluate('PLATFORM.showInterstitial()'),'skipped')
        self.click(page,'menu.classicVersionButton')
        self.assertEqual(page.evaluate('PLATFORM.showInterstitial()'),'skipped')
        self.snap(page,'active-play-no-ad')
        return page

    def requests(self,p):
        return p.evaluate("probe.calls.filter(e=>e.name==='ad-request')")

    def click(self,p,button):
        p.wait_for_function('!unTouch')
        point=p.evaluate('''() => {const b='''+button+'''.background,r=canvas.getBoundingClientRect();return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}}''')
        p.mouse.click(**point)

    def snap(self,p,phase,capture=False):
        r=p.evaluate('''() => ({ms:performance.now(),menu:menu.visible,paused:menu.gamePaused,death:continueOffer.visible,pending:interstitialPending,adOpen,score:scoreText.count[version],audio:AUDIO.getState(),host_events:probe.calls.filter(e=>e.name==='host-event'),requests:probe.calls.filter(e=>e.name==='ad-request'||e.name==='REWARDED_REQUEST'),inputs})''')
        r['phase']=phase
        if capture:
            p.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            path=self.out/f'{self.case}-{len(self.results[self.case]):02d}-{phase}.png'
            subprocess.run(['import','-window','root',str(path)],env=self.env,check=True,timeout=12)
            r['capture']={'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        self.results[self.case].append(r)
        return r

    def death(self,p):
        # Let real gravity and collisions end the run; no application-state injection.
        p.wait_for_function('continueOffer.visible')
        self.assertTrue(p.evaluate('runOver'))
        self.assertEqual(p.evaluate('typeof PLATFORM.requestRewarded'),'undefined')
        self.assertEqual(p.evaluate('continueOffer.title.text'),'Game over')
        self.assertEqual(p.evaluate('continueOffer.restartButton.text.text'),'Restart')
        self.assertEqual(p.evaluate('continueOffer.menuButton.text.text'),'back to menu')
        self.snap(p,'death-menu',True)

    def restarted(self,p,phase='post-ad'):
        p.wait_for_function('!interstitialPending && !continueOffer.visible')
        r=self.snap(p,phase,True)
        self.assertFalse(r['menu']);self.assertFalse(r['adOpen'])
        self.assertEqual(r['score'],0)
        self.assertFalse(r['audio']['muted']['ad'])
        return r

    def finish_case(self,p):
        requests=self.requests(p)
        for a,b in zip(requests,requests[1:]): self.assertGreaterEqual(b['ms']-a['ms'],120000)
        for r in requests:
            self.assertTrue(r['data']['runOver']);self.assertTrue(r['data']['death']);self.assertFalse(r['data']['menu'])
        self.assertEqual(p.evaluate("probe.calls.filter(e=>e.name==='REWARDED_REQUEST').length"),0)
        self.assertTrue(p.evaluate('inputs.every(e=>e.trusted)'))
        self.results[self.case].append({'verdict':'PASS natural deaths; free native restart/menu; zero startup/active-play/rewarded requests; request gaps >=120000ms; audio/pause reconciled','request_timestamps':[r['ms'] for r in requests]})
        print('PASS '+self.case+': '+self.results[self.case][-1]['verdict'][5:],flush=True)

    def test_supported_cooldown_duplicates(self):
        p=self.open('supported');self.death(p)
        self.click(p,'continueOffer.restartButton')
        self.assertEqual(len(self.requests(p)),1)
        self.assertTrue(p.evaluate('interstitialPending && adOpen && AUDIO.isMuted()'))
        before=p.evaluate('[ninja.x,ninja.y]');p.wait_for_timeout(150)
        self.assertEqual(before,p.evaluate('[ninja.x,ninja.y]'))
        self.click(p,'continueOffer.restartButton')
        self.assertEqual(len(self.requests(p)),1)
        self.snap(p,'ad-open')
        p.evaluate("emitHost('pause',true); emitHost('interstitial','closed'); emitHost('interstitial','closed'); emitHost('interstitial','failed'); emitHost('interstitial','opened')")
        r=self.restarted(p);self.assertTrue(r['paused']);self.assertTrue(r['audio']['muted']['hostPause'])
        p.evaluate("emitHost('pause',false)")
        self.click(p,'menu.resume')
        self.assertFalse(p.evaluate('AUDIO.isMuted()'))
        self.death(p);self.click(p,'continueOffer.restartButton');self.restarted(p,'before-cooldown')
        self.assertEqual(len(self.requests(p)),1)
        self.death(p)
        # Clock boundary advance preserves all production cooldown checks and callbacks.
        p.evaluate('clockOffset+=120000')
        self.click(p,'continueOffer.menuButton');self.assertEqual(len(self.requests(p)),2)
        p.evaluate("emitHost('interstitial','closed');emitHost('interstitial','closed')")
        p.wait_for_function('menu.visible && !interstitialPending')
        self.snap(p,'post-ad-menu',True)
        self.click(p,'menu.classicVersionButton');self.restarted(p,'menu-new-run')
        self.finish_case(p)

    def frozen(self,p,label):
        r=p.evaluate("({adOpen,pending:interstitialPending,muted:AUDIO.getState().muted.ad})")
        before=p.evaluate('[ninja.x,ninja.y]');p.wait_for_timeout(150)
        after=p.evaluate('[ninja.x,ninja.y]')
        print(f'ASSERT {label}: adOpen={r["adOpen"]} pending={r["pending"]} ad-muted={r["muted"]} ninja {before} -> {after}',flush=True)
        self.assertTrue(r['adOpen']);self.assertTrue(r['muted']);self.assertFalse(r['pending'])
        self.assertEqual(before,after)

    def released(self,p,label):
        p.evaluate("emitHost('interstitial','closed')")
        r=p.evaluate("({adOpen,muted:AUDIO.getState().muted.ad})")
        before=p.evaluate('[ninja.x,ninja.y]');p.wait_for_function('([x,y])=>ninja.x!==x||ninja.y!==y',arg=before)
        print(f'ASSERT {label} closed: adOpen={r["adOpen"]} ad-muted={r["muted"]} ninja moves from {before}',flush=True)
        self.assertFalse(r['adOpen']);self.assertFalse(r['muted'])

    def ad_states(self,p):
        return p.evaluate("adStates")

    def test_late_open_after_open_watchdog(self):
        # TASK-340: the SDK opens our interstitial after the 'skipped' watchdog.
        p=self.open('late')
        p.evaluate("outcome='late';PLATFORM.interstitialOpenTimeoutMs=300;window.adStates=[];PLATFORM.onAdState(s=>adStates.push(s));window.adResults=[];const show=PLATFORM.showInterstitial;PLATFORM.showInterstitial=(...a)=>show(...a).then(r=>(adResults.push(r),r))")
        self.death(p);self.click(p,'continueOffer.restartButton')
        p.wait_for_function('!interstitialPending && !continueOffer.visible')
        self.assertFalse(p.evaluate('adOpen'))
        self.assertEqual(len(self.requests(p)),1);self.assertEqual(p.evaluate('adResults.at(-1)'),'skipped')
        print('ASSERT showInterstitial resolved '+json.dumps(p.evaluate('adResults.at(-1)'))+'; run restarted; adStates='+json.dumps(self.ad_states(p)),flush=True)
        p.evaluate("emitHost('interstitial','loading');emitHost('interstitial','opened')")
        self.assertEqual(self.ad_states(p),['opened'])
        print('ASSERT late opened emitted adState '+json.dumps(self.ad_states(p)),flush=True)
        self.frozen(p,'late opened');self.released(p,'late')
        self.assertEqual(self.ad_states(p),['opened','closed'])
        # A host interstitial nobody requested after that close is not ours.
        p.evaluate("emitHost('interstitial','opened')")
        self.assertFalse(p.evaluate('adOpen'))
        print('ASSERT unrequested opened after close ignored: adStates='+json.dumps(self.ad_states(p)),flush=True)
        p.evaluate("emitHost('interstitial','closed')")

    def test_playing_watchdog_while_sdk_open(self):
        # TASK-340: the playing watchdog fires while the SDK still reports 'opened'.
        p=self.open('stuck')
        p.evaluate("outcome='stuck';PLATFORM.interstitialPlayingTimeoutMs=300;window.adStates=[];PLATFORM.onAdState(s=>adStates.push(s));window.adResults=[];const show=PLATFORM.showInterstitial;PLATFORM.showInterstitial=(...a)=>show(...a).then(r=>(adResults.push(r),r))")
        self.death(p);self.click(p,'continueOffer.restartButton')
        p.wait_for_function('!interstitialPending && !continueOffer.visible')
        self.assertEqual(len(self.requests(p)),1);self.assertEqual(p.evaluate('adResults.at(-1)'),'closed')
        print('ASSERT playing watchdog resolved '+json.dumps(p.evaluate('adResults.at(-1)'))+' while SDK interstitialState='+p.evaluate('bridge.advertisement.interstitialState'),flush=True)
        self.frozen(p,'playing watchdog, SDK still opened')
        p.evaluate("bridge.advertisement.interstitialState='closed'")
        self.released(p,'stuck')
        self.assertEqual(self.ad_states(p),['opened','closed'])

    def test_unsupported(self): self.failure('unsupported')
    def test_rejected(self): self.failure('reject')
    def test_failed(self): self.failure('failed')
    def test_thrown(self): self.failure('throw')

    def failure(self,outcome):
        p=self.open(outcome)
        p.evaluate('(v)=>{outcome=v;bridge.advertisement.isInterstitialSupported=v!=="unsupported"}',outcome)
        self.death(p);self.click(p,'continueOffer.restartButton');self.restarted(p)
        self.assertFalse(p.evaluate('AUDIO.isMuted()'))
        self.death(p);self.click(p,'continueOffer.menuButton')
        p.wait_for_function('menu.visible && !interstitialPending');self.snap(p,'post-ad-menu',True)
        self.assertEqual(len(self.requests(p)),0 if outcome=='unsupported' else 1)
        self.finish_case(p)

if __name__=='__main__':unittest.main()
