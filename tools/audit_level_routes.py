"""Bounded whole-route production physics audit, using the shipped 540-unit profile.

Retains successful policies and every bypass. A failed search is inconclusive
about playability, never a pass. No velocities are injected after fixtures.
"""
import argparse
from contextlib import ExitStack
import itertools
import json
from pathlib import Path
from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
PROBE = '''o => {const r = ROUTE_PROBE.run({...o,level:importedMountainLevel(o.level)});
if(grappleOverAcquisitionRadius()!==540)throw new Error("Wrong production acquisition radius");
return {hit:r.hit,arrival:r.arrival,ticks:r.ticks,bounces:r.bounces,minY:r.minY};}'''


def audit(level, output, mode='shortcuts', sources=None, expanded=False, quick=False):
    elements = {e['id']: e for e in level['elements']}
    fs = level['svgFormat']['fragments']
    boxes = []
    for f in fs:
        pts = [(elements[e]['x']+p['x'], elements[e]['y']+p['y']) for e in f['elements'] for p in elements[e]['points']]
        boxes.append((min(x for x,y in pts), min(y for x,y in pts), max(x for x,y in pts), max(y for x,y in pts)))
    cases=[];excluded=[]
    with ExitStack() as stack:
        url,browser=start_browser_test(ROOT,stack.callback)
        page=browser.new_page(viewport={'width':1280,'height':720})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url);wait_for_boot_run(page)
        page.add_script_tag(path=str(ROOT/'tools/probe_level_routes.js'))
        for i,a in enumerate(fs[:-1]):
            if sources and a['id'] not in sources:continue
            for j,b in enumerate(fs[i+1:],i+1):
                if mode=='routes' and j!=i+1:continue
                if mode=='shortcuts' and j==i+1:continue
                ax,ay,ar,ab=boxes[i];bx,by,br,bb=boxes[j]
                # Test all later panels within a generous local envelope; report exclusions.
                if mode=='shortcuts' and (max(bx-ar,ax-br)>6000 or abs(by-ay)>14000):
                    excluded.append([a['id'],b['id']]);continue
                hits=[];trials=0
                policies = itertools.product((1,2,3,5,8),(.2,.5,.8),(-.15,.15,-.3,.3), (30,300)) if expanded else ((p,f,0,30) for p,f in itertools.product((0,1,2,3,5,8),(.05,.5,.95)))
                if quick: policies=((p,f,0,30) for p,f in ((5,.05),(5,.5),(8,.95)))
                for pumps,fraction,offset,drop in policies:
                    o=dict(source=a['id'],target=b['id'],pumps=pumps,fraction=fraction,aimOffset=offset,drop=drop,budget=2400 if expanded else 1800)
                    if expanded:o.update(aimOffset=0,lastAimOffset=offset)
                    r=page.evaluate(PROBE,dict(o,level=level));trials+=1
                    if r['hit']:
                        hits.append(dict(policy=o,**r))
                        if mode=='routes' and r['hit']['id']==b['id']+'-body0':break
                case=dict(source=a['id'],target=b['id'],trials=trials,hits=hits)
                cases.append(case)
                skips=[h for h in hits if int(h['hit']['id'].split('-')[0][1:])>i+1]
                print(a['id'],b['id'],'trials',trials,'hits',len(hits),'SKIPS',len(skips),flush=True)
                Path(output).write_text(json.dumps(dict(mode=mode,layoutId=level['layoutId'],cases=cases,errors=errors,
                    complete=False),separators=(',',':')))
    data=dict(mode=mode,layoutId=level['layoutId'],cases=cases,errors=errors,complete=True,
              excludedPairs=excluded,quick=quick,expanded=expanded,
              coverage='Local gravity-produced entry fixtures, real pointer events, production physics and acquisition radius 540. Each hit records its exact policy. Candidate envelope: horizontal box gap <=6000, top height difference <=14000. Quick mode is triage only. Finite policies, not a proof of global shortcut absence.')
    bypasses=[dict(source=c['source'],target=c['target'],**h) for c in cases for h in c['hits']
              if int(h['hit']['id'].split('-')[0][1:])>int(c['source'][1:])+1]
    missing=[c['source']+':'+c['target'] for c in cases
             if mode=='routes' and not any(h['hit']['id']==c['target']+'-body0' for h in c['hits'])]
    data.update(bypasses=bypasses,unreachedTransfers=missing,scopeSources=sources,
                passing=bool(cases) and not quick and not errors and not bypasses and not missing)
    Path(output).write_text(json.dumps(data,separators=(',',':')))
    print('AUDIT', 'PASS' if data['passing'] else 'NOT ACCEPTED', 'pairs',len(cases),
          'bypasses',len(bypasses),'unreached',missing,flush=True)
    return data

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--level',required=True);p.add_argument('--output',required=True)
    p.add_argument('--quick',action='store_true');p.add_argument('--expanded',action='store_true');p.add_argument('--mode',choices=('routes','shortcuts'),default='shortcuts');p.add_argument('--sources')
    a=p.parse_args();result=audit(json.loads(Path(a.level).read_text()),a.output,a.mode,a.sources and a.sources.split(','),a.expanded,a.quick)

    if not result['passing'] and not a.quick:raise SystemExit(1)
