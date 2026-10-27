"""TASK-445 internal third-mode initialization and fixed climb proof."""
import hashlib
import json
import math
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, STATE, source_hashes, step
from perf_mobile import SEED_SCRIPT


class Task445Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-445')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_modes.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for helper in ('tools/game_harness.py', 'tools/game_test_support.py'):
            hashes[helper] = hashlib.sha256((ROOT / helper).read_bytes()).hexdigest()
        cls.proof = {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=ROOT, text=True).strip(), 'source_hashes': hashes,
            'browser': cls.browser.version, 'viewports': [[1280, 720], [960, 720]],
            'device_scale_factor': 1, 'seed': 1, 'modes': {},
            'baseline_path': 'artifacts/TASK-444/baseline.json'}
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('modes.json', cls.proof)

    def open(self, mode, width=1280):
        context = self.browser.new_context(viewport={'width': width, 'height': 720},
                                           device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate(SEED_SCRIPT % 1)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page, errors

    def test_three_modes_and_baseline_traces(self):
        baseline = json.loads((ROOT / self.proof['baseline_path']).read_text())
        for mode in ('classic', 'bad', 'grapple_over'):
            with self.subTest(mode=mode):
                page, errors = self.open(mode)
                initial = page.evaluate(STATE)
                state = page.evaluate('''() => ({player:[ninja.x,ninja.y,ninja.radius],
                    camera:[screen.x,screen.y,screen.borderX,scale[version]],
                    hud:[scoreText.x,scoreText.y,scoreText.fontSize,
                         scoreText.count[version],scoreText.record[version]],
                    constants:{gravity:GRAVITY,pull:grappleSpeed,throwSpeed:grapnelSpeed,
                               cyclesPerTick,physicsStepMs,gameplay:GAMEPLAY},
                    definition:MODE_DEFINITIONS[version]})''')
                for key in ('player', 'camera', 'hud'):
                    self.assertTrue(all(isinstance(v, (int, float)) and math.isfinite(v)
                                        for v in state[key]), (mode, key, state[key]))
                self.assertEqual(initial['radius'], 10.8)
                self.assertEqual(state['constants'], baseline['modes']['bad']['constants'])
                trace = step(page, 12)
                if mode != 'grapple_over':
                    self.assertEqual(initial, baseline['modes'][mode]['initial'])
                    self.assertEqual(trace, baseline['modes'][mode]['movement_trace'])
                else:
                    self.assertEqual(state['definition']['cameraScale'], 0.75)
                    self.assertEqual(state['definition']['acquisitionRadius'], 540)
                page.evaluate('draw()')
                self.assertEqual(errors, [])
                self.proof['modes'][mode] = dict(state, initial=initial, movement_trace=trace,
                    finite=True, browser_errors=errors, baseline_trace_equal=mode != 'grapple_over')
                print(f'PASS {mode}: finite player/camera/HUD; browser_errors=0; '
                      f'baseline_trace_equal={mode != "grapple_over"}')

    def test_fixture_geometry_and_rendering(self):
        observations = []
        for width in (1280, 960):
            page, errors = self.open('grapple_over', width)
            geometry = page.evaluate('''() => floors.map(f => f.elements.map(e =>
                ({x:e.x,y:e.y,points:e.points,fill:e.fill,stroke:e.stroke})))''')
            self.assertEqual(len(geometry[0]), 4)
            self.assertEqual([(e['x'], e['y']) for e in geometry[0]],
                             [(120,1100),(600,800),(240,500),(650,200)])
            self.assertEqual([e['points'][2] for e in geometry[0]],
                             [dict(x=w,y=h) for w,h in [(1000,60),(300,40),(280,40),(300,40)]])
            page.evaluate('draw()')
            page.screenshot(path=str(self.evidence.path('fixture.png' if width == 1280
                                                     else 'fixture-960.png')))
            self.assertEqual(errors, [])
            observations.append({'viewport': [width,720], 'geometry': geometry,
                                 'browser_errors': errors})
        self.assertEqual(observations[0]['geometry'], observations[1]['geometry'])
        self.proof['fixture'] = {'observations': observations, 'identical_geometry': True,
                                'rendered_with_existing_trampolines': True}
        print('PASS fixture: 4 existing neon Trampolines; identical geometry/dimensions at 1280x720 and 960x720')


class Task459Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-459')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_modes.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for helper in ('tools/game_harness.py', 'tools/game_test_support.py'):
            hashes[helper] = hashlib.sha256((ROOT / helper).read_bytes()).hexdigest()
        cls.proof = {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=ROOT, text=True).strip(), 'source_hashes': hashes,
            'browser': cls.browser.version, 'viewports': [[800,450],[667,375]],
            'device_scale_factor': 1, 'has_touch': True, 'runs': []}
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('navigation.json', cls.proof)

    def open(self, viewport):
        context = self.browser.new_context(viewport=dict(zip(('width','height'),viewport)),
                                           device_scale_factor=1, has_touch=True)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        def instrument(route):
            response = route.fetch()
            body = response.text().replace('            boot()\n', '''            window.lifecycle459 = []
            const original459 = PLATFORM.sendLifecycle.bind(PLATFORM)
            PLATFORM.sendLifecycle = (name, data) => {
                lifecycle459.push({name, data}); return original459(name, data)
            }
            boot()
''', 1)
            route.fulfill(response=response, body=body)
        page.route(self.url, instrument)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate('cancelAnimationFrame(game)')
        return page

    def state(self, page):
        return page.evaluate('''() => ({mode:version, paused:menu.gamePaused,
            runInProgress, climb:version==='grapple_over'?captureClimbState():null,
            score:scoreText.count[version], lifecycle:lifecycle459.slice()})''')

    def menu_boxes(self, page):
        return page.evaluate('''() => {
            cancelAnimationFrame(game);
            if (!menu.gamePaused) menu.startPause();
            draw(); LAYOUT_PROBE.boxes=[]; menu.drawPauseScreen();
            const boxes=LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes=null; return boxes;
        }''')

    def tap(self, page, box):
        rect = page.locator('#canvas').bounding_box()
        page.touchscreen.tap(rect['x']+box['x']+box['width']/2,
                             rect['y']+box['y']+box['height']/2)
        page.evaluate('cancelAnimationFrame(game)')

    def test_boot_transitions_and_localized_touch_layout(self):
        modes = ['grapple_over','bad','classic','grapple_over','classic','bad','grapple_over']
        for viewport in self.proof['viewports']:
            page = self.open(viewport)
            fresh = self.state(page)
            self.assertEqual(fresh['mode'], 'grapple_over')
            self.assertFalse(fresh['paused'])
            self.assertEqual([x['name'] for x in fresh['lifecycle']], ['level_started'])
            page.evaluate('ninja.x=1111; ninja.y=777; ninja.speedY=2; menu.startPause()')
            saved = page.evaluate('captureClimbState()')
            transitions = []
            for source, target in zip(modes, modes[1:]):
                boxes = self.menu_boxes(page)
                label = page.evaluate('m=>I18N.t("mode."+m)', target)
                button = next(b for b in boxes if b['kind']=='button' and b['name']==label)
                before = len(page.evaluate('lifecycle459'))
                self.tap(page, button)
                after = self.state(page)
                self.assertEqual(after['mode'], target)
                calls = after['lifecycle'][before:]
                self.assertEqual([c['name'] for c in calls],
                    ['level_failed','level_started'] + (['level_paused'] if target=='grapple_over' else []))
                self.assertEqual(calls[0]['data']['world'], source)
                self.assertEqual(calls[1]['data']['world'], target)
                self.assertEqual(after['paused'], target=='grapple_over')
                if target=='grapple_over':
                    self.assertEqual(after['climb'], saved)
                else:
                    self.assertEqual(after['score'], 0)
                transitions.append({'from':source,'to':target,'after':after,'calls':calls,
                                    'restore_or_fresh_pass':True,'single_start_pass':True})
            layouts = []
            for lang in ('en','ru'):
                page.evaluate('lang=>setLanguage(lang)',lang)
                boxes = self.menu_boxes(page)
                buttons = [b for b in boxes if b['kind']=='button']
                self.assertEqual(len(buttons), 7)  # resume, restart, two modes, grapnel toggle (TASK-719), FPS, language
                for i,b in enumerate(buttons):
                    self.assertGreaterEqual(b['width']+1e-6,44)
                    self.assertGreaterEqual(b['height']+1e-6,44)
                    self.assertGreaterEqual(b['x'],0)
                    self.assertGreaterEqual(b['y'],0)
                    self.assertLessEqual(b['x']+b['width'],viewport[0]+1)
                    self.assertLessEqual(b['y']+b['height'],viewport[1]+1)
                    for other in buttons[i+1:]:
                        self.assertFalse(b['x']<other['x']+other['width'] and other['x']<b['x']+b['width']
                            and b['y']<other['y']+other['height'] and other['y']<b['y']+b['height'])
                    texts = [t for t in boxes if t['kind']=='text' and t['name']==b['name']]
                    for t in texts:
                        self.assertGreaterEqual(t['x'], b['x'])
                        self.assertLessEqual(t['x']+t['width'], b['x']+b['width'])
                        self.assertGreaterEqual(t['y'], b['y'])
                        self.assertLessEqual(t['y']+t['height'], b['y']+b['height'])
                name = f'menu-{lang}.png' if viewport[0]==667 else f'menu-{lang}-800.png'
                page.screenshot(path=str(self.evidence.path(name)))
                # Same-mode selection must not start or resume a run.
                label=page.evaluate('I18N.t("mode.grapple_over")')
                before=self.state(page)
                self.tap(page,next(b for b in buttons if b['name']==label))
                self.assertEqual(self.state(page),before)
                layouts.append({'language':lang,'boxes':boxes,'screenshot':name,
                    'touch_size_bounds_no_overlap_pass':True,'labels_fit_pass':True,
                    'same_mode_no_start_pass':True})
            page.evaluate('PROGRESS.flushClimb(); PROGRESS.flush()')
            page.wait_for_function("localStorage.getItem('grapnelninja.grappleOver') !== null")
            page.reload()
            wait_for_boot(page)
            page.evaluate('cancelAnimationFrame(game)')
            restored = self.state(page)
            self.assertEqual(restored['mode'],'grapple_over')
            self.assertTrue(restored['paused'])
            self.assertEqual(restored['climb'],saved)
            self.assertEqual([c['name'] for c in restored['lifecycle']],['level_started','level_paused'])
            self.proof['runs'].append({'viewport':viewport,'fresh_boot':fresh,'saved_boot':restored,
                'saved_state':saved,'transitions':transitions,'layouts':layouts,
                'fresh_and_saved_boot_pass':True})
            print(f'PASS {viewport}: fresh/saved boot; all 6 directed transitions; single lifecycle starts; en/ru labels fit; touch targets >=44; no overlaps')

    def test_shared_harness_explicit_mode_selection(self):
        from browser_test_support import wait_for_boot_run
        from game_harness import switch_mode
        page = self.open([800,450])
        wait_for_boot_run(page, mode='bad')
        self.assertEqual(page.evaluate('version'), 'bad')
        switch_mode(page, 'classic')
        self.assertEqual(page.evaluate('version'), 'classic')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        self.proof['shared_harness'] = {'requested_modes':['bad','classic'],
            'lifecycle':page.evaluate('lifecycle459'), 'explicit_selection_pass':True}
        print('PASS shared boot wait and mode selector explicitly select bad/classic from Grapple Over')


