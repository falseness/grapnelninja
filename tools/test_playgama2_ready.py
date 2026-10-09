"""Readiness delivery on the real page, with SDK and frame scheduler faults only."""
import hashlib
import json
import subprocess
import unittest

import test_playgama2_bridge as support

# Hold only the post-overlay animation frame at the browser boundary so real
# mouse input and native menu proof can precede readiness deterministically.
# Production functions, input handlers and renderers are never replaced.
FRAME_PROBE = r"""
window.readyProbe = {events: [], draws: 0, inputs: []};
const fillText = CanvasRenderingContext2D.prototype.fillText;
CanvasRenderingContext2D.prototype.fillText = function(...args) {
    readyProbe.draws++;
    return fillText.apply(this, args);
};
document.addEventListener('mousedown', e => {
    readyProbe.inputs.push({ms: performance.now(), trusted: e.isTrusted});
});
const raf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = fn => {
    if (!window.frameHeld && document.getElementById('loading')?.hidden) {
        window.frameHeld = true;
        return raf(t => {
            readyProbe.events.push({name:'paint', ms:t, draws:readyProbe.draws});
            function release() {
                if (window.releaseReadyFrame) raf(fn);
                else setTimeout(release, 10);
            }
            release();
        });
    }
    return raf(fn);
};
"""
SEND = r"""
sendMessage(name, data) {
    record(name, data);
    if (name !== 'game_ready') return Promise.resolve();
    const event = {name:'send', ms:performance.now(), loadingHidden:document.getElementById('loading').hidden,
        menuVisible:menu.visible, bootComplete, draws:readyProbe.draws, language:I18N.language};
    readyProbe.events.push(event);
    window.sendCount = (window.sendCount || 0) + 1;
    window.activeSends = (window.activeSends || 0) + 1;
    window.maxActiveSends = Math.max(window.maxActiveSends || 0, activeSends);
    return new Promise((resolve, reject) => {
        const settle = () => {
            activeSends--;
            const fail = CASE === 'exhausted' || (CASE === 'retries' && sendCount <= 3);
            readyProbe.events.push({name:fail ? 'reject':'resolve', ms:performance.now()});
            if (fail) reject(Error('INJECTED readiness rejection')); else resolve();
        };
        if (CASE === 'unresolved') window.settleReady = settle;
        else setTimeout(settle, 60);
    });
}
"""


