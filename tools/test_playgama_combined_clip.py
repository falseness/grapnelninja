"""Execute generated JS and compare coverage with an independent pixel oracle."""
import json
import math
from pathlib import Path
import subprocess
import unittest
from playgama_combined_clip import candidate

ROOT = Path(__file__).resolve().parents[1]
JS = r'''
const vm = require('vm'), fs = require('fs');
const source = fs.readFileSync(0, 'utf8');
function context() {
 const c = {calls: [], stack: [], matrix: {a:1,b:0,c:0,d:1,e:0,f:0}, rects:[],
 save(){this.stack.push({matrix:this.matrix,alpha:this.globalAlpha,blend:this.globalCompositeOperation})},
 restore(){const s=this.stack.pop();this.matrix=s.matrix;this.globalAlpha=s.alpha;this.globalCompositeOperation=s.blend},
 setTransform(...a){this.matrix=a.length===1?a[0]:Object.fromEntries(['a','b','c','d','e','f'].map((k,i)=>[k,a[i]]))},
 getTransform(){return this.matrix}, beginPath(){this.rects=[]}, rect(x,y,w,h){this.rects.push([x,y,x+w,y+h])},
 clip(){this.calls.push({clip:this.rects.slice()})}, drawImage(...a){this.calls.push({draw:a.slice(1), matrix:this.matrix,alpha:this.globalAlpha,blend:this.globalCompositeOperation})},
 fillRect(){},clearRect(){},scale(){},translate(){},moveTo(){},lineTo(){},closePath(){},stroke(){}, createRadialGradient(){return {addColorStop(){}}}};
 return c;
}
const cfg={blurLevels:4,resolutionScale:.5,touchResolutionScale:.5,levelAlphas:[.1,.2,.3,.4],strength:.8,compositeOperation:'lighter'};
const sandbox={console, ctx:context(), neonPulse:.75, bloomPassActive:false,
 STYLE:{ambient:{glow:cfg},lights:{resolutionScale:1,touchResolutionScale:1,worldCompositeAlpha:.3,compositeOperation:'screen',shapeSpread:2.3,colors:{},falloff:[[0,1],[1,0]]},features:{lightmap:true}},
 QUALITY:{lightmap:true},isTouchFirstDevice:()=>false, LOGICAL_VIEWPORT:{width:64,height:48},scale:{classic:1},version:'classic',height:1080,
 visualEffects:{particles:{ctx:context(),moteLayout:[],shouldDrawAmbientMotes:()=>true}},
 document:{createElement:()=>({width:0,height:0,getContext:()=>context()})}};
sandbox.screen={x:0,y:0};
sandbox.STYLE.colors={cube:{blue:'#ffffff'}};
for(const name of ['Rect','Triangle','Trampoline','Ground','Side'])sandbox[name]=class {};
sandbox.getElementCullBox=e=>e.box;
vm.createContext(sandbox);
vm.runInContext(source+'\nthis.A=AmbientGlowRenderer;this.L=LightmapRenderer;',sandbox);
const a=new sandbox.A(context(),{width:64,height:48});a.resize();
const cases=[{name:'overlapping',layout:[1,5.2,6.7,3.4,1,6,7,2],m:[1,0,0,1,0,0]},
{name:'disjoint',layout:[1,2,2,2,1,25,17,2],m:[1,0,0,1,0,0]},
{name:'empty',layout:[],m:[1,0,0,1,0,0]},
{name:'offscreen',layout:[1,-100,-100,2,1,200,200,2],m:[1,0,0,1,0,0]},
{name:'rounding_filter_transform',layout:[1,3.3,4.7,2.6],m:[.8,.3,-.2,1.1,5.7,-1.2]}];
for(const c of cases){
 sandbox.visualEffects.particles.moteLayout=c.layout;a.supportedMotes=true;
 a.renderGlow(...c.m,()=>{});c.support=a.support;c.levels=a.levels.map(l=>[l.canvas.width,l.canvas.height]);
 a.ctx.calls=[];a.composite();c.calls=a.ctx.calls;
}
function check(ok,message){if(!ok)throw Error(message)}
a.supportedMotes=false;a.renderGlow(1,0,0,1,0,0,()=>{});check(a.support===null,'unsupported ambient callback');
a.ctx.calls=[];a.composite();check(a.ctx.calls.filter(c=>c.clip).length===0,'ambient fallback clips');
a.support=[[1]];a.resize();check(a.support===null,'resize reset');
a.drawScreen(()=>{});check(a.support===null && !a.supportedMotes,'frame reset');
a.supportedMotes=true;sandbox.visualEffects.particles.moteLayout=[1,1,1,2];
a.renderGlow(1,0,0,1,0,0,()=>{});cfg.compositeOperation='source-over';a.ctx.calls=[];a.composite();
check(!a.ctx.calls.some(c=>c.clip),'unsupported ambient blend');cfg.compositeOperation='lighter';
const l=new sandbox.L(context(),{width:128,height:96});l.clear();
check(l.clipSupport.length===0 && !l.clipFallback,'light clear reset');
const shape=new sandbox.Rect();shape.box={left:7.4,top:8.6,right:10.1,bottom:12.8};
shape.getPoints=()=>[{x:7.4,y:8.6},{x:10.1,y:8.6},{x:10.1,y:12.8}];shape.getGlowStroke=()=>'#ffffff';
l.drawElementLight(new sandbox.Ground());l.drawElementLight(new sandbox.Side());
check(!l.clipFallback,'known boundary non-emitters must retain clipping');
l.drawElementLight(shape);const emitted=l.clipSupport.slice();
check(emitted.length===1 && emitted[0].join() === '3,4,18,20','sprite rounding/filter padding');
l.clear();l.ctx.calls=[];l.composite();check(l.ctx.calls.length===0,'empty world light');
l.clipSupport=[[5,5,12,12],[8,8,15,15],[30,20,33,24],[-100,-100,-50,-50]];l.hasLights=true;
l.ctx.setTransform(1.5,.2,-.3,1.2,3.2,2.7);l.composite();const lightCalls=l.ctx.calls.slice();
l.ctx.calls=[];l.drawRadialLight(10,10,5,'#ffffff',.5);l.composite();
check(l.clipFallback && l.ctx.calls.filter(c=>c.clip).length===0,'radial fallback');
l.clear();l.drawElementLight({});check(l.clipFallback,'unknown element fallback');
l.clear();l.clipSupport=[[1,1,5,5]];l.hasLights=true;l.drawWorldLights=()=>{};l.ctx.calls=[];l.composite();
check(l.ctx.calls.filter(c=>c.clip).length===0,'unsupported emitter fallback');
l.resize();check(l.clipFallback && l.clipSupport.length===0,'light resize reset');
console.log(JSON.stringify({cases,lightCalls,emitted,checks:'PASS transform/resize/frame reset unsupported/radial emitter fallback'}));
'''


