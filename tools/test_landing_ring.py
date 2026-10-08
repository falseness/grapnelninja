"""Frozen-clock landing ring geometry, lifecycle and bounce regression."""
import json
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT
from render_snapshot import CLOCK_SCRIPT, boot_frozen, png_bytes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/landing-ring'

PROBE = '''mode => {
    startGame(mode)
    const effect=visualEffects.screenEffects, u=scale[version]
    const surface=new Trampoline({x:0,y:0,points:[
        {x:0,y:0},{x:100,y:0},{x:100,y:20},{x:0,y:20}]})
    const line=lineFormula(0,0,100,0)
    ninja.speedX=2; ninja.speedY=3
    const expected={speedX:2,speedY:3}
    bounceSpeed(expected,line)
    const contact={x:0,y:0,nx:0,ny:-1,approaching:true,line,element:surface}
    ninja.applyBounce(contact)
    const bounce={count:effect.landings.length,speedX:ninja.speedX,
        speedY:ninja.speedY,expected,position:[ninja.x,ninja.y],
        expectedY:-(ninja.radius+GAMEPLAY.cubeContactEpsilon)}
    ninja.applyBounce({...contact,approaching:false})
    bounce.afterSeparating=effect.landings.length
    const scratch=document.createElement('canvas'); scratch.width=scratch.height=256
    const c=scratch.getContext('2d'), ring=new ScreenEffects(c)
    const oldScreen={x:screen.x,y:screen.y}
    const rows=[]
    try {
        screen.x=screen.y=0
        for(const [name,nx,ny] of [['floor',0,-1],['ceiling',0,1],['wall',1,0],['slope',Math.SQRT1_2,-Math.SQRT1_2]]) {
            ring.landings=[]; ring.triggerLanding({x:0,y:0,nx,ny})
            const start=performance.now()
            for(const ms of [0,80,200,280]) {
                c.setTransform(1,0,0,1,0,0); c.clearRect(0,0,256,256)
                c.setTransform(u,0,0,u,128,128)
                ring.drawLandings(start+ms)
                const pixels=c.getImageData(0,0,256,256).data
                let count=0,inside=0,maxAlpha=0,maxRadius=0
                for(let y=0;y<256;y++) for(let x=0;x<256;x++) {
                    const a=pixels[(y*256+x)*4+3]
                    if(a>5) {
                        count++; maxAlpha=Math.max(maxAlpha,a)
                        if((x+.5-128)*nx+(y+.5-128)*ny < -1) inside++
                        maxRadius=Math.max(maxRadius,Math.hypot(x+.5-128,y+.5-128))
                    }
                }
                rows.push({name,ms,count,inside,maxAlpha,maxRadius})
            }
        }
        for(let i=0;i<20;i++) ring.triggerLanding(contact)
        const capped=ring.landings.length
        ring.drawLandings(performance.now()+280)
        return {bounce,rows,capped,cap:STYLE.screenEffects.landingMaxCount,
            remaining:ring.landings.length,shakeUntil:effect.shakeUntil}
    } finally {screen.x=oldScreen.x;screen.y=oldScreen.y}
}'''


class LandingRingTests(unittest.TestCase):
    def test_contact_ring(self):
        OUT.mkdir(parents=True, exist_ok=True)
        url, browser = start_browser_test(ROOT, self.addCleanup)
        results = {}
        for name, w, h, dpr in [('desktop',1920,1080,1),('phone',844,390,3)]:
            for mode in ['bad','classic']:
                context = browser.new_context(viewport={'width':w,'height':h},
                    device_scale_factor=dpr, is_mobile=dpr==3, has_touch=dpr==3)
                try:
                    context.add_init_script(SEED_SCRIPT % 1)
                    context.add_init_script(CLOCK_SCRIPT)
                    page = context.new_page()
                    errors=[]
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(url); boot_frozen(page)
                    result=page.evaluate(PROBE, mode)
                    results[f'{name}-{mode}']=result
                    b=result['bounce']
                    self.assertEqual(b['count'],1)
                    self.assertEqual(b['afterSeparating'],1)
                    self.assertEqual(b['speedX'],b['expected']['speedX'])
                    self.assertEqual(b['speedY'],b['expected']['speedY'])
                    self.assertEqual(b['position'],[0,b['expectedY']])
                    self.assertEqual(result['capped'],result['cap'])
                    self.assertEqual(result['remaining'],0)
                    self.assertEqual(result['shakeUntil'],0)
                    for kind in ['floor','ceiling','wall','slope']:
                        rows=[r for r in result['rows'] if r['name']==kind]
                        self.assertTrue(all(r['count']>0 for r in rows[:3]), rows)
                        self.assertTrue(all(r['inside']==0 for r in rows), rows)
                        self.assertEqual(rows[-1]['count'],0)
                        self.assertLess(rows[0]['maxRadius'],rows[1]['maxRadius'])
                        self.assertLess(rows[1]['maxRadius'],rows[2]['maxRadius'])
                        self.assertGreater(rows[0]['maxAlpha'],rows[2]['maxAlpha'])
                    # Real layer order and full-scene visual evidence, with a
                    # real collision on a visible, safe trampoline fixture.
                    data=page.evaluate('''() => {
                        startGame(version)
                        const e=visualEffects.screenEffects
                        const resetCount=e.landings.length
                        visualEffects.particles.particles=[]
                        const u=scale[version], top=ninja.y+ninja.radius
                        floors[1].elements=[new Trampoline({x:ninja.x-60/u,y:top,
                            points:[{x:0,y:0},{x:120/u,y:0},{x:120/u,y:25/u},{x:0,y:25/u}]})]
                        ninja.y=top-ninja.radius+ninja.radius*.05
                        ninja.speedX=0; ninja.speedY=1
                        ninja.collision()
                        const landingCount=e.landings.length
                        __snap.now+=80
                        const order=[]
                        const oldWorld=drawWorldLayer,oldPlayer=drawPlayerLayer,oldRing=e.drawLandings
                        drawWorldLayer=function(...a){order.push('world');return oldWorld(...a)}
                        drawPlayerLayer=function(...a){order.push('player');return oldPlayer(...a)}
                        e.drawLandings=function(...a){order.push('ring');return oldRing.apply(this,a)}
                        try {draw()} finally {drawWorldLayer=oldWorld;drawPlayerLayer=oldPlayer;e.drawLandings=oldRing}
                        return {order,landingCount,resetCount,png:canvas.toDataURL()}
                    }''')
                    self.assertEqual(data['order'],['world','ring','player'])
                    self.assertEqual(data['landingCount'],1,(name,mode))
                    self.assertEqual(data['resetCount'],0)
                    (OUT/f'{name}-{mode}.png').write_bytes(png_bytes(data['png']))
                    self.assertFalse(errors)
                finally:
                    context.close()
        (OUT/'probe.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__ == '__main__':
    unittest.main()
