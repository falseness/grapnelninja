"""Reproducible hatch comparisons, tracked camera-pan luminance and clip probes."""
from contextlib import ExitStack
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import ROOT, SEED_SCRIPT, export_rev
import render_snapshot as snap
import danger_gallery

VARIANTS = ('thin', 'bold', 'cross', 'chevron')
OUT = ROOT / 'artifacts/TASK-210'
PROBE = '''() => {
    const results = []
    const z = scale[version] * canvas.width / width
    const savedX = screen.x, savedY = screen.y
    ctx.save()
    ctx.setTransform(z, 0, 0, z, 0, 0)
    for (const [w, h] of [[120, 240], [240, 70], [96, 128]]) {
        const rect = new RectFactory().create(60, 60, w, h)
        const variant = STYLE.dangerHatch.variant
        function render(v, pan) {
            STYLE.dangerHatch.variant = v
            screen.x = pan; screen.y = pan * .37
            ctx.clearRect(-1000, -1000, 10000, 10000)
            rect.draw()
            return ctx.getImageData(0, 0, canvas.width, canvas.height).data
        }
        const off = render('off', 0), on = render(variant, 0)
        let outside = 0, sumOn = 0, sumOff = 0, sqOn = 0, sqOff = 0, count = 0
        const margin = Math.min(w,h)*.20 + 6/z
        const left = 60*z, top = 60*z, right = (60+w)*z, bottom = (60+h)*z
        for (let y = Math.floor(top-4); y <= Math.ceil(bottom+4); y++)
            for (let x = Math.floor(left-4); x <= Math.ceil(right+4); x++) {
                const p = (y*canvas.width+x)*4
                if (x+1 < left || x > right || y+1 < top || y > bottom) {
                    for(let c=0;c<4;c++) outside = Math.max(outside, Math.abs(on[p+c]-off[p+c]))
                } else if(x>left+margin*z && x<right-margin*z && y>top+margin*z && y<bottom-margin*z) {
                    const a=(on[p]+on[p+1]+on[p+2])/3, b=(off[p]+off[p+1]+off[p+2])/3
                    sumOn+=a; sumOff+=b; sqOn+=a*a; sqOff+=b*b; count++
                }
            }
        const means=[]
        for(let frame=0;frame<60;frame++) {
            const pan=frame*.43, pixels=render(variant,pan)
            // Fixed world-space interior, translated with the obstacle each frame.
            const x0=Math.round((60+margin+pan)*z), y0=Math.round((60+margin+pan*.37)*z)
            const nw=Math.floor((w-2*margin)*z), nh=Math.floor((h-2*margin)*z)
            let sum=0
            for(let y=y0;y<y0+nh;y++) for(let x=x0;x<x0+nw;x++) {
                const p=(y*canvas.width+x)*4
                sum+=(pixels[p]+pixels[p+1]+pixels[p+2])/3
            }
            means.push(sum/(nw*nh))
        }
        const changes=means.slice(1).map((v,i)=>Math.abs(v-means[i]))
        results.push({width:w,height:h,scale:z,outside_band_max_delta:outside,
            interior_variance_on:sqOn/count-(sumOn/count)**2,
            interior_variance_off:sqOff/count-(sumOff/count)**2,
            frames:60,mean_brightness:means,brightness_changes:changes,
            mean_change:changes.reduce((a,b)=>a+b,0)/changes.length,max_change:Math.max(...changes)})
    }
    ctx.restore(); screen.x=savedX; screen.y=savedY
    return results
}'''


def collect(out=OUT, sheets=False):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    report={}
    with ExitStack() as stack:
        root, rev=export_rev('worktree',stack.callback)
        url,browser=start_browser_test(root,stack.callback)
        for variant in VARIANTS:
            panels=[]; samples={}
            for viewport,w,h,dpr in [('desktop',1920,1080,1),('phone',844,390,3)]:
                context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=dpr,
                                            is_mobile=viewport=='phone',has_touch=viewport=='phone')
                context.add_init_script(SEED_SCRIPT % snap.SEED)
                context.add_init_script(snap.CLOCK_SCRIPT)
                page=context.new_page(); page.goto(url+'index.html',wait_until='load'); snap.boot_frozen(page)
                page.evaluate(snap.SETUP_SCRIPT,[snap.input_script(snap.SEED,900,w,h),False])
                for mode in ('bad','classic'):
                    page.evaluate('v => STYLE.dangerHatch.variant=v',variant)
                    page.evaluate(danger_gallery.SETUP,mode)
                    if sheets:
                        raw=out/'captures'/variant; raw.mkdir(parents=True,exist_ok=True)
                        images,_=danger_gallery.capture(page,mode,raw,viewport,frames=1)
                        im=images[0]; panels.append((f'{viewport} {mode}',im.resize((844,390))))
                        crop=im.crop((int(im.width*.15),int(im.height*.22),int(im.width*.15)+min(180,int(im.width*.085)),int(im.height*.22)+160))
                        panels.append((f'{viewport} {mode} 3x native crop',crop.resize((crop.width*3,crop.height*3))))
                    samples[f'{viewport}-{mode}']=page.evaluate(PROBE)
                    for sample in samples[f'{viewport}-{mode}']:
                        assert all(math.isfinite(v) for v in sample['mean_brightness']), sample
                        assert len(sample['brightness_changes']) == 59
                context.close()
            report[variant]={'rev':rev,'samples':samples}
            if sheets:
                sheet=Image.new('RGB',(1600,4*570),'#101020'); draw=ImageDraw.Draw(sheet)
                for i,(label,im) in enumerate(panels):
                    x=0 if i%2==0 else 850; y=(i//2)*570
                    draw.text((x+5,y+5),variant+' '+label,fill='white'); sheet.paste(im,(x,y+25))
                (out/'variants').mkdir(exist_ok=True); sheet.save(out/'variants'/f'{variant}.png')
                (out/'flicker').mkdir(exist_ok=True)
                (out/'flicker'/f'{variant}.json').write_text(json.dumps(report[variant],indent=2,allow_nan=False)+'\n')
    (out/'hatch-probe.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report

if __name__=='__main__':
    collect(sheets=True)
