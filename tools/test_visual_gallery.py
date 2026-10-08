"""Smoke test for the visual gallery (tools/visual_gallery.py)."""
from contextlib import nullcontext
import os
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
        evidence = os.environ.get('VISUAL_GALLERY_EVIDENCE_DIR')
        with (nullcontext(evidence) if evidence else tempfile.TemporaryDirectory()) as tmp:
            out = Path(tmp) / 'gallery'
            proc = subprocess.run([sys.executable, str(TOOLS / 'visual_gallery.py'),
                                   '--rev', 'worktree', '--out', str(out)],
                                  capture_output=True, text=True)
            print(proc.stdout, proc.stderr)
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
                # Touch backing stores are capped at DPR 2 by configureStage.
                dpr = min(vp['dpr'], 2) if vp['touch'] else vp['dpr']
                self.assertEqual((c['width'], c['height']),
                                 (vp['width'] * dpr, vp['height'] * dpr))
                with Image.open(out / c['file']) as png:
                    self.assertEqual(png.size, (c['width'], c['height']))
                if c['mode'] == 'menu':
                    continue
                state = c['state']
                self.assertEqual(state['version'], c['mode'])
                for key in visual_gallery.STATE_KEYS[:-1]:
                    self.assertIsInstance(state[key], (int, float), f'{name} {key}')
                    self.assertTrue(math.isfinite(state[key]), f'{name} {key}')

            pauses = [f'{vp["name"]}-{mode}-pause' for vp in visual_gallery.VIEWPORTS
                      for mode in visual_gallery.MODES]
            self.assertEqual(sorted(manifest['screens']), sorted(pauses))
            for name in pauses:
                self.assertTrue((out / f'{name}.png').exists(), name)

            for mode in visual_gallery.MODES:
                ember = Image.open(out / f'ember-gif-{mode}.gif')
                self.assertEqual(ember.n_frames, 120)
                info = manifest['ember_gifs'][mode]
                self.assertEqual(info['file'], f'ember-gif-{mode}.gif')
                self.assertGreater(info['peak_shared_alpha'], 0.1)
                self.assertTrue((out / info['phone_file']).exists())
                gif = Image.open(out / f'gif-{mode}.gif')
                self.assertGreaterEqual(gif.n_frames, 30)
                self.assertEqual(gif.size, visual_gallery.GIF_SIZE)
                info = manifest['gifs'][mode]
                self.assertEqual(info['file'], f'gif-{mode}.gif')
                if mode == 'bad':
                    self.assertTrue(all(a['screen.x'] != b['screen.x']
                                        for a, b in zip(info['states'][:10], info['states'][1:10])),
                                    'bad first ten GIF frames must move the camera')
                self.assertEqual(info['viewport'], visual_gallery.GIF_CAPTURE[mode][0])
                self.assertEqual(info['ticks'], visual_gallery.gif_ticks(mode))
                self.assertEqual(len(info['states']), gif.n_frames)
                camera_x = [state['screen.x'] for state in info['states']]
                self.assertGreater(max(camera_x) - min(camera_x), 100,
                                   f'{mode} GIF must demonstrate camera parallax')
            with Image.open(out / 'gif-menu.gif') as gif:
                self.assertGreaterEqual(gif.n_frames, 30)
                gif.seek(0)
                first = gif.convert('RGB').tobytes()
                gif.seek(gif.n_frames - 1)
                self.assertNotEqual(first, gif.convert('RGB').tobytes())
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
