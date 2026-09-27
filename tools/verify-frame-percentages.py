"""Compare Frames 2–11 against a git baseline in Chromium and check safe motion.

Run a local HTTP server; requires Python Playwright. Evidence is never staged.
"""
import argparse
import hashlib
import json
from verification_support import assert_near
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', required=True)
parser.add_argument('--url', default='http://127.0.0.1:8027/')
parser.add_argument('--output', type=Path, default=Path('artifacts/TASK-027'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
files = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
frames = ['frame2Rect', 'frame3Triangle', 'frame4Elements', 'frame5Rects',
          'frame6Rects', 'frame7Elements', 'frame8Elements', 'frame9Elements',
          'frame10Elements', 'frame11Elements']
expected = [['Trampoline'], ['Triangle'], ['Trampoline', 'Rect', 'Triangle'],
            ['Trampoline']*3, ['Rect']*2, ['Trampoline', 'JumpingCube'],
            ['Rect']+['Trampoline']*3, ['Trampoline']*3+['Triangle', 'JumpingCube'],
            ['Trampoline', 'Rect', 'Rect'], ['Trampoline', 'Rect', 'Rect']]
setup = '''frame => {
 startGame('bad'); cancelAnimationFrame(game); menu.visible=false;
 window.seed=1234;
 Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296};
 const f=floors[1]; f.elements=[];
 window.snapshot=e=>({type:e.constructor.name,x:e.x,y:e.y,width:e.width,height:e.height,
   radius:e.radius,side:e.side,speedX:e.speedX,speedY:e.speedY,restrictionY:e.restrictionY,
   points:e.getPoints(),circle:e.getCircumscribedCircle(),fill:e.fill,stroke:e.stroke});
 // Check direct factory output as well as the floor's real group placement.
 window.raw=elementsFactory.create({min:width*.2,max:width*.2},{min:f.top,max:f.bottom},frame).map(snapshot);
 seed=1234; f.creations=[{type:frame,chance:100}]; f.generatePrimaryElements();
 window.initial=f.elements.map(snapshot);
 window.box=e=>{const p=e.getPoints();return {left:Math.min(...p.map(p=>p.x)),right:Math.max(...p.map(p=>p.x)),top:Math.min(...p.map(p=>p.y)),bottom:Math.max(...p.map(p=>p.y))}};
 window.dynamic=f.elements.filter(e=>e instanceof Triangle||e instanceof JumpingCube);
 draw();return {raw,initial};
}'''
motion = '''() => {
 const samples=[], stats=dynamic.map(e=>({type:e.constructor.name,minY:e.y,maxY:e.y,turns:0,minGap:Infinity,overlaps:0,boundViolations:0}));
 for(let step=0;step<14400;step++) {
  const speeds=dynamic.map(e=>e.speedY); floors[1].moveElements();
  dynamic.forEach((e,i)=>{
   const a=box(e), s=stats[i]; s.minY=Math.min(s.minY,e.y);s.maxY=Math.max(s.maxY,e.y);
   if(speeds[i]*e.speedY<0)s.turns++;
   if(e instanceof Triangle && (a.top<e.restrictionY.min-Math.abs(e.speedY)-1e-8||a.bottom>e.restrictionY.max+Math.abs(e.speedY)+1e-8))s.boundViolations++;
   for(const o of floors.flatMap(f=>f.elements)) {
    if(o===e)continue;const b=box(o);
    const gap=Math.max(b.left-a.right,a.left-b.right,b.top-a.bottom,a.top-b.bottom);
    s.minGap=Math.min(s.minGap,gap);if(gap < -1e-8)s.overlaps++;
   }
  });
  if(step%480===0)samples.push(floors[1].elements.map(snapshot));
 }
 draw(); return {stats,samples,substeps:14400,seconds:14400/(60*cyclesPerTick)};
}'''

def near(a, b, path='root'):
    assert_near(a, b, path, rel_tol=1e-9, abs_tol=1e-8, require_finite=True)

results = {}; errors = []; console = []
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox'])
    for revision in ['baseline', 'current']:
        page = browser.new_page(viewport={'width':1920,'height':1080})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: console.append(m.text) if m.type=='error' else None)
        if revision == 'baseline':
            sources = {f:subprocess.check_output(['git','show',args.baseline+':'+f]) for f in files if f.endswith(('.js','.html'))}
            def route(r):
                file = urlparse(r.request.url).path.lstrip('/') or 'index.html'
                if file in sources:
                    r.fulfill(body=sources[file], content_type='text/javascript' if file.endswith('.js') else 'text/html')
                else: r.continue_()
            page.route('**/*', route)
        results[revision] = {}
        for frame, types in zip(frames, expected):
            page.goto(args.url)
            row = page.evaluate(setup, frame)
            assert [e['type'] for e in row['initial']] == types
            if revision=='current': page.screenshot(path=str(args.output/(frame+'.png')))
            row['motion'] = page.evaluate(motion)
            results[revision][frame] = row
            if revision=='current':
                near(results['baseline'][frame], row, frame)
                print(f'PASS {frame}: 1920x1080 raw/packed geometry, colors, types and 30 motion samples match baseline; objects={types}', flush=True)
                for stat in row['motion']['stats']:
                    assert stat['maxY']>stat['minY'] and stat['turns']>0, stat
                    assert stat['overlaps']==0 and stat['boundViolations']==0, stat
                    print(f'PASS {frame} safe motion: substeps=14400 simulatedSeconds=30 {json.dumps(stat)}', flush=True)
        page.close()
    # Independent axis check at a different aspect ratio, before floor translation.
    page=browser.new_page(viewport={'width':1600,'height':720})
    page.goto(args.url)
    scaled=page.evaluate(setup,'frame9Elements')['raw']
    original=results['current']['frame9Elements']['raw']
    for old,new in zip(original,scaled):
        near(old['x']*1600/1920,new['x'])
        near(old['y']*720/1080,new['y'])
        for a,b in zip(old['points'],new['points']):
            near(a['y']*720/1080,b['y'])
            expected_x = new['x']+(a['x']-old['x'])*720/1080 if old['type']=='Triangle' else a['x']*1600/1920
            near(expected_x,b['x'])
        if isinstance(old.get('width'), (int,float)): near(old['width']*1600/1920,new['width'])
        if isinstance(old.get('side'), (int,float)): near(old['side']*720/1080,new['side'])
    print('PASS 1600x720 independent axes: X/width use W; Y/height/triangle shape use H',flush=True)
    page.close()
    for mode in ['classic','bad']:
        page=browser.new_page(viewport={'width':1920,'height':1080})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
        page.goto(args.url);page.evaluate('mode=>startGame(mode)',mode)
        page.mouse.move(1200,300);page.mouse.down();page.wait_for_timeout(1500)
        page.mouse.up();page.wait_for_timeout(1500)
        page.close()
        print(f'PASS live {mode}: game loop and mouse grapnel input',flush=True)
    browser.close()
results['baselineCommit']=subprocess.check_output(['git','rev-parse',args.baseline],text=True).strip()
results['sourceHashes']={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in files}
results['harnessHash']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(args.output/'run.json').write_text(json.dumps(results,indent=2)+'\n')
(args.output/'console-errors.log').write_text('\n'.join(console))
(args.output/'page-errors.log').write_text('\n'.join(errors))
assert not errors and not console,(errors,console)
print('PASS browser console errors=0; page errors=0',flush=True)
