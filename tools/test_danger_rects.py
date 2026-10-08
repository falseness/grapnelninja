"""Frozen-clock colour probes in both modes, plus full-scene parent/HEAD pairs.

Run: cd tools && python3 -m unittest test_danger_rects -v
DANGER_BASE optionally pins the parent before committing. Evidence defaults to
artifacts/TASK-210. Isolated factory-drawn probes use a black backdrop so nearby
orange spill cannot contaminate the unchanged-obstacle comparison. We compare
ALL RGBA pixels of triangles, green trampolines and blue cubes, not just swatches.
Full gameplay captures retain all effects, camera, layout and seeded input.
"""
import base64
import colorsys
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import ROOT, SEED_SCRIPT, export_rev
import render_snapshot as snap
import danger_gallery

OUT = Path(os.environ.get('DANGER_EVIDENCE_DIR', ROOT / 'artifacts/TASK-210'))
PROBE = '''() => {
    const oldScreen = {x: screen.x, y: screen.y}, oldScale = scale[version]
    screen.x = screen.y = 0
    scale[version] = 1
    const factory = new RectFactory()
    const frame = new Frame13ElementsFactory()
    const green = frame.createGreenTrampolineRect({x: 0, y: 0, width: 8, height: 12})
    const cube = frame.createBlueSquare()
    const triangle = frame.createTriangle({max: height})
    const objects = {
        danger_tall: factory.create(80, 80, 120, 160),
        danger_wide: factory.create(80, 80, 160, 120),
        triangle, green, cube
    }
    const samples = {}
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    for (const [name, element] of Object.entries(objects)) {
        element.x = 80
        element.y = 80
        ctx.clearRect(0, 0, canvas.width, canvas.height)
        ctx.fillStyle = '#000'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        element.draw()
        const png = document.createElement('canvas')
        png.width = png.height = 400
        png.getContext('2d').drawImage(canvas, 0, 0)
        samples[name] = {
            png: png.toDataURL(),
            danger: element.isDangerRect === true,
            light: visualEffects.lightmap.getElementLightColor(element),
            edge: [...ctx.getImageData(78, 130, 1, 1).data].slice(0, 3),
            fill: [...ctx.getImageData(90, 130, 1, 1).data].slice(0, 3)
        }
    }
    // Factory tags survive palette changes, including another obstacle's colour.
    const tagged = objects.danger_tall
    tagged.stroke = STYLE.colors.cube.greenStroke
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    tagged.draw()
    const recoloredFill = [...ctx.getImageData(140, 160, 1, 1).data].slice(0, 3)
    const factoryTags = [Frame6RectFactory, Frame8ElementsFactory,
        Frame10ElementsFactory, Frame11ElementsFactory].map(F => {
        const rects = new F().create({min: 0, max: width}, {min: 0, max: height})
            .filter(e => e instanceof Rect)
        return {factory: F.name, count: rects.length,
                allDanger: rects.every(e => e.isDangerRect === true)}
    })
    ctx.restore()
    screen.x = oldScreen.x; screen.y = oldScreen.y; scale[version] = oldScale
    return {samples, factoryTags, recoloredFill}
}'''


def capture(rev, label):
    result = {'modes': {}, 'page_errors': []}
    with ExitStack() as stack:
        root, result['rev'] = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for mode in ('bad', 'classic'):
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            context.add_init_script(SEED_SCRIPT % snap.SEED)
            context.add_init_script(snap.CLOCK_SCRIPT)
            page = context.new_page()
            page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
            page.goto(url + 'index.html', wait_until='load')
            snap.boot_frozen(page)
            script = snap.input_script(snap.SEED, 900, 1920, 1080)
            page.evaluate(snap.SETUP_SCRIPT, [script, False])
            page.evaluate('mode => startGame(mode)', mode)
            page.evaluate(snap.ADVANCE_SCRIPT, 300)
            images, _ = danger_gallery.capture(page, mode, OUT, label, frames=1)
            images[0].save(OUT / f'{label}-{mode}.png')
            result['modes'][mode] = page.evaluate(PROBE)
            context.close()
    return result


