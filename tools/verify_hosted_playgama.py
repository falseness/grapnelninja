"""Read-only hosted QA with real Bridge and real browser input; no SDK mocks.

Uses fresh anonymous browser contexts. Saves traces and native screenshots, never
certifies physical devices or submits moderation. Run after uploading the ZIP.

Boot starts a 'bad' run with no title menu (TASK-360/364). Classic is reached
by real clicks on the HUD menu button and the pause-screen mode switch
(TASK-362); the first held press dismisses the canvas tutorial hint
(TASK-366/367); a death with no interstitial due restarts at once (TASK-370).
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright


def state(frame):
    return frame.evaluate('''() => ({mode:version, running:runInProgress,
        paused:menu.gamePaused, dead:continueOffer.visible, x:ninja?.x ?? null,
        time:PROGRESS.getTime(), records:{...scoreText.record},
        muted:PROGRESS.getMuted(), language:I18N.language,
        hint:{visible:TUTORIAL_HINT.visible, pressed:TUTORIAL_HINT.pressed}, readiness:PLATFORM.readiness,
        platform:PLATFORM.platformId, environment:PLATFORM.environment,
        audio:AUDIO.getState(), viewport:{width:innerWidth,height:innerHeight},
        scroll:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}})''')


def click(page, frame, expression, touch=False, scaled=False):
    """Real click/tap on a canvas rect; HUD menu button rects are in scale[version] units."""
    frame.wait_for_function('!unTouch && !interstitialPending && !adOpen')
    point = frame.evaluate('''scaled => {const b=''' + expression + ''', s=scaled ? scale[version] : 1;
        return {x:(b.x+b.width/2)*s/width,y:(b.y+b.height/2)*s/height}}''', scaled)
    bounds = frame.locator('#canvas').bounding_box()
    (page.touchscreen.tap if touch else page.mouse.click)(
        bounds['x'] + point['x'] * bounds['width'],
        bounds['y'] + point['y'] * bounds['height'])


def game_frame(page):
    for _ in range(200):
        for frame in page.frames:
            if '.games.playgama.net/' in frame.url:
                frame.wait_for_function('typeof bootComplete !== "undefined" && bootComplete', timeout=20000)
                frame.wait_for_function('PLATFORM.readiness.state === "success"', timeout=20000)
                return frame
        page.wait_for_timeout(100)
    raise AssertionError('Hosted game iframe missing')


def context_options(devices, engine, touch, phone):
    """new_context options for one case; the case label's touch flag always wins."""
    options = {'viewport':{'width':1280,'height':720}}
    if phone:
        options.update(devices['Pixel 7'])
        options.pop('default_browser_type', None)
        options.update(viewport={'width':915,'height':412}, screen={'width':915,'height':412})
        if not touch:
            # Desktop keeps the phone-sized screen but not the mobile identity.
            options.pop('user_agent', None)
    options['has_touch'] = touch
    if engine == 'firefox' or not touch:
        # Firefox rejects is_mobile; a desktop case must not be a mobile context.
        options.pop('is_mobile', None)
    return options


def pause(page, frame, touch):
    """Real click on the HUD menu button."""
    if not frame.evaluate('menu.gamePaused'):
        click(page, frame, 'menu.button.background', touch, scaled=True)
        frame.wait_for_function('menu.gamePaused')


def start_mode(page, frame, mode, touch):
    """Leave a running, unpaused run of `mode` using real input only."""
    if frame.evaluate('version') != mode:
        pause(page, frame, touch)
        click(page, frame, 'menu.backToMenu.background', touch)
    elif frame.evaluate('menu.gamePaused'):
        # A host-paused, rotated or hidden boot run waits on the pause screen
        click(page, frame, 'menu.resume.background', touch)
    frame.wait_for_function('m => version === m && runInProgress && !menu.gamePaused && !unTouch', arg=mode)


