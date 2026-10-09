"""Storage boundary fault probes using the production browser application."""
import hashlib
import json
import subprocess
import unittest

import test_playgama2_bridge as support
from test_playgama2_boot import INSTRUMENT

REMOTE = {'grapnelninja.records': {'classic': 80, 'bad': 30},
          'grapnelninja.time': 600, 'grapnelninja.lang': 'ru'}
BOUNDARY = r"""
window.storageFault = CASE;
window.remote = INITIAL;
window.storageTrace = [];
const trace = (op, data) => storageTrace.push({op, data: JSON.parse(JSON.stringify(data)), ms: performance.now()});
bridge.storage.get = async keys => {
    trace('read-start', keys);
    if (storageFault === 'reject-read') throw Error('INJECTED rejected read');
    if (storageFault === 'late' || storageFault === 'no-local')
        await new Promise(resolve => window.releaseRead = resolve);
    const result = keys.map(k => remote[k] ?? null);
    trace('read-result', result);
    return result;
};
bridge.storage.set = async (keys, values) => {
    trace('write-start', {keys, values});
    if (storageFault === 'reject-write') { trace('write-rejected', values); throw Error('INJECTED rejected write'); }
    if (storageFault === 'delay-write') await new Promise(resolve => window.releaseWrite = resolve);
    keys.forEach((k,i) => remote[k] = values[i]);
    trace('write-result', remote);
};
"""
STATE = "({records:{classic:scoreText.record.classic,bad:scoreText.record.bad},time:PROGRESS.getTime(),lang:PROGRESS.getLang()})"


