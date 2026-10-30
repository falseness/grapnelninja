"""HUD glyph sprites (TASK-755) look like the whole-string glow sprites they replace.

The climb HUD is rendered with a frozen clock and fixed stats (time 0.0 s /
12.3 s / 754.9 s, height and best 0 / 2935 / 54508) in both grapnel modes at
DPR 1 and 1.5, by the worktree and by a git archive copy of the revision
before the change (HUD_GLYPHS_BASELINE, default 0445f21). Each HUD crop must
differ by a mean absolute channel difference <= 2/255 with >= 99% of pixels
within 8/255. Writes hud-diff.json and hud-side-by-side.png to
HUD_GLYPHS_EVIDENCE_DIR (default artifacts/TASK-755).

Since TASK-796 the HUD has no Time row (the baseline still draws it), so
each crop compares bands: the Height/Best/Section rows, plus the
double-range row from its own place in each tree, drawn over a flat fill
(that row moved up, so the scene behind it differs).

    cd tools && python3 -m unittest -v test_hud_glyphs
"""
import base64
import io
import json
import os
import unittest
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import numpy as np
from PIL import Image, ImageDraw

from browser_test_support import QuietHandler, start_browser_test, wait_for_boot_run
from perf_mobile import export_rev

ROOT = Path(__file__).resolve().parent.parent
BASELINE = os.environ.get('HUD_GLYPHS_BASELINE', '0445f21')
EVIDENCE = Path(os.environ.get('HUD_GLYPHS_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-755'))
VIEWPORT = {'width': 1706, 'height': 932}
CASES = [(0, 0), (12300, 2935), (754900, 54508)]   # elapsedActiveMs, height
MODES = ('single', 'double')
DPRS = (1, 1.5)
MEAN_LIMIT = 2
WITHIN = 8
WITHIN_SHARE = 0.99

FREEZE = '''mode => {
    window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
    const now = performance.now()
    performance.now = () => now
    if (typeof TUTORIAL_HINT != 'undefined') TUTORIAL_HINT.visible = false
    // Ambient motes draw from Math.random: not the same frame in both trees
    visualEffects.particles.drawAmbientMotes = () => {}
    setGrapnelMode(mode)
    ninja.x = 500; ninja.y = -200; ninja.speedX = 0; ninja.speedY = 0
}'''

# Draws a frame and returns the HUD rows' canvas px box as a PNG
RENDER = '''([ms, value]) => {
    const s = floors[0].climbStats
    s.elapsedActiveMs = ms; s.currentHeight = value; s.maxHeight = value
    let m = null, flat = false
    const hud = CLIMB_UI.drawHud
    CLIMB_UI.drawHud = function() {
        m = ctx.getTransform()
        // flat: a plain fill under the HUD instead of the scene
        if (flat) { ctx.save(); ctx.resetTransform(); ctx.fillStyle = '#20143a'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.restore() }
        return hud.apply(this, arguments)
    }
    const h = height / scale[version]
    const size = Math.max(h * 0.025, 12 * h / getCanvasCssRect().height)
    const rows = 5   // the baseline's most rows (double mode, with Time)
    const grab = () => {
        draw()
        const w = Math.ceil(m.a * size * 16 + m.e), hh = Math.ceil(m.d * size * (1.5 + (rows - 1) * 1.6 + 1.4) + m.f)
        const crop = document.createElement('canvas')
        crop.width = w; crop.height = hh
        crop.getContext('2d').drawImage(canvas, 0, 0, w, hh, 0, 0, w, hh)
        return {png: crop.toDataURL('image/png'), box: [w, hh]}
    }
    let plain, flatShot
    try {
        flat = true; flatShot = grab()
        flat = false; plain = grab()
    } finally { CLIMB_UI.drawHud = hud }
    return {png: plain.png, flatPng: flatShot.png, box: plain.box, unit: m.d * size, top: m.f,
            glyph: typeof GLYPH_SPRITES != 'undefined' ? GLYPH_SPRITES.cache.size : null,
            hudTextSprites: [...GLOW_SPRITES.cache.keys()].filter(k => /^text\\|(Time|Height|Best)/.test(k)).length}
}'''


def serve(root, add_cleanup):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
    add_cleanup(server.server_close)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    add_cleanup(thread.join)
    add_cleanup(server.shutdown)
    return f'http://127.0.0.1:{server.server_port}/'


def bands(shot, mode, last, shift=0):
    # Rows 0-2 (Height, Best, Section) over the scene, then the double-range row at
    # index last over the flat fill (shift: whole device px added to its band start)
    y = lambda i: shot['top'] + shot['unit'] * (1.5 + i * 1.6)
    parts = [decode(shot['png'])[:round(y(2) + shot['unit'] * 0.8)]]
    if mode == 'double':
        start = round(y(last) - shot['unit'] * 0.8) + shift
        parts.append(decode(shot['flatPng'])[start:start + round(shot['unit'] * 1.6)])
    return np.concatenate(parts)


