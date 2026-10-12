"""Generate an isolated conservative world-light clipping prototype."""
import argparse
from pathlib import Path
import shutil

SUPPORT = '''        const sx = (x - spread) * toLight
        const sy = (y - spread) * toLight
        this.clipSupport.push([Math.floor(sx) - 2, Math.floor(sy) - 2,
            Math.ceil(sx + sprite.width) + 2, Math.ceil(sy + sprite.height) + 2])
'''

CLIP = '''        // Conservative source padding includes the sprite raster and bilinear
        // footprint. Clip only in integer destination pixels; keep sampling intact.
        const matrix = this.ctx.getTransform()
        const sx = viewWidth / this.lightCanvas.width
        const sy = viewHeight / this.lightCanvas.height
        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        this.ctx.beginPath()
        for (const [left, top, right, bottom] of this.clipSupport) {
            const x0 = Math.max(0, left), y0 = Math.max(0, top)
            const x1 = Math.min(this.lightCanvas.width, right)
            const y1 = Math.min(this.lightCanvas.height, bottom)
            if (x0 >= x1 || y0 >= y1) continue
            const points = [[x0,y0],[x1,y0],[x0,y1],[x1,y1]].map(([x,y]) =>
                [matrix.a*x*sx + matrix.c*y*sy + matrix.e,
                 matrix.b*x*sx + matrix.d*y*sy + matrix.f])
            const l = Math.max(0, Math.floor(Math.min(...points.map(p => p[0]))) - 2)
            const t = Math.max(0, Math.floor(Math.min(...points.map(p => p[1]))) - 2)
            const r = Math.min(this.canvas.width, Math.ceil(Math.max(...points.map(p => p[0]))) + 2)
            const b = Math.min(this.canvas.height, Math.ceil(Math.max(...points.map(p => p[1]))) + 2)
            if (l < r && t < b) this.ctx.rect(l, t, r-l, b-t)
        }
        this.ctx.clip()
        this.ctx.setTransform(matrix)
'''


def prepare(source, out):
    assert not out.exists(), 'preserve earlier experiments'
    shutil.copytree(source, out)
    path = out/'render/effects.js'
    original = path.read_text()
    start = original.index('class LightmapRenderer')
    end = original.index('\nfunction positiveModulo', start)
    light = original[start:end]
    # The world path currently only emits shape sprites; a future radial caller
    # must extend the support collector before using this prototype.
    assert light.count('this.drawRadialLight(') == 0
    clear = '        this.hasLights = false\n'
    assert light.count(clear) == 2
    light = light.replace(clear, clear+'        this.clipSupport = []\n')
    marker = '        this.lightCtx.drawImage(sprite, x - spread, y - spread,\n'
    assert light.count(marker) == 1
    light = light.replace(marker, SUPPORT+marker)
    marker = '        this.ctx.drawImage(this.lightCanvas, 0, 0, viewWidth, viewHeight)'
    assert light.count(marker) == 1
    light = light.replace(marker, CLIP+marker)
    path.chmod(0o644)
    path.write_text(original[:start]+light+original[end:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.out)
    print('PASS generated isolated light clipping prototype')
