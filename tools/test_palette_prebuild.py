"""Palette strips (TASK-760) draw the same frames as the full-frame images.

Frozen-clock Grapple Over frames with the camera at three heights (a band
core, mid-blend between two bands, the next band core) are rendered at
1706x932 DPR 1.5 and 1280x720 DPR 1 (neither width a multiple of 256) by the
worktree and by a git archive copy of the revision before the change
(PALETTE_PREBUILD_BASELINE, default 07bcf62, full-frame palette images). Each
height is drawn twice in a row; every frame's rgba sha256 must match the
baseline. The worktree must hold one 256 px wide strip of the frame's device
height per palette, all built before the frames (no build in them). Writes
pixels.json to PALETTE_PREBUILD_EVIDENCE_DIR (default artifacts/TASK-760).

    cd tools && python3 -m unittest -v test_palette_prebuild
"""
import base64
import hashlib
import io
import json
import os
import unittest
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from PIL import Image

from browser_test_support import start_browser_test, wait_for_boot_run
from perf_mobile import export_rev
from test_hud_glyphs import serve

ROOT = Path(__file__).resolve().parent.parent
BASELINE = os.environ.get('PALETTE_PREBUILD_BASELINE', '07bcf62')
EVIDENCE = Path(os.environ.get('PALETTE_PREBUILD_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-760'))
VIEWPORTS = (({'width': 1706, 'height': 932}, 1.5), ({'width': 1280, 'height': 720}, 1))
# camera rise as a share of bandHeight: band 1 core, boundary 1/2 (t 0.5), band 2 core
HEIGHTS = (('core', 1.5), ('blend', 2.0), ('nextCore', 2.5))

FREEZE = '''() => {
    window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
    performance.now = () => 600000
    floors[0].elapsedSteps = 600000 * cyclesPerTick / physicsStepMs
    if (typeof TUTORIAL_HINT != 'undefined') TUTORIAL_HINT.visible = false
    visualEffects.particles.drawAmbientMotes = () => {}
    // Particles left by the boot run (how far it got differs between loads)
    visualEffects.particles.particles.length = 0
    setGrapnelMode('single')
    const s = floors[0].climbStats
    s.elapsedActiveMs = 0; s.currentHeight = 0; s.maxHeight = 0
}'''

RENDER = '''bands => {
    const rise = bands * GRAPPLE_OVER_THEME.bandHeight
    ninja.x = 500; ninja.y = -rise; ninja.speedX = 0; ninja.speedY = 0
    ninja.visualRotation = 0; ninja.invulnerableMs = 0; ninja.track.pos = [{x: ninja.x, y: ninja.y}]
    screen.trackGrappleOver(true)
    // camera centre exactly at -rise (drawBackgroundLayer's cameraY)
    screen.y = height / scale[version] / 2 + rise
    const strips = () => drawGrappleOverPalette.images ?
        [...drawGrappleOverPalette.images].map(([i, o]) => o.image ? [i, o.image.canvas.width, o.image.canvas.height] : [i]) : []
    const before = strips()
    const shots = []
    for (let i = 0; i < 2; i++)
    {
        draw()
        const p = visualEffects.background.palette
        shots.push({png: canvas.toDataURL('image/png'), palette: [p.from, p.to, Math.round(p.t * 1000) / 1000]})
    }
    // no strip is (re)built by the draws: same sizes and the same key before and after
    const key = drawGrappleOverPalette.strips ? drawGrappleOverPalette.strips.key : null
    return {shots, before, after: strips(), canvas: [canvas.width, canvas.height], same: JSON.stringify(before) === JSON.stringify(strips()) &&
            key === (drawGrappleOverPalette.strips ? drawGrappleOverPalette.strips.key : null),
            palettes: GRAPPLE_OVER_THEME.palettes.length}
}'''


def decode(data_url):
    raw = base64.b64decode(data_url.split(',', 1)[1])
    return np.asarray(Image.open(io.BytesIO(raw)).convert('RGBA'), dtype=np.int16)


def sha(pixels):
    return hashlib.sha256(pixels.astype(np.uint8).tobytes()).hexdigest()


class PalettePrebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, stack.callback)
        root, cls.sha = export_rev(BASELINE, stack.callback)
        cls.baseline_url = serve(root, stack.callback)

    def render(self, url, viewport, dpr):
        context = self.browser.new_context(viewport=viewport, device_scale_factor=dpr)
        try:
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)[:300]))
            page.goto(url + 'index.html', wait_until='load')
            wait_for_boot_run(page)
            page.evaluate(FREEZE)
            out = [page.evaluate(RENDER, bands) for _, bands in HEIGHTS]
            self.assertEqual(errors, [])
            return out
        finally:
            context.close()

    def test_01_frames_match_baseline(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        frames, strips = [], []
        for viewport, dpr in VIEWPORTS:
            new = self.render(self.url, viewport, dpr)
            old = self.render(self.baseline_url, viewport, dpr)
            for (name, bands), a, b in zip(HEIGHTS, old, new):
                for draw, (sa, sb) in enumerate(zip(a['shots'], b['shots'])):
                    pa, pb = decode(sa['png']), decode(sb['png'])
                    diff = np.abs(pa - pb)
                    frames.append({'viewport': [viewport['width'], viewport['height'], dpr], 'height': name,
                                   'rise': bands, 'draw': draw + 1, 'palette': sb['palette'],
                                   'oldSha': sha(pa), 'newSha': sha(pb), 'maxAbs': int(diff.max()),
                                   'same': sha(pa) == sha(pb) and sa['palette'] == sb['palette']})
                strips.append({'viewport': [viewport['width'], viewport['height'], dpr], 'height': name,
                               'canvas': b['canvas'], 'strips': b['after'], 'noBuildInDraws': b['same'],
                               'palettes': b['palettes']})
        summary = {'baseline': self.sha, 'frames': frames, 'strips': strips,
                   'allSame': all(f['same'] for f in frames)}
        (EVIDENCE / 'pixels.json').write_text(json.dumps(summary, separators=(',', ':')) + '\n')
        self.assertEqual([f['palette'] for f in frames if f['draw'] == 1], [[1, 1, 0], [1, 2, 0.5], [2, 2, 0]] * 2)
        for f in frames:
            self.assertTrue(f['same'], f)
        for row in strips:
            # one strip per palette, 256 px x the frame's device height, none built by the frames
            self.assertEqual([s[0] for s in row['strips']], list(range(row['palettes'])), row)
            self.assertTrue(all(s[1:] == [256, row['canvas'][1]] for s in row['strips']), row)
            self.assertTrue(row['noBuildInDraws'], row)


if __name__ == '__main__':
    unittest.main()
