"""Search real input policies for a ceiling / slope / rebound combination.
No position or velocity writes follow the initial gravity fixture.
"""
import argparse,json,random
from contextlib import ExitStack
from pathlib import Path
from browser_test_support import start_browser_test,wait_for_boot_run
ROOT=Path(__file__).resolve().parent.parent

POLICY = r"""([level, ids, p]) => {
  const c = OPENING_REPLAY.start({level, fixture: {panel: ids.source, fraction: p.fraction, drop: p.fixtureDrop||30}});
  const box = id => { const pts = floors[0].byId.get(id + '-body0').getPoints();
    return {x0: Math.min(...pts.map(q => q.x)), x1: Math.max(...pts.map(q => q.x)), y0: Math.min(...pts.map(q => q.y)), y1: Math.max(...pts.map(q => q.y))}; };
  const P2 = box(ids.source), R1 = box(ids.R1), R2 = box(ids.R2), R3 = box(ids.R3); let rp = 0, hop = 0, hx = 0;
  const inputs = []; const press = (aim) => { inputs.push({tick: c.tick, type: 'down', aim}); c.press(aim); };
  const release = () => { inputs.push({tick: c.tick, type: 'up'}); c.release(); };
  let phase = p.prefix?'prefix':'pump', prefixIndex=0, bounces = 0, t0 = 0, seen = [];
  for (let i = 0; i < 4000; i++) {
    const s = c.state();
    while(p.prefix && prefixIndex<p.prefix.length && p.prefix[prefixIndex].tick===c.tick){const e=p.prefix[prefixIndex++];if(e.type==='down')press(e.aim);else if(e.type==='up')release();else {c.aim(e.aim);inputs.push(e);}}
    if (phase === 'pump') {
      if (bounces < p.pumps && !c.held && s.vy > 0 && c.tick > 0) press([Math.max(P2.x0 + 20, Math.min(P2.x1 - 20, s.x + p.px)), P2.y0]);
      if (bounces >= p.pumps) { phase = 'wait'; t0 = c.tick; }
    }
    if (phase === 'wait' && c.tick >= t0 + p.d1 && s.vy < 0 && s.y < R1.y1 + p.yb && Math.hypot(s.x - R1.x0 - p.a1, s.y - R1.y1) < p.r1) { press([R1.x0 + p.a1, R1.y1 - 2]); phase = 'catch'; }
    if (phase === 'swing' && c.tick >= t0 + p.d2 && !c.held) {
      hx = Math.max(R1.x0+2,Math.min(R1.x1-2,s.x+p.fallDir*p.ahead)); press([hx, R1.y1 - 2]); t0 = c.tick; phase = 'hold'; }
    if (phase === 'hold' && (c.tick >= t0 + p.h2 || p.fallDir*(s.x-hx)>=p.rq)) {
      release(); hop++; t0 = c.tick; phase = (hop >= p.hops || (p.fallDir>0?s.x>=R1.x1-p.endq:s.x<=R1.x0+p.endq)) ? 'fall' : 'swing'; }
    if (phase === 'rebound' && rp < p.np && !c.held && s.vy > 0) {
      const x = Math.max(R2.x0 + 20, Math.min(R2.x1 - 20, s.x + p.ppx));
      press([x, OPENING_REPLAY.topAt(floors[0].byId.get(ids.R2+'-body0'),(x-R2.x0)/(R2.x1-R2.x0)).y+2]); }
    if (phase === 'rebound' && rp >= p.np && p.h3 === 0) phase = 'free';
    if (phase === 'rebound' && rp >= p.np && c.tick >= t0 + p.d3 && !c.held) { press([R3.x0 + p.f3 * (R3.x1 - R3.x0), R3.y0]); t0 = c.tick; phase = 'pull'; }
    if (phase === 'pull' && (c.tick >= t0 + p.h3 || (grapnel.grappled && grapnel.pos.at(-1)?.[2]?.id===ids.R3+'-body0' && s.y<R3.y0-p.ry))) { release(); phase = 'free'; }
    const fresh = c.step();
    if(floors[0].climbStats.completed)return {inputs,contacts:seen.concat(fresh),stopped:null,completed:true,finishState:c.state(),ticks:c.tick,maxStep:c.log.maxStep};
    for (const k of fresh) {
      seen.push(k);
      if (phase === 'pump' && k.id === ids.source+'-body0') { bounces++; if (c.held) release(); }
      if ((phase === 'catch'||phase==='prefix') && k.id === ids.R1 + '-body0' && k.ny > 0) { release(); phase = 'swing'; t0 = c.tick; }
      if (phase === 'rebound' && k.id === ids.R2 + '-body0') { rp++; t0 = c.tick; if (c.held) release(); }
      if (phase === 'fall' && k.id === ids.R2 + '-body0') { phase = 'rebound'; t0 = c.tick; }
      if (k.id === ids.R3 + '-body0' && k.ny < 0) { if(c.held)release();return {inputs,contacts:seen,stopped:k,ticks:c.tick,maxStep:c.log.maxStep}; }
    }
    if (Math.abs(s.y - c.origin.y) > 6000) break;
  }
  if (c.held) release();
  return {inputs, contacts: seen, stopped: null, ticks: c.tick,maxStep:c.log.maxStep};
}"""

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--level',required=True);ap.add_argument('--source',type=int,required=True);ap.add_argument('--output',required=True);ap.add_argument('--samples',type=int,default=300);ap.add_argument('--seed-partials');ap.add_argument('--auto-prefix',action='store_true');ap.add_argument('--prefix-policy',type=json.loads);a=ap.parse_args()
    level=json.loads(Path(a.level).read_text());n=a.source
    ids=dict(source='P'+str(n),R1='P'+str(n+1),R2='P'+str(n+2),R3='P'+str(n+3))
    def bounds(pid):
        e=next(e for e in level['elements'] if e['id']==pid+'-body0');pts=[(e['x']+p['x'],e['y']+p['y']) for p in e['points']]
        return min(x for x,y in pts),min(y for x,y in pts),max(x for x,y in pts),max(y for x,y in pts)
    b0,b1,b2=bounds(ids['source']),bounds(ids['R1']),bounds(ids['R2']);fall=1 if b2[0]>b1[0] else -1
    launch=1 if b1[0]+b1[2]>b0[0]+b0[2] else -1
    rng=random.Random(1023+n);wins=[];outcomes={};partial=[]
    seeds=json.loads(Path(a.seed_partials).read_text())['partial'] if a.seed_partials else []
    with ExitStack() as stack:
        url,browser=start_browser_test(ROOT,stack.callback);page=browser.new_page(viewport={'width':1280,'height':720});page.goto(url);wait_for_boot_run(page);page.add_script_tag(path=str(ROOT/'tools/opening_combination_replay.js'))
        prefix=None;prefix_options=None
        if a.auto_prefix:
            probe=browser.new_page(viewport={'width':1280,'height':720});probe.goto(url);wait_for_boot_run(probe);probe.add_script_tag(path=str(ROOT/'tools/probe_level_routes.js'))
            import itertools
            for pumps,fraction,offset,surface in itertools.product((1,2,3,5,8),(.8,.5,.2),(-.15,.15,-.3,.3,0),('underside','nearest')):
                options=dict(level=level,source=ids['source'],target=ids['R1'],pumps=pumps,fraction=fraction,
                             lastAimOffset=offset,drop=30,budget=2400,recordInputs=True,targetSurface=surface)
                if a.prefix_policy:options.update(a.prefix_policy);fraction=options['fraction']
                r=probe.evaluate('o=>ROUTE_PROBE.run(o)',options)
                if r['hit'] and r['hit']['id']==ids['R1']+'-body0':
                    candidate_prefix=r['inputs'][:-1]
                    catch=page.evaluate('o=>OPENING_REPLAY.run(o)',dict(level=level,fixture=dict(panel=ids['source'],fraction=fraction,drop=options['drop']),inputs=candidate_prefix,budget=min(2400,r['ticks']+500),stopOn=dict(id=ids['R1'],ny='down')))
                    if not catch['stopped']:
                        t=r['ticks']+1
                        for delay in (30,60,120):
                            aim=[max(b1[0]+2,min(b1[2]-2,r['hit']['x'])),b1[3]-2]
                            variant=candidate_prefix+[dict(tick=t,type='up'),dict(tick=t+delay,type='down',aim=aim)]
                            catch=page.evaluate('o=>OPENING_REPLAY.run(o)',dict(level=level,fixture=dict(panel=ids['source'],fraction=fraction,drop=options['drop']),inputs=variant,budget=min(2400,t+delay+600),stopOn=dict(id=ids['R1'],ny='down')))
                            if catch['stopped'] and catch['maxStep']<200:
                                candidate_prefix=variant;break
                    if catch['stopped'] and catch['maxStep']<200:
                        prefix=candidate_prefix;prefix_options=options;break
                if a.prefix_policy:break
            probe.close()
            print('PREFIX',None if prefix_options is None else {k:v for k,v in prefix_options.items() if k!='level'},flush=True)
        for i in range(a.samples):
            p=dict(fraction=rng.choice([.2,.5,.8]),pumps=rng.choice([2,3,4,5]),px=launch*rng.choice([0,20,40,80,120]),d1=0,
                a1=(b1[2]-b1[0])*rng.choice([.1,.5,.9]),r1=540,yb=rng.choice([100,300,500]),
                fallDir=fall,d2=rng.choice([0,1,3]),ahead=rng.choice([250,350,450]),h2=rng.choice([30,60,90,120]),rq=rng.choice([-80,0,100]),hops=rng.choice([0,1,2,3,4]),endq=rng.choice([0,100,300]),
                np=rng.choice([0,0,0,1,2]),ppx=rng.choice([-80,-40,0,40,80]),drop=240,
                d3=rng.choice([0,10,40]),f3=rng.choice([.01,.1,.9,.99]),h3=rng.choice([120,240,480,1000]),ry=100,nq=0,qpx=0)
            if seeds:
                dynamic={k:p[k] for k in ('np','ppx','d3','f3','h3','ry')}
                p=dict(rng.choice(seeds)['params'],**dynamic)
            if prefix:p.update(prefix=prefix,fraction=prefix_options['fraction'],fixtureDrop=prefix_options['drop'])
            r=page.evaluate(POLICY,[level,ids,p]);seq=[]
            for c in r['contacts']:
                if c['id']==ids['source']+'-body0':continue
                if not seq or seq[-1]!=c['id']:seq.append(c['id'])
            label='>'.join(seq[:4]);outcomes[label]=outcomes.get(label,0)+1
            if ids['R2']+'-body0' in seq:partial.append(dict(params=p,**r))
            surfaces = [next((c for c in r['contacts'] if c['id']==ids[k]+'-body0' and (c['ny']>.9 if k=='R1' else c['ny']<(-.9 if k=='R2' else -.5))),None) for k in ('R1','R2','R3')]
            valid_surfaces = all(surfaces) and surfaces[0]['ny']>.9 and surfaces[1]['ny']<-.9 and surfaces[1]['vyIn']>0 and surfaces[2]['ny']<-.5 and surfaces[2]['vyIn']>=0 and surfaces[2]['y']<surfaces[1]['y'] and surfaces[0]['tick']<surfaces[1]['tick']<surfaces[2]['tick']
            if (n==27 and r.get('completed') and surfaces[0] and surfaces[1] and surfaces[0]['tick']<surfaces[1]['tick'] and surfaces[1]['vyIn']>0 and r['maxStep']<200 and seq[:2]==[ids[k]+'-body0' for k in ('R1','R2')]) or (r['stopped'] and valid_surfaces and r['maxStep']<200 and seq[:3]==[ids[k]+'-body0' for k in ('R1','R2','R3')]):
                wins.append(dict(params=p,**r));break
            if i%25==0: print(i,outcomes,flush=True)
    data=dict(source=ids['source'],layoutId=level['layoutId'],wins=wins,partial=partial,outcomes=outcomes,prefix=prefix,prefixOptions={k:v for k,v in prefix_options.items() if k!='level'} if prefix_options else None)
    Path(a.output).write_text(json.dumps(data,separators=(',',':')));print('WINS',len(wins),flush=True)
    if not wins:raise SystemExit(1)
if __name__=='__main__':main()
