"""TASK-449: runtime camera trajectories and fixed-clock regression proof."""
import hashlib
import json
import math
import unittest

from test_grapple_over_world import Task446Tests
from grapple_over_test_support import ROOT


class Task449Tests(unittest.TestCase):
    TASK = 'TASK-449'
    setUpClass = classmethod(Task446Tests.setUpClass.__func__)
    open = Task446Tests.open

    def test_tracking_and_video(self):
        self.proof['source_hashes']['tools/test_grapple_over_camera.py'] = hashlib.sha256(
            (ROOT / 'tools/test_grapple_over_camera.py').read_bytes()).hexdigest()
        self.evidence.log('CONFIG ' + json.dumps(self.proof, sort_keys=True))
        page = self.open()
        # Record the same deterministic paths in a real rendered canvas.
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720},
            record_video_dir=str(self.evidence.path('video')), record_video_size={'width':1280,'height':720})
        self.addCleanup(context.close)
        video_page = context.new_page()
        from browser_test_support import wait_for_boot
        video_page.goto(self.url)
        wait_for_boot(video_page)
        video_page.evaluate("() => {startGame('grapple_over'); cancelAnimationFrame(game)}")
        setup = '''() => {
            TUTORIAL_HINT.press(version); TUTORIAL_HINT.advance(2500);
            window.rows=[];
            window.sample=(name) => {
                const w=width/scale[version],h=height/scale[version];
                const row={name,world:{...floors[0].level.bounds},player:[ninja.x,ninja.y],
                    velocity:[ninja.speedX,ninja.speedY],camera:[screen.x,screen.y],view:[w,h],radius:ninja.radius};
                rows.push(row); return row;
            };
            window.pathStep=(i) => {
                let name;
                if(i<120) {name='ascent'; ninja.y=980-i*12; ninja.x=360; ninja.speedY=-1.5; ninja.speedX=0}
                else if(i<180) {name='fast fall'; ninja.y=-448+(i-120)*38; ninja.speedY=4.75}
                else if(i<300) {name='reversal'; ninja.y=1794-(i-180)*17; ninja.speedY=-2.125}
                else {name='leftward travel and negative Y'; ninja.x=360-(i-300)*10; ninja.y=-229; ninja.speedX=-1.25; ninja.speedY=0}
                screen.trackGrappleOver(); draw(); return sample(name);
            };
        }'''
        page.evaluate(setup)
        trace = page.evaluate('() => Array.from({length:420},(_,i)=>pathStep(i))')
        video_page.evaluate(setup)
        video_page.evaluate('''async () => {
            for(let i=0;i<420;i+=2) {pathStep(i);pathStep(i+1);await new Promise(r=>setTimeout(r,33))}
        }''')
        video = video_page.video
        context.close()
        video.save_as(str(self.evidence.path('camera.webm')))
        video.delete()
        for row in trace:
            for axis in (0,1):
                p,c,v,r = row['player'][axis],row['camera'][axis],row['view'][axis],row['radius']
                self.assertTrue(all(math.isfinite(n) for n in (p,c,v)))
                self.assertGreaterEqual(p+c, r-1e-8)
                self.assertLessEqual(p+c, v-r+1e-8)
                low,high = (row['world']['left'],row['world']['right']) if axis==0 else (row['world']['top'],row['world']['bottom'])
                self.assertGreaterEqual(c,v-high-1e-8)
                self.assertLessEqual(c,-low+1e-8)
        # A stationary target beyond the dead zone converges monotonically;
        # one tick must match the specified time constant, not a center snap.
        stability = page.evaluate('''() => {
            ninja.x=360;ninja.y=0;ninja.speedX=ninja.speedY=0;screen.x=500;screen.y=0;
            const out=[];for(let i=0;i<180;i++){screen.trackGrappleOver();out.push(screen.y)}
            const before=screen.y; ninja.y=720-screen.y;
            for(let i=0;i<120;i++)screen.trackGrappleOver();
            const deadZone={before,after:screen.y};
            const b=floors[0].level.bounds;
            floors[0].level.bounds={left:0,right:100,top:-100,bottom:100};
            screen.trackGrappleOver();const small=[screen.x,screen.y];floors[0].level.bounds=b;
            return {out,deadZone,small,view:[width/scale[version],height/scale[version]]};
        }''')
        self.assertAlmostEqual(stability['out'][0], 576*(1-math.exp(-(1/60)/.18)))
        self.assertTrue(all(a<=b for a,b in zip(stability['out'],stability['out'][1:])))
        self.assertEqual(stability['deadZone']['before'],stability['deadZone']['after'])
        self.assertEqual(stability['small'],[(stability['view'][0]-100)/2,stability['view'][1]/2])
        lookahead = page.evaluate('''() => [1,100,-1,-100].map(speed=>{
            ninja.x=1000;ninja.y=900;ninja.speedX=ninja.speedY=speed;screen.x=700;screen.y=0;
            screen.trackGrappleOver();return {speed,camera:[screen.x,screen.y]};
        })''')
        for row in lookahead:
            look=max(-288,min(288,row['speed']*480*.15))
            for axis,(pos,size,near,far,offset) in enumerate([(1000,2560,.35,.65,700),(900,1440,.4,.6,0)]):
                target=pos+look+offset
                correction=max(size*near,min(size*far,target))-target
                self.assertAlmostEqual(row['camera'][axis],offset+correction*(1-math.exp(-(1/60)/.18)))
        cadence=json.loads(self.evidence.path('cadence.json').read_text())
        self.evidence.write('camera.json',dict(self.proof,trace=trace,stability=stability,
            lookahead=lookahead,cadence=cadence['cadence'],frame_cadence_identical=True,
            finite_visible_bounded=True,monotone_no_repeated_snap=True))
        print('PASS tracking: 420 samples; ascent, fast fall, reversal, leftward travel, negative Y; finite visible bounded; exponential easing; dead-zone stable; small-world centering')

    def test_fixed_cadence_and_legacy(self):
        page=self.open()
        results=page.evaluate('''() => [30,60,120].map(hz=>{
            startGame('grapple_over');cancelAnimationFrame(game);resetPhysicsTiming();
            ninja.x=1500;ninja.y=-800;ninja.speedX=-.2;ninja.speedY=0;
            screen.trackGrappleOver(true);
            let ticks=0;const states=[];
            for(let i=0;i<=hz*2;i++) {
                ticks+=runFixedPhysics(1000+i*1000/hz);
            }
            return {hz,ticks,player:[ninja.x,ninja.y,ninja.speedX,ninja.speedY],camera:[screen.x,screen.y]};
        })''')
        for row in results[1:]:
            self.assertEqual(row['ticks'],results[0]['ticks'])
            self.assertEqual(row['player'],results[0]['player'])
            self.assertEqual(row['camera'],results[0]['camera'])
        Task446Tests.test_classic_bad_baseline(self)
        path=self.evidence.path('camera.json')
        data=json.loads(path.read_text()) if path.exists() else dict(self.proof)
        data.update(cadence=results,frame_cadence_identical=True,legacy_baseline_equal=True)
        self.evidence.write('cadence.json',data)
        print('PASS cadence: 30/60/120 Hz identical physics and camera; classic/bad baseline equal')
