"""Retune a preserved concept measurement file; never modify the original."""
import argparse
import hashlib
import copy
import itertools
import json
import math
from pathlib import Path
from fractions import Fraction
from check_level_geometry import (COORD_TOL, MIN_INTERIOR_ANGLE, MIN_SIDE_LENGTH, interior_angles, point_segment,
                                  self_intersections, union_distance)
import convert_extended_mountain_svg as svg

TARGETS = {1: 80, 2: 80, 3: 150, 5: 150, 8: 150, 14: 150, 18: 150, 21: 150}
LAYOUT = 'extended-mountain-v5'
EXTENDED_LAYOUT = 'extended-mountain-v15'
# Shipped since TASK-687: every gameplay polygon side >= 0.5 R (scope all) and three purple encounters
# (NG1, NGM, NGU); since TASK-698 also the --purple-rest chutes (no rest inside a purple zone). Only the default
# CLI run (no layout flag) gets SHIPPED_LAYOUT; explicit flags and tune() keep EXTENDED_LAYOUT, so earlier
# candidates still reproduce byte for byte. `--no-purple-rest` without layout flags is the previous shipped v16.
# Since TASK-711 the shipped run also adds SEC-ext-summit (--ext-summit, three big zones above the old summit) as
# v18; `--no-ext-summit` without layout flags is the previous shipped v17.
# Since TASK-725 the shipped run lays SEC-ext-summit out inside the bottom run's x span (--ext-summit-riser,
# EXT_SUMMIT_RISER) as v19; `--no-ext-summit-riser` is the previous shipped v18 (extension beyond the left edge).
SHIPPED_LAYOUT = 'extended-mountain-v19'
EXT_SUMMIT_V18_LAYOUT = 'extended-mountain-v18'
PREVIOUS_SHIPPED_LAYOUT = 'extended-mountain-v17'
NO_REST_SHIPPED_LAYOUT = 'extended-mountain-v16'
SHIPPED_SCOPE = dict(min_side_scope='all', middle_purple=True, upper_purple=True)
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


def raise_opening_left_ledges(fs, rows):
    """Add up-left/up-left/down-left jumps without moving the later mountain.

    Keep the first leftward release gap and the departure/arrival turn panels.
    Moving only L1/L2 after fold placement prevents an opening edit from
    changing the purple chute or the upper route's calibrated geometry.
    """
    i = next(i for i, f in enumerate(fs) if f.get('semanticId') == 'L1')
    turn, first, second = fs[i-1:i+2]
    distance = gap(turn, first)[0]
    fs[i] = place_along(turn, first, -1, 0, distance,
                        origin=(turn['x'] - first['width'], first['y'] - 900))
    second['y'] -= 1440
    for k, text in ((i-1, 'UP-LEFT'), (i, 'UP-LEFT'), (i+1, 'DOWN-LEFT')):
        rows[k].update(direction=text, action=text + ' diagonal release jump')


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


def band_endpoints(m, number):
    """The fragments a band is centred under. A jump that a second purple encounter (TASK-682) moved to
    leave its exit ledge keeps its band under the original departure and the target before the shift."""
    a, b = [m['fragments'][i] for i in band_ends(m, number)]
    for e in purple_extensions(m)[1:]:
        if a['id'] == e['arrival'] and b['id'] != e['exit'] and any(
                r.get('originalNumber') == number and r['fromFragment'] == e['exit'] for r in m['encounters']):
            b = moved(b, -e['upperTranslation'][0], -e['upperTranslation'][1])
    return a, b


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
    # Raise only the rebound landings, preserving the x positions and the
    # ceiling/upper-route geometry. Reflowing the whole run moves ceilings
    # under later mountain panels and introduces upward bypasses.
    for f in added:
        f['y'] -= {'X2': 350, 'X5': 350, 'X9': 450}.get(f['semanticId'], 0)
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
# TASK-682 (candidate, opt-in via --middle-purple): a second purple encounter in
# the middle of the route, after the original chute and the normal grapple
# transfers S07-03 .. S08-01 that follow it. It starts at P7 (the arrival of the
# rightward S08-01, before the vertical S08-02) and is NG1's mirror image: an
# approach ledge right of P7, a 10R x 5R zone right of that holding NG1's slabs
# (and its post) reflected about the zone centre, at the same height below its
# approach, and an exit ledge copying P7 7500 to the right, so S08-02 and every
# later panel keep their geometry translated by +7500 (later falls stay above
# lower terrain). Bounces run rightward; the exit overhangs the zone's upper right.
# TASK-683 tuning (production-input shortcut probes): NGM's chute floor (NGM3) is a thin tapered slab
# (like the low ceiling) instead of NG1's 364-thick block. Its top face (the traversal contact), angle
# and extents are unchanged. A player rolling off NGM1's lower arm falls out of the zone onto P4 below
# at the capped fall speed, which rebounds it to a fixed apex about 4000 above P4 (y ~ -14410), under
# NGM3; with the underside 150 below the top (-14495) that apex no longer reaches it (the NGM1 -> NGM3
# skip). Rebuilt with tapered end caps in rebuild_purple_slabs (min-side scope all).
MIDDLE_PURPLE_THICKNESS = {'Chute floor': 150}
MIDDLE_SLAB_TAPER = ('Low ceiling', 'Chute floor', 'Launch ramp')
PURPLE_MIDDLE = dict(PURPLE, departure='P7', upId='S08-02', prefix='NGM', zoneId='NGM', mirror=True,
                     mirrorOf='NG1', shift=7500, label='Middle purple',
                     panels=[p[:5]+(MIDDLE_PURPLE_THICKNESS.get(p[0], p[5]),)+p[6:] for p in PURPLE['panels']],
                     purpose='Rightward rope-free bounce traversal (mirror of NG1) after S08-01, before the S08-02 climb')


# TASK-684 (candidate, opt-in via --upper-purple with --middle-purple): a third purple encounter higher and
# later, in the leftward upper run after NGM, separated from it by the normal grapple transfers S08-02 ..
# EXT-13. It starts at P13 (the arrival of the leftward EXT-13 rebound, before the EXT-14 ceiling hold) and
# runs leftward with NG1's unmirrored slabs and post (the middle encounter runs rightward, mirrored): an
# approach ledge left of P13, a 10R x 5R zone left of that at NG1's height below its approach, and an exit
# ledge copying P13 7500 to the left, so EXT-14 and every later panel keep their geometry translated by
# -7500 (the summit end then lies over the opening P2 .. R2, so late falls land on lower terrain).
# TASK-685 tuning (production-input shortcut probes): the exit keeps P13's left end and outline but is
# 1700 wide instead of 3300 (x scaled), so like NG-EXIT it no longer overhangs NGU1 .. NGU3. The full
# copy covered zone-top offsets 510 .. 3810: a capped-speed rebound off NGU3 landed on its top and a
# carried NGU1 state grappled its right end (13 skips). Its right end stays right of P14, so EXT-14 keeps
# its 810 vertical gap.
UPPER_EXIT_WIDTH = 1700
PURPLE_UPPER = dict(PURPLE, departure='P13', upId='EXT-14', prefix='NGU', zoneId='NGU', mirror=False,
                    copyOf='NG1', shift=-7500, label='Upper purple', exitWidth=UPPER_EXIT_WIDTH,
                    purpose='Leftward rope-free bounce traversal (NG1 orientation, opposite to NGM) after EXT-13, '
                            'before the EXT-14 ceiling hold')


# TASK-706 (template, fixture only via --big-zone-fixture): the big no-grapple zone, 5760 x 4320 world units
# (3/4 width x full height of the 1920 x 1080 logical viewport at the Grapple Over camera scale 0.25; fixed
# world units). Without a rope a bounce cannot gain net height, so the crossing is level or descending: the
# player runs off the approach ledge into the zone's upper left, bounces rope-free off green slabs
# (zone-local, PURPLE panel format; every top >= 15 deg for the no-rest rule, consecutive gaps <= 270,
# others > 540 + player diameter) and leaves through the right side above a lower exit ledge outside the zone.
# The approach top is y = 0 so the fixed SVG spawn (500, -30) stands on it; the zone top sits zoneAbove
# higher, so the run-off starts inside the zone.
# TASK-707 (v2): every surface the crossing uses stays above the production fall recovery (CLIMB_FALL_RECOVERY_DEPTH
# 1500 below the spawn, world y 1470); v1's staircase (exit top 2700) sent every crossing back to the spawn. A
# straight staircase cannot span 5760 at >= 15 deg inside that depth, so the slabs alternate tilt (negative =
# top rising to the right) and the elastic bounces keep the player's height: the recorded crossing
# (tools/fixtures/big-zone-inputs.json) runs off at full pull speed, bounces off NGB2 and NGB3 and leaves the
# right side above the exit ledge (top 342), where a fresh press grapples it.
BIG_ZONE_PANELS = [((918, 1579), 15.0, 525), ((2023, 1683), 15.0, 525), ((2941, 1580), -25.0, 300),
                   ((3833, 1379), 25.0, 375), ((4929, 1614), 20.0, 525)]
BIG_ZONE = dict(zone=(5760, 4320), zoneMargin=60, zoneAbove=600, approach=(1200, 260), exit=(1200, 260), exitTop=342,
                layoutId='big-zone-fixture-v2', zoneId='NGB', prefix='NGB', label='Big zone',
                panels=[('Bounce slab %d' % (i+1), contact, angle, extent, extent, 280, 1)
                        for i, (contact, angle, extent) in enumerate(BIG_ZONE_PANELS)])


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


def mirror_fragment(f, cx):
    """f reflected about the vertical line x = cx (vertex order reversed, so the winding is kept);
    applying it twice restores f, vertex order included."""
    w = f['width']
    g = dict(f, x=2*cx-f['x']-w, polys=[[[w-x, y] for x, y in poly[::-1]] for poly in f['polys']])
    if 'contactPoint' in f:
        g['contactPoint'] = [w-f['contactPoint'][0], f['contactPoint'][1]]
    if 'surfaceAngle' in f:
        g['surfaceAngle'] = -f['surfaceAngle']
    return g


def in_mirror(f, cx, op, *others):
    """Run op on f (and others) reflected about x = cx, then reflect f's new shape back; returns op's result."""
    g = mirror_fragment(f, cx)
    out = op(g, *[mirror_fragment(o, cx) for o in others])
    f.update(mirror_fragment(g, cx))
    return out


def purple_extensions(m):
    """Every purple encounter in route order (TASK-682); a layout with one keeps the singular key only."""
    return m.get('purpleExtensions') or ([m['purpleExtension']] if m.get('purpleExtension') else [])


