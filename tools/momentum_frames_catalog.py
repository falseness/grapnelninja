"""Convert the picked momentum concept frames to a W-unit catalog (TASK-102).

Reads artifacts/momentum-frames/catalog.json (frame px, the only geometry
source) and writes {unit:'W', frames:[...]} as compact JSON to --out.
1 W = the interior width of the corridor a piece sits in = 480 frame px.

Anchors: 'right' x = (px - anchorX)/480 along, y = (py - 315)/480 across;
'down' x = (px - 315)/480 across, y = (py - anchorY)/480 along; anchorX/Y =
smallest piece edge - 48 (0.1 W), span = (largest edge + 48 - anchor)/480.
'up' = the down frame flipped along the shaft (y' = span - y). Corners are
relative to the course vertex (x scales by the shaft W, y by the corridor W).
Piece x, y are centres (polygons: vertex centroid, points relative to it);
motion {axis, min, max} bounds the piece's top/left edge (min) and
bottom/right edge (max), speed = travel / 840 W per cycle.

Also re-plots every entry from the written catalog at 480 px per W (pieces
and walls only) and builds concept | re-plot montage sheets in
<out dir>/shots/.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / 'artifacts' / 'momentum-frames'
UNIT = 480.0
MARGIN = 48.0
CYCLES_PER_PASS = 840.0

ORDER = [
    ('M04', 'right'), ('M23', 'right'), ('M24', 'right'), ('M46', 'right'), ('M47', 'right'), ('M66', 'right'),
    ('M11', 'down'), ('M30', 'down'), ('M93', 'down'), ('M110', 'down'),
    ('M11-up', 'up'), ('M30-up', 'up'), ('M93-up', 'up'), ('M110-up', 'up'),
    ('M18', 'corner'), ('M60', 'corner'), ('M39', 'corner'), ('M117', 'corner'), ('M134', 'corner'),
    ('M40', 'corner'), ('M98', 'corner'), ('M136', 'corner'),
]

# Bigger gaps: every window between two blues at the same x is 240 px
# (0.5 W) wide around the old window's centre. Frame px (x, y, w, h), in
# catalog.json blue order.
WINDOWS = {
    'M98': [(650, 75, 50, 110), (650, 425, 50, 130)],
    'M134': [(590, 217, 30, 133), (590, 590, 30, 107), (700, 217, 30, 53), (700, 510, 30, 187)],
    'M136': [(600, 75, 30, 45), (600, 360, 30, 195), (710, 75, 30, 95), (710, 410, 30, 145)],
}

# Course vertex (frame px) = where the two corridor centre lines meet.
VERTEX = {'right-down': (457, 315), 'right-up': (457, 457), 'down-right': (315, 457), 'up-right': (315, 315)}

COLORS = {'green': '#1CEA75', 'blue': '#0080FF', 'wall': '#1E5631'}


def r6(v):
    return round(v + 0.0, 6)


def source_pieces(frame):
    """catalog.json pieces with the widened windows applied (frame px)."""
    pieces = [dict(p) for p in frame['pieces']]
    rects = iter(WINDOWS.get(frame['id'], []))
    if frame['id'] in WINDOWS:
        for p in pieces:
            if p['kind'] == 'blue':
                p['x'], p['y'], p['w'], p['h'] = next(rects)
    return pieces


def bounds(p):
    if p['shape'] == 'polygon':
        xs = [q[0] for q in p['points']]
        ys = [q[1] for q in p['points']]
        return min(xs), min(ys), max(xs), max(ys)
    return p['x'], p['y'], p['x'] + p['w'], p['y'] + p['h']


def convert(p, ox, oy):
    """Frame px piece -> W piece with origin (ox, oy) frame px."""
    out = {'kind': p['kind'], 'shape': p['shape']}
    if p['shape'] == 'polygon':
        cx = sum(q[0] for q in p['points']) / len(p['points'])
        cy = sum(q[1] for q in p['points']) / len(p['points'])
        out['x'] = r6((cx - ox) / UNIT)
        out['y'] = r6((cy - oy) / UNIT)
        out['points'] = [[r6((q[0] - cx) / UNIT), r6((q[1] - cy) / UNIT)] for q in p['points']]
        return out
    out['x'] = r6((p['x'] + p['w'] / 2 - ox) / UNIT)
    out['y'] = r6((p['y'] + p['h'] / 2 - oy) / UNIT)
    out['w'] = r6(p['w'] / UNIT)
    out['h'] = r6(p['h'] / UNIT)
    m = p.get('motion')
    if m:
        axis = m['axis']
        size, origin = (p['w'], ox) if axis == 'x' else (p['h'], oy)
        lo = (m['min'] - origin) / UNIT
        hi = (m['max'] + size - origin) / UNIT
        out['motion'] = {'axis': axis, 'min': r6(lo), 'max': r6(hi),
                         'speed': r6(abs(hi - lo - size / UNIT) / CYCLES_PER_PASS)}
    return out


def mirror(entry, new_id):
    """Down frame flipped along the shaft: y' = span - y."""
    span = entry['span']
    pieces = []
    for p in entry['pieces']:
        q = json.loads(json.dumps(p))
        q['y'] = r6(span - p['y'])
        if 'points' in q:
            q['points'] = [[a, r6(-b)] for a, b in p['points']]
        m = q.get('motion')
        if m and m['axis'] == 'y':
            m['min'], m['max'] = r6(span - p['motion']['max']), r6(span - p['motion']['min'])
        pieces.append(q)
    return dict(entry, id=new_id, layout='up', dirs=['up'], pieces=pieces)