class Task460Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-460')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_modes.py', 'tools/game_harness.py', 'tools/game_test_support.py'):
            hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = {'revision': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
                     'source_hashes':hashes, 'browser':cls.browser.version,
                     'viewports':[[800,450],[667,375]], 'device_scale_factor':1, 'has_touch':True, 'runs':[]}
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('flow.json', cls.proof)

    def test_climb_flow_and_localized_layout(self):
        for viewport, lang in (([800,450],'en'),([667,375],'ru')):
            context = self.browser.new_context(viewport=dict(zip(('width','height'),viewport)), has_touch=True)
            self.addCleanup(context.close)
            page = context.new_page()
            errors=[]
            page.on('pageerror', lambda e: errors.append(str(e)))
            def instrument(route):
                response=route.fetch()
                body=response.text().replace('            boot()\n', '''
            window.events460=[]
            PLATFORM.sendLifecycle=(name,data)=>{events460.push({name,data});return Promise.resolve()}
            GRAPPLE_OVER_LEVEL.finish={left:1500,right:1600,top:0,bottom:100}
            GRAPPLE_OVER_LEVEL.movers=[{id:'test-mover',element:'right-step',axis:'x',min:600,max:800,periodMs:2000,phase:0}]
            boot()
''',1)
                route.fulfill(response=response,body=body)
            page.route(self.url,instrument)
            page.goto(self.url)
            wait_for_boot(page)
            page.evaluate('cancelAnimationFrame(game); window.requestAnimationFrame=()=>0')
            page.evaluate('lang=>setLanguage(lang)',lang)
            page.evaluate('CLIMB_UI.restart(); cancelAnimationFrame(game)')
            base=page.evaluate('captureClimbState()')
            page.evaluate('ninja.y=500; physics()')
            high=page.evaluate('captureClimbState()')
            page.evaluate('ninja.y=900; physics(); draw()')
            low=page.evaluate('captureClimbState()')
            self.assertLess(low['stats']['currentHeight'],high['stats']['currentHeight'])
            self.assertEqual(low['stats']['maxHeight'],high['stats']['maxHeight'])
            self.assertGreater(low['player']['y'],high['player']['y'])
            hud_boxes=page.evaluate('''() => {LAYOUT_PROBE.boxes=[];draw();const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;return b}''')
            hud_text=[b for b in hud_boxes if b['kind']=='text']
            self.assertGreaterEqual(len(hud_text),4)
            for b in hud_text:
                self.assertGreaterEqual(b['fontPx'],12-1e-6)
                self.assertGreaterEqual(b['x'],0)
                self.assertLessEqual(b['x']+b['width'],viewport[0])
            page.screenshot(path=str(self.evidence.path('hud.png' if lang=='en' else 'hud-ru.png')))
            page.evaluate('menu.startPause()')
            paused=page.evaluate('captureClimbState()')
            page.wait_for_timeout(150)
            page.evaluate('for(let i=0;i<20;i++) physics()')
            self.assertEqual(page.evaluate('captureClimbState()'),paused)
            def tap(key):
                # Menu taps start the real input debounce in events.js. Wait for
                # it to expire before sending another touch, even with RAF frozen.
                page.wait_for_function('!unTouch')
                boxes=page.evaluate('''() => {LAYOUT_PROBE.boxes=[]; menu.drawPauseScreen();
                    const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;return b}''')
                label=page.evaluate('k=>I18N.t(k)',key)
                box=next(b for b in boxes if b['kind']=='button' and b['name']==label)
                rect=page.locator('#canvas').bounding_box()
                page.touchscreen.tap(rect['x']+box['x']+box['width']/2,rect['y']+box['y']+box['height']/2)
                page.evaluate('cancelAnimationFrame(game); window.requestAnimationFrame=()=>0')
            tap('climb.restart')
            self.assertTrue(page.evaluate('CLIMB_UI.confirming'))
            tap('climb.cancel')
            self.assertFalse(page.evaluate('CLIMB_UI.confirming'))
            self.assertEqual(page.evaluate('captureClimbState()'),paused)
            tap('climb.restart')
            self.assertTrue(page.evaluate('CLIMB_UI.confirming'))
            tap('climb.yes')
            self.assertFalse(page.evaluate('CLIMB_UI.confirming'))
            reset=page.evaluate('captureClimbState()')
            self.assertEqual(reset,base)
            page.wait_for_function("JSON.parse(localStorage.getItem('grapnelninja.grappleOver')).simulationTick===0")
            page.evaluate('for(let i=0;i<120;i++) physics(); ninja.x=1550; ninja.y=50; ninja.speedY=0; physics()')
            completed=page.evaluate('captureClimbState()')
            self.assertTrue(completed['stats']['completed'])
            self.assertEqual(page.evaluate('events460.find(e=>e.name==="level_completed").data.elapsedActiveMs'), completed['stats']['elapsedActiveMs'])
            page.evaluate('for(let i=0;i<20;i++) physics(); menu.unPause()')
            self.assertEqual(page.evaluate('captureClimbState()'),completed)
            events=page.evaluate('events460')
            self.assertEqual(sum(e['name']=='level_completed' for e in events),1)
            self.assertFalse(any(e['name']=='level_failed' for e in events))
            self.assertTrue(page.evaluate('menu.gamePaused'))
            page.wait_for_function("JSON.parse(localStorage.getItem('grapnelninja.grappleOver')).stats.completed")
            page.reload(); wait_for_boot(page)
            page.evaluate('cancelAnimationFrame(game); window.requestAnimationFrame=()=>0')
            self.assertEqual(page.evaluate('captureClimbState()'),completed)
            self.assertEqual(page.evaluate('events460.filter(e=>e.name==="level_completed").length'),0)
            page.evaluate('lang=>setLanguage(lang)',lang)
            boxes=page.evaluate('''() => {LAYOUT_PROBE.boxes=[];draw();
                const b=LAYOUT_PROBE.boxes;LAYOUT_PROBE.boxes=null;return b}''')
            buttons=[b for b in boxes if b['kind']=='button']
            # Ignore the background HUD menu icon under the opaque ending choices.
            buttons=[b for b in buttons if b['name']!='icon']
            for i,b in enumerate(buttons):
                self.assertGreaterEqual(b['height']+1e-6,44)
                self.assertGreaterEqual(b['x'],0); self.assertGreaterEqual(b['y'],0)
                self.assertLessEqual(b['x']+b['width'],viewport[0]+1)
                self.assertLessEqual(b['y']+b['height'],viewport[1]+1)
                for o in buttons[i+1:]:
                    self.assertFalse(b['x']<o['x']+o['width'] and o['x']<b['x']+b['width'] and
                                     b['y']<o['y']+o['height'] and o['y']<b['y']+b['height'])
                for t in [t for t in boxes if t['kind']=='text' and t['name']==b['name']]:
                    self.assertGreaterEqual(t['x'],b['x'])
                    self.assertLessEqual(t['x']+t['width'],b['x']+b['width'])
            page.screenshot(path=str(self.evidence.path('ending.png' if lang=='en' else 'ending-ru.png')))
            tap('mode.bad')
            self.assertEqual(page.evaluate('version'),'bad')
            self.assertFalse(page.evaluate('events460.some(e=>e.name==="level_failed")'))
            page.evaluate("menu.selectMode('grapple_over');cancelAnimationFrame(game)")
            self.assertTrue(page.evaluate('floors[0].climbStats.completed'))
            tap('climb.replay')
            self.assertFalse(page.evaluate('floors[0].climbStats.completed'))
            self.assertFalse(page.evaluate('menu.gamePaused'))
            self.assertEqual(errors,[])
            self.proof['runs'].append(dict(language=lang,viewport=viewport,base=base,high=high,low=low,
                paused=paused,reset=reset,completed=completed,events=events,ending_boxes=boxes,hud_boxes=hud_boxes,
                falls_pass=True,max_informational_pass=True,paused_time_excluded_pass=True,
                restart_cancel_preserves_pass=True,restart_confirm_resets_movers_save_pass=True,
                completion_once_frozen_pass=True,reload_completion_pass=True,replay_pass=True,
                mode_switch_no_failed_completion_pass=True,localized_layout_pass=True,browser_errors=errors))
            print(f'PASS {lang} {viewport}: falls; informational max; pause; cancel; restart movers/save; completion once/frozen; reload; replay; mode switch; localized layout')