def extend_purple_route(m, spec):
    """Insert one purple encounter after spec's departure (default: the original P4 / S07-03 chute).

    The chute (approach, zone, internal slabs, exit copying the departure) is
    built leftward; spec['mirror'] reflects the approach side, the zone and its
    slabs to the right of the departure (a rightward arrival) with a positive
    shift, so the internal geometry is the mirror image of NG1's. Every later
    panel moves by shift; ids, rows, combinations and earlier purple metadata
    are remapped."""
    fs, rows, route = m['fragments'], m['encounters'], m['routeMap']
    pre, zid, mirror = spec.get('prefix', 'NG'), spec.get('zoneId', 'NG1'), spec.get('mirror', False)
    k = next(i for i, f in enumerate(fs) if f['id'] == route['fragmentIds'][spec.get('departure', 'P4')])
    up = rows[k]
    if up['originalId'] != spec.get('upId', 'S07-03') or up['fromFragment'] != fs[k]['id']:
        raise ValueError('Purple extension expects the arrival before %s' % spec.get('upId', 'S07-03'))
    dep = fs[k]
    shift = spec['shift']
    side = 1 if mirror else -1
    if side*shift <= 0:
        raise ValueError('Purple shift must point to the chute side')
    label = spec.get('label', 'Purple')
    exit_ = dict(copy.deepcopy(dep), name='%s exit ledge' % label, x=dep['x']+shift, originalId=None, semanticId=pre+'-EXIT')
    if spec.get('exitWidth'):
        # A shorter exit copy (TASK-685): the departure's outline scaled along x from its left end.
        k_ = spec['exitWidth']/exit_['width']
        exit_['polys'] = [[[px*k_, py] for px, py in poly] for poly in exit_['polys']]
        exit_['width'] = spec['exitWidth']
    w, h = spec['approach']
    approach = dict(panel('%s approach ledge' % label, w, h, 0, 0), originalId=None, semanticId=pre+'-APPROACH')
    approach = place_along(dep, approach, side, 0, spec['approachGap'],
                           origin=(dep['x']+dep['width'] if mirror else dep['x']-w, dep['y']))
    # The zone ends just past the approach and starts just below the exit
    # ledge, which overhangs its far upper part: the player leaves through the top.
    zw, zh = spec['zone']
    zx = approach['x']+w+spec['zoneMargin'] if mirror else approach['x']-spec['zoneMargin']-zw
    zy = exit_['y']+exit_['height']+spec['zoneMargin']
    if 'zoneBelowApproach' in spec:
        # A mirrored copy keeps the original zone's height relative to its approach (the momentum entry).
        zy = approach['y']+spec['zoneBelowApproach']
    zone = dict(id=zid, x=zx, y=zy, width=zw, height=zh, polygon=[[zx, zy], [zx+zw, zy], [zx+zw, zy+zh], [zx, zy+zh]],
                purpose='no-grapple bounce chute: rope-free momentum traversal')
    if mirror:
        zone['mirrorOf'] = spec['mirrorOf']
    if spec.get('copyOf'):
        zone['copyOf'] = spec['copyOf']
    internal = []
    for n, (name, contact, angle, before, after, thickness, side_) in enumerate(spec['panels'], 1):
        f = purple_panel(name, slab(contact, angle, before, after, thickness, side_), contact,
                         'top' if side_ > 0 else 'underside', zx, zy)
        f.update(originalId=None, semanticId='%s%d' % (pre, n), surfaceAngle=angle)
        if mirror:
            f = mirror_fragment(f, zx+zw/2)
        if 'label' in spec:
            f['name'] = '%s %s' % (label, name[0].lower()+name[1:])
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
    way = 'RIGHT' if mirror else 'LEFT'
    extra = []
    for a, b in zip(chain, chain[1:]):
        if b is approach:
            rid, direction, action = pre+'-APPROACH', way, '%sward release jump to the %s approach ledge' % (
                way.capitalize(), label.lower())
        elif a is approach:
            rid, direction, action = pre+'-ENTRY', way+' → MOMENTUM ENTRY', 'Carry momentum into the no-grapple zone'
        elif b is exit_:
            rid, direction, action = pre+'-EXIT', 'UP → EXIT LEDGE', 'Launch out of the zone top, then grapple the exit ledge'
        else:
            rid, direction, action = '%s-%s-%s' % (pre, a['semanticId'], b['semanticId']), 'BOUNCE', \
                'Rope-free bounce off the %s %s' % (b['surface'], (b['name'][len(label)+1:] if 'label' in spec else b['name']).lower())
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
    remap = lambda v: [mapping.get(x, x) for x in v] if isinstance(v, list) else mapping.get(v, v)
    earlier = [{k_: remap(v) if k_ in ('arrival', 'approach', 'exit', 'internal', 'exitCopiesDeparture') else v
                for k_, v in e.items()} for e in purple_extensions(m)]
    new = dict(zone=zone['id'], arrival=dep['id'], approach=approach['id'], exit=exit_['id'],
               internal=[f['id'] for f in internal], encounters=[r['id'] for r in extra],
               upperTranslation=[shift, 0], exitCopiesDeparture=dep['id'],
               purpose=spec.get('purpose', 'Leftward rope-free bounce traversal after the first right -> up -> left sequence'))
    if not earlier:
        m['noGrappleZones'] = [zone]
        m['purpleExtension'] = new
        return
    # A second encounter (TASK-682): the singular keys stay the first encounter; the plural ones list all.
    new.update(prefix=pre, mirror=mirror, **{k_: spec[k_] for k_ in ('mirrorOf', 'copyOf') if k_ in spec},
               departureSemanticId=dep['semanticId'])
    m['noGrappleZones'] = m['noGrappleZones']+[zone]
    m['purpleExtension'] = earlier[0]
    m['purpleExtensions'] = earlier+[new]


def big_zone_level(spec=BIG_ZONE):
    """The BIG_ZONE encounter alone as a measurements dict (approach P0, internal slabs, exit summit)."""
    pre, label = spec['prefix'], spec['label']
    w, h = spec['approach']
    approach = dict(panel('%s approach ledge' % label, w, h, 0, 0), originalId=None, semanticId=pre+'-APPROACH')
    zw, zh = spec['zone']
    zx, zy = w+spec['zoneMargin'], -spec['zoneAbove']
    zone = dict(id=spec['zoneId'], x=zx, y=zy, width=zw, height=zh,
                polygon=[[zx, zy], [zx+zw, zy], [zx+zw, zy+zh], [zx, zy+zh]],
                purpose='big no-grapple zone: rope-free level-or-descending traversal')
    ew, eh = spec['exit']
    exit_ = dict(panel('%s exit ledge' % label, ew, eh, zx+zw+spec['zoneMargin'], spec['exitTop']), kind='summit',
                 originalId=None, semanticId=pre+'-EXIT')
    internal = []
    for n, (name, contact, angle, before, after, thickness, side_) in enumerate(spec['panels'], 1):
        f = purple_panel('%s %s' % (label, name[0].lower()+name[1:]), slab(contact, angle, before, after, thickness, side_),
                         contact, 'top' if side_ > 0 else 'underside', zx, zy)
        f.update(originalId=None, semanticId='%s%d' % (pre, n), surfaceAngle=angle)
        internal.append(f)
    for f in [approach, exit_]:
        if union_distance(svg.bodies(f), [zone['polygon']])[0] <= 0:
            raise ValueError('%s must lie outside the big zone' % f['semanticId'])
    for f in internal:
        if not zone_contains(zone, f):
            raise ValueError('%s must lie completely inside the big zone' % f['semanticId'])
    if exit_['y'] < approach['y']:
        raise ValueError('A rope-free big-zone crossing cannot leave higher than it enters')
    fs = [approach]+internal+[exit_]
    for i, f in enumerate(fs):
        f['id'] = 'P%d' % i
    rows = []
    for i, (a, b) in enumerate(zip(fs, fs[1:]), 1):
        if a is approach:
            rid, action = pre+'-ENTRY', 'Run off the approach ledge into the big no-grapple zone'
        elif b is exit_:
            rid, action = pre+'-EXIT', 'Bounce out of the zone side onto the lower exit ledge'
        else:
            rid, action = '%s-%s-%s' % (pre, a['semanticId'], b['semanticId']), 'Rope-free bounce down to the next slab'
        rows.append(dict(id=rid, number=i, fromFragment=a['id'], toFragment=b['id'], direction='RIGHT', action=action,
                         baseline=False, originalNumber=None, originalId=None, percent=None,
                         noGrappleZone=zone['id'] if a in internal and b in internal else None))
    m = dict(layoutId=spec['layoutId'], grappleRange=svg.R, fragments=fs, encounters=rows, yellowBands=[],
             noGrappleZones=[zone], fallIllustrations=[], combinations=[],
             bigZone=dict(zone=zone['id'], approach=approach['id'], internal=[f['id'] for f in internal], exit=exit_['id'],
                          size=[zw, zh], viewport=[1920, 1080], cameraScale=0.25))
    measure_transfers(m, None)
    return m


def write_big_zone_fixture(dest, spec=BIG_ZONE):
    """--big-zone-fixture: SVG, measurements, imported level JSON and leveldata-style JS for BIG_ZONE alone."""
    import import_level_svg
    m = big_zone_level(spec)
    svg.LAYOUT_ID = m['layoutId']
    text = svg.build(m)
    level = import_level_svg.import_svg(text.encode())
    (dest/'big-zone.svg').write_text(text)
    (dest/'big-zone-measurements.json').write_text(json.dumps(m, separators=(',', ':'))+'\n')
    payload = import_level_svg.dumps(level)
    (dest/'big-zone.level.json').write_text(payload)
    (dest/'big-zone.level.js').write_text('// Generated by tools/retune_extended_level.py --big-zone-fixture; do not edit.\n'
                                          'window.GRAPPLE_OVER_BUNDLED_LEVEL = '+payload.rstrip()+';\n')
    print('Wrote big-zone fixture', dest, 'layout', m['layoutId'], 'fragments', len(m['fragments']),
          'transfers', len(m['encounters']), 'elements', len(level['elements']))


