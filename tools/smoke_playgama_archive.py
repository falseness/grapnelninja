"""Historical: smoke a pre-inlining multi-file ZIP; not used by docs/playgama-release.md."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urlparse, unquote
import zipfile
from browser_test_support import start_browser_test, wait_for_boot
from test_playgama2_bridge import SDK, FAKE
from test_playgama2_audio import PROBE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True); parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    report={'zip_sha256':hashlib.sha256(args.zip.read_bytes()).hexdigest(),'cases':[],
            'limitations':['Chromium desktop and emulated touch, not physical mobile hardware.', 'SDK normal/rejected initialization are network-boundary fixtures; live portal not tested.']}
    with ExitStack() as stack:
        root=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='playgama-release-')))
        extracted=root/'nested/game/release'; extracted.mkdir(parents=True)
        with zipfile.ZipFile(args.zip) as z:
            for name in z.namelist():
                assert not Path(name).is_absolute() and '..' not in Path(name).parts
            z.extractall(extracted)
        assert all(not p.is_symlink() for p in root.rglob('*'))
        url,browser=start_browser_test(root,stack.callback)
        report.update(server_root=str(root),extracted_root=str(extracted),browser=browser.version,
                      extracted_files={str(p.relative_to(extracted)):hashlib.sha256(p.read_bytes()).hexdigest() for p in extracted.rglob('*') if p.is_file()})
        for touch in (False,True):
            for mode in ('classic','bad'):
                for fault in ('normal','init_rejected'):
                    case=f'{"touch" if touch else "desktop"}-{mode}-{fault}'
                    ctx=browser.new_context(viewport={'width':960 if touch else 1280,'height':540 if touch else 720},has_touch=touch,device_scale_factor=1)
                    ctx.add_init_script(PROBE)
                    ctx.route(SDK,lambda route:route.fulfill(content_type='application/javascript',body=f'const FAULT={json.dumps(fault)},SAVED_LANGUAGE="en";'+FAKE))
                    p=ctx.new_page(); errors=[]; network=[]; console=[]
                    p.on('pageerror',lambda e:errors.append(str(e)))
                    p.on('console',lambda m:console.append(m.text))
                    p.on('response',lambda r:network.append({'url':r.url,'status':r.status}))
                    p.on('requestfailed',lambda r:errors.append(f'{r.url}: {r.failure}'))
                    try:
                        p.goto(url+'nested/game/release/index.html'); wait_for_boot(p)
                        p.wait_for_function('bootComplete && !unTouch')
                        readiness=p.evaluate('({complete:bootComplete,loading:document.getElementById("loading").hidden,environment:PLATFORM.environment,calls:probe.calls})')
                        assert readiness['environment']==('playgama' if fault=='normal' else 'disabled')
                        if fault=='normal': assert sum(c['name']=='game_ready' for c in readiness['calls'])==1
                        else: assert any('initialize failed' in m for m in console)
                        point=p.evaluate('''mode=>{const b=menu[mode+'VersionButton'].background,r=canvas.getBoundingClientRect();return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}}''',mode)
                        (p.touchscreen.tap if touch else p.mouse.click)(**point)
                        p.wait_for_function('!menu.visible && !unTouch')
                        if p.locator('#tutorial button').is_visible():
                            (p.locator('#tutorial button').tap if touch else p.locator('#tutorial button').click)()
                        p.wait_for_function('!unTouch')
                        (p.touchscreen.tap if touch else p.mouse.click)(700,180)
                        state=p.evaluate('({mode:version,menu:menu.visible,grapple:__audioLog.some(e=>e.name==="throw" && !e.muted)})')
                        assert state['mode']==mode and not state['menu'] and state['grapple'],state
                        capture=args.out/(case+'.png');p.screenshot(path=str(capture))
                        audio=[]
                        for muted in (False,True,False):
                            if audio: (p.locator('#mute-button').tap if touch else p.locator('#mute-button').click)()
                            p.wait_for_timeout(150);p.evaluate('audioProbe.chunks=[]');p.wait_for_timeout(350)
                            sample=p.evaluate('''()=>{const pcm=audioProbe.chunks.flatMap(c=>c.pcm);return {samples:pcm.length,rms:Math.sqrt(pcm.reduce((s,v)=>s+v*v,0)/Math.max(1,pcm.length)),state:AUDIO.getState()}}''')
                            assert muted or sample['samples']>0,sample
                            assert sample['rms']<.00001 if muted else sample['rms']>.001,sample
                            audio.append(sample)
                        inputs=p.evaluate('audioProbe.inputs');assert any(i['trusted'] for i in inputs)
                        assert not errors,errors
                        for req in network:
                            assert req['status']==200,req
                            if req['url']!=SDK:
                                assert req['url'].startswith(url+'nested/game/release/'),req
                                local=root/unquote(urlparse(req['url']).path).lstrip('/')
                                assert local.is_file() and local.resolve().is_relative_to(extracted),req
                        requested={unquote(urlparse(r['url']).path).removeprefix('/nested/game/release/') for r in network if r['url']!=SDK}
                        expected=set(report['extracted_files'])-({'playgama-bridge-config.json'} if fault!='normal' else set())
                        assert expected<=requested,expected-requested
                        report['cases'].append(dict(case=case,readiness=readiness,state=state,audio=audio,inputs=inputs,network=network,errors=errors,console=console,capture=str(capture),capture_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),verdict='PASS'))
                        print(f'PASS {case}: extracted-only nested requests all 200; trusted input/grapple; audio audible/muted/restored; readiness; native capture {capture.name}',flush=True)
                    finally:
                        (args.out/'smoke.json').write_text(json.dumps(report,indent=2)+'\n')
                        ctx.close()
    print('PASS eight extracted-ZIP cases; no checkout fallback, page errors or failed requests')
if __name__=='__main__':main()
