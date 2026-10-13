"""Readiness recovery regression: real clicks/rendering, faults only in the SDK.

Before-fix characterization is preserved under artifacts/TASK-288.
The shared offline harness blocks production analytics, SDK traffic and ads.

Boot starts a 'bad' run with no title menu (TASK-360/364); classic is reached
through the pause-screen switch (TASK-362). A trusted canvas press then throws
the grapnel and dismisses the canvas tutorial hint (TASK-366/367).
"""
import json
import unittest

import test_playgama2_bridge as support

OBSERVE = r"""
window.startProbe = {inputs: [], frames: [], checkpoints: []};
window.runSnapshot = () => ({ms:performance.now(), readiness:PLATFORM.readiness,
    paused:menu.gamePaused, runInProgress, version,
    ninja: ninja ? {x:ninja.x,y:ninja.y,speedY:ninja.speedY}:null,
    floors:floors ? floors.length : 0, grapnel:!!grapnel, runOver,
    hintVisible:TUTORIAL_HINT.visible, hintPressed:TUTORIAL_HINT.pressed});
document.addEventListener('mousedown', e => {
    startProbe.inputs.push({ms:performance.now(), trusted:e.isTrusted, x:e.clientX,y:e.clientY});
    setTimeout(() => startProbe.checkpoints.push({name:'after-input-task', ...runSnapshot()}), 0);
}, true);
// Browser-boundary observation only: invoke each callback exactly once with its
// original timestamp and preserve the browser's handle/cancellation semantics.
// Records the first 12 unpaused gameplay frames after the last trusted input.
const nativeRAF = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = callback => nativeRAF(t => {
    callback(t);
    const after = startProbe.inputs.at(-1)?.ms;
    if (typeof bootComplete !== 'undefined' && bootComplete && runInProgress &&
        !menu.gamePaused && ninja && after !== undefined && performance.now() > after) {
        startProbe.frames = startProbe.frames.filter(f => f.ms > after);
        if (startProbe.frames.length >= 12) return;
        const frame = {name:'gameplay-frame', frameTimestamp:t, ...runSnapshot()};
        startProbe.frames.push(frame);
        console.log('START_FLOW_FRAME ' + JSON.stringify(frame));
    }
});
"""
SEND = r"""
sendMessage(name, data) {
    record(name, data);
    if (name === 'level_started') {
        probe.calls[probe.calls.length-1].hintVisible = TUTORIAL_HINT.visible;
    }
    if (name !== 'game_ready') return Promise.resolve();
    window.readySends = (window.readySends || 0) + 1;
    return new Promise((resolve, reject) => {
        window.releaseReady = () => { record('ready-resolve'); resolve(); };
        if (CASE === 'immediate' || CASE === 'late-init') releaseReady();
        if (CASE === 'rejected-recovered' && readySends === 1) {
            record('ready-reject'); reject(Error('INJECTED readiness rejection'));
        }
    });
}
"""


class StartFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'start-traces.json').write_text(json.dumps(cls.results, indent=2) + '\n')

    def run_case(self, mode, case):
        key = mode + '-' + case
        context = self.browser.new_context(viewport={'width':1280, 'height':720}, locale='en')
        self.addCleanup(context.close)
        context.add_init_script(OBSERVE)
        body = "const FAULT='normal', SAVED_LANGUAGE='en', CASE=" + json.dumps(case) + ';\n' + support.FAKE
        original = 'sendMessage(name, data) { record(name, data); return Promise.resolve(); }'
        self.assertIn(original, body)
        body = body.replace(original, SEND)
        if case == 'late-init':
            body = body.replace("record('initialize', options);", "record('initialize', options); await new Promise(r => window.releaseInit = () => {record('init-release'); r();});")
        context.route(support.SDK, lambda route: route.fulfill(content_type='application/javascript', body=body))
        page = context.new_page()
        page.set_default_timeout(12000)
        logs, errors, network = [], [], []
        page.on('console', lambda msg: logs.append({'type':msg.type, 'text':msg.text}))
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: network.append({'url':response.url, 'status':response.status}))
        page.goto(self.url + 'current/index.html')
        support.wait_for_boot(page)
        target = {'immediate':'success', 'delayed':'inflight', 'rejected-recovered':'inflight', 'late-init':'pending'}[case]
        page.wait_for_function('state => PLATFORM.readiness.applicationReady && PLATFORM.readiness.state === state', arg=target)
        if case == 'rejected-recovered':
            page.wait_for_function('PLATFORM.readiness.attempts === 2')
        before = page.evaluate('runSnapshot()')
        try:
            self.assertEqual((before['version'], before['runInProgress']), ('bad', True))
            self.assertTrue(before['hintVisible'])
            support.Playgama2BridgeTests.click_mode(self, page, mode)
            page.wait_for_function('!menu.gamePaused && !unTouch')
            # The boot or switched run is shown with its hint until a press
            self.assertTrue(page.evaluate('TUTORIAL_HINT.visible && !TUTORIAL_HINT.pressed'))
            page.mouse.click(800, 250)
            page.wait_for_function('TUTORIAL_HINT.pressed && startProbe.frames.length >= 6')
            initialized = page.evaluate('runSnapshot()')
            page.screenshot(path=str(self.out / (key + '-before-ready.png')))
            if case == 'late-init':
                page.evaluate('releaseInit()')
            elif case != 'immediate':
                page.evaluate('releaseReady()')
            page.wait_for_function("PLATFORM.readiness.state === 'success'")
            # Bounded observation after success; preserve the same run identity.
            page.wait_for_timeout(250)
            after = page.evaluate('runSnapshot()')
            page.screenshot(path=str(self.out / (key + '-after-ready.png')))
            result = page.evaluate('({probe:startProbe, calls:probe.calls, readiness:PLATFORM.readiness})')
            result.update(before=before, initialized=initialized, after=after,
                          screenshots=[key+'-before-ready.png', key+'-after-ready.png'],
                          browser_log=key+'-browser.json', mode=mode, case=case,
                          browser=self.browser.version, environment=page.evaluate('''() => {
                            const gl=document.createElement('canvas').getContext('webgl');
                            const ext=gl && gl.getExtension('WEBGL_debug_renderer_info');
                            return {userAgent:navigator.userAgent, devicePixelRatio,
                              viewport:[innerWidth,innerHeight], graphics:ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):'unavailable'};
                          }'''))
            self.results[key] = result
            frames = result['probe']['frames']
            starts = [c for c in result['calls'] if c['name']=='level_started']
            lifecycle = [(c['name'], c['data']) for c in result['calls'] if c['name'].startswith('level_')]
            inputs = result['probe']['inputs']
            self.assertEqual(errors, [])
            # Classic: HUD menu button + pause switch; then the press
            self.assertEqual(len(inputs), 3 if mode == 'classic' else 1)
            self.assertTrue(all(i['trusted'] for i in inputs))
            self.assertLess(inputs[-1]['ms'], frames[0]['ms'])
            self.assertTrue(all(f['ninja'] and f['grapnel'] and f['floors'] > 0 and not f['paused']
                                and f['version'] == mode for f in frames))
            self.assertGreater(len({(f['ninja']['x'], f['ninja']['y']) for f in frames}), 1)
            # One level_started per run, none replayed: the boot run, then the
            # classic run that the pause switch starts
            expected = [('level_started', {'world':'bad'})]
            if mode == 'classic':
                expected += [('level_paused', None), ('level_failed', {'world':'bad'}), ('level_started', {'world':'classic'})]
            self.assertEqual([n for n, _ in lifecycle], [n for n, _ in expected])
            self.assertEqual([d for (_, d), (_, e) in zip(lifecycle, expected) if e is not None],
                             [e for _, e in expected if e is not None])
            self.assertEqual(result['readiness']['lifecycle']['queued'], 0)
            self.assertFalse(after['paused'])
            self.assertFalse(after['runOver'])
            self.assertEqual(after['version'], mode)
            self.assertTrue(initialized['hintPressed'])
            success = next(e['ms'] for e in result['readiness']['events'] if e['state']=='success')
            # The queued boot level_started is delivered only after game_ready
            self.assertLessEqual(success, starts[0]['ms'])
            self.assertTrue(starts[0]['hintVisible'])
            if case != 'immediate':
                self.assertLess(frames[0]['ms'], success)
            self.assertTrue(all(r['status']==200 and (r['url']==support.SDK or r['url'].startswith(self.url)) for r in network))
            result['verdict'] = f'PASS {key}: trusted input; initialized/advancing gameplay; level_started={len(starts)}; readiness=success; no replay observed'
            print(result['verdict'], flush=True)
        finally:
            (self.out / (key+'-browser.json')).write_text(json.dumps({'console':logs, 'errors':errors, 'network':network}, indent=2)+'\n')
            (self.out / 'start-traces.json').write_text(json.dumps(self.results, indent=2)+'\n')
            context.close()

    def test_eight_recovery_cases(self):
        for mode in ('classic', 'bad'):
            for case in ('immediate', 'delayed', 'rejected-recovered', 'late-init'):
                with self.subTest(mode=mode, readiness=case):
                    self.run_case(mode, case)


if __name__ == '__main__':
    unittest.main()