def build(catalog):
    frames = {f['id']: f for f in catalog['frames']}
    out = []
    for fid, layout in ORDER:
        if layout == 'up':
            down = next(e for e in out if e['id'] == fid[:-3])
            out.append(mirror(down, fid))
            continue
        frame = frames[fid]
        pieces = source_pieces(frame)
        box = [bounds(p) for p in pieces]
        entry = {'id': fid, 'layout': layout}
        if layout == 'right':
            ax = min(b[0] for b in box) - MARGIN
            entry['dirs'] = ['right']
            entry['difficulty'] = frame['difficulty']
            entry['span'] = r6((max(b[2] for b in box) + MARGIN - ax) / UNIT)
            entry['pieces'] = [convert(p, ax, 315) for p in pieces]
        elif layout == 'down':
            ay = min(b[1] for b in box) - MARGIN
            entry['dirs'] = ['down']
            entry['difficulty'] = frame['difficulty']
            entry['span'] = r6((max(b[3] for b in box) + MARGIN - ay) / UNIT)
            entry['pieces'] = [convert(p, 315, ay) for p in pieces]
        else:
            join = frame['layout']
            vx, vy = VERTEX[join]
            incoming, outgoing = join.split('-')
            entry['join'] = join
            entry['difficulty'] = frame['difficulty']
            # Back along the incoming corridor: right = towards -x, down =
            # towards -y, up = towards +y. Forward along the outgoing: down
            # +y, up -y, right +x.
            back = {'right': max(vx - b[0] for b in box), 'down': max(vy - b[1] for b in box),
                    'up': max(b[3] - vy for b in box)}[incoming]
            fwd = {'down': max(b[3] - vy for b in box), 'up': max(vy - b[1] for b in box),
                   'right': max(b[2] - vx for b in box)}[outgoing]
            entry['reach'] = {'in': r6(max(0.0, back) / UNIT + 0.1), 'out': r6(max(0.0, fwd) / UNIT + 0.1)}
            entry['axisScale'] = {'x': 'shaft', 'y': 'corridor'}
            entry['pieces'] = [convert(p, vx, vy) for p in pieces]
        out.append(entry)
    return {'unit': 'W', 'frames': out}


# ---- re-plot ---------------------------------------------------------------

def to_px(p, ox, oy, s):
    """W piece -> drawable (polygon points or rect box) in canvas px."""
    cx, cy = ox + p['x'] * s, oy + p['y'] * s
    if p['shape'] == 'polygon':
        return [(cx + a * s, cy + b * s) for a, b in p['points']]
    return [cx - p['w'] * s / 2, cy - p['h'] * s / 2, cx + p['w'] * s / 2, cy + p['h'] * s / 2]


