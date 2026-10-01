"""Compare gameplay against a pre-conversion git revision, then exercise Chromium.

Requires Python Playwright and a local HTTP server. Evidence stays in artifacts.
Usage: python3 tools/verify-gameplay-percentages.py --baseline REV
"""
import argparse
import hashlib
import json
from verification_support import assert_near, load_baseline_sources, baseline_route
from verification_scenarios import scenario
from pathlib import Path
import subprocess
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


def near(a, b, path='root'):
    assert_near(a, b, path, rel_tol=1e-12, abs_tol=1e-12, require_finite=True)

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox'])
    for revision in ['baseline', 'current']:
        page = browser.new_page(viewport={'width':1920, 'height':1080})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: console.append(m.type+': '+m.text) if m.type=='error' else None)
        if revision == 'baseline':
            sources = load_baseline_sources(args.baseline, files)
            page.route('**/*', baseline_route(sources))
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
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: console.append(m.type+': '+m.text) if m.type=='error' else None)
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
          floors[1].elements=[];floors[1].creations=[{type:'frame13Elements',chance:100}];floors[1].generatePrimaryElements();
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