class Task537Tests(unittest.TestCase):
    """The fps checkbox on the Grapple Over pause menu, from trusted mouse and touch input."""
    RUNS = [dict(name='desktop', viewport=[1280, 720], touch=False, lang='en',
                 pause_png='pause-desktop-en.png', hud_png='hud-fps.png'),
            dict(name='touch', viewport=[844, 390], touch=True, lang='ru',
                 pause_png='pause-touch-ru.png', hud_png='hud-fps-touch-ru.png')]

    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-537')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_modes.py', 'tools/test_menu_fps_checkbox.py'):
            hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = {'revision': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
                     'source_hashes': hashes, 'browser': cls.browser.version, 'device_scale_factor': 1,
                     'runs': {}}
        cls.layout = {'runs': {}}
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('toggle.json', cls.proof)
        cls.evidence.write('layout.json', cls.layout)

    def open(self, run):
        context = self.browser.new_context(viewport=dict(zip(('width','height'), run['viewport'])),
                                           device_scale_factor=1, has_touch=run['touch'])
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url)
        wait_for_boot(page)
        page.wait_for_function('runInProgress && !menu.gamePaused')
        return page

    def boxes(self, page, pause):
        """CSS px LAYOUT_PROBE boxes of one frame, with the pause screen over it when paused."""
        return page.evaluate('''pause => {LAYOUT_PROBE.boxes=[]; draw(); if (pause) menu.drawPauseScreen();
            const b=LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes=null; return b}''', pause)

    def press(self, page, run, box):
        """One trusted mouse click or touch tap on the centre of a probed box."""
        page.wait_for_function('!unTouch')
        rect = page.locator('#canvas').bounding_box()
        x, y = rect['x']+box['x']+box['width']/2, rect['y']+box['y']+box['height']/2
        if run['touch']:
            page.touchscreen.tap(x, y)
        else:
            page.mouse.click(x, y)
        return [x, y]

    def pick(self, boxes, name, kind='button'):
        found = [b for b in boxes if b['kind'] == kind and b['name'] == name]
        return found[0] if found else None

    def label(self, page, key):
        return page.evaluate('k => I18N.t(k)', key)

    def pause(self, page, run):
        icon = self.pick(self.boxes(page, False), 'icon')
        self.press(page, run, icon)
        page.wait_for_function('menu.gamePaused')
        return icon

    def ink(self, page, box):
        """Bright pixels inside the checkbox square (the check mark when ticked)."""
        from io import BytesIO
        from PIL import Image
        size = box['height']
        image = Image.open(BytesIO(page.screenshot())).convert('L')
        # The square sits at the left of the hit rect, padded by 0.45 of its size.
        check = page.evaluate('[menu.pauseFpsCounterCheckbox.size, menu.pauseFpsCounterCheckbox.x, '
                              'menu.pauseFpsCounterCheckbox.y]')
        css = page.evaluate('getCanvasCssRect().height / height')
        s, x0, yc = check[0]*css, check[1]*css, check[2]*css
        crop = image.crop((int(x0+s*0.2), int(yc-s*0.3), int(x0+s*0.8), int(yc+s*0.3)))
        return sum(1 for p in crop.getdata() if p > 160)

    @staticmethod
    def overlap(a, b):
        return a['x'] < b['x']+b['width'] and b['x'] < a['x']+a['width'] and \
               a['y'] < b['y']+b['height'] and b['y'] < a['y']+a['height']

    def check_layout(self, page, run, boxes):
        fps = self.pick(boxes, self.label(page, 'menu.fpsCounter'))
        self.assertIsNotNone(fps)
        keys = ['pause.resume', 'climb.restart', 'mode.bad', 'mode.classic']
        buttons = [self.pick(boxes, self.label(page, k)) for k in keys]
        self.assertTrue(all(buttons))
        language = self.pick(boxes, 'language')
        title = self.pick(boxes, self.label(page, 'mode.grapple_over'), 'text')
        hud = [b for b in boxes if b['kind'] == 'text' and b['x'] < run['viewport'][0]*0.3
               and b['y'] < run['viewport'][1]*0.3 and b is not title]
        self.assertGreaterEqual(len(hud), 4)
        label = self.pick(boxes, self.label(page, 'menu.fpsCounter'), 'text')
        width, height = run['viewport']
        for other in buttons + [language] + hud + [title]:
            self.assertFalse(self.overlap(fps, other), other)
        for i, b in enumerate(buttons + [language]):
            for o in (buttons + [language])[i+1:]:
                self.assertFalse(self.overlap(b, o), (b, o))
            for h in hud:
                self.assertFalse(self.overlap(b, h), (b, h))
        self.assertTrue(0 <= fps['x'] and fps['x']+fps['width'] <= width and
                        0 <= fps['y'] and fps['y']+fps['height'] <= height)
        self.assertTrue(fps['x'] <= label['x'] and label['x']+label['width'] <= fps['x']+fps['width'])
        if run['touch']:
            self.assertGreaterEqual(fps['height']+1e-6, 44)
            self.assertGreaterEqual(fps['width']+1e-6, 44)
        return {'viewport': run['viewport'], 'touch': run['touch'], 'language': run['lang'],
                'checkbox_hit': fps, 'checkbox_label': label, 'buttons': dict(zip(keys, buttons)),
                'language_button': language, 'hud_text': hud, 'title': title,
                'no_overlap_pass': True, 'inside_canvas_pass': True,
                'touch_target_ge_44_pass': fps['height'] >= 44-1e-6 and fps['width'] >= 44-1e-6}

    def flow(self, run):
        page = self.open(run)
        page.evaluate('lang => setLanguage(lang)', run['lang'])
        record = {'viewport': run['viewport'], 'input': 'touch' if run['touch'] else 'mouse',
                  'language': run['lang'], 'steps': []}
        def step(name, **data):
            data.update(name=name, mode=page.evaluate('version'), paused=page.evaluate('menu.gamePaused'),
                        fps_enabled=page.evaluate('fpsCounter.enabled'))
            record['steps'].append(data)
            return data
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        self.assertFalse(page.evaluate('fpsCounter.enabled'))
        storage_initial = page.evaluate('Object.keys(localStorage).sort()')

        icon = self.pause(page, run)
        boxes = self.boxes(page, True)
        layout = self.check_layout(page, run, boxes)
        self.layout['runs'][run['name']] = layout
        fps_name = self.label(page, 'menu.fpsCounter')
        unchecked_ink = self.ink(page, layout['checkbox_hit'])
        page.screenshot(path=str(self.evidence.path(run['pause_png'])))
        step('open_pause', pause_icon=icon, checkbox=layout['checkbox_hit'], checkbox_ink=unchecked_ink)

        at = self.press(page, run, layout['checkbox_hit'])
        page.wait_for_function('fpsCounter.enabled')
        self.assertTrue(page.evaluate('menu.gamePaused && version === "grapple_over"'))
        redrawn = self.pick(self.boxes(page, True), fps_name)
        checked_ink = self.ink(page, redrawn)
        self.assertGreater(checked_ink, unchecked_ink)
        step('click_checkbox', at=at, checkbox_ink=checked_ink, redrawn_checkbox=redrawn)

        self.press(page, run, layout['buttons']['pause.resume'])
        page.wait_for_function('!menu.gamePaused')
        page.wait_for_function('fpsCounter.value > 0')
        page.wait_for_timeout(300)
        play = self.boxes(page, False)
        fps_text = [b for b in play if b['kind'] == 'text' and b['name'].startswith('FPS')]
        self.assertEqual(len(fps_text), 1)
        hud = [b for b in play if b['kind'] == 'text' and b not in fps_text and b['x'] < run['viewport'][0]*0.3]
        self.assertGreaterEqual(len(hud), 4)
        for h in hud:
            self.assertFalse(self.overlap(fps_text[0], h), (fps_text[0], h))
        page.screenshot(path=str(self.evidence.path(run['hud_png'])))
        layout['resumed_play'] = {'fps_text': fps_text[0], 'hud_text': hud, 'fps_hud_no_overlap_pass': True}
        step('resumed_play', fps_panel_text=fps_text[0], hud_rows=len(hud), run_in_progress=page.evaluate('runInProgress'))

        self.pause(page, run)
        self.press(page, run, self.pick(self.boxes(page, True), self.label(page, 'mode.classic')))
        page.wait_for_function('version === "classic"')
        page.wait_for_function('!unTouch')
        self.pause(page, run)
        classic = self.boxes(page, True)
        classic_box = self.pick(classic, fps_name)
        self.assertIsNotNone(classic_box)
        classic_checked_ink = self.ink(page, classic_box)
        self.assertTrue(page.evaluate('fpsCounter.enabled'))
        step('classic_pause_shows_checked', checkbox=classic_box, checkbox_ink=classic_checked_ink)
        self.press(page, run, classic_box)
        page.wait_for_function('!fpsCounter.enabled')
        classic_unchecked_ink = self.ink(page, classic_box)
        self.assertLess(classic_unchecked_ink, classic_checked_ink)
        step('classic_uncheck', checkbox_ink=classic_unchecked_ink)

        mode_box = self.pick(self.boxes(page, True), self.label(page, 'mode.grapple_over'))
        self.press(page, run, mode_box)
        page.wait_for_function('version === "grapple_over" && menu.gamePaused')
        back = self.pick(self.boxes(page, True), fps_name)
        self.assertIsNotNone(back)
        back_ink = self.ink(page, back)
        self.assertFalse(page.evaluate('fpsCounter.enabled'))
        self.assertLess(back_ink, checked_ink)
        step('return_grapple_over_unchecked', checkbox=back, checkbox_ink=back_ink)

        self.press(page, run, self.pick(self.boxes(page, True), self.label(page, 'climb.restart')))
        page.wait_for_function('CLIMB_UI.confirming')
        confirm = self.boxes(page, True)
        self.assertIsNone(self.pick(confirm, fps_name))
        self.assertIsNone(self.pick(confirm, fps_name, 'text'))
        self.assertFalse(page.evaluate('menu.pauseFpsCounterCheckbox.clickable'))
        at = self.press(page, run, back)
        page.wait_for_function('!unTouch')
        self.assertFalse(page.evaluate('fpsCounter.enabled'))
        self.assertTrue(page.evaluate('CLIMB_UI.confirming && menu.gamePaused'))
        step('restart_confirmation', checkbox_drawn=False, clicked_old_checkbox_at=at,
             clickable=page.evaluate('menu.pauseFpsCounterCheckbox.clickable'),
             confirm_buttons=[b['name'] for b in confirm if b['kind'] == 'button'])
        self.press(page, run, self.pick(confirm, self.label(page, 'climb.cancel')))
        page.wait_for_function('!CLIMB_UI.confirming')
        self.assertIsNotNone(self.pick(self.boxes(page, True), fps_name))

        # Enabled before the reload: it must still come back off, with no new keys.
        self.press(page, run, self.pick(self.boxes(page, True), fps_name))
        page.wait_for_function('fpsCounter.enabled')
        page.evaluate('PROGRESS.flushClimb(); PROGRESS.save(); PROGRESS.flush && PROGRESS.flush()')
        page.wait_for_timeout(300)
        storage_before = page.evaluate('Object.fromEntries(Object.entries(localStorage))')
        page.reload()
        wait_for_boot(page)
        storage_after = page.evaluate('Object.fromEntries(Object.entries(localStorage))')
        self.assertFalse(page.evaluate('fpsCounter.enabled'))
        self.assertEqual(sorted(storage_after), sorted(storage_before))
        self.assertTrue(set(storage_initial) <= set(storage_after))
        for key, value in storage_after.items():
            self.assertNotIn('fps', (key + value).lower())
        step('reload', enabled_before_reload=True, storage_keys_initial=storage_initial,
             storage_keys_before=sorted(storage_before), storage_keys_after=sorted(storage_after),
             new_keys=sorted(set(storage_after) - set(storage_before)), fps_in_storage=False)
        record.update(open_click_enabled_panel_pass=True, shared_state_across_modes_pass=True,
                      absent_during_confirmation_pass=True, not_persisted_no_new_key_pass=True)
        self.proof['runs'][run['name']] = record
        return record

    def test_01_desktop_mouse(self):
        self.flow(self.RUNS[0])
        print('PASS desktop 1280x720 mouse en: pause opens with fps checkbox; click enables fpsCounter; '
              'FPS panel drawn in resumed play; Classic shows checked, unchecked there -> Grapple Over unchecked; '
              'absent/unclickable in restart confirmation; reload -> disabled, no new storage key')

    def test_02_touch_ru(self):
        self.flow(self.RUNS[1])
        print('PASS touch 844x390 ru: same flow by trusted taps; checkbox hit rect >=44 CSS px; no overlaps')
