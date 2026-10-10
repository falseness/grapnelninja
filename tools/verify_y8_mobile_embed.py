"""Offline TASK-258 nested-embed proof. Chromium emulation, never native phones.

Run against an extracted release archive; writes incremental JSON even on failure.
Viewport/orientation overrides model rotation and browser bars, not physical UI.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import hashlib
import struct
from pathlib import Path
import traceback

from browser_test_support import start_browser_test, wait_for_boot

INIT = '''window.__touches=[];
for(const type of ['touchstart','touchmove','touchend','touchcancel'])
 document.addEventListener(type,e=>__touches.push({type,trusted:e.isTrusted,
 x:e.changedTouches[0]?.clientX,y:e.changedTouches[0]?.clientY}),true);'''
STATE = '''() => ({iframe:[innerWidth,innerHeight], orientation:window.screen.orientation.type,
 active_element:document.activeElement.tagName, rotated:isViewRotated(),
 menu:menu.visible,paused:menu.gamePaused,throwed:grapnel?.throwed||false,
 scroll:[scrollX,scrollY],stage_hidden:canvas.hidden,stage_inert:!!canvas.closest('[inert]'),
 canvas_rect:canvas.getBoundingClientRect().toJSON(),progress:PROGRESS.getLang(),
 fullscreen_enabled:document.fullscreenEnabled, fullscreen:!!document.fullscreenElement,
 physics_steps:window.__physicsSteps,score:scoreText.count[version],version})'''


def run(root, out):
    out.mkdir(parents=True, exist_ok=True)
    (out/'captures').mkdir(exist_ok=True)
    report = {'utc': datetime.now(timezone.utc).isoformat(), 'runs': [],
              'limits': ['Chromium Linux touch emulation; native phones unavailable.',
                         'Physical orientation modeled with CDP screenOrientation independent of iframe CSS size.',
                         'Browser bars modeled by viewport height changes; native browser chrome unavailable.',
                         'No tutorial screen/control exists in this runtime; first-run hold/release exercises its input.',
                         'No live SDK, advertisements, upload or moderation.'], 'verdict': 'FAIL'}
    def save():
        (out/'mobile-embed.json').write_text(json.dumps(report, indent=2)+'\n')
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        report['browser_version'] = browser.version
        for mode in ('bad', 'classic'):
            for fullscreen in (True, False):
                label = mode + ('-fullscreen' if fullscreen else '-no-fullscreen')
                row = {'id': label, 'mode': mode, 'fullscreen_allowed': fullscreen,
                       'states': [], 'coordinate_checks': [], 'captures': [], 'errors': []}
                report['runs'].append(row)
                context = browser.new_context(viewport={'width':390,'height':844}, has_touch=True,
                                              is_mobile=True, device_scale_factor=1)
                context.add_init_script(INIT)
                page = context.new_page()
                page.set_default_timeout(15000)
                page.on('pageerror', lambda e: row['errors'].append(str(e)))
                host = '''<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0}iframe{border:0;display:block}</style>
<button id="fs" onclick="document.querySelector('iframe').contentDocument.querySelector('iframe').contentDocument.documentElement.requestFullscreen().then(()=>window.fsResult='entered',()=>window.fsResult='denied')">Fullscreen fixture</button>
<iframe src="wrapper.html" allow="fullscreen" style="width:100%;height:780px"></iframe>'''
                wrapper = '''<style>body{margin:0}iframe{border:0;display:block}</style>
<iframe src="index.html" allow="fullscreen" style="margin:8px;width:374px;height:720px"></iframe>'''
                context.route(url+'host.html', lambda r:r.fulfill(body=host, content_type='text/html',
                    headers={'Permissions-Policy':'fullscreen=(self)' if fullscreen else 'fullscreen=()'}))
                context.route(url+'wrapper.html', lambda r:r.fulfill(body=wrapper, content_type='text/html'))
                try:
                    page.goto(url+'host.html', wait_until='load')
                    frame = next(f for f in page.frames if f.url==url+'index.html')
                    wrap = frame.parent_frame
                    wait_for_boot(frame)
                    frame.evaluate("() => {window.__physicsSteps=0;const oldPhysics=physics;physics=function(){__physicsSteps++;return oldPhysics.apply(this,arguments)}}")
                    frame.wait_for_function('!unTouch')
                    cd = context.new_cdp_session(page)
                    def snapshot(name):
                        s = frame.evaluate(STATE)
                        s.update(name=name, host=page.evaluate('({size:[innerWidth,innerHeight],scroll:[scrollX,scrollY],active:document.activeElement.tagName})'),
                                 wrapper=wrap.evaluate('({size:[innerWidth,innerHeight],scroll:[scrollX,scrollY],active:document.activeElement.tagName})'))
                        assert not s['stage_hidden'] and not s['stage_inert'], s
                        assert s['scroll']==[0,0] and s['host']['scroll']==[0,0] and s['wrapper']['scroll']==[0,0],s
                        row['states'].append(s)
                        name=f'captures/{label}-{len(row["states"]):02}-{name}.png'
                        page.screenshot(path=str(out/name))
                        row['captures'].append(name)
                        print('PASS',label,s['name'],json.dumps(s),flush=True)
                        save()
                        return s
                    def xy(expr):
                        data=frame.evaluate('''expr=>{const b=eval(expr);const logical={x:b.x+b.width/2,y:b.y+b.height/2};
const viewport=canvasCoordsToViewportCoords(logical);const back=viewportCoordsToCanvasCoords(viewport);
return {logical,viewport,back,error:Math.hypot(logical.x-back.x,logical.y-back.y)}}''',expr)
                        assert data['error']<0.001,data
                        bounds=frame.frame_element().bounding_box()
                        data['top']={'x':bounds['x']+data['viewport']['x'],'y':bounds['y']+data['viewport']['y']}
                        data['target']=expr
                        row['coordinate_checks'].append(data)
                        return data['top']
                    def tap(expr):
                        frame.wait_for_function('!unTouch')
                        page.touchscreen.tap(**xy(expr))
                        event=frame.evaluate('__touches.filter(e=>e.type==="touchstart").at(-1)')
                        check=row['coordinate_checks'][-1]
                        assert event['trusted'] and abs(event['x']-check['viewport']['x'])<1 and abs(event['y']-check['viewport']['y'])<1,event
                        check['observed_trusted_touch']=event
                    def hold(end='touchEnd'):
                        point=xy('({x:width*.65,y:height*.25,width:0,height:0})')
                        cd.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
                        assert frame.evaluate('grapnel.throwed'),'hold failed'
                        # A trusted drag must neither scroll the parent nor lose input.
                        cd.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[dict(x=point['x']+3,y=point['y']+3)]})
                        cd.send('Input.dispatchTouchEvent',{'type':end,'touchPoints':[]})
                        assert not frame.evaluate('grapnel.throwed'),'release failed'
                        row.setdefault('holds',[]).append({'end':end,'throwed_before':True,'throwed_after':False})
                    snapshot('loaded-menu')
                    tap('menu.'+mode+'VersionButton.background')
                    frame.wait_for_function('!menu.visible && !unTouch')
                    hold();hold('touchCancel')
                    snapshot('first-run-input')
                    frame.evaluate("PROGRESS.setLang('ru');PROGRESS.save();PROGRESS.flush()")
                    # Pause via HUD; hold cancellation is tested above, blur interruption below.
                    tap('({x:menu.button.background.x*scale[version],y:menu.button.background.y*scale[version],width:menu.button.background.width*scale[version],height:menu.button.background.height*scale[version]})')
                    frame.wait_for_function('menu.gamePaused')
                    snapshot('touch-paused')
                    scenarios=[('landscape-1',844,390,800,320,'landscapePrimary'),
                               ('portrait-1',390,844,374,720,'portraitPrimary'),
                               ('landscape-2',844,390,800,320,'landscapePrimary'),
                               ('portrait-2',390,844,374,720,'portraitPrimary'),
                               ('physical-landscape-fixed-portrait',1000,850,374,720,'landscapePrimary'),
                               ('bars-expanded',390,700,374,580,'portraitPrimary'),
                               ('bars-collapsed',390,844,374,720,'portraitPrimary')]
                    for name,w,h,fw,fh,orientation in scenarios:
                        before=frame.evaluate('({x:ninja.x,y:ninja.y,score:scoreText.count[version]})')
                        cd.send('Emulation.setDeviceMetricsOverride',{'width':w,'height':h,'deviceScaleFactor':1,'mobile':True,
                            'screenOrientation':{'type':orientation,'angle':90 if orientation.startswith('landscape') else 0}})
                        page.set_viewport_size({'width':w,'height':h})
                        page.locator('iframe').evaluate('(el,h)=>el.style.height=h+"px"',h-30)
                        wrap.locator('iframe').evaluate('(el,s)=>{el.style.width=s[0]+"px";el.style.height=s[1]+"px"}',[fw,fh])
                        frame.wait_for_function('s=>innerWidth===s[0]&&innerHeight===s[1]',arg=[fw,fh])
                        page.wait_for_timeout(200)
                        assert before==frame.evaluate('({x:ninja.x,y:ninja.y,score:scoreText.count[version]})'),'resize lost run state'
                        assert frame.evaluate('PROGRESS.getLang()')=='ru'
                        s=snapshot(name)
                        assert s['paused'] and s['rotated']==(fw<fh)
                        tap('menu.resume.background');frame.wait_for_function('!menu.gamePaused')
                        hold('touchCancel')
                        steps=frame.evaluate('__physicsSteps')
                        frame.wait_for_function('n=>__physicsSteps>n',arg=steps)
                        snapshot(name+'-resumed')
                        tap('({x:menu.button.background.x*scale[version],y:menu.button.background.y*scale[version],width:menu.button.background.width*scale[version],height:menu.button.background.height*scale[version]})')
                        frame.wait_for_function('menu.gamePaused')
                    page.locator('#fs').tap()
                    page.wait_for_function('window.fsResult')
                    row['fullscreen_result']=page.evaluate('fsResult')
                    assert row['fullscreen_result']==('entered' if fullscreen else 'denied')
                    page.wait_for_timeout(350)
                    snapshot('fullscreen-result')
                    if fullscreen:
                        frame.evaluate('document.exitFullscreen()')
                        frame.wait_for_function('!document.fullscreenElement')
                    tap('menu.resume.background');frame.wait_for_function('!menu.gamePaused')
                    cd.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[xy('({x:width*.65,y:height*.25,width:0,height:0})')]})
                    assert frame.evaluate('grapnel.throwed')
                    frame.evaluate("window.dispatchEvent(new Event('blur'))")
                    assert frame.evaluate('menu.gamePaused && !grapnel.throwed')
                    cd.send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]})
                    row['interrupted_hold']='PASS synthetic blur during trusted hold clears grapple and pauses'
                    snapshot('interrupted-hold')
                    tap('menu.backToMenu.background');frame.wait_for_function('menu.visible')
                    snapshot('post-rotation-menu')
                    tap('menu.'+mode+'VersionButton.background');frame.wait_for_function('!menu.visible && !unTouch')
                    hold();snapshot('post-rotation-restart')
                    row['touch_events']=frame.evaluate('__touches')
                    assert row['touch_events'] and all(e['trusted'] for e in row['touch_events'])
                    assert not row['errors'],row['errors']
                    row['verdict']='PASS'
                except Exception:
                    row['verdict']='FAIL';row['error']=traceback.format_exc()
                    print(row['error'],flush=True)
                finally:
                    save();context.close()
    report['verdict']='PASS' if all(r['verdict']=='PASS' for r in report['runs']) else 'FAIL'
    save();print('OVERALL',report['verdict'],'runs',len(report['runs']),flush=True)
    return report['verdict']=='PASS'


def audit(out):
    """Cheap evidence audit; no browser launch."""
    data=json.loads((out/'mobile-embed.json').read_text())
    assert data['verdict']=='PASS' and len(data['runs'])==4
    log=(out/'mobile-embed.log').read_text()
    assert 'OVERALL PASS runs 4' in log and 'exit_code=0' in log
    for run in data['runs']:
        assert run['verdict']=='PASS' and not run['errors']
        states={s['name']:s for s in run['states']}
        for name in ['landscape-1','portrait-1','landscape-2','portrait-2',
                     'physical-landscape-fixed-portrait','bars-expanded','bars-collapsed']:
            s=states[name];resumed=states[name+'-resumed']
            assert s['paused'] and not resumed['paused'] and resumed['physics_steps']>s['physics_steps']
            assert s['progress']==resumed['progress']=='ru'
        fixed=states['physical-landscape-fixed-portrait']
        assert fixed['orientation']=='landscape-primary' and fixed['rotated']
        assert fixed['iframe']==[374,720] and fixed['host']['size']==[1000,850]
        assert states['loaded-menu']['menu'] and states['post-rotation-menu']['menu']
        assert not states['post-rotation-restart']['menu']
        assert run['fullscreen_result']==('entered' if run['fullscreen_allowed'] else 'denied')
        assert states['fullscreen-result']['fullscreen']==run['fullscreen_allowed']
        assert states['interrupted-hold']['paused'] and not states['interrupted-hold']['throwed']
        assert {h['end'] for h in run['holds']}=={'touchEnd','touchCancel'}
        assert all(e['trusted'] for e in run['touch_events'])
        assert all(c['error']<0.001 for c in run['coordinate_checks'])
        assert any('observed_trusted_touch' in c for c in run['coordinate_checks'])
        for s in states.values():
            assert not s['stage_hidden'] and not s['stage_inert']
            assert s['scroll']==s['host']['scroll']==s['wrapper']['scroll']==[0,0]
            assert 'PASS '+run['id']+' '+s['name']+' ' in log
        assert len(run['captures'])==len(states)
        for name in run['captures']:
            content=(out/name).read_bytes()
            assert content[:8]==b'\x89PNG\r\n\x1a\n' and len(content)>1000
            assert min(struct.unpack('>II',content[16:24]))>=320
        print('PASS',run['id'],'repeated rotations, coordinate checks, trusted input, progress, fullscreen, interrupted hold, menu/restart;',len(states),'captures')
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['commands'] and all(c['exit_code']==0 and c['utc'] and c['argv'] for c in manifest['commands'])
    assert manifest['source_revision'] and manifest['environment'] and manifest['archive_sha256']
    for name,digest in manifest['sha256'].items():
        assert hashlib.sha256((out/name).read_bytes()).hexdigest()==digest,name
    assert hashlib.sha256((out/'tested.zip').read_bytes()).hexdigest()==manifest['archive_sha256']
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==manifest['runner_sha256']
    print('PASS mobile-embed.json / mobile-embed.log: four complete cases and exact pass markers')
    print('PASS manifest.json: commands/exit codes/UTC/source/archive/environment/evidence paths and hashes')
    print('PASS captures: all',sum(len(r['captures']) for r in data['runs']),'files exist and have valid PNG dimensions; visual review recorded separately')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path)
    ap.add_argument('--audit',action='store_true')
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    if args.audit:
        audit(args.out)
    else:
        if not args.root: ap.error('--root is required for capture')
        raise SystemExit(0 if run(args.root,args.out) else 1)