def hsv(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return [round(h * 360, 3), round(s, 5), round(v, 5)]


def pixels(data):
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(data.split(',')[1])))).astype(int)


class DangerRectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        base = os.environ.get('DANGER_BASE', 'HEAD^')
        cls.before = capture(base, 'parent')
        cls.after = capture('worktree', 'head')
        cls.report = {'parent': cls.before['rev'], 'current': cls.after['rev'],
                      'limits': {'hue_degrees': [20, 40], 'edge_saturation_min_exclusive': 0.6,
                                 'other_max_channel_delta': 2}, 'modes': {}}
        for mode in ('bad', 'classic'):
            a = cls.after['modes'][mode]
            r = {'rects': {}, 'others': {}, 'factory_tags': a['factoryTags'],
                 'recolored_fill_rgb': a['recoloredFill']}
            for name, sample in a['samples'].items():
                if name.startswith('danger_'):
                    r['rects'][name] = {key: {'rgb': sample[key], 'hsv': hsv(sample[key])}
                                       for key in ('edge', 'fill')}
                    r['rects'][name].update(danger=sample['danger'], light=sample['light'])
                else:
                    old = cls.before['modes'][mode]['samples'][name]
                    r['others'][name] = {'max_channel_delta': int(np.abs(
                        pixels(sample['png']) - pixels(old['png'])).max()),
                        'danger': sample['danger']}
            cls.report['modes'][mode] = r
        (OUT / 'colors.json').write_text(json.dumps(cls.report, indent=2) + '\n')
        sheet = Image.new('RGB', (1920, 1120))
        draw = ImageDraw.Draw(sheet)
        for row, mode in enumerate(('bad', 'classic')):
            for col, label in enumerate(('parent', 'head')):
                with Image.open(OUT / f'{label}-{mode}.png') as im:
                    sheet.paste(im.resize((960, 540)), (col * 960, row * 560 + 20))
                draw.text((col * 960 + 8, row * 560 + 3), f'{mode} / {label}', fill='white')
        sheet.save(OUT / 'before-after.png')
        print(json.dumps(cls.report, indent=2))

    def test_orange_edge_fill_and_spill(self):
        for mode, report in self.report['modes'].items():
            for name, rect in report['rects'].items():
                with self.subTest(mode=mode, rect=name):
                    self.assertTrue(rect['danger'])
                    for key in ('edge', 'fill'):
                        self.assertGreaterEqual(rect[key]['hsv'][0], 20)
                        self.assertLessEqual(rect[key]['hsv'][0], 40)
                    self.assertGreater(rect['edge']['hsv'][1], 0.6)
                    self.assertEqual(rect['light'], '#ff8a1f')

    def test_other_obstacles_identical(self):
        for mode, report in self.report['modes'].items():
            for name, sample in report['others'].items():
                with self.subTest(mode=mode, obstacle=name):
                    self.assertLessEqual(sample['max_channel_delta'], 2)
                    self.assertFalse(sample['danger'])

    def test_factory_tags_and_recolor(self):
        for mode, report in self.report['modes'].items():
            for factory in report['factory_tags']:
                self.assertGreater(factory['count'], 0)
                self.assertTrue(factory['allDanger'], factory['factory'])
            if mode == 'bad':
                # Centre fill must stay brown when the edge is recoloured green.
                r, g, b = report['recolored_fill_rgb']
                self.assertGreater(r, g)
                self.assertGreater(g, b)

    def test_hatch_clipping_and_interior(self):
        from danger_hatch_probe import collect
        report = collect(OUT)
        for variant, data in report.items():
            for scene, samples in data['samples'].items():
                for sample in samples:
                    with self.subTest(variant=variant, scene=scene, width=sample['width']):
                        self.assertLessEqual(sample['outside_band_max_delta'], 2)
                        self.assertGreater(sample['interior_variance_on'], sample['interior_variance_off'])
        print('PASS hatch: all variants/modes/viewports/rects outside delta <= 2; interior variance on > off')

    def test_no_page_errors(self):
        self.assertEqual(self.before['page_errors'], [])
        self.assertEqual(self.after['page_errors'], [])


if __name__ == '__main__':
    unittest.main()
