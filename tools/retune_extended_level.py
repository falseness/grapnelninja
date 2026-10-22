"""Retune a preserved concept measurement file; never modify the original."""
import argparse
import copy
import json
import math
from pathlib import Path
from check_level_geometry import union_distance
import convert_extended_mountain_svg as svg

TARGETS = {1: 80, 2: 80, 3: 150, 5: 150, 8: 150, 14: 150, 18: 150, 21: 150}
LAYOUT = 'extended-mountain-v3'
DIRECTION_OFFSETS = {13: -25, 15: 30}
NONCONSECUTIVE_CLEARANCE = 1400


def gap(a, b):
    return union_distance(svg.bodies(a), svg.bodies(b))


def tune(source, reposition=True, guards=True):
    source = copy.deepcopy(source)
    # The extra second polygon is the unwanted rectangular bump, not the shelf.
    for n, fragment in enumerate(source['fragments']):
        if n < 10:
            assert len(fragment['polys']) == 2
            fragment['polys'] = fragment['polys'][:1]
        fragment['surfaceRole'] = 'bounce'
    m = copy.deepcopy(source)
    fs = m['fragments']
    for n in range(1, len(fs)):
        a, original = fs[n-1], source['fragments'][n]
        prev = source['fragments'][n-1]
        dx, dy = original['x']-prev['x'], original['y']-prev['y']
        angle = math.atan2(dy, dx) + math.radians(DIRECTION_OFFSETS.get(n, 0) if reposition else 0)
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
            # P6 used to sit directly over P3, skipping the leftward section.
            if reposition and n == 6:
                old = [p[0] for poly in svg.bodies(fs[3]) for p in poly]
                new = [p[0] for poly in svg.bodies(candidate) for p in poly]
                if max(min(new) - max(old), min(old) - max(new)) < 1000:
                    continue
            if reposition and n in (15, 19):
                if any(box(candidate)[1] < box(p)[1] and gap(p, candidate)[0] < NONCONSECUTIVE_CLEARANCE for p in fs[:n-1]):
                    continue
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
    if guards:
        add_shortcut_guards(m)
    m['fallIllustrations'] = [dict(id='F'+str(i+1),band=z['id'],start=[z['x']+z['width']/2,z['y']-500],
        end=[z['x']+z['width']/2,z['y']+1000],meaning='Illustrative fall only') for i,z in enumerate(m['yellowBands'])]
    m['layoutId']=LAYOUT
    m['allowedGrapplePairs']=[['P0','P1'],['P1','P2']]
    m['checks']={'geometryOnly':True}
    m['limitations']=['Jump playability remains unverified. Opening transfers intentionally allow direct grappling.']
    return m


def box(fragment):
    points=[p for poly in svg.bodies(fragment) for p in poly]
    return min(x for x,y in points), min(y for x,y in points), max(x for x,y in points), max(y for x,y in points)


def add_shortcut_guards(m):
    fs=m['fragments']; guards=[]
    candidates=[(0, None)]
    for i,a in enumerate(fs):
        ax,ay,ar,ab=box(a)
        for j in range(i+2,len(fs)):
            bx,by,br,bb=box(fs[j])
            if by < ay and max(0,bx-ar,ax-br)<540 and gap(a,fs[j])[0]<8000:
                candidates.append((i,j))
    for i,j in candidates:
        a=fs[i]; ax,ay,ar,ab=box(a)
        width=720 if i == 0 else max(920,ar-ax+200)
        x=(ax+ar-width)/2
        nxt=box(fs[i+1]) if i+1<len(fs) else None
        if nxt and nxt[1] < ay-.01:
            nc=(nxt[0]+nxt[2])/2; ac=(ax+ar)/2
            if nc > ac+200:
                width=min(x+width,nxt[0]-80)-x
            elif nc < ac-200:
                right=x+width; x=max(x,nxt[2]+80); width=right-x
        if width<400:continue
        # Cap the launch above a shelf; skip candidates whose intended next
        # platform occupies this corridor. Exact outcomes require physics probes.
        for height in ([600,400,240] if i == 0 else [800,600,400,240]):
            y=ay-90-height
            poly=[[x,y],[x+width,y],[x+width,y+height],[x,y+height]]
            nearest=min(union_distance([poly],svg.bodies(f))[0] for f in fs)
            if nearest<80 or width<=height: continue
            nxt=box(fs[i+1]) if i+1<len(fs) else None
            if nxt and nxt[1]<ay-.01 and not (nxt[0]>=x+width+30 or nxt[2]<=x-30):continue
            if any(union_distance([poly],[g['polygon']])[0]<30 for g in guards):continue
            guards.append(dict(id='G'+str(len(guards)+1),belowJump=i+1,source=a['id'],
                target=None if j is None else fs[j]['id'],purpose='upward shortcut brake',
                x=x,y=y,width=width,height=height,polygon=poly,nearestSolidClearance=nearest,
                minimumSolidClearance=80,role='non-solid, non-grappleable, pass-through braking'))
            break
    # Brake the high leftward arc from P3 that overshoots P4 into P5.
    # The lower leftward transfer stays beneath this horizontal zone.
    left = box(fs[4])[2] + 300
    right = box(fs[3])[0] - 300
    bottom = box(fs[4])[1] - 600
    height = 800
    poly = [[left,bottom-height],[right,bottom-height],[right,bottom],[left,bottom]]
    nearest = min(union_distance([poly],svg.bodies(f))[0] for f in fs)
    assert right-left > height and nearest >= 80
    guards.append(dict(id='G'+str(len(guards)+1),belowJump=4,source='P3',target='P5',
        purpose='high-arc bypass brake',x=left,y=bottom-height,width=right-left,height=height,
        polygon=poly,nearestSolidClearance=nearest,minimumSolidClearance=80,
        role='non-solid, non-grappleable, pass-through braking'))
    upper = copy.deepcopy(guards[-1])
    upper.update(id='G'+str(len(guards)+1),purpose='higher-arc bypass brake',y=bottom-1900)
    upper['polygon']=[[left,upper['y']],[right,upper['y']],
                      [right,upper['y']+height],[left,upper['y']+height]]
    upper['nearestSolidClearance']=min(union_distance([upper['polygon']],svg.bodies(f))[0] for f in fs)
    assert upper['nearestSolidClearance']>=80
    guards.append(upper)
    m['yellowBands']+=guards
    m['shortcutCandidates']=[{'from':fs[i]['id'],'to':None if j is None else fs[j]['id']} for i,j in candidates]


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
    (dest/'extended-mountain.svg').write_text(''.join(lines))
    (dest/'extended-mountain-measurements.json').write_text(json.dumps(m,separators=(',',':'))+'\n')
    print('Wrote',dest,'layout',LAYOUT,'targets',TARGETS)

if __name__=='__main__':main()
