"""Frozen-clock pixel regression for TASK-214's classic triangle palette.

Render real Triangle.draw/track code on a dark canvas at desktop and phone
resolutions. Sample fixed geometric edge/fill locations (not pixels selected
by their colour). Also compare complete seeded bad-mode frames with the old
classic palette applied to the current renderer. Later background, lighting
and trail changes must be identical on both sides of this palette-only check.
The normal gallery separately checks the palette in the composited game.
"""
import colorsys
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import re
import subprocess
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot as snap

PARENT = os.environ.get('TRIANGLE_PARENT', '40b2fb1')
EVIDENCE = Path(os.environ.get('TRIANGLE_EVIDENCE_DIR',
                             str(Path(__file__).resolve().parents[1] / 'artifacts/TASK-214')))

# Normal rendering methods, with a known triangle centred at (160, 120).
# Coordinate transform is explicit so pixel probes don't depend on camera motion.
ISOLATE = '''() => {
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.fillStyle = '#050910'; ctx.fillRect(0, 0, canvas.width, canvas.height)
    const density = canvas.width / 1920
    ctx.scale(density, density)
    scale[version] = 1
    screen.x = screen.y = 0
    const t = new Triangle({x: 160, y: 120, radius: 70,
        yMin: 0, yMax: 300, fill: '#21070f', stroke: '#ff2d95'})
    for (let i = 0; i < 12; i++) { t.y -= 2; t.track.addPos(t.getPoints(), true) }
    t.y = 120
    if (t.syncTrackStyle) t.syncTrackStyle()
    t.track.draw(); t.draw()
    const emitted = []
    if (typeof visualEffects !== 'undefined' && visualEffects.particles && STYLE.particles.embers) {
        const particles = visualEffects.particles
        // TASK-204 emits calm shared-colour embers directly through pushParticle.
        // Prime the beat before probing: a new obstacle's first call is silent.
        particles.emitElementParticles(t)
        t.emberBeat--
        const first = particles.particles.length
        particles.emitElementParticles(t)
        emitted.push(...particles.particles.slice(first).map(p => p.color))
    }
    return {density, top: 120 - t.height / 3,
            emitted, emberColor: typeof STYLE.particles.embers !== 'undefined'
                ? STYLE.particles.embers.hazardColor : null,
            trail: t.track.stroke,
            light: t.getGlowStroke ? t.getGlowStroke() : null,
            particle: typeof visualEffects !== 'undefined' && visualEffects.particles
                ? visualEffects.particles.getElementParticleColor(t) : null}
}'''


def parent_palette():
    source = subprocess.check_output(['git', 'show', f'{PARENT}:style.js'], text=True,
                                     cwd=Path(__file__).resolve().parents[1])
    return {key: re.search(rf"{key}: '([^']+)'", source).group(1)
            for key in ('classicTriangleFill', 'classicTriangleStroke')}


def capture(rev, palette=None):
    result = {'frames': {}, 'triangles': {}, 'errors': []}
    with ExitStack() as stack:
        root, result['rev'] = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for vp in snap.VIEWPORTS:
            for mode in ('classic', 'bad'):
                context = browser.new_context(viewport={k: vp[k] for k in ('width', 'height')},
                                              device_scale_factor=vp['dpr'])
                context.add_init_script(SEED_SCRIPT % snap.SEED)
                context.add_init_script(snap.CLOCK_SCRIPT)
                if palette:
                    source = (root / 'style.js').read_text()
                    for key, value in palette.items():
                        source, count = re.subn(rf"{key}: '[^']+'", f"{key}: '{value}'", source)
                        assert count == 1, (key, count)
                    context.route('**/style.js', lambda route:
                                  route.fulfill(body=source, content_type='application/javascript'))
                page = context.new_page()
                page.on('pageerror', lambda e: result['errors'].append(str(e)))
                page.goto(url + 'index.html', wait_until='load')
                snap.boot_frozen(page)
                page.evaluate(snap.SETUP_SCRIPT, [[], False])
                page.evaluate('mode => startGame(mode)', mode)
                for tick in (60, 180, 300):
                    page.evaluate(snap.ADVANCE_SCRIPT, tick)
                    data = snap.png_bytes(page.evaluate('() => __snap.capture()'))
                    result['frames'][(vp['name'], mode, tick)] = np.asarray(Image.open(io.BytesIO(data)).convert('RGB'))
                probe = page.evaluate(ISOLATE)
                data = snap.png_bytes(page.evaluate('() => __snap.capture()'))
                result['triangles'][(vp['name'], mode)] = (Image.open(io.BytesIO(data)).convert('RGB'), probe)
                context.close()
    return result


def hsv(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(float(x) / 255 for x in rgb))
    return [h * 360, s, v]


class ClassicTriangleColorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_palette = parent_palette()
        cls.runs = {'original': capture('e430f92'),
                    'parent': capture('worktree', palette=cls.old_palette),
                    'head': capture('worktree')}
        cls.report = {'revs': {n: r['rev'] for n, r in cls.runs.items()},
                      'parent_palette_source': PARENT, 'parent_palette': cls.old_palette,
                      'page_errors': {n: r['errors'] for n, r in cls.runs.items()},
                      'classic': {}, 'bad_max_channel_delta': {}}
        for vp in snap.VIEWPORTS:
            name = vp['name']
            img, p = cls.runs['head']['triangles'][(name, 'classic')]
            a, d = np.asarray(img), p['density']
            # Fixed positions along the top edge; avoid the pale central core.
            edge = [hsv(a[round((p['top'] + 1) * d), round(x * d)]) for x in (135, 160, 185)]
            fill = hsv(a[round(120 * d), round(160 * d)])
            cls.report['classic'][name] = {'edge_hsv': edge, 'fill_hsv': fill, 'derived_colors': p}
            # The early gameplay frames may contain no triangles. Compare the
            # isolated real bad-mode triangle and its trail explicitly as well.
            head_triangle = np.asarray(cls.runs['head']['triangles'][(name, 'bad')][0]).astype(int)
            parent_triangle = np.asarray(cls.runs['parent']['triangles'][(name, 'bad')][0]).astype(int)
            cls.report['bad_max_channel_delta'][f'{name}-triangle-and-trail'] = int(
                np.abs(head_triangle - parent_triangle).max())
            for tick in (60, 180, 300):
                k = (name, 'bad', tick)
                delta = np.abs(cls.runs['head']['frames'][k].astype(int) - cls.runs['parent']['frames'][k].astype(int))
                cls.report['bad_max_channel_delta'][f'{name}-tick{tick}'] = int(delta.max())
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / 'colors.json').write_text(json.dumps(cls.report, indent=2) + '\n')
        sheet = Image.new('RGB', (900, 440), '#141414')
        draw = ImageDraw.Draw(sheet)
        for col, (label, run) in enumerate(cls.runs.items()):
            sha = run['rev'].removeprefix('worktree@').split('+')[0]
            if label == 'parent':
                label = 'old palette'
            draw.text((col * 300 + 10, 5), f'{label}: {sha[:7]}', fill='white')
            for row, vp in enumerate(snap.VIEWPORTS):
                img, p = run['triangles'][(vp['name'], 'classic')]
                d = p['density']
                tile = img.crop(tuple(round(v * d) for v in (70, 40, 250, 200))).resize((225, 180))
                sheet.paste(tile, (col * 300 + 30, row * 205 + 25))
                draw.text((col * 300 + 10, row * 205 + 205), vp['name'], fill='white')
        sheet.save(EVIDENCE / 'before-after.png')

    def test_classic_pixels(self):
        for name, c in self.report['classic'].items():
            for h, s, v in c['edge_hsv']:
                self.assertTrue(190 <= h <= 205 and .25 <= s <= .7 and v > .75, (name, h, s, v))
            h, s, v = c['fill_hsv']
            self.assertTrue(200 <= h <= 240 and v < .3, (name, h, s, v))
        print('PASS classic edge H 190-205 S .25-.7 V > .75; fill H 200-240 V < .3')

    def test_derived_colors(self):
        for c in self.report['classic'].values():
            for key in ('trail', 'light', 'particle'):
                self.assertEqual(c['derived_colors'][key], '#8fdcff', key)
            self.assertTrue(c['derived_colors']['emitted'])
            self.assertEqual(set(c['derived_colors']['emitted']),
                             {c['derived_colors']['emberColor']})
        print('PASS classic trail/light/particle #8fdcff; emitted embers retain TASK-204 configured color')

    def test_bad_unchanged(self):
        # Prove the control actually uses the historical classic colour, so
        # equal bad-mode pixels cannot pass because both captures are identical.
        for vp in snap.VIEWPORTS:
            control = self.runs['parent']['triangles'][(vp['name'], 'classic')][1]
            self.assertEqual(control['light'], self.old_palette['classicTriangleStroke'])
            self.assertNotEqual(control['light'], '#8fdcff')
        for name, delta in self.report['bad_max_channel_delta'].items():
            self.assertLessEqual(delta, 2, name)
        print('PASS classic-palette isolation: bad-mode triangle/trail and full-frame max channel deltas <= 2:',
              self.report['bad_max_channel_delta'])

    def test_no_page_errors(self):
        self.assertTrue(all(not r['errors'] for r in self.runs.values()), self.report['page_errors'])


if __name__ == '__main__':
    unittest.main()
