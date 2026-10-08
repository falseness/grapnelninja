"""Labelled fixed-scene ember inspection; real obstacle/particle draw methods.

The native phone frame uses the game's transform and DPR cap. A separately
labelled 3x crop preserves tiny dim pixels for temporal inspection in GIFs.
Gameplay captures/parallax GIFs remain separate, unchanged evidence.
"""
import io
from PIL import Image, ImageDraw
from render_snapshot import png_bytes

SETUP = r'''mode => {
    startGame(mode); version = mode; screen.x = screen.y = 0;
    __snap.now = 0;
    const z = scale[mode], w = LOGICAL_VIEWPORT.width / z, h = LOGICAL_VIEWPORT.height / z;
    const elements = [
        new Triangle({x:w/2-250/z, y:h/2, radius:65/z,
            yMin:0, yMax:h, stroke:'#ff547f'}),
        new Rect({x:w/2+200/z, y:h/2-50/z, width:100/z, height:100/z, stroke:'#559dff'})
    ];
    window.__emberGallery = {elements, system:new ParticleSystem(ctx,canvas), tick:0};
}'''
STEP = r'''target => {
    const s = __emberGallery;
    while (s.tick < target) {
        __snap.now = ++s.tick * 1000 / 60;
        s.system.update({floors:[{elements:s.elements}]});
    }
    ctx.setTransform(1,0,0,1,0,0); ctx.globalAlpha=1;
    ctx.fillStyle='#14103c'; ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.setTransform(canvas.width/LOGICAL_VIEWPORT.width,0,0,canvas.height/LOGICAL_VIEWPORT.height,0,0);
    ctx.save(); ctx.scale(scale[version],scale[version]);
    for (const e of s.elements) e.draw();
    s.system.draw(); ctx.restore();
    ctx.fillStyle='#e4e4ff'; ctx.font='30px sans-serif';
    ctx.fillText(version+' | fixed ember scene | native game scale | '+(__snap.now/1000).toFixed(2)+' s',40,60);
    return canvas.toDataURL();
}'''


def capture(page, mode, out):
    page.evaluate(SETUP, mode)
    frames, states = [], []
    ticks = list(range(4, 481, 4))
    best, best_score = None, -1
    for tick in ticks:
        native = Image.open(io.BytesIO(png_bytes(page.evaluate(STEP, tick)))).convert('RGB')
        state = page.evaluate('''() => ({tick:__emberGallery.tick, embers:__emberGallery.system.particles.map(p =>
            ({color:p.color, alpha:__emberGallery.system.emberAlpha(p),x:p.x,y:p.y}))})''')
        states.append(state)
        score = min([max([p['alpha'] for p in state['embers'] if p['color']==color] or [0])
                     for color in ('#ff547f','#559dff')])
        if score > best_score:
            best, best_score = native.copy(), score
        panel = Image.new('RGB', (960,720), '#14103c')
        # Full native frame above; individual 3x pixel crops below.
        full = native.copy(); full.thumbnail((960,260)); panel.paste(full,((960-full.width)//2,0))
        factor = native.height / 1080
        for x, label, offset in ((native.width/2-250*factor,'triangle: red/pink',0),
                                 (native.width/2+250*factor,'cube: blue',480)):
            crop = native.crop((round(x-80),round(native.height/2-72),round(x+80),round(native.height/2+72)))
            panel.paste(crop.resize((480,432),Image.NEAREST),(offset,288))
            ImageDraw.Draw(panel).text((offset+12,268),label+' | 3x pixels',fill='white')
        frames.append(panel.quantize(colors=256,method=Image.MEDIANCUT,dither=Image.NONE))
    name = f'phone-{mode}-embers.png'
    best.save(out/name)
    return frames, {'scene':'fixed obstacle inspection, native phone above; labelled 3x crops below',
                    'viewport':'phone','size':[960,720],'fps':15,'frames':120,'ticks':ticks,'states':states,'phone_file':name,
                    'peak_shared_alpha':best_score}
