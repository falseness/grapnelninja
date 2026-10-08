"""Measure actual drawHook pixels against the parent, under a frozen clock.

Run directly with --parent HEAD before committing, or use the default HEAD^
post-commit. DOT_EVIDENCE_DIR preserves the unittest's JSON and 4x crops.
An 8x raster avoids quantization bias for the subpixel phone tip. Radius is
median of eight alpha-boundary rays, in logical screen pixels, not JS ratios.
"""
import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
from render_snapshot import CLOCK_SCRIPT, boot_frozen, png_bytes

ZOOM = 8
SIZE = 512
SCENE = '''([mode, attached]) => {
    startGame(mode)
    screen.x = screen.y = 0
    const hook = new Grapnel({})
    hook.throwed = true; hook.grappled = attached
    hook.pos = [[0, 0]]
    const scratch = document.createElement('canvas')
    scratch.width = scratch.height = 512
    const original = ctx
    try {
        ctx = scratch.getContext('2d')
        ctx.setTransform(8*scale[version],0,0,8*scale[version],256,256)
        hook.drawHook()
    } finally { ctx = original }
    return {png: scratch.toDataURL('image/png'), ropeWidth: hook.getWidth()*scale[version]}
}'''


def radius(image):
    alpha = np.asarray(image.convert('RGBA'))[:, :, 3]
    distances = np.arange(0, SIZE / 2 - 1, .05)
    radii = []
    for angle in np.arange(8) * np.pi / 4:
        x = np.floor(SIZE/2 + distances*np.cos(angle)).astype(int)
        y = np.floor(SIZE/2 + distances*np.sin(angle)).astype(int)
        hits = distances[alpha[y, x] >= 128]
        if not len(hits):
            raise AssertionError('drawHook has no visible pixels on a measurement ray')
        radii.append(float(hits[-1] / ZOOM))
    return {'radius': float(np.median(radii)), 'eight_radii': radii}


def capture(rev):
    images, values = {}, {}
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for viewport, width, height, touch in [('desktop', 1920, 1080, False),
                                               ('phone', 844, 390, True)]:
            context = browser.new_context(viewport={'width': width, 'height': height},
                                          device_scale_factor=3 if touch else 1,
                                          is_mobile=touch, has_touch=touch)
            try:
                context.add_init_script(SEED_SCRIPT % 1)
                context.add_init_script(CLOCK_SCRIPT)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url)
                boot_frozen(page)
                for mode in ['bad', 'classic']:
                    for kind in ['anchor', 'tip']:
                        key = f'{viewport}-{mode}-{kind}'
                        result = page.evaluate(SCENE, [mode, kind == 'anchor'])
                        img = Image.open(io.BytesIO(png_bytes(result['png']))).convert('RGBA')
                        images[key] = img
                        values[key] = dict(radius(img), rope_width=result['ropeWidth'])
                assert not errors, errors
            finally:
                context.close()
    return rev_id, values, images


def probe(out, parent='HEAD^', head='worktree'):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    parent_rev, before, a = capture(parent)
    head_rev, after, b = capture(head)
    report = {'parent': parent_rev, 'head': head_rev,
              'method': 'median of 8 alpha >= 128 rays; 8x raster; screen-pixel radii',
              'captures': {}}
    sheet = Image.new('RGB', (600, len(a)*150), '#101020')
    pen = ImageDraw.Draw(sheet)
    for row, key in enumerate(a):
        entry = {'parent': before[key], 'head': after[key],
                 'ratio': after[key]['radius']/before[key]['radius']}
        report['captures'][key] = entry
        for col, (label, images) in enumerate([('parent', a), ('HEAD', b)]):
            # 8x source -> 4x crop, with nearest-neighbour display of raster edges.
            crop = images[key].crop((136,136,376,376)).resize((120,120), Image.NEAREST)
            sheet.paste(crop, (col*300+90,row*150+25), crop)
            pen.text((col*300+5,row*150+5), f'{key} {label} (4x)', fill='white')
    sheet.save(out/'before-after.png')
    (out/'dot.json').write_text(json.dumps(report, indent=2)+'\n')
    for key, value in report['captures'].items():
        assert .45 <= value['ratio'] <= .55, (key, value)
        assert value['parent']['rope_width'] == value['head']['rope_width'], (key, value)
        print(f"PASS {key}: HEAD/parent={value['ratio']:.4f}; rope width unchanged", flush=True)
    return report


class GrapnelDotTest(unittest.TestCase):
    def test_radii_halved_and_rope_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe(os.environ.get('DOT_EVIDENCE_DIR', tmp),
                  os.environ.get('DOT_PARENT', 'HEAD^'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--parent', default='HEAD^')
    parser.add_argument('--head', default='worktree')
    args = parser.parse_args()
    probe(args.out, args.parent, args.head)
