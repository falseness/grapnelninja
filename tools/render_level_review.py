"""Render candidate collision geometry through the real game and SVG renderer."""
import argparse,base64,json,re
from contextlib import ExitStack
from pathlib import Path
from browser_test_support import start_browser_test,wait_for_boot_run
from test_imported_level_runtime import CAPTURE_SETUP
ROOT=Path(__file__).resolve().parent.parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--directory',required=True);ap.add_argument('--output',required=True)
    a=ap.parse_args();src=Path(a.directory);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    level_path=src/'level.json';measure_path=src/'measurements.json'
    if not level_path.exists():level_path=src/'extended-mountain.level.json'
    if not measure_path.exists():measure_path=src/'extended-mountain-measurements.json'
    level=json.loads(level_path.read_text());m=json.loads(measure_path.read_text())
    svg=(src/'extended-mountain.svg').read_text()
    with ExitStack() as stack:
        url,browser=start_browser_test(ROOT,stack.callback)
        page=browser.new_page(viewport={'width':1280,'height':720})
        page.goto(url);wait_for_boot_run(page);page.evaluate('window.reviewEffects=visualEffects');page.add_script_tag(path=str(ROOT/'tools/opening_combination_replay.js'))
        page.evaluate('level=>OPENING_REPLAY.start({level,fixture:{panel:"P0",fraction:.5,drop:30}})',level)
        page.evaluate('visualEffects=window.reviewEffects');page.evaluate(CAPTURE_SETUP)
        concept=browser.new_page(viewport={'width':1280,'height':720})
        for name,frags in [('opening',m['fragments'][:11]),('full-route',m['fragments'])]:
            pts=[(f['x']+x,f['y']+y) for f in frags for poly in f['polys'] for x,y in poly]
            if name=='full-route':pts += [p for z in m['yellowBands'] for p in z['polygon']]
            left,top=min(x for x,y in pts)-300,min(y for x,y in pts)-300
            right,bottom=max(x for x,y in pts)+300,max(y for x,y in pts)+300
            k=min(1280/(right-left),720/(bottom-top))
            left-=(1280/k-(right-left))/2
            data=page.evaluate('a=>TASK651_CAPTURE(...a)',[left,top,k,True])
            (out/(name+'-game.png')).write_bytes(base64.b64decode(data.split(',')[1]))
            # Collision geometry and the root SVG viewBox both use world units.
            # Annotation groups already transform their canvas coordinates.
            box=[left,top,1280/k,720/k]
            crop=re.sub(r'<svg[^>]*?>',lambda z:re.sub(r' (width|height|viewBox)="[^"]*"','',z.group(0))[:-1]+
                        ' width="1280" height="720" viewBox="'+ ' '.join(map(str,box))+'" preserveAspectRatio="none">',svg,count=1)
            concept.set_content('<body style="margin:0;background:#101326">'+crop+'</body>')
            concept.screenshot(path=str(out/(name+'-svg.png')))
            (out/(name+'-view.json')).write_text(json.dumps(dict(left=left,top=top,pixelsPerUnit=k)))
    print(out.resolve())

if __name__=='__main__':main()
