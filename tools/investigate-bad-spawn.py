"""Capture bad-mode spawn placement with real mouse input for 30 seconds.

Requires Python Playwright and Chromium (python3 -m playwright install chromium).
Serve the repository with python3 -m http.server 8018, then run this script
from the repository root. Set BROWSER_CDP_URL to use an existing browser.
Use --output to select the evidence directory (default: artifacts/TASK-018).
The generation and restart wrappers only observe; gameplay is unchanged.
"""
import argparse,json,time,subprocess,os,base64,faulthandler,hashlib
faulthandler.dump_traceback_later(60, repeat=True)
from pathlib import Path
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', default='artifacts/TASK-018')
args=parser.parse_args()
out=Path(args.output)
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
 b=(p.chromium.connect_over_cdp(os.environ['BROWSER_CDP_URL'])
    if os.environ.get('BROWSER_CDP_URL') else p.chromium.launch(headless=True,args=['--no-sandbox']))
 page=b.new_page(viewport={'width':772,'height':630})
 console=[]; errors=[]
 page.on('console',lambda m: console.append({'type':m.type,'text':m.text}))
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:8018/')
 page.evaluate('''() => {
 window.probe={spawns:[],restarts:0};
 const restart=reStart; reStart=function(){probe.restarts++;return restart()};
 const generate=Floor.prototype.generateElements;
 Floor.prototype.generateElements=function(x,...args){
 const old=new Set(this.elements); const result=generate.call(this,x,...args);
 if(this.constructor===Floor && typeof ninja!=='undefined' && ninja){
 const added=this.elements.filter(e=>!old.has(e));
 probe.spawns.push({time:performance.now(),anchor:x,playerX:ninja.x,screenX:screen.x,
 objects:added.map(e=>({type:e.constructor.name,left:e.getLeftPointX(),right:e.getRightPointX(),group:e.generationGroupId}))});}
 return result;};
 startGame('bad'); probe.start=performance.now();
 }''')
 start=time.monotonic(); samples=[]
 for target in range(31):
  page.wait_for_timeout(max(0,(start+target-time.monotonic())*1000))
  if target%3==0:
   state=page.evaluate('''() => ({png:canvas.toDataURL('image/png'),elapsed:(performance.now()-probe.start)/1000,playerX:ninja.x,playerY:ninja.y,screenX:screen.x,speedX:ninja.speedX,restarts:probe.restarts,spawns:probe.spawns.length,objects:floors[1].elements.map(e=>({type:e.constructor.name,group:e.generationGroupId,left:e.getLeftPointX(),right:e.getRightPointX(),pixelLeft:(e.getLeftPointX()+screen.x)*scale.bad,pixelRight:(e.getRightPointX()+screen.x)*scale.bad})),playerPixelX:(ninja.x+screen.x)*scale.bad})''')
   state['target']=target; samples.append(state)
   print('Captured',target,round(state['elapsed'],2),flush=True)
   (out/f'current-{target:02d}.png').write_bytes(base64.b64decode(state.pop('png').split(',')[1]))
  if target<30:
   page.mouse.up(); page.mouse.move(700,85); page.mouse.down()
 result=page.evaluate('probe');result.update(samples=samples,console=console,errors=errors,wallSeconds=time.monotonic()-start,sourceCommit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),method='Unmodified gameplay with repeated mouse grapnel throws to (700,85), once per second; observation-only generation/restart wrappers.')
 result['sourceHashes']={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in subprocess.check_output(['git','ls-files'],text=True).splitlines() if name.endswith(('.js','.html','.py'))}
 (out/'run.json').write_text(json.dumps(result,indent=2))
 (out/'console.log').write_text('\n'.join(f"{m['type']}: {m['text']}" for m in console)+'\n')
 (out/'page-errors.log').write_text('\n'.join(errors))
 print(json.dumps({k:result[k] for k in ['wallSeconds','restarts','errors','samples']},indent=2))
 b.close()
