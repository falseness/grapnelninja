"""Production mobile paths with trusted Chromium touches and SDK-boundary faults.

Device names describe viewport/DPR emulation, never physical Safari/Android tests.

The title menu is gone (TASK-364): the page boots straight into a 'bad' run
(paused while the view is portrait), 'classic' is reached by touch taps on the
HUD menu button and the pause screen's mode switch, and the death screen opens
when a game over interstitial is due (TASK-370). Runnable from the repo root or
tools/: git and source hashes resolve against ROOT.

PLAYGAMA2_EVIDENCE_DIR selects the output directory (default artifacts/TASK-395).
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
import unittest
from datetime import datetime, timezone

from browser_test_support import start_browser_test, wait_for_boot
from layout_matrix import PROBE, evaluate
import test_playgama2_bridge as support
from test_mode_switch import EXTRA

PROFILES = {'iphone-se': (375, 667, 2), 'iphone-13': (390, 844, 3), 'pixel-7': (412, 915, 2.625)}
STATE = '({score:scoreText.count[version],mode:version,x:ninja.x,y:ninja.y,time:PROGRESS.getTime(),record:scoreText.record[version],paused:menu.gamePaused,held:grapnel.throwed})'


class MobileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', support.ROOT / 'artifacts/TASK-395'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(support.ROOT, cls.addClassCleanup)
        cls.records = {}
        paths = subprocess.check_output(['git', 'ls-files'], text=True, cwd=support.ROOT).splitlines() + ['tools/test_playgama2_mobile.py']
        cls.hashes = {p: hashlib.sha256((support.ROOT / p).read_bytes()).hexdigest() for p in sorted(set(paths))
                      if not p.startswith(('artifacts/', 'screenshots/'))}
        (cls.out/'tested-source-hashes.json').write_text(json.dumps(cls.hashes, indent=2)+'\n')

    @classmethod
    def tearDownClass(cls):
        (cls.out/'mobile-events.json').write_text(json.dumps(cls.records, indent=2)+'\n')
        matrix = {name: {'kind':'Chromium emulation; not a tested physical device',
                        'browser':cls.browser.version, 'device_os_version':'unverified; no physical device connected',
                        'portrait':[w,h], 'landscape':[h,w], 'dpr':dpr,
                        'requirements':{'landscape_controls':'mobile-events.json#'+name+'/checks',
                                        'portrait_rotation_continuity':'mobile-events.json#'+name+'/rotations',
                                        'focus_background_host_pause':'mobile-events.json#'+name+'/pauses',
                                        'native_captures':'mobile-events.json#'+name+'/screens'},
                        'fullscreen':'UNVERIFIED: live hosting iframe permissions and physical browser unavailable; viewport launch/resize emulated only',
                        'native_long_press':'UNVERIFIED: physical OS callout unavailable; trusted emulated hold and cancellation of contextmenu tested'}
                  for name,(w,h,dpr) in PROFILES.items()}
        (cls.out/'mobile-matrix.json').write_text(json.dumps(matrix, indent=2)+'\n')

    def tap(self, expression, scaled=False):
        p=self.p
        p.wait_for_function('!unTouch')
        point=p.evaluate('()=>{const b='+expression+',r=canvas.getBoundingClientRect(),s='+('scale[version]' if scaled else '1')+';return {x:r.x+(b.x+b.width/2)*s*r.width/width,y:r.y+(b.y+b.height/2)*s*r.height/height}}')
        self.assertEqual(p.evaluate('p=>document.elementFromPoint(p.x,p.y).id',point),'canvas')
        p.touchscreen.tap(**point)
        self.rec['checks'].append({'control':expression,'point':point,'result':'PASS'})

    # Touch taps: HUD menu button, then the pause screen's mode switch
    def switch_on_pause(self, target):
        p=self.p
        self.tap('menu.button.background',True);p.wait_for_function('menu.gamePaused')
        self.assertEqual(p.evaluate('menu.backToMenu.text.text'),p.evaluate("I18N.t(version==='bad'?'menu.chillVersion':'menu.mainVersion')"))
        self.tap('menu.backToMenu.background')
        p.wait_for_function('t => version === t && !!ninja && runInProgress && !menu.gamePaused && !unTouch',arg=target)

    def capture(self, phase, draw=None):
        p=self.p
        entry={'phase':phase,'utc':datetime.now(timezone.utc).isoformat(),
               'viewport':p.viewport_size,'timings':{},'completed':False}
        self.rec['screens'].append(entry)

        def checkpoint():
            (self.out/'mobile-events.json').write_text(json.dumps(self.records, indent=2)+'\n')

        def timed(stage, action):
            timing={'started':datetime.now(timezone.utc).isoformat(),'status':'running'}
            entry['timings'][stage]=timing
            checkpoint()  # Preserve the active stage even if the outer budget kills the run.
            started=perf_counter()
            try:
                result=action()
                timing['status']='PASS'
                return result
            except Exception as exc:
                timing.update(status='FAIL',error=str(exc))
                raise
            finally:
                timing['duration_ms']=round((perf_counter()-started)*1000,3)
                checkpoint()

        timed('animation_frames', lambda: p.evaluate(
            'new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))'))
        # Locator.evaluate waits for attachment (not visibility). Avoid all locator
        # round trips here and sample geometry and orientation from the same DOM turn.
        entry.update(timed('dom_snapshot', lambda: p.evaluate("""() => {
            const canvas=document.querySelector('#canvas');
            const stage=document.querySelector('#stage');
            const prompt=document.querySelector('#rotate-prompt');
            if (!canvas || !stage || !prompt) throw new Error('Missing capture DOM');
            const visible=e=>{const r=e.getBoundingClientRect();
                return getComputedStyle(e).visibility==='visible' && r.width>0 && r.height>0};
            return {canvas:canvas.getBoundingClientRect().toJSON(),
                orientation:{rotate_visible:visible(prompt),stage_inert:stage.inert,
                             canvas_visible:visible(canvas)},
                prompt:prompt.innerText,
                prompt_unclipped:prompt.scrollWidth<=prompt.clientWidth &&
                                 prompt.scrollHeight<=prompt.clientHeight};
        }""")))
        timed('orientation_assertions', lambda: self.assert_capture_orientation(
            entry['orientation'], portrait=not bool(draw)))
        if draw:
            raw=timed('layout_probe', lambda: p.evaluate(PROBE,draw)); result,_=evaluate(raw,True)
            entry['layout']=result
            self.assertEqual(result['failures'],[],result)
            dom=timed('dom_bounds', lambda: p.evaluate('''()=>[...document.querySelectorAll('#mute-button,#tutorial')].filter(e=>!e.hidden).map(e=>{
                const r=e.getBoundingClientRect();return {id:e.id,rect:r.toJSON(),fits:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
                unclipped:e.scrollWidth<=e.clientWidth,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}})'''))
            entry['dom']=dom
            for d in dom: self.assertTrue(d['fits'] and d['unclipped'] and d['hit'],d)
        else:
            self.assertTrue(entry['prompt_unclipped'])
            self.assertIn('landscape',entry['prompt'])
        name=self.name+'-'+phase+'.png'
        timed('screenshot', lambda: p.screenshot(path=str(self.out/name)))
        entry['capture']={'path':name,'sha256':hashlib.sha256((self.out/name).read_bytes()).hexdigest(),'kind':'desktop Chromium device emulation'}
        entry['completed']=True
        checkpoint()

    def assert_capture_orientation(self, state, portrait):
        self.assertEqual(state['rotate_visible'], portrait, state)
        self.assertEqual(state['stage_inert'], portrait, state)
        self.assertEqual(state['canvas_visible'], not portrait, state)

    def run_profile(self,name):
        self.name=name;w,h,dpr=PROFILES[name]
        self.rec=self.records[name]={'checks':[],'screens':[],'rotations':[],'pauses':[],'started':datetime.now(timezone.utc).isoformat()}
        ctx=self.browser.new_context(viewport={'width':w,'height':h},device_scale_factor=dpr,is_mobile=True,has_touch=True,locale='en-US')
        self.addCleanup(ctx.close)
        ctx.add_init_script("window.mobileInputs=[];for(const n of ['touchstart','touchend','touchcancel','touchmove','click'])addEventListener(n,e=>mobileInputs.push({type:n,trusted:e.isTrusted,target:e.target.id||e.target.tagName,ms:performance.now()}),true)")
        ctx.route(support.SDK,lambda r:r.fulfill(content_type='application/javascript',body='const FAULT="normal",SAVED_LANGUAGE="en";'+support.FAKE+EXTRA))
        self.p=p=ctx.new_page();p.set_default_timeout(20000)
        errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
        p.goto(self.url);wait_for_boot(p)
        self.capture('portrait-launch')
        p.set_viewport_size({'width':h,'height':w});p.wait_for_timeout(250)
        # Boot run (TASK-360): a 'bad' run with the tutorial hint, no title menu.
        # The portrait launch paused it; resume with a touch tap on the pause screen.
        p.wait_for_function('bootComplete && runInProgress && !!ninja')
        self.assertEqual(p.evaluate('[version, TUTORIAL_HINT.visible, TUTORIAL_HINT.pressed, menu.gamePaused]'),['bad',True,False,True])
        self.capture('landscape-boot-pause','menu.drawPauseScreen()')
        p.locator('#mute-button').tap();self.assertTrue(p.evaluate('MUTE_BUTTON.muted'))
        p.locator('#mute-button').tap();self.assertFalse(p.evaluate('MUTE_BUTTON.muted'))
        self.rec['checks'].append({'control':'mute toggle twice','result':'PASS'})
        self.tap('menu.resume.background')
        p.wait_for_function('!menu.gamePaused && !unTouch')
        self.capture('boot-run','draw()')
        self.assertTrue(p.evaluate('TUTORIAL_HINT.visible && !TUTORIAL_HINT.pressed'))
        cd=ctx.new_cdp_session(p)
        def hold(): cd.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':h*.72,'y':w*.28}]})
        for end in ('touchEnd','touchCancel'):
            hold();self.assertTrue(p.evaluate('grapnel.throwed'))
            # The first trusted throw dismisses the tutorial hint
            self.assertTrue(p.evaluate('TUTORIAL_HINT.pressed'))
            cd.send('Input.dispatchTouchEvent',{'type':end,'touchPoints':[]})
            self.assertFalse(p.evaluate('grapnel.throwed'))
            self.rec['checks'].append({'control':end,'held_before':True,'held_after':False,'result':'PASS'})
        hold();p.wait_for_timeout(850)
        cd.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':h*.6,'y':w*.5}]})
        cd.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        self.assertEqual(p.evaluate('[scrollX,scrollY,String(getSelection())]'),[0,0,''])
        prevented=p.evaluate("!document.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}))")
        self.assertTrue(prevented)
        self.rec['checks'].append({'control':'850ms long press + swipe','scroll':[0,0],'selection':'','contextmenu_prevented':prevented,'result':'PASS'})
        self.tap('menu.button.background',True);self.assertTrue(p.evaluate('menu.gamePaused'))
        self.capture('pause','menu.drawPauseScreen()')
        # A paused session supplies exact continuity comparisons across resize.
        before=p.evaluate(STATE)
        p.set_viewport_size({'width':h-60,'height':w});p.wait_for_timeout(250)
        self.assertEqual(p.evaluate(STATE),before)
        self.capture('landscape-resize','menu.drawPauseScreen()')
        p.set_viewport_size({'width':h,'height':w});p.wait_for_timeout(250)
        self.assertEqual(p.evaluate(STATE),before)
        self.rec['resize']={'before':before,'after':p.evaluate(STATE),'result':'PASS'}
        for i in range(2):
            p.set_viewport_size({'width':w,'height':h});p.wait_for_timeout(250)
            self.capture('portrait-'+str(i))
            self.assertEqual(p.evaluate(STATE),before)
            p.set_viewport_size({'width':h,'height':w});p.wait_for_timeout(250)
            after=p.evaluate(STATE);self.assertEqual(after,before)
            self.capture('return-'+str(i),'menu.drawPauseScreen()')
            self.rec['rotations'].append({'reason':'orientation','before':before,'after':after,'result':'PASS'})
        self.tap('menu.resume.background');self.assertFalse(p.evaluate('menu.gamePaused'))
        # Rotate a running session with a held grapple; production resize must pause/release.
        hold();p.set_viewport_size({'width':w,'height':h});p.wait_for_timeout(250)
        self.assertTrue(p.evaluate('menu.gamePaused'));self.assertFalse(p.evaluate('grapnel.throwed'))
        cd.send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]})
        frozen=p.evaluate(STATE);self.capture('portrait-active')
        p.wait_for_timeout(200);self.assertEqual(p.evaluate(STATE),frozen)
        p.set_viewport_size({'width':h,'height':w});p.wait_for_timeout(250)
        self.assertEqual(p.evaluate(STATE),frozen)
        self.rec['rotations'].append({'reason':'orientation during active hold','before':frozen,'after':p.evaluate(STATE),'result':'PASS'})
        # Boundary injections: browser focus/visibility and SDK host notifications.
        for reason,trigger,restore in [
            ('focus',"dispatchEvent(new Event('blur'))","dispatchEvent(new Event('focus'))"),
            ('background',"Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))","delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'))"),
            ('host',"emitHost('pause',true)","emitHost('pause',false)")]:
            self.tap('menu.resume.background');hold();p.evaluate(trigger)
            self.assertTrue(p.evaluate('menu.gamePaused'),p.evaluate('({reason:'+json.dumps(reason)+',dead:continueOffer.visible,state:'+STATE+'})'));self.assertFalse(p.evaluate('grapnel.throwed'))
            cd.send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]})
            frozen=p.evaluate(STATE);p.wait_for_timeout(150);self.assertEqual(p.evaluate(STATE),frozen)
            p.evaluate(restore);self.assertEqual(p.evaluate(STATE),frozen)
            self.capture(reason+'-pause','menu.drawPauseScreen()')
            self.rec['pauses'].append({'reason':reason,'injection':'platform boundary; not native physical transition','before':frozen,'after':p.evaluate(STATE),'result':'PASS'})
        # Still paused after the host pause: tap the pause screen's mode switch
        self.assertEqual(p.evaluate('menu.backToMenu.text.text'),p.evaluate("I18N.t('menu.chillVersion')"))
        self.tap('menu.backToMenu.background')
        p.wait_for_function("version === 'classic' && !!ninja && runInProgress && !menu.gamePaused && !unTouch")
        hold();self.assertTrue(p.evaluate('grapnel.throwed'));cd.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        self.assertFalse(p.evaluate('grapnel.throwed'))
        self.rec['checks'].append({'control':'chill-mode touch hold/release','result':'PASS'})
        self.capture('gameplay','draw()')
        # No interstitial requested yet, so a game over ad is due and the death screen opens
        self.assertTrue(p.evaluate('PLATFORM.isInterstitialDue()'))
        p.wait_for_function('continueOffer.visible && !continueOffer.adPending',timeout=60000)
        self.capture('death','continueOffer.draw()')
        self.tap('continueOffer.restartButton.background')
        p.wait_for_function('!continueOffer.visible && !unTouch')
        # Restart resumes a live classic run (the title menu no longer exists)
        self.assertEqual(p.evaluate('[version, runInProgress, !!ninja, menu.gamePaused]'),['classic',True,True,False])
        self.switch_on_pause('bad')
        hold();self.assertTrue(p.evaluate('grapnel.throwed'));cd.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        self.assertFalse(p.evaluate('grapnel.throwed'));self.assertEqual(p.evaluate('version'),'bad')
        self.rec['checks'].append({'control':'main-mode touch hold/release','result':'PASS'})
        inputs=p.evaluate('mobileInputs');self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        self.assertEqual(errors,[])
        self.rec.update(inputs=inputs,errors=errors,verdict='PASS',finished=datetime.now(timezone.utc).isoformat())
        print('PASS profile test_'+name.replace('-','_')+': portrait/landscape; boot-run/mute/tutorial-hint/pause-switch/death/restart; both modes touch hold/release/cancel; long press/swipe; repeated rotation exact continuity; orientation/focus/background/host pause; desktop Chromium emulated captures; no browser errors',flush=True)


for name in PROFILES:
    setattr(MobileTests,'test_'+name.replace('-','_'),lambda self,n=name:self.run_profile(n))

if __name__=='__main__': unittest.main()
