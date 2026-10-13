"""Offline first-play funnel: real input/rendering with SDK boundary faults.

The adapter entry observer forwards every call unchanged, recording occurrence
state independently of delayed analytics delivery. Repeated runs additionally
exercise the production startGame entry point directly.

Boot starts a 'bad' run with no title menu (TASK-360/364), so mode_selected,
run_initialized and first_gameplay_frame come from the boot run. The first
grapnel press sends first_grapple and tutorial_dismissed, which starts the
canvas tutorial hint's fade (TASK-366/367).
"""
import json
import unittest

import test_playgama2_bridge as support

STAGES = ['mode_selected', 'run_initialized', 'first_gameplay_frame', 'first_grapple', 'tutorial_dismissed']
BOOT_STAGES = STAGES[:3]

OBSERVE = r'''
window.occurrences = [];
const startup = PLATFORM.startup;
PLATFORM.startup = function(stage, mode) {
    if (!occurrences.some(e => e.stage === stage)) occurrences.push({
        stage, mode, ms:performance.now(), bootComplete,
        loadingHidden:document.getElementById('loading').hidden,
        ninja:!!ninja, grapnel:!!grapnel, floors:floors?.length || 0,
        paused:hostPaused || menu.gamePaused,
        hintVisible:TUTORIAL_HINT.visible, hintPressed:TUTORIAL_HINT.pressed
    });
    return startup.call(this, stage, mode);
};
'''
TRANSPORT = r'''
bridge.analytics = {send(name, data) {
    record(name, data);
    if (CASE === 'throws') throw Error('PRIVATE injected transport error');
    if (CASE === 'rejects') return Promise.reject(Error('PRIVATE injected transport error'));
    return Promise.resolve();
}};
const send = bridge.platform.sendMessage;
bridge.platform.sendMessage = function(name, data) {
    if (name !== 'game_ready') return send(name, data);
    record(name, data);
    if (CASE === 'exhausted') return Promise.reject(Error('readiness fault'));
    if (CASE === 'delayed') return new Promise(resolve => window.releaseReady = resolve);
    return Promise.resolve();
};
if (CASE === 'late-init') {
    const init = bridge.initialize;
    bridge.initialize = async options => {
        await new Promise(resolve => window.releaseInit = resolve);
        return init(options);
    };
}
if (CASE === 'paused') bridge.platform.isPaused = true;
'''
# Canvas centre of a button, in page coordinates
CENTER = '''([expr, scaled]) => {
    const b = eval(expr), s = scaled ? scale[version] : 1, r = canvas.getBoundingClientRect();
    return {x:r.x+(b.x+b.width/2)*s*r.width/width, y:r.y+(b.y+b.height/2)*s*r.height/height};
}'''


class StartupTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'event-transcripts.json').write_text(json.dumps(cls.results, indent=2) + '\n')

    def test_funnel(self):
        for mode in ('classic', 'bad'):
            for case in ('immediate', 'delayed', 'late-init', 'boot-only', 'exhausted', 'throws', 'rejects', 'paused'):
                # A page without input stays in the boot run's mode
                if (mode, case) == ('classic', 'boot-only'):
                    continue
                with self.subTest(mode=mode, case=case):
                    self.run_case(mode, case)

    def test_portrait_first_frame_milestone(self):
        context = self.browser.new_context(viewport={'width':390, 'height':844},
                                           has_touch=True, is_mobile=True, locale='en')
        self.addCleanup(context.close)
        body = 'const FAULT="normal", SAVED_LANGUAGE="en", CASE="immediate";' + support.FAKE + TRANSPORT
        context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body=body))
        context.route('**/platform.js', lambda r: r.fulfill(content_type='application/javascript',
            body=(support.ROOT / 'platform.js').read_text() + OBSERVE))
        context.add_init_script("""
            window.touchInputs = [];
            document.addEventListener('touchstart', e => touchInputs.push({
                trusted:e.isTrusted, ms:performance.now()}), true);
        """)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url + 'current/index.html')
        support.wait_for_boot(page)
        page.wait_for_function("PLATFORM.readiness.state === 'success'")

        def snapshot():
            return page.evaluate("""({bootComplete, inert:document.getElementById('stage').inert,
                rotateVisible:getComputedStyle(document.getElementById('rotate-prompt')).display !== 'none',
                readiness:PLATFORM.readiness, paused:menu.gamePaused,
                frameCount:occurrences.filter(e=>e.stage==='first_gameplay_frame').length,
                sentFrameCount:probe.calls.filter(e=>e.name==='startup_funnel' && e.data.stage==='first_gameplay_frame').length,
                occurrences, calls:probe.calls, inputs:touchInputs, hint:TUTORIAL_HINT.visible,
                ninja:!!ninja, grapnel:!!grapnel, floors:floors?.length || 0})""")

        # The boot run is paused behind the rotate prompt: no gameplay frame yet
        page.wait_for_timeout(200)
        portrait = snapshot()
        self.assertTrue(portrait['bootComplete'] and portrait['inert'] and portrait['rotateVisible'])
        self.assertEqual(portrait['readiness']['state'], 'success')
        self.assertEqual((portrait['frameCount'], portrait['sentFrameCount']), (0, 0))
        self.assertTrue(portrait['paused'] and portrait['hint'])
        page.screenshot(path=str(self.out / 'portrait.png'))
        page.set_viewport_size({'width':844, 'height':390})
        page.wait_for_function("!document.getElementById('stage').inert")
        page.wait_for_timeout(200)  # let the debounced canvas layout settle
        landscape = snapshot()
        self.assertFalse(landscape['inert'] or landscape['rotateVisible'])
        self.assertTrue(landscape['paused'])
        self.assertEqual((landscape['frameCount'], landscape['sentFrameCount']), (0, 0))
        page.screenshot(path=str(self.out / 'landscape.png'))
        # Resuming is left to the player: a trusted tap on Resume
        page.touchscreen.tap(**page.evaluate(CENTER, ['menu.resume.background', False]))
        page.wait_for_function("occurrences.some(e=>e.stage==='first_gameplay_frame')")
        page.wait_for_function('!unTouch')
        page.touchscreen.tap(560, 150)
        page.wait_for_function("occurrences.some(e=>e.stage==='tutorial_dismissed')")
        started = snapshot()
        self.assertFalse(started['paused'])
        self.assertTrue(started['ninja'] and started['grapnel'] and started['floors'] > 0)
        self.assertEqual(len(started['inputs']), 2)
        self.assertTrue(all(i['trusted'] for i in started['inputs']))
        self.assertEqual([e['stage'] for e in started['occurrences']], STAGES)
        self.assertEqual((started['frameCount'], started['sentFrameCount']), (1, 1))
        page.set_viewport_size({'width':390, 'height':844})
        page.wait_for_function("document.getElementById('stage').inert")
        page.set_viewport_size({'width':844, 'height':390})
        page.wait_for_function("!document.getElementById('stage').inert")
        page.evaluate('for(let i=0;i<20;i++) PLATFORM.gameReady(); updateOrientation(); updateOrientation()')
        page.wait_for_timeout(200)
        repeated = snapshot()
        self.assertEqual((repeated['frameCount'], repeated['sentFrameCount']), (1, 1))
        self.assertEqual([c['data']['stage'] for c in repeated['calls'] if c['name'] == 'startup_funnel'], STAGES)
        self.assertEqual(errors, [])
        verdict = 'PASS portrait first_gameplay_frame milestone deferred until interactive landscape'
        trace = dict(environment='Chromium touch emulation', browser=self.browser.version,
                     portrait=portrait, landscape=landscape, started=started, repeated=repeated,
                     screenshots={'portrait.png':'Chromium touch emulation: portrait rotate overlay',
                                  'landscape.png':'Chromium touch emulation: landscape pause screen'},
                     errors=errors, verdict=verdict)
        (self.out / 'portrait-regression.json').write_text(json.dumps(trace, indent=2) + '\n')
        print(verdict, flush=True)

    def run_case(self, mode, case):
        context = self.browser.new_context(viewport={'width':1280, 'height':720}, locale='en')
        self.addCleanup(context.close)
        body = 'const FAULT="normal", SAVED_LANGUAGE="en", CASE=' + json.dumps(case) + ';' + support.FAKE + TRANSPORT
        context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body=body))
        context.route('**/platform.js', lambda r: r.fulfill(content_type='application/javascript',
            body=(support.ROOT / 'platform.js').read_text() + OBSERVE))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url + 'current/index.html')
        support.wait_for_boot(page)
        page.wait_for_function('PLATFORM.readiness.applicationReady')
        boot_state = page.evaluate('({readiness:PLATFORM.readiness, occurrences, calls:probe.calls})')
        boot_event = boot_state['occurrences'][0]
        self.assertEqual((boot_event['stage'], boot_event['mode']), ('mode_selected', 'bad'))
        self.assertTrue(boot_event['bootComplete'] and boot_event['loadingHidden'])
        # chooseVersion() shows the tutorial hint for the boot run
        self.assertTrue(boot_state['occurrences'][1]['hintVisible'])
        # A host-paused boot run has not drawn a gameplay frame yet
        boot_stages = BOOT_STAGES[:2] if case == 'paused' else BOOT_STAGES
        self.assertEqual([e['stage'] for e in boot_state['occurrences']], boot_stages)
        inactive = None
        if case != 'boot-only':
            if case == 'paused':
                page.wait_for_timeout(150)
                inactive = page.evaluate('({occurrences, x:ninja.x,y:ninja.y, paused:menu.gamePaused})')
                self.assertNotIn('first_gameplay_frame', [e['stage'] for e in inactive['occurrences']])
                self.assertTrue(inactive['paused'])
                page.evaluate("emitHost('pause', false)")
                if mode == 'bad':
                    # Resuming is left to the player: a trusted click on Resume
                    page.wait_for_function('!unTouch')
                    page.mouse.click(**page.evaluate(CENTER, ['menu.resume.background', False]))
            support.Playgama2BridgeTests.click_mode(self, page, mode)
            page.wait_for_function("occurrences.some(e=>e.stage==='first_gameplay_frame')")
            page.wait_for_function('!menu.gamePaused && !unTouch')
            # A trusted press on the play field throws the grapnel and starts the hint fade
            page.mouse.click(800, 250)
            page.wait_for_function("occurrences.some(e=>e.stage==='tutorial_dismissed')")
        before = page.evaluate('({readiness:PLATFORM.readiness,calls:probe.calls})')
        stages = BOOT_STAGES if case == 'boot-only' else STAGES
        if case in ('delayed', 'late-init'):
            self.assertEqual(before['readiness']['startup']['queued'], len(stages))
            self.assertFalse(any(c['name']=='startup_funnel' for c in before['calls']))
            page.evaluate('releaseReady()' if case == 'delayed' else 'releaseInit()')
        expected_state = 'exhausted' if case == 'exhausted' else 'success'
        page.wait_for_function('s => PLATFORM.readiness.state === s', arg=expected_state)
        if case != 'boot-only':
            page.evaluate("startGame('bad'); startGame('classic'); for(let i=0;i<20;i++) PLATFORM.gameReady()")
            page.wait_for_timeout(120)
        else:
            page.wait_for_timeout(200)
        result = page.evaluate('''({calls:probe.calls, occurrences, readiness:PLATFORM.readiness,
            now:performance.now(), game_version:PLATFORM.buildVersion, bootComplete,
            environment:{userAgent:navigator.userAgent,viewport:[innerWidth,innerHeight],
            graphics:(() => {const gl=document.createElement('canvas').getContext('webgl');
              const e=gl?.getExtension('WEBGL_debug_renderer_info');return e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):'unavailable'})()}})''')
        result.update(before=before, boot_state=boot_state, inactive=inactive, errors=errors, browser=self.browser.version)
        self.results[mode+'-'+case] = result
        events = [c for c in result['calls'] if c['name']=='startup_funnel']
        # The boot run is 'bad'; a host-paused boot draws its first frame in the
        # mode it resumes into; the press happens in the mode under test
        modes = ['bad', 'bad', mode if case == 'paused' else 'bad', mode, mode][:len(stages)]
        self.assertEqual([e['stage'] for e in result['occurrences']], stages)
        self.assertEqual([e['mode'] for e in result['occurrences']], modes)
        self.assertEqual([e['data']['stage'] for e in events], [] if case=='exhausted' else stages)
        for event, occurrence, expected_mode in zip(events, result['occurrences'], modes):
            expected = dict(stage=occurrence['stage'], elapsed_ms=event['data']['elapsed_ms'],
                            game_version=result['game_version'], mode=expected_mode)
            self.assertEqual(event['data'], expected)
            self.assertLessEqual(abs(event['data']['elapsed_ms']-occurrence['ms']), 10)
            self.assertLessEqual(event['data']['elapsed_ms'], result['now']+1)
            self.assertGreaterEqual(event['data']['elapsed_ms'], 0)
        self.assertEqual([e['data']['elapsed_ms'] for e in events], sorted(e['data']['elapsed_ms'] for e in events))
        initialized = result['occurrences'][1]
        self.assertTrue(initialized['ninja'] and initialized['grapnel'] and initialized['floors'] > 0)
        self.assertFalse(result['occurrences'][2]['paused'])
        if case != 'boot-only':
            dismissed = result['occurrences'][-1]
            self.assertTrue(dismissed['hintPressed'] and dismissed['hintVisible'])
        lifecycle = [c['name'] for c in result['calls'] if c['name'].startswith('level_')]
        # Boot run; classic leaves it through the pause screen's switch
        # (level_failed), a host-paused bad run is resumed; then the two
        # direct startGame calls
        if mode == 'classic':
            after_boot = ['level_paused', 'level_failed', 'level_started']
        else:
            after_boot = ['level_paused', 'level_resumed'] if case == 'paused' else []
        if case == 'exhausted':
            expected_lifecycle = []
        elif case == 'boot-only':
            expected_lifecycle = ['level_started']
        else:
            expected_lifecycle = ['level_started'] + after_boot + ['level_started']*2
        self.assertEqual(lifecycle, expected_lifecycle)
        if case in ('delayed','late-init'):
            names = [c['name'] for c in result['calls']]
            self.assertLess(names.index('level_started'), names.index('startup_funnel'))
        self.assertEqual(result['readiness']['startup'], dict(queued=0, capacity=5, seen=len(stages)))
        self.assertEqual(errors, [])
        self.assertTrue(result['bootComplete'])
        result['verdict'] = f'PASS {mode}-{case}: exact payloads/order; count={len(events)}; queue<=5; elapsed_ms; privacy; inactive frame excluded; lifecycle preserved; no page errors'
        print(result['verdict'], flush=True)
        context.close()


if __name__ == '__main__':
    unittest.main()
