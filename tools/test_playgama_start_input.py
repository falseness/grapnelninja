"""Bounded offline input matrix using production handlers and trusted browser input.

Chromium touch is emulation, not native Android evidence. Firefox covers desktop
mouse/layout only. No game state, rendering quality or scheduler is replaced.

Boot starts a 'bad' run with no title menu (TASK-360/364): classic is reached
by real clicks on the HUD menu button and the pause-screen switch (TASK-362),
and the first press on the canvas dismisses the tutorial hint (TASK-366/367).
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

from playwright.sync_api import sync_playwright
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from browser_test_support import OfflineBrowser, QuietHandler, wait_for_boot
import test_playgama2_bridge as support

OBSERVE = r"""
window.inputProbe = {inputs: [], frames: []};
const ids = new WeakMap(); let nextId = 0;
const objectId = o => { if (!o) return null; if (!ids.has(o)) ids.set(o, ++nextId); return ids.get(o); };
window.inputSnapshot = () => ({ms:performance.now(), runInProgress,
    paused:menu.gamePaused, hostPaused, rotated:isViewRotated(), unTouch, version,
    ninja:ninja ? {id:objectId(ninja), x:ninja.x, y:ninja.y}:null,
    grapnel:objectId(grapnel), floors:floors ? floors.length:0, runOver,
    hint:TUTORIAL_HINT.visible, hintPressed:TUTORIAL_HINT.pressed,
    overlay:getComputedStyle(document.getElementById('rotate-prompt')).display,
    inert:document.getElementById('stage').inert,
    readiness:PLATFORM.readiness.state});