# TASK-708 (candidate, opt-in via --ext-summit on the shipped run): SEC-ext-summit above the old summit. The old
# summit (P61) becomes an ordinary landing; three grapple climbs, each a translated copy of the shipped final chain
# (EXT-21 .. EXT-24: vertical commitment, ceiling hold, release, bounce onto a summit-shaped landing, +4181), lead
# into the big zones BZ1 .. BZ3 (BIG_ZONE template: approach ledge approachGap past the landing at its height, the
# zone and its lower exit ledge), each zone running in its last climb's direction (leftward = mirrored template).
# After BZ1 / BZ2 two climbs (+8362) lead to the next zone. TASK-708 zigzagged them (rightward back over the zone,
# then leftward); TASK-710's shortcut matrix found that stacking skippable (pumps from a lower climb or an approach
# reach the climb above), so every climb now runs leftward and nothing is stacked over an earlier panel or zone; the
# b climbs sit 1700 left like C1. zoneFacingOffset moves the first panel after a zone (and all after it) by (dx, dy).
# A release jump from BZ3's exit reaches the new summit (finish) at the exit's height. climbShifts moves a climb sideways from its start: C1 sits 1700
# left so its first panel keeps the 300% yellow clearance from G-final (the roof-pump brake right of the old summit). Every new panel keeps > 540 + player diameter
# from every other panel and margin from every zone it does not belong to.
EXT_SUMMIT = dict(chain=('P20', 'P21', 'P22', 'P23', 'P24'), climbs=((-1,), (-1, -1), (-1, -1)), climbShifts=((-1700,), (0, -1700), (0, -1700)),
                  zoneFacingFirst=(False, True, True), zoneFacingOffset=(0, 0),
                  # TASK-710: the last slab tilts 30 deg (template 20) so a high drop onto it bounces into the exit
                  # ledge's side instead of over it onto the next climb / the summit (shortcut matrix highDrop skips).
                  zoneSlabs={5: ('Bounce slab 5', BIG_ZONE_PANELS[4][0], 30.0, 525, 525, 280, 1)},
                  approachGap=1350, finishGap=1350,
                  zoneClearance=600, section='SEC-ext-summit', prefix='XS', zones=('BZ1', 'BZ2', 'BZ3'))


def ext_summit_climb(chain, start, direction, shift=0):
    """Copies of chain[1:] placed so chain[0] coincides with start's top edge (leftward = shipped orientation)."""
    c0 = chain[0]
    if direction > 0:
        cx = c0['x']+c0['width']/2
        chain = [mirror_fragment(f, cx) for f in chain]
        for f in chain:
            f['bounceSign'] = -f['bounceSign']
        c0 = chain[0]
        dx = start['x']+start['width']-(c0['x']+c0['width'])
    else:
        dx = start['x']-c0['x']
    return [moved(copy.deepcopy(f), dx+shift, start['y']-c0['y']) for f in chain[1:]]


def ext_summit_zone(landing, direction, n, spec=EXT_SUMMIT):
    """The BIG_ZONE template (approach, slabs, exit) past landing, in direction; returns (fragments, zone)."""
    panels = [spec['zoneSlabs'].get(k, p) for k, p in enumerate(BIG_ZONE['panels'], 1)]
    t = big_zone_level(dict(BIG_ZONE, zoneId=spec['zones'][n-1], prefix=spec['zones'][n-1], label='Big zone %d' % n, panels=panels))
    fs, zone = [copy.deepcopy(f) for f in t['fragments']], copy.deepcopy(t['noGrappleZones'][0])
    if direction < 0:
        fs = [mirror_fragment(f, 0) for f in fs]
        zone['x'] = -zone['x']-zone['width']
        dx = landing['x']-spec['approachGap']
    else:
        dx = landing['x']+landing['width']+spec['approachGap']
    fs = [moved(f, dx, landing['y']) for f in fs]
    zone['x'] += dx; zone['y'] += landing['y']
    x, y, w, h = zone['x'], zone['y'], zone['width'], zone['height']
    zone['polygon'] = [[x, y], [x+w, y], [x+w, y+h], [x, y+h]]
    zone['purpose'] = 'big no-grapple zone %s (SEC-ext-summit): rope-free level-or-descending traversal' % zone['id']
    fs[-1]['kind'] = 'platform'
    return fs, zone


# TASK-723 (candidate, --ext-summit-fold): the same extension refolded inside the bottom run's x span
# (FOLD_X_RANGE) so a failed jump lands on lower geometry instead of beside the map. The old summit is at the
# left end of the map, so every section runs rightward twice and back leftward once into its zone (3 climbs a
# section): each zone then sits over the previous section, about 632 right of the zone below it. Each big-zone unit
# (approach, slabs, exit, zone) is the v18 unit moved RIGIDLY by a pure whole-unit translation (units[n] = (dx, dy),
# recorded in extSummit.units; the approach gap is 1350 +- 0.5), so the TASK-709 crossing inputs only need their aims shifted; the climbs are untranslated
# re-laid copies of the shipped chain (rightward = mirrored). The new summit keeps its v18 place relative to BZ3.
# climbShifts: C1a 600 left keeps 1621 from G-final; the b / c climbs move 1900 / 900 right (their first panel still
# overlaps the start ledge above it), so each section drifts right (unshifted ~1068 left per section), the C2a / C3a
# first panels and the summit stay inside, and no drop point sits over a column the main level leaves empty.
# C2a / C3a are unshifted, so their first panel is the v18 copy facing the exit ledge (ext-summit-inputs aims).
# catchShelves: one flat body under C1b (hosted by XS-C1b-3, > 540 + player diameter from every panel) spans the
# columns where the main level has nothing at any height (x 13965..15184, 16438..18243, 20638..21352), so a drop
# from the lowest section lands there instead of the void.
FOLD_X_RANGE = (-1100, 62534)
EXT_SUMMIT_FOLD = dict(EXT_SUMMIT, climbs=((1, 1, -1),)*3, climbShifts=((-600, 1900, 900), (0, 1900, 900), (0, 1900, 900)),
                       zoneFacingFirst=(False, False, False), rigidUnits=True,
                       catchShelves=(('XS-C1b-3', 13700, 21600, -34500, 300),))


# TASK-724 (candidate, --ext-summit-riser): the fold of TASK-723 stacked every leftward return climb within a pump's
# reach (~5200) of the rightward climb under it (shortcut matrix: 368 SKIPs), and with chain climbs every such
# reversal does at any shift. So the extension now turns once: five rightward climbs along the bottom to the right end
# of the map (C1a 600 left as before; each later first panel 2300 right of the chain's right alignment, so it is clear
# of the previous climb's a-3 bounce panel, which otherwise launches the player straight onto it), then a RISER TURN:
# the turn climb's first panel (C1f-1, 1600 right, clear of that bounce too) is copied 5000 straight up (C1f-1R, its lowest point more than a
# pump's reach above the landing below), and the leftward rest of the climb starts from that copy. Then everything
# runs leftward as in v18: BZ1, one climb (its first panel the v18 copy facing the exit ledge, a-2..a-4 2000 nearer
# to it), BZ2, one climb, BZ3, the summit. Each big-zone unit is the v18 unit moved rigidly by whole-unit (dx, dy)
# (extSummit.units), 750 nearer its landing (approach release jump 600). Catch shelves (flat bodies of XS-C1a-1, so
# a landing on one is a fall back, never a skip) cover the columns where the bottom run has nothing under it; a drop
# off either shelf end lands on the main level. Chosen by artifacts/TASK-724/sweep (calibrated stacking predictor:
# 0 conflicts, 0 predicted void drops).
# TASK-725: the rightward run starts with a riser too (C1a-1R, 5000 above C1a-1), so C1a-2..4 are more than a pump's
# reach above the last main-level climb P18..P24 that runs leftward under them (from P21 / P22 the whole-route matrix
# skipped onto C1a-4 / C1a-3), and the two shelves over P17..P20 sit at -37500 (at -34500 P18 pumped onto one).
EXT_SUMMIT_RISER = dict(EXT_SUMMIT, climbs=((1,)*5+(-1,), (-1,), (-1,)), climbShifts=((-600,)+(2300,)*4+(1600,), (0,), (0,)),
                        zoneFacingFirst=(False, True, True), rigidUnits=True, risers={(1, 0): (0, -5000), (1, 5): (0, -5000)},
                        unitShifts=(750, 750, 750), offsets={(2, 0): (2000, 0), (3, 0): (2000, 0)},
                        catchShelves=(('XS-C1a-1', 3506, 4306, -36500, 300), ('XS-C1a-1', 13935, 18237, -37500, 300), ('XS-C1a-1', 20369, 21387, -37500, 300)))


def add_catch_shelf(f, x0, x1, top, thickness):
    """Extra flat body (absolute x0..x1, top, thickness) on fragment f: catches drops where nothing lies below."""
    f['polys'] = f['polys']+[[[x0-f['x'], top-f['y']], [x1-f['x'], top-f['y']], [x1-f['x'], top+thickness-f['y']],
                              [x0-f['x'], top+thickness-f['y']]]]


def rigid_moved(f, dx, dy):
    """f moved by (dx, dy) with its polygons rebased on its absolute points, so each moved absolute point
    (x + px) is exactly the original absolute point + (dx, dy) wherever that sum is a double, and that sum
    correctly rounded elsewhere (TASK-724: a unit moved into a coarser binade)."""
    g = moved(copy.deepcopy(f), dx, dy)

    def rebased(origin, old_origin, p, d):
        want = float(Fraction(old_origin+p)+Fraction(d))
        q = (old_origin+p)-old_origin
        if origin+q == want:
            return q
        q = want-origin
        for _ in range(8):
            if origin+q == want:
                return q
            q = math.nextafter(q, math.inf if origin+q < want else -math.inf)
        raise ValueError('no rebased offset reaches the correctly rounded moved point')
    g['polys'] = [[[rebased(g['x'], f['x'], px, dx), rebased(g['y'], f['y'], py, dy)] for px, py in poly] for poly in f['polys']]
    return g


