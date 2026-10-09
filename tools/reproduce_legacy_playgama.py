"""TASK-235 offline legacy boot diagnosis.

Run: python3 artifacts/TASK-235/reproduce.py
Requires Python Playwright, installed Chromium, Xvfb and ImageMagick import. No remote SDK is contacted.
Extracted bytes are unchanged; instrumentation observes listeners/canvas drawing.
Browser actions have 12 s deadlines; the whole run has a 150 s deadline.
The real legacy init watchdog remains 8 s.
"""
import os
import signal
import subprocess
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from playwright.sync_api import sync_playwright
import hashlib
import json
from pathlib import Path
import time
import zipfile
from contextlib import ExitStack

from browser_test_support import QuietHandler, OfflineBrowser

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/TASK-235'
CASES = ('normal', 'sdk_stalled', 'init_rejected', 'init_unresolved',
         'storage_unresolved', 'readiness_rejected')
SDK = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


OBSERVER = r"""(() => {
 window.__probe = {stages: [], listeners: [], draws: 0, readyCalls: 0, readyResolves: 0, readyRejects: 0};
 window.__stage = (name) => __probe.stages.push({name, ms: performance.now()});
 __stage('document_start');
 const add = EventTarget.prototype.addEventListener;
 EventTarget.prototype.addEventListener = function(name, ...args) {
   if(this === document && ['mousedown','touchstart','keydown'].includes(name)) {
     __probe.listeners.push(name); __stage('input_attached:' + name);
   }
   return add.call(this, name, ...args);
 };
 const text = CanvasRenderingContext2D.prototype.fillText;
 CanvasRenderingContext2D.prototype.fillText = function(...args) {
   if (!__probe.draws++) __stage('first_canvas_text');
   return text.apply(this, args);
 };
 new MutationObserver(() => {
   const el = document.getElementById('loading');
   const state = !el ? 'absent' : el.hidden ? 'hidden' : el.textContent.trim();
   if(state !== window.__lastLoading) { __stage('loading:' + state); window.__lastLoading = state; }
 }).observe(document, {subtree:true, childList:true, attributes:true, characterData:true});
})()"""

STUB = r"""
__stage('sdk_executed');
window.bridge = {
 initialize() {
   __stage('init_call');
   if (FAULT === 'init_unresolved') return new Promise(() => {});
   if (FAULT === 'init_rejected') { __stage('init_reject'); return Promise.reject(new Error('INJECTED init rejection')); }
   return Promise.resolve().then(() => __stage('init_resolve'));
 },
 EVENT_NAME: {},
 platform: {id:'offline-fixture', language:'en', isAudioEnabled:true, on() {},
   sendMessage(name) {
     if(name !== 'game_ready') return Promise.resolve();
     __probe.readyCalls++; __stage('readiness_call');
     if(FAULT === 'readiness_rejected') {
       __probe.readyRejects++; __stage('readiness_reject');
       return Promise.reject(new Error('INJECTED readiness rejection'));
     }
     return Promise.resolve().then(() => {__probe.readyResolves++; __stage('readiness_resolve');});
   }
 },
 advertisement: {on() {}, isRewardedSupported:false},
 storage: {
   get() { __stage('storage_call');
     if(FAULT === 'storage_unresolved') return new Promise(() => {});
     return Promise.resolve([]).then(v => {__stage('storage_resolve'); return v;});
   }, set() {return Promise.resolve();}
 }
};
"""

STATE = r"""() => {
 const el = document.getElementById('loading');
 return {...__probe, loadingPresent:!!el, loadingVisible:!!el && !el.hidden,
 loadingText:el ? el.textContent.trim() : null,
 menuVisible:typeof menu !== 'undefined' ? menu.visible : null,
 environment:typeof PLATFORM !== 'undefined' ? PLATFORM.environment : null,
 canvasPresent:!!document.getElementById('canvas')};
}"""


