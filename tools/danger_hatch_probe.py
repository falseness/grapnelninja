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


def collect(out=OUT, sheets=False, revision="worktree"):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    report={}
    with ExitStack() as stack:
        root, rev=export_rev(revision,stack.callback)
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

# The motion fixture calls production draw methods, with physics/time frozen.
# Moving classes get a prescribed displacement, not a physics-dependent bounce.
MOTION_SETUP = r'''mode => {
    startGame(mode); screen.x=screen.y=0;
    const z=scale[version]*canvas.width/width, W=canvas.width/z, H=canvas.height/z;
    const rect=new RectFactory().create(W*.16,H*.35,W*.18,H*.3);
    const cube=new JumpingCube({x:W*.45,y:H*.35,width:W*.14,height:H*.3,
        stroke:STYLE.colors.cube.blueStroke,speedX:0,speedY:0});
    cube.x=W*.45;cube.y=H*.35;cube.track=new Empty();
    const tri=new Triangle({x:W*.77,y:H*.47,radius:H*.24,
        stroke:STYLE.colors.hazard.stroke,yMin:0,yMax:H});tri.track=new Empty();
    const objects=mode==='bad'?[rect,cube,tri]:[rect];
    const regions={danger_rect:[(rect.x+rect.width*.35)*z,(rect.y+rect.height*.35)*z,
        rect.width*.3*z,rect.height*.3*z]};
    if(mode==='bad') {
        regions.moving_cube=[(cube.x+cube.width*.35)*z,(cube.y+cube.height*.35)*z,cube.width*.3*z,cube.height*.3*z];
        regions.triangle=[(tri.x-tri.radius*.12)*z,(tri.y-tri.radius*.05)*z,tri.radius*.24*z,tri.radius*.2*z];
    }
    const strips=mode==='classic'?[floors[0],floors[floors.length-1]]:[];
    const joins=[];
    for(const [i,f] of strips.entries()) {
        // Recenter a real generated segment join in the viewport.
        const shift=W*.5-f.elements[0].getRightPointX();
        for(const e of f.elements)e.x+=shift;
        const b=f.getContinuousSurfaceBounds();
        const seam=f.elements[0].getRightPointX();
        if(seam===undefined)throw Error('No visible floor join');
        const inset=Math.max(STYLE.strokes.neonGlowWidth,(b.bottom-b.top)*.20);
        const top=Math.max(4/z,b.top+inset+3/z),bottom=Math.min(H-20/z,b.bottom-inset-3/z);
        if(bottom<=top)throw Error('No boundary interior');
        regions[i===0?'ceiling_join':'floor_join']=[seam*z-24,top*z,48,(bottom-top)*z];
        joins.push({seam,bounds:b});
    }
    window.__motion={z,objects,strips,regions,previous:{},origins:objects.map(o=>[o.x,o.y])};
    return {backing:[canvas.width,canvas.height],logical:[width,height],effective_backing_scale:z,
        regions,joins,classes:Object.keys(regions)};
}'''
MOTION_FRAME = r'''([frame,trajectory,variant]) => {
    const {z,objects,strips,origins}=__motion;
    const dx=trajectory==='static'?0:frame*.25,dy=trajectory==='diagonal'?frame*.25:0;
    STYLE.dangerHatch.variant=variant;screen.x=dx/z;screen.y=dy/z;
    // Camera supplies half the net displacement for moving hazards; the other
    // half comes from object movement. Rectangles and joins use camera alone.
    if(version==='bad')for(let i=1;i<objects.length;i++) {
        objects[i].x=origins[i][0]+dx/(2*z);objects[i].y=origins[i][1]+dy/(2*z);
    }
    ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#101020';
    ctx.fillRect(0,0,canvas.width,canvas.height);ctx.setTransform(z,0,0,z,0,0);
    for(const f of strips)f.draw();
    for(let i=0;i<objects.length;i++) {
        if(i>0){screen.x=dx/(2*z);screen.y=dy/(2*z);}
        objects[i].draw();
    }
    ctx.restore();
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data, errors={};
    for(const [name,[x,y,w,h]] of Object.entries(__motion.regions)) {
        const samples=[];
        for(let yy=Math.ceil(y);yy<Math.floor(y+h);yy++)
            for(let xx=Math.ceil(x);xx<Math.floor(x+w);xx++) {
                const sx=xx+dx,sy=yy+dy,ix=Math.floor(sx),iy=Math.floor(sy),fx=sx-ix,fy=sy-iy;
                if(ix<0||iy<0||ix+1>=canvas.width||iy+1>=canvas.height)throw Error('ROI outside canvas');
                const a=(iy*canvas.width+ix)*4,b=a+4,c=a+canvas.width*4,d=c+4;
                for(let k=0;k<3;k++) samples.push(
                    (pixels[a+k]*(1-fx)+pixels[b+k]*fx)*(1-fy)+
                    (pixels[c+k]*(1-fx)+pixels[d+k]*fx)*fy);
            }
        if(!samples.length)throw Error('Empty ROI');
        const previous=__motion.previous[name];
        errors[name]=previous?samples.reduce((sum,v,i)=>sum+Math.abs(v-previous[i]),0)/samples.length:0;
        __motion.previous[name]=samples;
    }
    return {png:canvas.toDataURL('image/png'),errors};
}'''


