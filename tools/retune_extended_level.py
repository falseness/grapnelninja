"""Retune a preserved concept measurement file; never modify the original."""
import argparse
import hashlib
import copy
import json
import math
from pathlib import Path
from check_level_geometry import MIN_INTERIOR_ANGLE, interior_angles, point_segment, self_intersections, union_distance
import convert_extended_mountain_svg as svg

TARGETS = {1: 80, 2: 80, 3: 150, 5: 150, 8: 150, 14: 150, 18: 150, 21: 150}
LAYOUT = 'extended-mountain-v5'
EXTENDED_LAYOUT = 'extended-mountain-v8'
# Rightward span is a minimum; usable surfaces and measured release gaps take
# priority over fitting a fixed endpoint. Leftward span retains its 3x target.
MIN_OPENING_SPAN = 720.0
# After the two easy transfers the rightward run is one mixed combination:
# ceiling underside catch, descent onto a sloped bounce face, rebound up, then
# a mostly horizontal transfer to the upward-turn departure. lift is the rise
# of the new contact over the previous one (negative descends); gap is the
# complete-polygon release gap reached by sliding the panel rightward.
OPENING = dict(factor=3,
               right=[dict(kind='ceiling', width=960, height=240, lift=450, gap=700, share=.34,
                           surface='underside', direction='UP-RIGHT → CEILING HOLD'),
                      dict(kind='bounce', width=900, height=520, lift=-650, gap=650, share=.22,
                           surface='slope', direction='RELEASE → DOWN-RIGHT ONTO SLOPE'),
                      dict(kind='platform', width=800, height=180, lift=450, gap=700, share=.22,
                           surface='top', direction='BOUNCE → UP-RIGHT'),
                      dict(kind='platform', width=1000, height=260, lift=150, gap=810, share=.22,
                           surface='top', direction='RIGHT → UPWARD-TURN DEPARTURE')],
               left=[dict(width=900, height=240, drop=0),
                     dict(width=1100, height=260, share=.52, drop=-160)])
GUIDELINES = Path(__file__).resolve().parent.parent / 'artifacts/levels/level-guidelines.md'
# Yellow-to-green clearance: 300% R in the current guidelines. The frozen v5
# layout (--opening original) was generated under the earlier 200% R rule.
YELLOW_CLEARANCE = 1620
LEGACY_YELLOW_CLEARANCE = 1080
YELLOW_PAIR_CLEARANCE = 540
DIRECTION_OFFSETS = {13: -25, 15: 30}
NONCONSECUTIVE_CLEARANCE = 1400
# A truncated tip leaves a flat face about this wide; each cut stays within this
# fraction of either adjacent edge so neighbouring corners keep their angles.
BLUNT_FACE = 40.0
BLUNT_EDGE_FRACTION = 0.4


def blunt_polygon(poly, minimum=MIN_INTERIOR_ANGLE):
    """Truncate every corner sharper than minimum with a symmetric cut.

    The tip vertex becomes two vertices on its adjacent edges; each new corner is
    (180 + tip) / 2 >= 90 degrees, so a single pass suffices. Other vertices are
    untouched, which makes the output a deterministic function of the input.
    """
    poly = [list(p) for p in poly]
    angles = interior_angles(poly)
    out = []
    for i, (p, angle) in enumerate(zip(poly, angles)):
        if angle >= minimum:
            out.append(p)
            continue
        prev, nxt = poly[i-1], poly[(i+1) % len(poly)]
        a, b = math.dist(p, prev), math.dist(p, nxt)
        d = min(BLUNT_FACE / (2*math.sin(math.radians(angle)/2)), BLUNT_EDGE_FRACTION*min(a, b))
        out.append([p[0]+(prev[0]-p[0])*d/a, p[1]+(prev[1]-p[1])*d/a])
        out.append([p[0]+(nxt[0]-p[0])*d/b, p[1]+(nxt[1]-p[1])*d/b])
    if min(interior_angles(out)) < minimum or self_intersections(out):
        raise ValueError('Blunting did not produce a simple polygon with %g-degree corners' % minimum)
    return out


