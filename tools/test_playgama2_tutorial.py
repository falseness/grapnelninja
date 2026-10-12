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
        paths += ['tutorial.js','tools/test_playgama2_tutorial.py']
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
        return page.evaluate('''() => ({ms:performance.now(), visible:!TUTORIAL.element.hidden,
            text:TUTORIAL.text.textContent, done:PROGRESS.getTutorialDone(),
            loading:!document.getElementById('loading').hidden, readiness:PLATFORM.readiness,
            throwed:!!grapnel?.throwed, calls:probe.calls, inputs:window.inputs,
            directStorageAccesses:window.directStorageAccesses})''')

    def start(self, page, touch):
        point = page.evaluate('''() => { const b=menu.classicVersionButton.background,r=canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}; }''')
        if touch: page.touchscreen.tap(**point)
        else: page.mouse.click(**point)
        page.wait_for_function('!menu.visible && !!ninja')
        page.wait_for_function('!unTouch')

    def matrix(self, lang, touch, fault='normal'):
        case = lang + ('-touch' if touch else '-desktop') + ('' if fault == 'normal' else '-' + fault)
        record = self.results[case] = {'utc':datetime.now(timezone.utc).isoformat(), 'fault':fault}
        unexpected = len(self.runner.unexpected)
        context = self.browser.new_context(viewport={'width':800 if touch else 1280,'height':450 if touch else 720}, has_touch=touch)
        self.addCleanup(context.close)
        context.add_init_script("window.inputs=[]; for(const name of ['mousedown','mouseup','touchstart','touchend','click']) window.addEventListener(name,e=>inputs.push({name,trusted:e.isTrusted,target:e.target.tagName,ms:performance.now()}),true)")
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
        page.goto(self.url+'current/index.html')
        support.wait_for_boot(page)
        page.wait_for_function("PLATFORM.readiness.state === 'success'")
        record['boot'] = self.snapshot(page)
        self.assertFalse(record['boot']['loading'])
        self.assertFalse(record['boot']['visible'])
        self.start(page,touch)
        record['first'] = self.snapshot(page)
        self.assertTrue(record['first']['visible'])
        self.assertFalse(record['first']['done'])
        expected = {
            ('en',False):'Hold the mouse button to grapple. Release to let go. Move right to score.',
            ('en',True):'Touch and hold to grapple. Lift your finger to let go. Move right to score.',
            ('ru',False):'Удерживайте кнопку мыши, чтобы зацепиться. Отпустите, чтобы отцепиться. Двигайтесь вправо, чтобы набирать очки.',
            ('ru',True):'Коснитесь и удерживайте палец, чтобы зацепиться. Отпустите, чтобы отцепиться. Двигайтесь вправо, чтобы набирать очки.'}
        self.assertEqual(record['first']['text'],expected[lang,touch])
        geometry = page.evaluate('''() => {const a=TUTORIAL.element.getBoundingClientRect(),b=MUTE_BUTTON.element.getBoundingClientRect();
            const r=canvas.getBoundingClientRect(), m=menu.button.background;
            const hud={left:r.x+m.x*scale[version]*r.width/width,top:r.y+m.y*scale[version]*r.height/height,
                right:r.x+(m.x+m.width)*scale[version]*r.width/width,bottom:r.y+(m.y+m.height)*scale[version]*r.height/height};
            const overlap=(x,y)=>x.left<y.right&&x.right>y.left&&x.top<y.bottom&&x.bottom>y.top;
            return {rect:a.toJSON(),fits:a.left>=0&&a.top>=0&&a.right<=innerWidth&&a.bottom<=innerHeight,
                muteOverlap:overlap(a,b),hudOverlap:overlap(a,hud),clipped:TUTORIAL.element.scrollWidth>TUTORIAL.element.clientWidth};}''')
        record['geometry'] = geometry
        self.assertTrue(geometry['fits']); self.assertFalse(geometry['clipped'])
        self.assertFalse(geometry['muteOverlap']); self.assertFalse(geometry['hudOverlap'])
        capture = self.out / (case+'.png')
        subprocess.run(['import','-window','root',str(capture)],env=self.env,check=True,timeout=12)
        record['capture'] = {'path':capture.name,'sha256':hashlib.sha256(capture.read_bytes()).hexdigest()}
        button=page.locator('#tutorial button')
        if touch: button.tap()
        else: button.click()
        record['dismissed']=checkpoint('dismissed')
        self.assertFalse(record['dismissed']['visible']); self.assertTrue(record['dismissed']['done'])
        self.assertTrue(any(e['trusted'] and e['target']=='BUTTON' and e['name']=='click' for e in record['dismissed']['inputs']))
        # Hold, observe the real grapnel, then release without changing application state.
        if touch:
            cdp=context.new_cdp_session(page)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':600,'y':140}]})
        else:
            page.mouse.move(850,200); page.mouse.down()
        page.wait_for_function('grapnel.throwed')
        record['held']=self.snapshot(page)
        self.assertTrue(record['held']['throwed'])
        if touch: cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else: page.mouse.up()
        record['released']=self.snapshot(page)
        self.assertFalse(record['released']['throwed'])
        if fault != 'normal':
            rejected = 'read-rejected' if fault == 'storage_rejected' else 'write-rejected'
            wait_boundary(lambda: any(op['op'] == rejected for op in operations))
            self.assertTrue(any(op['op'] == rejected for op in operations))
            before = checkpoint('before_unsaved_reload')
            self.assertTrue(before['done'])
            self.assertNotEqual(remote.get('grapnelninja.tutorialDone'), 'true')
            # Keep the fault active through pagehide so its flush cannot save.
            boundary['reload_epoch'] += 1
            page.reload(); support.wait_for_boot(page)
            self.start(page, touch)
            unsaved = checkpoint('reload_before_save')
            self.assertFalse(unsaved['done']); self.assertTrue(unsaved['visible'])
            self.assertFalse(any(op['op'] == 'write-success' for op in operations))
            page.locator('#tutorial button').click()
            again = checkpoint('dismissed_before_recovery')
            self.assertTrue(again['done']); self.assertFalse(again['visible'])
            self.assertTrue(any(e['trusted'] and e['target']=='BUTTON' and e['name']=='click' for e in again['inputs']))
            operation('recovery-enabled')
            boundary['fault'] = 'normal'
        # Poll only the SDK fixture; application retries and reconciliation do the save.
        wait_boundary(lambda: remote.get('grapnelninja.tutorialDone') == 'true')
        saved = checkpoint('confirmed_save')
        self.assertTrue(saved['done'])
        self.assertTrue(any(op['op'] == 'write-success' and
                            dict(zip(op['keys'], op['values'])).get('grapnelninja.tutorialDone') == 'true'
                            for op in operations))
        boundary['reload_epoch'] += 1
        page.reload(); support.wait_for_boot(page)
        self.start(page,touch)
        record['reload']=checkpoint('reload')
        self.assertFalse(record['reload']['visible']); self.assertTrue(record['reload']['done'])
        self.assertFalse(record['reload']['loading'])
        closing.append(True)
        context.close()
        self.runner.settle(self.browser)
        record['runner_errors'] = self.runner.unexpected[unexpected:]
        self.assertEqual(record['runner_errors'], [], 'unexpected runner errors')
        self.assertEqual(errors,[])
        record['verdict']='PASS first display, device wording, native dismissal, hold/release, readiness before dismissal, persisted reload'
        print('PASS '+case+': '+record['verdict'][5:],flush=True)

    def test_en_desktop(self): self.matrix('en',False)
    def test_en_touch(self): self.matrix('en',True)
    def test_ru_desktop(self): self.matrix('ru',False)
    def test_ru_touch(self): self.matrix('ru',True)
    def test_storage_read_rejection(self): self.matrix('en',False,'storage_rejected')
    def test_storage_write_rejection(self): self.matrix('en',False,'write_rejected')


if __name__ == '__main__': unittest.main()
