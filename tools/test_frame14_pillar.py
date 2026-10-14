"""Browser regression test: the Frame 14 right pillar stands on the bad-mode ground.

Frame 5 and the other two Frame 14 elements keep their geometry.
"""
from pathlib import Path
import json
import os
import sys
import unittest

# Allow `python3 -m unittest tools/test_frame14_pillar.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('FRAME14_EVIDENCE_DIR', ROOT / 'artifacts' / 'frame14'))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

VIEWPORT = (1920, 1080)
REFERENCE = (1120, 630)
# Bad-mode ground top in reference pixels (2 * height of a 2.2 * height world).
GROUND_TOP = REFERENCE[1] * 2 / 2.2
SEED = 412
TOLERANCE = 1e-6
CONTACT_TOLERANCE = 0.5

# Rects: x, y, width, height in reference pixels, as at HEAD before TASK-412.
FRAME5 = [
    (688.5 + 115.03, 76.5, 52, 266),
    (393.5, 188.5, 52, 365),
    (445.5, 188.5, 128, 43),
]
FRAME14_OLD_PILLAR = (688.5 + 116, 287.5, 52, 266)
FRAME14_UNCHANGED = [
    (333.5, 76.5, 52, 323),
    (385.5, 356.5, 187, 43),
]

SETUP = '''(seed) => {
    let s = seed >>> 0
    Math.random = () => (s = (1664525 * s + 1013904223) >>> 0) / 4294967296
    startGame('bad')
    cancelAnimationFrame(game)
}'''

MEASURE = '''() => {
    const box = e => {
        const p = e.getPoints()
        return {left: Math.min(...p.map(p => p.x)), right: Math.max(...p.map(p => p.x)),
                top: Math.min(...p.map(p => p.y)), bottom: Math.max(...p.map(p => p.y))}
    }
    const create = t => elementsFactory.create({min: 0, max: 0}, {min: 0, max: 0}, t)
        .map(e => Object.assign({type: e.constructor.name}, box(e)))
    return {width, height, scaleBad: scale.bad,
        groundTop: Math.min(...floors[0].elements.map(e => box(e).top)),
        frame5Rects: create('frame5Rects'), frame14Rects: create('frame14Rects')}
}'''

SHOW = '''(template) => {
    floors[1].creations = [{type: template, chance: 100}]
    floors[1].generatePrimaryElements()
    draw()
}'''


def to_frame(run, world):
    """World units -> reference frame px."""
    return {k: world[k] * REFERENCE[0 if k in ('left', 'right') else 1] * run['scaleBad']
            / run['width' if k in ('left', 'right') else 'height'] for k in ('left', 'right', 'top', 'bottom')}


def describe(run):
    """Per-element x, y, width, height, bottom in frame px and world units."""
    out = {'viewport': VIEWPORT, 'logical': [run['width'], run['height']], 'scaleBad': run['scaleBad'],
           'seed': SEED, 'groundTop': {'world': run['groundTop'],
                                       'frame': run['groundTop'] * REFERENCE[1] * run['scaleBad'] / run['height']}}
    for name in ('frame5Rects', 'frame14Rects'):
        out[name] = []
        for e in run[name]:
            f = to_frame(run, e)
            out[name].append({'type': e['type'],
                              'world': {'x': e['left'], 'y': e['top'], 'width': e['right'] - e['left'],
                                        'height': e['bottom'] - e['top'], 'bottom': e['bottom']},
                              'frame': {'x': f['left'], 'y': f['top'], 'width': f['right'] - f['left'],
                                        'height': f['bottom'] - f['top'], 'bottom': f['bottom']}})
    return out


def open_page(browser, url):
    page = browser.new_page(viewport={'width': VIEWPORT[0], 'height': VIEWPORT[1]})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text)
            if message.type == 'error' else None)
    page.goto(url)
    wait_for_boot(page)
    page.evaluate(SETUP, SEED)
    return page, errors


class Frame14PillarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self):
        page, errors = open_page(self.browser, self.url)
        self.addCleanup(page.close)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def assertRect(self, actual, rect, label):
        x, y, w, h = rect
        for key, value in (('x', x), ('y', y), ('width', w), ('height', h), ('bottom', y + h)):
            self.assertAlmostEqual(actual[key], value, delta=TOLERANCE, msg=f'{label}.{key}')

    def test_pillar_touches_ground(self):
        geometry = describe(self.open().evaluate(MEASURE))
        ground = geometry['groundTop']['frame']
        self.assertAlmostEqual(ground, GROUND_TOP, delta=TOLERANCE)

        pillar, *rest = [e['frame'] for e in geometry['frame14Rects']]
        gap = abs(pillar['bottom'] - ground)
        print(f'PILLAR bottom={pillar["bottom"]:.6f} groundTop={ground:.6f} gap={gap:.3e}', flush=True)
        self.assertLessEqual(gap, CONTACT_TOLERANCE)
        x, y, w, _ = FRAME14_OLD_PILLAR
        for key, value in (('x', x), ('y', y), ('width', w)):
            self.assertAlmostEqual(pillar[key], value, delta=TOLERANCE, msg=f'frame14[0].{key}')
        print(f'PILLAR top={pillar["y"]:.6f} unchanged', flush=True)
        for i, (actual, rect) in enumerate(zip(rest, FRAME14_UNCHANGED), 1):
            self.assertRect(actual, rect, f'frame14[{i}]')
            print(f'FRAME14[{i}] unchanged {actual}', flush=True)

        self.assertEqual(len(geometry['frame5Rects']), len(FRAME5))
        for i, (element, rect) in enumerate(zip(geometry['frame5Rects'], FRAME5)):
            self.assertRect(element['frame'], rect, f'frame5[{i}]')
            print(f'FRAME5[{i}] identical to HEAD {element["frame"]}', flush=True)
        self.assertEqual([e['type'] for e in geometry['frame14Rects']], ['Trampoline'] * 3)

    def test_screenshots(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        for template, name in (('frame14Rects', 'frame14.png'), ('frame5Rects', 'frame5.png')):
            page = self.open()
            page.evaluate(SHOW, template)
            page.screenshot(path=str(EVIDENCE / name))
            print(f'SCREENSHOT {EVIDENCE / name}', flush=True)


if __name__ == '__main__':
    unittest.main()