for (const type of ['mousedown','touchstart']) window.addEventListener(type, e => {
    const p=e.changedTouches ? e.changedTouches[0]:e;
    inputProbe.inputs.push({type, trusted:e.isTrusted, x:p.clientX, y:p.clientY,
        hit:document.elementFromPoint(p.clientX,p.clientY)?.id, state:inputSnapshot()});
}, true);
const raf = requestAnimationFrame.bind(window);
window.requestAnimationFrame = cb => raf(t => {
    cb(t);
    if (typeof bootComplete !== 'undefined' && bootComplete) {
        inputProbe.frames.push(inputSnapshot());
        if (inputProbe.frames.length > 240) inputProbe.frames.shift();
    }
});
"""


class StartInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', tempfile.mkdtemp()))
        cls.out.mkdir(parents=True, exist_ok=True)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(support.ROOT)))
        cls.addClassCleanup(server.server_close)
        Thread(target=server.serve_forever, daemon=True).start()
        cls.addClassCleanup(server.shutdown)
        cls.url = f'http://127.0.0.1:{server.server_port}/'
        pw = sync_playwright().start()
        cls.addClassCleanup(pw.stop)
        chromium = pw.chromium.launch(args=['--no-sandbox'])
        cls.addClassCleanup(chromium.close)
        cls.chromium = OfflineBrowser(chromium)
        browser = pw.firefox.launch()
        cls.addClassCleanup(browser.close)
        cls.firefox = OfflineBrowser(browser)
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        cls.save()

    @classmethod
    def save(cls):
        (cls.out / 'input-traces.json').write_text(json.dumps(cls.results, indent=2)+'\n')
        matrix = [{k:v for k,v in result.items() if k not in ('frames','console','network','inputs')}
                  for result in cls.results.values()]
        (cls.out / 'input-matrix.json').write_text(json.dumps(matrix, indent=2)+'\n')

    def run_case(self, engine, mode):
        touch = engine == 'chromium'
        # The boot-run mode also covers delayed SDK readiness
        delayed = mode == 'bad'
        key = engine + '-' + mode
        browser = getattr(self, engine)
        context = browser.new_context(viewport={'width':1280,'height':900},
                                      has_touch=touch, locale='en')
        self.addCleanup(context.close)
        context.add_init_script(OBSERVE)
        fake = "const FAULT='normal', SAVED_LANGUAGE='en';\n" + support.FAKE
        if delayed:
            fake = fake.replace('record(name, data); return Promise.resolve();',
                "record(name, data); return name === 'game_ready' ? new Promise(r => window.releaseReady=r) : Promise.resolve();")
        context.route(support.SDK, lambda route: route.fulfill(content_type='application/javascript', body=fake))
        page = context.new_page()
        page.set_default_timeout(10000)
        result = dict(case=key, mode=mode, engine=engine, browser_version=browser.version,
                      input_type='trusted touch' if touch else 'desktop mouse',
                      native_android='UNVERIFIED', tutorial='canvas hint dismissed by the first press',
                      sdk='delayed recovery' if delayed else 'immediate',
                      iframe={'offset':[90,70], 'scale':0.8, 'size':[1000,600]},
                      checkpoints=[], targets=[], screenshots=[], console=[], errors=[], network=[], verdict='INCOMPLETE')
        self.results[key] = result
        page.on('console', lambda m: result['console'].append(m.text))
        page.on('pageerror', lambda e: result['errors'].append(str(e)))
        page.on('response', lambda r: result['network'].append({'url':r.url,'status':r.status}))
        # Local embedding fixture only; iframe loads the unmodified production page.
        context.route(self.url+'input-host', lambda r: r.fulfill(content_type='text/html', body=
            '<!DOCTYPE html><iframe id="game" style="position:absolute;left:90px;top:70px;width:1000px;height:600px;border:0;transform:scale(.8);transform-origin:top left" src="/index.html"></iframe>'))
        page.goto(self.url+'input-host')
        game = page.frames[1]

        def snap(label):
            state = game.evaluate('inputSnapshot()')
            result['checkpoints'].append(dict(label=label, **state))
            return state

        def shot(label):
            name = key+'-'+label+'.png'
            page.screenshot(path=str(self.out/name), scale='css')
            result['screenshots'].append(name)

        def click(button, scaled=False):
            # HUD menu button rects are in scale[version] units
            game.wait_for_function('!unTouch')
            local = game.evaluate('''([name, scaled]) => {
                const b=menu[name].background, s=scaled ? scale[version] : 1, r=canvas.getBoundingClientRect();
                const p={x:r.x+(b.x+b.width/2)*s*r.width/width,y:r.y+(b.y+b.height/2)*s*r.height/height};
                return {...p, hit:document.elementFromPoint(p.x,p.y)?.id,
                    logical:viewportCoordsToCanvasCoords(p), button:{...b}};
            }''', [button, scaled])
            box = page.locator('#game').bounding_box()
            point = dict(x=box['x']+local['x']*.8, y=box['y']+local['y']*.8)
            result['targets'].append(dict(button=button, local=local, parent=point))
            self.assertEqual(local['hit'], 'canvas')
            (page.touchscreen.tap if touch else page.mouse.click)(**point)

        def advancing(label):
            before = snap(label+'-before')
            game.wait_for_function('old => ninja && (ninja.x !== old.x || ninja.y !== old.y)', arg=before['ninja'])
            after = snap(label+'-after')
            self.assertFalse(after['paused'] or after['runOver'])
            self.assertTrue(after['runInProgress'])
            self.assertTrue(after['ninja'] and after['grapnel'] and after['floors'])
            self.assertEqual(before['ninja']['id'], after['ninja']['id'])
            return after

        def frozen(label):
            before = snap(label+'-before')
            page.wait_for_timeout(200)
            after = snap(label+'-after')
            self.assertEqual(before['ninja'], after['ninja'])

        try:
            wait_for_boot(game)
            game.wait_for_function('PLATFORM.readiness.applicationReady')
            result['environment'] = game.evaluate('''() => {
                const gl=document.createElement('canvas').getContext('webgl');
                const ext=gl && gl.getExtension('WEBGL_debug_renderer_info');
                return {userAgent:navigator.userAgent, dpr:devicePixelRatio,
                    graphics:ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):'unavailable',
                    viewport:[innerWidth,innerHeight],coarse:matchMedia('(pointer:coarse)').matches};
            }''')
            game.wait_for_function('runInProgress')
            boot = snap('boot'); shot('iframe-targets')
            self.assertEqual((boot['version'], boot['hint'], boot['hintPressed']), ('bad', True, False))
            if mode != 'bad':
                click('button', scaled=True)
                game.wait_for_function('menu.gamePaused')
                click('backToMenu')
                game.wait_for_function('v => version === v && !!ninja && !menu.gamePaused', arg=mode)
            first = advancing('start')
            self.assertEqual(first['version'], mode)
            self.assertTrue(first['hint'] and not first['hintPressed'])
            shot('tutorial')
            # A trusted press on the play field dismisses the hint
            game.wait_for_function('!unTouch')
            box = page.locator('#game').bounding_box()
            (page.touchscreen.tap if touch else page.mouse.click)(box['x']+box['width']*.7, box['y']+box['height']*.3)
            game.wait_for_function('TUTORIAL_HINT.pressed')
            self.assertTrue(snap('tutorial-dismissed')['hintPressed'])
            if delayed:
                self.assertEqual(first['readiness'], 'inflight')
                game.evaluate('releaseReady()')
                game.wait_for_function("PLATFORM.readiness.state === 'success'")
                self.assertEqual(snap('sdk-recovered')['ninja']['id'], first['ninja']['id'])
            # Host changes happen at the SDK boundary, recovery uses real input.
            game.evaluate("emitHost('pause', true)")
            self.assertTrue(snap('host-pause')['paused'])
            frozen('host-pause')
            game.evaluate("emitHost('pause', false)")
            self.assertTrue(snap('host-resume-await-input')['paused'])
            click('resume'); advancing('host-user-recovery')
            if touch:
                page.locator('#game').evaluate("e => {e.style.width='600px'; e.style.height='900px'}")
                game.wait_for_function('isViewRotated() && menu.gamePaused')
                page.wait_for_timeout(150)
                shot('rotation-overlay')
                state = snap('portrait')
                self.assertEqual(state['overlay'], 'flex')
                self.assertTrue(state['inert'])
                page.touchscreen.tap(300,300)
                frozen('portrait-input-blocked')
                page.locator('#game').evaluate("e => {e.style.width='1000px'; e.style.height='600px'}")
                game.wait_for_function('!isViewRotated() && !document.getElementById("stage").inert')
                page.wait_for_timeout(180)
                self.assertTrue(snap('landscape-await-input')['paused'])
                click('resume'); advancing('rotation-user-recovery')
            game.wait_for_function('!unTouch')
            final = snap('final')
            self.assertEqual(final['ninja']['id'], first['ninja']['id'])
            self.assertEqual(final['version'], mode)
            result.update(game.evaluate('({inputs:inputProbe.inputs,frames:inputProbe.frames,calls:probe.calls})'))
            starts = [c['data'] for c in result['calls'] if c['name']=='level_started']
            # One start per run: the boot run, plus the switched classic run
            self.assertEqual(starts, [{'world':'bad'}] + ([{'world':mode}] if mode != 'bad' else []))
            self.assertTrue(result['inputs'])
            self.assertTrue(all(i['trusted'] for i in result['inputs']))
            if touch:
                self.assertTrue(any(i['type']=='touchstart' for i in result['inputs']))
                self.assertFalse(any(i['type']=='mousedown' and i['hit']=='canvas' for i in result['inputs']))
            self.assertEqual(result['errors'], [])
            self.assertTrue(all(r['status']==200 and (r['url'].startswith(self.url) or r['url']==support.SDK) for r in result['network']))
            result['verdict'] = f'PASS {key}: trusted input; initialized/advancing gameplay; host freeze/user recovery; '+('portrait freeze/landscape user recovery; ' if touch else 'desktop Firefox layout; ')+'same run identity; one start per run; no stuck suppression'
            print(result['verdict'], flush=True)
        except Exception as error:
            result['verdict'] = 'FAIL '+repr(error)
            shot('failure')
            raise
        finally:
            result.update(game.evaluate('({inputs:inputProbe.inputs,frames:inputProbe.frames,calls:probe.calls})'))
            self.save()
            context.close()

    def test_paired_input_matrix(self):
        for engine in ('chromium','firefox'):
            for mode in ('classic','bad'):
                with self.subTest(engine=engine, mode=mode):
                    self.run_case(engine, mode)


if __name__ == '__main__':
    unittest.main()
