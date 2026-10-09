"""Controlled SDK boundary faults against the real application; native X11 proof."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest

import test_playgama2_bridge as support

ROOT = Path(__file__).resolve().parents[1]
INSTRUMENT = r"""
window.bootProbe = {events: [], maxLoops: 0, inputListeners: 0};
window.mark = (name, data) => {
    bootProbe.events.push({name, ms: performance.now(), data});
    if (name === 'sdk_start') {
        let environment = PLATFORM.environment;
        Object.defineProperty(PLATFORM, 'environment', {
            get: () => environment,
            set: value => { environment = value; mark(value); }
        });
    }
};
const raf = window.requestAnimationFrame.bind(window);
const cancel = window.cancelAnimationFrame.bind(window);
const loops = new Set();
window.requestAnimationFrame = fn => {
    let id = raf(t => { loops.delete(id); fn(t); });
    if (fn.name === 'gameLoop') { loops.add(id); bootProbe.maxLoops = Math.max(bootProbe.maxLoops, loops.size); }
    return id;
};
window.cancelAnimationFrame = id => { loops.delete(id); cancel(id); };
const add = EventTarget.prototype.addEventListener;
EventTarget.prototype.addEventListener = function(name, fn, opts) {
    if (name === 'mousedown' && fn.name === 'click' && this === document) bootProbe.inputListeners++;
    return add.call(this, name, fn, opts);
};
new MutationObserver(() => {
    const el = document.getElementById('loading');
    if (el && el.hidden && !bootProbe.events.some(e => e.name === 'menu')) mark('menu');
}).observe(document, {subtree:true, attributes:true, attributeFilter:['hidden']});
"""


class Playgama2BootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.timings = {}
        cls.networks = {}
        cls.captures = []

    @classmethod
    def tearDownClass(cls):
        for name, data in [('timings.json', cls.timings), ('network.json', cls.networks), ('captures.json', cls.captures)]:
            (cls.out / name).write_text(json.dumps(data, indent=2) + '\n')

    click_mode = support.Playgama2BridgeTests.click_mode

    def capture(self, page, name):
        page.wait_for_timeout(100)
        subprocess.run(['import', '-window', 'root', str(self.out / (name + '.png'))],
                       env=self.env, check=True, timeout=12)
        self.captures.append({'path': name + '.png',
            'sha256': hashlib.sha256((self.out / (name + '.png')).read_bytes()).hexdigest(),
            'state': page.evaluate('({loadingHidden:document.getElementById("loading").hidden, retryVisible:!document.getElementById("boot-retry").hidden, menuVisible:menu.visible, version:version || null, ms:performance.now()})')})

    def open_case(self, fault, lang='en'):
        context = self.browser.new_context(viewport={'width':1280, 'height':720}, locale=lang)
        self.addCleanup(context.close)
        context.add_init_script(INSTRUMENT)
        if fault == 'retry':
            # A real canvas API failure, once per session; no application function replaced.
            context.add_init_script("""const original = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(...args) {
                    const ctx = original.apply(this, args);
                    if (ctx && !sessionStorage.failedOnce) {
                        const fill = ctx.fillRect.bind(ctx);
                        ctx.fillRect = (...a) => {
                            sessionStorage.failedOnce = 'yes'; ctx.fillRect = fill;
                            throw Error('INJECTED one-shot canvas boot failure');
                        };
                    }
                    return ctx;
                };""")
        pending = []
        def sdk(route):
            if fault in ('download_stalled', 'download_late'):
                pending.append(route)
            else:
                route.fulfill(content_type='application/javascript', body=body)
        body = 'const FAULT = ' + json.dumps('init_rejected' if fault == 'init_rejected' else 'normal') + '; const SAVED_LANGUAGE = ' + json.dumps(lang) + ';\n' + support.FAKE
        if fault in ('init_unresolved', 'init_late'):
            body = body.replace("record('initialize', options);", "record('initialize', options); await new Promise(resolve => window.releaseInit = resolve);")
        context.route(support.SDK, sdk)
        page = context.new_page()
        page.set_default_timeout(10000)
        requests, console, errors = [], [], []
        page.on('request', lambda r: requests.append({'phase':'request', 'url':r.url}))
        page.on('response', lambda r: requests.append({'phase':'response', 'url':r.url, 'status':r.status}))
        page.on('console', lambda m: console.append(m.text))
        page.on('pageerror', lambda e: errors.append(str(e)))
        # Timestamp the real inline application start without changing its behavior.
        context.route('**/index.html', lambda r: r.fulfill(content_type='text/html', body=(ROOT/'index.html').read_text().replace("            'use strict'", "            'use strict'; mark('sdk_start');")))
        page.goto(self.url + 'current/index.html', wait_until='domcontentloaded')
        self.assertTrue(page.locator('script[src="'+support.SDK+'"]').evaluate('(s) => s.async'))
        self.networks[fault + '-' + lang] = {'requests': requests, 'async': True, 'console': console}
        return page, pending, body, errors

    def test_fault_deadlines_and_late_attachment(self):
        for fault in ['download_stalled', 'init_rejected', 'init_unresolved', 'init_late', 'download_late']:
            with self.subTest(fault=fault):
                page, pending, body, errors = self.open_case(fault)
                support.wait_for_boot(page)
                self.assertEqual(page.evaluate('PLATFORM.environment'), 'disabled')
                self.assertFalse(page.locator('#boot-retry').is_visible())
                self.click_mode(page, 'classic')
                page.evaluate("mark('input', {version, visible:menu.visible}); window.originalNinja = ninja")
                self.capture(page, fault + '-input')
                if fault in ('init_late', 'download_late'):
                    if pending:
                        pending.pop().fulfill(content_type='application/javascript', body=body)
                    else:
                        page.evaluate('releaseInit()')
                    page.wait_for_function("PLATFORM.environment === 'playgama'")
                    page.evaluate("Promise.all([boot(), boot(), PLATFORM.init(), PLATFORM.init()]); PLATFORM.gameReady()")
                    page.wait_for_timeout(150)
                    self.assertTrue(page.evaluate('originalNinja === ninja && !menu.visible'))
                    data = page.evaluate('({calls:probe.calls, subscriptions:probe.subscriptions})')
                    self.assertEqual(data['subscriptions'], {'pause':1,'audio':1,'interstitial':1,'rewarded':1})
                    for name in ['initialize','game_ready']:
                        self.assertEqual(sum(c['name']==name for c in data['calls']), 1)
                    self.capture(page, fault + '-recovery')
                else:
                    data = None
                result = page.evaluate('bootProbe')
                events = {e['name']:e['ms'] for e in result['events']}
                result['sdk_wait_ms'] = events['disabled'] - events['sdk_start']
                result['menu_ms'] = events['menu'] - events['sdk_start']
                self.assertLessEqual(result['sdk_wait_ms'], 3000)
                self.assertLessEqual(result['menu_ms'], 5000)
                result['input_ms'] = events['input'] - events['sdk_start']
                self.assertLessEqual(result['input_ms'], 5000)
                self.assertEqual(result['maxLoops'], 1)
                self.assertEqual(result['inputListeners'], 1)
                self.assertEqual(errors, [])
                requests = self.networks[fault + '-en']['requests']
                self.assertTrue(any(r['url'] == support.SDK and r['phase'] == 'request' for r in requests))
                self.assertTrue(any(r['url'].endswith('/events.js') and r.get('status') == 200 for r in requests))
                if fault == 'download_stalled':
                    self.assertFalse(any(r['url'] == support.SDK and r['phase'] == 'response' for r in requests))
                self.networks[fault + '-en']['verdict'] = 'PASS async SDK; local scripts HTTP 200; input works'
                result.update(verdict='PASS SDK <=3000ms; menu <=5000ms; real input; one loop/listener', sdk=data)
                self.timings[fault] = result
                print(f"PASS {fault}: SDK={result['sdk_wait_ms']:.1f}ms menu={result['menu_ms']:.1f}ms input={result['input_ms']:.1f}ms/classic loops=1 listeners=1" + (' initialize=1 game_ready=1 subscriptions=1 each; same ninja' if data else ''), flush=True)
                for route in pending:
                    route.abort()
                page.context.close()

    def test_localized_boot_failure_and_real_retry(self):
        for lang, message, button in [('en','The game could not start. Please retry.','Retry'), ('ru','Не удалось запустить игру. Попробуйте ещё раз.','Повторить')]:
            with self.subTest(lang=lang):
                page, _, _, errors = self.open_case('retry', lang)
                page.locator('#boot-retry').wait_for(state='visible')
                self.assertEqual(page.locator('#loading-progress').inner_text(), message)
                self.assertEqual(page.locator('#boot-retry').inner_text(), button)
                self.assertTrue(page.evaluate("sessionStorage.failedOnce === 'yes'"))
                self.assertEqual(page.evaluate('bootProbe.maxLoops'), 0)
                self.capture(page, 'retry-' + lang + '-failure')
                failure = page.evaluate('bootProbe')
                with page.expect_navigation(wait_until='domcontentloaded'):
                    page.locator('#boot-retry').click()
                support.wait_for_boot(page)
                self.click_mode(page, 'classic')
                page.evaluate("mark('input'); boot(); boot()")
                self.capture(page, 'retry-' + lang + '-recovered')
                result = page.evaluate('bootProbe')
                self.assertEqual(result['maxLoops'], 1)
                self.assertEqual(result['inputListeners'], 1)
                self.assertEqual(errors, [])
                self.timings['retry-' + lang] = {'failure': failure, 'recovery': result, 'verdict':'PASS localized failure; actual reload retry; input; one loop/listener'}
                self.assertTrue(any('Application boot failed' in x for x in self.networks['retry-' + lang]['console']))
                print('PASS retry-' + lang + ': localized error and button; canvas boundary failure; actual retry; input=classic loops=1 listeners=1', flush=True)
                page.context.close()


if __name__ == '__main__':
    unittest.main()
