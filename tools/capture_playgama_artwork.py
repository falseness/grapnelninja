"""Capture ten native Main gameplay frames with trusted input and provenance.

Run: python3 tools/capture_playgama_artwork.py --out artifacts/TASK-247
Only host SDK responses and seeded randomness are fixtures; gameplay, rendering,
requestAnimationFrame and browser input are unmodified.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageOps, ImageDraw
from browser_test_support import start_browser_test, wait_for_boot
import test_playgama2_bridge as support
from test_playgama2_ads import AD_FAKE

ROOT = Path(__file__).resolve().parents[1]
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def sources():
    return {p: digest(ROOT/p) for p in subprocess.check_output(['git','ls-files'],text=True).splitlines()
            if not p.startswith(('artifacts/','screenshots/')) and (ROOT/p).is_file()}
def capture(out):
    dest=out/'screenshots'; dest.mkdir(parents=True,exist_ok=True)
    report={'revision': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'source_hashes':sources(), 'viewport':{'width':1280,'height':720}, 'dpr':1,
            'limitations':['Local current Playgama application; SDK network-boundary fixture, not live portal.',
                            'Seed and timestamped trusted inputs recorded; realtime RAF scheduling is not bit-exact replay.'], 'screenshots':[]}
    with ExitStack() as stack:
        url,browser=start_browser_test(ROOT,stack.callback)
        report['browser']=browser.version
        for i in range(10):
            seed=24700+i
            ctx=browser.new_context(viewport=report['viewport'],device_scale_factor=1)
            ctx.add_init_script('''(() => {let s=SEED; Math.random=()=>((s=Math.imul(s,1664525)+1013904223>>>0)/4294967296);
                window.artInputs=[]; for (const name of ['mousedown','mouseup','mousemove','click'])
                addEventListener(name,e=>artInputs.push({name,x:e.clientX,y:e.clientY,ms:performance.now(),trusted:e.isTrusted}),true);})()'''.replace('SEED',str(seed)))
            ctx.route(support.SDK,lambda r:r.fulfill(content_type='application/javascript',body='const FAULT="normal",SAVED_LANGUAGE="en";'+support.FAKE+AD_FAKE))
            p=ctx.new_page(); errors=[]
            p.on('pageerror',lambda e:errors.append(str(e)))
            p.goto(url+'index.html'); wait_for_boot(p); p.wait_for_function('bootComplete && !unTouch')
            point=p.evaluate('''() => {const b=menu.badVersionButton.background,r=canvas.getBoundingClientRect();return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}}''')
            p.mouse.click(**point);p.wait_for_function('!menu.visible && !unTouch')
            if p.locator('#tutorial button').is_visible(): p.locator('#tutorial button').click()
            p.mouse.move(870+i*20,150+i*11);p.mouse.down()
            p.wait_for_timeout(500+i*110)
            state=p.evaluate('({mode:version,menu:menu.visible,paused:menu.gamePaused,score:scoreText.count[version],ninja:{x:ninja.x,y:ninja.y},grapple:grapnel.throwed,ms:performance.now()})')
            assert state['mode']=='bad' and not state['menu'] and not state['paused'],state
            path=dest/f'main-{i+1:02d}.png';p.screenshot(path=str(path))
            inputs=p.evaluate('artInputs');assert inputs and all(x['trusted'] for x in inputs)
            assert not errors,errors
            report['screenshots'].append({'path':str(path),'sha256':digest(path),'seed':seed,'state':state,'inputs':inputs,'errors':errors,'kind':'real browser gameplay, native unedited PNG'})
            ctx.close();print(f'PASS Main native screenshot {i+1:02d} seed={seed} trusted input; no page errors',flush=True)
    assert len({s['sha256'] for s in report['screenshots']})==10
    (dest/'capture.json').write_text(json.dumps(report,indent=2)+'\n')
    sheet=Image.new('RGB',(640*2,380*5),'#101018');draw=ImageDraw.Draw(sheet)
    for i,row in enumerate(report['screenshots']):
        with Image.open(row['path']) as im: sheet.paste(ImageOps.contain(im,(640,360)),((i%2)*640,(i//2)*380))
        draw.text(((i%2)*640+8,(i//2)*380+362),Path(row['path']).name,fill='white')
    sheet.save(dest/'contact-sheet.jpg')
    print('PASS ten distinct native Main screenshots; capture.json and contact-sheet.jpg written')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    capture(parser.parse_args().out)
