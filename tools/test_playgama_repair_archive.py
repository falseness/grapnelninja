"""Run repair regressions against extracted ZIP bytes, never checkout runtime.

The isolated lifecycle probe receives the adapter extracted from the ZIP's
inline script. Full-page tests serve index.html byte-for-byte. All SDK requests
are fulfilled locally and other external requests are blocked.

This is a CLI, not a discoverable module: unittest discovery only reports a
skip. Run it from the repo root with:
  python3 tools/test_playgama_repair_archive.py --zip <build.zip> --out <evidence dir>
"""
import argparse
import contextlib
from functools import partial
import hashlib
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
from threading import Thread
import time
import unittest
import zipfile

from playwright.sync_api import sync_playwright
from browser_test_support import OfflineBrowser, QuietHandler
import test_playgama2_bridge as support
from test_playgama2_ready import Playgama2ReadyTests
from test_playgama_start_flow import StartFlowTests
from test_playgama_start_input import StartInputTests
from test_playgama_startup_telemetry import STAGES, TRANSPORT


class Scripts(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.active = False; self.scripts = []; self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.active = tag == 'script' and not dict(attrs).get('src')
    def handle_endtag(self, tag):
        if tag == 'script': self.active = False
    def handle_data(self, data):
        if self.active: self.scripts.append(data)


def descendants():
    """PIDs of every descendant process (Playwright driver, browsers, Xvfb) via /proc."""
    children = {}
    for entry in Path('/proc').iterdir():
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            children.setdefault(int(fields[1]), []).append(int(entry.name))
        except (ValueError, OSError, IndexError):
            continue
    pending, found = [os.getpid()], []
    while pending:
        for pid in children.get(pending.pop(), []):
            found.append(pid); pending.append(pid)
    return found


def kill_descendants():
    found = descendants()
    for pid in found:
        try: os.kill(pid, signal.SIGKILL)
        except OSError: pass
    return found


class BoundedResult(unittest.TextTestResult):
    """Bound each browser arm (a subTest, or a test without subTests) to `timeout` seconds.

    The deadline runs on a watchdog thread. Raising from a SIGALRM handler inside
    Playwright's sync dispatcher killed its event loop and left cleanup spinning
    forever, so expiry prints a named FAIL, writes watchdog.json, kills the
    browser processes and hard-exits with status 3.
    """
    timeout = 120
    evidence = None

    def arm(self, name):
        self.disarm()
        started = time.monotonic()
        def expired():
            elapsed = time.monotonic() - started
            line = f'FAIL: {name} exceeded {self.timeout} seconds watchdog (elapsed {elapsed:.1f} s); killing browser processes, exit 3'
            print('\n' + line, flush=True)
            if self.evidence:
                (self.evidence / 'watchdog.json').write_text(json.dumps(dict(
                    test=name, timeout_s=self.timeout, elapsed_s=round(elapsed, 1),
                    tests_run=self.testsRun, failures=[t.id() for t, _ in self.failures],
                    errors=[t.id() for t, _ in self.errors]), indent=2) + '\n')
            kill_descendants()
            sys.stdout.flush(); sys.stderr.flush()
            os._exit(3)
        self.watchdog = threading.Timer(self.timeout, expired)
        self.watchdog.daemon = True
        self.watchdog.start()

    def disarm(self):
        if getattr(self, 'watchdog', None): self.watchdog.cancel()

    def startTest(self, test):
        super().startTest(test)
        self.arm(test.id())
        # unittest only reports subTests once the whole test ends, so re-arm on entry.
        enter = test.subTest
        @contextlib.contextmanager
        def subTest(msg=None, **params):
            self.arm(test.id() + ' ' + ' '.join(f'{k}={v}' for k, v in params.items()))
            with (enter(msg, **params) if msg else enter(**params)):
                yield
        test.subTest = subTest

    def stopTest(self, test):
        self.disarm()
        super().stopTest(test)


class TelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)

    def test_packaged_funnel(self):
        # Boot starts a 'bad' run with no title menu (TASK-360/364): the first
        # three stages come from the boot run, classic is reached through the
        # pause switch, and the first trusted press sends first_grapple and
        # tutorial_dismissed (canvas hint, TASK-366/367).
        results = {}
        for mode in ('classic', 'bad'):
            for case in ('immediate', 'delayed', 'late-init', 'boot-only', 'exhausted', 'throws', 'rejects'):
                # A page without input stays in the boot run's mode
                if (mode, case) == ('classic', 'boot-only'):
                    continue
                with self.subTest(mode=mode, case=case):
                    context = self.browser.new_context(viewport={'width':1280,'height':720})
                    self.addCleanup(context.close)
                    body = 'const FAULT="normal", SAVED_LANGUAGE="en", CASE='+json.dumps(case)+';'+support.FAKE+TRANSPORT
                    context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body=body))
                    page = context.new_page(); page.set_default_timeout(12000); errors=[]
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(self.url+'current/index.html'); support.wait_for_boot(page)
                    page.wait_for_function('PLATFORM.readiness.applicationReady && !unTouch')
                    stages=STAGES[:3] if case=='boot-only' else STAGES
                    if case != 'boot-only':
                        support.Playgama2BridgeTests.click_mode(self, page, mode)
                        page.wait_for_function('PLATFORM.readiness.startup.seen >= 3 && !menu.gamePaused && !unTouch')
                        page.mouse.click(800,250)
                        page.wait_for_function('PLATFORM.readiness.startup.seen === 5')
                    if case in ('delayed','late-init'):
                        self.assertEqual(page.evaluate('PLATFORM.readiness.startup.queued'),len(stages))
                        page.evaluate('releaseReady()' if case=='delayed' else 'releaseInit()')
                    page.wait_for_function('s => PLATFORM.readiness.state === s', arg='exhausted' if case=='exhausted' else 'success')
                    if case != 'boot-only':
                        page.evaluate("startGame('bad');startGame('classic');for(let i=0;i<20;i++)PLATFORM.gameReady()")
                    page.wait_for_timeout(150)
                    result = page.evaluate('({calls:probe.calls,readiness:PLATFORM.readiness,build:PLATFORM.buildVersion,now:performance.now()})')
                    events=[c for c in result['calls'] if c['name']=='startup_funnel']
                    self.assertEqual([e['data']['stage'] for e in events], [] if case=='exhausted' else stages)
                    self.assertEqual(result['build'],self.expected_build_version)
                    # The boot run is 'bad'; the press happens in the mode under test
                    modes=['bad','bad','bad',mode,mode]
                    times=[]
                    for e, expected_mode in zip(events, modes):
                        d=e['data']; self.assertEqual(set(d), {'stage','elapsed_ms','game_version','mode'})
                        self.assertEqual(d['game_version'],result['build'])
                        self.assertEqual(d['mode'],expected_mode)
                        self.assertTrue(0<=d['elapsed_ms']<=result['now']);times.append(d['elapsed_ms'])
                    self.assertEqual(times,sorted(times))
                    self.assertEqual(result['readiness']['startup'],dict(queued=0,capacity=5,seen=len(stages)))
                    lifecycle=[c['name'] for c in result['calls'] if c['name'].startswith('level_')]
                    # Boot run; classic leaves it through the pause switch; then
                    # the two direct startGame calls
                    after_boot=['level_paused','level_failed','level_started'] if mode=='classic' else []
                    expected_lifecycle=([] if case=='exhausted' else ['level_started'] if case=='boot-only'
                                        else ['level_started']+after_boot+['level_started']*2)
                    self.assertEqual(lifecycle, expected_lifecycle)
                    names=[c['name'] for c in result['calls']]
                    if case in ('delayed','late-init'): self.assertLess(names.index('level_started'),names.index('startup_funnel'))
                    self.assertEqual(errors,[])
                    result['verdict']='PASS bounded packaged telemetry payload/order/privacy; capacity=5; no page errors'
                    results[mode+'-'+case]=result
                    (self.out/'packaged-telemetry.json').write_text(json.dumps(results,indent=2)+'\n')
                    print('PASS packaged telemetry '+mode+'-'+case,flush=True)
                    context.close()


