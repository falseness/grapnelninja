"""Measure actual drawHook pixels against the parent, under a frozen clock.

Save the baseline before editing and supply it via DOT_PARENT or --parent.
DOT_EVIDENCE_DIR preserves JSON, native gameplay captures and 4x crops.
An 8x raster avoids quantization bias for the subpixel phone tip. Radius is
median of eight alpha-boundary rays, in logical screen pixels, not JS ratios.
"""
import argparse
from contextlib import ExitStack
import hashlib
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
from render_snapshot import CLOCK_SCRIPT, boot_frozen, png_bytes, SETUP_SCRIPT, ADVANCE_SCRIPT, input_script

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
    let strokeWidth = null, centre = null
    try {
        ctx = scratch.getContext('2d')
        ctx.setTransform(8*scale[version],0,0,8*scale[version],256,256)
        const stroke = ctx.stroke.bind(ctx), arc = ctx.arc.bind(ctx)
        ctx.stroke = (...args) => {strokeWidth = ctx.lineWidth*scale[version]; return stroke(...args)}
        ctx.arc = (...args) => {centre = args.slice(0,2); return arc(...args)}
        if (attached === 'rope') { hook.pos = [[-10,0]]; ninja.x=10;ninja.y=0;hook.draw() }
        else hook.drawHook()
    } finally { ctx = original }
    return {png: scratch.toDataURL('image/png'), ropeWidth: hook.getWidth()*scale[version], strokeWidth, centre}
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


NATIVE = '''() => {
    grapnel.throwed = grapnel.grappled = true;
    // A fixed attached fixture, drawn by the full production renderer without physics steps.
    grapnel.pos = [[ninja.x + 110/scale[version], ninja.y - 70/scale[version]]];
    draw();
    const transform = ctx.getTransform(), dpr = canvas.width/innerWidth;
    const point = new DOMPoint((grapnel.pos[0][0]+screen.x)*scale[version],
        (grapnel.pos[0][1]+screen.y)*scale[version]).matrixTransform(transform);
    return {png: __snap.capture(), centre: [point.x/dpr,point.y/dpr],
        state: {player:[ninja.x,ninja.y],camera:[screen.x,screen.y],rope:grapnel.pos,clock:__snap.now}};
}'''


def capture(rev, out, label):
    images, values, native = {}, {}, {}
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
                if touch:
                    context.add_init_script("Object.defineProperty(window,'devicePixelRatio',{get:()=>2})")
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                for mode in ['bad', 'classic']:
                    page.goto(url)
                    boot_frozen(page)
                    page.evaluate(SETUP_SCRIPT, [input_script(1,60,width,height), touch])
                    page.evaluate('mode=>startGame(mode)', mode)
                    page.evaluate(ADVANCE_SCRIPT, 60)
                    scene = page.evaluate(NATIVE)
                    path = f'{label}-{viewport}-{mode}-native.png'
                    (out/path).write_bytes(png_bytes(scene.pop('png')))
                    scene['path'] = path
                    native[f'{viewport}-{mode}'] = scene
                    for kind in ([] if label == 'reference' else ['anchor', 'tip', 'rope']):
                        key = f'{viewport}-{mode}-{kind}'
                        result = page.evaluate(SCENE, [mode, 'rope' if kind == 'rope' else kind == 'anchor'])
                        img = Image.open(io.BytesIO(png_bytes(result['png']))).convert('RGBA')
                        images[key] = img
                        img.save(out/f'{label}-{key}-8x.png')
                        values[key] = dict(radius(img) if kind != 'rope' else {},
                            rope_width=result['ropeWidth'], stroke_width=result['strokeWidth'], centre=result['centre'])
                assert not errors, errors
            finally:
                context.close()
    return rev_id, values, images, native