class Playgama2StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.cases, cls.timings, cls.captures = {}, {}, []

    @classmethod
    def tearDownClass(cls):
        for name, data in [('storage-cases.json', cls.cases), ('timings.json', cls.timings), ('captures.json', cls.captures)]:
            (cls.out / name).write_text(json.dumps(data, indent=2) + '\n')

    click_mode = support.Playgama2BridgeTests.click_mode

    def open_case(self, case):
        context = self.browser.new_context(viewport={'width':1280, 'height':720})
        self.addCleanup(context.close)
        context.add_init_script(INSTRUMENT)
        context.add_init_script("window.localStorageAccesses=0; Object.defineProperty(window,'localStorage',{get(){localStorageAccesses++; throw Error('Direct local storage is forbidden')}})")
        config = {'case': case, 'remote': REMOTE}
        def sdk(route):
            body = "const FAULT='normal', SAVED_LANGUAGE='ru';\n" + support.FAKE
            body += '\nconst CASE=' + json.dumps(config['case']) + ', INITIAL=' + json.dumps(config['remote']) + ';\n' + BOUNDARY
            route.fulfill(content_type='application/javascript', body=body)
        context.route(support.SDK, sdk)
        context.route('**/index.html', lambda r: r.fulfill(content_type='text/html', body=(support.ROOT/'index.html').read_text().replace("            'use strict'", "            'use strict'; mark('sdk_start');")))
        page = context.new_page()
        page.set_default_timeout(10000)
        errors, console = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: console.append(m.text))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'current/index.html', wait_until='domcontentloaded')
        support.wait_for_boot(page)
        events = page.evaluate('bootProbe.events')
        times = {e['name']: e['ms'] for e in events}
        start = page.evaluate("storageTrace.find(x=>x.op==='read-start').ms")
        # Menu includes rendering after the read deadline; measure the read itself
        # with loading.starting DOM text observed by a boundary-only observer.
        read_done = page.evaluate('window.storageFinished')
        self.assertLessEqual(read_done - start, 1500)
        self.assertLessEqual(times['menu'] - times['sdk_start'], 5000)
        self.timings[case] = {'read_ms':read_done-start, 'menu_ms':times['menu']-times['sdk_start'], 'verdict':'PASS read <=1500ms; interactive menu <=5000ms'}
        path = case + '-menu.png'
        subprocess.run(['import','-window','root', str(self.out/path)], env=self.env, check=True, timeout=12)
        self.captures.append({'path':path,'sha256':hashlib.sha256((self.out/path).read_bytes()).hexdigest(), 'loadingHidden':page.locator('#loading').evaluate('(e)=>e.hidden'), 'menuVisible':page.evaluate('menu.visible')})
        self.cases[case] = {'initial':page.evaluate(STATE), 'delayed_remote':REMOTE, 'console':console}
        return page, config

    def test_storage_recovery_and_reload(self):
        for case in ['normal', 'late', 'reject-read', 'reject-write', 'delay-write', 'no-local']:
            with self.subTest(case=case):
                page, config = self.open_case(case)
                before = page.evaluate(STATE)
                if case in ('normal','reject-write','delay-write'):
                    self.assertEqual(before, {'records':{'classic':80,'bad':30},'time':600,'lang':'ru'})
                else:
                    self.assertEqual(page.evaluate("storageTrace.filter(x=>x.op==='write-start').length"), 0)
                if case in ('late', 'no-local', 'reject-read'):
                    self.click_mode(page, 'classic')
                    page.evaluate("emitHost('pause',true)")
                    self.timings[case]['degraded_input'] = 'PASS real menu input while remote unknown'
                page.evaluate("scoreText.record.classic=100; PROGRESS.setTime(PROGRESS.getTime()+25); setLanguage('en'); PROGRESS.flush()")
                self.cases[case]['session_changes'] = page.evaluate(STATE)
                if case in ('late','no-local','reject-read'):
                    self.assertEqual(page.evaluate("storageTrace.filter(x=>x.op==='write-start').length"), 0)
                    page.evaluate("storageFault='normal'; if(window.releaseRead) releaseRead()")
                if case == 'delay-write':
                    # Probe the actual bounded production wrapper, while the original
                    # pending write is still held by the boundary.
                    page.wait_for_timeout(1550)
                    self.assertFalse(page.evaluate("PLATFORM.storage.setMany({'grapnelninja.lang':'ru'})"))
                    self.click_mode(page,'classic')
                    page.evaluate("emitHost('pause',true)")
                    self.assertTrue(page.evaluate('menu.gamePaused'))
                    page.evaluate("storageFault='normal'; releaseWrite()")
                    self.timings[case]['write_verdict'] = 'PASS pending write bounded; real input and rendering continue; no overlapping writes'
                elif case == 'reject-write':
                    page.wait_for_timeout(100)
                    self.assertTrue(page.evaluate("storageTrace.some(x=>x.op==='write-rejected')"))
                    # Unsaved changes stay in memory until the SDK write recovers.
                    # No private browser-storage journal may bypass the SDK.
                    self.cases[case]['before_recovery_trace'] = page.evaluate('storageTrace')
                    page.evaluate("storageFault='normal'")
                page.wait_for_function("storageTrace.some(x=>x.op==='write-result')")
                page.wait_for_timeout(1200 if case == 'delay-write' else 50)
                final = page.evaluate(STATE)
                self.assertEqual(final['records'], {'classic':100,'bad':30})
                # Delayed-write real gameplay may add a second; never regress.
                self.assertGreaterEqual(final['time'],625)
                self.assertEqual(final['lang'],'en')
                self.assertEqual(page.evaluate('I18N.language'),'en')
                self.assertEqual(page.evaluate('localStorageAccesses'), 0)
                trace = page.evaluate('storageTrace')
                self.assertLess(next(i for i,x in enumerate(trace) if x['op']=='read-result'), next(i for i,x in enumerate(trace) if x['op']=='write-start'))
                self.cases[case].update(trace=trace,result=final)
                config.update(case='normal', remote=page.evaluate('remote'))
                page.reload(wait_until='domcontentloaded')
                support.wait_for_boot(page)
                reloaded = page.evaluate(STATE)
                self.assertEqual(reloaded,final)
                self.cases[case].update(reloaded=reloaded, verdict='PASS no default writes before reconciliation; records/time monotonic; session language wins; recovery/reload preserved')
                if case != 'delay-write': self.click_mode(page,'classic')
                print('PASS '+case+': read <=1500ms; menu <=5000ms; ordered read/write; record=100/30 time>=625 language=en; recovery/reload; real input',flush=True)
                page.context.close()

    def test_record_only_delayed_read_recovery_and_sdk_reload(self):
        page, config = self.open_case('late')
        expected = {'records': {'classic': 100, 'bad': 30}, 'time': 600, 'lang': 'ru'}
        self.cases['record-only'] = {}
        self.assertFalse(page.evaluate('PLATFORM.storage.remoteKnown'))
        page.evaluate('scoreText.record.classic=100; PROGRESS.flush()')
        self.cases['record-only']['session_changes'] = page.evaluate(STATE)
        self.assertEqual(page.evaluate('scoreText.record.classic'), 100)
        self.assertEqual(page.evaluate("storageTrace.filter(x=>x.op==='write-start').length"), 0)
        self.cases['record-only']['before_recovery_trace'] = page.evaluate('storageTrace')
        page.evaluate('PROGRESS.save(); PROGRESS.flush()')
        self.assertEqual(page.evaluate('scoreText.record.classic'), 100)
        self.assertEqual(page.evaluate('localStorageAccesses'), 0)
        self.assertEqual(page.evaluate("storageTrace.filter(x=>x.op==='write-start').length"), 0)
        page.evaluate("storageFault='normal'; releaseRead()")
        page.wait_for_function("storageTrace.some(x=>x.op==='write-result')")
        self.assertEqual(page.evaluate(STATE), expected)
        trace = page.evaluate('storageTrace')
        self.assertLess(next(i for i,x in enumerate(trace) if x['op']=='read-result'), next(i for i,x in enumerate(trace) if x['op']=='write-start'))
        self.cases['record-only'].update(trace=trace, result=page.evaluate(STATE))
        config.update(case='normal', remote=page.evaluate('remote'))
        page.reload(wait_until='domcontentloaded')
        support.wait_for_boot(page)
        self.assertEqual(page.evaluate(STATE), expected)
        self.assertEqual(page.evaluate('localStorageAccesses'), 0)
        verdict = 'PASS memory retains pending record100; SDK recovery persists it; SDK reload record=100/30 time=600 language=ru; zero direct localStorage accesses'
        self.cases['record-only'].update(reloaded=page.evaluate(STATE), verdict=verdict)
        print(verdict, flush=True)
        page.context.close()

    def test_write_deadline(self):
        page, _ = self.open_case('bounded-write')
        result = page.evaluate("""async () => {
            storageFault='delay-write';
            const start=performance.now();
            const ok=await PLATFORM.storage.setMany(Object.fromEntries(PROGRESS.keys.map(k=>[k,remote[k]])));
            return {ok, elapsed_ms:performance.now()-start};
        }""")
        self.assertFalse(result['ok'])
        self.assertLessEqual(result['elapsed_ms'],1500)
        self.assertGreaterEqual(result['elapsed_ms'],1150)
        self.click_mode(page,'classic')
        result['verdict']='PASS delayed write returns false <=1500ms; real input works while write unresolved'
        self.timings['bounded-write']['write']=result
        self.cases['bounded-write'].update(trace=page.evaluate('storageTrace'), result=page.evaluate(STATE), verdict=result['verdict'])
        print('PASS bounded-write: delayed write returns false <=1500ms; real input while unresolved',flush=True)
        page.context.close()


# Observe DOM platform output; never replace a production method.
INSTRUMENT += r"""
new MutationObserver(() => {
    const el = document.getElementById('loading-progress');
    if (el && /Starting|Запуск/.test(el.textContent) && !window.storageFinished)
        window.storageFinished = performance.now();
}).observe(document, {subtree:true, childList:true, characterData:true});
"""
