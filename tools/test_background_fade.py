"""Frozen-clock geometry probes for translucent cave facets and unchanged obstacles.

Luminance is Rec.709 weighted sRGB bytes (0..255), floor 12. Probe each
facet palette at polygon centroids from the renderer's own seeded geometry,
after its actual layer shift. Exclude pixels covered by isolated obstacle
geometry. Obstacle fills and opaque neon edges are compared in complete game
frames at the same coordinates against --parent (default HEAD before a task
commit, HEAD^ after it). No golden images or hard-coded screen coordinates.
"""
import argparse
from contextlib import ExitStack
import json
import hashlib
import os
from pathlib import Path
import subprocess
import unittest

from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'artifacts/TASK-202/probe.json'
FLOOR = 12

PROBE = r'''mode => {
    const b = visualEffects.background, w = LOGICAL_VIEWPORT.width, h = LOGICAL_VIEWPORT.height
    const full = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const transform = ctx.getTransform()
    const mainCtx = ctx, backgroundCtx = b.ctx
    const scratch = document.createElement('canvas')
    scratch.width=canvas.width; scratch.height=canvas.height
    ctx=scratch.getContext('2d'); ctx.setTransform(transform); b.ctx=ctx
    const clear = () => { ctx.save(); ctx.resetTransform(); ctx.clearRect(0,0,canvas.width,canvas.height); ctx.restore() }
    // Only obstacle geometry, preserving the game's actual world transform.
    clear()
    if (mode !== 'menu') {
        ctx.save(); ctx.scale(scale[version], scale[version])
        for (let i=1; i<floors.length-1; i++) floors[i].drawExtrusions()
        for (let i=1; i<floors.length-1; i++) floors[i].draw()
        floors[0].draw(); floors[floors.length-1].draw()
        ctx.restore()
    }
    const obstacles = ctx.getImageData(0,0,canvas.width,canvas.height)
    // Mask other foreground objects as well, so facet probes cannot hit UI,
    // ninja, rope or trails. Keep the obstacle-only mask for edge/fill checks.
    if (mode !== 'menu') {
        ctx.save(); ctx.scale(scale[version],scale[version])
        grapnel.draw(); grapnel.drawHook(); ninja.draw()
        drawPlayerTrailLayer(visualEffects.getGameState())
        drawUILayer(visualEffects.getGameState())
        ctx.restore()
    } else {
        for (const item of [menu.mainText,menu.classicVersionButton,menu.classicRecord,
            menu.badVersionButton,menu.badRecord,menu.mainFpsCounterCheckbox,menu.timeInGame,LANGUAGE_BUTTON]) item.draw()
    }
    const foreground = ctx.getImageData(0,0,canvas.width,canvas.height)
    clear(); b.drawBaseGradient(w,h)
    const gradient = ctx.getImageData(0,0,canvas.width,canvas.height)
    const points = []
    const original = b.getTileTools
    b.getTileTools = function(c,width,seed) {
        const t = original.call(this,c,width,seed), polygon = t.polygon
        t.polygon = (vertices,fill) => {
            const x = vertices.reduce((s,p)=>s+p[0],0)/vertices.length
            const y = vertices.reduce((s,p)=>s+p[1],0)/vertices.length
            const p = c.getTransform().transformPoint({x,y})
            const sx=c.canvas.width/w, sy=c.canvas.height/h
            if (p.x>=0 && p.x<c.canvas.width && p.y>=0 && p.y<c.canvas.height)
                points.push({x:p.x/sx,y:p.y/sy,fill,layer:seed===STYLE.backgroundGeometry.crystals.seed?'far':'near'})
            polygon(vertices,fill)
        }
        return t
    }
    b.layerCache = {}
    clear()
    try { mode==='menu' ? b.paintMenu() : b.paint() }
    finally { b.getTileTools=original }
    const background = ctx.getImageData(0,0,canvas.width,canvas.height)
    const pixel = (data,x,y) => Array.from(data.data.slice((y*data.width+x)*4,(y*data.width+x)*4+3))
    const alpha = (x,y) => obstacles.data[(y*canvas.width+x)*4+3]
    const samples=[], counts={}
    for (const p of points) {
        const shift = mode==='menu' ? b.getMenuLayerShift(p.layer==='far'?1:1.5) :
            b.getLayerShift(w,h,STYLE.backgroundGeometry[p.layer==='far'?'crystals':'nearRocks'])
        const logicalX=((p.x+shift.x)%w+w)%w, logicalY=p.y+shift.y
        const pos=transform.transformPoint({x:logicalX,y:logicalY})
        const x=Math.round(pos.x), y=Math.round(pos.y)
        if(x<3 || y<3 || x>=canvas.width-3 || y>=canvas.height-3) continue
        let covered=false
        for(let dy=-2;dy<=2;dy++) for(let dx=-2;dx<=2;dx++) if(foreground.data[((y+dy)*canvas.width+x+dx)*4+3]>0) covered=true
        if(covered) continue
        const key=p.layer+':'+p.fill
        if((counts[key]||0)>=3) continue
        counts[key]=(counts[key]||0)+1
        samples.push({...p,x,y,rgb:pixel(full,x,y),background_only_rgb:pixel(background,x,y),background_rgb:pixel(gradient,x,y)})
    }
    const obstacleSamples=[]
    for(const kind of ['fill','edge']) {
        let n=0
        for(let y=4;y<canvas.height-4 && n<12;y+=7) for(let x=4;x<canvas.width-4 && n<12;x+=7) {
            const rgb=pixel(obstacles,x,y), bright=Math.max(...rgb)
            if(alpha(x,y)!==255 || (kind==='fill' ? bright>65 : bright<180)) continue
            // Opaque core pixels, not background-dependent antialiasing.
            if(alpha(x-1,y)!==255 || alpha(x+1,y)!==255 || alpha(x,y-1)!==255 || alpha(x,y+1)!==255) continue
            obstacleSamples.push({kind,x,y,rgb:pixel(full,x,y)}); n++
        }
    }
    ctx=mainCtx; b.ctx=backgroundCtx
    return {samples,obstacleSamples}
}'''


