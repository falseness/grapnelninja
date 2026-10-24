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
EXTENDED_LAYOUT = 'extended-mountain-v14'
OPENING_TARGETS = dict(TARGETS)
OPENING_TARGETS.update({1:120, 2:160})
# Rightward span is a minimum; usable surfaces and measured release gaps take
# priority over fitting a fixed endpoint. Fold separation may change the leftward span.
MIN_OPENING_SPAN = 720.0
# After the two opening release jumps the rightward run is one mixed combination:
# ceiling underside catch, descent onto a sloped bounce face, rebound up, then
# a mostly horizontal transfer to the upward-turn departure. lift is the rise
# of the new contact over the previous one (negative descends); gap is the
# complete-polygon release gap reached by sliding the panel rightward.
# The opening uses a ceiling catch, descending slope, rebound and exposed hop.
# Geometry is only a candidate until the whole-route production audit and
# continuous combination replay pass; an edge-gap check cannot prove this.
# Original v5 P0-to-P2 contact span; increasing the first gaps must not
# multiply the already-extended ceiling combination a second time.
OPENING = dict(factor=3, baselineRightSpan=1836.2141822795545,
               right=[dict(kind='ceiling', width=2700, height=240, lift=1250, gap=1620, share=.52,
                           surface='underside', direction='UP-RIGHT → CEILING HOLD', pattern='ceiling-catch'),
                      dict(kind='bounce', width=3600, height=700, lift=-1000, gap=1080, share=.22, drop=320,
                           surface='slope', direction='RELEASE → DOWN-RIGHT ONTO SLOPE', pattern='descending-slope'),
                      dict(kind='platform', width=1400, height=180, lift=650, gap=1080, share=.22,
                           surface='top', direction='BOUNCE → UP-RIGHT', pattern='upward-rebound'),
                      dict(kind='platform', width=1000, height=260, lift=400, gap=2160, share=.22,
                           surface='top', direction='RIGHT → EXPOSED TRANSFER', pattern='exposed-traverse')],
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
# physics.js CLIMB_FALL_RECOVERY_DEPTH: a fall this far below the spawn returns
# the player to the spawn, so a yellow brake must lie wholly above that line
# (bottom plus the player radius): a falling player then passes through it
# before recovery; one the line cuts is never traversed.
FALL_RECOVERY_DEPTH = 1500
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


def panel(name, width, height, x, y, kind='platform', drop=240):
    """A new green panel; svg.contact() gives its contact for each kind.

    platform: trapezoid, contact above the top-edge centre. ceiling: slab with
    a raised top (the concept's ceiling profile), contact below the underside
    centre. bounce: the concept's sloped face falling drop (240) units to the
    right, contact above the slope midpoint; another drop is kept as slopeDrop.
    """
    inset = round(width*.12, 3)
    polys = {'platform': [[0, 0], [width, 0], [width-inset, height], [inset, height]],
             'ceiling': [[0, -90], [width, -90], [width, height], [0, height]],
             'bounce': [[0, 0], [width, drop], [width, height], [0, height-drop]]}[kind]
    # The concept's face falling to the right redirects up-right (bounceSign 1).
    out = dict(id=None, name=name, x=x, y=y, width=width, height=height, kind=kind,
               bounceSign=1 if kind == 'bounce' else 0,
               surfaceRole='bounce', polys=[polys])
    if kind == 'bounce' and drop != 240:
        out['slopeDrop'] = drop
    return out


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


def place_along(anchor, fragment, ux, uy, target, origin=None, steps=80):
    """Translate fragment from origin (anchor's origin by default) along (ux, uy) until its gap to anchor is target."""
    ox, oy = origin or (anchor['x'], anchor['y'])
    lo, hi = 0., 30000.
    for _ in range(steps):
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
    span_r, span_l = spec.get('baselineRightSpan', cx(fs[right_end])-cx(fs[0])), cx(fs[up_to])-cx(fs[left_end])
    # Each panel rises (or descends) by lift between contacts, then slides
    # rightward until its complete-polygon gap to the previous panel is gap.
    added, prev = [], fs[right_end]
    total = sum(p['share'] for p in spec['right'])
    for k, p in enumerate(spec['right'], 1):
        shape = panel('Rightward %s %d' % (p['kind'], k), p['width'], p['height'], 0, 0, p['kind'], p.get('drop', 240))
        if usable_span(dict(shape, id='R%d' % k)) < MIN_OPENING_SPAN:
            raise ValueError('Opening landing surface must span at least 720 units')
        desired_x = cx(prev)+(factor-1)*span_r*p['share']/total
        y = svg.contact(prev)[1]-p['lift']-(svg.contact(shape)[1]-shape['y'])
        candidate = place_along(prev, shape, 1, 0, p['gap'], origin=(prev['x'], y))
        x = max(desired_x, cx(candidate))
        prev = dict(candidate, x=x-p['width']/2, semanticId='R%d' % k, surface=p['surface'],
                    openingDirection=p['direction'], pattern=p['pattern'])
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
                row.update(departureSurface=a.get('surface', 'top'), arrivalSurface=b['surface'], pattern=b['pattern'])
        out_rows.append(row)
    route_map = dict(factor=factor, fragmentIds=fragment_ids, encounterNumbers=numbers, encounterIds=ids,
                     addedFragments={f['semanticId']: f['id'] for f in out if f['originalId'] is None},
                     addedEncounters=[r['id'] for r in out_rows if r['originalId'] is None],
                     openingCombination=[r['id'] for r in out_rows if 'arrivalSurface' in r],
                     baselineSpans=dict(rightward=span_r, leftward=span_l))
    return out, out_rows, route_map


def separated(a,b,minimum):
    ax,ay,ar,ab=box(a);bx,by,br,bb=box(b)
    if math.hypot(max(0,bx-ar,ax-br),max(0,by-ab,ay-bb))>=minimum:return True
    return gap(a,b)[0]>=minimum


def separate_route_folds(fs, rows, minimum=3400):
    """Place the later route with room for legal brakes between unrelated legs.

    The opening folds reserve a 3400-unit corridor for legal yellow guards.
    Later lateral combinations use 2400 units and continue left, away from
    earlier terrain. These candidate clearances still require physics audits.
    Adjacent vertical transfers retain their 810-unit gap; their tall turn
    structures allow the following traverse to return above earlier terrain.
    """
    templates=copy.deepcopy(fs)
    visits=0
    def search(i):
        nonlocal visits
        visits+=1
        if i==len(fs):return True
        if visits>250:return False
        prev=fs[i-1]; old_prev,shape=templates[i-1],templates[i]
        clearance=minimum if i<18 else 2400
        a,b=svg.contact(old_prev),svg.contact(shape)
        theta=math.atan2(b[1]-a[1],b[0]-a[0])
        old=rows[i-1].get('originalNumber')
        vertical=old in TARGETS and TARGETS[old]==150
        descent=shape['kind']=='bounce' and old_prev['kind']=='ceiling'
        target=810 if vertical else 1350 if old_prev['kind']=='bounce' else max(1080,gap(old_prev,shape)[0])
        if i==16:theta-=math.radians(5)
        if i==17:theta=math.atan2(-.6,-1)
        if descent:theta=math.atan2(.4,-1)
        if old_prev['kind']=='bounce' and not vertical:
            incoming=svg.contact(prev)[0]-svg.contact(fs[i-2])[0]
            theta=math.atan2(-.25,1 if incoming>0 else -1)
        offsets=[0]+[sign*d for d in (range(5,16,5) if old_prev['kind']=='bounce' else range(5,86,5)) for sign in (1,-1)]
        angles=[theta+math.radians(delta) for delta in offsets]
        if i>10 and not vertical:
            angles += [math.pi-theta+math.radians(delta) for delta in offsets]
        for factor in ((1,) if vertical else (1,1.15,1.3,1.5,1.75,2)):
            if visits>250:return False
            if i+1<len(fs):
                next_old=rows[i].get('originalNumber')
                if next_old in TARGETS and TARGETS[next_old]==150:
                    points=[p for poly in shape['polys'] for p in poly]
                    diameter=max(math.dist(a,b) for a in points for b in points)
                    if target*factor+diameter+810<clearance:continue
            for angle in angles:
                ux,uy=math.cos(angle),math.sin(angle)
                if i>=17 and not vertical and ux>=0:continue
                if (i<=10 and not vertical and (b[0]-a[0])*ux < -1e-6) or (not descent and (b[1]-a[1])*uy < -1e-6):continue
                if 8<=i<=10 and abs(uy)>=abs(ux):continue
                if vertical and (uy>=0 or abs(uy)<abs(ux)):continue
                local=svg.contact(dict(shape,x=0,y=0))
                origin=(svg.contact(prev)[0]-local[0],svg.contact(prev)[1]-local[1])
                candidate=place_along(prev,shape,ux,uy,target*factor,origin=origin,steps=35)
                ca,cb=svg.contact(prev),svg.contact(candidate)
                if shape['kind']=='bounce' and old_prev['kind']=='ceiling' and cb[1]-ca[1]<800:continue
                if not vertical and abs(b[1]-a[1])<.25*abs(b[0]-a[0]) and abs(cb[1]-ca[1])>=abs(cb[0]-ca[0]):continue
                if all(separated(f,candidate,clearance) for f in fs[:i-1]):
                    fs[i]=candidate
                    if search(i+1):return True
        return False
    if not search(7):raise ValueError('Cannot separate folded route after %d placement branches' % visits)
    for i in range(7,len(fs)):
        prev,chosen=fs[i-1:i+1]
        a,b=svg.contact(templates[i-1]),svg.contact(templates[i])
        if (svg.contact(chosen)[0]-svg.contact(prev)[0])*(b[0]-a[0])<0:
            for field in ('direction','action'):
                text=rows[i-1][field]
                rows[i-1][field]=text.replace('LEFT','TEMP').replace('RIGHT','LEFT').replace('TEMP','RIGHT')


def spread_upper_landings(fs):
    """Put the next turn beyond a slope's pumped shortcut trajectory.

    Extend the landing to the left without moving its incoming right edge,
    then shift the following route left. This retains the 810-unit vertical
    gap and the preceding exposed rebound while separating the two skips.
    """
    for index in (19,26):
        f=fs[index]; old=f['width']; width=3300
        f['x']-=width-old
        f['polys']=[[[x*width/old,y] for x,y in poly] for poly in f['polys']]
        f['width']=width
        for later in fs[index+1:]:later['x']-=1200
    # The last natural slope rebound has a lower apex than a pumped fixture.
    # Keep the exposed transfer, but place the summit inside that catch arc.
    fs[-1]['y']+=300


def band_ends(m, number):
    """Fragment indices of an original jump's endpoints in the current route."""
    route = m.get('routeMap')
    if not route:
        return number-1, number
    row = next(r for r in m['encounters'] if r.get('originalNumber') == number)
    index = {f['id']: i for i, f in enumerate(m['fragments'])}
    return index[route['fragmentIds'][row['originalFrom']]], index[route['fragmentIds'][row['originalTo']]]


# Legacy lower catch chain (TASK-675 and earlier): eight platform tops. Only its
# endpoint is still used: the upward-turn departure stays exactly where it was,
# so the upper route, the purple extension and the late falls keep their geometry.
LEGACY_LOWER_SPECS=[(4200,350,1620),(5000,-650,1350),(3600,450,1890),
                    (4600,100,1620),(4000,-500,1350),(5000,600,1890),
                    (4400,-250,1620),(1000,300,1350)]
# TASK-676: the rest of the rightward run varies its mechanics after the R1-R4
# combination (which ends with an exposed traverse). Each entry: (pattern, kind,
# width, height, lift, gap, slope drop); lift is the contact rise over the
# previous contact, gap the complete-polygon release gap. Patterns never repeat
# back to back: exposed -> descent -> rebound -> ceiling -> descent -> rebound
# -> exposed -> ceiling -> descent -> rebound -> exposed (the departure, which is
# the legacy endpoint itself).
LOWER_PATTERNS=[('descending-slope','bounce',4400,700,-1800,1350,320),
                ('upward-rebound','platform',3400,300,650,1080,None),
                ('ceiling-catch','ceiling',3000,240,1150,1620,None),
                ('descending-slope','bounce',4400,700,-1350,1080,320),
                ('upward-rebound','platform',3400,300,650,1080,None),
                ('exposed-traverse','platform',5000,380,400,2700,None),
                ('ceiling-catch','ceiling',3000,240,1150,1620,None),
                ('descending-slope','bounce',4400,700,-1350,1080,320),
                ('upward-rebound','platform',5100,300,650,1080,None),
                ('exposed-traverse','platform',1000,460,None,None,None)]
# Minimum horizontal contact advance of a descent: the slope starts below-right of
# its departure, so a descent below a ceiling stays a diagonal drop.
MIN_DESCENT_ADVANCE=2500
PATTERN_TEXT={'ceiling-catch':('UP-RIGHT → CEILING HOLD','Grab the ceiling underside from below','underside'),
              'descending-slope':('RELEASE → DOWN-RIGHT ONTO SLOPE','Drop down-right onto the sloped bounce face','slope'),
              'upward-rebound':('BOUNCE → UP-RIGHT','Rebound up-right off the slope onto the top','top'),
              'exposed-traverse':('RIGHT → EXPOSED TRANSFER','Exposed rightward release jump between tops','top')}


def legacy_lower_end(start):
    prev=start
    for i,(width,lift,distance) in enumerate(LEGACY_LOWER_SPECS,1):
        f=panel('Lower return catch %d'%i,width,300+(i%3)*80,0,0)
        y=svg.contact(prev)[1]-lift
        prev=place_along(prev,f,1,0,distance,origin=(prev['x'],y))
    return prev


def extend_lower_catch_route(m):
    """Lengthen the opening below the late leftward route, preserving upper geometry.

    Insert full-size landing structures after the original mixed combination,
    varying ceiling catches, descending slope landings, upward rebounds and
    exposed traverses. The last structure (the upward-turn departure) keeps
    the legacy endpoint, so the upper route moves exactly as before.
    Distances remain measured release gaps.
    """
    fs=m['fragments']; rows=m['encounters']; route=m['routeMap']
    anchor=legacy_lower_end(fs[6])
    added=[]; prev=fs[6]
    for i,(pattern,kind,width,height,lift,distance,drop) in enumerate(LOWER_PATTERNS,1):
        surface=PATTERN_TEXT[pattern][2]
        if i==len(LOWER_PATTERNS):
            f=dict(anchor,name='Lower return catch %d'%i)
        else:
            f=panel('Lower return catch %d'%i,width,height,0,0,kind,drop or 240)
            y=svg.contact(prev)[1]-lift-(svg.contact(f)[1]-f['y'])
            f=place_along(prev,f,1,0,distance,origin=(prev['x'],y))
            # A descent below a ceiling would clear its gap vertically; keep it a diagonal drop.
            advance=svg.contact(prev)[0]+MIN_DESCENT_ADVANCE-svg.contact(f)[0]
            if pattern=='descending-slope' and advance>0:f['x']+=advance
        if usable_span(dict(f,id='X%d'%i))<MIN_OPENING_SPAN:
            raise ValueError('X%d landing surface must span at least 720 units'%i)
        f.update(semanticId='X%d'%i,originalId=None,surface=surface,pattern=pattern)
        added.append(f);prev=f
    dx=prev['x']-fs[6]['x'];dy=prev['y']-fs[6]['y']
    for f in fs[7:]:f['x']+=dx;f['y']+=dy
    old_ids={f['id']:f for f in fs}
    fs[7:7]=added
    for i,f in enumerate(fs):f['id']='P%d'%i
    mapping={old:f['id'] for old,f in old_ids.items()}
    for r in rows:
        r['fromFragment']=mapping[r['fromFragment']];r['toFragment']=mapping[r['toFragment']]
    rows[6]['fromFragment']=added[-1]['id']
    extra=[]
    for i,f in enumerate(added,1):
        a=fs[5+i]
        direction,action,_=PATTERN_TEXT[f['pattern']]
        if i==len(added):action+=' to the upward-turn departure'
        extra.append(dict(id='RIGHT-EXT-%02d'%i,fromFragment=a['id'],toFragment=f['id'],
            direction=direction,action=action,pattern=f['pattern'],
            departureSurface=a.get('surface','top'),arrivalSurface=f['surface'],
            baseline=False,originalNumber=None,originalId=None,percent=None))
    rows[6:6]=extra
    for r in rows[:2]:r.setdefault('pattern','release-jump')
    for i,r in enumerate(rows,1):r['number']=i
    route['fragmentIds']={k:mapping[v] for k,v in route['fragmentIds'].items()}
    route['addedFragments']={k:mapping[v] for k,v in route['addedFragments'].items()}
    route['addedFragments'].update({f['semanticId']:f['id'] for f in added})
    route['encounterNumbers']={str(r['originalNumber']):r['number'] for r in rows if r.get('originalNumber')}
    route['addedEncounters'] += [r['id'] for r in extra]
    m['combinations']=[[n+len(added) if n>=7 else n for n in group] for group in m['combinations']]
    m['lowerCatchExtension']=dict(fragments=[f['id'] for f in added],patterns=[f['pattern'] for f in added],
        addedHorizontalSpan=dx,upperTranslation=[dx,dy],firstUpDeparture=added[-1]['id'],
        purpose='Earlier terrain beneath late leftward falls, with a rightward return to the climb')


# Purple no-grapple extension (TASK-675): after the first right -> up -> left
# sequence the route continues leftward from its arrival (original P4) to an
# approach ledge, then through one 10R x 5R zone on rope-free bounces and out
# to an exit ledge. The exit is a copy of the original departure, so the
# upward transfer and every later panel keep their geometry, translated by
# shift. shift keeps the three leftmost late panels above lower terrain.
# Internal panels are zone-local rotated slabs: (name, contact point of the
# player centre, surface angle in degrees (0 = horizontal, y down; positive
# tilts the right end down), surface extent before/after the contact along the
# surface, thickness, side) with side +1 for a top face, -1 for an underside.
PURPLE = dict(shift=-7500, approachGap=1350, approach=(1200, 260), zone=(5400, 2700), zoneMargin=60,
              panels=[('Kicker slope', (4468.535, 1608.966), -32.8, 502, 385, 305, 1),
                      ('Low ceiling', (3993.895, 1467.495), 4.8, 962, 375, 149, -1),
                      ('Chute floor', (3048.898, 1616.432), 0.0, 706, 369, 364, 1),
                      ('Overhang', (1995.901, 1459.177), 0.6, 1309, 278, 283, -1),
                      ('Launch ramp', (671.178, 1655.582), 33.5, 481, 946, 202, 1)])
NO_GRAPPLE_INTERNAL_GAP = 270.0


def slab(contact, angle, before, after, thickness, side):
    """Rectangle whose face lies PLAYER_RADIUS from contact, on the side the player touches."""
    ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    # Outward normal of the face: up for a top (side 1), down for an underside.
    nx, ny = uy*side, -ux*side
    fx, fy = contact[0]-nx*svg.PLAYER_RADIUS, contact[1]-ny*svg.PLAYER_RADIUS
    a, b = (fx-ux*before, fy-uy*before), (fx+ux*after, fy+uy*after)
    c, d = (b[0]-nx*thickness, b[1]-ny*thickness), (a[0]-nx*thickness, a[1]-ny*thickness)
    poly = [a, b, c, d]
    return poly if side > 0 else poly[::-1]


def purple_panel(name, points, contact_point, surface, zx, zy):
    pts = [(zx+x, zy+y) for x, y in points]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    return dict(id=None, name=name, x=x0, y=y0, width=max(p[0] for p in pts)-x0, height=max(p[1] for p in pts)-y0,
                kind='chute', bounceSign=0, surfaceRole='bounce', surface=surface,
                contactPoint=[zx+contact_point[0]-x0, zy+contact_point[1]-y0],
                polys=[[[px-x0, py-y0] for px, py in pts]])


def zone_contains(zone, fragment):
    x, y, w, h = zone['x'], zone['y'], zone['width'], zone['height']
    return all(x <= px <= x+w and y <= py <= y+h for poly in svg.bodies(fragment) for px, py in poly)


def extend_purple_route(m, spec):
    fs, rows, route = m['fragments'], m['encounters'], m['routeMap']
    k = next(i for i, f in enumerate(fs) if f['id'] == route['fragmentIds']['P4'])
    up = rows[k]
    if up['originalId'] != 'S07-03' or up['fromFragment'] != fs[k]['id']:
        raise ValueError('Purple extension expects the first leftward arrival before S07-03')
    dep = fs[k]
    shift = spec['shift']
    exit_ = dict(copy.deepcopy(dep), name='Purple exit ledge', x=dep['x']+shift, originalId=None, semanticId='NG-EXIT')
    w, h = spec['approach']
    approach = dict(panel('Purple approach ledge', w, h, 0, 0), originalId=None, semanticId='NG-APPROACH')
    approach = place_along(dep, approach, -1, 0, spec['approachGap'], origin=(dep['x']-w, dep['y']))
    # The zone ends just left of the approach and starts just below the exit
    # ledge, which overhangs its upper-left part: the player leaves through the top.
    zw, zh = spec['zone']
    zx = approach['x']-spec['zoneMargin']-zw
    zy = exit_['y']+exit_['height']+spec['zoneMargin']
    zone = dict(id='NG1', x=zx, y=zy, width=zw, height=zh, polygon=[[zx, zy], [zx+zw, zy], [zx+zw, zy+zh], [zx, zy+zh]],
                purpose='no-grapple bounce chute: rope-free momentum traversal')
    internal = []
    for n, (name, contact, angle, before, after, thickness, side) in enumerate(spec['panels'], 1):
        f = purple_panel(name, slab(contact, angle, before, after, thickness, side), contact,
                         'top' if side > 0 else 'underside', zx, zy)
        f.update(originalId=None, semanticId='NG%d' % n, surfaceAngle=angle)
        internal.append(f)
    for f in [approach, exit_]:
        if union_distance(svg.bodies(f), [zone['polygon']])[0] <= 0:
            raise ValueError('%s must lie outside the purple zone' % f['semanticId'])
    for f in internal:
        if not zone_contains(zone, f):
            raise ValueError('%s must lie completely inside the purple zone' % f['semanticId'])
    for f in fs[k+1:]:
        f['x'] += shift
    added = [approach]+internal+[exit_]
    fs[k+1:k+1] = added
    old_ids = {f['id']: f for f in fs if f['id'] is not None and f.get('semanticId') not in [a['semanticId'] for a in added]}
    for i, f in enumerate(fs):
        f['id'] = 'P%d' % i
    mapping = {old: f['id'] for old, f in old_ids.items()}
    for r in rows:
        r['fromFragment'], r['toFragment'] = mapping[r['fromFragment']], mapping[r['toFragment']]
    up['fromFragment'] = exit_['id']
    chain = [dep]+added
    extra = []
    for a, b in zip(chain, chain[1:]):
        if b is approach:
            rid, direction, action = 'NG-APPROACH', 'LEFT', 'Leftward release jump to the purple approach ledge'
        elif a is approach:
            rid, direction, action = 'NG-ENTRY', 'LEFT → MOMENTUM ENTRY', 'Carry momentum into the no-grapple zone'
        elif b is exit_:
            rid, direction, action = 'NG-EXIT', 'UP → EXIT LEDGE', 'Launch out of the zone top, then grapple the exit ledge'
        else:
            rid, direction, action = 'NG-%s-%s' % (a['semanticId'], b['semanticId']), 'BOUNCE', \
                'Rope-free bounce off the %s %s' % (b['surface'], b['name'].lower())
        extra.append(dict(id=rid, fromFragment=a['id'], toFragment=b['id'], direction=direction, action=action,
                          baseline=False, originalNumber=None, originalId=None, percent=None,
                          noGrappleZone=zone['id'] if a in internal and b in internal else None))
    rows[k:k] = extra
    for i, r in enumerate(rows, 1):
        r['number'] = i
    route['fragmentIds'] = {o: mapping[v] for o, v in route['fragmentIds'].items()}
    route['addedFragments'] = {s: mapping.get(v, v) for s, v in route['addedFragments'].items()}
    route['addedFragments'].update({f['semanticId']: f['id'] for f in added})
    route['encounterNumbers'] = {str(r['originalNumber']): r['number'] for r in rows if r.get('originalNumber')}
    route['addedEncounters'] += [r['id'] for r in extra]
    first = k+1
    m['combinations'] = [[n+len(extra) if n >= first else n for n in group] for group in m['combinations']]
    ext = m['lowerCatchExtension']
    ext['fragments'] = [mapping.get(f, f) for f in ext['fragments']]
    ext['firstUpDeparture'] = mapping.get(ext['firstUpDeparture'], ext['firstUpDeparture'])
    m['noGrappleZones'] = [zone]
    m['purpleExtension'] = dict(zone=zone['id'], arrival=dep['id'], approach=approach['id'], exit=exit_['id'],
                                internal=[f['id'] for f in internal], encounters=[r['id'] for r in extra],
                                upperTranslation=[shift, 0], exitCopiesDeparture=dep['id'],
                                purpose='Leftward rope-free bounce traversal after the first right -> up -> left sequence')


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
    if opening:
        # Shallow rebound faces retain enough vertical momentum for the next
        # lateral transfer instead of ejecting the player below its catch.
        for f in source['fragments']:
            if f['kind']=='bounce':
                shape=panel(f['name'],f['width'],f['height'],f['x'],f['y'],'bounce',80)
                f['polys']=shape['polys'];f['slopeDrop']=80
                if f['bounceSign']<0:
                    f['polys']=[list(reversed([[f['width']-x,y] for x,y in poly])) for poly in f['polys']]
        for index in (13,16,20):
            f=source['fragments'][index]
            width=max(1440,f['width'])
            sx=width/f['width']
            f['polys']=[[[x*sx,y] for x,y in poly] for poly in f['polys']]
            f['width']=width
        # Tall turn structures put the returning route above the preceding jump
        # corridor. Their lower catch remains a 150% vertical transfer; the
        # player climbs the continuous side before taking the next traverse.
        for index, height in ((3, 6500), (5, 2200), (8, 6500), (21, 2200)):
            f = source['fragments'][index]
            ratio = height/f['height']
            width=max(f['width'],source['fragments'][index-1]['width']+1080)
            sx=width/f['width']
            f['polys'] = [[[x*sx, y*ratio] for x,y in poly] for poly in f['polys']]
            f['height'],f['width'] = height,width
    # Collision polygons, not only outlines: placement below measures blunted shapes.
    blunted = blunt_fragments(source)
    m = copy.deepcopy(source)
    fs = m['fragments']
    for n in range(1, len(fs)):
        a, original = fs[n-1], source['fragments'][n]
        prev = source['fragments'][n-1]
        dx, dy = original['x']-prev['x'], original['y']-prev['y']
        angle = math.atan2(dy, dx) + math.radians(DIRECTION_OFFSETS.get(n, 0) if reposition else 0)
        if opening and n == 6:
            angle += math.radians(30)
        target = (OPENING_TARGETS if opening else TARGETS).get(n, source['encounters'][n-1]['percent']) * 5.4
        angles = [angle]
        if n not in TARGETS:
            angles += [angle + math.radians(delta*sign) for delta in range(5, 86, 5) for sign in (1, -1)]
        base_target=target
        factors=(1,1.15,1.3,1.5) if opening and n not in TARGETS else (1,)
        for theta,target in ((theta,base_target*factor) for factor in factors for theta in angles):
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
        separate_route_folds(fs,m['encounters'])
        spread_upper_landings(fs)
        for f in fs:
            if f['kind']=='ceiling':
                w,h=f['width'],f['height']
                f['polys']=[[[0,-90],[w,-90],[w,h],[0,h]]]
        for f,nxt in zip(fs,fs[1:]):
            if f['kind']!='bounce':continue
            direction=1 if svg.contact(nxt)[0]>svg.contact(f)[0] else -1
            if f['bounceSign']!=direction:
                f['polys']=[list(reversed([[f['width']-x,y] for x,y in poly])) for poly in f['polys']]
                f['bounceSign']=direction
        extend_lower_catch_route(m)
        extend_purple_route(m, PURPLE)
        add_shortcut_shields(m, SHIELDS)
    for row in m['encounters']:
        n = row['number']; a,b = fs[n-1:n+1]
        d,w,_,_ = gap(a,b)
        # Gap targets stay keyed by the original concept numbering; new transfers record their measured gap.
        old = row.get('originalNumber', n)
        percent = round(d/5.4, 2) if opening else TARGETS.get(old, row['percent']) if old else round(d/5.4, 2)
        if row.get('noGrappleZone'):
            # Scoped exception: both panels lie inside one convex purple zone (level-guidelines.md).
            if not 0 < d <= NO_GRAPPLE_INTERNAL_GAP:
                raise ValueError('Internal no-grapple transfer %s gap %.2f not in (0, 270]' % (row['id'], d))
        elif opening and old not in TARGETS and d < 1080 - .01:
            raise ValueError('Transfer %s violates the 200%% release-gap minimum: %.2f' % (row['id'], d))
        row.update(percent=percent, distance=d, witness=w,
                   flight=[svg.contact(a),svg.contact(b)], baseline=False)
    m['pairChecks'] = []
    for i,a in enumerate(fs):
        for b in fs[i+1:]:
            d = gap(a,b)[0]
            m['pairChecks'].append(dict(source=a['id'],target=b['id'],minimumGap=d,passOutsideRange=d-21.6>540))
    placed_bands, kept, unreachable = [], [], []
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
        # The frozen v5 reproduction (no opening) keeps its bands unchanged.
        if opening and by+band['height']+svg.PLAYER_RADIUS >= svg.SPAWN[1]+FALL_RECOVERY_DEPTH:
            unreachable.append(dict(id=band['id'], belowEncounter=band.get('belowEncounter'), y=by,
                                    recoveryLine=svg.SPAWN[1]+FALL_RECOVERY_DEPTH))
            continue
        placed_bands.append(poly)
        kept.append(band)
        band.update(x=x,y=by,polygon=poly,nearestSolidClearance=nearest,minimumSolidClearance=yellow_clearance)
        band.pop('nominalRouteSampleCheck',None)
    m['yellowBands'] = kept
    if unreachable:
        m['unreachableYellowBands'] = unreachable
    if guards:
        (add_shortcut_guards if opening else add_legacy_shortcut_guards)(m, yellow_clearance)
    if opening:
        add_opening_brake(m, yellow_clearance)
        add_final_transfer_brake(m, yellow_clearance)
    consolidate_yellow_bands(m, yellow_clearance)
    if opening:
        restore_guard_coverage(m, yellow_clearance)
    m['fallIllustrations'] = [dict(id='F'+str(i+1),band=z['id'],start=[z['x']+z['width']/2,z['y']-500],
        end=[z['x']+z['width']/2,z['y']+1000],meaning='Illustrative fall only') for i,z in enumerate(m['yellowBands'])]
    m['bluntedCorners']=dict(minimumAngle=MIN_INTERIOR_ANGLE, face=BLUNT_FACE, changed=blunted)
    m['layoutId']=EXTENDED_LAYOUT if opening else LAYOUT
    m['allowedGrapplePairs']=[] if opening else [['P0','P1'],['P1','P2']]
    if opening:
        new=m['routeMap']['fragmentIds']
        m['allowedGrapplePairs']=[[new[a],new[b]] for a,b in m['allowedGrapplePairs']]
    m['checks']={'geometryOnly':True}
    m['limitations']=['Geometry alone does not prove playability or shortcut absence; run production-input audits. A complete from-spawn climb remains unverified.']
    return m


# TASK-677: the whole-route shortcut matrix showed carried-momentum flights that
# pass beneath the R1 ceiling onto R2, a fall short of R4 that lands on (or
# grapples from below) X1's left end, which sat under R4, and a high entry over
# the purple approach that dives onto NG2's top past NG1. fins: a second body of
# a panel hanging below its underside (fragment-local x0..x1, from top to bottom
# below the underside). The ceiling-catch glide hugs R1's underside and passes
# through the slot above the fin; a flight from P2 lower under R1 strikes R1's
# fin itself and rebounds left. R1's fin stays right of its underside contact
# span. trim: X1's sloped face loses its left trim units (its right end and
# every later panel stay put). post: a wall of the given width and top height
# rising from the high right end of NG1's top face, inside the zone; the route
# drops almost vertically onto NG1 left of it, the diagonal dive strikes NG1.
# Every transfer gap stays measured; NG internal gaps are unchanged.
SHIELDS = dict(fins=[('R1', 1750, 2050, 300, 1600)], trim=('X1', 2100), post=('NG1', 80, 970))


def add_post(f, width, height):
    """Raise a wall from the right (high) end of a chute slab's top face; keeps fragment-local coordinates normalised."""
    pts = [(f['x']+x, f['y']+y) for x, y in f['polys'][0]]
    a, b = pts[0], pts[1]
    if f['surface'] != 'top' or not b[1] < a[1] or not b[0] > a[0]+width:
        raise ValueError('%s post needs a top face rising to the right' % f['semanticId'])
    t = (b[0]-width-a[0])/(b[0]-a[0])
    foot = (b[0]-width, a[1]+(b[1]-a[1])*t)
    pts = [a, foot, (foot[0], b[1]-height), (b[0], b[1]-height)]+pts[1:]
    cx, cy = f['x']+f['contactPoint'][0], f['y']+f['contactPoint'][1]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    f.update(x=x0, y=y0, width=max(p[0] for p in pts)-x0, height=max(p[1] for p in pts)-y0,
             contactPoint=[cx-x0, cy-y0], polys=[[[px-x0, py-y0] for px, py in pts]])
    return dict(foot=list(foot), top=b[1]-height)


def add_fin(f, x0, x1, top, bottom):
    """Add a separate body below a panel's underside (fragment-local x0..x1, top..bottom below it)."""
    h = f['height']
    f['polys'] = f['polys'][:1]+[[[x0, h+top], [x1, h+top], [x1, h+bottom], [x0, h+bottom]]]


def add_shortcut_shields(m, spec):
    by = {f['semanticId']: f for f in m['fragments']}
    sid, trim = spec['trim']
    f = by[sid]
    w, drop = f['width'], f['slopeDrop']
    if f['kind'] != 'bounce' or f['bounceSign'] != 1 or w-trim < MIN_OPENING_SPAN:
        raise ValueError('%s trim must keep a rightward slope at least 720 wide' % sid)
    lost = drop*trim/w
    f.update(x=f['x']+trim, y=f['y']+lost, width=w-trim, height=f['height']-lost, slopeDrop=drop-lost)
    f['polys'] = [[[0, 0], [w-trim, drop-lost], [w-trim, f['height']], [0, f['height']-(drop-lost)]]]
    fins = []
    for sid, x0, x1, top, bottom in spec['fins']:
        f = by[sid]
        if f['kind'] == 'ceiling' and x0 < f['width']/2 + MIN_OPENING_SPAN/2:
            raise ValueError('%s fin must hang right of the ceiling contact span' % sid)
        add_fin(f, x0, x1, top, bottom)
        under = f['y']+f['height']
        fins.append(dict(fragment=f['id'], semanticId=sid, localX=[x0, x1], slot=top, y=[under+top, under+bottom]))
    # The post belongs to the purple chute; a layout generated without it (tests) has no post.
    post = None
    if m.get('noGrappleZones'):
        sid, width, height = spec['post']
        post = dict(fragment=by[sid]['id'], semanticId=sid, width=width, height=height, **add_post(by[sid], width, height))
        if not zone_contains(m['noGrappleZones'][0], by[sid]):
            raise ValueError('%s post must stay inside the purple zone' % sid)
    m['shortcutShields'] = dict(fins=fins, trim=dict(fragment=by[spec['trim'][0]]['id'], semanticId=spec['trim'][0],
                                                       trimmedLeft=trim), post=post,
                                purpose='TASK-677: block demonstrated skips beneath R1, short of R4 onto X1 and over NG1')


def box(fragment):
    points=[p for poly in svg.bodies(fragment) for p in poly]
    return min(x for x,y in points), min(y for x,y in points), max(x for x,y in points), max(y for x,y in points)


def add_legacy_shortcut_guards(m, clearance=LEGACY_YELLOW_CLEARANCE):
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
        # Try the broad corridor first, then a narrower rectangle covering the
        # launch positions aligned with this particular upper target. A nearby
        # turn tower can make a full-width cap illegal while leaving a valid
        # brake over the actual bypass launch point.
        placements=[(x,width)]
        if j is not None:
            tx,ty,tr,tb=box(fs[j])
            lo,hi=max(ax,tx-540),min(ar,tr+540)
            if hi>lo:
                w=min(720,hi-lo+100)
                placements.extend([(lo,min(960,hi-lo)),(lo,w),((lo+hi-w)/2,w)])
        placed=False
        for gx,gw in placements:
            for height, offset in ((h, off) for off in range(0, 8001, 120) for h in (240,120)):
                y=ay-clearance-height-offset
                if j is not None and y < box(fs[j])[3]+clearance:
                    continue  # A brake above its target cannot prevent reaching it.
                poly=[[gx,y],[gx+gw,y],[gx+gw,y+height],[gx,y+height]]
                nearest=min(union_distance([poly],svg.bodies(f))[0] for f in fs)
                if nearest<clearance or gw<=height: continue
                if any(union_distance([poly],[g['polygon']])[0]<30 for g in guards):continue
                guards.append(dict(id='G'+str(len(guards)+1),belowJump=i+1,source=a['id'],
                    target=None if j is None else fs[j]['id'],purpose='upward shortcut brake',
                    x=gx,y=y,width=gw,height=height,polygon=poly,nearestSolidClearance=nearest,
                    minimumSolidClearance=clearance,role='non-solid, non-grappleable, pass-through braking'))
                placed=True
                break
            if placed:break
    m['yellowBands']+=guards
    m['shortcutCandidates']=[{'from':fs[i]['id'],'to':None if j is None else fs[j]['id']} for i,j in candidates]


def add_opening_brake(m, clearance):
    """One wide brake across the easy start's upward escape corridor.

    Search above nearby ceiling geometry as well as the launch panels. Local
    guards below a ceiling used to conflict and consolidation discarded them.
    Complete-polygon clearances still apply to every candidate rectangle.
    """
    fs=m['fragments']
    x=min(box(f)[0] for f in fs[:3])-100
    width=max(box(f)[2] for f in fs[:3])+100-x
    height=120
    y=min(box(f)[1] for f in fs[:3])-clearance-height
    for offset in range(0,8001,60):
        by=y-offset
        poly=[[x,by],[x+width,by],[x+width,by+height],[x,by+height]]
        nearest=min(union_distance([poly],svg.bodies(f))[0] for f in fs)
        if nearest>=clearance:
            m['yellowBands'].append(dict(id='G-opening',belowJump=3,source='P2',target=None,
                purpose='opening upward bypass brake',x=x,y=by,width=width,height=height,
                polygon=poly,nearestSolidClearance=nearest,minimumSolidClearance=clearance,
                role='non-solid, non-grappleable, pass-through braking'))
            return
    m['omittedOpeningBrake']='No legal full-width rectangle; require production shortcut validation of the separated route'


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
            if clearance < YELLOW_CLEARANCE:
                del bands[j if a['width']>=b['width'] else i]
                continue
            # Preserve both useful brakes when only their horizontal ends are
            # too close. Trimming cannot reduce clearance to green geometry.
            left,right=(a,b) if a['x']<=b['x'] else (b,a)
            new_width=right['x']-YELLOW_PAIR_CLEARANCE-left['x']
            if left['x']+left['width'] <= right['x'] and new_width>max(400,left['height']):
                left['trimmedFromWidth']=left['width']
                left['width']=new_width
                lx,ly=left['x'],left['y']
                left['polygon']=[[lx,ly],[lx+new_width,ly],[lx+new_width,ly+left['height']],[lx,ly+left['height']]]
                left['nearestSolidClearance']=min(union_distance([left['polygon']],svg.bodies(f))[0] for f in m['fragments'])
                continue
            # If a safe merge or trim is impossible, prioritize a corridor
            # guard over a decorative falling-area band, and record removal.
            ga,gb=bool(a.get('source')),bool(b.get('source'))
            drop=j if ga and not gb else i if gb and not ga else j if a['width']>=b['width'] else i
            m.setdefault('omittedYellowConflicts',[]).append(bands[drop]['id'])
            del bands[drop]


def add_final_transfer_brake(m, clearance):
    """Catch the tested roof-pump skip while leaving the underside descent open."""
    ceiling,slope,summit=m['fragments'][-3:]
    cx,cy,cr,cb=box(ceiling);sx,sy,sr,sb=box(slope);gx,gy,gr,gb=box(summit)
    left=max(sx-500,gr+1000);right=cx-clearance-10
    bottom=sy-clearance-1; height=min(1000,right-left-1)
    poly=[[left,bottom-height],[right,bottom-height],[right,bottom],[left,bottom]]
    nearest=min(union_distance([poly],svg.bodies(f))[0] for f in m['fragments'])
    if height<=0 or nearest<clearance:raise ValueError('No legal final transfer brake corridor')
    m['yellowBands'].append(dict(id='G-final',belowJump=len(m['fragments'])-2,source=ceiling['id'],target=summit['id'],
        purpose='roof-pump shortcut brake; underside descent remains below the zone',
        x=left,y=bottom-height,width=right-left,height=height,polygon=poly,
        nearestSolidClearance=nearest,minimumSolidClearance=clearance,
        role='non-solid, non-grappleable, pass-through braking'))


def restore_guard_coverage(m, clearance):
    """Restore a guard's ends after neighbouring bands were merged or removed."""
    fs={f['id']:f for f in m['fragments']}
    for band in m['yellowBands']:
        if band.get('source') not in fs:continue
        sx,sy,sr,sb=box(fs[band['source']])
        x,right=min(band['x'],sx-30),max(band['x']+band['width'],sr+30)
        y,h=band['y'],band['height']
        poly=[[x,y],[right,y],[right,y+h],[x,y+h]]
        nearest=min(union_distance([poly],svg.bodies(f))[0] for f in fs.values())
        if nearest<clearance:continue
        if any(other is not band and union_distance([poly],[other['polygon']])[0]<YELLOW_PAIR_CLEARANCE
               for other in m['yellowBands']):continue
        band.update(x=x,width=right-x,polygon=poly,nearestSolidClearance=nearest)


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
    text=text.replace('01–10: preserved baseline geometry', 'Opening 120% / 160% · vertical transfers 150%')
    text=text.replace('BASELINE PRESERVED', 'RELEASE JUMPS FROM THE START')
    text=text.replace('original 01–10 unchanged','opening gaps 120% / 160%; vertical gaps 150%')
    text=text.replace('Geometric checks exclude direct fragment-to-fragment grappling.', 'Opening and later transfers require release jumps.')
    text=text.replace('No nominal illustrated arc enters a band.', 'Fall-band paths require gameplay testing.')
    text=text.replace('All 300 fragment pairs > grapple + player diameter.', 'All consecutive panels are beyond grapple range.')
    lines=text.splitlines(True)
    (dest/'extended-mountain.svg').write_text(''.join(lines))
    (dest/'extended-mountain-measurements.json').write_text(json.dumps(m,separators=(',',':'))+'\n')
    print('Wrote',dest,'layout',m['layoutId'],'fragments',len(m['fragments']),'transfers',len(m['encounters']),'targets',OPENING_TARGETS if opening else TARGETS)

if __name__=='__main__':main()