def run(args, prepare=None):
    """`prepare(context)` may install routes; the offline flow test uses it."""
    args.out.mkdir(parents=True, exist_ok=True)
    report = {'url':args.url, 'cases':[], 'limitations':[
        'Fresh anonymous Linux browser contexts; touch profiles emulate devices.',
        'Real Playgama Bridge/host, with no game or SDK replacements.',
        'Bounded gameplay, not proof for every possible procedural run or legacy OS.']}
    def save():
        (args.out/'hosted.json').write_text(json.dumps(report, indent=2)+'\n')
    with sync_playwright() as pw:
        launch = {'headless':not args.headed}
        if args.executable_path: launch['executable_path']=args.executable_path
        browser = getattr(pw, args.engine).launch(**launch)
        report.update(engine=args.engine, browser=browser.version)
        devices = (False, True) if args.device == 'both' else (args.device == 'touch',)
        for touch in devices:
            for mode in args.modes:
                case = f'{args.engine}-{"touch" if touch else "desktop"}-{mode}'
                row = {'case':case, 'verdict':'INCOMPLETE', 'page_errors':[], 'requests':[], 'console':[]}
                report['cases'].append(row)
                options = context_options(pw.devices, args.engine, touch, args.phone)
                row['context_options'] = options
                context = browser.new_context(**options)
                if prepare: prepare(context)
                page = context.new_page()
                page.set_default_timeout(20000)
                page.on('pageerror', lambda e: row['page_errors'].append(str(e)))
                page.on('console', lambda m: row['console'].append({'type':m.type,'text':m.text}))
                def response(r):
                    if '.games.playgama.net/' in r.url or 'bridge.playgama.com/' in r.url:
                        row['requests'].append({'url':r.url, 'status':r.status})
                page.on('response', response)
                try:
                    start = time.monotonic()
                    page.goto(args.url, wait_until='domcontentloaded')
                    frame = game_frame(page)
                    row['ready_wall_ms'] = round((time.monotonic()-start)*1000)
                    row['frame_url'] = frame.url
                    row['boot'] = state(frame)
                    assert row['boot']['environment'] == 'playgama'
                    assert row['boot']['readiness']['attempts'] == 1
                    assert row['boot']['running'] and row['boot']['mode'] == 'bad', row['boot']
                    assert row['boot']['hint'] == {'visible':True, 'pressed':False}, row['boot']['hint']
                    body = page.locator('body').inner_text()
                    assert 'config passed to initialize() as an external URL' not in body, body
                    assert not row['page_errors'], row['page_errors']
                    page.screenshot(path=str(args.out/(case+'-boot.png')))
                    start_mode(page, frame, mode, touch)
                    row['started'] = state(frame)
                    assert row['started']['hint'] == {'visible':True, 'pressed':False}, row['started']['hint']
                    samples=[]
                    for _ in range(12):
                        if frame.evaluate('continueOffer.visible'): break
                        bounds=frame.locator('#canvas').bounding_box()
                        x,y=bounds['x']+bounds['width']*.72,bounds['y']+bounds['height']*.22
                        if touch and args.engine == 'chromium':
                            session=context.new_cdp_session(page)
                            session.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
                            page.wait_for_timeout(1000)
                            session.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
                            session.detach()
                        elif touch: page.touchscreen.tap(x,y)
                        else:
                            page.mouse.move(x,y);page.mouse.down();page.wait_for_timeout(1000);page.mouse.up()
                        page.wait_for_timeout(350)
                        samples.append(state(frame))
                    row['gameplay']=samples
                    assert samples and any(s['x'] != row['started']['x'] for s in samples), 'No horizontal movement from held grapple input'
                    assert samples[-1]['hint']['pressed'], 'Held press did not dismiss the tutorial hint'
                    assert all(s['mode'] == mode for s in samples), 'Run left the mode under test'
                    page.screenshot(path=str(args.out/(case+'-gameplay.png')))
                    if frame.evaluate('continueOffer.visible'):
                        row['natural_death']=True
                    else:
                        # Real input pauses and commits elapsed play before reload.
                        pause(page, frame, touch)
                        row['paused']=state(frame)
                    row['after_run']=state(frame)
                    page.wait_for_timeout(1400)
                    page.reload(wait_until='domcontentloaded')
                    frame=game_frame(page)
                    row['run_reloaded']=state(frame)
                    assert row['run_reloaded']['time'] == row['after_run']['time']
                    assert row['run_reloaded']['records'] == row['after_run']['records']
                    mute=frame.locator('#mute-button')
                    (mute.tap if touch else mute.click)()
                    frame.wait_for_function('PROGRESS.getMuted()')
                    # The language button is on the pause screen; pausing also saves.
                    pause(page,frame,touch)
                    click(page,frame,'LANGUAGE_BUTTON.rect()',touch)
                    frame.wait_for_function('I18N.language === "ru"')
                    page.wait_for_timeout(1400)
                    row['saved']=state(frame)
                    row['sdk_values']=frame.evaluate('Promise.race([bridge.storage.get(PROGRESS.keys),new Promise((_,reject)=>setTimeout(()=>reject(Error("SDK read timeout")),5000))])')
                    assert row['saved']['audio']['muted']['user'], row['saved']['audio']
                    assert row['saved']['audio']['gain'] == 0, row['saved']['audio']
                    assert row['saved']['time']>0, 'Play time did not persist on pause/death'
                    page.reload(wait_until='domcontentloaded')
                    frame=game_frame(page)
                    row['reloaded']=state(frame)
                    for key in ['time','records','muted','language']:
                        assert row['saved'][key]==row['reloaded'][key], (key,row['saved'][key],row['reloaded'][key])
                    # The hint is not persisted: every page load shows it on the boot run
                    assert row['reloaded']['hint'] == {'visible':True, 'pressed':False}, row['reloaded']['hint']
                    assert not row['page_errors'],row['page_errors']
                    assert all(r['status'] in (200,304) for r in row['requests']),row['requests']
                    assert any(r['url'].split('?')[0].endswith('/playgama-bridge-config.json') for r in row['requests'])
                    row['qa_text']=page.locator('body').inner_text()
                    assert 'config passed to initialize() as an external URL' not in row['qa_text']
                    page.screenshot(path=str(args.out/(case+'-reload.png')))
                    row['verdict']='PASS'
                    print('PASS',case,'real ready/boot run/mode switch/input/hint dismissal/movement/audio settings/SDK save/reload; config error absent',flush=True)
                except Exception as error:
                    row['verdict']='FAIL';row['error']=str(error)
                    save()
                    try: page.screenshot(path=str(args.out/(case+'-failure.png')))
                    except Exception as capture_error: row['capture_error']=str(capture_error);save()
                    raise
                finally:
                    save();context.close()
        browser.close()
    report['captures']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.out.glob('*.png')}
    save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--engine',choices=['chromium','firefox','webkit'],default='chromium')
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--executable-path')
    parser.add_argument('--device',choices=['both','desktop','touch'],default='both')
    parser.add_argument('--phone',action='store_true',help='Use Pixel 7 landscape emulation')
    parser.add_argument('--modes',nargs='+',choices=['bad','classic'],default=['bad','classic'])
    run(parser.parse_args())