def blunt_fragments(source):
    """Blunt every collision polygon in place; returns the changed tips."""
    changed = []
    for fragment in source['fragments']:
        for k, poly in enumerate(fragment['polys']):
            blunt = blunt_polygon(poly)
            if blunt != [list(p) for p in poly]:
                changed.append(dict(fragment=fragment['id'], polygon=k, before=poly, after=blunt))
                fragment['polys'][k] = blunt
    return changed


def gap(a, b):
    return union_distance(svg.bodies(a), svg.bodies(b))


def opening_sections(points):
    """Split the route start into rightward, upward and leftward runs.

    points are contact points in route order; returns (right_end, left_start,
    left_end) fragment indices: rightward 0..right_end, upward right_end ->
    left_start, leftward left_start..left_end. Runs follow horizontal direction
    between consecutive contacts, so a section is measured between its own
    departure and arrival contacts.
    """
    def kind(i):
        dx = points[i+1][0]-points[i][0]; dy = points[i+1][1]-points[i][1]
        return 'up' if abs(dy) > abs(dx) and dy < 0 else 'right' if dx > 0 else 'left'
    i = 0
    while kind(i) == 'right':
        i += 1
    if i == 0 or kind(i) != 'up':
        raise ValueError('Route does not open rightward then upward')
    left = i+1
    j = left
    while j+1 < len(points) and kind(j) == 'left':
        j += 1
    if j == left:
        raise ValueError('Route does not turn leftward after the first upward transfer')
    return i, left, j


def section_spans(points):
    right_end, left_start, left_end = opening_sections(points)
    return dict(rightward=points[right_end][0]-points[0][0],
                leftward=points[left_start][0]-points[left_end][0],
                sections=dict(rightward=[0, right_end], upward=[right_end, left_start], leftward=[left_start, left_end]))


def panel(name, width, height, x, y, kind='platform'):
    """A new green panel; svg.contact() gives its contact for each kind.

    platform: trapezoid, contact above the top-edge centre. ceiling: slab with
    a raised top (the concept's ceiling profile), contact below the underside
    centre. bounce: the concept's sloped face falling 240 units to the right,
    contact above the slope midpoint.
    """
    inset = round(width*.12, 3)
    polys = {'platform': [[0, 0], [width, 0], [width-inset, height], [inset, height]],
             'ceiling': [[0, 0], [width*.2, -90], [width*.8, -90], [width, 0], [width, height], [0, height]],
             'bounce': [[0, 0], [width, 240], [width, height], [0, height-240]]}[kind]
    # The concept's face falling to the right redirects up-right (bounceSign 1).
    return dict(id=None, name=name, x=x, y=y, width=width, height=height, kind=kind,
                bounceSign=1 if kind == 'bounce' else 0,
                surfaceRole='bounce', polys=[polys])


SURFACE_SIDE = {'platform': 1, 'bounce': 1, 'summit': 1, 'ceiling': -1}


def contact_surface(fragment):
    """The intended collision edge under (or over) svg.contact() and the point on it.

    Returns (edge, point): the polygon edge in world coordinates and the point
    PLAYER_RADIUS from the contact towards the surface. Raises if no edge
    carries that point, so a mislabelled kind cannot pass silently.
    """
    cx, cy = svg.contact(fragment)
    point = (cx, cy + SURFACE_SIDE[fragment['kind']]*svg.PLAYER_RADIUS)
    for poly in svg.bodies(fragment):
        for a, b in zip(poly, poly[1:]+poly[:1]):
            if point_segment(point, a, b)[0] <= 1e-6:
                return (list(a), list(b)), point
    raise ValueError('%s: contact is not on a %s surface' % (fragment['id'], fragment['kind']))


def usable_span(fragment):
    """Horizontal projection of the intended continuous contact edge."""
    (a, b), _ = contact_surface(fragment)
    return abs(b[0]-a[0])


def moved(fragment, dx, dy):
    return dict(fragment, x=fragment['x']+dx, y=fragment['y']+dy)


def place_along(anchor, fragment, ux, uy, target, origin=None):
    """Translate fragment from origin (anchor's origin by default) along (ux, uy) until its gap to anchor is target."""
    ox, oy = origin or (anchor['x'], anchor['y'])
    lo, hi = 0., 30000.
    for _ in range(80):
        mid = (lo+hi)/2
        if gap(anchor, dict(fragment, x=ox+ux*mid, y=oy+uy*mid))[0] < target: lo = mid
        else: hi = mid
    return dict(fragment, x=ox+ux*hi, y=oy+uy*hi)


