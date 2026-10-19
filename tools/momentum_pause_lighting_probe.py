"""Pause screen per mode (TASK-095): layout rects and pixels of a tree.

For 1280x720 (mouse), 844x390 (touch, dpr 2) and 390x844 (mouse,
letterboxed), the same sizes as test_momentum_lighting_switch, each mode
(classic, bad, momentum) is started with startGame(mode), the loop is
stopped and the pause screen drawn once with LAYOUT_PROBE.boxes on (button
and text boxes in CSS px). For the pixels the canvas is first filled black
and the pause screen drawn on it, so the run under the panel (changed by
later tickets) does not enter the comparison; the canvas is saved as PNG,
and once more drawn without the bloom (<size>-<mode>-nobloom.png): the
bloom stays out of the comparison. neonPulse (the title halo's
performance.now() pulse) is pinned to 1.

Usage: python3 momentum_pause_lighting_probe.py ROOT OUT.json PNG_DIR
ROOT is the tree to serve (a worktree for older commits).
"""
import base64
import json
import sys
from pathlib import Path

from browser_test_support import start_browser_test, wait_for_boot_run

SIZES = [
    ('1280x720', {'viewport': {'width': 1280, 'height': 720}}),
    ('844x390', {'viewport': {'width': 844, 'height': 390}, 'device_scale_factor': 2,
                 'has_touch': True, 'is_mobile': True}),
    ('390x844', {'viewport': {'width': 390, 'height': 844}}),
]
MODES = ['classic', 'bad', 'momentum']

PAUSE = '''(mode) => {
    startGame(mode)
    cancelAnimationFrame(game)
    runFixedPhysics = function () {}
    reuseTimeInGame = function () {}
    if (typeof TUTORIAL_HINT != 'undefined') { TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true }
    draw()
    // The title halo pulses on performance.now() (STYLE.ambient): pinned
    neonPulse = 1
    menu.startPause()
    LAYOUT_PROBE.boxes = []
    menu.drawPauseScreen()
    const boxes = LAYOUT_PROBE.boxes
    LAYOUT_PROBE.boxes = null
    const c = ctx.canvas
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, c.width, c.height)
    ctx.restore()
    menu.drawPauseScreen()
    const png = c.toDataURL('image/png')
    // Again without the bloom (blurred on the GPU, not bit-stable run to run)
    const bloom = visualEffects.bloom
    visualEffects.bloom = null
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, c.width, c.height)
    ctx.restore()
    menu.drawPauseScreen()
    visualEffects.bloom = bloom
    return {version, boxes, lighting: typeof MOMENTUM_FX != 'undefined' ? MOMENTUM_FX.enabled : null,
            png, pngNoBloom: c.toDataURL('image/png'), canvas: [c.width, c.height]}
}'''


def main():
    root, out, png_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    png_dir.mkdir(parents=True, exist_ok=True)
    cleanups = []
    url, browser = start_browser_test(root, cleanups.append)
    result = {'root': str(root), 'sizes': {}}
    try:
        for size, options in SIZES:
            result['sizes'][size] = {}
            for mode in MODES:
                context = browser.new_context(locale='en-US', **options)
                try:
                    page = context.new_page()
                    page.goto(url + 'index.html')
                    wait_for_boot_run(page)
                    page.evaluate('document.fonts.ready')
                    shot = page.evaluate(PAUSE, mode)
                finally:
                    context.close()
                png = png_dir / f'{size}-{mode}.png'
                png.write_bytes(base64.b64decode(shot['png'].split(',', 1)[1]))
                (png_dir / f'{size}-{mode}-nobloom.png').write_bytes(
                    base64.b64decode(shot['pngNoBloom'].split(',', 1)[1]))
                seen, buttons, texts = set(), [], []
                for b in shot['boxes']:
                    key = json.dumps(b, sort_keys=True)
                    if key in seen:
                        continue
                    seen.add(key)
                    (buttons if b['kind'] == 'button' else texts).append(b)
                result['sizes'][size][mode] = {
                    'version': shot['version'], 'lighting': shot['lighting'], 'canvas': shot['canvas'],
                    'buttons': buttons, 'texts': texts, 'png': str(png)}
                print(size, mode, len(buttons), 'buttons', [b['name'] for b in buttons], file=sys.stderr)
    finally:
        for cleanup in reversed(cleanups):
            cleanup()
    out.write_text(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
