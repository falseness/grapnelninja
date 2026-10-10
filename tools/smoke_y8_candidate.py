"""Audit an exact preceding Y8 candidate; never serve the working tree."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import partial
import hashlib
import importlib.metadata
import json
from http.server import ThreadingHTTPServer
import pathlib
import platform
import subprocess
import sys
from threading import Thread
import time
import traceback
import zipfile

from playwright.sync_api import sync_playwright
from browser_test_support import QuietHandler, EXTERNAL_URL, wait_for_boot
from verify_y8_release import SDK, FAKE, point


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


# Observe real input after the game's handlers. No gameplay state is injected.
OBSERVER = """() => {
    window.smokeEvents = [];
    for (const type of ['mousedown','mouseup','touchstart','touchend','keydown'])
        document.addEventListener(type, e => window.smokeEvents.push({
            type, trusted:e.isTrusted, key:e.key,
            thrown: typeof grapnel !== 'undefined' && !!grapnel && grapnel.throwed,
            t: performance.now()
        }));
    window.smokeDeaths = [];
    const original = onLethalDeath;
    onLethalDeath = function() {
        window.smokeDeaths.push({x:ninja.x,y:ninja.y,score:scoreText.count[version],
            stack:new Error().stack,t:performance.now()});
        return original.apply(this, arguments);
    };
    window.smokeNinja = ninja;
}"""
STATE = "({x:ninja.x,y:ninja.y,score:scoreText.count[version],paused:menu.gamePaused,menu:menu.visible,offer:continueOffer.visible})"


def case(browser, engine, profile, size, mode, sdk, url, out):
    row = dict(engine=engine, browser_version=browser.version, profile=profile,
               mode=mode, sdk=sdk, real_sdk=False, errors=[], console=[], responses=[],
               request_failures=[], external_blocked=[], checks={}, captures=[])
    touch = profile != 'desktop'
    opts = dict(viewport=dict(zip(('width','height'),size)), has_touch=touch,
                device_scale_factor=2 if touch else 1)
    if engine != 'firefox':
        opts['is_mobile'] = touch
    name = '-'.join((engine,profile,mode,sdk))
    with browser.new_context(**opts) as c:
        def block(r):
            row['external_blocked'].append(r.request.url)
            r.abort()
        c.route(EXTERNAL_URL, block)
        body = FAKE
        if sdk == 'unavailable':
            body = '// SDK unavailable fixture: no global, no ready event'
        elif sdk == 'delayed':
            # Arrives after the real adapter timeout, testing late SDK recovery.
            body = 'setTimeout(function(){' + FAKE + '}, 3600);'
        c.route(SDK, lambda r:r.fulfill(content_type='text/javascript',body=body))
        p = c.new_page()
        p.set_default_timeout(12000)
        p.on('pageerror',lambda e:row['errors'].append(str(e)))
        p.on('console',lambda m:row['console'].append(dict(type=m.type,text=m.text)))
        p.on('response',lambda r:row['responses'].append(dict(url=r.url,status=r.status)))
        p.on('requestfailed',lambda r:row['request_failures'].append(dict(url=r.url,error=r.failure)))
        def capture(stage):
            file = out/'captures'/(name+'-'+stage+'.png')
            file.parent.mkdir(exist_ok=True)
            p.screenshot(path=str(file))
            row['captures'].append(dict(stage=stage,path=str(file),sha256=sha(file)))
        def tap(expr):
            p.wait_for_function('!unTouch')
            (p.touchscreen.tap if touch else p.mouse.click)(**point(p,expr))
        try:
            started=time.monotonic()
            p.goto(url,wait_until='domcontentloaded')
            wait_for_boot(p)
            assert p.evaluate('menu.visible')
            row['checks']['first_menu'] = dict(result='PASS',milliseconds=round(1000*(time.monotonic()-started)))
            capture('menu')
            row['checks']['sdk_startup'] = dict(result='PASS',environment=p.evaluate('PLATFORM.environment'),fixture=sdk)
            assert row['checks']['sdk_startup']['environment'] == ('y8' if sdk=='immediate' else 'disabled')
            row['checks']['tutorial'] = dict(result='NOT_APPLICABLE',reason='No tutorial module, completion state or tutorial control in candidate; no completion claimed.')
            row['checks']['mute'] = dict(result='NOT_APPLICABLE',reason='No game audio or mute control in candidate; SDK configured sound off; no audible/phone check claimed.')
            tap('menu.'+mode+'VersionButton.background')
            p.wait_for_function('!menu.visible && !unTouch')
            p.evaluate(OBSERVER)
            before=p.evaluate(STATE)
            xy=p.evaluate('canvasCoordsToViewportCoords({x:width*.7,y:height*.3})')
            if touch:
                p.touchscreen.tap(**xy)
            else:
                p.mouse.move(**xy);p.mouse.down();p.wait_for_timeout(150);p.mouse.up()
            events=p.evaluate('smokeEvents')
            down='touchstart' if touch else 'mousedown'
            up='touchend' if touch else 'mouseup'
            assert any(e['type']==down and e['trusted'] and e['thrown'] for e in events),events
            assert any(e['type']==up and e['trusted'] and not e['thrown'] for e in events),events
            row['checks']['grapple'] = dict(result='PASS',events=events)
            p.wait_for_timeout(500)
            after=p.evaluate(STATE)
            assert (before['x'],before['y']) != (after['x'],after['y'])
            row['checks']['gameplay']=dict(result='PASS',before=before,after=after)
            capture('gameplay')
            # Use the HUD control on touch profiles too, not a hardware keyboard.
            p.wait_for_function('!unTouch')
            xy=p.evaluate('''() => { const b=menu.button.background; return canvasCoordsToViewportCoords({x:(b.x+b.width/2)*scale[version],y:(b.y+b.height/2)*scale[version]}) }''')
            (p.touchscreen.tap if touch else p.mouse.click)(**xy)
            p.wait_for_function('menu.gamePaused')
            paused=p.evaluate(STATE);p.wait_for_timeout(180)
            assert p.evaluate(STATE)==paused
            capture('pause')
            tap('menu.resume.background');p.wait_for_function('!menu.gamePaused')
            p.wait_for_timeout(180)
            assert p.evaluate(STATE)!=paused
            row['checks']['pause_resume']=dict(result='PASS',paused=paused,resumed=p.evaluate(STATE))
            # Drive the unmodified simulation with trusted input until a real collision.
            # Playwright offers only touch taps on Firefox/WebKit; sustained input
            # there uses a mouse on the emulated touch viewport, explicitly labeled.
            row['recovery_input']='trusted CDP touch hold' if touch and engine=='chromium' else 'trusted mouse hold (touch-profile fallback)' if touch else 'trusted mouse hold'
            cd=c.new_cdp_session(p) if touch and engine=='chromium' else None
            deadline=time.monotonic()+120
            attempts=0
            while not p.evaluate('smokeDeaths.length') and time.monotonic()<deadline:
                attempts+=1
                aim=p.evaluate('''attempt => {
                    const targets=floors.flatMap(f=>f.elements).filter(e=>e instanceof Rect && !(e instanceof Trampoline))
                        .map(e=>({x:e.x+e.width/2,y:e.y+e.height/2}))
                        .filter(t=>t.x>ninja.x && (t.x+screen.x)*scale[version]<width)
                        .sort((a,b)=>Math.hypot(a.x-ninja.x,a.y-ninja.y)-Math.hypot(b.x-ninja.x,b.y-ninja.y));
                    const t=targets[(attempt-1)%Math.max(1,Math.min(3,targets.length))];
                    return t ? canvasCoordsToViewportCoords({x:(t.x+screen.x)*scale[version],y:(t.y+screen.y)*scale[version]})
                        : canvasCoordsToViewportCoords({x:width*.8,y:height*(.2+.2*(attempt%3))});
                }''',attempts)
                if cd:
                    cd.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[aim]})
                else:
                    p.mouse.move(**aim);p.mouse.down()
                p.wait_for_timeout(3000+500*(attempts%3))
                if cd: cd.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                else: p.mouse.up()
                p.wait_for_timeout(400)
            assert p.evaluate('smokeDeaths.length'), 'No natural collision after 120s trusted input toward visible obstacles'
            row['recovery_attempts']=attempts
            row['checks']['natural_death']=dict(result='PASS',deaths=p.evaluate('smokeDeaths'))
            capture('death')
            if p.evaluate('continueOffer.visible'):
                tap('continueOffer.restartButton.background')
            p.wait_for_function('ninja !== smokeNinja && !continueOffer.visible && !menu.visible')
            restarted=p.evaluate(STATE);p.wait_for_timeout(250)
            assert p.evaluate(STATE)!=restarted
            row['checks']['restart']=dict(result='PASS',before=restarted,after=p.evaluate(STATE),automatic=not p.evaluate('smokeEvents.some(e=>e.t>smokeDeaths[0].t)'))
            capture('restart')
            p.keyboard.press('p');p.wait_for_function('menu.gamePaused')
            tap('menu.backToMenu.background');p.wait_for_function('menu.visible')
            tap('LANGUAGE_BUTTON.rect()')
            language=p.evaluate('I18N.language')
            p.wait_for_function("localStorage.getItem('grapnelninja.lang')===I18N.language")
            saved=p.evaluate('({lang:I18N.language,time:PROGRESS.getTime(),records:scoreText.record})')
            row['trusted_input']=p.evaluate('smokeEvents')
            assert all(e['trusted'] for e in row['trusted_input'])
            p.reload(wait_until='domcontentloaded');wait_for_boot(p)
            restored=p.evaluate('({lang:I18N.language,time:PROGRESS.getTime(),records:scoreText.record})')
            assert saved==restored,(saved,restored)
            row['checks']['save_reload']=dict(result='PASS',saved=saved,restored=restored)
            capture('reload')
            if sdk=='delayed':
                p.wait_for_function('!!window.y8')
                assert p.evaluate('PLATFORM.environment')=='disabled'
                row['checks']['late_sdk']=dict(result='PASS',environment='disabled',late_global_present=True)
            assert not row['errors'],row['errors']
            assert not [m for m in row['console'] if m['type']=='error'],row['console']
            assert not row['request_failures'],row['request_failures']
            assert not [r for r in row['responses'] if r['status']>=400],row['responses']
            assert not row['external_blocked'],row['external_blocked']
            row['checks']['http_js_errors']=dict(result='PASS',http_errors=0,uncaught_errors=0,console_errors=0,request_failures=0)
            row['verdict']='PASS'
        except Exception:
            row['verdict']='FAIL';row['error']=traceback.format_exc()
            try: capture('failure')
            except Exception: pass
        print(row['verdict'],name,json.dumps(row['checks']),flush=True)
        if row.get('error'): print(row['error'],flush=True)
    return row


def run(a):
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    candidate=json.loads(a.candidate.read_text());archive=pathlib.Path(candidate['zip'])
    assert sha(archive)==candidate['sha256']
    root=out/'extracted'
    assert not root.exists(), 'Use a fresh evidence directory to avoid mixing runs'
    root.mkdir()
    with zipfile.ZipFile(archive) as z: z.extractall(root)
    inventory={f['path']:f['sha256'] for f in candidate['files']}
    actual={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
    assert inventory==actual
    for name,digest in inventory.items():
        source=subprocess.check_output(['git','show',candidate['source_revision']+':'+name])
        assert hashlib.sha256(source).hexdigest()==digest
    print(f"PASS archive/source/served hashes: {len(actual)} files; ZIP {sha(archive)}; source {candidate['source_revision']}; served root {root}",flush=True)
    result=dict(archive_sha256=sha(archive),source=candidate['source_revision'],served_root=str(root),file_hashes=actual,
                limitations=['Local emulation only; physical phones, hosted ads, console upload and moderation not tested.',
                              'Tutorial and mute absent from this candidate; recorded NOT_APPLICABLE, not successful feature tests.'],results=[])
    result['feature_inventory']={name: name in actual for name in ('tutorial.js','mutebutton.js','audio.js')}
    with ExitStack() as stack:
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(root)))
        Thread(target=server.serve_forever,daemon=True).start()
        stack.callback(server.server_close);stack.callback(server.shutdown)
        pw=stack.enter_context(sync_playwright())
        for engine in a.engines.split(','):
            b=stack.enter_context(getattr(pw,engine).launch())
            for profile,size in [('desktop',(1280,720)),('portrait',(390,844)),('landscape',(844,390))]:
                if a.profile and profile!=a.profile: continue
                for mode in ['bad','classic']:
                    for sdk in ([{'desktop':'immediate','portrait':'unavailable','landscape':'delayed'}[profile]] if a.sdks=='balanced' else a.sdks.split(',')):
                        row=case(b,engine,profile,size,mode,sdk,f'http://127.0.0.1:{server.server_port}/',out)
                        row.update(archive_sha256=result['archive_sha256'],source=result['source'])
                        result['results'].append(row)
                        (out/'release-smoke.json').write_text(json.dumps(result,indent=2)+'\n')
                        if row['verdict']=='FAIL': return 1
    assert actual=={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
    passed=all(r['verdict']=='PASS' for r in result['results'])
    print(f"{'PASS' if passed else 'FAIL'} smoke matrix: {len(result['results'])} cases; served hashes unchanged",flush=True)
    return 0 if passed else 1


if __name__=='__main__':
    ap=argparse.ArgumentParser(__doc__)
    ap.add_argument('--candidate',type=pathlib.Path,required=True)
    ap.add_argument('--out',type=pathlib.Path,required=True)
    ap.add_argument('--engines',default='chromium,firefox,webkit')
    ap.add_argument('--profile')
    ap.add_argument('--sdks',default='balanced')
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    manifest=dict(command=[sys.executable,*sys.argv],started_utc=utc(),environment=dict(python=sys.version,platform=platform.platform(),playwright=importlib.metadata.version('playwright')),harness_sha256=sha(pathlib.Path(__file__)),candidate_manifest=str(a.candidate.resolve()))
    print('COMMAND '+json.dumps(manifest['command']),flush=True)
    print('START_UTC '+manifest['started_utc'],flush=True)
    print('ENVIRONMENT '+json.dumps(manifest['environment']),flush=True)
    try: code=run(a)
    except Exception: traceback.print_exc();code=1
    manifest.update(ended_utc=utc(),exit_code=code)
    (a.out/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('END_UTC '+manifest['ended_utc'],flush=True)
    print('EXIT_CODE='+str(code),flush=True)
    sys.exit(code)
