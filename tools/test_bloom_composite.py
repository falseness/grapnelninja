"""Bloom must preserve direct additive resampling and the ring exclusion."""
from pathlib import Path
import os
import unittest
from browser_test_support import start_browser_test, wait_for_boot


class BloomCompositeTest(unittest.TestCase):
    def test_direct_reference_pixels_and_restored_state(self):
        url, browser = start_browser_test(Path(os.environ.get('BLOOM_TEST_ROOT', Path(__file__).resolve().parents[1])), self.addCleanup)
        page = browser.new_page()
        self.addCleanup(page.close)
        page.goto(url+'index.html'); wait_for_boot(page)
        result = page.evaluate('''() => {
            startGame('bad');
            const results=[];
            for(const size of [128,197]) for(const clipped of [false,true]) {
                const a=document.createElement('canvas'), b=document.createElement('canvas');
                a.width=b.width=size; a.height=b.height=96;
                const ac=a.getContext('2d'), bc=b.getContext('2d');
                for(const c of [ac,bc]) {
                    c.fillStyle='#19436f'; c.fillRect(0,0,size,96);
                    c.translate(3,5); c.globalAlpha=.7;
                }
                const renderer=new BloomRenderer(ac,a);
                renderer.getConfig=()=>({compositeOperation:'lighter',levelAlphas:[.9,.7,.5,.3],strength:1});
                renderer.levels=[32,16,8,4].map((w,i)=>{
                    const c=document.createElement('canvas');c.width=w;c.height=w;
                    const x=c.getContext('2d');x.fillStyle=['#ff5511','#ffffcc','#cc55ff','#33ddff'][i];
                    x.fillRect(w/3,w/4,w/2,w/2);return {canvas:c,ctx:x};
                });
                const player=clipped?{x:60-screen.x,y:40-screen.y,getRingOuterRadius:()=>9}:null;
                renderer.composite(player);
                bc.save();const world=bc.getTransform();bc.setTransform(1,0,0,1,0,0);
                if(player){bc.beginPath();bc.rect(0,0,size,96);bc.setTransform(world);
                    bc.moveTo(78,40);bc.arc(60,40,18,0,Math.PI*2);bc.clip('evenodd');bc.setTransform(1,0,0,1,0,0);}
                bc.globalCompositeOperation='lighter';bc.imageSmoothingEnabled=true;
                for(let i=0;i<4;i++) {bc.globalAlpha=Math.max(0,Math.min(1,[.9,.7,.5,.3][i]*neonPulse));
                    bc.drawImage(renderer.levels[i].canvas,0,0,size,96);}
                bc.restore();
                const ap=ac.getImageData(0,0,size,96).data,bp=bc.getImageData(0,0,size,96).data;
                let differences=0; for(let i=0;i<ap.length;i++) if(ap[i]!==bp[i]) differences++;
                results.push({size,clipped,differences,state:ac.globalAlpha===.7 && ac.getTransform().e===3
                    && ac.globalCompositeOperation==='source-over'});
            }
            return results;
        }''')
        for row in result:
            self.assertEqual(row['differences'],0,row)
            self.assertTrue(row['state'],row)
        print('PASS bloom additive pixels, saturated colors, resampling, ring exclusion and canvas state:',result)
