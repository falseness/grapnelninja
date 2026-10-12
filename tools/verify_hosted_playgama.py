"""Read-only hosted QA with real Bridge and real browser input; no SDK mocks.

Uses fresh anonymous browser contexts. Saves traces and native screenshots, never
certifies physical devices or submits moderation. Run after uploading the ZIP.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright


def state(frame):
    return frame.evaluate('''() => ({mode:version, menu:menu.visible,
        paused:menu.gamePaused, dead:continueOffer.visible, x:ninja?.x ?? null,
        time:PROGRESS.getTime(), records:{...scoreText.record},
        muted:PROGRESS.getMuted(), language:I18N.language,
        tutorial:PROGRESS.getTutorialDone(), readiness:PLATFORM.readiness,
        platform:PLATFORM.platformId, environment:PLATFORM.environment,
        audio:AUDIO.getState(), viewport:{width:innerWidth,height:innerHeight},
        scroll:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}})''')


def click(page, frame, expression, touch=False):
    frame.wait_for_function('!unTouch && !interstitialPending && !adOpen')
    point = frame.evaluate('''() => {const b=''' + expression + ''';
        return {x:(b.x+b.width/2)/width,y:(b.y+b.height/2)/height}}''')
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


def run(args):
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
                    row['menu'] = state(frame)
                    assert row['menu']['environment'] == 'playgama'
                    assert row['menu']['readiness']['attempts'] == 1
                    body = page.locator('body').inner_text()
                    assert 'config passed to initialize() as an external URL' not in body, body
                    assert not row['page_errors'], row['page_errors']
                    page.screenshot(path=str(args.out/(case+'-menu.png')))
                    click(page, frame, 'menu.'+mode+'VersionButton.background', touch)
                    if frame.locator('#tutorial button').is_visible():
                        (frame.locator('#tutorial button').tap if touch else frame.locator('#tutorial button').click)()
                    frame.wait_for_function('!unTouch && !menu.visible')
                    row['started'] = state(frame)
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
                    page.screenshot(path=str(args.out/(case+'-gameplay.png')))
                    if frame.evaluate('continueOffer.visible'):
                        row['natural_death']=True
                    else:
                        # Real input pauses and commits elapsed play before reload.
                        page.keyboard.press('p')
                        frame.wait_for_function('menu.gamePaused')
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
                    # Language control is part of the menu/HUD and uses ordinary input.
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
                    for key in ['time','records','muted','language','tutorial']:
                        assert row['saved'][key]==row['reloaded'][key], (key,row['saved'][key],row['reloaded'][key])
                    assert not row['page_errors'],row['page_errors']
                    assert all(r['status'] in (200,304) for r in row['requests']),row['requests']
                    assert any(r['url'].split('?')[0].endswith('/playgama-bridge-config.json') for r in row['requests'])
                    row['qa_text']=page.locator('body').inner_text()
                    assert 'config passed to initialize() as an external URL' not in row['qa_text']
                    page.screenshot(path=str(args.out/(case+'-reload.png')))
                    row['verdict']='PASS'
                    print('PASS',case,'real ready/input/movement/audio settings/SDK save/reload; config error absent',flush=True)
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