def capture(rev):
    result = {}
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for vp in snap.VIEWPORTS:
            for mode in ['menu', 'bad', 'classic']:
                context = browser.new_context(viewport={k:vp[k] for k in ('width','height')},
                                              device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
                try:
                    context.add_init_script(SEED_SCRIPT % snap.SEED)
                    context.add_init_script(snap.CLOCK_SCRIPT)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(url+'index.html', wait_until='load')
                    snap.boot_frozen(page)
                    page.evaluate(snap.SETUP_SCRIPT, [snap.input_script(ticks=300,width=vp['width'],height=vp['height']),vp['touch']])
                    if mode != 'menu':
                        page.evaluate('mode => startGame(mode)',mode)
                        page.evaluate(snap.ADVANCE_SCRIPT,300)
                    else:
                        page.evaluate('() => { __snap.now=5000; menu.draw() }')
                    result[vp['name']+'-'+mode] = page.evaluate(PROBE,mode)
                    if errors:
                        raise AssertionError(errors)
                finally:
                    context.close()
    return rev_id, result


def parent_revision():
    subject = subprocess.check_output(['git','log','-1','--format=%s'],cwd=ROOT,text=True)
    return 'HEAD^' if subject.startswith('TASK-202:') else 'HEAD'


def probe(rev='worktree', parent=None, out=OUT):
    parent = parent or os.environ.get('BACKGROUND_FADE_PARENT') or parent_revision()
    parent_id, before = capture(parent)
    rev_id, after = capture(rev)
    lum = lambda rgb: sum(c*w for c,w in zip(rgb,(0.2126,0.7152,0.0722)))
    report = {'rev':rev_id,'parent':parent_id,
              'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'luminance_definition':'Rec.709 weighted sRGB bytes, range 0..255','captures':{}}
    for name,data in after.items():
        samples=[]
        for p in data['samples']:
            value, bg = lum(p['rgb']), lum(p['background_rgb'])
            samples.append(dict(p,luminance=value,background_luminance=bg,ratio=value/bg,floor=FLOOR))
        old={(p['kind'],p['x'],p['y']):p for p in before[name]['obstacleSamples']}
        obs=[]
        for p in data['obstacleSamples']:
            previous=old[(p['kind'],p['x'],p['y'])]
            obs.append(dict(p,parent_rgb=previous['rgb'],max_delta=max(abs(a-b) for a,b in zip(p['rgb'],previous['rgb']))))
        report['captures'][name]={'samples':samples,'obstacles':obs}
    out=Path(out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
    return report


def validate(report):
    for name,data in report['captures'].items():
        assert {p['layer'] for p in data['samples']}=={'far','near'}, name
        # Low edge rocks can be hidden by gameplay's floor/ceiling. The
        # menu exposes all nine facet palettes; game probes cover both layers.
        minimum = 9 if name.endswith('menu') else 6
        assert len({p['fill'] for p in data['samples']}) >= minimum, (name,'missing facet palettes')
        for p in data['samples']:
            assert p['luminance'] >= p['floor'] and p['ratio'] >= .6, (name,p)
        if not name.endswith('menu'):
            assert {p['kind'] for p in data['obstacles']}=={'fill','edge'}, name
            for p in data['obstacles']:
                assert p['max_delta'] <= 2, (name,p)


class BackgroundFadeTests(unittest.TestCase):
    def test_geometry_luminance_and_parent_obstacles(self):
        report=probe(out=os.environ.get('BACKGROUND_FADE_OUT',OUT))
        validate(report)
        for name,data in report['captures'].items():
            print(f"PASS {name}: {len(data['samples'])} geometry samples ratio >= 0.6, floor >= {FLOOR}; "
                  f"{len(data['obstacles'])} obstacle fill/edge samples max delta <= 2",flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rev',default='worktree')
    parser.add_argument('--parent')
    parser.add_argument('--out',default=str(OUT))
    args=parser.parse_args()
    report=probe(args.rev,args.parent,args.out)
    validate(report)
    print('PASS background luminance ratios >= 0.6, floor >= 12; obstacle deltas <= 2')
