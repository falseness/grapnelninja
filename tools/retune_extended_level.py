"""Retune a preserved concept measurement file; never modify the original."""
import argparse
import copy
import json
import math
from pathlib import Path
from check_level_geometry import union_distance
import convert_extended_mountain_svg as svg

TARGETS = {1: 80, 2: 80, 3: 150, 5: 150, 8: 150, 14: 150, 18: 150, 21: 150}
LAYOUT = 'extended-mountain-v2'


def gap(a, b):
    return union_distance(svg.bodies(a), svg.bodies(b))


def tune(source):
    m = copy.deepcopy(source)
    fs = m['fragments']
    for n in range(1, len(fs)):
        a, original = fs[n-1], source['fragments'][n]
        prev = source['fragments'][n-1]
        dx, dy = original['x']-prev['x'], original['y']-prev['y']
        angle = math.atan2(dy, dx)
        target = TARGETS.get(n, source['encounters'][n-1]['percent']) * 5.4
        angles = [angle]
        if n not in TARGETS:
            angles += [angle + math.radians(delta*sign) for delta in range(5, 86, 5) for sign in (1, -1)]
        for theta in angles:
            vx, vy = math.cos(theta), math.sin(theta)
            if dx*vx < -1e-6 or dy*vy < -1e-6:
                continue
            def at(t):
                return dict(original, x=a['x']+vx*t, y=a['y']+vy*t)
            lo, hi = 0., 20000.
            for _ in range(60):
                mid = (lo+hi)/2
                if gap(a, at(mid))[0] < target: lo = mid
                else: hi = mid
            candidate = at(hi)
            if all(gap(p, candidate)[0] > (0 if n <= 2 and i == n-1 else 561.6)
                   for i, p in enumerate(fs[:n])):
                fs[n] = candidate
                break
        else:
            raise ValueError('Cannot place P%d without a shortcut' % n)
    for row in m['encounters']:
        n = row['number']; a,b = fs[n-1:n+1]
        d,w,_,_ = gap(a,b)
        row.update(percent=TARGETS.get(n,row['percent']), distance=d, witness=w,
                   flight=[svg.contact(a),svg.contact(b)], baseline=False)
    m['pairChecks'] = []
    for i,a in enumerate(fs):
        for b in fs[i+1:]:
            d = gap(a,b)[0]
            m['pairChecks'].append(dict(source=a['id'],target=b['id'],minimumGap=d,passOutsideRange=d-21.6>540))
    placed_bands = []
    for band in m['yellowBands']:
        n = band['belowJump']; a,b=fs[n-1:n+1]
        x=(svg.contact(a)[0]+svg.contact(b)[0])/2-band['width']/2
        y=max(svg.contact(a)[1],svg.contact(b)[1])+900
        for step in range(200):
            by=y+step*120
            poly=[[x,by],[x+band['width'],by],[x+band['width'],by+band['height']],[x,by+band['height']]]
            nearest=min(union_distance([poly],svg.bodies(f))[0] for f in fs)
            if nearest>=540 and all(union_distance([poly],[other])[0]>=120 for other in placed_bands):break
        else: raise ValueError('Cannot place '+band['id'])
        placed_bands.append(poly)
        band.update(x=x,y=by,polygon=poly,nearestSolidClearance=nearest)
        band.pop('nominalRouteSampleCheck',None)
    m['fallIllustrations'] = [dict(id='F'+str(i+1),band=z['id'],start=[z['x']+z['width']/2,z['y']-500],
        end=[z['x']+z['width']/2,z['y']+1000],meaning='Illustrative fall only') for i,z in enumerate(m['yellowBands'])]
    m['layoutId']=LAYOUT
    m['allowedGrapplePairs']=[['P0','P1'],['P1','P2']]
    m['checks']={'geometryOnly':True}
    m['limitations']=['Jump playability remains unverified. Opening transfers intentionally allow direct grappling.']
    return m


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',required=True)
    ap.add_argument('--output-dir',required=True)
    args=ap.parse_args()
    dest=Path(args.output_dir); dest.mkdir(parents=True,exist_ok=True)
    m=tune(json.loads(Path(args.source).read_text()))
    svg.LAYOUT_ID=LAYOUT
    text=svg.build(m)
    text=text.replace('01–10: preserved baseline geometry', 'Opening 80% · vertical transfers 150%')
    text=text.replace('BASELINE PRESERVED', 'EASIER OPENING / SHORTER CLIMBS')
    text=text.replace('original 01–10 unchanged','opening gaps 80%; vertical gaps 150%')
    text=text.replace('Geometric checks exclude direct fragment-to-fragment grappling.', 'Opening transfers allow grappling; later transfers remain beyond grapple range.')
    text=text.replace('No nominal illustrated arc enters a band.', 'Fall-band paths require gameplay testing.')
    text=text.replace('All 300 fragment pairs > grapple + player diameter.', 'Opening pairs allow grappling; other pairs stay separated.')
    lines=text.splitlines(True)
    for i,line in enumerate(lines):
        if '<polygon id="P0-body' in line:
            lines[i]=line.replace('data-role="solid"','data-role="bounce"').replace('fill="#213d38" stroke="#8dc8b2"','fill="#294a34" stroke="#a3e184"')
    (dest/'extended-mountain.svg').write_text(''.join(lines))
    (dest/'extended-mountain-measurements.json').write_text(json.dumps(m,separators=(',',':'))+'\n')
    print('Wrote',dest,'layout',LAYOUT,'targets',TARGETS)

if __name__=='__main__':main()
