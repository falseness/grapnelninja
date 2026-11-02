"""TASK-867: tools/make_screenshots.py compose step on synthetic frames (no browser).

    python3 -m unittest discover -s tools -p test_make_screenshots.py -v
"""
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_screenshots as ms


def noise(size, seed):
    rnd = random.Random(seed)
    return Image.frombytes('RGB', size, bytes(rnd.getrandbits(8) for _ in range(size[0] * size[1] * 3)))


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.frames = self.tmp / 'frames'
        self.release = self.tmp / 'release'
        self.saved = (ms.PLAN, ms.ROOT)
        ms.ROOT = self.tmp
        self.addCleanup(lambda: (setattr(ms, 'PLAN', self.saved[0]), setattr(ms, 'ROOT', self.saved[1])))

    def frames_for(self, scenes, sizes):
        meta = {'frames': {}}
        for vp, size in sizes.items():
            (self.frames / vp).mkdir(parents=True, exist_ok=True)
            for i, scene in enumerate(scenes):
                for lang in ('en', 'ru'):
                    path = self.frames / vp / f'{scene}-{lang}.png'
                    noise(size, f'{scene}{lang}{vp}').save(path)
                    meta['frames'][f'{vp}/{scene}-{lang}'] = {'file': f'{vp}/{path.name}', 'label': scene}
        (self.frames / 'frames.json').write_text(json.dumps(meta))

    def test_01_exact_sizes_and_names(self):
        self.frames_for(('a', 'b'), {'16x9': (512, 288), '4x3': (384, 288)})
        ms.PLAN = {'p': [('shot-160x90', 160, 90, '16x9', ('a', 'b'), ('en', 'ru'), ('png',), None),
                         ('std-152x114', 152, 114, '4x3', ('a',), ('en',), ('png', 'jpg'), None)]}
        report = ms.compose(self.frames, self.release)
        names = sorted(p.name for p in (self.release / 'p' / 'screenshots').iterdir())
        self.assertEqual(names, ['shot-160x90-01-a-en.png', 'shot-160x90-01-a-ru.png', 'shot-160x90-02-b-en.png',
                                 'shot-160x90-02-b-ru.png', 'std-152x114-01-a-en.png'])
        for r in report:
            self.assertEqual(Image.open(self.tmp / r['file']).size, (r['width'], r['height']))
            self.assertGreaterEqual(r['downscale'], 2.0)

    def test_02_refuses_upscale_and_wrong_aspect(self):
        self.frames_for(('a',), {'16x9': (300, 169)})
        ms.PLAN = {'p': [('shot-160x90', 160, 90, '16x9', ('a',), ('en',), ('png',), None)]}
        with self.assertRaises(SystemExit):
            ms.compose(self.frames, self.release)
        self.frames_for(('a',), {'16x9': (512, 384)})
        with self.assertRaises(SystemExit):
            ms.compose(self.frames, self.release)

    def test_03_jpeg_under_byte_cap(self):
        self.frames_for(('a',), {'16x9': (1024, 576)})
        ms.PLAN = {'p': [('shot-480x270', 480, 270, '16x9', ('a',), ('en',), ('png', 'jpg'), 200000)]}
        report = ms.compose(self.frames, self.release)
        self.assertEqual(report[0]['format'], 'jpg')
        self.assertLessEqual(report[0]['bytes'], 200000)
        ms.PLAN = {'p': [('shot-480x270', 480, 270, '16x9', ('a',), ('en',), ('png',), 200000)]}
        with self.assertRaises(SystemExit):
            ms.compose(self.frames, self.release)

    def test_04_plan_matches_image_spec(self):
        spec = json.loads((self.saved[1] / 'artifacts/TASK-865/image-spec.json').read_text())
        for portal, slots in self.saved[0].items():
            sizes = {(e['width'], e['height']) for e in spec['portals'][portal]['images'] if 'screenshot' in e['name']}
            self.assertEqual({(s[1], s[2]) for s in slots}, sizes, portal)


if __name__ == '__main__':
    unittest.main()
