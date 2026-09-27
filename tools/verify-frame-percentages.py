"""Compare Frames 2–11 against a git baseline in Chromium and check safe motion.

Run a local HTTP server; requires Python Playwright. Evidence is never staged.
"""
import argparse
import hashlib
import json
from verification_support import assert_near, load_baseline_sources, baseline_route
from verification_scenarios import frames, expected, setup, motion
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', required=True)
parser.add_argument('--url', default='http://127.0.0.1:8027/')
parser.add_argument('--output', type=Path, default=Path('artifacts/TASK-027'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
files = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()

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
            sources = load_baseline_sources(args.baseline, files)
            page.route('**/*', baseline_route(sources))
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
