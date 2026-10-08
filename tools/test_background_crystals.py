"""Frozen-clock silhouette probes; lit facets and translucent back rows stay lighter."""
import argparse
import colorsys
from contextlib import ExitStack
import json
import hashlib
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'artifacts/TASK-217/crystals.json'

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
    // Mask other foreground objects as well, so facet probes cannot hit UI,
    // ninja, rope or trails.
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
    b.layerCache = {}
    clear(); mode==='menu' ? b.paintMenu() : b.paint()
    const background = ctx.getImageData(0,0,canvas.width,canvas.height)
    const pixel = (data,x,y) => Array.from(data.data.slice((y*data.width+x)*4,(y*data.width+x)*4+3))
    const samples=[]
    const geometry = STYLE.caveLayers || STYLE.backgroundGeometry
    const shift = layer => mode==='menu' ? b.getMenuLayerShift(layer==='far'?1:1.5) :
        b.getLayerShift(w,h,geometry[layer==='far'?'crystals':'nearRocks'])
    const tiles = Object.fromEntries(['far','near'].map(layer => {
        const c=b.layerCache[layer].canvas
        return [layer,c.getContext('2d').getImageData(0,0,c.width,c.height)]
    }))
    const at = (layer,lx,ly) => {
        const d=tiles[layer], sh=shift(layer)
        const x=Math.floor(((lx-sh.x)%w+w)%w*d.width/w), y=Math.floor((ly-sh.y)*d.height/h)
        return y<0 || y>=d.height ? [0,0,0,0] : Array.from(d.data.slice((y*d.width+x)*4,(y*d.width+x)*4+4))
    }
    // Select opaque shadow interiors by tile ownership, before testing final
    // pixels. Far probes use the roof, outside the intentionally magenta floor haze.
    for (const layer of ['far','near']) {
        const target = layer==='far' ? STYLE.colors.background.crystalFrontShadow : STYLE.colors.background.nearShadow
        const match = /^#([0-9a-f]{6})$/i.exec(target)
        if (!match) continue // A translucent regression must fail sample coverage.
        const expected=[0,2,4].map(i=>parseInt(match[1].slice(i,i+2),16))
        let count=0
        for(let ly=25;ly<h*(layer==='far'?.45:.95) && count<12;ly+=17) {
            for(let lx=25;lx<w-25 && count<12;lx+=23) {
                const rgba=at(layer,lx,ly)
                if(rgba[3]!==255 || !expected.every((v,i)=>v===rgba[i])) continue
                // Reject facet boundaries before scaling/interpolation.
                if([-4,4].some(dx=>[-4,4].some(dy=>!expected.every((v,i)=>v===at(layer,lx+dx,ly+dy)[i])))) continue
                if(layer==='far' && at('near',lx,ly)[3]!==0) continue
                const pos=transform.transformPoint({x:lx,y:ly}), x=Math.round(pos.x),y=Math.round(pos.y)
                if(x<3||y<3||x>=canvas.width-3||y>=canvas.height-3) continue
                let covered=false
                for(let dy=-2;dy<=2;dy++) for(let dx=-2;dx<=2;dx++)
                    if(foreground.data[((y+dy)*canvas.width+x+dx)*4+3]) covered=true
                if(covered) continue
                // Light spill, particles and bloom also cover cave pixels; do
                // not mistake their colours for the material's colour.
                if(pixel(full,x,y).some((v,i)=>Math.abs(v-pixel(background,x,y)[i])>1)) continue
                samples.push({layer,x,y,fill:target,rgb:pixel(full,x,y)});count++
            }
        }
    }
    ctx=mainCtx; b.ctx=backgroundCtx
    return {samples}
}'''


def capture(rev, positions=None):
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
                    name = vp['name']+'-'+mode
                    if positions is None:
                        result[name] = page.evaluate(PROBE,mode)
                    else:
                        result[name] = {'samples': page.evaluate("""points => points.map(p => ({...p,
                            rgb:Array.from(ctx.getImageData(p.x,p.y,1,1).data).slice(0,3)}))""",
                            positions[name]['samples'])}
                    if errors:
                        raise AssertionError(errors)
                finally:
                    context.close()
    return rev_id, result



def probe(rev='worktree', out=OUT):
    rev_id, current = capture(rev)
    reference_id, reference = capture('afbc657', current)
    report = {'rev': rev_id, 'reference': reference_id,
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'limits': {'value_max_exclusive': .15, 'hue_min': 235, 'hue_max': 265},
              'captures': {}}
    for name, data in current.items():
        samples = []
        for p in data['samples']:
            h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in p['rgb']))
            samples.append(dict(p, hue=h*360, value=v))
        previous = []
        for p in reference[name]['samples']:
            h, _, v = colorsys.rgb_to_hsv(*(c / 255 for c in p['rgb']))
            previous.append({k: p[k] for k in ('layer', 'x', 'y', 'rgb')})
            previous[-1].update(hue=h*360, value=v)
        report['captures'][name] = {'samples': samples, 'reference_samples': previous}
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2)+'\n')
    return report


def validate(report):
    for name, data in report['captures'].items():
        assert {p['layer'] for p in data['samples']} == {'near', 'far'}, name
        assert len(data['samples']) >= 12, (name, 'insufficient uncovered silhouettes')
        for p in data['samples']:
            assert p['value'] < .15 and 235 <= p['hue'] <= 265, (name, p)


class BackgroundCrystalsTests(unittest.TestCase):
    def test_dark_indigo_silhouettes(self):
        report = probe()
        for name, data in report['captures'].items():
            print(name, json.dumps(data), flush=True)
        validate(report)
        for name, data in report['captures'].items():
            print(f"PASS {name}: {len(data['samples'])} silhouette samples V < 0.15; H 235-265", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rev', default='worktree')
    parser.add_argument('--out', default=str(OUT))
    args = parser.parse_args()
    result = probe(args.rev, args.out)
    validate(result)
    print('PASS dark indigo silhouettes')
