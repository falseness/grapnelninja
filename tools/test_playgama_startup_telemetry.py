"""Offline first-play funnel: real input/rendering with SDK boundary faults.

The adapter entry observer forwards every call unchanged, recording occurrence
state independently of delayed analytics delivery. Repeated runs additionally
exercise the production startGame entry point directly.
"""
import json
import unittest

import test_playgama2_bridge as support

OBSERVE = r'''
window.occurrences = [];
const startup = PLATFORM.startup;
PLATFORM.startup = function(stage, mode) {
    if (!occurrences.some(e => e.stage === stage)) occurrences.push({
        stage, mode, ms:performance.now(), bootComplete, menu:menu.visible,
        loadingHidden:document.getElementById('loading').hidden,
        ninja:!!ninja, grapnel:!!grapnel, floors:floors?.length || 0,
        paused:hostPaused || menu.gamePaused, tutorialHidden:TUTORIAL.element.hidden
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
            for case in ('immediate', 'delayed', 'late-init', 'menu-only', 'exhausted', 'throws', 'rejects', 'paused'):
                with self.subTest(mode=mode, case=case):
                    self.run_case(mode, case)

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
        menu_state = page.evaluate('({readiness:PLATFORM.readiness, occurrences, calls:probe.calls})')
        menu_event = menu_state['occurrences'][0]
        self.assertEqual(menu_event['stage'], 'menu_interactive')
        self.assertTrue(menu_event['bootComplete'] and menu_event['menu'] and menu_event['loadingHidden'])
        self.assertEqual(len(menu_state['occurrences']), 1)
        # Trusted language input proves attached input while still in the menu.
        point = page.evaluate('''() => {const b=LANGUAGE_BUTTON.rect(),r=canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height};}''')
        page.mouse.click(**point)
        page.wait_for_function("I18N.language === 'ru'")
        page.wait_for_function('!unTouch')
        inactive = None
        if case != 'menu-only':
            support.Playgama2BridgeTests.click_mode(self, page, mode)
            if case == 'paused':
                page.wait_for_timeout(150)
                inactive = page.evaluate('({occurrences, x:ninja.x,y:ninja.y})')
                self.assertNotIn('first_gameplay_frame', [e['stage'] for e in inactive['occurrences']])
                page.evaluate("emitHost('pause', false)")
            page.wait_for_function("occurrences.some(e=>e.stage==='first_gameplay_frame')")
            page.wait_for_function('!unTouch')
            page.mouse.click(800, 250)
            page.locator('#tutorial button').click()
            page.wait_for_function("occurrences.some(e=>e.stage==='tutorial_dismissed')")
        before = page.evaluate('({readiness:PLATFORM.readiness,calls:probe.calls})')
        if case in ('delayed', 'late-init'):
            self.assertEqual(before['readiness']['startup']['queued'], 6)
            self.assertFalse(any(c['name']=='startup_funnel' for c in before['calls']))
            page.evaluate('releaseReady()' if case == 'delayed' else 'releaseInit()')
        expected_state = 'exhausted' if case == 'exhausted' else 'success'
        page.wait_for_function('s => PLATFORM.readiness.state === s', arg=expected_state)
        if case != 'menu-only':
            page.evaluate("startGame('bad'); startGame('classic'); for(let i=0;i<20;i++) PLATFORM.gameReady()")
            page.wait_for_timeout(120)
        else:
            page.wait_for_timeout(200)
        result = page.evaluate('''({calls:probe.calls, occurrences, readiness:PLATFORM.readiness,
            now:performance.now(), game_version:PLATFORM.buildVersion, bootComplete,
            environment:{userAgent:navigator.userAgent,viewport:[innerWidth,innerHeight],
            graphics:(() => {const gl=document.createElement('canvas').getContext('webgl');
              const e=gl?.getExtension('WEBGL_debug_renderer_info');return e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):'unavailable'})()}})''')
        result.update(before=before, menu_state=menu_state, inactive=inactive, errors=errors, browser=self.browser.version)
        self.results[mode+'-'+case] = result
        events = [c for c in result['calls'] if c['name']=='startup_funnel']
        stages = ['menu_interactive'] if case == 'menu-only' else [
            'menu_interactive','mode_selected','run_initialized','first_gameplay_frame','first_grapple','tutorial_dismissed']
        self.assertEqual([e['stage'] for e in result['occurrences']], stages)
        self.assertEqual([e['data']['stage'] for e in events], [] if case=='exhausted' else stages)
        for event, occurrence in zip(events, result['occurrences']):
            expected = dict(stage=occurrence['stage'], elapsed_ms=event['data']['elapsed_ms'], game_version=result['game_version'])
            if occurrence['stage'] != 'menu_interactive': expected['mode'] = mode
            self.assertEqual(event['data'], expected)
            self.assertLessEqual(abs(event['data']['elapsed_ms']-occurrence['ms']), 10)
            self.assertLessEqual(event['data']['elapsed_ms'], result['now']+1)
            self.assertGreaterEqual(event['data']['elapsed_ms'], 0)
        self.assertEqual([e['data']['elapsed_ms'] for e in events], sorted(e['data']['elapsed_ms'] for e in events))
        if case != 'menu-only':
            initialized = result['occurrences'][2]
            self.assertTrue(initialized['ninja'] and initialized['grapnel'] and initialized['floors'] > 0)
            self.assertFalse(result['occurrences'][3]['paused'])
            self.assertTrue(result['occurrences'][-1]['tutorialHidden'])
        lifecycle = [c['name'] for c in result['calls'] if c['name'].startswith('level_')]
        self.assertEqual(lifecycle, [] if case in ('exhausted','menu-only') else
                         ['level_started']*3)
        if case in ('delayed','late-init'):
            names = [c['name'] for c in result['calls']]
            self.assertLess(names.index('level_started'), names.index('startup_funnel'))
        self.assertEqual(result['readiness']['startup'], dict(queued=0, capacity=6, seen=len(stages)))
        self.assertEqual(errors, [])
        self.assertTrue(result['bootComplete'])
        result['verdict'] = f'PASS {mode}-{case}: exact payloads/order; count={len(events)}; queue<=6; elapsed_ms; privacy; inactive frame excluded; lifecycle preserved; no page errors'
        print(result['verdict'], flush=True)
        context.close()


if __name__ == '__main__':
    unittest.main()
