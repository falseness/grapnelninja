"""Real Bridge 2.3.1 + real QA adapter with an unresponsive host, no SDK mocks.

REAL_BRIDGE_DIR points to downloaded official SDK files. External requests are
blocked; only the vendor scripts are served from their original CDN URLs.
Without REAL_BRIDGE_DIR the test is skipped. Run it from the repo root with:
  REAL_BRIDGE_DIR=/path/to/bridge-sdk python3 -m unittest discover -s tools -p test_loading_real_sdk.py -v
"""
import json,os,tempfile,unittest
from pathlib import Path
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from playwright.sync_api import sync_playwright
from browser_test_support import QuietHandler,OfflineBrowser,wait_for_boot
import test_playgama2_bridge as support
SDK=support.SDK

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.environ.get('REAL_BRIDGE_DIR'), 'requires REAL_BRIDGE_DIR (official Bridge SDK files); run: REAL_BRIDGE_DIR=/path/to/bridge-sdk python3 -m unittest discover -s tools -p test_loading_real_sdk.py -v')
class RealSDKTests(unittest.TestCase):
    def test_real_sdk_normal_and_unresponsive_host(self):
        vendor=Path(os.environ['REAL_BRIDGE_DIR'])
        out=Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR','artifacts/loading2/real-sdk'));out.mkdir(parents=True,exist_ok=True)
        game_root=Path(os.environ.get('GAME_ROOT',str(ROOT)))
        rows=[]
        with ExitStack() as stack:
            server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(game_root)))
            stack.callback(server.server_close);Thread(target=server.serve_forever,daemon=True).start();stack.callback(server.shutdown)
            pw=stack.enter_context(sync_playwright())
            for engine in ['chromium','firefox','webkit']:
                browser=getattr(pw,engine).launch();stack.callback(browser.close)
                for fault in ['normal','host-unresponsive','config-failed-host-unresponsive']:
                    with self.subTest(engine=engine,fault=fault):
                        ctx=OfflineBrowser(browser).new_context(viewport={'width':1280,'height':720})
                        ctx.route(SDK,lambda r:r.fulfill(content_type='application/javascript',body=(vendor/'live-bridge.js').read_text()))
                        ctx.route('**/platform-bridges/qatool.js',lambda r:r.fulfill(content_type='application/javascript',body=(vendor/'qatool.js').read_text()))
                        if fault.startswith('config-failed'):
                            ctx.route('**/playgama-bridge-config.json',lambda r:r.fulfill(status=503,body='unavailable'))
                        page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{server.server_port}/'+('' if fault=='normal' else '?platform_id=qa_tool'),wait_until='domcontentloaded')
                        wait_for_boot(page);page.wait_for_function('bootComplete && !unTouch')
                        self.assertEqual(page.locator('#loading-overlay').count(),0)
                        self.assertEqual(page.evaluate('document.elementFromPoint(innerWidth/2,innerHeight/2).id'),'canvas')
                        expected='playgama' if fault=='normal' else 'disabled'
                        self.assertEqual(page.evaluate('PLATFORM.environment'),expected)
                        support.Playgama2BridgeTests.click_mode(self,page,'bad')
                        self.assertTrue(page.evaluate('bootComplete && runInProgress && !menu.gamePaused && !continueOffer.visible && version==="bad"'))
                        self.assertEqual(errors,[])
                        row=page.evaluate('({ready:PLATFORM.readiness,downloadAttempts:bridgeDownloadAttempts,mode:version,environment:PLATFORM.environment})')
                        row.update(engine=engine,fault=fault,verdict='PASS');rows.append(row)
                        page.screenshot(path=str(out/(engine+'-'+fault+'.png')))
                        (out/'real-sdk.json').write_text(json.dumps(rows,indent=2))
                        print('PASS',engine,fault,'real SDK; no blocking overlay; real menu click starts Main',flush=True)
                        ctx.close()
                browser.close()
