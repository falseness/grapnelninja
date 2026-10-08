"""Labelled factory obstacle inspection, rendered by the full game draw pipeline.

Only this browser probe arranges obstacles and freezes physics. Baseline state
captures remain untouched. Used for parent/HEAD comparison and gallery clips.
"""
import io
from PIL import Image, ImageDraw
from render_snapshot import png_bytes

SETUP = '''mode => {
    startGame(mode)
    screen.x = screen.y = 0
    const z = scale[mode], w = width / z, h = height / z
    const frame = new Frame13ElementsFactory()
    const tall = new RectFactory().create(w * .16, h * .23, w * .065, h * .48)
    const wide = new RectFactory().create(w * .33, h * .24, w * .24, h * .075)
    const green = new HorizontalRectFactory().create(w * .65, h * .75, w * .2, h * .06)[0]
    const triangle = frame.createTriangle({max: h})
    triangle.x = w * .44; triangle.y = h * .6
    const cube = frame.createBlueSquare()
    cube.x = w * .76; cube.y = h * .36
    cube.track = new Empty(); triangle.track = new Empty()
    for (const floor of floors) floor.elements = []
    floors[1].elements = [tall, wide, green, triangle, cube]
    ninja.x = w * .08; ninja.y = h * .5
    ninja.speedX = ninja.speedY = 0
    // Advance past prior effects; rewinding would reactivate old screen shakes.
    window.__dangerInspectionStart = __snap.now + 1000
}'''

STEP = '''ms => {
    __snap.now = __dangerInspectionStart + ms
    draw()
    return __snap.capture()
}'''


def capture(page, mode, out, viewport, frames=12):
    page.evaluate(SETUP, mode)
    images = []
    for index in range(frames):
        native = Image.open(io.BytesIO(png_bytes(page.evaluate(STEP, 1000 + index * 1000 / 15)))).convert('RGB')
        # Explicit label distinguishes arranged inspection from seeded gameplay.
        ImageDraw.Draw(native).text((20, native.height - 24),
                                   f'{mode} | factory danger inspection | physics frozen', fill='white')
        images.append(native)
    name = f'{viewport}-{mode}-danger.png'
    images[0].save(out / name)
    return images, {'file': name, 'frames': frames, 'scene': 'factory danger inspection; physics frozen',
                    'width': images[0].width, 'height': images[0].height}
