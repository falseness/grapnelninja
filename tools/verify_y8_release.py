"""Offline, trusted-input verification of Y8 game source or an extracted ZIP."""
import argparse,json,pathlib,sys,time,traceback
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from playwright.sync_api import sync_playwright
from browser_test_support import QuietHandler,wait_for_boot,EXTERNAL_URL
ROOT=pathlib.Path(__file__).resolve().parents[1]
SDK='https://cdn.y8.com/minimal-sdk/2-0/y8.min.js'
FAKE=(ROOT/'tools/fixtures/fake-y8-sdk.js').read_text()
def point(p,expr):
 return p.evaluate('''expr=>{const b=eval(expr);return canvasCoordsToViewportCoords({x:b.x+b.width/2,y:b.y+b.height/2})}''',expr)
def run(root,out):
 out.mkdir(parents=True,exist_ok=True);rows=[]
 with ExitStack() as stack:
  server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(root)))
  thread=Thread(target=server.serve_forever,daemon=True);thread.start();stack.callback(server.server_close);stack.callback(server.shutdown)
  pw=stack.enter_context(sync_playwright());url=f'http://127.0.0.1:{server.server_port}/'
  for engine in ['chromium','firefox','webkit']:
   b=stack.enter_context(getattr(pw,engine).launch())
   for touch,size in [(False,(1280,720)),(True,(390,844)),(True,(844,390))]:
    for mode in ['bad','classic']:
     row={'engine':engine,'touch':touch,'size':size,'mode':mode,'errors':[],'external_blocked':[]};rows.append(row)
     options={'viewport':dict(zip(['width','height'],size)),'has_touch':touch,'device_scale_factor':2 if touch else 1}
     if engine!='firefox':options['is_mobile']=touch
     c=b.new_context(**options);c.route(EXTERNAL_URL,lambda r:(row['external_blocked'].append(r.request.url.split('?')[0]),r.abort()))
     c.route(SDK,lambda r:r.fulfill(content_type='text/javascript',body=FAKE))
     p=c.new_page();p.set_default_timeout(8000);p.on('pageerror',lambda e:row['errors'].append(str(e)))
     try:
      t=time.monotonic();p.goto(url,wait_until='domcontentloaded');wait_for_boot(p);row['menu_ms']=round((time.monotonic()-t)*1000)
      p.wait_for_function('!unTouch');pt=point(p,'menu.'+mode+'VersionButton.background')
      (p.touchscreen.tap if touch else p.mouse.click)(**pt);p.wait_for_function('!menu.visible');p.wait_for_timeout(400)
      xy=p.evaluate('canvasCoordsToViewportCoords({x:width*.7,y:height*.3})')
      if touch:
       # Trusted CDP hold/cancel in Chromium; native trusted taps in other engines.
       if engine=='chromium':
        cd=c.new_cdp_session(p);cd.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[xy]});assert p.evaluate('grapnel.throwed'), 'hold did not throw';cd.send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]});assert not p.evaluate('grapnel.throwed'), 'release/cancel did not release';row['cancel']='PASS'
       else:p.touchscreen.tap(**xy)
      else:
       p.mouse.move(**xy);p.mouse.down();assert p.evaluate('grapnel.throwed'), 'hold did not throw';p.mouse.up();assert not p.evaluate('grapnel.throwed'), 'release/cancel did not release'
      p.wait_for_timeout(750);p.keyboard.press('p');p.wait_for_function('menu.gamePaused');before=p.evaluate('({x:ninja.x,y:ninja.y})');p.wait_for_timeout(100);assert before==p.evaluate('({x:ninja.x,y:ninja.y})'), 'paused position moved'
      for w,h in [(size[1],size[0]),size]:p.set_viewport_size({'width':w,'height':h});p.wait_for_timeout(250)
      p.screenshot(path=str(out/(engine+'-'+str(touch)+'-'+str(size[0])+'-'+mode+'.png')))
      p.wait_for_function('!unTouch');pt=point(p,'menu.resume.background')
      (p.touchscreen.tap if touch else p.mouse.click)(**pt)
      p.wait_for_function('!menu.gamePaused')
      before=p.evaluate('({x:ninja.x,y:ninja.y})')
      p.wait_for_function('before=>ninja.x!==before.x || ninja.y!==before.y',arg=before)
      row['resume']='PASS trusted Resume restores moving gameplay'
      p.evaluate("PROGRESS.setLang('ru'); PROGRESS.save()");p.reload(wait_until='domcontentloaded');wait_for_boot(p);assert p.evaluate('I18N.language')=='ru'
      assert not row['errors'],row['errors'];row['verdict']='PASS';print('PASS',engine,touch,size,mode,flush=True)
     except Exception as e:
      row['verdict']='FAIL';row['error']=traceback.format_exc();print('FAIL',row,flush=True)
     finally:c.close();(out/'results.json').write_text(json.dumps(rows,indent=2))
 return all(r['verdict']=='PASS' for r in rows)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=pathlib.Path,default=ROOT);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args();sys.exit(0 if run(a.root,a.out) else 1)
