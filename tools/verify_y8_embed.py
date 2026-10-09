"""Offline embedding and SDK-failure checks; never opens a public game."""
import sys,json,pathlib,argparse,time
from contextlib import ExitStack
from browser_test_support import start_browser_test,EXTERNAL_URL
from verify_y8_release import SDK,FAKE

def run(root,out):
 out.mkdir(parents=True,exist_ok=True);rows=[]
 with ExitStack() as stack:
  url,b=start_browser_test(root,stack.callback)
  for case in ['portrait-frame','storage-denied','sdk-missing','sdk-hang','sdk-reject','sdk-ready-never']:
   c=b.new_context(viewport={'width':1000,'height':650},has_touch=True,is_mobile=True,device_scale_factor=2)
   if case!='sdk-missing':c.route(SDK,lambda r:r.fulfill(content_type='text/javascript',body=FAKE))
   config={'sdk-hang':{'initHang':True},'sdk-reject':{'initReject':True},'sdk-ready-never':{'readyNever':True}}.get(case,{})
   c.add_init_script('window.__y8Fake='+json.dumps(config))
   sandbox='allow-scripts' if case=='storage-denied' else 'allow-scripts allow-same-origin'
   c.route(url+'embed.html',lambda r:r.fulfill(content_type='text/html',body='<meta name="viewport" content="width=device-width,initial-scale=1"><iframe style="width:390px;height:550px;border:0" sandbox="'+sandbox+'" src="index.html"></iframe>'))
   p=c.new_page();p.set_default_timeout(10000);errors=[];p.on('pageerror',lambda e:errors.append(str(e)));t=time.monotonic();p.goto(url+'embed.html',wait_until='domcontentloaded');f=p.frames[1]
   f.wait_for_function('document.getElementById("loading") && document.getElementById("loading").hidden');menu_ms=round((time.monotonic()-t)*1000)
   assert menu_ms<5000,(case,menu_ms)
   def tap(expr):
    xy=f.evaluate('expr=>{const b=eval(expr);return canvasCoordsToViewportCoords({x:b.x+b.width/2,y:b.y+b.height/2})}',expr)
    bounds=p.locator('iframe').bounding_box();p.touchscreen.tap(bounds['x']+xy['x'],bounds['y']+xy['y'])
   tap('menu.badVersionButton.background');f.wait_for_function('!menu.visible');f.wait_for_function('!unTouch')
   xy=f.evaluate('canvasCoordsToViewportCoords({x:width*.7,y:height*.3})');bounds=p.locator('iframe').bounding_box();cd=c.new_cdp_session(p)
   cd.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':bounds['x']+xy['x'],'y':bounds['y']+xy['y']}]});assert f.evaluate('grapnel.throwed')
   cd.send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]});assert not f.evaluate('grapnel.throwed')
   f.evaluate("PROGRESS.setLang('ru');PROGRESS.save();PROGRESS.flush()");assert f.evaluate('PROGRESS.getLang()')=='ru'
   f.evaluate("window.dispatchEvent(new Event('blur'))");assert f.evaluate('menu.gamePaused')
   p.screenshot(path=str(out/(case+'.png')));assert not errors,errors
   row={'case':case,'menu_ms':menu_ms,'environment':f.evaluate('PLATFORM.environment'),'outer':[1000,650],'iframe':[390,550],'rotated':f.evaluate('isViewRotated()'),'errors':errors,'verdict':'PASS'};rows.append(row);print(row,flush=True);c.close()
   (out/'results.json').write_text(json.dumps(rows,indent=2))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--root',type=pathlib.Path,default=pathlib.Path.cwd());a.add_argument('--out',type=pathlib.Path,required=True);args=a.parse_args();run(args.root,args.out)
