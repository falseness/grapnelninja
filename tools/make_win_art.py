#!/usr/bin/env python3
"""Picture-only Grapple Over summit art (art/win-default.svg, art/win-long.svg).

The user-approved concept artifacts/win-art-3/winart3.py with the same seed and
drawing, minus every text element: the game draws the title, stats, badge and
call to action itself (translated). Re-running it reproduces the files byte-identically.
"""
import argparse, math, random, pathlib
OUT = pathlib.Path(__file__).resolve().parent.parent / 'art'
W, H = 1280, 720
f = lambda v: f'{v:.1f}'.rstrip('0').rstrip('.')

def helix(x0, y0, x1, y1, amp=6, wave=11, phase=0.0):
    L = math.hypot(x1-x0, y1-y0); ux, uy = (x1-x0)/L, (y1-y0)/L; pts = []; s = 0.0
    while s <= L:
        d = min(1, min(s, L-s)/24) * math.sin(s/wave + phase) * amp
        pts.append((x0+ux*s-uy*d, y0+uy*s+ux*d)); s += 4
    pts.append((x1, y1)); return 'M' + ' L'.join(f'{f(x)} {f(y)}' for x, y in pts)

def background(r, long):
    o = []
    # crystals hanging from the top
    for i in range(26):
        x = i*52 + r.uniform(-20, 20); w = r.uniform(30, 80); h = r.uniform(60, 230)
        o.append(f'<path d="M{f(x)} -2 L{f(x+w)} -2 L{f(x+w*r.uniform(.3,.7))} {f(h)}Z" fill="#14124a" fill-opacity=".55" stroke="#5552b8" stroke-opacity=".28"/>')
    # far ridge
    pts = ' '.join(f'{x},{f(560 - 90*abs(math.sin(x/170+.6)) - r.uniform(0,40))}' for x in range(-40, W+81, 80))
    o.append(f'<polygon points="-40,{H} {pts} {W+40},{H}" fill="#2b2878" fill-opacity=".45" stroke="#6a66d0" stroke-opacity=".22"/>')
    # stepped skyline outline
    x, d = 0, 'M0 420'
    while x < W:
        y = r.choice([300, 330, 360, 390, 410, 380]); nx = x + r.choice([60, 90, 120, 150])
        d += f' V{y} H{nx}'; x = nx
    o.append(f'<path d="{d} V420" fill="none" stroke="#5d5bc4" stroke-opacity=".35" stroke-width="1.5"/>')
    # antenna lines
    for i in range(9):
        ax = 90 + i*140 + r.uniform(-30, 30); ay = r.uniform(250, 300)
        o.append(f'<line x1="{f(ax)}" y1="{f(ay)}" x2="{f(ax)}" y2="{f(ay+150)}" stroke="#6a66d0" stroke-opacity=".25"/><circle cx="{f(ax)}" cy="{f(ay)}" r="3" fill="none" stroke="#6a66d0" stroke-opacity=".4"/>')
    # glowing square motes
    cols = ['#7fb8ff', '#b49cff', '#ffffff', '#5a8cff'] if not long else ['#b49cff', '#d9ccff', '#ffffff', '#8a7cff']
    for i in range(70):
        mx, my, s = r.uniform(0, W), r.uniform(0, H), r.choice([3, 4, 5, 6, 8, 10]); c = r.choice(cols)
        o.append(f'<rect x="{f(mx-s*1.6)}" y="{f(my-s*1.6)}" width="{f(s*3.2)}" height="{f(s*3.2)}" fill="{c}" opacity=".1"/><rect x="{f(mx-s/2)}" y="{f(my-s/2)}" width="{s}" height="{s}" fill="{c}" opacity="{f(r.uniform(.45,.95))}"/>')
    return ''.join(o)

