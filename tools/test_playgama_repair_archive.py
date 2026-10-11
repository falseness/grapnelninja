"""Run repair regressions against extracted ZIP bytes, never checkout runtime.

The isolated lifecycle probe receives the adapter extracted from the ZIP's
inline script. Full-page tests serve index.html byte-for-byte. All SDK requests
are fulfilled locally and other external requests are blocked.
"""
import argparse
from functools import partial
import hashlib
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
import json
import os
import subprocess
from pathlib import Path
import tempfile
from threading import Thread
import unittest
import zipfile

from playwright.sync_api import sync_playwright
from browser_test_support import OfflineBrowser, QuietHandler
import test_playgama2_bridge as support
from test_playgama2_ready import Playgama2ReadyTests
from test_playgama_start_flow import StartFlowTests
from test_playgama_start_input import StartInputTests
from test_playgama_startup_telemetry import TRANSPORT


class Scripts(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.active = False; self.scripts = []; self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.active = tag == 'script' and not dict(attrs).get('src')
    def handle_endtag(self, tag):
        if tag == 'script': self.active = False
    def handle_data(self, data):
        if self.active: self.scripts.append(data)


class TelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)

    def test_packaged_funnel(self):
        results = {}
        for mode in ('classic', 'bad'):
            for case in ('immediate', 'delayed', 'late-init', 'menu-only', 'exhausted', 'throws', 'rejects'):
                with self.subTest(mode=mode, case=case):
                    context = self.browser.new_context(viewport={'width':1280,'height':720})
                    self.addCleanup(context.close)
                    body = 'const FAULT="normal", SAVED_LANGUAGE="en", CASE='+json.dumps(case)+';'+support.FAKE+TRANSPORT
                    context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body=body))
                    page = context.new_page(); page.set_default_timeout(12000); errors=[]
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(self.url+'current/index.html'); support.wait_for_boot(page)
                    page.wait_for_function('PLATFORM.readiness.applicationReady && !unTouch')
                    if case != 'menu-only':
                        support.Playgama2BridgeTests.click_mode(self, page, mode)
                        page.wait_for_function('PLATFORM.readiness.startup.seen >= 4 && !unTouch')
                        page.mouse.click(800,250)
                        page.locator('#tutorial button').click()
                        page.wait_for_function('PLATFORM.readiness.startup.seen === 6')
                    if case in ('delayed','late-init'):
                        self.assertEqual(page.evaluate('PLATFORM.readiness.startup.queued'),6)
                        page.evaluate('releaseReady()' if case=='delayed' else 'releaseInit()')
                    page.wait_for_function('s => PLATFORM.readiness.state === s', arg='exhausted' if case=='exhausted' else 'success')
                    if case != 'menu-only':
                        page.evaluate("startGame('bad');startGame('classic');for(let i=0;i<20;i++)PLATFORM.gameReady()")
                    page.wait_for_timeout(150)
                    result = page.evaluate('({calls:probe.calls,readiness:PLATFORM.readiness,build:PLATFORM.buildVersion,now:performance.now()})')
                    events=[c for c in result['calls'] if c['name']=='startup_funnel']
                    stages=['menu_interactive'] if case=='menu-only' else ['menu_interactive','mode_selected','run_initialized','first_gameplay_frame','first_grapple','tutorial_dismissed']
                    self.assertEqual([e['data']['stage'] for e in events], [] if case=='exhausted' else stages)
                    self.assertEqual(result['build'],'2026-10-11-start-firefox')
                    times=[]
                    for e in events:
                        d=e['data']; self.assertEqual(set(d), {'stage','elapsed_ms','game_version'} | (set() if d['stage']=='menu_interactive' else {'mode'}))
                        self.assertEqual(d['game_version'],result['build'])
                        if 'mode' in d: self.assertEqual(d['mode'],mode)
                        self.assertTrue(0<=d['elapsed_ms']<=result['now']);times.append(d['elapsed_ms'])
                    self.assertEqual(times,sorted(times))
                    self.assertEqual(result['readiness']['startup'],dict(queued=0,capacity=6,seen=len(stages)))
                    names=[c['name'] for c in result['calls']]
                    self.assertEqual([n for n in names if n.startswith('level_')], [] if case in ('menu-only','exhausted') else ['level_started']*3)
                    if case in ('delayed','late-init'): self.assertLess(names.index('level_started'),names.index('startup_funnel'))
                    self.assertEqual(errors,[])
                    result['verdict']='PASS bounded packaged telemetry payload/order/privacy; capacity=6; no page errors'
                    results[mode+'-'+case]=result
                    (self.out/'packaged-telemetry.json').write_text(json.dumps(results,indent=2)+'\n')
                    print('PASS packaged telemetry '+mode+'-'+case,flush=True)
                    context.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory); extracted=root/'current';extracted.mkdir()
        with zipfile.ZipFile(args.zip) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist())=={'index.html','playgama-bridge-config.json'}
            archive.extractall(extracted)
        members={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in extracted.iterdir()}
        scripts=Scripts((extracted/'index.html').read_text()).scripts
        adapters=[s for s in scripts if 'const PLATFORM = (function()' in s]
        assert len(adapters)==1
        adapter=adapters[0]
        # Compatibility URL for the isolated lifecycle unit probe; its bytes
        # come exclusively from the archive, not platform.js in the checkout.
        class Handler(QuietHandler):
            def do_GET(self):
                if self.path=='/current/platform.js':
                    data=adapter.encode();self.send_response(200);self.send_header('Content-Type','application/javascript');self.end_headers();self.wfile.write(data)
                else: super().do_GET()
        def setup(cls):
            cls.out=args.out/cls.__name__;cls.out.mkdir(parents=True,exist_ok=True)
            server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root)))
            cls.addClassCleanup(server.server_close)
            Thread(target=server.serve_forever,daemon=True).start();cls.addClassCleanup(server.shutdown)
            cls.url=f'http://127.0.0.1:{server.server_port}/'
            pw=sync_playwright().start();cls.addClassCleanup(pw.stop)
            read_fd, write_fd = os.pipe()
            xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x900x24'], pass_fds=(write_fd,))
            os.close(write_fd);cls.addClassCleanup(xvfb.wait);cls.addClassCleanup(xvfb.terminate)
            with os.fdopen(read_fd) as pipe:
                cls.env = {**os.environ, 'DISPLAY': ':' + pipe.readline().strip()}
            browser=pw.chromium.launch(headless=False,env=cls.env,args=['--no-sandbox']);cls.addClassCleanup(browser.close)
            cls.browser=OfflineBrowser(browser)
        support.Playgama2BridgeTests.setUpClass=classmethod(setup)
        support.ROOT=extracted
        os.environ['PLAYGAMA2_EVIDENCE_DIR']=str(args.out/'input')
        report=dict(zip_sha256=hashlib.sha256(args.zip.read_bytes()).hexdigest(),extracted_members=members,
                    adapter_sha256=hashlib.sha256(adapter.encode()).hexdigest(),runtime_source='extracted ZIP only',external_network='blocked; SDK fulfilled locally')
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Playgama2ReadyTests,StartFlowTests,StartInputTests,TelemetryTests))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        report.update(tests_run=result.testsRun,successful=result.wasSuccessful())
        assert members=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in extracted.iterdir()}
        (args.out/'suite.json').write_text(json.dumps(report,indent=2)+'\n')
        if not result.wasSuccessful(): raise SystemExit(1)
        print('PASS exact ZIP readiness/recovery/ordered lifecycle/input/orientation/tutorial/telemetry; Chromium and Firefox; unchanged member hashes')


if __name__=='__main__': main()