def main():
    signal.alarm(150)  # hard finite deadline, including browser protocol operations
    OUT.mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'artifacts/playgama/grapnelninja-playgama.zip'
    extracted = OUT / 'extracted'
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            dest = (extracted / name).resolve()
            if not dest.is_relative_to(extracted.resolve()):
                raise ValueError('Unsafe ZIP member')
        z.extractall(extracted)
    hashes = {str(p.relative_to(extracted)): digest(p) for p in sorted(extracted.rglob('*')) if p.is_file()}
    write('archive.json', {'archive':str(archive.relative_to(ROOT)), 'sha256':digest(archive),
                          'identity':'saved local legacy archive; remote upload identity unknown',
                          'extracted_source_hashes':hashes})
    results = []
    with (OUT / 'browser.log').open('w', buffering=1) as log, ExitStack() as stack:
        # A native X display capture also works before Chromium's first paint;
        # page.screenshot waits for that paint when a head script stalls parsing.
        read_fd, write_fd = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x900x24'], pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(write_fd)
        stack.callback(xvfb.wait)
        stack.callback(xvfb.terminate)
        with os.fdopen(read_fd) as pipe:
            display = ':' + pipe.readline().strip()
        env = {**os.environ, 'DISPLAY':display}
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(extracted)))
        stack.callback(server.server_close)
        Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/'
        pw = stack.enter_context(sync_playwright())
        native = pw.chromium.launch(headless=False, env=env, args=['--no-sandbox', '--window-size=1280,850'])
        stack.callback(native.close)
        browser = OfflineBrowser(native)
        for fault in CASES:
            context = browser.new_context(viewport={'width':1280, 'height':720}, device_scale_factor=1)
            context.add_init_script(OBSERVER)
            pending = []
            def sdk_route(route):
                if fault == 'sdk_stalled':
                    pending.append(route)  # deliberately neither abort nor fulfill until observation ends
                else:
                    route.fulfill(content_type='application/javascript', body='const FAULT = ' + json.dumps(fault) + ';\n' + STUB)
            context.route(SDK, sdk_route)
            page = context.new_page()
            page.set_default_timeout(12000)
            errors = []
            observing = True
            def event(kind, message):
                if not observing:
                    return
                item = {'kind':kind, 'message':message, 'elapsed_ms':round((time.monotonic()-began)*1000)}
                errors.append(item)
                log.write(f'{fault} EVENT {json.dumps(item)}\n')
            began = time.monotonic()
            page.on('console', lambda msg: event('console:'+msg.type, msg.text))
            page.on('pageerror', lambda error: event('pageerror', str(error)))
            page.goto(url, wait_until='commit', timeout=12000)
            blocked = fault in ('sdk_stalled', 'storage_unresolved')
            if blocked:
                page.wait_for_timeout(9500)  # exceeds the real init watchdog
            else:
                page.wait_for_function("() => document.getElementById('loading')?.hidden === true", timeout=12000)
                page.wait_for_timeout(200)
            before = page.evaluate(STATE)
            screenshot = f'{fault}.png'
            subprocess.run(['import', '-window', 'root', str(OUT / screenshot)], env=env, check=True, timeout=12)
            # Real DOM input against the legacy menu button (not a direct menu.click call).
            point = page.evaluate("""() => {
              if(typeof menu === 'undefined') return {x:640,y:360};
              const b = menu.classicVersionButton.background;
              const c = document.getElementById('canvas'); const r = c.getBoundingClientRect();
              return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height};
            }""")
            page.mouse.click(point['x'], point['y'])
            page.wait_for_timeout(100)
            after = page.evaluate(STATE)
            checks = {
                'no_uncaught_errors':not any(e['kind']=='pageerror' for e in errors),
                'ready_counts':(before['readyCalls'],before['readyResolves'],before['readyRejects']) ==
                    ((1,1,0) if fault=='normal' else (1,0,1) if fault=='readiness_rejected' else (0,0,0)),
            }
            if fault == 'sdk_stalled':
                checks['parser_block_reproduced'] = not before['canvasPresent'] and not before['loadingPresent'] and not before['listeners'] and not before['draws']
            elif fault == 'storage_unresolved':
                checks['storage_block_reproduced'] = before['loadingVisible'] and not before['listeners'] and not before['draws'] and after['menuVisible'] == before['menuVisible']
            else:
                checks['menu_rendered_and_input_works'] = before['menuVisible'] and before['draws'] > 0 and not before['loadingVisible'] and after['menuVisible'] is False
                checks['environment'] = before['environment'] == ('disabled' if fault.startswith('init_') else 'playgama')
            if fault.startswith('init_'):
                marker = 'initialize timeout' if fault=='init_unresolved' else 'INJECTED init rejection'
                checks['fallback_warning'] = any(marker in e['message'] for e in errors)
            if fault == 'readiness_rejected':
                checks['send_warning'] = any('Playgama sendMessage failed game_ready' in e['message'] for e in errors)
            result = {'case':fault,'observation_ms':round((time.monotonic()-began)*1000),
                      'before_input':before,'after_input':after,'output':list(errors),'screenshot':screenshot,
                      'checks':checks,'verdict':'PASS reproduced expected legacy behavior' if all(checks.values()) else 'FAIL unexpected behavior'}
            results.append(result)
            log.write(json.dumps(result) + '\n')
            print(f"{fault}: {result['verdict']}", flush=True)
            observing = False  # cleanup abort is outside the observed fault interval
            for route in pending:
                route.abort()
            context.close()
        write('cases.json', results)
        assert all(all(r['checks'].values()) for r in results), 'See cases.json: unexpected behavior'
        log.write('PASS all 6 deterministic legacy cases; reproduced failures are findings, not healthy startup\n')


if __name__ == '__main__':
    main()