def collect_motion(revision, out):
    import hashlib
    import shutil
    import subprocess
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    base=subprocess.check_output(['git','rev-parse', 'HEAD' if revision=='worktree' else revision],text=True).strip()
    # A worktree capture can name an immutable runtime only if runtime files match HEAD.
    runtime=[p for p in subprocess.check_output(['git','ls-files'],text=True).splitlines()
             if p.endswith(('.js','.html','.css','.svg')) and not p.startswith('tools/')]
    if revision=='worktree':
        subprocess.run(['git','diff','--exit-code',base,'--',*runtime],check=True)
    (out/'BASE_REV').write_text(base+'\n')
    manifest={'BASE_REV':base,'requested_rev':revision,'seed':snap.SEED,'cases':{},
              'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'fixture':'production object/floor draw methods on solid background; frozen time; prescribed hazard movement',
              'trajectory':'net x=0.25 backing px/frame; diagonal y=0.25; static zero. Moving hazards: half object, half camera.',
              'fps':30}
    motion={'registration':'Fixed bilinear RGB sampling at frame-zero interior pixel centers + known displacement. Adjacent registered frame RGB MAE (0..255), float64 rounded to 9 decimals. Excludes clipped edges; no brightness averaging. Resampling itself contributes error: this diagnoses temporal instability, not its cause.',
            'numeric_precision':1e-9,'cases':{}}
    with ExitStack() as stack:
        root,resolved=export_rev(revision,stack.callback)
        url,browser=start_browser_test(root,stack.callback)
        manifest.update(resolved_rev=resolved,browser=browser.version)
        for viewport,w,h,dpr in [('desktop',1920,1080,1),('phone',844,390,3)]:
            context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=dpr,
                                        is_mobile=viewport=='phone',has_touch=viewport=='phone')
            context.add_init_script(SEED_SCRIPT % snap.SEED);context.add_init_script(snap.CLOCK_SCRIPT)
            page=context.new_page();page.goto(url+'index.html',wait_until='load');snap.boot_frozen(page)
            for mode in ('bad','classic'):
                for variant in VARIANTS:
                    for trajectory in ('static','horizontal','diagonal'):
                        case=f'{viewport}-{mode}-{variant}-{trajectory}'
                        meta=page.evaluate(MOTION_SETUP,mode)
                        folder=out/'frames'/case;folder.mkdir(parents=True,exist_ok=True)
                        clip=out/'clips'/f'{case}.mp4';clip.parent.mkdir(exist_ok=True)
                        command=[ffmpeg,'-y','-loglevel','error','-framerate','30','-i',str(folder/'%03d.png'),
                                 '-c:v','libx264','-threads','2','-preset','ultrafast','-crf','0','-pix_fmt','yuv444p',str(clip)]
                        errors={name:[] for name in meta['regions']};previous={}; hashes=[]
                        for batch in range(0,60,10):
                            captured=page.evaluate('(p) => Array.from({length:10}, (_,i) => ('+MOTION_FRAME+')([p[0]+i,p[1],p[2]]))', [batch,trajectory,variant])
                            for offset,result in enumerate(captured):
                                frame=batch+offset
                                data=snap.png_bytes(result['png'])
                                (folder/f'{frame:03d}.png').write_bytes(data)
                                hashes.append(hashlib.sha256(data).hexdigest())
                                if frame:
                                    for name,value in result['errors'].items():errors[name].append(round(value,9))
                        subprocess.run(command,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                        entry={**meta,'viewport':[w,h],'DPR':dpr,'mode':mode,'variant':variant,
                               'trajectory':trajectory,'frames':60,'frame_sha256':hashes,
                               'clip':str(clip.relative_to(out)),'encoder_command':command,'encoder_exit':0}
                        manifest['cases'][case]=entry
                        motion['cases'][case]={name:{'region_frame_zero':meta['regions'][name],
                            'per_frame_errors':[0.0]+values,'mean_absolute_temporal_error':round(sum(values)/59,9)}
                            for name,values in errors.items()}
                        assert all(math.isfinite(v) for values in errors.values() for v in values)
                        if trajectory=='static':assert all(v==0 for values in errors.values() for v in values)
                        print(f'PASS {case}: 60 frames; '+', '.join(f'{n} MAE={sum(v)/59:.9f}' for n,v in errors.items()),flush=True)
            context.close()
    for name,data in [('manifest',manifest),('motion',motion)]:
        (out/f'{name}.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    print(f'PASS coverage: {len(manifest["cases"])} cases; BASE_REV={base}',flush=True)
    return manifest


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rev',default='worktree')
    parser.add_argument('--out',type=Path,default=OUT)
    parser.add_argument('--motion',action='store_true')
    args=parser.parse_args()
    if args.motion:collect_motion(args.rev,args.out)
    else:collect(args.out,sheets=True,revision=args.rev)