def platform(r, cx, cy, w, h, rot, slant=0.12):
    # circuit-board floor: dark fill, neon outline + glow, PCB traces
    hw, hh = w/2, h/2
    poly = f'M{f(-hw)} {f(-hh)} L{f(hw)} {f(-hh)} L{f(hw - w*slant)} {f(hh)} L{f(-hw + w*slant)} {f(hh)}Z'
    t = []
    for _ in range(int(w/45)):
        x = r.uniform(-hw*.75, hw*.6); y = r.uniform(-hh*.55, hh*.4); d = f'M{f(x)} {f(y)}'
        for _ in range(r.randint(2, 4)):
            step = r.uniform(14, 34); kind = r.choice(['h', 'd', 'u'])
            x += step; y += {'h': 0, 'd': step*.6, 'u': -step*.6}[kind]
            y = max(-hh*.6, min(hh*.5, y)); x = min(hw*.8 - w*slant, x)
            d += f' L{f(x)} {f(y)}'
        t.append(f'<path d="{d}" fill="none" stroke="#3dff4a" stroke-opacity=".55" stroke-width="1.6"/><circle cx="{f(x)}" cy="{f(y)}" r="3.2" fill="#062814" stroke="#3dff4a" stroke-opacity=".75" stroke-width="1.4"/>')
    for _ in range(int(w/80)):
        px, py = r.uniform(-hw*.7, hw*.5), r.uniform(-hh*.5, hh*.4)
        t.append(f'<rect x="{f(px)}" y="{f(py)}" width="5" height="5" fill="#8a7a3a"/><rect x="{f(px+8)}" y="{f(py)}" width="5" height="5" fill="#8a7a3a"/>')
    for _ in range(int(w/120)+1):
        px, py = r.uniform(-hw*.6, hw*.5), r.uniform(-hh*.5, hh*.4)
        t.append(f'<path d="M{f(px-4)} {f(py)}h8M{f(px)} {f(py-4)}v8" stroke="#fff" stroke-opacity=".8" stroke-width="1.2"/>')
    return (f'<g transform="translate({f(cx)} {f(cy)}) rotate({rot})">'
            f'<ellipse rx="{f(w*.75)}" ry="{f(h*1.6+40)}" fill="url(#greenGlow)"/>'
            f'<path d="{poly}" fill="#072a15" stroke="#3dff4a" stroke-width="12" stroke-opacity=".14"/>'
            f'<path d="{poly}" fill="none" stroke="#3dff4a" stroke-width="3.5" stroke-linejoin="round"/>{"".join(t)}</g>')

def burst(r, cx, cy, n, radius, cols):
    o = []
    for i in range(n):
        a = i/n*2*math.pi + r.uniform(-.08, .08); d = radius*r.uniform(.45, 1)
        for k in range(3):
            dd = d*(1 - k*.13); s = 6 - k*1.6
            o.append(f'<rect x="{f(cx+math.cos(a)*dd - s/2)}" y="{f(cy+math.sin(a)*dd - s/2)}" width="{f(s)}" height="{f(s)}" fill="{r.choice(cols)}" opacity="{f(.95 - k*.3)}" transform="rotate(45 {f(cx+math.cos(a)*dd)} {f(cy+math.sin(a)*dd)})"/>')
    return ''.join(o)