def aligned(a, b, mode):
    # The baseline's double-range row follows its Time row (index 4), now it is index 3.
    # Its 1.6-row move is fractional in device px, so the band start is rounded; take
    # the whole-px offset (-1..1) that matches best.
    pa = bands(a, mode, 4)
    pb = min((bands(b, mode, 3, k) for k in (-1, 0, 1)), key=lambda p: np.abs(pa - p).mean())
    return pa, pb


def decode(data_url):
    raw = base64.b64decode(data_url.split(',', 1)[1])
    return np.asarray(Image.open(io.BytesIO(raw)).convert('RGB'), dtype=np.int16)


class HudGlyphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, stack.callback)
        root, cls.sha = export_rev(BASELINE, stack.callback)
        cls.baseline_url = serve(root, stack.callback)

    def render(self, url, mode, dpr):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=dpr)
        try:
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)[:300]))
            page.goto(url + 'index.html', wait_until='load')
            wait_for_boot_run(page)
            page.evaluate(FREEZE, mode)
            shots = [page.evaluate(RENDER, case) for case in CASES]
            # Same frozen frame twice: the frame is repeatable
            again = page.evaluate(RENDER, CASES[1])
            self.assertEqual(errors, [])
            return shots, again
        finally:
            context.close()

    def test_01_hud_crops_match_baseline(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        results, pairs = [], []
        for dpr in DPRS:
            for mode in MODES:
                old, _ = self.render(self.baseline_url, mode, dpr)
                new, again = self.render(self.url, mode, dpr)
                self.assertEqual(again['png'], new[1]['png'], 'frozen frame not repeatable')
                for (ms, value), a, b in zip(CASES, old, new):
                    self.assertEqual(a['box'], b['box'])
                    pa, pb = aligned(a, b, mode)
                    diff = np.abs(pa - pb)
                    within = float((diff.max(axis=2) <= WITHIN).mean())
                    row = {'dpr': dpr, 'mode': mode, 'timeS': ms / 1000, 'height': value, 'box': b['box'],
                           'meanAbs': round(float(diff.mean()), 4), 'within8': round(within, 5),
                           'maxAbs': int(diff.max()), 'changedPx': int((diff.max(axis=2) > 0).sum()),
                           'newGlyphSprites': b['glyph'], 'newHudTextSprites': b['hudTextSprites'],
                           'oldHudTextSprites': a['hudTextSprites']}
                    row['pass'] = row['meanAbs'] <= MEAN_LIMIT and within >= WITHIN_SHARE and \
                        b['glyph'] > 0 and b['hudTextSprites'] == 0
                    results.append(row)
                    pairs.append((row, pa, pb))
        (EVIDENCE / 'hud-diff.json').write_text(json.dumps({
            'baseline': self.sha, 'thresholds': {'meanAbsMax': MEAN_LIMIT, 'withinChannel': WITHIN,
                                                 'withinShareMin': WITHIN_SHARE},
            'viewport': [VIEWPORT['width'], VIEWPORT['height']], 'crops': results,
            'allPass': all(r['pass'] for r in results)}, separators=(',', ':')) + '\n')
        self.side_by_side(pairs)
        for row in results:
            self.assertTrue(row['pass'], row)

    def side_by_side(self, pairs):
        # old | new | difference x8, one row per case at DPR 1.5 single plus
        # the largest-number case of the others
        chosen = [p for p in pairs if p[0]['dpr'] == 1.5 and p[0]['mode'] == 'single']
        chosen += [p for p in pairs if p[0]['height'] == 54508 and p not in chosen]
        gap, label = 8, 18
        width = max(p[1].shape[1] for p in chosen) * 3 + gap * 4
        height = sum(p[1].shape[0] + label + gap for p in chosen) + gap
        sheet = Image.new('RGB', (width, height), (40, 40, 40))
        draw = ImageDraw.Draw(sheet)
        y = gap
        for row, pa, pb in chosen:
            draw.text((gap, y), 'old %s | new | |diff| x8   DPR %s %s time %.1f s height %d   mean %.3f within8 %.4f' % (
                self.sha[:7], row['dpr'], row['mode'], row['timeS'], row['height'], row['meanAbs'], row['within8']),
                fill=(255, 255, 255))
            y += label
            w = pa.shape[1]
            for i, image in enumerate((pa, pb, np.minimum(np.abs(pa - pb) * 8, 255))):
                sheet.paste(Image.fromarray(image.astype(np.uint8)), (gap + i * (w + gap), y))
            y += pa.shape[0] + gap
        sheet.save(EVIDENCE / 'hud-side-by-side.png')


if __name__ == '__main__':
    unittest.main()
