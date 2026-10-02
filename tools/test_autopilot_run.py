"""Store-asset autopilot helpers (TASK-084); no browser needed."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from autopilot_run import build_filmstrip, parse_seeds

ROOT = Path(__file__).resolve().parent.parent


class AutopilotRunTest(unittest.TestCase):
    def test_parse_seeds(self):
        self.assertEqual(parse_seeds('1-200'), list(range(1, 201)))
        self.assertEqual(parse_seeds('3,7-9'), [3, 7, 8, 9])

    def test_filmstrip_grid(self):
        from PIL import Image
        frames = [Image.new('RGB', (40, 20), 'red') for _ in range(7)]
        with tempfile.TemporaryDirectory() as tmp:
            size = build_filmstrip(frames, Path(tmp) / 'strip.png', columns=3)
            self.assertEqual(size, (120, 60))
            self.assertEqual(Image.open(Path(tmp) / 'strip.png').size, (120, 60))

    def test_index_does_not_load_autopilot(self):
        self.assertNotIn('autopilot', (ROOT / 'index.html').read_text().lower())


if __name__ == '__main__':
    unittest.main()
