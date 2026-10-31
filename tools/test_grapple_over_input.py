"""TASK-450/494: browser input through camera, DPR and orientation changes; real phone touch."""
import hashlib
import json
import math
import shutil
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
            // Climbs (re)start paused since 97ea9d0 TASK-458; the press must reach play.
            startGame('grapple_over'); menu.unPause(); cancelAnimationFrame(game);
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
                // Mouse/touch client coordinates are whole pixels; since the 0.25
                // camera (c2a6743 TASK-688) a pixel spans several world units, so
                // shift the camera until the target sits exactly on a whole pixel.
                const raw=canvasCoordsToViewportCoords({x:(target.x+screen.x)*scale[version],
                    y:(target.y+screen.y)*scale[version]});
                const client={x:Math.round(raw.x),y:Math.round(raw.y)};
                const snap=viewportCoordsToCanvasCoords(client);
                screen.x=snap.x/scale[version]-target.x;screen.y=snap.y/scale[version]-target.y;
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
        # Since 97ea9d0 TASK-458 a Grapple Over pause keeps the shot (pauseRun no
        # longer detaches it) and a release under the pause menu is not owned.
        self.assertEqual(rows['mouse_blur']['shots'],4)
        self.assertTrue(rows['mouse_blur']['throwed'])
        self.assertTrue(rows['mouse_blur']['paused'])
        page.mouse.up()
        rows['paused_release'] = page.evaluate('inputState()')
        self.assertTrue(rows['paused_release']['throwed'])
        page.evaluate('menu.unPause();grapnel.endShot()')
        # Hit actual rendered HUD / pause button geometry through browser events.
        for button in ('hud','language','resume'):
            page.wait_for_function('!unTouch')
            # Grapple Over pauses into the climb menu (f016357 TASK-460), whose
            # first button is resume; menu.resume is only drawn in classic/bad.
            pos = page.evaluate('''name=>{
                const r=name==='language'?LANGUAGE_BUTTON.rect():
                    (name==='hud'?menu.button:CLIMB_UI.buttons[0]).background;
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


class Task494Tests(unittest.TestCase):
    """TASK-494: genuine browser touch on phones and live viewport changes.

    test_03 proves the touch cancel path on the legacy v3 S01 hoist; test_04 changes the viewport live and proves the
    world is the same. Every viewport only moves the camera. test_01/test_02 (touch replays of the legacy v3 S01..S08
    nominal routes) were retired by TASK-834: see artifacts/TASK-834/retired.md.
    """
    PHONE = dict(width=844, height=390)
    WORLD = '''() => JSON.stringify({elements:floors[0].elements.map(e=>({id:e.id,x:e.x,y:e.y,points:e.points,role:e.surfaceRole})),
        player:[ninja.x,ninja.y,ninja.radius],gravity:GRAVITY,pull:grappleSpeed,throw:grapnelSpeed,
        range:grappleOverAcquisitionRadius(),mode:MODE_DEFINITIONS.grapple_over})'''

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        cls.evidence = EvidenceWriter('TASK-494')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.hashes = hashes()
        for name in ('tools/test_grapple_over_input.py', 'tools/test_grapple_over_sections.py', 'tools/grapple_over_verify.py',
                     'tools/grapple_over_injector.js', 'tools/grapple_over_support.py'):
            cls.hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'], cwd=ROOT, text=True).splitlines(),
            browser=cls.browser.version, seed=1, hz=60, source_hashes=cls.hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))
        cls.drivers = {}

    @classmethod
    def driver(cls, suite):
        """An instance of a section tolerance suite sharing this browser, with TASK-494 evidence."""
        import test_grapple_over_sections as sections
        if suite not in cls.drivers:
            base = getattr(sections, suite)
            sub = type('Phone'+suite, (base,), dict(browser=cls.browser, url=cls.url, proof=cls.proof,
                evidence=EvidenceWriter('TASK-494'), __module__=base.__module__))
            cls.drivers[suite] = sub('test_01_tolerance_matrix')
        return cls.drivers[suite]

    def test_03_touch_cancel(self):
        """touchcancel while grappled detaches without a throw; the next touchstart throws exactly once."""
        context = self.browser.new_context(viewport=self.PHONE, device_scale_factor=2, has_touch=True)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script(SEED_SCRIPT % 1)
        # The hoist is a legacy v3 S01 point: the normal start loads the imported level since ba5ca11 TASK-650.
        page.goto(self.url + '?grappleFixture=legacy-v3'); wait_for_boot(page)
        page.evaluate('''() => {cancelAnimationFrame(game); window.requestAnimationFrame=()=>0; startGame('grapple_over'); CLIMB_UI.restart();
            window.domEvents=[]; window.shots=0;
            for (const t of ['touchstart','touchend','touchcancel','mousedown','mouseup','click'])
                document.addEventListener(t, e=>domEvents.push({type:t, trusted:e.isTrusted}), true);
            const aim=grapnel.setAim.bind(grapnel); grapnel.setAim=t=>{shots++; return aim(t)};
            window.st=()=>({shots, throwed:grapnel.throwed, grappled:grapnel.isGrappled(), paused:menu.gamePaused})}''')
        page.wait_for_function('!unTouch')
        cdp = context.new_cdp_session(page)
        hoist = self.driver('Task549Tests').SEGMENTS[0][0][2:]
        def touch(kind):
            p = page.evaluate('w=>canvasCoordsToViewportCoords({x:(w.x+screen.x)*scale[version],y:(w.y+screen.y)*scale[version]})',
                              dict(x=hoist[0], y=hoist[1]))
            cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [] if kind != 'touchStart' else [dict(x=p['x'], y=p['y'], id=1)]})
            return p
        rows = {}
        rows['client'] = touch('touchStart')
        rows['after_touchstart'] = page.evaluate('st()')
        for _ in range(120):
            page.evaluate('physics()')
            if page.evaluate('grapnel.isGrappled()'): break
        rows['grappled'] = page.evaluate('st()')
        self.assertTrue(rows['grappled']['grappled'])
        touch('touchCancel')
        rows['after_touchcancel'] = page.evaluate('st()')
        self.assertEqual(rows['after_touchcancel']['shots'], 1)
        self.assertFalse(rows['after_touchcancel']['grappled'])
        self.assertFalse(rows['after_touchcancel']['throwed'])
        for _ in range(30): page.evaluate('physics()')
        touch('touchStart')
        rows['second_touchstart'] = page.evaluate('st()')
        touch('touchEnd')
        rows['after_touchend'] = page.evaluate('st()')
        self.assertEqual(rows['second_touchstart']['shots'], 2)
        self.assertEqual(rows['after_touchend']['shots'], 2)
        self.assertFalse(rows['after_touchend']['throwed'])
        dom = page.evaluate('domEvents')
        self.assertEqual([e['type'] for e in dom], ['touchstart','touchcancel','touchstart','touchend'])
        self.assertTrue(all(e['trusted'] for e in dom))
        self.assertEqual(errors, [])
        type(self).cancel = dict(viewport=self.PHONE, device_scale_factor=2, target_world=hoist, dom_events=dom, states=rows,
            throws=2, touchstarts=2, ghost_throws=0, double_throws=0, cancel_detaches=True, compat_mouse_events=0)
        self.write_touch()
        print('PASS touchcancel: grappled hoist detached by touchcancel with no throw; DOM events', [e['type'] for e in dom], flush=True)

    def write_touch(self):
        self.evidence.write('touch.json', dict(self.proof, phone_viewport=self.PHONE,
            touchcancel=getattr(type(self), 'cancel', None)))

    def snapshot_view(self, page, cdp, name):
        """World hash, HUD/control boxes and range ring of the current frame, plus a screenshot."""
        row = page.evaluate('''() => {LAYOUT_PROBE.boxes=[]; draw(); const boxes=LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes=null;
            const css=getCanvasCssRect(), k=css.width/width*scale[version];
            return {boxes, canvas:{x:css.left??css.x, y:css.top??css.y, width:css.width, height:css.height},
                viewport:[innerWidth,innerHeight], dpr:devicePixelRatio, backing:[canvas.width,canvas.height],
                resolution:typeof BACKDROP!='undefined'?BACKDROP.resolution:1,
                logical:[width,height], rotated:isViewRotated(), paused:menu.gamePaused, touchFirst:isTouchFirstDevice(),
                ring:{x:(ninja.x+screen.x)*css.width/width*scale[version], y:(ninja.y+screen.y)*css.height/height*scale[version],
                      r:grappleOverAcquisitionRadius()*k}}}''')
        world = page.evaluate(self.WORLD)
        row['name'] = name
        row['world_sha256'] = hashlib.sha256(world.encode()).hexdigest()
        c = row['canvas']
        clipped = [b['name'] for b in row['boxes'] if b['kind'] in ('button','text') and not row['paused']
                   and (b['x'] < -0.5 or b['y'] < -0.5 or b['x']+b['width'] > c['width']+0.5 or b['y']+b['height'] > c['height']+0.5)]
        row['clipped'] = clipped
        buttons = [b for b in row['boxes'] if b['kind'] == 'button']
        row['buttons'] = [dict(name=b['name'], width=round(b['width'],1), height=round(b['height'],1)) for b in buttons]
        row['min_button_css'] = min((min(b['width'], b['height']) for b in buttons), default=None)
        ring = row['ring']
        inside = sum(1 for i in range(360) if 0 <= ring['x']+ring['r']*math.cos(i*math.pi/180) <= c['width']
                     and 0 <= ring['y']+ring['r']*math.sin(i*math.pi/180) <= c['height'])
        row['ring_visible_fraction'] = inside/360
        row['player_on_screen'] = 0 <= ring['x'] <= c['width'] and 0 <= ring['y'] <= c['height']
        row['hud_text'] = [b['name'] for b in row['boxes'] if b['kind'] == 'text'][:6]
        # CDP capture: page.screenshot() would reset the emulated metrics to the context viewport.
        import base64
        shot = cdp.send('Page.captureScreenshot', dict(format='png'))
        self.evidence.path('screenshots/%s.png' % name).write_bytes(base64.b64decode(shot['data']))
        self.assertEqual(page.evaluate('[innerWidth,innerHeight,devicePixelRatio]'), row['viewport']+[row['dpr']], name)
        row['screenshot'] = 'screenshots/%s.png' % name
        del row['boxes']
        return row, world

    def open_view(self, viewport, dpr, touch):
        context = self.browser.new_context(viewport=viewport, device_scale_factor=dpr, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url); wait_for_boot(page)
        page.evaluate("cancelAnimationFrame(game); window.requestAnimationFrame=()=>0; startGame('grapple_over'); CLIMB_UI.restart();"
                      " window.shots=0; const aim=grapnel.setAim.bind(grapnel); grapnel.setAim=t=>{shots++; return aim(t)}; 0")
        page.wait_for_function('!unTouch')
        # A mid-climb pose so the range ring and HUD are judged over the mountain, not the base: standing on
        # platform P41 of the shipped imported level (ba5ca11 TASK-650). The old pose (the legacy v3 S05 start
        # chained from the S01..S04 replays) is gone with that level.
        page.evaluate('''() => {const e=floors[0].byId.get('P41-body0'), b=getElementBounds(e);
            ninja.x=(b.left+b.right)/2; ninja.y=b.top-ninja.radius-1; ninja.speedX=ninja.speedY=0;
            screen.trackGrappleOver(true); draw()}''')
        return page, context.new_cdp_session(page)

    def test_04_viewports_resize_portrait(self):
        rows, worlds = [], set()
        def check_backing(row):
            # The backing store follows the live DPR (capped at 2 on touch), also after DPR-only changes.
            dpr = (min(row['dpr'], 2) if row['touchFirst'] else row['dpr']) * row['resolution']
            row['expected_backing'] = [max(1, math.floor(row['canvas'][k]*dpr + 0.5)) for k in ('width', 'height')]
            self.assertEqual(row['backing'], row['expected_backing'], row['name'])
        def check(row, world, touch):
            worlds.add(world)
            self.assertEqual(row['clipped'], [], row['name'])
            self.assertTrue(row['player_on_screen'], row['name'])
            self.assertGreaterEqual(row['ring_visible_fraction'], 0.25, row['name'])
            self.assertTrue(row['hud_text'], row['name'])
            if touch: self.assertGreaterEqual(round(row['min_button_css'], 3), 44, row['name'])
            check_backing(row)
            rows.append(row)
            self.evidence.log('VIEW %s viewport=%s dpr=%s touch=%s backing=%s logical=%s' % (row['name'], row['viewport'], row['dpr'],
                              touch, row['backing'], row['logical']))
        # Desktop: live resize through 1280x720 / 960x720 at DPR 1 and 2 in one page.
        page, cdp = self.open_view(dict(width=1280, height=720), 1, False)
        for w, h, dpr in ((1280,720,1), (960,720,1), (960,720,2), (1280,720,2), (1280,720,1)):
            cdp.send('Emulation.setDeviceMetricsOverride', dict(width=w, height=h, deviceScaleFactor=dpr, mobile=False))
            page.wait_for_timeout(200)
            row, world = self.snapshot_view(page, cdp, 'desktop-%dx%d-dpr%d' % (w, h, dpr))
            self.assertEqual(row['viewport'], [w, h]); self.assertEqual(row['dpr'], dpr)
            check(row, world, False)
        # Phone: 844x390 / 667x375 at DPR 1 and 2, then live portrait (paused) and back (still paused until Resume).
        page, cdp = self.open_view(self.PHONE, 2, True)
        for w, h, dpr in ((844,390,2), (667,375,2), (667,375,1), (844,390,1), (844,390,2)):
            cdp.send('Emulation.setDeviceMetricsOverride', dict(width=w, height=h, deviceScaleFactor=dpr, mobile=False))
            page.wait_for_timeout(200)
            row, world = self.snapshot_view(page, cdp, 'phone-%dx%d-dpr%d' % (w, h, dpr))
            self.assertTrue(row['touchFirst']); self.assertFalse(row['paused'])
            check(row, world, True)
        def tap(name):
            # Grapple Over's pause menu is the climb menu (f016357 TASK-460); its first button resumes.
            p = page.evaluate('''name => {const r=name==='resume'?CLIMB_UI.buttons[0].background:menu.button.background, s=name==='resume'?1:scale[version];
                return canvasCoordsToViewportCoords({x:(r.x+r.width/2)*s,y:(r.y+r.height/2)*s})}''', name)
            cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[dict(x=p['x'], y=p['y'], id=1)]})
            cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
            page.wait_for_timeout(100)
            return p
        shots = page.evaluate('shots')
        cdp.send('Emulation.setDeviceMetricsOverride', dict(width=390, height=844, deviceScaleFactor=2, mobile=False))
        page.wait_for_timeout(250)
        row, world = self.snapshot_view(page, cdp, 'phone-portrait-390x844-dpr2')
        self.assertTrue(row['rotated']); self.assertTrue(row['paused'])
        check_backing(row)
        worlds.add(world); rows.append(row)
        page.wait_for_function('!unTouch')
        row['resume_tap_client'] = tap('resume')
        row['paused_after_resume_tap'] = page.evaluate('menu.gamePaused')
        self.assertTrue(row['paused_after_resume_tap'])  # Resume is blocked while the phone is upright.
        cdp.send('Emulation.setDeviceMetricsOverride', dict(width=844, height=390, deviceScaleFactor=2, mobile=False))
        page.wait_for_timeout(250)
        row, world = self.snapshot_view(page, cdp, 'phone-landscape-return-844x390-dpr2-paused')
        self.assertFalse(row['rotated']); self.assertTrue(row['paused'])
        check_backing(row)
        worlds.add(world); rows.append(row)
        page.wait_for_function('!unTouch')
        row['resume_tap_client'] = tap('resume')
        row['paused_after_resume_tap'] = page.evaluate('menu.gamePaused')
        self.assertFalse(row['paused_after_resume_tap'])
        self.assertEqual(page.evaluate('shots'), shots)  # The Resume tap is not a throw.
        row, world = self.snapshot_view(page, cdp, 'phone-resumed-844x390-dpr2')
        check(row, world, True)
        self.assertEqual(len(worlds), 1)
        self.evidence.write('viewports.json', dict(self.proof, pose='real S05 start (S04 v3 exit settled pose, labeled placement)',
            identical_world=len(worlds) == 1, world_sha256=rows[0]['world_sha256'], world=json.loads(next(iter(worlds))),
            views=rows, portrait_pause=dict(paused_on_rotate=True, resume_blocked_upright=True, resume_required_after_return=True,
                                            resumed_by_touch_tap=True),
            min_touch_button_css=min(r['min_button_css'] for r in rows if r['touchFirst'] and r['min_button_css'] is not None)))
        print('PASS viewports: %d views (1280x720/960x720 DPR 1/2 live resize, 844x390/667x375 DPR 1/2, portrait pause, Resume tap), '
              'one world hash %s, no clipped controls, touch buttons >= 44 CSS px' % (len(rows), rows[0]['world_sha256'][:12]), flush=True)

    def test_05_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: runtime and harness match the tested worktree', flush=True)