class ArchiveCLI(unittest.TestCase):
    @unittest.skip('requires --zip; run: python3 tools/test_playgama_repair_archive.py --zip <build.zip> --out <evidence dir>')
    def test_requires_zip_cli(self):
        pass


def load_tests(loader, tests, pattern):
    # Discovery would otherwise collect the imported suites against the checkout
    # and TelemetryTests without expected_build_version; main() builds its own.
    return loader.loadTestsFromTestCase(ArchiveCLI)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--test-timeout',type=float,default=BoundedResult.timeout,help='per browser arm watchdog seconds')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    BoundedResult.timeout=args.test_timeout;BoundedResult.evidence=args.out
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
        versions = re.findall(r"buildVersion:\s*'([^']+)'", adapter)
        assert len(versions) == 1, 'Expected one buildVersion in packaged adapter'
        TelemetryTests.expected_build_version = versions[0]
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
                    expected_build_version=TelemetryTests.expected_build_version,
                    adapter_sha256=hashlib.sha256(adapter.encode()).hexdigest(),runtime_source='extracted ZIP only',external_network='blocked; SDK fulfilled locally')
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Playgama2ReadyTests,StartFlowTests,StartInputTests,TelemetryTests))
        result=unittest.TextTestRunner(verbosity=2, resultclass=BoundedResult).run(suite)
        report.update(tests_run=result.testsRun,successful=result.wasSuccessful())
        assert members=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in extracted.iterdir()}
        report['unchanged_extracted_members'] = True
        (args.out/'suite.json').write_text(json.dumps(report,indent=2)+'\n')
        if not result.wasSuccessful(): raise SystemExit(1)
        print('PASS exact ZIP readiness/recovery/ordered lifecycle/input/orientation/tutorial/telemetry; Chromium and Firefox; unchanged member hashes')


if __name__=='__main__': main()
