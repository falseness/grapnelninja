"""Build an isolated bounded player-glow experiment; never edits production.

Use --out with a fresh directory. Original per-level scales and integer origins
are retained, including odd full-surface dimensions. Eligibility is determined
by recorded browser/visual evidence, not by this builder.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

METHODS = r'''
    // Experimental cropped intermediates. Full-grid dimensions remain the
    // authority for transforms; allocated dimensions never set effect scale.
    draw(gameState, shakeOffset)
    {
        if (!this.shouldDraw()) return
        const config = this.getConfig()
        const ratio = isTouchFirstDevice() ? config.touchResolutionScale : config.resolutionScale
        let fw = Math.max(1, Math.floor(this.canvas.width * ratio))
        let fh = Math.max(1, Math.floor(this.canvas.height * ratio))
        const full = []
        for (let i = 0; i < config.blurLevels; ++i) {
            full.push([fw, fh]); fw = Math.max(1, Math.floor(fw / 2)); fh = Math.max(1, Math.floor(fh / 2))
        }
        const sx = full[0][0] / width * scale[version]
        const sy = full[0][1] / height * scale[version]
        const player = gameState.ninja
        let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
        const include = (x, y, radius) => {
            x += shakeOffset.x; y += shakeOffset.y
            left = Math.min(left, (x-radius)*sx); right = Math.max(right, (x+radius)*sx)
            top = Math.min(top, (y-radius)*sy); bottom = Math.max(bottom, (y+radius)*sy)
        }
        include(player.x+screen.x, player.y+screen.y, player.getRingOuterRadius())
        const trail = visualEffects.playerTrail
        if (trail.shouldDraw()) {
            const radius = trail.getRibbonWidth(player.track) * Math.max(1, STYLE.trails.player.headWidthRatio)
            for (const p of player.track.pos) include(p.x+screen.x, p.y+screen.y, radius)
        }
        for (const p of visualEffects.particles.particles) if (p.spark)
            include(p.x+(p.worldAnchored?screen.x:0), p.y+(p.worldAnchored?screen.y:0), p.size)
        // Four texels at the coarsest level cover the bilinear chain and halo.
        const padding = 4 * Math.max(full[0][0]/full.at(-1)[0], full[0][1]/full.at(-1)[1])
        left -= padding; top -= padding; right += padding; bottom += padding
        this.prototypeAllocations = this.prototypeAllocations || 0
        this.prototypeResizes = this.prototypeResizes || 0
        const geometry = []
        for (let i = 0; i < full.length; ++i) {
            const [w,h] = full[i], rx = w/full[0][0], ry = h/full[0][1]
            const x = Math.max(0, Math.min(w-1, Math.floor(left*rx)))
            const y = Math.max(0, Math.min(h-1, Math.floor(top*ry)))
            // Bucket capacity to reuse canvases as the trail moves.
            const cw = Math.max(1, Math.min(w-x, Math.ceil((Math.min(w,Math.ceil(right*rx))-x)/16)*16))
            const ch = Math.max(1, Math.min(h-y, Math.ceil((Math.min(h,Math.ceil(bottom*ry))-y)/16)*16))
            if (!this.levels[i]) {
                const canvas = document.createElement('canvas')
                this.levels[i] = {canvas, ctx:canvas.getContext('2d',{alpha:false})}
                ++this.prototypeAllocations
            }
            const level = this.levels[i]
            if (level.canvas.width !== cw || level.canvas.height !== ch) {
                level.canvas.width = cw; level.canvas.height = ch; ++this.prototypeResizes
            }
            level.origin = [x,y]; level.full = [w,h]
            geometry.push({old:[w,h],new:[cw,ch],origin:[x,y],scale:[rx,ry]})
        }
        this.prototypeGeometry = {levels:geometry, bounds:[left,top,right,bottom],padding,
            sampling:'integer origins on original per-level grids', allocations:this.prototypeAllocations,
            resizes:this.prototypeResizes, shake:shakeOffset, camera:{x:screen.x,y:screen.y}}
        const first = this.levels[0]
        this.renderGlow(sx,0,0,sy,shakeOffset.x*sx-first.origin[0],shakeOffset.y*sy-first.origin[1],this.drawEmissiveShapes,gameState)
        for (let i=1;i<this.levels.length;++i) {
            const a=this.levels[i-1], b=this.levels[i]
            const rx=b.full[0]/a.full[0], ry=b.full[1]/a.full[1]
            b.ctx.setTransform(1,0,0,1,0,0); b.ctx.fillStyle='black'
            b.ctx.fillRect(0,0,b.canvas.width,b.canvas.height)
            b.ctx.drawImage(a.canvas,a.origin[0]*rx-b.origin[0],a.origin[1]*ry-b.origin[1],a.canvas.width*rx,a.canvas.height*ry)
        }
        const context=this.ctx, world=context.getTransform()
        context.save(); context.setTransform(1,0,0,1,0,0)
        context.beginPath(); context.rect(0,0,this.canvas.width,this.canvas.height)
        context.setTransform(world)
        const radius=player.getRingOuterRadius()*config.ringClearanceRatio
        context.moveTo(player.x+screen.x+radius,player.y+screen.y)
        context.arc(player.x+screen.x,player.y+screen.y,radius,0,Math.PI*2)
        context.clip('evenodd'); context.setTransform(1,0,0,1,0,0)
        context.globalCompositeOperation=config.compositeOperation; context.imageSmoothingEnabled=true
        for(let i=0;i<this.levels.length;++i) {
            const l=this.levels[i], rx=this.canvas.width/l.full[0], ry=this.canvas.height/l.full[1]
            context.globalAlpha=Math.max(0,Math.min(1,config.levelAlphas[i]*config.strength*neonPulse))
            context.drawImage(l.canvas,l.origin[0]*rx,l.origin[1]*ry,l.canvas.width*rx,l.canvas.height*ry)
        }
        context.restore()
    }
'''

def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True); p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(); a.out.mkdir(exist_ok=True,parents=True)
    for arm in ('control','candidate'): shutil.copytree(a.source,a.out/arm)
    path=a.out/'candidate/render/effects.js'; before=path.read_text()
    marker='class PlayerGlowRenderer extends BloomRenderer\n{'
    assert before.count(marker)==1
    after=before.replace(marker,marker+METHODS); path.write_text(after)
    (a.out/'candidate.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/render/effects.js',tofile='b/render/effects.js')))
    sources={arm:digest(a.out/arm) for arm in ('control','candidate')}
    (a.out/'source.json').write_text(json.dumps({'base':'TASK-309 accepted-runtime','revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sources':sources,'build_sha256':{k:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest() for k,v in sources.items()}},indent=2)+'\n')
    print('PASS isolated candidate; original scales and integer sampling origins; production untouched')

if __name__=='__main__': main()
