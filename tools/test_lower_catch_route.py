"""Verify the longer opening catches falls from the formerly empty left side.

Panels are selected semantically: the lower route runs up to the upward-turn
departure (lowerCatchExtension.firstUpDeparture), and the late route is everything
after the purple exit (purpleExtension.exit). LOWER_CATCH_EVIDENCE_DIR=DIR writes
DIR/fall-landings.json (nothing is written without it)."""
import json
import os
from contextlib import ExitStack
from pathlib import Path
import unittest
from browser_test_support import start_browser_test, wait_for_boot_run
import convert_extended_mountain_svg as conv

ROOT = Path(__file__).resolve().parent.parent
LEVELS = ROOT / 'artifacts/levels'


def routes(m):
    fs = m['fragments']; ids = [f['id'] for f in fs]
    lower = fs[:ids.index(m['lowerCatchExtension']['firstUpDeparture']) + 1]
    late = fs[ids.index(m['purpleExtension']['exit']) + 1:]
    return lower, late


class LowerCatchRouteTests(unittest.TestCase):
    def test_late_route_is_above_the_opening_extent(self):
        m = json.loads((LEVELS / 'extended-mountain-measurements.json').read_text())
        extension = m['lowerCatchExtension']
        ids = {f['id']: f['semanticId'] for f in m['fragments']}
        self.assertEqual([ids[i] for i in extension['fragments']], ['X%d' % n for n in range(1, 11)])
        self.assertGreater(extension['addedHorizontalSpan'], 40000)
        lower, late = routes(m)
        left = min(x for f in lower for b in conv.bodies(f) for x, _ in b)
        right = max(x for f in lower for b in conv.bodies(f) for x, _ in b)
        for f in late:
            xs = [x for b in conv.bodies(f) for x, _ in b]
            self.assertGreaterEqual(min(xs), left, f['id'])
            self.assertLessEqual(max(xs), right, f['id'])

    def test_falls_from_leftmost_late_panels_land_on_earlier_terrain(self):
        m = json.loads((LEVELS / 'extended-mountain-measurements.json').read_text())
        level = json.loads((LEVELS / 'extended-mountain.level.json').read_text())
        lower, late = routes(m)
        lower_ids = {f['id'] for f in lower}
        sem = {f['id']: f['semanticId'] for f in m['fragments']}
        # The three leftmost late panels by contact point (not frozen indices).
        sources = sorted(late, key=lambda f: conv.contact(f)[0])[:3]
        results = []
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            page = browser.new_page(); page.goto(url); wait_for_boot_run(page)
            page.add_script_tag(path=str(ROOT / 'tools/opening_combination_replay.js'))
            for f in sources:
                result = page.evaluate('''([level,id])=>{
                    const el=level.elements.find(e=>e.id===id+'-body0');
                    const top=Math.min(...el.points.map(p=>p.y))+el.y;
                    const bottom=Math.max(...el.points.map(p=>p.y))+el.y;
                    // Gravity-only fall from below the source panel, no input
                    // or position/velocity writes after this initial fixture.
                    const c=OPENING_REPLAY.start({level,fixture:{panel:id,fraction:.5,drop:top-bottom-100}});
                    const start={x:ninja.x,y:ninja.y};
                    for(let i=0;i<6000;i++){
                        const fresh=c.step();
                        const hit=fresh.find(k=>k.id!==id+'-body0');
                        if(hit)return {source:id,start,hit,maxStep:c.log.maxStep,ticks:c.tick,
                            recoveries:(c.log.recoveries||[]).length};
                        if(c.log.maxStep>200)return {source:id,recovered:true,ticks:c.tick};
                    }
                    return {source:id,timeout:true};
                }''', [level, f['id']])
                self.assertIn('hit', result, result)
                landed = result['hit']['id'].split('-')[0]
                self.assertIn(landed, lower_ids, result)
                self.assertLess(result['maxStep'], 200, result)
                self.assertEqual(result['recoveries'], 0, result)
                results.append(dict(result, semantic=f['semanticId'], landedSemantic=sem[landed]))
        self.assertEqual(len(results), 3)
        out = os.environ.get('LOWER_CATCH_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / 'fall-landings.json').write_text(json.dumps(dict(
                layoutId=level['layoutId'], lowerRoute=[f['id'] for f in lower], lateRoute=[f['id'] for f in late],
                selection='three leftmost late panels by contact x; late = after purpleExtension.exit',
                falls=results), indent=1) + '\n')


if __name__ == '__main__': unittest.main()