def extend_opening(fs, rows, spec):
    """Lengthen the first rightward and leftward runs by spec['factor'].

    The first rightward transfers keep their fragments; new panels follow them
    before the upward turn, which keeps its original direction and gap target
    from the last new panel. The leftward departure keeps its original gap
    target to the first new leftward panel. The arrival and all later terrain
    are translated rigidly, so their mutual gaps are unchanged. Returns
    fragments renumbered in route order (originalId/semanticId kept), rows
    renumbered with originalNumber/originalId, and an original-to-new route map.
    """
    factor = spec['factor']
    right_end, up_to, left_end = opening_sections([svg.contact(f) for f in fs])
    if left_end != up_to+1:
        raise ValueError('Expected a single original leftward transfer')
    by_pair = {(r['fromFragment'], r['toFragment']): r for r in rows}
    up_row = by_pair[(fs[right_end]['id'], fs[up_to]['id'])]
    left_row = by_pair[(fs[up_to]['id'], fs[left_end]['id'])]
    cx = lambda f: svg.contact(f)[0]
    span_r, span_l = cx(fs[right_end])-cx(fs[0]), cx(fs[up_to])-cx(fs[left_end])
    # Each panel rises (or descends) by lift between contacts, then slides
    # rightward until its complete-polygon gap to the previous panel is gap.
    added, prev = [], fs[right_end]
    total = sum(p['share'] for p in spec['right'])
    for k, p in enumerate(spec['right'], 1):
        shape = panel('Rightward %s %d' % (p['kind'], k), p['width'], p['height'], 0, 0, p['kind'])
        if usable_span(dict(shape, id='R%d' % k)) < MIN_OPENING_SPAN:
            raise ValueError('Opening landing surface must span at least 720 units')
        desired_x = cx(prev)+(factor-1)*span_r*p['share']/total
        y = svg.contact(prev)[1]-p['lift']-(svg.contact(shape)[1]-shape['y'])
        candidate = place_along(prev, shape, 1, 0, p['gap'], origin=(prev['x'], y))
        x = max(desired_x, cx(candidate))
        prev = dict(candidate, x=x-p['width']/2, semanticId='R%d' % k, surface=p['surface'],
                    openingDirection=p['direction'])
        added.append(prev)
    # Upward: the original turn direction and gap target, now from the last new panel.
    dx, dy = fs[up_to]['x']-fs[right_end]['x'], fs[up_to]['y']-fs[right_end]['y']
    norm = math.hypot(dx, dy)
    turn = place_along(prev, fs[up_to], dx/norm, dy/norm, TARGETS.get(up_row['number'], up_row['percent'])*5.4)
    # Leftward: the original departure gap to the first new panel, then shares of the rest.
    p = spec['left'][0]
    ledge = dict(panel('Leftward ledge 1', p['width'], p['height'], 0, 0), semanticId='L1')
    ledge = place_along(turn, ledge, -1, 0, left_row['percent']*5.4,
                        origin=(turn['x']-p['width'], turn['y']+p['drop']))
    left = [ledge]
    arrival_x = cx(turn)-factor*span_l
    rest = cx(ledge)-arrival_x
    for k, p in enumerate(spec['left'][1:], 2):
        x = cx(left[-1])-rest*p['share']
        left.append(dict(panel('Leftward ledge %d' % k, p['width'], p['height'], x-p['width']/2, turn['y']+p['drop']),
                         semanticId='L%d' % k))
    arrival = fs[left_end]
    shift = (arrival_x-cx(arrival), turn['y']-fs[up_to]['y'])
    route = fs[:right_end+1]+added+[turn]+left+[moved(f, *shift) for f in fs[left_end:]]
    # Renumber in route order; map every original fragment and encounter to its successor.
    out, fragment_ids = [], {}
    for n, f in enumerate(route):
        original = None if 'semanticId' in f else f['id']
        f = dict(f, id='P%d' % n, originalId=original, semanticId=f.get('semanticId', original))
        if original:
            fragment_ids[original] = f['id']
        out.append(f)
    out_rows, numbers, ids = [], {}, {}
    for n in range(1, len(out)):
        a, b = out[n-1], out[n]
        old = by_pair.get((a['originalId'], b['originalId']))
        if old is None and b['originalId'] == fs[up_to]['id']:
            old = up_row
        if old is None and a['originalId'] == fs[up_to]['id']:
            old = left_row
        if old is not None:
            row = dict(old, number=n, fromFragment=a['id'], toFragment=b['id'], originalNumber=old['number'],
                       originalId=old['id'], originalFrom=old['fromFragment'], originalTo=old['toFragment'])
            numbers[str(old['number'])], ids[str(old['number'])] = n, old['id']
        else:
            mixed = b['semanticId'].startswith('R')
            row = dict(number=n, id='OPEN-%s-%s' % (a['semanticId'], b['semanticId']), fromFragment=a['id'],
                       toFragment=b['id'], direction=b['openingDirection'] if mixed else 'LEFT',
                       percent=None, action=b['openingDirection'] if mixed else 'Added opening release jump',
                       baseline=False, originalNumber=None, originalId=None)
            if mixed:
                row.update(departureSurface=a.get('surface', 'top'), arrivalSurface=b['surface'])
        out_rows.append(row)
    route_map = dict(factor=factor, fragmentIds=fragment_ids, encounterNumbers=numbers, encounterIds=ids,
                     addedFragments={f['semanticId']: f['id'] for f in out if f['originalId'] is None},
                     addedEncounters=[r['id'] for r in out_rows if r['originalId'] is None],
                     openingCombination=[r['id'] for r in out_rows if 'arrivalSurface' in r],
                     baselineSpans=dict(rightward=span_r, leftward=span_l))
    return out, out_rows, route_map


