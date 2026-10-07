"""Smoke test for the visual gallery (tools/visual_gallery.py)."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

import visual_gallery

TOOLS = Path(__file__).resolve().parent


class VisualGalleryTest(unittest.TestCase):
    def test_worktree_gallery(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'gallery'
            proc = subprocess.run([sys.executable, str(TOOLS / 'visual_gallery.py'),
                                   '--rev', 'worktree', '--out', str(out)],
                                  capture_output=True, text=True)
            print(proc.stdout[-2000:], proc.stderr[-2000:])
            self.assertEqual(proc.returncode, 0)
            manifest = json.loads((out / 'manifest.json').read_text())
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TOOLS, text=True).strip()
            self.assertEqual(manifest['rev'], head)
            self.assertEqual(manifest['page_errors'], [])

            names = []
            for vp in visual_gallery.VIEWPORTS:
                names.append(f'{vp["name"]}-menu')
                names += [f'{vp["name"]}-{mode}-tick{tick:04d}'
                          for mode in visual_gallery.MODES for tick in visual_gallery.TICKS]
            self.assertEqual(sorted(manifest['captures']), sorted(names))
            for name, c in manifest['captures'].items():
                self.assertTrue((out / f'{name}.png').exists(), name)
                vp = next(v for v in visual_gallery.VIEWPORTS if v['name'] == c['viewport'])
                self.assertEqual((c['width'], c['height']), (vp['width'] * vp['dpr'], vp['height'] * vp['dpr']))
                if c['mode'] == 'menu':
                    continue
                state = c['state']
                self.assertEqual(state['version'], c['mode'])
                for key in visual_gallery.STATE_KEYS[:-1]:
                    self.assertIsInstance(state[key], (int, float), f'{name} {key}')
                    self.assertTrue(math.isfinite(state[key]), f'{name} {key}')

            for mode in visual_gallery.MODES:
                gif = Image.open(out / f'gif-{mode}.gif')
                self.assertGreaterEqual(gif.n_frames, 30)
                self.assertEqual(gif.size, visual_gallery.GIF_SIZE)
            self.assertTrue((out / 'sheet.png').exists())

            same = subprocess.run([sys.executable, str(TOOLS / 'visual_gallery.py'), '--compare-state',
                                   str(out / 'manifest.json'), str(out / 'manifest.json')],
                                  capture_output=True, text=True)
            self.assertEqual(same.returncode, 0)
            self.assertIn('differences: 0', same.stdout)

            tampered = json.loads((out / 'manifest.json').read_text())
            tampered['captures']['desktop-bad-tick0300']['state']['ninja.x'] += 1
            (Path(tmp) / 'tampered.json').write_text(json.dumps(tampered))
            diff = subprocess.run([sys.executable, str(TOOLS / 'visual_gallery.py'), '--compare-state',
                                   str(out / 'manifest.json'), str(Path(tmp) / 'tampered.json')],
                                  capture_output=True, text=True)
            self.assertEqual(diff.returncode, 1)
            self.assertIn('differences: 1', diff.stdout)


if __name__ == '__main__':
    unittest.main()