def art(long):
    r = random.Random(7)
    pillar = '#38e8ff' if not long else '#b49cff'
    sx, sy = 640, 560           # summit platform centre
    ninja_y = sy - 22 - 15
    defs = ('<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
            + ('<stop offset="0" stop-color="#0c0a26"/><stop offset=".5" stop-color="#24237a"/><stop offset="1" stop-color="#3a2a8c"/>' if not long else
               '<stop offset="0" stop-color="#0a0a22"/><stop offset=".5" stop-color="#22206a"/><stop offset="1" stop-color="#2c2470"/>')
            + '</linearGradient>'
            '<radialGradient id="greenGlow"><stop offset="0" stop-color="#3dff4a" stop-opacity=".22"/><stop offset="1" stop-color="#3dff4a" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="beam" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="{pillar}" stop-opacity=".95"/><stop offset=".7" stop-color="{pillar}" stop-opacity=".35"/><stop offset="1" stop-color="{pillar}" stop-opacity="0"/></linearGradient>'
            '<radialGradient id="halo"><stop offset="0" stop-color="#22c8ff" stop-opacity=".6"/><stop offset="1" stop-color="#22c8ff" stop-opacity="0"/></radialGradient>'
            '<radialGradient id="knot"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".35" stop-color="#d9ccff" stop-opacity=".5"/><stop offset="1" stop-color="#d9ccff" stop-opacity="0"/></radialGradient>'
            '<radialGradient id="vignette" cx=".5" cy=".45" r=".75"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>'
            '<linearGradient id="trail" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#36b8ff" stop-opacity="0"/><stop offset="1" stop-color="#36b8ff" stop-opacity=".9"/></linearGradient>')
    o = [f'<rect width="{W}" height="{H}" fill="url(#sky)"/>', background(r, long)]
    # light pillar from the summit
    o.append(f'<rect x="{sx-40}" y="0" width="80" height="{sy-20}" fill="url(#beam)" opacity=".12"/><rect x="{sx-9}" y="0" width="18" height="{sy-20}" fill="url(#beam)" opacity=".5"/><rect x="{sx-2}" y="0" width="4" height="{sy-20}" fill="#fff" opacity=".5"/>')
    # lower route platforms
    o.append(platform(r, 150, 690, 340, 70, -8))
    o.append(platform(r, 1150, 650, 300, 64, 10))
    o.append(platform(r, 230, 400, 230, 52, 4))
    o.append(platform(r, 1090, 330, 210, 50, -5))
    if long:
        o.append(f'<rect x="760" y="380" width="300" height="260" fill="#9b5cff" fill-opacity=".14" stroke="#b07cff" stroke-width="2" stroke-opacity=".7"/>')
    # summit
    o.append(platform(r, sx, sy, 470, 64, 0, 0.08))
    # swing trail into the ninja, rope + plasma knot up the beam
    o.append(f'<path d="M300 650 C 420 640, 540 600, {sx-14} {ninja_y+4}" fill="none" stroke="url(#trail)" stroke-width="12" stroke-linecap="round" opacity=".35"/>'
             f'<path d="M300 650 C 420 640, 540 600, {sx-14} {ninja_y+4}" fill="none" stroke="#d8fbff" stroke-width="2.4" stroke-linecap="round" opacity=".8"/>')
    kx, ky = (sx+150, 300) if not long else (sx+260, 240)
    o.append(f'<g fill="none" stroke-linecap="round"><path d="{helix(sx, ninja_y, kx, ky)}" stroke="#d9ccff" stroke-width="2"/><path d="{helix(sx, ninja_y, kx, ky, phase=math.pi)}" stroke="#fff" stroke-width="2.2"/></g>'
             f'<circle cx="{kx}" cy="{ky}" r="26" fill="url(#knot)"/><circle cx="{kx}" cy="{ky}" r="9" fill="none" stroke="#d9ccff" stroke-width="2"/><circle cx="{kx}" cy="{ky}" r="4.5" fill="#fff"/>')
    if long:
        for rr, op in ((140, .5), (280, .3)):
            o.append(f'<circle cx="{sx}" cy="{ninja_y}" r="{rr}" fill="none" stroke="#d9ccff" stroke-opacity="{op}" stroke-width="1.6" stroke-dasharray="6 9"/>')
    o.append(f'<circle cx="{sx}" cy="{ninja_y}" r="42" fill="url(#halo)"/><circle cx="{sx}" cy="{ninja_y}" r="15" fill="#125dff" stroke="#30d5c8" stroke-width="3"/><circle cx="{sx}" cy="{ninja_y}" r="5.5" fill="#050a2e"/>')
    # pixel fireworks
    cols = ['#ffe27a', '#38e8ff', '#b49cff', '#ffffff', '#3dff4a'] if not long else ['#d9ccff', '#b49cff', '#ffffff']
    o.append(burst(r, 330, 150, 18, 90, cols))
    o.append(burst(r, 960, 120, 16, 75, cols))
    if not long:
        o.append(burst(r, 1180, 230, 12, 50, cols)); o.append(burst(r, 120, 260, 12, 55, cols))
    o.append(f'<rect width="{W}" height="{H}" fill="url(#vignette)"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"><defs>{defs}</defs>{"".join(o)}</svg>'

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default=str(OUT), help='output directory (default: art/)')
    out = pathlib.Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    for long in (False, True):
        (out / f'win-{"long" if long else "default"}.svg').write_text(art(long), encoding='utf-8')

if __name__ == '__main__':
    main()
