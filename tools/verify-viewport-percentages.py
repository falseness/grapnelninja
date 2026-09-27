"""Viewport regression checks for percentage conversion (TASK-030).

Requires Python Playwright and a local HTTP server. Run from the repository root:
python3 tools/verify-viewport-percentages.py --url http://127.0.0.1:8030/
Evidence is written under artifacts/TASK-030; never stage that directory.
"""
import argparse
import hashlib
import json
from verification_support import assert_near
from verification_scenarios import scenario as gameplay, setup, motion, frames, expected
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops



def near(a, b, path='root'):
    assert_near(a, b, path, rel_tol=1e-12, abs_tol=1e-10, require_finite=False)

init='''window.testNow=1000;performance.now=()=>testNow;Date.now=()=>1000000;window.requestAnimationFrame=()=>1;let seed=1234;Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296};'''

scenario=r'''mode=>{
 startGame(mode);menu.visible=false;screen.x=0;screen.y=0;fpsCounter.enabled=true;fpsCounter.value=60;
 const W=width/scale[mode],H=height/scale[mode];
 ninja.x=W*.5;ninja.y=H*.5;ninja.speedX=1;ninja.speedY=1;
 ninja.track.pos=Array.from({length:30},(_,i)=>({x:W*(.25+i*.008),y:H*(.52+Math.sin(i/5)*.025)}));
 const triangle=new Triangle({x:W*.7,y:H*.5,radius:H*.08,yMin:0,yMax:H});
 for(let i=0;i<12;i++){triangle.y+=H*.005;triangle.track.addPos(triangle.getPoints(),true)}
 const tramp=new Trampoline({x:W*.4,y:H*.7,points:[{x:0,y:0},{x:W*.18,y:0},{x:W*.18,y:H*.05},{x:0,y:H*.05}]});
 const cube=new Rect({x:W*.15,y:H*.55,width:W*.07,height:H*.12});
 floors[1].elements=[triangle,tramp,cube];
 const real=ctx;let trace=[];
 const norm=v=>v instanceof HTMLCanvasElement?'canvas':v instanceof CanvasGradient?'gradient':v;
 const wrap=t=>new Proxy(t,{get(t,k){let v=t[k];return typeof v==='function'? (...a)=>{trace.push([k,...a.map(norm)]);return v.apply(t,a)}:v},set(t,k,v){trace.push(['set',k,norm(v)]);t[k]=v;return true}});
 ctx=wrap(real);visualEffects=new VisualEffects(ctx,canvas);visualEffects.lightmap.lightCtx=wrap(visualEffects.lightmap.lightCtx);
 const parts={};const capture=(name,fn)=>{trace=[];fn();parts[name]=trace.slice()};
 capture('menu',()=>menu.draw());
 capture('background',()=>visualEffects.background.draw());
 ctx.scale(scale[mode],scale[mode]);
 const state=visualEffects.getGameState();
 capture('lights',()=>drawLightsLayer(state));
 const ps=visualEffects.particles;
 ps.emitTrampolineSplash(ninja,tramp);ps.emitPlayerParticles(ninja);
 for(let i=0;i<10;i++)ps.emitWorldParticles([{elements:[triangle,cube]}]);
 const particles=JSON.parse(JSON.stringify(ps.particles));
 capture('particles',()=>{ps.drawBehindForeground();ps.draw()});
 capture('trails',()=>visualEffects.playerTrail.draw(state));
 capture('hud',()=>{scoreText.draw();scoreText.drawStageIndicator(W,getHudCenterY(H,mode),getHudFontSize(W,H,mode));fpsCounter.draw()});
 capture('screenEffects',()=>{visualEffects.screenEffects.triggerDeath(W*.5,H*.5);testNow+=60;visualEffects.screenEffects.begin();visualEffects.screenEffects.draw();visualEffects.screenEffects.end()});
 const shake={...visualEffects.screenEffects.shakeOffset};
 ctx.scale(1/scale[mode],1/scale[mode]);
 window.drawTestGame=()=>draw();drawTestGame();
 window.drawTestMenu=()=>menu.draw();window.drawTestPause=()=>menu.drawPauseScreen();
 const quality={};QUALITY.setLowPower(true);
 capture('lowPower',()=>{ps.update(state);ps.draw();visualEffects.playerTrail.draw(state);visualEffects.lightmap.draw(state);visualEffects.lightmap.composite(state);visualEffects.screenEffects.begin()});
 quality.low={...QUALITY,particles:ps.particles.length,backgroundTime:visualEffects.background.getAnimationTime(),shaking:visualEffects.screenEffects.isShaking};
 if(parts.lowPower.length||ps.particles.length||quality.low.backgroundTime||quality.low.shaking)throw Error('low power path executed');
 QUALITY.setLowPower(false);quality.restored={...QUALITY};
 const style=JSON.parse(JSON.stringify(STYLE));
 return {parts,particles,shake,quality,style,panel:menu.getPausePanel()};
}'''

