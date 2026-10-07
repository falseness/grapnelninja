"""The ninja ball is drawn at its pre-overhaul size again (TASK-212).

On render_snapshot's frozen clock (same seeded input), bad and classic at
1920x1080@1 and 844x390@3, the ball's drawn outer radius is measured from
pixels: along 8 directions from the ninja centre out to RMAX, the outermost
brightness drop of at least EDGE_DROP_RATIO of the largest one marks where the
ring colour ends (outer edge); the
median of the 8 directions is the radius of a capture, the median over TICKS
the radius of a mode/viewport. Rope or obstacles crossing a direction are
outliers that the median drops.

Asserts per mode/viewport: HEAD (BALL_SIZE_REV, default worktree) within
max(1 CSS px, 10%) of BALL_SIZE_ORIGINAL (default e430f92, before the
overhaul), and BALL_SIZE_PARENT (default 1f91051, the enlarged TASK-189 ball)
larger than the original. Where the hitbox is bigger than the minimum radius
(classic on desktop) the parent only grew by its wider ring. Writes ball-size.json and before-after.png (4x crops)
into BALL_SIZE_EVIDENCE_DIR when it is set.
"""
from contextlib import ExitStack
import io
import json
import math
import os
from pathlib import Path
import statistics
import unittest

import numpy as np
from PIL import Image, ImageDraw

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot

REV = os.environ.get('BALL_SIZE_REV', 'worktree')
ORIGINAL = os.environ.get('BALL_SIZE_ORIGINAL', 'e430f92')
PARENT = os.environ.get('BALL_SIZE_PARENT', '1f91051')
EVIDENCE = os.environ.get('BALL_SIZE_EVIDENCE_DIR')
VIEWPORTS = list(reversed(render_snapshot.VIEWPORTS))  # desktop, mobile (phone)
MODES = ['bad', 'classic']
TICKS = [60, 180, 300]
DIRECTIONS = 8
# Walk inward from this many times the TASK-189 minimum radius (12 px at 1080)
RMAX_FACTOR = 3
TOLERANCE_CSS_PX = 1
TOLERANCE_RATIO = 0.1
EDGE_DROP_RATIO = 0.5
CROP_CSS_PX = 24
ZOOM = 4

# Centre of the ninja in canvas pixels and canvas pixels per CSS pixel
PROBE_SCRIPT = '''() => {
    const m = ctx.getTransform()
    const k = scale[version]
    const p = m.transformPoint(new DOMPoint((ninja.x + screen.x) * k, (ninja.y + screen.y) * k))
    return {x: p.x, y: p.y, density: canvas.width / canvas.getBoundingClientRect().width,
            hitbox: ninja.radius * k * Math.hypot(m.a, m.b), x_world: ninja.x, y_world: ninja.y}
}'''


def brightness(img, x, y):
    h, w = img.shape[:2]
    x, y = int(round(x)), int(round(y))
    if 0 <= x < w and 0 <= y < h:
        return int(img[y, x].astype(int).sum())
    return 0


def outer_radius(img, cx, cy, rmax):
    """Median over DIRECTIONS of the outer edge, in canvas pixels, plus the samples.

    The ring is the brightest thing in the ball (teal on blue before the
    overhaul, the bloomed cyan ring with a pale core after), so its outer edge
    is a sharp brightness drop going outward, also on top of trail and bloom
    haze. The outermost drop of at least EDGE_DROP_RATIO of the largest one is
    taken, so the core-to-ring step inside a wide ring does not count as the edge.
    """
    samples = []
    for i in range(DIRECTIONS):
        a = 2 * math.pi * i / DIRECTIONS
        dx, dy = math.cos(a), math.sin(a)
        drops = []
        for d in range(int(math.ceil(rmax))):
            drops.append((brightness(img, cx + dx * d, cy + dy * d)
                          - brightness(img, cx + dx * (d + 1), cy + dy * (d + 1)), d + 0.5))
        largest = max(drop for drop, _ in drops)
        samples.append(max(edge for drop, edge in drops if drop >= EDGE_DROP_RATIO * largest))
    return statistics.median(samples), samples


def run(rev):
    """Captures and probes for every viewport/mode/tick of one revision."""
    result = {'captures': {}, 'page_errors': []}
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        result['rev'] = rev_id
        url, browser = start_browser_test(root, stack.callback)
        for vp in VIEWPORTS:
            script = render_snapshot.input_script(render_snapshot.SEED, TICKS[-1], vp['width'], vp['height'])
            for mode in MODES:
                context = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                              device_scale_factor=vp['dpr'],
                                              is_mobile=vp['touch'], has_touch=vp['touch'])
                context.add_init_script(SEED_SCRIPT % render_snapshot.SEED)
                context.add_init_script(render_snapshot.CLOCK_SCRIPT)
                page = context.new_page()
                page.on('pageerror', lambda e, n=vp['name']: result['page_errors'].append(f'{n}: {e}'))
                page.goto(url + 'index.html', wait_until='load')
                render_snapshot.boot_frozen(page)
                page.evaluate(render_snapshot.SETUP_SCRIPT, [script, vp['touch']])
                page.evaluate('mode => startGame(mode)', mode)
                for tick in TICKS:
                    page.evaluate(render_snapshot.ADVANCE_SCRIPT, tick)
                    png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
                    probe = page.evaluate(PROBE_SCRIPT)
                    result['captures'][(vp['name'], mode, tick)] = {'png': png, 'probe': probe}
                context.close()
    return result


