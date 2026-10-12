"""Prepare an isolated ambient-support clipping experiment; never edit runtime in place.

Conservative rectangles retain full-surface drawImage sampling. This prototype
requires pixel/state and paired performance evidence before any adoption.
"""
import argparse
from pathlib import Path
import shutil

METHODS = r'''
    renderGlow(a, b, c, d, e, f, drawShapes, arg)
    {
        super.renderGlow(a, b, c, d, e, f, drawShapes, arg)
        const layout = visualEffects.particles.moteLayout
        const first = this.levels[0].canvas
        let rectangles = []
        // Include both halo and core, transformed in the original level grid.
        for (let j = 0; j < layout.length; j += 4) {
            const x = layout[j+1], y = layout[j+2], size = layout[j+3]
            const points = [[x,y],[x+size,y],[x,y+size],[x+size,y+size]]
                .map(([x,y]) => [a*x+c*y+e,b*x+d*y+f])
            rectangles.push([
                Math.max(0, Math.floor(Math.min(...points.map(p=>p[0])))-2),
                Math.max(0, Math.floor(Math.min(...points.map(p=>p[1])))-2),
                Math.min(first.width, Math.ceil(Math.max(...points.map(p=>p[0])))+2),
                Math.min(first.height, Math.ceil(Math.max(...points.map(p=>p[1])))+2)])
        }
        rectangles = rectangles.filter(r=>r[2]>r[0] && r[3]>r[1])
        this.support = []
        for (let i = 0; i < this.levels.length; ++i) {
            const target = this.levels[i].canvas
            if (i) {
                const source = this.levels[i-1].canvas
                // Two source texels conservatively cover bilinear support;
                // round outward after every downsample, retaining edge clamp.
                rectangles = rectangles.map(r=>[
                    Math.max(0, Math.floor((r[0]-2)*target.width/source.width)),
                    Math.max(0, Math.floor((r[1]-2)*target.height/source.height)),
                    Math.min(target.width, Math.ceil((r[2]+2)*target.width/source.width)),
                    Math.min(target.height, Math.ceil((r[3]+2)*target.height/source.height))])
            }
            this.support.push(rectangles.map(r=>[
                Math.max(0, Math.floor((r[0]-2)*this.canvas.width/target.width)),
                Math.max(0, Math.floor((r[1]-2)*this.canvas.height/target.height)),
                Math.min(this.canvas.width, Math.ceil((r[2]+2)*this.canvas.width/target.width)),
                Math.min(this.canvas.height, Math.ceil((r[3]+2)*this.canvas.height/target.height))]))
        }
    }
    composite(player)
    {
        // Only drawScreen's ambient-only pass has a proven support envelope.
        if (player || !this.support) return super.composite(player)
        const config = this.getConfig()
        this.ctx.save()
        this.ctx.setTransform(1,0,0,1,0,0)
        this.ctx.globalCompositeOperation = config.compositeOperation
        this.ctx.imageSmoothingEnabled = true
        for (let i = 0; i < this.levels.length; ++i) {
            this.ctx.save()
            this.ctx.beginPath()
            // Nonzero winding makes overlaps a union, with one composite.
            for (const [x,y,r,b] of this.support[i]) this.ctx.rect(x,y,r-x,b-y)
            this.ctx.clip()
            this.ctx.globalAlpha = Math.max(0, Math.min(1, config.levelAlphas[i]*config.strength*neonPulse))
            this.ctx.drawImage(this.levels[i].canvas,0,0,this.canvas.width,this.canvas.height)
            this.ctx.restore()
        }
        this.ctx.restore()
    }
'''


def prepare(source, out, skip_last_level=False):
    assert not out.exists(), 'preserve previous experiments'
    out.mkdir(parents=True)
    for arm in ('control', 'candidate'):
        shutil.copytree(source, out/arm)
    path = out/'candidate/render/effects.js'
    original = path.read_text()
    marker = 'class AmbientGlowRenderer extends BloomRenderer\n{'
    assert original.count(marker) == 1
    path.chmod(0o644)
    methods = METHODS
    if skip_last_level:
        methods = methods.replace(
            '            this.ctx.beginPath()',
            '            if (i < this.levels.length - 1) {\n'
            '            this.ctx.beginPath()')
        methods = methods.replace('            this.ctx.clip()',
                                  '            this.ctx.clip()\n            }')
    path.write_text(original.replace(marker, marker+'\n'+methods))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--skip-last-level', action='store_true',
                        help='Screen clipping only sparse levels; leave final composite unclipped')
    args = parser.parse_args()
    prepare(args.source, args.out, args.skip_last_level)
