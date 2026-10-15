"""TASK-450: browser input through camera, DPR and orientation changes."""
import hashlib
import json
import math
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, source_hashes
from perf_mobile import SEED_SCRIPT


class Task450Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-450')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        hashes['tools/test_grapple_over_input.py'] = hashlib.sha256(
            (ROOT / 'tools/test_grapple_over_input.py').read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes, browser=cls.browser.version, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, touch=False):
        context = self.browser.new_context(viewport={'width':1280, 'height':720},
                                          device_scale_factor=1, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate('''() => {
            startGame('grapple_over'); cancelAnimationFrame(game);
            TUTORIAL_HINT.press(version); TUTORIAL_HINT.advance(2500);
            window.shots=[];
            const calc=grapnel.calcSpeed.bind(grapnel);
            grapnel.calcSpeed=target=>{shots.push({...target});return calc(target)};
            window.inputState=()=>({shots:shots.length,throwed:grapnel.throwed,
                grappled:grapnel.grappled,paused:menu.gamePaused,stale:stalePress,
                held:pressHeld,vector:[grapnel.speedX,grapnel.speedY]});
            window.worldState=()=>JSON.stringify({player:[ninja.x,ninja.y],
                terrain:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points})),
                speed:grapnelSpeed,radius:MODE_DEFINITIONS.grapple_over.acquisitionRadius});
            window.aimPoint=()=>{
                const target={x:ninja.x+180,y:ninja.y-110};
                const client=canvasCoordsToViewportCoords({x:(target.x+screen.x)*scale[version],
                    y:(target.y+screen.y)*scale[version]});
                const canvasPoint=viewportCoordsToCanvasCoords(client);
                return {target,client,world:{x:canvasPoint.x/scale[version]-screen.x,
                    y:canvasPoint.y/scale[version]-screen.y},camera:[screen.x,screen.y],
                    player:[ninja.x,ninja.y],dpr:devicePixelRatio,
                    viewport:[innerWidth,innerHeight],rotated:isViewRotated(),
                    backing:[canvas.width,canvas.height],scale:scale[version],speed:grapnelSpeed};
            };
        }''')
        page.wait_for_function('!unTouch')
        self.evidence.log('BROWSER viewport=1280x720 device_scale_factor=1 has_touch=' + str(touch))
        return page

    def check_aim(self, row, fires=True):
        self.assertLessEqual(math.hypot(row['world']['x']-row['target']['x'],
                                       row['world']['y']-row['target']['y']), 1)
        if fires:
            self.assertEqual(row['resolved_target'], row['world'])
            dx = row['target']['x']-row['player'][0]
            dy = row['target']['y']-row['player'][1]
            for actual, expected in zip(row['vector'], (dx,dy)):
                self.assertAlmostEqual(actual, expected/math.hypot(dx,dy)*row['speed'], places=7)

    def test_aim_scroll_dpr_resize_rotation(self):
        page = self.open(touch=True)
        cdp = page.context.new_cdp_session(page)
        original = page.evaluate('worldState()')
        rows = []
        for name,w,h,dpr,camera in (
            ('initial',1280,720,1,[500,-300]),
            ('scroll_both_axes',1280,720,1,[300,-450]),
            ('dpr_change',1280,720,2,[300,-450]),
            ('landscape_resize',960,600,2,[300,-450]),
            ('portrait_rotation',600,960,2,[300,-450]),
            ('landscape_return',1280,720,1,[300,-450])):
            cdp.send('Emulation.setDeviceMetricsOverride',dict(width=w,height=h,
                deviceScaleFactor=dpr,mobile=False))
            page.wait_for_timeout(180)
            page.evaluate('c=>{screen.x=c[0];screen.y=c[1]}',camera)
            row = page.evaluate('aimPoint()')
            row['name'] = name
            self.evidence.log('VIEW ' + json.dumps(row))
            # Portrait is deliberately paused; validate its inverse transform
            # and blocked press, then explicitly resume after rotating back.
            if name == 'landscape_return':
                self.assertTrue(page.evaluate('menu.gamePaused'))
                page.evaluate('menu.unPause()')
            before = page.evaluate('shots.length')
            page.mouse.move(row['client']['x'],row['client']['y'])
            page.mouse.down()
            state = page.evaluate('inputState()')
            row.update(vector=state['vector'],shots_before=before,shots_after=state['shots'],
                       paused=state['paused'])
            if row['rotated']:
                self.assertTrue(state['paused'])
                self.assertFalse(state['throwed'])
                self.assertEqual(before,state['shots'])
                self.check_aim(row,False)
            else:
                row['resolved_target'] = page.evaluate('shots.at(-1)')
                self.assertEqual(state['shots'],before+1)
                self.check_aim(row)
            page.mouse.up()
            after = page.evaluate('worldState()')
            self.assertEqual(original,after)
            row['world_state_sha256'] = hashlib.sha256(after.encode()).hexdigest()
            row['world_unchanged'] = True
            rows.append(row)
        self.evidence.write('aim.json',dict(self.proof,observations=rows,
            initial_world_state_sha256=hashlib.sha256(original.encode()).hexdigest(),
            max_round_trip_error=max(math.hypot(r['world']['x']-r['target']['x'],
                r['world']['y']-r['target']['y']) for r in rows),
            terrain_player_grapple_distances_unchanged=True))
        print('PASS aim: 6 scenarios; scrolling, DPR 1/2, landscape resize, portrait pause and return; round-trip <=1; world unchanged')

    def test_input_touch_mouse_cancel_camera_ui(self):
        page = self.open(touch=True)
        cdp = page.context.new_cdp_session(page)
        point = page.evaluate('aimPoint().client')
        def touch(kind):
            cdp.send('Input.dispatchTouchEvent',{'type':kind,'touchPoints':
                [] if kind in ('touchEnd','touchCancel') else [dict(x=point['x'],y=point['y'],id=1)]})
        rows = {}
        touch('touchStart')
        rows['touch_start'] = page.evaluate('inputState()')
        self.assertEqual(rows['touch_start']['shots'],1)
        self.assertTrue(rows['touch_start']['throwed'])
        rows['camera_motion'] = page.evaluate('''() => {
            const before={vector:[grapnel.speedX,grapnel.speedY],tip:grapnel.pos[0].slice(0,2),camera:[screen.x,screen.y]};
            screen.x+=280;screen.y-=170;grapnel.move();
            return {before,after:{vector:[grapnel.speedX,grapnel.speedY],tip:grapnel.pos[0].slice(0,2),camera:[screen.x,screen.y]}};
        }''')
        motion = rows['camera_motion']
        self.assertEqual(motion['before']['vector'],motion['after']['vector'])
        for a,b,v in zip(motion['after']['tip'],motion['before']['tip'],motion['before']['vector']):
            self.assertAlmostEqual(a-b,v)
        touch('touchMove')
        touch('touchEnd')
        page.wait_for_timeout(100)
        rows['touch_release'] = page.evaluate('inputState()')
        self.assertEqual(rows['touch_release']['shots'],1)  # No compatibility mouse throw.
        self.assertFalse(rows['touch_release']['throwed'])
        touch('touchStart')
        page.evaluate('grapnel.setGrappled(true)')
        touch('touchCancel')
        rows['touch_cancel'] = page.evaluate('inputState()')
        self.assertEqual(rows['touch_cancel']['shots'],2)
        self.assertFalse(rows['touch_cancel']['grappled'])
        self.assertFalse(rows['touch_cancel']['throwed'])
        page.mouse.move(point['x'],point['y'])
        page.mouse.down()
        page.mouse.up()
        rows['mouse_release'] = page.evaluate('inputState()')
        self.assertEqual(rows['mouse_release']['shots'],3)
        self.assertFalse(rows['mouse_release']['throwed'])
        page.mouse.down()
        page.evaluate("window.dispatchEvent(new Event('blur'))")
        rows['mouse_blur'] = page.evaluate('inputState()')
        self.assertFalse(rows['mouse_blur']['throwed'])
        self.assertTrue(rows['mouse_blur']['paused'])
        page.mouse.up()
        page.evaluate('menu.unPause()')
        # Hit actual rendered HUD / pause button geometry through browser events.
        for button in ('hud','language','resume'):
            page.wait_for_function('!unTouch')
            pos = page.evaluate('''name=>{
                const r=name==='language'?LANGUAGE_BUTTON.rect():
                    (name==='hud'?menu.button:menu.resume).background;
                const s=name==='hud'?scale[version]:1;
                return canvasCoordsToViewportCoords({x:(r.x+r.width/2)*s,y:(r.y+r.height/2)*s});
            }''',button)
            page.mouse.click(pos['x'],pos['y'])
            rows[button] = page.evaluate('inputState()')
            self.assertEqual(rows[button]['shots'],4)
            self.assertFalse(rows[button]['throwed'])
        self.assertFalse(rows['resume']['paused'])
        # Existing stale-input guard requires a release before the next shot.
        page.wait_for_function('!unTouch')
        page.evaluate('stalePress=true')
        page.mouse.move(point['x'],point['y'])
        page.mouse.down()
        rows['stale_press'] = page.evaluate('inputState()')
        self.assertEqual(rows['stale_press']['shots'],4)
        page.mouse.up()
        page.mouse.down()
        rows['fresh_press'] = page.evaluate('inputState()')
        self.assertEqual(rows['fresh_press']['shots'],5)
        page.mouse.up()
        self.evidence.write('input.json',dict(self.proof,observations=rows,
            one_touch_one_throw=True,release_cancel_detaches=True,
            camera_cannot_redirect=True,ui_presses_do_not_fire=True,fresh_input_guard=True))
        print('PASS input: one touch one throw; release/cancel detach; camera cannot redirect; UI presses do not fire; fresh-input guard')
