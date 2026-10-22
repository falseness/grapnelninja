"""Convert the extended-mountain concept into an SVG level format v1 file.

Reads only extended-mountain-measurements.json (world coordinates) and writes
one new SVG (docs/level-svg-format.md). The concept SVG, its generator,
measurements and previews are never written.

Gameplay geometry is written in world units. The display labels, route
curves and side panel from the concept are redrawn in an annotations layer
whose transform maps the concept's 2600x4300 canvas onto world space, and the
root viewBox frames that same canvas, so the file looks like the concept.

    python3 tools/convert_extended_mountain_svg.py \
        --measurements artifacts/level/extended-mountain-measurements.json \
        --output artifacts/level/extended-mountain.import.svg
"""
import argparse
import html
import json
import os
import tempfile
from pathlib import Path

R = 540.0
PLAYER_RADIUS = 10.8
CANVAS_W, CANVAS_H = 2600, 4300
LAYOUT_ID = 'extended-mountain-v1'
COMBO_TEXT = 'Ceiling hold → downward jump → rebound'
SPAWN = (500.0, -30.0)          # on P0's top edge (y=0), right of the post
FINISH_PAD = (60.0, 300.0)      # finish box: summit width + pad, height above top
BOUNDS_PAD = 1000.0


def num(v):
    """Shortest exact decimal for a float; integral values without a point."""
    v = float(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def disp(v):
    return f'{v:.2f}'


def world(m, p):
    return (m['x'] + p[0], m['y'] + p[1])


def bodies(m):
    return [[world(m, p) for p in poly] for poly in m['polys']]


def contact(m):
    if m['kind'] == 'ceiling':
        return (m['x'] + m['width'] * .5, m['y'] + m['height'] + PLAYER_RADIUS)
    if m['kind'] == 'bounce':
        return (m['x'] + m['width'] * .5, m['y'] + 120 - PLAYER_RADIUS)
    return (m['x'] + m['width'] * .5, m['y'] - PLAYER_RADIUS)


def fit(points, box, pad):
    xmin = min(x for x, y in points) - pad
    xmax = max(x for x, y in points) + pad
    ymin = min(y for x, y in points) - pad
    ymax = max(y for x, y in points) + pad
    bx, by, bw, bh = box
    s = min(bw / (xmax - xmin), bh / (ymax - ymin))
    ox = bx + (bw - (xmax - xmin) * s) / 2 - xmin * s
    oy = by + (bh - (ymax - ymin) * s) / 2 - ymin * s
    return (lambda p: (ox + p[0] * s, oy + p[1] * s)), s, ox, oy


def curve(r, frags):
    a, b = r['flight']
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    target = frags[r['number']]
    if target['kind'] == 'ceiling':
        c1 = (a[0] + dx * .4, a[1] + dy * .45)
        c2 = (b[0] - dx * .12, b[1] + 650)
    elif dy > 0:
        c1 = (a[0] + dx * .45, a[1] + dy * .06)
        c2 = (b[0] - dx * .15, b[1] - 650)
    else:
        c1 = (a[0] + dx * .25, min(a[1], b[1]) - 700)
        c2 = (b[0] - dx * .2, b[1] - 500)
    return [a, c1, c2, b]


def guide(r, frags):
    """Optional gn:transfer guide value: the route curve() in world units."""
    return ' '.join(num(v) for p in curve(r, frags) for v in p)


class Canvas:
    """Annotation drawing in concept canvas pixels (same calls as the concept)."""

    def __init__(self):
        self.out = []

    def add(self, s):
        self.out.append(s)

    def rect(self, x, y, w, h, fill, stroke='none', rx=0):
        self.add(f'<rect x="{disp(x)}" y="{disp(y)}" width="{disp(w)}" height="{disp(h)}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>')

    def text(self, x, y, t, size=20, color='#b7cbd4', weight=400, anchor='start'):
        self.add(f'<text x="{disp(x)}" y="{disp(y)}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(str(t))}</text>')

    def line(self, a, b, color='#486475', dash='', width=2, marker=''):
        self.add(f'<line x1="{disp(a[0])}" y1="{disp(a[1])}" x2="{disp(b[0])}" y2="{disp(b[1])}" stroke="{color}" stroke-width="{width}"'
                 + (f' stroke-dasharray="{dash}"' if dash else '') + (f' marker-end="url(#{marker})"' if marker else '') + '/>')

    def poly(self, p, fill, stroke, width=2):
        self.add('<polygon points="' + ' '.join(f'{disp(x)},{disp(y)}' for x, y in p) + f'" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')

    def circle(self, x, y, r, fill, stroke='none'):
        self.add(f'<circle cx="{disp(x)}" cy="{disp(y)}" r="{disp(r)}" fill="{fill}" stroke="{stroke}"/>')


def fragment_style(kind):
    color = '#91dfcb' if kind == 'ceiling' else '#a3e184' if kind == 'bounce' else '#8dc8b2'
    fill = '#193a45' if kind == 'ceiling' else '#294a34' if kind == 'bounce' else '#213d38'
    return fill, color


def draw_fragment_labels(c, m, T, s):
    kind = m['kind']
    x, y = T(contact(m))
    if kind == 'ceiling':
        a = T((m['x'], m['y'] + m['height']))
        b = T((m['x'] + m['width'], m['y'] + m['height']))
        c.line(a, b, '#a0edf0', '', 3)
        c.circle(x, y, 5, '#d1ffff')
        c.text(x, y + 27, 'HOLD', 14, '#a0edf0', 700, 'middle')
    elif kind == 'bounce':
        sign = m['bounceSign']
        c.line((x, y), (x + sign * 25, y - 30), '#b5eb93', '', 2, 'route')
        c.circle(x, y, 5, '#c7f4a5')
        c.text(x, y + 38, 'BOUNCE UP-RIGHT' if sign > 0 else 'BOUNCE UP-LEFT', 12, '#b5eb93', 700, 'middle')
    elif kind == 'summit':
        c.line((x, y), (x, y - 45), '#e8f4e6', '', 2)
        c.poly([(x, y - 45), (x + 28, y - 37), (x, y - 29)], '#e8f4e6', '#e8f4e6')
        c.text(x, y - 62, 'SUMMIT', 22, '#e8f4e6', 700, 'middle')
    else:
        c.text(x, y + max(24, m['height'] * s + 16), m['id'], 14, '#8dc8b2', 700, 'middle')


def draw_route(c, r, frags, T):
    pts = [T(p) for p in curve(r, frags)]
    a, b = pts[0], pts[-1]
    c.add(f'<path d="M{disp(a[0])} {disp(a[1])} C{disp(pts[1][0])} {disp(pts[1][1])} {disp(pts[2][0])} {disp(pts[2][1])} {disp(b[0])} {disp(b[1])}" fill="none" stroke="#eaf3ed" stroke-width="2" stroke-dasharray="8 6" marker-end="url(#route)"/>')
    p, q = [T(v) for v in r['witness']]
    c.line(p, q, '#7fc0a8', '', 1.3)
    mx = (p[0] + q[0]) / 2
    my = (p[1] + q[1]) / 2
    offx = 105 if r['number'] % 2 else -105
    if abs(q[0] - p[0]) > 100:
        offx = 0
        my += 35 if r['number'] % 2 else -30
    mx += offx
    w = 170
    c.rect(mx - w / 2, my - 23, w, 47, '#0b1923', rx=5)
    c.text(mx, my, f"{r['number']:02d} · {r['percent']}%", 18, '#aae0bd', 700, 'middle')
    c.text(mx, my + 19, f"{r['distance']:.0f}u clear gap", 13, '#96b4be', 400, 'middle')


def build(meas, guides=False):
    frags = meas['fragments']
    rows = meas['encounters']
    bands = meas['yellowBands']
    falls = meas['fallIllustrations']
    combos = [tuple(c) for c in meas['combinations']]
    assert len(frags) == 25 and len(rows) == 24 and len(bands) > 0 and len(combos) == 4
    assert float(meas['grappleRange']) == R

    allb = [p for m in frags for p in bodies(m)]
    pts = [p for b in allb for p in b] + [tuple(p) for z in bands for p in z['polygon']] + [tuple(f['end']) for f in falls]
    T, s, ox, oy = fit(pts, (70, 335, 1860, 3500), 1000)
    inv = f'matrix({num(1 / s)} 0 0 {num(1 / s)} {num(-ox / s)} {num(-oy / s)})'
    view = (-ox / s, -oy / s, CANVAS_W / s, CANVAS_H / s)

    summit = frags[-1]
    assert summit['kind'] == 'summit'
    goal = contact(summit)
    finish = (summit['x'] - FINISH_PAD[0], summit['y'] - FINISH_PAD[1],
              summit['width'] + 2 * FINISH_PAD[0], FINISH_PAD[1])
    xs = [x for b in allb for x, _ in b] + [p[0] for z in bands for p in z['polygon']] + [SPAWN[0], finish[0], finish[0] + finish[2]]
    ys = [y for b in allb for _, y in b] + [p[1] for z in bands for p in z['polygon']] + [SPAWN[1], finish[1], finish[1] + finish[3]]
    import math
    bounds = (math.floor(min(xs) - BOUNDS_PAD), math.floor(min(ys) - BOUNDS_PAD),
              math.ceil(max(xs) + BOUNDS_PAD), math.ceil(max(ys) + BOUNDS_PAD))

    out = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:gn="urn:grapnelninja:level-svg:1"'
           ' data-level-format="grapnelninja-level" data-level-version="1"'
           f' data-layout-id="{LAYOUT_ID}" data-grapple-range="540"'
           f' data-bounds="{" ".join(num(v) for v in bounds)}"'
           f' viewBox="{" ".join(num(v) for v in view)}" width="{CANVAS_W}" height="{CANVAS_H}">',
           '<title>Extended mountain: 24 jumps, ceiling holds, descending rebounds and yellow fall brakes (level SVG v1)</title>',
           '<defs><marker id="route" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#eaf3ed"/></marker>'
           '<marker id="drop" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#e8b477"/></marker></defs>']

    # Annotations drawn beneath gameplay: background, heading, fall arrows.
    back = Canvas()
    back.rect(0, 0, CANVAS_W, CANVAS_H, '#09141e')
    back.text(70, 62, 'GRAPPLE OVER / EXTENDED ROUTE / BASELINE PRESERVED', 21, '#8ad3b7', 700)
    back.text(70, 125, 'Hold the ceiling. Drop. Bounce back up.', 45, '#edf4f5', 700)
    back.text(70, 170, '24 jumps · original 01–10 unchanged · four compound ceiling / descent / rebound sequences · yellow braking bands', 21)
    back.rect(70, 202, 2460, 65, '#29283a', rx=8)
    back.text(92, 232, 'GRAPPLE RANGE 540u · percentages show minimum open gaps · every illustrated flight remains unverified with production physics', 20, '#e8c493', 700)
    back.text(92, 255, 'Yellow rectangles slow falls without providing a foothold, grapple target, checkpoint or automatic return.', 17, '#c5b6a1')
    for f in falls:
        back.line(T(f['start']), T(f['end']), '#d7a46e', '6 8', 2, 'drop')
    out.append(f'<g id="annotations-back" data-layer="annotations" font-family="Arial,sans-serif" transform="{inv}">')
    out += back.out
    out.append('</g>')

    # Gameplay geometry in world units.
    sw = num(2 / s)
    out.append('<g id="geometry" data-layer="geometry">')
    for z in bands:
        out.append(f'<rect id="{z["id"]}-drag" x="{num(z["x"])}" y="{num(z["y"])}" width="{num(z["width"])}" height="{num(z["height"])}"'
                   f' data-role="drag" data-grapplable="false" data-name="{z["id"]} fall brake" fill="#66551f" stroke="#e8ce61" stroke-width="{sw}"/>')
    roles = {}
    for m in frags:
        role = m.get('surfaceRole', 'bounce' if m['kind'] == 'bounce' else 'solid')
        fill, color = fragment_style('bounce' if role == 'bounce' else m['kind'])
        out.append(f'<g id="{m["id"]}" data-fragment="true">')
        ids = []
        for i, poly in enumerate(m['polys']):
            eid = f'{m["id"]}-body{i}'
            ids.append(eid)
            pts_s = ' '.join(f'{num(m["x"] + px)},{num(m["y"] + py)}' for px, py in poly)
            out.append(f'<polygon id="{eid}" points="{pts_s}" data-role="{role}" data-grapplable="true"'
                       f' data-name="{html.escape(m["name"])}" fill="{fill}" stroke="{color}" stroke-width="{sw}"/>')
        roles[m['id']] = (role, ids)
        out.append('</g>')
    out.append('</g>')

    # Annotations above gameplay: band labels, contact marks, routes, panel.
    front = Canvas()
    for z in bands:
        x, y = T((z['x'], z['y']))
        front.text(x + z['width'] * s / 2, y - 9, z['id'] + ' · FALL BRAKE', 14, '#efd571', 700, 'middle')
    for m in frags:
        draw_fragment_labels(front, m, T, s)
    for r in rows:
        draw_route(front, r, frags, T)
    x, y = T(contact(frags[10]))
    front.text(x - 35, y - 40, 'BASELINE ENDS / EXTENSION STARTS', 16, '#d4d6ba', 700, 'end')
    front.rect(1980, 315, 550, 3480, '#11222d', rx=12)
    front.text(2010, 362, '24-JUMP ROUTE', 24, '#e7f0f3', 700)
    front.text(2010, 396, '01–10: preserved baseline geometry', 19, '#92aebb')
    for i, r in enumerate(rows):
        y = 443 + i * 99
        front.text(2010, y, f"{r['number']:02d}  {r['fromFragment']} → {r['toFragment']}", 19, '#d9e7eb', 700)
        front.text(2495, y, str(r['percent']) + '%', 24, '#aae0bd', 700, 'end')
        action = r['action'] if not r['baseline'] else r['direction']
        front.text(2010, y + 29, action, 16, '#a6c1cb')
        front.text(2010, y + 53, f"{r['distance']:.0f} world units", 16, '#7f9ba9')
        front.line((2010, y + 71), (2495, y + 71), '#29434f', '', 1)
    front.text(2010, 2890, 'FOUR COMBINATIONS', 22, '#dcebe7', 700)
    for i, (a, b, c) in enumerate(combos):
        y = 2937 + i * 86
        front.text(2010, y, f'{a:02d} → {b:02d} → {c:02d}', 24, '#9ae3e4', 700)
        front.text(2010, y + 30, COMBO_TEXT, 16, '#b4ccd2')
    front.text(2010, 3325, 'YELLOW BANDS', 22, '#edd575', 700)
    for i, z in enumerate(bands):
        y = 3367 + i * min(48, 300 / len(bands))
        front.text(2010, y, f"{z['id']} · {z.get('purpose', 'fall brake')} · {z['width']:.0f} × {z['height']:.0f}u", 17, '#c7b67b')
    front.text(2010, 3710, 'Fall brakes and upward-shortcut damping zones.', 17, '#9fb8c3')
    front.text(2010, 3740, 'No nominal illustrated arc enters a band.', 17, '#9fb8c3')
    front.rect(70, 3930, 2460, 270, '#12242e', rx=12)
    front.text(100, 3975, 'THE COMBINATIONS ARE THE CHALLENGE', 23, '#e4efed', 700)
    front.text(100, 4013, 'Grab a ceiling from below; release diagonally down onto a sloped green bounce surface; redirect into an upward jump.', 21)
    front.text(100, 4054, 'Descending and ascending legs share the same bounce contact. No reset, teleport, extra launch force or hidden intermediate anchor is implied.', 19, '#a7c0ca')
    front.text(100, 4093, 'Yellow bands are horizontal, non-solid fall brakes. Falling continues through them into earlier terrain; recovery and damping remain unverified.', 19, '#d3bd91')
    front.text(100, 4133, 'Geometric checks exclude direct fragment-to-fragment grappling. They do not establish viable jump physics, mandatory release or absence of swing bypasses.', 18, '#c4b39e')
    front.text(70, 4260, 'Level SVG v1 conversion of extended-mountain.svg. Gameplay is in the geometry/markers layers; this layer is display only.', 18, '#8aa5b1')
    out.append(f'<g id="annotations-front" data-layer="annotations" font-family="Arial,sans-serif" transform="{inv}">')
    out += front.out
    out.append('</g>')

    # Markers: spawn on the opening platform, finish around the summit destination.
    out.append('<g id="markers" data-layer="markers">')
    out.append(f'<circle id="spawn" data-marker="spawn" cx="{num(SPAWN[0])}" cy="{num(SPAWN[1])}" r="{num(PLAYER_RADIUS * 3)}" fill="#8ad3b7"/>')
    out.append(f'<rect id="finish" data-marker="finish" x="{num(finish[0])}" y="{num(finish[1])}" width="{num(finish[2])}" height="{num(finish[3])}"'
               f' fill="none" stroke="#efd571" stroke-width="{sw}" stroke-dasharray="{num(8 / s)} {num(6 / s)}"/>')
    out.append('</g>')

    # Route metadata: one encounter + transfer per jump, sections follow the chains.
    out.append('<metadata id="level-route">')
    by_num = {r['number']: r for r in rows}
    in_combo = {n: k for k, combo in enumerate(combos, 1) for n in combo}
    sections = [('SEC-baseline', [n for n in range(1, 11)])]
    n = 11
    while n <= 24:
        if n in in_combo:
            k = in_combo[n]
            sections.append((f'SEC-chain{k}', list(combos[k - 1])))
            n = combos[k - 1][-1] + 1
        else:
            sections.append((f'SEC-jump{n:02d}', [n]))
            n += 1
    for sid, nums in sections:
        out.append(f'<gn:section id="{sid}" encounters="{" ".join(by_num[k]["id"] for k in nums)}"/>')
    for r in rows:
        els = roles[r['fromFragment']][1] + roles[r['toFragment']][1]
        out.append(f'<gn:encounter id="{r["id"]}" elements="{" ".join(els)}"/>')
    for r in rows:
        extra = f' guide="{guide(r, frags)}"' if guides else ''
        out.append(f'<gn:transfer id="T{r["number"]:02d}" from="{r["fromFragment"]}" to="{r["toFragment"]}" encounter="{r["id"]}" gap-percent="{num(r["percent"])}"{extra}/>')
    out.append('</metadata>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--measurements', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    src = Path(args.measurements).resolve()
    dst = Path(args.output).resolve()
    if dst.name in ('extended-mountain.svg', 'jump-combinations.svg') or dst == src:
        ap.error('refusing to overwrite a concept file')
    text = build(json.loads(src.read_text()))
    fd, tmp = tempfile.mkstemp(dir=dst.parent, suffix='.tmp')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    os.replace(tmp, dst)
    print(f'WROTE {dst} bytes={len(text.encode())}')


if __name__ == '__main__':
    main()
