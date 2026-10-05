"""Tests for the pixel-identity harness (tools/render_snapshot.py)."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import render_snapshot

TOOLS = Path(__file__).resolve().parent

# Draws one opaque red device pixel after every draw(): a deliberate one-pixel
# canvas change that the menu capture does not see but every game tick does.
ONE_PIXEL_CHANGE = '''window.addEventListener('load', () => {
    const draw0 = window.draw
    window.draw = function() {
        draw0()
        ctx.save()
        ctx.setTransform(1, 0, 0, 1, 0, 0)
        ctx.globalAlpha = 1
        ctx.globalCompositeOperation = 'source-over'
        ctx.fillStyle = '#ff0000'
        ctx.fillRect(7, 7, 1, 1)
        ctx.restore()
    }
})'''


class RenderSnapshotTest(unittest.TestCase):
    def test_input_script_is_seeded(self):
        self.assertEqual(render_snapshot.input_script(1), render_snapshot.input_script(1))
        self.assertNotEqual(render_snapshot.input_script(1), render_snapshot.input_script(2))
        ticks = [e['tick'] for e in render_snapshot.input_script(1)]
        self.assertTrue(ticks)
        self.assertLessEqual(max(ticks), render_snapshot.TICKS[-1])
        self.assertEqual(len(render_snapshot.capture_names()), 18)

    def test_two_captures_of_head_are_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = render_snapshot.capture('HEAD', Path(tmp) / 'one')
            second = render_snapshot.capture('HEAD', Path(tmp) / 'two')
        self.assertEqual(first['page_errors'], [])
        self.assertEqual(len(first['captures']), 18)
        hashes = {n: c['sha256'] for n, c in first['captures'].items()}
        self.assertEqual(hashes, {n: c['sha256'] for n, c in second['captures'].items()})
        # Ticks of one game are different frames, not one frozen image.
        for vp in ('mobile', 'desktop'):
            for mode in render_snapshot.MODES:
                ticks = {hashes[f'{vp}-{mode}-tick{t:04d}'] for t in render_snapshot.TICKS}
                self.assertEqual(len(ticks), len(render_snapshot.TICKS), f'{vp}-{mode}')

    def test_injected_one_pixel_change_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            init = Path(tmp) / 'one_pixel.js'
            init.write_text(ONE_PIXEL_CHANGE)
            out = Path(tmp) / 'cmp'
            proc = subprocess.run([sys.executable, str(TOOLS / 'render_snapshot.py'), '--compare',
                                   'HEAD', 'HEAD', '--init-script-b', str(init), '--out', str(out)],
                                  capture_output=True, text=True)
            print(proc.stdout[-2000:], proc.stderr[-2000:])
            self.assertEqual(proc.returncode, 1)
            report = json.loads((out / 'compare.json').read_text())
            captures = report['captures']
            for vp in ('mobile', 'desktop'):
                self.assertEqual(captures[f'{vp}-menu']['differing_pixels'], 0)
                for mode in render_snapshot.MODES:
                    for t in render_snapshot.TICKS:
                        entry = captures[f'{vp}-{mode}-tick{t:04d}']
                        self.assertGreaterEqual(entry['differing_pixels'], 1)
                        self.assertTrue(Path(entry['diff_png']).exists())
            self.assertEqual(len(report['differing_captures']), 16)


if __name__ == '__main__':
    unittest.main()