def measure(result):
    """{viewport: {mode: {radius_css, per_tick}}} from run()."""
    out = {}
    for (vp_name, mode, tick), c in result['captures'].items():
        vp = next(v for v in VIEWPORTS if v['name'] == vp_name)
        img = np.asarray(Image.open(io.BytesIO(c['png'])).convert('RGB'))
        p = c['probe']
        rmax = RMAX_FACTOR * max(12 / 1080 * img.shape[0], p['hitbox'])
        radius, samples = outer_radius(img, p['x'], p['y'], rmax)
        entry = out.setdefault(vp_name, {}).setdefault(mode, {'per_tick': {}})
        entry['per_tick'][tick] = {'radius_canvas_px': radius, 'radius_css_px': radius / p['density'],
                                   'directions_canvas_px': samples, 'centre_canvas_px': [p['x'], p['y']],
                                   'hitbox_radius_css_px': p['hitbox'] / p['density'],
                                   'ninja_world': [p['x_world'], p['y_world']]}
    for modes in out.values():
        for entry in modes.values():
            entry['radius_css_px'] = statistics.median(t['radius_css_px'] for t in entry['per_tick'].values())
    return out


def crop(result, key):
    c = result['captures'][key]
    img = Image.open(io.BytesIO(c['png'])).convert('RGB')
    p = c['probe']
    half = CROP_CSS_PX * p['density'] / 2
    box = [int(round(p['x'] - half)), int(round(p['y'] - half)),
           int(round(p['x'] + half)), int(round(p['y'] + half))]
    tile = img.crop(box)
    size = CROP_CSS_PX * ZOOM * 2
    return tile.resize((size, size), Image.NEAREST)


def before_after(results, labels, path):
    """Rows: viewport/mode at TICKS[0]; columns: the revisions."""
    keys = [(vp['name'], mode, TICKS[0]) for vp in VIEWPORTS for mode in MODES]
    tile = CROP_CSS_PX * ZOOM * 2
    label_h, pad = 24, 8
    sheet = Image.new('RGB', (pad + len(results) * (tile + pad) + 160, label_h + len(keys) * (tile + pad) + pad),
                      (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for j, label in enumerate(labels):
        draw.text((pad + j * (tile + pad), 6), label, fill=(255, 255, 255))
    for i, key in enumerate(keys):
        y = label_h + i * (tile + pad)
        for j, result in enumerate(results):
            sheet.paste(crop(result, key), (pad + j * (tile + pad), y))
        draw.text((pad + len(results) * (tile + pad), y + tile // 2), f'{key[0]} {key[1]}\ntick {key[2]}',
                  fill=(255, 255, 255))
    sheet.save(path)


class BallSizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {name: run(rev) for name, rev in
                       [('original', ORIGINAL), ('parent', PARENT), ('head', REV)]}
        cls.sizes = {name: measure(r) for name, r in cls.results.items()}
        cls.report = {'revs': {name: r['rev'] for name, r in cls.results.items()},
                      'ticks': TICKS, 'directions': DIRECTIONS,
                      'limit': f'|head - original| <= max({TOLERANCE_CSS_PX} CSS px, '
                               f'{TOLERANCE_RATIO:.0%} of original); parent > original',
                      'page_errors': {name: r['page_errors'] for name, r in cls.results.items()},
                      'viewports': {}}
        for vp in VIEWPORTS:
            for mode in MODES:
                orig, parent, head = (cls.sizes[n][vp['name']][mode]['radius_css_px']
                                      for n in ('original', 'parent', 'head'))
                limit = max(TOLERANCE_CSS_PX, TOLERANCE_RATIO * orig)
                cls.report['viewports'].setdefault(
                    f'{vp["name"]} {vp["width"]}x{vp["height"]}@{vp["dpr"]}', {})[mode] = {
                    'outer_radius_css_px': {'original': orig, 'parent': parent, 'head': head},
                    'limit_css_px': limit,
                    'head_minus_original_css_px': head - orig,
                    'head_within_limit': abs(head - orig) <= limit,
                    'parent_larger': parent > orig,
                    'detail': {n: cls.sizes[n][vp['name']][mode] for n in ('original', 'parent', 'head')}}
        if EVIDENCE:
            out = Path(EVIDENCE)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'ball-size.json').write_text(json.dumps(cls.report, indent=1) + '\n')
            before_after([cls.results[n] for n in ('original', 'parent', 'head')],
                         [f'e430f92 (original) {cls.results["original"]["rev"][:7]}',
                          f'parent {cls.results["parent"]["rev"][:7]}',
                          f'HEAD {cls.results["head"]["rev"][:16]}'], out / 'before-after.png')

    def test_no_page_errors(self):
        for name, r in self.results.items():
            self.assertEqual(r['page_errors'], [], name)

    def test_head_matches_original(self):
        for vp, modes in self.report['viewports'].items():
            for mode, e in modes.items():
                r = e['outer_radius_css_px']
                print(f'{vp} {mode}: original {r["original"]:.2f} parent {r["parent"]:.2f} '
                      f'head {r["head"]:.2f} CSS px (limit +-{e["limit_css_px"]:.2f})')
                self.assertTrue(e['head_within_limit'], f'{vp} {mode}: {r}')

    def test_parent_was_larger(self):
        for vp, modes in self.report['viewports'].items():
            for mode, e in modes.items():
                self.assertTrue(e['parent_larger'], f'{vp} {mode}: {e["outer_radius_css_px"]}')


if __name__ == '__main__':
    unittest.main()
