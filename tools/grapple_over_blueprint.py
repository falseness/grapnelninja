"""Render design reservations; no game runtime dependency."""
import html
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'docs/grapple-over-blueprint.json'


def export(out):
    b = json.loads(SOURCE.read_text())
    (out / 'blueprint.json').write_text(json.dumps(b, separators=(',', ':')) + '\n')
    encounters = [e for s in b['sections'] for e in s['encounters']]
    graph = {'scope': 'planned connectivity only; no proven routes',
             'nodes': ['base'] + [e['id'] for e in encounters],
             'edges': [e['recoveryEdge'] for e in encounters], 'shortcuts': b['shortcuts']}
    (out / 'recovery-graph.json').write_text(json.dumps(graph, separators=(',', ':')) + '\n')
    (out / 'review.md').write_text(SOURCE.with_suffix('.md').read_text())
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="2900" viewBox="0 0 1200 2900">',
           '<rect width="1200" height="2900" fill="#101923"/>',
           '<g font-family="sans-serif" fill="white">',
           '<text x="30" y="30" font-size="24">Grapple Over: eight sections / 32 planned encounters</text>',
           '<text x="30" y="58">Reservation schematic only. UP = ascent. All recovery edges are planned.</text>',
           '<text x="30" y="85">West: fall | middle: ascent | east: lateral recovery. Gaps reserve 200 world units.</text>']
    for n, e in enumerate(reversed(encounters)):
        y = 110 + n * 84
        s = b['sections'][int(e['id'][1:3])-1]
        svg.append(f'<text x="20" y="{y+19}" font-size="17">{e["id"]} {html.escape(s["name"])}</text>')
        svg.append(f'<text x="20" y="{y+40}" font-size="12">{e["phase"]} / range {e["rangeStage"]} / {html.escape(e["landmark"])}</text>')
        for x,w,color in [(430,260,'#334b68'),(710,160,'#265440'),(890,140,'#624c75')]:
            svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="72" fill="{color}"/>')
        svg.append(f'<path d="M790 {y+65}V{y+5}m-5 8 5-8 5 8" stroke="#adf7cc" fill="none"/>')
        svg.append(f'<path d="M960 {y+4}V{y+72}m-5-8 5 8 5-8" stroke="#efd4ff" fill="none"/>')
        svg.append(f'<rect x="730" y="{y+55}" width="54" height="6" fill="#7bec92"/>')
        if 'yellowReservation' in e:
            svg.append(f'<rect x="440" y="{y+32}" width="240" height="14" fill="#d5c65b"/>')
        svg.append(f'<text x="1040" y="{y+25}" font-size="12">to {e["recoveryEdge"]["to"]}</text>')
        svg.append(f'<text x="1040" y="{y+45}" font-size="12">planned</text>')
    svg += ['<text x="30" y="2840">BASE — connected by planned descending recovery edges; no teleports/checkpoints.</text>',
            '<text x="30" y="2870">Optional: S05-E02 → E04 and S07-E02 → E04. One skipped encounter each.</text>', '</g></svg>']
    (out / 'route-map.svg').write_text('\n'.join(svg))
    return b, graph
