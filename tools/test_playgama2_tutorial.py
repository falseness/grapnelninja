"""First-run guidance through production boot, storage, and trusted browser input."""
import gc
import hashlib
import inspect
import json
import subprocess
import time
import unittest
from datetime import datetime, timezone

from playwright._impl._connection import from_channel
from playwright._impl._errors import TargetClosedError
from playwright._impl._helper import serialize_error
from playwright._impl._js_handle import parse_result, serialize_argument
from playwright._impl._page import BindingCall

import test_playgama2_bridge as support

FIXTURE_BINDINGS = ('fixtureGet', 'fixtureSet')
# Playwright 1.60 answers a failed resolve with an unawaited reject task, so a
# fixture reply racing page/context close leaks "Task exception was never retrieved".
BINDING_CALL_SHA256 = '8cc0ce2ca14041278a751a600b813fe44d8cac90bb7e60fee475317521ccb35f'


class RunnerErrors:
    """Fixture binding replies and asyncio errors on the Playwright loop.

    Only a fixture reply rejected with TargetClosedError after the checker closed
    its page or context is expected; callback errors and any other loop error are not.
    """
    def __init__(self):
        self.expected, self.unexpected = [], []

    def install(self, loop):
        source = inspect.getsource(BindingCall.call).encode()
        if hashlib.sha256(source).hexdigest() != BINDING_CALL_SHA256:
            raise RuntimeError('Unreviewed Playwright BindingCall.call; recheck fixture shutdown handling')
        original, monitor = BindingCall.call, self
        async def call(binding, func):
            if binding._initializer['name'] not in FIXTURE_BINDINGS:
                return await original(binding, func)
            await monitor.fixture_call(binding, func)
        BindingCall.call = call
        loop.set_exception_handler(self.loop_error)
        def uninstall():
            BindingCall.call = original
            loop.set_exception_handler(None)
        return uninstall

    async def fixture_call(self, binding, func):
        name = binding._initializer['name']
        frame = from_channel(binding._initializer['frame'])
        page = frame._page
        try:
            result = func(dict(context=page.context, page=page, frame=frame),
                          *map(parse_result, binding._initializer['args']))
            if inspect.iscoroutine(result):
                result = await result
            reply = 'resolve', dict(result=serialize_argument(result))
        except Exception as error:
            self.unexpected.append(f'fixture callback {name} raised {error!r}')
            reply = 'reject', dict(error=dict(error=serialize_error(error, error.__traceback__)))
        try:
            await binding._channel.send(reply[0], None, reply[1])
        except TargetClosedError as error:
            closing = 'page closed' if page._close_was_called else \
                'context closed' if page.context._closing_or_closed else None
            if closing is None:
                self.unexpected.append(f'fixture {name} {reply[0]} failed on a live page: {error!r}')
            else:
                self.expected.append({'binding': name, 'reply': reply[0], 'cancelled_by': closing})
        except Exception as error:
            self.unexpected.append(f'fixture {name} {reply[0]} failed: {error!r}')

    def loop_error(self, loop, context):
        self.unexpected.append('unexpected runner error: ' + context['message'] +
                               ': ' + repr(context.get('exception')))
        loop.default_exception_handler(context)

    def settle(self, browser):
        """Let loop work queued by a close finish, then surface dropped task errors."""
        browser.new_context().close()
        gc.collect()