def band_ends(m, number):
    """Fragment indices of an original jump's endpoints in the current route."""
    route = m.get('routeMap')
    if not route:
        return number-1, number
    row = next(r for r in m['encounters'] if r.get('originalNumber') == number)
    index = {f['id']: i for i, f in enumerate(m['fragments'])}
    return index[route['fragmentIds'][row['originalFrom']]], index[route['fragmentIds'][row['originalTo']]]


def tune(source, reposition=True, guards=True, opening=None, yellow_clearance=LEGACY_YELLOW_CLEARANCE):
    source = copy.deepcopy(source)
    # The extra second polygon is the unwanted rectangular bump, not the shelf.
    for n, fragment in enumerate(source['fragments']):
        if n < 10:
            assert len(fragment['polys']) == 2
            fragment['polys'] = fragment['polys'][:1]
        fragment['surfaceRole'] = 'bounce'
    if reposition:
        # Keep the upper shelf over the far end of P4, away from P3's flight arc.
        shelf=source['fragments'][5]
        scale=450 / shelf['width']
        shelf['polys']=[[[x*scale,y] for x,y in poly] for poly in shelf['polys']]
        shelf['width']=450
    # Collision polygons, not only outlines: placement below measures blunted shapes.
    blunted = blunt_fragments(source)
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
                return dict(original, x=(a['x']-400 if reposition and n == 3 else a['x']+vx*t), y=a['y']+vy*t)
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
    if opening:
        fs[:], m['encounters'], m['routeMap'] = extend_opening(fs, m['encounters'], opening)
        m['combinations'] = [[m['routeMap']['encounterNumbers'][str(n)] for n in combo] for combo in m['combinations']]
    for row in m['encounters']:
        n = row['number']; a,b = fs[n-1:n+1]
        d,w,_,_ = gap(a,b)
        # Gap targets stay keyed by the original concept numbering; new transfers record their measured gap.
        old = row.get('originalNumber', n)
        percent = TARGETS.get(old, row['percent']) if old else round(d/5.4, 2)
        row.update(percent=percent, distance=d, witness=w,
                   flight=[svg.contact(a),svg.contact(b)], baseline=False)
    m['pairChecks'] = []
    for i,a in enumerate(fs):
        for b in fs[i+1:]:
            d = gap(a,b)[0]
            m['pairChecks'].append(dict(source=a['id'],target=b['id'],minimumGap=d,passOutsideRange=d-21.6>540))
    placed_bands = []
    for band in m['yellowBands']:
        # A split original jump keeps its band centred between its original endpoints.
        a,b = [fs[i] for i in band_ends(m, band['belowJump'])]
        if opening:
            band.update(belowEncounter=m['routeMap']['encounterIds'][str(band['belowJump'])],
                        belowJump=m['routeMap']['encounterNumbers'][str(band['belowJump'])])
        x=(svg.contact(a)[0]+svg.contact(b)[0])/2-band['width']/2
        y=max(svg.contact(a)[1],svg.contact(b)[1])+900
        for step in range(200):
            by=y+step*120
            poly=[[x,by],[x+band['width'],by],[x+band['width'],by+band['height']],[x,by+band['height']]]
            nearest=min(union_distance([poly],svg.bodies(f))[0] for f in fs)
            if nearest>=yellow_clearance and all(union_distance([poly],[other])[0]>=120 for other in placed_bands):break
        else: raise ValueError('Cannot place '+band['id'])
        placed_bands.append(poly)
        band.update(x=x,y=by,polygon=poly,nearestSolidClearance=nearest,minimumSolidClearance=yellow_clearance)
        band.pop('nominalRouteSampleCheck',None)
    if guards:
        add_shortcut_guards(m, yellow_clearance)
    consolidate_yellow_bands(m, yellow_clearance)
    m['fallIllustrations'] = [dict(id='F'+str(i+1),band=z['id'],start=[z['x']+z['width']/2,z['y']-500],
        end=[z['x']+z['width']/2,z['y']+1000],meaning='Illustrative fall only') for i,z in enumerate(m['yellowBands'])]
    m['bluntedCorners']=dict(minimumAngle=MIN_INTERIOR_ANGLE, face=BLUNT_FACE, changed=blunted)
    m['layoutId']=EXTENDED_LAYOUT if opening else LAYOUT
    m['allowedGrapplePairs']=[['P0','P1'],['P1','P2']]
    if opening:
        new=m['routeMap']['fragmentIds']
        m['allowedGrapplePairs']=[[new[a],new[b]] for a,b in m['allowedGrapplePairs']]
    m['checks']={'geometryOnly':True}
    m['limitations']=['Jump playability remains unverified. Opening transfers intentionally allow direct grappling.']
    return m


