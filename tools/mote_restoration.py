"""Historical/full-scene and isolated ambient parity at fixed camera and clock.

The isolated probe calls each revision's own mote and bloom renderers over
black, removing unrelated changes to cave art, obstacles and player styling.
Full-scene pairs retain those differences and are labelled accordingly.
"""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import argparse

from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap
from test_static_background import delta
from visual_gallery import VIEWPORTS, STATE_SCRIPT

REFERENCE = '2ea4347f60cb88cb9c07ce1b814cde7541c715a6'
SAMPLE = r'''([scene, time, isolated, historical]) => {
    __snap.now = time;
    ++drawFrameId;
    if (!isolated) {
        if (scene === 'menu') menu.draw(); else draw();
    } else {
        ctx.save();
        ctx.setTransform(1,0,0,1,0,0);
        ctx.globalAlpha = 1; ctx.fillStyle = 'black';
        ctx.fillRect(0,0,canvas.width,canvas.height);
        ctx.setTransform(canvas.width/LOGICAL_VIEWPORT.width,0,0,
                         canvas.height/LOGICAL_VIEWPORT.height,0,0);
        if (scene !== 'menu') ctx.scale(scale[version],scale[version]);
        if (scene !== 'menu') updateNeonPulse(); else neonPulse = 1;
        const view = scene === 'menu' ? MENU_MOTES_VIEW : undefined;
        visualEffects.particles.drawAmbientMotes(view);
        if (historical) visualEffects.bloom.drawScreen(
            () => visualEffects.particles.drawAmbientMotes(view));
        ctx.restore();
    }
    return __snap.capture();
}'''


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'reference': REFERENCE, 'seed': snap.SEED,
                'times_ms': [375 + 500*i for i in range(11)], 'pairs': {}}
    images = {}
    for label, rev in [('historical-reference', REFERENCE), ('restored', 'worktree')]:
        with ExitStack() as stack:
            root, revision = export_rev(rev, stack.callback)
            manifest[label] = revision
            url, browser = start_browser_test(root, stack.callback)
            for vp in VIEWPORTS:
                for scene in ['bad', 'classic', 'menu']:
                    key = f'{vp["name"]}-{scene}'
                    context = browser.new_context(viewport={k: vp[k] for k in ('width','height')},
                        device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
                    try:
                        context.add_init_script(SEED_SCRIPT % snap.SEED)
                        context.add_init_script(snap.CLOCK_SCRIPT)
                        page = context.new_page()
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(url + 'index.html', wait_until='load')
                        snap.boot_frozen(page)
                        page.evaluate(snap.SETUP_SCRIPT, [[], vp['touch']])
                        page.evaluate('mode => startGame(mode)', 'bad' if scene == 'menu' else scene)
                        if scene == 'menu':
                            page.evaluate('() => { menu.startPause(); menu.backToMenu.click() }')
                        page.evaluate('() => { screen.x = 0; screen.y = 0; ninja.speedX = ninja.speedY = 0 }')
                        states, layouts, sets = [], [], {}
                        for isolated in [False, True]:
                            frames = []
                            for time in manifest['times_ms']:
                                args = [scene,time,isolated,label == 'historical-reference']
                                data = snap.png_bytes(page.evaluate(SAMPLE,args))
                                if isolated:
                                    repeat = snap.png_bytes(page.evaluate(SAMPLE,args))
                                    assert data == repeat, f'{key}: nondeterministic sample'
                                    layouts.append(page.evaluate('() => Array.from(visualEffects.particles.moteLayout)'))
                                else:
                                    states.append(page.evaluate(STATE_SCRIPT))
                                frames.append(data)
                            kind = 'motes' if isolated else 'scene'
                            sets[kind] = frames
                            folder = out / key / label
                            folder.mkdir(parents=True, exist_ok=True)
                            decoded = []
                            for i, data in enumerate(frames):
                                (folder/f'{kind}-{i:02}.png').write_bytes(data)
                                decoded.append(Image.open(io.BytesIO(data)).convert('RGB'))
                            decoded[0].save(folder/f'{kind}.gif',save_all=True,
                                append_images=decoded[1:],duration=500,loop=0)
                        assert not errors, errors
                        assert all(s == states[0] for s in states), f'{key}: moving state'
                        images[(key,label)] = sets
                        record = manifest['pairs'].setdefault(key, {'viewport':vp})
                        record[label] = {'states':states, 'layouts':layouts,'page_errors':errors,
                            'sha256': {f'{kind}-{i:02}.png':hashlib.sha256(data).hexdigest()
                                       for kind, frames in sets.items() for i,data in enumerate(frames)}}
                    finally:
                        context.close()
    for key, record in manifest['pairs'].items():
        a, b = [images[(key,label)] for label in ('historical-reference','restored')]
        assert record['historical-reference']['layouts'] == record['restored']['layouts'], key
        diffs = [delta(x,y) for x,y in zip(a['motes'],b['motes'])]
        assert all(d['max_channel_delta'] == 0 for d in diffs), (key,diffs)
        motion = delta(b['motes'][0], b['motes'][-1])
        assert motion['differing_pixels'] > 0
        record['isolated_parity'] = diffs
        record['motion'] = motion
        for kind in ['scene','motes']:
            frames=[]
            for i in range(11):
                pair=Image.new('RGB',(1280,390),(20,20,20)); d=ImageDraw.Draw(pair)
                for j,label in enumerate(['historical-reference','restored']):
                    im=Image.open(io.BytesIO(images[(key,label)][kind][i])).convert('RGB')
                    im.thumbnail((640,360)); pair.paste(im,(j*640,30))
                    d.text((j*640+8,8),f'{label} | {key} | {kind} | {375+i*500} ms',fill='white')
                frames.append(pair)
            frames[0].save(out/key/f'{kind}-comparison.gif',save_all=True,append_images=frames[1:],duration=500,loop=0)
            sheet=Image.new('RGB',(1280,390*11))
            for i,im in enumerate(frames): sheet.paste(im,(0,390*i))
            sheet.save(out/key/f'{kind}-review.png')
        print(f'PASS {key}: 11 frames / 5000 ms; fixed camera/state; identical layouts; isolated RGBA appearance max delta=0; deterministic repeats; moving pixels={motion["differing_pixels"]}',flush=True)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=Path('artifacts/TASK-208/restoration'))
    run(parser.parse_args().out)
