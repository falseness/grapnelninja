"""Independent checks for the light-support diagnostic's geometric accounting."""
import random
import unittest

from playgama_light_profile import support_rects, union_area


class LightSupportTests(unittest.TestCase):
    def test_union_matches_integer_pixel_sets(self):
        rng = random.Random(312)
        for _ in range(100):
            rects = []
            pixels = set()
            for _ in range(rng.randrange(20)):
                x0, x1 = sorted(rng.sample(range(21), 2))
                y0, y1 = sorted(rng.sample(range(21), 2))
                rects.append((x0, y0, x1, y1))
                pixels.update((x, y) for x in range(x0, x1) for y in range(y0, y1))
            self.assertEqual(union_area(rects), len(pixels))

    def test_source_clamp_scale_translation_and_destination_padding(self):
        light = dict(source=[100, 50], destination=[200, 100],
                     backing=[800, 400], transform=[2, 0, 0, 2, 10, 20],
                     rects=[[-3, -2, 20, 10], [101, 1, 105, 5]])
        self.assertEqual(support_rects(light), [(8, 18, 92, 62)])

    def test_rotation_and_canvas_clamp(self):
        light = dict(source=[100, 50], destination=[100, 50],
                     backing=[100, 50], transform=[0, 1, -1, 0, 10, 0],
                     rects=[[0, 0, 20, 10]])
        self.assertEqual(support_rects(light), [(0, 0, 12, 22)])


if __name__ == '__main__':
    unittest.main()
