"""Full-viewport trail evidence using real obstacle physics and the game renderer.

A labelled, fixed gameplay fixture keeps both hazards on screen in each mode.
Only placement, launch velocity and camera are controlled; obstacle move(),
collision, track sampling, draw layers and viewport scale are production code.
The ordinary visual_gallery captures remain the unmodified seeded gameplay run.
"""
import argparse
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot as snap
from visual_gallery import VIEWPORTS, MODES, write_gif

SETUP = r'''mode => {
    startGame(mode);
    screen.x = screen.y = 0;
    const w = width / scale[mode], h = height / scale[mode];
    for (const floor of floors) floor.elements = [];
    const triangle = new Triangle({x:w*.35, y:h*.35, radius:height*.25/Math.sqrt(3),
        yMin:h*.18, yMax:h*.8, fill:STYLE.colors.hazard.fill, stroke:STYLE.colors.hazard.stroke});
    const cube = new JumpingCube({x:w*.64,y:h*.65,width:height*.12,height:height*.12,
        fill:STYLE.colors.cube.blueFill,stroke:STYLE.colors.cube.blueStroke});
    cube.x = w*.64; cube.y = h*.65;
    cube.speedX = 0; cube.speedY = -Math.sqrt(2*GRAVITY*h*.42);
    const platform = new Rect({x:w*.56,y:h*.82,width:w*.3,height:h*.05});
    floors[1].elements = [triangle,cube,platform];
    for (const element of [triangle,cube]) {
        element.track.pos = [];
        if (element === cube) element.track.addPos(cube.x+cube.circle.x,cube.y+cube.circle.y,true);
        else element.track.addPos(triangle.getPoints(),true);
    }
    ninja.x = w*.12; ninja.y = h*.5;
    window.__trailScene = {triangle,cube,tick:0};
    // Newly inserted hazards need the normal first draw to synchronise styles
    // before their first sampled trail (Floor draws tracks before bodies).
    draw();
}'''
STEP = r'''target => {
    const s = __trailScene;
    while (s.tick < target) {
        __snap.now = ++s.tick * 1000/60;
        for (let i=0; i<cyclesPerTick; i++) {
            firstCycleInThisTick = i===0 || i===cyclesPerTick-1;
            s.triangle.move(); s.cube.move();
        }
    }
    draw();
    return {tick:s.tick,triangle:{x:s.triangle.x,y:s.triangle.y,points:s.triangle.track.pos.length},
        cube:{x:s.cube.x,y:s.cube.y,points:s.cube.track.pos.length},
        canvas:[canvas.width,canvas.height],scale:scale[version]};
}'''


def run(rev, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    report = {'seed':snap.SEED, 'scene':__doc__.split('\n\n')[1], 'captures':{}}
    with ExitStack() as stack:
        root, sha = export_rev(rev, stack.callback)
        report['rev'] = sha
        url, browser = start_browser_test(root, stack.callback)
        for vp in VIEWPORTS:
            for mode in MODES:
                context = browser.new_context(viewport={k:vp[k] for k in ('width','height')},
                    device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.add_init_script(SEED_SCRIPT % snap.SEED)
                page.add_init_script(snap.CLOCK_SCRIPT)
                page.goto(url)
                snap.boot_frozen(page)
                page.evaluate(SETUP, mode)
                frames, states = [], []
                ticks = list(range(24, 201, 4))
                name = f'trails-{vp["name"]}-{mode}'
                for tick in ticks:
                    states.append(page.evaluate(STEP, tick))
                    frame = Image.open(io.BytesIO(snap.png_bytes(page.evaluate('() => canvas.toDataURL()')))).convert('RGB')
                    # Preserve aspect ratio and CSS phone size; no enlarged obstacle crops.
                    frame = frame.resize((vp['width'],vp['height']), Image.LANCZOS)
                    ImageDraw.Draw(frame).text((16,80),f'{mode} | fixed gameplay fixture | tick {tick}',fill='white')
                    if tick in (24,112,200):
                        frame.save(out / f'{name}-tick{tick:04d}.png')
                    frames.append(frame.quantize(colors=256,method=Image.MEDIANCUT,dither=Image.NONE))
                assert not errors, errors
                for kind in ('triangle','cube'):
                    assert max(s[kind]['y'] for s in states)-min(s[kind]['y'] for s in states)>20, kind
                    assert all(s[kind]['points']>1 for s in states), kind
                path = out / f'{name}.gif'
                write_gif(frames,path)
                with Image.open(path) as gif:
                    assert gif.n_frames == len(ticks)
                report['captures'][name] = {'viewport':vp,'ticks':ticks,'states':states,
                    'frames':len(frames),'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'page_errors':errors}
                print(f'PASS rev={sha} viewport={vp["name"]} {vp["width"]}x{vp["height"]}@{vp["dpr"]} '
                      f'mode={mode} ticks=24..200 step=4 frames={len(frames)} triangle=moving cube=moving '
                      f'file={path} sha256={report["captures"][name]["sha256"]}',flush=True)
                context.close()
    (out/'trails-manifest.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rev',required=True)
    parser.add_argument('--out',required=True)
    args = parser.parse_args()
    run(args.rev,args.out)
