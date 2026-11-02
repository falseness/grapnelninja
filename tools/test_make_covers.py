"""Unit tests of the Grapple Over compose step of tools/make_covers.py (no browser).

Synthetic source frames stand in for the captured ones: every spec image is
written at its exact size and format, nothing is upscaled, and too small a
source frame is refused.

    python3 tools/test_make_covers.py -v
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_covers  # noqa: E402


def frames(root, scale=1):
    root.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, (w, h) in {'swing': (960, 540), 'swing-tall': (1920, 1080), 'spire': (960, 540),
                         'mountain': (960, 540)}.items():
        w, h = w * scale // 4, h * scale // 4
        im = Image.new('RGB', (w, h))
        for x in range(0, w, 7):
            for y in range(0, h, 5):
                im.putpixel((x, y), (40 + x % 200, 30, 120 + y % 100))
        im.save(root / f'{name}.png')
        meta[name] = {'file': f'{name}.png', 'size': [w, h], 'ninjaPx': [w * 0.75, h * 0.45],
                      'anchorPx': [w * 0.6, h * 0.2]}
    (root / 'source-frames.json').write_text(json.dumps({'frames': meta}))


SPEC = {'portals': {
    'a': {'images': [
        {'name': 'cover', 'width': 126, 'height': 100, 'format': ['png', 'jpg'], 'max_bytes': None},
        {'name': 'screenshot', 'width': 192, 'height': 108, 'format': ['png'], 'max_bytes': None, 'count': '3-5'},
        {'name': 'icon-64x64', 'width': 64, 'height': 64, 'format': ['png'], 'max_bytes': None}]},
    'b': {'images': [
        {'name': 'portrait', 'width': 108, 'height': 192, 'format': ['png', 'jpg'], 'max_bytes': 2097152},
        {'name': 'standard-screenshot', 'width': 76, 'height': 57, 'format': ['png', 'jpg'], 'max_bytes': 2097152,
         'count': '1-6'}]}}}


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='covers-'))
        (self.tmp / 'spec.json').write_text(json.dumps(SPEC))
        self.root = make_covers.ROOT
        make_covers.ROOT = self.tmp  # report paths relative to the temp dir

    def tearDown(self):
        make_covers.ROOT = self.root
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exact_sizes_no_upscale(self):
        frames(self.tmp / 'frames', scale=4)
        report = make_covers.go_compose(self.tmp / 'frames', self.tmp / 'spec.json', self.tmp / 'release')
        names = sorted((r['portal'], r['name'], r['index']) for r in report)
        self.assertEqual(names, [('a', 'cover', 1), ('a', 'icon-64x64', 1), ('a', 'screenshot', 1),
                                 ('a', 'screenshot', 2), ('a', 'screenshot', 3), ('b', 'portrait', 1),
                                 ('b', 'standard-screenshot', 1), ('b', 'standard-screenshot', 2)])
        for r in report:
            with Image.open(self.tmp / r['file']) as im:
                self.assertEqual(im.size, (r['width'], r['height']), r)
                self.assertEqual(im.format, 'PNG')
            self.assertGreaterEqual(r['crop_size'][0], r['width'])
            self.assertGreaterEqual(r['crop_size'][1], r['height'])
            self.assertEqual(r['title'], 'screenshot' not in r['name'], r)
        self.assertEqual([r['source_frame'] for r in report if r['name'] == 'screenshot'],
                         ['swing.png', 'spire.png', 'mountain.png'])
        self.assertEqual(next(r for r in report if r['name'] == 'portrait')['source_frame'], 'swing-tall.png')
        self.assertTrue((self.tmp / 'release/images.json').exists())

    def test_refuses_upscale(self):
        frames(self.tmp / 'frames', scale=1)  # 240x135 frames: smaller than a 400x225 cover
        spec = {'portals': {'a': {'images': [
            {'name': 'cover', 'width': 400, 'height': 225, 'format': ['png'], 'max_bytes': None}]}}}
        (self.tmp / 'spec.json').write_text(json.dumps(spec))
        with self.assertRaises(SystemExit) as caught:
            make_covers.go_compose(self.tmp / 'frames', self.tmp / 'spec.json', self.tmp / 'release')
        self.assertIn('would upscale', str(caught.exception))

    def test_crop_keeps_aspect_inside_frame(self):
        meta = {'ninjaPx': [3000, 900], 'anchorPx': [2500, 400]}
        frame = Image.new('RGB', (3840, 2160))
        for aspect in (16 / 9, 1.6, 1.26, 4 / 3, 1, 9 / 16):
            l, t, r, b = make_covers.go_crop(frame, meta, aspect)
            self.assertTrue(0 <= l < r <= 3840 and 0 <= t < b <= 2160, aspect)
            self.assertAlmostEqual((r - l) / (b - t), aspect, delta=0.01)


if __name__ == '__main__':
    unittest.main()