def extend_summit(m, spec=EXT_SUMMIT):
    # A spec with rigidUnits moves each big-zone unit of the EXT_SUMMIT (v18) extension rigidly behind its landing.
    reference = extend_summit(copy.deepcopy(m)) if spec.get('rigidUnits') else None
    fs, rows = m['fragments'], m['encounters']
    by_sem = {f.get('semanticId'): f for f in fs}
    chain = [copy.deepcopy(by_sem[s]) for s in spec['chain']]
    old = fs[-1]
    if old['kind'] != 'summit':
        raise ValueError('The extension starts at the current summit')
    old['kind'] = 'platform'
    pre, new, zones, steps, units = spec['prefix'], [], [], [], []
    start = old
    zone_of = {}
    for n, directions in enumerate(spec['climbs'], 1):
        for c, direction in enumerate(directions):
            if c == 0 and spec['zoneFacingFirst'][n-1]:
                # The first panel after a zone keeps the TASK-708 rightward (mirrored) copy, which faces the exit
                # ledge (tools/fixtures/ext-summit-inputs-BZn.json aim at its underside); the rest runs leftward
                # from it, so no climb is stacked over an earlier climb, approach or zone (TASK-710 shortcuts).
                first = moved(ext_summit_climb(chain, start, 1)[0], *spec['zoneFacingOffset'])
                climb = ext_summit_climb(chain, start, direction)
                climb = [first]+[moved(f, first['x']-climb[0]['x'], first['y']-climb[0]['y']) for f in climb[1:]]
            else:
                climb = ext_summit_climb(chain, start, direction, spec['climbShifts'][n-1][c])
            ox, oy = spec.get('offsets', {}).get((n, c), (0, 0))
            climb = climb[:1]+[moved(f, ox, oy) for f in climb[1:]]
            for k, f in enumerate(climb, 1):
                f.update(name='%s climb %d%s %s' % (pre, n, 'abcdefgh'[c], f['name']), originalId=None, kind=f['kind'] if k < 4 else 'platform',
                         semanticId='%s-C%d%s-%d' % (pre, n, 'abcdefgh'[c], k))
            if (n, c) in spec.get('risers', {}):
                # Riser turn: a second copy of the climb's first panel, (dx, dy) from it, and the rest of the climb
                # re-based on it, so the return climb runs over the climb below more than a pump's reach higher.
                rx, ry = spec['risers'][(n, c)]
                riser = moved(copy.deepcopy(climb[0]), rx, ry)
                riser.update(name=climb[0]['name']+' riser', semanticId=climb[0]['semanticId']+'R')
                climb = [climb[0], riser]+[moved(f, rx, ry) for f in climb[1:]]
            steps += [(f, 'climb %d' % n) for f in climb]
            start = climb[-1]
        for host, x0, x1, top, thick in spec.get('catchShelves', ()) if n == 1 else ():
            add_catch_shelf(next(f for f, _ in steps if f['semanticId'] == host), x0, x1, top, thick)
        zfs, zone = ext_summit_zone(start, directions[-1], n)
        if reference:
            ref = {f['semanticId']: f for f in reference['fragments']}
            rz = next(z for z in reference['noGrappleZones'] if z['id'] == zone['id'])
            land = reference['fragments'][[f['semanticId'] for f in reference['fragments']].index(zfs[0]['semanticId'])-1]
            # Whole-unit offsets: the moved points keep their fractional digits, so the imported unit equals v18 + (dx, dy).
            dx, dy = float(round(start['x']-land['x'])), float(round(start['y']-land['y']))
            # unitShifts moves a unit toward (+, for a leftward zone) its landing: a shorter release jump.
            dx += float(spec.get('unitShifts', (0, 0, 0))[n-1])*(1 if directions[-1] < 0 else -1)
            zfs = [rigid_moved(ref[f['semanticId']], dx, dy) for f in zfs]
            zone = dict(copy.deepcopy(rz), x=rz['x']+dx, y=rz['y']+dy, polygon=[[x+dx, y+dy] for x, y in rz['polygon']])
            units.append(dict(zone=zone['id'], dx=dx, dy=dy, fragments=[f['semanticId'] for f in zfs]))
        steps += [(f, zone['id']) for f in zfs]
        zone_of.update({id(f): zone['id'] for f in zfs[1:-1]})
        zones.append(zone); start = zfs[-1]
    summit = copy.deepcopy(chain[-1]); summit.update(name='%s summit' % pre, originalId=None, semanticId=pre+'-SUMMIT', kind='summit')
    summit = moved(summit, (start['x']-spec['finishGap']-summit['width'] if spec['climbs'][-1][-1] < 0
                            else start['x']+start['width']+spec['finishGap'])-summit['x'], start['y']-summit['y'])
    steps.append((summit, 'finish'))
    first = len(fs)
    for i, (f, _) in enumerate(steps):
        f['id'] = 'P%d' % (first+i)
    zone_of = {f['id']: zone_of[id(f)] for f, _ in steps if id(f) in zone_of}
    numbers = []
    prev = old
    for f, part in steps:
        number = len(rows)+1
        za, zb = zone_of.get(prev['id']), zone_of.get(f['id'])
        sem_a, sem_b = prev.get('semanticId'), f['semanticId']
        if za and za == zb:
            rid, action = '%s-%s-%s' % (za, sem_a, sem_b), 'Rope-free bounce to the next slab'
        elif zb:
            rid, action = zb+'-ENTRY', 'Run off the approach ledge into big no-grapple zone '+zb
        elif za:
            rid, action = za+'-EXIT', 'Bounce out of the zone side onto the lower exit ledge'
        elif f['semanticId'].endswith('-APPROACH'):
            rid, action = f['semanticId'], 'Release jump onto the big-zone approach ledge'
        elif part == 'finish':
            rid, action = pre+'-FINISH', 'Release jump onto the new summit'
        else:
            rid, action = sem_b, 'Grapple climb %s' % part
        d, w, _, _ = gap(prev, f)
        rows.append(dict(id=rid, number=number, fromFragment=prev['id'], toFragment=f['id'],
                         direction='RIGHT' if f['x'] > prev['x'] else 'LEFT', action=action, baseline=False,
                         originalNumber=None, originalId=None, percent=round(d/5.4, 2), distance=d, witness=w,
                         flight=[svg.contact(prev), svg.contact(f)], noGrappleZone=za if za and za == zb else None))
        numbers.append(number)
        fs.append(f); prev = f
    m['noGrappleZones'] = m['noGrappleZones']+zones
    close = ['%s/%s %.0f' % (f['id'], z['id'], d) for z in zones for f in fs if zone_of.get(f['id']) != z['id']
             for d in [union_distance(svg.bodies(f), [z['polygon']])[0]]
             if d < (60 if (f.get('semanticId') or '').startswith(z['id']+'-') else spec['zoneClearance'])]
    close += ['%s/%s overlap' % (a['id'], b['id']) for a, b in itertools.combinations(m['noGrappleZones'], 2)
              if union_distance([a['polygon']], [b['polygon']])[0] <= 0]
    close += ['%s/%s yellow %.0f' % (f['id'], b['id'], d) for b in m['yellowBands'] for f, _ in steps
              for d in [union_distance(svg.bodies(f), [b['polygon']])[0]] if d < b['nearestSolidClearance']]
    if close:
        raise ValueError('Panels too close to a big zone or yellow band: '+', '.join(close))
    m['namedSections'] = [dict(id=spec['section'], encounters=numbers)]
    m['extSummit'] = dict(oldSummit=old['id'], oldFinishTop=old['y']-svg.FINISH_PAD[1], summit=summit['id'],
                          finishTop=summit['y']-svg.FINISH_PAD[1], zones=[z['id'] for z in zones],
                          fragments=[f['id'] for f, _ in steps], encounters=[rows[n-1]['id'] for n in numbers])
    if units:
        m['extSummit'].update(units=units, xRange=list(FOLD_X_RANGE))
    m['pairChecks'] = []
    for i, a in enumerate(fs):
        for b in fs[i+1:]:
            d = gap(a, b)[0]
            m['pairChecks'].append(dict(source=a['id'], target=b['id'], minimumGap=d, passOutsideRange=d-21.6 > 540))
    return m


def measure_transfers(m, opening):
    fs = m['fragments']
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


def tune(source, reposition=True, guards=True, opening=None, yellow_clearance=LEGACY_YELLOW_CLEARANCE, min_sides=None,
         middle_purple=False, upper_purple=False, purple_rest=False):
    if purple_rest and min_sides != 'all':
        raise ValueError('The purple rest retilt rebuilds the slabs of min-side scope all')
    if upper_purple and not middle_purple:
        raise ValueError('The upper purple encounter follows the middle one')
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
        raise_opening_left_ledges(fs, m['encounters'])
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
        if middle_purple:
            z1, a1 = m['noGrappleZones'][0], next(f for f in fs if f['semanticId'] == 'NG-APPROACH')
            extend_purple_route(m, dict(PURPLE_MIDDLE, zoneBelowApproach=z1['y']-a1['y']))
            if upper_purple:
                extend_purple_route(m, dict(PURPLE_UPPER, zoneBelowApproach=z1['y']-a1['y']))
        add_shortcut_shields(m, SHIELDS)
        if min_sides in ('opening', 'all'):
            resize_opening_sides(m)
    measure_transfers(m, opening)
    placed_bands, kept, unreachable = [], [], []
    for band in m['yellowBands']:
        # A split original jump keeps its band centred between its original endpoints.
        a,b = band_endpoints(m, band['belowJump'])
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
    # TASK-682: the middle chute above P4 makes P4 a guard source; guards keep clear of the later P4 shield.
    reserved = planned_shield_bodies(m) if opening and min_sides in ('opening', 'all') and middle_purple else ()
    if guards and opening:
        add_shortcut_guards(m, yellow_clearance, reserved)
    elif guards:
        add_legacy_shortcut_guards(m, yellow_clearance)
    if opening:
        add_opening_brake(m, yellow_clearance)
        add_final_transfer_brake(m, yellow_clearance)
    consolidate_yellow_bands(m, yellow_clearance, reserved)
    if opening:
        restore_guard_coverage(m, yellow_clearance, reserved)
    if min_sides in ('opening', 'all'):
        add_opening_min_side_shields(m, yellow_clearance, MIDDLE_PURPLE_SHIELDS if middle_purple else OPENING_MIN_SIDE_SHIELDS)
        if middle_purple:
            narrow_from_left(m, 'L2', MIDDLE_L2_LEFT_CUT, 'NGM5')
            extend_middle_zone_right(m)
    if min_sides == 'all':
        resize_later_sides(m, opening, yellow_clearance, purple_rest=purple_rest)
        deepen_yellow_bands(m, yellow_clearance)
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
    post, posts = None, []
    for ext, zone in zip(purple_extensions(m), m.get('noGrappleZones', [])):
        sid, width, height = spec['post']
        sid = ext.get('prefix', 'NG')+sid[2:]
        f = by[sid]
        if ext.get('mirror'):
            # The mirrored chute gets NG1's post reflected: added on the reflected slab, then reflected back.
            cx = zone['x']+zone.get('mirrorWidth', zone['width'])/2
            made = in_mirror(f, cx, lambda g: add_post(g, width, height))
            made = dict(foot=[2*cx-made['foot'][0], made['foot'][1]], top=made['top'], mirroredAbout=cx)
        else:
            made = add_post(f, width, height)
        posts.append(dict(fragment=f['id'], semanticId=sid, width=width, height=height, **made))
        if not zone_contains(zone, f):
            raise ValueError('%s post must stay inside the purple zone' % sid)
    post = posts[0] if posts else None
    m['shortcutShields'] = dict(fins=fins, trim=dict(fragment=by[spec['trim'][0]]['id'], semanticId=spec['trim'][0],
                                                       trimmedLeft=trim), post=post,
                                purpose='TASK-677: block demonstrated skips beneath R1, short of R4 onto X1 and over NG1')
    if len(posts) > 1:
        m['shortcutShields']['posts'] = posts


