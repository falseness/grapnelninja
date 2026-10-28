"""Bounce contact atlas (TASK-756) draws the same pulse frames as one canvas per part.

Frozen-clock Grapple Over frames, centred on several bounce panels of the
level, each with a forced contact pulse at its centroid at a few pulse ages,
are rendered at 1706x932 DPR 1.5 by the worktree and by a git archive copy of
the revision before the change (BOUNCE_ATLAS_BASELINE, default b151296). Each
frame's rgba sha256 must match; a differing frame may differ by at most
1/255 per channel. The worktree must build one atlas canvas per board, whose
cells are byte-identical to the old per-part canvases with >= 2 px gaps, and
share one contact dot. Writes pixels.json to BOUNCE_ATLAS_EVIDENCE_DIR
(default artifacts/TASK-756).

    cd tools && python3 -m unittest -v test_bounce_contact_atlas
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
BASELINE = os.environ.get('BOUNCE_ATLAS_BASELINE', 'b151296')
EVIDENCE = Path(os.environ.get('BOUNCE_ATLAS_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-756'))
VIEWPORT = {'width': 1706, 'height': 932}
DPR = 1.5
PANELS = 4
AGES = (0.1, 0.35, 0.6)   # share of pulseMs since the contact


FREEZE = '''() => {
    window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
    // One fixed clock (wall and simulated) in every page load and tree
    performance.now = () => 600000
    floors[0].elapsedSteps = 600000 * cyclesPerTick / physicsStepMs
    if (typeof TUTORIAL_HINT != 'undefined') TUTORIAL_HINT.visible = false
    // Ambient motes draw from Math.random: not the same frame in both trees
    visualEffects.particles.drawAmbientMotes = () => {}
    setGrapnelMode('single')
    // HUD rows show how far the boot run got before the freeze
    const s = floors[0].climbStats
    s.elapsedActiveMs = 0; s.currentHeight = 0; s.maxHeight = 0
}'''

# Bounce panels with points, spread over the level's height, most trace parts first per band
PICK = '''count => {
    const w = floors[0], unit = 1 / scale[version]
    const panels = w.elements.filter(e => e.surfaceRole === 'bounce' && e.points && e.points.length > 2)
        .sort((a, b) => b.y - a.y)
    const out = []
    for (let i = 0; i < count; i++)
    {
        const band = panels.slice(Math.floor(i * panels.length / count), Math.floor((i + 1) * panels.length / count))
        const sized = band.map(e => [e, bounceMaterialSprite(e, w, 1, 1, unit).bright.parts.length])
        sized.sort((a, b) => b[1] - a[1])
        out.push(w.elements.indexOf(sized[0][0]))
    }
    return out
}'''

RENDER = '''([index, age]) => {
    const w = floors[0], e = w.elements[index]
    const c = e.points.reduce((a, p) => ({x: a.x + p.x / e.points.length, y: a.y + p.y / e.points.length}), {x: 0, y: 0})
    ninja.x = e.x + c.x; ninja.y = e.y + c.y; ninja.speedX = 0; ninja.speedY = 0
    // Marker angle, trail and respawn blink keep how the boot run moved
    ninja.visualRotation = 0; ninja.invulnerableMs = 0; ninja.track.pos = [{x: ninja.x, y: ninja.y}]
    screen.trackGrappleOver(true)
    const steps = Math.round(age * GRAPPLE_OVER_ROLE_DETAIL.bounce.pulseMs * cyclesPerTick / physicsStepMs)
    ROLE_DETAIL.contacts.set(e, {step: w.elapsedSteps - steps, strength: 1, point: c})
    let created = 0
    const create = document.createElement
    document.createElement = function(tag) { if (String(tag).toLowerCase() === 'canvas') created++; return create.apply(this, arguments) }
    try { draw() } finally { document.createElement = create }
    ROLE_DETAIL.contacts.delete(e)
    const pulses = ROLE_DETAIL.frame ? ROLE_DETAIL.frame.pulses.filter(p => p.id === e.id).length : 0
    const m = ctx.getTransform(), unit = 1 / scale[version]
    const bright = bounceMaterialSprite(e, w, glowSpriteScale(m.a), glowSpriteScale(m.d), unit).bright
    return {png: canvas.toDataURL('image/png'), id: e.id, pulses, created, parts: bright.parts.length,
            atlas: bright.image ? [bright.image.width, bright.image.height] : null,
            sharedDot: typeof BOUNCE_MATERIAL.dot != 'undefined' ? bright.dot === BOUNCE_MATERIAL.dot : null,
            view: [m.a, m.d, m.e, m.f, screen.x, screen.y, ninja.x, ninja.y],
            counts: ROLE_DETAIL.frame ? JSON.stringify(ROLE_DETAIL.frame.counts) + ROLE_DETAIL.frame.dots : null}
}'''


# Each atlas cell against the same part rasterized the old way, on its own canvas
CELLS = '''indices => {
    const w = floors[0], m = ctx.getTransform(), unit = 1 / scale[version]
    const sx = glowSpriteScale(m.a), sy = glowSpriteScale(m.d), config = GRAPPLE_OVER_ROLE_DETAIL.bounce
    let parts = 0, differing = 0, overlaps = 0, gapOk = true
    for (const index of indices)
    {
        const {bright, board} = bounceMaterialSprite(w.elements[index], w, sx, sy, unit)
        const atlas = bright.image.getContext('2d')
        for (const part of bright.parts)
        {
            parts++
            const one = document.createElement('canvas'); one.width = part.sw; one.height = part.sh
            const c = one.getContext('2d')
            c.setTransform(sx, 0, 0, sy, -part.left * sx, -part.top * sy)
            c.strokeStyle = config.pulseTrace; c.lineWidth = (part.via ? 0.5 : 0.8) * board.scale
            c.lineCap = 'round'; c.beginPath()
            if (part.via) c.arc(part.a.x, part.a.y, 1.2 * board.scale, 0, 2 * Math.PI)
            else { c.moveTo(part.a.x, part.a.y); c.lineTo(part.b.x, part.b.y) }
            c.stroke()
            const want = c.getImageData(0, 0, part.sw, part.sh).data
            const got = atlas.getImageData(part.sx, part.sy, part.sw, part.sh).data
            if (want.some((v, i) => v !== got[i])) differing++
            // >= 2 px transparent gap to every other cell and inside the atlas
            if (part.sx < 2 || part.sy < 2 || part.sx + part.sw + 2 > bright.image.width ||
                part.sy + part.sh + 2 > bright.image.height) gapOk = false
            for (const q of bright.parts)
                if (q !== part && part.sx < q.sx + q.sw + 2 && q.sx < part.sx + part.sw + 2 &&
                    part.sy < q.sy + q.sh + 2 && q.sy < part.sy + part.sh + 2) overlaps++
            if (!Number.isInteger(part.sx) || !Number.isInteger(part.sy)) gapOk = false
        }
    }
    return {parts, differing, overlaps, gapOk}
}'''


def decode(data_url):
    raw = base64.b64decode(data_url.split(',', 1)[1])
    return np.asarray(Image.open(io.BytesIO(raw)).convert('RGBA'), dtype=np.int16)


class BounceContactAtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, stack.callback)
        root, cls.sha = export_rev(BASELINE, stack.callback)
        cls.baseline_url = serve(root, stack.callback)

    def render(self, url, panels=None):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=DPR)
        try:
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)[:300]))
            page.goto(url + 'index.html', wait_until='load')
            wait_for_boot_run(page)
            page.evaluate(FREEZE)
            if panels is None:
                panels = page.evaluate(PICK, PANELS)
            # The first frame on a panel warms its sprites; every compared
            # frame is drawn again after that
            for index in panels:
                page.evaluate(RENDER, [index, AGES[0]])
            shots = [page.evaluate(RENDER, [index, age]) for index in panels for age in AGES]
            again = page.evaluate(RENDER, [panels[0], AGES[1]])
            self.cells = page.evaluate(CELLS, panels) if url == self.url else getattr(self, 'cells', None)
            self.assertEqual(errors, [])
            return panels, shots, again
        finally:
            context.close()

    def test_01_pulse_frames_match_baseline(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        panels, new, again = self.render(self.url)
        _, old, _ = self.render(self.baseline_url, panels)
        self.assertEqual(again['png'], new[1]['png'], 'frozen frame not repeatable')
        frames = []
        for i, (a, b) in enumerate(zip(old, new)):
            pa, pb = decode(a['png']), decode(b['png'])
            diff = np.abs(pa - pb)
            row = {'panel': b['id'], 'age': AGES[i % len(AGES)], 'pulses': [a['pulses'], b['pulses']],
                   'parts': b['parts'], 'atlas': b['atlas'], 'sharedDot': b['sharedDot'],
                   'oldSha': hashlib.sha256(pa.astype(np.uint8).tobytes()).hexdigest(),
                   'newSha': hashlib.sha256(pb.astype(np.uint8).tobytes()).hexdigest(),
                   'maxAbs': int(diff.max()), 'changedPx': int((diff.max(axis=2) > 0).sum())}
            row['same'] = row['oldSha'] == row['newSha']
            row['pass'] = row['maxAbs'] <= 1 and b['pulses'] == 1 and a['pulses'] == 1 and \
                b['atlas'] is not None and b['sharedDot'] is True
            frames.append(row)
        summary = {'baseline': self.sha, 'viewport': [VIEWPORT['width'], VIEWPORT['height']], 'dpr': DPR,
                   'panels': len(set(r['panel'] for r in frames)), 'cells': self.cells, 'frames': frames,
                   'allSame': all(r['same'] for r in frames), 'allPass': all(r['pass'] for r in frames)}
        if not summary['allSame']:
            summary['reason'] = ('every atlas cell is byte-identical to the old per-part canvas (cells.differing 0); '
                                 'the <= 1/255 changes come from sampling a sub-rect of the larger atlas canvas '
                                 'instead of a whole small canvas when it is scaled onto the frame')
        (EVIDENCE / 'pixels.json').write_text(json.dumps(summary, separators=(',', ':')) + '\n')
        self.assertGreaterEqual(summary['panels'], 3)
        self.assertEqual((self.cells['differing'], self.cells['overlaps'], self.cells['gapOk']), (0, 0, True), self.cells)
        for row in frames:
            self.assertTrue(row['pass'], row)


if __name__ == '__main__':
    unittest.main()