def pixels(rects, width=64, height=48):
    return {(x,y) for x in range(width) for y in range(height)
            if any(l <= x < r and t <= y < b for l,t,r,b in rects)}


def resample(source, sw, sh, dw, dh):
    # Independent inverse-sampling oracle: enumerate destination centers and
    # their four bilinear source texels, including edge clamp.
    result = set()
    for x in range(dw):
        for y in range(dh):
            sx=(x+.5)*sw/dw-.5; sy=(y+.5)*sh/dh-.5
            if any((min(sw-1,max(0,i)),min(sh-1,max(0,j))) in source
                   for i in (math.floor(sx),math.floor(sx)+1)
                   for j in (math.floor(sy),math.floor(sy)+1)):
                result.add((x,y))
    return result


class CombinedSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=(ROOT/'render/effects.js').read_bytes()
        proc=subprocess.run(['node','-e',JS],input=candidate(cls.original),capture_output=True,check=True)
        cls.result=json.loads(proc.stdout)

    def test_independent_pixels_overlapping_disjoint_empty_offscreen_all_four_levels_rounding_filter_padding(self):
        for c in self.result['cases']:
            a,b,cc,d,e,f=c['m']; sw,sh=c['levels'][0]; source=set()
            # Raster oracle scans pixel cells against transformed bounds with
            # one-pixel antialias allowance, independently of candidate padding.
            for j in range(0,len(c['layout']),4):
                _,x,y,s=c['layout'][j:j+4]
                p=[(a*u+cc*v+e,b*u+d*v+f) for u,v in [(x,y),(x+s,y),(x,y+s),(x+s,y+s)]]
                for i in range(sw):
                    for k in range(sh):
                        if i+1>min(q[0] for q in p)-1 and i<max(q[0] for q in p)+1 and k+1>min(q[1] for q in p)-1 and k<max(q[1] for q in p)+1:
                            source.add((i,k))
            self.assertEqual(len(c['support']),4)
            for level,(dw,dh) in enumerate(c['levels']):
                if level: source=resample(source,sw,sh,dw,dh)
                sw,sh=dw,dh
                expected=resample(source,sw,sh,64,48)
                covered=pixels(c['support'][level])
                self.assertTrue(expected <= covered,(c['name'],level,expected-covered))
                if c['name'] in ('empty','offscreen'): self.assertEqual(covered,set())
            print('PASS independent pixel oracle',c['name'],'all four ambient levels rounding/filter padding')

    def test_one_composite_per_level_preserves_full_source_alpha_blending(self):
        for c in self.result['cases']:
            draws=[x for x in c['calls'] if 'draw' in x]
            self.assertEqual(len(draws),4)
            self.assertEqual(len([x for x in c['calls'] if 'clip' in x]),4)
            for i,draw in enumerate(draws):
                self.assertEqual(draw['draw'],[0,0,64,48])
                self.assertEqual(draw['blend'],'lighter')
                self.assertAlmostEqual(draw['alpha'],[.1,.2,.3,.4][i]*.8*.75)
        print('PASS overlapping supports one composite per level; full-source transforms blending alpha')

    def test_light_transform_coverage_single_composite_and_fallback_reset(self):
        calls=self.result['lightCalls']; clips=[x['clip'] for x in calls if 'clip' in x];draws=[x for x in calls if 'draw' in x]
        self.assertEqual(len(clips),1);self.assertEqual(len(draws),1)
        self.assertEqual(draws[0]['draw'],[0,0,64,48]);self.assertEqual(draws[0]['alpha'],.3)
        self.assertEqual(draws[0]['blend'],'screen')
        m=draws[0]['matrix'];covered=pixels(clips[0],128,96)
        for x,y in pixels([[5,5,12,12],[8,8,15,15],[30,20,33,24]]):
            for dx,dy in [(0,0),(1,0),(0,1),(1,1)]:
                px=math.floor(m['a']*(x+dx)+m['c']*(y+dy)+m['e']);py=math.floor(m['b']*(x+dx)+m['d']*(y+dy)+m['f'])
                if 0<=px<128 and 0<=py<96:self.assertIn((px,py),covered)
        print('PASS independent world-light pixel oracle overlapping/disjoint/offscreen transform; one composite')
        print('PASS actual sprite emission rounding/filter padding; empty world-light frame')
        print(self.result['checks'])

    def test_menu_lights_unchanged_and_reproducible_scope(self):
        output=candidate(self.original).decode(); original=self.original.decode()
        # The title-menu lights (drawMenu) were removed with the title menu
        # (TASK-386); the candidate must not bring them back.
        self.assertNotIn('    drawMenu(controls)',original)
        self.assertNotIn('    drawMenu(controls)',output)
        self.assertEqual(candidate(self.original),candidate(self.original))
        print('PASS menu lights absent in source and candidate; reproducible candidate')

if __name__=='__main__':unittest.main(verbosity=2)