# TASK-679 (candidate, opt-in via --min-side-scope opening): every edge of the
# opening green bodies (P0 .. the first leftward arrival P4, with R1's fin and
# X1's trim) reaches MIN_SIDE_LENGTH (0.5 R = 270). Short sides are lengthened
# along their own lines ('extend': (anchor, moving) vertex pairs scaled by one
# common factor, so a trapezoid's bottom stays level); the contact faces, the
# vertex or edge line carrying each transfer's gap witness, and so every
# measured transfer gap stay as they were. P2's 147-unit stem cannot hold three
# 270 underside edges within its 820 width, so P2 becomes a slab ('slab'): the
# same top, a right side of the given depth and a left corner at local x that
# slides down until the gap to its route predecessor equals the previous gap.
# SIDE_TARGET leaves margin above the checker's 270 - 0.01 threshold.
SIDE_TARGET = 275.0
OPENING_MIN_SIDES = [('P0', 'extend', [(1, 2), (0, 3)]),
                     ('P1', 'extend', [(0, 3)]),
                     ('P2', 'slab', dict(depth=300, cornerX=40)),
                     ('R3', 'extend', [(0, 3), (1, 2)]),
                     ('L1', 'extend', [(0, 3), (1, 2)]),
                     ('P4', 'extend', [(1, 2)])]


def opening_scope(m):
    """Fragments from the spawn to the first leftward arrival (route P4), in route order."""
    fs = m['fragments']
    end = next(i for i, f in enumerate(fs) if f['id'] == m['routeMap']['fragmentIds']['P4'])
    return fs[:end+1]


def short_sides(fragment, minimum=MIN_SIDE_LENGTH):
    return [dict(body=k, edge=e, length=math.dist(a, b)) for k, poly in enumerate(fragment['polys'])
            for e, (a, b) in enumerate(zip(poly, poly[1:]+poly[:1])) if math.dist(a, b) < minimum-COORD_TOL]


def resize_opening_sides(m, spec=OPENING_MIN_SIDES, target=SIDE_TARGET):
    fs = m['fragments']
    by = {f['semanticId']: f for f in fs}
    index = {f['id']: i for i, f in enumerate(fs)}
    changed = []
    for sid, op, arg in spec:
        f = by[sid]
        before, height = copy.deepcopy(f['polys']), f['height']
        poly = [list(p) for p in f['polys'][0]]
        if op == 'extend':
            scale = max(target/math.dist(poly[a], poly[b]) for a, b in arg)
            for a, b in arg:
                poly[b] = [poly[a][0]+(poly[b][0]-poly[a][0])*scale, poly[a][1]+(poly[b][1]-poly[a][1])*scale]
        else:
            prev = fs[index[f['id']]-1]
            keep = gap(prev, f)[0]
            w, x = f['width'], arg['cornerX']
            lo, hi = 0., 2000.
            for _ in range(80):
                mid = (lo+hi)/2
                probe = dict(f, polys=[[[0, 0], [w, 0], [w, arg['depth']], [x, mid]]])
                if gap(prev, probe)[0] > keep: lo = mid
                else: hi = mid
            poly = [[0, 0], [w, 0], [w, arg['depth']], [x, lo]]
        f['polys'] = [poly]+f['polys'][1:]
        f['height'] = max(y for body in f['polys'] for _, y in body)
        if min(interior_angles(poly)) < MIN_INTERIOR_ANGLE or self_intersections(poly):
            raise ValueError('%s resize breaks the corner rules' % sid)
        changed.append(dict(fragment=f['id'], semanticId=sid, op=op, before=before, after=copy.deepcopy(f['polys']),
                            heightBefore=height, heightAfter=f['height']))
    short = [dict(fragment=f['id'], semanticId=f['semanticId'], sides=s) for f in opening_scope(m) for s in [short_sides(f)] if s]
    if short:
        raise ValueError('Opening edges below %g: %s' % (MIN_SIDE_LENGTH, short))
    m['minimumSides'] = dict(scope='opening', minimum=MIN_SIDE_LENGTH, target=target,
                             fragments=[f['id'] for f in opening_scope(m)], changed=changed,
                             purpose='TASK-679: opening green edges >= 0.5 R; later bodies are migrated separately')


# TASK-680 (candidate only, with --min-side-scope opening): the opening probe grid
# showed a fast pumped release from L2's right end flying ~2400 above P4's top
# and landing first on NG-APPROACH, skipping P4 (the same flight exists in v15).
# The shield is a second P4 body hanging high above P4 (fragment-local x0..x1
# from P4's left end, top..bottom relative to P4's top) where that arc peaks;
# the intended low arcs (L2 -> P4 descending onto P4 from the right, P4 ->
# NG-APPROACH with an apex near -700) pass well below it. It is added after the
# yellow bands are placed, so no band moves: every band must stay at least the
# yellow clearance away. Every side is >= 270 and no transfer gap changes.
OPENING_MIN_SIDE_SHIELDS = [('P4', 298, 578, -2708, -2358)]
# TASK-686 (with --middle-purple): the whole-route matrix on the three-zone
# candidate showed 5-pump vertical bounces from P4 (.5/.8) and L2 (.8) rising
# ~6200 into the NGM encounter, which hangs above them: P4 struck NGM3's
# underside, L2 grappled NGM5 on the way up or struck P8's underside. P4 keeps
# its TASK-680 shield and gains a second, higher one right of it over the .8
# column (the 3-pump apex, 2195 above the top, stays below both; the 4-pump
# bounce, which reached NGM3, strikes it). It sits just below the NGM zone
# (nothing but the slabs may touch the zone) and its lower-right corner is as
# far right as the L2 -> P4 gap allows. Contacts with it are contacts with P4.
MIDDLE_PURPLE_SHIELDS = OPENING_MIN_SIDE_SHIELDS + [('P4', 500, 770, -3103, -2833)]
# L2 cannot be shielded: any body above its left part comes within the L2 -> P4
# gap of P4's shields or the grapple range of NGM5, and a shield over its right
# part becomes a rope anchor that swings the player left under the zone onto
# NGM5 or over P4. Bounces from L2's left part are already safe: they rise into
# the NGM zone, which drops the rope, so pumping stalls near the 3-pump apex.
# The NGM zone therefore extends right (away from its approach, past L2's right
# end) so the whole of L2 lies under it. Its slabs, approach, exit and NG1
# mirror frame (the unextended width) are unchanged; nothing else lies in the
# added strip. L2's left part also lay under NGM5's underside, only 2350 .. 2600
# above it, which a 300 drop and 2 pumps from L2 .2 (rising ~3500 even under
# the zone) struck: L2 also loses its left 560 (left half of its outline moves
# right; its right end stays), so nothing lies above it lower than P8 (5640).
# Only the L2 -> P4 gap grows.
MIDDLE_ZONE_EXTEND_RIGHT = 550
MIDDLE_L2_LEFT_CUT = 560


def planned_shield_bodies(m, spec=OPENING_MIN_SIDE_SHIELDS):
    by = {f['semanticId']: f for f in m['fragments']}
    return [[[by[sid]['x']+x, by[sid]['y']+y] for x, y in [[x0, top], [x1, top], [x1, bottom], [x0, bottom]]]
            for sid, x0, x1, top, bottom in spec]


def add_opening_min_side_shields(m, clearance, spec=OPENING_MIN_SIDE_SHIELDS):
    fs = m['fragments']
    by = {f['semanticId']: f for f in fs}
    shields = []
    for sid, x0, x1, top, bottom in spec:
        f = by[sid]
        before = [gap(a, b)[0] for a, b in zip(fs, fs[1:])]
        f['polys'] = f['polys']+[[[x0, top], [x1, top], [x1, bottom], [x0, bottom]]]
        body = [[f['x']+x, f['y']+y] for x, y in f['polys'][-1]]
        if short_sides(f) or [gap(a, b)[0] for a, b in zip(fs, fs[1:])] != before:
            raise ValueError('%s shield must keep sides >= %g and every transfer gap' % (sid, MIN_SIDE_LENGTH))
        bands = []
        for band in m['yellowBands']:
            d = union_distance([band['polygon']], [body])[0]
            if d < clearance:
                raise ValueError('%s shield is %.1f from yellow band %s' % (sid, d, band['id']))
            if d < band['nearestSolidClearance']:
                band['nearestSolidClearance'] = d
                bands.append(band['id'])
        # Pair clearances were measured before the bands; re-measure this fragment's pairs.
        moved = []
        for row in m['pairChecks']:
            if f['id'] in (row['source'], row['target']):
                other = next(g for g in fs if g['id'] == (row['target'] if row['source'] == f['id'] else row['source']))
                d = gap(f, other)[0]
                if d - 21.6 <= 540:
                    raise ValueError('%s shield brings %s within grapple range' % (sid, other['semanticId']))
                if abs(d - row['minimumGap']) > 1e-9:
                    moved.append(other['semanticId'])
                row.update(minimumGap=d, passOutsideRange=d-21.6 > 540)
        shields.append(dict(fragment=f['id'], semanticId=sid, body=len(f['polys'])-1, pairsWithNewMinimumGap=moved, localX=[x0, x1], localY=[top, bottom],
                            world=body, nearestYellowClearance=min(union_distance([b['polygon']], [body])[0]
                                                                   for b in m['yellowBands']),
                            bandsWithNewNearestSolid=bands))
    m['minimumSides']['shields'] = dict(bodies=shields, purpose='TASK-680: block the demonstrated L2 -> NG-APPROACH '
                                        'flight over P4 found by the candidate opening probe grid')
    if spec is MIDDLE_PURPLE_SHIELDS:
        m['minimumSides']['shields']['middlePurple'] = ('TASK-686: a second P4 shield (body 2) against the demonstrated '
                                                        '5-pump P4 bounces into NGM3; L2 is narrowed and covered by the NGM zone '
                                                        'extension')


def narrow_from_left(m, sid, cut, clear_of):
    fs = m['fragments']
    f = next(g for g in fs if g['semanticId'] == sid)
    before = [gap(a, b)[0] for a, b in zip(fs, fs[1:])]
    old = dict(x=f['x'], width=f['width'], polys=copy.deepcopy(f['polys']))
    f['polys'] = [[[x, y] if x < f['width']/2 else [x-cut, y] for x, y in poly] for poly in f['polys']]
    f['x'] += cut
    f['width'] -= cut
    after = [gap(a, b)[0] for a, b in zip(fs, fs[1:])]
    if short_sides(f) or any(d < d0-COORD_TOL for d, d0 in zip(after, before)):
        raise ValueError('%s narrowing must keep sides >= %g and not shorten a transfer gap' % (sid, MIN_SIDE_LENGTH))
    other = next(g for g in fs if g['semanticId'] == clear_of)
    right = max(x for b in svg.bodies(other) for x, _ in b)
    if f['x'] <= right:
        raise ValueError('%s must lie right of %s (%.1f <= %.1f)' % (sid, clear_of, f['x'], right))
    m['minimumSides']['narrowedFromLeft'] = dict(
        fragment=f['id'], semanticId=sid, cut=cut, before=old, x=f['x'], width=f['width'], clearOf=clear_of,
        clearance=f['x']-right, grownTransferGaps={fs[i+1]['semanticId'] if fs[i] is f else fs[i]['semanticId']: [before[i], after[i]]
                                                   for i in range(len(fs)-1) if abs(after[i]-before[i]) > COORD_TOL},
        purpose='TASK-686: L2 no longer lies under NGM5 (L2 .2 drop-300 2-pump bounces struck its underside)')


