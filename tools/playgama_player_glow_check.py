"""Deterministic edge/allocation evidence for the isolated player-glow prototype."""
import argparse
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import platform
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from playgama_render_compare import FIXTURE, STATE, pixel_diff
from playgama_firefox_perf import SDK, QuietHandler, SEED_SCRIPT, SEED, write
from render_snapshot import CLOCK_SCRIPT, boot_frozen

SETUP = '''mode => {
 startGame(mode); for(let i=0;i<25;i++){__snap.tick++;__snap.now=__snap.tick*1000/60;gameLoop(__snap.now)}
 menu.visible=false;menu.gamePaused=false;continueOffer.visible=false;
 ninja.x=width/scale[version]*0.65-screen.x; ninja.y=height/scale[version]*0.5-screen.y;
 ninja.track.pos=Array.from({length:80},(_,i)=>({x:ninja.x-(79-i)*3/scale[version],y:ninja.y+Math.sin(i/10)*10/scale[version]}));
 visualEffects.particles.emitPlayerParticles(ninja);
 visualEffects.particles.pushParticle(ninja.x-30/scale[version],ninja.y,0,0,'#ffffff',1000,4/scale[version],1,true,false,true);
 draw();
}'''
PROBE='''() => ({geometry:visualEffects.playerGlow.prototypeGeometry || null,
 levels:visualEffects.playerGlow.levels.map(l=>[l.canvas.width,l.canvas.height]),
 blink:ninja.getBlinkAlpha(),sparks:visualEffects.particles.particles.filter(p=>p.spark).length,
 trail:ninja.track.pos.length,transform:Array.from(ctx.getTransform().toFloat64Array())})'''
STEPS=[('long-trail','draw()'),('left','ninja.x=-screen.x;draw()'),
 ('right','ninja.x=width/scale[version]-screen.x;draw()'),
 ('top','ninja.y=-screen.y;draw()'),('bottom','ninja.y=height/scale[version]-screen.y;draw()'),
 ('shake','visualEffects.screenEffects.triggerDeath(ninja.x,ninja.y);draw()'),
 ('blink','ninja.getBlinkAlpha=()=>0.25;draw()'),
 ('camera','screen.x-=30;screen.y+=20;draw()'),
 ('portrait','onViewportResize();draw()'),('landscape','onViewportResize();draw()'),
 ('resize','onViewportResize();draw()'),('repeat','draw()')]

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out
 images=out/'visuals/extended';images.mkdir(parents=True)
 records=[];errors=[];network=[];env={'os':platform.platform(),'browsers':{},'native_android':'UNVERIFIED'}
 with ExitStack() as stack:
  origins={}
  for arm in ('control','candidate'):
   server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str((out/arm).resolve())))
   stack.callback(server.server_close);Thread(target=server.serve_forever,daemon=True).start();stack.callback(server.shutdown)
   origins[arm]=f'http://127.0.0.1:{server.server_port}'
  def route(r):
   url=r.request.url;action='LOCAL' if any(url.startswith(o+'/') for o in origins.values()) else 'SDK_STUB' if url==SDK else 'BLOCKED'
   network.append({'url':url,'action':action})
   if action=='LOCAL':r.continue_()
   elif action=='SDK_STUB':r.fulfill(content_type='application/javascript',body=FIXTURE)
   else:r.abort()
  pw=stack.enter_context(sync_playwright())
  for engine in ('firefox','chromium'):
   browser=getattr(pw,engine).launch(headless=True)
   try:
    env['browsers'][engine]={'version':browser.version}
    for mode in ('classic','bad'):
     captures={}
     for arm in ('control','candidate'):
      context=browser.new_context(viewport={'width':844,'height':390},device_scale_factor=2,has_touch=True,service_workers='block')
      context.route('**/*',route)
      for js in (SEED_SCRIPT%SEED,CLOCK_SCRIPT):context.add_init_script(js)
      page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
      page.goto(origins[arm]+'/index.html');boot_frozen(page)
      env['browsers'][engine]['graphics']=page.evaluate('''() => {const g=document.createElement('canvas').getContext('webgl');if(!g)return {webgl:false};const d=g.getExtension('WEBGL_debug_renderer_info');return {vendor:g.getParameter(g.VENDOR),renderer:g.getParameter(g.RENDERER),unmasked:d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):null}}''')
      page.evaluate(SETUP,mode)
      for name,js in STEPS:
       if name in ('portrait','landscape','resize'):
        w,h=(390,844) if name=='portrait' else (900,410) if name=='resize' else (844,390)
        page.set_viewport_size({'width':w,'height':h})
       page.evaluate(js)
       key=f'{engine}-{mode}-{name}-{arm}'
       state=page.evaluate(STATE);probe=page.evaluate(PROBE)
       page.screenshot(path=str(images/(key+'.png')))
       write(images/(key+'.json'),{'state':state,'probe':probe})
       captures[name,arm]={'key':key,'state':state,'probe':probe}
      context.close()
     for name,_ in STEPS:
      c,d=[captures[name,arm] for arm in ('control','candidate')]
      assert c['state']==d['state'],(engine,mode,name,'state differs')
      diff=pixel_diff(images/(c['key']+'.png'),images/(d['key']+'.png'),images/(c['key']+'-diff.png'))
      records.append({'engine':engine,'mode':mode,'checkpoint':name,'control':c,'candidate':d,'pixels':diff})
      print(f'PASS {engine} {mode} {name} equal gameplay state; changed_pixels={diff["changed_pixels"]}',flush=True)
     # Review contact sheets contain every before/after/difference, labelled.
     sheet=Image.new('RGB',(900,len(STEPS)*165),'#333333');draw=ImageDraw.Draw(sheet)
     for row,(name,_) in enumerate(STEPS):
      c,d=[captures[name,arm]['key'] for arm in ('control','candidate')]
      for col,key in enumerate((c,d,c+'-diff')):
       im=Image.open(images/(key+'.png')).convert('RGB');im.thumbnail((298,140))
       sheet.paste(im,(col*300,row*165+20));draw.text((col*300,row*165),name+' '+('before','after','diff')[col],fill='white')
     sheet.save(images/f'{engine}-{mode}-review.png')
   finally:browser.close()
 write(out/'geometry.json',records);write(out/'environment.json',env);write(out/'network.json',network);write(out/'errors.json',errors)
 assert not errors,errors
 for engine in ('firefox','chromium'):
  for mode in ('classic','bad'):
   rs=[r for r in records if r['engine']==engine and r['mode']==mode]
   a,b=[r['candidate']['probe']['geometry'] for r in rs[-2:]]
   assert a==b,'repeated draw changes geometry or allocations'
 print('PASS Firefox/Chromium no exceptions; repeated frame stable surfaces; all modes and edges captured',flush=True)

if __name__=='__main__':main()
