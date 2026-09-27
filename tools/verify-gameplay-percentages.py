"""Compare gameplay against a pre-conversion git revision, then exercise Chromium.

Requires Python Playwright and a local HTTP server. Evidence stays in artifacts.
Usage: python3 tools/verify-gameplay-percentages.py --baseline REV
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', required=True)
parser.add_argument('--url', default='http://127.0.0.1:8026/')
parser.add_argument('--output', type=Path, default=Path('artifacts/TASK-026'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
files = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
errors = []
console = []
results = {}

scenario = '''mode => {
 startGame(mode); cancelAnimationFrame(game); menu.visible=false;
 // Reset randomness after startup so factory warm-up is identical.
 window.seed=1234;
 Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296};
 floors[1].elements=[];
 floors[1].creations=[{type:'frame9Elements',chance:100}];
 floors[1].generatePrimaryElements();
 const cube=floors[1].elements.find(e=>e instanceof JumpingCube);
 const triangle=floors[1].elements.find(e=>e instanceof Triangle);
 ninja.x=width*.2; ninja.y=height*.3; ninja.speedX=0; ninja.speedY=0;
 const values={gravity:GRAVITY,throwSpeed:grapnelSpeed,pullSpeed:grappleSpeed,
   triangleSpeed:Math.abs(triangle.speedY),cameraX:screen.borderX,
   cameraTop:screen.topBorderY,cameraBottom:screen.bottomBorderY,cameraCenter:screen.centerBorderY};
 // Exercise the actual player cap without obstacle interference.
 const savedFloors=floors; floors=[];
 ninja.speedY=height; ninja.move(); values.ninjaCap=ninja.speedY;
 ninja.speedY=0; floors=savedFloors;
 grapnel.pos=[[ninja.x,ninja.y,new Empty()]];grapnel.throwed=true;
 const direction=grapnel.calcSpeed({x:ninja.x+100,y:ninja.y-100});
 grapnel.speedX=direction.cos*grapnelSpeed;grapnel.speedY=direction.sin*grapnelSpeed;
 const trace=[];
 for(let i=0;i<240;i++) {
   ninja.speedY+=GRAVITY;ninja.move();triangle.move();cube.move();grapnel.move();
   trace.push([ninja.x,ninja.y,ninja.speedY,triangle.y,triangle.speedY,cube.x,cube.y,cube.speedY,grapnel.pos[0][0],grapnel.pos[0][1]]);
 }
 // Exercise attached grapnel pull in the real physics function.
 floors=[];grapnel.pos=[[ninja.x+100,ninja.y-100,new Empty()]];
 grapnel.grappled=true; ninja.speedX=0;ninja.speedY=0;
 calcPhysics();values.pulledSpeedX=ninja.speedX;values.pulledSpeedY=ninja.speedY;
 floors=savedFloors;
 const eps=typeof GAMEPLAY==='undefined'?1:screenHeightPercent(GAMEPLAY.coordinateToleranceHeightPercent);
 values.lineInside=pointIsOnStraight({x:0,y:eps*.9},{type:'line',k:0,b:0});
 values.lineOutside=pointIsOnStraight({x:0,y:eps*1.1},{type:'line',k:0,b:0});
 values.cornerTolerance=typeof GAMEPLAY==='undefined'?6:screenHeightPercent(GAMEPLAY.cornerToleranceHeightPercent);
 values.firstPointTolerance=typeof GAMEPLAY==='undefined'?50:screenHeightPercent(GAMEPLAY.firstPointToleranceHeightPercent);
 values.coordinateTolerance=eps;
 return {values,trace};
}'''

def near(a, b, path='root'):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for k in a: near(a[k], b[k], path+'.'+k)
    elif isinstance(a, list):
        assert len(a) == len(b)
        for i, (x, y) in enumerate(zip(a, b)): near(x, y, path+f'[{i}]')
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        assert math.isfinite(b) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), (path, a, b)
    else:
        assert a == b, (path, a, b)

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox'])
    for revision in ['baseline', 'current']:
        page = browser.new_page(viewport={'width':1920, 'height':1080})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: console.append(m.type+': '+m.text) if m.type=='error' else None)
        if revision == 'baseline':
            sources = {f:subprocess.check_output(['git','show',args.baseline+':'+f]) for f in files if f.endswith(('.js','.html'))}
            def route(r):
                file = urlparse(r.request.url).path.lstrip('/') or 'index.html'
                if file in sources:
                    r.fulfill(body=sources[file], content_type='text/javascript' if file.endswith('.js') else 'text/html')
                else: r.continue_()
            page.route('**/*', route)
        results[revision] = {}
        for mode in ['classic','bad']:
            page.goto(args.url)
            page.add_script_tag(content='window.seed=1234;')
            results[revision][mode] = page.evaluate(scenario, mode)
        page.close()
    near(results['baseline'], results['current'])
    for mode in ['classic','bad']:
        print(f'PASS 1920x1080 {mode}: original/current computed values and 240 movement substeps match (relative/absolute tolerance 1e-12)', flush=True)
        for name, value in results['current'][mode]['values'].items():
            print(f'PASS {mode} baseline {name}={value}', flush=True)
    # Non-baseline dimensions check axis selection and tolerances independently.
    page = browser.new_page(viewport={'width':1280,'height':720})
    page.goto(args.url)
    scaled = page.evaluate(scenario, 'bad')['values']
    for key in ['gravity','throwSpeed','pullSpeed','triangleSpeed','ninjaCap','cameraTop','cameraBottom','cameraCenter','cornerTolerance','firstPointTolerance','coordinateTolerance']:
        near(results['current']['bad']['values'][key]*720/1080, scaled[key], key)
    near(results['current']['bad']['values']['cameraX']*1280/1920, scaled['cameraX'])
    page.close()
    print('PASS 1280x720: width camera border and height movement/tolerances scale by their axes', flush=True)
    for mode in ['classic','bad']:
        page = browser.new_page(viewport={'width':1920,'height':1080})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: console.append(m.type+': '+m.text) if m.type=='error' else None)
        page.goto(args.url)
        page.evaluate('''mode=>{
          startGame(mode);menu.visible=false;
          floors[1].elements=[];floors[1].creations=[{type:'frame9Elements',chance:100}];floors[1].generatePrimaryElements();
          window.motion={};
          for(const Type of [Ninja,Grapnel,Triangle,JumpingCube]) {
            const move=Type.prototype.move;const name=Type.name;
            motion[name]={calls:0,moved:0};
            Type.prototype.move=function(){const before=JSON.stringify([this.x,this.y,this.pos]);const r=move.call(this);motion[name].calls++;if(before!==JSON.stringify([this.x,this.y,this.pos]))motion[name].moved++;return r;};
          }
        }''', mode)
        page.mouse.move(1100,300)
        page.mouse.down()
        page.wait_for_timeout(2000)
        page.mouse.up()
        page.wait_for_timeout(3000)
        sample = page.evaluate('motion')
        for name, counts in sample.items():
            assert counts['calls']>0 and counts['moved']>0, (mode,name,counts)
        page.screenshot(path=str(args.output/(mode+'.png')))
        results['live-'+mode] = sample
        print(f'PASS live {mode}: mouse grapnel input; player/grapnel/triangle/cube movement={json.dumps(sample)}', flush=True)
        page.close()
    browser.close()
(args.output/'console-errors.log').write_text('\n'.join(console))
(args.output/'page-errors.log').write_text('\n'.join(errors))
results['baselineCommit'] = subprocess.check_output(['git','rev-parse',args.baseline],text=True).strip()
results['sourceHashes'] = {f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in files}
results['harnessHash'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(args.output/'run.json').write_text(json.dumps(results,indent=2)+'\n')
assert not errors and not console, (errors,console)
print('PASS browser console errors=0; page errors=0', flush=True)