def extend_middle_zone_right(m, extend=MIDDLE_ZONE_EXTEND_RIGHT, under='L2'):
    zone = next(z for z in m['noGrappleZones'] if z['id'] == 'NGM')
    width = zone['width']+extend
    poly = [[zone['x'], zone['y']], [zone['x']+width, zone['y']], [zone['x']+width, zone['y']+zone['height']],
            [zone['x'], zone['y']+zone['height']]]
    strip = [[zone['x']+zone['width'], zone['y']]]+poly[1:3]+[[zone['x']+zone['width'], zone['y']+zone['height']]]
    for f in m['fragments']:
        if union_distance(svg.bodies(f), [strip])[0] <= 0:
            raise ValueError('%s lies in the NGM zone extension' % f['semanticId'])
    for band in m['yellowBands']:
        if union_distance([band['polygon']], [strip])[0] <= 0:
            raise ValueError('yellow band %s lies in the NGM zone extension' % band['id'])
    l2 = next(f for f in m['fragments'] if f['semanticId'] == under)
    if not (zone['x'] < l2['x'] and l2['x']+l2['width'] < zone['x']+width):
        raise ValueError('%s must lie under the extended NGM zone' % under)
    zone.update(mirrorWidth=zone['width'], extendedRight=extend, width=width, polygon=poly)
    zone['extension'] = dict(strip=strip, under=under, underRightMargin=zone['x']+width-(l2['x']+l2['width']),
                             purpose='TASK-686: L2 lies under the NGM zone, so its pumped bounces lose the rope '
                                     'before NGM5/P8 (the demonstrated 5-pump .8 skips)')


# TASK-681 (candidate only, with --min-side-scope all): every remaining gameplay
# polygon edge reaches MIN_SIDE_LENGTH. The end caps of purple chute slabs that
# were too thin (NG2 Low ceiling 149, NG5 Launch ramp 202) tilt inward until
# they are SIDE_TARGET long: the same contact face, contact point, angle and
# thickness, and the new slab lies inside the old one, so no gap or clearance
# shrinks (thickening would bring NG5 within 1620 of yellow band G2). NG1's
# post keeps its left face and top-left corner (the route drops just left of
# it; widening left lands the player on the post) and widens right to the
# slab's lower-right corner, its top sloping down just enough that the entry
# gap from the approach (whose witness was the post's top-right) stays. Later green bodies and the exit ledge (a copy of P4, so the
# same P4 resize) lengthen short underside sides along their own lines
# ('extend-each': each (anchor, moving) pair scaled on its own), take an
# explicit underside ('set'), or ('tangent') turn the vertex that carries the
# gap witness of the transfer from the route predecessor about the witness
# point on the predecessor (downward), so the gap stays. Top faces are unchanged. Yellow bands thinner
# than the target deepen away from their nearest solid (kept >= the clearance).
LATER_SLAB_TAPER = ('Low ceiling', 'Launch ramp')
LATER_MIN_SIDES = [('NG-EXIT', 'extend-each', [(1, 2)]),
                   ('P7', 'extend-each', [(0, 3)]),
                   ('NGM-EXIT', 'extend-each', [(0, 3)]),  # TASK-682: the middle exit copies P7
                   ('NGU-EXIT', 'extend-each', [(0, 4)]),  # TASK-684: the upper exit copies P13
                   ('P9', 'set', [[0, 0], [980, 0], [980, 275], [372.4, 275], [372.4, 550], [0, 550]]),
                   ('P13', 'extend-each', [(0, 4)]),
                   ('P16', 'extend-each', [(0, 4), (1, 2)]),
                   ('P17', 'extend-each', [(0, 4)]),
                   ('P20', 'extend-each', [(0, 4)]),
                   ('P24', 'tangent', (1, 2))]


def tapered_slab(contact, angle, before, after, thickness, side, target=SIDE_TARGET):
    """slab() whose end caps lean inward to length target; the contact face is unchanged."""
    a, b, c, d = slab(contact, angle, before, after, thickness, side)[::side]
    ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    s = math.sqrt(max(0., target**2-thickness**2))
    poly = [a, b, (c[0]-ux*s, c[1]-uy*s), (d[0]+ux*s, d[1]+uy*s)]
    return poly if side > 0 else poly[::-1]


def wide_post(f, width, height, approach, keep, target=SIDE_TARGET):
    """add_post() whose top runs right to the slab's lower-right corner, sloping down until the
    entry gap from the approach equals keep; the post's left face and top-left corner stay."""
    pts = [(f['x']+x, f['y']+y) for x, y in f['polys'][0]]
    a, b, c, d = pts
    if f['surface'] != 'top' or not b[1] < a[1] or not b[0] > a[0]+width:
        raise ValueError('%s post needs a top face rising to the right' % f['semanticId'])
    t = (b[0]-width-a[0])/(b[0]-a[0])
    foot = (b[0]-width, a[1]+(b[1]-a[1])*t)
    tl = (foot[0], b[1]-height)
    cx, cy = f['x']+f['contactPoint'][0], f['y']+f['contactPoint'][1]
    def shape(drop):
        q = [a, foot, tl, (c[0], tl[1]+drop), c, d]
        x0, y0 = min(p[0] for p in q), min(p[1] for p in q)
        return dict(f, x=x0, y=y0, width=max(p[0] for p in q)-x0, height=max(p[1] for p in q)-y0,
                    contactPoint=[cx-x0, cy-y0], polys=[[[px-x0, py-y0] for px, py in q]])
    lo, hi = 0., c[1]-tl[1]-target
    if gap(approach, shape(hi))[0] < keep:
        raise ValueError('%s wide post cannot keep the entry gap' % f['semanticId'])
    for _ in range(100):
        mid = (lo+hi)/2
        if gap(approach, shape(mid))[0] < keep: lo = mid
        else: hi = mid
    g = shape(hi)
    poly = g['polys'][0]
    if short_sides(g) or min(interior_angles(poly)) < MIN_INTERIOR_ANGLE or self_intersections(poly):
        raise ValueError('%s wide post breaks the side or corner rules' % f['semanticId'])
    f.update({k: g[k] for k in ('x', 'y', 'width', 'height', 'contactPoint', 'polys')})
    return dict(foot=list(foot), top=tl[1], topRight=[c[0], tl[1]+hi], width=c[0]-foot[0], entryGap=keep)


# TASK-696 (candidate, opt-in via --purple-rest): no upward face inside a purple zone may be flatter than
# 15 deg (check_level_geometry.py --no-grapple-rest), so a ninja can never come to rest there. NG1's three flat
# tops (and their NGM mirror / NGU copy) are retilted: the Low ceiling and Overhang keep their underside (the
# traversal contact) and left end cap, and their top rises rightward from the top-left corner at
# PURPLE_REST_ANGLE over the same x extent; the Chute floor turns to -PURPLE_REST_FLOOR_TURN about the face point
# PURPLE_REST_PIVOT along the face from its contact foot (contact rotated with it, same extents and thickness),
# then moves by PURPLE_REST_SHIFT. Already-steep faces (kicker, post top, end caps) are unchanged.
# TASK-697 re-route: TASK-696's floor (left end down, (-420, -40)) cannot be traversed. The ball leaves the Low
# ceiling descending ~12 deg, shallower than the floor, so it only ever meets the floor's right cap and bounces
# back (artifacts/TASK-697/search/search.py, rsearch.py: no production approach input gets past NG3). The floor now
# rises leftward (right end down, drains toward the zone bottom right of NG2) and kicks the ball up ~42 deg into
# the Overhang's underside, which turns it down onto a flatter Launch ramp that throws it up out of the zone
# under the exit ledge. PURPLE_REST_PANELS moves the contact (dx, dy), turns the surface angle and trims /
# extends the extents (before, after) of the Low ceiling (left end trimmed, so the Overhang can reach right
# under the floor's rebound while keeping the 540 + diameter pair clearance), the Overhang (raised and tilted
# left end up, shorter at the left and longer at the right) and the Launch ramp (33.5 -> 25.64 deg, raised,
# left end trimmed so the NG-EXIT transfer keeps its 1080 minimum).
# Every chain gap stays in (0, 270] (NG1 -> NG2 258, NG2 -> NG3 248, NG3 -> NG4 255, NG4 -> NG5 232) and every
# other pair >= 570 apart. Found by a joint search over these offsets with the production replay
# (artifacts/TASK-697/search/geo3.py, sample.py, grid3.py, evalp.py).
PURPLE_REST_ANGLE = 15.5
PURPLE_REST_TOPS = ('Low ceiling', 'Overhang')
PURPLE_REST_FLOOR = 'Chute floor'
PURPLE_REST_FLOOR_TURN = -PURPLE_REST_ANGLE
PURPLE_REST_PIVOT = 422.5
PURPLE_REST_SHIFT = (-5.16, 72.61)
# name: (contact offset, angle change, before change, after change), NG1 frame.
PURPLE_REST_PANELS = {'Low ceiling': ((-121.92, -32.92), 0.4, -255.89, 0),
                      'Overhang': ((67.88, -363.45), 9.27, -416.89, 146.72),
                      'Launch ramp': ((200.0, -630.0), -7.86, -460, 0)}