class Playgama2TutorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.results = {}
        cls.runner = RunnerErrors()
        cls.addClassCleanup(cls.runner.install(cls.browser._impl_obj._loop))
        paths = subprocess.check_output(['git','ls-files'],cwd=support.ROOT,text=True).splitlines()
        paths += ['render/tutorialhint.js','tools/test_playgama2_tutorial.py']
        hashes = {p:hashlib.sha256((support.ROOT/p).read_bytes()).hexdigest() for p in sorted(set(paths)) if (support.ROOT/p).is_file() and not p.startswith(('artifacts/','screenshots/'))}
        (cls.out/'tested-source-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')

    @classmethod
    def tearDownClass(cls):
        cls.runner.settle(cls.browser)
        (cls.out / 'runner-errors.json').write_text(json.dumps({
            'expected_shutdown_cancellations': cls.runner.expected,
            'unexpected': cls.runner.unexpected}, indent=2) + '\n')
        (cls.out / 'tutorial-cases.json').write_text(json.dumps(cls.results, indent=2, ensure_ascii=False) + '\n')
        (cls.out / 'storage-fault-traces.json').write_text(json.dumps({
            k: v for k, v in cls.results.items() if v['fault'] != 'normal'
        }, indent=2) + '\n')
        if cls.runner.unexpected:
            raise AssertionError('Unexpected runner errors: ' + '; '.join(cls.runner.unexpected))

    def snapshot(self, page):
        return page.evaluate('''() => ({ms:performance.now(), visible:TUTORIAL_HINT.visible,
            alpha:TUTORIAL_HINT.alpha, pressed:TUTORIAL_HINT.pressed, done:TUTORIAL_HINT.done,
            lines:TUTORIAL_HINT.lines, shown:window.hintShown,
            dismissed:probe.calls.filter(c => c.name === 'startup_funnel' && c.data.stage === 'tutorial_dismissed').length,
            loading:!document.getElementById('loading').hidden, readiness:PLATFORM.readiness,
            throwed:!!grapnel?.throwed, calls:probe.calls, inputs:window.inputs,
            directStorageAccesses:window.directStorageAccesses})''')

    def start(self, page, touch):
        # Current trees boot straight into a run (TASK-360/364); no click starts it.
        page.wait_for_function('bootComplete && runInProgress && !!ninja')
        page.wait_for_function('!unTouch')
        # The hint's sprite (and its baked lines) is built on the first draw.
        page.wait_for_function('TUTORIAL_HINT.lines !== null')

    def press(self, page, context, touch):
        """Trusted hold on the play field: throws the grapnel, which starts the hint fade."""
        if touch:
            cdp = context.new_cdp_session(page)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':600,'y':140}]})
            release = lambda: cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else:
            page.mouse.move(850,200); page.mouse.down()
            release = page.mouse.up
        page.wait_for_function('grapnel.throwed')
        return release

    def trusted_press(self, inputs, touch):
        name = 'touchstart' if touch else 'mousedown'
        return any(e['trusted'] and e['target']=='CANVAS' and e['name']==name for e in inputs)

    def matrix(self, lang, touch, fault='normal'):
        case = lang + ('-touch' if touch else '-desktop') + ('' if fault == 'normal' else '-' + fault)
        record = self.results[case] = {'utc':datetime.now(timezone.utc).isoformat(), 'fault':fault}
        unexpected = len(self.runner.unexpected)
        context = self.browser.new_context(viewport={'width':800 if touch else 1280,'height':450 if touch else 720}, has_touch=touch)
        self.addCleanup(context.close)
        context.add_init_script("window.inputs=[]; for(const name of ['mousedown','mouseup','touchstart','touchend','click']) window.addEventListener(name,e=>inputs.push({name,trusted:e.isTrusted,target:e.target.tagName,ms:performance.now()}),true)")
        # State at the first frame the hint is visible on each page load.
        context.add_init_script('''window.hintShown=null; (function watch() {
            try { if (TUTORIAL_HINT.visible) hintShown = {ms:performance.now(), bootComplete,
                loading:!document.getElementById('loading').hidden, readiness:PLATFORM.readiness.state} }
            catch (_) {}
            if (!hintShown) requestAnimationFrame(watch) })()''')
        # Remote fixture state survives document reloads without browser storage.
        remote = {'grapnelninja.lang': lang}
        operations = record['sdk_operations'] = []
        boundary = {'fault': fault, 'reload_epoch': 0}
        def operation(op, **data):
            operations.append({'seq': len(operations), 'reload_epoch': boundary['reload_epoch'],
                               'op': op, **data})
        def get(keys):
            rejected = boundary['fault'] == 'storage_rejected'
            result = [remote.get(k) for k in keys]
            operation('read-rejected' if rejected else 'read-success', keys=keys, values=result)
            return {'rejected': rejected, 'values': result}
        def set_values(keys, values):
            rejected = boundary['fault'] == 'write_rejected'
            if not rejected:
                remote.update(zip(keys, values))
            operation('write-rejected' if rejected else 'write-success', keys=keys, values=values)
            return {'rejected': rejected}
        context.expose_function('fixtureGet', get)
        context.expose_function('fixtureSet', set_values)
        # Fail and count every direct access, including property-style storage use.
        context.add_init_script('''window.directStorageAccesses=[];
            for (const name of ['localStorage','sessionStorage'])
                Object.defineProperty(window,name,{get(){
                    directStorageAccesses.push(name); throw Error('Direct storage forbidden: '+name);
                }});''')
        fake = support.FAKE + '''
            bridge.storage.get = async keys => {
                const result = await fixtureGet(keys);
                if (result.rejected) throw Error('INJECTED read rejection');
                return result.values;
            };
            bridge.storage.set = async (keys, values) => {
                const result = await fixtureSet(keys, values);
                if (result.rejected) throw Error('INJECTED write rejection');
            };
            bridge.analytics = {send(name, data) { record(name, data); }};
        '''
        fake += '\nbridge.platform.language=' + json.dumps(lang) + ';'
        sdk = 'const FAULT='+json.dumps(fault)+', SAVED_LANGUAGE='+json.dumps(lang)+';\n'+fake
        def fulfill_sdk(route):
            try:
                route.fulfill(content_type='application/javascript', body=sdk)
            except TargetClosedError:
                if not closing: raise
                self.runner.expected.append({'route': 'sdk', 'cancelled_by': 'context closed'})
        closing = []
        context.route(support.SDK, fulfill_sdk)
        page = context.new_page()
        page.set_default_timeout(12000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def checkpoint(name):
            state = self.snapshot(page)
            state.update(reload_epoch=boundary['reload_epoch'], operation_count=len(operations), remote=dict(remote))
            record[name] = state
            self.assertEqual(state['directStorageAccesses'], [])
            return state
        def wait_boundary(predicate):
            deadline = time.monotonic() + 12
            while not predicate():
                self.assertLess(time.monotonic(), deadline, 'SDK boundary condition timed out')
                page.wait_for_timeout(50)
        def boot():
            support.wait_for_boot(page)
            page.wait_for_function("PLATFORM.readiness.state === 'success'")
            # Another context's focus must not pause this page's run.
            page.evaluate('() => { window.onblur = null }')
            self.start(page, touch)
        def shown_after_boot(state):
            # The hint first appears only once boot finished, behind no loading screen.
            self.assertTrue(state['visible']); self.assertEqual(state['alpha'], 1)
            self.assertFalse(state['pressed']); self.assertEqual(state['dismissed'], 0)
            self.assertTrue(state['shown']['bootComplete']); self.assertFalse(state['shown']['loading'])
        page.goto(self.url+'current/index.html')
        boot()
        record['first'] = checkpoint('first')
        self.assertFalse(record['first']['loading'])
        shown_after_boot(record['first'])
        expected = {
            ('en',False):['HOLD','TO GRAPPLE','MOVE RIGHT TO SCORE  →'],
            ('en',True):['TOUCH & HOLD','TO GRAPPLE','MOVE RIGHT TO SCORE  →'],
            ('ru',False):['ДЕРЖИ','— ЗАЦЕПИШЬСЯ','ДВИГАЙСЯ ВПРАВО  →'],
            ('ru',True):['КОСНИСЬ И ДЕРЖИ','— ЗАЦЕПИШЬСЯ','ДВИГАЙСЯ ВПРАВО  →']}
        self.assertEqual(record['first']['lines'],expected[lang,touch])
        # The hint is one canvas-sized sprite under the UI layer.
        geometry = page.evaluate('''() => {const r=canvas.getBoundingClientRect(),s=TUTORIAL_HINT.sprite;
            return {rect:r.toJSON(),sprite:[s.width,s.height],canvas:[canvas.width,canvas.height],
                fits:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight};}''')
        record['geometry'] = geometry
        self.assertTrue(geometry['fits']); self.assertEqual(geometry['sprite'], geometry['canvas'])
        capture = self.out / (case+'.png')
        subprocess.run(['import','-window','root',str(capture)],env=self.env,check=True,timeout=12)
        record['capture'] = {'path':capture.name,'sha256':hashlib.sha256(capture.read_bytes()).hexdigest()}
        # A death would freeze the fade on the death screen; keep the run alive for it.
        page.evaluate('() => { window.__onLethalDeath = onLethalDeath; onLethalDeath = () => {} }')
        # Hold, observe the real grapnel, then release; the trusted press dismisses the hint.
        release = self.press(page, context, touch)
        record['held']=checkpoint('held')
        self.assertTrue(record['held']['throwed']); self.assertTrue(record['held']['pressed'])
        self.assertEqual(record['held']['dismissed'], 1)
        self.assertTrue(self.trusted_press(record['held']['inputs'], touch))
        release()
        record['released']=self.snapshot(page)
        self.assertFalse(record['released']['throwed'])
        page.wait_for_function('TUTORIAL_HINT.done', timeout=20000)
        record['dismissed']=checkpoint('dismissed')
        self.assertFalse(record['dismissed']['visible']); self.assertEqual(record['dismissed']['alpha'], 0)
        # A new run on the same page does not show it again. No game over ad is
        # due this soon, so the death fast-restarts (TASK-370) without the offer.
        restart = page.evaluate('''() => {
            window.__offerShown = 0; let offerVisible = continueOffer.visible;
            Object.defineProperty(continueOffer, 'visible', {configurable: true,
                get: () => offerVisible, set: value => { if (value) __offerShown++; offerVisible = value }});
            const world = probe.calls.filter(c => c.name === 'level_started').at(-1).data.world;
            const starts = probe.calls.filter(c => c.name === 'level_started').length;
            onLethalDeath = window.__onLethalDeath; onLethalDeath();
            return {world, starts}}''')
        page.wait_for_function('''r => runInProgress && !continueOffer.visible && !interstitialPending &&
            probe.calls.filter(c => c.name === 'level_started').length > r.starts''', arg=restart)
        page.wait_for_timeout(200)
        record['restarted']=checkpoint('restarted')
        level = [[c['name'], c['data']] for c in record['restarted']['calls'] if c['name'].startswith('level_')]
        self.assertEqual(level[-2:], [['level_failed', {'world': restart['world']}],
                                      ['level_started', {'world': restart['world']}]])
        self.assertEqual(page.evaluate('__offerShown'), 0)
        self.assertFalse(record['restarted']['visible']); self.assertEqual(record['restarted']['dismissed'], 1)
        if page.evaluate('menu.gamePaused'): page.evaluate('menu.unPause()')
        release = self.press(page, context, touch); release()
        record['pressed_again']=checkpoint('pressed_again')
        self.assertFalse(record['pressed_again']['visible']); self.assertEqual(record['pressed_again']['dismissed'], 1)
        if fault != 'normal':
            rejected = 'read-rejected' if fault == 'storage_rejected' else 'write-rejected'
            wait_boundary(lambda: any(op['op'] == rejected for op in operations))
            self.assertTrue(any(op['op'] == rejected for op in operations))
            before = checkpoint('before_unsaved_reload')
            self.assertTrue(before['done'])
            self.assertNotEqual(remote.get('grapnelninja.tutorialDone'), 'true')
            # Keep the fault active through pagehide so its flush cannot save.
            boundary['reload_epoch'] += 1
            page.reload(); boot()
            unsaved = checkpoint('reload_before_save')
            shown_after_boot(unsaved)
            self.assertFalse(any(op['op'] == 'write-success' for op in operations))
            release = self.press(page, context, touch); release()
            again = checkpoint('dismissed_before_recovery')
            self.assertTrue(again['pressed']); self.assertEqual(again['dismissed'], 1)
            self.assertTrue(self.trusted_press(again['inputs'], touch))
            operation('recovery-enabled')
            boundary['fault'] = 'normal'
            recovery = len(operations)
            # Poll only the SDK fixture; application retries and reconciliation do the save.
            page.evaluate('onLethalDeath()')
            wait_boundary(lambda: any(op['op'] == 'write-success' for op in operations[recovery:]))
            checkpoint('confirmed_save')
        # Dismissal is not stored: the legacy tutorialDone key is only ever written as 'false'.
        self.assertFalse(any(dict(zip(op['keys'], op['values'])).get('grapnelninja.tutorialDone') == 'true'
                             for op in operations if op['op'].startswith('write')))
        boundary['reload_epoch'] += 1
        page.reload(); boot()
        record['reload']=checkpoint('reload')
        shown_after_boot(record['reload'])
        self.assertFalse(record['reload']['loading'])
        closing.append(True)
        context.close()
        self.runner.settle(self.browser)
        record['runner_errors'] = self.runner.unexpected[unexpected:]
        self.assertEqual(record['runner_errors'], [], 'unexpected runner errors')
        self.assertEqual(errors,[])
        record['verdict']='PASS shown after boot, device wording, trusted-press fade, one tutorial_dismissed, hidden on restart, shown again after reload'
        print('PASS '+case+': '+record['verdict'][5:],flush=True)

    def test_en_desktop(self): self.matrix('en',False)
    def test_en_touch(self): self.matrix('en',True)
    def test_ru_desktop(self): self.matrix('ru',False)
    def test_ru_touch(self): self.matrix('ru',True)
    def test_storage_read_rejection(self): self.matrix('en',False,'storage_rejected')
    def test_storage_write_rejection(self): self.matrix('en',False,'write_rejected')


if __name__ == '__main__': unittest.main()