def normalized_style(s):
 s=json.loads(json.dumps(s))
 s.pop('spriteGeometry',None)  # New names for previously inline sprite dimensions.
 if 'grapnelWidthHeightPercent' in s['strokes']:
  s['strokes']['grapnelWidthRatio']=s['strokes'].pop('grapnelWidthHeightPercent')/100
 for k in ['hudExtraShadowBlur','stageExtraShadowBlur','pauseMarginWidthPercent','pauseMarginHeightPercent']:s['ui'].pop(k,None)
 s['particles'].pop('playerMinSpeed',None)
 for group,old in [('particles','trampolineSplashDispersion'),('screenEffects','shakeMagnitude')]:
  if old+'X' in s[group]:s[group][old]=s[group].pop(old+'X');s[group].pop(old+'Y')
 return s


contact_scenario = 'mode=>{startGame(mode);cancelAnimationFrame(game);\n const t=new Trampoline({x:width*.4,y:height*.5,points:[{x:0,y:0},{x:width*.2,y:0},{x:width*.2,y:height*.05},{x:0,y:height*.05}]});\n floors=[{elements:[t]}];ninja.x=width*.5;ninja.y=t.y-ninja.radius*.5;ninja.speedX=0;ninja.speedY=height*.001;\n const contact=!!ninja.collision();const bounce=ninja.speedY<0;\n ninja.y=height*.3;grapnel.pos=[[ninja.x,height*.6,new Empty()]];grapnel.throwed=true;grapnel.grappled=false;grapnel.collision();\n return {contact,bounce,attached:grapnel.grappled};}'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8030/')
    parser.add_argument('--baseline', default='a6b41aa')
    parser.add_argument('--output', type=Path, default=Path('artifacts/TASK-030'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    files = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
    sources = {f: subprocess.check_output(['git', 'show', args.baseline+':'+f])
               for f in files if f.endswith(('.js', '.html'))}
    errors, results = [], {}

    def new_page(browser, w, h, baseline=False, live=False):
        page = browser.new_page(viewport={'width': w, 'height': h})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        if not live:
            page.add_init_script(init)
        if baseline:
            def route(r):
                name = urlparse(r.request.url).path.lstrip('/') or 'index.html'
                if name in sources:
                    r.fulfill(body=sources[name], content_type='text/javascript' if name.endswith('.js') else 'text/html')
                else:
                    r.continue_()
            page.route('**/*', route)
        page.goto(args.url)
        return page

    def check_geometry(old, new, w, h):
        sx, sy = w/1920, h/1080
        for a, b in zip(old, new):
            for key in ['type', 'fill', 'stroke']:
                near(a[key], b[key], key)
            near(a['x']*sx, b['x'], 'x')
            near(a['y']*sy, b['y'], 'y')
            for p, q in zip(a['points'], b['points']):
                near(p['y']*sy, q['y'], 'point.y')
                x = b['x']+(p['x']-a['x'])*sy if a['type']=='Triangle' else p['x']*sx
                # Rotated green templates store absolute points with a zero origin;
                # their anchor uses width, but both local shape axes use height.
                if a['type']=='Trampoline' and a['x']==0 and a['y']==0:
                    anchor = a['points'][0]['x']
                    x = anchor*sx+(p['x']-anchor)*sy
                near(x, q['x'], 'point.x')
            for key in ['width', 'height', 'side', 'radius', 'speedY']:
                if isinstance(a.get(key), (int, float)):
                    near(a[key]*(sx if key=='width' else sy), b[key], key)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--no-sandbox'])
            for revision, w, h in [('baseline',1920,1080), ('current',1920,1080),
                                   ('current',1280,720), ('current',1600,720)]:
                key = f'{revision}-{w}x{h}'
                row = results[key] = {'frames': {}, 'modes': {}}
                page = new_page(browser, w, h, revision=='baseline')
                for name, types in zip(frames, expected):
                    page.goto(args.url)
                    sample = page.evaluate(setup, name)
                    assert [e['type'] for e in sample['initial']] == types
                    sample['motion'] = page.evaluate(motion)
                    row['frames'][name] = sample
                    for stat in sample['motion']['stats']:
                        assert stat['maxY']>stat['minY'] and stat['turns']>0, stat
                        assert stat['overlaps']==0 and stat['boundViolations']==0, stat
                    if revision=='current':
                        original = results['baseline-1920x1080']['frames'][name]
                        if w==1920:
                            near(original, sample, name)
                        else:
                            check_geometry(original['raw'], sample['raw'], w, h)
                        print(f'PASS {key} {name}: expected object types/colors; geometry matches axes; 14400 motion substeps; overlaps=0 boundViolations=0', flush=True)
                for mode in ['classic','bad']:
                    page.goto(args.url)
                    values = page.evaluate(gameplay, mode)
                    page.goto(args.url)
                    contact = page.evaluate(contact_scenario, mode)
                    assert all(contact.values()), contact
                    row.setdefault('contacts', {})[mode] = contact
                    print(f'PASS {key} {mode}: collision detected, trampoline bounced, grapnel attached', flush=True)
                    page.goto(args.url)
                    effects = page.evaluate(scenario, mode)
                    for part in ['particles','trails','hud','screenEffects']:
                        assert len(effects['parts'][part])>5
                    row['modes'][mode] = {'gameplay': values, 'effects': effects}
                    for stage, fn in [('game','drawTestGame'),('menu','drawTestMenu'),('pause','drawTestPause')]:
                        page.evaluate(fn+'()')
                        page.screenshot(path=str(args.output/f'{key}-{mode}-{stage}.png'))
                    if revision=='current':
                        old = results['baseline-1920x1080']['modes'][mode]
                        if w==1920:
                            near(old['gameplay'], values, mode+'.gameplay')
                            for stage in ['game','menu','pause']:
                                a=Image.open(args.output/f'baseline-1920x1080-{mode}-{stage}.png')
                                b=Image.open(args.output/f'current-1920x1080-{mode}-{stage}.png')
                                assert not ImageChops.difference(a,b).getbbox(), (mode,stage)
                            print(f'PASS 1920x1080 {mode}: game/menu/pause screenshots pixel-identical to pre-conversion',flush=True)
                            for field in ['parts','particles','shake','quality','panel']:
                                near(old['effects'][field], effects[field], mode+'.'+field)
                            near(normalized_style(old['effects']['style']), normalized_style(effects['style']))
                            print(f'PASS 1920x1080 {mode}: pre-conversion physics and 240 substeps, HUD/effects draw traces, dimensions, particle states, menu/pause match', flush=True)
                        else:
                            original = old['gameplay']['values']
                            for field in ['gravity','throwSpeed','pullSpeed','triangleSpeed','ninjaCap','cameraTop','cameraBottom','cameraCenter','cornerTolerance','firstPointTolerance','coordinateTolerance']:
                                near(original[field]*h/1080, values['values'][field], field)
                            near(original['cameraX']*w/1920, values['values']['cameraX'], 'cameraX')
                            panel = effects['panel']
                            assert panel['x']>=0 and panel['y']>=0 and panel['x']+panel['width']<=w and panel['y']+panel['height']<=h, panel
                            print(f'PASS {w}x{h} {mode}: gameplay speeds/tolerances/camera scale by declared axes; HUD/effects rendered; pause panel within viewport', flush=True)
                page.close()
                if revision=='current' and w!=1920:
                    scaled = row['modes']['classic']['effects']['style']
                    # Tag each actual helper call so repeated property names and
                    # unconverted template ratios cannot be confused with pixels.
                    tagged_source = (
                        "function screenWidthPercent(p){return {axis:'Width',percent:p}};"
                        "function screenHeightPercent(p){return {axis:'Height',percent:p}};"
                        + Path('style.js').read_text()
                        + ";process.stdout.write(JSON.stringify(STYLE));")
                    tagged = json.loads(subprocess.check_output(['node','-e',tagged_source],text=True))
                    def check_dimensions(template, actual, path='STYLE'):
                        if isinstance(template,dict) and set(template)=={'axis','percent'}:
                            extent = w if template['axis']=='Width' else h
                            near(extent*template['percent']/100, actual, path)
                            return 1
                        if isinstance(template,dict):
                            return sum(check_dimensions(v,actual[k],path+'.'+k) for k,v in template.items())
                        if isinstance(template,list):
                            return sum(check_dimensions(v,actual[k],path+f'[{k}]') for k,v in enumerate(template))
                        near(template,actual,path)
                        return 0
                    count = check_dimensions(tagged,scaled)
                    assert count==80, count
                    print(f'PASS {w}x{h}: {count} STYLE dimension checks scale on declared width/height axes; all other STYLE values unchanged', flush=True)
            # Real animation loop and mouse controls at every requested viewport.
            for w,h in [(1920,1080),(1280,720),(1600,720)]:
                for mode in ['classic','bad']:
                    page = new_page(browser,w,h,live=True)
                    page.evaluate('''mode=>{
                      startGame(mode);menu.visible=false;
                      floors[1].elements=[];floors[1].creations=[{type:'frame9Elements',chance:100}];floors[1].generatePrimaryElements();
                      window.motion={};
                      for(const Type of [Ninja,Grapnel,Triangle,JumpingCube]) {
                        const move=Type.prototype.move,name=Type.name;motion[name]={calls:0,moved:0};
                        Type.prototype.move=function(){const before=JSON.stringify([this.x,this.y,this.pos]);const r=move.call(this);motion[name].calls++;if(before!==JSON.stringify([this.x,this.y,this.pos]))motion[name].moved++;return r;};
                      }
                    }''',mode)
                    page.mouse.move(w*.57,h*.28);page.mouse.down();page.wait_for_timeout(2000)
                    page.mouse.up();page.wait_for_timeout(3000)
                    sample=page.evaluate('motion')
                    for counts in sample.values(): assert counts['calls']>0 and counts['moved']>0, sample
                    results[f'live-{w}x{h}-{mode}']=sample
                    page.screenshot(path=str(args.output/f'live-{w}x{h}-{mode}.png'))
                    page.close()
                    print(f'PASS live {w}x{h} {mode}: 5 seconds mouse grapnel input; player/grapnel/triangle/cube moved {json.dumps(sample)}',flush=True)
            browser.close()
        assert not errors, errors
        print('PASS Step 1: 1920x1080 pre-conversion invariant',flush=True)
        print('PASS Step 2: 1280x720 proportional scaling',flush=True)
        print('PASS Step 3: 1600x720 aspect ratio geometry and safe bounds',flush=True)
        print('PASS Step 4: classic/bad real controls and generated motion at all three viewports',flush=True)
        print('PASS browser console/page errors=0',flush=True)
    finally:
        (args.output/'browser-errors.log').write_text('\n'.join(errors))
        results['baselineCommit']=subprocess.check_output(['git','rev-parse',args.baseline],text=True).strip()
        results['sourceCommit']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        results['sourceHashes']={f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in files if f.endswith(('.js','.html'))}
        results['harnessHash']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        (args.output/'run.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__ == '__main__':
    main()
