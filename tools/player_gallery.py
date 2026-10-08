"""Compare frozen player rendering independently of unrelated cave/obstacle changes.

The quantitative crop uses the real sampled trail on a common dark backdrop,
with no global bloom in any revision. Full-scene crops alongside it show context.
Phone comparisons normalize the historical DPR 3 backing store to the current
DPR 2 cap; viewport and input remain 844x390, touch, device scale factor 3.
"""
import argparse
from contextlib import ExitStack
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap
from visual_gallery import VIEWPORTS, MODES

CAPTURE = r'''() => {
    const m = ctx.getTransform(), k = scale[version];
    const pts = ninja.track.pos.map(p => m.transformPoint(new DOMPoint((p.x+screen.x)*k,(p.y+screen.y)*k)));
    const ball = m.transformPoint(new DOMPoint((ninja.x+screen.x)*k,(ninja.y+screen.y)*k));
    const pad = 50*canvas.height/1080;
    const box = [Math.floor(Math.min(...pts.map(p=>p.x),ball.x)-pad),
                 Math.floor(Math.min(...pts.map(p=>p.y),ball.y)-pad),
                 Math.ceil(Math.max(...pts.map(p=>p.x),ball.x)+pad),
                 Math.ceil(Math.max(...pts.map(p=>p.y),ball.y)+pad)];
    const scene = canvas.toDataURL();
    ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#12102c';
    ctx.fillRect(0,0,canvas.width,canvas.height);ctx.restore();ctx.save();ctx.scale(k,k);
    visualEffects.playerTrail.drawSmoothPlayerTrail(ninja.track);
    const trail = canvas.toDataURL();
    visualEffects.particles.drawLayer(p=>p.spark);
    ninja.draw();ctx.restore();
    return {box,scene,trail,player:canvas.toDataURL(),points:pts.length,
        sparks:visualEffects.particles.particles.filter(p=>p.spark).length};
}'''


def run(out, parent):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    results={};revs={}
    for label,rev in [('reference','40b2fb1'),('parent',parent),('head','worktree')]:
        with ExitStack() as stack:
            root,sha=export_rev(rev,stack.callback);revs[label]=sha
            url,browser=start_browser_test(root,stack.callback)
            for vp in VIEWPORTS:
                for mode in MODES:
                    context=browser.new_context(viewport={k:vp[k] for k in ('width','height')},device_scale_factor=vp['dpr'],is_mobile=vp['touch'],has_touch=vp['touch'])
                    context.add_init_script(SEED_SCRIPT % snap.SEED);context.add_init_script(snap.CLOCK_SCRIPT)
                    page=context.new_page()
                    # Use the current phone DPR cap in all three revisions.
                    page.add_init_script("Object.defineProperty(window, 'devicePixelRatio', {get: () => 2})" if vp['touch'] else "")
                    page.goto(url);snap.boot_frozen(page)
                    page.evaluate(snap.SETUP_SCRIPT,[snap.input_script(snap.SEED,60,vp['width'],vp['height']),vp['touch']])
                    page.evaluate('mode=>startGame(mode)',mode);page.evaluate(snap.ADVANCE_SCRIPT,60)
                    result=page.evaluate(CAPTURE)
                    for kind in ('scene','trail','player'):
                        result[kind]=Image.open(io.BytesIO(snap.png_bytes(result[kind]))).convert('RGB').crop(result['box'])
                        result[kind].save(out/f'{label}-{vp["name"]}-{mode}-{kind}.png')
                    results[label,vp['name'],mode]=result
                    context.close()
    report={'revs':revs,'tick':60,'method':__doc__,'captures':{}}
    sheet=Image.new('RGB',(1200,4*320),'#12102c');d=ImageDraw.Draw(sheet)
    for row,(vp,mode) in enumerate((v,m) for v in VIEWPORTS for m in MODES):
        key=(vp['name'],mode);ref=results[('reference',)+key]
        a=np.asarray(ref['trail'],dtype=float)
        diffs={}
        for col,label in enumerate(('reference','parent','head')):
            r=results[(label,)+key];assert r['box']==ref['box'], (label,key,r['box'],ref['box']);assert r['points']>2 and r['sparks']>0, (label,key,r['points'],r['sparks'])
            for i,kind in enumerate(('scene','player')):
                tile=r[kind].copy();tile.thumbnail((390,130));sheet.paste(tile,(col*400,row*320+25+i*145))
            d.text((col*400+5,row*320+5),f'{label} {vp["name"]} {mode} tick60 / scene',fill='white')
            d.text((col*400+5,row*320+155),'Player only / common backdrop / no global bloom',fill='white')
            diffs[label]=float(np.abs(np.asarray(r['trail'],dtype=float)-a).mean())
        ratio=diffs['head']/diffs['parent'];report['captures']['-'.join(key)]={'head_vs_reference':diffs['head'],'parent_vs_reference':diffs['parent'],'ratio':ratio,'box':ref['box']}
        print(f'PASS {key}: trail MAD head={diffs["head"]:.6f} parent={diffs["parent"]:.6f} ratio={ratio:.6f} <= 0.25',flush=True)
        assert ratio<=.25
    sheet.save(out/'player-crops.png');(out/'player-diff.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);p.add_argument('--parent',required=True)
    a=p.parse_args();run(a.out,a.parent)