class Playgama2ReadyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'ready-events.json').write_text(json.dumps(cls.results, indent=2) + '\n')

    def run_case(self, case, gated=True):
        context = self.browser.new_context(viewport={'width':1280, 'height':720}, locale='en')
        self.addCleanup(context.close)
        context.add_init_script(FRAME_PROBE if gated else FRAME_PROBE.split('const raf =')[0])
        body = "const FAULT='normal', SAVED_LANGUAGE='en', CASE=" + json.dumps(case) + ';\n' + support.FAKE
        body = body.replace('sendMessage(name, data) { record(name, data); return Promise.resolve(); }', SEND)
        if case == 'late-init':
            body = body.replace("record('initialize', options);", "record('initialize', options); await new Promise(r => window.releaseInit = r);")
        context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body=body))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url + 'current/index.html', wait_until='domcontentloaded')
        support.wait_for_boot(page)
        if gated:
            page.wait_for_function('frameHeld && readyProbe.events.some(e => e.name === "paint")')
            self.assertEqual(page.evaluate('PLATFORM.readiness.attempts'), 0)
        point = page.evaluate('''() => {
            const b = LANGUAGE_BUTTON.rect(), r = canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width, y:r.y+(b.y+b.height/2)*r.height/height};
        }''')
        page.mouse.click(**point)
        page.wait_for_function("I18N.language === 'ru'")
        input_proof = page.evaluate("({ms:performance.now(), language:I18N.language, menu:menu.visible, loadingHidden:document.getElementById('loading').hidden, inputs:readyProbe.inputs})")
        self.assertTrue(input_proof['menu'] and input_proof['loadingHidden'])
        self.assertTrue(input_proof['inputs'][0]['trusted'])
        capture = self.out / (case + '-menu.png')
        subprocess.run(['import', '-window', 'root', str(capture)], env=self.env, check=True, timeout=12)
        page.evaluate('window.releaseReadyFrame = true')
        page.wait_for_function('PLATFORM.readiness.applicationReady')
        late_pending = None
        if case == 'late-init':
            late_pending = page.evaluate('({ms:performance.now(), readiness:PLATFORM.readiness})')
            self.assertEqual(page.evaluate('PLATFORM.readiness.state'), 'pending')
            self.assertEqual(page.evaluate('PLATFORM.readiness.attempts'), 0)
            page.evaluate('releaseInit()')
        page.wait_for_function('PLATFORM.readiness.attempts >= 1')
        # Repeat calls while pending/inflight, and exercise init/lifecycle without
        # allowing any of these to shortcut the retry schedule.
        page.evaluate("window.repeatReady = setInterval(() => { PLATFORM.gameReady(); PLATFORM.init(); PLATFORM.sendLifecycle('level_paused'); }, 30)")
        if case == 'unresolved':
            page.wait_for_timeout(4200)
            self.assertEqual(page.evaluate('PLATFORM.readiness.state'), 'inflight')
            self.assertEqual(page.evaluate('PLATFORM.readiness.attempts'), 1)
            unresolved = page.evaluate('({ms:performance.now(), readiness:PLATFORM.readiness})')
            self.assertFalse(page.evaluate("probe.calls.some(e => e.name === 'level_paused')"))
            page.evaluate('settleReady()')
        else:
            unresolved = None
        expected = 'exhausted' if case == 'exhausted' else 'success'
        page.wait_for_function('state => PLATFORM.readiness.state === state', arg=expected)
        page.evaluate("boot(); boot(); document.dispatchEvent(new Event('bridge-loaded')); emitHost('pause', true); emitHost('pause', false)")
        page.wait_for_timeout(2200)
        page.evaluate('clearInterval(repeatReady)')
        result = page.evaluate('({diagnostics:PLATFORM.readiness, probe:readyProbe, maxActiveSends, activeSends, calls:probe.calls})')
        events = result['probe']['events']
        sends = [e for e in events if e['name']=='send']
        outcomes = [e for e in events if e['name'] in ('resolve','reject')]
        expected_count = 4 if case in ('retries','exhausted') else 1
        self.assertEqual(len(sends), expected_count)
        self.assertEqual(result['diagnostics']['attempts'], expected_count)
        self.assertEqual(result['maxActiveSends'], 1)
        self.assertEqual(result['activeSends'], 0)
        self.assertEqual(len(errors), 0, errors)
        self.assertTrue(all(e['loadingHidden'] and e['menuVisible'] and e['bootComplete'] and e['draws'] > 0 for e in sends))
        if gated:
            self.assertLess(input_proof['ms'], sends[0]['ms'])
            self.assertLess(next(e['ms'] for e in events if e['name']=='paint'), sends[0]['ms'])
        stages = result['diagnostics']['events']
        successes = [e for e in stages if e['state']=='success']
        self.assertEqual(len(successes), 0 if case=='exhausted' else 1)
        self.assertEqual(sum(e['state']=='inflight' for e in stages), expected_count)
        self.assertEqual(sum(e['state']=='pending' for e in stages), expected_count)
        if successes:
            self.assertGreaterEqual(successes[0]['ms'], outcomes[-1]['ms'])
        delays = []
        if expected_count == 4:
            self.assertEqual([e['delayMs'] for e in stages if 'delayMs' in e], [500,1000,2000])
            for i, target in enumerate([500,1000,2000]):
                actual = sends[i+1]['ms'] - outcomes[i]['ms']
                self.assertGreaterEqual(actual, target-10)
                self.assertLessEqual(actual, target+350)
                delays.append(actual)
        result.update(verdict='PASS ' + case, input=input_proof, unresolved=unresolved, late_pending=late_pending, retry_delays_ms=delays,
            capture={'path':capture.name, 'sha256':hashlib.sha256(capture.read_bytes()).hexdigest()},
            scheduler='post-overlay frame held for real input proof' if gated else 'unaltered browser scheduling')
        self.results[case] = result
        print(f'PASS {case}: sends={expected_count} pending={expected_count} inflight={expected_count} success={len(successes)} maxActive=1; retries={delays}; rendered menu, hidden loading, trusted language input; no duplicate on repeated calls/init/lifecycle', flush=True)
        context.close()

    def test_immediate_success(self): self.run_case('immediate')
    def test_three_retries(self): self.run_case('retries')
    def test_exhausted_rejection(self): self.run_case('exhausted')
    def test_unresolved_send(self): self.run_case('unresolved')
    def test_late_init(self): self.run_case('late-init')
    def test_unaltered_scheduler(self): self.run_case('natural', gated=False)


if __name__ == '__main__':
    unittest.main()
