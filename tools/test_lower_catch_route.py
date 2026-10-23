"""Verify the longer opening catches falls from the formerly empty left side."""
import json
from contextlib import ExitStack
from pathlib import Path
import unittest
from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent


class LowerCatchRouteTests(unittest.TestCase):
    def test_late_route_is_above_the_opening_extent(self):
        m=json.loads((ROOT/'artifacts/levels/extended-mountain-measurements.json').read_text())
        fs=m['fragments']; extension=m['lowerCatchExtension']
        self.assertEqual(len(extension['fragments']),8)
        self.assertGreater(extension['addedHorizontalSpan'],40000)
        lower=fs[:15]
        left=min(f['x'] for f in lower);right=max(f['x']+f['width'] for f in lower)
        for f in fs[-15:]:
            self.assertGreaterEqual(f['x'],left,f['id'])
            self.assertLessEqual(f['x']+f['width'],right,f['id'])

    def test_falls_from_leftmost_late_panels_land_on_earlier_terrain(self):
        level=json.loads((ROOT/'artifacts/levels/extended-mountain.level.json').read_text())
        results=[]
        with ExitStack() as stack:
            url,browser=start_browser_test(ROOT,stack.callback)
            page=browser.new_page();page.goto(url);wait_for_boot_run(page)
            page.add_script_tag(path=str(ROOT/'tools/opening_combination_replay.js'))
            for source in (36,37,38):
                result=page.evaluate('''([level,n])=>{
                    const el=level.elements.find(e=>e.id==='P'+n+'-body0');
                    const top=Math.min(...el.points.map(p=>p.y))+el.y;
                    const bottom=Math.max(...el.points.map(p=>p.y))+el.y;
                    // Gravity-only fall from below the source panel, no input
                    // or position/velocity writes after this initial fixture.
                    const c=OPENING_REPLAY.start({level,fixture:{panel:'P'+n,fraction:.5,drop:top-bottom-100}});
                    for(let i=0;i<6000;i++){
                        const fresh=c.step();
                        const hit=fresh.find(k=>Number(k.id.split('-')[0].slice(1))<n);
                        if(hit)return {source:n,hit,maxStep:c.log.maxStep,ticks:c.tick};
                        if(c.log.maxStep>200)return {source:n,recovered:true,ticks:c.tick};
                    }
                    return {source:n,timeout:true};
                }''',[level,source])
                self.assertIn('hit',result,result)
                self.assertLess(int(result['hit']['id'].split('-')[0][1:]),15,result)
                self.assertLess(result['maxStep'],200,result)
                results.append(result)
        out=ROOT/'artifacts/levels/harder-right/fall-landings.json'
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':unittest.main()
