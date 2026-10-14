"""Regression checks for SDK download recovery and active-play measurement."""
import json
import unittest
from pathlib import Path
import test_playgama2_bridge as support


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)

    def test_failed_download_recovers_once(self):
        for failures in (1, 2, 3):
            with self.subTest(failures=failures):
                ctx = self.browser.new_context()
                requests = []
                body = 'const FAULT="normal",SAVED_LANGUAGE="en";' + support.FAKE
                def handle(route):
                    requests.append(route.request.url)
                    if len(requests) <= failures:
                        route.abort('connectionreset')
                    else:
                        route.fulfill(content_type='application/javascript', body=body)
                ctx.route(support.SDK, handle)
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(self.url + 'current/index.html')
                support.wait_for_boot(page)
                page.wait_for_timeout(1700)
                self.assertEqual(len(requests), min(failures + 1, 3))
                self.assertTrue(page.evaluate('bootComplete && runInProgress'))
                if failures < 3:
                    self.assertEqual(page.evaluate('PLATFORM.readiness.state'), 'success')
                    for event in ('initialize', 'game_ready'):
                        self.assertEqual(page.evaluate('(name)=>probe.calls.filter(c=>c.name===name).length', event), 1)
                else:
                    self.assertEqual(page.evaluate('PLATFORM.environment'), 'disabled')
                self.assertEqual(errors, [])
                ctx.close()

    def test_actual_play_clock_excludes_menu_pause_and_background_gaps(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.goto('about:blank')
        page.evaluate('window.events=[]; window.PLATFORM={track:(name,data)=>events.push({name,data})}')
        page.add_script_tag(content=(support.ROOT / 'telemetry.js').read_text())
        page.evaluate('''() => {
            TELEMETRY.frame(0, false, 'bad');
            TELEMETRY.frame(60000, false, 'bad');
            TELEMETRY.frame(60001, true, 'bad');
            for(let t=60011;t<=75001;t+=10) TELEMETRY.frame(t,true,'bad');
            TELEMETRY.frame(75002,false,'bad');
            TELEMETRY.frame(175002,true,'bad');
            for(let t=175012;t<=190002;t+=10) TELEMETRY.frame(t,true,'bad');
        }''')
        events = page.evaluate('events')
        milestones = [e['data']['seconds'] for e in events if e['name']=='active_play_milestone']
        self.assertEqual(milestones, [30])
        sample = next(e['data'] for e in events if e['name']=='performance_sample')
        self.assertEqual(sample['active_ms'], 30000)
        self.assertEqual(sample['frame_time_max_ms'], 10)
        page.evaluate('''() => {
            document.dispatchEvent(new Event('visibilitychange'));
            TELEMETRY.frame(290002,true,'bad');
            for(let t=290012;t<=320002;t+=10) TELEMETRY.frame(t,true,'bad');
            for(let t=320012;t<=350002;t+=10) TELEMETRY.frame(t,true,'bad');
        }''')
        self.assertEqual(page.evaluate("events.filter(e=>e.name==='active_play_milestone').map(e=>e.data.seconds)"), [30,60])
        (self.out/'active-clock.json').write_text(json.dumps(page.evaluate('events'),indent=2))
        ctx.close()

    def test_analytics_failure_cannot_break_game(self):
        ctx = self.browser.new_context()
        ctx.route(support.SDK, lambda r:r.fulfill(content_type='application/javascript',body=
            'const FAULT="normal",SAVED_LANGUAGE="en";'+support.FAKE+
            ';bridge.analytics={send(){throw Error("INJECTED telemetry failure")}};'))
        page=ctx.new_page(); errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(self.url+'current/index.html'); support.wait_for_boot(page)
        page.evaluate("PLATFORM.track('active_play_milestone',{seconds:30,mode:'bad'})")
        support.Playgama2BridgeTests.click_mode(self,page,'bad')
        self.assertTrue(page.evaluate('bootComplete && runInProgress && !menu.gamePaused && !continueOffer.visible && version==="bad"'))
        self.assertEqual(errors,[])
        ctx.close()

    def test_running_state_assertions_are_not_vacuous(self):
        # menu has no visible flag any more, so negating it was always true;
        # the real running-state expression must flip when the run is paused
        here, old = Path(__file__).resolve().parent, '!menu' + '.visible'
        for name in ('test_loading_recovery.py', 'test_loading_real_sdk.py', 'test_playgama2_audio.py', 'test_playgama2_boot.py'):
            self.assertNotIn(old, (here/name).read_text(), name)
        ctx = self.browser.new_context()
        ctx.route(support.SDK, lambda r:r.fulfill(content_type='application/javascript',body=
            'const FAULT="normal",SAVED_LANGUAGE="en";'+support.FAKE))
        page=ctx.new_page(); errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(self.url+'current/index.html'); support.wait_for_boot(page)
        running = 'bootComplete && runInProgress && !menu.gamePaused && !continueOffer.visible && version==="bad"'
        page.wait_for_function('bootComplete && runInProgress')
        self.assertIsNone(page.evaluate('menu' + '.visible'))
        self.assertTrue(page.evaluate(running))
        page.evaluate("emitHost('pause',true)")
        self.assertFalse(page.evaluate(running))
        self.assertTrue(page.evaluate(old + ' && bootComplete'))
        self.assertEqual(errors,[])
        ctx.close()

    def test_initial_host_pause_blocks_physics_until_released(self):
        ctx = self.browser.new_context()
        ctx.route(support.SDK, lambda r:r.fulfill(content_type='application/javascript',body=
            'const FAULT="normal",SAVED_LANGUAGE="en";'+support.FAKE+';bridge.platform.isPaused=true;'))
        page=ctx.new_page();page.goto(self.url+'current/index.html');support.wait_for_boot(page)
        support.Playgama2BridgeTests.click_mode(self,page,'bad')
        initial=page.evaluate('({x:ninja.x,y:ninja.y})')
        page.wait_for_timeout(250)
        self.assertEqual(page.evaluate('({x:ninja.x,y:ninja.y})'),initial)
        page.evaluate("emitHost('pause',false)")
        # The boot run started paused behind the host pause; once released,
        # a real click on Resume lets physics run
        page.wait_for_timeout(250)
        self.assertEqual(page.evaluate('({x:ninja.x,y:ninja.y})'),initial)
        point=page.evaluate('''() => { const b=menu.resume.background, r=canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width, y:r.y+(b.y+b.height/2)*r.height/height} }''')
        page.wait_for_function('menu.gamePaused && !unTouch')
        page.mouse.click(**point)
        page.wait_for_function('(y)=>ninja.y!==y',arg=initial['y'])
        ctx.close()