# Shortcut-matrix fixes (production-input neighbourhood matrices around NG1 / NGM / NGU, TASK-697). With tops
# rising rightward, high drops onto the Low ceiling slid or bounced left onto the raised Overhang's ~860 tall
# right end or into NG-EXIT, and the Overhang's top sat ~350 under the exit ledge: both tops fall rightward instead
# (PURPLE_REST_DOWN_TOPS, from the top-left corner at PURPLE_REST_ANGLE, draining right toward the zone bottom),
# thicker at the left cap so the right cap keeps the 270 minimum side (PURPLE_REST_THICKNESS). The Low ceiling's
# tall left cap leans out PURPLE_REST_LEFT_OVERHANG past its underside, so a high floor rebound striking it turns
# down instead of up toward the exit ledge (100 keeps it 540 + diameter from the Overhang).
PURPLE_REST_DOWN_TOPS = ('Low ceiling', 'Overhang')
PURPLE_REST_THICKNESS = {'Low ceiling': 550, 'Overhang': 410}
PURPLE_REST_LEFT_OVERHANG = {'Low ceiling': 100}
# The re-routed player leaves the zone top rising steeply about 1300 .. 1450 right of the zone's left edge (NG1
# frame), just right of NG-EXIT's lower right corner. NGU-EXIT (P13's outline at 1700 wide) and NGM-EXIT (P7's
# copy, inner end at 1437 .. 1560 in NG1's frame) hang over that path, so the player struck their underside and
# fell back in. PURPLE_REST_EXIT_WIDTHS rescales the outlines in x (unmirrored from the left end, NGM from its
# outer, right end); NG-EXIT and NGU-EXIT at 900 also keep a vertical rebound off the Overhang's top clear of
# their lower right corner. NGU-EXIT then grows PURPLE_REST_EXIT_GROW at its outer (left) end: a high drop off
# NGU5 carried onto the short ledge rolled off its left end and roped P15 before the EXT-14 hold P14. At 900 wide
# its lower right side is shorter than 270 and is extended like NG-EXIT's (PURPLE_REST_MIN_SIDES).
PURPLE_REST_EXIT_WIDTHS = {'NG-EXIT': 900, 'NGU-EXIT': 900, 'NGM-EXIT': 790}
PURPLE_REST_EXIT_GROW = {'NGU-EXIT': 400}
PURPLE_REST_MIN_SIDES = [('NGU-EXIT', 'extend-each', [(1, 2)])]
# NGM3 only: the turned floor's low end reached over P4's pump columns below the middle zone, where five-pump
# rebounds off P4 (apex ~4230 above its top) struck it (TASK-683 / TASK-686 skip P4 -> NGM3). It is 400 shorter
# at that end (PURPLE_REST_MIDDLE_TRIM_AFTER, NG1 frame) and 200 thick; NGM2 -> NGM3 becomes 260 (NG1's 248).
PURPLE_REST_MIDDLE_THICKNESS = {'Chute floor': 200}
PURPLE_REST_MIDDLE_TRIM_AFTER = {'Chute floor': 400}


def rest_floor(contact, angle, before, after, thickness, side, pivot=None, shift=None, rest=None):
    """(contact, angle) of a top slab turned to -rest (default PURPLE_REST_FLOOR_TURN: right end down) about the
    face point pivot units along the face from the contact foot, then moved by shift."""
    pivot = PURPLE_REST_PIVOT if pivot is None else pivot
    shift = PURPLE_REST_SHIFT if shift is None else shift
    rest = PURPLE_REST_FLOOR_TURN if rest is None else rest
    ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    fx, fy = contact[0]-uy*svg.PLAYER_RADIUS, contact[1]+ux*svg.PLAYER_RADIUS
    px, py = fx+ux*pivot, fy+uy*pivot
    t = math.radians(-rest-angle)
    rx, ry = contact[0]-px, contact[1]-py
    return (px+rx*math.cos(t)-ry*math.sin(t)+shift[0], py+rx*math.sin(t)+ry*math.cos(t)+shift[1]), -rest


def rest_top(poly, rest=PURPLE_REST_ANGLE, down=False, overhang=0):
    """Underside slab [top-left, top-right, under-right, under-left] whose top rises (down: falls) rightward at
    rest from the top-left corner (moved overhang further left; the right corner keeps its x); the underside is
    unchanged."""
    d, c, b, a = poly
    d = (d[0]-overhang, d[1])
    c = (c[0], d[1]+(c[0]-d[0])*math.tan(math.radians(rest))*(1 if down else -1))
    if c[1] >= b[1]:
        raise ValueError('rest top meets the underside')
    return [d, c, b, a]


def rebuild_purple_slabs(m, by, purple_rest=False):
    """Rebuild the thin chute slabs with tapered end caps and NG1 with the wide post (each purple
    encounter; a mirrored one is rebuilt reflected, then reflected back). purple_rest also retilts the
    flat tops (TASK-696)."""
    out = []
    posts = m.get('shortcutShields', {}).get('posts') or [m.get('shortcutShields', {}).get('post')]
    for ext, zone, post_meta in zip(purple_extensions(m), m.get('noGrappleZones', []), posts):
        pre = ext.get('prefix', 'NG')
        cx = zone['x']+zone.get('mirrorWidth', zone['width'])/2  # the NG1 mirror frame (TASK-686 extends NGM)
        panels, taper = (PURPLE_MIDDLE['panels'], MIDDLE_SLAB_TAPER) if ext.get('mirror') else (PURPLE['panels'], LATER_SLAB_TAPER)
        for n, (name, contact, angle, before, after, thickness, side) in enumerate(panels, 1):
            sid = '%s%d' % (pre, n)
            post = 'NG%d' % n == SHIELDS['post'][0] and bool(post_meta)
            rest = purple_rest and name in PURPLE_REST_TOPS+(PURPLE_REST_FLOOR,)+tuple(PURPLE_REST_PANELS)
            if name not in taper and not post and not rest:
                continue
            f = by[sid]
            polys, height, x0, y0, width = copy.deepcopy(f['polys']), f['height'], f['x'], f['y'], f['width']
            angle0 = f.get('surfaceAngle')
            if rest and name in PURPLE_REST_PANELS:
                (dx, dy), turn, grow_before, grow_after = PURPLE_REST_PANELS[name]
                contact, angle = (contact[0]+dx, contact[1]+dy), angle+turn
                before, after = before+grow_before, after+grow_after
                thickness = PURPLE_REST_THICKNESS.get(name, thickness)
            if rest and ext.get('mirror'):
                thickness = PURPLE_REST_MIDDLE_THICKNESS.get(name, thickness)
                after -= PURPLE_REST_MIDDLE_TRIM_AFTER.get(name, 0)
            if rest and name == PURPLE_REST_FLOOR:
                contact, angle = rest_floor(contact, angle, before, after, thickness, side)
            shape = (tapered_slab if name in taper else slab)(contact, angle, before, after, thickness, side)
            if rest and name in PURPLE_REST_TOPS:
                shape = rest_top(shape, down=name in PURPLE_REST_DOWN_TOPS,
                                 overhang=PURPLE_REST_LEFT_OVERHANG.get(name, 0))
            g = purple_panel(name, shape, contact, 'top' if side > 0 else 'underside', zone['x'], zone['y'])
            if rest:
                g['surfaceAngle'] = angle
            if ext.get('mirror'):
                g = mirror_fragment(g, cx)
            f.update({k: g[k] for k in ('x', 'y', 'width', 'height', 'contactPoint', 'polys')})
            if rest:
                f['surfaceAngle'] = g['surfaceAngle']
            if post:
                approach = by[pre+'-APPROACH']
                keep = gap(approach, dict(f, polys=polys, x=x0, y=y0))[0]
                if ext.get('mirror'):
                    made = in_mirror(f, cx, lambda g, a: wide_post(g, SHIELDS['post'][1], SHIELDS['post'][2], a, keep),
                                     approach)
                    made.update(foot=[2*cx-made['foot'][0], made['foot'][1]],
                                topRight=[2*cx-made['topRight'][0], made['topRight'][1]], mirroredAbout=cx)
                    made['topLeft'] = made.pop('topRight')
                else:
                    made = wide_post(f, SHIELDS['post'][1], SHIELDS['post'][2], approach, keep)
                post_meta.update(made)
            if not zone_contains(zone, f):
                raise ValueError('%s must stay inside the purple zone' % sid)
            out.append(dict(fragment=f['id'], semanticId=sid, op='post' if post else 'rest' if rest else 'taper', before=polys,
                            after=copy.deepcopy(f['polys']), heightBefore=height, heightAfter=f['height'],
                            boxBefore=[x0, y0, width, height], thickness=thickness,
                            **({'restAngle': PURPLE_REST_ANGLE, 'surfaceAngleBefore': angle0,
                                'taper': name in taper} if rest else {})))
    return out


def rest_exit_ledges(m, by):
    """TASK-697: PURPLE_REST_EXIT_WIDTHS (x-scaled outlines; a mirrored encounter keeps its outer, right end),
    then PURPLE_REST_EXIT_GROW moves an unmirrored ledge's left end further left."""
    out = []
    mirrored = {e.get('prefix', 'NG')+'-EXIT' for e in purple_extensions(m) if e.get('mirror')}
    for sid, width in PURPLE_REST_EXIT_WIDTHS.items():
        if sid not in by:
            continue
        f = by[sid]
        before, box0 = copy.deepcopy(f['polys']), [f['x'], f['y'], f['width'], f['height']]
        k = width/f['width']
        if sid in mirrored:
            f['polys'] = [[[f['width']-(f['width']-px)*k, py] for px, py in poly] for poly in f['polys']]
            x0 = min(px for poly in f['polys'] for px, _ in poly)
            f['polys'] = [[[px-x0, py] for px, py in poly] for poly in f['polys']]
            f['x'] += x0
        else:
            grow = PURPLE_REST_EXIT_GROW.get(sid, 0)
            f['polys'] = [[[px*k+grow if px else 0., py] for px, py in poly] for poly in f['polys']]
            f['x'] -= grow
            width += grow
        f['width'] = width
        out.append(dict(fragment=f['id'], semanticId=sid, op='rest-exit', before=before,
                        after=copy.deepcopy(f['polys']), heightBefore=f['height'], heightAfter=f['height'],
                        boxBefore=box0, widthAfter=width))
    return out


