"""Browser regression test: the Frame 10 lower danger block stands on the bad-mode ground.

The Frame 10 upper block and green platform, and all of Frame 11, keep their geometry.
"""
from pathlib import Path
import os
import sys
import unittest

# Allow `python3 -m unittest tools/test_frame10_ground.py` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('FRAME10_EVIDENCE_DIR', ROOT / 'artifacts' / 'frame10'))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

VIEWPORT = (1920, 1080)
REFERENCE = (1120, 630)
# Bad-mode ground top in reference pixels (2 * height of a 2.2 * height world).
GROUND_TOP = REFERENCE[1] * 2 / 2.2
SEED = 413
TOLERANCE = 1e-6
CONTACT_TOLERANCE = 0.5

# Elements: x, y, width, height in reference pixels, as at HEAD before TASK-413.
# Order: green platform, lower danger block, upper danger block.
FRAME10_GREEN = (119.5, 288.5, 397, 52)
FRAME10_OLD_LOWER = (292, 427.5, 52, 126)
FRAME10_UPPER = (292, 161.5, 52, 126)
FRAME11 = [
    (119.5, 288.5, 397, 52),
    (292, 341.5, 52, 126),
    (292, 75.5, 52, 126),
]
TEMPLATES = ('frame10Elements', 'frame11Elements')

SETUP = '''(seed) => {
    let s = seed >>> 0
    Math.random = () => (s = (1664525 * s + 1013904223) >>> 0) / 4294967296
    startGame('bad')
    cancelAnimationFrame(game)
}'''

MEASURE = '''(templates) => {
    const box = e => {
        const p = e.getPoints()
        return {left: Math.min(...p.map(p => p.x)), right: Math.max(...p.map(p => p.x)),
                top: Math.min(...p.map(p => p.y)), bottom: Math.max(...p.map(p => p.y))}
    }
    const create = t => elementsFactory.create({min: 0, max: 0}, {min: 0, max: 0}, t)
        .map(e => Object.assign({type: e.constructor.name}, box(e)))
    const result = {width, height, scaleBad: scale.bad,
        groundTop: Math.min(...floors[0].elements.map(e => box(e).top))}
    for (const t of templates) result[t] = create(t)
    return result
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
    for name in TEMPLATES:
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


def measure(page):
    return describe(page.evaluate(MEASURE, list(TEMPLATES)))


class Frame10GroundTests(unittest.TestCase):
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

    def test_lower_block_touches_ground(self):
        geometry = measure(self.open())
        ground = geometry['groundTop']['frame']
        self.assertAlmostEqual(ground, GROUND_TOP, delta=TOLERANCE)

        self.assertEqual(len(geometry['frame10Elements']), 3)
        green, lower, upper = [e['frame'] for e in geometry['frame10Elements']]
        gap = abs(lower['bottom'] - ground)
        print(f'LOWER bottom={lower["bottom"]:.6f} groundTop={ground:.6f} gap={gap:.3e}', flush=True)
        self.assertLessEqual(gap, CONTACT_TOLERANCE)
        x, y, w, _ = FRAME10_OLD_LOWER
        for key, value in (('x', x), ('y', y), ('width', w)):
            self.assertAlmostEqual(lower[key], value, delta=TOLERANCE, msg=f'frame10 lower.{key}')
        print(f'LOWER top={lower["y"]:.6f} unchanged', flush=True)
        self.assertRect(upper, FRAME10_UPPER, 'frame10 upper')
        print(f'UPPER unchanged {upper}', flush=True)
        self.assertRect(green, FRAME10_GREEN, 'frame10 green')
        print(f'GREEN unchanged {green}', flush=True)

        self.assertEqual(len(geometry['frame11Elements']), len(FRAME11))
        for i, (element, rect) in enumerate(zip(geometry['frame11Elements'], FRAME11)):
            self.assertRect(element['frame'], rect, f'frame11[{i}]')
            print(f'FRAME11[{i}] identical to HEAD {element["frame"]}', flush=True)
        self.assertEqual([e['type'] for e in geometry['frame10Elements']],
                         [e['type'] for e in geometry['frame11Elements']])

    def test_screenshots(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        for template, name in (('frame10Elements', 'frame10.png'), ('frame11Elements', 'frame11.png')):
            page = self.open()
            page.evaluate(SHOW, template)
            page.screenshot(path=str(EVIDENCE / name))
            print(f'SCREENSHOT {EVIDENCE / name}', flush=True)


if __name__ == '__main__':
    unittest.main()
