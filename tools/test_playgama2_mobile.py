"""Production mobile paths with trusted Chromium touches and SDK-boundary faults.

Device names describe viewport/DPR emulation, never physical Safari/Android tests.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from datetime import datetime, timezone

from browser_test_support import start_browser_test, wait_for_boot
from layout_matrix import PROBE, evaluate
import test_playgama2_bridge as support

PROFILES = {'iphone-se': (375, 667, 2), 'iphone-13': (390, 844, 3), 'pixel-7': (412, 915, 2.625)}
STATE = '({score:scoreText.count[version],mode:version,x:ninja.x,y:ninja.y,time:PROGRESS.getTime(),record:scoreText.record[version],paused:menu.gamePaused,held:grapnel.throwed})'


class MobileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', 'artifacts/TASK-244'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(support.ROOT, cls.addClassCleanup)
        cls.records = {}
        paths = subprocess.check_output(['git', 'ls-files'], text=True).splitlines() + ['tools/test_playgama2_mobile.py']
        cls.hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(set(paths))
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

    def capture(self, phase, draw=None):
        p=self.p
        p.evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        entry={'phase':phase,'utc':datetime.now(timezone.utc).isoformat(),'viewport':p.viewport_size,
               # Portrait deliberately hides the stage; geometry must not wait for visibility.
               'canvas':p.locator('#canvas').evaluate('(e)=>e.getBoundingClientRect().toJSON()'),
               'orientation':{
                   'rotate_visible':p.locator('#rotate-prompt').is_visible(),
                   'stage_inert':p.locator('#stage').evaluate('(e)=>e.inert'),
                   'canvas_visible':p.locator('#canvas').is_visible()}}
        self.assert_capture_orientation(entry['orientation'], portrait=not bool(draw))
        if draw:
            raw=p.evaluate(PROBE,draw); result,_=evaluate(raw,True)
            entry['layout']=result
            self.assertEqual(result['failures'],[],result)
            dom=p.evaluate('''()=>[...document.querySelectorAll('#mute-button,#tutorial')].filter(e=>!e.hidden).map(e=>{
                const r=e.getBoundingClientRect();return {id:e.id,rect:r.toJSON(),fits:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
                unclipped:e.scrollWidth<=e.clientWidth,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}})''')
            entry['dom']=dom
            for d in dom: self.assertTrue(d['fits'] and d['unclipped'] and d['hit'],d)
        else:
            self.assertTrue(p.locator('#rotate-prompt').evaluate('(e)=>e.scrollWidth<=e.clientWidth && e.scrollHeight<=e.clientHeight'))
            entry['prompt']=p.locator('#rotate-prompt').inner_text()
            self.assertIn('landscape',entry['prompt'])
        name=self.name+'-'+phase+'.png'
        p.screenshot(path=str(self.out/name))
        entry['capture']={'path':name,'sha256':hashlib.sha256((self.out/name).read_bytes()).hexdigest(),'native':True}
        self.rec['screens'].append(entry)

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
        ctx.route(support.SDK,lambda r:r.fulfill(content_type='application/javascript',body='const FAULT="normal",SAVED_LANGUAGE="en";'+support.FAKE))
        self.p=p=ctx.new_page();p.set_default_timeout(20000)
        errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
        p.goto(self.url);wait_for_boot(p)
        self.capture('portrait-launch')
        p.set_viewport_size({'width':h,'height':w});p.wait_for_timeout(250)
        self.capture('landscape-menu','menu.draw()')
        p.locator('#mute-button').tap();self.assertTrue(p.evaluate('MUTE_BUTTON.muted'))
        p.locator('#mute-button').tap();self.assertFalse(p.evaluate('MUTE_BUTTON.muted'))
        self.rec['checks'].append({'control':'mute toggle twice','result':'PASS'})
        self.tap('menu.badVersionButton.background')
        p.wait_for_function('!menu.visible && !unTouch')
        self.capture('tutorial','draw()')
        p.locator('#tutorial button').tap();self.assertTrue(p.evaluate('TUTORIAL.element.hidden && PROGRESS.getTutorialDone()'))
        self.rec['checks'].append({'control':'tutorial dismiss','result':'PASS'})
        cd=ctx.new_cdp_session(p)
        def hold(): cd.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':h*.72,'y':w*.28}]})
        for end in ('touchEnd','touchCancel'):
            hold();self.assertTrue(p.evaluate('grapnel.throwed'))
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
        self.tap('menu.backToMenu.background');p.wait_for_function('menu.visible')
        self.tap('menu.classicVersionButton.background');p.wait_for_function('!menu.visible && !unTouch')
        hold();self.assertTrue(p.evaluate('grapnel.throwed'));cd.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        self.assertFalse(p.evaluate('grapnel.throwed'))
        self.rec['checks'].append({'control':'chill-mode touch hold/release','result':'PASS'})
        self.capture('gameplay','draw()')
        p.wait_for_function('continueOffer.visible',timeout=60000)
        self.capture('death','continueOffer.draw()')
        self.tap('continueOffer.restartButton.background')
        p.wait_for_function('!continueOffer.visible && !unTouch')
        self.assertFalse(p.evaluate('menu.visible'))
        self.tap('menu.button.background',True);self.tap('menu.backToMenu.background')
        p.wait_for_function('menu.visible')
        self.tap('menu.badVersionButton.background');p.wait_for_function('!menu.visible && !unTouch')
        hold();self.assertTrue(p.evaluate('grapnel.throwed'));cd.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        self.assertFalse(p.evaluate('grapnel.throwed'));self.assertEqual(p.evaluate('version'),'bad')
        self.rec['checks'].append({'control':'main-mode touch hold/release','result':'PASS'})
        inputs=p.evaluate('mobileInputs');self.assertTrue(inputs and all(e['trusted'] for e in inputs))
        self.assertEqual(errors,[])
        self.rec.update(inputs=inputs,errors=errors,verdict='PASS',finished=datetime.now(timezone.utc).isoformat())
        print('PASS '+name+': portrait/landscape; menu/mute/tutorial/death/restart; both modes touch hold/release/cancel; long press/swipe; repeated rotation exact continuity; orientation/focus/background/host pause; native captures; no browser errors',flush=True)


for name in PROFILES:
    setattr(MobileTests,'test_'+name.replace('-','_'),lambda self,n=name:self.run_profile(n))

if __name__=='__main__': unittest.main()