def box(fragment):
    points=[p for poly in svg.bodies(fragment) for p in poly]
    return min(x for x,y in points), min(y for x,y in points), max(x for x,y in points), max(y for x,y in points)


def add_shortcut_guards(m, clearance=LEGACY_YELLOW_CLEARANCE):
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
        if nxt and nxt[1]<ay-.01 and not (nxt[0]>=x+width+30 or nxt[2]<=x-30):continue
        # Cap the launch above a shelf; skip candidates whose intended next
        # platform occupies this corridor. Exact outcomes require physics probes.
        for height, offset in ((h, offset) for offset in range(0, 4001, 120) for h in ([600,400,240] if i == 0 else [800,600,400,240])):
            y=ay-clearance-height-offset
            poly=[[x,y],[x+width,y],[x+width,y+height],[x,y+height]]
            nearest=min(union_distance([poly],svg.bodies(f))[0] for f in fs)
            if nearest<clearance or width<=height: continue
            if any(union_distance([poly],[g['polygon']])[0]<30 for g in guards):continue
            guards.append(dict(id='G'+str(len(guards)+1),belowJump=i+1,source=a['id'],
                target=None if j is None else fs[j]['id'],purpose='upward shortcut brake',
                x=x,y=y,width=width,height=height,polygon=poly,nearestSolidClearance=nearest,
                minimumSolidClearance=clearance,role='non-solid, non-grappleable, pass-through braking'))
            break
    m['yellowBands']+=guards
    m['shortcutCandidates']=[{'from':fs[i]['id'],'to':None if j is None else fs[j]['id']} for i,j in candidates]


