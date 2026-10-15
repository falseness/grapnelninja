"""Browser pixel and compositing proofs for the acquisition distance guide."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, source_hashes
from perf_mobile import SEED_SCRIPT


class Task453Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-453')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_visuals.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes, browser=cls.browser.version, observations=[])
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, viewport, dpr, mode='grapple_over'):
        context = self.browser.new_context(viewport=viewport, device_scale_factor=dpr)
        self.addCleanup(context.close)
        self.evidence.log('BROWSER_CONTEXT ' + json.dumps(dict(
            test=self.id(), browser=self.browser.version,
            viewport=viewport, dpr=dpr, mode=mode), sort_keys=True))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        return page

    def test_pixels_camera_dpr_and_state(self):
        for viewport in ({'width':1280,'height':720}, {'width':844,'height':390}):
            for dpr in (1,2):
                page = self.open(viewport,dpr)
                for shift in (0,73):
                    row = page.evaluate('''shift => {
                        const original=ctx;
                        // A transparent target lets us measure actual rasterized edges.
                        const probe=document.createElement('canvas');
                        probe.width=canvas.width;probe.height=canvas.height;
                        ctx=probe.getContext('2d');
                        const sx=canvas.width/width*scale[version];
                        const sy=canvas.height/height*scale[version];
                        ctx.setTransform(sx,0,0,sy,0,0);
                        ninja.x=1000; ninja.y=1000;
                        screen.x=width/scale[version]/2-1000+shift;
                        screen.y=height/scale[version]/2-1000-shift/3;
                        const snapshot=()=>JSON.stringify([ctx.globalAlpha,ctx.strokeStyle,
                            ctx.lineWidth,ctx.shadowBlur,ctx.shadowOffsetX,ctx.getLineDash(),
                            ctx.globalCompositeOperation,Array.from(ctx.getTransform().toFloat64Array())]);
                        ctx.globalAlpha=.7;ctx.strokeStyle='#ff0000';ctx.lineWidth=9;
                        ctx.shadowBlur=7;ctx.shadowOffsetX=4;ctx.setLineDash([3,5]);
                        const before=snapshot();drawAcquisitionCircle();const restored=before===snapshot();
                        const cx=(ninja.x+screen.x)*sx,cy=(ninja.y+screen.y)*sy;
                        const R=MODE_DEFINITIONS.grapple_over.acquisitionRadius;
                        const data=ctx.getImageData(0,0,probe.width,probe.height).data;
                        const x=Math.round(cx), hits=[];
                        for(let y=0;y<probe.height;y++) if(data[(y*probe.width+x)*4+3]) hits.push(y);
                        const horizontal=[];
                        for(let xx=0;xx<probe.width;xx++) if(data[(Math.round(cy)*probe.width+xx)*4+3]) horizontal.push(xx);
                        const left=horizontal.filter(xx=>xx<cx),right=horizontal.filter(xx=>xx>cx);
                        const top=hits.filter(y=>y<cy),bottom=hits.filter(y=>y>cy);
                        const middle=a=>a.reduce((s,v)=>s+v,0)/a.length;
                        const observedTop=middle(top)+.5,observedBottom=middle(bottom)+.5;
                        const centerAlpha=data[(Math.round(cy)*probe.width+x)*4+3];
                        // Observe the stroke style on the real context, without replacing its drawing.
                        let style;const stroke=ctx.stroke;
                        ctx.stroke=function(){style={alpha:this.globalAlpha,blur:this.shadowBlur,
                            color:this.strokeStyle,cssWidth:this.lineWidth*sx/(canvas.width/getCanvasCssRect().width)};
                            return stroke.apply(this,arguments)};
                        drawAcquisitionCircle();
                        ctx=original;
                        return {R,restored,centerAlpha,style,expectedCenter:[cx,cy],
                            measuredCenterY:(observedTop+observedBottom)/2,
                            measuredCenterX:(middle(left)+middle(right))/2+.5,
                            measuredRadiusX:(middle(right)-middle(left))/2,expectedRadiusX:R*sx,
                            measuredRadius:(observedBottom-observedTop)/2,expectedRadius:R*sy,
                            topPixels:top.length,bottomPixels:bottom.length};
                    }''',shift)
                    self.assertTrue(row['restored'])
                    self.assertEqual(row['centerAlpha'],0)
                    self.assertLessEqual(abs(row['measuredCenterY']-row['expectedCenter'][1]),1)
                    self.assertLessEqual(abs(row['measuredRadius']-row['expectedRadius']),1)
                    self.assertLessEqual(abs(row['measuredCenterX']-row['expectedCenter'][0]),1)
                    self.assertLessEqual(abs(row['measuredRadiusX']-row['expectedRadiusX']),1)
                    self.assertAlmostEqual(row['style']['cssWidth'],1,places=6)
                    self.assertEqual({k:v for k,v in row['style'].items() if k!='cssWidth'},
                                     dict(alpha=.2,blur=0,color='#00ffff'))
                    row.update(viewport=viewport,dpr=dpr,camera_shift=shift)
                    self.proof['observations'].append(row)
                page.evaluate('draw()')
                page.screenshot(path=str(self.evidence.path(f'screenshots/climb-{viewport["width"]}-dpr{dpr}.png')))
        self.evidence.write('circle.json', self.proof)
        print('PASS pixels: 8 camera/desktop/phone/DPR observations; center and radius within 1 rendered pixel; unfilled cyan alpha 0.20; 1 CSS pixel; no glow; canvas state restored')

    def test_modes_pause_attachment_and_shared_range(self):
        page = self.open({'width':1280,'height':720},1)
        rows=[]
        for mode in ('grapple_over','classic','bad'):
            page.evaluate('m=>{startGame(m);cancelAnimationFrame(game)}',mode)
            row=page.evaluate('''() => {
                const events=[];
                const circle=drawAcquisitionCircle,world=grapnel.draw,player=drawPlayerLayer,ui=drawUILayer;
                let arcs=0;const arc=ctx.arc;
                drawAcquisitionCircle=function(){events.push('circle');
                    ctx.arc=function(){arcs++;return arc.apply(this,arguments)};
                    try{return circle()}finally{ctx.arc=arc}};
                grapnel.draw=function(){events.push('terrain');return world.apply(this,arguments)};
                drawPlayerLayer=function(){events.push('player');return player()};
                drawUILayer=function(s){events.push('hud');return ui(s)};
                draw();
                drawAcquisitionCircle=circle;grapnel.draw=world;drawPlayerLayer=player;drawUILayer=ui;
                return {mode:version,arcs,events};
            }''')
            self.assertEqual(row['arcs'],1 if mode=='grapple_over' else 0)
            self.assertEqual(row['events'],['circle','terrain','player','hud'])
            rows.append(row)
            page.screenshot(path=str(self.evidence.path(f'screenshots/{mode}.png')))
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
        row=page.evaluate('''() => {
            const R=MODE_DEFINITIONS.grapple_over.acquisitionRadius;
            // Real flight clipping must stop at the same radius that is rendered.
            grapnel.throwed=true;grapnel.grappled=false;grapnel.traveled=R-2;
            grapnel.pos=[[ninja.x,ninja.y]];grapnel.speedX=10;grapnel.speedY=0;
            grapnel.move();const traveled=grapnel.traveled;
            const anchor=new Rect({x:ninja.x+R+100,y:ninja.y,width:20,height:20});
            grapnel.pos=[[anchor.x,anchor.y,anchor]];grapnel.grappled=true;
            let radius;const arc=ctx.arc;
            ctx.arc=function(x,y,r){radius=r;return arc.apply(this,arguments)};
            drawAcquisitionCircle();ctx.arc=arc;
            draw();menu.startPause();
            let pausedRadius;ctx.arc=function(x,y,r){pausedRadius=r;return arc.apply(this,arguments)};
            drawAcquisitionCircle();ctx.arc=arc;
            redrawOverlays();
            return {traveled,radius,pausedRadius,paused:menu.gamePaused,
                attached:grapnel.grappled,anchorDistance:Math.hypot(anchor.x-ninja.x,anchor.y-ninja.y)};
        }''')
        self.assertEqual(row['traveled'],row['radius'])
        self.assertEqual(row['pausedRadius'],row['radius'])
        self.assertTrue(row['paused'] and row['attached'])
        self.assertGreater(row['anchorDistance'],row['radius'])
        page.screenshot(path=str(self.evidence.path('screenshots/paused-attached.png')))
        proof_path=self.evidence.path('circle.json')
        proof=json.loads(proof_path.read_text()) if proof_path.exists() else self.proof.copy()
        proof.update(modes=rows,attachment=row)
        self.proof.update(modes=rows,attachment=row)
        self.evidence.write('circle.json',proof)
        print('PASS modes: classic/bad zero circle arcs; world order circle/terrain/player/HUD; attached beyond R and pause visible; rendered radius equals real flight limit')
