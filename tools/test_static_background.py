"""Frozen-world background probe: only the clock or camera changes, never physics.

Covers cave, haze, vignette, faded obstacle/menu spill, grade and ambient bloom.
Foreground sprites/trails/UI are omitted. Motes are hidden only for the pixel
assertion; a second pass records their unchanged drift/twinkle for eye review.
Run directly or via unittest; STATIC_BACKGROUND_EVIDENCE_DIR selects the output.
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap

OUT = Path(__file__).resolve().parent.parent / 'artifacts/TASK-208'

PROBE = r'''([scene, time, visible, camera]) => {
    __snap.now = time
    ++drawFrameId
    screen.x = camera[0]; screen.y = camera[1]
    const effects = visualEffects
    const originalMotes = effects.particles.drawAmbientMotes
    if (!visible) effects.particles.drawAmbientMotes = () => {}
    try {
        if (scene === 'menu') {
            // Menu draw() does not update the gameplay neon pulse.
            effects.background.drawMenuBackground()
            effects.lightmap.drawMenu([menu.classicVersionButton, menu.badVersionButton])
            effects.particles.drawAmbientMotes(MENU_MOTES_VIEW)
            effects.colorGrade.draw()
            drawScreenGlow(() => {
                effects.particles.drawAmbientMotes(MENU_MOTES_VIEW)
                menu.mainText.drawGlow()
                menu.classicVersionButton.drawGlow()
                menu.badVersionButton.drawGlow()
                menu.mainFpsCounterCheckbox.drawGlow()
                LANGUAGE_BUTTON.drawGlow()
            })
        } else {
            drawBackgroundLayer()
            ctx.save()
            ctx.scale(scale[version], scale[version])
            updateNeonPulse()
            drawLightsLayer(effects.getGameState())
            effects.particles.drawAmbientMotes()
            // Foreground emission (rope, trail, shocks) is outside this probe.
            effects.bloom.drawScreen(() => effects.particles.drawAmbientMotes())
            drawColorGradeLayer()
            ctx.restore()
        }
        return __snap.capture()
    } finally {
        effects.particles.drawAmbientMotes = originalMotes
    }
}'''


def delta(a, b):
    aa = np.asarray(Image.open(io.BytesIO(a)).convert('RGB'), dtype=np.int16)
    bb = np.asarray(Image.open(io.BytesIO(b)).convert('RGB'), dtype=np.int16)
    diff = np.abs(aa - bb)
    return {'max_channel_delta': int(diff.max()),
            'differing_pixels': int(np.any(diff, axis=2).sum())}


def probe(out=OUT, rev='worktree'):
    out = Path(out)
    frames = out / 'still-frames'
    frames.mkdir(parents=True, exist_ok=True)
    result = {'duration_ms': 5000, 'camera_delta': [160, 80], 'scenes': {}}
    with ExitStack() as stack:
        root, result['rev'] = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for scene in ['bad', 'classic', 'menu']:
            context = browser.new_context(viewport={'width': 844, 'height': 390},
                                          device_scale_factor=3, is_mobile=True, has_touch=True)
            try:
                context.add_init_script(SEED_SCRIPT % snap.SEED)
                context.add_init_script(snap.CLOCK_SCRIPT)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url + 'index.html', wait_until='load')
                snap.boot_frozen(page)
                page.evaluate(snap.SETUP_SCRIPT, [[], True])
                page.evaluate('mode => startGame(mode)', 'bad' if scene == 'menu' else scene)
                if scene == 'menu':
                    page.evaluate('() => { menu.startPause(); menu.backToMenu.click() }')
                camera = page.evaluate('() => [screen.x, screen.y]')

                def capture(time, visible=False, move=False):
                    position = [camera[0] + 160, camera[1] + 80] if move else camera
                    return snap.png_bytes(page.evaluate(PROBE, [scene, time, visible, position]))

                # Nonzero phase also catches a pulse sampled at a sine zero.
                first = capture(375)
                last = capture(5375)
                moved = capture(5375, move=True)
                visible_first = capture(375, visible=True)
                visible_last = capture(5375, visible=True)
                (frames / f'{scene}-first.png').write_bytes(visible_first)
                (frames / f'{scene}-last.png').write_bytes(visible_last)
                # Ten consecutive frozen-camera samples make temporal review possible.
                sequence = [Image.open(io.BytesIO(capture(375 + i * 500, visible=True))).convert('RGB')
                            for i in range(11)]
                sequence[0].save(frames / f'{scene}.gif', save_all=True,
                                 append_images=sequence[1:], duration=500, loop=0)
                result['scenes'][scene] = {
                    'camera': camera, 'fixed': delta(first, last),
                    'moved': delta(last, moved), 'motes_visible': delta(visible_first, visible_last),
                    'page_errors': errors,
                }
            finally:
                context.close()
    (out / 'static.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


class StaticBackgroundTest(unittest.TestCase):
    def test_clock_is_static_camera_moves_and_motes_animate(self):
        result = probe(os.environ.get('STATIC_BACKGROUND_EVIDENCE_DIR', OUT))
        for scene, record in result['scenes'].items():
            with self.subTest(scene=scene):
                self.assertEqual(record['page_errors'], [])
                self.assertLessEqual(record['fixed']['max_channel_delta'], 1)
                self.assertGreater(record['moved']['max_channel_delta'], 0)
                self.assertGreater(record['motes_visible']['differing_pixels'], 0)
                print(f"PASS {scene}: fixed max delta={record['fixed']['max_channel_delta']} <= 1; "
                      f"camera move delta={record['moved']['max_channel_delta']} > 0; "
                      f"motes changed pixels={record['motes_visible']['differing_pixels']} > 0", flush=True)


if __name__ == '__main__':
    unittest.main()