def consolidate_yellow_bands(m, clearance=LEGACY_YELLOW_CLEARANCE):
    """Prefer one long rectangle; never bridge a green panel to merge zones."""
    bands=m['yellowBands']
    while True:
        conflict=next(((i,j) for i,a in enumerate(bands) for j,b in enumerate(bands)
                       if i<j and union_distance([a['polygon']],[b['polygon']])[0]<YELLOW_PAIR_CLEARANCE),None)
        if conflict is None:
            break
        i,j=conflict; a,b=bands[i],bands[j]
        x,y=min(a['x'],b['x']),min(a['y'],b['y'])
        right=max(a['x']+a['width'],b['x']+b['width'])
        bottom=max(a['y']+a['height'],b['y']+b['height'])
        poly=[[x,y],[right,y],[right,bottom],[x,bottom]]
        nearest=min(union_distance([poly],svg.bodies(f))[0] for f in m['fragments'])
        if right-x > bottom-y and nearest>=clearance:
            a.update(x=x,y=y,width=right-x,height=bottom-y,polygon=poly,
                     nearestSolidClearance=nearest,minimumSolidClearance=clearance)
            a['mergedFrom']=a.get('mergedFrom',[a['id']])+b.get('mergedFrom',[b['id']])
            del bands[j]
        else:
            # Prefer the longer existing horizontal zone when a union is unsafe.
            del bands[j if a['width']>=b['width'] else i]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',required=True)
    ap.add_argument('--output-dir',required=True)
    ap.add_argument('--guidelines', default=str(GUIDELINES), help='Required current design guidelines')
    ap.add_argument('--opening', choices=('extended', 'original'), default='extended',
                    help='extended: threefold rightward/leftward opening (guidelines); original: the v5 layout')
    args=ap.parse_args()
    guidelines=Path(args.guidelines).read_bytes()
    opening = OPENING if args.opening == 'extended' else None
    # The extended layout follows the current 300% rule; original reproduces v5 (200%).
    clearance, rule = (YELLOW_CLEARANCE, b'300% R = 1,620 units') if opening else (LEGACY_YELLOW_CLEARANCE, b'')
    if (rule and rule not in guidelines) or b'100% R = 540 units' not in guidelines:
        raise ValueError('Guidelines must specify the supported 300% panel and 100% yellow-pair clearances')
    if opening and b'3x the pre-change' not in guidelines:
        raise ValueError('Guidelines must specify the threefold opening rule')
    if opening and b'ceiling underside catch' not in guidelines:
        raise ValueError('Guidelines must specify the mixed opening combination')
    dest=Path(args.output_dir); dest.mkdir(parents=True,exist_ok=True)
    m=tune(json.loads(Path(args.source).read_text()), opening=opening, yellow_clearance=clearance)
    m['guidelines']={'path':str(Path(args.guidelines).resolve()),'sha256':hashlib.sha256(guidelines).hexdigest(),'yellowMinimumPercent':round(clearance/5.4),'yellowPairMinimumPercent':100}
    svg.LAYOUT_ID=m['layoutId']
    # The shipped extended level carries display-only transfer guides and their arrows (TASK-660);
    # the original opening stays the frozen v5 reproduction without them.
    text=svg.build(m, guides=bool(opening), arrows=bool(opening))
    text=text.replace('01–10: preserved baseline geometry', 'Opening 80% · vertical transfers 150%')
    text=text.replace('BASELINE PRESERVED', 'EASIER OPENING / SHORTER CLIMBS')
    text=text.replace('original 01–10 unchanged','opening gaps 80%; vertical gaps 150%')
    text=text.replace('Geometric checks exclude direct fragment-to-fragment grappling.', 'Opening transfers allow grappling; later transfers remain beyond grapple range.')
    text=text.replace('No nominal illustrated arc enters a band.', 'Fall-band paths require gameplay testing.')
    text=text.replace('All 300 fragment pairs > grapple + player diameter.', 'Opening pairs allow grappling; other pairs stay separated.')
    lines=text.splitlines(True)
    (dest/'extended-mountain.svg').write_text(''.join(lines))
    (dest/'extended-mountain-measurements.json').write_text(json.dumps(m,separators=(',',':'))+'\n')
    print('Wrote',dest,'layout',m['layoutId'],'fragments',len(m['fragments']),'transfers',len(m['encounters']),'targets',TARGETS)

if __name__=='__main__':main()
