"""Local extracted-release lifecycle checks; synthetic visibility, emulated touch."""
import argparse,json,pathlib,time
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from playwright.sync_api import sync_playwright
from browser_test_support import QuietHandler,EXTERNAL_URL,wait_for_boot
from verify_y8_release import SDK,FAKE,point

def run(root,out):
 out.mkdir(parents=True,exist_ok=True);rows=[]
 with ExitStack() as stack:
  server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(root)))
  Thread(target=server.serve_forever,daemon=True).start();stack.callback(server.server_close);stack.callback(server.shutdown)
  pw=stack.enter_context(sync_playwright())
  for engine in ['chromium','webkit']:
   b=stack.enter_context(getattr(pw,engine).launch())
   for mode in ['bad','classic']:
    c=b.new_context(viewport={'width':844,'height':390},has_touch=True,is_mobile=True,device_scale_factor=2)
    c.route(EXTERNAL_URL,lambda r:r.abort());c.route(SDK,lambda r:r.fulfill(content_type='text/javascript',body=FAKE))
    p=c.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)));p.goto(f'http://127.0.0.1:{server.server_port}/');wait_for_boot(p)
    p.touchscreen.tap(**point(p,'menu.'+mode+'VersionButton.background'));p.wait_for_function('!menu.visible && !unTouch')
    p.evaluate("window.dispatchEvent(new Event('blur'))");p.wait_for_function('menu.gamePaused')
    before=p.evaluate('({x:ninja.x,y:ninja.y,hold:grapnel.throwed})');p.wait_for_timeout(150);assert before==p.evaluate('({x:ninja.x,y:ninja.y,hold:grapnel.throwed})');assert not before['hold']
    sizes=[]
    for i in range(10):
     p.set_viewport_size({'width':390 if i%2==0 else 844,'height':844 if i%2==0 else 390});p.wait_for_timeout(60)
     sizes.append(p.evaluate('({width:canvas.width,height:canvas.height,canvases:document.querySelectorAll("canvas").length})'))
    assert len(set(s['canvases'] for s in sizes))==1
    p.keyboard.press('p');p.wait_for_function('!menu.gamePaused')
    p.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
    assert p.evaluate('menu.gamePaused')
    p.evaluate("delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'))")
    assert p.evaluate('menu.gamePaused')
    p.screenshot(path=str(out/(engine+'-'+mode+'.png')))
    p.keyboard.press('p');p.wait_for_function('!menu.gamePaused')
    p.evaluate("PROGRESS.setLang('ru');PROGRESS.save();PROGRESS.flush()")
    p.reload();wait_for_boot(p);assert p.evaluate('I18N.language')=='ru';assert not errors,errors
    row={'engine':engine,'browser_version':b.version,'mode':mode,'viewport':[844,390],'dpr':2,'blur_freezes':True,'hidden_pauses':True,'visible_requires_resume':True,'reload_persistence':True,'resize_cycles':sizes,'audio':'N/A: silent game','physical_device':False,'errors':errors,'verdict':'PASS'}
    rows.append(row);print(json.dumps(row),flush=True);(out/'results.json').write_text(json.dumps(rows,indent=2));c.close()
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args();run(a.root,a.out)
