"""Focused cross-engine production boot/gameplay probes; faults at host boundaries.

Fresh contexts disable caches through routing. Timings are local controlled
measurements, not a production-network SLA or legacy-device certification.

The title menu is gone (TASK-360/364): the page boots straight into a 'bad'
run and 'classic' is reached through the pause screen's mode switch; the
language button sits on the pause screen. Runnable from the repo root or
tools/: git and source hashes resolve against ROOT. Engines without an
installed executable are reported as unittest skips.

PLAYGAMA2_EVIDENCE_DIR selects the output directory (default artifacts/TASK-396/browsers).
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright
from browser_test_support import OfflineBrowser, QuietHandler, wait_for_boot
import test_playgama2_bridge as support
from test_playgama2_ads import AD_FAKE

ROOT = support.ROOT
COMMAND = "cd tools && python3 -m unittest test_playgama2_browsers -v"


def hashes():
    paths = subprocess.check_output(['git', 'ls-files'], text=True, cwd=ROOT).splitlines()
    paths.append('tools/test_playgama2_browsers.py')
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(set(paths))
            if not p.startswith(('artifacts/', 'screenshots/'))}


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', ROOT/'artifacts/TASK-396/browsers'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.initial_hashes = hashes()
        cls.baseline = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, cwd=ROOT).strip()
        cls.matrix, cls.runs, cls.logs = {}, [], []
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
        cls.addClassCleanup(cls.server.server_close)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)

    @classmethod
    def tearDownClass(cls):
        for name in ['edge', 'opera']:
            cls.matrix.setdefault(name, {'available': False, 'version': None, 'reason': 'No installed executable found'})
        stages = ['app_script', 'sdk', 'storage', 'first_render', 'input_ready', 'readiness_delivery']
        summary = {}
        for engine in cls.matrix:
            rows = [r for r in cls.runs if r['engine'] == engine and r['case'].startswith('cold-')]
            if rows:
                summary[engine] = {s: dict(zip(['min', 'median', 'max'], [min(v), statistics.median(v), max(v)]))
                                   for s in stages if (v := [r['stages_ms'][s] for r in rows if r['stages_ms'][s] is not None])}
        limitations = ['Linux browser engines only; Windows/macOS/Android/iOS and their legacy versions unavailable; no physical devices tested.',
                      'SDK is a deterministic network-boundary fixture. No production traffic or universal 5s guarantee.',
                      'Background visibility is a browser-boundary event injection, not an OS background transition.',
                      'CPU/network throttle uses Chromium CDP (4x CPU, 150ms latency, 200KB/s); delayed resource cases cover every engine.',
                      'PNG captures are native viewport pixels, without resizing.']
        cls.write('browser-matrix.json', {'engines': cls.matrix, 'limitations': limitations})
        cls.write('cold-starts.json', {'definitions': {
            'origin': 'performance.now at inline application entry after all local application scripts execute',
            'app_script': '0; local application code available', 'sdk': 'PLATFORM.init settled (including bounded fallback)',
            'storage': 'PROGRESS.load after bounded platform storage read', 'first_render': 'start() returned after first menu draw',
            'input_ready': 'bootComplete set after createEvents', 'readiness_delivery': 'SDK game_ready boundary receipt; null if unavailable',
            'navigation_ms': 'navigation origin to interactive menu; includes resource delays',
            'summary': 'min/median/max across three fresh-context baseline runs per engine; all stages milliseconds'},
            'runs': cls.runs, 'summary': summary})
        (cls.out/'browser.log').write_text('\n'.join(cls.logs)+'\n')
        cls.write('manifest.json', {'task': 'TASK-396', 'baseline_revision': cls.baseline,
            'baseline_source_hashes': cls.initial_hashes, 'final_source_hashes': hashes(), 'commands': [COMMAND],
            'environment': {'os': platform.platform(), 'python': platform.python_version(), 'playwright': subprocess.check_output(['python3', '-m', 'pip', 'show', 'playwright'], text=True).split('Version: ')[1].splitlines()[0]},
            'limitations': limitations, 'evidence_paths': sorted(str(p) for p in cls.out.iterdir() if p.is_file())})

    @classmethod
    def write(cls, name, data):
        (cls.out/name).write_text(json.dumps(data, indent=2)+'\n')

    def click(self, p, expression):
        p.wait_for_function('!unTouch')
        point = p.evaluate('''() => {const b='''+expression+'''.background,r=canvas.getBoundingClientRect();return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}}''')
        p.mouse.click(**point)

    def capture(self, p, name):
        p.screenshot(path=str(self.out/(name+'.png')))
        return {'path': name+'.png', 'sha256': hashlib.sha256((self.out/(name+'.png')).read_bytes()).hexdigest(), 'viewport': p.viewport_size}

    def run_engine(self, engine, executable=None):
        browser_type = getattr(self.pw, engine if engine in ('chromium', 'firefox', 'webkit') else 'chromium')
        if not executable and not os.path.exists(browser_type.executable_path):
            self.matrix[engine] = {'available': False, 'version': None, 'reason': 'Not installed: '+browser_type.executable_path}
            self.skipTest(engine+' not installed: '+browser_type.executable_path)
        browser = browser_type.launch(headless=True, **({'executable_path': executable} if executable else {}))
        self.addCleanup(browser.close)
        self.matrix[engine] = {'available': True, 'version': browser.version, 'executable': executable or browser_type.executable_path, 'checks': []}
        for case in ['cold-1', 'cold-2', 'cold-3', 'delayed-sdk', 'offline-sdk', 'init-hung', 'storage-hung', 'storage-rejected'] + (['throttled'] if engine == 'chromium' else []):
            with self.subTest(engine=engine, case=case):
                try:
                    self.cold(browser, engine, case)
                except Exception as error:
                    self.logs.append(f'{engine}-{case} FAIL {type(error).__name__}: {error}; reproduce: {COMMAND}; fresh 1280x720 context')
                    raise
        self.matrix[engine]['verdict'] = 'PASS' if all(r.get('verdict') == 'PASS' for r in self.runs if r['engine'] == engine) else 'FAIL'

    def cold(self, browser, engine, case):
        label = engine+'-'+case
        with OfflineBrowser(browser).new_context(viewport={'width': 1280, 'height': 720}) as ctx:
            ctx.add_init_script("window.stages={};window.inputs=[];addEventListener('mousedown',e=>inputs.push({trusted:e.isTrusted,ms:performance.now()}),true)")
            html = (ROOT/'index.html').read_text()
            for old, new in [
                ("            'use strict'", "            'use strict'; stages.app_script=performance.now();"),
                ('await PLATFORM.init()', 'await PLATFORM.init(); stages.sdk=performance.now()'),
                ('PROGRESS.load(await PLATFORM.storage.getMany(PROGRESS.keys))', 'PROGRESS.load(await PLATFORM.storage.getMany(PROGRESS.keys)); stages.storage=performance.now()'),
                ('                start()\n', '                start(); stages.first_render=performance.now()\n'),
                ('bootComplete = true', 'bootComplete = true; stages.input_ready=performance.now()')]:
                self.assertIn(old, html)
                html = html.replace(old, new)
            ctx.route('**/index.html', lambda r: r.fulfill(content_type='text/html', body=html))
            body = 'const FAULT='+json.dumps('storage_rejected' if case == 'storage-rejected' else 'normal')+',SAVED_LANGUAGE="en";'+support.FAKE+AD_FAKE
            body += "\nconst send=bridge.platform.sendMessage;bridge.platform.sendMessage=(n,d)=>{if(n==='game_ready')stages.readiness_delivery=performance.now();return send(n,d)};"
            # Host persistence across reloads; no application storage implementation replaced.
            body += "\nconst saved=localStorage.getItem('fixture.remote');if(saved)Object.assign(values,JSON.parse(saved));const save=bridge.storage.set;bridge.storage.set=async(k,v)=>{await save(k,v);localStorage.setItem('fixture.remote',JSON.stringify(values))};"
            if case == 'init-hung':
                body += '\nbridge.initialize=()=>new Promise(()=>{});'
            if case == 'storage-hung':
                body += '\nbridge.storage.get=()=>new Promise(()=>{});'
            def sdk(route):
                if case == 'offline-sdk':
                    route.abort('internetdisconnected')
                else:
                    if case == 'delayed-sdk':
                        time.sleep(.8)
                    route.fulfill(content_type='application/javascript', body=body)
            ctx.route(support.SDK, sdk)
            if case == 'delayed-sdk':
                def delayed_script(route):
                    time.sleep(.4)
                    route.continue_()
                ctx.route('**/events.js', delayed_script)
            p = ctx.new_page()
            p.set_default_timeout(15000)
            errors = []
            p.on('pageerror', lambda e: errors.append(str(e)))
            p.on('console', lambda m: self.logs.append(label+' console '+m.type+': '+m.text))
            p.on('requestfailed', lambda r: self.logs.append(label+' network-failure '+r.url+' '+str(r.failure)))
            if case == 'throttled':
                cd = ctx.new_cdp_session(p)
                cd.send('Emulation.setCPUThrottlingRate', {'rate': 4})
                cd.send('Network.enable')
                cd.send('Network.emulateNetworkConditions', {'offline': False, 'latency': 150, 'downloadThroughput': 200000, 'uploadThroughput': 100000})
            p.goto(self.url+'index.html', wait_until='domcontentloaded')
            wait_for_boot(p)
            p.wait_for_function('bootComplete')
            if case not in ('offline-sdk', 'init-hung'):
                p.wait_for_function('stages.readiness_delivery !== undefined')
            raw = p.evaluate('stages')
            stages = {k: raw.get(k)-raw['app_script'] if k in raw else None for k in ['app_script', 'sdk', 'storage', 'first_render', 'input_ready', 'readiness_delivery']}
            self.assertLessEqual(stages['input_ready'], 5000, label)
            self.assertTrue(0 <= stages['sdk'] <= stages['storage'] <= stages['first_render'] <= stages['input_ready'])
            if stages['readiness_delivery'] is not None:
                self.assertGreaterEqual(stages['readiness_delivery'], stages['input_ready'])
            row = {'engine': engine, 'case': case, 'utc_epoch': time.time(), 'stages_ms': stages, 'navigation_ms': raw['input_ready'], 'profile': 'fresh context; cache disabled by routing', 'checks': []}
            row['fault_config'] = {'sdk_delay_ms': 800 if case == 'delayed-sdk' else 0, 'events_script_delay_ms': 400 if case == 'delayed-sdk' else 0, 'cpu_rate': 4 if case == 'throttled' else 1, 'network': '150ms latency; 200KB/s down; 100KB/s up' if case == 'throttled' else 'local unthrottled', 'sdk': case}
            self.runs.append(row)
            if case == 'cold-1':
                row['menu_capture'] = self.capture(p, engine+'-menu')
            # Boot run (TASK-360): a 'bad' run with the tutorial hint, no title
            # menu; real clicks on the HUD menu button and the pause switch
            # start the classic run
            p.wait_for_function('bootComplete && runInProgress && !!ninja')
            self.assertEqual(p.evaluate('[version, TUTORIAL_HINT.visible, menu.gamePaused]'), ['bad', True, False])
            support.Playgama2BridgeTests.click_mode(self, p, 'classic')
            p.wait_for_function("version === 'classic' && runInProgress && !menu.gamePaused && !unTouch")
            p.mouse.move(900, 200); p.mouse.down()
            p.wait_for_function('grapnel.throwed')
            p.mouse.up()
            self.assertFalse(p.evaluate('grapnel.throwed'))
            row['checks'].append('PASS trusted gameplay hold/release')
            row['inputs'] = p.evaluate('inputs')
            self.assertTrue(row['inputs'] and all(e['trusted'] for e in row['inputs']))
            if case == 'cold-1':
                self.full_flow(p, row, engine)
            self.assertEqual(errors, [])
            row['verdict'] = 'PASS'
            self.logs.append(label+' PASS no page errors; input-ready <=5000ms; '+json.dumps(stages))
            print(label+' PASS input-ready=%.1fms'%stages['input_ready'], flush=True)

    def full_flow(self, p, row, engine):
        row['gameplay_capture'] = self.capture(p, engine+'-gameplay')
        p.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        self.assertTrue(p.evaluate('menu.gamePaused'))
        before = p.evaluate('[ninja.x,ninja.y,scoreText.count[version]]')
        p.wait_for_timeout(150)
        self.assertEqual(before, p.evaluate('[ninja.x,ninja.y,scoreText.count[version]]'))
        p.evaluate("delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'))")
        self.click(p, 'menu.resume')
        row['checks'].append('PASS background pause freezes position/score; resume')
        for outcome in ['hold', 'reject']:
            # Advance only the monotonic clock boundary for second ad cooldown;
            # before the death, as a death with no ad due restarts at once
            if outcome == 'reject':
                p.evaluate('const now=performance.now.bind(performance);performance.now=()=>now()+120001')
            p.wait_for_function('continueOffer.visible && !continueOffer.adPending', timeout=60000)
            p.evaluate('(v)=>outcome=v', outcome)
            self.click(p, 'continueOffer.restartButton')
            if outcome == 'hold':
                self.assertTrue(p.evaluate('interstitialPending && adOpen'))
                p.evaluate("emitHost('interstitial','closed')")
            p.wait_for_function('!interstitialPending && !continueOffer.visible')
            self.assertFalse(p.evaluate('adOpen || AUDIO.isMuted()'))
            row['checks'].append('PASS ad '+outcome+' real death/restart reconciles audio and pause')
        self.assertEqual(p.evaluate("probe.calls.filter(x=>x.name==='ad-request').length"), 2)
        # The pause screen's mode switch replaces back-to-menu: a real click
        # leaves a live 'bad' run; the language button is on the pause screen
        p.keyboard.press('Escape')
        p.wait_for_function('menu.gamePaused && !unTouch')
        self.click(p, 'menu.backToMenu')
        p.wait_for_function("bootComplete && runInProgress && version === 'bad' && !menu.gamePaused")
        p.keyboard.press('Escape')
        p.wait_for_function('menu.gamePaused && !unTouch')
        point = p.evaluate('''() => {const b=LANGUAGE_BUTTON.rect(),r=canvas.getBoundingClientRect();return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}}''')
        p.mouse.click(**point)
        self.assertEqual(p.evaluate('I18N.language'), 'ru')
        p.wait_for_function("JSON.parse(localStorage.getItem('fixture.remote'))['grapnelninja.lang']==='ru'")
        p.reload(); wait_for_boot(p)
        p.wait_for_function('bootComplete && runInProgress')
        self.assertEqual(p.evaluate('I18N.language'), 'ru')
        row['checks'].append('PASS host storage language survives reload')
        self.matrix[engine]['checks'] = row['checks']

    def test_chromium(self): self.run_engine('chromium')
    def test_firefox(self): self.run_engine('firefox')
    def test_webkit(self): self.run_engine('webkit')
    def test_installed_vendor_browsers(self):
        for name, candidates in [('edge', ['microsoft-edge', 'microsoft-edge-stable']), ('opera', ['opera', 'opera-stable'])]:
            executable = next((shutil.which(p) for p in candidates if shutil.which(p)), None)
            if executable:
                self.run_engine(name, executable)
            else:
                self.matrix[name] = {'available': False, 'version': None, 'reason': 'No installed executable found: '+', '.join(candidates)}
        missing = [n for n in ['edge', 'opera'] if not self.matrix[n]['available']]
        if missing:
            self.skipTest('not installed: '+'; '.join(self.matrix[n]['reason'] for n in missing))


if __name__ == '__main__':
    unittest.main()