def resize_later_sides(m, opening, clearance, spec=LATER_MIN_SIDES, target=SIDE_TARGET, purple_rest=False):
    """Runs after the bands are placed, so no band moves; transfers and pairs are re-measured."""
    fs = m['fragments']
    by = {f['semanticId']: f for f in fs}
    before_rows = {r['id']: (r['distance'], r['witness']) for r in m['encounters']}
    changed = rebuild_purple_slabs(m, by, purple_rest)
    if purple_rest:
        changed += rest_exit_ledges(m, by)
        spec = spec+PURPLE_REST_MIN_SIDES
    # A layout generated without the purple extension (tests) has no exit ledge.
    for sid, op, arg in [e for e in spec if e[0] in by]:
        f = by[sid]
        before, height, box0 = copy.deepcopy(f['polys']), f['height'], [f['x'], f['y'], f['width'], f['height']]
        poly = [list(p) for p in f['polys'][0]]
        if op == 'extend-each':
            for a, b in arg:
                scale = max(1., target/math.dist(poly[a], poly[b]))
                poly[b] = [poly[a][0]+(poly[b][0]-poly[a][0])*scale, poly[a][1]+(poly[b][1]-poly[a][1])*scale]
        elif op == 'tangent':
            a, b = arg
            prev = fs[fs.index(f)-1]
            keep, (w, v) = gap(prev, f)[:2]
            if math.dist(v, (f['x']+poly[b][0], f['y']+poly[b][1])) > 1e-6:
                raise ValueError('%s tangent vertex must carry the gap witness' % sid)
            # Rotate the vertex about the predecessor's witness point (downward), so the gap is exact.
            rx, ry = v[0]-w[0], v[1]-w[1]
            turn = 1 if rx*0-ry*-1 < 0 else -1
            def at(t):
                c, sn = math.cos(t*turn), math.sin(t*turn)
                return [w[0]+rx*c-ry*sn-f['x'], w[1]+rx*sn+ry*c-f['y']]
            if at(.01)[1] < poly[b][1]:
                turn = -turn
            lo, hi = 0., math.pi/4
            for _ in range(80):
                mid = (lo+hi)/2
                if math.dist(poly[a], at(mid)) < target: lo = mid
                else: hi = mid
            poly[b] = [round(v, 9) for v in at(hi)]  # independent of the route's translation
        else:
            if arg[:2] != poly[:2]:
                raise ValueError('%s explicit underside must keep the top face' % sid)
            poly = [list(p) for p in arg]
        f['polys'] = [poly]+f['polys'][1:]
        f['height'] = max(y for body in f['polys'] for _, y in body)
        if min(interior_angles(poly)) < MIN_INTERIOR_ANGLE or self_intersections(poly):
            raise ValueError('%s resize breaks the corner rules' % sid)
        changed.append(dict(fragment=f['id'], semanticId=sid, op=op, before=before, after=copy.deepcopy(f['polys']),
                            heightBefore=height, heightAfter=f['height'], boxBefore=box0))
    short = [dict(fragment=f['id'], semanticId=f['semanticId'], sides=s) for f in fs for s in [short_sides(f)] if s]
    if short:
        raise ValueError('Edges below %g: %s' % (MIN_SIDE_LENGTH, short))
    measure_transfers(m, opening)
    moved = [dict(id=r['id'], before=before_rows[r['id']][0], after=r['distance'],
                  witnessBefore=before_rows[r['id']][1], witnessAfter=r['witness'])
             for r in m['encounters'] if abs(r['distance']-before_rows[r['id']][0]) > 1e-6]
    for band in m['yellowBands']:
        band['nearestSolidClearance'] = min(union_distance([band['polygon']], svg.bodies(f))[0] for f in fs)
        if band['nearestSolidClearance'] < clearance:
            raise ValueError('Resize brings green within %.1f of yellow band %s' % (band['nearestSolidClearance'], band['id']))
    m['minimumSides'].update(scope='all', fragments=[f['id'] for f in fs], laterChanged=changed, transfersChanged=moved,
                             slabTaper=list(LATER_SLAB_TAPER),
                             purpose='TASK-679/680/681: every gameplay polygon edge >= 0.5 R')
    if any(e.get('mirror') for e in purple_extensions(m)):
        m['minimumSides'].update(middleSlabTaper=list(MIDDLE_SLAB_TAPER), middleThickness=MIDDLE_PURPLE_THICKNESS)


def deepen_yellow_bands(m, clearance, target=SIDE_TARGET):
    """Thicken drag bands below target away from their nearest solid; keep solid and pair clearances."""
    fs, bands, changed = m['fragments'], m['yellowBands'], []
    for band in bands:
        if band['height'] >= target:
            continue
        x, y, w, h = band['x'], band['y'], band['width'], band['height']
        grow = target-h
        best = None
        # Down (keep top), up (keep bottom), centred; a band squeezed between
        # solids loses the fewest units from one end (at most 5% of its width).
        for trim in range(0, int(w*.05)+1, 5):
            for dy in (0., -grow, -grow/2):
                for left, right in {(trim, 0), (0, trim)}:
                    poly = [[x+left, y+dy], [x+w-right, y+dy], [x+w-right, y+dy+target], [x+left, y+dy+target]]
                    nearest = min(union_distance([poly], svg.bodies(f))[0] for f in fs)
                    pair = min((union_distance([poly], [o['polygon']])[0] for o in bands if o is not band),
                               default=math.inf)
                    if nearest >= clearance and pair >= YELLOW_PAIR_CLEARANCE and (best is None or nearest > best[1]):
                        best = (dy, nearest, poly, left, right)
            if best:
                break
        if best is None:
            raise ValueError('Cannot deepen yellow band %s to %g' % (band['id'], target))
        dy, nearest, poly, left, right = best
        changed.append(dict(id=band['id'], before=[x, y, w, h], after=[x+left, y+dy, w-left-right, target],
                            grew='down' if dy == 0 else 'up' if dy == -grow else 'both', trimmed=[left, right],
                            nearestSolidBefore=band['nearestSolidClearance'], nearestSolidAfter=nearest))
        band.update(x=x+left, y=y+dy, width=w-left-right, height=target, polygon=poly, nearestSolidClearance=nearest)
    m['minimumSides']['yellowBands'] = changed


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


def add_shortcut_guards(m, clearance=LEGACY_YELLOW_CLEARANCE, reserved=()):
    """reserved: bodies added after the bands (the TASK-680 shields) that guards must also clear."""
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
                if reserved and union_distance([poly],list(reserved))[0]<clearance: continue
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


def consolidate_yellow_bands(m, clearance=LEGACY_YELLOW_CLEARANCE, reserved=()):
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
        if reserved and union_distance([poly],list(reserved))[0]<clearance:
            nearest=-1  # TASK-682: a merge may not reach the later P4 shield either
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


def restore_guard_coverage(m, clearance, reserved=()):
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
        if reserved and union_distance([poly],list(reserved))[0]<clearance:continue
        if any(other is not band and union_distance([poly],[other['polygon']])[0]<YELLOW_PAIR_CLEARANCE
               for other in m['yellowBands']):continue
        band.update(x=x,width=right-x,polygon=poly,nearestSolidClearance=nearest)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',help='concept measurements JSON (required unless --big-zone-fixture)')
    ap.add_argument('--output-dir',required=True)
    ap.add_argument('--guidelines', default=str(GUIDELINES), help='Required current design guidelines')
    ap.add_argument('--opening', choices=('extended', 'original'), default='extended',
                    help='extended: threefold rightward/leftward opening (guidelines); original: the v5 layout')
    # No layout flag at all = the shipped level (SHIPPED_SCOPE). Any explicit flag leaves the unspecified ones at
    # their pre-TASK-687 values (none / off), so earlier candidate commands still reproduce their candidates.
    ap.add_argument('--min-side-scope', choices=('none', 'opening', 'all'), default=None,
                    help='opening: candidate with opening green edges >= 0.5 R (TASK-679); all: every gameplay '
                         'polygon edge (TASK-681); none: the v15 layout. Default (no layout flags): shipped v18 = all')
    ap.add_argument('--middle-purple', action=argparse.BooleanOptionalAction, default=None,
                    help='add the second (middle) purple no-grapple encounter NGM after S08-01 (TASK-682); shipped')
    ap.add_argument('--purple-rest', action=argparse.BooleanOptionalAction, default=None,
                    help='retilt the flat tops in every purple zone to >= 15 deg (TASK-696/697; needs min-side scope '
                         'all). Not a layout flag. Default: on for the shipped run, off with explicit layout flags; '
                         '--no-purple-rest without layout flags gives v16')
    ap.add_argument('--upper-purple', action=argparse.BooleanOptionalAction, default=None,
                    help='(with --middle-purple) add the third (upper) purple encounter NGU after EXT-13 (TASK-684); shipped')
    ap.add_argument('--big-zone-fixture', action='store_true',
                    help='write only the BIG_ZONE encounter template as a fixture level (TASK-706); --source is ignored')
    ap.add_argument('--ext-summit', action=argparse.BooleanOptionalAction, default=None,
                    help='add SEC-ext-summit (three big zones, new finish 8640+ higher) above the old summit (TASK-708/'
                         '710); only with the default shipped layout flags and --purple-rest. Default: on for the shipped '
                         'v19 run; --no-ext-summit without layout flags gives the previous shipped v17')
    ap.add_argument('--ext-summit-riser', action=argparse.BooleanOptionalAction, default=None,
                    help='(with --ext-summit) SEC-ext-summit inside FOLD_X_RANGE with one riser turn (no stacked '
                         'return climbs), big-zone units moved rigidly (TASK-724). Default: on (shipped v19) unless '
                         '--ext-summit-fold; --no-ext-summit-riser gives the previous shipped v18')
    ap.add_argument('--ext-summit-fold', action='store_true',
                    help='(with the shipped run) candidate: SEC-ext-summit refolded inside FOLD_X_RANGE, big-zone units '
                         'moved rigidly (TASK-723)')
    args=ap.parse_args()
    if args.big_zone_fixture:
        dest=Path(args.output_dir); dest.mkdir(parents=True,exist_ok=True)
        return write_big_zone_fixture(dest)
    if not args.source:
        ap.error('--source is required')
    explicit=(args.min_side_scope, args.middle_purple, args.upper_purple) != (None, None, None)
    shipped = not explicit and args.opening == 'extended'
    if shipped:
        args.min_side_scope, args.middle_purple, args.upper_purple = (SHIPPED_SCOPE[k] for k in SHIPPED_SCOPE)
    args.min_side_scope=args.min_side_scope or 'none'
    args.purple_rest = shipped if args.purple_rest is None else args.purple_rest
    args.ext_summit = shipped and args.purple_rest if args.ext_summit is None else args.ext_summit
    if args.ext_summit_riser is None:
        args.ext_summit_riser = args.ext_summit and not args.ext_summit_fold
    args.middle_purple=bool(args.middle_purple); args.upper_purple=bool(args.upper_purple)
    if args.upper_purple and not args.middle_purple:
        raise ValueError('--upper-purple needs --middle-purple')
    if args.middle_purple and args.opening != 'extended':
        raise ValueError('--middle-purple needs the extended opening')
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
    m=tune(json.loads(Path(args.source).read_text()), opening=opening, yellow_clearance=clearance,
         min_sides=None if args.min_side_scope == 'none' else args.min_side_scope, middle_purple=args.middle_purple,
         upper_purple=args.upper_purple, purple_rest=args.purple_rest)
    if shipped:
        m['layoutId']=(((SHIPPED_LAYOUT if args.ext_summit_riser else EXT_SUMMIT_V18_LAYOUT) if args.ext_summit
                        else PREVIOUS_SHIPPED_LAYOUT) if args.purple_rest else NO_REST_SHIPPED_LAYOUT)
    if args.ext_summit:
        if not (shipped and args.purple_rest):
            raise ValueError('--ext-summit extends the v17 layout (default flags with --purple-rest) only')
        if args.ext_summit_fold and args.ext_summit_riser:
            raise ValueError('--ext-summit-fold and --ext-summit-riser are alternatives')
        extend_summit(m, EXT_SUMMIT_FOLD if args.ext_summit_fold else EXT_SUMMIT_RISER if args.ext_summit_riser else EXT_SUMMIT)
    elif args.ext_summit_fold or args.ext_summit_riser:
        raise ValueError('--ext-summit-fold / --ext-summit-riser need --ext-summit')
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