def replot(entry, layouts):
    from PIL import Image, ImageDraw
    s = UNIT
    if entry['layout'] == 'right':
        size = (round(entry['span'] * s), 630)
        walls = [(0, 0, size[0], 75), (0, 555, size[0], 630)]
        origin = (0, 315)
    elif entry['layout'] in ('down', 'up'):
        size = (630, round(entry['span'] * s))
        walls = [(0, 0, 75, size[1]), (555, 0, 630, size[1])]
        origin = (315, 0)
    else:
        lay = layouts[entry['join']]
        size = tuple(lay['size'])
        walls = [(x, y, x + w, y + h) for x, y, w, h in lay['walls']]
        origin = VERTEX[entry['join']]
    img = Image.new('RGB', size, 'white')
    d = ImageDraw.Draw(img)
    for w in walls:
        d.rectangle([w[0], w[1], w[2] - 1, w[3] - 1], fill=COLORS['wall'])
    for p in entry['pieces']:
        shape = to_px(p, origin[0], origin[1], s)
        if p['shape'] == 'polygon':
            d.polygon(shape, fill=COLORS['green'] if p['kind'] == 'green' else COLORS['blue'],
                      outline='black' if p['kind'] == 'green' else None)
        else:
            box = [shape[0], shape[1], shape[2] - 1, shape[3] - 1]
            if p['kind'] == 'green':
                d.rectangle(box, fill=COLORS['green'], outline='black')
            else:
                d.rectangle(box, fill=COLORS['blue'])
    return img


SHEETS = [('sheet1-right.png', 0, 6), ('sheet2-down-up.png', 6, 14), ('sheet3-corners.png', 14, 22)]


def montage(doc, catalog, shots):
    from PIL import Image, ImageDraw
    pngs = {f['id']: FRAMES / f['png'] for f in catalog['frames']}
    shots.mkdir(parents=True, exist_ok=True)
    scale, cols, head, gap = 0.5, 2, 26, 16
    written = []
    for name, a, b in SHEETS:
        pairs = []
        for e in doc['frames'][a:b]:
            src = e['id'].replace('-up', '')
            concept = Image.open(pngs[src]).convert('RGB')
            plot = replot(e, catalog['layouts'])
            label = '%s  concept %s | re-plot from catalog-m.json%s' % (
                e['id'], src, ' (up = down concept flipped)' if e['layout'] == 'up' else '')
            pairs.append((label, concept, plot))
        cw = max(round((c.width + p.width) * scale) + gap for _, c, p in pairs)
        ch = max(round(max(c.height, p.height) * scale) for _, c, p in pairs) + head
        rows = (len(pairs) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * (cw + gap) + gap, rows * (ch + gap) + gap), '#cccccc')
        d = ImageDraw.Draw(sheet)
        for i, (label, c, p) in enumerate(pairs):
            x0 = gap + (i % cols) * (cw + gap)
            y0 = gap + (i // cols) * (ch + gap)
            d.text((x0 + 4, y0 + 6), label, fill='black')
            c2 = c.resize((round(c.width * scale), round(c.height * scale)))
            p2 = p.resize((round(p.width * scale), round(p.height * scale)))
            sheet.paste(c2, (x0, y0 + head))
            sheet.paste(p2, (x0 + c2.width + gap, y0 + head))
        sheet.save(shots / name)
        written.append(str(shots / name))
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--catalog', default=str(FRAMES / 'catalog.json'))
    ap.add_argument('--out', default=str(ROOT / 'artifacts' / 'TASK-102' / 'catalog-m.json'))
    ap.add_argument('--shots', default=None, help='montage dir, default <out dir>/shots')
    args = ap.parse_args()
    catalog = json.loads(Path(args.catalog).read_text())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(catalog), separators=(',', ':')))
    # Re-plot from the written file, not the in-memory build.
    doc = json.loads(out.read_text())
    shots = Path(args.shots) if args.shots else out.parent / 'shots'
    for path in montage(doc, catalog, shots):
        print(path)
    print(out, len(doc['frames']), 'frames')


if __name__ == '__main__':
    main()