def probe(out, parent='HEAD^', head='worktree'):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    parent_rev, before, a, na = capture(parent, out, 'parent')
    head_rev, after, b, nb = capture(head, out, 'final')
    reference_rev, _, _, nr = capture('e430f92', out, 'reference')
    report = {'parent': parent_rev, 'head': head_rev,
              'method': 'median of 8 alpha >= 128 rays; 8x raster; screen-pixel radii',
              'captures': {}}
    sheet = Image.new('RGB', (600, len(a)*150), '#101020')
    pen = ImageDraw.Draw(sheet)
    for row, key in enumerate(a):
        entry = {'parent': before[key], 'head': after[key],
                 'identical_pixels': bool(np.array_equal(np.asarray(a[key]), np.asarray(b[key])))}
        if 'radius' in before[key]:
            entry['ratio'] = after[key]['radius']/before[key]['radius']
        if key.endswith('anchor'):
            entry['stroke_ratio'] = after[key]['stroke_width']/before[key]['stroke_width']
        report['captures'][key] = entry
        for col, (label, images) in enumerate([('parent', a), ('HEAD', b)]):
            # 8x source -> 4x crop, with nearest-neighbour display of raster edges.
            crop = images[key].crop((136,136,376,376)).resize((120,120), Image.NEAREST)
            sheet.paste(crop, (col*300+90,row*150+25), crop)
            pen.text((col*300+5,row*150+5), f'{key} {label} (4x)', fill='white')
    sheet.save(out/'before-after.png')
    (out/'dot.json').write_text(json.dumps(report, indent=2)+'\n')
    manifest = dict(baseline=parent_rev, final_capture_revision=head_rev, reference=reference_rev,
        seed=1, tick=60, viewports={'desktop':[1920,1080,1], 'phone':[844,390,3]},
        phone_backing_dpr=2, native={'parent':na,'final':nb,'reference':nr},
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [*Path('..').glob('*.js'), *Path('../sprites').glob('*.js'),
                      *Path('../render').glob('*.js'), Path('test_grapnel_dot.py')]},
        outputs=sorted(p.name for p in out.glob('*.png')))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for key, value in report['captures'].items():
        if key.endswith('anchor'):
            assert .45 <= value['ratio'] <= .55, (key, value)
            assert value['stroke_ratio'] == .5, (key, value)
            assert value['parent']['centre'] == value['head']['centre'], (key,value)
        else:
            assert value['identical_pixels'], (key,value)
            assert np.asarray(a[key])[:,:,3].max() > 0, key
        assert value['parent']['rope_width'] == value['head']['rope_width'], (key, value)
        print(f"PASS {key}: {json.dumps(value)}", flush=True)
    for key in na:
        assert na[key]['state'] == nb[key]['state'], key
        assert na[key]['centre'] == nb[key]['centre'], key
        x,y = nb[key]['centre']
        parent_pixels = np.asarray(Image.open(out/na[key]['path']))
        final_pixels = np.asarray(Image.open(out/nb[key]['path']))
        changed = np.any(parent_pixels != final_pixels, axis=2)
        dpr = 2 if key.startswith('phone') else 1
        yy,xx = np.where(changed)
        assert len(xx) > 0, (key,'native ring must visibly change')
        assert max(abs(xx-x*dpr)) < 12*dpr and max(abs(yy-y*dpr)) < 12*dpr, (key,'changes outside anchor')
        # Native crop keeps original backing pixels; CSS-sized image is also archived.
        for label, records in [('parent',na),('final',nb),('reference',nr)]:
            img = Image.open(out/records[key]['path'])
            dpr = 2 if key.startswith('phone') else 1
            img.resize((img.width//dpr,img.height//dpr),Image.LANCZOS).save(out/f'{label}-{key}-css.png')
            cx,cy=records[key]['centre']
            img.crop((int(cx*dpr)-30,int(cy*dpr)-30,int(cx*dpr)+30,int(cy*dpr)+30)).save(out/f'{label}-{key}-native-ring.png')
        print(f'PASS {key}: native anchor centre, rope attachment, player, camera and clock identical',flush=True)
    sheet.save(out/'raster-comparison.png')
    combined = Image.new('RGB', (1200, 1200), '#101020')
    pen = ImageDraw.Draw(combined)
    for row,key in enumerate(na):
        for col,label in enumerate(['reference','parent','final']):
            pen.text((col*400+5,row*300+5),f'{key} {label}',fill='white')
            scene=Image.open(out/f'{label}-{key}-css.png').convert('RGB')
            scene.thumbnail((390,200))
            combined.paste(scene,(col*400+5,row*300+25))
            ring=Image.open(out/f'{label}-{key}-native-ring.png').convert('RGB')
            combined.paste(ring,(col*400+5,row*300+230))
            pen.text((col*400+75,row*300+240),'ring: native backing pixels',fill='white')
    combined.save(out/'before-after.png')
    manifest['outputs'] = sorted(p.name for p in out.glob('*.png'))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return report


class GrapnelDotTest(unittest.TestCase):
    def test_anchor_halved_tip_and_rope_unchanged(self):
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
